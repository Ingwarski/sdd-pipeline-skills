"""Injected journal/accounting faults retain conservative recovery boundaries."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence.accounting import Accounting
from evidence.io import EvidenceError
from evidence.policy import load_defaults
from evidence import process_identity, producer, producer_runtime as runtime


class ProducerFaultTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-producer-fault-")
        self.root = Path(self.temporary.name).resolve()
        self.output = self.root / "output"
        self.output.mkdir()
        self.policy = load_defaults()
        self.policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider="local")
        self.ledger = Accounting(self.root / "machine/ledger.sqlite", self.policy["project_id"], self.policy)
        self.children = []

    def _process(self):
        process = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(60)"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=os.name == "posix")
        self.children.append(process)
        return process, process_identity.identity(process.pid)

    def _journal(self, *, status="running", guardian=None, processes=None):
        attempt = str(uuid.uuid4())
        reservation = self.ledger.reserve("fault-attempt", "unit-fixture", 65536, 20,
                                          local_bytes=65536, metadata_bytes=runtime.MAX_RECORD,
                                          capacity_path=self.output)
        output_id = self.ledger.register_output("fault-attempt", "unit-fixture", self.output)
        value = {"version": 1, "attempt_id": attempt, "run_id": "fault-attempt",
                 "unit_id": "unit-fixture", "reservation_id": reservation,
                 "output_id": output_id, "intent_id": None,
                 "coordinator": process_identity.identity(), "guardian": guardian,
                 "status": status, "processes": processes or {}, "resources": [],
                 "output_dir": str(self.output), "output_identity": runtime.directory_identity(self.output),
                 "policy": self.policy}
        self.ledger.connection.execute("INSERT INTO producer_sessions VALUES(?,?)", (attempt, json.dumps(value)))
        return attempt

    def _raw_record(self, attempt):
        return json.loads(self.ledger.connection.execute("SELECT record FROM producer_sessions WHERE id=?",
                                                       (attempt,)).fetchone()[0])

    def tearDown(self):
        errors = []
        try:
            for process in self.children:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            for row in self.ledger.connection.execute("SELECT id,record FROM producer_sessions").fetchall():
                value = json.loads(row[1])
                identities = [item["identity"] for item in value.get("processes", {}).values()]
                if any(process_identity.state(item) == "alive" for item in identities):
                    runtime.stop_registered(self.ledger, row[0])
                    errors.extend(runtime.verify_stopped(self.ledger, row[0]))
            marker = self.output / "payload.json"
            if marker.exists():
                owned = json.loads(marker.read_text())
                if process_identity.state(owned) == "alive":
                    process_identity.terminate(owned, force=True)
                deadline = time.monotonic() + 5
                while process_identity.state(owned) != "gone" and time.monotonic() < deadline:
                    time.sleep(.02)
                if process_identity.state(owned) != "gone":
                    errors.append("payload exit could not be verified")
        except BaseException as error:
            errors.append(str(error))
        finally:
            self.ledger.close()
        if errors:
            self.temporary._finalizer.detach()
            self.fail("; ".join(errors) + "; fixture retained at " + str(self.root))
        self.temporary.cleanup()

    def test_unknown_owner_identity_preserves_real_unrelated_process_and_reservation(self):
        sentinel, identity = self._process()
        foreign = deepcopy(identity)
        foreign["host"] += "-different-host"
        malformed = deepcopy(identity)
        malformed["created"] = ["invalid process birth token"]
        attempt = self._journal(guardian=foreign,
                                processes={str(uuid.uuid4()): {"identity": identity, "group": sentinel.pid,
                                                             "status": "gated"}})
        for owner in (foreign, malformed):
            with self.subTest(owner=owner):
                value = self._raw_record(attempt)
                value["guardian"] = owner
                self.ledger.connection.execute("UPDATE producer_sessions SET record=? WHERE id=?",
                                               (json.dumps(value), attempt))
                before = self._raw_record(attempt)
                recovery = producer.recover_producers(self.ledger, dry_run=False)
                self.assertTrue(recovery["incomplete"])
                self.assertIsNone(sentinel.poll(), "unknown ownership authorized termination")
                self.assertEqual(self._raw_record(attempt), before)
                self.assertEqual(len(self.ledger.snapshot()["reservations"]), 1)

    def test_cleanup_exception_releases_claim_and_same_caller_can_retry_recovery(self):
        departed, owner = self._process()
        departed.kill()
        departed.wait(timeout=5)
        attempt = self._journal(guardian=owner)
        with patch.object(runtime, "stop_registered", side_effect=OSError("injected cleanup failure")) as cleanup:
            try:
                producer.recover_producers(self.ledger, dry_run=False)
            except EvidenceError:
                pass  # Structured refusal and a raised domain error are both safe.
            cleanup.assert_called_once()
        self.assertIsNone(self._raw_record(attempt).get("recovery_owner"))
        self.assertEqual(len(self.ledger.snapshot()["reservations"]), 1)
        recovery = producer.recover_producers(self.ledger, dry_run=False)
        self.assertTrue(recovery["incomplete"], "missing monitor history cannot be certified by retry")
        self.assertEqual(self._raw_record(attempt)["status"], "terminal")
        self.assertIsNone(self._raw_record(attempt).get("recovery_owner"))
        self.assertFalse(self.ledger.snapshot()["accounting_complete"])
        self.assertEqual(self.ledger.snapshot()["runs"][0]["status"], "incomplete")

    def test_late_guardian_cannot_reactivate_terminal_attempt(self):
        attempt = self._journal(status="terminal")
        before = self._raw_record(attempt)
        with self.assertRaises(EvidenceError):
            runtime.claim_guardian(self.ledger, attempt)
        self.assertEqual(self._raw_record(attempt), before)
        self.assertEqual(len(self.ledger.snapshot()["reservations"]), 1)

    def test_metadata_capacity_lost_after_launch_stops_real_payload_and_keeps_failure(self):
        attempt = self._journal(guardian=process_identity.identity())
        source = ("import json, time\nfrom pathlib import Path\n"
                  "from evidence.process_identity import identity\n"
                  "Path('diagnostic.txt').write_text('preserved after capacity failure')\n"
                  "Path('payload.json').write_text(json.dumps(identity()))\n"
                  "time.sleep(60)\n")
        original = producer._inventory
        exhausted = False

        def observe(root):
            nonlocal exhausted
            current = original(root)
            if "payload.json" in current and not exhausted:
                # Another writer consumes shared metadata capacity while the
                # producer is active; its immutable policy remains unchanged.
                self.ledger.reconcile_metadata("other-client",
                    self.ledger.policy["limits"]["metadata_stop_bytes"])
                exhausted = True
            return current

        with patch.object(producer, "_inventory", side_effect=observe):
            result = producer._run_monitored(self.ledger, "fault-attempt", "unit-fixture", self.output,
                [sys.executable, "-B", "-c", source], 65536, 20,
                timeout=5, poll_interval=.02, attempt=attempt)
        self.assertTrue(exhausted, "fixture did not consume capacity while a payload was active")
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("metadata", str(result["problem"]) + str(result["accounting"]))
        self.assertNotIn("timeout", str(result["problem"]), "capacity exhaustion was only noticed after timeout")
        owned = json.loads((self.output / "payload.json").read_text())
        self.assertEqual(process_identity.state(owned), "gone")
        self.assertEqual((self.output / "diagnostic.txt").read_text(), "preserved after capacity failure")
        self.assertEqual(self.ledger.snapshot()["runs"][0]["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
