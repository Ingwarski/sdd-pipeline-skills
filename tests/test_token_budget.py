import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("measure_tokens", ROOT / "scripts/measure_tokens.py")
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)


class BudgetTests(unittest.TestCase):
    def test_recent_regression_cannot_hide_under_old_baseline(self):
        self.assertTrue(hasattr(measure, "budget_errors"), "Need recent and absolute budget enforcement")
        report = {"entrypoints": {"before": 1000, "after": 500}, "readme": {"before": 900, "after": 400}, "scenarios": {}}
        recent = {"entrypoints": {"before": 450, "after": 500}, "readme": {"before": 390, "after": 400}, "scenarios": {}}
        policy = {"absolute": {"entrypoints": 600, "readme": 450}, "approved_growth_tokens": {"entrypoints": 20, "readme": 20}}
        self.assertEqual(["entrypoints: recent growth exceeds reviewed allowance"], measure.budget_errors(report, recent, policy))
        policy["absolute"]["readme"] = 300
        self.assertIn("readme: absolute budget exceeded", measure.budget_errors(report, recent, policy))


if __name__ == "__main__":
    unittest.main()
