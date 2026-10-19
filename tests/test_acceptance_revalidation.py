"""Carry-forward needs explicit current review and immutable original acceptance."""
import copy
import json
import unittest

import test_unit_execution as unit_fixtures
from test_sdd_check import sdd
from revalidation_fixture import preserve_context, fresh_plan_authorization, record_review


class AcceptanceRevalidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = unit_fixtures.UnitExecutionTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.p, self.m = self.fixture.p, self.fixture.m
        self.fixture.complete("U-1", 3)
        self.context = preserve_context(self.p, "U-1", sdd.Checker(self.p.root, self.m))
        self.p.write("docs/development-plan.md", (self.p.root / "docs/development-plan.md").read_text() + "\nReviewed clarification; execution contract unchanged.\n")
        fresh_plan_authorization(self.p)

    def review(self, **changes):
        return record_review(self.p, "U-1", self.context, sdd.Checker(self.p.root, self.m), changes=changes)

    def report(self, action=None, unit=None):
        return self.fixture.report(action, unit)

    def blocked(self, fragment):
        report = self.report()
        self.assertNotEqual("passed", report["result"], report)
        self.assertTrue(any(fragment in issue["detail"] or fragment == issue["code"] for issue in report["issues"]), report)

    def test_plan_prose_review_retains_original_times_hashes_and_allows_next_start(self):
        self.review()
        self.assertEqual("passed", self.report("start", "U-2")["result"])
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        self.assertEqual(self.context["checks"]["QA-02"], {k: v for k, v in check.items() if k != "revalidation_ref"})
        self.assertEqual("2026-08-20T10:04:00Z", check["executed_at"])
        self.assertEqual("2026-08-20T10:05:00Z", self.m["unit_runs"]["U-1"]["completed_at"])

    def test_missing_review_still_blocks_old_plan_completion(self):
        self.blocked("stale run binding")

    def test_compatible_source_change_requires_complete_explicit_impact(self):
        self.p.write("src/alpha.txt", "Synthetic implementation, not product work.\n# inert comment\n")
        self.review()
        self.assertEqual("passed", self.report()["result"])
        self.review(changed_paths=[])
        self.blocked("changed paths missing")

    def test_affected_behavior_and_required_new_tests_block_retention(self):
        self.p.write("src/alpha.txt", "Different synthetic behavior.")
        event = self.review()
        event["changed_paths"][0]["behavior_changed"] = True
        self.review(changed_paths=event["changed_paths"])
        self.blocked("affected behavior")
        self.review(required_new_check_ids=["QA-02"])
        self.blocked("required new checks")
        self.review(behavior_changed=True)
        self.blocked("affected behavior")

    def test_false_missing_and_future_review_metadata_block(self):
        for change, text in (({"reviewer": ""}, "named reviewer"), ({"outcome": "unreviewed"}, "retained outcome"),
                             ({"reviewed_at": "2999-01-01T00:00:00Z"}, "future review"),
                             ({"current_plan_hash": "0" * 64}, "stale plan"),
                             ({"reviewed_at": "2026-08-20T10:00:00Z"}, "precedes original completion")):
            with self.subTest(change=change):
                self.review(**change)
                self.blocked(text)

    def test_scope_change_cannot_use_old_contract_context(self):
        self.m["unit_plan"]["units"]["U-1"]["scope"] = "Changed required behavior"
        self.p.sync_unit_contract()
        fresh_plan_authorization(self.p)
        self.review()
        self.blocked("changed work")

    def test_review_does_not_supply_new_implementation_authorization(self):
        self.review()
        self.m["implementation_gate"] = copy.deepcopy(self.context["implementation_gate"])
        self.blocked("implementation_not_authorized")

    def test_altered_original_check_run_plan_or_review_bytes_block(self):
        self.review()
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        check["executed_at"] = "2026-08-20T10:04:30Z"
        self.blocked("original check was rebound")
        check["executed_at"] = self.context["checks"]["QA-02"]["executed_at"]
        self.m["unit_runs"]["U-1"]["completed_at"] = "2026-08-20T10:06:00Z"
        self.blocked("original run was rebound")
        self.m["unit_runs"]["U-1"]["completed_at"] = self.context["unit_run"]["completed_at"]
        self.p.write(self.context["plan_source"]["path"], "Altered original plan.")
        self.blocked("original plan source is unreadable/changed")

    def test_complete_source_inventory_and_original_evidence_required(self):
        self.review(current_source_hashes={})
        self.blocked("complete identical source-path inventory")
        self.review()
        capture = self.context["checks"]["QA-02"]["evidence"][0]["path"]
        self.p.write(capture, "Altered original observation.")
        self.blocked("unit_stale_evidence")

    def test_stale_prerequisite_is_not_hidden_by_consumer_review(self):
        self.m["unit_plan"]["acceptance"]["QA-01"]["prerequisite_checks"] = ["QA-02"]
        self.fixture.sync()
        self.fixture.complete("U-1", 3)
        self.fixture.complete("U-2", 6)
        self.fixture.complete("U-3", 9)
        context = preserve_context(self.p, "U-3", sdd.Checker(self.p.root, self.m))
        self.p.write("docs/development-plan.md", (self.p.root / "docs/development-plan.md").read_text() + "\nReview only.\n")
        fresh_plan_authorization(self.p)
        record_review(self.p, "U-3", context, sdd.Checker(self.p.root, self.m))
        self.blocked("stale run binding")

    def test_original_unpassed_check_cannot_be_promoted_by_review(self):
        key = "QA-02"
        self.context["checks"][key]["execution_status"] = "not_run"
        next(item for item in self.m["verification"]["checks"] if item["check_id"] == key)["execution_status"] = "not_run"
        self.review()
        self.blocked("original passed execution required")

    def test_changed_definition_cannot_keep_claims_through_identical_clause_ids(self):
        self.review()
        self.p.write("docs/prd.md", (self.p.root / "docs/prd.md").read_text() + "\nChanged underlying behavior.\n")
        self.p.refresh(["prd"])
        self.blocked("changed acceptance-definition source")

    def test_original_required_path_omission_cannot_bypass_owner_inventory(self):
        key = "QA-02"
        self.m["unit_plan"]["units"]["U-1"]["implementation_paths"].append("src/required.txt")
        self.p.write("src/required.txt", "Synthetic omitted owner source.")
        self.p.sync_unit_contract()
        self.context["unit_plan"] = copy.deepcopy(self.m["unit_plan"])
        self.context["definition_source_hashes"] = {path: self.p.hash(path) for path in self.context["definition_source_hashes"]}
        original_path = self.context["plan_source"]["path"]
        self.p.write(original_path, (self.p.root / "docs/development-plan.md").read_text())
        original_hash = self.p.hash(original_path)
        self.context["plan_source"]["content_hash"] = original_hash
        self.context["unit_run"]["development_plan_hash"] = original_hash
        self.m["unit_runs"]["U-1"]["development_plan_hash"] = original_hash
        self.context["checks"][key]["evaluated_plan_hash"] = original_hash
        next(item for item in self.m["verification"]["checks"] if item["check_id"] == key)["evaluated_plan_hash"] = original_hash
        self.context["checks"][key]["acceptance"] = copy.deepcopy(next(item for item in self.m["verification"]["checks"] if item["check_id"] == key)["acceptance"])
        gate = self.context["implementation_gate"]
        gate["development_plan_hash"] = original_hash
        event = self.p.evidence("forge/revalidation/omitted-path-prompt.json", {
            "event": "implementation_prompt", "intent": "start_production_implementation", "role": "user", "message": "Synthetic explicit implementation prompt.",
            "development_plan_hash": original_hash, "approved_baseline_id": "B-1", "prompt_id": gate["prompt_id"], "received_at": gate["prompt_received_at"]})
        gate["prompt_receipt"] = event
        fresh_plan_authorization(self.p)
        self.review()
        self.blocked("required implementation/consumer paths")

    def test_malformed_context_and_changed_review_bytes_fail_closed(self):
        event = self.review()
        bad = self.p.evidence("forge/revalidation/not-an-object.json", [])
        self.review(original_context=bad)
        self.blocked("original context is unreadable/changed")
        self.review()
        ref = self.m["unit_runs"]["U-1"]["revalidation_ref"]
        self.p.write(ref["path"], "Changed review bytes.")
        self.blocked("unreadable or changed review receipt")

    def test_recursive_reviews_preserve_history_and_require_current_dependency_order(self):
        self.m["unit_plan"]["acceptance"]["QA-01"]["prerequisite_checks"] = ["QA-02"]
        self.fixture.sync()
        for unit, minute in (("U-1", 3), ("U-2", 6), ("U-3", 9)):
            self.fixture.complete(unit, minute)
        contexts = {unit: preserve_context(self.p, unit, sdd.Checker(self.p.root, self.m)) for unit in ("U-1", "U-2", "U-3")}
        self.p.write("docs/development-plan.md", (self.p.root / "docs/development-plan.md").read_text() + "\nEditorial revision only.\n")
        fresh_plan_authorization(self.p)
        for unit, minute in (("U-1", 22), ("U-2", 23), ("U-3", 24)):
            record_review(self.p, unit, contexts[unit], sdd.Checker(self.p.root, self.m), minute=minute)
        self.assertEqual("passed", self.report()["result"])
        record_review(self.p, "U-1", contexts["U-1"], sdd.Checker(self.p.root, self.m), minute=25)
        self.blocked("prerequisite acceptance/review is later than consumer")

    def test_construction_dependencies_also_require_earlier_current_reviews(self):
        self.fixture.sync()
        for unit, minute in (("U-1", 3), ("U-2", 6), ("U-3", 9)):
            self.fixture.complete(unit, minute)
        contexts = {unit: preserve_context(self.p, unit, sdd.Checker(self.p.root, self.m)) for unit in ("U-1", "U-2", "U-3")}
        self.p.write("docs/development-plan.md", (self.p.root / "docs/development-plan.md").read_text() + "\nEditorial revision only.\n")
        fresh_plan_authorization(self.p)
        for unit, minute in (("U-1", 25), ("U-2", 23), ("U-3", 24)):
            record_review(self.p, unit, contexts[unit], sdd.Checker(self.p.root, self.m), minute=minute)
        self.blocked("construction/acceptance prerequisite review is later")

    def original_plan_fixture(self, text):
        """Forge consistent fixture metadata to exercise canonical-source validation."""
        path = self.context["plan_source"]["path"]
        self.p.write(path, text)
        value = self.p.hash(path)
        self.context["plan_source"]["content_hash"] = value
        self.context["unit_run"]["development_plan_hash"] = value
        self.m["unit_runs"]["U-1"]["development_plan_hash"] = value
        self.context["checks"]["QA-02"]["evaluated_plan_hash"] = value
        next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")["evaluated_plan_hash"] = value
        gate = self.context["implementation_gate"]
        event = json.loads((self.p.root / gate["prompt_receipt"]["path"]).read_text())
        event["development_plan_hash"] = value
        gate["development_plan_hash"] = value
        gate["prompt_receipt"] = self.p.evidence("forge/revalidation/forged-original-prompt.json", event)

    def test_original_canonical_section_ignores_inline_decoy_and_rejects_duplicates(self):
        heading = self.m["unit_plan"]["definition_ref"]["heading"]
        current = json.dumps(self.m["unit_plan"])
        changed = copy.deepcopy(self.m["unit_plan"])
        changed["units"]["U-1"]["scope"] = "Different original behavior"
        cases = (("# Historical plan\n\nInline reference: " + heading + "\n\n```json\n" + current + "\n```\n\n" + heading + "\n\n```json\n" + json.dumps(changed) + "\n```\n", "canonical JSON and projection differ"),
                 (heading + "\n```json\n" + current + "\n```\n" + heading + "\n```json\n" + current + "\n```\n", "heading must occur exactly once"),
                 (heading + "\n```json\n" + current.replace('"policy": "strict_sequential"', '"policy": "strict_sequential", "policy": "strict_sequential"', 1) + "\n```\n", "duplicate JSON key"))
        for text, error in cases:
            with self.subTest(error=error):
                self.original_plan_fixture(text)
                self.review()
                self.blocked(error)
        self.original_plan_fixture("# Historical plan\n\nInline reference: " + heading + "\n```json\n" + json.dumps(changed) + "\n```\n" + heading + "\n```json\n" + current + "\n```\n")
        self.review()
        self.assertEqual("passed", self.report()["result"])

    def test_malformed_manifest_containers_block_instead_of_crashing(self):
        self.review()
        for key in ("unit_runs", "implementation_gate"):
            original = self.m[key]
            for value in (None, [], 7, "bad"):
                with self.subTest(key=key, value=value):
                    self.m[key] = value
                    report = self.report()
                    self.assertEqual("blocked", report["result"], report)
                    self.assertTrue(any("must be an object" in issue["detail"] or "unknown unit run" in issue["detail"] for issue in report["issues"]), report)
            self.m[key] = original
