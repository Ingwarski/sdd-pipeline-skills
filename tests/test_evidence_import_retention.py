"""Imported policy decisions never mutate original evidence identities or claim bindings."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

import test_evidence_importer as fixtures
from evidence.identity import same_reference, reference_identity
from evidence.io import EvidenceError
from evidence.manager import Manager
from evidence.resolver import EvidenceResolver

SEALED = datetime.fromisoformat(fixtures.SEALED.replace("Z", "+00:00"))


class ImportedRetentionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EvidenceImporterTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manager = self.fixture.manager

    def import_refs(self, dependency=False):
        mapping = self.fixture.mapping
        if dependency:
            parent = deepcopy(self.fixture.file)
            parent.update(artifact_id="synthetic-parent-attachment", original_path="recovery/parent.bundle")
            mapping["files"].append(parent)
            prerequisite = self.fixture.normalized()[0][0]
            parent["dependencies"] = [prerequisite]
        return self.manager.import_archive(mapping)

    def actions(self, manager=None, **extra):
        return (manager or self.manager).cleanup(now=SEALED + timedelta(days=30), dry_run=True,
            expire=True, reference_snapshot_complete=True, **extra)

    def test_exported_reference_survives_acknowledgement_without_any_identity_change(self):
        ref = self.import_refs()[0]
        original = deepcopy(ref)
        acknowledged = self.manager.establish_import_retention([ref["artifact_id"]])
        self.assertEqual([original], acknowledged)
        self.assertEqual(original, ref)
        catalog = self.manager._catalog()
        self.assertEqual(original, catalog["refs"][ref["artifact_id"]])
        self.assertFalse(ref["retention"]["migration_policy_established"])
        decision = catalog["import_retention_decisions"][ref["artifact_id"]]
        self.assertEqual(30, decision["days"])
        self.assertEqual("local", decision["provider"])
        self.assertNotEqual(ref["retention"]["sealed_at"], decision["decided_at"])
        prepared = self.manager.prepare([original])
        self.assertEqual(self.fixture.payload, EvidenceResolver(prepared).resolve(original).read_bytes())
        self.assertTrue(any(a.get("artifact_id") == ref["artifact_id"] and a["action"] == "retire" for a in self.actions()))
        sequence = self.manager._catalog()["sequence"]
        self.manager.establish_import_retention([ref["artifact_id"], ref["artifact_id"]])
        self.assertEqual(sequence, self.manager._catalog()["sequence"])

    def test_parent_embedded_dependency_survives_child_policy_acknowledgement(self):
        child, parent = self.import_refs(dependency=True)
        original_parent = deepcopy(parent)
        original_child = deepcopy(child)
        self.manager.establish_import_retention([child["artifact_id"]])
        prepared = self.manager.prepare([original_parent])
        resolver = EvidenceResolver(prepared)
        resolver.resolve(original_parent)
        self.assertIn(child["artifact_id"], resolver.visited)
        self.assertEqual(original_child, original_parent["dependencies"][0])
        self.assertEqual(original_parent, self.manager._catalog()["refs"][parent["artifact_id"]])
        protected = {a["artifact_id"]: a for a in self.actions() if a["action"] == "expired-but-protected"}
        self.assertIn("imported-migration-policy-pending", protected[parent["artifact_id"]]["reasons"])
        self.assertIn("current-claim-or-prerequisite", protected[child["artifact_id"]]["reasons"])
        self.assertNotIn("imported-migration-policy-pending", protected[child["artifact_id"]]["reasons"])

    def test_cold_recovery_keeps_administrative_decision_and_original_age(self):
        ref = self.import_refs()[0]
        self.manager.establish_import_retention([ref["artifact_id"]])
        original_catalog = self.manager._catalog()
        cold = Manager(fixtures.RecordingLocalTransport(self.fixture.base / "durable"), self.fixture.base / "cold-retention", self.fixture.policy)
        catalog = cold._catalog()
        self.assertEqual(original_catalog["import_retention_decisions"], catalog["import_retention_decisions"])
        self.assertEqual(ref, catalog["refs"][ref["artifact_id"]])
        self.assertEqual(fixtures.SEALED, catalog["refs"][ref["artifact_id"]]["retention"]["sealed_at"])
        prepared = cold.prepare([ref])
        self.assertEqual(self.fixture.payload, EvidenceResolver(prepared).resolve(ref).read_bytes())
        # A recovered administrative decision grants no coordinator/pruning authority.
        with self.assertRaisesRegex(EvidenceError, "coordinator authority"):
            self.actions(cold)

    def test_supplied_legacy_flag_cannot_establish_pruning_authority(self):
        ref = self.import_refs()[0]
        caller = deepcopy(ref)
        caller["retention"]["migration_policy_established"] = True
        self.manager.prepare([caller])
        self.assertFalse(self.manager._catalog()["refs"][ref["artifact_id"]]["retention"]["migration_policy_established"])
        actions = self.actions()
        self.assertEqual("expired-but-protected", actions[0]["action"])
        self.assertIn("imported-migration-policy-pending", actions[0]["reasons"])
        self.assertFalse(self.manager._catalog()["import_retention_decisions"])

    def test_old_updated_refs_catalog_recovers_parent_child_without_rebinding(self):
        child, parent = self.import_refs(dependency=True)
        updated = deepcopy(child)
        updated["retention"]["migration_policy_established"] = True
        self.manager._publish(self.manager._catalog(mutation=True), {"version": 1, "updated_refs": [updated]})
        catalog = self.manager._catalog()
        self.assertEqual(child, catalog["refs"][child["artifact_id"]])
        self.assertEqual(parent, catalog["refs"][parent["artifact_id"]])
        self.assertEqual({"version": 1, "legacy": True}, catalog["import_retention_decisions"][child["artifact_id"]])
        cold = Manager(fixtures.RecordingLocalTransport(self.fixture.base / "durable"), self.fixture.base / "legacy-cold", self.fixture.policy)
        prepared = cold.prepare([parent])
        resolver = EvidenceResolver(prepared)
        resolver.resolve(parent)
        resolver.resolve(updated)
        self.assertEqual({"version": 1, "legacy": True}, cold._catalog()["import_retention_decisions"][child["artifact_id"]])
        self.assertEqual(fixtures.SEALED, child["retention"]["sealed_at"])

    def test_mixed_false_true_references_match_receipts_in_one_resolver_invocation(self):
        child, parent = self.import_refs(dependency=True)
        legacy = deepcopy(parent)
        legacy["retention"]["migration_policy_established"] = True
        legacy["dependencies"][0]["retention"]["migration_policy_established"] = True
        prepared = self.manager.prepare([legacy])
        resolver = EvidenceResolver(prepared)
        resolver.resolve(parent)
        resolver.resolve(legacy)
        self.assertEqual(parent["sha256"], resolver.references[parent["artifact_id"]]["sha256"])
        self.assertTrue(same_reference(parent, legacy))
        self.assertEqual(reference_identity(parent), reference_identity(legacy))

    def test_content_locator_provenance_bindings_sealing_and_protections_remain_strict(self):
        ref = self.import_refs()[0]
        self.manager.establish_import_retention([ref["artifact_id"]])
        mutations = [("sha256", "e" * 64), ("locator", {**ref["locator"], "object_id": "different-original-object"}),
            ("provenance", {**ref["provenance"], "run_id": "different-original-run"}),
            ("bindings", {"different-plan": "e" * 64}),
            ("retention", {**ref["retention"], "sealed_at": "2026-02-01T12:00:00Z"}),
            ("retention", {**ref["retention"], "protections": ["changed-original-protection"]})]
        for field, value in mutations:
            changed = {**deepcopy(ref), field: value}
            self.assertFalse(same_reference(ref, changed))
            with self.subTest(field=field), self.assertRaisesRegex(EvidenceError, "missing/mismatched"):
                self.manager.prepare([changed])
        malformed = deepcopy(ref)
        malformed["retention"]["migration_policy_established"] = 1
        with self.assertRaisesRegex(EvidenceError, "retention flag"):
            same_reference(ref, malformed)
        ordinary = deepcopy(ref)
        ordinary["retention"]["imported"] = False
        ordinary_flag = deepcopy(ordinary)
        ordinary_flag["retention"]["migration_policy_established"] = True
        self.assertFalse(same_reference(ordinary, ordinary_flag))

    def test_acknowledgement_of_another_import_leaves_pending_collection_protected(self):
        child, parent = self.import_refs(dependency=True)
        self.manager.establish_import_retention([parent["artifact_id"]])
        protected = {a["artifact_id"]: a for a in self.actions() if a["action"] == "expired-but-protected"}
        self.assertIn("imported-migration-policy-pending", protected[child["artifact_id"]]["reasons"])
        self.assertNotIn(parent["artifact_id"], protected)
        with self.assertRaisesRegex(EvidenceError, "registered imported"):
            self.manager.establish_import_retention(["unregistered-artifact"])

    def test_reference_shaped_binding_and_provenance_values_remain_exact(self):
        ref = self.import_refs()[0]
        for field in ("bindings", "provenance"):
            original = deepcopy(ref)
            original[field]["reference_shaped_observation"] = deepcopy(ref)
            changed = deepcopy(original)
            changed[field]["reference_shaped_observation"]["retention"]["migration_policy_established"] = True
            with self.subTest(field=field):
                self.assertFalse(same_reference(original, changed))
        child, parent = self.import_refs(dependency=True)
        changed = deepcopy(parent)
        changed["dependencies"][0]["retention"]["migration_policy_established"] = True
        self.assertTrue(same_reference(parent, changed))
