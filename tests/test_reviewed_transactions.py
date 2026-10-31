"""Synthetic reviewed-contract transactions; no product projects or providers."""
import copy
import json
import subprocess
import sys
import unittest
from unittest import mock

import test_unit_history as fixture
from test_reviewed_acceptance import ReviewedFixture
import test_reviewed_gates as gate_fixture
from test_sdd_check import SCRIPT
import reviewed_acceptance


class ReviewedTransactionTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture.UnitHistoryTests("test_version_one_retains_original_acceptance_and_plan_binding_rules")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.p, self.m = self.base.p, self.base.m
        self.m.update(checker_contract_version=3, unit_contract_version=3)
        self.h = self.base.history()
        self.p.save()
        self.active = self.p.root / "forge/sdd-manifest.json"
        self.before = self.active.read_bytes()
        self.expected = self.h.sha(self.before)

    def candidate(self):
        candidate = copy.deepcopy(self.m)
        candidate.update(checker_contract_version=4, unit_contract_version=4)
        return candidate

    def stage(self, candidate=None):
        return self.h.stage_candidate(self.p.root, candidate or self.candidate(), self.expected)

    def journals(self):
        return sorted((self.p.root / self.h.HISTORY / "activations").glob("*/record.json"))

    def test_staging_retry_is_bounded_and_retains_every_original_field(self):
        candidate = self.candidate()
        original = copy.deepcopy(candidate)
        first, second = self.stage(candidate), self.stage(candidate)
        self.assertEqual(first, second)
        self.assertEqual(1, len(list((self.p.root / self.h.HISTORY / "candidates").glob("*/record.json"))))
        self.assertEqual(self.before, self.active.read_bytes())
        self.assertEqual(original, candidate)
        result = self.h.activate_candidate(self.p.root, first, self.expected)
        self.assertEqual("activated", result["status"])
        actual = json.loads(self.active.read_text())
        for key in set(actual) | set(self.m):
            if key not in ("checker_contract_version", "unit_contract_version"):
                self.assertEqual(self.m.get(key), actual.get(key), key)

    def test_activation_retry_reports_only_transaction_outcome_even_after_source_change(self):
        staged = self.stage()
        first = self.h.activate_candidate(self.p.root, staged, self.expected)
        journal_bytes = self.journals()[0].read_bytes()
        self.p.write("src/alpha.txt", "Changed after the historical activation.\n")
        result = self.h.activate_candidate(self.p.root, staged, self.expected)
        self.assertEqual("already_activated", result["status"])
        self.assertEqual("not_revalidated", result["acceptance"])
        self.assertNotIn("report", result)
        self.assertEqual(first["journal_ref"], result["journal_ref"])
        self.assertEqual([journal_bytes], [path.read_bytes() for path in self.journals()])

    def test_interrupted_activation_retry_reuses_immutable_journal(self):
        staged = self.stage()
        with mock.patch.object(self.h.os, "replace", side_effect=OSError("synthetic interruption")):
            with self.assertRaisesRegex(OSError, "synthetic interruption"):
                self.h.activate_candidate(self.p.root, staged, self.expected)
        self.assertEqual(self.before, self.active.read_bytes())
        self.assertFalse(list(self.active.parent.glob(".sdd-manifest-*.tmp")))
        journal_bytes = self.journals()[0].read_bytes()
        journal = {"path": self.journals()[0].relative_to(self.p.root).as_posix(),
                   "content_hash": self.h.sha(journal_bytes)}
        self.assertEqual("not_activated", self.h.recover_activation(self.p.root, journal)["status"])
        result = self.h.activate_candidate(self.p.root, staged, self.expected)
        self.assertEqual("activated", result["status"])
        self.assertEqual(journal, result["journal_ref"])
        self.assertEqual([journal_bytes], [path.read_bytes() for path in self.journals()])

    def test_interrupted_staging_write_never_publishes_a_partial_candidate(self):
        original_write = self.h.write_new
        interrupted = []
        def partial(project, path, data):
            if "/candidates/" in path and "record.json.pending-" in path:
                original_write(project, path, data[:13])
                interrupted.append(path.split(".pending-", 1)[0])
                raise OSError("synthetic interruption during candidate write")
            return original_write(project, path, data)
        with mock.patch.object(self.h, "write_new", side_effect=partial):
            with self.assertRaisesRegex(OSError, "during candidate write"):
                self.stage()
        self.assertEqual(1, len(interrupted))
        self.assertFalse((self.p.root / interrupted[0]).exists())
        self.assertFalse(list((self.p.root / self.h.HISTORY).rglob("*.pending-*")))
        self.assertEqual(self.before, self.active.read_bytes())
        staged = self.stage()
        self.assertEqual(interrupted[0], staged["path"])
        self.assertEqual("activated", self.h.activate_candidate(self.p.root, staged, self.expected)["status"])

    def test_interrupted_member_writes_are_retryable_without_partial_publication(self):
        for member in ("before", "after", "record"):
            with self.subTest(member=member):
                case = ReviewedTransactionTests("runTest")
                case.setUp()
                self.addCleanup(case.doCleanups)
                staged = case.stage()
                original_write = case.h.write_new
                interrupted = []
                def partial(project, path, data):
                    if "/activations/" in path and member + ".json.pending-" in path:
                        original_write(project, path, data[:11])
                        interrupted.append(path.split(".pending-", 1)[0])
                        raise OSError("synthetic interruption during member write")
                    return original_write(project, path, data)
                with mock.patch.object(case.h, "write_new", side_effect=partial):
                    with self.assertRaisesRegex(OSError, "during member write"):
                        case.h.activate_candidate(case.p.root, staged, case.expected)
                self.assertEqual(1, len(interrupted))
                self.assertFalse((case.p.root / interrupted[0]).exists())
                self.assertFalse(list((case.p.root / case.h.HISTORY).rglob("*.pending-*")))
                self.assertEqual(case.before, case.active.read_bytes())
                result = case.h.activate_candidate(case.p.root, staged, case.expected)
                self.assertEqual("activated", result["status"])
                self.assertEqual(1, len(case.journals()))
                self.assertEqual("already_activated", case.h.activate_candidate(case.p.root, staged, case.expected)["status"])

    def test_immutable_publication_never_overwrites_a_conflicting_winner(self):
        path = "forge/unit-history/candidates/synthetic-conflict/record.json"
        original = self.h.encoded({"synthetic": "first complete writer"})
        first = self.h.publish_immutable(self.p.root, path, original)
        self.assertEqual(first, self.h.publish_immutable(self.p.root, path, original))
        with self.assertRaisesRegex(ValueError, "immutable publication differs"):
            self.h.publish_immutable(self.p.root, path, self.h.encoded({"synthetic": "conflicting writer"}))
        self.assertEqual(original, (self.p.root / path).read_bytes())

    def test_competing_writer_cannot_replace_newer_manifest(self):
        first = self.stage()
        candidate = self.candidate()
        candidate["reviewed_acceptance"] = {}
        second = self.stage(candidate)
        self.assertNotEqual(first, second)
        self.h.activate_candidate(self.p.root, first, self.expected)
        current = self.active.read_bytes()
        with self.assertRaisesRegex(ValueError, "active manifest changed"):
            self.h.activate_candidate(self.p.root, second, self.expected)
        self.assertEqual(current, self.active.read_bytes())
        self.assertEqual(1, len(self.journals()))

    def test_existing_lock_is_preserved_and_no_journal_is_created(self):
        staged = self.stage()
        lock = self.p.root / self.h.HISTORY / "activation.lock"
        lock.write_text('{"token":"synthetic-other-writer"}\n')
        before = lock.read_bytes()
        with self.assertRaises(FileExistsError):
            self.h.activate_candidate(self.p.root, staged, self.expected)
        self.assertEqual(before, lock.read_bytes())
        self.assertEqual(self.before, self.active.read_bytes())
        self.assertEqual([], self.journals())

    def test_source_drift_before_activation_is_rejected_without_publication(self):
        staged = self.stage()
        self.p.write("src/alpha.txt", "Changed after staging.\n")
        with self.assertRaisesRegex(ValueError, "changed|candidate plan validation failed"):
            self.h.activate_candidate(self.p.root, staged, self.expected)
        self.assertEqual(self.before, self.active.read_bytes())
        self.assertEqual([], self.journals())

    def test_review_history_cannot_be_removed_or_reordered(self):
        previous = self.candidate()
        references = [{"path": "forge/unit-history/reviewed-acceptance/" + str(index) + "/record.json",
                       "content_hash": str(index) * 64} for index in (1, 2)]
        previous["reviewed_acceptance"] = {"U-1": references}
        for retained in ([], references[:1], list(reversed(references))):
            with self.subTest(retained=retained):
                candidate = copy.deepcopy(previous)
                candidate["reviewed_acceptance"] = {"U-1": retained}
                with self.assertRaisesRegex(ValueError, "history was dropped or reordered"):
                    self.h.validate_transition(self.p.root, previous, candidate, {})
        self.assertEqual(self.before, self.active.read_bytes())

    def test_version_adoption_cannot_alter_authority_accounting_or_execution(self):
        for field, value in (("implementation_gate", {}), ("evidence_accounting", {"runs": {}}),
                             ("unit_runs", {"U-1": {"status": "completed"}}), ("verification", {}),
                             ("execution_contexts", {"U-1": {}}), ("state", {"phase": "implementation"})):
            with self.subTest(field=field):
                candidate = self.candidate()
                candidate[field] = value
                with self.assertRaisesRegex(ValueError, "preserve original state, authority and accounting"):
                    self.h.validate_transition(self.p.root, self.m, candidate, {})
        self.assertEqual(self.before, self.active.read_bytes())

    def legacy_review(self):
        """Use the public legacy migration before any reviewed acceptance exists."""
        f = ReviewedFixture(self, legacy=True)
        f.m.clear()
        f.m.update(copy.deepcopy(f.original))
        f.m["unit_runs"]["U-1"].update(status="completed", completed_at=f.h.utcnow())
        original = copy.deepcopy(f.m)
        f.p.save()
        active = f.p.root / "forge/sdd-manifest.json"
        expected = f.h.sha(active.read_bytes())
        migrated = f.h.adopt_legacy(f.p.root, expected)
        f.h.activate_candidate(f.p.root, migrated, expected)
        f.m.clear()
        f.m.update(json.loads(active.read_text()))
        legacy_ref = f.m["legacy_history"][-1]
        legacy_bytes = (f.p.root / legacy_ref["path"]).read_bytes()
        self.assertEqual(original, f.h.read_ref(f.p.root, f.h.read_ref(f.p.root, legacy_ref)["manifest_ref"]))
        # Integrity-policy selection and contract opt-in are explicit separate
        # transitions; neither invents a review or changes archived run facts.
        for changes in ({"checker_contract_version": 4, "unit_contract_version": 4},
                        {"history_integrity": {"legacy_payloads": "audit_only"}}):
            candidate = copy.deepcopy(f.m)
            candidate.update(changes)
            expected = f.h.sha(active.read_bytes())
            staged = f.h.stage_candidate(f.p.root, candidate, expected)
            f.h.activate_candidate(f.p.root, staged, expected)
            f.m.clear()
            f.m.update(json.loads(active.read_text()))
        original_current = copy.deepcopy(f.m)
        f.request["source_ref"] = legacy_ref
        f.request["current_inventory"] = f.b.inventory(f.environment)
        f.request["review"]["reviewed_at"] = f.h.utcnow()
        f.capture()
        expected = f.h.sha(active.read_bytes())
        staged = f.h.stage_candidate(f.p.root, f.m, expected)
        return f, original, original_current, legacy_ref, legacy_bytes, staged, expected

    def test_actual_legacy_completed_source_is_reviewed_transactionally_without_rewriting_runs(self):
        f, original, prior, legacy_ref, legacy_bytes, staged, expected = self.legacy_review()
        active = f.p.root / "forge/sdd-manifest.json"
        before = active.read_bytes()
        result = f.h.activate_candidate(f.p.root, staged, expected)
        self.assertEqual("activated", result["status"])
        self.assertNotEqual(before, active.read_bytes())
        current = json.loads(active.read_text())
        self.assertEqual(prior["unit_runs"], current["unit_runs"])
        self.assertEqual(prior["verification"], current["verification"])
        self.assertEqual(prior["implementation_gate"], current["implementation_gate"])
        self.assertEqual(prior.get("evidence_accounting"), current.get("evidence_accounting"))
        self.assertEqual(prior.get("execution_contexts"), current.get("execution_contexts"))
        self.assertEqual(legacy_bytes, (f.p.root / legacy_ref["path"]).read_bytes())
        archived = f.h.read_ref(f.p.root, f.h.read_ref(f.p.root, legacy_ref)["manifest_ref"])
        self.assertEqual(original["unit_runs"], archived["unit_runs"])
        self.assertEqual(original["verification"], archived["verification"])
        checker = f.h.api().Checker(f.p.root, current)
        report = checker.run("implementation", unit_action="complete", unit_id="U-1")
        self.assertEqual("passed", report["result"], report)
        self.assertIn("U-1", report["implementation_progress"]["accepted_unit_ids"])
        self.assertEqual("audit_only", report["history_integrity"]["legacy_payloads"])
        # A later ordinary start sees the same accepted prerequisite state.
        f.m.clear()
        f.m.update(current)
        context = f.h.capture_context(f.p.root, f.m, "U-2", f.b.inventory(unit="U-2"))
        f.m.setdefault("execution_contexts", {})["U-2"] = context
        report = f.h.api().Checker(f.p.root, f.m).run("implementation", unit_action="start", unit_id="U-2")
        self.assertEqual("passed", report["result"], report)
        self.assertIn("U-1", report["implementation_progress"]["accepted_unit_ids"])

    def test_accepted_legacy_payload_drift_cannot_hide_behind_audit_only_policy(self):
        f, _, _, legacy_ref, _, staged, expected = self.legacy_review()
        active = f.p.root / "forge/sdd-manifest.json"
        before = active.read_bytes()
        archive = f.h.read_ref(f.p.root, legacy_ref)
        path = archive["files"]["forge/evidence/QA-02.json"]["path"]
        (f.p.root / path).write_text('{"corrupt_synthetic_observation":true}\n')
        with self.assertRaises(ValueError):
            f.h.activate_candidate(f.p.root, staged, expected)
        self.assertEqual(before, active.read_bytes())
        report = f.h.api().Checker(f.p.root, f.m).run("implementation", unit_action="complete", unit_id="U-1")
        self.assertNotEqual("passed", report["result"], report)
        self.assertNotIn("U-1", report["implementation_progress"].get("accepted_unit_ids") or [])

    def test_public_import_inventory_and_review_commands_write_only_immutable_records(self):
        f = ReviewedFixture(self, second=False)
        f.p.save()
        active = f.p.root / "forge/sdd-manifest.json"
        original = active.read_bytes()
        f.p.write("forge/source.json", json.dumps(f.original))
        f.p.write("forge/source-ref.json", json.dumps(f.source_ref))
        f.p.write("forge/original-inventory-request.json", json.dumps(f.inputs))
        def command(*arguments):
            process = subprocess.run([sys.executable, str(SCRIPT.with_name("sdd_history.py")),
                                      "--project", str(f.p.root), *arguments], text=True, capture_output=True)
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            return json.loads(process.stdout)
        imported = command("import-observations", "--unit", "U-1", "--source-manifest", "forge/source.json")
        self.assertEqual(f.source_ref, imported)
        inventory = command("prepare-original-inventory", "--unit", "U-1", "--source-kind", "external_observations",
                            "--source-ref", "forge/source-ref.json", "--inventory", "forge/original-inventory-request.json")
        request = copy.deepcopy(f.request)
        request["original_inventory_ref"] = inventory
        f.p.write("forge/review-request.json", json.dumps(request))
        first = command("capture-review", "--request", "forge/review-request.json")
        self.assertEqual(first, command("capture-review", "--request", "forge/review-request.json"))
        self.assertEqual(original, active.read_bytes())
        self.assertEqual("reviewed_unit_acceptance", f.h.read_ref(f.p.root, first)["event"])

    def test_partial_contextless_resume_uses_explicit_new_context_and_standard_publication(self):
        fixture = gate_fixture.ReviewedGateTests("test_version_four_preserves_per_check_inputs_without_granting_acceptance")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.reviewed(("U-1", "U-2", "U-3"), interrupted=True, fresh=("QA-04",))
        p, manifest = fixture.p, fixture.m
        h = reviewed_acceptance.history()
        p.save()
        active = p.root / "forge/sdd-manifest.json"
        before = active.read_bytes()
        original = copy.deepcopy(manifest)
        prior_ref = manifest["reviewed_acceptance"]["U-3"][-1]
        original_review = h.read_ref(p.root, prior_ref)
        source = h.read_ref(p.root, original_review["source_ref"])
        original_source = h.read_ref(p.root, source["manifest_ref"])
        candidate = copy.deepcopy(manifest)
        candidate["unit_runs"]["U-3"] = {"status": "pending", "findings": copy.deepcopy(manifest["unit_runs"]["U-3"].get("findings", []))}
        check = next(row for row in candidate["verification"]["checks"] if row["check_id"] == "QA-04")
        for field in h.EXECUTION_KEYS - {"findings"}:
            check.pop(field, None)
        check["execution_status"] = "not_run"
        p.write("forge/resume-candidate.json", json.dumps(candidate))
        p.write("forge/reviewed-prior-ref.json", json.dumps(prior_ref))
        p.write("forge/resume-inventory.json", json.dumps(fixture.inventory("U-3")))
        process = subprocess.run([sys.executable, str(SCRIPT.with_name("sdd_history.py")), "--project", str(p.root),
                                  "--manifest", "forge/resume-candidate.json", "capture-context", "--unit", "U-3",
                                  "--inventory", "forge/resume-inventory.json", "--reviewed-prior-ref", "forge/reviewed-prior-ref.json"],
                                 text=True, capture_output=True)
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        context = json.loads(process.stdout)
        self.assertEqual(prior_ref, h.read_ref(p.root, context)["reviewed_prior_ref"])
        candidate.setdefault("execution_contexts", {})["U-3"] = context
        changed_source = copy.deepcopy(original)
        changed_check = next(row for row in changed_source["verification"]["checks"] if row["check_id"] == "QA-04")
        changed_check["execution_status"] = "failed"
        with self.assertRaisesRegex(ValueError, "exact original contextless run and observations"):
            h.validate_transition(p.root, changed_source, candidate, {})
        existing_context = copy.deepcopy(original)
        existing_context.setdefault("execution_contexts", {})["U-3"] = {
            "path": "forge/unit-history/contexts/missing/record.json", "content_hash": "0" * 64}
        with self.assertRaisesRegex(ValueError, "exact immutable attempt"):
            h.validate_transition(p.root, existing_context, candidate, {})
        unbound = copy.deepcopy(candidate)
        unbound.get("execution_contexts", {}).pop("U-3", None)
        unbound_ref = h.capture_context(p.root, unbound, "U-3", fixture.inventory("U-3"))
        unbound.setdefault("execution_contexts", {})["U-3"] = unbound_ref
        with self.assertRaisesRegex(ValueError, "explicitly bind"):
            h.validate_transition(p.root, original, unbound, {})
        expected = h.sha(before)
        staged = h.stage_candidate(p.root, candidate, expected)
        self.assertEqual(before, active.read_bytes())
        h.activate_candidate(p.root, staged, expected)
        self.assertEqual(original_source, h.read_ref(p.root, source["manifest_ref"]))
        self.assertEqual(original["unit_runs"], original_source["unit_runs"])
        current = json.loads(active.read_text())
        self.assertEqual(original["reviewed_acceptance"], current["reviewed_acceptance"])
        self.assertEqual(original.get("evidence_accounting"), current.get("evidence_accounting"))
        self.assertEqual("pending", current["unit_runs"]["U-3"]["status"])
        self.assertNotIn("attempt_ref", current["unit_runs"]["U-3"])
        report = h.api().Checker(p.root, current).run("implementation", unit_action="start", unit_id="U-3")
        self.assertEqual("passed", report["result"], report)
        report = h.api().Checker(p.root, current).run("implementation", unit_action="complete", unit_id="U-3")
        self.assertNotEqual("passed", report["result"], report)



if __name__ == "__main__":
    unittest.main()
