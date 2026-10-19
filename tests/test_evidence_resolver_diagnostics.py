"""Prepared evidence diagnostics preserve Windows I/O and safety distinctions."""
import errno
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence import resolver as module
from evidence.io import EvidenceError


def wrapped_os_error(message, cause):
    error = EvidenceError(message)
    error.__cause__ = cause
    return error


class ResolverDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdd-resolver-diagnostic-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name).resolve() / "missing-prepared-observation"

    def test_windows_missing_file_normalizes_real_open_error_and_preserves_cause(self):
        with patch.object(module, "sys", SimpleNamespace(platform="win32")), \
             patch.object(module, "_verify_stable") as verify:
            with self.assertRaisesRegex(ValueError, "prepared evidence missing/unreadable") as raised:
                module._regular(self.path)
        self.assertIsInstance(raised.exception.__cause__, FileNotFoundError)
        self.assertEqual(raised.exception.__cause__.errno, errno.ENOENT)
        self.assertIn(str(self.path), str(raised.exception))
        verify.assert_not_called()

    def test_windows_permission_error_normalizes_and_preserves_original_os_error(self):
        cause = PermissionError(errno.EACCES, "synthetic permission failure", str(self.path))
        failure = wrapped_os_error("cannot safely open " + str(self.path), cause)
        with patch.object(module, "sys", SimpleNamespace(platform="win32")), \
             patch.object(module, "_open_regular", side_effect=failure):
            with self.assertRaisesRegex(ValueError, "prepared evidence missing/unreadable") as raised:
                module._regular(self.path)
        self.assertIs(raised.exception.__cause__, cause)

    def test_windows_unsafe_link_nonregular_and_open_mutation_errors_are_unchanged(self):
        for message in ("linked or non-directory parent", "not a regular file", "file changed while opening"):
            with self.subTest(message=message):
                failure = EvidenceError(message + ": " + str(self.path))
                with patch.object(module, "sys", SimpleNamespace(platform="win32")), \
                     patch.object(module, "_open_regular", side_effect=failure):
                    with self.assertRaises(EvidenceError) as raised:
                        module._regular(self.path)
                self.assertIs(raised.exception, failure)
                self.assertNotIn("missing/unreadable", str(raised.exception))

    def test_no_follow_link_race_is_not_relabelled_as_missing(self):
        cause = OSError(errno.ELOOP, "synthetic linked input", str(self.path))
        failure = wrapped_os_error("cannot safely open " + str(self.path), cause)
        with patch.object(module, "sys", SimpleNamespace(platform="win32")), \
             patch.object(module, "_open_regular", side_effect=failure):
            with self.assertRaises(EvidenceError) as raised:
                module._regular(self.path)
        self.assertIs(raised.exception, failure)
        self.assertIs(raised.exception.__cause__, cause)

    def test_disappearance_after_open_retains_mutation_diagnostic_and_closes_descriptor(self):
        cause = FileNotFoundError(errno.ENOENT, "synthetic input disappearance", str(self.path))
        failure = wrapped_os_error("input disappeared while reading: " + str(self.path), cause)
        baseline = object()
        with patch.object(module, "sys", SimpleNamespace(platform="win32")), \
             patch.object(module, "_open_regular", return_value=(self.path, 42, baseline)), \
             patch.object(module, "_verify_stable", side_effect=failure) as verify, \
             patch.object(module.os, "close") as close:
            with self.assertRaises(EvidenceError) as raised:
                module._regular(self.path)
        self.assertIs(raised.exception, failure)
        self.assertIs(raised.exception.__cause__, cause)
        verify.assert_called_once_with(self.path, 42, baseline)
        close.assert_called_once_with(42)


if __name__ == "__main__":
    unittest.main()
