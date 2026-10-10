"""Path/fd timestamp differences must not weaken stable-byte file checks."""
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence import io


def snapshot(**changes):
    fields = {"st_dev": 123, "st_ino": 456, "st_mode": stat.S_IFREG | 0o600,
              "st_size": 5, "st_mtime_ns": 1000, "st_ctime_ns": 2000,
              "st_birthtime_ns": 500, "st_file_attributes": 0}
    fields.update(changes)
    return SimpleNamespace(**fields)


class StatComparisonTests(unittest.TestCase):
    def test_aligned_windows_executable_mode_keeps_descriptor_mutation_guard(self):
        baseline = snapshot(st_mode=stat.S_IFREG | 0o711)
        path_info = snapshot(st_mode=stat.S_IFREG | 0o711, st_ctime_ns=500)
        with patch.object(io, "_WINDOWS_STAT", True), patch.object(io, "_parents"), \
             patch.object(io.Path, "lstat", return_value=path_info), \
             patch.object(io.os, "supports_dir_fd", frozenset()), \
             patch.object(io.os, "open", return_value=123), \
             patch.object(io.os, "fstat", return_value=baseline), patch.object(io.os, "close"):
            path, descriptor, actual = io._open_regular("synthetic-observation.cmd")
            io._verify_stable(path, descriptor, actual)
            with patch.object(io.os, "fstat", return_value=snapshot(st_mode=stat.S_IFREG | 0o700)):
                with self.assertRaisesRegex(io.EvidenceError, "changed while reading"):
                    io._verify_stable(path, descriptor, actual)

    def test_open_accepts_windows_clock_difference_and_returns_descriptor_baseline(self):
        path_info = snapshot(st_ctime_ns=500)
        fd_info = snapshot(st_ctime_ns=2000)
        with patch.object(io, "_WINDOWS_STAT", True), patch.object(io, "_parents"), \
             patch.object(io.Path, "lstat", return_value=path_info), \
             patch.object(io.os, "supports_dir_fd", frozenset()), \
             patch.object(io.os, "open", return_value=123), \
             patch.object(io.os, "fstat", return_value=fd_info), patch.object(io.os, "close") as close:
            _, descriptor, baseline = io._open_regular("synthetic-observation")
            self.assertEqual(descriptor, 123)
            self.assertIs(baseline, fd_info)
            close.assert_not_called()

    def test_open_rejects_windows_identity_or_byte_mutation_and_closes_descriptor(self):
        path_info = snapshot(st_ctime_ns=500)
        changes = {"st_dev": 124, "st_ino": 457, "st_mode": stat.S_IFREG | 0o400,
                   "st_size": 6, "st_mtime_ns": 1001, "st_birthtime_ns": 501}
        for field, value in changes.items():
            with self.subTest(field=field), patch.object(io, "_WINDOWS_STAT", True), \
                 patch.object(io, "_parents"), patch.object(io.Path, "lstat", return_value=path_info), \
                 patch.object(io.os, "supports_dir_fd", frozenset()), \
                 patch.object(io.os, "open", return_value=123), \
                 patch.object(io.os, "fstat", return_value=snapshot(**{field: value})), \
                 patch.object(io.os, "close") as close:
                with self.assertRaisesRegex(io.EvidenceError, "changed while opening"):
                    io._open_regular("synthetic-observation")
                close.assert_called_once_with(123)

    def test_windows_path_creation_ctime_matches_descriptor_change_ctime(self):
        path_info = snapshot(st_ctime_ns=500)
        fd_info = snapshot(st_ctime_ns=2000)
        with patch.object(io, "_WINDOWS_STAT", True):
            self.assertEqual(io._path_descriptor_signature(path_info), io._path_descriptor_signature(fd_info))
        # The descriptor's real change clock must remain part of its own
        # stability check, even though cross-API ctime has different meanings.
        self.assertNotEqual(io._signature(fd_info), io._signature(snapshot(st_ctime_ns=2001)))

    def test_windows_cross_api_comparison_keeps_identity_mode_size_mtime_and_birthtime(self):
        baseline = snapshot()
        changes = {"st_dev": 124, "st_ino": 457, "st_mode": stat.S_IFREG | 0o400,
                   "st_size": 6, "st_mtime_ns": 1001, "st_birthtime_ns": 501}
        with patch.object(io, "_WINDOWS_STAT", True):
            for field, value in changes.items():
                with self.subTest(field=field):
                    self.assertNotEqual(io._path_descriptor_signature(baseline),
                                        io._path_descriptor_signature(snapshot(**{field: value})))
            missing = snapshot()
            del missing.st_birthtime_ns
            with self.assertRaises(io.EvidenceError):
                io._path_descriptor_signature(missing)

    def test_posix_ctime_remains_part_of_cross_api_comparison(self):
        with patch.object(io, "_WINDOWS_STAT", False):
            self.assertNotEqual(io._path_descriptor_signature(snapshot()),
                                io._path_descriptor_signature(snapshot(st_ctime_ns=2001)))

    def test_windows_only_normalizes_execute_bits_synthesized_from_path_name(self):
        descriptor = snapshot()
        executable_path = snapshot(st_mode=descriptor.st_mode | 0o111, st_ctime_ns=500)
        with patch.object(io, "_WINDOWS_STAT", True):
            for name in ("fixture.exe", "fixture.bat", "fixture.CMD", "fixture.com", ".exe"):
                with self.subTest(name=name):
                    self.assertEqual(io._path_descriptor_signature(executable_path, path=Path(name)),
                                     io._path_descriptor_signature(descriptor))
            self.assertNotEqual(io._path_descriptor_signature(executable_path, path=Path("fixture.txt")),
                                io._path_descriptor_signature(descriptor))
            self.assertNotEqual(io._path_descriptor_signature(snapshot(st_mode=stat.S_IFREG | 0o444), path=Path("fixture.cmd")),
                                io._path_descriptor_signature(descriptor))
        with patch.object(io, "_WINDOWS_STAT", False):
            self.assertNotEqual(io._path_descriptor_signature(executable_path, path=Path("fixture.cmd")),
                                io._path_descriptor_signature(descriptor))

    def test_verify_preserves_descriptor_change_time_and_rejects_reparse_points(self):
        path_info = snapshot(st_ctime_ns=500)
        baseline = snapshot(st_ctime_ns=2000)
        path = SimpleNamespace(lstat=lambda: path_info)
        with patch.object(io, "_WINDOWS_STAT", True), patch.object(io, "_parents"), patch.object(io.os, "fstat", return_value=baseline):
            io._verify_stable(path, 1, baseline)
        with patch.object(io, "_WINDOWS_STAT", True), patch.object(io, "_parents"), patch.object(io.os, "fstat", return_value=snapshot(st_ctime_ns=2001)):
            with self.assertRaisesRegex(io.EvidenceError, "changed while reading"):
                io._verify_stable(path, 1, baseline)
        # Check Windows reparse attributes regardless of the host running this
        # synthetic regression; S_IFREG alone does not identify junctions.
        with patch.object(io, "_WINDOWS_STAT", True), patch.object(io, "_parents"), patch.object(io.os, "fstat", return_value=baseline), patch.object(io.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024, create=True):
            path_info.st_file_attributes = 1024
            with self.assertRaisesRegex(io.EvidenceError, "changed while reading"):
                io._verify_stable(path, 1, baseline)


