"""Exact optional snapshot retirement without weakening required proof reads."""
import copy
import json
import shutil
import unittest
from unittest import mock

import test_history_integrity_scope as history_fixture
import test_evidence_manager as storage_fixture
from evidence import diagnostics
from evidence.policy import load_defaults
from history_integrity import history_integrity_scope, policy_mode


class OptionalDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.base = history_fixture.HistoryIntegrityGateTests("runTest")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.p, self.h = self.base.project, self.base.history
        self.m = self.p.manifest
        self.m["history_integrity"] = {"legacy_payloads": "every_gate"}
        policy = load_defaults()
        policy.update(project_id="11111111-1111-4111-8111-111111111111",
            store_id="22222222-2222-4222-8222-222222222222", provider="local")
        self.p.write("forge/evidence-policy.json", json.dumps(policy))

    def member(self):
        return {"record_ref": copy.deepcopy(self.base.reference), "logical_path": "assets/observation.bin",
            "content_hash": self.base.record["files"]["assets/observation.bin"]["content_hash"],
            "rationale": "Synthetic unattached observation; not a check or execution input."}

    def review(self, members=None):
        reference = diagnostics.capture_review(self.p.root, self.m,
            [self.member()] if members is None else members,
            {"reviewer": "synthetic-evidence-owner", "reviewed_at": self.h.utcnow(),
             "rationale": "Keep required proof and retire only unrelated diagnostic snapshots."})
        self.m["history_integrity"]["optional_diagnostics_ref"] = reference
        return reference

    def test_full_audit_accepts_explicit_optional_retirement_and_preserves_originals(self):
        original = (self.p.root / self.base.reference["path"]).read_bytes()
        reference = self.review()
        self.base.payload.unlink()
        with mock.patch("subprocess.run", side_effect=AssertionError("audit must not run tests or fetch")):
            report = self.base.checker().run("product-idea", audit=True, require_current=True)
        self.assertEqual("passed", report["result"], report)
        self.assertEqual(original, (self.p.root / self.base.reference["path"]).read_bytes())
        self.assertEqual(reference, report["history_integrity"]["optional_diagnostics"]["review_ref"])
        self.assertEqual(1, report["history_integrity"]["optional_diagnostics"]["bulk_members_not_required"])
        self.m["history_integrity"].pop("optional_diagnostics_ref")
        report = self.base.checker().run("product-idea", audit=True, require_current=True)
        self.assertEqual("blocked", report["result"], report)

    def test_direct_active_file_and_directory_access_stays_strict_even_before_deletion(self):
        self.review()
        frozen = self.base.record["files"]["assets/observation.bin"]
        with history_integrity_scope(self.m, project=self.p.root):
            self.h.validate_files(self.p.root, self.base.record)
            with self.assertRaisesRegex(ValueError, "active input/proof"):
                self.h.archived_source_path(self.p.root, frozen)
            with self.assertRaisesRegex(ValueError, "active input/proof"):
                self.h.source_view_path(self.p.root, self.base.record["snapshot_root"],
                    self.base.record["files"], "assets")
        self.assertTrue(self.base.payload.is_file())

    def test_candidate_hashes_preserve_envelopes_and_omit_only_reviewed_bulk_members(self):
        self.review()
        frozen = self.base.record["files"]["assets/observation.bin"]
        before = self.h.candidate_hashes(self.p.root, self.m)
        self.assertNotIn(frozen["path"], before)
        self.assertIn(self.base.reference["path"], before)
        active = {**self.m, "required_input": frozen}
        with self.assertRaisesRegex(ValueError, "active input/proof"):
            self.h.candidate_hashes(self.p.root, active)
        self.base.payload.unlink()
        self.assertEqual(before, self.h.candidate_hashes(self.p.root, self.m))
        with self.assertRaisesRegex(ValueError, "active input/proof"):
            self.h.candidate_hashes(self.p.root, active)

    def test_changed_original_hash_or_foreign_member_cannot_be_reviewed(self):
        for change in ({"content_hash": "0" * 64}, {"logical_path": "assets/missing.bin"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "original member identity"):
                self.review([{**self.member(), **change}])

    def test_missing_original_bytes_cannot_receive_a_new_optional_review(self):
        self.base.payload.unlink()
        with self.assertRaisesRegex(ValueError, "verified original bytes"):
            self.review()

    def test_empty_review_supports_contract_two_without_legacy_deferral(self):
        self.m.update(checker_contract_version=2, unit_contract_version=2)
        # Bare every_gate is not an opt-in history policy for contract two.
        self.m.pop("history_integrity")
        reference = diagnostics.capture_review(self.p.root, self.m, [],
            {"reviewer": "synthetic-owner", "reviewed_at": self.h.utcnow(), "rationale": "Adopt lifecycle with unchanged proof."})
        self.m["history_integrity"] = {"legacy_payloads": "every_gate", "optional_diagnostics_ref": reference}
        self.assertEqual("every_gate", policy_mode(self.m))
        with history_integrity_scope(self.m, project=self.p.root):
            self.h.validate_files(self.p.root, self.base.record)
        self.m["history_integrity"]["legacy_payloads"] = "audit_only"
        with self.assertRaisesRegex(ValueError, "contract 2"):
            policy_mode(self.m)

    def test_owner_review_binding_and_original_metadata_remain_strict(self):
        self.review()
        path = self.p.root / self.base.reference["path"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "changed history file"):
            diagnostics.load_review(self.p.root, self.m)

    def test_review_cannot_drop_an_earlier_optional_member(self):
        self.review()
        self.base.payload.unlink()
        with self.assertRaisesRegex(ValueError, "cannot drop"):
            self.review([])

    def test_public_lookup_binds_exact_envelope_and_scope_does_not_leak(self):
        self.review()
        selected = diagnostics.load_review(self.p.root, self.m)
        self.assertEqual({"assets/observation.bin"}, set(selected.members(self.base.record)))
        changed = copy.deepcopy(self.base.record)
        changed["event"] = "unit_execution_context"
        self.assertFalse(selected.members(changed))
        with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
            with history_integrity_scope(self.m, project=self.p.root):
                raise RuntimeError("synthetic interruption")
        self.assertEqual(self.base.record["files"], diagnostics.effective_files(self.p.root, self.base.record))

    def test_existing_full_view_and_cold_reduced_view_preserve_exact_membership(self):
        self.optional_source_archive("inline")

    def test_compact_source_archive_fingerprints_and_cold_views_omit_only_optional_members(self):
        self.optional_source_archive("sha_objects_v1")

    def optional_source_archive(self, encoding):
        store = storage_fixture.EvidenceManagerTests("runTest")
        store.setUp()
        self.addCleanup(store.doCleanups)
        self.p.write("forge/evidence-policy.json", json.dumps(store.policy))
        frozen = self.base.record["files"]["assets/observation.bin"]
        external = store.manager.archive({"version": 1, "files": [{
            "path": str(self.base.payload), "original_path": frozen["path"],
            "sealed_at": storage_fixture.SEALED, "kind": "source_snapshot", "schema": "evidence-bytes-v1",
            "provenance": {"run_id": "synthetic-source", "unit_id": "U-1"},
            "bindings": {"original_snapshot": copy.deepcopy(frozen)}}]})[0]
        store.manager.prepare([external])
        index = self.h.create_source_archive_index(self.p.root, [{"record_ref": self.base.reference,
            "snapshot_root": self.base.record["snapshot_root"], "sources": [{**frozen, "evidence_ref": external}]}],
            evidence_cache=store.manager.cache, encoding=encoding)
        self.m["source_archive_index_ref"] = index
        self.h.prepare_source_views(self.p.root, index, evidence_cache=store.manager.cache,
            max_bytes=1024 * 1024, max_files=100, manifest=self.m)
        reference = diagnostics.capture_review(self.p.root, self.m, [self.member()],
            {"reviewer": "synthetic-owner", "reviewed_at": self.h.utcnow(), "rationale": "Unattached trace only."},
            evidence_cache=store.manager.cache)
        self.m["history_integrity"]["optional_diagnostics_ref"] = reference
        before = self.h.candidate_hashes(self.p.root, self.m, evidence_cache=store.manager.cache)
        self.assertIn(index["path"], before)
        self.assertNotIn(frozen["path"], before)
        self.assertFalse(any(key.startswith("@evidence/") for key in before))
        active_external = {**self.m, "required_capture": external}
        active = self.h.candidate_hashes(self.p.root, active_external, evidence_cache=store.manager.cache)
        self.assertIn(external["sha256"], [value for key, value in active.items()
            if key.startswith("@evidence/") and key.endswith("/original")])
        repeated = self.h.prepare_source_views(self.p.root, index, evidence_cache=store.manager.cache,
            max_bytes=1024 * 1024, max_files=100, manifest=self.m)
        self.assertEqual("already_prepared", repeated["status"])
        self.assertEqual(0, repeated["unique_copied_bytes"])
        with diagnostics.scope(self.p.root, self.m), self.h.source_archive_scope(
                self.p.root, index, store.manager.cache, policy_manifest=self.m) as archive:
            retained = diagnostics.effective_files(self.p.root, self.base.record)
            tree = archive.validate_view(self.base.record["snapshot_root"], retained)
            self.assertEqual({}, retained)
            (tree / "foreign.bin").write_bytes(b"must not become an allowed optional member")
            with self.assertRaisesRegex(ValueError, "membership changed"):
                archive.validate_view(self.base.record["snapshot_root"], retained, force=True)
            (tree / "foreign.bin").unlink()
        self.base.payload.unlink()
        shutil.rmtree(store.manager.cache / "source-views")
        for child in (store.manager.cache / "objects").iterdir():
            child.unlink()
        self.assertEqual(before, self.h.candidate_hashes(self.p.root, self.m, evidence_cache=store.manager.cache))
        with self.assertRaises(ValueError):
            self.h.candidate_hashes(self.p.root, active_external, evidence_cache=store.manager.cache)
        prepared = self.h.prepare_source_views(self.p.root, index, evidence_cache=store.manager.cache,
            max_bytes=1024 * 1024, max_files=100, manifest=self.m)
        self.assertEqual(0, prepared["unique_copied_bytes"])
        checker = history_fixture.sdd.Checker(self.p.root, self.m, evidence_cache=store.manager.cache)
        report = checker.run("product-idea", audit=True, require_current=True)
        self.assertEqual("passed", report["result"], report)


if __name__ == "__main__":
    unittest.main()
