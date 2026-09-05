"""Supported release boundaries are deliberate and periodically reviewed."""
from datetime import date
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimePolicyTests(unittest.TestCase):
    def test_maintained_boundaries_and_review_deadline(self):
        path = ROOT / "runtime-policy.json"
        self.assertTrue(path.is_file(), "Declare supported Python and its review deadline")
        policy = json.loads(path.read_text())
        self.assertGreaterEqual(tuple(map(int, policy["minimum_python"].split("."))), (3, 12))
        self.assertLess(date.today(), date.fromisoformat(policy["review_by"]), "Review current stable/support dates on python.org, then update policy and CI")
        workflow = (ROOT / ".github/workflows/installers.yml").read_text()
        self.assertIn("python: ['" + policy["minimum_python"] + "', '" + policy["recommended_python"] + "']", workflow)
        self.assertNotIn("python-version: '3.9'", workflow)
        self.assertNotIn("python-version: '3.11'", workflow)


if __name__ == "__main__":
    unittest.main()
