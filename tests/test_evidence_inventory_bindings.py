"""Shared source inventories compact bindings without refreshing execution observations."""
from copy import deepcopy
from pathlib import Path
import unittest

import test_evidence_checker as fixtures
from test_sdd_check import sdd


class InventoryBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EvidenceCheckerTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.p, self.m = self.fixture.p, self.fixture.m
        self.p.authorize()
        self.p.execute_checks()
        self.hashes = deepcopy(self.m["verification"]["checks"][0]["evaluated_source_hashes"])
        self.inventory = self.fixture.prepare({"version": 1, "source_hashes": self.hashes}, "shared-current-inventory", "source_inventory", "source-inventory-v1")
        self.checks = self.m["verification"]["checks"]
        for check in self.checks:
            check["source_inventory_ref"] = self.inventory
            check.pop("evaluated_source_hashes")
        self.evidence = []
        for check in self.checks:
            bindings = self.fixture.checker().check_bindings(check)
            captures = []
            for number, legacy in enumerate(check["evidence"]):
                content = (self.p.root / legacy["path"]).read_bytes()
                ref = self.fixture.prepare(content, check["check_id"] + "-capture-" + str(number), legacy["kind"], "evidence-json-v1", deepcopy(bindings))
                ref["original_path"] = legacy["path"]
                ref["dependencies"] = [self.inventory]
                self.fixture.receipt(ref)
                captures.append(ref)
                self.evidence.append(ref)
            check["evidence"] = captures

    def report(self):
        return self.fixture.checker().run("implementation")

    def blocked(self, text):
        report = self.report()
        self.assertNotEqual("passed", report["result"], report)
        self.assertTrue(any(text in issue["detail"] for issue in report["issues"]), report)

    def update_receipt(self, ref):
        self.fixture.receipt(ref)

    def test_compact_bindings_pass_whole_implementation_and_prefer_shared_hash_for_authoring(self):
        self.assertEqual("passed", self.report()["result"])
        for check in self.checks:
            expected = self.fixture.checker().check_bindings(check)
            self.assertEqual(self.inventory["sha256"], expected["evaluated_source_inventory_sha256"])
            self.assertNotIn("evaluated_source_hashes", expected)
            self.assertEqual("2026-08-20T10:05:00Z", expected["executed_at"])
        self.assertEqual("2026-08-20T10:06:00Z", self.m["unit_runs"]["U-1"]["completed_at"])

    def test_stale_or_replaced_inventory_hash_cannot_refresh_pass(self):
        changed = self.fixture.prepare({"version": 1, "source_hashes": self.hashes, "metadata": "different original inventory bytes"},
            "new-inventory", "source_inventory", "source-inventory-v1")
        self.checks[0]["source_inventory_ref"] = changed
        self.blocked("source-inventory dependency")
        # Even when replacement is in closure, old bindings retain the original inventory hash.
        self.evidence[0]["dependencies"] = [changed]
        self.update_receipt(self.evidence[0])
        self.blocked("evidence binding: evaluated_source_inventory_sha256")

    def test_live_source_changes_still_block_when_inventory_bytes_and_bindings_match(self):
        self.p.write("src/app.txt", "Changed after original execution.")
        self.blocked("src/app.txt")

    def test_compact_binding_requires_inventory_in_its_own_verified_closure(self):
        # The declared inventory was already prepared and validated for the check.
        self.evidence[0].pop("dependencies")
        self.update_receipt(self.evidence[0])
        self.blocked("verified source-inventory dependency")

    def test_corrupt_or_missing_inventory_bytes_block_current_claim(self):
        path = self.fixture.cache / "objects" / self.inventory["sha256"]
        original = path.read_bytes()
        path.write_bytes(b"corrupt source inventory")
        self.blocked("hash/size mismatch")
        path.write_bytes(original)
        path.unlink()
        self.blocked("missing/unreadable")

    def test_full_legacy_bindings_remain_valid_with_or_without_shared_inventory(self):
        for evidence in self.evidence:
            evidence["bindings"].pop("evaluated_source_inventory_sha256")
            evidence["bindings"]["evaluated_source_hashes"] = deepcopy(self.hashes)
            evidence.pop("dependencies")
            self.update_receipt(evidence)
        self.assertEqual("passed", self.report()["result"])
        for check in self.checks:
            check.pop("source_inventory_ref")
            check["evaluated_source_hashes"] = deepcopy(self.hashes)
        self.assertEqual("passed", self.report()["result"])

    def test_both_binding_forms_must_match_identical_expanded_map(self):
        evidence = self.evidence[0]
        evidence["bindings"]["evaluated_source_hashes"] = deepcopy(self.hashes)
        self.update_receipt(evidence)
        self.assertEqual("passed", self.report()["result"])
        evidence["bindings"]["evaluated_source_hashes"]["src/app.txt"] = "0" * 64
        self.update_receipt(evidence)
        self.blocked("evidence binding: evaluated_source_hashes")

    def test_inline_and_shared_source_maps_cannot_disagree(self):
        self.checks[0]["evaluated_source_hashes"] = {"src/app.txt": "0" * 64}
        self.blocked("inline and shared source inventory differ")

    def test_compact_binding_without_declared_inventory_blocks(self):
        self.checks[0].pop("source_inventory_ref")
        self.checks[0]["evaluated_source_hashes"] = deepcopy(self.hashes)
        self.blocked("requires a declared source inventory")

    def test_transitive_verified_inventory_dependency_is_valid(self):
        bridge = self.fixture.prepare({"source_inventory": {"evidence_ref": self.inventory}}, "inventory-bridge", "receipt", "sdd-receipt-v1")
        self.evidence[0]["dependencies"] = [bridge]
        self.update_receipt(self.evidence[0])
        self.assertEqual("passed", self.report()["result"])

    def test_changed_plan_or_execution_time_remains_stale_with_compact_inventory(self):
        self.checks[0]["evaluated_plan_hash"] = "e" * 64
        self.blocked("evaluated_plan_hash")
        self.checks[0]["evaluated_plan_hash"] = self.p.hash("docs/development-plan.md")
        self.checks[0]["executed_at"] = "2026-08-20T10:05:30Z"
        self.blocked("evidence binding: executed_at")

    def test_compact_binding_size_does_not_repeat_large_source_map(self):
        import json
        hashes = {**self.hashes, **{"src/synthetic-" + str(i) + ".txt": "a" * 64 for i in range(1000)}}
        inventory = self.fixture.prepare({"version": 1, "source_hashes": hashes}, "large-shared-map", "source_inventory", "source-inventory-v1")
        check = self.checks[0]
        check["source_inventory_ref"] = inventory
        compact = self.fixture.checker().check_bindings(check)
        full = {**compact, "evaluated_source_hashes": hashes}
        full.pop("evaluated_source_inventory_sha256")
        self.assertLess(len(json.dumps(compact).encode()), 1024)
        self.assertGreater(len(json.dumps(full).encode()), 80000)
        self.assertNotIn("evaluated_source_hashes", compact)
        # Authoring compact metadata cannot turn the synthetic absent live paths into acceptance.
        self.blocked("source-inventory dependency")
