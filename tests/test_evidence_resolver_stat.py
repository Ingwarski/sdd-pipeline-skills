"""Prepared split evidence and memo invalidation use comparable native clocks."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence import io, resolver as module
from evidence.resolver import EvidenceResolver


def digest(value):
    return hashlib.sha256(value).hexdigest()


@contextmanager
def windows_stat_clocks():
    """Model CPython's path creation-ctime and fd metadata-change-ctime."""
    original_lstat, original_fstat = Path.lstat, os.fstat
    def adapt(info, *, by_path):
        return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_mode=info.st_mode,
            st_size=info.st_size, st_mtime_ns=info.st_mtime_ns,
            st_ctime_ns=100 if by_path else info.st_ctime_ns,
            st_birthtime_ns=100, st_file_attributes=getattr(info, "st_file_attributes", 0))
    with patch.object(module, "sys", SimpleNamespace(platform="win32")), \
         patch.object(io, "_WINDOWS_STAT", True), \
         patch.object(Path, "lstat", lambda path: adapt(original_lstat(path), by_path=True)), \
         patch.object(io.os, "fstat", lambda descriptor: adapt(original_fstat(descriptor), by_path=False)):
        yield


class ResolverStatTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdd-resolver-stat-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.cache = self.root / "cache"
        (self.cache / "objects").mkdir(parents=True)
        (self.cache / "receipts").mkdir()

    def prepared(self, content=b"first-halfsecond-half", *, split=True, schema="evidence-bytes-v1"):
        ref = {"version": 1, "artifact_id": "stat-fixture", "sha256": digest(content), "size": len(content),
            "kind": "diagnostic", "schema": schema, "provenance": {"run_id": "run-a", "unit_id": "unit-a"},
            "bindings": {}, "retention": {"sealed_at": "2026-10-01T00:00:00Z", "class": "diagnostic"}}
        chunks = [content[:10], content[10:]] if split else [content]
        segments, proofs, offset = [], [], 0
        for index, chunk in enumerate(chunks):
            segment = {"object_id": "stat-pack-" + str(index), "pack_sha256": str(index + 1) * 64,
                "pack_size": 1000, "member": "pieces/" + str(index), "offset": offset,
                "length": len(chunk), "sha256": digest(chunk)}
            segments.append(segment)
            proofs.append({"object_id": segment["object_id"], "sha256": segment["pack_sha256"], "size": 1000,
                "members": [{"artifact_id": ref["artifact_id"], "member": segment["member"],
                             "sha256": segment["sha256"], "size": len(chunk)}]})
            offset += len(chunk)
        ref["locator"] = {"provider": "local", "store_id": "stat-store", **({"segments": segments} if split else segments[0])}
        original = self.cache / "objects" / ref["sha256"]
        original.write_bytes(content)
        receipt = self.cache / "receipts" / (ref["artifact_id"] + ".json")
        receipt.write_text(json.dumps({**ref, "verified_archive": proofs}), encoding="utf-8")
        return ref, original, receipt

    def rewrite_preserving_size_and_mtime(self, path, content):
        before = path.stat()
        self.assertEqual(len(content), before.st_size)
        time.sleep(0.02)
        with path.open("wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = path.stat()
        self.assertEqual(after.st_size, before.st_size)
        self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)

    def test_native_split_resolution_is_read_only_and_reuses_byte_reads(self):
        ref, original, _ = self.prepared()
        before = {path: path.read_bytes() for path in self.cache.rglob("*") if path.is_file()}
        resolver = EvidenceResolver(self.cache)
        with patch.object(module, "hash_file", wraps=module.hash_file) as hashing, \
             patch.object(module, "read_json", wraps=module.read_json) as reading:
            self.assertEqual(resolver.resolve(ref), original)
            self.assertEqual(resolver.resolve(ref), original)
            self.assertEqual(hashing.call_count, 1)
            self.assertEqual(reading.call_count, 1)
            self.assertEqual(len(resolver.segment_hashes), 1)
        self.assertEqual(before, {path: path.read_bytes() for path in self.cache.rglob("*") if path.is_file()})

    def test_split_resolution_accepts_synthetic_windows_path_fd_ctime_difference(self):
        ref, original, _ = self.prepared()
        with windows_stat_clocks():
            self.assertEqual(original.lstat().st_ctime_ns, 100)
            fingerprint = module._regular(original)
            self.assertNotEqual(fingerprint[4], 100)
            self.assertEqual(EvidenceResolver(self.cache).resolve(ref), original)

    def test_native_same_size_restored_mtime_invalidates_original_hash_and_split_memo(self):
        ref, original, _ = self.prepared()
        resolver = EvidenceResolver(self.cache)
        resolver.resolve(ref)
        self.rewrite_preserving_size_and_mtime(original, b"X" * ref["size"])
        with self.assertRaisesRegex(ValueError, "changed during validation"):
            resolver.resolve(ref)

    def test_synthetic_windows_metadata_change_invalidates_memo_with_restored_mtime(self):
        ref, original, _ = self.prepared()
        with windows_stat_clocks():
            resolver = EvidenceResolver(self.cache)
            resolver.resolve(ref)
            original_bytes = original.read_bytes()
            before = original.stat()
            self.rewrite_preserving_size_and_mtime(original, b"X" * len(original_bytes))
            self.assertEqual(original.lstat().st_ctime_ns, 100)
            self.assertEqual(original.stat().st_mtime_ns, before.st_mtime_ns)
            with self.assertRaisesRegex(ValueError, "changed during validation"):
                resolver.resolve(ref)

    def test_native_equal_length_receipt_edit_invalidates_cached_json(self):
        ref, _, receipt = self.prepared()
        resolver = EvidenceResolver(self.cache)
        resolver.resolve(ref)
        content = receipt.read_bytes()
        changed = content.replace(b"unit-a", b"unit-b")
        self.assertNotEqual(content, changed)
        self.rewrite_preserving_size_and_mtime(receipt, changed)
        with self.assertRaisesRegex(ValueError, "changed during validation"):
            resolver.resolve(ref)

    def test_native_equal_length_payload_edit_invalidates_cached_json(self):
        content = b'{"result":"before"}'
        ref, original, _ = self.prepared(content, split=False, schema="evidence-json-v1")
        resolver = EvidenceResolver(self.cache)
        with patch.object(module, "read_json", wraps=module.read_json) as reading:
            self.assertEqual(resolver.json(ref), {"result": "before"})
            self.assertEqual(resolver.json(ref), {"result": "before"})
            self.assertEqual(reading.call_count, 2)  # One receipt and one payload.
        self.rewrite_preserving_size_and_mtime(original, b'{"result":"after!"}')
        with self.assertRaisesRegex(ValueError, "changed during validation"):
            resolver.json(ref)


if __name__ == "__main__":
    unittest.main()
