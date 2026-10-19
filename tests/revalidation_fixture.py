"""Immutable review contexts for synthetic checker tests; no product execution."""
from copy import deepcopy


def preserve_context(project, unit, checker):
    manifest = project.manifest
    plan = manifest["unit_plan"]
    gate = deepcopy(manifest["implementation_gate"])
    receipt = gate["prompt_receipt"]
    copied = f"forge/revalidation/{unit}-original-prompt.json"
    project.write(copied, (project.root / receipt["path"]).read_text())
    gate["prompt_receipt"] = {"path": copied, "content_hash": project.hash(copied)}
    original_plan = f"forge/revalidation/{unit}-original-plan.md"
    project.write(original_plan, (project.root / "docs/development-plan.md").read_text())
    checks = {item["check_id"]: deepcopy(item) for item in manifest["verification"]["checks"]
              if item["check_id"] in plan["units"][unit]["required_check_ids"]}
    definitions = {item["path"]: project.hash(item["path"]) for key, item in manifest["artifacts"].items()
                   if key != "development-plan" and (project.root / item["path"]).is_file()}
    return {"unit_plan": deepcopy(plan), "unit_run": deepcopy(manifest["unit_runs"][unit]), "checks": checks, "definition_source_hashes": definitions,
            "plan_source": {"path": original_plan, "content_hash": project.hash(original_plan), "schema": "evidence-bytes-v1"},
            "implementation_gate": gate}


def fresh_plan_authorization(project):
    """A fixture user event after the original executions, not revalidation consent."""
    project.refresh(["development-plan"])
    project.authorize()
    gate = project.manifest["implementation_gate"]
    gate.update(awaiting_at="2026-08-20T10:20:00Z", prompt_received_at="2026-08-20T10:21:00Z", released_at="2026-08-20T10:21:01Z")
    event = {key: gate[key] for key in ("development_plan_hash", "approved_baseline_id", "prompt_id")}
    event.update(event="implementation_prompt", intent="start_production_implementation", role="user",
                 received_at=gate["prompt_received_at"], message="Synthetic user: implement the changed validated plan.")
    gate["prompt_receipt"] = project.evidence("forge/runs/current-implementation-prompt.json", event)


def record_review(project, unit, context, checker, *, minute=22, changes=None):
    manifest = project.manifest
    originals = {}
    for check in context["checks"].values():
        originals.update(checker.source_inventory(check, "evaluated_source_hashes")[0])
    current = {path: project.hash(path) for path in originals}
    impact = [{"path": path, "original_hash": originals[path], "current_hash": current[path],
               "behavior_changed": False, "claims_unchanged": True, "rationale": "Synthetic review: inert comment change only."}
              for path in originals if originals[path] != current[path]]
    event = {"version": 1, "event": "unit_acceptance_revalidation", "unit_id": unit,
             "reviewer": "synthetic named reviewer", "reviewed_at": f"2026-08-20T10:{minute:02}:00Z", "outcome": "retained",
             "behavior_changed": False, "claims_unchanged": True, "impact_summary": "Synthetic review: unchanged specified behavior and acceptance; editorial/comment change only.",
             "original_plan_hash": context["unit_run"]["development_plan_hash"],
             "current_plan_hash": project.hash("docs/development-plan.md"), "approved_baseline_id": "B-1",
             "retained_check_ids": manifest["unit_plan"]["units"][unit]["required_check_ids"].copy(),
             "retained_claims": {key: manifest["unit_plan"]["acceptance"][key]["obligation_ids"].copy() for key in context["checks"]},
             "original_context": project.evidence(f"forge/revalidation/{unit}-context.json", context),
             "current_source_hashes": current, "changed_paths": impact, "required_new_check_ids": [], **(changes or {})}
    ref = project.evidence(f"forge/revalidation/{unit}-review.json", event)
    manifest["unit_runs"][unit]["revalidation_ref"] = ref
    for check in manifest["verification"]["checks"]:
        if check["check_id"] in context["checks"]:
            check["revalidation_ref"] = ref
    return event