class NativeStableReadTests(unittest.TestCase):
    def test_rewritten_regular_file_uses_descriptor_baseline_and_reads_stably(self):
        with tempfile.TemporaryDirectory(prefix="sdd-stat-native-") as directory:
            path = Path(directory).resolve() / "observation"
            path.write_bytes(b"before")
            # Separate creation and modification clocks on native Windows. The
            # test remains meaningful after upstream CPython aligns ctime APIs.
            time.sleep(0.02)
            with path.open("wb") as output:
                output.write(b"after!")
                output.flush()
                os.fsync(output.fileno())
            _, descriptor, baseline = io._open_regular(path)
            try:
                self.assertEqual(io._signature(baseline), io._signature(os.fstat(descriptor)))
                io._verify_stable(path, descriptor, baseline)
            finally:
                os.close(descriptor)
            self.assertEqual(io.hash_file(path), (hashlib.sha256(b"after!").hexdigest(), 6))

    def test_native_executable_filename_is_a_stable_regular_file(self):
        with tempfile.TemporaryDirectory(prefix="sdd-stat-executable-") as directory:
            path = Path(directory).resolve() / "observation.cmd"
            path.write_bytes(b"synthetic regular observation\n")
            self.assertEqual(io.hash_file(path), (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size))

    def test_real_same_size_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="sdd-stat-mutation-") as directory:
            path = Path(directory).resolve() / "observation"
            path.write_bytes(b"before")
            _, descriptor, baseline = io._open_regular(path)
            try:
                time.sleep(0.02)
                with path.open("wb") as output:
                    output.write(b"after!")
                    output.flush()
                    os.fsync(output.fileno())
                with self.assertRaisesRegex(io.EvidenceError, "changed while reading"):
                    io._verify_stable(path, descriptor, baseline)
            finally:
                os.close(descriptor)


if __name__ == "__main__":
    unittest.main()
