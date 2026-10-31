"""Cold sealed-check snapshots through the real isolated local archive."""
import copy
import unittest

import test_evidence_manager as storage_fixture
import test_history_source_archive as archive_fixture
import test_per_check_reuse as reuse_fixture


class SealedSourceArchiveTests(unittest.TestCase):
    archive_records = archive_fixture.HistorySourceArchiveTests.archive_records
    prepare = archive_fixture.HistorySourceArchiveTests.prepare
    remove_sources = archive_fixture.HistorySourceArchiveTests.remove_sources

    def setUp(self):
        self.reuse = reuse_fixture.PerCheckReuseTests("runTest")
        self.reuse.setUp()
        self.addCleanup(self.reuse.doCleanups)
        self.reuse.start_and_seal()
        self.p, self.m, self.helper = self.reuse.p, self.reuse.m, self.reuse.h
        self.storage = storage_fixture.EvidenceManagerTests("runTest")
        self.storage.setUp()
        self.addCleanup(self.storage.doCleanups)
        self.manager, self.cache = self.storage.manager, self.storage.manager.cache

    def test_sealed_source_archive_restores_original_truth_without_local_snapshots(self):
        references = (self.reuse.context, self.reuse.seal, self.reuse.attempt)
        envelopes = {ref["path"]: (self.p.root / ref["path"]).read_bytes() for ref in references}
        self.archive_records(references)
        self.prepare()
        self.p.save()
        self.remove_sources()
        self.assertFalse((self.p.root / self.helper.read_ref(self.p.root, self.reuse.seal)["files"]["src/alpha.txt"]["path"]).exists())
        current = self.helper.capture_continuation(self.p.root, self.m, "U-1", self.reuse.attempt,
                                                   "synthetic-cold-continuation", self.reuse.inventory(),
                                                   evidence_cache=self.cache)
        check = next(item for item in current["manifest"]["verification"]["checks"] if item["check_id"] == "QA-02")
        self.assertEqual("passed", check["execution_status"])
        self.assertEqual(self.reuse.original["executed_at"], check["executed_at"])
        self.assertEqual(self.reuse.seal, check["reused_from"]["seal_ref"])
        self.assertEqual(envelopes, {path: (self.p.root / path).read_bytes() for path in envelopes})
        report = self.helper.api().Checker(self.p.root, current["manifest"], evidence_cache=self.cache).run(
            "implementation", unit_action="start", unit_id="U-1", require_current=True)
        self.assertEqual("passed", report["result"], report)

    def test_source_archive_requires_event_specific_versions(self):
        self.archive_records((self.reuse.context, self.reuse.seal))
        original_index = self.helper.read_ref(self.p.root, self.index)
        for index, bad_version in ((0, 1), (1, 2)):
            with self.subTest(record=index, version=bad_version):
                record = self.helper.read_ref(self.p.root, self.records[index]["record_ref"])
                record["version"] = bad_version
                bad_ref = self.helper.store_record(self.p.root, "invalid-fixture-records", record)
                document = copy.deepcopy(original_index)
                document["records"][index]["record_ref"] = bad_ref
                with self.assertRaisesRegex(ValueError, "original native history envelope"):
                    self.helper.SourceArchive(self.p.root, self.index, self.cache, _document=document)


if __name__ == "__main__":
    unittest.main()
