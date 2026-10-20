"""Unfinished-attempt regressions; synthetic records never establish product acceptance."""
import copy
import json
import sys
import unittest
from unittest import mock

import test_unit_history as history_fixture


class AttemptHistoryTests(unittest.TestCase):
    def setUp(self):
        self.base = history_fixture.UnitHistoryTests("test_version_one_retains_original_acceptance_and_plan_binding_rules")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.p, self.m = self.base.p, self.base.m

    def start(self, failed=True):
        self.helper, self.inventory, self.context, _ = self.base.capture_alpha(finish=False)
        self.m["unit_runs"]["U-1"]["run_id"] = "synthetic-attempt-1"
        if failed:
            self.base.fixture.evidence("U-1", 4)
            self.base.stamp_evidence(self.helper, "U-1", self.inventory)
            check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
            check.update(execution_status="failed", run_id="synthetic-attempt-1")
            check["evaluated_source_hashes"]["docs/qa-checklist.md"] = self.p.hash("docs/qa-checklist.md")
            self.m["unit_runs"]["U-1"].update(status="blocked", reason="Actual synthetic required check failed.")
        return self.m["unit_runs"]["U-1"]

    def status_edit(self):
        path = "docs/qa-checklist.md"
        self.p.write(path, (self.p.root / path).read_text() + "\n## Current execution status\n\nUnit remains unfinished.\n")
        self.p.refresh()
        self.m["verification"]["source_hashes"] = {
            "docs/qa-checklist.md": self.p.hash("docs/qa-checklist.md"),
            "docs/dod-evals.md": self.p.hash("docs/dod-evals.md")}

    def capture(self, outcome="failed"):
        reference = self.helper.capture_attempt(self.p.root, self.m, "U-1", self.context,
                                                 "synthetic-attempt-1", outcome, self.base.inventory())
        self.m["unit_runs"]["U-1"]["attempt_ref"] = reference
        return reference

    def continuation_inventory(self):
        reference = self.helper.observe_runtime(self.p.root, {"runtime": [sys.executable, "--version"]})
        reviewed = self.base.inventory(environment=self.base.read(reference)["environment"])
        reviewed["runtime_observation_ref"] = reference
        return reviewed

    def test_failed_and_interrupted_status_edits_preserve_actual_results_and_block_completion(self):
        for failed in (True, False):
            with self.subTest(failed=failed):
                if hasattr(self, "helper"):
                    self.setUp()
                self.start(failed)
                actual = copy.deepcopy(self.m["verification"]["checks"])
                context_bytes = (self.p.root / self.context["path"]).read_bytes()
                self.status_edit()
                before = self.base.report("implementation", "start", "U-1")
                self.assertTrue(any("capture-attempt" in item["detail"] for item in before["issues"]), before)
                with self.assertRaisesRegex(ValueError, "fresh current inventory review"):
                    self.helper.capture_attempt(self.p.root, self.m, "U-1", self.context,
                                                "synthetic-attempt-1", "failed" if failed else "interrupted", self.inventory)
                ref = self.capture("failed" if failed else "interrupted")
                report = self.base.report("implementation", "start", "U-1")
                self.assertEqual("passed", report["result"], report)
                self.assertEqual(actual, self.m["verification"]["checks"])
                self.assertEqual(context_bytes, (self.p.root / self.context["path"]).read_bytes())
                self.assertEqual("not_completed", self.base.read(ref)["acceptance"])
                self.base.assert_blocked(self.base.report("implementation", "complete", "U-1"))
                self.base.assert_blocked(self.base.report("implementation", "start", "U-2"))

    def test_changed_acceptance_authority_and_fabricated_hashes_are_rejected(self):
        for mutation in ("definition", "authority", "canonical_hash", "missing_result", "empty_results"):
            with self.subTest(mutation=mutation):
                if hasattr(self, "helper"):
                    self.setUp()
                self.start()
                if mutation == "definition":
                    path = "docs/qa-checklist.md"
                    self.p.write(path, (self.p.root / path).read_text().replace("## Checks\n", "## Checks\nNew acceptance requirement.\n"))
                    self.p.refresh()
                elif mutation == "authority":
                    self.m["implementation_gate"]["prompt_id"] = "fabricated-replacement-authority"
                elif mutation == "canonical_hash":
                    next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")["evaluated_source_hashes"]["docs/qa-checklist.md"] = "0" * 64
                elif mutation == "missing_result":
                    self.m["verification"]["checks"] = [item for item in self.m["verification"]["checks"] if item["check_id"] != "QA-02"]
                else:
                    self.m["verification"]["checks"] = []
                with self.assertRaises((ValueError, KeyError)):
                    self.capture()

    def test_archived_result_cannot_be_relabelled_or_corrupted(self):
        self.start()
        self.status_edit()
        reference = self.capture()
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        check["execution_status"] = "passed"
        report = self.base.report("implementation", "start", "U-1")
        self.assertTrue(any("actual status/results" in item["detail"] for item in report["issues"]), report)
        check["execution_status"] = "failed"
        record = self.base.read(reference)
        snapshot = self.p.root / record["files"]["src/alpha.txt"]["path"]
        snapshot.write_text("tampered preserved work\n")
        self.base.assert_blocked(self.base.report("implementation", "start", "U-1"))
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            self.helper.validate_attempt(self.p.root, reference)

    def test_interrupted_archive_with_passed_checks_cannot_complete(self):
        self.start()
        self.m["unit_runs"]["U-1"].update(status="running")
        self.m["unit_runs"]["U-1"].pop("reason")
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        check["execution_status"] = "passed"
        self.capture("interrupted")
        report = self.base.report("implementation", "complete", "U-1")
        self.assertTrue(any("archived unfinished attempt cannot complete" in item["detail"]
                            for item in report["issues"]), report)

    def test_continuation_probes_real_runtime_resets_results_and_preserves_work(self):
        self.start()
        self.status_edit()
        reference = self.capture()
        prior_bytes = (self.p.root / reference["path"]).read_bytes()
        code_bytes = (self.p.root / "src/alpha.txt").read_bytes()
        reviewed = self.continuation_inventory()
        result = self.helper.capture_continuation(self.p.root, self.m, "U-1", reference,
                                                  "synthetic-attempt-2", reviewed)
        candidate = result["manifest"]
        self.assertEqual([reference], candidate["attempt_history"]["U-1"])
        self.assertEqual("pending", candidate["unit_runs"]["U-1"]["status"])
        current = next(item for item in candidate["verification"]["checks"] if item["check_id"] == "QA-02")
        self.assertEqual("not_run", current["execution_status"])
        self.assertNotIn("evidence", current)
        self.helper.validate_transition(self.p.root, self.m, candidate, {})
        self.m.clear()
        self.m.update(candidate)
        self.assertEqual("passed", self.base.report("implementation", "start", "U-1")["result"])
        self.assertEqual(code_bytes, (self.p.root / "src/alpha.txt").read_bytes())
        self.assertEqual(prior_bytes, (self.p.root / reference["path"]).read_bytes())
        self.base.assert_blocked(self.base.report("implementation", "complete", "U-1"))
        # Start and execute new evidence genuinely within the new qualification run.
        self.m["unit_runs"]["U-1"].update(status="running", started_at=self.base.now(),
            development_plan_hash=self.p.hash("docs/development-plan.md"), approved_baseline_id="B-1")
        runtime = self.helper.observe_runtime(self.p.root, {"runtime": [sys.executable, "--version"]})
        self.base.fixture.evidence("U-1", 4)
        self.base.stamp_evidence(self.helper, "U-1", reviewed)
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        check["run_id"] = "synthetic-attempt-2"
        self.m["unit_runs"]["U-1"].update(status="completed", completed_at=self.base.now())
        with self.assertRaisesRegex(ValueError, "execution-time runtime observation"):
            self.helper.capture_completion(self.p.root, self.m, "U-1", result["context_ref"],
                                             "synthetic-attempt-2", reviewed)
        check["runtime_observation_ref"] = self.helper.observe_runtime(
            self.p.root, {"runtime": [sys.executable, "-c", "print('different actual test runtime identity')"]})
        check["executed_at"] = self.base.now()
        self.m["unit_runs"]["U-1"]["completed_at"] = self.base.now()
        with self.assertRaisesRegex(ValueError, "executed runtime changed"):
            self.helper.capture_completion(self.p.root, self.m, "U-1", result["context_ref"],
                                             "synthetic-attempt-2", reviewed)
        check["runtime_observation_ref"] = runtime
        completion = self.helper.capture_completion(self.p.root, self.m, "U-1", result["context_ref"],
                                                     "synthetic-attempt-2", reviewed)
        self.assertEqual("completed", self.base.read(completion)["run"]["status"])
        self.assertEqual("failed", self.base.read(reference)["checks"][0]["execution_status"])

    def test_continuation_rejects_old_id_stale_probe_changed_scope_and_erased_history(self):
        self.start(False)
        stale = self.continuation_inventory()
        reference = self.capture("interrupted")
        with self.assertRaises(ValueError):
            self.helper.capture_continuation(self.p.root, self.m, "U-1", reference, "synthetic-attempt-2", stale)
        reviewed = self.continuation_inventory()
        with self.assertRaisesRegex(ValueError, "new run identity"):
            self.helper.capture_continuation(self.p.root, self.m, "U-1", reference, "synthetic-attempt-1", reviewed)
        missing_probe = copy.deepcopy(reviewed)
        missing_probe.pop("runtime_observation_ref")
        with self.assertRaises(ValueError):
            self.helper.capture_continuation(self.p.root, self.m, "U-1", reference, "synthetic-attempt-2", missing_probe)
        reviewed["environment"]["runtime"] = "invented version"
        with self.assertRaisesRegex(ValueError, "runtime observation differs"):
            self.helper.capture_continuation(self.p.root, self.m, "U-1", reference, "synthetic-attempt-2", reviewed)
        erased = copy.deepcopy(self.m)
        erased["unit_runs"]["U-1"] = {"status": "pending"}
        with self.assertRaisesRegex(ValueError, "history was dropped"):
            self.helper.validate_transition(self.p.root, self.m, erased, {})

    def test_attempt_capture_rejects_substituted_continuation_identity(self):
        self.start(False)
        reference = self.capture("interrupted")
        result = self.helper.capture_continuation(self.p.root, self.m, "U-1", reference,
                                                  "synthetic-attempt-2", self.continuation_inventory())
        self.m.clear()
        self.m.update(result["manifest"])
        self.m["unit_runs"]["U-1"].update(status="running", run_id="unrelated-attempt-3", started_at=self.base.now(),
            development_plan_hash=self.p.hash("docs/development-plan.md"), approved_baseline_id="B-1")
        with self.assertRaisesRegex(ValueError, "identity differs from its continuation context"):
            self.helper.capture_attempt(self.p.root, self.m, "U-1", result["context_ref"], "unrelated-attempt-3",
                                         "interrupted", self.base.read(result["context_ref"])["input_inventory"])

    def test_inherited_findings_require_preserved_identity_and_evidenced_closure(self):
        self.start(False)
        finding = {"severity": "P1", "release_effect": "blocking", "status": "open", "detail": "Original blocker without an ID"}
        self.m["unit_runs"]["U-1"]["findings"] = [copy.deepcopy(finding)]
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        check["findings"] = [{**finding, "id": "SYNTHETIC-FINDING-1"}]
        reference = self.capture("interrupted")
        result = self.helper.capture_continuation(self.p.root, self.m, "U-1", reference,
                                                  "synthetic-attempt-2", self.continuation_inventory())
        self.m.clear()
        self.m.update(result["manifest"])
        run = self.m["unit_runs"]["U-1"]
        run.update(status="running", started_at=self.base.now(),
                   development_plan_hash=self.p.hash("docs/development-plan.md"), approved_baseline_id="B-1")
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        inventory = self.base.read(result["context_ref"])["input_inventory"]
        original_run, original_check = copy.deepcopy(run["findings"]), copy.deepcopy(check["findings"])
        for location, mutation in (("run", "delete"), ("check", "delete"), ("check", "substitute"), ("run", "downgrade")):
            with self.subTest(location=location, mutation=mutation):
                subject = run if location == "run" else check
                if mutation == "delete":
                    subject["findings"] = []
                elif mutation == "substitute":
                    subject["findings"][0]["id"] = "UNRELATED-FINDING"
                else:
                    subject["findings"][0].update(severity="P3", release_effect="advisory")
                report = self.base.report("implementation", "start", "U-1")
                self.assertTrue(any("inherited finding" in item["detail"] for item in report["issues"]), report)
                with self.assertRaisesRegex(ValueError, "inherited finding"):
                    self.helper.capture_attempt(self.p.root, self.m, "U-1", result["context_ref"],
                                                 "synthetic-attempt-2", "interrupted", inventory)
                run["findings"], check["findings"] = copy.deepcopy(original_run), copy.deepcopy(original_check)
        runtime = self.helper.observe_runtime(self.p.root, {"runtime": [sys.executable, "--version"]})
        self.base.fixture.evidence("U-1", 4)
        self.base.stamp_evidence(self.helper, "U-1", inventory)
        check.update(run_id="synthetic-attempt-2", runtime_observation_ref=runtime)
        for item in run["findings"] + check["findings"]:
            item["status"] = "closed"
        run.update(status="completed", completed_at=self.base.now())
        with self.assertRaisesRegex(ValueError, "evidence-backed rationale"):
            self.helper.capture_completion(self.p.root, self.m, "U-1", result["context_ref"], "synthetic-attempt-2", inventory)
        closure = {"closed_at": self.base.now(), "rationale": "Repair verified by the new synthetic check.", "check_ids": ["QA-02"]}
        for item in run["findings"] + check["findings"]:
            item["closure"] = copy.deepcopy(closure)
        with self.assertRaisesRegex(ValueError, "closure is outside"):
            self.helper.capture_completion(self.p.root, self.m, "U-1", result["context_ref"], "synthetic-attempt-2", inventory)
        run["completed_at"] = self.base.now()
        completion = self.helper.capture_completion(self.p.root, self.m, "U-1", result["context_ref"], "synthetic-attempt-2", inventory)
        self.assertEqual("closed", self.base.read(completion)["run"]["findings"][0]["status"])
        self.assertEqual("open", self.base.read(reference)["run"]["findings"][0]["status"])

    def test_partial_edits_and_deletions_preserve_stale_results_without_reusing_acceptance(self):
        for change in ("edit", "delete"):
            with self.subTest(change=change):
                if hasattr(self, "helper"):
                    self.setUp()
                self.start()
                old_check = copy.deepcopy(next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02"))
                if change == "edit":
                    self.p.write("src/alpha.txt", "Later partial repair, not yet tested.\n")
                else:
                    (self.p.root / "src/alpha.txt").unlink()
                self.status_edit()
                reference = self.capture()
                archived = self.base.read(reference)
                self.assertEqual("unverified_stale_inputs", archived["observation_validity"])
                self.assertEqual([old_check], archived["checks"])
                report = self.base.report("implementation", "start", "U-1")
                self.assertEqual("passed", report["result"], report)
                self.assertTrue(any("stale input observations" in warning for warning in report["warnings"]))
                self.base.assert_blocked(self.base.report("implementation", "complete", "U-1"))
                self.base.assert_blocked(self.base.report("implementation", "start", "U-2"))
                continuation = self.helper.capture_continuation(self.p.root, self.m, "U-1", reference,
                                                               "synthetic-attempt-2", self.continuation_inventory())
                self.assertEqual("not_run", next(item for item in continuation["manifest"]["verification"]["checks"]
                                                 if item["check_id"] == "QA-02")["execution_status"])
                self.assertEqual(old_check, next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02"))

    def test_reopened_finding_can_close_again_without_rewriting_earlier_closure(self):
        self.start(False)
        finding = {"id": "REOPENED-1", "severity": "P1", "release_effect": "blocking", "status": "open",
                   "detail": "A recurring synthetic blocker"}
        self.m["unit_runs"]["U-1"]["findings"] = [copy.deepcopy(finding)]
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        check["findings"] = [copy.deepcopy(finding)]

        def advance(next_id):
            context_ref = self.m["execution_contexts"]["U-1"]
            reference = self.helper.capture_attempt(self.p.root, self.m, "U-1", context_ref,
                self.m["unit_runs"]["U-1"]["run_id"], "interrupted", self.base.read(context_ref)["input_inventory"])
            self.m["unit_runs"]["U-1"]["attempt_ref"] = reference
            result = self.helper.capture_continuation(self.p.root, self.m, "U-1", reference, next_id,
                                                       self.continuation_inventory())
            self.m.clear()
            self.m.update(result["manifest"])
            self.m["unit_runs"]["U-1"].update(status="running", started_at=self.base.now(),
                development_plan_hash=self.p.hash("docs/development-plan.md"), approved_baseline_id="B-1")
            return reference

        def close():
            inventory = self.base.read(self.m["execution_contexts"]["U-1"])["input_inventory"]
            runtime = self.helper.observe_runtime(self.p.root, {"runtime": [sys.executable, "--version"]})
            self.base.fixture.evidence("U-1", 4)
            self.base.stamp_evidence(self.helper, "U-1", inventory)
            run = self.m["unit_runs"]["U-1"]
            check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
            check.update(run_id=run["run_id"], runtime_observation_ref=runtime)
            closure = {"closed_at": self.base.now(), "rationale": "Verified this recurrence using current evidence.", "check_ids": ["QA-02"]}
            for item in run["findings"] + check["findings"]:
                item.update(status="closed", closure=copy.deepcopy(closure))

        advance("synthetic-attempt-2")
        close()
        earlier = advance("synthetic-attempt-3")
        earlier_bytes = (self.p.root / earlier["path"]).read_bytes()
        self.m["unit_runs"]["U-1"]["findings"][0]["status"] = "open"
        next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")["findings"][0]["status"] = "open"
        advance("synthetic-attempt-4")
        close()
        self.m["unit_runs"]["U-1"].update(status="completed", completed_at=self.base.now())
        context_ref = self.m["execution_contexts"]["U-1"]
        completion = self.helper.capture_completion(self.p.root, self.m, "U-1", context_ref, "synthetic-attempt-4",
                                                      self.base.read(context_ref)["input_inventory"])
        self.assertEqual("closed", self.base.read(completion)["run"]["findings"][0]["status"])
        self.assertEqual(earlier_bytes, (self.p.root / earlier["path"]).read_bytes())

    def test_repeated_retry_validation_reuses_one_operation_cache_and_rejects_old_identity(self):
        self.start(False)
        counts = []
        for number in range(1, 5):
            run_id = "synthetic-attempt-" + str(number)
            with mock.patch.object(self.helper.api().Checker, "run", autospec=True,
                                   side_effect=self.helper.api().Checker.run) as calls:
                reference = self.helper.capture_attempt(self.p.root, self.m, "U-1",
                    self.m["execution_contexts"]["U-1"], run_id, "interrupted",
                    self.base.read(self.m["execution_contexts"]["U-1"])["input_inventory"])
                self.m["unit_runs"]["U-1"]["attempt_ref"] = reference
                candidate = self.helper.capture_continuation(self.p.root, self.m, "U-1", reference,
                    "synthetic-attempt-" + str(number + 1), self.continuation_inventory())["manifest"]
                counts.append(calls.call_count)
            self.m.clear()
            self.m.update(candidate)
            self.m["unit_runs"]["U-1"].update(status="running", started_at=self.base.now(),
                development_plan_hash=self.p.hash("docs/development-plan.md"), approved_baseline_id="B-1")
        self.assertTrue(all(count <= counts[0] * (index + 1) for index, count in enumerate(counts)), counts)
        # Reusing the oldest ID is invalid even after several distinct retries.
        reference = self.helper.capture_attempt(self.p.root, self.m, "U-1", self.m["execution_contexts"]["U-1"],
            "synthetic-attempt-5", "interrupted", self.base.read(self.m["execution_contexts"]["U-1"])["input_inventory"])
        self.m["unit_runs"]["U-1"]["attempt_ref"] = reference
        with self.assertRaisesRegex(ValueError, "new run identity"):
            self.helper.capture_continuation(self.p.root, self.m, "U-1", reference,
                                             "synthetic-attempt-1", self.continuation_inventory())


if __name__ == "__main__":
    unittest.main()
