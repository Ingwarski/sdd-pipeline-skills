"""Raw ZIP names remain unsafe even when a platform normalizes their spelling."""
import binascii
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence.archive import verify_pack
from evidence.io import EvidenceError, hash_file


class RawZipNameTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdd-raw-zip-names-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def raw_zip(self, name, *, extra=b""):
        # Replace equal-length names in both real ZIP headers, avoiding every
        # ZipInfo writer normalization on native Windows and other hosts.
        encoded = name.encode("utf-8")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            info = zipfile.ZipInfo("x" * len(encoded))
            info.extra = extra
            archive.writestr(info, b"synthetic original")
        data = bytearray(stream.getvalue())
        local, central = data.index(b"PK\x03\x04"), data.index(b"PK\x01\x02")
        self.assertEqual(struct.unpack_from("<H", data, local + 26)[0], len(encoded))
        self.assertEqual(struct.unpack_from("<H", data, central + 28)[0], len(encoded))
        data[local + 30:local + 30 + len(encoded)] = encoded
        data[central + 46:central + 46 + len(encoded)] = encoded
        target = self.root / "raw.zip"
        target.write_bytes(data)
        return target

    def verified(self, path, **kwargs):
        digest, size = hash_file(path)
        return verify_pack(path, digest, size, **kwargs)

    def test_native_reader_preserves_backslash_original_and_verifier_rejects_it(self):
        target = self.raw_zip("a\\b")
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(archive.infolist()[0].orig_filename, "a\\b")
        destination = self.root / "extracted"
        with self.assertRaises(EvidenceError):
            self.verified(target, destination=destination)
        self.assertFalse(destination.exists())

    def test_raw_backslash_and_nul_fail_before_zipinfo_can_normalize_names(self):
        for name in ("a\\b", "a\\b/", "a\0b", "directory//"):
            with self.subTest(name=name):
                target = self.raw_zip(name)
                with patch("evidence.archive.zipfile.ZipFile", side_effect=AssertionError("raw preflight must reject")):
                    with self.assertRaises(EvidenceError):
                        self.verified(target)

    def test_raw_unicode_alternative_cannot_hide_backslash_in_extra_field(self):
        name, alternative = "safe", b"a\\b"
        field = struct.pack("<BL", 1, binascii.crc32(name.encode())) + alternative
        target = self.raw_zip(name, extra=struct.pack("<HH", 0x7075, len(field)) + field)
        with patch("evidence.archive.zipfile.ZipFile", side_effect=AssertionError("raw preflight must reject")):
            with self.assertRaises(EvidenceError):
                    self.verified(target)

    def test_portable_unicode_alternative_remains_valid(self):
        name, alternative = "safe", "folder/caf\u00e9"
        field = struct.pack("<BL", 1, binascii.crc32(name.encode())) + alternative.encode("utf-8")
        target = self.raw_zip(name, extra=struct.pack("<HH", 0x7075, len(field)) + field)
        result = self.verified(target)
        # CPython versions differ in whether they adopt this optional Unicode
        # field, but both original and alternative are valid portable names.
        self.assertIn(result["members"][0]["member"], (name, alternative))

    def test_portable_slash_member_and_single_directory_marker_still_verify(self):
        target = self.root / "portable.zip"
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("folder/", b"")
            archive.writestr("folder/member", b"original")
        result = self.verified(target)
        self.assertEqual([item["member"] for item in result["members"]], ["folder/member"])


if __name__ == "__main__":
    unittest.main()
