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
        value = self.record_now(); value['observation_session']['closure']['helper_diagnostics_sha256'] = '0' * 64; self.save(value)
        with self.assertRaisesRegex(EvidenceError, 'diagnostic integrity'): self.record_now()


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
        sampler['helper_diagnostics'] = [diagnostic]; sampler['helper_diagnostic_bindings'] = {}
        self.rebind(session); observed.validate_session(session)
        return session

    @staticmethod
    def diagnostic(session): return session['native_sampler']['helper_diagnostics'][0]

    def rebind(self, session):
        item = self.diagnostic(session)
        session['native_sampler']['helper_diagnostic_bindings'][str(item['capture_sequence'])] = observed._helper_raw_digest(item)

    def test_three_explicit_and_two_rejects_new_type_without_reinterpretation(self):
        for kind in ('a', 'b'):
            session = self.session(kind); session['native_sampler']['version'] = 2
            with self.subTest(kind=kind), self.assertRaises(EvidenceError): observed.validate_session(session)

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


class MetadataV3CaptureTests(unittest.TestCase):
    def setUp(self):
        self.now, self.tick, self.phase, self.path_count = 100.0, 1000, 0, 0
        self.raw = fixtures.snapshot(102, 1100, 1000, birth=103, version=20, parent_version=10, ppid=101, pgid=555)
        self.post = copy.deepcopy(self.raw); self.post['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
        self.path_error = None; self.fail_second = False
        self.contexts = [patch.object(observed.time, 'monotonic', side_effect=lambda: self.now),
                         patch.object(observed.time, 'monotonic_ns', side_effect=self.clock),
                         patch.object(observed.native, 'read_snapshot', side_effect=self.read),
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

