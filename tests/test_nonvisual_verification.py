"""Synthetic nonvisual verification records, not product or participant tests."""
import copy
import unittest

import test_audit_regressions as fixtures
from test_sdd_check import sdd


class NonvisualVerificationTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.AuditRegressions("test_headless_plan_has_no_fabricated_ui_documents_or_approval")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture, self.p, self.m = fixture, fixture.p, fixture.m
        self.allocations = copy.deepcopy(self.m["unit_plan"]["acceptance"])

    def nonvisual(self, gate_id):
        gate = next(item for item in self.m["verification"]["gates"] if item["gate_id"] == gate_id)
        check = next(item for item in self.m["verification"]["checks"] if item["gate_id"] == gate_id)
        gate.update(applicability="applicable", required=True)
        gate.pop("rationale", None)
        check.update(execution_status="not_run", interaction_scope={
            "kind": "nonvisual", "context": "Operator command, text result and error recovery.",
            "rationale": "The required operator task needs an observed nonvisual interaction review."})
        check.pop("rationale", None)
        for field in ("route", "state", "viewport", "baseline_id", "target_hash"):
            check.pop(field, None)
        key = check["check_id"]
        self.m["unit_plan"]["acceptance"][key] = copy.deepcopy(self.allocations[key])
        self.m["unit_plan"]["acceptance"][key]["obligation_ids"] = [
            item for item in self.allocations[key]["obligation_ids"] if item != "STATE-01"]
        required = self.m["unit_plan"]["units"]["U-1"]["required_check_ids"]
        if key not in required:
            required.append(key)
        path = "docs/qa-checklist.md"
        text = (self.p.root / path).read_text()
        self.p.write(path, text.replace("## Checks\n", "## Checks\n" + key + ": " +
            check["interaction_scope"]["context"] + " " + check["interaction_scope"]["rationale"] + "\n", 1))
        self.p.sync_unit_contract()
        return check

    def verification_issues(self, baseline_required=True, release=False):
        checker = sdd.Checker(self.p.root, self.m)
        checker.verification(release=release, baseline_required=baseline_required)
        return checker.issues

    def assert_code(self, code, **kwargs):
        issues = self.verification_issues(**kwargs)
        self.assertIn(code, {item["code"] for item in issues}, issues)

    def test_headless_observed_tasks_and_heuristics_need_no_visual_artifacts(self):
        self.fixture.headless()
        for gate_id in ("heuristic_usability_review", "representative_user_task_validation"):
            self.nonvisual(gate_id)
        report = self.p.run(after=True)
        self.assertEqual("passed", report["result"], report)
        self.assertNotIn("design-brief", report["checked_artifacts"])
        self.assertIsNone(self.m["approved_baseline_id"])
        self.assertEqual("not_evaluated", self.m["verification"]["release_readiness"])
        self.assertTrue(all(item["execution_status"] in ("not_run", "not_applicable")
                            for item in self.m["verification"]["checks"]))
        self.assertIn("implementation_not_authorized", {
            item["code"] for item in self.p.run("implementation")["issues"]})

    def test_nonvisual_task_can_coexist_with_visual_product_checks(self):
        self.nonvisual("representative_user_task_validation")
        report = self.p.run(after=True)
        self.assertEqual("passed", report["result"], report)

    def test_headless_checks_cannot_invent_visual_scope_instead(self):
        self.fixture.headless()
        check = self.nonvisual("representative_user_task_validation")
        del check["interaction_scope"]
        check.update(route="invented", state="invented", viewport="invented")
        self.assert_code("contradictory_applicability", baseline_required=False)

    def test_nonvisual_scope_requires_explicit_valid_metadata(self):
        check = self.nonvisual("representative_user_task_validation")
        original = copy.deepcopy(check["interaction_scope"])
        for value in (False, [], {}, {"kind": "visual"}, {"kind": "unknown"},
                      {**original, "context": ""}, {**original, "rationale": ""},
                      {**original, "context": []}, {**original, "rationale": False}):
            with self.subTest(value=value):
                check["interaction_scope"] = value
                self.assert_code("invalid_check_scope")

    def test_nonvisual_context_and_rationale_must_exist_in_canonical_qa(self):
        check = self.nonvisual("representative_user_task_validation")
        for field in ("context", "rationale"):
            with self.subTest(field=field):
                original = check["interaction_scope"][field]
                check["interaction_scope"][field] = "Unreviewed metadata-only claim."
                self.assert_code("invalid_check_scope")
                check["interaction_scope"][field] = original

    def test_nonvisual_still_requires_task_and_user_group(self):
        check = self.nonvisual("representative_user_task_validation")
        for field in ("task", "user_group"):
            with self.subTest(field=field):
                original = check.pop(field)
                self.assert_code("missing_check_scope")
                check[field] = original

    def test_visual_fidelity_cannot_use_nonvisual_scope(self):
        self.nonvisual("approved_visual_baseline_fidelity")
        self.assert_code("invalid_check_scope")

    def test_headless_visual_gate_remains_inapplicable(self):
        self.fixture.headless()
        gate = next(item for item in self.m["verification"]["gates"]
                    if item["gate_id"] == "approved_visual_baseline_fidelity")
        gate.update(applicability="applicable", required=True)
        self.assert_code("contradictory_applicability", baseline_required=False)

    def test_legacy_visual_bindings_and_scope_remain_required(self):
        self.assertEqual([], self.verification_issues())
        for gate_id in sdd.GATE_KINDS:
            check = next(item for item in self.m["verification"]["checks"] if item["gate_id"] == gate_id)
            for field in ("route", "state", "viewport"):
                with self.subTest(gate_id=gate_id, field=field):
                    original = check.pop(field)
                    self.assert_code("missing_check_scope")
                    check[field] = original
            original = check["target_hash"]
            check["target_hash"] = "0" * 64
            self.assert_code("stale_check_binding")
            check["target_hash"] = original

    def test_nonvisual_execution_keeps_distinct_evidence_classes(self):
        self.fixture.headless()
        checks = [self.nonvisual(gate) for gate in
                  ("heuristic_usability_review", "representative_user_task_validation")]
        excluded = {item["check_id"] for item in self.m["verification"]["checks"]
                    if item["execution_status"] == "not_applicable"}
        self.p.execute_checks()
        for item in self.m["verification"]["checks"]:
            if item["check_id"] in excluded:
                item.update(execution_status="not_applicable", evidence=[], rationale="Outside declared scope.")
        self.assertEqual([], self.verification_issues(baseline_required=False, release=True))
        for check in checks:
            with self.subTest(gate_id=check["gate_id"]):
                original = copy.deepcopy(check["evidence"])
                for item in check["evidence"]:
                    item["kind"] = "visual"
                self.assert_code("wrong_evidence_class", baseline_required=False, release=True)
                check["evidence"] = original

    def test_required_nonvisual_checks_and_heuristics_cannot_be_skipped(self):
        self.fixture.headless()
        check = self.nonvisual("heuristic_usability_review")
        self.assert_code("required_check_incomplete", baseline_required=False, release=True)
        check["heuristic_ids"].remove("H10")
        self.assert_code("heuristic_coverage", baseline_required=False)


if __name__ == "__main__":
    unittest.main()
