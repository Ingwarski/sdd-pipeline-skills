"""Actual toolchain bytes, not a manually typed version label, identify a run."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_sdd_check import Project, SCRIPT, sdd


class CheckerProvenanceTests(unittest.TestCase):
    def test_identity_tracks_instruction_code_and_resource_changes_without_git(self):
        with tempfile.TemporaryDirectory(prefix="sdd-toolchain-") as directory:
            root = Path(directory)
            files = {"to-sdd-pipeline/SKILL.md": "Synthetic skill",
                     "to-sdd-pipeline/scripts/sdd_check.py": "# Synthetic checker",
                     "to-sdd-pipeline/references/pipeline-contract.json": '{"artifacts":{"plan":{"owner_skill":"to-development-plan"}}}',
                     "to-development-plan/SKILL.md": "Synthetic planner"}
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            original = sdd.toolchain_identity(root)
            self.assertEqual(4, original["source_file_count"])
            for name, content in files.items():
                with self.subTest(source=name):
                    (root / name).write_text(content + ("\n" if name.endswith(".json") else " changed"), encoding="utf-8")
                    changed = sdd.toolchain_identity(root)
                    self.assertNotEqual(original["skillset_sha256"], changed["skillset_sha256"])
                    self.assertEqual(name.endswith("sdd_check.py"), original["checker_sha256"] != changed["checker_sha256"])
                    (root / name).write_text(content, encoding="utf-8")
            cache = root / "to-sdd-pipeline/scripts/__pycache__/sdd_check.pyc"
            cache.parent.mkdir()
            cache.write_bytes(b"generated cache")
            (root / "to-sdd-pipeline/.DS_Store").write_bytes(b"finder data")
            unrelated = root / "unrelated-personal-skill/SKILL.md"
            unrelated.parent.mkdir()
            unrelated.write_text("Not part of the SDD collection", encoding="utf-8")
            self.assertEqual(original, sdd.toolchain_identity(root))
            (root / "to-development-plan/SKILL.md").unlink()
            with self.assertRaisesRegex(ValueError, "skill sources unavailable"):
                sdd.toolchain_identity(root)

    def test_cli_records_actual_identity_on_pass_and_block_without_changing_project(self):
        with tempfile.TemporaryDirectory(prefix="sdd-provenance-") as directory:
            project = Project(directory)
            before = {str(path): path.read_bytes() for path in project.root.rglob("*") if path.is_file()}
            for option in ("--after", "--before"):
                node = "development-plan" if option == "--after" else "implementation"
                result = subprocess.run([sys.executable, str(SCRIPT), "--project", directory, option, node], capture_output=True, text=True)
                self.assertEqual(0 if option == "--after" else 1, result.returncode, result.stdout + result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(sdd.toolchain_identity(), report["toolchain"])
                self.assertEqual(sdd.digest(SCRIPT.read_bytes()), report["toolchain"]["checker_sha256"])
            self.assertEqual(before, {str(path): path.read_bytes() for path in project.root.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
