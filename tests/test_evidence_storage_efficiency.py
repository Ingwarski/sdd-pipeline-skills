"""Generic transfer and encoding regressions using isolated synthetic stores."""
import hashlib
import json
import random
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import test_evidence_manager as manager_fixtures
from evidence.accounting import Accounting, BudgetExceeded
from evidence.archive import build_pack, verify_pack, encoded_pack_bound
from evidence.io import EvidenceError, hash_file
from evidence.policy import append_policy_transition
from evidence.resolver import EvidenceResolver


class ReadbackReuseTests(unittest.TestCase):
    setUp = manager_fixtures.EvidenceManagerTests.setUp
    file = manager_fixtures.EvidenceManagerTests.file
    spec = manager_fixtures.EvidenceManagerTests.spec

    def payload_gets(self):
        return sum("/packs/" in key for key in self.transport.gets)

    def assert_settled(self):
        self.assertEqual([], list(self.manager.staging.iterdir()))
        with Accounting(self.manager.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            totals = ledger.snapshot()["totals"]
            self.assertEqual(0, totals["pending_working_bytes"])
        self.assertFalse(hasattr(self.manager, "_archive_readbacks"))

    def test_independent_readback_populates_complete_receipts_once(self):
        paths = [self.file(str(index) + ".json", json.dumps({"assertions": [index] * 2000}).encode())
                 for index in range(3)]
        refs = self.manager.archive(self.spec(*paths))
        self.assertEqual(1, self.payload_gets())
        resolver = EvidenceResolver(self.manager.cache)
        for ref, path in zip(refs, paths):
            self.assertEqual(path.read_bytes(), resolver.resolve(ref).read_bytes())
            receipt = json.loads((self.manager.cache / "receipts" / (ref["artifact_id"] + ".json")).read_text())
            self.assertEqual(ref["bindings"], receipt["bindings"])
            self.assertEqual(ref["provenance"], receipt["provenance"])
            self.assertEqual(1, len(receipt["verified_archive"][0]["members"]))
        self.assertEqual(sum(path.stat().st_size for path in paths), self.manager.status()["gross_generated_bytes"])
        self.assert_settled()

    def test_deletion_still_performs_a_separate_durable_readback(self):
        path = self.file("result.json", b'{"assertion":"passed"}\n' * 1000)
        ref = self.manager.archive(self.spec(path), remove_local=True)[0]
        self.assertEqual(2, self.payload_gets())
        self.assertFalse(path.exists())
        self.assertTrue(EvidenceResolver(self.manager.cache).resolve(ref).is_file())
        self.assert_settled()

    def test_mutated_retained_readback_cannot_create_a_cache_receipt(self):
        path = self.file("result.txt", b"synthetic observation\n" * 1000)
        publish = self.manager._publish
        def corrupt_after_publication(*args, **kwargs):
            result = publish(*args, **kwargs)
            staged = next(iter(self.manager._archive_readbacks.values()))["path"]
            with staged.open("r+b") as stream:
                stream.write(b"!")
            return result
        with patch.object(self.manager, "_publish", side_effect=corrupt_after_publication):
            with self.assertRaises(EvidenceError):
                self.manager.archive(self.spec(path))
        self.assertEqual([], list((self.manager.cache / "receipts").iterdir()))
        self.assertTrue(path.exists())
        self.assert_settled()

    def test_remote_identity_is_fresh_after_publication(self):
        path = self.file("result.txt", b"synthetic observation\n" * 1000)
        publish, stat = self.manager._publish, self.transport.stat
        published = False
        def remember_publication(*args, **kwargs):
            nonlocal published
            result = publish(*args, **kwargs)
            published = True
            return result
        def changed_identity(locator):
            result = stat(locator)
            key = locator["key"] if isinstance(locator, dict) else locator
            if published and "/packs/" in key:
                return {**result, "size": result["size"] + 1}
            return result
        with patch.object(self.manager, "_publish", side_effect=remember_publication), \
                patch.object(self.transport, "stat", side_effect=changed_identity):
            with self.assertRaisesRegex(EvidenceError, "identity changed"):
                self.manager.archive(self.spec(path))
        self.assertTrue(path.exists())
        self.assert_settled()

    def test_promotion_capacity_shortfall_falls_back_to_normal_preparation(self):
        path = self.file("result.txt", b"synthetic observation\n" * 1000)
        retain = self.manager._retain_readback
        def no_promotion_headroom(*args, **kwargs):
            with patch.object(self.manager, "_capacity", side_effect=EvidenceError("combined local working-space allowance exhausted")):
                return retain(*args, **kwargs)
        with patch.object(self.manager, "_retain_readback", side_effect=no_promotion_headroom):
            ref = self.manager.archive(self.spec(path))[0]
        self.assertEqual(2, self.payload_gets())
        self.assertEqual(path.read_bytes(), EvidenceResolver(self.manager.cache).resolve(ref).read_bytes())
        self.assert_settled()

    def test_unpublished_readback_is_discarded_and_resume_retrieves_durable_bytes(self):
        path = self.file("result.txt", b"synthetic observation\n" * 1000)
        specification = self.spec(path)
        self.transport.interrupt_before_index = True
        with self.assertRaises(EvidenceError):
            self.manager.archive(specification)
        self.assertEqual(1, self.payload_gets())
        self.assertFalse((self.manager.cache / "receipts").exists())
        self.assert_settled()
        self.transport.interrupt_before_index = False
        ref = self.manager.archive(specification)[0]
        self.assertEqual(2, self.payload_gets())
        self.assertEqual(1, sum("/packs/" in key for key in self.transport.puts))
        self.assertEqual(path.read_bytes(), EvidenceResolver(self.manager.cache).resolve(ref).read_bytes())
        self.assert_settled()

    def test_later_pack_settlement_can_release_earlier_optional_readbacks(self):
        part_size = 512 * 1024
        path = self.file("capture.png", b"".join(bytes([index]) * part_size for index in range(8)))
        self.manager.limits.update(archive_pack_target_bytes=part_size,
                                   local_stop_bytes=13 * 1024 * 1024, cache_stop_bytes=5 * 1024 * 1024)
        discard = self.manager._discard_readbacks
        releases = []
        def observe_release(**kwargs):
            count = len(getattr(self.manager, "_archive_readbacks", {}))
            result = discard(**kwargs)
            if result:
                releases.append(count)
            return result
        with patch.object(self.manager, "_discard_readbacks", side_effect=observe_release):
            ref = self.manager.archive(self.spec(path))[0]
        self.assertTrue(releases, "later packing must release optional earlier readbacks")
        self.assertGreater(self.payload_gets(), 8)
        self.assertEqual(path.read_bytes(), EvidenceResolver(self.manager.cache).resolve(ref).read_bytes())
        self.assert_settled()

    def test_split_original_releases_readbacks_when_assembly_needs_the_space(self):
        part_size = 512 * 1024
        path = self.file("capture.png", b"".join(bytes([index]) * part_size for index in range(16)))
        self.manager.limits.update(archive_pack_target_bytes=part_size,
                                   local_stop_bytes=24 * 1024 * 1024, cache_stop_bytes=9 * 1024 * 1024)
        discard = self.manager._discard_readbacks
        preparation_releases = []
        def observe_release(**kwargs):
            count = len(getattr(self.manager, "_archive_readbacks", {}))
            result = discard(**kwargs)
            if result and kwargs.get("preparation"):
                preparation_releases.append(count)
            return result
        with patch.object(self.manager, "_discard_readbacks", side_effect=observe_release):
            ref = self.manager.archive(self.spec(path))[0]
        self.assertTrue(preparation_releases, "split assembly must release optional earlier readbacks")
        self.assertGreater(self.payload_gets(), 16)
        self.assertEqual(path.read_bytes(), EvidenceResolver(self.manager.cache).resolve(ref).read_bytes())
        self.assert_settled()

    def test_preparation_reservation_failure_recalculates_after_releasing_readbacks(self):
        path = self.file("result.txt", b"synthetic observation\n" * 1000)
        reserve = Accounting.reserve_working
        blocked = []
        def reservation_pressure(ledger, amount, **kwargs):
            if (getattr(self.manager, "_readback_preparation", False)
                    and getattr(self.manager, "_archive_readbacks", {})):
                blocked.append(amount)
                raise BudgetExceeded(["combined local working reservation exceeds allowance"])
            return reserve(ledger, amount, **kwargs)
        with patch.object(Accounting, "reserve_working", new=reservation_pressure):
            ref = self.manager.archive(self.spec(path))[0]
        self.assertEqual(1, len(blocked))
        self.assertEqual(2, self.payload_gets())
        self.assertEqual(path.read_bytes(), EvidenceResolver(self.manager.cache).resolve(ref).read_bytes())
        self.assert_settled()

    def test_legacy_orphan_charge_gets_a_separate_monotonic_hold(self):
        path = self.file("result.txt", b"synthetic observation\n" * 1000)
        specification = self.spec(path)
        self.transport.interrupt_before_index = True
        with self.assertRaises(EvidenceError):
            self.manager.archive(specification)
        catalog = self.manager._catalog()
        ident, metadata = next(iter(catalog["unreconciled_packs"].items()))
        identity = "unreconciled-pack:" + ident
        with Accounting(self.manager.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            # This is the exact encoded-byte row written before compression.
            ledger.record_object(identity, metadata["size"], physical_count=1)
        for maximum, expected in ((2 * 1024 * 1024, 2 * 1024 * 1024),
                                  (4 * 1024 * 1024, 4 * 1024 * 1024),
                                  (3 * 1024 * 1024, 4 * 1024 * 1024)):
            self.manager.limits["archive_pack_stop_bytes"] = maximum
            status = self.manager.status()
            self.assertEqual(expected, status["retained_allowance_bytes"])
            self.assertEqual(1, status["physical_objects"])
            with Accounting(self.manager.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
                row = ledger.connection.execute("SELECT bytes,physical_count FROM objects WHERE identity=?", (identity,)).fetchone()
                self.assertEqual((metadata["size"], 1), tuple(row))
        self.transport.interrupt_before_index = False
        self.manager.archive(specification)
        status = self.manager.status()
        self.assertEqual(path.stat().st_size, status["retained_allowance_bytes"])
        self.assertEqual(1, status["physical_objects"])
        self.assert_settled()

    def test_cold_orphan_hold_preserves_larger_historical_policy_bound(self):
        path = self.file("result.txt", b"synthetic observation\n" * 1000)
        self.transport.interrupt_before_index = True
        with self.assertRaises(EvidenceError):
            self.manager.archive(self.spec(path))
        catalog = self.manager._catalog()
        previous = {**self.policy, "limits": {**self.policy["limits"], "archive_pack_stop_bytes": 4 * 1024 * 1024}}
        policy = append_policy_transition(json.dumps(previous).encode(), self.policy)
        self.manager.policy, self.manager.limits = policy, policy["limits"]
        with Accounting(self.base / "cold-accounting.sqlite", policy["project_id"], policy) as ledger:
            self.manager._reconcile_ledger(catalog, ledger)
            totals = ledger.snapshot()["totals"]
            self.assertEqual(4 * 1024 * 1024, totals["retained_unique_bytes"])
            self.assertEqual(1, totals["retained_physical_objects"])


class SelectiveZipTests(unittest.TestCase):
    def test_utf8_sample_boundaries_compress_without_accepting_invalid_text(self):
        with tempfile.TemporaryDirectory(prefix="sdd-utf8-sample-") as temp:
            root = Path(temp).resolve()
            payloads = {
                "two-byte.txt": (b"a" + "Ж".encode() * 40000, zipfile.ZIP_DEFLATED),
                "three-byte.txt": ("界".encode() * 30000, zipfile.ZIP_DEFLATED),
                "four-byte.txt": (b"a" + "🙂".encode() * 20000, zipfile.ZIP_DEFLATED),
                "invalid-middle.txt": (b"a" * 1024 + b"\xff" + b"a" * 70000, zipfile.ZIP_STORED),
                "incomplete-file.txt": (b"a" * 2048 + b"\xe2\x82", zipfile.ZIP_STORED),
            }
            items = []
            for name, (data, _) in payloads.items():
                source = root / name
                source.write_bytes(data)
                items.append({"path": source, "sha256": hashlib.sha256(data).hexdigest(),
                              "size": len(data), "original_path": name})
            total = sum(item["size"] for item in items)
            pack = build_pack(items, root / "pack.zip", total, len(items))
            with zipfile.ZipFile(root / "pack.zip") as archive:
                for item in items:
                    with self.subTest(name=item["original_path"]):
                        info = archive.getinfo("objects/" + item["sha256"])
                        self.assertEqual(payloads[item["original_path"]][1], info.compress_type)
            verify_pack(root / "pack.zip", pack["sha256"], pack["size"], pack["members"],
                        destination=root / "extracted", max_bytes=total)
            for item in items:
                self.assertEqual((item["sha256"], item["size"]), hash_file(root / "extracted" / item["sha256"]))

    def test_fixed_huffman_expansion_fits_before_write_reservation(self):
        # RFC 1951 fixed Huffman literals can use nine bits per input byte.
        # Supply a real decodable stream with that expansion on every runtime,
        # even when its installed compressor normally chooses smaller blocks.
        class FixedLiterals:
            def __init__(self):
                self.bits, self.count = 3, 3  # BFINAL=1, BTYPE=01.
                self.codes = []
                for value in range(256):
                    code, width = (48 + value, 8) if value < 144 else (256 + value, 9)
                    self.codes.append((int(format(code, "0%db" % width)[::-1], 2), width))

            def compress(self, data):
                output = bytearray()
                for value in data:
                    code, width = self.codes[value]
                    self.bits |= code << self.count
                    self.count += width
                    while self.count >= 8:
                        output.append(self.bits & 255)
                        self.bits >>= 8
                        self.count -= 8
                return bytes(output)

            def flush(self):
                self.count += 7  # End-of-block symbol 256 is seven zero bits.
                output = bytearray()
                while self.count > 0:
                    output.append(self.bits & 255)
                    self.bits >>= 8
                    self.count -= 8
                return bytes(output)

        with tempfile.TemporaryDirectory(prefix="sdd-fixed-deflate-") as temp:
            root = Path(temp).resolve()
            data = b"a" * (64 * 1024) + b"\xff" * (1024 * 1024)
            source = root / "result.log"
            source.write_bytes(data)
            item = {"path": source, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            reserved = encoded_pack_bound([len(data)])
            with patch.object(zipfile, "_get_compressor", return_value=FixedLiterals()):
                pack = build_pack([item], root / "pack.zip", len(data), 1)
            verified = verify_pack(root / "pack.zip", pack["sha256"], pack["size"], pack["members"],
                                   max_bytes=len(data))
            self.assertEqual(len(data), verified["original_bytes"])
            classic_bound = len(data) + (len(data) >> 12) + (len(data) >> 14) + (len(data) >> 25) + 13 + 2048 + 65536
            self.assertGreater(pack["size"], classic_bound, "fixture must expose the classic-only bound")
            self.assertLessEqual(pack["size"], reserved)

    def test_unrepresentative_sample_stays_within_encoded_reservation(self):
        with tempfile.TemporaryDirectory(prefix="sdd-zip-bound-") as temp:
            root = Path(temp).resolve()
            data = b"compressible observation\n" * 4096 + random.Random(7).randbytes(4 * 1024 * 1024)
            source = root / "result.log"
            source.write_bytes(data)
            item = {"path": source, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            pack = build_pack([item], root / "pack.zip", len(data), 1)
            with zipfile.ZipFile(root / "pack.zip") as archive:
                self.assertEqual(zipfile.ZIP_DEFLATED, archive.infolist()[0].compress_type)
            self.assertLessEqual(pack["size"], encoded_pack_bound([len(data)]))
            verified = verify_pack(root / "pack.zip", pack["sha256"], pack["size"], pack["members"], max_bytes=len(data))
            self.assertEqual(len(data), verified["original_bytes"])
        # Check custom large-pack arithmetic without allocating a giant fixture.
        large = 2 * 1024 * 1024 * 1024
        self.assertGreater(encoded_pack_bound([large]), large + 2048 + 65536 + 600000)

    def test_text_compresses_media_and_binary_remain_stored_with_original_hashes(self):
        with tempfile.TemporaryDirectory(prefix="sdd-zip-encoding-") as temp:
            root = Path(temp).resolve()
            payloads = {"result.json": json.dumps({"assertions": ["passed"] * 10000}).encode(),
                        "capture.png": b"synthetic media bytes" * 10000,
                        "binary.bin": bytes(range(256)) * 1000}
            items = []
            for name, data in payloads.items():
                source = root / name
                source.write_bytes(data)
                items.append({"path": source, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                              "original_path": name})
            total = sum(item["size"] for item in items)
            pack = build_pack(items, root / "pack.zip", total, len(items))
            with zipfile.ZipFile(root / "pack.zip") as archive:
                for item in items:
                    info = archive.getinfo("objects/" + item["sha256"])
                    expected = zipfile.ZIP_DEFLATED if item["original_path"].endswith(".json") else zipfile.ZIP_STORED
                    self.assertEqual(expected, info.compress_type)
                    if expected == zipfile.ZIP_DEFLATED:
                        self.assertLess(info.compress_size, info.file_size // 10)
            verified = verify_pack(root / "pack.zip", pack["sha256"], pack["size"], pack["members"],
                                   destination=root / "extracted", max_bytes=total)
            self.assertEqual(total, verified["original_bytes"])
            for item in items:
                self.assertEqual((item["sha256"], item["size"]), hash_file(root / "extracted" / item["sha256"]))
            with self.assertRaises(EvidenceError):
                build_pack(items, root / "too-small.zip", total - 1, len(items))


if __name__ == "__main__":
    unittest.main()
