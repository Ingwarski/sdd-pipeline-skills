"""Bounded, stable-byte I/O shared by the evidence manager and read-only checker."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import uuid


class EvidenceError(ValueError):
    """Evidence cannot be safely read, accounted, stored, or verified."""


def safe_relative(value: str) -> str:
    """Validate a portable member/source path without normalizing unsafe spelling."""
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise EvidenceError("expected a nonempty portable relative path")
    parts = value.split("/")
    if value.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise EvidenceError("unsafe relative path: " + repr(value))
    reserved = {"CON", "PRN", "AUX", "NUL"} | {"COM" + str(i) for i in range(1, 10)} | {"LPT" + str(i) for i in range(1, 10)}
    if any(any(char in ':<>"|?*' or ord(char) < 32 or ord(char) == 127 for char in part)
           or part.endswith((".", " ")) or part.split(".", 1)[0].upper() in reserved for part in parts):
        raise EvidenceError("unsafe portable path: " + repr(value))
    if PurePosixPath(value).is_absolute():
        raise EvidenceError("absolute paths are forbidden")
    return value


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _parents(path: Path):
    """Reject linked parents; callers should pass the actual OS temporary folder."""
    for parent in reversed(path.parents):
        info = parent.lstat()
        if _is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise EvidenceError("linked or non-directory parent: " + str(parent))


def _open_regular(path):
    """Open the same regular inode that was inspected, without following links."""
    path = Path(os.path.abspath(os.fspath(path)))
    try:
        _parents(path)
        before = path.lstat()
        if _is_link(before) or not stat.S_ISREG(before.st_mode):
            raise EvidenceError("not a regular file: " + str(path))
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
        if os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"):
            # Pin each parent inode while descending so a renamed ancestor
            # cannot redirect the open through a symlink between lstat/open.
            parent_fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for component in path.parts[1:-1]:
                    next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                    os.close(parent_fd)
                    parent_fd = next_fd
                fd = os.open(path.name, flags, dir_fd=parent_fd)
            finally:
                os.close(parent_fd)
        else:
            fd = os.open(path, flags)
        actual = os.fstat(fd)
        if not stat.S_ISREG(actual.st_mode) or _signature(before) != _signature(actual):
            os.close(fd)
            raise EvidenceError("file changed while opening: " + str(path))
        return path, fd, before
    except OSError as exc:
        raise EvidenceError("cannot safely open " + str(path) + ": " + str(exc)) from exc


def _verify_stable(path, fd, before):
    try:
        _parents(path)
        if _signature(before) != _signature(os.fstat(fd)) or _signature(before) != _signature(path.lstat()):
            raise EvidenceError("input changed while reading: " + str(path))
    except OSError as exc:
        raise EvidenceError("input disappeared while reading: " + str(path)) from exc


def hash_file(path) -> tuple[str, int]:
    """Hash stable regular bytes in 1 MiB chunks, rejecting links and mutations."""
    path, fd, before = _open_regular(path)
    try:
        digest, size = hashlib.sha256(), 0
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
        _verify_stable(path, fd, before)
        if size != before.st_size:
            raise EvidenceError("file length changed while hashing: " + str(path))
        return digest.hexdigest(), size
    finally:
        os.close(fd)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path, limit: int):
    """Read a bounded stable UTF-8 JSON document, rejecting ambiguous objects."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise EvidenceError("JSON limit must be a positive integer")
    path, fd, before = _open_regular(path)
    try:
        if before.st_size > limit:
            raise EvidenceError("JSON exceeds configured byte limit: " + str(path))
        chunks, size = [], 0
        while True:
            block = os.read(fd, min(1024 * 1024, limit + 1 - size))
            if not block:
                break
            size += len(block)
            if size > limit:
                raise EvidenceError("JSON exceeds configured byte limit: " + str(path))
            chunks.append(block)
        _verify_stable(path, fd, before)
        if size != before.st_size:
            raise EvidenceError("JSON length changed while reading")
        return json.loads(b"".join(chunks).decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(EvidenceError("non-finite JSON number")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise EvidenceError("invalid UTF-8 JSON: " + str(path)) from exc
    except ValueError as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("invalid bounded JSON value: " + str(path)) from exc
    finally:
        os.close(fd)


def atomic_json(path, obj):
    """Durably replace JSON through a task-owned file in the same safe directory."""
    path = Path(os.path.abspath(os.fspath(path)))
    temporary = None
    parent_fd = None
    try:
        _parents(path)
        if path.exists() or path.is_symlink():
            destination = path.lstat()
            if _is_link(destination) or not stat.S_ISREG(destination.st_mode):
                raise EvidenceError("JSON destination is not a regular file: " + str(path))
        raw = (json.dumps(obj, sort_keys=True, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode("utf-8")
        pinned = os.open in os.supports_dir_fd and os.rename in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW")
        if pinned:
            parent_fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            for component in path.parts[1:-1]:
                next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                os.close(parent_fd)
                parent_fd = next_fd
            parent_identity = os.fstat(parent_fd)
            actual_parent = path.parent.lstat()
            if (parent_identity.st_dev, parent_identity.st_ino) != (actual_parent.st_dev, actual_parent.st_ino):
                raise EvidenceError("JSON parent changed while opening")
            temporary = "." + path.name + "-" + uuid.uuid4().hex + ".tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
        else:
            descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + "-", suffix=".tmp", dir=path.parent)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _parents(path)
        if pinned:
            actual_parent = path.parent.lstat()
            if (parent_identity.st_dev, parent_identity.st_ino) != (actual_parent.st_dev, actual_parent.st_ino):
                raise EvidenceError("JSON parent changed while writing")
            try:
                target = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
                if _is_link(target) or not stat.S_ISREG(target.st_mode):
                    raise EvidenceError("JSON destination changed to an unsafe file")
            except FileNotFoundError:
                pass
            os.replace(temporary, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            os.fsync(parent_fd)
        else:
            os.replace(temporary, path)
        temporary = None
        if parent_fd is None and hasattr(os, "O_DIRECTORY"):
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("cannot persist JSON: " + str(path) + ": " + str(exc)) from exc
    finally:
        if temporary is not None:
            try:
                if parent_fd is not None:
                    os.unlink(temporary, dir_fd=parent_fd)
                else:
                    os.unlink(temporary)
            except FileNotFoundError:
                pass
        if parent_fd is not None:
            os.close(parent_fd)
