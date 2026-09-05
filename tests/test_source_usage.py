"""Owner-reviewed consumption, not proof of an agent's unreported reading."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from test_sdd_check import CONTRACT, Project, SCRIPT, sdd


class SourceUsageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="sdd-source-usage-")
        self.addCleanup(temp.cleanup)
        self.p = Project(temp.name)

    def assert_issue(self, code, after=False):
        report = self.p.run(after=after)
        self.assertEqual("blocked", report["result"], report)
        self.assertIn(code, {issue["code"] for issue in report["issues"]}, report)

    def test_legacy_omission_requires_owner_review(self):
        del self.p.manifest["artifacts"]["architecture"]["source_usage"]
        self.assert_issue("source_usage_missing")

    def test_context_cannot_be_silently_omitted(self):
        del self.p.manifest["artifacts"]["architecture"]["source_usage"]["docs/project-context.md"]
        self.assert_issue("source_decision_missing")

    def test_declared_context_fragment_needs_a_binding(self):
        self.p.manifest["artifacts"]["architecture"]["source_usage"]["docs/project-context.md"] = ["## Платформи"]
        self.assert_issue("unbound_consumed_source")

    def test_pending_malformed_and_ambiguous_usage_is_not_validated(self):
        entry = self.p.manifest["artifacts"]["architecture"]
        for decision in ({"review_required": True}, [], ["## Платформи", "## Платформи"], [1], ["Missing hashes"], None):
            with self.subTest(decision=decision):
                entry["source_usage"]["docs/project-context.md"] = decision
                self.assert_issue("invalid_source_usage")

    def test_declared_headings_must_exist_even_with_a_full_hash(self):
        entry = self.p.manifest["artifacts"]["architecture"]
        entry["source_usage"]["docs/project-context.md"] = ["## Missing section"]
        entry["source_hashes"]["docs/project-context.md"] = self.p.hash("docs/project-context.md")
        self.assert_issue("invalid_source_usage")

    def test_undeclared_fragment_is_rejected(self):
        path = self.p.root / "docs/project-context.md"
        entry = self.p.manifest["artifacts"]["architecture"]
        entry["source_usage"]["docs/project-context.md"] = ["## Примітки"]
        entry["consumed_source_fragments"] = {"docs/project-context.md": [
            {"heading": "## Примітки", "content_hash": sdd.digest(sdd.section_bytes(path, "## Примітки"))},
            {"heading": "## Платформи", "content_hash": sdd.digest(sdd.section_bytes(path, "## Платформи"))}]}
        self.assert_issue("unreviewed_source")

    def test_unused_source_needs_a_reason_and_cannot_be_bound(self):
        entry = self.p.manifest["artifacts"]["architecture"]
        entry["source_usage"]["docs/project-context.md"] = {"unused": " "}
        self.assert_issue("invalid_source_usage")
        entry["source_usage"]["docs/project-context.md"] = {"unused": "Not applied."}
        entry["source_hashes"]["docs/project-context.md"] = self.p.hash("docs/project-context.md")
        self.assert_issue("source_usage_conflict")

    def test_required_noncontext_input_cannot_be_waived(self):
        entry = self.p.manifest["artifacts"]["architecture"]
        entry["source_usage"]["docs/prd.md"] = {"unused": "Shortcut."}
        self.assert_issue("source_usage_conflict")

    def test_snapshot_without_review_is_not_a_consumption_claim(self):
        entry = self.p.manifest["artifacts"]["architecture"]
        entry["source_hashes"]["notes/source.md"] = self.p.evidence("notes/source.md", "Synthetic note")["content_hash"]
        self.assert_issue("unreviewed_source")

    def test_partial_qa_snapshot_cannot_omit_declared_shared_scope(self):
        path = self.p.root / "docs/qa-checklist.md"
        self.p.write("docs/qa-checklist.md", path.read_text(encoding="utf-8") + "\n## Shared scope\nS-01 keyboard and recovery evidence.\n")
        self.p.refresh(["qa-checklist"])
        self.p.manifest["verification"]["source_hashes"]["docs/qa-checklist.md"] = self.p.hash("docs/qa-checklist.md")
        entry = self.p.manifest["artifacts"]["development-plan"]
        del entry["source_hashes"]["docs/qa-checklist.md"]
        entry["source_usage"]["docs/qa-checklist.md"] = ["## Checks", "## Shared scope"]
        entry["consumed_source_fragments"] = {"docs/qa-checklist.md": [
            {"heading": "## Checks", "content_hash": sdd.digest(sdd.section_bytes(path, "## Checks"))}]}
        self.assert_issue("unbound_consumed_source", after=True)
        entry["consumed_source_fragments"]["docs/qa-checklist.md"].append(
            {"heading": "## Shared scope", "content_hash": sdd.digest(sdd.section_bytes(path, "## Shared scope"))})
        report = self.p.run(after=True)
        self.assertEqual("passed", report["result"], report)
        self.p.write("docs/qa-checklist.md", path.read_text(encoding="utf-8") + "## Execution results\nNot run.\n")
        self.p.refresh(["qa-checklist"])
        self.p.manifest["verification"]["source_hashes"]["docs/qa-checklist.md"] = self.p.hash("docs/qa-checklist.md")
        self.assertEqual("passed", self.p.run(after=True)["result"])
        self.p.write("docs/qa-checklist.md", path.read_text(encoding="utf-8").replace("keyboard and recovery", "screen-reader and recovery"))
        self.p.refresh(["qa-checklist"])
        self.p.manifest["verification"]["source_hashes"]["docs/qa-checklist.md"] = self.p.hash("docs/qa-checklist.md")
        self.assert_issue("stale_fragment", after=True)

    def test_only_consumed_context_changes_invalidate_the_consumer(self):
        path = self.p.root / "docs/project-context.md"
        entry = self.p.manifest["artifacts"]["architecture"]
        entry["source_usage"]["docs/project-context.md"] = ["## Платформи"]
        entry["consumed_source_fragments"] = {"docs/project-context.md": [
            {"heading": "## Платформи", "content_hash": sdd.digest(sdd.section_bytes(path, "## Платформи"))}]}
        self.p.write("docs/project-context.md", path.read_text(encoding="utf-8").replace("Опис для прикладу.", "Інші примітки."))
        self.p.refresh(CONTRACT["context_bundle"])
        self.assertEqual("passed", self.p.run()["result"])
        self.p.write("docs/project-context.md", path.read_text(encoding="utf-8").replace("Мобільна й настільна", "Лише настільна"))
        self.p.refresh(CONTRACT["context_bundle"])
        self.assert_issue("stale_fragment")

    def test_snapshot_exposes_unresolved_context_without_writing(self):
        self.p.save()
        original = (self.p.root / "forge/sdd-manifest.json").read_bytes()
        result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.p.root), "--snapshot", "architecture"], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual({"review_required": True}, record.get("source_usage", {}).get("docs/project-context.md"))
        self.assertEqual("unvalidated", record["status"])
        self.assertEqual(original, (self.p.root / "forge/sdd-manifest.json").read_bytes())

    def test_snapshot_hashes_selected_sections_and_explicit_unused_context(self):
        self.p.save()
        result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.p.root), "--snapshot", "architecture",
            "--consume", "docs/project-context.md### Платформи", "--unused", "docs/canonical-terms.md=No terminology applied."],
            capture_output=True, text=True, env={**os.environ, "PYTHONIOENCODING": "cp1252"})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(["## Платформи"], record["source_usage"]["docs/project-context.md"])
        self.assertEqual({"unused": "No terminology applied."}, record["source_usage"]["docs/canonical-terms.md"])
        self.assertEqual(sdd.digest(sdd.section_bytes(self.p.root / "docs/project-context.md", "## Платформи")), record["consumed_source_fragments"]["docs/project-context.md"][0]["content_hash"])
        self.assertNotIn("docs/project-context.md", record["source_hashes"])

    def test_localized_diagnostics_survive_non_utf8_output_pipes(self):
        self.p.manifest["artifacts"]["architecture"]["source_usage"]["notes/Примітки.md"] = "full"
        self.p.save()
        result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.p.root), "--before", "development-plan"],
            capture_output=True, text=True, env={**os.environ, "PYTHONIOENCODING": "cp1252"})
        self.assertEqual(1, result.returncode)
        issues = json.loads(result.stdout)["issues"]
        self.assertTrue(any(issue["code"] == "unbound_consumed_source" and "Примітки" in issue["detail"] for issue in issues), issues)

    def test_snapshot_rejects_conflicting_and_out_of_project_selections(self):
        checker = sdd.Checker(self.p.root, self.p.manifest)
        for consumed, unused in (
            (["../outside.md"], []),
            (["/etc/passwd"], []),
            (["docs/project-context.md", "docs/project-context.md### Платформи"], []),
            (["docs/project-context.md### Платформи"] * 2, []),
            (["docs/project-context.md"], ["docs/project-context.md=Not used"]),
            ([], ["docs/project-context.md= "]),
            ([], ["docs/prd.md=Skip"]),
        ):
            with self.subTest(consumed=consumed, unused=unused), self.assertRaises(ValueError):
                checker.source_proposal("architecture", consumed, unused)

    def test_consumption_flags_require_snapshot_mode(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.p.root), "--audit",
            "--consume", "docs/prd.md"], capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("require --snapshot", result.stderr)


if __name__ == "__main__":
    unittest.main()
