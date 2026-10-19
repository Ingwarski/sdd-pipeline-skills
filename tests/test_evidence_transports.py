"""Synthetic byte-level transport tests; these do not authenticate to Google Drive."""
from __future__ import annotations

import json
import errno
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "to-sdd-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from evidence.io import EvidenceError, atomic_json, hash_file, read_json
from evidence.transports import (
    ConnectedDriveTransport, JsonCommandAdapter, LocalTransport, RcloneDriveTransport,
)


CAPABILITIES = ["upload", "download_original", "metadata", "lookup", "list", "delete",
                "stable_object_id", "bounded_original_download"]


class ConnectedFixture:
    """A capability adapter with independent original-byte downloads and stable IDs."""

    def __init__(self):
        self.requests = []
        self.objects = {}
        self.capabilities = list(CAPABILITIES)
        self.upload_failure = None
        self.corrupt_download = False
        self.original_download = True
        self.duplicate_lookup = False
        self.repeated_page = False

    def metadata(self, object_id):
        item = self.objects[object_id]
        return {"object_id": object_id, "key": item["key"], "size": len(item["bytes"])}

    def __call__(self, request):
        self.requests.append(dict(request))
        if request.get("version") != 1 or not request.get("folder_id"):
            raise EvidenceError("fixture requires explicit version and selected folder")
        operation = request["operation"]
        if operation in ("capabilities", "handshake"):
            return {"version": 1, "provider": "google_drive", "capabilities": self.capabilities}
        if operation == "lookup":
            matches = [self.metadata(key) for key, item in self.objects.items()
                       if item["key"] == request["key"]]
            if matches and self.duplicate_lookup:
                matches.append(dict(matches[0], object_id="ambiguous-second-id"))
            return {"objects": matches}
        if operation == "metadata":
            return self.metadata(request["object_id"])
        if operation == "list":
            matches = [self.metadata(key) for key, item in self.objects.items()
                       if item["key"].startswith(request.get("prefix", ""))]
            return {"objects": matches, "next_page_token": "loop" if self.repeated_page else None}
        if operation == "upload":
            if self.upload_failure == "before":
                raise TimeoutError("synthetic upload response unavailable")
            payload = Path(request["source_path"]).read_bytes()
            object_id = "synthetic-object-" + str(len(self.objects) + 1)
            self.objects[object_id] = {"key": request["key"], "bytes": payload}
            if self.upload_failure == "after":
                raise TimeoutError("synthetic upload outcome unknown")
            return self.metadata(object_id)
        if operation == "download_original":
            payload = self.objects[request["object_id"]]["bytes"]
            if self.corrupt_download:
                payload = bytes([payload[0] ^ 1]) + payload[1:] if payload else b"unexpected"
            Path(request["destination_path"]).write_bytes(payload)
            return {"object_id": request["object_id"], "size": len(payload),
                    "original_bytes": self.original_download}
        if operation == "delete":
            self.objects.pop(request["object_id"], None)
            return {"deleted": True}
        raise EvidenceError("unsupported fixture operation: " + str(operation))

    def uploads(self):
        return [item for item in self.requests if item["operation"] == "upload"]


RCLONE_SHIM = r'''
import hashlib, json, pathlib, shutil, sys
root = pathlib.Path(__file__).parent / "remote"
root.mkdir(exist_ok=True)
state_path = pathlib.Path(__file__).parent / "shim-state.json"
state = json.loads(state_path.read_text()) if state_path.exists() else {"commands": [], "objects": {}, "mode": ""}
args = sys.argv[1:]
state["commands"].append(args)
state_path.write_text(json.dumps(state))
position = next((i for i, x in enumerate(args) if x in ("lsjson", "copyto", "backend", "deletefile", "listremotes", "rc")), None)
if position is None:
    raise SystemExit(2)
operation = args[position]
tail = args[position + 1:]
def positional(values):
    result = []
    skip = False
    for item in values:
        if skip:
            skip = False
            continue
        if item in ("--config", "--retries", "--low-level-retries", "--timeout", "--contimeout", "--max-depth"):
            skip = True
        elif not item.startswith("--"):
            result.append(item)
    return result
items = positional(tail)
if operation == "rc":
    assert "--loopback" in args and "--rc=false" in args
    request = json.loads(args[args.index("--json") + 1])
    assert type(request["_config"]["MaxTransfer"]) is int
    assert request["_config"]["CutoffMode"] == "HARD"
    if "operations/copyfile" in args:
        operation = "copyto"
        items = [str(pathlib.Path(request["srcFs"]) / request["srcRemote"]),
                 request["dstFs"] + "/" + request["dstRemote"]]
    elif "backend/command" in args:
        operation = "backend"
        items = [request["command"], request["fs"], *request["arg"]]
    else:
        raise SystemExit(2)
def remote_key(value):
    return value.split(":", 1)[1].strip("/")
def metadata(key, prefix=""):
    relative = key[len(prefix):].lstrip("/") if prefix else key
    return {"Path": relative, "Name": pathlib.PurePosixPath(relative).name,
            "Size": (root / key).stat().st_size, "IsDir": False,
            "ID": state["objects"][key], "MimeType": "application/octet-stream"}
if operation == "listremotes":
    print("fixture:")
elif operation == "lsjson":
    prefix = remote_key(items[0])
    rows = [metadata(key, prefix) for key in sorted(state["objects"])
            if key == prefix or key.startswith(prefix + "/") or not prefix]
    if "--recursive" not in args:
        rows = [row for row in rows if "/" not in row["Path"]]
    if state["mode"] == "duplicate" and rows:
        rows.append(dict(rows[0], ID="duplicate-object-id"))
    print(json.dumps(rows))
elif operation == "copyto":
    source, destination = items[:2]
    if ":" in destination:
        if state["mode"] == "fail-before":
            raise SystemExit(7)
        key = remote_key(destination)
        (root / key).parent.mkdir(parents=True, exist_ok=True)
        if state["mode"] == "race-before":
            payload = pathlib.Path(source).read_bytes()
            (root / key).write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
        if not ((root / key).exists() and request["_config"]["IgnoreExisting"]):
            shutil.copyfile(source, root / key)
        state["objects"][key] = "id-" + hashlib.sha256(key.encode()).hexdigest()[:20]
        state_path.write_text(json.dumps(state))
        if state["mode"] == "fail-after":
            raise SystemExit(7)
    else:
        shutil.copyfile(root / remote_key(source), destination)
elif operation == "backend":
    if items[0] != "copyid":
        raise SystemExit(2)
    remote, object_id, destination = items[1:4]
    key = next(key for key, identity in state["objects"].items() if identity == object_id)
    if state["mode"] == "corrupt-readback":
        payload = (root / key).read_bytes()
        pathlib.Path(destination).write_bytes(bytes([payload[0] ^ 1]) + payload[1:] if payload else b"unexpected")
    elif state["mode"] == "oversize-readback":
        pathlib.Path(destination).write_bytes((root / key).read_bytes() + b"!")
    else:
        shutil.copyfile(root / key, destination)
elif operation == "deletefile":
    key = remote_key(items[0])
    (root / key).unlink(missing_ok=True)
    state["objects"].pop(key, None)
    state_path.write_text(json.dumps(state))
    if state["mode"] == "fail-delete-after":
        raise SystemExit(7)
'''


class TransportTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-evidence-transport-")
        self.addCleanup(self.temp.cleanup)
        # Resolve /var -> /private/var on macOS: transport safety rejects linked parents.
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.bin"
        self.source.write_bytes(b"synthetic original evidence\x00\xff\n" * 128)

    def state(self, name="state"):
        return self.root / name

    def assert_roundtrip(self, transport, key="packs/synthetic.pack"):
        locator = transport.put(key, self.source)
        self.assertEqual(key, locator["key"])
        self.assertTrue(locator["object_id"])
        self.assertEqual(self.source.stat().st_size, locator["size"])
        self.assertEqual(locator, transport.stat(locator))
        destination = self.root / "readback.bin"
        actual = transport.get(locator, destination, max_bytes=locator["size"])
        self.assertEqual(destination, Path(actual))
        self.assertEqual(self.source.read_bytes(), destination.read_bytes())
        self.assertIn(key, transport.keys("packs/"))
        return locator


class LocalTransportTests(TransportTestCase):
    def local(self):
        return LocalTransport(self.root / "durable")

    def test_roundtrip_and_cold_restoration(self):
        locator = self.assert_roundtrip(self.local())
        destination = self.root / "cold.bin"
        self.local().get(locator, destination, max_bytes=locator["size"])
        self.assertEqual(self.source.read_bytes(), destination.read_bytes())

    def test_selected_disk_without_hardlinks_uses_atomic_coordinator_write(self):
        with patch("evidence.transports.os.link", side_effect=OSError(errno.EOPNOTSUPP, "synthetic selected disk")):
            locator = self.assert_roundtrip(self.local())
        self.assertEqual(self.source.stat().st_size, locator["size"])

    def test_immutable_key_deduplicates_and_rejects_changed_bytes(self):
        transport = self.local()
        first = transport.put("packs/p.pack", self.source)
        self.assertEqual(first, transport.put("packs/p.pack", self.source))
        self.source.write_bytes(b"different evidence")
        with self.assertRaises(ValueError):
            transport.put("packs/p.pack", self.source)
        self.assertEqual(["packs/p.pack"], transport.keys())

    def test_size_bound_preserves_existing_destination(self):
        transport = self.local()
        locator = transport.put("packs/p.pack", self.source)
        destination = self.root / "existing.bin"
        destination.write_bytes(b"retain existing output")
        with self.assertRaises(ValueError):
            transport.get(locator, destination, max_bytes=locator["size"] - 1)
        self.assertEqual(b"retain existing output", destination.read_bytes())

    def test_delete_only_selected_object(self):
        transport = self.local()
        selected = transport.put("packs/selected.pack", self.source)
        retained = transport.put("packs/retained.pack", self.source)
        transport.delete(selected)
        self.assertEqual(["packs/retained.pack"], transport.keys())
        self.assertEqual(retained, transport.stat(retained))

    def test_local_total_object_listing_is_bounded(self):
        transport = self.local()
        transport.put("packs/one.pack", self.source)
        transport.put("packs/two.pack", self.source)
        with self.assertRaises(ValueError):
            LocalTransport(self.root / "durable", max_objects=1).keys()

    def test_independent_readback_cannot_replace_durable_object(self):
        transport = self.local()
        locator = transport.put("packs/p.pack", self.source)
        with self.assertRaises(ValueError):
            transport.get(locator, self.root / "durable/packs/p.pack", max_bytes=locator["size"])
        self.assertEqual(self.source.read_bytes(), (self.root / "durable/packs/p.pack").read_bytes())

    def test_unsafe_keys_rejected(self):
        transport = self.local()
        for key in ("../outside", "/absolute", "packs//p", "packs/./p", "a\\b", "C:drive", "a\x00b"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                transport.put(key, self.source)
        self.assertEqual([], transport.keys())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_linked_source_destination_and_store_rejected(self):
        source_link = self.root / "source-link"
        source_link.symlink_to(self.source)
        transport = self.local()
        with self.assertRaises(ValueError):
            transport.put("packs/linked.pack", source_link)
        locator = transport.put("packs/p.pack", self.source)
        target = self.root / "protected.bin"
        target.write_bytes(b"protected")
        destination = self.root / "destination-link"
        destination.symlink_to(target)
        with self.assertRaises(ValueError):
            transport.get(locator, destination, max_bytes=locator["size"])
        self.assertEqual(b"protected", target.read_bytes())
        linked_root = self.root / "linked-store"
        linked_root.symlink_to(self.root / "durable", target_is_directory=True)
        with self.assertRaises(ValueError):
            LocalTransport(linked_root)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unavailable")
    def test_special_source_file_rejected_without_opening(self):
        fifo = self.root / "source-fifo"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            self.local().put("packs/fifo.pack", fifo)


class ConnectedDriveTransportTests(TransportTestCase):
    def test_locator_identity_utf8_byte_bound_and_control_characters(self):
        for identity in ("x" * 4097, "漢" * 1366, "id\x7f", "id\x85", "id\ud800"):
            def adapter(request):
                if request["operation"] == "capabilities":
                    return {"version":1, "provider":"google_drive", "capabilities":CAPABILITIES}
                if request["operation"] == "lookup":
                    return {"objects":[{"object_id":identity, "key":request["key"], "size":0}]}
                raise AssertionError("must not persist oversized provider identity")
            transport = ConnectedDriveTransport(adapter, "synthetic-folder", state_dir=self.state())
            with self.subTest(identity_size=len(identity)), self.assertRaises(EvidenceError):
                transport.stat("packs/p.pack")
            self.assertEqual([], list(self.state().glob("*.json")))

    def test_key_utf8_bound_precedes_upload_or_checkpoint_persistence(self):
        transport = self.connected()
        for key in ("x" * 4097, "漢" * 1366, "packs/control\x7f"):
            with self.subTest(key_size=len(key)), self.assertRaises(EvidenceError):
                transport.put(key, self.source)
        self.assertEqual([], self.adapter.uploads())
        self.assertEqual([], list(self.state().glob("*.json")))

    def test_key_and_identity_exact_utf8_boundary_is_accepted(self):
        def adapter(request):
            if request["operation"] == "capabilities":
                return {"version":1, "provider":"google_drive", "capabilities":CAPABILITIES}
            return {"objects":[{"object_id":"x" * 4096,"key":request["key"],"size":0}]}
        transport = ConnectedDriveTransport(adapter, "synthetic-folder", state_dir=self.state())
        self.assertEqual("x" * 4096, transport.stat("k" * 4096)["object_id"])

    def setUp(self):
        super().setUp()
        self.adapter = ConnectedFixture()

    def connected(self, **kwargs):
        return ConnectedDriveTransport(self.adapter, "synthetic-selected-folder", state_dir=self.state(), **kwargs)

    def test_roundtrip_original_download_and_cold_restoration(self):
        locator = self.assert_roundtrip(self.connected())
        destination = self.root / "cold.bin"
        shutil.rmtree(self.state())
        restored = ConnectedDriveTransport(self.adapter, "synthetic-selected-folder", state_dir=self.state("cold-state"))
        restored.get(locator, destination, max_bytes=locator["size"])
        self.assertEqual(self.source.read_bytes(), destination.read_bytes())
        operations = [request["operation"] for request in self.adapter.requests]
        self.assertIn("download_original", operations)
        self.assertEqual(1, len(self.adapter.uploads()))

    def test_same_bytes_reuse_remote_identity_and_changed_bytes_fail(self):
        transport = self.connected()
        first = transport.put("packs/p.pack", self.source)
        self.assertEqual(first, transport.put("packs/p.pack", self.source))
        self.assertEqual(1, len(self.adapter.uploads()))
        self.source.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            transport.put("packs/p.pack", self.source)
        self.assertEqual(1, len(self.adapter.uploads()))

    def test_missing_original_download_capability_blocks_setup(self):
        self.adapter.capabilities.remove("download_original")
        with self.assertRaisesRegex(ValueError, "capabil|download_original"):
            self.connected()
        self.assertEqual([], self.adapter.uploads())

    def test_unbounded_download_capability_blocks_setup(self):
        self.adapter.capabilities.remove("bounded_original_download")
        with self.assertRaisesRegex(ValueError, "capabil|bounded_original_download"):
            self.connected()
        self.assertEqual([], self.adapter.uploads())

    def test_provider_and_version_must_match_protocol(self):
        original = self.adapter
        for response in ({"version": 2, "provider": "google_drive", "capabilities": CAPABILITIES},
                         {"version": 1, "provider": "another-provider", "capabilities": CAPABILITIES}):
            with self.subTest(response=response):
                def adapter(request):
                    if request["operation"] in ("capabilities", "handshake"):
                        return response
                    return original(request)
                with self.assertRaises(ValueError):
                    ConnectedDriveTransport(adapter, "synthetic-folder", state_dir=self.state("version-state"))

    def test_duplicate_remote_keys_are_not_accepted(self):
        transport = self.connected()
        transport.put("packs/p.pack", self.source)
        self.adapter.duplicate_lookup = True
        with self.assertRaises(ValueError):
            transport.stat("packs/p.pack")

    def test_unknown_upload_outcome_never_reissues_upload_after_restart(self):
        self.adapter.upload_failure = "after"
        transport = self.connected()
        try:
            transport.put("packs/p.pack", self.source)
        except ValueError:
            pass
        self.assertEqual(1, len(self.adapter.uploads()))
        self.adapter.upload_failure = None
        # It may reconcile verified remote bytes or require explicit reconciliation,
        # but an unknown upload must never be retried as a fresh payload upload.
        try:
            self.connected().put("packs/p.pack", self.source)
        except ValueError:
            pass
        self.assertEqual(1, len(self.adapter.uploads()))

    def test_interrupted_upload_without_visible_object_keeps_pending_state(self):
        self.adapter.upload_failure = "before"
        with self.assertRaises(ValueError):
            self.connected().put("packs/p.pack", self.source)
        self.adapter.upload_failure = None
        with self.assertRaises(ValueError):
            self.connected().put("packs/p.pack", self.source)
        self.assertEqual(1, len(self.adapter.uploads()))
        self.assertTrue(any(self.state().iterdir()), "pending state must survive a fresh transport")

    def test_unknown_upload_errors_name_exact_key_and_both_recovery_entrypoints(self):
        key = "projects/synthetic-project/authority/generation-0001.json"
        self.adapter.upload_failure = "before"
        transport = self.connected()
        for _ in range(2):
            with self.assertRaises(EvidenceError) as raised:
                transport.put(key, self.source)
            self.assertIn(key, str(raised.exception))
            self.assertIn("acknowledge-missing-upload --key", str(raised.exception))
            self.assertIn("configure --acknowledge-missing-upload", str(raised.exception))

    def test_checkpoint_quota_counts_escaped_wire_bytes_before_upload(self):
        transport = self.connected()
        transport.checkpoint_metadata_bytes = 1024
        with self.assertRaisesRegex(EvidenceError, "checkpoint exceeds"):
            transport.put("packs/" + "é" * 200, self.source)
        self.assertEqual([], self.adapter.uploads())
        self.assertEqual([], list(self.state().iterdir()))

    def test_checkpoint_atomic_wire_size_boundary_preserves_previous_record(self):
        transport = self.connected()
        record = {"version": 1, "key": "packs/" + "é" * 16}
        wire = (json.dumps(record, sort_keys=True, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode()
        transport.checkpoint_metadata_bytes = len(wire)
        target = transport._checkpoint(record["key"])
        transport._write_checkpoint(target, record)
        self.assertEqual(wire, target.read_bytes())
        with self.assertRaisesRegex(EvidenceError, "checkpoint exceeds"):
            transport._write_checkpoint(target, dict(record, key=record["key"] + "é"))
        self.assertEqual(wire, target.read_bytes())

    def test_located_checkpoint_overflow_retains_pending_and_retry_reuses_upload(self):
        transport = self.connected()
        key = "packs/p.pack"
        digest, size = hash_file(self.source)
        pending = {"version": 1, "key": key, "sha256": digest, "size": size, "state": "pending"}
        pending_wire = (json.dumps(pending, sort_keys=True, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode()
        transport.checkpoint_metadata_bytes = len(pending_wire)
        with self.assertRaisesRegex(EvidenceError, "checkpoint exceeds"):
            transport.put(key, self.source)
        self.assertEqual("pending", read_json(transport._checkpoint(key), len(pending_wire))["state"])
        self.assertEqual(1, len(self.adapter.uploads()))
        transport.checkpoint_metadata_bytes = 64 * 1024
        transport.put(key, self.source)
        self.assertEqual(1, len(self.adapter.uploads()))
        self.assertEqual("located", read_json(transport._checkpoint(key), 64 * 1024)["state"])

    def test_missing_upload_acknowledgement_requires_matching_pending_checkpoint(self):
        transport = self.connected()
        key = "packs/p.pack"
        with self.assertRaisesRegex(EvidenceError, "no owned local"):
            transport.acknowledge_missing_upload(key)
        self.adapter.upload_failure = "before"
        with self.assertRaises(EvidenceError):
            transport.put(key, self.source)
        checkpoint = transport._checkpoint(key)
        valid = read_json(checkpoint, 65536)
        for changed in (dict(valid, key="packs/other.pack"), dict(valid, sha256="invalid"),
                        dict(valid, size=True), dict(valid, version=2), dict(valid, state="unknown")):
            atomic_json(checkpoint, changed)
            with self.assertRaisesRegex(EvidenceError, "invalid or belongs"):
                transport.acknowledge_missing_upload(key)
            self.assertTrue(checkpoint.exists())
        atomic_json(checkpoint, dict(valid, state="located"))
        with self.assertRaisesRegex(EvidenceError, "only a pending"):
            transport.acknowledge_missing_upload(key)
        self.assertTrue(checkpoint.exists())

    def test_changed_pending_checkpoint_is_preserved_during_acknowledgement(self):
        transport = self.connected()
        key = "packs/p.pack"
        self.adapter.upload_failure = "before"
        with self.assertRaises(EvidenceError):
            transport.put(key, self.source)
        checkpoint = transport._checkpoint(key)
        previous = read_json(checkpoint, 65536)
        def change(_):
            atomic_json(checkpoint, dict(previous, state="located"))
            return None
        with patch.object(transport, "_find_retry", side_effect=change):
            with self.assertRaisesRegex(EvidenceError, "changed during"):
                transport.acknowledge_missing_upload(key)
        self.assertTrue(checkpoint.exists())

    def test_nonobject_checkpoints_fail_closed_in_put_and_acknowledgement(self):
        transport = self.connected()
        key = "packs/p.pack"
        checkpoint = transport._checkpoint(key)
        for record in ([], ["unexpected"], None, True, 12, "unexpected"):
            for operation in (lambda: transport.put(key, self.source),
                              lambda: transport.acknowledge_missing_upload(key)):
                with self.subTest(record=record, operation=operation):
                    atomic_json(checkpoint, record)
                    previous = checkpoint.read_bytes()
                    with self.assertRaisesRegex(EvidenceError, "checkpoint"):
                        operation()
                    self.assertEqual(previous, checkpoint.read_bytes())
        self.assertEqual([], self.adapter.uploads())

    def test_explicit_missing_upload_acknowledgement_allows_safe_retry(self):
        transport = self.connected()
        self.adapter.upload_failure = "before"
        with self.assertRaises(ValueError):
            transport.put("packs/p.pack", self.source)
        self.adapter.upload_failure = None
        transport.acknowledge_missing_upload("packs/p.pack")
        locator = transport.put("packs/p.pack", self.source)
        self.assertEqual(self.source.stat().st_size, locator["size"])
        self.assertEqual(2, len(self.adapter.uploads()))

    def test_existing_object_cannot_be_acknowledged_as_missing(self):
        transport = self.connected()
        transport.put("packs/p.pack", self.source)
        with self.assertRaisesRegex(ValueError, "exists"):
            transport.acknowledge_missing_upload("packs/p.pack")
        self.assertEqual(1, len(self.adapter.uploads()))

    def test_original_byte_attestation_required(self):
        transport = self.connected()
        locator = transport.put("packs/p.pack", self.source)
        self.adapter.original_download = False
        with self.assertRaises(ValueError):
            transport.get(locator, self.root / "readback.bin", max_bytes=locator["size"])

    def test_corrupt_same_size_original_bytes_do_not_reuse_immutable_key(self):
        transport = self.connected()
        transport.put("packs/p.pack", self.source)
        self.adapter.corrupt_download = True
        with self.assertRaisesRegex(ValueError, "original bytes|immutable"):
            transport.put("packs/p.pack", self.source)
        self.assertEqual(1, len(self.adapter.uploads()))

    def test_size_bound_is_sent_to_connector_and_enforced(self):
        transport = self.connected()
        locator = transport.put("packs/p.pack", self.source)
        with self.assertRaises(ValueError):
            transport.get(locator, self.root / "small.bin", max_bytes=locator["size"] - 1)
        destination = self.root / "readback.bin"
        transport.get(locator, destination, max_bytes=locator["size"])
        request = [item for item in self.adapter.requests if item["operation"] == "download_original"][-1]
        self.assertEqual(locator["size"], request["max_bytes"])

    def test_object_listing_aggregate_and_pagination_are_bounded(self):
        transport = self.connected(max_objects=1)
        transport.put("packs/one.pack", self.source)
        self.adapter.objects["synthetic-extra"] = {"key": "packs/two.pack", "bytes": b"extra"}
        with self.assertRaises(ValueError):
            transport.keys()

    def test_paginated_metadata_bytes_have_a_combined_bound(self):
        original = self.adapter
        def adapter(request):
            if request["operation"] == "list":
                index = int(request.get("page_token") or "0")
                return {"objects": [{"object_id": "id-" + str(index), "key": "packs/" + str(index), "size": 0}],
                        "next_page_token": str(index + 1) if index < 20 else None,
                        "padding": "x" * 80}
            return original(request)
        transport = ConnectedDriveTransport(adapter, "synthetic-folder", state_dir=self.state(),
                                            max_metadata_bytes=512, max_objects=100)
        with self.assertRaises(ValueError):
            transport.keys()

    def test_missing_stable_identity_and_duplicate_list_ids_fail(self):
        original = self.adapter
        for rows in ([{"key": "packs/one", "size": 1}],
                     [{"object_id": "same-id", "key": "packs/one", "size": 1},
                      {"object_id": "same-id", "key": "packs/two", "size": 1}]):
            with self.subTest(rows=rows):
                def adapter(request):
                    if request["operation"] == "list":
                        return {"objects": rows, "next_page_token": None}
                    return original(request)
                transport = ConnectedDriveTransport(adapter, "synthetic-folder", state_dir=self.state())
                with self.assertRaises(ValueError):
                    transport.keys()

    def test_repeated_pagination_token_fails_without_infinite_loop(self):
        transport = self.connected(max_objects=3)
        self.adapter.repeated_page = True
        with self.assertRaises(ValueError):
            transport.keys()
        self.assertLessEqual(len([x for x in self.adapter.requests if x["operation"] == "list"]), 4)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_unsafe_source_and_destination_do_not_cross_links(self):
        transport = self.connected()
        source_link = self.root / "source-link"
        source_link.symlink_to(self.source)
        with self.assertRaises(ValueError):
            transport.put("packs/linked.pack", source_link)
        self.assertEqual([], self.adapter.uploads())
        locator = transport.put("packs/p.pack", self.source)
        target = self.root / "retain.bin"
        target.write_bytes(b"retain")
        destination = self.root / "destination-link"
        destination.symlink_to(target)
        with self.assertRaises(ValueError):
            transport.get(locator, destination, max_bytes=locator["size"])
        self.assertEqual(b"retain", target.read_bytes())


class RcloneDriveTransportTests(TransportTestCase):
    def setUp(self):
        super().setUp()
        self.executable = self.root / "rclone-fixture"
        self.executable.write_text("#!" + sys.executable + "\n" + RCLONE_SHIM, encoding="utf-8")
        self.executable.chmod(0o700)
        if os.name == "nt" or any(character.isspace() for character in sys.executable):
            # Windows cannot launch a shebang file directly; POSIX shebangs also
            # cannot quote interpreter paths containing spaces. Adapt only this
            # fixture launch; subprocesses and all protocol bytes remain real.
            import evidence.transports as module
            original_popen = module.subprocess.Popen
            def launch_fixture(command, *args, **kwargs):
                if command[0] == str(self.executable):
                    command = [sys.executable, str(self.executable), *command[1:]]
                return original_popen(command, *args, **kwargs)
            launcher = patch.object(module.subprocess, "Popen", side_effect=launch_fixture)
            launcher.start()
            self.addCleanup(launcher.stop)
        self.config = self.root / "rclone-fixture.conf"
        self.config.write_text("[fixture]\ntype = drive\n", encoding="utf-8")

    def rclone(self, **kwargs):
        return RcloneDriveTransport("fixture:objects", config=self.config,
                                   executable=str(self.executable), state_dir=self.state(), **kwargs)

    def shim_state(self):
        path = self.root / "shim-state.json"
        return json.loads(path.read_text()) if path.exists() else {"commands": [], "objects": {}, "mode": ""}

    def mode(self, mode):
        state = self.shim_state()
        state["mode"] = mode
        (self.root / "shim-state.json").write_text(json.dumps(state))

    def uploads(self):
        return [args for args in self.shim_state()["commands"] if "operations/copyfile" in args]

    def test_roundtrip_uses_stable_id_and_independent_original_download(self):
        locator = self.assert_roundtrip(self.rclone())
        self.assertTrue(locator["object_id"].startswith("id-"))
        downloads = [args for args in self.shim_state()["commands"] if "backend/command" in args]
        self.assertTrue(downloads)
        self.assertEqual("copyid", json.loads(downloads[0][downloads[0].index("--json") + 1])["command"])

    def test_transfer_limits_remain_exact_numeric_hard_bounds(self):
        transport = self.rclone()
        for size in (0, 65535, 1024 * 1024 - 1, 1024 * 1024 + 1, 8 * 1024 * 1024 + 1):
            with self.subTest(size=size):
                previous = len(self.shim_state()["commands"])
                self.source.write_bytes(b"x" * size)
                locator = transport.put("packs/exact-" + str(size), self.source)
                destination = self.root / ("exact-" + str(size))
                transport.get(locator, destination, max_bytes=size)
                self.assertEqual(hash_file(self.source), hash_file(destination))
                commands = [args for args in self.shim_state()["commands"][previous:] if "--json" in args]
                self.assertEqual(3, len(commands))
                for args in commands:
                    request = json.loads(args[args.index("--json") + 1])
                    self.assertEqual(max(1, size), request["_config"]["MaxTransfer"])
                    self.assertEqual("HARD", request["_config"]["CutoffMode"])
                    self.assertTrue(request["_config"]["CheckSum"])
                    self.assertEqual("operations/copyfile" in args, request["_config"]["Immutable"])
                    self.assertEqual("operations/copyfile" in args, request["_config"]["IgnoreExisting"])
                    self.assertNotIn("--max-transfer", args)
                    self.assertIn("--loopback", args)
                    self.assertIn("--rc=false", args)

    def test_transfer_rejects_inexact_json_integer_bound_before_subprocess(self):
        transport = self.rclone()
        with self.assertRaisesRegex(EvidenceError, "exact JSON integer"):
            transport._transfer("operations/copyfile", {}, 2 ** 53)
        self.assertEqual([], self.shim_state()["commands"])

    def test_oversized_readback_preserves_destination_and_removes_partial(self):
        transport = self.rclone()
        locator = transport.put("packs/p.pack", self.source)
        target = self.root / "preserved.bin"
        target.write_bytes(b"previous verified bytes")
        self.mode("oversize-readback")
        with self.assertRaisesRegex(EvidenceError, "bound"):
            transport.get(locator, target, locator["size"])
        self.assertEqual(b"previous verified bytes", target.read_bytes())
        self.assertEqual([], list(self.root.glob(".rclone-readback-*")))

    def test_raced_immutable_upload_preserves_conflicting_bytes_and_pending_checkpoint(self):
        transport = self.rclone()
        expected = self.source.read_bytes()
        self.mode("race-before")
        with self.assertRaisesRegex(EvidenceError, "immutable|original bytes"):
            transport.put("packs/p.pack", self.source)
        self.assertEqual(bytes([expected[0] ^ 1]) + expected[1:],
                         (self.root / "remote/objects/packs/p.pack").read_bytes())
        self.assertEqual("pending", json.loads(transport._checkpoint("packs/p.pack").read_text())["state"])
        self.assertEqual(1, len(self.uploads()))

    def test_cold_restore_without_original_state_database(self):
        locator = self.rclone().put("packs/p.pack", self.source)
        shutil.rmtree(self.state())
        destination = self.root / "cold.bin"
        self.rclone().get(locator, destination, max_bytes=locator["size"])
        self.assertEqual(self.source.read_bytes(), destination.read_bytes())

    def test_immutable_keys_reuse_bytes_and_reject_mutation(self):
        transport = self.rclone()
        first = transport.put("packs/p.pack", self.source)
        self.assertEqual(first, transport.put("packs/p.pack", self.source))
        self.assertEqual(1, len(self.uploads()))
        self.source.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            transport.put("packs/p.pack", self.source)
        self.assertEqual(1, len(self.uploads()))

    def test_missing_executable_reports_optional_transport_dependency(self):
        with self.assertRaisesRegex(ValueError, "rclone|executable|available"):
            RcloneDriveTransport("fixture:objects", executable=str(self.root / "absent"), state_dir=self.state()).keys()

    def test_missing_credentials_do_not_fall_back_to_another_remote(self):
        with self.assertRaisesRegex(ValueError, "credentials missing|rclone config"):
            RcloneDriveTransport("fixture:objects", config=self.root / "missing.conf",
                                 executable=str(self.executable), state_dir=self.state())

    def test_unsafe_remote_paths_fail_before_subprocess(self):
        for remote in ("fixture:../escape", "fixture:/absolute", "fixture:objects//nested", "fixture:objects\\nested"):
            with self.subTest(remote=remote), self.assertRaises(ValueError):
                RcloneDriveTransport(remote, executable=str(self.executable), state_dir=self.state())
        self.assertEqual([], self.shim_state()["commands"])

    def test_duplicate_remote_objects_fail_instead_of_picking_one(self):
        transport = self.rclone()
        transport.put("packs/p.pack", self.source)
        self.mode("duplicate")
        with self.assertRaises(ValueError):
            transport.stat("packs/p.pack")

    def test_unknown_upload_outcome_is_not_uploaded_again(self):
        self.mode("fail-after")
        try:
            self.rclone(attempts=3).put("packs/p.pack", self.source)
        except ValueError:
            pass
        self.assertEqual(1, len(self.uploads()))
        self.mode("")
        try:
            self.rclone().put("packs/p.pack", self.source)
        except ValueError:
            pass
        self.assertEqual(1, len(self.uploads()))

    def test_corrupt_same_size_readback_blocks_immutable_reuse(self):
        transport = self.rclone()
        transport.put("packs/p.pack", self.source)
        self.mode("corrupt-readback")
        with self.assertRaisesRegex(ValueError, "original bytes|immutable"):
            transport.put("packs/p.pack", self.source)
        self.assertEqual(1, len(self.uploads()))

    def test_failed_upload_with_no_object_keeps_pending_checkpoint(self):
        self.mode("fail-before")
        with self.assertRaises(ValueError):
            self.rclone().put("packs/p.pack", self.source)
        self.mode("")
        with self.assertRaises(ValueError):
            self.rclone().put("packs/p.pack", self.source)
        self.assertEqual(1, len(self.uploads()))

    def test_explicit_missing_upload_acknowledgement_allows_retry(self):
        transport = self.rclone()
        self.mode("fail-before")
        with self.assertRaises(ValueError):
            transport.put("packs/p.pack", self.source)
        self.mode("")
        transport.acknowledge_missing_upload("packs/p.pack")
        locator = transport.put("packs/p.pack", self.source)
        self.assertEqual(self.source.stat().st_size, locator["size"])
        self.assertEqual(2, len(self.uploads()))

    def test_existing_remote_object_cannot_be_acknowledged_as_missing(self):
        transport = self.rclone()
        transport.put("packs/p.pack", self.source)
        with self.assertRaisesRegex(ValueError, "exists"):
            transport.acknowledge_missing_upload("packs/p.pack")
        self.assertEqual(1, len(self.uploads()))

    def test_listing_bound_cannot_be_bypassed_by_multiple_objects(self):
        transport = self.rclone()
        transport.put("packs/one.pack", self.source)
        transport.put("packs/two.pack", self.source)
        with self.assertRaises(ValueError):
            self.rclone(max_objects=1).keys()

    def test_readback_size_bound_and_delete(self):
        transport = self.rclone()
        locator = transport.put("packs/p.pack", self.source)
        with self.assertRaises(ValueError):
            transport.get(locator, self.root / "small.bin", max_bytes=locator["size"] - 1)
        transport.delete(locator)
        self.assertEqual([], transport.keys())

    def test_interrupted_remote_deletion_resumes_as_verified_absence(self):
        transport = self.rclone()
        locator = transport.put("packs/p.pack", self.source)
        self.mode("fail-delete-after")
        with self.assertRaises(EvidenceError):
            transport.delete(locator)
        self.assertEqual({}, self.shim_state()["objects"])
        self.assertTrue(transport._checkpoint(locator["key"]).exists())
        self.mode("")
        self.rclone().delete(locator)
        self.assertFalse(transport._checkpoint(locator["key"]).exists())
        self.assertEqual(1, len([args for args in self.shim_state()["commands"] if "deletefile" in args]))

    def test_absent_delete_does_not_treat_failed_lookup_as_absence(self):
        transport = self.rclone()
        locator = {"object_id":"absent-id", "key":"packs/absent.pack", "size":0}
        with patch.object(transport, "_list", side_effect=EvidenceError("synthetic credentials unavailable")):
            with self.assertRaisesRegex(EvidenceError, "credentials"):
                transport.delete(locator)
        self.assertEqual([], self.shim_state()["commands"])

    def test_delete_refuses_replacement_object_identity(self):
        transport = self.rclone()
        locator = transport.put("packs/p.pack", self.source)
        with self.assertRaisesRegex(EvidenceError, "identity"):
            transport.delete(dict(locator, object_id="replaced-id"))
        self.assertEqual(0, len([args for args in self.shim_state()["commands"] if "deletefile" in args]))

    def test_provider_filename_metadata_is_bounded(self):
        transport = self.rclone()
        values = [{"Name":"x" * 4097,"Path":"packs/p.pack","ID":"id","Size":0}]
        with patch.object(transport, "_command", return_value=json.dumps(values).encode()):
            with self.assertRaisesRegex(EvidenceError, "4096"):
                transport.keys()


class JsonCommandAdapterTests(TransportTestCase):
    def adapter(self, body, **kwargs):
        script = self.root / "adapter.py"
        script.write_text(body, encoding="utf-8")
        return JsonCommandAdapter([sys.executable, str(script)], **kwargs)

    def test_json_request_response_are_structured_and_bounded(self):
        adapter = self.adapter("import json, sys\nx=json.load(sys.stdin)\nprint(json.dumps({'version': x['version']}))\n")
        self.assertEqual({"version": 1}, adapter({"version": 1, "operation": "capabilities"}))

    def test_nonzero_error_does_not_disclose_stderr(self):
        adapter = self.adapter("import sys\nsys.stderr.write('synthetic-secret-must-not-appear')\nsys.exit(3)\n")
        with self.assertRaises(ValueError) as raised:
            adapter({"version": 1})
        self.assertNotIn("synthetic-secret-must-not-appear", str(raised.exception))

    def test_oversized_response_fails(self):
        adapter = self.adapter("print('x' * 4096)\n", max_metadata_bytes=256)
        with self.assertRaises(ValueError):
            adapter({"version": 1})

    def test_invalid_duplicate_or_nonobject_json_fails(self):
        for payload in ('{"version":1,"version":2}', '[]', '{invalid json', '{"x":NaN}'):
            with self.subTest(payload=payload):
                adapter = self.adapter("print(" + repr(payload) + ")\n")
                with self.assertRaises(ValueError):
                    adapter({"version": 1})

    def test_timeout_stops_command(self):
        adapter = self.adapter("import time\ntime.sleep(10)\n", timeout_seconds=1)
        with self.assertRaises(ValueError):
            adapter({"version": 1})

    def test_denied_group_signal_falls_back_to_owned_child_and_preserves_error(self):
        import evidence.transports as module
        adapter = self.adapter("import sys,time\nsys.stdout.write('x' * 4096)\nsys.stdout.flush()\ntime.sleep(10)\n", max_metadata_bytes=256)
        original_popen, processes = module.subprocess.Popen, []
        def track(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process
        with patch.object(module.subprocess, "Popen", side_effect=track), patch.object(module.os, "killpg", create=True, side_effect=PermissionError(errno.EPERM, "synthetic denial")):
            with self.assertRaisesRegex(EvidenceError, "output exceeds metadata bound"):
                adapter({"version":1})
        self.assertEqual(1, len(processes))
        self.assertIsNotNone(processes[0].returncode)
        self.assertTrue(processes[0].stdin.closed)
        self.assertFalse(any(t.name == "sdd-transport-input" and t.is_alive() for t in threading.enumerate()))

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX only")
    def test_changed_process_group_never_signals_unrelated_group(self):
        import evidence.transports as module
        adapter = self.adapter("import sys,time\nsys.stdout.write('x' * 4096)\nsys.stdout.flush()\ntime.sleep(10)\n", max_metadata_bytes=256)
        original_popen, processes = module.subprocess.Popen, []
        def track(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process
        with patch.object(module.subprocess, "Popen", side_effect=track), patch.object(module.os, "getpgid", side_effect=lambda pid:pid + 1), patch.object(module.os, "killpg") as group_signal:
            with self.assertRaisesRegex(EvidenceError, "output exceeds metadata bound"):
                adapter({"version":1})
        group_signal.assert_not_called()
        self.assertIsNotNone(processes[0].returncode)

    def test_nonreading_bridge_large_stdin_cannot_bypass_timeout(self):
        import evidence.transports as module
        adapter = self.adapter("import time\ntime.sleep(10)\n", timeout_seconds=1)
        original_popen, processes = module.subprocess.Popen, []
        def track(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process
        started = time.monotonic()
        with patch.object(module.subprocess, "Popen", side_effect=track):
            with self.assertRaisesRegex(EvidenceError, "timed out"):
                adapter({"version":1,"synthetic_input":"x" * (2 * 1024 * 1024)})
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(1, len(processes))
        self.assertIsNotNone(processes[0].returncode)
        self.assertTrue(processes[0].stdin.closed)
        self.assertFalse(any(t.name == "sdd-transport-input" and t.is_alive() for t in threading.enumerate()))


if __name__ == "__main__":
    unittest.main()
