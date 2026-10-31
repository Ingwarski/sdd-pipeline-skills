"""Isolated SDK registry fixtures: no shared ledger, browser, provider or signals."""
import copy
import ctypes
import errno
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import stat
import sys
import tempfile
import threading
import time
import select
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


@unittest.skipUnless(os.name == 'posix', 'Registry integration requires real POSIX 0700 roots and directory-FD nofollow operations')
class RegistryTests(unittest.TestCase):
    # Allow real collector and ledger work to reach the semantic assertion on
    # busy CI. This is a deadline, not a sleep; ready operations return early.
    # Deliberately short generic failure/deadline probes keep their own limits.
    SEMANTIC_TIMEOUT = 3

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sdd-observed-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'output'; self.output.mkdir()
        self.policy = load_defaults(); self.policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider='local')
        self.ledger = Accounting(self.root / 'machine/ledger.sqlite', self.policy['project_id'], self.policy)
        # Close before TemporaryDirectory even if the rest of setUp fails.
        self.addCleanup(self.ledger.close)
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
                        patch.object(observed.os, 'getsid', return_value=100, create=True),
                        patch.object(runtime, 'managed_group_identity', return_value=self.membership),
                        patch.object(observed.process_identity, 'identity', side_effect=self.identity),
                        patch.object(observed.process_identity, 'state', return_value='alive'),
                        patch.object(observed.native, 'read_snapshot', side_effect=self.native),
                        patch.object(observed, 'executable_path', side_effect=lambda pid: '/fixture/node' if pid == 99 else '/fixture/python'),
                        patch.object(observed, 'candidate_pids', side_effect=lambda: tuple(self.nodes)),
                        patch.object(observed, 'child_pids', return_value=()),
                        patch.object(observed, '_no_handles')]
        # Only this fixture emulates Darwin OS hooks; runtime platform checks stay real.
        self.fixture_uid = self.root.stat().st_uid
        uid_hook = patch.object(observed.os, 'geteuid', return_value=self.fixture_uid, create=True)
        uid_hook.start(); self.addCleanup(uid_hook.stop)
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)
        self.created = []
        self.observer = None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.observer is not None and hasattr(self.observer, '_sampler'):
            try:
                self.observer.shutdown_sampler()
            except EvidenceError:
                pass
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

    def registered_target(self, *, scoped=False):
        observer = self.arm()
        allocation = observer.allocate('target profile', 4096); self.created.append(Path(allocation['path']))
        target = (self.root / 'package' if scoped else self.root) / 'Fixture.app' / 'Contents' / 'MacOS' / 'Fixture'
        target.parent.mkdir(parents=True); target.write_bytes(b'#!/bin/sh\nexit 0\n'); target.chmod(0o700)
        declaration = (dict(path=str(target), sha256=observed.hashlib.sha256(target.read_bytes()).hexdigest(),
                            observation_scope=str(target.parents[3])) if scoped else str(target))
        observer.request(dict(command='register_root', pid=101, expected_identity=self.browser['identity'],
                              expected_executable='/fixture/python', writable_root_refs=[allocation['ref']],
                              expected_target_executable=declaration))
        self.target = target
        self.scope = target.parents[3] if scoped else target.parents[2]
        return observer

    def test_v2_scope_exact_parent_pin_and_legacy_descriptor_shapes(self):
        observer = self.registered_target(scoped=True)
        target = observer.value['roots']['1000']['target_executable']
        self.assertEqual(target['version'], 2)
        self.assertEqual(target['scope'], str(self.scope))
        self.assertEqual(target['observation_scope'], dict(path=str(self.scope), identity=list(runtime.directory_identity(self.scope)), uid=self.fixture_uid))
        legacy = observed.target_descriptor(str(self.target))
        declared = observed.target_descriptor(dict(path=str(self.target), sha256=legacy['sha256']))
        self.assertEqual(legacy, declared)
        self.assertEqual(set(legacy), {'path', 'sha256', 'size', 'identity', 'mtime_ns', 'ctime_ns', 'scope'})
        self.assertEqual(legacy['scope'], str(self.target.parents[2]))

    def test_v2_scope_rejects_wrong_global_alias_shared_and_denied_paths(self):
        self.registered_target(scoped=True)
        declaration = dict(path=str(self.target), sha256=observed.hashlib.sha256(self.target.read_bytes()).hexdigest())
        link = self.root / 'scope-link'; link.symlink_to(self.scope, target_is_directory=True)
        try:
            for scope in (self.scope.parent, self.target.parents[2], self.root / 'sibling', Path('/'), Path.home(),
                          Path(tempfile.gettempdir()), Path('/tmp'), link, str(self.scope) + '/.', str(self.scope) + '/../package', '\x00'):
                with self.subTest(scope=str(scope)), self.assertRaises((EvidenceError, OSError)):
                    observed.target_descriptor({**declaration, 'observation_scope': str(scope)})
        finally: link.unlink()
        plain = self.root / 'plain'; plain.write_bytes(b'plain'); plain.chmod(0o700)
        with self.assertRaises(EvidenceError): observed.target_descriptor(dict(path=str(plain), sha256='a' * 64, observation_scope=str(self.root)))
        self.scope.chmod(0o777)
        try:
            with self.assertRaisesRegex(EvidenceError, 'non-shared'): observed._scope_pin(str(self.scope))
        finally: self.scope.chmod(0o700)
        with patch.object(observed.os, 'open', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError): observed._scope_pin(str(self.scope))
        with patch.object(observed.os, 'geteuid', return_value=self.fixture_uid + 1):
            with self.assertRaises(EvidenceError): observed._scope_pin(str(self.scope))
        for digest in (None, 1, 'bad', '0' * 64):
            with self.subTest(digest=digest), self.assertRaises(EvidenceError):
                observed.target_descriptor({**declaration, 'sha256': digest, 'observation_scope': str(self.scope)})
        for path in (Path('/'), Path.home(), Path(tempfile.gettempdir()), Path('/tmp'), self.target):
            with self.subTest(path=str(path)), self.assertRaises(EvidenceError): observed._scope_pin(str(path))
        capabilities = Mock(spec=['geteuid']); capabilities.geteuid.return_value = self.fixture_uid
        with patch.object(observed, 'os', capabilities):
            with self.assertRaisesRegex(EvidenceError, 'unsupported'): observed._scope_pin(str(self.scope))

    @contextmanager
    def replaced_scope(self):
        saved = self.scope.with_name(self.scope.name + '-saved')
        self.scope.rename(saved); self.scope.mkdir(mode=0o700)
        (saved / 'Fixture.app').rename(self.scope / 'Fixture.app')
        try: yield
        finally:
            (self.scope / 'Fixture.app').rename(saved / 'Fixture.app')
            self.scope.rmdir(); saved.rename(self.scope)

    def test_v2_scope_replacement_blocks_census_but_history_stays_readable(self):
        observer = self.registered_target(scoped=True)
        target = observer.value['roots']['1000']['target_executable']
        with self.replaced_scope():
            observed.validate_session(self.record_now()['observation_session'])
            with self.assertRaisesRegex(EvidenceError, 'scope'): observed.verify_target(target)
            with self.assertRaises(EvidenceError): observer.sample(force_census=True)
        def census(): self.scope.chmod(0o777); return ()
        with patch.object(observed, 'candidate_pids', side_effect=census):
            try:
                with self.assertRaises(EvidenceError): observer.sample(force_census=True)
            finally: self.scope.chmod(0o700)

    def test_v2_scope_prepare_close_and_all_terminal_consumers_recheck(self):
        observer = self.registered_target(scoped=True); self.nodes.pop(101)
        with patch.object(observed, '_no_handles', side_effect=lambda *args, **kwargs: self.scope.chmod(0o777)):
            try:
                with self.assertRaises(EvidenceError): observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
            finally: self.scope.chmod(0o700)
        observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
        self.scope.chmod(0o777)
        try:
            with self.assertRaises(EvidenceError): observer.close(.02)
        finally: self.scope.chmod(0o700)
        observer.close(self.SEMANTIC_TIMEOUT)
        self.scope.chmod(0o777)
        try:
            value = self.record_now(); self.assertEqual(value['observation_session']['state'], 'closed')
            value['status'] = 'terminal'; self.save(value)
            self.assertTrue(any('scope' in item for item in observed.disposition_problems(value, ledger=self.ledger)))
            self.assertTrue(producer.recover_producers(self.ledger, dry_run=True)['incomplete'])
            with self.assertRaises(EvidenceError): quarantine.original_state(self.ledger, self.attempt)
        finally: self.scope.chmod(0o700)

    def test_v2_scope_sibling_orphan_stays_pending_after_absence(self):
        observer = self.registered_target(scoped=True)
        self.nodes[102] = snapshot(102, 1100, 9999, birth=105, ppid=1, pgid=555)
        sibling = str(self.scope / 'Sibling.app' / 'Contents/MacOS/Service')
        with patch.object(observed, 'executable_path', side_effect=lambda pid: sibling if pid == 102 else '/fixture/node' if pid == 99 else '/fixture/python'):
            observer.sample(force_census=True)
        self.assertIn('pid:102', observer.value['pending']); self.assertNotIn('1100', observer.value['writers'])
        self.nodes.pop(102); self.nodes.pop(101)
        with self.assertRaises(EvidenceError): observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)

    def test_v2_scope_old_unrelated_complete_sibling_ancestry_excludes(self):
        observer = self.registered_target(scoped=True)
        self.nodes[500] = snapshot(500, 5000, 9999, birth=90, version=10, parent_version=9, ppid=1, pgid=555)
        self.nodes[102] = snapshot(102, 1100, 5000, birth=105, parent_version=10, ppid=500, pgid=555)
        sibling = str(self.scope / 'Sibling.app' / 'Contents/MacOS/Service')
        with patch.object(observed, 'executable_path', side_effect=lambda pid: sibling if pid in (102, 500) else '/fixture/node' if pid == 99 else '/fixture/python'):
            observer.sample(force_census=True)
        self.assertIn('1100', observer.value['excluded_candidates'])
        self.assertNotIn('pid:102', observer.value['pending'])
        observed.validate_session(self.record_now()['observation_session'])

    def test_v2_scope_file_pin_tamper_and_registration_ack_replacement_reject(self):
        observer = self.registered_target(scoped=True)
        original = self.record_now()
        for field in ('version', 'observation_scope', 'scope', 'uid', 'device', 'inode'):
            changed = copy.deepcopy(original); target = changed['observation_session']['roots']['1000']['target_executable']
            if field in ('version', 'observation_scope'): target.pop(field)
            elif field == 'scope': target['scope'] = str(self.scope.parent)
            elif field == 'uid': target['observation_scope']['uid'] += 1
            else: target['observation_scope']['identity'][0 if field == 'device' else 1] += 1
            if field in ('uid', 'device', 'inode'):
                observed.validate_session(changed['observation_session'])  # Historical pins remain auditable.
                with self.assertRaises(EvidenceError): observed.verify_target(target)
            else:
                with self.assertRaises(EvidenceError): observed.validate_session(changed['observation_session'])
        self.save(original)
        # A source pin is also checked immediately before a clean registration ACK.
        self.nodes[103] = snapshot(103, 1300, 900, birth=105)
        allocation = observer.allocate('second source-bound profile', 4096); self.created.append(Path(allocation['path']))
        original_add = observer._sampler.add_root
        def changed_scope(*args, **kwargs):
            watermark = original_add(*args, **kwargs); self.scope.chmod(0o777); return watermark
        with patch.object(observer._sampler, 'add_root', side_effect=changed_scope):
            try:
                with self.assertRaises(EvidenceError): observer.register_root(103, self.nodes[103]['identity'], '/fixture/python', [allocation['ref']],
                    dict(path=str(self.target), sha256=observed.hashlib.sha256(self.target.read_bytes()).hexdigest(), observation_scope=str(self.scope)))
            finally: self.scope.chmod(0o700)
        self.assertEqual(observer.value['state'], 'failed')

    def test_image_opt_in_forces_new_durable_full_sequence_and_exact_schema(self):
        observer = self.registered_target(scoped=True)
        self.assertEqual(set(observer.request(dict(command='observe_pid', pid=101))), {'associated'})
        previous = observer.value['sequence']
        first = observer.request(dict(command='observe_pid', pid=101, include_image=True))
        image = first['image']
        self.assertTrue(first['associated']); self.assertFalse(image['target_match'])
        self.assertEqual(set(image), {'version', 'session_id', 'root', 'observation_sequence', 'capture_sequence', 'identity',
            'unique_id', 'boot_uuid', 'uid', 'status', 'idversion', 'executable_uuid', 'executable', 'target_sha256', 'target_match'})
        self.assertGreater(image['observation_sequence'], previous)
        self.assertEqual(self.record_now()['observation_session']['observations'][image['observation_sequence'] - 1]['executable'], image['executable'])
        self.assertEqual(image['target_sha256'], observed.hashlib.sha256(self.target.read_bytes()).hexdigest())
        second = observer.request(dict(command='observe_pid', pid=101, include_image=True))['image']
        self.assertGreater(second['observation_sequence'], image['observation_sequence'])
        self.assertGreater(second['capture_sequence'], image['capture_sequence'])
        self.nodes[101]['idversion'] += 1
        self.nodes[101]['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
        with patch.object(observed, 'executable_path', side_effect=lambda pid: str(self.target) if pid == 101 else '/fixture/node' if pid == 99 else '/fixture/python'):
            matched = observer.request(dict(command='observe_pid', pid=101, include_image=True))['image']
        self.assertTrue(matched['target_match']); self.assertEqual(matched['executable'], str(self.target))

    def test_forced_root_image_reprojects_existing_descendants_without_mutating_observations(self):
        observer = self.registered_target()
        self.nodes[102] = snapshot(102, 1100, 1000, birth=103, version=20, parent_version=10, ppid=101, pgid=555)
        self.nodes[103] = snapshot(103, 1200, 1100, birth=104, version=30, parent_version=20, ppid=1, pgid=666)
        self.assertTrue(observer.observe(102)); self.assertTrue(observer.observe(103))
        prefix = copy.deepcopy(observer.value['observations'])
        leaf_sequences = {key: writer['observation_sequence'] for key, writer in observer.value['writers'].items()}
        for _ in range(2):
            image = observer.request(dict(command='observe_pid', pid=101, include_image=True))['image']
            self.assertGreater(image['observation_sequence'], len(prefix))
            self.assertEqual(observer.value['observations'][:len(prefix)], prefix)
            record = self.record_now(); session = record['observation_session']
            observed.validate_registry(record)
            for key, writer in session['writers'].items():
                self.assertEqual(writer['observation_sequence'], leaf_sequences[key])
                self.assertEqual(writer['lineage_observation_sequences'], observed.exact_chain_sequences(session, '1000', leaf_sequences[key]))
                self.assertEqual(writer['lineage_observation_sequences'][0], image['observation_sequence'])
                self.assertEqual(writer['authority'], observed.AUTHORITY)
        # Ordinary same-epoch parent changes require the same reprojection too.
        self.nodes[102]['pgid'] = 556; observer.observe(102)
        session = self.record_now()['observation_session']
        grandchild = session['writers']['1200']
        self.assertEqual(grandchild['lineage_observation_sequences'], observed.exact_chain_sequences(session, '1000', grandchild['observation_sequence']))
        self.assertEqual(observer.value['observations'][:len(prefix)], prefix)
        for pid in (101, 102, 103): self.nodes.pop(pid)
        observer.prepare_cleanup(self.SEMANTIC_TIMEOUT); observer.close(self.SEMANTIC_TIMEOUT)
        record = self.record_now(); observed.validate_registry(record)
        self.assertEqual(observed.disposition_problems(record, ledger=self.ledger), [])
        runtime.update(self.ledger, self.attempt, lambda value: value.update(status='terminal'))
        with patch.object(observed.process_identity, 'state', return_value='gone'):
            # A completed fixture is not a quarantinable failed accounting gap;
            # reaching this guard proves its shared observed-writer read passed.
            with self.assertRaisesRegex(EvidenceError, 'original failed accounting binding'):
                quarantine.original_state(self.ledger, self.attempt)
        self.ledger.settle(self.reservation, 0, 0)
        self.assertFalse(producer.recover_producers(self.ledger, dry_run=True)['incomplete'])

    def test_image_legacy_no_target_and_strict_nonroot_phase_flag_and_witness_rejection(self):
        observer = self.registered()
        image = observer.request(dict(command='observe_pid', pid=101, include_image=True))['image']
        self.assertIsNone(image['target_sha256']); self.assertFalse(image['target_match'])
        for value in (False, 1, 'true', None):
            with self.assertRaises(EvidenceError): observer.request(dict(command='observe_pid', pid=101, include_image=value))
        for extra in ('snapshot', 'identity', 'image', 'capture_sequence'):
            with self.assertRaises(EvidenceError): observer.request(dict(command='observe_pid', pid=101, include_image=True, **{extra: {}}))
        with patch.object(observer._sampler, 'observe_pid') as capture:
            with self.assertRaises(EvidenceError): observer.request(dict(command='observe_pid', pid=102, include_image=True))
            capture.assert_not_called()
        self.nodes.pop(101); observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
        with self.assertRaises(EvidenceError): observer.request(dict(command='observe_pid', pid=101, include_image=True))
        observer.close(self.SEMANTIC_TIMEOUT)
        with self.assertRaises(EvidenceError): observer.request(dict(command='observe_pid', pid=101, include_image=True))

    def test_image_missing_or_partial_capture_never_uses_old_full(self):
        observer = self.registered()
        durable = observer.value['native_sampler']['durable_sequence']
        for snapshot_value in (None, self.native(101)):
            with patch.object(observer._sampler, 'observe_pid', return_value=(durable, snapshot_value, None)):
                self.assertIsNone(observer.request(dict(command='observe_pid', pid=101, include_image=True))['image'])
        with patch.object(observed, 'executable_path', side_effect=EvidenceError('unsupported/denied native path')):
            self.assertIsNone(observer.request(dict(command='observe_pid', pid=101, include_image=True))['image'])
        self.assertTrue(observer.value['native_sampler']['unresolved'])
        self.nodes.pop(101)
        with self.assertRaises(EvidenceError): observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)

    def test_image_zombie_and_esrch_are_not_complete_images(self):
        observer = self.registered()
        self.nodes[101]['status'] = 'zombie'; self.nodes[101]['query']['native_status'] = 5
        self.assertIsNone(observer.request(dict(command='observe_pid', pid=101, include_image=True))['image'])
        self.nodes.pop(101)
        reply = observer.request(dict(command='observe_pid', pid=101, include_image=True))
        self.assertEqual(reply, dict(associated=False, image=None))

    def test_image_mixed_root_capture_never_falls_back_to_later_or_prior_full(self):
        observer = self.registered_target()
        original_collect = observer._sampler._collect
        def at_forced_capture(pid, **kwargs):
            if kwargs.get('force_ticket') is not None:
                self.nodes[101]['idversion'] += 1  # Mixed raw new epoch / old UUID, exactly at this request.
            return original_collect(pid, **kwargs)
        def changed_image(pid):
            if pid == 101:
                self.nodes[101]['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
                return str(self.target)
            return '/fixture/node' if pid == 99 else '/fixture/python'
        with patch.object(observer._sampler, '_collect', side_effect=at_forced_capture), \
             patch.object(observed, 'executable_path', side_effect=changed_image):
            self.assertIsNone(observer.request(dict(command='observe_pid', pid=101, include_image=True))['image'])
        self.assertTrue(observer.value['pending'])
        self.assertTrue(observer.value['native_sampler']['helper_diagnostics'])

    def test_image_root_epoch_regression_fails_without_success_projection(self):
        observer = self.registered()
        self.nodes[101]['idversion'] -= 1
        with self.assertRaises(EvidenceError): observer.request(dict(command='observe_pid', pid=101, include_image=True))
        self.assertTrue(observer._drain_lost)

    def test_image_arming_phase_is_rejected_before_collector_request(self):
        observer = self.arm()
        with patch.object(observer._sampler, 'observe_pid') as capture:
            with self.assertRaises(EvidenceError): observer.request(dict(command='observe_pid', pid=101, include_image=True))
            capture.assert_not_called()

    def test_image_wrong_native_key_or_unflushed_receipt_cannot_use_prior_full(self):
        observer = self.registered()
        watermark = observer.value['native_sampler']['durable_sequence']
        for field in ('birth', 'unique_id', 'uid', 'boot_uuid', 'parent_version'):
            node = self.native(101)
            if field == 'birth': node['identity']['created']['microseconds'] += 1
            elif field == 'unique_id': node[field] = '9999'
            elif field == 'uid': node[field] += 1
            elif field == 'boot_uuid': node[field] = '56565656-5656-4565-8565-565656565656'
            else: node['original_parent_idversion'] += 1
            with patch.object(observer._sampler, 'observe_pid', return_value=(watermark, node, watermark)):
                self.assertIsNone(observer.request(dict(command='observe_pid', pid=101, include_image=True))['image'])
        with patch.object(observer._sampler, 'observe_pid', return_value=(watermark + 1, self.native(101), watermark + 1)):
            with self.assertRaisesRegex(EvidenceError, 'unflushed tail'):
                observer.request(dict(command='observe_pid', pid=101, include_image=True))

    def test_image_oversize_actual_path_latches_unflushed_history(self):
        observer = self.registered()
        with patch.object(observed, 'executable_path', return_value='/' + 'a' * 4096):
            with self.assertRaises(EvidenceError): observer.request(dict(command='observe_pid', pid=101, include_image=True))
        self.assertTrue(observer._drain_lost)

    def test_image_forced_bound_source_and_scope_fail_closed(self):
        observer = self.registered_target(scoped=True)
        with patch.object(observed, 'sources', return_value={key: 'b' * 64 for key in observed.SOURCE_FILES}):
            with self.assertRaises(EvidenceError): observer.request(dict(command='observe_pid', pid=101, include_image=True))
        with self.replaced_scope():
            with self.assertRaises(EvidenceError): observer.request(dict(command='observe_pid', pid=101, include_image=True))
        with patch.object(observed, 'MAX_OBSERVATIONS', observer.value['sequence']):
            with self.assertRaises(EvidenceError): observer.request(dict(command='observe_pid', pid=101, include_image=True))
        self.assertTrue(observer._drain_lost)

    def test_image_control_reply_bound_is_enforced_after_durable_capture(self):
        observer = self.registered()
        with patch.object(observed, 'MAX_REQUEST', 128):
            with self.assertRaisesRegex(EvidenceError, 'reply exceeds'):
                observer.request(dict(command='observe_pid', pid=101, include_image=True))

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
        updated = copy.deepcopy(self.nodes[101])
        updated.update(idversion=11, executable_uuid='34343434-3434-4343-8343-343434343434')
        with patch.object(observed, 'executable_path', return_value='/fixture/Chrome'):
            self.nodes[101] = updated  # Publish one complete native epoch after its path mock is active.
            self.assertTrue(observer.observe(101, required=True))
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
        result = observer.close(self.SEMANTIC_TIMEOUT)
        self.assertTrue(result['closed'])
        self.assertFalse(observed.disposition_problems(self.record_now(), ledger=self.ledger))
        observed._no_handles.assert_called()
        self.assertEqual(observer.value['closure']['sequence'], 1)

    def test_closed_report_replay_is_noop_but_fresh_reuse_blocks(self):
        observer = self.registered(); del self.nodes[101]; observer.close(self.SEMANTIC_TIMEOUT)
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
            updated = copy.deepcopy(self.nodes[101]); updated['idversion'] = 11
            self.nodes[101] = updated
            with self.assertRaisesRegex(EvidenceError, 'bound'): observer.observe(101, required=True)
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
        del self.nodes[101]; observer.close(self.SEMANTIC_TIMEOUT)
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
        first = self.registered(); del self.nodes[101]; first.close(self.SEMANTIC_TIMEOUT)
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
            del self.nodes[202]; second.close(self.SEMANTIC_TIMEOUT)
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
        del self.nodes[101]; observer.close(self.SEMANTIC_TIMEOUT)
        with patch.object(observed, 'sources', return_value=changed):
            self.assertEqual(self.record_now()['observation_session']['source_sha256'], before)
            self.assertFalse(observed.disposition_problems(self.record_now(), ledger=self.ledger))
        value = self.record_now(); value['observation_session']['capability'] = 'unknown-older-capability'
        self.save(value)
        with self.assertRaises(EvidenceError): self.record_now()

    def test_cumulative_session_bound_and_immutable_history_digest(self):
        observer = self.registered(); del self.nodes[101]; observer.close(self.SEMANTIC_TIMEOUT)
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
                reply = observer.request(dict(command='prepare_cleanup', timeout=self.SEMANTIC_TIMEOUT))
                self.assertEqual(reply, dict(ready=True, root_refs=sorted(observer.value['working_roots']), sequence=1, closed=False))
                self.assertEqual(observer.value['state'], 'closing')
                self.assertTrue(observer.value['cleanup_barrier']['valid'])
                self.assertIsNone(observer.value['closure'])
                self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))
                with self.assertRaisesRegex(EvidenceError, 'payload'): observer.close(self.SEMANTIC_TIMEOUT)
                with patch.object(observed, '_bounded_usage', side_effect=AssertionError('no filesystem walk while caller cleans')):
                    payload.unlink()
                    observer.sample(force_census=True)
                    self.assertTrue(observer.close(self.SEMANTIC_TIMEOUT)['closed'])
                self.assertFalse(observed.disposition_problems(self.record_now(), ledger=self.ledger))
        finally:
            if payload.exists(): payload.unlink()

    def test_prepare_ack_then_death_or_guardian_stop_never_closes(self):
        observer = self.registered(); del self.nodes[101]
        observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
        observer.fail('EOF during caller content cleanup', lost=True)
        session = self.record_now()['observation_session']
        self.assertFalse(session['cleanup_barrier']['valid'])
        self.assertEqual(session['state'], 'failed')
        self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))
        with self.assertRaises(EvidenceError): observer.close(.02)

    def test_guardian_stop_after_prepare_latches_valid_structural_failure(self):
        observer = self.registered(); del self.nodes[101]; observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
        runtime.stop_registered(self.ledger, self.attempt)
        value = self.record_now()
        self.assertFalse(value['observation_session']['cleanup_barrier']['valid'])
        self.assertTrue(value['observation_session']['lost_history'])

    def test_closing_refuses_new_roots_allocations_and_registration(self):
        observer = self.registered(); del self.nodes[101]; observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
        with self.assertRaisesRegex(EvidenceError, 'ownership changed'): observer.allocate('late root', 1)
        with self.assertRaises(EvidenceError):
            observer.register_root(101, self.browser['identity'], '/fixture/python', [next(iter(observer.value['working_roots']))])
        self.assertEqual(observer.value['state'], 'closing')

    def test_prepare_and_close_reject_replaced_linked_roots_and_open_handles(self):
        observer = self.registered(); del self.nodes[101]
        path = self.created[0]
        with self.real_handle_checks(result=(0, b'123\n', b'')):
            with self.assertRaisesRegex(EvidenceError, 'handles'): observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
        with self.real_handle_checks():
            observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
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
                with self.assertRaisesRegex(EvidenceError, 'handles'): observer.close(self.SEMANTIC_TIMEOUT)
            self.assertTrue(observer.close(self.SEMANTIC_TIMEOUT)['closed'])

    def test_new_postbarrier_writer_invalidates_precleanup_receipt(self):
        observer = self.registered(); del self.nodes[101]; observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
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
            with self.assertRaisesRegex(EvidenceError, 'pending'): observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
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
        observer = self.registered_target(); del self.nodes[101]; observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
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
        updated = copy.deepcopy(self.nodes[101])
        updated.update(idversion=11, executable_uuid='34343434-3434-4343-8343-343434343434')
        with patch.object(observed, 'executable_path', return_value=str(self.target)):
            self.target.write_bytes(b'#!/bin/sh\nexit 1\n')
            self.nodes[101] = updated
            with self.assertRaisesRegex(EvidenceError, 'changed'): observer.observe(101, required=True)

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

    def test_ready_capture_fence_is_durable_before_root_ack(self):
        observer = self.registered()
        self.assertTrue(observer._sampler._thread.is_alive())
        self.assertEqual(observer.value['native_sampler']['roots'], ['1000'])
        self.assertGreaterEqual(observer.value['native_sampler']['durable_sequence'], 1)
        self.assertEqual(observer.value['native_sampler']['state'], 'running')

    def test_failed_historical_v2_source_hashes_remain_readable_not_reopened(self):
        observer = self.registered(); observer.fail('original failure', lost=True)
        original = self.record_now(); changed = {key: 'b' * 64 for key in observed.SOURCE_FILES}
        with patch.object(observed, 'sources', return_value=changed):
            self.assertEqual(self.record_now(), original)
            self.assertTrue(observed.disposition_problems(original, ledger=self.ledger))
            with self.assertRaisesRegex(EvidenceError, 'prior closure'):
                observed.Observer(self.ledger, self.attempt, 99, self.working)

    def test_unflushed_capture_loss_and_incomplete_receipts_cannot_close(self):
        observer = self.registered()
        self.nodes[102] = snapshot(102, 1100, 1000, birth=103, parent_version=10, ppid=100)
        with patch.object(observed, 'executable_path', side_effect=EvidenceError('controlled missed path')):
            observer._sampler.observe_pid(102)
        observer._drain_native()
        self.assertTrue(observer.value['native_sampler']['unresolved'])
        self.nodes.pop(102); self.nodes.pop(101)
        with self.assertRaisesRegex(EvidenceError, 'pending'): observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
        self.assertTrue(observed.disposition_problems(self.record_now(), ledger=self.ledger))

    def test_lost_capture_tail_preserves_incomplete_journal(self):
        observer = self.registered()
        self.nodes[102] = snapshot(102, 1100, 1000, birth=103, parent_version=10, ppid=100)
        watermark, _ = observer._sampler.observe_pid(102)
        with patch.object(observer._sampler, 'take', return_value=[]):
            with self.assertRaisesRegex(EvidenceError, 'unflushed tail'): observer._drain_native(through=watermark)
        observer.fail('lost capture tail', lost=True)
        self.assertTrue(self.record_now()['observation_session']['lost_history'])
        with self.assertRaisesRegex(EvidenceError, 'lost unflushed'): observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)

    def typed_helper_exec(self, observer, pid=102, before_version=718685, after_version=718686, *, parent='1000'):
        self.nodes[pid] = snapshot(pid, 10000 + pid, parent, birth=103, version=before_version,
                                   parent_version=10, ppid=101, pgid=555)
        original_uuid = self.nodes[pid]['executable_uuid']
        def executable(target):
            if target == pid:
                if self.nodes[pid]['idversion'] == before_version:
                    self.nodes[pid]['idversion'] = after_version
                    self.nodes[pid]['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
                return '/fixture/complete-helper'
            return '/fixture/node' if target == 99 else '/fixture/python'
        with patch.object(observed, 'executable_path', side_effect=executable):
            observer.observe(pid)
        return original_uuid

    def test_runtime_exec_epochs_qualify_only_new_typed_same_birth_witnesses(self):
        # Exact epoch pairs from runtime fixture2, replayed as isolated SDK
        # native calls. This does not repair that preserved failed session.
        observer = self.registered()
        for pid, before, after in ((102, 718685, 718686), (103, 718687, 718688)):
            old_uuid = self.typed_helper_exec(observer, pid, before, after)
            transition = next(item for item in observer.value['native_sampler']['exec_transitions']
                              if item['before']['identity']['pid'] == pid)
            self.assertEqual(transition['before']['executable_uuid'], old_uuid)
            self.assertEqual(transition['before']['idversion'], before)
            self.assertEqual(transition['after']['idversion'], after)
            self.assertEqual(transition['path_status'], 'unobserved_during_exec')
            self.assertIsNotNone(transition['resolution'])
            full = observer.value['observations'][transition['resolution']['observation_sequence'] - 1]
            self.assertEqual(full['snapshot']['idversion'], after)
            self.assertEqual(full['executable'], '/fixture/complete-helper')
            self.assertNotIn('executable', transition)  # No invented pre-exec path.
        self.assertFalse(observer.value['native_sampler']['unresolved'])
        self.assertFalse(observer.value['pending'])
        self.nodes.pop(101); self.nodes.pop(102); self.nodes.pop(103)
        self.assertTrue(observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)['ready'])
        self.assertTrue(observer.close(self.SEMANTIC_TIMEOUT)['closed'])
        self.assertFalse(observed.disposition_problems(self.record_now(), ledger=self.ledger))

    def test_typed_exec_resolution_rejects_wrong_birth_parent_uid_boot_or_epoch(self):
        observer = self.registered(); self.typed_helper_exec(observer)
        original = self.record_now()
        for field in ('identity', 'unique_id', 'original_parent_unique_id', 'original_parent_idversion', 'uid', 'boot_uuid', 'idversion'):
            changed = copy.deepcopy(original)
            before = changed['observation_session']['native_sampler']['exec_transitions'][0]['before']
            if field == 'identity': before[field]['created']['microseconds'] += 1
            elif field in ('uid', 'idversion', 'original_parent_idversion'): before[field] += 100
            elif field == 'boot_uuid': before[field] = '56565656-5656-4565-8565-565656565656'
            else: before[field] = '999999'
            self.save(changed)
            with self.subTest(field=field):
                with self.assertRaises(EvidenceError): self.record_now()
        self.save(original)
        changed = copy.deepcopy(original)
        changed['observation_session']['native_sampler']['exec_transitions'][0]['resolution']['observation_sequence'] = 1
        self.save(changed)
        with self.assertRaisesRegex(EvidenceError, 'exec transition resolution'): self.record_now()
        self.save(original)

    def test_missing_native_ancestry_does_not_resolve_typed_exec(self):
        observer = self.registered()
        self.typed_helper_exec(observer, parent='9999')
        transition = observer.value['native_sampler']['exec_transitions'][0]
        self.assertIsNone(transition['resolution'])
        self.assertIn('exec:' + str(transition['capture_sequence']), observer.value['pending'])
        self.assertFalse(observer.value['writers'])
        self.nodes.pop(101); self.nodes.pop(102)
        with self.assertRaisesRegex(EvidenceError, 'pending'): observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)

    def test_all_terminal_consumers_reject_unqualified_typed_exec(self):
        observer = self.registered(); self.typed_helper_exec(observer, parent='9999')
        runtime.update(self.ledger, self.attempt, lambda record: record.update(status='terminal'))
        recovered = producer.recover_producers(self.ledger, dry_run=True)
        self.assertTrue(recovered['incomplete'])
        self.assertTrue(recovered['actions'][0]['problems'])
        with self.assertRaisesRegex(EvidenceError, 'observed writer'): quarantine.original_state(self.ledger, self.attempt)
        # A forged closed flag or cleared pending map cannot bypass the shared
        # validator used by every runtime/recovery/quarantine reader.
        value = self.record_now(); session = value['observation_session']
        session['state'] = 'closed'; session['pending'] = {}
        session['closure'] = dict(sequence=session['sequence'], numeric_absent=True, roots_no_handles=True)
        session['native_sampler'].update(state='stopped', stopped_sequence=session['native_sampler']['durable_sequence'])
        self.save(value)
        with self.assertRaisesRegex(EvidenceError, 'pending obligation'): self.record_now()

    def test_generic_permission_failure_is_never_retyped_by_later_exec(self):
        observer = self.registered()
        self.nodes[102] = snapshot(102, 1100, 1000, birth=103, version=20, parent_version=10, ppid=101)
        def denied(pid):
            if pid == 102: raise EvidenceError('controlled permission failure')
            return '/fixture/python'
        with patch.object(observed, 'executable_path', side_effect=denied):
            observer.observe(102)
        self.nodes[102]['idversion'] = 21
        self.nodes[102]['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
        observer.observe(102)
        self.assertTrue(observer.value['native_sampler']['unresolved'])
        self.assertFalse(observer.value['native_sampler']['exec_transitions'])
        self.nodes.pop(101); self.nodes.pop(102)
        with self.assertRaisesRegex(EvidenceError, 'pending'): observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)

    def test_root_executable_lookup_failure_cannot_ack_or_release_go(self):
        observer = self.arm(); allocation = observer.allocate('held wrapper', 4096)
        self.created.append(Path(allocation['path']))
        def executable(pid):
            if pid == 101 and threading.current_thread().name == 'sdd-native-observation':
                raise EvidenceError('controlled held-root executable query failure')
            return '/fixture/node' if pid == 99 else '/fixture/python'
        with patch.object(observed, 'executable_path', side_effect=executable):
            with self.assertRaisesRegex(EvidenceError, 'root ACK refused'):
                observer.register_root(101, self.browser['identity'], '/fixture/python', [allocation['ref']])
        session = self.record_now()['observation_session']
        self.assertEqual(session['state'], 'failed')
        self.assertTrue(session['lost_history'])
        self.assertTrue(session['native_sampler']['unresolved'])
        self.assertIn('pid:101', session['pending'])

    def test_kernel_exec_pair_rejects_equal_backward_and_missing_native_birth(self):
        before = snapshot(102, 1100, 1000, birth=103, version=20, parent_version=10, ppid=101)
        after = copy.deepcopy(before); after['idversion'] = 21
        after['observed']['monotonic_ns'] = '1001'; after['observed']['wall_time_ns'] = '2000000000001'
        self.assertTrue(observed._exec_pair(before, after))
        self.assertFalse(observed._exec_pair(None, after))
        self.assertFalse(observed._exec_pair(before, None))
        after['idversion'] = 20; self.assertFalse(observed._exec_pair(before, after))
        after['idversion'] = 19; self.assertFalse(observed._exec_pair(before, after))

    def mixed_helper_boundary(self, observer, pid=102):
        old_uuid = '4c4c44c3-5555-3144-a137-125a1864d84f'
        new_uuid = '4c4c44f2-5555-3144-a199-123b8f619b55'
        self.nodes[pid] = snapshot(pid, 10000 + pid, 1000, birth=103, version=721350, parent_version=10, ppid=101, pgid=555)
        self.nodes[pid]['executable_uuid'] = old_uuid
        observer.observe(pid)
        def executable(target):
            if target == pid:
                if self.nodes[pid]['idversion'] == 721351:
                    self.nodes[pid]['executable_uuid'] = new_uuid
                return '/fixture/GPU'
            return '/fixture/node' if target == 99 else '/fixture/python'
        with patch.object(observed, 'executable_path', side_effect=executable):
            self.nodes[pid]['idversion'] = 721351  # Raw tuple still holds OLD UUID.
            observer.observe(pid)
        return next(item for item in observer.value['native_sampler']['helper_diagnostics'] if item['pid'] == pid)

    def path_gap(self, observer, pid=102, *, query_errno=errno.ESRCH, post='gone'):
        self.nodes[pid] = snapshot(pid, 20000 + pid, 1000, birth=103 + pid, version=721383, parent_version=10, ppid=101, pgid=555)
        observer.observe(pid)
        def unavailable(target):
            if target == pid:
                query = dict(version=1, api='libproc.proc_pidpath', stage='query', pid=pid, returned_size=0,
                             errno=query_errno, buffer_size=4096, outcome='unavailable', monotonic_ns=str(self.stamp))
                if post == 'gone': self.nodes.pop(pid, None)
                elif post == 'zombie':
                    self.nodes[pid]['status'] = 'zombie'; self.nodes[pid]['query']['native_status'] = 5
                raise observed._PathQueryError('controlled structured path gap', query)
            return '/fixture/node' if target == 99 else '/fixture/python'
        with patch.object(observed, 'executable_path', side_effect=unavailable):
            self.nodes[pid]['current_ppid'] = 1
            observer.observe(pid)
        return next(item for item in observer.value['native_sampler']['helper_diagnostics'] if item['pid'] == pid)

    def test_actual3_mixed_image_boundary_is_diagnostic_only_with_full_brackets(self):
        observer = self.registered(); diagnostic = self.mixed_helper_boundary(observer)
        self.assertEqual(diagnostic['raw']['idversion'], 721351)
        self.assertEqual(diagnostic['raw']['executable_uuid'], '4c4c44c3-5555-3144-a137-125a1864d84f')
        self.assertEqual(diagnostic['image_status'], 'nonqualifying')
        qualification = diagnostic['qualification']; self.assertIsNotNone(qualification)
        before = observer.value['observations'][qualification['before_observation_sequence'] - 1]
        after = observer.value['observations'][qualification['after_observation_sequence'] - 1]
        self.assertEqual(before['snapshot']['idversion'], 721350)
        self.assertEqual(after['snapshot']['idversion'], 721351)
        self.assertEqual(after['snapshot']['executable_uuid'], '4c4c44f2-5555-3144-a199-123b8f619b55')
        self.assertFalse(any(item['snapshot']['idversion'] == 721351 and item['snapshot']['executable_uuid'] == diagnostic['raw']['executable_uuid']
                             for item in observer.value['observations']))
        self.assertEqual(observer.graphs['1000']._nodes['10102']['executable_uuid'], after['snapshot']['executable_uuid'])
        self.nodes.pop(102); self.nodes.pop(101)
        observer.prepare_cleanup(self.SEMANTIC_TIMEOUT); self.assertTrue(observer.close(self.SEMANTIC_TIMEOUT)['closed'])

    def test_mixed_diagnostic_rejects_wrong_endpoint_identity_epoch_root_or_order(self):
        observer = self.registered(); self.mixed_helper_boundary(observer); original = self.record_now()
        for field in ('uuid', 'epoch', 'birth', 'parent', 'parent_epoch', 'uid', 'boot', 'status', 'order', 'before_ref', 'after_ref', 'root'):
            changed = copy.deepcopy(original); item = changed['observation_session']['native_sampler']['helper_diagnostics'][0]
            if field == 'uuid': item['raw']['executable_uuid'] = '56565656-5656-4565-8565-565656565656'
            elif field == 'epoch': item['raw']['idversion'] = 721350
            elif field == 'birth': item['raw']['identity']['created']['microseconds'] += 1
            elif field == 'parent': item['raw']['original_parent_unique_id'] = '9999'
            elif field == 'parent_epoch': item['raw']['original_parent_idversion'] += 1
            elif field == 'uid': item['raw']['uid'] += 1
            elif field == 'boot': item['raw']['boot_uuid'] = '56565656-5656-4565-8565-565656565656'
            elif field == 'status':
                item['raw']['status'] = 'zombie'; item['raw']['query']['native_status'] = 5
            elif field == 'order': item['raw']['observed']['monotonic_ns'] = '1'
            elif field == 'before_ref': item['qualification']['before_observation_sequence'] = None
            elif field == 'after_ref': item['qualification']['after_observation_sequence'] = item['qualification']['before_observation_sequence']
            else: item['qualification']['root'] = '9999'
            # Reach semantic qualification validation, not only byte integrity.
            changed['observation_session']['native_sampler']['helper_diagnostic_bindings'][str(item['capture_sequence'])] = observed._helper_raw_digest(item)
            self.save(changed)
            with self.subTest(field=field):
                with self.assertRaises(EvidenceError): self.record_now()
        self.save(original)

    def test_actual3_known_epoch_path_exit_gap_needs_structured_esrch_followup(self):
        observer = self.registered(); diagnostic = self.path_gap(observer)
        self.assertEqual(diagnostic['raw']['current_ppid'], 1)
        self.assertEqual(diagnostic['path_query']['errno'], errno.ESRCH)
        self.assertEqual(diagnostic['followup']['outcome'], 'numeric_esrch')
        self.assertEqual(diagnostic['qualification']['mode'], 'known_epoch_exit_gap')
        self.assertEqual(diagnostic['path_status'], 'unobserved')
        self.assertNotIn('executable', diagnostic)
        self.nodes.pop(101); observer.prepare_cleanup(self.SEMANTIC_TIMEOUT); observer.close(self.SEMANTIC_TIMEOUT)

    def test_known_zombie_path_gap_still_requires_numeric_absence(self):
        observer = self.registered(); diagnostic = self.path_gap(observer, post='zombie')
        self.assertIsNotNone(diagnostic['qualification'])
        self.assertEqual(diagnostic['followup']['snapshot']['status'], 'zombie')
        self.nodes.pop(101)
        with self.assertRaisesRegex(EvidenceError, 'numeric ESRCH'): observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
        self.nodes.pop(102); observer.prepare_cleanup(self.SEMANTIC_TIMEOUT); observer.close(self.SEMANTIC_TIMEOUT)

    def test_permitted_same_epoch_gap_requires_later_genuine_full_receipt(self):
        observer = self.registered(); diagnostic = self.path_gap(observer, post='alive')
        self.assertIsNone(diagnostic['qualification'])  # PPID1/alive is not exit proof.
        self.nodes[102]['pgid'] = 556  # A genuine later full same-epoch observation.
        observer.observe(102)
        diagnostic = observer.value['native_sampler']['helper_diagnostics'][0]
        self.assertEqual(diagnostic['qualification']['mode'], 'bounded_same_epoch_gap')
        self.assertIsNone(diagnostic['qualification']['before_observation_sequence'])
        self.nodes.pop(102); self.nodes.pop(101); observer.prepare_cleanup(self.SEMANTIC_TIMEOUT); observer.close(self.SEMANTIC_TIMEOUT)

    def test_path_gap_raw_zombie_cannot_regress_to_alive_even_with_rebound_digest(self):
        observer = self.registered(); self.path_gap(observer, post='alive')
        self.nodes[102]['pgid'] = 556
        observer.observe(102)
        value = self.record_now(); session = value['observation_session']
        diagnostic = session['native_sampler']['helper_diagnostics'][0]
        self.assertEqual(diagnostic['qualification']['mode'], 'bounded_same_epoch_gap')
        diagnostic['raw']['status'] = 'zombie'
        diagnostic['raw']['query']['native_status'] = 5
        session['native_sampler']['helper_diagnostic_bindings'][str(diagnostic['capture_sequence'])] = observed._helper_raw_digest(diagnostic)
        self.save(value)
        with self.assertRaises(EvidenceError): self.record_now()
        self.assertTrue(producer.recover_producers(self.ledger, dry_run=True)['incomplete'])
        with self.assertRaises(EvidenceError): quarantine.original_state(self.ledger, self.attempt)

    def test_permission_unknown_and_malformed_path_gaps_never_resolve_by_absence(self):
        observer = self.registered()
        for index, error in enumerate((errno.EPERM, errno.EACCES, 0, errno.EINVAL, errno.ENOTSUP)):
            diagnostic = self.path_gap(observer, pid=102 + index, query_errno=error)
            self.assertIsNone(diagnostic['qualification'])
        self.nodes.pop(101)
        with self.assertRaisesRegex(EvidenceError, 'pending'): observer.prepare_cleanup(self.SEMANTIC_TIMEOUT)
        value = self.record_now(); value['status'] = 'terminal'; self.save(value)
        self.assertTrue(producer.recover_producers(self.ledger, dry_run=True)['incomplete'])
        with self.assertRaisesRegex(EvidenceError, 'observed writer'): quarantine.original_state(self.ledger, self.attempt)

    def test_helper_diagnostic_cannot_masquerade_root_or_clear_unknown_followup(self):
        observer = self.registered(); self.path_gap(observer); original = self.record_now()
        for mode in ('root', 'unknown', 'wrong_epoch', 'wrong_birth', 'wrong_parent', 'wrong_uid', 'wrong_boot', 'wrong_uuid'):
            value = copy.deepcopy(original); diagnostic = value['observation_session']['native_sampler']['helper_diagnostics'][0]
            if mode == 'root': diagnostic['qualification']['before_observation_sequence'] = 1
            elif mode == 'unknown': diagnostic['followup'] = dict(outcome='unavailable', snapshot=None, problem='unsupported native query')
            else:
                raw = copy.deepcopy(diagnostic['raw']); raw['status'] = 'zombie'; raw['query']['native_status'] = 5
                raw['observed']['monotonic_ns'] = str(int(raw['observed']['monotonic_ns']) + 1)
                raw['observed']['wall_time_ns'] = str(int(raw['observed']['wall_time_ns']) + 1)
                if mode == 'wrong_epoch': raw['idversion'] += 1
                elif mode == 'wrong_birth': raw['identity']['created']['microseconds'] += 1
                elif mode == 'wrong_parent': raw['original_parent_unique_id'] = '9999'
                elif mode == 'wrong_uid': raw['uid'] += 1
                elif mode == 'wrong_boot': raw['boot_uuid'] = '45454545-4545-4545-8545-454545454545'
                else: raw['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
                diagnostic['followup'] = dict(outcome='snapshot', snapshot=raw, problem=None)
            value['observation_session']['native_sampler']['helper_diagnostic_bindings'][str(diagnostic['capture_sequence'])] = observed._helper_raw_digest(diagnostic)
            self.save(value)
            with self.subTest(mode=mode):
                with self.assertRaises(EvidenceError): self.record_now()
        self.save(original)

    def test_removed_raw_helper_receipts_or_bindings_are_rejected_by_all_readers(self):
        observer = self.registered(); self.path_gap(observer); self.nodes.pop(101)
        observer.prepare_cleanup(self.SEMANTIC_TIMEOUT); observer.close(self.SEMANTIC_TIMEOUT)
        original = self.record_now()
        for field in ('helper_diagnostics', 'helper_diagnostic_bindings'):
            value = copy.deepcopy(original)
            value['observation_session']['native_sampler'][field].clear()
            self.save(value)
            with self.subTest(field=field):
                with self.assertRaisesRegex(EvidenceError, 'diagnostic'): self.record_now()
                self.assertTrue(producer.recover_producers(self.ledger, dry_run=True)['incomplete'])
                with self.assertRaises(EvidenceError): quarantine.original_state(self.ledger, self.attempt)
        self.save(original)
        value = copy.deepcopy(original); value['observation_session']['closure']['helper_diagnostics_sha256'] = '0' * 64
        self.save(value)
        with self.assertRaisesRegex(EvidenceError, 'integrity binding'): self.record_now()
        self.save(original)

    def test_proc_pidpath_errno_is_captured_before_any_later_native_call(self):
        library = Mock()
        def failure(pid, buffer, size): ctypes.set_errno(errno.ESRCH); return 0
        library.proc_pidpath.side_effect = failure
        def later_clock(): ctypes.set_errno(errno.EACCES); return 12345
        self.patches[-4].stop()  # Exercise the actual wrapper, not setUp's path mock.
        try:
            with patch.object(native, '_library', return_value=library), patch.object(observed.time, 'monotonic_ns', side_effect=later_clock):
                with self.assertRaises(observed._PathQueryError) as error: observed.executable_path(102)
        finally:
            self.patches[-4].start()
        self.assertEqual(error.exception.receipt['returned_size'], 0)
        self.assertEqual(error.exception.receipt['errno'], errno.ESRCH)
        self.assertEqual(error.exception.receipt['stage'], 'query')

    def test_collector_stopped_joined_drained_before_closed_ack(self):
        observer = self.registered(); self.nodes.pop(101)
        observer.close(self.SEMANTIC_TIMEOUT)
        sampler = observer.value['native_sampler']
        self.assertEqual(sampler['state'], 'stopped')
        self.assertEqual(sampler['stopped_sequence'], sampler['durable_sequence'])
        self.assertFalse(observer._sampler._thread.is_alive())
        self.assertFalse(observer._sampler.take())

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
                                ([b'{"command":"prepare_cleanup","timeout":1}\n'], 'lost ack'),
                                ([b'{"command":"observe_pid","pid":101,"include_image":true}\n'], 'lost ack')):
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


