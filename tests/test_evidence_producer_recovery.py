"""Real, isolated coordinator failures exercise durable producer recovery.

Every command and process belongs to this disposable fixture. These checks do
not launch a product, use installed skills, or imply product acceptance.
"""
from pathlib import Path
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence.accounting import Accounting
from evidence.io import EvidenceError
from evidence.policy import load_defaults
from evidence import process_identity
from evidence.producer import recover_producers, run_producer
from evidence.producer_runtime import stop_registered


COORDINATOR = """import json, sys
from pathlib import Path
from evidence.accounting import Accounting
from evidence.producer import run_producer
config = json.loads(sys.argv[1])
with Accounting(config['ledger'], config['policy']['project_id'], config['policy']) as ledger:
    result = run_producer(ledger, config['run_id'], 'unit-fixture', config['output'],
        [sys.executable, '-B', '-c', config['source']], 65536, 20,
        timeout=config['timeout'], poll_interval=.02)
Path(config['result']).write_text(json.dumps(result), encoding='utf-8')
"""


class ProducerRecoveryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-producer-recovery-")
        self.root = Path(self.temporary.name).resolve()
        self.output = self.root / "output"
        self.output.mkdir()
        self.policy = load_defaults()
        self.policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider="local")
        self.ledger = Accounting(self.root / "machine" / "ledger.sqlite",
                                 self.policy["project_id"], self.policy)
        self.children = []
        self.identities = {}
        self.streams = []
        self.coordinator_source = self.root / "coordinator.py"
        self.coordinator_source.write_text(COORDINATOR, encoding="utf-8")

    def _remember(self, value):
        if isinstance(value, dict):
            if set(value) == {"version", "host", "platform", "pid", "created"}:
                if value["pid"] != os.getpid():
                    self.identities[json.dumps(value, sort_keys=True)] = value
            else:
                for child in value.values():
                    self._remember(child)
        elif isinstance(value, list):
            for child in value:
                self._remember(child)

    def _records(self):
        try:
            rows = self.ledger.connection.execute("SELECT record FROM producer_sessions ORDER BY id").fetchall()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error):
                return []
            raise
        records = [json.loads(row[0]) for row in rows]
        self._remember(records)
        return records

    def _record(self):
        records = self._records()
        return records[0] if records else None

    def _wait(self, predicate, description, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.02)
        detail = ""
        path = self.root / "coordinator.log"
        if path.exists():
            detail = path.read_text(encoding="utf-8", errors="replace")[-2500:]
        self.fail(description + " did not finish within its bound\n" + detail)

    def _start(self, source, timeout=10):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(SCRIPTS)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        config = {"policy": self.policy, "ledger": str(self.ledger.path),
                  "run_id": "interrupted-attempt", "output": str(self.output),
                  "result": str(self.root / "result.json"), "source": source,
                  "timeout": timeout}
        log = (self.root / "coordinator.log").open("wb")
        self.streams.append(log)
        process = subprocess.Popen([sys.executable, "-B", str(self.coordinator_source), json.dumps(config)],
                                   cwd=self.root, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=os.name == "posix")
        self.children.append(process)
        self._remember(process_identity.identity(process.pid))
        return process

    def _sentinel(self):
        process = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(60)"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=os.name == "posix")
        self.children.append(process)
        self._remember(process_identity.identity(process.pid))
        return process

    def _payload(self, *, helper=True):
        source = ("import json, os, signal, sys, time\nfrom pathlib import Path\n"
                  "from evidence.process_identity import identity\n"
                  "Path('payload.json').write_text(json.dumps(identity()), encoding='utf-8')\n"
                  "Path('observation.txt').write_text('preserved observation\\n', encoding='utf-8')\n"
                  "print('retained diagnostic', flush=True)\n")
        if helper:
            helper_source = ("import json, os, signal, time\nfrom pathlib import Path\n"
                             "from evidence.process_identity import identity\n"
                             "if os.name == 'posix': signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                             "Path('helper.json').write_text(json.dumps(identity()), encoding='utf-8')\n"
                             "time.sleep(60)\n")
            source += ("from evidence.producer_runtime import spawn_managed\n"
                       "helper = spawn_managed([sys.executable, '-B', '-c', " + repr(helper_source) + "])\n")
        return source + "time.sleep(60)\n"

    def _marker(self, name):
        path = self.output / name
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        self._remember(value)
        return value

    def _ready(self, *, helper=True):
        payload = self._wait(lambda: self._marker("payload.json"), "payload registration")
        child = self._wait(lambda: self._marker("helper.json"), "helper registration") if helper else None
        record = self._wait(lambda: self._record() if self._record() and self._record().get("guardian") else None,
                            "guardian registration")
        return payload, child, record

    def _gone(self, identity):
        self._wait(lambda: process_identity.state(identity) == "gone", "owned process exit", timeout=8)

    def _force_coordinator(self, process):
        if process.poll() is not None:
            return
        if os.name == "posix":
            # This fixture deliberately kills the coordinator's entire group.
            # The guardian and registered launch gates must be outside it.
            self.assertEqual(os.getpgid(process.pid), process.pid)
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)

    def tearDown(self):
        # Failed assertions must not leak real processes. Only fixture-owned
        # Popen handles and recorded process-birth identities authorize cleanup.
        errors = []
        try:
            for process in self.children:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            records = self._records()
            # A controller can die while its guardian is still registering.
            # Let that bounded startup publish ownership before final cleanup.
            deadline = time.monotonic() + 2
            while any(item.get("status") == "launching" and not item.get("guardian") for item in records):
                if time.monotonic() >= deadline:
                    break
                time.sleep(.02)
                records = self._records()
            for record in records:
                guardian = record.get("guardian")
                if guardian and process_identity.state(guardian) == "alive":
                    process_identity.terminate(guardian, force=True)
            records = self._records()
            for record in records:
                if any(process_identity.state(item["identity"]) == "alive"
                       for item in record.get("processes", {}).values()):
                    stop_registered(self.ledger, record["attempt_id"])
            for owned in self.identities.values():
                if process_identity.state(owned) == "alive":
                    process_identity.terminate(owned, force=True)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                remaining = [item for item in self.identities.values()
                             if process_identity.state(item) != "gone"]
                if not remaining:
                    break
                time.sleep(.02)
            else:
                errors.append("unverified fixture process cleanup: " + repr(remaining))
        except BaseException as error:
            errors.append(str(error))
        finally:
            for stream in self.streams:
                stream.close()
            self.ledger.close()
        if errors:
            # Retain diagnostics if ownership/exit could not be verified.
            self.temporary._finalizer.detach()
            self.fail("; ".join(errors) + "; fixture retained at " + str(self.root))
        self.temporary.cleanup()

    def test_coordinator_group_kill_retains_outputs_settles_once_and_allows_distinct_retry(self):
        sentinel = self._sentinel()
        coordinator = self._start(self._payload())
        payload, helper, record = self._ready()
        if os.name == "posix":
            self.assertNotEqual(os.getpgid(record["guardian"]["pid"]), coordinator.pid)
            self.assertNotEqual(os.getpgid(payload["pid"]), os.getpgid(helper["pid"]))
        self._force_coordinator(coordinator)
        self._wait(lambda: self._record().get("status") == "terminal", "guardian recovery")
        self._gone(payload)
        self._gone(helper)
        self.assertIsNone(sentinel.poll(), "unrelated process was stopped")
        snapshot = self.ledger.snapshot()
        self.assertEqual(snapshot["reservations"], [], self._record().get("result"))
        self.assertEqual(snapshot["runs"][0]["status"], "incomplete")
        self.assertTrue(snapshot["accounting_complete"])
        self.assertEqual((self.output / "observation.txt").read_text(), "preserved observation\n")
        self.assertIn("retained diagnostic", (self.output / "producer.log").read_text())
        charged = snapshot["totals"]["project_generated_bytes"]
        self.assertGreater(charged, len(b"preserved observation\n"))
        before = self._record()
        recover_producers(self.ledger, dry_run=True)
        self.assertEqual(self._record(), before)
        recover_producers(self.ledger, dry_run=False)
        recover_producers(self.ledger, dry_run=False)
        self.assertEqual(self.ledger.snapshot()["totals"]["project_generated_bytes"], charged)
        retry = self.root / "retry"
        retry.mkdir()
        result = run_producer(self.ledger, "distinct-retry", "unit-fixture", retry,
                             [sys.executable, "-B", "-c", "from pathlib import Path; Path('retry.txt').write_bytes(b'retry')"],
                             1000, 3, timeout=5, poll_interval=.02)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.ledger.snapshot()["totals"]["project_generated_bytes"], charged + 5)
        self.assertEqual(self.ledger.snapshot()["runs"][0]["status"], "incomplete")
        self.assertIsNone(sentinel.poll())

    def test_lost_guardian_keeps_uncertain_hold_and_recovery_does_not_authorize_retry(self):
        sentinel = self._sentinel()
        coordinator = self._start(self._payload())
        payload, helper, record = self._ready()
        self.assertEqual(process_identity.terminate(record["guardian"], force=True), "signalled")
        self._force_coordinator(coordinator)
        self._gone(record["guardian"])
        before = self._record()
        recover_producers(self.ledger, dry_run=True)
        self.assertEqual(self._record(), before, "dry-run changed ownership records")
        recover_producers(self.ledger, dry_run=False)
        self._gone(payload)
        self._gone(helper)
        snapshot = self.ledger.snapshot()
        self.assertFalse(snapshot["accounting_complete"])
        self.assertEqual(len(snapshot["reservations"]), 1)
        self.assertEqual(snapshot["totals"]["pending_generated_bytes"], 65536)
        self.assertEqual(snapshot["runs"][0]["status"], "incomplete")
        self.assertTrue((self.output / "observation.txt").is_file())
        with self.assertRaisesRegex(EvidenceError, "accounting recovery required"):
            self.ledger.reserve("unsafe-retry", "unit-fixture", 1, 1)
        charged = snapshot["totals"]["project_generated_bytes"]
        recover_producers(self.ledger, dry_run=False)
        self.assertEqual(self.ledger.snapshot()["totals"]["project_generated_bytes"], charged)
        self.assertEqual(len(self.ledger.snapshot()["reservations"]), 1)
        self.assertIsNone(sentinel.poll(), "unrelated process was stopped")

    def test_timeout_stops_separate_registered_term_resistant_helper(self):
        # Allow the nested Python launch gates to initialize on Windows CI;
        # the payload/helper still outlive this bounded producer timeout.
        coordinator = self._start(self._payload(), timeout=4)
        payload, helper, _ = self._ready()
        coordinator.wait(timeout=12)
        result = json.loads((self.root / "result.json").read_text())
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("timeout", result["problem"])
        self._gone(payload)
        self._gone(helper)
        self.assertEqual(self.ledger.snapshot()["reservations"], [], result)
        self.assertTrue((self.output / "observation.txt").is_file())

    @unittest.skipUnless(os.name == "posix", "SIGINT cancellation is a POSIX fixture")
    def test_cooperative_coordinator_cancellation_retains_failure_and_cleans_helpers(self):
        coordinator = self._start(self._payload())
        payload, helper, _ = self._ready()
        coordinator.send_signal(signal.SIGINT)
        coordinator.wait(timeout=12)
        self._wait(lambda: self._record().get("status") == "terminal", "cancelled guardian settlement")
        self._gone(payload)
        self._gone(helper)
        self.assertEqual(self.ledger.snapshot()["runs"][0]["status"], "incomplete")
        self.assertEqual(self.ledger.snapshot()["reservations"], [], self._record().get("result"))
        self.assertTrue((self.output / "observation.txt").is_file())

    def test_registered_empty_directory_is_removed_and_populated_diagnostics_are_retained(self):
        source = ("from pathlib import Path\n"
                  "from evidence.producer_runtime import register_temporary_directory\n"
                  "for name in ('empty-resource', 'diagnostics'):\n"
                  " Path(name).mkdir(); register_temporary_directory(Path(name))\n"
                  "Path('diagnostics/observation.txt').write_text('retained detail')\n"
                  "raise SystemExit(7)\n")
        result = run_producer(self.ledger, "resource-attempt", "unit-fixture", self.output,
                             [sys.executable, "-B", "-c", source], 65536, 20,
                             timeout=5, poll_interval=.02)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["exit_code"], 7)
        self.assertFalse((self.output / "empty-resource").exists())
        self.assertEqual((self.output / "diagnostics/observation.txt").read_text(), "retained detail")
        self.assertEqual(self.ledger.snapshot()["reservations"], [])
        self.assertTrue(self.ledger.snapshot()["accounting_complete"])

    def test_resource_registration_rejects_unowned_directory(self):
        outside = self.root / "unowned-directory"
        outside.mkdir()
        source = ("from evidence.producer_runtime import register_temporary_directory\n"
                  "register_temporary_directory(" + repr(str(outside)) + ")\n")
        result = run_producer(self.ledger, "resource-attempt", "unit-fixture", self.output,
                             [sys.executable, "-B", "-c", source], 65536, 20,
                             timeout=5, poll_interval=.02)
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(outside.is_dir())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertIn("inside the managed output root", (self.output / "producer.log").read_text())
        self.assertEqual(self.ledger.snapshot()["reservations"], [])

    def test_replaced_temporary_directory_identity_retains_resource_and_capacity(self):
        source = ("from pathlib import Path\n"
                  "from evidence.producer_runtime import register_temporary_directory\n"
                  "original = Path('temporary-resource'); original.mkdir()\n"
                  "register_temporary_directory(original)\n"
                  "original.rename('preserved-original')\n"
                  "original.mkdir()\n"
                  "(original / 'observation.txt').write_text('replacement retained')\n")
        result = run_producer(self.ledger, "resource-attempt", "unit-fixture", self.output,
                             [sys.executable, "-B", "-c", source], 65536, 20,
                             timeout=5, poll_interval=.02)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("identity changed", result["cleanup_problem"])
        self.assertTrue((self.output / "preserved-original").is_dir())
        self.assertEqual((self.output / "temporary-resource/observation.txt").read_text(), "replacement retained")
        snapshot = self.ledger.snapshot()
        self.assertFalse(snapshot["accounting_complete"])
        self.assertEqual(len(snapshot["reservations"]), 1)
        self.assertEqual(snapshot["totals"]["pending_generated_bytes"], 65536)
        with self.assertRaisesRegex(EvidenceError, "accounting recovery required"):
            self.ledger.reserve("unsafe-retry", "unit-fixture", 1, 1)


if __name__ == "__main__":
    unittest.main()
