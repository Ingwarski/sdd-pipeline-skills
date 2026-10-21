"""Read-only observations of real native POSIX launch gate membership."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/to-sdd-pipeline/scripts'
sys.path.insert(0, str(SCRIPTS))
from evidence.accounting import Accounting
from evidence.io import EvidenceError
from evidence.policy import load_defaults
from evidence import process_identity, producer_runtime as runtime


class PlatformContractTests(unittest.TestCase):
    def test_non_posix_is_explicitly_unsupported(self):
        with patch.object(runtime.os, 'name', 'nt'):
            with self.assertRaisesRegex(EvidenceError, 'requires POSIX'):
                runtime.managed_group_identity()


@unittest.skipUnless(os.name == 'posix', 'native POSIX group inspection')
class ManagedGroupIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sdd-group-inspection-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'output'
        self.output.mkdir()
        policy = load_defaults()
        policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider='local')
        self.ledger = Accounting(self.root / 'state' / 'accounting.sqlite', policy['project_id'], policy)
        self.addCleanup(self.ledger.close)
        self.attempt = str(uuid.uuid4())
        reservation = self.ledger.reserve('run', 'unit', 65536, 20, local_bytes=65536, metadata_bytes=3 * 1024 * 1024)
        output = self.ledger.register_output('run', 'unit', self.output)
        owner = process_identity.identity()
        value = {'version': 1, 'attempt_id': self.attempt, 'run_id': 'run', 'unit_id': 'unit',
                 'reservation_id': reservation, 'output_id': output, 'intent_id': None,
                 'coordinator': owner, 'guardian': owner, 'status': 'running', 'processes': {}, 'resources': [],
                 'output_dir': str(self.output), 'output_identity': runtime.directory_identity(self.output), 'policy': policy}
        self.ledger.connection.execute('INSERT INTO producer_sessions VALUES(?,?)', (self.attempt, json.dumps(value)))

    def wait_file(self, path):
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(path.exists(), str(path))

    def inspect(self, mutate=None, *, target='None', dead_anchor=False):
        ready, go, result, finish = (self.root / name for name in ('ready', 'go', 'result.json', 'finish'))
        source = """import hashlib,json,os,sqlite3,time
from pathlib import Path
from unittest.mock import patch
from evidence import producer_runtime as runtime
from evidence.process_identity import identity
from evidence.io import EvidenceError
Path(READY).write_text('ready')
while not Path(GO).exists(): time.sleep(.01)
ledger=Path(os.environ['SDD_PRODUCER_LEDGER'])
def snapshot():
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ledger,Path(str(ledger)+'-wal'),Path(str(ledger)+'-shm'))}
before=snapshot(); statements=[]; changes=[]; actual_connect=sqlite3.connect
class InspectionConnection(sqlite3.Connection):
    def close(self):
        changes.append(self.total_changes)
        super().close()
def readonly_connect(*args,**kwargs):
    c=actual_connect(*args,**kwargs,factory=InspectionConnection)
    c.set_trace_callback(statements.append)
    return c
value={'caller':identity()}
try:
    with patch.object(runtime,'Accounting',side_effect=AssertionError('inspection opened writable Accounting')), patch.object(sqlite3,'connect',side_effect=readonly_connect), patch.object(os,'kill',side_effect=AssertionError('inspection signalled a process')), patch.object(os,'killpg',side_effect=AssertionError('inspection signalled a group')):
        value['inspection']=runtime.managed_group_identity(TARGET)
except EvidenceError as exc:
    value['problem']=str(exc)
