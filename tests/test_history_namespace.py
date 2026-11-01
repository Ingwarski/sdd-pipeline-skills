"""Portable history migration and known-old pathname writers; isolated roots only."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_sdd_check import ROOT, sdd
from evidence import history_namespace as namespace
from evidence.io import EvidenceError


OLD_EMITTER = ROOT / "tests/fixtures/history-emitter-656aa8a.py"
OLD_EMITTER_SHA256 = "b88439124b279ff1f1d58ef9d66581f51cb2ed4060bebc029de22eb65afa7712"


class HistoryNamespaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-history-namespace-test-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name).resolve() / "project"
        self.old = self.project / namespace.HISTORY
        self.old.mkdir(parents=True)
        self.target = self.project / namespace.PHYSICAL_HISTORY
        self.journal = self.project / namespace.JOURNAL
        self.facts = {"project_id": "11111111-1111-4111-8111-111111111111",
                      "store_id": "22222222-2222-4222-8222-222222222222",
                      "participant_id": "synthetic-main"}
        self.relative = namespace.HISTORY + "/attempts/original/record.json"
        self.original = (json.dumps({"event": "unit_attempt", "version": 2,
            "acceptance": "not_completed", "run_id": "synthetic-original-run",
            "context_ref": {"path": namespace.HISTORY + "/contexts/original/record.json",
                            "content_hash": "a" * 64}}, sort_keys=True) + "\n").encode()
        selected = self.project / self.relative
        selected.parent.mkdir(parents=True)
        selected.write_bytes(self.original)

    def ensure(self, **changes):
        return namespace.ensure_history_namespace(self.project, **{**self.facts, **changes})

    @staticmethod
    def files(root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*") if path.is_file()}

    def old_emitter(self, mode):
        self.assertEqual(OLD_EMITTER_SHA256, hashlib.sha256(OLD_EMITTER.read_bytes()).hexdigest())
        return subprocess.run([sys.executable, "-B", str(OLD_EMITTER), str(self.project), mode],
                              capture_output=True, text=True, timeout=30)

    def test_migration_preserves_bytes_logical_refs_and_is_idempotent(self):
        before = self.files(self.old)
        self.assertIsNone(namespace.namespace_status(self.project))
        self.assertEqual(self.project / self.relative, namespace.physical_path(self.project, self.relative))
        result = self.ensure()
        self.assertTrue(self.old.is_file())
        self.assertFalse(self.old.is_symlink())
        self.assertEqual(before, self.files(self.target))
        resolved = namespace.physical_path(self.project, self.relative)
        self.assertEqual(self.original, resolved.read_bytes())
        self.assertEqual(self.relative, namespace.logical_path(self.project, resolved))
        self.assertEqual(self.relative, namespace.logical_path(self.project, self.relative))
        self.assertEqual(result, namespace.require_history_namespace(self.project))
        after = self.files(self.project)
        self.assertEqual(result, self.ensure())
        self.assertEqual(after, self.files(self.project))

    def test_frozen_emitters_work_before_fence_and_cannot_publish_after_it(self):
        for mode in ("runtime", "import-source"):
            with self.subTest(mode=mode, state="legacy"):
                outcome = self.old_emitter(mode)
                self.assertEqual(0, outcome.returncode, outcome.stdout + outcome.stderr)
                self.assertTrue((self.project / json.loads(outcome.stdout)["path"]).is_file())
        self.ensure()
        before = self.files(self.target)
        for mode in ("runtime", "import-source"):
            with self.subTest(mode=mode, state="adopted"):
                outcome = self.old_emitter(mode)
                self.assertNotEqual(0, outcome.returncode, outcome.stdout + outcome.stderr)
                self.assertEqual("blocked", json.loads(outcome.stdout)["result"])
        self.assertEqual(before, self.files(self.target))
        self.assertTrue(self.old.is_file())

    def test_rename_gap_recreation_preserves_both_trees_and_blocks_retry(self):
        rename = namespace._rename_directory
        def recreate(source, target):
            rename(source, target)
            source.mkdir()
            (source / "old-writer-output.txt").write_text("Concurrent old writer; preserve me.\n")
        with patch.object(namespace, "_rename_directory", side_effect=recreate):
            with self.assertRaises(EvidenceError):
                self.ensure()
        self.assertEqual(self.original, (self.target / "attempts/original/record.json").read_bytes())
        self.assertEqual("Concurrent old writer; preserve me.\n", (self.old / "old-writer-output.txt").read_text())
        with self.assertRaises(EvidenceError):
            self.ensure()
        with self.assertRaises(EvidenceError):
            namespace.require_history_namespace(self.project)
        self.assertTrue(self.old.is_dir())
        self.assertTrue(self.target.is_dir())

    def test_existing_activation_lock_blocks_without_moving_history(self):
        lock = self.old / "activation.lock"
        lock.write_text('{"pid": 123, "synthetic_fixture": true}\n')
        before = self.files(self.old)
        with self.assertRaisesRegex(EvidenceError, "activation lock"):
            self.ensure()
        self.assertEqual(before, self.files(self.old))
        self.assertFalse(self.target.exists())

    def test_activation_lock_appearing_during_move_preserves_recovery_hold(self):
        rename = namespace._rename_directory
        def activate(source, target):
            rename(source, target)
            (target / "activation.lock").write_text('{"synthetic_fixture": true}\n')
        with patch.object(namespace, "_rename_directory", side_effect=activate):
            with self.assertRaisesRegex(EvidenceError, "activation lock"):
                self.ensure()
        self.assertTrue((self.target / "activation.lock").is_file())
        self.assertTrue(self.journal.is_file())
        with self.assertRaises(EvidenceError):
            namespace.require_history_namespace(self.project)
        with self.assertRaisesRegex(EvidenceError, "activation lock"):
            self.ensure()
        self.assertEqual(self.original, (self.target / "attempts/original/record.json").read_bytes())

    def test_marker_interruption_blocks_reads_until_exact_retry_completes(self):
        with patch.object(namespace, "_write_marker", side_effect=OSError("synthetic marker interruption")):
            with self.assertRaises(EvidenceError):
                self.ensure()
        self.assertTrue(self.target.is_dir())
        self.assertTrue(self.journal.is_file())
        with self.assertRaises(EvidenceError):
            namespace.namespace_status(self.project)
        with self.assertRaises(EvidenceError):
            namespace.physical_path(self.project, self.relative)
        with self.assertRaises(EvidenceError):
            self.ensure(store_id="33333333-3333-4333-8333-333333333333")
        self.ensure()
        self.assertEqual(self.original, namespace.physical_path(self.project, self.relative).read_bytes())

    def test_unowned_destination_is_not_overwritten_or_enrolled(self):
        self.target.mkdir()
        sentinel = self.target / "unrelated.txt"
        sentinel.write_text("Retain unowned destination.\n")
        with self.assertRaises(EvidenceError):
            self.ensure()
        self.assertEqual("Retain unowned destination.\n", sentinel.read_text())
        self.assertEqual(self.original, (self.project / self.relative).read_bytes())

    def test_symlink_source_is_rejected_without_following_its_target(self):
        outside = Path(self.temporary.name).resolve() / "outside-history"
        self.old.rename(outside)
        try:
            self.old.symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError) as error:
            self.skipTest("symlink creation unavailable: " + str(error))
        with self.assertRaises(EvidenceError):
            self.ensure()
        self.assertEqual(self.original, (outside / "attempts/original/record.json").read_bytes())
        self.assertTrue(self.old.is_symlink())
        self.assertFalse(self.target.exists())

    def test_malformed_marker_and_foreign_identity_fail_closed(self):
        self.ensure()
        marker = self.old.read_bytes()
        self.old.write_text('{"version": 1, "physical_root": "../escape"}\n')
        with self.assertRaises(EvidenceError):
            namespace.physical_path(self.project, self.relative)
        self.old.write_bytes(marker)
        with self.assertRaises(EvidenceError):
            self.ensure(project_id="44444444-4444-4444-8444-444444444444")
        self.assertEqual(self.original, namespace.physical_path(self.project, self.relative).read_bytes())

    def test_completed_copy_keeps_creator_provenance_for_distinct_participant(self):
        original_facts = self.ensure()
        checkout = Path(self.temporary.name).resolve() / "copied-checkout"
        shutil.copytree(self.project, checkout)
        result = namespace.ensure_history_namespace(checkout,
            **{**self.facts, "participant_id": "synthetic-branch"})
        self.assertEqual(original_facts, result)
        self.assertEqual("synthetic-main", result["participant_id"])
        self.assertEqual(self.original, namespace.physical_path(checkout, self.relative).read_bytes())

    def test_physical_storage_and_journal_cannot_be_authored_source_paths(self):
        self.ensure()
        for relative in (namespace.PHYSICAL_HISTORY,
                         namespace.PHYSICAL_HISTORY + "/attempts/original/record.json",
                         namespace.JOURNAL, namespace.STAGED_MARKER):
            with self.subTest(relative=relative):
                self.assertTrue(namespace.is_reserved_path(relative))
                with self.assertRaises(EvidenceError):
                    namespace.physical_path(self.project, relative)

    def test_parent_source_scope_excludes_namespace_controls_and_stored_history(self):
        authored = self.project / "forge/authored.txt"
        authored.write_text("Authored input remains an input.\n")
        self.ensure()
        paths = sdd.history_api().referenced_paths(self.project, {"source_root": "forge"})
        self.assertEqual({"forge/authored.txt"}, paths)


if __name__ == "__main__":
    unittest.main()
