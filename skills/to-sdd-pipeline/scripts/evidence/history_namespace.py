"""Portable path fence for known clients using the former history directory.

Logical references never change. A fixed regular marker replaces the old
directory; only this implementation maps it to the fixed physical namespace.
This is a compatibility boundary, not protection against owner filesystem edits.
"""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import stat
import sys

from .io import EvidenceError, _is_link, _parents, atomic_json, read_json, safe_relative

HISTORY = "forge/unit-history"
PHYSICAL_HISTORY = "forge/history-store-v1"
JOURNAL = "forge/history-namespace-migration-v1.json"
STAGED_MARKER = "forge/history-namespace-marker-v1.pending"
MAX_MARKER_BYTES = 16384
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")
_recovery = ContextVar("sdd_history_namespace_recovery", default=None)


def _root(project):
    return Path(project).resolve(strict=True)


def _entry(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if _is_link(info):
        raise EvidenceError("history cannot follow links: " + str(path))
    return info


def _safe_path(root, relative):
    safe_relative(relative)
    current = root
    for component in relative.split("/"):
        current /= component
        info = _entry(current)
        if info is not None and current != root / relative and not stat.S_ISDIR(info.st_mode):
            raise EvidenceError("history namespace parent is not a directory: " + str(current))
    return current


def validate_namespace_facts(value):
    fields = {"version", "event", "logical_root", "physical_root", "project_id", "store_id", "participant_id"}
    if (not isinstance(value, dict) or set(value) != fields or type(value.get("version")) is not int
            or value["version"] != 1 or value.get("event") != "managed_history_namespace"
            or value.get("logical_root") != HISTORY or value.get("physical_root") != PHYSICAL_HISTORY
            or any(not isinstance(value.get(key), str) or not _ID.fullmatch(value[key])
                   for key in ("project_id", "store_id", "participant_id"))):
        raise EvidenceError("invalid fixed history namespace marker")
    return dict(value)


def is_reserved_path(relative):
    safe_relative(relative)
    return relative in (JOURNAL, STAGED_MARKER) or relative == PHYSICAL_HISTORY or relative.startswith(PHYSICAL_HISTORY + "/")


def _validate_journal(value):
    if (not isinstance(value, dict) or set(value) != {"version", "facts", "phase", "source_identity"}
            or type(value.get("version")) is not int or value["version"] != 1
            or value.get("phase") not in ("prepared", "moved", "complete")):
        raise EvidenceError("invalid history namespace migration journal")
    validate_namespace_facts(value["facts"])
    identity = value["source_identity"]
    if (not isinstance(identity, dict) or set(identity) != {"device", "inode"}
            or any(type(identity[key]) is not int or identity[key] < 0 for key in identity)):
        raise EvidenceError("invalid history namespace source identity")
    return value


def namespace_status(project):
    """Return portable marker facts, or None for an untouched legacy layout."""
    root = _root(project)
    old = _safe_path(root, HISTORY)
    target = _safe_path(root, PHYSICAL_HISTORY)
    journal = _safe_path(root, JOURNAL)
    old_info, target_info, journal_info = _entry(old), _entry(target), _entry(journal)
    if old_info is None or stat.S_ISDIR(old_info.st_mode):
        if target_info is not None or journal_info is not None or _entry(_safe_path(root, STAGED_MARKER)) is not None:
            raise EvidenceError("history namespace migration is incomplete or colliding; resume adoption")
        return None
    if not stat.S_ISREG(old_info.st_mode):
        raise EvidenceError("history namespace marker is not a regular file")
    facts = validate_namespace_facts(read_json(old, MAX_MARKER_BYTES))
    if target_info is None or not stat.S_ISDIR(target_info.st_mode):
        raise EvidenceError("history namespace physical directory is missing or invalid")
    if _entry(_safe_path(root, STAGED_MARKER)) is not None:
        raise EvidenceError("history namespace has a colliding staged marker; preserve and reconcile")
    if journal_info is not None:
        state = _validate_journal(read_json(journal, MAX_MARKER_BYTES))
        if state["facts"] != facts:
            raise EvidenceError("history namespace migration journal conflicts with marker")
    return facts


def physical_path(project, logical_relative):
    """Resolve a logical project path, retaining ordinary legacy behavior."""
    safe_relative(logical_relative)
    root = _root(project)
    if is_reserved_path(logical_relative):
        raise EvidenceError("physical history namespace is reserved; use logical history references")
    relative = logical_relative
    if relative == HISTORY or relative.startswith(HISTORY + "/"):
        recovery = _recovery.get()
        if recovery is not None and recovery["project"] == root:
            selected = _recovery_directory(root, recovery["facts"])
            relative = selected.relative_to(root).as_posix() + relative[len(HISTORY):]
        elif namespace_status(root) is not None:
            relative = PHYSICAL_HISTORY + relative[len(HISTORY):]
    return _safe_path(root, relative)


def logical_path(project, physical_or_relative):
    root = _root(project)
    value = Path(physical_or_relative)
    if value.is_absolute():
        try:
            relative = value.relative_to(root).as_posix()
        except ValueError as error:
            raise EvidenceError("physical history path escapes project") from error
    else:
        relative = value.as_posix()
    safe_relative(relative)
    if relative == PHYSICAL_HISTORY or relative.startswith(PHYSICAL_HISTORY + "/"):
        if namespace_status(root) is None:
            raise EvidenceError("physical history path has no valid namespace marker")
        return HISTORY + relative[len(PHYSICAL_HISTORY):]
    if relative in (JOURNAL, STAGED_MARKER):
        raise EvidenceError("history namespace migration journal is reserved")
    return relative


def require_history_namespace(project):
    facts = namespace_status(project)
    if facts is None:
        raise EvidenceError("managed history namespace adoption required")
    root = _root(project)
    lock = _safe_path(root, PHYSICAL_HISTORY + "/activation.lock")
    if _entry(lock) is not None:
        raise EvidenceError("history activation lock blocks namespace adoption or cleanup")
    return facts


def guard_history_write(project, relative):
    """Native recovery reads must never grant pending history publication."""
    safe_relative(relative)
    recovery = _recovery.get()
    if (recovery is not None and recovery["project"] == _root(project)
            and (relative == HISTORY or relative.startswith(HISTORY + "/"))):
        require_history_namespace(project)


def _identity(info):
    return {"device": info.st_dev, "inode": info.st_ino}


def _recovery_directory(root, facts):
    """Resolve only the exact journal-owned tree for native adoption reads."""
    old, target, journal = (_safe_path(root, name) for name in (HISTORY, PHYSICAL_HISTORY, JOURNAL))
    state = _validate_journal(read_json(journal, MAX_MARKER_BYTES))
    if state["facts"] != facts:
        raise EvidenceError("history namespace recovery facts changed")
    old_info, target_info = _entry(old), _entry(target)
    if old_info is not None and stat.S_ISREG(old_info.st_mode):
        if namespace_status(root) != facts:
            raise EvidenceError("history namespace recovery marker changed")
        return target
    if state["phase"] == "complete":
        raise EvidenceError("completed history namespace marker is missing")
    if old_info is None and target_info is not None and stat.S_ISDIR(target_info.st_mode):
        selected, info = target, target_info
    elif (target_info is None and old_info is not None and stat.S_ISDIR(old_info.st_mode)
            and state["phase"] == "prepared"):
        selected, info = old, old_info
    else:
        raise EvidenceError("history namespace recovery has conflicting trees")
    if _identity(info) != state["source_identity"]:
        raise EvidenceError("history namespace recovery source identity changed")
    if _entry(selected / "activation.lock") is not None:
        raise EvidenceError("history activation lock blocks namespace recovery")
    return selected


@contextmanager
def recovery_read_scope(project, *, project_id, store_id, participant_id):
    """Allow native cache audits to read an exact interrupted move on retry.

    Only adoption callers enter this scope. It grants no writer/deletion
    authority: namespace_status and require_history_namespace remain strict,
    and the authoritative pending catalog hold is checked before any mutation.
    """
    root = _root(project)
    journal = _safe_path(root, JOURNAL)
    if _entry(journal) is None:
        yield
        return
    try:
        complete = namespace_status(root)
    except EvidenceError:
        complete = None
    if complete is not None:
        yield
        return
    state = _validate_journal(read_json(journal, MAX_MARKER_BYTES))
    facts = state["facts"]
    if any(facts[key] != value for key, value in (("project_id", project_id),
            ("store_id", store_id), ("participant_id", participant_id))):
        raise EvidenceError("history namespace recovery belongs to a different adoption")
    _recovery_directory(root, facts)
    token = _recovery.set({"project": root, "facts": facts})
    try:
        yield
    finally:
        _recovery.reset(token)


def _check_unfinished(root):
    """Adoption-only bounded inspection; never expire unfinished old writes."""
    pending, count = [root], 0
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            count += 1
            if count > 100000:
                raise EvidenceError("history namespace adoption exceeds file allowance")
            info = _entry(path)
            if info is None:
                raise EvidenceError("history changed during namespace adoption")
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(info.st_mode):
                pending.append(path)
            elif not stat.S_ISREG(info.st_mode):
                raise EvidenceError("history namespace contains a nonregular entry")
            elif ("/files/" not in "/" + relative and
                  (".pending-" in path.name or path.name.startswith(".blob-") or relative == "activation.lock")):
                raise EvidenceError("unfinished history publication blocks namespace adoption: " + relative)


def _sync_directory(path):
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_directory(source, target):
    """No-replace rename; an old client's raced directory is never overwritten."""
    if os.name == "nt":
        os.rename(source, target)
        return
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = getattr(library, "renamex_np", None)
        arguments = (os.fsencode(source), os.fsencode(target), 4)
        kinds = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    elif sys.platform.startswith("linux"):
        function = getattr(library, "renameat2", None)
        arguments = (-100, os.fsencode(source), -100, os.fsencode(target), 1)
        kinds = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    else:
        function = None
    if function is None:
        raise EvidenceError("atomic no-replace namespace rename is unsupported")
    function.argtypes, function.restype = kinds, ctypes.c_int
    if function(*arguments):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


def _write_marker(path, facts):
    raw = (json.dumps(facts, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode()
    _parents(path)
    staged = path.parent / Path(STAGED_MARKER).name
    if _entry(staged) is None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(staged, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    from .io import hash_file
    import hashlib
    if hash_file(staged) != (hashlib.sha256(raw).hexdigest(), len(raw)):
        raise EvidenceError("history namespace staged marker differs; preserve it for reconciliation")
    _rename_directory(staged, path)
    _sync_directory(path.parent)


def ensure_history_namespace(project, *, project_id, store_id, participant_id):
    """Resume an exact adoption under its catalog hold and manager lock.

    The caller must first publish catalog v2 and a pending namespace hold. This
    helper never overwrites, merges, deletes or guesses ownership of a tree.
    """
    root = _root(project)
    facts = validate_namespace_facts({"version": 1, "event": "managed_history_namespace",
        "logical_root": HISTORY, "physical_root": PHYSICAL_HISTORY, "project_id": project_id,
        "store_id": store_id, "participant_id": participant_id})
    old, target, journal = (_safe_path(root, name) for name in (HISTORY, PHYSICAL_HISTORY, JOURNAL))
    old.parent.mkdir(parents=True, exist_ok=True)
    old_info, target_info = _entry(old), _entry(target)
    if old_info is not None and stat.S_ISREG(old_info.st_mode):
        existing = require_history_namespace(root)
        if any(existing[key] != facts[key] for key in ("project_id", "store_id")):
            raise EvidenceError("history namespace belongs to a different project/store")
        _check_unfinished(target)
        # Participant in the marker is creation provenance, not a writer lease.
        if _entry(journal) is not None:
            state = _validate_journal(read_json(journal, MAX_MARKER_BYTES))
            if state.get("phase") != "complete":
                state["phase"] = "complete"
                atomic_json(journal, state)
        return existing
    if _entry(journal) is not None:
        state = _validate_journal(read_json(journal, MAX_MARKER_BYTES))
        if state["facts"] != facts or state["phase"] not in ("prepared", "moved"):
            raise EvidenceError("history namespace migration journal differs from adoption")
    else:
        if target_info is not None:
            raise EvidenceError("unowned physical history namespace; adoption cannot enroll it")
        if old_info is None:
            old.mkdir()
            old_info = _entry(old)
        if not stat.S_ISDIR(old_info.st_mode):
            raise EvidenceError("history namespace source is not a directory")
        if _entry(old / "activation.lock") is not None:
            raise EvidenceError("history activation lock blocks namespace adoption")
        _check_unfinished(old)
        state = {"version": 1, "facts": facts, "phase": "prepared", "source_identity": _identity(old_info)}
        atomic_json(journal, state)
    old_info, target_info = _entry(old), _entry(target)
    if target_info is None:
        if (old_info is None or not stat.S_ISDIR(old_info.st_mode)
                or _identity(old_info) != state["source_identity"]):
            raise EvidenceError("history namespace source identity changed during adoption")
        if _entry(old / "activation.lock") is not None:
            raise EvidenceError("history activation lock blocks namespace adoption")
        try:
            _rename_directory(old, target)
            _sync_directory(old.parent)
        except OSError as error:
            raise EvidenceError("history namespace rename blocked; adoption remains pending: " + str(error)) from error
        target_info = _entry(target)
    elif old_info is not None:
        raise EvidenceError("history namespace rename-gap collision; preserve both trees and reconcile")
    if (not stat.S_ISDIR(target_info.st_mode) or _identity(target_info) != state["source_identity"]):
        raise EvidenceError("history namespace moved tree identity differs from journal")
    state["phase"] = "moved"
    atomic_json(journal, state)
    if _entry(target / "activation.lock") is not None:
        raise EvidenceError("history activation lock blocks namespace adoption after move")
    try:
        _write_marker(old, facts)
    except OSError as error:
        raise EvidenceError("history namespace marker collision/interruption; adoption remains pending: " + str(error)) from error
    result = require_history_namespace(root)
    _check_unfinished(target)
    state["phase"] = "complete"
    atomic_json(journal, state)
    return result
