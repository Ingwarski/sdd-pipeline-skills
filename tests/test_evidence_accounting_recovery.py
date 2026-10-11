"""Charge floors survive loss/rollback without inventing accounting completeness."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence.accounting import Accounting, BudgetExceeded
from evidence.io import EvidenceError
from evidence.manager import Manager
from evidence.policy import load_defaults
from evidence.producer import run_producer
from evidence.transports import LocalTransport


class AccountingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "accounting.sqlite"
        self.policy = load_defaults()
        self.policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider="local")

    def ledger(self):
        return Accounting(self.path, self.policy["project_id"], self.policy)

    def lose_database(self):
        for path in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")):
            path.unlink(missing_ok=True)

    def test_failed_generation_survives_database_loss_as_explicit_lower_bound(self):
        with self.ledger() as ledger:
            reservation = ledger.reserve("failed-run", "unit-01", 10, 1)
            ledger.settle(reservation, 6, 1)
            ledger.mark_incomplete("failed-run")
        self.lose_database()
        with self.ledger() as recovered:
            snapshot = recovered.snapshot()
            self.assertEqual(snapshot["totals"]["project_generated_bytes"], 6)
            self.assertEqual(snapshot["runs"][0]["status"], "incomplete")
            self.assertFalse(snapshot["accounting_complete"])
            self.assertTrue(snapshot["totals_are_lower_bounds"])
            with self.assertRaisesRegex(EvidenceError, "recovery required"):
                recovered.reserve("new-chat", "unit-01", 1, 1)
            with self.assertRaisesRegex(EvidenceError, "recovery required"):
                recovered.complete_run("failed-run")
            # Bounded payload restoration remains available during recovery.
            recovery = recovered.reserve_working(1)
            recovered.finish_working(recovery)
        with self.ledger() as reopened:
            self.assertFalse(reopened.snapshot()["accounting_complete"])
            self.assertEqual(reopened.snapshot()["totals"]["project_generated_bytes"], 6)

    def test_unknown_inventory_keeps_hold_and_charges_idempotent_observed_floor(self):
        with self.ledger() as ledger:
            reservation = ledger.reserve("run", "unit-01", 10, 2, local_bytes=10)
            ledger.record_uncertain(reservation, 3, 1)
            ledger.record_uncertain(reservation, 3, 1)
            ledger.record_uncertain(reservation, 4, 1)
            snapshot = ledger.snapshot()
            self.assertEqual(snapshot["totals"]["project_generated_bytes"], 4)
            self.assertEqual(snapshot["totals"]["pending_generated_bytes"], 10)
            self.assertEqual(snapshot["totals"]["pending_local_bytes"], 10)
            with self.assertRaises(EvidenceError):
                ledger.cancel(reservation)
            with self.assertRaises(EvidenceError):
                ledger.settle(reservation, 4, 1)
        self.lose_database()
        with self.ledger() as recovered:
            self.assertEqual(recovered.snapshot()["totals"]["project_generated_bytes"], 4)
            self.assertEqual(recovered.snapshot()["totals"]["pending_generated_bytes"], 10)
            self.assertFalse(recovered.snapshot()["accounting_complete"])

    def test_checkpoint_before_failed_sql_commit_stays_conservative(self):
        with self.ledger() as ledger:
            original = ledger._checkpoint_runs
            def interrupted_checkpoint():
                original()
                raise OSError("synthetic interruption after durable journal write")
            with patch.object(ledger, "_checkpoint_runs", side_effect=interrupted_checkpoint):
                with self.assertRaises(OSError):
                    ledger.reserve("interrupted", "unit-01", 10, 1)
            self.assertFalse(ledger.snapshot()["accounting_complete"])
            with self.assertRaises(EvidenceError):
                ledger.reserve("same-process-retry", "unit-01", 1, 1)
        with self.ledger() as recovered:
            self.assertFalse(recovered.snapshot()["accounting_complete"])
            self.assertEqual(recovered.snapshot()["totals"]["pending_generated_bytes"], 10)
            with self.assertRaises(EvidenceError):
                recovered.reserve("retry", "unit-01", 1, 1)

    def test_interruption_before_run_checkpoint_cannot_reopen_as_complete(self):
        from evidence import accounting
        original = accounting.atomic_json
        with self.ledger() as ledger:
            reservation = ledger.reserve("run", "unit-01", 10, 1)
            def fail_run_write(path, value):
                if Path(path).name.startswith("run-"):
                    raise OSError("synthetic failure before run charge checkpoint")
                return original(path, value)
            with patch("evidence.accounting.atomic_json", side_effect=fail_run_write):
                with self.assertRaises(OSError):
                    ledger.settle(reservation, 6, 1)
        with self.ledger() as recovered:
            self.assertFalse(recovered.snapshot()["accounting_complete"])
            self.assertEqual(recovered.snapshot()["totals"]["pending_generated_bytes"], 10)
            with self.assertRaises(EvidenceError):
                recovered.reserve("new", "unit-01", 1, 1)

    def test_already_open_worker_detects_another_clients_interrupted_checkpoint(self):
        from evidence import accounting
        original = accounting.atomic_json
        with self.ledger() as first, self.ledger() as second:
            reservation = first.reserve("run", "unit-01", 10, 1)
            def fail_run_write(path, value):
                if Path(path).name.startswith("run-"):
                    raise OSError("synthetic interrupted charge")
                return original(path, value)
            with patch("evidence.accounting.atomic_json", side_effect=fail_run_write):
                with self.assertRaises(OSError):
                    first.settle(reservation, 6, 1)
            with self.assertRaisesRegex(EvidenceError, "recovery required"):
                second.reserve("other-client", "unit-02", 1, 1)
            self.assertFalse(second.snapshot()["accounting_complete"])

    def test_missing_recovery_journal_does_not_erase_live_database_charges(self):
        with self.ledger() as ledger:
            reservation = ledger.reserve("run", "unit-01", 6, 1)
            ledger.settle(reservation, 6, 1)
            recovery_dir = ledger.recovery_dir
        for path in recovery_dir.iterdir():
            path.unlink()
        with self.ledger() as recovered:
            self.assertEqual(recovered.snapshot()["totals"]["project_generated_bytes"], 6)
            self.assertFalse(recovered.snapshot()["accounting_complete"])

    def test_managed_run_snapshots_are_maxima_not_independent_output_charges(self):
        record = {"run_id": "shared-run", "unit_id": "unit-01", "gross_bytes": 12,
                  "logical_files": 2, "mode": "managed-run-total"}
        catalog = {"output-one": record, "output-two": deepcopy(record)}
        with self.ledger() as ledger:
            ledger.reconcile_generation(catalog)
            self.assertEqual(ledger.snapshot()["totals"]["project_generated_bytes"], 12)
            self.assertEqual(ledger.snapshot()["totals"]["project_generated_files"], 2)
            catalog["later-snapshot"] = {**record, "gross_bytes": 18, "logical_files": 3}
            ledger.reconcile_generation(catalog)
            ledger.reconcile_generation(catalog)
            self.assertEqual(ledger.snapshot()["totals"]["project_generated_bytes"], 18)
            self.assertEqual(ledger.snapshot()["totals"]["project_generated_files"], 3)

    def test_recovery_journal_shares_metadata_count_limit(self):
        self.policy["limits"]["metadata_stop_files"] = 2
        with self.ledger() as ledger:
            reservation = ledger.reserve("one", "unit-01", 0, 0)
            ledger.cancel(reservation)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("second", "unit-02", 0, 0)
            self.assertEqual(ledger.snapshot()["totals"]["metadata_files"], 2)

    def test_combined_database_and_journal_loss_never_promotes_durable_charges_to_completion(self):
        for exit_code in (0, 3):
            with self.subTest(exit_code=exit_code):
                base = self.root / str(exit_code)
                manager = Manager(LocalTransport(base / "store"), base / "home", self.policy)
                self.path = manager.state / "accounting.sqlite"
                manager.initialize_generation_authority()
                intent = manager.begin_generation("run", "unit-01", 20, 2)
                output = base / "output"
                output.mkdir()
                with self.ledger() as ledger:
                    result = run_producer(ledger, "run", "unit-01", output,
                        [sys.executable, "-c", "from pathlib import Path; Path('data').write_bytes(b'123456'); raise SystemExit(" + str(exit_code) + ")"],
                        20, 2, poll_interval=0.01)
                self.assertTrue(manager.finish_generation(intent, result["reservation_id"])["settled"])
                self.assertTrue(manager._catalog()["generation_intents"][intent]["settled"])
                refs = []
                if exit_code == 0:
                    refs = manager.archive({"version": 1, "managed_output_id": result["output_id"], "files": [{
                        "path": str(output / "data"), "sealed_at": "2099-01-01T00:00:00Z",
                        "kind": "diagnostic", "schema": "evidence-bytes-v1",
                        "provenance": {"run_id": "run", "unit_id": "unit-01"}}]})
                self.lose_database()
                recovery = Path(str(self.path) + ".recovery")
                for path in recovery.iterdir():
                    path.unlink()
                recovery.rmdir()
                # Coordinator identity and settled remote intents are retained;
                # neither substitutes for the lost original output accounting.
                with self.assertRaisesRegex(EvidenceError, "accounting recovery required"):
                    manager.assert_generation_authority()
                status = manager.status()
                self.assertFalse(status["accounting_complete"])
                self.assertIsNone(status["gross_generated_bytes"])
                self.assertEqual(status["known_gross_generated_bytes"], 6)
                with self.ledger() as recovered:
                    self.assertEqual(recovered.snapshot()["runs"][0]["status"], "incomplete")
                    with self.assertRaisesRegex(EvidenceError, "accounting recovery required"):
                        recovered.complete_run("run")
                    with self.assertRaisesRegex(EvidenceError, "accounting recovery required"):
                        recovered.reserve("retry", "unit-01", 1, 1)
                if refs:
                    restored = manager.restore(refs, base / "restore")
                    self.assertEqual(Path(restored[0]).read_bytes(), b"123456")


if __name__ == "__main__":
    unittest.main()
