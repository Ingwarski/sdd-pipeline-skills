"""Cold producer accounting and concurrent transient reservations use only fixtures."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/to-sdd-pipeline/scripts"))
from evidence.accounting import Accounting, BudgetExceeded
from evidence.io import atomic_json
from evidence.manager import Manager
from evidence.policy import load_defaults
from evidence.transports import LocalTransport


class WorkingReservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-working-reservation-")
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.policy = {**load_defaults(), "project_id": str(uuid.uuid4()), "store_id": str(uuid.uuid4()), "provider": "local"}
        self.policy["limits"].update(local_stop_bytes=1024**2, cache_stop_bytes=150000, free_space_reserve_bytes=0)
        self.db = self.root / "ledger.sqlite"

    def ledger(self):
        return Accounting(self.db, self.policy["project_id"], self.policy)

    def test_parallel_working_holds_are_atomic_and_never_charge_generation(self):
        with self.ledger():
            pass
        def reserve(_):
            with self.ledger() as ledger:
                try:
                    return ledger.reserve_working(500000)
                except BudgetExceeded:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            held = list(pool.map(reserve, range(2)))
        self.assertEqual(sum(item is not None for item in held), 1)
        with self.ledger() as ledger:
            snapshot = ledger.snapshot()
            self.assertEqual(snapshot["totals"]["pending_local_bytes"], 500000)
            self.assertEqual(snapshot["totals"]["project_generated_bytes"], 0)
            self.assertEqual(snapshot["runs"], [])
            ledger.finish_working(next(item for item in held if item))
            self.assertEqual(ledger.snapshot()["working_reservations"], [])

    def test_atomic_finish_reconciles_usage_and_charges_actual_overrun(self):
        with self.ledger() as ledger:
            held = ledger.reserve_working(10000)
            result = ledger.finish_working(held, local_key="restore:synthetic", actual_bytes=12000)
            self.assertTrue(result["incomplete"])
            self.assertEqual(result["totals"]["pending_working_bytes"], 0)
            actual = ledger.connection.execute("SELECT bytes FROM local_usage WHERE key='restore:synthetic'").fetchone()[0]
            self.assertEqual(actual, 12000)
            # A full current allocation is compared with its previous occupancy,
            # so extending an existing allocation charges the measured delta.
            held = ledger.reserve_working(1000)
            self.assertFalse(ledger.finish_working(held, local_key="restore:synthetic", actual_bytes=13000)["incomplete"])

    def test_combined_metadata_and_cache_holds_cannot_be_split(self):
        self.policy["limits"].update(metadata_stop_bytes=1024**2, metadata_stop_files=2)
        with self.ledger() as ledger:
            ledger.reconcile_metadata("existing", 100000, 1)
            held = ledger.reserve_working(300000, metadata_bytes=200000, metadata_files=1, cache_bytes=100000)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve_working(100, metadata_bytes=100, metadata_files=1)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve_working(100000, cache_bytes=60000)
            result = ledger.finish_working(held, local_key="manager-working", actual_bytes=1000, kind="staging",
                metadata_key="new-receipt", actual_metadata_bytes=200000, actual_metadata_files=1,
                cache_key="cache", actual_cache_bytes=100000)
            self.assertFalse(result["incomplete"])
            self.assertEqual(result["totals"]["cache_bytes"], 100000)
            self.assertEqual(result["totals"]["metadata_files"], 2)

    def test_recovery_ignores_generation_retained_overage_but_preserves_floor(self):
        self.policy["limits"].update(project_generation_stop_bytes=10, project_generation_warning_bytes=5,
                                      retained_stop_bytes=10, retained_warning_bytes=5)
        with self.ledger() as ledger:
            ledger.record_object("legacy", 1000)
            ledger.reconcile_generation({"old": {"run_id": "old-run", "unit_id": "U-1", "gross_bytes": 20, "logical_files": 1}})
            held = ledger.reserve_working(1000, migration=True)
            ledger.finish_working(held)
            self.assertEqual(ledger.snapshot()["totals"]["project_generated_bytes"], 20)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("new-run", "U-1", 1, 1)

    def test_working_hold_can_replace_its_own_archive_peak(self):
        with self.ledger() as ledger:
            archive = ledger.reserve("archive", "U-1", 0, 0, local_bytes=500000)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve_working(500000)
            working = ledger.reserve_working(500000, exclude_reservation=archive)
            ledger.finish_working(working)
            ledger.cancel(archive)

    def test_owner_identity_survives_reopen_without_automatic_release(self):
        with self.ledger() as ledger:
            held = ledger.reserve_working(1000)
            record = ledger.snapshot()["working_reservations"][0]
            self.assertEqual(record["owner_pid"], os.getpid())
            self.assertEqual(record["owner_host"], socket.gethostname())
            # A fixture representing an exited local owner remains charged.
            # Only explicit recovery can verify its process/helper state and
            # reconcile remaining physical writes before releasing the hold.
            ledger.connection.execute("UPDATE working_reservations SET owner_pid=? WHERE id=?", (2**30, held))
        with self.ledger() as ledger:
            record = ledger.snapshot()["working_reservations"][0]
            self.assertEqual(record["owner_pid"], 2**30)
            self.assertEqual(ledger.snapshot()["totals"]["pending_working_bytes"], 1000)
            ledger.finish_working(held)

    def test_bounded_reads_report_existing_metadata_cache_overage_without_new_writes(self):
        self.policy["limits"].update(metadata_stop_bytes=1000, metadata_stop_files=1, cache_stop_bytes=500)
        with self.ledger() as ledger:
            ledger.reconcile_metadata("existing", 2000, 2)
            ledger.reconcile_local("cache", 600, "cache")
            held = ledger.reserve_working(100)
            result = ledger.finish_working(held)
            self.assertTrue(result["incomplete"])
            self.assertIn("combined metadata usage exceeds allowance", result["violations"])
            self.assertIn("combined cache bytes exceed allowance", result["violations"])
            with self.assertRaises(BudgetExceeded):
                ledger.reserve_working(100, metadata_bytes=1)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve_working(100, cache_bytes=1)


class ColdProducerCliTests(unittest.TestCase):
    def test_deleted_local_database_restores_unit_charges_before_launch(self):
        with tempfile.TemporaryDirectory(prefix="sdd-cold-run-") as temporary:
            base = Path(temporary).resolve()
            project, home, store = base / "project", base / "home", base / "store"
            (project / "forge").mkdir(parents=True)
            policy = {**load_defaults(), "project_id": str(uuid.uuid4()), "store_id": str(uuid.uuid4()), "provider": "local"}
            policy["limits"].update(unit_warning_bytes=5, unit_stop_bytes=10, free_space_reserve_bytes=0)
            atomic_json(project / "forge/evidence-policy.json", policy)
            source = base / "existing-source"
            source.write_bytes(b"123456")
            manager = Manager(LocalTransport(store), home, policy)
            manager.archive({"version": 1, "files": [{"path": str(source), "sealed_at": "2099-01-01T00:00:00Z",
                "kind": "diagnostic", "schema": "evidence-bytes-v1", "provenance": {"run_id": "old-run", "unit_id": "U-1"}}]})
            # Model a missing local database, preserving the selected durable
            # store and original coordinator. The remote catalog is authoritative.
            for item in manager.state.glob("accounting.sqlite*"):
                item.unlink()
            config = base / "machine-config.json"
            atomic_json(config, {"version": 1, "provider": "local", "store_id": policy["store_id"], "destination": str(store), "evidence_home": str(home)})
            output = base / "producer-output"
            result = subprocess.run([sys.executable, str(ROOT / "skills/to-sdd-pipeline/scripts/evidence_store.py"),
                "run", "--project", str(project), "--config", str(config), "--run-id", "new-run", "--unit-id", "U-1",
                "--output-dir", str(output), "--reserve-bytes", "5", "--reserve-files", "2", "--",
                sys.executable, "-c", "from pathlib import Path; Path('must-not-run').write_text('x')"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            response = json.loads(result.stdout)
            self.assertTrue(response["incomplete"])
            self.assertIn("unit cumulative", response["error"])
            self.assertFalse((output / "producer.log").exists())
            self.assertFalse((output / "must-not-run").exists())
            with Accounting(manager.state / "accounting.sqlite", policy["project_id"], policy) as ledger:
                self.assertEqual(ledger.snapshot()["totals"]["project_generated_bytes"], 6)


if __name__ == "__main__":
    unittest.main()
