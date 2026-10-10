"""Isolated managed producers exercise actual launch/stop/accounting behavior."""
from pathlib import Path
import os
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence.accounting import Accounting
from evidence.io import EvidenceError
from evidence.policy import load_defaults
from evidence.producer import run_producer


class ManagedProducerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.output = self.root / "output"
        self.output.mkdir()
        policy = load_defaults()
        policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider="local")
        self.ledger = Accounting(self.root / "machine/ledger.sqlite", policy["project_id"], policy)

    def tearDown(self):
        self.ledger.close()
        self.temporary.cleanup()

    def run_script(self, source, bytes=10000, files=10, timeout=10):
        return run_producer(self.ledger, "run-1", "unit-01", self.output,
                            [sys.executable, "-c", source], bytes, files,
                            timeout=timeout, poll_interval=0.02)

    def test_successfully_reserves_monitors_and_seals_actual_outputs(self):
        result = self.run_script("from pathlib import Path; import os; Path(os.environ['SDD_EVIDENCE_OUTPUT_DIR'],'observation.txt').write_text('synthetic'); print('observed')")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["gross_files"], 2)
        expected_bytes = len(b"synthetic") + len(("observed" + os.linesep).encode())
        self.assertEqual(result["gross_bytes"], expected_bytes)
        self.assertEqual(set(result["observations"]), {"producer.log", "observation.txt"})
        self.assertEqual(self.ledger.snapshot()["totals"]["project_generated_bytes"], expected_bytes)
        self.assertEqual(self.ledger.snapshot()["reservations"], [])
        observed = result["observations"]["observation.txt"]
        binding = self.ledger.require_managed_source(result["output_id"], "run-1", "unit-01",
                                                    self.output / "observation.txt", observed["content_hash"], observed["size"])
        self.assertEqual(binding["accounting_mode"], "managed-generation")
        (self.output / "observation.txt").write_text("changed")
        with self.assertRaises(EvidenceError):
            self.ledger.require_managed_source(result["output_id"], "run-1", "unit-01",
                                               self.output / "observation.txt", observed["content_hash"], observed["size"])

    def test_over_budget_producer_stopped_without_truncating_log(self):
        started = time.monotonic()
        result = self.run_script("import time; print('x'*4096,flush=True); time.sleep(30)", bytes=100)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("reserved aggregate", result["problem"])
        self.assertGreaterEqual((self.output / "producer.log").stat().st_size, 4097)
        self.assertGreaterEqual(self.ledger.snapshot()["totals"]["project_generated_bytes"], 4097)
        self.assertLess(time.monotonic() - started, 10)
        with self.assertRaises(EvidenceError):
            self.ledger.complete_run("run-1")

    def test_many_small_outputs_exhaust_logical_count(self):
        result = self.run_script("from pathlib import Path; import time; [Path(str(i)).write_bytes(b'x') for i in range(10)]; time.sleep(30)", files=3)
        self.assertEqual(result["status"], "incomplete")
        self.assertGreater(result["gross_files"], 3)
        self.assertLessEqual(result["gross_files"], 11)
        self.assertEqual(len(result["observations"]), result["gross_files"])
        self.assertEqual(self.ledger.snapshot()["totals"]["project_generated_files"], result["gross_files"])

    def test_timeout_stops_task_owned_process_and_marks_incomplete(self):
        started = time.monotonic()
        result = self.run_script("import time; time.sleep(30)", timeout=0.1)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("timeout", result["problem"])
        self.assertIsNotNone(result["exit_code"])
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(self.ledger.snapshot()["runs"][0]["status"], "incomplete")

    def test_nonzero_exit_and_missing_command_preserve_truthful_accounting(self):
        result = self.run_script("import sys; print('failure detail'); sys.exit(7)")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual((self.output / "producer.log").read_text().strip(), "failure detail")
        other = self.root / "missing-command"
        other.mkdir()
        result = run_producer(self.ledger, "run-2", "unit-02", other,
                              [str(self.root / "nonexistent-command")], 100, 1)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(self.ledger.snapshot()["reservations"], [])

    def test_rejects_nonempty_location_and_shell_source(self):
        (self.output / "authored-fixture").write_text("preserve")
        with self.assertRaises(EvidenceError):
            self.run_script("print('cannot overwrite')")
        self.assertEqual((self.output / "authored-fixture").read_text(), "preserve")
        with self.assertRaises(EvidenceError):
            run_producer(self.ledger, "run", "unit", self.output, "echo not argv", 100, 1)

    def test_interrupt_still_settles_and_marks_incomplete_before_propagating(self):
        with patch("evidence.producer.subprocess.Popen", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.run_script("print('not launched')")
        self.assertEqual(self.ledger.snapshot()["reservations"], [])
        self.assertEqual(self.ledger.snapshot()["runs"][0]["status"], "incomplete")

    @unittest.skipUnless(os.name == "posix", "Unix process-group assertion")
    def test_timeout_stops_helpers_in_same_task_owned_process_group(self):
        # The launched parent waits for its helper, letting it reap normally when
        # both receive SIGTERM. No unrelated process is touched.
        source = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(p.pid,flush=True); p.wait()"
        result = self.run_script(source, timeout=0.2)
        self.assertEqual(result["status"], "incomplete")
        helper = int((self.output / "producer.log").read_text().strip())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(helper, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            self.fail("task-owned helper process still exists")


if __name__ == "__main__":
    unittest.main()
