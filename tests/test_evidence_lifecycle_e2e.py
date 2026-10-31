"""Isolated lifecycle exercises: real toy checks, synthetic SDD owner receipts.

The fixture's approvals and generic acceptance declarations are deliberately
synthetic. The three tiny application checks really execute, and their counter
proves that adoption, storage cleanup, recovery and gates do not execute them.
No user project, personal evidence configuration or live provider is accessed.
"""
import copy
import json
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import test_unit_history as history_fixture
import test_evidence_manager as storage_fixture
from test_sdd_check import sdd
from evidence.manager import Manager
from evidence.resolver import EvidenceResolver


TOY_RUNNER = '''import json
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parents[1]
unit, counter_path = sys.argv[1:]
counter = Path(counter_path)
with counter.open("a", encoding="utf-8") as stream:
    stream.write(unit + "\\n")
path = {"U-1": "alpha", "U-2": "beta", "U-3": "integration"}[unit]
component = runpy.run_path(str(root / "src" / (path + ".txt")))["component"]
expected = {"U-1": 10, "U-2": 8, "U-3": 13}[unit]
assert component(5) == expected
try:
    component(-1)
except ValueError:
    rejected_negative = True
else:
    raise AssertionError("negative input was accepted")
print(json.dumps({"unit": unit, "value": expected,
                  "negative_input_rejected": rejected_negative,
                  "status": "passed", "synthetic_application": True}))
'''


