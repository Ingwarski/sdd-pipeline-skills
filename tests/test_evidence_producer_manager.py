"""Generic producer recovery at durable catalog and command boundaries."""
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
import os
import socket
import sqlite3
import sys
import threading
import time
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

    def test_manager_without_quarantine_keeps_payload_timeout_and_omits_gate_publication_deadline(self):
        from evidence.producer import run_producer
        intent = self.manager.begin_generation('ordinary-slow-preflight', 'unit', 4096, 8)
        output = self.fixture.base / 'ordinary-timeout-output'; output.mkdir()
        probe = self.fixture.base / 'request-probe'; probe.mkdir()
        request_file = self.fixture.base / 'observed-native-gate-request.json'
        # Observe the real guardian's unmodified gate request in its child
        # interpreter; no fake producer result or patched native SDK function.
        hook = '''import json, pathlib, subprocess
_actual_popen = subprocess.Popen
def _observed_popen(*args, **kwargs):
    process = _actual_popen(*args, **kwargs)
    argv = args[0] if args else kwargs.get('args', [])
    if isinstance(argv, list) and argv and argv[-1] == 'gate' and process.stdin is not None:
        original = process.stdin
        class Stream:
            def __getattr__(self, name): return getattr(original, name)
            def write(self, raw):
                pathlib.Path(REQUEST_PATH).write_bytes(raw)
                return original.write(raw)
        process.stdin = Stream()
    return process
subprocess.Popen = _observed_popen
'''.replace('REQUEST_PATH', repr(str(request_file)))
        (probe / 'sitecustomize.py').write_text(hook)
        def delayed_preflight(ledger, *, dry_run):
            time.sleep(.35)
            return {'actions': [], 'incomplete': False}
        self.recover.side_effect = delayed_preflight
        with self.ledger() as ledger, patch.dict(os.environ, {'PYTHONPATH': str(probe) + os.pathsep + os.environ.get('PYTHONPATH', '')}):
            result = run_producer(ledger, 'ordinary-slow-preflight', 'unit', output,
                [sys.executable, '-B', '-c', 'from pathlib import Path; Path("ordinary.txt").write_text("ok")'],
                4096, 8, timeout=.2, poll_interval=.02, intent_id=intent, manager=self.manager)
            self.assertIsNone(ledger._publication_manager)
        self.assertEqual('complete', result['status'], result)
        self.assertEqual('ok', (output / 'ordinary.txt').read_text())
        request = json.loads(request_file.read_bytes())
        self.assertNotIn('publication_deadline', request)
        self.assertTrue(self.manager.finish_generation(intent, result['reservation_id'])['settled'])

    def test_begin_reuses_final_catalog_only_inside_publication_lock(self):
        seed = self.manager.begin_generation("seed", "unit", 20, 2)
        recovery_depths, readiness_depths, published = [], [], []
        original_readiness = self.manager._generation_readiness
        original_publish = self.manager._publish

        def recover(ledger, *, dry_run):
            recovery_depths.append(self.manager._catalog_lock_depth)
            return {"actions": [], "incomplete": False}

        def readiness(catalog, ledger):
            readiness_depths.append(self.manager._catalog_lock_depth)
            published.append(catalog)
            return original_readiness(catalog, ledger)

        def publish(catalog, segment):
            self.assertIs(catalog, published[-1])
            self.assertEqual(1, self.manager._catalog_lock_depth)
            self.assertIn(seed, catalog["generation_intents"])
            return original_publish(catalog, segment)

        with patch.object(self.manager, "_catalog", wraps=self.manager._catalog) as catalogs, \
                patch.object(self.manager, "_generation_readiness", side_effect=readiness), \
                patch.object(self.manager, "_publish", side_effect=publish):
            self.recover.side_effect = recover
            first = self.manager.begin_generation("first", "unit", 20, 2)
            second = self.manager.begin_generation("second", "unit", 20, 2)
        self.assertEqual(4, catalogs.call_count, "each begin requires two fresh catalog validations")
        self.assertEqual([0, 0], recovery_depths, "do not hold catalog ownership during producer shutdown")
        self.assertEqual([1, 1], readiness_depths)
        self.assertEqual(0, self.manager._catalog_lock_depth)
        self.assertIn(first, published[1]["generation_intents"])
        self.assertIn(second, self.manager._catalog()["generation_intents"])

    def test_public_authority_keeps_result_shape_and_releases_catalog(self):
        with patch.object(self.manager, "_catalog", wraps=self.manager._catalog) as catalogs:
            result = self.manager.assert_generation_authority()
        self.assertEqual({"coordinator_authorized": True, "coordinator": self.manager.coordinator}, result)
        self.assertEqual(2, catalogs.call_count)
        self.assertEqual(0, self.manager._catalog_lock_depth)
        self.assertFalse((self.manager.state / "catalog.lock").exists())

    def test_final_catalog_reads_changed_original_index_bytes_after_recovery(self):
        self.manager.begin_generation("seed", "unit", 20, 2)
        catalog = self.manager._catalog()
        index = self.fixture.store / catalog["segments"][0]["locator"]["key"]
        puts = list(self.fixture.transport.puts)

        def change_bytes(ledger, *, dry_run):
            data = index.read_bytes()
            # Keep the size and valid JSON while changing the original bytes.
            self.assertIn(b'"seed"', data)
            index.write_bytes(data.replace(b'"seed"', b'"evil"'))
            return {"actions": [], "incomplete": False}

        self.recover.side_effect = change_bytes
        with self.assertRaisesRegex(EvidenceError, "index identity mismatch"):
            self.manager.begin_generation("must-not-start", "unit", 20, 2)
        self.assertEqual(puts, self.fixture.transport.puts)
        self.assertEqual(0, self.manager._catalog_lock_depth)

    def test_final_catalog_rechecks_authority_after_recovery(self):
        self.manager.begin_generation("seed", "unit", 20, 2)
        authority = self.fixture.store / self.manager.prefix / "authority/coordinator.json"
        puts = list(self.fixture.transport.puts)

        def replace_authority(ledger, *, dry_run):
            record = json.loads(authority.read_text())
            record["coordinator"] = "another-coordinator"
            authority.write_text(json.dumps(record))
            return {"actions": [], "incomplete": False}

        self.recover.side_effect = replace_authority
        with self.assertRaisesRegex(EvidenceError, "designated coordinator"):
            self.manager.begin_generation("must-not-start", "unit", 20, 2)
        self.assertEqual(puts, self.fixture.transport.puts)
        self.assertEqual(0, self.manager._catalog_lock_depth)

    def test_publication_retains_fresh_root_guard_after_readiness(self):
        seed = self.manager.begin_generation("seed", "unit", 20, 2)
        puts = list(self.fixture.transport.puts)
        original_publish = self.manager._publish

        def concurrent_root(catalog, segment):
            self.assertEqual(1, self.manager._catalog_lock_depth)
            previous = self.fixture.store / catalog["root_key"]
            # Simulate an out-of-band remote writer, outside the local lock.
            changed = previous.parent / ("999999999999-" + "0" * 64 + ".json")
            changed.write_bytes(previous.read_bytes())
            try:
                return original_publish(catalog, segment)
            finally:
                changed.unlink()

        with patch.object(self.manager, "_publish", side_effect=concurrent_root), \
                self.assertRaisesRegex(EvidenceError, "catalog changed on another client"):
            self.manager.begin_generation("must-not-start", "unit", 20, 2)
        self.assertEqual(puts, self.fixture.transport.puts)
        self.assertEqual({seed}, set(self.manager._catalog()["generation_intents"]))
        self.assertEqual(0, self.manager._catalog_lock_depth)

    def test_begin_final_catalog_sees_automatic_recovery_settlement(self):
        old = self.publish_intent(legacy=True)
        with self.ledger() as ledger:
            hold = ledger.reserve("run", "unit", 20, 2)
            ledger.settle(hold, 5, 1)
        self.recover.return_value = {"actions": [self.action(old, hold)], "incomplete": False}
        with patch.object(self.manager, "_generation_owner_state", return_value="gone"), \
                patch.object(self.manager, "_catalog", wraps=self.manager._catalog) as catalogs:
            new = self.manager.begin_generation("new", "unit", 20, 2)
        self.assertEqual(3, catalogs.call_count, "automatic settlement owns its additional fresh catalog")
        actual = self.manager._catalog()
        self.assertEqual(3, actual["sequence"])
        self.assertTrue(actual["generation_intents"][old]["settled"])
        self.assertIn(new, actual["generation_intents"])
        self.assertEqual([False, True], [call.kwargs["dry_run"] for call in self.recover.call_args_list])
        with self.ledger() as ledger:
            self.assertEqual(5, ledger.snapshot()["totals"]["project_generated_bytes"])

    def test_unknown_owner_keeps_full_original_hold_and_blocks_new_intent(self):
        old = self.manager.begin_generation("run", "unit", 20, 2)
        with self.ledger() as ledger:
            hold = ledger.reserve("run", "unit", 20, 2)
            original = dict(ledger.connection.execute("SELECT * FROM reservations WHERE id=?", (hold,)).fetchone())
        puts = list(self.fixture.transport.puts)
        with patch.object(self.manager, "_generation_owner_state", return_value="unknown"), \
                self.assertRaisesRegex(EvidenceError, "unknown local accounting"):
            self.manager.begin_generation("must-not-start", "unit", 20, 2)
        self.assertEqual(puts, self.fixture.transport.puts)
        self.assertEqual({old}, set(self.manager._catalog()["generation_intents"]))
        with self.ledger() as ledger:
            self.assertEqual(original, dict(ledger.connection.execute("SELECT * FROM reservations WHERE id=?", (hold,)).fetchone()))

    def test_incomplete_recovery_preserves_hold_floor_and_publication_state(self):
        self.manager.begin_generation("run", "unit", 20, 2)
        with self.ledger() as ledger:
            hold = ledger.reserve("run", "unit", 20, 2)
            ledger.record_uncertain(hold, 7, 1)
            before = ledger.snapshot()
            uncertain = [tuple(row) for row in ledger.connection.execute("SELECT * FROM uncertain_generation")]
        puts = list(self.fixture.transport.puts)
        self.recover.return_value = {"actions": [{"action": "retained", "incomplete": True}], "incomplete": True}
        with self.assertRaisesRegex(EvidenceError, "producer recovery remains incomplete"):
            self.manager.begin_generation("must-not-start", "unit", 20, 2)
        self.assertEqual(puts, self.fixture.transport.puts)
        with self.ledger() as ledger:
            after = ledger.snapshot()
            self.assertEqual(before["reservations"], after["reservations"])
            self.assertEqual(before["runs"], after["runs"])
            # Manager control metadata is freshly accounted by catalog reads;
            # producer charges, uncertainty and reservations never decrease.
            for key in before["totals"]:
                if key not in {"metadata_bytes", "metadata_files", "local_bytes", "cache_bytes", "ledger_bytes"}:
                    self.assertEqual(before["totals"][key], after["totals"][key], key)
            self.assertEqual(uncertain, [tuple(row) for row in ledger.connection.execute("SELECT * FROM uncertain_generation")])
            self.assertFalse(after["accounting_complete"])

    def test_capacity_failure_releases_final_lock_without_publishing(self):
        seed = self.manager.begin_generation("seed", "unit", 20, 2)
        puts = list(self.fixture.transport.puts)
        original_readiness = self.manager._generation_readiness

        def exhaust(catalog, ledger):
            result = original_readiness(catalog, ledger)
            # Capacity changes after validation must still be enforced by publish.
            self.manager.limits["metadata_stop_files"] = catalog["metadata_files"]
            return result

        original_limit = self.manager.limits["metadata_stop_files"]
        try:
            with patch.object(self.manager, "_generation_readiness", side_effect=exhaust), \
                    self.assertRaisesRegex(EvidenceError, "metadata/index/history budget"):
                self.manager.begin_generation("must-not-start", "unit", 20, 2)
        finally:
            self.manager.limits["metadata_stop_files"] = original_limit
        self.assertEqual(puts, self.fixture.transport.puts)
        self.assertEqual({seed}, set(self.manager._catalog()["generation_intents"]))
        self.assertFalse((self.manager.state / "catalog.lock").exists())

    def test_two_clients_serialize_final_readiness_through_publication(self):
        other = fixtures.Manager(self.fixture.transport, self.manager.home, self.manager.policy)
        ready, release, other_started, other_entered = (threading.Event() for _ in range(4))
        original_publish = self.manager._publish
        original_other_catalog = other._catalog_locked

        def pause(catalog, segment):
            ready.set()
            if not release.wait(timeout=10):
                raise AssertionError("test publication barrier timed out")
            return original_publish(catalog, segment)

        def observe_other(**kwargs):
            other_entered.set()
            return original_other_catalog(**kwargs)

        def start_other():
            other_started.set()
            return other.begin_generation("second", "unit", 20, 2)

        with patch.object(self.manager, "_publish", side_effect=pause), \
                patch.object(other, "_catalog_locked", side_effect=observe_other), \
                ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.manager.begin_generation, "first", "unit", 20, 2)
            try:
                self.assertTrue(ready.wait(timeout=10))
                second = pool.submit(start_other)
                self.assertTrue(other_started.wait(timeout=10))
                self.assertFalse(other_entered.wait(timeout=.1), "another client entered the retained catalog lock")
            finally:
                release.set()
            identities = {first.result(timeout=10), second.result(timeout=10)}
        actual = self.manager._catalog()
        self.assertEqual(identities, set(actual["generation_intents"]))
        self.assertEqual(2, actual["sequence"])
        self.assertEqual(0, self.manager._catalog_lock_depth)
        self.assertEqual(0, other._catalog_lock_depth)

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
