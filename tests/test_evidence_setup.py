"""Isolated setup/status tests; no personal roots, accounts or cloud uploads."""
from copy import deepcopy
import hashlib
import json
import os
import shlex
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evidence_setup as setup
import installation_status


class EvidenceSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-evidence-setup-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "machine-state"
        self.project = self.base / "project"
        self.project.mkdir()
        self.probes = []

    def probe(self, config, project):
        self.probes.append(deepcopy(config))
        if config["provider"] != "google-drive":
            Path(config["destination"]).mkdir(parents=True, exist_ok=True)
        return {"verified": True, "synthetic_fixture": True, "verification": "independent_original_bytes"}

    def configure(self, **kwargs):
        return setup.configure(self.project, home=self.home, provider="local", probe=self.probe, **kwargs)

    def test_import_and_status_are_read_only(self):
        result = setup.inspect(self.project, self.home)
        self.assertEqual("setup_required", result["result"])
        self.assertFalse(self.home.exists())
        self.assertEqual([], list(self.project.iterdir()))

    def test_noninteractive_missing_setup_records_status_without_selection(self):
        result = setup.ensure(self.project, home=self.home)
        self.assertEqual("setup_required", result["result"])
        self.assertEqual(["setup-status.json"], [p.name for p in self.home.iterdir()])
        self.assertFalse((self.project / "forge").exists())
        self.assertEqual([], self.probes)

    def test_noninteractive_cli_never_hangs_or_chooses_provider(self):
        env = dict(os.environ, SDD_EVIDENCE_HOME=str(self.home))
        result = subprocess.run([sys.executable, str(ROOT / "scripts/evidence_setup.py"), "ensure", "--project", str(self.project), "--non-interactive"],
                                env=env, input="", capture_output=True, text=True, timeout=10)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("setup_required", json.loads(result.stdout)["result"])
        self.assertFalse((self.home / "default.json").exists())

    def test_explicit_setup_separates_machine_paths_from_portable_policy(self):
        result = self.configure()
        self.assertEqual("configured", result["result"])
        policy = json.loads((self.project / "forge/evidence-policy.json").read_text())
        binding = setup._read(Path(result["config_path"]))
        self.assertEqual(30, policy["retention"]["local_days"])
        self.assertEqual(policy["store_id"], binding["store_id"])
        self.assertNotIn(str(self.base), json.dumps(policy))
        self.assertNotIn("destination", policy)
        self.assertEqual("local", binding["transport"])
        self.assertTrue(Path(binding["destination"]).is_dir())

    def test_existing_choices_preserved_and_no_repeated_probe(self):
        self.configure()
        policy_before = (self.project / "forge/evidence-policy.json").read_bytes()
        self.assertEqual("configured", setup.ensure(self.project, home=self.home)["result"])
        self.assertEqual(1, len(self.probes))
        with self.assertRaisesRegex(setup.SetupError, "--reconfigure"):
            self.configure()
        self.assertEqual(policy_before, (self.project / "forge/evidence-policy.json").read_bytes())

    def test_explicit_reconfiguration_preserves_project_identity(self):
        first = self.configure()
        second = self.configure(reconfigure=True, retention_days=14)
        self.assertEqual(first["project_id"], second["project_id"])
        self.assertEqual(first["store_id"], second["store_id"])
        self.assertEqual(14, setup._read(self.project / "forge/evidence-policy.json")["retention"]["local_days"])

    def test_selected_folder_is_durable_and_mounted_folder_failure_preserves_choice(self):
        folder = self.base / "selected-volume"
        result = setup.configure(self.project, home=self.home, provider="folder", destination=str(folder), probe=self.probe)
        binding = Path(result["config_path"])
        before = binding.read_bytes()
        folder.rmdir()
        result = setup.ensure(self.project, home=self.home)
        self.assertEqual("setup_required", result["result"])
        self.assertIn("unavailable", result["reason"])
        self.assertEqual(before, binding.read_bytes())
        self.assertFalse(folder.exists())

    def test_drive_retention_requires_explicit_selection_before_any_probe(self):
        with self.assertRaisesRegex(setup.SetupError, "drive-retention-days"):
            setup.configure(self.project, home=self.home, provider="google-drive", destination="synthetic:", probe=self.probe)
        self.assertEqual([], self.probes)
        self.assertFalse(self.home.exists())

    def test_failed_probe_does_not_commit_provider_or_policy(self):
        def fail(config, project):
            return {"verified": False}
        with self.assertRaisesRegex(setup.SetupError, "independently"):
            setup.configure(self.project, home=self.home, provider="google-drive", destination="synthetic:", drive_retention_days="never", probe=fail)
        self.assertFalse((self.project / "forge/evidence-policy.json").exists())
        self.assertFalse((self.home / "default.json").exists())

    def test_drive_choice_keeps_credentials_machine_only(self):
        credential = self.base / "synthetic-rclone.conf"
        credential.write_text("Synthetic fixture; no credential.\n")
        result = setup.configure(self.project, home=self.home, provider="google-drive", destination="synthetic:",
                                 drive_retention_days="90", rclone_config=credential, rclone_executable=sys.executable, probe=self.probe)
        policy = setup._read(self.project / "forge/evidence-policy.json")
        binding = setup._read(Path(result["config_path"]))
        self.assertEqual(90, policy["retention"]["drive_days"])
        self.assertEqual(str(credential.resolve()), binding["rclone_config"])
        self.assertNotIn(str(credential), json.dumps(policy))
        self.assertNotIn("rclone_config", json.dumps(policy))
        credential.unlink()
        status = setup.ensure(self.project, home=self.home)
        self.assertEqual("setup_required", status["result"])
        self.assertIn("credentials are missing", status["reason"])
        self.assertEqual(1, len(self.probes))

    def test_default_first_use_then_clone_share_stable_identity_without_upload(self):
        setup.configure(home=self.home, provider="local", probe=self.probe)
        first = setup.ensure(self.project, home=self.home)
        self.assertEqual("configured", first["result"])
        clone = self.base / "worktree"
        shutil.copytree(self.project, clone)
        result = setup.ensure(clone, home=self.home)
        self.assertEqual(first["project_id"], result["project_id"])
        self.assertEqual(first["store_id"], result["store_id"])
        self.assertEqual(1, len(self.probes))

    def test_clone_missing_machine_binding_uses_matching_saved_default(self):
        setup.configure(home=self.home, provider="local", probe=self.probe)
        first = setup.ensure(self.project, home=self.home)
        Path(first["config_path"]).unlink()
        second = setup.ensure(self.project, home=self.home)
        self.assertEqual(first["project_id"], second["project_id"])
        self.assertEqual("configured", second["result"])

    def test_bad_or_unknown_policy_never_replaced_with_defaults(self):
        setup.configure(home=self.home, provider="local", probe=self.probe)
        policy = self.project / "forge/evidence-policy.json"
        policy.parent.mkdir()
        policy.write_text('{"version":99}')
        before = policy.read_bytes()
        result = setup.ensure(self.project, home=self.home)
        self.assertEqual("setup_required", result["result"])
        self.assertEqual(before, policy.read_bytes())

    def test_current_skill_links_still_report_missing_setup(self):
        skill_root = self.base / "installed"
        skill_root.mkdir()
        rows = installation_status.validate_manifest(ROOT)
        for name, relative, _ in rows:
            (skill_root / name).symlink_to(ROOT / relative, target_is_directory=True)
        report = installation_status.inspect(ROOT, [skill_root], evidence_home=self.home)
        self.assertEqual("current", report["links_result"])
        self.assertEqual("setup_required", report["result"])
        self.assertFalse(self.home.exists())
        setup.configure(home=self.home, provider="local", probe=self.probe)
        report = installation_status.inspect(ROOT, [skill_root], evidence_home=self.home)
        self.assertEqual("current", report["result"])
        self.assertEqual(1, len(self.probes))

    def test_aggregate_limit_overrides_validate_before_probe(self):
        self.configure(limits={"run_warning_bytes": 1024, "run_stop_bytes": 2048, "unit_stop_files": 17, "metadata_stop_bytes": 4096})
        policy = setup._read(self.project / "forge/evidence-policy.json")
        self.assertEqual(17, policy["limits"]["unit_stop_files"])
        self.assertEqual(4096, policy["limits"]["metadata_stop_bytes"])
        with self.assertRaises(Exception):
            self.configure(reconfigure=True, limits={"unknown_budget": 1})
        self.assertEqual(1, len(self.probes))

    def test_repository_destinations_and_symlinked_forge_rejected(self):
        with self.assertRaisesRegex(setup.SetupError, "outside"):
            setup.configure(self.project, home=self.home, provider="folder", destination=str(self.project / "storage"), probe=self.probe)
        other = self.base / "other"
        other.mkdir()
        (self.project / "forge").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(setup.SetupError, "contained"):
            self.configure()
        self.assertEqual([], list(other.iterdir()))

    def test_environment_override_never_uses_personal_home(self):
        with patch.dict(os.environ, {"SDD_EVIDENCE_HOME": str(self.home)}):
            result = setup.ensure()
        self.assertEqual("setup_required", result["result"])
        self.assertTrue((self.home / "setup-status.json").is_file())

    def test_saved_choice_does_not_repeat_wizard_when_disk_unavailable(self):
        result = self.configure()
        binding = setup._read(Path(result["config_path"]))
        Path(binding["destination"]).rmdir()
        with patch.object(setup, "wizard", side_effect=AssertionError("ordinary update repeated setup")):
            result = setup.ensure(self.project, home=self.home, interactive=True)
        self.assertEqual("setup_required", result["result"])

    def test_wizard_explicit_local_selection_and_cancel(self):
        answers = iter(["1", *("" for _ in range(10)), "", ""])
        with patch.object(setup, "_probe", side_effect=self.probe):
            result = setup.wizard(self.project, home=self.home, input_fn=lambda prompt: next(answers))
        self.assertEqual("configured", result["result"])
        before = setup._read(Path(result["config_path"]))
        setup.wizard(self.project, home=self.home, input_fn=lambda prompt: "")
        self.assertEqual(before, setup._read(Path(result["config_path"])))

    def test_source_repository_contains_no_machine_config_after_setup(self):
        self.configure()
        generated = list(self.project.rglob("*"))
        self.assertEqual({"forge", "forge/evidence-policy.json"}, {path.relative_to(self.project).as_posix() for path in generated})

    def test_connected_bridge_argument_array_is_portable(self):
        value = ["python", "C:\\Synthetic folder\\bridge.py", "--option"]
        self.assertEqual(value, setup.parse_bridge_command(json.dumps(value)))
        with self.assertRaises(setup.SetupError):
            setup.parse_bridge_command("[]")

    def test_new_project_explicit_choice_preserves_global_default(self):
        setup.configure(home=self.home, provider="local", probe=self.probe)
        before = (self.home / "default.json").read_bytes()
        result = setup.configure(self.project, home=self.home, provider="folder", destination=str(self.base / "project-durable"), probe=self.probe)
        self.assertEqual("configured", result["result"])
        self.assertEqual("folder", result["provider"])
        self.assertEqual(before, (self.home / "default.json").read_bytes())

    def test_reconfiguration_preserves_unmentioned_retention_and_limits(self):
        self.configure(retention_days=21, limits={"metadata_stop_bytes": 1048576})
        self.configure(reconfigure=True)
        policy = setup._read(self.project / "forge/evidence-policy.json")
        self.assertEqual(21, policy["retention"]["local_days"])
        self.assertEqual(1048576, policy["limits"]["metadata_stop_bytes"])
        setup.configure(home=self.home, provider="local", retention_days=14, probe=self.probe)
        setup.configure(home=self.home, provider="local", reconfigure=True, probe=self.probe)
        self.assertEqual(14, setup._read(self.home / "default-policy.json")["retention"]["local_days"])

    def test_drive_reconfiguration_preserves_transport_destination_and_retention(self):
        setup.configure(self.project, home=self.home, provider="google-drive", destination="synthetic-folder-id",
                        transport="connected", bridge_command=[sys.executable, "synthetic-bridge.py"], drive_retention_days="90", probe=self.probe)
        result = setup.configure(self.project, home=self.home, provider="google-drive", reconfigure=True, probe=self.probe)
        config = setup._read(Path(result["config_path"]))
        self.assertEqual("connected", config["transport"])
        self.assertEqual("synthetic-folder-id", config["destination"])
        self.assertEqual([sys.executable, "synthetic-bridge.py"], config["bridge_command"])
        self.assertEqual(90, setup._read(self.project / "forge/evidence-policy.json")["retention"]["drive_days"])

    def test_saved_missing_drive_executable_is_read_only_setup_failure(self):
        result = setup.configure(self.project, home=self.home, provider="google-drive", destination="synthetic:",
                                 drive_retention_days="never", rclone_executable=sys.executable, probe=self.probe)
        config_path = Path(result["config_path"])
        config = setup._read(config_path)
        config["rclone_executable"] = str(self.base / "removed-rclone-executable")
        setup._write(config_path, config)
        before = config_path.read_bytes()
        status = setup.ensure(self.project, home=self.home)
        self.assertEqual("setup_required", status["result"])
        self.assertIn("rclone executable is missing", status["reason"])
        self.assertEqual(before, config_path.read_bytes())
        self.assertEqual(1, len(self.probes))

    def test_saved_missing_bridge_executable_does_not_probe_or_switch_provider(self):
        result = setup.configure(self.project, home=self.home, provider="google-drive", destination="synthetic-folder-id",
                                 transport="connected", bridge_command=[sys.executable, "synthetic-bridge.py"], drive_retention_days="never", probe=self.probe)
        config_path = Path(result["config_path"])
        config = setup._read(config_path)
        config["bridge_command"] = [str(self.base / "removed-host-bridge")]
        setup._write(config_path, config)
        before = config_path.read_bytes()
        status = setup.ensure(self.project, home=self.home)
        self.assertEqual("setup_required", status["result"])
        self.assertIn("bridge executable is missing", status["reason"])
        self.assertEqual(before, config_path.read_bytes())
        self.assertEqual(1, len(self.probes))

    def test_setup_required_action_uses_concrete_safely_quoted_project_and_home(self):
        project = self.base / "Synthetic project 'quote' $(literal)"
        project.mkdir()
        home = self.base / "Machine state 'quote' $(literal)"
        status = setup.inspect(project, home)
        arguments = status["next_action_argv"]
        self.assertEqual(sys.executable, arguments[0])
        self.assertEqual(str(ROOT / "scripts/evidence_setup.py"), arguments[1])
        self.assertEqual("wizard", arguments[2])
        self.assertEqual(str(project), arguments[arguments.index("--project") + 1])
        self.assertEqual(str(home), arguments[arguments.index("--evidence-home") + 1])
        self.assertNotIn("PATH", arguments)
        if os.name != "nt":
            self.assertEqual(arguments, shlex.split(status["next_action"]))
        self.assertFalse(home.exists())

    def run_cli(self, script, *arguments, expected=0):
        result = subprocess.run([sys.executable, str(ROOT / script), *arguments],
                                env=dict(os.environ, SDD_EVIDENCE_HOME=str(self.home)),
                                input="", capture_output=True, text=True, timeout=30)
        self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_real_local_setup_archive_prepare_resolver(self):
        from evidence.resolver import EvidenceResolver
        configured = self.run_cli("scripts/evidence_setup.py", "configure", "--project", str(self.project), "--provider", "local")
        config = setup._read(Path(configured["config_path"]))
        self.assertTrue(config["setup_receipt"]["verified"])
        self.assertTrue(config["setup_receipt"]["test_resource_removed"])
        self.assertIn("original_sha256", config["setup_receipt"])
        self.assertEqual("configured", self.run_cli("scripts/evidence_setup.py", "ensure", "--project", str(self.project), "--non-interactive")["result"])
        payload = self.project / "synthetic-observation.bin"
        original = b"Synthetic fixture, not product evidence.\n" * 1024
        payload.write_bytes(original)
        specification = self.base / "archive-spec.json"
        specification.write_text(json.dumps({"version": 1, "files": [{"path": str(payload), "kind": "integration", "schema": "evidence-bytes-v1",
            "sealed_at": "2026-10-10T12:00:00Z", "provenance": {"run_id": "synthetic-run-1", "unit_id": "U-1"}, "bindings": {}}]}))
        refs_path = self.base / "refs.json"
        archived = self.run_cli("skills/to-sdd-pipeline/scripts/evidence_store.py", "archive", "--project", str(self.project), "--spec", str(specification), "--output", str(refs_path))
        prepared = self.run_cli("skills/to-sdd-pipeline/scripts/evidence_store.py", "prepare", "--project", str(self.project), "--refs", str(refs_path))
        reference = archived["refs"][0]
        resolved = EvidenceResolver(prepared["cache"]).resolve(reference)
        self.assertEqual(original, resolved.read_bytes())
        self.assertEqual(hashlib.sha256(original).hexdigest(), reference["sha256"])
        self.assertEqual("2026-10-10T12:00:00Z", reference["retention"]["sealed_at"])

    def test_real_standalone_missing_tool_does_not_fallback_or_claim_setup(self):
        result = self.run_cli("scripts/evidence_setup.py", "configure", "--project", str(self.project), "--provider", "google-drive",
            "--destination", "synthetic:", "--drive-retention-days", "never", "--rclone-executable", str(self.base / "missing-rclone"), expected=1)
        self.assertEqual("setup_required", result["result"])
        self.assertIn("missing", result["reason"])
        self.assertFalse((self.project / "forge/evidence-policy.json").exists())
        self.assertFalse((self.home / "default.json").exists())

    def test_real_default_setup_plain_pull_first_use_retains_selected_policy(self):
        default = self.run_cli("scripts/evidence_setup.py", "configure", "--provider", "local", "--retention-days", "21")
        self.assertEqual("configured", default["result"])
        before = (self.home / "default.json").read_bytes()
        first = self.run_cli("scripts/evidence_setup.py", "ensure", "--project", str(self.project), "--non-interactive")
        status = self.run_cli("scripts/evidence_setup.py", "status", "--project", str(self.project))
        self.assertEqual(first, status)
        self.assertEqual(21, setup._read(self.project / "forge/evidence-policy.json")["retention"]["local_days"])
        self.assertEqual(before, (self.home / "default.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
