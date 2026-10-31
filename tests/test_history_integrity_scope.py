"""Synthetic regression cases for explicitly deferred legacy payload integrity."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_sdd_check import Project, sdd
from history_integrity import defer_legacy_payload, history_integrity_scope, policy_mode


def current(mode="audit_only"):
    return {"checker_contract_version": 3, "unit_contract_version": 3,
            "history_integrity": {"legacy_payloads": mode}}


class HistoryIntegrityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.reference = {"path": "forge/unit-history/archive/record.json", "content_hash": "a" * 64}
        self.record = {"event": "legacy_execution_archive", "version": 2,
                       "acceptance": "unverified_not_reusable",
                       "manifest_ref": {"path": "forge/unit-history/archive/manifest.json", "content_hash": "b" * 64},
                       "snapshot_root": "forge/unit-history/archive/files",
                       "files": {"assets/observation.bin": {"path": "forge/unit-history/archive/files/assets/observation.bin", "content_hash": "c" * 64}}}

    def test_default_is_full_and_older_contracts_cannot_opt_in(self):
        self.assertEqual("every_gate", policy_mode({"checker_contract_version": 2, "unit_contract_version": 2}))
        self.assertFalse(defer_legacy_payload(self.reference, self.record))
        for version in (1, 2, True, 4):
            manifest = current()
            manifest["checker_contract_version"] = version
            with self.assertRaisesRegex(ValueError, "contracts 3"):
                policy_mode(manifest)

    def test_unknown_or_malformed_policy_fails_closed(self):
        for value in (None, [], {}, {"legacy_payloads": "skip"}, {"legacy_payloads": "audit_only", "trust": True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy_mode(dict(current(), history_integrity=value))

    def test_nested_gate_inherits_scope_and_reports_unique_deferred_members(self):
        with history_integrity_scope(current()) as outer:
            self.assertTrue(defer_legacy_payload(self.reference, self.record))
            with history_integrity_scope({"checker_contract_version": 2, "unit_contract_version": 2}) as nested:
                self.assertFalse(nested.is_root)
                self.assertTrue(defer_legacy_payload(self.reference, self.record))
            report = outer.report()
            self.assertEqual(1, report["deferred_archive_count"])
            self.assertEqual(1, report["deferred_snapshot_files"])
            self.assertIsNone(report["last_full_payload_verification"])
            self.assertEqual("not_audited_this_gate", report["legacy_payload_status"])
        self.assertFalse(defer_legacy_payload(self.reference, self.record))

    def test_audit_release_or_migration_scope_forces_full_even_when_nested(self):
        with history_integrity_scope(current(), force_full=True) as root:
            with history_integrity_scope(current()):
                self.assertFalse(defer_legacy_payload(self.reference, self.record))
            self.assertEqual("every_gate", root.report()["effective_legacy_payloads"])
            self.assertEqual(0, root.report()["deferred_archive_count"])
        with history_integrity_scope(current()):
            with history_integrity_scope(current(), force_full=True):
                self.assertFalse(defer_legacy_payload(self.reference, self.record))
            self.assertTrue(defer_legacy_payload(self.reference, self.record))

    def test_scope_does_not_survive_failure(self):
        with self.assertRaises(RuntimeError):
            with history_integrity_scope(current()):
                raise RuntimeError("interrupted")
        self.assertFalse(defer_legacy_payload(self.reference, self.record))

    def test_only_unusable_legacy_record_can_be_deferred(self):
        for changes in ({"event": "unit_completion"}, {"acceptance": "passed"}, {"version": 3}, {"version": True}):
            with self.subTest(changes=changes), history_integrity_scope(current()), self.assertRaises(ValueError):
                defer_legacy_payload(self.reference, dict(self.record, **changes))

    def test_deferred_membership_is_still_validated(self):
        mutations = [
            lambda r: r.update(snapshot_root="../outside"),
            lambda r: r.update(files=[]),
            lambda r: r["files"].update({"../outside": self.record["files"]["assets/observation.bin"]}),
            lambda r: r["files"]["assets/observation.bin"].update(path="forge/other.bin"),
            lambda r: r["files"]["assets/observation.bin"].update(content_hash="not a hash"),
            lambda r: r["manifest_ref"].update(path="/absolute/manifest.json"),
        ]
        for mutation in mutations:
            record = copy.deepcopy(self.record)
            mutation(record)
            with self.subTest(record=record), history_integrity_scope(current()), self.assertRaises(ValueError):
                defer_legacy_payload(self.reference, record)


class HistoryIntegrityGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdd-legacy-integrity-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.history = sdd.history_api()
        self.project = Project(self.root)
        self.payload = self.root / "forge/unit-history/old/files/assets/observation.bin"
        self.payload.parent.mkdir(parents=True)
        self.payload.write_bytes(b"original")
        manifest_ref = self.history.write_new(self.root, "forge/unit-history/old/manifest.json",
                                              self.history.encoded(self.project.manifest))
        self.record = {"event": "legacy_execution_archive", "version": 2,
                       "acceptance": "unverified_not_reusable", "manifest_ref": manifest_ref,
                       "snapshot_root": "forge/unit-history/old/files",
                       "files": {"assets/observation.bin": {"path": self.payload.relative_to(self.root).as_posix(),
                                                             "content_hash": sdd.digest(b"original")}}}
        self.reference = self.history.write_new(self.root, "forge/unit-history/old/record.json",
                                                self.history.encoded(self.record))
        self.project.manifest.update(current(), legacy_history=[self.reference], next_ready_nodes=[])

    def checker(self):
        return sdd.Checker(self.root, self.project.manifest)

    def run_legacy(self, *, audit=False, node="product-idea"):
        checker = self.checker()
        def body(*args, **kwargs):
            self.history.HistoryView(checker).resolve()
            return {"result": "passed", "issues": checker.issues}
        with mock.patch.object(checker, "_run", side_effect=body):
            return checker.run(node, audit=audit)

    def test_ordinary_gate_defers_unusable_payload_and_audit_detects_damage(self):
        self.payload.write_bytes(b"damaged")
        result = self.run_legacy()
        self.assertEqual("passed", result["result"])
        self.assertEqual(1, result["history_integrity"]["deferred_archive_count"])
        with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
            self.run_legacy(audit=True)
        with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
            self.run_legacy(node="release")

    def test_ordinary_gate_still_rejects_changed_legacy_metadata(self):
        path = self.root / self.reference["path"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "changed history file"):
            self.run_legacy()

    def test_original_manifest_metadata_is_not_deferred(self):
        path = self.root / self.record["manifest_ref"]["path"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "changed history file"):
            self.run_legacy()

    def test_legacy_payload_also_used_as_active_snapshot_still_requires_bytes(self):
        self.payload.write_bytes(b"damaged")
        with history_integrity_scope(current()):
            self.assertTrue(defer_legacy_payload(self.reference, self.record))
            with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
                self.history.validate_files(self.root, dict(self.record, event="unit_execution_context"))

    def test_default_every_gate_policy_still_detects_damage(self):
        self.project.manifest["history_integrity"]["legacy_payloads"] = "every_gate"
        self.payload.write_bytes(b"damaged")
        with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
            self.run_legacy()

    def test_migration_scope_forces_full_payload_validation(self):
        self.payload.write_bytes(b"damaged")
        with history_integrity_scope(self.project.manifest, force_full=True), self.assertRaisesRegex(ValueError, "historical snapshot changed"):
            self.run_legacy()

    def test_real_gate_reports_deferral_and_audit_rejects_damaged_payload(self):
        self.payload.write_bytes(b"damaged")
        report = self.checker().run("product-idea", require_current=True)
        self.assertEqual("passed", report["result"], report)
        self.assertEqual("not_audited_this_gate", report["history_integrity"]["legacy_payload_status"])
        audit = self.checker().run("product-idea", audit=True, require_current=True)
        self.assertEqual("blocked", audit["result"], audit)
        self.assertTrue(any(issue["code"] == "unit_history" and "historical snapshot changed" in issue["detail"]
                            for issue in audit["issues"]), audit)
        self.assertEqual("every_gate", audit["history_integrity"]["effective_legacy_payloads"])


if __name__ == "__main__":
    unittest.main()