class LifecycleProject:
    """Native immutable history plus separately registered real source bytes."""

    def __init__(self, owner, *, complete_all=False):
        self.owner = owner
        self.base = history_fixture.UnitHistoryTests("runTest")
        self.base.setUp()
        owner.addCleanup(self.base.doCleanups)
        self.p, self.m = self.base.p, self.base.m
        self.h = self.base.history()
        self.storage = storage_fixture.EvidenceManagerTests("runTest")
        self.storage.setUp()
        owner.addCleanup(self.storage.doCleanups)
        self.manager = Manager(self.storage.transport, self.storage.home,
                               self.storage.policy, project=self.p.root.resolve())
        self.counter = self.storage.base / "application-invocations.txt"
        self.cache = self.manager.cache
        self.p.write("forge/evidence-policy.json", json.dumps(self.storage.policy, sort_keys=True) + "\n")
        self.p.write("tests/verify.py", TOY_RUNNER)
        self.p.write("src/alpha.txt", "def component(value):\n    if value < 0: raise ValueError('negative')\n    return value * 2\n")
        self.p.write("src/beta.txt", "def component(value):\n    if value < 0: raise ValueError('negative')\n    return value + 3\n")
        self.p.write("src/integration.txt", "from pathlib import Path\nimport runpy\n"
            "root = Path(__file__).resolve().parent\n"
            "alpha = runpy.run_path(str(root / 'alpha.txt'))['component']\n"
            "beta = runpy.run_path(str(root / 'beta.txt'))['component']\n"
            "def component(value):\n    return beta(alpha(value))\n")
        self.m.update(checker_contract_version=3, unit_contract_version=3)
        self.m["unit_plan"]["units"]["U-1"]["implementation_paths"].append("tests/verify.py")
        self.m["unit_plan"]["units"]["U-2"]["construction_dependencies"] = ["U-1"]
        for check in self.m["verification"]["checks"]:
            unit = self.m["unit_plan"]["acceptance"][check["check_id"]]["owner_unit"]
            paths = list(self.m["unit_plan"]["units"][unit]["implementation_paths"])
            if "tests/verify.py" not in paths:
                paths.append("tests/verify.py")
            if unit == "U-3":
                paths.extend(["src/alpha.txt", "src/beta.txt"])
            check["acceptance"].update(required_source_paths=paths,
                reuse_policy="deterministic_isolated", dependency_review={
                    "complete": True, "reviewer": "synthetic dependency owner",
                    "rationale": "The toy runner and every executed component are listed."})
        self.base.fixture.sync()
        self.references = []
        self.optional_members = []
        self.diagnostic = "forge/diagnostics/optional-trace.txt"
        self.p.write(self.diagnostic, "Optional synthetic troubleshooting trace.\n" * 1000)
        self.complete("U-1", diagnostic=True)
        if complete_all:
            self.complete("U-2")
            self.complete("U-3")
        else:
            pending_context, _ = self.capture_context("U-2")
            self.references.append(pending_context)
        self.initial_runs = copy.deepcopy(self.m["unit_runs"])
        self.initial_checks = copy.deepcopy(self.m["verification"]["checks"])
        self.initial_authority = copy.deepcopy(self.m["implementation_gate"])
        self.envelopes = {ref["path"]: (self.p.root / ref["path"]).read_bytes()
                          for ref in self.references}
        self.archive_sources()
        self.prepare_views()
        self.p.save()

    def invocations(self):
        return self.counter.read_text(encoding="utf-8").splitlines() if self.counter.exists() else []

    def capture_context(self, unit):
        runtime = self.h.observe_runtime(self.p.root, {"runtime": [sys.executable, "--version"]})
        inventory = self.base.inventory(unit=unit, environment=self.base.read(runtime)["environment"])
        inventory["runtime_observation_ref"] = runtime
        checker = sdd.Checker(self.p.root, self.m)
        for check in self.m["verification"]["checks"]:
            if check["check_id"] in self.m["unit_plan"]["units"][unit]["required_check_ids"]:
                inventory["execution_inputs"].update({path: {"mode": "file"}
                    for path in self.h.check_inputs.required_paths(checker, check)})
        # The tiny fixture deliberately retains a conservative shared input set.
        inventory["execution_inputs"].update({path: {"mode": "file"}
            for definition in self.m["unit_plan"]["units"].values()
            for path in definition["implementation_paths"]})
        context = self.h.capture_context(self.p.root, self.m, unit, inventory)
        self.m.setdefault("execution_contexts", {})[unit] = context
        return context, inventory

    def complete(self, unit, *, diagnostic=False):
        context, inventory = self.capture_context(unit)
        run_id = "synthetic-lifecycle-" + unit
        self.m.setdefault("unit_runs", {})[unit] = {
            "status": "running", "started_at": self.base.now(), "run_id": run_id,
            "development_plan_hash": self.p.hash("docs/development-plan.md"),
            "approved_baseline_id": "B-1", "findings": []}
        result = subprocess.run([sys.executable, str(self.p.root / "tests/verify.py"), unit,
                                 str(self.counter)], capture_output=True, text=True, check=True)
        observation = json.loads(result.stdout)
        self.owner.assertEqual("passed", observation["status"])
        self.base.fixture.evidence(unit, 4)
        runtime = self.h.observe_runtime(self.p.root, {"runtime": [sys.executable, "--version"]})
        for check in self.m["verification"]["checks"]:
            if check["check_id"] not in self.m["unit_plan"]["units"][unit]["required_check_ids"]:
                continue
            evidence = self.p.evidence("forge/evidence/" + check["check_id"] + ".json", observation)
            for entry in check["evidence"]:
                entry.update(evidence)
            paths = self.h.check_inputs.required_paths(sdd.Checker(self.p.root, self.m), check)
            check.update(executed_at=self.base.now(), run_id=run_id, runtime_observation_ref=runtime,
                evaluated_source_hashes={path: self.p.hash(path) for path in paths},
                evaluated_execution_inputs=self.h.observe_execution_inputs(
                    self.p.root, self.m, unit, inventory, check_id=check["check_id"]))
        self.m["unit_runs"][unit].update(status="completed", completed_at=self.base.now())
        freeze = self.h.freeze_files

        def with_extra_snapshot(project, manifest, directory, *args, **kwargs):
            files = freeze(project, manifest, directory, *args, **kwargs)
            files[self.diagnostic] = self.h.write_snapshot(project,
                directory + "/files/" + self.diagnostic, (self.p.root / self.diagnostic).read_bytes())
            return files

        with mock.patch.object(self.h, "freeze_files", side_effect=with_extra_snapshot if diagnostic else freeze):
            completion = self.h.capture_completion(self.p.root, self.m, unit, context, run_id)
        self.m["unit_runs"][unit] = {"status": "completed", "completion_ref": completion}
        self.references.extend([context, completion])
        if diagnostic:
            record = self.h.read_ref(self.p.root, completion)
            self.optional_members.append({"record_ref": copy.deepcopy(completion),
                "logical_path": self.diagnostic,
                "content_hash": record["files"][self.diagnostic]["content_hash"],
                "rationale": "Extra troubleshooting capture; no test, input or approval consumes it."})
        self.p.save()

    def archive_sources(self):
        specs, locations, self.records = [], [], []
        for reference in self.references:
            record = self.h.read_ref(self.p.root, reference)
            sources = []
            for logical, frozen in record["files"].items():
                locations.append((sources, frozen, logical))
                specs.append({"path": str((self.p.root / frozen["path"]).resolve()),
                    "original_path": frozen["path"], "sealed_at": storage_fixture.SEALED,
                    "kind": "source_snapshot", "schema": "evidence-bytes-v1",
                    "provenance": {"run_id": "synthetic-lifecycle-source-archive", "unit_id": "U-1"},
                    "bindings": {"original_snapshot": copy.deepcopy(frozen)}})
            self.records.append({"record_ref": copy.deepcopy(reference),
                                 "snapshot_root": record["snapshot_root"], "sources": sources})
        self.refs = self.manager.archive({"version": 1, "files": specs})
        self.manager.prepare(self.refs)
        self.optional_ids = []
        for (sources, frozen, logical), ref in zip(locations, self.refs):
            sources.append({**frozen, "evidence_ref": ref})
            if logical == self.diagnostic:
                self.optional_ids.append(ref["artifact_id"])
        self.index = self.h.create_source_archive_index(self.p.root, self.records, evidence_cache=self.cache)
        self.m["source_archive_index_ref"] = self.index

    def prepare_views(self):
        return self.h.prepare_source_views(self.p.root, self.index, evidence_cache=self.cache,
            max_bytes=32 * 1024 * 1024, max_files=10000, manifest=self.m)

    def review(self):
        return {"reviewer": "synthetic lifecycle owner", "reviewed_at": self.base.now(),
                "rationale": "Isolated synthetic fixture; preserve all required proof and original chronology."}

    def adopt(self):
        from evidence.diagnostics import capture_review
        reference = capture_review(self.p.root, self.m, self.optional_members, self.review(),
                                   evidence_cache=self.cache)
        self.m["history_integrity"] = {"legacy_payloads": "every_gate", "optional_diagnostics_ref": reference}
        self.p.save()
        self.prepare_views()
        self.manager.adopt_lifecycle("synthetic-main", review=self.review(), automatic_cleanup=True)
        self.manager.classify_lifecycle(self.optional_ids, role="optional_diagnostic",
                                       review=self.review(), purpose_complete=True)

    def cold_restore(self):
        for record in self.records:
            for source in record["sources"]:
                (self.p.root / source["path"]).unlink(missing_ok=True)
        blobs = self.p.root / self.h.HISTORY / "blobs"
        if blobs.exists():
            shutil.rmtree(blobs)
        shutil.rmtree(self.cache)
        self.cache.mkdir()
        catalog = self.manager._catalog()
        self.manager.prepare([ref for ref in self.refs if ref["artifact_id"] in catalog["refs"]])
        self.prepare_views()

    def report(self, *, release=False, action=None, unit=None):
        return sdd.Checker(self.p.root, self.m, evidence_cache=self.cache).run(
            "release" if release else "implementation",
            unit_action=action, unit_id=unit)

    def assert_original_records(self):
        self.owner.assertEqual(self.initial_runs, self.m["unit_runs"])
        self.owner.assertEqual(self.initial_checks, self.m["verification"]["checks"])
        self.owner.assertEqual(self.initial_authority, self.m["implementation_gate"])
        self.owner.assertEqual(self.envelopes, {path: (self.p.root / path).read_bytes()
                                              for path in self.envelopes})


