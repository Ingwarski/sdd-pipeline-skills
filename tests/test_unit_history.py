"""Completion history regressions using isolated, explicitly synthetic projects.

The frozen predecessor fixture is the byte-for-byte checker from commit
36d7952c14d6807538ca0e40011bce89999cd48b, gzip-compressed with mtime=0.
These records exercise validators; they are not real approvals or product tests.
"""

import copy
from datetime import datetime, timezone
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_unit_execution as unit_fixture
from test_sdd_check import CONTRACT, ROOT, SCRIPT, sdd


PREDECESSOR_SHA256 = "a7c8975c9abf9d4e9753c6c1c9473c56f84fea076559b79f3962d4a7257e31a6"


class UnitHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_temp = tempfile.TemporaryDirectory(prefix="sdd-frozen-predecessor-")
        cls.addClassCleanup(cls.old_temp.cleanup)
        old_skills = Path(cls.old_temp.name) / "skills"
        shutil.copytree(ROOT / "skills", old_skills,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        cls.old_script = old_skills / "to-sdd-pipeline/scripts/sdd_check.py"
        data = gzip.decompress((ROOT / "tests/fixtures/sdd-check-36d7952.py.gz").read_bytes())
        if sdd.digest(data) != PREDECESSOR_SHA256:
            raise AssertionError("frozen predecessor differs from reviewed commit 36d7952")
        cls.old_script.write_bytes(data)

    def setUp(self):
        self.fresh()

    def fresh(self):
        # Composition reuses fixture setup without rerunning its imported test class.
        self.fixture = unit_fixture.UnitExecutionTests("test_plan_and_first_start_pass_with_prepared_unrun_checks")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.p, self.m = self.fixture.p, self.fixture.m

    def old_report(self, *arguments):
        self.p.save()
        result = subprocess.run([sys.executable, str(self.old_script), "--project", str(self.p.root),
                                 *arguments], capture_output=True, text=True)
        self.assertTrue(result.stdout.strip(), result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(PREDECESSOR_SHA256, report["toolchain"]["checker_sha256"])
        return result, report

    def report(self, node="development-plan", action=None, unit=None):
        return sdd.Checker(self.p.root, self.m).run(node, after=node == "development-plan",
                                                    unit_action=action, unit_id=unit)

    def assert_blocked(self, report):
        self.assertNotEqual("passed", report["result"], report)
        self.assertTrue(report["issues"], report)

    def history(self):
        path = SCRIPT.with_name("sdd_history.py")
        spec = importlib.util.spec_from_file_location("sdd_history_test_helper", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def inventory(self, environment=None, unit="U-1"):
        sources = {artifact["path"]: {"mode": "full"}
                   for artifact in self.m["artifacts"].values()}
        # Existing shared prose applies to alpha; the separate structured plan
        # contains pending beta/integration allocations that can legitimately vary.
        sources["docs/development-plan.md"] = {"mode": "sections", "headings": ["## Definition"]}
        sources["docs/qa-checklist.md"] = {"mode": "sections", "headings": ["## Checks"]}
        inputs = set(self.m["unit_plan"]["units"][unit]["implementation_paths"])
        owned = {key for key, allocation in self.m["unit_plan"]["acceptance"].items() if allocation["owner_unit"] == unit}
        for check in self.m["verification"]["checks"]:
            if check["check_id"] in owned:
                inputs.update(check["acceptance"]["required_source_paths"])
        return {"review": {"reviewer": "synthetic-source-owner", "reviewed_at": self.now(),
                           "complete": True, "rationale": "Reviewed all canonical inputs and shared alpha definitions; synthetic fixture."},
                "sources": sources, "execution_inputs": {path: {"mode": "file"} for path in sorted(inputs)},
                "environment": environment or {"runtime": "synthetic-runtime-1"}}

    def read(self, ref):
        return json.loads((self.p.root / ref["path"]).read_text(encoding="utf-8"))

    def rewrite(self, ref, value):
        self.p.write(ref["path"], json.dumps(value, ensure_ascii=False) + "\n")
        ref["content_hash"] = self.p.hash(ref["path"])

    def stamp_evidence(self, helper, unit, inventory):
        observed = helper.observe_execution_inputs(self.p.root, self.m, unit, inventory)
        for check in self.m["verification"]["checks"]:
            if check["check_id"] in self.m["unit_plan"]["units"][unit]["required_check_ids"]:
                check["executed_at"] = self.now()
                check["evaluated_execution_inputs"] = copy.deepcopy(observed)

    def capture_alpha(self, *, finish=True):
        helper = self.history()
        self.m["checker_contract_version"] = 2
        self.m["unit_contract_version"] = 2
        inventory = self.inventory()
        context = helper.capture_context(self.p.root, self.m, "U-1", inventory)
        self.m.setdefault("execution_contexts", {})["U-1"] = context
        self.fixture.begin("U-1", 3)
        self.m["unit_runs"]["U-1"]["started_at"] = self.now()
        if not finish:
            return helper, inventory, context, None
        self.fixture.evidence("U-1", 4)
        self.stamp_evidence(helper, "U-1", inventory)
        self.m["unit_runs"]["U-1"].update(status="completed", completed_at=self.now())
        completion = helper.capture_completion(self.p.root, self.m, "U-1", context, "synthetic-alpha-run-1")
        self.m["unit_runs"]["U-1"] = {"status": "completed", "completion_ref": completion}
        self.p.save()
        return helper, inventory, context, completion

    def complete_current(self, helper, unit):
        inventory = self.inventory(unit=unit)
        context = helper.capture_context(self.p.root, self.m, unit, inventory)
        self.m.setdefault("execution_contexts", {})[unit] = context
        self.fixture.begin(unit, 3)
        self.m["unit_runs"][unit]["started_at"] = self.now()
        self.fixture.evidence(unit, 4)
        self.stamp_evidence(helper, unit, inventory)
        self.m["unit_runs"][unit].update(status="completed", completed_at=self.now())
        ref = helper.capture_completion(self.p.root, self.m, unit, context, "synthetic-current-" + unit)
        self.m["unit_runs"][unit] = {"status": "completed", "completion_ref": ref}
        self.p.save()
        return context, ref

    def pending_map(self):
        return {key: [key] for key in self.m["unit_plan"]["order"] if key != "U-1"}

    def preserve(self, helper, completion, inventory=None, mapping=None):
        applicability = helper.assess_completion(self.p.root, self.m, completion,
                                                 inventory or self.inventory(),
                                                 self.pending_map() if mapping is None else mapping)
        self.m["unit_runs"]["U-1"] = {"status": "completed", "completion_ref": completion,
                                       "applicability_ref": applicability}
        return applicability

    def revise_pending(self, suffix=" revised"):
        self.m["unit_plan"]["units"]["U-2"]["scope"] += suffix
        self.p.sync_unit_contract()
        self.m["state"] = "awaiting-implementation-prompt"
        self.m["implementation_gate"] = {"state": "awaiting_implementation_prompt",
                                          "development_plan_hash": self.p.hash("docs/development-plan.md"),
                                          "approved_baseline_id": "B-1", "awaiting_at": self.now()}

    def authorize_current(self):
        awaiting = self.m["implementation_gate"]["awaiting_at"]
        received = self.now()
        gate = {"state": "authorized_for_phase3", "development_plan_hash": self.p.hash("docs/development-plan.md"),
                "approved_baseline_id": "B-1", "prompt_id": "synthetic-revised-plan-prompt",
                "awaiting_at": awaiting, "prompt_received_at": received, "released_at": self.now()}
        gate["prompt_receipt"] = self.p.evidence("forge/runs/revised-plan-prompt.json", {
            "event": "implementation_prompt", "role": "user", "intent": "start_production_implementation",
            "message": "Implement the remaining units in this revised plan.", "prompt_id": gate["prompt_id"],
            "received_at": received, "development_plan_hash": gate["development_plan_hash"],
            "approved_baseline_id": "B-1", "synthetic_fixture": True})
        self.m["implementation_gate"] = gate

    def rename_pending(self, replacements):
        def rename(value):
            if isinstance(value, dict):
                return {replacements.get(key, key): rename(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rename(item) for item in value]
            return replacements.get(value, value) if isinstance(value, str) else value
        self.m["unit_plan"] = rename(self.m["unit_plan"])
        trace = self.m["artifacts"]["development-plan"]["traceability"]
        self.m["artifacts"]["development-plan"]["traceability"] = trace = rename(trace)
        for definition in trace["definitions"]:
            if definition["id"] in replacements.values():
                definition["definition_ref"]["heading"] = "## Pending unit definitions"
        linked_ids = []
        for link in trace["links"]:
            if link["from"] in replacements.values():
                link["definition_ref"]["heading"] = "## Pending unit definitions"
                linked_ids.extend((link["from"], link["to"]))
        path = "docs/development-plan.md"
        text = (self.p.root / path).read_text(encoding="utf-8")
        text = text.replace("\n## Unit Execution Contract", "\n## Pending unit definitions\n" +
                            " ".join(list(replacements.values()) + linked_ids) + "\n\n## Unit Execution Contract", 1)
        self.p.write(path, text)

    def add_pending_component(self, unit="U-4", check_id="QA-05"):
        plan = self.m["unit_plan"]
        path = "src/component-" + unit + ".txt"
        plan["units"][unit] = {"scope": "Pending gamma contribution", "owner": "fixture executor",
                               "kind": "implementation", "construction_dependencies": [],
                               "implementation_paths": [path], "required_check_ids": [check_id]}
        plan["order"] = sorted(plan["units"], key=lambda key: int(key.rsplit("-", 1)[1]))
        plan["acceptance"][check_id] = {"owner_unit": unit, "prerequisite_units": [],
                                        "prerequisite_checks": [], "obligation_ids": []}
        check = copy.deepcopy(next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-03"))
        check_heading = "## Pending check " + check_id
        check.update(check_id=check_id, definition_ref={"path": "docs/qa-checklist.md", "heading": check_heading})
        check["acceptance"]["required_source_paths"] = [path]
        self.m["verification"]["checks"].append(check)
        next(gate for gate in self.m["verification"]["gates"] if gate["gate_id"] == check["gate_id"])["check_ids"].append(check_id)
        for artifact, identifier, kind, heading, boundary in (
                ("development-plan", unit, "unit", "## Pending component " + unit, "## Unit Execution Contract"),
                ("qa-checklist", check_id, "check", check_heading, "## Acceptance Contract")):
            document = "docs/" + artifact + ".md"
            self.m["artifacts"][artifact]["traceability"]["definitions"].append({
                "id": identifier, "kind": kind, "required": True,
                "definition_ref": {"path": document, "heading": heading}})
            text = (self.p.root / document).read_text(encoding="utf-8")
            self.p.write(document, text.replace("\n" + boundary, "\n" + heading + "\n" + identifier + "\n\n" + boundary, 1))

    def test_version_one_retains_original_acceptance_and_plan_binding_rules(self):
        self.fixture.complete("U-1", 3)
        self.assertEqual("passed", self.report()["result"])
        result, old = self.old_report("--after", "development-plan")
        self.assertEqual(0, result.returncode, old)
        self.m["unit_plan"]["units"]["U-2"]["scope"] += " revised pending work"
        self.p.sync_unit_contract()
        self.assert_blocked(self.report())
        result, old = self.old_report("--after", "development-plan")
        self.assertNotEqual(0, result.returncode, old)

    def test_actual_frozen_predecessor_rejects_version_two_at_every_boundary(self):
        self.m["unit_contract_version"] = 2
        for arguments in (("--after", "development-plan"), ("--before", "implementation"),
                          ("--start-unit", "U-1"), ("--complete-unit", "U-1"),
                          ("--audit",), ("--before", "release")):
            with self.subTest(arguments=arguments):
                result, report = self.old_report(*arguments)
                self.assertNotEqual(0, result.returncode, report)
                self.assertTrue(any(issue["code"] == "migration_required" for issue in report["issues"]), report)

    def test_frozen_predecessor_rejects_top_level_version_gate(self):
        self.m["checker_contract_version"] = 2
        result, report = self.old_report("--before", "implementation")
        self.assertNotEqual(0, result.returncode, report)
        self.assertTrue(any(issue["code"] == "migration_required" for issue in report["issues"]), report)

    def applicability(self, report, expected, historical=True):
        result = report["unit_history"]["units"]["U-1"]
        self.assertEqual(historical, result["historical_valid"], report)
        self.assertEqual(expected, result["current_applicability"], report)
        if expected == "needs_revalidation":
            self.assertTrue(result["reasons"], report)

    def test_repeated_pending_edits_preserve_original_run_but_need_current_authority(self):
        helper, inventory, context, completion = self.capture_alpha()
        original = {ref["path"]: (self.p.root / ref["path"]).read_bytes() for ref in (context, completion)}
        for suffix in (" first correction", " second correction"):
            self.revise_pending(suffix)
            self.preserve(helper, completion)
            report = self.report()
            self.assertEqual("passed", report["result"], report)
            self.applicability(report, "applicable")
            self.assert_blocked(self.report("implementation", "start", "U-2"))
            self.assertEqual(completion, self.m["unit_runs"]["U-1"]["completion_ref"])
            self.p.save()
        self.assertEqual(original, {path: (self.p.root / path).read_bytes() for path in original})
        self.authorize_current()
        self.m["execution_contexts"]["U-2"] = helper.capture_context(self.p.root, self.m, "U-2", self.inventory(unit="U-2"))
        self.assertEqual("passed", self.report("implementation", "start", "U-2")["result"])

    def test_source_evidence_and_environment_changes_require_revalidation_without_rewriting_code(self):
        for mode in ("implementation", "evidence", "shared_qa", "plan_prose", "requirements", "architecture", "dod", "environment"):
            with self.subTest(mode=mode):
                self.fresh()
                helper, inventory, context, completion = self.capture_alpha()
                self.revise_pending()
                environment = None
                path = {"implementation": "src/alpha.txt", "evidence": "forge/evidence/QA-02.json",
                        "shared_qa": "docs/qa-checklist.md", "plan_prose": "docs/development-plan.md",
                        "requirements": "docs/prd.md", "architecture": "docs/architecture.md",
                        "dod": "docs/dod-evals.md"}.get(mode)
                if path:
                    text = (self.p.root / path).read_text(encoding="utf-8")
                    if mode in ("shared_qa", "plan_prose"):
                        text = text.replace("\n## ", "\n## ", 1)
                        heading = "## Checks" if mode == "shared_qa" else "## Definition"
                        text = text.replace(heading + "\n", heading + "\nChanged applicable acceptance wording.\n", 1)
                    else:
                        text += "\nChanged relevant input.\n"
                    self.p.write(path, text)
                else:
                    environment = {"runtime": "synthetic-runtime-2"}
                self.p.sync_unit_contract()
                self.preserve(helper, completion, self.inventory(environment))
                report = self.report()
                self.assertEqual("passed", report["result"], report)
                self.applicability(report, "needs_revalidation")
                before = (self.p.root / "src/alpha.txt").read_bytes()
                self.assert_blocked(self.report("implementation", "start", "U-2"))
                self.assertEqual(before, (self.p.root / "src/alpha.txt").read_bytes())

    def test_changed_actual_check_task_and_open_blocker_cannot_hide_in_unchanged_json_projection(self):
        for mode in ("task", "expected", "finding"):
            with self.subTest(mode=mode):
                self.fresh()
                helper, inventory, context, completion = self.capture_alpha()
                self.revise_pending()
                check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
                if mode == "finding":
                    check["findings"] = [{"severity": "P1", "release_effect": "blocking", "status": "open"}]
                else:
                    check["task" if mode == "task" else "expected_behavior"] = "New obligation absent from original successful run"
                self.preserve(helper, completion)
                report = self.report()
                self.applicability(report, "needs_revalidation")
                self.assert_blocked(self.report("implementation", "start", "U-2"))

    def test_completion_capture_rejects_untested_changes_and_unfinished_runs(self):
        for mode in ("changed_after_check", "running", "blocked", "invalid_authorization"):
            with self.subTest(mode=mode):
                self.fresh()
                helper, inventory, context, _ = self.capture_alpha(finish=False)
                self.fixture.evidence("U-1", 4)
                check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
                self.stamp_evidence(helper, "U-1", inventory)
                run = self.m["unit_runs"]["U-1"]
                run.update(status="completed", completed_at=self.now())
                if mode == "changed_after_check":
                    self.p.write("src/alpha.txt", "Different bytes after the successful synthetic check.\n")
                elif mode in ("running", "blocked"):
                    run.update(status=mode)
                    run.pop("completed_at")
                    if mode == "blocked":
                        run["reason"] = "Synthetic incomplete execution"
                else:
                    gate = self.m["implementation_gate"]
                    value = self.read(gate["prompt_receipt"])
                    value["message"] = "continue"
                    self.rewrite(gate["prompt_receipt"], value)
                with self.assertRaises(ValueError):
                    helper.capture_completion(self.p.root, self.m, "U-1", context, "synthetic-invalid-run")

    def test_capture_context_rejects_missing_approval_and_incomplete_owner_inventory(self):
        for mode in ("no_prompt", "missing_source", "missing_review", "mandatory_unused"):
            with self.subTest(mode=mode):
                self.fresh()
                helper = self.history()
                self.m.update(checker_contract_version=2, unit_contract_version=2)
                inventory = self.inventory()
                if mode == "no_prompt":
                    self.m["implementation_gate"] = {"state": "awaiting_implementation_prompt"}
                elif mode == "missing_source":
                    inventory["sources"].pop("docs/guardrails.md")
                elif mode == "missing_review":
                    inventory.pop("review")
                else:
                    inventory["sources"]["docs/prd.md"] = {"mode": "unused", "reason": "Pretending requirements do not matter"}
                with self.assertRaises(ValueError):
                    helper.capture_context(self.p.root, self.m, "U-1", inventory)

    def test_current_mixed_versions_and_disguised_history_are_rejected(self):
        for checker_version, unit_version, field in ((1, 2, None), (2, 1, None),
                                                    (1, 1, "execution_contexts"), (1, 1, "unit_runs")):
            with self.subTest(checker=checker_version, units=unit_version, field=field):
                self.fresh()
                self.m.update(checker_contract_version=checker_version, unit_contract_version=unit_version)
                if field == "execution_contexts":
                    self.m[field] = {"U-1": {"path": "forge/missing.json", "content_hash": "0" * 64}}
                elif field == "unit_runs":
                    self.m[field] = {"U-1": {"status": "completed", "completion_ref": {}, "applicability_ref": {}}}
                self.assert_blocked(self.report())

    def test_stage_and_activate_are_optimistic_and_do_not_mutate_live_state_early(self):
        helper, inventory, context, completion = self.capture_alpha()
        self.revise_pending()
        self.preserve(helper, completion)
        active_path = self.p.root / "forge/sdd-manifest.json"
        original_bytes = active_path.read_bytes()
        expected_hash = sdd.digest(original_bytes)
        candidate = helper.stage_candidate(self.p.root, self.m, expected_hash)
        self.assertEqual(original_bytes, active_path.read_bytes())
        # Another writer changing the live bytes invalidates this candidate.
        active_path.write_bytes(original_bytes + b"\n")
        with self.assertRaises(ValueError):
            helper.activate_candidate(self.p.root, candidate, expected_hash)
        self.assertEqual(original_bytes + b"\n", active_path.read_bytes())
        active_path.write_bytes(original_bytes)
        result = helper.activate_candidate(self.p.root, candidate, expected_hash)
        self.assertEqual("activated", result["status"])
        recovery = helper.recover_activation(self.p.root, result["journal_ref"])
        self.assertEqual("activated", recovery["status"])
        before = active_path.read_bytes()
        self.assertEqual(recovery, helper.recover_activation(self.p.root, result["journal_ref"]))
        self.assertEqual(before, active_path.read_bytes())

    def test_staged_candidate_does_not_activate_after_source_changes(self):
        helper, inventory, context, completion = self.capture_alpha()
        self.revise_pending()
        self.preserve(helper, completion)
        active = self.p.root / "forge/sdd-manifest.json"
        before = active.read_bytes()
        expected = sdd.digest(before)
        candidate = helper.stage_candidate(self.p.root, self.m, expected)
        self.p.write("src/alpha.txt", "Changed after candidate validation.\n")
        with self.assertRaises(ValueError):
            helper.activate_candidate(self.p.root, candidate, expected)
        self.assertEqual(before, active.read_bytes())

    def test_pending_additions_splits_merges_and_renumbering_preserve_completed_identity(self):
        for operation in ("addition", "split", "merge", "renumber"):
            with self.subTest(operation=operation):
                self.fresh()
                helper, inventory, context, completion = self.capture_alpha()
                if operation in ("addition", "split"):
                    self.rename_pending({"U-3": "U-5"})
                    self.add_pending_component()
                    self.m["unit_plan"]["units"]["U-5"]["construction_dependencies"].append("U-4")
                    mapping = {"U-2": ["U-2", "U-4"] if operation == "split" else ["U-2"], "U-3": ["U-5"]}
                    if operation == "addition":
                        mapping["__added__"] = ["U-4"]
                elif operation == "renumber":
                    self.rename_pending({"U-2": "U-7", "U-3": "U-8"})
                    mapping = {"U-2": ["U-7"], "U-3": ["U-8"]}
                else:
                    plan = self.m["unit_plan"]
                    plan["units"]["U-2"].update(scope="Merged beta and integration work", kind="integration",
                        construction_dependencies=["U-1"], implementation_paths=["src/beta.txt", "src/integration.txt"],
                        required_check_ids=["QA-01", "QA-03", "QA-04"])
                    del plan["units"]["U-3"]
                    plan["order"] = ["U-1", "U-2"]
                    for key in ("QA-01", "QA-03", "QA-04"):
                        plan["acceptance"][key]["owner_unit"] = "U-2"
                        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == key)
                        check["acceptance"].update(level="integration", evidence_mode="real_consumers")
                    trace = self.m["artifacts"]["development-plan"]["traceability"]
                    trace["definitions"] = [item for item in trace["definitions"] if item["id"] != "U-3"]
                    for link in trace["links"]:
                        if link["from"] == "U-3":
                            link["from"] = "U-2"
                    mapping = {"U-2": ["U-2"], "U-3": ["U-2"]}
                self.p.sync_unit_contract()
                self.m["implementation_gate"] = {"state": "awaiting_implementation_prompt"}
                self.preserve(helper, completion, mapping=mapping)
                report = self.report()
                self.assertEqual("passed", report["result"], report)
                self.applicability(report, "applicable")
                self.assertEqual(completion, self.m["unit_runs"]["U-1"]["completion_ref"])

    def test_missing_pending_mapping_and_lost_integration_obligations_are_rejected(self):
        helper, inventory, context, completion = self.capture_alpha()
        self.rename_pending({"U-2": "U-7", "U-3": "U-8"})
        self.p.sync_unit_contract()
        self.m["implementation_gate"] = {"state": "awaiting_implementation_prompt"}
        with self.assertRaisesRegex(ValueError, "explicit mappings"):
            self.preserve(helper, completion, mapping={})
        assessment = self.preserve(helper, completion, mapping={"U-2": ["U-7"], "U-3": ["U-8"]})
        value = self.read(assessment)
        value["pending_unit_map"] = {}
        self.rewrite(assessment, value)
        report = self.report()
        self.applicability(report, "needs_revalidation")
        self.assert_blocked(report)
        # Omitting full integration checks cannot be justified by preserved alpha.
        self.m["unit_plan"]["units"]["U-8"]["required_check_ids"].remove("QA-04")
        self.p.sync_unit_contract()
        self.assert_blocked(self.report())

    def test_preserved_component_cannot_pass_release_or_security_gate_on_its_own(self):
        helper, inventory, context, completion = self.capture_alpha()
        self.revise_pending()
        self.preserve(helper, completion)
        self.authorize_current()
        report = self.report("release")
        self.assert_blocked(report)
        self.assertNotEqual("passed", self.m["verification"]["release_readiness"])
        for key in ("QA-01", "QA-03", "QA-04"):
            self.assertEqual("not_run", next(item for item in self.m["verification"]["checks"] if item["check_id"] == key)["execution_status"])

    def test_full_release_resolves_history_for_generic_and_security_checks(self):
        helper, inventory, context, completion = self.capture_alpha()
        self.revise_pending()
        self.preserve(helper, completion)
        self.authorize_current()
        self.complete_current(helper, "U-2")
        self.complete_current(helper, "U-3")
        # The canonical live check index need not rebind immutable old results.
        execution_fields = ("execution_status", "executor", "executed_at", "evidence", "execution_mode",
                            "evaluated_plan_hash", "evaluated_source_hashes", "evaluated_execution_inputs")
        for check in self.m["verification"]["checks"]:
            for field in execution_fields:
                check.pop(field, None)
            check["execution_status"] = "not_run"
        report = self.report("release")
        self.assertEqual("passed", report["result"], report)
        security_evidence = "forge/evidence/QA-04.json"
        self.p.write(security_evidence, '{"synthetic_fixture":true,"changed":true}\n')
        report = self.report("release")
        self.assert_blocked(report)
        self.assertEqual("needs_revalidation", report["unit_history"]["units"]["U-3"]["current_applicability"])

    def test_original_sequence_exception_is_required_after_pending_units_move_later(self):
        helper = self.history()
        self.m.update(checker_contract_version=2, unit_contract_version=2)
        with self.assertRaises(ValueError):
            helper.capture_context(self.p.root, self.m, "U-2", self.inventory(unit="U-2"))
        self.fixture.exception("U-2", ["U-1"])
        context, completion = self.complete_current(helper, "U-2")
        self.rename_pending({"U-1": "U-4", "U-3": "U-5"})
        self.m["unit_plan"]["order"] = ["U-2", "U-4", "U-5"]
        self.p.sync_unit_contract()
        self.m["implementation_gate"] = {"state": "awaiting_implementation_prompt"}
        assessment = helper.assess_completion(self.p.root, self.m, completion, self.inventory(unit="U-2"),
                                              {"U-1": ["U-4"], "U-3": ["U-5"]})
        self.m["unit_runs"]["U-2"]["applicability_ref"] = assessment
        report = self.report()
        self.assertEqual("passed", report["result"], report)
        self.assertEqual("applicable", report["unit_history"]["units"]["U-2"]["current_applicability"])
        # Rehashing altered history must not erase an original ordering violation.
        historical_context = self.read(context)
        historical_context["manifest"]["unit_sequence_exceptions"] = []
        self.rewrite(context, historical_context)
        historical_completion = self.read(completion)
        historical_completion["context_ref"] = context
        self.rewrite(completion, historical_completion)
        with self.assertRaises(ValueError):
            helper.assess_completion(self.p.root, self.m, completion, self.inventory(unit="U-2"),
                                      {"U-1": ["U-4"], "U-3": ["U-5"]})

    def test_checker_is_read_only_and_capture_does_not_claim_execution(self):
        helper = self.history()
        self.m.update(checker_contract_version=2, unit_contract_version=2)
        before_manifest = copy.deepcopy(self.m)
        before_files = {path.relative_to(self.p.root).as_posix(): path.read_bytes()
                        for path in self.p.root.rglob("*") if path.is_file()}
        context = helper.capture_context(self.p.root, self.m, "U-1", self.inventory())
        self.assertEqual(before_manifest, self.m)
        self.assertFalse(self.m.get("unit_runs"))
        self.assertTrue(all(item["execution_status"] == "not_run" for item in self.m["verification"]["checks"]))
        for path, data in before_files.items():
            self.assertEqual(data, (self.p.root / path).read_bytes(), path)
        self.m["execution_contexts"] = {"U-1": context}
        before = {path.relative_to(self.p.root).as_posix(): path.read_bytes()
                  for path in self.p.root.rglob("*") if path.is_file()}
        before_manifest = copy.deepcopy(self.m)
        self.report()
        self.assertEqual(before_manifest, self.m)
        self.assertEqual(before, {path.relative_to(self.p.root).as_posix(): path.read_bytes()
                                  for path in self.p.root.rglob("*") if path.is_file()})

    def test_second_revision_cannot_drop_checks_introduced_by_first_revision(self):
        helper, inventory, context, completion = self.capture_alpha()
        self.rename_pending({"U-3": "U-5"})
        self.add_pending_component()
        self.p.sync_unit_contract()
        self.m["implementation_gate"] = {"state": "awaiting_implementation_prompt"}
        self.preserve(helper, completion, mapping={"U-3": ["U-5"], "__added__": ["U-4"]})
        self.applicability(self.report(), "applicable")
        self.p.save()  # The first accepted revision is now the real previous plan.
        del self.m["unit_plan"]["units"]["U-4"]
        self.m["unit_plan"]["order"].remove("U-4")
        del self.m["unit_plan"]["acceptance"]["QA-05"]
        self.m["verification"]["checks"] = [item for item in self.m["verification"]["checks"] if item["check_id"] != "QA-05"]
        for gate in self.m["verification"]["gates"]:
            gate["check_ids"] = [key for key in gate["check_ids"] if key != "QA-05"]
        for artifact, identifier in (("development-plan", "U-4"), ("qa-checklist", "QA-05")):
            trace = self.m["artifacts"][artifact]["traceability"]
            trace["definitions"] = [item for item in trace["definitions"] if item["id"] != identifier]
        self.p.sync_unit_contract()
        with self.assertRaisesRegex(ValueError, "QA-05"):
            self.preserve(helper, completion, mapping={"U-4": ["U-2"]})

    def test_prototype_promotion_keeps_original_git_and_plan_bindings(self):
        def git(*arguments):
            return subprocess.check_output(["git", "-c", "user.name=Synthetic Fixture",
                "-c", "user.email=fixture@example.invalid", *arguments], cwd=self.p.root)
        helper = self.history()
        self.m.update(checker_contract_version=2, unit_contract_version=2)
        baseline = self.m["active_baseline"]
        baseline.update(candidate_id="a", version="v1")
        mapping = {"source": "forge/design/candidates/a/v1/index.html", "destination": "src/promoted.html", "strategy": "adapt"}
        self.m["unit_plan"]["units"]["U-1"]["implementation_paths"].append(mapping["destination"])
        self.p.sync_unit_contract()
        self.p.authorize()
        git("init", "-q")
        # Keep this byte-identity fixture independent of Windows/global Git EOL
        # conversion: receipt hashes must match the bytes stored in the commit.
        git("config", "core.autocrlf", "true")
        self.p.write(".gitattributes", "* -text\n")
        git("add", ".")
        git("commit", "-qm", "Synthetic historical base")
        base = git("rev-parse", "HEAD").decode().strip()
        promotion = {"unit_id": "U-1", "base_commit": base, "path_mappings": [mapping]}
        self.m["prototype_promotions"] = [promotion]
        context = helper.capture_context(self.p.root, self.m, "U-1", self.inventory())
        self.m["execution_contexts"] = {"U-1": context}
        self.fixture.begin("U-1", 3)
        self.m["unit_runs"]["U-1"]["started_at"] = self.now()
        promotion["started_at"] = self.now()
        # Exercise the Windows CRLF case on every test platform.
        (self.p.root / mapping["destination"]).write_bytes(b"<h1>Adapted synthetic implementation</h1>\r\n")
        git("add", mapping["destination"])
        git("commit", "-qm", "Synthetic prototype promotion")
        head = git("rev-parse", "HEAD").decode().strip()
        self.assertEqual((self.p.root / mapping["destination"]).read_bytes(),
                         git("show", head + ":" + mapping["destination"]))
        self.fixture.evidence("U-1", 4)
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        self.stamp_evidence(helper, "U-1", self.inventory())
        check["evaluated_source_hashes"][mapping["destination"]] = self.p.hash(mapping["destination"])
        visual = self.p.evidence("forge/evidence/promotion-visual.json", {"synthetic_fixture": True})
        actual = {"schema_version": 1, "promotion_id": "synthetic-promotion-1", "unit_id": "U-1", "run_id": "synthetic-alpha-1",
            "development_plan_ref": "docs/development-plan.md", "development_plan_hash": self.p.hash("docs/development-plan.md"),
            **{key: baseline[key] for key in ("baseline_id", "visual_target_hash", "candidate_id", "version", "prototype_source_root", "prototype_tree_hash")},
            "base_commit": base, "head_commit": head, "changed_paths": [mapping["destination"]],
            "patch_hash": sdd.digest(git("diff", "--binary", "--no-ext-diff", "--no-textconv", base, head, "--", mapping["destination"])),
            "path_mappings": [{**mapping, "source_hash": self.p.hash(mapping["source"]), "destination_hash": self.p.hash(mapping["destination"])}],
            "adaptations": ["Synthetic adaptation"], "variances": [], "qa_ids": ["QA-02"],
            "visual_evidence": [{**visual, "kind": "visual"}], "verification_status": "passed", "completed_at": self.now()}
        promotion["receipt"] = self.p.evidence("forge/runs/promotion.json", actual)
        self.m["unit_runs"]["U-1"].update(status="completed", completed_at=self.now())
        completion = helper.capture_completion(self.p.root, self.m, "U-1", context, "synthetic-alpha-promotion-run")
        original_receipt = (self.p.root / promotion["receipt"]["path"]).read_bytes()
        self.p.save()
        self.revise_pending()
        self.preserve(helper, completion)
        self.applicability(self.report(), "applicable")
        self.assertEqual(original_receipt, (self.p.root / promotion["receipt"]["path"]).read_bytes())
        self.assertEqual(actual["development_plan_hash"], self.read(promotion["receipt"])["development_plan_hash"])
        self.p.write(mapping["destination"], "Changed after promoted completion.\n")
        self.preserve(helper, completion)
        self.applicability(self.report(), "needs_revalidation")

    def test_unrelated_qa_sections_can_change_without_rebinding_completed_evidence(self):
        helper, inventory, context, completion = self.capture_alpha()
        old_qa_hash = self.p.hash("docs/qa-checklist.md")
        old_evaluated_hash = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")["evaluated_plan_hash"]
        self.revise_pending()
        path = "docs/qa-checklist.md"
        text = (self.p.root / path).read_text(encoding="utf-8")
        self.p.write(path, text.replace("\n## Acceptance Contract", "\n## Pending beta clarification\nOnly beta needs this later check detail.\n\n## Acceptance Contract", 1))
        self.p.sync_unit_contract()
        self.assertNotEqual(old_qa_hash, self.p.hash(path))
        self.preserve(helper, completion)
        report = self.report()
        self.assertEqual("passed", report["result"], report)
        self.applicability(report, "applicable")
        self.assertEqual(old_evaluated_hash, next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")["evaluated_plan_hash"])

    def test_invalid_original_history_blocks_plan_instead_of_becoming_unassessed(self):
        for mode in ("missing_completion", "changed_completion", "changed_context", "pending_wrapper", "reassigned_id"):
            with self.subTest(mode=mode):
                self.fresh()
                helper, inventory, context, completion = self.capture_alpha()
                self.revise_pending()
                self.preserve(helper, completion)
                if mode == "missing_completion":
                    (self.p.root / completion["path"]).unlink()
                elif mode in ("changed_completion", "changed_context"):
                    ref = completion if mode == "changed_completion" else context
                    self.p.write(ref["path"], "{}\n")
                elif mode == "pending_wrapper":
                    self.m["unit_runs"]["U-1"]["status"] = "pending"
                else:
                    self.m["unit_runs"]["U-2"] = self.m["unit_runs"].pop("U-1")
                self.assert_blocked(self.report())

    def test_stale_predecessor_invalidates_dependent_completion(self):
        for dependency in ("construction", "check"):
            with self.subTest(dependency=dependency):
                self.fresh()
                if dependency == "check":
                    self.m["unit_plan"]["acceptance"]["QA-01"]["prerequisite_checks"] = ["QA-02"]
                    self.p.sync_unit_contract()
                    self.p.authorize()
                helper, inventory, context, completion = self.capture_alpha()
                self.revise_pending()
                self.preserve(helper, completion)
                self.authorize_current()
                self.complete_current(helper, "U-2")
                self.complete_current(helper, "U-3")
                self.assertEqual("passed", self.report("release")["result"])
                self.p.write("forge/evidence/QA-02.json", '{"synthetic_fixture":true,"altered":true}\n')
                report = self.report()
                self.applicability(report, "needs_revalidation")
                self.assertEqual("needs_revalidation", report["unit_history"]["units"]["U-3"]["current_applicability"], report)
                self.assert_blocked(self.report("release"))

    def test_revalidation_creates_new_run_and_keeps_original_history_unchanged(self):
        helper, inventory, context, completion = self.capture_alpha()
        old_bytes = (self.p.root / completion["path"]).read_bytes()
        self.revise_pending()
        self.p.write("src/alpha.txt", "Changed relevant implementation retained during fresh verification.\n")
        self.preserve(helper, completion)
        self.applicability(self.report(), "needs_revalidation")
        self.authorize_current()
        self.m.setdefault("completion_history", {}).setdefault("U-1", []).append(copy.deepcopy(completion))
        self.m["unit_runs"]["U-1"] = {"status": "pending"}
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        for field in ("executor", "executed_at", "evidence", "execution_mode", "evaluated_plan_hash", "evaluated_source_hashes", "evaluated_execution_inputs"):
            check.pop(field, None)
        check["execution_status"] = "not_run"
        new_context = helper.capture_context(self.p.root, self.m, "U-1", self.inventory())
        self.m["execution_contexts"]["U-1"] = new_context
        source_before = (self.p.root / "src/alpha.txt").read_bytes()
        self.m["unit_runs"]["U-1"] = {"status": "running", "started_at": self.now(),
            "development_plan_hash": self.p.hash("docs/development-plan.md"), "approved_baseline_id": "B-1", "findings": []}
        self.fixture.evidence("U-1", 4)
        self.stamp_evidence(helper, "U-1", self.inventory())
        self.m["unit_runs"]["U-1"].update(status="completed", completed_at=self.now())
        fresh = helper.capture_completion(self.p.root, self.m, "U-1", new_context, "synthetic-revalidated-alpha-2")
        self.m["unit_runs"]["U-1"] = {"status": "completed", "completion_ref": fresh}
        report = self.report()
        self.assertEqual("passed", report["result"], report)
        self.applicability(report, "applicable")
        self.assertNotEqual(completion, fresh)
        self.assertEqual(old_bytes, (self.p.root / completion["path"]).read_bytes())
        self.assertEqual(source_before, (self.p.root / "src/alpha.txt").read_bytes())
        # One immutable run can be referenced by history and the active wrapper;
        # assigning its identity to a distinct execution must not create two truths.
        self.m["completion_history"]["U-1"].append(copy.deepcopy(fresh))
        repeated = self.report()
        self.assertEqual("passed", repeated["result"], repeated)
        self.m["completion_history"]["U-1"].pop()
        new_record = self.read(fresh)
        self.assertNotEqual(self.read(completion)["run"]["started_at"], new_record["run"]["started_at"])
        new_record["run_id"] = self.read(completion)["run_id"]
        self.rewrite(fresh, new_record)
        collision = self.report()
        self.assert_blocked(collision)
        self.assertTrue(any("unit/run identity is reused by a different completion" in item["detail"]
                            for item in collision["issues"]), collision)

    def test_inventory_review_cannot_be_backfilled_after_execution(self):
        helper, inventory, context, completion = self.capture_alpha()
        old = self.read(completion)
        historical_context = self.read(context)
        too_late = old["run"]["completed_at"]
        historical_context["input_inventory"]["review"]["reviewed_at"] = too_late
        self.rewrite(context, historical_context)
        old["input_inventory"]["review"]["reviewed_at"] = too_late
        old["context_ref"] = context
        self.rewrite(completion, old)
        with self.assertRaises(ValueError):
            helper.validate_completion(self.p.root, completion)

    def test_interrupted_activation_keeps_old_manifest_and_recovery_does_not_overwrite(self):
        helper, inventory, context, completion = self.capture_alpha()
        self.revise_pending()
        self.preserve(helper, completion)
        active = self.p.root / "forge/sdd-manifest.json"
        before = active.read_bytes()
        expected = sdd.digest(before)
        candidate = helper.stage_candidate(self.p.root, self.m, expected)
        with mock.patch.object(helper.os, "replace", side_effect=OSError("Synthetic interruption before replacement")):
            with self.assertRaises(OSError):
                helper.activate_candidate(self.p.root, candidate, expected)
        self.assertEqual(before, active.read_bytes())
        self.assertFalse(list(active.parent.glob(".sdd-manifest-*.tmp")))
        journals = list((self.p.root / helper.HISTORY / "activations").glob("*/record.json"))
        self.assertEqual(1, len(journals))
        path = journals[0].relative_to(self.p.root).as_posix()
        journal = {"path": path, "content_hash": self.p.hash(path)}
        self.assertEqual("not_activated", helper.recover_activation(self.p.root, journal)["status"])
        active.write_bytes(before + b"\n")
        self.assertEqual("conflict", helper.recover_activation(self.p.root, journal)["status"])
        self.assertEqual(before + b"\n", active.read_bytes())

    def test_new_fixture_and_previously_absent_configuration_invalidate_completion(self):
        for addition in ("fixture", "configuration"):
            with self.subTest(addition=addition):
                self.fresh()
                self.p.write("tests/alpha/base.json", '{"synthetic_fixture":true}\n')
                base_inventory = self.__class__.inventory.__get__(self, self.__class__)
                def inventory(environment=None, unit="U-1"):
                    result = base_inventory(environment, unit)
                    result["execution_inputs"].update({"tests/alpha": {"mode": "tree"},
                                                       "runtime-options.json": {"mode": "file"}})
                    return result
                self.inventory = inventory
                helper, reviewed, context, completion = self.capture_alpha()
                self.revise_pending()
                if addition == "fixture":
                    self.p.write("tests/alpha/new-case.json", '{"synthetic_fixture":true,"new":true}\n')
                else:
                    self.p.write("runtime-options.json", '{"synthetic_configuration":true}\n')
                self.preserve(helper, completion)
                self.applicability(self.report(), "needs_revalidation")

    def test_absent_execution_input_cannot_hide_a_file_already_present_at_capture(self):
        helper = self.history()
        self.m.update(checker_contract_version=2, unit_contract_version=2)
        self.p.write("src/alpha.txt", "Present synthetic source must be fingerprinted.\n")
        inventory = self.inventory()
        inventory["execution_inputs"]["src/alpha.txt"] = {"mode": "absent"}
        with self.assertRaises(ValueError):
            helper.capture_context(self.p.root, self.m, "U-1", inventory)

    def test_staging_cannot_drop_or_reassign_a_completed_wrapper(self):
        for change in ("drop_wrapper", "reassign_wrapper", "change_scope"):
            with self.subTest(change=change):
                self.fresh()
                helper, inventory, context, completion = self.capture_alpha()
                expected = self.p.hash("forge/sdd-manifest.json")
                if change == "drop_wrapper":
                    self.m["unit_runs"] = {}
                elif change == "reassign_wrapper":
                    self.m["unit_runs"]["U-2"] = self.m["unit_runs"].pop("U-1")
                else:
                    self.m["unit_plan"]["units"]["U-1"]["scope"] = "Different product obligation under an old completed ID"
                    self.p.sync_unit_contract()
                with self.assertRaises(ValueError):
                    helper.stage_candidate(self.p.root, self.m, expected)
                self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))

    def test_legacy_adoption_archives_unverified_records_then_requires_a_new_run(self):
        helper = self.history()
        self.fixture.complete("U-1", 3)
        original_gate = copy.deepcopy(self.m["implementation_gate"])
        work = {str(path.relative_to(self.p.root)): path.read_bytes()
                for folder in ("docs", "src") for path in (self.p.root / folder).rglob("*") if path.is_file()}
        self.p.save()
        original_bytes = (self.p.root / "forge/sdd-manifest.json").read_bytes()
        expected = sdd.digest(original_bytes)
        staged = helper.adopt_legacy(self.p.root, expected)
        self.assertEqual(original_bytes, (self.p.root / "forge/sdd-manifest.json").read_bytes())
        candidate = self.read(staged)["manifest"]
        self.assertEqual((2, 2), (candidate["checker_contract_version"], candidate["unit_contract_version"]))
        self.assertEqual(original_gate, candidate["implementation_gate"])
        self.assertFalse(candidate["unit_runs"])
        self.assertTrue(all(item["execution_status"] == "not_run" for item in candidate["verification"]["checks"]))
        archive_ref = candidate["legacy_history"][0]
        archive = self.read(archive_ref)
        self.assertEqual("unverified_not_reusable", archive["acceptance"])
        self.assertEqual(original_bytes, (self.p.root / archive["manifest_ref"]["path"]).read_bytes())
        helper.activate_candidate(self.p.root, staged, expected)
        self.m = self.p.manifest = self.fixture.m = candidate
        self.assertEqual("passed", self.report()["result"])
        # Old passes cannot advance the next unit; the same scoped approval can
        # authorize a fresh context and real revalidation of the existing work.
        self.assert_blocked(self.report("implementation", "start", "U-2"))
        self.assert_blocked(self.report("implementation", "start", "U-1"))
        self.m["unit_runs"]["U-1"] = {"status": "completed", "completion_ref": archive_ref}
        self.assert_blocked(self.report())
        self.m["unit_runs"].pop("U-1")
        context, fresh = self.complete_current(helper, "U-1")
        self.assertEqual(original_gate, self.m["implementation_gate"])
        for path, content in work.items():
            self.assertEqual(content, (self.p.root / path).read_bytes(), path)
        report = self.report()
        self.assertEqual("passed", report["result"], report)
        self.applicability(report, "applicable")
        self.assertNotEqual(archive_ref, fresh)
        self.assertEqual(original_bytes, (self.p.root / archive["manifest_ref"]["path"]).read_bytes())

    def test_five_sequential_completions_reuse_validation_within_one_check_only(self):
        helper = self.history()
        self.rename_pending({"U-3": "U-5"})
        self.add_pending_component("U-3", "QA-05")
        self.add_pending_component("U-4", "QA-06")
        plan = self.m["unit_plan"]
        for unit, prior in (("U-2", "U-1"), ("U-3", "U-2"), ("U-4", "U-3")):
            plan["units"][unit]["construction_dependencies"] = [prior]
        plan["units"]["U-5"]["construction_dependencies"] = ["U-1", "U-2", "U-3", "U-4"]
        self.p.sync_unit_contract()
        self.p.authorize()
        self.m.update(checker_contract_version=2, unit_contract_version=2)
        for unit in plan["order"]:
            self.complete_current(helper, unit)
        resolver = sdd.history_api()
        with mock.patch.object(resolver, "historical_checker", wraps=resolver.historical_checker) as historical:
            report = self.report("release")
        self.assertEqual("passed", report["result"], report)
        self.assertGreater(historical.call_count, 0)
        # Each unit has three distinct views: pre-start context, the original
        # acceptance sources with actual results, and the reconciled post-run owners.
        self.assertLessEqual(historical.call_count, 3 * len(plan["order"]),
                             "An immutable historical view was recursively validated more than once")
        # The cache belongs to this invocation; it must not hide later changes.
        self.p.write("forge/evidence/QA-02.json", '{"synthetic_fixture":true,"changed_after_validation":true}\n')
        self.assert_blocked(self.report("release"))

    def test_added_required_check_requires_new_authorized_run_and_retains_original_history(self):
        helper, inventory, context, completion = self.capture_alpha()
        original_bytes = (self.p.root / completion["path"]).read_bytes()
        expected = self.p.hash("forge/sdd-manifest.json")
        plan = self.m["unit_plan"]
        plan["units"]["U-1"]["required_check_ids"].append("QA-05")
        plan["acceptance"]["QA-05"] = {"owner_unit": "U-1", "prerequisite_units": [],
                                        "prerequisite_checks": [], "obligation_ids": []}
        check = copy.deepcopy(next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-03"))
        check.update(check_id="QA-05", definition_ref={"path": "docs/qa-checklist.md", "heading": "## New alpha acceptance"})
        check["acceptance"]["required_source_paths"] = ["src/alpha.txt"]
        self.m["verification"]["checks"].append(check)
        next(gate for gate in self.m["verification"]["gates"] if gate["gate_id"] == check["gate_id"])["check_ids"].append("QA-05")
        self.m["artifacts"]["qa-checklist"]["traceability"]["definitions"].append({
            "id": "QA-05", "kind": "check", "required": True,
            "definition_ref": {"path": "docs/qa-checklist.md", "heading": "## New alpha acceptance"}})
        path = "docs/qa-checklist.md"
        text = (self.p.root / path).read_text(encoding="utf-8")
        self.p.write(path, text.replace("\n## Acceptance Contract", "\n## New alpha acceptance\nQA-05\n\n## Acceptance Contract", 1))
        self.p.sync_unit_contract()
        self.m["implementation_gate"] = {"state": "awaiting_implementation_prompt", "awaiting_at": self.now(),
            "development_plan_hash": self.p.hash("docs/development-plan.md"), "approved_baseline_id": "B-1"}

        # The previous completion did not execute the additional acceptance check.
        with self.assertRaisesRegex(ValueError, "completed unit definition"):
            helper.stage_candidate(self.p.root, self.m, expected)
        self.assert_blocked(self.report("implementation", "complete", "U-1"))
        self.m.setdefault("completion_history", {})["U-1"] = [copy.deepcopy(completion)]
        self.m["unit_runs"]["U-1"] = {"status": "pending"}
        old_check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        for field in ("executor", "executed_at", "evidence", "execution_mode", "evaluated_plan_hash", "evaluated_source_hashes", "evaluated_execution_inputs"):
            old_check.pop(field, None)
        old_check["execution_status"] = "not_run"

        for invalid_change, message in (("scope", "completed unit definition"),
                                        ("required_check", "completed unit definition"),
                                        ("obligation", "existing obligation was dropped")):
            with self.subTest(invalid_change=invalid_change):
                invalid = copy.deepcopy(self.m)
                if invalid_change == "scope":
                    invalid["unit_plan"]["units"]["U-1"]["scope"] = "Unrelated work using the completed ID"
                elif invalid_change == "required_check":
                    invalid["unit_plan"]["units"]["U-1"]["required_check_ids"].remove("QA-02")
                else:
                    invalid["unit_plan"]["acceptance"]["QA-01"]["obligation_ids"].remove("FR-01")
                with self.assertRaisesRegex(ValueError, message):
                    helper.stage_candidate(self.p.root, invalid, expected)
        staged = helper.stage_candidate(self.p.root, self.m, expected)
        self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))
        helper.activate_candidate(self.p.root, staged, expected)
        self.assertEqual("passed", self.report()["result"])
        self.assert_blocked(self.report("implementation", "start", "U-1"))
        with self.assertRaises(ValueError):
            helper.capture_context(self.p.root, self.m, "U-1", self.inventory())

        self.authorize_current()
        _, fresh = self.complete_current(helper, "U-1")
        report = self.report()
        self.assertEqual("passed", report["result"], report)
        self.applicability(report, "applicable")
        self.assertNotEqual(completion, fresh)
        self.assertEqual({"QA-02", "QA-05"}, {item["check_id"] for item in self.read(fresh)["checks"]})
        self.assertEqual([completion], self.m["completion_history"]["U-1"])
        self.assertEqual(original_bytes, (self.p.root / completion["path"]).read_bytes())

    def append_recorded_qa_history(self):
        path = "docs/qa-checklist.md"
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        text = (self.p.root / path).read_text(encoding="utf-8")
        self.p.write(path, text + "\n## Recorded Execution History\n\n" +
                     "Synthetic QA-02 result: passed at " + check["executed_at"] +
                     "; executor: synthetic test runner; evidence: forge/evidence/QA-02.json.\n")
        # Model the affected source owners reconciling the real new document bytes.
        # These owner records are distinct from the preceding check observations.
        self.p.refresh()
        self.m["verification"]["source_hashes"] = {
            "docs/qa-checklist.md": self.p.hash("docs/qa-checklist.md"),
            "docs/dod-evals.md": self.p.hash("docs/dod-evals.md")}

    def test_qa_history_output_requires_fresh_review_and_preserves_actual_test_provenance(self):
        for test_observed_canonical in (False, True):
            with self.subTest(test_observed_canonical=test_observed_canonical):
                self.fresh()
                helper, inventory, context, _ = self.capture_alpha(finish=False)
                context_bytes = (self.p.root / context["path"]).read_bytes()
                original_qa_hash = self.p.hash("docs/qa-checklist.md")
                self.fixture.evidence("U-1", 4)
                self.stamp_evidence(helper, "U-1", inventory)
                check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
                if test_observed_canonical:
                    check["evaluated_source_hashes"]["docs/qa-checklist.md"] = original_qa_hash
                actual_check = copy.deepcopy(check)
                self.append_recorded_qa_history()
                current_qa_hash = self.p.hash("docs/qa-checklist.md")
                self.assertNotEqual(original_qa_hash, current_qa_hash)
                self.m["unit_runs"]["U-1"].update(status="completed", completed_at=self.now())
                self.assert_blocked(self.report("implementation", "complete", "U-1"))
                with self.assertRaisesRegex(ValueError, "fresh current inventory review"):
                    helper.capture_completion(self.p.root, self.m, "U-1", context, "synthetic-unreviewed-owner-output")
                with self.assertRaisesRegex(ValueError, "fresh current inventory review"):
                    helper.capture_completion(self.p.root, self.m, "U-1", context, "synthetic-stale-review", inventory)

                reviewed = self.inventory()
                completion = helper.capture_completion(self.p.root, self.m, "U-1", context,
                                                       "synthetic-reviewed-owner-output", reviewed)
                saved = self.read(completion)
                self.assertEqual(context, saved["context_ref"])
                self.assertEqual([actual_check], saved["checks"])
                self.assertEqual(original_qa_hash, self.read(context)["input_inventory"]["canonical_hashes"]["docs/qa-checklist.md"])
                self.assertEqual(current_qa_hash, saved["input_inventory"]["canonical_hashes"]["docs/qa-checklist.md"])
                self.assertEqual(reviewed["review"], saved["input_inventory"]["review"])
                self.assertEqual(context_bytes, (self.p.root / context["path"]).read_bytes())
                self.m["unit_runs"]["U-1"] = {"status": "completed", "completion_ref": completion}
                report = self.report()
                self.assertEqual("passed", report["result"], report)
                self.applicability(report, "applicable")

    def test_fresh_owner_review_cannot_waive_changed_acceptance_or_fabricated_test_hashes(self):
        for change in ("selected_definition", "new_acceptance_obligation", "fabricated_canonical_test_hash"):
            with self.subTest(change=change):
                self.fresh()
                helper, inventory, context, _ = self.capture_alpha(finish=False)
                self.fixture.evidence("U-1", 4)
                self.stamp_evidence(helper, "U-1", inventory)
                check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
                if change == "selected_definition":
                    path = "docs/qa-checklist.md"
                    text = (self.p.root / path).read_text(encoding="utf-8")
                    self.p.write(path, text.replace("## Checks\n", "## Checks\nQA-02 must also verify a new failure path.\n", 1))
                elif change == "new_acceptance_obligation":
                    check["task"] += "; also prove the newly required failure recovery behavior"
                else:
                    check["evaluated_source_hashes"]["docs/qa-checklist.md"] = "sha256:" + "0" * 64
                self.append_recorded_qa_history()
                self.m["unit_runs"]["U-1"].update(status="completed", completed_at=self.now())
                with self.assertRaises(ValueError):
                    helper.capture_completion(self.p.root, self.m, "U-1", context, "synthetic-changed-obligation", self.inventory())

    def test_empty_execution_tree_and_empty_nested_directories_survive_snapshots(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                self.fresh()
                tree = self.p.root / "tests/empty-fixtures"
                (tree / "empty-child" if nested else tree).mkdir(parents=True)
                base_inventory = self.__class__.inventory.__get__(self, self.__class__)
                def inventory(environment=None, unit="U-1"):
                    reviewed = base_inventory(environment, unit)
                    reviewed["execution_inputs"]["tests/empty-fixtures"] = {"mode": "tree"}
                    return reviewed
                self.inventory = inventory
                helper, reviewed, context, completion = self.capture_alpha()
                for record_ref in (context, completion):
                    record = self.read(record_ref)
                    frozen_tree = self.p.root / record["snapshot_root"] / "tests/empty-fixtures"
                    self.assertTrue(frozen_tree.is_dir())
                    if nested:
                        self.assertTrue((frozen_tree / "empty-child").is_dir())
                report = self.report()
                self.assertEqual("passed", report["result"], report)
                self.applicability(report, "applicable")
                self.p.write("tests/empty-fixtures/new-case.json", '{"synthetic_fixture":true}\n')
                self.applicability(self.report(), "needs_revalidation")

    def test_reused_checker_resolves_original_wrappers_and_rechecks_changed_history(self):
        helper, inventory, context, completion = self.capture_alpha()
        original = copy.deepcopy(self.m)
        checker = sdd.Checker(self.p.root, self.m)
        first = checker.run("development-plan", after=True, require_current=True)
        second = checker.run("development-plan", after=True, require_current=True)
        self.assertEqual("passed", first["result"], first)
        self.assertEqual("passed", second["result"], second)
        self.assertEqual(first["unit_history"], second["unit_history"])
        self.assertEqual(original, self.m)
        self.p.write(completion["path"], "Changed immutable completion envelope.\n")
        self.assert_blocked(checker.run("development-plan", after=True, require_current=True))

    def test_current_wrapper_findings_survive_resolution_and_invalid_classification_blocks(self):
        for severity in ("P2", "INVALID"):
            with self.subTest(severity=severity):
                self.fresh()
                helper, inventory, context, completion = self.capture_alpha()
                original_bytes = (self.p.root / completion["path"]).read_bytes()
                finding = {"severity": severity, "release_effect": "advisory", "status": "open",
                           "detail": "Synthetic current finding must remain visible after history resolves."}
                self.m["unit_runs"]["U-1"]["findings"] = [finding]
                checker = sdd.Checker(self.p.root, self.m)
                report = checker.run("development-plan", after=True)
                if severity == "P2":
                    self.assertEqual("passed", report["result"], report)
                    self.assertIn(finding, checker.manifest["unit_runs"]["U-1"]["findings"])
                else:
                    self.assert_blocked(report)
                self.assertEqual(original_bytes, (self.p.root / completion["path"]).read_bytes())

    def test_repository_observations_keep_original_absence_and_validate_actual_post_run_files(self):
        for tamper in (None, "original", "current"):
            with self.subTest(tamper=tamper):
                self.fresh()
                source, test_path, note = "src/alpha.txt", "tests/alpha-check.py", "notes/repository-inspection.txt"
                check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
                check["acceptance"]["required_source_paths"].append(test_path)
                self.p.sync_unit_contract()
                self.p.authorize()
                self.p.write(note, "Original repository inspection outside unit execution inputs.\n")
                before = {"commands": ["synthetic repository existence and byte inspection"], "observed_at": self.now(),
                          "paths": {source: None, test_path: None, note: self.p.hash(note)}}
                self.m["repository_observations"] = {"before": copy.deepcopy(before)}
                for artifact in self.m["artifacts"].values():
                    artifact["repository_observation_id"] = "before"
                self.assertFalse((self.p.root / source).exists())
                self.assertFalse((self.p.root / test_path).exists())
                helper, inventory, context, _ = self.capture_alpha(finish=False)
                original_context_bytes = (self.p.root / context["path"]).read_bytes()
                frozen_context = self.read(context)
                self.assertEqual(before, frozen_context["manifest"]["repository_observations"]["before"])
                self.assertIn(note, frozen_context["files"])

                self.p.write(test_path, "# Synthetic acceptance fixture created during this unit.\n")
                self.p.write(note, "Updated repository inspection after new files were created.\n")
                self.fixture.evidence("U-1", 4)
                self.stamp_evidence(helper, "U-1", inventory)
                check["evaluated_source_hashes"][test_path] = self.p.hash(test_path)
                after = {"commands": ["synthetic repository existence and byte inspection"], "observed_at": self.now(),
                         "paths": {path: self.p.hash(path) for path in (source, test_path, note)}}
                self.m["repository_observations"]["after"] = copy.deepcopy(after)
                for artifact in self.m["artifacts"].values():
                    artifact["repository_observation_id"] = "after"
                self.append_recorded_qa_history()
                self.m["unit_runs"]["U-1"].update(status="completed", completed_at=self.now())
                completion = helper.capture_completion(self.p.root, self.m, "U-1", context,
                                                       "synthetic-refreshed-repository-observations", self.inventory())
                saved = self.read(completion)
                self.assertEqual(after, saved["post_manifest"]["repository_observations"]["after"])
                self.assertEqual(original_context_bytes, (self.p.root / context["path"]).read_bytes())
                self.m["unit_runs"]["U-1"] = {"status": "completed", "completion_ref": completion}
                report = self.report()
                self.assertEqual("passed", report["result"], report)
                self.applicability(report, "applicable")

                if tamper == "original":
                    # Rehash the forged records so validation must check the
                    # original observation against its actual original snapshot.
                    frozen_context["manifest"]["repository_observations"]["before"]["paths"][source] = after["paths"][source]
                    self.rewrite(context, frozen_context)
                    saved["context_ref"] = context
                    saved["post_manifest"]["execution_contexts"]["U-1"] = context
                elif tamper == "current":
                    saved["post_manifest"]["repository_observations"]["after"]["paths"][test_path] = None
                if tamper:
                    self.rewrite(completion, saved)
                    with self.assertRaisesRegex(ValueError, "stale_observation"):
                        helper.validate_completion(self.p.root, completion)

    def add_unexecuted_excluded_check(self):
        check = copy.deepcopy(next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-03"))
        check.update(check_id="QA-99", execution_status="not_applicable",
                     rationale="Synthetic optional variant is outside the confirmed fixture scope.")
        self.m["verification"]["checks"].append(check)
        next(gate for gate in self.m["verification"]["gates"] if gate["gate_id"] == check["gate_id"])["check_ids"].append("QA-99")
        self.m["artifacts"]["qa-checklist"]["traceability"]["definitions"].append({
            "id": "QA-99", "kind": "check", "required": False,
            "rationale": check["rationale"],
            "definition_ref": {"path": "docs/qa-checklist.md", "heading": "## Checks"}})
        path = "docs/qa-checklist.md"
        self.p.write(path, (self.p.root / path).read_text(encoding="utf-8").replace("## Checks\n", "## Checks\nQA-99 optional excluded variant\n", 1))
        self.p.sync_unit_contract()
        self.p.authorize()
        return check

    def test_pristine_legacy_adoption_preserves_exact_authority_and_original_pause(self):
        for representation in ("empty", "pending_placeholders", "excluded_unexecuted_check"):
            for authority in ("authorized", "awaiting"):
                with self.subTest(representation=representation, authority=authority):
                    self.fresh()
                    helper = self.history()
                    self.m["unit_runs"] = {}
                    if representation == "pending_placeholders":
                        self.m["unit_runs"] = {unit: {"status": "pending", "findings": []} for unit in self.m["unit_plan"]["order"]}
                        for check in self.m["verification"]["checks"]:
                            check.update(evidence=[], findings=[], evaluated_source_hashes={}, evaluated_execution_inputs={})
                    elif representation == "excluded_unexecuted_check":
                        self.add_unexecuted_excluded_check()
                    if authority == "awaiting":
                        self.m["implementation_gate"] = {"state": "awaiting_implementation_prompt",
                            "awaiting_at": "2026-08-20T10:01:00Z", "approved_baseline_id": "B-1",
                            "development_plan_hash": self.p.hash("docs/development-plan.md")}
                    original_gate = copy.deepcopy(self.m["implementation_gate"])
                    original_state = self.m["state"]
                    original_checks = copy.deepcopy(self.m["verification"]["checks"])
                    original_runs = copy.deepcopy(self.m["unit_runs"])
                    self.p.save()
                    original_bytes = (self.p.root / "forge/sdd-manifest.json").read_bytes()
                    expected = sdd.digest(original_bytes)
                    staged = helper.adopt_legacy(self.p.root, expected)
                    candidate = self.read(staged)["manifest"]
                    self.assertEqual(original_gate, candidate["implementation_gate"])
                    self.assertEqual(original_state, candidate["state"])
                    self.assertEqual(original_checks, candidate["verification"]["checks"])
                    self.assertEqual(original_runs, candidate["unit_runs"])
                    self.assertEqual(original_bytes, (self.p.root / "forge/sdd-manifest.json").read_bytes())
                    helper.activate_candidate(self.p.root, staged, expected)
                    self.m = self.p.manifest = self.fixture.m = candidate
                    report = self.report()
                    self.assertEqual("passed", report["result"], report)
                    if authority == "authorized":
                        self.assertEqual("authorized", report["execution_authority"]["status"])
                        helper.capture_context(self.p.root, self.m, "U-1", self.inventory())
                    else:
                        self.assertEqual("not_authorized", report["execution_authority"]["status"])
                        self.assert_blocked(self.report("implementation", "start", "U-1"))
                        with self.assertRaises(ValueError):
                            helper.capture_context(self.p.root, self.m, "U-1", self.inventory())

    def test_pristine_adoption_does_not_repair_invalid_authority_or_reauthorize_changed_plan(self):
        for invalid in ("missing_receipt", "invalid_receipt", "changed_plan"):
            with self.subTest(invalid=invalid):
                self.fresh()
                helper = self.history()
                if invalid == "missing_receipt":
                    self.m["implementation_gate"].pop("prompt_receipt")
                elif invalid == "invalid_receipt":
                    reference = self.m["implementation_gate"]["prompt_receipt"]
                    receipt = self.read(reference)
                    receipt["role"] = "assistant"
                    self.rewrite(reference, receipt)
                else:
                    self.m["unit_plan"]["units"]["U-2"]["scope"] += " with a new product obligation"
                    self.p.sync_unit_contract()
                original_gate = copy.deepcopy(self.m["implementation_gate"])
                self.p.save()
                expected = self.p.hash("forge/sdd-manifest.json")
                staged = helper.adopt_legacy(self.p.root, expected)
                candidate = self.read(staged)["manifest"]
                self.assertEqual(original_gate, candidate["implementation_gate"])
                helper.activate_candidate(self.p.root, staged, expected)
                self.m = self.p.manifest = self.fixture.m = candidate
                report = self.report()
                self.assertEqual("not_authorized", report["execution_authority"]["status"], report)
                self.assert_blocked(self.report("implementation", "start", "U-1"))
                with self.assertRaises(ValueError):
                    helper.capture_context(self.p.root, self.m, "U-1", self.inventory())

    def test_legacy_execution_requires_new_evidence_without_rebinding_authorization(self):
        variants = ("running", "blocked", "pending_with_timestamp", "orphan_evidence", "excluded_evidence",
                    "executed_at", "executor", "findings", "release_claim", "sequence_exception",
                    "malformed_runs", "malformed_evidence", "malformed_promotions")
        for variant in variants:
            with self.subTest(variant=variant):
                self.fresh()
                helper = self.history()
                check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
                if variant in ("running", "blocked"):
                    self.fixture.begin("U-1", 3)
                    self.m["unit_runs"]["U-1"]["status"] = variant
                elif variant == "pending_with_timestamp":
                    self.m["unit_runs"] = {"U-1": {"status": "pending", "started_at": self.now()}}
                elif variant in ("orphan_evidence", "excluded_evidence"):
                    if variant == "excluded_evidence":
                        check = self.add_unexecuted_excluded_check()
                    check["evidence"] = [self.p.evidence("forge/evidence/ambiguous-result.json", {"synthetic_fixture": True})]
                elif variant == "executed_at":
                    check["executed_at"] = self.now()
                elif variant == "executor":
                    check["executor"] = "synthetic earlier executor"
                elif variant == "findings":
                    check["findings"] = [{"severity": "P2", "release_effect": "advisory", "status": "open", "detail": "Existing observation"}]
                elif variant == "release_claim":
                    self.m["verification"]["release_readiness"] = "passed"
                elif variant == "sequence_exception":
                    self.fixture.exception()
                elif variant == "malformed_runs":
                    self.m["unit_runs"] = []
                elif variant == "malformed_evidence":
                    check["evidence"] = {"unexpected": "non-list evidence"}
                else:
                    self.m["prototype_promotions"] = {"unexpected": "non-list promotions"}
                original_gate = copy.deepcopy(self.m["implementation_gate"])
                self.p.save()
                expected = self.p.hash("forge/sdd-manifest.json")
                try:
                    staged = helper.adopt_legacy(self.p.root, expected)
                except ValueError:
                    # Malformed history may be rejected instead of automatically
                    # repaired; a failed migration leaves the active record intact.
                    self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))
                    continue
                candidate = self.read(staged)["manifest"]
                self.assertEqual(original_gate, candidate["implementation_gate"])
                self.assertEqual({}, candidate["unit_runs"])
                self.assertEqual("not_evaluated", candidate["verification"]["release_readiness"])
                self.assertTrue(all(item["execution_status"] in ("not_run", "not_applicable")
                                    for item in candidate["verification"]["checks"]))
                self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))

    def test_executed_legacy_migration_preserves_missing_stale_and_invalid_authority(self):
        for invalid in ("awaiting", "missing_receipt", "invalid_receipt", "changed_plan"):
            with self.subTest(invalid=invalid):
                self.fresh()
                helper = self.history()
                self.fixture.complete("U-1", 3)
                if invalid == "awaiting":
                    self.m["implementation_gate"] = {"state": "awaiting_implementation_prompt"}
                elif invalid == "missing_receipt":
                    self.m["implementation_gate"].pop("prompt_receipt")
                elif invalid == "invalid_receipt":
                    reference = self.m["implementation_gate"]["prompt_receipt"]
                    receipt = self.read(reference)
                    receipt["role"] = "assistant"
                    self.rewrite(reference, receipt)
                else:
                    self.m["unit_plan"]["units"]["U-2"]["scope"] += " changed scope"
                    self.p.sync_unit_contract()
                gate = copy.deepcopy(self.m["implementation_gate"])
                self.p.save()
                expected = self.p.hash("forge/sdd-manifest.json")
                staged = helper.adopt_legacy(self.p.root, expected)
                helper.activate_candidate(self.p.root, staged, expected)
                self.m = self.p.manifest = self.fixture.m = self.read(staged)["manifest"]
                self.assertEqual(gate, self.m["implementation_gate"])
                self.assertEqual("not_authorized", self.report()["execution_authority"]["status"])
                with self.assertRaises(ValueError):
                    helper.capture_context(self.p.root, self.m, "U-1", self.inventory())

    def test_migration_retains_unit_and_check_findings_with_partial_work(self):
        helper = self.history()
        self.fixture.begin("U-1", 3)
        finding = {"severity": "P1", "release_effect": "blocking", "status": "open", "detail": "Unresolved fixture defect"}
        self.m["unit_runs"]["U-1"].update(status="blocked", reason="Fixture defect", findings=[finding])
        self.m["verification"]["checks"][0]["findings"] = [copy.deepcopy(finding)]
        self.p.write("src/partial-work.txt", "Preserve this unfinished user work.\n")
        self.p.save()
        expected = self.p.hash("forge/sdd-manifest.json")
        staged = helper.adopt_legacy(self.p.root, expected)
        candidate = self.read(staged)["manifest"]
        self.assertEqual({"status": "pending", "findings": [finding]}, candidate["unit_runs"]["U-1"])
        self.assertEqual([finding], candidate["verification"]["checks"][0]["findings"])
        helper.activate_candidate(self.p.root, staged, expected)
        self.assertEqual("Preserve this unfinished user work.\n", (self.p.root / "src/partial-work.txt").read_text())
        legacy = self.read(candidate["legacy_history"][-1])
        self.assertEqual("blocked", self.read(legacy["manifest_ref"])["unit_runs"]["U-1"]["status"])

    def test_history_writer_rejects_new_legacy_candidates(self):
        helper = self.history()
        self.p.save()
        with self.assertRaises(ValueError):
            helper.stage_candidate(self.p.root, copy.deepcopy(self.m), self.p.hash("forge/sdd-manifest.json"))

    def test_early_legacy_resume_migrates_without_requiring_a_future_plan(self):
        for unit_version in (None, 1):
            with self.subTest(unit_version=unit_version):
                self.fresh()
                helper = self.history()
                self.m.clear()
                self.m.update(checker_contract_version=1, traceability_version=1, artifacts={},
                              language={"working_language": "en", "artifact_language": "en"},
                              implementation_gate={"state": "awaiting_implementation_prompt"})
                if unit_version is not None:
                    self.m["unit_contract_version"] = unit_version
                self.p.save()
                original = copy.deepcopy(self.m)
                expected = self.p.hash("forge/sdd-manifest.json")
                staged = helper.adopt_legacy(self.p.root, expected)
                record = self.read(staged)
                self.assertEqual("migration_ready", record["report"]["result"])
                self.assertNotEqual("passed", record["report"]["project_validation"]["result"])
                helper.activate_candidate(self.p.root, staged, expected)
                current = self.read(staged)["manifest"]
                self.assertEqual(original["implementation_gate"], current["implementation_gate"])
                archive = self.read(current["legacy_history"][0])
                self.assertEqual(original, self.read(archive["manifest_ref"]))
                self.assertEqual("passed", sdd.Checker(self.p.root, current).run("product-idea", require_current=True)["result"])
                self.assert_blocked(sdd.Checker(self.p.root, current).run("implementation", unit_action="start", unit_id="U-1", require_current=True))

    def test_stale_legacy_plan_can_migrate_but_cannot_authorize_execution(self):
        helper = self.history()
        self.fixture.complete("U-1", 3)
        self.p.write("docs/architecture.md", "Changed source awaiting owner reconciliation.\n")
        self.p.save()
        gate = copy.deepcopy(self.m["implementation_gate"])
        expected = self.p.hash("forge/sdd-manifest.json")
        staged = helper.adopt_legacy(self.p.root, expected)
        record = self.read(staged)
        self.assertEqual("migration_ready", record["report"]["result"])
        self.assertEqual("blocked", record["report"]["project_validation"]["result"])
        helper.activate_candidate(self.p.root, staged, expected)
        self.assertEqual(gate, record["manifest"]["implementation_gate"])
        self.assert_blocked(sdd.Checker(self.p.root, record["manifest"]).run("implementation", unit_action="start", unit_id="U-1", require_current=True))

    def test_migration_activation_rejects_appearing_sources_and_invalid_version_types(self):
        helper = self.history()
        for value in (True, 1.0, "1"):
            with self.subTest(version=value):
                self.m["checker_contract_version"] = value
                self.p.save()
                with self.assertRaises(ValueError):
                    helper.adopt_legacy(self.p.root, self.p.hash("forge/sdd-manifest.json"))
        self.m["checker_contract_version"] = 1
        self.p.save()
        missing = self.p.root / "docs/development-plan.md"
        original = missing.read_bytes()
        missing.unlink()
        expected = self.p.hash("forge/sdd-manifest.json")
        staged = helper.adopt_legacy(self.p.root, expected)
        missing.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "sources changed|snapshot inventory changed"):
            helper.activate_candidate(self.p.root, staged, expected)
        self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))

    def test_migration_ready_cannot_hide_missing_or_forged_archive_snapshots(self):
        for corrupt in ("missing_snapshot", "empty_inventory"):
            with self.subTest(corrupt=corrupt):
                self.fresh()
                helper = self.history()
                self.p.save()
                expected = self.p.hash("forge/sdd-manifest.json")
                staged = helper.adopt_legacy(self.p.root, expected)
                candidate = self.read(staged)["manifest"]
                reference = candidate["legacy_history"][-1]
                legacy = self.read(reference)
                if corrupt == "missing_snapshot":
                    snapshot = next(iter(legacy["files"].values()))
                    (self.p.root / snapshot["path"]).unlink()
                else:
                    legacy["files"] = {}
                    self.rewrite(reference, legacy)
                with self.assertRaisesRegex(ValueError, "historical snapshot changed|snapshot inventory changed"):
                    helper.stage_candidate(self.p.root, candidate, expected)
                self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))

    def test_older_legacy_archive_extra_inputs_are_preserved_and_every_byte_still_validates(self):
        for mutation in (None, "missing_required", "missing_extra_snapshot", "changed_extra_snapshot", "changed_extra_source"):
            with self.subTest(mutation=mutation):
                self.fresh()
                helper = self.history()
                extra = "forge/old-history-only.txt"
                self.p.write(extra, "Original inactive history input.\n")
                self.m["history"].append({"event": "historical_note", "path": extra})
                self.p.save()
                expected = self.p.hash("forge/sdd-manifest.json")
                staged = helper.adopt_legacy(self.p.root, expected)
                candidate = self.read(staged)["manifest"]
                ref = candidate["legacy_history"][-1]
                archive = self.read(ref)
                self.assertNotIn(extra, archive["files"])
                # Emulate a previously captured archive that included inactive inputs.
                snapshot = helper.write_snapshot(self.p.root, archive["snapshot_root"] + "/" + extra,
                                                 (self.p.root / extra).read_bytes())
                archive["files"][extra] = snapshot
                if mutation == "missing_required":
                    del archive["files"]["docs/prd.md"]
                self.rewrite(ref, archive)
                if mutation == "missing_extra_snapshot":
                    (self.p.root / snapshot["path"]).unlink()
                elif mutation == "changed_extra_snapshot":
                    (self.p.root / snapshot["path"]).write_text("Changed archived bytes.\n")
                elif mutation == "changed_extra_source":
                    self.p.write(extra, "Changed original source.\n")
                if mutation:
                    with self.assertRaisesRegex(ValueError, "snapshot inventory changed|historical snapshot changed|legacy snapshot source changed"):
                        helper.stage_candidate(self.p.root, candidate, expected)
                else:
                    restaged = helper.stage_candidate(self.p.root, candidate, expected)
                    self.assertEqual(candidate["legacy_history"], self.read(restaged)["manifest"]["legacy_history"])
                    self.assertEqual(archive, self.read(ref))
                self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))

    def test_adoption_activation_rejects_changed_authority_and_false_execution_modes(self):
        for forgery in ("changed_authority", "fake_execution_mode", "fake_no_execution_mode"):
            with self.subTest(forgery=forgery):
                self.fresh()
                helper = self.history()
                if forgery == "fake_no_execution_mode":
                    self.fixture.complete("U-1", 3)
                self.p.save()
                expected = self.p.hash("forge/sdd-manifest.json")
                staged = helper.adopt_legacy(self.p.root, expected)
                record = self.read(staged)
                if forgery == "changed_authority":
                    record["manifest"]["implementation_gate"]["released_at"] = self.now()
                    message = "legacy adoption must preserve original fields"
                else:
                    record["adoption_mode"] = "legacy_revalidation" if forgery == "fake_execution_mode" else "format_only_no_execution"
                    message = "adoption mode differs from actual legacy execution state"
                self.rewrite(staged, record)
                with self.assertRaisesRegex(ValueError, message):
                    helper.activate_candidate(self.p.root, staged, expected)
                self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))

    def test_generic_adoption_paths_cannot_change_authority_or_hide_actual_history(self):
        for bypass in ("generic_stage", "activation_without_label", "mismatched_archive"):
            with self.subTest(bypass=bypass):
                self.fresh()
                helper = self.history()
                self.fixture.begin("U-1", 3)
                original_gate = copy.deepcopy(self.m["implementation_gate"])
                self.p.save()
                expected = self.p.hash("forge/sdd-manifest.json")
                staged = helper.adopt_legacy(self.p.root, expected)
                record = self.read(staged)
                candidate = record["manifest"]
                if bypass == "mismatched_archive":
                    archive_ref = candidate["legacy_history"][0]
                    archive = self.read(archive_ref)
                    archived_manifest = self.read(archive["manifest_ref"])
                    archived_manifest["unit_runs"] = {}
                    self.rewrite(archive["manifest_ref"], archived_manifest)
                    self.rewrite(archive_ref, archive)
                    with self.assertRaises(ValueError):
                        helper.stage_candidate(self.p.root, candidate, expected)
                else:
                    candidate["implementation_gate"] = {**original_gate, "released_at": self.now()}
                    if bypass == "generic_stage":
                        with self.assertRaises(ValueError):
                            helper.stage_candidate(self.p.root, candidate, expected)
                    else:
                        record.pop("adoption_mode")
                        # A caller can recompute hashes/reports; the actual prior
                        # execution state must enforce unchanged authority independently.
                        record["report"] = sdd.Checker(self.p.root, candidate).run("development-plan", after=True)
                        record["observed_hashes"] = helper.candidate_hashes(self.p.root, candidate)
                        self.rewrite(staged, record)
                        with self.assertRaises(ValueError):
                            helper.activate_candidate(self.p.root, staged, expected)
                self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))


if __name__ == "__main__":
    unittest.main()