class PortableReceiptTests(unittest.TestCase):
    """Literal synthetic receipts only: no Observer, OS hooks, paths or ledger I/O."""
    @staticmethod
    def at(node, tick):
        node = copy.deepcopy(node)
        node['observed'] = dict(monotonic_ns=str(tick), wall_time_ns=str(2000000000000 + tick))
        return node

    def setUp(self):
        owner = snapshot(99, 900, 800, birth=99, version=9, parent_version=8, ppid=98)
        mine = snapshot(200, 2000, 900, birth=102, ppid=99)
        root = self.at(snapshot(101, 1000, 900, birth=101, ppid=99), 1000)
        before = self.at(snapshot(102, 1100, 1000, birth=103, version=20, parent_version=10, ppid=101, pgid=555), 2000)
        raw = self.at(before, 3000); raw['idversion'] = 21
        after = self.at(raw, 5000)
        after['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
        follow = self.at(after, 4000)
        diagnostic = dict(version=1, kind='helper_native_metadata_gap', capture_sequence=3,
                          subtype='mixed_image_boundary', pid=102, raw=raw, path_status='unobserved',
                          image_status='nonqualifying', path_query=None,
                          followup=dict(outcome='snapshot', snapshot=follow, problem=None),
                          qualification=dict(version=1, mode='mixed_image_bracket', root='1000',
                                             before_observation_sequence=2, after_observation_sequence=3))
        self.session = dict(version=1, capability=observed.CAPABILITY, state='observing',
                            observer=mine['identity'], owner=owner['identity'],
                            membership=dict(version=1, attempt_id='portable-receipts', owner=owner['identity'],
                                            anchor=snapshot(100, 950, 800)['identity'], group_id=100, session_id=100),
                            source_sha256={key: 'a' * 64 for key in observed.SOURCE_FILES},
                            roots={'1000': dict(pid=101, identity=root['identity'], unique_id='1000',
                                                observation_sequence=1, writable_root_refs=['private-root'])},
                            observations=[dict(sequence=index, snapshot=node, executable=executable)
                                          for index, node, executable in ((1, root, '/fixture/wrapper'),
                                                                         (2, before, '/fixture/helper-before'),
                                                                         (3, after, '/fixture/helper-after'))],
                            writers={'1100': dict(authority=copy.deepcopy(observed.AUTHORITY), root='1000',
                                                  identity=after['identity'], unique_id='1100',
                                                  observation_sequence=3, lineage_observation_sequences=[1, 3])},
                            pending={}, working_roots={'private-root': dict(ref='private-root',
                                path='/fixture/sdd-observed-portable', parent='/fixture', identity=[1, 2],
                                parent_identity=[1, 1], uid=501, mode=0o700, purpose='literal receipt only', budget_bytes=4096)},
                            errors=[], lost_history=False, sequence=3, closure=None, warnings=list(observed.WARNINGS),
                            observer_snapshot=mine, owner_snapshot=owner, owner_executable='/fixture/node',
                            observer_executable='/fixture/python', observer_python_version='synthetic', ipc_paths={},
                            native_sampler=dict(version=2, state='running', roots=['1000'], durable_sequence=4,
                                stopped_sequence=None, unresolved=[], statuses={}, exec_transitions=[],
                                helper_diagnostics=[diagnostic], helper_diagnostic_bindings={}))
        self.rebind(self.session)
        self.assertIs(observed.validate_session(self.session), self.session)

    @staticmethod
    def diagnostic(session):
        return session['native_sampler']['helper_diagnostics'][0]

    @classmethod
    def rebind(cls, session):
        diagnostic = cls.diagnostic(session)
        session['native_sampler']['helper_diagnostic_bindings'][str(diagnostic['capture_sequence'])] = observed._helper_raw_digest(diagnostic)

    def path_gap(self, *, recovered=False):
        session = copy.deepcopy(self.session); diagnostic = self.diagnostic(session)
        # A complete, genuine same-epoch helper receipt precedes the query gap.
        raw = self.at(session['observations'][2]['snapshot'], 6000)
        diagnostic.update(subtype='known_epoch_path_gap', raw=raw,
                          path_query=dict(version=1, api='libproc.proc_pidpath', stage='query', pid=102,
                                          returned_size=0, errno=errno.ESRCH, buffer_size=4096,
                                          outcome='unavailable', monotonic_ns='6001'),
                          followup=dict(outcome='numeric_esrch', snapshot=None, problem=None),
                          qualification=dict(version=1, mode='known_epoch_exit_gap', root='1000',
                                             before_observation_sequence=3, after_observation_sequence=None))
        if recovered:
            later = self.at(raw, 8000)
            session['observations'].append(dict(sequence=4, snapshot=later, executable='/fixture/helper-after'))
            session['sequence'] = 4
            session['writers']['1100'].update(observation_sequence=4, lineage_observation_sequences=[1, 4])
            diagnostic['followup'] = dict(outcome='snapshot', snapshot=self.at(raw, 7000), problem=None)
            diagnostic['qualification'].update(mode='bounded_same_epoch_gap',
                                               before_observation_sequence=None, after_observation_sequence=4)
        self.rebind(session)
        self.assertIs(observed.validate_session(session), session)
        return session

    def test_mixed_bracket_is_nonqualifying_raw_with_exact_full_chain(self):
        diagnostic = self.diagnostic(self.session)
        self.assertTrue(observed._valid_helper_qualification(self.session, diagnostic, diagnostic['qualification']))
        self.assertEqual(observed.exact_chain_sequences(self.session, '1000', 3), [1, 3])
        self.assertNotIn(diagnostic['raw'], [item['snapshot'] for item in self.session['observations']])
        self.assertEqual(diagnostic['path_status'], 'unobserved')
        self.assertEqual(diagnostic['image_status'], 'nonqualifying')

    def test_same_epoch_root_refresh_requires_new_projection_with_immutable_prefix(self):
        session = copy.deepcopy(self.session); prefix = copy.deepcopy(session['observations'])
        refreshed = self.at(session['observations'][0]['snapshot'], 6000)
        session['observations'].append(dict(sequence=4, snapshot=refreshed, executable='/fixture/wrapper'))
        session['sequence'] = 4
        with self.assertRaisesRegex(EvidenceError, 'exact predecessor observation references'):
            observed.validate_session(session)
        for writer in session['writers'].values():
            writer['lineage_observation_sequences'] = observed.exact_chain_sequences(session, writer['root'], writer['observation_sequence'])
        observed.validate_session(session)
        self.assertEqual(session['observations'][:len(prefix)], prefix)
        self.assertEqual(session['writers']['1100']['lineage_observation_sequences'], [4, 3])
        self.assertEqual(session['writers']['1100']['observation_sequence'], 3)

    def test_known_pid_census_cache_is_not_an_explicit_capture_barrier(self):
        observer = observed.Observer.__new__(observed.Observer)
        observer._sampler_stopped_for_close = False
        observer._sampler = Mock()
        observer._sampler.has_pid.return_value = True
        observer._sampler.observe_pid.return_value = (1, self.session['observations'][0]['snapshot'])
        observer._drain_native = Mock()
        graph = Mock(); graph.lineage.return_value = [self.session['observations'][0]['snapshot']]
        observer.graphs = {'1000': graph}
        self.assertTrue(observer.observe(101, required=False))
        observer._sampler.observe_pid.assert_not_called()
        self.assertTrue(observer.observe(101, required=True))
        observer._sampler.observe_pid.assert_called_once_with(101)
        observer._drain_native.assert_called_with(through=1)

    def test_later_full_reparent_receipt_does_not_requalify_emitted_unresolved_history(self):
        session = copy.deepcopy(self.session)
        raw = copy.deepcopy(session['observations'][2]['snapshot'])
        session['observations'][2]['snapshot']['current_ppid'] = 1
        session.update(state='failed', lost_history=True)
        session['native_sampler']['state'] = 'failed'
        session['native_sampler']['unresolved'].append(dict(sequence=4, pid=102,
            reason='incomplete native/executable capture: native executable/birth changed during fast capture', snapshot=raw))
        before = copy.deepcopy(session)
        observed.validate_session(session)
        self.assertEqual(session, before)
        session.update(state='closed', lost_history=False, closure=dict(sequence=session['sequence'], numeric_absent=True, roots_no_handles=True,
            helper_diagnostics_sha256=observed.hashlib.sha256(observed.canonical(session['native_sampler']['helper_diagnostic_bindings']).encode()).hexdigest()))
        session['native_sampler'].update(state='stopped', stopped_sequence=session['native_sampler']['durable_sequence'])
        with self.assertRaisesRegex(EvidenceError, 'closed observer lacks'): observed.validate_session(session)

    def test_mixed_immutable_epoch_order_and_status_reject_with_rebound_digest(self):
        for field in ('birth', 'uid', 'boot', 'parent', 'parent_epoch', 'epoch', 'uuid', 'order', 'status'):
            session = copy.deepcopy(self.session); raw = self.diagnostic(session)['raw']
            if field == 'birth': raw['identity']['created']['microseconds'] += 1
            elif field == 'uid': raw['uid'] += 1
            elif field == 'boot': raw['boot_uuid'] = '56565656-5656-4565-8565-565656565656'
            elif field == 'parent': raw['original_parent_unique_id'] = '9999'
            elif field == 'parent_epoch': raw['original_parent_idversion'] += 1
            elif field == 'epoch': raw['idversion'] -= 1
            elif field == 'uuid': raw['executable_uuid'] = '56565656-5656-4565-8565-565656565656'
            elif field == 'order': raw['observed']['monotonic_ns'] = '1'
            else: raw['status'] = 'zombie'; raw['query']['native_status'] = 5
            self.rebind(session)
            with self.subTest(field=field), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_root_exclusion_missing_chain_and_wrong_full_references_reject(self):
        for variant in ('root_before', 'no_after', 'wrong_root', 'missing_parent_epoch'):
            session = copy.deepcopy(self.session); diagnostic = self.diagnostic(session)
            if variant == 'root_before': diagnostic['qualification']['before_observation_sequence'] = 1
            elif variant == 'no_after': diagnostic['qualification']['after_observation_sequence'] = None
            elif variant == 'wrong_root': diagnostic['qualification']['root'] = '9999'
            else:
                for node in [item['snapshot'] for item in session['observations'][1:]] + [diagnostic['raw'], diagnostic['followup']['snapshot']]:
                    node['original_parent_idversion'] = 999
            self.rebind(session)
            with self.subTest(variant=variant), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_path_gap_exit_and_later_same_epoch_positive_proofs(self):
        self.path_gap(); self.path_gap(recovered=True)

    def test_permissions_unknown_malformed_and_unsupported_path_results_block(self):
        original = self.path_gap()
        for field, value in (('errno', errno.EPERM), ('errno', errno.EACCES), ('errno', 0),
                             ('errno', errno.ENOTSUP), ('returned_size', -1), ('returned_size', 4096),
                             ('stage', 'decode'), ('outcome', 'malformed'), ('api', 'unknown')):
            session = copy.deepcopy(original); self.diagnostic(session)['path_query'][field] = value
            self.rebind(session)
            with self.subTest(field=field, value=value), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_path_followup_identity_status_and_unknown_native_result_block(self):
        original = self.path_gap(recovered=True)
        for field in ('birth', 'uid', 'boot', 'parent_epoch', 'epoch', 'uuid', 'order', 'raw_zombie', 'unknown'):
            session = copy.deepcopy(original); diagnostic = self.diagnostic(session); follow = diagnostic['followup']['snapshot']
            if field == 'birth': follow['identity']['created']['microseconds'] += 1
            elif field == 'uid': follow['uid'] += 1
            elif field == 'boot': follow['boot_uuid'] = '56565656-5656-4565-8565-565656565656'
            elif field == 'parent_epoch': follow['original_parent_idversion'] += 1
            elif field == 'epoch': follow['idversion'] += 1
            elif field == 'uuid': follow['executable_uuid'] = '56565656-5656-4565-8565-565656565656'
            elif field == 'order': follow['observed']['monotonic_ns'] = '1'
            elif field == 'raw_zombie': diagnostic['raw']['status'] = 'zombie'; diagnostic['raw']['query']['native_status'] = 5
            else: diagnostic['followup'] = dict(outcome='unavailable', snapshot=None, problem='unknown native query')
            self.rebind(session)
            with self.subTest(field=field), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_raw_receipt_removal_mutation_and_schema_downgrade_reject(self):
        for variant in ('raw', 'receipt', 'binding', 'downgrade'):
            session = copy.deepcopy(self.session); sampler = session['native_sampler']
            if variant == 'raw': self.diagnostic(session)['raw']['current_ppid'] = 1
            elif variant == 'receipt': sampler['helper_diagnostics'].clear()
            elif variant == 'binding': sampler['helper_diagnostic_bindings'].clear()
            else: sampler['version'] = 1
            with self.subTest(variant=variant), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_closed_receipt_digest_and_pending_lost_history_are_not_completion(self):
        session = copy.deepcopy(self.session); sampler = session['native_sampler']
        sampler.update(state='stopped', stopped_sequence=sampler['durable_sequence'])
        session.update(state='closed', closure=dict(sequence=session['sequence'], numeric_absent=True, roots_no_handles=True,
            helper_diagnostics_sha256=observed.hashlib.sha256(observed.canonical(sampler['helper_diagnostic_bindings']).encode()).hexdigest()))
        observed.validate_session(session)
        for variant in ('digest', 'pending', 'lost_history', 'unqualified'):
            changed = copy.deepcopy(session)
            if variant == 'digest': changed['closure']['helper_diagnostics_sha256'] = '0' * 64
            elif variant == 'pending': changed['pending']['pid:999'] = dict(pid=999, reason='unseen ancestry')
            elif variant == 'lost_history': changed['lost_history'] = True
            else: self.diagnostic(changed)['qualification'] = None
            with self.subTest(variant=variant), self.assertRaises(EvidenceError): observed.validate_session(changed)

    def test_external_native_receipt_never_grants_signal_group_or_adoption(self):
        self.assertEqual(self.session['observations'][2]['snapshot']['pgid'], 555)
        for field in ('signal', 'group', 'adoption', 'class'):
            session = copy.deepcopy(self.session)
            session['writers']['1100']['authority'][field] = True if field != 'class' else 'native_group'
            with self.subTest(field=field), self.assertRaises(EvidenceError): observed.validate_session(session)

    def test_exec_pair_semantic_dedup_and_unsupported_sampler_versions(self):
        before = self.session['observations'][1]['snapshot']; after = self.session['observations'][2]['snapshot']
        self.assertTrue(observed._exec_pair(before, after))
        self.assertEqual(observed.semantic(before), observed.semantic(self.at(before, 9000)))
        for version in (0, 4, True, '2'):
            session = copy.deepcopy(self.session); session['native_sampler']['version'] = version
            with self.subTest(version=version), self.assertRaises(EvidenceError): observed.validate_session(session)


    @staticmethod
    def scoped_target():
        return dict(version=2, path='/fixture/package/Playwright.app/Contents/MacOS/Playwright', sha256='a' * 64,
                    size=5, identity=[1, 5], mtime_ns=1, ctime_ns=1, scope='/fixture/package',
                    observation_scope=dict(path='/fixture/package', identity=[1, 4], uid=501))

    def test_v2_scope_structural_audit_never_queries_current_filesystem(self):
        session = copy.deepcopy(self.session)
        session['roots']['1000']['target_executable'] = self.scoped_target()
        with patch.object(observed, '_scope_pin', side_effect=AssertionError('historical audit must not query scope')):
            observed.validate_session(session)
            for variant in ('version', 'observation_scope', 'scope', 'pin_path', 'pin_identity', 'pin_uid', 'unknown'):
                changed = copy.deepcopy(session); target = changed['roots']['1000']['target_executable']
                if variant in ('version', 'observation_scope'): target.pop(variant)
                elif variant == 'scope': target['scope'] = '/fixture'
                elif variant == 'pin_path': target['observation_scope']['path'] = '/other'
                elif variant == 'pin_identity': target['observation_scope']['identity'] = [-1, 4]
                elif variant == 'pin_uid': target['observation_scope']['uid'] = True
                else: target['extra'] = True
                with self.subTest(variant=variant), self.assertRaises(EvidenceError): observed.validate_session(changed)

    def test_v2_scope_excluded_candidate_refs_use_same_effective_classifier(self):
        session = copy.deepcopy(self.session); session['roots']['1000']['target_executable'] = self.scoped_target()
        older = snapshot(500, 5000, 8000, birth=90, ppid=1, pgid=555)
        session['excluded_candidates'] = {'5000': dict(chain=[older], executable='/fixture/package/Sibling.app/Service',
            ancestor_executable='/fixture/package/Sibling.app/Service', roots=['1000'])}
        observed.validate_session(session)
        for field in ('executable', 'ancestor_executable', 'roots'):
            changed = copy.deepcopy(session)
            changed['excluded_candidates']['5000'][field] = ['9999'] if field == 'roots' else '/unrelated/service'
            with self.subTest(field=field), self.assertRaises(EvidenceError): observed.validate_session(changed)


class PureReparentCaptureTests(unittest.TestCase):
    """Private capture order with literal receipts; no thread/native/FD/ledger resources."""
    def setUp(self):
        self.before = snapshot(102, 1100, 1000, birth=103, version=20, parent_version=10, ppid=101, pgid=555)
        self.after = copy.deepcopy(self.before); self.after['current_ppid'] = 1
        self.after['observed'] = dict(monotonic_ns='1001', wall_time_ns='2000000000001')
        self.previous = copy.deepcopy(self.before); self.previous['idversion'] = 19
        self.previous['executable_uuid'] = '45454545-4545-4545-8545-454545454545'

    def capture(self, *, before=None, after=None, initial=False, root_kind=None, expected=None, force_ticket=None,
                paths=None, native_error=None, native_error_at=1, absent_confirm=False,
                setup=None, on_path=None, on_emit=None, actual_queue=False):
        before = copy.deepcopy(self.before if before is None else before)
        after = copy.deepcopy(self.after if after is None else after)
        sampler = observed._NativeSampler.__new__(observed._NativeSampler)
        sampler._condition = threading.Condition()
        sampler._known = {} if initial else {102: copy.deepcopy(self.previous)}
        sampler._last = {} if initial else {102: observed.semantic(self.previous)}
        sampler._complete = {} if initial else {102: copy.deepcopy(self.previous)}
        sampler._seed = copy.deepcopy(self.previous)
        sampler._roots = {}
        if root_kind is not None:
            root = copy.deepcopy(self.before)
            if root_kind == 'pid': root['unique_id'] = '9999'
            if root_kind == 'unique': root['identity']['pid'] = 999
            sampler._roots[root['unique_id']] = root
        sampler.query_lock_states = []
        if actual_queue:
            sampler._events, sampler._bytes, sampler._sequence = observed.deque(), 0, 0
            sampler.max_events, sampler.max_bytes = 256, 262144
            enqueue = observed._NativeSampler._emit.__get__(sampler)
        else:
            enqueue = lambda *args, **kwargs: 7
        def emit(*args, **kwargs):
            if on_emit is not None: on_emit(sampler, *args, **kwargs)
            return enqueue(*args, **kwargs)
        sampler._emit = Mock(side_effect=emit)
        if setup is not None: setup(sampler)
        events = []
        def read(pid, include_zombie=True):
            sampler.query_lock_states.append(sampler._condition._is_owned())
            events.append('native')
            if native_error is not None and events.count('native') == native_error_at: raise native_error
            if absent_confirm and events.count('native') > 1: return None
            return copy.deepcopy(before if events.count('native') == 1 else after)
        values = list(paths if paths is not None else ['/fixture/crashpad', '/fixture/crashpad'])
        def path(pid):
            sampler.query_lock_states.append(sampler._condition._is_owned())
            events.append('path')
            if on_path is not None: on_path(sampler, events.count('path'))
            value = values.pop(0)
            if isinstance(value, BaseException): raise value
            return value
        result, problem = None, None
        with patch.object(observed.native, 'read_snapshot', side_effect=read), patch.object(observed, 'executable_path', side_effect=path):
            try: result = sampler._collect(102, required=True, expected=expected, force_ticket=force_ticket)
            except (EvidenceError, OSError) as exc: problem = str(exc)
        return sampler, result, problem, events

    def test_helper_reparent_completes_with_untouched_confirmed_endpoint(self):
        for initial in (False, True):
            sampler, result, problem, events = self.capture(initial=initial)
            with self.subTest(initial=initial):
                self.assertIsNone(problem)
                self.assertEqual(events, ['native', 'path', 'native', 'path'])
                self.assertEqual(sampler._emit.call_args.args[0], 'snapshot')
                self.assertEqual(sampler._emit.call_args.kwargs['snapshot'], self.after)
                self.assertEqual(result, self.after)
                self.assertEqual(sampler._complete[102], self.after)
                self.assertEqual(sampler._last[102], observed.semantic(self.after))
                self.assertEqual(sampler._known[102], self.before if initial else self.previous)
                self.assertEqual(self.before['current_ppid'], 101)

    def test_reparent_root_inserted_during_second_path_cannot_enqueue_helper_full(self):
        def register(sampler, count):
            if count == 2:
                self.assertFalse(sampler._condition._is_owned())
                with sampler._condition:
                    sampler._roots[self.before['unique_id']] = copy.deepcopy(self.before)
        sampler, result, problem, events = self.capture(on_path=register)
        self.assertFalse(any(call.args[0] == 'snapshot' for call in sampler._emit.call_args_list))
        self.assertEqual(sampler._emit.call_args.args[0], 'pending')
        self.assertEqual(sampler._complete[102], self.previous)

    def test_reparent_values_iteration_is_protected_against_registration_resize(self):
        class InterleavedRoots(dict):
            def values(mapping):
                iterator = iter(super(InterleavedRoots, mapping).values())
                def ordered():
                    yield next(iterator)
                    if not mapping.condition._is_owned():
                        mapping['new-root'] = copy.deepcopy(self.before)
                    else:
                        mapping.registration_deferred = True
                    yield from iterator
                return ordered()
        def setup(sampler):
            unrelated = copy.deepcopy(self.before); unrelated['identity']['pid'] = 999; unrelated['unique_id'] = '9999'
            roots = InterleavedRoots({'9999': unrelated}); roots.condition = sampler._condition
            roots.registration_deferred = False; sampler._roots = roots
        sampler, result, problem, events = self.capture(setup=setup)
        self.assertIsNone(problem); self.assertEqual(result, self.after)
        self.assertTrue(sampler._roots.registration_deferred)
        self.assertEqual(sampler._emit.call_args.args[0], 'snapshot')
        self.assertNotIn(self.before['unique_id'], sampler._roots)
        with sampler._condition: sampler._roots[self.before['unique_id']] = copy.deepcopy(self.before)

    def test_reparent_full_enqueue_holds_condition_without_locking_native_queries(self):
        def inspect(sampler, kind, pid, **kwargs):
            if kind == 'snapshot':
                self.assertTrue(sampler._condition._is_owned())
                self.assertNotIn(self.before['unique_id'], sampler._roots)
        sampler, result, problem, events = self.capture(on_emit=inspect, actual_queue=True)
        self.assertIsNone(problem); self.assertEqual(result, self.after)
        self.assertEqual(sampler.query_lock_states, [False, False, False, False])
        self.assertEqual(sampler._sequence, 1)
        self.assertEqual(sampler._events[0][0]['snapshot'], self.after)
        self.assertEqual(sampler._known[102], self.previous)

    def test_non_parent_native_mutations_never_enter_successful_reparent_branch(self):
        fields = ('birth', 'host', 'platform', 'identity_version', 'pid', 'unique', 'uid', 'boot', 'parent', 'parent_epoch',
                  'pgid', 'epoch', 'uuid', 'status', 'version', 'query', 'query_api', 'query_status', 'query_size')
        for field in fields:
            after = copy.deepcopy(self.after)
            if field == 'birth': after['identity']['created']['microseconds'] += 1
            elif field == 'host': after['identity']['host'] = 'other.invalid'
            elif field == 'platform': after['identity']['platform'] = 'linux'
            elif field == 'identity_version': after['identity']['version'] = 2
            elif field == 'pid': after['identity']['pid'] = 999
            elif field == 'unique': after['unique_id'] = '9999'
            elif field == 'uid': after['uid'] += 1
            elif field == 'boot': after['boot_uuid'] = '56565656-5656-4565-8565-565656565656'
            elif field == 'parent': after['original_parent_unique_id'] = '9999'
            elif field == 'parent_epoch': after['original_parent_idversion'] += 1
            elif field == 'pgid': after['pgid'] += 1
            elif field == 'epoch': after['idversion'] += 1
            elif field == 'uuid': after['executable_uuid'] = '56565656-5656-4565-8565-565656565656'
            elif field == 'status': after['status'] = 'zombie'; after['query']['native_status'] = 5
            elif field == 'version': after['version'] = 2
            elif field == 'query_api': after['query']['api'] = 'unknown'
            elif field == 'query_status': after['query']['native_status'] = 5
            elif field == 'query_size': after['query']['returned_size'] = 1
            else: after['query']['errno'] = errno.EACCES
            sampler, result, problem, events = self.capture(after=after)
            with self.subTest(field=field):
                self.assertFalse(any(call.args[0] == 'snapshot' for call in sampler._emit.call_args_list))

    def test_root_force_direction_time_and_path_guards_remain_strict(self):
        variants = ['root_pid', 'root_unique', 'expected', 'force', 'reverse', 'noninit', 'zero',
                    'same_time', 'wall_backwards', 'monotonic_backwards', 'different_path', 'relative_path',
                    'nul_path', 'oversize_path', 'permission_first', 'permission_second', 'missing_first', 'missing_second',
                    'native_absent', 'native_denied_first', 'native_denied_second', 'boolean_parent', 'wrong_requested_pid']
        for variant in variants:
            before, after, options = copy.deepcopy(self.before), copy.deepcopy(self.after), {}
            if variant == 'root_pid': options['root_kind'] = 'pid'
            elif variant == 'root_unique': options['root_kind'] = 'unique'
            elif variant == 'expected': options['expected'] = copy.deepcopy(before)
            elif variant == 'force': options['force_ticket'] = Mock(capture_sequence=None)
            elif variant == 'reverse': before['current_ppid'] = 1; after['current_ppid'] = 101
            elif variant == 'noninit': after['current_ppid'] = 102
            elif variant == 'zero': before['current_ppid'] = 0
            elif variant == 'same_time': after['observed'] = copy.deepcopy(before['observed'])
            elif variant == 'wall_backwards': after['observed']['wall_time_ns'] = '1'
            elif variant == 'monotonic_backwards': after['observed']['monotonic_ns'] = '1'
            elif variant == 'different_path': options['paths'] = ['/fixture/crashpad', '/other/path']
            elif variant == 'relative_path': options['paths'] = ['relative', 'relative']
            elif variant == 'nul_path': options['paths'] = ['/nul\x00', '/nul\x00']
            elif variant == 'oversize_path': options['paths'] = ['/' + 'a' * 4096] * 2
            elif variant == 'native_absent': options['absent_confirm'] = True
            elif variant.startswith('native_denied'):
                options.update(native_error=native.ObservationError('denied native query'), native_error_at=1 if variant.endswith('first') else 2)
            elif variant == 'boolean_parent': before['current_ppid'] = True
            elif variant == 'wrong_requested_pid':
                before['identity']['pid'] = after['identity']['pid'] = 999; options['initial'] = True
            else:
                code = errno.EACCES if variant.startswith('permission') else errno.ESRCH
                error = observed._PathQueryError('denied or missing actual path', dict(version=1, api='libproc.proc_pidpath', stage='query', pid=102,
                    returned_size=0, errno=code, buffer_size=4096, outcome='unavailable', monotonic_ns='1002'))
                options['paths'] = [error] if variant.endswith('first') else ['/fixture/crashpad', error]
            sampler, result, problem, events = self.capture(before=before, after=after, **options)
            with self.subTest(variant=variant):
                self.assertFalse(any(call.args[0] == 'snapshot' for call in sampler._emit.call_args_list))

    def test_unchanged_capture_and_missing_original_ancestry_contract_stay_intact(self):
        after = copy.deepcopy(self.before); after['observed'] = copy.deepcopy(self.after['observed'])
        sampler, result, problem, events = self.capture(after=after)
        self.assertIsNone(problem); self.assertEqual(result, self.before)
        self.assertEqual(sampler._emit.call_args.kwargs['snapshot'], self.before)
        before = copy.deepcopy(self.before); before['current_ppid'] = 1
        after = copy.deepcopy(before); after['observed'] = copy.deepcopy(self.after['observed'])
        sampler, result, problem, events = self.capture(before=before, after=after)
        self.assertEqual(result, before)  # No reparent delta; ordinary strict capture still selects A.
        graph = native.LineageGraph(8)
        root = snapshot(101, 1000, 900, birth=101, ppid=99)
        graph.add_root(root, expected_identity=root['identity'], expected_unique_id='1000')
        missing = copy.deepcopy(self.after); missing['original_parent_unique_id'] = '9999'
        self.assertIsNone(graph.ingest(missing)); self.assertIsNone(graph.lineage('1100'))


class NativeCollectorTests(unittest.TestCase):
    def setUp(self):
        self.nodes = {100: snapshot(100, 1000, 900, birth=100)}
        self.children, self.samplers, self.stamp = {}, [], 1000
        self.patches = [patch.object(native, 'read_snapshot', side_effect=self.read),
                        patch.object(observed, 'executable_path', side_effect=lambda pid: '/fixture/executable'),
                        patch.object(observed, 'child_pids', side_effect=lambda pid: tuple(self.children.get(pid, ()))),
                        patch.object(observed, 'sources', side_effect=AssertionError('collector must not hash sources')),
                        patch.object(observed, 'candidate_pids', side_effect=AssertionError('collector must not enumerate UID'))]
        for patcher in self.patches: patcher.start()
        self.addCleanup(self.cleanup)

    def read(self, pid, include_zombie=True):
        self.stamp += 1
        value = copy.deepcopy(self.nodes.get(pid))
        if value:
            value['observed']['monotonic_ns'] = str(self.stamp)
            value['observed']['wall_time_ns'] = str(2000000000000 + self.stamp)
        return value

    def collector(self, **kwargs):
        sampler = observed._NativeSampler(**kwargs); self.samplers.append(sampler)
        return sampler

    def cleanup(self):
        for sampler in self.samplers:
            try: sampler.stop()
            except EvidenceError: pass
            self.assertFalse(sampler._thread.is_alive())
        for patcher in reversed(self.patches): patcher.stop()

    @staticmethod
    def events(sampler):
        result = []
        while True:
            batch = sampler.take()
            if not batch: return result
            result.extend(batch)

    def test_force_image_capture_is_fresh_full_even_when_semantic_fields_match(self):
        sampler = self.collector(); sampler.add_root(self.read(100))
        original = self.events(sampler)
        self.assertEqual(len(original), 1)
        watermark, node, capture = sampler.observe_pid(100, force_full=True)
        events = self.events(sampler)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'snapshot'); self.assertTrue(events[0]['force_full'])
        self.assertEqual(events[0]['snapshot'], node); self.assertEqual(events[0]['sequence'], capture)
        self.assertGreaterEqual(watermark, capture)
        self.assertEqual(observed.semantic(original[0]['snapshot']), observed.semantic(node))
        self.assertGreater(int(node['observed']['monotonic_ns']), int(original[0]['snapshot']['observed']['monotonic_ns']))
        sampler.observe_pid(100)
        self.assertEqual(self.events(sampler), [])

    def test_real_ready_fence_native_only_and_semantic_noop(self):
        sampler = self.collector()
        ready = sampler.add_root(self.nodes[100]); self.assertEqual(ready, 1)
        first = self.events(sampler)
        self.assertEqual(first[0]['kind'], 'snapshot')
        self.assertEqual(first[0]['snapshot']['unique_id'], '1000')
        for _ in range(20): self.assertEqual(sampler.fence(), ready)
        self.assertFalse(self.events(sampler))
        self.assertEqual(sampler.stop(), ready)

    def test_native_receipt_survives_process_exit_while_main_is_slow(self):
        sampler = self.collector(); sampler.add_root(self.nodes[100]); self.events(sampler)
        self.nodes[102] = snapshot(102, 1100, 1000, birth=101, parent_version=10, ppid=100)
        self.children[100] = (102,)
        # No main SQL/drain work runs during this controlled native capture window.
        time.sleep(.02)
        self.nodes.pop(102); self.children.clear()
        sampler.fence()
        events = self.events(sampler)
        receipts = [event for event in events if event['kind'] == 'snapshot' and event['pid'] == 102]
        self.assertTrue(receipts)
        self.assertEqual(receipts[0]['snapshot']['original_parent_unique_id'], '1000')
        self.assertTrue(any(event['kind'] == 'absent' and event['pid'] == 102 for event in events))

    def test_exec_versions_retained_before_main_drain(self):
        sampler = self.collector(); sampler.add_root(self.nodes[100]); self.events(sampler)
        self.nodes[102] = snapshot(102, 1100, 1000, birth=101, version=20, parent_version=10, ppid=100)
        self.children[100] = (102,); sampler.fence()
        self.nodes[102]['idversion'] = 21
        self.nodes[102]['executable_uuid'] = '45454545-4545-4545-8545-454545454545'
        sampler.fence()
        receipts = [event['snapshot'] for event in self.events(sampler) if event['kind'] == 'snapshot' and event['pid'] == 102]
        self.assertEqual([receipt['idversion'] for receipt in receipts], [20, 21])

    def test_queue_event_and_byte_overflow_latch_loss(self):
        sampler = self.collector(max_events=1); sampler.add_root(self.nodes[100])
        self.nodes[102] = snapshot(102, 1100, 1000, birth=101, parent_version=10, ppid=100)
        with self.assertRaisesRegex(EvidenceError, 'bound'): sampler.observe_pid(102)
        with self.assertRaisesRegex(EvidenceError, 'lost history'): sampler.check()
        tiny = self.collector(max_bytes=1)
        with self.assertRaisesRegex(EvidenceError, 'bound'): tiny.add_root(self.nodes[100])

    def test_missing_ready_native_failure_and_join_timeout_block(self):
        missing = self.collector()
        value = self.nodes.pop(100)
        with self.assertRaisesRegex(EvidenceError, 'gone before ready'): missing.add_root(value)
        self.nodes[100] = value
        sampler = self.collector(); sampler.add_root(value); self.events(sampler)
        with patch.object(native, 'read_snapshot', side_effect=native.ObservationError('controlled native denial')):
            with self.assertRaisesRegex(EvidenceError, 'denial'): sampler.fence()
        joiner = self.collector(); joiner.add_root(value)
        with patch.object(joiner._thread, 'join'), patch.object(joiner._thread, 'is_alive', return_value=True):
            with self.assertRaisesRegex(EvidenceError, 'join deadline'): joiner.stop(.01)

    def test_lost_ready_fence_and_unexpected_thread_death_are_not_empty_success(self):
        with patch.object(observed._NativeSampler, '_cycle'):
            sampler = self.collector()
            with self.assertRaisesRegex(EvidenceError, 'deadline'): sampler.add_root(self.nodes[100], timeout=.01)
            with self.assertRaisesRegex(EvidenceError, 'deadline'): sampler.fence(timeout=.01)
            sampler.stop()
        with patch.object(observed._NativeSampler, '_run'):
            dead = self.collector(); dead._thread.join(1)
            with self.assertRaisesRegex(EvidenceError, 'not alive'): dead.check()

    def test_partial_native_capture_is_pending_not_an_invented_executable(self):
        sampler = self.collector(); sampler.add_root(self.nodes[100]); self.events(sampler)
        self.nodes[102] = snapshot(102, 1100, 1000, birth=101, parent_version=10, ppid=100)
        with patch.object(observed, 'executable_path', side_effect=EvidenceError('gone before path')):
            sampler.observe_pid(102)
        event = next(event for event in self.events(sampler) if event['pid'] == 102)
        self.assertEqual(event['kind'], 'pending'); self.assertIsNone(event['executable'])
        self.assertEqual(event['snapshot']['unique_id'], '1100')

    def test_known_zombie_records_actual_status_without_fabricating_current_path(self):
        sampler = self.collector(); sampler.add_root(self.nodes[100]); self.events(sampler)
        self.nodes[100]['status'] = 'zombie'; self.nodes[100]['query']['native_status'] = 5
        with patch.object(observed, 'executable_path', side_effect=AssertionError('zombie has no current path')):
            sampler.fence()
        events = self.events(sampler)
        self.assertEqual(events[0]['kind'], 'status')
        self.assertIsNone(events[0]['executable'])
        self.assertEqual(events[0]['snapshot']['status'], 'zombie')


class ControlDescriptorTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'Actual Darwin POSIX socket descriptors; Windows sockets are not POSIX FDs')
    def test_anonymous_stream_socketpair_accepted_without_closing_originals(self):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            worker.validate_control_fd(left.fileno()); worker.validate_control_fd(right.fileno())
            left.send(b'proof'); self.assertEqual(right.recv(5), b'proof')
        finally:
            left.close(); right.close()

    @unittest.skipUnless(sys.platform == 'darwin', 'Actual anonymous FIFO metadata is Darwin-specific')
    def test_darwin_anonymous_pipe_accepted_without_closing_originals(self):
        read_fd, write_fd = os.pipe()
        try:
            worker.validate_control_fd(read_fd); worker.validate_control_fd(write_fd)
            os.write(write_fd, b'x'); self.assertEqual(os.read(read_fd, 1), b'x')
        finally:
            os.close(read_fd); os.close(write_fd)

    def test_socket_metadata_boundaries_are_portable_mocks(self):
        # Emulate this Darwin enum even on Windows builds without AF_UNIX.
        with patch.object(worker.socket, 'AF_UNIX', getattr(socket, 'AF_UNIX', 1), create=True):
            control = Mock(family=socket.AF_UNIX)
            control.getsockopt.return_value = socket.SOCK_STREAM
            control.getsockname.return_value = ''
            control.getpeername.return_value = b''
            wrapped = Mock()
            wrapped.__enter__ = Mock(return_value=control)
            wrapped.__exit__ = Mock(return_value=False)
            with patch.object(worker.os, 'fstat', return_value=Mock(st_mode=stat.S_IFSOCK)), \
                 patch.object(worker.os, 'dup', return_value=17) as duplicate, \
                 patch.object(worker.socket, 'socket', return_value=wrapped) as constructor:
                worker.validate_control_fd(7)
                duplicate.assert_called_once_with(7)
                constructor.assert_called_once_with(fileno=17)
                for method, value in ((control.getsockname, '/named'),
                                      (control.getpeername, '/named'),
                                      (control.getsockopt, socket.SOCK_DGRAM)):
                    original = method.return_value; method.return_value = value
                    with self.assertRaises(EvidenceError): worker.validate_control_fd(7)
                    method.return_value = original
                control.family = socket.AF_INET
                with self.assertRaises(EvidenceError): worker.validate_control_fd(7)
            wrapped.__exit__.assert_called()

    def test_fifo_metadata_boundary_is_portable_without_assuming_linux_nlink(self):
        with patch.object(worker.os, 'fstat', return_value=Mock(st_mode=stat.S_IFIFO | 0o600, st_nlink=0)):
            worker.validate_control_fd(3)
        # Linux anonymous pipes can also have nlink1. The Darwin-only observer
        # does not silently treat that as sufficient proof of an anonymous FD.
        with patch.object(worker.os, 'fstat', return_value=Mock(st_mode=stat.S_IFIFO | 0o600, st_nlink=1)):
            with self.assertRaisesRegex(EvidenceError, 'named'): worker.validate_control_fd(3)

    @unittest.skipUnless(sys.platform == 'darwin', 'Actual Darwin filesystem and POSIX socket descriptors')
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
    def test_actual_owned_fork_windows_capture_or_preserve_pending_without_compiler(self):
        code = r"""
import os, sys, time, json
print('READY', flush=True)
if sys.stdin.readline().strip() != 'GO': raise SystemExit(1)
for index in range(25):
    read_fd, write_fd = os.pipe()
    before = time.time_ns()
    before_monotonic = time.monotonic_ns()
    middle = os.fork()
    if middle == 0:
        os.close(read_fd)
        grandchild = 0
        if index == 0:
            grandchild = os.fork()
            if grandchild == 0:
                time.sleep(.03)
                os._exit(0)
            os.waitpid(grandchild, 0)
        os.write(write_fd, (str(grandchild) + '\n').encode())
        os.close(write_fd)
        os._exit(0)
    os.close(write_fd)
    message = os.read(read_fd, 64)
    os.close(read_fd)
    os.waitpid(middle, 0)
    print(json.dumps(dict(index=index, middle=middle, grandchild=int(message), before_wall_ns=before,
                          reaped_wall_ns=time.time_ns(), before_monotonic_ns=before_monotonic,
                          reaped_monotonic_ns=time.monotonic_ns())), flush=True)
print('DONE', flush=True)
sys.stdin.readline()
"""
        process = subprocess.Popen([sys.executable, '-B', '-c', code], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        sampler, rows, events = None, [], []
        try:
            self.assertTrue(select.select([process.stdout], [], [], 3)[0])
            self.assertEqual(process.stdout.readline().strip(), b'READY')
            root = native.read_snapshot(process.pid)
            sampler = observed._NativeSampler()
            sampler.add_root(root)
            process.stdin.write(b'GO\n'); process.stdin.flush()
            for _ in range(26):
                self.assertTrue(select.select([process.stdout], [], [], 5)[0])
                line = process.stdout.readline().strip()
                if line == b'DONE': break
                rows.append(json.loads(line))
                events.extend(sampler.take())
            self.assertEqual(len(rows), 25)
            sampler.fence()
            while True:
                batch = sampler.take()
                if not batch: break
                events.extend(batch)
            # Reported PIDs request SDK-native lookups only. If the live window
            # was missed, genuine lack of birth becomes a pending event.
            for row in rows[1:]:
                sampler.observe_pid(row['middle'])
                events.extend(sampler.take())
            sampler.stop()
            events.extend(sampler.take())
            receipts = [event for event in events if event['kind'] == 'snapshot']
            by_pid = {event['pid']: event['snapshot'] for event in receipts}
            positive = rows[0]
            self.assertIn(positive['middle'], by_pid)
            self.assertIn(positive['grandchild'], by_pid)
            middle, grandchild = by_pid[positive['middle']], by_pid[positive['grandchild']]
            self.assertEqual(middle['original_parent_unique_id'], root['unique_id'])
            self.assertEqual(grandchild['original_parent_unique_id'], middle['unique_id'])
            self.assertEqual(grandchild['original_parent_idversion'], middle['idversion'])
            pending = {event['pid'] for event in events if event['kind'] in ('pending', 'helper_metadata', 'exec_transition')}
            # Collector-only typed candidates remain unqualified here; only the
            # authenticated SDK main thread can bind full-witness references.
            for row in rows[1:]:
                self.assertTrue(row['middle'] in by_pid or row['middle'] in pending)
            durations = []
            for row in rows[1:]:
                witness = by_pid.get(row['middle'])
                birth = witness['identity']['created'] if witness else None
                # Parent monotonic interval encloses creation AND reaping, so
                # it is a conservative lifetime upper bound without wall-clock
                # adjustment or microsecond birth timestamp assumptions.
                upper = row['reaped_monotonic_ns'] - row['before_monotonic_ns']
                durations.append(upper)
            result = dict(kind='owned-native-fork-window-result', trials=24,
                          complete_captured=sum(row['middle'] in by_pid for row in rows[1:]),
                          pending=sum(row['middle'] in pending and row['middle'] not in by_pid for row in rows[1:]),
                          unqualified_diagnostic_events=sum(event['kind'] == 'helper_metadata' for event in events),
                          measured_lifetime_upper_bound_ns=durations,
                          proven_submillisecond_windows=sum(0 < duration < 1000000 for duration in durations),
                          positive_exact_three_process_chain=True,
                          qualification='Measured case only; not a guarantee for arbitrary ephemeral forks or Chrome')
            print('NATIVE_FORK_RESULT ' + json.dumps(result, sort_keys=True), flush=True)
            for row in rows:
                self.assertIsNone(native.read_snapshot(row['middle']))
                if row['grandchild']: self.assertIsNone(native.read_snapshot(row['grandchild']))
        finally:
            if sampler is not None:
                try: sampler.stop()
                except EvidenceError: pass
                self.assertFalse(sampler._thread.is_alive())
            if process.stdin:
                try: process.stdin.close()
                except OSError: pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate(); process.wait(timeout=3)
            if process.stdout: process.stdout.close()
            if process.stderr: process.stderr.close()
        self.assertEqual(process.returncode, 0)
        self.assertIsNone(native.read_snapshot(process.pid))

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
