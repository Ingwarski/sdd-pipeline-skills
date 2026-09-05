"""Synthetic pipeline replays; no product tests or user-research claims are made."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/to-sdd-pipeline/scripts/sdd_check.py"
spec = importlib.util.spec_from_file_location("sdd_check", SCRIPT)
sdd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdd)
CONTRACT = sdd.read_contract()


class Project:
    def __init__(self, root):
        self.root = Path(root)
        self.manifest = {"checker_contract_version": 1, "pipeline_version": "existing-project-version",
                         "state": "awaiting-implementation-prompt",
                         "language": {"working_language": "uk", "artifact_language": "uk", "product_content_locales": ["en"]},
                         "artifacts": {}, "history": [{"id": "preserve-me"}],
                         "design_execution": {"mode": "codex"},
                         "implementation_gate": {"state": "awaiting_implementation_prompt"}}
        for key in CONTRACT["artifacts"]:
            self.write("docs/" + key + ".md", "# Synthetic fixture: " + key + "\n\n## Definition\nSource-backed fixture obligation. NFR-02 implementation consequence.\n")
        self.write("docs/product-idea.md", "# Test product\n\n## Jobs\nJOB-01: compare options with confidence.\n")
        self.write("docs/prd.md", "# Test requirements\n\n## Use cases\nUC-01 / FR-01: compare and safely retry.\n\n"
                   "## Security Requirements\nASVS 5.0.0. Synthetic production service.\n\n"
                   "### NFR-02\nNFR-02: deny cross-user data access. v5.0.0-8.2.2.\n")
        self.write("docs/project-context.md", "# Контекст\n\n## Платформи\nМобільна й настільна версії.\n\n## Примітки\nОпис для прикладу.\n")
        gates = list(sdd.GATE_KINDS)
        self.write("docs/dod-evals.md", "# Synthetic definitions\n\n## Gates\n" + "\n".join(gates) + "\n" + sdd.SECURITY_GATE + " NFR-02\n")
        self.write("docs/qa-checklist.md", "# Synthetic checks\n\n## Checks\nQA-01 visual\nQA-02 heuristic\nQA-03 representative user\nQA-04 security NFR-02\n")
        self.write("forge/design/candidates/a/v1/index.html", "<h1>Synthetic approved prototype</h1>\n")
        self.write("forge/design/evidence/target.txt", "Synthetic visual target, not a real screenshot.\n")
        baseline = {"baseline_id": "B-1", "prototype_source_root": "forge/design/candidates/a/v1",
                    "prototype_tree_hash": sdd.tree_hash(self.root / "forge/design/candidates/a/v1"),
                    "hash_algorithm": "sdd-tree-sha256-v1", "visual_target_path": "forge/design/evidence/target.txt",
                    "visual_target_hash": self.hash("forge/design/evidence/target.txt"),
                    "canonical_ref": {"path": "docs/design-brief.md", "heading": "## Approved Visual Baseline"}}
        receipt = {"event": "approve_design_baseline", "actor": "synthetic-test-operator", "approved_at": "2026-08-20T10:00:00Z"}
        receipt.update({key: baseline[key] for key in ("baseline_id", "visual_target_hash", "prototype_tree_hash")})
        baseline["approval_receipt"] = self.evidence("forge/design/evidence/approval.json", receipt)
        self.manifest.update(approved_baseline_id="B-1", active_baseline=baseline)
        self.write("docs/design-brief.md", "# Synthetic design\n\n## Approved Visual Baseline\nStatus: approved\n" +
                   "\n".join(str(baseline[key]) for key in ("baseline_id", "prototype_tree_hash", "visual_target_hash")) +
                   "\nforge/design/evidence/approval.json\n")
        self.refresh()
        self.manifest["artifacts"]["prd"]["security_review"] = {
            "version": 1, "asvs_version": "5.0.0", "scope": "web-api", "level": 2,
            "status": "complete", "rationale": "Synthetic production service.",
            "definition_ref": {"path": "docs/prd.md", "heading": "## Security Requirements"},
            "requirements": [{"requirement_id": "NFR-02", "asvs_ids": ["v5.0.0-8.2.2"],
                              "definition_ref": {"path": "docs/prd.md", "heading": "### NFR-02"}}]}
        for key in sdd.SECURITY_OWNERS:
            heading = "## Gates" if key == "dod-evals" else "## Checks" if key == "qa-checklist" else "## Definition"
            self.manifest["artifacts"][key]["security_coverage"] = {
                "NFR-02": {"path": "docs/" + key + ".md", "heading": heading}}
        self.manifest["verification"] = {"definition_status": "prepared", "release_readiness": "not_evaluated",
            "source_hashes": {"docs/qa-checklist.md": self.hash("docs/qa-checklist.md"), "docs/dod-evals.md": self.hash("docs/dod-evals.md")},
            "gates": [], "checks": []}
        for index, gate in enumerate(gates, 1):
            key = "QA-0" + str(index)
            self.manifest["verification"]["gates"].append({"gate_id": gate, "required": True, "active": True,
                "applicability": "applicable", "check_ids": [key], "definition_ref": {"path": "docs/dod-evals.md", "heading": "## Gates"}})
            self.manifest["verification"]["checks"].append({"check_id": key, "gate_id": gate,
                "definition_ref": {"path": "docs/qa-checklist.md", "heading": "## Checks"},
                "definition_status": "prepared", "execution_status": "not_run", "phase": "implementation",
                "baseline_id": "B-1", "target_hash": baseline["visual_target_hash"],
                "task": "compare options", "user_group": "synthetic group", "route": "/compare", "state": "default",
                "viewport": "390x844", "job_ids": ["JOB-01"], "use_case_ids": ["UC-01"],
                "heuristic_ids": ["H" + str(i) for i in range(1, 11)] if gate == "heuristic_usability_review" else []})
        self.manifest["verification"]["gates"].append({
            "gate_id": sdd.SECURITY_GATE, "required": True, "active": True, "applicability": "applicable",
            "check_ids": ["QA-04"], "security_requirement_ids": ["NFR-02"],
            "definition_ref": {"path": "docs/dod-evals.md", "heading": "## Gates"}})
        self.manifest["verification"]["checks"].append({
            "check_id": "QA-04", "gate_id": sdd.SECURITY_GATE, "security_requirement_ids": ["NFR-02"],
            "definition_ref": {"path": "docs/qa-checklist.md", "heading": "## Checks"},
            "definition_status": "prepared", "execution_status": "not_run", "phase": "implementation"})
        self.traceability()
        self.save()

    def traceability(self):
        self.manifest["traceability_version"] = 1
        owners = {"product-idea": [("JOB-01", "job", "## Jobs")],
                  "prd": [("UC-01", "use_case", "## Use cases"), ("FR-01", "requirement", "## Use cases"), ("NFR-02", "requirement", "### NFR-02")],
                  "screen-map": [("SCREEN-01", "surface", "## Definition"), ("STATE-01", "state", "## Definition")],
                  "development-plan": [("U-1", "unit", "## Definition")],
                  "qa-checklist": [("QA-0" + str(i), "check", "## Checks") for i in range(1, 5)]}
        relations = {"prd": [("UC-01", "JOB-01", "realizes_job"), ("FR-01", "UC-01", "specifies")],
                     "screen-map": [("SCREEN-01", "UC-01", "supports"), ("STATE-01", "SCREEN-01", "state_of")],
                     "development-plan": [("U-1", key, "implements") for key in ("FR-01", "NFR-02", "STATE-01")],
                     "qa-checklist": [("QA-01", "FR-01", "verifies"), ("QA-01", "STATE-01", "verifies"), ("QA-04", "NFR-02", "verifies")]}
        for owner, definitions in owners.items():
            heading = definitions[0][2]
            path = "docs/" + owner + ".md"
            links = relations.get(owner, [])
            # References are visible in canonical fixture sections, not metadata-only claims.
            text = (self.root / path).read_text()
            additions = " ".join([item[0] for item in definitions] + [value for link in links for value in link[:2]])
            self.write(path, text.replace(heading + "\n", heading + "\n" + additions + "\n", 1))
            self.manifest["artifacts"][owner]["traceability"] = {
                "definitions": [{"id": key, "kind": kind, "required": True,
                                 "cross_cutting": key == "NFR-02", "definition_ref": {"path": path, "heading": h}}
                                for key, kind, h in definitions],
                "links": [{"from": source, "to": target, "relation": relation,
                           "definition_ref": {"path": path, "heading": heading}} for source, target, relation in links]}
        self.refresh()
        self.manifest["verification"]["source_hashes"] = {"docs/" + k + ".md": self.hash("docs/" + k + ".md") for k in ("qa-checklist", "dod-evals")}

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def hash(self, path):
        return sdd.digest((self.root / path).read_bytes())

    def evidence(self, path, value):
        self.write(path, json.dumps(value, ensure_ascii=False) + "\n")
        return {"path": path, "content_hash": self.hash(path)}

    def refresh(self, keys=None):
        for key in keys or CONTRACT["artifacts"]:
            definition = CONTRACT["artifacts"][key]
            old = self.manifest["artifacts"].get(key, {})
            self.manifest["artifacts"][key] = {**old, "path": definition["path"], "owner_skill": definition["owner_skill"],
                "owner_invocation_id": "context-bundle-1" if key in CONTRACT["context_bundle"] else key + "-1",
                "declared_output_set": ["docs/" + k + ".md" for k in CONTRACT["context_bundle"]] if key in CONTRACT["context_bundle"] else [definition["path"]],
                "status": "validated", "content_hash": self.hash(definition["path"]),
                "source_hashes": {CONTRACT["artifacts"][k]["path"]: self.hash(CONTRACT["artifacts"][k]["path"]) for k in definition["required_before"] if k not in CONTRACT["context_bundle"]},
                "source_usage": {CONTRACT["artifacts"][k]["path"]: {"unused": "Synthetic fixture consumes no context facts or terms."} if k in CONTRACT["context_bundle"] else "full" for k in definition["required_before"]},
                "dependencies": definition["required_before"].copy(),
                "validation": {"result": "passed", "working_language": "uk"}, "validated_baseline_id": "B-1"}

    def save(self):
        self.write("forge/sdd-manifest.json", json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n")

    def run(self, node="development-plan", after=False):
        return sdd.Checker(self.root, self.manifest).run(node, after)

    def authorize(self):
        gate = {"state": "authorized_for_phase3", "development_plan_hash": self.hash("docs/development-plan.md"),
                "approved_baseline_id": "B-1", "prompt_id": "test-user-message-2", "awaiting_at": "2026-08-20T10:01:00Z",
                "prompt_received_at": "2026-08-20T10:02:00Z", "released_at": "2026-08-20T10:02:01Z"}
        receipt = {key: gate[key] for key in ("development_plan_hash", "approved_baseline_id", "prompt_id")}
        receipt.update(event="implementation_prompt", intent="start_production_implementation", role="user",
                       received_at=gate["prompt_received_at"], message="Start Phase 3 production implementation from this validated plan.")
        gate["prompt_receipt"] = self.evidence("forge/runs/implementation-prompt.json", receipt)
        self.manifest["implementation_gate"] = gate

    def execute_checks(self):
        self.write("src/app.txt", "Synthetic implementation fixture.\n")
        for check in self.manifest["verification"]["checks"]:
            evidence = self.evidence("forge/evidence/" + check["check_id"] + ".json", {"synthetic_fixture": True, "not_real_user_research": True})
            evidence["kind"] = sdd.GATE_KINDS.get(check["gate_id"], "security")
            check.update(execution_status="passed", executor="synthetic-test-runner", executed_at="2026-08-20T10:05:00Z",
                         evidence=[evidence], evaluated_source_hashes={"src/app.txt": self.hash("src/app.txt")})

    def candidates(self, claude=False):
        self.manifest["prototype_candidates"] = []
        for candidate_id in ("a", "b", "c"):
            root = "forge/design/candidates/" + candidate_id + "/v1"
            if candidate_id != "a":
                self.write(root + "/index.html", "<h1>Synthetic candidate " + candidate_id + "</h1>\n")
            record = {"candidate_id": candidate_id, "version": "v1", "prototype_source_root": root,
                      "prototype_tree_hash": sdd.tree_hash(self.root / root), "hash_algorithm": "sdd-tree-sha256-v1",
                      "visual_target_path": "forge/design/evidence/target.txt", "visual_target_hash": self.hash("forge/design/evidence/target.txt"),
                      "preview_url": "http://localhost:3000/" + candidate_id, "route": "/" + candidate_id,
                      "source_hashes": {spec["path"]: self.hash(spec["path"]) for key, spec in CONTRACT["artifacts"].items() if key != "development-plan"}}
            actual = {key: record[key] for key in ("candidate_id", "version", "prototype_tree_hash", "visual_target_hash", "preview_url")}
            actual.update(observed_at="2026-08-20T09:55:00Z", result="passed", synthetic_fixture=True)
            record["browser_receipt"] = self.evidence("forge/design/evidence/" + candidate_id + "-browser.json", {**actual, "browser_kind": "external_default"})
            record["visual_qa_evidence"] = self.evidence("forge/design/evidence/" + candidate_id + "-visual.json", actual)
            self.manifest["prototype_candidates"].append(record)
        if not claude:
            return
        self.manifest["prototype_candidates"] = self.manifest["prototype_candidates"][:1]
        self.manifest["prototype_candidates"][0]["origin_reference"] = "claude:a:v1"
        handoff = {"mode": "claude_design", "claude_candidate_references": ["claude:a:v1", "claude:b:v1", "claude:c:v1"],
                   "selected_candidate_version": "claude:a:v1", "required_source_count": 2,
                   "codex_accessible_required_source_count": 2, "claude_read_required_source_count": 2}
        materials = [{"material_id": key, "required": True, "content_hash": self.hash(path)}
                     for key, path in (("design", "docs/design-brief.md"), ("brand", "forge/design/evidence/target.txt"))]
        inventory = self.evidence("forge/design/handoffs/test/design-source-manifest.json", {"language": self.manifest["language"], "materials": materials})
        handoff.update(source_manifest_path=inventory["path"], source_manifest_hash=inventory["content_hash"])
        for key, status in (("codex_access_receipt", "accessible"), ("claude_source_read_receipt", "read")):
            receipt = self.evidence("forge/design/handoffs/test/" + key + ".json", {
                "manifest_hash": inventory["content_hash"], "results": [{**item, "status": status} for item in materials]})
            handoff[key + "_path"], handoff[key + "_hash"] = receipt["path"], receipt["content_hash"]
        self.manifest["design_execution"] = handoff


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-check-test-")
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)
        self.m = self.project.manifest

    def assert_issue(self, code, report=None):
        report = report or self.project.run()
        self.assertIn(code, [item["code"] for item in report["issues"]], report)

    def test_planning_accepts_prepared_not_run_checks(self):
        self.assertEqual("passed", self.project.run()["result"])
        self.assertEqual("passed", self.project.run(after=True)["result"])

    def test_required_owner_stages(self):
        for node in list(CONTRACT["artifacts"]) + ["project-context-bundle", "architecture-approved", "dod-evals-approved", "qa-checklist-approved"]:
            with self.subTest(node=node):
                self.assertEqual("passed", self.project.run(node, after=True)["result"])

    def test_no_file_is_valid_intake_entry_but_not_prd_input(self):
        self.m["artifacts"].clear()
        self.assertEqual("passed", self.project.run("product-idea")["result"])
        self.assert_issue("missing_artifact", self.project.run("prd"))

    def test_post_approval_reconciliation_is_required(self):
        for key in ("architecture", "dod-evals", "qa-checklist"):
            self.m["artifacts"][key]["validated_baseline_id"] = "old-baseline"
        report = self.project.run()
        self.assert_issue("baseline_reconciliation_required", report)
        self.assertTrue({"architecture", "dod-evals", "qa-checklist"}.issubset(report["affected_artifacts"]))

    def test_missing_and_wrong_owner_and_changed_document(self):
        for mode in ("missing", "owner", "changed"):
            with self.subTest(mode=mode):
                original = copy.deepcopy(self.m["artifacts"]["architecture"])
                if mode == "missing":
                    del self.m["artifacts"]["architecture"]
                    self.assert_issue("missing_artifact")
                elif mode == "owner":
                    self.m["artifacts"]["architecture"]["owner_skill"] = "to-qa-checklist"
                    self.assert_issue("wrong_owner_or_path")
                else:
                    self.project.write("docs/architecture.md", "Changed without validation.\n")
                    self.assert_issue("stale_artifact")
                self.m["artifacts"]["architecture"] = original

    def test_missing_validation_and_invocation(self):
        entry = self.m["artifacts"]["architecture"]
        entry["validation"] = {}
        entry["owner_invocation_id"] = None
        self.assert_issue("missing_validation")
        self.assert_issue("missing_invocation")

    def test_context_bundle_is_atomic(self):
        self.m["artifacts"]["canonical-terms"]["owner_invocation_id"] = "other-run"
        self.assert_issue("incomplete_context_bundle")

    def test_later_references_are_not_false_dependency_loops(self):
        self.m["artifacts"]["qa-checklist"]["dependencies"].append("development-plan")
        del self.m["artifacts"]["development-plan"]
        (self.project.root / "docs/development-plan.md").unlink()
        report = self.project.run("prototype-candidates")
        self.assertEqual("passed", report["result"], report)
        self.assertTrue(any("later reference" in warning for warning in report["warnings"]))

    def test_real_prerequisite_cycle_is_rejected(self):
        contract = copy.deepcopy(CONTRACT)
        contract["artifacts"]["wireframes"]["required_before"].append("design-brief")
        with self.assertRaisesRegex(ValueError, "cycle"):
            sdd.validate_contract(contract)

    def test_unconsumed_context_edit_does_not_invalidate_consumers(self):
        path = self.project.root / "docs/project-context.md"
        before = path.read_text(encoding="utf-8")
        entry = self.m["artifacts"]["architecture"]
        entry["source_usage"]["docs/project-context.md"] = ["## Платформи"]
        entry["consumed_source_fragments"] = {"docs/project-context.md": [{"heading": "## Платформи", "content_hash": sdd.digest(sdd.section_bytes(path, "## Платформи"))}]}
        path.write_text(before.replace("Опис для прикладу.", "Інший опис."), encoding="utf-8")
        self.project.refresh(CONTRACT["context_bundle"])
        self.assertEqual("passed", self.project.run()["result"])
        path.write_text(before.replace("Мобільна й настільна", "Лише настільна"), encoding="utf-8")
        self.project.refresh(CONTRACT["context_bundle"])
        self.assert_issue("stale_fragment")

    def test_fragment_ignores_code_fence_headings(self):
        self.project.write("docs/fragment.md", "## Keep\n```md\n## Not a boundary\n```\nStill inside.\n## End\nOutside.\n")
        value = sdd.section_bytes(self.project.root / "docs/fragment.md", "## Keep")
        self.assertIn(b"Still inside", value)
        self.assertNotIn(b"Outside", value)

    def test_qa_run_updates_do_not_invalidate_a_plan_using_stable_definitions(self):
        path = self.project.root / "docs/qa-checklist.md"
        entry = self.m["artifacts"]["development-plan"]
        del entry["source_hashes"]["docs/qa-checklist.md"]
        entry["source_usage"]["docs/qa-checklist.md"] = ["## Checks"]
        entry["consumed_source_fragments"] = {"docs/qa-checklist.md": [
            {"heading": "## Checks", "content_hash": sdd.digest(sdd.section_bytes(path, "## Checks"))}]}
        original = path.read_text(encoding="utf-8")
        path.write_text(original + "## Execution Results\nA later synthetic run record.\n", encoding="utf-8")
        self.project.refresh(["qa-checklist"])
        self.m["verification"]["source_hashes"]["docs/qa-checklist.md"] = self.project.hash("docs/qa-checklist.md")
        self.assertEqual("passed", self.project.run(after=True)["result"])
        path.write_text(original.replace("QA-01 visual", "QA-01 stricter visual expectation"), encoding="utf-8")
        self.project.refresh(["qa-checklist"])
        self.m["verification"]["source_hashes"]["docs/qa-checklist.md"] = self.project.hash("docs/qa-checklist.md")
        self.assert_issue("stale_fragment", self.project.run(after=True))

    def test_duplicate_heading_cannot_hide_changed_fragment(self):
        self.project.write("docs/fragment.md", "## Same\nOne\n## Same\nTwo\n")
        with self.assertRaises(ValueError):
            sdd.section_bytes(self.project.root / "docs/fragment.md", "## Same")

    def test_baseline_hash_is_recomputed(self):
        self.m["active_baseline"]["integrity"] = {"status": "verified"}
        self.project.write("forge/design/candidates/a/v1/added.txt", "Unapproved change\n")
        self.assert_issue("baseline_integrity")

    def test_changed_visual_target_is_rejected(self):
        self.project.write("forge/design/evidence/target.txt", "Replaced target\n")
        self.assert_issue("visual_target_integrity")

    def test_linked_frozen_root_cannot_bypass_tree_integrity(self):
        link = self.project.root / "forge/design/linked-candidate"
        try:
            link.symlink_to(self.project.root / "forge/design/candidates/a/v1", target_is_directory=True)
        except OSError:
            if os.name == "nt":
                result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.project.root / "forge/design/candidates/a/v1")], capture_output=True)
                self.assertEqual(0, result.returncode, result.stderr)
            else:
                raise
        self.m["active_baseline"]["prototype_source_root"] = "forge/design/linked-candidate"
        self.assert_issue("baseline_integrity")

    def test_candidates_are_required_after_generation_not_before(self):
        self.assertEqual("passed", self.project.run("prototype-candidates")["result"])
        self.assert_issue("candidate_coverage", self.project.run("prototype-candidates", after=True))
        self.project.candidates()
        self.assertEqual("passed", self.project.run("prototype-candidates", after=True)["result"])
        self.assertEqual("passed", self.project.run("design-approval")["result"])

    def test_candidate_history_is_preserved_without_extra_current_candidates(self):
        self.project.candidates()
        self.m["prototype_candidates"].append({"candidate_id": "old", "version": "v0", "status": "superseded"})
        self.assertEqual("passed", self.project.run("design-approval")["result"])

    def test_candidate_receipt_needs_the_actual_version_and_external_browser(self):
        self.project.candidates()
        candidate = self.m["prototype_candidates"][0]
        receipt = candidate["browser_receipt"]
        actual = sdd.read_json(self.project.root / receipt["path"])
        for field, value in (("version", "v0"), ("browser_kind", "headless"), ("result", "failed")):
            with self.subTest(field=field):
                candidate["browser_receipt"] = self.project.evidence(receipt["path"], {**actual, field: value})
                self.assert_issue("browser_receipt", self.project.run("design-approval"))

    def test_candidate_source_changes_invalidate_review(self):
        self.project.candidates()
        self.project.write("docs/wireframes.md", "# Revised structural design\n")
        self.project.refresh()
        self.assert_issue("stale_source", self.project.run("design-approval"))

    def test_claude_sources_are_verified_before_generation(self):
        self.project.candidates(claude=True)
        self.assertEqual("passed", self.project.run("prototype-candidates")["result"])
        self.assertEqual("passed", self.project.run("design-approval")["result"])
        handoff = self.m["design_execution"]
        path = handoff["claude_source_read_receipt_path"]
        receipt = sdd.read_json(self.project.root / path)
        receipt["results"].pop()
        handoff["claude_source_read_receipt_hash"] = self.project.evidence(path, receipt)["content_hash"]
        self.assert_issue("source_access_incomplete", self.project.run("prototype-candidates"))

    def test_claude_wrong_source_hash_cannot_hide_behind_matching_counts(self):
        self.project.candidates(claude=True)
        handoff = self.m["design_execution"]
        path = handoff["claude_source_read_receipt_path"]
        receipt = sdd.read_json(self.project.root / path)
        receipt["results"][0]["content_hash"] = "0" * 64
        handoff["claude_source_read_receipt_hash"] = self.project.evidence(path, receipt)["content_hash"]
        self.assert_issue("source_access_incomplete", self.project.run("design-approval"))

    def test_claude_import_must_match_exact_selection(self):
        self.project.candidates(claude=True)
        self.m["design_execution"]["selected_candidate_version"] = "claude:b:v1"
        self.assert_issue("candidate_selection", self.project.run("design-approval"))

    def test_executor_choice_is_not_silently_defaulted(self):
        self.m["design_execution"].clear()
        self.assert_issue("design_executor_required", self.project.run("prototype-candidates"))

    def test_approval_receipt_must_match(self):
        approval = {"event": "approve_design_baseline", "actor": "fixture", "baseline_id": "B-other"}
        self.m["active_baseline"]["approval_receipt"] = self.project.evidence("forge/design/evidence/approval.json", approval)
        self.assert_issue("approval_receipt")

    def test_canonical_baseline_cannot_move_to_a_parallel_document(self):
        self.m["active_baseline"]["canonical_ref"] = {"path": "docs/prd.md", "heading": "## Use cases"}
        self.assert_issue("baseline_projection_mismatch")

    def test_missing_check_and_gate_bindings(self):
        self.m["verification"]["gates"][0]["check_ids"] = ["QA-invented"]
        self.assert_issue("unbound_gate")

    def test_no_manufactured_pass_or_release_claim(self):
        self.m["verification"]["checks"][0]["execution_status"] = "passed"
        self.assert_issue("unsupported_result")
        self.m["verification"]["release_readiness"] = "passed"
        self.assert_issue("unsupported_release_claim")

    def test_visual_evidence_cannot_replace_user_validation(self):
        self.project.execute_checks()
        self.m["verification"]["checks"][2]["evidence"][0]["kind"] = "visual"
        self.assert_issue("wrong_evidence_class")

    def test_stale_run_evidence_and_implementation_revision(self):
        self.project.execute_checks()
        self.project.write("src/app.txt", "Modified after the run.\n")
        self.assert_issue("stale_source")
        self.project.write("forge/evidence/QA-01.json", "Missing actual fixture result.\n")
        self.assert_issue("invalid_evidence")

    def test_heuristics_cannot_silently_omit_h7_or_h10(self):
        self.m["verification"]["checks"][1]["heuristic_ids"] = ["H" + str(i) for i in range(1, 7)]
        self.assert_issue("heuristic_coverage")

    def test_ui_gate_cannot_be_omitted(self):
        self.m["verification"]["gates"].pop(2)
        self.assert_issue("missing_ui_gate")

    def test_inactive_gate_cannot_remain_load_bearing(self):
        self.m["verification"]["gates"][0]["active"] = False
        self.assert_issue("inactive_load_bearing_gate")

    def test_not_applicable_needs_source_rationale(self):
        self.m["verification"]["checks"][2]["execution_status"] = "not_applicable"
        self.assert_issue("missing_rationale")

    def test_unexecuted_checks_do_not_block_authorized_implementation(self):
        self.project.authorize()
        self.assertEqual("passed", self.project.run("implementation")["result"])

    def test_unexecuted_or_deferred_required_checks_block_release(self):
        self.project.authorize()
        self.assert_issue("required_check_incomplete", self.project.run("release"))
        self.project.execute_checks()
        self.m["verification"]["checks"][2].update(execution_status="deferred", rationale="Synthetic missing participant fixture")
        self.assert_issue("required_check_incomplete", self.project.run("release"))

    def test_executed_synthetic_evidence_can_satisfy_structural_release_checks(self):
        self.project.authorize()
        self.project.execute_checks()
        self.assertEqual("passed", self.project.run("release")["result"])

    def test_severity_does_not_hide_a_blocker(self):
        self.project.authorize()
        self.project.execute_checks()
        check = self.m["verification"]["checks"][0]
        check["findings"] = [{"severity": "P1", "release_effect": "advisory", "status": "open"}]
        self.assert_issue("finding_classification")
        check["findings"][0]["release_effect"] = "blocking"
        self.assert_issue("open_blocking_finding", self.project.run("release"))

    def test_saved_release_pass_cannot_hide_open_blocker_on_resume(self):
        self.project.execute_checks()
        self.m["verification"]["release_readiness"] = "passed"
        self.m["verification"]["checks"][0]["findings"] = [{"severity": "P1", "release_effect": "blocking", "status": "open"}]
        self.assert_issue("open_blocking_finding")

    def test_advisory_failure_stays_failed_without_blocking_release(self):
        self.project.authorize()
        self.project.execute_checks()
        self.m["verification"]["gates"][2]["required"] = False
        check = self.m["verification"]["checks"][2]
        check.update(execution_status="failed", findings=[{"severity": "P2", "release_effect": "advisory", "status": "open"}])
        self.assertEqual("passed", self.project.run("release")["result"])
        self.assertEqual("failed", check["execution_status"])

    def test_gate_and_check_applicability_cannot_contradict(self):
        self.m["verification"]["gates"][2].update(applicability="not_applicable", rationale="Source-backed synthetic low-risk scope")
        self.assert_issue("contradictory_applicability")

    def test_separate_later_implementation_prompt_is_mandatory(self):
        self.assert_issue("implementation_not_authorized", self.project.run("implementation"))
        self.project.authorize()
        self.m["implementation_gate"]["awaiting_at"] = "2026-08-20T10:03:00Z"
        self.assert_issue("prompt_receipt", self.project.run("implementation"))

    def test_generic_continue_is_not_authorization(self):
        self.project.authorize()
        receipt = self.m["implementation_gate"]["prompt_receipt"]
        value = sdd.read_json(self.project.root / receipt["path"])
        value["message"] = "continue"
        self.m["implementation_gate"]["prompt_receipt"] = self.project.evidence(receipt["path"], value)
        self.assert_issue("prompt_receipt", self.project.run("implementation"))

    def test_explicit_later_implementation_prompt_needs_no_magic_wording(self):
        self.project.authorize()
        receipt = self.m["implementation_gate"]["prompt_receipt"]
        value = sdd.read_json(self.project.root / receipt["path"])
        value["message"] = "Implement it."
        self.m["implementation_gate"]["prompt_receipt"] = self.project.evidence(receipt["path"], value)
        self.assertEqual("passed", self.project.run("implementation")["result"])

    def test_changed_plan_invalidates_authorization(self):
        self.project.authorize()
        self.project.write("docs/development-plan.md", "# Changed plan\n")
        self.project.refresh(["development-plan"])
        self.assert_issue("implementation_not_authorized", self.project.run("implementation"))

    def test_promotion_receipts_are_not_planning_dependencies(self):
        self.m["prototype_promotions"] = [{"unit_id": "U-1", "path_mappings": [{"source": "index.html", "destination": "src/app.txt", "strategy": "adapt"}]}]
        self.assertEqual("passed", self.project.run()["result"])
        self.project.authorize()
        self.project.execute_checks()
        self.assert_issue("promotion_receipt", self.project.run("release"))

    def test_promotion_receipt_must_match_unit_and_strategy(self):
        self.project.authorize()
        self.project.execute_checks()
        record = {"unit_id": "U-1", "started_at": "2026-08-20T10:04:00Z", "path_mappings": [
            {"source": "forge/design/candidates/a/v1/index.html", "destination": "src/app.txt", "strategy": "adapt"}]}
        actual = {"unit_id": "U-1", "baseline_id": "B-1", "development_plan_hash": self.project.hash("docs/development-plan.md"),
                  "path_mappings": copy.deepcopy(record["path_mappings"]), "synthetic_fixture": True}
        record["receipt"] = self.project.evidence("forge/runs/U-1/prototype-promotion.json", actual)
        self.m["prototype_promotions"] = [record]
        # A matching path map alone no longer proves the actual promotion.
        self.assert_issue("promotion_receipt", self.project.run("release"))
        actual["path_mappings"][0]["strategy"] = "copy"
        record["receipt"] = self.project.evidence(record["receipt"]["path"], actual)
        self.assert_issue("promotion_receipt", self.project.run("release"))

    def test_every_planned_promotion_destination_is_checked(self):
        self.project.authorize()
        self.project.execute_checks()
        self.m["prototype_promotions"] = [{"unit_id": "U-1", "path_mappings": [
            {"source": "index.html", "destination": "src/app.txt", "strategy": "adapt"},
            {"source": "other.html", "destination": "src/missing.txt", "strategy": "adapt"}]}]
        self.assert_issue("promotion_destination", self.project.run("release"))

    def test_language_change_requires_owner_revalidation(self):
        self.m["language"].update(working_language="en", artifact_language="en")
        self.assert_issue("language_revalidation")

    def test_readonly_legacy_migration_preserves_documents_and_history(self):
        del self.m["checker_contract_version"]
        self.project.save()
        before = {str(path.relative_to(self.project.root)): path.read_bytes() for path in self.project.root.rglob("*") if path.is_file()}
        result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.project.root), "--before", "development-plan"], capture_output=True, text=True)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertEqual("migration_required", json.loads(result.stdout)["result"])
        self.assertEqual(before, {str(path.relative_to(self.project.root)): path.read_bytes() for path in self.project.root.rglob("*") if path.is_file()})
        self.m["checker_contract_version"] = 1
        self.assertEqual("passed", self.project.run()["result"])
        self.assertEqual([{"id": "preserve-me"}], self.m["history"])

    def test_path_escape_and_duplicate_json_fail_closed(self):
        self.m["artifacts"]["architecture"]["source_hashes"]["../outside.txt"] = "0" * 64
        self.assert_issue("stale_source")
        self.project.write("forge/duplicate.json", '{"state": "ok", "state": "bad"}')
        with self.assertRaises(ValueError):
            sdd.read_json(self.project.root / "forge/duplicate.json")

    def test_resume_audit_does_not_change_saved_state(self):
        original = copy.deepcopy(self.m)
        report = sdd.Checker(self.project.root, self.m).run("audit", audit=True)
        self.assertEqual("passed", report["result"], report)
        self.assertEqual(original, self.m)


if __name__ == "__main__":
    unittest.main()