value.update(before=before,after=snapshot(),statements=statements,sql_changes=changes)
Path(RESULT).write_text(json.dumps(value))
while not Path(FINISH).exists(): time.sleep(.01)
"""
        source = source.replace('READY', repr(str(ready))).replace('GO', repr(str(go))).replace('RESULT', repr(str(result))).replace('FINISH', repr(str(finish))).replace('TARGET', target)
        env = os.environ.copy()
        env.update(SDD_PRODUCER_LEDGER=str(self.ledger.path), SDD_PRODUCER_ATTEMPT=self.attempt,
                   PYTHONPATH=str(SCRIPTS) + os.pathsep + env.get('PYTHONPATH', ''))
        child = runtime.launch(self.ledger, self.attempt, [sys.executable, '-B', '-c', source],
                               cwd=self.output, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            self.wait_file(ready)
            original = runtime.read(self.ledger, self.attempt)
            anchor = max(original['processes'].values(), key=lambda value: value['sequence'])['identity']
            restore = None
            if mutate:
                restore = mutate(anchor)
            go.write_text('go')
            self.wait_file(result)
            if callable(restore):
                restore()
            finish.write_text('finish')
            if dead_anchor:
                child.process.wait(timeout=5)
            else:
                self.assertEqual(0, child.wait(timeout=5))
        finally:
            finish.touch()
            child.close()
            if child.process.stdout:
                log = child.process.stdout.read().decode('utf-8', errors='replace')
                child.process.stdout.close()
            else:
                log = ''
        self.assertTrue(result.exists(), log)
        value = json.loads(result.read_text())
        # SQLite mode=ro can update read marks in an existing SHM index. Its
        # committed database/WAL bytes and logical records must stay unchanged.
        self.assertEqual(set(value['before']), set(value['after']))
        for path, before in value['before'].items():
            if not path.endswith('-shm'):
                self.assertEqual(before, value['after'][path], value)
        self.assertTrue(all(count == 0 for count in value['sql_changes']), value)
        self.assertTrue(all(statement.startswith(('SELECT ', 'BEGIN', 'ROLLBACK')) for statement in value['statements']), value)
        return value, anchor

    def test_default_owner_is_live_caller_inside_exact_native_gate_without_writes(self):
        value, anchor = self.inspect()
        self.assertNotIn('problem', value)
        observed = value['inspection']
        self.assertEqual({'version', 'attempt_id', 'owner', 'anchor', 'group_id', 'session_id'}, set(observed))
        self.assertEqual(1, observed['version'])
        self.assertEqual(self.attempt, observed['attempt_id'])
        self.assertEqual(value['caller'], observed['owner'])
        self.assertEqual(anchor, observed['anchor'])
        self.assertEqual(anchor['pid'], observed['group_id'])
        self.assertEqual(anchor['pid'], observed['session_id'])

    def test_explicit_same_group_pid_is_supported(self):
        value, _ = self.inspect(target='os.getpid()')
        self.assertNotIn('problem', value)
        self.assertEqual(value['caller'], value['inspection']['owner'])

    def test_another_existing_pid_in_same_group_is_supported(self):
        value, anchor = self.inspect(target='os.getppid()')
        self.assertNotIn('problem', value)
        self.assertEqual(anchor, value['inspection']['owner'])
        self.assertNotEqual(value['caller'], value['inspection']['owner'])

    def test_foreign_pid_is_not_adopted(self):
        value, _ = self.inspect(target=str(os.getpid()))
        self.assertIn('outside the caller', value['problem'])

    def test_unregistered_caller_group_cannot_claim_a_gate(self):
        env = {'SDD_PRODUCER_LEDGER': str(self.ledger.path), 'SDD_PRODUCER_ATTEMPT': self.attempt}
        original = self.ledger.connection.total_changes
        with patch.dict(os.environ, env):
            with self.assertRaisesRegex(EvidenceError, 'no unique recorded'):
                runtime.managed_group_identity()
        self.assertEqual(original, self.ledger.connection.total_changes)

    def test_inactive_attempt_is_rejected(self):
        value, _ = self.inspect(lambda _: runtime.update(self.ledger, self.attempt, lambda v: v.update(status='stopping')))
        self.assertIn('running producer bindings', value['problem'])

    def test_malformed_native_reservation_binding_is_rejected(self):
        def malformed(_):
            raw = self.ledger.connection.execute('SELECT record FROM producer_sessions WHERE id=?', (self.attempt,)).fetchone()[0]
            changed = json.loads(raw)
            changed['reservation_id'] = str(uuid.uuid4())
            self.ledger.connection.execute('UPDATE producer_sessions SET record=? WHERE id=?', (json.dumps(changed), self.attempt))
            return lambda: self.ledger.connection.execute('UPDATE producer_sessions SET record=? WHERE id=?', (raw, self.attempt))
        value, _ = self.inspect(malformed)
        self.assertIn('reservation binding changed', value['problem'])

    def test_reused_anchor_identity_is_rejected(self):
        def replace(anchor):
            def mutate(value):
                item = next(iter(value['processes'].values()))
                item['identity'] = deepcopy(anchor)
                created = item['identity']['created']
                if 'start_ticks' in created:
                    created['start_ticks'] += 1
                else:
                    created['microseconds'] = (created['microseconds'] + 1) % 1000000
            runtime.update(self.ledger, self.attempt, mutate)
        value, _ = self.inspect(replace)
        self.assertIn('anchor identity', value['problem'])

    def test_dead_guardian_is_rejected(self):
        process = subprocess.Popen([sys.executable, '-B', '-c', 'import sys;sys.stdin.buffer.read()'], stdin=subprocess.PIPE)
        try:
            dead = process_identity.identity(process.pid)
        finally:
            process.stdin.close()
            process.wait(timeout=5)
        value, _ = self.inspect(lambda _: runtime.update(self.ledger, self.attempt, lambda v: v.update(guardian=dead)))
        self.assertIn('live producer owners', value['problem'])

    def test_dead_gate_anchor_cannot_authorize_surviving_group_member(self):
        import signal
        def kill_owned_anchor(anchor):
            self.assertEqual('alive', process_identity.state(anchor))
            os.kill(anchor['pid'], signal.SIGKILL)
            deadline = time.monotonic() + 5
            while process_identity.state(anchor) != 'gone' and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual('gone', process_identity.state(anchor))
        value, _ = self.inspect(kill_owned_anchor, dead_anchor=True)
        self.assertIn('anchor identity', value['problem'])
        deadline = time.monotonic() + 5
        while process_identity.state(value['caller']) != 'gone' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual('gone', process_identity.state(value['caller']))

    def test_missing_environment_and_invalid_pid_fail_explicitly(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(EvidenceError, 'active producer session'):
                runtime.managed_group_identity()
        value, _ = self.inspect(target='True')
        self.assertIn('positive integer PID', value['problem'])

    def test_missing_sidecar_is_not_created(self):
        import sqlite3
        shm = Path(str(self.ledger.path) + '-shm')
        saved = shm.with_name(shm.name + '.preserved')
        shm.rename(saved)
        try:
            with patch.dict(os.environ, {'SDD_PRODUCER_LEDGER': str(self.ledger.path), 'SDD_PRODUCER_ATTEMPT': self.attempt}), patch.object(sqlite3, 'connect') as connect:
                with self.assertRaisesRegex(EvidenceError, 'sidecar is unavailable'):
                    runtime.managed_group_identity()
            connect.assert_not_called()
            self.assertFalse(shm.exists())
        finally:
            saved.rename(shm)


if __name__ == '__main__':
    unittest.main()
