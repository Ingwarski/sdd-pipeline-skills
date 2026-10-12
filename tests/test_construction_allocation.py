"""Construction allocation regressions using isolated, unimplemented fixtures."""

import copy
import json
import tempfile
import unittest

from test_sdd_check import Project


class ConstructionAllocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-construction-")
        self.addCleanup(self.temp.cleanup)
        self.p = Project(self.temp.name)
        self.m = self.p.manifest
        self.plan = self.m["unit_plan"]
        self.plan["order"] = ["U-1", "U-2"]
        self.plan["units"]["U-2"] = copy.deepcopy(self.plan["units"]["U-1"])
        self.plan["units"]["U-2"].update(
            scope="Integrated consumer", construction_dependencies=["U-1"],
            required_check_ids=["QA-01", "QA-03", "QA-04"])
        self.plan["units"]["U-1"].update(
            kind="implementation", scope="Bounded repository mechanism",
            implementation_paths=["src/model.txt"], required_check_ids=["QA-02"])
        for key, record in self.plan["acceptance"].items():
            record["owner_unit"] = "U-1" if key == "QA-02" else "U-2"
        self.plan["acceptance"]["QA-02"]["obligation_ids"] = ["FR-01"]
        check = self.check("QA-02")
        check["acceptance"].update(level="unit", evidence_mode="component",
                                   required_source_paths=["src/model.txt"])
        trace = self.m["artifacts"]["development-plan"]["traceability"]
        trace["definitions"].append({"id": "U-2", "kind": "unit", "required": True,
            "definition_ref": {"path": "docs/development-plan.md", "heading": "## Definition"}})
        for obligation in ("FR-01", "NFR-02", "STATE-01"):
            trace["links"].append({"from": "U-2", "to": obligation, "relation": "implements",
                "definition_ref": {"path": "docs/development-plan.md", "heading": "## Definition"}})
        path = "docs/development-plan.md"
        self.p.write(path, (self.p.root / path).read_text().replace("## Definition\n", "## Definition\nU-2\n"))
        self.m["artifacts"]["qa-checklist"]["traceability"]["links"].append({
            "from": "QA-02", "to": "FR-01", "relation": "verifies",
            "definition_ref": {"path": "docs/qa-checklist.md", "heading": "## Checks"}})
        self.heading = "## Construction Mechanisms"
        self.definition = {"version": 1, "mechanisms": {"M-STORE": {
            "required": True, "obligation_ids": ["FR-01"], "source_paths": ["src/model.txt"]}}}
        self.plan["construction_ref"] = {"path": "docs/architecture.md", "heading": self.heading}
        self.m["artifacts"]["architecture"]["construction_ref"] = copy.deepcopy(self.plan["construction_ref"])
        self.plan["construction"] = {"M-STORE": {"owner_unit": "U-1", "check_ids": ["QA-02"]}}
        self.architecture = (self.p.root / "docs/architecture.md").read_text()

    def check(self, key):
        return next(item for item in self.m["verification"]["checks"] if item["check_id"] == key)

    def sync(self):
        definition = "" if self.definition is None else "\n" + self.heading + "\n\n```json\n" + json.dumps(self.definition, ensure_ascii=False, indent=2) + "\n```\n"
        self.p.write("docs/architecture.md", self.architecture + definition)
        self.p.sync_unit_contract()

    def report(self):
        self.sync()
        return self.p.run(after=True)

    def blocked(self, fragment):
        report = self.report()
        self.assertEqual("blocked", report["result"], report)
        self.assertTrue(any("construction:" in issue["detail"] and fragment in issue["detail"]
                            for issue in report["issues"]), report)

    def test_valid_bounded_allocation_without_production_files(self):
        self.assertFalse((self.p.root / "src").exists())
        self.assertEqual("passed", self.report()["result"])

    def test_missing_required_mechanism_allocation_is_rejected(self):
        self.plan["construction"].clear()
        self.blocked("required mechanism has no allocation")

    def test_missing_mechanism_owner_is_rejected(self):
        del self.plan["construction"]["M-STORE"]["owner_unit"]
        self.blocked("no valid owner unit")

    def test_source_file_without_owning_unit_is_rejected(self):
        self.definition["mechanisms"]["M-STORE"]["source_paths"] = ["src/unowned-migration.txt"]
        self.blocked("source path is not owned")

    def test_integration_link_cannot_replace_constructor_clause_link(self):
        trace = self.m["artifacts"]["development-plan"]["traceability"]
        trace["links"] = [link for link in trace["links"] if (link["from"], link["to"]) != ("U-1", "FR-01")]
        self.plan["acceptance"]["QA-02"]["obligation_ids"] = []
        self.blocked("owner lacks implements link")

    def test_constructor_check_must_cover_its_clause(self):
        self.plan["acceptance"]["QA-02"]["obligation_ids"] = []
        self.blocked("checks omit a mechanism obligation")

    def test_check_owned_by_later_integration_unit_is_rejected(self):
        self.plan["construction"]["M-STORE"]["check_ids"] = ["QA-01"]
        self.blocked("check belongs to another unit")

    def test_check_source_inventory_must_cover_mechanism(self):
        self.check("QA-02")["acceptance"]["required_source_paths"] = ["src/other.txt"]
        self.blocked("checks omit a mechanism source path")

    def test_split_interface_responsibilities_can_have_distinct_owners(self):
        self.definition["mechanisms"]["M-CONSUMER"] = {
            "required": True, "obligation_ids": ["FR-01"], "source_paths": ["src/app.txt"]}
        self.plan["construction"]["M-CONSUMER"] = {"owner_unit": "U-2", "check_ids": ["QA-01"]}
        self.assertEqual("passed", self.report()["result"])

    def test_optional_mechanism_can_remain_unallocated(self):
        self.definition["mechanisms"]["M-STORE"]["required"] = False
        self.plan["construction"].clear()
        self.assertEqual("passed", self.report()["result"])

    def test_legacy_plan_without_new_fields_remains_compatible(self):
        del self.plan["construction_ref"], self.plan["construction"]
        del self.m["artifacts"]["architecture"]["construction_ref"]
        self.definition = None
        self.assertEqual("passed", self.report()["result"])

    def test_dropping_plan_fields_cannot_hide_declared_architecture_mechanisms(self):
        del self.plan["construction_ref"], self.plan["construction"]
        self.blocked("declared architecture requires")

    def test_dropping_all_metadata_cannot_hide_structured_architecture_declaration(self):
        del self.plan["construction_ref"], self.plan["construction"]
        del self.m["artifacts"]["architecture"]["construction_ref"]
        self.blocked("declared architecture mechanisms require")

    def test_plan_cannot_replace_the_architecture_owner_pointer(self):
        self.plan["construction_ref"]["heading"] = "## Other mechanisms"
        self.blocked("differs from the architecture owner's reference")

    def test_unrelated_legacy_json_and_prose_are_not_mechanism_declarations(self):
        del self.plan["construction_ref"], self.plan["construction"]
        del self.m["artifacts"]["architecture"]["construction_ref"]
        self.definition = None
        self.architecture += '\n## Design prose\nConstruction mechanisms remain prose.\n```json\n{"version": 1, "examples": []}\n```\n'
        self.assertEqual("passed", self.report()["result"])

    def test_quoted_nested_json_is_not_a_top_level_declaration(self):
        del self.plan["construction_ref"], self.plan["construction"]
        del self.m["artifacts"]["architecture"]["construction_ref"]
        quoted = json.dumps(self.definition)
        self.definition = None
        self.architecture += '\n````markdown\n```json\n' + quoted + '\n```\n````\n'
        self.assertEqual("passed", self.report()["result"])

    def test_partial_declaration_is_rejected(self):
        del self.plan["construction_ref"]
        self.blocked("requires construction_ref and construction together")

    def test_localized_owner_heading_is_resolved(self):
        self.heading = "## Механізми побудови"
        self.plan["construction_ref"]["heading"] = self.heading
        self.m["artifacts"]["architecture"]["construction_ref"]["heading"] = self.heading
        self.assertEqual("passed", self.report()["result"])

    def test_unknown_or_duplicate_mechanism_inventory_is_rejected(self):
        for field, value, fragment in (
            ("obligation_ids", ["FR-UNKNOWN"], "unknown/nonrequired obligation"),
            ("obligation_ids", ["FR-01", "FR-01"], "duplicate entries"),
            ("source_paths", [], "nonempty ID/path list"),
            ("source_paths", ["src/model.txt", "src/model.txt"], "duplicate entries"),
        ):
            with self.subTest(field=field, value=value):
                original = self.definition["mechanisms"]["M-STORE"][field]
                self.definition["mechanisms"]["M-STORE"][field] = value
                self.blocked(fragment)
                self.definition["mechanisms"]["M-STORE"][field] = original

    def test_architecture_must_be_canonical_owner(self):
        self.plan["construction_ref"]["path"] = "docs/prd.md"
        self.m["artifacts"]["architecture"]["construction_ref"]["path"] = "docs/prd.md"
        self.blocked("definitions belong to docs/architecture.md")

    def test_source_paths_cannot_escape_project_or_use_noncanonical_aliases(self):
        for path in ("../other.txt", "/outside.txt", "./src/model.txt"):
            with self.subTest(path=path):
                self.definition["mechanisms"]["M-STORE"]["source_paths"] = [path]
                report = self.report()
                self.assertEqual("blocked", report["result"], report)
                self.assertTrue(any("path" in issue["detail"] for issue in report["issues"]), report)


if __name__ == "__main__":
    unittest.main()
