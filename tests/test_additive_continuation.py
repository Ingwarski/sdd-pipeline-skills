"""Additive executor inputs preserve failed history and grant no inherited pass."""
import copy
import unittest

import test_attempt_history as fixtures


class AdditiveContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AttemptHistoryTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.start()
        self.reference = self.fixture.capture()
        self.helper = self.fixture.helper
        self.base = self.fixture.base
        self.p, self.m = self.fixture.p, self.fixture.m
        self.context = self.helper.validate_context(self.p.root, self.fixture.context, "U-1")
        self.attempt = self.base.read(self.reference)
        self.review = self.fixture.continuation_inventory()
        self.prepared = self.helper.prepare_inventory(
            self.helper.api().Checker(self.p.root, self.m), "U-1", self.review)

    def validate(self, reviewed):
        self.helper.continuation_inventory(self.context, self.attempt, reviewed)

    def add(self, reviewed):
        reviewed["execution_inputs"]["executor/retry.py"] = {"mode": "file"}
        reviewed["execution_fingerprints"]["executor/retry.py"] = {
            "mode": "file", "exists": True, "content_hash": "a" * 64}
        return reviewed

    def test_exact_original_selection_remains_accepted(self):
        self.validate(self.prepared)

    def test_additive_reviewed_executor_keeps_all_original_inputs(self):
        reviewed = self.add(copy.deepcopy(self.prepared))
        self.validate(reviewed)
        for path, value in self.attempt["input_inventory"]["execution_inputs"].items():
            self.assertEqual(value, reviewed["execution_inputs"][path])
            self.assertEqual(self.attempt["input_inventory"]["execution_fingerprints"][path],
                             reviewed["execution_fingerprints"][path])

    def test_missing_extra_or_original_fingerprint_is_rejected(self):
        for mutation in ("missing_new", "missing_original", "unselected_fingerprint"):
            with self.subTest(mutation=mutation):
                reviewed = self.add(copy.deepcopy(self.prepared))
                if mutation == "missing_new":
                    del reviewed["execution_fingerprints"]["executor/retry.py"]
                elif mutation == "missing_original":
                    del reviewed["execution_fingerprints"][next(iter(self.prepared["execution_inputs"]))]
                else:
                    reviewed["execution_fingerprints"]["unreviewed.py"] = {"mode": "absent", "exists": False}
                with self.assertRaisesRegex(ValueError, "every exact fingerprint"):
                    self.validate(reviewed)

    def test_removed_replaced_mode_changed_or_byte_changed_original_is_rejected(self):
        for mutation in ("removed", "replaced", "mode", "hash", "exists", "fingerprint_mode"):
            with self.subTest(mutation=mutation):
                reviewed = self.add(copy.deepcopy(self.prepared))
                path = next(iter(self.prepared["execution_inputs"]))
                if mutation in ("removed", "replaced"):
                    selection = reviewed["execution_inputs"].pop(path)
                    fingerprint = reviewed["execution_fingerprints"].pop(path)
                    if mutation == "replaced":
                        reviewed["execution_inputs"]["replacement.py"] = selection
                        reviewed["execution_fingerprints"]["replacement.py"] = fingerprint
                elif mutation == "mode":
                    reviewed["execution_inputs"][path] = {"mode": "tree"}
                elif mutation == "hash":
                    reviewed["execution_fingerprints"][path]["content_hash"] = "f" * 64
                elif mutation == "exists":
                    reviewed["execution_fingerprints"][path]["exists"] = False
                else:
                    reviewed["execution_fingerprints"][path]["mode"] = "absent"
                with self.assertRaisesRegex(ValueError, "changed or removed preserved execution input"):
                    self.validate(reviewed)

    def test_semantic_source_acceptance_and_binding_changes_remain_rejected(self):
        for field in ("sources", "inputs", "bindings"):
            with self.subTest(field=field):
                reviewed = self.add(copy.deepcopy(self.prepared))
                reviewed[field]["substituted-acceptance"] = {"mode": "full"}
                with self.assertRaisesRegex(ValueError, "relevant acceptance definitions"):
                    self.validate(reviewed)

    def test_additive_inputs_still_require_fresh_review(self):
        reviewed = self.add(copy.deepcopy(self.prepared))
        reviewed["review"]["reviewed_at"] = "2000-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "fresh owner review"):
            self.validate(reviewed)

    def test_actual_capture_adds_source_resets_all_owned_checks_and_preserves_history(self):
        preserved_bytes = (self.p.root / self.reference["path"]).read_bytes()
        source_bytes = (self.p.root / "src/alpha.txt").read_bytes()
        self.p.write("executor/retry.py", "# Corrected executor in a fresh distinct attempt.\n")
        review = self.fixture.continuation_inventory()
        review["execution_inputs"]["executor/retry.py"] = {"mode": "file"}
        result = self.helper.capture_continuation(self.p.root, self.m, "U-1", self.reference,
                                                  "synthetic-additive-attempt-2", review)
        candidate = result["manifest"]
        self.helper.validate_transition(self.p.root, self.m, candidate, {})
        self.assertEqual("pending", candidate["unit_runs"]["U-1"]["status"])
        self.assertEqual("synthetic-additive-attempt-2", candidate["unit_runs"]["U-1"]["run_id"])
        self.assertEqual([self.reference], candidate["attempt_history"]["U-1"])
        owned = {key for key, allocation in candidate["unit_plan"]["acceptance"].items()
                 if allocation["owner_unit"] == "U-1"}
        for check in candidate["verification"]["checks"]:
            if check["check_id"] in owned:
                self.assertEqual("not_run", check["execution_status"])
                for key in self.helper.EXECUTION_KEYS - {"execution_status", "findings"}:
                    self.assertNotIn(key, check)
        context = self.base.read(result["context_ref"])
        self.assertEqual(self.reference, context["prior_attempt_ref"])
        self.assertIn("executor/retry.py", context["input_inventory"]["execution_inputs"])
        self.assertEqual(self.p.hash("executor/retry.py"),
                         context["input_inventory"]["execution_fingerprints"]["executor/retry.py"]["content_hash"])
        self.assertEqual(preserved_bytes, (self.p.root / self.reference["path"]).read_bytes())
        self.assertEqual(source_bytes, (self.p.root / "src/alpha.txt").read_bytes())
        self.assertEqual("failed", self.base.read(self.reference)["checks"][0]["execution_status"])
        self.assertEqual(self.m["implementation_gate"], candidate["implementation_gate"])
        self.assertEqual(self.m["unit_plan"], candidate["unit_plan"])
        self.m.clear()
        self.m.update(candidate)
        self.assertEqual("passed", self.base.report("implementation", "start", "U-1")["result"])
        self.base.assert_blocked(self.base.report("implementation", "complete", "U-1"))

    def test_actual_capture_original_file_change_and_removed_selection_fail(self):
        original = (self.p.root / "src/alpha.txt").read_bytes()
        for mutation in ("file_bytes", "mode", "remove"):
            with self.subTest(mutation=mutation):
                (self.p.root / "src/alpha.txt").write_bytes(original)
                if mutation == "file_bytes":
                    self.p.write("src/alpha.txt", "Changed original work cannot be hidden by additive input.\n")
                reviewed = self.fixture.continuation_inventory()
                self.p.write("executor/retry.py", "# new source\n")
                reviewed["execution_inputs"]["executor/retry.py"] = {"mode": "file"}
                if mutation == "mode":
                    reviewed["execution_inputs"]["src/alpha.txt"] = {"mode": "absent"}
                elif mutation == "remove":
                    reviewed["execution_inputs"].pop("src/alpha.txt")
                with self.assertRaises(ValueError):
                    self.helper.capture_continuation(self.p.root, self.m, "U-1", self.reference,
                                                     "synthetic-additive-attempt-2", reviewed)


if __name__ == "__main__":
    unittest.main()
