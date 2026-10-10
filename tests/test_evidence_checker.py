"""Prepared-cache resolution using synthetic bytes, never network or product files."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_sdd_check import Project, sdd
from evidence.resolver import EvidenceResolver


class EvidenceCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-prepared-evidence-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cache = self.root / "cache"
        (self.cache / "objects").mkdir(parents=True)
        (self.cache / "receipts").mkdir()
        self.p = Project(self.root / "project")
        self.m = self.p.manifest
        from evidence.policy import load_defaults
        self.policy = load_defaults()
        self.policy.update(project_id="11111111-1111-4111-8111-111111111111", store_id="22222222-2222-4222-8222-222222222222", provider="local")
        self.p.write("forge/evidence-policy.json", json.dumps(self.policy))
        self.m["evidence_accounting"] = {"version": 1, "project_id": self.policy["project_id"],
            "policy_sha256": self.p.hash("forge/evidence-policy.json"), "runs": {}}
        self.accounted = {}

    def prepare(self, content, artifact_id="fixture", kind="visual", schema="evidence-json-v1", bindings=None):
        data = content if isinstance(content, bytes) else json.dumps(content, sort_keys=True).encode()
        value = sdd.digest(data)
        ref = {"version": 1, "artifact_id": artifact_id, "sha256": value, "size": len(data),
               "kind": kind, "schema": schema, "provenance": {"run_id": "synthetic-original-run", "unit_id": "U-1"},
               "bindings": bindings or {}, "locator": {"provider": "local", "store_id": "synthetic-store",
                   "object_id": "synthetic-immutable-pack", "pack_sha256": "a" * 64, "pack_size": 1000, "member": "objects/" + value},
               "retention": {"sealed_at": "2026-08-20T10:06:00Z", "class": "current_acceptance"}}
        (self.cache / "objects" / value).write_bytes(data)
        self.receipt(ref)
        self.accounted[artifact_id] = len(data)
        self.m["evidence_accounting"]["runs"][ref["provenance"]["run_id"]] = {"unit_id": "U-1", "status": "complete",
            "gross_generated_bytes": sum(self.accounted.values()), "original_logical_files": len(self.accounted),
            "pending_reservations": 0, "unreconciled_outputs": 0}
        return ref

    def receipt(self, ref, closure=True):
        receipt = copy.deepcopy(ref)
        if closure:
            receipt["verified_archive"] = {"object_id": ref["locator"]["object_id"], "sha256": ref["locator"]["pack_sha256"],
                "size": ref["locator"]["pack_size"], "members": [{"artifact_id": ref["artifact_id"],
                "member": ref["locator"]["member"], "sha256": ref["sha256"], "size": ref["size"]}]}
        (self.cache / "receipts" / (ref["artifact_id"] + ".json")).write_text(json.dumps(receipt))

    def replace(self, record, artifact_id, kind, bindings, schema="sdd-receipt-v1"):
        path = self.p.root / record["path"]
        ref = self.prepare(path.read_bytes(), artifact_id, kind, schema, bindings)
        path.unlink()
        return ref

    def checker(self, cache=True):
        return sdd.Checker(self.p.root, self.m, evidence_cache=self.cache if cache else None)

    def test_prepared_original_bytes_and_receipt_identity_are_verified_without_writes(self):
        ref = self.prepare({"synthetic": True})
        before = {p: p.read_bytes() for p in self.cache.rglob("*") if p.is_file()}
        with patch("subprocess.run", side_effect=AssertionError("checker must not contact transport")):
            resolver = EvidenceResolver(self.cache)
            self.assertEqual({"synthetic": True}, resolver.json(ref))
        self.assertEqual(before, {p: p.read_bytes() for p in self.cache.rglob("*") if p.is_file()})

    def test_absent_prepared_cache_blocks_claim_and_never_creates_directory(self):
        ref = self.prepare({"synthetic": True})
        missing = self.root / "never-created"
        with self.assertRaises(ValueError):
            EvidenceResolver(missing).resolve(ref)
        self.assertFalse(missing.exists())
        checker = self.checker(cache=False)
        self.assertFalse(checker.evidence_snapshot(ref, "qa-checklist"))
        self.assertIn("--evidence-cache", checker.issues[0]["detail"])

    def test_corrupt_original_size_and_receipt_mismatch_block(self):
        ref = self.prepare({"synthetic": True})
        path = self.cache / "objects" / ref["sha256"]
        path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "hash/size mismatch"):
            EvidenceResolver(self.cache).resolve(ref)
        wrong = copy.deepcopy(ref)
        wrong["artifact_id"] = "other"
        self.receipt(wrong)
        wrong["locator"]["object_id"] = "different-object"
        with self.assertRaisesRegex(ValueError, "identity/reference mismatch"):
            EvidenceResolver(self.cache).resolve(wrong)

    def test_missing_or_duplicate_archive_member_closure_blocks(self):
        ref = self.prepare({"synthetic": True})
        self.receipt(ref, closure=False)
        with self.assertRaisesRegex(ValueError, "archive closure"):
            EvidenceResolver(self.cache).resolve(ref)
        self.receipt(ref)
        path = self.cache / "receipts" / "fixture.json"
        record = json.loads(path.read_text())
        record["verified_archive"]["members"] *= 2
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            EvidenceResolver(self.cache).resolve(ref)

    def test_unsupported_reference_and_payload_schemas_fail(self):
        ref = self.prepare({"version": 2, "source_hashes": {}}, schema="source-inventory-v1")
        with self.assertRaisesRegex(ValueError, "source inventory schema"):
            EvidenceResolver(self.cache).json(ref)
        for field, value in (("version", 2), ("schema", "unknown-future-schema")):
            bad = {**ref, field: value}
            with self.assertRaisesRegex(ValueError, "unsupported"):
                EvidenceResolver(self.cache).resolve(bad)

    def test_link_special_file_and_mutated_input_block(self):
        ref = self.prepare({"synthetic": True})
        path = self.cache / "objects" / ref["sha256"]
        resolver = EvidenceResolver(self.cache)
        resolver.resolve(ref)
        path.write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "changed during"):
            resolver.resolve(ref)
        path.unlink()
        real = self.root / "real"
        real.write_bytes(b"different")
        try:
            path.symlink_to(real)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(ValueError, "regular file"):
            EvidenceResolver(self.cache).resolve(ref)
        path.unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(path)
            with self.assertRaisesRegex(ValueError, "regular file"):
                EvidenceResolver(self.cache).resolve(ref)

    def test_reference_dependency_closure_is_required(self):
        dependency = self.prepare({"version": 1, "platform": "synthetic"}, "environment", "environment", "environment-v1")
        ref = self.prepare({"synthetic": True})
        ref["dependencies"] = [dependency]
        self.receipt(ref)
        EvidenceResolver(self.cache).resolve(ref)
        (self.cache / "objects" / dependency["sha256"]).unlink()
        with self.assertRaises((ValueError, OSError)):
            EvidenceResolver(self.cache).resolve(ref)

    def test_authorization_can_be_archived_without_rebinding_original_event(self):
        self.p.authorize()
        gate = self.m["implementation_gate"]
        original = json.loads((self.p.root / gate["prompt_receipt"]["path"]).read_text())
        gate["prompt_receipt"] = self.replace(gate["prompt_receipt"], "original-prompt", "authorization",
            {key: gate[key] for key in ("prompt_id", "development_plan_hash", "approved_baseline_id")})
        checker = self.checker()
        checker.authorization()
        self.assertFalse(checker.issues, checker.issues)
        self.assertEqual(original["received_at"], gate["prompt_received_at"])
        self.assertEqual(original, checker.evidence_json(gate["prompt_receipt"]))
        gate["development_plan_hash"] = "b" * 64
        checker = self.checker()
        checker.authorization()
        self.assertEqual("implementation_not_authorized", checker.issues[0]["code"])

    def test_generic_archived_continue_does_not_grant_authorization(self):
        self.p.authorize()
        gate = self.m["implementation_gate"]
        original = json.loads((self.p.root / gate["prompt_receipt"]["path"]).read_text())
        original["message"] = "continue"
        gate["prompt_receipt"] = self.prepare(original, "generic-prompt", "authorization", "sdd-receipt-v1",
            {key: gate[key] for key in ("prompt_id", "development_plan_hash", "approved_baseline_id")})
        checker = self.checker()
        checker.authorization()
        self.assertIn("does not authorize", checker.issues[0]["detail"])

    def test_current_unit_evidence_ref_keeps_exact_execution_bindings(self):
        self.p.authorize()
        self.p.execute_checks()
        check = self.m["verification"]["checks"][0]
        checker = self.checker()
        bindings = checker.check_bindings(check)
        check["evidence"][0] = self.replace(check["evidence"][0], "unit-current", "visual", bindings, "evidence-json-v1")
        # The fixture used one legacy file for both logical observations; preserve the second association as its own ref.
        check["evidence"][1] = self.prepare({"synthetic_fixture": True}, "unit-integration", "integration", "evidence-json-v1", bindings)
        self.assertEqual("passed", self.checker().run("implementation")["result"])
        check["executed_at"] = "2026-08-20T10:05:30Z"
        report = self.checker().run("implementation")
        self.assertNotEqual("passed", report["result"])
        self.assertTrue(any("evidence binding: executed_at" in issue["detail"] for issue in report["issues"]))

    def test_shared_source_inventory_expands_exact_hashes_and_retains_containment(self):
        entry = self.m["artifacts"]["development-plan"]
        original = copy.deepcopy(entry["source_hashes"])
        entry["source_inventory_ref"] = self.prepare({"version": 1, "source_hashes": original}, "shared-sources", "source_inventory", "source-inventory-v1")
        entry.pop("source_hashes")
        checker = self.checker()
        checker.sources(entry, "development-plan", checker.specs["development-plan"]["required_before"])
        checker.source_usage(entry, "development-plan", checker.specs["development-plan"]["required_before"])
        self.assertFalse(checker.issues, checker.issues)
        self.assertEqual(original, checker.source_inventory(entry)[0])
        entry["source_hashes"] = {"docs/prd.md": "0" * 64}
        with self.assertRaisesRegex(ValueError, "differ"):
            self.checker().source_inventory(entry)
        entry.pop("source_hashes")
        entry["source_inventory_ref"] = self.prepare({"version": 1, "source_hashes": {"/external/source": "0" * 64}}, "unsafe-sources", "source_inventory", "source-inventory-v1")
        with self.assertRaisesRegex(ValueError, "escapes project"):
            self.checker().source_inventory(entry)

    def test_archived_visual_target_and_approval_keep_canonical_baseline(self):
        baseline = self.m["active_baseline"]
        baseline["visual_target_ref"] = self.replace({"path": baseline["visual_target_path"]}, "visual-target", "visual", {}, "evidence-bytes-v1")
        baseline.pop("visual_target_path")
        receipt = baseline["approval_receipt"]
        baseline["approval_receipt"] = self.replace(receipt, "approved-original", "approval",
            {key: baseline[key] for key in ("baseline_id", "visual_target_hash", "prototype_tree_hash")})
        path = "docs/design-brief.md"
        self.p.write(path, (self.p.root / path).read_text().replace(receipt["path"], "approved-original"))
        checker = self.checker()
        checker.baseline()
        self.assertFalse(checker.issues, checker.issues)

    def test_current_state_does_not_require_loading_superseded_payloads(self):
        self.m["history"].append({"evidence_ref": {"version": 999, "artifact_id": "historical-unprepared"}})
        self.assertEqual("passed", self.checker().run("development-plan", after=True)["result"])

    def test_source_path_api_does_not_accept_external_paths_or_urls(self):
        checker = self.checker()
        for path in ("https://example.invalid/evidence", "/outside", "../outside"):
            with self.assertRaises(ValueError):
                checker.path(path)
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            sdd.Checker(self.p.root, self.m, evidence_cache=self.p.root / "cache")

    def test_stable_hash_memo_is_reused_and_changes_fail(self):
        checker = self.checker()
        path = self.p.root / "docs/prd.md"
        original = sdd.hash_file
        with patch.object(sdd, "hash_file", wraps=original) as hashing:
            checker.file_hash(path)
            checker.file_hash(path)
            self.assertEqual(1, hashing.call_count)
        path.write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed during"):
            checker.file_hash(path)

    def test_real_local_manager_archive_prepare_and_checker_integration(self):
        from evidence.manager import Manager
        from evidence.policy import load_defaults
        from evidence.transports import LocalTransport
        policy = load_defaults()
        policy.update(project_id="11111111-1111-4111-8111-111111111111", store_id="22222222-2222-4222-8222-222222222222", provider="local")
        policy["limits"]["free_space_reserve_bytes"] = 0
        manager = Manager(LocalTransport(self.root / "durable"), self.root / "machine", policy)
        self.p.authorize()
        gate = self.m["implementation_gate"]
        path = self.p.root / gate["prompt_receipt"]["path"]
        original = path.read_bytes()
        refs = manager.archive({"version": 1, "files": [{"path": str(path), "original_path": gate["prompt_receipt"]["path"],
            "kind": "authorization", "schema": "sdd-receipt-v1", "sealed_at": "2026-08-20T10:02:01Z",
            "provenance": {"unit_id": "U-1", "run_id": "original-authorized-run"},
            "bindings": {key: gate[key] for key in ("prompt_id", "development_plan_hash", "approved_baseline_id")},
            "protections": ["authorization"]}]}, remove_local=True)
        self.assertFalse(path.exists())
        gate["prompt_receipt"] = {"evidence_ref": refs[0]}
        self.p.write("forge/evidence-policy.json", json.dumps(policy))
        self.m["evidence_accounting"] = {"version": 1, "project_id": policy["project_id"],
            "policy_sha256": self.p.hash("forge/evidence-policy.json"), "runs": {"original-authorized-run": {
                "unit_id": "U-1", "status": "complete", "gross_generated_bytes": len(original), "original_logical_files": 1,
                "pending_reservations": 0, "unreconciled_outputs": 0}}}
        prepared = manager.prepare(refs)
        checker = sdd.Checker(self.p.root, self.m, evidence_cache=prepared)
        checker.authorization()
        self.assertFalse(checker.issues, checker.issues)
        self.assertEqual(original, checker.evidence_resolver.resolve(refs[0]).read_bytes())
        # A cold manager proves restoration is independent of the original checkout/database.
        cold = Manager(LocalTransport(self.root / "durable"), self.root / "cold-machine", policy)
        cold_cache = cold.prepare(refs)
        self.assertEqual(original, EvidenceResolver(cold_cache).resolve(refs[0]).read_bytes())

    def test_split_file_resolver_checks_offsets_and_actual_segment_hashes(self):
        content = b"first-halfsecond-half"
        ref = self.prepare(content, "split-original", "attachment", "archive-attachment-v1")
        chunks = [content[:10], content[10:]]
        segments, proofs, offset = [], [], 0
        for index, chunk in enumerate(chunks):
            segment = {"object_id": "split-pack-" + str(index), "pack_sha256": str(index + 1) * 64,
                "pack_size": 1000, "member": "pieces/" + str(index), "offset": offset,
                "length": len(chunk), "sha256": sdd.digest(chunk)}
            segments.append(segment)
            proofs.append({"object_id": segment["object_id"], "sha256": segment["pack_sha256"], "size": 1000,
                "members": [{"artifact_id": ref["artifact_id"], "member": segment["member"], "sha256": segment["sha256"], "size": len(chunk)}]})
            offset += len(chunk)
        ref["locator"] = {"provider": "local", "store_id": "synthetic-store", "segments": segments}
        receipt_path = self.cache / "receipts" / "split-original.json"
        receipt_path.write_text(json.dumps({**ref, "verified_archive": proofs}))
        self.assertEqual(content, EvidenceResolver(self.cache).resolve(ref).read_bytes())
        segments[1]["sha256"] = "0" * 64
        proofs[1]["members"][0]["sha256"] = "0" * 64
        receipt_path.write_text(json.dumps({**ref, "verified_archive": proofs}))
        with self.assertRaisesRegex(ValueError, "segment bytes mismatch"):
            EvidenceResolver(self.cache).resolve(ref)
        segments[1]["offset"] = 3
        with self.assertRaisesRegex(ValueError, "contiguously"):
            EvidenceResolver(self.cache).resolve(ref)

    def test_nested_screenshot_reference_is_part_of_current_receipt_closure(self):
        screenshot = self.prepare(b"synthetic pixels", "screen", "visual", "evidence-bytes-v1")
        receipt = self.prepare({"screenshots": [{"evidence_ref": screenshot}]}, "browser", "browser", "sdd-receipt-v1")
        resolver = EvidenceResolver(self.cache)
        resolver.resolve(receipt)
        (self.cache / "objects" / screenshot["sha256"]).unlink()
        with self.assertRaisesRegex(ValueError, "missing/unreadable"):
            EvidenceResolver(self.cache).resolve(receipt)

    def test_missing_stale_and_unreconciled_accounting_block_new_claims(self):
        ref = self.prepare({"synthetic": True})
        original = copy.deepcopy(self.m["evidence_accounting"])
        cases = [None, {**original, "policy_sha256": "0" * 64}]
        for missing in cases:
            self.m["evidence_accounting"] = missing
            self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))
        for field, value in (("pending_reservations", 1), ("unreconciled_outputs", 1), ("original_logical_files", 0), ("gross_generated_bytes", 0)):
            self.m["evidence_accounting"] = copy.deepcopy(original)
            self.m["evidence_accounting"]["runs"][ref["provenance"]["run_id"]][field] = value
            with self.subTest(field=field):
                self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))
        # Existing contained evidence has no mandatory migration or fabricated accounting.
        self.m.pop("evidence_accounting")
        record = self.p.evidence("forge/old.json", {"synthetic": True})
        self.assertTrue(self.checker().evidence_snapshot(record, "qa-checklist"))

    def test_imported_existing_accounting_preserves_original_provenance_without_generation(self):
        ref = self.prepare({"synthetic": True})
        original_provenance = copy.deepcopy(ref["provenance"])
        ref["retention"]["imported"] = True
        ref["retention"]["migration_policy_established"] = False
        self.receipt(ref)
        row = self.m["evidence_accounting"]["runs"][ref["provenance"]["run_id"]]
        row.update(mode="imported-existing", gross_generated_bytes=0, original_logical_files=0)
        self.assertTrue(self.checker().evidence_snapshot(ref, "qa-checklist"))
        self.assertEqual(original_provenance, ref["provenance"])
        ref["retention"].pop("imported")
        self.receipt(ref)
        self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))

    def test_archived_browser_and_source_access_records_use_original_semantic_checks(self):
        self.p.candidates(claude=True)
        handoff = self.m["design_execution"]
        for stem in ("source_manifest", "codex_access_receipt", "claude_source_read_receipt"):
            handoff[stem + "_ref"] = self.replace({"path": handoff.pop(stem + "_path")}, stem, "source_access", {})
        candidate = self.m["prototype_candidates"][0]
        bindings = {key: candidate[key] for key in ("candidate_id", "version", "visual_target_hash", "prototype_tree_hash", "preview_url")}
        candidate["browser_receipt"] = {"evidence_ref": self.replace(candidate["browser_receipt"], "browser-original", "browser", bindings)}
        checker = self.checker()
        checker.source_access()
        checker.candidates()
        self.assertFalse(checker.issues, checker.issues)
        candidate["version"] = "later-version"
        checker = self.checker()
        checker.candidates()
        self.assertTrue(any("evidence binding: version" in issue["detail"] for issue in checker.issues), checker.issues)

    def test_evidence_storage_declared_completion_requires_accounted_stable_run(self):
        self.p.authorize()
        self.p.execute_checks()
        self.m["evidence_storage"] = {"policy_path": "forge/evidence-policy.json"}
        report = self.checker().run("implementation")
        self.assertNotEqual("passed", report["result"])
        self.assertTrue(any("accounting identities" in issue["detail"] for issue in report["issues"]), report)
        run = self.m["unit_runs"]["U-1"]
        run["run_id"] = "managed-current-run"
        self.m["evidence_accounting"]["runs"][run["run_id"]] = {"unit_id": "U-1", "status": "complete", "gross_generated_bytes": 10000,
            "original_logical_files": 4, "pending_reservations": 0, "unreconciled_outputs": 0}
        self.assertEqual("passed", self.checker().run("implementation")["result"])

    def test_linked_cache_parent_is_rejected(self):
        ref = self.prepare({"synthetic": True})
        alias = self.root / "linked"
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(ValueError, "linked|link"):
            EvidenceResolver(alias / "cache").resolve(ref)

    def test_shared_inventory_and_receipt_parsing_are_reused(self):
        entry = self.m["artifacts"]["development-plan"]
        ref = self.prepare({"version": 1, "source_hashes": entry["source_hashes"]}, "inventory-memo", "source_inventory", "source-inventory-v1")
        resolver = EvidenceResolver(self.cache)
        import evidence.resolver as module
        with patch.object(module, "read_json", wraps=module.read_json) as parsing:
            resolver.json(ref)
            resolver.json(ref)
            self.assertEqual(2, parsing.call_count)  # One receipt and one payload.

    def test_mutation_after_validation_blocks_final_current_claim(self):
        checker = self.checker()
        original = checker._run
        def mutate_after(*args, **kwargs):
            report = original(*args, **kwargs)
            self.p.write("docs/prd.md", "Changed after its integrity snapshot.")
            return report
        with patch.object(checker, "_run", side_effect=mutate_after):
            report = checker.run("development-plan", after=True)
        self.assertEqual("blocked", report["result"])
        self.assertTrue(any(issue["code"] == "changing_input" for issue in report["issues"]))

    def test_new_file_in_frozen_tree_after_validation_blocks_final_claim(self):
        self.p.authorize()
        checker = self.checker()
        original = checker._run
        def mutate_after(*args, **kwargs):
            report = original(*args, **kwargs)
            self.p.write("forge/design/candidates/a/v1/added-after-validation.txt", "changed tree")
            return report
        with patch.object(checker, "_run", side_effect=mutate_after):
            report = checker.run("implementation")
        self.assertEqual("blocked", report["result"])
        self.assertTrue(any("prototype directory changed" in issue["detail"] for issue in report["issues"]))

    def test_multiple_check_associations_do_not_recharge_one_original_logical_file(self):
        first = self.prepare({"synthetic": True}, "logical-first", "visual")
        first["original_path"] = "generated/original.json"
        self.receipt(first)
        second = copy.deepcopy(first)
        second.update(artifact_id="logical-second", kind="integration")
        self.receipt(second)
        row = self.m["evidence_accounting"]["runs"][first["provenance"]["run_id"]]
        row.update(gross_generated_bytes=first["size"], original_logical_files=1)
        checker = self.checker()
        self.assertTrue(checker.evidence_snapshot(first, "qa-checklist"))
        self.assertTrue(checker.evidence_snapshot(second, "qa-checklist"))
        second["original_path"] = "generated/different-original.json"
        self.receipt(second)
        checker = self.checker()
        self.assertTrue(checker.evidence_snapshot(first, "qa-checklist"))
        self.assertFalse(checker.evidence_snapshot(second, "qa-checklist"))

    def test_cache_parent_link_replacement_cannot_hide_behind_hash_memo(self):
        ref = self.prepare({"synthetic": True})
        resolver = EvidenceResolver(self.cache)
        resolver.resolve(ref)
        old = self.root / "original-cache"
        self.cache.rename(old)
        try:
            self.cache.symlink_to(old, target_is_directory=True)
        except OSError:
            old.rename(self.cache)
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(ValueError, "link"):
            resolver.resolve(ref)

    def test_shared_json_reference_dag_scales_with_unique_prepared_artifacts(self):
        leaf = self.prepare({"observations": []}, "dag-leaf")
        previous = leaf
        depth = 24
        for number in range(depth):
            previous = self.prepare({"observations": [{"evidence_ref": previous}, {"evidence_ref": previous}]}, "dag-" + str(number))
        resolver = EvidenceResolver(self.cache)
        with patch.object(resolver, "_resolve", wraps=resolver._resolve) as resolving:
            resolver.resolve(previous)
            self.assertLessEqual(resolving.call_count, 2 * depth + 1)
        self.assertEqual(depth + 1, len(resolver.visited))
        (self.cache / "objects" / leaf["sha256"]).unlink()
        with self.assertRaisesRegex(ValueError, "missing/unreadable"):
            resolver.resolve(previous)

    def test_current_wrapper_sibling_capture_is_required_reference_closure(self):
        present = self.prepare({"observed": True}, "present")
        screenshot = self.prepare(b"synthetic pixels", "required-sibling", "visual", "evidence-bytes-v1")
        receipt = self.prepare({"observations": [{"evidence_ref": present, "screenshots": [{"evidence_ref": screenshot}]}]}, "sibling-browser", "browser", "sdd-receipt-v1")
        EvidenceResolver(self.cache).resolve(receipt)
        (self.cache / "objects" / screenshot["sha256"]).unlink()
        with self.assertRaisesRegex(ValueError, "missing/unreadable"):
            EvidenceResolver(self.cache).resolve(receipt)

    def test_empty_or_malformed_storage_declaration_cannot_disable_accounting(self):
        self.p.authorize()
        self.p.execute_checks()
        for declaration in ({}, None, False, []):
            self.m["evidence_storage"] = declaration
            with self.subTest(declaration=declaration):
                self.assertNotEqual("passed", self.checker().run("implementation")["result"])
        self.m.pop("evidence_storage")
        self.assertEqual("passed", self.checker().run("implementation")["result"])
