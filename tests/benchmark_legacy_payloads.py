#!/usr/bin/env python3
"""Matched synthetic legacy-integrity gate benchmark, never product QA.

This uses the same history-resolution fixture in every-gate and audit-only modes.
The fixture runs the real product-idea gate with a fixed set of current artifacts.
All generated files are disposable; no application execution is measured.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

from test_history_integrity_scope import HistoryIntegrityGateTests
from test_sdd_check import SCRIPT, sdd
import verification_metrics as metrics


def benchmark(files=500, payload_bytes=4096, repeats=3):
    if not 1 <= files <= 2000 or not 1 <= payload_bytes <= 65536 or files * payload_bytes > 32 * 1024 * 1024:
        raise ValueError("fixture must contain 1-2000 files of 1-65536 bytes, at most 32 MiB total")
    if not 1 <= repeats <= 5:
        raise ValueError("repeat count must be from 1 through 5")
    fixture = HistoryIntegrityGateTests("runTest")
    fixture.setUp()
    try:
        fixture.record["files"] = {}
        content = b"synthetic retained observation\n"
        payload = (content * ((payload_bytes + len(content) - 1) // len(content)))[:payload_bytes]
        first = None
        for number in range(files):
            logical = "assets/observation-" + str(number).zfill(4) + ".bin"
            relative = fixture.record["snapshot_root"] + "/" + logical
            path = fixture.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            first = first or path
            fixture.record["files"][logical] = {"path": relative, "content_hash": sdd.digest(payload)}
        fixture.reference = fixture.history.write_new(
            fixture.root, "forge/unit-history/old/benchmark-record.json", fixture.history.encoded(fixture.record))
        fixture.project.manifest["legacy_history"] = [fixture.reference]
        samples = {"every_gate": [], "audit_only": []}
        # Alternate order to reduce a systematic filesystem-warmup advantage.
        for number in range(repeats):
            for mode in (("every_gate", "audit_only") if number % 2 == 0 else ("audit_only", "every_gate")):
                fixture.project.manifest["history_integrity"]["legacy_payloads"] = mode
                with metrics.collect() as observation:
                    started = perf_counter()
                    report = fixture.checker().run("product-idea", require_current=True)
                    elapsed = perf_counter() - started
                if report["result"] != "passed" or report.get("issues"):
                    raise RuntimeError("synthetic history-resolution fixture did not validate")
                scope = report["history_integrity"]
                expected = files if mode == "audit_only" else 0
                if scope["deferred_snapshot_files"] != expected:
                    raise RuntimeError("history policy integration did not report the expected scope")
                samples[mode].append({"elapsed_seconds": elapsed,
                    "deferred_snapshot_files": scope["deferred_snapshot_files"],
                    "report_bytes": len(json.dumps(report, separators=(",", ":")).encode()),
                    "performance": observation.snapshot()})
        # Deferral must not make an explicit audit trust damaged original bytes.
        first.write_bytes(b"changed")
        fixture.project.manifest["history_integrity"]["legacy_payloads"] = "audit_only"
        audited = fixture.checker().run("product-idea", audit=True, require_current=True)
        if audited["result"] != "blocked" or not any(
                issue["code"] == "unit_history" and "historical snapshot changed" in issue["detail"]
                for issue in audited.get("issues", [])):
            raise RuntimeError("full audit failed to reject damaged legacy payload")
        return {"version": 1, "synthetic_fixture": True,
            "scope": "Synthetic product-idea gates with retained unusable legacy payloads; no product tests or current attempt/completion savings are measured.",
            "qualification": "Matched same-file samples alternate policy order. Filesystem caches may be warm; this is not a live-project or implementation-start benchmark.",
            "python_version": sys.version.split()[0], "payload_files": files,
            "payload_logical_bytes": files * payload_bytes,
            "metadata_bytes": (fixture.root / fixture.reference["path"]).stat().st_size,
            "samples": samples,
            "median_seconds": {key: statistics.median(v["elapsed_seconds"] for v in values)
                               for key, values in samples.items()},
            "audit_rejected_corrupted_payload": True,
            "source_sha256": {name: hashlib.sha256((SCRIPT.parent / name).read_bytes()).hexdigest()
                              for name in ("sdd_check.py", "sdd_history.py", "history_integrity.py", "verification_metrics.py")}}
    finally:
        fixture.doCleanups()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=500)
    parser.add_argument("--payload-bytes", type=int, default=4096)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12+ is required")
    try:
        result = benchmark(args.files, args.payload_bytes, args.repeats)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
