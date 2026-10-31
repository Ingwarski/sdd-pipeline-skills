"""CLI adoption/recovery on isolated synthetic projects and local durable stores."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_optional_diagnostics as diagnostic_fixture
import test_evidence_manager as storage_fixture
from evidence.io import EvidenceError, atomic_json, hash_file
from evidence.manager import Manager
from evidence import lifecycle_cli
from evidence_store import checkpoint_after_history, history_publication_guard, probe

ROOT = Path(__file__).resolve().parents[1]


class LifecycleCliTests(unittest.TestCase):
    def setUp(self):
        self.diagnostics = diagnostic_fixture.OptionalDiagnosticsTests()
        self.diagnostics.setUp()
        self.addCleanup(self.diagnostics.doCleanups)
        self.p, self.m = self.diagnostics.p, self.diagnostics.m
        self.p.save()
        self.storage = storage_fixture.EvidenceManagerTests()
        self.storage.setUp()
        self.addCleanup(self.storage.doCleanups)
        self.policy = json.loads((self.p.root / 'forge/evidence-policy.json').read_text())
        self.manager = Manager(self.storage.transport, self.storage.home, self.policy, project=self.p.root)
        self.review = {'reviewer': 'synthetic-owner', 'reviewed_at': self.diagnostics.h.utcnow(),
                       'rationale': 'Isolated lifecycle CLI test; not real project authorization.'}
        self.manifest = self.p.root / 'forge/sdd-manifest.json'
        self.original = self.manifest.read_bytes()
        self.binding = self.storage.home / 'bindings' / (self.policy['project_id'] + '.json')
        self.binding.parent.mkdir(parents=True)
        config = {'version': 1, 'provider': 'local', 'project_id': self.policy['project_id'], 'store_id': self.policy['store_id'],
            'transport': 'local', 'destination': str(self.storage.store), 'evidence_home': str(self.storage.home)}
        atomic_json(self.binding, config)
        config['setup_receipt'] = probe(SimpleNamespace(config=str(self.binding), host_session=None))
        atomic_json(self.binding, config)

    def adopt(self):
        return lifecycle_cli.adopt(self.manager, participant_id='synthetic-main',
            manifest_path='forge/sdd-manifest.json', review=self.review, members=[], automatic_cleanup=True)

    def test_adoption_retry_preserves_original_records_and_creates_no_new_execution(self):
        history_before = {str(path.relative_to(self.p.root)): path.read_bytes()
                          for path in (self.p.root / 'forge/unit-history').rglob('*') if path.is_file()}
        first = self.adopt()
        root = self.manager._catalog()['root_key']
        manifest = self.manifest.read_bytes()
        self.assertFalse(first['new_execution'])
        second = self.adopt()
        self.assertEqual(first['optional_diagnostics_ref'], second['optional_diagnostics_ref'])
        self.assertEqual(root, self.manager._catalog()['root_key'])
        self.assertEqual(manifest, self.manifest.read_bytes())
        for relative, data in history_before.items():
            self.assertEqual(data, (self.p.root / relative).read_bytes())
        self.assertEqual(self.m['unit_runs'] if 'unit_runs' in self.m else None,
                         json.loads(manifest).get('unit_runs'))

    def test_failed_publication_retries_exact_candidate_without_rewriting_history(self):
        with patch.object(self.manager, 'adopt_lifecycle', side_effect=EvidenceError('synthetic publication interruption')):
            with self.assertRaisesRegex(EvidenceError, 'publication interruption'):
                self.adopt()
        candidate = self.manifest.read_bytes()
        self.assertNotEqual(self.original, candidate)
        self.assertEqual('adopted', self.adopt()['result'])
        self.assertEqual(candidate, self.manifest.read_bytes())

    def test_changed_manifest_after_interruption_is_not_overwritten(self):
        with patch.object(self.manager, 'adopt_lifecycle', side_effect=EvidenceError('synthetic interruption')):
            with self.assertRaises(EvidenceError):
                self.adopt()
        changed = json.loads(self.manifest.read_bytes())
        changed['synthetic-new-work'] = True
        atomic_json(self.manifest, changed)
        before = self.manifest.read_bytes()
        with self.assertRaisesRegex(EvidenceError, 'manifest changed'):
            self.adopt()
        self.assertEqual(before, self.manifest.read_bytes())

    def test_changed_inputs_after_interrupted_adoption_are_not_silently_reused(self):
        with patch.object(self.manager, 'adopt_lifecycle', side_effect=EvidenceError('transport unavailable')):
            with self.assertRaisesRegex(EvidenceError, 'transport unavailable'):
                self.adopt()
        self.p.write('docs/product-idea.md', 'Changed product input after review.\n')
        with self.assertRaisesRegex(EvidenceError, 'inputs changed'):
            self.adopt()

    def test_history_publication_holds_the_same_lock_as_cleanup(self):
        self.adopt()
        with history_publication_guard(self.p.root, 'forge/sdd-manifest.json',
                                       evidence_cache=self.manager.cache) as writer:
            self.assertIsNotNone(writer)
            with self.assertRaisesRegex(EvidenceError, 'busy'):
                with self.manager.locked(timeout=0.01):
                    self.fail('cleanup acquired the history writer lock')

    def test_legacy_publication_serializes_with_adoption_without_provider_session(self):
        with patch('evidence_store.transport', side_effect=AssertionError('legacy work opened provider')):
            with history_publication_guard(self.p.root, 'forge/sdd-manifest.json',
                                           evidence_cache=self.manager.cache) as writer:
                self.assertIsNone(writer)
                with self.assertRaisesRegex(EvidenceError, 'busy'):
                    with self.manager.locked(timeout=0.01):
                        self.fail('adoption raced legacy history publication')

    def test_registered_older_manifest_still_refreshes_inventory(self):
        from evidence.lifecycle_cli import checkpoint
        self.adopt()
        manifest = json.loads(self.manifest.read_bytes())
        manifest['history_integrity'].pop('optional_diagnostics_ref')
        atomic_json(self.manifest, manifest)
        with history_publication_guard(self.p.root, 'forge/sdd-manifest.json',
                                       evidence_cache=self.manager.cache) as writer:
            updated = checkpoint(writer)
        self.assertTrue(updated['changed'], updated)

    def test_unregistered_writer_with_older_manifest_is_blocked_before_publication(self):
        self.adopt()
        manifest = json.loads(self.manifest.read_bytes())
        manifest['history_integrity'].pop('optional_diagnostics_ref')
        atomic_json(self.manifest, manifest)
        atomic_json(self.manager.state / 'lifecycle-bindings.json', {'version': 1, 'participants': {}})
        before = self.manifest.read_bytes()
        with self.assertRaisesRegex(EvidenceError, 'writer must register'):
            with history_publication_guard(self.p.root, 'forge/sdd-manifest.json',
                                           evidence_cache=self.manager.cache):
                self.fail('unregistered writer reached publication')
        self.assertEqual(before, self.manifest.read_bytes())

    def test_public_cli_and_read_only_status_use_only_isolated_binding(self):
        review_path = self.storage.base / 'review.json'
        atomic_json(review_path, self.review)
        command = [sys.executable, '-B', str(ROOT / 'skills/to-sdd-pipeline/scripts/evidence_store.py')]
        common = ['--project', str(self.p.root), '--home', str(self.storage.home)]
        environment = dict(os.environ, SDD_EVIDENCE_HOME=str(self.storage.home))
        adopted = subprocess.run(command + ['lifecycle-adopt', *common, '--participant', 'synthetic-main',
            '--review', str(review_path)], env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(0, adopted.returncode, adopted.stdout + adopted.stderr)
        self.assertFalse(json.loads(adopted.stdout)['new_execution'])
        before = {str(path.relative_to(self.storage.store)): hash_file(path)
                  for path in self.storage.store.rglob('*') if path.is_file()}
        status = subprocess.run(command + ['lifecycle-status', *common], env=environment,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(0, status.returncode, status.stdout + status.stderr)
        self.assertTrue(json.loads(status.stdout)['adopted'])
        after = {str(path.relative_to(self.storage.store)): hash_file(path)
                 for path in self.storage.store.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_history_checkpoint_noop_does_not_change_acceptance_or_catalog(self):
        self.adopt()
        before = self.manifest.read_bytes()
        root = self.manager._catalog()['root_key']
        status = checkpoint_after_history(self.p.root, 'forge/sdd-manifest.json', evidence_cache=self.manager.cache)
        self.assertNotEqual('cleanup_deferred', status.get('status'), status)
        self.assertEqual(root, self.manager._catalog()['root_key'])
        self.assertEqual(before, self.manifest.read_bytes())


if __name__ == '__main__':
    unittest.main()
