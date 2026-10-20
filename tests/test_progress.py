"""Progress is derived from current gates, never from stale display fields."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest

from test_sdd_check import Project, SCRIPT, sdd
from progress import workflow_progress


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-progress-")
        self.addCleanup(self.temp.cleanup)
        self.p = Project(self.temp.name)
        self.m = self.p.manifest

    def progress(self, worked=None):
        return workflow_progress(sdd.Checker(self.p.root, self.m), worked_unit=worked)

    def test_missing_optional_projections_preserve_legacy_validation(self):
        self.assertEqual("passed", self.p.run(after=True)["result"])

    def test_resume_after_several_documents_derives_actual_next_owner(self):
        for key in list(self.m["artifacts"]):
            if key not in ("product-idea", "prd", "project-context", "canonical-terms"):
                del self.m["artifacts"][key]
        self.m["next_ready_nodes"] = ["prd"]
        report = self.progress()
        self.assertEqual(["guardrails"], report["progress"]["next_ready_nodes"], report)
        self.assertEqual("passed", report["result"], report)
        gated = self.p.run("guardrails")
        self.assertTrue(any(item["code"] == "stale_progress" for item in gated["issues"]), gated)
        self.m["next_ready_nodes"] = ["guardrails"]
        self.assertEqual("passed", self.p.run("guardrails")["result"])

    def test_stale_predecessor_returns_to_its_owner(self):
        self.p.write("docs/prd.md", (self.p.root / "docs/prd.md").read_text() + "\nA real edit.\n")
        report = self.progress()
        self.assertEqual("prd", report["progress"]["next_node"], report)
        self.assertEqual(["prd"], report["progress"]["next_ready_nodes"], report)

    def test_handed_off_intake_displays_canonical_source_instead_of_old_draft(self):
        self.m["product_idea_intake"] = {"status": "handed_off", "draft": "Surface remains unknown.",
            "answered_decision_ids": ["surface"], "current_request_id": None,
            "product_idea_hash": self.p.hash("docs/product-idea.md")}
        report = self.progress()
        self.assertEqual({"status": "handed_off", "source": "docs/product-idea.md",
                          "current_request_id": None}, report["progress"]["intake"])
        self.assertEqual("Surface remains unknown.", self.m["product_idea_intake"]["draft"])

    def test_handoff_cannot_keep_pending_question_or_old_hash(self):
        for extra in ({"current_request_id": "Q-1"}, {"pending_question": {"decision_id": "surface"}},
                      {"material_gaps": ["surface"]}, {"product_idea_hash": "0" * 64}):
            with self.subTest(extra=extra):
                self.m["product_idea_intake"] = {"status": "handed_off", **extra}
                report = self.p.run("prd")
                self.assertTrue(any(item["code"] == "intake_progress" for item in report["issues"]), report)
                self.assertEqual([], self.progress()["progress"]["next_ready_nodes"])

    def test_invalid_intake_blocks_early_progress_without_a_unit_plan(self):
        self.m["artifacts"] = {key: value for key, value in self.m["artifacts"].items()
                              if key in ("product-idea", "prd", "project-context", "canonical-terms")}
        self.m["product_idea_intake"] = {"status": "handed_off", "current_request_id": "Q-OLD"}
        del self.m["unit_plan"]
        report = self.progress()
        self.assertEqual("blocked", report["result"], report)
        self.assertEqual([], report["progress"]["next_ready_nodes"], report)
        self.assertTrue(any(item["code"] == "intake_progress" for item in report["issues"]), report)

    def test_answered_decision_cannot_be_reported_pending(self):
        self.m["product_idea_intake"] = {"status": "awaiting_answer", "answered_decision_ids": ["surface"],
            "pending_question": {"decision_id": "surface"}}
        report = self.p.run("product-idea")
        self.assertTrue(any(item["code"] == "intake_progress" for item in report["issues"]), report)

    def test_unknown_intake_draft_does_not_manufacture_answer(self):
        self.m["artifacts"].clear()
        self.m.pop("product_scope", None)
        self.m["product_idea_intake"] = {"status": "awaiting_answer", "draft": "Maybe a UI",
                                       "current_request_id": "Q-1"}
        report = self.progress()
        self.assertEqual("awaiting_answer", report["progress"]["intake"]["status"])
        self.assertEqual([], report["progress"]["next_ready_nodes"])
        self.assertEqual("awaiting_intake_answer", report["progress"]["blockers"][0]["code"])

    def test_reopened_intake_remains_pending_despite_existing_valid_product(self):
        self.m["product_idea_intake"] = {"status": "awaiting_answer", "current_request_id": "Q-NEW"}
        report = self.progress()
        self.assertEqual("product-idea", report["progress"]["next_node"])
        self.assertEqual("awaiting_answer", report["progress"]["intake"]["status"])
        self.assertEqual([], report["progress"]["next_ready_nodes"])

    def test_plan_ready_still_requires_implementation_prompt(self):
        report = self.progress()
        self.assertEqual("implementation", report["progress"]["next_node"])
        self.assertEqual([], report["progress"]["next_ready_nodes"])
        self.assertTrue(any(item["code"] == "implementation_not_authorized" for item in report["progress"]["blockers"]), report)
        self.assertEqual(1, report["progress"]["implementation"]["total_units"])
        self.assertEqual(0, report["progress"]["implementation"]["accepted_complete"])

    def test_authorized_pending_unit_is_eligible_and_absent_worked_unit_not_invented(self):
        self.p.authorize()
        report = self.progress()
        self.assertEqual(["implementation"], report["progress"]["next_ready_nodes"], report)
        summary = report["progress"]["implementation"]
        self.assertEqual((1, 0, "U-1"), (summary["total_units"], summary["accepted_complete"], summary["next_eligible_unit"]))
        self.assertIsNone(summary["just_worked_unit"])

    def test_failed_completion_does_not_count_running_unit_complete(self):
        self.p.authorize()
        self.p.execute_checks()
        self.m["unit_runs"]["U-1"]["status"] = "running"
        del self.m["unit_runs"]["U-1"]["completed_at"]
        self.m["verification"]["checks"][0]["execution_status"] = "failed"
        report = sdd.Checker(self.p.root, self.m).run("implementation", unit_action="complete", unit_id="U-1")
        self.assertEqual("blocked", report["result"], report)
        summary = report["implementation_progress"]
        self.assertEqual(0, summary["accepted_complete"])
        self.assertEqual("completion_blocked", summary["just_worked_unit"]["outcome"])
        self.assertIsNone(summary["next_eligible_unit"])

    def test_blocked_unit_reports_its_reason_and_no_next_unit(self):
        self.p.authorize()
        self.p.execute_checks()
        run = self.m["unit_runs"]["U-1"]
        run.update(status="blocked", reason="Required check failed")
        del run["completed_at"]
        report = self.progress("U-1")
        summary = report["progress"]["implementation"]
        self.assertEqual((1, 0, None), (summary["total_units"], summary["accepted_complete"], summary["next_eligible_unit"]))
        self.assertEqual("blocked", summary["just_worked_unit"]["outcome"])
        self.assertEqual("Required check failed", summary["blockers"][0]["detail"])
        self.assertEqual([], report["progress"]["next_ready_nodes"])

    def test_scoped_sequence_exception_keeps_independent_unit_eligible(self):
        from test_unit_execution import UnitExecutionTests
        fixture = UnitExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.begin("U-1", 3)
        fixture.m["unit_runs"]["U-1"].update(status="blocked", reason="Required alpha check failed")
        fixture.exception("U-2")
        report = workflow_progress(sdd.Checker(fixture.p.root, fixture.m))
        summary = report["progress"]["implementation"]
        self.assertEqual("passed", report["result"], report)
        self.assertEqual("U-2", summary["next_eligible_unit"])
        self.assertEqual(["implementation"], report["progress"]["next_ready_nodes"])
        self.assertEqual("U-1", summary["blocked_units"][0]["target"])
        del fixture.m["unit_sequence_exceptions"]
        report = workflow_progress(sdd.Checker(fixture.p.root, fixture.m))
        self.assertEqual([], report["progress"]["next_ready_nodes"])
        self.assertIsNone(report["progress"]["implementation"]["next_eligible_unit"])

    def test_completed_unit_is_counted_only_after_validation(self):
        self.p.authorize()
        self.p.execute_checks()
        report = self.progress("U-1")
        self.assertEqual(1, report["progress"]["implementation"]["accepted_complete"], report)
        self.assertEqual([], report["progress"]["next_ready_nodes"])
        self.p.write("src/app.txt", "Changed after acceptance.\n")
        report = self.progress("U-1")
        self.assertIsNone(report["progress"]["implementation"]["accepted_complete"], report)
        self.assertEqual([], report["progress"]["next_ready_nodes"])

    def test_pending_transition_to_completion_requires_recorded_completion(self):
        self.p.authorize()
        self.p.execute_checks()
        self.m["unit_runs"]["U-1"]["status"] = "running"
        del self.m["unit_runs"]["U-1"]["completed_at"]
        report = sdd.Checker(self.p.root, self.m).run("implementation", unit_action="complete", unit_id="U-1")
        self.assertEqual("passed", report["result"], report)
        self.assertEqual(0, report["implementation_progress"]["accepted_complete"])
        self.assertEqual("ready_to_record_completion", report["implementation_progress"]["just_worked_unit"]["outcome"])

    def test_unknown_worked_unit_is_rejected_without_inventing_a_run(self):
        self.p.authorize()
        report = self.progress("U-999")
        self.assertEqual("blocked", report["result"])
        self.assertTrue(any(item["code"] == "unknown_worked_unit" for item in report["progress"]["blockers"]))
        self.assertIsNone(report["progress"]["implementation"])

    def test_projection_does_not_modify_manifest_or_files(self):
        original = copy.deepcopy(self.m)
        before = {path: path.read_bytes() for path in self.p.root.rglob("*") if path.is_file()}
        self.progress()
        self.assertEqual(original, self.m)
        self.assertEqual(before, {path: path.read_bytes() for path in self.p.root.rglob("*") if path.is_file()})

    def test_current_cli_reports_stale_projection_and_preserves_manifest(self):
        self.m.update(checker_contract_version=2, unit_contract_version=2)
        self.m["artifacts"] = {key: value for key, value in self.m["artifacts"].items()
                              if key in ("product-idea", "prd", "project-context", "canonical-terms")}
        self.m["next_ready_nodes"] = ["prd"]
        self.p.save()
        original = (self.p.root / "forge/sdd-manifest.json").read_bytes()
        result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.p.root), "--progress"],
                                text=True, capture_output=True)
        self.assertEqual(1, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(["guardrails"], report["progress"]["next_ready_nodes"], report)
        self.assertTrue(any(item["code"] == "stale_progress" for item in report["issues"]), report)
        self.assertEqual(original, (self.p.root / "forge/sdd-manifest.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
