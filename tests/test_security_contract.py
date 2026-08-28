"""Offline security-authoring reference and synthetic traceability regressions."""

import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_sdd_check import Project, sdd


ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / "skills/to-sdd-prd/scripts/asvs.py"
spec = importlib.util.spec_from_file_location("sdd_asvs", READER)
asvs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(asvs)


class CatalogTests(unittest.TestCase):
    def test_pinned_complete_catalog_and_correct_chapters(self):
        catalog = asvs.load_catalog()
        self.assertEqual(asvs.CATALOG_SHA256, sdd.ASVS_CATALOG_SHA256)
        chapters = {item["Shortcode"]: item["Name"] for item in catalog["Requirements"]}
        self.assertEqual(17, len(chapters))
        self.assertEqual("Authentication", chapters["V6"])
        self.assertEqual("Session Management", chapters["V7"])
        self.assertEqual("Authorization", chapters["V8"])
        self.assertEqual("Configuration", chapters["V13"])
        rows = asvs.requirements(catalog)
        self.assertEqual(345, len(rows))
        self.assertEqual(345, len({row["id"] for row in rows}))

    def test_levels_are_cumulative_and_selection_is_exact(self):
        catalog = asvs.load_catalog()
        self.assertEqual([70, 253, 345], [len(asvs.select(catalog, level=level)) for level in (1, 2, 3)])
        rows = asvs.select(catalog, chapters=["V6", "V8"], level=1)
        self.assertTrue(rows)
        self.assertTrue(all(row["level"] == 1 and row["chapter"] in ("V6", "V8") for row in rows))
        row, = asvs.select(catalog, ids=["v5.0.0-8.2.2"])
        self.assertEqual("V8", row["chapter"])
        for kwargs in ({"ids": ["8.2.2"]}, {"ids": ["v5.0.0-8.2.999"]}, {"chapters": ["V99"]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                asvs.select(catalog, **kwargs)

    def test_catalog_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="sdd-asvs-") as directory:
            path = Path(directory) / "altered.json"
            path.write_bytes(asvs.CATALOG.read_bytes().replace(b'"Version": "5.0.0"', b'"Version": "4.0.3"'))
            with self.assertRaisesRegex(ValueError, "pin"):
                asvs.load_catalog(path)

    def test_reader_works_from_unrelated_directory_without_writes(self):
        with tempfile.TemporaryDirectory(prefix="sdd-asvs-cwd-") as directory:
            result = subprocess.run([sys.executable, str(READER), "--chapters", "V8", "--level", "2"],
                                    cwd=directory, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("v5.0.0-8.2.2", result.stdout)
            self.assertEqual([], list(Path(directory).iterdir()))


class SecurityContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-security-")
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)
        self.m = self.project.manifest
        self.review = self.m["artifacts"]["prd"]["security_review"]
        self.gate = self.m["verification"]["gates"][-1]
        self.check = self.m["verification"]["checks"][-1]

    def assert_issue(self, code, report=None):
        report = report or self.project.run()
        self.assertIn(code, [item["code"] for item in report["issues"]], report)

    def test_security_assessment_is_required_after_prd_not_before(self):
        del self.m["artifacts"]["prd"]["security_review"]
        self.assertEqual("passed", self.project.run("prd")["result"])
        self.assert_issue("security_review_missing", self.project.run("prd", after=True))
        self.assert_issue("security_review_missing", self.project.run("project-context-bundle"))

    def test_profile_and_complete_assessment_are_not_optional(self):
        original = copy.deepcopy(self.review)
        for field, value, code in (("level", True, "security_profile"), ("level", 4, "security_profile"),
                                  ("scope", "unknown", "security_profile"), ("asvs_version", "4.0.3", "security_profile"),
                                  ("rationale", "", "security_profile"), ("status", "blocked", "security_review_incomplete"),
                                  ("requirements", [], "security_requirements")):
            with self.subTest(field=field, value=value):
                self.review.clear()
                self.review.update(copy.deepcopy(original))
                self.review[field] = value
                self.assert_issue(code)

    def test_nonweb_adaptation_cannot_claim_assurance_level(self):
        self.review.update(scope="adapted", level=None)
        self.assertEqual("passed", self.project.run()["result"])
        self.review["level"] = 2
        self.assert_issue("security_profile")

    def test_asvs_ids_must_be_real_versioned_and_in_prd(self):
        for value in (["v5.0.0-8.2.999"], ["8.2.2"], ["v5.0.0-6.2.1"], ["v5.0.0-8.2.2"] * 2, "v5.0.0-8.2.2"):
            with self.subTest(value=value):
                self.review["requirements"][0]["asvs_ids"] = value
                self.assert_issue("security_asvs_id")

    def test_supplemental_rules_need_canonical_rationale(self):
        requirement = self.review["requirements"][0]
        requirement["asvs_ids"] = []
        self.assert_issue("security_supplement")
        requirement["rationale"] = "deny cross-user data access"
        self.assertEqual("passed", self.project.run()["result"])

    def test_malformed_or_duplicate_requirements_fail_closed(self):
        self.review["requirements"].append(copy.deepcopy(self.review["requirements"][0]))
        self.assert_issue("security_requirements")
        self.review["requirements"] = [None]
        self.assert_issue("security_requirements")

    def test_catalog_unavailability_blocks_assessment(self):
        with patch.object(sdd, "ASVS_CATALOG", self.project.root / "missing-catalog.json"):
            self.assert_issue("security_catalog")

    def test_every_downstream_owner_retains_security_coverage(self):
        for owner in sdd.SECURITY_OWNERS:
            with self.subTest(owner=owner):
                entry = self.m["artifacts"][owner]
                original = entry.pop("security_coverage")
                self.assert_issue("security_coverage", self.project.run(owner, after=True))
                entry["security_coverage"] = original

    def test_coverage_references_cannot_point_to_another_owner(self):
        self.m["artifacts"]["architecture"]["security_coverage"]["NFR-02"] = self.review["requirements"][0]["definition_ref"]
        self.assert_issue("security_reference")

    def test_requirement_prefix_does_not_count_as_coverage(self):
        self.assertTrue(sdd.contains_id("NFR-02: protected", "NFR-02"))
        self.assertTrue(sdd.contains_id("Use v5.0.0-8.2.2.", "v5.0.0-8.2.2"))
        self.assertTrue(sdd.contains_id("See NFR-02.", "NFR-02"))
        self.assertFalse(sdd.contains_id("NFR-020: unrelated", "NFR-02"))
        self.assertFalse(sdd.contains_id("v5.0.0-1.2.10", "v5.0.0-1.2.1"))

    def test_missing_or_waived_security_gate_blocks(self):
        for field, value in (("active", False), ("required", False), ("applicability", "not_applicable")):
            with self.subTest(field=field):
                original = self.gate[field]
                self.gate[field] = value
                self.assert_issue("security_gate")
                self.gate[field] = original
        self.m["verification"]["gates"].pop()
        self.assert_issue("security_gate")

    def test_security_checks_cover_all_declared_requirements(self):
        self.check["security_requirement_ids"] = []
        self.assert_issue("security_check_coverage")
        self.check["security_requirement_ids"] = ["NFR-unknown"]
        self.assert_issue("security_check_coverage")
        self.check["security_requirement_ids"] = ["NFR-02"]
        self.gate["security_requirement_ids"] = []
        self.assert_issue("security_gate_coverage")

    def test_prototype_only_or_excluded_checks_cannot_satisfy_security(self):
        self.check["phase"] = "prototype"
        self.assert_issue("security_check_scope")
        self.check.update(phase="implementation", execution_status="not_applicable", rationale="Mockup looks fine")
        self.assert_issue("security_check_scope")

    def test_visual_evidence_is_not_security_evidence(self):
        self.project.execute_checks()
        self.check["evidence"][0]["kind"] = "visual"
        self.assert_issue("wrong_evidence_class")

    def test_planning_does_not_run_security_checks_and_release_requires_them(self):
        before = copy.deepcopy(self.m)
        self.assertEqual("passed", self.project.run()["result"])
        self.assertEqual(before, self.m)
        self.project.authorize()
        self.assertEqual("passed", self.project.run("implementation")["result"])
        self.assert_issue("required_check_incomplete", self.project.run("release"))
        self.project.execute_checks()
        self.assertEqual("passed", self.project.run("release")["result"])

    def test_new_security_obligation_invalidates_old_coverage(self):
        path = self.project.root / "docs/prd.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n### NFR-03\nNFR-03: enforce function permissions. v5.0.0-8.2.1\n", encoding="utf-8")
        self.review["requirements"].append({"requirement_id": "NFR-03", "asvs_ids": ["v5.0.0-8.2.1"],
            "definition_ref": {"path": "docs/prd.md", "heading": "### NFR-03"}})
        self.project.refresh(["prd"])
        report = self.project.run()
        self.assert_issue("security_coverage", report)
        self.assert_issue("security_gate_coverage", report)
        self.assert_issue("security_check_coverage", report)
        self.assert_issue("stale_source", report)

    def test_existing_assessment_migration_is_read_only(self):
        del self.m["artifacts"]["prd"]["security_review"]
        original = copy.deepcopy(self.m)
        files = {path: path.read_bytes() for path in self.project.root.rglob("*") if path.is_file()}
        self.assert_issue("security_review_missing")
        self.assertEqual(original, self.m)
        self.assertEqual(files, {path: path.read_bytes() for path in self.project.root.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
