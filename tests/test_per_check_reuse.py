"""Synthetic dependency and interrupted-result tests; no product acceptance."""
import copy
import json
import sys
import unittest
from unittest import mock

import test_unit_history as fixture


class PerCheckReuseTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture.UnitHistoryTests("test_version_one_retains_original_acceptance_and_plan_binding_rules")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.p, self.m = self.base.p, self.base.m
        self.h = self.base.history()
        self.m.update(checker_contract_version=3, unit_contract_version=3)
        self.check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        self.check["acceptance"].update(source_set_ids=["component"], required_source_paths=[],
            dependency_review={"complete": True, "reviewer": "synthetic dependency owner", "rationale": "Isolated deterministic component and its explicit inputs."},
            reuse_policy="deterministic_isolated")
        self.m["unit_plan"]["units"]["U-1"]["implementation_paths"].append("src/other.txt")
        self.m["verification"].update(source_sets={"component": ["src/alpha.txt"]},
            source_sets_ref={"path": "docs/qa-checklist.md", "heading": "## Source sets"})
        self.p.sync_unit_contract()
        self.p.write("docs/qa-checklist.md", (self.p.root / "docs/qa-checklist.md").read_text()
                     + "\n## Source sets\n\n```json\n" + json.dumps(self.m["verification"]["source_sets"]) + "\n```\n")
        self.p.refresh()
        self.m["verification"]["source_hashes"] = {name: self.p.hash(name)
            for name in ("docs/qa-checklist.md", "docs/dod-evals.md")}
        self.p.authorize()

    def inventory(self):
        runtime = self.h.observe_runtime(self.p.root, {"runtime": [sys.executable, "--version"]})
        reviewed = self.base.inventory(environment=self.base.read(runtime)["environment"])
        reviewed["runtime_observation_ref"] = runtime
        for path in getattr(self, "dependencies", []):
            reviewed["execution_inputs"][path] = {"mode": "file"}
        if getattr(self, "tree_inputs", False):
            reviewed["execution_inputs"] = {"src": {"mode": "tree"}}
        return reviewed

    def start_and_seal(self, *, settlement_changes=None, before_attempt=None, seal=True):
        self.inputs = self.inventory()
        self.context = self.h.capture_context(self.p.root, self.m, "U-1", self.inputs)
        self.m.setdefault("execution_contexts", {})["U-1"] = self.context
        self.base.fixture.begin("U-1", 3)
        run = self.m["unit_runs"]["U-1"]
        run.update(started_at=self.base.now(), run_id="synthetic-original-run")
        runtime = self.h.observe_runtime(self.p.root, {"runtime": [sys.executable, "--version"]})
        self.base.fixture.evidence("U-1", 4)
        for check in self.m["verification"]["checks"]:
            if check["check_id"] in self.m["unit_plan"]["units"]["U-1"]["required_check_ids"]:
                paths = self.h.check_inputs.required_paths(self.h.api().Checker(self.p.root, self.m), check)
                check.update(executed_at=self.base.now(), run_id=run["run_id"], runtime_observation_ref=runtime,
                    evaluated_source_hashes={path: self.p.hash(path) for path in paths},
                    evaluated_execution_inputs=self.h.observe_execution_inputs(self.p.root, self.m, "U-1", self.inputs, check_id=check["check_id"]))
        settlement_body = {
            "event": "execution_group_settlement", "version": 1, "unit_id": "U-1", "run_id": run["run_id"],
            "group_id": "synthetic-group", "check_ids": list(self.m["unit_plan"]["units"]["U-1"]["required_check_ids"]), "isolation": "independent", "status": "settled",
            "producer_state": "stopped", "cleanup_state": "complete", "accounting_state": "complete",
            "pending_actions": [], "unknown_outcomes": [], "open_resources": [], "completed_at": self.base.now()}
        settlement_body.update(settlement_changes or {})
        self.settlement = self.p.evidence("forge/runs/group-settlement.json", settlement_body)
        if not seal:
            return
        self.seal = self.h.seal_check(self.p.root, self.m, "U-1", "QA-02", self.settlement, self.inputs)
        self.check["seal_ref"] = self.seal
        self.original = copy.deepcopy(self.check)
        if before_attempt:
            before_attempt()
        self.attempt = self.h.capture_attempt(self.p.root, self.m, "U-1", self.context, run["run_id"], "interrupted", self.inputs)
        run["attempt_ref"] = self.attempt

    def resume(self, reuse=True):
        return self.h.capture_continuation(self.p.root, self.m, "U-1", self.attempt,
                                           "synthetic-continuation", self.inventory(), reuse=reuse)

    def test_fine_inputs_ignore_unrelated_code_and_preserve_original_result(self):
        self.start_and_seal()
        self.assertEqual({"src/alpha.txt"}, set(self.check["evaluated_execution_inputs"]))
        self.p.write("src/other.txt", "Changed unrelated implementation.\n")
        continued = self.resume()
        current = next(item for item in continued["manifest"]["verification"]["checks"] if item["check_id"] == "QA-02")
        self.assertEqual("passed", current["execution_status"])
        for field in ("run_id", "executed_at", "evidence", "evaluated_execution_inputs"):
            self.assertEqual(self.original[field], current[field])
        self.assertEqual("not_completed", self.base.read(self.attempt)["acceptance"])
        self.h.validate_transition(self.p.root, self.m, continued["manifest"], {})
        self.m.clear(); self.m.update(continued["manifest"])
        report = self.base.report("implementation", "start", "U-1")
        self.assertEqual("passed", report["result"], report)
        run = self.m["unit_runs"]["U-1"]
        run.update(status="running", started_at=self.base.now(),
                   development_plan_hash=self.p.hash("docs/development-plan.md"), approved_baseline_id="B-1")
        report = self.base.report("implementation", "complete", "U-1")
        self.assertEqual("passed", report["result"], report)

    def test_changed_dependency_is_reset_not_relabelled(self):
        self.start_and_seal()
        self.p.write("src/alpha.txt", "Changed checked code.\n")
        continued = self.resume()
        current = next(item for item in continued["manifest"]["verification"]["checks"] if item["check_id"] == "QA-02")
        self.assertEqual("not_run", current["execution_status"])
        self.assertIn("dependency changed", continued["rerun_reasons"]["QA-02"])

    def test_explicit_fresh_checks_and_tampered_seal_fail_closed(self):
        self.start_and_seal()
        continued = self.resume(reuse=False)
        current = next(item for item in continued["manifest"]["verification"]["checks"] if item["check_id"] == "QA-02")
        self.assertEqual("not_run", current["execution_status"])
        (self.p.root / self.seal["path"]).write_text("{}")
        with self.assertRaises(ValueError):
            self.resume()

    def install_continuation(self, continued):
        self.m.clear()
        self.m.update(continued["manifest"])
        self.m["unit_runs"]["U-1"].update(status="running", started_at=self.base.now(),
            development_plan_hash=self.p.hash("docs/development-plan.md"), approved_baseline_id="B-1")

    def configure_dependencies(self, paths):
        self.dependencies = list(paths)
        self.m["verification"]["source_sets"]["component"].extend(paths)
        self.p.sync_unit_contract()
        content = (self.p.root / "docs/qa-checklist.md").read_text().split("## Source sets")[0]
        self.p.write("docs/qa-checklist.md", content + "## Source sets\n\n```json\n" + json.dumps(self.m["verification"]["source_sets"]) + "\n```\n")
        self.p.refresh()
        self.m["verification"]["source_hashes"] = {name: self.p.hash(name) for name in ("docs/qa-checklist.md", "docs/dod-evals.md")}
        self.p.authorize()

    def test_repeated_interruption_keeps_original_identity_and_can_complete(self):
        self.start_and_seal()
        original_attempt = self.attempt
        continued = self.resume()
        self.install_continuation(continued)
        run = self.m["unit_runs"]["U-1"]
        second = self.h.capture_attempt(self.p.root, self.m, "U-1", continued["context_ref"], run["run_id"], "interrupted")
        run["attempt_ref"] = second
        third = self.h.capture_continuation(self.p.root, self.m, "U-1", second, "synthetic-third-run", self.inventory())
        check = next(item for item in third["manifest"]["verification"]["checks"] if item["check_id"] == "QA-02")
        self.assertEqual(original_attempt, check["reused_from"]["attempt_ref"])
        self.assertEqual(self.original["executed_at"], check["executed_at"])
        self.assertEqual("passed", check["execution_status"])
        self.install_continuation(third)
        run = self.m["unit_runs"]["U-1"]
        run.update(status="completed", completed_at=self.base.now())
        completed = self.h.capture_completion(self.p.root, self.m, "U-1", third["context_ref"], run["run_id"])
        self.h.validate_completion(self.p.root, completed)
        self.assertEqual("not_completed", self.base.read(original_attempt)["acceptance"])

    def test_changes_between_seal_and_attempt_reset_only_current_claim(self):
        self.start_and_seal(before_attempt=lambda: self.p.write("src/alpha.txt", "Changed after sealing.\n"))
        current = self.resume()
        check = next(item for item in current["manifest"]["verification"]["checks"] if item["check_id"] == "QA-02")
        self.assertEqual("not_run", check["execution_status"])
        self.assertIn("dependency changed", current["rerun_reasons"]["QA-02"])
        self.assertNotIn("src/other.txt", self.base.read(self.seal)["files"])

    def test_stale_inherited_check_remains_archivable_then_reruns(self):
        self.start_and_seal()
        continued = self.resume()
        self.install_continuation(continued)
        self.p.write("src/alpha.txt", "Changed after continuation.\n")
        run = self.m["unit_runs"]["U-1"]
        second = self.h.capture_attempt(self.p.root, self.m, "U-1", continued["context_ref"], run["run_id"], "interrupted")
        run["attempt_ref"] = second
        third = self.h.capture_continuation(self.p.root, self.m, "U-1", second, "synthetic-third-run", self.inventory())
        self.assertIn("dependency changed", third["rerun_reasons"]["QA-02"])

    def test_declared_fixture_assertion_and_shared_configuration_changes_rerun(self):
        paths = ["tests/fixture.json", "tests/assertions.py", "config/shared.json"]
        for path in paths:
            self.p.write(path, "Original authored dependency.\n")
        self.configure_dependencies(paths)
        self.start_and_seal()
        for path in paths:
            with self.subTest(path=path):
                self.p.write(path, "Changed authored dependency.\n")
                self.assertIn("dependency changed", self.resume()["rerun_reasons"]["QA-02"])
                self.p.write(path, "Original authored dependency.\n")

    def test_new_tree_member_invalidates_check(self):
        self.tree_inputs = True
        self.start_and_seal()
        self.p.write("src/new-input.txt", "New file participates in selected tree.\n")
        self.assertIn("dependency changed", self.resume()["rerun_reasons"]["QA-02"])

    def test_unsettled_or_unknown_groups_cannot_be_sealed(self):
        self.start_and_seal(seal=False)
        body = self.base.read(self.settlement)
        for change in ({"producer_state": "running"}, {"cleanup_state": "incomplete"}, {"accounting_state": "incomplete"},
                       {"unknown_outcomes": ["unknown"]}, {"pending_actions": ["pending"]}, {"open_resources": ["active"]}):
            with self.subTest(change=change):
                reference = self.p.evidence("forge/runs/invalid-settlement.json", {**body, **change})
                with self.assertRaises(ValueError):
                    self.h.seal_check(self.p.root, self.m, "U-1", "QA-02", reference, self.inputs)

    def add_second_check(self, *, independent=False):
        extra = copy.deepcopy(self.check)
        extra["check_id"] = "QA-07"
        if independent:
            extra["acceptance"].update(source_set_ids=[], required_source_paths=["src/other.txt"])
        self.m["verification"]["checks"].append(extra)
        next(gate for gate in self.m["verification"]["gates"] if gate["gate_id"] == extra["gate_id"])["check_ids"].append("QA-07")
        trace = self.m["artifacts"]["qa-checklist"]["traceability"]
        definition = next(item for item in trace["definitions"] if item["id"] == "QA-02")
        trace["definitions"].append({**copy.deepcopy(definition), "id": "QA-07"})
        trace["links"].extend({**copy.deepcopy(item), "from": "QA-07"} for item in list(trace["links"]) if item["from"] == "QA-02")
        content = (self.p.root / "docs/qa-checklist.md").read_text().replace("## Checks\n", "## Checks\nQA-07 extra isolated check\n")
        self.p.write("docs/qa-checklist.md", content)
        self.m["unit_plan"]["acceptance"]["QA-07"] = copy.deepcopy(self.m["unit_plan"]["acceptance"]["QA-02"])
        self.m["unit_plan"]["units"]["U-1"]["required_check_ids"].append("QA-07")
        self.configure_dependencies([])

    def test_batch_sealing_validates_current_gate_once(self):
        self.add_second_check()
        self.start_and_seal(seal=False)
        calls = []
        original = self.h.api().Checker.run
        def track(checker, *args, **kwargs):
            if not hasattr(checker, "_history_stack"):
                calls.append(args)
            return original(checker, *args, **kwargs)
        with mock.patch.object(self.h.api().Checker, "run", track):
            seals = self.h.seal_checks(self.p.root, self.m, "U-1", ["QA-02", "QA-07"], self.settlement, self.inputs)
        self.assertEqual({"QA-02", "QA-07"}, set(seals))
        self.assertEqual(1, len(calls))

    def test_completed_unit_identifies_only_check_with_changed_inputs(self):
        self.add_second_check(independent=True)
        self.start_and_seal()
        run = self.m["unit_runs"]["U-1"]
        run.pop("attempt_ref")
        run.update(status="completed", completed_at=self.base.now())
        completed = self.h.capture_completion(self.p.root, self.m, "U-1", self.context, run["run_id"])
        self.m["unit_runs"]["U-1"] = {"status": "completed", "completion_ref": completed}
        self.p.write("src/alpha.txt", "Changed only first check's source.\n")
        report = self.base.report()
        assessment = report["unit_history"]["units"]["U-1"]
        self.assertTrue(assessment["historical_valid"], report)
        self.assertEqual("needs_revalidation", assessment["current_applicability"])
        self.assertEqual(["QA-02"], assessment["revalidation_check_ids"])

    def test_old_contract_rejects_even_pending_reuse_fields(self):
        self.m.update(checker_contract_version=2, unit_contract_version=2)
        self.check.update(seal_ref={"path": "forge/missing.json", "content_hash": "0" * 64}, reused_from={})
        self.base.assert_blocked(self.base.report())

    def test_changed_check_diagnostics_and_unknown_ownership_are_conservative(self):
        import check_inputs
        previous = {"inputs": {}, "bindings": {}, "environment": {},
            "execution_inputs": {key: {"mode": "file"} for key in ("a", "b", "unowned")},
            "execution_fingerprints": {key: "old" for key in ("a", "b", "unowned")},
            "check_execution_fingerprints": {"A": {"a": "old"}, "B": {"b": "old"}}}
        current = copy.deepcopy(previous)
        current["execution_fingerprints"]["a"] = "new"
        current["check_execution_fingerprints"]["A"]["a"] = "new"
        self.assertEqual(["A"], check_inputs.changed_checks(previous, current, ["A", "B"]))
        current["execution_fingerprints"]["unowned"] = "new"
        self.assertEqual(["A", "B"], check_inputs.changed_checks(previous, current, ["A", "B"]))

    def test_changed_environment_requires_fresh_check_and_old_probe_is_rejected(self):
        self.start_and_seal()
        with self.assertRaisesRegex(ValueError, "fresh owner review|new runtime observation"):
            self.h.capture_continuation(self.p.root, self.m, "U-1", self.attempt, "stale-runtime", self.inputs)
        runtime = self.h.observe_runtime(self.p.root, {"runtime": [sys.executable, "-c", "print('changed runtime identity')"]})
        inventory = self.inventory()
        inventory.update(environment=self.base.read(runtime)["environment"], runtime_observation_ref=runtime)
        continued = self.h.capture_continuation(self.p.root, self.m, "U-1", self.attempt, "new-environment", inventory)
        self.assertIn("environment changed", continued["rerun_reasons"]["QA-02"])

    def test_original_snapshot_does_not_grant_current_authority(self):
        self.start_and_seal()
        self.m.pop("implementation_gate")
        with self.assertRaises(ValueError):
            self.resume()

    def test_seal_cannot_forge_runtime_applicability(self):
        original = self.h.seal_check
        def forged(*args, **kwargs):
            reference = original(*args, **kwargs)
            record = self.base.read(reference)
            record["input_inventory"]["environment"] = {"fabricated": "runtime"}
            return self.h.store_record(self.p.root, "sealed-checks", record)
        with mock.patch.object(self.h, "seal_check", forged):
            self.start_and_seal()
        with self.assertRaisesRegex(ValueError, "sealed inventory"):
            self.resume()

    def test_v3_preserves_approved_correction_validation(self):
        from test_authorization_corrections import AuthorizationCorrectionTests
        case = AuthorizationCorrectionTests("runTest")
        # This fixture is composed directly rather than invoking an unrelated test.
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.m.update(checker_contract_version=3, unit_contract_version=3)
        case.correction(("docs/development-plan.md", "docs/qa-checklist.md"))
        self.assertEqual([], case.auth_issues())

    def test_later_run_finding_does_not_rewrite_seal_and_still_blocks_completion(self):
        finding = {"severity": "P1", "release_effect": "blocking", "status": "open", "detail": "Synthetic later global blocker"}
        self.start_and_seal(before_attempt=lambda: self.m["unit_runs"]["U-1"]["findings"].append(finding))
        self.assertEqual([], self.base.read(self.seal)["run"]["findings"])
        current = self.resume()
        self.assertEqual([finding], current["manifest"]["unit_runs"]["U-1"]["findings"])
        self.install_continuation(current)
        report = self.base.report("implementation", "complete", "U-1")
        self.base.assert_blocked(report)
        self.assertIn("blocking finding", str(report))

    def test_seal_inventory_is_bounded_to_own_inputs_and_context_reference(self):
        self.start_and_seal()
        sealed = self.base.read(self.seal)
        self.assertEqual({"execution_inputs", "execution_fingerprints"}, set(sealed["input_inventory"]))
        self.assertEqual({"src/alpha.txt"}, set(sealed["input_inventory"]["execution_inputs"]))
        self.assertEqual(self.context, sealed["context_ref"])
        self.assertNotIn("bindings", sealed["input_inventory"])

    def test_unreviewed_dependencies_keep_whole_unit_fallback(self):
        self.check["acceptance"].pop("dependency_review")
        self.check["acceptance"].pop("reuse_policy")
        self.configure_dependencies([])
        inventory = self.inventory()
        whole = self.h.observe_execution_inputs(self.p.root, self.m, "U-1", inventory)
        observed = self.h.observe_execution_inputs(self.p.root, self.m, "U-1", inventory, check_id="QA-02")
        self.assertEqual(whole, observed)
        self.assertIn("src/other.txt", observed)

    def test_source_sets_are_canonical_and_unknown_names_rejected(self):
        self.assertEqual("passed", self.base.report()["result"])
        self.m["verification"]["source_sets"]["component"].append("src/unreviewed.txt")
        self.base.assert_blocked(self.base.report())


if __name__ == "__main__":
    unittest.main()
