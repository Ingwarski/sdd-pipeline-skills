"""Operation-local catalog holds, using isolated synthetic originals only."""
from collections import Counter
from contextlib import closing
from copy import deepcopy
import json
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import test_catalog_inventory as fixtures
from evidence.accounting import Accounting, BudgetExceeded
from evidence.io import EvidenceError
from evidence.manager import Manager
from evidence.policy import load_defaults
from evidence.transports import ConnectedDriveTransport, LocalTransport

OWNED_PROCESSES = []


class CatalogWorkingScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-catalog-scope-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.policy = deepcopy(load_defaults())
        self.policy.update(project_id="11111111-1111-4111-8111-111111111111",
            store_id="22222222-2222-4222-8222-222222222222", provider="local")
        self.policy["limits"]["free_space_reserve_bytes"] = 0
        self.transport = LocalTransport(self.root / "durable")
        self.manager = Manager(self.transport, self.root / "home", self.policy)
        self.adapter = fixtures.CatalogFixture()
        def add(key, value):
            data = fixtures.canonical(value)
            target = self.root / "durable" / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return self.transport.stat(key), hashlib.sha256(data).hexdigest()
        add(self.manager.prefix + "authority/coordinator.json", {"version": 1,
            "project_id": self.policy["project_id"], "store_id": self.policy["store_id"],
            "coordinator": self.manager.coordinator})
        segments, roots = [], []
        for number in (1, 2):
            value = {"version": 1, "generation": {str(number): {"run_id": "run-" + str(number),
                "unit_id": "unit", "gross_bytes": number, "logical_files": number}}}
            digest = hashlib.sha256(fixtures.canonical(value)).hexdigest()
            locator, _ = add(self.manager.prefix + "indexes/" + digest + ".json", value)
            segments.append({"sha256": digest, "size": locator["size"], "locator": locator})
            value = {"version": 1, "project_id": self.policy["project_id"], "store_id": self.policy["store_id"],
                "sequence": number, "coordinator": self.manager.coordinator,
                "previous": roots[-1]["key"] if roots else None, "segments": list(segments)}
            digest = hashlib.sha256(fixtures.canonical(value)).hexdigest()
            locator, _ = add(self.manager.prefix + "roots/" + str(number).zfill(12) + "-" + digest + ".json", value)
            roots.append(locator)
        add(self.manager.prefix + "indexes/orphan.json", {"version": 1, "unused": "historical index"})
        self.db = self.manager.state / "accounting.sqlite"

    def rows(self):
        with closing(sqlite3.connect(self.db)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT * FROM working_reservations ORDER BY created,id")]

    def assert_closed(self):
        self.assertIsNone(self.manager._catalog_working)
        self.assertIsNone(self.manager._working_reservation)
        self.assertEqual(0, self.manager._working_depth)
        self.assertEqual(0, self.manager._catalog_lock_depth)
        self.assertEqual([], list(self.manager.staging.iterdir()))

    def connected(self, control=64):
        session = self.root / "host-session"
        session.mkdir()
        self.adapter.host_session_path = session
        self.adapter.working_overhead = lambda *, upload_bytes=0, download_bytes=0: control + max(upload_bytes, download_bytes)
        transport = ConnectedDriveTransport(self.adapter, "fixture-folder", state_dir=self.root / "transfers")
        manager = Manager(transport, self.root / "connected-home", {**self.policy, "provider": "google-drive"})
        self.adapter.objects.clear()
        self.objects = fixtures.seed_catalog(manager, self.adapter)
        self.adapter.requests.clear()
        self.transport, self.manager, self.db = transport, manager, manager.state / "accounting.sqlite"
        return session

    def test_three_independent_catalogs_have_three_settled_rows_and_complete_fresh_requests(self):
        self.connected(control=0)
        sequences = []
        for _ in range(3):
            self.adapter.requests.clear()
            self.assertEqual(2, self.manager._catalog()["sequence"])
            sequences.append([{key: value for key, value in request.items() if key != "destination_path"}
                for request in self.adapter.requests])
        self.assertEqual(sequences[0], sequences[1])
        self.assertEqual(sequences[0], sequences[2])
        self.assertEqual(5, Counter(x["operation"] for x in sequences[0])["download_original"])
        self.assertEqual(3, len(self.rows()))
        self.assertTrue(all(row["state"] == "settled" for row in self.rows()))
        with closing(sqlite3.connect(self.db)) as connection:
            for table in ("runs", "reservations", "durable_generation", "uncertain_generation"):
                self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0])
        self.assert_closed()

    def test_sequential_reuse_has_only_highwater_updates_and_still_checks_capacity(self):
        with self.manager.locked(), self.manager._catalog_working_scope() as scope:
            sql = []
            scope["ledger"].connection.set_trace_callback(sql.append)
            with patch.object(self.manager, "_capacity", wraps=self.manager._capacity) as capacity:
                for size in (100, 300, 100, 300):
                    with self.manager._catalog_working_lease(scope, size):
                        self.assertEqual(size, sum(scope["active"].values()))
                self.assertEqual([100, 300, 100, 300], [call.args[0] for call in capacity.call_args_list])
            self.assertEqual(300, scope["bounds"]["bytes"])
            self.assertEqual(2, sum(s.startswith("UPDATE working_reservations SET bytes=") for s in sql))
            self.assertEqual(0, sum(s.startswith("INSERT INTO working_reservations") for s in sql))
        self.assertEqual(300, self.rows()[0]["bytes"])
        self.assert_closed()

    def test_nested_json_and_host_materialization_sum_but_fixed_control_is_held_once(self):
        self.connected()
        seen = []
        original = self.transport.get
        def get(*args):
            scope = self.manager._catalog_working
            seen.append((args[2], scope["bounds"]["bytes"], sum(scope["active"].values()), scope["control"]))
            return original(*args)
        with patch.object(self.transport, "get", side_effect=get):
            self.manager._catalog()
        self.assertTrue(seen)
        self.assertTrue(all(held >= 64 + 2 * size and active == 2 * size and control == 64
            for size, held, active, control in seen))
        self.assertEqual(64 + 2 * max(x[0] for x in seen), self.rows()[0]["bytes"])
        self.assertEqual(64, self.rows()[0]["metadata_bytes"])
        self.assertEqual(3, self.rows()[0]["metadata_files"])
        self.assert_closed()

    def test_equal_size_reuse_rechecks_staging_and_host_free_space_before_effect(self):
        session = self.connected()
        with self.manager.locked(), self.manager._catalog_working_scope() as scope:
            with self.manager._catalog_working_lease(scope, 100, capacity_path=session):
                pass
            before = dict(scope["bounds"])
            real_disk = shutil.disk_usage
            def disk(path):
                value = real_disk(path)
                return value._replace(free=0) if Path(path) == session else value
            with patch("evidence.manager.shutil.disk_usage", side_effect=disk), \
                    self.assertRaisesRegex(EvidenceError, "host transport working peak"):
                with self.manager._catalog_working_lease(scope, 100, capacity_path=session):
                    self.fail("effect after failed fresh capacity")
            self.assertEqual(before, scope["bounds"])
            self.assertFalse(scope["active"])
            with patch("evidence.manager.shutil.disk_usage", return_value=real_disk(session)._replace(free=0)), \
                    self.assertRaisesRegex(EvidenceError, "free-space reserve unavailable"):
                with self.manager._catalog_working_lease(scope, 100):
                    self.fail("effect after failed fresh staging capacity")

    def test_growth_rejection_does_not_create_temp_or_call_get(self):
        with patch.object(Accounting, "grow_working", side_effect=BudgetExceeded(["synthetic admission"])), \
                patch.object(self.transport, "get", wraps=self.transport.get) as get, \
                patch("evidence.manager.tempfile.TemporaryDirectory", wraps=tempfile.TemporaryDirectory) as temporary:
            with self.assertRaisesRegex(BudgetExceeded, "synthetic admission"):
                self.manager._catalog()
        self.assertFalse(get.called)
        self.assertFalse(temporary.called)
        self.assertEqual(0, self.rows()[0]["bytes"])
        self.assertEqual("settled", self.rows()[0]["state"])
        self.assert_closed()

    def test_rejected_nested_lease_preserves_live_sibling_and_committed_bound(self):
        with self.manager.locked(), self.manager._catalog_working_scope() as scope:
            with self.manager._catalog_working_lease(scope, 100):
                before = dict(scope["bounds"])
                with patch.object(self.manager, "_capacity", side_effect=EvidenceError("synthetic full staging")), \
                        self.assertRaisesRegex(EvidenceError, "full staging"):
                    with self.manager._catalog_working_lease(scope, 200):
                        self.fail("nested payload after rejection")
                self.assertEqual(100, sum(scope["active"].values()))
                self.assertEqual(before, scope["bounds"])
            self.assertFalse(scope["active"])

    def test_hard_exit_after_growth_keeps_exact_pending_parent_on_reopen(self):
        code = '''import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from evidence.manager import Manager
from evidence.transports import LocalTransport
root = Path(sys.argv[2])
manager = Manager(LocalTransport(root / "durable"), root / "home", json.loads(sys.argv[3]))
with manager.locked(), manager._catalog_working_scope() as scope:
    with manager._catalog_working_lease(scope, 1024):
        os._exit(39)
'''
        process = subprocess.Popen([sys.executable, "-B", "-c", code,
            str(Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"),
            str(self.root), json.dumps(self.policy)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = process.communicate(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            OWNED_PROCESSES.append({"pid": process.pid, "returncode": process.returncode,
                "purpose": "isolated catalog hard-exit regression", "exit_observed": process.poll() is not None})
        self.assertEqual((39, b"", b""), (process.returncode, stdout, stderr))
        row = self.rows()[0]
        self.assertEqual(("pending", 1024, process.pid), (row["state"], row["bytes"], row["owner_pid"]))
        with Accounting(self.db, self.policy["project_id"], self.policy):
            pass
        self.assertEqual(row, self.rows()[0])
        self.assertIsNone(self.manager._catalog_working)

    def test_closed_foreign_and_cross_thread_tokens_reject_before_effect(self):
        other = Manager(self.transport, self.root / "other-home", self.policy)
        with self.manager.locked(), self.manager._catalog_working_scope() as scope:
            with other.locked(), self.assertRaisesRegex(EvidenceError, "closed, foreign"):
                with other._catalog_working_lease(scope, 100):
                    self.fail("foreign effect")
            errors = []
            def foreign_thread():
                try:
                    with self.manager._catalog_working_lease(scope, 100):
                        errors.append("unexpected lease")
                except EvidenceError as error:
                    errors.append(str(error))
            thread = threading.Thread(target=foreign_thread)
            thread.start()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertIn("closed, foreign", errors[0])
        with self.manager.locked(), self.assertRaisesRegex(EvidenceError, "closed, foreign"):
            with self.manager._catalog_working_lease(scope, 100):
                self.fail("closed effect")
        self.assert_closed()

    def test_reentrant_independent_catalog_fails_before_traversal(self):
        with self.manager.locked(), self.manager._catalog_working_scope(), \
                patch.object(self.manager, "_catalog_locked") as traversal:
            with self.assertRaisesRegex(EvidenceError, "cannot reenter"):
                self.manager._catalog()
            traversal.assert_not_called()
        self.assertEqual(1, len(self.rows()))

    def test_arbitrary_working_cannot_silently_borrow_catalog_parent(self):
        with self.manager.locked(), self.manager._catalog_working_scope(), \
                self.assertRaisesRegex(EvidenceError, "unleased working"):
            with self.manager._working(10):
                self.fail("unleased effect")
        self.assertEqual(0, self.manager._working_depth)

    def test_preexisting_working_and_policy_paths_preserve_fallback(self):
        with patch.object(self.manager, "_catalog_working_scope", wraps=self.manager._catalog_working_scope) as scoped:
            with self.manager._working(10000):
                previous = self.manager._working_reservation
                self.manager._catalog()
                self.assertEqual(previous, self.manager._working_reservation)
                self.assertEqual(1, self.manager._working_depth)
            self.manager._catalog(allow_policy_transition=True)
            with self.assertRaisesRegex(EvidenceError, "cold recovery requires"):
                self.manager._catalog(recover_policy=True)
            scoped.assert_not_called()
        self.assert_closed()

    def test_clean_local_parse_failure_settles_and_preserves_original_exception(self):
        original = self.transport.get
        def corrupt(*args):
            result = original(*args)
            Path(args[1]).write_bytes(b"{invalid")
            return result
        with patch.object(self.transport, "get", side_effect=corrupt):
            with self.assertRaises(EvidenceError) as caught:
                self.manager._catalog()
        self.assertIn("JSON", str(caught.exception))
        self.assertEqual("settled", self.rows()[0]["state"])
        self.assert_closed()

    def test_unknown_host_failure_retains_highwater_and_original_error_across_reopen(self):
        session = self.connected()
        def timeout(*args):
            (session / "request.json").write_text("{}")
            raise EvidenceError("synthetic timeout with retained request")
        with patch.object(self.transport, "get", side_effect=timeout), \
                self.assertRaisesRegex(EvidenceError, "synthetic timeout") as caught:
            self.manager._catalog()
        row = self.rows()[0]
        self.assertEqual("pending", row["state"])
        self.assertGreater(row["bytes"], 64)
        self.assertIn(row["id"], " ".join(caught.exception.__notes__))
        with Accounting(self.db, self.policy["project_id"], self.manager.policy):
            pass
        self.assertEqual(row, self.rows()[0])
        (session / "request.json").unlink()
        self.assert_closed()

    def test_success_with_unremoved_host_materialization_retains_parent(self):
        session = self.connected()
        original = self.transport.get
        def leak(*args):
            result = original(*args)
            (session / ("original-" + "a" * 32 + ".bin")).write_bytes(b"leaked")
            return result
        with patch.object(self.transport, "get", side_effect=leak), \
                self.assertRaisesRegex(EvidenceError, "cleanup is incomplete"):
            self.manager._catalog()
        self.assertEqual("pending", self.rows()[0]["state"])
        (session / ("original-" + "a" * 32 + ".bin")).unlink()
        self.assert_closed()

    def test_inside_state_host_leaks_retain_parent_independently_of_occupancy_dedup(self):
        previous = self.connected()
        session = self.manager.state / "host-session"
        previous.rename(session)
        self.adapter.host_session_path = session
        self.assertEqual([], self.manager._transport_records())
        original = self.transport.get
        for name in ("original-" + "b" * 32 + ".bin", "request.json", "response.json"):
            with self.subTest(name=name):
                def leak(*args):
                    result = original(*args)
                    (session / name).write_bytes(b"{}")
                    return result
                try:
                    with patch.object(self.transport, "get", side_effect=leak), \
                            self.assertRaisesRegex(EvidenceError, "cleanup is incomplete"):
                        self.manager._catalog()
                    row = self.rows()[-1]
                    self.assertEqual("pending", row["state"])
                    authority_size = len(next(item["bytes"] for item in self.adapter.objects.values()
                        if "/authority/" in item["key"]))
                    self.assertEqual(64 + 2 * authority_size, row["bytes"])
                    self.assertEqual((64, 3), (row["metadata_bytes"], row["metadata_files"]))
                finally:
                    (session / name).unlink(missing_ok=True)
                self.assert_closed()

    def test_clean_host_sessions_inside_or_equal_to_state_are_valid_and_counted_once(self):
        previous = self.connected()
        session = self.manager.state / "host-session"
        previous.rename(session)
        for folder in (session, self.manager.state):
            with self.subTest(folder=folder):
                self.adapter.host_session_path = folder
                self.assertEqual([], self.manager._transport_records())
                measured = []
                original = Accounting.finish_working
                def finish(ledger, *args, **kwargs):
                    records = self.manager._metadata_records(include_checkpoints=False)
                    self.assertEqual(len(records), len(set(records)))
                    self.assertEqual(self.manager._existing_bytes(records), kwargs["actual_metadata_bytes"])
                    self.assertEqual(len(records), kwargs["actual_metadata_files"])
                    measured.append((kwargs["actual_metadata_bytes"], kwargs["actual_metadata_files"]))
                    return original(ledger, *args, **kwargs)
                with patch.object(Accounting, "finish_working", finish):
                    self.assertEqual(2, self.manager._catalog()["sequence"])
                row = self.rows()[-1]
                self.assertEqual("settled", row["state"])
                self.assertEqual((64, 3), (row["metadata_bytes"], row["metadata_files"]))
                with Accounting(self.db, self.manager.policy["project_id"], self.manager.policy) as ledger:
                    totals = ledger._totals()
                    self.assertEqual(0, totals["pending_working_bytes"])
                    actual = tuple(ledger.connection.execute("SELECT bytes,files FROM metadata_usage WHERE key='local-journals-receipts'").fetchone())
                    self.assertEqual([actual], measured)
                self.assert_closed()

    def test_missing_unreadable_or_linked_inside_state_session_retains_parent(self):
        previous = self.connected()
        session = self.manager.state / "host-session"
        previous.rename(session)
        self.adapter.host_session_path = session
        external = self.root / "untrusted-session-target"
        external.mkdir()
        sentinel = external / "request.json"
        sentinel.write_bytes(b"unrelated original bytes")
        original_get, original_scandir = self.transport.get, os.scandir
        for problem in ("missing", "unreadable", "linked"):
            with self.subTest(problem=problem):
                changed = []
                def get(*args):
                    result = original_get(*args)
                    changed.append(True)
                    if problem in ("missing", "linked"):
                        session.rmdir()
                    if problem == "linked":
                        session.symlink_to(external, target_is_directory=True)
                    return result
                def scandir(path):
                    if problem == "unreadable" and changed and not isinstance(path, int) and Path(path) == session:
                        raise PermissionError("synthetic unreadable native session")
                    return original_scandir(path)
                try:
                    with patch.object(self.transport, "get", side_effect=get), \
                            patch("evidence.manager.os.scandir", side_effect=scandir), \
                            self.assertRaises(EvidenceError):
                        self.manager._catalog()
                    row = self.rows()[-1]
                    self.assertEqual("pending", row["state"])
                    self.assertGreater(row["bytes"], 64)
                    self.assertEqual(b"unrelated original bytes", sentinel.read_bytes())
                finally:
                    if session.is_symlink():
                        session.unlink()
                    if not session.exists():
                        session.mkdir()
                self.assert_closed()

    def test_lost_grow_commit_ack_retains_committed_highwater(self):
        grow = Accounting.grow_working
        def lost(ledger, *args, **kwargs):
            grow(ledger, *args, **kwargs)
            raise OSError("synthetic lost growth COMMIT acknowledgement")
        with patch.object(Accounting, "grow_working", lost), \
                patch.object(self.transport, "get", wraps=self.transport.get) as get, \
                self.assertRaisesRegex(OSError, "lost growth COMMIT"):
            self.manager._catalog()
        self.assertFalse(get.called)
        self.assertEqual("pending", self.rows()[0]["state"])
        self.assertGreater(self.rows()[0]["bytes"], 0)
        self.assert_closed()

    def test_cleanup_error_preserves_parse_exception_and_full_hold(self):
        cleanup = tempfile.TemporaryDirectory.cleanup
        def broken(temporary):
            cleanup(temporary)
            raise OSError("synthetic cleanup acknowledgement lost")
        with patch("evidence.manager.read_json", side_effect=EvidenceError("original parse failure")), \
                patch("evidence.manager.tempfile.TemporaryDirectory.cleanup", broken), \
                self.assertRaisesRegex(EvidenceError, "original parse failure") as caught:
            self.manager._catalog()
        self.assertIn("cleanup acknowledgement lost", " ".join(caught.exception.__notes__))
        self.assertEqual("pending", self.rows()[0]["state"])
        self.assert_closed()

    def test_failed_final_audit_and_finish_keep_parent_pending(self):
        for point in ("audit", "finish"):
            with self.subTest(point=point):
                if point == "audit":
                    original = self.manager._audit_source_payloads
                    def audit():
                        if self.manager._catalog_working is not None:
                            raise EvidenceError("synthetic final audit failure")
                        return original()
                    fault = patch.object(self.manager, "_audit_source_payloads", side_effect=audit)
                else:
                    fault = patch.object(Accounting, "finish_working", side_effect=OSError("synthetic finish failure"))
                with fault, self.assertRaisesRegex((EvidenceError, OSError), "synthetic"):
                    self.manager._catalog()
                self.assertEqual("pending", self.rows()[-1]["state"])
                self.assert_closed()

    def test_full_historical_rows_and_recovery_checkpoint_bytes_are_unchanged(self):
        with Accounting(self.db, self.policy["project_id"], self.policy) as ledger:
            held = ledger.reserve("historical-failure", "old-unit", 100, 1, local_bytes=10)
            ledger.record_uncertain(held, 70, 1)
            ledger.mark_incomplete("historical-failure")
            old_working = ledger.reserve_working(80)
            ledger.finish_working(old_working)
        tables = ("runs", "reservations", "uncertain_generation", "durable_generation", "outputs", "observations", "producer_sessions", "producer_quarantines")
        def history():
            with closing(sqlite3.connect(self.db)) as connection:
                rows = {table: connection.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall() for table in tables}
                rows["old_working"] = connection.execute("SELECT * FROM working_reservations WHERE id=?", (old_working,)).fetchall()
            recovery = Path(str(self.db) + ".recovery")
            return rows, {p.name: p.read_bytes() for p in recovery.iterdir() if p.name == "marker.json" or p.name.startswith("run-")}
        before = history()
        self.manager._catalog()
        self.assertEqual(before, history())
        with patch.object(Accounting, "grow_working", side_effect=BudgetExceeded(["reject"])), \
                self.assertRaises(BudgetExceeded):
            self.manager._catalog()
        self.assertEqual(before, history())


if __name__ == "__main__":
    unittest.main()
