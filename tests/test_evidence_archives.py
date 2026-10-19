"""Synthetic archives exercise original bytes, changing inputs and format bounds."""
import gzip
import hashlib
import io
import os
from pathlib import Path
import stat
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"))
from evidence.archive import build_pack, capture, verify_pack
from evidence.io import EvidenceError, hash_file


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-safe-archives-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        self.source.write_bytes(b"synthetic original bytes\0" * 100)

    def verified(self, path, **kwargs):
        digest, size = hash_file(path)
        return verify_pack(path, digest, size, **kwargs)

    def zip(self, names=("file",), *, payload=b"original", compression=zipfile.ZIP_STORED):
        target = self.root / "archive.zip"
        with zipfile.ZipFile(target, "w", compression=compression) as archive:
            for name in names:
                info = zipfile.ZipInfo(name)
                # Preserve hostile raw member spelling on every host; Windows
                # ZipInfo otherwise rewrites backslashes before writing them.
                info.filename = name
                archive.writestr(info, payload, compress_type=compression)
        return target

    def tar(self, names=("file",), *, payload=b"original", mode="w", special=None, pax=None):
        target = self.root / "archive.tar"
        with tarfile.open(target, mode, format=tarfile.PAX_FORMAT) as archive:
            for name in names:
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                if special is not None:
                    info.type = special
                    info.linkname = "elsewhere"
                    info.size = 0
                if pax:
                    info.pax_headers = pax
                archive.addfile(info, io.BytesIO(payload) if info.size else None)
        return target

    def test_stable_capture_and_immutable_output(self):
        destination = self.root / "captured"
        result = capture(self.source, destination, self.source.stat().st_size)
        self.assertEqual((result["sha256"], result["size"]), hash_file(destination))
        with self.assertRaises(FileExistsError):
            capture(self.source, destination, result["size"])
        self.assertEqual(hash_file(self.source), hash_file(destination))

    def test_capture_bound_does_not_delete_existing_destination(self):
        target = self.root / "existing"
        target.write_bytes(b"keep")
        with self.assertRaises(EvidenceError):
            capture(self.source, target, 1)
        self.assertEqual(b"keep", target.read_bytes())

    def test_capture_rejects_linked_source_and_destination_parent(self):
        link = self.root / "source-link"
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest("host does not permit symlinks")
        with self.assertRaises(EvidenceError):
            capture(link, self.root / "output", 10000)
        linked = self.root / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(EvidenceError):
            capture(self.source, linked / "output", 10000)
        self.assertFalse((self.root / "output").exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO is a POSIX fixture")
    def test_capture_never_opens_fifo_as_regular_source(self):
        target = self.root / "fifo"
        os.mkfifo(target)
        with self.assertRaises(EvidenceError):
            capture(target, self.root / "output", 100)

    def test_capture_detects_mutation_and_removes_its_partial_output(self):
        import evidence.archive as module
        original = module._verify_stable
        def mutate(path, fd, before):
            self.source.write_bytes(b"changed")
            return original(path, fd, before)
        with patch.object(module, "_verify_stable", mutate):
            with self.assertRaises(EvidenceError):
                capture(self.source, self.root / "captured", 10000)
        self.assertFalse((self.root / "captured").exists())

    def test_pack_deduplicates_content_and_preserves_member_identity(self):
        digest, size = hash_file(self.source)
        item = {"path": self.source, "sha256": digest, "size": size}
        target = self.root / "pack.zip"
        pack = build_pack([item, dict(item)], target, size, 1)
        self.assertEqual(1, len(pack["members"]))
        destination = self.root / "extracted"
        result = verify_pack(target, pack["sha256"], pack["size"], pack["members"], destination=destination, max_bytes=size)
        self.assertEqual(size, result["original_bytes"])
        self.assertEqual(self.source.read_bytes(), (destination / digest).read_bytes())

    def test_pack_detects_changed_expected_bytes_and_removes_partial_archive(self):
        target = self.root / "pack.zip"
        with self.assertRaises(EvidenceError):
            build_pack([{"path": self.source, "sha256": "0" * 64, "size": self.source.stat().st_size}], target, 10000, 1)
        self.assertFalse(target.exists())

    def test_pack_existing_output_survives_exclusive_open_failure(self):
        digest, size = hash_file(self.source)
        target = self.root / "pack.zip"
        target.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            build_pack([{"path": self.source, "sha256": digest, "size": size}], target, 10000, 1)
        self.assertEqual(b"preserve", target.read_bytes())

    def test_zip_preflight_checks_actual_count_before_zipfile_parsing(self):
        target = self.zip(("first", "second"))
        data = bytearray(target.read_bytes())
        end = data.rfind(b"PK\x05\x06")
        struct.pack_into("<HH", data, end + 8, 1, 1)
        target.write_bytes(data)
        with patch("evidence.archive.zipfile.ZipFile", side_effect=AssertionError("must preflight")):
            with self.assertRaises(EvidenceError):
                self.verified(target, max_files=1)

    def test_zip_metadata_count_and_encoded_size_have_separate_bounds(self):
        target = self.zip(("first", "second"))
        with self.assertRaises(EvidenceError):
            self.verified(target, max_files=1)
        with self.assertRaises(EvidenceError):
            self.verified(target, max_metadata_bytes=10)
        with self.assertRaises(EvidenceError):
            self.verified(target, max_archive_bytes=10)

    def test_zip_duplicate_and_unsafe_member_paths_fail(self):
        for names in (("file", "file"), ("../escape",), ("/absolute",), ("a\\b",), ("a/./b",)):
            target = self.zip(names)
            with self.subTest(names=names), self.assertRaises(EvidenceError):
                self.verified(target)

    def test_zip_symlink_member_fails(self):
        target = self.root / "linked.zip"
        with zipfile.ZipFile(target, "w") as archive:
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "elsewhere")
        with self.assertRaises(EvidenceError):
            self.verified(target)

    def test_zip_decompression_is_bounded(self):
        target = self.zip(payload=b"0" * 100000, compression=zipfile.ZIP_DEFLATED)
        with self.assertRaises(EvidenceError):
            self.verified(target, max_bytes=1000)

    def test_member_expected_hash_size_and_closure_fail(self):
        target = self.zip()
        for expected in ([{"member":"file", "sha256":"0" * 64, "size":8}], []):
            with self.assertRaises(EvidenceError):
                self.verified(target, expected_members=expected)

    def test_failed_archive_removes_only_created_extracted_bytes(self):
        target = self.zip(("first", "second"))
        destination = self.root / "partial"
        destination.mkdir()
        preserved = destination / hashlib.sha256(b"original").hexdigest()
        preserved.write_bytes(b"original")
        with self.assertRaises(EvidenceError):
            self.verified(target, expected_members=[], destination=destination)
        self.assertEqual([preserved], list(destination.iterdir()))
        preserved.unlink()
        with self.assertRaises(EvidenceError):
            self.verified(target, expected_members=[{"member":"first", "sha256":hashlib.sha256(b"original").hexdigest(), "size":8}], destination=destination)
        self.assertEqual([], list(destination.iterdir()))

    def test_tar_gzip_bzip2_original_contents_verify(self):
        for mode in ("w", "w:gz", "w:bz2"):
            target = self.tar(mode=mode)
            result = self.verified(target, destination=self.root / mode.replace(":", "-"))
            self.assertEqual(8, result["original_bytes"])
            self.assertEqual(hashlib.sha256(b"original").hexdigest(), result["members"][0]["sha256"])

    def test_tar_link_special_and_unsafe_member_fail(self):
        for special in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            target = self.tar(special=special)
            with self.assertRaises(EvidenceError):
                self.verified(target)
        target = self.tar(names=("../escape",))
        with self.assertRaises(EvidenceError):
            self.verified(target)

    def test_tar_pax_metadata_bound_fails_before_large_payload_allocation(self):
        target = self.tar(pax={"comment": "x" * 10000}, mode="w:gz")
        with self.assertRaisesRegex(EvidenceError, "metadata"):
            self.verified(target, max_metadata_bytes=1000, max_archive_bytes=100000)

    def test_compressed_tail_cannot_bypass_member_bound(self):
        target = self.tar()
        target.write_bytes(gzip.compress(target.read_bytes() + b"\0" * 100000))
        with self.assertRaisesRegex(EvidenceError, "decompression"):
            self.verified(target, max_bytes=100, max_metadata_bytes=20000)

    def test_extraction_rejects_linked_ancestor(self):
        target = self.zip()
        linked = self.root / "linked"
        try:
            linked.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("host does not permit symlinks")
        with self.assertRaises(EvidenceError):
            self.verified(target, destination=linked / "extracted")
        self.assertFalse((self.root / "extracted").exists())

    def test_xz_archive_verifies_original_bytes_without_repacking(self):
        import lzma
        target = self.tar()
        target.write_bytes(lzma.compress(target.read_bytes()))
        original = target.read_bytes()
        result = self.verified(target)
        self.assertEqual(original, target.read_bytes())
        self.assertEqual(8, result["original_bytes"])
        self.assertEqual(hashlib.sha256(b"original").hexdigest(), result["members"][0]["sha256"])


if __name__ == "__main__":
    unittest.main()
