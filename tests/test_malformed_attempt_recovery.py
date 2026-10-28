"""Preserve malformed original attempts while qualifying a fresh synthetic retry."""
import copy
import unittest

import test_attempt_history as attempt_fixture


class MalformedAttemptRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = attempt_fixture.AttemptHistoryTests(
            "test_continuation_rejects_old_id_stale_probe_changed_scope_and_erased_history")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        run = self.fixture.start(False)
        run.pop("development_plan_hash")
        run.pop("approved_baseline_id")
        self.p, self.m, self.helper = self.fixture.p, self.fixture.m, self.fixture.helper
        self.p.save()
        self.original_bytes = (self.p.root / "forge/sdd-manifest.json").read_bytes()
        self.original = copy.deepcopy(self.m)
        self.context_bytes = (self.p.root / self.fixture.context["path"]).read_bytes()
        self.reference = self.helper.capture_attempt(
            self.p.root, self.m, "U-1", self.fixture.context, "synthetic-attempt-1",
            "interrupted", self.fixture.base.inventory())
        self.attempt_bytes = (self.p.root / self.reference["path"]).read_bytes()

    def continuation(self):
        return self.helper.capture_continuation(
            self.p.root, self.m, "U-1", self.reference, "synthetic-attempt-2",
            self.fixture.continuation_inventory())

    def test_fresh_candidate_activates_without_rewriting_malformed_original(self):
        attached = copy.deepcopy(self.m)
        attached["unit_runs"]["U-1"]["attempt_ref"] = self.reference
        with self.assertRaisesRegex(ValueError, "stale run binding"):
            self.helper.stage_candidate(self.p.root, attached, self.helper.sha(self.original_bytes))
        self.assertEqual(self.original, self.m)
        self.assertNotIn("attempt_ref", self.m["unit_runs"]["U-1"])
        archived = self.fixture.base.read(self.reference)
        self.assertEqual(self.original["unit_runs"]["U-1"], archived["run"])
        self.assertEqual(self.helper.attempt_checks(self.original, "U-1"), archived["checks"])
        self.assertEqual(self.original, archived["post_manifest"])
        self.assertEqual(self.fixture.context, archived["context_ref"])
        result = self.continuation()
        candidate = result["manifest"]
        self.assertEqual([self.reference], candidate["attempt_history"]["U-1"])
        self.assertEqual({"status": "pending", "run_id": "synthetic-attempt-2", "findings": []},
                         candidate["unit_runs"]["U-1"])
        self.assertEqual(self.original["implementation_gate"], candidate["implementation_gate"])
        self.assertEqual(self.original["unit_plan"], candidate["unit_plan"])
        self.assertTrue(all(c["execution_status"] == "not_run" for c in candidate["verification"]["checks"]))
        context = self.fixture.base.read(result["context_ref"])
        self.assertEqual(self.reference, context["prior_attempt_ref"])
        self.assertEqual(self.original["implementation_gate"], context["manifest"]["implementation_gate"])
        staged = self.helper.stage_candidate(self.p.root, candidate, self.helper.sha(self.original_bytes))
        self.assertEqual(self.original_bytes, (self.p.root / "forge/sdd-manifest.json").read_bytes())
        activated = self.helper.activate_candidate(self.p.root, staged, self.helper.sha(self.original_bytes))
        self.assertEqual("activated", activated["status"])
        journal = self.fixture.base.read(activated["journal_ref"])
        self.assertEqual(self.original_bytes, (self.p.root / journal["before"]["path"]).read_bytes())
        self.assertEqual(self.attempt_bytes, (self.p.root / self.reference["path"]).read_bytes())
        self.assertEqual(self.context_bytes, (self.p.root / self.fixture.context["path"]).read_bytes())
        self.m.clear()
        self.m.update(candidate)
        self.assertEqual("passed", self.fixture.base.report("implementation", "start", "U-1")["result"])
        self.fixture.base.assert_blocked(self.fixture.base.report("implementation", "complete", "U-1"))
        self.fixture.base.assert_blocked(self.fixture.base.report("implementation", "start", "U-2"))

    def test_missing_history_and_changed_original_events_block_replacement(self):
        candidate = self.continuation()["manifest"]
        for mutation in ("history", "run", "check"):
            with self.subTest(mutation=mutation):
                original, changed = copy.deepcopy(self.original), copy.deepcopy(candidate)
                if mutation == "history":
                    changed["attempt_history"].pop("U-1")
                elif mutation == "run":
                    original["unit_runs"]["U-1"]["started_at"] = "2026-08-20T10:00:00Z"
                else:
                    next(c for c in original["verification"]["checks"] if c["check_id"] == "QA-02")["findings"] = [{"detail": "changed original check"}]
                with self.assertRaisesRegex(ValueError, "exact immutable attempt"):
                    self.helper.validate_transition(self.p.root, original, changed, {})

    def test_tampered_archive_changed_sources_and_authority_block_continuation(self):
        for mutation in ("archive", "source", "authority"):
            with self.subTest(mutation=mutation):
                path = self.p.root / (self.reference["path"] if mutation == "archive" else "docs/qa-checklist.md")
                original_bytes = path.read_bytes()
                gate = copy.deepcopy(self.m["implementation_gate"])
                try:
                    if mutation == "authority":
                        self.m["implementation_gate"]["prompt_id"] = "substituted-authority"
                    else:
                        path.write_bytes(original_bytes + b"\nChanged preserved bytes.\n")
                    with self.assertRaises(ValueError):
                        self.continuation()
                finally:
                    if mutation != "authority":
                        path.write_bytes(original_bytes)
                    self.m["implementation_gate"] = gate
