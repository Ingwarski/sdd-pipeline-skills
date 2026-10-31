"""Existing contract-2 transitions using isolated synthetic history, not product QA."""
import copy
import json
import sys
import unittest

import test_unit_history as fixture


class Contract3AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture.UnitHistoryTests("test_version_one_retains_original_acceptance_and_plan_binding_rules")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.p, self.m = self.base.p, self.base.m
        self.m.update(checker_contract_version=2, unit_contract_version=2)
        self.h = self.base.history()
        self.p.save()

    def activate(self, candidate):
        active = self.p.root / "forge/sdd-manifest.json"
        before = active.read_bytes()
        expected = self.p.hash("forge/sdd-manifest.json")
        staged = self.h.stage_candidate(self.p.root, candidate, expected)
        self.assertEqual(before, active.read_bytes())
        result = self.h.activate_candidate(self.p.root, staged, expected)
        self.assertEqual("activated", result["status"])
        self.assertEqual("passed", result["report"]["result"], result)
        self.m.clear()
        self.m.update(json.loads(active.read_text()))
        self.assertEqual((3, 3), (self.m["checker_contract_version"], self.m["unit_contract_version"]))
        return result

    def candidate(self):
        candidate = copy.deepcopy(self.m)
        candidate.update(checker_contract_version=3, unit_contract_version=3)
        return candidate

    def prepare_start(self, unit):
        context = self.h.capture_context(self.p.root, self.m, unit, self.base.inventory(unit=unit))
        self.m.setdefault("execution_contexts", {})[unit] = context
        report = self.base.report("implementation", "start", unit)
        self.assertEqual("passed", report["result"], report)

    def test_pending_adoption_preserves_authority_and_creates_no_execution(self):
        original = copy.deepcopy(self.m)
        self.activate(self.candidate())
        self.assertEqual(original["implementation_gate"], self.m["implementation_gate"])
        for field in ("verification", "unit_plan", "unit_runs", "execution_contexts"):
            self.assertEqual(original.get(field), self.m.get(field), field)
        self.prepare_start("U-1")
        self.base.assert_blocked(self.base.report("implementation", "complete", "U-1"))

    def test_interrupted_adoption_preserves_attempt_and_requires_fresh_checks(self):
        self.h, inventory, context, _ = self.base.capture_alpha(finish=False)
        run = self.m["unit_runs"]["U-1"]
        run["run_id"] = "synthetic-contract2-run"
        self.base.fixture.evidence("U-1", 4)
        self.base.stamp_evidence(self.h, "U-1", inventory)
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        check["run_id"] = run["run_id"]
        attempt = self.h.capture_attempt(self.p.root, self.m, "U-1", context, run["run_id"], "interrupted", self.base.inventory())
        run["attempt_ref"] = attempt
        self.p.save()
        original_gate = copy.deepcopy(self.m["implementation_gate"])
        original_check = copy.deepcopy(check)
        original_attempt = (self.p.root / attempt["path"]).read_bytes()
        original_code = (self.p.root / "src/alpha.txt").read_bytes()
        runtime = self.h.observe_runtime(self.p.root, {"runtime": [sys.executable, "--version"]})
        reviewed = self.base.inventory(environment=self.base.read(runtime)["environment"])
        reviewed["runtime_observation_ref"] = runtime
        continued = self.h.capture_continuation(self.p.root, self.candidate(), "U-1", attempt,
                                               "synthetic-contract3-run", reviewed)
        self.activate(continued["manifest"])
        current = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        self.assertEqual("not_run", current["execution_status"])
        self.assertNotIn("evidence", current)
        self.assertEqual([attempt], self.m["attempt_history"]["U-1"])
        self.assertEqual(original_check, self.base.read(attempt)["checks"][0])
        self.assertEqual(original_attempt, (self.p.root / attempt["path"]).read_bytes())
        self.assertEqual(original_code, (self.p.root / "src/alpha.txt").read_bytes())
        self.assertEqual(original_gate, self.m["implementation_gate"])
        self.assertEqual("passed", self.base.report("implementation", "start", "U-1")["result"])
        self.base.assert_blocked(self.base.report("implementation", "complete", "U-1"))
        self.base.assert_blocked(self.base.report("implementation", "start", "U-2"))

    def test_unused_context_is_replaced_without_inventing_an_attempt(self):
        old_context = self.h.capture_context(self.p.root, self.m, "U-1", self.base.inventory())
        old_bytes = (self.p.root / old_context["path"]).read_bytes()
        self.m.setdefault("execution_contexts", {})["U-1"] = old_context
        self.p.save()
        candidate = self.candidate()
        new_context = self.h.capture_context(self.p.root, candidate, "U-1", self.base.inventory())
        candidate["execution_contexts"]["U-1"] = new_context
        self.activate(candidate)
        self.assertNotEqual(old_context, new_context)
        self.assertEqual(old_bytes, (self.p.root / old_context["path"]).read_bytes())
        self.assertFalse(self.m.get("attempt_history"))
        self.assertFalse(self.m.get("unit_runs"))
        report = self.base.report("implementation", "start", "U-1")
        self.assertEqual("passed", report["result"], report)

    def test_completed_adoption_preserves_applicable_whole_unit_history(self):
        self.h, inventory, context, completion = self.base.capture_alpha()
        original = (self.p.root / completion["path"]).read_bytes()
        authority = copy.deepcopy(self.m["implementation_gate"])
        candidate = self.candidate()
        assessment = self.h.assess_completion(self.p.root, candidate, completion, self.base.inventory(), {})
        self.assertEqual("applicable", self.base.read(assessment)["outcome"])
        candidate["unit_runs"]["U-1"]["applicability_ref"] = assessment
        self.activate(candidate)
        self.assertEqual(completion, self.m["unit_runs"]["U-1"]["completion_ref"])
        self.assertEqual(original, (self.p.root / completion["path"]).read_bytes())
        self.assertEqual(authority, self.m["implementation_gate"])
        self.prepare_start("U-2")

    def test_completed_dependency_review_requires_revalidation_without_rewriting_history(self):
        self.h, inventory, context, completion = self.base.capture_alpha()
        original = (self.p.root / completion["path"]).read_bytes()
        self.m.update(checker_contract_version=3, unit_contract_version=3)
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        check["acceptance"]["dependency_review"] = {
            "complete": True, "reviewer": "synthetic dependency owner",
            "rationale": "Reviewed the component's complete code and test dependency scope."}
        self.p.sync_unit_contract()
        assessment = self.h.assess_completion(self.p.root, self.m, completion, self.base.inventory(), {})
        self.assertEqual("needs_revalidation", self.base.read(assessment)["outcome"])
        self.assertTrue(any("QA-02" in reason for reason in self.base.read(assessment)["reasons"]))
        self.m["unit_runs"]["U-1"]["applicability_ref"] = assessment
        # A valid plan can retain an inapplicable completion; activation cannot
        # make that old result satisfy completion or dependent execution.
        self.activate(copy.deepcopy(self.m))
        report = self.base.report()
        self.assertEqual("needs_revalidation", report["unit_history"]["units"]["U-1"]["current_applicability"])
        self.base.assert_blocked(self.base.report("implementation", "start", "U-2"))
        self.m.setdefault("completion_history", {})["U-1"] = [completion]
        self.m["unit_runs"]["U-1"] = {"status": "pending"}
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        for field in self.h.EXECUTION_KEYS:
            if field != "findings":
                check.pop(field, None)
        check["execution_status"] = "not_run"
        self.m.get("execution_contexts", {}).pop("U-1", None)
        self.activate(copy.deepcopy(self.m))
        self.assertEqual([completion], self.m["completion_history"]["U-1"])
        self.assertEqual(original, (self.p.root / completion["path"]).read_bytes())
        self.base.assert_blocked(self.base.report("implementation", "complete", "U-1"))


if __name__ == "__main__":
    unittest.main()
