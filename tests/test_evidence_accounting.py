"""Synthetic evidence accounting and stable-byte I/O; no product/remote data."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence.accounting import Accounting, BudgetExceeded, git_blob_growth
from evidence.io import EvidenceError, atomic_json, hash_file, read_json, safe_relative, _is_link
from evidence.policy import load_defaults, validate_policy


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.policy = load_defaults()
        self.policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider="local")
        self.db = self.root / "machine" / "accounting.sqlite"

    def tearDown(self):
        self.temporary.cleanup()

    def accounting(self, **limits):
        self.policy["limits"].update(limits)
        for prefix in ("run", "unit", "project_generation", "retained"):
            self.policy["limits"][prefix + "_warning_bytes"] = min(self.policy["limits"][prefix + "_warning_bytes"], self.policy["limits"][prefix + "_stop_bytes"])
        return Accounting(self.db, self.policy["project_id"], self.policy)

    def test_defaults_are_concrete_numeric_and_portable(self):
        actual = validate_policy(self.policy)
        self.assertEqual(actual["limits"]["run_warning_bytes"], 250 * 1024**2)
        self.assertEqual(actual["limits"]["run_stop_bytes"], 500 * 1024**2)
        self.assertEqual(actual["retention"]["local_days"], 30)
        self.assertIsNone(actual["retention"]["drive_days"])
        for field in ("destination", "credentials", "project_path"):
            invalid = {**self.policy, field: "/private-data"}
            with self.assertRaises(EvidenceError):
                validate_policy(invalid)

    def test_policy_rejects_unknown_versions_boolean_negative_and_inverted_limits(self):
        for mutate in (lambda p: p.update(version=2), lambda p: p.update(version=True), lambda p: p["limits"].update(run_stop_bytes=True),
                       lambda p: p["limits"].update(local_stop_bytes=-1), lambda p: p.update(project_id="not-a-uuid"),
                       lambda p: p["limits"].update(run_warning_bytes=p["limits"]["run_stop_bytes"] + 1)):
            invalid = deepcopy(self.policy)
            mutate(invalid)
            with self.assertRaises(EvidenceError):
                validate_policy(invalid)

    def test_hash_is_streaming_and_bounded_json_rejects_duplicate_keys(self):
        path = self.root / "large.bin"
        path.write_bytes(b"x" * (3 * 1024**2 + 7))
        original_read = os.read
        sizes = []
        def observe(descriptor, amount):
            sizes.append(amount)
            return original_read(descriptor, amount)
        with patch("evidence.io.os.read", side_effect=observe):
            digest, size = hash_file(path)
        self.assertEqual(size, path.stat().st_size)
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertLessEqual(max(sizes), 1024**2)
        path.write_text('{"x":1,"x":2}', encoding="utf-8")
        with self.assertRaises(EvidenceError):
            read_json(path, 100)
        with self.assertRaises(EvidenceError):
            read_json(path, 3)

    def test_hash_detects_changed_and_replaced_inputs(self):
        path = self.root / "changing.bin"
        path.write_bytes(b"original")
        original_read, changed = os.read, [False]
        def mutate(descriptor, amount):
            block = original_read(descriptor, amount)
            if not changed[0]:
                changed[0] = True
                path.write_bytes(b"modified")
            return block
        with patch("evidence.io.os.read", side_effect=mutate), self.assertRaises(EvidenceError):
            hash_file(path)

    @unittest.skipUnless(hasattr(os, "mkfifo") and os.open in os.supports_dir_fd, "Unix FIFO/openat required")
    def test_regular_file_replaced_by_fifo_never_blocks(self):
        path = self.root / "raced"
        path.write_bytes(b"original")
        original_lstat, replaced = Path.lstat, [False]
        def substitute(target, *args, **kwargs):
            result = original_lstat(target, *args, **kwargs)
            if target == path and not replaced[0]:
                replaced[0] = True
                path.unlink()
                os.mkfifo(path)
            return result
        with patch("evidence.io.Path.lstat", substitute), self.assertRaises(EvidenceError):
            hash_file(path)

    def test_windows_reparse_attribute_is_a_link_even_for_directory_mode(self):
        from types import SimpleNamespace
        import stat
        # This exercises the Windows branch without claiming a live Windows run.
        with patch("evidence.io.stat.FILE_ATTRIBUTE_REPARSE_POINT", 1024, create=True):
            self.assertTrue(_is_link(SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_file_attributes=1024)))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_links_and_special_files_are_rejected(self):
        path = self.root / "file.json"
        path.write_text('{}', encoding="utf-8")
        try:
            (self.root / "link.json").symlink_to(path)
            (self.root / "linked-parent").symlink_to(self.root, target_is_directory=True)
        except OSError as error:
            self.skipTest("host does not grant symlink creation: " + str(error))
        for unsafe in (self.root / "link.json", self.root / "linked-parent/file.json", self.root):
            with self.assertRaises(EvidenceError):
                hash_file(unsafe)
        with self.assertRaises(EvidenceError):
            atomic_json(self.root / "link.json", {})
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.root / "fifo")
            with self.assertRaises(EvidenceError):
                hash_file(self.root / "fifo")

    def test_safe_relative_rejects_archive_escape_and_atomic_json_roundtrip(self):
        for value in ("../x", "/x", "a/../x", "a//b", "a\\b", "C:/x", "a/./x", "a/", "a\0b", "CON.txt", "LPT1", "a/x.", "a/x ", "a/x?y"):
            with self.assertRaises(EvidenceError):
                safe_relative(value)
        self.assertEqual(safe_relative("nested/observation.json"), "nested/observation.json")
        path = self.root / "safe.json"
        atomic_json(path, {"observation": "синтетична"})
        self.assertEqual(read_json(path, 1000), {"observation": "синтетична"})
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_many_small_files_and_split_reservations_cannot_bypass(self):
        with self.accounting(run_stop_files=3, run_stop_bytes=10) as ledger:
            first = ledger.reserve("run", "unit-01", 6, 2)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("run", "unit-01", 3, 2)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("run", "unit-01", 5, 1)
            ledger.settle(first, 6, 2)
            second = ledger.reserve("run", "unit-01", 4, 1)
            ledger.settle(second, 4, 1)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("run", "unit-01", 1, 0)

    def test_dedup_and_deleted_objects_never_refund_cumulative_generation(self):
        with self.accounting(unit_stop_bytes=10, project_generation_stop_bytes=20) as ledger:
            item = ledger.reserve("r1", "unit-01", 6, 1)
            ledger.settle(item, 6, 1)
            ledger.record_object("same", 6)
            ledger.record_object("same", 6)
            self.assertEqual(ledger.snapshot()["totals"]["retained_unique_bytes"], 6)
            ledger.remove_object("same")
            self.assertEqual(ledger.snapshot()["totals"]["retained_unique_bytes"], 0)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("renamed-script-new-run", "unit-01", 5, 1)
            self.assertEqual(ledger.snapshot()["totals"]["project_generated_bytes"], 6)

    def test_resumes_and_worktrees_share_stable_unit_project_charges(self):
        with self.accounting(unit_stop_bytes=10) as ledger:
            item = ledger.reserve("same-run", "unit-01", 6, 1)
            ledger.settle(item, 6, 1)
        with self.accounting() as resumed:
            self.assertEqual(len(resumed.snapshot()["runs"]), 1)
            item = resumed.reserve("same-run", "unit-01", 4, 1)
            resumed.settle(item, 4, 1)
            with self.assertRaises(BudgetExceeded):
                resumed.reserve("new-chat-worktree", "unit-01", 1, 1)
            with self.assertRaises(EvidenceError):
                resumed.reserve("same-run", "unit-02", 1, 1)

    def test_unit_retries_charge_distinct_runs_automatically(self):
        with self.accounting(max_unit_retries=1) as ledger:
            for run in ("attempt-one", "attempt-two"):
                item = ledger.reserve(run, "unit-01", 1, 1)
                ledger.settle(item, 1, 1)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("renamed-third", "unit-01", 0, 0)
            # Another unit has its own bounded retry allowance.
            ledger.cancel(ledger.reserve("next-unit", "unit-02", 0, 0))

    def test_concurrent_reservations_are_atomic(self):
        with self.accounting(unit_stop_bytes=10):
            pass
        def worker(index):
            with Accounting(self.db, self.policy["project_id"], self.policy) as ledger:
                try:
                    return ledger.reserve("worker-" + str(index), "unit-01", 6, 1)
                except BudgetExceeded:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            identifiers = list(pool.map(worker, range(2)))
        self.assertEqual(sum(value is not None for value in identifiers), 1)
        with self.accounting() as ledger:
            self.assertEqual(ledger.snapshot()["totals"]["pending_generated_bytes"], 6)

    def test_actual_overrun_is_charged_and_status_truthfully_incomplete(self):
        with self.accounting(run_stop_bytes=10) as ledger:
            item = ledger.reserve("run", "unit-01", 5, 1)
            result = ledger.settle(item, 12, 2)
            self.assertTrue(result["incomplete"])
            self.assertEqual(result["totals"]["project_generated_bytes"], 12)
            self.assertEqual(ledger.snapshot()["runs"][0]["status"], "incomplete")
            with self.assertRaises(EvidenceError):
                ledger.complete_run("run")
            with self.assertRaises(EvidenceError):
                ledger.settle(item, 12, 2)

    def test_local_combined_usage_and_free_space_floor(self):
        with self.accounting(local_stop_bytes=1024**2, cache_stop_bytes=1024**2, free_space_reserve_bytes=100) as ledger:
            ledger.reconcile_local("cache", 200000, "cache")
            ledger.reconcile_local("readback", 200000, "readback")
            ledger.reconcile_local("restore", 200000, "restore")
            ledger.reconcile_local("staging", 200000, "staging")
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("run", "unit-01", 1, 1, local_bytes=300000)
            # Include the independently persisted reservation checkpoint peak.
            with patch("evidence.accounting.shutil.disk_usage", return_value=shutil_usage(free=150 + 8192)):
                with self.assertRaises(BudgetExceeded):
                    ledger.reserve("run", "unit-01", 1, 1, local_bytes=51)
                ledger.cancel(ledger.reserve("run", "unit-01", 1, 1, local_bytes=50))

    def test_metadata_split_indexes_and_retained_reservations_share_budgets(self):
        with self.accounting(metadata_stop_bytes=1024**2, metadata_stop_files=4, retained_stop_bytes=10, retained_stop_objects=2) as ledger:
            # Two index allocations plus the recovery marker and run checkpoint
            # share the same metadata count limit.
            ledger.reconcile_metadata("segment1", 200000, 1)
            ledger.reconcile_metadata("segment2", 200000, 1)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("run", "unit-01", 0, 0, metadata_files=1)
            first = ledger.reserve("run", "unit-01", 0, 0, retained_bytes=6, retained_objects=1)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("other-run", "unit-02", 0, 0, retained_bytes=5, retained_objects=1)
            ledger.cancel(first)
            ledger.record_object("one", 6)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("run", "unit-01", 0, 0, retained_bytes=5, retained_objects=1)

    def test_retained_settlement_atomically_replaces_reserved_capacity(self):
        with self.accounting(retained_stop_bytes=10, retained_stop_objects=2) as ledger:
            item = ledger.reserve("run", "unit-01", 6, 1, retained_bytes=6, retained_objects=1)
            result = ledger.settle(item, 6, 1, objects=[("original-content", 6, 1)])
            self.assertFalse(result["incomplete"])
            self.assertEqual(result["totals"]["retained_unique_bytes"], 6)
            self.assertEqual(result["totals"]["pending_retained_bytes"], 0)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("other-run", "unit-02", 0, 0, retained_bytes=5, retained_objects=1)

    def test_migration_has_separate_bounded_allowance_above_project_budget(self):
        with self.accounting(project_generation_stop_bytes=10, retained_stop_bytes=10,
                             migration_batch_stop_bytes=8, migration_batch_stop_files=2) as ledger:
            ledger.record_object("legacy-object", 1000)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("ordinary", "unit-01", 1, 1)
            for index in range(3):
                item = ledger.reserve("migration-" + str(index), "migration", 8, 2, migration=True)
                ledger.settle(item, 8, 2)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("migration-0", "migration", 1, 1, migration=True)
            self.assertEqual(ledger.snapshot()["totals"]["project_generated_bytes"], 0)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("too-big-batch", "migration", 9, 1, migration=True)

    def test_output_registration_detects_bypass_and_reconcile_is_idempotent(self):
        path = self.root / "output"
        path.mkdir()
        with self.accounting() as ledger:
            item = ledger.reserve("run", "unit-01", 0, 0)
            output = ledger.register_output("run", "unit-01", path)
            with self.assertRaises(EvidenceError):
                ledger.complete_run("run")
            ledger.settle(item, 0, 0)
            (path / "unreserved.bin").write_bytes(b"unexpected")
            result = ledger.reconcile_output(output)
            self.assertEqual(result["new_bytes"], 10)
            self.assertTrue(result["incomplete"])
            repeated = ledger.reconcile_output(output)
            self.assertEqual(repeated["new_bytes"], 0)
            self.assertEqual(repeated["totals"]["project_generated_bytes"], 10)
            (path / "unreserved.bin").write_bytes(b"again")
            self.assertEqual(ledger.reconcile_output(output)["totals"]["project_generated_bytes"], 15)
            with self.assertRaises(EvidenceError):
                ledger.complete_run("run")

    def test_managed_output_binding_and_missing_accounting_completion(self):
        path = self.root / "managed"
        path.mkdir()
        with self.accounting() as ledger:
            with self.assertRaises(EvidenceError):
                ledger.complete_run("missing-run")
            item = ledger.reserve("run", "unit-01", 3, 1)
            output = ledger.register_output("run", "unit-01", path)
            (path / "file").write_bytes(b"abc")
            ledger.settle(item, 3, 1)
            ledger.acknowledge_output(output)
            self.assertEqual(ledger.reconcile_output(output)["new_bytes"], 0)
            ledger.complete_run("run")

    def test_coordinator_serializes_and_incomplete_clients_cannot_prune(self):
        with self.accounting() as ledger:
            ledger.acquire_coordinator("client-a")
            with self.assertRaises(EvidenceError):
                ledger.acquire_coordinator("client-b")
            with self.assertRaises(EvidenceError):
                ledger.require_coordinator("client-a", pruning=True)
            ledger.release_coordinator("client-a")
            ledger.acquire_coordinator("client-b", complete_knowledge=True)
            ledger.require_coordinator("client-b", pruning=True)
            ledger.release_coordinator("client-b")

    def test_cold_generation_merge_is_unique_preserves_failures_and_restores_retries(self):
        catalog = {
            "op-1": {"run_id": "original-run", "unit_id": "unit-01", "gross_bytes": 4, "logical_files": 1},
            "op-2": {"run_id": "original-run", "unit_id": "unit-01", "gross_bytes": 3, "logical_files": 1},
            "imported": {"run_id": "historic-run", "unit_id": "unit-01", "gross_bytes": 0, "logical_files": 0, "mode": "imported-existing"},
        }
        with self.accounting(unit_stop_bytes=10, max_unit_retries=0) as ledger:
            # A retained original run can merge remote floors and later settle
            # its own writes. A run reconstructed without its local accounting
            # must instead stay incomplete (covered by recovery regressions).
            ledger.cancel(ledger.reserve("original-run", "unit-01", 0, 0))
            ledger.reconcile_generation(catalog)
            ledger.reconcile_generation(catalog)
            self.assertEqual(ledger.snapshot()["totals"]["project_generated_bytes"], 7)
            self.assertEqual(len(ledger.snapshot()["runs"]), 1)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("new-attempt", "unit-01", 1, 1)
            item = ledger.reserve("original-run", "unit-01", 3, 1)
            ledger.settle(item, 4, 1)  # Failed local overrun must survive remote merge.
            ledger.reconcile_generation(catalog)
            self.assertEqual(ledger.snapshot()["totals"]["project_generated_bytes"], 11)
            self.assertEqual(ledger.snapshot()["runs"][0]["status"], "incomplete")
            changed = deepcopy(catalog)
            changed["op-1"]["gross_bytes"] = 2
            with self.assertRaises(EvidenceError):
                ledger.reconcile_generation(changed)

    def test_wrong_project_or_checkout_ledger_is_rejected(self):
        with self.accounting():
            pass
        other = {**self.policy, "project_id": str(uuid.uuid4())}
        with self.assertRaises(EvidenceError):
            Accounting(self.db, other["project_id"], other)
        with self.assertRaises(EvidenceError):
            Accounting(self.root / "checkout.sqlite", self.policy["project_id"], self.policy, project_root=self.root)

    def test_representative_starter_workloads_and_warnings(self):
        # Simulate logical observations and streaming-accounted byte totals; no
        # hundreds-of-MiB scratch files or real browser/cloud data are generated.
        with self.accounting() as ledger:
            captures = ledger.reserve("captures", "unit-01", 40 * 1024**2, 200)
            ledger.settle(captures, 40 * 1024**2, 200)
            logs = ledger.reserve("diagnostics", "unit-01", 300 * 1024**2, 60)
            ledger.settle(logs, 300 * 1024**2, 60)
            self.assertTrue(ledger.snapshot("diagnostics", "unit-01")["warnings"])
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("diagnostics", "unit-01", 201 * 1024**2, 1)


def shutil_usage(free):
    from collections import namedtuple
    return namedtuple("usage", "total used free")(free, 0, free)


class GitRangeTests(unittest.TestCase):
    def test_added_then_deleted_and_changed_blobs_count_across_all_commits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            def git(*args):
                result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
                return result.stdout.decode().strip()
            git("init", "-q")
            git("config", "user.email", "synthetic@example.invalid")
            git("config", "user.name", "Synthetic fixture")
            (root / "source").write_bytes(b"base")
            git("add", "."); git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            (root / "temporary").write_bytes(b"1234567")
            (root / "source").write_bytes(b"changed")
            git("add", "."); git("commit", "-qm", "generated")
            (root / "temporary").unlink()
            (root / "source").write_bytes(b"base")
            git("add", "."); git("commit", "-qm", "deleted and reverted")
            actual = git_blob_growth(root, base, blob_review_bytes=6, range_review_bytes=13)
            self.assertEqual(actual["new_blob_count"], 2)
            self.assertEqual(actual["new_blob_bytes"], 14)
            self.assertTrue(actual["review_required"])
            self.assertFalse(actual["enforced_rejection"])
            self.assertEqual(git_blob_growth(root, base, range_review_bytes=100)["new_blob_count"], 2)


if __name__ == "__main__":
    unittest.main()
