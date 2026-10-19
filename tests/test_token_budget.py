"""Instruction budgets remain enforceable in a source-only, one-commit export."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("measure_tokens", ROOT / "scripts/measure_tokens.py")
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)
try:
    import tiktoken
except ImportError:
    tiktoken = None


class BudgetTests(unittest.TestCase):
    def test_pipeline_accounts_for_setup_and_generated_policy_reads(self):
        scenario = {"intake": False, "claude_design": False, "prototype_reuse": False}
        paths = [path for path, _ in measure.resource_loads("to-sdd-pipeline", scenario)]
        for suffix in ("references/project-instructions.md", "references/host-instruction-loading.md", "assets/project-AGENTS.md"):
            self.assertIn("skills/to-sdd-pipeline/" + suffix, paths)
        self.assertEqual(len(paths), len(set(paths)))

    def test_current_history_reads_cover_all_fixed_workflows_without_duplicates(self):
        scenarios = measure.scenarios_from_disk()
        resource = "skills/to-sdd-pipeline/references/completion-preservation.md"
        for name, scenario in scenarios.items():
            for owner in measure.HISTORY_CONSUMERS:
                with self.subTest(scenario=name, owner=owner):
                    paths = [path for path, _ in measure.resource_loads(owner, scenario)]
                    self.assertEqual(1, paths.count(resource))
                    self.assertEqual(len(paths), len(set(paths)))

    def test_every_conditional_resource_is_counted_only_for_its_scenario(self):
        plain = {"intake": False, "claude_design": False, "prototype_reuse": False}
        cases = (
            ("intake", True, "to-sdd-pipeline", measure.SHARED + "intake-adapter.md"),
            ("claude_design", True, "to-sdd-pipeline", measure.SHARED + "claude-design-handoff.md"),
            ("prototype_reuse", True, "to-development-plan", "skills/to-development-plan/references/prototype-promotion.md"),
            ("approved_decision_correction", True, "to-development-plan", measure.SHARED + "authorization-corrections.md"),
            ("evidence_storage_consumers", ["to-sdd-pipeline"], "to-sdd-pipeline", measure.SHARED + "evidence-storage-contract.md"),
        )
        for flag, value, skill, path in cases:
            with self.subTest(flag=flag, skill=skill):
                self.assertNotIn(path, dict(measure.resource_loads(skill, plain)))
                loaded = dict(measure.resource_loads(skill, {**plain, flag: value}))
                self.assertIn(path, loaded)

    def test_missing_required_resource_fails_instead_of_reducing_cost(self):
        scenario = {"intake": False, "claude_design": False, "prototype_reuse": False}
        with patch.object(measure, "read_version", return_value=None):
            with self.assertRaisesRegex(ValueError, "required instruction resource missing"):
                measure.resource_loads("to-sdd-pipeline", scenario)

    def test_historical_git_reads_are_not_a_fallback(self):
        with self.assertRaisesRegex(ValueError, "Historical Git reads are unsupported"):
            measure.read_version("README.md", "old-revision")

    def test_recent_regression_cannot_hide_under_initial_baseline(self):
        report = {"entrypoints": {"before": 1000, "after": 500}, "readme": {"before": 900, "after": 400}, "scenarios": {}}
        recent = {"totals": {"entrypoints": 450, "readme": 390}}
        policy = {"absolute": {"entrypoints": 600, "readme": 450}, "approved_growth_tokens": {"entrypoints": 20, "readme": 20}}
        self.assertEqual(["entrypoints: recent growth exceeds reviewed allowance"], measure.budget_errors(report, recent, policy))
        policy["absolute"]["readme"] = 300
        self.assertIn("readme: absolute budget exceeded", measure.budget_errors(report, recent, policy))
        policy["absolute"]["extra"] = 10
        self.assertIn("budget metric coverage differs from measured workflows", measure.budget_errors(report, recent, policy))


@unittest.skipUnless(tiktoken, "tokenizer is a test-only dependency")
class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoding = tiktoken.get_encoding("o200k_base")
        cls.snapshot = measure.make_snapshot(cls.encoding)

    def test_snapshot_records_every_invocation_and_retry_without_source_copies(self):
        snapshot = self.snapshot
        measure.validate_snapshot(snapshot, measure.scenarios_from_disk(), self.encoding)
        self.assertEqual(5, len(snapshot["scenario_loads"]))
        for name, scenario in measure.scenarios_from_disk().items():
            value = snapshot["scenario_loads"][name]
            self.assertEqual(scenario["invocations"], [load["skill"] for load in value["loads"]])
            self.assertEqual(scenario["retries"], value["retries_included"])
            self.assertEqual(snapshot["totals"][name], sum(load["tokens"] for load in value["loads"]))
        self.assertTrue(all(set(value) == {"tokens", "sha256"} for value in snapshot["resources"].values()))

    def test_changed_seeds_invocations_retries_and_conditions_require_review(self):
        original = measure.scenarios_from_disk()
        for key, value in (("seed", "Shorter prompt"), ("invocations", ["to-sdd-pipeline"]),
                           ("retries", 0), ("intake", False)):
            changed = copy.deepcopy(original)
            changed["first_setup_with_retry"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "scenario definitions changed"):
                measure.validate_snapshot(self.snapshot, changed, self.encoding)

    def test_baseline_checksum_and_internal_totals_are_verified(self):
        snapshot = copy.deepcopy(self.snapshot)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            reference = {"path": path.name, "sha256": measure.canonical_hash(snapshot)}
            self.assertEqual(snapshot, measure.load_baseline(reference, path.parent, self.encoding))
            snapshot["totals"]["entrypoints"] += 1
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                measure.load_baseline(reference, path.parent, self.encoding)
            reference["sha256"] = measure.canonical_hash(snapshot)
            with self.assertRaisesRegex(ValueError, "entrypoint total is inconsistent"):
                measure.load_baseline(reference, path.parent, self.encoding)

    def test_tokenizer_and_method_changes_require_remeasurement(self):
        for key, value, expected in (("method_version", "unknown", "measurement method"),
                                     ("encoding", "other", "tokenizer differs"),
                                     ("tokenizer", {"package": "tiktoken", "version": "0.0.0"}, "tokenizer differs")):
            changed = copy.deepcopy(self.snapshot)
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, expected):
                measure.validate_snapshot(changed, measure.scenarios_from_disk(), self.encoding)

    def test_measurement_and_comparison_work_without_a_git_checkout(self):
        # Copy only the current resources needed by the estimator, with no .git directory.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in self.snapshot["resources"]:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / relative).read_bytes())
            scenarios = root / "tests/fixtures/token-scenarios.json"
            scenarios.parent.mkdir(parents=True, exist_ok=True)
            scenarios.write_bytes((ROOT / "tests/fixtures/token-scenarios.json").read_bytes())
            with patch.object(measure, "ROOT", root):
                current = measure.measure_current(self.encoding)
                report = measure.build_report(self.snapshot, current)
            self.assertFalse((root / ".git").exists())
            self.assertEqual(self.snapshot["totals"], current["totals"])
            self.assertTrue(all(value["growth_tokens"] == 0 for value in report["scenarios"].values()))
            policy = {"absolute": current["totals"], "approved_growth_tokens": dict.fromkeys(current["totals"], 0)}
            self.assertEqual([], measure.budget_errors(report, self.snapshot, policy))


if __name__ == "__main__":
    unittest.main()
