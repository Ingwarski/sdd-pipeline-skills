"""Synthetic public custody/guardian integration; never product acceptance.

Only the initial historical fixture capture substitutes device numbers. Current
scanners and the spawned native guardian always use real unpatched stat data.
"""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sys
import threading
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import test_evidence_quarantine_manager as fixtures
import test_evidence_checker as checker_fixtures
from evidence import process_identity, producer_runtime, quarantine, quarantine_device
from evidence import producer as producer_module
from evidence.io import EvidenceError, hash_file
from evidence.manager import Manager
from evidence.producer import _inventory, run_producer
import evidence_store


@unittest.skipUnless(os.name == 'posix', 'current custody and self-alarm require POSIX')
class QuarantineDeviceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.QuarantineManagerTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manager = self.fixture.manager
        self.base = self.fixture.fixture.base
        self.output = self.fixture.output
        self.output.chmod(0o700)
        for number in range(5):
            (self.output / ('retained-%s.txt' % number)).write_text('synthetic retained %s' % number)
        for path in self.output.iterdir():
            path.chmod(0o600)
        self.old_device = self.output.stat().st_dev + 1
        with self.ledger() as ledger:
            original = deepcopy(self.fixture.original_record)
            original['output_identity'][0] = self.old_device
            raw = json.dumps(original, sort_keys=True, ensure_ascii=True, allow_nan=False)
            ledger.connection.execute('UPDATE producer_sessions SET record=? WHERE id=?',
                                      (raw, self.fixture.attempt))
        self.fixture.original_record = original
        self.fixture.proof['original_record_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
        inventory = [dict(path=name, identity=[self.old_device, item[1]], size=item[2],
                          sha256=hash_file(self.output / name)[0])
                     for name, item in sorted(_inventory(self.output).items())]
        self.assertEqual(6, len(inventory))
        with patch.object(quarantine, 'current_inventory', return_value=inventory):
            self.descriptor = self.fixture.apply()['descriptor']
        self.operation = str(uuid.uuid4())
        with self.ledger() as ledger:
            current = quarantine_device.scan_current(ledger, self.descriptor, original)
        self.assertion = dict(version=1, kind='quarantine-device-current-custody-assertion',
            operation_id=self.operation,
            **{key: self.descriptor[key] for key in ('project_id', 'store_id', 'ledger_id',
                                                    'attempt_id', 'reservation_id', 'intent_id')},
            original_descriptor_digest=self.descriptor['digest'],
            original_record_sha256=self.descriptor['original_record_sha256'],
            original_policy_sha256=self.descriptor['policy_sha256'],
            current_policy_sha256=quarantine.digest(self.manager.policy),
            coordinator_authority_sha256=quarantine.digest(self.manager._generation_authority()),
            root_path=str(self.output),
            old_view=dict(root_identity=self.descriptor['output_identity'],
                          inventory_sha256=self.descriptor['inventory_sha256'],
                          inventory=self.descriptor['inventory']),
            new_view=current, verifier='isolated SDK test owner', observed_at='2026-10-28T00:00:00Z',
            purpose='retain-quarantined-gap-for-fresh-distinct-runs',
            limitations='Synthetic captured device substitution; no historical physical continuity')
        path = self.base / 'named-custody-assertion.json'
        path.write_text(json.dumps(self.assertion, indent=2) + '\n')
        path.chmod(0o600)
        self.assertion_ref = dict(path=str(path), sha256=hash_file(path)[0])

    def ledger(self):
        return self.fixture.ledger()

    def apply(self):
        return self.manager.revalidate_quarantine_device(self.fixture.attempt, self.assertion_ref,
                                                        operation_id=self.operation, dry_run=False)

    def historical_rows(self):
        with self.ledger() as ledger:
            return {table: [tuple(row) for row in ledger.connection.execute('SELECT * FROM ' + table)]
                    for table in ('runs', 'reservations', 'uncertain_generation', 'producer_sessions',
                                  'outputs', 'producer_quarantines')}

    def _run_deferred_native_case(self, *, deny_completion):
        self.apply()
        before = self.historical_rows()
        run = 'deferred-denied-run' if deny_completion else 'deferred-positive-run'
        intent = self.manager.begin_generation(run, 'deferred-unit', 4096, 8)
        output = self.base / 'deferred-native-output'
        output.mkdir(mode=0o700)
        attempts = []
        original_coverage = self.manager._producer_publication_coverage
        def coverage(ledger, *args, **kwargs):
            self.assertFalse(ledger.connection.in_transaction)
            attempt = kwargs.get('attempt_id')
            if attempt is not None:
                attempts.append(attempt)
                if deny_completion and len(attempts) == 2:
                    raise EvidenceError('synthetic deferred completion publication denied')
            return original_coverage(ledger, *args, **kwargs)
        with self.ledger() as ledger, patch.object(self.manager, '_producer_publication_coverage', coverage):
            result = run_producer(ledger, run, 'deferred-unit', output,
                [sys.executable, '-B', '-c', "from pathlib import Path; Path('fresh.txt').write_text('measured deferred bytes')"],
                4096, 8, timeout=15, poll_interval=.02, complete_run=False,
                intent_id=intent, manager=self.manager)
            self.assertIsNone(ledger._publication_manager)
            self.native_record = producer_runtime.read(ledger, result['attempt_id'])
            row = dict(ledger.connection.execute('SELECT * FROM runs WHERE id=?', (run,)).fetchone())
            reservation = dict(ledger.connection.execute('SELECT * FROM reservations WHERE id=?',
                                                         (result['reservation_id'],)).fetchone())
        self.deferred_observation = dict(result=result, run=row, reservation=reservation,
                                         attempt_bound_publication_calls=attempts)
        self.assertEqual('measured deferred bytes', (output / 'fresh.txt').read_text())
        self.assertGreaterEqual(result['gross_bytes'], len(b'measured deferred bytes'))
        self.assertGreaterEqual(row['gross_bytes'], len(b'measured deferred bytes'))
        self.assertGreaterEqual(result['gross_files'], 1)
        self.assertEqual('settled', reservation['state'])
        self.assertTrue(result['final_observation_complete'])
        self.assertIn('final_observation', self.native_record)
        self.assertEqual('gone', process_identity.state(self.native_record['guardian']))
        for item in self.native_record['processes'].values():
            self.assertEqual('gone', process_identity.state(item['identity']))
        for item in self.native_record['resources']:
            self.assertFalse(Path(item['path']).exists(), item['path'])
        after = self.historical_rows()
        for table, rows in before.items():
            for historical in rows:
                self.assertIn(historical, after[table], table)
        self.assertGreaterEqual(len(attempts), 2,
            'deferred guardian must refresh BOTH launch and completion publication')
        self.assertEqual(1, len(set(attempts)))
        self.assertEqual('deferred', result['run_completion'])
        self.assertFalse(self.manager._catalog()['generation_intents'][intent].get('settled'))
        return result, row

    def test_deferred_native_success_refreshes_worker_completion_without_completing_run(self):
        result, row = self._run_deferred_native_case(deny_completion=False)
        self.assertEqual('complete', result['status'])
        self.assertEqual('active', row['status'], 'run completion remains a separate deferred action')

    def test_deferred_native_completion_denial_preserves_measured_failed_result(self):
        result, row = self._run_deferred_native_case(deny_completion=True)
        self.assertEqual('incomplete', result['status'])
        self.assertEqual('incomplete', row['status'])
        self.assertIn('synthetic deferred completion publication denied', result['problem'])
        self.assertNotEqual('complete', self.native_record['result']['status'])

    def test_public_apply_native_guardian_finish_receipt_checker_and_cli(self):
        before = self.historical_rows()
        applied = self.apply()
        self.assertEqual(before, self.historical_rows())
        self.assertFalse(applied['history_complete'])
        sequence = self.manager._catalog()['sequence']
        self.assertEqual(applied, self.apply())
        self.assertEqual(sequence, self.manager._catalog()['sequence'])
        intent = self.manager.begin_generation('fresh-device-run', 'fresh-device-unit', 4096, 8)
        output = self.base / 'fresh-native-output'
        output.mkdir(mode=0o700)
        phases = []
        original_coverage = self.manager._producer_publication_coverage
        def coverage(ledger, *args, **kwargs):
            self.assertFalse(ledger.connection.in_transaction)
            phases.append(kwargs.get('attempt_id'))
            return original_coverage(ledger, *args, **kwargs)
        with self.ledger() as ledger, patch.object(self.manager, '_producer_publication_coverage', coverage):
            result = run_producer(ledger, 'fresh-device-run', 'fresh-device-unit', output,
                [sys.executable, '-B', '-c', "from pathlib import Path; Path('fresh.txt').write_text('fresh')"],
                4096, 8, timeout=15, poll_interval=.02, intent_id=intent, manager=self.manager)
            self.assertIsNone(ledger._publication_manager)
            self.native_record = producer_runtime.read(ledger, result['attempt_id'])
        self.assertEqual('complete', result['status'])
        self.assertEqual('gone', process_identity.state(self.native_record['guardian']))
        for item in self.native_record['processes'].values():
            self.assertEqual('gone', process_identity.state(item['identity']))
        for item in self.native_record['resources']:
            self.assertFalse(Path(item['path']).exists(), item['path'])
        self.assertGreaterEqual(sum(item is not None for item in phases), 2,
                                'native guardian must refresh launch and completion coverage')
        self.assertTrue(self.manager.finish_generation(intent, result['reservation_id'])['settled'])
        with self.assertRaisesRegex(EvidenceError, 'quarantined'):
            self.manager.finish_generation(self.fixture.intent, self.fixture.reservation)
        policy = self.base / 'portable-policy.json'
        policy.write_text(json.dumps(self.manager.policy, indent=4) + '\n')
        with self.manager.accounting_receipt_snapshot(hash_file(policy)[0]) as receipt:
            self.assertGreater(self.manager._catalog_lock_depth, 0)
            self.assertEqual(3, receipt['version'])
            self.assertEqual('scoped-known-generation-with-device-custody', receipt['kind'])
            self.assertFalse(receipt['accounting_complete'])
            self.assertFalse(receipt['history_complete'])
            self.assertTrue(receipt['totals_are_lower_bounds'])
            self.assertTrue(receipt['generation_ready'])
            self.assertEqual({'run_ids': ['fresh-device-run'], 'complete': True}, receipt['selected_scope'])
            self.assertEqual('incomplete', receipt['runs']['old-run']['status'])
            self.assertEqual([applied['witness']], receipt['quarantine_device_witnesses'])
        check = checker_fixtures.EvidenceCheckerTests(methodName='runTest')
        check.setUp()
        self.addCleanup(check.doCleanups)
        check.p.write('forge/evidence-policy.json', policy.read_text())
        check.m['evidence_storage'] = {'policy_path': 'forge/evidence-policy.json'}
        check.m['evidence_accounting'] = receipt
        check.checker().evidence_accounting(run_id='fresh-device-run', unit_id='fresh-device-unit')
        with self.assertRaisesRegex(ValueError, 'outside.*scope'):
            check.checker().evidence_accounting(run_id='old-run', unit_id='old-unit')
        for field in ('quarantine_device_witnesses', 'quarantine_device_catalog'):
            check.m['evidence_accounting'] = deepcopy(receipt)
            check.m['evidence_accounting'][field] = [] if field.endswith('witnesses') else {}
            with self.assertRaises((ValueError, EvidenceError)):
                check.checker().evidence_accounting(run_id='fresh-device-run', unit_id='fresh-device-unit')
        arguments = ['evidence_store.py', 'accounting-receipt', '--policy', str(policy)]
        test = self
        class LockedEmission(StringIO):
            def write(self, value):
                test.assertGreater(test.manager._catalog_lock_depth, 0,
                                   'CLI must emit while the verified catalog lock remains held')
                return super().write(value)
        with patch.object(evidence_store, 'project_setup', return_value=None), \
                patch.object(evidence_store, 'load_manager', return_value=self.manager), \
                patch.object(sys, 'argv', arguments), redirect_stdout(LockedEmission()) as captured:
            code = evidence_store.main()
        self.assertEqual(0, code)
        self.assertEqual(3, json.loads(captured.getvalue())['version'])
        with self.ledger() as ledger:
            self.assertEqual(self.fixture.original_record, producer_runtime.read(ledger, self.fixture.attempt))
        self.manager.begin_generation('pending-extra-run', 'pending-unit', 64, 2)
        with patch.object(evidence_store, 'project_setup', return_value=None), \
                patch.object(evidence_store, 'load_manager', return_value=self.manager), \
                patch.object(sys, 'argv', arguments), redirect_stdout(StringIO()) as captured:
            code = evidence_store.main()
        self.assertEqual(1, code)
        rejected = json.loads(captured.getvalue())
        self.assertTrue(rejected['incomplete'])
        self.assertIn('complete selected known scope', rejected['error'])

    def test_raw_quarantine_admission_requires_live_manager_and_restores_binding_on_error(self):
        self.apply()
        intent = self.manager.begin_generation('fresh-blocked', 'unit', 64, 2)
        output = self.base / 'raw-blocked-output'
        output.mkdir()
        with self.ledger() as ledger:
            with self.assertRaisesRegex(EvidenceError, 'fresh Manager'):
                ledger.reserve('fresh-blocked', 'unit', 64, 2)
            with self.assertRaises(EvidenceError):
                run_producer(ledger, 'fresh-blocked', 'unit', output, [sys.executable, '-B', '-c', 'pass'],
                             64, 2, timeout=0, intent_id=intent, manager=self.manager)
            self.assertIsNone(ledger._publication_manager)
            with patch.object(producer_module, '_run_producer', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    run_producer(ledger, 'fresh-blocked', 'unit', output, [sys.executable, '-B', '-c', 'pass'],
                                 64, 2, timeout=1, intent_id=intent, manager=self.manager)
            self.assertIsNone(ledger._publication_manager)

    def test_local_witness_change_after_coverage_is_rejected_inside_transaction(self):
        self.apply()
        intent = self.manager.begin_generation('drift-run', 'unit', 64, 2)
        with self.ledger() as ledger:
            ledger._publication_manager = (self.manager, intent, time.monotonic() + 5)
            original_coverage = self.manager._producer_publication_coverage
            def drift(*args, **kwargs):
                coverage = original_coverage(*args, **kwargs)
                self.assertFalse(ledger.connection.in_transaction)
                sidecar = ledger.recovery_dir / ('quarantine-device-' + hashlib.sha256(self.operation.encode()).hexdigest() + '.json')
                sidecar.write_bytes(sidecar.read_bytes() + b' ')
                return coverage
            with patch.object(self.manager, '_producer_publication_coverage', drift):
                with self.assertRaises(EvidenceError):
                    ledger.reserve('drift-run', 'unit', 64, 2)
            self.assertIsNone(ledger.connection.execute("SELECT id FROM runs WHERE id='drift-run'").fetchone())

    def test_remote_only_drift_is_rejected_on_next_fresh_phase(self):
        self.apply()
        with self.ledger() as ledger:
            coverage = self.manager._producer_publication_coverage(ledger)
            self.assertTrue(coverage['witnesses'])
            # A finite check cannot promise lifetime remote atomicity. Retain a
            # previously checked local view, then publish a real catalog fork;
            # the NEXT phase must reread and reject, never reuse that old view.
            changed = deepcopy(self.apply()['witness'])
            changed['validated_at'] = '2026-10-28T00:00:01Z'
            changed['digest'] = quarantine.digest({k: v for k, v in changed.items() if k != 'digest'})
            with self.manager.locked():
                self.manager._publish(self.manager._catalog(mutation=True), {'version': 1,
                    'generation_quarantine_device_witnesses': {self.descriptor['digest']: changed}})
            with self.assertRaises(EvidenceError):
                self.manager._producer_publication_coverage(ledger)

    def test_whole_lock_and_slow_transport_share_one_deadline_and_restore_alarm(self):
        self.apply()
        other = Manager(self.fixture.fixture.transport, self.manager.home, self.manager.policy)
        acquired, release, released = threading.Event(), threading.Event(), threading.Event()
        contended, read_started = threading.Event(), threading.Event()
        errors = []
        def hold_lock():
            try:
                with other.locked():
                    acquired.set()
                    if not release.wait(10):
                        raise AssertionError('publication never observed the competing catalog lock')
            except BaseException as exc:
                errors.append(exc)
            finally:
                released.set()
        worker = threading.Thread(target=hold_lock)
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(release.set)
        self.assertTrue(acquired.wait(2))
        original_owner = self.manager._catalog_owner
        def observed_owner(*args, **kwargs):
            owner = original_owner(*args, **kwargs)
            if not contended.is_set():
                self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 0,
                                   'the publication alarm must already cover lock contention')
                contended.set()
                release.set()
            return owner
        original_keys = self.fixture.fixture.transport.keys
        def slow_keys(*args, **kwargs):
            read_started.set()
            self.assertTrue(contended.is_set())
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 0)
            # Block past the original absolute deadline. The real alarm must
            # interrupt transport; no startup-speed race or timer reset is used.
            threading.Event().wait(5)
            return original_keys(*args, **kwargs)
        handler = signal.getsignal(signal.SIGALRM)
        real_setitimer = signal.setitimer
        armed = []
        def observed_timer(which, seconds, *args):
            if seconds > 0:
                armed.append(seconds)
            return real_setitimer(which, seconds, *args)
        with self.ledger() as ledger, patch.object(self.fixture.fixture.transport, 'keys', slow_keys), \
                patch.object(self.manager, '_catalog_owner', observed_owner), \
                patch.object(signal, 'setitimer', observed_timer):
            # Ledger setup is outside the operation under test. Lock acquisition
            # and all catalog/transport work share this one real timer.
            started = time.monotonic()
            deadline = started + 2
            with self.assertRaisesRegex(EvidenceError, 'deadline'):
                self.manager._producer_publication_coverage(ledger, deadline=deadline)
        elapsed = time.monotonic() - started
        self.assertEqual(1, len(armed), 'lock and transport must not each receive a fresh publication timer')
        self.assertLessEqual(armed[0], 2)
        self.assertGreaterEqual(time.monotonic(), deadline)
        self.assertTrue(read_started.is_set(), 'exercise transport after real catalog lock contention')
        self.assertLess(elapsed, 5)
        self.assertTrue(released.wait(2))
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors, errors)
        self.assertEqual(handler, signal.getsignal(signal.SIGALRM))
        self.assertEqual((0.0, 0.0), signal.getitimer(signal.ITIMER_REAL))

    def test_alarm_restored_on_success_error_and_base_exception(self):
        handler = signal.getsignal(signal.SIGALRM)
        with self.manager._publication_budget(time.monotonic() + 1):
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        for error in (EvidenceError('injected validation error'), KeyboardInterrupt()):
            with self.assertRaises(type(error)):
                with self.manager._publication_budget(time.monotonic() + 1):
                    raise error
            self.assertEqual(handler, signal.getsignal(signal.SIGALRM))
            self.assertEqual((0.0, 0.0), signal.getitimer(signal.ITIMER_REAL))

    def test_timer_setup_failure_restores_handler_even_when_timer_reset_also_fails(self):
        original_handler = signal.getsignal(signal.SIGALRM)
        real_setitimer = signal.setitimer
        self.assertEqual((0.0, 0.0), signal.getitimer(signal.ITIMER_REAL))
        def prior_handler(*_):
            pass
        try:
            for reset_also_fails in (False, True):
                with self.subTest(reset_also_fails=reset_also_fails):
                    signal.signal(signal.SIGALRM, prior_handler)
                    calls = []
                    def setup_failure(which, seconds, *args):
                        calls.append((which, seconds))
                        if seconds > 0:
                            raise OSError('synthetic timer setup failure')
                        if reset_also_fails:
                            raise OSError('synthetic timer reset failure')
                        return real_setitimer(which, seconds, *args)
                    with patch.object(signal, 'setitimer', setup_failure):
                        with self.assertRaises(OSError):
                            with self.manager._publication_budget(time.monotonic() + 1):
                                self.fail('failed timer setup must not enter the publication body')
                    self.assertGreaterEqual(len(calls), 2, 'setup failure must still attempt timer cleanup')
                    self.assertEqual(prior_handler, signal.getsignal(signal.SIGALRM))
                    self.assertEqual((0.0, 0.0), signal.getitimer(signal.ITIMER_REAL))
        finally:
            real_setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, original_handler)

    def test_preexisting_alarm_and_nonmain_thread_reject_without_replacing_alarm(self):
        handler = signal.getsignal(signal.SIGALRM)
        signal.setitimer(signal.ITIMER_REAL, 20, 3)
        try:
            with self.assertRaisesRegex(EvidenceError, 'existing process alarm'):
                with self.manager._publication_budget():
                    self.fail('must reject before changing alarm')
            remaining, interval = signal.getitimer(signal.ITIMER_REAL)
            self.assertGreater(remaining, 19)
            self.assertEqual(3, interval)
            self.assertEqual(handler, signal.getsignal(signal.SIGALRM))
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        errors = []
        def enter():
            try:
                with self.manager._publication_budget():
                    errors.append('unexpected success')
            except EvidenceError as exc:
                errors.append(str(exc))
        worker = threading.Thread(target=enter)
        worker.start()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(1, len(errors))
        self.assertIn('main-thread', errors[0])
        self.assertEqual(handler, signal.getsignal(signal.SIGALRM))


