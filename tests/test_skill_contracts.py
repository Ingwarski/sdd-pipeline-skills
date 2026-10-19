"""Packaged-resource and ownership checks, independent of the open project."""

import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sdd_contract_check", ROOT / "skills/to-sdd-pipeline/scripts/sdd_check.py")
sdd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdd)


class SkillContractTests(unittest.TestCase):
    def test_manifest_names_match_artifact_owners(self):
        manifest = json.loads((ROOT / "skills-manifest.json").read_text(encoding="utf-8"))
        names = {item["name"] for item in manifest["skills"]}
        contract = sdd.read_contract()
        owners = {item["owner_skill"] for item in contract["artifacts"].values()}
        self.assertEqual(names, owners | {"to-sdd-pipeline"})
        self.assertEqual(13, len(names))
        paths = [item["path"] for item in contract["artifacts"].values()]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual({"project-context", "canonical-terms"}, set(contract["context_bundle"]))
        for key in contract["context_bundle"]:
            self.assertEqual("to-project-context", contract["artifacts"][key]["owner_skill"])

    def test_reconciliation_nodes_inherit_owner_prerequisites(self):
        raw = sdd.read_json(sdd.CONTRACT)
        for owner in ("architecture", "dod-evals", "qa-checklist"):
            alias = raw["nodes"][owner + "-approved"]
            self.assertEqual(owner, alias["owner_artifact"])
            self.assertNotIn("required_before", alias)
        with tempfile.TemporaryDirectory(prefix="sdd-contract-") as directory:
            path = Path(directory) / "contract.json"
            raw["artifacts"]["architecture"]["required_before"].append("product-idea")
            path.write_text(json.dumps(raw), encoding="utf-8")
            with patch.object(sdd, "CONTRACT", path):
                contract = sdd.read_contract()
            self.assertEqual(contract["nodes"]["architecture"]["required_before"],
                             contract["nodes"]["architecture-approved"]["required_before"])
            self.assertIn("product-idea", contract["nodes"]["architecture-approved"]["required_before"])

    def test_later_lookups_are_not_required_inputs(self):
        contract = sdd.read_contract()
        sdd.validate_contract(contract)
        for owner, future in (("dod-evals", "qa-checklist"), ("qa-checklist", "development-plan")):
            self.assertIn(future, contract["artifacts"][owner]["consulted_later"])
            self.assertNotIn(future, contract["nodes"][owner]["required_before"])
        self.assertNotIn("design-brief", contract["nodes"]["wireframes"]["required_before"])

    def test_local_markdown_links_resolve(self):
        files = list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md")) + list((ROOT / "skills").rglob("*.md"))
        for path in files:
            text = path.read_text(encoding="utf-8")
            text = re.sub(r"(?ms)^```[^\n]*\n.*?^```\s*$", "", text)
            for link in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", text):
                link = link.strip("<>")
                if urlsplit(link).scheme or link.startswith("#"):
                    continue
                target = (path.parent / unquote(link.split("#", 1)[0])).resolve()
                with self.subTest(file=str(path.relative_to(ROOT)), link=link):
                    self.assertTrue(target.is_relative_to(ROOT), "packaged link leaves the repository")
                    self.assertTrue(target.is_file(), "missing linked resource: " + str(target))

    def test_agent_installation_guidance_is_consistent(self):
        self.assertEqual((ROOT / "AGENTS.md").read_bytes(), (ROOT / "CLAUDE.md").read_bytes())

    @unittest.skipUnless(importlib.util.find_spec("yaml"), "PyYAML is test-only; installed in the content CI job")
    def test_skill_frontmatter_with_real_yaml_parser(self):
        import yaml
        for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
            with self.subTest(skill=path.parent.name):
                text = path.read_text(encoding="utf-8")
                match = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.S)
                self.assertIsNotNone(match)
                metadata = yaml.safe_load(match[1])
                self.assertEqual(path.parent.name, metadata["name"])
                self.assertIsInstance(metadata["description"], str)
                self.assertTrue(metadata["description"].strip())
                self.assertLessEqual(len(text.splitlines()), 500)


if __name__ == "__main__":
    unittest.main()
