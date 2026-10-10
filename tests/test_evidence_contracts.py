"""Cross-owner evidence contracts and conditional instruction accounting."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / "skills/to-sdd-pipeline/references"


class EvidenceContracts(unittest.TestCase):
    def test_qa_keeps_canonical_current_results_and_referenced_history(self):
        qa = (ROOT / "skills/to-qa-checklist/SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("run history within this same file", qa)
        self.assertIn("compact current results canonical", qa)
        self.assertIn("superseded run history through verified evidence references", qa)
        self.assertIn("original executor/time", qa)
        self.assertIn("storage migration never executes a check", qa)

    def test_external_payloads_do_not_relax_source_containment_or_authority(self):
        manifest = (REFS / "manifest-contract.md").read_text(encoding="utf-8")
        self.assertIn("Project-source paths, including resolved links, stay inside the project", manifest)
        for consumer in ("visual_target_ref", "source_manifest_ref", "codex_access_receipt_ref", "claude_source_read_receipt_ref", "source_inventory_ref"):
            self.assertIn(consumer, manifest)
        evidence = (REFS / "evidence-storage-contract.md").read_text(encoding="utf-8")
        for consumer in ("approval/browser/visual/promotion/prompt/sequencing receipts", "original whole-file hash/size", "no network or cache writes", "missing accounting"):
            self.assertIn(consumer, evidence)
        self.assertIn("separate implementation prompt", evidence)

    def test_storage_reference_load_is_conditional_and_counted(self):
        spec = importlib.util.spec_from_file_location("measure_tokens", ROOT / "scripts/measure_tokens.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        scenario = {"intake": False, "prototype_reuse": False, "claude_design": False}
        evidence_path = module.SHARED + "evidence-storage-contract.md"
        self.assertNotIn(evidence_path, dict(module.resource_loads("to-sdd-pipeline", scenario, None)))
        scenario["evidence_storage_consumers"] = ["to-sdd-pipeline"]
        self.assertIn(evidence_path, dict(module.resource_loads("to-sdd-pipeline", scenario, None)))
        self.assertNotIn(evidence_path, dict(module.resource_loads("to-qa-checklist", scenario, None)))
        scenarios = json.loads((ROOT / "tests/fixtures/token-scenarios.json").read_text())
        for value in scenarios.values():
            self.assertIn("to-sdd-pipeline", value["evidence_storage_consumers"])
            self.assertIn("not payloads", value["description"])

    def test_no_unnecessary_action_uploads_or_false_log_retention_claim(self):
        workflows = list((ROOT / ".github/workflows").glob("*.yml")) + list((ROOT / ".github/workflows").glob("*.yaml"))
        for path in workflows:
            text = path.read_text()
            for step in text.split("- uses:")[1:]:
                if "actions/upload-artifact@" in step.splitlines()[0]:
                    self.assertIn("retention-days: 30", step)
        readme = (ROOT / "README.md").read_text()
        self.assertIn("Workflow YAML does not configure log retention", readme)
        self.assertIn("never blanket-ignore `forge/` or `output/`", (REFS / "evidence-storage-contract.md").read_text())


if __name__ == "__main__":
    unittest.main()
