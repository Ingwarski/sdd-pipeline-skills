"""Exercise the release entry point and native installers against a local Git transport."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = "https://github.com/Ingwarski/sdd-pipeline-skills.git"
WINDOWS = os.name == "nt"


def inventory(root, exclude=()):
    """Include Git metadata, empty dirs, ignored files and link objects without following links."""
    entries = {}

    def visit(path):
        if path in exclude:
            return
        info = path.lstat()
        metadata = (info.st_mode, info.st_mtime_ns, info.st_ino)
        if path.is_symlink() or os.path.isjunction(path):
            value = os.readlink(path)
        elif stat.S_ISDIR(info.st_mode):
            value = None
            for child in path.iterdir():
                visit(child)
        else:
            with path.open("rb") as stream:
                value = hashlib.file_digest(stream, "sha256").hexdigest()
        entries[path.relative_to(root)] = (*metadata, value)

    visit(root)
    return entries


class InstallationLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-location-")
        self.addCleanup(self.temp.cleanup)
        temp = Path(self.temp.name).resolve()
        self.client = temp / "client"
        self.home = self.client / "personal home"
        self.projects = self.client / "Projects"
        self.product = self.projects / "Student product"
        self.destination = self.projects / "SDD Skills"
        self.codex = self.home / ".agents/skills"
        self.claude = self.home / ".claude/skills"
        for directory in (self.product, self.codex, self.claude):
            directory.mkdir(parents=True)
        self.env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("GIT_", "SDD_", "CODEX_", "CLAUDE_", "PYTHON"))
        }
        self.env.update(
            HOME=str(self.home), USERPROFILE=str(self.home),
            GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(temp / "gitconfig"),
            GIT_ALLOW_PROTOCOL="file", GIT_TERMINAL_PROMPT="0",
            PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
        )
        if WINDOWS:
            self.env.update(HOMEDRIVE=self.home.drive, HOMEPATH=str(self.home)[2:],
                            APPDATA=str(temp / "appdata"), LOCALAPPDATA=str(temp / "localappdata"))
        # Keep the publisher, the downloaded one-file entry point, and its Git config
        # outside the inventoried client. No caller credential or external remote is used.
        self.remote = temp / "publisher.git"
        self.git("clone", "--quiet", "--bare", "--single-branch", "--no-tags", "--no-local", str(ROOT), str(self.remote))
        self.sha = self.git("--git-dir", str(self.remote), "rev-parse", "HEAD")
        self.publish(self.sha)
        self.git("config", "--global", "url." + self.remote.as_uri() + ".insteadOf", OFFICIAL)
        self.bootstrap_script = temp / "install_location.py"
        self.bootstrap_script.write_bytes(subprocess.check_output(
            ["git", "--git-dir", str(self.remote), "show", self.sha + ":scripts/install_location.py"],
            env=self.env,
        ))
        self.git("init", "--quiet", "--initial-branch=main", str(self.product))
        (self.product / "README.md").write_text("Product owned by a student.\n")
        self.git("-C", str(self.product), "add", "README.md")
        self.git("-C", str(self.product), "-c", "user.name=Student", "-c", "user.email=s@example.invalid",
                 "-c", "commit.gpgSign=false", "commit", "--quiet", "-m", "Product")
        (self.product / "README.md").write_text("Work in progress.\n")
        (self.product / ".private").write_bytes(b"hidden untracked data\x00")
        (self.product / "untracked.txt").write_bytes(b"keep local work\n")
        for directory in (self.codex, self.claude):
            (directory / ".unrelated").write_bytes(b"unrelated registration data\n")
            retired = directory / "communications-audit"
            retired.mkdir()
            (retired / ".student-file").write_bytes(b"retirement sentinel\n")

    def publish(self, sha):
        for branch in ("main", "stable"):
            self.git("--git-dir", str(self.remote), "update-ref", f"refs/heads/{branch}", sha)
        self.git("--git-dir", str(self.remote), "symbolic-ref", "HEAD", "refs/heads/main")

    def run_client(self, args, **env):
        return subprocess.run(
            [str(a) for a in args], cwd=self.product, env={**self.env, **env},
            input="\n", capture_output=True, text=True, errors="replace", timeout=120,
        )

    def git(self, *args):
        result = self.run_client(["git", *args])
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def bootstrap(self, destination=None, *, operation="bootstrap", revision=None, extra=(), **env):
        return self.run_client([sys.executable, "-B", self.bootstrap_script, operation, "--destination",
                                destination or self.destination, "--revision", revision or self.sha,
                                "--channel", "stable", *extra], **env)

    def clone(self, destination=None):
        self.git("clone", "--quiet", "--branch", "main", OFFICIAL, str(destination or self.destination))

    def link_directory(self, alias, target):
        if WINDOWS:
            result = self.run_client(["cmd.exe", "/d", "/c", "mklink", "/j", alias, target])
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            alias.symlink_to(target, target_is_directory=True)

    def native(self, operation, *options, source=None, **env):
        source = source or self.destination
        if WINDOWS:
            flags = {
                "--repair": "-Repair", "--claude-dir": "-ClaudeDir", "--codex-dir": "-CodexDir",
                "--retire-only": "-RetireOnly", "--evidence-non-interactive": "-EvidenceNonInteractive",
            }
            options = [flags.get(option, option) for option in options]
        if operation.endswith("-launcher"):
            action = operation.split("-")[0].title()
            script = source / (action + (" Skills.cmd" if WINDOWS else " Skills.command"))
            args = ["cmd.exe", "/d", "/c", script] if WINDOWS else ["/bin/bash", script]
        elif WINDOWS:
            args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", source / (operation + ".ps1")]
        else:
            args = ["/bin/bash", source / (operation + ".sh")]
        return self.run_client([*args, *options], **env)

    def assert_inventory(self, before, after):
        changed = [p for p in before.keys() | after.keys() if before.get(p) != after.get(p)]
        self.assertEqual(sorted(map(str, changed)), [], "Unexpected filesystem changes")

    def assert_refusal(self, command, *conflicts):
        before = inventory(self.client)
        result = command()
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assert_inventory(before, inventory(self.client))
        for path in conflicts:
            self.assertIn(str(path), output)

    def assert_success(self, result, agents):
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        # The installer can also print human-readable process/status messages.
        decoder = json.JSONDecoder()
        report = None
        for pos, character in enumerate(result.stdout):
            if character == "{":
                try:
                    obj, _ = decoder.raw_decode(result.stdout[pos:])
                except ValueError:
                    continue
                if isinstance(obj, dict) and "registrations" in obj:
                    report = obj
        self.assertIsNotNone(report, output)
        self.assertEqual(Path(report["checkout"]), self.destination)
        self.assertEqual(report["revision"], self.sha)
        self.assertEqual(self.git("-C", str(self.destination), "rev-parse", "HEAD"), self.sha)
        manifest = json.loads((self.destination / "skills-manifest.json").read_text())
        registrations = {entry["agent"]: entry for entry in report["registrations"]}
        self.assertEqual(set(registrations), set(agents))
        self.assertEqual(len(manifest["skills"]), 13)
        for agent in agents:
            directory = self.codex if agent == "codex" else self.claude
            registration = registrations[agent]
            self.assertEqual(Path(registration["directory"]), directory)
            self.assertEqual(set(registration["targets"]), {skill["name"] for skill in manifest["skills"]})
            for skill in manifest["skills"]:
                link = directory / skill["name"]
                target = self.destination / skill["path"]
                self.assertTrue(link.is_symlink() or os.path.isjunction(link), str(link))
                self.assertEqual(link.resolve(strict=True), target)
                self.assertEqual(Path(registration["targets"][skill["name"]]), target)
            self.assertEqual((directory / ".unrelated").read_bytes(), b"unrelated registration data\n")

    def test_product_cwd_empty_sibling_only_selected_roots_change(self):
        self.destination.mkdir()
        legacy = self.home / ".codex/skills/issue-happypro-certificate"
        legacy.mkdir(parents=True)
        (legacy / "SKILL.md").write_text("Preserve the unselected legacy root")
        (self.home / ".claude/CLAUDE.md").write_text("Personal Claude instructions")
        (self.home / ".codex/AGENTS.md").write_text("Personal Codex instructions")
        (self.home / "src").mkdir()
        allowed = (self.destination, self.codex, self.claude)
        before = inventory(self.client, exclude=allowed)
        self.assert_success(self.bootstrap(), ("codex", "claude"))
        self.assert_inventory(before, inventory(self.client, exclude=allowed))

    def test_absent_destination_single_agent(self):
        before = inventory(self.claude)
        self.assert_success(self.bootstrap(extra=("--agent", "codex")), ("codex",))
        self.assert_inventory(before, inventory(self.claude))

    def test_linked_standalone_collection_reports_physical_checkout(self):
        alias = self.client / "my projects"
        self.link_directory(alias, self.projects)
        self.assert_success(self.bootstrap(alias / self.destination.name), ("codex", "claude"))

    def test_git_product_root_empty_descendant_and_link_into_product(self):
        empty = self.product / "empty"
        empty.mkdir()
        alias = self.projects / "alias to student work"
        self.link_directory(alias, self.product)
        for destination in (self.product, empty, alias / "absent"):
            with self.subTest(destination=destination):
                self.assert_refusal(lambda: self.bootstrap(destination), self.product)

    def test_non_git_product_empty_descendant(self):
        product = self.projects / "Unversioned application"
        child = product / "planned/empty"
        child.mkdir(parents=True)
        (product / "pyproject.toml").write_text('[project]\nname = "student"\n')
        self.assert_refusal(lambda: self.bootstrap(child), product, child)

    def test_hidden_only_destination_and_invalid_release(self):
        self.destination.mkdir()
        (self.destination / ".keep").touch()
        self.assert_refusal(self.bootstrap, self.destination)
        (self.destination / ".keep").unlink()
        self.assert_refusal(lambda: self.bootstrap("relative"), "relative")
        self.assert_refusal(lambda: self.bootstrap(revision="0" * 40))
        # A repeated destination is ambiguous even when both locations would be safe.
        self.assert_refusal(lambda: self.bootstrap(extra=("--destination", self.projects / "other")))

    def test_environment_registration_rejected_before_clone(self):
        local = self.product / ".agents/skills"
        self.assert_refusal(lambda: self.bootstrap(CODEX_SKILLS_DIR=str(local)), self.product, local)

    def test_install_repair_launchers_and_update_refuse_product_local_registration(self):
        self.clone()
        local = self.product / ".claude/skills"
        local.mkdir(parents=True)
        for operation, flags in (
            ("install", ("--claude-dir", local)),
            ("install", ("--repair", "--claude-dir", local)),
            ("update", ("--claude-dir", local)),
            ("install-launcher", ()),
            ("update-launcher", ()),
        ):
            with self.subTest(operation=operation, flags=flags):
                env = {"CLAUDE_SKILLS_DIR": str(local)} if not flags else {}
                self.assert_refusal(lambda: self.native(operation, *flags, **env), self.product, local)
        codex_home = self.product / "codex home"
        self.assert_refusal(lambda: self.native("install", CODEX_HOME=str(codex_home)), self.product)
        self.assert_refusal(lambda: self.bootstrap(operation="update", CODEX_SKILLS_DIR=str(local)),
                            self.product, local)

    def test_default_registration_with_linked_parent_is_refused(self):
        self.clone()
        shutil.rmtree(self.claude.parent)
        self.link_directory(self.claude.parent, self.product)
        self.assert_refusal(lambda: self.native("install"), self.product)

    def test_implicit_backup_and_evidence_destinations_checked_before_cleanup(self):
        self.clone()
        dangerous_backup = self.product / "prior backups"
        self.assert_refusal(lambda: self.native("install", "--retire-only",
                                                SDD_SKILL_BACKUP_DIR=str(dangerous_backup)),
                            self.product, dangerous_backup)
        dangerous_evidence_home = self.product / "evidence bindings"
        self.assert_refusal(lambda: self.native("install", "--evidence-non-interactive",
                                                SDD_EVIDENCE_HOME=str(dangerous_evidence_home)),
                            self.product, dangerous_evidence_home)

    def test_nested_official_clone_and_mixed_source_block_before_mutation(self):
        nested = self.product / "actual SDD clone"
        self.clone(nested)
        self.assert_refusal(lambda: self.native("install", source=nested), self.product, nested)
        self.clone()
        (self.destination / ".untracked-student-work").write_bytes(b"keep")
        for operation in ("install", "update"):
            with self.subTest(operation=operation):
                self.assert_refusal(lambda: self.native(operation), self.destination)

    def test_existing_checkout_fast_forward_and_missing_link_repair(self):
        # Install at the last official predecessor before the standalone bootstrap was added.
        added = self.git("--git-dir", str(self.remote), "log", "--diff-filter=A", "-1", "--format=%H",
                         self.sha, "--", "scripts/install_location.py")
        previous = self.git("--git-dir", str(self.remote), "rev-parse", added + "^")
        self.publish(previous)
        self.clone()
        self.assertFalse((self.destination / "scripts/install_location.py").exists())
        self.publish(self.sha)
        product_before = inventory(self.product)
        self.assert_success(self.bootstrap(operation="update"), ("codex", "claude"))
        self.assert_inventory(product_before, inventory(self.product))
        link = self.codex / "to-sdd-prd"
        if os.path.isjunction(link):
            link.rmdir()
        else:
            link.unlink()
        self.assert_success(self.native("install", "--repair"), ("codex", "claude"))
        self.assert_success(self.native("update"), ("codex", "claude"))
        self.assert_inventory(product_before, inventory(self.product))


if __name__ == "__main__":
    unittest.main()
