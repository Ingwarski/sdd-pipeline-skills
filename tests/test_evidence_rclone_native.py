"""Optional installed-rclone regressions using local fixtures, never a Drive account."""
from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "to-sdd-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from evidence.transports import EvidenceError, RcloneDriveTransport


RCLONE = shutil.which("rclone")


class QuietHandler(SimpleHTTPRequestHandler):
    timeout = 5

    def log_message(self, *args):
        pass

    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError):
            # A rejected bounded transfer may close its HTTP request early.
            pass


@unittest.skipUnless(RCLONE, "optional native regression: rclone is not installed on PATH")
class NativeRcloneTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        # Explicit private config plus a clean rclone environment prevents use
        # of personal remotes, credentials, defaults or a configured RC server.
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith("RCLONE_")}
        with (tempfile.TemporaryDirectory(prefix="sdd-rclone-native-") as folder,
              patch.dict(os.environ, environment, clear=True)):
            root = Path(folder).resolve()
            source, destination = root / "source", root / "destination"
            source.mkdir()
            destination.mkdir()
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(source)))
            server.daemon_threads = False  # server_close waits for request workers.
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                                      name="sdd-rclone-native-http")
            started = False
            try:
                thread.start()
                started = True
                config = root / "isolated.conf"
                config.write_text("[sdd_native_http]\ntype = http\nurl = http://127.0.0.1:"
                                  + str(server.server_port) + "/\n", encoding="utf-8")
                config.chmod(0o600)
                transport = RcloneDriveTransport("sdd_native_http:", config=config, executable=RCLONE,
                                                state_dir=root / "state", attempts=1, timeout_seconds=30)
                yield transport, source, destination
            finally:
                if started:
                    server.shutdown()
                server.server_close()
                if started:
                    thread.join(timeout=5)
                self.assertFalse(thread.is_alive(), "native fixture HTTP server did not stop")

    def test_http_transfer_preserves_exact_limits_and_rejects_one_byte_over(self):
        with self.fixture() as (transport, source, destination):
            payload, target = source / "payload", destination / "original"
            parameters = {"srcFs": "sdd_native_http:", "srcRemote": payload.name,
                          "dstFs": str(destination), "dstRemote": target.name}
            for size in (0, 37, 65535, 1024 * 1024 + 1):
                with self.subTest(size=size):
                    original = b"x" * size
                    payload.write_bytes(original)
                    transport._transfer("operations/copyfile", parameters, size, output_path=target)
                    self.assertEqual(original, target.read_bytes())
                    target.unlink()
                    if size:
                        with self.assertRaisesRegex(EvidenceError, r"exit 8|download exceeds configured byte bound"):
                            transport._transfer("operations/copyfile", parameters, size - 1, output_path=target)
                        self.assertFalse(target.exists())
                    self.assertEqual([], list(destination.iterdir()), "rclone retained a partial download")

    def test_immutable_upload_skips_existing_bytes_and_copies_missing_target(self):
        with self.fixture() as (transport, source, destination):
            payload, target = source / "payload", destination / "original"
            original = b"new original"
            payload.write_bytes(original)
            parameters = {"srcFs": str(source), "srcRemote": payload.name,
                          "dstFs": str(destination), "dstRemote": target.name}
            for existing in (b"old original", b"different length old original", None):
                with self.subTest(existing=existing):
                    target.unlink(missing_ok=True)
                    if existing is not None:
                        target.write_bytes(existing)
                    transport._transfer("operations/copyfile", parameters, len(original), immutable=True)
                    self.assertEqual(original if existing is None else existing, target.read_bytes())


if __name__ == "__main__":
    unittest.main()
