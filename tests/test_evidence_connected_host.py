"""Exercise the shipped connected-host bridge; native Drive tools are fixtures."""
from __future__ import annotations

import json
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))

from evidence.connected_host import (ConnectedHostAdapter, TOOLS, close_session, next_request,
                                     respond, start_session, _pid_alive, CONTROL_PEAK_BYTES)
from evidence.io import EvidenceError, atomic_json, read_json
from evidence.transports import ConnectedDriveTransport


class NativeDrive:
    """Native schemas, not the existing high-level transport adapter protocol."""

    def __init__(self, root):
        self.root, self.files, self.calls = root, {}, []
        self.partial_listing = False
        self.signed_download = False
        self.missing_capability = False
        self.bad_parent = False
        self.upload_error_after_write = False
        self.oversized_download = False
        self.next_id = 0

    def metadata(self, identity):
        if identity == "selected-folder":
            return {"id": identity, "mimeType": "application/vnd.google-apps.folder", "trashed": False}
        value = self.files[identity]
        return {"id": identity, "title": value["name"], "size": str(len(value["bytes"])),
                "mime_type": "application/octet-stream", "parent_ids": ["wrong-folder" if self.bad_parent else "selected-folder"],
                "trashed": False}

    def call(self, request):
        self.calls.append(request)
        tool, args = request["tool"], request["arguments"]
        if tool == "host_capabilities":
            return {"tools": list(TOOLS[:-1] if self.missing_capability else TOOLS), "original_download": True}, None
        if tool == "get_file_metadata":
            return {"structuredContent": self.metadata(args["fileId"])}, None
        if tool == "upload_file":
            self.next_id += 1
            identity = "object-" + str(self.next_id)
            self.files[identity] = {"name": args["file_name"], "bytes": Path(args["file_uri"]).read_bytes()}
            if self.upload_error_after_write:
                self.upload_error_after_write = False
                return {"isError": True, "content": [{"type": "text", "text": "fixture upload response lost"}]}, None
            return {"content": [{"type": "text", "text": json.dumps({"id": identity})}]}, None
        if tool == "list_folder":
            assert args["url"] == "https://drive.google.com/drive/folders/selected-folder"
            assert 1 <= args["top_k"] <= 1000
            rows = [{"id": identity, "title": value["name"], "mime_type": "application/octet-stream",
                     "size": len(value["bytes"]), "parent_ids": None}
                    for identity, value in self.files.items()][:args["top_k"]]
            return {"structuredContent": {"files": rows, "next_page_token": "next" if self.partial_listing else None}}, None
        if tool == "fetch":
            identity = args["url"].split("/d/", 1)[1].split("/")[0]
            assert args["download_raw_file"] is True and args["include_base64"] is False
            target = self.root / ("original-" + str(len(self.calls)))
            payload = self.files[identity]["bytes"]
            if self.signed_download:
                return {"structuredContent": {"file_uri": {"download_url": "https://files.oaiusercontent.com/fixture?sig=secret",
                                                            "file_id": "sediment-fixture", "file_name": "original.pack",
                                                            "mime_type": "application/octet-stream"},
                                              "file_size_bytes": len(payload)}}, None
            target.write_bytes(payload + (b"oversized" if self.oversized_download else b""))
            return {"file_uri": "authenticated-fixture-reference"}, str(target)
        if tool == "delete_file":
            identity = args["url"].split("/d/", 1)[1].split("/")[0]
            self.files.pop(identity, None)
            return {"success": True}, None
        raise AssertionError(tool)

class HostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-host-test-")
        self.root = Path(self.temporary.name).resolve()
        self.session = start_session(self.root)
        self.native = NativeDrive(self.root)
        self.stop = threading.Event()
        self.failure = []
        self.adapters = []
        self.thread = threading.Thread(target=self.service, name="test-native-drive-host")
        self.thread.start()

    def tearDown(self):
        self.stop.set()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())
        for adapter in self.adapters:
            adapter.close()
        close_session(self.session, cancel=True)
        self.temporary.cleanup()
        if self.failure:
            raise self.failure[0]

    def service(self):
        try:
            while not self.stop.is_set():
                request = next_request(self.session)
                if request:
                    result, downloaded = self.native.call(request)
                    respond(self.session, request["request_id"], result, materialized_path=downloaded)
                self.stop.wait(0.005)
        except Exception as error:
            self.failure.append(error)

    def transport(self, **kwargs):
        adapter = ConnectedHostAdapter(self.session, timeout_seconds=2, **kwargs)
        self.adapters.append(adapter)
        return ConnectedDriveTransport(adapter, "selected-folder", state_dir=self.root / "transfers")

    def source(self, data=b"original binary evidence\x00\xff"):
        source = self.root / "source.bin"
        source.write_bytes(data)
        return source

    def test_shipped_queue_round_trip_lookup_list_original_readback_and_delete(self):
        transport = self.transport()
        source = self.source()
        locator = transport.put("project/packs/first.pack", source)
        self.assertEqual("object-1", locator["object_id"])
        self.assertEqual(["project/packs/first.pack"], transport.keys("project/"))
        restored = transport.get(locator, self.root / "restored", source.stat().st_size)
        self.assertEqual(source.read_bytes(), restored.read_bytes())
        self.assertEqual(locator, transport.put("project/packs/first.pack", source))
        self.assertEqual(1, sum(call["tool"] == "upload_file" for call in self.native.calls))
        transport.delete(locator)
        transport.delete(locator)  # interrupted deletion is safe to resume
        self.assertEqual([], transport.keys("project/"))
        self.assertEqual({"session.json", "owner.json"}, {p.name for p in self.session.iterdir()})

    def test_binary_folder_lookup_filters_exact_keys_and_rejects_duplicates(self):
        transport = self.transport()
        locator = transport.put("packs/first", self.source())
        self.native.files["unrelated"] = {"name": "other/key", "bytes": b"unrelated"}
        self.assertEqual(locator, transport.stat("packs/first"))
        self.assertFalse(any(call["tool"] == "search" for call in self.native.calls))
        self.native.files["duplicate"] = dict(self.native.files[locator["object_id"]])
        with self.assertRaisesRegex(EvidenceError, "duplicate Drive object"):
            transport.stat("packs/first")

    def test_partial_folder_listing_cannot_prove_missing_upload(self):
        transport = self.transport()
        self.native.partial_listing = True
        with self.assertRaisesRegex(EvidenceError, "enumeration unavailable"):
            transport.stat("packs/missing")

    def test_saturated_folder_scan_cannot_claim_complete_listing(self):
        transport = self.transport()
        self.native.files.update({"id-" + str(i): {"name": "packs/" + str(i), "bytes": b"x"} for i in range(1000)})
        with self.assertRaisesRegex(EvidenceError, "saturated or partial"):
            transport.keys("packs/")

    def test_new_upload_cannot_make_folder_unenumerable_and_creates_no_checkpoint(self):
        transport = self.transport()
        self.native.files.update({"id-" + str(i): {"name": "packs/" + str(i), "bytes": b"x"} for i in range(999)})
        with self.assertRaisesRegex(EvidenceError, "would saturate"):
            transport.put("packs/new", self.source())
        self.assertFalse(any(call["tool"] == "upload_file" for call in self.native.calls))
        self.assertFalse(transport._checkpoint("packs/new").exists())

    def test_configured_object_limit_admits_last_allowed_item_then_blocks_new_upload(self):
        transport = self.transport(max_objects=2)
        transport.put("packs/one", self.source())
        transport.put("packs/two", self.source())
        with self.assertRaisesRegex(EvidenceError, "would saturate"):
            transport.put("packs/three", self.source())
        self.assertEqual(2, sum(call["tool"] == "upload_file" for call in self.native.calls))

    def test_signed_original_reference_is_bounded_materialized_and_automatically_cleaned(self):
        transport = self.transport()
        source = self.source()
        locator = transport.put("packs/first", source)
        self.native.signed_download = True
        class Download(io.BytesIO):
            headers = {"Content-Length": str(source.stat().st_size)}
        class Opener:
            def open(self, request, timeout):
                self.request = request
                return Download(source.read_bytes())
        with patch("evidence.connected_host.urllib.request.build_opener", return_value=Opener()):
            transport.get(locator, self.root / "restored", locator["size"])
        self.assertEqual(source.read_bytes(), (self.root / "restored").read_bytes())
        self.assertEqual([], list(self.session.glob("original-*.bin")))
        self.assertEqual(CONTROL_PEAK_BYTES + locator["size"], transport.working_overhead(download_bytes=locator["size"]))
        self.assertEqual(self.session, transport.host_session_path)

    def test_interrupted_upload_is_recovered_without_second_upload(self):
        transport = self.transport()
        self.native.upload_error_after_write = True
        locator = transport.put("packs/once", self.source())
        self.assertEqual("object-1", locator["object_id"])
        self.assertEqual(1, sum(call["tool"] == "upload_file" for call in self.native.calls))

    def test_missing_native_capability_cannot_complete_setup(self):
        self.native.missing_capability = True
        with self.assertRaisesRegex(EvidenceError, "lacks required"):
            self.transport()

    def test_metadata_outside_selected_folder_is_rejected_before_fetch(self):
        transport = self.transport()
        locator = transport.put("packs/first", self.source())
        self.native.bad_parent = True
        with self.assertRaisesRegex(EvidenceError, "outside the selected"):
            transport.get(locator, self.root / "restored", 1024)
        self.assertFalse(any(call["tool"] == "fetch" for call in self.native.calls))

    def test_oversized_materialized_original_is_rejected_before_destination_copy(self):
        transport = self.transport()
        locator = transport.put("packs/first", self.source())
        self.native.oversized_download = True
        with self.assertRaisesRegex(EvidenceError, "materialized Drive original"):
            transport.get(locator, self.root / "restored", locator["size"])
        self.assertFalse((self.root / "restored").exists())

    def test_changed_materialized_source_preserves_destination_and_cleans_copy(self):
        transport = self.transport()
        locator = transport.put("packs/first", self.source())
        destination = self.root / "restored"
        destination.write_bytes(b"preserved destination")
        with patch("evidence.connected_host._verify_stable", side_effect=EvidenceError("synthetic changing original")):
            with self.assertRaisesRegex(EvidenceError, "changing original"):
                transport.get(locator, destination, locator["size"])
        self.assertEqual(b"preserved destination", destination.read_bytes())
        self.assertEqual([], list(self.root.glob(".host-original-*")))
        self.assertEqual([], list(self.root.glob(".drive-readback-*")))

    def test_list_accounts_native_page_metadata_and_has_complete_results(self):
        transport = self.transport()
        transport.put("packs/first", self.source())
        self.assertEqual(["packs/first"], transport.keys("packs/"))
        transport.max_metadata_bytes = 300
        with self.assertRaisesRegex(EvidenceError, "bound"):
            transport.keys("packs/")

    def test_concurrent_adapter_or_cleanup_cannot_take_live_session(self):
        self.transport()
        with self.assertRaisesRegex(EvidenceError, "already in use"):
            ConnectedHostAdapter(self.session)
        with self.assertRaisesRegex(EvidenceError, "still running"):
            close_session(self.session)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-host-session-")
        self.root = Path(self.temporary.name).resolve()
        self.session = start_session(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_session_lives_outside_git_and_has_private_permissions(self):
        if os.name != "nt":
            self.assertEqual(0o700, self.session.stat().st_mode & 0o777)
            self.assertEqual(0o600, (self.session / "session.json").stat().st_mode & 0o777)
        (self.root / ".git").mkdir()
        with self.assertRaisesRegex(EvidenceError, "outside Git"):
            start_session(self.root)

    @unittest.skipUnless(os.name == "nt", "Windows process-query API")
    def test_windows_liveness_uses_read_only_handle_and_never_signals_process(self):
        with patch("evidence.connected_host.os.kill", side_effect=AssertionError("must not signal Windows process")):
            self.assertTrue(_pid_alive(os.getpid()))

    def test_response_rejects_wrong_request_and_materialized_path_for_upload(self):
        value = {"version": 1, "session_id": read_json(self.session / "session.json", 4096)["session_id"],
                 "request_id": "1" * 32, "expires_at": time.time() + 10, "tool": "upload_file", "arguments": {}}
        atomic_json(self.session / "request.json", value)
        with self.assertRaisesRegex(EvidenceError, "mismatched"):
            respond(self.session, "2" * 32, {})
        with self.assertRaisesRegex(EvidenceError, "only an original-byte"):
            respond(self.session, "1" * 32, {}, materialized_path=str(self.root / "file"))
        with self.assertRaisesRegex(EvidenceError, "metadata bound"):
            respond(self.session, "1" * 32, {"unexpected": "x" * (1024 * 1024)})

    def test_expired_request_not_presented_as_live_tool_work(self):
        atomic_json(self.session / "request.json", {"version": 1, "session_id": read_json(self.session / "session.json", 4096)["session_id"],
                                                    "request_id": "1" * 32, "expires_at": 0})
        with self.assertRaisesRegex(EvidenceError, "expired"):
            next_request(self.session)

    def test_cleanup_preserves_unknown_files_and_requires_explicit_pending_cancel(self):
        (self.session / "keep.txt").write_text("preserve")
        with self.assertRaisesRegex(EvidenceError, "unexpected files"):
            close_session(self.session)
        self.assertTrue((self.session / "keep.txt").exists())
        (self.session / "keep.txt").unlink()
        atomic_json(self.session / "request.json", {})
        with self.assertRaisesRegex(EvidenceError, "pending"):
            close_session(self.session)
        close_session(self.session, cancel=True)
        self.assertFalse(self.session.exists())

    def test_unserviced_request_times_out_and_is_retained(self):
        adapter = ConnectedHostAdapter(self.session, timeout_seconds=1)
        try:
            with self.assertRaisesRegex(EvidenceError, "active agent"):
                adapter({"version": 1, "operation": "capabilities", "folder_id": "selected-folder"})
            self.assertTrue((self.session / "request.json").exists())
        finally:
            adapter.close()

    def test_actual_signed_file_reference_streams_bounded_bytes_without_persisting_url(self):
        request = {"version": 1, "session_id": read_json(self.session / "session.json", 4096)["session_id"],
                   "request_id": "1" * 32, "expires_at": time.time() + 10, "tool": "fetch", "arguments": {},
                   "requirements": {"max_bytes": 3, "expected_size": 3}}
        atomic_json(self.session / "request.json", request)
        class Download(io.BytesIO):
            headers = {"Content-Length": "3"}
        class Opener:
            def open(self, request, timeout):
                return Download(b"abc")
        raw = {"structuredContent": {"file_uri": {"download_url": "https://files.oaiusercontent.com/raw?sig=secret",
                                                 "file_id": "sediment-fixture", "file_name": "original", "mime_type": "application/octet-stream"},
                                      "file_size_bytes": 3}}
        with patch("evidence.connected_host.urllib.request.build_opener", return_value=Opener()):
            respond(self.session, "1" * 32, raw)
        response = read_json(self.session / "response.json", 4096)
        self.assertNotIn("secret", json.dumps(response))
        self.assertNotIn("download_url", json.dumps(response))
        self.assertTrue(response["managed_original"])
        self.assertEqual(b"abc", Path(response["materialized_path"]).read_bytes())
        close_session(self.session, cancel=True)

    def test_oversized_stream_fails_without_byte_overflow_or_signed_url_in_queue(self):
        request = {"version": 1, "session_id": read_json(self.session / "session.json", 4096)["session_id"],
                   "request_id": "1" * 32, "expires_at": time.time() + 10, "tool": "fetch", "arguments": {},
                   "requirements": {"max_bytes": 3, "expected_size": 3}}
        atomic_json(self.session / "request.json", request)
        class Download(io.BytesIO):
            headers = {}
        class Opener:
            def open(self, request, timeout):
                return Download(b"four")
        raw = {"file_uri": {"download_url": "https://files.oaiusercontent.com/raw?sig=secret"}}
        with patch("evidence.connected_host.urllib.request.build_opener", return_value=Opener()):
            respond(self.session, "1" * 32, raw)
        response = read_json(self.session / "response.json", 4096)
        self.assertIn("exceeded reserved bytes", response["result"]["error"])
        self.assertNotIn("secret", json.dumps(response))
        self.assertEqual([], list(self.session.glob("original-*.bin")))

    def test_unapproved_reference_host_never_makes_network_request(self):
        request = {"version": 1, "session_id": read_json(self.session / "session.json", 4096)["session_id"],
                   "request_id": "1" * 32, "expires_at": time.time() + 10, "tool": "fetch", "arguments": {},
                   "requirements": {"max_bytes": 3, "expected_size": 3}}
        atomic_json(self.session / "request.json", request)
        with patch("evidence.connected_host.urllib.request.build_opener") as opener:
            respond(self.session, "1" * 32, {"file_uri": {"download_url": "https://private.invalid/raw?sig=secret"}})
        opener.assert_not_called()
        response = read_json(self.session / "response.json", 4096)
        self.assertIn("unsupported HTTPS destination", response["result"]["error"])
        self.assertNotIn("secret", json.dumps(response))


if __name__ == "__main__":
    unittest.main()
