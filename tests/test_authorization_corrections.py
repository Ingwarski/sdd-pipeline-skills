"""Synthetic authorization continuity; these receipts are not real user evidence."""

import copy
import json
import tempfile
import unittest

from test_sdd_check import CONTRACT, Project, sdd


class AuthorizationCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.fresh()

    def fresh(self):
        temp = tempfile.TemporaryDirectory(prefix="sdd-authorization-correction-")
        self.addCleanup(temp.cleanup)
        self.p = Project(temp.name)
        self.m = self.p.manifest
        self.p.authorize()
        self.original_gate = copy.deepcopy(self.m["implementation_gate"])
        self.original_prompt = (self.p.root / self.original_gate["prompt_receipt"]["path"]).read_bytes()
        self.steps = []

    def read(self, ref):
        return sdd.read_json(self.p.root / ref["path"])

    def rewrite(self, ref, value):
        ref.update(self.p.evidence(ref["path"], value))

    def auth_issues(self):
        checker = sdd.Checker(self.p.root, self.m)
        checker.authorization()
        return checker.issues

    def assert_authorized(self):
        self.assertEqual([], self.auth_issues())

    def assert_rejected(self):
        self.assertTrue(self.auth_issues(), "invalid correction preserved authorization")

    def correction(self, paths=("docs/development-plan.md",), mutate=None):
        """Capture real before/after bytes; refresh owners without issuing a prompt."""
        index = len(self.steps) + 1
        prefix = f"forge/runs/corrections/{index}"
        canonical_paths = sorted(artifact["path"] for artifact in self.m["artifacts"].values())
        before = {path: (self.p.root / path).read_text(encoding="utf-8") for path in canonical_paths}
        original_manifest = self.p.evidence(prefix + "/original-manifest.json", copy.deepcopy(self.m)) if index == 1 else None
        from_hash = self.p.hash("docs/development-plan.md")
        if mutate:
            mutate()
        for path in paths:
            text = (self.p.root / path).read_text(encoding="utf-8")
            self.p.write(path, text.replace("\n## ", f"\nApproved retry wording recorded, correction {index}.\n\n## ", 1))
        for artifact in self.m["artifacts"].values():
            artifact["content_hash"] = self.p.hash(artifact["path"])
            artifact["source_hashes"] = {path: self.p.hash(path) for path in artifact["source_hashes"]}
        self.m["verification"]["source_hashes"] = {
            "docs/" + key + ".md": self.p.hash("docs/" + key + ".md")
            for key in ("qa-checklist", "dod-evals")}
        decision_id = f"synthetic-user-decision-{index}"
        decision = self.p.evidence(prefix + "/decision.json", {
            "event": "approved_decision", "role": "user", "decision_id": decision_id,
            "approved_at": "2026-08-20T10:00:30Z",
            "message": "Keep the existing retry behavior; record this already approved wording.",
            "synthetic_fixture": True, "host_metadata": "unavailable in synthetic fixture"})
        source_snapshots = {}
        for ordinal, path in enumerate(canonical_paths):
            snapshots = {}
            for label, text in (("before", before[path]), ("after", (self.p.root / path).read_text(encoding="utf-8"))):
                snapshot_path = f"{prefix}/{ordinal}-{label}.md"
                self.p.write(snapshot_path, text)
                snapshots[label] = {"path": snapshot_path, "content_hash": self.p.hash(snapshot_path)}
            source_snapshots[path] = snapshots
        documents = []
        for path in paths:
            key = next(key for key, spec in CONTRACT["artifacts"].items() if spec["path"] == path)
            documents.append({"path": path, "owner_skill": CONTRACT["artifacts"][key]["owner_skill"],
                "owner_invocation_id": self.m["artifacts"][key]["owner_invocation_id"],
                "decision_ids": [decision_id], **source_snapshots[path]})
        review = self.p.evidence(prefix + "/review.json", {
            "event": "documentation_correction_review", "reviewer": "synthetic-independent-reviewer",
            "reviewed_at": f"2026-08-20T10:{index + 2:02}:30Z", "result": "preserves_approved_intent",
            "rationale": "Compared all snapshots to the earlier decision; only its omitted wording is added.",
            "decision_ids": [decision_id],
            "documents": {d["path"]: {"before_hash": d["before"]["content_hash"], "after_hash": d["after"]["content_hash"]} for d in documents},
            "source_snapshots": {path: {"before_hash": snapshots["before"]["content_hash"],
                "after_hash": snapshots["after"]["content_hash"]} for path, snapshots in source_snapshots.items()},
            "unchanged": {key: True for key in ("scope", "behavior", "design", "security", "cost", "acceptance", "unit_contract", "permissions")}})
        baseline = self.m.get("active_baseline")
        value = {"event": "approved_decision_documentation_correction", "version": 1,
            "author": "synthetic-document-owner", "recorded_at": f"2026-08-20T10:{index + 2:02}:00Z",
            "from_plan_hash": from_hash, "to_plan_hash": self.p.hash("docs/development-plan.md"),
            "approved_baseline_id": self.original_gate["approved_baseline_id"],
            "product_scope_hash": self.original_gate.get("product_scope_hash"),
            "baseline": {key: baseline[key] for key in ("prototype_tree_hash", "visual_target_hash")} if baseline else None,
            "decisions": [decision], "documents": documents, "source_snapshots": source_snapshots, "review": review}
        if original_manifest is not None:
            value["original_manifest"] = original_manifest
        ref = self.p.evidence(prefix + "/correction.json", value)
        self.steps.append(ref)
        self.m["implementation_gate"].update(development_plan_hash=value["to_plan_hash"], correction_receipts=copy.deepcopy(self.steps))
        return value

    def save_correction(self, value, index=-1):
        self.rewrite(self.steps[index], value)
        self.m["implementation_gate"]["correction_receipts"] = copy.deepcopy(self.steps)

    def change_review(self, receipt, mutate):
        review = self.read(receipt["review"])
        mutate(review)
        self.rewrite(receipt["review"], review)
        self.save_correction(receipt)

    def headless(self):
        """Remove UI artifacts and retain actual functional/security obligations."""
        scope = {"profile": "headless", "capabilities": {"ui": False, "api": True,
            "persistence": True, "payments": False, "sensitive_data": True}}
        path = "docs/product-idea.md"
        self.p.write(path, (self.p.root / path).read_text() + "\n## Scope\n```json\n" + json.dumps(scope) + "\n```\n")
        self.m["product_scope"] = {**scope, "definition_ref": {"path": path, "heading": "## Scope"}}
        self.m["verification"]["checks"][0]["gate_id"] = "functional_delivery"
        self.m["verification"]["gates"][0]["check_ids"] = []
        self.m["verification"]["gates"].append({"gate_id": "functional_delivery", "active": True,
            "required": True, "applicability": "applicable", "check_ids": ["QA-01"],
            "definition_ref": {"path": "docs/dod-evals.md", "heading": "## Gates"}})
        path = "docs/dod-evals.md"
        self.p.write(path, (self.p.root / path).read_text() + "\nfunctional_delivery\n")
        self.p.refresh()
        for key in ("screen-map", "wireframes", "design-brief"):
            self.m["artifacts"].pop(key)
            (self.p.root / ("docs/" + key + ".md")).unlink()
        for artifact in self.m["artifacts"].values():
            artifact["dependencies"] = [key for key in artifact["dependencies"] if key not in ("screen-map", "wireframes", "design-brief")]
            for key in ("screen-map", "wireframes", "design-brief"):
                artifact["source_hashes"].pop("docs/" + key + ".md", None)
                artifact["source_usage"].pop("docs/" + key + ".md", None)
            if "traceability" in artifact:
                artifact["traceability"]["links"] = [link for link in artifact["traceability"]["links"] if link["to"] != "STATE-01"]
        self.m.pop("active_baseline")
        self.m["approved_baseline_id"] = None
        for gate in self.m["verification"]["gates"]:
            if gate["gate_id"] in sdd.GATE_KINDS:
                gate.update(applicability="not_applicable", rationale="Synthetic headless scope")
        for check in self.m["verification"]["checks"]:
            if check["gate_id"] in sdd.GATE_KINDS:
                check.update(execution_status="not_applicable", rationale="Synthetic headless scope")
        eligible = {c["check_id"] for c in self.m["verification"]["checks"] if c["execution_status"] != "not_applicable"}
        self.m["unit_plan"]["acceptance"] = {key: {**value,
            "obligation_ids": [item for item in value["obligation_ids"] if item != "STATE-01"]}
            for key, value in self.m["unit_plan"]["acceptance"].items() if key in eligible}
        self.m["unit_plan"]["units"]["U-1"]["required_check_ids"] = sorted(eligible)
        self.p.sync_unit_contract()
        self.p.authorize()
        gate = self.m["implementation_gate"]
        gate["approved_baseline_id"] = None
        gate["product_scope_hash"] = sdd.digest(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode())
        prompt = self.read(gate["prompt_receipt"])
        prompt.update(approved_baseline_id=None, product_scope_hash=gate["product_scope_hash"])
        self.rewrite(gate["prompt_receipt"], prompt)
        self.original_gate = copy.deepcopy(gate)

    def test_headless_correction_preserves_null_baseline_and_original_scope(self):
        self.headless()
        self.assertEqual("passed", self.p.run("implementation")["result"])
        receipt = self.correction()
        self.assertIsNone(receipt["baseline"])
        self.assertIsNone(receipt["approved_baseline_id"])
        self.assert_authorized()
        report = self.p.run("implementation")
        self.assertEqual("passed", report["result"], report)

    def test_correction_cannot_expand_original_headless_product_scope(self):
        self.headless()
        self.correction()
        self.m["product_scope"]["capabilities"]["payments"] = True
        scope = {key: self.m["product_scope"][key] for key in ("profile", "capabilities")}
        self.m["implementation_gate"]["product_scope_hash"] = sdd.digest(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode())
        self.assert_rejected()

    def test_archived_original_prompt_preserves_its_binding_through_verified_correction(self):
        # Compose archive/cache setup without inheriting or re-running its suite.
        from test_evidence_checker import EvidenceCheckerTests
        storage = EvidenceCheckerTests("runTest")
        storage.setUp()
        self.addCleanup(storage.doCleanups)
        storage.p, storage.m = self.p, self.m
        self.p.write("forge/evidence-policy.json", json.dumps(storage.policy))
        self.m["evidence_accounting"] = {"version": 1, "project_id": storage.policy["project_id"],
            "policy_sha256": self.p.hash("forge/evidence-policy.json"), "runs": {}}
        gate = self.m["implementation_gate"]
        receipt = storage.replace(gate["prompt_receipt"], "original-corrected-prompt", "authorization",
            {key: gate[key] for key in ("prompt_id", "development_plan_hash", "approved_baseline_id")})
        gate["prompt_receipt"] = receipt
        self.original_gate = copy.deepcopy(gate)
        self.correction()
        checker = sdd.Checker(self.p.root, self.m, evidence_cache=storage.cache)
        self.assertTrue(checker.authorization(), checker.issues)
        self.assertEqual([], checker.issues)
        self.assertNotEqual(receipt["bindings"]["development_plan_hash"], gate["development_plan_hash"])
        self.assertEqual(self.original_prompt, checker.evidence_bytes(receipt))
        receipt["bindings"]["development_plan_hash"] = gate["development_plan_hash"]
        changed = sdd.Checker(self.p.root, self.m, evidence_cache=storage.cache)
        self.assertFalse(changed.authorization())
        self.assertTrue(changed.issues)

    def test_original_explicit_prompt_still_works_without_corrections(self):
        self.assert_authorized()
        report = self.p.run("implementation")
        self.assertEqual("passed", report["result"], report)

    def test_prior_decision_correction_preserves_original_prompt_and_full_start(self):
        self.assertEqual("passed", self.p.run("implementation")["result"])
        self.correction(("docs/development-plan.md", "docs/qa-checklist.md"))
        self.assert_authorized()
        report = sdd.Checker(self.p.root, self.m).run("implementation", unit_action="start", unit_id="U-1")
        self.assertEqual("passed", report["result"], report)
        gate = self.m["implementation_gate"]
        for key in ("prompt_id", "prompt_receipt", "awaiting_at", "prompt_received_at", "released_at"):
            self.assertEqual(self.original_gate[key], gate[key])
        self.assertEqual(self.original_prompt, (self.p.root / gate["prompt_receipt"]["path"]).read_bytes())
        self.assertTrue(all(c["execution_status"] == "not_run" for c in self.m["verification"]["checks"]))

    def test_multistep_chain_retains_each_intermediate_snapshot(self):
        first = self.correction(("docs/development-plan.md", "docs/qa-checklist.md"))
        second = self.correction(("docs/development-plan.md", "docs/qa-checklist.md"))
        self.assertEqual(first["to_plan_hash"], second["from_plan_hash"])
        self.assert_authorized()
        self.assertEqual("passed", self.p.run("implementation")["result"])

    def test_correction_cannot_create_initial_authorization(self):
        self.correction()
        self.m["implementation_gate"]["state"] = "awaiting_implementation_prompt"
        self.assert_rejected()

    def test_original_prompt_is_still_required_and_integrity_bound(self):
        for mode in ("missing", "generic", "wrong_intent", "tampered"):
            with self.subTest(mode=mode):
                self.fresh()
                self.correction()
                ref = self.m["implementation_gate"]["prompt_receipt"]
                if mode == "missing":
                    del self.m["implementation_gate"]["prompt_receipt"]
                elif mode == "tampered":
                    self.p.write(ref["path"], "{}\n")
                else:
                    value = self.read(ref)
                    value.update({"message": "continue"} if mode == "generic" else {"intent": "discuss_plan"})
                    self.rewrite(ref, value)
                self.assert_rejected()

    def test_missing_or_empty_correction_chain_cannot_rebind_old_prompt(self):
        for value in (None, []):
            with self.subTest(value=value):
                self.fresh()
                self.correction()
                if value is None:
                    self.m["implementation_gate"].pop("correction_receipts")
                else:
                    self.m["implementation_gate"]["correction_receipts"] = value
                self.assert_rejected()

    def test_decision_requires_original_user_evidence_and_timely_approval(self):
        for mode in ("missing", "empty", "tampered", "late", "future", "non_user", "wrong_event", "no_message", "no_id"):
            with self.subTest(mode=mode):
                self.fresh()
                receipt = self.correction()
                ref = receipt["decisions"][0]
                decision = self.read(ref)
                if mode == "missing":
                    (self.p.root / ref["path"]).unlink()
                elif mode == "empty":
                    receipt["decisions"] = []
                    self.save_correction(receipt)
                elif mode == "tampered":
                    self.p.write(ref["path"], "{}\n")
                else:
                    if mode in ("late", "future"):
                        decision["approved_at"] = "2026-08-20T10:02:30Z" if mode == "late" else "2999-01-01T00:00:00Z"
                    elif mode == "non_user":
                        decision["role"] = "assistant"
                    elif mode == "wrong_event":
                        decision["event"] = "proposal"
                    else:
                        decision.pop("message" if mode == "no_message" else "decision_id")
                    self.rewrite(ref, decision)
                    self.save_correction(receipt)
                self.assert_rejected()

    def test_correction_times_must_follow_release_and_not_be_in_future(self):
        for time in ("2026-08-20T10:02:00Z", "2999-01-01T00:00:00Z", "2026-08-20T10:03:00"):
            with self.subTest(time=time):
                self.fresh()
                receipt = self.correction()
                receipt["recorded_at"] = time
                self.save_correction(receipt)
                self.assert_rejected()

    def test_independent_review_and_rationale_are_required(self):
        for mode in ("missing", "self", "empty_reviewer", "no_rationale", "wrong_result", "before_correction", "future", "tampered"):
            with self.subTest(mode=mode):
                self.fresh()
                receipt = self.correction()
                if mode == "missing":
                    receipt.pop("review")
                    self.save_correction(receipt)
                elif mode == "tampered":
                    self.p.write(receipt["review"]["path"], "{}\n")
                else:
                    changes = {"self": {"reviewer": receipt["author"]}, "empty_reviewer": {"reviewer": " "},
                        "no_rationale": {"rationale": ""}, "wrong_result": {"result": "needs_changes"},
                        "before_correction": {"reviewed_at": "2026-08-20T10:02:30Z"},
                        "future": {"reviewed_at": "2999-01-01T00:00:00Z"}}
                    self.change_review(receipt, lambda value: value.update(changes[mode]))
                self.assert_rejected()

    def test_each_unchanged_dimension_must_be_explicitly_true(self):
        for dimension in ("scope", "behavior", "design", "security", "cost", "acceptance", "unit_contract", "permissions"):
            for value in (False, "true", None):
                with self.subTest(dimension=dimension, value=value):
                    self.fresh()
                    receipt = self.correction()
                    self.change_review(receipt, lambda review: review["unchanged"].update({dimension: value}))
                    self.assert_rejected()

    def test_missing_review_dimension_is_not_an_unchanged_claim(self):
        receipt = self.correction()
        self.change_review(receipt, lambda review: review["unchanged"].pop("security"))
        self.assert_rejected()

    def test_review_binds_exact_document_hashes_and_decision_ids(self):
        for mode in ("before_hash", "after_hash", "missing_path", "extra_path", "wrong_decision", "extra_decision"):
            with self.subTest(mode=mode):
                self.fresh()
                receipt = self.correction()
                def mutate(review):
                    if mode in ("before_hash", "after_hash"):
                        review["documents"]["docs/development-plan.md"][mode] = "0" * 64
                    elif mode == "missing_path":
                        review["documents"].clear()
                    elif mode == "extra_path":
                        review["documents"]["src/app.txt"] = copy.deepcopy(next(iter(review["documents"].values())))
                    elif mode == "wrong_decision":
                        review["decision_ids"] = ["unapproved-decision"]
                    else:
                        review["decision_ids"].append("unapproved-decision")
                self.change_review(receipt, mutate)
                self.assert_rejected()

    def test_snapshots_must_exist_and_match_their_recorded_hashes(self):
        for label in ("before", "after"):
            for mode in ("missing", "tampered"):
                with self.subTest(label=label, mode=mode):
                    self.fresh()
                    receipt = self.correction()
                    path = receipt["documents"][0][label]["path"]
                    if mode == "missing":
                        (self.p.root / path).unlink()
                    else:
                        self.p.write(path, "An unreviewed replacement snapshot.\n")
                    self.assert_rejected()

    def test_last_snapshot_must_equal_current_document_even_after_owner_refresh(self):
        self.correction()
        self.p.write("docs/development-plan.md", (self.p.root / "docs/development-plan.md").read_text() + "\nUnreviewed prose.\n")
        self.p.refresh()
        self.m["implementation_gate"]["development_plan_hash"] = self.p.hash("docs/development-plan.md")
        self.assert_rejected()

    def test_document_paths_owners_invocations_and_decisions_are_bound(self):
        for mode in ("production", "noncanonical", "owner", "invocation", "decision", "duplicate", "missing_plan"):
            with self.subTest(mode=mode):
                self.fresh()
                receipt = self.correction(("docs/development-plan.md", "docs/qa-checklist.md"))
                document = receipt["documents"][0]
                if mode == "production":
                    document["path"] = "src/app.txt"
                elif mode == "noncanonical":
                    document["path"] = "docs/../docs/development-plan.md"
                elif mode == "owner":
                    document["owner_skill"] = "to-qa-checklist"
                elif mode == "invocation":
                    document["owner_invocation_id"] = "unreturned-owner-run"
                elif mode == "decision":
                    document["decision_ids"] = ["unapproved-decision"]
                elif mode == "duplicate":
                    receipt["documents"].append(copy.deepcopy(document))
                else:
                    receipt["documents"] = receipt["documents"][1:]
                self.save_correction(receipt)
                self.assert_rejected()

    def test_plan_contract_changes_cannot_be_called_documentation_corrections(self):
        for mode in ("scope", "qa_mapping", "implementation_paths"):
            with self.subTest(mode=mode):
                self.fresh()
                def mutate():
                    plan = self.m["unit_plan"]
                    if mode == "scope":
                        plan["units"]["U-1"]["scope"] = "Additional payment behavior"
                    elif mode == "qa_mapping":
                        plan["acceptance"]["QA-01"]["obligation_ids"] = ["NFR-02"]
                    else:
                        plan["units"]["U-1"]["implementation_paths"].append("src/new-feature.txt")
                    self.p.sync_unit_contract()
                self.correction(mutate=mutate)
                self.assert_rejected()

    def test_unit_order_is_frozen_even_when_both_units_are_independent(self):
        plan = self.m["unit_plan"]
        plan["order"].append("U-2")
        plan["units"]["U-1"]["required_check_ids"].remove("QA-02")
        plan["units"]["U-2"] = {"scope": "Independent component", "owner": "fixture executor",
            "kind": "implementation", "construction_dependencies": [], "implementation_paths": ["src/component.txt"],
            "required_check_ids": ["QA-02"]}
        plan["acceptance"]["QA-02"]["owner_unit"] = "U-2"
        self.m["verification"]["checks"][1]["acceptance"].update(level="unit", evidence_mode="component",
            required_source_paths=["src/component.txt"])
        trace = self.m["artifacts"]["development-plan"]["traceability"]
        trace["definitions"].append({"id": "U-2", "kind": "unit", "required": True,
            "definition_ref": {"path": "docs/development-plan.md", "heading": "## Definition"}})
        path = "docs/development-plan.md"
        self.p.write(path, (self.p.root / path).read_text().replace("## Definition\n", "## Definition\nU-2\n"))
        self.p.sync_unit_contract()
        self.p.authorize()
        self.original_gate = copy.deepcopy(self.m["implementation_gate"])
        self.assertEqual("passed", self.p.run("implementation")["result"])
        def mutate():
            plan["order"].reverse()
            self.p.sync_unit_contract()
        self.correction(mutate=mutate)
        self.assert_rejected()

    def test_changed_qa_acceptance_json_cannot_keep_old_authorization(self):
        def mutate():
            self.m["verification"]["checks"][0]["acceptance"]["required_source_paths"].append("src/new-feature.txt")
            self.p.sync_unit_contract()
        self.correction(("docs/development-plan.md", "docs/qa-checklist.md"), mutate=mutate)
        self.assert_rejected()

    def test_omitting_changed_qa_document_cannot_hide_new_consumer_acceptance(self):
        self.assertEqual("passed", self.p.run("implementation")["result"])
        def mutate():
            self.m["verification"]["checks"][0]["acceptance"]["required_source_paths"] = ["src/unapproved-consumer.txt"]
            self.p.sync_unit_contract()
        receipt = self.correction(mutate=mutate)
        self.assertEqual(["docs/development-plan.md"], [item["path"] for item in receipt["documents"]])
        report = self.p.run("implementation")
        self.assertNotEqual("passed", report["result"], report)
        self.assertTrue(any(issue["code"] == "authorization_correction" for issue in report["issues"]), report)

    def test_substituted_before_qa_cannot_disagree_with_original_manifest(self):
        def mutate():
            self.m["verification"]["checks"][0]["acceptance"]["required_source_paths"] = ["src/unapproved-consumer.txt"]
            self.p.sync_unit_contract()
        receipt = self.correction(mutate=mutate)
        archive = self.read(receipt["original_manifest"])
        original_qa_hash = archive["artifacts"]["qa-checklist"]["content_hash"]
        qa = receipt["source_snapshots"]["docs/qa-checklist.md"]
        self.assertNotEqual(original_qa_hash, qa["after"]["content_hash"])
        qa["before"] = copy.deepcopy(qa["after"])
        review = self.read(receipt["review"])
        review["source_snapshots"]["docs/qa-checklist.md"]["before_hash"] = qa["before"]["content_hash"]
        self.rewrite(receipt["review"], review)
        self.save_correction(receipt)
        self.assertEqual(archive, self.read(receipt["original_manifest"]))
        report = self.p.run("implementation")
        self.assertNotEqual("passed", report["result"], report)
        self.assertTrue(any(issue["code"] == "authorization_correction" for issue in report["issues"]), report)

    def test_complete_inventory_detects_omitted_noncontract_document_change(self):
        def mutate():
            path = "docs/architecture.md"
            self.p.write(path, (self.p.root / path).read_text() + "\nUnreviewed deployment architecture change.\n")
        self.correction(mutate=mutate)
        self.assert_rejected()

    def test_source_inventory_is_complete_and_reviewed_even_for_unchanged_sources(self):
        for mode in ("missing", "empty", "omitted", "extra", "review_hash"):
            with self.subTest(mode=mode):
                self.fresh()
                receipt = self.correction()
                review = self.read(receipt["review"])
                if mode == "missing":
                    receipt.pop("source_snapshots")
                elif mode == "empty":
                    receipt["source_snapshots"] = {}
                    review["source_snapshots"] = {}
                elif mode == "omitted":
                    receipt["source_snapshots"].pop("docs/qa-checklist.md")
                    review["source_snapshots"].pop("docs/qa-checklist.md")
                elif mode == "extra":
                    receipt["source_snapshots"]["src/app.txt"] = copy.deepcopy(receipt["source_snapshots"]["docs/qa-checklist.md"])
                    review["source_snapshots"]["src/app.txt"] = copy.deepcopy(review["source_snapshots"]["docs/qa-checklist.md"])
                else:
                    review["source_snapshots"]["docs/qa-checklist.md"]["after_hash"] = "0" * 64
                self.rewrite(receipt["review"], review)
                self.save_correction(receipt)
                self.assert_rejected()

    def test_original_manifest_is_required_and_bound_to_original_authorization(self):
        for mode in ("missing", "tampered", "wrong_prompt", "wrong_source", "wrong_contract"):
            with self.subTest(mode=mode):
                self.fresh()
                receipt = self.correction()
                if mode == "missing":
                    receipt.pop("original_manifest")
                elif mode == "tampered":
                    self.p.write(receipt["original_manifest"]["path"], "{}\n")
                else:
                    archive = self.read(receipt["original_manifest"])
                    if mode == "wrong_prompt":
                        archive["implementation_gate"]["prompt_id"] = "unrelated-authorization"
                    elif mode == "wrong_source":
                        archive["artifacts"]["qa-checklist"]["content_hash"] = "0" * 64
                    else:
                        archive["verification"]["checks"][0]["acceptance"]["required_source_paths"] = ["src/other-consumer.txt"]
                    self.rewrite(receipt["original_manifest"], archive)
                self.save_correction(receipt)
                self.assert_rejected()

    def test_numeric_one_cannot_replace_a_boolean_in_archived_qa_contract(self):
        def mutate():
            self.m["verification"]["checks"][0]["acceptance"]["required"] = 1
            self.p.sync_unit_contract()
        self.correction(("docs/development-plan.md", "docs/qa-checklist.md"), mutate=mutate)
        self.assert_rejected()

    def test_malformed_correction_references_fail_closed(self):
        for value in ({"path": "forge/runs/corrections/1/correction.json"}, [None], "correction.json"):
            with self.subTest(value=value):
                self.fresh()
                self.correction()
                self.m["implementation_gate"]["correction_receipts"] = value
                self.assert_rejected()

    def test_correction_receipt_bytes_are_integrity_bound(self):
        for mode in ("missing", "tampered"):
            with self.subTest(mode=mode):
                self.fresh()
                self.correction()
                path = self.steps[0]["path"]
                if mode == "missing":
                    (self.p.root / path).unlink()
                else:
                    self.p.write(path, "{}\n")
                self.assert_rejected()

    def test_current_owner_refresh_is_required_besides_a_valid_receipt(self):
        receipt = self.correction()
        self.m["artifacts"]["development-plan"]["source_hashes"]["docs/qa-checklist.md"] = "0" * 64
        self.assert_authorized()
        report = self.p.run("implementation")
        self.assertNotEqual("passed", report["result"], report)
        self.assertTrue(any(i["code"] == "stale_source" for i in report["issues"]), report)
        self.assertEqual(receipt["to_plan_hash"], self.p.hash("docs/development-plan.md"))

    def test_baseline_and_scope_cannot_change_through_a_correction(self):
        for mode in ("baseline_id", "prototype", "visual_target", "scope"):
            with self.subTest(mode=mode):
                self.fresh()
                receipt = self.correction()
                if mode == "baseline_id":
                    receipt["approved_baseline_id"] = "B-2"
                elif mode == "scope":
                    receipt["product_scope_hash"] = "0" * 64
                else:
                    receipt["baseline"]["prototype_tree_hash" if mode == "prototype" else "visual_target_hash"] = "0" * 64
                self.save_correction(receipt)
                self.assert_rejected()

    def test_replacing_active_baseline_cannot_be_hidden_by_matching_gate(self):
        self.correction()
        self.m["approved_baseline_id"] = self.m["active_baseline"]["baseline_id"] = "B-2"
        self.m["implementation_gate"]["approved_baseline_id"] = "B-2"
        self.assert_rejected()

    def test_baseline_approved_after_original_prompt_is_not_preapproved(self):
        self.correction()
        ref = self.m["active_baseline"]["approval_receipt"]
        approval = self.read(ref)
        approval["approved_at"] = "2026-08-20T10:02:30Z"
        self.rewrite(ref, approval)
        self.assert_rejected()

    def test_chain_rejects_missing_interrupted_cyclic_and_extraneous_steps(self):
        for mode in ("missing_first", "missing_last", "interrupted", "cycle", "extraneous", "reversed"):
            with self.subTest(mode=mode):
                self.fresh()
                first = self.correction()
                second = self.correction()
                if mode == "interrupted":
                    second["from_plan_hash"] = "0" * 64
                    self.save_correction(second)
                elif mode == "cycle":
                    second["to_plan_hash"] = first["from_plan_hash"]
                    self.save_correction(second)
                else:
                    refs = self.m["implementation_gate"]["correction_receipts"]
                    if mode == "missing_first":
                        refs.pop(0)
                    elif mode == "missing_last":
                        refs.pop()
                    elif mode == "extraneous":
                        refs.append(copy.deepcopy(refs[-1]))
                    else:
                        refs.reverse()
                self.assert_rejected()

    def test_repeated_document_snapshot_chain_cannot_skip_an_intermediate_revision(self):
        first = self.correction(("docs/development-plan.md", "docs/qa-checklist.md"))
        second = self.correction(("docs/development-plan.md", "docs/qa-checklist.md"))
        second["documents"][1]["before"] = copy.deepcopy(first["documents"][1]["before"])
        review = self.read(second["review"])
        review["documents"]["docs/qa-checklist.md"]["before_hash"] = second["documents"][1]["before"]["content_hash"]
        self.rewrite(second["review"], review)
        self.save_correction(second)
        self.assert_rejected()

    def test_new_prompt_for_current_plan_does_not_need_old_correction_chain(self):
        self.correction()
        self.p.authorize()
        gate = self.m["implementation_gate"]
        gate.update(prompt_id="synthetic-new-prompt-3", awaiting_at="2026-08-20T10:04:00Z",
            prompt_received_at="2026-08-20T10:05:00Z", released_at="2026-08-20T10:05:01Z")
        prompt = self.read(gate["prompt_receipt"])
        prompt.update(prompt_id=gate["prompt_id"], received_at=gate["prompt_received_at"])
        gate["prompt_receipt"] = self.p.evidence("forge/runs/new-implementation-prompt.json", prompt)
        self.assertNotIn("correction_receipts", gate)
        self.assert_authorized()
        self.assertEqual("passed", self.p.run("implementation")["result"])

    def test_correction_does_not_turn_unrun_checks_into_completion(self):
        self.correction()
        self.assert_authorized()
        self.m["unit_runs"] = {"U-1": {"status": "running", "started_at": "2026-08-20T10:04:00Z",
            "development_plan_hash": self.p.hash("docs/development-plan.md"), "approved_baseline_id": "B-1", "findings": []}}
        report = sdd.Checker(self.p.root, self.m).run("implementation", unit_action="complete", unit_id="U-1")
        self.assertNotEqual("passed", report["result"], report)
        self.assertTrue(any("required acceptance is not passed" in issue["detail"] for issue in report["issues"]), report)
        self.assertNotEqual("passed", self.p.run("release")["result"])

    def test_prior_passed_evidence_is_not_rebound_to_corrected_plan(self):
        self.p.execute_checks()
        self.assertEqual("passed", self.p.run("release")["result"])
        old_checks = copy.deepcopy(self.m["verification"]["checks"])
        old_run = copy.deepcopy(self.m["unit_runs"])
        self.correction()
        self.assert_authorized()
        report = self.p.run("release")
        self.assertNotEqual("passed", report["result"], report)
        self.assertEqual(old_checks, self.m["verification"]["checks"])
        self.assertEqual(old_run, self.m["unit_runs"])

    def test_correction_does_not_override_failed_product_evidence(self):
        self.correction()
        self.p.execute_checks()
        self.m["verification"]["checks"][0]["execution_status"] = "failed"
        self.assert_authorized()
        self.assertNotEqual("passed", self.p.run("release")["result"])


if __name__ == "__main__":
    unittest.main()
