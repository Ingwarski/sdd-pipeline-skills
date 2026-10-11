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
import socket
import sqlite3
import stat
import tempfile
import threading
import time
import uuid

from .archive import build_pack, verify_pack, capture
from .io import EvidenceError, atomic_json, hash_file, read_json, safe_relative, _open_regular, _verify_stable
from .policy import validate_policy
from .identity import same_reference, same_imported_original


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
    def __init__(self, transport, home, policy):
        self.transport, self.policy = transport, validate_policy(policy)
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
        self._catalog_thread_lock = threading.RLock()
        self._catalog_lock_depth = 0

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
        guard = self.state / ".coordinator-init.lock"
        if guard.is_symlink() or (guard.exists() and not guard.is_file()):
            raise EvidenceError("coordinator initialization lock is unsafe; retained")
        descriptor = os.open(guard, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        acquired = False
        try:
            info, current = os.fstat(descriptor), guard.lstat()
            if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(current.st_mode)
                    or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)):
                raise EvidenceError("coordinator initialization lock changed; retained")
            if info.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            deadline = time.monotonic() + 30
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
                        raise EvidenceError("coordinator initialization is busy; bounded wait exhausted")
                    time.sleep(0.01)
            if not identity.exists() and not identity.is_symlink():
                atomic_json(identity, {"id": str(uuid.uuid4()), "host": socket.gethostname()})
            return existing()
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
                    self._catalog_lock_depth = 0

    @contextmanager
    def _file_locked(self, timeout):
        lock = self.state / "catalog.lock"
        deadline = time.monotonic() + timeout
        while True:
            try:
                lock.mkdir()
                break
            except FileExistsError as error:
                if not lock.exists() and not lock.is_symlink():
                    continue
                if lock.is_symlink() or not lock.is_dir():
                    raise EvidenceError("catalog coordinator lock is unsafe; retained: " + str(lock)) from error
                try:
                    owner = read_json(lock / "owner.json", 4096)
                except (FileNotFoundError, EvidenceError) as read_error:
                    cause = getattr(read_error, "__cause__", None)
                    # Opening a Windows owner record can briefly conflict with
                    # its publisher/remover, just as releasing it can conflict
                    # with a stable reader. Retry only this lock handshake.
                    transient = (isinstance(cause, FileNotFoundError)
                        or getattr(cause, "winerror", None) in (32, 33)
                        or str(read_error).startswith(("file changed while opening:", "input changed while reading:")))
                    if not transient and ((lock / "owner.json").exists() or (lock / "owner.json").is_symlink()):
                        raise
                    owner = None  # Another same-home process is creating/removing its lock.
                if owner is not None:
                    if owner.get("host") != socket.gethostname() or owner.get("coordinator") != self.coordinator:
                        raise EvidenceError("catalog lock belongs to another host/coordinator; retained") from error
                    if not self._owner_alive(owner.get("pid")):
                        raise EvidenceError("catalog coordinator exited; reconcile the recorded lock: " + str(lock)) from error
                if time.monotonic() >= deadline:
                    raise EvidenceError("catalog coordinator is busy; bounded wait exhausted: " + str(lock)) from error
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            atomic_json(lock / "owner.json", {"pid": os.getpid(), "host": socket.gethostname(), "coordinator": self.coordinator})
            yield
        finally:
            self._release_owner_file(lock / "owner.json")
            lock.rmdir()

    @staticmethod
    def _release_owner_file(path):
        # Windows stable readers deny deletion while their short-lived handle
        # is open. Wait for those readers; never change evidence read sharing.
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
        if not lock.exists() and not lock.is_symlink():
            return []
        if lock.is_symlink() or not lock.is_dir() or {p.name for p in lock.iterdir()} != {"owner.json"}:
            raise EvidenceError("catalog lock ownership is incomplete; inspect without removing: " + str(lock))
        owner = read_json(lock / "owner.json", 4096)
        if owner.get("host") != socket.gethostname() or owner.get("coordinator") != self.coordinator:
            raise EvidenceError("catalog lock belongs to another host/coordinator; retained")
        if self._owner_alive(owner.get("pid")):
            raise EvidenceError("catalog coordinator process is still running; retained")
        action = {"action": "reconcile-exited-catalog-lock", "path": str(lock), "dry_run": dry_run}
        if not dry_run:
            atomic_json(self.state / "lock-reconciliation.json", {"version": 1, "owner": owner, "verified_exited": True})
            if read_json(lock / "owner.json", 4096) != owner or self._owner_alive(owner["pid"]):
                raise EvidenceError("catalog lock changed during reconciliation; retained")
            self._release_owner_file(lock / "owner.json")
            lock.rmdir()
            if lock.exists():
                raise EvidenceError("catalog lock removal failed")
            action["verified"] = True
        return [action]

    def _usage(self, *, include_ledger=True, include_checkpoints=True):
        """Account all local capture/cache/staging/readback/restoration, without following links."""
        count = 0
        for directory, dirs, files in os.walk(self.state, followlinks=False):
            for name in dirs + files:
                path = Path(directory) / name
                if not include_ledger and (path.name.startswith("accounting.sqlite") or (self.state / "accounting.sqlite.recovery") in path.parents):
                    continue
                checkpoint_root = self._checkpoint_root()
                if not include_checkpoints and checkpoint_root is not None and (path == checkpoint_root or checkpoint_root in path.parents):
                    continue
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue  # A managed sibling completed its reserved temporary work.
                if stat.S_ISLNK(info.st_mode):
                    raise EvidenceError("unregistered link in evidence workspace: " + str(path))
                if stat.S_ISREG(info.st_mode):
                    count += info.st_size
                elif not stat.S_ISDIR(info.st_mode):
                    raise EvidenceError("special file in evidence workspace")
        count += self._existing_bytes(self._transport_records())
        checkpoint_root = self._checkpoint_root()
        if include_checkpoints and checkpoint_root is not None and self.state not in checkpoint_root.parents and checkpoint_root != self.state:
            count += self._existing_bytes(self._checkpoint_records())
        return count

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

    def _checkpoint_allocations(self, ledger):
        if self._checkpoint_root() is None:
            return
        records = self._checkpoint_records()
        metadata = [path for path in records if path.suffix == ".json"]
        ledger.reconcile_local("transport-checkpoints", self._existing_bytes(records), "staging")
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
                result = ledger.finish_working(ident, local_key="transport-checkpoints",
                    actual_bytes=self._existing_bytes(records), kind="staging", metadata_key="transport-checkpoints",
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
        cache_bytes = self._existing_bytes(p for p in (self.cache / "objects").glob("*") if p.is_file())
        ledger.reconcile_local("cache", cache_bytes, "cache")
        ledger.reconcile_local("manager-working", max(0, self._usage(include_ledger=False, include_checkpoints=False) - cache_bytes), "staging")
        records = self._metadata_records(include_checkpoints=False)
        ledger.reconcile_metadata("local-journals-receipts", self._existing_bytes(p for p in records), len(records))
        self._checkpoint_allocations(ledger)

    def _metadata_records(self, *, include_checkpoints=True):
        recovery = self.state / "accounting.sqlite.recovery"
        checkpoint_root = self._checkpoint_root()
        records = [p for p in self.state.rglob("*.json")
                if p.is_file() and not p.is_symlink() and recovery not in p.parents
                and (checkpoint_root is None or checkpoint_root not in p.parents)] + [
                p for p in self._transport_records() if p.suffix == ".json"]
        if include_checkpoints:
            records += [p for p in self._checkpoint_records() if p.suffix == ".json"]
        return records

    @contextmanager
    def _working(self, peak, *, migration=False, metadata_bytes=0, metadata_files=0, cache_bytes=0,
                 additional_peak=False, capacity_path=None, transport_scope=False):
        with self.locked():
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
                    cache = self._existing_bytes(p for p in (self.cache / "objects").glob("*") if p.is_file())
                    records = self._metadata_records(include_checkpoints=False)
                    allocations = {"metadata_key": "local-journals-receipts", "actual_metadata_bytes": self._existing_bytes(p for p in records),
                        "actual_metadata_files": len(records)}
                    if nested and additional_peak and not (metadata_bytes or metadata_files):
                        allocations = {}  # The enclosing operation owns persistent control metadata.
                    if not nested:
                        allocations.update(local_key="manager-working", actual_bytes=max(0, self._usage(include_ledger=False, include_checkpoints=False) - cache),
                            kind="staging", cache_key="cache", actual_cache_bytes=cache)
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

    def _transport_call(self, method, *args, **kwargs):
        """Reserve durable transfer checkpoints separately from host queue peaks."""
        if method == "put" and self._checkpoint_root() is not None:
            with self._checkpoint_working(Path(args[1]).stat().st_size):
                return self._transport_host_call(method, *args, **kwargs)
        return self._transport_host_call(method, *args, **kwargs)

    def _transport_host_call(self, method, *args, **kwargs):
        """Reserve private host queues and materialized originals outside this state."""
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
        self._capacity(size)
        with self._working(size), tempfile.TemporaryDirectory(dir=self.staging, prefix="index-") as temp:
            target = Path(temp).resolve() / "data.json"
            self._transport_call("get", locator, target, size)
            return read_json(target, maximum), hash_file(target)

    def _catalog(self, *, mutation=False, recover_policy=False):
        with self.locked():
            return self._catalog_locked(mutation=mutation, recover_policy=recover_policy)

    def _catalog_locked(self, *, mutation=False, recover_policy=False):
        roots = self._transport_call("keys", self.prefix + "roots/")
        authorities = self._transport_call("keys", self.prefix + "authority/")
        authority_bytes = sum(self._transport_call("stat", item)["size"] for item in authorities)
        authority = self._generation_authority() if authorities else None
        if mutation and authority is not None and authority["coordinator"] != self.coordinator:
            raise EvidenceError("this client lacks designated coordinator authority; cold recovery is read-only")
        if len(roots) + len(authorities) > self.limits["metadata_stop_files"] or authority_bytes > self.limits["metadata_stop_bytes"]:
            raise EvidenceError("combined catalog object count exhausted")
        if not roots:
            return {"version": 1, "project_id": self.policy["project_id"], "store_id": self.policy["store_id"],
                    "sequence": 0, "coordinator": authority["coordinator"] if authority else self.coordinator, "segments": [], "refs": {}, "packs": {},
                    "generation": {}, "generation_intents": {}, "reference_aliases": {}, "import_retention_decisions": {}, "root_key": None, "metadata_bytes": authority_bytes, "metadata_files": len(authorities), "unreconciled_packs": self._unreconciled_packs({})}
        keys = sorted((x if isinstance(x, str) else x["key"]) for x in roots)
        latest = keys[-1]
        root, (digest, size) = self._read_remote_json(latest, self.limits["metadata_stop_bytes"])
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
        if not isinstance(root.get("segments"), list) or len(root["segments"]) > self.limits["metadata_stop_files"]:
            raise EvidenceError("invalid catalog segment closure")
        total = authority_bytes
        indexes = self._transport_call("keys", self.prefix + "indexes/")
        index_keys = {(x if isinstance(x, str) else x["key"]) for x in indexes}
        # Old roots count too: splitting or retaining checkpoints cannot evade metadata limits.
        for key in keys:
            total += int(self._transport_call("stat", key)["size"])
        for key in index_keys:
            total += int(self._transport_call("stat", key)["size"])
        refs, packs, generation, pending_deletions, retired_refs, import_retention_decisions = {}, {}, {}, {}, {}, {}
        generation_intents, reference_aliases = {}, {}
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
                        or set(intent) != {"run_id", "unit_id", "reserve_bytes", "reserve_files", "owner_pid", "owner_host"}
                        or any(not isinstance(intent[field], str) or not intent[field] for field in ("run_id", "unit_id"))
                        or any(type(intent[field]) is not int or intent[field] < 0 for field in ("reserve_bytes", "reserve_files"))
                        or type(intent["owner_pid"]) is not int or intent["owner_pid"] <= 0
                        or not isinstance(intent["owner_host"], str) or not intent["owner_host"]
                        or ident in generation_intents):
                    raise EvidenceError("invalid or duplicated durable generation intent")
                generation_intents[ident] = intent
            for ident in data.get("settled_generation_intents", []):
                if ident not in generation_intents:
                    raise EvidenceError("durable generation settlement lacks its original intent")
                generation_intents[ident] = {**generation_intents[ident], "settled": True}
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
        root.update(refs=refs, packs=packs, unreconciled_packs=self._unreconciled_packs(packs), generation=generation, generation_intents=generation_intents, reference_aliases=reference_aliases, pending_deletions=pending_deletions, retired_refs=retired_refs, import_retention_decisions=import_retention_decisions, root_key=latest,
                    metadata_bytes=total, metadata_files=len(keys) + len(index_keys) + len(authorities))
        from .accounting import Accounting
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
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
        ledger.reconcile_metadata("remote-catalog", catalog["metadata_bytes"], catalog["metadata_files"])
        records = self._metadata_records(include_checkpoints=False)
        ledger.reconcile_metadata("local-journals-receipts", self._existing_bytes(p for p in records), len(records))
        self._checkpoint_allocations(ledger)
        cache_bytes = self._existing_bytes(p for p in (self.cache / "objects").glob("*") if p.is_file())
        ledger.reconcile_local("cache", cache_bytes, "cache")
        ledger.reconcile_local("manager-working", max(0, self._usage(include_ledger=False, include_checkpoints=False) - cache_bytes), "staging")
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

    def _publish(self, catalog, segment):
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
            # A content identity in metadata is insufficient; verify reused original bytes now.
            reuse = {entry["sha256"] for entry in logical} & set(existing)
            if reuse:
                self.prepare([next(r for r in catalog["refs"].values() if r["sha256"] == digest) for digest in reuse])
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
            self.prepare([ref for entry, ref in zip(intent["entries"], refs) if not entry["done"]])
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

    def prepare(self, refs, *, catalog=None):
        """Reuse one verified shared pack within this invocation, then remove staging."""
        self._session_pack = None
        try:
            with tempfile.TemporaryDirectory(dir=self.staging, prefix="verified-pack-") as temp:
                self._session_path = Path(temp).resolve()
                return self._prepare(refs, catalog=catalog)
        finally:
            self._preparing.clear()
            self._session_pack = None
            from .accounting import Accounting
            with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
                self._local_records(ledger)

    def _prepare(self, refs, *, catalog=None):
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
                self._prepare([dependency], catalog=catalog)
            locator = ref["locator"]
            segments = locator.get("segments") or [{**locator, "offset": 0, "length": ref["size"], "sha256": ref["sha256"]}]
            packs = []
            for seg in segments:
                pack = catalog["packs"].get(seg["pack_sha256"])
                if pack is None or pack["locator"]["object_id"] != seg["object_id"] or pack["size"] != seg["pack_size"]:
                    raise EvidenceError("archive object identity closure mismatch")
                packs.append(pack)
            if self._session_pack is not None and any(pack["sha256"] != self._session_pack["sha256"] for pack in packs):
                shutil.rmtree(self._session_path / "members")
                self._session_pack = None
            peak = ref["size"] + max((pack["size"] + pack["original_bytes"] for pack in packs
                if self._session_pack is None or pack["sha256"] != self._session_pack["sha256"]), default=0)
            self._capacity(peak)
            cache_bytes = self._existing_bytes(p for p in objects.iterdir() if p.is_file())
            if cache_bytes + (0 if (objects / ref["sha256"]).exists() else ref["size"]) > self.limits["cache_stop_bytes"]:
                raise EvidenceError("bounded evidence cache full; explicitly evict replaceable cache bytes")
            proofs, offset = [], 0
            receipt_peak = (local_json_size(ref) + local_json_size(aliases) + len(segments) * 1024 + 4096) * 2
            with self._working(peak + receipt_peak, metadata_bytes=receipt_peak, metadata_files=0 if (receipts / (ref["artifact_id"] + ".json")).exists() else 1,
                cache_bytes=0 if (objects / ref["sha256"]).exists() else ref["size"]), tempfile.TemporaryDirectory(dir=self.staging, prefix="prepare-") as temp:
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
                target = objects / ref["sha256"]
                if target.is_symlink():
                    raise EvidenceError("linked cache object")
                whole.replace(target)
                receipt = {**ref, "verified_archive": proofs}
                if aliases:
                    receipt["original_references"] = aliases
                atomic_json(receipts / (ref["artifact_id"] + ".json"), receipt)
            if ref["schema"] not in ("evidence-bytes-v1", "archive-attachment-v1"):
                value = read_json(target, min(JSON_LIMIT, self.limits["metadata_stop_bytes"]))
                for nested in payload_references(value, ref["schema"]):
                    self._prepare([nested], catalog=catalog)
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
                result = ledger.finish_working(reservation, local_key=key, actual_bytes=old_bytes + actual, kind="restore")
            if result["incomplete"]:
                raise EvidenceError("restoration resource settlement incomplete: " + "; ".join(result["violations"]))
        return restored

    def _generation_authority(self):
        key = self.prefix + "authority/coordinator.json"
        entries = self._transport_call("keys", self.prefix + "authority/")
        if not entries:
            return None
        if len(entries) != 1 or (entries[0] if isinstance(entries[0], str) else entries[0]["key"]) != key:
            raise EvidenceError("ambiguous generation coordinator authority; reconciliation required")
        value, _ = self._read_remote_json(key, 4096)
        if (not isinstance(value, dict) or value.get("version") != 1
                or value.get("project_id") != self.policy["project_id"]
                or value.get("store_id") != self.policy["store_id"]
                or not isinstance(value.get("coordinator"), str)):
            raise EvidenceError("invalid generation coordinator authority")
        return value

    def initialize_generation_authority(self):
        """Explicit setup selects one coordinator; another home cannot take it over."""
        with self.locked():
            catalog = self._catalog(mutation=True)
            value = self._generation_authority()
            expected = {"version": 1, "project_id": self.policy["project_id"],
                        "store_id": self.policy["store_id"], "coordinator": self.coordinator}
            if value is None:
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
            return {"coordinator_authorized": True, "coordinator": self.coordinator,
                    "project_id": self.policy["project_id"]}

    def assert_generation_authority(self):
        """Read-only clients cannot reserve an independent generation allowance."""
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
        from .accounting import Accounting
        with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
            self._reconcile_ledger(catalog, ledger)
            ledger.require_generation_ready()
            for intent in catalog.get("generation_intents", {}).values():
                if not intent.get("settled") and ledger.connection.execute("SELECT 1 FROM runs WHERE id=?", (intent["run_id"],)).fetchone() is None:
                    launching = intent["owner_host"] == socket.gethostname() and self._owner_alive(intent["owner_pid"])
                    if not launching:
                        raise EvidenceError("durable generation intent has unknown local accounting; reconcile before generation")
        return {"coordinator_authorized": True, "coordinator": self.coordinator}

    @staticmethod
    def _run_generation(run):
        record = {"gross_bytes": run["gross_bytes"], "logical_files": run["gross_files"],
                  "run_id": run["id"], "unit_id": run["unit_id"], "mode": "managed-run-total"}
        return {"managed-run:" + hashlib.sha256(canonical(record)).hexdigest(): record}

    def begin_generation(self, run_id, unit_id, reserve_bytes, reserve_files):
        """Record an incomplete durable intent before any managed producer starts."""
        self.assert_generation_authority()
        if (any(not isinstance(value, str) or not value for value in (run_id, unit_id))
                or any(type(value) is not int or value < 0 for value in (reserve_bytes, reserve_files))):
            raise EvidenceError("generation intent requires stable run/unit and nonnegative reservation bounds")
        intent = str(uuid.uuid4())
        with self.locked():
            catalog = self._catalog(mutation=True)
            self._publish(catalog, {"version": 1, "generation_intents": {intent: {
                "run_id": run_id, "unit_id": unit_id, "reserve_bytes": reserve_bytes, "reserve_files": reserve_files,
                "owner_pid": os.getpid(), "owner_host": socket.gethostname()}}})
        return intent

    def finish_generation(self, intent_id, reservation_id=None):
        """Publish settled success/failure charges without requiring a payload archive."""
        from .accounting import Accounting
        with self.locked():
            catalog = self._catalog(mutation=True)
            intent = catalog.get("generation_intents", {}).get(intent_id)
            if intent is None:
                raise EvidenceError("generation settlement requires its original durable intent")
            if intent.get("settled"):
                return {"settled": True, "intent_id": intent_id}
            if intent["owner_host"] != socket.gethostname() or (intent["owner_pid"] != os.getpid() and self._owner_alive(intent["owner_pid"])):
                raise EvidenceError("generation intent owner/helper exit cannot be verified; intent retained")
            with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
                snapshot = ledger.snapshot()
                run = ledger.connection.execute("SELECT * FROM runs WHERE id=?", (intent["run_id"],)).fetchone()
                pending = ledger.connection.execute("SELECT COUNT(*) FROM reservations WHERE run_id=? AND state='pending'", (intent["run_id"],)).fetchone()[0]
                if not snapshot.get("accounting_complete", True):
                    raise EvidenceError("generation accounting remains incomplete; durable intent retained for reconciliation")
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
        """Resume individually registered deletion intents, never discover disposable paths."""
        actions = self._reconcile_lock(dry_run)
        if dry_run and (self.state / "catalog.lock").exists():
            return actions  # A retained stale lock must be reconciled before catalog work.
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
        for ident, intent in catalog.get("generation_intents", {}).items():
            if intent.get("settled"):
                continue
            own_catalog = catalog["coordinator"] == self.coordinator
            exited = intent["owner_host"] == socket.gethostname() and not self._owner_alive(intent["owner_pid"])
            action = {"action": "generation-intent-retained", "intent_id": ident, "incomplete": True,
                      "reason": "designated coordinator or owning process exit is not verified"}
            if own_catalog and exited:
                with Accounting(self.state / "accounting.sqlite", self.policy["project_id"], self.policy) as ledger:
                    known = ledger.snapshot().get("accounting_complete", True)
                    pending = ledger.connection.execute("SELECT COUNT(*) FROM reservations WHERE run_id=? AND state='pending'", (intent["run_id"],)).fetchone()[0]
                if known and not pending:
                    action = {"action": "reconcile-exited-generation-intent", "intent_id": ident, "dry_run": dry_run}
                    if not dry_run:
                        self.finish_generation(ident)
                        action["verified"] = True
                else:
                    action["reason"] = "local accounting or producer reservations remain incomplete"
            actions.append(action)
        return actions

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
                    path = self.cache / "objects" / ref["sha256"]
                    if path.exists() or path.is_symlink():
                        # Cache is replaceable only after independently reading the durable copy now.
                        if not dry_run:
                            self.prepare([ref])
                            hash_file(path)
                            path.unlink()
                            if path.exists() or path.is_symlink():
                                raise EvidenceError("cache deletion failed: " + str(path))
                        results.append({"artifact_id": ref["artifact_id"], "action": "evict-cache", "dry_run": dry_run})
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
                        path = self.cache / "objects" / ref["sha256"]
                        if path.exists() or path.is_symlink():
                            self.prepare([ref])
                            if hash_file(path) != (ref["sha256"], ref["size"]):
                                raise EvidenceError("cache changed before final eviction")
                            path.unlink()
                            if path.exists() or path.is_symlink():
                                raise EvidenceError("final cache eviction failed: " + str(path))
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
