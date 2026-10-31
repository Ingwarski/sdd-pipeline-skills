"""Reviewed acceptance shares every gate without rewriting recorded execution."""
import copy
from datetime import datetime
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import test_unit_history as fixture
from test_sdd_check import ROOT, sdd
from progress import workflow_progress
import check_inputs
import reviewed_acceptance


class ReviewedGateTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture.UnitHistoryTests("test_version_one_retains_original_acceptance_and_plan_binding_rules")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.p, self.m = self.base.p, self.base.m

    def reviewed(self, units=("U-1",), *, interrupted=False, fresh=()):
        """Actual public import/review APIs over the shared synthetic unit fixture."""
        self.m.update(checker_contract_version=3, unit_contract_version=3)
        for check in self.m["verification"]["checks"]:
            check["acceptance"].update(reuse_policy="fresh" if check["check_id"] in fresh else "deterministic_isolated", dependency_review={
                "complete": True, "reviewer": "synthetic dependency owner",
                "rationale": "Complete declared synthetic input and prerequisite inventory."})
        self.base.fixture.sync()
        h = sdd.history_api()
        inventories, sources = {}, {}
        for index, unit in enumerate(units):
            self.base.fixture.complete(unit, 3 + index * 3)
            run = self.m["unit_runs"][unit]
            run["run_id"] = "synthetic-original-" + unit
            for check in self.m["verification"]["checks"]:
                if self.m["unit_plan"]["acceptance"][check["check_id"]]["owner_unit"] != unit:
                    continue
                check["run_id"] = run["run_id"]
                native_runtime = {"unit_id": unit, "run_id": run["run_id"],
                                  "observed_at": check["executed_at"],
                                  "environment": {"runtime": "synthetic-runtime-1"}}
                native_evidence = self.p.evidence(check["evidence"][0]["path"], {
                    "synthetic_fixture": True, "not_real_product_validation": True, "runtime": native_runtime})
                for evidence in check["evidence"]:
                    evidence.update(native_evidence)
                check["runtime_observation_ref"] = self.p.evidence("forge/runs/runtime-" + check["check_id"] + ".json", {
                    "event": "external_runtime_observation", "version": 1, **native_runtime,
                    "evidence": check["evidence"]})
            if interrupted:
                run.update(status="blocked", reason="Synthetic interruption after completed observations")
                del run["completed_at"]
        for unit in units:
            inventory = h.prepare_inventory(sdd.Checker(self.p.root, self.m), unit, self.inventory(unit))
            inventories[unit] = h.store_record(self.p.root, "synthetic-original-inventories", inventory)
            sources[unit] = reviewed_acceptance.import_observations(self.p.root, self.m, unit)
        original = copy.deepcopy(self.m)
        self.m.update(checker_contract_version=4, unit_contract_version=4, reviewed_acceptance={})
        for unit in units:
            request = {"unit_id": unit, "source_kind": "external_observations", "source_ref": sources[unit],
                       "original_inventory_ref": inventories[unit], "current_inventory": self.inventory(unit),
                       "review": {"complete": True, "reviewer": "synthetic acceptance owner",
                                  "rationale": "Review supplied observations with disclosed missing registration.",
                                  "reviewed_at": h.utcnow(),
                                  "reuse_eligibility": {key: "deterministic_isolated" for key, allocation in self.m["unit_plan"]["acceptance"].items()
                                                        if allocation["owner_unit"] == unit},
                                  "preconditions": {key: [] for key, allocation in self.m["unit_plan"]["acceptance"].items()
                                                    if allocation["owner_unit"] == unit}},
                       "procedural_gaps": ["Execution context was not registered before execution."]}
            self.m["reviewed_acceptance"][unit] = [reviewed_acceptance.capture(self.p.root, self.m, request)]
        return original

    def inventory(self, unit):
        inventory = self.base.inventory(unit=unit)
        pending = list(self.m["unit_plan"]["units"][unit]["construction_dependencies"])
        seen = set()
        while pending:
            dependency = pending.pop()
            if dependency in seen:
                continue
            seen.add(dependency)
            definition = self.m["unit_plan"]["units"][dependency]
            inventory["execution_inputs"].update({path: {"mode": "file"} for path in definition["implementation_paths"]})
            pending.extend(definition["construction_dependencies"])
        return inventory

    def test_reviewed_completion_preserves_interrupted_run_and_progress_provenance(self):
        original = self.reviewed(interrupted=True)
        before = copy.deepcopy(self.m)
        report = self.base.report("implementation", "complete", "U-1")
        self.assertEqual("passed", report["result"], report)
        progress = report["implementation_progress"]
        self.assertEqual(["U-1"], progress["accepted_unit_ids"])
        self.assertEqual("blocked", progress["just_worked_unit"]["recorded_status"])
        self.assertEqual("accepted_complete", progress["just_worked_unit"]["outcome"])
        self.assertEqual("accepted", progress["just_worked_unit"]["current_acceptance"])
        self.assertEqual(self.m["reviewed_acceptance"]["U-1"][-1],
                         progress["just_worked_unit"]["acceptance_review"]["review_ref"])
        receipt = self.base.read(self.m["reviewed_acceptance"]["U-1"][-1])
        self.assertEqual(receipt["recorded_at"], progress["just_worked_unit"]["acceptance_review"]["recorded_at"])
        self.assertEqual(before, self.m)
        self.assertEqual(original["unit_runs"], self.m["unit_runs"])
        self.assertEqual("U-2", progress["next_eligible_unit"])
        progress_report = workflow_progress(sdd.Checker(self.p.root, self.m), worked_unit="U-1")
        self.assertEqual("accepted_complete", progress_report["progress"]["implementation"]["just_worked_unit"]["outcome"])
        self.assertNotEqual("passed", self.base.report("implementation", "start", "U-1")["result"])

    def test_owner_review_date_cannot_make_acceptance_available_before_capture(self):
        h = sdd.history_api()
        owner_review = "2026-08-21T10:00:00+00:00"
        system_capture = "2026-08-21T10:00:02+00:00"
        capture = reviewed_acceptance.capture

        def capture_later(*args, **kwargs):
            with mock.patch.object(h, "utcnow", return_value=system_capture):
                return capture(*args, **kwargs)

        # Separate the real capture call from the owner review explicitly;
        # consecutive wall-clock reads can share one Windows clock tick.
        with mock.patch.object(h, "utcnow", return_value=owner_review), \
                mock.patch.object(self.base, "now", return_value=owner_review), \
                mock.patch.object(reviewed_acceptance, "capture", side_effect=capture_later):
            self.reviewed()
        receipt = self.base.read(self.m["reviewed_acceptance"]["U-1"][-1])
        reviewed_at = sdd.timestamp(receipt["review"]["reviewed_at"])
        recorded_at = sdd.timestamp(receipt["recorded_at"])
        self.assertEqual(owner_review, receipt["review"]["reviewed_at"])
        self.assertEqual(system_capture, receipt["recorded_at"])
        self.assertLess(reviewed_at, recorded_at)
        before_capture = reviewed_at + (recorded_at - reviewed_at) / 2

        class EarlierGateClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return before_capture.astimezone(tz)

        # The independently recorded evidence remains intact. The gate itself
        # must not claim that acceptance existed at the earlier owner's date.
        with mock.patch.object(sdd, "datetime", EarlierGateClock):
            report = self.base.report("implementation", "complete", "U-1")
        self.assertEqual("blocked", report["result"], report)
        self.assertTrue(any("reviewed acceptance is in the future" in issue["detail"]
                            for issue in report["issues"]), report)

    def test_current_authority_is_required_even_with_accepted_review(self):
        self.m["implementation_gate"]["state"] = "awaiting_implementation_prompt"
        self.reviewed()
        # Make and bind a review while current execution authority is absent.
        self.m["implementation_gate"]["state"] = "awaiting_implementation_prompt"
        previous = self.base.read(self.m["reviewed_acceptance"]["U-1"][-1])
        request = {key: previous[key] for key in ("unit_id", "source_kind", "source_ref", "original_inventory_ref",
                                                  "current_inventory", "review", "procedural_gaps")}
        request["review"]["reviewed_at"] = sdd.history_api().utcnow()
        self.m["reviewed_acceptance"]["U-1"].append(reviewed_acceptance.capture(self.p.root, self.m, request))
        report = self.base.report("implementation", "complete", "U-1")
        self.assertNotEqual("passed", report["result"], report)
        self.assertTrue(any(issue["code"] == "implementation_not_authorized" for issue in report["issues"]), report)

    def test_reviewed_components_do_not_satisfy_integration_security_or_release(self):
        self.reviewed(("U-1", "U-2"))
        report = self.base.report("release")
        self.assertNotEqual("passed", report["result"], report)
        self.assertTrue(any(issue["code"] == "required_check_incomplete" for issue in report["issues"]), report)

    def test_full_review_uses_shared_release_security_and_progress_acceptance(self):
        original = self.reviewed(("U-1", "U-2", "U-3"))
        report = self.base.report("release")
        self.assertEqual("passed", report["result"], report)
        self.assertEqual(["U-1", "U-2", "U-3"], report["implementation_progress"]["accepted_unit_ids"])
        self.assertEqual(original["unit_runs"], self.m["unit_runs"])
        self.p.write("src/alpha.txt", "Changed prerequisite source after review.\n")
        report = self.base.report("release")
        self.assertNotEqual("passed", report["result"], report)
        self.assertNotIn("U-3", report["implementation_progress"]["accepted_unit_ids"] or [])

    def test_current_blocking_finding_cannot_be_hidden_by_review(self):
        self.reviewed()
        self.m["unit_runs"]["U-1"]["findings"] = [{"severity": "P1", "status": "open", "release_effect": "blocking"}]
        report = self.base.report("implementation", "complete", "U-1")
        self.assertNotEqual("passed", report["result"], report)
        self.assertNotIn("U-1", report["implementation_progress"]["accepted_unit_ids"] or [])

    def test_partial_review_retains_deterministic_checks_but_fresh_security_still_blocks(self):
        original = self.reviewed(("U-1", "U-2", "U-3"), fresh=("QA-04",))
        checker = sdd.Checker(self.p.root, self.m)
        report = checker.run("development-plan", after=True)
        self.assertEqual("passed", report["result"], report)
        self.assertEqual(["U-1", "U-2"], report["implementation_progress"]["accepted_unit_ids"])
        self.assertIn("QA-01", checker._unit_history.reviewed_checks)
        self.assertNotIn("QA-04", checker._unit_history.reviewed_checks)
        diagnostic = report["unit_history"]["reviews"]["U-3"]
        self.assertEqual("needs_revalidation", diagnostic["current_applicability"])
        self.assertIn("QA-04", diagnostic["revalidation_check_ids"])
        self.assertTrue(diagnostic["reasons"])
        self.assertIn("review_ref", diagnostic)
        self.assertLessEqual(set(diagnostic["original_run"]), {"status", "run_id", "started_at", "completed_at"})
        self.assertNotIn("source_run_matches_current", diagnostic)
        self.assertEqual(original["unit_runs"], self.m["unit_runs"])
        self.assertNotEqual("passed", self.base.report("implementation", "complete", "U-3")["result"])
        self.assertNotEqual("passed", self.base.report("release")["result"])

    def prepare_partial_current_run(self):
        self.m["unit_plan"]["acceptance"]["QA-04"]["prerequisite_checks"] = ["QA-02"]
        self.reviewed(("U-1", "U-2", "U-3"), interrupted=True, fresh=("QA-04",))
        h = sdd.history_api()
        self.m["unit_runs"]["U-3"] = {"status": "pending"}
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-04")
        for field in h.EXECUTION_KEYS:
            if field != "findings":
                check.pop(field, None)
        check["execution_status"] = "not_run"
        context = h.capture_context(self.p.root, self.m, "U-3", self.inventory("U-3"))
        self.m.setdefault("execution_contexts", {})["U-3"] = context
        self.m["unit_runs"]["U-3"] = {
            "status": "running", "run_id": "synthetic-current-integration",
            "started_at": h.utcnow(), "development_plan_hash": self.p.hash("docs/development-plan.md"),
            "approved_baseline_id": "B-1", "findings": []}
        evidence = self.p.evidence("forge/evidence/fresh-security.json", {"synthetic_fixture": True})
        check.update(execution_status="passed", executor="synthetic current runner", executed_at=h.utcnow(),
                     run_id="synthetic-current-integration", evidence=[{**evidence, "kind": "security"},
                                                                      {**evidence, "kind": "integration"}],
                     execution_mode="real_consumers", evaluated_plan_hash=self.p.hash("docs/development-plan.md"),
                     evaluated_source_hashes={path: self.p.hash(path) for path in self.inventory("U-3")["execution_inputs"]})
        observed = h.observe_execution_inputs(self.p.root, self.m, "U-3", self.inventory("U-3"), check_id="QA-04")
        check["evaluated_execution_inputs"] = observed
        return h, context

    def test_partial_review_can_contribute_to_genuine_new_execution(self):
        h, context = self.prepare_partial_current_run()
        report = self.base.report("implementation", "complete", "U-3")
        self.assertEqual("passed", report["result"], report)
        self.assertEqual("ready_to_record_completion", report["implementation_progress"]["just_worked_unit"]["outcome"])
        self.m["unit_runs"]["U-3"].update(status="completed", completed_at=h.utcnow())
        completion = h.capture_completion(self.p.root, self.m, "U-3", context, "synthetic-current-integration")
        self.m["unit_runs"]["U-3"] = {"status": "completed", "completion_ref": completion}
        report = self.base.report("release")
        self.assertEqual("passed", report["result"], report)

    def test_distinct_new_pass_with_wrong_evidence_cannot_borrow_old_review(self):
        h, context = self.prepare_partial_current_run()
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-01")
        evidence = self.p.evidence("forge/evidence/current-wrong-class.json", {"synthetic_fixture": True})
        check.update(run_id="synthetic-current-integration", executed_at=h.utcnow(),
                     evidence=[{**evidence, "kind": "functional"}])
        check["evaluated_execution_inputs"] = h.observe_execution_inputs(
            self.p.root, self.m, "U-3", self.inventory("U-3"), check_id="QA-01")
        report = self.base.report("implementation", "complete", "U-3")
        self.assertNotEqual("passed", report["result"], report)
        self.assertTrue(any(issue["code"] == "wrong_evidence_class" for issue in report["issues"]), report)
        self.m["unit_runs"]["U-3"].update(status="completed", completed_at=h.utcnow())
        with self.assertRaisesRegex(ValueError, "invalid|wrong_evidence_class"):
            h.capture_completion(self.p.root, self.m, "U-3", context, "synthetic-current-integration")
        self.assertNotEqual("passed", self.base.report("release")["result"])

    def test_archived_evidence_delegation_uses_exact_reference_and_keeps_live_paths(self):
        self.reviewed()
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        reference = copy.deepcopy(check["evidence"][0])
        original = (self.p.root / reference["path"]).read_bytes()
        self.p.write(reference["path"], '{"current_unrelated_record":true}\n')
        current = (self.p.root / reference["path"]).read_bytes()
        checker = sdd.Checker(self.p.root, self.m)
        report = checker.run("implementation", unit_action="complete", unit_id="U-1")
        self.assertEqual("passed", report["result"], report)
        self.assertEqual(current, checker.path(reference["path"]).read_bytes())
        self.assertEqual(original, checker.evidence_bytes(reference))
        self.assertIn("runtime", checker.evidence_json(reference))
        current_reference = {**reference, "content_hash": self.p.hash(reference["path"])}
        self.assertEqual({"current_unrelated_record": True}, checker.evidence_json(current_reference))
        self.assertIsNone(checker.reviewed_evidence_view(current_reference))
        self.p.write("src/alpha.txt", "Changed current source invalidates the old result.\n")
        checker.run("development-plan", after=True)
        self.assertIsNone(checker.reviewed_evidence_view(reference))

    def test_review_field_is_rejected_by_every_older_contract_even_when_empty(self):
        for version in (1, 2, 3):
            with self.subTest(version=version):
                self.m.update(checker_contract_version=version, unit_contract_version=version,
                              reviewed_acceptance={})
                report = self.base.report()
                self.assertNotEqual("passed", report["result"], report)
                self.assertTrue(any(issue["code"] == "unsupported_contract_version"
                                    for issue in report["issues"]), report)

    def test_reused_checker_cannot_cache_counterevidence_when_empty_review_index_is_removed(self):
        h, _, _, _ = self.base.capture_alpha()
        self.m.update(checker_contract_version=4, unit_contract_version=4, reviewed_acceptance={})
        checker = sdd.Checker(self.p.root, self.m)
        first = checker.run("implementation", unit_action="complete", unit_id="U-1")
        self.assertEqual("passed", first["result"], first)
        self.m.pop("reviewed_acceptance")
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        check.update(execution_status="failed", executed_at=h.utcnow())
        reused = checker.run("implementation", unit_action="complete", unit_id="U-1")
        fresh = sdd.Checker(self.p.root, self.m).run("implementation", unit_action="complete", unit_id="U-1")
        self.assertEqual("blocked", reused["result"], reused)
        self.assertEqual(fresh["result"], reused["result"])
        self.assertEqual(fresh["issues"], reused["issues"])
        self.assertNotIn("U-1", reused["implementation_progress"]["accepted_unit_ids"] or [])

    def test_version_four_preserves_per_check_inputs_without_granting_acceptance(self):
        self.m.update(checker_contract_version=4, unit_contract_version=4)
        self.assertTrue(check_inputs.enabled(self.m))
        self.assertFalse(check_inputs.enabled({"checker_contract_version": 3, "unit_contract_version": 4}))
        original = copy.deepcopy(self.m)
        report = self.base.report()
        self.assertEqual("passed", report["result"], report)
        self.assertEqual([], report["implementation_progress"]["accepted_unit_ids"])
        self.assertEqual(original, self.m)
        report = self.base.report("implementation", "complete", "U-1")
        self.assertNotEqual("passed", report["result"], report)

    def test_actual_previous_checker_rejects_version_four_at_every_boundary(self):
        self.m.update(checker_contract_version=4, unit_contract_version=4)
        self.p.save()
        with tempfile.TemporaryDirectory(prefix="sdd-previous-review-gates-") as directory:
            skills = Path(directory) / "skills"
            shutil.copytree(ROOT / "skills", skills,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
            script = skills / "to-sdd-pipeline/scripts/sdd_check.py"
            frozen = gzip.decompress((ROOT / "tests/fixtures/sdd-check-f114a84.py.gz").read_bytes())
            script.write_bytes(frozen)
            for arguments in (("--after", "development-plan"), ("--before", "implementation"),
                              ("--start-unit", "U-1"), ("--complete-unit", "U-1"),
                              ("--audit",), ("--before", "release"), ("--progress",)):
                with self.subTest(arguments=arguments):
                    process = subprocess.run([sys.executable, "-B", str(script), "--project", str(self.p.root),
                                              *arguments], text=True, capture_output=True)
                    self.assertTrue(process.stdout.strip(), process.stderr)
                    report = json.loads(process.stdout)
                    self.assertNotEqual(0, process.returncode, report)
                    self.assertEqual(sdd.digest(frozen), report["toolchain"]["checker_sha256"])
                    self.assertTrue(any(issue["code"] in ("unsupported_contract_version", "migration_required")
                                        for issue in report["issues"]), report)


if __name__ == "__main__":
    unittest.main()
