"""Generic synthetic proof of current review semantics, not product acceptance."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import unittest
from unittest import mock

import test_per_check_reuse as fixture
import test_evidence_checker as evidence_fixture
import test_reviewed_gates as gate_fixture
import reviewed_acceptance as reviewed


class ReviewedFixture:
    """A contextless failed run containing two genuine synthetic observations."""
    def __init__(self, owner, *, legacy=False, second=True, plain=False, full=False, completed=False, original_policy=None, record_inputs=True):
        self.base = fixture.PerCheckReuseTests("test_independently_owned_inputs_preserve_original_result")
        self.base.setUp()
        owner.addCleanup(self.base.doCleanups)
        self.p, self.m, self.b = self.base.p, self.base.m, self.base.base
        self.h = reviewed.history()
        if second:
            self.base.add_second_check(independent=True)
        # Literal paths work for actual legacy version 1 as well as newer sources.
        self.base.check["acceptance"].update(required_source_paths=["src/alpha.txt"], source_set_ids=[])
        self.m["verification"].pop("source_sets", None)
        self.m["verification"].pop("source_sets_ref", None)
        if plain:
            for check in self.m["verification"]["checks"]:
                check["acceptance"].pop("reuse_policy", None)
                check["acceptance"].pop("dependency_review", None)
        if original_policy:
            self.base.check["acceptance"]["reuse_policy"] = original_policy
        self.p.sync_unit_contract()
        self.p.authorize()
        self.m.update(checker_contract_version=1 if legacy else 4, unit_contract_version=1 if legacy else 4)
        self.b.fixture.begin("U-1", 3)
        run = self.m["unit_runs"]["U-1"]
        run.update(status="blocked", run_id="synthetic-contextless-run", started_at=self.h.utcnow())
        self.b.fixture.evidence("U-1", 4)
        self.environment = {"runtime": "synthetic-runtime-1", "configuration": "synthetic-isolated"}
        for check in self.m["verification"]["checks"]:
            if check["check_id"] not in self.m["unit_plan"]["units"]["U-1"]["required_check_ids"]:
                continue
            key = check["check_id"]
            native = {"unit_id": "U-1", "run_id": run["run_id"], "environment": self.environment,
                      "observed_at": self.h.utcnow()}
            evidence = self.p.evidence("forge/evidence/" + key + ".json", {"runtime": native, "synthetic_fixture": True})
            check["evidence"] = [{**evidence, "kind": self.h.api().GATE_KINDS.get(check["gate_id"], "security")}]
            runtime = self.p.evidence("forge/runs/" + key + "-runtime.json", {
                "event": "external_runtime_observation", "version": 1, **native, "evidence": check["evidence"]})
            check.update(run_id=run["run_id"], executed_at=self.h.utcnow(), runtime_observation_ref=runtime)
        if completed:
            run.update(status="completed", completed_at=self.h.utcnow())
        self.inputs = self.b.inventory(self.environment)
        if full:
            self.inputs["sources"] = {path: {"mode": "full"} for path in self.inputs["sources"]}
        old_checker = self.h.api().Checker(self.p.root, self.m)
        self.old_inventory = self.h.prepare_inventory(old_checker, "U-1", self.inputs)
        for check in self.m["verification"]["checks"]:
            if record_inputs and check["check_id"] in self.m["unit_plan"]["units"]["U-1"]["required_check_ids"]:
                check["evaluated_execution_inputs"] = copy.deepcopy(self.h.check_inputs.expected(self.old_inventory, check["check_id"]))
        self.original = copy.deepcopy(self.m)
        self.inventory_ref = self.h.write_new(self.p.root, "forge/original-inventory.json", self.h.encoded(self.old_inventory))
        if legacy:
            directory = self.h.HISTORY + "/legacy/synthetic-original"
            manifest_ref = self.h.write_new(self.p.root, directory + "/manifest.json", self.h.encoded(self.original))
            source = {"event": "legacy_execution_archive", "version": 2, "acceptance": "unverified_not_reusable",
                      "manifest_ref": manifest_ref, "archived_at": self.h.utcnow(),
                      "snapshot_root": directory + "/files", "files": self.h.freeze_files(self.p.root, self.original, directory)}
            self.source_ref = self.h.store_record(self.p.root, "legacy", source, directory)
            self.m["legacy_history"] = [self.source_ref]
        else:
            self.source_ref = reviewed.import_observations(self.p.root, self.original, "U-1")
        self.m.update(checker_contract_version=4, unit_contract_version=4)
        self.request = {"unit_id": "U-1", "source_kind": "legacy_archive" if legacy else "external_observations",
                        "source_ref": self.source_ref, "original_inventory_ref": self.inventory_ref,
                        "current_inventory": copy.deepcopy(self.inputs),
                        "review": {"complete": True, "reviewer": "synthetic owner", "reviewed_at": self.h.utcnow(),
                                   "rationale": "Review of preserved synthetic facts, not a production approval.",
                                   "reuse_eligibility": {key: "deterministic_isolated" for key, row in self.m["unit_plan"]["acceptance"].items() if row["owner_unit"] == "U-1"},
                                   "preconditions": {key: [] for key, row in self.m["unit_plan"]["acceptance"].items() if row["owner_unit"] == "U-1"}},
                        "procedural_gaps": ["missing_registered_prestart_context"]}

    def capture(self):
        ref = reviewed.capture(self.p.root, self.m, self.request)
        self.m.setdefault("reviewed_acceptance", {}).setdefault("U-1", []).append(ref)
        return ref

    def resolve(self):
        return reviewed.resolve(self.h.api().Checker(self.p.root, self.m))


class ReviewedAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.f = ReviewedFixture(self)

    def test_contextless_acceptance_preserves_failed_run_and_original_observations(self):
        f = self.f
        f.capture()
        result = f.resolve()
        self.assertEqual({"U-1"}, set(result["units"]), result)
        self.assertEqual({"QA-02", "QA-07"}, set(result["checks"]))
        self.assertEqual("blocked", f.m["unit_runs"]["U-1"]["status"])
        self.assertNotIn("execution_contexts", f.m)
        for key, check in result["checks"].items():
            self.assertEqual(next(row for row in f.original["verification"]["checks"] if row["check_id"] == key), check)

    def test_import_and_identical_review_are_idempotent(self):
        f = self.f
        self.assertEqual(f.source_ref, reviewed.import_observations(f.p.root, f.original, "U-1"))
        captured_at = f.h.api().timestamp(f.request["review"]["reviewed_at"]) + timedelta(seconds=1)
        with mock.patch.object(f.h, "utcnow", return_value=captured_at.isoformat()):
            first = reviewed.capture(f.p.root, f.m, f.request)
        record = f.h.read_ref(f.p.root, first)
        self.assertEqual(captured_at.isoformat(), record["recorded_at"])
        self.assertGreater(f.h.api().timestamp(record["recorded_at"]), f.h.api().timestamp(record["review"]["reviewed_at"]))
        self.assertEqual(f.request["review"]["reviewed_at"], record["review"]["reviewed_at"])
        with mock.patch.object(f.h, "utcnow", return_value=(captured_at + timedelta(seconds=1)).isoformat()):
            retry = reviewed.capture(f.p.root, f.m, f.request)
        self.assertEqual(first, retry)
        self.assertEqual(record["recorded_at"], f.h.read_ref(f.p.root, retry)["recorded_at"])

    def test_legacy_file_observations_can_be_reviewed_without_relabeling(self):
        f = ReviewedFixture(self, legacy=True, second=False)
        f.capture()
        result = f.resolve()
        self.assertIn("U-1", result["units"], result)
        self.assertEqual("unverified_not_reusable", f.h.read_ref(f.p.root, f.source_ref)["acceptance"])

    def test_true_legacy_full_sources_without_old_reuse_policy_can_be_reviewed(self):
        f = ReviewedFixture(self, legacy=True, second=False, plain=True, full=True, completed=True, record_inputs=False)
        f.capture()
        result = f.resolve()
        self.assertIn("U-1", result["units"], result)
        self.assertNotIn("reuse_policy", result["checks"]["QA-02"]["acceptance"])
        self.assertNotIn("dependency_review", result["checks"]["QA-02"]["acceptance"])
        self.assertNotIn("evaluated_execution_inputs", result["checks"]["QA-02"])
        self.assertEqual("full", f.old_inventory["sources"]["docs/qa-checklist.md"]["mode"])
        self.assertEqual("completed", f.m["unit_runs"]["U-1"]["status"])

    def test_explicit_original_fresh_policy_cannot_be_relabelled(self):
        f = ReviewedFixture(self, original_policy="fresh")
        f.base.check["acceptance"]["reuse_policy"] = "deterministic_isolated"
        f.p.sync_unit_contract()
        f.capture()
        result = f.resolve()
        self.assertNotIn("QA-02", result["checks"])
        self.assertIn("original explicit fresh", str(result["reviews"]))

    def test_missing_or_unknown_owner_precondition_is_unresolved(self):
        f = self.f
        f.request["review"]["preconditions"].pop("QA-02")
        f.capture()
        self.assertEqual({"QA-07"}, set(f.resolve()["checks"]))
        f.request["review"]["preconditions"]["QA-02"] = [{"source_ref": {}, "observation_ref": {},
                                                        "observed_at": f.h.utcnow(), "status": "unknown"}]
        f.capture()
        self.assertIn("precondition is unknown", str(f.resolve()["reviews"]))

    def test_frozen_runtime_and_native_proof_survive_removed_working_copies(self):
        f = self.f
        f.capture()
        for check in f.original["verification"]["checks"]:
            if check.get("run_id") == "synthetic-contextless-run":
                (f.p.root / check["runtime_observation_ref"]["path"]).unlink()
                for evidence in check["evidence"]:
                    (f.p.root / evidence["path"]).unlink()
        self.assertIn("U-1", f.resolve()["units"])

    def test_duplicate_review_reference_is_rejected(self):
        f = self.f
        ref = f.capture()
        f.m["reviewed_acceptance"]["U-1"].append(ref)
        with self.assertRaisesRegex(ValueError, "duplicate acceptance"):
            f.resolve()

    def test_managed_original_and_current_accounting_enforce_prepared_evidence(self):
        f = self.f
        external = evidence_fixture.EvidenceCheckerTests("runTest")
        external.setUp()
        self.addCleanup(external.doCleanups)
        external.p, external.m = f.p, f.m
        f.p.write("forge/evidence-policy.json", json.dumps(external.policy))
        f.m["evidence_storage"] = {"policy_path": "forge/evidence-policy.json"}
        f.m["evidence_accounting"] = {"version": 1, "project_id": external.policy["project_id"],
                                      "policy_sha256": f.p.hash("forge/evidence-policy.json"), "runs": {}}
        references = []
        for check in f.m["verification"]["checks"]:
            if check.get("run_id") != "synthetic-contextless-run":
                continue
            old = check["evidence"][0]
            reference = external.prepare((f.p.root / old["path"]).read_bytes(), "managed-" + check["check_id"],
                                         old["kind"], "sdd-result-v1", f.h.api().Checker(f.p.root, f.m).check_bindings(check))
            reference["provenance"]["run_id"] = check["run_id"]
            external.receipt(reference)
            check["evidence"] = [reference]
            runtime = f.h.read_ref(f.p.root, check["runtime_observation_ref"])
            runtime["evidence"] = [reference]
            check["runtime_observation_ref"] = f.p.evidence(check["runtime_observation_ref"]["path"], runtime)
            references.append(reference)
        runs = f.m["evidence_accounting"]["runs"]
        runs["synthetic-contextless-run"] = runs.pop("synthetic-original-run")
        original_accounting = copy.deepcopy(f.m["evidence_accounting"])
        original_runs = copy.deepcopy(f.m["unit_runs"])
        f.request["source_ref"] = reviewed.import_observations(f.p.root, f.m, "U-1", evidence_cache=external.cache)
        f.request["review"]["reviewed_at"] = f.h.utcnow()
        with mock.patch("subprocess.run", side_effect=AssertionError("read-only gates cannot fetch evidence")):
            ref = reviewed.capture(f.p.root, f.m, f.request, evidence_cache=external.cache)
            f.m["reviewed_acceptance"] = {"U-1": [ref]}
            result = reviewed.resolve(f.h.api().Checker(f.p.root, f.m, evidence_cache=external.cache))
        self.assertIn("U-1", result["units"], result)
        self.assertEqual(original_accounting, f.m["evidence_accounting"])
        self.assertEqual(original_runs, f.m["unit_runs"])
        for field in ("pending_reservations", "unreconciled_outputs"):
            runs["synthetic-contextless-run"][field] = 1
            result = reviewed.resolve(f.h.api().Checker(f.p.root, f.m, evidence_cache=external.cache))
            self.assertFalse(result["checks"], result)
            self.assertIn("outstanding", str(result["reviews"]))
            runs["synthetic-contextless-run"][field] = 0
        try:
            missing = reviewed.resolve(f.h.api().Checker(f.p.root, f.m))
        except ValueError as error:
            self.assertIn("evidence preparation required", str(error))
        else:
            self.assertFalse(missing["checks"])
        (external.cache / "objects" / references[0]["sha256"]).write_bytes(b"corrupt prepared proof")
        with self.assertRaisesRegex(ValueError, "hash/size mismatch"):
            reviewed.resolve(f.h.api().Checker(f.p.root, f.m, evidence_cache=external.cache))

    def test_public_original_inventory_preparation_reads_frozen_bytes(self):
        f = self.f
        f.p.write("src/alpha.txt", "Current work differs from original observations.\n")
        inventory = copy.deepcopy(f.inputs)
        inventory["review"]["reviewed_at"] = f.h.utcnow()
        ref = reviewed.prepare_original_inventory(f.p.root, f.m, "U-1", "external_observations", f.source_ref, inventory)
        prepared = f.h.read_ref(f.p.root, ref)
        self.assertEqual(f.old_inventory["execution_fingerprints"], prepared["execution_fingerprints"])
        self.assertNotEqual(f.p.hash("src/alpha.txt"), prepared["execution_fingerprints"]["src/alpha.txt"]["content_hash"])
        self.assertEqual(ref, reviewed.prepare_original_inventory(f.p.root, f.m, "U-1", "external_observations", f.source_ref, inventory))

    def test_interrupted_import_reuses_verified_partial_bytes(self):
        f = self.f
        for position in (1, 3):
            source = copy.deepcopy(f.original)
            source["unit_runs"]["U-1"]["reason"] = "Synthetic interrupted import " + str(position)
            original = f.h.write_snapshot
            calls = []
            def interrupt(*args, **kwargs):
                calls.append(args)
                if len(calls) == position:
                    raise RuntimeError("synthetic write interruption")
                return original(*args, **kwargs)
            with mock.patch.object(f.h, "write_snapshot", side_effect=interrupt):
                with self.assertRaisesRegex(RuntimeError, "interruption"):
                    reviewed.import_observations(f.p.root, source, "U-1")
            ref = reviewed.import_observations(f.p.root, source, "U-1")
            self.assertEqual(ref, reviewed.import_observations(f.p.root, source, "U-1"))
            self.assertFalse(list((f.p.root / f.h.HISTORY).rglob("*.pending-*")))

    def test_identical_concurrent_import_and_review_share_complete_publications(self):
        f = self.f
        source = copy.deepcopy(f.original)
        source["unit_runs"]["U-1"]["reason"] = "Synthetic concurrent import"
        with ThreadPoolExecutor(max_workers=2) as executor:
            refs = list(executor.map(lambda _: reviewed.import_observations(f.p.root, source, "U-1"), range(2)))
        self.assertEqual(refs[0], refs[1])
        with ThreadPoolExecutor(max_workers=2) as executor:
            refs = list(executor.map(lambda _: reviewed.capture(f.p.root, f.m, f.request), range(2)))
        self.assertEqual(refs[0], refs[1])

    def test_retained_review_failure_cannot_be_erased_by_reviewing_an_older_pass(self):
        f = self.f
        later = copy.deepcopy(f.original)
        check = next(row for row in later["verification"]["checks"] if row["check_id"] == "QA-02")
        check.update(execution_status="failed", executed_at=f.h.utcnow(), findings=[])
        request = copy.deepcopy(f.request)
        request["source_ref"] = reviewed.import_observations(f.p.root, later, "U-1")
        request["review"]["reviewed_at"] = f.h.utcnow()
        failure = reviewed.capture(f.p.root, f.m, request)
        f.m["reviewed_acceptance"] = {"U-1": [failure]}
        f.request["review"]["reviewed_at"] = f.h.utcnow()
        f.capture()
        result = f.resolve()
        self.assertNotIn("QA-02", result["checks"])
        self.assertIn("failed/ambiguous", str(result["reviews"]))

    def undated_failure(self):
        f = self.f
        source = copy.deepcopy(f.original)
        check = next(row for row in source["verification"]["checks"] if row["check_id"] == "QA-02")
        check["execution_status"] = "failed"
        check.pop("executed_at")
        request = copy.deepcopy(f.request)
        request["source_ref"] = reviewed.import_observations(f.p.root, source, "U-1")
        request["review"]["reviewed_at"] = f.h.utcnow()
        reference = reviewed.capture(f.p.root, f.m, request)
        f.m["reviewed_acceptance"] = {"U-1": [reference]}
        return reference, request["source_ref"]

    def test_genuine_fresh_pass_after_immutable_unknown_failure_bound_recovers(self):
        f = self.f
        failure_ref, failure_source = self.undated_failure()
        bound = f.h.read_ref(f.p.root, failure_source)["imported_at"]
        # Explicitly later execution must not depend on the host clock ticking.
        fresh_at = (f.h.api().timestamp(bound) + timedelta(seconds=1)).isoformat()
        clock = mock.patch.object(f.h, "utcnow", return_value=fresh_at)
        clock.start()
        self.addCleanup(clock.stop)
        run = f.m["unit_runs"]["U-1"]
        run.update(run_id="synthetic-fresh-run", started_at=f.h.utcnow())
        for check in f.m["verification"]["checks"]:
            if f.m["unit_plan"]["acceptance"][check["check_id"]]["owner_unit"] != "U-1":
                continue
            native = {"unit_id": "U-1", "run_id": run["run_id"], "environment": f.environment, "observed_at": f.h.utcnow()}
            evidence = f.p.evidence("forge/evidence/fresh-" + check["check_id"] + ".json", {"runtime": native, "synthetic_fixture": True})
            check["evidence"] = [{**evidence, "kind": f.h.api().GATE_KINDS.get(check["gate_id"], "security")}]
            check["runtime_observation_ref"] = f.p.evidence("forge/runs/fresh-" + check["check_id"] + ".json", {
                "event": "external_runtime_observation", "version": 1, **native, "evidence": check["evidence"]})
            check.update(run_id=run["run_id"], executed_at=f.h.utcnow())
        request = copy.deepcopy(f.request)
        request["source_ref"] = reviewed.import_observations(f.p.root, f.m, "U-1")
        request["review"]["reviewed_at"] = f.h.utcnow()
        fresh_ref = reviewed.capture(f.p.root, f.m, request)
        f.m["reviewed_acceptance"]["U-1"].append(fresh_ref)
        result = f.resolve()
        self.assertIn("U-1", result["units"], result)
        self.assertGreater(f.h.api().timestamp(result["checks"]["QA-02"]["executed_at"]), f.h.api().timestamp(bound))
        failed_manifest = f.h.read_ref(f.p.root, f.h.read_ref(f.p.root, failure_source)["manifest_ref"])
        failed = next(row for row in failed_manifest["verification"]["checks"] if row["check_id"] == "QA-02")
        self.assertEqual("failed", failed["execution_status"])
        self.assertNotIn("executed_at", failed)
        self.assertEqual(failure_ref, f.m["reviewed_acceptance"]["U-1"][0])

    def test_forged_unknown_failure_bounds_never_establish_recovery(self):
        f = self.f
        failure_ref, failure_source = self.undated_failure()
        source = f.h.read_ref(f.p.root, failure_source)
        original_review = f.h.read_ref(f.p.root, failure_ref)
        prior_pass = next(row for row in f.original["verification"]["checks"] if row["check_id"] == "QA-02")
        for value in (None, "not-a-date", "1900-01-01T00:00:00Z", "2999-01-01T00:00:00Z"):
            with self.subTest(bound=value):
                bad = {**source, "imported_at": value}
                bad_source = f.h.store_record(f.p.root, "synthetic-invalid-bound", bad)
                bad_review = {**original_review, "source_ref": bad_source}
                f.m["reviewed_acceptance"] = {"U-1": [f.h.store_record(f.p.root, "reviewed-acceptance", bad_review)]}
                with self.assertRaisesRegex(ValueError, "failed/ambiguous"):
                    reviewed.require_no_counterevidence(f.h.api().Checker(f.p.root, f.m), "U-1", prior_pass)

    def test_original_check_owner_construction_prerequisites_are_transitive(self):
        fixture = gate_fixture.ReviewedGateTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = fixture.m["unit_plan"]
        plan["units"]["U-2"]["construction_dependencies"] = ["U-1"]
        plan["units"]["U-3"]["construction_dependencies"] = []
        plan["acceptance"]["QA-01"]["prerequisite_checks"] = ["QA-03"]
        original_inventory = fixture.inventory
        def inventory(unit):
            value = original_inventory(unit)
            if unit == "U-3":
                value["execution_inputs"].update({path: {"mode": "file"} for path in ("src/alpha.txt", "src/beta.txt")})
            return value
        fixture.inventory = inventory
        fixture.reviewed(("U-1", "U-2", "U-3"))
        h = reviewed.history()
        result = reviewed.resolve(h.api().Checker(fixture.p.root, fixture.m))
        facts = result["reviews"]["U-3"]["original_prerequisites"]["QA-01"]
        self.assertEqual({"QA-02", "QA-03"}, set(facts["checks"]))
        self.assertEqual({"U-1", "U-2"}, set(facts["units"]))

    def test_other_unit_retained_source_cannot_hide_newer_ancestor_failure(self):
        f = self.f
        f.capture()
        source = copy.deepcopy(f.original)
        check = next(row for row in source["verification"]["checks"] if row["check_id"] == "QA-02")
        check.update(execution_status="failed", executed_at=f.h.utcnow(), findings=[])
        source_ref = reviewed.import_observations(f.p.root, source, "U-2")
        inventory = f.b.inventory(f.environment, unit="U-2")
        original_ref = reviewed.prepare_original_inventory(f.p.root, f.m, "U-2", "external_observations", source_ref, inventory)
        request = {"unit_id": "U-2", "source_kind": "external_observations", "source_ref": source_ref,
                   "original_inventory_ref": original_ref, "current_inventory": inventory,
                   "review": {"complete": True, "reviewer": "synthetic owner", "reviewed_at": f.h.utcnow(),
                              "rationale": "Preserve observations including another unit's failure.",
                              "preconditions": {"QA-03": []}, "reuse_eligibility": {"QA-03": "deterministic_isolated"}},
                   "procedural_gaps": ["missing_registered_prestart_context"]}
        reference = reviewed.capture(f.p.root, f.m, request)
        f.m["reviewed_acceptance"]["U-2"] = [reference]
        result = f.resolve()
        self.assertNotIn("QA-02", result["checks"])
        self.assertIn("QA-07", result["checks"])
        self.assertIn("failed/ambiguous", str(result["reviews"]["U-1"]))

    def test_decision_cannot_predate_an_input_owner_review(self):
        f = self.f
        later_review = (f.h.api().timestamp(f.request["review"]["reviewed_at"]) + timedelta(seconds=1)).isoformat()
        f.request["current_inventory"]["review"]["reviewed_at"] = later_review
        with mock.patch.object(f.h, "utcnow", return_value=later_review):
            with self.assertRaisesRegex(ValueError, "predates an input owner review"):
                f.capture()

    def test_legacy_scalar_hashes_cannot_establish_unknown_tree_membership(self):
        f = ReviewedFixture(self, legacy=True, second=False, plain=True, record_inputs=False)
        inventory = copy.deepcopy(f.inputs)
        inventory["execution_inputs"] = {"src": {"mode": "tree"}}
        inventory["review"]["reviewed_at"] = f.h.utcnow()
        reference = reviewed.prepare_original_inventory(f.p.root, f.m, "U-1", "legacy_archive", f.source_ref, inventory)
        f.request.update(original_inventory_ref=reference, current_inventory=inventory)
        f.request["review"]["reviewed_at"] = f.h.utcnow()
        f.capture()
        self.assertNotIn("QA-02", f.resolve()["checks"])
        self.assertIn("input fact is unknown", str(f.resolve()["reviews"]))

    def test_selected_proof_ignores_inactive_missing_payload_but_checks_active_bytes(self):
        f = ReviewedFixture(self, legacy=True)
        source = f.h.read_ref(f.p.root, f.source_ref)
        source["files"]["forge/evidence/inactive.bin"] = f.h.write_snapshot(f.p.root,
            source["snapshot_root"] + "/forge/evidence/inactive.bin", b"Unrelated archived synthetic payload")
        reference = f.h.store_record(f.p.root, "legacy", source)
        f.m["legacy_history"].append(reference)
        f.m["history_integrity"] = {"legacy_payloads": "audit_only"}
        inactive = f.p.root / source["files"]["forge/evidence/inactive.bin"]["path"]
        inactive.unlink()
        f.request["source_ref"] = reference
        f.request["review"]["reviewed_at"] = f.h.utcnow()
        f.capture()
        self.assertIn("U-1", f.resolve()["units"])
        with f.h.history_integrity_scope(f.m, force_full=True):
            with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
                f.resolve()
        policy = f.m.pop("history_integrity")
        with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
            f.resolve()
        f.m["history_integrity"] = policy
        active = f.p.root / source["files"]["forge/evidence/QA-02.json"]["path"]
        active.unlink()
        with self.assertRaisesRegex(ValueError, "active original source"):
            f.resolve()

    def test_legacy_only_deferral_does_not_skip_external_observation_payloads(self):
        f = self.f
        source = f.h.read_ref(f.p.root, f.source_ref)
        source["files"]["forge/evidence/inactive.bin"] = f.h.write_snapshot(f.p.root,
            source["snapshot_root"] + "/forge/evidence/inactive.bin", b"Unrelated external import payload")
        f.request["source_ref"] = f.h.store_record(f.p.root, "external-observations", source)
        f.request["review"]["reviewed_at"] = f.h.utcnow()
        f.m["history_integrity"] = {"legacy_payloads": "audit_only"}
        (f.p.root / source["files"]["forge/evidence/inactive.bin"]["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "historical snapshot changed"):
            f.capture()

    def test_original_precondition_uses_native_observation_time(self):
        f = self.f
        check = next(row for row in f.original["verification"]["checks"] if row["check_id"] == "QA-02")
        native = f.h.read_ref(f.p.root, check["runtime_observation_ref"])
        row = {"source_ref": {"path": "docs/qa-checklist.md", "content_hash": f.p.hash("docs/qa-checklist.md")},
               "observation_ref": check["runtime_observation_ref"], "observed_at": native["observed_at"], "status": "established"}
        f.request["review"]["preconditions"]["QA-02"] = [row]
        f.capture()
        self.assertIn("QA-02", f.resolve()["checks"])
        row["observed_at"] = (f.h.api().timestamp(native["observed_at"]) - timedelta(seconds=1)).isoformat()
        f.request["review"]["reviewed_at"] = f.h.utcnow()
        f.capture()
        result = f.resolve()
        self.assertNotIn("QA-02", result["checks"])
        self.assertIn("precondition date is not established by native evidence", str(result["reviews"]))

    def test_source_change_only_invalidates_affected_check(self):
        f = self.f
        f.capture()
        f.p.write("src/other.txt", "Changed independent input.\n")
        result = f.resolve()
        self.assertEqual({"QA-02"}, set(result["checks"]), result)
        self.assertNotIn("U-1", result["units"])
        self.assertEqual(["QA-07"], result["reviews"]["U-1"]["revalidation_check_ids"])

    def test_definition_change_only_invalidates_affected_check(self):
        f = self.f
        f.capture()
        next(row for row in f.m["verification"]["checks"] if row["check_id"] == "QA-07")["task"] = "Different assertion"
        result = f.resolve()
        self.assertEqual({"QA-02"}, set(result["checks"]), result)

    def test_newer_failure_without_finding_prevents_old_pass(self):
        f = self.f
        f.capture()
        check = next(row for row in f.m["verification"]["checks"] if row["check_id"] == "QA-02")
        check.update(execution_status="failed", executed_at=f.h.utcnow(), findings=[])
        result = f.resolve()
        self.assertNotIn("QA-02", result["checks"])
        self.assertIn("QA-07", result["checks"])
        self.assertIn("failed/ambiguous", str(result["reviews"]))

    def test_later_authority_change_does_not_rewrite_original_authority(self):
        f = self.f
        f.capture()
        f.m["implementation_gate"] = {"state": "awaiting_implementation_prompt"}
        result = f.resolve()
        self.assertIn("U-1", result["units"], result)
        self.assertEqual(f.original["implementation_gate"]["state"], result["reviews"]["U-1"]["original_authority"]["state"])

    def test_fresh_check_and_changed_environment_are_not_reused(self):
        f = self.f
        f.capture()
        f.base.check["acceptance"]["reuse_policy"] = "fresh"
        self.assertNotIn("QA-02", f.resolve()["checks"])
        f.base.check["acceptance"]["reuse_policy"] = "deterministic_isolated"
        request = copy.deepcopy(f.request)
        request["current_inventory"]["environment"]["runtime"] = "different"
        ref = reviewed.capture(f.p.root, f.m, request)
        f.m["reviewed_acceptance"]["U-1"].append(ref)
        self.assertFalse(f.resolve()["checks"])

    def test_corrupt_latest_review_never_falls_back(self):
        f = self.f
        first = f.capture()
        f.m["reviewed_acceptance"]["U-1"].append({**first, "content_hash": "0" * 64})
        with self.assertRaisesRegex(ValueError, "changed history"):
            f.resolve()

    def test_false_native_runtime_claim_is_unresolved(self):
        f = self.f
        source = f.h.read_ref(f.p.root, f.source_ref)
        original = f.h.read_ref(f.p.root, source["manifest_ref"])
        check = next(row for row in original["verification"]["checks"] if row["check_id"] == "QA-02")
        # Preserve a genuinely new imported source whose runtime envelope lies
        # about native evidence. Capture must not adopt its declared environment.
        runtime = f.h.read_ref(f.p.root, check["runtime_observation_ref"])
        runtime["environment"] = {"runtime": "invented"}
        check["runtime_observation_ref"] = f.p.evidence("forge/runs/false-runtime.json", runtime)
        source_ref = reviewed.import_observations(f.p.root, original, "U-1")
        request = copy.deepcopy(f.request)
        request.update(source_ref=source_ref)
        request["review"]["reviewed_at"] = f.h.utcnow()
        ref = reviewed.capture(f.p.root, f.m, request)
        f.m["reviewed_acceptance"] = {"U-1": [ref]}
        result = f.resolve()
        self.assertNotIn("QA-02", result["checks"])
        self.assertIn("native evidence", str(result["reviews"]))

    def test_future_review_and_unknown_original_inventory_rejected(self):
        f = self.f
        f.request["review"]["reviewed_at"] = "2999-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "future"):
            f.capture()
        f.request["review"]["reviewed_at"] = f.h.utcnow()
        f.request["original_inventory_ref"]["content_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "changed history"):
            f.capture()


if __name__ == "__main__":
    unittest.main()
