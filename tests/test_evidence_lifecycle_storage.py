"""Isolated lifecycle/storage regressions; these do not claim product acceptance."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_evidence_manager as fixtures
from evidence.manager import Manager
from evidence.io import EvidenceError
from evidence.resolver import EvidenceResolver
from evidence.relocation import create_relocation, validate_relocation


class LifecycleStorageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EvidenceManagerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.project = f.base / "project"
        (self.project / "forge").mkdir(parents=True)
        self.manifest = self.project / "forge/sdd-manifest.json"
        self.write_manifest([])
        self.manager = Manager(f.transport, f.home, f.policy, project=self.project)
        self.review = {"reviewer": "synthetic-owner", "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "rationale": "Synthetic lifecycle storage exercise, not human product approval."}

    def write_manifest(self, refs):
        self.manifest.write_text(json.dumps({"checker_contract_version": 3, "unit_contract_version": 3,
            "verification": {"checks": [{"check_id": "synthetic-check", "evidence": refs}]}}))

    def archive(self, *payloads, roles=None):
        f = self.fixture
        paths = [f.file("synthetic-" + str(f.counter) + "-" + str(index) + ".bin", payload)
            for index, payload in enumerate(payloads)]
        specification = f.spec(*paths, kinds=["test-result"] * len(paths))
        if roles:
            for entry, role in zip(specification["files"], roles):
                entry["retention_class"] = role
        return self.manager.archive(specification)

    def adopt(self, refs=(), participant="main"):
        self.write_manifest(list(refs))
        return self.manager.adopt_lifecycle(participant, review=self.review)

    def classify(self, refs, role="optional_diagnostic", complete=True):
        return self.manager.classify_lifecycle([ref["artifact_id"] for ref in refs], role=role,
            review=self.review, purpose_complete=complete)

    def test_legacy_expiry_apply_cannot_trust_complete_boolean(self):
        ref = self.archive(b"synthetic proof")[0]
        with self.assertRaisesRegex(EvidenceError, "lifecycle adoption required"):
            self.manager.cleanup(now=fixtures.SEALED_TIME + timedelta(days=100), expire=True, dry_run=False,
                reference_snapshot_complete=True, protected_refs=[])
        self.assertIn(ref["artifact_id"], self.manager._catalog()["refs"])

    def test_warm_cache_cannot_mask_missing_required_archive_during_adoption(self):
        ref = self.archive(b"warm proof with lost durable bytes")[0]
        self.manager.prepare([ref])
        self.fixture.transport.delete(ref["locator"])
        with self.assertRaises((EvidenceError, OSError)):
            self.adopt([ref])
        self.assertFalse(self.manager.lifecycle_status()["adopted"])

    def test_every_retained_reason_protects_its_dependency_closure(self):
        for role in (None, "investigation", "required_proof", "optional_diagnostic"):
            with self.subTest(role=role):
                child = self.archive(("child for " + str(role)).encode())[0]
                path = self.fixture.file("parent-" + str(role) + ".bin", ("parent " + str(role)).encode())
                spec = self.fixture.spec(path)
                spec["files"][0]["dependencies"] = [child]
                parent = self.manager.archive(spec)[0]
                if not self.manager.lifecycle_status()["adopted"]:
                    self.adopt()
                self.classify([child])
                if role is not None:
                    self.classify([parent], role, complete=(role == "required_proof"))
                self.manager.cleanup_lifecycle(dry_run=False)
                self.assertIn(child["artifact_id"], self.manager._catalog()["refs"])

    def test_retained_json_payload_protects_nested_reference_without_dependency_field(self):
        child = self.archive(b"nested required bytes")[0]
        path = self.fixture.file("investigation.json", json.dumps({"evidence": [child]}).encode())
        spec = self.fixture.spec(path)
        spec["files"][0]["schema"] = "evidence-json-v1"
        parent = self.manager.archive(spec)[0]
        self.adopt()
        self.classify([parent], "investigation", False)
        self.classify([child])
        self.manager.cleanup_lifecycle(dry_run=False)
        self.assertIn(child["artifact_id"], self.manager._catalog()["refs"])

    def test_removed_retained_history_envelope_does_not_release_its_proof(self):
        from evidence.dependencies import HISTORY
        ref = self.archive(b"orphan retained history proof")[0]
        directory = self.project / HISTORY / "synthetic-orphan"
        directory.mkdir(parents=True)
        envelope = directory / "record.json"
        envelope.write_text(json.dumps({"event": "unit_completion", "version": 2, "evidence": [ref]}))
        self.adopt()
        envelope.unlink()
        with self.assertRaisesRegex(EvidenceError, "retained immutable history envelope"):
            self.manager.checkpoint_lifecycle("main")
        self.assertIn(ref["artifact_id"], self.manager._catalog()["refs"])

    def test_retained_json_source_snapshot_protects_nested_proof(self):
        child = self.archive(b"source snapshot embedded proof")[0]
        path = self.fixture.file("frozen-synthetic-manifest.JSON", json.dumps({"evidence": [child]}).encode())
        spec = self.fixture.spec(path, kinds=["source_snapshot"])
        parent = self.manager.archive(spec)[0]
        self.adopt()
        self.classify([parent], "investigation", False)
        self.classify([child])
        self.manager.cleanup_lifecycle(dry_run=False)
        self.assertIn(child["artifact_id"], self.manager._catalog()["refs"])

    def test_root2_adoption_retry_and_unchanged_checkpoint_are_idempotent(self):
        ref = self.archive(b"synthetic proof")[0]
        self.adopt([ref])
        catalog = self.manager._catalog()
        self.assertEqual(2, catalog["version"])
        self.assertEqual("main", self.manager.lifecycle_participant())
        self.manager.adopt_lifecycle("main", review=self.review)
        self.manager.checkpoint_lifecycle("main", cleanup=False)
        self.assertEqual(catalog["root_key"], self.manager._catalog()["root_key"])
        with self.assertRaisesRegex(EvidenceError, "different decision"):
            self.manager.adopt_lifecycle("main", review={**self.review, "rationale": "another decision"})

    def test_computed_required_proof_overrides_omitted_keep_list_and_optional_label(self):
        ref = self.archive(b"required original")[0]
        self.adopt([ref])
        self.classify([ref])
        actions = self.manager.cleanup(expire=True, dry_run=False, reference_snapshot_complete=True)
        self.assertFalse(any(item["action"] == "retire" for item in actions))
        self.assertIn(ref["artifact_id"], self.manager._catalog()["refs"])

    def test_unknown_and_open_investigation_remain_but_closed_optional_is_deleted(self):
        unknown, investigation, optional = self.archive(b"unknown", b"investigation", b"optional")
        self.adopt()
        self.classify([investigation], "investigation", False)
        self.classify([optional], complete=False)
        self.assertEqual([], self.manager.cleanup_lifecycle(dry_run=False))
        self.classify([optional])
        actions = self.manager.cleanup_lifecycle(dry_run=False)
        catalog = self.manager._catalog()
        self.assertIn(unknown["artifact_id"], catalog["refs"])
        self.assertIn(investigation["artifact_id"], catalog["refs"])
        self.assertNotIn(optional["artifact_id"], catalog["refs"])
        self.assertTrue(any(item.get("artifact_id") == optional["artifact_id"] for item in actions))

    def test_stale_participant_blocks_deletion_until_explicit_checkpoint(self):
        ref = self.archive(b"newly required")[0]
        self.adopt()
        self.classify([ref])
        self.write_manifest([ref])
        with self.assertRaisesRegex(EvidenceError, "records changed"):
            self.manager.cleanup_lifecycle(dry_run=False)
        self.manager.checkpoint_lifecycle("main")
        self.assertIn(ref["artifact_id"], self.manager._catalog()["refs"])

    def test_offline_participant_blocks_cleanup_without_blocking_preparation(self):
        ref = self.archive(b"required cold proof")[0]
        self.adopt([ref])
        binding = self.manager.state / "lifecycle-bindings.json"
        binding.unlink()
        with self.assertRaisesRegex(EvidenceError, "unavailable"):
            self.manager.cleanup_lifecycle(dry_run=False)
        self.manager.prepare([ref])
        self.assertEqual(b"required cold proof", EvidenceResolver(self.manager.cache).resolve(ref).read_bytes())

    def test_retiring_one_participant_keeps_shared_required_proof(self):
        ref = self.archive(b"shared proof")[0]
        self.adopt([ref])
        second = self.fixture.base / "second-project"
        (second / "forge").mkdir(parents=True)
        (second / "forge/sdd-manifest.json").write_bytes(self.manifest.read_bytes())
        other = Manager(self.fixture.transport, self.fixture.home, self.fixture.policy, project=second)
        other.checkpoint_lifecycle("branch", cleanup=False)
        self.manager.retire_lifecycle_scope("main", review=self.review)
        self.manager.cleanup_lifecycle(dry_run=False)
        self.assertIn(ref["artifact_id"], self.manager._catalog()["refs"])
        other.retire_lifecycle_scope("branch", review=self.review)
        other.cleanup_lifecycle(dry_run=False)
        self.assertNotIn(ref["artifact_id"], self.manager._catalog()["refs"])

    def test_separate_lifetimes_use_separate_new_packs(self):
        a, b = self.archive(b"proof", b"optional", roles=["required_proof", "optional_diagnostic"])
        self.assertNotEqual(a["locator"]["pack_sha256"], b["locator"]["pack_sha256"])

    def test_unregistered_writer_cannot_publish_into_adopted_store(self):
        self.adopt()
        path = self.fixture.file("new-unregistered-proof.bin", b"not admitted")
        unknown = Manager(self.fixture.transport, self.fixture.home, self.fixture.policy)
        before = set(self.fixture.transport.keys(""))
        with self.assertRaisesRegex(EvidenceError, "register its project participant"):
            unknown.archive(self.fixture.spec(path))
        self.assertEqual(before, set(self.fixture.transport.keys("")))

    def test_interrupted_delete_rechecks_new_dependency_and_checkpoint_restores_original(self):
        ref = self.archive(b"reused before physical deletion")[0]
        self.adopt()
        self.classify([ref])
        with patch.object(self.fixture.transport, "delete", side_effect=OSError("synthetic interruption")):
            self.manager.cleanup_lifecycle(dry_run=False)
        self.write_manifest([ref])
        with self.assertRaisesRegex(EvidenceError, "records changed"):
            self.manager.cleanup_lifecycle(dry_run=False)
        self.assertEqual(ref["locator"]["pack_size"], self.fixture.transport.stat(ref["locator"])["size"])
        self.manager.checkpoint_lifecycle("main")
        catalog = self.manager._catalog()
        self.assertEqual(ref, catalog["refs"][ref["artifact_id"]])
        self.assertFalse(catalog["pending_deletions"])
        self.assertFalse((self.manager.state / "lifecycle-pruning.json").exists())
        self.manager.prepare([ref])
        self.assertEqual(b"reused before physical deletion", EvidenceResolver(self.manager.cache).resolve(ref).read_bytes())

    def test_last_moment_source_change_blocks_actual_remote_delete(self):
        ref = self.archive(b"new required evidence")[0]
        self.adopt()
        self.classify([ref])
        original = self.manager._lifecycle_recheck
        def change_then_recheck(inventory, catalog):
            self.write_manifest([ref])
            return original(inventory, catalog)
        with patch.object(self.manager, "_lifecycle_recheck", side_effect=change_then_recheck):
            with self.assertRaises(EvidenceError):
                self.manager.cleanup_lifecycle(dry_run=False)
        self.assertIn(ref["artifact_id"], self.manager._catalog()["refs"])
        self.assertEqual(ref["locator"]["pack_size"], self.fixture.transport.stat(ref["locator"])["size"])

    def test_mixed_pack_relocation_preserves_original_reference_and_cold_bytes(self):
        proof, optional = self.archive(b"retained native result", b"unneeded verbose output" * 100)
        original = deepcopy(proof)
        old_pack = proof["locator"]["pack_sha256"]
        self.assertEqual(old_pack, optional["locator"]["pack_sha256"])
        self.adopt([proof])
        self.classify([optional])
        self.manager.cleanup_lifecycle(dry_run=False)
        self.assertIn(old_pack, self.manager._catalog()["packs"])
        result = self.manager.relocate_lifecycle_pack(old_pack, dry_run=False)
        self.assertEqual("relocate-surviving-members", result["action"])
        catalog = self.manager._catalog()
        self.assertEqual(original, catalog["refs"][proof["artifact_id"]])
        self.assertNotIn(old_pack, catalog["packs"])
        shutil.rmtree(self.manager.cache)
        self.manager.cache.mkdir()
        self.manager.prepare([original])
        self.assertEqual(b"retained native result", EvidenceResolver(self.manager.cache).resolve(original).read_bytes())
        self.assertGreater(result["net_encoded_bytes_freed"], 0)

    def test_relocation_refreshes_receipt_without_rebuilding_pinned_source_scope(self):
        from evidence.source_payloads import SourcePayloadScope
        proof, optional = self.archive(b"pinned required result", b"discardable" * 100)
        self.adopt([proof])
        self.classify([optional])
        self.manager.cleanup_lifecycle(dry_run=False)
        self.manager.prepare([proof])
        with self.manager.locked():
            scope = SourcePayloadScope(self.project, self.manager.cache, self.fixture.policy)
            scope.resolver.resolve(proof)
            self.manager._source_payload_scope = scope
            pinned_manifest = scope.resolver.documents[self.manifest]
            self.manager.relocate_lifecycle_pack(proof["locator"]["pack_sha256"], dry_run=False)
            self.assertIs(scope, self.manager._source_payload_scope)
            self.assertEqual(pinned_manifest, scope.resolver.documents[self.manifest])
            scope.audit()
            self.assertIn("storage_relocations", scope.resolver.documents[self.manager.cache / "receipts" /
                (proof["artifact_id"] + ".json")][1])

    def test_receipt_refresh_cannot_reset_an_unrelated_changed_source_input(self):
        from evidence.source_payloads import SourcePayloadScope
        ref = self.archive(b"pinned proof")[0]
        self.manager.prepare([ref])
        scope = SourcePayloadScope(self.project, self.manager.cache, self.fixture.policy)
        scope.resolver.resolve(ref)
        receipt = scope.resolver.documents[self.manager.cache / "receipts" / (ref["artifact_id"] + ".json")][1]
        self.write_manifest([ref])
        with self.assertRaisesRegex(ValueError, "proof input changed"):
            with scope.verified_receipt_transition(ref, receipt):
                self.fail("changed proof must fail before Manager can write")

    def test_relocation_cannot_change_original_semantics(self):
        original = self.archive(b"native bytes")[0]
        for field, changed in (("sha256", "0" * 64), ("provenance", {"run_id": "different"}),
                               ("retention", {**original["retention"], "sealed_at": "2020-01-01T00:00:00Z"})):
            replacement = {**original, field: changed}
            with self.assertRaisesRegex(EvidenceError, "changes original evidence"):
                create_relocation(original, replacement)

    def test_interrupted_relocation_keeps_old_pack_and_retries_exact_publication(self):
        proof, optional = self.archive(b"still required", b"discardable" * 100)
        old_pack = proof["locator"]["pack_sha256"]
        self.adopt([proof])
        self.classify([optional])
        self.manager.cleanup_lifecycle(dry_run=False)
        publish = self.manager._publish
        def interrupted(catalog, segment, **kwargs):
            if segment.get("storage_relocations"):
                raise EvidenceError("synthetic interruption before relocation commit")
            return publish(catalog, segment, **kwargs)
        with patch.object(self.manager, "_publish", side_effect=interrupted):
            with self.assertRaisesRegex(EvidenceError, "synthetic interruption"):
                self.manager.relocate_lifecycle_pack(old_pack, dry_run=False)
        self.assertIn(old_pack, self.manager._catalog()["packs"])
        self.manager.relocate_lifecycle_pack(old_pack, dry_run=False)
        self.assertNotIn(old_pack, self.manager._catalog()["packs"])
        self.assertEqual("already-relocated", self.manager.relocate_lifecycle_pack(old_pack, dry_run=False)["action"])


if __name__ == "__main__":
    unittest.main()
