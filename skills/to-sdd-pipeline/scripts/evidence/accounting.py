"""Transactional cumulative resource accounting shared across project worktrees.

This ledger enforces managed reservations. Unrestricted external producers can
bypass reservations; registered-location reconciliation detects that and records
an incomplete run. It cannot physically prevent their writes.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import hashlib
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import stat
import subprocess
import time
import uuid

from .io import EvidenceError, atomic_json, hash_file, read_json, _is_link
from .policy import validate_policy


class BudgetExceeded(EvidenceError):
    def __init__(self, violations):
        self.violations = violations
        super().__init__("evidence budget exhausted: " + "; ".join(violations))


def _amount(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 2**63 - 1:
        raise EvidenceError(label + " must be a nonnegative integer")
    return value


def _identity(value, label):
    if not isinstance(value, str) or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise EvidenceError(label + " must be a stable nonempty identifier")
    return value


class Accounting:
    """One SQLite ledger per stable project, stored outside every Git checkout."""

    def __init__(self, db_path, project_id: str, policy: dict, *, project_root=None):
        self.path = Path(db_path).absolute()
        self.policy = validate_policy(policy)
        self.project_id = project_id
        if project_id != self.policy["project_id"]:
            raise EvidenceError("accounting project identity differs from portable policy")
        if project_root is not None:
            root = Path(project_root).resolve()
            if self.path.resolve().is_relative_to(root):
                raise EvidenceError("accounting ledger must be outside the Git project")
        for ancestor in reversed(self.path.parents):
            if ancestor.exists() or ancestor.is_symlink():
                info = ancestor.lstat()
                if _is_link(info) or not stat.S_ISDIR(info.st_mode):
                    raise EvidenceError("unsafe accounting directory: " + str(ancestor))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for ancestor in (self.path, *self.path.parents):
            if ancestor.exists() and _is_link(ancestor.lstat()) or ancestor.is_symlink():
                raise EvidenceError("linked accounting path: " + str(ancestor))
        if self.path.exists() and not stat.S_ISREG(self.path.lstat().st_mode):
            raise EvidenceError("accounting ledger must be a regular file")
        self.recovery_dir = Path(str(self.path) + ".recovery")
        self._dirty_runs = set()
        self._journal_ready = False
        self._recovery_problem = None
        self.connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS identity (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, unit_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    gross_bytes INTEGER NOT NULL DEFAULT 0, gross_files INTEGER NOT NULL DEFAULT 0,
                    migration INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active', created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS reservations (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    bytes INTEGER NOT NULL, files INTEGER NOT NULL, local_bytes INTEGER NOT NULL,
                    metadata_bytes INTEGER NOT NULL, metadata_files INTEGER NOT NULL,
                    retained_bytes INTEGER NOT NULL DEFAULT 0, retained_objects INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS objects (
                    identity TEXT PRIMARY KEY, bytes INTEGER NOT NULL, physical_count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS local_usage (
                    key TEXT PRIMARY KEY, kind TEXT NOT NULL, bytes INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata_usage (
                    key TEXT PRIMARY KEY, bytes INTEGER NOT NULL, files INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS durable_generation (
                    operation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, unit_id TEXT NOT NULL,
                    gross_bytes INTEGER NOT NULL, logical_files INTEGER NOT NULL, mode TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS uncertain_generation (
                    reservation_id TEXT PRIMARY KEY REFERENCES reservations(id),
                    gross_bytes INTEGER NOT NULL, logical_files INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS working_reservations (
                    id TEXT PRIMARY KEY, bytes INTEGER NOT NULL, migration INTEGER NOT NULL,
                    metadata_bytes INTEGER NOT NULL DEFAULT 0, metadata_files INTEGER NOT NULL DEFAULT 0,
                    cache_bytes INTEGER NOT NULL DEFAULT 0,
                    owner_pid INTEGER, owner_host TEXT,
                    state TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS outputs (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), path TEXT NOT NULL,
                    reconciled INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS observations (
                    output_id TEXT NOT NULL REFERENCES outputs(id), path TEXT NOT NULL,
                    digest TEXT NOT NULL, bytes INTEGER NOT NULL,
                    PRIMARY KEY(output_id, path));
                CREATE TABLE IF NOT EXISTS producer_sessions (id TEXT PRIMARY KEY, record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS coordinator (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), owner TEXT NOT NULL,
                    expires REAL NOT NULL, complete_knowledge INTEGER NOT NULL);
            """)
            with self._transaction():
                # Intermediate ledgers and future recovery clients must preserve
                # unknown owners. NULL ownership is intentionally unverifiable.
                working_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(working_reservations)")}
                for name, declaration in (("metadata_bytes", "INTEGER NOT NULL DEFAULT 0"),
                                          ("metadata_files", "INTEGER NOT NULL DEFAULT 0"),
                                          ("cache_bytes", "INTEGER NOT NULL DEFAULT 0"),
                                          ("owner_pid", "INTEGER"), ("owner_host", "TEXT")):
                    if name not in working_columns:
                        self.connection.execute("ALTER TABLE working_reservations ADD COLUMN " + name + " " + declaration)
                prior = self.connection.execute("SELECT value FROM identity WHERE key='project_id'").fetchone()
                if prior is not None and prior[0] != project_id:
                    raise EvidenceError("ledger belongs to another project")
                self.connection.execute("INSERT OR IGNORE INTO identity VALUES ('project_id', ?)", (project_id,))
                self.connection.execute("INSERT OR IGNORE INTO identity VALUES ('version', '1')")
                version = self.connection.execute("SELECT value FROM identity WHERE key='version'").fetchone()[0]
                if version != "1":
                    raise EvidenceError("unsupported accounting ledger version")
                self._initialize_recovery()
        except BaseException:
            # A failed constructor has no context manager available to close
            # SQLite handles, which otherwise block native Windows cleanup.
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def _transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        checkpoint_started = False
        try:
            if self._journal_ready:
                reason = self._current_recovery_reason()
                if reason:
                    self._recovery_problem = reason
                    self.connection.execute("INSERT OR REPLACE INTO identity VALUES('recovery_required',?)", (reason,))
            yield
            if self._journal_ready:
                checkpoint_started = bool(self._dirty_runs)
                self._checkpoint_runs()
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            if checkpoint_started:
                self._recovery_problem = "accounting checkpoint/transaction was interrupted; known charges require recovery"
            raise
        finally:
            self._dirty_runs.clear()

    def _initialize_recovery(self):
        """Keep charge floors independently of SQLite; missing history fails closed.

        These compact checkpoints are not output backups. After database loss
        they recover known generation/holds, but cannot reconstruct lost output
        observations or certify completeness. Payload restoration still works.
        """
        if self.recovery_dir.is_symlink() or self.recovery_dir.exists() and (_is_link(self.recovery_dir.lstat()) or not self.recovery_dir.is_dir()):
            raise EvidenceError("unsafe accounting recovery directory")
        self.recovery_dir.mkdir(exist_ok=True)
        marker_path = self.recovery_dir / "marker.json"
        stored = self.connection.execute("SELECT value FROM identity WHERE key='ledger_id'").fetchone()
        reason = None
        if marker_path.exists():
            marker = read_json(marker_path, 4096)
            if not isinstance(marker, dict) or type(marker.get("version")) is not int or marker["version"] != 1 or marker.get("project_id") != self.project_id:
                raise EvidenceError("accounting recovery marker belongs to another project/version")
            _identity(marker.get("ledger_id"), "recovery ledger identity")
            _amount(marker.get("runs"), "recovery run count")
            _amount(marker.get("revision"), "recovery revision")
            if stored and stored[0] != marker["ledger_id"]:
                raise EvidenceError("accounting database and recovery journal identities differ")
            if not stored:
                reason = "accounting database was lost; original output observations and complete history require recovery"
            self._ledger_id = marker["ledger_id"]
            revision = self.connection.execute("SELECT value FROM identity WHERE key='recovery_revision'").fetchone()
            if stored and revision and int(revision[0]) == marker["revision"]:
                self._journal_ready = True
                return
            if stored:
                reason = "accounting transaction/checkpoint differs; complete generation accounting requires recovery"
        else:
            self._ledger_id = stored[0] if stored else str(uuid.uuid4())
            marker = {"runs": 0}
            if stored:
                reason = "accounting recovery journal was lost; complete generation history cannot be verified"
        self.connection.execute("INSERT OR IGNORE INTO identity VALUES('ledger_id',?)", (self._ledger_id,))
        paths = sorted(self.recovery_dir.glob("run-*.json"))
        if len(paths) > self.policy["limits"]["metadata_stop_files"]:
            raise EvidenceError("accounting recovery journal exceeds metadata file bound")
        if self._recovery_usage()[0] > self.policy["limits"]["metadata_stop_bytes"]:
            raise EvidenceError("combined accounting recovery journal exceeds metadata byte bound")
        if len(paths) != marker["runs"]:
            reason = "accounting recovery journal is incomplete; generation history cannot be verified"
        for path in paths:
            item = read_json(path, self.policy["limits"]["metadata_stop_bytes"])
            if not isinstance(item, dict) or not isinstance(item.get("run"), dict):
                raise EvidenceError("invalid accounting recovery checkpoint")
            run = item.get("run", {})
            if type(item.get("version")) is not int or item["version"] != 1 or item.get("project_id") != self.project_id or item.get("ledger_id") != self._ledger_id:
                raise EvidenceError("invalid accounting recovery checkpoint identity")
            _identity(run.get("id"), "recovered run"); _identity(run.get("unit_id"), "recovered unit")
            if path.name != self._recovery_path(run["id"]).name:
                raise EvidenceError("accounting recovery checkpoint has an invalid filename")
            for field in ("ordinal", "gross_bytes", "gross_files", "migration"):
                _amount(run.get(field), "recovered " + field)
            if run["migration"] not in (0, 1) or run.get("status") not in ("active", "complete", "incomplete"):
                raise EvidenceError("invalid recovered accounting run state")
            if not isinstance(run.get("created"), (int, float)) or isinstance(run["created"], bool):
                raise EvidenceError("invalid recovered accounting creation time")
            present = self.connection.execute("SELECT * FROM runs WHERE id=?", (run["id"],)).fetchone()
            if present is not None and (present["unit_id"] != run["unit_id"] or present["migration"] != run["migration"]):
                raise EvidenceError("recovered accounting run identity was rebound")
            if present is None or dict(present) != run:
                reason = reason or "accounting transaction/checkpoint differs; known charges retained but complete accounting requires recovery"
                if present is None:
                    self.connection.execute("INSERT INTO runs(id,unit_id,ordinal,gross_bytes,gross_files,migration,status,created) VALUES(?,?,?,?,?,?,?,?)", tuple(run[key] for key in ("id", "unit_id", "ordinal", "gross_bytes", "gross_files", "migration", "status", "created")))
                else:
                    self.connection.execute("UPDATE runs SET gross_bytes=MAX(gross_bytes,?),gross_files=MAX(gross_files,?) WHERE id=?", (run["gross_bytes"], run["gross_files"], run["id"]))
                self.connection.execute("UPDATE runs SET status='incomplete' WHERE id=?", (run["id"],))
            pending = item.get("pending")
            if not isinstance(pending, list):
                raise EvidenceError("invalid recovered pending reservations")
            for hold in pending:
                if not isinstance(hold, dict) or hold.get("run_id") != run["id"] or hold.get("state") != "pending":
                    raise EvidenceError("invalid recovered reservation binding")
                _identity(hold.get("id"), "recovered reservation")
                fields = ("id", "run_id", "bytes", "files", "local_bytes", "metadata_bytes", "metadata_files", "retained_bytes", "retained_objects", "state", "created")
                for field in fields[2:-2]:
                    _amount(hold.get(field), "recovered reservation " + field)
                if not isinstance(hold.get("created"), (int, float)) or isinstance(hold["created"], bool):
                    raise EvidenceError("invalid recovered reservation creation time")
                previous = self.connection.execute("SELECT * FROM reservations WHERE id=?", (hold["id"],)).fetchone()
                if previous is None:
                    self.connection.execute("INSERT INTO reservations(" + ",".join(fields) + ") VALUES(" + ",".join("?" for _ in fields) + ")", tuple(hold[field] for field in fields))
                    reason = reason or "pending accounting reservation recovered without its original ledger"
                elif dict(previous) != hold:
                    reason = reason or "pending accounting reservation and checkpoint differ"
            self._dirty_runs.add(run["id"])
        if reason:
            self.connection.execute("INSERT OR REPLACE INTO identity VALUES('recovery_required',?)", (reason,))
        self._dirty_runs.update(row[0] for row in self.connection.execute("SELECT id FROM runs"))
        self._journal_ready = True
        self._checkpoint_runs(force=True)
        self._dirty_runs.clear()

    def _recovery_path(self, run_id):
        return self.recovery_dir / ("run-" + hashlib.sha256(run_id.encode()).hexdigest() + ".json")

    def _checkpoint_runs(self, *, force=False):
        if not self._dirty_runs and not force:
            return
        count = self.connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        prior = self.connection.execute("SELECT value FROM identity WHERE key='recovery_revision'").fetchone()
        revision = int(prior[0]) + 1 if prior else 1
        marker = {"version": 1, "project_id": self.project_id, "ledger_id": self._ledger_id, "runs": count, "revision": revision}
        # Persist intent first. A crash after any subsequent partial write leaves
        # a revision mismatch, so another client cannot treat old totals as final.
        atomic_json(self.recovery_dir / "marker.json", marker)
        for run_id in sorted(self._dirty_runs):
            row = self.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                continue
            value = {"version": 1, "project_id": self.project_id, "ledger_id": self._ledger_id,
                     "run": dict(row), "pending": [dict(item) for item in self.connection.execute("SELECT * FROM reservations WHERE run_id=? AND state='pending' ORDER BY id", (run_id,))]}
            if len((json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode()) > self.policy["limits"]["metadata_stop_bytes"]:
                raise EvidenceError("accounting run checkpoint exceeds metadata byte bound")
            atomic_json(self._recovery_path(run_id), value)
        self.connection.execute("INSERT OR REPLACE INTO identity VALUES('recovery_revision',?)", (str(revision),))

    def require_generation_ready(self):
        reason = self._current_recovery_reason()
        if reason:
            raise EvidenceError("accounting recovery required: " + reason + "; restore the original accounting.sqlite and its journal before generating or completing evidence")

    def _current_recovery_reason(self):
        row = self.connection.execute("SELECT value FROM identity WHERE key='recovery_required'").fetchone()
        reason = self._recovery_problem or (row[0] if row else None)
        if reason:
            return reason
        try:
            marker = read_json(self.recovery_dir / "marker.json", 4096)
            revision = self.connection.execute("SELECT value FROM identity WHERE key='recovery_revision'").fetchone()
            if not isinstance(marker, dict) or marker.get("ledger_id") != self._ledger_id or revision is None or marker.get("revision") != int(revision[0]):
                return "accounting checkpoint/transaction differs; complete history requires recovery"
        except (EvidenceError, OSError, ValueError):
            return "accounting recovery marker is missing or unreadable; complete history requires recovery"
        return None

    def _recovery_usage(self):
        # Include interrupted atomic-write temporaries in the physical budget.
        byte_count, file_count = 0, 0
        for path in self.recovery_dir.iterdir():
            try:
                info = path.lstat()
            except FileNotFoundError:
                if path.name.startswith(".") and path.name.endswith(".tmp"):
                    # Atomic checkpoint temporaries can disappear while manager
                    # occupancy is inspected outside a ledger transaction.
                    continue
                raise
            if _is_link(info) or not stat.S_ISREG(info.st_mode):
                raise EvidenceError("unsafe accounting recovery journal entry: " + str(path))
            byte_count += info.st_size
            file_count += 1
        return byte_count, file_count

    def _ledger_bytes(self):
        result = self.path.stat().st_size
        for suffix in ("-wal", "-shm"):
            try:
                result += Path(str(self.path) + suffix).stat().st_size
            except FileNotFoundError:
                pass  # SQLite may remove an unused sidecar during checkpoint.
        return result + self._recovery_usage()[0]

    def _totals(self, run_id=None, unit_id=None):
        query = "SELECT COALESCE(SUM(gross_bytes),0), COALESCE(SUM(gross_files),0) FROM runs WHERE migration=0"
        project = tuple(self.connection.execute(query).fetchone())
        unit = tuple(self.connection.execute(query + " AND unit_id=?", (unit_id,)).fetchone()) if unit_id else (0, 0)
        run = self.connection.execute("SELECT gross_bytes,gross_files,migration,status FROM runs WHERE id=?", (run_id,)).fetchone() if run_id else None
        pending = self.connection.execute("""SELECT COALESCE(SUM(q.bytes),0), COALESCE(SUM(q.files),0),
            COALESCE(SUM(q.local_bytes),0), COALESCE(SUM(q.metadata_bytes),0), COALESCE(SUM(q.metadata_files),0)
            FROM reservations q JOIN runs r ON r.id=q.run_id WHERE q.state='pending' AND r.migration=0""").fetchone()
        unit_pending = self.connection.execute("""SELECT COALESCE(SUM(q.bytes),0), COALESCE(SUM(q.files),0)
            FROM reservations q JOIN runs r ON r.id=q.run_id WHERE q.state='pending' AND r.migration=0 AND r.unit_id=?""", (unit_id,)).fetchone() if unit_id else (0, 0)
        run_pending = self.connection.execute("SELECT COALESCE(SUM(bytes),0),COALESCE(SUM(files),0) FROM reservations WHERE state='pending' AND run_id=?", (run_id,)).fetchone() if run_id else (0, 0)
        all_pending = self.connection.execute("SELECT COALESCE(SUM(local_bytes),0),COALESCE(SUM(metadata_bytes),0),COALESCE(SUM(metadata_files),0),COALESCE(SUM(retained_bytes),0),COALESCE(SUM(retained_objects),0) FROM reservations WHERE state='pending'").fetchone()
        working_pending = self.connection.execute("SELECT COALESCE(SUM(bytes),0),COALESCE(SUM(metadata_bytes),0),COALESCE(SUM(metadata_files),0),COALESCE(SUM(cache_bytes),0) FROM working_reservations WHERE state='pending'").fetchone()
        objects = self.connection.execute("SELECT COALESCE(SUM(bytes),0),COALESCE(SUM(physical_count),0) FROM objects").fetchone()
        metadata = self.connection.execute("SELECT COALESCE(SUM(bytes),0),COALESCE(SUM(files),0) FROM metadata_usage").fetchone()
        local = self.connection.execute("SELECT COALESCE(SUM(bytes),0) FROM local_usage").fetchone()[0]
        cache = self.connection.execute("SELECT COALESCE(SUM(bytes),0) FROM local_usage WHERE kind='cache'").fetchone()[0]
        ledger_bytes = self._ledger_bytes()
        return {"project_generated_bytes": project[0], "project_generated_files": project[1],
                "unit_generated_bytes": unit[0], "unit_generated_files": unit[1],
                "run_generated_bytes": run[0] if run else 0, "run_generated_files": run[1] if run else 0,
                "pending_generated_bytes": pending[0], "pending_generated_files": pending[1],
                "pending_unit_bytes": unit_pending[0], "pending_unit_files": unit_pending[1],
                "pending_run_bytes": run_pending[0], "pending_run_files": run_pending[1],
                "pending_local_bytes": all_pending[0] + working_pending[0], "pending_working_bytes": working_pending[0],
                "pending_metadata_bytes": all_pending[1] + working_pending[1], "pending_metadata_files": all_pending[2] + working_pending[2],
                "pending_cache_bytes": working_pending[3],
                "pending_retained_bytes": all_pending[3], "pending_retained_objects": all_pending[4],
                "retained_unique_bytes": objects[0], "retained_physical_objects": objects[1],
                "metadata_bytes": metadata[0] + ledger_bytes, "metadata_files": metadata[1] + self._recovery_usage()[1],
                "local_bytes": local + ledger_bytes, "cache_bytes": cache,
                "ledger_bytes": ledger_bytes}

    def _violations(self, totals, *, extra_bytes=0, extra_files=0, extra_local=0,
                    extra_metadata=0, extra_metadata_files=0, extra_retained=0,
                    extra_retained_objects=0, migration=False):
        limits, errors = self.policy["limits"], []
        checks = [("combined local bytes", totals["local_bytes"] + totals["pending_local_bytes"] + extra_local,
                   limits["migration_local_stop_bytes"] if migration else limits["local_stop_bytes"]),
                  ("combined metadata bytes", totals["metadata_bytes"] + totals["pending_metadata_bytes"] + extra_metadata, limits["metadata_stop_bytes"]),
                  ("combined metadata files", totals["metadata_files"] + totals["pending_metadata_files"] + extra_metadata_files, limits["metadata_stop_files"])]
        if not migration:
            checks.extend([
                ("run bytes", totals["run_generated_bytes"] + totals["pending_run_bytes"] + extra_bytes, limits["run_stop_bytes"]),
                ("run logical files", totals["run_generated_files"] + totals["pending_run_files"] + extra_files, limits["run_stop_files"]),
                ("unit cumulative bytes", totals["unit_generated_bytes"] + totals["pending_unit_bytes"] + extra_bytes, limits["unit_stop_bytes"]),
                ("unit cumulative logical files", totals["unit_generated_files"] + totals["pending_unit_files"] + extra_files, limits["unit_stop_files"]),
                ("project cumulative bytes", totals["project_generated_bytes"] + totals["pending_generated_bytes"] + extra_bytes, limits["project_generation_stop_bytes"]),
                ("project cumulative logical files", totals["project_generated_files"] + totals["pending_generated_files"] + extra_files, limits["project_generation_stop_files"]),
                ("retained unique bytes", totals["retained_unique_bytes"] + totals["pending_retained_bytes"] + extra_retained, limits["retained_stop_bytes"]),
                ("retained physical objects", totals["retained_physical_objects"] + totals["pending_retained_objects"] + extra_retained_objects, limits["retained_stop_objects"]),
            ])
        else:
            checks.extend([("migration batch bytes", totals["run_generated_bytes"] + totals["pending_run_bytes"] + extra_bytes, limits["migration_batch_stop_bytes"]),
                           ("migration batch logical files", totals["run_generated_files"] + totals["pending_run_files"] + extra_files, limits["migration_batch_stop_files"])])
        for label, actual, maximum in checks:
            if actual > maximum:
                errors.append(label + " " + str(actual) + " exceeds " + str(maximum))
        return errors

    def reserve(self, run_id: str, unit_id: str, byte_count: int, file_count: int,
                *, local_bytes=0, metadata_bytes=0, metadata_files=0,
                retained_bytes=0, retained_objects=0,
                retry=False, migration=False, capacity_path=None, producer_record=None) -> str:
        """Atomically reserve gross generation and peak local capacity before writes.

        Every distinct non-migration run in a unit consumes one attempt, even when
        its caller omits ``retry``. Stable run IDs therefore resume without a new
        attempt, while renamed directories/chats cannot reset the unit budget.
        A migration run is one bounded batch; total migration volume is unbounded.
        An optional managed-producer record is bound to this reservation in the
        same transaction, so interruption cannot leave an unregistered launch hold.
        """
        _identity(run_id, "run_id"); _identity(unit_id, "unit_id")
        for value, label in ((byte_count, "bytes"), (file_count, "files"), (local_bytes, "local bytes"),
                             (metadata_bytes, "metadata bytes"), (metadata_files, "metadata files"),
                             (retained_bytes, "retained bytes"), (retained_objects, "retained objects")):
            _amount(value, label)
        session = None
        identifier = str(uuid.uuid4())
        if producer_record is not None:
            if (not isinstance(producer_record, dict)
                    or producer_record.get("reservation_id") is not None
                    or producer_record.get("output_id") is not None
                    or producer_record.get("status") != "launching"
                    or producer_record.get("run_id") != run_id
                    or producer_record.get("unit_id") != unit_id):
                raise EvidenceError("producer record must describe this unlaunched run/unit without existing bindings")
            attempt_id = _identity(producer_record.get("attempt_id"), "producer attempt_id")
            try:
                # Serialize before mutation/transaction: nested caller changes
                # cannot alter the identity or bytes committed for this attempt.
                value = json.loads(json.dumps(producer_record, allow_nan=False))
                value.update(reservation_id=identifier, output_id=None)
                session = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)
            except (ValueError, TypeError) as error:
                raise EvidenceError("producer record must contain finite JSON data") from error
            if len(session.encode("utf-8")) > metadata_bytes:
                raise EvidenceError("producer record exceeds its reserved metadata allowance")
        with self._transaction():
            self.require_generation_ready()
            if session is not None and self.connection.execute("SELECT 1 FROM producer_sessions WHERE id=?", (attempt_id,)).fetchone():
                raise EvidenceError("producer attempt identity is already registered")
            run = self.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                ordinal = self.connection.execute("SELECT COUNT(*) FROM runs WHERE unit_id=? AND migration=0", (unit_id,)).fetchone()[0]
                if not migration and ordinal > self.policy["limits"]["max_unit_retries"]:
                    raise BudgetExceeded(["unit retry allowance exhausted"])
                self.connection.execute("INSERT INTO runs(id,unit_id,ordinal,migration,created) VALUES(?,?,?,?,?)",
                                        (run_id, unit_id, ordinal, int(migration), time.time()))
            elif run["unit_id"] != unit_id or bool(run["migration"]) != bool(migration):
                raise EvidenceError("run identity cannot be rebound to another unit/accounting class")
            elif run["status"] != "active":
                raise EvidenceError("run is " + run["status"] + "; reconcile or start another bounded attempt")
            totals = self._totals(run_id, unit_id)
            journal_path = self._recovery_path(run_id)
            # One compact run snapshot is replaced atomically per change. Its
            # temporary copy and the new reservation's metadata share the same
            # combined bounds as payload writes; it is not free hidden storage.
            journal_peak = (journal_path.stat().st_size if journal_path.exists() else 0) + 8192
            violations = self._violations(totals, extra_bytes=byte_count, extra_files=file_count,
                                          extra_local=local_bytes + journal_peak, extra_metadata=metadata_bytes + 8192,
                                          extra_metadata_files=metadata_files + (0 if journal_path.exists() else 1), extra_retained=retained_bytes,
                                          extra_retained_objects=retained_objects, migration=migration)
            # Reservation uses peak additional writes plus the selected floor,
            # never a fixed 10 GiB prerequisite. Existing occupied bytes are
            # already reflected by the filesystem's current free capacity.
            capacity = Path(capacity_path) if capacity_path is not None else self.path.parent
            free = shutil.disk_usage(capacity).free
            if free - totals["pending_local_bytes"] - local_bytes - journal_peak < self.policy["limits"]["free_space_reserve_bytes"]:
                violations.append("free-space reserve cannot be preserved")
            if shutil.disk_usage(self.path.parent).free - journal_peak < self.policy["limits"]["free_space_reserve_bytes"]:
                violations.append("accounting journal cannot preserve free-space reserve")
            if violations:
                raise BudgetExceeded(violations)
            self.connection.execute("INSERT INTO reservations(id,run_id,bytes,files,local_bytes,metadata_bytes,metadata_files,retained_bytes,retained_objects,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                    (identifier, run_id, byte_count, file_count, local_bytes, metadata_bytes, metadata_files, retained_bytes, retained_objects, time.time()))
            if session is not None:
                self.connection.execute("INSERT INTO producer_sessions(id,record) VALUES(?,?)", (attempt_id, session))
            self._dirty_runs.add(run_id)
            return identifier

    def settle(self, reservation_id: str, actual_bytes: int, actual_files: int, *,
               local_bytes=0, metadata_bytes=0, metadata_files=0, objects=()) -> dict:
        """Charge actual writes, including overruns; never hide an exhausted run."""
        for value, label in ((actual_bytes, "actual bytes"), (actual_files, "actual files"),
                             (local_bytes, "local bytes"), (metadata_bytes, "metadata bytes"), (metadata_files, "metadata files")):
            _amount(value, label)
        prepared_objects = []
        for identity, byte_count, physical_count in objects:
            _identity(identity, "settled object identity")
            _amount(byte_count, "settled object bytes"); _amount(physical_count, "settled physical objects")
            prepared_objects.append((identity, byte_count, physical_count))
        with self._transaction():
            reservation = self.connection.execute("SELECT q.*,r.unit_id,r.migration FROM reservations q JOIN runs r ON r.id=q.run_id WHERE q.id=?", (reservation_id,)).fetchone()
            if reservation is None or reservation["state"] != "pending":
                raise EvidenceError("reservation is unknown or already settled")
            uncertain = self.connection.execute("SELECT gross_bytes,logical_files FROM uncertain_generation WHERE reservation_id=?", (reservation_id,)).fetchone()
            if uncertain:
                # Unknown gross production cannot be established from a later
                # surviving inventory. Preserve its held allowance and failure.
                raise EvidenceError("uncertain production requires original accounting recovery; reservation retained")
            self.connection.execute("UPDATE reservations SET state='settled' WHERE id=?", (reservation_id,))
            self.connection.execute("UPDATE runs SET gross_bytes=gross_bytes+?,gross_files=gross_files+? WHERE id=?", (actual_bytes, actual_files, reservation["run_id"]))
            self.connection.execute("INSERT OR REPLACE INTO local_usage VALUES(?,?,?)", ("settled:" + reservation_id, "capture", local_bytes))
            self.connection.execute("INSERT OR REPLACE INTO metadata_usage VALUES(?,?,?)", ("settled:" + reservation_id, metadata_bytes, metadata_files))
            added_retained_bytes, added_retained_objects = 0, 0
            for identity, byte_count, physical_count in prepared_objects:
                prior = self.connection.execute("SELECT bytes,physical_count FROM objects WHERE identity=?", (identity,)).fetchone()
                if prior is not None:
                    if tuple(prior) != (byte_count, physical_count):
                        raise EvidenceError("immutable settled object identity changed")
                    continue
                self.connection.execute("INSERT INTO objects VALUES(?,?,?)", (identity, byte_count, physical_count))
                added_retained_bytes += byte_count
                added_retained_objects += physical_count
            totals = self._totals(reservation["run_id"], reservation["unit_id"])
            violations = self._violations(totals, migration=bool(reservation["migration"]))
            if actual_bytes > reservation["bytes"] or actual_files > reservation["files"] or local_bytes > reservation["local_bytes"] or metadata_bytes > reservation["metadata_bytes"] or metadata_files > reservation["metadata_files"] or (not reservation["migration"] and (added_retained_bytes > reservation["retained_bytes"] or added_retained_objects > reservation["retained_objects"])):
                violations.insert(0, "producer exceeded its reservation")
            if reservation["migration"] and (actual_bytes > self.policy["limits"]["migration_batch_stop_bytes"] or actual_files > self.policy["limits"]["migration_batch_stop_files"]):
                violations.append("migration batch exceeded bounded allowance")
            if violations:
                self.connection.execute("UPDATE runs SET status='incomplete' WHERE id=?", (reservation["run_id"],))
            self._dirty_runs.add(reservation["run_id"])
            return {"reservation_id": reservation_id, "run_id": reservation["run_id"],
                    "incomplete": bool(violations), "violations": violations, "totals": totals}

    def record_uncertain(self, reservation_id: str, observed_bytes: int, observed_files: int):
        """Charge an observed lower bound while keeping an unknown output's hold.

        The operation is idempotent: repeated observations only raise its floor.
        A surviving reservation deliberately remains conservative until the
        original output and its complete accounting can be recovered.
        """
        _amount(observed_bytes, "observed bytes"); _amount(observed_files, "observed files")
        with self._transaction():
            row = self.connection.execute("SELECT q.*,r.unit_id FROM reservations q JOIN runs r ON r.id=q.run_id WHERE q.id=?", (reservation_id,)).fetchone()
            if row is None or row["state"] != "pending":
                raise EvidenceError("uncertain reservation is unknown or no longer pending")
            prior = self.connection.execute("SELECT gross_bytes,logical_files FROM uncertain_generation WHERE reservation_id=?", (reservation_id,)).fetchone()
            previous_bytes, previous_files = tuple(prior) if prior else (0, 0)
            byte_count, file_count = max(observed_bytes, previous_bytes), max(observed_files, previous_files)
            self.connection.execute("INSERT OR REPLACE INTO uncertain_generation VALUES(?,?,?)", (reservation_id, byte_count, file_count))
            self.connection.execute("UPDATE runs SET gross_bytes=gross_bytes+?,gross_files=gross_files+?,status='incomplete' WHERE id=?", (byte_count - previous_bytes, file_count - previous_files, row["run_id"]))
            self.connection.execute("INSERT OR REPLACE INTO identity VALUES('recovery_required',?)", ("managed output inventory is unknown; observed charges are lower bounds and its reservation remains held",))
            self._dirty_runs.add(row["run_id"])
            return {"reservation_id": reservation_id, "run_id": row["run_id"], "incomplete": True,
                    "violations": ["actual output inventory is unknown; reservation retained"],
                    "totals": self._totals(row["run_id"], row["unit_id"])}

    def cancel(self, reservation_id: str):
        """Release an unused reservation only; charged generation is immutable."""
        with self._transaction():
            if self.connection.execute("SELECT 1 FROM uncertain_generation WHERE reservation_id=?", (reservation_id,)).fetchone():
                raise EvidenceError("unknown actual output cannot release its reservation")
            row = self.connection.execute("SELECT run_id FROM reservations WHERE id=?", (reservation_id,)).fetchone()
            changed = self.connection.execute("UPDATE reservations SET state='cancelled' WHERE id=? AND state='pending'", (reservation_id,)).rowcount
            if not changed:
                raise EvidenceError("reservation is unknown or not pending")
            self._dirty_runs.add(row[0])

    def reserve_working(self, byte_count: int, *, capacity_path=None, migration=False,
                        exclude_reservation=None, metadata_bytes=0, metadata_files=0, cache_bytes=0) -> str:
        """Atomically hold transient working space without generation/retry charges.

        Readback and bounded recovery remain available while durable occupancy or
        cumulative generation is over its normal budget. Only combined local
        usage, concurrent holds and the configured free-space floor apply here.
        The manager reconciles its actual current state before calling this API.
        """
        _amount(byte_count, "working reservation bytes")
        _amount(metadata_bytes, "working metadata bytes"); _amount(metadata_files, "working metadata files")
        _amount(cache_bytes, "working cache bytes")
        if cache_bytes > byte_count:
            raise EvidenceError("working cache reservation exceeds combined working bytes")
        with self._transaction():
            totals = self._totals()
            excluded = 0
            if exclude_reservation is not None:
                own = self.connection.execute("SELECT local_bytes FROM reservations WHERE id=? AND state='pending'", (exclude_reservation,)).fetchone()
                excluded = own[0] if own else 0
            maximum = self.policy["limits"]["migration_local_stop_bytes" if migration else "local_stop_bytes"]
            violations = []
            if totals["local_bytes"] + totals["pending_local_bytes"] - excluded + byte_count > maximum:
                violations.append("combined local working reservation exceeds allowance")
            if (metadata_bytes or metadata_files) and (totals["metadata_bytes"] + totals["pending_metadata_bytes"] + metadata_bytes > self.policy["limits"]["metadata_stop_bytes"] or totals["metadata_files"] + totals["pending_metadata_files"] + metadata_files > self.policy["limits"]["metadata_stop_files"]):
                violations.append("combined metadata working reservation exceeds allowance")
            if cache_bytes and totals["cache_bytes"] + totals["pending_cache_bytes"] + cache_bytes > self.policy["limits"]["cache_stop_bytes"]:
                violations.append("combined cache working reservation exceeds allowance")
            capacity = Path(capacity_path) if capacity_path is not None else self.path.parent
            if shutil.disk_usage(capacity).free - totals["pending_local_bytes"] + excluded - byte_count < self.policy["limits"]["free_space_reserve_bytes"]:
                violations.append("working reservation cannot preserve free-space reserve")
            if violations:
                raise BudgetExceeded(violations)
            identifier = str(uuid.uuid4())
            self.connection.execute("INSERT INTO working_reservations(id,bytes,migration,metadata_bytes,metadata_files,cache_bytes,owner_pid,owner_host,created) VALUES(?,?,?,?,?,?,?,?,?)", (identifier, byte_count, int(migration), metadata_bytes, metadata_files, cache_bytes, os.getpid(), socket.gethostname(), time.time()))
            return identifier

    def finish_working(self, reservation_id: str, *, local_key=None, actual_bytes=0, kind="restore",
                       metadata_key=None, actual_metadata_bytes=0, actual_metadata_files=0,
                       cache_key=None, actual_cache_bytes=0):
        """Atomically replace a temporary hold with reconciled persistent usage."""
        _amount(actual_bytes, "settled working bytes")
        _amount(actual_metadata_bytes, "settled working metadata bytes"); _amount(actual_metadata_files, "settled working metadata files")
        _amount(actual_cache_bytes, "settled working cache bytes")
        if kind not in ("capture", "cache", "staging", "readback", "restore", "durable"):
            raise EvidenceError("unknown working storage classification")
        if local_key is not None:
            _identity(local_key, "settled working allocation")
        elif actual_bytes:
            raise EvidenceError("persistent working bytes require a registered local allocation")
        if metadata_key is not None:
            _identity(metadata_key, "settled metadata allocation")
        elif actual_metadata_bytes or actual_metadata_files:
            raise EvidenceError("persistent metadata requires a registered allocation")
        if cache_key is not None:
            _identity(cache_key, "settled cache allocation")
        elif actual_cache_bytes:
            raise EvidenceError("persistent cache requires a registered allocation")
        with self._transaction():
            row = self.connection.execute("SELECT * FROM working_reservations WHERE id=?", (reservation_id,)).fetchone()
            if row is None or row["state"] != "pending":
                raise EvidenceError("working reservation is unknown or already finished")
            self.connection.execute("UPDATE working_reservations SET state=? WHERE id=?", ("settled" if any(key is not None for key in (local_key, metadata_key, cache_key)) else "cancelled", reservation_id))
            prior_local = self.connection.execute("SELECT bytes FROM local_usage WHERE key=?", (local_key,)).fetchone() if local_key is not None else None
            prior_cache = self.connection.execute("SELECT bytes FROM local_usage WHERE key=?", (cache_key,)).fetchone() if cache_key is not None else None
            prior_metadata = self.connection.execute("SELECT bytes,files FROM metadata_usage WHERE key=?", (metadata_key,)).fetchone() if metadata_key is not None else None
            if local_key is not None:
                self.connection.execute("INSERT OR REPLACE INTO local_usage VALUES(?,?,?)", (local_key, kind, actual_bytes))
            if metadata_key is not None:
                self.connection.execute("INSERT OR REPLACE INTO metadata_usage VALUES(?,?,?)", (metadata_key, actual_metadata_bytes, actual_metadata_files))
            if cache_key is not None:
                self.connection.execute("INSERT OR REPLACE INTO local_usage VALUES(?,'cache',?)", (cache_key, actual_cache_bytes))
            totals = self._totals()
            maximum = self.policy["limits"]["migration_local_stop_bytes" if row["migration"] else "local_stop_bytes"]
            violations = []
            local_delta = max(0, actual_bytes - (prior_local[0] if prior_local else 0)) + max(0, actual_cache_bytes - (prior_cache[0] if prior_cache else 0))
            metadata_delta = max(0, actual_metadata_bytes - (prior_metadata[0] if prior_metadata else 0))
            metadata_files_delta = max(0, actual_metadata_files - (prior_metadata[1] if prior_metadata else 0))
            if local_delta > row["bytes"] or metadata_delta > row["metadata_bytes"] or metadata_files_delta > row["metadata_files"] or max(0, actual_cache_bytes - (prior_cache[0] if prior_cache else 0)) > row["cache_bytes"]:
                violations.append("working operation exceeded its reservation")
            if totals["local_bytes"] + totals["pending_local_bytes"] > maximum:
                violations.append("combined local working usage exceeds allowance")
            if totals["cache_bytes"] + totals["pending_cache_bytes"] > self.policy["limits"]["cache_stop_bytes"]:
                violations.append("combined cache bytes exceed allowance")
            if totals["metadata_bytes"] + totals["pending_metadata_bytes"] > self.policy["limits"]["metadata_stop_bytes"] or totals["metadata_files"] + totals["pending_metadata_files"] > self.policy["limits"]["metadata_stop_files"]:
                violations.append("combined metadata usage exceeds allowance")
            return {"incomplete": bool(violations), "violations": violations, "totals": totals}

    def record_object(self, identity: str, byte_count: int, physical_count=1):
        _identity(identity, "object identity"); _amount(byte_count, "object bytes"); _amount(physical_count, "object count")
        with self._transaction():
            prior = self.connection.execute("SELECT bytes,physical_count FROM objects WHERE identity=?", (identity,)).fetchone()
            if prior is not None:
                if tuple(prior) != (byte_count, physical_count):
                    raise EvidenceError("immutable object identity changed")
                return
            self.connection.execute("INSERT INTO objects VALUES(?,?,?)", (identity, byte_count, physical_count))
            violations = self._violations(self._totals())
            # Imported/migrated occupancy can already exceed the normal limit;
            # record its truthful size. Ordinary operations reserve beforehand.
            return {"violations": violations}

    def remove_object(self, identity: str):
        """Reconcile a verified physical removal; does not refund generation."""
        with self._transaction():
            self.connection.execute("DELETE FROM objects WHERE identity=?", (identity,))

    def reconcile_local(self, key: str, byte_count: int, kind="capture"):
        _identity(key, "local allocation"); _amount(byte_count, "local bytes")
        if kind not in ("capture", "cache", "staging", "readback", "restore", "durable"):
            raise EvidenceError("unknown local storage classification")
        with self._transaction():
            self.connection.execute("INSERT OR REPLACE INTO local_usage VALUES(?,?,?)", (key, kind, byte_count))
            totals = self._totals()
            violations = self._violations(totals)
            if totals["cache_bytes"] > self.policy["limits"]["cache_stop_bytes"]:
                violations.append("combined cache bytes exceed allowance")
            return {"violations": violations, "totals": totals}

    def reconcile_metadata(self, key: str, byte_count: int, file_count=1):
        _identity(key, "metadata allocation"); _amount(byte_count, "metadata bytes"); _amount(file_count, "metadata files")
        with self._transaction():
            self.connection.execute("INSERT OR REPLACE INTO metadata_usage VALUES(?,?,?)", (key, byte_count, file_count))
            totals = self._totals()
            return {"violations": self._violations(totals), "totals": totals}

    def reconcile_generation(self, catalog_generation: dict):
        """Merge authoritative immutable operation charges after cold recovery.

        ``operation_id -> {gross_bytes, logical_files, run_id, unit_id}`` is the
        remote schema. Distinct durable operations sum once per original run.
        Their totals raise the local floor but never erase larger local charges,
        including failed or interrupted attempts. Import/migration modes with
        zero new-generation charges register history without inventing a retry.
        Neither catalog adoption nor this ledger merge grants execution success.
        """
        if not isinstance(catalog_generation, dict):
            raise EvidenceError("catalog generation must be an operation mapping")
        prepared = []
        for operation_id, item in catalog_generation.items():
            _identity(operation_id, "durable operation")
            if not isinstance(item, dict):
                raise EvidenceError("invalid durable generation record")
            run_id, unit_id = item.get("run_id"), item.get("unit_id")
            _identity(run_id, "durable run"); _identity(unit_id, "durable unit")
            byte_count, file_count = item.get("gross_bytes"), item.get("logical_files")
            _amount(byte_count, "durable generated bytes"); _amount(file_count, "durable logical files")
            mode = item.get("mode", "generation")
            if mode not in ("generation", "managed-generation", "managed-run-total", "imported-existing", "migration"):
                raise EvidenceError("unsupported durable accounting mode")
            if mode in ("migration", "imported-existing") and (byte_count or file_count):
                raise EvidenceError("existing-data accounting cannot claim new generation charges")
            prepared.append((operation_id, run_id, unit_id, byte_count, file_count, mode))
        with self._transaction():
            for item in prepared:
                existing = self.connection.execute("SELECT operation_id,run_id,unit_id,gross_bytes,logical_files,mode FROM durable_generation WHERE operation_id=?", (item[0],)).fetchone()
                if existing is not None and tuple(existing) != item:
                    raise EvidenceError("immutable durable generation operation changed")
                self.connection.execute("INSERT OR IGNORE INTO durable_generation VALUES(?,?,?,?,?,?)", item)
            # New managed records are cumulative run snapshots, not independent
            # output charges. Multiple output archives and failure checkpoints
            # may publish the same run total. Keep the largest snapshot once.
            totals = self.connection.execute("""SELECT run_id,unit_id,
                MAX(SUM(CASE WHEN mode IN ('generation','managed-generation') THEN gross_bytes ELSE 0 END),
                    MAX(CASE WHEN mode='managed-run-total' THEN gross_bytes ELSE 0 END)),
                MAX(SUM(CASE WHEN mode IN ('generation','managed-generation') THEN logical_files ELSE 0 END),
                    MAX(CASE WHEN mode='managed-run-total' THEN logical_files ELSE 0 END))
                FROM durable_generation WHERE mode IN ('generation','managed-generation','managed-run-total')
                GROUP BY run_id,unit_id""").fetchall()
            for run_id, unit_id, byte_count, file_count in totals:
                run = self.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
                if run is not None:
                    if run["unit_id"] != unit_id or run["migration"]:
                        raise EvidenceError("durable run identity differs from local accounting")
                    self.connection.execute("UPDATE runs SET gross_bytes=MAX(gross_bytes,?),gross_files=MAX(gross_files,?) WHERE id=?", (byte_count, file_count, run_id))
                    if byte_count > run["gross_bytes"] or file_count > run["gross_files"]:
                        self._dirty_runs.add(run_id)
                else:
                    ordinal = self.connection.execute("SELECT COUNT(*) FROM runs WHERE unit_id=? AND migration=0", (unit_id,)).fetchone()[0]
                    self.connection.execute("INSERT INTO runs(id,unit_id,ordinal,gross_bytes,gross_files,migration,status,created) VALUES(?,?,?,?,?,0,'incomplete',?)", (run_id, unit_id, ordinal, byte_count, file_count, time.time()))
                    self.connection.execute("INSERT OR REPLACE INTO identity VALUES('recovery_required',?)", ("generation charges were reconstructed from the durable catalog without original run/output accounting; known totals are lower bounds",))
                    self._dirty_runs.add(run_id)
            actual = self._totals()
            return {"violations": self._violations(actual), "totals": actual}

    def register_output(self, run_id: str, unit_id: str, path) -> str:
        """Register an empty managed output folder before a producer starts."""
        path = Path(path).absolute()
        if not path.is_dir() or _is_link(path.lstat()) or any(path.iterdir()):
            raise EvidenceError("register an existing empty regular output directory")
        if any(_is_link(parent.lstat()) for parent in path.parents):
            raise EvidenceError("linked output directory parent")
        with self._transaction():
            run = self.connection.execute("SELECT unit_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None or run[0] != unit_id:
                raise EvidenceError("reserve the stable run/unit before registering output")
            identifier = str(uuid.uuid4())
            self.connection.execute("INSERT INTO outputs(id,run_id,path) VALUES(?,?,?)", (identifier, run_id, str(path)))
            return identifier

    def reconcile_output(self, output_id: str) -> dict:
        """Inventory unexpected stable files; changes always charge gross bytes."""
        row = self.connection.execute("SELECT o.*,r.unit_id,r.migration FROM outputs o JOIN runs r ON r.id=o.run_id WHERE o.id=?", (output_id,)).fetchone()
        if row is None:
            raise EvidenceError("unregistered output location")
        root = Path(row["path"])
        inventory = []
        if not root.is_dir() or _is_link(root.lstat()):
            raise EvidenceError("registered output location is missing or unsafe")
        for directory, subdirs, filenames in os.walk(root, followlinks=False):
            for dirname in subdirs:
                if _is_link((Path(directory) / dirname).lstat()):
                    raise EvidenceError("linked output directory")
            for filename in filenames:
                path = Path(directory) / filename
                digest, size = hash_file(path)
                inventory.append((path.relative_to(root).as_posix(), digest, size))
        with self._transaction():
            previous = {item["path"]: item for item in self.connection.execute("SELECT * FROM observations WHERE output_id=?", (output_id,))}
            changed = [(path, digest, size) for path, digest, size in inventory if path not in previous or previous[path]["digest"] != digest]
            added_bytes, added_files = sum(item[2] for item in changed), len(changed)
            if changed:
                self.connection.execute("UPDATE runs SET gross_bytes=gross_bytes+?,gross_files=gross_files+?,status='incomplete' WHERE id=?", (added_bytes, added_files, row["run_id"]))
                self._dirty_runs.add(row["run_id"])
            self.connection.execute("DELETE FROM observations WHERE output_id=?", (output_id,))
            self.connection.executemany("INSERT INTO observations VALUES(?,?,?,?)", [(output_id, *item) for item in inventory])
            self.connection.execute("UPDATE outputs SET reconciled=1 WHERE id=?", (output_id,))
            self.connection.execute("INSERT OR REPLACE INTO local_usage VALUES(?,?,?)", ("output:" + output_id, "capture", sum(item[2] for item in inventory)))
            totals = self._totals(row["run_id"], row["unit_id"])
            violations = self._violations(totals, migration=bool(row["migration"]))
            if changed:
                violations.insert(0, "unexpected output lacks settled managed accounting")
            return {"incomplete": bool(violations), "violations": violations,
                    "new_bytes": added_bytes, "new_files": added_files, "totals": totals}

    def acknowledge_output(self, output_id: str):
        """Bind the current inventory after settling its producer reservation.

        This avoids charging a managed output twice. The manager must invoke it
        only after it has compared produced bytes/counts with the settlement.
        """
        row = self.connection.execute("SELECT * FROM outputs WHERE id=?", (output_id,)).fetchone()
        if row is None:
            raise EvidenceError("unregistered output location")
        root, inventory = Path(row["path"]), []
        for directory, subdirs, filenames in os.walk(root, followlinks=False):
            if any(_is_link((Path(directory) / name).lstat()) for name in subdirs):
                raise EvidenceError("linked output directory")
            for name in filenames:
                path = Path(directory) / name
                digest, size = hash_file(path)
                inventory.append((output_id, path.relative_to(root).as_posix(), digest, size))
        with self._transaction():
            self.connection.execute("DELETE FROM observations WHERE output_id=?", (output_id,))
            self.connection.executemany("INSERT INTO observations VALUES(?,?,?,?)", inventory)
            self.connection.execute("UPDATE outputs SET reconciled=1 WHERE id=?", (output_id,))

    def complete_run(self, run_id: str) -> dict:
        """Completion requires settled reservations and reconciled output roots."""
        with self._transaction():
            self.require_generation_ready()
            row = self.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise EvidenceError("run has no required accounting")
            missing = self.connection.execute("SELECT COUNT(*) FROM outputs WHERE run_id=? AND reconciled=0", (run_id,)).fetchone()[0]
            pending = self.connection.execute("SELECT COUNT(*) FROM reservations WHERE run_id=? AND state='pending'", (run_id,)).fetchone()[0]
            if row["status"] == "incomplete" or missing or pending:
                raise EvidenceError("run incomplete: unresolved accounting, outputs, or reservation overrun")
            violations = self._violations(self._totals(run_id, row["unit_id"]), migration=bool(row["migration"]))
            if violations:
                raise BudgetExceeded(violations)
            self.connection.execute("UPDATE runs SET status='complete' WHERE id=?", (run_id,))
            self._dirty_runs.add(run_id)
            return self._totals(run_id, row["unit_id"])

    def mark_incomplete(self, run_id: str):
        """Persist a producer failure/stop without manufacturing an execution pass."""
        with self._transaction():
            if not self.connection.execute("UPDATE runs SET status='incomplete' WHERE id=?", (run_id,)).rowcount:
                raise EvidenceError("run has no required accounting")
            self._dirty_runs.add(run_id)

    def require_managed_source(self, output_id: str, run_id: str, unit_id: str,
                               path, digest: str, size: int):
        """Authorize archive registration without charging managed bytes twice.

        A caller-supplied mode flag cannot waive generation accounting. The
        source must match a reconciled observation of the exact completed run,
        unit and output root in the shared ledger, and still contain those bytes.
        """
        row = self.connection.execute("SELECT o.*,r.unit_id,r.status FROM outputs o JOIN runs r ON r.id=o.run_id WHERE o.id=?", (output_id,)).fetchone()
        if row is None or row["run_id"] != run_id or row["unit_id"] != unit_id or row["status"] != "complete" or not row["reconciled"]:
            raise EvidenceError("managed generation source has no completed reconciled run binding")
        source, root = Path(path).absolute(), Path(row["path"])
        try:
            relative = source.relative_to(root).as_posix()
        except ValueError as exc:
            raise EvidenceError("source is outside managed output location") from exc
        observed = self.connection.execute("SELECT * FROM observations WHERE output_id=? AND path=?", (output_id, relative)).fetchone()
        if observed is None or (observed["digest"], observed["bytes"]) != (digest, size) or hash_file(source) != (digest, size):
            raise EvidenceError("managed source differs from settled observation")
        return {"accounting_mode": "managed-generation", "run_id": run_id,
                "unit_id": unit_id, "output_id": output_id, "path": relative}

    def acquire_coordinator(self, owner: str, *, lease_seconds=300, complete_knowledge=False):
        """Serialize catalog mutation; incomplete clients never gain prune rights."""
        _identity(owner, "coordinator owner"); _amount(lease_seconds, "lease seconds")
        if not lease_seconds or lease_seconds > 3600:
            raise EvidenceError("coordinator lease must be between 1 and 3600 seconds")
        now = time.time()
        with self._transaction():
            prior = self.connection.execute("SELECT * FROM coordinator WHERE singleton=1").fetchone()
            if prior is not None and prior["owner"] != owner and prior["expires"] > now:
                raise EvidenceError("another coordinator holds the catalog lease")
            self.connection.execute("INSERT OR REPLACE INTO coordinator VALUES(1,?,?,?)", (owner, now + lease_seconds, int(complete_knowledge)))

    def require_coordinator(self, owner: str, *, pruning=False):
        prior = self.connection.execute("SELECT * FROM coordinator WHERE singleton=1").fetchone()
        if prior is None or prior["owner"] != owner or prior["expires"] <= time.time():
            raise EvidenceError("active coordinator lease required")
        if pruning and not prior["complete_knowledge"]:
            raise EvidenceError("shared remote pruning requires reconciled knowledge of every client")

    def release_coordinator(self, owner: str):
        with self._transaction():
            self.connection.execute("DELETE FROM coordinator WHERE singleton=1 AND owner=?", (owner,))

    def snapshot(self, run_id=None, unit_id=None):
        with self._transaction():
            totals = self._totals(run_id, unit_id)
            recovery_reason = self._current_recovery_reason()
            limits = self.policy["limits"]
            warnings = []
            for field, key in (("run_generated_bytes", "run_warning_bytes"), ("unit_generated_bytes", "unit_warning_bytes"),
                               ("project_generated_bytes", "project_generation_warning_bytes"), ("retained_unique_bytes", "retained_warning_bytes")):
                if totals[field] >= limits[key]:
                    warnings.append(field + " reached warning threshold")
            return {"project_id": self.project_id, "totals": totals, "warnings": warnings,
                    "accounting_complete": recovery_reason is None,
                    "recovery_required": recovery_reason,
                    "totals_are_lower_bounds": recovery_reason is not None,
                    "runs": [dict(row) for row in self.connection.execute("SELECT * FROM runs ORDER BY created,id")],
                    "working_reservations": [dict(row) for row in self.connection.execute("SELECT * FROM working_reservations WHERE state='pending' ORDER BY created,id")],
                    "reservations": [dict(row) for row in self.connection.execute("SELECT * FROM reservations WHERE state='pending' ORDER BY created,id")]}


def git_blob_growth(repo, base: str, head="HEAD", *, blob_review_bytes=1048576,
                    range_review_bytes=52428800) -> dict:
    """Count each unique newly introduced blob across the entire proposed range.

    Each commit's changed trees are examined, including merge-parent differences.
    A file introduced and subsequently removed remains counted. Blob deduplication
    is by Git object identity, not filename or only the final diff. Thresholds
    request review and never reject legitimate source material.
    """
    _amount(blob_review_bytes, "blob review threshold"); _amount(range_review_bytes, "range review threshold")

    def git(*arguments, binary=False):
        result = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, check=False)
        if result.returncode:
            raise EvidenceError("Git range accounting failed: " + result.stderr.decode("utf-8", "replace").strip())
        return result.stdout if binary else result.stdout.decode("ascii", "strict").strip()

    base_id = git("rev-parse", "--verify", base + "^{commit}")
    head_id = git("rev-parse", "--verify", head + "^{commit}")
    reachable = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", base_id, head_id], capture_output=True)
    if reachable.returncode:
        raise EvidenceError("base must be an ancestor of proposed head")
    commits = git("rev-list", "--reverse", base_id + ".." + head_id).splitlines()
    existing = {line.split(b" ", 1)[0].decode("ascii") for line in git("rev-list", "--objects", base_id, binary=True).splitlines()}
    blobs = set()
    for commit in commits:
        # Raw diff records include new object identity without parsing paths,
        # including names containing tabs/newlines. -m covers every merge parent.
        raw = git("diff-tree", "--root", "-m", "--no-commit-id", "-r", "--raw", "--no-abbrev", "-z", commit, binary=True)
        for record in raw.split(b"\0"):
            if not record.startswith(b":"):
                continue
            fields = record.split(b" ")
            if len(fields) >= 5:
                mode, identifier = fields[1], fields[3]
                if mode in (b"100644", b"100755", b"120000") and identifier.strip(b"0"):
                    identifier = identifier.decode("ascii")
                    if identifier not in existing:
                        blobs.add(identifier)
    sizes = {identifier: int(git("cat-file", "-s", identifier)) for identifier in sorted(blobs)}
    total = sum(sizes.values())
    return {"base": base_id, "head": head_id, "commits": len(commits),
            "new_blob_bytes": total, "new_blob_count": len(sizes), "blobs": sizes,
            "large_blobs": [key for key, size in sizes.items() if size > blob_review_bytes],
            "review_required": total > range_review_bytes or any(size > blob_review_bytes for size in sizes.values()),
            "enforced_rejection": False}
