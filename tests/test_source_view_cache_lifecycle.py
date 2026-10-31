"""Synthetic inode occupancy and shared source-view cache lifecycle regressions.

Occupancy means each distinct regular inode's byte length, not filesystem block
allocation, directory overhead, logical membership or gross generation charges.
No source-view subtree is exempt: malformed/orphan/private files remain charged.
"""
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_evidence_manager as fixtures
from evidence.accounting import Accounting, BudgetExceeded
from evidence.io import EvidenceError, atomic_json
from evidence.resolver import EvidenceResolver


class SourceViewCacheLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EvidenceManagerTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manager, self.transport = self.fixture.manager, self.fixture.transport

    def archived(self, *, remove_local=False):
        original = self.fixture.file("source.bin", b"Synthetic immutable source bytes.\n" * 80)
        ref = self.manager.archive(self.fixture.spec(original), remove_local=remove_local)[0]
        return ref, self.manager.cache / "objects" / ref["sha256"]

    def link(self, target, name=None):
        alias = self.manager.cache / "source-views" / "synthetic-index" / "blobs" / (name or target.name)
        alias.parent.mkdir(parents=True, exist_ok=True)
        os.link(target, alias)
        return alias

    def test_distinct_inode_occupancy_counts_links_once_and_private_copies_twice(self):
        before = self.manager._usage()
        target = self.manager.cache / "synthetic-object"
        target.write_bytes(b"x" * 257)
        alias = self.link(target)
        self.assertEqual(before + 257, self.manager._usage())
        self.assertEqual(257, self.manager._cache_bytes())
        private = alias.with_name("independent-private-copy")
        shutil.copyfile(alias, private)
        self.assertEqual(before + 514, self.manager._usage())
        self.assertEqual(514, self.manager._cache_bytes())
        self.assertEqual(771, self.manager._existing_bytes([target, alias, private]),
            "logical metadata accounting retains per-path charges")

    def test_retained_views_remain_cache_occupancy_when_primary_name_is_gone(self):
        ref, target = self.archived()
        alias = self.link(target)
        before = self.manager._cache_bytes()
        target.unlink()
        self.assertEqual(before, self.manager._cache_bytes())
        self.assertEqual(ref["size"], alias.stat().st_size)
        with Accounting(self.manager.state / "accounting.sqlite", self.manager.policy["project_id"], self.manager.policy) as ledger:
            self.manager._local_records(ledger)
            self.assertEqual(before, ledger.snapshot()["totals"]["cache_bytes"])

    def test_missing_canonical_with_retained_blob_requires_explicit_rebuild(self):
        ref, target = self.archived(remove_local=True)
        alias = self.link(target)
        catalog = self.manager._catalog()
        target.unlink()
        with patch.object(self.transport, "get", side_effect=AssertionError("missing canonical was silently rebuilt")):
            with self.assertRaisesRegex(EvidenceError, "retained.*alias.*rebuild"):
                self.manager.prepare([ref], catalog=catalog)
        self.assertFalse(target.exists())
        self.assertEqual(ref["size"], alias.stat().st_size)
        actions = self.manager.cleanup(now=fixtures.SEALED_TIME + timedelta(days=30), dry_run=False)
        retained = [a for a in actions if a["action"] == "retain-cache-aliases"]
        self.assertTrue(retained)
        self.assertTrue(retained[0]["canonical_missing"])
        self.assertEqual(ref["size"], retained[0]["retained_bytes"])
        self.assertEqual(0, retained[0]["freed_bytes"])

    def test_owned_state_transport_and_checkpoint_aliases_share_one_local_charge(self):
        before = self.manager._usage()
        target = self.manager.cache / "payload"
        target.write_bytes(b"x" * 100)
        os.link(target, self.manager.staging / "same-inode")
        session = self.fixture.base / "host-session"
        session.mkdir()
        os.link(target, session / "same-inode")
        checkpoints = self.fixture.base / "checkpoints"
        checkpoints.mkdir()
        os.link(target, checkpoints / "same-inode")
        self.transport.host_session_path = session
        self.transport.checkpoint_peak_bytes = 1
        self.transport.state_dir = checkpoints
        self.assertEqual(before + 100, self.manager._usage())
        self.assertEqual(100, self.manager._cache_bytes())
        with Accounting(self.manager.state / "accounting.sqlite", self.manager.policy["project_id"], self.manager.policy) as ledger:
            self.manager._local_records(ledger)
            rows = dict(ledger.connection.execute("SELECT key,bytes FROM local_usage"))
            self.assertEqual(100, rows["cache"])
            self.assertEqual(0, rows["transport-checkpoints"])

    def test_no_view_or_unregistered_path_quota_exemption(self):
        for name in ("source-views/orphan/unknown", "unregistered/private-copy"):
            path = self.manager.cache / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 4000)
        self.manager.limits["cache_stop_bytes"] = 7999
        with self.assertRaisesRegex(BudgetExceeded, "cache"):
            with self.manager._working(1, cache_bytes=1):
                self.fail("unregistered source paths bypassed cache allowance")
        self.manager.limits["local_stop_bytes"] = self.manager._usage() - 1
        with self.assertRaisesRegex(EvidenceError, "local working-space"):
            self.manager._capacity(0)

    def test_link_and_special_file_errors_are_not_hidden_by_inode_deduplication(self):
        target = self.manager.cache / "real"
        target.write_bytes(b"synthetic")
        unsafe = self.manager.cache / "source-views"
        unsafe.symlink_to(target)
        for method in (self.manager._usage, self.manager._cache_bytes):
            with self.assertRaisesRegex(EvidenceError, "link"):
                method()
        unsafe.unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(unsafe)
            for method in (self.manager._usage, self.manager._cache_bytes):
                with self.assertRaisesRegex(EvidenceError, "special"):
                    method()
            unsafe.unlink()

    def test_valid_reprepare_preserves_inode_receipt_and_avoids_provider_download(self):
        ref, target = self.archived()
        self.link(target)
        catalog = self.manager._catalog()
        before = target.stat()
        receipt = self.manager.cache / "receipts" / (ref["artifact_id"] + ".json")
        saved = (receipt.read_bytes(), receipt.stat().st_ino)
        with patch.object(self.transport, "get", side_effect=AssertionError("valid cache was downloaded")), \
                patch("evidence.manager.atomic_json", wraps=atomic_json) as writes:
            self.manager.prepare([ref], catalog=catalog)
        self.assertEqual((before.st_dev, before.st_ino), (target.stat().st_dev, target.stat().st_ino))
        self.assertEqual(saved, (receipt.read_bytes(), receipt.stat().st_ino))
        self.assertFalse(any(Path(call.args[0]) == receipt for call in writes.call_args_list))
        EvidenceResolver(self.manager.cache).resolve(ref)

    def test_explicit_durable_readback_also_preserves_verified_shared_inode(self):
        ref, target = self.archived()
        alias = self.link(target)
        catalog = self.manager._catalog()
        inode = target.stat().st_ino
        receipt = self.manager.cache / "receipts" / (ref["artifact_id"] + ".json")
        saved = receipt.read_bytes(), receipt.stat().st_ino
        with patch.object(self.transport, "get", wraps=self.transport.get) as get:
            self.manager.prepare([ref], catalog=catalog, reverify_durable=True)
        self.assertGreater(get.call_count, 0)
        self.assertEqual(inode, target.stat().st_ino)
        self.assertEqual(inode, alias.stat().st_ino)
        self.assertEqual(saved, (receipt.read_bytes(), receipt.stat().st_ino))

    def test_fresh_reprepare_detects_alias_write_even_with_restored_mtime(self):
        ref, target = self.archived()
        alias = self.link(target)
        catalog = self.manager._catalog()
        self.manager.prepare([ref], catalog=catalog)
        saved = target.stat()
        alias.write_bytes(b"!" * ref["size"])
        os.utime(alias, ns=(saved.st_atime_ns, saved.st_mtime_ns))
        corrupted = alias.read_bytes()
        with patch.object(self.transport, "get", side_effect=AssertionError("invalid shared cache was downloaded")):
            with self.assertRaisesRegex(EvidenceError, "retained.*alias.*rebuild"):
                self.manager.prepare([ref], catalog=catalog)
        self.assertEqual(saved.st_ino, target.stat().st_ino)
        self.assertEqual(corrupted, target.read_bytes())

    def test_invalid_shared_receipt_blocks_without_replacement_or_rewrite(self):
        ref, target = self.archived()
        alias = self.link(target)
        catalog = self.manager._catalog()
        receipt = self.manager.cache / "receipts" / (ref["artifact_id"] + ".json")
        forged = json.loads(receipt.read_text())
        forged["bindings"] = {"source_hashes": {"forged": "1" * 64}}
        atomic_json(receipt, forged)
        before = target.stat().st_ino, receipt.read_bytes()
        with patch.object(self.transport, "get", side_effect=AssertionError("invalid receipt fetched payload")):
            with self.assertRaisesRegex(EvidenceError, "retained.*alias.*rebuild"):
                self.manager.prepare([ref], catalog=catalog)
        self.assertEqual(before, (target.stat().st_ino, receipt.read_bytes()))
        self.assertEqual(target.stat().st_ino, alias.stat().st_ino)

    def test_current_reference_binding_mismatch_is_not_blessed_by_valid_local_bytes(self):
        ref, target = self.archived()
        self.link(target)
        catalog = self.manager._catalog()
        forged = deepcopy(ref)
        forged["bindings"] = {"source_hashes": {"forged": "1" * 64}}
        inode = target.stat().st_ino
        with patch.object(self.transport, "get", side_effect=AssertionError("forged reference fetched payload")):
            with self.assertRaisesRegex(EvidenceError, "authoritative durable catalog"):
                self.manager.prepare([forged], catalog=catalog)
        self.assertEqual(inode, target.stat().st_ino)

    def test_alias_creation_during_reuse_fails_current_signature_check(self):
        ref, target = self.archived()
        alias = self.link(target)
        catalog = self.manager._catalog()
        inode = target.stat().st_ino
        original_capacity = self.manager._capacity
        def changed_links(peak, **kwargs):
            os.link(target, alias.with_name("raced-alias"))
            return original_capacity(peak, **kwargs)
        with patch.object(self.manager, "_capacity", side_effect=changed_links):
            with self.assertRaisesRegex(ValueError, "changed during validation"):
                self.manager.prepare([ref], catalog=catalog)
        self.assertEqual(inode, target.stat().st_ino)

    def test_alias_created_during_unaliased_recovery_blocks_replacement(self):
        ref, target = self.archived()
        catalog = self.manager._catalog()
        target.write_bytes(b"invalid unaliased original")
        inode, saved = target.stat().st_ino, target.read_bytes()
        original_get = self.transport.get
        created = []
        def add_alias(locator, destination, maximum):
            if not created:
                created.append(self.link(target))
            return original_get(locator, destination, maximum)
        with patch.object(self.transport, "get", side_effect=add_alias):
            with self.assertRaisesRegex(EvidenceError, "retained.*alias.*rebuild"):
                self.manager.prepare([ref], catalog=catalog)
        self.assertEqual((inode, saved), (target.stat().st_ino, target.read_bytes()))
        self.assertEqual(inode, created[0].stat().st_ino)

    def test_unaliased_invalid_cache_retains_normal_recovery(self):
        ref, target = self.archived()
        catalog = self.manager._catalog()
        before = target.stat().st_ino
        target.write_bytes(b"corrupt")
        with patch.object(self.transport, "get", wraps=self.transport.get) as get:
            self.manager.prepare([ref], catalog=catalog)
        self.assertGreater(get.call_count, 0)
        self.assertNotEqual(before, target.stat().st_ino)
        self.assertEqual(ref["sha256"], fixtures.hash_file(target)[0])

    def test_dependencies_are_prepared_and_durable_identity_is_checked_before_reuse(self):
        child, child_target = self.archived()
        parent_file = self.fixture.file("parent.bin", b"Synthetic dependent source")
        parent = self.manager.archive(self.fixture.spec(parent_file, dependencies=[[child]]))[0]
        target = self.manager.cache / "objects" / parent["sha256"]
        self.link(target)
        inode = target.stat().st_ino
        catalog = self.manager._catalog()
        child_target.unlink()
        self.manager.prepare([parent], catalog=catalog)
        self.assertTrue(child_target.exists())
        self.assertEqual(inode, target.stat().st_ino)
        original_stat = self.transport.stat
        def changed_identity(locator):
            result = original_stat(locator)
            if isinstance(locator, dict) and locator.get("object_id") == parent["locator"]["object_id"]:
                return {**result, "object_id": "forged-durable-object"}
            return result
        with patch.object(self.transport, "stat", side_effect=changed_identity):
            with self.assertRaisesRegex(EvidenceError, "durable.*identity"):
                self.manager.prepare([parent], catalog=catalog)
        self.assertEqual(inode, target.stat().st_ino)

    def test_cleanup_retains_aliases_and_reports_no_physical_release_or_refund(self):
        ref, target = self.archived(remove_local=True)
        alias = self.link(target)
        outside = self.fixture.base / "unknown-outside-alias"
        os.link(target, outside)
        before = self.manager.status()
        actions = self.manager.cleanup(now=fixtures.SEALED_TIME + timedelta(days=30), dry_run=False)
        retained = [a for a in actions if a.get("artifact_id") == ref["artifact_id"] and a["action"] == "retain-cache-aliases"]
        self.assertTrue(retained)
        self.assertTrue(all(a["freed_bytes"] == 0 and a["retained_bytes"] == ref["size"] for a in retained))
        self.assertTrue(all("rebuild" in a["reason"] for a in retained))
        self.assertFalse(any(a["action"] == "evict-cache" and a.get("artifact_id") == ref["artifact_id"] for a in actions))
        self.assertEqual(target.stat().st_ino, alias.stat().st_ino)
        self.assertEqual(target.stat().st_ino, outside.stat().st_ino)
        after = self.manager.status()
        for key in ("gross_generated_bytes", "original_logical_files", "retained_unique_bytes"):
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(self.manager._cache_bytes(), after["accounting"]["totals"]["cache_bytes"])

    def test_cleanup_preserves_required_independent_durable_readback(self):
        ref, target = self.archived()
        original = self.fixture.capture / "source.bin"
        saved = target.read_bytes(), target.stat().st_ino
        self.transport.corrupt_packs = True
        with self.assertRaises(EvidenceError):
            self.manager.cleanup(now=fixtures.SEALED_TIME + timedelta(days=30), dry_run=False)
        self.assertTrue(original.exists())
        self.assertEqual(saved, (target.read_bytes(), target.stat().st_ino))

    def test_metadata_files_and_generation_still_have_logical_charges(self):
        ref, target = self.archived()
        before = self.manager.status()
        receipt = self.manager.cache / "source-views" / "synthetic-index" / "view-receipt.json"
        receipt.parent.mkdir(parents=True)
        atomic_json(receipt, {"literal_members": ["one", "two"]})
        self.link(target)
        records = self.manager._metadata_records(include_checkpoints=False)
        with Accounting(self.manager.state / "accounting.sqlite", self.manager.policy["project_id"], self.manager.policy) as ledger:
            self.manager._local_records(ledger)
            row = ledger.connection.execute("SELECT bytes,files FROM metadata_usage WHERE key='local-journals-receipts'").fetchone()
            self.assertEqual((self.manager._existing_bytes(records), len(records)), tuple(row))
        after = self.manager.status()
        self.assertEqual(before["gross_generated_bytes"], after["gross_generated_bytes"])
        self.assertEqual(before["original_logical_files"], after["original_logical_files"])


if __name__ == "__main__":
    unittest.main()
