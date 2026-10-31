"""Original-byte evidence transports. Cloud dependencies are optional and external.

Objects are immutable. Upload checkpoints are deliberately conservative: an
unacknowledged upload is looked up again, never blindly uploaded a second time.
The evidence manager independently verifies downloaded pack and member hashes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import errno
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat as file_stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata

from .io import (EvidenceError, _is_link, _open_regular, _parents, _unique_pairs, _verify_stable,
                 atomic_json, hash_file, read_json, safe_relative)

MAX_LOCATOR_STRING_BYTES = 4096


def _locator_string(value, label):
    if not isinstance(value, str) or not value or any(unicodedata.category(char) == "Cc" for char in value):
        raise EvidenceError(label + " must be a nonempty string without control characters")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise EvidenceError(label + " must be valid UTF-8") from exc
    if size > MAX_LOCATOR_STRING_BYTES:
        raise EvidenceError(label + " exceeds 4096 UTF-8 bytes")
    return value


def _transport_key(value):
    return safe_relative(_locator_string(value, "object key"))


def _positive(value, name, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if zero else 1):
        raise EvidenceError(name + " must be " + ("nonnegative" if zero else "positive"))
    return value


def _directory(path, *, create=False):
    """Inspect every directory component without accepting symlink aliases."""
    path = Path(os.path.abspath(os.fspath(path)))
    for item in [*reversed(path.parents), path]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            if not create:
                raise EvidenceError("directory is missing: " + str(item))
            item.mkdir(mode=0o700)
            info = item.lstat()
        if not file_stat.S_ISDIR(info.st_mode) or _is_link(info):
            raise EvidenceError("linked or non-directory storage path: " + str(item))
    return path


def _outside_git(path):
    for item in [path, *path.parents]:
        if (item / ".git").exists() or (item / ".git").is_symlink():
            raise EvidenceError("evidence storage and transfer state must be outside Git")


def _destination(path):
    path = Path(os.path.abspath(os.fspath(path)))
    _parents(path)
    if path.exists() or path.is_symlink():
        if _is_link(path.lstat()) or not file_stat.S_ISREG(path.lstat().st_mode):
            raise EvidenceError("download destination must be a regular file")
    return path


def _metadata(value, key=None):
    if not isinstance(value, dict):
        raise EvidenceError("transport metadata must be an object")
    identity = value.get("object_id")
    identity = _locator_string(identity, "stable object_id")
    actual_key = _transport_key(value.get("key", key))
    if key is not None and actual_key != key:
        raise EvidenceError("transport metadata key does not match requested key")
    result = {"object_id": identity, "key": actual_key,
              "size": _positive(value.get("size"), "object size", zero=True)}
    if "sha256" in value:
        digest = value["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise EvidenceError("invalid transport sha256 metadata")
        result["sha256"] = digest
    return result


def _key(value):
    return _transport_key(value["key"] if isinstance(value, dict) else value)


def _json_response(raw, label):
    try:
        return json.loads(raw, object_pairs_hook=_unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(EvidenceError("non-finite JSON value")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(label + " returned invalid JSON") from exc


class Transport(ABC):
    @abstractmethod
    def put(self, key, source_path): ...

    @abstractmethod
    def stat(self, locator_or_key): ...

    @abstractmethod
    def get(self, locator, destination_path, max_bytes): ...

    @abstractmethod
    def delete(self, locator): ...

    @abstractmethod
    def keys(self, prefix=""): ...


class LocalTransport(Transport):
    """A durable selected folder; this is never implicitly disposable cache."""
    def __init__(self, root, *, max_objects=100_000):
        candidate = Path(os.path.abspath(os.fspath(root)))
        _outside_git(candidate)
        self.root = _directory(candidate, create=True)
        self.max_objects = _positive(max_objects, "max_objects")

    def _path(self, key, *, create=False):
        path = self.root.joinpath(*_transport_key(key).split("/"))
        _directory(path.parent, create=create)
        for parent in [path.parent, *path.parent.parents]:
            if parent == self.root:
                break
            if parent.stat().st_dev != self.root.stat().st_dev:
                raise EvidenceError("mounted directory inside durable evidence store")
        if path.exists() or path.is_symlink():
            if _is_link(path.lstat()) or not file_stat.S_ISREG(path.lstat().st_mode):
                raise EvidenceError("local object is not a regular file")
        return path

    def stat(self, locator_or_key):
        key = _key(locator_or_key)
        if isinstance(locator_or_key, dict) and locator_or_key.get("object_id") != key:
            raise EvidenceError("local object identity does not match key")
        path = self._path(key)
        if not path.exists():
            raise EvidenceError("evidence object is missing: " + key)
        path, fd, before = _open_regular(path)
        try:
            _verify_stable(path, fd, before)
            return {"object_id": key, "key": key, "size": before.st_size}
        finally:
            os.close(fd)

    def put(self, key, source_path):
        key = _transport_key(key)
        digest, size = hash_file(source_path)
        path = self._path(key, create=True)
        if path.exists():
            if hash_file(path) != (digest, size):
                raise EvidenceError("immutable storage key has different bytes: " + key)
            return self.stat(key)
        descriptor, temporary = tempfile.mkstemp(prefix=".transfer-", dir=path.parent)
        try:
            self._copy(source_path, descriptor, size)
            os.close(descriptor)
            descriptor = None
            if hash_file(temporary) != (digest, size):
                raise EvidenceError("upload source changed during capture")
            _directory(path.parent)
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                if hash_file(path) != (digest, size):
                    raise EvidenceError("immutable storage key was concurrently replaced")
            except OSError as exc:
                if exc.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV):
                    raise
                # FAT/exFAT selected disks lack hardlinks. Managed catalog writes
                # already have one coordinator; atomic rename retains pack bytes.
                # An outside producer can bypass coordination and is unsupported.
                if path.exists() or path.is_symlink():
                    if hash_file(path) != (digest, size):
                        raise EvidenceError("immutable storage key was concurrently replaced")
                else:
                    _directory(path.parent)
                    os.replace(temporary, path)
            return self.stat(key)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def _copy(source, destination_fd, max_bytes):
        source, source_fd, before = _open_regular(source)
        try:
            if before.st_size > max_bytes:
                raise EvidenceError("object exceeds download byte bound")
            count = 0
            while True:
                block = os.read(source_fd, min(1024 * 1024, max_bytes + 1 - count))
                if not block:
                    break
                count += len(block)
                if count > max_bytes:
                    raise EvidenceError("object exceeds download byte bound")
                offset = 0
                while offset < len(block):
                    offset += os.write(destination_fd, block[offset:])
            _verify_stable(source, source_fd, before)
            if count != before.st_size:
                raise EvidenceError("object length changed during download")
            os.fsync(destination_fd)
        finally:
            os.close(source_fd)

    def get(self, locator, destination_path, max_bytes):
        max_bytes = _positive(max_bytes, "max_bytes", zero=True)
        info = self.stat(locator)
        if info["size"] > max_bytes:
            raise EvidenceError("object exceeds download byte bound")
        target = _destination(destination_path)
        if target == self.root or self.root in target.parents:
            raise EvidenceError("independent readback destination must be outside durable store")
        descriptor, temporary = tempfile.mkstemp(prefix=".readback-", dir=target.parent)
        try:
            self._copy(self._path(info["key"]), descriptor, max_bytes)
            os.close(descriptor)
            descriptor = None
            if hash_file(temporary)[1] != info["size"]:
                raise EvidenceError("download metadata size mismatch")
            _destination(target)
            os.replace(temporary, target)
            return target
        finally:
            if descriptor is not None:
                os.close(descriptor)
            Path(temporary).unlink(missing_ok=True)

    def delete(self, locator):
        key = _key(locator)
        path = self._path(key)
        if not path.exists():
            return
        self.stat(locator)
        path.unlink()
        if path.exists() or path.is_symlink():
            raise EvidenceError("local deletion did not remove object: " + key)

    def keys(self, prefix=""):
        if prefix:
            safe_relative(prefix.rstrip("/"))
        _directory(self.root)
        root_device = self.root.stat().st_dev
        result, observed = [], 0
        for base, dirs, files in os.walk(self.root, followlinks=False):
            for name in dirs:
                info = (Path(base) / name).lstat()
                if _is_link(info) or not file_stat.S_ISDIR(info.st_mode) or info.st_dev != root_device:
                    raise EvidenceError("linked or mounted directory in local evidence store")
            for name in files:
                path = Path(base) / name
                if name.startswith(".transfer-"):
                    continue
                if _is_link(path.lstat()) or not file_stat.S_ISREG(path.lstat().st_mode):
                    raise EvidenceError("unsafe file in local evidence store")
                key = _transport_key(path.relative_to(self.root).as_posix())
                observed += 1
                if key.startswith(prefix):
                    result.append(key)
                if observed > self.max_objects:
                    raise EvidenceError("object listing exceeds configured object bound")
        return sorted(result)


def _stop_owned_process(process):
    """Reap this Popen child; group denial must not prevent direct cleanup."""
    if process.poll() is None:
        group_stopped = False
        if os.name == "posix":
            try:
                # start_new_session made this child its group leader. Never
                # signal a different group if a host command changed groups.
                if os.getpgid(process.pid) == process.pid:
                    os.killpg(process.pid, signal.SIGKILL)
                    group_stopped = True
            except OSError:
                # Exit races and denied group signals both fall back to the
                # exact child owned by this Popen object, without guessing IDs.
                pass
        if not group_stopped and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired as exc:
                raise EvidenceError("owned transport helper could not be reaped: PID " + str(process.pid)) from exc
    else:
        process.wait()


def _run_command(command, *, payload=None, timeout_seconds=120,
                 max_output_bytes=16 * 1024 * 1024, output_path=None, max_file_bytes=None):
    """Bound process time, captured output, and an optional download file.

    Errors intentionally never include subprocess output: a host/rclone error can
    contain OAuth tokens. The task owns this single process and reaps it on error.
    """
    _positive(timeout_seconds, "timeout_seconds")
    _positive(max_output_bytes, "max_output_bytes")
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process, writer = None, None
        write_errors = []
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, start_new_session=os.name == "posix")
            deadline = time.monotonic() + timeout_seconds
            if payload is not None:
                def send_request():
                    try:
                        process.stdin.write(payload)
                        process.stdin.close()
                    except (OSError, ValueError):
                        write_errors.append(True)
                        try:
                            process.stdin.close()
                        except (OSError, ValueError):
                            pass
                # A host that ignores stdin cannot block the monitoring thread
                # before timeout or output/download bounds are enforced.
                writer = threading.Thread(target=send_request, name="sdd-transport-input", daemon=True)
                writer.start()
            while process.poll() is None:
                if write_errors:
                    raise EvidenceError("transport command could not receive the complete request")
                if time.monotonic() >= deadline:
                    raise EvidenceError("transport command timed out; outcome may be unknown")
                if stdout.tell() + stderr.tell() > max_output_bytes:
                    raise EvidenceError("transport command output exceeds metadata bound")
                if output_path is not None and Path(output_path).exists():
                    if Path(output_path).lstat().st_size > max_file_bytes:
                        raise EvidenceError("download exceeds configured byte bound")
                time.sleep(0.01)
            if stdout.tell() + stderr.tell() > max_output_bytes:
                raise EvidenceError("transport command output exceeds metadata bound")
            if writer is not None:
                writer.join(timeout=5)
                if writer.is_alive() or write_errors:
                    raise EvidenceError("transport command could not receive the complete request")
            stdout.seek(0)
            result = stdout.read(max_output_bytes + 1)
            return process.returncode, result
        except FileNotFoundError as exc:
            raise EvidenceError("transport executable is missing; install the optional tool or configure the host bridge") from exc
        finally:
            original_error = sys.exception()
            cleanup_error = None
            if process is not None:
                try:
                    _stop_owned_process(process)
                except (OSError, EvidenceError) as exc:
                    cleanup_error = "owned transport process cleanup failed: PID " + str(process.pid) + " (" + type(exc).__name__ + ")"
            if writer is not None:
                writer.join(timeout=5)
                if writer.is_alive():
                    cleanup_error = "owned transport input writer did not stop after process cleanup"
            if process is not None and process.stdin is not None and (writer is None or not writer.is_alive()):
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            if cleanup_error:
                if original_error is not None:
                    raise EvidenceError(str(original_error) + "; " + cleanup_error) from original_error
                raise EvidenceError(cleanup_error)


class JsonCommandAdapter:
    """A host-owned one-request JSON stdin/stdout bridge; no shell invocation."""
    def __init__(self, command, *, timeout_seconds=120, max_metadata_bytes=16 * 1024 * 1024):
        if not isinstance(command, (list, tuple)) or not command or not all(isinstance(x, str) and x for x in command):
            raise EvidenceError("bridge_command must be a nonempty argument array")
        self.command = list(command)
        self.timeout_seconds = _positive(timeout_seconds, "timeout_seconds")
        self.max_metadata_bytes = _positive(max_metadata_bytes, "max_metadata_bytes")

    def __call__(self, request):
        code, raw = _run_command(self.command, payload=json.dumps(request, allow_nan=False).encode("utf-8"),
                                 timeout_seconds=self.timeout_seconds,
                                 max_output_bytes=self.max_metadata_bytes,
                                 output_path=request.get("destination_path"),
                                 max_file_bytes=request.get("max_bytes"))
        if code:
            raise EvidenceError("connected Drive bridge failed (exit " + str(code) + "); inspect host capabilities and authentication")
        result = _json_response(raw, "connected Drive bridge")
        if not isinstance(result, dict):
            raise EvidenceError("connected Drive bridge must return a JSON object")
        return result


class _CheckpointedDrive(Transport):
    # Atomic replacement can coexist with the old checkpoint. Managers reserve
    # this peak before every put, including immutable-object retry readbacks.
    checkpoint_peak_bytes = 128 * 1024
    checkpoint_metadata_bytes = 64 * 1024
    checkpoint_metadata_files = 1

    def _write_checkpoint(self, path, record):
        try:
            # Match atomic_json's on-disk representation, including escaping,
            # indentation and the trailing newline; compact JSON undercounts.
            encoded = (json.dumps(record, sort_keys=True, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError) as error:
            raise EvidenceError("upload checkpoint is not valid bounded JSON") from error
        if len(encoded) > self.checkpoint_metadata_bytes:
            raise EvidenceError("upload checkpoint exceeds the reserved metadata byte bound")
        atomic_json(path, record)

    def _initialize(self, identity, state_dir, attempts, max_metadata_bytes, max_objects):
        self.attempts = _positive(attempts, "attempts")
        self.max_metadata_bytes = _positive(max_metadata_bytes, "max_metadata_bytes")
        self.max_objects = _positive(max_objects, "max_objects")
        candidate = Path(state_dir) if state_dir is not None else Path.home() / ".sdd-pipeline" / "evidence" / "transfers"
        candidate = Path(os.path.abspath(candidate))
        _outside_git(candidate)
        self.state_dir = _directory(candidate, create=True)
        self.identity = identity

    def _checkpoint(self, key):
        name = hashlib.sha256((self.identity + "\0" + key).encode()).hexdigest() + ".json"
        return self.state_dir / name

    def _find_retry(self, key):
        for attempt in range(self.attempts):
            found = self._lookup(key)
            if found:
                return found
        return None

    def _same(self, metadata, digest, size):
        if metadata["size"] != size:
            raise EvidenceError("immutable storage key has different size")
        with tempfile.TemporaryDirectory(prefix="sdd-existing-", dir=self.state_dir) as folder:
            target = Path(folder) / "original"
            self.get(metadata, target, size)
            if hash_file(target) != (digest, size):
                raise EvidenceError("immutable storage key has different original bytes")
        return metadata

    def _unknown_upload(self, key):
        return ("unknown upload outcome for immutable key " + json.dumps(key) +
                ": pending checkpoint retained; resume lookup without reupload, or explicitly acknowledge this key "
                "with evidence_store.py acknowledge-missing-upload --key / evidence_setup.py configure "
                "--acknowledge-missing-upload after checking the selected destination")

    def put(self, key, source_path):
        key = _transport_key(key)
        digest, size = hash_file(source_path)
        checkpoint = self._checkpoint(key)
        if checkpoint.exists():
            record = read_json(checkpoint, self.checkpoint_metadata_bytes)
            if (not isinstance(record, dict) or record.get("version") != 1 or record.get("key") != key
                    or record.get("sha256") != digest or record.get("size") != size):
                raise EvidenceError("upload checkpoint conflicts with immutable input")
        else:
            record = None
        existing = self._find_retry(key) if record is not None else self._lookup(key)
        if existing:
            verified = self._same(existing, digest, size)
            self._write_checkpoint(checkpoint, {"version": 1, "key": key, "sha256": digest, "size": size,
                                     "state": "located", "locator": verified})
            return verified
        if record is not None:
            raise EvidenceError(self._unknown_upload(key))
        self._pre_upload(key)
        self._write_checkpoint(checkpoint, {"version": 1, "key": key, "sha256": digest, "size": size, "state": "pending"})
        try:
            self._upload(key, Path(source_path), digest, size)
        except Exception as exc:
            existing = self._find_retry(key)
            if existing:
                verified = self._same(existing, digest, size)
                self._write_checkpoint(checkpoint, {"version": 1, "key": key, "sha256": digest, "size": size,
                                         "state": "located", "locator": verified})
                return verified
            raise EvidenceError(self._unknown_upload(key)) from exc
        if hash_file(source_path) != (digest, size):
            raise EvidenceError("upload source changed; pending checkpoint retained")
        existing = self._find_retry(key)
        if existing is None:
            raise EvidenceError(self._unknown_upload(key) + "; completed response but object lookup missing")
        if existing["size"] != size:
            raise EvidenceError("uploaded object size mismatch; pending checkpoint retained")
        self._write_checkpoint(checkpoint, {"version": 1, "key": key, "sha256": digest, "size": size,
                                 "state": "located", "locator": existing})
        return existing

    def acknowledge_missing_upload(self, key):
        """Explicit recovery action after checking the selected remote destination."""
        key = _transport_key(key)
        checkpoint = self._checkpoint(key)
        if not checkpoint.exists():
            raise EvidenceError("no owned local upload checkpoint exists for immutable key " + json.dumps(key))
        fingerprint = hash_file(checkpoint)
        record = read_json(checkpoint, self.checkpoint_metadata_bytes)
        if (not isinstance(record, dict) or record.get("version") != 1 or record.get("key") != key
                or not isinstance(record.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
                or isinstance(record.get("size"), bool) or not isinstance(record.get("size"), int) or record["size"] < 0
                or record.get("state") not in ("pending", "located")):
            raise EvidenceError("owned local upload checkpoint is invalid or belongs to another immutable key")
        if self._find_retry(key) is not None:
            raise EvidenceError("upload object exists; resume the verified object instead")
        if record["state"] != "pending":
            raise EvidenceError("only a pending unknown-outcome upload can be acknowledged; previously located objects need recovery")
        if hash_file(checkpoint) != fingerprint:
            raise EvidenceError("upload checkpoint changed during acknowledgement; retained for reconciliation")
        checkpoint.unlink()

    def _pre_upload(self, key):
        return None


class ConnectedDriveTransport(_CheckpointedDrive):
    REQUIRED_CAPABILITIES = frozenset({"upload", "download_original", "metadata", "lookup", "list", "delete",
                                       "stable_object_id", "bounded_original_download"})

    @property
    def control_peak_bytes(self):
        return getattr(self.adapter, "control_peak_bytes", 0)

    @property
    def host_session_path(self):
        return getattr(self.adapter, "host_session_path", None)

    def working_overhead(self, *, upload_bytes=0, download_bytes=0):
        method = getattr(self.adapter, "working_overhead", None)
        return method(upload_bytes=upload_bytes, download_bytes=download_bytes) if method else 0

    def _pre_upload(self, key):
        method = getattr(self.adapter, "preflight_upload", None)
        if method:
            method(self.folder_id, key)

    def __init__(self, adapter, folder_id, *, state_dir=None, attempts=3,
                 max_metadata_bytes=16 * 1024 * 1024, max_objects=100_000):
        if not callable(adapter):
            raise EvidenceError("connected Drive requires an injected host adapter or JsonCommandAdapter")
        folder_id = _locator_string(folder_id, "Google Drive destination folder_id")
        self.adapter, self.folder_id = adapter, folder_id
        self._initialize("connected:" + folder_id, state_dir, attempts, max_metadata_bytes, max_objects)
        capabilities = self._call("capabilities")
        supplied = capabilities.get("capabilities", [])
        if capabilities.get("version") != 1 or capabilities.get("provider") != "google_drive" or not isinstance(supplied, list) or not all(isinstance(item, str) for item in supplied):
            raise EvidenceError("connected Drive host bridge must expose version 1 google_drive capabilities")
        missing = sorted(self.REQUIRED_CAPABILITIES - set(supplied))
        if missing:
            raise EvidenceError("connected Google Drive capabilities missing: " + ", ".join(missing) +
                                "; provide a host bridge exposing those operations, or explicitly configure optional rclone Drive")

    def _call(self, operation, **values):
        try:
            result = self.adapter({"version": 1, "operation": operation, "folder_id": self.folder_id, **values})
        except Exception as exc:
            if isinstance(exc, EvidenceError) and getattr(self.adapter, "safe_error_messages", False):
                raise
            raise EvidenceError("connected Drive " + operation + " failed; check selected account, permission and host bridge") from exc
        if not isinstance(result, dict):
            raise EvidenceError("connected Drive " + operation + " returned no JSON object")
        try:
            if len(json.dumps(result, allow_nan=False).encode()) > self.max_metadata_bytes:
                raise EvidenceError("connected Drive response exceeds metadata bound")
        except (ValueError, TypeError) as exc:
            raise EvidenceError("connected Drive response is invalid bounded JSON") from exc
        return result

    def _lookup(self, key):
        response = self._call("lookup", key=key)
        objects = response.get("objects")
        if not isinstance(objects, list):
            raise EvidenceError("connected Drive lookup must return objects")
        if len(objects) > 1:
            raise EvidenceError("duplicate Drive object identity for immutable key; reconciliation required")
        return _metadata(objects[0], key) if objects else None

    def _upload(self, key, source, digest, size):
        result = self._call("upload", key=key, source_path=str(source.absolute()), size=size, sha256=digest,
                            idempotency_key=hashlib.sha256((self.identity + "\0" + key).encode()).hexdigest())
        return _metadata(result, key)

    def stat(self, locator_or_key):
        if isinstance(locator_or_key, str):
            result = self._lookup(_transport_key(locator_or_key))
            if result is None:
                raise EvidenceError("Drive evidence object is missing")
            return result
        expected = _metadata(locator_or_key)
        result = _metadata(self._call("metadata", object_id=expected["object_id"], key=expected["key"]), expected["key"])
        if result["object_id"] != expected["object_id"]:
            raise EvidenceError("Drive object identity mismatch")
        return result

    def get(self, locator, destination_path, max_bytes):
        max_bytes = _positive(max_bytes, "max_bytes", zero=True)
        info = self.stat(locator)
        if info["size"] > max_bytes:
            raise EvidenceError("object exceeds download byte bound")
        target = _destination(destination_path)
        descriptor, temporary = tempfile.mkstemp(prefix=".drive-readback-", dir=target.parent)
        os.close(descriptor)
        try:
            result = self._call("download_original", object_id=info["object_id"], key=info["key"],
                                destination_path=temporary, max_bytes=max_bytes, bypass_cache=True)
            if result.get("original_bytes") is not True or result.get("object_id") != info["object_id"]:
                raise EvidenceError("Drive host must retrieve independent original bytes by stable object ID")
            actual_size = hash_file(temporary)[1]
            if actual_size > max_bytes or actual_size != info["size"] or result.get("size") != actual_size:
                raise EvidenceError("Drive download size mismatch or byte bound exceeded")
            _destination(target)
            os.replace(temporary, target)
            return target
        finally:
            Path(temporary).unlink(missing_ok=True)

    def delete(self, locator):
        info = _metadata(locator)
        result = self._call("delete", object_id=info["object_id"], key=info["key"])
        if result.get("deleted") is not True:
            raise EvidenceError("Drive host did not verify deletion")
        existing = self._lookup(info["key"])
        if existing is not None:
            raise EvidenceError("Drive deletion did not remove registered object")
        self._checkpoint(info["key"]).unlink(missing_ok=True)

    def inventory(self, prefix=""):
        """List fresh validated locators; callers still stat each original object."""
        if prefix:
            safe_relative(prefix.rstrip("/"))
        result, identities, seen_keys, tokens, page_token, total_bytes = [], set(), set(), set(), None, 0
        while True:
            response = self._call("list", prefix=prefix, page_token=page_token, max_objects=self.max_objects - len(result))
            total_bytes += max(len(json.dumps(response).encode()),
                               _positive(response.get("metadata_bytes", 0), "Drive listing metadata bytes", zero=True))
            objects = response.get("objects")
            if not isinstance(objects, list) or total_bytes > self.max_metadata_bytes:
                raise EvidenceError("Drive listing exceeds combined metadata bound or has invalid objects")
            for value in objects:
                item = _metadata(value)
                if not item["key"].startswith(prefix):
                    raise EvidenceError("Drive list returned a key outside requested prefix")
                if item["key"] in seen_keys or item["object_id"] in identities:
                    raise EvidenceError("duplicate Drive object identity in catalog listing")
                result.append(item)
                seen_keys.add(item["key"])
                identities.add(item["object_id"])
                if len(result) > self.max_objects:
                    raise EvidenceError("Drive object listing exceeds configured object bound")
            page_token = response.get("next_page_token")
            if page_token is None:
                break
            if not isinstance(page_token, str) or not page_token or page_token in tokens:
                raise EvidenceError("Drive list has invalid or repeated continuation token")
            tokens.add(page_token)
            if len(tokens) > self.max_objects:
                raise EvidenceError("Drive listing exceeds continuation page bound")
        return sorted(result, key=lambda item: item["key"])


    def keys(self, prefix=""):
        return [item["key"] for item in self.inventory(prefix)]

class RcloneDriveTransport(_CheckpointedDrive):
    """Optional standalone Google Drive binary-object transport, never a mount."""
    def __init__(self, remote, *, config=None, executable="rclone", state_dir=None,
                 timeout_seconds=120, attempts=3, max_metadata_bytes=16 * 1024 * 1024, max_objects=100_000):
        if not isinstance(remote, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*:.*", remote):
            raise EvidenceError("rclone Drive destination must be a configured remote:path")
        name, suffix = remote.split(":", 1)
        if suffix:
            safe_relative(suffix.rstrip("/"))
        self.remote = name + ":" + suffix.rstrip("/")
        self.backend = name + ":"
        self.executable = os.fspath(executable)
        self.timeout_seconds = _positive(timeout_seconds, "timeout_seconds")
        self.config = None
        if config is not None:
            candidate = Path(os.path.abspath(os.fspath(config)))
            _outside_git(candidate)
            if not candidate.exists():
                raise EvidenceError("rclone credentials missing: run rclone config with the external --config path and your own Google OAuth client")
            path, fd, _ = _open_regular(candidate)
            os.close(fd)
            self.config = path
        self._initialize("rclone:" + self.remote, state_dir, attempts, max_metadata_bytes, max_objects)

    def _remote_path(self, key=""):
        return self.remote + ("/" if not self.remote.endswith(":") and key else "") + key

    def _command(self, *args, output_path=None, max_bytes=None, missing_ok=False):
        command = [self.executable, *args, "--retries", "1", "--low-level-retries", str(self.attempts),
                   "--transfers", "1", "--checkers", "1", "--log-level", "ERROR",
                   "--timeout", str(min(self.timeout_seconds, 60)) + "s", "--contimeout", "15s",
                   "--drive-import-formats=", "--drive-export-formats="]
        if self.config is not None:
            command += ["--config", str(self.config)]
        code, raw = _run_command(command, timeout_seconds=self.timeout_seconds,
                                 max_output_bytes=self.max_metadata_bytes,
                                 output_path=output_path, max_file_bytes=max_bytes)
        if code and not (missing_ok and code in (3, 4)):
            raise EvidenceError("rclone " + str(args[0]) + " failed (exit " + str(code) +
                                "); verify optional rclone, Google Drive remote, external credentials and selected-folder permissions")
        return None if code else raw

    def _list(self, parent="", recursive=False):
        args = ["lsjson", self._remote_path(parent), "--files-only", "--no-modtime", "--no-mimetype"]
        if recursive:
            args += ["--recursive"]
        raw = self._command(*args, missing_ok=True)
        if raw is None:
            return []
        values = _json_response(raw, "rclone metadata")
        if not isinstance(values, list) or len(values) > self.max_objects or not all(isinstance(item, dict) for item in values):
            raise EvidenceError("rclone listing exceeds configured object bound or invalid schema")
        for item in values:
            _locator_string(item.get("Name"), "provider object name")
        return values

    def _lookup(self, key):
        key = _transport_key(key)
        parent = str(PurePosixPath(key).parent)
        parent = "" if parent == "." else parent
        matches = [item for item in self._list(parent) if item.get("Name") == PurePosixPath(key).name]
        if len(matches) > 1:
            raise EvidenceError("duplicate Drive object identity for immutable key; reconciliation required")
        if not matches:
            return None
        value = matches[0]
        return _metadata({"object_id": value.get("ID"), "key": key, "size": value.get("Size")})

    def _upload(self, key, source, digest, size):
        source = source.absolute()
        self._transfer("operations/copyfile", {"srcFs": str(source.parent), "srcRemote": source.name,
                                             "dstFs": self.remote, "dstRemote": key}, size,
                       immutable=True)
        # copyfile/copyto do not enforce Immutable on every transfer path.
        # IgnoreExisting preserves a raced existing object, while readback
        # proves that a skipped or newly uploaded object has the expected bytes.
        existing = self._find_retry(key)
        if existing is None:
            raise EvidenceError("uploaded object lookup missing; pending checkpoint retained")
        self._same(existing, digest, size)

    def _transfer(self, operation, parameters, max_bytes, *, immutable=False, output_path=None):
        # rclone v1.75.2 rounds SizeSuffix CLI flags to three decimal places:
        # 1048577B becomes 1Mi and rejects a valid exact-bound transfer. Numeric
        # per-call config preserves the integer. --loopback executes in this
        # foreground process; it neither starts nor contacts an RC HTTP server.
        # RC JSON numbers pass through float64, so reject inexact huge integers.
        if max_bytes > 2 ** 53 - 1:
            raise EvidenceError("rclone transfer byte bound exceeds exact JSON integer range")
        parameters = dict(parameters, _config={"MaxTransfer": max(1, max_bytes), "CutoffMode": "HARD",
                                               "CheckSum": True, "Immutable": immutable,
                                               "IgnoreExisting": immutable})
        return self._command("rc", "--loopback", operation, "--json", json.dumps(parameters),
                             "--rc=false", "--local-no-preallocate", output_path=output_path,
                             max_bytes=max_bytes if output_path is not None else None)

    def stat(self, locator_or_key):
        key = _key(locator_or_key)
        result = self._lookup(key)
        if result is None:
            raise EvidenceError("Drive evidence object is missing")
        if isinstance(locator_or_key, dict) and result["object_id"] != locator_or_key.get("object_id"):
            raise EvidenceError("Drive object identity mismatch")
        return result

    def get(self, locator, destination_path, max_bytes):
        max_bytes = _positive(max_bytes, "max_bytes", zero=True)
        info = self.stat(locator)
        if info["size"] > max_bytes:
            raise EvidenceError("object exceeds download byte bound")
        target = _destination(destination_path)
        descriptor, temporary = tempfile.mkstemp(prefix=".rclone-readback-", dir=target.parent)
        os.close(descriptor)
        try:
            self._transfer("backend/command", {"command": "copyid", "fs": self.backend,
                                                "arg": [info["object_id"], temporary]},
                           max_bytes, output_path=temporary)
            actual_size = hash_file(temporary)[1]
            if actual_size > max_bytes or actual_size != info["size"]:
                raise EvidenceError("rclone original download size mismatch or byte bound exceeded")
            _destination(target)
            os.replace(temporary, target)
            return target
        finally:
            Path(temporary).unlink(missing_ok=True)

    def delete(self, locator):
        key = _key(locator)
        info = self._lookup(key)
        if info is None:
            # A previous delete may have committed before its response or the
            # local pruning checkpoint was recorded. Only a successful exact
            # listing proves absence; authentication/network errors propagate.
            self._checkpoint(key).unlink(missing_ok=True)
            return
        if isinstance(locator, dict) and info["object_id"] != locator.get("object_id"):
            raise EvidenceError("Drive object identity mismatch")
        self._command("deletefile", self._remote_path(info["key"]), "--drive-use-trash=false")
        if self._lookup(info["key"]) is not None:
            raise EvidenceError("rclone deletion did not remove registered object")
        self._checkpoint(info["key"]).unlink(missing_ok=True)

    def keys(self, prefix=""):
        if prefix:
            safe_relative(prefix.rstrip("/"))
        result, identities, seen_keys = [], set(), set()
        for value in self._list(recursive=True):
            key = _transport_key(value.get("Path"))
            item = _metadata({"object_id": value.get("ID"), "key": key, "size": value.get("Size")})
            if item["key"] in seen_keys or item["object_id"] in identities:
                raise EvidenceError("duplicate Drive object identity in catalog listing")
            identities.add(item["object_id"])
            seen_keys.add(item["key"])
            if key.startswith(prefix):
                result.append(key)
        return sorted(result)
