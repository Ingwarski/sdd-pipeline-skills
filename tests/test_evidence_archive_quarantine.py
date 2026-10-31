"""Real local archive/quarantine integration; synthetic bytes, never product acceptance."""
from copy import deepcopy
import hashlib
import os
import signal
import time
import unittest
from unittest.mock import patch

import test_evidence_quarantine_manager as strict_fixtures
import test_evidence_quarantine_device_integration as device_fixtures
from evidence import quarantine, quarantine_device
from evidence.io import EvidenceError
from evidence.manager import canonical
from evidence.resolver import EvidenceResolver


@unittest.skipUnless(os.name == 'posix', 'fresh quarantine publication requires POSIX main-thread alarms')
class ArchiveQuarantineTests(unittest.TestCase):
    def fixture(self, *, device=False, publish=True):
        owner = (device_fixtures.QuarantineDeviceIntegrationTests if device else
                 strict_fixtures.QuarantineManagerTests)(methodName='runTest')
        owner.setUp()
        self.addCleanup(owner.doCleanups)
        strict = owner.fixture if device else owner
        if publish:
            owner.apply()
        return owner, strict, strict.fixture

    def historical_rows(self, strict):
        with strict.ledger() as ledger:
            return {table: [tuple(row) for row in ledger.connection.execute('SELECT * FROM ' + table)]
                    for table in ('runs', 'reservations', 'uncertain_generation', 'producer_sessions',
                                  'outputs', 'observations', 'producer_quarantines',
                                  'producer_quarantine_device_witnesses', 'durable_generation')}

    def assert_history(self, strict, before, *, unchanged=False):
        after = self.historical_rows(strict)
        for table, rows in before.items():
            if unchanged:
                self.assertEqual(rows, after[table], table)
            else:
                for row in rows:
                    self.assertIn(row, after[table], table)
        with strict.ledger() as ledger:
            snapshot = ledger.snapshot()
            self.assertFalse(snapshot['accounting_complete'])
            self.assertTrue(snapshot['totals_are_lower_bounds'])
        self.assertFalse(strict.manager._catalog()['generation_intents'][strict.intent].get('settled'))
        self.assertFalse(hasattr(strict.manager, '_archive_ledger'))
        self.assertIsNone(strict.manager._active_reservation)

    def archive_success(self, *, migration, device):
        owner, strict, storage = self.fixture(device=device)
        manager = strict.manager
        before = self.historical_rows(strict)
        path = storage.file('archive/original.bin', b'Isolated sealed archive original.\n' * 50)
        specification = storage.spec(path)
        phases = []
        payload_gets_before = sum(key.endswith('.zip') for key in storage.transport.gets)
        original = manager._producer_publication_coverage
        def coverage(ledger, *args, **kwargs):
            self.assertFalse(ledger.connection.in_transaction)
            self.assertGreater(manager._catalog_lock_depth, 0)
            self.assertEqual((manager, None, None), ledger._publication_manager)
            phases.append(len(storage.transport.gets))
            return original(ledger, *args, **kwargs)
        with patch.object(manager, '_producer_publication_coverage', coverage):
            refs = manager.archive(specification, migration=migration)
        self.assertGreaterEqual(len(phases), 1 if migration else 2,
                                'reservation and ordinary run completion must each refresh publication')
        self.assertEqual(1, len(refs))
        reference = refs[0]
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), reference['sha256'])
        self.assertEqual(path.read_bytes(), EvidenceResolver(manager.cache).resolve(reference).read_bytes())
        self.assertTrue(storage.pack_puts())
        self.assertEqual(payload_gets_before + 1, sum(key.endswith('.zip') for key in storage.transport.gets),
                         'the first independent durable readback also prepares the fresh cache')
        # A separate empty cache must independently retrieve the durable original.
        cold = type(manager)(storage.transport, storage.base / 'cold-archive-home', manager.policy)
        cold.prepare(refs)
        self.assertEqual(payload_gets_before + 2, sum(key.endswith('.zip') for key in storage.transport.gets),
                         'a separate cold cache must perform another independent durable readback')
        self.assertEqual(path.read_bytes(), EvidenceResolver(cold.cache).resolve(reference).read_bytes())
        with strict.ledger(publication=True) as ledger:
            ready = ledger.generation_readiness()
            self.assertTrue(ready['ready'])
            self.assertFalse(ready['history_complete'])
            new = [dict(row) for row in ledger.connection.execute('SELECT * FROM runs WHERE id != ?', ('old-run',))]
            self.assertEqual(1, len(new))
            self.assertEqual(migration, bool(new[0]['migration']))
            self.assertEqual('active' if migration else 'complete', new[0]['status'])
            self.assertEqual(path.stat().st_size, new[0]['gross_bytes'])
        self.assert_history(strict, before)

    def test_ordinary_archive_under_strict_quarantine(self):
        self.archive_success(migration=False, device=False)

    def test_migration_archive_under_strict_quarantine(self):
        self.archive_success(migration=True, device=False)

    def test_ordinary_archive_under_device_custody_quarantine(self):
        self.archive_success(migration=False, device=True)

    def test_migration_archive_under_device_custody_quarantine(self):
        self.archive_success(migration=True, device=True)

    def denied(self, strict, storage, *, pattern=None):
        manager = strict.manager
        before = self.historical_rows(strict)
        path = storage.file('denied/original.bin', b'Never upload before fresh admission.')
        specification = storage.spec(path)
        puts = list(storage.transport.puts)
        with self.assertRaisesRegex(EvidenceError, pattern or '.'):
            manager.archive(specification, migration=True)
        self.assertEqual(puts, storage.transport.puts, 'denied fresh admission must not upload')
        self.assertEqual(b'Never upload before fresh admission.', path.read_bytes())
        # Catalog may deliberately be invalid in these cases: compare SQL directly.
        self.assertEqual(before, self.historical_rows(strict))
        with strict.ledger() as ledger:
            snapshot = ledger.snapshot()
            self.assertFalse(snapshot['accounting_complete'])
            self.assertTrue(snapshot['totals_are_lower_bounds'])
        self.assertFalse(hasattr(manager, '_archive_ledger'))
        self.assertIsNone(manager._active_reservation)

    def test_missing_publication_denies_without_changing_old_rows_or_uploading(self):
        owner, strict, storage = self.fixture(publish=False)
        storage.transport.interrupt_before_index = True
        with self.assertRaisesRegex(EvidenceError, 'synthetic interruption'):
            owner.apply()
        storage.transport.interrupt_before_index = False
        self.denied(strict, storage)

    def test_conflicting_publication_denies_without_changing_old_rows_or_uploading(self):
        owner, strict, storage = self.fixture()
        changed = deepcopy(owner.apply()['descriptor'])
        changed['run_id'] = 'conflicting-historical-run'
        changed['digest'] = hashlib.sha256(canonical({k: v for k, v in changed.items() if k != 'digest'})).hexdigest()
        with strict.manager.locked():
            strict.manager._publish(strict.manager._catalog(mutation=True),
                {'version': 1, 'generation_quarantines': {strict.reservation: changed}})
        self.denied(strict, storage)

    def test_changed_retained_native_bytes_deny_without_changing_old_rows_or_uploading(self):
        _, strict, storage = self.fixture()
        (strict.output / 'retained.txt').write_text('Changed current native bytes')
        self.denied(strict, storage)

    def test_missing_device_witness_denies_without_changing_old_rows_or_uploading(self):
        owner, strict, storage = self.fixture(device=True)
        with strict.ledger() as ledger:
            ledger._device_path(owner.operation).unlink()
        self.denied(strict, storage)

    def test_conflicting_device_publication_denies_without_changing_old_rows_or_uploading(self):
        owner, strict, storage = self.fixture(device=True)
        changed = deepcopy(owner.apply()['witness'])
        changed['validated_at'] = '2026-10-28T00:00:01Z'
        changed['digest'] = quarantine.digest({k: v for k, v in changed.items() if k != 'digest'})
        with strict.manager.locked():
            strict.manager._publish(strict.manager._catalog(mutation=True), {'version': 1,
                'generation_quarantine_device_witnesses': {owner.descriptor['digest']: changed}})
        self.denied(strict, storage)

    def test_completion_refresh_rejects_retained_bytes_changed_after_admission(self):
        _, strict, storage = self.fixture()
        manager = strict.manager
        before = self.historical_rows(strict)
        path = storage.file('late-drift/original.bin', b'Admitted before retained native bytes drift.')
        specification = storage.spec(path)
        phases = []
        original = manager._producer_publication_coverage
        def coverage(ledger, *args, **kwargs):
            self.assertFalse(ledger.connection.in_transaction)
            phases.append(len(storage.pack_puts()))
            if len(phases) == 2:
                (strict.output / 'retained.txt').write_text('Native retained bytes drift after admission')
            return original(ledger, *args, **kwargs)
        with patch.object(manager, '_producer_publication_coverage', coverage):
            with self.assertRaisesRegex(EvidenceError, 'quarantine publication/native validation incomplete'):
                manager.archive(specification)
        self.assertEqual(0, phases[0])
        self.assertGreater(phases[1], 0, 'completion must refresh after the admitted archive transfer')
        self.assert_history(strict, before)
        with strict.ledger() as ledger:
            run = ledger.connection.execute('SELECT status FROM runs WHERE id=?',
                                            (specification['files'][0]['provenance']['run_id'],)).fetchone()
            self.assertEqual('active', run[0], 'native drift cannot complete the new run')

    def test_slow_fresh_publication_is_bounded_and_preserves_old_rows(self):
        _, strict, storage = self.fixture()
        manager = strict.manager
        original_coverage = manager._producer_publication_coverage
        original_keys = storage.transport.keys
        entered = []
        def slow_keys(*args, **kwargs):
            entered.append(True)
            time.sleep(.3)
            return original_keys(*args, **kwargs)
        def coverage(*args, **kwargs):
            with patch.object(storage.transport, 'keys', slow_keys):
                return original_coverage(*args, **kwargs)
        handler = signal.getsignal(signal.SIGALRM)
        timer = signal.getitimer(signal.ITIMER_REAL)
        self.assertEqual((0.0, 0.0), timer)
        started = time.monotonic()
        with patch.object(quarantine_device, 'PUBLICATION_TIMEOUT', .06), \
                patch.object(manager, '_producer_publication_coverage', coverage):
            self.denied(strict, storage, pattern='deadline')
        self.assertTrue(entered, 'exercise real fresh catalog read rather than raw-ledger rejection')
        self.assertLess(time.monotonic() - started, .8)
        self.assertEqual(handler, signal.getsignal(signal.SIGALRM))
        self.assertEqual(timer, signal.getitimer(signal.ITIMER_REAL))


if __name__ == '__main__':
    unittest.main()
