#!/usr/bin/env python3
"""Compare deterministic instruction-load budgets, including references and retry loads.

Not a live-model, generated-document, cached-token or billing benchmark.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "e5d6ab9df4502cf6babc76e273602ecbd66881f0"
SHARED = "skills/to-sdd-pipeline/references/"
HEURISTIC_CONSUMERS = {"to-guardrails", "to-wireframes", "to-design-brief", "to-dod-evals", "to-qa-checklist", "to-development-plan", "to-sdd-pipeline"}
SECURITY_CONSUMERS = {"to-sdd-prd", "to-architecture", "to-dod-evals", "to-qa-checklist", "to-development-plan", "to-sdd-pipeline"}
TRACE_CONSUMERS = {"to-product-idea", "to-sdd-prd", "to-screen-map", "to-qa-checklist", "to-development-plan", "to-sdd-pipeline"}
LIFECYCLE_CONSUMERS = {"to-sdd-prd", "to-architecture", "to-dod-evals", "to-qa-checklist", "to-development-plan"}


def read_version(relative, revision):
    if revision is None:
        path = ROOT / relative
        return path.read_text(encoding="utf-8") if path.is_file() else None
    result = subprocess.run(["git", "show", revision + ":" + relative], cwd=ROOT, capture_output=True)
    return result.stdout.decode("utf-8") if result.returncode == 0 else None


def resource_loads(skill, scenario, revision):
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
        paths += [SHARED + "manifest-contract.md", SHARED + "prototype-contract.md", SHARED + "freeze-contract.md", SHARED + "pipeline-contract.json"]
        if scenario["intake"]:
            paths.append(SHARED + "intake-adapter.md")
        if scenario["claude_design"]:
            paths.append(SHARED + "claude-design-handoff.md")
    if skill in ("to-development-plan", "to-sdd-pipeline") and scenario["prototype_reuse"]:
        paths.append("skills/to-development-plan/references/prototype-promotion.md")
    # Old entrypoints inline several of these contracts. Count only existing files,
    # not fictional shared copies. Every invocation reloads its complete read set.
    return [(path, text) for path in paths if (text := read_version(path, revision)) is not None]


def build_report(base, encoding):
    scenarios = json.loads((ROOT / "tests/fixtures/token-scenarios.json").read_text(encoding="utf-8"))
    count = lambda text: len(encoding.encode(text, disallowed_special=()))
    report = {"base_commit": base, "encoding": encoding.name,
              "method": "Fresh instruction loads per invocation, including shared/conditional references and every listed retry. Same seeds and sequences for both versions.",
              "limits": "Static instruction budget only; no live agent execution, generated-document savings, cache pricing, tool-output or runtime retry claims.",
              "entrypoints": {}, "readme": {}, "scenarios": {}}
    before = after = 0
    for path in sorted(ROOT.glob("skills/*/SKILL.md")):
        relative = path.relative_to(ROOT).as_posix()
        old = read_version(relative, base)
        if old is None:
            raise ValueError("baseline skill missing: " + relative)
        before += count(old)
        after += count(path.read_text(encoding="utf-8"))
    def comparison(old, new):
        return {"before": old, "after": new, "reduction_percent": round(100 * (old - new) / old, 2)}
    report["entrypoints"] = comparison(before, after)
    report["readme"] = comparison(count(read_version("README.md", base)), count(read_version("README.md", None)))
    for name, scenario in scenarios.items():
        totals, loads = [], []
        for revision in (base, None):
            total = 0
            sequence = []
            for skill in scenario["invocations"]:
                resources = resource_loads(skill, scenario, revision)
                tokens = count(scenario["seed"]) + sum(count(text) for _, text in resources)
                total += tokens
                sequence.append({"skill": skill, "tokens": tokens, "resources": [path for path, _ in resources]})
            totals.append(total)
            loads.append(sequence)
        report["scenarios"][name] = {**comparison(*totals), "invocations": len(scenario["invocations"]),
                                    "retries_included": scenario["retries"], "loads_before": loads[0], "loads_after": loads[1]}
    return report


def budget_errors(report, recent, policy):
    measured = {"entrypoints": report["entrypoints"], "readme": report["readme"], **report["scenarios"]}
    previous = {"entrypoints": recent["entrypoints"], "readme": recent["readme"], **recent["scenarios"]}
    errors = []
    for name, values in measured.items():
        if name not in policy["absolute"] or name not in policy["approved_growth_tokens"]:
            errors.append(name + ": missing reviewed budget")
            continue
        if values["after"] > policy["absolute"][name]:
            errors.append(name + ": absolute budget exceeded")
        if values["after"] - previous[name]["before"] > policy["approved_growth_tokens"][name]:
            errors.append(name + ": recent growth exceeds reviewed allowance")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--encoding", default="o200k_base")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--check", action="store_true", help="enforce reviewed recent-version growth and absolute ceilings")
    parser.add_argument("--policy", type=Path, default=ROOT / "tests/fixtures/instruction-budget.json")
    args = parser.parse_args()
    try:
        import tiktoken
    except ImportError:
        parser.error("Install test-only dependencies with: python -m pip install -r tests/requirements.txt")
    try:
        subprocess.run(["git", "rev-parse", "--verify", args.base + "^{commit}"], cwd=ROOT, check=True, capture_output=True)
        report = build_report(args.base, tiktoken.get_encoding(args.encoding))
        errors = []
        if args.check:
            policy = json.loads(args.policy.read_text(encoding="utf-8"))
            recent = build_report(policy["recent_base"], tiktoken.get_encoding(args.encoding))
            errors = budget_errors(report, recent, policy)
            report["budget_review"] = {"recent_base": policy["recent_base"], "reason": policy["reason"], "errors": errors,
                                       "recent": {"entrypoints": recent["entrypoints"], "readme": recent["readme"],
                                                  **{key: {k: v for k, v in value.items() if not k.startswith("loads_")}
                                                     for key, value in recent["scenarios"].items()}}}
        if args.summary:
            for scenario in report["scenarios"].values():
                scenario.pop("loads_before")
                scenario.pop("loads_after")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
