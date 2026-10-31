"""Synthetic path-boundary tests for the native history resolver."""
import errno
import ntpath
import os
from pathlib import Path, PureWindowsPath
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from test_sdd_check import sdd


class PhysicalPathMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdd-physical-path-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.history = sdd.history_api()

    def symlink(self, path, target, *, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except (NotImplementedError, OSError) as error:
            self.skipTest("symlink creation unavailable: " + str(error))

    def test_existing_components_use_one_fresh_lstat_each(self):
        target = self.root / "one" / "two" / "payload.txt"
        target.parent.mkdir(parents=True)
        target.write_text("synthetic\n", encoding="utf-8")
        components = [self.root / name for name in ("one", "one/two", "one/two/payload.txt")]
        original_lstat = Path.lstat
        counts = {path: 0 for path in components}

        def counted_lstat(path, *args, **kwargs):
            if path in counts:
                counts[path] += 1
            return original_lstat(path, *args, **kwargs)

        with mock.patch.object(Path, "lstat", autospec=True, side_effect=counted_lstat):
            resolved = self.history.physical(self.root, "one/two/payload.txt")

        self.assertEqual(target, resolved)
        self.assertEqual({path: 1 for path in components}, counts)

    def test_missing_terminal_and_ancestor_remain_lexically_contained(self):
        self.assertEqual(self.root / "missing" / "child.txt",
                         self.history.physical(self.root, "missing/child.txt"))
        blocker = self.root / "regular-file"
        blocker.write_text("not a directory\n", encoding="utf-8")
        self.assertEqual(blocker / "child.txt",
                         self.history.physical(self.root, "regular-file/child.txt"))

    def test_dangling_and_intermediate_symlinks_are_rejected(self):
        dangling = self.root / "dangling"
        self.symlink(dangling, self.root / "not-present")
        with self.assertRaisesRegex(ValueError, "links"):
            self.history.physical(self.root, "dangling")

        outside = self.root.parent / (self.root.name + "-outside")
        outside.mkdir()
        self.addCleanup(lambda: outside.rmdir())
        link = self.root / "escape"
        self.symlink(link, outside, directory=True)
        with self.assertRaisesRegex(ValueError, "links"):
            self.history.physical(self.root, "escape/child.txt")

    def test_reparse_attribute_is_rejected_portably(self):
        target = self.root / "junction-like-directory"
        target.mkdir()
        original_lstat = Path.lstat
        reparse_attribute = 0x400

        def flagged_lstat(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            if path == target:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=reparse_attribute)
            return info

        with mock.patch.object(stat, "FILE_ATTRIBUTE_REPARSE_POINT", reparse_attribute, create=True), \
                mock.patch.object(Path, "lstat", autospec=True, side_effect=flagged_lstat):
            with self.assertRaisesRegex(ValueError, "links"):
                self.history.physical(self.root, "junction-like-directory")

    def test_new_symlink_between_calls_is_seen_without_cross_call_cache(self):
        directory = self.root / "replace-me"
        directory.mkdir()
        (directory / "child.txt").write_text("inside\n", encoding="utf-8")
        self.assertEqual(directory / "child.txt",
                         self.history.physical(self.root, "replace-me/child.txt"))

        outside = self.root.parent / (self.root.name + "-replacement")
        outside.mkdir()
        self.addCleanup(lambda: outside.rmdir())
        (directory / "child.txt").unlink()
        directory.rmdir()
        self.symlink(directory, outside, directory=True)
        with self.assertRaisesRegex(ValueError, "links"):
            self.history.physical(self.root, "replace-me/child.txt")

    def test_unexpected_component_io_errors_fail_closed(self):
        target = self.root / "protected"
        target.mkdir()
        original_lstat = Path.lstat

        for error in (PermissionError(errno.EACCES, "denied"), OSError(errno.EIO, "I/O error")):
            def failing_lstat(path, *args, **kwargs):
                if path == target:
                    raise error
                return original_lstat(path, *args, **kwargs)

            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(Path, "lstat", autospec=True, side_effect=failing_lstat):
                with self.assertRaises(type(error)):
                    self.history.physical(self.root, "protected")

    def test_lexical_escape_and_non_posix_paths_are_rejected(self):
        invalid = ("", "../outside", "one/../outside", "./child", "/absolute", "one\\child")
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.history.physical(self.root, value)

    def test_equivalent_resolved_windows_anchors_preserve_containment(self):
        pairs = (
            (r"C:\project", r"\\?\C:\project\pending.json"),
            (r"\\?\C:\project", r"c:\PROJECT\pending.json"),
            (r"\\server\share\project", r"\\?\UNC\server\share\project\pending.json"),
            (r"\\?\UNC\server\share\project", r"\\SERVER\SHARE\project\pending.json"),
        )
        for root, child in pairs:
            with self.subTest(root=root, child=child):
                self.assertTrue(self.history._containment_path(PureWindowsPath(child)).is_relative_to(
                    self.history._containment_path(PureWindowsPath(root))))

    def test_windows_anchor_comparison_preserves_escape_and_namespace_boundaries(self):
        pairs = (
            (r"C:\project", r"\\?\C:\project-other\pending.json"),
            (r"C:\project", r"\\?\D:\project\pending.json"),
            (r"C:\project", r"\\?\C:\project.\pending.json"),
            (r"C:\project", "\\\\?\\C:\\project \\pending.json"),
            (r"C:\project", r"\\?\GLOBALROOT\Device\project\pending.json"),
            (r"C:\project", r"\\?\Volume{synthetic}\project\pending.json"),
            (r"C:\project", r"\\.\C:\project\pending.json"),
            (r"\\server\share\project", r"\\?\UNC\other\share\project\pending.json"),
            (r"\\server\share\project", r"\\?\UNC\server\other\project\pending.json"),
            (r"\\.\share\project", r"\\?\UNC\.\share\project\pending.json"),
        )
        for root, child in pairs:
            with self.subTest(root=root, child=child):
                self.assertFalse(self.history._containment_path(PureWindowsPath(child)).is_relative_to(
                    self.history._containment_path(PureWindowsPath(root))))

    @unittest.skipUnless(os.name == "nt", "native Windows realpath error transition")
    def test_missing_parent_race_keeps_original_io_path(self):
        leaf = self.root / "concurrent-parent" / "pending.json"
        leaf.parent.mkdir()
        original = ntpath._getfinalpathname
        calls = []

        def missing_parent_then_leaf(path):
            if ntpath.normcase(os.fspath(path)) == ntpath.normcase(str(leaf)):
                calls.append(path)
                error = FileNotFoundError(errno.ENOENT, "synthetic concurrent parent creation", str(leaf))
                error.winerror = 3 if len(calls) == 1 else 2
                raise error
            return original(path)

        with mock.patch.object(ntpath, "_getfinalpathname", side_effect=missing_parent_then_leaf):
            self.assertTrue(str(leaf.resolve()).startswith("\\\\?\\"))
            self.assertGreaterEqual(len(calls), 3)
            calls.clear()
            result = self.history.physical(self.root, "concurrent-parent/pending.json")
            self.assertGreaterEqual(len(calls), 3)
        self.assertEqual(leaf, result)
        self.assertFalse(str(result).startswith("\\\\?\\"))


if __name__ == "__main__":
    unittest.main()
