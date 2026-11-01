"""Real native source views classified in isolated LocalTransport fixtures only."""
from copy import deepcopy
import json
import os
import shutil
from pathlib import Path, PurePosixPath, PureWindowsPath
import unittest
from unittest.mock import patch

import test_history_source_archive as sources
import test_unit_history as native
from evidence import policy as policies
from evidence.manager import Manager
from evidence.source_payloads import SourcePayloadScope


def payload_aliases(candidates, cache):
    """Test expectation only: payload alias directories inside this cache."""
    return {path for path in candidates if 'files' in path.relative_to(cache).parts[:-1]}


class PayloadAliasPathTests(unittest.TestCase):
    def check_path_flavor(self, flavor, root):
        cache = flavor(root)
        view = cache / 'source-views' / 'index' / 'views' / 'view'
        payloads = {view / 'files' / 'payload.json', view / 'files' / 'nested' / 'receipt.json'}
        controls = {view / 'receipt.json', cache / 'profiles' / 'control.json',
                    view / 'files-like' / 'control.json', cache / 'files.json'}
        self.assertEqual(payloads, payload_aliases(payloads | controls, cache))
        self.assertFalse(payload_aliases(controls, cache))

    def test_windows_components_keep_payloads_and_exclude_controls(self):
        self.check_path_flavor(PureWindowsPath, r'C:\fixture\files\cache')

    def test_posix_components_ignore_files_in_cache_ancestor_and_filename(self):
        self.check_path_flavor(PurePosixPath, '/fixture/files/cache')