class PublicationChannelIntegrationTests(unittest.TestCase):
    def pair(self, seconds=1):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        return quarantine_device.PublicationChannel(left, deadline=time.monotonic() + seconds), right

    def test_eof_timeout_malformed_and_oversized_messages_fail_closed(self):
        for raw in (None, b'{malformed}\n', b'x' * (quarantine_device.MAXIMUM + 1)):
            with self.subTest(raw='EOF' if raw is None else len(raw)):
                channel, remote = self.pair(.15)
                if raw is None:
                    remote.close()
                else:
                    def send():
                        try:
                            remote.sendall(raw)
                        except OSError:
                            pass
                    sender = threading.Thread(target=send)
                    sender.start()
                    self.addCleanup(sender.join, 2)
                with self.assertRaises((EvidenceError, ValueError)):
                    channel._line(.15)
                channel.close()
                if raw is not None:
                    sender.join(2)
                    self.assertFalse(sender.is_alive())
        channel, _ = self.pair(.08)
        started = time.monotonic()
        with self.assertRaisesRegex(EvidenceError, 'deadline'):
            channel._line(600)
        self.assertLess(time.monotonic() - started, .5)

    def test_frame_receive_and_parse_cannot_return_after_absolute_deadline(self):
        real_loads = json.loads
        for slow_step in ('receive', 'parse'):
            with self.subTest(slow_step=slow_step):
                channel, remote = self.pair(.06)
                deadline = channel.deadline
                remote.sendall(b'{"synthetic":"bounded real socket frame"}\n')
                raw_socket = channel.stream
                class SlowReceive:
                    def fileno(self):
                        return raw_socket.fileno()
                    def recv(self, amount):
                        time.sleep(max(0, deadline - time.monotonic()) + .02)
                        return raw_socket.recv(amount)
                def slow_parse(*args, **kwargs):
                    time.sleep(max(0, deadline - time.monotonic()) + .02)
                    return real_loads(*args, **kwargs)
                if slow_step == 'receive':
                    channel.stream = SlowReceive()
                parser = slow_parse if slow_step == 'parse' else real_loads
                started = time.monotonic()
                with patch.object(quarantine_device.json, 'loads', parser):
                    with self.assertRaisesRegex(EvidenceError, 'deadline'):
                        channel._line(600)
                self.assertGreaterEqual(time.monotonic(), deadline)
                self.assertEqual(deadline, channel.deadline)
                self.assertLess(time.monotonic() - started, .5)

    def test_response_nonce_phase_replay_and_explicit_rejection_fail_closed(self):
        for defect in ('nonce', 'phase', 'replayed-response', 'error', 'missing-coverage'):
            with self.subTest(defect=defect):
                channel, remote = self.pair()
                errors = []
                def respond():
                    try:
                        raw = b''
                        while not raw.endswith(b'\n'):
                            raw += remote.recv(65536)
                        request = json.loads(raw)
                        response = {'request': deepcopy(request), 'publication': {}, 'error': None}
                        if defect in ('nonce', 'replayed-response'):
                            response['request']['nonce'] = str(uuid.uuid4())
                        elif defect == 'phase':
                            response['request']['phase'] = 'completion'
                        elif defect == 'error':
                            response['error'] = 'synthetic rejected current publication'
                        else:
                            response['publication'] = None
                        remote.sendall(quarantine.canonical(response) + b'\n')
                    except BaseException as exc:
                        errors.append(exc)
                worker = threading.Thread(target=respond)
                worker.start()
                with self.assertRaises(EvidenceError):
                    channel.request(SimpleNamespace(_ledger_id='synthetic-ledger'), 'intent', 'attempt', 'guardian-launch')
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertFalse(errors, errors)

    def test_cancelled_service_never_contacts_manager(self):
        channel, remote = self.pair()
        request = dict(version=1, phase='completion', nonce=str(uuid.uuid4()),
                       intent_id='intent', attempt_id='attempt', ledger_id='ledger')
        remote.sendall(quarantine.canonical(request) + b'\n')
        manager = SimpleNamespace(_producer_publication_coverage=lambda *a, **k: self.fail('cancelled lookup'))
        channel.service(manager, SimpleNamespace(_ledger_id='ledger'), 'intent', 'attempt', cancelled=True)
        response = json.loads(remote.recv(65536))
        self.assertEqual(request, response['request'])
        self.assertIsNone(response['publication'])
        self.assertIn('cancelled', response['error'])


if __name__ == '__main__':
    unittest.main()
