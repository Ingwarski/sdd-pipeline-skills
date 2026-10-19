#!/usr/bin/env python3
"""Compare deterministic instruction-load budgets, including references and retry loads.

Not a live-model, generated-document, cached-token or billing benchmark.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "tests/fixtures/instruction-budget.json"
METHOD_VERSION = "sdd-static-instruction-loads-v1"
METHOD = ("Fresh instruction loads per invocation, including each shared/conditional "
          "reference and the scenario seed on every invocation, including every listed retry. "
          "No cache discount; UTF-8 text uses normalized newlines. Fixed scenario definitions are checksum-bound to the baseline.")
LIMITS = ("Static instruction budget only; no live agent execution, generated-document savings, "
          "automatic host/worker loads, cache pricing, tool-output or runtime retry claims. "
          "Checksums detect accidental baseline drift, not edits by an authorized policy maintainer.")
SHARED = "skills/to-sdd-pipeline/references/"
HEURISTIC_CONSUMERS = {"to-guardrails", "to-wireframes", "to-design-brief", "to-dod-evals", "to-qa-checklist", "to-development-plan", "to-sdd-pipeline"}
SECURITY_CONSUMERS = {"to-sdd-prd", "to-architecture", "to-dod-evals", "to-qa-checklist", "to-development-plan", "to-sdd-pipeline"}
TRACE_CONSUMERS = {"to-product-idea", "to-sdd-prd", "to-screen-map", "to-qa-checklist", "to-development-plan", "to-sdd-pipeline"}
LIFECYCLE_CONSUMERS = {"to-sdd-prd", "to-architecture", "to-dod-evals", "to-qa-checklist", "to-development-plan"}
HISTORY_CONSUMERS = {"to-development-plan", "to-qa-checklist", "to-dod-evals", "to-sdd-pipeline"}


def read_version(relative, revision=None):
    """Read current files only; baseline comparison never requires Git history."""
    if revision is not None:
        raise ValueError("Historical Git reads are unsupported; use a numerical baseline snapshot")
    path = ROOT / relative
    return path.read_text(encoding="utf-8") if path.is_file() else None


def reads_history(skill, scenario, entry):
    """Current unit-work owners load completion preservation on every fixed workflow."""
    return skill in HISTORY_CONSUMERS and "completion-preservation.md" in entry


def resource_loads(skill, scenario, revision=None):
    paths = ["skills/" + skill + "/SKILL.md", SHARED + "common-contract.md"]
    if skill in TRACE_CONSUMERS:
        paths.append(SHARED + "traceability-contract.md")
    if skill in LIFECYCLE_CONSUMERS:
        paths.append(SHARED + "lifecycle-contract.md")
    if skill in ("to-product-idea", "to-sdd-pipeline", "to-screen-map"):
        paths.append(SHARED + "scope-and-execution.md")
    if skill in ("to-sdd-prd", "to-design-brief", "to-qa-checklist"):
        paths.append(SHARED + "accessibility-policy.md")
    entry = read_version("skills/" + skill + "/SKILL.md", revision) or ""
    if skill == "to-design-brief" and "references/freeze-contract.md" in entry:
        paths.append(SHARED + "freeze-contract.md")
    if skill in SECURITY_CONSUMERS:
        paths.append(SHARED + "security-contract.md")
    if skill == "to-sdd-prd":
        paths.append("skills/to-sdd-prd/references/security-authoring.md")
    if skill in HEURISTIC_CONSUMERS:
        paths += [SHARED + "heuristic-usability-review.md", SHARED + "verification-contract.md"]
    if skill == "to-sdd-pipeline":
        paths += [SHARED + "manifest-contract.md", SHARED + "prototype-contract.md", SHARED + "freeze-contract.md", SHARED + "pipeline-contract.json",
                  SHARED + "project-instructions.md", SHARED + "host-instruction-loading.md",
                  "skills/to-sdd-pipeline/assets/project-AGENTS.md"]
        if scenario["intake"]:
            paths.append(SHARED + "intake-adapter.md")
        if scenario["claude_design"]:
            paths.append(SHARED + "claude-design-handoff.md")
    if skill in ("to-development-plan", "to-sdd-pipeline") and scenario["prototype_reuse"]:
        paths.append("skills/to-development-plan/references/prototype-promotion.md")
    if skill in ("to-development-plan", "to-qa-checklist", "to-sdd-pipeline"):
        paths.append(SHARED + "unit-execution-contract.md")
    if scenario.get("approved_decision_correction") and skill in ("to-development-plan", "to-sdd-pipeline"):
        paths.append(SHARED + "authorization-corrections.md")
    if reads_history(skill, scenario, entry):
        paths.append(SHARED + "completion-preservation.md")
    if skill in scenario.get("evidence_storage_consumers", []):
        paths.append(SHARED + "evidence-storage-contract.md")
    # A missing required resource is a failure, never an instruction saving.
    resources = []
    for path in paths:
        text = read_version(path, revision)
        if text is None:
            raise ValueError("required instruction resource missing: " + path)
        resources.append((path, text))
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate instruction resource for " + skill)
    return resources


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def scenarios_from_disk():
    return json.loads((ROOT / "tests/fixtures/token-scenarios.json").read_text(encoding="utf-8"))


def measure_current(encoding):
    """Measure current text and retain numerical provenance, never source-text copies."""
    scenarios = scenarios_from_disk()
    resources = {}
    def record(relative, text):
        tokens = len(encoding.encode(text, disallowed_special=()))
        resources[relative] = {"tokens": tokens, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        return tokens
    entrypoints = sorted(path.relative_to(ROOT).as_posix() for path in ROOT.glob("skills/*/SKILL.md"))
    if not entrypoints:
        raise ValueError("no current skill entrypoints found")
    totals = {"entrypoints": sum(record(path, read_version(path)) for path in entrypoints),
              "readme": record("README.md", read_version("README.md"))}
    scenario_loads = {}
    for name, scenario in scenarios.items():
        seed_tokens = len(encoding.encode(scenario["seed"], disallowed_special=()))
        loads = []
        for skill in scenario["invocations"]:
            texts = resource_loads(skill, scenario)
            tokens = seed_tokens + sum(record(path, text) for path, text in texts)
            loads.append({"skill": skill, "tokens": tokens, "resources": [path for path, _ in texts]})
        totals[name] = sum(load["tokens"] for load in loads)
        scenario_loads[name] = {"seed_tokens": seed_tokens, "retries_included": scenario["retries"],
                                "invocations": len(loads), "loads": loads}
    return {"schema_version": 1, "method_version": METHOD_VERSION, "method": METHOD, "limits": LIMITS,
            "encoding": encoding.name, "tokenizer": {"package": "tiktoken", "version": version("tiktoken")},
            "scenarios_sha256": canonical_hash(scenarios), "entrypoint_paths": entrypoints,
            "totals": totals, "scenario_loads": scenario_loads, "resources": resources}


def make_snapshot(encoding):
    snapshot = measure_current(encoding)
    snapshot["provenance"] = {
        "source": "Current consolidated skillset; numerical metadata only, no historical source copies",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "measurement_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return snapshot


def validate_snapshot(snapshot, scenarios, encoding):
    """Reject changed scenarios/methods and internally inconsistent numerical baselines."""
    if snapshot.get("schema_version") != 1 or snapshot.get("method_version") != METHOD_VERSION:
        raise ValueError("unsupported instruction baseline schema or measurement method")
    if snapshot.get("method") != METHOD:
        raise ValueError("instruction baseline methodology differs")
    if snapshot.get("encoding") != encoding.name or snapshot.get("tokenizer") != {
            "package": "tiktoken", "version": version("tiktoken")}:
        raise ValueError("instruction baseline tokenizer differs; review a new measurement")
    if snapshot.get("scenarios_sha256") != canonical_hash(scenarios):
        raise ValueError("scenario definitions changed; review seeds, invocation order, conditions and retries")
    expected = {"entrypoints", "readme", *scenarios}
    if set(snapshot["totals"]) != expected or set(snapshot["scenario_loads"]) != set(scenarios):
        raise ValueError("instruction baseline metric coverage differs")
    resources = snapshot["resources"]
    for path, value in resources.items():
        if (not isinstance(value["tokens"], int) or isinstance(value["tokens"], bool) or value["tokens"] < 0
                or len(value["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in value["sha256"])):
            raise ValueError("invalid baseline resource: " + path)
    paths = snapshot["entrypoint_paths"]
    if len(paths) != len(set(paths)) or not paths:
        raise ValueError("invalid baseline entrypoint paths")
    if snapshot["totals"]["entrypoints"] != sum(resources[path]["tokens"] for path in paths):
        raise ValueError("baseline entrypoint total is inconsistent")
    if snapshot["totals"]["readme"] != resources["README.md"]["tokens"]:
        raise ValueError("baseline README total is inconsistent")
    for name, scenario in scenarios.items():
        value = snapshot["scenario_loads"][name]
        loads = value["loads"]
        seed_tokens = len(encoding.encode(scenario["seed"], disallowed_special=()))
        if (value["seed_tokens"] != seed_tokens or value["retries_included"] != scenario["retries"]
                or value["invocations"] != len(scenario["invocations"])
                or [load["skill"] for load in loads] != scenario["invocations"]):
            raise ValueError("baseline invocation/seed/retry accounting differs: " + name)
        for load in loads:
            paths = load["resources"]
            if len(paths) != len(set(paths)) or not paths:
                raise ValueError("invalid baseline load resources: " + name)
            if load["tokens"] != seed_tokens + sum(resources[path]["tokens"] for path in paths):
                raise ValueError("baseline resource total is inconsistent: " + name)
        if snapshot["totals"][name] != sum(load["tokens"] for load in loads):
            raise ValueError("baseline scenario total is inconsistent: " + name)


def load_baseline(reference, policy_dir, encoding):
    path = policy_dir / reference["path"]
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if canonical_hash(snapshot) != reference["sha256"]:
        raise ValueError("instruction baseline checksum mismatch: " + str(path))
    validate_snapshot(snapshot, scenarios_from_disk(), encoding)
    return snapshot


def build_report(baseline, current):
    def comparison(old, new):
        return {"before": old, "after": new, "growth_tokens": new - old,
                "reduction_percent": round(100 * (old - new) / old, 2) if old else None}
    report = {"baseline": baseline["provenance"], "encoding": current["encoding"],
              "method": METHOD, "limits": LIMITS, "entrypoints": {}, "readme": {}, "scenarios": {}}
    for name, total in current["totals"].items():
        values = comparison(baseline["totals"][name], total)
        if name in ("entrypoints", "readme"):
            report[name] = values
        else:
            loads = current["scenario_loads"][name]
            report["scenarios"][name] = {**values, "invocations": loads["invocations"],
                "retries_included": loads["retries_included"],
                "loads_before": baseline["scenario_loads"][name]["loads"], "loads_after": loads["loads"]}
    return report


def budget_errors(report, recent, policy):
    measured = {"entrypoints": report["entrypoints"], "readme": report["readme"], **report["scenarios"]}
    errors = []
    if set(policy["absolute"]) != set(measured) or set(policy["approved_growth_tokens"]) != set(measured):
        errors.append("budget metric coverage differs from measured workflows")
    for name, values in measured.items():
        if name not in policy["absolute"] or name not in policy["approved_growth_tokens"]:
            errors.append(name + ": missing reviewed budget")
            continue
        ceiling, growth = policy["absolute"][name], policy["approved_growth_tokens"][name]
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (ceiling, growth)):
            errors.append(name + ": budget values must be nonnegative integers")
            continue
        if values["after"] > ceiling:
            errors.append(name + ": absolute budget exceeded")
        if values["after"] - recent["totals"][name] > growth:
            errors.append(name + ": recent growth exceeds reviewed allowance")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoding", default="o200k_base")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--check", action="store_true", help="enforce reviewed recent-snapshot growth and absolute ceilings")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--record-baseline", type=Path, help="write a new candidate numerical snapshot; never changes approved policy")
    args = parser.parse_args()
    if args.record_baseline and args.check:
        parser.error("baseline recording and budget enforcement are separate operations")
    try:
        import tiktoken
    except ImportError:
        parser.error("Install test-only dependencies with: python -m pip install -r tests/requirements.txt")
    try:
        encoding = tiktoken.get_encoding(args.encoding)
        if args.record_baseline:
            snapshot = make_snapshot(encoding)
            validate_snapshot(snapshot, scenarios_from_disk(), encoding)
            # Exclusive creation prevents silently replacing an existing reviewed baseline.
            with args.record_baseline.open("x", encoding="utf-8") as output:
                output.write(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"path": str(args.record_baseline), "sha256": canonical_hash(snapshot),
                              "totals": snapshot["totals"]}, indent=2))
            return 0
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        if policy.get("schema_version") != 1:
            raise ValueError("unsupported instruction budget policy schema")
        baseline = load_baseline(policy["baseline"], args.policy.parent, encoding)
        recent = load_baseline(policy["recent_baseline"], args.policy.parent, encoding)
        report = build_report(baseline, measure_current(encoding))
        errors = budget_errors(report, recent, policy) if args.check else []
        report["budget_review"] = {"baseline": policy["baseline"], "recent_baseline": policy["recent_baseline"],
            "reason": policy["reason"], "errors": errors, "recent_totals": recent["totals"]}
        if args.summary:
            for scenario in report["scenarios"].values():
                scenario.pop("loads_before")
                scenario.pop("loads_after")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
