"""Historical gaps remain charged while an explicitly scoped fresh run settles."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence.accounting import Accounting, BudgetExceeded
from evidence.io import EvidenceError
from evidence.policy import load_defaults
from evidence.producer import _run_monitored, recover_producers, run_producer
from evidence import process_identity, producer_runtime
from evidence.quarantine import canonical, digest, validate_quarantine_descriptor


def uncertain_fixture(ledger, root, *, run_id="old-run", unit_id="unit"):
    """Real dead owner, retained raw journal, current inventory and host assertion."""
    root = Path(root)
    output = root / (run_id + "-output")
    output.mkdir()
    child = subprocess.Popen([sys.executable, "-B", "-c", "import sys; sys.stdin.buffer.read()"],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=sys.platform != "win32")
    try:
        owner = process_identity.identity(child.pid)
    finally:
        child.stdin.close()
        child.wait(timeout=5)
    attempt = str(uuid.uuid4())
    reservation = ledger.reserve(run_id, unit_id, 512, 10, local_bytes=512, metadata_bytes=1024 * 1024)
    output_id = ledger.register_output(run_id, unit_id, output)
    (output / "original.txt").write_bytes(b"retained diagnostic")
    record = {"version": 1, "attempt_id": attempt, "run_id": run_id, "unit_id": unit_id,
              "reservation_id": reservation, "output_id": output_id, "intent_id": str(uuid.uuid4()),
              "coordinator": owner, "guardian": owner, "status": "stopping", "processes": {}, "resources": [],
              "output_dir": str(output), "output_identity": producer_runtime.directory_identity(output),
              "policy": ledger.policy, "observed_bytes": 600, "observed_files": 2,
              "result": {"status": "incomplete", "problem": "aggregate overrun", "cleanup_problem": "EPERM",
                         "gross_bytes": 600, "gross_files": 2, "observations": {}, "observations_in_ledger": False}}
    raw = json.dumps(record, sort_keys=True)
    ledger.connection.execute("INSERT INTO producer_sessions VALUES(?,?)", (attempt, raw))
    ledger.record_uncertain(reservation, 600, 2)
    journal = root / (run_id + "-external-journal.json")
    external = root / (run_id + "-external-disposition.json")
    journal.write_text(json.dumps({"run_id": run_id, "helpers": [], "resources": []}))
    external.write_text(json.dumps({"run_id": run_id, "all_external_helpers_stopped": True, "all_resources_disposed": True}))
    proof = {"version": 1, "kind": "producer-disposition", "attempt_id": attempt,
             "original_record_sha256": hashlib.sha256(raw.encode()).hexdigest(),
             "verifier": "isolated-test-host", "observed_at": datetime.now(timezone.utc).isoformat(),
             "external_disposition": {"coverage": "all-unregistered-helpers-and-resources",
                                      "journal": {"path": str(journal), "sha256": hashlib.sha256(journal.read_bytes()).hexdigest()},
                                      "proof": {"path": str(external), "sha256": hashlib.sha256(external.read_bytes()).hexdigest()},
                                      "limitations": "Host assertion binds external coverage; no reconstructed accounting or physical quota claim."}}
    return {"attempt": attempt, "reservation": reservation, "output_id": output_id, "output": output,
            "record": record, "raw": raw, "proof": proof, "journal": journal, "external": external}


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-quarantine-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "state" / "accounting.sqlite"
        self.policy = load_defaults()
        self.policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider="local")
        self.ledger = self.open()
        self.addCleanup(lambda: self.ledger.close())
        self.f = uncertain_fixture(self.ledger, self.root)

    def open(self):
        return Accounting(self.path, self.policy["project_id"], self.policy)

    def apply(self):
        return self.ledger.quarantine_producer(self.f["attempt"], self.f["proof"], dry_run=False)

    def originals(self):
        return {table: [tuple(row) for row in self.ledger.connection.execute("SELECT * FROM " + table + " ORDER BY 1")]
                for table in ("runs", "reservations", "uncertain_generation", "producer_sessions", "outputs", "observations")}

    def test_explicit_quarantine_preserves_every_original_and_full_hold(self):
        original = self.originals()
        before = self.ledger.snapshot()["totals"]
        with self.assertRaises(EvidenceError):
            self.ledger.require_generation_ready()
        preview = self.ledger.quarantine_producer(self.f["attempt"], self.f["proof"])
        self.assertEqual([], self.ledger.quarantines())
        self.assertEqual(original, self.originals())
        descriptor = self.apply()
        self.assertEqual(preview["original_record_sha256"], descriptor["original_record_sha256"])
        self.assertEqual(original, self.originals())
        self.assertEqual(descriptor, validate_quarantine_descriptor(deepcopy(descriptor), self.policy))
        readiness = self.ledger.generation_readiness()
        self.assertTrue(readiness["ready"], readiness)
        self.assertFalse(readiness["history_complete"])
        after = self.ledger.snapshot()
        self.assertFalse(after["accounting_complete"])
        self.assertTrue(after["totals_are_lower_bounds"])
        for key in ("project_generated_bytes", "project_generated_files", "pending_generated_bytes", "pending_generated_files", "pending_local_bytes", "pending_metadata_bytes"):
            self.assertEqual(before[key], after["totals"][key], key)
        actions = recover_producers(self.ledger, dry_run=False)
        self.assertFalse(actions["incomplete"], actions)
        self.assertEqual("quarantined", actions["actions"][0]["action"])
        self.assertTrue(actions["actions"][0]["historical_uncertainty"])
        self.assertEqual(original, self.originals())

    def test_real_fresh_managed_producer_completes_but_old_run_never_does(self):
        self.apply()
        fresh = self.root / "fresh"
        fresh.mkdir()
        result = run_producer(self.ledger, "fresh-run", "unit", fresh,
                              [sys.executable, "-B", "-c", "from pathlib import Path; Path('new.txt').write_bytes(b'new')"],
                              10000, 10, timeout=5, poll_interval=.02)
        self.assertEqual("complete", result["status"], result)
        snapshot = self.ledger.snapshot()
        self.assertFalse(snapshot["accounting_complete"])
        self.assertEqual(512, snapshot["totals"]["pending_generated_bytes"])
        self.assertEqual(2, next(row for row in snapshot["runs"] if row["id"] == "old-run")["gross_files"])
        self.assertEqual(1, next(row for row in snapshot["runs"] if row["id"] == "fresh-run")["ordinal"])
        with self.assertRaises(EvidenceError):
            self.ledger.complete_run("old-run")
        with self.assertRaises(EvidenceError):
            self.ledger.reserve("old-run", "unit", 1, 1)
        with self.assertRaises(EvidenceError):
            self.ledger.cancel(self.f["reservation"])
        with self.assertRaises(EvidenceError):
            self.ledger.settle(self.f["reservation"], 600, 2)

    def test_replay_concurrency_and_reopen_do_not_recharge_or_mutate_session(self):
        def apply_other():
            with self.open() as other:
                return other.quarantine_producer(self.f["attempt"], self.f["proof"], dry_run=False)
        with ThreadPoolExecutor(max_workers=2) as pool:
            descriptors = list(pool.map(lambda _: apply_other(), range(2)))
        self.assertEqual(descriptors[0], descriptors[1])
        self.assertEqual(descriptors[0], self.apply())
        self.assertEqual(600, self.ledger.snapshot()["totals"]["project_generated_bytes"])
        self.assertEqual(self.f["raw"], self.ledger.connection.execute("SELECT record FROM producer_sessions").fetchone()[0])
        with self.open() as reopened:
            self.assertTrue(reopened.generation_readiness()["ready"])
            self.assertEqual(descriptors, reopened.quarantines() * 2)

    def test_proof_and_descriptor_changes_fail_without_releasing_capacity(self):
        self.apply()
        changed = deepcopy(self.f["proof"])
        changed["verifier"] = "different"
        with self.assertRaisesRegex(EvidenceError, "immutable"):
            self.ledger.quarantine_producer(self.f["attempt"], changed, dry_run=False)
        row = self.ledger.connection.execute("SELECT record FROM producer_quarantines").fetchone()[0]
        value = json.loads(row)
        value["reservation"]["bytes"] = 0
        with self.assertRaisesRegex(EvidenceError, "digest"):
            validate_quarantine_descriptor(value, self.policy)
        self.ledger.connection.execute("UPDATE producer_quarantines SET record=?", (json.dumps(value),))
        self.assertFalse(self.ledger.generation_readiness()["ready"])
        before = self.f["raw"]
        self.assertTrue(recover_producers(self.ledger, dry_run=False)["incomplete"])
        self.assertEqual(before, self.ledger.connection.execute("SELECT record FROM producer_sessions").fetchone()[0])

    def test_current_raw_inventory_or_external_reference_change_blocks_readiness(self):
        self.apply()
        self.f["external"].write_text("changed assertion")
        self.assertFalse(self.ledger.generation_readiness()["ready"])

    def test_changed_preserved_output_blocks_readiness(self):
        self.apply()
        (self.f["output"] / "original.txt").write_bytes(b"changed")
        self.assertFalse(self.ledger.generation_readiness()["ready"])
        with self.assertRaises(EvidenceError):
            self.ledger.reserve("fresh", "unit", 1, 1)

    def test_masked_marker_revision_and_missing_checkpoint_always_block(self):
        self.apply()
        marker = self.ledger.recovery_dir / "marker.json"
        value = json.loads(marker.read_text())
        value["revision"] += 1
        marker.write_text(json.dumps(value))
        self.assertFalse(self.ledger.generation_readiness()["ready"])
        with self.assertRaises(EvidenceError):
            self.ledger.reserve("fresh", "unit", 1, 1)

    def test_unknown_owner_or_surviving_registered_resource_cannot_be_quarantined(self):
        record = deepcopy(self.f["record"])
        record["coordinator"]["host"] += "-foreign"
        self.ledger.connection.execute("UPDATE producer_sessions SET record=?", (json.dumps(record),))
        with self.assertRaisesRegex(EvidenceError, "exit"):
            self.apply()
        self.assertEqual([], self.ledger.quarantines())

    def test_live_owner_cannot_be_quarantined(self):
        record = deepcopy(self.f["record"])
        record["guardian"] = process_identity.identity()
        self.ledger.connection.execute("UPDATE producer_sessions SET record=?", (json.dumps(record),))
        with self.assertRaisesRegex(EvidenceError, "exit"):
            self.apply()

    def test_partial_external_coverage_and_symlink_proof_rejected(self):
        proof = deepcopy(self.f["proof"])
        proof["external_disposition"]["coverage"] = "some-helpers"
        with self.assertRaises(EvidenceError):
            self.ledger.quarantine_producer(self.f["attempt"], proof, dry_run=False)
        link = self.root / "proof-link"
        try:
            link.symlink_to(self.f["external"])
        except OSError:
            self.skipTest("host does not permit test symlinks")
        proof = deepcopy(self.f["proof"])
        proof["external_disposition"]["proof"]["path"] = str(link)
        with self.assertRaises(EvidenceError):
            self.ledger.quarantine_producer(self.f["attempt"], proof, dry_run=False)

    def test_held_floor_and_reservation_both_enforce_unchanged_policy_bounds(self):
        self.apply()
        # Original gross 600 plus full hold 512; an extra 1 must not fit a1112 cap.
        policy = deepcopy(self.policy)
        policy["limits"]["unit_stop_bytes"] = 1112
        with patch.object(self.ledger, "_violations", wraps=self.ledger._violations) as observed:
            totals = self.ledger._totals("fresh", "unit")
            original = self.ledger.policy
            try:
                self.ledger.policy = policy
                self.assertTrue(any("unit cumulative bytes" in x for x in self.ledger._violations(totals, extra_bytes=1)))
            finally:
                self.ledger.policy = original
            observed.assert_called()
        self.assertEqual(600, totals["unit_generated_bytes"])
        self.assertEqual(512, totals["pending_unit_bytes"])

    def test_checkpoint_interruption_and_rollback_stay_blocked(self):
        original = self.ledger._checkpoint_runs
        def interrupted():
            original()
            raise OSError("after durable quarantine checkpoint before SQL commit")
        with patch.object(self.ledger, "_checkpoint_runs", side_effect=interrupted):
            with self.assertRaises(OSError):
                self.apply()
        self.assertFalse(self.ledger.generation_readiness()["ready"])
        self.assertEqual(0, self.ledger.connection.execute("SELECT COUNT(*) FROM producer_quarantines").fetchone()[0])
        with self.open() as reopened:
            self.assertFalse(reopened.generation_readiness()["ready"])
            self.assertFalse(reopened.snapshot()["accounting_complete"])
            self.assertEqual(512, reopened.snapshot()["totals"]["pending_generated_bytes"])

    def test_database_loss_recovers_gap_descriptor_hold_and_floor_without_readiness(self):
        self.apply()
        self.ledger.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        self.ledger = self.open()
        readiness = self.ledger.generation_readiness()
        self.assertFalse(readiness["ready"])
        self.assertFalse(readiness["history_complete"])
        self.assertEqual(1, self.ledger.connection.execute("SELECT COUNT(*) FROM producer_quarantines").fetchone()[0])
        self.assertEqual(1, self.ledger.connection.execute("SELECT COUNT(*) FROM uncertain_generation").fetchone()[0])
        self.assertEqual(600, self.ledger.snapshot()["totals"]["project_generated_bytes"])
        self.assertEqual(512, self.ledger.snapshot()["totals"]["pending_generated_bytes"])

    def test_cold_catalog_merge_preserves_full_record_and_never_creates_native_history(self):
        descriptor = self.apply()
        cold_path = self.root / "cold" / "accounting.sqlite"
        with Accounting(cold_path, self.policy["project_id"], self.policy) as cold:
            cold.reconcile_quarantines({descriptor["reservation_id"]: descriptor})
            cold.reconcile_quarantines([descriptor])
            self.assertFalse(cold.generation_readiness()["ready"])
            self.assertFalse(cold.snapshot()["accounting_complete"])
            self.assertEqual(0, cold.connection.execute("SELECT COUNT(*) FROM producer_sessions").fetchone()[0])
            self.assertEqual(descriptor["reservation"], dict(cold.connection.execute("SELECT * FROM reservations").fetchone()))
            self.assertEqual(descriptor["run"], dict(cold.connection.execute("SELECT * FROM runs").fetchone()))

    def test_portable_validator_reads_no_paths_or_processes(self):
        descriptor = self.apply()
        with patch("evidence.quarantine.hash_file", side_effect=AssertionError("portable validator read a path")), patch("evidence.process_identity.state", side_effect=AssertionError("portable validator read processes")):
            self.assertEqual(descriptor, validate_quarantine_descriptor(descriptor, self.policy))

    def test_missing_history_flag_never_hides_uncertain_rows(self):
        self.ledger.connection.execute("DELETE FROM identity WHERE key='recovery_required'")
        snapshot = self.ledger.snapshot()
        self.assertFalse(snapshot["accounting_complete"])
        self.assertTrue(snapshot["totals_are_lower_bounds"])
        self.assertFalse(self.ledger.generation_readiness()["ready"])

    def test_missing_checkpoint_cannot_hide_behind_unknown_reason(self):
        self.apply()
        self.ledger._recovery_path("old-run").unlink()
        self.assertFalse(self.ledger.generation_readiness()["ready"])
        with self.assertRaises(EvidenceError):
            self.ledger.reserve("new", "unit", 1, 1)

    def test_changed_old_run_status_and_output_reuse_are_rejected(self):
        self.apply()
        self.ledger.connection.execute("UPDATE runs SET status='active' WHERE id='old-run'")
        for migration in (False, True):
            with self.assertRaisesRegex(EvidenceError, "quarantined run"):
                self.ledger.reserve("old-run", "unit", 0, 0, migration=migration)
        new = self.root / "different-output"
        new.mkdir()
        with self.assertRaisesRegex(EvidenceError, "quarantined run"):
            self.ledger.register_output("old-run", "unit", new)
        with self.assertRaises(EvidenceError):
            self.ledger.acknowledge_output(self.f["output_id"])
        with self.assertRaises(EvidenceError):
            self.ledger.reconcile_output(self.f["output_id"])
        with self.assertRaises(EvidenceError):
            self.ledger.record_uncertain(self.f["reservation"], 800, 3)
        self.assertEqual(600, self.ledger.connection.execute("SELECT gross_bytes FROM runs WHERE id='old-run'").fetchone()[0])
        self.assertFalse(self.ledger.generation_readiness()["ready"])

    def test_registered_resource_must_already_be_disposed(self):
        record = deepcopy(self.f["record"])
        resource = self.f["output"] / "temporary"
        resource.mkdir()
        record["resources"] = [{"path": str(resource), "identity": producer_runtime.directory_identity(resource)}]
        raw = json.dumps(record)
        self.ledger.connection.execute("UPDATE producer_sessions SET record=?", (raw,))
        proof = deepcopy(self.f["proof"])
        proof["original_record_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        with self.assertRaisesRegex(EvidenceError, "resource disposition"):
            self.ledger.quarantine_producer(self.f["attempt"], proof, dry_run=False)

    def monitored_attempt(self, source, *, byte_count=10000, file_count=10):
        """Use real gated helpers in this test process so failure points are injectable."""
        self.apply()
        output = self.root / "monitored-output"
        output.mkdir()
        attempt = str(uuid.uuid4())
        reservation = self.ledger.reserve("monitored", "unit", byte_count, file_count,
                                          local_bytes=byte_count, metadata_bytes=3 * 1024 * 1024)
        output_id = self.ledger.register_output("monitored", "unit", output)
        owner = process_identity.identity()
        record = {"version": 1, "attempt_id": attempt, "run_id": "monitored", "unit_id": "unit",
                  "reservation_id": reservation, "output_id": output_id, "intent_id": None,
                  "coordinator": owner, "guardian": owner, "status": "running", "processes": {}, "resources": [],
                  "output_dir": str(output), "output_identity": producer_runtime.directory_identity(output), "policy": self.policy}
        self.ledger.connection.execute("INSERT INTO producer_sessions VALUES(?,?)", (attempt, json.dumps(record)))
        return attempt, reservation, output, lambda: _run_monitored(
            self.ledger, "monitored", "unit", output, [sys.executable, "-B", "-c", source],
            byte_count, file_count, timeout=5, poll_interval=.02, attempt=attempt)

    def test_final_proof_survives_cleanup_failure_and_precedes_uncertain_settlement(self):
        attempt, reservation, output, run = self.monitored_attempt("from pathlib import Path; Path('final.txt').write_bytes(b'original')")
        with patch.object(producer_runtime, "cleanup_directories", side_effect=OSError("synthetic cleanup EPERM")):
            result = run()
        self.assertEqual("incomplete", result["status"])
        self.assertIn("EPERM", result["cleanup_problem"])
        self.assertTrue(result["final_observation_complete"], result)
        proof = producer_runtime.read(self.ledger, attempt)["final_observation"]
        self.assertTrue(proof["complete"])
        self.assertIn("final.txt", proof["observations"])
        self.assertEqual(hashlib.sha256(b"original").hexdigest(), proof["observations"]["final.txt"]["content_hash"])
        self.assertEqual("pending", self.ledger.connection.execute("SELECT state FROM reservations WHERE id=?", (reservation,)).fetchone()[0])
        self.assertEqual([], producer_runtime.verify_stopped(self.ledger, attempt))

    def test_final_hash_failure_is_explicit_even_after_aggregate_overrun(self):
        attempt, reservation, output, run = self.monitored_attempt(
            "from pathlib import Path; import time; Path('large.txt').write_bytes(b'x'*2048); time.sleep(10)", byte_count=512)
        from evidence.producer import hash_file as actual_hash
        def fail_final(path):
            if Path(path).name == "large.txt":
                raise EvidenceError("synthetic final hash failure")
            return actual_hash(path)
        with patch("evidence.producer.hash_file", side_effect=fail_final):
            result = run()
        self.assertIn("aggregate", result["problem"])
        self.assertFalse(result["final_observation_complete"])
        self.assertIn("synthetic final hash failure", result["final_observation_problem"])
        proof = producer_runtime.read(self.ledger, attempt)["final_observation"]
        self.assertFalse(proof["complete"])
        self.assertIn("final hash failure", proof["problem"])
        self.assertEqual("pending", self.ledger.connection.execute("SELECT state FROM reservations WHERE id=?", (reservation,)).fetchone()[0])

    def test_terminal_proof_is_retained_before_accounting_error(self):
        attempt, reservation, output, run = self.monitored_attempt("from pathlib import Path; Path('final.txt').write_bytes(b'original')")
        with patch.object(producer_runtime, "cleanup_directories", side_effect=OSError("cleanup EPERM")), patch.object(self.ledger, "record_uncertain", side_effect=EvidenceError("settlement failed")):
            with self.assertRaisesRegex(EvidenceError, "settlement failed"):
                run()
        proof = producer_runtime.read(self.ledger, attempt)["final_observation"]
        self.assertTrue(proof["complete"])
        self.assertIn("final.txt", proof["observations"])
        self.assertEqual("pending", self.ledger.connection.execute("SELECT state FROM reservations WHERE id=?", (reservation,)).fetchone()[0])

    def test_oversized_final_proof_fails_explicitly_without_releasing_hold(self):
        attempt, reservation, output, run = self.monitored_attempt(
            "from pathlib import Path; [Path(str(i)).write_bytes(b'x') for i in range(100)]", byte_count=10000, file_count=200)
        with patch.object(producer_runtime, "MAX_RECORD", 5000):
            result = run()
        self.assertEqual("incomplete", result["status"])
        self.assertFalse(result["final_observation_complete"])
        self.assertIn("could not be durably recorded", result["final_observation_problem"])
        proof = producer_runtime.read(self.ledger, attempt)["final_observation"]
        self.assertFalse(proof["complete"])
        self.assertNotIn("observations", proof)
        self.assertEqual(101, len(list(output.iterdir())))
        self.assertEqual("pending", self.ledger.connection.execute("SELECT state FROM reservations WHERE id=?", (reservation,)).fetchone()[0])

    def test_replaced_output_root_cannot_claim_complete_final_observation(self):
        attempt, reservation, output, run = self.monitored_attempt(
            "from pathlib import Path; Path('preserved.txt').write_bytes(b'original')")
        original_identity = producer_runtime.directory_identity(output)
        preserved = output.with_name('preserved-original-output')
        actual_cleanup = producer_runtime.cleanup_directories
        replacements = []
        def replace_after_exit(ledger, current_attempt):
            self.assertEqual([], producer_runtime.verify_stopped(ledger, current_attempt))
            problems = actual_cleanup(ledger, current_attempt)
            self.assertEqual([], problems)
            output.rename(preserved)
            output.mkdir()
            replacements.append(producer_runtime.directory_identity(output))
            return problems
        with patch.object(producer_runtime, 'cleanup_directories', side_effect=replace_after_exit):
            result = run()
        self.assertEqual(1, len(replacements), 'the replacement prerequisite did not execute')
        self.assertNotEqual(original_identity, replacements[0])
        self.assertEqual(original_identity, producer_runtime.directory_identity(preserved))
        self.assertEqual(b'original', (preserved / 'preserved.txt').read_bytes())
        self.assertFalse(result["final_observation_complete"], result)
        self.assertIn("identity changed", result["final_observation_problem"])
        proof = producer_runtime.read(self.ledger, attempt)["final_observation"]
        self.assertFalse(proof["complete"])
        self.assertEqual("pending", self.ledger.connection.execute("SELECT state FROM reservations WHERE id=?", (reservation,)).fetchone()[0])

    def test_missing_journal_reason_survives_uncertain_recovery_and_reopen(self):
        self.ledger.close()
        for path in self.ledger.recovery_dir.iterdir():
            path.unlink()
        self.ledger = self.open()
        reason = self.ledger._current_recovery_reason()
        self.assertIn("journal was lost", reason)
        self.ledger.record_uncertain(self.f["reservation"], 600, 2)
        self.assertEqual(reason, self.ledger.connection.execute("SELECT value FROM identity WHERE key='recovery_required'").fetchone()[0])
        self.ledger.close()
        self.ledger = self.open()
        self.assertEqual(reason, self.ledger._current_recovery_reason())
        with self.assertRaisesRegex(EvidenceError, "intact original accounting"):
            self.apply()
        self.assertFalse(self.ledger.generation_readiness()["ready"])

    def test_unchanged_quarantine_reads_append_no_sql_changes_or_wal_bytes(self):
        self.apply()
        before_changes = self.ledger.connection.total_changes
        wal = Path(str(self.path) + "-wal")
        before_wal = wal.stat().st_size
        for _ in range(10):
            self.assertFalse(self.ledger.snapshot()["accounting_complete"])
            self.assertTrue(self.ledger.generation_readiness()["ready"])
        self.assertEqual(before_changes, self.ledger.connection.total_changes)
        self.assertEqual(before_wal, wal.stat().st_size)

    def test_new_durable_structural_cause_wins_over_cached_unknown(self):
        self.apply()
        # Prime the legacy cached reason on an already-open coordinator.
        self.ledger.snapshot()
        from evidence.quarantine import UNKNOWN_REASON
        self.assertEqual(UNKNOWN_REASON, self.ledger._recovery_problem)
        structural = "accounting recovery journal was lost; complete generation history cannot be verified"
        with self.open() as other:
            with other._transaction():
                other._record_recovery_reason(structural)
        self.assertEqual(structural, self.ledger._current_recovery_reason())
        for _ in range(3):
            self.ledger.snapshot()
            self.assertFalse(self.ledger.generation_readiness()["ready"])
        self.assertEqual(structural, self.ledger.connection.execute("SELECT value FROM identity WHERE key='recovery_required'").fetchone()[0])
        with self.open() as reopened:
            self.assertEqual(structural, reopened._current_recovery_reason())
            self.assertFalse(reopened.generation_readiness()["ready"])


if __name__ == "__main__":
    unittest.main()
