"""Single-coordinator immutable catalogs, resumable packs, preparation and retention."""
from __future__ import annotations

from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import stat
import tempfile
import threading
import time
import uuid

from .archive import build_pack, verify_pack, capture
from .io import EvidenceError, atomic_json, hash_file, read_json, safe_relative, _open_regular, _verify_stable, _is_link
from .policy import validate_policy, resolve_historical_policy, LINEAGE_FIELD
from .identity import same_reference, same_imported_original
from . import process_identity


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def local_json_size(value):
    return len((json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode("utf-8"))


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as error:
        raise EvidenceError("sealed_at must be an original timezone-aware completion time") from error


class Manager:
    def __init__(self, transport, home, policy, *, project=None):
        self.transport, self.policy = transport, validate_policy(policy)
        self.project = Path(project) if project is not None else None
        if self.project is not None and (not self.project.is_absolute()
                or self.project.resolve(strict=True) != self.project or self.project.is_symlink()
                or not self.project.is_dir()):
            raise EvidenceError("source payload classification requires a canonical project directory")
        self.home = Path(home).resolve()
        self.state = self.home / "projects" / self.policy["project_id"]
        self.cache = self.state / "cache"
        self.staging = self.state / "staging"
        self.prefix = "projects/" + self.policy["project_id"] + "/"
        self.limits = self.policy["limits"]
        self.state.mkdir(parents=True, exist_ok=True)
        for path in (self.state, self.cache, self.staging):
            if path.is_symlink():
                raise EvidenceError("evidence working directory is linked")
            path.mkdir(exist_ok=True)
        identity = self.state / "coordinator.json"
        self.coordinator = self._coordinator_identity(identity)
        self._preparing = set()
        self._active_reservation = None
        self._working_depth = 0
        self._working_reservation = None
        self._working_migration = False
        self._catalog_working = None
        self._catalog_thread_lock = threading.RLock()
        self._catalog_lock_depth = 0
        self._source_payload_scope = None

    def _coordinator_identity(self, identity):
        """Publish once; the OS releases initialization ownership after a crash."""
        def existing():
            value = read_json(identity, 4096)
            if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"]:
                raise EvidenceError("coordinator identity is invalid; retained")
            return value["id"]

        # Initialized identities never change, so readers need no temporary
        # owner records and cannot inflate another operation's working usage.
        if identity.exists() or identity.is_symlink():
            return existing()
        with self._advisory_lock(self.state / ".coordinator-init.lock", 30):
            if not identity.exists() and not identity.is_symlink():
                atomic_json(identity, {"id": str(uuid.uuid4()), "host": socket.gethostname()})
            return existing()

    @staticmethod
    @contextmanager
    def _advisory_lock(guard, timeout):
        """Never remove this synchronization inode; process death releases it."""
        try:
            before = guard.lstat()
        except FileNotFoundError:
            before = None
        if before is not None and (_is_link(before) or not stat.S_ISREG(before.st_mode)):
            raise EvidenceError("ownership guard is unsafe; retained: " + str(guard))
        descriptor = os.open(guard, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        acquired = False
        try:
            info, current = os.fstat(descriptor), guard.lstat()
            if (not stat.S_ISREG(info.st_mode) or _is_link(current)
                    or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)):
                raise EvidenceError("ownership guard changed; retained: " + str(guard))
            deadline = time.monotonic() + timeout
            while not acquired:
                try:
                    if os.name == "nt":
                        import msvcrt
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (BlockingIOError, PermissionError):
                    if time.monotonic() >= deadline:
                        raise EvidenceError("ownership guard is busy; bounded wait exhausted: " + str(guard))
                    time.sleep(min(0.01, max(0, deadline - time.monotonic())))
            # Initialize under the lock, including when a previous creator died
            # before writing. Windows permits byte locks beyond current EOF.
            if os.fstat(descriptor).st_size == 0:
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            yield
        finally:
            if acquired:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @contextmanager
    def locked(self, timeout=600):
        with self._catalog_thread_lock:
            if self._catalog_lock_depth:
                self._catalog_lock_depth += 1
                try:
                    yield
                finally:
                    self._catalog_lock_depth -= 1
                return
            with self._file_locked(timeout):
                self._catalog_lock_depth = 1
                try:
                    yield
                finally:
                    try:
                        self._audit_source_payloads()
                    finally:
                        self._source_payload_scope = None
                        self._catalog_lock_depth = 0

    def _audit_source_payloads(self):
        """Check retained proofs before metadata-dependent commit boundaries."""
        if self._source_payload_scope is not None:
            self._source_payload_scope.audit()

    def _catalog_guard(self, timeout=600):
        return self._advisory_lock(self.state / ".catalog-lifecycle.lock", timeout)

    @staticmethod
    def _catalog_lock_identity(lock):
        try:
            info = lock.lstat()
        except FileNotFoundError:
            return None
        if _is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise EvidenceError("catalog coordinator lock is unsafe; retained: " + str(lock))
        return info.st_dev, info.st_ino, getattr(info, "st_birthtime_ns", None)

    @staticmethod
    def _catalog_owner(lock):
        try:
            owner = read_json(lock / "owner.json", 4096)
        except (FileNotFoundError, EvidenceError) as error:
            cause = getattr(error, "__cause__", None)
            if (isinstance(error, FileNotFoundError) or isinstance(cause, FileNotFoundError)
                    or getattr(cause, "winerror", None) in (32, 33)
                    or str(error).startswith(("file changed while opening:", "input changed while reading:"))):
                return None  # Bounded retry applies only to the ownership handshake.
            raise
        if not isinstance(owner, dict):
            raise EvidenceError("catalog lock ownership is invalid; retained")
        return owner

    @contextmanager
    def _file_locked(self, timeout):
        lock = self.state / "catalog.lock"
        deadline = time.monotonic() + timeout
        own = {"pid": os.getpid(), "host": socket.gethostname(), "coordinator": self.coordinator}
        while True:
            acquired = False
            with self._catalog_guard(max(0, deadline - time.monotonic())):
                try:
                    lock.mkdir()
                except FileExistsError:
                    identity = self._catalog_lock_identity(lock)
                    owner = self._catalog_owner(lock) if identity is not None else None
                    if owner is not None and identity == self._catalog_lock_identity(lock):
                        if owner.get("host") != socket.gethostname() or owner.get("coordinator") != self.coordinator:
                            raise EvidenceError("catalog lock belongs to another host/coordinator; retained")
                        if not self._owner_alive(owner.get("pid")):
                            # Legacy clients may not use the lifecycle guard.
                            # A completed owner can release and exit after our
                            # first observation; never mistake that for a stale lock.
                            if self._catalog_owner(lock) == owner and identity == self._catalog_lock_identity(lock):
                                raise EvidenceError("catalog coordinator exited; reconcile the recorded lock: " + str(lock))
                else:
                    identity = self._catalog_lock_identity(lock)
                    try:
                        atomic_json(lock / "owner.json", own)
                    except BaseException:
                        self._remove_catalog_lock(lock, identity, own, allow_unpublished=True)
                        raise
                    acquired = True
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise EvidenceError("catalog coordinator is busy; bounded wait exhausted: " + str(lock))
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            with self._catalog_guard():
                self._remove_catalog_lock(lock, identity, own)

    def _remove_catalog_lock(self, lock, identity, expected_owner, *, allow_unpublished=False):
        """Caller holds the lifecycle guard throughout validation and removal."""
        if identity is None or identity != self._catalog_lock_identity(lock):
            raise EvidenceError("catalog lock changed before release; retained")
        contents = {path.name for path in lock.iterdir()}
        if not contents and allow_unpublished:
            self._release_lock_directory(lock)
            return
        if contents != {"owner.json"}:
            raise EvidenceError("catalog lock ownership is incomplete; retained")
        deadline = time.monotonic() + 5
        while True:
            actual = self._catalog_owner(lock)
            if actual is not None:
                break
            if time.monotonic() >= deadline:
                raise EvidenceError("catalog owner could not be verified before release; retained")
            time.sleep(0.01)
        if actual != expected_owner or identity != self._catalog_lock_identity(lock):
            raise EvidenceError("catalog lock owner changed before release; retained")
        self._release_owner_file(lock / "owner.json")
        self._release_lock_directory(lock)

    @staticmethod
    def _release_owner_file(path):
        # Stable Windows readers can temporarily deny deletion. The lifecycle
        # guard prevents new managed readers until the complete removal ends.
        deadline = time.monotonic() + 5
        while True:
            try:
                path.unlink(missing_ok=True)
                return
            except PermissionError as error:
                if getattr(error, "winerror", None) not in (32, 33) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)

    @staticmethod
    def _release_lock_directory(path):
        deadline = time.monotonic() + 5
        while True:
            try:
                path.rmdir()
                return
            except PermissionError as error:
                if getattr(error, "winerror", None) not in (32, 33) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)

    @staticmethod
    def _owner_alive(pid):
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise EvidenceError("catalog lock has invalid process identity")
        if os.name == "nt":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                if ctypes.get_last_error() == 87:
                    return False
                raise EvidenceError("cannot verify catalog lock process exit")
            try:
                code = ctypes.c_ulong()
                if not kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                    raise EvidenceError("cannot inspect catalog lock process")
                return code.value == 259
            finally:
                kernel.CloseHandle(ctypes.c_void_p(handle))
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError as error:
            raise EvidenceError("cannot verify catalog lock process exit") from error

    def _reconcile_lock(self, dry_run):
        lock = self.state / "catalog.lock"
        with self._catalog_guard():
            identity = self._catalog_lock_identity(lock)
            if identity is None:
                return []
            if {p.name for p in lock.iterdir()} != {"owner.json"}:
                raise EvidenceError("catalog lock ownership is incomplete; inspect without removing: " + str(lock))
            owner = self._catalog_owner(lock)
            if owner is None:
                raise EvidenceError("catalog lock owner could not be verified; retained")
            if owner.get("host") != socket.gethostname() or owner.get("coordinator") != self.coordinator:
                raise EvidenceError("catalog lock belongs to another host/coordinator; retained")
            if self._owner_alive(owner.get("pid")):
                raise EvidenceError("catalog coordinator process is still running; retained")
            action = {"action": "reconcile-exited-catalog-lock", "path": str(lock), "dry_run": dry_run}
            if not dry_run:
                atomic_json(self.state / "lock-reconciliation.json", {"version": 1, "owner": owner, "verified_exited": True})
                if self._owner_alive(owner["pid"]):
                    raise EvidenceError("catalog lock changed during reconciliation; retained")
                self._remove_catalog_lock(lock, identity, owner)
                if self._catalog_lock_identity(lock) is not None:
                    raise EvidenceError("catalog lock removal failed")
                action["verified"] = True
            return [action]

    def _usage(self, *, include_ledger=True, include_checkpoints=True, seen=None):
        """Count distinct regular inode lengths across owned local state.

        Hardlink aliases share one payload charge; independent copies do not.
        This is neither logical generation accounting nor allocated disk blocks.
        No source-view subtree, receipt or unregistered regular file is exempt.
        """
        checkpoint_root = self._checkpoint_root()
        def excluded(path):
            return (not include_ledger and (path.name.startswith("accounting.sqlite") or
                (self.state / "accounting.sqlite.recovery") in path.parents) or
                not include_checkpoints and checkpoint_root is not None and
                (path == checkpoint_root or checkpoint_root in path.parents))
        seen = set() if seen is None else seen
        count = self._occupancy_bytes(self._workspace_records(self.state, excluded=excluded), seen=seen)
        count += self._occupancy_bytes(self._transport_records(), seen=seen)
        if include_checkpoints and checkpoint_root is not None and self.state not in checkpoint_root.parents and checkpoint_root != self.state:
            count += self._occupancy_bytes(self._checkpoint_records(), seen=seen)
        return count

    @staticmethod
    def _workspace_records(root, *, excluded=lambda path: False):
        """Inventory regular paths without following links, including orphan views."""
        root_info = root.lstat()
        if _is_link(root_info) or not stat.S_ISDIR(root_info.st_mode):
            raise EvidenceError("linked or non-directory evidence workspace: " + str(root))
        records = []
        def failed(error):
            raise error
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
            for name in dirs + files:
                path = Path(directory) / name
                if excluded(path):
                    continue
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue  # A managed sibling completed its reserved temporary work.
                if _is_link(info):
                    raise EvidenceError("unregistered link in evidence workspace: " + str(path))
                if stat.S_ISREG(info.st_mode):
                    records.append(path)
                elif not stat.S_ISDIR(info.st_mode):
                    raise EvidenceError("special file in evidence workspace")
        return records

    @staticmethod
    def _occupancy_bytes(paths, *, seen=None):
        seen = set() if seen is None else seen
        total = 0
        for path in paths:
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue  # Its in-flight peak remains reserved separately.
            if _is_link(info):
                raise EvidenceError("unregistered link in evidence workspace: " + str(path))
            if not stat.S_ISREG(info.st_mode):
                raise EvidenceError("special file in evidence workspace")
            identity = info.st_dev, info.st_ino
            if identity not in seen:
                seen.add(identity)
                total += info.st_size
        return total

    def _cache_bytes(self, *, seen=None):
        # Retained aliases remain cache occupancy even after objects/SHA is gone.
        # Counting the entire safe tree conservatively includes receipt metadata.
        return self._occupancy_bytes(self._workspace_records(self.cache), seen=seen)

    def _local_occupancy(self):
        """Attribute each owned inode once, including cross-bucket aliases."""
        seen = set()
        cache = self._cache_bytes(seen=seen)
        working = self._usage(include_ledger=False, include_checkpoints=False, seen=seen)
        checkpoints = self._occupancy_bytes(self._checkpoint_records(), seen=seen)
        return cache, working, checkpoints

    @staticmethod
    def _existing_bytes(paths):
        total = 0
        for path in paths:
            try:
                total += path.stat().st_size
            except FileNotFoundError:
                continue  # Occupancy disappeared; its in-flight peak remains reserved.
        return total

    def _checkpoint_root(self):
        if not getattr(self.transport, "checkpoint_peak_bytes", 0):
            return None
        return Path(self.transport.state_dir).absolute()

    def _checkpoint_records(self):
        root = self._checkpoint_root()
        if root is None:
            return []
        if root.is_symlink() or not root.is_dir():
            raise EvidenceError("transfer checkpoint directory is missing or linked")
        records = []
        for directory, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files:
                path = Path(directory) / name
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISREG(info.st_mode):
                    records.append(path)
                elif not stat.S_ISDIR(info.st_mode):
                    raise EvidenceError("transfer checkpoint directory contains an unsafe entry")
        return records

    def _checkpoint_allocations(self, ledger, *, actual_bytes=None):
        if self._checkpoint_root() is None:
            return
        records = self._checkpoint_records()
        metadata = [path for path in records if path.suffix == ".json"]
        if actual_bytes is None:
            actual_bytes = self._local_occupancy()[2]
        ledger.reconcile_local("transport-checkpoints", actual_bytes, "staging")
        self._audit_source_payloads()
        ledger.reconcile_metadata("transport-checkpoints", self._existing_bytes(metadata), len(metadata))

    @contextmanager
    def _checkpoint_working(self, upload_bytes):
        """Hold a checkpoint's atomic replacement and any immutable retry read."""
        from .accounting import Accounting
        with self.locked(), Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            self._checkpoint_allocations(ledger)
            ident = ledger.reserve_working(self.transport.checkpoint_peak_bytes + upload_bytes,
                migration=self._working_migration, metadata_bytes=self.transport.checkpoint_metadata_bytes,
                metadata_files=self.transport.checkpoint_metadata_files, capacity_path=self.transport.state_dir)
            failed = False
            try:
                yield
            except BaseException:
                failed = True
                raise
            finally:
                records = self._checkpoint_records()
                metadata = [path for path in records if path.suffix == ".json"]
                self._audit_source_payloads()
                result = ledger.finish_working(ident, local_key="transport-checkpoints",
                    actual_bytes=self._local_occupancy()[2], kind="staging", metadata_key="transport-checkpoints",
                    actual_metadata_bytes=self._existing_bytes(metadata), actual_metadata_files=len(metadata))
                violations = [value for value in result["violations"] if not value.startswith("combined cache")]
                if violations and not failed:
                    raise EvidenceError("transfer checkpoint settlement incomplete: " + "; ".join(violations))

    def _transport_records(self):
        folder = getattr(self.transport, "host_session_path", None)
        if folder is None:
            return []
        root = Path(folder).absolute()
        if root == self.state or self.state in root.parents:
            return []  # Already included in the ordinary workspace walk.
        if root.is_symlink() or not root.is_dir():
            raise EvidenceError("host transport session directory is missing or linked")
        records = []
        for directory, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files:
                path = Path(directory) / name
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISREG(info.st_mode):
                    records.append(path)
                elif not stat.S_ISDIR(info.st_mode):
                    raise EvidenceError("host transport session contains an unsafe entry")
        return records

    def _verify_catalog_host_cleanup(self):
        """Inspect the actual session even when occupancy is counted in this state."""
        folder = getattr(self.transport, "host_session_path", None)
        if folder is None:
            return
        from .transports import _directory
        descriptor = None
        problem = "catalog host request/materialization cleanup is incomplete"
        try:
            root = _directory(folder)
            before = root.lstat()
            if hasattr(os, "getuid") and before.st_uid != os.getuid():
                raise EvidenceError(problem + ": foreign session owner")
            if os.scandir in os.supports_fd:
                descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
                opened = os.fstat(descriptor)
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise EvidenceError(problem + ": session changed")
            with os.scandir(descriptor if descriptor is not None else root) as entries:
                for count, entry in enumerate(entries, 1):
                    if count > self.limits["metadata_stop_files"]:
                        raise EvidenceError(problem + ": session inspection bound exceeded")
                    if entry.name in ("request.json", "response.json") or entry.name.startswith("original-"):
                        raise EvidenceError(problem + ": retained native control or original")
                    info = entry.stat(follow_symlinks=False)
                    if _is_link(info) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                        raise EvidenceError(problem + ": unsafe session entry")
            after = _directory(root).lstat()
            fields = ("st_dev", "st_ino", "st_mtime_ns", "st_ctime_ns")
            if any(getattr(before, field) != getattr(after, field) for field in fields):
                raise EvidenceError(problem + ": session changed during inspection")
        except OSError as error:
            raise EvidenceError(problem + ": session cannot be inspected") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _capacity(self, peak, *, migration=False):
        local_limit = self.limits["migration_local_stop_bytes" if migration else "local_stop_bytes"]
        used, pending, external = self._usage(), 0, 0
        ledger_path = self.state / "accounting.sqlite"
        if ledger_path.is_file():
            with closing(sqlite3.connect(ledger_path.as_uri() + "?mode=ro", uri=True)) as connection:
                pending = connection.execute("SELECT COALESCE(SUM(local_bytes),0) FROM reservations WHERE state='pending' AND id!=?", (self._active_reservation or "",)).fetchone()[0]
                table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='working_reservations'").fetchone()
                if table:
                    pending += connection.execute("SELECT COALESCE(SUM(bytes),0) FROM working_reservations WHERE state='pending' AND id!=?", (self._working_reservation or "",)).fetchone()[0]
                external = connection.execute("SELECT COALESCE(SUM(bytes),0) FROM local_usage WHERE kind IN ('capture','restore') AND key!='manager-working'").fetchone()[0]
        if used + external + pending + peak > local_limit:
            raise EvidenceError("combined local working-space allowance exhausted")
        reserve = self.limits["free_space_reserve_bytes"]
        if shutil.disk_usage(self.state).free < pending + peak + reserve:
            raise EvidenceError("measured staging/restoration peak plus preserved free-space reserve unavailable")

    def _local_records(self, ledger):
        cache_bytes, working_bytes, checkpoint_bytes = self._local_occupancy()
        ledger.reconcile_local("cache", cache_bytes, "cache")
        ledger.reconcile_local("manager-working", working_bytes, "staging")
        records = self._metadata_records(include_checkpoints=False)
        self._audit_source_payloads()
        ledger.reconcile_metadata("local-journals-receipts", self._existing_bytes(p for p in records), len(records))
        self._checkpoint_allocations(ledger, actual_bytes=checkpoint_bytes)

    def _metadata_records(self, *, include_checkpoints=True):
        recovery = self.state / "accounting.sqlite.recovery"
        checkpoint_root = self._checkpoint_root()
        records = [p for p in self.state.rglob("*.json")
                if p.is_file() and not p.is_symlink() and recovery not in p.parents
                and (checkpoint_root is None or checkpoint_root not in p.parents)] + [
                p for p in self._transport_records() if p.suffix == ".json"]
        if include_checkpoints:
            records += [p for p in self._checkpoint_records() if p.suffix == ".json"]
        candidates = [p for p in records if p.is_relative_to(self.cache / "source-views")]
        if self.project is not None and candidates:
            from .source_payloads import SourcePayloadScope
            standalone = not self._catalog_lock_depth
            scope = self._source_payload_scope
            if scope is None:
                scope = SourcePayloadScope(self.project, self.cache, self.policy)
                if not standalone:
                    self._source_payload_scope = scope
            try:
                payloads = scope.payload_paths(candidates)
                if type(payloads) is not set or not payloads <= set(candidates):
                    raise EvidenceError("source payload proof returned foreign metadata paths")
                controls = scope.control_paths()
                if type(controls) is not set or any(not isinstance(p, Path) or not p.is_absolute()
                        or not (p.is_relative_to(self.project) or p.is_relative_to(self.cache)) for p in controls):
                    raise EvidenceError("source payload proof returned foreign control paths")
                if payloads & controls:
                    raise EvidenceError("source payload proof cannot exempt a consumed control")
                records = list(dict.fromkeys([p for p in records if p not in payloads] + sorted(controls)))
            finally:
                if standalone:
                    scope.audit()
        return records

    @contextmanager
    def _working(self, peak, *, migration=False, metadata_bytes=0, metadata_files=0, cache_bytes=0,
                 additional_peak=False, capacity_path=None, transport_scope=False):
        with self.locked():
            if self._catalog_working is not None:
                raise EvidenceError("catalog working scope cannot cover an unleased working operation")
            with self._working_reserved(peak, migration=migration, metadata_bytes=metadata_bytes,
                metadata_files=metadata_files, cache_bytes=cache_bytes, additional_peak=additional_peak,
                capacity_path=capacity_path, transport_scope=transport_scope):
                yield

    @contextmanager
    def _working_reserved(self, peak, *, migration=False, metadata_bytes=0, metadata_files=0, cache_bytes=0,
                          additional_peak=False, capacity_path=None, transport_scope=False):
        """Share atomic local holds with producers; nesting retains the outer peak."""
        nested = bool(self._working_depth)
        migration = migration or (nested and self._working_migration)
        if not nested and not transport_scope:
            overhead = getattr(self.transport, "working_overhead", None)
            control = overhead(upload_bytes=0, download_bytes=0) if overhead else 0
            if type(control) is not int or control < 0:
                raise EvidenceError("transport control overhead must be nonnegative")
            peak += control
            metadata_bytes += control
            metadata_files += 3 if control else 0
            session = getattr(self.transport, "host_session_path", None)
            if control and session is not None and shutil.disk_usage(session).free < control + self.limits["free_space_reserve_bytes"]:
                raise EvidenceError("host transport control peak cannot preserve the configured free-space reserve")
        if nested and not (metadata_bytes or metadata_files or cache_bytes or additional_peak):
            yield
            return
        from .accounting import Accounting
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            if not (nested and additional_peak):
                self._local_records(ledger)
            ident = ledger.reserve_working(peak if not nested or additional_peak else 0, migration=migration,
                exclude_reservation=self._active_reservation, metadata_bytes=metadata_bytes,
                metadata_files=metadata_files, cache_bytes=cache_bytes, capacity_path=capacity_path)
            if not nested:
                self._working_reservation = ident
                self._working_migration = migration
            self._working_depth += 1
            failed = False
            try:
                yield
            except BaseException:
                failed = True
                raise
            finally:
                try:
                    cache, working, checkpoints = self._local_occupancy()
                    records = self._metadata_records(include_checkpoints=False)
                    allocations = {"metadata_key": "local-journals-receipts", "actual_metadata_bytes": self._existing_bytes(p for p in records),
                        "actual_metadata_files": len(records)}
                    if nested and additional_peak and not (metadata_bytes or metadata_files):
                        allocations = {}  # The enclosing operation owns persistent control metadata.
                    if not nested:
                        allocations.update(local_key="manager-working", actual_bytes=working,
                            kind="staging", cache_key="cache", actual_cache_bytes=cache)
                        self._checkpoint_allocations(ledger, actual_bytes=checkpoints)
                    self._audit_source_payloads()
                    result = ledger.finish_working(ident, **allocations)
                    violations = [v for v in result["violations"] if not
                        (not metadata_bytes and not metadata_files and v.startswith("combined metadata")) and not
                        (not cache_bytes and v.startswith("combined cache"))]
                    if violations and not failed:
                        raise EvidenceError("working resource settlement incomplete: " + "; ".join(violations))
                finally:
                    self._working_depth -= 1
                    if not nested:
                        self._working_reservation = None
                        self._working_migration = False

    def _catalog_working_token(self, scope):
        if (scope is not self._catalog_working or not scope or not scope["open"]
                or scope["thread"] != threading.get_ident() or not self._catalog_lock_depth
                or scope["policy"] != self.policy):
            raise EvidenceError("catalog working scope is closed, foreign or changed")
        return scope

    @contextmanager
    def _catalog_working_scope(self):
        """One pending high-water hold for one fresh, independently validated catalog."""
        if not self._catalog_lock_depth:
            raise EvidenceError("catalog working scope requires catalog ownership")
        if self._catalog_working is not None or self._working_depth or self._working_reservation is not None:
            raise EvidenceError("catalog working scope cannot adopt an existing working operation")
        from .accounting import Accounting
        overhead = getattr(self.transport, "working_overhead", None)
        control = overhead(upload_bytes=0, download_bytes=0) if overhead else 0
        if type(control) is not int or control < 0:
            raise EvidenceError("transport control overhead must be nonnegative")
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            self._local_records(ledger)
            session = getattr(self.transport, "host_session_path", None)
            if session is not None and shutil.disk_usage(session).free < ledger._totals()["pending_local_bytes"] + control + self.limits["free_space_reserve_bytes"]:
                raise EvidenceError("host transport control peak cannot preserve the configured free-space reserve")
            ident = ledger.reserve_working(control, metadata_bytes=control, metadata_files=3 if control else 0)
            previous = self._working_reservation
            scope = {"open": True, "thread": threading.get_ident(), "policy": deepcopy(self.policy),
                "ledger": ledger, "id": ident, "control": control, "active": {}, "uncertain": False,
                "bounds": {"bytes": control, "metadata_bytes": control, "metadata_files": 3 if control else 0, "cache_bytes": 0}}
            self._catalog_working, self._working_reservation = scope, ident
            failure = None
            try:
                yield scope
            except BaseException as error:
                failure = error
                raise
            finally:
                try:
                    if scope["active"] or scope["uncertain"]:
                        raise EvidenceError("catalog working outcome is unknown; retained pending reservation " + ident)
                    cache, working, checkpoints = self._local_occupancy()
                    records = self._metadata_records(include_checkpoints=False)
                    allocations = {"metadata_key": "local-journals-receipts", "actual_metadata_bytes": self._existing_bytes(records),
                        "actual_metadata_files": len(records), "local_key": "manager-working", "actual_bytes": working,
                        "kind": "staging", "cache_key": "cache", "actual_cache_bytes": cache}
                    self._checkpoint_allocations(ledger, actual_bytes=checkpoints)
                    self._audit_source_payloads()
                    result = ledger.finish_working(ident, **allocations)
                    violations = [v for v in result["violations"] if not
                        (not control and v.startswith("combined metadata")) and not v.startswith("combined cache")]
                    if violations and failure is None:
                        raise EvidenceError("working resource settlement incomplete: " + "; ".join(violations))
                except BaseException as settlement:
                    if failure is None:
                        settlement.add_note("catalog working reservation: " + ident)
                        raise
                    failure.add_note("catalog working reservation " + ident + ": " + str(settlement))
                finally:
                    scope["open"] = False
                    self._catalog_working = None
                    self._working_reservation = previous

    @contextmanager
    def _catalog_working_lease(self, scope, byte_count, *, capacity_path=None):
        scope = self._catalog_working_token(scope)
        if type(byte_count) is not int or byte_count < 0:
            raise EvidenceError("catalog working lease must be a nonnegative byte bound")
        aggregate = scope["control"] + sum(scope["active"].values()) + byte_count
        self._capacity(aggregate)
        if capacity_path is not None:
            pending = scope["ledger"]._totals()["pending_local_bytes"] - scope["bounds"]["bytes"]
            if shutil.disk_usage(capacity_path).free < pending + aggregate + self.limits["free_space_reserve_bytes"]:
                raise EvidenceError("host transport working peak cannot preserve the configured free-space reserve")
        if aggregate > scope["bounds"]["bytes"]:
            from .accounting import BudgetExceeded
            try:
                scope["bounds"] = scope["ledger"].grow_working(scope["id"], aggregate,
                    metadata_bytes=scope["control"], metadata_files=3 if scope["control"] else 0,
                    capacity_path=capacity_path)
            except BudgetExceeded:
                raise  # Rejected before effects, with the previous hold intact.
            except BaseException:
                scope["uncertain"] = True  # COMMIT acknowledgement may have been lost.
                raise
        lease = object()
        scope["active"][lease] = byte_count
        try:
            yield
        finally:
            if not scope["uncertain"]:
                del scope["active"][lease]

    def _transport_call(self, method, *args, **kwargs):
        """Reserve durable transfer checkpoints separately from host queue peaks."""
        if method == "put":
            self._audit_source_payloads()
        if method == "put" and self._checkpoint_root() is not None:
            with self._checkpoint_working(Path(args[1]).stat().st_size):
                return self._transport_host_call(method, *args, **kwargs)
        return self._transport_host_call(method, *args, **kwargs)

    def _transport_host_call(self, method, *args, **kwargs):
        """Reserve private host queues and materialized originals outside this state."""
        if self._catalog_working is not None:
            scope = self._catalog_working_token(self._catalog_working)
            if method not in ("inventory", "keys", "stat", "get"):
                raise EvidenceError("catalog working scope permits only catalog read operations")
            overhead = getattr(self.transport, "working_overhead", None)
            peak = overhead(upload_bytes=0, download_bytes=args[2] if method == "get" else 0) if overhead else 0
            if type(peak) is not int or peak < scope["control"]:
                raise EvidenceError("transport control overhead must fit its working bound")
            with self._catalog_working_lease(scope, peak - scope["control"],
                    capacity_path=getattr(self.transport, "host_session_path", None)):
                try:
                    result = getattr(self.transport, method)(*args, **kwargs)
                    self._verify_catalog_host_cleanup()
                    return result
                except BaseException:
                    from .transports import LocalTransport
                    if not isinstance(self.transport, LocalTransport):
                        scope["uncertain"] = True
                    raise
        overhead = getattr(self.transport, "working_overhead", None)
        if overhead is None:
            return getattr(self.transport, method)(*args, **kwargs)
        upload = Path(args[1]).stat().st_size if method == "put" else 0
        download = args[2] if method == "get" else 0
        peak = overhead(upload_bytes=upload, download_bytes=download)
        if type(peak) is not int or peak < 0:
            raise EvidenceError("transport working overhead must be a nonnegative byte bound")
        if not peak:
            return getattr(self.transport, method)(*args, **kwargs)
        control = overhead(upload_bytes=0, download_bytes=0)
        if type(control) is not int or control < 0 or control > peak:
            raise EvidenceError("transport control overhead must fit its working bound")
        if self._working_depth:
            peak -= control  # The outer operation holds the fixed queue bound throughout.
            if not peak:
                return getattr(self.transport, method)(*args, **kwargs)
            control = 0
        with self._working(peak, additional_peak=True, metadata_bytes=control, metadata_files=3 if control else 0,
                           capacity_path=getattr(self.transport, "host_session_path", None), transport_scope=True):
            return getattr(self.transport, method)(*args, **kwargs)

    def _checkpoint(self, path, value):
        data = local_json_size(value)
        previous = path.stat().st_size if path.exists() else 0
        with self._working(data * 2 + 4096, metadata_bytes=max(0, data - previous) + 4096,
            metadata_files=0 if previous else 1):
            atomic_json(path, value)

    def _read_remote_json(self, locator, maximum):
        size = self._transport_call("stat", locator)["size"]
        if size > maximum:
            raise EvidenceError("remote metadata exceeds combined configured bound")
        if self._catalog_working is not None:
            scope = self._catalog_working_token(self._catalog_working)
            with self._catalog_working_lease(scope, size):
                temporary, failure = None, None
                try:
                    temporary = tempfile.TemporaryDirectory(dir=self.staging, prefix="index-")
                    target = Path(temporary.name).resolve() / "data.json"
                    self._transport_call("get", locator, target, size)
                    return read_json(target, maximum), hash_file(target)
                except BaseException as error:
                    failure = error
                    raise
                finally:
                    if temporary is not None:
                        try:
                            temporary.cleanup()
                            if os.path.lexists(temporary.name):
                                raise EvidenceError("catalog temporary materialization remains")
                        except BaseException as cleanup:
                            scope["uncertain"] = True
                            if failure is None:
                                raise
                            failure.add_note("catalog temporary cleanup failed: " + str(cleanup))
        self._capacity(size)
        with self._working(size), tempfile.TemporaryDirectory(dir=self.staging, prefix="index-") as temp:
            target = Path(temp).resolve() / "data.json"
            self._transport_call("get", locator, target, size)
            return read_json(target, maximum), hash_file(target)

    def _catalog(self, *, mutation=False, recover_policy=False, allow_policy_transition=False):
        with self.locked():
            if self._catalog_working is not None:
                raise EvidenceError("independent catalog cannot reenter an active catalog working scope")
            if not (self._working_depth or self._working_reservation is not None or recover_policy or allow_policy_transition):
                with self._catalog_working_scope():
                    return self._catalog_locked(mutation=mutation, recover_policy=recover_policy, allow_policy_transition=allow_policy_transition)
            return self._catalog_locked(mutation=mutation, recover_policy=recover_policy, allow_policy_transition=allow_policy_transition)

    def _catalog_inventory(self, prefix):
        # Reuse only this fresh listing's object identity, never its sizes for
        # admission. Older transports keep their existing string-key contract.
        method = "inventory" if callable(getattr(self.transport, "inventory", None)) else "keys"
        return self._transport_call(method, prefix)

    def _catalog_locked(self, *, mutation=False, recover_policy=False, allow_policy_transition=False):
        roots = self._catalog_inventory(self.prefix + "roots/")
        authorities = self._catalog_inventory(self.prefix + "authority/")
        authority_bytes = sum(self._transport_call("stat", item)["size"] for item in authorities)
        authority = self._generation_authority(authorities) if authorities else None
        if mutation and authority is not None and authority["coordinator"] != self.coordinator:
            raise EvidenceError("this client lacks designated coordinator authority; cold recovery is read-only")
        if len(roots) + len(authorities) > self.limits["metadata_stop_files"] or authority_bytes > self.limits["metadata_stop_bytes"]:
            raise EvidenceError("combined catalog object count exhausted")
        if not roots:
            if mutation and LINEAGE_FIELD in self.policy and not allow_policy_transition:
                raise EvidenceError("policy lineage is not committed; finish explicit evidence setup first")
            return {"version": 1, "project_id": self.policy["project_id"], "store_id": self.policy["store_id"],
                    "sequence": 0, "coordinator": authority["coordinator"] if authority else self.coordinator, "segments": [], "refs": {}, "packs": {},
                    "generation": {}, "generation_intents": {}, "generation_quarantines": {}, "generation_quarantine_device_witnesses": {}, "generation_quarantine_device_bindings": {}, "reference_aliases": {}, "import_retention_decisions": {}, "root_key": None, "metadata_bytes": authority_bytes, "metadata_files": len(authorities), "unreconciled_packs": self._unreconciled_packs({})}
        keys = sorted((x if isinstance(x, str) else x["key"]) for x in roots)
        latest = keys[-1]
        latest_locator = next(item for item in roots if (item if isinstance(item, str) else item["key"]) == latest)
        root, (digest, size) = self._read_remote_json(latest_locator, self.limits["metadata_stop_bytes"])
        if latest != self.prefix + "roots/" + str(root.get("sequence", 0)).zfill(12) + "-" + digest + ".json":
            raise EvidenceError("catalog root identity/hash mismatch")
        if root.get("version") != 1 or root.get("project_id") != self.policy["project_id"] or root.get("store_id") != self.policy["store_id"]:
            raise EvidenceError("unsupported or mismatched remote catalog")
        if authority is not None and root.get("coordinator") != authority["coordinator"]:
            raise EvidenceError("catalog and generation coordinator authority disagree; reconciliation required")
        if recover_policy:
            if "policy" not in root:
                raise EvidenceError("cold recovery requires original portable --policy for a legacy catalog")
            recovered = validate_policy(root["policy"])
            if (recovered["project_id"], recovered["store_id"], recovered["provider"]) != (self.policy["project_id"], self.policy["store_id"], self.policy["provider"]):
                raise EvidenceError("recovered policy disagrees with selected storage identity")
            self.policy, self.limits = recovered, recovered["limits"]
        if mutation and root.get("coordinator") != self.coordinator:
            raise EvidenceError("this clone has incomplete coordinator authority; cold recovery is read-only; explicitly transfer coordinator authority before mutation/pruning")
        if mutation and (LINEAGE_FIELD in self.policy or isinstance(root.get("policy"), dict) and LINEAGE_FIELD in root["policy"]):
            head = validate_policy(root.get("policy"))
            if head != self.policy:
                if not allow_policy_transition:
                    raise EvidenceError("portable policy differs from committed lineage head; finish explicit evidence setup before mutation")
                self._require_policy_successor(head)

        if not isinstance(root.get("segments"), list) or len(root["segments"]) > self.limits["metadata_stop_files"]:
            raise EvidenceError("invalid catalog segment closure")
        # All published roots are retained by this format; there is no root
        # compaction authority. Verify their append-only ancestry so a later
        # valid hash cannot erase an older witness by omitting its segment.
        total, previous_key, previous_segments, sequence = authority_bytes, None, [], 0
        for locator in sorted(roots, key=lambda item: item if isinstance(item, str) else item['key']):
            key = locator if isinstance(locator, str) else locator['key']
            historical, (root_sha, root_size) = ((root, (digest, size)) if key == latest
                                                else self._read_remote_json(locator, self.limits['metadata_stop_bytes']))
            total += root_size
            if total > self.limits['metadata_stop_bytes']:
                raise EvidenceError('catalog root ancestry exceeds metadata allowance')
            if (not isinstance(historical, dict) or type(historical.get('sequence')) is not int
                    or historical['sequence'] != sequence + 1 or historical.get('version') != 1
                    or historical.get('project_id') != self.policy['project_id'] or historical.get('store_id') != self.policy['store_id']
                    or key != self.prefix + 'roots/' + str(historical['sequence']).zfill(12) + '-' + root_sha + '.json'
                    or historical.get('previous') != previous_key or not isinstance(historical.get('segments'), list)
                    or len(historical['segments']) > self.limits['metadata_stop_files']
                    or historical['segments'][:len(previous_segments)] != previous_segments):
                raise EvidenceError('catalog root ancestry/fork or preserved segment prefix differs')
            previous_key, previous_segments, sequence = key, historical['segments'], historical['sequence']
        indexes = self._catalog_inventory(self.prefix + "indexes/")
        index_locators = {(item if isinstance(item, str) else item["key"]): item for item in indexes}
        index_keys = set(index_locators)
        # Historical root bytes were independently verified above.
        for key in index_keys:
            total += int(self._transport_call("stat", index_locators[key])["size"])
        refs, packs, generation, pending_deletions, retired_refs, import_retention_decisions = {}, {}, {}, {}, {}, {}
        generation_intents, generation_quarantines, reference_aliases = {}, {}, {}
        device_witnesses, device_bindings = {}, {}
        seen = set()
        for descriptor in root["segments"]:
            if descriptor["sha256"] in seen:
                raise EvidenceError("duplicate catalog segment")
            seen.add(descriptor["sha256"])
            if descriptor["locator"]["key"] not in index_keys:
                raise EvidenceError("catalog index missing from complete immutable index inventory")
            if total > self.limits["metadata_stop_bytes"]:
                raise EvidenceError("combined catalog/history/index byte allowance exhausted")
            data, actual = self._read_remote_json(descriptor["locator"], descriptor["size"])
            if actual != (descriptor["sha256"], descriptor["size"]) or data.get("version") != 1:
                raise EvidenceError("catalog index identity mismatch")
            for ref in data.get("refs", []):
                if ref["artifact_id"] in refs and refs[ref["artifact_id"]] != ref:
                    raise EvidenceError("artifact identity collision in catalog")
                refs[ref["artifact_id"]] = ref
            packs.update(data.get("packs", {}))
            generation.update(data.get("generation", {}))
            for ident, intent in data.get("generation_intents", {}).items():
                if (not isinstance(ident, str) or not isinstance(intent, dict)
                        or set(intent) not in ({"run_id", "unit_id", "reserve_bytes", "reserve_files", "owner_pid", "owner_host"},
                                              {"run_id", "unit_id", "reserve_bytes", "reserve_files", "owner_pid", "owner_host", "owner_identity"})
                        or any(not isinstance(intent[field], str) or not intent[field] for field in ("run_id", "unit_id"))
                        or any(type(intent[field]) is not int or intent[field] < 0 for field in ("reserve_bytes", "reserve_files"))
                        or type(intent["owner_pid"]) is not int or intent["owner_pid"] <= 0
                        or not isinstance(intent["owner_host"], str) or not intent["owner_host"]
                        or ident in generation_intents):
                    raise EvidenceError("invalid or duplicated durable generation intent")
                if "owner_identity" in intent:
                    owner = intent["owner_identity"]
                    if (not process_identity.valid_identity(owner) or owner.get("pid") != intent["owner_pid"]
                            or owner.get("host") != intent["owner_host"]):
                        raise EvidenceError("durable generation intent process identity differs from its owner")
                generation_intents[ident] = intent
            for ident in data.get("settled_generation_intents", []):
                if ident not in generation_intents:
                    raise EvidenceError("durable generation settlement lacks its original intent")
                generation_intents[ident] = {**generation_intents[ident], "settled": True}
            quarantine_records = data.get("generation_quarantines", {})
            if not isinstance(quarantine_records, dict):
                raise EvidenceError("invalid durable generation quarantine index")
            for ident, value in quarantine_records.items():
                self._validate_generation_quarantine(ident, value, generation_intents)
                if ident in generation_quarantines and generation_quarantines[ident] != value:
                    raise EvidenceError("immutable generation quarantine changed")
                if any(other != ident and (prior["attempt_id"] == value["attempt_id"]
                       or prior["intent_id"] == value["intent_id"])
                       for other, prior in generation_quarantines.items()):
                    raise EvidenceError("generation quarantine replays another binding")
                generation_quarantines[ident] = value
            device_records = data.get('generation_quarantine_device_witnesses', {})
            if not isinstance(device_records, dict):
                raise EvidenceError('invalid custody publication map')
            from .quarantine_device import validate_quarantine_device_witness
            for ident, value in device_records.items():
                original = next((q for q in generation_quarantines.values() if q['digest'] == ident), None)
                if original is None:
                    raise EvidenceError('published custody witness lacks original quarantine')
                validate_quarantine_device_witness(value, original, self.policy)
                if ident in device_witnesses and device_witnesses[ident] != value:
                    raise EvidenceError('immutable published custody witness changed')
                if any(other != ident and any(prior[k] == value[k] for k in ('attempt_id', 'reservation_id', 'operation_id'))
                       for other, prior in device_witnesses.items()):
                    raise EvidenceError('published custody witness replays another binding')
                device_witnesses[ident] = value
                device_bindings.setdefault(ident, {'root_key': latest, 'sequence': root['sequence'],
                    'segment_sha256': descriptor['sha256'], 'witness_digest': value['digest']})
            for ident, aliases in data.get("reference_aliases", {}).items():
                if ident not in refs or not isinstance(aliases, list) or len(aliases) > 10000:
                    raise EvidenceError("imported reference aliases lack registered original identity")
                target = reference_aliases.setdefault(ident, [])
                for alias in aliases:
                    if not same_imported_original(alias, refs[ident]):
                        raise EvidenceError("imported reference alias changes original evidence")
                    if not any(same_reference(alias, prior) for prior in target):
                        target.append(alias)
            for ident in data.get("deletion_intent", []):
                if ident not in packs:
                    raise EvidenceError("deletion intent lacks registered archive identity")
                pending_deletions[ident] = packs[ident]
            for ident in data.get("retired", []):
                removed = refs.pop(ident, None)
                if removed is not None:
                    retired_refs[ident] = removed
            for ident in data.get("deleted_packs", []):
                packs.pop(ident, None)
                pending_deletions.pop(ident, None)
            for ref in data.get("updated_refs", []):
                ident = ref.get("artifact_id")
                original = refs.get(ident)
                if (original is None or original.get("retention", {}).get("imported") is not True
                        or ref.get("retention", {}).get("migration_policy_established") is not True
                        or not same_reference(original, ref)):
                    raise EvidenceError("legacy retention update must preserve a registered imported reference")
                # Older v1 writers placed administrative decisions inside refs.
                # Preserve their original immutable records and no invented time.
                import_retention_decisions.setdefault(ident, {"version": 1, "legacy": True})
            decisions = data.get("import_retention_decisions", {})
            if not isinstance(decisions, dict):
                raise EvidenceError("unsupported imported retention decision index")
            for ident, decision in decisions.items():
                if (ident not in refs or refs[ident].get("retention", {}).get("imported") is not True
                        or not isinstance(decision, dict) or type(decision.get("version")) is not int
                        or decision["version"] != 1):
                    raise EvidenceError("retention decision lacks a registered imported artifact")
                if set(decision) != {"version", "policy_sha256", "provider", "days", "decided_at"}:
                    raise EvidenceError("unsupported imported retention decision fields")
                digest = decision["policy_sha256"]
                days = decision["days"]
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(char not in "0123456789abcdef" for char in digest)
                        or decision["provider"] not in ("local", "folder", "google-drive")
                        or days is None and decision["provider"] != "google-drive"
                        or days is not None and (type(days) is not int or days <= 0)):
                    raise EvidenceError("invalid imported retention policy binding")
                timestamp(decision["decided_at"])
                if ident in import_retention_decisions and import_retention_decisions[ident] != decision:
                    raise EvidenceError("conflicting imported retention decisions")
                import_retention_decisions[ident] = decision
        if len(keys) + len(index_keys) + len(authorities) > self.limits["metadata_stop_files"] or total > self.limits["metadata_stop_bytes"]:
            raise EvidenceError("combined metadata allowance exhausted")
        for ident, value in generation_quarantines.items():
            self._validate_generation_quarantine(ident, value, generation_intents)
        root.update(refs=refs, packs=packs, unreconciled_packs=self._unreconciled_packs(packs), generation=generation, generation_intents=generation_intents, generation_quarantines=generation_quarantines, reference_aliases=reference_aliases, pending_deletions=pending_deletions, retired_refs=retired_refs, import_retention_decisions=import_retention_decisions, root_key=latest,
                    generation_quarantine_device_witnesses=device_witnesses, generation_quarantine_device_bindings=device_bindings,
                    metadata_bytes=total, metadata_files=len(keys) + len(index_keys) + len(authorities))
        from .accounting import Accounting
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            self._audit_source_payloads()
            ledger.reconcile_metadata("remote-catalog", total, len(keys) + len(index_keys) + len(authorities))
        return root

    def _unreconciled_packs(self, packs):
        registered = {pack["locator"].get("key") for pack in packs.values()}
        unknown = {}
        for entry in self._transport_call("keys", self.prefix + "packs/"):
            key = entry if isinstance(entry, str) else entry["key"]
            if key not in registered:
                metadata = self._transport_call("stat", key)
                unknown[metadata["object_id"]] = metadata
        return unknown

    def _reconcile_ledger(self, catalog, ledger):
        # Remote records are authoritative after cold recovery; local deletion never resets charges.
        existing = {row[0] for row in ledger.connection.execute("SELECT identity FROM objects")}
        unique = self._retained_content(catalog["packs"])
        for digest, size in unique.items():
            ledger.record_object("content:" + digest, size, physical_count=0)
        for digest in catalog["packs"]:
            ledger.record_object("pack:" + digest, 0, physical_count=1)
        # Unknown-outcome/orphan transfers occupy the store even before root publication.
        # Encoded size is a conservative allowance charge; it is not an original-byte claim.
        for ident, metadata in catalog.get("unreconciled_packs", {}).items():
            ledger.record_object("unreconciled-pack:" + ident, metadata["size"], physical_count=1)
        active = {"content:" + k for k in unique} | {"pack:" + k for k in catalog["packs"]} | {"unreconciled-pack:" + k for k in catalog.get("unreconciled_packs", {})}
        for ident in existing - active:
            ledger.remove_object(ident)
        self._audit_source_payloads()
        ledger.reconcile_metadata("remote-catalog", catalog["metadata_bytes"], catalog["metadata_files"])
        records = self._metadata_records(include_checkpoints=False)
        self._audit_source_payloads()
        ledger.reconcile_metadata("local-journals-receipts", self._existing_bytes(p for p in records), len(records))
        cache_bytes, working_bytes, checkpoint_bytes = self._local_occupancy()
        self._checkpoint_allocations(ledger, actual_bytes=checkpoint_bytes)
        ledger.reconcile_local("cache", cache_bytes, "cache")
        ledger.reconcile_local("manager-working", working_bytes, "staging")
        ledger.reconcile_quarantines(catalog.get("generation_quarantines", {}))
        ledger.reconcile_generation(catalog["generation"])

    @staticmethod
    def _retained_content(packs):
        """Every stored member occupies allowance until its pack is verified absent."""
        unique = {}
        for pack in packs.values():
            for member in pack["members"]:
                digest, size = member["sha256"], member["size"]
                if digest in unique and unique[digest] != size:
                    raise EvidenceError("stored original content identity has conflicting sizes")
                unique[digest] = size
        return unique

    def _put_json(self, key_prefix, value):
        data = canonical(value)
        digest = hashlib.sha256(data).hexdigest()
        self._capacity(len(data) * 2)
        with self._working(len(data) * 2, metadata_bytes=len(data), metadata_files=1), tempfile.TemporaryDirectory(dir=self.staging, prefix="publish-") as temp:
            temp = Path(temp).resolve()
            target = temp / "record.json"
            target.write_bytes(data)
            locator = self._transport_call("put", key_prefix + digest + ".json", target)
            readback = temp / "readback.json"
            self._transport_call("get", locator, readback, len(data))
            if hash_file(readback) != (digest, len(data)):
                raise EvidenceError("catalog independent readback corrupt")
        return {"locator": locator, "sha256": digest, "size": len(data)}

    def _publish(self, catalog, segment, *, allow_policy_transition=False):
        head = catalog.get("policy")
        if LINEAGE_FIELD in self.policy or isinstance(head, dict) and LINEAGE_FIELD in head:
            current = validate_policy(self.policy)
            if head is None:
                if not allow_policy_transition or catalog["sequence"] != 0 or len(current[LINEAGE_FIELD]["steps"]) != 1:
                    raise EvidenceError("uncommitted policy lineage requires explicit setup publication")
            elif validate_policy(head) != current:
                if not allow_policy_transition:
                    raise EvidenceError("publication policy differs from committed lineage head")
                self._require_policy_successor(validate_policy(head))
        segment_bytes = len(canonical(segment))
        segments = catalog["segments"] + [{"sha256": "0" * 64, "size": segment_bytes, "locator": {"object_id": "pending", "key": "pending", "size": segment_bytes}}]
        root = {"version": 1, "project_id": self.policy["project_id"], "store_id": self.policy["store_id"], "policy": self.policy,
                "sequence": catalog["sequence"] + 1, "coordinator": self.coordinator,
                "previous": catalog["root_key"], "segments": segments}
        # Allow locator length variation, then check exact serialized bytes before root upload.
        local_records = self._metadata_records()
        local_metadata = self._existing_bytes(p for p in local_records)
        db_metadata = self._existing_bytes(p for p in self.state.glob("accounting.sqlite*") if p.is_file())
        db_metadata += self._existing_bytes(p for p in (self.state / "accounting.sqlite.recovery").rglob("*") if p.is_file())
        if catalog["metadata_bytes"] + local_metadata + db_metadata + segment_bytes + len(canonical(root)) + 4096 > self.limits["metadata_stop_bytes"] or catalog["metadata_files"] + len(local_records) + 2 > self.limits["metadata_stop_files"]:
            raise EvidenceError("combined metadata/index/history budget would be exceeded")
        roots = self._transport_call("keys", self.prefix + "roots/")
        current = max((x if isinstance(x, str) else x["key"] for x in roots), default=None)
        if current != catalog["root_key"]:
            raise EvidenceError("catalog changed on another client; mutation stopped")
        descriptor = self._put_json(self.prefix + "indexes/", segment)
        root["segments"][-1] = descriptor
        root_size = len(canonical(root))
        local_records = self._metadata_records()
        db_metadata = self._existing_bytes(p for p in self.state.glob("accounting.sqlite*") if p.is_file())
        db_metadata += self._existing_bytes(p for p in (self.state / "accounting.sqlite.recovery").rglob("*") if p.is_file())
        if catalog["metadata_bytes"] + descriptor["size"] + root_size + self._existing_bytes(p for p in local_records) + db_metadata > self.limits["metadata_stop_bytes"] or catalog["metadata_files"] + len(local_records) + 2 > self.limits["metadata_stop_files"]:
            raise EvidenceError("exact combined catalog metadata allowance exhausted; verified index is recoverable")
        from .accounting import Accounting
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            self._audit_source_payloads()
            ledger.reconcile_metadata("remote-catalog", catalog["metadata_bytes"] + descriptor["size"], catalog["metadata_files"] + 1)
        self._put_json(self.prefix + "roots/" + str(root["sequence"]).zfill(12) + "-", root)
        return root

    def _pack(self, items, checkpoint):
        maximum = self.limits["archive_pack_stop_bytes"]
        peak = (sum(i["size"] for i in items) + len(items) * 2048 + 65536) * 2 + local_json_size(checkpoint) * 2
        self._capacity(peak, migration=checkpoint["migration"])
        with self._working(peak, migration=checkpoint["migration"], metadata_bytes=local_json_size(checkpoint) * 2 + len(items) * 4096 + 65536, metadata_files=3), tempfile.TemporaryDirectory(dir=self.staging, prefix="pack-") as temp:
            temp = Path(temp).resolve()
            pack = build_pack(items, temp / "pack.zip", maximum, self.limits["migration_batch_stop_files"])
            # Persist expected immutable identity before upload; transport owns unknown-outcome recovery.
            checkpoint["pending_pack"] = {k: v for k, v in pack.items()}
            self._checkpoint(Path(checkpoint["path"]), checkpoint)
            locator = self._transport_call("put", self.prefix + "packs/" + pack["sha256"] + ".zip", temp / "pack.zip")
            readback = temp / "readback.zip"
            self._transport_call("get", locator, readback, pack["size"])
            verified = verify_pack(readback, pack["sha256"], pack["size"], pack["members"],
                                   max_bytes=maximum, max_files=self.limits["migration_batch_stop_files"],
                                   max_decoder_memory_bytes=self.limits.get("archive_decoder_memory_bytes", 128 * 1024 * 1024))
            verified["locator"] = locator
            checkpoint["packs"][pack["sha256"]] = verified
            checkpoint.pop("pending_pack", None)
            self._checkpoint(Path(checkpoint["path"]), checkpoint)
            return verified

    def _reference(self, item, locator):
        timestamp(item["sealed_at"])
        provenance = deepcopy(item.get("provenance", {}))
        if not provenance.get("run_id") or not provenance.get("unit_id"):
            raise EvidenceError("evidence requires stable run_id and unit_id provenance")
        original = item.get("original_path", Path(item.get("path", "observation")).name)
        safe_relative(original)
        identity = {"project_id": self.policy["project_id"], "provenance": provenance,
                    "kind": item.get("kind", "observation"), "schema": item.get("schema", "evidence-bytes-v1"),
                    "original_path": original, "sha256": item["sha256"], "bindings": item.get("bindings", {})}
        return {"version": 1, "artifact_id": hashlib.sha256(canonical(identity)).hexdigest(),
                "sha256": item["sha256"], "size": item["size"], "kind": item.get("kind", "observation"),
                "schema": item.get("schema", "evidence-bytes-v1"), "provenance": provenance,
                "bindings": deepcopy(item.get("bindings", {})), "original_path": original,
                "locator": {"store_id": self.policy["store_id"], "provider": self.policy["provider"], **locator},
                "retention": {"sealed_at": item["sealed_at"], "class": item.get("retention_class", "diagnostic"),
                              "protections": item.get("protections", [])},
                **({"dependencies": item["dependencies"]} if item.get("dependencies") else {})}

    def _small_packs(self, logical, checkpoint, known):
        """Batch many small originals into packs; pack size never limits total migration."""
        locations, group, group_bytes, seen = {}, [], 0, set()
        def flush():
            nonlocal group, group_bytes
            if not group:
                return
            peak = group_bytes * 3 + len(group) * 4096 + 131072 + local_json_size(checkpoint) * 2
            self._capacity(peak, migration=checkpoint["migration"])
            with self._working(peak, migration=checkpoint["migration"]), tempfile.TemporaryDirectory(dir=self.staging, prefix="capture-batch-") as temp:
                temp = Path(temp).resolve()
                captured = []
                for entry in group:
                    path = temp / entry["sha256"]
                    capture(entry["path"], path, entry["size"])
                    captured.append({"path": path, "sha256": entry["sha256"], "size": entry["size"]})
                pack = self._pack(captured, checkpoint)
                for item in pack["members"]:
                    locations[item["sha256"]] = {"object_id": pack["locator"]["object_id"], "key": pack["locator"]["key"],
                        "pack_sha256": pack["sha256"], "pack_size": pack["size"], "member": item["member"],
                        "sha256": item["sha256"], "offset": 0, "length": item["size"]}
            group, group_bytes = [], 0
        for entry in logical[checkpoint["next_file"]:]:
            digest = entry["sha256"]
            if digest in known or digest in seen or entry["size"] > self.limits["archive_pack_target_bytes"]:
                continue
            seen.add(digest)
            prior = next((p for p in checkpoint["packs"].values() if any(m["sha256"] == digest and m["size"] == entry["size"] for m in p["members"])), None)
            if prior:
                member = next(m for m in prior["members"] if m["sha256"] == digest)
                locations[digest] = {"object_id": prior["locator"]["object_id"], "key": prior["locator"]["key"],
                    "pack_sha256": prior["sha256"], "pack_size": prior["size"], "member": member["member"]}
                continue
            if group and (group_bytes + entry["size"] > self.limits["archive_pack_target_bytes"] or len(group) >= self.limits["migration_batch_stop_files"]):
                flush()
            group.append(entry)
            group_bytes += entry["size"]
        flush()
        return locations

    def archive(self, specification, *, migration=False, remove_local=False):
        try:
            return self._archive(specification, migration=migration, remove_local=remove_local)
        finally:
            ledger = getattr(self, "_archive_ledger", None)
            if ledger is not None:
                ledger.close()
                del self._archive_ledger
            self._active_reservation = None

    def _archive(self, specification, *, migration=False, remove_local=False):
        """Bounded batches, immutable packs. Copying never changes observation timestamps."""
        if specification.get("version") != 1 or not isinstance(specification.get("files"), list):
            raise EvidenceError("archive specification requires version 1 files")
        from .accounting import Accounting
        with self.locked():
            catalog = self._catalog(mutation=True)
            operation = hashlib.sha256(canonical(specification)).hexdigest()
            journal = self.state / ("archive-" + operation + ".json")
            checkpoint = read_json(journal, self.limits["metadata_stop_bytes"]) if journal.exists() else {
                "version": 1, "path": str(journal), "migration": migration, "packs": {}, "refs": [], "next_file": 0,
                "status": "capturing"}
            if checkpoint["migration"] != migration:
                raise EvidenceError("resume cannot change accounting mode")
            files = specification["files"]
            if checkpoint.get("status") == "complete":
                inventory = checkpoint.get("inventory", [])
                if len(inventory) != len(files):
                    raise EvidenceError("completed archive inventory is incomplete")
                deletion = journal.with_suffix(".deletion.json")
                removed = read_json(deletion, self.limits["metadata_stop_bytes"])["entries"] if deletion.exists() else []
                for entry, recorded in zip(files, inventory):
                    path = Path(entry["path"])
                    if str(path) != recorded["path"]:
                        raise EvidenceError("completed archive source association changed")
                    if path.exists() or path.is_symlink():
                        if hash_file(path) != (recorded["sha256"], recorded["size"]):
                            raise EvidenceError("archive resume input inventory changed")
                    elif not any(x == {**recorded, "done": True} for x in removed):
                        raise EvidenceError("completed archive original is missing without verified deletion intent")
                self.prepare(checkpoint["refs"])
                if remove_local:
                    self._remove_captured(inventory, checkpoint["refs"], journal)
                return checkpoint["refs"]
            logical = []
            for entry in files:
                path = Path(entry["path"])
                digest, size = hash_file(path)
                logical.append({**entry, "sha256": digest, "size": size})
                timestamp(entry["sealed_at"])
            gross = sum(x["size"] for x in logical)
            inventory = [{"path": str(x["path"]), "sha256": x["sha256"], "size": x["size"]} for x in logical]
            if "inventory" in checkpoint and checkpoint["inventory"] != inventory:
                raise EvidenceError("archive resume input inventory changed; old references cannot cover or delete new bytes")
            checkpoint["inventory"] = inventory
            if not migration:
                if len({x["provenance"]["unit_id"] for x in logical}) > 1 or len({x["provenance"]["run_id"] for x in logical}) > 1:
                    raise EvidenceError("one managed archive operation must belong to one stable run and unit")
            ledger = Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy)
            self._archive_ledger = ledger
            self._reconcile_ledger(catalog, ledger)
            if not specification.get("managed_output_id"):
                local = ledger.reconcile_local("source:" + operation, gross, "capture")
                if not migration and local["violations"]:
                    raise EvidenceError("registered source occupancy exceeds aggregate limits: " + "; ".join(local["violations"]))
            recorded_generation = catalog["generation"].get(operation)
            already_accounted = recorded_generation is not None
            if already_accounted and logical:
                if recorded_generation.get("inventory_sha256") != hashlib.sha256(canonical(inventory)).hexdigest():
                    raise EvidenceError("archived operation content inventory changed or lacks an immutable binding")
                if (recorded_generation["gross_bytes"], recorded_generation["logical_files"], recorded_generation["run_id"], recorded_generation["unit_id"]) != (gross, len(logical), logical[0]["provenance"]["run_id"], logical[0]["provenance"]["unit_id"]):
                    raise EvidenceError("archived operation cannot be rebound to different generation")
            managed = specification.get("managed_output_id")
            if managed:
                row = ledger.connection.execute("SELECT o.*,r.unit_id,r.status FROM outputs o JOIN runs r ON r.id=o.run_id WHERE o.id=?", (managed,)).fetchone()
                if row is None or not row["reconciled"] or row["status"] != "complete":
                    raise EvidenceError("managed evidence lacks settled, reconciled producer accounting")
                observations = {r["path"]: r for r in ledger.connection.execute("SELECT * FROM observations WHERE output_id=?", (managed,))}
                for item in logical:
                    try:
                        name = Path(item["path"]).relative_to(Path(row["path"])).as_posix()
                    except ValueError as error:
                        raise EvidenceError("archive source is outside its registered producer output") from error
                    item.setdefault("original_path", name)
                    observed = observations.get(name)
                    if observed is None or (observed["digest"], observed["bytes"], row["run_id"], row["unit_id"]) != (item["sha256"], item["size"], item["provenance"]["run_id"], item["provenance"]["unit_id"]):
                        raise EvidenceError("managed output changed or has different execution provenance")
            associations = [self._reference(item, {"object_id": "identity-only"})["artifact_id"] for item in logical]
            if len(set(associations)) != len(associations):
                raise EvidenceError("duplicate logical evidence identity; supply distinct relative original_path or original check provenance")
            if "reservation" not in checkpoint and logical and not migration and not managed and not already_accounted:
                first = logical[0]["provenance"]
                new_content = {i["sha256"]: i for i in logical if not any(r["sha256"] == i["sha256"] for r in catalog["refs"].values())}
                target = self.limits["archive_pack_target_bytes"]
                upper_packs = sum((item["size"] + target - 1) // target for item in new_content.values() if item["size"] > target)
                small_bytes = sum(item["size"] for item in new_content.values() if item["size"] <= target)
                # Byte grouping and count grouping can each force a boundary.
                small_files = sum(1 for item in new_content.values() if item["size"] <= target)
                upper_packs += (small_bytes + target - 1) // target + (small_files + self.limits["migration_batch_stop_files"] - 1) // self.limits["migration_batch_stop_files"]
                checkpoint["reservation"] = ledger.reserve(first["run_id"], first["unit_id"], gross, len(logical),
                                                          local_bytes=min(gross, self.limits["archive_pack_target_bytes"]) * 3,
                                                          retry=bool(specification.get("retry")),
                                                          retained_bytes=sum(x["size"] for x in new_content.values()), retained_objects=upper_packs)
                self._checkpoint(journal, checkpoint)
            if migration and logical and "reservation" not in checkpoint:
                checkpoint["reservation"] = ledger.reserve("migration:" + operation, "migration", gross, len(logical),
                    local_bytes=min(gross, self.limits["archive_pack_target_bytes"]) * 3, migration=True)
                self._checkpoint(journal, checkpoint)
            self._active_reservation = checkpoint.get("reservation")
            if checkpoint.get("status") == "complete":
                self.prepare(checkpoint["refs"])
                if remove_local:
                    self._remove_captured(logical, checkpoint["refs"], journal)
                return checkpoint["refs"]
            # Deduplicate contents, preserving every logical path/check association.
            existing = {}
            for ref in catalog["refs"].values():
                existing.setdefault(ref["sha256"], ref["locator"])
            # Verify reused bytes under their new logical interpretation. A prior
            # failed schema/dependency association must not prevent a corrected
            # reference from reusing the same intact immutable original.
            reuse = {entry["sha256"] for entry in logical} & set(existing)
            if reuse:
                proposed = [self._reference(entry, existing[entry["sha256"]])
                            for entry in logical if entry["sha256"] in reuse]
                for reference in proposed:
                    prior = catalog["refs"].get(reference["artifact_id"])
                    if prior is not None and not same_reference(prior, reference):
                        raise EvidenceError("archive artifact identity conflicts with an existing logical record")
                prospective = {**catalog, "refs": {**catalog["refs"],
                    **{reference["artifact_id"]: reference for reference in proposed}}}
                self.prepare(proposed, catalog=prospective)
            for ref in checkpoint["refs"]:
                existing.setdefault(ref["sha256"], ref["locator"])
            small = self._small_packs(logical, checkpoint, existing)
            all_packs = {**catalog["packs"], **checkpoint["packs"]}
            for index in range(checkpoint["next_file"], len(logical)):
                entry = logical[index]
                if entry["sha256"] in existing:
                    reference = self._reference(entry, existing[entry["sha256"]])
                elif entry["sha256"] in small:
                    reference = self._reference(entry, small[entry["sha256"]])
                    existing[entry["sha256"]] = reference["locator"]
                else:
                    segments = []
                    target_size = self.limits["archive_pack_target_bytes"]
                    # Large original files are streamed into bounded packs, never capped by pack size.
                    source = Path(entry["path"])
                    source, descriptor, before = _open_regular(source)
                    try:
                        with os.fdopen(descriptor, "rb", closefd=False) as stream:
                            offset, digest = 0, hashlib.sha256()
                            while offset < entry["size"] or (entry["size"] == 0 and not segments):
                                length = min(target_size, entry["size"] - offset)
                                peak = length * 3 + 139264 + local_json_size(checkpoint) * 2
                                self._capacity(peak, migration=migration)
                                with self._working(peak, migration=migration), tempfile.TemporaryDirectory(dir=self.staging, prefix="capture-") as temp:
                                    part = Path(temp).resolve() / "part"
                                    part_hash = hashlib.sha256()
                                    count = 0
                                    with part.open("xb") as output:
                                        while count < length:
                                            block = stream.read(min(1024 * 1024, length - count))
                                            if not block:
                                                raise EvidenceError("original input truncated during capture")
                                            output.write(block)
                                            digest.update(block)
                                            part_hash.update(block)
                                            count += len(block)
                                    ph = part_hash.hexdigest()
                                    matching = next((p for p in all_packs.values() if any(m["sha256"] == ph and m["size"] == count for m in p["members"])), None)
                                    packed = matching or self._pack([{"path": part, "sha256": ph, "size": count}], checkpoint)
                                    all_packs[packed["sha256"]] = packed
                                    member = next(m["member"] for m in packed["members"] if m["sha256"] == ph)
                                    segments.append({"object_id": packed["locator"]["object_id"], "key": packed["locator"]["key"],
                                                     "pack_sha256": packed["sha256"], "pack_size": packed["size"],
                                                     "member": member, "offset": offset, "length": count, "sha256": ph})
                                    offset += count
                                    if count == 0:
                                        break
                            if stream.read(1) or digest.hexdigest() != entry["sha256"]:
                                raise EvidenceError("original input changed during capture")
                        _verify_stable(source, descriptor, before)
                        if hash_file(source) != (entry["sha256"], entry["size"]):
                            raise EvidenceError("original input changed during capture")
                    finally:
                        os.close(descriptor)
                    loc = segments[0] if len(segments) == 1 else {"object_id": segments[0]["object_id"], "segments": segments}
                    reference = self._reference(entry, loc)
                    existing[entry["sha256"]] = reference["locator"]
                checkpoint["refs"].append(reference)
                checkpoint["next_file"] = index + 1
                self._checkpoint(journal, checkpoint)
            new_refs = [r for r in checkpoint["refs"] if r["artifact_id"] not in catalog["refs"]]
            new_packs = {k: v for k, v in checkpoint["packs"].items() if k not in catalog["packs"]}
            retained = self._retained_content({**catalog["packs"], **new_packs})
            if not migration and (sum(retained.values()) > self.limits["retained_stop_bytes"] or len(catalog["packs"]) + len(new_packs) > self.limits["retained_stop_objects"]):
                checkpoint["status"] = "incomplete"
                self._checkpoint(journal, checkpoint)
                raise EvidenceError("retained aggregate allowance exhausted; verified transfers checkpointed")
            if checkpoint.get("reservation") and checkpoint.get("status") != "settled":
                reservation = ledger.connection.execute("SELECT state FROM reservations WHERE id=?", (checkpoint["reservation"],)).fetchone()
                if reservation is None:
                    raise EvidenceError("archive resume lost its accounting reservation")
                if reservation[0] == "pending":
                    settled = ledger.settle(checkpoint["reservation"], gross, len(logical), local_bytes=0)
                    if settled["incomplete"]:
                        checkpoint["status"] = "incomplete"
                        self._checkpoint(journal, checkpoint)
                        raise EvidenceError("archive resource settlement incomplete: " + "; ".join(settled["violations"]))
                checkpoint["status"] = "settled"
                self._checkpoint(journal, checkpoint)
            if new_refs or new_packs:
                generation = {} if migration else {operation: {"gross_bytes": gross, "logical_files": len(logical),
                    "run_id": logical[0]["provenance"]["run_id"] if logical else "", "unit_id": logical[0]["provenance"]["unit_id"] if logical else "", "inventory_sha256": hashlib.sha256(canonical(inventory)).hexdigest()}}
                if managed:
                    run = ledger.connection.execute("SELECT * FROM runs WHERE id=?", (logical[0]["provenance"]["run_id"],)).fetchone()
                    generation = self._run_generation(run)
                self._publish(catalog, {"version": 1, "refs": new_refs, "packs": new_packs, "generation": generation})
            self.prepare(checkpoint["refs"])
            if logical and not migration:
                ledger.complete_run(logical[0]["provenance"]["run_id"])
            ledger.close()
            self._active_reservation = None
            checkpoint["status"] = "complete"
            self._checkpoint(journal, checkpoint)
            if remove_local:
                self._remove_captured(logical, checkpoint["refs"], journal)
            return checkpoint["refs"]

    def _remove_captured(self, logical, refs, journal, *, permanent=False):
        # Intent is durable before any unlink. Originals must still match captured bytes.
        intent_path = journal.with_suffix(".deletion.json")
        intent = read_json(intent_path, self.limits["metadata_stop_bytes"]) if intent_path.exists() else {"version": 1, "entries": [
            {"path": str(item["path"]), "sha256": item["sha256"], "size": item["size"], "done": False} for item in logical]}
        atomic_json(intent_path, intent)
        if len(intent["entries"]) != len(refs):
            raise EvidenceError("deletion intent/reference association count mismatch")
        if not permanent:
            self.prepare([ref for entry, ref in zip(intent["entries"], refs) if not entry["done"]], reverify_durable=True)
        for entry, ref in zip(intent["entries"], refs):
            if (entry["sha256"], entry["size"]) != (ref["sha256"], ref["size"]):
                raise EvidenceError("deletion intent does not identify the verified original bytes")
            if entry["done"]:
                continue
            # All pending durable copies were reverified before removal.
            path = Path(entry["path"])
            if path.exists() or path.is_symlink():
                if hash_file(path) != (entry["sha256"], entry["size"]):
                    raise EvidenceError("cleanup original changed; retained: " + str(path))
                path.unlink()
            if path.exists() or path.is_symlink():
                raise EvidenceError("cleanup deletion failed: " + str(path))
            entry["done"] = True
            atomic_json(intent_path, intent)
        from .accounting import Accounting
        checkpoint = read_json(journal, self.limits["metadata_stop_bytes"])
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            if checkpoint.get("reservation"):
                ledger.reconcile_local("settled:" + checkpoint["reservation"], 0)
            if journal.name.startswith("archive-"):
                ledger.reconcile_local("source:" + journal.stem.removeprefix("archive-"), 0)

    def prepare(self, refs, *, catalog=None, reverify_durable=False):
        """Serialize cache mutation; reuse freshly verified objects without replacement.

        Deletion callers explicitly retain independent durable payload readback.
        Ordinary reuse still checks current catalog, closure and remote identity.
        """
        with self.locked():
            self._session_pack = None
            try:
                with tempfile.TemporaryDirectory(dir=self.staging, prefix="verified-pack-") as temp:
                    self._session_path = Path(temp).resolve()
                    return self._prepare(refs, catalog=catalog, reverify_durable=reverify_durable)
            finally:
                self._preparing.clear()
                self._session_pack = None
                from .accounting import Accounting
                with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
                    self._local_records(ledger)

    @staticmethod
    def _cache_object_info(target):
        try:
            info = target.lstat()
        except FileNotFoundError:
            return None
        if _is_link(info):
            raise EvidenceError("linked cache object")
        if not stat.S_ISREG(info.st_mode):
            raise EvidenceError("special file in evidence cache object")
        return info

    def _missing_object_aliases(self, target):
        # Source views retain a digest-named blob as well as their logical links.
        # Even a malformed/unregistered digest-named file is retained, never
        # interpreted as authority to rebuild or delete a source view.
        return [path for path in self._workspace_records(self.cache)
            if path != target and path.name == target.name]

    def _prepared_cache_resolver(self, ref, supplied, catalog, *, reverify_durable):
        from .resolver import EvidenceResolver, payload_references, JSON_LIMIT
        target = self.cache / "objects" / ref["sha256"]
        if ref["schema"] not in ("evidence-bytes-v1", "archive-attachment-v1"):
            try:
                if hash_file(target) != (ref["sha256"], ref["size"]):
                    return None, "prepared original bytes hash/size mismatch"
                nested = list(payload_references(read_json(target, min(JSON_LIMIT,
                    self.limits["metadata_stop_bytes"])), ref["schema"]))
            except ValueError as error:
                return None, str(error)
            for dependency in nested:
                self._prepare([dependency], catalog=catalog, reverify_durable=reverify_durable)
        try:
            # A new resolver hashes current bytes and validates ordinary receipt,
            # exact reference/bindings, verified archive and dependency closure.
            resolver = EvidenceResolver(self.cache)
            resolver.resolve(ref)
            resolver.resolve(supplied)
            return resolver, None
        except ValueError as error:
            return None, str(error)

    @staticmethod
    def _shared_rebuild_required(target, problem):
        raise EvidenceError("cache object has retained source aliases; explicit source-view rebuild required before replacement: "
            + str(target) + "; " + str(problem))

    def _prepare(self, refs, *, catalog=None, reverify_durable=False):
        """Network and cache writes live here, never in the checker."""
        from .resolver import payload_references, JSON_LIMIT
        catalog = catalog if catalog is not None else self._catalog()
        objects = self.cache / "objects"
        receipts = self.cache / "receipts"
        objects.mkdir(exist_ok=True)
        receipts.mkdir(exist_ok=True)
        for supplied in refs:
            if supplied["artifact_id"] in self._preparing or len(self._preparing) >= 32:
                raise EvidenceError("cyclic or excessive preparation reference closure")
            self._preparing.add(supplied["artifact_id"])
            ref = catalog["refs"].get(supplied["artifact_id"])
            aliases = catalog.get("reference_aliases", {}).get(supplied["artifact_id"], [])
            matching = ref is not None and (same_reference(ref, supplied) or
                any(same_reference(alias, supplied) for alias in aliases))
            if not matching and ref is not None and catalog.get("_adopting") and same_imported_original(supplied, ref):
                aliases = catalog.setdefault("reference_aliases", {}).setdefault(ref["artifact_id"], [])
                if len(aliases) >= 10000:
                    raise EvidenceError("imported reference aliases exceed validation bounds")
                aliases.append(deepcopy(supplied))
                matching = True
            if not matching:
                raise EvidenceError("reference is missing/mismatched in authoritative durable catalog")
            for dependency in ref.get("dependencies", []):
                self._prepare([dependency], catalog=catalog, reverify_durable=reverify_durable)
            locator = ref["locator"]
            segments = locator.get("segments") or [{**locator, "offset": 0, "length": ref["size"], "sha256": ref["sha256"]}]
            packs = []
            for seg in segments:
                pack = catalog["packs"].get(seg["pack_sha256"])
                if pack is None or pack["locator"]["object_id"] != seg["object_id"] or pack["size"] != seg["pack_size"]:
                    raise EvidenceError("archive object identity closure mismatch")
                packs.append(pack)
            target = objects / ref["sha256"]
            existing = self._cache_object_info(target)
            reusable = None
            if existing is not None:
                reusable, problem = self._prepared_cache_resolver(ref, supplied, catalog,
                    reverify_durable=reverify_durable)
                current = self._cache_object_info(target)
                if reusable is None and (current is not None and current.st_nlink > 1 or
                        self._missing_object_aliases(target)):
                    self._shared_rebuild_required(target, problem)
            elif self._missing_object_aliases(target):
                self._shared_rebuild_required(target, "canonical object is missing while digest-named aliases remain")
            if reusable is not None and not reverify_durable:
                for pack in packs:
                    actual = self._transport_call("stat", pack["locator"])
                    if (actual["object_id"], actual["size"]) != (pack["locator"]["object_id"], pack["size"]):
                        raise EvidenceError("durable archive object identity/size changed before cache reuse")
                self._capacity(0)
                if self._cache_bytes() > self.limits["cache_stop_bytes"]:
                    raise EvidenceError("bounded evidence cache full; explicitly evict replaceable cache bytes")
                # Detect replacement/mutation during current-identity/capacity
                # checks; never refresh an already accepted resolver baseline.
                reusable.resolve(ref)
                reusable.resolve(supplied)
                self._preparing.remove(supplied["artifact_id"])
                continue
            if self._session_pack is not None and any(pack["sha256"] != self._session_pack["sha256"] for pack in packs):
                shutil.rmtree(self._session_path / "members")
                self._session_pack = None
            peak = ref["size"] + max((pack["size"] + pack["original_bytes"] for pack in packs
                if self._session_pack is None or pack["sha256"] != self._session_pack["sha256"]), default=0)
            self._capacity(peak)
            proofs, offset = [], 0
            receipt_peak = 0 if reusable is not None else (local_json_size(ref) + local_json_size(aliases) + len(segments) * 1024 + 4096) * 2
            existing = self._cache_object_info(target)
            if reusable is None and existing is not None and existing.st_nlink > 1:
                self._shared_rebuild_required(target, "aliases appeared before preparation")
            cache_growth = 0 if reusable is not None else max(0, ref["size"] - (existing.st_size if existing else 0)) + receipt_peak
            if self._cache_bytes() + cache_growth > self.limits["cache_stop_bytes"]:
                raise EvidenceError("bounded evidence cache full; explicitly evict replaceable cache bytes")
            with self._working(peak + receipt_peak, metadata_bytes=receipt_peak, metadata_files=0 if (receipts / (ref["artifact_id"] + ".json")).exists() else 1,
                cache_bytes=cache_growth), tempfile.TemporaryDirectory(dir=self.staging, prefix="prepare-") as temp:
                temp = Path(temp).resolve()
                whole = temp / "whole"
                with whole.open("xb") as output:
                    for seg in segments:
                        if seg["offset"] != offset:
                            raise EvidenceError("split-file offsets overlap or have gaps")
                        pack = catalog["packs"].get(seg["pack_sha256"])
                        if pack is None or pack["locator"]["object_id"] != seg["object_id"] or pack["size"] != seg["pack_size"]:
                            raise EvidenceError("archive object identity closure mismatch")
                        archive = self._session_path / "readback.pack"
                        extracted = self._session_path / "members"
                        if self._session_pack is None or self._session_pack["sha256"] != pack["sha256"]:
                            if extracted.exists():
                                shutil.rmtree(extracted)
                            self._session_pack = None
                            self._transport_call("get", pack["locator"], archive, pack["size"])
                            verified = verify_pack(archive, pack["sha256"], pack["size"], pack["members"], destination=extracted,
                                max_bytes=pack["original_bytes"], max_files=self.limits["migration_batch_stop_files"],
                                max_decoder_memory_bytes=self.limits.get("archive_decoder_memory_bytes", 128 * 1024 * 1024))
                            archive.unlink()
                            self._session_pack = {"sha256": pack["sha256"], "verified": verified}
                        else:
                            verified = self._session_pack["verified"]
                        member = next((m for m in verified["members"] if m["member"] == seg["member"]), None)
                        if member is None or (member["sha256"], member["size"]) != (seg["sha256"], seg["length"]):
                            raise EvidenceError("referenced segment bytes mismatch")
                        if hash_file(extracted / member["sha256"]) != (member["sha256"], member["size"]):
                            raise EvidenceError("verified staging member changed during preparation")
                        with (extracted / member["sha256"]).open("rb") as stream:
                            shutil.copyfileobj(stream, output, 1024 * 1024)
                        proof = {"object_id": seg["object_id"], "sha256": pack["sha256"], "size": pack["size"],
                                 "members": [{**member, "artifact_id": ref["artifact_id"]}]}
                        prior = next((p for p in proofs if p["sha256"] == proof["sha256"]), None)
                        if prior is None:
                            proofs.append(proof)
                        elif not any(m["member"] == member["member"] for m in prior["members"]):
                            prior["members"].append(proof["members"][0])
                        offset += member["size"]
                if hash_file(whole) != (ref["sha256"], ref["size"]):
                    raise EvidenceError("reassembled original hash or length mismatch")
                current = self._cache_object_info(target)
                if reusable is not None:
                    reusable.resolve(ref)
                    reusable.resolve(supplied)
                    # Independent durable readback succeeded; keep the verified
                    # canonical inode and receipt, including all retained links.
                else:
                    if current is not None and current.st_nlink > 1:
                        self._shared_rebuild_required(target, "aliases appeared during preparation")
                    if current is None and self._missing_object_aliases(target):
                        self._shared_rebuild_required(target, "canonical object disappeared while aliases remain")
                    whole.replace(target)
                    receipt = {**ref, "verified_archive": proofs}
                    if aliases:
                        receipt["original_references"] = aliases
                    atomic_json(receipts / (ref["artifact_id"] + ".json"), receipt)
            if ref["schema"] not in ("evidence-bytes-v1", "archive-attachment-v1"):
                value = read_json(target, min(JSON_LIMIT, self.limits["metadata_stop_bytes"]))
                for nested in payload_references(value, ref["schema"]):
                    self._prepare([nested], catalog=catalog, reverify_durable=reverify_durable)
            self._preparing.remove(supplied["artifact_id"])
        return self.cache

    def import_archive(self, mapping):
        """Register original remote IDs without uploading or modifying any payload."""
        from .importer import normalize
        from .resolver import EvidenceResolver
        refs, packs = normalize(mapping, store_id=self.policy["store_id"], provider=self.policy["provider"])
        with self.locked():
            catalog = self._catalog(mutation=True)
            if len(refs) > self.limits["project_generation_stop_files"] or len(packs) > self.limits["retained_stop_objects"]:
                raise EvidenceError("import logical/object count exceeds configured aggregate bounds")
            for pack in packs.values():
                if pack["original_bytes"] > self.limits["archive_pack_stop_bytes"] or len(pack["members"]) > self.limits["migration_batch_stop_files"]:
                    raise EvidenceError("import archive requires explicitly sized decompression bounds")
                metadata = self._transport_call("stat", pack["locator"])
                if metadata["object_id"] != pack["locator"]["object_id"] or metadata["size"] != pack["size"]:
                    raise EvidenceError("imported remote object identity/size mismatch")
            for ref in refs:
                prior = catalog["refs"].get(ref["artifact_id"])
                if prior is not None and not same_reference(prior, ref):
                    raise EvidenceError("import artifact identity conflicts with an existing logical record")
            for digest, pack in packs.items():
                if digest in catalog["packs"] and catalog["packs"][digest] != pack:
                    raise EvidenceError("import archive identity conflicts with an existing original pack")
            prospective = {**catalog, "refs": {**catalog["refs"], **{r["artifact_id"]: r for r in refs}},
                           "packs": {**catalog["packs"], **packs},
                           "reference_aliases": deepcopy(catalog.get("reference_aliases", {})), "_adopting": True}
            active = mapping.get("active_artifact_ids", [r["artifact_id"] for r in refs])
            if not isinstance(active, list) or any(ident not in prospective["refs"] for ident in active):
                raise EvidenceError("import active reference list is incomplete or malformed")
            self.prepare([prospective["refs"][ident] for ident in active], catalog=prospective)
            resolver = EvidenceResolver(self.cache)
            for ident in active:
                resolver.resolve(prospective["refs"][ident])
            saved = self.state / "imports" / (hashlib.sha256(canonical(mapping)).hexdigest() + ".json")
            saved.parent.mkdir(exist_ok=True)
            if saved.parent.is_symlink():
                raise EvidenceError("import catalog preservation directory is linked")
            if not saved.exists():
                atomic_json(saved, mapping)
            new_refs = []
            for ref in refs:
                prior = catalog["refs"].get(ref["artifact_id"])
                if prior is not None and not same_reference(prior, ref):
                    raise EvidenceError("import artifact identity conflicts with an existing logical record")
                if prior is None:
                    new_refs.append(ref)
            new_packs = {key: value for key, value in packs.items() if key not in catalog["packs"]}
            new_aliases = {ident: aliases for ident, aliases in prospective["reference_aliases"].items()
                          if aliases != catalog.get("reference_aliases", {}).get(ident, [])}
            if new_refs or new_packs or new_aliases:
                self._publish(catalog, {"version": 1, "refs": new_refs, "packs": new_packs,
                    "reference_aliases": new_aliases,
                    "import_provenance": {"mapping_sha256": hashlib.sha256(canonical(mapping)).hexdigest(),
                                          "original_catalogs": mapping.get("original_catalogs", [])}})
            return refs

    def restore(self, refs, destination):
        """Reserve every external restored copy and retain its truthful occupancy."""
        from .accounting import Accounting
        refs = list(refs)
        destination = Path(destination).absolute()
        if destination.is_symlink():
            raise EvidenceError("restoration destination is linked")
        destination.mkdir(parents=True, exist_ok=True)
        destination = destination.resolve()
        self.prepare(refs)
        amount = sum(r["size"] for r in refs)
        self._capacity(amount)
        key = "restore:" + hashlib.sha256(str(destination).encode()).hexdigest()
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            self._local_records(ledger)
            reservation = ledger.reserve_working(amount, capacity_path=destination)
            old = ledger.connection.execute("SELECT bytes FROM local_usage WHERE key=?", (key,)).fetchone()
            old_bytes = old[0] if old else 0
            restored, actual = [], 0
            try:
                for ref in refs:
                    target = destination / ref["artifact_id"]
                    if target.exists() or target.is_symlink():
                        raise EvidenceError("restoration never overwrites an existing path")
                    capture(self.cache / "objects" / ref["sha256"], target, ref["size"])
                    actual += ref["size"]
                    restored.append(str(target))
            finally:
                self._audit_source_payloads()
                result = ledger.finish_working(reservation, local_key=key, actual_bytes=old_bytes + actual, kind="restore")
            if result["incomplete"]:
                raise EvidenceError("restoration resource settlement incomplete: " + "; ".join(result["violations"]))
        return restored

    def _generation_authority(self, entries=None):
        key = self.prefix + "authority/coordinator.json"
        if entries is None:
            entries = self._catalog_inventory(self.prefix + "authority/")
        if not entries:
            return None
        if len(entries) != 1 or (entries[0] if isinstance(entries[0], str) else entries[0]["key"]) != key:
            raise EvidenceError("ambiguous generation coordinator authority; reconciliation required")
        value, _ = self._read_remote_json(entries[0], 4096)
        if (not isinstance(value, dict) or value.get("version") != 1
                or value.get("project_id") != self.policy["project_id"]
                or value.get("store_id") != self.policy["store_id"]
                or not isinstance(value.get("coordinator"), str)):
            raise EvidenceError("invalid generation coordinator authority")
        return value

    def _require_policy_successor(self, head):
        lineage = self.policy.get(LINEAGE_FIELD)
        if not lineage or lineage["steps"][-1]["from_policy_sha256"] != hashlib.sha256(canonical(head)).hexdigest():
            raise EvidenceError("explicit policy transition requires the exact committed immediate predecessor")
        if resolve_historical_policy(self.policy, hashlib.sha256(canonical(head)).hexdigest()) != head:
            raise EvidenceError("policy transition predecessor differs from full committed policy")

    def initialize_generation_authority(self):
        """Explicit setup commits a same-owner policy transition before local setup."""
        with self.locked():
            catalog = self._catalog(mutation=True, allow_policy_transition=True)
            value = self._generation_authority()  # Independent fresh authority read.
            expected = {"version": 1, "project_id": self.policy["project_id"],
                        "store_id": self.policy["store_id"], "coordinator": self.coordinator}
            lineage = self.policy.get(LINEAGE_FIELD)
            if value is None:
                if lineage:
                    raise EvidenceError("policy lineage cannot create generation authority; original setup must remain provable")
                data = canonical(expected)
                with self._working(len(data) * 2, metadata_bytes=len(data), metadata_files=1), tempfile.TemporaryDirectory(dir=self.staging, prefix="authority-") as temp:
                    source, readback = Path(temp) / "claim.json", Path(temp) / "verified.json"
                    source.write_bytes(data)
                    locator = self._transport_call("put", self.prefix + "authority/coordinator.json", source)
                    self._transport_call("get", locator, readback, len(data))
                    if hash_file(readback) != (hashlib.sha256(data).hexdigest(), len(data)):
                        raise EvidenceError("generation coordinator authority readback mismatch")
                value = self._generation_authority()
            if value != expected:
                raise EvidenceError("generation requires the designated coordinator and shared accounting home; cold recovery is read-only")
            if lineage:
                head = validate_policy(catalog["policy"]) if "policy" in catalog else None
                if head is None:
                    if catalog["sequence"] != 0 or len(lineage["steps"]) != 1:
                        raise EvidenceError("first policy lineage requires one transition and existing exact authority")
                elif head != self.policy:
                    self._require_policy_successor(head)
                if head != self.policy:
                    # A unique policy-only segment avoids duplicate immutable index
                    # descriptors while retaining ordinary publication fences/readback.
                    self._publish(catalog, {"version": 1, "policy_transition": lineage["steps"][-1]["digest"]}, allow_policy_transition=True)
                    verified = self._catalog(mutation=True)
                    if validate_policy(verified.get("policy")) != self.policy:
                        raise EvidenceError("policy transition independent catalog readback differs")
            return {"coordinator_authorized": True, "coordinator": self.coordinator,
                    "project_id": self.policy["project_id"]}

    def _generation_owner_state(self, intent):
        """Exact identities resist PID reuse; old records retain conservative checks."""
        if "owner_identity" in intent:
            return process_identity.state(intent["owner_identity"])
        if intent["owner_host"] != socket.gethostname():
            return "unknown"
        return "alive" if self._owner_alive(intent["owner_pid"]) else "gone"

    def _recover_managed_producers(self, *, dry_run=True):
        from .accounting import Accounting
        from .producer import recover_producers
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            ledger._publication_manager = (self, None, None)
            return recover_producers(ledger, dry_run=dry_run)

    def _validate_generation_quarantine(self, ident, value, intents):
        from .quarantine import validate_quarantine_descriptor
        validate_quarantine_descriptor(value, policy=self.policy)
        if ident != value["reservation_id"]:
            raise EvidenceError("generation quarantine reservation index differs")
        intent = intents.get(value["intent_id"])
        if (intent is None or intent.get("settled")
                or (intent["run_id"], intent["unit_id"]) != (value["run_id"], value["unit_id"])
                or (intent["reserve_bytes"], intent["reserve_files"])
                   != (value["reservation"]["bytes"], value["reservation"]["files"])):
            raise EvidenceError("generation quarantine lacks its exact unresolved durable intent")

    def _generation_readiness(self, catalog, ledger):
        publication = self._publication_view(catalog)
        readiness = ledger.generation_readiness(_publication=publication)
        published = catalog.get("generation_quarantines", {})
        local = {item["reservation_id"]: item for item in readiness["quarantines"]}
        if local != published:
            raise EvidenceError("generation quarantine publication or original local accounting is incomplete")
        for ident, value in published.items():
            self._validate_generation_quarantine(ident, value, catalog.get("generation_intents", {}))
        return readiness

    def _publication_view(self, catalog):
        authority = self._generation_authority()
        if (catalog.get('generation_quarantines') or catalog.get('generation_quarantine_device_witnesses')) and (
                authority is None or authority['coordinator'] != self.coordinator or catalog['coordinator'] != self.coordinator):
            raise EvidenceError('quarantine publication requires designated original coordinator')
        return {'quarantines': catalog.get('generation_quarantines', {}),
                'witnesses': catalog.get('generation_quarantine_device_witnesses', {}),
                'bindings': catalog.get('generation_quarantine_device_bindings', {}), 'authority': authority}

    @contextmanager
    def _publication_budget(self, deadline=None):
        """Bound the whole synchronous lock/catalog sequence, not each RPC alone."""
        from .quarantine_device import PUBLICATION_TIMEOUT
        end = min(time.monotonic() + PUBLICATION_TIMEOUT, deadline if deadline is not None else float('inf'))
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise EvidenceError('publication verification deadline expired')
        if os.name != 'posix' or threading.current_thread() is not threading.main_thread():
            raise EvidenceError('bounded quarantine publication requires POSIX main-thread execution')
        prior_timer = signal.getitimer(signal.ITIMER_REAL)
        if prior_timer != (0.0, 0.0):
            raise EvidenceError('publication verification cannot replace an existing process alarm')
        prior_handler = signal.getsignal(signal.SIGALRM)
        def expired(*_):
            raise EvidenceError('publication verification total deadline expired')
        try:
            signal.signal(signal.SIGALRM, expired)
            signal.setitimer(signal.ITIMER_REAL, remaining)
            yield end
        finally:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0)
            finally:
                signal.signal(signal.SIGALRM, prior_handler)

    def _producer_publication_coverage(self, ledger, intent_id=None, *, attempt_id=None, deadline=None):
        if ledger.connection.in_transaction:
            raise EvidenceError('publication check cannot run inside an accounting write transaction')
        if ledger.path != self.state / 'accounting.sqlite' or ledger.policy != self.policy:
            raise EvidenceError('publication coverage requires original accounting home/policy')
        with self._publication_budget(deadline) as end, self.locked(timeout=max(0, end - time.monotonic())):
            catalog = self._catalog(mutation=True)
            if intent_id is not None:
                intent = catalog.get('generation_intents', {}).get(intent_id)
                if intent is None or intent.get('settled'):
                    raise EvidenceError('publication coverage lacks exact unresolved generation intent')
                if intent.get('owner_identity') != process_identity.identity():
                    raise EvidenceError('publication coverage requires exact live intent owner')
                if attempt_id is not None:
                    from .producer_runtime import read
                    record = read(ledger, attempt_id)
                    if (record.get('intent_id') != intent_id or record['run_id'] != intent['run_id']
                            or record['unit_id'] != intent['unit_id'] or record['coordinator'] != intent.get('owner_identity')):
                        raise EvidenceError('publication coverage producer/intent/owner changed')
                    reservation = ledger.connection.execute('SELECT run_id,bytes,files FROM reservations WHERE id=?', (record['reservation_id'],)).fetchone()
                    if reservation is None or tuple(reservation) != (intent['run_id'], intent['reserve_bytes'], intent['reserve_files']):
                        raise EvidenceError('publication coverage reservation/intent changed')
            publication = self._publication_view(catalog)
            readiness = ledger.generation_readiness(_publication=publication)
            if not readiness['ready']:
                raise EvidenceError('quarantine publication/native validation incomplete: ' + str(readiness['problem']))
            publication.update(intent_id=intent_id, intent=catalog.get('generation_intents', {}).get(intent_id))
            return publication

    def revalidate_quarantine_device(self, attempt_id, assertion_ref, *, operation_id, dry_run=True):
        """Explicit current-custody append; never repair or accept old generation."""
        from .accounting import Accounting
        from .quarantine import canonical
        from .quarantine_device import verify_quarantine_device_current, read_assertion
        if type(dry_run) is not bool:
            raise EvidenceError('custody dry_run must be boolean')
        with self.locked():
            catalog = self._catalog(mutation=True)
            publication = self._publication_view(catalog)
            with Accounting(self.state / 'accounting.sqlite', self.policy['project_id'], self.policy) as ledger:
                row = ledger.connection.execute('SELECT record FROM producer_quarantines WHERE attempt_id=?', (attempt_id,)).fetchone()
                if row is None:
                    raise EvidenceError('device revalidation requires existing original quarantine')
                descriptor = json.loads(row[0])
                if publication['quarantines'].get(descriptor['reservation_id']) != descriptor:
                    raise EvidenceError('device revalidation original local/publication differs')
                self._validate_generation_quarantine(descriptor['reservation_id'], descriptor, catalog['generation_intents'])
                if descriptor['ledger_id'] != ledger._ledger_id:
                    raise EvidenceError('device revalidation cannot adopt a recovered ledger')
                witness = ledger.prepare_device_witness(descriptor, assertion_ref, operation_id, publication['authority'])
                published = publication['witnesses'].get(descriptor['digest'])
                local = ledger.device_witnesses(allow_orphan=operation_id).get(descriptor['digest'])
                if published is not None and (published != witness or local != witness):
                    raise EvidenceError('published custody witness has missing or conflicting local authority')
                if not dry_run and published is None:
                    # Includes durable assertion/witness/SQL-WAL, staging, index,
                    # root history and readback peaks; actual occupancy is also
                    # charged by the existing accounting/transport machinery.
                    size = len(canonical(witness)) + Path(assertion_ref['path']).lstat().st_size
                    peak = size * 12 + len(canonical(catalog)) * 3 + 262144
                    with self._working(peak, metadata_bytes=peak, metadata_files=12):
                        read_assertion(assertion_ref, descriptor, self.policy)
                        verify_quarantine_device_current(ledger, descriptor, witness, coordinator_authority=publication['authority'])
                        if local is None:
                            ledger.append_device_witness(witness)
                        verify_quarantine_device_current(ledger, descriptor, witness, coordinator_authority=publication['authority'])
                        # Unknown outcomes are retried only after this method's
                        # initial independent catalog reload, never blindly.
                        self._publish(catalog, {'version': 1, 'generation_quarantine_device_witnesses': {descriptor['digest']: witness}})
                        verified = self._catalog(mutation=True)
                        if verified.get('generation_quarantine_device_witnesses', {}).get(descriptor['digest']) != witness:
                            raise EvidenceError('custody publication independent readback differs')
                    publication = self._publication_view(verified)
                if not dry_run:
                    if ledger.device_witnesses() != publication['witnesses']:
                        raise EvidenceError('custody authoritative triple is incomplete')
                    verify_quarantine_device_current(ledger, descriptor, witness, coordinator_authority=publication['authority'])
                return {'action': 'revalidate-quarantine-device', 'dry_run': dry_run,
                        'history_complete': False, 'historical_uncertainty': True, 'witness': witness}

    def quarantine_producer(self, attempt_id, disposition_proof, *, dry_run=True):
        """Preserve an unresolved gap and publish its immutable bounded disposition."""
        from .accounting import Accounting
        with self.locked():
            catalog = self._catalog(mutation=True)
            authority = self._generation_authority()
            if authority is None or authority["coordinator"] != self.coordinator:
                raise EvidenceError("producer quarantine requires the designated generation coordinator")
            with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
                self._reconcile_ledger(catalog, ledger)
                descriptor = ledger.quarantine_producer(attempt_id, disposition_proof, dry_run=True)
                ident = descriptor["reservation_id"]
                self._validate_generation_quarantine(ident, descriptor, catalog.get("generation_intents", {}))
                prior = catalog.get("generation_quarantines", {}).get(ident)
                if prior is not None and prior != descriptor:
                    raise EvidenceError("immutable generation quarantine changed")
                if any(other != ident and (item["attempt_id"] == descriptor["attempt_id"]
                       or item["intent_id"] == descriptor["intent_id"])
                       for other, item in catalog.get("generation_quarantines", {}).items()):
                    raise EvidenceError("generation quarantine replays another binding")
                if not dry_run:
                    descriptor = ledger.quarantine_producer(attempt_id, disposition_proof, dry_run=False)
            if not dry_run and prior is None:
                self._publish(catalog, {"version": 1, "generation_quarantines": {ident: descriptor}})
                verified = self._catalog(mutation=True).get("generation_quarantines", {}).get(ident)
                if verified != descriptor:
                    raise EvidenceError("generation quarantine independent catalog readback differs")
            return {"action": "quarantine-producer", "dry_run": dry_run,
                    "history_complete": False, "historical_uncertainty": True,
                    "descriptor": descriptor}

    @contextmanager
    def _generation_catalog(self):
        """Yield fresh ready catalog under its lock; recover before acquiring it."""
        catalog = self._catalog(mutation=True)
        authority = self._generation_authority()
        if authority is None:
            if catalog["sequence"] == 0:
                raise EvidenceError("generation coordinator is not initialized; run evidence setup for this project first")
            # An existing catalog already records its original designated coordinator.
            self.initialize_generation_authority()
            authority = self._generation_authority()
        if authority["coordinator"] != self.coordinator:
            raise EvidenceError("generation requires the designated coordinator and shared accounting home; cold recovery is read-only")
        recovery = self._recover_managed_producers(dry_run=False)
        if recovery["incomplete"]:
            details = '; '.join(str(item['problem']) for item in recovery.get('actions', []) if item.get('problem'))
            raise EvidenceError("managed producer recovery remains incomplete; retain its resources and reconcile before generation" + ('; ' + details if details else ''))
        for action in recovery["actions"]:
            intent = catalog.get("generation_intents", {}).get(action.get("intent_id"))
            if (intent and not intent.get("settled") and action["action"] in ("cleaned", "terminal")
                    and not action.get("incomplete") and self._generation_owner_state(intent) == "gone"):
                self.finish_generation(action["intent_id"], reservation_id=action.get("reservation_id"))
        # Recovery may publish settlements. Always reload after it, then retain
        # this lock through the caller's publication instead of loading again.
        # Do not extend the lock across producer shutdown above.
        with self.locked():
            catalog = self._catalog(mutation=True)
            from .accounting import Accounting
            with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
                self._reconcile_ledger(catalog, ledger)
                readiness = self._generation_readiness(catalog, ledger)
                if not readiness['ready']:
                    raise EvidenceError('accounting recovery required: ' + str(readiness['problem']))
                quarantined = {item["intent_id"] for item in readiness["quarantines"]}
                for intent_id, intent in catalog.get("generation_intents", {}).items():
                    if intent_id in quarantined:
                        continue
                    if not intent.get("settled"):
                        owner_state = self._generation_owner_state(intent)
                        run = ledger.connection.execute("SELECT 1 FROM runs WHERE id=?", (intent["run_id"],)).fetchone()
                        pending = ledger.connection.execute("SELECT 1 FROM reservations WHERE run_id=? AND state='pending'", (intent["run_id"],)).fetchone()
                        if (run is None or pending) and owner_state != "alive":
                            raise EvidenceError("durable generation intent has unknown local accounting; reconcile before generation")
            yield catalog

    def assert_generation_authority(self):
        """Recover owned local attempts, then require designated generation authority."""
        with self._generation_catalog():
            return {"coordinator_authorized": True, "coordinator": self.coordinator}

    @staticmethod
    def _run_generation(run):
        record = {"gross_bytes": run["gross_bytes"], "logical_files": run["gross_files"],
                  "run_id": run["id"], "unit_id": run["unit_id"], "mode": "managed-run-total"}
        return {"managed-run:" + hashlib.sha256(canonical(record)).hexdigest(): record}

    def begin_generation(self, run_id, unit_id, reserve_bytes, reserve_files):
        """Record an incomplete durable intent before any managed producer starts."""
        with self._generation_catalog() as catalog:
            if (any(not isinstance(value, str) or not value for value in (run_id, unit_id))
                    or any(type(value) is not int or value < 0 for value in (reserve_bytes, reserve_files))):
                raise EvidenceError("generation intent requires stable run/unit and nonnegative reservation bounds")
            owner = process_identity.identity()
            if owner is None:
                raise EvidenceError("cannot establish the generation owner process identity")
            intent = str(uuid.uuid4())
            if any(item["run_id"] == run_id for item in catalog.get("generation_quarantines", {}).values()):
                raise EvidenceError("quarantined historical run cannot resume generation; use a fresh run identity")
            self._publish(catalog, {"version": 1, "generation_intents": {intent: {
                "run_id": run_id, "unit_id": unit_id, "reserve_bytes": reserve_bytes, "reserve_files": reserve_files,
                "owner_pid": os.getpid(), "owner_host": socket.gethostname(), "owner_identity": owner}}})
        return intent

    def finish_generation(self, intent_id, reservation_id=None):
        """Publish settled success/failure charges without requiring a payload archive."""
        from .accounting import Accounting
        with self.locked():
            catalog = self._catalog(mutation=True)
            intent = catalog.get("generation_intents", {}).get(intent_id)
            if intent is None:
                raise EvidenceError("generation settlement requires its original durable intent")
            if any(item["intent_id"] == intent_id or item["reservation_id"] == reservation_id
                   for item in catalog.get("generation_quarantines", {}).values()):
                raise EvidenceError("quarantined generation intent remains unresolved and cannot be settled")
            if intent.get("settled"):
                with Accounting(self.state / 'accounting.sqlite', self.policy['project_id'], self.policy) as ledger:
                    if not self._generation_readiness(catalog, ledger)['ready']:
                        raise EvidenceError('settled intent publication readiness is incomplete')
                return {"settled": True, "intent_id": intent_id}
            owner_state = self._generation_owner_state(intent)
            owns_intent = (intent.get("owner_identity") == process_identity.identity() if "owner_identity" in intent
                           else intent["owner_host"] == socket.gethostname() and intent["owner_pid"] == os.getpid())
            if owner_state == "unknown" or owner_state == "alive" and not owns_intent:
                raise EvidenceError("generation intent owner/helper exit cannot be verified; intent retained")
            recovery = self._recover_managed_producers(dry_run=True)
            attempts = [action for action in recovery["actions"] if action.get("intent_id") == intent_id]
            if recovery["incomplete"]:
                raise EvidenceError("generation intent has active or unresolved producer recovery; intent retained")
            if attempts:
                if (len(attempts) != 1 or attempts[0].get("incomplete")
                        or attempts[0]["action"] not in ("cleaned", "terminal")):
                    raise EvidenceError("generation intent still has an active or unresolved producer; intent retained")
                exact_reservation = attempts[0].get("reservation_id")
                if (not isinstance(exact_reservation, str) or not exact_reservation
                        or attempts[0].get("run_id") != intent["run_id"]):
                    raise EvidenceError("generation producer recovery lacks its original run/reservation binding")
                if reservation_id is not None and reservation_id != exact_reservation:
                    raise EvidenceError("generation settlement reservation belongs to another producer intent")
                reservation_id = exact_reservation
            with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
                self._reconcile_ledger(catalog, ledger)
                readiness = self._generation_readiness(catalog, ledger)
                if not readiness['ready']:
                    raise EvidenceError('accounting recovery required: ' + str(readiness['problem']))
                run = ledger.connection.execute("SELECT * FROM runs WHERE id=?", (intent["run_id"],)).fetchone()
                pending = ledger.connection.execute("SELECT COUNT(*) FROM reservations WHERE run_id=? AND state='pending'", (intent["run_id"],)).fetchone()[0]
                if reservation_id is not None:
                    reservation = ledger.connection.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
                    if reservation is None or reservation["run_id"] != intent["run_id"] or reservation["state"] == "pending":
                        raise EvidenceError("generation settlement lacks its settled producer reservation")
                elif pending:
                    raise EvidenceError("generation has pending reservations; retain intent or supply its settled producer reservation")
                if run is not None and run["unit_id"] != intent["unit_id"]:
                    raise EvidenceError("generation settlement run/unit differs from its durable intent")
                generation = self._run_generation(run) if run is not None else {}
            self._publish(catalog, {"version": 1, "generation": generation,
                                   "settled_generation_intents": [intent_id]})
            return {"settled": True, "pending_workers": bool(pending), "intent_id": intent_id}

    @contextmanager
    def accounting_receipt_snapshot(self, policy_sha256):
        """Hold current publication authority through caller serialization/emission."""
        from .accounting import Accounting
        from .quarantine import _hash
        if not _hash(policy_sha256):
            raise EvidenceError('accounting receipt requires exact original policy byte hash')
        with self.locked():
            catalog = self._catalog()
            with Accounting(self.state / 'accounting.sqlite', self.policy['project_id'], self.policy) as ledger:
                self._reconcile_ledger(catalog, ledger)
                runs = {}
                for row in ledger.connection.execute('SELECT * FROM runs WHERE migration=0'):
                    pending = ledger.connection.execute("SELECT COUNT(*) FROM reservations WHERE run_id=? AND state='pending'", (row['id'],)).fetchone()[0]
                    outputs = ledger.connection.execute('SELECT COUNT(*) FROM outputs WHERE run_id=? AND reconciled=0', (row['id'],)).fetchone()[0]
                    runs[row['id']] = {'unit_id': row['unit_id'], 'status': 'complete' if row['status'] == 'complete' and not pending and not outputs else 'incomplete',
                        'gross_generated_bytes': row['gross_bytes'], 'original_logical_files': row['gross_files'],
                        'pending_reservations': pending, 'unreconciled_outputs': outputs}
                for ref in catalog['refs'].values():
                    if ref['retention'].get('imported') or ref['provenance'].get('accounting_mode') == 'imported-existing':
                        runs.setdefault(ref['provenance']['run_id'], {'unit_id': ref['provenance']['unit_id'], 'status': 'complete', 'mode': 'imported-existing',
                            'gross_generated_bytes': 0, 'original_logical_files': 0, 'pending_reservations': 0, 'unreconciled_outputs': 0})
                snapshot = ledger.snapshot()
                pending_intents = {k: v for k, v in catalog.get('generation_intents', {}).items() if not v.get('settled')}
                complete = snapshot.get('accounting_complete', True) and not pending_intents
                result = {'version': 1, 'project_id': self.policy['project_id'], 'runs': runs,
                          'accounting_complete': complete, 'incomplete': not complete, 'totals_are_lower_bounds': not complete,
                          'pending_generation_intents': pending_intents, 'policy_sha256': policy_sha256}
                readiness = self._generation_readiness(catalog, ledger)
                quarantines = readiness['quarantines']
                if quarantines:
                    quarantined_intents = {q['intent_id'] for q in quarantines}
                    quarantined_runs = {q['run_id'] for q in quarantines}
                    outstanding = any(k not in quarantined_runs and (v['pending_reservations'] or v['unreconciled_outputs']) for k, v in runs.items())
                    outstanding = outstanding or any(runs[k]['pending_reservations'] != sum(q['run_id'] == k for q in quarantines) for k in quarantined_runs)
                    ready = readiness['ready'] and set(pending_intents) == quarantined_intents and not outstanding
                    result.update(version=2, kind='scoped-known-generation', accounting_complete=False, incomplete=True,
                                  totals_are_lower_bounds=True, history_complete=False, generation_ready=ready, quarantines=quarantines,
                                  selected_scope={'run_ids': sorted(k for k, v in runs.items() if v['status'] == 'complete'), 'complete': bool(ready)})
                    witnesses = catalog.get('generation_quarantine_device_witnesses', {})
                    if witnesses:
                        from .quarantine_device import validate_device_custody_receipt
                        if not ready:
                            raise EvidenceError('custody receipt requires complete selected known scope')
                        result.update(version=3, kind='scoped-known-generation-with-device-custody',
                                      quarantine_device_witnesses=[witnesses[k] for k in sorted(witnesses)],
                                      quarantine_device_catalog=catalog['generation_quarantine_device_bindings'])
                        validate_device_custody_receipt(result, self.policy, quarantines)
                elif catalog.get('generation_quarantine_device_witnesses'):
                    raise EvidenceError('custody receipt publication/local readiness is incomplete')
                yield result

    def status(self):
        catalog = self._catalog()
        unique = self._retained_content(catalog["packs"])
        from .accounting import Accounting
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            self._reconcile_ledger(catalog, ledger)
            accounting = ledger.snapshot()
        pending = {key: value for key, value in catalog.get("generation_intents", {}).items() if not value.get("settled")}
        complete = accounting.get("accounting_complete", True) and not pending
        authority = self._generation_authority()
        authorized = catalog["coordinator"] == self.coordinator and (authority is None or authority["coordinator"] == self.coordinator)
        accounting["accounting_complete"] = complete
        accounting["totals_are_lower_bounds"] = not complete
        accounting["pending_generation_intents"] = pending
        return {"project_id": self.policy["project_id"], "refs": len(catalog["refs"]), "retained_unique_bytes": sum(unique.values()),
                "physical_objects": len(catalog["packs"]) + len(catalog.get("unreconciled_packs", {})),
                "unreconciled_archive_objects": len(catalog.get("unreconciled_packs", {})),
                "unreconciled_archive_encoded_bytes": sum(p["size"] for p in catalog.get("unreconciled_packs", {}).values()),
                "retained_allowance_bytes": accounting["totals"]["retained_unique_bytes"], "metadata_bytes": catalog["metadata_bytes"],
                "metadata_objects": catalog["metadata_files"], "local_working_bytes": self._usage(),
                "gross_generated_bytes": accounting["totals"]["project_generated_bytes"] if complete else None,
                "known_gross_generated_bytes": accounting["totals"]["project_generated_bytes"],
                "original_logical_files": accounting["totals"]["project_generated_files"] if complete else None,
                "known_original_logical_files": accounting["totals"]["project_generated_files"], "accounting": accounting,
                "accounting_complete": complete, "coordinator_authorized": authorized}

    def establish_import_retention(self, artifact_ids):
        """Acknowledge selected policy administratively; immutable references stay valid."""
        if not isinstance(artifact_ids, (list, tuple)) or any(not isinstance(ident, str) or not ident for ident in artifact_ids):
            raise EvidenceError("retention migration decision requires registered artifact IDs")
        with self.locked():
            catalog = self._catalog(mutation=True)
            acknowledged = catalog.get("import_retention_decisions", {})
            if not isinstance(acknowledged, dict):
                raise EvidenceError("unsupported imported retention decision index")
            decisions, refs = {}, []
            for ident in dict.fromkeys(artifact_ids):
                ref = catalog["refs"].get(ident)
                if ref is None or ref["retention"].get("imported") is not True:
                    raise EvidenceError("retention migration decision applies only to registered imported artifacts: " + ident)
                refs.append(deepcopy(ref))
                if ident in acknowledged:
                    continue  # Preserve previous decisions and avoid repeated catalog growth.
                decisions[ident] = {"version": 1, "policy_sha256": hashlib.sha256(canonical(self.policy)).hexdigest(),
                    "provider": self.policy["provider"],
                    "days": self.policy["retention"]["drive_days" if self.policy["provider"] == "google-drive" else "local_days"],
                    "decided_at": datetime.now(timezone.utc).isoformat()}
            if decisions:
                self._publish(catalog, {"version": 1, "import_retention_decisions": decisions})
            return refs

    def reconcile(self, *, dry_run=True):
        """Recover registered producer/deletion intents, never discover disposable paths."""
        actions = self._reconcile_lock(dry_run)
        if dry_run and (self.state / "catalog.lock").exists():
            return actions  # A retained stale lock must be reconciled before catalog work.
        producer_recovery = self._recover_managed_producers(dry_run=dry_run)
        actions.extend(producer_recovery["actions"])
        if producer_recovery["incomplete"] and not any(action.get("incomplete") for action in producer_recovery["actions"]):
            actions.append({"action": "producer-recovery-retained", "incomplete": True,
                            "reason": "managed producer recovery remains incomplete"})
        from .accounting import Accounting
        from .transports import LocalTransport
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            for row in ledger.connection.execute("SELECT * FROM working_reservations WHERE state='pending'").fetchall():
                owner_known = row["owner_host"] == socket.gethostname() and row["owner_pid"] is not None
                exited = owner_known and not self._owner_alive(row["owner_pid"])
                if exited and isinstance(self.transport, LocalTransport):
                    action = {"action": "reconcile-exited-working-reservation", "reservation_id": row["id"], "dry_run": dry_run}
                    if not dry_run:
                        self._local_records(ledger)
                        self._audit_source_payloads()
                        ledger.finish_working(row["id"])
                        action["verified"] = True
                    actions.append(action)
                else:
                    actions.append({"action": "working-reservation-retained", "reservation_id": row["id"], "incomplete": True,
                        "reason": "owner/helper exit cannot be verified" if exited or not owner_known else "owning process is still running"})
        for journal in sorted(self.state.glob("archive-*.deletion.json")):
            intent = read_json(journal, self.limits["metadata_stop_bytes"])
            archive_journal = journal.with_name(journal.name.replace(".deletion.json", ".json"))
            checkpoint = read_json(archive_journal, self.limits["metadata_stop_bytes"])
            remaining = [entry for entry in intent["entries"] if not entry["done"]]
            if not remaining:
                continue
            actions.append({"journal": str(journal), "pending": len(remaining), "dry_run": dry_run})
            if not dry_run:
                self._remove_captured(checkpoint["inventory"], checkpoint["refs"], archive_journal)
        if (self.state / "pruning.json").exists():
            actions += self.cleanup(dry_run=dry_run, expire=False)
        catalog = self._catalog()
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            self._reconcile_ledger(catalog, ledger)
            validated_quarantines = {item["intent_id"]: item
                for item in self._generation_readiness(catalog, ledger)["quarantines"]}
        for ident, intent in catalog.get("generation_intents", {}).items():
            if ident in validated_quarantines:
                actions.append({"action": "generation-intent-quarantined", "intent_id": ident,
                    "reservation_id": validated_quarantines[ident]["reservation_id"],
                    "incomplete": False, "historical_uncertainty": True, "history_complete": False})
                continue
            if intent.get("settled"):
                continue
            own_catalog = catalog["coordinator"] == self.coordinator
            owner_state = self._generation_owner_state(intent)
            attempts = [item for item in producer_recovery["actions"] if item.get("intent_id") == ident]
            settled_attempt = (attempts[0] if len(attempts) == 1 and not attempts[0].get("incomplete")
                               and attempts[0]["action"] in ("terminal", "cleaned") else None)
            action = {"action": "generation-intent-retained", "intent_id": ident, "incomplete": True,
                      "reason": "designated coordinator or owning process exit is not verified"}
            if (own_catalog and owner_state == "alive" and len(attempts) == 1
                    and attempts[0]["action"] == "active" and not attempts[0].get("incomplete")):
                action = {"action": "generation-intent-active", "intent_id": ident, "incomplete": False}
            if own_catalog and owner_state == "gone":
                with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
                    known = ledger.generation_readiness()["ready"]
                    pending = ledger.connection.execute("SELECT COUNT(*) FROM reservations WHERE run_id=? AND state='pending'", (intent["run_id"],)).fetchone()[0]
                if known and (not pending or settled_attempt):
                    action = {"action": "reconcile-exited-generation-intent", "intent_id": ident, "dry_run": dry_run}
                    if not dry_run:
                        self.finish_generation(ident, reservation_id=(settled_attempt or {}).get("reservation_id"))
                        action["verified"] = True
                else:
                    action["reason"] = "local accounting or producer reservations remain incomplete"
            actions.append(action)
        return actions

    def _evict_cache(self, ref, *, dry_run):
        """Never remove another link's canonical object or claim its bytes freed."""
        target = self.cache / "objects" / ref["sha256"]
        def retained(info):
            return {"artifact_id": ref["artifact_id"], "action": "retain-cache-aliases", "dry_run": dry_run,
                "retained_bytes": info.st_size, "freed_bytes": 0, "other_link_count": info.st_nlink - 1,
                "remaining_cache_bytes": self._cache_bytes(),
                "occupancy_scope": "distinct regular inode lengths under owned cache; not logical membership or allocated disk blocks",
                "reason": "retained aliases require explicit source-view rebuild/removal before cache eviction; other link ownership is unknown"}
        info = self._cache_object_info(target)
        if info is None:
            aliases = self._missing_object_aliases(target)
            if aliases:
                return {"artifact_id": ref["artifact_id"], "action": "retain-cache-aliases", "dry_run": dry_run,
                    "canonical_missing": True, "retained_bytes": self._occupancy_bytes(aliases), "freed_bytes": 0,
                    "remaining_cache_bytes": self._cache_bytes(),
                    "occupancy_scope": "distinct regular inode lengths under owned cache; digest-named orphan paths conservatively retained",
                    "reason": "canonical object is missing; retained digest-named aliases require explicit source-view rebuild"}
            return None
        if info.st_nlink > 1:
            return retained(info)
        released_bytes = 0
        if not dry_run:
            # Fresh ordinary reuse must not substitute for destructive cleanup's
            # independent current durable original-byte readback.
            self.prepare([ref], reverify_durable=True)
            if hash_file(target) != (ref["sha256"], ref["size"]):
                raise EvidenceError("cache changed before eviction")
            path, descriptor, before = _open_regular(target)
            try:
                _verify_stable(path, descriptor, before)
                if before.st_nlink > 1:
                    return retained(before)
                if os.name == "nt":
                    # The Windows stable-read handle intentionally denies delete
                    # sharing. Release it only after verification, then repeat
                    # the regular-inode/link-count guard under manager ownership.
                    os.close(descriptor)
                    descriptor = None
                    current = self._cache_object_info(path)
                    if current is None or (current.st_dev, current.st_ino, current.st_size) != (before.st_dev, before.st_ino, before.st_size):
                        raise EvidenceError("cache changed before eviction")
                    if current.st_nlink > 1:
                        return retained(current)
                path.unlink()
                if path.exists() or path.is_symlink():
                    raise EvidenceError("cache deletion failed: " + str(path))
                if descriptor is not None and os.fstat(descriptor).st_nlink:
                    raise EvidenceError("cache alias appeared during eviction; retained bytes require explicit source-view rebuild")
                released_bytes = before.st_size
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                from .accounting import Accounting
                with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
                    self._local_records(ledger)
        return {"artifact_id": ref["artifact_id"], "action": "evict-cache", "dry_run": dry_run,
            "freed_bytes": released_bytes, "remaining_cache_bytes": self._cache_bytes(),
            "occupancy_scope": "distinct regular inode lengths under owned cache; not allocated disk blocks"}

    def cleanup(self, *, now=None, dry_run=True, expire=False, protected_refs=(), reference_snapshot_complete=False):
        now = now or datetime.now(timezone.utc)
        with self.locked():
            catalog = self._catalog(mutation=expire)
            decisions = catalog.get("import_retention_decisions", {})
            if not isinstance(decisions, dict):
                raise EvidenceError("unsupported imported retention decision index")
            def pending_import(ref):
                retention = ref["retention"]
                for field in ("imported", "migration_policy_established"):
                    if field in retention and type(retention[field]) is not bool:
                        raise EvidenceError("unsupported imported retention flag: " + field)
                return retention.get("imported") is True and ref["artifact_id"] not in decisions
            protected = set(protected_refs)
            if expire and not reference_snapshot_complete:
                raise EvidenceError("permanent expiry requires a complete current claim/reference snapshot from the coordinator")
            # Required nested receipts/inventories have the same protection as their parent claim.
            roots = set(protected)
            roots.update(ref["artifact_id"] for ref in catalog["refs"].values() if ref["retention"].get("protections") or
                         ref["kind"] in ("approval", "authorization", "approved-baseline", "unresolved-failure") or
                         pending_import(ref))
            queue, visited = list(roots), set()
            while queue:
                ident = queue.pop()
                if ident in visited:
                    continue
                visited.add(ident)
                ref = catalog["refs"].get(ident)
                if ref is None:
                    raise EvidenceError("current protection root/dependency is absent from catalog")
                protected.add(ident)
                queue.extend(d["artifact_id"] for d in ref.get("dependencies", []))
            results, retired = [], []
            journal = self.state / "pruning.json"
            if not journal.exists() and catalog.get("pending_deletions"):
                recovered = {"version": 1, "retired": [], "packs": catalog["pending_deletions"], "done": []}
                if not dry_run:
                    atomic_json(journal, recovered)
                else:
                    results += [{"pack": key, "action": "resume-pending-delete", "dry_run": True} for key in recovered["packs"]]
            if journal.exists():
                intent = read_json(journal, self.limits["metadata_stop_bytes"])
                if catalog["coordinator"] != self.coordinator:
                    raise EvidenceError("pending pruning belongs to another coordinator")
                if not dry_run:
                    catalog = self._resume_pruning(catalog, intent, journal, results)
                else:
                    results += [{"pack": key, "action": "resume-pending-delete", "dry_run": True} for key in intent["packs"] if key not in intent["done"]]
            for ref in catalog["refs"].values():
                age = now - timestamp(ref["retention"]["sealed_at"])
                days = self.policy["retention"]["drive_days" if self.policy["provider"] == "google-drive" and expire else "local_days"]
                if days is None or age < timedelta(days=days):
                    continue
                protections = list(ref["retention"].get("protections", []))
                if ref["artifact_id"] in protected:
                    protections.append("current-claim-or-prerequisite")
                if pending_import(ref):
                    protections.append("imported-migration-policy-pending")
                if ref["kind"] in ("approval", "authorization", "approved-baseline", "unresolved-failure"):
                    protections.append(ref["kind"])
                if expire and protections:
                    results.append({"artifact_id": ref["artifact_id"], "action": "expired-but-protected", "reasons": protections})
                    continue
                if expire:
                    retired.append(ref["artifact_id"])
                    results.append({"artifact_id": ref["artifact_id"], "action": "retire", "dry_run": dry_run})
                else:
                    action = self._evict_cache(ref, dry_run=dry_run)
                    if action is not None:
                        results.append(action)
            if retired and not dry_run:
                remaining = {k: v for k, v in catalog["refs"].items() if k not in retired}
                used_packs = {seg["pack_sha256"] for ref in remaining.values() for seg in (ref["locator"].get("segments") or [ref["locator"]])}
                deleted = [key for key in catalog["packs"] if key not in used_packs]
                intent = {"version": 1, "retired": retired, "packs": {key: catalog["packs"][key] for key in deleted}, "done": []}
                if journal.exists():
                    previous = read_json(journal, self.limits["metadata_stop_bytes"])
                    intent["packs"].update(previous["packs"])
                    intent["done"] = previous["done"]
                atomic_json(journal, intent)
                # Catalog retirement precedes physical removal; interrupted removal is recoverable garbage.
                self._publish(catalog, {"version": 1, "retired": retired, "deletion_intent": deleted})
                self._resume_pruning(self._catalog(mutation=True), intent, journal, results)
            if not expire:
                # Only registered captured originals with verified durable references are eligible.
                for archive_journal in sorted(self.state.glob("archive-*.json")):
                    if archive_journal.name.endswith(".deletion.json"):
                        continue
                    checkpoint = read_json(archive_journal, self.limits["metadata_stop_bytes"])
                    if checkpoint.get("status") != "complete" or "inventory" not in checkpoint:
                        continue
                    pairs = list(zip(checkpoint["inventory"], checkpoint["refs"]))
                    if not pairs or any(now - timestamp(ref["retention"]["sealed_at"]) < timedelta(days=self.policy["retention"]["local_days"]) for _, ref in pairs):
                        continue
                    active_pairs = [(entry, ref) for entry, ref in pairs if catalog["refs"].get(ref["artifact_id"]) == ref]
                    expired_pairs = [(entry, ref) for entry, ref in pairs if catalog.get("retired_refs", {}).get(ref["artifact_id"]) == ref]
                    present = [entry for entry, _ in active_pairs if Path(entry["path"]).exists() or Path(entry["path"]).is_symlink()]
                    if present:
                        results.append({"action": "evict-local-originals", "paths": [entry["path"] for entry in present], "dry_run": dry_run})
                        if not dry_run:
                            if len(active_pairs) == len(pairs):
                                self._remove_captured(checkpoint["inventory"], checkpoint["refs"], archive_journal)
                    obsolete = [entry for entry, _ in expired_pairs if Path(entry["path"]).exists() or Path(entry["path"]).is_symlink()]
                    if obsolete:
                        results.append({"action": "expire-local-originals", "paths": [entry["path"] for entry in obsolete], "dry_run": dry_run})
                        if not dry_run:
                            expiry = self.state / ("expired-sources-" + hashlib.sha256(canonical(expired_pairs)).hexdigest() + ".json")
                            atomic_json(expiry, {"inventory": [x[0] for x in expired_pairs], "refs": [x[1] for x in expired_pairs], "retirement_root": catalog["root_key"]})
                            self._remove_captured([x[0] for x in expired_pairs], [x[1] for x in expired_pairs], expiry, permanent=True)
                # Original evacuation may have prepared a fresh cache copy. Evict that copy last.
                if not dry_run:
                    for ref in catalog["refs"].values():
                        if now - timestamp(ref["retention"]["sealed_at"]) < timedelta(days=self.policy["retention"]["local_days"]):
                            continue
                        action = self._evict_cache(ref, dry_run=False)
                        if action is not None and not any(item.get("artifact_id") == action["artifact_id"] and
                                item["action"] == action["action"] for item in results):
                            results.append(action)
                from .accounting import Accounting
                with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
                    self._local_records(ledger)
            return results

    def _resume_pruning(self, catalog, intent, journal, results):
        completed = []
        for key, pack in intent["packs"].items():
            if key in intent["done"]:
                if key in catalog["packs"]:
                    completed.append(key)
                continue
            try:
                # Transport delete is idempotent and independently verifies absence.
                self._transport_call("delete", pack["locator"])
                intent["done"].append(key)
                completed.append(key)
                atomic_json(journal, intent)
                results.append({"pack": key, "action": "deleted", "verified": True})
            except (OSError, EvidenceError) as error:
                results.append({"pack": key, "action": "delete-failed", "reason": str(error)})
        if completed:
            self._publish(catalog, {"version": 1, "deleted_packs": completed})
            catalog = self._catalog(mutation=True)
        if len(intent["done"]) == len(intent["packs"]):
            journal.unlink()
        return catalog
