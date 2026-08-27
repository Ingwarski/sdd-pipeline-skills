"""Exercise the real platform installer in isolated clones and installation roots."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallerInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-input-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clone = self.root / "Skills with spaces"
        self.clone.mkdir()
        for directory in ("scripts", "skills"):
            shutil.copytree(ROOT / directory, self.clone / directory, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("install.sh", "install.ps1", "skills-manifest.json", "retired-skills.txt"):
            shutil.copy2(ROOT / name, self.clone / name)
        self.dest = self.root / "agent-skills"
        self.dest.mkdir()
        self.retired = self.dest / "communications-audit"
        self.retired.mkdir()
        (self.retired / "marker.txt").write_text("Synthetic retired copy.\n", encoding="utf-8")
        self.manifest = json.loads((self.clone / "skills-manifest.json").read_text(encoding="utf-8"))
        self.unrelated_project = self.root / "unrelated-project"
        self.unrelated_project.mkdir()

    def write_manifest(self, manifest=None, **kwargs):
        (self.clone / "skills-manifest.json").write_text(json.dumps(manifest or self.manifest, **kwargs), encoding="utf-8")

    def install(self, repair=False, environment=None):
        if os.name == "nt":
            command = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                       str(self.clone / "install.ps1"), "-Codex", "-CodexDir", str(self.dest)]
            if repair:
                command.append("-Repair")
        else:
            command = ["/bin/bash", str(self.clone / "install.sh"), "--codex", "--codex-dir", str(self.dest)]
            if repair:
                command.append("--repair")
        return subprocess.run(command, cwd=self.unrelated_project, env=environment, capture_output=True, text=True, timeout=60)

    def assert_failed_without_mutation(self, result):
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue((self.retired / "marker.txt").is_file(), result.stdout + result.stderr)
        self.assertEqual(["communications-audit"], sorted(p.name for p in self.dest.iterdir()))

    def test_compact_reordered_and_crlf_json(self):
        value = {"skills": [{"legacy_name": entry["legacy_name"], "path": entry["path"], "name": entry["name"]} for entry in self.manifest["skills"]],
                 "skill_count": 13, "skill_set": "sdd-pipeline", "schema_version": 1}
        for compact in (True, False):
            with self.subTest(compact=compact):
                text = json.dumps(value, separators=(",", ":")) if compact else json.dumps(value, indent=4).replace("\n", "\r\n")
                (self.clone / "skills-manifest.json").write_bytes(text.encode("utf-8"))
                result = self.install()
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertFalse(self.retired.exists())
                for entry in value["skills"]:
                    self.assertEqual((self.clone / entry["path"] / "SKILL.md").read_bytes(), (self.dest / entry["name"] / "SKILL.md").read_bytes())

    def test_invalid_manifest_variants_fail_before_cleanup(self):
        variants = []
        for field, value in (("schema_version", 2), ("schema_version", True), ("skill_count", 12), ("skill_set", "custom-agent-skills")):
            data = copy.deepcopy(self.manifest)
            data[field] = value
            variants.append((field + str(value), data))
        for field, value in (("path", "skills/../outside"), ("path", "/tmp/outside"), ("name", "to-prd"), ("name", "to-sdd-prd"), ("legacy_name", "unrelated-skill")):
            data = copy.deepcopy(self.manifest)
            data["skills"][0][field] = value
            variants.append((field + value, data))
        for label, data in variants:
            with self.subTest(label=label):
                self.write_manifest(data)
                self.assert_failed_without_mutation(self.install())

    def test_duplicate_keys_are_rejected_by_both_platforms(self):
        text = json.dumps(self.manifest).replace('"schema_version": 1', '"schema_version": 2, "schema_version": 1')
        (self.clone / "skills-manifest.json").write_text(text, encoding="utf-8")
        self.assert_failed_without_mutation(self.install())

    def test_missing_shared_reference_stops_before_mutation(self):
        (self.clone / "skills/to-sdd-pipeline/references/common-contract.md").unlink()
        self.assert_failed_without_mutation(self.install())

    def test_invalid_frontmatter_stops_before_mutation(self):
        (self.clone / "skills/to-wireframes/SKILL.md").write_text("# Not a valid skill\n", encoding="utf-8")
        self.assert_failed_without_mutation(self.install())

    def test_missing_python_stops_before_mutation(self):
        fake_bin = self.root / "no-python"
        fake_bin.mkdir()
        for name in ("python3", "python", "py"):
            path = fake_bin / (name + ".cmd" if os.name == "nt" else name)
            path.write_text("@exit /b 1\r\n" if os.name == "nt" else "#!/bin/sh\nexit 1\n", encoding="utf-8")
            path.chmod(0o755)
        environment = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
        self.assert_failed_without_mutation(self.install(environment=environment))

    def test_source_relative_references_survive_move_and_repair(self):
        result = self.install()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.clone = Path(shutil.move(str(self.clone), str(self.root / "Renamed skills repository")))
        result = self.install(repair=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        for name in ("to-guardrails", "to-wireframes", "to-design-brief", "to-dod-evals", "to-qa-checklist", "to-development-plan"):
            directory = (self.dest / name).resolve()
            reference = (directory / "../to-sdd-pipeline/references/heuristic-usability-review.md").resolve()
            self.assertEqual((self.clone / "skills/to-sdd-pipeline/references/heuristic-usability-review.md").resolve(), reference)
            self.assertIn("H1-H10", reference.read_text(encoding="utf-8"))
        before = {entry["name"]: (self.dest / entry["name"]).resolve() for entry in self.manifest["skills"]}
        self.assertEqual(0, self.install().returncode)
        self.assertEqual(before, {entry["name"]: (self.dest / entry["name"]).resolve() for entry in self.manifest["skills"]})


if __name__ == "__main__":
    unittest.main()
