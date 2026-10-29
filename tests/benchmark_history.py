#!/usr/bin/env python3
"""Bounded synthetic history benchmark; no product evidence or acceptance claim.

Run from this checkout with a supported Python. Setup creates disposable fixtures;
only gate timings enter samples. A profile is separate because profiling changes
elapsed time. Reports contain aggregate counts, never fixture paths or content.
"""
import argparse
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import statistics
import sys
from time import perf_counter

import test_attempt_history as fixture_module
from test_sdd_check import SCRIPT, sdd

sys.path.insert(0, str(SCRIPT.parent))
import verification_metrics as metrics


PROFILE_FUNCTIONS = frozenset({
    "validate_context", "validate_attempt", "validate_completion", "historical_checker",
    "validate_files", "prepare_inventory", "_parents", "_regular", "_open_regular",
    "hash_file", "read_json", "deepcopy", "_run_invocation",
})


def make_history(fixture, depth):
    fixture.start(failed=False)
    for number in range(depth):
        run_id = "synthetic-attempt-" + str(number + 1)
        reference = fixture.helper.capture_attempt(
            fixture.p.root, fixture.m, "U-1", fixture.context, run_id,
            "interrupted")
        fixture.m["unit_runs"]["U-1"]["attempt_ref"] = reference
        inventory = fixture.continuation_inventory()
        result = fixture.helper.capture_continuation(
            fixture.p.root, fixture.m, "U-1", reference,
            "synthetic-attempt-" + str(number + 2), inventory)
        fixture.m.clear()
        fixture.m.update(result["manifest"])
        fixture.context = result["context_ref"]
        fixture.m["unit_runs"]["U-1"].update(
            status="running", started_at=fixture.base.now(),
            development_plan_hash=fixture.p.hash("docs/development-plan.md"),
            approved_baseline_id="B-1")


def gate(fixture):
    with metrics.collect() as observation:
        started = perf_counter()
        report = sdd.Checker(fixture.p.root, fixture.m).run(
            "implementation", unit_action="start", unit_id="U-1", projections=False)
        elapsed = perf_counter() - started
    if report["result"] != "passed":
        # Diagnostic codes are sufficient; never persist fixture/project paths.
        raise RuntimeError("synthetic gate blocked: " + ", ".join(
            sorted({issue["code"] for issue in report.get("issues", [])})))
    return {"elapsed_seconds": elapsed, "result": report["result"],
            "performance": observation.snapshot()}


def benchmark(depths, repeats, profile=False):
    if not depths or any(type(depth) is not int or not 0 <= depth <= 6 for depth in depths):
        raise ValueError("history depths must be integers from 0 through 6")
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("repeat count must be from 1 through 5")
    results = []
    for depth in depths:
        fixture = fixture_module.AttemptHistoryTests("runTest")
        fixture.setUp()
        try:
            started = perf_counter()
            make_history(fixture, depth)
            setup_seconds = perf_counter() - started
            samples = [gate(fixture) for _ in range(repeats)]
            entry = {"prior_attempts": depth, "setup_seconds_excluded": setup_seconds,
                     "samples": samples,
                     "median_gate_seconds": statistics.median(s["elapsed_seconds"] for s in samples)}
            if profile:
                profiler = cProfile.Profile()
                profiler.enable()
                profiled = gate(fixture)
                profiler.disable()
                rows = []
                for (filename, _line, function), values in pstats.Stats(profiler).stats.items():
                    if function in PROFILE_FUNCTIONS:
                        primitive, calls, self_seconds, cumulative_seconds, _callers = values
                        rows.append({"module": Path(filename).name, "function": function,
                                     "calls": calls, "primitive_calls": primitive,
                                     "self_seconds": self_seconds,
                                     "cumulative_seconds": cumulative_seconds})
                entry["separate_profile"] = {"elapsed_seconds": profiled["elapsed_seconds"],
                    "qualification": "Profiling adds overhead; cumulative times overlap and must not be added.",
                    "functions": sorted(rows, key=lambda row: (row["module"], row["function"]))}
            results.append(entry)
        finally:
            fixture.doCleanups()
    return {"version": 1, "synthetic_fixture": True,
            "qualification": "Small synthetic start gates only; not a product benchmark or platform qualification. Each sample starts a fresh checker invocation; filesystem caches may be warm.",
            "python_version": sys.version.split()[0],
            "source_sha256": {name: hashlib.sha256((SCRIPT.parent / name).read_bytes()).hexdigest()
                              for name in ("sdd_check.py", "sdd_history.py", "verification_metrics.py")},
            "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depths", nargs="+", type=int, default=[0, 1, 3])
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12+ is required")
    try:
        result = benchmark(args.depths, args.repeats, args.profile)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
