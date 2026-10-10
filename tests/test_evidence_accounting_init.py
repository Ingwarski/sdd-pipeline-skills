"""Failed accounting initialization releases real SQLite file handles."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence.accounting import Accounting
from evidence.io import EvidenceError
from evidence.policy import load_defaults


class AccountingInitializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name).resolve() / "accounting.sqlite"
        self.policy = load_defaults()
        self.policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider="local")
        with Accounting(self.path, self.policy["project_id"], self.policy):
            pass

    def rejected_connection(self, policy, message):
        connections = []
        real_connect = sqlite3.connect

        def track_connection(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connections.append(connection)
            # Also release a leaked connection if this regression fails.
            self.addCleanup(connection.close)
            return connection

        with patch("evidence.accounting.sqlite3.connect", side_effect=track_connection):
            with self.assertRaisesRegex(EvidenceError, message):
                Accounting(self.path, policy["project_id"], policy)
        self.assertEqual(len(connections), 1)
        with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
            connections[0].execute("SELECT 1")

    def assert_database_can_be_reopened_and_deleted(self):
        # Native Windows fails this unlink if the rejected constructor leaked
        # its database handle, even though POSIX permits unlinking open files.
        with Accounting(self.path, self.policy["project_id"], self.policy) as ledger:
            self.assertEqual(ledger.snapshot()["runs"], [])
        self.path.unlink()
        self.assertFalse(self.path.exists())

    def test_wrong_project_closes_connection_and_preserves_identity(self):
        wrong_policy = deepcopy(self.policy)
        wrong_policy["project_id"] = str(uuid.uuid4())
        self.rejected_connection(wrong_policy, "ledger belongs to another project")
        self.assert_database_can_be_reopened_and_deleted()

    def test_unsupported_version_closes_connection_and_preserves_version(self):
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("UPDATE identity SET value='999' WHERE key='version'")
            connection.commit()
        finally:
            connection.close()
        self.rejected_connection(self.policy, "unsupported accounting ledger version")
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("SELECT value FROM identity WHERE key='version'").fetchone()[0], "999")
            connection.execute("UPDATE identity SET value='1' WHERE key='version'")
            connection.commit()
        finally:
            connection.close()
        self.assert_database_can_be_reopened_and_deleted()


if __name__ == "__main__":
    unittest.main()
