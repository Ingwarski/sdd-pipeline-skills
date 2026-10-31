"""Sealed reuse through real isolated local archival; no live connector or product QA."""
import copy
import json
import unittest

import test_evidence_manager as storage_fixture
import test_per_check_reuse as reuse_fixture


class PerCheckStorageReuseTests(unittest.TestCase):
    def setUp(self):
        self.reuse = reuse_fixture.PerCheckReuseTests(methodName="runTest")
        self.reuse.setUp()
        self.addCleanup(self.reuse.doCleanups)
        self.storage = storage_fixture.EvidenceManagerTests(methodName="runTest")
        self.storage.setUp()
        self.addCleanup(self.storage.doCleanups)
        self.p, self.m, self.h = self.reuse.p, self.reuse.m, self.reuse.h
        self.manager = self.storage.manager
        self.cache = self.manager.cache
        self.p.write("forge/evidence-policy.json", json.dumps(self.storage.policy))
        self.m["evidence_storage"] = {"policy_path": "forge/evidence-policy.json"}
        self.refresh_accounting()

    def refresh_accounting(self):
        with self.manager.accounting_receipt_snapshot(self.p.hash("forge/evidence-policy.json")) as receipt:
            self.m["evidence_accounting"] = copy.deepcopy(receipt)

    def test_local_archive_reuses_seal_time_accounting_and_rejects_missing_proof(self):
        self.reuse.start_and_seal(seal=False)
        check = self.reuse.check
        run = self.m["unit_runs"]["U-1"]
        context = self.reuse.base.read(self.reuse.context)
        self.assertNotIn(run["run_id"], context["manifest"]["evidence_accounting"]["runs"])
        legacy = copy.deepcopy(check["evidence"])
        paths = [self.storage.file("observations/" + str(index) + ".json",
                                   (self.p.root / evidence["path"]).read_bytes())
                 for index, evidence in enumerate(legacy)]
        spec = self.storage.spec(*paths, kinds=[item["kind"] for item in legacy], run=run["run_id"])
        bindings = self.h.api().Checker(self.p.root, self.m).check_bindings(check)
        for item in spec["files"]:
            item.update(schema="sdd-result-v1", sealed_at=check["executed_at"],
                        provenance={"run_id": run["run_id"], "unit_id": "U-1", "check_id": check["check_id"]},
                        bindings=copy.deepcopy(bindings))
        references = self.manager.archive(spec)
        self.manager.prepare(references)
        check["evidence"] = references
        for path in {item["path"] for item in legacy}:
            (self.p.root / path).unlink()
        self.refresh_accounting()
        self.assertEqual("complete", self.m["evidence_accounting"]["runs"][run["run_id"]]["status"])
        self.assertTrue(self.storage.pack_puts(), "fixture must really archive through local transport")

        seal_ref = self.h.seal_check(self.p.root, self.m, "U-1", check["check_id"],
                                    self.reuse.settlement, self.reuse.inputs, evidence_cache=self.cache)
        check["seal_ref"] = seal_ref
        sealed = self.reuse.base.read(seal_ref)
        self.assertEqual(self.m["evidence_accounting"], sealed["accounting"]["evidence_accounting"])
        attempt_ref = self.h.capture_attempt(self.p.root, self.m, "U-1", self.reuse.context,
                                            run["run_id"], "interrupted", evidence_cache=self.cache)
        run["attempt_ref"] = attempt_ref
        original = copy.deepcopy(check)
        continued = self.h.capture_continuation(self.p.root, self.m, "U-1", attempt_ref,
                                               "synthetic-storage-continuation", self.reuse.inventory(),
                                               evidence_cache=self.cache)
        reused = next(item for item in continued["manifest"]["verification"]["checks"]
                      if item["check_id"] == check["check_id"])
        self.assertEqual("passed", reused["execution_status"])
        for field in ("evidence", "executed_at", "run_id", "findings"):
            self.assertEqual(original.get(field), reused.get(field))
        report = self.h.api().Checker(self.p.root, continued["manifest"], evidence_cache=self.cache).run(
            "implementation", unit_action="start", unit_id="U-1", require_current=True)
        self.assertEqual("passed", report["result"], report)

        attempt = self.reuse.base.read(attempt_ref)
        for defect in ("missing", "incomplete"):
            with self.subTest(accounting=defect):
                bad_seal = copy.deepcopy(sealed)
                if defect == "missing":
                    bad_seal["accounting"].pop("evidence_accounting")
                else:
                    bad_seal["accounting"]["evidence_accounting"]["runs"][run["run_id"]]["status"] = "incomplete"
                bad_ref = self.h.store_record(self.p.root, "sealed-checks", bad_seal)
                bad_attempt = copy.deepcopy(attempt)
                next(item for item in bad_attempt["checks"] if item["check_id"] == check["check_id"])["seal_ref"] = bad_ref
                checker = self.h.api().Checker(self.p.root, self.m, evidence_cache=self.cache)
                checker._history_cache = {}
                # Evidence resolution reports accounting failures through its
                # public unreadable-evidence boundary before final run accounting.
                with self.assertRaisesRegex(ValueError, "accounting|sealed evidence is unreadable or changed"):
                    self.h.validate_sealed_check(self.p.root, bad_ref, bad_attempt, context, checker)

        # The checker must use independently prepared bytes, never the retained ZIP
        # or the now-removed original observation as an implicit repair source.
        cached = self.cache / "objects" / references[0]["sha256"]
        cached.write_bytes(b"Corrupted prepared original.\n")
        with self.assertRaises((ValueError, OSError)):
            self.h.capture_continuation(self.p.root, self.m, "U-1", attempt_ref,
                                       "synthetic-corrupt-cache-continuation", self.reuse.inventory(),
                                       evidence_cache=self.cache)


if __name__ == "__main__":
    unittest.main()
