"""Read-only scope checks preserve unknown historical producer accounting."""
from copy import deepcopy
import unittest

import test_evidence_checker as checker_fixtures
from evidence.quarantine import digest


class ScopedAccountingCheckerTests(unittest.TestCase):
    setUp = checker_fixtures.EvidenceCheckerTests.setUp
    prepare = checker_fixtures.EvidenceCheckerTests.prepare
    receipt = checker_fixtures.EvidenceCheckerTests.receipt
    checker = checker_fixtures.EvidenceCheckerTests.checker

    def scoped(self):
        self.m["evidence_storage"] = {"policy_path": "forge/evidence-policy.json"}
        ref = self.prepare({"fresh": True})
        reservation = dict(id="old-reservation", run_id="failed-run", bytes=100,
                           files=10, local_bytes=100, metadata_bytes=0,
                           metadata_files=0, retained_bytes=0, retained_objects=0,
                           state="pending", created=1.0)
        record_hash = "a" * 64
        proof = dict(version=1, kind="producer-disposition", attempt_id="old-attempt",
                     original_record_sha256=record_hash, verifier="synthetic-test-host",
                     observed_at="2026-10-21T10:00:00Z", external_disposition={
                         "coverage": "all-unregistered-helpers-and-resources",
                         "journal": {"path": str(self.root / "synthetic-journal.json"), "sha256": "b" * 64},
                         "proof": {"path": str(self.root / "synthetic-proof.json"), "sha256": "c" * 64},
                         "limitations": "Synthetic declared proof, never live ownership or product acceptance"})
        run = dict(id="failed-run", unit_id="U-1", ordinal=0, gross_bytes=110,
                   gross_files=2, migration=0, status="incomplete", created=1.0)
        gap = dict(version=1, kind="quarantined-producer-gap",
                   project_id=self.policy["project_id"], store_id=self.policy["store_id"],
                   ledger_id="original-ledger", policy_sha256=digest(self.policy),
                   attempt_id="old-attempt", run_id="failed-run", unit_id="U-1",
                   ordinal=0, reservation_id="old-reservation", output_id="old-output",
                   intent_id="old-intent", original_record_sha256=record_hash,
                   uncertain={"reservation_id": "old-reservation", "gross_bytes": 110,
                              "logical_files": 2}, reservation=reservation,
                   disposition="quarantined-unresolved", history_complete=False,
                   proof=proof, inventory=[], inventory_sha256=digest([]),
                   output_identity=[1, 2], quarantined_at="2026-10-21T10:00:01Z")
        # The immutable descriptor includes the original run in addition to its
        # unknown output floor, so cold recovery retains cumulative charges.
        gap["run"] = run
        gap["digest"] = digest(gap)
        receipt = self.m["evidence_accounting"]
        receipt.update(version=2, kind="scoped-known-generation",
                       accounting_complete=False, incomplete=True,
                       totals_are_lower_bounds=True, history_complete=False,
                       generation_ready=True, quarantines=[gap],
                       pending_generation_intents={"old-intent": {
                           "run_id": "failed-run", "unit_id": "U-1",
                           "reserve_bytes": 100, "reserve_files": 10}},
                       selected_scope={"run_ids": [ref["provenance"]["run_id"]], "complete": True})
        receipt["runs"]["failed-run"] = dict(unit_id="U-1", status="incomplete",
                                             gross_generated_bytes=110,
                                             original_logical_files=2,
                                             pending_reservations=1,
                                             unreconciled_outputs=1)
        return ref, receipt

    def test_fresh_scope_is_readable_without_claiming_global_completeness(self):
        ref, receipt = self.scoped()
        before = deepcopy(receipt)
        self.assertTrue(self.checker().evidence_snapshot(ref, "qa-checklist"))
        self.assertEqual(before, receipt)
        self.assertFalse(receipt["accounting_complete"])

    def test_failed_run_cannot_be_in_scope_or_required_dependency(self):
        ref, receipt = self.scoped()
        receipt["selected_scope"]["run_ids"].append("failed-run")
        self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))
        receipt["selected_scope"]["run_ids"].remove("failed-run")
        with self.assertRaisesRegex(ValueError, "outside.*scope"):
            self.checker().evidence_accounting(run_id="failed-run", unit_id="U-1")

    def test_undisclosed_or_active_pending_intent_blocks(self):
        ref, receipt = self.scoped()
        receipt["pending_generation_intents"]["unresolved-other"] = {
            "run_id": "another-run", "unit_id": "U-2"}
        self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))

    def test_unconsumed_run_cannot_hide_outstanding_output_or_hold(self):
        ref, receipt = self.scoped()
        original = deepcopy(receipt)
        for status in ("complete", "incomplete"):
            for field in ("pending_reservations", "unreconciled_outputs"):
                with self.subTest(status=status, field=field):
                    self.m["evidence_accounting"] = deepcopy(original)
                    updated = self.m["evidence_accounting"]
                    row = deepcopy(updated["runs"][ref["provenance"]["run_id"]])
                    row.update(status=status)
                    row[field] = 1
                    updated["runs"]["unconsumed-run"] = row
                    if status == "complete":
                        updated["selected_scope"]["run_ids"].append("unconsumed-run")
                    self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))

    def test_historical_floor_hold_and_intent_must_stay_visible(self):
        ref, receipt = self.scoped()
        original = deepcopy(receipt)
        cases = [("pending_reservations", 0), ("gross_generated_bytes", 109),
                 ("original_logical_files", 1), ("status", "complete")]
        for field, value in cases:
            with self.subTest(field=field):
                self.m["evidence_accounting"] = deepcopy(original)
                self.m["evidence_accounting"]["runs"]["failed-run"][field] = value
                self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))
        self.m["evidence_accounting"] = deepcopy(original)
        self.m["evidence_accounting"]["pending_generation_intents"]["old-intent"]["reserve_bytes"] = 99
        self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))

    def test_false_complete_flags_and_nonboolean_flags_block(self):
        ref, receipt = self.scoped()
        original = deepcopy(receipt)
        for key, value in (("accounting_complete", True), ("incomplete", False),
                           ("totals_are_lower_bounds", False), ("history_complete", True),
                           ("generation_ready", 1)):
            with self.subTest(key=key):
                self.m["evidence_accounting"] = {**deepcopy(original), key: value}
                self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))

    def test_tampered_or_other_policy_quarantine_blocks(self):
        ref, receipt = self.scoped()
        gap = receipt["quarantines"][0]
        gap["reservation"]["bytes"] = 99
        self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))
        gap["digest"] = digest({k: v for k, v in gap.items() if k != "digest"})
        gap["policy_sha256"] = "f" * 64
        gap["digest"] = digest({k: v for k, v in gap.items() if k != "digest"})
        self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))

    def test_multiple_preserved_holds_cannot_understate_run_pending_count(self):
        ref, receipt = self.scoped()
        gap = deepcopy(receipt["quarantines"][0])
        gap.update(attempt_id="old-attempt-two", reservation_id="reservation-two",
                   output_id="output-two", intent_id="intent-two")
        gap["reservation"]["id"] = gap["reservation_id"]
        gap["uncertain"]["reservation_id"] = gap["reservation_id"]
        gap["proof"]["attempt_id"] = gap["attempt_id"]
        gap["digest"] = digest({k: v for k, v in gap.items() if k != "digest"})
        receipt["quarantines"].append(gap)
        receipt["pending_generation_intents"]["intent-two"] = deepcopy(
            receipt["pending_generation_intents"]["old-intent"])
        self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))
        receipt["runs"]["failed-run"]["pending_reservations"] = 2
        self.assertTrue(self.checker().evidence_snapshot(ref, "qa-checklist"))

    def test_missing_duplicate_or_unsettled_scope_blocks(self):
        ref, receipt = self.scoped()
        original = deepcopy(receipt)
        for run_ids in ([], ["nonexistent"], receipt["selected_scope"]["run_ids"] * 2):
            with self.subTest(run_ids=run_ids):
                self.m["evidence_accounting"] = deepcopy(original)
                self.m["evidence_accounting"]["selected_scope"]["run_ids"] = run_ids
                self.assertFalse(self.checker().evidence_snapshot(ref, "qa-checklist"))


if __name__ == "__main__":
    unittest.main()
