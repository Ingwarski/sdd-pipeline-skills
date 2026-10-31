"""Real disposable SQLite rows; no producer processes, remote store or product."""
import ast
from copy import deepcopy
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence.accounting import Accounting
from evidence.io import EvidenceError
from evidence.policy import load_defaults
from evidence import producer, producer_runtime as runtime


class NoopWriteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-noop-writes-")
        self.root = Path(self.temporary.name).resolve()
        self.clients = []
        self.addCleanup(self.cleanup)
        self.policy = load_defaults()
        self.policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider="local")
        self.path = self.root / "machine" / "accounting.sqlite"
        self.ledger = self.client()
        self.output = self.root / "output"
        self.output.mkdir()
        self.reservation = self.ledger.reserve("synthetic-run", "synthetic-unit", 65536, 20,
                                               metadata_bytes=runtime.MAX_RECORD, capacity_path=self.output)
        output_id = self.ledger.register_output("synthetic-run", "synthetic-unit", self.output)
        self.attempt = str(uuid.uuid4())
        # Portable structure only: no process lookup, launch or ownership claim.
        coordinator = {"version": 1, "host": "synthetic.invalid", "platform": "darwin", "pid": 123,
                       "created": {"seconds": 1, "microseconds": 0}}
        self.record = {"version": 1, "attempt_id": self.attempt, "run_id": "synthetic-run",
                       "unit_id": "synthetic-unit", "reservation_id": self.reservation,
                       "output_id": output_id, "output_dir": str(self.output), "output_identity": [1, 2],
                       "coordinator": coordinator, "policy": deepcopy(self.policy), "processes": {},
                       "resources": [], "status": "running", "observed_bytes": 7, "observed_files": 1}
        self.ledger.connection.execute("INSERT INTO producer_sessions VALUES(?,?)",
                                       (self.attempt, self.encode(self.record)))

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)

    def client(self):
        ledger = Accounting(self.path, self.policy["project_id"], self.policy)
        self.clients.append(ledger)
        return ledger

    def cleanup(self):
        for ledger in reversed(self.clients):
            ledger.close()
        self.temporary.cleanup()
        self.assertFalse(self.root.exists())

    def raw(self, ledger=None):
        return (ledger or self.ledger).connection.execute(
            "SELECT record FROM producer_sessions WHERE id=?", (self.attempt,)).fetchone()[0]

    def traced(self, operation, *, writes):
        connection = self.ledger.connection
        statements = []
        before = connection.total_changes
        connection.set_trace_callback(statements.append)
        try:
            result = operation()
        finally:
            connection.set_trace_callback(None)
        self.assertEqual(connection.total_changes - before, writes)
        self.assertEqual(statements[0], "BEGIN IMMEDIATE")
        self.assertEqual(statements[-1], "COMMIT")
        return result, statements

    def test_identical_session_keeps_transaction_validation_and_calls_callback_once(self):
        callback = Mock(side_effect=lambda value: value.update(observed_bytes=7, observed_files=1))
        with patch.object(runtime, "read", wraps=runtime.read) as read:
            result, trace = self.traced(lambda: runtime.update(self.ledger, self.attempt, callback), writes=0)
        callback.assert_called_once()
        read.assert_called_once_with(self.ledger, self.attempt)
        self.assertEqual(result, self.record)
        self.assertFalse(any(sql.startswith("UPDATE producer_sessions") for sql in trace))

    def test_genuine_session_change_persists_and_next_call_is_noop(self):
        changed, _ = self.traced(lambda: runtime.update(self.ledger, self.attempt,
            lambda value: value.update(observed_bytes=19, observed_files=2)), writes=1)
        self.assertEqual(self.raw(), self.encode(changed))
        self.traced(lambda: runtime.update(self.ledger, self.attempt, lambda value: None), writes=0)
        self.assertEqual(json.loads(self.raw(self.client()))["observed_bytes"], 19)

    def test_semantically_equal_but_differently_serialized_record_is_written_once(self):
        self.ledger.connection.execute("UPDATE producer_sessions SET record=? WHERE id=?",
                                       (json.dumps(self.record, indent=2), self.attempt))
        self.traced(lambda: runtime.update(self.ledger, self.attempt, lambda value: None), writes=1)
        self.assertEqual(self.raw(), self.encode(self.record))
        self.traced(lambda: runtime.update(self.ledger, self.attempt, lambda value: None), writes=0)

    def test_callback_exception_rolls_back_without_changing_original_record(self):
        before = self.raw()
        def fail(value):
            value["observed_bytes"] = 200
            raise RuntimeError("synthetic callback failure")
        callback = Mock(side_effect=fail)
        with self.assertRaisesRegex(RuntimeError, "synthetic callback failure"):
            runtime.update(self.ledger, self.attempt, callback)
        callback.assert_called_once()
        self.assertFalse(self.ledger.connection.in_transaction)
        self.assertEqual(self.raw(), before)

    def test_oversize_and_serialization_errors_still_call_once_and_preserve_record(self):
        before = self.raw()
        for payload, error in (("x" * runtime.MAX_RECORD, EvidenceError), (object(), TypeError)):
            callback = Mock(side_effect=lambda value: value.update(payload=payload))
            with self.subTest(error=error.__name__), self.assertRaises(error):
                runtime.update(self.ledger, self.attempt, callback)
            callback.assert_called_once()
            self.assertEqual(self.raw(), before)
            self.assertFalse(self.ledger.connection.in_transaction)

    def test_missing_or_invalid_session_fails_before_callback(self):
        callback = Mock()
        with self.assertRaisesRegex(EvidenceError, "missing producer ownership"):
            runtime.update(self.ledger, str(uuid.uuid4()), callback)
        self.ledger.connection.execute("UPDATE producer_sessions SET record=? WHERE id=?",
                                       (self.encode({**self.record, "status": "invalid"}), self.attempt))
        with self.assertRaisesRegex(EvidenceError, "invalid producer ownership/binding"):
            runtime.update(self.ledger, self.attempt, callback)
        callback.assert_not_called()

    def test_stale_reservation_and_output_bindings_still_fail_before_callback(self):
        other = self.client()
        other.reserve("foreign-run", "synthetic-unit", 1, 1, capacity_path=self.output)
        for table, field, value in (("reservations", "run_id", "foreign-run"),
                                    ("outputs", "path", str(self.root / "foreign"))):
            key = self.reservation if table == "reservations" else self.record["output_id"]
            old = other.connection.execute(f"SELECT {field} FROM {table} WHERE id=?", (key,)).fetchone()[0]
            other.connection.execute(f"UPDATE {table} SET {field}=? WHERE id=?", (value, key))
            callback = Mock()
            try:
                with self.subTest(table=table), self.assertRaisesRegex(EvidenceError, "binding changed"):
                    runtime.update(self.ledger, self.attempt, callback)
                callback.assert_not_called()
            finally:
                other.connection.execute(f"UPDATE {table} SET {field}=? WHERE id=?", (old, key))

    def test_unresolved_changed_policy_still_rejects_a_noop_callback(self):
        changed = deepcopy(self.record)
        changed["policy"]["limits"]["max_unit_retries"] += 1
        self.ledger.connection.execute("UPDATE producer_sessions SET record=? WHERE id=?",
                                       (self.encode(changed), self.attempt))
        callback = Mock()
        with self.assertRaisesRegex(EvidenceError, "unresolved producer policy changed"):
            runtime.update(self.ledger, self.attempt, callback)
        callback.assert_not_called()

    def test_second_worker_session_change_is_fresh_and_retained_by_noop(self):
        other = self.client()
        runtime.update(other, self.attempt, lambda value: value.update(worker_note="fresh"))
        result, _ = self.traced(lambda: runtime.update(self.ledger, self.attempt,
            lambda value: value.update(observed_bytes=7, observed_files=1)), writes=0)
        self.assertEqual(result["worker_note"], "fresh")
        self.assertEqual(json.loads(self.raw(other))["worker_note"], "fresh")

    def test_deletion_only_actual_observer_call_does_not_rewrite_same_counters(self):
        payload = self.output / "temporary.txt"
        payload.write_bytes(b"payload")
        expected_output_identity = runtime.directory_identity(self.output)
        initial = producer._inventory(self.output, expected_identity=expected_output_identity)
        # Run the actual nested observer without launching a producer, guardian,
        # subprocess or OS scanner. Its only output change is this file deletion.
        function = ast.parse(inspect.getsource(producer._run_monitored)).body[0]
        observe = next(node for node in function.body if isinstance(node, ast.FunctionDef) and node.name == "observe")
        factory = ast.parse("def fixture():\n previous=initial\n gross_bytes=7\n gross_files=1\n last_inventory=initial\n").body[0]
        factory.body.extend([observe, ast.Return(value=ast.Name(id="observe", ctx=ast.Load()))])
        module = ast.fix_missing_locations(ast.Module(body=[factory], type_ignores=[]))
        scope = {"initial": initial, "root": self.output, "_inventory": producer._inventory,
                 "expected_output_identity": expected_output_identity,
                 "runtime": runtime, "ledger": self.ledger, "attempt": self.attempt}
        exec(compile(module, "<actual-producer-observer>", "exec"), scope)
        poll = scope["fixture"]()
        payload.unlink()
        with patch.object(runtime, "update", wraps=runtime.update) as update:
            _, trace = self.traced(lambda: poll(check_limits=False), writes=0)
        update.assert_called_once()
        self.assertFalse(any(sql.startswith("UPDATE producer_sessions") for sql in trace))
        self.assertEqual(json.loads(self.raw())["observed_bytes"], 7)

    def test_local_missing_changed_and_reclassified_rows_write_identical_rows_do_not(self):
        self.traced(lambda: self.ledger.reconcile_local("fixture", 10, "cache"), writes=1)
        self.traced(lambda: self.ledger.reconcile_local("fixture", 10, "cache"), writes=0)
        self.traced(lambda: self.ledger.reconcile_local("fixture", 11, "cache"), writes=1)
        self.traced(lambda: self.ledger.reconcile_local("fixture", 11, "staging"), writes=1)
        self.traced(lambda: self.ledger.reconcile_local("fixture", 11, "staging"), writes=0)

    def test_metadata_missing_bytes_and_file_count_changes_write(self):
        self.traced(lambda: self.ledger.reconcile_metadata("fixture", 10, 1), writes=1)
        self.traced(lambda: self.ledger.reconcile_metadata("fixture", 10, 1), writes=0)
        self.traced(lambda: self.ledger.reconcile_metadata("fixture", 11, 1), writes=1)
        self.traced(lambda: self.ledger.reconcile_metadata("fixture", 11, 2), writes=1)
        self.traced(lambda: self.ledger.reconcile_metadata("fixture", 11, 2), writes=0)

    def test_usage_comparison_reads_fresh_worker_values_not_cached_values(self):
        other = self.client()
        for method, arguments, changed in (("reconcile_local", ("fixture", 10, "cache"), ("fixture", 20, "staging")),
                                            ("reconcile_metadata", ("fixture", 10, 1), ("fixture", 20, 2))):
            with self.subTest(method=method):
                getattr(self.ledger, method)(*arguments)
                getattr(other, method)(*changed)
                self.traced(lambda: getattr(self.ledger, method)(*arguments), writes=1)
                self.traced(lambda: getattr(self.ledger, method)(*arguments), writes=0)

    def test_noop_usage_still_computes_fresh_totals_and_violations(self):
        self.ledger.reconcile_local("fixture-cache", 20, "cache")
        self.ledger.reconcile_metadata("fixture-metadata", 10, 1)
        self.client().reconcile_local("other-cache", 30, "cache")
        self.ledger.policy["limits"]["cache_stop_bytes"] = 40
        self.ledger.policy["limits"]["metadata_stop_bytes"] = 1
        for method, arguments in (("reconcile_local", ("fixture-cache", 20, "cache")),
                                  ("reconcile_metadata", ("fixture-metadata", 10, 1))):
            with self.subTest(method=method), patch.object(self.ledger, "_totals", wraps=self.ledger._totals) as totals, \
                    patch.object(self.ledger, "_violations", wraps=self.ledger._violations) as violations:
                result, _ = self.traced(lambda: getattr(self.ledger, method)(*arguments), writes=0)
                totals.assert_called_once()
                violations.assert_called_once()
                self.assertEqual(result["totals"]["cache_bytes"], 50)
                self.assertTrue(result["violations"])

    def test_noop_transaction_retains_recovery_failure_and_original_charges(self):
        self.ledger.reconcile_metadata("fixture", 10, 1)
        marker = self.ledger.recovery_dir / "marker.json"
        value = json.loads(marker.read_bytes())
        value["revision"] += 1
        marker.write_text(json.dumps(value), encoding="utf-8")
        self.ledger.reconcile_metadata("fixture", 10, 1)
        with self.assertRaisesRegex(EvidenceError, "recovery required"):
            self.ledger.require_generation_ready()
        self.assertEqual(self.ledger.connection.execute("SELECT state,bytes,files FROM reservations WHERE id=?",
                         (self.reservation,)).fetchone()[:], ("pending", 65536, 20))


if __name__ == "__main__":
    unittest.main()
