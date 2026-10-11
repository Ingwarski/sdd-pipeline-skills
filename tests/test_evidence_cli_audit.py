"""Real local CLI boundaries and synthetic connected-command dispatch; no accounts."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/to-sdd-pipeline/scripts/evidence_store.py"
SETUP = ROOT / "scripts/evidence_setup.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("evidence_cli_audit", SCRIPT)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class EvidenceCliAuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdd-evidence-cli-audit-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / "home"
        self.project = self.base / "project"
        self.project.mkdir()
        self.env = dict(os.environ, SDD_EVIDENCE_HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1")

    def command(self, command, *arguments):
        return [sys.executable, "-B", str(SCRIPT), command, "--project", str(self.project),
                "--home", str(self.home), *map(str, arguments)]

    def run_cli(self, command, *arguments, expected=0):
        process = subprocess.run(self.command(command, *arguments), env=self.env,
                                 input="", capture_output=True, text=True, timeout=45)
        self.assertEqual(expected, process.returncode, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def configure(self, default=False):
        arguments = [] if default else ["--project", str(self.project)]
        process = subprocess.run([sys.executable, "-B", str(SETUP), "configure", "--provider", "local",
            "--evidence-home", str(self.home), "--limit", "free_space_reserve_bytes=0", *arguments],
            env=self.env, input="", capture_output=True, text=True, timeout=45)
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual("configured", result["result"])
        return result

    def manager(self):
        return cli.load_manager(SimpleNamespace(home=str(self.home), project=str(self.project),
            policy=None, project_id=None, config=None, host_session=None))

    def producer(self, output, *, run_id="run", deferred=False, code=None):
        return ["--run-id", run_id, "--unit-id", "U-1", "--output-dir", output,
            "--reserve-bytes", "100", "--reserve-files", "3", "--timeout", "20",
            *(["--defer-run-completion"] if deferred else []), "--", sys.executable, "-B", "-c",
            code or "from pathlib import Path; Path('data').write_bytes(b'123456')"]

    def test_first_status_is_read_only_and_explicit_run_reuses_saved_defaults(self):
        report = self.run_cli("status", expected=2)
        self.assertEqual("setup_required", report["result"])
        self.assertIn(str(SETUP), report["next_action_argv"])
        self.assertIn(str(self.home), report["next_action_argv"])
        self.assertFalse(self.home.exists())
        self.assertEqual([], list(self.project.iterdir()))
        self.configure(default=True)
        defaults = (self.home / "default.json").read_bytes()
        before = {str(path.relative_to(self.base)): path.read_bytes() for path in self.base.rglob("*") if path.is_file()}
        self.run_cli("status", expected=2)
        self.assertEqual(before, {str(path.relative_to(self.base)): path.read_bytes() for path in self.base.rglob("*") if path.is_file()})
        result = self.run_cli("run", *self.producer(self.base / "first-output"))
        self.assertEqual("complete", result["status"])
        policy = json.loads((self.project / "forge/evidence-policy.json").read_text())
        config = json.loads(defaults)
        self.assertEqual(config["store_id"], policy["store_id"])
        self.assertEqual(defaults, (self.home / "default.json").read_bytes())
        self.assertEqual(6, self.run_cli("status")["gross_generated_bytes"])

    def test_first_use_forwards_active_host_session_to_setup(self):
        setup = SimpleNamespace(inspect=Mock(return_value={"result": "setup_required"}),
                                ensure=Mock(return_value={"result": "configured"}))
        session = str(self.base / "active-connected-session")
        args = SimpleNamespace(project=str(self.project), home=str(self.home), config=None,
                               policy=None, command="run", host_session=session)
        loader = SimpleNamespace(loader=SimpleNamespace(exec_module=Mock()))
        with patch.object(cli.importlib.util, "spec_from_file_location", return_value=loader), \
             patch.object(cli.importlib.util, "module_from_spec", return_value=setup):
            self.assertIsNone(cli.project_setup(args))
        self.assertEqual(session, setup.ensure.call_args.kwargs["host_session"])
        self.assertEqual(self.home, setup.ensure.call_args.kwargs["home"])
        self.assertEqual(self.project, setup.ensure.call_args.args[0])

    def test_host_session_reaches_transport_without_persisting_it(self):
        self.configure()
        policy = json.loads((self.project / "forge/evidence-policy.json").read_text())
        binding = self.home / "bindings" / (policy["project_id"] + ".json")
        before = binding.read_bytes()
        session = str(self.base / "active-connected-session")
        args = SimpleNamespace(home=str(self.home), project=str(self.project), policy=None,
                               project_id=None, config=None, host_session=session)
        with patch.object(cli, "transport") as factory, patch.object(cli, "Manager"):
            cli.load_manager(args)
        self.assertEqual(session, factory.call_args.args[2])
        self.assertEqual(before, binding.read_bytes())

    def test_shared_run_workers_defer_completion_until_coordinator_seals(self):
        self.configure()
        output, release = self.base / "first-worker", self.base / "release-first-worker"
        code = ("from pathlib import Path\nimport time\nPath('data').write_bytes(b'123456')\n"
                "while not Path(" + repr(str(release)) + ").exists(): time.sleep(0.02)\n")
        process = subprocess.Popen(self.command("run", *self.producer(output, deferred=True, code=code)),
                                   env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 15
            while not (output / "data").exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((output / "data").exists(), "first worker failed to start")
            second = self.run_cli("run", *self.producer(self.base / "second-worker", deferred=True))
            self.assertEqual("complete", second["status"])
            self.assertEqual("deferred", second["run_completion"])
            blocked = self.run_cli("complete-run", "--run-id", "run", expected=1)
            self.assertIn("incomplete", blocked["error"])
        finally:
            release.touch()
            try:
                stdout, stderr = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(0, process.returncode, stdout + stderr)
        first = json.loads(stdout)
        self.assertEqual("deferred", first["run_completion"])
        self.assertEqual(12, self.run_cli("status")["gross_generated_bytes"])
        before = self.run_cli("accounting-receipt")
        self.assertEqual("incomplete", before["runs"]["run"]["status"])
        self.assertEqual("complete", self.run_cli("complete-run", "--run-id", "run")["status"])
        after = self.run_cli("accounting-receipt")
        self.assertEqual("complete", after["runs"]["run"]["status"])
        self.assertEqual(12, after["runs"]["run"]["gross_generated_bytes"])
        self.assertTrue(after["accounting_complete"])
        self.assertFalse(after["incomplete"])

    def test_second_home_cannot_launch_an_independent_producer(self):
        configured = self.configure()
        output = self.base / "unauthorized-output"
        report = self.run_cli("run", "--config", configured["config_path"], "--home", self.base / "second-home",
                              *self.producer(output), expected=1)
        self.assertIn("coordinator", report["error"])
        self.assertFalse(output.exists())
        self.assertEqual(0, self.run_cli("status")["gross_generated_bytes"])

    def test_accounting_receipt_marks_lost_ledger_history_incomplete(self):
        self.configure()
        self.run_cli("run", *self.producer(self.base / "generated"))
        manager = self.manager()
        database = manager.state / "accounting.sqlite"
        database.unlink()
        receipt = self.run_cli("accounting-receipt", expected=1)
        self.assertFalse(receipt["accounting_complete"])
        self.assertTrue(receipt["incomplete"])
        self.assertTrue(receipt["totals_are_lower_bounds"])
        self.assertEqual(6, receipt["runs"]["run"]["gross_generated_bytes"])
        self.assertEqual("incomplete", receipt["runs"]["run"]["status"])

    def test_accounting_receipt_marks_pending_durable_intent_incomplete(self):
        configured = self.configure()
        manager = self.manager()
        intent = manager.begin_generation("unstarted", "U-1", 100, 3)
        receipt = self.run_cli("accounting-receipt", "--config", configured["config_path"],
                              "--home", self.base / "cold-home", expected=1)
        self.assertFalse(receipt["accounting_complete"])
        self.assertTrue(receipt["incomplete"])
        self.assertTrue(receipt["totals_are_lower_bounds"])
        self.assertIn(intent, receipt["pending_generation_intents"])
        self.assertEqual({}, receipt["runs"])

    def test_missing_upload_acknowledgement_dispatches_only_exact_project_key(self):
        project_id = "11111111-1111-4111-8111-111111111111"
        key = "projects/" + project_id + "/packs/original.zip"
        manager = SimpleNamespace(policy={"project_id": project_id}, assert_generation_authority=Mock(),
                                  transport=SimpleNamespace(acknowledge_missing_upload=Mock()))
        for selected, expected in ((key, 0), ("projects/other/packs/original.zip", 1)):
            manager.transport.acknowledge_missing_upload.reset_mock()
            output = io.StringIO()
            with patch.object(sys, "argv", [str(SCRIPT), "acknowledge-missing-upload", "--key", selected]), \
                 patch.object(cli, "project_setup", return_value=None), \
                 patch.object(cli, "load_manager", return_value=manager), redirect_stdout(output):
                self.assertEqual(expected, cli.main())
            report = json.loads(output.getvalue())
            if expected == 0:
                manager.transport.acknowledge_missing_upload.assert_called_once_with(key)
                self.assertEqual(key, report["acknowledged_missing_upload"])
                self.assertTrue(report["verified_absent"])
            else:
                manager.transport.acknowledge_missing_upload.assert_not_called()
                self.assertIn("project's namespace", report["error"])

    def test_cold_receipt_cannot_invent_original_policy_byte_binding(self):
        output = io.StringIO()
        with patch.object(sys, "argv", [str(SCRIPT), "accounting-receipt"]), \
             patch.object(cli, "project_setup", return_value=None), \
             patch.object(cli, "load_manager", return_value=Mock()), redirect_stdout(output):
            self.assertEqual(1, cli.main())
        report = json.loads(output.getvalue())
        self.assertTrue(report["incomplete"])
        self.assertIn("original portable policy file", report["error"])
        self.assertNotIn("policy_sha256", report)


if __name__ == "__main__":
    unittest.main()
