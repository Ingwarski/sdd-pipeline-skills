"""Reviewed carry-forward of immutable acceptance, never execution or authorization."""
import re
from datetime import datetime
from evidence.resolver import evidence_reference


def validate_revalidation(checker, *, check=None, unit_id=None):
    """Return the current review while leaving the original observation untouched.

    The conservative v1 extension permits identical unit contracts only. Review
    authenticity and semantic impact remain host responsibilities, like execution.
    """
    def require(condition, detail):
        if not condition:
            raise ValueError("acceptance revalidation: " + detail)

    def without_review(record):
        return {key: value for key, value in record.items() if key != "revalidation_ref"}

    def stamp(value):
        require(isinstance(value, str), "timezone-aware review/execution time required")
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.tzinfo is not None and result.utcoffset() is not None, "timezone-aware time required")
        return result

    receipt = check.get("revalidation_ref") if check is not None else None
    if check is not None and receipt is None:
        return None
    runs = checker.manifest.get("unit_runs", {})
    require(isinstance(runs, dict), "unit_runs must be an object")
    if check is None:
        candidate = runs.get(unit_id, {})
        require(isinstance(candidate, dict), "unit run must be an object")
        receipt = candidate.get("revalidation_ref")
    if receipt is None:
        return None
    require(checker.evidence_snapshot(receipt, "implementation", "invalid_revalidation"), "unreadable or changed review receipt")
    review = checker.evidence_json(receipt)
    require(isinstance(review, dict), "review must be an object")
    require(type(review.get("version")) is int and review["version"] == 1 and review.get("event") == "unit_acceptance_revalidation", "version 1 review event required")
    require(review.get("outcome") == "retained" and isinstance(review.get("reviewer"), str) and review["reviewer"].strip(), "retained outcome and named reviewer required")
    require(review.get("behavior_changed") is False and review.get("claims_unchanged") is True and isinstance(review.get("impact_summary"), str) and review["impact_summary"].strip(), "affected behavior or missing overall impact review requires execution")
    reviewed = stamp(review.get("reviewed_at"))
    require(reviewed <= datetime.now().astimezone(), "future review time")
    review_bindings = {key: review.get(key) for key in ("unit_id", "original_plan_hash", "current_plan_hash", "reviewer", "reviewed_at")}
    require(checker.evidence_snapshot(receipt, "implementation", "invalid_revalidation", review_bindings), "review identity bindings differ")
    external = evidence_reference(receipt)
    if external is not None:
        provenance = external.get("provenance", {})
        require(provenance.get("executor") == review["reviewer"] and provenance.get("executed_at") == review["reviewed_at"], "review provenance must identify its reviewer and actual time")
    unit_id = unit_id or review.get("unit_id")
    require(review.get("unit_id") == unit_id, "wrong unit")
    if external is not None:
        require(external.get("provenance", {}).get("unit_id") == unit_id, "review provenance belongs to another unit")
    plan = checker.manifest["unit_plan"]
    run = runs.get(unit_id, {})
    require(isinstance(run, dict), "unit run must be an object")
    require(unit_id in plan["units"] and run.get("status") == "completed" and run.get("revalidation_ref") == receipt, "original completed unit and matching review reference required")
    baseline = checker.manifest.get("approved_baseline_id")
    current_hash = checker.artifacts["development-plan"]["content_hash"]
    require(review.get("current_plan_hash") == current_hash and review.get("approved_baseline_id") == baseline and run.get("approved_baseline_id") == baseline, "stale plan/baseline review")
    require(checker.file_hash(checker.path("docs/development-plan.md", no_links=True)) == current_hash, "current plan bytes differ")
    original_hash = review.get("original_plan_hash")
    require(isinstance(original_hash, str) and re.fullmatch(r"[0-9a-f]{64}", original_hash) and run.get("development_plan_hash") == original_hash, "original plan identity required")
    context_ref = review.get("original_context")
    require(checker.evidence_snapshot(context_ref, "implementation", "invalid_revalidation"), "original context is unreadable/changed")
    context = checker.evidence_json(context_ref)
    require(isinstance(context, dict), "original context must be an object")
    require(context.get("unit_plan") == plan, "changed work, ownership, acceptance, or dependency contract requires execution")
    definitions = context.get("definition_source_hashes")
    paths = {item["path"] for key, item in checker.artifacts.items() if key != "development-plan" and checker.path(item["path"]).is_file()}
    require(isinstance(definitions, dict) and set(definitions) == paths, "complete original definition-source inventory required")
    require(all(checker.file_hash(checker.path(path, no_links=True)) == value for path, value in definitions.items()), "changed acceptance-definition source requires execution")
    require(context.get("unit_run") == without_review(run), "original run was rebound or altered")
    require(reviewed >= stamp(run.get("completed_at")), "review precedes original completion")
    plan_source = context.get("plan_source")
    require(checker.evidence_snapshot(plan_source, "implementation", "invalid_revalidation"), "original plan source is unreadable/changed")
    data = checker.evidence_bytes(plan_source)
    require(checker.bytes_hash(data) == original_hash, "original plan bytes differ")
    heading = plan["definition_ref"]["heading"]
    checker.canonical_json_bytes(data, heading, plan)
    gate = checker.manifest.get("implementation_gate", {})
    require(isinstance(gate, dict), "current implementation_gate must be an object")
    require(checker.authorization_record(gate, current_hash, baseline), "fresh current implementation authorization required")
    require(reviewed >= stamp(gate.get("released_at")), "review precedes current authorization")
    original_gate = context.get("implementation_gate", {})
    require(isinstance(original_gate, dict), "original authorization must be an object")
    require(checker.authorization_record(original_gate, original_hash, baseline), "original implementation authorization required")
    require(stamp(original_gate.get("released_at")) <= stamp(run.get("started_at")), "original run precedes authorization")
    checks = {item["check_id"]: item for item in checker.manifest["verification"]["checks"]}
    required = set(plan["units"][unit_id]["required_check_ids"])
    retained = review.get("retained_check_ids")
    require(isinstance(retained, list) and len(retained) == len(set(retained)) and set(retained) == required, "review must cover every required check exactly once")
    originals = context.get("checks")
    require(isinstance(originals, dict) and set(originals) == required, "complete original check context required")
    claims = review.get("retained_claims")
    require(isinstance(claims, dict) and set(claims) == required, "retained claim map required")
    require(review.get("required_new_check_ids") == [], "required new checks cannot be replaced by retained acceptance")
    old_hashes = {}
    for key in required:
        current, original = checks[key], originals[key]
        require(isinstance(original, dict), key + ": original check must be an object")
        require(current.get("revalidation_ref") == receipt and original == without_review(current), key + ": original check was rebound or altered")
        require(original.get("execution_status") == "passed" and original.get("definition_status") == "prepared" and original.get("evaluated_plan_hash") == original_hash, key + ": original passed execution required")
        require(stamp(run["started_at"]) <= stamp(original.get("executed_at")) <= stamp(run["completed_at"]), key + ": execution outside original unit")
        require(claims[key] == plan["acceptance"][key]["obligation_ids"], key + ": retained obligations differ")
        hashes, _ = checker.source_inventory(original, "evaluated_source_hashes")
        require(hashes, key + ": original source inventory missing")
        for path, value in hashes.items():
            require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "invalid original source hash")
            require(path not in old_hashes or old_hashes[path] == value, "original inventories disagree")
            old_hashes[path] = value
    if check is not None:
        require(check.get("check_id") in required and originals[check["check_id"]] == without_review(check), "check is outside retained unit")
    current_hashes = review.get("current_source_hashes")
    require(isinstance(current_hashes, dict) and set(current_hashes) == set(old_hashes), "complete identical source-path inventory required")
    changed = {}
    for path, value in current_hashes.items():
        require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "invalid current source hash")
        require(checker.file_hash(checker.path(path, no_links=True)) == value, "changed/missing current source: " + path)
        if value != old_hashes[path]:
            changed[path] = (old_hashes[path], value)
    impacts = review.get("changed_paths")
    require(isinstance(impacts, list) and all(isinstance(item, dict) for item in impacts), "changed-path impact list required")
    require(len(impacts) == len(changed) and {item.get("path") for item in impacts} == set(changed), "changed paths missing, duplicated, or invented")
    for item in impacts:
        before, after = changed[item["path"]]
        require((item.get("original_hash"), item.get("current_hash")) == (before, after), "impact source identities differ")
        require(item.get("behavior_changed") is False and item.get("claims_unchanged") is True and isinstance(item.get("rationale"), str) and item["rationale"].strip(), "affected behavior or missing impact review requires execution")
    return {"reviewed_at": reviewed, "current_source_hashes": current_hashes, "original_gate": original_gate, "receipt": receipt}
