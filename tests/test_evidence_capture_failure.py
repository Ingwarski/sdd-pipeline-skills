"""Capture removes only its owned partial bytes after read/sharing failures."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence import archive
from evidence.io import EvidenceError


class CaptureFailureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdd-capture-failure-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source, self.destination = self.root / "original", self.root / "captured"
        self.source.write_bytes(b"original")

    def test_sharing_or_stability_oserror_removes_partial_and_preserves_cause(self):
        error = PermissionError("synthetic concurrent write was refused")
        with patch.object(archive, "_verify_stable", side_effect=error):
            with self.assertRaises(EvidenceError) as raised:
                archive.capture(self.source, self.destination, 100)
        self.assertIs(raised.exception.__cause__, error)
        self.assertFalse(self.destination.exists())
        # A failed capture closes its owned reader, including Windows sharing
        # exclusions. The original is writable again after error propagation.
        self.assertEqual(self.source.read_bytes(), b"original")
        self.source.write_bytes(b"modified")
        self.assertEqual(self.source.read_bytes(), b"modified")

    def test_read_oserror_removes_owned_partial_and_preserves_original(self):
        error = OSError("synthetic source read failure")
        original_fdopen = os.fdopen
        class FailedRead:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self, amount):
                raise error
        def fdopen(descriptor, mode, *args, **kwargs):
            return FailedRead() if mode == "rb" else original_fdopen(descriptor, mode, *args, **kwargs)
        with patch.object(archive.os, "fdopen", side_effect=fdopen):
            with self.assertRaises(EvidenceError) as raised:
                archive.capture(self.source, self.destination, 100)
        self.assertIs(raised.exception.__cause__, error)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), b"original")

    def test_preexisting_destination_failure_remains_fileexists_without_cleanup(self):
        self.destination.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            archive.capture(self.source, self.destination, 100)
        self.assertEqual(self.destination.read_bytes(), b"preserve")


if __name__ == "__main__":
    unittest.main()
