"""Self-contained unit execution tests using isolated synthetic projects."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest

from test_sdd_check import Project, SCRIPT, sdd


class UnitExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-unit-contract-")
        self.addCleanup(self.temp.cleanup)
        self.p = Project(self.temp.name)
        self.m = self.p.manifest
        plan = self.m["unit_plan"]
        plan["order"] = ["U-1", "U-2", "U-3"]
        plan["units"] = {
            key: {"scope": scope, "owner": "fixture executor", "kind": kind,
                  "construction_dependencies": deps, "implementation_paths": [path], "required_check_ids": checks}
            for key, scope, kind, deps, path, checks in (
                ("U-1", "Component alpha", "implementation", [], "src/alpha.txt", ["QA-02"]),
                ("U-2", "Component beta", "implementation", [], "src/beta.txt", ["QA-03"]),
                ("U-3", "Integrated component behavior", "integration", ["U-1", "U-2"], "src/integration.txt", ["QA-01", "QA-04"]))}
        for check in self.m["verification"]["checks"]:
            key = check["check_id"]
            owner = "U-1" if key == "QA-02" else "U-2" if key == "QA-03" else "U-3"
            plan["acceptance"][key]["owner_unit"] = owner
            check["acceptance"].update(level="integration" if owner == "U-3" else "unit",
                evidence_mode="real_consumers" if owner == "U-3" else "component",
                required_source_paths=plan["units"][owner]["implementation_paths"])
        trace = self.m["artifacts"]["development-plan"]["traceability"]
        for unit in ("U-2", "U-3"):
            trace["definitions"].append({"id": unit, "kind": "unit", "required": True,
                "definition_ref": {"path": "docs/development-plan.md", "heading": "## Definition"}})
        for obligation in ("FR-01", "NFR-02", "STATE-01"):
            trace["links"].append({"from": "U-3", "to": obligation, "relation": "implements",
                "definition_ref": {"path": "docs/development-plan.md", "heading": "## Definition"}})
        path = "docs/development-plan.md"
        self.p.write(path, (self.p.root / path).read_text().replace("## Definition\n", "## Definition\nU-2 U-3\n"))
        self.sync()

    def sync(self):
        self.p.sync_unit_contract()
        self.p.authorize()

    def report(self, action=None, unit=None, release=False):
        return sdd.Checker(self.p.root, self.m).run("release" if release else "implementation", unit_action=action, unit_id=unit)

    def blocked(self, fragment, action=None, unit=None, release=False):
        report = self.report(action, unit, release)
        self.assertNotEqual("passed", report["result"], report)
        self.assertTrue(any(fragment in issue["detail"] or fragment == issue["code"] for issue in report["issues"]), report)

    def begin(self, unit, minute):
        self.m.setdefault("unit_runs", {})[unit] = {"status": "running", "started_at": f"2026-08-20T10:{minute:02}:00Z",
            "development_plan_hash": self.p.hash("docs/development-plan.md"), "approved_baseline_id": "B-1", "findings": []}
        for path in self.m["unit_plan"]["units"][unit]["implementation_paths"]:
            self.p.write(path, "Synthetic implementation, not product work.\n")

    def evidence(self, unit, minute):
        for key in self.m["unit_plan"]["units"][unit]["required_check_ids"]:
            check = next(x for x in self.m["verification"]["checks"] if x["check_id"] == key)
            evidence = self.p.evidence("forge/evidence/" + key + ".json", {"synthetic_fixture": True, "not_real_product_validation": True})
            check.update(execution_status="passed", executor="synthetic test runner", executed_at=f"2026-08-20T10:{minute:02}:00Z",
                evidence=[{**evidence, "kind": sdd.GATE_KINDS.get(check["gate_id"], "security")}, {**evidence, "kind": "integration"}],
                execution_mode=check["acceptance"]["evidence_mode"], evaluated_plan_hash=self.p.hash("docs/development-plan.md"),
                evaluated_source_hashes={p.relative_to(self.p.root).as_posix(): self.p.hash(p.relative_to(self.p.root).as_posix()) for p in (self.p.root / "src").glob("*.txt")})

    def complete(self, unit, minute):
        self.begin(unit, minute)
        self.evidence(unit, minute + 1)
        self.m["unit_runs"][unit].update(status="completed", completed_at=f"2026-08-20T10:{minute + 2:02}:00Z")

    def exception(self, target="U-2", prior=None, **changes):
        event = {"event": "unit_sequence_exception", "role": "user", "message": "Start this independent unit before the named unfinished unit.",
            "prompt_id": "synthetic-user-exception", "received_at": "2026-08-20T10:02:30Z",
            "development_plan_hash": self.p.hash("docs/development-plan.md"), "approved_baseline_id": "B-1",
            "unit_id": target, "prior_unit_ids": prior or ["U-1"], **changes}
        self.m["unit_sequence_exceptions"] = [self.p.evidence("forge/runs/sequence-exception.json", event)]

    def test_plan_and_first_start_pass_with_prepared_unrun_checks(self):
        self.assertEqual("passed", self.p.run(after=True)["result"])
        self.assertEqual("passed", self.report("start", "U-1")["result"])
        self.assertTrue(all(x["execution_status"] == "not_run" for x in self.m["verification"]["checks"]))

    def test_forward_acceptance_prerequisite_blocks_sequential_plan(self):
        self.m["unit_plan"]["acceptance"]["QA-02"]["prerequisite_units"] = ["U-2"]
        self.sync()
        self.blocked("forward acceptance/construction prerequisite")

    def test_combined_construction_and_acceptance_cycle(self):
        self.m["unit_plan"]["units"]["U-2"]["construction_dependencies"] = ["U-1"]
        self.m["unit_plan"]["acceptance"]["QA-02"]["prerequisite_units"] = ["U-2"]
        self.sync()
        self.blocked("combined construction/acceptance: dependency cycle")

    def test_check_owner_edges_and_check_cycles(self):
        self.m["unit_plan"]["acceptance"]["QA-02"]["prerequisite_checks"] = ["QA-03"]
        self.sync()
        self.blocked("forward acceptance")
        self.m["unit_plan"]["acceptance"]["QA-03"]["prerequisite_checks"] = ["QA-02"]
        self.sync()
        self.blocked("acceptance checks: dependency cycle")

    def test_missing_invalid_and_duplicate_acceptance_ownership(self):
        original = copy.deepcopy(self.m["unit_plan"])
        for mutate in (
                lambda p: p["acceptance"].pop("QA-02"),
                lambda p: p["acceptance"]["QA-02"].update(owner_unit="UNKNOWN"),
                lambda p: p["units"]["U-2"]["required_check_ids"].append("QA-02")):
            self.m["unit_plan"] = copy.deepcopy(original)
            mutate(self.m["unit_plan"])
            self.sync()
            self.blocked("unit_contract")

    def test_unknown_references_and_malformed_lists(self):
        original = copy.deepcopy(self.m["unit_plan"])
        for field, value in (("prerequisite_units", ["UNKNOWN"]), ("prerequisite_checks", ["UNKNOWN"]),
                             ("obligation_ids", ["FR-UNKNOWN"]), ("prerequisite_units", "U-2")):
            self.m["unit_plan"] = copy.deepcopy(original)
            self.m["unit_plan"]["acceptance"]["QA-02"][field] = value
            self.sync()
            self.blocked("unit_contract")

    def test_component_pass_cannot_remove_full_requirement_acceptance(self):
        for check in self.m["verification"]["checks"]:
            check["acceptance"].update(level="unit", evidence_mode="component")
        self.sync()
        self.blocked("full integration/release acceptance ownership")

    def test_integration_requires_integration_owner(self):
        self.m["unit_plan"]["units"]["U-3"]["kind"] = "implementation"
        self.sync()
        self.blocked("integration ownership")

    def test_canonical_definitions_prevent_metadata_only_downgrade(self):
        self.m["verification"]["checks"][0]["acceptance"]["evidence_mode"] = "component"
        self.blocked("canonical JSON and projection differ")
        self.sync()
        self.blocked("real consumers")

    def test_pending_failed_deferred_and_blocked_checks_prevent_completion(self):
        self.begin("U-1", 3)
        check = self.m["verification"]["checks"][1]
        for status in ("not_run", "failed", "deferred", "blocked", "not_applicable"):
            with self.subTest(status=status):
                check.update(execution_status=status, rationale="Synthetic unfinished check")
                self.blocked("unit_contract", "complete", "U-1")

    def test_missing_stale_evidence_and_plan_bindings_prevent_completion(self):
        self.begin("U-1", 3)
        self.evidence("U-1", 4)
        check = self.m["verification"]["checks"][1]
        original = copy.deepcopy(check)
        for field, value in (("evidence", []), ("evaluated_source_hashes", {}), ("evaluated_plan_hash", "0" * 64),
                             ("executed_at", "2026-08-20T10:01:00Z"), ("executed_at", "2999-01-01T00:00:00Z")):
            check.clear(); check.update(copy.deepcopy(original)); check[field] = value
            self.blocked("unit_contract", "complete", "U-1")
        check.clear(); check.update(original)
        self.p.write("src/alpha.txt", "Changed after run")
        self.blocked("unit_stale_evidence", "complete", "U-1")

    def test_stale_evidence_files_and_open_blocking_findings(self):
        self.begin("U-1", 3)
        self.evidence("U-1", 4)
        run = self.m["unit_runs"]["U-1"]
        run["findings"] = [{"severity": "P1", "release_effect": "blocking", "status": "open"}]
        self.blocked("unresolved blocking finding", "complete", "U-1")
        run["findings"] = []
        check = self.m["verification"]["checks"][1]
        check["findings"] = [{"severity": "P2", "release_effect": "blocking", "status": "open"}]
        self.blocked("unresolved blocking finding", "complete", "U-1")
        check["findings"] = []
        self.p.write(check["evidence"][0]["path"], "Changed evidence")
        self.blocked("unit_stale_evidence", "complete", "U-1")

    def test_later_start_requires_completed_prior_or_explicit_exception(self):
        self.blocked("incomplete at start", "start", "U-2")
        self.exception()
        self.assertEqual("passed", self.report("start", "U-2")["result"])
        self.begin("U-2", 3)
        self.assertEqual("passed", self.report("start", "U-2")["result"])

    def test_exceptions_cannot_waive_dependencies_or_authorize_implementation(self):
        self.exception("U-3", ["U-1", "U-2"])
        self.blocked("cannot waive")
        self.exception()
        self.m["implementation_gate"]["state"] = "awaiting_implementation_prompt"
        self.blocked("implementation_not_authorized", "start", "U-2")

    def test_stale_nonuser_future_and_late_exceptions_are_rejected(self):
        for change in ({"role": "assistant"}, {"message": "continue"}, {"development_plan_hash": "0" * 64},
                       {"prior_unit_ids": ["UNKNOWN"]}, {"received_at": "2999-01-01T00:00:00Z"}):
            self.exception(**change)
            self.blocked("unit_contract", "start", "U-2")
        self.exception(received_at="2026-08-20T10:04:00Z")
        self.begin("U-2", 3)
        self.blocked("incomplete at start", "start", "U-2")

    def test_completed_label_is_revalidated_before_later_start(self):
        self.complete("U-1", 3)
        self.assertEqual("passed", self.report("start", "U-2")["result"])
        self.m["verification"]["checks"][1]["execution_status"] = "deferred"
        self.blocked("required acceptance is not passed", "start", "U-2")

    def test_completion_cannot_retroactively_authorize_prior_start(self):
        self.complete("U-1", 5)
        self.begin("U-2", 3)
        self.blocked("incomplete at start")

    def test_valid_components_then_required_real_integration(self):
        self.complete("U-1", 3)
        self.complete("U-2", 6)
        self.assertEqual("passed", self.report("start", "U-3")["result"])
        self.blocked("required_check_incomplete", release=True)
        self.begin("U-3", 9)
        self.evidence("U-3", 10)
        self.assertEqual("passed", self.report("complete", "U-3")["result"])
        self.m["unit_runs"]["U-3"].update(status="completed", completed_at="2026-08-20T10:11:00Z")
        self.assertEqual("passed", self.report(release=True)["result"])
        self.m["verification"]["checks"][0]["execution_mode"] = "mock"
        self.blocked("mocks/fixtures", release=True)

    def test_integration_evidence_must_include_actual_consumers(self):
        self.complete("U-1", 3); self.complete("U-2", 6)
        self.begin("U-3", 9); self.evidence("U-3", 10)
        self.m["verification"]["checks"][0]["evaluated_source_hashes"].pop("src/beta.txt")
        self.blocked("consumer paths", "complete", "U-3")

    def test_advisory_owned_check_with_blocking_finding_prevents_completion(self):
        # Advisory classification does not erase a subsequently discovered blocker.
        check = self.m["verification"]["checks"][2]
        check["acceptance"]["required"] = False
        self.m["verification"]["gates"][2]["required"] = False
        plan = self.m["unit_plan"]
        plan["units"]["U-2"]["required_check_ids"] = ["QA-02"]
        plan["units"]["U-1"]["required_check_ids"] = ["QA-01", "QA-04"]
        # Use two units for this focused case; full acceptance remains integration-owned.
        plan["order"] = ["U-1", "U-2"]
        del plan["units"]["U-3"]
        plan["units"]["U-1"]["kind"] = "integration"
        for key in ("QA-01", "QA-04"):
            plan["acceptance"][key]["owner_unit"] = "U-1"
            next(x for x in self.m["verification"]["checks"] if x["check_id"] == key)["acceptance"]["required_source_paths"] = ["src/alpha.txt"]
        plan["acceptance"]["QA-02"]["owner_unit"] = "U-2"
        trace = self.m["artifacts"]["development-plan"]["traceability"]
        trace["definitions"] = [x for x in trace["definitions"] if x["id"] != "U-3"]
        trace["links"] = [x for x in trace["links"] if x["from"] != "U-3"]
        self.sync()
        self.complete("U-1", 3)
        self.begin("U-2", 6); self.evidence("U-2", 7)
        check["findings"] = [{"severity": "P1", "release_effect": "blocking", "status": "open"}]
        self.blocked("unresolved blocking finding", "complete", "U-2")

    def test_prerequisite_checks_need_earlier_passing_runs(self):
        self.m["unit_plan"]["acceptance"]["QA-01"]["prerequisite_checks"] = ["QA-04"]
        self.sync()
        self.complete("U-1", 3); self.complete("U-2", 6)
        self.begin("U-3", 9); self.evidence("U-3", 10)
        self.m["verification"]["checks"][3]["executed_at"] = "2026-08-20T10:12:00Z"
        self.blocked("outside current unit run", "complete", "U-3")

    def test_missing_records_require_migration_but_do_not_block_early_authoring(self):
        self.m.pop("unit_contract_version")
        self.assertEqual("passed", self.p.run("prd")["result"])
        self.assertEqual("migration_required", self.p.run(after=True)["result"])
        self.blocked("migration_required", "start", "U-1")
        self.m["unit_contract_version"] = 1
        self.m.pop("unit_plan")
        self.blocked("unit_contract", "start", "U-1")

    def test_plan_change_requires_fresh_implementation_authorization(self):
        self.m["unit_plan"]["units"]["U-1"]["scope"] += " revised"
        self.p.sync_unit_contract()
        self.blocked("implementation_not_authorized", "start", "U-1")

    def test_future_authorization_cannot_start_first_unit(self):
        gate = self.m["implementation_gate"]
        gate.update(awaiting_at="2999-01-01T00:01:00Z", prompt_received_at="2999-01-01T00:02:00Z", released_at="2999-01-01T00:02:01Z")
        receipt = sdd.read_json(self.p.root / gate["prompt_receipt"]["path"])
        receipt["received_at"] = gate["prompt_received_at"]
        gate["prompt_receipt"] = self.p.evidence(gate["prompt_receipt"]["path"], receipt)
        self.blocked("future implementation authorization", "start", "U-1")

    def test_required_check_cannot_rely_on_unfinished_advisory_owner_acceptance(self):
        plan = self.m["unit_plan"]
        check = self.m["verification"]["checks"][2]
        check["acceptance"]["required"] = False
        self.m["verification"]["gates"][2]["required"] = False
        # U-1 owns a required component check and an advisory prerequisite; U-2
        # is removed to isolate the advisory check's owning-run time boundary.
        plan["order"] = ["U-1", "U-3"]
        del plan["units"]["U-2"]
        plan["units"]["U-3"]["construction_dependencies"] = ["U-1"]
        plan["acceptance"]["QA-03"]["owner_unit"] = "U-1"
        check["acceptance"]["required_source_paths"] = ["src/alpha.txt"]
        plan["acceptance"]["QA-01"]["prerequisite_checks"] = ["QA-03"]
        trace = self.m["artifacts"]["development-plan"]["traceability"]
        trace["definitions"] = [x for x in trace["definitions"] if x["id"] != "U-2"]
        self.sync()
        self.complete("U-1", 3)  # closes at 10:05
        self.begin("U-3", 6); self.evidence("U-3", 9)
        template = copy.deepcopy(self.m["verification"]["checks"][1])
        check.update({key: template[key] for key in ("executor", "evidence", "execution_mode", "evaluated_plan_hash", "evaluated_source_hashes")})
        check.update(execution_status="passed", executed_at="2026-08-20T10:08:00Z")
        check["evidence"] = [{**x, "kind": "representative_user"} for x in template["evidence"]]
        self.blocked("required check prerequisites must be required acceptance", "complete", "U-3")

    def test_cli_boundaries_are_read_only_and_fail_closed(self):
        self.p.save()
        before = (self.p.root / "forge/sdd-manifest.json").read_bytes()
        for option, unit, expected in (("--start-unit", "U-1", 0), ("--start-unit", "U-2", 1),
                                       ("--complete-unit", "U-1", 1), ("--start-unit", "UNKNOWN", 1)):
            result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.p.root), option, unit], capture_output=True, text=True)
            self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
            self.assertIn(json.loads(result.stdout)["result"], ("passed", "blocked"))
        self.assertEqual(before, (self.p.root / "forge/sdd-manifest.json").read_bytes())

    def test_boundary_api_cannot_skip_implementation_gates(self):
        for node, action in (("prd", "start"), ("implementation", "unknown")):
            report = sdd.Checker(self.p.root, self.m).run(node, unit_action=action, unit_id="U-1")
            self.assertIn("unit_boundary", {x["code"] for x in report["issues"]})

    def test_localized_contract_headings_and_explicit_owner_paths(self):
        plan = self.m["unit_plan"]
        for path, old, new in (("docs/development-plan.md", "## Unit Execution Contract", "## Порядок виконання"),
                               ("docs/qa-checklist.md", "## Acceptance Contract", "## Умови приймання")):
            self.p.write(path, (self.p.root / path).read_text(encoding="utf-8").replace(old, new))
        plan["definition_ref"]["heading"] = "## Порядок виконання"
        self.m["verification"]["acceptance_ref"]["heading"] = "## Умови приймання"
        self.sync()
        self.assertEqual("passed", self.report("start", "U-1")["result"])
        plan["definition_ref"]["path"] = "docs/qa-checklist.md"
        self.sync()
        self.blocked("belongs to development plan")


if __name__ == "__main__":
    unittest.main()
