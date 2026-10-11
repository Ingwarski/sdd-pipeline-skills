"""Budget reservations use actual complete packs and shared restoration occupancy."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/to-sdd-pipeline/scripts'))
from evidence.accounting import Accounting, BudgetExceeded
from evidence.io import EvidenceError, atomic_json
from evidence.manager import Manager
from evidence.policy import load_defaults
from evidence.transports import LocalTransport


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.policy = {**load_defaults(), 'project_id': str(uuid.uuid4()), 'store_id': str(uuid.uuid4()), 'provider': 'local'}
        self.policy['limits']['free_space_reserve_bytes'] = 0
        self.transport = LocalTransport(self.base / 'durable')
        self.manager = Manager(self.transport, self.base / 'home', self.policy)
        self.spec = {'version': 1, 'files': []}
        for index, data in enumerate((b'x' * 100, b'y' * 262144)):
            path = self.base / ('capture-' + str(index))
            path.write_bytes(data)
            self.spec['files'].append({'path': str(path), 'sealed_at': '2026-01-01T00:00:00Z',
                'provenance': {'run_id': 'run', 'unit_id': 'unit'}})

    def test_small_member_must_reserve_entire_shared_pack_before_download(self):
        refs = self.manager.archive(self.spec)
        catalog = self.manager._catalog()
        for path in (self.manager.cache / 'objects').iterdir():
            path.unlink()
        # Enough for the original bug's 300B estimate, insufficient for whole pack.
        self.manager.limits['local_stop_bytes'] = self.manager._usage() + 262244 + 2048
        self.manager.limits['cache_stop_bytes'] = 1000
        with patch.object(self.transport, 'get', wraps=self.transport.get) as get:
            with self.assertRaisesRegex(EvidenceError, 'local working-space'):
                self.manager.prepare([refs[0]], catalog=catalog)
            self.assertEqual(0, get.call_count)
        self.assertFalse((self.manager.cache / 'objects' / refs[0]['sha256']).exists())

    def test_parallel_managers_share_transient_holds(self):
        other = Manager(self.transport, self.base / 'home', self.policy)
        # Account SQLite's transaction overhead in this synthetic tiny allowance.
        self.manager.limits.update(local_stop_bytes=750000, cache_stop_bytes=100000)
        other.limits.update(local_stop_bytes=750000, cache_stop_bytes=100000)
        held, release, second_entered = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def worker():
            try:
                with self.manager._working(400000):
                    held.set()
                    release.wait(10)
            except BaseException as error:
                errors.append(error)
                held.set()
        thread = threading.Thread(target=worker)
        thread.start()
        def second_worker():
            try:
                with other._working(400000):
                    second_entered.set()
            except BaseException as error:
                errors.append(error)
        second = threading.Thread(target=second_worker)
        try:
            self.assertTrue(held.wait(10))
            self.assertEqual([], errors)
            second.start()
            self.assertFalse(second_entered.wait(0.1), 'coordinator operations must serialize their combined working peaks')
            with Accounting(self.manager.state / 'accounting.sqlite', self.policy['project_id'], self.policy) as ledger:
                self.assertEqual(400000, ledger.snapshot()['totals']['pending_working_bytes'])
        finally:
            release.set()
            thread.join(10)
            if second.ident is not None:
                second.join(10)
        self.assertFalse(thread.is_alive())
        self.assertFalse(second.is_alive())
        self.assertTrue(second_entered.is_set())
        self.assertEqual([], errors)
        with Accounting(self.manager.state / 'accounting.sqlite', self.policy['project_id'], self.policy) as ledger:
            self.assertEqual(0, ledger.snapshot()['totals']['pending_working_bytes'])

    def test_external_restoration_is_registered_and_remains_charged(self):
        refs = self.manager.archive(self.spec)
        restored = self.manager.restore(refs, self.base / 'restoration')
        self.assertEqual([Path(x).read_bytes() for x in restored], [Path(x['path']).read_bytes() for x in self.spec['files']])
        with Accounting(self.manager.state / 'accounting.sqlite', self.policy['project_id'], self.policy) as ledger:
            amount = ledger.connection.execute("SELECT SUM(bytes) FROM local_usage WHERE kind='restore'").fetchone()[0]
            self.assertEqual(262244, amount)
            self.assertEqual(0, ledger.snapshot()['totals']['pending_working_bytes'])
        self.assertEqual(262244, self.manager.status()['gross_generated_bytes'])

    def test_completed_archive_retry_reverifies_remote_and_handles_verified_removed_originals(self):
        refs = self.manager.archive(self.spec, remove_local=True)
        self.assertEqual(refs, self.manager.archive(self.spec, remove_local=True))
        self.transport.delete(self.manager._catalog()['packs'][refs[0]['locator']['pack_sha256']]['locator'])
        with self.assertRaises(EvidenceError):
            self.manager.archive(self.spec)

    def test_archive_error_releases_connection_and_active_hold_omission(self):
        with patch.object(self.transport, 'put', side_effect=EvidenceError('interrupted')):
            with self.assertRaises(EvidenceError):
                self.manager.archive(self.spec)
        self.assertIsNone(self.manager._active_reservation)
        self.assertFalse(hasattr(self.manager, '_archive_ledger'))

    def test_reconcile_dead_catalog_lock_is_explicit_and_verified(self):
        lock = self.manager.state / 'catalog.lock'
        lock.mkdir()
        atomic_json(lock / 'owner.json', {'pid': 12345, 'host': socket.gethostname(), 'coordinator': self.manager.coordinator})
        with patch.object(self.manager, '_owner_alive', return_value=False):
            result = self.manager.reconcile(dry_run=True)
            self.assertTrue(lock.exists())
            self.assertTrue(result[0]['dry_run'])
            result = self.manager.reconcile(dry_run=False)
            self.assertFalse(lock.exists())
            self.assertTrue(result[0]['verified'])
        with self.manager.locked():
            self.assertTrue(lock.exists())

    def test_reconcile_preserves_live_or_foreign_coordinator_lock(self):
        lock = self.manager.state / 'catalog.lock'
        lock.mkdir()
        atomic_json(lock / 'owner.json', {'pid': os.getpid(), 'host': socket.gethostname(), 'coordinator': self.manager.coordinator})
        with self.assertRaisesRegex(EvidenceError, 'still running'):
            self.manager.reconcile(dry_run=False)
        self.assertTrue(lock.exists())

    def test_migration_batch_bounds_are_enforced_before_payload_upload(self):
        self.manager.limits['migration_batch_stop_bytes'] = 262243
        with patch.object(self.transport, 'put', wraps=self.transport.put) as put:
            with self.assertRaisesRegex(EvidenceError, 'migration batch bytes'):
                self.manager.archive(self.spec, migration=True)
            self.assertEqual(0, put.call_count)

    def test_unpublished_verified_pack_remains_in_authoritative_occupancy(self):
        original = self.transport.put
        def interrupt(key, source):
            if '/indexes/' in key:
                raise EvidenceError('interrupted publication')
            return original(key, source)
        with patch.object(self.transport, 'put', side_effect=interrupt):
            with self.assertRaisesRegex(EvidenceError, 'interrupted publication'):
                self.manager.archive(self.spec)
        status = self.manager.status()
        self.assertEqual(1, status['physical_objects'])
        self.assertEqual(1, status['unreconciled_archive_objects'])
        self.assertGreater(status['retained_allowance_bytes'], 262244)
        self.assertEqual(262244, status['gross_generated_bytes'])
        self.manager.archive(self.spec)
        self.assertEqual(0, self.manager.status()['unreconciled_archive_objects'])
        self.assertEqual(262244, self.manager.status()['gross_generated_bytes'])

    def test_duplicate_default_names_require_distinct_portable_associations(self):
        paths = [self.base / 'a' / 'report.json', self.base / 'b' / 'report.json']
        spec = {'version': 1, 'files': []}
        for path in paths:
            path.parent.mkdir()
            path.write_bytes(b'identical')
            spec['files'].append({'path': str(path), 'sealed_at': '2026-01-01T00:00:00Z',
                'provenance': {'run_id': 'names', 'unit_id': 'names'}})
        with self.assertRaisesRegex(EvidenceError, 'distinct relative original_path'):
            self.manager.archive(spec)
        for index, item in enumerate(spec['files']):
            item['original_path'] = ('a' if index == 0 else 'b') + '/report.json'
        refs = self.manager.archive(spec)
        self.assertEqual(2, len({ref['artifact_id'] for ref in refs}))
        self.assertEqual(1, len({ref['locator']['object_id'] for ref in refs}))

    def test_dead_local_working_hold_reconciles_actual_remaining_bytes(self):
        with Accounting(self.manager.state / 'accounting.sqlite', self.policy['project_id'], self.policy) as ledger:
            ident = ledger.reserve_working(1000)
            ledger.connection.execute('UPDATE working_reservations SET owner_pid=? WHERE id=?', (12345, ident))
        leftover = self.manager.staging / 'registered-leftover'
        leftover.write_bytes(b'z' * 100)
        with patch.object(self.manager, '_owner_alive', return_value=False):
            result = self.manager.reconcile(dry_run=False)
        self.assertTrue(any(action['action'] == 'reconcile-exited-working-reservation' for action in result))
        self.assertTrue(leftover.exists())
        with Accounting(self.manager.state / 'accounting.sqlite', self.policy['project_id'], self.policy) as ledger:
            self.assertEqual(0, ledger.snapshot()['totals']['pending_working_bytes'])
            self.assertGreaterEqual(ledger.snapshot()['totals']['local_bytes'], 100)


if __name__ == '__main__':
    unittest.main()
