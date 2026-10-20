"""Read-only workflow projections. Gates retain authority; drafts are not answers."""


def implementation_progress(checker, worked_unit=None, action=None):
    state = getattr(checker, "_unit_progress_state", {})
    accepted = state.get("accepted_unit_ids")
    if any(item["code"] not in {"implementation_not_authorized", "prompt_receipt",
                               "authorization_correction", "unit_boundary", "unit_contract",
                               "stale_progress", "intake_progress"} for item in checker.issues):
        accepted = None
    blocked_units = [
        {"code": "unit_blocked", "target": item["unit_id"], "detail": item["reason"]}
        for item in state.get("run_blockers", [])]
    eligible = state.get("eligible_unit_ids", []) if not checker.issues else []
    blockers = list(checker.issues) + ([] if eligible else blocked_units)
    runs = checker.manifest.get("unit_runs", {})
    worked = None
    if worked_unit is not None:
        run = runs.get(worked_unit, {})
        status = run.get("status", "pending")
        outcome = status
        if action == "complete":
            outcome = ("completion_blocked" if checker.issues else
                       "accepted_complete" if accepted is not None and worked_unit in accepted else
                       "ready_to_record_completion")
        elif action == "start":
            outcome = "start_blocked" if checker.issues else "start_permitted"
        worked = {"unit_id": worked_unit, "recorded_status": status, "outcome": outcome}
        if run.get("reason"):
            worked["reason"] = run["reason"]
    return {"total_units": state.get("total_units"),
            "accepted_complete": None if accepted is None else len(accepted),
            "accepted_unit_ids": accepted, "just_worked_unit": worked,
            "next_eligible_unit": eligible[0] if eligible else None,
            "blockers": blockers, "blocked_units": blocked_units}


def validate_intake_progress(checker):
    """Check explicit handoff facts, never infer answers from arbitrary draft prose."""
    intake = checker.manifest.get("product_idea_intake")
    if intake is None:
        return
    if not isinstance(intake, dict):
        checker.issue("intake_progress", "product-idea", "product_idea_intake must be an object")
        return
    handed_off = intake.get("status") == "handed_off"
    if handed_off:
        if checker.artifacts.get("product-idea", {}).get("status") != "validated":
            checker.issue("intake_progress", "product-idea", "handed-off intake needs the current validated product-idea owner return")
        for key in ("current_request_id", "pending_question", "material_gaps"):
            if intake.get(key):
                checker.issue("intake_progress", "product-idea",
                              "handed-off intake retains unresolved " + key + "; reconcile through its owner")
        if intake.get("product_idea_hash") is not None:
            checker.snapshot("docs/product-idea.md", intake["product_idea_hash"],
                             "product-idea", "intake_progress")
    answered = intake.get("answered_decision_ids")
    pending = intake.get("pending_question")
    if isinstance(answered, list) and isinstance(pending, dict):
        decision = pending.get("decision_id")
        if decision is not None and decision in answered:
            checker.issue("intake_progress", "product-idea",
                          "pending question names an answered decision; reconcile its actual answer through the owner")


def _candidate(checker):
    """Choose a probe from metadata; only its gate result establishes readiness."""
    stages = ["product-idea", "prd", "project-context-bundle", "guardrails", "user-journey"]
    intake = checker.manifest.get("product_idea_intake")
    if isinstance(intake, dict) and intake.get("status") in ("awaiting_answer", "ready_to_submit"):
        return "product-idea", stages
    if checker.ui:
        stages.extend(["screen-map", "wireframes", "design-brief"])
    stages.extend(["architecture", "dod-evals", "qa-checklist-proposed"])
    for node in stages:
        outputs = checker.contract["nodes"][node]["outputs"]
        if any(checker.artifacts.get(key, {}).get("status") != "validated" for key in outputs):
            return node, stages
    if checker.ui:
        if not checker.manifest.get("approved_baseline_id"):
            return ("design-approval" if checker.manifest.get("prototype_candidates")
                    else "prototype-candidates"), stages
        for node in ("architecture-approved", "dod-evals-approved", "qa-checklist-approved"):
            stages.append(node)
            owner = checker.contract["nodes"][node]["owner_artifact"]
            if checker.artifacts.get(owner, {}).get("validated_baseline_id") != checker.manifest["approved_baseline_id"]:
                return node, stages
    stages.append("development-plan")
    if checker.artifacts.get("development-plan", {}).get("status") != "validated":
        return "development-plan", stages
    return "implementation", stages


