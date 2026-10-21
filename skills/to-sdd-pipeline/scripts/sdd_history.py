#!/usr/bin/env python3
"""Current unit history. Read-only resolution and validated local migration.

Recorded reviews and user events are supplied facts, never authenticated by hashes.
The checker never calls the writing helpers. Standard library only.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import subprocess
import sys
import uuid

from evidence.resolver import EvidenceResolver, INACTIVE_HISTORY_KEYS, evidence_reference, validate_reference

VERSION = 2
CONTRACT = "sdd-unit-history-v2"
HISTORY = "forge/unit-history"
REF_KEYS = {"path", "content_hash"}
EXECUTION_KEYS = {"execution_status", "executor", "executed_at", "evidence", "execution_mode", "evaluated_plan_hash", "evaluated_source_hashes", "evaluated_execution_inputs", "findings", "rationale", "source_inventory_ref", "revalidation_ref", "run_id", "runtime_observation_ref"}
V2_KEYS = {"execution_contexts", "completion_ref", "applicability_ref", "unit_history", "completion_history", "legacy_history", "evaluated_execution_inputs", "context_ref", "attempt_ref", "attempt_history", "prior_attempt_ref"}


def contains_v2_fields(value):
    if isinstance(value, dict):
        return bool(set(value) & V2_KEYS) or any(contains_v2_fields(child) for child in value.values())
    return isinstance(value, list) and any(contains_v2_fields(child) for child in value)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def api():
    existing = sys.modules.get("_sdd_history_checker")
    if existing:
        return existing
    spec = importlib.util.spec_from_file_location("_sdd_history_checker", Path(__file__).with_name("sdd_check.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode()


def same(a, b):
    return encoded(a) == encoded(b)


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


def physical(project, path):
    require(isinstance(path, str) and path and "\\" not in path, "history path must be relative POSIX text")
    parts = PurePosixPath(path)
    require(not parts.is_absolute() and all(p not in ("..", ".") for p in path.split("/")), "unsafe history path: " + path)
    root = Path(project).resolve()
    current = root
    for part in parts.parts:
        current /= part
        if current.exists() or current.is_symlink():
            require(not api().is_link(current), "history cannot follow links: " + path)
    require(current.resolve().is_relative_to(root), "history path escapes project")
    return current


def read_ref(project, ref):
    require(isinstance(ref, dict) and set(ref) == REF_KEYS, "hash-bound path reference required")
    path = physical(project, ref["path"])
    require(path.is_file(), "missing history file: " + ref["path"])
    data = path.read_bytes()
    require(api().hash_matches(ref["content_hash"], sha(data)), "changed history file: " + ref["path"])
    return api().read_json(path)


def write_new(project, path, data):
    target = physical(project, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": path, "content_hash": sha(data)}


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


def canonical_hashes(checker, allow_missing=False):
    result = {}
    for key, spec in checker.specs.items():
        if key in checker.skipped:
            continue
        path = checker.path(spec["path"], no_links=True)
        if allow_missing and not path.exists():
            result[spec["path"]] = None
        else:
            result[spec["path"]] = sha(path.read_bytes())
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
            result[logical] = {"mode": mode, "exists": True, "content_hash": sha(target.read_bytes())}
        else:
            require(target.is_dir(), "execution input is not a directory: " + logical)
            members = {}
            for directory, dirs, names in os.walk(target, followlinks=False):
                for name in dirs + names:
                    path = Path(directory) / name
                    require(not api().is_link(path), "execution inventory cannot follow a symlink")
                    if path.is_file():
                        members[path.relative_to(target).as_posix()] = sha(path.read_bytes())
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
        needed.update(checks[key]["acceptance"]["required_source_paths"])
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
    if "runtime_observation_ref" in inventory:
        observation = validate_runtime_observation(checker.project, inventory["runtime_observation_ref"])
        require(same(observation["environment"], environment), "runtime observation differs from reviewed environment")
        require(api().timestamp(observation["observed_at"]) <= api().timestamp(review["reviewed_at"]),
                "owner review must follow the runtime observation")
        result["runtime_observation_ref"] = copy.deepcopy(inventory["runtime_observation_ref"])
    return result


class _ExternalEvidenceError(ValueError):
    """Explicit reference failures are never optional application path metadata."""


def referenced_paths(project, manifest, *, checker=None, external_refs=None):
    """Enumerate declared regular sources/receipts and frozen render trees only."""
    found, seen_json, seen_external, seen_files = set(), set(), set(), set()
    seen_directories, directory_stamps = set(), {}

    def directory_stamp(path):
        info = path.stat(follow_symlinks=False)
        return info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, info.st_ctime_ns

    def scan_directory(value, path):
        if value in seen_directories:
            return
        directory_stamps[value] = directory_stamp(path)
        for child in sorted(path.iterdir()):
            relative = child.relative_to(Path(project).resolve()).as_posix()
            checked = physical(project, relative)
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
            path = physical(project, value)
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
        if path.suffix == ".json" and value not in seen_json:
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
        path = physical(project, value)
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


def validate_files(project, record):
    require(isinstance(record.get("files"), dict) and (record["files"] or record.get("event") == "legacy_execution_archive"), "historical snapshots required")
    for logical, ref in record["files"].items():
        physical(project, logical)
        require(ref.get("path") == record["snapshot_root"] + "/" + logical, "snapshot path must preserve logical identity")
        path = physical(project, ref["path"])
        require(path.is_file() and api().hash_matches(ref.get("content_hash"), sha(path.read_bytes())), "historical snapshot changed: " + logical)


def historical_checker(project, manifest, context, completion=None, stack=(), cache=None, original_canonical=True, *, evidence_cache=None):
    validate_files(project, context)
    files = dict(context["files"])
    if completion:
        validate_files(project, completion)
        files = dict(completion["files"])  # A post-run deletion must not resurrect a pre-start file.
        if original_canonical:
            for artifact in context["manifest"]["artifacts"].values():
                logical = artifact["path"]
                if logical in context["files"]:
                    files[logical] = context["files"][logical]
    checker = api().Checker(project, copy.deepcopy(manifest), evidence_cache=evidence_cache)
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


def validate_context(project, reference, unit_id, stack=(), cache=None, *, evidence_cache=None):
    cache = cache if cache is not None else {}
    context = read_ref(project, reference)
    cache_key = ("context", reference["content_hash"], unit_id)
    if cache_key in cache:
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
    require(manifest.get("unit_contract_version") in (1, 2), "unsupported historical unit contract")
    require(manifest.get("unit_runs", {}).get(unit_id, {}).get("status", "pending") == "pending", "context must be captured before first start")
    if "prior_attempt_ref" in context:
        attempt, original = validate_attempt(project, context["prior_attempt_ref"], stack, cache, evidence_cache=evidence_cache)
        require(attempt["unit_id"] == unit_id, "continuation context belongs to another attempted unit")
        attempt_authority(original["manifest"], manifest)
        continuation_inventory(original, attempt, context["input_inventory"])
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
            require(check.get("execution_status") == "not_run" and not check.get("evidence"),
                    "continuation cannot reuse old acceptance results")
            require(same(check.get("findings", []), old_checks[check["check_id"]].get("findings", [])),
                    "continuation dropped check findings")
    checker = historical_checker(project, manifest, context, stack=stack, cache=cache, evidence_cache=evidence_cache)
    checker._history_capturing = unit_id
    report = checker.run("implementation", unit_action="start", unit_id=unit_id)
    require(report["result"] == "passed", "original execution context was not authorized/startable: " + json.dumps(report["issues"]))
    reviewed = prepare_inventory(checker, unit_id, context["input_inventory"])
    require(same(reviewed, context["input_inventory"]), "captured inventory does not match original context")
    remember_evidence(checker)
    cache[cache_key] = copy.deepcopy(context)
    del cache[visiting]
    return context


def capture_context(project, manifest, unit_id, inventory, *, evidence_cache=None, prior_attempt_ref=None, _cache=None):
    require(manifest.get("unit_contract_version") == VERSION, "migrate legacy records before capturing current execution")
    require(manifest.get("unit_runs", {}).get(unit_id, {}).get("status", "pending") == "pending", "capture context before starting the unit")
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
    context["files"] = freeze_files(project, manifest, directory, reviewed["execution_inputs"], checker=checker)
    reference = store_record(project, "contexts", context, directory)
    if prior_attempt_ref is not None:
        validate_context(project, reference, unit_id, cache=cache, evidence_cache=evidence_cache)
    return reference


def validate_completion(project, reference, stack=(), cache=None, *, evidence_cache=None):
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
    if cache_key in cache:
        return copy.deepcopy(cache[cache_key])
    context = validate_context(project, completed["context_ref"], unit, stack, cache, evidence_cache=evidence_cache)
    run = completed["run"]
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
            require(same(check.get("evaluated_execution_inputs"), completed["input_inventory"]["execution_fingerprints"]), "executed check lacks matching test-time execution input observation")
            validate_check_runtime(project, context, check, run, accepting=True)
    cache[cache_key] = copy.deepcopy((completed, context))
    return completed, context


def validate_completion_inventory(context, current, checks):
    ignored = {"execution_fingerprints", "canonical_hashes", "review"}
    require(same({k: v for k, v in current.items() if k not in ignored},
                 {k: v for k, v in context["input_inventory"].items() if k not in ignored}), "relevant acceptance inputs changed during execution")
    if not same(current["canonical_hashes"], context["input_inventory"]["canonical_hashes"]):
        threshold = max([api().timestamp(context["captured_at"])] + [api().timestamp(check["executed_at"]) for check in checks if check.get("execution_status") in ("passed", "failed")])
        require(api().timestamp(current["review"]["reviewed_at"]) >= threshold, "canonical owner output changed; supply a fresh current inventory review after the check evidence")


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
    """Continuation acceptance needs the runtime actually observed in that run."""
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
                    require(same(check.get("evaluated_execution_inputs"), inventory["execution_fingerprints"]),
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
    return ("unverified_stale_inputs" if any(not same(check["evaluated_execution_inputs"], inventory["execution_fingerprints"])
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
        require(set(fingerprints) == set(record["input_inventory"]["execution_inputs"]),
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


def validate_attempt(project, reference, stack=(), cache=None, *, evidence_cache=None):
    """Validate preserved execution without ever requiring or granting completion."""
    cache = cache if cache is not None else {}
    record = read_ref(project, reference)
    identity = reference["content_hash"]
    marker = ("attempt", identity)
    require(identity not in stack and len(stack) < 128, "cyclic/excessive attempt history")
    if marker in cache:
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
            require(api().timestamp(run["started_at"]) <= api().timestamp(check["executed_at"]) <= api().timestamp(record["captured_at"]),
                    "attempt check was not executed within the actual run")
            require(check.get("evaluated_plan_hash") == run["development_plan_hash"], "attempt check belongs to another plan")
            require(not check.get("run_id") or check["run_id"] == record["run_id"], "attempt check belongs to another run")
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
        checker._history_canonical_evidence = unfinished_evidence_alternatives(project, context, record, checker)
        report = checker.run("implementation", unit_action="start", unit_id=unit)
        require(report["result"] == "passed", "unfinished attempt records are invalid: " + json.dumps(report["issues"]))
        if not original_canonical:
            require(same(prepare_inventory(checker, unit, record["input_inventory"]), record["input_inventory"]),
                    "attempt inventory differs from preserved snapshots")
        remember_evidence(checker)
    cache[marker] = copy.deepcopy((record, context))
    return record, context


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


def continuation_inventory(context, attempt, reviewed):
    ignored = {"environment", "runtime_observation_ref", "canonical_hashes", "review",
               "execution_inputs", "execution_fingerprints"}
    original = attempt["input_inventory"]
    require(same({k: v for k, v in original.items() if k not in ignored},
                 {k: v for k, v in reviewed.items() if k not in ignored}),
            "continuation changed relevant acceptance definitions or preserved work")
    # A fresh attempt may add reviewed executor inputs, retaining the exact old
    # selections and bytes. It never edits earlier work or reuses its results.
    for inventory in (original, reviewed):
        selections, fingerprints = inventory.get("execution_inputs"), inventory.get("execution_fingerprints")
        require(isinstance(selections, dict) and selections and isinstance(fingerprints, dict)
                and set(selections) == set(fingerprints),
                "continuation execution inputs require every exact fingerprint")
    for path, selection in original["execution_inputs"].items():
        require(path in reviewed["execution_inputs"]
                and same(selection, reviewed["execution_inputs"][path])
                and same(original["execution_fingerprints"][path], reviewed["execution_fingerprints"][path]),
                "continuation changed or removed preserved execution input: " + path)
    require(api().timestamp(reviewed["review"]["reviewed_at"]) >= api().timestamp(attempt["captured_at"]),
            "continuation needs a fresh owner review after attempt capture")
    attempt_authority(context["manifest"], attempt["post_manifest"])


def capture_continuation(project, manifest, unit_id, attempt_ref, run_id, inventory, *, evidence_cache=None):
    cache = {}
    attempt, original = validate_attempt(project, attempt_ref, cache=cache, evidence_cache=evidence_cache)
    require(attempt["unit_id"] == unit_id, "continuation attempt belongs to another unit")
    require(same({k: v for k, v in manifest.get("unit_runs", {}).get(unit_id, {}).items() if k != "attempt_ref"}, attempt["run"])
            and same(attempt_checks(manifest, unit_id), attempt["checks"]), "continuation must preserve the actual current attempt")
    attempt_authority(original["manifest"], manifest)
    reviewed = prepare_inventory(api().Checker(project, manifest, evidence_cache=evidence_cache), unit_id, inventory)
    continuation_inventory(original, attempt, reviewed)
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
    for index, check in enumerate(candidate["verification"]["checks"]):
        if candidate["unit_plan"]["acceptance"].get(check["check_id"], {}).get("owner_unit") == unit_id:
            candidate["verification"]["checks"][index] = {k: v for k, v in check.items() if k not in EXECUTION_KEYS or k == "findings"}
            candidate["verification"]["checks"][index]["execution_status"] = "not_run"
    candidate.setdefault("execution_contexts", {}).pop(unit_id, None)
    context_ref = capture_context(project, candidate, unit_id, inventory, evidence_cache=evidence_cache,
                                  prior_attempt_ref=attempt_ref, _cache=cache)
    candidate["execution_contexts"][unit_id] = context_ref
    return {"manifest": candidate, "context_ref": context_ref, "prior_attempt_ref": copy.deepcopy(attempt_ref),
            "run_id": run_id, "acceptance": "not_completed"}


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
        self.units = {}
        self.canonical_evidence = getattr(checker, "_history_canonical_evidence", {})
        if not hasattr(checker, "_history_cache"):
            checker._history_cache = {}

    def resolve(self, executing=False, action=None, unit_id=None):
        checker = self.checker
        manifest = checker.manifest
        plan_hash = manifest.get("artifacts", {}).get("development-plan", {}).get("content_hash")
        for run in manifest.get("unit_runs", {}).values():
            merged_findings(run.get("findings", []))
        for check in manifest.get("verification", {}).get("checks", []):
            merged_findings(check.get("findings", []))
        for reference in manifest.get("legacy_history", []):
            legacy = read_ref(checker.project, reference)
            require(legacy.get("event") == "legacy_execution_archive" and legacy.get("version") == VERSION and legacy.get("acceptance") == "unverified_not_reusable", "invalid legacy execution archive")
            validate_files(checker.project, legacy)
            previous = read_ref(checker.project, legacy["manifest_ref"])
            require(legacy_format(previous), "legacy archive must retain actual supported legacy context")
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
                    require(same(prepare_inventory(checker, key, attempted["input_inventory"]), attempted["input_inventory"]),
                            "current attempt inventory is stale; preserve it and capture a reviewed continuation")
                    self.canonical_evidence.update(canonical_alternatives(context, attempted))
                    self.attempts[key] = attempted
                    require(not (action == "complete" and unit_id == key),
                            "archived unfinished attempt cannot complete; use capture-continuation before fresh qualification")
                    if attempted["observation_validity"] == "unverified_stale_inputs":
                        # The raw manifest and immutable archive keep actual outcomes;
                        # the validation view cannot borrow them as current acceptance.
                        for index, check in enumerate(manifest["verification"]["checks"]):
                            if manifest["unit_plan"]["acceptance"].get(check["check_id"], {}).get("owner_unit") == key:
                                manifest["verification"]["checks"][index] = {name: value for name, value in check.items()
                                                                            if name not in EXECUTION_KEYS or name == "findings"}
                                manifest["verification"]["checks"][index]["execution_status"] = "not_run"
                        checker.warnings.append(key + ": original " + attempted["outcome"] + " attempt preserved; stale input observations are unverified and grant no current acceptance")
                except (ValueError, OSError, KeyError, TypeError) as error:
                    checker.issue("unit_history", "development-plan", key + ": invalid unfinished attempt: " + str(error))
                continue
            if "completion_ref" not in run:
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
                            require(same({k: v for k, v in observed.items() if k not in ("execution_fingerprints", "canonical_hashes", "review")},
                                         {k: v for k, v in context["input_inventory"].items() if k not in ("execution_fingerprints", "canonical_hashes", "review")}), "pre-start reviewed acceptance inputs changed during execution")
                            owned = {check for check, allocation in manifest["unit_plan"]["acceptance"].items() if allocation["owner_unit"] == key}
                            for check_id in owned:
                                self.canonical_evidence[check_id] = {path: {value, context["input_inventory"]["canonical_hashes"][path]}
                                                                   for path, value in observed["canonical_hashes"].items()}
                            for check in manifest["verification"]["checks"]:
                                if check["check_id"] in owned and check.get("execution_status") in ("passed", "failed"):
                                    require(same(check.get("evaluated_execution_inputs"), observed["execution_fingerprints"]), "check execution inputs changed since actual test observation: " + check["check_id"])
                                    validate_check_runtime(checker.project, context, check, run,
                                                           accepting=action == "complete" or run.get("status") == "completed")
                            validate_continuation_findings(checker.project, context, run, attempt_checks(manifest, key), observed)
                        except (ValueError, OSError, KeyError, TypeError) as error:
                            checker.issue("unit_history", "development-plan", str(error))
                continue
            reasons, valid, integrity_checked = [], False, False
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
                require(same(prepare_inventory(checker, key, inventory), inventory), "reviewed current input inventory is stale")
                reasons = applicability(checker, completed, context, inventory, mapping, previous)
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
                               "revalidation_check_ids": list(manifest.get("unit_plan", {}).get("units", {}).get(key, {}).get("required_check_ids", [])) if reasons else []}
        # Applicability is closed over the CURRENT combined prerequisite graph.
        # A historically valid integration result cannot outlive a stale prerequisite.
        plan = manifest.get("unit_plan", {})
        allocations = plan.get("acceptance", {})
        changed = True
        while changed:
            changed = False
            for key in list(self.preserved):
                dependencies = set(plan["units"][key]["construction_dependencies"])
                for allocation in allocations.values():
                    if allocation["owner_unit"] == key:
                        dependencies.update(allocation["prerequisite_units"])
                        dependencies.update(allocations[check]["owner_unit"] for check in allocation["prerequisite_checks"])
                dependencies.discard(key)
                missing = {dep for dep in dependencies if dep not in self.preserved}
                if missing:
                    self.units[key]["current_applicability"] = "needs_revalidation"
                    self.units[key]["reasons"].append("current prerequisite acceptance unavailable: " + ", ".join(sorted(missing)))
                    self.units[key]["revalidation_check_ids"] = list(plan["units"][key]["required_check_ids"])
                    del self.preserved[key]
                    manifest["unit_runs"][key] = {"status": "pending", "findings": manifest["unit_runs"][key].get("findings", [])}
                    changed = True
        self.checks = {check["check_id"]: copy.deepcopy(check) for record in self.preserved.values() for check in record["checks"]}
        # Every inherited result enters generic/security/release validation through this one view.
        for index, check in enumerate(manifest.get("verification", {}).get("checks", [])):
            key = check.get("check_id")
            if key in self.checks:
                replacement = {**check, **{k: v for k, v in self.checks[key].items() if k in EXECUTION_KEYS}}
                replacement["findings"] = merged_findings(self.checks[key].get("findings", []), check.get("findings", []))
                manifest["verification"]["checks"][index] = replacement
            elif check.get("phase") in ("implementation", "both"):
                owner = manifest.get("unit_plan", {}).get("acceptance", {}).get(key, {}).get("owner_unit")
                if owner in self.units and owner not in self.preserved:
                    manifest["verification"]["checks"][index] = {k: v for k, v in check.items() if k not in EXECUTION_KEYS or k == "findings"}
                    manifest["verification"]["checks"][index]["execution_status"] = "not_run"
        # Old exceptions remain in their original snapshots; they grant no current starts.
        manifest["unit_sequence_exceptions"] = [ref for ref in manifest.get("unit_sequence_exceptions", [])
            if checker.evidence_snapshot(ref, "implementation", "unit_exception")
            and checker.evidence_json(ref).get("development_plan_hash") == plan_hash]
        manifest["prototype_promotions"] = [record for record in manifest.get("prototype_promotions", []) if record.get("unit_id") not in self.preserved]
        if action == "start" and getattr(checker, "_history_capturing", None) != unit_id and unit_id not in self.preserved:
            try:
                context = validate_context(checker.project, manifest.get("execution_contexts", {})[unit_id], unit_id, getattr(checker, "_history_stack", ()), checker._history_cache, evidence_cache=checker.evidence_resolver.cache)
                require(context["manifest"]["artifacts"]["development-plan"]["content_hash"] == plan_hash, "start context belongs to another plan")
            except (ValueError, OSError, KeyError, TypeError) as error:
                checker.issue("unit_history", "development-plan", "capture a valid execution context before start: " + str(error))


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
        target = physical(project, path)
        result[path] = sha(target.read_bytes()) if target.is_file() else "directory" if target.is_dir() else None
    if include_external:
        # Bind prepared originals and readback receipts, including dependency
        # closure, without storing external machine paths or copying payloads.
        resolver = EvidenceResolver(evidence_cache)
        if checker is not None:
            external_refs.extend(checker.evidence_resolver.references.values())
            external_refs.extend(getattr(checker, "_history_cache", {}).get("evidence_references", {}).values())
        for ref in external_refs:
            resolver.resolve(ref)
        for key, path in resolver.resolved_paths.items():
            result["@evidence/" + key + "/original"] = sha(path.read_bytes())
            result["@evidence/" + key + "/receipt"] = sha(resolver._path("receipts", key + ".json").read_bytes())
    return result


def completion_refs(manifest):
    references = {key: list(value) for key, value in manifest.get("completion_history", {}).items()}
    for key, run in manifest.get("unit_runs", {}).items():
        if "completion_ref" in run:
            references.setdefault(key, []).append(run["completion_ref"])
    return references


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


def validate_transition(project, previous, candidate, mapping, *, evidence_cache=None):
    """Validate the whole transition even when a candidate deletes all active indexes."""
    if previous.get("checker_contract_version") != VERSION or previous.get("unit_contract_version") != VERSION:
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
    old_refs, new_refs = completion_refs(previous), completion_refs(candidate)
    old_attempts, new_attempts = attempt_refs(previous), attempt_refs(candidate)
    for unit, references in old_attempts.items():
        require(unit in candidate.get("unit_plan", {}).get("units", {}), "attempted unit identity removed")
        for reference in references:
            require(any(same(reference, item) for item in new_attempts.get(unit, [])), "unfinished attempt history was dropped: " + unit)
    if previous.get("unit_contract_version") == VERSION:
        for unit, run in previous.get("unit_runs", {}).items():
            if run.get("status") not in ("running", "blocked"):
                continue
            current = candidate.get("unit_runs", {}).get(unit, {})
            same_execution = (current.get("status") != "pending" and current.get("started_at") == run.get("started_at")
                              and current.get("run_id") == run.get("run_id")
                              and same(previous.get("execution_contexts", {}).get(unit), candidate.get("execution_contexts", {}).get(unit)))
            if "completion_ref" in current:
                completed, _ = validate_completion(project, current["completion_ref"], evidence_cache=evidence_cache)
                same_execution = (completed["run"].get("started_at") == run.get("started_at")
                                  and completed["run"].get("run_id") == run.get("run_id"))
            if same_execution:
                continue
            preserved = False
            for reference in new_attempts.get(unit, []):
                attempted, _ = validate_attempt(project, reference, evidence_cache=evidence_cache)
                if (same(attempted["run"], {key: value for key, value in run.items() if key != "attempt_ref"})
                        and same(attempted["checks"], attempt_checks(previous, unit))
                        and same(attempted["context_ref"], previous.get("execution_contexts", {}).get(unit))):
                    preserved = True
            require(preserved, "replaced unfinished run needs its exact immutable attempt: " + unit)
            context_ref = candidate.get("execution_contexts", {}).get(unit)
            require(context_ref is not None, "replacement needs a captured continuation context")
            context = validate_context(project, context_ref, unit, evidence_cache=evidence_cache)
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
        if run.get("status") == "completed" and "completion_ref" not in run and candidate.get("unit_contract_version") == VERSION:
            current = candidate.get("unit_runs", {}).get(unit, {})
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
            completed, _ = validate_completion(project, current["completion_ref"], evidence_cache=evidence_cache)
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


def observe_execution_inputs(project, manifest, unit_id, inventory=None, *, evidence_cache=None):
    """Observe bytes only; the actual executor must bind this to its real check event."""
    if inventory is None:
        context = read_ref(project, manifest["execution_contexts"][unit_id])
        inventory = context["input_inventory"]
    return execution_fingerprints(api().Checker(project, manifest, evidence_cache=evidence_cache), inventory["execution_inputs"])


def current_authority(checker):
    probe = api().Checker(checker.project, copy.deepcopy(checker.manifest), checker.contract, evidence_cache=checker.evidence_resolver.cache)
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
    return store_record(project, "candidates", record)


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
        after = encoded(candidate["manifest"])
        directory = HISTORY + "/activations/" + uuid.uuid4().hex
        before_ref = write_new(project, directory + "/before.json", before)
        after_ref = write_new(project, directory + "/after.json", after)
        journal = store_record(project, "activations", {"event": "manifest_activation", "version": VERSION, "candidate_ref": candidate_ref,
                              "before": before_ref, "after": after_ref, "prepared_at": utcnow()}, directory)
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
    for command in ("capture-context", "capture-completion", "capture-attempt", "capture-continuation", "observe-runtime",
                    "assess", "stage", "activate", "recover", "adopt-legacy", "observe-inputs"):
        child = sub.add_parser(command)
        if command in ("capture-context", "capture-completion", "capture-attempt", "capture-continuation", "observe-inputs"):
            child.add_argument("--unit", required=True)
        if command in ("capture-context", "capture-continuation", "assess"):
            child.add_argument("--inventory", required=True)
        if command == "observe-inputs":
            child.add_argument("--inventory")
        if command in ("capture-completion", "capture-attempt"):
            child.add_argument("--context-ref", required=True)
            child.add_argument("--run-id", required=True)
            child.add_argument("--inventory")
        if command == "capture-attempt":
            child.add_argument("--outcome", required=True, choices=("failed", "interrupted"))
        if command == "capture-continuation":
            child.add_argument("--attempt-ref", required=True)
            child.add_argument("--run-id", required=True)
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
    args = parser.parse_args()
    def read(path):
        return api().read_json(physical(args.project, path))
    try:
        require(sys.version_info >= (3, 12), "Python 3.12+ required")
        manifest = read(args.manifest)
        if args.command == "capture-context":
            result = capture_context(args.project, manifest, args.unit, read(args.inventory), evidence_cache=args.evidence_cache)
        elif args.command == "capture-completion":
            result = capture_completion(args.project, manifest, args.unit, read(args.context_ref), args.run_id, read(args.inventory) if args.inventory else None, evidence_cache=args.evidence_cache)
        elif args.command == "capture-attempt":
            result = capture_attempt(args.project, manifest, args.unit, read(args.context_ref), args.run_id, args.outcome,
                                     read(args.inventory) if args.inventory else None, evidence_cache=args.evidence_cache)
        elif args.command == "capture-continuation":
            result = capture_continuation(args.project, manifest, args.unit, read(args.attempt_ref), args.run_id,
                                          read(args.inventory), evidence_cache=args.evidence_cache)
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
            result = observe_execution_inputs(args.project, manifest, args.unit, read(args.inventory) if args.inventory else None, evidence_cache=args.evidence_cache)
        else:
            result = recover_activation(args.project, read(args.journal_ref))
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"result": "blocked", "detail": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
