"""An abandoned monitor's floor is durable even if resource cleanup throws."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/to-sdd-pipeline/scripts'
sys.path.insert(0, str(SCRIPTS))
from evidence.accounting import Accounting
from evidence.io import EvidenceError
from evidence.policy import load_defaults
from evidence import process_identity, producer, producer_runtime as runtime


class AbandonedAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sdd-abandoned-accounting-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'output'
        self.output.mkdir()
        self.policy = load_defaults()
        self.policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider='local')
        self.ledger = Accounting(self.root / 'state' / 'accounting.sqlite', self.policy['project_id'], self.policy)
        self.addCleanup(self.ledger.close)
        guardian = subprocess.Popen([sys.executable, '-B', '-c', 'import sys; sys.stdin.buffer.read()'],
                                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            owner = process_identity.identity(guardian.pid)
        finally:
            guardian.stdin.close()
            guardian.wait(timeout=5)
        self.sentinel = subprocess.Popen([sys.executable, '-B', '-c', 'import sys; sys.stdin.buffer.read()'],
                                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.close_sentinel)
        self.attempt = str(uuid.uuid4())
        self.reservation = self.ledger.reserve('abandoned', 'unit', 65536, 20,
                                               local_bytes=65536, metadata_bytes=3 * 1024 * 1024)
        self.output_id = self.ledger.register_output('abandoned', 'unit', self.output)
        (self.output / 'observation.txt').write_bytes(b'preserved original')
        self.original = {'version': 1, 'attempt_id': self.attempt, 'run_id': 'abandoned', 'unit_id': 'unit',
                         'reservation_id': self.reservation, 'output_id': self.output_id, 'intent_id': None,
                         'coordinator': process_identity.identity(), 'guardian': owner, 'status': 'running',
                         'processes': {}, 'resources': [], 'output_dir': str(self.output),
                         'output_identity': runtime.directory_identity(self.output), 'policy': self.policy,
                         'observed_bytes': 230, 'observed_files': 3}
        self.ledger.connection.execute('INSERT INTO producer_sessions VALUES(?,?)', (self.attempt, json.dumps(self.original)))

    def close_sentinel(self):
        if self.sentinel.stdin:
            self.sentinel.stdin.close()
        self.sentinel.wait(timeout=5)

    def record(self):
        return runtime.read(self.ledger, self.attempt)

    def assert_preserved(self):
        snapshot = self.ledger.snapshot()
        self.assertFalse(snapshot['accounting_complete'])
        self.assertTrue(snapshot['totals_are_lower_bounds'])
        self.assertEqual(230, snapshot['totals']['project_generated_bytes'])
        self.assertEqual(3, snapshot['totals']['project_generated_files'])
        self.assertEqual(65536, snapshot['totals']['pending_generated_bytes'])
        self.assertEqual(20, snapshot['totals']['pending_generated_files'])
        self.assertEqual(65536, snapshot['totals']['pending_local_bytes'])
        self.assertEqual('incomplete', snapshot['runs'][0]['status'])
        self.assertIsNone(self.sentinel.poll(), 'recovery stopped an unrelated sentinel')
        self.assertEqual(b'preserved original', (self.output / 'observation.txt').read_bytes())
        current = self.record()
        for key in self.original.keys() - {'status'}:
            self.assertEqual(self.original[key], current[key], key)
        self.assertIsNone(current.get('recovery_owner'))

    def test_floor_precedes_throwing_cleanup_and_repeated_recovery_is_idempotent(self):
        def fail_before_verification(ledger, attempt):
            # These invariants must already be durable before cleanup starts.
            with Accounting(self.ledger.path, self.policy['project_id'], self.policy) as observer:
                snapshot = observer.snapshot()
                self.assertFalse(snapshot['accounting_complete'])
                self.assertEqual(230, snapshot['totals']['project_generated_bytes'])
                self.assertEqual('incomplete', snapshot['runs'][0]['status'])
            raise PermissionError(1, 'injected cleanup before verification', str(self.output))
        first_failure = None
        for _ in range(2):
            with patch.object(runtime, 'stop_registered', side_effect=fail_before_verification), patch.object(runtime, 'verify_stopped') as verify:
                result = producer.recover_producers(self.ledger, dry_run=False)
            verify.assert_not_called()
            self.assertTrue(result['incomplete'])
            self.assertIn('injected cleanup before verification', result['actions'][0]['problem'])
            self.assertEqual('stopping', self.record()['status'])
            self.assertIn('injected cleanup before verification', self.record()['recovery_problem'])
            if first_failure is None:
                first_failure = deepcopy(self.record()['first_recovery_failure'])
            self.assertEqual(first_failure, self.record()['first_recovery_failure'])
            self.assert_preserved()
            with self.assertRaises(EvidenceError):
                self.ledger.reserve('unsafe-retry', 'unit', 1, 1)
        # Exact native helpers/resources are now verifiably absent. The real
        # recovery reaches terminal while keeping unknown accounting held.
        result = producer.recover_producers(self.ledger, dry_run=False)
        self.assertTrue(result['incomplete'])
        self.assertEqual('terminal', self.record()['status'])
        self.assertIsNone(self.record()['recovery_problem'])
        self.assertEqual(first_failure, self.record()['first_recovery_failure'])
        self.assert_preserved()
        producer.recover_producers(self.ledger, dry_run=False)
        self.assert_preserved()

    def test_healthy_abandoned_cleanup_reaches_terminal_without_refunding_hold(self):
        result = producer.recover_producers(self.ledger, dry_run=False)
        self.assertTrue(result['incomplete'])
        self.assertEqual('terminal', self.record()['status'])
        self.assertNotIn('first_recovery_failure', self.record())
        self.assert_preserved()

    def test_returned_cleanup_error_preserves_first_failure_after_success(self):
        with patch.object(runtime, 'stop_registered', return_value=['injected returned cleanup failure']):
            result = producer.recover_producers(self.ledger, dry_run=False)
        self.assertTrue(result['incomplete'])
        self.assertEqual('stopping', self.record()['status'])
        self.assertEqual('injected returned cleanup failure', self.record()['recovery_problem'])
        first = deepcopy(self.record()['first_recovery_failure'])
        self.assertEqual('injected returned cleanup failure', first['problem'])
        self.assert_preserved()
        result = producer.recover_producers(self.ledger, dry_run=False)
        self.assertTrue(result['incomplete'])
        self.assertEqual('terminal', self.record()['status'])
        self.assertIsNone(self.record()['recovery_problem'])
        self.assertEqual(first, self.record()['first_recovery_failure'])
        self.assert_preserved()

    def test_guardian_loss_diagnostic_contains_actual_bounded_target_problem(self):
        result = {'incomplete': True, 'actions': [
            {'attempt_id': 'unrelated', 'action': 'retained', 'problem': 'unrelated-secret-context'},
            {'attempt_id': self.attempt, 'action': 'retained', 'incomplete': True,
             'problem': 'injected cleanup before verification ' + '\u1234' * 10000}]}
        diagnostic = producer._recovery_failure_diagnostic(result, self.attempt)
        self.assertIn('injected cleanup before verification', diagnostic)
        self.assertNotIn('unrelated-secret-context', diagnostic)
        self.assertLess(len(diagnostic.encode()), 8192)
        self.assertEqual(self.attempt, json.loads(diagnostic)['attempt_id'])


if __name__ == '__main__':
    unittest.main()
