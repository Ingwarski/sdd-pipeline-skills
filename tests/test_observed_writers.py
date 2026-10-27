"""Isolated SDK registry fixtures: no shared ledger, browser, provider or signals."""
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/to-sdd-pipeline/scripts'
sys.path.insert(0, str(SCRIPTS))
from evidence import observed_writers as observed, observed_writer_worker as worker
from evidence import producer_runtime as runtime, producer, quarantine, darwin_observation as native
from evidence.accounting import Accounting
from evidence.io import EvidenceError
from evidence.policy import load_defaults


def snapshot(pid, unique, parent, *, birth=100, version=10, parent_version=9, ppid=99, pgid=100):
    return dict(version=1, identity=dict(version=1, host='fixture.invalid', platform='darwin', pid=pid,
                created=dict(seconds=birth, microseconds=0)), boot_uuid='12121212-1212-4212-8212-121212121212',
                uid=501, current_ppid=ppid, pgid=pgid, status='alive', unique_id=str(unique),
                original_parent_unique_id=str(parent), idversion=version, original_parent_idversion=parent_version,
                executable_uuid='23232323-2323-4323-8323-232323232323',
                query=dict(api='libproc.proc_pidinfo', flavor=18, arg=1, abi=native.ABI, size=192,
                           returned_size=192, errno=0, native_status=2),
                observed=dict(wall_time_ns='2000000000000', monotonic_ns='1000'))


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sdd-observed-fixture-')
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'output'; self.output.mkdir()
        self.policy = load_defaults(); self.policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider='local')
        self.ledger = Accounting(self.root / 'machine/ledger.sqlite', self.policy['project_id'], self.policy)
        self.reservation = self.ledger.reserve('run', 'unit', 65536, 20, local_bytes=65536,
                                              metadata_bytes=runtime.MAX_RECORD * 3, capacity_path=self.output)
        self.output_id = self.ledger.register_output('run', 'unit', self.output)
        self.working = self.ledger.reserve_working(131072, capacity_path=self.output)
        self.ledger.connection.execute('UPDATE working_reservations SET owner_pid=?,owner_host=? WHERE id=?',
                                       (99, 'fixture.invalid', self.working))
        self.attempt = str(uuid.uuid4())
        self.owner = snapshot(99, 900, 800, birth=99, version=9, parent_version=8, ppid=98)
        self.mine = snapshot(200, 2000, 900, birth=102)
        self.browser = snapshot(101, 1000, 900, birth=101)
        self.nodes = {99: self.owner, 200: self.mine, 101: self.browser}
        self.membership = dict(version=1, attempt_id=self.attempt, owner=self.owner['identity'],
                               anchor=snapshot(100, 950, 800)['identity'], group_id=100, session_id=100)
        self.record = dict(version=1, attempt_id=self.attempt, run_id='run', unit_id='unit', reservation_id=self.reservation,
                           output_id=self.output_id, coordinator=self.owner['identity'], guardian=self.owner['identity'],
                           status='running', processes={}, resources=[], output_dir=str(self.output),
                           output_identity=runtime.directory_identity(self.output), policy=self.policy)
        self.save(self.record)
        self.stamp = 1000
        self.patches = [patch.object(observed.os, 'getppid', return_value=99),
                        patch.object(observed.os, 'getpid', return_value=200),
                        patch.object(observed.os, 'getsid', return_value=100),
                        patch.object(runtime, 'managed_group_identity', return_value=self.membership),
                        patch.object(observed.process_identity, 'identity', side_effect=self.identity),
                        patch.object(observed.process_identity, 'state', return_value='alive'),
                        patch.object(observed.native, 'read_snapshot', side_effect=self.native),
                        patch.object(observed, 'executable_path', side_effect=lambda pid: '/fixture/node' if pid == 99 else '/fixture/python'),
                        patch.object(observed, 'candidate_pids', side_effect=lambda: tuple(self.nodes)),
                        patch.object(observed, 'child_pids', return_value=()),
                        patch.object(observed, '_no_handles')]
        for item in self.patches: item.start()
        self.created = []
        self.observer = None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for path in self.created:
            if path.exists(): path.rmdir()
        for item in reversed(self.patches): item.stop()
        self.ledger.close(); self.temp.cleanup()
        self.assertFalse(self.root.exists())

    def identity(self, pid=None):
        if pid is None:
            return self.mine['identity']
        if pid not in self.nodes:
            raise EvidenceError('fixture numeric process gone')
        return self.nodes[pid]['identity']

    def native(self, pid, include_zombie=True):
        self.stamp += 1
        item = copy.deepcopy(self.nodes.get(pid))
        if item:
            item['observed']['monotonic_ns'] = str(self.stamp)
            item['observed']['wall_time_ns'] = str(2000000000000 + self.stamp)
        return item

    def save(self, value):
        self.ledger.connection.execute('INSERT OR REPLACE INTO producer_sessions VALUES(?,?)', (self.attempt, json.dumps(value, sort_keys=True)))

    def arm(self):
        self.observer = observed.Observer(self.ledger, self.attempt, 99, self.working)
        return self.observer

    def registered(self):
        observer = self.arm()
        allocation = observer.allocate('controlled browser profile', 4096)
        self.created.append(Path(allocation['path']))
        result = observer.register_root(101, self.browser['identity'], '/fixture/python', [allocation['ref']])
        self.assertTrue(result['durable'])
        return observer

    @contextmanager
    def real_handle_checks(self, result=(1, b'', b'')):
        self.patches[-1].stop()
        try:
            with patch.object(observed, '_bounded_lsof', return_value=result):
                yield
        finally:
            self.patches[-1].start()

    def registered_target(self):
        observer = self.arm()
        allocation = observer.allocate('target profile', 4096); self.created.append(Path(allocation['path']))
        target = self.root / 'Fixture.app' / 'Contents' / 'MacOS' / 'Fixture'
        target.parent.mkdir(parents=True); target.write_bytes(b'#!/bin/sh\nexit 0\n'); target.chmod(0o700)
        observer.request(dict(command='register_root', pid=101, expected_identity=self.browser['identity'],
                              expected_executable='/fixture/python', writable_root_refs=[allocation['ref']],
                              expected_target_executable=str(target)))
        self.target = target
        return observer

    def record_now(self):
        return runtime.read(self.ledger, self.attempt)

    def test_opt_in_version2_and_old_reader_rejection(self):
        self.assertEqual(self.record_now()['version'], 1)
        self.arm()
        self.assertEqual(self.record_now()['version'], 2)
        # Previous SDK's explicit version1 condition rejects these bytes.
        self.assertNotEqual(json.loads(self.ledger.connection.execute('SELECT record FROM producer_sessions').fetchone()[0])['version'], 1)

    def test_version1_smuggling_rejected_even_empty(self):
        for key in ('observation_session', 'observed_writers', 'observation_roots', 'observation_sessions', 'observation_history'):
            self.save({**self.record, key: {}})
            with self.assertRaisesRegex(EvidenceError, 'version2'): self.record_now()

    def test_unknown_v2_or_source_change_rejected(self):
        self.arm()
        value = self.record_now(); value['observation_session']['source_sha256']['observed_writers.py'] = '0' * 64
        self.save(value)
        with self.assertRaisesRegex(EvidenceError, 'source'): self.record_now()

    def test_observer_parent_authentication_and_replay(self):
        with patch.object(observed.os, 'getppid', return_value=98):
            with self.assertRaisesRegex(EvidenceError, 'direct child'): self.arm()
        self.arm()
        with self.assertRaisesRegex(EvidenceError, 'replayed'): observed.Observer(self.ledger, self.attempt, 99, self.working)

    def test_caller_snapshot_or_unknown_fields_rejected(self):
        observer = self.arm()
        for request in ({'command': 'observe_pid', 'pid': 101, 'snapshot': self.browser},
                        {'command': 'ingest', 'snapshot': self.browser},
                        {'command': 'close', 'timeout': 1, 'proof': {}},
                        {'command': 'allocate_root', 'purpose': 'a' * observed.MAX_REQUEST, 'budget_bytes': 1}):
            with self.assertRaises(EvidenceError): observer.request(request)

    def test_root_wrong_parent_and_lost_ack_stay_pending(self):
        observer = self.arm(); allocation = observer.allocate('profile', 4096); self.created.append(Path(allocation['path']))
        self.nodes[101]['original_parent_unique_id'] = '777'
        with self.assertRaisesRegex(EvidenceError, 'proof failed'):
            observer.register_root(101, self.browser['identity'], '/fixture/python', [allocation['ref']])
        self.assertIn('root:101', self.record_now()['observation_session']['pending'])
        observer.fail('root ACK lost after durable registration', lost=True)
        self.nodes.clear()
        self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))

    def test_root_immutable_ack_and_reference_scope(self):
        observer = self.registered()
        row = self.record_now()['observation_session']['roots']['1000']
        self.assertEqual(row['identity'], self.browser['identity'])
        with self.assertRaises(EvidenceError):
            observer.register_root(101, self.browser['identity'], '/fixture/python', ['/tmp/user-profile'])

    def test_timestamp_only_poll_never_grows_graph_or_sql(self):
        observer = self.registered(); before = self.ledger.connection.total_changes
        for _ in range(4100): observer.observe(101, required=False)
        self.assertEqual(self.ledger.connection.total_changes, before)
        self.assertEqual(observer.value['sequence'], 1)
        self.assertEqual(observer.graphs['1000']._updates, 1)

    def test_foreign_group_chain_is_no_signal_obligation(self):
        observer = self.registered()
        child = snapshot(102, 1100, 1000, birth=103, parent_version=10, ppid=1, pgid=555)
        self.nodes[102] = child
        with patch.object(os, 'killpg') as signal_group, patch.object(observed.process_identity, 'terminate') as terminate:
            self.assertTrue(observer.observe(102))
            row = observer.value['writers']['1100']
            self.assertEqual(row['authority'], observed.AUTHORITY)
            self.assertEqual(self.record_now()['processes'], {})
            observed.disposition_problems(self.record_now(), ledger=self.ledger)
            signal_group.assert_not_called(); terminate.assert_not_called()

    def test_missing_intermediary_pending_then_exact_chain(self):
        observer = self.registered()
        self.nodes[103] = snapshot(103, 1200, 1100, birth=105, parent_version=10, ppid=1, pgid=666)
        self.assertFalse(observer.observe(103))
        self.assertIn('pid:103', observer.value['pending'])
        self.nodes[102] = snapshot(102, 1100, 1000, birth=103, parent_version=10, ppid=1, pgid=555)
        self.assertTrue(observer.observe(102))
        self.assertIn('1200', observer.value['writers'])
        self.assertFalse(observer.value['pending'])

    def test_wrong_parent_exec_version_does_not_associate(self):
        observer = self.registered()
        self.nodes[102] = snapshot(102, 1100, 1000, birth=103, parent_version=999, ppid=1, pgid=555)
        self.assertFalse(observer.observe(102))
        self.assertTrue(observer.value['pending']); self.assertFalse(observer.value['writers'])

    def test_exec_transition_preserves_wrapper_and_updates_truthful_identity(self):
        observer = self.registered(); old = copy.deepcopy(observer.value['observations'][0])
        self.nodes[101]['idversion'] = 11
        self.nodes[101]['executable_uuid'] = '34343434-3434-4343-8343-343434343434'
        with patch.object(observed, 'executable_path', return_value='/fixture/Chrome'):
            self.assertTrue(observer.observe(101, required=False))
        self.assertEqual(observer.value['observations'][0], old)
        self.assertEqual(observer.value['observations'][1]['executable'], '/fixture/Chrome')
        self.assertEqual(observer.value['observations'][1]['snapshot']['idversion'], 11)

    def test_numeric_reuse_and_zombie_block_closure(self):
        observer = self.registered()
        self.nodes[101] = snapshot(101, 9999, 900, birth=200, version=99)
        self.assertTrue(any('numeric PID' in x for x in observed.disposition_problems(self.record_now(), ledger=self.ledger)))
        self.nodes[101]['status'] = 'zombie'; self.nodes[101]['query']['native_status'] = 5
        self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))

    def test_no_empty_pass_after_observer_death_eof_or_lost_history(self):
        observer = self.registered(); self.nodes.clear()
        observer.fail('observer control EOF without durable closure', lost=True)
        value = self.record_now()
        self.assertTrue(observed.disposition_problems(value, ledger=self.ledger))
        self.assertEqual(value['observation_session']['state'], 'failed')
        self.assertTrue(value['observation_session']['lost_history'])
        with self.assertRaises(EvidenceError): observer.close(.01)

    def test_close_requires_fresh_absence_and_no_handles(self):
        observer = self.registered()
        del self.nodes[101]
        result = observer.close(.1)
        self.assertTrue(result['closed'])
        self.assertFalse(observed.disposition_problems(self.record_now(), ledger=self.ledger))
        observed._no_handles.assert_called()
        self.assertEqual(observer.value['closure']['sequence'], 1)

    def test_closed_report_replay_is_noop_but_fresh_reuse_blocks(self):
        observer = self.registered(); del self.nodes[101]; observer.close(.1)
        before = self.ledger.connection.total_changes
        runtime.update(self.ledger, self.attempt, lambda _: None)
        self.assertEqual(self.ledger.connection.total_changes, before)
        self.nodes[101] = snapshot(101, 9999, 900, birth=200)
        self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))

    def test_pending_empty_numeric_set_does_not_close(self):
        observer = self.registered(); self.nodes[103] = snapshot(103, 1200, 9999, birth=105)
        observer.observe(103); self.nodes.pop(103); self.nodes.pop(101)
        with self.assertRaisesRegex(EvidenceError, 'closure incomplete'): observer.close(.01)
        self.assertIn('pid:103', self.record_now()['observation_session']['pending'])

    def test_terminal_recovery_fast_path_honors_session(self):
        self.registered()
        runtime.update(self.ledger, self.attempt, lambda v: v.update(status='terminal'))
        self.ledger.settle(self.reservation, 0, 0)
        value = producer.recover_producers(self.ledger, dry_run=True)
        self.assertTrue(value['incomplete']); self.assertIn('problems', value['actions'][0])

    def test_quarantine_and_directory_cleanup_cannot_bypass_nonclosed_history(self):
        self.registered()
        runtime.update(self.ledger, self.attempt, lambda v: v.update(status='terminal'))
        with self.assertRaisesRegex(EvidenceError, 'observed writer'): quarantine.original_state(self.ledger, self.attempt)
        self.assertTrue(runtime.cleanup_directories(self.ledger, self.attempt))

    def test_managed_stop_latches_observer_loss_without_external_signals(self):
        observer = self.registered()
        with patch.object(os, 'killpg') as group, patch.object(observed.process_identity, 'terminate') as terminate:
            runtime.stop_registered(self.ledger, self.attempt)
            group.assert_not_called(); terminate.assert_not_called()
        session = self.record_now()['observation_session']
        self.assertTrue(session['lost_history']); self.assertEqual(session['state'], 'failed')

    def test_observation_bound_rollback_preserves_prior_record(self):
        observer = self.registered(); before = self.record_now()
        with patch.object(observed, 'MAX_OBSERVATIONS', 1):
            self.nodes[101]['idversion'] = 11
            with self.assertRaisesRegex(EvidenceError, 'bound'): observer.observe(101, required=False)
        self.assertEqual(self.record_now(), before)

    def test_metadata_oversize_rollback(self):
        self.arm(); before = self.record_now()
        with self.assertRaisesRegex(EvidenceError, 'metadata bound'):
            runtime.update(self.ledger, self.attempt, lambda v: v.update(large='x' * runtime.MAX_RECORD))
        self.assertEqual(self.record_now(), before)

    def test_native_lookup_failure_is_not_absence(self):
        self.registered()
        with patch.object(native, 'read_snapshot', side_effect=native.ObservationError('denied')):
            self.assertTrue(any('unavailable' in x for x in observed.disposition_problems(self.record_now(), ledger=self.ledger)))

    def test_forged_writer_missing_chain_rejected_on_read(self):
        observer = self.registered()
        self.nodes[103] = snapshot(103, 1200, 9999, birth=105)
        observer.observe(103)
        value = self.record_now(); session = value['observation_session']
        session['writers']['1200'] = dict(authority=dict(observed.AUTHORITY), root='1000',
            identity=self.nodes[103]['identity'], unique_id='1200', observation_sequence=2)
        self.save(value)
        with self.assertRaisesRegex(EvidenceError, 'complete immutable|predecessor'): self.record_now()


    def test_idle_sampler_discovers_native_children_without_caller_pid_request(self):
        observer = self.registered()
        self.nodes[102] = snapshot(102, 1100, 1000, birth=103, parent_version=10, ppid=101, pgid=555)
        self.nodes[103] = snapshot(103, 1200, 1100, birth=105, parent_version=10, ppid=1, pgid=666)
        # No census and no explicit observe_pid request: a single BFS poll sees
        # the intermediary first, then its child, including foreign PGIDs.
        observer.last_census = observed.time.monotonic()
        with patch.object(observed, 'child_pids', side_effect=lambda pid: {101: (102,), 102: (103,)}.get(pid, ())), \
             patch.object(observed, 'candidate_pids') as census:
            observer.sample()
        self.assertEqual(set(observer.value['writers']), {'1100', '1200'})
        self.assertFalse(observer.value['pending']); census.assert_not_called()
        before = self.ledger.connection.total_changes
        with patch.object(observed, 'child_pids', side_effect=lambda pid: {101: (102,), 102: (103,)}.get(pid, ())):
            for _ in range(30): observer.sample()
        self.assertEqual(self.ledger.connection.total_changes, before)

    def test_native_child_and_uid_enumeration_are_bounded(self):
        library = Mock()
        def children(pid, buffer, size):
            self.assertEqual(pid, 101); buffer[0] = 102; return 1
        library.proc_listchildpids.side_effect = children
        def candidates(kind, uid, buffer, size):
            self.assertEqual(kind, 4); self.assertEqual(uid, os.geteuid()); buffer[0] = 101; return 4
        library.proc_listpids.side_effect = candidates
        # Restore these actual wrappers; setUp patches only discovery call sites.
        with patch.object(native, '_library', return_value=library):
            # Access preserved wrapper functions captured from source compilation
            # would bypass normal module binding, so stop only the two fixture
            # enumeration mocks for this isolated native-ABI buffer exercise.
            child_patch = self.patches[-2]
            census_patch = self.patches[-3]
            child_patch.stop(); census_patch.stop()
            try:
                self.assertEqual(observed.child_pids(101), (102,))
                self.assertEqual(observed.candidate_pids(), (101,))
                library.proc_listchildpids.side_effect = lambda pid, buffer, size: size
                with self.assertRaisesRegex(EvidenceError, 'bound'): observed.child_pids(101)
                library.proc_listpids.side_effect = lambda kind, uid, buffer, size: size
                with self.assertRaisesRegex(EvidenceError, 'bound'): observed.candidate_pids()
            finally:
                census_patch.start(); child_patch.start()


    def test_working_root_capacity_is_bounded_and_symlink_not_followed(self):
        observer = self.registered()
        path = self.created[0]
        payload = path / 'payload'
        payload.write_bytes(b'x' * 4097)
        try:
            with self.assertRaisesRegex(EvidenceError, 'byte budget'): observer.check_working_capacity()
        finally:
            payload.unlink()
        link = path / 'link'
        link.symlink_to('/path/never-followed')
        try:
            size, count = observed._bounded_usage(path, deadline=observed.time.monotonic() + 1)
            self.assertEqual(count, 1); self.assertEqual(size, len('/path/never-followed'))
        finally:
            link.unlink()

    def test_ipc_paths_record_separately_once_and_foreign_targets_fail(self):
        observer = self.registered(); path = self.created[0] / 'socket-link'
        path.symlink_to('task-socket')
        try:
            observer.check_working_capacity()
            row = observer.value['ipc_paths'][str(path)]
            self.assertEqual(row['kind'], 'symlink')
            before = self.ledger.connection.total_changes
            observer.check_working_capacity()
            self.assertEqual(self.ledger.connection.total_changes, before)
        finally:
            path.unlink()
        path.symlink_to('/foreign/normal-profile/socket')
        try:
            with self.assertRaisesRegex(EvidenceError, 'no declared SDK'): observer.check_working_capacity()
        finally:
            path.unlink()

    def test_six_roots_and_exact_eight_root_limit(self):
        observer = self.arm()
        for index in range(8):
            pid, token = 101 + index, 1000 + index
            node = snapshot(pid, token, 900, birth=101 + index)
            self.nodes[pid] = node
            allocation = observer.allocate('profile-' + str(index), 4096)
            self.created.append(Path(allocation['path']))
            observer.register_root(pid, node['identity'], '/fixture/python', [allocation['ref']])
            if index == 5:
                self.assertEqual(len(self.record_now()['observation_session']['roots']), 6)
        allocation = observer.allocate('ninth', 4096); self.created.append(Path(allocation['path']))
        self.nodes[109] = snapshot(109, 1009, 900, birth=109)
        with self.assertRaisesRegex(EvidenceError, 'invalid root'):
            observer.register_root(109, self.nodes[109]['identity'], '/fixture/python', [allocation['ref']])
        self.assertEqual(len(observer.value['roots']), 8)

    def test_runtime_budget_and_files_are_independent_of_capture_reservation(self):
        observer = self.arm(); allocation = observer.allocate('large runtime', 100000)
        path = Path(allocation['path']); self.created.append(path)
        files = []
        try:
            for index in range(30):
                file = path / str(index); file.write_bytes(b'x' * 3000); files.append(file)
            observer.check_working_capacity()  # 90000 bytes/30 files exceeds capture65536/20.
        finally:
            for file in files: file.unlink()
        self.assertEqual(observer.value['working_binding']['id'], self.working)
        self.assertEqual(observer.value['runtime_file_limit'], 10000)

    def test_foreign_settled_unknown_predating_and_reused_owner_working_holds_reject(self):
        row = dict(self.ledger.connection.execute('SELECT * FROM working_reservations WHERE id=?', (self.working,)).fetchone())
        for field, bad in (('owner_pid', 77), ('owner_host', 'foreign.invalid'), ('state', 'settled'), ('created', 1.0)):
            with self.subTest(field=field):
                self.ledger.connection.execute('UPDATE working_reservations SET ' + field + '=? WHERE id=?', (bad, self.working))
                with self.assertRaises(EvidenceError): self.arm()
                self.ledger.connection.execute('UPDATE working_reservations SET ' + field + '=? WHERE id=?', (row[field], self.working))
        with self.assertRaisesRegex(EvidenceError, 'unknown'):
            observed.Observer(self.ledger, self.attempt, 99, 'unknown')
        actual = copy.deepcopy(self.owner['identity']); actual['created']['seconds'] += 1
        with patch.object(observed.process_identity, 'identity', side_effect=lambda pid=None: self.mine['identity'] if pid is None else actual):
            with self.assertRaisesRegex(EvidenceError, 'exact live coordinator'): self.arm()

    def test_working_hold_must_remain_pending_until_closed_then_settlement_is_preserved(self):
        observer = self.registered()
        self.ledger.finish_working(self.working)
        with self.assertRaisesRegex(EvidenceError, 'pending hold'): observer.allocate('late', 1)
        self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))
        self.ledger.connection.execute("UPDATE working_reservations SET state='pending' WHERE id=?", (self.working,))
        del self.nodes[101]; observer.close(.1)
        frozen = copy.deepcopy(observer.value['working_binding'])
        self.ledger.finish_working(self.working, local_key='closed-runtime', actual_bytes=0)
        self.assertFalse(observed.disposition_problems(self.record_now(), ledger=self.ledger))
        self.assertEqual(self.record_now()['observation_session']['working_binding'], frozen)
        self.ledger.connection.execute('UPDATE working_reservations SET owner_host=? WHERE id=?', ('foreign.invalid', self.working))
        self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))

    def test_runtime_file_limit_bound_and_overflow(self):
        with self.assertRaisesRegex(EvidenceError, 'file limit'):
            observed.Observer(self.ledger, self.attempt, 99, self.working, runtime_file_limit=50001)
        self.observer = observed.Observer(self.ledger, self.attempt, 99, self.working, runtime_file_limit=2)
        allocation = self.observer.allocate('files', 4096); path = Path(allocation['path']); self.created.append(path)
        files = [path / str(index) for index in range(3)]
        try:
            for file in files: file.write_text('x')
            with self.assertRaisesRegex(EvidenceError, 'entry bound'): self.observer.check_working_capacity()
        finally:
            for file in files: file.unlink()

    def test_sequential_node_sessions_preserve_closed_history_and_all_dispositions(self):
        first = self.registered(); del self.nodes[101]; first.close(.1)
        frozen = copy.deepcopy(first.value); del self.nodes[200]
        self.created[0].rmdir()  # Prior CLOSED session's allocated root was cleaned.
        second_owner = snapshot(199, 1900, 800, birth=200, version=19, parent_version=8, ppid=98)
        self.mine = snapshot(201, 2100, 1900, birth=201, version=20, parent_version=19, ppid=199)
        self.nodes[199], self.nodes[201] = second_owner, self.mine
        self.membership['owner'] = second_owner['identity']
        with patch.object(observed.os, 'getpid', return_value=201), patch.object(observed.os, 'getppid', return_value=199), \
             patch.object(observed, 'executable_path', side_effect=lambda pid: '/fixture/node' if pid == 199 else '/fixture/python'):
            second = observed.Observer(self.ledger, self.attempt, 199, self.working)
            history = self.record_now()['observation_history']
            self.assertEqual(history[0]['session'], frozen)
            self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))
            allocation = second.allocate('second profile', 4096); self.created.append(Path(allocation['path']))
            browser = snapshot(202, 2200, 1900, birth=202, version=21, parent_version=19, ppid=199)
            self.nodes[202] = browser
            second.register_root(202, browser['identity'], '/fixture/python', [allocation['ref']])
            del self.nodes[202]; second.close(.1)
            self.assertTrue(observed._no_handles.call_args_list[-2].kwargs['allow_absent'])
            self.assertFalse(observed._no_handles.call_args_list[-1].kwargs['allow_absent'])
            self.assertFalse(observed.disposition_problems(self.record_now(), ledger=self.ledger))
            self.assertEqual(self.record_now()['observation_history'][0]['session'], frozen)
        # A prior closed root's reused numeric PID remains a fresh disposition blocker.
        self.nodes[101] = snapshot(101, 9999, 900, birth=400)
        self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))
        value = self.record_now(); value['observation_history'][0]['session']['owner_executable'] = '/tampered/node'
        self.save(value)
        with self.assertRaisesRegex(EvidenceError, 'history digest'): self.record_now()

    def test_previous_failed_or_pending_session_cannot_be_replaced(self):
        observer = self.registered(); frozen = self.record_now()
        for state in ('observing', 'failed'):
            if state == 'failed': observer.fail('lost history', lost=True)
            before = self.record_now()
            with self.assertRaisesRegex(EvidenceError, 'prior closure'):
                observed.Observer(self.ledger, self.attempt, 99, self.working)
            self.assertEqual(self.record_now(), before)
        self.assertNotIn('observation_history', self.record_now())

    def test_closed_source_hashes_survive_later_sdk_update_but_active_sources_fail(self):
        observer = self.registered(); before = copy.deepcopy(observer.value['source_sha256'])
        changed = {key: 'a' * 64 for key in observed.SOURCE_FILES}
        with patch.object(observed, 'sources', return_value=changed):
            with self.assertRaisesRegex(EvidenceError, 'source'): self.record_now()
            with self.assertRaisesRegex(EvidenceError, 'source'): observer.allocate('invalid source', 1)
        del self.nodes[101]; observer.close(.1)
        with patch.object(observed, 'sources', return_value=changed):
            self.assertEqual(self.record_now()['observation_session']['source_sha256'], before)
            self.assertFalse(observed.disposition_problems(self.record_now(), ledger=self.ledger))
        value = self.record_now(); value['observation_session']['capability'] = 'unknown-older-capability'
        self.save(value)
        with self.assertRaises(EvidenceError): self.record_now()

    def test_cumulative_session_bound_and_immutable_history_digest(self):
        observer = self.registered(); del self.nodes[101]; observer.close(.1)
        value = self.record_now()
        archived = dict(sha256=__import__('hashlib').sha256(observed.canonical(observer.value).encode()).hexdigest(), session=observer.value)
        value['observation_history'] = [archived] * observed.MAX_SESSIONS
        self.save(value)
        with self.assertRaisesRegex(EvidenceError, 'session bound'): self.record_now()

    def test_working_hold_cannot_be_shared_by_another_nonclosed_attempt(self):
        observer = self.registered()
        other = copy.deepcopy(self.record); other['attempt_id'] = str(uuid.uuid4())
        self.ledger.connection.execute('INSERT INTO producer_sessions VALUES(?,?)', (other['attempt_id'], json.dumps(other)))
        original = copy.deepcopy(self.membership); self.membership['attempt_id'] = other['attempt_id']
        try:
            with self.assertRaisesRegex(EvidenceError, 'another active attempt'):
                observed.Observer(self.ledger, other['attempt_id'], 99, self.working)
            self.assertEqual(self.record_now()['observation_session'], observer.value)
        finally:
            self.membership.clear(); self.membership.update(original)

    def test_prepare_cleanup_nonempty_payload_is_ready_but_not_complete(self):
        observer = self.registered(); del self.nodes[101]
        payload = self.created[0] / 'profile'; payload.write_bytes(b'preserve until guarded cleanup')
        try:
            with self.real_handle_checks():
                reply = observer.request(dict(command='prepare_cleanup', timeout=.5))
                self.assertEqual(reply, dict(ready=True, root_refs=sorted(observer.value['working_roots']), sequence=1, closed=False))
                self.assertEqual(observer.value['state'], 'closing')
                self.assertTrue(observer.value['cleanup_barrier']['valid'])
                self.assertIsNone(observer.value['closure'])
                self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))
                with self.assertRaisesRegex(EvidenceError, 'payload'): observer.close(.02)
                with patch.object(observed, '_bounded_usage', side_effect=AssertionError('no filesystem walk while caller cleans')):
                    payload.unlink()
                    observer.sample(force_census=True)
                    self.assertTrue(observer.close(.5)['closed'])
                self.assertFalse(observed.disposition_problems(self.record_now(), ledger=self.ledger))
        finally:
            if payload.exists(): payload.unlink()

    def test_prepare_ack_then_death_or_guardian_stop_never_closes(self):
        observer = self.registered(); del self.nodes[101]
        observer.prepare_cleanup(.5)
        observer.fail('EOF during caller content cleanup', lost=True)
        session = self.record_now()['observation_session']
        self.assertFalse(session['cleanup_barrier']['valid'])
        self.assertEqual(session['state'], 'failed')
        self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))
        with self.assertRaises(EvidenceError): observer.close(.02)

    def test_guardian_stop_after_prepare_latches_valid_structural_failure(self):
        observer = self.registered(); del self.nodes[101]; observer.prepare_cleanup(.5)
        runtime.stop_registered(self.ledger, self.attempt)
        value = self.record_now()
        self.assertFalse(value['observation_session']['cleanup_barrier']['valid'])
        self.assertTrue(value['observation_session']['lost_history'])

    def test_closing_refuses_new_roots_allocations_and_registration(self):
        observer = self.registered(); del self.nodes[101]; observer.prepare_cleanup(.5)
        with self.assertRaisesRegex(EvidenceError, 'ownership changed'): observer.allocate('late root', 1)
        with self.assertRaises(EvidenceError):
            observer.register_root(101, self.browser['identity'], '/fixture/python', [next(iter(observer.value['working_roots']))])
        self.assertEqual(observer.value['state'], 'closing')

    def test_prepare_and_close_reject_replaced_linked_roots_and_open_handles(self):
        observer = self.registered(); del self.nodes[101]
        path = self.created[0]
        with self.real_handle_checks(result=(0, b'123\n', b'')):
            with self.assertRaisesRegex(EvidenceError, 'handles'): observer.prepare_cleanup(.5)
        with self.real_handle_checks():
            observer.prepare_cleanup(.5)
            old = path.with_name(path.name + '-saved'); path.rename(old)
            try:
                path.symlink_to(old, target_is_directory=True)
                with self.assertRaises(EvidenceError): observer.close(.02)
                path.unlink(); path.mkdir(mode=0o700)
                with self.assertRaises(EvidenceError): observer.close(.02)
                path.rmdir()
            finally:
                if path.is_symlink(): path.unlink()
                if path.exists(): path.rmdir()
                old.rename(path)
            with patch.object(observed, '_bounded_lsof', return_value=(0, b'456\n', b'')):
                with self.assertRaisesRegex(EvidenceError, 'handles'): observer.close(.02)
            self.assertTrue(observer.close(.5)['closed'])

    def test_new_postbarrier_writer_invalidates_precleanup_receipt(self):
        observer = self.registered(); del self.nodes[101]; observer.prepare_cleanup(.5)
        self.nodes[102] = snapshot(102, 1100, 1000, birth=105, parent_version=10, ppid=1, pgid=555)
        with self.assertRaisesRegex(EvidenceError, 'invalidated'):
            observer.sample(force_census=True)
        self.assertFalse(observer.value['cleanup_barrier']['valid'])
        self.assertEqual(observer.value['state'], 'failed')
        self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))

    def test_new_app_orphan_with_missed_intermediary_stays_durable_pending(self):
        observer = self.registered_target()
        helper = str(self.target.parents[2] / 'Frameworks' / 'helper')
        self.nodes[103] = snapshot(103, 1200, 7777, birth=105, parent_version=77, ppid=1, pgid=666)
        with patch.object(observed, 'executable_path', side_effect=lambda pid: helper if pid == 103 else '/fixture/python'):
            observer.sample(force_census=True)
            self.assertIn('pid:103', observer.value['pending'])
            self.assertNotIn('1200', observer.value['writers'])
            self.nodes.pop(103); self.nodes.pop(101)
            with self.assertRaisesRegex(EvidenceError, 'pending'): observer.prepare_cleanup(.5)
        self.assertIn('pid:103', self.record_now()['observation_session']['pending'])

    def test_old_app_process_and_exact_unrelated_old_app_ancestry_exclude(self):
        observer = self.registered_target()
        helper = str(self.target.parents[2] / 'Frameworks' / 'helper')
        self.nodes[70] = snapshot(70, 700, 600, birth=50, version=7, parent_version=6, ppid=69, pgid=777)
        self.nodes[104] = snapshot(104, 1400, 700, birth=105, parent_version=7, ppid=70, pgid=777)
        with patch.object(observed, 'executable_path', side_effect=lambda pid: helper if pid in (70, 104) else '/fixture/python'):
            observer.sample(force_census=True)
            self.assertFalse(observer.value['pending']); self.assertFalse(observer.value['writers'])
            exclusion = observer.value['excluded_candidates']['1400']
            self.assertEqual([node['unique_id'] for node in exclusion['chain']], ['1400', '700'])
            before = self.ledger.connection.total_changes
            observer.sample(force_census=True)
            self.assertEqual(self.ledger.connection.total_changes, before)

    def test_postbarrier_new_target_orphan_invalidates_without_signal_rights(self):
        observer = self.registered_target(); del self.nodes[101]; observer.prepare_cleanup(.5)
        helper = str(self.target.parents[2] / 'Frameworks' / 'helper')
        self.nodes[103] = snapshot(103, 1200, 7777, birth=105, parent_version=77, ppid=1, pgid=666)
        with patch.object(observed, 'executable_path', side_effect=lambda pid: helper if pid == 103 else '/fixture/python'), \
             patch.object(os, 'killpg') as signal_group, patch.object(observed.process_identity, 'terminate') as terminate:
            with self.assertRaisesRegex(EvidenceError, 'invalidated'): observer.sample(force_census=True)
            signal_group.assert_not_called(); terminate.assert_not_called()
        self.assertIn('pid:103', observer.value['pending'])
        self.assertFalse(observer.value['cleanup_barrier']['valid'])

    def test_expected_target_descriptor_hash_and_exec_source_change_fail(self):
        observer = self.registered_target()
        target = observer.value['roots']['1000']['target_executable']
        self.assertEqual(target['path'], str(self.target))
        self.assertEqual(target['sha256'], __import__('hashlib').sha256(self.target.read_bytes()).hexdigest())
        with self.assertRaisesRegex(EvidenceError, 'hash mismatch'):
            observed.target_descriptor(dict(path=str(self.target), sha256='0' * 64))
        self.target.write_bytes(b'#!/bin/sh\nexit 1\n')
        self.nodes[101]['idversion'] = 11
        self.nodes[101]['executable_uuid'] = '34343434-3434-4343-8343-343434343434'
        with patch.object(observed, 'executable_path', return_value=str(self.target)):
            with self.assertRaisesRegex(EvidenceError, 'changed'): observer.observe(101, required=False)

    def test_exact_exec_predecessor_receipt_sequences_survive_parent_exec(self):
        observer = self.registered()
        self.nodes[102] = snapshot(102, 1100, 1000, birth=103, version=20, parent_version=10, ppid=101, pgid=555)
        observer.observe(102)
        self.nodes[103] = snapshot(103, 1200, 1100, birth=104, version=30, parent_version=20, ppid=1, pgid=666)
        # Parent is observed execing before the child's first observation. The
        # old actual parent idversion20 receipt must remain the edge witness.
        self.nodes[102]['idversion'] = 21
        self.nodes[102]['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
        observer.observe(102); observer.observe(103)
        writer = observer.value['writers']['1200']
        chain = [observer.value['observations'][sequence - 1]['snapshot'] for sequence in writer['lineage_observation_sequences']]
        self.assertEqual([node['idversion'] for node in chain], [10, 20, 30])
        value = self.record_now(); value['observation_session']['writers']['1200']['lineage_observation_sequences'][1] = 3
        self.save(value)
        with self.assertRaisesRegex(EvidenceError, 'predecessor observation'): self.record_now()

    def test_worker_samples_continuously_while_control_pipe_idle(self):
        fake = Mock(); fake.value = {'state': 'observing'}
        with patch.object(worker, '_environment_ledger', return_value=(Mock(), self.attempt)), \
             patch.object(worker, 'Observer', return_value=fake), \
             patch.object(worker, 'validate_control_fd'), \
             patch.object(worker.os, 'set_blocking'), patch.object(worker.os, 'close'), \
             patch.object(worker.os, 'read', return_value=b''), patch.object(worker.os, 'write'), \
             patch.object(worker.select, 'select', side_effect=[([], [], [])] * 5 + [([3], [], [])]):
            self.assertEqual(worker.run(99, 3, 4, self.working), 1)
        self.assertEqual(fake.sample.call_count, 5)
        self.assertIn('EOF', fake.fail.call_args.args[0])

    def test_worker_bounded_oversize_eof_and_lost_ack(self):
        for chunks, message in (([b'x' * (observed.MAX_REQUEST + 1)], 'byte bound'),
                                ([b''], 'EOF'),
                                ([b'{"command":"close","timeout":1}\n'], 'lost ack'),
                                ([b'{"command":"prepare_cleanup","timeout":1}\n'], 'lost ack')):
            fake = Mock(); fake.value = {'state': 'observing'}; fake.request.return_value = {'closed': True}
            with patch.object(worker, '_environment_ledger', return_value=(Mock(), self.attempt)), \
                 patch.object(worker, 'Observer', return_value=fake), \
                 patch.object(worker, 'validate_control_fd'), \
                 patch.object(worker.os, 'set_blocking'), patch.object(worker.os, 'close'), \
                 patch.object(worker.os, 'read', side_effect=chunks), \
                 patch.object(worker.os, 'write', side_effect=BrokenPipeError('lost ack')), \
                 patch.object(worker.select, 'select', return_value=([3], [4], [])):
                self.assertEqual(worker.run(99, 3, 4, self.working), 1)
                self.assertTrue(fake.fail.call_args.kwargs['lost'])
                self.assertIn(message, fake.fail.call_args.args[0])


class ControlDescriptorTests(unittest.TestCase):
    def test_anonymous_stream_socketpair_and_pipe_accepted_without_closing_originals(self):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            worker.validate_control_fd(left.fileno()); worker.validate_control_fd(right.fileno())
            left.send(b'proof'); self.assertEqual(right.recv(5), b'proof')
        finally:
            left.close(); right.close()
        read_fd, write_fd = os.pipe()
        try:
            worker.validate_control_fd(read_fd); worker.validate_control_fd(write_fd)
            os.write(write_fd, b'x'); self.assertEqual(os.read(read_fd, 1), b'x')
        finally:
            os.close(read_fd); os.close(write_fd)

    def test_regular_file_named_fifo_named_socket_and_datagram_rejected(self):
        with tempfile.TemporaryDirectory(prefix='sdd-control-fixture-') as temp:
            path = Path(temp) / 'regular'; path.write_text('private')
            with path.open('rb') as handle:
                with self.assertRaises(EvidenceError): worker.validate_control_fd(handle.fileno())
            fifo = Path(temp) / 'named-fifo'; os.mkfifo(fifo)
            descriptor = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            try:
                with self.assertRaisesRegex(EvidenceError, 'named'): worker.validate_control_fd(descriptor)
            finally:
                os.close(descriptor)
            path = str(Path(temp) / 'named-socket')
            server, client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM), socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            peer = None
            try:
                server.bind(path); server.listen(1); client.connect(path); peer, _ = server.accept()
                with self.assertRaisesRegex(EvidenceError, 'anonymous'): worker.validate_control_fd(client.fileno())
            finally:
                if peer: peer.close()
                client.close(); server.close()
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                with self.assertRaisesRegex(EvidenceError, 'SOCK_STREAM'): worker.validate_control_fd(left.fileno())
            finally:
                left.close(); right.close()


@unittest.skipUnless(sys.platform == 'darwin', 'Darwin native child enumeration')
class NativeChildEnumerationTests(unittest.TestCase):
    def test_actual_direct_owned_child_is_enumerated_and_reaped(self):
        child = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(10)'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.assertIn(child.pid, observed.child_pids(os.getpid()))
            witness = native.read_snapshot(child.pid, include_zombie=True)
            self.assertEqual(witness['current_ppid'], os.getpid())
        finally:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=3)
        self.assertIsNotNone(child.poll())
        self.assertIsNone(native.read_snapshot(child.pid, include_zombie=True))


if __name__ == '__main__': unittest.main()
