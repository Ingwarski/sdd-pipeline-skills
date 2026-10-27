"""Manager wiring and operation lifetime for proof-backed source payloads.

The classifier's native/index security checks have separate tests. These checks
exercise actual Manager enumeration, physical occupancy and lock boundaries.
"""
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_evidence_manager as fixtures
from evidence.io import EvidenceError
from evidence.manager import Manager


class SourcePayloadManagerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EvidenceManagerTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manager = self.fixture.manager
        self.project = self.fixture.base / "classification-project"
        self.project.mkdir(mode=0o700)
        self.external_control = self.project / "external-index.json"
        self.external_control.write_bytes(b"{}\n")
        view = self.manager.cache / "source-views" / ("a" * 64) / "views" / ("b" * 64)
        self.payload = view / "files" / "bulk.json"
        self.payload.parent.mkdir(parents=True)
        self.payload.write_bytes(b'{"bulk": "original source bytes"}\n')
        self.receipt = view / "receipt.json"
        self.receipt.write_bytes(b"{}\n")
        self.unknown = self.manager.state / "unknown.json"
        self.unknown.write_bytes(b"{}\n")
        self.instances = []
        self.audit_error = None
        self.foreign = False
        self.control_is_payload = False
        owner = self

        class Scope:
            def __init__(self, project, cache, policy):
                owner.assertEqual(owner.project, project)
                owner.assertEqual(owner.manager.cache, cache)
                owner.assertEqual(owner.manager.policy, policy)
                self.calls = self.audits = 0
                owner.instances.append(self)

            def payload_paths(self, candidates):
                self.calls += 1
                owner.assertIn(owner.payload, candidates)
                owner.assertIn(owner.receipt, candidates)
                owner.assertNotIn(owner.unknown, candidates)
                return {owner.unknown if owner.foreign else owner.payload}

            def audit(self):
                self.audits += 1
                if owner.audit_error is not None:
                    raise owner.audit_error

            def control_paths(self):
                return {owner.receipt, owner.payload if owner.control_is_payload else owner.external_control}

        self.module = SimpleNamespace(SourcePayloadScope=Scope)
        self.mock = patch.dict(sys.modules, {"evidence.source_payloads": self.module})
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def enable_project(self):
        self.manager = Manager(self.manager.transport, self.manager.home,
                               self.manager.policy, project=self.project)

    def test_default_without_project_keeps_all_json_as_metadata(self):
        records = self.manager._metadata_records()
        self.assertTrue({self.payload, self.receipt, self.unknown} <= set(records))
        self.assertEqual([], self.instances)

    def test_exact_payload_filter_retains_controls_and_physical_occupancy(self):
        before_usage, before_cache = self.manager._usage(), self.manager._cache_bytes()
        self.enable_project()
        records = self.manager._metadata_records()
        self.assertNotIn(self.payload, records)
        self.assertTrue({self.receipt, self.unknown} <= set(records))
        self.assertIn(self.external_control, records)
        self.assertEqual(1, records.count(self.receipt))
        self.assertEqual(before_usage, self.manager._usage())
        self.assertEqual(before_cache, self.manager._cache_bytes())
        self.assertEqual(1, self.instances[0].audits)

    def test_nested_operation_reuses_scope_and_audits_only_at_outer_exit(self):
        self.enable_project()
        with self.manager.locked():
            self.manager._metadata_records()
            with self.manager.locked():
                self.manager._metadata_records()
            self.assertEqual(1, len(self.instances))
            self.assertEqual(2, self.instances[0].calls)
            self.assertEqual(0, self.instances[0].audits)
        self.assertEqual(1, self.instances[0].audits)
        self.assertIsNone(self.manager._source_payload_scope)
        self.assertEqual(0, self.manager._catalog_lock_depth)

    def test_standalone_calls_do_not_reuse_proof_between_operations(self):
        self.enable_project()
        self.manager._metadata_records()
        self.manager._metadata_records()
        self.assertEqual(2, len(self.instances))
        self.assertEqual([1, 1], [x.audits for x in self.instances])

    def test_exit_audit_failure_blocks_operation_and_clears_scope(self):
        self.enable_project()
        self.audit_error = EvidenceError("synthetic source changed before exit")
        with self.assertRaisesRegex(EvidenceError, "source changed"):
            with self.manager.locked():
                self.manager._metadata_records()
        self.assertIsNone(self.manager._source_payload_scope)
        self.assertEqual(0, self.manager._catalog_lock_depth)

    def test_body_failure_still_audits_and_preserves_exception(self):
        self.enable_project()
        with self.assertRaisesRegex(RuntimeError, "original body failure"):
            with self.manager.locked():
                self.manager._metadata_records()
                raise RuntimeError("original body failure")
        self.assertEqual(1, self.instances[0].audits)
        self.assertIsNone(self.manager._source_payload_scope)

    def test_foreign_classifier_path_is_rejected_and_audited(self):
        self.enable_project()
        self.foreign = True
        with self.assertRaisesRegex(EvidenceError, "foreign metadata paths"):
            self.manager._metadata_records()
        self.assertEqual(1, self.instances[0].audits)

    def test_no_candidate_source_json_needs_no_classifier(self):
        self.payload.unlink()
        self.receipt.unlink()
        self.enable_project()
        self.assertIn(self.unknown, self.manager._metadata_records())
        self.assertEqual([], self.instances)

    def test_noncanonical_project_is_rejected(self):
        with self.assertRaisesRegex(EvidenceError, "canonical project"):
            Manager(self.manager.transport, self.manager.home, self.manager.policy, project=Path("."))

    def test_a_consumed_control_cannot_be_exempted_as_payload(self):
        self.enable_project()
        self.control_is_payload = True
        with self.assertRaisesRegex(EvidenceError, "cannot exempt a consumed control"):
            self.manager._metadata_records()
        self.assertEqual(1, self.instances[0].audits)

    def test_changed_proof_keeps_actual_working_reservation_pending(self):
        self.enable_project()
        with self.assertRaisesRegex(EvidenceError, "changed before settlement"):
            with self.manager._working(4096):
                self.manager._metadata_records()
                self.audit_error = EvidenceError("changed before settlement")
        database = self.manager.state / "accounting.sqlite"
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute("SELECT bytes,state FROM working_reservations").fetchall()
        self.assertEqual([(4096, "pending")], rows)
        self.assertEqual(0, self.manager._working_depth)
        self.assertIsNone(self.manager._working_reservation)

    def test_changed_proof_blocks_transport_publication_before_put(self):
        self.enable_project()
        source = self.fixture.file("prospective-control.json", b"{}\n")
        before = list(self.manager.transport.puts)
        with self.assertRaisesRegex(EvidenceError, "changed before publication"):
            with self.manager.locked():
                self.manager._metadata_records()
                self.audit_error = EvidenceError("changed before publication")
                self.manager._transport_call("put", "synthetic/control.json", source)
        self.assertEqual(before, self.manager.transport.puts)


if __name__ == "__main__":
    unittest.main()
