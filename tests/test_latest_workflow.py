"""Current operational records with read-only support for legacy import/history.

These isolated synthetic fixtures test CLI boundaries, not product acceptance.
"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest

from test_sdd_check import CONTRACT, Project, SCRIPT, sdd


class LatestWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-latest-workflow-")
        self.addCleanup(self.temp.cleanup)
        self.p = Project(self.temp.name)
        self.m = self.p.manifest

    def files(self):
        return {str(path.relative_to(self.p.root)): path.read_bytes()
                for path in self.p.root.rglob("*") if path.is_file()}

    def cli(self, *arguments):
        self.p.save()
        before = self.files()
        result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.p.root),
                                 *arguments], capture_output=True, text=True)
        self.assertTrue(result.stdout.strip(), result.stderr)
        self.assertEqual(before, self.files(), "read-only checks must preserve all project files")
        return result, json.loads(result.stdout)

    def test_legacy_cli_requires_migration_at_every_operational_boundary(self):
        self.p.authorize()
        original = copy.deepcopy(self.m)
        for arguments in (("--before", "product-idea"), ("--before", "implementation"),
                          ("--after", "development-plan"), ("--start-unit", "U-1"),
                          ("--complete-unit", "U-1"), ("--audit",), ("--before", "release")):
            with self.subTest(arguments=arguments):
                self.m.clear()
                self.m.update(copy.deepcopy(original))
                if arguments[0] == "--complete-unit" or "release" in arguments:
                    self.p.execute_checks()
                result, report = self.cli(*arguments)
                self.assertEqual(2, result.returncode, report)
                self.assertEqual("migration_required", report["result"])
                self.assertEqual({"migration_required"}, {issue["code"] for issue in report["issues"]})
                self.assertEqual([{"id": "preserve-me"}], self.m["history"])

    def test_incomplete_legacy_versions_require_owner_review_on_early_resume(self):
        for omitted in (("unit_contract_version",), ("checker_contract_version",),
                        ("checker_contract_version", "unit_contract_version")):
            with self.subTest(omitted=omitted):
                self.m.update(checker_contract_version=1, unit_contract_version=1)
                for key in omitted:
                    del self.m[key]
                result, report = self.cli("--before", "product-idea")
                self.assertEqual(2, result.returncode, report)
                self.assertEqual("migration_required", report["result"])

    def test_legacy_validation_remains_available_for_import_and_frozen_history(self):
        original = copy.deepcopy(self.m)
        self.assertEqual("passed", sdd.Checker(self.p.root, self.m).run("development-plan", after=True)["result"])
        report = sdd.Checker(self.p.root, self.m).run("development-plan", after=True, require_current=True)
        self.assertEqual("migration_required", report["result"])
        self.assertEqual(original, self.m)

    def test_migration_requirement_does_not_hide_existing_diagnostics(self):
        self.p.write("docs/architecture.md", "Changed without owner validation.\n")
        result, report = self.cli("--before", "development-plan")
        self.assertEqual(1, result.returncode, report)
        self.assertEqual("blocked", report["result"])
        self.assertIn("migration_required", {issue["code"] for issue in report["issues"]})
        self.assertIn("stale_artifact", {issue["code"] for issue in report["issues"]})

    def test_current_planning_does_not_require_or_invent_implementation_authority(self):
        self.m.update(checker_contract_version=2, unit_contract_version=2)
        original = copy.deepcopy(self.m)
        for node in list(CONTRACT["artifacts"]) + ["project-context-bundle", "architecture-approved",
                                                  "dod-evals-approved", "qa-checklist-approved"]:
            with self.subTest(node=node):
                result, report = self.cli("--after", node)
                self.assertEqual(0, result.returncode, report)
                self.assertEqual("passed", report["result"])
                self.assertEqual("not_authorized", report["execution_authority"]["status"])
        self.assertEqual(original, self.m)
        self.assertEqual(1, self.m["traceability_version"], "traceability uses its own version")
        result, report = self.cli("--start-unit", "U-1")
        self.assertEqual(1, result.returncode, report)
        self.assertIn("implementation_not_authorized", {issue["code"] for issue in report["issues"]})

    def test_current_intake_does_not_require_a_future_plan(self):
        self.m.clear()
        self.m.update(checker_contract_version=2, unit_contract_version=2, traceability_version=1,
                      language={"working_language": "en", "artifact_language": "en"}, artifacts={})
        result, report = self.cli("--before", "product-idea")
        self.assertEqual(0, result.returncode, report)
        self.assertNotIn("implementation_gate", self.m)
        self.assertNotIn("unit_plan", self.m)
        self.assertEqual("not_authorized", report["execution_authority"]["status"])

    def test_mixed_future_and_malformed_versions_fail_closed(self):
        for checker_version, unit_version in ((1, 2), (2, 1), (4, 4), (2, 3), (3, 2),
                                               (True, 1), (1, True), ("2", "2"),
                                               (2.0, 2), (2, 2.0), ({}, 1), (2, None)):
            with self.subTest(checker=checker_version, units=unit_version):
                self.m.update(checker_contract_version=checker_version, unit_contract_version=unit_version)
                result, report = self.cli("--before", "product-idea")
                self.assertEqual(1, result.returncode, report)
                self.assertEqual("blocked", report["result"])
                self.assertIn("unsupported_contract_version", {issue["code"] for issue in report["issues"]})

    def test_hash_and_snapshot_remain_unvalidated_read_only_migration_tools(self):
        result, proposal = self.cli("--snapshot", "development-plan")
        self.assertEqual(0, result.returncode, proposal)
        self.assertEqual("unvalidated", proposal["status"])
        self.assertNotIn("execution_authority", proposal)
        before = self.files()
        result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.p.root),
                                 "--hash", "docs/development-plan.md"], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(self.p.hash("docs/development-plan.md"), result.stdout.strip())
        self.assertEqual(before, self.files())


if __name__ == "__main__":
    unittest.main()
