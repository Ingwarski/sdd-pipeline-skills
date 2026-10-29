"""A progress projection reuses only the current matching before-gate."""

import tempfile
import unittest
from unittest.mock import patch

from test_sdd_check import Project, sdd
from progress import workflow_progress


class ProgressReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-progress-reuse-")
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)
        self.project.authorize()
        self.project.manifest["next_ready_nodes"] = ["implementation"]

    def run_counted(self, node="implementation", **options):
        calls = []
        original = sdd.Checker._run

        def tracked(checker, selected, *args, **kwargs):
            calls.append(selected)
            return original(checker, selected, *args, **kwargs)

        with patch.object(sdd.Checker, "_run", tracked):
            report = sdd.Checker(self.project.root, self.project.manifest).run(node, **options)
        return report, calls

    def test_matching_gate_is_not_repeated_for_saved_progress(self):
        report, calls = self.run_counted()
        self.assertEqual("passed", report["result"], report)
        self.assertEqual(["implementation"], calls)

    def test_after_gate_still_probes_before_readiness(self):
        report, calls = self.run_counted(after=True)
        self.assertEqual("passed", report["result"], report)
        self.assertEqual(["implementation", "implementation"], calls)

    def test_unrelated_gate_cannot_supply_readiness(self):
        _, calls = self.run_counted(node="guardrails")
        self.assertEqual(["guardrails", "implementation"], calls)

    def test_stale_owner_still_receives_reconciliation_probe(self):
        path = self.project.root / "docs/prd.md"
        path.write_text(path.read_text() + "\nChanged requirement.\n")
        report, calls = self.run_counted()
        self.assertEqual("blocked", report["result"])
        self.assertEqual(["implementation", "prd"], calls)
        self.assertTrue(any(issue["code"] == "stale_progress" for issue in report["issues"]))

    def test_previous_run_is_not_a_cache_for_standalone_progress(self):
        checker = sdd.Checker(self.project.root, self.project.manifest)
        checker.run("implementation")
        path = self.project.root / "docs/prd.md"
        path.write_text(path.read_text() + "\nNew requirement after the gate.\n")
        report = workflow_progress(checker, _current_node="implementation")
        self.assertEqual("prd", report["progress"]["next_node"])


if __name__ == "__main__":
    unittest.main()
