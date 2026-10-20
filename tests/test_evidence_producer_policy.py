"""Authorized policy changes preserve settled producer history and its charges."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence.accounting import Accounting
from evidence.io import EvidenceError
from evidence.policy import load_defaults
from evidence.process_identity import identity
from evidence.producer import recover_producers, run_producer
from evidence import producer_runtime as runtime


class ProducerPolicyCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-producer-policy-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.database = self.root / "accounting" / "ledger.sqlite"
        self.policy = load_defaults()
        self.policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider="local")
        self.policy["limits"]["free_space_reserve_bytes"] = 0

    def ledger(self, policy=None):
        selected = policy or self.policy
        return Accounting(self.database, selected["project_id"], selected)

    def changed_policy(self):
        policy = deepcopy(self.policy)
        policy["limits"]["run_stop_bytes"] += 1024
        policy["retention"]["local_days"] += 1
        return policy

    def create_unlaunched(self, ledger, *, status="launching", reservation_state="pending"):
        output = self.root / str(uuid.uuid4())
        output.mkdir()
        attempt = str(uuid.uuid4())
        value = dict(version=1, attempt_id=attempt, run_id="old-run", unit_id="unit-fixture",
                     reservation_id=None, output_id=None, intent_id=None,
                     coordinator=identity(), guardian=None, status="launching", processes={}, resources=[],
                     output_dir=str(output), output_identity=runtime.directory_identity(output), policy=ledger.policy)
        held = ledger.reserve("old-run", "unit-fixture", 0, 0, metadata_bytes=runtime.MAX_RECORD * 3,
                              producer_record=value)
        if reservation_state == "cancelled":
            ledger.cancel(held)
        elif reservation_state == "settled":
            ledger.settle(held, 0, 0)
        if status != "launching":
            runtime.update(ledger, attempt, lambda row: row.update(status=status))
        return attempt

    def test_changed_limits_allow_new_run_without_rewriting_completed_history(self):
        output = self.root / "first"
        output.mkdir()
        command = [sys.executable, "-B", "-c", "from pathlib import Path; Path('observation').write_bytes(b'old')"]
        with self.ledger() as ledger:
            first = run_producer(ledger, "first-run", "unit-fixture", output, command, 1024, 3,
                                 timeout=5, poll_interval=.02)
            self.assertEqual(first["status"], "complete")
            original = ledger.connection.execute("SELECT record FROM producer_sessions WHERE id=?", (first["attempt_id"],)).fetchone()[0]
            before = ledger.snapshot()["totals"]["project_generated_bytes"]
        next_output = self.root / "second"
        next_output.mkdir()
        with self.ledger(self.changed_policy()) as ledger:
            self.assertFalse(recover_producers(ledger, dry_run=True)["incomplete"])
            second = run_producer(ledger, "second-run", "unit-fixture", next_output, command, 1024, 3,
                                  timeout=5, poll_interval=.02)
            self.assertEqual(second["status"], "complete")
            self.assertEqual(ledger.snapshot()["totals"]["project_generated_bytes"], before + 3)
            after = ledger.connection.execute("SELECT record FROM producer_sessions WHERE id=?", (first["attempt_id"],)).fetchone()[0]
            self.assertEqual(after, original)
            self.assertEqual(json.loads(after)["policy"], self.policy)

    def test_changed_limits_keep_cancelled_terminal_history_readable(self):
        with self.ledger() as ledger:
            attempt = self.create_unlaunched(ledger, status="terminal", reservation_state="cancelled")
            original = runtime.read(ledger, attempt)
        with self.ledger(self.changed_policy()) as ledger:
            self.assertEqual(runtime.read(ledger, attempt), original)
            self.assertFalse(recover_producers(ledger, dry_run=True)["incomplete"])

    def test_changed_policy_does_not_release_active_or_unresolved_attempts(self):
        with self.ledger() as ledger:
            attempt = self.create_unlaunched(ledger)
        with self.ledger(self.changed_policy()) as ledger:
            with self.assertRaisesRegex(EvidenceError, "unresolved producer policy changed"):
                runtime.read(ledger, attempt)
            self.assertTrue(recover_producers(ledger, dry_run=False)["incomplete"])
            self.assertEqual(len(ledger.snapshot()["reservations"]), 1)
        with self.ledger() as ledger:
            runtime.update(ledger, attempt, lambda value: value.update(status="terminal"))
        with self.ledger(self.changed_policy()) as ledger:
            with self.assertRaisesRegex(EvidenceError, "unresolved producer policy changed"):
                runtime.read(ledger, attempt)
            self.assertEqual(len(ledger.snapshot()["reservations"]), 1)

    def test_other_store_and_malformed_original_policy_remain_invalid(self):
        with self.ledger() as ledger:
            attempt = self.create_unlaunched(ledger, status="terminal", reservation_state="settled")
            original = runtime.read(ledger, attempt)
            for changed in ({**original["policy"], "store_id": str(uuid.uuid4())},
                            {**original["policy"], "limits": []}):
                value = {**original, "policy": changed}
                ledger.connection.execute("UPDATE producer_sessions SET record=? WHERE id=?", (json.dumps(value), attempt))
                with self.assertRaises(EvidenceError):
                    runtime.read(ledger, attempt)
                self.assertTrue(recover_producers(ledger, dry_run=True)["incomplete"])


if __name__ == "__main__":
    unittest.main()
