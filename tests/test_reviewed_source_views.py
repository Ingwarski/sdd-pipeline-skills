"""Selected reviewed proof uses existing prepared views, never a payload copy."""
import copy
from pathlib import Path
import unittest
from unittest import mock

import test_evidence_manager as storage_fixture
from test_sdd_check import sdd


class ReviewedSourceViewTests(unittest.TestCase):
    def setUp(self):
        self.storage = storage_fixture.EvidenceManagerTests('runTest')
        self.storage.setUp()
        self.addCleanup(self.storage.doCleanups)
        self.manager, self.cache = self.storage.manager, self.storage.manager.cache
        self.h = sdd.history_api()
        self.project = self.storage.base / 'reviewed-source-project'
        self.project.mkdir()
        self.root = self.h.HISTORY + '/legacy/synthetic/files'
        self.files = {name: self.h.write_snapshot(self.project, self.root + '/' + name, data)
                      for name, data in {'src/a.txt': b'first input', 'src/b.txt': b'second input',
                                         'inactive/output.bin': b'unrelated historical payload'}.items()}
        record = {'event': 'legacy_execution_archive', 'version': 2,
                  'snapshot_root': self.root, 'files': self.files}
        self.original_ref = self.h.store_record(self.project, 'synthetic-source-view', record)
        specifications = [{'path': str(self.project / frozen['path']), 'original_path': frozen['path'],
                           'sealed_at': storage_fixture.SEALED, 'kind': 'source_snapshot', 'schema': 'evidence-bytes-v1',
                           'provenance': {'run_id': 'synthetic-transport', 'unit_id': 'UNIT-01'},
                           'bindings': {'original_snapshot': copy.deepcopy(frozen)}} for frozen in self.files.values()]
        self.refs = self.manager.archive({'version': 1, 'files': specifications})
        self.manager.prepare(self.refs)
        self.sources = [{**frozen, 'evidence_ref': ref} for frozen, ref in zip(self.files.values(), self.refs)]
        self.records = [{'record_ref': self.original_ref, 'snapshot_root': self.root, 'sources': self.sources}]
        self.index = self.h.create_source_archive_index(self.project, self.records, evidence_cache=self.cache)
        self.h.prepare_source_views(self.project, self.index, evidence_cache=self.cache, max_bytes=1000000, max_files=1000)
        self.selected = {name: frozen for name, frozen in self.files.items() if name.startswith('src/')}

    def archive(self):
        return self.h.SourceArchive(self.project, self.index, self.cache)

    def test_selected_proof_does_not_read_missing_inactive_payload_or_copy_views(self):
        inactive = self.refs[-1]
        (self.cache / 'objects' / inactive['sha256']).unlink()
        before = sorted(str(path) for path in self.cache.rglob('*'))
        archive = self.archive()
        with mock.patch.object(archive.resolver, 'resolve', wraps=archive.resolver.resolve) as resolve:
            path = self.h.source_view_path(self.project, self.root, self.selected, 'src/a.txt', archive)
            self.assertEqual(b'first input', path.read_bytes())
            archive.audit()
            self.assertNotIn(inactive['artifact_id'], {call.args[0]['artifact_id'] for call in resolve.call_args_list})
        self.assertEqual(before, sorted(str(path) for path in self.cache.rglob('*')))
        with self.assertRaises((ValueError, OSError)):
            self.archive().validate_view(self.root, self.files)

    def test_directory_selection_requires_complete_membership_and_checks_exit_mutation(self):
        partial = {'src/a.txt': self.files['src/a.txt']}
        with self.assertRaisesRegex(ValueError, 'omits original'):
            self.h.source_view_path(self.project, self.root, partial, 'src', self.archive())
        with self.assertRaisesRegex(ValueError, 'outside selected'):
            self.h.source_view_path(self.project, self.root, partial, 'src/b.txt', self.archive())
        with self.assertRaisesRegex(ValueError, 'membership changed'):
            with self.h.source_archive_scope(self.project, self.index, self.cache):
                tree = self.h.source_view_path(self.project, self.root, self.selected, 'src')
                (tree / 'added.txt').write_bytes(b'undeclared input')

    def test_selected_payload_corruption_and_symlinks_remain_errors(self):
        archive = self.archive()
        descriptor = archive.descriptor(self.root, self.files)
        path = archive.location(descriptor) / 'files/src/a.txt'
        path.write_bytes(b'corrupt active proof')
        with self.assertRaisesRegex(ValueError, 'hash/size/private-link'):
            self.h.source_view_path(self.project, self.root, self.selected, 'src/a.txt', self.archive())
        path.unlink()
        path.symlink_to(self.cache / 'objects' / self.refs[0]['sha256'])
        with self.assertRaisesRegex(ValueError, 'links'):
            self.h.source_view_path(self.project, self.root, self.selected, 'src/a.txt', self.archive())

    def test_other_native_history_does_not_gain_subset_semantics(self):
        archive = self.archive()
        archive.originals[self.root]['event'] = 'unit_execution_context'
        with self.assertRaisesRegex(ValueError, 'complete prepared'):
            self.h.source_view_path(self.project, self.root, self.selected, 'src/a.txt', archive)

    def test_external_observation_sources_have_explicit_version_one_membership(self):
        original = self.h.read_ref(self.project, self.original_ref)
        original.update(event='external_check_observations', version=1)
        reference = self.h.store_record(self.project, 'synthetic-external-source', original)
        records = copy.deepcopy(self.records)
        records[0]['record_ref'] = reference
        index = self.h.create_source_archive_index(self.project, records, evidence_cache=self.cache)
        self.h.prepare_source_views(self.project, index, evidence_cache=self.cache, max_bytes=1000000, max_files=1000)
        archive = self.h.SourceArchive(self.project, index, self.cache)
        path = self.h.source_view_path(self.project, self.root, self.selected, 'src/a.txt', archive)
        self.assertEqual(b'first input', path.read_bytes())
        archive.audit()


if __name__ == '__main__':
    unittest.main()
