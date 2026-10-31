"""Public history boundaries on isolated synthetic policy-successor fixtures.

No SDK, mutable accounting ledger, provider, or product execution is involved.
Runtime receipts observe only the Python interpreter running these tests.
"""
import copy
import hashlib
import json
import sys
import unittest

import test_attempt_history as attempts
from test_evidence_policy_lineage import effective, policies, setup_bytes


POLICY = "forge/evidence-policy.json"


class AttemptPolicyLineageTests(unittest.TestCase):
    def setUp(self):
        # Composition deliberately does not inherit or rediscover the old suite.
        self.fixture = attempts.AttemptHistoryTests(
            "test_continuation_probes_real_runtime_resets_results_and_preserves_work")
        self.fixture.setUp()
        temporary_project = self.fixture.p.root
        self.addCleanup(lambda: self.assertFalse(temporary_project.exists(), temporary_project))
        self.addCleanup(self.fixture.doCleanups)
        self.base = self.fixture.base
        self.p, self.m = self.fixture.p, self.fixture.m
        self.policy = policies.load_defaults()
        self.policy.update(project_id="11111111-1111-4111-8111-111111111111",
                           store_id="22222222-2222-4222-8222-222222222222", provider="local")
        self.policy = policies.validate_policy(self.policy)
        self.original_raw = (json.dumps(self.policy, indent=4) + "\n\n").encode()
        (self.p.root / "forge").mkdir(exist_ok=True)
        (self.p.root / POLICY).write_bytes(self.original_raw)
        self.p.write("config/synthetic.txt", "unchanged synthetic configuration\n")
        # A portable, already captured receipt, not a live accounting operation.
        self.m["evidence_accounting"] = {
            "version": 1, "project_id": self.policy["project_id"],
            "policy_sha256": hashlib.sha256(self.original_raw).hexdigest(), "runs": {}}
        original_inventory = self.base.inventory

        def inventory(environment=None, unit="U-1"):
            result = original_inventory(environment=environment, unit=unit)
            result["execution_inputs"].update({POLICY: {"mode": "file"},
                                                "config/synthetic.txt": {"mode": "file"}})
            return result

        self.base.inventory = inventory

    def transition(self, *, raw=None, key="max_unit_retries", amount=1):
        raw = (self.p.root / POLICY).read_bytes() if raw is None else raw
        candidate = effective(json.loads(raw))
        candidate["limits"][key] += amount
        value = policies.append_policy_transition(raw, candidate)
        (self.p.root / POLICY).write_bytes(setup_bytes(value))
        return value

    def archive(self):
        self.fixture.start()
        self.reference = self.fixture.capture()
        self.helper = self.fixture.helper
        self.original_checks = copy.deepcopy(self.m["verification"]["checks"])
        self.original_accounting = copy.deepcopy(self.m["evidence_accounting"])
        self.original_gate = copy.deepcopy(self.m["implementation_gate"])
        self.old_bytes = {path.relative_to(self.p.root).as_posix(): path.read_bytes()
                          for path in (self.p.root / "forge/unit-history").rglob("*")
                          if path.is_file()}
        self.code_bytes = (self.p.root / "src/alpha.txt").read_bytes()
        return self.reference

    def assert_original_preserved(self):
        for path, raw in self.old_bytes.items():
            self.assertEqual(raw, (self.p.root / path).read_bytes(), path)
        self.assertEqual(self.original_accounting, self.m["evidence_accounting"])
        self.assertEqual(self.original_gate, self.m["implementation_gate"])
        self.assertEqual(self.code_bytes, (self.p.root / "src/alpha.txt").read_bytes())
        archived = self.base.read(self.reference)
        self.assertEqual("not_completed", archived["acceptance"])
        self.assertEqual("failed", archived["checks"][0]["execution_status"])

    def reviewed(self):
        return self.fixture.continuation_inventory()

    def continue_attempt(self, inventory=None, run_id="synthetic-attempt-2"):
        return self.helper.capture_continuation(
            self.p.root, self.m, "U-1", self.reference, run_id,
            self.reviewed() if inventory is None else inventory)

    def assert_rejected(self, inventory=None):
        with self.assertRaises((ValueError, KeyError)):
            self.continue_attempt(inventory)
        self.base.assert_blocked(self.base.report("implementation", "start", "U-1"))
        self.base.assert_blocked(self.base.report("implementation", "complete", "U-1"))
        self.assert_original_preserved()

    def assert_nonaccepting_reconciliation(self):
        report = self.base.report("guardrails")
        self.assertEqual("passed", report["result"], report)
        self.assertTrue(report["warnings"], report)
        self.assertEqual(self.original_checks, self.m["verification"]["checks"])
        self.base.assert_blocked(self.base.report("implementation", "start", "U-1"))
        self.base.assert_blocked(self.base.report("implementation", "complete", "U-1"))
        self.assert_original_preserved()

    def assert_fresh_candidate(self, result):
        candidate = result["manifest"]
        self.assertEqual([self.reference], candidate["attempt_history"]["U-1"])
        self.assertEqual("pending", candidate["unit_runs"]["U-1"]["status"])
        self.assertEqual("synthetic-attempt-2", candidate["unit_runs"]["U-1"]["run_id"])
        check = next(c for c in candidate["verification"]["checks"] if c["check_id"] == "QA-02")
        self.assertEqual("not_run", check["execution_status"])
        for key in ("evidence", "executed_at", "evaluated_execution_inputs", "runtime_observation_ref"):
            self.assertNotIn(key, check)
        context = self.base.read(result["context_ref"])
        fingerprint = context["input_inventory"]["execution_fingerprints"][POLICY]
        self.assertEqual(self.p.hash(POLICY), fingerprint["content_hash"])
        self.assertEqual(self.reference, context["prior_attempt_ref"])
        self.helper.validate_transition(self.p.root, self.m, candidate, {})
        self.m.clear()
        self.m.update(candidate)
        self.assertEqual("passed", self.base.report("implementation", "start", "U-1")["result"])
        self.base.assert_blocked(self.base.report("implementation", "complete", "U-1"))
        self.assert_original_preserved()

    def test_base_raw_ancestor_reconciles_without_reusing_failed_results(self):
        self.archive()
        self.transition()
        self.assert_nonaccepting_reconciliation()
        self.assert_fresh_candidate(self.continue_attempt())

    def test_multi_step_successor_resolves_base_and_intermediate_raw_ancestors(self):
        # Separate composed fixtures keep each archived raw ancestor independent.
        for intermediate in (False, True):
            with self.subTest(intermediate=intermediate):
                if hasattr(self, "reference"):
                    self.setUp()
                if intermediate:
                    self.transition()
                self.archive()
                self.transition(key="unit_stop_files", amount=7)
                self.transition(key="max_unit_retries")
                self.assert_nonaccepting_reconciliation()
                self.assert_fresh_candidate(self.continue_attempt())

    def test_tampered_lineage_tail_is_not_a_reconciliation(self):
        self.archive()
        current = self.transition()
        current["policy_lineage"]["steps"][-1]["digest"] = "a" * 64
        (self.p.root / POLICY).write_bytes(setup_bytes(current))
        self.assert_rejected()
        self.base.assert_blocked(self.base.report("guardrails"))

    def test_fork_does_not_resolve_an_archived_intermediate_policy(self):
        self.transition()
        self.archive()
        self.transition(raw=self.original_raw, amount=2)
        self.assert_rejected()

    def test_same_effective_ancestor_with_different_raw_bytes_is_rejected(self):
        self.archive()
        different_raw = setup_bytes(self.policy)
        self.assertNotEqual(self.original_raw, different_raw)
        self.assertEqual(json.loads(self.original_raw), json.loads(different_raw))
        self.transition(raw=different_raw)
        self.assert_rejected()

    def test_noncanonical_successor_serialization_is_rejected(self):
        self.archive()
        current = self.transition()
        (self.p.root / POLICY).write_text(json.dumps(current, indent=4) + "\n")
        self.assert_rejected()

    def test_unrelated_code_or_input_change_cannot_use_policy_exception(self):
        for path in ("src/alpha.txt", "config/synthetic.txt"):
            with self.subTest(path=path):
                if hasattr(self, "reference"):
                    self.setUp()
                self.archive()
                self.transition()
                self.p.write(path, "different preserved work\n")
                with self.assertRaises(ValueError):
                    self.continue_attempt()
                self.base.assert_blocked(self.base.report("guardrails"))
                # This test deliberately changes live work; archive bytes remain exact.
                for archived, raw in self.old_bytes.items():
                    self.assertEqual(raw, (self.p.root / archived).read_bytes())

    def test_policy_selection_or_path_change_is_rejected(self):
        for mutation in ("tree", "selection_details", "replacement_path", "policy_path"):
            with self.subTest(mutation=mutation):
                if hasattr(self, "reference"):
                    self.setUp()
                self.archive()
                self.transition()
                reviewed = self.reviewed()
                if mutation == "tree":
                    reviewed["execution_inputs"][POLICY] = {"mode": "tree"}
                elif mutation == "selection_details":
                    reviewed["execution_inputs"][POLICY] = {"mode": "file", "changed_selection": True}
                elif mutation == "replacement_path":
                    raw = (self.p.root / POLICY).read_bytes()
                    self.p.write("forge/other-policy.json", raw.decode())
                    del reviewed["execution_inputs"][POLICY]
                    reviewed["execution_inputs"]["forge/other-policy.json"] = {"mode": "file"}
                else:
                    self.m["evidence_storage"] = {"policy_path": "forge/other-policy.json"}
                    self.p.write("forge/other-policy.json", (self.p.root / POLICY).read_text())
                self.assert_rejected(reviewed)

    def test_unrelated_policy_identity_change_without_lineage_is_rejected(self):
        self.archive()
        changed = copy.deepcopy(self.policy)
        changed["retention"]["local_days"] += 1
        policies.validate_policy(changed)
        (self.p.root / POLICY).write_bytes(setup_bytes(changed))
        self.assert_rejected()
        self.base.assert_blocked(self.base.report("guardrails"))

    def test_borrowing_archived_check_under_new_run_cannot_complete(self):
        self.archive()
        self.transition()
        reviewed = self.reviewed()
        result = self.continue_attempt(reviewed)
        self.assert_fresh_candidate(result)
        self.m["unit_runs"]["U-1"].update(status="running", started_at=self.base.now(),
            development_plan_hash=self.p.hash("docs/development-plan.md"), approved_baseline_id="B-1")
        check = next(c for c in self.m["verification"]["checks"] if c["check_id"] == "QA-02")
        old = next(c for c in self.original_checks if c["check_id"] == "QA-02")
        check.clear()
        check.update(copy.deepcopy(old))
        check.update(execution_status="passed", run_id="synthetic-attempt-2", executed_at=self.base.now())
        check["runtime_observation_ref"] = self.helper.observe_runtime(
            self.p.root, {"runtime": [sys.executable, "--version"]})
        check["executed_at"] = self.base.now()
        self.m["unit_runs"]["U-1"].update(status="completed", completed_at=self.base.now())
        with self.assertRaises(ValueError):
            self.helper.capture_completion(self.p.root, self.m, "U-1", result["context_ref"],
                                           "synthetic-attempt-2", reviewed)
        self.base.assert_blocked(self.base.report("implementation", "complete", "U-1"))
        self.assert_original_preserved()

    def test_changed_acceptance_or_authority_is_rejected(self):
        for mutation in ("definition", "authority"):
            with self.subTest(mutation=mutation):
                if hasattr(self, "reference"):
                    self.setUp()
                self.archive()
                self.transition()
                if mutation == "definition":
                    path = "docs/qa-checklist.md"
                    self.p.write(path, (self.p.root / path).read_text().replace(
                        "## Checks\n", "## Checks\nNew mandatory acceptance requirement.\n"))
                    self.p.refresh()
                else:
                    self.m["implementation_gate"]["prompt_id"] = "unapproved-substitution"
                with self.assertRaises(ValueError):
                    self.continue_attempt()
                self.base.assert_blocked(self.base.report("guardrails"))
                self.assertEqual(self.original_checks, self.m["verification"]["checks"])
                for path, raw in self.old_bytes.items():
                    self.assertEqual(raw, (self.p.root / path).read_bytes())

    def test_fresh_review_probe_and_new_run_are_still_required(self):
        self.fixture.start()
        stale = self.fixture.continuation_inventory()
        self.reference = self.fixture.capture()
        self.helper = self.fixture.helper
        self.transition()
        with self.assertRaises(ValueError):
            self.continue_attempt(stale)
        reviewed = self.reviewed()
        with self.assertRaises(ValueError):
            self.continue_attempt(reviewed, run_id="synthetic-attempt-1")
        without_runtime = copy.deepcopy(reviewed)
        del without_runtime["runtime_observation_ref"]
        with self.assertRaises(ValueError):
            self.continue_attempt(without_runtime)
        reviewed["review"]["reviewed_at"] = "2020-01-01T00:00:00+00:00"
        with self.assertRaises(ValueError):
            self.continue_attempt(reviewed)

    def test_new_completion_requires_fresh_execution_and_runtime_gates(self):
        self.archive()
        self.transition()
        reviewed = self.reviewed()
        result = self.continue_attempt(reviewed)
        self.assert_fresh_candidate(result)
        self.m["unit_runs"]["U-1"].update(status="running", started_at=self.base.now(),
            development_plan_hash=self.p.hash("docs/development-plan.md"), approved_baseline_id="B-1")
        self.base.fixture.evidence("U-1", 4)
        self.base.stamp_evidence(self.helper, "U-1", reviewed)
        check = next(c for c in self.m["verification"]["checks"] if c["check_id"] == "QA-02")
        check["run_id"] = "synthetic-attempt-2"
        self.m["unit_runs"]["U-1"].update(status="completed", completed_at=self.base.now())
        with self.assertRaisesRegex(ValueError, "execution-time runtime observation"):
            self.helper.capture_completion(self.p.root, self.m, "U-1", result["context_ref"],
                                           "synthetic-attempt-2", reviewed)
        check["runtime_observation_ref"] = self.helper.observe_runtime(
            self.p.root, {"runtime": [sys.executable, "--version"]})
        check["executed_at"] = self.base.now()
        self.m["unit_runs"]["U-1"]["completed_at"] = self.base.now()
        completion = self.helper.capture_completion(self.p.root, self.m, "U-1", result["context_ref"],
                                                    "synthetic-attempt-2", reviewed)
        self.assertEqual("completed", self.base.read(completion)["run"]["status"])
        self.assert_original_preserved()


if __name__ == "__main__":
    unittest.main()
