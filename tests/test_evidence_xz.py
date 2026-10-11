"""Bounded original-byte TAR/XZ adoption and hostile container regressions."""
from copy import deepcopy
import hashlib
import io
import lzma
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/to-sdd-pipeline/scripts"))
from evidence.archive import CHUNK, XZ_DECODER_MEMORY, _XZDecompression, verify_pack
from evidence.io import EvidenceError, hash_file
from evidence.manager import Manager
from evidence.policy import load_defaults
from evidence.resolver import EvidenceResolver
from evidence.transports import LocalTransport


class RecordingTransport(LocalTransport):
    def __init__(self, root):
        super().__init__(root)
        self.puts = []

    def put(self, key, source_path):
        result = super().put(key, source_path)
        self.puts.append(key)
        return result


class XZArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-xz-archive-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.archive = self.base / "original.tar.xz"
        self.payload = b"Original binary evidence\0\xff\xfe\r\n" * 31

    def tar_bytes(self, names=("evidence/original.bin",), *, payload=None, special=None, pax=None):
        payload = self.payload if payload is None else payload
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name in names:
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                if special is not None:
                    member.type, member.linkname, member.size = special, "somewhere", 0
                if pax:
                    member.pax_headers = pax
                archive.addfile(member, io.BytesIO(payload) if member.size else None)
        return buffer.getvalue()

    def write_xz(self, data=None, **kwargs):
        data = self.tar_bytes() if data is None else data
        self.archive.write_bytes(lzma.compress(data, **kwargs))
        return self.archive

    def verify(self, **kwargs):
        digest, size = hash_file(self.archive)
        return verify_pack(self.archive, digest, size, **kwargs)

    def test_lossless_members_verify_and_extract_with_original_pack_identity(self):
        for check in (lzma.CHECK_CRC32, lzma.CHECK_CRC64, lzma.CHECK_SHA256):
            if not lzma.is_check_supported(check):
                continue
            with self.subTest(check=check):
                self.write_xz(self.tar_bytes(("evidence/original.bin", "unicode/caf\u00e9.bin")), check=check)
                identity = hash_file(self.archive)
                expected = [{"member": name, "sha256": hashlib.sha256(self.payload).hexdigest(), "size": len(self.payload)}
                            for name in ("evidence/original.bin", "unicode/caf\u00e9.bin")]
                result = self.verify(expected_members=expected, destination=self.base / ("extracted-" + str(check)))
                self.assertEqual(expected, result["members"])
                self.assertEqual(identity, (result["sha256"], result["size"]))
                self.assertEqual(identity, hash_file(self.archive))
                self.assertEqual(self.payload, (self.base / ("extracted-" + str(check)) / expected[0]["sha256"]).read_bytes())

    def test_decoder_memory_bound_is_enforced_and_can_be_raised_explicitly(self):
        self.write_xz(filters=[{"id": lzma.FILTER_LZMA2, "dict_size": 1024 * 1024}])
        with self.assertRaisesRegex(EvidenceError, "memory bound"):
            self.verify(max_decoder_memory_bytes=512 * 1024)
        self.assertEqual(len(self.payload), self.verify(max_decoder_memory_bytes=4 * 1024 * 1024)["original_bytes"])
        for invalid in (0, -1, True, None, "unlimited"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(EvidenceError, "decoder memory bound"):
                self.verify(max_decoder_memory_bytes=invalid)

    def test_incremental_decoder_never_allocates_unbounded_expanded_output(self):
        self.write_xz(self.tar_bytes(payload=b"x" * (CHUNK * 3)))
        original = lzma.LZMADecompressor
        calls = []
        class ObservedDecoder:
            def __init__(self, **kwargs):
                self.decoder = original(**kwargs)
            def __getattr__(self, name):
                return getattr(self.decoder, name)
            def decompress(self, data, *, max_length):
                result = self.decoder.decompress(data, max_length=max_length)
                calls.append((len(data), max_length, len(result)))
                return result
        with patch("evidence.archive.lzma.LZMADecompressor", ObservedDecoder):
            with self.assertRaisesRegex(EvidenceError, "decompression"):
                self.verify(max_bytes=1024, max_metadata_bytes=4096)
        self.assertTrue(calls)
        self.assertTrue(all(encoded <= CHUNK and 0 < bound <= 5121 and output <= bound for encoded, bound, output in calls))

    def test_member_count_metadata_encoded_and_output_limits_still_apply(self):
        self.write_xz(self.tar_bytes(("first", "second")))
        with self.assertRaisesRegex(EvidenceError, "member count"):
            self.verify(max_files=1)
        with self.assertRaisesRegex(EvidenceError, "encoded"):
            self.verify(max_archive_bytes=10)
        with self.assertRaisesRegex(EvidenceError, "decompression"):
            self.verify(max_bytes=1)
        self.write_xz(self.tar_bytes(pax={"comment": "x" * 10000}))
        with self.assertRaisesRegex(EvidenceError, "metadata"):
            self.verify(max_metadata_bytes=1000, max_archive_bytes=10000)

    def test_links_special_files_unsafe_paths_and_duplicate_members_fail(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            self.write_xz(self.tar_bytes(special=kind))
            with self.subTest(kind=kind), self.assertRaises(EvidenceError):
                self.verify()
        for names in (("../outside",), ("/absolute",), ("a\\b",), ("a/./b",), ("same", "same")):
            self.write_xz(self.tar_bytes(names))
            with self.subTest(names=names), self.assertRaises(EvidenceError):
                self.verify()

    def test_expected_hash_size_and_member_closure_remain_mandatory(self):
        self.write_xz()
        member = self.verify()["members"][0]
        for expected in ([], [{**member, "sha256": "0" * 64}], [{**member, "size": 1}], [{**member, "member": "absent"}]):
            with self.subTest(expected=expected), self.assertRaises(EvidenceError):
                self.verify(expected_members=expected)

    def test_truncated_stream_header_payload_index_and_footer_fail(self):
        self.write_xz()
        original = self.archive.read_bytes()
        for length in (6, 12, len(original) // 2, len(original) - 12, len(original) - 1):
            self.archive.write_bytes(original[:length])
            with self.subTest(length=length), self.assertRaises(EvidenceError):
                self.verify()

    def test_corrupt_xz_integrity_failure_discards_only_new_extracted_objects(self):
        self.write_xz()
        original = self.archive.read_bytes()
        for position in (8, 15, len(original) - 16, len(original) - 8):
            corrupt = bytearray(original)
            corrupt[position] ^= 1
            self.archive.write_bytes(corrupt)
            destination = self.base / ("corrupt-" + str(position))
            destination.mkdir()
            preserved = destination / "unrelated"
            preserved.write_bytes(b"keep")
            with self.subTest(position=position), self.assertRaises(EvidenceError):
                self.verify(destination=destination)
            self.assertEqual([preserved], list(destination.iterdir()))
            self.assertEqual(b"keep", preserved.read_bytes())

    def test_valid_stream_padding_is_accepted_across_input_chunk_boundaries(self):
        self.write_xz()
        original = self.archive.read_bytes()
        for padding_size in (0, 4, 12, CHUNK + 4):
            self.archive.write_bytes(original + b"\0" * padding_size)
            with self.subTest(padding_size=padding_size):
                self.assertEqual(len(self.payload), self.verify()["original_bytes"])

    def test_concatenated_xz_nonzero_trailing_and_misaligned_padding_fail(self):
        self.write_xz()
        original = self.archive.read_bytes()
        for suffix in (b"\0", b"\0" * 6, b"trailing", original, b"\0" * 4 + original,
                       b"\0" * CHUNK + b"hidden"):
            self.archive.write_bytes(original + suffix)
            with self.subTest(suffix_size=len(suffix)), self.assertRaisesRegex(EvidenceError, "padding|trailing|concatenated"):
                self.verify()

    def test_decoder_is_drained_past_tar_eof_under_the_same_expansion_bound(self):
        self.write_xz(self.tar_bytes() + b"\0" * 100000)
        with self.assertRaisesRegex(EvidenceError, "decompression"):
            self.verify(max_bytes=10000, max_metadata_bytes=20000)

    def test_appending_encoded_padding_cannot_extend_verification_past_the_input_bound(self):
        encoded = lzma.compress(self.tar_bytes())
        stream = io.BytesIO(encoded + b"\0" * (CHUNK * 2))
        decoder = _XZDecompression(stream, XZ_DECODER_MEMORY, len(encoded))
        with self.assertRaisesRegex(EvidenceError, "encoded archive grew"):
            while decoder.read(1024):
                pass
        self.assertEqual(len(encoded) + 1, stream.tell())

    def test_second_tar_or_garbage_after_tar_end_is_rejected_including_read_ahead(self):
        original = self.tar_bytes()
        # A tiny tail is already in TarFile's read-ahead buffer when iteration
        # stops; both that tail and later decoder output must be checked.
        for expanded in (original[:2560] + b"hidden", original + self.tar_bytes(("hidden",)), original + b"garbage"):
            self.write_xz(expanded)
            with self.subTest(size=len(expanded)), self.assertRaisesRegex(EvidenceError, "TAR end-of-archive"):
                self.verify()

    def test_truncated_or_invalid_tar_after_a_valid_first_member_fails(self):
        original = self.tar_bytes(payload=b"x")
        for expanded in (original[:1024], original[:1024] + b"x" * 512,
                         original[:1536], original[:1024] + b"\0" * 512 + b"x" * 512):
            self.write_xz(expanded)
            with self.subTest(size=len(expanded)), self.assertRaisesRegex(EvidenceError, "TAR"):
                self.verify()

    def test_original_xz_adopts_without_payload_reupload_and_restores_cold(self):
        self.write_xz()
        original_bytes = self.archive.read_bytes()
        verified = self.verify()
        transport = RecordingTransport(self.base / "durable")
        locator = transport.put("historical/original.tar.xz", self.archive)
        policy = load_defaults()
        policy.update(project_id="11111111-1111-4111-8111-111111111111",
                      store_id="22222222-2222-4222-8222-222222222222", provider="local")
        policy["limits"]["free_space_reserve_bytes"] = 0
        member = verified["members"][0]
        record = {"artifact_id": "original-xz-evidence", "sha256": member["sha256"], "size": member["size"],
                  "kind": "recovery-attachment", "schema": "archive-attachment-v1", "original_path": member["member"],
                  "provenance": {"run_id": "original-run", "unit_id": "original-unit", "executed_at": "2026-01-01T12:00:00Z"},
                  "bindings": {"original_plan_hash": "c" * 64}, "verified_at": "2026-01-02T08:30:00Z",
                  "retention": {"sealed_at": "2026-01-01T12:00:00Z", "class": "recovery"},
                  "parts": [{"object": "xz", "member": member["member"], "offset": 0, "length": member["size"]}]}
        mapping = {"version": 1, "objects": {"xz": {**verified, "locator": locator}}, "files": [record]}
        before_mapping = deepcopy(mapping)
        transport.puts.clear()
        refs = Manager(transport, self.base / "warm-machine", policy).import_archive(mapping)
        self.assertEqual(before_mapping, mapping)
        self.assertTrue(transport.puts)
        self.assertTrue(all(key.endswith(".json") for key in transport.puts))
        self.assertEqual(original_bytes, (self.base / "durable/historical/original.tar.xz").read_bytes())
        self.archive.unlink()
        cold = Manager(RecordingTransport(self.base / "durable"), self.base / "cold-machine", policy)
        ref = cold._catalog()["refs"][refs[0]["artifact_id"]]
        self.assertEqual(record["provenance"], ref["provenance"])
        self.assertEqual(record["verified_at"], ref["historical_verified_at"])
        self.assertEqual(locator["object_id"], ref["locator"]["object_id"])
        self.assertEqual(self.payload, EvidenceResolver(cold.prepare([ref])).resolve(ref).read_bytes())
        restored = cold.restore([ref], self.base / "restored")
        self.assertEqual(self.payload, Path(restored[0]).read_bytes())
        self.assertEqual([], cold.transport.puts)


if __name__ == "__main__":
    unittest.main()
