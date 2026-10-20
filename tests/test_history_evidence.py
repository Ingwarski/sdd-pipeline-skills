"""History plus prepared external evidence; isolated synthetic records only."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import test_evidence_checker as external_fixture
import test_unit_history as history_fixture
from test_sdd_check import SCRIPT, sdd


class HistoryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.history = history_fixture.UnitHistoryTests(methodName="runTest")
        self.history.setUp()
        self.addCleanup(self.history.doCleanups)
        self.p, self.m = self.history.p, self.history.m
        self.external = external_fixture.EvidenceCheckerTests(methodName="runTest")
        self.external.setUp()
        self.addCleanup(self.external.doCleanups)
        self.external.p, self.external.m = self.p, self.m
        self.p.write("forge/evidence-policy.json", json.dumps(self.external.policy))
        self.m["evidence_accounting"] = {"version": 1, "project_id": self.external.policy["project_id"],
            "policy_sha256": self.p.hash("forge/evidence-policy.json"), "runs": {}}
        self.cache = self.external.cache
        self.helper = self.history.history()
        self.m.update(checker_contract_version=2, unit_contract_version=2)
        gate = self.m["implementation_gate"]
        self.prompt = self.external.replace(gate["prompt_receipt"], "original-prompt", "receipt",
            {key: gate[key] for key in ("prompt_id", "development_plan_hash", "approved_baseline_id")})
        gate["prompt_receipt"] = self.prompt

    def checker(self):
        return sdd.Checker(self.p.root, self.m, evidence_cache=self.cache)

    def capture(self):
        inventory = self.history.inventory()
        context = self.helper.capture_context(self.p.root, self.m, "U-1", inventory, evidence_cache=self.cache)
        self.m.setdefault("execution_contexts", {})["U-1"] = context
        self.history.fixture.begin("U-1", 3)
        self.m["unit_runs"]["U-1"]["started_at"] = self.history.now()
        self.history.fixture.evidence("U-1", 4)
        self.history.stamp_evidence(self.helper, "U-1", inventory)
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        hashes = check.pop("evaluated_source_hashes")
        # Include a source visible only through the compact test-time inventory.
        self.p.write("tests/fixture-support.txt", "Stable synthetic test support.\n")
        hashes["tests/fixture-support.txt"] = self.p.hash("tests/fixture-support.txt")
        source_ref = self.external.prepare({"version": 1, "source_hashes": hashes}, "test-inventory", "source_inventory", "source-inventory-v1")
        check["source_inventory_ref"] = source_ref
        captures = []
        legacy = copy.deepcopy(check["evidence"])
        for index, record in enumerate(legacy):
            data = (self.p.root / record["path"]).read_bytes()
            ref = self.external.prepare(data, "capture-" + str(index), record["kind"], "sdd-result-v1", self.checker().check_bindings(check))
            ref.update(original_path=record["path"], dependencies=[source_ref])
            self.external.receipt(ref)
            captures.append(ref)
        for path in {record["path"] for record in legacy}:
            (self.p.root / path).unlink()
        check["evidence"] = captures
        self.m["unit_runs"]["U-1"].update(status="completed", completed_at=self.history.now())
        completion = self.helper.capture_completion(self.p.root, self.m, "U-1", context, "synthetic-history-external", evidence_cache=self.cache)
        self.m["unit_runs"]["U-1"] = {"status": "completed", "completion_ref": completion}
        self.p.save()
        return inventory, context, completion, source_ref, captures

    def test_external_prompt_inventory_and_evidence_preserve_history_without_payload_copies(self):
        inventory, context, completion, source_ref, captures = self.capture()
        report = self.checker().run("development-plan", after=True)
        self.assertEqual("passed", report["result"], report)
        self.assertEqual("authorized", report["execution_authority"]["status"])
        self.assertEqual("applicable", report["unit_history"]["units"]["U-1"]["current_applicability"])
        archived = self.history.read(completion)
        self.assertIn("forge/evidence-policy.json", self.history.read(context)["files"])
        self.assertIn("tests/fixture-support.txt", archived["files"])
        self.assertNotIn(captures[0]["original_path"], archived["files"])
        self.assertEqual(source_ref, archived["checks"][0]["source_inventory_ref"])
        self.assertEqual(captures, archived["checks"][0]["evidence"])
        before = {p: p.read_bytes() for p in self.cache.rglob("*") if p.is_file()}
        self.helper.validate_completion(self.p.root, completion, evidence_cache=self.cache)
        self.assertEqual(before, {p: p.read_bytes() for p in self.cache.rglob("*") if p.is_file()})

    def test_missing_cache_and_changed_external_dependency_block_history(self):
        _, _, completion, source_ref, _ = self.capture()
        with self.assertRaisesRegex(ValueError, "evidence preparation required"):
            self.helper.validate_completion(self.p.root, completion)
        (self.cache / "objects" / source_ref["sha256"]).write_bytes(b"changed inventory")
        report = self.checker().run("development-plan", after=True)
        self.assertNotEqual("passed", report["result"], report)
        self.assertFalse(report["unit_history"]["units"]["U-1"]["historical_valid"])

    def test_compact_tested_source_changes_invalidate_current_acceptance_not_history(self):
        self.capture()
        self.p.write("tests/fixture-support.txt", "Changed test support.\n")
        report = self.checker().run("development-plan", after=True)
        unit = report["unit_history"]["units"]["U-1"]
        self.assertTrue(unit["historical_valid"], report)
        self.assertEqual("needs_revalidation", unit["current_applicability"])
        self.assertIn("tests/fixture-support.txt", str(unit["reasons"]))

    def test_unit_inventory_binds_its_construction_allocations_and_mechanisms(self):
        plan = self.m["unit_plan"]
        reference = {"path": "docs/architecture.md", "heading": "## Construction Mechanisms"}
        definition = {"version": 1, "mechanisms": {"M-ALPHA": {
            "required": True, "obligation_ids": ["FR-01"], "source_paths": ["src/alpha.txt"]}}}
        original = (self.p.root / "docs/architecture.md").read_text()
        self.p.write("docs/architecture.md", original + "\n## Construction Mechanisms\n```json\n" + json.dumps(definition) + "\n```\n")
        plan.update(construction_ref=reference, construction={"M-ALPHA": {"owner_unit": "U-1", "check_ids": ["QA-02"]}})
        inventory = self.history.inventory()
        inventory["sources"]["docs/architecture.md"] = {"mode": "sections", "headings": ["## Definition"]}
        before = self.helper.prepare_inventory(self.checker(), "U-1", inventory)
        self.assertEqual(definition["mechanisms"], before["bindings"]["construction"]["mechanisms"])
        plan["construction"]["M-ALPHA"]["check_ids"] = ["QA-03"]
        after = self.helper.prepare_inventory(self.checker(), "U-1", inventory)
        self.assertEqual(before["inputs"], after["inputs"])
        self.assertNotEqual(before["bindings"], after["bindings"])

    def test_stage_activate_bind_external_closure_without_new_authorization(self):
        self.capture()
        original_gate = copy.deepcopy(self.m["implementation_gate"])
        expected = self.p.hash("forge/sdd-manifest.json")
        candidate = self.helper.stage_candidate(self.p.root, self.m, expected, evidence_cache=self.cache)
        staged = self.history.read(candidate)
        self.assertTrue(any(key.startswith("@evidence/") for key in staged["observed_hashes"]))
        result = self.helper.activate_candidate(self.p.root, candidate, expected, evidence_cache=self.cache)
        self.assertEqual("activated", result["status"])
        self.assertEqual(original_gate, json.loads((self.p.root / "forge/sdd-manifest.json").read_text())["implementation_gate"])

    def test_external_receipt_change_after_staging_prevents_activation(self):
        self.capture()
        expected = self.p.hash("forge/sdd-manifest.json")
        candidate = self.helper.stage_candidate(self.p.root, self.m, expected, evidence_cache=self.cache)
        path = self.cache / "receipts" / (self.prompt["artifact_id"] + ".json")
        path.write_text(path.read_text() + "\n")  # Same semantics, changed prepared readback bytes.
        with self.assertRaisesRegex(ValueError, "candidate source/evidence/history changed"):
            self.helper.activate_candidate(self.p.root, candidate, expected, evidence_cache=self.cache)
        self.assertEqual(expected, self.p.hash("forge/sdd-manifest.json"))

    def test_legacy_missing_external_evidence_archives_unverified_without_granting_authority(self):
        self.m.update(checker_contract_version=1, unit_contract_version=1)
        self.history.fixture.complete("U-1", 3)
        check = next(item for item in self.m["verification"]["checks"] if item["check_id"] == "QA-02")
        check["revalidation_ref"] = {"path": "forge/missing-review.json", "content_hash": "a" * 64}
        gate = copy.deepcopy(self.m["implementation_gate"])
        self.p.save()
        expected = self.p.hash("forge/sdd-manifest.json")
        candidate = self.helper.adopt_legacy(self.p.root, expected)
        record = self.history.read(candidate)
        self.assertEqual("migration_ready", record["report"]["result"])
        self.assertEqual(gate, record["manifest"]["implementation_gate"])
        migrated = next(item for item in record["manifest"]["verification"]["checks"] if item["check_id"] == "QA-02")
        self.assertEqual("not_run", migrated["execution_status"])
        self.assertNotIn("revalidation_ref", migrated)
        self.assertEqual("unverified_not_reusable", self.history.read(record["manifest"]["legacy_history"][0])["acceptance"])

    def test_cli_explicit_cache_supports_context_and_rejects_in_project_cache(self):
        self.p.save()
        self.p.write("forge/inventory.json", json.dumps(self.history.inventory()))
        command = [sys.executable, str(SCRIPT.with_name("sdd_history.py")), "--project", str(self.p.root), "--evidence-cache", str(self.cache),
            "capture-context", "--unit", "U-1", "--inventory", "forge/inventory.json"]
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            self.helper.capture_context(self.p.root, self.m, "U-1", self.history.inventory(), evidence_cache=self.p.root / "cache")

    def test_context_capture_preserves_ordinary_version_hash_metadata(self):
        metadata = {"native_runtime": {"path": "/opt/synthetic-browser/metadata.json",
                    "version": "12.3", "sha256": "a" * 64, "build": "3"}}
        path = "forge/runtime-observation.json"
        self.p.write(path, json.dumps(metadata))
        self.m["runtime_observation"] = {"path": path, "content_hash": self.p.hash(path)}
        original = (self.p.root / path).read_bytes()
        context = self.helper.capture_context(self.p.root, self.m, "U-1", self.history.inventory(), evidence_cache=self.cache)
        record = self.history.read(context)
        self.assertEqual(original, (self.p.root / record["files"][path]["path"]).read_bytes())
        self.assertEqual(original, (self.p.root / path).read_bytes())
        self.assertNotIn("U-1", self.m.get("execution_contexts", {}))
        self.helper.validate_context(self.p.root, context, "U-1", evidence_cache=self.cache)

    def test_nested_explicit_reference_errors_are_not_swallowed_after_metadata(self):
        path = "forge/runtime-observation.json"
        missing_bytes = self.external.prepare({"synthetic": True}, "missing-prepared")
        (self.cache / "objects" / missing_bytes["sha256"]).unlink()
        for bad in ({"artifact_id": "missing-fields"}, {"locator": {}},
                    {"evidence_ref": None}, {"evidence_ref": {}},
                    {**self.prompt, "schema": []}, missing_bytes):
            with self.subTest(bad=bad):
                self.p.write(path, json.dumps({"runtime": {"path": "/opt/synthetic-runtime/info",
                    "version": "12.3", "sha256": "a" * 64}, "capture": bad}))
                manifest = {"observation": {"path": path, "content_hash": self.p.hash(path)}}
                with self.assertRaises(ValueError):
                    self.helper.referenced_paths(self.p.root, manifest, checker=self.checker())

    def test_history_rejects_malformed_explicit_refs_without_a_checker(self):
        for bad in ({"locator": {}}, {"artifact_id": "missing-fields"}, {"evidence_ref": None}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.helper.referenced_paths(self.p.root, {"capture": bad}, external_refs=[])

    def test_metadata_paths_do_not_hide_verified_payload_sources_or_siblings(self):
        source = "tests/only-in-external-payload.txt"
        sibling = "tests/only-in-observation.txt"
        self.p.write(source, "Synthetic payload source.\n")
        self.p.write(sibling, "Synthetic sibling source.\n")
        reference = self.external.prepare({"source_hashes": {source: self.p.hash(source)}}, "payload-sources")
        path = "forge/runtime-observation.json"
        self.p.write(path, json.dumps({"runtime": {"path": "/opt/synthetic-runtime/info",
            "version": "12.3", "sha256": "a" * 64}, "capture": reference,
            "sibling": {"path": sibling}}))
        manifest = {"observation": {"path": path, "content_hash": self.p.hash(path)}}
        paths = self.helper.referenced_paths(self.p.root, manifest, checker=self.checker())
        self.assertEqual({source, sibling, path}, paths)
        with self.assertRaisesRegex(ValueError, "unsafe history path"):
            self.helper.referenced_paths(self.p.root, {"path": "/opt/synthetic-runtime/info"})

    def test_direct_external_payload_keeps_declared_source_containment_strict(self):
        reference = self.external.prepare({"source_hashes": {
            "/opt/synthetic-runtime/info": "a" * 64}}, "unsafe-payload-source")
        with self.assertRaisesRegex(ValueError, "unsafe history path"):
            self.helper.referenced_paths(self.p.root, {"capture": reference}, checker=self.checker())

    def test_inactive_logs_preserve_bytes_without_loading_payloads_or_changing_authority(self):
        unavailable = self.external.prepare({"synthetic": True}, "inactive-unavailable")
        (self.cache / "objects" / unavailable["sha256"]).unlink()
        entries = [{"evidence_ref": value} for value in
                   ("forge/old-log.json", None, {}, unavailable)]
        logs = {key: entries for key in ("history", "run_history", "superseded")}
        path = "forge/legacy-manifest-snapshot.json"
        self.p.write(path, json.dumps(logs))
        original = (self.p.root / path).read_bytes()
        manifest = {**logs, "snapshot": {"path": path, "content_hash": self.p.hash(path)}}
        checker = self.checker()
        with mock.patch.object(checker.evidence_resolver, "resolve", side_effect=AssertionError("inactive payload loaded")):
            self.assertEqual({path}, self.helper.referenced_paths(self.p.root, manifest, checker=checker))
        self.assertEqual({path: self.p.hash(path)}, self.helper.candidate_hashes(self.p.root, manifest))
        self.m["history"].extend(entries)
        self.m["legacy_snapshot"] = manifest["snapshot"]
        before = copy.deepcopy(self.m)
        context = self.helper.capture_context(self.p.root, self.m, "U-1", self.history.inventory(), evidence_cache=self.cache)
        record = self.history.read(context)
        self.assertEqual(before, record["manifest"])
        self.assertEqual(before, self.m)
        self.assertEqual(original, (self.p.root / record["files"][path]["path"]).read_bytes())
        self.helper.validate_context(self.p.root, context, "U-1", evidence_cache=self.cache)

    def test_inactive_logs_do_not_hide_active_invalid_or_unavailable_references(self):
        unavailable = self.external.prepare({"synthetic": True}, "active-unavailable")
        (self.cache / "objects" / unavailable["sha256"]).unlink()
        for key in ("capture", "completion_history", "legacy_history"):
            for bad in ({"evidence_ref": "forge/old-log.json"}, {"evidence_ref": None},
                        {"artifact_id": "missing-fields"}, {**self.prompt, "schema": []}, unavailable):
                manifest = {"history": [{"evidence_ref": "forge/old-log.json"}], key: [bad]}
                with self.subTest(key=key, bad=bad):
                    with self.assertRaises(ValueError):
                        self.helper.referenced_paths(self.p.root, manifest, checker=self.checker())
                    with self.assertRaises(ValueError):
                        self.helper.candidate_hashes(self.p.root, manifest, evidence_cache=self.cache)

    def test_current_path_to_historical_payload_is_validated_and_parent_bytes_remain_bound(self):
        path = "forge/former-history-payload.json"
        self.p.write(path, json.dumps({"evidence_ref": "forge/old-log.json"}))
        inactive = {"history": [{"path": path, "content_hash": self.p.hash(path)}]}
        self.assertEqual(set(), self.helper.referenced_paths(self.p.root, inactive))
        with self.assertRaisesRegex(ValueError, "evidence_ref must be an object"):
            self.helper.referenced_paths(self.p.root, {**inactive, "current": {"path": path}})
        self.p.write(path, json.dumps(inactive))
        manifest = {"current": {"path": path}}
        before = self.helper.candidate_hashes(self.p.root, manifest)
        self.p.write(path, json.dumps({"history": [{"evidence_ref": "forge/another-old-log.json"}]}))
        self.assertNotEqual(before, self.helper.candidate_hashes(self.p.root, manifest))

    def test_candidate_hashes_still_validate_explicit_completion_and_legacy_envelopes(self):
        path = "forge/unit-history/legacy/synthetic/record.json"
        self.p.write(path, json.dumps({"history": [{"evidence_ref": "forge/old-log.json"}]}))
        ref = {"path": path, "content_hash": self.p.hash(path)}
        for key in ("completion_history", "legacy_history"):
            manifest = {key: [ref]}
            with self.subTest(key=key):
                self.assertIn(path, self.helper.candidate_hashes(self.p.root, manifest))
                with self.assertRaisesRegex(ValueError, "changed history file"):
                    self.helper.candidate_hashes(self.p.root, {key: [{**ref, "content_hash": "0" * 64}]})

    def test_repeated_sources_are_checked_once_per_traversal_and_fresh_calls_recheck_json(self):
        path = "forge/repeated-source.json"
        self.p.write(path, json.dumps({"version": 1, "sha256": "a" * 64}))
        manifest = {"observations": [{"path": path}] * 1000}
        with mock.patch.object(self.helper, "physical", wraps=self.helper.physical) as physical:
            self.assertEqual({path}, self.helper.referenced_paths(self.p.root, manifest))
        self.assertEqual(1, physical.call_count)
        self.p.write(path, json.dumps({"evidence_ref": None}))
        with self.assertRaisesRegex(ValueError, "evidence_ref must be an object"):
            self.helper.referenced_paths(self.p.root, manifest)

    def test_directory_discovery_does_not_skip_explicit_json_dependency_validation(self):
        path, source = "forge/discovery/record.json", "src/only-in-record.txt"
        self.p.write(source, "Synthetic source.\n")
        self.p.write(path, json.dumps({"source_hashes": {source: self.p.hash(source)}}))
        manifest = {"tree": {"path": "forge/discovery"}, "record": {"path": path}}
        self.assertEqual({path, source}, self.helper.referenced_paths(self.p.root, manifest))
        self.p.write(path, json.dumps({"evidence_ref": None}))
        with self.assertRaisesRegex(ValueError, "evidence_ref must be an object"):
            self.helper.referenced_paths(self.p.root, manifest)

    def test_repeated_and_overlapping_trees_are_scanned_once_and_fresh_calls_see_additions(self):
        path = "forge/discovery/nested/first.txt"
        self.p.write(path, "First.\n")
        manifest = {"trees": [{"path": value} for value in
                    ["forge/discovery", "forge/discovery/nested"] * 100]}
        scanned = []
        iterdir = Path.iterdir
        def observe(directory):
            scanned.append(directory)
            return iterdir(directory)
        with mock.patch.object(Path, "iterdir", observe):
            self.assertEqual({path}, self.helper.referenced_paths(self.p.root, manifest))
        self.assertCountEqual([self.p.root.resolve() / "forge/discovery", self.p.root.resolve() / "forge/discovery/nested"], scanned)
        second = "forge/discovery/nested/second.txt"
        self.p.write(second, "Second.\n")
        self.assertEqual({path, second}, self.helper.referenced_paths(self.p.root, manifest))

    def test_nested_directory_change_between_mentions_fails_instead_of_using_stale_membership(self):
        path = "forge/discovery/nested/first.txt"
        self.p.write(path, "First.\n")
        mutation = {"synthetic_mutation": True}
        manifest = {"first": {"path": "forge/discovery"}, "mutation": mutation,
                    "again": {"path": "forge/discovery"}}
        classify = self.helper.evidence_reference
        def change(value):
            if value is mutation:
                self.p.write("forge/discovery/nested/second.txt", "Second.\n")
            return classify(value)
        with mock.patch.object(self.helper, "evidence_reference", side_effect=change):
            with self.assertRaisesRegex(ValueError, "snapshot directory changed during discovery"):
                self.helper.referenced_paths(self.p.root, manifest)

    def test_cached_history_directory_keeps_recursive_embedding_prohibition(self):
        self.p.write("forge/unit-history/synthetic.txt", "Synthetic history.\n")
        manifest = {"ancestor": {"path": "forge"}, "history_tree": {"path": "forge/unit-history"}}
        with self.assertRaisesRegex(ValueError, "history directories cannot be embedded recursively"):
            self.helper.referenced_paths(self.p.root, manifest)

    def test_cached_root_or_nested_directory_replaced_by_link_is_rejected(self):
        for replaced in ("forge/discovery", "forge/discovery/nested"):
            with self.subTest(replaced=replaced):
                # Unique roots allow both cases without restoring any symlink.
                prefix = "root-case" if replaced == "forge/discovery" else "nested-case"
                base = "forge/" + prefix
                original = self.p.root / (base if prefix == "root-case" else base + "/nested")
                (self.p.root / (base + "/nested")).mkdir(parents=True)
                target = self.p.root / (prefix + "-target")
                target.mkdir()
                mutation = {"synthetic_mutation": True}
                manifest = {"first": {"path": base}, "mutation": mutation, "again": {"path": base}}
                classify = self.helper.evidence_reference
                def change(value):
                    if value is mutation:
                        original.rename(original.with_name(original.name + "-original"))
                        try:
                            original.symlink_to(target, target_is_directory=True)
                        except OSError as error:
                            self.skipTest("symlink creation unavailable: " + str(error))
                    return classify(value)
                with mock.patch.object(self.helper, "evidence_reference", side_effect=change):
                    with self.assertRaisesRegex(ValueError, "history cannot follow links|snapshot directory changed"):
                        self.helper.referenced_paths(self.p.root, manifest)
                with self.assertRaisesRegex(ValueError, "history cannot follow links"):
                    self.helper.referenced_paths(self.p.root, {"path": base})

    def test_capture_rechecks_containment_after_source_discovery(self):
        path, target = "src/replaceable.txt", "src/link-target.txt"
        self.p.write(path, "Original.\n")
        self.p.write(target, "Synthetic replacement.\n")
        manifest = {"sources": [{"path": path}] * 3}
        discover = self.helper.referenced_paths
        def change_after_discovery(*args, **kwargs):
            paths = discover(*args, **kwargs)
            (self.p.root / path).unlink()
            try:
                (self.p.root / path).symlink_to(self.p.root / target)
            except OSError as error:
                self.skipTest("symlink creation unavailable: " + str(error))
            return paths
        with mock.patch.object(self.helper, "referenced_paths", side_effect=change_after_discovery):
            with self.assertRaisesRegex(ValueError, "history cannot follow links"):
                self.helper.freeze_files(self.p.root, manifest, "forge/unit-history/contexts/synthetic")
        with self.assertRaisesRegex(ValueError, "history cannot follow links"):
            self.helper.referenced_paths(self.p.root, manifest)


if __name__ == "__main__":
    unittest.main()
