"""Synthetic custody schemas/scans/append crashes; never a private ledger."""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import time
import unittest
from unittest.mock import patch
import uuid

import test_evidence_quarantine_manager as fixtures
from evidence import producer_runtime
from evidence.io import EvidenceError
from evidence.accounting import Accounting, BudgetExceeded
from evidence.quarantine import canonical, digest, validate_current
from evidence.quarantine_device import (scan_current, validate_device_custody_assertion,
    validate_quarantine_device_witness, verify_quarantine_device_current)


@unittest.skipUnless(os.name == 'posix', 'device current custody is POSIX only')
class DeviceCustodyTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.QuarantineManagerTests(methodName='runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.manager = self.f.manager
        self.f.output.chmod(0o700)
        for i in range(5):
            (self.f.output / ('retained-' + str(i))).write_bytes(b'historical-' + bytes([65 + i]))
        inventory = []
        old_dev = self.f.output.stat().st_dev + 1
        for path in sorted(self.f.output.iterdir()):
            path.chmod(0o600)
            info = path.stat()
            inventory.append({'path': path.name, 'size': info.st_size,
                              'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'identity': [old_dev, info.st_ino]})
        with self.f.ledger() as ledger:
            producer_runtime.update(ledger, self.f.attempt, lambda v: v.update(output_identity=[old_dev, self.f.output.stat().st_ino]))
            raw = ledger.connection.execute('SELECT record FROM producer_sessions WHERE id=?', (self.f.attempt,)).fetchone()[0]
            self.f.proof['original_record_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
        # Only initial historical capture uses the artificial old device. All
        # revalidation, including child processes in integration tests, is native.
        with patch('evidence.quarantine.current_inventory', return_value=inventory):
            self.descriptor = self.f.apply()['descriptor']
        self.operation = str(uuid.uuid4())
        self.assertion_path = self.f.fixture.base / 'custody-assertion.json'
        self.assertion = self.make_assertion()
        self.ref = self.save_assertion(self.assertion)

    def make_assertion(self):
        d = self.descriptor
        with self.f.ledger() as ledger:
            record = producer_runtime.read(ledger, self.f.attempt)
            current = scan_current(ledger, d, record)
        return {'version': 1, 'kind': 'quarantine-device-current-custody-assertion',
            'operation_id': self.operation, **{k: d[k] for k in ('project_id', 'store_id', 'ledger_id', 'attempt_id', 'reservation_id', 'intent_id')},
            'original_descriptor_digest': d['digest'], 'original_record_sha256': d['original_record_sha256'],
            'original_policy_sha256': d['policy_sha256'], 'current_policy_sha256': digest(self.manager.policy),
            'coordinator_authority_sha256': digest(self.manager._generation_authority()), 'root_path': str(self.f.output),
            'old_view': {'root_identity': d['output_identity'], 'inventory_sha256': d['inventory_sha256'], 'inventory': d['inventory']},
            'new_view': current, 'verifier': 'synthetic-explicit-custody-owner', 'observed_at': '2026-10-28T01:00:00Z',
            'purpose': 'retain-quarantined-gap-for-fresh-distinct-runs',
            'limitations': 'Current view only; no historical continuity, same volume, authentic human, or exclusive writer proof.'}

    def save_assertion(self, assertion):
        self.assertion_path.write_text(json.dumps(assertion, indent=2) + '\n')
        self.assertion_path.chmod(0o600)
        return {'path': str(self.assertion_path), 'sha256': hashlib.sha256(self.assertion_path.read_bytes()).hexdigest()}

    def apply(self, **kw):
        return self.manager.revalidate_quarantine_device(self.f.attempt, self.ref, operation_id=self.operation, **kw)

    def originals(self):
        with self.f.ledger() as ledger:
            rows = {t: [tuple(row) for row in ledger.connection.execute('SELECT * FROM ' + t + ' ORDER BY 1')]
                    for t in ('runs', 'reservations', 'uncertain_generation', 'producer_sessions', 'outputs', 'observations', 'producer_quarantines')}
            journal = {p.name: p.read_bytes() for p in ledger.recovery_dir.iterdir() if p.name == 'marker.json' or p.name.startswith('run-')}
            return rows, journal

    def test_dry_apply_and_repeat_preserve_originals_and_frozen_bytes(self):
        before = self.originals()
        with self.f.ledger() as ledger:
            with self.assertRaisesRegex(EvidenceError, 'identity changed'):
                validate_current(ledger, self.descriptor)
        dry = self.apply()
        self.assertTrue(dry['dry_run'])
        self.assertEqual(before, self.originals())
        with self.f.ledger() as ledger:
            self.assertEqual({}, ledger.device_witnesses())
        applied = self.apply(dry_run=False)
        self.assertEqual(before, self.originals())
        catalog = self.manager._catalog()
        repeated = self.apply(dry_run=False)
        self.assertEqual(applied, repeated)
        self.assertEqual(catalog['sequence'], self.manager._catalog()['sequence'])
        self.assertEqual(before, self.originals())
        with self.f.ledger() as ledger:
            ledger._publication_manager = None
            self.assertFalse(ledger.generation_readiness()['ready'], 'raw local state cannot assert publication')
            ready = self.manager._generation_readiness(self.manager._catalog(), ledger)
            self.assertTrue(ready['ready'], ready)
        witness = applied['witness']
        self.assertFalse(witness['same_volume_proven'])
        self.assertFalse(witness['history_complete'])
        self.assertEqual(6, len(witness['new_view']['files']))

    def test_pure_schema_rejects_unknown_bool_nonfinite_and_rebindings(self):
        witness = self.apply()['witness']
        with patch('os.open', side_effect=AssertionError('pure validator performed IO')):
            self.assertEqual(witness, validate_quarantine_device_witness(witness, self.descriptor, self.manager.policy))
        changes = [lambda x: x.update(extra=True), lambda x: x.update(version=True),
                   lambda x: x.update(ledger_id='other'), lambda x: x.update(intent_id='other'),
                   lambda x: x.update(current_policy_sha256='0' * 64),
                   lambda x: x['new_view']['root'].update(uid=True),
                   lambda x: x['new_view']['root'].update(mode=0o755),
                   lambda x: x['new_view']['root']['identity'].__setitem__(0, x['old_view']['root_identity'][0]),
                   lambda x: x['new_view']['files'][0].update(nlink=2),
                   lambda x: x['new_view']['files'][0].update(size=float('nan')),
                   lambda x: x['new_view']['files'][0].update(path='nested/path'),
                   lambda x: x['new_view']['files'][0]['identity'].__setitem__(1, 1),
                   lambda x: x['new_view']['files'][0]['identity'].__setitem__(0, 0)]
        for i, change in enumerate(changes):
            with self.subTest(i=i):
                value = deepcopy(self.assertion)
                change(value)
                with self.assertRaises((EvidenceError, ValueError)):
                    validate_device_custody_assertion(value, self.descriptor, self.manager.policy)

    def test_native_flat_ownership_modes_links_and_byte_changes_reject(self):
        path = self.f.output / 'retained.txt'
        actions = [('directory', lambda: (self.f.output / 'empty').mkdir()),
                   ('link', lambda: (self.f.output / 'alias').symlink_to(path)),
                   ('hardlink', lambda: os.link(path, self.f.output / 'alias')),
                   ('mode', lambda: path.chmod(0o644)), ('bytes', lambda: path.write_bytes(b'changed'))]
        for label, action in actions:
            with self.subTest(label=label):
                original = path.read_bytes()
                action()
                try:
                    with self.assertRaises((EvidenceError, OSError)):
                        self.apply()
                finally:
                    extra = self.f.output / ('empty' if label == 'directory' else 'alias')
                    if extra.is_symlink() or extra.is_file(): extra.unlink()
                    elif extra.is_dir(): extra.rmdir()
                    path.write_bytes(original); path.chmod(0o600)
                    self.assertion = self.make_assertion()
                    self.ref = self.save_assertion(self.assertion)

    def test_sidecar_only_crash_freezes_candidate_and_same_operation_recovers(self):
        before = self.originals()
        candidate = self.apply()['witness']
        with self.f.ledger() as ledger, patch('evidence.accounting.os.fsync', side_effect=OSError('synthetic sidecar fsync failure')):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                ledger.append_device_witness(candidate)
        with self.f.ledger() as ledger:
            sidecar = ledger._device_preparations()[0][self.operation][0][1]
            with self.assertRaisesRegex(EvidenceError, 'orphan'):
                ledger.device_witnesses()
        applied = self.apply(dry_run=False)
        self.assertEqual(sidecar, applied['witness'])
        self.assertEqual(before, self.originals())

    def test_unknown_publication_outcome_reloads_and_does_not_republish(self):
        publish = self.manager._publish
        def lose_ack(catalog, segment, **kw):
            result = publish(catalog, segment, **kw)
            if 'generation_quarantine_device_witnesses' in segment:
                raise EvidenceError('synthetic lost publication acknowledgement')
            return result
        with patch.object(self.manager, '_publish', side_effect=lose_ack):
            with self.assertRaisesRegex(EvidenceError, 'lost publication'):
                self.apply(dry_run=False)
        sequence = self.manager._catalog()['sequence']
        self.apply(dry_run=False)
        self.assertEqual(sequence, self.manager._catalog()['sequence'])

    def test_partial_or_modified_row_sidecar_and_second_operation_fail_closed(self):
        witness = self.apply(dry_run=False)['witness']
        with self.f.ledger() as ledger:
            path = ledger._device_path(self.operation)
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            with self.assertRaises(EvidenceError): ledger.device_witnesses()
            path.write_bytes(original)
            ledger.connection.execute('DELETE FROM producer_quarantine_device_witnesses')
            self.assertFalse(ledger.generation_readiness()['ready'])
        with self.assertRaisesRegex(EvidenceError, 'missing or conflicting'):
            self.apply(dry_run=False)
        other = deepcopy(self.assertion); other['operation_id'] = str(uuid.uuid4())
        self.ref = self.save_assertion(other)
        with self.assertRaises(EvidenceError):
            self.manager.revalidate_quarantine_device(self.f.attempt, self.ref, operation_id=other['operation_id'], dry_run=False)

    def test_assertion_raw_sha_and_embedded_canonical_sha_are_distinct_and_bound(self):
        witness = self.apply()['witness']
        self.assertNotEqual(witness['assertion']['sha256'], witness['assertion']['ref']['sha256'])
        self.assertEqual(digest(self.assertion), witness['assertion']['sha256'])
        self.assertion_path.write_bytes(self.assertion_path.read_bytes() + b' ')
        with self.assertRaisesRegex(EvidenceError, 'SHA changed'):
            self.apply()

    def _sql_crash(self, statement):
        candidate = self.apply()['witness']
        before = self.originals()
        with self.f.ledger() as ledger:
            connection = ledger.connection
            class Interrupted:
                def __getattr__(inner, key): return getattr(connection, key)
                def execute(inner, sql, *args):
                    if sql.startswith(statement):
                        raise sqlite3.OperationalError('synthetic dedicated transaction crash')
                    return connection.execute(sql, *args)
            ledger.connection = Interrupted()
            with self.assertRaisesRegex(sqlite3.OperationalError, 'synthetic dedicated'):
                ledger.append_device_witness(candidate)
            ledger.connection = connection
            self.assertEqual(0, connection.execute('SELECT COUNT(*) FROM producer_quarantine_device_witnesses').fetchone()[0])
            self.assertEqual(candidate, ledger._device_sidecars()[self.operation])
        self.assertEqual(before, self.originals())
        self.assertEqual(candidate, self.apply(dry_run=False)['witness'])
        self.assertEqual(before, self.originals())

    def test_insert_crash_keeps_frozen_sidecar_and_all_historical_checkpoints(self):
        self._sql_crash('INSERT INTO producer_quarantine_device_witnesses')

    def test_commit_crash_keeps_frozen_sidecar_and_all_historical_checkpoints(self):
        self._sql_crash('COMMIT')

    def test_metadata_overflow_rejects_before_any_witness_or_history_write(self):
        before = self.originals()
        with self.f.ledger() as ledger:
            ledger.reconcile_metadata('synthetic-full', self.manager.limits['metadata_stop_bytes'], self.manager.limits['metadata_stop_files'])
        with self.assertRaises((EvidenceError, BudgetExceeded)):
            self.apply(dry_run=False)
        with self.f.ledger() as ledger:
            self.assertEqual({}, ledger._device_sidecars())
            self.assertEqual(0, ledger.connection.execute('SELECT COUNT(*) FROM producer_quarantine_device_witnesses').fetchone()[0])
        self.assertEqual(before, self.originals())

    def test_native_wrong_current_uid_nonposix_mount_and_hash_race_reject(self):
        with self.f.ledger() as ledger:
            record = producer_runtime.read(ledger, self.f.attempt)
            with patch('evidence.quarantine_device.os.getuid', return_value=os.getuid() + 1):
                with self.assertRaisesRegex(EvidenceError, 'owned private'):
                    scan_current(ledger, self.descriptor, record)
            with patch('evidence.quarantine_device.os.path.ismount', return_value=True):
                with self.assertRaisesRegex(EvidenceError, 'nonmount'):
                    scan_current(ledger, self.descriptor, record)
            with patch('evidence.quarantine_device.os.name', 'nt'):
                with self.assertRaisesRegex(EvidenceError, 'requires POSIX'):
                    scan_current(ledger, self.descriptor, record)
        from evidence.quarantine_device import _verify_stable
        changed = []
        def change_during_hash(path, handle, info):
            if path.parent == self.f.output and not changed:
                changed.append(path)
                path.write_bytes(b'concurrent synthetic writer')
            return _verify_stable(path, handle, info)
        with patch('evidence.quarantine_device._verify_stable', side_effect=change_during_hash):
            with self.assertRaises(EvidenceError):
                self.apply()

    def test_original_proof_and_missing_checkpoint_block_after_valid_publication(self):
        self.apply(dry_run=False)
        with self.f.ledger() as ledger:
            original = ledger._recovery_path('old-run').read_bytes()
            ledger._recovery_path('old-run').unlink()
            with self.assertRaises(EvidenceError):
                self.manager._generation_readiness(self.manager._catalog(), ledger)
            ledger._recovery_path('old-run').write_bytes(original)
        proof = Path(self.descriptor['proof']['external_disposition']['proof']['path'])
        proof.write_text('changed original external disposition')
        with self.f.ledger() as ledger:
            with self.assertRaises(EvidenceError):
                self.manager._generation_readiness(self.manager._catalog(), ledger)

    def test_append_preserves_original_marker_and_nine_run_checkpoints(self):
        # Explicit pre-existing synthetic history, not reconstructed execution.
        with self.f.ledger() as ledger, ledger._transaction():
            for i in range(8):
                run = 'synthetic-prior-' + str(i)
                ledger.connection.execute('INSERT INTO runs(id,unit_id,ordinal,migration,status,created) VALUES(?,?,0,0,\'complete\',0)',
                                          (run, 'prior-unit-' + str(i)))
                ledger._dirty_runs.add(run)
        before = self.originals()
        self.assertEqual(10, len(before[1]), 'one marker plus nine original run checkpoints')
        self.apply(dry_run=False)
        self.assertEqual(before, self.originals())

    def test_published_only_witness_blocks_even_if_old_strict_inventory_would_pass(self):
        self.apply(dry_run=False)
        with self.f.ledger() as ledger:
            ledger._device_path(self.operation).unlink()
            ledger.connection.execute('DELETE FROM producer_quarantine_device_witnesses')
            # Simulate the old device returning with its captured inventory.
            # An unsafe original-identity fallback would now accept this view.
            with patch('evidence.quarantine.current_inventory', return_value=deepcopy(self.descriptor['inventory'])):
                with self.assertRaises(EvidenceError):
                    self.manager._generation_readiness(self.manager._catalog(), ledger)
                self.assertFalse(ledger.generation_readiness()['ready'])

    def test_omitted_published_witness_segment_cannot_erase_mandatory_custody(self):
        self.apply(dry_run=False)
        catalog = self.manager._catalog()
        root = json.loads((self.f.fixture.store / catalog['root_key']).read_bytes())
        root.update(sequence=root['sequence'] + 1, previous=catalog['root_key'], segments=root['segments'][:-1])
        self.manager._put_json(self.manager.prefix + 'roots/' + str(root['sequence']).zfill(12) + '-', root)
        with self.f.ledger() as ledger:
            ledger._device_path(self.operation).unlink()
            ledger.connection.execute('DELETE FROM producer_quarantine_device_witnesses')
            with patch('evidence.quarantine.current_inventory', return_value=deepcopy(self.descriptor['inventory'])):
                with self.assertRaises(EvidenceError):
                    self.manager._generation_readiness(self.manager._catalog(), ledger)

    def test_valid_hashed_root_fork_cannot_hide_in_retained_root_inventory(self):
        self.apply(dry_run=False)
        catalog = self.manager._catalog()
        root = json.loads((self.f.fixture.store / catalog['root_key']).read_bytes())
        root['segments'] = root['segments'][:-1]
        self.manager._put_json(self.manager.prefix + 'roots/' + str(root['sequence']).zfill(12) + '-', root)
        with self.assertRaises(EvidenceError):
            self.manager._catalog()

    def test_interrupted_partial_write_never_publishes_partial_final_sidecar(self):
        candidate = self.apply()['witness']
        original_fdopen = os.fdopen
        @contextmanager
        def interrupted(fd, *args, **kwargs):
            with original_fdopen(fd, *args, **kwargs) as stream:
                class Partial:
                    def write(inner, data):
                        stream.write(data[:100]); stream.flush()
                        raise OSError('synthetic interrupted partial sidecar write')
                yield Partial()
        before = self.originals()
        with self.f.ledger() as ledger:
            with patch('evidence.accounting.os.fdopen', side_effect=interrupted):
                with self.assertRaisesRegex(OSError, 'interrupted partial'):
                    ledger.append_device_witness(candidate)
            self.assertFalse(ledger._device_path(self.operation).exists(), 'partial final name must never become visible')
        self.apply(dry_run=False)
        self.assertEqual(before, self.originals())

    def test_fsynced_preparation_survives_link_interruption_and_reuses_exact_candidate(self):
        candidate = self.apply()['witness']
        before = self.originals()
        with self.f.ledger() as ledger, patch('evidence.accounting.os.link', side_effect=OSError('synthetic atomic link interruption')):
            with self.assertRaisesRegex(OSError, 'atomic link'):
                ledger.append_device_witness(candidate)
        self.assertEqual(candidate, self.apply(dry_run=False)['witness'])
        self.assertEqual(before, self.originals())

    def test_linked_final_and_temp_pair_recovers_without_tolerating_unknown_hardlinks(self):
        candidate = self.apply()['witness']
        before = self.originals()
        with self.f.ledger() as ledger, patch('evidence.accounting.os.unlink', side_effect=OSError('synthetic temp unlink interruption')):
            with self.assertRaisesRegex(OSError, 'temp unlink'):
                ledger.append_device_witness(candidate)
            final = ledger._device_path(self.operation)
            self.assertEqual(2, final.stat().st_nlink)
            self.assertEqual(candidate, ledger._device_sidecars()[self.operation])
        self.assertEqual(candidate, self.apply(dry_run=False)['witness'])
        with self.f.ledger() as ledger:
            self.assertEqual(1, ledger._device_path(self.operation).stat().st_nlink)
            self.assertEqual({}, ledger._device_preparations()[0])
        self.assertEqual(before, self.originals())

    def test_child_gate_rejects_absolute_deadline_expired_after_parent_release_check(self):
        import subprocess
        self.apply(dry_run=False)
        intent = self.manager.begin_generation('gate-deadline', 'fresh-unit', 4096, 8)
        output = self.f.fixture.base / 'deadline-gate-output'; output.mkdir()
        marker = output / 'payload-must-not-run'
        owner = __import__('evidence.process_identity', fromlist=['identity']).identity()
        attempt = str(uuid.uuid4())
        record = dict(version=1, attempt_id=attempt, run_id='gate-deadline', unit_id='fresh-unit',
            reservation_id=None, output_id=None, intent_id=intent, coordinator=owner, guardian=owner,
            status='launching', processes={}, resources=[], output_dir=str(output),
            output_identity=producer_runtime.directory_identity(output), policy=self.manager.policy)
        real_popen = subprocess.Popen
        def delayed_gate_request(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            actual = process.stdin
            class Delayed:
                def __getattr__(inner, key): return getattr(actual, key)
                def write(inner, raw):
                    time.sleep(.35)
                    return actual.write(raw)
            process.stdin = Delayed()
            return process
        with self.f.ledger(publication=True) as ledger:
            hold = ledger.reserve('gate-deadline', 'fresh-unit', 4096, 8, local_bytes=4096,
                                  metadata_bytes=1024 * 1024, producer_record=record)
            output_id = ledger.register_output('gate-deadline', 'fresh-unit', output)
            producer_runtime.update(ledger, attempt, lambda v: v.update(output_id=output_id, status='running'))
            ledger._publication_manager = (self.manager, intent, time.monotonic() + .2)
            child = None
            try:
                with patch('evidence.producer_runtime.subprocess.Popen', side_effect=delayed_gate_request):
                    child = producer_runtime.launch(ledger, attempt,
                        [__import__('sys').executable, '-B', '-c', 'from pathlib import Path; Path(' + repr(str(marker)) + ').write_text("bad")'],
                        cwd=output, env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.assertNotEqual(0, child.process.wait(timeout=5))
                self.assertFalse(marker.exists())
            finally:
                if child is not None:
                    child.close()
                    child.process.wait(timeout=5)
            pending = ledger.connection.execute('SELECT state FROM reservations WHERE id=?', (hold,)).fetchone()[0]
            self.assertEqual('pending', pending, 'no fabricated settlement for an unmonitored gate fixture')

    def test_child_native_validation_cannot_authorize_use_after_absolute_deadline(self):
        self.apply(dry_run=False)
        with self.f.ledger() as ledger:
            publication = self.manager._publication_view(self.manager._catalog())
            class Deadline:
                deadline = time.monotonic() + .02
            ledger._publication_channel = (Deadline(), None, None, 'guardian-launch')
            original = ledger.generation_readiness
            def slow_native(**kwargs):
                result = original(**kwargs)
                time.sleep(.04)
                return result
            with patch.object(ledger, 'generation_readiness', side_effect=slow_native):
                with self.assertRaisesRegex(EvidenceError, 'deadline expired'):
                    ledger.require_generation_ready(_publication=publication)

    def test_quarantined_native_timeout_keeps_measured_charge_and_original_gap(self):
        import sys
        from evidence.producer import run_producer
        self.apply(dry_run=False)
        before = self.originals()
        intent = self.manager.begin_generation('bounded-payload', 'fresh-unit', 4096, 8)
        output = self.f.fixture.base / 'bounded-payload-output'; output.mkdir()
        actual = self.manager._producer_publication_coverage
        delayed = []
        def slow_first(*args, **kwargs):
            if not delayed:
                delayed.append(True); time.sleep(.25)
            return actual(*args, **kwargs)
        with self.f.ledger() as ledger, patch.object(self.manager, '_producer_publication_coverage', side_effect=slow_first):
            try:
                result = run_producer(ledger, 'bounded-payload', 'fresh-unit', output,
                    [sys.executable, '-B', '-c', 'from pathlib import Path; import time; Path("measured.txt").write_bytes(b"charged"); time.sleep(10)'],
                    4096, 8, timeout=3, poll_interval=.02, complete_run=False, intent_id=intent, manager=self.manager)
            except EvidenceError as exc:
                # EOF arriving after the absolute deadline can reject the
                # public call. Its retained native failed result must still
                # prove every measured-byte/history preservation assertion.
                self.assertIn('deadline', str(exc))
                raw = ledger.connection.execute("SELECT record FROM producer_sessions WHERE json_extract(record,'$.run_id')=?", ('bounded-payload',)).fetchone()[0]
                result = json.loads(raw)['result']
            self.assertEqual(b'charged', (output / 'measured.txt').read_bytes())
            self.assertEqual('incomplete', result['status'])
            self.assertIn('timeout', result['problem'])
            self.assertGreaterEqual(result['gross_bytes'], 7)
            record = producer_runtime.read(ledger, result['attempt_id'])
            self.assertIn('final_observation', record)
            run = ledger.connection.execute('SELECT status,gross_bytes FROM runs WHERE id=?', ('bounded-payload',)).fetchone()
            self.assertEqual('incomplete', run['status']); self.assertGreaterEqual(run['gross_bytes'], 7)
            for table, rows in before[0].items():
                after = [tuple(row) for row in ledger.connection.execute('SELECT * FROM ' + table)]
                for row in rows: self.assertIn(row, after, table)



class PolicyLineageCustodyTests(DeviceCustodyTests):
    def setUp(self):
        from evidence.policy import load_defaults
        defaults = load_defaults()
        defaults['limits'].update(max_unit_retries=8, local_stop_bytes=256 * 1024 * 1024,
                                  cache_stop_bytes=128 * 1024 * 1024,
                                  metadata_stop_bytes=16 * 1024 * 1024, metadata_stop_files=1024)
        with patch('test_evidence_manager.load_defaults', return_value=defaults):
            super().setUp()

    def successor(self):
        from evidence.policy import append_policy_transition
        old = self.manager.policy
        candidate = deepcopy(old)
        candidate['limits']['max_unit_retries'] += 1
        raw = (json.dumps(old, indent=2, sort_keys=True) + '\n').encode()
        new = append_policy_transition(raw, candidate)
        self.manager.policy = new
        self.manager.limits = new['limits']
        return new

    def test_published_witness_replays_under_successor_with_live_custody(self):
        witness = self.apply(dry_run=False)['witness']
        before = self.originals()
        new = self.successor()
        with patch('os.open', side_effect=AssertionError('portable validator performed IO')):
            self.assertEqual(witness, validate_quarantine_device_witness(witness, self.descriptor, new))
        self.manager.initialize_generation_authority()
        self.assertEqual(witness, self.apply(dry_run=False)['witness'])
        self.assertEqual(before, self.originals())
        with self.f.ledger() as ledger:
            authority = self.manager._generation_authority()
            verify_quarantine_device_current(ledger, self.descriptor, witness, coordinator_authority=authority)
            with self.assertRaises(EvidenceError):
                verify_quarantine_device_current(ledger, self.descriptor, witness, coordinator_authority={'foreign': True})
            with patch('evidence.quarantine_device.scan_current', return_value={'changed': True}):
                with self.assertRaises(EvidenceError):
                    verify_quarantine_device_current(ledger, self.descriptor, witness, coordinator_authority=authority)

    def test_frozen_sidecar_retries_but_unfrozen_old_assertion_rejects(self):
        witness = self.apply()['witness']
        with self.f.ledger() as ledger, patch('evidence.accounting.os.fsync', side_effect=OSError('frozen synthetic failure')):
            with self.assertRaises(OSError): ledger.append_device_witness(witness)
        new = self.successor()
        from evidence.quarantine_device import read_assertion, build_witness
        with self.assertRaises(EvidenceError): read_assertion(self.ref, self.descriptor, new)
        with self.f.ledger() as ledger:
            with self.assertRaises(EvidenceError):
                build_witness(ledger, self.descriptor, self.ref, self.operation, self.manager._generation_authority())
            retry = ledger.prepare_device_witness(self.descriptor, self.ref, self.operation, self.manager._generation_authority())
            self.assertEqual(witness, retry)
            changed = dict(self.ref, sha256='0' * 64)
            with self.assertRaises(EvidenceError):
                ledger.prepare_device_witness(self.descriptor, changed, self.operation, self.manager._generation_authority())

    def test_frozen_preparation_retries_after_transition(self):
        witness = self.apply()['witness']
        with self.f.ledger() as ledger, patch('evidence.accounting.os.link', side_effect=OSError('freeze before link')):
            with self.assertRaises(OSError): ledger.append_device_witness(witness)
        self.successor()
        self.manager.initialize_generation_authority()
        self.assertEqual(witness, self.apply(dry_run=False)['witness'])

    def test_current_resource_limit_still_applies_to_historical_witness(self):
        from evidence.policy import append_policy_transition
        witness = self.apply()['witness']
        old = self.manager.policy
        candidate = deepcopy(old)
        candidate['limits']['metadata_stop_files'] = 1
        new = append_policy_transition((json.dumps(old, indent=2, sort_keys=True) + '\n').encode(), candidate)
        with self.assertRaises(EvidenceError):
            validate_quarantine_device_witness(witness, self.descriptor, new)

    def test_historical_binding_rejects_tampering_and_corrupt_lineage(self):
        from evidence.policy import validate_policy
        witness = self.apply()['witness']
        new = self.successor()
        for key in ('project_id', 'store_id', 'ledger_id', 'original_descriptor_digest',
                    'original_record_sha256', 'original_policy_sha256', 'current_policy_sha256',
                    'coordinator_authority_sha256', 'root_path'):
            changed = deepcopy(witness)
            changed['assertion']['payload'][key] = '0' * 64
            changed['assertion']['sha256'] = digest(changed['assertion']['payload'])
            changed[key] = '0' * 64
            changed['digest'] = digest({k: v for k, v in changed.items() if k != 'digest'})
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                if key in ('coordinator_authority_sha256', 'root_path'):
                    with self.f.ledger() as ledger:
                        verify_quarantine_device_current(ledger, self.descriptor, changed, coordinator_authority=self.manager._generation_authority())
                else:
                    validate_quarantine_device_witness(changed, self.descriptor, new)
        for key in ('raw_sha256', 'policy_sha256'):
            broken = deepcopy(new); broken['policy_lineage']['base'][key] = '0' * 64
            with self.subTest(lineage=key), self.assertRaises(EvidenceError): validate_policy(broken)
        broken = deepcopy(new); broken['policy_lineage']['steps'][0]['digest'] = '0' * 64
        with self.assertRaises(EvidenceError): validate_policy(broken)


if __name__ == '__main__':
    unittest.main()