class EvidenceLifecycleEndToEndTests(unittest.TestCase):
    def test_completed_project_survives_cleanup_relocation_and_cold_release_without_reruns(self):
        f = LifecycleProject(self, complete_all=True)
        self.assertEqual(["U-1", "U-2", "U-3"], f.invocations())
        before = f.report(release=True)
        self.assertEqual("passed", before["result"], before)
        f.adopt()
        f.manager.checkpoint_lifecycle("synthetic-main", cleanup=True)
        self.assertFalse(set(f.optional_ids) & set(f.manager._catalog()["refs"]),
                         "The managed checkpoint must automatically retire unneeded diagnostics.")
        for pack in list(f.manager._catalog()["packs"]):
            f.manager.relocate_lifecycle_pack(pack, dry_run=False)
        f.manager.cleanup_lifecycle(dry_run=False)
        self.assertFalse(set(f.optional_ids) & set(f.manager._catalog()["refs"]))
        f.cold_restore()
        with mock.patch("subprocess.run", side_effect=AssertionError("recovery/gates must not execute application checks")):
            after = f.report(release=True)
        self.assertEqual("passed", after["result"], after)
        self.assertEqual(["U-1", "U-2", "U-3"], f.invocations())
        f.assert_original_records()
        # Losing the last prepared required report must still block. A retained
        # status label and intact optional-diagnostic review cannot replace it.
        required = next(ref for ref in f.refs if ref["artifact_id"] not in f.optional_ids
                        and ref["original_path"].endswith("/forge/evidence/QA-02.json"))
        EvidenceResolver(f.cache).resolve(required).unlink()
        for path in (f.cache / "source-views").rglob("QA-02.json"):
            path.unlink()
        try:
            invalid = f.report(release=True)
        except (ValueError, OSError):
            pass
        else:
            self.assertNotEqual("passed", invalid["result"], invalid)
        self.assertEqual(["U-1", "U-2", "U-3"], f.invocations())

    def test_completed_prerequisite_survives_cold_resume_without_repeating_its_check(self):
        f = LifecycleProject(self)
        before = f.report(action="start", unit="U-2")
        self.assertEqual("passed", before["result"], before)
        from evidence.diagnostics import capture_review
        completion = f.m["unit_runs"]["U-1"]["completion_ref"]
        original = f.h.read_ref(f.p.root, completion)
        required_input = {"record_ref": copy.deepcopy(completion), "logical_path": "src/alpha.txt",
            "content_hash": original["files"]["src/alpha.txt"]["content_hash"],
            "rationale": "Deliberately invalid synthetic request: this source is still required."}
        with self.assertRaisesRegex(ValueError, "withholding changes acceptance|active input/proof"):
            capture_review(f.p.root, f.m, [required_input], f.review(), evidence_cache=f.cache)
        f.adopt()
        f.manager.checkpoint_lifecycle("synthetic-main", cleanup=True)
        self.assertFalse(set(f.optional_ids) & set(f.manager._catalog()["refs"]),
                         "The managed checkpoint must automatically retire unneeded diagnostics.")
        f.cold_restore()
        with mock.patch("subprocess.run", side_effect=AssertionError("resume must not execute the completed application check")):
            resumed = f.report(action="start", unit="U-2")
        self.assertEqual("passed", resumed["result"], resumed)
        self.assertEqual(["U-1"], f.invocations())
        f.assert_original_records()

