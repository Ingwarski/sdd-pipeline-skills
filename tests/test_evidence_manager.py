"""Manager lifecycle regressions on synthetic bytes and isolated durable stores."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/to-sdd-pipeline/scripts"))
from evidence.archive import build_pack
from evidence.accounting import Accounting, BudgetExceeded
from evidence.io import EvidenceError, hash_file
from evidence.manager import Manager
from evidence.policy import load_defaults
from evidence.producer import run_producer
from evidence.resolver import EvidenceResolver
from evidence.transports import LocalTransport

SEALED = "2026-01-01T12:00:00Z"
SEALED_TIME = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


class ObservedTransport(LocalTransport):
    """Real local copies with focused injection at transport operation boundaries."""
    def __init__(self, root):
        super().__init__(root)
        self.puts, self.gets, self.deletes = [], [], []
        self.corrupt_packs = False
        self.unavailable = False
        self.fail_deletions = set()
        self.interrupt_before_index = False

    def put(self, key, source_path):
        if self.unavailable:
            raise EvidenceError("synthetic store unavailable")
        if self.interrupt_before_index and "/indexes/" in key:
            raise EvidenceError("synthetic interruption after verified payload transfer")
        result = super().put(key, source_path)
        self.puts.append(key)
        return result

    def get(self, locator, destination_path, max_bytes):
        if self.unavailable:
            raise EvidenceError("synthetic store unavailable")
        result = super().get(locator, destination_path, max_bytes)
        key = locator["key"] if isinstance(locator, dict) else locator
        self.gets.append(key)
        if self.corrupt_packs and key.endswith(".zip"):
            path = Path(destination_path)
            with path.open("r+b") as stream:
                original = stream.read(1)
                stream.seek(0)
                stream.write(bytes([original[0] ^ 1]))
        return result

    def keys(self, prefix=""):
        if self.unavailable:
            raise EvidenceError("synthetic store unavailable")
        return super().keys(prefix)

    def delete(self, locator):
        key = locator["key"] if isinstance(locator, dict) else locator
        if self.unavailable or key in self.fail_deletions:
            raise EvidenceError("synthetic registered-object deletion failure")
        result = super().delete(locator)
        self.deletes.append(key)
        return result


class EvidenceManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-manager-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.capture = self.base / "capture"
        self.capture.mkdir()
        self.home = self.base / "working"
        self.store = self.base / "durable"
        self.policy = {**load_defaults(), "project_id": str(uuid.uuid4()), "store_id": str(uuid.uuid4()), "provider": "local"}
        self.policy["limits"].update(archive_pack_target_bytes=1024 * 1024, archive_pack_stop_bytes=2 * 1024 * 1024,
                                     free_space_reserve_bytes=0)
        self.transport = ObservedTransport(self.store)
        self.manager = Manager(self.transport, self.home, self.policy)
        self.counter = 0

    def file(self, name, data):
        path = self.capture / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def spec(self, *paths, kinds=None, protections=None, dependencies=None, run=None):
        self.counter += 1
        run = run or "synthetic-run-" + str(self.counter)
        return {"version": 1, "files": [{"path": str(path), "original_path": path.relative_to(self.capture).as_posix(),
            "sealed_at": SEALED, "kind": kinds[index] if kinds else "diagnostic", "schema": "evidence-bytes-v1",
            "provenance": {"run_id": run, "unit_id": "U-" + str(self.counter), "check_id": "QA-" + str(index)},
            "bindings": {"source_hashes": {"synthetic-source.txt": "0" * 64}},
            "protections": protections[index] if protections else [],
            **({"dependencies": dependencies[index]} if dependencies and dependencies[index] else {})}
            for index, path in enumerate(paths)]}

    def pack_puts(self):
        return [key for key in self.transport.puts if "/packs/" in key]

    def resolved(self, reference):
        self.manager.prepare([reference])
        return EvidenceResolver(self.manager.cache).resolve(reference).read_bytes()

    def test_many_small_files_share_pack_but_preserve_all_logical_associations(self):
        paths = [self.file("observations/" + str(index) + ".bin", ("Synthetic observation " + str(index)).encode() * 100)
                 for index in range(24)]
        refs = self.manager.archive(self.spec(*paths))
        self.assertEqual(1, len(self.pack_puts()))
        self.assertEqual(2, sum(key.endswith(".zip") for key in self.transport.gets), "one upload readback plus one shared preparation readback")
        for ref in refs:
            receipt = json.loads((self.manager.cache / "receipts" / (ref["artifact_id"] + ".json")).read_text())
            self.assertEqual(1, sum(len(proof["members"]) for proof in receipt["verified_archive"]), "shared catalog metadata must not multiply into every receipt")
        self.assertEqual(24, len({ref["artifact_id"] for ref in refs}))
        self.assertEqual({path.relative_to(self.capture).as_posix() for path in paths}, {ref["original_path"] for ref in refs})
        self.assertEqual(1, len({ref["locator"]["object_id"] for ref in refs}))
        for ref, path in zip(refs, paths):
            self.assertEqual(path.read_bytes(), self.resolved(ref))
        status = self.manager.status()
        self.assertEqual(24, status["original_logical_files"])
        self.assertEqual(sum(path.stat().st_size for path in paths), status["gross_generated_bytes"])
        self.assertEqual(1, status["physical_objects"])

    def test_dedup_preserves_check_paths_and_never_refunds_generation(self):
        data = b"Identical synthetic original.\n" * 300
        first = self.file("QA-1/result.bin", data)
        second = self.file("QA-2/result.bin", data)
        refs = self.manager.archive(self.spec(first, second))
        self.assertEqual(1, len(self.pack_puts()))
        self.assertEqual(2, len({ref["artifact_id"] for ref in refs}))
        self.assertEqual(refs[0]["locator"], refs[1]["locator"])
        third = self.file("retry/result.bin", data)
        later = self.manager.archive(self.spec(third))[0]
        self.assertEqual(1, len(self.pack_puts()))
        self.assertNotEqual(refs[0]["artifact_id"], later["artifact_id"])
        status = self.manager.status()
        self.assertEqual(len(data), status["retained_unique_bytes"])
        self.assertEqual(3 * len(data), status["gross_generated_bytes"])
        self.assertEqual(3, status["original_logical_files"])

    def test_large_original_splits_into_bounded_packs_and_resolves_whole_bytes(self):
        self.policy["limits"].update(archive_pack_target_bytes=64 * 1024, archive_pack_stop_bytes=128 * 1024)
        self.manager = Manager(self.transport, self.home, self.policy)
        data = bytes(range(256)) * 3000 + b"synthetic-tail"
        path = self.file("large-observation.bin", data)
        ref = self.manager.archive(self.spec(path))[0]
        segments = ref["locator"]["segments"]
        self.assertGreater(len(segments), 1)
        self.assertEqual(len(data), sum(part["length"] for part in segments))
        self.assertTrue(all(part["length"] <= 64 * 1024 for part in segments))
        self.assertEqual(list(range(0, len(data), 64 * 1024)), [part["offset"] for part in segments])
        self.assertEqual(data, self.resolved(ref))
        self.assertEqual(hashlib.sha256(data).hexdigest(), ref["sha256"])

    def test_exact_completed_resume_preserves_refs_totals_and_transfers(self):
        path = self.file("result.bin", b"Synthetic resumable bytes.\n" * 100)
        specification = self.spec(path)
        refs = self.manager.archive(specification)
        before = self.manager.status()
        puts = list(self.transport.puts)
        self.assertEqual(refs, self.manager.archive(specification))
        self.assertEqual(puts, self.transport.puts)
        after = self.manager.status()
        for key in ("refs", "physical_objects", "retained_unique_bytes", "gross_generated_bytes", "original_logical_files"):
            self.assertEqual(before[key], after[key], key)

    def test_resume_after_verified_pack_interruption_does_not_reupload_pack(self):
        path = self.file("result.bin", b"Synthetic interrupted transfer.\n" * 100)
        specification = self.spec(path)
        self.transport.interrupt_before_index = True
        with self.assertRaisesRegex(EvidenceError, "interruption"):
            self.manager.archive(specification)
        self.assertEqual(1, len(self.pack_puts()))
        self.assertTrue(path.is_file())
        self.transport.interrupt_before_index = False
        refs = self.manager.archive(specification)
        self.assertEqual(1, len(self.pack_puts()))
        self.assertEqual(path.read_bytes(), self.resolved(refs[0]))
        self.assertEqual(path.stat().st_size, self.manager.status()["gross_generated_bytes"])

    def test_changed_source_after_complete_checkpoint_never_deletes_new_bytes(self):
        path = self.file("result.bin", b"Original synthetic bytes")
        specification = self.spec(path)
        refs = self.manager.archive(specification)
        path.write_bytes(b"NEW bytes produced after original sealing")
        puts = list(self.transport.puts)
        with self.assertRaisesRegex(EvidenceError, "inventory changed"):
            self.manager.archive(specification, remove_local=True)
        self.assertEqual(b"NEW bytes produced after original sealing", path.read_bytes())
        self.assertEqual(puts, self.transport.puts)
        self.assertEqual(b"Original synthetic bytes", self.resolved(refs[0]))

    def test_changed_input_during_incomplete_resume_preserves_every_original(self):
        first = self.file("first.bin", b"First synthetic captured bytes")
        second = self.file("second.bin", b"Second unchanged synthetic bytes")
        specification = self.spec(first, second)
        self.transport.interrupt_before_index = True
        with self.assertRaisesRegex(EvidenceError, "interruption"):
            self.manager.archive(specification)
        first.write_bytes(b"NEW first bytes after interrupted archive")
        puts = list(self.transport.puts)
        self.transport.interrupt_before_index = False
        with self.assertRaisesRegex(EvidenceError, "inventory changed"):
            self.manager.archive(specification, remove_local=True)
        self.assertEqual(b"NEW first bytes after interrupted archive", first.read_bytes())
        self.assertEqual(b"Second unchanged synthetic bytes", second.read_bytes())
        self.assertEqual(puts, self.transport.puts)
        self.assertEqual(0, self.manager.status()["refs"])

    def test_corrupt_independent_readback_never_removes_local_original(self):
        path = self.file("result.bin", b"Synthetic original to preserve" * 100)
        original = path.read_bytes()
        self.transport.corrupt_packs = True
        with self.assertRaisesRegex(EvidenceError, "archive original bytes"):
            self.manager.archive(self.spec(path), remove_local=True)
        self.assertEqual(original, path.read_bytes())
        self.transport.corrupt_packs = False
        self.assertEqual(0, self.manager.status()["refs"])
        journals = list(self.manager.state.glob("archive-*.json"))
        self.assertTrue(journals)
        self.assertTrue(all(json.loads(path.read_text())["status"] != "complete" for path in journals))

    def imported_mapping(self, *, neutral=False):
        data = b"Synthetic imported recovery bytes.\n" * 50
        path = self.file("legacy-original.bin", data)
        digest, size = hash_file(path)
        pack_file = self.base / "existing-archive.zip"
        pack = build_pack([{"path": path, "sha256": digest, "size": size}], pack_file, 1024 * 1024, 10)
        locator = self.transport.put("preexisting/synthetic-archive.zip", pack_file)
        historical = "2026-01-02T08:30:00Z"
        obj = {**pack, "locator": locator}
        record = {"artifact_id": "synthetic-import-1", "sha256": digest, "size": size,
            "provenance": {"run_id": "historical-synthetic-run", "unit_id": "U-legacy"}, "bindings": {},
            "original_path": "original/captured.bin", "retention": {"sealed_at": SEALED, "class": "recovery"},
            "verified_at": historical, "parts": [{"object": "legacy-object", "member": pack["members"][0]["member"], "offset": 0, "length": size}]}
        mapping = {"version": 1, "objects": {"legacy-object": obj}, "files": [record], "original_catalogs": ["synthetic-original-catalog.json"]}
        if neutral:
            member = pack["members"][0]
            ref = {"version": 1, "artifact_id": record["artifact_id"], "sha256": digest, "size": size,
                   "kind": "recovery-attachment", "schema": "archive-attachment-v1", "provenance": record["provenance"],
                   "bindings": {}, "original_path": record["original_path"], "historical_verified_at": historical,
                   "retention": record["retention"], "locator": {"provider": "local", "store_id": self.policy["store_id"],
                       "object_id": locator["object_id"], "key": locator["key"], "pack_sha256": pack["sha256"],
                       "pack_size": pack["size"], "member": member["member"]}}
            mapping = {"version": 1, "refs": [ref], "packs": {pack["sha256"]: {**pack, "locator": locator, "original_bytes": size}},
                       "original_catalogs": ["synthetic-original-catalog.json"]}
        return mapping, data, historical

    def test_import_object_table_verifies_payload_without_reupload_and_cold_restore(self):
        mapping, data, historical = self.imported_mapping()
        preserved_mapping = deepcopy(mapping)
        old_payload = (self.store / "preexisting/synthetic-archive.zip").read_bytes()
        before = len(self.transport.puts)
        refs = self.manager.import_archive(mapping)
        self.assertEqual(preserved_mapping, mapping)
        new_puts = self.transport.puts[before:]
        self.assertTrue(new_puts)
        self.assertTrue(all(key.endswith(".json") and "/packs/" not in key for key in new_puts))
        self.assertEqual(old_payload, (self.store / "preexisting/synthetic-archive.zip").read_bytes())
        ref = refs[0]
        self.assertEqual(SEALED, ref["retention"]["sealed_at"])
        self.assertEqual(historical, ref["historical_verified_at"])
        self.assertTrue(ref["retention"]["imported"])
        self.assertFalse(ref["retention"]["migration_policy_established"])
        self.assertEqual(0, self.manager.status()["gross_generated_bytes"])
        cold = Manager(ObservedTransport(self.store), self.base / "cold-home", self.policy)
        restored = cold.restore(list(cold._catalog()["refs"].values()), self.base / "restoration")
        self.assertEqual(data, Path(restored[0]).read_bytes())
        self.assertEqual(historical, cold._catalog()["refs"][ref["artifact_id"]]["historical_verified_at"])
        with self.assertRaisesRegex(EvidenceError, "coordinator authority"):
            cold.cleanup(now=SEALED_TIME + timedelta(days=31), dry_run=False, expire=True, reference_snapshot_complete=True)

    def test_import_neutral_refs_alternative_layout_and_original_mapping_preserved(self):
        mapping, data, historical = self.imported_mapping(neutral=True)
        before = deepcopy(mapping)
        payload_puts = len([key for key in self.transport.puts if key.endswith(".zip")])
        refs = self.manager.import_archive(mapping)
        self.assertEqual(before, mapping)
        self.assertEqual(payload_puts, len([key for key in self.transport.puts if key.endswith(".zip")]))
        self.assertEqual(data, self.resolved(refs[0]))
        self.assertEqual(historical, refs[0]["historical_verified_at"])
        saved = list((self.manager.state / "imports").glob("*.json"))
        self.assertEqual(1, len(saved))
        self.assertEqual(before, json.loads(saved[0].read_text()))

    def test_imported_collection_protected_until_explicit_retention_decision(self):
        mapping, _, _ = self.imported_mapping()
        refs = self.manager.import_archive(mapping)
        actions = self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), expire=True,
                                      reference_snapshot_complete=True, dry_run=False)
        protected = [action for action in actions if action["action"] == "expired-but-protected"]
        self.assertEqual(1, len(protected))
        self.assertIn("imported-migration-policy-pending", protected[0]["reasons"])
        self.assertEqual(1, self.manager.status()["refs"])
        self.manager.establish_import_retention([refs[0]["artifact_id"]])
        self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), expire=True,
                             reference_snapshot_complete=True, dry_run=False)
        self.assertEqual(0, self.manager.status()["refs"])
        self.assertFalse((self.store / "preexisting/synthetic-archive.zip").exists())

    def test_import_split_file_offsets_and_original_whole_hash(self):
        pieces = [b"Synthetic first imported segment\n" * 100, b"Synthetic second imported segment\n" * 80]
        objects, parts, offset = {}, [], 0
        for index, data in enumerate(pieces):
            path = self.file("legacy-part-" + str(index) + ".bin", data)
            digest, size = hash_file(path)
            packed_path = self.base / ("legacy-part-" + str(index) + ".zip")
            packed = build_pack([{"path": path, "sha256": digest, "size": size}], packed_path, 1024 * 1024, 10)
            locator = self.transport.put("preexisting/part-" + str(index) + ".zip", packed_path)
            name = "part-" + str(index)
            objects[name] = {**packed, "locator": locator}
            parts.append({"object": name, "member": packed["members"][0]["member"], "offset": offset, "length": size})
            offset += size
        whole = b"".join(pieces)
        mapping = {"version": 1, "objects": objects, "files": [{"artifact_id": "synthetic-import-split", "sha256": hashlib.sha256(whole).hexdigest(),
            "size": len(whole), "provenance": {"run_id": "historical-synthetic-run", "unit_id": "U-legacy"}, "bindings": {},
            "original_path": "original/whole.bin", "retention": {"sealed_at": SEALED, "class": "recovery"},
            "verified_at": "2026-01-02T08:30:00Z", "parts": parts}]}
        payload_puts = len([key for key in self.transport.puts if key.endswith(".zip")])
        refs = self.manager.import_archive(mapping)
        self.assertEqual([0, len(pieces[0])], [segment["offset"] for segment in refs[0]["locator"]["segments"]])
        self.assertEqual(whole, self.resolved(refs[0]))
        self.assertEqual(payload_puts, len([key for key in self.transport.puts if key.endswith(".zip")]))
        self.assertEqual("2026-01-02T08:30:00Z", refs[0]["historical_verified_at"])

    def test_import_index_cannot_prove_corrupt_active_payload(self):
        mapping, _, _ = self.imported_mapping()
        before = list(self.transport.puts)
        self.transport.corrupt_packs = True
        with self.assertRaisesRegex(EvidenceError, "archive original bytes"):
            self.manager.import_archive(mapping)
        self.assertEqual(before, self.transport.puts)
        self.transport.corrupt_packs = False
        self.assertEqual(0, self.manager.status()["refs"])

    def test_day29_day30_cache_eviction_keeps_sole_local_durable_copy(self):
        data = b"Synthetic sole durable copy" * 100
        path = self.file("result.bin", data)
        ref = self.manager.archive(self.spec(path), remove_local=True)[0]
        self.assertFalse(path.exists())
        object_path = self.manager.cache / "objects" / ref["sha256"]
        self.assertTrue(object_path.is_file())
        actions = self.manager.cleanup(now=SEALED_TIME + timedelta(days=29), dry_run=False)
        self.assertEqual([], actions)
        actions = self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), dry_run=False)
        self.assertTrue(any(action["action"] == "evict-cache" for action in actions))
        self.assertFalse(object_path.exists())
        self.assertTrue((self.store / ref["locator"]["key"]).is_file())
        self.assertEqual(data, self.resolved(ref))
        self.assertEqual(SEALED, ref["retention"]["sealed_at"])

    def test_dry_run_and_permanent_expiry_never_treat_durable_store_as_cache(self):
        path = self.file("obsolete.bin", b"Obsolete synthetic diagnostics")
        ref = self.manager.archive(self.spec(path))[0]
        durable = self.store / ref["locator"]["key"]
        self.assertEqual([], self.manager.cleanup(now=SEALED_TIME + timedelta(days=29), expire=True, reference_snapshot_complete=True))
        dry = self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), expire=True, reference_snapshot_complete=True)
        self.assertTrue(any(action["action"] == "retire" for action in dry))
        self.assertTrue(durable.exists())
        self.assertEqual(1, self.manager.status()["refs"])
        self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), expire=True, dry_run=False, reference_snapshot_complete=True)
        self.assertFalse(durable.exists())
        self.assertEqual(0, self.manager.status()["refs"])
        self.assertEqual(len(b"Obsolete synthetic diagnostics"), self.manager.status()["gross_generated_bytes"])

    def test_drive_archive_expiry_is_independent_of_local_cache_days(self):
        # A real local byte transport stands in for a synthetic remote host here;
        # this verifies retention semantics and makes no cloud-account assertion.
        self.policy["provider"] = "google-drive"
        self.policy["retention"]["drive_days"] = 90
        self.manager = Manager(self.transport, self.home, self.policy)
        path = self.file("remote-diagnostic.bin", b"Synthetic remote durable bytes")
        ref = self.manager.archive(self.spec(path))[0]
        durable = self.store / ref["locator"]["key"]
        self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), dry_run=False)
        self.assertFalse((self.manager.cache / "objects" / ref["sha256"]).exists())
        self.assertTrue(durable.exists())
        for age in (30, 89):
            actions = self.manager.cleanup(now=SEALED_TIME + timedelta(days=age), expire=True, dry_run=False, reference_snapshot_complete=True)
            self.assertEqual([], actions)
            self.assertTrue(durable.exists())
        self.manager.cleanup(now=SEALED_TIME + timedelta(days=90), expire=True, dry_run=False, reference_snapshot_complete=True)
        self.assertFalse(durable.exists())

    def test_explicit_never_remote_expiry_does_not_inherit_local_30_days(self):
        self.policy["provider"] = "google-drive"
        self.policy["retention"]["drive_days"] = None
        self.manager = Manager(self.transport, self.home, self.policy)
        path = self.file("remote-recovery.bin", b"Synthetic remote never-expire bytes")
        ref = self.manager.archive(self.spec(path))[0]
        actions = self.manager.cleanup(now=SEALED_TIME + timedelta(days=365), expire=True, dry_run=False, reference_snapshot_complete=True)
        self.assertEqual([], actions)
        self.assertTrue((self.store / ref["locator"]["key"]).exists())

    def test_current_claim_dependencies_and_receipts_protect_only_required_evidence(self):
        child = self.file("source-inventory.bin", b"Synthetic prerequisite inventory")
        child_ref = self.manager.archive(self.spec(child))[0]
        parent = self.file("acceptance.bin", b"Synthetic current acceptance")
        parent_ref = self.manager.archive(self.spec(parent, dependencies=[[child_ref]]))[0]
        receipt = self.file("approval.bin", b"Synthetic approval fixture, not a human receipt")
        receipt_ref = self.manager.archive(self.spec(receipt, kinds=["approval"]))[0]
        obsolete = self.file("unneeded.bin", b"Synthetic obsolete diagnostics")
        obsolete_ref = self.manager.archive(self.spec(obsolete))[0]
        actions = self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), expire=True, dry_run=False,
                                      protected_refs=[parent_ref["artifact_id"]], reference_snapshot_complete=True)
        current = self.manager._catalog()["refs"]
        self.assertEqual({child_ref["artifact_id"], parent_ref["artifact_id"], receipt_ref["artifact_id"]}, set(current))
        self.assertNotIn(obsolete_ref["artifact_id"], current)
        reasons = {action["artifact_id"]: action.get("reasons", []) for action in actions if action["action"] == "expired-but-protected"}
        self.assertIn("current-claim-or-prerequisite", reasons[child_ref["artifact_id"]])
        self.assertIn("approval", reasons[receipt_ref["artifact_id"]])

    def test_permanent_expiry_requires_complete_reference_snapshot(self):
        path = self.file("result.bin", b"Synthetic complete snapshot obligation")
        ref = self.manager.archive(self.spec(path))[0]
        with self.assertRaisesRegex(EvidenceError, "complete current claim"):
            self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), expire=True, dry_run=False)
        self.assertEqual(1, self.manager.status()["refs"])
        self.assertTrue((self.store / ref["locator"]["key"]).exists())

    def test_unavailable_remote_preserves_original_and_replaceable_cache(self):
        path = self.file("result.bin", b"Synthetic unavailable store obligation")
        specification = self.spec(path)
        ref = self.manager.archive(specification)[0]
        cached = self.manager.cache / "objects" / ref["sha256"]
        original, prepared = path.read_bytes(), cached.read_bytes()
        self.transport.unavailable = True
        with self.assertRaisesRegex(EvidenceError, "unavailable"):
            self.manager.archive(specification, remove_local=True)
        with self.assertRaisesRegex(EvidenceError, "unavailable"):
            self.manager.cleanup(now=SEALED_TIME + timedelta(days=31), dry_run=False)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(prepared, cached.read_bytes())

    def test_partial_local_deletion_intent_resumes_without_missing_original_rearchive(self):
        first = self.file("first.bin", b"Synthetic first original")
        second = self.file("second.bin", b"Synthetic second original")
        specification = self.spec(first, second)
        original_unlink = Path.unlink
        def interrupted(path, *args, **kwargs):
            if path == second:
                raise OSError("synthetic original deletion interrupted")
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", interrupted):
            with self.assertRaisesRegex(OSError, "interrupted"):
                self.manager.archive(specification, remove_local=True)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        journals = list(self.manager.state.glob("archive-*.deletion.json"))
        self.assertEqual(1, len(journals))
        intent = json.loads(journals[0].read_text())
        self.assertEqual([True, False], [entry["done"] for entry in intent["entries"]])
        puts = list(self.transport.puts)
        self.manager.reconcile(dry_run=False)
        self.assertFalse(second.exists())
        self.assertEqual(puts, self.transport.puts)
        self.assertTrue(all(entry["done"] for entry in json.loads(journals[0].read_text())["entries"]))

    def test_partial_pack_deletion_counts_failed_object_then_reconciles(self):
        self.policy["limits"].update(archive_pack_target_bytes=32, archive_pack_stop_bytes=4096)
        self.manager = Manager(self.transport, self.home, self.policy)
        first = self.file("first.bin", b"A" * 30)
        second = self.file("second.bin", b"B" * 30)
        refs = self.manager.archive(self.spec(first, second))
        self.assertEqual(2, self.manager.status()["physical_objects"])
        failed_key = refs[0]["locator"]["key"]
        self.transport.fail_deletions.add(failed_key)
        actions = self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), expire=True, dry_run=False,
                                       reference_snapshot_complete=True)
        self.assertTrue(any(action["action"] == "delete-failed" for action in actions))
        self.assertEqual(0, self.manager.status()["refs"])
        self.assertEqual(1, self.manager.status()["physical_objects"])
        self.assertTrue((self.store / failed_key).exists())
        self.assertTrue((self.manager.state / "pruning.json").is_file())
        self.transport.fail_deletions.clear()
        self.manager.reconcile(dry_run=False)
        self.assertEqual(0, self.manager.status()["physical_objects"])
        self.assertFalse((self.store / failed_key).exists())
        self.assertFalse((self.manager.state / "pruning.json").exists())

    def test_remote_pruning_intent_survives_lost_local_deletion_journal(self):
        path = self.file("obsolete.bin", b"Synthetic recoverable pending deletion")
        ref = self.manager.archive(self.spec(path))[0]
        key = ref["locator"]["key"]
        self.transport.fail_deletions.add(key)
        self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), expire=True, dry_run=False, reference_snapshot_complete=True)
        self.assertEqual(1, self.manager.status()["physical_objects"])
        (self.manager.state / "pruning.json").unlink()
        self.transport.fail_deletions.clear()
        restarted = Manager(self.transport, self.home, self.policy)
        restarted.cleanup(now=SEALED_TIME + timedelta(days=31), expire=False, dry_run=False)
        self.assertFalse((self.store / key).exists())
        self.assertEqual(0, restarted.status()["physical_objects"])
        self.assertFalse((restarted.state / "pruning.json").exists())

    def test_combined_root_and_index_byte_limit_cannot_be_bypassed_by_splitting(self):
        self.policy["limits"]["metadata_stop_bytes"] = 2 * 1024 * 1024
        self.manager = Manager(self.transport, self.home, self.policy)
        published = 0
        for number in range(20):
            catalog = self.manager._catalog(mutation=True)
            try:
                self.manager._publish(catalog, {"version": 1, "refs": [], "packs": {}, "generation": {},
                                               "synthetic_segment": number, "padding": "x" * 200000})
                published += 1
            except EvidenceError as error:
                self.assertRegex(str(error), r"combined (?:catalog )?metadata")
                break
        else:
            self.fail("splitting indexes evaded combined metadata bound")
        self.assertGreaterEqual(published, 2)
        catalog = self.manager._catalog()
        self.assertLessEqual(catalog["metadata_bytes"], 2 * 1024 * 1024)
        files = [path for path in self.store.rglob("*.json")]
        self.assertTrue(all(path.stat().st_size < 2 * 1024 * 1024 for path in files))
        self.assertEqual(sum(path.stat().st_size for path in files), catalog["metadata_bytes"])

    def test_cold_database_recovers_generation_and_enforces_same_unit_budget(self):
        self.policy["limits"].update(unit_warning_bytes=900, unit_stop_bytes=1000)
        self.manager = Manager(self.transport, self.home, self.policy)
        path = self.file("first.bin", b"S" * 500)
        specification = self.spec(path)
        self.manager.archive(specification)
        cold = Manager(ObservedTransport(self.store), self.base / "fresh-home-no-original-db", self.policy)
        status = cold.status()
        self.assertEqual(500, status["gross_generated_bytes"])
        self.assertEqual(1, status["original_logical_files"])
        unit_id = specification["files"][0]["provenance"]["unit_id"]
        with Accounting(cold.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            with self.assertRaisesRegex(BudgetExceeded, "unit cumulative bytes"):
                ledger.reserve("new-session-new-script-name", unit_id, 600, 1)
        self.assertEqual(500, cold.status()["gross_generated_bytes"])

    def produce(self):
        output = self.base / "managed-output"
        output.mkdir()
        code = "import os; from pathlib import Path; Path(os.environ['SDD_EVIDENCE_OUTPUT_DIR'], 'observation.bin').write_bytes(b'Synthetic managed observation\\n' * 50)"
        with Accounting(self.manager.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            result = run_producer(ledger, "managed-run-1", "U-managed", output, [sys.executable, "-c", code],
                                  4096, 3, timeout=10, poll_interval=0.02)
        self.assertEqual("complete", result["status"], result)
        specification = {"version": 1, "managed_output_id": result["output_id"], "files": [{"path": str(output / name),
            "original_path": name, "sealed_at": SEALED, "kind": "diagnostic", "schema": "evidence-bytes-v1", "bindings": {},
            "provenance": {"run_id": result["run_id"], "unit_id": result["unit_id"]}}
            for name in result["observations"]]}
        return result, specification, output

    def test_real_managed_producer_archive_settles_once_and_cold_recovery_keeps_charge(self):
        produced, specification, output = self.produce()
        before = self.manager.status()
        self.assertEqual(produced["gross_bytes"], before["gross_generated_bytes"])
        refs = self.manager.archive(specification)
        after = self.manager.status()
        self.assertEqual(before["gross_generated_bytes"], after["gross_generated_bytes"])
        self.assertEqual(before["original_logical_files"], after["original_logical_files"])
        for ref in refs:
            self.assertEqual((output / ref["original_path"]).read_bytes(), self.resolved(ref))
        cold = Manager(ObservedTransport(self.store), self.base / "cold-managed-home", self.policy)
        self.assertEqual(produced["gross_bytes"], cold.status()["gross_generated_bytes"])
        self.assertEqual(produced["gross_files"], cold.status()["original_logical_files"])

    def test_managed_output_changed_after_settlement_cannot_be_registered(self):
        produced, specification, output = self.produce()
        (output / "observation.bin").write_bytes(b"Changed after managed producer sealing")
        puts = list(self.transport.puts)
        with self.assertRaisesRegex(EvidenceError, "changed|different"):
            self.manager.archive(specification)
        self.assertEqual(puts, self.transport.puts)
        self.assertEqual(0, self.manager.status()["refs"])
        self.assertEqual(produced["gross_bytes"], self.manager.status()["gross_generated_bytes"])
        self.assertEqual(b"Changed after managed producer sealing", (output / "observation.bin").read_bytes())

    def test_day30_original_cleanup_only_registered_verified_paths(self):
        registered = self.file("registered.bin", b"Registered synthetic diagnostic")
        unregistered = self.file("unregistered.bin", b"Unregistered authored material to preserve")
        ref = self.manager.archive(self.spec(registered))[0]
        self.manager.cleanup(now=SEALED_TIME + timedelta(days=29), dry_run=False)
        self.assertTrue(registered.exists())
        dry = self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), dry_run=True)
        self.assertTrue(any(action["action"] == "evict-local-originals" for action in dry))
        self.assertTrue(registered.exists())
        self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), dry_run=False)
        self.assertFalse(registered.exists())
        self.assertEqual(b"Unregistered authored material to preserve", unregistered.read_bytes())
        self.assertTrue((self.store / ref["locator"]["key"]).exists())
        self.assertEqual(b"Registered synthetic diagnostic", self.resolved(ref))

    def test_day30_corrupt_durable_copy_preserves_registered_original_and_cache(self):
        registered = self.file("registered.bin", b"Preserve while durable bytes fail verification")
        ref = self.manager.archive(self.spec(registered))[0]
        cached = self.manager.cache / "objects" / ref["sha256"]
        original = registered.read_bytes()
        cache = cached.read_bytes()
        self.transport.corrupt_packs = True
        with self.assertRaisesRegex(EvidenceError, "archive original bytes"):
            self.manager.cleanup(now=SEALED_TIME + timedelta(days=30), dry_run=False)
        self.assertEqual(original, registered.read_bytes())
        self.assertEqual(cache, cached.read_bytes())

    def test_cli_git_review_obeys_policy_and_counts_added_then_removed_blob(self):
        project = self.base / "synthetic-git-project"
        project.mkdir()
        def git(*arguments):
            result = subprocess.run(["git", "-C", str(project), *arguments], capture_output=True, text=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            return result.stdout.strip()
        git("init", "--quiet")
        (project / "source.txt").write_text("Synthetic authored source.\n")
        git("add", "source.txt")
        git("-c", "user.name=Synthetic tests", "-c", "user.email=synthetic@example.invalid", "commit", "--quiet", "-m", "source")
        base = git("rev-parse", "HEAD")
        (project / "temporary-data.bin").write_bytes(b"T" * 1024)
        git("add", "temporary-data.bin")
        git("-c", "user.name=Synthetic tests", "-c", "user.email=synthetic@example.invalid", "commit", "--quiet", "-m", "introduce synthetic bytes")
        git("rm", "--quiet", "temporary-data.bin")
        git("-c", "user.name=Synthetic tests", "-c", "user.email=synthetic@example.invalid", "commit", "--quiet", "-m", "remove synthetic bytes")
        self.assertEqual("", git("diff", "--name-only", base, "HEAD"))
        policy = deepcopy(self.policy)
        policy["git_review"] = {"blob_bytes": 512, "range_bytes": 768}
        policy_path = project / "forge/evidence-policy.json"
        policy_path.parent.mkdir()
        policy_path.write_text(json.dumps(policy))
        def review():
            result = subprocess.run([sys.executable, str(ROOT / "skills/to-sdd-pipeline/scripts/evidence_store.py"), "git-review",
                "--project", str(project), "--base", base], env=dict(os.environ, SDD_EVIDENCE_HOME=str(self.home)),
                capture_output=True, text=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            return json.loads(result.stdout)
        report = review()
        self.assertEqual(1024, report["new_blob_bytes"])
        self.assertEqual(1, report["new_blob_count"])
        self.assertEqual(2, report["commits"])
        self.assertTrue(report["review_required"])
        self.assertFalse(report["enforced_rejection"])
        policy["git_review"] = {"blob_bytes": 2048, "range_bytes": 3072}
        policy_path.write_text(json.dumps(policy))
        self.assertFalse(review()["review_required"])


if __name__ == "__main__":
    unittest.main()
