#!/usr/bin/env python3
"""Current unit history. Read-only resolution and validated local migration.

Recorded reviews and user events are supplied facts, never authenticated by hashes.
The checker never calls the writing helpers. Standard library only.
"""
import argparse
import check_inputs
import verification_metrics as metrics
from history_integrity import history_integrity_scope, defer_legacy_payload
from observation_capture import snapshot_dependencies
import copy
import ctypes
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import errno
from functools import wraps
import hashlib
import importlib.util
import inspect
import shutil
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import socket
import stat
import subprocess
import sys
import uuid

from evidence.resolver import EvidenceResolver, INACTIVE_HISTORY_KEYS, evidence_reference, validate_reference, _regular, JSON_LIMIT
from evidence.io import safe_relative, _parents, _open_regular, _verify_stable, hash_file, read_json as bounded_json
from evidence.policy import validate_policy, MAX_POLICY_BYTES

VERSION = 2
CONTRACT = "sdd-unit-history-v2"
HISTORY = "forge/unit-history"
_SCRIPT_PATH = Path(__file__).resolve()
REF_KEYS = {"path", "content_hash"}
SOURCE_INDEX_MAX_BYTES = 64 * 1024 * 1024  # Native read_ref/read_json consumer ceiling.
SOURCE_VIEW_RECEIPT_MAX_BYTES = JSON_LIMIT  # Ordinary prepared _json consumer ceiling.
EXECUTION_KEYS = {"execution_status", "executor", "executed_at", "evidence", "execution_mode", "evaluated_plan_hash", "evaluated_source_hashes", "evaluated_execution_inputs", "findings", "rationale", "source_inventory_ref", "revalidation_ref", "run_id", "runtime_observation_ref", "seal_ref", "reused_from"}
V2_KEYS = {"execution_contexts", "completion_ref", "applicability_ref", "unit_history", "completion_history", "legacy_history", "evaluated_execution_inputs", "context_ref", "attempt_ref", "attempt_history", "prior_attempt_ref", "source_archive_index_ref"}
_snapshot_hash_owner = ContextVar("sdd_history_snapshot_hash_owner", default=None)
_checker_audit_lease = ContextVar("sdd_history_checker_audit_lease", default=None)
_source_archive = ContextVar("sdd_history_source_archive", default=None)


@contextmanager
def snapshot_hash_scope(owner=None, *, audit=False):
    """A fresh standalone invocation, or the active caller's snapshot hashes."""
    current = _snapshot_hash_owner.get()
    if current is not None:
        require(owner is None or not owner.depth or owner is current, "conflicting snapshot hash invocations")
        owner = current
    elif owner is None or not owner.depth:
        owner = api().SnapshotFileHashes()
    token = _snapshot_hash_owner.set(owner)
    owner.depth += 1
    try:
        yield owner
    finally:
        try:
            # Audit each checker/projection boundary and the outer read-only
            # phase, including exceptions and semantic history cache hits.
            # Tiny nested helpers still stat each use; they need no repeated
            # full-union scan while their enclosing boundary remains active.
            if audit or owner.depth == 1:
                owner.audit()
        finally:
            owner.depth -= 1
            if not owner.depth:
                owner.hashes.clear()
                owner.physical_hashes.clear()
                owner.history_results.clear()
                owner.legacy_files.clear()
                owner.section_indexes.clear()
            _snapshot_hash_owner.reset(token)


@contextmanager
def _checker_run_hash_scope(checker):
    """An unexported, expiring lease backed by a mandatory checker-end audit."""
    with source_archive_scope(checker.project, getattr(checker, "_history_source_archive_index_ref",
                              checker._source_manifest.get("source_archive_index_ref")),
                              checker.evidence_resolver.cache, policy_manifest=checker._source_manifest), snapshot_hash_scope(getattr(checker, "_history_hash_owner", None), audit=True) as owner:
        lease = {"checker": checker, "owner": owner, "active": True}
        token = _checker_audit_lease.set(lease)
        try:
            yield owner
        finally:
            lease["active"] = False
            _checker_audit_lease.reset(token)


def snapshot_hash_invocation(function):
    return source_archive_invocation(_snapshot_hash_invocation(function))


def _snapshot_hash_invocation(function):
    @wraps(function)
    def scoped(*args, **kwargs):
        with snapshot_hash_scope():
            return function(*args, **kwargs)
    return scoped


def source_archive_invocation(function):
    signature = inspect.signature(function)
    @wraps(function)
    def scoped(*args, **kwargs):
        explicit = kwargs.pop("source_archive_index_ref", None)
        values = signature.bind(*args, **kwargs).arguments
        manifest = values.get("candidate_manifest", values.get("candidate", values.get("manifest", {})))
        if function.__name__ == "activate_candidate":
            manifest = read_ref(values["project"], values["candidate_ref"])["manifest"]
        reference = explicit
        if reference is None and _source_archive.get() is None:
            reference = manifest.get("source_archive_index_ref") if isinstance(manifest, dict) else None
        with source_archive_scope(values.get("project"), reference, values.get("evidence_cache"),
                                  policy_manifest=manifest if isinstance(manifest, dict) and manifest else None):
            return function(*args, **kwargs)
    return scoped


def contains_v2_fields(value):
    if isinstance(value, dict):
        return bool(set(value) & V2_KEYS) or any(contains_v2_fields(child) for child in value.values())
    return isinstance(value, list) and any(contains_v2_fields(child) for child in value)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def api():
    name = "_sdd_history_checker"
    path = _SCRIPT_PATH.with_name("sdd_check.py")
    if name in sys.modules:
        existing = sys.modules[name]
        require(_module_at(existing, path), "conflicting checker module alias: " + name)
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _module_at(module, path):
    try:
        return module.__file__ == str(path) or Path(module.__file__).resolve() == path
    except (AttributeError, TypeError, ValueError, OSError):
        return False


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode()


def same(a, b):
    return encoded(a) == encoded(b)


def reviewed_observation(check, accepted):
    """Identify the exact original observation already validated by a review."""
    original = accepted.get(check.get("check_id"))
    fields = EXECUTION_KEYS - {"findings"}
    return original is not None and same({key: value for key, value in check.items() if key in fields},
                                         {key: value for key, value in original.items() if key in fields})


def merged_findings(*collections):
    """Keep current observations alongside immutable execution observations."""
    result = []
    for findings in collections:
        require(isinstance(findings, list), "findings list required")
        for finding in findings:
            require(isinstance(finding, dict) and finding.get("severity") in ("P0", "P1", "P2", "P3")
                    and finding.get("release_effect") in ("blocking", "advisory")
                    and finding.get("status") in ("open", "closed"), "invalid current finding classification")
            require(finding["severity"] not in ("P0", "P1") or finding["release_effect"] == "blocking", "P0/P1 findings must block")
            require(finding["severity"] != "P3" or finding["release_effect"] == "advisory", "P3 findings must be advisory")
            if not any(same(finding, existing) for existing in result):
                result.append(copy.deepcopy(finding))
    return result


def differences(before, after, prefix=""):
    if same(before, after):
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(set(before) | set(after)):
            result.extend(differences(before.get(key), after.get(key), prefix + (" / " if prefix else "") + str(key)))
        return result
    return [prefix]


def _containment_path(path):
    """Compare equivalent resolved Windows anchors without changing I/O paths."""
    if isinstance(path, PureWindowsPath) and path.root:
        drive = path.drive
        if re.fullmatch(r"\\\\\?\\[A-Za-z]:", drive):
            return PureWindowsPath(drive[4:] + path.root, *path.parts[1:])
        if drive.casefold().startswith("\\\\?\\unc\\"):
            components = drive[8:].split("\\")
            if len(components) == 2 and all(part not in ("", ".", "..", "?") for part in components):
                return PureWindowsPath("\\\\" + drive[8:] + path.root, *path.parts[1:])
    return path


def physical(project, path):
    require(isinstance(path, str) and path and "\\" not in path, "history path must be relative POSIX text")
    parts = PurePosixPath(path)
    require(not parts.is_absolute() and all(p not in ("..", ".") for p in path.split("/")), "unsafe history path: " + path)
    root = Path(project).resolve()
    current = root
    for part in parts.parts:
        current /= part
        try:
            info = current.lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        require(not (stat.S_ISLNK(info.st_mode) or
                     getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)),
                "history cannot follow links: " + path)
    # Concurrent parent creation can make Windows realpath retain its extended
    # prefix (initial missing-directory error, final missing-file error).
    require(_containment_path(current.resolve()).is_relative_to(_containment_path(root)),
            "history path escapes project")
    return current


def read_ref(project, ref):
    require(isinstance(ref, dict) and set(ref) == REF_KEYS, "hash-bound path reference required")
    path = physical(project, ref["path"])
    require(path.is_file(), "missing history file: " + ref["path"])
    owner = _snapshot_hash_owner.get()
    owner = owner if owner is not None and owner.depth > 0 else None
    if owner is not None:
        require(api().hash_matches(ref["content_hash"], owner.file_hash(path)), "changed history file: " + ref["path"])
    data = path.read_bytes()
    require(api().hash_matches(ref["content_hash"], sha(data)), "changed history file: " + ref["path"])
    metrics.count("json_parse_bytes", len(data))
    document = api().read_json(path)
    if owner is not None:
        require(api().hash_matches(ref["content_hash"], owner.file_hash(path)), "changed history file: " + ref["path"])
    return document


def write_new(project, path, data):
    target = physical(project, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": path, "content_hash": sha(data)}


def _rename_noreplace(staged, target):
    """Move a complete same-directory file without replacing any winner.

    Unlike link/unlink publication, exclusive rename leaves no temporary alias
    whose later removal changes the published inode during a concurrent read.
    Unsupported APIs/filesystems fail closed; ordinary POSIX rename overwrites.
    """
    if os.name == "nt":
        os.rename(staged, target)  # Windows rename refuses an existing target.
        return
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = getattr(library, "renamex_np", None)
        arguments = (os.fsencode(staged), os.fsencode(target), 0x00000004)  # RENAME_EXCL
        types = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    elif sys.platform.startswith("linux"):
        function = getattr(library, "renameat2", None)
        arguments = (-100, os.fsencode(staged), -100, os.fsencode(target), 1)  # AT_FDCWD, RENAME_NOREPLACE
        types = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    else:
        function = None
    if function is None:
        raise OSError(errno.ENOTSUP, "atomic no-replace history publication is unavailable", os.fspath(target))
    function.argtypes, function.restype = types, ctypes.c_int
    if function(*arguments) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), os.fspath(target))


def publish_immutable(project, path, data, *, existing_winner=False):
    """Publish complete bytes without replacing an immutable concurrent winner.

    A partial write can leave only this attempt's temporary file, never a
    partial deterministic destination. A caller accepting a different winner
    must independently validate its semantic identity before using the result.
    """
    target = physical(project, path)
    if not target.exists():
        temporary = path + ".pending-" + uuid.uuid4().hex
        staged = physical(project, temporary)
        try:
            write_new(project, temporary, data)
            try:
                _rename_noreplace(staged, target)
            except FileExistsError:
                pass
        finally:
            if staged.exists():
                staged.unlink()
    digest, size = hash_file(physical(project, path))
    require(existing_winner or size == len(data) and digest == sha(data),
            "existing immutable publication differs: " + path)
    return {"path": path, "content_hash": digest}


