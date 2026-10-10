"""Cold identity and actual ZIP space are bounded using isolated local fixtures."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/to-sdd-pipeline/scripts"))
from evidence.io import EvidenceError, hash_file
from evidence.manager import Manager
from evidence.policy import load_defaults
from evidence.transports import LocalTransport


class ResourceEdgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdd-resource-edge-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.policy = {**load_defaults(), "project_id": str(uuid.uuid4()),
                       "store_id": str(uuid.uuid4()), "provider": "local"}
        self.policy["limits"]["free_space_reserve_bytes"] = 0
        self.transport = LocalTransport(self.base / "store")
        self.manager = Manager(self.transport, self.base / "home", self.policy)
        self.source = self.base / "source"
        self.source.write_bytes(b"first!")
        self.spec = {"version": 1, "files": [{"path": str(self.source),
            "sealed_at": "2099-01-01T00:00:00Z", "provenance": {"run_id": "run", "unit_id": "unit"}}]}

    def test_cold_same_operation_cannot_adopt_changed_equal_length_content(self):
        first = self.manager.archive(self.spec)
        # Preserve selected durable storage and coordinator while modelling the
        # lost local ledger and operation journal from a cold resume.
        for path in self.manager.state.glob("archive-*.json"):
            path.unlink()
        for path in self.manager.state.glob("accounting.sqlite*"):
            path.unlink()
        self.source.write_bytes(b"other!")
        with self.assertRaisesRegex(EvidenceError, "inventory|generation|content"):
            self.manager.archive(self.spec)
        catalog = self.manager._catalog()
        self.assertEqual(set(catalog["refs"]), {first[0]["artifact_id"]})
        self.assertEqual(self.manager.status()["gross_generated_bytes"], 6)

    def test_successful_publication_then_interruption_does_not_charge_resume_twice(self):
        publish = self.manager._publish
        def publish_then_stop(catalog, segment):
            publish(catalog, segment)
            raise EvidenceError("fixture interruption after successful root publication")
        with patch.object(self.manager, "_publish", side_effect=publish_then_stop):
            with self.assertRaisesRegex(EvidenceError, "fixture interruption"):
                self.manager.archive(self.spec)
        refs = self.manager.archive(self.spec)
        status = self.manager.status()
        self.assertEqual(len(refs), 1)
        self.assertEqual(status["gross_generated_bytes"], 6)
        self.assertEqual(status["original_logical_files"], 1)
        self.assertEqual(status["accounting"]["reservations"], [])

    def test_many_tiny_members_reserve_measured_capture_pack_and_readback_peak(self):
        logical = []
        for index in range(1000):
            source = self.base / ("tiny-" + str(index))
            source.write_bytes(index.to_bytes(4, "little"))
            digest, size = hash_file(source)
            logical.append({"path": str(source), "sha256": digest, "size": size})
        checkpoint = {"path": str(self.manager.state / "archive-tiny.json"),
                      "migration": False, "packs": {}, "refs": [], "next_file": 0}
        original_get = self.transport.get
        measured = []
        def get_with_peak(locator, destination, maximum):
            result = original_get(locator, destination, maximum)
            actual_staging = sum(path.stat().st_size for path in self.manager.staging.rglob("*") if path.is_file())
            with sqlite3.connect(self.manager.state / "accounting.sqlite") as connection:
                held = connection.execute("SELECT bytes FROM working_reservations WHERE id=? AND state='pending'",
                    (self.manager._working_reservation,)).fetchone()
            self.assertIsNotNone(held)
            measured.append((actual_staging, held[0]))
            self.assertLessEqual(actual_staging, held[0], "actual ZIP overhead exceeded the atomic working hold")
            return result
        with patch.object(self.transport, "get", side_effect=get_with_peak):
            locations = self.manager._small_packs(logical, checkpoint, {})
        self.assertEqual(len(locations), 1000)
        self.assertEqual(len(measured), 1)
        self.assertGreater(measured[0][0], 4000 * 3 + 65536)


if __name__ == "__main__":
    unittest.main()
