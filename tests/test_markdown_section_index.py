"""Verified 5651687 parser differential and isolated audited section-index regressions."""
import hashlib
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from test_sdd_check import sdd

BASELINE_SOURCE = "def section_from_bytes(data, heading):\n    \"\"\"The same exact section rules for a verified immutable archived source.\"\"\"\n    if not isinstance(heading, str) or not re.match(r\"^#{1,6} \\S\", heading):\n        raise ValueError(\"fragment requires an exact Markdown heading, including #\")\n    lines = data.splitlines(keepends=True)\n    headings, fence = [], None\n    for index, line in enumerate(lines):\n        text = line.decode(\"utf-8\").rstrip(\"\\r\\n\").lstrip(\"\\ufeff\")\n        marker = re.match(r\"^ {0,3}(`{3,}|~{3,})\", text)\n        if marker:\n            run = marker[1]\n            if fence is None:\n                fence = run\n            elif run[0] == fence[0] and len(run) >= len(fence):\n                fence = None\n            continue\n        match = re.match(r\"^(#{1,6})[ \\t]+\", text) if fence is None else None\n        if match:\n            headings.append((index, len(match[1]), text))\n    matches = [index for index, _, text in headings if text == heading]\n    if len(matches) != 1:\n        raise ValueError(\"fragment heading must occur exactly once: \" + heading)\n    start = matches[0]\n    level = len(heading.split(\" \", 1)[0])\n    end = len(lines)\n    for index, depth, _ in headings:\n        if index > start and depth <= level:\n            end = index\n            break\n    return b\"\".join(lines[start:end])\n"

BASELINE_SHA256 = '89efe58d38471dac413b3c89dfb8380aa9665e8d16f3e8c26295f61b7ee33a7e'
baseline_scope = {'re': re}
exec(compile(BASELINE_SOURCE, 'verified-5651687-section-parser', 'exec'), baseline_scope)
old_section = baseline_scope['section_from_bytes']
history = sdd.history_api()
api = history.api()


def outcome(function, data, heading):
    try:
        value = function(data, heading)
        return ('value', type(value), value)
    except Exception as error:
        return ('error', type(error), str(error))


class ParserEquivalenceTests(unittest.TestCase):
    def test_oracle_is_exact_verified_5651687_function(self):
        self.assertEqual(hashlib.sha256(BASELINE_SOURCE.encode()).hexdigest(), BASELINE_SHA256)

    def test_differential_bytes_extents_fences_duplicates_heading_errors_and_utf8(self):
        cases = [
            b'# A\nbody\n## B\nchild\n# C\nlast',
            b'\xef\xbb\xbf# A\r\nbody\r\n## B\r\nchild\r\n# C\r\n',
            b'# A\n\xef\xbb\xbf## B\ntext\n# C\n',
            b'# A\n\x60\x60\x60json\n# C\n\x60\x60\x60\n## B\n# C\n',
            b'# A\n~~~lang\n# C\n\x60\x60\x60\n# A\n~~~~\n# C\n',
            b'# A\n   \x60\x60\x60\n# C\n  \x60\x60\x60\n# C\n',
            b'# A\n    \x60\x60\x60\n# C\n',
            b'# A\n\x60\x60\x60\x60\n# C\n\x60\x60\x60\n# A\n',
            b'# A\n# A\n', b'# A\n## B\n### D\n## E\n# C\n',
            b'# A\tlabel ###\nbody\n# C\n', b'#\tTab\nbody\n# C\n',
            b'####### ignored\n# A\nbody\n', b'# A\rbody\r# C',
            '# A\nПривіт 😀\n## B\nкінець'.encode(), b'# A\nvalid\n# C\n\xff',
            b'# A\n\x60\x60\x60\n\xff\n', b'', bytearray(b'# A\nbody\n# C\n')
        ]
        headings = ['# A', '## B', '# C', '### D', '## E', '# A\tlabel ###', '#\tTab',
                    '# Missing', '# ', 'A', '####### A', '', None]
        for index, data in enumerate(cases):
            for heading in headings:
                with self.subTest(case=index, heading=heading):
                    self.assertEqual(outcome(api.section_from_bytes, data, heading),
                                     outcome(old_section, data, heading))

    def test_generated_nested_extent_matrix_matches_original(self):
        for depths in ((1, 2, 3, 2, 1), (3, 3, 2, 4, 1), (6, 5, 4, 3, 2, 1)):
            data = b''.join(('#' * depth + ' H' + str(index) + '\r\nbody\r\n').encode()
                            for index, depth in enumerate(depths))
            for index, depth in enumerate(depths):
                heading = '#' * depth + ' H' + str(index)
                self.assertEqual(api.section_from_bytes(data, heading), old_section(data, heading))

    def test_generic_parser_is_fresh_and_mutable_bytes_are_detached(self):
        data = bytearray(b'# A\nbody\n')
        with patch.object(api, '_section_index', wraps=api._section_index) as builds:
            first = api.section_from_bytes(data, '# A')
            data[2] = ord('B')
            second = api.section_from_bytes(data, '# B')
        self.assertEqual(type(first), bytes); self.assertEqual(first, b'# A\nbody\n')
        self.assertEqual(second, b'# B\nbody\n'); self.assertEqual(builds.call_count, 2)


class AuditedSectionIndexTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='sdd-section-index-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.path = self.root / 'docs/source.md'; self.path.parent.mkdir()
        self.data = b''.join(('# H' + str(index) + '\nbody ' + str(index) + '\n').encode()
                             for index in range(80))
        self.path.write_bytes(self.data)
        self.identity = api.digest(self.data)

    def checker(self):
        return api.Checker(self.root, {})

    def run_body(self, checker, body):
        def invocation(*args, **kwargs):
            body()
            return {'result': 'passed', 'issues': checker.issues}
        with patch.object(checker, '_run', side_effect=invocation):
            return checker.run('product-idea')

    def test_many_headings_share_one_build_and_every_source_joins_final_union(self):
        with patch.object(api, '_section_index', wraps=api._section_index) as builds:
            with history.snapshot_hash_scope() as owner:
                for index in range(80):
                    heading = '# H' + str(index)
                    self.assertEqual(owner.section(self.path, self.identity, heading),
                                     old_section(self.data, heading))
                self.assertEqual(builds.call_count, 1)
                self.assertEqual(set(owner.hashes), {self.path})
                self.assertEqual(set(owner.section_indexes), {(self.path, self.identity)})
                index = owner.section_indexes[(self.path, self.identity)]
                with self.assertRaises(TypeError): index[1]['# H0'] = ((0, 0),)
            self.assertEqual(owner.section_indexes, {}); self.assertEqual(owner.hashes, {})

    def test_same_sha_distinct_physical_paths_keep_separate_verified_indexes(self):
        second = self.path.with_name('same-bytes.md'); second.write_bytes(self.data)
        with patch.object(api, '_section_index', wraps=api._section_index) as builds:
            with history.snapshot_hash_scope() as owner:
                owner.section(self.path, self.identity, '# H0')
                owner.section(second, self.identity, '# H0')
                self.assertEqual(set(owner.hashes), {self.path, second})
                self.assertEqual(builds.call_count, 2)

    def test_nested_checker_reuses_owner_but_new_top_level_run_is_fresh(self):
        first, second = self.checker(), self.checker()
        with patch.object(api, '_section_index', wraps=api._section_index) as builds:
            with history.snapshot_hash_scope() as owner:
                first._history_hash_owner = owner; second._history_hash_owner = owner
                self.assertEqual(self.run_body(first, lambda: first.section('docs/source.md', '# H0'))['result'], 'passed')
                self.assertEqual(self.run_body(second, lambda: second.section('docs/source.md', '# H1'))['result'], 'passed')
                self.assertEqual(builds.call_count, 1)
                self.assertTrue(owner.section_indexes)
            self.assertEqual(owner.section_indexes, {})
            self.assertEqual(self.run_body(first, lambda: first.section('docs/source.md', '# H2'))['result'], 'passed')
            self.assertEqual(builds.call_count, 2)
            self.assertEqual(first._history_hash_owner.section_indexes, {})

    def test_outside_scope_owner_reads_fresh_and_retains_nothing(self):
        owner = api.SnapshotFileHashes()
        with patch.object(api, '_section_index', wraps=api._section_index) as builds:
            owner.section(self.path, self.identity, '# H0')
            owner.section(self.path, self.identity, '# H1')
            self.assertEqual(builds.call_count, 2)
        self.assertEqual(owner.hashes, {}); self.assertEqual(owner.section_indexes, {})

    def test_wrong_identity_on_cached_hit_is_not_trusted(self):
        with history.snapshot_hash_scope() as owner:
            owner.section(self.path, self.identity, '# H0')
            with self.assertRaises(ValueError): owner.section(self.path, 'f' * 64, '# H1')

    def test_same_length_changed_bytes_with_restored_mtime_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'changed'):
            with history.snapshot_hash_scope() as owner:
                owner.section(self.path, self.identity, '# H0')
                before = self.path.stat(); changed = b'X' + self.data[1:]
                self.path.write_bytes(changed)
                os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
                owner.section(self.path, self.identity, '# H1')

    def test_replaced_parent_directory_with_equal_bytes_is_rejected(self):
        with self.assertRaises(ValueError):
            with history.snapshot_hash_scope() as owner:
                owner.section(self.path, self.identity, '# H0')
                original = self.path.parent; original.rename(self.root / 'retained-docs')
                original.mkdir(); self.path.write_bytes(self.data)
                owner.section(self.path, self.identity, '# H1')

    def test_checker_repeated_heading_still_checks_file_and_parent_links(self):
        checker = self.checker()
        probe = self.path.with_name('link-probe')
        try:
            probe.symlink_to(self.path)
        except OSError as error:
            self.skipTest('native symlink creation unavailable: ' + str(error))
        probe.unlink()
        retained = self.path.with_name('retained.md')
        try:
            with self.assertRaises(ValueError):
                with history.snapshot_hash_scope() as owner:
                    checker._history_hash_owner = owner
                    checker.section('docs/source.md', '# H0')
                    self.path.rename(retained); self.path.symlink_to(retained)
                    # Access rejects immediately; the final union audit must
                    # independently reject the still-replaced source as well.
                    with self.assertRaises(ValueError): checker.section('docs/source.md', '# H0')
        finally:
            if self.path.is_symlink(): self.path.unlink()
            if retained.exists(): retained.rename(self.path)

    def test_initial_read_bytes_must_match_supplied_verified_sha(self):
        original = Path.read_bytes
        def wrong_read(path):
            return b'# H0\nwrong bytes\n' if path == self.path else original(path)
        with history.snapshot_hash_scope() as owner, patch.object(Path, 'read_bytes', wrong_read):
            with self.assertRaisesRegex(ValueError, 'changed'):
                owner.section(self.path, self.identity, '# H0')
            self.assertEqual(owner.section_indexes, {})

    def test_mutation_after_initial_read_before_registration_is_rejected(self):
        original = Path.read_bytes
        def read_then_change(path):
            data = original(path)
            if path == self.path: self.path.write_bytes(b'X' + self.data[1:])
            return data
        with self.assertRaisesRegex(ValueError, 'changed'):
            with history.snapshot_hash_scope() as owner, patch.object(Path, 'read_bytes', read_then_change):
                owner.section(self.path, self.identity, '# H0')

    def test_child_only_indexed_source_mutation_is_caught_by_outer_union_audit(self):
        checker = self.checker()
        with self.assertRaisesRegex(ValueError, 'changed'):
            with history.snapshot_hash_scope() as owner:
                checker._history_hash_owner = owner
                self.run_body(checker, lambda: checker.section('docs/source.md', '# H0'))
                self.path.write_bytes(b'X' + self.data[1:])
        self.assertEqual(owner.section_indexes, {}); self.assertEqual(owner.depth, 0)

    def test_exception_exit_audits_and_clears_index_without_reviving_owner(self):
        with self.assertRaisesRegex(ValueError, 'changed'):
            with history.snapshot_hash_scope() as owner:
                owner.section(self.path, self.identity, '# H0')
                self.path.write_bytes(b'X' + self.data[1:])
                raise RuntimeError('synthetic body failure')
        self.assertEqual(owner.section_indexes, {}); self.assertEqual(owner.depth, 0)
        self.path.write_bytes(self.data)
        with history.snapshot_hash_scope(owner) as fresh:
            self.assertIsNot(fresh, owner)
            self.assertFalse(fresh.section_indexes)

    def test_invalid_heading_precedes_full_file_utf8_decode(self):
        self.path.write_bytes(b'\xff')
        identity = api.digest(b'\xff')
        with history.snapshot_hash_scope() as owner:
            with self.assertRaisesRegex(ValueError, 'exact Markdown heading'):
                owner.section(self.path, identity, 'bad heading')
            self.assertEqual(owner.section_indexes, {})
            with self.assertRaises(UnicodeDecodeError): owner.section(self.path, identity, '# H0')


if __name__ == '__main__':
    unittest.main(verbosity=2)
