"""Opt-in native history transport, using synthetic projects and local mock stores."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import test_unit_history as history_fixture
import test_attempt_history as attempt_fixture
import test_attempt_policy_lineage as policy_fixture
from test_evidence_policy_lineage import setup_bytes
import test_evidence_manager as manager_fixture
from test_sdd_check import SCRIPT, sdd


class HistorySourceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fixture = history_fixture.UnitHistoryTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.p, self.m = self.fixture.p, self.fixture.m
        self.storage = manager_fixture.EvidenceManagerTests('runTest')
        self.storage.setUp()
        self.addCleanup(self.storage.doCleanups)
        self.manager = self.storage.manager
        self.cache = self.manager.cache
        self.helper, self.inventory, self.context, self.completion = self.fixture.capture_alpha()
        self.original_gate = copy.deepcopy(self.m['implementation_gate'])
        self.envelopes = {ref['path']: (self.p.root / ref['path']).read_bytes() for ref in (self.context, self.completion)}
        self.archive_records((self.context, self.completion))

    def archive_records(self, references):
        self.batch = getattr(self, 'batch', 0) + 1
        self.records = []
        specifications = []
        frozen_sources = []
        for reference in references:
            original = self.helper.read_ref(self.p.root, reference)
            sources = []
            for frozen in original['files'].values():
                frozen_sources.append((sources, frozen))
                specifications.append({'path': str((self.p.root / frozen['path']).resolve()), 'original_path': frozen['path'],
                    'sealed_at': manager_fixture.SEALED, 'kind': 'source_snapshot', 'schema': 'evidence-bytes-v1',
                    'provenance': {'run_id': 'synthetic-source-transport-' + str(self.batch), 'unit_id': 'U-1'},
                    'bindings': {'original_snapshot': copy.deepcopy(frozen)}})
            self.records.append({'record_ref': copy.deepcopy(reference), 'snapshot_root': original['snapshot_root'], 'sources': sources})
        self.refs = self.manager.archive({'version': 1, 'files': specifications})
        self.manager.prepare(self.refs)
        for (sources, frozen), ref in zip(frozen_sources, self.refs):
            sources.append({**frozen, 'evidence_ref': ref})
        self.index = self.helper.create_source_archive_index(self.p.root, self.records, evidence_cache=self.cache)
        self.m['source_archive_index_ref'] = self.index

    def prepare(self):
        return self.helper.prepare_source_views(self.p.root, self.index, evidence_cache=self.cache,
                                               max_bytes=10 * 1024 * 1024, max_files=10000)

    def remove_sources(self):
        for entry in self.records:
            for source in entry['sources']:
                (self.p.root / source['path']).unlink()
        shutil.rmtree(self.p.root / self.helper.HISTORY / 'blobs')

    def checker(self, manifest=None):
        return sdd.Checker(self.p.root, manifest or self.m, evidence_cache=self.cache)

    def report(self):
        return self.checker().run('development-plan', after=True)

    def assert_blocked(self):
        try:
            report = self.report()
        except (ValueError, OSError):
            return
        self.assertNotEqual('passed', report['result'], report)

    def test_native_capture_index_prepare_cold_history_preserves_authority(self):
        inventory = self.helper.SourceArchive(self.p.root, self.index, self.cache)
        with mock.patch.object(inventory.resolver, 'resolve', side_effect=AssertionError('metadata-only inventory must not resolve payloads')):
            planned = inventory.source_inventory()
        before = self.report()
        self.assertNotEqual('passed', before['result'], before)  # Explicit full views are required.
        result = self.prepare()
        logical_bytes = sum(ref['size'] for ref in self.refs)
        self.assertLess(result['unique_copied_bytes'], logical_bytes)
        self.assertGreaterEqual(result['views'], 2)
        metrics = result['source_inventory']
        self.assertEqual(planned, metrics)
        self.assertEqual(len(self.refs), metrics['mapping_count'])
        self.assertEqual(len({ref['artifact_id'] for ref in self.refs}), metrics['unique_refs'])
        self.assertEqual(len({ref['sha256'] for ref in self.refs}), metrics['unique_sha256'])
        self.assertEqual(result['unique_copied_bytes'], metrics['declared_unique_bytes'])
        self.remove_sources()
        original = self.report()
        self.assertEqual('passed', original['result'], original)
        self.assertTrue(original['unit_history']['units']['U-1']['historical_valid'])
        self.assertEqual('authorized', original['execution_authority']['status'])
        self.assertEqual(self.original_gate, self.m['implementation_gate'])
        self.assertEqual(self.envelopes, {path: (self.p.root / path).read_bytes() for path in self.envelopes})
        with mock.patch('subprocess.run', side_effect=AssertionError('read-only checker cannot fetch')):
            self.assertEqual(original, self.report())
        # An offline copy contains the exact same Git-eligible metadata and source refs.
        cold = self.storage.base / 'cold-project'
        shutil.copytree(self.p.root, cold)
        offline = sdd.Checker(cold, copy.deepcopy(self.m), evidence_cache=self.cache).run('development-plan', after=True)
        self.assertEqual(original, offline)

    def test_independent_old_manifest_does_not_autoselect_index(self):
        self.prepare()
        self.remove_sources()
        self.assertEqual('passed', self.report()['result'])
        old = copy.deepcopy(self.m)
        old.pop('source_archive_index_ref')
        result = self.checker(old).run('development-plan', after=True)
        self.assertNotEqual('passed', result['result'])
        # Original local shape still works on a fresh capture, with no index selection.
        fresh = history_fixture.UnitHistoryTests('runTest')
        fresh.setUp()
        self.addCleanup(fresh.doCleanups)
        fresh.capture_alpha()
        self.assertEqual('passed', fresh.report()['result'])

    def test_cache_miss_corruption_alias_and_schema_are_fail_closed(self):
        self.prepare()
        self.remove_sources()
        ref = self.refs[0]
        source = self.cache / 'objects' / ref['sha256']
        original = source.read_bytes()
        source.unlink()
        self.assert_blocked()
        source.write_bytes(original + b'corrupt')
        self.assert_blocked()
        source.write_bytes(original)
        receipt = self.cache / 'receipts' / (ref['artifact_id'] + '.json')
        saved = receipt.read_bytes()
        altered = json.loads(saved)
        alias = copy.deepcopy(ref)
        alias['sha256'] = 'f' * 64
        altered['original_references'] = [alias]
        receipt.write_text(json.dumps(altered))
        self.assert_blocked()
        receipt.write_bytes(saved)
        self.assertEqual('passed', self.report()['result'])
        invalid = copy.deepcopy(self.records)
        invalid[0]['sources'][0]['evidence_ref']['schema'] = 'evidence-json-v1'
        with self.assertRaisesRegex(ValueError, 'schema'):
            self.helper.create_source_archive_index(self.p.root, invalid, evidence_cache=self.cache)

    def test_mapping_foreign_membership_root_hash_and_duplicate_rejected(self):
        mutations = [lambda x: x[0]['sources'][0].update(path='forge/unit-history/foreign/files/test.txt'),
                     lambda x: x[0]['sources'][0].update(content_hash='f' * 64),
                     lambda x: x[0].update(snapshot_root='forge/unit-history/foreign/files'),
                     lambda x: x[0]['sources'].append(copy.deepcopy(x[0]['sources'][0])),
                     lambda x: x[0]['sources'][0].update(path='../escape')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                invalid = copy.deepcopy(self.records)
                mutation(invalid)
                with self.assertRaises(ValueError):
                    self.helper.create_source_archive_index(self.p.root, invalid, evidence_cache=self.cache)

    def test_directory_membership_symlink_and_view_corruption_rejected(self):
        self.prepare()
        self.remove_sources()
        tree = next((self.cache / 'source-views').glob('*/views/*/files'))
        extra = tree / 'unexpected.txt'
        extra.write_bytes(b'extra')
        self.assert_blocked()
        extra.unlink()
        extra_dir = tree / 'extra-directory'
        extra_dir.mkdir()
        self.assert_blocked()
        extra_dir.rmdir()
        path = next(path for path in tree.rglob('*') if path.is_file())
        data = path.read_bytes()
        path.unlink()
        path.symlink_to(self.cache / 'objects' / self.refs[0]['sha256'])
        self.assert_blocked()
        path.unlink()
        path.write_bytes(data + b'corrupt')
        self.assert_blocked()
        path.unlink()
        digest = self.helper.sha(data)
        blob = self.cache / 'source-views' / self.index['content_hash'] / 'blobs' / digest
        os.link(blob, path)
        self.assertEqual('passed', self.report()['result'])

    def test_missing_view_cannot_replace_directory_and_capacity_precedes_writes(self):
        with self.assertRaisesRegex(ValueError, 'capacity'):
            self.helper.prepare_source_views(self.p.root, self.index, evidence_cache=self.cache, max_bytes=1, max_files=10000)
        self.assertFalse((self.cache / 'source-views').exists())
        with self.assertRaisesRegex(ValueError, 'capacity'):
            self.helper.prepare_source_views(self.p.root, self.index, evidence_cache=self.cache, max_bytes=10**8, max_files=1)
        self.prepare()
        self.remove_sources()
        view = next((self.cache / 'source-views').glob('*/views/*'))
        shutil.rmtree(view)
        self.assert_blocked()

    def test_current_source_drift_requires_revalidation_without_rewriting_history(self):
        self.prepare()
        self.remove_sources()
        self.p.write('src/alpha.txt', 'Changed after original execution.\n')
        report = self.report()
        unit = report['unit_history']['units']['U-1']
        self.assertTrue(unit['historical_valid'], report)
        self.assertEqual('needs_revalidation', unit['current_applicability'])
        self.assertIn('stale', str(unit['reasons']))
        self.assertEqual(self.envelopes, {path: (self.p.root / path).read_bytes() for path in self.envelopes})

    def test_stage_activate_resolve_candidate_index_without_refreshing_authority(self):
        self.prepare()
        self.remove_sources()
        expected = self.p.hash('forge/sdd-manifest.json')  # Active manifest intentionally predates optional field.
        candidate = self.helper.stage_candidate(self.p.root, self.m, expected, evidence_cache=self.cache)
        result = self.helper.activate_candidate(self.p.root, candidate, expected, evidence_cache=self.cache)
        self.assertEqual('activated', result['status'])
        current = json.loads((self.p.root / 'forge/sdd-manifest.json').read_text())
        self.assertEqual(self.original_gate, current['implementation_gate'])
        self.assertEqual(self.completion, current['unit_runs']['U-1']['completion_ref'])
        self.assertEqual(self.index, current['source_archive_index_ref'])

    def test_index_and_cache_receipt_changes_after_stage_block_activation(self):
        self.prepare()
        self.remove_sources()
        expected = self.p.hash('forge/sdd-manifest.json')
        staged = self.helper.stage_candidate(self.p.root, self.m, expected, evidence_cache=self.cache)
        receipt = self.cache / 'receipts' / (self.refs[0]['artifact_id'] + '.json')
        receipt.write_bytes(receipt.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'changed|restage'):
            self.helper.activate_candidate(self.p.root, staged, expected, evidence_cache=self.cache)
        self.assertEqual(expected, self.p.hash('forge/sdd-manifest.json'))
        index = self.p.root / self.index['path']
        index.write_bytes(index.read_bytes() + b'\n')
        self.assert_blocked()


    def test_failed_attempt_pre_and_post_views_keep_failed_results_through_activation(self):
        attempted = attempt_fixture.AttemptHistoryTests('runTest')
        attempted.setUp()
        self.addCleanup(attempted.doCleanups)
        attempted.start()
        (attempted.p.root / 'src/alpha.txt').unlink()  # Actual partial work after the old test observation.
        attempted.status_edit()
        reference = attempted.capture()
        self.p, self.m, self.helper = attempted.p, attempted.m, attempted.helper
        self.context, self.completion = attempted.context, reference
        failed_checks = copy.deepcopy(self.m['verification']['checks'])
        authority = copy.deepcopy(self.m['implementation_gate'])
        self.p.save()
        self.archive_records((self.context, reference))
        self.prepare()
        self.remove_sources()
        record, context = self.helper.validate_attempt(self.p.root, reference, evidence_cache=self.cache,
                                                       source_archive_index_ref=self.index)
        self.assertEqual('failed', record['checks'][0]['execution_status'])
        self.assertEqual('unverified_stale_inputs', record['observation_validity'])
        original = context['files']['docs/qa-checklist.md']
        actual = record['files']['docs/qa-checklist.md']
        self.assertNotEqual(original['content_hash'], actual['content_hash'])
        with self.helper.source_archive_scope(self.p.root, self.index, self.cache):
            before = self.helper.historical_checker(self.p.root, self.m, context, record, evidence_cache=self.cache)
            after = self.helper.historical_checker(self.p.root, self.m, context, record, original_canonical=False,
                                                   evidence_cache=self.cache)
            self.assertEqual(original['content_hash'], self.helper.sha(before.path('docs/qa-checklist.md').read_bytes()))
            self.assertEqual(actual['content_hash'], self.helper.sha(after.path('docs/qa-checklist.md').read_bytes()))
            self.assertFalse(after.path('src/alpha.txt').exists())  # Post-start deletion cannot resurrect pre-start bytes.
        expected = self.p.hash('forge/sdd-manifest.json')
        staged = self.helper.stage_candidate(self.p.root, self.m, expected, evidence_cache=self.cache)
        result = self.helper.activate_candidate(self.p.root, staged, expected, evidence_cache=self.cache)
        self.assertEqual('activated', result['status'])
        current = json.loads((self.p.root / 'forge/sdd-manifest.json').read_text())
        self.assertEqual(authority, current['implementation_gate'])
        self.assertEqual(failed_checks, current['verification']['checks'])
        complete = self.checker().run('implementation', unit_action='complete', unit_id='U-1')
        self.assertNotEqual('passed', complete['result'])

    def test_recorded_tree_keeps_empty_directories_and_detects_membership_changes(self):
        base = history_fixture.UnitHistoryTests('runTest')
        base.setUp()
        self.addCleanup(base.doCleanups)
        base.p.write('tests/native-tree/fixture.txt', 'Frozen tree input.\n')
        (base.p.root / 'tests/native-tree/empty/nested').mkdir(parents=True)
        inventory = base.inventory
        def reviewed(*args, **kwargs):
            value = inventory(*args, **kwargs)
            value['execution_inputs']['tests/native-tree'] = {'mode': 'tree'}
            return value
        base.inventory = reviewed
        self.helper, _, self.context, self.completion = base.capture_alpha()
        self.p, self.m = base.p, base.m
        self.archive_records((self.context, self.completion))
        self.prepare()
        self.remove_sources()
        report = self.report()
        self.assertEqual('passed', report['result'], report)
        roots = list((self.cache / 'source-views' / self.index['content_hash']).glob('views/*/files/tests/native-tree/empty/nested'))
        self.assertTrue(roots)
        roots[0].rmdir()
        self.assert_blocked()

    def test_preparation_failure_cleans_only_exclusive_view_tree(self):
        sentinel = self.cache / 'unrelated.txt'
        sentinel.write_bytes(b'preserve')
        with mock.patch.object(self.helper.os, 'link', side_effect=OSError('unsupported fixture links')):
            with self.assertRaisesRegex(ValueError, 'hardlink support'):
                self.prepare()
        self.assertFalse((self.cache / 'source-views' / self.index['content_hash']).exists())
        self.assertEqual(b'preserve', sentinel.read_bytes())
        self.assertEqual('prepared', self.prepare()['status'])

    def test_cache_root_symlink_and_view_receipt_tamper_block(self):
        self.prepare()
        receipt = next((self.cache / 'source-views').glob('*/views/*/receipt.json'))
        record = json.loads(receipt.read_text())
        record['index_ref']['content_hash'] = 'f' * 64
        receipt.write_text(json.dumps(record))
        self.assert_blocked()
        alias = self.storage.base / 'cache-alias'
        alias.symlink_to(self.cache, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.helper.create_source_archive_index(self.p.root, self.records, evidence_cache=alias)

    def test_cli_explicit_index_and_view_preparation(self):
        mapping = 'forge/source-mapping-fixture.json'
        self.p.write(mapping, json.dumps(self.records))
        args = [sys.executable, str(SCRIPT.with_name('sdd_history.py')), '--project', str(self.p.root),
                '--evidence-cache', str(self.cache)]
        index = subprocess.run(args + ['create-source-archive-index', '--mapping', mapping], capture_output=True, text=True)
        self.assertEqual(0, index.returncode, index.stdout + index.stderr)
        reference = json.loads(index.stdout)
        self.p.write('forge/source-index-ref-fixture.json', json.dumps(reference))
        prepared = subprocess.run(args + ['prepare-source-views', '--index-ref', 'forge/source-index-ref-fixture.json',
            '--max-bytes', str(10 * 1024 * 1024), '--max-files', '10000'], capture_output=True, text=True)
        self.assertEqual(0, prepared.returncode, prepared.stdout + prepared.stderr)
        self.assertEqual('prepared', json.loads(prepared.stdout)['status'])

    def test_reused_checker_rechecks_cache_and_detects_mid_invocation_drift(self):
        self.prepare()
        self.remove_sources()
        checker = self.checker()
        self.assertEqual('passed', checker.run('development-plan', after=True)['result'])
        path = self.cache / 'objects' / self.refs[0]['sha256']
        original = path.read_bytes()
        path.write_bytes(original + b'corrupt')
        result = checker.run('development-plan', after=True)
        self.assertNotEqual('passed', result['result'])
        path.write_bytes(original)
        checker = self.checker()
        implementation = checker._run_invocation
        def drift(*args, **kwargs):
            result = implementation(*args, **kwargs)
            path.write_bytes(original + b'drift')
            return result
        with mock.patch.object(checker, '_run_invocation', side_effect=drift):
            self.assertNotEqual('passed', checker.run('development-plan', after=True)['result'])

    def test_mapped_frozen_policy_successor_continuation_preserves_raw_ancestry(self):
        fixture = policy_fixture.AttemptPolicyLineageTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        attempt = fixture.archive()
        self.p, self.m, self.helper = fixture.p, fixture.m, fixture.helper
        self.context, self.completion = fixture.fixture.context, attempt
        original_records = {ref['path']: (self.p.root / ref['path']).read_bytes() for ref in (self.context, attempt)}
        self.archive_records((self.context, attempt))
        self.prepare()
        self.remove_sources()
        fixture.transition()
        reviewed = fixture.reviewed()
        result = self.helper.capture_continuation(self.p.root, self.m, 'U-1', attempt,
            'synthetic-mapped-policy-successor', reviewed, evidence_cache=self.cache)
        candidate = result['manifest']
        self.assertEqual([attempt], candidate['attempt_history']['U-1'])
        self.assertEqual(fixture.original_gate, candidate['implementation_gate'])
        self.assertEqual(fixture.original_accounting, candidate['evidence_accounting'])
        check = next(item for item in candidate['verification']['checks'] if item['check_id'] == 'QA-02')
        self.assertEqual('not_run', check['execution_status'])
        self.assertNotIn('evidence', check)
        # A semantically identical policy with a different raw ancestor cannot substitute.
        fixture.transition(raw=setup_bytes(fixture.policy))
        with self.assertRaisesRegex(ValueError, 'raw anchor|exact original|fingerprint'):
            self.helper.capture_continuation(self.p.root, self.m, 'U-1', attempt,
                'synthetic-forged-policy-ancestor', fixture.reviewed(), evidence_cache=self.cache)
        # Nor can a hash-mismatched prepared frozen policy supply ancestry.
        frozen_policy = next(source for source in self.records[1]['sources']
                             if source['path'].endswith('/forge/evidence-policy.json'))
        (self.cache / 'objects' / frozen_policy['evidence_ref']['sha256']).write_bytes(b'changed frozen policy')
        with self.assertRaisesRegex(ValueError, 'hash/size mismatch'):
            self.helper.capture_continuation(self.p.root, self.m, 'U-1', attempt,
                'synthetic-corrupt-policy-ancestor', fixture.reviewed(), evidence_cache=self.cache)
        self.assertEqual(original_records, {path: (self.p.root / path).read_bytes() for path in original_records})
        self.assertEqual(fixture.original_checks, self.m['verification']['checks'])

    def test_private_blob_cannot_be_forged_as_a_hardlink_to_ordinary_cache_object(self):
        self.prepare()
        self.remove_sources()
        ref = self.refs[0]
        digest = ref['sha256']
        source = self.cache / 'objects' / digest
        root = self.cache / 'source-views' / self.index['content_hash']
        blob = root / 'blobs' / digest
        views = []
        for receipt in root.glob('views/*/receipt.json'):
            descriptor = json.loads(receipt.read_text())['view']
            for logical, frozen in descriptor['files'].items():
                if self.helper.api().hash_matches(frozen['content_hash'], digest):
                    views.append(receipt.parent / 'files' / logical)
        self.assertTrue(views)
        blob.unlink()
        os.link(source, blob)
        for view in views:
            view.unlink()
            os.link(source, view)
        self.assertEqual(source.stat().st_ino, blob.stat().st_ino)
        self.assert_blocked()

    def test_index_consumer_byte_limit_preflights_before_immutable_write(self):
        document = {'event': 'unit_source_archive_index', 'version': 1, 'records': self.records}
        actual = len(self.helper.encoded(document))
        before = set((self.p.root / self.helper.HISTORY / 'source-indexes').rglob('*'))
        with mock.patch.object(self.helper, 'SOURCE_INDEX_MAX_BYTES', actual - 1, create=True):
            with self.assertRaisesRegex(ValueError, 'source archive index.*bytes.*limit'):
                self.helper.create_source_archive_index(self.p.root, self.records, evidence_cache=self.cache)
        self.assertEqual(before, set((self.p.root / self.helper.HISTORY / 'source-indexes').rglob('*')))
        with mock.patch.object(self.helper, 'SOURCE_INDEX_MAX_BYTES', actual, create=True):
            reference = self.helper.create_source_archive_index(self.p.root, self.records, evidence_cache=self.cache)
        self.assertEqual(document, self.helper.read_ref(self.p.root, reference))

    def test_view_receipt_consumer_byte_limit_preflights_before_any_view_write(self):
        with mock.patch.object(self.helper, 'SOURCE_VIEW_RECEIPT_MAX_BYTES', 1, create=True):
            with self.assertRaisesRegex(ValueError, 'source view receipt.*bytes.*limit'):
                self.prepare()
        self.assertFalse((self.cache / 'source-views').exists())
        self.assertEqual('prepared', self.prepare()['status'])

    def select_index(self, *, view_strategy='private_copy', encoding='inline', canonical=False):
        records = copy.deepcopy(self.records)
        if canonical:
            by_hash = {}
            for entry in records:
                for source in entry['sources']:
                    ref = source['evidence_ref']
                    source['evidence_ref'] = by_hash.setdefault(ref['sha256'], ref)
        self.index = self.helper.create_source_archive_index(self.p.root, records, evidence_cache=self.cache,
            view_strategy=view_strategy, encoding=encoding)
        self.m['source_archive_index_ref'] = self.index
        return records

    def test_shared_cache_links_bind_strategy_inodes_and_fresh_postassembly_resolution(self):
        self.select_index(view_strategy='shared_cache_links')
        objects = {ref['sha256']: self.cache / 'objects' / ref['sha256'] for ref in self.refs}
        content = {digest: path.read_bytes() for digest, path in objects.items()}
        observed = {'before': set(), 'after': set()}
        original = self.helper.EvidenceResolver.resolve
        def resolve(resolver, ref):
            phase = 'after' if (self.cache / 'source-views').exists() else 'before'
            observed[phase].add(id(resolver))
            return original(resolver, ref)
        with mock.patch.object(self.helper.EvidenceResolver, 'resolve', autospec=True, side_effect=resolve), \
             mock.patch.object(self.helper.shutil, 'copyfileobj', side_effect=AssertionError('shared assembly must not copy source bytes')):
            result = self.prepare()
        self.assertEqual('shared_cache_links', result['view_strategy'])
        self.assertEqual(0, result['unique_copied_bytes'])
        self.assertEqual(result['source_inventory']['declared_unique_bytes'], result['unique_linked_bytes'])
        self.assertTrue(observed['before'])
        self.assertTrue(observed['after'])
        self.assertTrue(observed['before'].isdisjoint(observed['after']))
        root = self.cache / 'source-views' / self.index['content_hash']
        for receipt in root.glob('views/*/receipt.json'):
            value = json.loads(receipt.read_text())
            self.assertEqual('shared_cache_links', value['view_strategy'])
            for logical, frozen in value['view']['files'].items():
                digest = frozen['content_hash']
                ordinary = objects[digest]
                alias = receipt.parent / 'files' / logical
                blob = root / 'blobs' / digest
                self.assertEqual((ordinary.stat().st_dev, ordinary.stat().st_ino), (alias.stat().st_dev, alias.stat().st_ino))
                self.assertEqual(ordinary.stat().st_ino, blob.stat().st_ino)
        self.assertEqual(content, {digest: path.read_bytes() for digest, path in objects.items()})
        self.remove_sources()
        self.assertEqual('passed', self.report()['result'])

    def test_shared_mode_receipt_index_alias_and_byte_tampering_reject(self):
        self.select_index(view_strategy='shared_cache_links')
        self.prepare()
        self.remove_sources()
        root = self.cache / 'source-views' / self.index['content_hash']
        receipt = next(root.glob('views/*/receipt.json'))
        saved_receipt = receipt.read_bytes()
        value = json.loads(saved_receipt)
        value['view_strategy'] = 'private_copy'
        receipt.write_text(json.dumps(value))
        self.assert_blocked()
        receipt.write_bytes(saved_receipt)
        logical, frozen = next(iter(value['view']['files'].items()))
        alias = receipt.parent / 'files' / logical
        ordinary = self.cache / 'objects' / frozen['content_hash']
        original = ordinary.read_bytes()
        alias.unlink()
        alias.write_bytes(original)  # Correct bytes at a foreign inode still fail.
        self.assert_blocked()
        alias.unlink()
        alias.symlink_to(ordinary)
        self.assert_blocked()
        alias.unlink()
        os.link(ordinary, alias)
        self.assertEqual('passed', self.report()['result'])
        alias.write_bytes(original + b'corrupt shared alias')
        self.assert_blocked()
        ordinary.write_bytes(original)
        self.assertEqual('passed', self.report()['result'])
        index = self.p.root / self.index['path']
        saved_index = index.read_bytes()
        document = json.loads(saved_index)
        document['view_strategy'] = 'private_copy'
        index.write_text(json.dumps(document))
        self.assert_blocked()
        index.write_bytes(saved_index)
        self.assertEqual('passed', self.report()['result'])

    def test_shared_alias_mutation_during_checker_invocation_blocks(self):
        self.select_index(view_strategy='shared_cache_links')
        self.prepare()
        self.remove_sources()
        alias = next(path for path in (self.cache / 'source-views').glob('*/views/*/files/**/*') if path.is_file())
        checker = self.checker()
        implementation = checker._run_invocation
        def drift(*args, **kwargs):
            result = implementation(*args, **kwargs)
            stamp = alias.stat()
            original = alias.read_bytes()
            self.assertTrue(original)
            alias.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            os.utime(alias, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            self.assertEqual(stamp.st_size, alias.stat().st_size)
            self.assertEqual(stamp.st_mtime_ns, alias.stat().st_mtime_ns)
            return result
        with mock.patch.object(checker, '_run_invocation', side_effect=drift):
            self.assertNotEqual('passed', checker.run('development-plan', after=True)['result'])

    def test_shared_view_survives_manager_reprepare_without_inode_replacement(self):
        self.select_index(view_strategy='shared_cache_links', encoding='sha_objects_v1', canonical=True)
        self.prepare()
        self.remove_sources()
        objects = {ref['sha256']: self.cache / 'objects' / ref['sha256'] for ref in self.refs}
        before = {digest: (path.stat().st_dev, path.stat().st_ino) for digest, path in objects.items()}
        self.manager.prepare(self.refs)
        self.assertEqual(before, {digest: (path.stat().st_dev, path.stat().st_ino) for digest, path in objects.items()})
        self.assertEqual('passed', self.report()['result'])

    def test_compact_encoding_roundtrips_all_members_with_identical_qa_and_authority(self):
        records = self.select_index(canonical=True)
        inline = self.index
        inline_doc = self.helper.read_ref(self.p.root, inline)
        inline_metrics = self.helper.SourceArchive(self.p.root, inline, self.cache).source_inventory()
        self.prepare()
        self.index = self.helper.create_source_archive_index(self.p.root, records, evidence_cache=self.cache,
            encoding='sha_objects_v1')
        compact = self.helper.read_ref(self.p.root, self.index)
        self.assertEqual('sha_objects_v1', compact['encoding'])
        self.assertEqual(inline_metrics['unique_sha256'], len(compact['objects']))
        self.assertLess(len(self.helper.encoded(compact)), len(self.helper.encoded(inline_doc)))
        archive = self.helper.SourceArchive(self.p.root, self.index, self.cache)
        expected = {source['path']: source for entry in records for source in entry['sources']}
        self.assertEqual(expected, archive.sources)
        self.assertEqual(inline_metrics, archive.source_inventory())
        self.prepare()
        self.remove_sources()
        self.m['source_archive_index_ref'] = inline
        before = self.report()
        self.m['source_archive_index_ref'] = self.index
        after = self.report()
        self.assertEqual('passed', before['result'], before)
        self.assertEqual(before, after)
        self.assertEqual(self.original_gate, self.m['implementation_gate'])
        self.assertEqual(self.envelopes, {path: (self.p.root / path).read_bytes() for path in self.envelopes})
        self.p.write('src/alpha.txt', 'Actual later source drift.\n')
        stale = self.report()['unit_history']['units']['U-1']
        self.assertTrue(stale['historical_valid'])
        self.assertEqual('needs_revalidation', stale['current_applicability'])

    def test_compact_wrong_objects_duplicates_and_missing_members_reject(self):
        with self.assertRaisesRegex(ValueError, 'conflicting compact source references'):
            self.helper.create_source_archive_index(self.p.root, self.records, evidence_cache=self.cache,
                encoding='sha_objects_v1')
        self.select_index(encoding='sha_objects_v1', canonical=True)
        original = self.helper.read_ref(self.p.root, self.index)
        key = next(iter(original['objects']))
        mutations = [lambda value: value['objects'][key].update(sha256=self.helper.sha(b'wrong original source')),
                     lambda value: value['objects'][key].update(size=value['objects'][key]['size'] + 1),
                     lambda value: value['objects'].pop(key),
                     lambda value: value['records'][0]['sources'].pop(),
                     lambda value: value['records'][0]['sources'][0].update(object_key=self.helper.sha(b'foreign source object')),
                     lambda value: value['records'][0]['sources'].append(copy.deepcopy(value['records'][0]['sources'][0]))]
        for mutation in mutations:
            value = copy.deepcopy(original)
            mutation(value)
            ref = self.helper.store_record(self.p.root, 'source-indexes', value)
            with self.assertRaises(ValueError):
                archive = self.helper.SourceArchive(self.p.root, ref, self.cache)
                for source in archive.sources.values():
                    archive.source({name: source[name] for name in self.helper.REF_KEYS})
        # Duplicate JSON keys are rejected by the actual native envelope reader.
        data = self.helper.encoded(original).decode()
        needle = '"objects": {'
        addition = needle + '\n    ' + json.dumps(key) + ': ' + json.dumps(original['objects'][key]) + ','
        data = data.replace(needle, addition, 1)
        ref = self.helper.write_new(self.p.root, self.helper.HISTORY + '/source-indexes/duplicate-objects/record.json', data.encode())
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.helper.SourceArchive(self.p.root, ref, self.cache)

    def test_shared_mode_requires_complete_mapped_ordinary_sources(self):
        partial = copy.deepcopy(self.records)
        partial[0]['sources'].pop()
        with self.assertRaisesRegex(ValueError, 'complete source archive membership'):
            self.helper.create_source_archive_index(self.p.root, partial, evidence_cache=self.cache,
                view_strategy='shared_cache_links')

    def test_cli_explicit_shared_compact_index_and_preparation(self):
        records = self.select_index(canonical=True)
        self.p.write('forge/shared-source-mapping.json', json.dumps(records))
        args = [sys.executable, str(SCRIPT.with_name('sdd_history.py')), '--project', str(self.p.root),
                '--evidence-cache', str(self.cache)]
        created = subprocess.run(args + ['create-source-archive-index', '--mapping', 'forge/shared-source-mapping.json',
            '--view-strategy', 'shared_cache_links', '--encoding', 'sha_objects_v1'], capture_output=True, text=True)
        self.assertEqual(0, created.returncode, created.stdout + created.stderr)
        reference = json.loads(created.stdout)
        record = self.helper.read_ref(self.p.root, reference)
        self.assertEqual('shared_cache_links', record['view_strategy'])
        self.assertEqual('sha_objects_v1', record['encoding'])
        self.p.write('forge/shared-source-index.json', json.dumps(reference))
        prepared = subprocess.run(args + ['prepare-source-views', '--index-ref', 'forge/shared-source-index.json',
            '--max-bytes', str(10 * 1024 * 1024), '--max-files', '10000'], capture_output=True, text=True)
        self.assertEqual(0, prepared.returncode, prepared.stdout + prepared.stderr)
        self.assertEqual(0, json.loads(prepared.stdout)['unique_copied_bytes'])

    def test_existing_local_corruption_still_fails_without_mapping(self):
        frozen = self.records[0]['sources'][0]
        (self.p.root / frozen['path']).write_bytes(b'corrupt-local')
        with self.assertRaisesRegex(ValueError, 'corrupt'):
            self.helper.create_source_archive_index(self.p.root, self.records, evidence_cache=self.cache)
        original = self.helper.read_ref(self.p.root, self.context)
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            self.helper.validate_files(self.p.root, original)


if __name__ == '__main__':
    unittest.main()
