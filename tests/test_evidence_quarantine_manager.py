"""Isolated catalog/CLI quarantine integration; no product or private ledger use."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

import test_evidence_manager as fixtures
from evidence.accounting import Accounting
from evidence.io import EvidenceError, hash_file
from evidence.manager import Manager, canonical
from evidence import process_identity, producer_runtime
from evidence.producer import run_producer
import evidence_store


class QuarantineManagerTests(unittest.TestCase):
    def setUp(self):
        self.prepare_fixture()

    def prepare_fixture(self, before_uncertainty=None):
        """Seed portable preexisting work before the fixture's historical gap."""
        self.fixture = fixtures.EvidenceManagerTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manager = self.fixture.manager
        self.manager.initialize_generation_authority()
        if before_uncertainty is not None:
            before_uncertainty()
        self.intent = self.manager.begin_generation("old-run", "old-unit", 1024, 8)
        self.output = self.fixture.base / "unknown-output"
        self.output.mkdir()
        owner = process_identity.identity()
        owner["pid"] = 2**30
        self.attempt = str(uuid.uuid4())
        record = {"version": 1, "attempt_id": self.attempt, "run_id": "old-run",
            "unit_id": "old-unit", "reservation_id": None, "output_id": None,
            "intent_id": self.intent, "coordinator": owner, "guardian": None,
            "status": "launching", "processes": {}, "resources": [],
            "output_dir": str(self.output), "output_identity": producer_runtime.directory_identity(self.output),
            "policy": self.manager.policy}
        with self.ledger(publication=True) as ledger:
            self.reservation = ledger.reserve("old-run", "old-unit", 1024, 8,
                local_bytes=1024, metadata_bytes=65536, producer_record=record)
            output_id = ledger.register_output("old-run", "old-unit", self.output)
            producer_runtime.update(ledger, self.attempt, lambda item: item.update(
                output_id=output_id, status="stopping"))
            (self.output / "retained.txt").write_text("historical retained bytes")
            ledger.record_uncertain(self.reservation, 24, 1)
            raw_record = ledger.connection.execute(
                "SELECT record FROM producer_sessions WHERE id=?", (self.attempt,)).fetchone()[0]
            original = json.loads(raw_record)
            self.original_record = original
        journal = self.fixture.base / "external-journal.txt"
        journal.write_text("Explicit isolated fixture external disposition journal")
        proof = self.fixture.base / "external-proof.txt"
        proof.write_text("No unregistered processes/resources in this synthetic fixture")
        self.proof = {"version": 1, "kind": "producer-disposition", "attempt_id": self.attempt,
            "original_record_sha256": hashlib.sha256(raw_record.encode()).hexdigest(),
            "verifier": "isolated-test-owner", "observed_at": "2026-10-21T12:00:00Z",
            "external_disposition": {"coverage": "all-unregistered-helpers-and-resources",
                "journal": {"path": str(journal), "sha256": hash_file(journal)[0]},
                "proof": {"path": str(proof), "sha256": hash_file(proof)[0]},
                "limitations": "Historical production totals remain unknown"}}

    def ledger(self, *, publication=False):
        ledger = Accounting(self.manager.state / "accounting.sqlite",
            self.manager.policy["project_id"], self.manager.policy)
        if publication:
            ledger._publication_manager = (self.manager, None, None)
        return ledger

    def apply(self):
        return self.manager.quarantine_producer(self.attempt, self.proof, dry_run=False)

    def receipt(self):
        policy = self.fixture.base / "portable-policy.json"
        policy.write_text(json.dumps(self.manager.policy, indent=4) + "\n")
        arguments = ["evidence_store.py", "accounting-receipt", "--policy", str(policy)]
        with patch.object(evidence_store, "project_setup", return_value=None), \
                patch.object(evidence_store, "load_manager", return_value=self.manager), \
                patch.object(sys, "argv", arguments), redirect_stdout(StringIO()) as output:
            code = evidence_store.main()
        return code, json.loads(output.getvalue()), policy

    def test_dry_run_and_repeated_publication_preserve_all_historical_rows(self):
        with self.ledger(publication=True) as ledger:
            before = {table: [tuple(row) for row in ledger.connection.execute("SELECT * FROM " + table)]
                for table in ("runs", "reservations", "uncertain_generation", "producer_sessions", "outputs")}
        dry = self.manager.quarantine_producer(self.attempt, self.proof)
        self.assertTrue(dry["dry_run"])
        self.assertEqual({}, self.manager._catalog()["generation_quarantines"])
        first = self.apply()
        sequence = self.manager._catalog()["sequence"]
        self.assertEqual(first, self.apply())
        self.assertEqual(sequence, self.manager._catalog()["sequence"])
        with self.ledger(publication=True) as ledger:
            for table, rows in before.items():
                self.assertEqual(rows, [tuple(row) for row in ledger.connection.execute("SELECT * FROM " + table)])
            self.assertFalse(ledger.snapshot()["accounting_complete"])
            readiness = ledger.generation_readiness()
            self.assertEqual(os.name == 'posix', readiness["ready"], readiness)
            if os.name != 'posix':
                self.assertIn('requires POSIX main-thread', readiness['problem'])
        self.assertFalse(self.manager._catalog()["generation_intents"][self.intent].get("settled"))

    def test_fresh_real_producer_finishes_without_completing_old_attempt(self):
        self.apply()
        if os.name != 'posix':
            with self.assertRaisesRegex(EvidenceError, 'POSIX'):
                self.manager.begin_generation('fresh-run', 'fresh-unit', 4096, 8)
            with self.ledger(publication=True) as ledger:
                with self.assertRaisesRegex(EvidenceError, 'POSIX'):
                    ledger.reserve('fresh-run', 'fresh-unit', 4096, 8)
                self.assertIsNone(ledger.connection.execute("SELECT id FROM runs WHERE id='fresh-run'").fetchone())
            self.assertEqual(self.original_record, self._original_record())
            self.assertFalse(self.manager._catalog()['generation_intents'][self.intent].get('settled'))
            return  # precise unsupported quarantined-native assertion
        intent = self.manager.begin_generation("fresh-run", "fresh-unit", 4096, 8)
        output = self.fixture.base / "fresh-output"
        output.mkdir()
        with self.ledger(publication=True) as ledger:
            result = run_producer(ledger, "fresh-run", "fresh-unit", output,
                [sys.executable, "-B", "-c", "from pathlib import Path; Path('fresh.txt').write_text('fresh')"],
                4096, 8, timeout=10, poll_interval=.02, intent_id=intent, manager=self.manager)
        self.assertEqual("complete", result["status"])
        self.assertTrue(self.manager.finish_generation(intent, result["reservation_id"])["settled"])
        with self.assertRaisesRegex(EvidenceError, "quarantined"):
            self.manager.finish_generation(self.intent, self.reservation)
        code, receipt, policy = self.receipt()
        self.assertEqual(0, code, "a valid scoped receipt is issued successfully with honest global flags")
        self.assertEqual(2, receipt["version"])
        self.assertEqual("scoped-known-generation", receipt["kind"])
        self.assertTrue(receipt["generation_ready"])
        self.assertFalse(receipt["accounting_complete"])
        self.assertTrue(receipt["totals_are_lower_bounds"])
        self.assertFalse(receipt["history_complete"])
        self.assertEqual({"run_ids": ["fresh-run"], "complete": True}, receipt["selected_scope"])
        self.assertEqual("incomplete", receipt["runs"]["old-run"]["status"])
        self.assertEqual({self.intent}, set(receipt["pending_generation_intents"]))
        self.assertEqual(hash_file(policy)[0], receipt["policy_sha256"])
        self.assertEqual(self.original_record, self._original_record())

    def _original_record(self):
        with self.ledger(publication=True) as ledger:
            return json.loads(ledger.connection.execute("SELECT record FROM producer_sessions WHERE id=?",
                (self.attempt,)).fetchone()[0])

    def test_publication_interruption_blocks_generation_and_retry_is_safe(self):
        self.fixture.transport.interrupt_before_index = True
        with self.assertRaisesRegex(EvidenceError, "synthetic interruption"):
            self.apply()
        self.fixture.transport.interrupt_before_index = False
        with self.assertRaisesRegex(EvidenceError, "publication"):
            self.manager.begin_generation("blocked", "unit", 10, 1)
        self.apply()
        if os.name == 'posix':
            self.assertTrue(self.manager.assert_generation_authority()["coordinator_authorized"])
        else:
            with self.assertRaisesRegex(EvidenceError, 'requires POSIX main-thread'):
                self.manager.assert_generation_authority()
        self.assertIn(self.reservation, self.manager._catalog()['generation_quarantines'])
        self.assertEqual(self.original_record, self._original_record())

    def test_catalog_replay_rebinding_and_settlement_are_rejected(self):
        descriptor = self.apply()["descriptor"]
        changed = deepcopy(descriptor)
        changed["run_id"] = "substituted"
        changed["digest"] = hashlib.sha256(canonical({key: value for key, value in changed.items()
            if key != "digest"})).hexdigest()
        with self.manager.locked():
            self.manager._publish(self.manager._catalog(mutation=True),
                {"version": 1, "generation_quarantines": {self.reservation: changed}})
        with self.assertRaises(EvidenceError):
            self.manager._catalog()

    def test_unrelated_pending_intent_and_unknown_hold_cannot_gain_acceptance(self):
        def preexisting_work():
            self.manager.begin_generation("parallel-pending", "unit", 10, 1)
            with self.ledger() as ledger:
                self.additional_reservation = ledger.reserve("another-unknown", "unit", 12, 2)
        if os.name != 'posix':
            self.prepare_fixture(preexisting_work)
        self.apply()
        if os.name == 'posix':
            self.manager.begin_generation("parallel-pending", "unit", 10, 1)
        code, receipt, _ = self.receipt()
        self.assertEqual(1, code)
        self.assertFalse(receipt["generation_ready"])
        self.assertFalse(receipt["selected_scope"]["complete"])
        self.assertIn('parallel-pending', {item['run_id'] for item in receipt['pending_generation_intents'].values()})

        with self.ledger(publication=True) as ledger:
            if os.name == 'posix':
                self.additional_reservation = ledger.reserve("another-unknown", "unit", 12, 2)
            ledger.record_uncertain(self.additional_reservation, 3, 1)
            self.assertIsNotNone(ledger.connection.execute('SELECT 1 FROM uncertain_generation WHERE reservation_id=?',
                                                          (self.additional_reservation,)).fetchone())
        with self.assertRaises(EvidenceError):
            self.manager.begin_generation("blocked", "unit", 10, 1)

    def test_scoped_receipt_does_not_hide_unisolated_pending_reservation(self):
        def preexisting_work(*, publication=False):
            with self.ledger(publication=publication) as ledger:
                ledger.reserve("unisolated-known-run", "unit", 10, 1)
        if os.name != 'posix':
            self.prepare_fixture(preexisting_work)
        self.apply()
        if os.name == 'posix':
            preexisting_work(publication=True)
        code, receipt, _ = self.receipt()
        self.assertEqual(1, code)
        self.assertFalse(receipt["generation_ready"])
        self.assertFalse(receipt["selected_scope"]["complete"])
        self.assertEqual(1, receipt['runs']['unisolated-known-run']['pending_reservations'])

    def test_scoped_receipt_does_not_hide_unreconciled_output(self):
        def preexisting_work(*, publication=False):
            output = self.fixture.base / "unreconciled-output"
            output.mkdir()
            with self.ledger(publication=publication) as ledger:
                hold = ledger.reserve("unreconciled-run", "unit", 10, 1)
                ledger.register_output("unreconciled-run", "unit", output)
                ledger.settle(hold, 0, 0)
        if os.name != 'posix':
            self.prepare_fixture(preexisting_work)
        self.apply()
        if os.name == 'posix':
            preexisting_work(publication=True)
        code, receipt, _ = self.receipt()
        self.assertEqual(1, code)
        self.assertFalse(receipt["generation_ready"])
        self.assertFalse(receipt["selected_scope"]["complete"])
        self.assertEqual(1, receipt['runs']['unreconciled-run']['unreconciled_outputs'])

    def test_missing_original_ledger_cold_restore_retains_hold_and_blocks_generation(self):
        descriptor = self.apply()["descriptor"]
        cold = Manager(self.fixture.transport, self.fixture.base / "cold-home", self.manager.policy)
        with Accounting(cold.state / "accounting.sqlite", cold.policy["project_id"], cold.policy) as ledger:
            cold._reconcile_ledger(cold._catalog(), ledger)
            snapshot = ledger.snapshot()
            self.assertFalse(snapshot["accounting_complete"])
            self.assertFalse(ledger.generation_readiness()["ready"])
            hold = ledger.connection.execute("SELECT * FROM reservations WHERE id=?", (self.reservation,)).fetchone()
            self.assertEqual(descriptor["reservation"], dict(hold))
            self.assertEqual(24, snapshot["totals"]["project_generated_bytes"])
        with self.assertRaises(EvidenceError):
            cold.assert_generation_authority()

    def test_quarantined_run_cannot_be_reused_or_completed(self):
        self.apply()
        sequence = self.manager._catalog()["sequence"]
        reason = "quarantined historical run" if os.name == 'posix' else 'requires POSIX main-thread'
        with self.assertRaisesRegex(EvidenceError, reason):
            self.manager.begin_generation("old-run", "old-unit", 1024, 8)
        with self.ledger(publication=True) as ledger:
            with self.assertRaises(EvidenceError):
                ledger.complete_run("old-run")
        self.assertEqual(sequence, self.manager._catalog()["sequence"])
        self.assertEqual(self.original_record, self._original_record())

    def test_unverified_foreign_intent_still_blocks_new_generation(self):
        self.apply()
        owner = process_identity.identity()
        owner["host"] += "-unverified-host"
        with self.manager.locked():
            self.manager._publish(self.manager._catalog(mutation=True),
                {"version": 1, "generation_intents": {str(uuid.uuid4()): {
                    "run_id": "unknown-foreign-run", "unit_id": "unit",
                    "reserve_bytes": 10, "reserve_files": 1,
                    "owner_pid": owner["pid"], "owner_host": owner["host"], "owner_identity": owner}}})
        reason = "unknown local accounting" if os.name == 'posix' else 'requires POSIX main-thread'
        with self.assertRaisesRegex(EvidenceError, reason):
            self.manager.begin_generation("blocked", "unit", 10, 1)
        self.assertIn('unknown-foreign-run', {item['run_id'] for item in self.manager._catalog()['generation_intents'].values()})
        self.assertEqual(self.original_record, self._original_record())

    def test_cli_quarantine_defaults_to_dry_run(self):
        path = self.fixture.base / "proof.json"
        path.write_text(json.dumps(self.proof))
        for apply in (False, True):
            arguments = ["evidence_store.py", "quarantine-producer", "--attempt-id", self.attempt,
                "--proof", str(path)] + (["--apply"] if apply else [])
            with patch.object(evidence_store, "project_setup", return_value=None), \
                    patch.object(evidence_store, "load_manager", return_value=self.manager), \
                    patch.object(sys, "argv", arguments), redirect_stdout(StringIO()) as output:
                code = evidence_store.main()
            result = json.loads(output.getvalue())
            self.assertEqual(0, code, result)
            self.assertEqual(not apply, result["dry_run"])
            self.assertEqual(apply, bool(self.manager._catalog()["generation_quarantines"]))


if __name__ == "__main__":
    unittest.main()