class SourcePayloadClassificationTests(unittest.TestCase):
    def setUp(self):
        self.f = sources.HistorySourceArchiveTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.p, self.cache = self.f.p, self.f.cache
        self.policy = deepcopy(self.f.manager.policy)
        self.p.write('forge/evidence-policy.json', json.dumps(self.policy))
        self.f.select_index(view_strategy='shared_cache_links', encoding='sha_objects_v1', canonical=True)
        self.f.prepare()

    def candidates(self):
        return list(self.cache.rglob('*.json'))

    def aliases(self):
        return payload_aliases(self.cache.rglob('*.json'), self.cache)

    def scope(self, policy=None):
        return SourcePayloadScope(self.p.root, self.cache, self.policy if policy is None else policy)

    def aware_manager(self, policy=None):
        return Manager(self.f.storage.transport, self.f.storage.home,
            self.policy if policy is None else policy, project=self.p.root.resolve())

    def test_real_manager_filters_only_proved_payloads_and_preserves_occupancy(self):
        unknown = self.cache / 'source-views' / 'unregistered' / 'unknown.json'
        unknown.parent.mkdir()
        unknown.write_text('{"unknown":true}')
        before = self.f.manager._cache_bytes(), self.f.manager._usage()
        conservative = set(self.f.manager._metadata_records())
        aware = self.aware_manager()
        records = set(aware._metadata_records())
        payloads = self.aliases()
        self.assertTrue(payloads)
        self.assertTrue(payloads <= conservative)
        self.assertFalse(payloads & records)
        self.assertIn(unknown, records)
        self.assertTrue(set((self.cache / 'receipts').glob('*.json')) <= records)
        self.assertTrue(set(self.cache.glob('source-views/*/views/*/receipt.json')) <= records)
        proof = self.scope()
        proof.payload_paths(self.candidates())
        controls = proof.control_paths()
        self.assertTrue(controls <= records)
        self.assertEqual(len(records), len(aware._metadata_records()))
        proof.audit()
        self.assertEqual(before, (aware._cache_bytes(), aware._usage()))

    def test_unchanged_operation_reuses_classification_but_final_audit_stays_full(self):
        scope = self.scope()
        candidates = self.candidates()
        expected = scope.payload_paths(candidates)
        archive = next(iter(scope.archives.values()))[0]
        with patch.object(archive, 'validate_view', wraps=archive.validate_view) as validate:
            self.assertEqual(expected, scope.payload_paths(candidates))
            scope.audit_pins()
            self.assertEqual(0, validate.call_count)
            scope.audit()
            self.assertGreater(validate.call_count, 0)

    def test_unchanged_json_candidates_cannot_hide_new_binary_view_member(self):
        scope = self.scope()
        candidates = self.candidates()
        scope.payload_paths(candidates)
        tree = next(iter(scope.archives.values()))[0].view_memos.values()
        next(iter(tree))[0].joinpath('unexpected-binary.bin').write_bytes(b'new member')
        with self.assertRaisesRegex(ValueError, 'directory membership changed'):
            scope.payload_paths(candidates)

    def test_real_manager_corrupt_proof_cannot_exempt(self):
        receipt = next(self.cache.glob('source-views/*/views/*/receipt.json'))
        value = json.loads(receipt.read_text())
        value['view_strategy'] = 'private_copy'
        receipt.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            self.aware_manager()._metadata_records()

    def test_no_project_or_wrong_project_remains_conservative(self):
        scope = SourcePayloadScope(None, self.cache, self.policy)
        self.assertEqual(set(), scope.payload_paths(self.candidates()))
        scope.audit()
        foreign = self.f.storage.base / 'foreign-project'
        (foreign / 'forge').mkdir(parents=True)
        policy = deepcopy(self.policy)
        policy['project_id'] = '11111111-1111-4111-8111-111111111111'
        (foreign / 'forge/evidence-policy.json').write_text(json.dumps(policy))
        scope = SourcePayloadScope(foreign, self.cache, self.policy)
        self.assertEqual(set(), scope.payload_paths(self.candidates()))
        scope.audit()

    def test_legitimate_unselected_index_stays_payload(self):
        old = self.f.index
        old_paths = self.aliases()
        self.f.select_index(encoding='sha_objects_v1', canonical=True)  # New private index.
        self.f.prepare()
        self.f.p.save()
        self.assertNotEqual(old, self.f.index)
        scope = self.scope()
        paths = scope.payload_paths(self.candidates())
        self.assertTrue(old_paths <= paths)
        self.assertEqual(self.aliases(), paths)
        scope.audit()

    def test_forged_self_consistent_subset_descriptor_rejects(self):
        receipt = next(self.cache.glob('source-views/*/views/*/receipt.json'))
        value = json.loads(receipt.read_text())
        index = value['index_ref']
        archive = self.f.helper.SourceArchive(self.p.root, index, self.cache)
        files = deepcopy(value['view']['files'])
        logical = next(iter(files))
        (receipt.parent / 'files' / logical).unlink()
        files.pop(logical)
        forged = archive.descriptor(value['view']['snapshot_root'], files)
        tree = receipt.parent / 'files'
        for directory in sorted((p for p in tree.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            if directory.relative_to(tree).as_posix() not in forged['directories']:
                directory.rmdir()
        target = receipt.parent.with_name(self.f.helper.sha(self.f.helper.encoded(forged)))
        receipt.parent.rename(target)
        (target / 'receipt.json').write_bytes(self.f.helper.encoded(archive.view_receipt(forged)))
        with self.assertRaisesRegex(ValueError, 'complete supported original'):
            self.scope().payload_paths(self.candidates())

    def test_extra_member_foreign_inode_and_symlink_reject(self):
        receipt = next(self.cache.glob('source-views/*/views/*/receipt.json'))
        tree = receipt.parent / 'files'
        extra = tree / 'extra.json'
        extra.write_text('{}')
        with self.assertRaises(ValueError):
            self.scope().payload_paths(self.candidates())
        extra.unlink()
        alias = next(iter(self.aliases()))
        data = alias.read_bytes()
        alias.unlink()
        alias.write_bytes(data)
        with self.assertRaises(ValueError):
            self.scope().payload_paths(self.candidates())
        alias.unlink()
        digest = self.f.helper.sha(data)
        alias.symlink_to(self.cache / 'objects' / digest)
        with self.assertRaises(ValueError):
            self.scope().payload_paths(self.candidates())

    def test_equal_size_restored_mtime_mutation_and_control_drift_fail_audit(self):
        scope = self.scope()
        scope.payload_paths(self.candidates())
        alias = next(iter(self.aliases()))
        before, data = alias.stat(), alias.read_bytes()
        self.assertTrue(data)
        alias.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        os.utime(alias, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaises(ValueError):
            scope.audit()

    def test_control_receipt_drift_after_proof_fails_audit(self):
        scope = self.scope()
        scope.payload_paths(self.candidates())
        receipt = next(self.cache.glob('source-views/*/views/*/receipt.json'))
        receipt.write_bytes(receipt.read_bytes() + b'\n')
        with self.assertRaises(ValueError):
            scope.audit()

    def test_selected_limits_successor_accepts_unchanged_checkout(self):
        path = self.p.root / 'forge/evidence-policy.json'
        raw = path.read_bytes()
        candidate = {key: deepcopy(value) for key, value in self.policy.items() if key != 'policy_lineage'}
        candidate['limits']['metadata_stop_files'] += 1
        selected = policies.append_policy_transition(raw, candidate)
        scope = self.scope(selected)
        self.assertEqual(self.aliases(), scope.payload_paths(self.candidates()))
        scope.audit()
        self.assertEqual(raw, path.read_bytes())
        self.assertFalse(self.aliases() & set(self.aware_manager(selected)._metadata_records()))

    def test_global_control_budgets_do_not_reset_between_indexes(self):
        first_paths = self.candidates()
        first = self.scope()
        first.payload_paths(first_paths)
        files = len(first.resolver.documents)
        byte_count = first.resolver.json_bytes
        first_refs = set(first.resolver.references)
        self.f.select_index()  # Full inline refs introduce aliases of the same SHA.
        self.f.prepare()
        combined = self.scope()
        combined.payload_paths(self.candidates())
        self.assertTrue(all(archive.resolver is combined.resolver for archive, _ in combined.archives.values()))
        self.assertEqual({ref['artifact_id'] for ref in self.f.refs}, set(combined.resolver.references))
        self.assertGreater(len(combined.resolver.references), len(first_refs))
        combined.audit()
        raw = (self.p.root / 'forge/evidence-policy.json').read_bytes()
        for field, limit in [('metadata_stop_files', files), ('metadata_stop_bytes', byte_count)]:
            with self.subTest(field=field):
                candidate = deepcopy(self.policy)
                candidate['limits'][field] = limit
                selected = policies.append_policy_transition(raw, candidate)
                with self.assertRaisesRegex(ValueError, 'allowance|metadata|closure'):
                    self.scope(selected).payload_paths(self.candidates())

    def test_consumed_controls_are_exact_repeatable_and_audited(self):
        scope = self.scope()
        payloads = scope.payload_paths(self.candidates())
        controls = scope.control_paths()
        self.assertEqual(set(scope.resolver.documents) | set(scope.controls), controls)
        project = self.p.root.resolve()  # macOS's system /var alias is canonicalized.
        self.assertIn(project / 'forge/evidence-policy.json', controls)
        self.assertTrue({project / self.f.index['path'], project / self.f.context['path'],
                         project / self.f.completion['path']} <= controls)
        self.assertTrue(set(self.cache.glob('receipts/*.json')) & controls)
        self.assertTrue(set(self.cache.glob('source-views/*/views/*/receipt.json')) <= controls)
        self.assertFalse(payloads & controls)
        controls.clear()  # A caller cannot mutate the retained accounting proof.
        self.assertTrue(scope.control_paths())
        scope.audit()
        self.assertEqual(scope.control_paths(), scope.control_paths())
        scope.audit()
        path = self.p.root / self.f.context['path']
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaises(ValueError):
            scope.audit()

    def test_policy_identity_and_selected_input_drift_fail_audit(self):
        scope = self.scope()
        scope.payload_paths(self.candidates())
        self.policy['limits']['metadata_stop_files'] += 1
        with self.assertRaisesRegex(ValueError, 'selected policy changed'):
            scope.audit()
        self.policy['limits']['metadata_stop_files'] -= 1
        path = self.p.root / 'forge/evidence-policy.json'
        changed = deepcopy(self.policy)
        changed['store_id'] = 'foreign-store'
        path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            scope.audit()

    def test_real_manager_locked_scope_reuses_then_final_audit_detects_mutation(self):
        aware = self.aware_manager()
        with self.assertRaises(ValueError):
            with aware.locked():
                aware._metadata_records()
                scope = aware._source_payload_scope
                aware._metadata_records()
                self.assertIs(scope, aware._source_payload_scope)
                alias = next(iter(self.aliases()))
                alias.write_bytes(alias.read_bytes() + b'late corruption')
        self.assertIsNone(aware._source_payload_scope)

    def test_large_opaque_json_named_receipt_is_payload_not_control(self):
        # The next native project has its own immutable relative indexes; remove
        # only this test's previous prepared views before archiving new aliases.
        shutil.rmtree(self.cache / 'source-views')
        base = native.UnitHistoryTests('runTest')
        base.setUp()
        self.addCleanup(base.doCleanups)
        base.p.write('payload/receipt.json', '{"opaque":"' + 'x' * (1536 * 1024) + '"}')
        inventory = base.inventory
        def reviewed(*args, **kwargs):
            value = inventory(*args, **kwargs)
            value['execution_inputs']['payload/receipt.json'] = {'mode': 'file'}
            return value
        base.inventory = reviewed
        self.f.helper, _, self.f.context, self.f.completion = base.capture_alpha()
        self.f.p, self.f.m = base.p, base.m
        self.p = base.p
        self.p.write('forge/evidence-policy.json', json.dumps(self.policy))
        self.f.archive_records((self.f.context, self.f.completion))
        self.f.select_index(view_strategy='shared_cache_links', encoding='sha_objects_v1', canonical=True)
        self.f.prepare()
        scope = self.scope()
        paths = scope.payload_paths(self.candidates())
        scope.audit()
        aliases = [p for p in paths if p.as_posix().endswith('/payload/receipt.json')]
        self.assertTrue(aliases)
        self.assertGreater(aliases[0].stat().st_size, scope.resolver.json_bytes)
        raw = (self.p.root / 'forge/evidence-policy.json').read_bytes()
        selected = deepcopy(self.policy)
        selected['limits']['metadata_stop_bytes'] = scope.resolver.json_bytes + 4096
        selected = policies.append_policy_transition(raw, selected)
        bounded = self.scope(selected)
        self.assertTrue(set(aliases) <= bounded.payload_paths(self.candidates()))
        bounded.audit()
        records = set(self.aware_manager(selected)._metadata_records())
        self.assertFalse(set(aliases) & records)
        control = self.cache / 'same-inode-control.json'
        os.link(aliases[0], control)
        self.assertIn(control, self.aware_manager()._metadata_records())


if __name__ == '__main__':
    unittest.main()
