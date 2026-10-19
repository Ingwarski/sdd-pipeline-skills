"""Windows read sharing and CRT ownership protect stable evidence bytes."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence import io


class WindowsHandleOwnershipTests(unittest.TestCase):
    def fake_api(self, *, handle=2**40, conversion_error=None):
        create, close = Mock(return_value=handle), Mock(return_value=True)
        convert = Mock(return_value=123, side_effect=conversion_error)
        kernel = SimpleNamespace(CreateFileW=create, CloseHandle=close)
        runtime = SimpleNamespace(open_osfhandle=convert)
        return kernel, runtime

    def test_read_only_noninherited_nofollow_handle_transfers_to_descriptor(self):
        kernel, runtime = self.fake_api()
        path = Path("synthetic-observation").absolute()
        with patch("ctypes.WinDLL", return_value=kernel, create=True) as library, \
             patch.object(io.os, "O_NOINHERIT", 0x80, create=True), \
             patch.dict(sys.modules, {"msvcrt": runtime}):
            self.assertEqual(io._windows_open_regular(path), 123)
        library.assert_called_once_with("kernel32", use_last_error=True)
        kernel.CreateFileW.assert_called_once_with(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
        self.assertIs(kernel.CreateFileW.restype, wintypes.HANDLE)
        self.assertEqual(kernel.CreateFileW.argtypes[-1], wintypes.HANDLE)
        runtime.open_osfhandle.assert_called_once_with(2**40, os.O_RDONLY | getattr(os, "O_BINARY", 0) | 0x80)
        kernel.CloseHandle.assert_not_called()

    def test_failed_crt_conversion_closes_still_owned_native_handle_once(self):
        failure = OSError("synthetic CRT conversion failure")
        kernel, runtime = self.fake_api(conversion_error=failure)
        with patch("ctypes.WinDLL", return_value=kernel, create=True), \
             patch.dict(sys.modules, {"msvcrt": runtime}):
            with self.assertRaises(OSError) as raised:
                io._windows_open_regular(Path("synthetic-observation").absolute())
        self.assertIs(raised.exception, failure)
        kernel.CloseHandle.assert_called_once_with(2**40)

    def test_invalid_native_handle_is_never_transferred_or_closed_as_owned(self):
        kernel, runtime = self.fake_api(handle=ctypes.c_void_p(-1).value)
        failure = OSError("synthetic sharing violation")
        with patch("ctypes.WinDLL", return_value=kernel, create=True), \
             patch("ctypes.get_last_error", return_value=32, create=True), \
             patch("ctypes.WinError", return_value=failure, create=True) as error, \
             patch.dict(sys.modules, {"msvcrt": runtime}):
            with self.assertRaises(OSError) as raised:
                io._windows_open_regular(Path("synthetic-observation").absolute())
        self.assertIs(raised.exception, failure)
        error.assert_called_once_with(32)
        runtime.open_osfhandle.assert_not_called()
        kernel.CloseHandle.assert_not_called()


@unittest.skipUnless(os.name == "nt", "native Windows file-sharing semantics required")
class NativeWindowsReadLockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdd-windows-read-lock-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / "observation"
        self.path.write_bytes(b"original")

    def test_reads_are_shared_but_writes_deletes_and_renames_require_close(self):
        _, descriptor, baseline = io._open_regular(self.path)
        replacement = self.root / "replacement"
        try:
            self.assertFalse(os.get_inheritable(descriptor))
            self.assertEqual(self.path.read_bytes(), b"original")
            with self.assertRaises(OSError):
                self.path.write_bytes(b"modified")
            with self.assertRaises(OSError):
                self.path.unlink()
            with self.assertRaises(OSError):
                self.path.rename(replacement)
            io._verify_stable(self.path, descriptor, baseline)
        finally:
            os.close(descriptor)
        self.path.rename(replacement)
        replacement.write_bytes(b"modified")
        replacement.unlink()
        self.assertFalse(replacement.exists())

    def test_existing_writer_prevents_verification_until_it_closes(self):
        with self.path.open("r+b") as writer:
            with self.assertRaises(io.EvidenceError):
                io.hash_file(self.path)
            writer.seek(0)
            self.assertEqual(writer.read(), b"original")
        self.assertEqual(io.hash_file(self.path), (hashlib.sha256(b"original").hexdigest(), 8))

    def test_immediate_hash_mutation_is_refused_and_failed_read_releases_lock(self):
        read = os.read
        attempted = False
        def mutate(descriptor, amount):
            nonlocal attempted
            block = read(descriptor, amount)
            if not attempted:
                attempted = True
                self.path.write_bytes(b"modified")
            return block
        with patch.object(io.os, "read", side_effect=mutate), self.assertRaises(io.EvidenceError):
            io.hash_file(self.path)
        self.assertTrue(attempted)
        self.assertEqual(self.path.read_bytes(), b"original")
        self.path.write_bytes(b"modified")
        self.assertEqual(self.path.read_bytes(), b"modified")

    def test_immediate_json_mutation_is_refused_and_failed_read_releases_lock(self):
        self.path.write_bytes(b'{"x":1}')
        read = os.read
        attempted = False
        def mutate(descriptor, amount):
            nonlocal attempted
            block = read(descriptor, amount)
            if not attempted:
                attempted = True
                self.path.write_bytes(b'{"x":2}')
            return block
        with patch.object(io.os, "read", side_effect=mutate), self.assertRaises(io.EvidenceError):
            io.read_json(self.path, 100)
        self.assertTrue(attempted)
        self.assertEqual(self.path.read_bytes(), b'{"x":1}')
        self.path.write_bytes(b'{"x":2}')
        self.assertEqual(io.read_json(self.path, 100), {"x": 2})


if __name__ == "__main__":
    unittest.main()
