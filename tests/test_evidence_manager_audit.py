"""Regression coverage for shared accounting, retained packs and active adoption."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import json
import os
import socket
from pathlib import Path
import subprocess
import sqlite3
import sys
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import test_evidence_manager as fixtures
import test_evidence_transports as transport_fixtures
from evidence.accounting import Accounting, BudgetExceeded
from evidence.archive import build_pack
from evidence.io import EvidenceError, hash_file, atomic_json, read_json
from evidence.manager import Manager
from evidence.producer import run_producer
from evidence.resolver import EvidenceResolver


class ManagerAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EvidenceManagerTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manager = self.fixture.manager
        self.base, self.policy = self.fixture.base, self.fixture.policy

    def cold(self, name="cold"):
        return Manager(fixtures.ObservedTransport(self.fixture.store), self.base / name, self.policy)

    def ledger(self):
        return Accounting(self.manager.state / "accounting.sqlite", self.policy["project_id"], self.policy)

    def test_retired_original_remains_charged_until_shared_pack_is_deleted(self):
        paths = [self.fixture.file("one", b"a"), self.fixture.file("two", b"b")]
        refs = self.manager.archive(self.fixture.spec(*paths))
        self.assertEqual(1, self.manager.status()["physical_objects"])
        self.manager.cleanup(now=fixtures.SEALED_TIME + timedelta(days=30), dry_run=False,
            expire=True, protected_refs=[refs[1]["artifact_id"]], reference_snapshot_complete=True)
        status = self.manager.status()
        self.assertEqual(1, status["refs"])
        self.assertEqual(2, status["retained_unique_bytes"])
        self.assertEqual(2, status["retained_allowance_bytes"])
        self.policy["limits"].update(retained_stop_bytes=2, retained_warning_bytes=1)
        with self.ledger() as ledger, self.assertRaises(BudgetExceeded):
            ledger.reserve("new", "U-new", 1, 1, retained_bytes=1)
        cold = self.cold()
        self.assertEqual(2, cold.status()["retained_allowance_bytes"])
        self.manager.cleanup(now=fixtures.SEALED_TIME + timedelta(days=30), dry_run=False,
            expire=True, reference_snapshot_complete=True)
        self.assertEqual(0, self.manager.status()["retained_allowance_bytes"])
        self.assertEqual(2, self.manager.status()["gross_generated_bytes"])

    def test_explicit_authority_rejects_second_home_before_first_archive(self):
        with self.assertRaisesRegex(EvidenceError, "not initialized"):
            self.manager.assert_generation_authority()
        self.manager.initialize_generation_authority()
        self.manager.initialize_generation_authority()
        self.assertTrue(self.manager.assert_generation_authority()["coordinator_authorized"])
        cold = self.cold()
        self.assertFalse(cold.status()["coordinator_authorized"])
        with self.assertRaisesRegex(EvidenceError, "designated coordinator"):
            cold.initialize_generation_authority()
        with self.assertRaisesRegex(EvidenceError, "designated coordinator"):
            cold.assert_generation_authority()
        self.assertEqual([], self.fixture.transport.keys(self.manager.prefix + "packs/"))

    def test_sixteen_fresh_home_constructors_keep_one_coordinator_identity(self):
        start = threading.Barrier(16)
        home = self.base / "concurrent-fresh-home"
        def create(_):
            start.wait(timeout=10)
            return Manager(self.fixture.transport, home, self.policy)
        with ThreadPoolExecutor(max_workers=16) as pool:
            managers = list(pool.map(create, range(16)))
        self.assertEqual(1, len({manager.coordinator for manager in managers}))
        managers[0].initialize_generation_authority()
        reopened = Manager(self.fixture.transport, home, self.policy)
        self.assertEqual(managers[0].coordinator, reopened.coordinator)
        self.assertTrue(reopened.assert_generation_authority()["coordinator_authorized"])

    def test_second_constructor_cannot_replace_first_in_progress_identity(self):
        home = self.base / "paused-fresh-home"
        writing, release, second_started = threading.Event(), threading.Event(), threading.Event()
        writes = []
        def delayed_write(path, value):
            if Path(path).name == "coordinator.json":
                writes.append(value["id"])
                writing.set()
                self.assertTrue(release.wait(10))
            return atomic_json(path, value)
        def second():
            second_started.set()
            return Manager(self.fixture.transport, home, self.policy)
        with patch("evidence.manager.atomic_json", side_effect=delayed_write), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(Manager, self.fixture.transport, home, self.policy)
            try:
                self.assertTrue(writing.wait(10))
                following = pool.submit(second)
                self.assertTrue(second_started.wait(10))
                self.assertFalse(following.done())
            finally:
                release.set()
            winner, loser = first.result(timeout=10), following.result(timeout=10)
        self.assertEqual([winner.coordinator], writes)
        self.assertEqual(winner.coordinator, loser.coordinator)

    def test_constructor_recovers_after_process_dies_before_or_after_identity_publication(self):
        policy_file = self.base / "crash-policy.json"
        atomic_json(policy_file, self.policy)
        for stage in ("before", "after"):
            with self.subTest(stage=stage):
                home = self.base / ("crash-" + stage)
                code = "\n".join([
                    "import json, os, sys",
                    "from pathlib import Path",
                    "sys.path.insert(0, sys.argv[1])",
                    "import evidence.manager as module",
                    "from evidence.transports import LocalTransport",
                    "original = module.atomic_json",
                    "def interrupt(path, value):",
                    "    if Path(path).name == 'coordinator.json':",
                    "        if sys.argv[5] == 'after': original(path, value)",
                    "        os._exit(37)",
                    "    return original(path, value)",
                    "module.atomic_json = interrupt",
                    "module.Manager(LocalTransport(sys.argv[2]), sys.argv[3], json.loads(Path(sys.argv[4]).read_text()))",
                ])
                result = subprocess.run([sys.executable, "-B", "-c", code,
                    str(fixtures.ROOT / "skills/to-sdd-pipeline/scripts"), str(self.fixture.store),
                    str(home), str(policy_file), stage], capture_output=True, text=True, timeout=10)
                self.assertEqual(37, result.returncode, result.stderr)
                identity = home / "projects" / self.policy["project_id"] / "coordinator.json"
                previous = json.loads(identity.read_text())["id"] if identity.exists() else None
                recovered = Manager(self.fixture.transport, home, self.policy)
                if previous:
                    self.assertEqual(previous, recovered.coordinator)
                self.assertEqual(recovered.coordinator, Manager(self.fixture.transport, home, self.policy).coordinator)

    def test_catalog_owner_release_waits_for_windows_stable_readers(self):
        original = Path.unlink
        attempts = []
        def release(path, *args, **kwargs):
            if path == self.manager.state / "catalog.lock/owner.json" and len(attempts) < 3:
                attempts.append(path)
                error = PermissionError("synthetic Windows stable reader")
                error.winerror = 32
                raise error
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", release):
            with self.manager.locked():
                pass
        self.assertEqual(3, len(attempts))
        self.assertFalse((self.manager.state / "catalog.lock").exists())
        with self.manager.locked(timeout=0.01):
            pass

    def test_catalog_waiter_retries_windows_owner_open_sharing_violations(self):
        waiting = Manager(self.fixture.transport, self.fixture.home, self.policy)
        retried = threading.Event()
        attempts = []
        owner = self.manager.state / "catalog.lock/owner.json"
        def transient_read(path, limit):
            if Path(path) == owner and len(attempts) < 3:
                attempts.append(path)
                if len(attempts) == 3:
                    retried.set()
                cause = PermissionError("synthetic Windows publisher/remover")
                cause.winerror = 32
                raise EvidenceError("cannot safely open " + str(path)) from cause
            return read_json(path, limit)
        def acquire():
            with waiting.locked(timeout=5):
                return True
        with patch("evidence.manager.read_json", side_effect=transient_read), ThreadPoolExecutor(max_workers=1) as pool:
            with self.manager.locked():
                result = pool.submit(acquire)
                self.assertTrue(retried.wait(3), "waiter did not retry transient owner-open failures")
                self.assertFalse(result.done())
            self.assertTrue(result.result(timeout=5))
        self.assertEqual(3, len(attempts))
        self.assertFalse((self.manager.state / "catalog.lock").exists())

    def test_disappearing_normal_lock_is_retried_from_one_directory_snapshot(self):
        lock = self.manager.state / "catalog.lock"
        lock.mkdir()
        atomic_json(lock / "owner.json", {"pid": os.getpid(), "host": socket.gethostname(),
            "coordinator": self.manager.coordinator})
        original = Path.mkdir
        released = []
        def disappearing(path, *args, **kwargs):
            if path == lock and not released:
                try:
                    original(path, *args, **kwargs)
                except FileExistsError:
                    # A former client releases after mkdir observed existence,
                    # before this waiter can inspect the directory.
                    (lock / "owner.json").unlink()
                    lock.rmdir()
                    released.append(True)
                    raise
            return original(path, *args, **kwargs)
        with patch.object(Path, "mkdir", disappearing):
            with self.manager.locked(timeout=2):
                self.assertTrue((lock / "owner.json").is_file())
        self.assertEqual([True], released)
        self.assertFalse(lock.exists())

    def test_released_owner_exit_is_not_reported_as_a_stale_lock(self):
        lock = self.manager.state / "catalog.lock"
        lock.mkdir()
        previous_pid = 2**30
        atomic_json(lock / "owner.json", {"pid": previous_pid, "host": socket.gethostname(),
            "coordinator": self.manager.coordinator})
        original = self.manager._owner_alive
        exited = []
        def released_then_exited(pid):
            if pid == previous_pid:
                (lock / "owner.json").unlink()
                lock.rmdir()
                exited.append(True)
                return False
            return original(pid)
        with patch.object(self.manager, "_owner_alive", side_effect=released_then_exited):
            with self.manager.locked(timeout=2):
                pass
        self.assertEqual([True], exited)
        self.assertFalse(lock.exists())

    def test_two_reconcilers_cannot_remove_a_new_live_catalog_lock(self):
        lock = self.manager.state / "catalog.lock"
        lock.mkdir()
        atomic_json(lock / "owner.json", {"pid": 2**30, "host": socket.gethostname(),
            "coordinator": self.manager.coordinator})
        second = Manager(self.fixture.transport, self.fixture.home, self.policy)
        holder = Manager(self.fixture.transport, self.fixture.home, self.policy)
        blocked, retire, started_reaper, started_holder, holding, finish = (threading.Event() for _ in range(6))
        original = self.manager._release_owner_file
        def paused_retirement(path):
            original(path)
            blocked.set()
            self.assertTrue(retire.wait(5))
        def second_reaper():
            started_reaper.set()
            try:
                return second._reconcile_lock(False)
            except EvidenceError as error:
                return str(error)
        def new_holder():
            started_holder.set()
            with holder.locked(timeout=5):
                holding.set()
                self.assertTrue(finish.wait(5))
        with patch.object(self.manager, "_release_owner_file", side_effect=paused_retirement), ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(self.manager._reconcile_lock, False)
            try:
                self.assertTrue(blocked.wait(3))
                following = pool.submit(second_reaper)
                fresh = pool.submit(new_holder)
                self.assertTrue(started_reaper.wait(3))
                self.assertTrue(started_holder.wait(3))
                self.assertFalse(following.done())
                self.assertFalse(holding.is_set())
                retire.set()
                self.assertTrue(first.result(timeout=5)[0]["verified"])
                self.assertTrue(holding.wait(5))
                result = following.result(timeout=5)
                self.assertTrue(result == [] or "still running" in result, result)
                self.assertTrue((lock / "owner.json").is_file())
                contender = Manager(self.fixture.transport, self.fixture.home, self.policy)
                with self.assertRaisesRegex(EvidenceError, "busy"):
                    with contender.locked(timeout=0.02):
                        self.fail("another operation entered the live catalog lock")
            finally:
                retire.set()
                finish.set()
            fresh.result(timeout=5)
        self.assertFalse(lock.exists())

    def legacy_exited_intent(self, run_id, reserve_files):
        # Publish the original v1 intent shape to exercise persisted historical
        # records; do not spoof the process identity used for new launches.
        intent = str(uuid.uuid4())
        with self.manager.locked():
            self.manager._publish(self.manager._catalog(mutation=True), {
                "version": 1, "generation_intents": {intent: {
                    "run_id": run_id, "unit_id": "U-1", "reserve_bytes": 20,
                    "reserve_files": reserve_files, "owner_pid": 2**30,
                    "owner_host": socket.gethostname()}}})
        return intent

    def test_unsettled_remote_generation_reports_unknown_after_loss_of_home(self):
        self.manager.initialize_generation_authority()
        intent = self.legacy_exited_intent("failed-run", 2)
        cold = self.cold()
        status = cold.status()
        self.assertFalse(status["accounting_complete"])
        self.assertIsNone(status["gross_generated_bytes"])
        self.assertIn(intent, status["accounting"]["pending_generation_intents"])
        with self.assertRaisesRegex(EvidenceError, "coordinator authority"):
            cold.assert_generation_authority()
        with self.assertRaisesRegex(EvidenceError, "unknown local accounting"):
            self.manager.assert_generation_authority()

    def test_failed_producer_charges_recover_remotely_without_any_archive(self):
        self.manager.initialize_generation_authority()
        intent = self.manager.begin_generation("failed-run", "U-1", 20, 2)
        output = self.base / "failed-output"
        output.mkdir()
        with self.ledger() as ledger:
            result = run_producer(ledger, "failed-run", "U-1", output,
                [sys.executable, "-c", "from pathlib import Path; Path('data').write_bytes(b'123456'); raise SystemExit(3)"],
                20, 2, poll_interval=0.02)
        self.assertEqual("incomplete", result["status"])
        self.assertTrue(self.manager.finish_generation(intent)["settled"])
        cold = self.cold()
        self.assertFalse(cold.status()["accounting_complete"])
        self.assertEqual(6, cold.status()["known_gross_generated_bytes"])
        self.assertEqual(0, cold.status()["physical_objects"])
        self.assertEqual([], self.fixture.transport.keys(self.manager.prefix + "packs/"))

    def test_shared_run_workers_settle_only_their_own_durable_intents(self):
        self.manager.initialize_generation_authority()
        first = self.manager.begin_generation("shared", "U-1", 20, 1)
        with self.ledger() as ledger:
            first_hold = ledger.reserve("shared", "U-1", 20, 1)
        second = self.manager.begin_generation("shared", "U-1", 20, 1)
        with self.ledger() as ledger:
            second_hold = ledger.reserve("shared", "U-1", 20, 1)
            ledger.settle(first_hold, 6, 1)
        result = self.manager.finish_generation(first, first_hold)
        self.assertTrue(result["settled"])
        self.assertTrue(result["pending_workers"])
        status = self.cold().status()
        self.assertFalse(status["accounting_complete"])
        self.assertEqual(6, status["known_gross_generated_bytes"])
        self.assertEqual([second], list(status["accounting"]["pending_generation_intents"]))
        with self.ledger() as ledger:
            ledger.settle(second_hold, 6, 1)
        self.manager.finish_generation(second, second_hold)
        status = self.cold("finished-cold").status()
        self.assertFalse(status["accounting_complete"])
        self.assertEqual(12, status["known_gross_generated_bytes"])

    def test_reconcile_closes_exited_prelaunch_intent_but_retains_live_owner(self):
        self.manager.initialize_generation_authority()
        live = self.manager.begin_generation("live", "U-1", 20, 1)
        actions = self.manager.reconcile(dry_run=False)
        self.assertTrue(any(action.get("intent_id") == live and action["action"] == "generation-intent-retained" for action in actions))
        self.manager.finish_generation(live)
        exited = self.legacy_exited_intent("not-launched", 1)
        self.assertFalse(self.manager.status()["accounting_complete"])
        actions = self.manager.reconcile(dry_run=True)
        self.assertTrue(any(action.get("intent_id") == exited and action["action"] == "reconcile-exited-generation-intent" for action in actions))
        self.assertFalse(self.manager.status()["accounting_complete"])
        actions = self.manager.reconcile(dry_run=False)
        self.assertTrue(any(action.get("intent_id") == exited and action.get("verified") for action in actions))
        self.assertTrue(self.manager.status()["accounting_complete"])
        self.assertEqual(0, self.manager.status()["gross_generated_bytes"])

    def test_two_output_archives_publish_shared_run_total_only_once(self):
        specs = []
        for index in range(2):
            output = self.base / ("worker-" + str(index))
            output.mkdir()
            with self.ledger() as ledger:
                result = run_producer(ledger, "shared-run", "U-1", output,
                    [sys.executable, "-c", "from pathlib import Path; Path('data').write_bytes(b'123456')"],
                    20, 2, poll_interval=0.02, complete_run=False)
            specs.append({"version": 1, "managed_output_id": result["output_id"], "files": [{
                "path": str(output / "data"), "original_path": "worker-" + str(index) + "/data",
                "sealed_at": fixtures.SEALED, "kind": "diagnostic", "schema": "evidence-bytes-v1",
                "bindings": {}, "provenance": {"run_id": "shared-run", "unit_id": "U-1"}}]})
        with self.ledger() as ledger:
            ledger.complete_run("shared-run")
        before = self.manager.status()
        for spec in specs:
            self.manager.archive(spec)
        after = self.manager.status()
        self.assertEqual(12, before["gross_generated_bytes"])
        self.assertEqual(before["gross_generated_bytes"], after["gross_generated_bytes"])
        self.assertEqual(before["original_logical_files"], after["original_logical_files"])
        self.assertEqual(12, self.cold().status()["known_gross_generated_bytes"])

    def test_four_cli_workers_launch_concurrently_and_serialize_catalog_updates(self):
        self.manager.initialize_generation_authority()
        policy_file, config_file = self.base / "policy.json", self.base / "config.json"
        atomic_json(policy_file, self.policy)
        atomic_json(config_file, {"version": 1, "store_id": self.policy["store_id"], "provider": "local",
            "destination": str(self.fixture.store), "evidence_home": str(self.fixture.home)})
        release = self.base / "release-workers"
        # Only the parent releases this barrier. A slow fourth startup must not
        # let earlier producers finish before simultaneous liveness is checked.
        readiness_timeout = 120
        code = ("from pathlib import Path; import time; Path('started').write_bytes(b'123456')\n"
                "while not Path(" + repr(str(release)) + ").exists(): time.sleep(0.02)\n")
        processes, outputs, results = [], [], []
        started = time.monotonic()
        deadline = started + readiness_timeout
        try:
            for index in range(4):
                output = self.base / ("concurrent-" + str(index))
                outputs.append(output)
                command = [sys.executable, "-B", str(fixtures.ROOT / "skills/to-sdd-pipeline/scripts/evidence_store.py"),
                    "run", "--policy", str(policy_file), "--config", str(config_file), "--run-id", "concurrent",
                    "--unit-id", "U-1", "--output-dir", str(output), "--reserve-bytes", "100", "--reserve-files", "3",
                    "--timeout", str(readiness_timeout + 60), "--defer-run-completion", "--", sys.executable, "-B", "-c", code]
                processes.append(subprocess.Popen(command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            while time.monotonic() < deadline and not all((path / "started").exists() for path in outputs):
                if any(process.poll() is not None for process in processes):
                    break
                time.sleep(0.02)
            ready = [(path / "started").exists() for path in outputs]
            alive = [process.poll() is None for process in processes]
            simultaneous = all(ready) and all(alive)
            readiness = {"elapsed_seconds": round(time.monotonic() - started, 3), "ready": ready, "alive": alive}
        finally:
            release.touch()
            for process in processes:
                timed_out = False
                try:
                    stdout, stderr = process.communicate(timeout=120)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    process.terminate()
                    try:
                        stdout, stderr = process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        stdout, stderr = process.communicate(timeout=10)
                results.append({"code": process.returncode, "timed_out": timed_out, "stdout": stdout, "stderr": stderr})
        self.assertTrue(simultaneous, {"readiness": readiness, "workers": results})
        self.assertTrue(all(result["code"] == 0 and not result["timed_out"] for result in results), results)
        status = self.manager.status()
        self.assertTrue(status["accounting_complete"], status)
        self.assertEqual(24, status["gross_generated_bytes"])
        with self.ledger() as ledger:
            self.assertEqual([], ledger.snapshot()["reservations"])
            ledger.complete_run("concurrent")

    def test_host_control_and_independent_materialization_have_one_combined_hold(self):
        owner = self
        class HostedTransport(fixtures.ObservedTransport):
            control_peak_bytes = 8192
            def working_overhead(self, *, upload_bytes=0, download_bytes=0):
                return self.control_peak_bytes + max(upload_bytes, download_bytes)
            def put(self, key, source_path):
                # A real upload keeps its transfer checkpoint after the private
                # request/response queue and materialized original are removed.
                atomic_json(self.host_session_path / "checkpoint.json", {"synthetic": "x" * 3000})
                return super().put(key, source_path)
            def get(self, locator, destination_path, max_bytes):
                with sqlite3.connect(owner.manager.state / "accounting.sqlite") as connection:
                    held = connection.execute("SELECT SUM(bytes) FROM working_reservations WHERE state='pending'").fetchone()[0]
                self.download_holds.append((max_bytes, held))
                return super().get(locator, destination_path, max_bytes)
        hosted = HostedTransport(self.fixture.store)
        hosted.host_session_path = self.base / "private-session"
        hosted.host_session_path.mkdir()
        hosted.download_holds = []
        atomic_json(hosted.host_session_path / "session.json", {"synthetic": True})
        self.manager = Manager(hosted, self.fixture.home, self.policy)
        self.manager.initialize_generation_authority()
        self.assertTrue(self.manager.assert_generation_authority()["coordinator_authorized"])
        # Reading one original requires its normal download plus the private
        # host materialization and a single bounded control queue.
        self.assertTrue(hosted.download_holds)
        self.assertTrue(all(held >= hosted.control_peak_bytes + size * 2 for size, held in hosted.download_holds))
        self.assertGreaterEqual(self.manager.status()["local_working_bytes"], 3000)

    def test_connected_and_rclone_checkpoints_have_their_own_exact_allocation(self):
        for provider, external in (("connected", False), ("connected", True), ("rclone", False)):
            with self.subTest(provider=provider, external=external):
                policy = deepcopy(self.policy)
                policy["provider"] = "google-drive"
                home = self.base / (provider + ("-external" if external else "-internal"))
                state = home / "projects" / policy["project_id"]
                transfer_dir = self.base / "external-transfers" if external else state / "transfers"
                if provider == "connected":
                    transport = transport_fixtures.ConnectedDriveTransport(transport_fixtures.ConnectedFixture(),
                        "synthetic-folder", state_dir=transfer_dir, attempts=1)
                else:
                    fixture = transport_fixtures.RcloneDriveTransportTests(methodName="runTest")
                    fixture.setUp()
                    self.addCleanup(fixture.doCleanups)
                    transport = transport_fixtures.RcloneDriveTransport("fixture:objects", config=fixture.config,
                        executable=str(fixture.executable), state_dir=transfer_dir, attempts=1)
                manager = Manager(transport, home, policy)
                self.assertTrue(manager.initialize_generation_authority()["coordinator_authorized"])
                value = {"version": 1, "synthetic": "checkpoint retry"}
                manager._put_json(manager.prefix + "synthetic/", value)
                manager._put_json(manager.prefix + "synthetic/", value)
                checkpoint_files = list(transfer_dir.glob("*.json"))
                self.assertEqual(2, len(checkpoint_files))
                checkpoint_bytes = sum(path.stat().st_size for path in checkpoint_files)
                with Accounting(state / "accounting.sqlite", policy["project_id"], policy) as ledger:
                    manager._local_records(ledger)
                    actual = ledger.connection.execute("SELECT bytes FROM local_usage WHERE key='transport-checkpoints'").fetchone()[0]
                    metadata = ledger.connection.execute("SELECT bytes,files FROM metadata_usage WHERE key='transport-checkpoints'").fetchone()
                    self.assertEqual(checkpoint_bytes, actual)
                    self.assertEqual((checkpoint_bytes, 2), tuple(metadata))
                    self.assertFalse(ledger.connection.execute("SELECT 1 FROM working_reservations WHERE state='pending'").fetchone())
                self.assertTrue(all(path not in manager._metadata_records(include_checkpoints=False) for path in checkpoint_files))
                self.assertEqual(checkpoint_bytes, manager._usage(include_ledger=False) - manager._usage(include_ledger=False, include_checkpoints=False))

    def test_host_overhead_is_reserved_before_calling_transport(self):
        class OversizedHost(fixtures.ObservedTransport):
            invoked = False
            def working_overhead(self, *, upload_bytes=0, download_bytes=0):
                return self.maximum
            def keys(self, prefix=""):
                self.invoked = True
                return super().keys(prefix)
        hosted = OversizedHost(self.fixture.store)
        hosted.maximum = self.policy["limits"]["local_stop_bytes"] + 1
        manager = Manager(hosted, self.fixture.home, self.policy)
        with self.assertRaises(BudgetExceeded):
            manager.status()
        self.assertFalse(hosted.invoked)

    def import_mapping(self, payload):
        source = self.fixture.file("import-report.json", json.dumps(payload).encode())
        digest, size = hash_file(source)
        pack_path = self.base / "existing-report.zip"
        pack = build_pack([{"path": source, "sha256": digest, "size": size}], pack_path, 1024**2, 10)
        pack["locator"] = self.fixture.transport.put("original/report.zip", pack_path)
        ref = {"version": 1, "artifact_id": "original-report", "sha256": digest, "size": size,
            "kind": "diagnostic", "schema": "evidence-json-v1", "provenance": {"run_id": "old", "unit_id": "U-old"},
            "bindings": {}, "locator": {"store_id": self.policy["store_id"], "provider": "local",
                **pack["locator"], "pack_sha256": pack["sha256"], "pack_size": pack["size"], "member": pack["members"][0]["member"]},
            "retention": {"sealed_at": fixtures.SEALED, "class": "diagnostic"}}
        return {"version": 1, "refs": [ref], "packs": {pack["sha256"]: pack}}

    def missing_ref(self):
        return {"version": 1, "artifact_id": "missing", "sha256": "a" * 64, "size": 1,
            "kind": "visual", "schema": "evidence-bytes-v1", "provenance": {"run_id": "old"}, "bindings": {},
            "locator": {"store_id": self.policy["store_id"], "provider": "local", "object_id": "missing.zip",
                "key": "missing.zip", "pack_sha256": "b" * 64, "pack_size": 200, "member": "missing"},
            "retention": {"sealed_at": fixtures.SEALED, "class": "diagnostic"}}

    def test_active_import_missing_nested_capture_fails_before_catalog_publication(self):
        mapping = self.import_mapping({"captures": [{"evidence_ref": self.missing_ref()}]})
        puts = list(self.fixture.transport.puts)
        with self.assertRaisesRegex(EvidenceError, "missing/mismatched"):
            self.manager.import_archive(mapping)
        self.assertEqual(puts, self.fixture.transport.puts)
        self.assertEqual({}, self.manager._catalog()["refs"])

    def test_inactive_history_is_preserved_without_preparing_missing_capture(self):
        payload = {"result": "passed", "history": [{"evidence_ref": self.missing_ref()}]}
        mapping = self.import_mapping(payload)
        original = deepcopy(mapping)
        ref = self.manager.import_archive(mapping)[0]
        self.assertEqual(payload, EvidenceResolver(self.manager.cache).json(ref))
        self.assertEqual(original, mapping)
        self.assertFalse((self.manager.cache / "receipts/missing.json").exists())

    def test_active_original_reference_alias_survives_import_and_cold_prepare(self):
        capture_path = self.fixture.file("capture.bin", b"original capture")
        digest, size = hash_file(capture_path)
        pack_path = self.base / "original-capture.zip"
        pack = build_pack([{"path": capture_path, "sha256": digest, "size": size}], pack_path, 1024**2, 10)
        pack["locator"] = self.fixture.transport.put("original/capture.zip", pack_path)
        capture_ref = self.missing_ref()
        capture_ref.update(artifact_id="original-capture", sha256=digest, size=size)
        capture_ref["locator"].update(**pack["locator"], pack_sha256=pack["sha256"], pack_size=pack["size"], member=pack["members"][0]["member"])
        payload = {"captures": [{"evidence_ref": capture_ref}]}
        mapping = self.import_mapping(payload)
        mapping["refs"].append(capture_ref)
        mapping["packs"][pack["sha256"]] = pack
        mapping["active_artifact_ids"] = ["original-report"]
        original = deepcopy(mapping)
        refs = self.manager.import_archive(mapping)
        self.assertEqual(original, mapping)
        self.assertEqual(payload, EvidenceResolver(self.manager.cache).json(refs[0]))
        cold = self.cold()
        cold.prepare([refs[0]])
        resolver = EvidenceResolver(cold.cache)
        self.assertEqual(payload, resolver.json(refs[0]))
        self.assertIn("original-capture", resolver.visited)
        self.assertTrue(resolver.references["original-capture"]["retention"]["imported"])


if __name__ == "__main__":
    unittest.main()