def write_snapshot(project, path, data):
    """Share immutable content-addressed bytes while retaining real render-tree paths."""
    digest = sha(data)
    blob = physical(project, HISTORY + "/blobs/" + digest)
    blob.parent.mkdir(parents=True, exist_ok=True)
    if not blob.exists():
        temporary = blob.with_name(".blob-" + uuid.uuid4().hex)
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, blob)
            except FileExistsError:
                pass
        finally:
            if temporary.exists():
                temporary.unlink()
    require(blob.is_file() and sha(blob.read_bytes()) == digest, "content-addressed snapshot blob is corrupt")
    target = physical(project, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.link(blob, target)
    return {"path": path, "content_hash": digest}


def store_record(project, kind, record, directory=None):
    directory = directory or HISTORY + "/" + kind + "/" + uuid.uuid4().hex
    return write_new(project, directory + "/record.json", encoded(record))


def snapshot_or_file_hash(checker, path):
    """Reuse registered snapshots only; other inventory reads retain their behavior."""
    prepared = source_view_hash(path, getattr(checker, "_history_source_archive", None))
    if prepared is not None:
        return prepared
    owner = getattr(checker, "_history_hash_owner", None)
    if owner is not None and owner.depth and path in owner.hashes:
        return checker.file_hash(path)
    return sha(path.read_bytes())


def canonical_hashes(checker, allow_missing=False):
    result = {}
    for key, spec in checker.specs.items():
        if key in checker.skipped:
            continue
        path = checker.path(spec["path"], no_links=True)
        if allow_missing and not path.exists():
            result[spec["path"]] = None
        else:
            result[spec["path"]] = snapshot_or_file_hash(checker, path)
    return result


def execution_fingerprints(checker, selections):
    require(isinstance(selections, dict) and selections, "reviewed execution_inputs file/tree inventory required")
    result = {}
    for logical, selection in selections.items():
        require(isinstance(selection, dict) and selection.get("mode") in ("file", "tree", "absent"), "execution input requires file/tree/absent mode")
        require(not logical.startswith(HISTORY + "/") and logical not in (".", "", "/"), "execution inventory must select relevant paths, not history or the whole project")
        target = checker.path(logical, no_links=True)
        mode = selection["mode"]
        if not target.exists():
            result[logical] = {"mode": mode, "exists": False}
        elif mode == "absent":
            raise ValueError("execution input must remain absent: " + logical)
        elif mode == "file":
            require(target.is_file(), "execution input is not a regular file: " + logical)
            result[logical] = {"mode": mode, "exists": True, "content_hash": snapshot_or_file_hash(checker, target)}
        else:
            require(target.is_dir(), "execution input is not a directory: " + logical)
            members = {}
            for directory, dirs, names in os.walk(target, followlinks=False):
                for name in dirs + names:
                    path = Path(directory) / name
                    require(not api().is_link(path), "execution inventory cannot follow a symlink")
                    if path.is_file():
                        members[path.relative_to(target).as_posix()] = snapshot_or_file_hash(checker, path)
                    else:
                        require(path.is_dir(), "execution tree contains a special file")
                        members[path.relative_to(target).as_posix() + "/"] = None
            result[logical] = {"mode": mode, "exists": True, "members": members}
    return result


def prepare_inventory(checker, unit_id, inventory):
    """Hash exact reviewed inputs; do not infer that an omitted dependency is absent."""
    require(isinstance(inventory, dict), "reviewed inventory required")
    review = inventory.get("review", {})
    require(review.get("complete") is True and isinstance(review.get("reviewer"), str) and review["reviewer"].strip()
            and isinstance(review.get("rationale"), str) and review["rationale"].strip(), "inventory needs actual complete owner review and rationale")
    require(api().timestamp(review.get("reviewed_at")) <= api().timestamp(utcnow()), "inventory review is in the future")
    canonical = canonical_hashes(checker)
    sources = inventory.get("sources", {})
    require(isinstance(sources, dict) and set(sources) == set(canonical), "inventory must review every current canonical artifact, including shared definitions")
    mandatory = {"docs/" + name + ".md" for name in ("prd", "architecture", "dod-evals", "qa-checklist", "development-plan", "guardrails", "canonical-terms", "project-context")}
    inputs = {}
    for path, selection in sources.items():
        require(isinstance(selection, dict), "invalid inventory selection: " + path)
        mode = selection.get("mode")
        if mode == "unused":
            require(path not in mandatory and isinstance(selection.get("reason"), str) and selection["reason"].strip(), "required input cannot be unused: " + path)
            inputs[path] = {"mode": mode, "reason": selection["reason"]}
        elif mode == "full":
            inputs[path] = {"mode": mode, "content_hash": canonical[path]}
        else:
            headings = selection.get("headings")
            require(mode == "sections" and isinstance(headings, list) and headings and len(headings) == len(set(headings)), "nonempty unique exact headings required: " + path)
            inputs[path] = {"mode": mode, "sections": {heading: sha(api().section_bytes(checker.path(path, no_links=True), heading)) for heading in sorted(headings)}}
    environment = inventory.get("environment")
    require(isinstance(environment, dict) and environment, "reviewed runtime/configuration environment identity required; do not store secrets")
    plan = checker.manifest["unit_plan"]
    require(unit_id in plan["units"], "inventory unit is not in the current plan")
    unit = plan["units"][unit_id]
    checks = {x["check_id"]: x for x in checker.manifest["verification"]["checks"]}
    owned = {key: value for key, value in plan["acceptance"].items() if value["owner_unit"] == unit_id}
    selections = inventory.get("execution_inputs", {})
    fingerprints = execution_fingerprints(checker, selections)
    needed = set(unit["implementation_paths"])
    for key in owned:
        needed.update(check_inputs.required_paths(checker, checks[key]))
    for path in needed:
        require(any(path == source or selection["mode"] == "tree" and path.startswith(source.rstrip("/") + "/") for source, selection in selections.items()), "execution inventory omits declared implementation/test input: " + path)
    # Preserve the complete authored QA definition, not only its JSON acceptance map.
    qa = {key: {k: v for k, v in checks[key].items() if k not in EXECUTION_KEYS} for key in owned}
    bindings = {"unit": unit, "acceptance": owned, "qa": qa,
                "contributions": [x for x in checker.artifacts["development-plan"]["traceability"]["links"] if x.get("from") == unit_id],
                "baseline": checker.manifest.get("active_baseline"), "baseline_id": checker.manifest.get("approved_baseline_id"),
                "product_scope": checker.manifest.get("product_scope")}
    if "construction" in plan:
        allocated = {key: value for key, value in plan["construction"].items() if value.get("owner_unit") == unit_id}
        reference = plan["construction_ref"]
        definitions = api().validate_architecture_construction(checker)
        require(definitions is not None, "construction inventory requires the canonical mechanism block")
        bindings["construction"] = {"definition_ref": copy.deepcopy(reference), "allocations": copy.deepcopy(allocated),
                                    "mechanisms": {key: copy.deepcopy(definitions[key]) for key in allocated}}
    result = {"review": copy.deepcopy(review), "sources": copy.deepcopy(sources), "environment": copy.deepcopy(environment),
            "execution_inputs": copy.deepcopy(selections), "execution_fingerprints": fingerprints,
            "canonical_hashes": canonical, "inputs": inputs, "bindings": copy.deepcopy(bindings)}
    if check_inputs.enabled(checker.manifest):
        result["check_execution_fingerprints"] = check_inputs.fingerprints(checker, unit_id, result)
    if "runtime_observation_ref" in inventory:
        observation = validate_runtime_observation(checker.project, inventory["runtime_observation_ref"])
        require(same(observation["environment"], environment), "runtime observation differs from reviewed environment")
        require(api().timestamp(observation["observed_at"]) <= api().timestamp(review["reviewed_at"]),
                "owner review must follow the runtime observation")
        result["runtime_observation_ref"] = copy.deepcopy(inventory["runtime_observation_ref"])
    return result


class _ExternalEvidenceError(ValueError):
    """Explicit reference failures are never optional application path metadata."""


def referenced_paths(project, manifest, *, checker=None, external_refs=None, path_resolver=None):
    """Enumerate declared regular sources/receipts and frozen render trees only."""
    found, seen_json, seen_external, seen_files = set(), set(), set(), set()
    seen_directories, directory_stamps = set(), {}

    def directory_stamp(path):
        info = path.stat(follow_symlinks=False)
        return info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, info.st_ctime_ns

    resolve_path = path_resolver or (lambda value: physical(project, value))

    def scan_directory(value, path):
        if value in seen_directories:
            return
        directory_stamps[value] = directory_stamp(path)
        for child in sorted(path.iterdir()):
            relative = (PurePosixPath(value) / child.name).as_posix()
            checked = resolve_path(relative)
            if checked.is_dir():
                scan_directory(relative, checked)
            elif checked.is_file():
                found.add(relative)
        # A tree scan discovers files without consuming their JSON dependencies.
        # Only complete scans can be reused, including overlapping subtrees.
        seen_directories.add(value)

    def add(value, *, optional=False):
        if not isinstance(value, str) or not value:
            return
        if value in seen_directories:
            require(not value.startswith(HISTORY), "history directories cannot be embedded recursively")
            return  # Directory membership is checked below.
        if value in seen_files:
            return  # Consumers recheck containment before reading.
        try:
            path = resolve_path(value)
        except ValueError:
            if not optional:
                raise
            return  # Incidental application metadata can name non-project paths.
        if not path.exists():
            return  # Planned implementation destinations need not exist before start.
        if path.is_dir():
            require(not value.startswith(HISTORY), "history directories cannot be embedded recursively")
            scan_directory(value, path)
            return
        require(path.is_file(), "snapshot source must be regular: " + value)
        seen_files.add(value)
        # History envelopes keep direct refs; their own immutable snapshots are checked independently.
        if value.startswith(HISTORY + "/"):
            return
        found.add(value)
        if PurePosixPath(value).suffix == ".json" and value not in seen_json:
            seen_json.add(value)
            try:
                document = api().read_json(path)
            except (ValueError, UnicodeError):
                return  # Application files need not be parseable JSON.
            # Ignore incidental paths individually, never the remaining references.
            walk(document, optional_paths=True)
    def walk(value, *, optional_paths=False):
        if isinstance(value, dict):
            try:
                external = evidence_reference(value)
                if external is not None:
                    validate_reference(external)
            except ValueError as error:
                raise _ExternalEvidenceError(str(error)) from error
            if external is not None:
                if external_refs is not None:
                    external_refs.append(external)
                # Locator/original_path values describe external evidence, not
                # project files. Only verified JSON payloads can add sources.
                marker = external["artifact_id"]
                if checker is not None and marker not in seen_external:
                    seen_external.add(marker)
                    try:
                        checker.evidence_resolver.resolve(external)
                        checker.evidence_accounting(external)
                        payload = checker.evidence_resolver.json(external) if external["schema"] not in (
                            "evidence-bytes-v1", "archive-attachment-v1") else None
                    except ValueError as error:
                        raise _ExternalEvidenceError(str(error)) from error
                    if payload is not None:
                        # JSON evidence can contain HTTP routes and observed machine
                        # paths, just like contained application JSON. Explicit
                        # references and declared source inventories remain strict.
                        walk(payload, optional_paths=True)
                if external is value:
                    return
                value = {key: child for key, child in value.items() if key != "evidence_ref"}
            dependencies = snapshot_dependencies(value)
            if dependencies is not None:
                for reference in dependencies:
                    path = resolve_path(reference["path"])
                    require(path.is_file() and hash_file(path)[0] == reference["content_hash"], "changed or missing observation dependency: " + reference["path"])
                    add(reference["path"])
                return
            for key, child in value.items():
                if key in INACTIVE_HISTORY_KEYS:
                    continue  # Preserve the containing record's bytes, not inactive dependency closure.
                if key == "repository_observations" and isinstance(child, dict):
                    for observation in child.values():
                        for path in observation.get("paths", {}):
                            add(path)
                elif key in ("source_hashes", "evaluated_source_hashes") and isinstance(child, dict):
                    for path in child:
                        add(path)
                elif key in ("implementation_paths", "required_source_paths", "render_dependencies") and isinstance(child, list):
                    for path in child:
                        add(path)
                elif isinstance(child, str) and (key in ("path", "source", "destination") or key.endswith("_path") or key.endswith("_root")):
                    add(child, optional=optional_paths and not (key == "path" and "content_hash" in value))
                walk(child, optional_paths=optional_paths)
        elif isinstance(value, list):
            for child in value:
                walk(child, optional_paths=optional_paths)
    walk(manifest)
    # The default policy is implied by external references even when a legacy
    # manifest has no evidence_storage declaration. Historical checks need the
    # exact original policy, never whatever policy exists when they resume.
    if manifest.get("evidence_accounting") is not None:
        add(manifest.get("evidence_storage", {}).get("policy_path", "forge/evidence-policy.json"))
    for value, stamp in directory_stamps.items():
        path = resolve_path(value)
        require(path.is_dir() and directory_stamp(path) == stamp,
                "snapshot directory changed during discovery; retry: " + value)
    return found


def freeze_files(project, manifest, directory, execution_inputs=None, *, checker=None):
    files = {}
    paths = referenced_paths(project, manifest, checker=checker)
    for logical in execution_inputs or {}:
        target = physical(project, logical)
        if target.is_file():
            paths.add(logical)
        elif target.is_dir():
            physical(project, directory + "/files/" + logical).mkdir(parents=True, exist_ok=True)
            for path in target.rglob("*"):
                relative = path.relative_to(Path(project).resolve()).as_posix()
                physical(project, relative)
                if path.is_file():
                    paths.add(relative)
                elif path.is_dir():
                    physical(project, directory + "/files/" + relative).mkdir(parents=True, exist_ok=True)
    for logical in sorted(paths):
        files[logical] = write_snapshot(project, directory + "/files/" + logical, physical(project, logical).read_bytes())
    return files



SOURCE_ARCHIVE_EVENTS = frozenset({"unit_execution_context", "unit_completion", "unit_attempt", "legacy_execution_archive", "sealed_check", "external_check_observations"})


class PreparedResolverPolicy:
    """One audited policy input; absent undeclared policy keeps ordinary defaults."""
    def __init__(self, project, manifest=None, *, path_resolver=None):
        self.project = Path(project).resolve()
        self.selector = None
        if manifest is None:
            active = physical(self.project, "forge/sdd-manifest.json")
            if active.exists():
                before = _regular(active)
                manifest = bounded_json(active, SOURCE_INDEX_MAX_BYTES)
                self.selector = (active, before, hash_file(active)[0])
                require(_regular(active) == before, "source transport manifest changed during policy selection")
            else:
                manifest = {}
        require(isinstance(manifest, dict), "policy selection requires a manifest object")
        storage = manifest.get("evidence_storage", {})
        require(isinstance(storage, dict), "evidence storage declaration must be an object")
        self.logical = storage.get("policy_path", "forge/evidence-policy.json")
        self.path_resolver = path_resolver
        self.path = self.selected_path()
        self.policy, self.signature, self.digest = None, None, None
        if not self.path.exists() and not self.path.is_symlink():
            require("evidence_storage" not in manifest and "evidence_accounting" not in manifest,
                    "declared prepared evidence policy is missing: " + self.logical)
            return
        before = _regular(self.path)
        self.policy = validate_policy(bounded_json(self.path, MAX_POLICY_BYTES))
        self.digest = hash_file(self.path)[0]
        require(_regular(self.path) == before, "prepared evidence policy changed during validation")
        self.signature = before

    def selected_path(self):
        return (self.path_resolver(self.logical, no_links=True) if self.path_resolver is not None
                else physical(self.project, self.logical))

    def audit(self):
        require(self.selected_path() == self.path, "prepared evidence policy path changed during validation")
        if self.signature is None:
            require(not self.path.exists() and not self.path.is_symlink(), "prepared evidence policy appeared during validation")
        else:
            require(_regular(self.path) == self.signature and hash_file(self.path)[0] == self.digest,
                    "prepared evidence policy changed during validation")
        if self.selector is not None:
            path, signature, digest = self.selector
            require(_regular(path) == signature and hash_file(path)[0] == digest,
                    "source transport manifest changed during policy selection")

    def apply(self, resolver):
        self.audit()
        if self.policy is not None:
            resolver.metadata_limit = self.policy["limits"]["metadata_stop_bytes"]
            resolver.closure_limit = self.policy["limits"]["metadata_stop_files"]
        require(resolver.json_bytes <= resolver.metadata_limit and len(resolver.references) <= resolver.closure_limit,
                "prepared metadata/reference closure exceeds project allowance")
        return resolver

    def new_resolver(self, cache):
        return self.apply(EvidenceResolver(cache))


class SourceArchive:
    """One explicitly selected native index; original envelopes always stay local."""
    def __init__(self, project, reference, evidence_cache, *, _document=None, policy_manifest=None, _read_ref=None):
        self.project, self.reference = Path(project).resolve(), copy.deepcopy(reference)
        self.resolver_policy = PreparedResolverPolicy(self.project, policy_manifest)
        self.resolver = self.new_resolver(evidence_cache)
        self.read_record = _read_ref or (lambda ref: read_ref(self.project, ref))
        require(self.resolver.cache is not None and not self.resolver.cache.resolve().is_relative_to(self.project),
                "source archive requires prepared evidence cache outside the repository")
        self.record = self.read_record(reference) if _document is None else copy.deepcopy(_document)
        require(isinstance(self.record, dict), "native source archive index object required")
        required = {"event", "version", "records"}
        require(required <= set(self.record) <= required | {"view_strategy", "encoding", "objects"}
                and self.record["event"] == "unit_source_archive_index"
                and type(self.record["version"]) is int and self.record["version"] == 1,
                "unsupported native source archive index")
        self.view_strategy = self.record.get("view_strategy", "private_copy")
        self.encoding = self.record.get("encoding", "inline")
        require(self.view_strategy in ("private_copy", "shared_cache_links"), "unsupported source view strategy")
        require(self.encoding in ("inline", "sha_objects_v1"), "unsupported source archive encoding")
        objects = self.record.get("objects", {})
        require((self.encoding == "sha_objects_v1") == ("objects" in self.record),
                "compact source archive requires its objects table exclusively")
        require(isinstance(objects, dict) and (objects or self.encoding == "inline"), "compact source objects required")
        for key, ref in objects.items():
            require(isinstance(key, str) and re.fullmatch(r"[a-f0-9]{64}", key), "invalid compact source object key")
            validate_reference(ref)
            require(ref["sha256"] == key and ref["schema"] == "evidence-bytes-v1",
                    "compact source object hash/schema mismatch")
        used_objects = set()
        entries = self.record["records"]
        require(isinstance(entries, list) and entries and len(entries) <= 100000, "bounded source archive records required")
        self.originals, self.sources, self.views = {}, {}, {}
        self.view_memos, self.private_blobs, self.view_files = {}, {}, {}
        self.selected_directories = {}
        self.active_scopes, self.membership = 0, set()
        for entry in entries:
            require(isinstance(entry, dict) and set(entry) == {"record_ref", "snapshot_root", "sources"}, "invalid source archive record binding")
            original = self.read_record(entry["record_ref"])
            require(original.get("event") in SOURCE_ARCHIVE_EVENTS and original.get("version") == (1 if original.get("event") in ("sealed_check", "external_check_observations") else VERSION),
                    "source archive requires original native history envelope")
            root = entry["snapshot_root"]
            safe_relative(root)
            require(root.startswith(HISTORY + "/") and root == original.get("snapshot_root"), "changed source archive snapshot root")
            require(root not in self.originals, "duplicate source archive snapshot root")
            require(isinstance(original.get("files"), dict), "original snapshot membership required")
            self.originals[root] = original
            files = original["files"]
            for logical, frozen in files.items():
                safe_relative(logical)
                require(isinstance(frozen, dict) and set(frozen) == REF_KEYS and frozen["path"] == root + "/" + logical,
                        "original snapshot path must preserve literal logical identity")
            self.membership.update((logical, frozen["path"], frozen["content_hash"]) for logical, frozen in files.items())
            literal_files = {frozen["path"]: frozen for frozen in files.values()}
            require(isinstance(entry["sources"], list) and entry["sources"], "source archive mappings required")
            mapped_paths = set()
            for item in entry["sources"]:
                keys = {"path", "content_hash", "object_key"} if self.encoding == "sha_objects_v1" else {"path", "content_hash", "evidence_ref"}
                require(isinstance(item, dict) and set(item) == keys, "invalid source archive mapping")
                if self.encoding == "sha_objects_v1":
                    key = item["object_key"]
                    require(isinstance(key, str) and key in objects, "missing compact source object")
                    source = {"path": item["path"], "content_hash": item["content_hash"], "evidence_ref": objects[key]}
                    used_objects.add(key)
                else:
                    source = item
                frozen = {key: source[key] for key in REF_KEYS}
                safe_relative(source["path"])
                require(same(frozen, literal_files.get(source["path"])), "foreign source archive membership or changed original hash")
                require(source["path"] not in self.sources, "duplicate source archive mapping")
                ref = validate_reference(source["evidence_ref"])
                require(ref["schema"] == "evidence-bytes-v1" and api().hash_matches(source["content_hash"], ref["sha256"]),
                        "source archive original hash/schema mismatch")
                self.sources[source["path"]] = copy.deepcopy(source)
                mapped_paths.add(source["path"])
            if self.encoding == "sha_objects_v1" or self.view_strategy == "shared_cache_links":
                require(mapped_paths == set(literal_files), "complete source archive membership required for compact/shared views")
        require(used_objects == set(objects), "unused or foreign compact source objects")

    def new_resolver(self, cache):
        return self.resolver_policy.new_resolver(cache)

    def source_inventory(self):
        references, contents = set(), {}
        dependencies = False
        for source in self.sources.values():
            ref = source["evidence_ref"]
            references.add(ref["artifact_id"])
            require(ref["sha256"] not in contents or contents[ref["sha256"]] == ref["size"],
                    "source archive content hash has conflicting declared sizes")
            contents[ref["sha256"]] = ref["size"]
            dependencies = dependencies or bool(ref.get("dependencies"))
        return {"mapping_count": len(self.sources), "unique_refs": len(references),
                "unique_sha256": len(contents), "declared_unique_bytes": sum(contents.values()),
                "declared_dependencies_present": dependencies,
                "reference_count_scope": "direct source references; dependencies retain ordinary resolver validation"}

    def audit(self):
        require(same(self.read_record(self.reference), self.record), "source archive index changed during validation")
        self.audit_inputs()

    def audit_inputs(self):
        self.resolver_policy.audit()
        for entry in self.record["records"]:
            require(same(self.read_record(entry["record_ref"]), self.originals[entry["snapshot_root"]]),
                    "source archive original envelope changed during validation")
        for ref in tuple(self.resolver.references.values()):
            self.resolver.resolve(ref)
        for key, descriptor in tuple(self.views.items()):
            require(same(descriptor[1], self.view_memos[key][1]), "source view overlay changed during validation")
            self.validate_view(*descriptor, force=True)

    def source(self, frozen):
        source = self.sources.get(frozen["path"])
        if source is None:
            return physical(self.project, frozen["path"])
        require(same({key: source[key] for key in REF_KEYS}, frozen), "source archive path/hash binding changed")
        return self.resolver.resolve(source["evidence_ref"])

    def directories(self, root, files):
        """Recover only membership actually recorded by native source metadata."""
        require(root in self.originals, "source view root is not indexed")
        directories = set()
        for logical in files:
            safe_relative(logical)
            directories.update(str(parent) for parent in PurePosixPath(logical).parents if str(parent) != ".")
        inventory = self.originals[root].get("input_inventory", {}).get("execution_fingerprints", {})
        for logical, selection in inventory.items():
            if selection.get("mode") == "tree" and selection.get("exists"):
                safe_relative(logical)
                directories.add(logical)
                directories.update(str(parent) for parent in PurePosixPath(logical).parents if str(parent) != ".")
                for member in selection.get("members", {}):
                    if member.endswith("/"):
                        name = logical + "/" + member[:-1]
                        safe_relative(name)
                        directories.add(name)
        return sorted(directories)

    def descriptor(self, root, files):
        directories = self.directories(root, files)
        # Every overlay source must be the literal member of a bound original.
        for logical, frozen in files.items():
            require((logical, frozen["path"], frozen["content_hash"]) in self.membership,
                    "source view has foreign original membership")
        return {"snapshot_root": root, "files": files, "directories": directories}

    def expected_views(self):
        """Complete allowed views, derived only from immutable original envelopes."""
        views = []
        for root, original in self.originals.items():
            views.append((root, original["files"]))
            if original.get("event") in ("unit_completion", "unit_attempt"):
                require(isinstance(original.get("context_ref"), dict), "source view requires its original context reference")
                context = self.read_record(original["context_ref"])
                require(context.get("event") == "unit_execution_context" and context.get("version") == VERSION,
                        "source view requires its original native pre-start context")
                require(context["snapshot_root"] in self.originals, "prepare source views requires indexed pre-start context")
                files = dict(original["files"])
                for artifact in context["manifest"]["artifacts"].values():
                    if artifact["path"] in context["files"]:
                        files[artifact["path"]] = context["files"][artifact["path"]]
                views.append((root, files))
        return {sha(encoded(self.descriptor(root, files))): (root, files) for root, files in views}

    def view_receipt(self, descriptor):
        receipt = {"event": "unit_source_view", "version": 1, "index_ref": self.reference, "view": descriptor}
        if "view_strategy" in self.record:
            receipt["view_strategy"] = self.view_strategy
        return receipt

    def location(self, descriptor):
        key = sha(encoded(descriptor))
        return self.cache_path("source-views/" + self.reference["content_hash"] + "/views/" + key)

    def cache_path(self, relative):
        safe_relative(relative)
        path = self.resolver.cache / relative
        _parents(self.resolver.cache / ".source-view-parent-check")
        current = self.resolver.cache
        for part in PurePosixPath(relative).parts:
            current /= part
            if current.exists() or current.is_symlink():
                require(not api().is_link(current), "source view cannot follow links")
        return path

    def view_blob_signature(self, blob, source):
        signature, original = _regular(blob), _regular(source)
        if self.view_strategy == "shared_cache_links":
            require(signature == original, "shared source view blob must be the verified ordinary source inode")
        else:
            require(signature[:2] != original[:2],
                    "source view private blob must be independent of the ordinary source object")
        return signature

    def selected_view(self, root, files):
        """Only imported review sources admit a strict, immutable proof subset."""
        original = self.originals.get(root, {})
        complete = original.get("files", {})
        return (original.get("event") in ("legacy_execution_archive", "external_check_observations")
                and bool(files) and len(files) < len(complete)
                and all(same(frozen, complete.get(logical)) for logical, frozen in files.items()))

    def validate_selected_directory(self, root, files, logical, *, remember=True):
        """A selected tree must retain every recorded member and reject additions."""
        safe_relative(logical)
        require(self.selected_view(root, files), "selected source view must bind an imported original")
        complete = self.originals[root]["files"]
        require(logical not in complete, "source view access is outside selected proof")
        expected_files = {name for name in complete if name.startswith(logical.rstrip("/") + "/")}
        require(expected_files <= set(files), "selected directory omits original source members")
        descriptor = self.descriptor(root, complete)
        tree = self.location(descriptor) / "files"
        path = self.cache_path((tree / logical).relative_to(self.resolver.cache).as_posix())
        expected_dirs = {name for name in descriptor["directories"]
                         if name == logical or name.startswith(logical.rstrip("/") + "/")}
        actual_files, actual_dirs = set(), set()
        if path.exists():
            require(path.is_dir() and not api().is_link(path), "selected source directory is not a regular directory")
            actual_dirs.add(logical)
            for parent, dirs, names in os.walk(path, followlinks=False):
                for name in dirs + names:
                    member = Path(parent) / name
                    require(not api().is_link(member), "source view cannot follow links")
                    relative = member.relative_to(tree).as_posix()
                    if member.is_dir():
                        actual_dirs.add(relative)
                    else:
                        require(member.is_file(), "source view must contain regular files only")
                        actual_files.add(relative)
        require(actual_files == expected_files and actual_dirs == expected_dirs,
                "selected source directory membership changed")
        if remember:
            self.selected_directories.setdefault((root, id(files)), set()).add(logical)

    def validate_view(self, root, files, *, force=False):
        key = (root, id(files))
        prior = self.view_memos.get(key)
        if prior is not None and not force:
            tree, original_files = prior
            require(len(files) == len(original_files), "source view overlay membership changed")
            return tree
        selected = self.selected_view(root, files)
        # Reuse the already prepared full view. Selection never creates a new
        # descriptor, copies payloads, or changes the immutable archive index.
        descriptor = self.descriptor(root, self.originals[root]["files"] if selected else files)
        directory = self.location(descriptor)
        require(directory.is_dir() and not api().is_link(directory), "complete prepared source view required; run prepare-source-views")
        receipt = self.resolver._json(directory / "receipt.json")
        require(same(receipt, self.view_receipt(descriptor)),
                "prepared source view receipt/index mismatch")
        require({path.name for path in directory.iterdir()} == {"receipt.json", "files"}, "source view directory membership changed")
        tree = directory / "files"
        require(tree.is_dir() and not api().is_link(tree), "prepared source view tree required")
        if selected:
            for logical in self.selected_directories.get(key, ()):
                self.validate_selected_directory(root, files, logical, remember=False)
        else:
            actual_files, actual_dirs = set(), set()
            for parent, dirs, names in os.walk(tree, followlinks=False):
                for name in dirs + names:
                    path = Path(parent) / name
                    require(not api().is_link(path), "source view cannot follow links")
                    relative = path.relative_to(tree).as_posix()
                    if path.is_dir():
                        actual_dirs.add(relative)
                    else:
                        require(path.is_file(), "source view must contain regular files only")
                        actual_files.add(relative)
            require(actual_files == set(files) and actual_dirs == set(descriptor["directories"]), "source view directory membership changed")
        for logical, frozen in files.items():
            if selected:
                self.cache_path((tree / logical).relative_to(self.resolver.cache).as_posix())
            source = self.source(frozen)  # Revalidates cache receipt and bytes, even with a complete view.
            source_ref = self.sources.get(frozen["path"])
            expected = ((source_ref["evidence_ref"]["sha256"], source_ref["evidence_ref"]["size"])
                        if source_ref else hash_file(source))
            blob = self.cache_path("source-views/" + self.reference["content_hash"] + "/blobs/" + expected[0])
            signature = self.view_blob_signature(blob, source)
            if blob not in self.private_blobs:
                # Shared mode proves the same inode/signature as the freshly
                # resolved ordinary original, whose hash/size was just checked.
                actual = expected if self.view_strategy == "shared_cache_links" else hash_file(blob)
                self.private_blobs[blob] = (signature, actual)
            saved, actual = self.private_blobs[blob]
            require(signature == saved and _regular(blob) == saved and actual == expected
                    and api().hash_matches(frozen["content_hash"], actual[0]) and _regular(tree / logical) == saved,
                    "prepared source view hash/size/private-link mismatch: " + logical)
            self.view_files[tree / logical] = (blob, saved, actual[0], source)
        self.views[key] = (root, files)
        self.view_memos[key] = (tree, copy.deepcopy(files))
        return tree


@contextmanager
def source_archive_scope(project, reference=None, evidence_cache=None, *, policy_manifest=None):
    active = _source_archive.get()
    if active is not None:
        require(project is None or Path(project).resolve() == active.project, "conflicting source archive project scope")
        require(reference is None or same(reference, active.reference), "conflicting source archive index scope")
        yield active
        return
    archive = SourceArchive(project, reference, evidence_cache, policy_manifest=policy_manifest) if reference is not None else None
    token = _source_archive.set(archive)
    if archive is not None:
        archive.active_scopes += 1
    try:
        yield archive
        if archive is not None:
            archive.audit()
    finally:
        if archive is not None:
            archive.active_scopes -= 1
        _source_archive.reset(token)


def archived_source_path(project, frozen):
    archive = _source_archive.get()
    return archive.source(frozen) if archive is not None else physical(project, frozen["path"])


def source_view_path(project, root, files, logical, archive=None):
    archive = _source_archive.get() or archive
    if archive is not None and root in archive.originals:
        safe_relative(logical)
        tree = archive.validate_view(root, files, force=not archive.active_scopes)
        prior_files = archive.view_memos[(root, id(files))][1]
        require(same(files.get(logical), prior_files.get(logical)), "source view overlay path changed")
        path = archive.cache_path((tree / logical).relative_to(archive.resolver.cache).as_posix())
        if logical not in files and archive.selected_view(root, files):
            archive.validate_selected_directory(root, files, logical)
        if logical in files:
            source_path = archive.source(files[logical])
            frozen = files[logical]
            source = archive.sources.get(frozen["path"])
            digest = source["evidence_ref"]["sha256"] if source else hash_file(archive.source(frozen))[0]
            blob = archive.cache_path("source-views/" + archive.reference["content_hash"] + "/blobs/" + digest)
            require(blob in archive.private_blobs and archive.view_blob_signature(blob, source_path) == archive.private_blobs[blob][0]
                    and _regular(path) == archive.private_blobs[blob][0], "source view bytes/private-link changed")
        return path
    frozen = files.get(logical)
    return physical(project, frozen["path"] if frozen else root + "/" + logical)



def source_view_hash(path, archive=None):
    """Only proven index-bound hardlinks can share their verified blob's digest."""
    archive = _source_archive.get() or archive
    if archive is None or Path(path) not in archive.view_files:
        return None
    blob, signature, digest, source = archive.view_files[Path(path)]
    require(archive.view_blob_signature(blob, source) == signature and _regular(Path(path)) == signature,
            "prepared source view bytes/private-link changed")
    return digest


def create_source_archive_index(project, records, *, evidence_cache=None, view_strategy="private_copy", encoding="inline"):
    """Append validated metadata; explicit compact encoding preserves all aliases."""
    require(view_strategy in ("private_copy", "shared_cache_links"), "unsupported source view strategy")
    require(encoding in ("inline", "sha_objects_v1"), "unsupported source archive encoding")
    document = {"event": "unit_source_archive_index", "version": 1, "records": copy.deepcopy(records)}
    if view_strategy != "private_copy":
        document["view_strategy"] = view_strategy
    if encoding == "sha_objects_v1":
        document["encoding"], document["objects"] = encoding, {}
        require(isinstance(document["records"], list), "source archive record list required")
        for entry in document["records"]:
            require(isinstance(entry, dict) and isinstance(entry.get("sources"), list), "source archive mappings required")
            compact = []
            for source in entry["sources"]:
                require(isinstance(source, dict) and set(source) == {"path", "content_hash", "evidence_ref"}, "full source mapping required for compact creation")
                ref = validate_reference(source["evidence_ref"])
                key = ref["sha256"]
                require(key not in document["objects"] or same(document["objects"][key], ref),
                        "conflicting compact source references for SHA " + key + "; reuse one exact ordinary reference for matching aliases")
                document["objects"][key] = copy.deepcopy(ref)
                compact.append({"path": source["path"], "content_hash": source["content_hash"], "object_key": key})
            entry["sources"] = compact
    data = encoded(document)
    require(len(data) <= SOURCE_INDEX_MAX_BYTES,
            "source archive index has " + str(len(data)) + " bytes; native consumer byte limit is " + str(SOURCE_INDEX_MAX_BYTES))
    directory = HISTORY + "/source-indexes/" + uuid.uuid4().hex
    reference = {"path": directory + "/record.json", "content_hash": sha(data)}
    archive = SourceArchive(project, reference, evidence_cache, _document=document)
    for source in archive.sources.values():
        path = archive.source({key: source[key] for key in REF_KEYS})
        require(api().hash_matches(source["content_hash"], hash_file(path)[0]), "source archive prepared bytes changed")
        local = physical(project, source["path"])
        if local.exists():
            require(api().hash_matches(source["content_hash"], hash_file(local)[0]), "existing original snapshot is corrupt")
    archive.audit_inputs()
    return write_new(project, reference["path"], data)


def prepare_source_views(project, index_ref, *, evidence_cache, max_bytes, max_files):
    """Explicit bounded assembly; immutable index selects copy or shared links."""
    require(_source_archive.get() is None and _snapshot_hash_owner.get() is None,
            "prepare source views outside active read-only history validation")
    require(type(max_bytes) is int and max_bytes >= 0 and type(max_files) is int and max_files >= 0,
            "explicit source view byte/file capacity required")
    archive = SourceArchive(project, index_ref, evidence_cache)
    descriptors = archive.expected_views()
    sources = {}
    logical_members = sum(len(files) for _, files in descriptors.values())
    require(logical_members <= max_files, "source view logical file capacity exceeded")
    for root, files in descriptors.values():
        for frozen in files.values():
            path = archive.source(frozen)
            mapped = archive.sources.get(frozen["path"])
            digest, size = ((mapped["evidence_ref"]["sha256"], mapped["evidence_ref"]["size"]) if mapped else hash_file(path))
            require(api().hash_matches(frozen["content_hash"], digest), "original snapshot changed before source view preparation")
            sources.setdefault(digest, (path, size))
    receipts = {}
    for key, (root, files) in descriptors.items():
        data = encoded(archive.view_receipt(archive.descriptor(root, files)))
        require(len(data) <= SOURCE_VIEW_RECEIPT_MAX_BYTES,
                "source view receipt has " + str(len(data)) + " bytes; prepared consumer byte limit is "
                + str(SOURCE_VIEW_RECEIPT_MAX_BYTES) + "; view=" + key)
        receipts[key] = data
    metadata = sum(len(data) for data in receipts.values())
    source_bytes = sum(size for _, size in sources.values())
    copied = 0 if archive.view_strategy == "shared_cache_links" else source_bytes
    require(copied + metadata <= max_bytes, "source view unique byte/metadata capacity exceeded")
    base = archive.cache_path("source-views/" + index_ref["content_hash"])
    require(not base.exists(), "prepared source views already exist; validate or select a fresh cache")
    require(shutil.disk_usage(archive.resolver.cache).free >= copied + metadata, "insufficient free space for source views")
    base.mkdir(parents=True, exist_ok=False)
    try:
        blobroot = base / "blobs"
        blobroot.mkdir()
        for digest, (path, size) in sources.items():
            if archive.view_strategy == "shared_cache_links":
                _regular(path)
                try:
                    os.link(path, blobroot / digest)
                except OSError as error:
                    raise ValueError("source views require shared-cache hardlink support") from error
            else:
                source, descriptor, info = _open_regular(path)
                try:
                    with (blobroot / digest).open("xb") as output:
                        with os.fdopen(os.dup(descriptor), "rb") as stream:
                            shutil.copyfileobj(stream, output, 1024 * 1024)
                    _verify_stable(source, descriptor, info)
                finally:
                    os.close(descriptor)
                require(hash_file(blobroot / digest) == (digest, size), "source changed during view copy")
        for key, (root, files) in descriptors.items():
            descriptor = archive.descriptor(root, files)
            destination = archive.location(descriptor)
            tree = destination / "files"
            tree.mkdir(parents=True)
            for relative in descriptor["directories"]:
                (tree / relative).mkdir(parents=True, exist_ok=True)
            for logical, frozen in files.items():
                mapped = archive.sources.get(frozen["path"])
                source_digest = mapped["evidence_ref"]["sha256"] if mapped else hash_file(archive.source(frozen))[0]
                try:
                    origin = sources[source_digest][0] if archive.view_strategy == "shared_cache_links" else blobroot / source_digest
                    _regular(origin)
                    os.link(origin, tree / logical)
                except OSError as error:
                    raise ValueError("source views require regular hardlink support for " + archive.view_strategy + "; no unbounded copy fallback") from error
            with (destination / "receipt.json").open("xb") as output:
                output.write(receipts[key])
        # Link assembly deliberately changes ctime/nlink. Discard all pre-link
        # evidence and view memos, then independently resolve bytes and receipts
        # with a fresh ordinary resolver after every link has been created.
        archive.resolver = archive.new_resolver(evidence_cache)
        archive.view_memos.clear()
        archive.private_blobs.clear()
        archive.view_files.clear()
        archive.views.clear()
        for source in archive.sources.values():
            archive.source({key: source[key] for key in REF_KEYS})
        for root, files in descriptors.values():
            archive.validate_view(root, files)
        archive.audit()
    except BaseException:
        # Only this operation's exclusive, nofollow tree is removed on failure.
        shutil.rmtree(base)
        raise
    return {"status": "prepared", "index_ref": index_ref, "view_strategy": archive.view_strategy,
            "unique_copied_bytes": copied, "unique_linked_bytes": source_bytes if archive.view_strategy == "shared_cache_links" else 0,
            "metadata_bytes": metadata, "logical_members": logical_members, "views": len(descriptors),
            "source_inventory": archive.source_inventory()}

def validate_files(project, record, *, hash_owner=None):
    with snapshot_hash_scope(hash_owner) as owner:
        require(isinstance(record.get("files"), dict) and (record["files"] or record.get("event") == "legacy_execution_archive"), "historical snapshots required")
        for logical, ref in record["files"].items():
            physical(project, logical)
            require(ref.get("path") == record["snapshot_root"] + "/" + logical, "snapshot path must preserve logical identity")
            path = archived_source_path(project, ref)
            require(path.is_file() and api().hash_matches(ref.get("content_hash"), owner.file_hash(path)), "historical snapshot changed: " + logical)


def _checker_legacy_files(checker, reference, record):
    """Reuse only frozen validation inside an actual audited Checker.run body."""
    if _source_archive.get() is not None:
        validate_files(checker.project, record)
        return
    lease, owner = _checker_audit_lease.get(), _snapshot_hash_owner.get()
    if (lease is None or not lease["active"] or lease["checker"] is not checker
            or lease["owner"] is not owner or not owner.depth or not checker._invocation_active):
        validate_files(checker.project, record)
        return
    key = (str(checker.project.resolve()), reference["path"], reference["content_hash"])
    content = owner._result_hash(record)
    prior = owner.legacy_files.get(key)
    if (prior is not None and prior[0] == content
            and all(owner.hashes.get(path) == saved for path, saved in prior[1])):
        # Current logical paths are not in the frozen signature union. Keep
        # their containment/link guards on every reuse; end audits cover all
        # original frozen files before this checker can return a passed result.
        for logical in record["files"]:
            physical(checker.project, logical)
        return
    validate_files(checker.project, record)
    registrations = tuple((checker.project / ref["path"], owner.hashes[checker.project / ref["path"]])
                          for ref in record["files"].values())
    owner.legacy_files[key] = (content, registrations)


@snapshot_hash_invocation
def historical_checker(project, manifest, context, completion=None, stack=(), cache=None, original_canonical=True, *, evidence_cache=None):
    owner = _snapshot_hash_owner.get()
    validate_files(project, context, hash_owner=owner)
    files = dict(context["files"])
    if completion:
        validate_files(project, completion, hash_owner=owner)
        files = dict(completion["files"])  # A post-run deletion must not resurrect a pre-start file.
        if original_canonical:
            for artifact in context["manifest"]["artifacts"].values():
                logical = artifact["path"]
                if logical in context["files"]:
                    files[logical] = context["files"][logical]
    checker = api().Checker(project, copy.deepcopy(manifest), evidence_cache=evidence_cache)
    checker._history_hash_owner = owner
    archive = _source_archive.get()
    if archive is not None:
        checker._history_source_archive_index_ref = copy.deepcopy(archive.reference)
        checker._history_source_archive = archive
    checker._history_snapshot_records = copy.deepcopy((context, completion) if completion else (context,))
    checker._history_overlay = files
    checker._history_snapshot_root = (completion or context)["snapshot_root"]
    if completion and original_canonical:
        # Pre-start authoring observations retain their original repository view;
        # actual implementation/evidence and post-run owner observations use completion bytes.
        checker._history_observation_overlay = context["files"]
        checker._history_observation_snapshot_root = context["snapshot_root"]
    checker._history_stack = stack
    checker._history_cache = cache if cache is not None else {}
    return checker


def remember_evidence(checker):
    """Share validated external dependency identities across historical views."""
    references = checker._history_cache.setdefault("evidence_references", {})
    for key, ref in checker.evidence_resolver.references.items():
        require(key not in references or same(references[key], ref), "historical evidence identity conflicts: " + key)
        references[key] = copy.deepcopy(ref)


def reviewed_prior(project, manifest, unit, reference):
    """Bind a disclosed contextless original to a genuinely new context."""
    require((manifest.get("checker_contract_version"), manifest.get("unit_contract_version")) == (4, 4),
            "reviewed prior context requires checker/unit contract 4")
    references = manifest.get("reviewed_acceptance", {}).get(unit, [])
    require(references and same(references[-1], reference), "reviewed prior must be the latest retained unit review")
    review = read_ref(project, reference)
    require(review.get("event") == "reviewed_unit_acceptance" and review.get("version") == 1
            and review.get("unit_id") == unit, "reviewed prior identity differs")
    source = read_ref(project, review["source_ref"])
    original = read_ref(project, source["manifest_ref"])
    run = original.get("unit_runs", {}).get(unit, {})
    require(run.get("status") in ("running", "blocked", "completed")
            and unit not in original.get("execution_contexts", {})
            and "attempt_ref" not in run and "completion_ref" not in run,
            "reviewed prior cannot bypass an existing execution context or attempt")
    require(unit not in manifest.get("execution_contexts", {}), "reviewed prior requires a genuinely new execution context")
    require(same(manifest.get("unit_runs", {}).get(unit, {}).get("findings", []), run.get("findings", [])),
            "reviewed retry dropped original run findings")
    originals = {check["check_id"]: check for check in attempt_checks(original, unit)}
    for check in attempt_checks(manifest, unit):
        require(check["check_id"] in originals and same(check.get("findings", []), originals[check["check_id"]].get("findings", [])),
                "reviewed retry dropped original check findings")
    return original


def reviewed_run_identity(project, context, run):
    reference = context.get("reviewed_prior_ref")
    if reference is not None:
        original = reviewed_prior(project, context["manifest"], context["unit_id"], reference)
        require(isinstance(run.get("run_id"), str) and run["run_id"].strip()
                and run["run_id"] != original["unit_runs"][context["unit_id"]].get("run_id"),
                "reviewed contextless retry requires a new actual run identity")


@snapshot_hash_invocation
@metrics.timed("history_context")
def validate_context(project, reference, unit_id, stack=(), cache=None, *, evidence_cache=None):
    metrics.count("history_context_requests")
    cache = cache if cache is not None else {}
    context = read_ref(project, reference)
    cache_key = ("context", reference["content_hash"], unit_id)
    if cache_key in cache and _snapshot_hash_owner.get().history_result(cache, cache_key):
        metrics.count("history_context_cache_hits")
        return copy.deepcopy(cache[cache_key])
    visiting = ("visiting_context", reference["content_hash"], unit_id)
    require(visiting not in cache, "cyclic execution context history")
    cache[visiting] = True
    require(context.get("event") == "unit_execution_context" and context.get("version") == VERSION and context.get("validation_contract") == CONTRACT,
            "unsupported historical execution context")
    require(context.get("unit_id") == unit_id, "execution context belongs to another unit")
    require(api().timestamp(context["captured_at"]) <= api().timestamp(utcnow()), "future execution context")
    require(api().timestamp(context["input_inventory"]["review"]["reviewed_at"]) <= api().timestamp(context["captured_at"]), "owner inventory review must predate context capture")
    manifest = context["manifest"]
    require(manifest.get("unit_contract_version") in (1, 2, 3, 4), "unsupported historical unit contract")
    require(manifest.get("unit_runs", {}).get(unit_id, {}).get("status", "pending") == "pending", "context must be captured before first start")
    if "reviewed_prior_ref" in context:
        require("prior_attempt_ref" not in context, "context cannot combine reviewed prior and an actual attempt")
        reviewed_prior(project, manifest, unit_id, context["reviewed_prior_ref"])
    if "prior_attempt_ref" in context:
        attempt, original = validate_attempt(project, context["prior_attempt_ref"], stack, cache, evidence_cache=evidence_cache)
        require(attempt["unit_id"] == unit_id, "continuation context belongs to another attempted unit")
        attempt_authority(original["manifest"], manifest)
        continuation_inventory(original, attempt, context["input_inventory"], project=project,
                               current_record=context, current_manifest=manifest)
        references = manifest.get("attempt_history", {}).get(unit_id, [])
        require(any(same(context["prior_attempt_ref"], item) for item in references), "continuation omitted its original attempt")
        for inherited in attempt_refs(attempt["post_manifest"]).get(unit_id, []):
            require(any(same(inherited, item) for item in references), "continuation dropped an earlier attempt")
        run_id = manifest.get("unit_runs", {}).get(unit_id, {}).get("run_id")
        require(isinstance(run_id, str) and run_id.strip(), "continuation requires a new run identity")
        for item in references:
            prior, _ = validate_attempt(project, item, stack, cache, evidence_cache=evidence_cache)
            require(prior["run_id"] != run_id, "continuation reuses an old run identity")
        observation = validate_runtime_observation(project, context["input_inventory"].get("runtime_observation_ref"))
        require(api().timestamp(attempt["captured_at"]) <= api().timestamp(observation["started_at"])
                and api().timestamp(observation["observed_at"]) <= api().timestamp(context["captured_at"]),
                "continuation runtime observation must be fresh and precede the new context")
        require(same(manifest["unit_runs"][unit_id].get("findings", []), attempt["run"].get("findings", [])),
                "continuation dropped run findings")
        old_checks = {item["check_id"]: item for item in attempt["checks"]}
        for check in attempt_checks(manifest, unit_id):
            require(check.get("execution_status") == "not_run" and not check.get("evidence")
                    or check_inputs.enabled(manifest) and check.get("reused_from") and check.get("execution_status") == "passed",
                    "continuation cannot reuse old acceptance results without an applicable independent seal")
            require(same(check.get("findings", []), old_checks[check["check_id"]].get("findings", [])),
                    "continuation dropped check findings")
    checker = historical_checker(project, manifest, context, stack=stack, cache=cache, evidence_cache=evidence_cache)
    checker._history_capturing = unit_id
    validate_reused_checks(checker, context, context["input_inventory"])
    report = checker.run("implementation", unit_action="start", unit_id=unit_id)
    require(report["result"] == "passed", "original execution context was not authorized/startable: " + json.dumps(report["issues"]))
    reviewed = prepare_inventory(checker, unit_id, context["input_inventory"])
    require(same(reviewed, context["input_inventory"]), "captured inventory does not match original context")
    remember_evidence(checker)
    cache[cache_key] = copy.deepcopy(context)
    _snapshot_hash_owner.get().history_result(cache, cache_key, remember=True)
    del cache[visiting]
    return context


@source_archive_invocation
def capture_context(project, manifest, unit_id, inventory, *, evidence_cache=None, prior_attempt_ref=None,
                    reviewed_prior_ref=None, _cache=None):
    require(manifest.get("unit_contract_version") in (2, 3, 4), "migrate legacy records before capturing current execution")
    require(manifest.get("unit_runs", {}).get(unit_id, {}).get("status", "pending") == "pending", "capture context before starting the unit")
    if reviewed_prior_ref is not None:
        require(prior_attempt_ref is None, "context cannot combine reviewed prior and an actual attempt")
        reviewed_prior(project, manifest, unit_id, reviewed_prior_ref)
    checker = api().Checker(project, copy.deepcopy(manifest), evidence_cache=evidence_cache)
    cache = _cache if _cache is not None else {}
    checker._history_stack, checker._history_cache = (), cache
    checker._history_capturing = unit_id
    report = checker.run("implementation", unit_action="start", unit_id=unit_id, require_current=True)
    require(report["result"] == "passed", "cannot capture unauthorized/unstartable context: " + json.dumps(report["issues"]))
    reviewed = prepare_inventory(checker, unit_id, inventory)
    directory = HISTORY + "/contexts/" + uuid.uuid4().hex
    context = {"event": "unit_execution_context", "version": VERSION, "validation_contract": CONTRACT, "unit_id": unit_id,
               "captured_at": utcnow(), "toolchain": api().toolchain_identity(), "manifest": copy.deepcopy(manifest),
               "input_inventory": reviewed, "snapshot_root": directory + "/files"}
    if prior_attempt_ref is not None:
        context["prior_attempt_ref"] = copy.deepcopy(prior_attempt_ref)
    if reviewed_prior_ref is not None:
        context["reviewed_prior_ref"] = copy.deepcopy(reviewed_prior_ref)
    context["files"] = freeze_files(project, manifest, directory, reviewed["execution_inputs"], checker=checker)
    reference = store_record(project, "contexts", context, directory)
    if prior_attempt_ref is not None or reviewed_prior_ref is not None:
        validate_context(project, reference, unit_id, cache=cache, evidence_cache=evidence_cache)
    return reference


@snapshot_hash_invocation
@metrics.timed("history_completion")
def validate_completion(project, reference, stack=(), cache=None, *, evidence_cache=None):
    metrics.count("history_completion_requests")
    cache = cache if cache is not None else {}
    identity = reference.get("content_hash") if isinstance(reference, dict) else None
    require(identity not in stack and len(stack) < 128, "cyclic/excessive completion history")
    stack = stack + (identity,)
    completed = read_ref(project, reference)
    require(completed.get("event") == "unit_completion" and completed.get("version") == VERSION, "unsupported completion envelope")
    unit = completed["unit_id"]
    require(isinstance(completed.get("run_id"), str) and completed["run_id"].strip(), "actual run identity required")
    run_identity = ("run_identity", unit, completed["run_id"])
    content_identity = sha(physical(project, reference["path"]).read_bytes())
    require(run_identity not in cache or cache[run_identity] == content_identity,
            "unit/run identity is reused by a different completion: " + unit + " / " + completed["run_id"])
    cache[run_identity] = content_identity
    cache_key = ("completion", identity)
    if cache_key in cache and _snapshot_hash_owner.get().history_result(cache, cache_key):
        metrics.count("history_completion_cache_hits")
        return copy.deepcopy(cache[cache_key])
    context = validate_context(project, completed["context_ref"], unit, stack, cache, evidence_cache=evidence_cache)
    run = completed["run"]
    reviewed_run_identity(project, context, run)
    require(run.get("status") == "completed" and "completion_ref" not in run, "only an actual completed run can be preserved")
    require("run_id" not in run or run["run_id"] == completed["run_id"], "completion identity differs from actual run")
    if "prior_attempt_ref" in context:
        require(run.get("run_id") == context["manifest"]["unit_runs"][unit]["run_id"],
                "completion identity differs from its continuation context")
    require(api().timestamp(context["captured_at"]) <= api().timestamp(run.get("started_at")), "execution context must predate start")
    manifest = copy.deepcopy(context["manifest"])
    manifest.setdefault("execution_contexts", {})[unit] = completed["context_ref"]
    manifest.setdefault("unit_runs", {})[unit] = copy.deepcopy(run)
    checks = {x["check_id"]: x for x in completed["checks"]}
    owned = {key for key, value in manifest["unit_plan"]["acceptance"].items() if value["owner_unit"] == unit}
    require(set(checks) == owned and len(checks) == len(completed["checks"]), "completion must retain every owned check exactly once")
    post_manifest = completed["post_manifest"]
    # Generation accounting grows during execution. Validate actual run outputs
    # against their frozen post-run ledger, keeping all authority from context.
    for field in ("evidence_accounting", "evidence_storage"):
        if field in post_manifest:
            manifest[field] = copy.deepcopy(post_manifest[field])
    require(same(post_manifest.get("unit_plan"), context["manifest"]["unit_plan"]), "post-run plan differs from original execution plan")
    for field in ("implementation_gate", "active_baseline", "approved_baseline_id", "product_scope"):
        require(same(post_manifest.get(field), context["manifest"].get(field)), "post-run authority/baseline differs from original execution context: " + field)
    require(post_manifest.get("artifacts", {}).get("development-plan", {}).get("content_hash") == context["manifest"]["artifacts"]["development-plan"]["content_hash"], "post-run plan prose differs from original execution plan")
    require(same(post_manifest.get("unit_runs", {}).get(unit), run), "post-run manifest claims a different execution")
    require(same(post_manifest.get("execution_contexts", {}).get(unit), completed["context_ref"]), "post-run manifest binds a different execution context")
    post_checks = {check["check_id"]: check for check in post_manifest["verification"]["checks"] if check["check_id"] in owned}
    require(same(post_checks, checks), "post-run manifest claims different actual QA results")
    for index, check in enumerate(manifest["verification"]["checks"]):
        if check["check_id"] in owned:
            actual = checks[check["check_id"]]
            require(same({k: v for k, v in actual.items() if k not in EXECUTION_KEYS}, {k: v for k, v in check.items() if k not in EXECUTION_KEYS}), "completion cannot change its original QA definition")
            manifest["verification"]["checks"][index] = copy.deepcopy(actual)
    validate_continuation_findings(project, context, run, completed["checks"], completed["input_inventory"])
    promotions = completed.get("prototype_promotions", [])
    def planned(records):
        return [{k: v for k, v in record.items() if k not in ("started_at", "receipt")} for record in records]
    require(same(planned(promotions), planned(manifest.get("prototype_promotions", []))), "completion changed/dropped planned prototype promotion bindings")
    manifest["prototype_promotions"] = promotions
    checker = historical_checker(project, manifest, context, completed, stack, cache, evidence_cache=evidence_cache)
    checker._history_validating_run = unit
    canonical_evidence = {check: {path: {context["files"][path]["content_hash"], completed["files"][path]["content_hash"]}
                                 for path in context["input_inventory"]["canonical_hashes"]} for check in owned}
    checker._history_canonical_evidence = canonical_evidence
    report = checker.run("implementation", unit_action="complete", unit_id=unit)
    require(report["result"] == "passed", "original completed run is invalid: " + json.dumps(report["issues"]))
    # Promotion QA and Git provenance are checked in their original plan, never rebound.
    checker.manifest["prototype_promotions"] = [record for record in promotions if record.get("unit_id") == unit]
    checker.promotions(release=True)
    require(not checker.issues, "original promotion acceptance is invalid: " + json.dumps(checker.issues))
    validate_completion_inventory(context, completed["input_inventory"], completed["checks"])
    post = historical_checker(project, completed["post_manifest"], context, completed, stack, cache, original_canonical=False, evidence_cache=evidence_cache)
    post._history_validating_run = unit
    post._history_canonical_evidence = canonical_evidence
    post_report = post.run("implementation", unit_action="complete", unit_id=unit)
    require(post_report["result"] == "passed", "actual post-run owner records do not validate: " + json.dumps(post_report["issues"]))
    require(same(prepare_inventory(post, unit, completed["input_inventory"]), completed["input_inventory"]), "completed execution input inventory differs from actual snapshots")
    remember_evidence(checker)
    remember_evidence(post)
    for check in completed["checks"]:
        if check.get("execution_status") in ("passed", "failed"):
            if (reviewed_observation(check, checker._unit_history.reviewed_checks)
                    and reviewed_observation(check, post._unit_history.reviewed_checks)):
                continue
            require(same(check.get("evaluated_execution_inputs"), check_inputs.expected(completed["input_inventory"], check["check_id"])), "executed check lacks matching test-time execution input observation")
            validate_check_runtime(project, context, check, run, accepting=True)
    cache[cache_key] = copy.deepcopy((completed, context))
    _snapshot_hash_owner.get().history_result(cache, cache_key, remember=True)
    return completed, context


def validate_completion_inventory(context, current, checks):
    ignored = {"execution_fingerprints", "check_execution_fingerprints", "canonical_hashes", "review"}
    require(same({k: v for k, v in current.items() if k not in ignored},
                 {k: v for k, v in context["input_inventory"].items() if k not in ignored}), "relevant acceptance inputs changed during execution")
    if not same(current["canonical_hashes"], context["input_inventory"]["canonical_hashes"]):
        threshold = max([api().timestamp(context["captured_at"])] + [api().timestamp(check["executed_at"]) for check in checks if check.get("execution_status") in ("passed", "failed")])
        require(api().timestamp(current["review"]["reviewed_at"]) >= threshold, "canonical owner output changed; supply a fresh current inventory review after the check evidence")


@source_archive_invocation
def capture_completion(project, manifest, unit_id, context_ref, run_id, inventory=None, *, evidence_cache=None):
    context = validate_context(project, context_ref, unit_id, evidence_cache=evidence_cache)
    run = manifest.get("unit_runs", {}).get(unit_id, {})
    require(run.get("status") == "completed" and "completion_ref" not in run, "supply the actual completed run; helper does not execute or complete work")
    original = context["manifest"]
    require(same(original["unit_plan"], manifest["unit_plan"]), "plan changed during execution; reconcile before capture")
    require(original["artifacts"]["development-plan"]["content_hash"] == manifest["artifacts"]["development-plan"]["content_hash"], "plan prose changed during execution")
    completed_inventory = prepare_inventory(api().Checker(project, manifest, evidence_cache=evidence_cache), unit_id, inventory or context["input_inventory"])
    owned = {key for key, value in manifest["unit_plan"]["acceptance"].items() if value["owner_unit"] == unit_id}
    actual_checks = [copy.deepcopy(x) for x in manifest["verification"]["checks"] if x["check_id"] in owned]
    validate_completion_inventory(context, completed_inventory, actual_checks)
    checker = api().Checker(project, copy.deepcopy(manifest), evidence_cache=evidence_cache)
    checker.manifest.setdefault("execution_contexts", {})[unit_id] = context_ref
    checker._history_capture_completed = unit_id
    checker._history_completion_inventory = {unit_id: completed_inventory}
    report = checker.run("implementation", unit_action="complete", unit_id=unit_id, require_current=True, projections=False)
    require(report["result"] == "passed", "cannot capture incomplete/unverified run: " + json.dumps(report["issues"]))
    directory = HISTORY + "/completions/" + uuid.uuid4().hex
    post_manifest = copy.deepcopy(manifest)
    post_manifest.setdefault("execution_contexts", {})[unit_id] = copy.deepcopy(context_ref)
    record = {"event": "unit_completion", "version": VERSION, "unit_id": unit_id, "run_id": run_id, "context_ref": context_ref,
              "run": copy.deepcopy(run), "checks": actual_checks, "post_manifest": post_manifest,
              "input_inventory": completed_inventory, "prototype_promotions": copy.deepcopy(manifest.get("prototype_promotions", [])),
              "snapshot_root": directory + "/files"}
    record["files"] = freeze_files(project, manifest, directory, completed_inventory["execution_inputs"], checker=checker)
    ref = store_record(project, "completions", record, directory)
    validate_completion(project, ref, evidence_cache=evidence_cache)
    return ref


def validate_runtime_observation(project, reference):
    record = read_ref(project, reference)
    require(record.get("event") == "runtime_observation" and record.get("version") == VERSION,
            "unsupported runtime observation")
    require(api().timestamp(record["started_at"]) <= api().timestamp(record["observed_at"]) <= api().timestamp(utcnow()),
            "invalid runtime observation chronology")
    probes = record.get("probes")
    require(isinstance(probes, dict) and probes, "actual runtime probes required")
    environment = {}
    for key, probe in probes.items():
        command = probe.get("command")
        require(isinstance(key, str) and key.strip() and isinstance(command, list) and command
                and all(isinstance(arg, str) and arg for arg in command) and Path(command[0]).is_absolute(),
                "runtime probe requires a named absolute executable and argument list")
        require(probe.get("returncode") == 0 and isinstance(probe.get("stdout"), str) and probe["stdout"].strip()
                and isinstance(probe.get("stderr"), str), "runtime probe must succeed with an observed identity")
        require(all(len(probe[name].encode("utf-8")) <= 65536 for name in ("stdout", "stderr")),
                "runtime identity output exceeds 64 KiB per stream")
        environment[key] = probe["stdout"].strip()
    require(same(environment, record.get("environment")), "runtime identity differs from actual probe output")
    return record


def observe_runtime(project, probes):
    """Execute explicit local identity probes once; validation only reads their receipts."""
    require(isinstance(probes, dict) and probes, "runtime probes must map identity names to argument lists")
    record = {"event": "runtime_observation", "version": VERSION, "started_at": utcnow(), "probes": {}, "environment": {}}
    for key, command in probes.items():
        require(isinstance(key, str) and key.strip() and isinstance(command, list) and command
                and all(isinstance(arg, str) and arg for arg in command) and Path(command[0]).is_absolute(),
                "runtime probe requires a named absolute executable and argument list")
        try:
            result = subprocess.run(command, cwd=Path(project).resolve(), capture_output=True, text=True, timeout=30, check=False)
        except subprocess.TimeoutExpired as error:
            raise ValueError("runtime identity probe timed out: " + key) from error
        require(result.returncode == 0 and result.stdout.strip(), "runtime identity probe failed: " + key)
        require(all(len(value.encode("utf-8")) <= 65536 for value in (result.stdout, result.stderr)),
                "runtime identity output exceeds 64 KiB per stream: " + key)
        record["probes"][key] = {"command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        record["environment"][key] = result.stdout.strip()
    record["observed_at"] = utcnow()
    return store_record(project, "runtime-observations", record)


def validate_check_runtime(project, context, check, run, *, accepting):
    """Continuation acceptance needs an actual runtime or a separately validated original seal."""
    if check.get("reused_from"):
        require(check_inputs.enabled(context["manifest"]), "sealed reuse requires checker/unit contract 3")
        return  # validate_reused_checks verifies original runtime plus current environment.
    if "prior_attempt_ref" not in context and "runtime_observation_ref" not in context["input_inventory"]:
        return
    reference = check.get("runtime_observation_ref")
    if reference is None and not accepting:
        return  # Preserve unfinished observations without granting acceptance.
    require(reference is not None, "continuation acceptance requires an execution-time runtime observation")
    observation = validate_runtime_observation(project, reference)
    require(api().timestamp(run["started_at"]) <= api().timestamp(observation["started_at"])
            and api().timestamp(observation["observed_at"]) <= api().timestamp(check["executed_at"]),
            "runtime observation must be made within this run before its check result")
    if accepting:
        require(same(observation["environment"], context["input_inventory"]["environment"]),
                "executed runtime changed; preserve this attempt and capture a new continuation context")


def attempt_checks(manifest, unit):
    owned = {key for key, allocation in manifest["unit_plan"]["acceptance"].items() if allocation["owner_unit"] == unit}
    checks = [copy.deepcopy(check) for check in manifest["verification"]["checks"] if check["check_id"] in owned]
    require(len(checks) == len(owned) and {check["check_id"] for check in checks} == owned,
            "attempt must retain every owned check exactly once, including unrun checks")
    return checks


def validate_continuation_findings(project, context, run, checks, inventory):
    """Carry finding identities forward; closure points to fresh current evidence."""
    if "prior_attempt_ref" not in context:
        return
    unit = context["unit_id"]
    original = context["manifest"]
    current_checks = {check["check_id"]: check for check in checks}
    collections = [(original["unit_runs"][unit].get("findings", []), run.get("findings", []), unit)]
    for before in attempt_checks(original, unit):
        require(before["check_id"] in current_checks, "continuation omitted inherited check findings")
        collections.append((before.get("findings", []), current_checks[before["check_id"]].get("findings", []), before["check_id"]))
    for prior, current, label in collections:
        merged_findings(prior, current)  # Retain ordinary classification validation.
        for finding in prior:
            matches = [item for item in current if all(name == "status"
                                                        or name == "closure" and finding["status"] == "open" and item.get("status") == "closed"
                                                        or name in item and same(value, item[name])
                                                        for name, value in finding.items())]
            require(len(matches) == 1, "continuation dropped or rewrote inherited finding: " + label)
            preserved = matches[0]
            if finding["status"] == "open" and preserved["status"] == "closed":
                closure = preserved.get("closure", {})
                require(isinstance(closure, dict) and isinstance(closure.get("rationale"), str)
                        and closure["rationale"].strip(), "inherited finding closure needs evidence-backed rationale: " + label)
                check_ids = closure.get("check_ids")
                require(isinstance(check_ids, list) and check_ids and all(isinstance(key, str) for key in check_ids)
                        and len(set(check_ids)) == len(check_ids) and set(check_ids) <= set(current_checks),
                        "inherited finding closure must name current owned checks: " + label)
                closed = api().timestamp(closure.get("closed_at"))
                finished = api().timestamp(run["completed_at"]) if run.get("completed_at") else api().timestamp(utcnow())
                require(api().timestamp(run["started_at"]) <= closed <= finished,
                        "inherited finding closure is outside the continuation run: " + label)
                for key in check_ids:
                    check = current_checks[key]
                    require(check.get("execution_status") == "passed" and check.get("executor") and check.get("evidence")
                            and api().timestamp(run["started_at"]) <= api().timestamp(check.get("executed_at")) <= closed,
                            "inherited finding closure needs fresh passed check evidence: " + key)
                    require(same(check.get("evaluated_execution_inputs"), check_inputs.expected(inventory, check["check_id"])),
                            "inherited finding closure cannot use stale check inputs: " + key)
                    validate_check_runtime(project, context, check, run, accepting=True)


def attempt_authority(original, current):
    for field in ("unit_plan", "implementation_gate", "active_baseline", "approved_baseline_id", "product_scope"):
        require(same(original.get(field), current.get(field)), "attempt authority/acceptance changed: " + field)
    require(original["artifacts"]["development-plan"]["content_hash"] == current["artifacts"]["development-plan"]["content_hash"],
            "attempt plan prose changed")


def canonical_alternatives(context, record):
    return {check["check_id"]: {path: {value, record["input_inventory"]["canonical_hashes"][path]}
                               for path, value in context["input_inventory"]["canonical_hashes"].items()}
            for check in record["checks"]}


def attempt_observation_validity(checks, inventory):
    executed = [check for check in checks if check.get("execution_status") in ("passed", "failed")]
    require(all(isinstance(check.get("evaluated_execution_inputs"), dict) and check["evaluated_execution_inputs"]
                for check in executed), "executed attempt results need their original input observations")
    return ("unverified_stale_inputs" if any(not same(check["evaluated_execution_inputs"], check_inputs.expected(inventory, check["check_id"]))
                                             for check in executed) else "matched")


def unfinished_evidence_alternatives(project, context, record, checker):
    """Allow archived stale bytes only while validating a nonaccepting attempt."""
    alternatives = canonical_alternatives(context, record)
    if record["observation_validity"] != "unverified_stale_inputs":
        return alternatives
    canonical = context["input_inventory"]["canonical_hashes"]
    for check in record["checks"]:
        if check.get("execution_status") not in ("passed", "failed"):
            continue
        fingerprints = check["evaluated_execution_inputs"]
        require(set(fingerprints) == set(check_inputs.expected(record["input_inventory"], check["check_id"])),
                "old attempt observation omits declared execution inputs")
        observed_hashes = {}
        for path, fingerprint in fingerprints.items():
            physical(project, path)
            selection = record["input_inventory"]["execution_inputs"][path]
            require(fingerprint.get("mode") == selection["mode"] and type(fingerprint.get("exists")) is bool,
                    "invalid original execution input observation")
            if not fingerprint["exists"]:
                continue
            if fingerprint["mode"] == "file":
                observed_hashes[path] = fingerprint.get("content_hash")
            elif fingerprint["mode"] == "tree":
                require(isinstance(fingerprint.get("members"), dict), "original tree membership required")
                for member, value in fingerprint["members"].items():
                    physical(project, path.rstrip("/") + "/" + member.rstrip("/"))
                    if not member.endswith("/"):
                        observed_hashes[path.rstrip("/") + "/" + member] = value
        for path, value in observed_hashes.items():
            require(isinstance(value, str) and api().HASH_RE.fullmatch(value), "invalid original input digest")
        hashes, _ = checker.source_inventory(check, "evaluated_source_hashes")
        for path, value in hashes.items():
            if path not in canonical and path in observed_hashes:
                require(api().hash_matches(value, observed_hashes[path]),
                        "old source hash differs from original execution observation: " + path)
                alternatives[check["check_id"]][path] = {observed_hashes[path]}
    return alternatives


@snapshot_hash_invocation
@metrics.timed("history_attempt")
def validate_attempt(project, reference, stack=(), cache=None, *, evidence_cache=None):
    """Validate preserved execution without ever requiring or granting completion."""
    metrics.count("history_attempt_requests")
    cache = cache if cache is not None else {}
    record = read_ref(project, reference)
    identity = reference["content_hash"]
    marker = ("attempt", identity)
    require(identity not in stack and len(stack) < 128, "cyclic/excessive attempt history")
    if marker in cache and _snapshot_hash_owner.get().history_result(cache, marker):
        metrics.count("history_attempt_cache_hits")
        return copy.deepcopy(cache[marker])
    require(record.get("event") == "unit_attempt" and record.get("version") == VERSION
            and record.get("validation_contract") == CONTRACT and record.get("acceptance") == "not_completed",
            "unsupported unfinished attempt envelope")
    unit, run = record["unit_id"], record["run"]
    require(record.get("outcome") in ("failed", "interrupted"), "unfinished attempt outcome required")
    require(run.get("status") in ("running", "blocked") and not any(key in run for key in ("completed_at", "completion_ref", "attempt_ref")),
            "attempt must retain an actual unfinished run")
    require(isinstance(record.get("run_id"), str) and record["run_id"].strip(), "actual attempt run identity required")
    require("run_id" not in run or run["run_id"] == record["run_id"], "attempt run identity differs from actual run")
    cache_key = ("attempt_run", unit, record["run_id"])
    require(cache_key not in cache or cache[cache_key] == identity, "attempt run identity was reused")
    cache[cache_key] = identity
    context = validate_context(project, record["context_ref"], unit, stack + (identity,), cache, evidence_cache=evidence_cache)
    reviewed_run_identity(project, context, run)
    if "prior_attempt_ref" in context:
        require(run.get("run_id") == context["manifest"]["unit_runs"][unit]["run_id"],
                "attempt identity differs from its continuation context")
    require(api().timestamp(context["captured_at"]) <= api().timestamp(run["started_at"]) <= api().timestamp(record["captured_at"]) <= api().timestamp(utcnow()),
            "invalid attempt chronology")
    post_manifest = record["post_manifest"]
    attempt_authority(context["manifest"], post_manifest)
    for inherited in attempt_refs(context["manifest"]).get(unit, []):
        require(any(same(inherited, item) for item in attempt_refs(post_manifest).get(unit, [])),
                "attempt dropped earlier unfinished history")
    require(same(post_manifest.get("unit_runs", {}).get(unit), run), "attempt differs from actual post-run status")
    require(same(post_manifest.get("execution_contexts", {}).get(unit), record["context_ref"]), "attempt binds another execution context")
    require(same(attempt_checks(post_manifest, unit), record.get("checks")), "attempt omitted or changed actual results")
    validate_continuation_findings(project, context, run, record["checks"], record["input_inventory"])
    actual = {check["check_id"]: check for check in record["checks"]}
    for original in attempt_checks(context["manifest"], unit):
        require(same({k: v for k, v in original.items() if k not in EXECUTION_KEYS},
                     {k: v for k, v in actual[original["check_id"]].items() if k not in EXECUTION_KEYS}),
                "attempt cannot change original QA definitions")
    validate_completion_inventory(context, record["input_inventory"], record["checks"])
    require(record.get("observation_validity") == attempt_observation_validity(record["checks"], record["input_inventory"]),
            "attempt observation validity differs from its actual input observations")
    for check in record["checks"]:
        if check.get("execution_status") in ("passed", "failed"):
            require(check.get("reused_from") and check_inputs.enabled(post_manifest) or api().timestamp(run["started_at"]) <= api().timestamp(check["executed_at"]) <= api().timestamp(record["captured_at"]),
                    "attempt check was not executed within the actual run")
            require(check.get("evaluated_plan_hash") == run["development_plan_hash"], "attempt check belongs to another plan")
            require(check.get("reused_from") and check_inputs.enabled(post_manifest) or not check.get("run_id") or check["run_id"] == record["run_id"], "attempt check belongs to another run")
            validate_check_runtime(project, context, check, run, accepting=False)
    for original_canonical in (True, False):
        manifest = copy.deepcopy(post_manifest)
        if original_canonical:
            # Original authoring provenance stays bound to the original document bytes.
            manifest["artifacts"] = copy.deepcopy(context["manifest"]["artifacts"])
            for field in ("bundle", "verification"):
                if field == "verification":
                    manifest[field] = copy.deepcopy(context["manifest"][field])
                    manifest[field]["checks"] = [actual.get(check["check_id"], check) for check in manifest[field]["checks"]]
                elif field in context["manifest"]:
                    manifest[field] = copy.deepcopy(context["manifest"][field])
        checker = historical_checker(project, manifest, context, record, stack + (identity,), cache,
                                     original_canonical=original_canonical, evidence_cache=evidence_cache)
        checker._history_validating_run = unit
        checker._history_nonaccepting_attempt = unit
        checker._history_canonical_evidence = unfinished_evidence_alternatives(project, context, record, checker)
        report = checker.run("implementation", unit_action="start", unit_id=unit)
        require(report["result"] == "passed", "unfinished attempt records are invalid: " + json.dumps(report["issues"]))
        if not original_canonical:
            require(same(prepare_inventory(checker, unit, record["input_inventory"]), record["input_inventory"]),
                    "attempt inventory differs from preserved snapshots")
        remember_evidence(checker)
    cache[marker] = copy.deepcopy((record, context))
    _snapshot_hash_owner.get().history_result(cache, marker, remember=True)
    return record, context


@source_archive_invocation
def capture_attempt(project, manifest, unit_id, context_ref, run_id, outcome, inventory=None, *, evidence_cache=None):
    cache = {}
    context = validate_context(project, context_ref, unit_id, cache=cache, evidence_cache=evidence_cache)
    run = manifest.get("unit_runs", {}).get(unit_id, {})
    require(run.get("status") in ("running", "blocked") and "attempt_ref" not in run,
            "supply an actual unarchived running/blocked attempt; completed work uses capture-completion")
    attempt_authority(context["manifest"], manifest)
    checker = api().Checker(project, copy.deepcopy(manifest), evidence_cache=evidence_cache)
    reviewed = prepare_inventory(checker, unit_id, inventory or context["input_inventory"])
    checks = attempt_checks(manifest, unit_id)
    validate_completion_inventory(context, reviewed, checks)
    directory = HISTORY + "/attempts/" + uuid.uuid4().hex
    record = {"event": "unit_attempt", "version": VERSION, "validation_contract": CONTRACT,
              "acceptance": "not_completed", "unit_id": unit_id, "run_id": run_id, "outcome": outcome,
              "captured_at": utcnow(), "context_ref": copy.deepcopy(context_ref), "run": copy.deepcopy(run),
              "checks": checks, "post_manifest": copy.deepcopy(manifest), "input_inventory": reviewed,
              "observation_validity": attempt_observation_validity(checks, reviewed),
              "snapshot_root": directory + "/files"}
    record["files"] = freeze_files(project, manifest, directory, reviewed["execution_inputs"], checker=checker)
    reference = store_record(project, "attempts", record, directory)
    validate_attempt(project, reference, cache=cache, evidence_cache=evidence_cache)
    return reference


def attempt_refs(manifest):
    references = {key: list(value) for key, value in manifest.get("attempt_history", {}).items()}
    for unit, run in manifest.get("unit_runs", {}).items():
        if "attempt_ref" in run:
            references.setdefault(unit, []).append(run["attempt_ref"])
    return references


def _policy_successor(project, attempt, reviewed, *, current_record=None, current_manifest=None):
    """Only exact portable-policy ancestry can replace one preserved file input.

    This permits no execution/acceptance and never changes the old envelope.
    Historical validation reads the new context's frozen policy, not today's file.
    """
    from evidence import policy as policies
    from evidence.io import _open_regular, _verify_stable

    logical = "forge/evidence-policy.json"
    original = attempt["input_inventory"]
    for inventory in (original, reviewed):
        require(same(inventory.get("execution_inputs", {}).get(logical), {"mode": "file"}),
                "policy successor requires the canonical file selection")
        for name, selection in inventory["execution_inputs"].items():
            require(not (selection.get("mode") == "tree" and logical.startswith(name.rstrip("/") + "/")),
                    "policy successor cannot replace a tree-selected policy")
        fingerprint = inventory.get("execution_fingerprints", {}).get(logical)
        require(isinstance(fingerprint, dict) and set(fingerprint) == {"mode", "exists", "content_hash"}
                and fingerprint.get("mode") == "file" and fingerprint.get("exists") is True
                and isinstance(fingerprint.get("content_hash"), str)
                and re.fullmatch(r"[a-f0-9]{64}", fingerprint["content_hash"]),
                "policy successor requires an exact existing-file fingerprint")
    for manifest in (attempt["post_manifest"], current_manifest or {}):
        storage = manifest.get("evidence_storage", {})
        require(isinstance(storage, dict) and storage.get("policy_path", logical) == logical,
                "policy successor cannot substitute another policy path")

    def read_policy(record, fingerprint):
        if record is None:
            target = physical(project, logical)
        else:
            reference = record.get("files", {}).get(logical)
            require(isinstance(reference, dict) and set(reference) == REF_KEYS
                    and reference["path"] == record["snapshot_root"] + "/" + logical
                    and reference["content_hash"] == fingerprint["content_hash"],
                    "policy successor requires exact frozen original bytes")
            target = archived_source_path(project, reference)
        path, descriptor, info = _open_regular(target)
        with os.fdopen(descriptor, "rb") as stream:
            require(info.st_size <= policies.MAX_POLICY_BYTES, "policy successor exceeds policy byte bound")
            raw = stream.read(policies.MAX_POLICY_BYTES + 1)
            _verify_stable(path, stream.fileno(), info)
        require(len(raw) <= policies.MAX_POLICY_BYTES and sha(raw) == fingerprint["content_hash"],
                "policy successor raw bytes differ from the observed fingerprint")
        owner = _snapshot_hash_owner.get()
        if owner is not None:
            require(owner.file_hash(target) == fingerprint["content_hash"], "policy successor changed during validation")
        return raw

    before_raw = read_policy(attempt, original["execution_fingerprints"][logical])
    after_raw = read_policy(current_record, reviewed["execution_fingerprints"][logical])
    before = policies.validate_policy(policies._raw_policy(before_raw))
    after = policies.validate_policy(policies._raw_policy(after_raw))
    require("policy_lineage" in after and not same(before, after), "policy replacement is not a strict lineage successor")
    ancestor = policies.resolve_historical_policy(after, policies._digest(before))
    require(same(ancestor, before), "policy successor does not preserve the full original policy")
    if "policy_lineage" in ancestor:
        require(before_raw == policies._setup_bytes(ancestor), "original policy differs from supported ancestor serialization")
    else:
        base = after["policy_lineage"]["base"]
        require(before_raw == base["raw_utf8"].encode("utf-8") and sha(before_raw) == base["raw_sha256"],
                "policy successor differs from the exact original raw anchor")
    require(after_raw == policies._setup_bytes(after), "current policy differs from supported successor serialization")
    return True


def continuation_inventory(context, attempt, reviewed, *, project=None, current_record=None, current_manifest=None):
    ignored = {"environment", "runtime_observation_ref", "canonical_hashes", "review",
               "execution_inputs", "execution_fingerprints", "check_execution_fingerprints"}
    original = attempt["input_inventory"]
    require(same({k: v for k, v in original.items() if k not in ignored},
                 {k: v for k, v in reviewed.items() if k not in ignored}),
            "continuation changed relevant acceptance definitions or preserved work")
    # A fresh attempt may add reviewed executor inputs, retaining the exact old
    # selections. Version 2 retains byte identity; version 3 separately checks
    # applicability before retaining any independently sealed result.
    for inventory in (original, reviewed):
        selections, fingerprints = inventory.get("execution_inputs"), inventory.get("execution_fingerprints")
        require(isinstance(selections, dict) and selections and isinstance(fingerprints, dict)
                and set(selections) == set(fingerprints),
                "continuation execution inputs require every exact fingerprint")
    for path, selection in original["execution_inputs"].items():
        require(path in reviewed["execution_inputs"]
                and same(selection, reviewed["execution_inputs"][path]),
                "continuation changed or removed preserved execution input: " + path)
        if not same(original["execution_fingerprints"][path], reviewed["execution_fingerprints"][path]):
            if path == "forge/evidence-policy.json":
                require(project is not None, "policy successor requires the original project")
                _policy_successor(project, attempt, reviewed, current_record=current_record, current_manifest=current_manifest)
            else:
                # Contract 3 can rerun changed checks; that never replaces policy lineage.
                require(current_manifest is not None and check_inputs.enabled(current_manifest),
                        "continuation changed or removed preserved execution input: " + path)
    require(api().timestamp(reviewed["review"]["reviewed_at"]) >= api().timestamp(attempt["captured_at"]),
            "continuation needs a fresh owner review after attempt capture")
    attempt_authority(context["manifest"], attempt["post_manifest"])


def _without_reuse(check):
    return {key: value for key, value in check.items() if key not in ("seal_ref", "reused_from")}


def _settlement(project, reference, check, unit, run_id, sealed_at):
    record = read_ref(project, reference)
    require(record.get("event") == "execution_group_settlement" and record.get("version") == 1,
            "independent execution-group settlement required")
    require(record.get("unit_id") == unit and record.get("run_id") == run_id
            and isinstance(record.get("group_id"), str) and record["group_id"].strip()
            and isinstance(record.get("check_ids"), list) and check["check_id"] in record["check_ids"],
            "settlement belongs to another group/run/check")
    require(record.get("isolation") == "independent" and record.get("status") == "settled"
            and record.get("producer_state") == "stopped" and record.get("cleanup_state") == "complete"
            and record.get("accounting_state") == "complete"
            and all(record.get(key) == [] for key in ("pending_actions", "unknown_outcomes", "open_resources")),
            "execution group has unsettled producer, cleanup, accounting or outcomes")
    require(api().timestamp(check["executed_at"]) <= api().timestamp(record.get("completed_at"))
            <= api().timestamp(sealed_at), "settlement must follow actual observations and precede sealing")
    return record


def _seal_observation(checker, context, check, run, inventory):
    require(check_inputs.enabled(checker.manifest), "sealing requires checker/unit contract 3")
    require(check_inputs.fine_grained(check) and check["acceptance"].get("reuse_policy") == "deterministic_isolated",
            "only explicitly reviewed deterministic isolated checks can be sealed")
    require(check.get("execution_status") == "passed" and check.get("executor") and check.get("evidence"),
            "only actual passed observations can be sealed")
    require(check.get("run_id") == run.get("run_id") and check["run_id"], "seal needs the original actual run identity")
    require(api().timestamp(run["started_at"]) <= api().timestamp(check["executed_at"]) <= api().timestamp(utcnow()),
            "sealed observation is outside its original run")
    require(same(check.get("evaluated_execution_inputs"), check_inputs.expected(inventory, check["check_id"])),
            "sealed check inputs differ from actual observation")
    require(not any(item.get("status") != "closed" and (item.get("severity") in ("P0", "P1")
                    or item.get("release_effect") == "blocking")
                    for item in check.get("findings", []) + run.get("findings", [])), "blocking findings prevent sealing")
    hashes, _ = checker.source_inventory(check, "evaluated_source_hashes")
    require(check_inputs.required_paths(checker, check) <= set(hashes), "sealed observation omits required source hashes")
    for path, expected_hash in hashes.items():
        require(checker.snapshot(path, expected_hash, "implementation", "sealed_check_stale"), "sealed source changed: " + path)
    for evidence in check["evidence"]:
        require(checker.evidence_snapshot(evidence, "implementation", "sealed_check_evidence",
                                         checker.check_bindings(check, evidence=evidence)), "sealed evidence is unreadable or changed")
    validate_check_runtime(checker.project, context, check, run, accepting=True)
    checker.evidence_accounting(run_id=check["run_id"], unit_id=checker.manifest["unit_plan"]["acceptance"][check["check_id"]]["owner_unit"])


def seal_check(project, manifest, unit_id, check_id, settlement_ref, inventory=None, *, evidence_cache=None):
    """Compatibility entrypoint for one independently settled result."""
    return seal_checks(project, manifest, unit_id, [check_id], settlement_ref, inventory,
                       evidence_cache=evidence_cache)[check_id]


@source_archive_invocation
def seal_checks(project, manifest, unit_id, check_ids, settlement_ref, inventory=None, *, evidence_cache=None):
    """One gate preflight for a settled group, with a bounded seal per check."""
    require(check_inputs.enabled(manifest), "sealing requires checker/unit contract 3")
    require(isinstance(check_ids, list) and check_ids and len(check_ids) == len(set(check_ids)), "unique check IDs required")
    require(all(manifest["unit_plan"]["acceptance"][key]["owner_unit"] == unit_id for key in check_ids),
            "seal check belongs to another unit")
    run = manifest["unit_runs"][unit_id]
    require(run.get("status") in ("running", "blocked") and "attempt_ref" not in run,
            "seal the independently settled result before archiving/interruption")
    reference = manifest["execution_contexts"][unit_id]
    context = validate_context(project, reference, unit_id, evidence_cache=evidence_cache)
    checker = api().Checker(project, copy.deepcopy(manifest), evidence_cache=evidence_cache)
    report = checker.run("implementation", unit_action="start", unit_id=unit_id, require_current=True)
    require(report["result"] == "passed", "cannot seal invalid current execution: " + json.dumps(report["issues"]))
    reviewed = prepare_inventory(checker, unit_id, inventory or context["input_inventory"])
    checks = {check["check_id"]: check for check in manifest["verification"]["checks"]}
    sealed_at = utcnow()
    for key in check_ids:
        check = checks[key]
        require("reused_from" not in check, "an inherited result retains its original seal")
        validate_completion_inventory(context, reviewed, [check])
        _seal_observation(checker, context, check, run, reviewed)
        _settlement(project, settlement_ref, check, unit_id, run["run_id"], sealed_at)
    results = {}
    for key in check_ids:
        check = checks[key]
        selected = {path: reviewed["execution_inputs"][path] for path in check_inputs.expected(reviewed, key)}
        record = {"event": "sealed_check", "version": 1, "unit_id": unit_id, "run_id": run["run_id"],
                  "check": copy.deepcopy(_without_reuse(check)), "context_ref": copy.deepcopy(reference),
                  "input_inventory": {"execution_inputs": selected, "execution_fingerprints": copy.deepcopy(check_inputs.expected(reviewed, key))},
                  "run": copy.deepcopy(run), "settlement_ref": copy.deepcopy(settlement_ref), "sealed_at": sealed_at,
                  "accounting": {field: copy.deepcopy(manifest[field]) for field in ("evidence_storage", "evidence_accounting") if field in manifest}}
        # Snapshot this observation's proof and selected dependencies. The earlier
        # context is referenced by context_ref, never duplicated in this record.
        directory = HISTORY + "/sealed-checks/" + uuid.uuid4().hex
        capture = {"check": copy.deepcopy(_without_reuse(check)), "settlement_ref": settlement_ref,
                   "canonical": [{"path": path} for path in reviewed["canonical_hashes"]], **record["accounting"]}
        record["snapshot_root"] = directory + "/files"
        record["files"] = freeze_files(project, capture, directory, selected, checker=checker)
        results[key] = store_record(project, "sealed-checks", record, directory)
    return results


def validate_sealed_check(project, reference, attempt, context, checker):
    seal = read_ref(project, reference)
    require(seal.get("event") == "sealed_check" and seal.get("version") == 1, "unsupported sealed check")
    require(seal.get("unit_id") == attempt["unit_id"] and seal.get("run_id") == attempt["run_id"]
            and same(seal.get("context_ref"), attempt["context_ref"]), "seal does not bind the original attempt")
    check = next((item for item in attempt["checks"] if item["check_id"] == seal["check"]["check_id"]), None)
    require(check is not None, "seal check is missing from the original attempt")
    require(same(seal["check"], _without_reuse(check)) and same(check.get("seal_ref"), reference),
            "original sealed observation was changed or omitted")
    require(api().timestamp(seal["sealed_at"]) <= api().timestamp(attempt["captured_at"]),
            "result was not independently sealed before attempt archival")
    validate_files(project, seal)
    compact = seal.get("input_inventory")
    require(isinstance(compact, dict) and set(compact) == {"execution_inputs", "execution_fingerprints"},
            "sealed inventory must contain only its selected execution inputs and fingerprints")
    require(isinstance(compact["execution_inputs"], dict) and isinstance(compact["execution_fingerprints"], dict)
            and compact["execution_inputs"] and set(compact["execution_inputs"]) == set(compact["execution_fingerprints"]),
            "sealed selected input and fingerprint identities differ")
    sealed_run = seal.get("run")
    require(isinstance(sealed_run, dict) and sealed_run.get("status") in ("running", "blocked"), "original sealed run facts required")
    for field in ("run_id", "started_at", "development_plan_hash", "approved_baseline_id"):
        require(same(sealed_run.get(field), attempt["run"].get(field)), "sealed run identity/binding differs from original attempt: " + field)
    original_manifest = copy.deepcopy(context["manifest"])
    accounting = seal.get("accounting")
    require(isinstance(accounting, dict) and set(accounting) <= {"evidence_storage", "evidence_accounting"}, "invalid sealed accounting metadata")
    require(same(accounting.get("evidence_storage"), context["manifest"].get("evidence_storage")), "sealed storage authority differs from its execution context")
    for field in ("evidence_storage", "evidence_accounting"):
        original_manifest.pop(field, None)
    original_manifest.update(accounting)
    frozen = historical_checker(project, original_manifest, context, seal,
                                 cache=checker._history_cache, original_canonical=False,
                                 evidence_cache=checker.evidence_resolver.cache)
    # The validated context supplies the full ownership universe; only sealed
    # inputs need fresh bytes. Otherwise a compact seal could hide an unassigned
    # input, or incorrectly require another check's independent snapshot bytes.
    selected = compact["execution_inputs"]
    selections = context["input_inventory"]["execution_inputs"]
    require(all(path in selections and same(selection, selections[path])
                for path, selection in selected.items()), "sealed input selection differs from original context")
    actual = {"execution_inputs": selections,
              "execution_fingerprints": {**context["input_inventory"]["execution_fingerprints"],
                                         **execution_fingerprints(frozen, selected)}}
    expected = check_inputs.fingerprints(frozen, attempt["unit_id"], actual, check["check_id"])[check["check_id"]]
    require(same(check_inputs.expected(seal["input_inventory"], check["check_id"]), expected),
            "sealed dependencies differ from immutable observation")
    _settlement(project, seal["settlement_ref"], check, attempt["unit_id"], attempt["run_id"], seal["sealed_at"])
    # The context already owns canonical definitions, environment and unit
    # bindings. Reconstruct these validated fields in memory instead of copying
    # the full unit inventory into every per-check seal.
    inventory = copy.deepcopy(context["input_inventory"])
    inventory.setdefault("check_execution_fingerprints", {})[check["check_id"]] = copy.deepcopy(expected)
    seal["input_inventory"] = inventory
    _seal_observation(frozen, context, check, sealed_run, inventory)
    return seal


def _reuse_applicable(seal, current, check):
    previous = seal["input_inventory"]
    require(same(check_inputs.expected(previous, check["check_id"]), check_inputs.expected(current, check["check_id"])),
            "sealed check dependency changed")
    # Canonical requirements, actual assertions, environment and prerequisite
    # allocations remain conservative until their own reviewed granular scope exists.
    for field in ("inputs", "environment", "bindings"):
        require(same(previous[field], current[field]), "sealed check " + field + " changed")
    require(same({key: value for key, value in seal["check"].items() if key not in EXECUTION_KEYS},
                 {key: value for key, value in check.items() if key not in EXECUTION_KEYS}),
            "sealed check assertion/definition changed")


def validate_reused_checks(checker, context, inventory, *, accepting=True):
    result = {}
    if not check_inputs.enabled(checker.manifest):
        require(not any("reused_from" in check or "seal_ref" in check
                        for check in checker.manifest.get("verification", {}).get("checks", [])),
                "sealed reuse requires checker/unit contract 3")
        return result
    for check in attempt_checks(checker.manifest, context["unit_id"]):
        reuse = check.get("reused_from")
        if reuse is None:
            continue
        require(isinstance(reuse, dict) and set(reuse) == {"attempt_ref", "seal_ref"}, "invalid original result reference")
        attempt, original = validate_attempt(checker.project, reuse["attempt_ref"],
                                             getattr(checker, "_history_stack", ()), checker._history_cache,
                                             evidence_cache=checker.evidence_resolver.cache)
        require(any(same(reuse["attempt_ref"], ref) for ref in checker.manifest.get("attempt_history", {}).get(context["unit_id"], [])),
                "reused result is outside preserved attempt history")
        historical = historical_checker(checker.project, attempt["post_manifest"], original, attempt,
                                         cache=checker._history_cache, original_canonical=False,
                                         evidence_cache=checker.evidence_resolver.cache)
        seal = validate_sealed_check(checker.project, reuse["seal_ref"], attempt, original, historical)
        require(same(_without_reuse(check), seal["check"]) and same(check.get("seal_ref"), reuse["seal_ref"]),
                "reused observation must retain original fields and timestamps")
        if accepting:
            _reuse_applicable(seal, inventory, check)
        require(api().timestamp(seal["sealed_at"]) <= api().timestamp(context["captured_at"]), "reuse predates original seal")
        result[check["check_id"]] = seal
    return result


@source_archive_invocation
def capture_continuation(project, manifest, unit_id, attempt_ref, run_id, inventory, *, evidence_cache=None, reuse=True):
    # One read-only preflight shares memoized dependencies; audit it before
    # capture_context creates new snapshot hard links and changes inode ctime.
    with snapshot_hash_scope():
        cache = {}
        attempt, original = validate_attempt(project, attempt_ref, cache=cache, evidence_cache=evidence_cache)
        require(attempt["unit_id"] == unit_id, "continuation attempt belongs to another unit")
        require(same({k: v for k, v in manifest.get("unit_runs", {}).get(unit_id, {}).items() if k != "attempt_ref"}, attempt["run"])
                and same(attempt_checks(manifest, unit_id), attempt["checks"]), "continuation must preserve the actual current attempt")
        attempt_authority(original["manifest"], manifest)
        reviewed = prepare_inventory(api().Checker(project, manifest, evidence_cache=evidence_cache), unit_id, inventory)
        continuation_inventory(original, attempt, reviewed, project=project, current_manifest=manifest)
        observation = validate_runtime_observation(project, inventory.get("runtime_observation_ref"))
        require(api().timestamp(observation["started_at"]) >= api().timestamp(attempt["captured_at"]),
                "continuation requires a new runtime observation after attempt capture")
        require(isinstance(run_id, str) and run_id.strip(), "new continuation run identity required")
        refs = attempt_refs(manifest).get(unit_id, [])
        if not any(same(attempt_ref, reference) for reference in refs):
            refs.append(attempt_ref)
        for reference in refs:
            previous, _ = validate_attempt(project, reference, cache=cache, evidence_cache=evidence_cache)
            require(previous["run_id"] != run_id, "continuation must use a new run identity")
        candidate = copy.deepcopy(manifest)
        candidate.setdefault("attempt_history", {})[unit_id] = refs
        candidate["unit_runs"][unit_id] = {"status": "pending", "run_id": run_id, "findings": copy.deepcopy(attempt["run"].get("findings", []))}
        reuse_reasons = {}
        for index, check in enumerate(candidate["verification"]["checks"]):
            if candidate["unit_plan"]["acceptance"].get(check["check_id"], {}).get("owner_unit") == unit_id:
                replacement = {k: v for k, v in check.items() if k not in EXECUTION_KEYS or k == "findings"}
                replacement["execution_status"] = "not_run"
                if reuse and check_inputs.enabled(manifest) and check.get("seal_ref"):
                    origin_ref = check.get("reused_from", {}).get("attempt_ref", attempt_ref)
                    origin_attempt, origin_context = (attempt, original) if same(origin_ref, attempt_ref) else validate_attempt(project, origin_ref, cache=cache, evidence_cache=evidence_cache)
                    frozen = historical_checker(project, origin_attempt["post_manifest"], origin_context, origin_attempt,
                                                cache=cache, original_canonical=False, evidence_cache=evidence_cache)
                    seal = validate_sealed_check(project, check["seal_ref"], origin_attempt, origin_context, frozen)
                    try:
                        _reuse_applicable(seal, reviewed, check)
                    except ValueError as error:
                        reuse_reasons[check["check_id"]] = str(error)
                    else:
                        replacement = copy.deepcopy(check)
                        replacement["reused_from"] = {"attempt_ref": copy.deepcopy(origin_ref), "seal_ref": copy.deepcopy(check["seal_ref"])}
                candidate["verification"]["checks"][index] = replacement
        candidate.setdefault("execution_contexts", {}).pop(unit_id, None)
    context_ref = capture_context(project, candidate, unit_id, inventory, evidence_cache=evidence_cache,
                                  prior_attempt_ref=attempt_ref, _cache=cache)
    candidate["execution_contexts"][unit_id] = context_ref
    return {"manifest": candidate, "context_ref": context_ref, "prior_attempt_ref": copy.deepcopy(attempt_ref),
            "run_id": run_id, "acceptance": "not_completed", "rerun_reasons": reuse_reasons}


def pending_mapping(original, current, mapping):
    require(isinstance(mapping, dict), "explicit pending unit mapping required")
    old, new = original["unit_plan"], current["unit_plan"]
    completed = {key for key, value in original.get("unit_runs", {}).items() if value.get("status") == "completed"}
    pending = {key for key in old["units"] if original.get("unit_runs", {}).get(key, {}).get("status", "pending") == "pending"}
    for key in completed:
        require(key in new["units"] and (same(old["units"][key], new["units"][key]) or explicit_revalidation(original, current, key)), "completed ID/scope cannot be reassigned: " + key)
    for source, targets in mapping.items():
        require(source == "__added__" or source in pending, "mapping may change pending IDs only")
        require(isinstance(targets, list) and targets and len(targets) == len(set(targets)) and set(targets) <= set(new["units"]), "mapping targets must be current unit IDs")
        require(not set(targets) & completed, "pending obligations cannot be transferred into completed units")
    changed = {key for key in old["units"] if key not in completed and (key not in new["units"] or not same(old["units"][key], new["units"][key]))}
    require(changed <= set(mapping), "changed pending units need explicit mappings: " + ", ".join(sorted(changed - set(mapping))))
    added = set(new["units"]) - set(old["units"])
    require(added <= {target for values in mapping.values() for target in values}, "new pending units need explicit mappings")
    # No old acceptance/obligation may silently vanish or shrink, regardless of renumbering.
    for check, allocation in old["acceptance"].items():
        require(check in new["acceptance"], "existing acceptance check was dropped: " + check)
        require(set(allocation["obligation_ids"]) <= set(new["acceptance"][check]["obligation_ids"]), "existing obligation was dropped: " + check)
        owner = allocation["owner_unit"]
        if owner in mapping:
            require(new["acceptance"][check]["owner_unit"] in mapping[owner], "check ownership does not follow explicit pending map: " + check)
    for artifact in ("prd", "screen-map"):
        previous = {x["id"] for x in original.get("artifacts", {}).get(artifact, {}).get("traceability", {}).get("definitions", []) if x.get("required")}
        present = {x["id"] for x in current.get("artifacts", {}).get(artifact, {}).get("traceability", {}).get("definitions", []) if x.get("required")}
        require(previous <= present, "previous required obligations disappeared: " + artifact)


def applicability(checker, completed, context, inventory, mapping, previous_manifest=None):
    reasons = []
    initial_issues = len(checker.issues)
    unit = completed["unit_id"]
    try:
        original = copy.deepcopy(previous_manifest if previous_manifest is not None else context["manifest"])
        original.setdefault("unit_runs", {})[unit] = {"status": "completed"}
        pending_mapping(original, checker.manifest, mapping)
        require(unit in checker.manifest["unit_plan"]["units"], "completed ID no longer exists")
        current = prepare_inventory(checker, unit, inventory)
        previous = completed["input_inventory"]
        if check_inputs.enabled(checker.manifest):
            changed = check_inputs.changed_checks(previous, current, current["bindings"]["unit"]["required_check_ids"])
            require(not changed, "changed check inputs; revalidate " + ", ".join(changed))
        else:
            for field in ("inputs", "bindings", "environment", "execution_inputs", "execution_fingerprints"):
                changed = differences(previous[field], current[field])
                require(not changed, "changed " + field + ": " + "; ".join(changed) + "; revalidate " + ", ".join(current["bindings"]["unit"]["required_check_ids"]))
        for check in completed["checks"]:
            for path, expected in checker.source_inventory(check, "evaluated_source_hashes")[0].items():
                if path in current["canonical_hashes"]:
                    continue  # Historical whole-file truth is preserved; current relevant sections were compared above.
                require(api().hash_matches(expected, sha(checker.path(path, no_links=True).read_bytes())), "tested source changed: " + path)
            for ref in check.get("evidence", []):
                require(checker.evidence_snapshot(ref, "implementation", "unit_stale_evidence", checker.check_bindings(check, evidence=ref)),
                        "execution evidence changed: " + str(checker.evidence_label(ref)))
        current_checks = {x["check_id"]: x for x in checker.manifest["verification"]["checks"]}
        findings = list(checker.manifest.get("unit_runs", {}).get(unit, {}).get("findings", []))
        for check in completed["checks"]:
            findings += current_checks[check["check_id"]].get("findings", [])
        require(not any(x.get("status") != "closed" and (x.get("severity") in ("P0", "P1") or x.get("release_effect") == "blocking") for x in findings), "new blocking finding requires revalidation")
    except (ValueError, OSError, KeyError, TypeError) as error:
        reasons.append(str(error))
    finally:
        # A current applicability failure is reported as revalidation work;
        # it does not turn sound historical proof into a corrupt-history error.
        for issue in checker.issues[initial_issues:]:
            detail = issue.get("detail") or issue.get("code") or "current applicability validation failed"
            if detail not in reasons:
                reasons.append(detail)
        del checker.issues[initial_issues:]
    return reasons


@source_archive_invocation
def assess_completion(project, manifest, completion_ref, inventory, pending_unit_map, *, evidence_cache=None):
    completed, context = validate_completion(project, completion_ref, evidence_cache=evidence_cache)
    checker = api().Checker(project, copy.deepcopy(manifest), evidence_cache=evidence_cache)
    reviewed = prepare_inventory(checker, completed["unit_id"], inventory)
    previous_path = physical(project, "forge/sdd-manifest.json")
    previous_bytes = previous_path.read_bytes()
    previous = api().read_json(previous_path)
    pending_mapping(previous, manifest, pending_unit_map)
    directory = HISTORY + "/applicability/" + uuid.uuid4().hex
    previous_ref = write_new(project, directory + "/prior-manifest.json", previous_bytes)
    reasons = applicability(checker, completed, context, reviewed, pending_unit_map, previous)
    record = {"event": "completion_applicability", "version": VERSION, "completion_ref": completion_ref,
              "current_plan_hash": manifest["artifacts"]["development-plan"]["content_hash"], "input_inventory": reviewed,
              "prior_manifest_ref": previous_ref, "pending_unit_map": pending_unit_map,
              "outcome": "needs_revalidation" if reasons else "applicable", "reasons": reasons}
    return store_record(project, "applicability", record, directory)


class HistoryView:
    def __init__(self, checker):
        self.checker = checker
        self.original = copy.deepcopy(checker.manifest)
        self.preserved = {}
        self.attempts = {}
        self.checks = {}
        self.reused = {}
        self.units = {}
        self.reviewed_checks = {}
        self.reviewed_units = {}
        self.reviews = {}
        self.reviewed_original_runs = set()
        self._current_runs = set()
        self._reviewed_execution_checks = set()
        self.canonical_evidence = getattr(checker, "_history_canonical_evidence", {})
        if not hasattr(checker, "_history_cache"):
            checker._history_cache = {}

    @snapshot_hash_invocation
    def resolve(self, executing=False, action=None, unit_id=None):
        checker = self.checker
        manifest = checker.manifest
        plan_hash = manifest.get("artifacts", {}).get("development-plan", {}).get("content_hash")
        if "reviewed_acceptance" in manifest:
            import reviewed_acceptance
            reviewed = reviewed_acceptance.resolve(checker)
            self.reviewed_checks = reviewed["checks"]
            self.reviewed_units = reviewed["units"]
            self.reviews = reviewed["reviews"]
        for run in manifest.get("unit_runs", {}).values():
            merged_findings(run.get("findings", []))
        for check in manifest.get("verification", {}).get("checks", []):
            merged_findings(check.get("findings", []))
        for reference in manifest.get("legacy_history", []):
            legacy = read_ref(checker.project, reference)
            require(legacy.get("event") == "legacy_execution_archive" and legacy.get("version") == VERSION and legacy.get("acceptance") == "unverified_not_reusable", "invalid legacy execution archive")
            previous = read_ref(checker.project, legacy["manifest_ref"])
            require(legacy_format(previous), "legacy archive must retain actual supported legacy context")
            if not defer_legacy_payload(reference, legacy):
                _checker_legacy_files(checker, reference, legacy)
        for key, references in manifest.get("completion_history", {}).items():
            require(key in manifest.get("unit_plan", {}).get("units", {}), "archived completed ID disappeared")
            require(isinstance(references, list) and references, "completion history must retain original references")
            identities = set()
            for reference in references:
                require(reference.get("content_hash") not in identities, "duplicate completion history reference")
                identities.add(reference.get("content_hash"))
                completed, _ = validate_completion(checker.project, reference, getattr(checker, "_history_stack", ()), checker._history_cache, evidence_cache=checker.evidence_resolver.cache)
                require(completed["unit_id"] == key, "archived completed ID reassigned")
        for key, references in manifest.get("attempt_history", {}).items():
            require(key in manifest.get("unit_plan", {}).get("units", {}), "archived attempted ID disappeared")
            require(isinstance(references, list) and references, "attempt history must retain original references")
            identities = set()
            for reference in references:
                require(reference.get("content_hash") not in identities, "duplicate attempt history reference")
                identities.add(reference.get("content_hash"))
                attempted, _ = validate_attempt(checker.project, reference, getattr(checker, "_history_stack", ()),
                                                checker._history_cache, evidence_cache=checker.evidence_resolver.cache)
                require(attempted["unit_id"] == key, "archived attempted ID reassigned")
        for key, run in list(manifest.get("unit_runs", {}).items()):
            if "attempt_ref" in run:
                try:
                    attempted, context = validate_attempt(checker.project, run["attempt_ref"], getattr(checker, "_history_stack", ()),
                                                         checker._history_cache, evidence_cache=checker.evidence_resolver.cache)
                    require(attempted["unit_id"] == key, "attempted ID reassigned")
                    require(same({name: value for name, value in run.items() if name != "attempt_ref"}, attempted["run"])
                            and same(attempt_checks(manifest, key), attempted["checks"]),
                            "current attempt differs from immutable actual status/results; capture a new continuation before retry")
                    require(same(manifest.get("execution_contexts", {}).get(key), attempted["context_ref"]),
                            "current attempt binds another context")
                    attempt_authority(context["manifest"], manifest)
                    observed = prepare_inventory(checker, key, attempted["input_inventory"])
                    policy_successor = not same(observed, attempted["input_inventory"])
                    if policy_successor:
                        unchanged = copy.deepcopy(observed)
                        logical = "forge/evidence-policy.json"
                        require(logical in unchanged["execution_fingerprints"]
                                and logical in attempted["input_inventory"]["execution_fingerprints"],
                                "current attempt inventory is stale; preserve it and capture a reviewed continuation")
                        unchanged["execution_fingerprints"][logical] = attempted["input_inventory"]["execution_fingerprints"][logical]
                        require(same(unchanged, attempted["input_inventory"]),
                                "current attempt inventory is stale; preserve it and capture a reviewed continuation")
                        frozen = ({"files": checker._history_overlay, "snapshot_root": checker._history_snapshot_root}
                                  if hasattr(checker, "_history_overlay") else None)
                        _policy_successor(checker.project, attempted, observed,
                                          current_record=frozen, current_manifest=manifest)
                    self.canonical_evidence.update(canonical_alternatives(context, attempted))
                    self.attempts[key] = attempted
                    require(not (action == "complete" and unit_id == key),
                            "archived unfinished attempt cannot complete; use capture-continuation before fresh qualification")
                    if attempted["observation_validity"] == "unverified_stale_inputs" or policy_successor:
                        # The raw manifest and immutable archive keep actual outcomes;
                        # the validation view cannot borrow them as current acceptance.
                        for index, check in enumerate(manifest["verification"]["checks"]):
                            if manifest["unit_plan"]["acceptance"].get(check["check_id"], {}).get("owner_unit") == key:
                                manifest["verification"]["checks"][index] = {name: value for name, value in check.items()
                                                                            if name not in EXECUTION_KEYS or name == "findings"}
                                manifest["verification"]["checks"][index]["execution_status"] = "not_run"
                        checker.warnings.append(key + (": validated policy successor; original unfinished attempt remains nonaccepting and requires a fresh continuation"
                                                       if policy_successor else ": original " + attempted["outcome"] + " attempt preserved; stale input observations are unverified and grant no current acceptance"))
                    require(not (policy_successor and action == "start" and unit_id == key),
                            "archived unfinished attempt with a policy successor cannot start; capture a fresh continuation")
                except (ValueError, OSError, KeyError, TypeError) as error:
                    checker.issue("unit_history", "development-plan", key + ": invalid unfinished attempt: " + str(error))
                continue
            if "completion_ref" not in run:
                # An explicit present-day review can recognize the procedural
                # gap of this exact original run. It never excuses a damaged
                # context or a different new run, and does not create a context.
                review = self.reviews.get(key, {})
                if (key not in manifest.get("execution_contexts", {})
                        and review.get("source_run_matches_current") is True):
                    self.reviewed_original_runs.add(key)
                    continue
                if getattr(checker, "_history_validating_run", None) == key:
                    # Immutable completion/attempt validators own the surrounding
                    # context, result and runtime checks for this exact run.
                    self._current_runs.add(key)
                if run.get("status") in ("running", "blocked", "completed"):
                    if run.get("development_plan_hash") != plan_hash:
                        self.units[key] = {"historical_valid": False, "current_applicability": "needs_revalidation", "reasons": ["unfinished/unarchived old-plan run cannot be preserved"]}
                        manifest["unit_runs"][key] = {"status": "pending"}
                    elif getattr(checker, "_history_validating_run", None) != key:
                        try:
                            require(run.get("status") != "completed" or getattr(checker, "_history_capture_completed", None) == key,
                                    "v2 completion requires an immutable completion envelope; capture actual results before activation")
                            ref = manifest.get("execution_contexts", {})[key]
                            context = validate_context(checker.project, ref, key, getattr(checker, "_history_stack", ()), checker._history_cache, evidence_cache=checker.evidence_resolver.cache)
                            reviewed_run_identity(checker.project, context, run)
                            require(context["manifest"]["artifacts"]["development-plan"]["content_hash"] == plan_hash, "execution context belongs to another plan")
                            require(api().timestamp(context["captured_at"]) <= api().timestamp(run.get("started_at")), "context was captured after start")
                            if "prior_attempt_ref" in context:
                                require(run.get("run_id") == context["manifest"]["unit_runs"][key]["run_id"],
                                        "current run identity differs from its continuation context")
                            reviewed = getattr(checker, "_history_completion_inventory", {}).get(key, context["input_inventory"])
                            observed = prepare_inventory(checker, key, reviewed)
                            if not same(observed["canonical_hashes"], reviewed["canonical_hashes"]):
                                operation = "capture-completion" if run.get("status") == "completed" else "capture-attempt"
                                raise ValueError("canonical owner output changed; reconcile owners and use " + operation + " --inventory with a fresh current review")
                            require(same({k: v for k, v in observed.items() if k not in ("execution_fingerprints", "check_execution_fingerprints", "canonical_hashes", "review")},
                                         {k: v for k, v in context["input_inventory"].items() if k not in ("execution_fingerprints", "check_execution_fingerprints", "canonical_hashes", "review")}), "pre-start reviewed acceptance inputs changed during execution")
                            owned = {check for check, allocation in manifest["unit_plan"]["acceptance"].items() if allocation["owner_unit"] == key}
                            for check_id in owned:
                                self.canonical_evidence[check_id] = {path: {value, context["input_inventory"]["canonical_hashes"][path]}
                                                                   for path, value in observed["canonical_hashes"].items()}
                            for check in manifest["verification"]["checks"]:
                                if check["check_id"] in owned and check.get("execution_status") in ("passed", "failed"):
                                    if reviewed_observation(check, self.reviewed_checks):
                                        # Separately validated original observations
                                        # are not executions of this new context.
                                        self._reviewed_execution_checks.add(check["check_id"])
                                        continue
                                    require(same(check.get("evaluated_execution_inputs"), check_inputs.expected(observed, check["check_id"])), "check execution inputs changed since actual test observation: " + check["check_id"])
                                    validate_check_runtime(checker.project, context, check, run,
                                                           accepting=action == "complete" or run.get("status") == "completed")
                            validate_continuation_findings(checker.project, context, run, attempt_checks(manifest, key), observed)
                            self._current_runs.add(key)
                        except (ValueError, OSError, KeyError, TypeError) as error:
                            checker.issue("unit_history", "development-plan", str(error))
                continue
            reasons, valid, integrity_checked = [], False, False
            revalidation_ids = list(manifest.get("unit_plan", {}).get("units", {}).get(key, {}).get("required_check_ids", []))
            try:
                require(run.get("status") == "completed", "only completed wrappers can reference history")
                completed, context = validate_completion(checker.project, run["completion_ref"], getattr(checker, "_history_stack", ()), checker._history_cache, evidence_cache=checker.evidence_resolver.cache)
                require(completed["unit_id"] == key, "completed ID reassigned")
                valid = True
                if completed["run"]["development_plan_hash"] == plan_hash and "applicability_ref" not in run:
                    inventory, mapping, previous = completed["input_inventory"], {}, None
                else:
                    if "applicability_ref" not in run:
                        integrity_checked = True
                        raise ValueError("current applicability review is missing; preserve history and revalidate")
                    assessment = read_ref(checker.project, run.get("applicability_ref"))
                    require(assessment.get("event") == "completion_applicability" and assessment.get("version") == VERSION, "unsupported applicability assessment")
                    require(same(assessment.get("completion_ref"), run["completion_ref"]), "assessment must directly reference original completion")
                    require(assessment.get("current_plan_hash") == plan_hash, "assessment belongs to another current plan")
                    inventory, mapping = assessment["input_inventory"], assessment["pending_unit_map"]
                    previous = read_ref(checker.project, assessment["prior_manifest_ref"])
                    pending_mapping(previous, manifest, mapping)
                integrity_checked = True
                current_inventory = prepare_inventory(checker, key, inventory)
                if check_inputs.enabled(manifest):
                    revalidation_ids = check_inputs.changed_checks(completed["input_inventory"], current_inventory,
                                                                  manifest["unit_plan"]["units"][key]["required_check_ids"])
                else:
                    require(same(current_inventory, inventory), "reviewed current input inventory is stale")
                reasons = applicability(checker, completed, context, current_inventory, mapping, previous)
                require(not reasons, "; ".join(reasons))
                self.preserved[key] = completed
                self.checks.update({x["check_id"]: copy.deepcopy(x) for x in completed["checks"]})
                manifest["unit_runs"][key] = copy.deepcopy(completed["run"])
                manifest["unit_runs"][key]["findings"] = merged_findings(completed["run"].get("findings", []), run.get("findings", []))
            except (ValueError, OSError, KeyError, TypeError) as error:
                reasons = reasons or [str(error)]
                manifest["unit_runs"][key] = {"status": "pending", "findings": copy.deepcopy(run.get("findings", []))}
                if not valid or not integrity_checked:
                    checker.issue("unit_history", "development-plan", key + ": invalid historical record: " + str(error))
            self.units[key] = {"historical_valid": valid, "current_applicability": "needs_revalidation" if reasons else "applicable", "reasons": reasons,
                               "revalidation_check_ids": (revalidation_ids or list(manifest.get("unit_plan", {}).get("units", {}).get(key, {}).get("required_check_ids", []))) if reasons else []}
        # Reuse is a current assessment of original observations, never a new
        # execution timestamp or completion of the earlier interrupted attempt.
        if check_inputs.enabled(manifest):
            for key, ref in manifest.get("execution_contexts", {}).items():
                if any(check.get("reused_from") for check in attempt_checks(manifest, key)):
                    context = validate_context(checker.project, ref, key, getattr(checker, "_history_stack", ()),
                                               checker._history_cache, evidence_cache=checker.evidence_resolver.cache)
                    observed = prepare_inventory(checker, key, context["input_inventory"])
                    self.reused.update(validate_reused_checks(checker, context, observed,
                                       accepting=getattr(checker, "_history_nonaccepting_attempt", None) != key))
        # A different actual execution must be validated on its own merits. An
        # older reviewed pass must never replace fresh but invalid claimed proof.
        for check in self.original.get("verification", {}).get("checks", []):
            key = check.get("check_id")
            if (key in self.reviewed_checks and check.get("execution_status") in ("passed", "failed")
                    and not reviewed_observation(check, self.reviewed_checks)):
                del self.reviewed_checks[key]
                owner = manifest["unit_plan"]["acceptance"][key]["owner_unit"]
                self.reviews[owner]["reasons"].append(key + ": distinct actual execution requires its own validation")
                self.reviews[owner]["current_applicability"] = "needs_revalidation"
        invalidated = set()
        if (manifest.get("checker_contract_version"), manifest.get("unit_contract_version")) == (4, 4):
            import reviewed_acceptance
            observations = [("current", check) for check in self.original.get("verification", {}).get("checks", [])
                            if check.get("execution_status") == "passed"]
            observations.extend(("preserved", check) for record in self.preserved.values() for check in record["checks"]
                                if check.get("execution_status") == "passed")
            observations.extend(("reused", record["check"]) for record in self.reused.values())
            observations.extend(("reviewed", check) for check in self.reviewed_checks.values())
            for source, observation in observations:
                key = observation["check_id"]
                owner = manifest["unit_plan"]["acceptance"][key]["owner_unit"]
                try:
                    reviewed_acceptance.require_no_counterevidence(checker, owner, observation)
                except (ValueError, OSError, KeyError, TypeError) as error:
                    if source == "current":
                        invalidated.add(key)
                    if source == "reviewed":
                        self.reviewed_checks.pop(key, None)
                    if source == "reused":
                        self.reused.pop(key, None)
                        invalidated.add(key)
                    if source == "preserved" and owner in self.preserved:
                        del self.preserved[owner]
                        self.units[owner]["current_applicability"] = "needs_revalidation"
                        self.units[owner]["reasons"].append(str(error))
                        self.units[owner]["revalidation_check_ids"] = list(manifest["unit_plan"]["units"][owner]["required_check_ids"])
                        manifest["unit_runs"][owner] = {"status": "pending", "findings": manifest["unit_runs"][owner].get("findings", [])}
                    if source == "reviewed" and owner in self.reviews:
                        self.reviews[owner]["current_applicability"] = "needs_revalidation"
                        self.reviews[owner]["reasons"].append(key + ": " + str(error))
        # Applicability is closed over the CURRENT combined prerequisite graph.
        # A historically valid integration result cannot outlive a stale prerequisite.
        plan = manifest.get("unit_plan", {})
        allocations = plan.get("acceptance", {})
        changed = True
        while changed:
            changed = False
            accepted_units = set(self.preserved) | set(self.reviewed_units)
            observations = {check["check_id"]: check for record in self.preserved.values() for check in record["checks"]}
            observations.update(self.reviewed_checks)
            accepted_checks = set(observations)
            # Original chronology is proved from each consumer's own preserved
            # source by reviewed_acceptance. A later genuine prerequisite rerun
            # must not rewrite when that consumer's original preconditions held.
            for check_id in list(self.reviewed_checks):
                allocation = allocations[check_id]
                owner = allocation["owner_unit"]
                dependencies = (set(plan["units"][owner]["construction_dependencies"])
                                | set(allocation["prerequisite_units"])) - {owner}
                missing_units = dependencies - accepted_units
                missing_checks = set(allocation["prerequisite_checks"]) - accepted_checks
                if missing_units or missing_checks:
                    del self.reviewed_checks[check_id]
                    review = self.reviews[owner]
                    review["current_applicability"] = "needs_revalidation"
                    reason = "current prerequisite acceptance unavailable: " + ", ".join(sorted(missing_units | missing_checks))
                    review["reasons"].append(check_id + ": " + reason)
                    decision = review.get("check_decisions", {}).get(check_id)
                    if decision is not None:
                        decision["outcome"] = "needs_revalidation"
                        decision["reasons"].append(reason)
                    changed = True
            for key in sorted(set(self.preserved) | set(self.reviewed_units)):
                dependencies = set(plan["units"][key]["construction_dependencies"])
                for allocation in allocations.values():
                    if allocation["owner_unit"] == key:
                        dependencies.update(allocation["prerequisite_units"])
                        dependencies.update(allocations[check]["owner_unit"] for check in allocation["prerequisite_checks"])
                dependencies.discard(key)
                missing = dependencies - (set(self.preserved) | set(self.reviewed_units))
                incomplete = (key in self.reviewed_units
                              and not set(plan["units"][key]["required_check_ids"]) <= set(self.reviewed_checks))
                if missing or incomplete:
                    reason = ("current prerequisite acceptance unavailable: " + ", ".join(sorted(missing))
                              if missing else "required reviewed check acceptance unavailable")
                    if key in self.preserved:
                        self.units[key]["current_applicability"] = "needs_revalidation"
                        self.units[key]["reasons"].append(reason)
                        self.units[key]["revalidation_check_ids"] = list(plan["units"][key]["required_check_ids"])
                        del self.preserved[key]
                        manifest["unit_runs"][key] = {"status": "pending", "findings": manifest["unit_runs"][key].get("findings", [])}
                    if key in self.reviewed_units:
                        del self.reviewed_units[key]
                        self.reviews[key]["current_applicability"] = "needs_revalidation"
                        self.reviews[key]["reasons"].append(reason)
                        self.reviews[key]["revalidation_check_ids"] = list(plan["units"][key]["required_check_ids"])
                        self.reviews[key]["accepted_check_ids"] = []
                        if missing:
                            self.reviewed_checks = {check_id: check for check_id, check in self.reviewed_checks.items()
                                                    if allocations[check_id]["owner_unit"] != key}
                    changed = True
        for key, review in self.reviews.items():
            accepted = sorted(check_id for check_id in self.reviewed_checks if allocations[check_id]["owner_unit"] == key)
            review["accepted_check_ids"] = accepted
            review["revalidation_check_ids"] = sorted(set(plan["units"][key]["required_check_ids"]) - set(accepted))
        self.checks = {check["check_id"]: copy.deepcopy(check) for record in self.preserved.values() for check in record["checks"]}
        effective_checks = {**self.checks, **self.reviewed_checks}
        # Every inherited result enters generic/security/release validation through this one view.
        for index, check in enumerate(manifest.get("verification", {}).get("checks", [])):
            key = check.get("check_id")
            if key in effective_checks:
                replacement = {**check, **{k: copy.deepcopy(v) for k, v in effective_checks[key].items() if k in EXECUTION_KEYS}}
                replacement["findings"] = merged_findings(effective_checks[key].get("findings", []), check.get("findings", []))
                manifest["verification"]["checks"][index] = replacement
            elif check.get("phase") in ("implementation", "both"):
                owner = manifest.get("unit_plan", {}).get("acceptance", {}).get(key, {}).get("owner_unit")
                if ((owner in self.units or owner in self.reviews and owner not in self._current_runs)
                        and owner not in self.preserved or key in self._reviewed_execution_checks or key in invalidated):
                    manifest["verification"]["checks"][index] = {k: v for k, v in check.items() if k not in EXECUTION_KEYS or k == "findings"}
                    manifest["verification"]["checks"][index]["execution_status"] = "not_run"
        # Old exceptions remain in their original snapshots; they grant no current starts.
        manifest["unit_sequence_exceptions"] = [ref for ref in manifest.get("unit_sequence_exceptions", [])
            if checker.evidence_snapshot(ref, "implementation", "unit_exception")
            and checker.evidence_json(ref).get("development_plan_hash") == plan_hash]
        manifest["prototype_promotions"] = [record for record in manifest.get("prototype_promotions", []) if record.get("unit_id") not in self.preserved]
        if (action == "start" and getattr(checker, "_history_capturing", None) != unit_id
                and unit_id not in self.preserved and unit_id not in self.reviewed_units):
            try:
                context = validate_context(checker.project, manifest.get("execution_contexts", {})[unit_id], unit_id, getattr(checker, "_history_stack", ()), checker._history_cache, evidence_cache=checker.evidence_resolver.cache)
                require(context["manifest"]["artifacts"]["development-plan"]["content_hash"] == plan_hash, "start context belongs to another plan")
            except (ValueError, OSError, KeyError, TypeError) as error:
                checker.issue("unit_history", "development-plan", "capture a valid execution context before start: " + str(error))


@source_archive_invocation
def candidate_hashes(project, manifest, *, evidence_cache=None, include_external=True, checker=None):
    """Optimistic guard covers executable/evidence/history inputs as well as docs."""
    external_refs = []
    paths, visited = set(referenced_paths(project, manifest, external_refs=external_refs)), set()
    def visit(value, collect_external=True):
        if isinstance(value, dict):
            if value.get("event") == "legacy_execution_archive":
                collect_external = False  # Retained, unverified legacy refs grant no acceptance.
            external = evidence_reference(value)
            if external is not None:
                if collect_external:
                    external_refs.append(external)
                if external is value:
                    return
                value = {key: child for key, child in value.items() if key != "evidence_ref"}
            if set(value) == REF_KEYS:
                path = value["path"]
                paths.add(path)
                if path.startswith(HISTORY + "/") and "/files/" not in path and path.endswith(".json") and path not in visited:
                    visited.add(path)
                    visit(read_ref(project, value), collect_external)
            for key, child in value.items():
                if key in INACTIVE_HISTORY_KEYS:
                    continue
                if key in ("implementation_paths", "required_source_paths") and isinstance(child, list):
                    paths.update(child)
                if key == "execution_inputs" and isinstance(child, dict):
                    for path in child:
                        paths.add(path)
                        target = physical(project, path)
                        if target.is_dir():
                            paths.update(item.relative_to(Path(project).resolve()).as_posix() for item in target.rglob("*"))
                visit(child, collect_external)
        elif isinstance(value, list):
            for child in value:
                visit(child, collect_external)
    visit(manifest)
    result = {}
    for path in sorted(paths):
        archive = _source_archive.get()
        source = archive.sources.get(path) if archive is not None else None
        target = archived_source_path(project, {key: source[key] for key in REF_KEYS}) if source else physical(project, path)
        result[path] = sha(target.read_bytes()) if target.is_file() else "directory" if target.is_dir() else None
    archive = _source_archive.get()
    if archive is not None:
        external_refs.extend(source["evidence_ref"] for source in archive.sources.values())
    if checker is not None:
        external_refs.extend(checker.evidence_resolver.references.values())
        external_refs.extend(getattr(checker, "_history_cache", {}).get("evidence_references", {}).values())
    # File-only/inactive selections consume no prepared transport policy. Active
    # references and explicit declarations still bind it, including migrations
    # which deliberately omit external payload hashes.
    policy = None
    if archive is not None:
        policy = archive.resolver_policy
    elif external_refs or "evidence_storage" in manifest or "evidence_accounting" in manifest:
        policy = PreparedResolverPolicy(project, manifest)
    if include_external and external_refs:
        # Bind prepared originals and readback receipts, including dependency
        # closure, without storing external machine paths or copying payloads.
        resolver = policy.new_resolver(evidence_cache)
        for ref in external_refs:
            resolver.resolve(ref)
        for key, path in resolver.resolved_paths.items():
            result["@evidence/" + key + "/original"] = sha(path.read_bytes())
            result["@evidence/" + key + "/receipt"] = sha(resolver._path("receipts", key + ".json").read_bytes())
    if policy is not None:
        if policy.digest is not None:
            result["@policy/" + policy.logical] = policy.digest
        policy.audit()
    return result


def completion_refs(manifest):
    references = {key: list(value) for key, value in manifest.get("completion_history", {}).items()}
    for key, run in manifest.get("unit_runs", {}).items():
        if "completion_ref" in run:
            references.setdefault(key, []).append(run["completion_ref"])
    return references


def reviewed_contextless_replacement(project, previous, candidate, unit, *, cache, evidence_cache):
    """Retain exact old facts before a genuinely new context replaces a gap."""
    run = previous.get("unit_runs", {}).get(unit, {})
    if (previous.get("checker_contract_version"), previous.get("unit_contract_version")) != (4, 4):
        return False
    references = previous.get("reviewed_acceptance", {}).get(unit, [])
    if (not references or unit in previous.get("execution_contexts", {})
            or "attempt_ref" in run or "completion_ref" in run):
        return False
    import reviewed_acceptance
    checker = api().Checker(project, copy.deepcopy(previous), evidence_cache=evidence_cache)
    checker._history_cache = cache
    reviewed = reviewed_acceptance.resolve(checker)
    metadata = reviewed["reviews"].get(unit, {})
    if metadata.get("source_run_matches_current") is not True:
        return False
    review = read_ref(project, references[-1])
    source = read_ref(project, review["source_ref"])
    original = read_ref(project, source["manifest_ref"])
    require(same(original.get("unit_runs", {}).get(unit), run)
            and same(attempt_checks(original, unit), attempt_checks(previous, unit)),
            "replacement must retain exact original contextless run and observations")
    context_ref = candidate.get("execution_contexts", {}).get(unit)
    require(context_ref is not None, "reviewed contextless replacement needs a fresh execution context")
    context = validate_context(project, context_ref, unit, cache=cache, evidence_cache=evidence_cache)
    require(same(context.get("reviewed_prior_ref"), references[-1]),
            "fresh context must explicitly bind its reviewed prior source")
    require(any(same(references[-1], reference) for reference in context["manifest"].get("reviewed_acceptance", {}).get(unit, [])),
            "fresh context must retain the original reviewed source")
    remember_evidence(checker)
    return True


def explicit_revalidation(previous, candidate, unit):
    """Append acceptance/prerequisites without reusing the old result or changing identity."""
    before = previous["unit_plan"]["units"][unit]
    after = candidate["unit_plan"]["units"].get(unit, {})
    if not same({k: v for k, v in before.items() if k in ("scope", "kind", "owner", "implementation_paths")},
                {k: v for k, v in after.items() if k in ("scope", "kind", "owner", "implementation_paths")}):
        return False
    if not set(before["required_check_ids"]) <= set(after.get("required_check_ids", [])) or not set(before["construction_dependencies"]) <= set(after.get("construction_dependencies", [])):
        return False
    old_refs = completion_refs(previous).get(unit, [])
    archived = candidate.get("completion_history", {}).get(unit, [])
    if not old_refs or not all(any(same(ref, item) for item in archived) for ref in old_refs):
        return False
    run = candidate.get("unit_runs", {}).get(unit, {})
    return "completion_ref" not in run and run.get("status", "pending") in ("pending", "running", "blocked")


@snapshot_hash_invocation
def validate_transition(project, previous, candidate, mapping, *, evidence_cache=None):
    """Validate the whole transition even when a candidate deletes all active indexes."""
    cache = {}
    previous_versions = (previous.get("checker_contract_version"), previous.get("unit_contract_version"))
    candidate_versions = (candidate.get("checker_contract_version"), candidate.get("unit_contract_version"))
    if previous_versions not in ((2, 2), (3, 3), (4, 4)):
        require(legacy_format(previous), "unsupported legacy records require owner-reviewed reconciliation")
        mode = "format_only_no_execution" if pristine_legacy(previous) else "legacy_revalidation"
        validate_adoption_mode(previous, candidate, mode)
        archives = []
        for reference in candidate.get("legacy_history", []):
            legacy = read_ref(project, reference)
            if (legacy.get("event") == "legacy_execution_archive" and legacy.get("version") == VERSION
                    and legacy.get("acceptance") == "unverified_not_reusable"
                    and same(read_ref(project, legacy["manifest_ref"]), previous)):
                # Migration readiness may tolerate unfinished project checks, but
                # must never tolerate an incomplete or corrupt original archive.
                validate_files(project, legacy)
                # Older captures can also contain inactive history-only inputs.
                # Retain and verify every extra byte without requiring inactive payloads.
                require(referenced_paths(project, previous) <= set(legacy["files"]),
                        "legacy snapshot inventory changed or omitted original files")
                for logical, ref in legacy["files"].items():
                    require(api().hash_matches(ref["content_hash"], sha(physical(project, logical).read_bytes())),
                            "legacy snapshot source changed: " + logical)
                archives.append(legacy)
        require(archives, "version 2 adoption requires an archive of the exact active version 1 manifest")
    previous_reviews = previous.get("reviewed_acceptance", {})
    candidate_reviews = candidate.get("reviewed_acceptance", {})
    require(isinstance(previous_reviews, dict) and isinstance(candidate_reviews, dict),
            "reviewed acceptance index must be an object")
    for unit, references in previous_reviews.items():
        require(unit in candidate.get("unit_plan", {}).get("units", {}), "reviewed unit identity removed")
        retained = candidate_reviews.get(unit, [])
        require(isinstance(references, list) and isinstance(retained, list)
                and len(retained) >= len(references) and same(retained[:len(references)], references),
                "reviewed acceptance history was dropped or reordered: " + unit)
    for unit, references in candidate_reviews.items():
        require(isinstance(references, list), "review history must be a reference list")
        for reference in references[len(previous_reviews.get(unit, [])):]:
            import reviewed_acceptance
            review = read_ref(project, reference)
            require(same(review.get("authority_fields"), reviewed_acceptance.authority(candidate)),
                    "review was captured against a different current authority or plan")
    if (candidate_versions == (4, 4)
            and (previous_versions != (4, 4) or not same(previous_reviews, candidate_reviews))):
        # Reviewing existing observations is a separate transaction from changing
        # authority, accounting, checks, plan definitions or actual execution.
        mutable = {"checker_contract_version", "unit_contract_version", "reviewed_acceptance"}
        require(same({key: value for key, value in previous.items() if key not in mutable},
                     {key: value for key, value in candidate.items() if key not in mutable}),
                "review adoption must preserve original state, authority and accounting")
    old_refs, new_refs = completion_refs(previous), completion_refs(candidate)
    old_attempts, new_attempts = attempt_refs(previous), attempt_refs(candidate)
    for unit, references in old_attempts.items():
        require(unit in candidate.get("unit_plan", {}).get("units", {}), "attempted unit identity removed")
        for reference in references:
            require(any(same(reference, item) for item in new_attempts.get(unit, [])), "unfinished attempt history was dropped: " + unit)
    if previous.get("unit_contract_version") in (2, 3, 4):
        for unit, run in previous.get("unit_runs", {}).items():
            if run.get("status") not in ("running", "blocked"):
                continue
            current = candidate.get("unit_runs", {}).get(unit, {})
            same_execution = (current.get("status") != "pending" and current.get("started_at") == run.get("started_at")
                              and current.get("run_id") == run.get("run_id")
                              and same(previous.get("execution_contexts", {}).get(unit), candidate.get("execution_contexts", {}).get(unit)))
            if "completion_ref" in current:
                completed, _ = validate_completion(project, current["completion_ref"], cache=cache, evidence_cache=evidence_cache)
                same_execution = (completed["run"].get("started_at") == run.get("started_at")
                                  and completed["run"].get("run_id") == run.get("run_id"))
            if same_execution:
                continue
            if reviewed_contextless_replacement(project, previous, candidate, unit, cache=cache, evidence_cache=evidence_cache):
                continue
            preserved = False
            for reference in new_attempts.get(unit, []):
                attempted, _ = validate_attempt(project, reference, cache=cache, evidence_cache=evidence_cache)
                if (same(attempted["run"], {key: value for key, value in run.items() if key != "attempt_ref"})
                        and same(attempted["checks"], attempt_checks(previous, unit))
                        and same(attempted["context_ref"], previous.get("execution_contexts", {}).get(unit))):
                    preserved = True
            require(preserved, "replaced unfinished run needs its exact immutable attempt: " + unit)
            context_ref = candidate.get("execution_contexts", {}).get(unit)
            require(context_ref is not None, "replacement needs a captured continuation context")
            context = validate_context(project, context_ref, unit, cache=cache, evidence_cache=evidence_cache)
            require(any(same(context.get("prior_attempt_ref"), reference) for reference in new_attempts.get(unit, [])),
                    "replacement context must retain its prior attempt")
    for reference in previous.get("legacy_history", []):
        require(any(same(reference, item) for item in candidate.get("legacy_history", [])), "legacy execution history was dropped")
    for unit, refs in old_refs.items():
        require(unit in candidate.get("unit_plan", {}).get("units", {}), "completed ID removed from candidate: " + unit)
        for ref in refs:
            require(any(same(ref, current) for current in new_refs.get(unit, [])), "completed history was dropped: " + unit)
        require(same(previous["unit_plan"]["units"][unit], candidate["unit_plan"]["units"][unit]) or explicit_revalidation(previous, candidate, unit), "completed unit definition changed outside explicit revalidation scope: " + unit)
    has_completed = bool(old_refs) or any(run.get("status") == "completed" for run in previous.get("unit_runs", {}).values())
    if has_completed:
        pending_mapping(previous, candidate, mapping)
    for unit, run in previous.get("unit_runs", {}).items():
        if run.get("status") == "completed" and "completion_ref" not in run and candidate.get("unit_contract_version") in (2, 3, 4):
            current = candidate.get("unit_runs", {}).get(unit, {})
            if candidate_versions == (4, 4) and candidate_reviews.get(unit) and same(run, current):
                # The candidate gate independently validates the explicit review.
                # Retaining the actual run is not an ordinary completion envelope.
                require(same(attempt_checks(previous, unit), attempt_checks(candidate, unit)),
                        "review adoption changed original observations")
                continue
            if reviewed_contextless_replacement(project, previous, candidate, unit, cache=cache, evidence_cache=evidence_cache):
                continue
            archived = False
            if previous.get("unit_contract_version") == 1 and current.get("status", "pending") == "pending":
                for reference in candidate.get("legacy_history", []):
                    legacy = read_ref(project, reference)
                    if legacy.get("event") == "legacy_execution_archive" and legacy.get("acceptance") == "unverified_not_reusable" and same(read_ref(project, legacy["manifest_ref"]), previous):
                        archived = True
                if archived:
                    require(same(candidate.get("implementation_gate"), previous.get("implementation_gate")),
                            "legacy migration must preserve exact authority; current checks still enforce its validity")
                    continue
            require("completion_ref" in current, "legacy completion requires verified original history; do not silently adopt or erase it")
            completed, _ = validate_completion(project, current["completion_ref"], cache=cache, evidence_cache=evidence_cache)
            require(same(completed["run"], run), "candidate does not preserve the actual original completed run")


def pristine_legacy(manifest):
    """Conservatively identify records with no actual or ambiguous execution history."""
    runs = manifest.get("unit_runs", {})
    if not isinstance(runs, dict):
        return False
    for run in runs.values():
        if not isinstance(run, dict) or run.get("status") != "pending" or set(run) - {"status", "findings"}:
            return False
        if not same(run.get("findings", []), []):
            return False
    for key, empty in (("prototype_promotions", []), ("unit_sequence_exceptions", []),
                       ("execution_contexts", {}), ("completion_history", {}), ("legacy_history", [])):
        if not same(manifest.get(key, empty), empty):
            return False
    verification = manifest.get("verification")
    if verification is None:
        return "unit_plan" not in manifest
    if not isinstance(verification, dict) or verification.get("release_readiness") != "not_evaluated":
        return False
    checks = verification.get("checks")
    if not isinstance(checks, list) or (not checks and "unit_plan" in manifest):
        return False
    for check in checks:
        if not isinstance(check, dict) or check.get("execution_status") not in ("not_run", "not_applicable"):
            return False
        for key in ("executor", "executed_at", "execution_mode", "evaluated_plan_hash", "started_at", "completed_at", "result", "results"):
            if key in check and check[key] is not None and check[key] != "":
                return False
        for key, empty in (("evidence", []), ("findings", []), ("evaluated_source_hashes", {}), ("evaluated_execution_inputs", {}),
                           ("source_inventory_ref", None), ("revalidation_ref", None), ("run_id", None)):
            if not same(check.get(key, empty), empty):
                return False
        if any(key.startswith(("execution_", "evaluated_")) and key not in EXECUTION_KEYS for key in check):
            return False
    return True


def legacy_format(manifest):
    """Recognize only known legacy records; absence is safe only before unit work."""
    return (type(manifest.get("checker_contract_version")) is int and manifest["checker_contract_version"] == 1
            and ((type(manifest.get("unit_contract_version")) is int and manifest["unit_contract_version"] == 1)
                 or ("unit_contract_version" not in manifest and "unit_plan" not in manifest and pristine_legacy(manifest))))


def legacy_candidate(original, history):
    candidate = copy.deepcopy(original)
    candidate.update(checker_contract_version=VERSION, unit_contract_version=VERSION)
    candidate["legacy_history"] = copy.deepcopy(history)
    if pristine_legacy(original):
        return candidate
    # Past completion is archived, never reissued as current evidence. Preserve
    # open findings and the exact authorization record, including an existing
    # pause or invalid receipt: migration must neither grant nor renew consent.
    candidate.update(unit_runs={unit: {"status": "pending", "findings": copy.deepcopy(run["findings"])}
                                for unit, run in original.get("unit_runs", {}).items() if run.get("findings")},
                     execution_contexts={})
    candidate["unit_sequence_exceptions"] = []
    candidate["verification"]["release_readiness"] = "not_evaluated"
    for index, check in enumerate(candidate["verification"]["checks"]):
        if check.get("phase") in ("implementation", "both") and check.get("execution_status") != "not_applicable":
            replacement = {key: value for key, value in check.items() if key not in EXECUTION_KEYS or key == "findings"}
            replacement["execution_status"] = "not_run"
            candidate["verification"]["checks"][index] = replacement
    return candidate


def adopt_legacy(project, expected_manifest_hash, *, evidence_cache=None):
    """Preserve work and exact authority; archive old results for genuine revalidation."""
    live = physical(project, "forge/sdd-manifest.json")
    original_bytes = live.read_bytes()
    require(api().hash_matches(expected_manifest_hash, sha(original_bytes)), "active legacy manifest changed")
    original = api().read_json(live)
    require(legacy_format(original), "legacy migration requires supported version 1 records; reconcile unknown metadata first")
    runs = original.get("unit_runs", {})
    require(isinstance(runs, dict) and all(isinstance(run, dict) for run in runs.values()), "malformed legacy unit_runs; reconcile the actual records before adoption")
    verification = original.get("verification")
    require((verification is None and pristine_legacy(original)) or (isinstance(verification, dict) and isinstance(verification.get("checks"), list)
            and all(isinstance(check, dict) for check in verification["checks"])), "malformed legacy verification records; reconcile before adoption")
    for key, kind in (("prototype_promotions", list), ("unit_sequence_exceptions", list),
                      ("execution_contexts", dict), ("completion_history", dict), ("legacy_history", list)):
        require(key not in original or isinstance(original[key], kind), "malformed legacy " + key + "; reconcile before adoption")
    directory = HISTORY + "/legacy/" + uuid.uuid4().hex
    manifest_ref = write_new(project, directory + "/manifest.json", original_bytes)
    legacy_ref = store_record(project, "legacy", {"event": "legacy_execution_archive", "version": VERSION,
                              "manifest_ref": manifest_ref, "acceptance": "unverified_not_reusable", "archived_at": utcnow(),
                              "snapshot_root": directory + "/files", "files": freeze_files(project, original, directory)}, directory)
    history = list(original.get("legacy_history", [])) + [legacy_ref]
    candidate = legacy_candidate(original, history)
    mode = "format_only_no_execution" if pristine_legacy(original) else "legacy_revalidation"
    return stage_candidate(project, candidate, expected_manifest_hash, adoption_mode=mode, evidence_cache=evidence_cache)


@source_archive_invocation
def observe_execution_inputs(project, manifest, unit_id, inventory=None, *, evidence_cache=None, check_id=None):
    """Observe bytes only; the actual executor must bind this to its real check event."""
    if inventory is None:
        context = read_ref(project, manifest["execution_contexts"][unit_id])
        inventory = context["input_inventory"]
    checker = api().Checker(project, manifest, evidence_cache=evidence_cache)
    if check_id is not None:
        require(check_inputs.enabled(manifest), "per-check observations require checker/unit contract 3")
        reviewed = prepare_inventory(checker, unit_id, inventory)
        require(check_id in reviewed["check_execution_fingerprints"], "check is not owned by the unit")
        return reviewed["check_execution_fingerprints"][check_id]
    return execution_fingerprints(checker, inventory["execution_inputs"])


def current_authority(checker):
    probe = api().Checker(checker.project, copy.deepcopy(checker.manifest), checker.contract, evidence_cache=checker.evidence_resolver.cache)
    probe._history_hash_owner = getattr(checker, "_history_hash_owner", None)
    for name in ("_history_overlay", "_history_snapshot_root"):
        if hasattr(checker, name):
            setattr(probe, name, getattr(checker, name))
    try:
        probe.authorization()
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        probe.issue("implementation_not_authorized", "implementation", str(error))
    return {"status": "not_authorized" if probe.issues else "authorized", "issues": probe.issues,
            "scope": "current implementation prompt only; prerequisites, evidence and release gates remain separate"}


def validate_adoption_mode(previous, candidate, mode):
    if mode is None:
        return
    require(legacy_format(previous) and all(type(candidate.get(key)) is int and candidate[key] == VERSION
            for key in ("checker_contract_version", "unit_contract_version")),
            "adoption mode requires a version 1 to version 2 transition")
    expected_mode = "format_only_no_execution" if pristine_legacy(previous) else "legacy_revalidation"
    require(mode == expected_mode, "adoption mode differs from actual legacy execution state")
    expected = legacy_candidate(previous, candidate.get("legacy_history"))
    require(same(expected, candidate), "legacy adoption must preserve original fields and the required execution reset; do not rebind authority")


def candidate_report(checker, migration):
    """A format migration may expose an unfinished plan; it cannot approve one."""
    try:
        with history_integrity_scope(checker._source_manifest, force_full=True):
            report = checker.run("development-plan", after=True, require_current=True)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        if not migration:
            raise
        report = {"result": "blocked", "issues": [{"code": "invalid_input", "detail": str(error)}]}
    if migration:
        return {"result": "migration_ready", "project_validation": report,
                "limits": "Exact format conversion only; unresolved project checks still block affected work. No product acceptance or permission granted."}
    require(report["result"] == "passed", "candidate plan validation failed: " + json.dumps(report["issues"]))
    return report


@source_archive_invocation
def stage_candidate(project, candidate_manifest, expected_manifest_hash, pending_unit_map=None, adoption_mode=None, *, evidence_cache=None):
    live = physical(project, "forge/sdd-manifest.json")
    require(live.is_file() and api().hash_matches(expected_manifest_hash, sha(live.read_bytes())), "active manifest changed before staging")
    previous = api().read_json(live)
    validate_adoption_mode(previous, candidate_manifest, adoption_mode)
    mapping = copy.deepcopy(pending_unit_map or {})
    for run in candidate_manifest.get("unit_runs", {}).values():
        if "applicability_ref" in run:
            assessment = read_ref(project, run["applicability_ref"])
            require(api().hash_matches(expected_manifest_hash, assessment["prior_manifest_ref"]["content_hash"]), "applicability was reviewed against a different active manifest")
            for key, value in assessment["pending_unit_map"].items():
                require(key not in mapping or same(mapping[key], value), "conflicting pending mappings")
                mapping[key] = value
    validate_transition(project, previous, candidate_manifest, mapping, evidence_cache=evidence_cache)
    migration = legacy_format(previous)
    checker = api().Checker(project, copy.deepcopy(candidate_manifest), evidence_cache=evidence_cache)
    report = candidate_report(checker, migration)
    record = {"event": "manifest_candidate", "version": VERSION, "expected_manifest_hash": expected_manifest_hash,
              "manifest": candidate_manifest, "pending_unit_map": mapping, "source_hashes": canonical_hashes(checker, migration),
              "observed_hashes": candidate_hashes(project, candidate_manifest, evidence_cache=evidence_cache, include_external=not migration, checker=checker),
              "report": report, "staged_at": utcnow()}
    if adoption_mode is not None:
        record["adoption_mode"] = adoption_mode  # Informational; never grants execution authority.
    # Identical retries retain the first staging timestamp and immutable record.
    identity = {key: value for key, value in record.items() if key != "staged_at"}
    directory = HISTORY + "/candidates/" + sha(encoded(identity))
    path = directory + "/record.json"
    ref = publish_immutable(project, path, encoded(record), existing_winner=True)
    existing = read_ref(project, ref)
    require(same({key: value for key, value in existing.items() if key != "staged_at"}, identity),
            "staged candidate identity conflicts")
    return ref


@source_archive_invocation
def activate_candidate(project, candidate_ref, expected_manifest_hash, *, evidence_cache=None):
    candidate = read_ref(project, candidate_ref)
    require(candidate.get("event") == "manifest_candidate" and candidate.get("version") == VERSION, "invalid staged candidate")
    require(candidate.get("expected_manifest_hash") == expected_manifest_hash, "candidate expected manifest mismatch")
    live = physical(project, "forge/sdd-manifest.json")
    lock = physical(project, HISTORY + "/activation.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("x") as stream:
        json.dump({"pid": os.getpid(), "hostname": socket.gethostname(), "created_at": utcnow(), "token": uuid.uuid4().hex}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        before = live.read_bytes()
        after = encoded(candidate["manifest"])
        directory = HISTORY + "/activations/" + sha(encoded(candidate_ref))
        journal_path = directory + "/record.json"
        journal, existing = None, None
        if physical(project, journal_path).exists():
            journal = {"path": journal_path, "content_hash": hash_file(physical(project, journal_path))[0]}
            existing = read_ref(project, journal)
            require(existing.get("event") == "manifest_activation" and existing.get("version") == VERSION
                    and same(existing.get("candidate_ref"), candidate_ref), "activation journal identity conflicts")
            read_ref(project, existing["before"])
            read_ref(project, existing["after"])
            require(api().hash_matches(expected_manifest_hash, existing["before"]["content_hash"])
                    and api().hash_matches(existing["after"]["content_hash"], sha(after)),
                    "activation journal transition conflicts")
            if sha(before) == sha(after):
                return {"status": "already_activated", "journal_ref": journal, "manifest_hash": sha(after),
                        "acceptance": "not_revalidated", "action": "transaction already applied; run the current gate to evaluate current acceptance"}
        require(api().hash_matches(expected_manifest_hash, sha(before)), "active manifest changed; restage candidate")
        previous = api().read_json(live)
        validate_adoption_mode(previous, candidate["manifest"], candidate.get("adoption_mode"))
        validate_transition(project, previous, candidate["manifest"], candidate["pending_unit_map"], evidence_cache=evidence_cache)
        migration = legacy_format(previous)
        checker = api().Checker(project, copy.deepcopy(candidate["manifest"]), evidence_cache=evidence_cache)
        checker.product_scope()
        require(same(canonical_hashes(checker, migration), candidate["source_hashes"]), "candidate sources changed; restage candidate")
        # Use a fresh checker so scope diagnostics are not duplicated above.
        checker = api().Checker(project, copy.deepcopy(candidate["manifest"]), evidence_cache=evidence_cache)
        report = candidate_report(checker, migration)
        require(same(report, candidate["report"]), "candidate applicability changed; restage candidate")
        require(same(candidate_hashes(project, candidate["manifest"], evidence_cache=evidence_cache, include_external=not migration, checker=checker), candidate["observed_hashes"]), "candidate source/evidence/history changed; restage candidate")
        def member(name, data):
            path = directory + "/" + name + ".json"
            return publish_immutable(project, path, data)
        before_ref, after_ref = member("before", before), member("after", after)
        if journal is None:
            journal = publish_immutable(project, directory + "/record.json", encoded({"event": "manifest_activation", "version": VERSION, "candidate_ref": candidate_ref,
                                        "before": before_ref, "after": after_ref, "prepared_at": utcnow()}))
        else:
            require(same(existing["before"], before_ref) and same(existing["after"], after_ref),
                    "activation journal member identity conflicts")
        require(sha(live.read_bytes()) == sha(before), "active manifest changed during activation")
        require(same(candidate_hashes(project, candidate["manifest"], evidence_cache=evidence_cache, include_external=not migration, checker=checker), candidate["observed_hashes"]), "candidate source/evidence changed during activation")
        temporary = live.with_name(".sdd-manifest-" + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, live)
        finally:
            if temporary.exists():
                temporary.unlink()
        return {"status": "activated", "journal_ref": journal, "manifest_hash": sha(after), "report": report}
    finally:
        lock.unlink()


def recover_activation(project, journal_ref):
    journal = read_ref(project, journal_ref)
    require(journal.get("event") == "manifest_activation" and journal.get("version") == VERSION, "invalid activation journal")
    read_ref(project, journal["before"])
    read_ref(project, journal["after"])
    current = sha(physical(project, "forge/sdd-manifest.json").read_bytes())
    status = "activated" if api().hash_matches(journal["after"]["content_hash"], current) else "not_activated" if api().hash_matches(journal["before"]["content_hash"], current) else "conflict"
    lock = physical(project, HISTORY + "/activation.lock")
    return {"status": status, "manifest_hash": current, "lock_path": str(lock),
            "lock_owner": api().read_json(lock) if lock.is_file() else None,
            "action": "read-only; verify lock owner has exited before any manual lock cleanup; no automatic overwrite or lock deletion"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", default="forge/sdd-manifest.json")
    parser.add_argument("--evidence-cache", type=Path, help="read-only prepared evidence cache outside the project")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("capture-context", "capture-completion", "capture-attempt", "capture-continuation", "seal-check", "seal-group", "observe-runtime",
                    "assess", "stage", "activate", "recover", "adopt-legacy", "observe-inputs", "create-source-archive-index", "prepare-source-views",
                    "import-observations", "prepare-original-inventory", "capture-review"):
        child = sub.add_parser(command)
        if command in ("capture-context", "capture-completion", "capture-attempt", "capture-continuation", "observe-inputs", "seal-check", "seal-group"):
            child.add_argument("--unit", required=True)
        if command in ("capture-context", "capture-continuation", "assess"):
            child.add_argument("--inventory", required=True)
        if command == "observe-inputs":
            child.add_argument("--inventory")
            child.add_argument("--check-id")
        if command == "capture-context":
            child.add_argument("--reviewed-prior-ref")
        if command == "import-observations":
            child.add_argument("--unit", required=True)
            child.add_argument("--source-manifest", required=True)
        if command == "capture-review":
            child.add_argument("--request", required=True)
        if command == "prepare-original-inventory":
            child.add_argument("--unit", required=True)
            child.add_argument("--source-kind", required=True, choices=("legacy_archive", "external_observations"))
            child.add_argument("--source-ref", required=True)
            child.add_argument("--inventory", required=True)
        if command in ("capture-completion", "capture-attempt"):
            child.add_argument("--context-ref", required=True)
            child.add_argument("--run-id", required=True)
            child.add_argument("--inventory")
        if command == "capture-attempt":
            child.add_argument("--outcome", required=True, choices=("failed", "interrupted"))
        if command == "capture-continuation":
            child.add_argument("--attempt-ref", required=True)
            child.add_argument("--run-id", required=True)
            child.add_argument("--fresh-checks", action="store_true")
        if command in ("seal-check", "seal-group"):
            child.add_argument("--check-id" if command == "seal-check" else "--check-ids", required=True, **({"nargs": "+"} if command == "seal-group" else {}))
            child.add_argument("--settlement-ref", required=True)
            child.add_argument("--inventory")
        if command == "observe-runtime":
            child.add_argument("--probes", required=True)
        if command == "assess":
            child.add_argument("--completion-ref", required=True)
            child.add_argument("--pending-map", required=True)
        if command == "stage":
            child.add_argument("--candidate", required=True)
            child.add_argument("--pending-map")
        if command in ("stage", "activate", "adopt-legacy"):
            child.add_argument("--expected-manifest-hash", required=True)
        if command == "activate":
            child.add_argument("--candidate-ref", required=True)
        if command == "recover":
            child.add_argument("--journal-ref", required=True)
        if command == "create-source-archive-index":
            child.add_argument("--mapping", required=True, help="JSON list of immutable record_ref, snapshot_root and full sources mappings")
            child.add_argument("--view-strategy", choices=("private_copy", "shared_cache_links"), default="private_copy")
            child.add_argument("--encoding", choices=("inline", "sha_objects_v1"), default="inline")
        if command == "prepare-source-views":
            child.add_argument("--index-ref", required=True)
            child.add_argument("--max-bytes", required=True, type=int)
            child.add_argument("--max-files", required=True, type=int)
    args = parser.parse_args()
    def read(path):
        return api().read_json(physical(args.project, path))
    try:
        require(sys.version_info >= (3, 12), "Python 3.12+ required")
        manifest = read(args.manifest)
        if args.command == "import-observations":
            import reviewed_acceptance
            result = reviewed_acceptance.import_observations(args.project, read(args.source_manifest), args.unit,
                                                            evidence_cache=args.evidence_cache)
        elif args.command == "capture-review":
            import reviewed_acceptance
            result = reviewed_acceptance.capture(args.project, manifest, read(args.request), evidence_cache=args.evidence_cache)
        elif args.command == "prepare-original-inventory":
            import reviewed_acceptance
            result = reviewed_acceptance.prepare_original_inventory(args.project, manifest, args.unit,
                args.source_kind, read(args.source_ref), read(args.inventory), evidence_cache=args.evidence_cache)
        elif args.command == "create-source-archive-index":
            result = create_source_archive_index(args.project, read(args.mapping), evidence_cache=args.evidence_cache,
                                                 view_strategy=args.view_strategy, encoding=args.encoding)
        elif args.command == "prepare-source-views":
            result = prepare_source_views(args.project, read(args.index_ref), evidence_cache=args.evidence_cache,
                                          max_bytes=args.max_bytes, max_files=args.max_files)
        elif args.command == "capture-context":
            result = capture_context(args.project, manifest, args.unit, read(args.inventory), evidence_cache=args.evidence_cache,
                                     reviewed_prior_ref=read(args.reviewed_prior_ref) if args.reviewed_prior_ref else None)
        elif args.command == "capture-completion":
            result = capture_completion(args.project, manifest, args.unit, read(args.context_ref), args.run_id, read(args.inventory) if args.inventory else None, evidence_cache=args.evidence_cache)
        elif args.command == "capture-attempt":
            result = capture_attempt(args.project, manifest, args.unit, read(args.context_ref), args.run_id, args.outcome,
                                     read(args.inventory) if args.inventory else None, evidence_cache=args.evidence_cache)
        elif args.command == "capture-continuation":
            result = capture_continuation(args.project, manifest, args.unit, read(args.attempt_ref), args.run_id,
                                          read(args.inventory), evidence_cache=args.evidence_cache, reuse=not args.fresh_checks)
        elif args.command == "seal-group":
            result = seal_checks(args.project, manifest, args.unit, args.check_ids, read(args.settlement_ref),
                                 read(args.inventory) if args.inventory else None, evidence_cache=args.evidence_cache)
        elif args.command == "seal-check":
            result = seal_check(args.project, manifest, args.unit, args.check_id, read(args.settlement_ref),
                                read(args.inventory) if args.inventory else None, evidence_cache=args.evidence_cache)
        elif args.command == "observe-runtime":
            result = observe_runtime(args.project, read(args.probes))
        elif args.command == "assess":
            result = assess_completion(args.project, manifest, read(args.completion_ref), read(args.inventory), read(args.pending_map), evidence_cache=args.evidence_cache)
        elif args.command == "stage":
            result = stage_candidate(args.project, read(args.candidate), args.expected_manifest_hash, read(args.pending_map) if args.pending_map else None, evidence_cache=args.evidence_cache)
        elif args.command == "activate":
            result = activate_candidate(args.project, read(args.candidate_ref), args.expected_manifest_hash, evidence_cache=args.evidence_cache)
        elif args.command == "adopt-legacy":
            result = adopt_legacy(args.project, args.expected_manifest_hash, evidence_cache=args.evidence_cache)
        elif args.command == "observe-inputs":
            result = observe_execution_inputs(args.project, manifest, args.unit, read(args.inventory) if args.inventory else None, evidence_cache=args.evidence_cache, check_id=args.check_id)
        else:
            result = recover_activation(args.project, read(args.journal_ref))
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"result": "blocked", "detail": str(error)}))
        return 1


def _cli_main():
    # The checker loads this exact sibling under this name. Dispatch through
    # that module so nested validation shares its ContextVars and audit owner.
    name = "_sdd_unit_history"
    if name not in sys.modules:
        sys.modules[name] = sys.modules[__name__]
    module = sys.modules[name]
    if not _module_at(module, _SCRIPT_PATH) or not callable(getattr(module, "main", None)):
        print(json.dumps({"result": "blocked", "detail": "conflicting history module alias: " + name}))
        return 1
    # A preloaded same-SDK helper may already own an active invocation; reuse
    # its entry point without replacing that module or any of its state.
    return module.main()


if __name__ == "__main__":
    sys.exit(_cli_main())
