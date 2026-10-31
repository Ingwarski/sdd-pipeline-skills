"""Setup publication/replay policy tests on an isolated local catalog, no subprocess/provider."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'skills/to-sdd-pipeline/scripts'))
import evidence_setup as setup
from evidence.io import EvidenceError
from evidence.manager import Manager
from evidence.policy import append_policy_transition, resolve_historical_policy
from evidence.quarantine import digest, validate_quarantine_descriptor
from evidence.transports import LocalTransport
from test_evidence_policy_lineage import setup_bytes, effective, descriptor_fixture


class FaultTransport(LocalTransport):
    def __init__(self, root):
        super().__init__(root)
        self.events = []; self.fail_before_root = False; self.fail_root_readback = False
        self.failed_readback_key = None

    def put(self, key, source_path):
        if '/roots/' in key and self.fail_before_root:
            self.fail_before_root = False
            self.events.append(('root_publication_failed', key))
            raise EvidenceError('synthetic failure before root publication')
        result = super().put(key, source_path)
        self.events.append(('put', key))
        if '/roots/' in key and self.fail_root_readback:
            self.failed_readback_key = key; self.fail_root_readback = False
        return result

    def get(self, locator, destination_path, max_bytes):
        key = locator['key'] if isinstance(locator, dict) else locator
        if key == self.failed_readback_key:
            self.failed_readback_key = None
            self.events.append(('root_readback_failed', key))
            raise EvidenceError('synthetic failure after root upload before readback acknowledgement')
        result = super().get(locator, destination_path, max_bytes)
        self.events.append(('get', key))
        return result


class SetupPolicyLineageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sdd-policy-lineage-setup-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.project = self.base / 'project'; self.project.mkdir()
        self.home = self.base / 'machine'; self.store = self.base / 'durable'
        self.transport = FaultTransport(self.store)
        self.policy_path = self.project / 'forge/evidence-policy.json'
        self.initialized = []; self.probes = []
        self.patch = patch.object(setup, '_initialize_authority', self.initialize)
        self.patch.start(); self.addCleanup(self.patch.stop)
        # Only the CLI subprocess seam is replaced; all manager, immutable catalog,
        # authority, readback, setup checkpoint and local policy writes are real fixtures.
        setup.configure(self.project, home=self.home, provider='folder', destination=str(self.store),
                        limits={'free_space_reserve_bytes': 0}, probe=self.probe)
        self.original_raw = self.policy_path.read_bytes(); self.original = json.loads(self.original_raw)
        self.prefix = 'projects/' + self.original['project_id'] + '/'
        self.transport.events.clear(); self.initialized.clear(); self.probes.clear()

    def probe(self, config, project):
        self.probes.append(deepcopy(config))
        return {'verified': True, 'synthetic_fixture': True, 'verification': 'independent_original_bytes'}

    def initialize(self, config, policy, project, *, host_session=None):
        self.initialized.append(deepcopy(policy))
        manager = Manager(self.transport, config['evidence_home'], policy)
        return manager.initialize_generation_authority()

    def configure(self, **changes):
        options = dict(home=self.home, provider='folder', destination=str(self.store), reconfigure=True, probe=self.probe)
        options.update(changes)
        return setup.configure(self.project, **options)

    def current(self):
        return json.loads(self.policy_path.read_bytes())

    def manager(self, policy=None, home=None):
        return Manager(self.transport, home or self.home, policy or self.current())

    def roots(self):
        return sorted(self.transport.keys(self.prefix + 'roots/'))

    def head(self):
        roots = self.roots()
        return json.loads((self.store / roots[-1]).read_bytes()) if roots else None

    def durable_bytes(self):
        return {str(path.relative_to(self.store)): path.read_bytes()
                for path in self.store.rglob('*') if path.is_file()}

    def next_limit(self):
        return {'max_unit_retries': self.current()['limits']['max_unit_retries'] + 1}

    def windows_text_defaults(self):
        # Exercise real text-stream translation on every host. Binary streams stay
        # binary, and an explicit writer newline retains its normal semantics.
        original = tempfile.NamedTemporaryFile
        def translated(*args, **kwargs):
            mode = kwargs.get('mode', args[0] if args else 'w+b')
            if 'b' not in mode:
                kwargs.setdefault('newline', '\r\n')
            return original(*args, **kwargs)
        return patch.object(tempfile, 'NamedTemporaryFile', translated)

    def test_new_setup_emits_lf_canonical_bytes_under_windows_text_translation(self):
        project = self.base / 'new-project'; project.mkdir()
        home = self.base / 'new-machine'
        with self.windows_text_defaults():
            result = setup.configure(project, home=home, provider='folder', destination=str(self.store),
                                     limits={'free_space_reserve_bytes': 0}, probe=self.probe)
        self.assertEqual(result['result'], 'configured')
        raw = (project / 'forge/evidence-policy.json').read_bytes()
        self.assertEqual(raw, setup_bytes(json.loads(raw)))
        self.assertNotIn(b'\r\n', raw)
        self.assertNotIn('policy_lineage', json.loads(raw))

    def test_crlf_original_anchor_and_two_supported_lf_transitions_keep_descriptor(self):
        original_raw = setup_bytes(self.original).replace(b'\n', b'\r\n')
        self.policy_path.write_bytes(original_raw)
        descriptor = descriptor_fixture(self.original); saved_descriptor = setup_bytes(descriptor)
        with self.windows_text_defaults():
            self.configure(limits=self.next_limit())
            first_raw = self.policy_path.read_bytes(); first = self.current()
            self.assertEqual(first_raw, setup_bytes(first))
            self.assertNotIn(b'\r\n', first_raw)
            self.configure(limits=self.next_limit())
        second_raw = self.policy_path.read_bytes(); second = self.current()
        self.assertEqual(second_raw, setup_bytes(second)); self.assertNotIn(b'\r\n', second_raw)
        self.assertEqual(len(second['policy_lineage']['steps']), 2)
        self.assertEqual(second['policy_lineage']['base']['raw_utf8'].encode(), original_raw)
        self.assertEqual(second['policy_lineage']['base']['raw_sha256'], hashlib.sha256(original_raw).hexdigest())
        self.assertEqual(resolve_historical_policy(second, digest(first)), first)
        self.assertEqual(validate_quarantine_descriptor(descriptor, second), descriptor)
        self.assertEqual(setup_bytes(descriptor), saved_descriptor)

    def test_existing_empty_plain_authority_can_publish_first_transition_then_local_policy(self):
        self.assertEqual(self.roots(), [])
        original_authority = self.durable_bytes()
        writes = []
        real_write = setup._write
        def observed_write(path, value):
            if path == self.policy_path:
                head = self.head(); self.assertIsNotNone(head)
                self.assertEqual(head['policy'], value)
                self.assertEqual(self.policy_path.read_bytes(), self.original_raw)
                roots = self.roots(); key = roots[-1]
                self.assertIn(('get', key), self.transport.events, 'Verified readback must precede local policy exposure')
                writes.append(key)
            return real_write(path, value)
        with patch.object(setup, '_write', observed_write): self.configure(limits=self.next_limit())
        self.assertEqual(len(writes), 1); self.assertEqual(len(self.roots()), 1)
        self.assertEqual(self.head()['policy'], self.current())
        self.assertEqual(self.current()['policy_lineage']['base']['raw_utf8'].encode(), self.original_raw)
        self.assertEqual(resolve_historical_policy(self.current(), digest(self.original)), self.original)
        for key, value in original_authority.items(): self.assertEqual(self.durable_bytes()[key], value)

    def test_second_transition_and_exact_retry_do_not_duplicate_policy_steps(self):
        self.configure(limits=self.next_limit()); first = self.current(); first_root = self.roots()[-1]
        self.configure(limits=self.next_limit()); second = self.current(); roots = self.roots()
        self.assertEqual(len(second['policy_lineage']['steps']), 2)
        self.assertEqual(self.head()['previous'], first_root)
        self.assertEqual(resolve_historical_policy(second, digest(first)), first)
        self.configure(limits={'max_unit_retries': second['limits']['max_unit_retries']})
        self.assertEqual(self.current(), second); self.assertEqual(self.roots(), roots)

    def test_failure_before_root_publication_never_exposes_new_local_policy_and_retries(self):
        self.transport.fail_before_root = True
        with self.assertRaises(EvidenceError): self.configure(limits=self.next_limit())
        self.assertEqual(self.policy_path.read_bytes(), self.original_raw); self.assertEqual(self.roots(), [])
        self.configure(limits=self.next_limit())
        self.assertEqual(len(self.roots()), 1); self.assertEqual(len(self.current()['policy_lineage']['steps']), 1)

    def test_unknown_root_upload_readback_outcome_retains_old_policy_and_exact_retry(self):
        self.transport.fail_root_readback = True
        with self.assertRaises(EvidenceError): self.configure(limits=self.next_limit())
        self.assertEqual(self.policy_path.read_bytes(), self.original_raw)
        uploaded = self.roots(); self.assertEqual(len(uploaded), 1)
        committed_policy = self.head()['policy']
        self.configure(limits=self.next_limit())
        self.assertEqual(self.roots(), uploaded); self.assertEqual(self.current(), committed_policy)
        self.assertEqual(len(self.current()['policy_lineage']['steps']), 1)

    def test_crash_after_verified_publication_before_local_policy_write_replays_once(self):
        real_write = setup._write
        def fail_policy_write(path, value):
            if path == self.policy_path: raise OSError('synthetic local policy-write interruption')
            return real_write(path, value)
        with patch.object(setup, '_write', fail_policy_write):
            with self.assertRaisesRegex(OSError, 'policy-write'): self.configure(limits=self.next_limit())
        self.assertEqual(self.policy_path.read_bytes(), self.original_raw)
        uploaded = self.roots(); candidate = self.head()['policy']
        self.configure(limits=self.next_limit())
        self.assertEqual(self.current(), candidate); self.assertEqual(self.roots(), uploaded)

    def test_crash_after_local_policy_write_before_pending_checkpoint_retirement_is_idempotent(self):
        real_write = setup._write
        def write_then_interrupt(path, value):
            result = real_write(path, value)
            if path == self.policy_path: raise OSError('synthetic interruption after local policy write')
            return result
        with patch.object(setup, '_write', write_then_interrupt):
            with self.assertRaisesRegex(OSError, 'after local'): self.configure(limits=self.next_limit())
        current = self.current(); roots = self.roots()
        self.configure(limits={'max_unit_retries': current['limits']['max_unit_retries']})
        self.assertEqual(self.current(), current); self.assertEqual(self.roots(), roots)
        self.assertEqual(list((self.home / 'pending-setup').glob('*.json')), [])

    def test_stale_source_fork_cannot_publish_over_advanced_head(self):
        self.configure(limits=self.next_limit()); first = self.current()
        self.configure(limits=self.next_limit()); roots = self.roots(); before = self.durable_bytes()
        self.policy_path.write_bytes(self.original_raw)
        with self.assertRaises(EvidenceError):
            self.configure(limits={'max_unit_retries': self.original['limits']['max_unit_retries'] + 2})
        self.assertEqual(self.durable_bytes(), before); self.assertEqual(self.roots(), roots)
        self.assertEqual(self.policy_path.read_bytes(), self.original_raw)
        self.assertNotEqual(first, self.head()['policy'])

    def test_stale_policy_ordinary_generation_and_cold_coordinator_cannot_mutate(self):
        self.configure(limits=self.next_limit()); before = self.durable_bytes()
        with self.assertRaises(EvidenceError): self.manager(self.original).begin_generation('stale', 'unit', 1, 1)
        with self.assertRaises(EvidenceError): self.manager(home=self.base / 'cold-home').initialize_generation_authority()
        self.assertEqual(self.durable_bytes(), before)

    def test_unpublished_lineage_cannot_mutate_through_ordinary_generation(self):
        pending = append_policy_transition(self.original_raw, {**effective(self.original), 'limits': {**self.original['limits'], **self.next_limit()}})
        before = self.durable_bytes()
        with self.assertRaises(EvidenceError): self.manager(pending).begin_generation('uncommitted', 'unit', 1, 1)
        self.assertEqual(self.durable_bytes(), before)

    def test_first_lineage_publication_cannot_create_absent_or_take_foreign_authority(self):
        pending = append_policy_transition(self.original_raw, {**effective(self.original), 'limits': {**self.original['limits'], **self.next_limit()}})
        before = self.durable_bytes()
        with self.assertRaises(EvidenceError): self.manager(pending, home=self.base / 'foreign').initialize_generation_authority()
        self.assertEqual(self.durable_bytes(), before)
        fresh_transport = FaultTransport(self.base / 'unclaimed-store')
        with self.assertRaises(EvidenceError): Manager(fresh_transport, self.base / 'unclaimed-home', pending).initialize_generation_authority()
        self.assertEqual(list(fresh_transport.root.rglob('*.json')), [])

    def test_empty_authority_does_not_accept_skipping_multiple_transitions(self):
        first = append_policy_transition(self.original_raw, {**effective(self.original), 'limits': {**self.original['limits'], **self.next_limit()}})
        second_effective = effective(first); second_effective['limits']['max_unit_retries'] += 1
        second = append_policy_transition(setup_bytes(first), second_effective)
        before = self.durable_bytes()
        with self.assertRaises(EvidenceError): self.manager(second).initialize_generation_authority()
        self.assertEqual(self.durable_bytes(), before)

    def test_history_bearing_nonlimits_reconfiguration_cannot_drop_lineage(self):
        self.configure(limits=self.next_limit()); before_policy = self.policy_path.read_bytes(); before = self.durable_bytes()
        for changes in ({'retention_days': 14}, {'provider': 'local', 'destination': str(self.store)},
                        {'destination': str(self.base / 'other-store')}):
            with self.subTest(changes=changes):
                with self.assertRaises((EvidenceError, setup.SetupError)): self.configure(**changes)
                self.assertEqual(self.policy_path.read_bytes(), before_policy); self.assertEqual(self.durable_bytes(), before)

    def test_stale_local_policy_mutation_during_probe_cannot_publish_or_overwrite(self):
        before = self.durable_bytes(); changed_raw = self.original_raw + b'\n'
        def mutate_during_probe(config, project):
            self.policy_path.write_bytes(changed_raw)
            return self.probe(config, project)
        with self.assertRaisesRegex(setup.SetupError, 'policy changed'):
            self.configure(limits=self.next_limit(), probe=mutate_during_probe)
        self.assertEqual(self.durable_bytes(), before)
        self.assertEqual(self.policy_path.read_bytes(), changed_raw)
        self.assertEqual(self.initialized, [])

    def test_stale_local_policy_mutation_after_publication_is_preserved_without_exposure(self):
        changed_raw = self.original_raw + b'\n'
        def publish_then_source_change(config, policy, project, **kwargs):
            result = self.initialize(config, policy, project, **kwargs)
            self.policy_path.write_bytes(changed_raw)
            return result
        with patch.object(setup, '_initialize_authority', publish_then_source_change):
            with self.assertRaisesRegex(setup.SetupError, 'policy changed'):
                self.configure(limits=self.next_limit())
        self.assertEqual(self.policy_path.read_bytes(), changed_raw)
        self.assertEqual(len(self.roots()), 1)
        self.assertNotEqual(self.head()['policy'], json.loads(changed_raw))
        self.assertTrue(list((self.home / 'pending-setup').glob('*.json')))

    def test_reformatted_lineage_source_is_not_silently_normalized_by_setup(self):
        self.configure(limits=self.next_limit()); before = self.durable_bytes()
        raw = (json.dumps(self.current(), indent=4) + '\n').encode()
        self.policy_path.write_bytes(raw); probe_count = len(self.probes)
        with self.assertRaises(EvidenceError): self.configure(limits=self.next_limit())
        self.assertEqual(self.policy_path.read_bytes(), raw); self.assertEqual(self.durable_bytes(), before)
        self.assertEqual(len(self.probes), probe_count)

    def test_legacy_retention_only_reconfiguration_keeps_plain_v1_behavior(self):
        self.configure(retention_days=14)
        self.assertEqual(self.current()['retention']['local_days'], 14)
        self.assertNotIn('policy_lineage', self.current())
        self.assertEqual(self.current()['project_id'], self.original['project_id'])

    def test_manual_format_of_original_v1_is_anchored_without_changing_its_bytes(self):
        raw = (json.dumps(self.original, indent=4, sort_keys=False) + '\n\n').encode()
        self.policy_path.write_bytes(raw); self.configure(limits=self.next_limit())
        self.assertEqual(self.current()['policy_lineage']['base']['raw_utf8'].encode(), raw)
        self.assertEqual(self.current()['policy_lineage']['base']['raw_sha256'], hashlib.sha256(raw).hexdigest())


class QuarantinedAccountingLineageTests(unittest.TestCase):
    """Existing isolated failed-ledger fixture; no child producer or provider launch."""
    def setUp(self):
        import test_evidence_quarantine_manager as fixtures
        self.fixture = fixtures.QuarantineManagerTests(methodName='runTest')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.original_policy = deepcopy(self.fixture.manager.policy)
        self.original_descriptor = self.fixture.apply()['descriptor']
        self.original_descriptor_raw = setup_bytes(self.original_descriptor)
        with self.fixture.ledger() as ledger:
            self.original_rows = {table: [tuple(row) for row in ledger.connection.execute('SELECT * FROM ' + table + ' ORDER BY 1')]
                                  for table in ('runs', 'reservations', 'uncertain_generation', 'producer_sessions', 'outputs', 'observations')}
            self.original_totals = ledger.snapshot()['totals']

    def transition(self, previous):
        candidate = effective(previous); candidate['limits']['max_unit_retries'] += 1
        current = append_policy_transition(setup_bytes(previous), candidate)
        manager = Manager(self.fixture.fixture.transport, self.fixture.fixture.home, current)
        manager.initialize_generation_authority()
        self.fixture.manager = manager
        return current

    def assert_original_rows_preserved(self, *, allow_new=False):
        manager = self.fixture.manager
        publication = manager._publication_view(manager._catalog())
        with self.fixture.ledger() as ledger:
            ledger._publication_manager = (self.fixture.manager, None, None)
            for table, before in self.original_rows.items():
                after = [tuple(row) for row in ledger.connection.execute('SELECT * FROM ' + table + ' ORDER BY 1')]
                if allow_new:
                    for old in before: self.assertIn(old, after, table)
                else: self.assertEqual(after, before, table)
            # Snapshot validation is portable; it grants no fresh native
            # publication capability on a host without the bounded alarm path.
            descriptors = ledger.quarantines(_publication=publication)
            self.assertEqual(setup_bytes(descriptors[0]), self.original_descriptor_raw)
            self.assertFalse(ledger.snapshot()['accounting_complete'])
            self.assertTrue(ledger.snapshot()['totals_are_lower_bounds'])
            return ledger.generation_readiness()

    def test_two_policy_transitions_keep_original_failed_session_and_full_hold_unchanged(self):
        first = self.transition(self.original_policy); second = self.transition(first)
        self.assertEqual(resolve_historical_policy(second, digest(first)), first)
        readiness = self.assert_original_rows_preserved()
        self.assertEqual(os.name == 'posix', readiness['ready'], readiness)
        if os.name != 'posix':
            self.assertIn('requires POSIX main-thread', readiness['problem'])
        with self.fixture.ledger() as ledger:
            for key in ('project_generated_bytes', 'project_generated_files', 'pending_generated_bytes', 'pending_generated_files'):
                self.assertEqual(ledger.snapshot()['totals'][key], self.original_totals[key], key)
            with self.assertRaises(EvidenceError): ledger.complete_run('old-run')
            with self.assertRaises(EvidenceError): ledger.cancel(self.fixture.reservation)
            with self.assertRaises(EvidenceError): ledger.settle(self.fixture.reservation, 24, 1)

    def test_fresh_registered_known_output_and_v2_receipt_preserve_history_after_transition(self):
        self.transition(self.original_policy)
        manager = self.fixture.manager
        if os.name == 'posix':
            intent = manager.begin_generation('fresh-lineage-run', 'fresh-unit', 4096, 8)
            output = self.fixture.fixture.base / 'known-lineage-output'; output.mkdir()
            with self.fixture.ledger(publication=True) as ledger:
                reservation = ledger.reserve('fresh-lineage-run', 'fresh-unit', 4096, 8, local_bytes=4096)
                output_id = ledger.register_output('fresh-lineage-run', 'fresh-unit', output)
                (output / 'known.txt').write_bytes(b'new')
                settlement = ledger.settle(reservation, 3, 1, local_bytes=3)
                self.assertFalse(settlement['incomplete'])
                ledger.acknowledge_output(output_id)
                self.assertEqual(ledger.reconcile_output(output_id)['new_bytes'], 0)
                ledger.complete_run('fresh-lineage-run')
            self.assertTrue(manager.finish_generation(intent, reservation)['settled'])
            self.assertTrue(self.assert_original_rows_preserved(allow_new=True)['ready'])
        else:
            with self.assertRaisesRegex(EvidenceError, 'requires POSIX main-thread'):
                manager.begin_generation('fresh-lineage-run', 'fresh-unit', 4096, 8)
            with self.fixture.ledger(publication=True) as ledger:
                with self.assertRaisesRegex(EvidenceError, 'requires POSIX main-thread'):
                    ledger.reserve('fresh-lineage-run', 'fresh-unit', 4096, 8, local_bytes=4096)
            readiness = self.assert_original_rows_preserved()
            self.assertFalse(readiness['ready'])
            self.assertIn('requires POSIX main-thread', readiness['problem'])
        code, receipt, policy_path = self.fixture.receipt()
        self.assertEqual(code, 0); self.assertEqual(receipt['version'], 2)
        selected = ['fresh-lineage-run'] if os.name == 'posix' else []
        self.assertEqual(receipt['selected_scope'], {'run_ids': selected, 'complete': True})
        self.assertFalse(receipt['accounting_complete']); self.assertFalse(receipt['history_complete'])
        self.assertTrue(receipt['totals_are_lower_bounds']); self.assertTrue(receipt['generation_ready'])
        self.assertEqual(setup_bytes(receipt['quarantines'][0]), self.original_descriptor_raw)
        self.assertEqual(receipt['runs']['old-run']['status'], 'incomplete')
        self.assertEqual(receipt['policy_sha256'], hashlib.sha256(policy_path.read_bytes()).hexdigest())
        self.assertNotEqual(receipt['policy_sha256'], self.original_descriptor['policy_sha256'])
        from test_sdd_check import sdd
        project = self.fixture.fixture.base / 'checker-scope'; (project / 'forge').mkdir(parents=True)
        (project / 'forge/evidence-policy.json').write_bytes(policy_path.read_bytes())
        manifest = {'evidence_storage': {'policy_path': 'forge/evidence-policy.json'}, 'evidence_accounting': receipt}
        checker = sdd.Checker(project, manifest)
        if os.name == 'posix':
            checker.evidence_accounting(run_id='fresh-lineage-run', unit_id='fresh-unit')
        else:
            self.assertNotIn('fresh-lineage-run', receipt['runs'])
            with self.assertRaisesRegex(ValueError, 'outside the complete current accounting scope'):
                checker.evidence_accounting(run_id='fresh-lineage-run', unit_id='fresh-unit')
