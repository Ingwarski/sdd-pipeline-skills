"""Exercise the native updater against local, independently versioned release channels."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from install_fixture import OFFICIAL, create_checkout, git, publish_snapshot


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="sdd-update-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.publisher = self.root / "publisher"
        self.remote = self.root / "remote.git"
        create_checkout(self.publisher)
        git(self.root, "clone", "--quiet", "--bare", str(self.publisher), str(self.remote))
        self.source = self.root / "checkout"
        git(self.root, "clone", "--quiet", str(self.remote), str(self.source))
        git(self.source, "remote", "set-url", "origin", OFFICIAL)
        self.codex = self.root / "personal" / "codex"
        self.claude = self.root / "personal" / "claude"
        personal = self.root / "personal"
        personal.mkdir()
        self.evidence = personal / "evidence"
        config = personal / ".gitconfig"
        self.old_url = "https://github.com/Ingwarski/codex-skills.git"
        for origin in (OFFICIAL, self.old_url):
            git(self.root, "config", "--file", str(config), "--add",
                "url." + self.remote.as_uri() + ".insteadOf", origin)
        self.trace = personal / "update.trace"
        isolated = {key: value for key, value in os.environ.items()
                    if not key.startswith(("GIT_", "SDD_", "CODEX_", "CLAUDE_"))}
        self.environment = dict(isolated, HOME=str(personal), USERPROFILE=str(personal),
                                LOCALAPPDATA=str(personal / "local"), APPDATA=str(personal / "roaming"),
                                SDD_EVIDENCE_HOME=str(self.evidence), SDD_SKILL_BACKUP_DIR=str(personal / "old-backups"),
                                CODEX_SKILLS_DIR=str(self.codex), CLAUDE_SKILLS_DIR=str(self.claude),
                                GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM="1",
                                GIT_ALLOW_PROTOCOL="file", GIT_TRACE=str(self.trace), PYTHONDONTWRITEBYTECODE="1")
        self.environment["SDD_TEST_UPDATER"] = str(self.source / "update.ps1")

    def update(self, *arguments, success=True):
        self.trace.unlink(missing_ok=True)
        if os.name == "nt":
            # Pass the flags to the native PowerShell parameter binder.
            flags = {"--all": "-All", "--codex": "-Codex", "--channel": "-Channel",
                     "--evidence-non-interactive": "-EvidenceNonInteractive"}
            # -Command supplies actual named parameters; string-array splatting
            # in a PS script would bind these flags as positional arguments.
            command = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                       "$ErrorActionPreference = 'Stop'; $script:LASTEXITCODE = 0; & $env:SDD_TEST_UPDATER " +
                       " ".join(flags.get(arg, arg) for arg in arguments) + "; exit $global:LASTEXITCODE"]
        else:
            command = ["/bin/bash", str(self.source / "update.sh"), *arguments]
        result = subprocess.run(command, env=self.environment, cwd=self.root, text=True, errors="replace",
                                capture_output=True, timeout=120)
        output = result.stdout + result.stderr
        self.assertEqual(success, result.returncode == 0, output)
        return output

    def head(self):
        return git(self.source, "rev-parse", "HEAD")

    def push(self, channel):
        git(self.publisher, "push", "--quiet", str(self.remote), "HEAD:refs/heads/" + channel)

    def assert_local_refusal(self, token):
        before = self.head()
        output = self.update("--codex", success=False)
        self.assertIn(token.lower(), output.lower())
        self.assertEqual(before, self.head())
        trace = self.trace.read_text(errors="replace") if self.trace.exists() else ""
        self.assertNotIn("git-upload-pack", trace, output)

    def test_update(self):
        # The initial remote has only main. Students request stable by default.
        before = self.head()
        self.update("--codex", success=False)
        self.assertIn("refs/heads/stable", self.trace.read_text(errors="replace"))
        self.assertEqual(before, self.head())
        self.assertFalse(self.codex.exists())

        # Mark the *new* installer so running stale code after fetch is observable.
        for name, line, hook in (
            ("install.sh", "if [[ $want_codex -eq 1 ]]; then\n  install_root", "printf '%s\\n' fresh-installer\n"),
            ("install.ps1", "if ($Codex) { Install-Root", "Write-Host 'fresh-installer'\n"),
        ):
            path = self.publisher / name
            script = path.read_text(encoding="utf-8")
            self.assertIn(line, script)
            path.write_text(script.replace(line, hook + line, 1), encoding="utf-8")
        publish_snapshot(self.publisher)
        self.push("main")
        self.push("stable")
        output = self.update("--codex")
        self.assertIn("fresh-installer", output)
        self.assertEqual(git(self.publisher, "rev-parse", "HEAD"), self.head())
        self.assertEqual((self.source / "skills/to-sdd-pipeline").resolve(), (self.codex / "to-sdd-pipeline").resolve())
        self.assertFalse(self.claude.exists())

        # An empty installer argument array selects both agents on Bash 3.2 too.
        self.update()
        self.assertEqual((self.source / "skills/to-sdd-pipeline").resolve(), (self.claude / "to-sdd-pipeline").resolve())
        old_link = self.codex / "to-sdd-pipeline"
        if old_link.is_symlink():
            old_link.unlink()
        else:
            old_link.rmdir()  # Windows directory junction
        for folder in (self.codex, self.claude):
            for name in ("communications-audit", "issue-happypro-certificate"):
                retired = folder / name
                retired.mkdir()
                (retired / "SKILL.md").write_text("Edited copy")
        output = self.update("--all")
        self.assertIn("permanently-deleted=4", output)
        self.assertTrue((old_link / "SKILL.md").is_file())
        for folder in (self.codex, self.claude):
            for name in ("communications-audit", "issue-happypro-certificate"):
                self.assertFalse((folder / name).exists())
        self.assertFalse(self.evidence.exists())

        retired = self.source / "skills" / "communications-audit"
        retired.mkdir()
        (retired / "SKILL.md").write_text("Old source copy")
        output = self.update("--all", "--evidence-non-interactive")
        self.assertIn("evidence storage setup is required", output.lower())
        self.assertFalse(retired.exists())
        self.assertEqual(b"", git(self.source, "status", "--porcelain"))
        self.assertTrue((self.evidence / "setup-status.json").is_file())

        user_work = self.source / "local.txt"
        user_work.write_text("user work")
        self.assert_local_refusal("local.txt")
        self.assertEqual("user work", user_work.read_text())
        user_work.unlink()
        git(self.source, "switch", "--quiet", "-c", "work-in-progress")
        self.assert_local_refusal("main")
        git(self.source, "switch", "--quiet", "main")
        git(self.source, "remote", "set-url", "origin", "https://github.com/someone/unrelated.git")
        self.assert_local_refusal("unrelated.git")
        git(self.source, "remote", "set-url", "origin", self.old_url)
        self.update("--codex")

        # Maintenance main may advance ahead of the tested channel.
        (self.publisher / "unverified.txt").write_text("unverified")
        publish_snapshot(self.publisher)
        self.push("main")
        self.update("--all")
        self.assertFalse((self.source / "unverified.txt").exists())
        self.update("--all", "--channel", "main")
        self.assertTrue((self.source / "unverified.txt").is_file())
        maintenance_head = self.head()
        self.update("--all", success=False)
        self.assertEqual(maintenance_head, self.head())
        self.assertTrue((self.source / "unverified.txt").is_file())

        # Unpublished personal commits remain intact and are refused before remote I/O.
        local = self.source / "local-commit.txt"
        local.write_text("work owned by the student")
        git(self.source, "add", "--", local.name)
        git(self.source, "-c", "user.name=Student", "-c", "user.email=student@example.invalid",
            "commit", "--quiet", "-m", "Student work")
        self.assert_local_refusal("origin")
        self.assertEqual("work owned by the student", local.read_text())
        git(self.source, "branch", "-m", "preserved-student-work")
        git(self.source, "switch", "--quiet", "-c", "main", maintenance_head.decode().strip())

        # A diverged stable branch also cannot replace this maintenance checkout.
        git(self.publisher, "switch", "--quiet", "-c", "other-release", "HEAD~1")
        (self.publisher / "upstream.txt").write_text("parallel change")
        publish_snapshot(self.publisher)
        self.push("stable")
        self.update("--codex", success=False)
        self.assertEqual(maintenance_head, self.head())
        self.assertFalse((self.source / "upstream.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