def workflow_progress(checker, *, worked_unit=None, require_current=False):
    """At most two normal gate probes; no writes, network or recursive projections."""
    def probe(node, after=False):
        child = type(checker)(checker.project, checker._source_manifest, checker.contract,
                              evidence_cache=checker.evidence_resolver.cache)
        report = child.run(node, after=after, require_current=require_current, projections=False)
        return child, report

    node, stages = _candidate(checker)
    current, report = probe(node)
    # A stale validated predecessor must return to its owner before its consumers.
    # Scope/migration/history failures cannot be repaired by declaring a node ready.
    global_codes = {"migration_required", "unsupported_contract_version", "unit_history", "unit_contract",
                    "unit_stale_evidence", "product_scope"}
    owner_codes = {"missing_artifact", "wrong_owner_or_path", "stale_artifact", "not_validated",
                   "missing_validation", "missing_invocation", "stale_owner_return", "language_revalidation",
                   "invalid_dependencies", "unexpected_dependency", "missing_dependency",
                   "source_usage_missing", "source_decision_missing", "unreviewed_source",
                   "invalid_source_usage", "source_usage_conflict", "unbound_consumed_source",
                   "construction"}
    reconciliation = []
    if report["issues"] and not any(item["code"] in global_codes for item in report["issues"]):
        targets = {item.get("target") for item in report["issues"] if item["code"] in owner_codes}
        for prior in stages:
            if prior == node:
                break
            outputs = checker.contract["nodes"][prior]["outputs"]
            if targets.intersection(outputs):
                reconciliation = report["issues"]
                node = prior
                current, report = probe(node)
                break
    # Before a reconciled owner's return may pass while its own bytes are stale;
    # this means ready to repair, never that the owner output is already valid.
    ready = [node] if report["result"] == "passed" else []
    gate_issues = list(report["issues"])
    blockers = list(gate_issues)
    validate_intake_progress(current)
    intake_issues = [item for item in current.issues if item not in gate_issues]
    if intake_issues:
        ready = []
        blockers.extend(intake_issues)
    intake = checker.manifest.get("product_idea_intake")
    intake = intake if isinstance(intake, dict) else {}
    if node == "product-idea" and intake.get("status") == "awaiting_answer":
        ready = []
        blockers.append({"code": "awaiting_intake_answer", "target": "product-idea",
                         "detail": "resume the recorded pending question using its actual answer"})
    if node == "design-approval" and report["result"] == "passed":
        ready = []
        blockers.append({"code": "awaiting_design_approval", "target": "design",
                         "detail": "the exact reviewed candidate awaits the whole-design decision"})
    unit_progress = None
    unknown_worked = worked_unit is not None and worked_unit not in checker.manifest.get("unit_plan", {}).get("units", {})
    if unknown_worked:
        blockers.append({"code": "unknown_worked_unit", "target": "development-plan",
                         "detail": "worked unit is not in the current plan: " + worked_unit})
        ready = []
    if "development-plan" in report["checked_artifacts"]:
        if not unknown_worked:
            unit_progress = implementation_progress(current, worked_unit)
        if unit_progress is not None:
            blockers.extend(item for item in unit_progress["blockers"] if item not in blockers)
            if node == "implementation" and unit_progress["next_eligible_unit"] is None:
                ready = []
    # Canonical handed-off content supersedes the retained interview draft in displays.
    idea_current = ("product-idea" in report["checked_artifacts"] and not intake_issues and
                    intake.get("status") not in ("awaiting_answer", "ready_to_submit") and
                    not any(item.get("target") == "product-idea" for item in report["issues"]))
    intake_projection = {"status": "handed_off" if idea_current else intake.get("status", "not_started"),
                         "source": "docs/product-idea.md" if idea_current else "product_idea_intake",
                         "current_request_id": None if idea_current else intake.get("current_request_id")}
    result = ("migration_required" if blockers and all(item["code"] == "migration_required" for item in blockers)
              else "blocked" if blockers else "passed")
    return {"result": result, "node": "progress", "mode": "progress",
            "issues": gate_issues + intake_issues, "warnings": report["warnings"],
            "checked_artifacts": report["checked_artifacts"],
            "progress": {"next_node": node, "next_ready_nodes": ready,
                         "intake": intake_projection, "implementation": unit_progress,
                         "blockers": blockers, "owner_reconciliation": reconciliation},
            "limits": "Read-only projection of validated records; does not infer answers, grant permission, execute work or prove semantic acceptance."}


def validate_ready_projection(checker, *, derived=None, require_current=False):
    saved = checker.manifest.get("next_ready_nodes")
    if saved is None:  # Existing manifests may omit this advisory projection.
        return
    if not isinstance(saved, list) or not all(isinstance(item, str) for item in saved) or len(saved) != len(set(saved)):
        checker.issue("stale_progress", "manifest", "next_ready_nodes must be a unique node list")
        return
    if derived is None:
        derived = workflow_progress(checker, require_current=require_current)["progress"]
    if saved != derived["next_ready_nodes"]:
        checker.issue("stale_progress", "manifest",
                      "next_ready_nodes differs from current gates; run --progress and reconcile the projection")
