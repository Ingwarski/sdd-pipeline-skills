"""Read-only capacity queries must release their SQLite handles immediately."""
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
from evidence.manager import Manager
from evidence.policy import load_defaults
from evidence.transports import LocalTransport


class CapacityHandleTests(unittest.TestCase):
    def test_successful_and_rejected_capacity_reads_close_all_connections(self):
        with tempfile.TemporaryDirectory(prefix="sdd-capacity-handles-") as temporary:
            root = Path(temporary).resolve()
            policy = load_defaults()
            policy.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider="local")
            policy["limits"]["free_space_reserve_bytes"] = 0
            manager = Manager(LocalTransport(root / "durable"), root / "home", policy)
            database = manager.state / "accounting.sqlite"
            with Accounting(database, policy["project_id"], policy):
                pass
            connections = []
            real_connect = sqlite3.connect

            def track_connection(*args, **kwargs):
                connection = real_connect(*args, **kwargs)
                connections.append(connection)
                self.addCleanup(connection.close)
                return connection

            with patch("evidence.manager.sqlite3.connect", side_effect=track_connection):
                manager._capacity(0)
                with self.assertRaisesRegex(EvidenceError, "working-space allowance"):
                    manager._capacity(policy["limits"]["local_stop_bytes"])
            self.assertEqual(len(connections), 2)
            for connection in connections:
                with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
                    connection.execute("SELECT 1")
            database.unlink()  # Native Windows also verifies no open handle remains.
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
