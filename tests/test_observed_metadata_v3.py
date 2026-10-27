"""Opt-in FULL-graph helper metadata; isolated ledger/native-return fixtures only."""
import copy
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_observed_writers as fixtures

observed, native, runtime = fixtures.observed, fixtures.native, fixtures.runtime
EvidenceError = fixtures.EvidenceError
_RealSampler = observed._NativeSampler


class ManualSampler(_RealSampler):
    """Run the actual collector cycle synchronously, without a host/native thread."""
    def __init__(self, **kwargs):
        self.fake_thread = Mock()
        self.fake_thread.is_alive.return_value = True
        with patch.object(threading, 'Thread', return_value=self.fake_thread):
            super().__init__(**kwargs)

    def _wait(self, predicate, timeout):
        self._cycle()
        return super()._wait(predicate, timeout)

    def stop(self, timeout=3):
        if not self._stop:
            self._cycle()
        self._stop = self._finished = True
        self.fake_thread.is_alive.return_value = False
        return self._sequence


@unittest.skipUnless(fixtures.os.name == 'posix', 'Isolated POSIX working roots and SQLite integration')
class MetadataV3Tests(unittest.TestCase):
    identity = fixtures.RegistryTests.identity
    native = fixtures.RegistryTests.native
    save = fixtures.RegistryTests.save
    registered = fixtures.RegistryTests.registered
    record_now = fixtures.RegistryTests.record_now

    def setUp(self):
        fixtures.RegistryTests.setUp(self)
        self.now = 100.0
        self.extra = [patch.object(observed, '_NativeSampler', ManualSampler),
                      patch.object(observed.time, 'monotonic_ns', side_effect=self.nanoseconds),
                      patch.object(observed.time, 'monotonic', side_effect=lambda: self.now)]
        for item in self.extra: item.start()

    def cleanup(self):
        try: fixtures.RegistryTests.cleanup(self)
        finally:
            for item in reversed(getattr(self, 'extra', [])): item.stop()

    def nanoseconds(self):
        self.stamp += 1
        return self.stamp

    def arm(self):
        self.observer = observed.Observer(self.ledger, self.attempt, 99, self.working, helper_metadata_version=3)
        return self.observer

    def helper(self):
        self.nodes[102] = fixtures.snapshot(102, 1100, 1000, birth=103, version=20, parent_version=10, ppid=101, pgid=555)

    def fail_path(self, pid):
        if pid != 102: return '/fixture/node' if pid == 99 else '/fixture/python'
        query = dict(version=1, api='libproc.proc_pidpath', stage='query', pid=pid, returned_size=0,
                     errno=fixtures.errno.ESRCH, buffer_size=4096, outcome='unavailable', monotonic_ns=str(self.nanoseconds()))
        raise observed._PathQueryError('actual mocked path ESRCH', query)

    def type_a(self):
        observer = self.registered(); self.helper(); observer.observe(102)
        with patch.object(observed, 'executable_path', side_effect=self.fail_path):
            updated = copy.deepcopy(self.nodes[102]); updated['pgid'] = 556; self.nodes[102] = updated
            observer.observe(102)
        return observer

    def type_b(self):
        observer = self.registered(); self.helper()
        old, new = self.nodes[102]['executable_uuid'], '45454545-4545-4545-8545-454545454545'
        def path(pid):
            if pid == 102:
                self.nodes[102]['executable_uuid'] = new
                return '/fixture/helper'
            return '/fixture/node' if pid == 99 else '/fixture/python'
        with patch.object(observed, 'executable_path', side_effect=path):
            self.assertFalse(observer.observe(102))
        diagnostic = observer.value['native_sampler']['helper_diagnostics'][0]
        self.assertEqual(diagnostic['raw']['executable_uuid'], old)
        return observer

    def advance_retry(self, observer):
        budgets = observer._sampler._metadata_budgets
        self.now = max(self.now, min(state['next'] for state in budgets.values())) + .00001
        observer.observe(102)

    def test_explicit_mode_ack_and_default_two_shape(self):
        observer = self.arm(); item = observer.allocate('mode3 root', 4096); self.created.append(Path(item['path']))
        reply = observer.register_root(101, self.browser['identity'], '/fixture/python', [item['ref']])
        self.assertEqual(set(reply), {'root', 'sequence', 'durable', 'metadata_version'})
        self.assertEqual(reply['metadata_version'], 3)
        self.assertEqual(observer.value['version'], 1); self.assertEqual(self.record_now()['version'], 2)
        self.assertEqual(observer.value['capability'], observed.CAPABILITY)
        self.assertEqual(observer.value['native_sampler']['version'], 3)

    def test_invalid_mode_rejected_before_any_native_or_ledger_operation(self):
        for version in (None, True, 1, 4, '3'):
            with patch.object(observed.native, 'read_snapshot', side_effect=AssertionError('must validate first')):
                with self.assertRaises(EvidenceError): observed.Observer(None, 'attempt', 99, 'hold', helper_metadata_version=version)

    def test_type_a_preserves_full_graph_and_closes_only_after_numeric_absence(self):
        observer = self.type_a(); session = self.record_now()['observation_session']
        diagnostic = session['native_sampler']['helper_diagnostics'][0]
        self.assertEqual(diagnostic['version'], 3)
        self.assertEqual(diagnostic['subtype'], 'known_full_epoch_state_gap')
        self.assertEqual(diagnostic['capture'], {'version': 1, 'failed_path': 'p1'})
        self.assertIsNotNone(diagnostic['qualification'])
        self.assertEqual(len(session['observations']), 2)
        self.assertEqual(session['writers']['1100']['authority'], observed.AUTHORITY)
        self.assertEqual(session['observations'][1]['snapshot']['pgid'], 555)
        self.assertEqual(diagnostic['raw']['pgid'], 556)
        with self.assertRaises(EvidenceError): observer._cleanup_checks(1, require_empty=False)
        self.nodes.pop(102); self.nodes.pop(101); observer.prepare_cleanup(3); observer.close(3)
        self.assertEqual(observed.disposition_problems(self.record_now(), ledger=self.ledger), [])

    def test_type_b_waits_for_first_independent_full_and_never_promotes_raw(self):
        observer = self.type_b(); prior = copy.deepcopy(observer.value['observations'])
        diagnostic = observer.value['native_sampler']['helper_diagnostics'][0]
        self.assertEqual(diagnostic['version'], 3); self.assertEqual(diagnostic['subtype'], 'helper_initial_image_gap')
        self.assertIsNone(diagnostic['qualification']); self.assertNotIn('1100', observer.value['writers'])
        self.assertEqual(diagnostic['capture']['p2'], {'outcome': 'not_called'})
        self.advance_retry(observer)
        session = self.record_now()['observation_session']; diagnostic = session['native_sampler']['helper_diagnostics'][0]
        self.assertIsNotNone(diagnostic['qualification']); self.assertEqual(session['observations'][:len(prior)], prior)
        full = session['observations'][diagnostic['qualification']['after_observation_sequence'] - 1]
        self.assertEqual(observed.semantic(full['snapshot']), observed.semantic(diagnostic['followup']['snapshot']))
        self.assertNotEqual(full['snapshot']['executable_uuid'], diagnostic['raw']['executable_uuid'])
        self.assertEqual(session['writers']['1100']['lineage_observation_sequences'], [1, full['sequence']])

    def test_type_b_missing_full_parent_never_qualifies_or_grants_membership(self):
        observer = self.registered(); self.helper(); self.nodes[102]['original_parent_idversion'] = 999
        def path(pid):
            if pid == 102: self.nodes[102]['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
            return '/fixture/node' if pid == 99 else '/fixture/python'
        with patch.object(observed, 'executable_path', side_effect=path): observer.observe(102)
        self.advance_retry(observer)
        self.assertNotIn('1100', observer.value['writers'])
        self.assertIsNone(observer.value['native_sampler']['helper_diagnostics'][0]['qualification'])
        self.assertTrue(observer.value['pending'])

    def test_retry_budget_dedup_exhaustion_and_clock_deadline(self):
        observer = self.registered(); self.helper()
        with patch.object(observed, 'executable_path', side_effect=self.fail_path):
            observer.observe(102)
            for _ in range(4): self.advance_retry(observer)
            changes = self.ledger.connection.total_changes
            sequence = observer.value['native_sampler']['durable_sequence']
            for _ in range(20): observer.observe(102)
        self.assertEqual(self.ledger.connection.total_changes, changes)
        self.assertEqual(observer.value['native_sampler']['durable_sequence'], sequence)
        self.assertEqual(len(observer.value['native_sampler']['helper_diagnostics']), 1)
        self.assertEqual({item['attempts'] for item in observer._sampler._metadata_budgets.values()}, {5})
        self.assertTrue(observer.value['pending'])

    def test_path_retry_recovers_unchanged_native_semantics_and_idle_full_no_writes(self):
        observer = self.registered(); self.helper()
        with patch.object(observed, 'executable_path', side_effect=self.fail_path): observer.observe(102)
        self.advance_retry(observer)
        self.assertIn('1100', observer.value['writers']); self.assertFalse(observer.value['pending'])
        changes = self.ledger.connection.total_changes
        for _ in range(4100): observer._sampler._collect(102)
        observer._drain_native()
        self.assertEqual(self.ledger.connection.total_changes, changes)

    def test_retry_generic_failure_is_deduplicated_but_never_cleared_by_later_full(self):
        observer = self.type_b()
        with patch.object(observed, 'executable_path', side_effect=EvidenceError('unknown native path condition')):
            self.advance_retry(observer)
            changes = self.ledger.connection.total_changes
            self.advance_retry(observer)
            self.assertEqual(self.ledger.connection.total_changes, changes)
        self.advance_retry(observer)
        self.assertIn('1100', observer.value['writers'])
        self.assertEqual(len(observer.value['native_sampler']['unresolved']), 1)
        self.nodes.pop(102); self.nodes.pop(101)
        with self.assertRaises(EvidenceError): observer.prepare_cleanup(3)

    def test_new_raw_hash_schema_removal_downgrade_and_all_terminal_consumers(self):
        observer = self.type_a(); original = self.record_now()
        for variant in ('raw', 'capture', 'binding', 'version', 'qualification'):
            value = copy.deepcopy(original); sampler = value['observation_session']['native_sampler']; diagnostic = sampler['helper_diagnostics'][0]
            if variant == 'raw': diagnostic['raw']['pgid'] += 1
            elif variant == 'capture': diagnostic['capture']['failed_path'] = 'p2'
            elif variant == 'binding': sampler['helper_diagnostic_bindings'].clear()
            elif variant == 'version': sampler['version'] = 2
            else: diagnostic['qualification']['before_observation_sequence'] = 1
            value['status'] = 'terminal'; self.save(value)
            with self.subTest(variant=variant):
                with self.assertRaises(EvidenceError): self.record_now()
                self.assertTrue(fixtures.producer.recover_producers(self.ledger, dry_run=True)['incomplete'])
                with self.assertRaises(EvidenceError): fixtures.quarantine.original_state(self.ledger, self.attempt)
        self.save(original)

    def test_source_policy_change_loss_and_closed_digest_do_not_complete(self):
        observer = self.type_a(); observer._helper_metadata_version = 2
        with self.assertRaises(EvidenceError): observer._active()
        observer._helper_metadata_version = 3
        observer.fail('lost acknowledgement', lost=True)
        self.assertTrue(self.record_now()['observation_session']['lost_history'])
        self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))

    def test_default_two_retains_legacy_ack_metadata_shape_and_blocking_meaning(self):
        self.observer = observer = observed.Observer(self.ledger, self.attempt, 99, self.working)
        item = observer.allocate('default root', 4096); self.created.append(Path(item['path']))
        self.assertEqual(set(observer.register_root(101, self.browser['identity'], '/fixture/python', [item['ref']])), {'root', 'sequence', 'durable'})
        self.helper(); observer.observe(102)
        with patch.object(observed, 'executable_path', side_effect=self.fail_path):
            self.nodes[102]['pgid'] = 556; observer.observe(102)
        sampler = observer.value['native_sampler']; diagnostic = sampler['helper_diagnostics'][0]
        self.assertEqual(sampler['version'], 2); self.assertEqual(diagnostic['version'], 1)
        self.assertNotIn('capture', diagnostic); self.assertIsNone(diagnostic['qualification'])
        self.assertTrue(observer.value['pending'])
        observer.fail('historical sampler2 failure', lost=True)
        before = self.ledger.connection.execute('SELECT record FROM producer_sessions WHERE id=?', (self.attempt,)).fetchone()[0]
        with self.assertRaisesRegex(EvidenceError, 'prior closure'):
            observed.Observer(self.ledger, self.attempt, 99, self.working, helper_metadata_version=3)
        self.assertEqual(self.ledger.connection.execute('SELECT record FROM producer_sessions WHERE id=?', (self.attempt,)).fetchone()[0], before)

    def test_default_two_initial_image_gap_remains_generic_despite_later_full(self):
        self.observer = observer = observed.Observer(self.ledger, self.attempt, 99, self.working)
        item = observer.allocate('legacy image root', 4096); self.created.append(Path(item['path']))
        observer.register_root(101, self.browser['identity'], '/fixture/python', [item['ref']]); self.helper()
        def path(pid):
            if pid == 102: self.nodes[102]['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
            return '/fixture/node' if pid == 99 else '/fixture/python'
        with patch.object(observed, 'executable_path', side_effect=path): observer.observe(102)
        self.assertIn('1100', observer.value['writers'])
        self.assertEqual(observer.value['native_sampler']['version'], 2)
        self.assertEqual(len(observer.value['native_sampler']['unresolved']), 1)
        self.assertEqual(observer.value['native_sampler']['helper_diagnostics'], [])

    def test_retry_deadline_and_signature_capacity_never_waive_pending(self):
        observer = self.type_b()
        self.now += observed.METADATA_DEADLINE + .001
        observer.observe(102)
        self.assertNotIn('1100', observer.value['writers']); self.assertTrue(observer.value['pending'])
        with patch.object(observed, 'MAX_PENDING', len(observer._sampler._metadata_budgets)):
            changed = copy.deepcopy(self.nodes[102]); changed['pgid'] += 1
            with self.assertRaisesRegex(EvidenceError, 'signature bound'):
                observer._sampler._plan_metadata_retry(102, changed)

    def test_qualified_new_raw_hash_is_bound_into_closed_receipt(self):
        observer = self.type_a(); self.nodes.pop(102); self.nodes.pop(101)
        observer.prepare_cleanup(3); observer.close(3)
        value = self.record_now(); value['observation_session']['closure']['metadata_capture_sha256'] = '0' * 64; self.save(value)
        with self.assertRaisesRegex(EvidenceError, 'capture integrity'): self.record_now()

    def test_private_event_map_survives_deferred_ancestry_and_cannot_use_observation_numbers(self):
        observer = self.registered()
        observer._sampler._emit('absent', 999)  # A real private fixture event, not a fabricated clock/order.
        self.nodes[103] = fixtures.snapshot(103, 1200, 1100, birth=105, parent_version=10, ppid=1, pgid=666)
        self.assertFalse(observer.observe(103))
        prefix = copy.deepcopy(observer.value['observations'])
        child_sequence = prefix[-1]['sequence']; binding = copy.deepcopy(observer.value['native_sampler']['full_capture_sequences'][str(child_sequence)])
        self.assertNotEqual(binding['capture_sequence'], child_sequence)
        self.nodes[102] = fixtures.snapshot(102, 1100, 1000, birth=103, parent_version=10, ppid=1, pgid=555)
        self.assertTrue(observer.observe(102))
        session = self.record_now()['observation_session']; observed.validate_session(session)
        self.assertEqual(session['observations'][:len(prefix)], prefix)
        self.assertEqual(session['native_sampler']['full_capture_sequences'][str(child_sequence)], binding)
        self.assertEqual(session['writers']['1200']['observation_sequence'], child_sequence)
        self.assertEqual(session['writers']['1200']['lineage_observation_sequences'], [1, 3, 2])

    def test_forced_root_fresh_full_reprojects_without_invalidating_metadata_references(self):
        observer = self.type_a(); prefix = copy.deepcopy(observer.value['observations'])
        diagnostic = copy.deepcopy(observer.value['native_sampler']['helper_diagnostics'][0])
        binding = copy.deepcopy(observer.value['native_sampler']['helper_diagnostic_bindings'])
        for _ in range(2):
            image = observer.request(dict(command='observe_pid', pid=101, include_image=True))['image']
            session = self.record_now()['observation_session']; observed.validate_registry(self.record_now())
            entry = session['native_sampler']['full_capture_sequences'][str(image['observation_sequence'])]
            self.assertEqual(entry['capture_sequence'], image['capture_sequence'])
            self.assertEqual(entry, observed._full_capture_binding(session['observations'][image['observation_sequence'] - 1], image['capture_sequence']))
            self.assertEqual(session['observations'][:len(prefix)], prefix)
            self.assertEqual(session['native_sampler']['helper_diagnostics'][0], diagnostic)
            self.assertEqual(session['native_sampler']['helper_diagnostic_bindings'], binding)
            self.assertEqual(session['writers']['1100']['lineage_observation_sequences'][0], image['observation_sequence'])

    def test_full_binding_transaction_failure_rolls_back_private_durable_watermark(self):
        observer = self.registered(); self.helper()
        original = self.record_now(); sequence = observer.value['native_sampler']['durable_sequence']
        with patch.object(observed, '_full_capture_binding', return_value=dict(capture_sequence=999, full_sha256='0' * 64)):
            with self.assertRaisesRegex(EvidenceError, 'lost unflushed history'): observer.observe(102)
        self.assertEqual(self.record_now(), original)
        self.assertEqual(observer.value['native_sampler']['durable_sequence'], sequence)
        self.assertTrue(observer._drain_lost)
        with self.assertRaises(EvidenceError): observer.prepare_cleanup(3)

    def test_barrier_and_closure_hash_complete_map_and_current_diagnostic_bindings(self):
        observer = self.type_a(); self.nodes.pop(102); self.nodes.pop(101)
        observer.prepare_cleanup(3)
        original = self.record_now(); session = original['observation_session']
        self.assertEqual(session['cleanup_barrier']['metadata_capture_sha256'], observed._metadata_capture_digest(session))
        broken = copy.deepcopy(original); broken['observation_session']['cleanup_barrier']['metadata_capture_sha256'] = '0' * 64
        self.save(broken)
        with self.assertRaisesRegex(EvidenceError, 'pre-cleanup FULL'): self.record_now()
        self.save(original); observer.close(3)
        closed = self.record_now(); final = closed['observation_session']
        self.assertEqual(final['closure']['metadata_capture_sha256'], observed._metadata_capture_digest(final))
        self.assertNotIn('helper_diagnostics_sha256', final['closure'])
        for variant in ('map', 'binding', 'closure', 'barrier'):
            value = copy.deepcopy(closed); current = value['observation_session']
            if variant == 'map': next(iter(current['native_sampler']['full_capture_sequences'].values()))['full_sha256'] = '0' * 64
            elif variant == 'binding': next(iter(current['native_sampler']['helper_diagnostic_bindings'].values()))['qualification_sha256'] = '0' * 64
            else: current['closure' if variant == 'closure' else 'cleanup_barrier']['metadata_capture_sha256'] = '0' * 64
            self.save(value)
            with self.subTest(variant=variant), self.assertRaises(EvidenceError): self.record_now()
            self.assertTrue(fixtures.producer.recover_producers(self.ledger, dry_run=True)['incomplete'])
            with self.assertRaises(EvidenceError): fixtures.quarantine.original_state(self.ledger, self.attempt)
        # Rebound per-FULL and qualifier hashes are internally coherent; the
        # original whole-map barrier and final closure must still catch change.
        rebound = copy.deepcopy(closed); current = rebound['observation_session']; sampler = current['native_sampler']
        sequence, entry = next(iter(sampler['full_capture_sequences'].items()))
        self.assertGreater(entry['capture_sequence'], 1)
        sampler['full_capture_sequences'][sequence] = observed._full_capture_binding(current['observations'][int(sequence) - 1], 1)
        item = sampler['helper_diagnostics'][0]
        item['qualification']['full_capture_reference'] = copy.deepcopy(sampler['full_capture_sequences'][sequence])
        sampler['helper_diagnostic_bindings'][str(item['capture_sequence'])] = observed._helper_binding(item)
        self.assertTrue(observed._valid_full_captures(current))
        self.assertTrue(observed._valid_metadata3_qualification(current, item, item['qualification']))
        self.save(rebound)
        with self.assertRaisesRegex(EvidenceError, 'pre-cleanup FULL'): self.record_now()
        current['cleanup_barrier']['metadata_capture_sha256'] = observed._metadata_capture_digest(current)
        self.save(rebound)
        with self.assertRaisesRegex(EvidenceError, 'closed FULL'): self.record_now()
        self.save(closed)

    def initial_exec(self, *, missing_parent=False):
        observer = self.registered(); self.helper(); phase = [0]
        if missing_parent: self.nodes[102]['original_parent_idversion'] = 999
        def path(pid):
            if pid == 102 and phase[0] == 0:
                self.nodes[102]['idversion'] += 1; phase[0] = 1
            return '/fixture/node' if pid == 99 else '/fixture/python'
        def read(pid, include_zombie=True):
            result = self.native(pid, include_zombie)
            if pid == 102 and phase[0] == 1:
                # Preserve the actual old-UUID after-frame, then present the
                # independent new-image snapshot on the NEXT native capture.
                phase[0] = 2; self.nodes[102]['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
            return result
        with patch.object(observed, 'executable_path', side_effect=path), patch.object(observed.native, 'read_snapshot', side_effect=read):
            observer.observe(102)
        return observer

    def test_real_collector_resolver_atomic_pending_update_and_all_terminal_consumers(self):
        observer = self.initial_exec(); session = observer.value; transition = session['native_sampler']['exec_transitions'][0]
        self.assertEqual(transition['resolution']['version'], 3); self.assertFalse(session['pending'])
        self.assertEqual(transition['before']['executable_uuid'], transition['after']['executable_uuid'])
        self.assertEqual(observer.graphs['1000']._versions['1100'], {self.nodes[102]['idversion']})
        raw = {k: copy.deepcopy(v) for k, v in transition.items() if k != 'resolution'}
        full = copy.deepcopy(session['observations'][transition['resolution']['observation_sequence'] - 1])
        observer.request(dict(command='observe_pid', pid=101, include_image=True))
        self.assertEqual({k: v for k, v in observer.value['native_sampler']['exec_transitions'][0].items() if k != 'resolution'}, raw)
        self.assertEqual(observer.value['observations'][full['sequence'] - 1], full)
        self.nodes.pop(102); self.nodes.pop(101)
        observer.prepare_cleanup(3); observer.close(3)
        record = self.record_now(); observed.validate_registry(record)
        self.assertEqual(observed.disposition_problems(record, ledger=self.ledger), [])
        closed = record['observation_session']; self.assertEqual(closed['closure']['metadata_capture_sha256'], observed._metadata_capture_digest(closed))
        for variant in ('raw', 'resolution', 'ref', 'digest', 'kind', 'removal'):
            value = copy.deepcopy(record); current = value['observation_session']; event = current['native_sampler']['exec_transitions'][0]
            if variant == 'raw': event['after']['pgid'] += 1
            elif variant == 'resolution': event['resolution']['transition_sha256'] = '0' * 64
            elif variant == 'ref': event['resolution']['full_capture_reference']['capture_sequence'] += 1
            elif variant == 'digest': current['closure']['metadata_capture_sha256'] = '0' * 64
            elif variant == 'kind': event['resolution']['kind'] = 'unknown'
            else: current['native_sampler']['exec_transitions'].clear()
            self.save(value)
            with self.subTest(variant=variant), self.assertRaises(EvidenceError): self.record_now()
            self.assertTrue(fixtures.producer.recover_producers(self.ledger, dry_run=True)['incomplete'])
            with self.assertRaises(EvidenceError): fixtures.quarantine.original_state(self.ledger, self.attempt)
        self.save(record)

    def test_generic_failure_and_missing_full_parent_are_not_resolved_or_reopened(self):
        observer = self.initial_exec(missing_parent=True)
        transition = observer.value['native_sampler']['exec_transitions'][0]
        self.assertIsNone(transition['resolution']); self.assertIn('exec:' + str(transition['capture_sequence']), observer.value['pending'])
        observer.fail('preserved prior failed sampler3', lost=True)
        prior = self.record_now(); self.assertIsNone(prior['observation_session']['native_sampler']['exec_transitions'][0]['resolution'])
        with self.assertRaisesRegex(EvidenceError, 'prior closure'):
            observed.Observer(self.ledger, self.attempt, 99, self.working, helper_metadata_version=3)
        self.assertEqual(self.record_now(), prior)

    def test_valid_exec_resolution_never_clears_generic_native_failures(self):
        observer = self.initial_exec(); transition = observer.value['native_sampler']['exec_transitions'][0]
        observer._sampler._emit('pending', 102, snapshot=copy.deepcopy(self.nodes[102]), reason='unknown native/path failure')
        observer._drain_native()
        self.assertEqual(transition['resolution']['version'], 3)
        self.assertEqual(len(observer.value['native_sampler']['unresolved']), 1)
        self.assertIn('pid:102', observer.value['pending'])
        self.nodes.pop(102); self.nodes.pop(101)
        with self.assertRaises(EvidenceError): observer.prepare_cleanup(3)


class MetadataV3ReceiptTests(unittest.TestCase):
    def setUp(self):
        base = fixtures.PortableReceiptTests()
        base.setUp(); self.base = base

    def session(self, kind):
        session = copy.deepcopy(self.base.session); sampler = session['native_sampler']; sampler['version'] = 3
        if kind == 'a':
            raw = self.base.at(session['observations'][2]['snapshot'], 6000); raw['pgid'] = 556
            post = self.base.at(raw, 8000)
            capture = dict(version=1, failed_path='p1')
            query = dict(version=1, api='libproc.proc_pidpath', stage='query', pid=102, returned_size=0,
                         errno=fixtures.errno.ESRCH, buffer_size=4096, outcome='unavailable', monotonic_ns='7000')
            before, after, subtype = 3, None, 'known_full_epoch_state_gap'
        else:
            raw = self.base.at(session['observations'][1]['snapshot'], 2000)
            post = self.base.at(raw, 4000); post['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
            full = self.base.at(post, 5000)
            session['observations'] = [session['observations'][0], dict(sequence=2, snapshot=full, executable='/fixture/helper')]
            session['sequence'] = 2
            session['writers']['1100'].update(observation_sequence=2, lineage_observation_sequences=[1, 2])
            capture = dict(version=1, p1=dict(outcome='success', executable='/fixture/unqualified', monotonic_ns='3000'), p2=dict(outcome='not_called'))
            query = None; before, after, subtype = None, 2, 'helper_initial_image_gap'
        diagnostic = dict(version=3, kind='helper_native_metadata_gap', capture_sequence=4, subtype=subtype,
            pid=102, raw=raw, path_status='unobserved', image_status='nonqualifying', path_query=query,
            followup=dict(outcome='snapshot', snapshot=post, problem=None), capture=capture,
            qualification=dict(version=3, mode=subtype, root='1000', before_observation_sequence=before, after_observation_sequence=after))
        caps = {2: 1, 3: 3} if kind == 'a' else {2: 5}
        sampler['durable_sequence'] = 4 if kind == 'a' else 5
        sampler['full_capture_sequences'] = {str(item['sequence']): observed._full_capture_binding(item, caps[item['sequence']])
            for item in session['observations'][1:]}
        diagnostic['qualification']['full_capture_reference'] = copy.deepcopy(sampler['full_capture_sequences'][str(before or after)])
        sampler['helper_diagnostics'] = [diagnostic]; sampler['helper_diagnostic_bindings'] = {}
        self.rebind(session); observed.validate_session(session)
        return session

    @staticmethod
    def diagnostic(session): return session['native_sampler']['helper_diagnostics'][0]

    def rebind(self, session):
        item = self.diagnostic(session)
        session['native_sampler']['helper_diagnostic_bindings'] = {str(item['capture_sequence']): observed._helper_binding(item)}

    def test_three_explicit_and_two_rejects_new_type_without_reinterpretation(self):
        for kind in ('a', 'b'):
            session = self.session(kind); session['native_sampler']['version'] = 2
            with self.subTest(kind=kind), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_new_binding_requires_exact_json_integer_version_keys_and_sha_shapes(self):
        for kind in ('a', 'b'):
            for variant in ('bool', 'float', 'zero', 'two', 'string', 'missing', 'extra', 'raw_type',
                            'raw_short', 'raw_upper', 'qualification_type', 'qualification_short', 'qualification_upper'):
                session = self.session(kind); item = self.diagnostic(session)
                binding = session['native_sampler']['helper_diagnostic_bindings'][str(item['capture_sequence'])]
                if variant in ('bool', 'float', 'zero', 'two', 'string'):
                    binding['version'] = {'bool': True, 'float': 1.0, 'zero': 0, 'two': 2, 'string': '1'}[variant]
                elif variant == 'missing': binding.pop('version')
                elif variant == 'extra': binding['unknown'] = 1
                elif variant == 'raw_type': binding['raw_sha256'] = 1
                elif variant == 'raw_short': binding['raw_sha256'] = '0' * 63
                elif variant == 'raw_upper': binding['raw_sha256'] = 'A' * 64
                elif variant == 'qualification_type': binding['qualification_sha256'] = None
                elif variant == 'qualification_short': binding['qualification_sha256'] = '0' * 65
                else: binding['qualification_sha256'] = 'A' * 64
                with self.subTest(kind=kind, variant=variant), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_selected_full_reference_is_exact_positive_integer_with_no_scalar_coercion(self):
        for kind in ('a', 'b'):
            for value in (True, False, 3.0 if kind == 'a' else 2.0, '3' if kind == 'a' else '2', 0, -1, None):
                session = self.session(kind); item = self.diagnostic(session)
                item['qualification']['before_observation_sequence' if kind == 'a' else 'after_observation_sequence'] = value
                self.rebind(session)  # Reach numeric semantics instead of failing a stale digest.
                with self.subTest(kind=kind, value=value, value_type=type(value).__name__), self.assertRaises(EvidenceError):
                    observed.validate_session(session)
            for nonselected in (False, 0, 0.0):
                session = self.session(kind); item = self.diagnostic(session)
                item['qualification']['after_observation_sequence' if kind == 'a' else 'before_observation_sequence'] = nonselected
                self.rebind(session)
                with self.subTest(kind=kind, nonselected=nonselected), self.assertRaises(EvidenceError): observed.validate_session(session)
            for nested_kind in ('bool', 'matching_float'):
                session = self.session(kind); item = self.diagnostic(session)
                reference = item['qualification']['full_capture_reference']
                reference['capture_sequence'] = True if nested_kind == 'bool' else float(reference['capture_sequence'])
                self.rebind(session)
                with self.subTest(kind=kind, nested=nested_kind), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_frozen_pre_three_reader_rejects_new_sampler_header(self):
        # The prior reader's explicit integer version gate, preserved as a
        # compatibility fixture; it has no sampler3 interpretation.
        def frozen_version_gate(value):
            return type(value.get('version')) is int and value['version'] in (1, 2)
        self.assertTrue(frozen_version_gate(self.base.session['native_sampler']))
        for kind in ('a', 'b'): self.assertFalse(frozen_version_gate(self.session(kind)['native_sampler']))

    def test_a_exact_alive_core_query_and_clock_inverse_table_with_rebound_hash(self):
        original = self.session('a')
        for variant in ('birth', 'uid', 'boot', 'parent', 'parent_epoch', 'epoch', 'uuid', 'query', 'raw_zombie',
                        'post_state', 'post_missing', 'permission', 'unknown', 'stage', 'position', 'query_time', 'post_time'):
            session = copy.deepcopy(original); item = self.diagnostic(session); raw, post = item['raw'], item['followup']['snapshot']
            if variant == 'birth': raw['identity']['created']['microseconds'] += 1
            elif variant == 'uid': raw['uid'] += 1
            elif variant == 'boot': raw['boot_uuid'] = '56565656-5656-4565-8565-565656565656'
            elif variant == 'parent': raw['original_parent_unique_id'] = '9999'
            elif variant == 'parent_epoch': raw['original_parent_idversion'] += 1
            elif variant == 'epoch': raw['idversion'] += 1
            elif variant == 'uuid': raw['executable_uuid'] = '56565656-5656-4565-8565-565656565656'
            elif variant == 'query': raw['query']['native_status'] = 3
            elif variant == 'raw_zombie': raw['status'] = 'zombie'; raw['query']['native_status'] = 5
            elif variant == 'post_state': post['pgid'] += 1
            elif variant == 'post_missing': item['followup'] = dict(outcome='numeric_esrch', snapshot=None, problem=None)
            elif variant == 'permission': item['path_query']['errno'] = fixtures.errno.EACCES
            elif variant == 'unknown': item['path_query']['errno'] = 0
            elif variant == 'stage': item['path_query']['stage'] = 'decode'
            elif variant == 'position': item['capture']['failed_path'] = 'unknown'
            elif variant == 'query_time': item['path_query']['monotonic_ns'] = raw['observed']['monotonic_ns']
            else: post['observed'] = copy.deepcopy(raw['observed'])
            self.rebind(session)
            with self.subTest(variant=variant), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_a_latest_preceding_full_never_ancient_matching_epoch(self):
        session = self.session('a'); newer = self.base.at(session['observations'][2]['snapshot'], 5500)
        newer['idversion'] += 1; newer['executable_uuid'] = '56565656-5656-4565-8565-565656565656'
        session['observations'].append(dict(sequence=4, snapshot=newer, executable='/fixture/newer'))
        session['sequence'] = 4; session['writers']['1100'].update(observation_sequence=4, lineage_observation_sequences=[1, 4])
        session['native_sampler']['full_capture_sequences']['4'] = observed._full_capture_binding(session['observations'][-1], 4)
        self.diagnostic(session)['capture_sequence'] = session['native_sampler']['durable_sequence'] = 5
        self.rebind(session)
        with self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_b_initial_first_full_and_confirmation_inverse_table(self):
        original = self.session('b')
        for variant in ('missing_confirmation', 'uuid_equal', 'post_epoch', 'post_state', 'post_parent', 'post_time', 'p1_missing',
                        'p1_unknown', 'p1_time', 'p2_fabricated', 'full_birth', 'full_epoch', 'full_uuid', 'full_state', 'full_time', 'parent_missing'):
            session = copy.deepcopy(original); item = self.diagnostic(session); post = item['followup']['snapshot']; full = session['observations'][1]['snapshot']
            if variant == 'missing_confirmation': item['followup'] = dict(outcome='unavailable', snapshot=None, problem='missing')
            elif variant == 'uuid_equal': post['executable_uuid'] = item['raw']['executable_uuid']
            elif variant == 'post_epoch': post['idversion'] += 1
            elif variant == 'post_state': post['current_ppid'] = 1
            elif variant == 'post_parent': post['original_parent_idversion'] += 1
            elif variant == 'post_time': post['observed'] = copy.deepcopy(item['raw']['observed'])
            elif variant == 'p1_missing': item['capture'].pop('p1')
            elif variant == 'p1_unknown': item['capture']['p1']['outcome'] = 'unknown'
            elif variant == 'p1_time': item['capture']['p1']['monotonic_ns'] = post['observed']['monotonic_ns']
            elif variant == 'p2_fabricated': item['capture']['p2'] = dict(outcome='success')
            elif variant == 'full_birth': full['identity']['created']['microseconds'] += 1
            elif variant == 'full_epoch': full['idversion'] += 1
            elif variant == 'full_uuid': full['executable_uuid'] = item['raw']['executable_uuid']
            elif variant == 'full_state': full['pgid'] += 1
            elif variant == 'full_time': full['observed'] = copy.deepcopy(post['observed'])
            else:
                for node in (item['raw'], post, full): node['original_parent_idversion'] = 999
            self.rebind(session)
            with self.subTest(variant=variant), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_b_prior_full_and_raw_graph_promotion_are_not_waivers(self):
        session = self.session('b'); item = self.diagnostic(session)
        prior = self.base.at(item['raw'], 1500); prior['idversion'] -= 1
        first = session['observations'].pop(); first['sequence'] = 3
        session['observations'] += [dict(sequence=2, snapshot=prior, executable='/fixture/prior'), first]
        session['sequence'] = 3; session['writers']['1100'].update(observation_sequence=3, lineage_observation_sequences=[1, 3])
        item['qualification']['after_observation_sequence'] = 3
        session['native_sampler']['full_capture_sequences'] = {'2': observed._full_capture_binding(session['observations'][1], 1),
                                                              '3': observed._full_capture_binding(first, 5)}
        item['qualification']['full_capture_reference'] = copy.deepcopy(session['native_sampler']['full_capture_sequences']['3'])
        self.rebind(session)
        with self.assertRaises(EvidenceError): observed.validate_session(session)
        graph = native.LineageGraph(8); root = session['observations'][0]['snapshot']
        graph.add_root(root, expected_identity=root['identity'], expected_unique_id='1000')
        graph.ingest(item['raw'])
        with self.assertRaises(native.ObservationError): graph.ingest(first['snapshot'])

    def test_root_exclusion_pid_and_key_applies_even_to_preexisting_diagnostic(self):
        for kind in ('a', 'b'):
            for field in ('pid', 'unique'):
                session = self.session(kind); item = self.diagnostic(session)
                if field == 'pid': session['roots']['1000']['pid'] = 102
                else: session['roots']['1100'] = session['roots']['1000']
                self.assertFalse(observed._valid_metadata3_qualification(session, item, item['qualification']))


    def append_full(self, session, node, capture):
        sequence = session['sequence'] + 1
        item = dict(sequence=sequence, snapshot=node, executable='/fixture/full')
        session['observations'].append(item); session['sequence'] = sequence
        sampler = session['native_sampler']; sampler['durable_sequence'] = max(sampler['durable_sequence'], capture)
        sampler['full_capture_sequences'][str(sequence)] = observed._full_capture_binding(item, capture)
        if node['unique_id'] == '1100':
            session['writers']['1100'].update(observation_sequence=sequence, lineage_observation_sequences=[1, sequence])
        else:
            session['writers']['1100']['lineage_observation_sequences'] = [sequence, session['writers']['1100']['observation_sequence']]
        return sequence

    def test_latest_capture_precedes_clock_checks_four_review_counterexamples(self):
        for name, mono, wall, post_mono, post_wall in (
                ('wall_regression', 6000, 5200, 8000, 5300), ('wall_tie', 6000, 5500, 8000, 5600),
                ('mono_regression', 5200, 6000, 8000, 8000), ('mono_tie', 5500, 6000, 8000, 8000)):
            session = self.session('a'); diagnostic = self.diagnostic(session)
            newer = self.base.at(session['observations'][2]['snapshot'], 5500)
            newer['idversion'] += 1; newer['executable_uuid'] = '56565656-5656-4565-8565-565656565656'
            self.append_full(session, newer, 4)
            diagnostic['capture_sequence'] = session['native_sampler']['durable_sequence'] = 5
            diagnostic['raw']['observed'] = dict(monotonic_ns=str(mono), wall_time_ns=str(2000000000000 + wall))
            diagnostic['followup']['snapshot']['observed'] = dict(monotonic_ns=str(post_mono), wall_time_ns=str(2000000000000 + post_wall))
            self.rebind(session)
            self.assertTrue(observed._valid_full_captures(session))
            with self.subTest(case=name, ref='ancient'), self.assertRaises(EvidenceError): observed.validate_session(session)
            diagnostic['qualification']['before_observation_sequence'] = 4
            diagnostic['qualification']['full_capture_reference'] = copy.deepcopy(session['native_sampler']['full_capture_sequences']['4'])
            self.rebind(session)
            with self.subTest(case=name, ref='actual_latest'), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_latest_matching_full_and_legitimate_future_full_or_root_refresh(self):
        session = self.session('a'); diagnostic = self.diagnostic(session)
        self.append_full(session, self.base.at(session['observations'][2]['snapshot'], 5500), 4)
        diagnostic['capture_sequence'] = session['native_sampler']['durable_sequence'] = 5
        diagnostic['qualification']['before_observation_sequence'] = 4
        diagnostic['qualification']['full_capture_reference'] = copy.deepcopy(session['native_sampler']['full_capture_sequences']['4'])
        self.rebind(session); observed.validate_session(session)
        for root_refresh in (False, True):
            value = self.session('a'); immutable = copy.deepcopy(value['observations'])
            node = self.base.at(value['observations'][0 if root_refresh else 2]['snapshot'], 9000)
            if not root_refresh:
                node['idversion'] += 1; node['executable_uuid'] = '56565656-5656-4565-8565-565656565656'
            self.append_full(value, node, 5)
            observed.validate_session(value)
            self.assertEqual(value['observations'][:len(immutable)], immutable)

    def test_b_actual_first_capture_not_future_clocks_or_later_convenience(self):
        session = self.session('b'); diagnostic = self.diagnostic(session)
        mapping = session['native_sampler']['full_capture_sequences']
        mapping['2'] = observed._full_capture_binding(session['observations'][1], 3)
        diagnostic['qualification']['full_capture_reference'] = copy.deepcopy(mapping['2']); self.rebind(session)
        self.assertTrue(observed._valid_full_captures(session))
        with self.assertRaises(EvidenceError): observed.validate_session(session)
        value = self.session('b'); self.append_full(value, self.base.at(value['observations'][1]['snapshot'], 9000), 6)
        observed.validate_session(value)

    def test_complete_full_map_shape_order_collision_hash_and_qualification_inverses(self):
        original = self.session('a')
        for variant in ('missing_map', 'missing', 'extra', 'root_fabricated', 'bool_cap', 'zero', 'future', 'duplicate',
                        'reordered', 'digest', 'body', 'diag_collision', 'exec_collision', 'status_collision', 'pending_collision',
                        'ref_cap', 'ref_bool', 'ref_hash', 'ref_removed', 'binding_raw', 'binding_qualification'):
            session = copy.deepcopy(original); sampler = session['native_sampler']; mapping = sampler['full_capture_sequences']
            item = self.diagnostic(session); reference = item['qualification']['full_capture_reference']
            if variant == 'missing_map': sampler.pop('full_capture_sequences')
            elif variant == 'missing': mapping.pop('2')
            elif variant == 'extra': mapping['99'] = copy.deepcopy(mapping['3'])
            elif variant == 'root_fabricated': mapping['1'] = observed._full_capture_binding(session['observations'][0], 2)
            elif variant == 'bool_cap': mapping['2']['capture_sequence'] = True
            elif variant == 'zero': mapping['2'] = observed._full_capture_binding(session['observations'][1], 0)
            elif variant == 'future': mapping['3'] = observed._full_capture_binding(session['observations'][2], 5)
            elif variant == 'duplicate': mapping['3'] = observed._full_capture_binding(session['observations'][2], 1)
            elif variant == 'reordered':
                mapping['2'] = observed._full_capture_binding(session['observations'][1], 3)
                mapping['3'] = observed._full_capture_binding(session['observations'][2], 1)
            elif variant == 'digest': mapping['3']['full_sha256'] = '0' * 64
            elif variant == 'body': session['observations'][2]['executable'] = '/fixture/replaced'
            elif variant == 'diag_collision': mapping['3'] = observed._full_capture_binding(session['observations'][2], 4)
            elif variant in ('exec_collision', 'status_collision', 'pending_collision'):
                if variant == 'exec_collision': sampler['exec_transitions'] = [dict(capture_sequence=3)]
                elif variant == 'status_collision': sampler['statuses'] = {'1100': dict(capture_sequence=3)}
                else: sampler['unresolved'] = [dict(sequence=3)]
                self.assertFalse(observed._valid_full_captures(session)); continue
            elif variant == 'ref_cap': reference['capture_sequence'] = 2
            elif variant == 'ref_bool': reference['capture_sequence'] = True
            elif variant == 'ref_hash': reference['full_sha256'] = '0' * 64
            elif variant == 'ref_removed': item['qualification'].pop('full_capture_reference')
            elif variant == 'binding_raw': sampler['helper_diagnostic_bindings']['4']['raw_sha256'] = '0' * 64
            else: sampler['helper_diagnostic_bindings']['4']['qualification_sha256'] = '0' * 64
            if not variant.startswith('binding_'): self.rebind(session)
            with self.subTest(variant=variant), self.assertRaises(EvidenceError): observed.validate_session(session)


_FROZEN_510_EXEC_V1 = "def _valid_exec_resolution(session, transition, resolution):\n    if (type(resolution) is not dict or set(resolution) != {'version', 'observation_sequence', 'root'}\n            or type(resolution['version']) is not int or resolution['version'] != 1 or type(resolution['observation_sequence']) is not int\n            or not 1 <= resolution['observation_sequence'] <= len(session['observations'])\n            or resolution['root'] not in session['roots']):\n        return False\n    item = session['observations'][resolution['observation_sequence'] - 1]\n    node, before, after = item['snapshot'], transition['before'], transition['after']\n    immutable = ('identity', 'unique_id', 'boot_uuid', 'uid', 'original_parent_unique_id', 'original_parent_idversion')\n    if (node['status'] != 'alive' or any(node[key] != before[key] for key in immutable)\n            or node['idversion'] < after['idversion'] or node['idversion'] <= before['idversion']\n            or node['idversion'] == after['idversion'] and node['executable_uuid'] != after['executable_uuid']\n            or any(int(node['observed'][key]) <= int(after['observed'][key]) for key in ('monotonic_ns', 'wall_time_ns'))):\n        return False\n    if node['unique_id'] in session['roots']:\n        root = session['roots'][node['unique_id']]\n        if (resolution['root'] != node['unique_id'] or 'target_executable' not in root\n                or item['executable'] != root['target_executable']['path']):\n            return False  # Roots still need actual declared target and wrapper proofs.\n    else:\n        writer = session['writers'].get(node['unique_id'])\n        if writer is None or writer['root'] != resolution['root'] or writer['identity'] != node['identity']:\n            return False\n    try:\n        exact_chain_sequences(session, resolution['root'], resolution['observation_sequence'])\n    except EvidenceError:\n        return False\n    return True"


class InitialHelperExecResolutionTests(unittest.TestCase):
    setUp = MetadataV3ReceiptTests.setUp
    diagnostic = staticmethod(MetadataV3ReceiptTests.diagnostic)
    rebind = MetadataV3ReceiptTests.rebind

    @staticmethod
    def raw_digest(transition):
        return observed.hashlib.sha256(observed.canonical({k: v for k, v in transition.items() if k != 'resolution'}).encode()).hexdigest()

    def make(self):
        session = MetadataV3ReceiptTests.session(self, 'b'); sampler = session['native_sampler']
        sampler['helper_diagnostics'] = []; sampler['helper_diagnostic_bindings'] = {}
        full = session['observations'][1]['snapshot']
        after = self.base.at(full, 4000); after['executable_uuid'] = '56565656-5656-4565-8565-565656565656'
        before = self.base.at(after, 2000); before['idversion'] -= 1
        transition = dict(version=1, kind='kernel_lineage_exec_transition', capture_sequence=4,
            path_status='unobserved_during_exec', before=before, after=after, resolution=None)
        sampler['exec_transitions'] = [transition]
        session['pending'] = {'exec:4': dict(pid=102, reason='unobserved executable during exec')}
        observed.validate_session(session)
        return session, transition

    def resolution(self, session, transition, sequence=2):
        return dict(version=3, kind='initial_helper_post_transition_full', observation_sequence=sequence, root='1000',
            full_capture_reference=copy.deepcopy(session['native_sampler']['full_capture_sequences'][str(sequence)]),
            transition_sha256=self.raw_digest(transition))

    def test_initial_helper_exact_first_full_resolves_without_raw_graph_or_image(self):
        session, transition = self.make(); prefix = copy.deepcopy(session['observations']); raw = copy.deepcopy(transition)
        resolution = self.resolution(session, transition)
        self.assertTrue(observed._valid_exec_resolution(session, transition, resolution))
        transition['resolution'] = resolution; session['pending'].pop('exec:4')
        observed.validate_session(session)
        self.assertEqual(session['observations'], prefix)
        self.assertEqual({k: v for k, v in transition.items() if k != 'resolution'}, {k: v for k, v in raw.items() if k != 'resolution'})
        self.assertEqual(session['writers']['1100']['authority'], observed.AUTHORITY)
        self.assertFalse(observed._valid_exec_resolution(session, transition, dict(version=1, observation_sequence=2, root='1000')))

    def qualified(self):
        session, transition = self.make(); transition['resolution'] = self.resolution(session, transition)
        session['pending'].pop('exec:4'); observed.validate_session(session)
        return session, transition

    def test_strict_new_resolution_shape_scalars_and_digest_rejection(self):
        for variant in ('version_bool', 'version_float', 'version_string', 'kind', 'extra', 'missing', 'obs_bool', 'obs_float',
                        'obs_zero', 'obs_foreign', 'root', 'ref_bool', 'ref_float', 'ref_hash', 'ref_extra', 'raw_type', 'raw_shape', 'raw_hash'):
            session, transition = self.make(); resolution = self.resolution(session, transition)
            if variant == 'version_bool': resolution['version'] = True
            elif variant == 'version_float': resolution['version'] = 3.0
            elif variant == 'version_string': resolution['version'] = '3'
            elif variant == 'kind': resolution['kind'] = 'unversioned_image_gap'
            elif variant == 'extra': resolution['unknown'] = None
            elif variant == 'missing': resolution.pop('kind')
            elif variant == 'obs_bool': resolution['observation_sequence'] = True
            elif variant == 'obs_float': resolution['observation_sequence'] = 2.0
            elif variant == 'obs_zero': resolution['observation_sequence'] = 0
            elif variant == 'obs_foreign': resolution['observation_sequence'] = 1
            elif variant == 'root': resolution['root'] = 'foreign'
            elif variant == 'ref_bool': resolution['full_capture_reference']['capture_sequence'] = True
            elif variant == 'ref_float': resolution['full_capture_reference']['capture_sequence'] = 5.0
            elif variant == 'ref_hash': resolution['full_capture_reference']['full_sha256'] = '0' * 64
            elif variant == 'ref_extra': resolution['full_capture_reference']['untrusted'] = 1
            elif variant == 'raw_type': resolution['transition_sha256'] = 1
            elif variant == 'raw_shape': resolution['transition_sha256'] = 'A' * 64
            else: resolution['transition_sha256'] = '0' * 64
            with self.subTest(variant=variant): self.assertFalse(observed._valid_exec_resolution(session, transition, resolution))
            transition['resolution'] = resolution; session['pending'].clear()
            with self.subTest(variant=variant), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_rebound_native_core_epoch_state_clock_and_root_inverse_table(self):
        for variant in ('birth', 'unique', 'uid', 'boot', 'parent', 'parent_epoch', 'epoch', 'pgid', 'ppid', 'query',
                        'zombie', 'wall_tie', 'mono_regress', 'raw_bad_query', 'raw_zombie', 'raw_backwards', 'root_pid', 'root_key', 'missing_writer'):
            session, transition = self.make(); full = session['observations'][1]['snapshot']
            if variant == 'birth': full['identity']['created']['microseconds'] += 1
            elif variant == 'unique': full['unique_id'] = '1199'
            elif variant == 'uid': full['uid'] += 1
            elif variant == 'boot': full['boot_uuid'] = '67676767-6767-4676-8676-676767676767'
            elif variant == 'parent': full['original_parent_unique_id'] = '9999'
            elif variant == 'parent_epoch': full['original_parent_idversion'] += 1
            elif variant == 'epoch': full['idversion'] += 1
            elif variant == 'pgid': full['pgid'] += 1
            elif variant == 'ppid': full['current_ppid'] = 1
            elif variant == 'query': full['query']['native_status'] = 3
            elif variant == 'zombie': full['status'] = 'zombie'; full['query']['native_status'] = 5
            elif variant == 'wall_tie': full['observed']['wall_time_ns'] = transition['after']['observed']['wall_time_ns']
            elif variant == 'mono_regress': full['observed']['monotonic_ns'] = '1'
            elif variant == 'raw_bad_query': transition['after']['query']['errno'] = fixtures.errno.EACCES
            elif variant == 'raw_zombie': transition['after']['status'] = 'zombie'; transition['after']['query']['native_status'] = 5
            elif variant == 'raw_backwards': transition['after']['observed'] = copy.deepcopy(transition['before']['observed'])
            elif variant == 'root_pid': session['roots']['1000']['pid'] = 102
            elif variant == 'root_key': session['roots']['1100'] = copy.deepcopy(session['roots']['1000'])
            else: session['writers'].clear()
            session['native_sampler']['full_capture_sequences']['2'] = observed._full_capture_binding(session['observations'][1], 5)
            resolution = self.resolution(session, transition)
            with self.subTest(variant=variant): self.assertFalse(observed._valid_exec_resolution(session, transition, resolution))

    def test_first_actual_capture_and_prior_full_are_never_filtered_by_clocks_or_epoch(self):
        session, transition = self.make()
        session['native_sampler']['full_capture_sequences']['2'] = observed._full_capture_binding(session['observations'][1], 3)
        self.assertTrue(observed._valid_full_captures(session))
        self.assertFalse(observed._valid_exec_resolution(session, transition, self.resolution(session, transition)))
        for conflicting_epoch in (False, True):
            session, transition = self.make(); selected = session['observations'][1]; selected['sequence'] = 3
            prior = self.base.at(transition['before'], 9000)  # Clock appears later but actual event is earlier.
            if not conflicting_epoch: prior['idversion'] = transition['after']['idversion']
            session['observations'] = [session['observations'][0], dict(sequence=2, snapshot=prior, executable='/fixture/prior'), selected]
            session['sequence'] = 3; session['writers']['1100'].update(observation_sequence=3, lineage_observation_sequences=[1, 3])
            session['native_sampler']['full_capture_sequences'] = {'2': observed._full_capture_binding(session['observations'][1], 1), '3': observed._full_capture_binding(selected, 5)}
            self.assertTrue(observed._valid_full_captures(session))
            self.assertFalse(observed._valid_exec_resolution(session, transition, self.resolution(session, transition, 3)))

    def test_frozen_actual_reader_and_legacy_digest_bytes_are_preserved(self):
        namespace = dict(vars(observed)); exec(compile(_FROZEN_510_EXEC_V1, '<frozen510_exec_validator>', 'exec'), namespace)
        frozen = namespace['_valid_exec_resolution']
        session, transition = self.make(); resolution = self.resolution(session, transition)
        self.assertFalse(frozen(session, transition, resolution))
        old_payload = dict(full_capture_sequences=session['native_sampler']['full_capture_sequences'], helper_diagnostic_bindings={})
        old_digest = observed.hashlib.sha256(observed.canonical(old_payload).encode()).hexdigest()
        self.assertEqual(observed._metadata_capture_digest(session), old_digest)
        transition['after']['executable_uuid'] = session['observations'][1]['snapshot']['executable_uuid']
        transition['resolution'] = dict(version=1, observation_sequence=2, root='1000'); session['pending'].clear()
        self.assertTrue(frozen(session, transition, transition['resolution']))
        self.assertEqual(observed._metadata_capture_digest(session), old_digest)
        session['state'] = 'closed'; session['native_sampler'].update(state='stopped', stopped_sequence=5)
        session['closure'] = dict(sequence=2, numeric_absent=True, roots_no_handles=True, metadata_capture_sha256=old_digest)
        observed.validate_session(session)
        qualified, event = self.qualified()
        frozen_globals = dict(observed.validate_session.__globals__, _valid_exec_resolution=frozen)
        frozen_reader = type(observed.validate_session)(observed.validate_session.__code__, frozen_globals)
        with self.assertRaises(EvidenceError): frozen_reader(qualified, current_sources=False)
        for version in (1, 2):
            qualified['native_sampler']['version'] = version
            self.assertFalse(observed._valid_exec_resolution(qualified, event, event['resolution']))

    def test_conditional_digest_recomputes_raw_and_entire_resolution_and_future_root_refresh(self):
        session, transition = self.qualified(); raw = copy.deepcopy(transition); full = copy.deepcopy(session['observations'][1])
        payload = dict(full_capture_sequences=session['native_sampler']['full_capture_sequences'], helper_diagnostic_bindings={},
            exec_resolution3_bindings={'4': dict(version=1, transition_sha256=self.raw_digest(transition),
                resolution_sha256=observed.hashlib.sha256(observed.canonical(transition['resolution']).encode()).hexdigest())})
        self.assertEqual(observed._metadata_capture_digest(session), observed.hashlib.sha256(observed.canonical(payload).encode()).hexdigest())
        root = dict(sequence=3, snapshot=self.base.at(session['observations'][0]['snapshot'], 9000), executable='/fixture/root')
        session['observations'].append(root); session['sequence'] = 3; session['native_sampler']['durable_sequence'] = 6
        session['native_sampler']['full_capture_sequences']['3'] = observed._full_capture_binding(root, 6)
        session['writers']['1100']['lineage_observation_sequences'] = [3, 2]
        observed.validate_session(session); self.assertEqual(transition, raw); self.assertEqual(session['observations'][1], full)
        old_digest = observed._metadata_capture_digest(session)
        transition['before']['executable_uuid'] = '78787878-7878-4787-8787-787878787878'
        transition['resolution']['transition_sha256'] = self.raw_digest(transition)
        observed.validate_session(session)  # Before UUID need not equal after UUID; neither is a FULL image.
        self.assertNotEqual(observed._metadata_capture_digest(session), old_digest)

    def test_new_resolution_raw_and_rebound_refs_invalidate_barrier_and_closed_digest(self):
        session, transition = self.qualified(); session['state'] = 'closing'; session['excluded_candidates'] = {}
        digest = observed._metadata_capture_digest(session)
        session['cleanup_barrier'] = dict(valid=True, sequence=2, root_refs=['private-root'], numeric_absent=True,
                                         roots_no_handles=True, closed=False, metadata_capture_sha256=digest)
        observed.validate_session(session)
        original = copy.deepcopy(session)
        def change(value):
            event = value['native_sampler']['exec_transitions'][0]
            event['before']['executable_uuid'] = '78787878-7878-4787-8787-787878787878'
            event['resolution']['transition_sha256'] = self.raw_digest(event)
        observed.Observer._mutate(session, change)
        self.assertEqual(session['state'], 'failed'); self.assertFalse(session['cleanup_barrier']['valid'])
        observed.validate_session(session)
        closed = copy.deepcopy(original); closed['state'] = 'closed'
        closed['native_sampler'].update(state='stopped', stopped_sequence=5)
        closed['closure'] = dict(sequence=2, numeric_absent=True, roots_no_handles=True, metadata_capture_sha256=digest)
        observed.validate_session(closed)
        change(closed)
        self.assertTrue(observed._valid_exec_resolution(closed, closed['native_sampler']['exec_transitions'][0],
                                                       closed['native_sampler']['exec_transitions'][0]['resolution']))
        with self.assertRaisesRegex(EvidenceError, 'pre-cleanup FULL'): observed.validate_session(closed)
        closed['cleanup_barrier']['metadata_capture_sha256'] = observed._metadata_capture_digest(closed)
        with self.assertRaisesRegex(EvidenceError, 'closed FULL'): observed.validate_session(closed)

    def test_raw_transition_still_cannot_be_promoted_into_full_graph(self):
        session, transition = self.make(); root = session['observations'][0]['snapshot']
        graph = native.LineageGraph(8); graph.add_root(root, expected_identity=root['identity'], expected_unique_id='1000')
        graph.ingest(transition['before']); graph.ingest(transition['after'])
        with self.assertRaisesRegex(native.ObservationError, 'exec version chronology inconsistent'):
            graph.ingest(session['observations'][1]['snapshot'])


class MetadataV3CaptureTests(unittest.TestCase):
    def setUp(self):
        self.now, self.tick, self.phase, self.path_count = 100.0, 1000, 0, 0
        self.raw = fixtures.snapshot(102, 1100, 1000, birth=103, version=20, parent_version=10, ppid=101, pgid=555)
        self.post = copy.deepcopy(self.raw); self.post['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
        self.path_error = None; self.fail_second = False
        self.contexts = [patch.object(observed.time, 'monotonic', side_effect=lambda: self.now),
                         patch.object(observed.time, 'monotonic_ns', side_effect=self.clock),
                         patch.object(observed.native, 'read_snapshot', side_effect=self.read),
                         patch.object(observed, 'child_pids', return_value=()),
                         patch.object(observed, 'executable_path', side_effect=self.path)]
        for item in self.contexts: item.start(); self.addCleanup(item.stop)
        self.sampler = ManualSampler(helper_metadata_version=3); self.addCleanup(self.sampler.stop)

    def clock(self): self.tick += 1; return self.tick

    def read(self, pid, include_zombie=True):
        self.phase += 1
        node = copy.deepcopy(self.raw if self.phase == 1 else self.post)
        tick = self.clock(); node['observed'] = dict(monotonic_ns=str(tick), wall_time_ns=str(2000000000000 + tick))
        return node

    def path(self, pid):
        self.path_count += 1
        if self.path_error is not None and (not self.fail_second or self.path_count % 2 == 0):
            raise observed._PathQueryError('mocked path failure', dict(version=1, api='libproc.proc_pidpath', stage='query', pid=pid,
                returned_size=0, errno=self.path_error, buffer_size=4096, outcome='unavailable', monotonic_ns=str(self.clock())))
        return '/fixture/helper'

    def poll(self, **kwargs):
        self.phase = 0
        return self.sampler._collect(102, required=True, **kwargs)

    def test_repeated_initial_image_pair_dedups_and_consumes_shared_five_attempt_budget(self):
        self.poll()
        for _ in range(4):
            self.now = min(state['next'] for state in self.sampler._metadata_budgets.values()) + .00001
            self.poll()
        count = self.path_count
        for _ in range(4100): self.poll()
        self.assertEqual(self.path_count, count); self.assertEqual(count, 5)
        self.assertEqual(self.sampler._sequence, 1); self.assertEqual(len(self.sampler._events), 1)
        self.assertEqual({item['attempts'] for item in self.sampler._metadata_budgets.values()}, {5})

    def test_a_second_path_error_retains_actual_position(self):
        self.post = copy.deepcopy(self.raw)
        previous = copy.deepcopy(self.raw); previous['observed'] = dict(monotonic_ns='999', wall_time_ns='2000000000999')
        self.sampler._complete[102] = previous
        self.sampler._known[102] = copy.deepcopy(previous); self.sampler._last[102] = observed.semantic(previous)
        self.raw['pgid'] = self.post['pgid'] = 556
        self.path_error, self.fail_second = fixtures.errno.ESRCH, True
        self.poll()
        event = self.sampler._events[0][0]
        self.assertEqual(event['diagnostic']['version'], 3)
        self.assertEqual(event['diagnostic']['capture'], {'version': 1, 'failed_path': 'p2'})
        self.assertEqual(self.path_count, 2)

    def test_root_expected_force_and_permission_never_gain_new_diagnostic_eligibility(self):
        for variant in ('pid', 'unique', 'expected', 'force', 'permission'):
            self.sampler = ManualSampler(helper_metadata_version=3); self.addCleanup(self.sampler.stop)
            self.path_error = None; self.fail_second = False; options = {}
            if variant in ('pid', 'unique'):
                root = copy.deepcopy(self.raw)
                if variant == 'pid': root['unique_id'] = '9999'
                else: root['identity']['pid'] = 999
                self.sampler._roots[root['unique_id']] = root
            elif variant == 'expected': options['expected'] = copy.deepcopy(self.raw)
            elif variant == 'force': options['force_ticket'] = Mock(capture_sequence=None)
            else: self.path_error = fixtures.errno.EACCES
            self.poll(**options)
            with self.subTest(variant=variant):
                self.assertFalse(any(event['kind'] == 'helper_metadata' and event['diagnostic'].get('version') == 3
                                     for event, size in self.sampler._events))


class MetadataV3WorkerTests(unittest.TestCase):
    def test_mode_forwarding_and_lost_ack_fail_closed_with_private_mock_descriptors(self):
        worker = fixtures.worker
        for lost in (False, True):
            fake = Mock(); fake.value = dict(state='observing'); fake.request.return_value = dict(closed=True)
            chunks = [b'{"command":"close","timeout":1}\n']
            with patch.object(worker, 'validate_control_fd'), patch.object(worker.os, 'set_blocking'), patch.object(worker.os, 'close'), \
                 patch.object(worker, '_environment_ledger', return_value=(Mock(), 'attempt')), patch.object(worker, 'Observer', return_value=fake) as constructor, \
                 patch.object(worker.os, 'read', side_effect=chunks), patch.object(worker.select, 'select', return_value=([3], [4], [])), \
                 patch.object(worker.os, 'write', side_effect=BrokenPipeError('lost ack') if lost else lambda fd, data: len(data)):
                self.assertEqual(worker.run(99, 3, 4, 'hold', helper_metadata_version=3), 1 if lost else 0)
                self.assertEqual(constructor.call_args.kwargs['helper_metadata_version'], 3)
                if lost: self.assertTrue(fake.fail.call_args.kwargs['lost'])

