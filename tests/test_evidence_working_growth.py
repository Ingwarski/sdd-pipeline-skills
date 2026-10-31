"""Isolated ledger regressions for absolute, monotonic working bounds."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import test_evidence_run_recovery as fixtures
from evidence import accounting

TEMP_ROOTS = []
DIMENSIONS = ("bytes", "metadata_bytes", "metadata_files", "cache_bytes")


class WorkingGrowthTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing isolated fixture without importing or inheriting its
        # TestCase, which would duplicate its independently owned tests.
        self.fixture = fixtures.WorkingReservationTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        TEMP_ROOTS.append(str(self.root))
        self.addCleanup(self.cleanup_fixture)
        self.policy = self.fixture.policy
        self.policy["limits"].update(local_stop_bytes=16 * 1024**2,
            metadata_stop_bytes=4 * 1024**2, metadata_stop_files=100,
            cache_stop_bytes=1024**2)

    def cleanup_fixture(self):
        self.fixture.doCleanups()
        self.assertFalse(self.root.exists(), str(self.root))

    def ledger(self):
        return self.fixture.ledger()

    def row(self, ledger, identifier):
        row = ledger.connection.execute("SELECT * FROM working_reservations WHERE id=?", (identifier,)).fetchone()
        return dict(row) if row is not None else None

    def bounds(self, row):
        return {key: row[key] for key in DIMENSIONS}

    def history(self, ledger):
        tables = [row[0] for row in ledger.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name!='working_reservations' ORDER BY name")]
        return {name: sorted(tuple(row) for row in ledger.connection.execute('SELECT * FROM "' + name + '"'))
                for name in tables}

    def checkpoint_bytes(self, ledger):
        return {path.name: path.read_bytes() for path in ledger.recovery_dir.iterdir()}

    def test_absolute_componentwise_growth_and_unchanged_reuse_have_no_child_rows(self):
        with self.ledger() as ledger:
            identifier = ledger.reserve_working(100, metadata_bytes=20, metadata_files=1, cache_bytes=10)
            original = self.row(ledger, identifier)
            schema = list(ledger.connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name"))
            statements = []
            ledger.connection.set_trace_callback(statements.append)
            try:
                returned = ledger.grow_working(identifier, 300, metadata_bytes=40, metadata_files=2, cache_bytes=30)
                self.assertEqual(self.bounds(returned), dict(bytes=300, metadata_bytes=40, metadata_files=2, cache_bytes=30))
                self.assertEqual(sum(sql.startswith("UPDATE working_reservations") for sql in statements), 1)
                self.assertEqual(statements[0], "BEGIN IMMEDIATE")
                self.assertEqual(statements[-1], "COMMIT")
                statements.clear()
                for size in (300, 100, 0):
                    returned = ledger.grow_working(identifier, size)
                    self.assertEqual(self.bounds(returned), dict(bytes=300, metadata_bytes=40, metadata_files=2, cache_bytes=30))
                self.assertFalse(any(sql.startswith(("UPDATE ", "INSERT ", "DELETE ")) for sql in statements))
            finally:
                ledger.connection.set_trace_callback(None)
            final = self.row(ledger, identifier)
            self.assertEqual({key: value for key, value in final.items() if key not in DIMENSIONS},
                             {key: value for key, value in original.items() if key not in DIMENSIONS})
            self.assertEqual(ledger.connection.execute("SELECT COUNT(*) FROM working_reservations").fetchone()[0], 1)
            self.assertEqual(list(ledger.connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name")), schema)

    def test_invalid_amounts_and_identity_leave_exact_pending_bounds(self):
        with self.ledger() as ledger:
            identifier = ledger.reserve_working(100)
            before = self.row(ledger, identifier)
            for key in DIMENSIONS:
                for value in (-1, True, 1.5, float("inf"), 2**63):
                    args = {"byte_count": 100, key if key != "bytes" else "byte_count": value}
                    with self.subTest(key=key, value=value), self.assertRaises(accounting.EvidenceError):
                        ledger.grow_working(identifier, **args)
                    self.assertEqual(self.row(ledger, identifier), before)
            for invalid in ("", None, True, "bad\nidentity"):
                with self.subTest(identity=invalid), self.assertRaises(accounting.EvidenceError):
                    ledger.grow_working(invalid, 200)
            with self.assertRaises(accounting.EvidenceError):
                ledger.grow_working(identifier, 100, cache_bytes=101)
            self.assertEqual(self.row(ledger, identifier), before)
            self.assertFalse(ledger.connection.in_transaction)

    def test_missing_settled_foreign_and_unknown_owner_cannot_grow(self):
        with self.ledger() as ledger:
            with self.assertRaises(accounting.EvidenceError):
                ledger.grow_working("missing", 100)
            for change, value in (("owner_pid", 2**30), ("owner_host", "foreign.invalid"),
                                  ("owner_pid", None), ("owner_host", None), ("state", "settled"),
                                  ("state", "cancelled")):
                identifier = ledger.reserve_working(100)
                ledger.connection.execute("UPDATE working_reservations SET " + change + "=? WHERE id=?", (value, identifier))
                before = self.row(ledger, identifier)
                with self.subTest(change=change, value=value), self.assertRaises(accounting.EvidenceError):
                    ledger.grow_working(identifier, 200)
                self.assertEqual(self.row(ledger, identifier), before)

    def test_each_capacity_limit_rolls_back_all_dimensions_and_keeps_sibling(self):
        for limit in ("local", "metadata_bytes", "metadata_files", "cache", "free"):
            with self.subTest(limit=limit), self.ledger() as ledger:
                identifier = ledger.reserve_working(100, metadata_bytes=10, metadata_files=1, cache_bytes=10)
                sibling = ledger.reserve_working(100)
                before, other = self.row(ledger, identifier), self.row(ledger, sibling)
                totals = ledger._totals()
                original_limits = deepcopy(ledger.policy["limits"])
                if limit == "local":
                    ledger.policy["limits"]["local_stop_bytes"] = totals["local_bytes"] + totals["pending_local_bytes"] + 99
                elif limit == "metadata_bytes":
                    ledger.policy["limits"]["metadata_stop_bytes"] = totals["metadata_bytes"] + totals["pending_metadata_bytes"] + 9
                elif limit == "metadata_files":
                    ledger.policy["limits"]["metadata_stop_files"] = totals["metadata_files"] + totals["pending_metadata_files"]
                elif limit == "cache":
                    ledger.policy["limits"]["cache_stop_bytes"] = totals["cache_bytes"] + totals["pending_cache_bytes"] + 9
                capacity = SimpleNamespace(free=totals["pending_local_bytes"] + 99 if limit == "free" else 2**40)
                try:
                    with patch.object(accounting.shutil, "disk_usage", return_value=capacity), self.assertRaises(accounting.BudgetExceeded):
                        ledger.grow_working(identifier, 200, metadata_bytes=20, metadata_files=2, cache_bytes=20)
                    self.assertEqual(self.row(ledger, identifier), before)
                    self.assertEqual(self.row(ledger, sibling), other)
                    self.assertFalse(ledger.connection.in_transaction)
                finally:
                    ledger.policy["limits"].update(original_limits)
                    ledger.finish_working(identifier)
                    ledger.finish_working(sibling)

    def test_fresh_capacity_path_errors_and_free_floor_leave_old_bounds(self):
        with self.ledger() as ledger:
            identifier = ledger.reserve_working(100)
            before = self.row(ledger, identifier)
            capacity_path = self.root / "host-session"
            for size in (100, 200):
                with patch.object(accounting.shutil, "disk_usage", side_effect=OSError("synthetic disk failure")) as disk:
                    with self.assertRaisesRegex(OSError, "synthetic disk failure"):
                        ledger.grow_working(identifier, size, capacity_path=capacity_path)
                    disk.assert_called_once_with(capacity_path)
                self.assertEqual(self.row(ledger, identifier), before)
                self.assertFalse(ledger.connection.in_transaction)
            with patch.object(accounting.shutil, "disk_usage", return_value=SimpleNamespace(free=99)):
                with self.assertRaises(accounting.BudgetExceeded):
                    ledger.grow_working(identifier, 100)
            self.assertEqual(self.row(ledger, identifier), before)

    def test_zero_metadata_cache_recovery_and_migration_semantics_match_reserve(self):
        with self.ledger() as ledger:
            identifier = ledger.reserve_working(100, migration=True)
            ledger.reconcile_metadata("over-budget", 100, 1)
            ledger.reconcile_local("over-cache", 100, "cache")
            ledger.policy["limits"].update(metadata_stop_bytes=1, metadata_stop_files=1,
                                           cache_stop_bytes=1, local_stop_bytes=1)
            ledger.grow_working(identifier, 200)
            before = self.row(ledger, identifier)
            self.assertEqual(before["migration"], 1)
            for kwargs in ({"metadata_bytes": 1}, {"metadata_files": 1}, {"cache_bytes": 1}):
                with self.subTest(kwargs=kwargs), self.assertRaises(accounting.BudgetExceeded):
                    ledger.grow_working(identifier, 200, **kwargs)
                self.assertEqual(self.row(ledger, identifier), before)

    def test_two_clients_atomic_growth_admits_only_fitting_bound(self):
        for dimension in ("local", "metadata_bytes", "metadata_files", "cache"):
            self.policy["limits"].update(local_stop_bytes=16 * 1024**2,
                metadata_stop_bytes=4 * 1024**2, metadata_stop_files=100, cache_stop_bytes=4 * 1024**2)
            with self.subTest(dimension=dimension):
                with self.ledger() as ledger:
                    identifiers = [ledger.reserve_working(100000, metadata_bytes=100000,
                        metadata_files=1, cache_bytes=100000) for _ in range(2)]
                    totals = ledger._totals()
                    key, total_key, pending_key, margin = {
                        "local": ("local_stop_bytes", "local_bytes", "pending_local_bytes", 700000),
                        "metadata_bytes": ("metadata_stop_bytes", "metadata_bytes", "pending_metadata_bytes", 700000),
                        "metadata_files": ("metadata_stop_files", "metadata_files", "pending_metadata_files", 3),
                        "cache": ("cache_stop_bytes", "cache_bytes", "pending_cache_bytes", 700000),
                    }[dimension]
                    self.policy["limits"][key] = totals[total_key] + totals[pending_key] + margin
                    if dimension == "local":
                        self.policy["limits"]["cache_stop_bytes"] = self.policy["limits"][key]
                barrier = threading.Barrier(2)
                def grow(identifier):
                    with self.ledger() as client:
                        barrier.wait(timeout=10)
                        try:
                            kwargs = {"local": {}, "metadata_bytes": {"metadata_bytes": 600000},
                                "metadata_files": {"metadata_files": 3}, "cache": {"cache_bytes": 600000}}[dimension]
                            client.grow_working(identifier, 600000, **kwargs)
                            return True
                        except accounting.BudgetExceeded:
                            return False
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(grow, identifiers))
                self.assertEqual(sorted(results), [False, True])
                with self.ledger() as ledger:
                    self.assertEqual(sorted(self.row(ledger, item)["bytes"] for item in identifiers), [100000, 600000])
                    self.assertTrue(all(self.row(ledger, item)["state"] == "pending" for item in identifiers))
                    for identifier in identifiers:
                        ledger.finish_working(identifier)

    def test_finish_growth_race_never_resurrects_finished_reservation(self):
        with self.ledger() as ledger:
            identifier = ledger.reserve_working(100)
        barrier = threading.Barrier(2)
        def operate(growing):
            with self.ledger() as client:
                barrier.wait(timeout=10)
                if growing:
                    try:
                        client.grow_working(identifier, 200)
                        return "grown"
                    except accounting.EvidenceError:
                        return "rejected"
                client.finish_working(identifier)
                return "finished"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(operate, (True, False)))
        self.assertIn(results[0], ("grown", "rejected"))
        self.assertEqual(results[1], "finished")
        with self.ledger() as ledger:
            row = self.row(ledger, identifier)
            self.assertEqual(row["state"], "cancelled")
            self.assertEqual(row["bytes"], 200 if results[0] == "grown" else 100)
            with self.assertRaises(accounting.EvidenceError):
                ledger.grow_working(identifier, 300)
            self.assertEqual(self.row(ledger, identifier), row)

    def test_sql_update_failure_rolls_back_and_committed_growth_survives_reopen(self):
        with self.ledger() as ledger:
            identifier = ledger.reserve_working(100, metadata_bytes=10, metadata_files=1, cache_bytes=10)
            before = self.row(ledger, identifier)
            ledger.connection.execute("CREATE TEMP TRIGGER fail_growth AFTER UPDATE OF bytes ON working_reservations BEGIN SELECT RAISE(ABORT, 'synthetic growth failure'); END")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "synthetic growth failure"):
                ledger.grow_working(identifier, 200, metadata_bytes=20, metadata_files=2, cache_bytes=20)
            self.assertEqual(self.row(ledger, identifier), before)
            self.assertFalse(ledger.connection.in_transaction)
            ledger.connection.execute("DROP TRIGGER fail_growth")
            ledger.grow_working(identifier, 200, metadata_bytes=20, metadata_files=2, cache_bytes=20)
            committed = self.row(ledger, identifier)
        with self.ledger() as ledger:
            self.assertEqual(self.row(ledger, identifier), committed)
            self.assertEqual(ledger._totals()["pending_working_bytes"], 200)

    def test_commit_failure_leaves_exact_old_pending_vector(self):
        with self.ledger() as ledger:
            identifier = ledger.reserve_working(100, metadata_bytes=10, metadata_files=1, cache_bytes=10)
            original = self.row(ledger, identifier)
            connection = ledger.connection
            class FailCommitOnce:
                failed = False
                def __getattr__(self, name):
                    return getattr(connection, name)
                def execute(self, sql, *args):
                    if sql == "COMMIT" and not self.failed:
                        self.failed = True
                        raise sqlite3.OperationalError("synthetic commit failure")
                    return connection.execute(sql, *args)
            ledger.connection = FailCommitOnce()
            try:
                with self.assertRaisesRegex(sqlite3.OperationalError, "synthetic commit failure"):
                    ledger.grow_working(identifier, 200, metadata_bytes=20, metadata_files=2, cache_bytes=20)
                self.assertEqual(self.row(ledger, identifier), original)
                self.assertFalse(connection.in_transaction)
            finally:
                ledger.connection = connection
        with self.ledger() as ledger:
            self.assertEqual(self.row(ledger, identifier), original)

    def test_success_rejection_and_reopen_preserve_exact_history_old_holds_and_checkpoints(self):
        with self.ledger() as ledger:
            failed = ledger.reserve("historical-failed-run", "historical-unit", 100, 1, local_bytes=100)
            ledger.record_uncertain(failed, 7, 1)
            output = self.root / "historical-output"
            output.mkdir()
            ledger.register_output("historical-failed-run", "historical-unit", output)
            old = ledger.reserve_working(70)
            ledger.connection.execute("UPDATE working_reservations SET owner_host='unknown.invalid' WHERE id=?", (old,))
            ledger.connection.execute("INSERT INTO producer_sessions VALUES('sentinel-session','{\"status\":\"failed\"}')")
            ledger.connection.execute("INSERT INTO producer_quarantines VALUES('sentinel-quarantine','{\"original\":\"preserve\"}')")
            ledger.reconcile_generation({"historical-charge": {"run_id": "durable-old", "unit_id": "historical-unit", "gross_bytes": 9, "logical_files": 1}})
            identifier = ledger.reserve_working(100)
            prior_history, checkpoints, old_row = self.history(ledger), self.checkpoint_bytes(ledger), self.row(ledger, old)
            ledger.grow_working(identifier, 200)
            with self.assertRaises(accounting.EvidenceError):
                ledger.grow_working(identifier, -1)
            self.assertEqual(self.history(ledger), prior_history)
            self.assertEqual(self.checkpoint_bytes(ledger), checkpoints)
            self.assertEqual(self.row(ledger, old), old_row)
        with self.ledger() as ledger:
            self.assertEqual(self.history(ledger), prior_history)
            self.assertEqual(self.checkpoint_bytes(ledger), checkpoints)
            self.assertEqual(self.row(ledger, old), old_row)
            self.assertEqual(self.row(ledger, identifier)["bytes"], 200)
            ledger.finish_working(identifier)
            self.assertEqual(self.history(ledger), prior_history)
            self.assertEqual(self.checkpoint_bytes(ledger), checkpoints)
            self.assertEqual(self.row(ledger, old), old_row)
