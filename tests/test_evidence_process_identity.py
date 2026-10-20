"""Birth-bound process recovery uses real owned children and platform fixtures."""
import copy
import ctypes
import errno
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence.io import EvidenceError
from evidence import process_identity as processes


def record(platform="linux", pid=424242):
    birth = {"linux": {"boot_id": "12121212-1212-4212-8212-121212121212", "start_ticks": 987},
             "darwin": {"seconds": 123456, "microseconds": 987654},
             "win32": {"ticks": 1234567890123456}}[platform]
    return {"version": 1, "host": socket.gethostname(), "platform": platform, "pid": pid, "created": birth}


class RealProcessIdentityTests(unittest.TestCase):
    def test_current_process_identity_is_precise_and_json_serializable(self):
        current = processes.identity()
        self.assertEqual(current["pid"], os.getpid())
        self.assertEqual(current["host"], socket.gethostname())
        self.assertEqual(json.loads(json.dumps(current)), current)
        self.assertTrue(processes.valid_identity(current, local=True))
        self.assertEqual(processes.state(current), "alive")
        self.assertEqual(processes.terminate(current), "unknown")

    def test_owned_child_exit_becomes_gone(self):
        child = subprocess.Popen([sys.executable, "-B", "-c", "import sys; print('ready',flush=True); sys.stdin.read()"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            owned = processes.identity(child.pid)
            self.assertEqual(processes.state(owned), "alive")
            child.communicate(timeout=5)
            self.assertEqual(processes.state(owned), "gone")
            self.assertEqual(processes.terminate(owned), "gone")
            with self.assertRaises(EvidenceError):
                processes.identity(child.pid)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

    def test_terminate_owned_child_and_wait_for_actual_exit(self):
        child = subprocess.Popen([sys.executable, "-B", "-c", "import time; print('ready',flush=True); time.sleep(30)"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            owned = processes.identity(child.pid)
            result = processes.terminate(owned)
            # Old Linux kernels may lack pidfd despite Python exposing its API.
            if result == "unknown" and sys.platform == "linux":
                self.skipTest("kernel cannot provide pidfd-bound termination")
            self.assertEqual(result, "signalled")
            child.communicate(timeout=5)
            self.assertEqual(processes.state(owned), "gone")
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)


class IdentityGuardTests(unittest.TestCase):
    def test_malformed_and_foreign_records_never_query_or_signal(self):
        current = processes.identity()
        foreign = {**current, "host": current["host"] + "-another-host"}
        malformed = [None, [], {}, {**current, "pid": True}, {**current, "pid": -1},
                     {**current, "created": []}, {**current, "platform": {}},
                     {**current, "version": True}, {**current, "extra": 1},
                     {**current, "host": "bad\nhost"}]
        with patch.object(processes, "_read", side_effect=AssertionError("must not query")), patch.object(processes.os, "kill") as killed:
            for value in malformed + [foreign]:
                with self.subTest(value=value):
                    self.assertEqual(processes.state(value), "unknown")
                    self.assertEqual(processes.terminate(value), "unknown")
            killed.assert_not_called()
        self.assertTrue(processes.valid_identity(foreign))
        self.assertFalse(processes.valid_identity(foreign, local=True))

    def test_portable_identity_validation_accepts_all_supported_birth_formats(self):
        for platform in ("linux", "darwin", "win32"):
            with self.subTest(platform=platform):
                item = record(platform)
                item["host"] = "another-machine"
                self.assertTrue(processes.valid_identity(item))
                self.assertFalse(processes.valid_identity(item, local=True))
                for key in item["created"]:
                    malformed = copy.deepcopy(item)
                    malformed["created"][key] = False
                    self.assertFalse(processes.valid_identity(malformed))

    def test_permission_denied_is_unknown_not_absent(self):
        current = processes.identity()
        with patch.object(processes, "_read", side_effect=PermissionError("fixture permission denial")):
            self.assertEqual(processes.state(current), "unknown")
            with self.assertRaisesRegex(EvidenceError, "cannot establish"):
                processes.identity(current["pid"])

    def test_invalid_pid_input_is_rejected_before_query(self):
        with patch.object(processes, "_read", side_effect=AssertionError("must not query")):
            for pid in (True, False, 0, -1, "123", 2**31, 1.5):
                with self.subTest(pid=pid), self.assertRaises(EvidenceError):
                    processes.identity(pid)


class LinuxIdentityTests(unittest.TestCase):
    def test_proc_parser_handles_spaces_parentheses_and_detects_zombie(self):
        item = record()
        # Fields 4..21 precede starttime (22); comm may itself contain ')'.
        line = b"424242 (worker (named) with spaces) S " + b"0 " * 18 + b"987 0\n"
        with patch.object(processes, "_bounded_bytes", side_effect=[line, item["created"]["boot_id"].encode()]):
            self.assertEqual(processes._read_linux(item["pid"]), item["created"])
        with patch.object(processes, "_bounded_bytes", return_value=line.replace(b") S ", b") Z ")) as read:
            self.assertIsNone(processes._read_linux(item["pid"]))
            self.assertEqual(read.call_count, 1)

    def test_pidfd_is_opened_before_verification_and_closed_after_signal(self):
        item, events = record(), []
        with patch.object(processes.sys, "platform", "linux"), \
             patch.object(processes.os, "pidfd_open", side_effect=lambda *_: events.append("open") or 99, create=True), \
             patch.object(processes, "_read", side_effect=lambda *_: events.append("verify") or item["created"]), \
             patch.object(processes.signal, "pidfd_send_signal", side_effect=lambda *_: events.append("signal"), create=True) as signalled, \
             patch.object(processes.os, "close", side_effect=lambda *_: events.append("close")), \
             patch.object(processes.os, "kill", side_effect=AssertionError("must not signal numeric PID")):
            self.assertEqual(processes.terminate(item, force=True), "signalled")
            signalled.assert_called_once_with(99, signal.SIGKILL, None, 0)
        self.assertEqual(events, ["open", "verify", "signal", "close"])

    def test_replaced_pid_and_permission_failure_never_signal_pidfd(self):
        item = record()
        for replacement, expected in (({**item["created"], "start_ticks": 988}, "gone"),
                                      (PermissionError("fixture"), "unknown")):
            with self.subTest(expected=expected), patch.object(processes.sys, "platform", "linux"), \
                 patch.object(processes.os, "pidfd_open", return_value=99, create=True), \
                 patch.object(processes, "_read", **({"side_effect": replacement} if isinstance(replacement, Exception) else {"return_value": replacement})), \
                 patch.object(processes.signal, "pidfd_send_signal", create=True) as signalled, \
                 patch.object(processes.os, "close") as closed:
                self.assertEqual(processes.terminate(item), expected)
                signalled.assert_not_called()
                closed.assert_called_once_with(99)

    def test_pidfd_unavailable_fails_closed_without_numeric_pid_fallback(self):
        with patch.object(processes.sys, "platform", "linux"), \
             patch.object(processes.os, "pidfd_open", side_effect=OSError(errno.ENOSYS, "fixture"), create=True), \
             patch.object(processes.signal, "pidfd_send_signal", create=True), \
             patch.object(processes.os, "kill") as killed:
            self.assertEqual(processes.terminate(record()), "unknown")
            killed.assert_not_called()


class DarwinIdentityTests(unittest.TestCase):
    def test_libproc_uses_exact_microseconds_and_detects_zombie(self):
        def query(pid, flavor, arg, pointer, size):
            self.assertEqual((flavor, arg, size), (3, 0, ctypes.sizeof(processes._DarwinBSDInfo)))
            pointer._obj.pid = pid
            pointer._obj.status = 2
            pointer._obj.seconds = 123456
            pointer._obj.microseconds = 987654
            return size
        library = Mock()
        library.proc_pidinfo.side_effect = query
        with patch.object(processes, "_darwin_library", return_value=library):
            self.assertEqual(processes._read_darwin(424242), record("darwin")["created"])
        def zombie(*args):
            size = query(*args)
            args[3]._obj.status = 5
            return size
        library.proc_pidinfo.side_effect = zombie
        with patch.object(processes, "_darwin_library", return_value=library):
            self.assertIsNone(processes._read_darwin(424242))

    def test_libproc_permission_is_not_treated_as_exit(self):
        library = Mock()
        def unavailable(*_):
            ctypes.set_errno(errno.EPERM)
            return 0
        library.proc_pidinfo.side_effect = unavailable
        with patch.object(processes, "_darwin_library", return_value=library), self.assertRaises(PermissionError):
            processes._read_darwin(424242)

    def test_second_precise_check_blocks_replacement_before_signal(self):
        item = record("darwin")
        with patch.object(processes.sys, "platform", "darwin"), \
             patch.object(processes, "_read", side_effect=[item["created"], {**item["created"], "microseconds": 987655}]), \
             patch.object(processes.os, "kill") as killed:
            self.assertEqual(processes.terminate(item), "gone")
            killed.assert_not_called()


class WindowsIdentityTests(unittest.TestCase):
    def kernel(self, *, ticks=1234567890123456, wait=258):
        kernel = Mock()
        kernel.OpenProcess.return_value = 321
        kernel.WaitForSingleObject.return_value = wait
        kernel.TerminateProcess.return_value = True
        def times(handle, created, *_):
            self.assertEqual(handle, 321)
            created._obj.dwHighDateTime = ticks >> 32
            created._obj.dwLowDateTime = ticks & (2**32 - 1)
            return True
        kernel.GetProcessTimes.side_effect = times
        return kernel

    def test_query_uses_read_only_handle_and_wait_state_not_exit_code(self):
        kernel = self.kernel()
        with patch.object(processes, "_windows_kernel", return_value=kernel):
            self.assertEqual(processes._read_windows(424242), record("win32")["created"])
        kernel.OpenProcess.assert_called_once_with(0x101000, False, 424242)
        kernel.TerminateProcess.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(321)
        kernel = self.kernel(wait=0)
        with patch.object(processes, "_windows_kernel", return_value=kernel):
            self.assertIsNone(processes._read_windows(424242))
        kernel.GetProcessTimes.assert_not_called()

    def test_creation_is_verified_on_same_handle_used_to_terminate(self):
        kernel = self.kernel()
        with patch.object(processes.sys, "platform", "win32"), \
             patch.object(processes, "_windows_kernel", return_value=kernel):
            self.assertEqual(processes.terminate(record("win32")), "signalled")
        kernel.OpenProcess.assert_called_once_with(0x101001, False, 424242)
        kernel.TerminateProcess.assert_called_once_with(321, 1)
        kernel.CloseHandle.assert_called_once_with(321)

    def test_reused_windows_pid_is_not_terminated(self):
        kernel = self.kernel(ticks=1234567890123457)
        with patch.object(processes.sys, "platform", "win32"), \
             patch.object(processes, "_windows_kernel", return_value=kernel):
            self.assertEqual(processes.terminate(record("win32")), "gone")
        kernel.TerminateProcess.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(321)

    def test_windows_access_denial_is_unknown_and_invalid_pid_is_gone(self):
        for error, expected in ((5, "unknown"), (87, "gone")):
            kernel = self.kernel()
            kernel.OpenProcess.return_value = None
            with self.subTest(error=error), patch.object(processes.sys, "platform", "win32"), \
                 patch.object(processes, "_windows_kernel", return_value=kernel), \
                 patch.object(processes, "_windows_error", return_value=error):
                self.assertEqual(processes.state(record("win32")), expected)
                self.assertEqual(processes.terminate(record("win32")), expected)
            kernel.TerminateProcess.assert_not_called()


if __name__ == "__main__":
    unittest.main()
