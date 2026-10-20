"""Generic producer recovery at durable catalog and command boundaries."""
from contextlib import redirect_stdout
from io import StringIO
import json
import socket
import sqlite3
import sys
import unittest
import uuid
from unittest.mock import patch

import test_evidence_manager as fixtures
from evidence.accounting import Accounting
from evidence.io import EvidenceError
from evidence import process_identity
import evidence_store


class ProducerManagerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EvidenceManagerTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manager = self.fixture.manager
        self.manager.initialize_generation_authority()
        self.recover_patch = patch("evidence.producer.recover_producers", create=True,
                                   return_value={"actions": [], "incomplete": False})
        self.recover = self.recover_patch.start()
        self.addCleanup(self.recover_patch.stop)

    def ledger(self):
        return Accounting(self.manager.state / "accounting.sqlite",
                          self.manager.policy["project_id"], self.manager.policy)

    def publish_intent(self, *, legacy=False, run="run", owner=None):
        ident = str(uuid.uuid4())
        record = {"run_id": run, "unit_id": "unit", "reserve_bytes": 20,
                  "reserve_files": 2, "owner_pid": 2**30, "owner_host": socket.gethostname()}
        if not legacy:
            owner = owner or process_identity.identity()
            record.update(owner_pid=owner["pid"], owner_host=owner["host"], owner_identity=owner)
        with self.manager.locked():
            self.manager._publish(self.manager._catalog(mutation=True),
                                  {"version": 1, "generation_intents": {ident: record}})
        return ident

    def action(self, intent, reservation, *, state="terminal", incomplete=False):
        return {"attempt_id": str(uuid.uuid4()), "intent_id": intent,
                "reservation_id": reservation, "run_id": "run",
                "action": state, "incomplete": incomplete}

    def test_new_intent_records_exact_portable_process_identity(self):
        intent = self.manager.begin_generation("run", "unit", 20, 2)
        record = self.manager._catalog()["generation_intents"][intent]
        self.assertEqual(process_identity.identity(), record["owner_identity"])
        self.assertTrue(process_identity.valid_identity(record["owner_identity"]))
        self.assertTrue(self.manager.finish_generation(intent)["settled"])

    def test_catalog_rejects_malformed_exact_identity(self):
        owner = process_identity.identity()
        owner["created"] = []
        self.publish_intent(owner=owner)
        with self.assertRaisesRegex(EvidenceError, "process identity"):
            self.manager._catalog()

    def test_foreign_exact_identity_is_readable_but_cannot_be_settled(self):
        owner = process_identity.identity()
        owner["host"] += "-another-host"
        intent = self.publish_intent(owner=owner)
        self.assertIn(intent, self.manager._catalog()["generation_intents"])
        with self.assertRaisesRegex(EvidenceError, "exit cannot be verified"):
            self.manager.finish_generation(intent)
        self.assertFalse(self.manager._catalog()["generation_intents"][intent].get("settled"))

    def test_legacy_prelaunch_intent_remains_readable_and_reconcilable(self):
        intent = self.publish_intent(legacy=True)
        dry = self.manager.reconcile()
        self.assertTrue(any(item.get("intent_id") == intent and item.get("dry_run") for item in dry))
        self.assertFalse(self.manager._catalog()["generation_intents"][intent].get("settled"))
        self.manager.reconcile(dry_run=False)
        self.assertTrue(self.manager._catalog()["generation_intents"][intent]["settled"])

    def test_generation_checks_orphan_recovery_before_new_capacity(self):
        self.recover.return_value = {"actions": [{"action": "retained", "incomplete": True}], "incomplete": True}
        with self.assertRaisesRegex(EvidenceError, "producer recovery remains incomplete"):
            self.manager.begin_generation("must-not-start", "unit", 20, 2)
        self.assertEqual(False, self.recover.call_args.kwargs["dry_run"])
        with self.ledger() as ledger:
            self.assertEqual([], ledger.snapshot()["runs"])
        self.assertEqual({}, self.manager._catalog()["generation_intents"])

    def test_healthy_parallel_attempt_does_not_block_generation(self):
        intent = self.manager.begin_generation("run", "unit", 20, 2)
        with self.ledger() as ledger:
            reservation = ledger.reserve("run", "unit", 20, 2)
        action = self.action(intent, reservation, state="active")
        self.recover.return_value = {"actions": [action], "incomplete": False}
        self.assertTrue(self.manager.assert_generation_authority()["coordinator_authorized"])
        reconciled = self.manager.reconcile()
        self.assertTrue(any(item.get("action") == "generation-intent-active" for item in reconciled))
        with self.ledger() as ledger:
            self.assertEqual(reservation, ledger.snapshot()["reservations"][0]["id"])

    def test_exact_attempt_cannot_settle_another_parallel_reservation(self):
        first = self.manager.begin_generation("run", "unit", 20, 2)
        second = self.manager.begin_generation("run", "unit", 21, 2)
        with self.ledger() as ledger:
            first_hold = ledger.reserve("run", "unit", 20, 2)
            second_hold = ledger.reserve("run", "unit", 20, 2)
            ledger.settle(first_hold, 5, 1)
            ledger.settle(second_hold, 7, 1)
        self.recover.return_value = {"actions": [self.action(first, first_hold), self.action(second, second_hold)],
                                    "incomplete": False}
        with self.assertRaisesRegex(EvidenceError, "another producer intent"):
            self.manager.finish_generation(first, second_hold)
        self.assertFalse(self.manager._catalog()["generation_intents"][first].get("settled"))
        self.assertTrue(self.manager.finish_generation(first, first_hold)["settled"])
        self.assertFalse(self.manager._catalog()["generation_intents"][second].get("settled"))
        with self.ledger() as ledger:
            self.assertEqual(12, ledger.snapshot()["totals"]["project_generated_bytes"])

    def test_exited_exact_attempt_settles_while_parallel_worker_remains_pending(self):
        first = self.manager.begin_generation("run", "unit", 20, 2)
        second = self.manager.begin_generation("run", "unit", 21, 2)
        with self.ledger() as ledger:
            first_hold = ledger.reserve("run", "unit", 20, 2)
            second_hold = ledger.reserve("run", "unit", 20, 2)
            ledger.settle(first_hold, 5, 1)
        self.recover.return_value = {"actions": [self.action(first, first_hold), self.action(second, second_hold, state="active")],
                                    "incomplete": False}
        original_state = self.manager._generation_owner_state
        first_record = self.manager._catalog()["generation_intents"][first]
        # Distinct declared bounds identify these synthetic workers even though
        # both intents were created by this test coordinator.
        with patch.object(self.manager, "_generation_owner_state", side_effect=lambda record: "gone" if record == first_record else original_state(record)):
            actions = self.manager.reconcile(dry_run=False)
        self.assertTrue(any(item.get("intent_id") == first and item.get("verified") for item in actions))
        self.assertTrue(self.manager._catalog()["generation_intents"][first]["settled"])
        with self.ledger() as ledger:
            self.assertEqual([second_hold], [item["id"] for item in ledger.snapshot()["reservations"]])

    def test_unknown_attempt_preserves_intent_and_hold(self):
        intent = self.manager.begin_generation("run", "unit", 20, 2)
        with self.ledger() as ledger:
            hold = ledger.reserve("run", "unit", 20, 2)
        self.recover.return_value = {"actions": [self.action(intent, hold, state="retained", incomplete=True)], "incomplete": True}
        with self.assertRaisesRegex(EvidenceError, "active or unresolved producer"):
            self.manager.finish_generation(intent, hold)
        actions = self.manager.reconcile(dry_run=False)
        self.assertTrue(any(item.get("incomplete") for item in actions))
        with self.ledger() as ledger:
            self.assertEqual([hold], [item["id"] for item in ledger.snapshot()["reservations"]])

    def test_reconciliation_forwards_dry_run_and_preserves_generic_incomplete(self):
        self.recover.return_value = {"actions": [], "incomplete": True}
        actions = self.manager.reconcile(dry_run=True)
        self.assertTrue(self.recover.call_args.kwargs["dry_run"])
        self.assertTrue(any(item.get("incomplete") for item in actions))
        self.manager.reconcile(dry_run=False)
        self.assertFalse(self.recover.call_args.kwargs["dry_run"])

    def test_cli_retained_recovery_is_nonzero_and_healthy_active_is_zero(self):
        for incomplete, expected in ((True, 1), (False, 0)):
            with self.subTest(incomplete=incomplete), patch.object(evidence_store, "project_setup", return_value=None), \
                    patch.object(evidence_store, "load_manager", return_value=self.manager), \
                    patch.object(self.manager, "reconcile", return_value=[{"action": "retained" if incomplete else "active", "incomplete": incomplete}]), \
                    patch.object(sys, "argv", ["evidence_store.py", "reconcile"]), redirect_stdout(StringIO()) as output:
                code = evidence_store.main()
            self.assertEqual(expected, code)
            self.assertEqual(incomplete, json.loads(output.getvalue())["actions"][0]["incomplete"])

    def test_producer_registration_and_capacity_commit_together(self):
        record = {"attempt_id": str(uuid.uuid4()), "run_id": "atomic-run", "unit_id": "unit",
                  "reservation_id": None, "output_id": None, "status": "launching"}
        with self.ledger() as ledger:
            hold = ledger.reserve("atomic-run", "unit", 20, 2, metadata_bytes=2048,
                                  producer_record=record)
        with self.ledger() as reopened:
            stored = json.loads(reopened.connection.execute("SELECT record FROM producer_sessions WHERE id=?", (record["attempt_id"],)).fetchone()[0])
            self.assertEqual(hold, stored["reservation_id"])
            self.assertIsNone(stored["output_id"])
            self.assertEqual("launching", stored["status"])
            self.assertEqual([hold], [row["id"] for row in reopened.snapshot()["reservations"]])
        self.assertIsNone(record["reservation_id"], "the caller's draft must remain unchanged")

    def test_duplicate_producer_attempt_preserves_original_without_new_hold(self):
        record = {"attempt_id": str(uuid.uuid4()), "run_id": "original", "unit_id": "unit",
                  "output_id": None, "status": "launching"}
        with self.ledger() as ledger:
            hold = ledger.reserve("original", "unit", 20, 2, metadata_bytes=2048,
                                  producer_record=record)
            original = ledger.connection.execute("SELECT record FROM producer_sessions WHERE id=?", (record["attempt_id"],)).fetchone()[0]
            with self.assertRaisesRegex(EvidenceError, "already registered"):
                ledger.reserve("replacement", "unit", 90, 9, metadata_bytes=2048,
                               producer_record={**record, "run_id": "replacement"})
            self.assertEqual(original, ledger.connection.execute("SELECT record FROM producer_sessions WHERE id=?", (record["attempt_id"],)).fetchone()[0])
            self.assertEqual([hold], [row["id"] for row in ledger.snapshot()["reservations"]])
            self.assertEqual(["original"], [row["id"] for row in ledger.snapshot()["runs"]])

    def test_failed_producer_registration_rolls_back_new_run_and_hold(self):
        record = {"attempt_id": str(uuid.uuid4()), "run_id": "atomic-run", "unit_id": "unit",
                  "output_id": None, "status": "launching"}
        with self.ledger() as ledger:
            ledger.connection.execute("CREATE TEMP TRIGGER reject_producer BEFORE INSERT ON producer_sessions BEGIN SELECT RAISE(ABORT,'synthetic registration failure'); END")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "registration failure"):
                ledger.reserve("atomic-run", "unit", 20, 2, metadata_bytes=2048,
                               producer_record=record)
            self.assertEqual([], ledger.snapshot()["runs"])
            self.assertEqual([], ledger.snapshot()["reservations"])
            self.assertEqual(0, ledger.connection.execute("SELECT COUNT(*) FROM producer_sessions").fetchone()[0])

    def test_producer_registration_rejects_changed_bindings_and_metadata_overrun(self):
        record = {"attempt_id": str(uuid.uuid4()), "run_id": "run", "unit_id": "unit",
                  "output_id": None, "status": "launching"}
        with self.ledger() as ledger:
            for change in ({"run_id": "other"}, {"unit_id": "other"}, {"reservation_id": "existing"},
                           {"output_id": "existing"}, {"status": "terminal"}, {"attempt_id": ""}):
                with self.subTest(change=change), self.assertRaises(EvidenceError):
                    ledger.reserve("run", "unit", 20, 2, metadata_bytes=2048,
                                   producer_record={**record, **change})
            with self.assertRaisesRegex(EvidenceError, "metadata allowance"):
                ledger.reserve("run", "unit", 20, 2, producer_record=record)
            self.assertEqual([], ledger.snapshot()["runs"])
            self.assertEqual([], ledger.snapshot()["reservations"])

    def test_cli_passes_original_intent_into_managed_producer(self):
        output_path = self.fixture.base / "cli-output"
        arguments = ["evidence_store.py", "run", "--run-id", "run", "--unit-id", "unit",
                     "--output-dir", str(output_path), "--reserve-bytes", "20", "--reserve-files", "2", "--", "synthetic-command"]
        with patch.object(evidence_store, "project_setup", return_value=None), \
                patch.object(evidence_store, "load_manager", return_value=self.manager), \
                patch("evidence.producer.run_producer", return_value={"status": "incomplete", "reservation_id": "hold"}) as run, \
                patch.object(self.manager, "finish_generation") as finish, \
                patch.object(sys, "argv", arguments), redirect_stdout(StringIO()):
            code = evidence_store.main()
        self.assertEqual(1, code)
        intent = run.call_args.kwargs["intent_id"]
        self.assertIn(intent, self.manager._catalog()["generation_intents"])
        finish.assert_called_once_with(intent, reservation_id="hold")


if __name__ == "__main__":
    unittest.main()
