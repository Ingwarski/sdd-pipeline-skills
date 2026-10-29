"""Continuation boundary regressions on isolated synthetic histories."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import test_attempt_policy_lineage as lineage
import test_per_check_reuse as reuse


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"


class ContinuationValidationTests(unittest.TestCase):
    def policy_case(self, version):
        case = lineage.AttemptPolicyLineageTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        if version == 3:
            # Construct a contract-3 original attempt through real capture APIs;
            # the shared older fixture's capture_alpha always selects contract 2.
            def capture_alpha(*, finish=True):
                self.assertFalse(finish)
                helper = case.base.history()
                case.m.update(checker_contract_version=3, unit_contract_version=3)
                inventory = case.base.inventory()
                context = helper.capture_context(case.p.root, case.m, "U-1", inventory)
                case.m.setdefault("execution_contexts", {})["U-1"] = context
                case.base.fixture.begin("U-1", 3)
                case.m["unit_runs"]["U-1"]["started_at"] = case.base.now()
                return helper, inventory, context, None
            case.base.capture_alpha = capture_alpha
        case.archive()
        return case

    def test_nonlineage_policy_change_blocks_continuation_in_both_contracts(self):
        for version in (2, 3):
            with self.subTest(version=version):
                case = self.policy_case(version)
                changed = copy.deepcopy(case.policy)
                changed["retention"]["local_days"] += 1
                lineage.policies.validate_policy(changed)
                (case.p.root / lineage.POLICY).write_bytes(lineage.setup_bytes(changed))
                with self.assertRaisesRegex(ValueError, "strict lineage successor"):
                    case.continue_attempt()
                case.assert_original_preserved()

    def test_contract_three_valid_successor_preserves_history_without_acceptance(self):
        case = self.policy_case(3)
        case.transition()
        case.assert_fresh_candidate(case.continue_attempt())

    def test_contract_three_tampered_successor_is_rejected(self):
        case = self.policy_case(3)
        current = case.transition()
        current["policy_lineage"]["steps"][-1]["digest"] = "a" * 64
        (case.p.root / lineage.POLICY).write_bytes(lineage.setup_bytes(current))
        with self.assertRaises(ValueError):
            case.continue_attempt()
        case.assert_original_preserved()

    def assert_blocked_cli(self, project, script, arguments):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / script), "--project", str(project), *arguments],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(1, result.returncode, result)
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("blocked", report["result"], report)
        self.assertIn("seal check is missing from the original attempt", result.stdout)

    def test_mismatched_seal_returns_structured_errors_from_both_clis(self):
        case = reuse.PerCheckReuseTests()
        case.setUp()
        self.addCleanup(case.doCleanups)

        def mismatch_seal():
            record = case.base.read(case.seal)
            record["check"]["check_id"] = "QA-NOT-IN-ATTEMPT"
            case.base.rewrite(case.seal, record)

        # Preserve the malformed producer output with its truthful content hash.
        case.start_and_seal(before_attempt=mismatch_seal)
        case.p.save()
        case.p.write("attempt-ref.json", json.dumps(case.attempt))
        case.p.write("inventory.json", json.dumps(case.inventory()))
        with self.subTest(cli="history"):
            self.assert_blocked_cli(case.p.root, "sdd_history.py", [
                "capture-continuation", "--unit", "U-1", "--attempt-ref", "attempt-ref.json",
                "--run-id", "synthetic-cli-continuation", "--inventory", "inventory.json"])

        candidate = case.resume(reuse=False)["manifest"]
        observation = copy.deepcopy(case.check)
        observation["reused_from"] = {"attempt_ref": copy.deepcopy(case.attempt),
                                      "seal_ref": copy.deepcopy(case.seal)}
        candidate["verification"]["checks"] = [
            observation if check["check_id"] == "QA-02" else check
            for check in candidate["verification"]["checks"]]
        case.m.clear()
        case.m.update(candidate)
        case.p.save()
        with self.subTest(cli="checker"):
            self.assert_blocked_cli(case.p.root, "sdd_check.py", ["--start-unit", "U-1"])


if __name__ == "__main__":
    unittest.main()
