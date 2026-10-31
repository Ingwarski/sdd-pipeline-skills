"""Current acceptance of preserved observations; never retroactive authorization.

Records and hashes establish consistency, not authentic execution or reviewer
identity. Only the writing entry points import/review supplied facts. Resolution
is read-only and recomputes applicability against the current inputs every time.
"""
import copy
from contextlib import ExitStack

import check_inputs
from history_integrity import history_integrity_scope, review_source_requires_full


VERSION = 1
EVENT = "reviewed_unit_acceptance"
SOURCE_EVENT = "external_check_observations"


def history():
    import sdd_check
    return sdd_check.history_api()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def enabled(manifest):
    return all(type(manifest.get(key)) is int and manifest[key] == 4
               for key in ("checker_contract_version", "unit_contract_version"))


def authority(manifest):
    """Bind the present decision without claiming original execution permission."""
    result = {key: copy.deepcopy(manifest.get(key)) for key in
              ("state", "implementation_gate", "product_scope", "active_baseline", "approved_baseline_id")}
    result["development_plan_hash"] = manifest["artifacts"]["development-plan"]["content_hash"]
    return result


def _stored(project, kind, record):
    h = history()
    data = h.encoded(record)
    path = h.HISTORY + "/" + kind + "/" + h.sha(data) + "/record.json"
    return _publish(project, path, data)


def _publish(project, path, data, *, existing_winner=False):
    return history().publish_immutable(project, path, data, existing_winner=existing_winner)


def _audit(resolver):
    for reference in tuple(resolver.references.values()):
        resolver.resolve(reference)


def import_observations(project, source_manifest, unit_id, *, evidence_cache=None):
    """Freeze supplied originals once. This neither runs nor passes any check."""
    h = history()
    require(isinstance(source_manifest, dict), "original observation manifest required")
    require(unit_id in source_manifest.get("unit_plan", {}).get("units", {}), "unknown original unit")
    _checks(source_manifest)
    checker = h.api().Checker(project, copy.deepcopy(source_manifest), evidence_cache=evidence_cache)
    with h.snapshot_hash_scope():
        paths = h.referenced_paths(project, source_manifest, checker=checker)
        hashes = {path: h.sha(h.physical(project, path).read_bytes()) for path in sorted(paths)}
        identity = h.sha(h.encoded({"manifest": source_manifest, "unit_id": unit_id, "sources": hashes}))
        directory = h.HISTORY + "/external-observations/" + identity
        target = h.physical(project, directory + "/record.json")
        if target.exists():
            ref = {"path": directory + "/record.json", "content_hash": h.sha(target.read_bytes())}
            record = h.read_ref(project, ref)
            require(record.get("event") == SOURCE_EVENT and record.get("version") == VERSION
                    and record.get("unit_id") == unit_id and record.get("import_identity") == identity,
                    "existing observation import differs")
            require(h.same(h.read_ref(project, record["manifest_ref"]), source_manifest), "imported manifest changed")
            h.validate_files(project, record)
            return ref
        manifest_ref = _publish(project, directory + "/manifest.json", h.encoded(source_manifest))
        files = {}
        for path in sorted(paths):
            data = h.physical(project, path).read_bytes()
            require(h.sha(data) == hashes[path], "original source changed during import: " + path)
            destination = directory + "/files/" + path
            target = h.physical(project, destination)
            if not target.exists():
                try:
                    h.write_snapshot(project, destination, data)
                except FileExistsError:
                    pass  # Identical concurrent imports can share complete snapshots.
            require(h.physical(project, destination).is_file()
                    and h.sha(target.read_bytes()) == hashes[path], "existing original snapshot differs: " + path)
            files[path] = {"path": destination, "content_hash": hashes[path]}
        require({path: ref["content_hash"] for path, ref in files.items()} == hashes,
                "original sources changed during import")
        record = {"event": SOURCE_EVENT, "version": VERSION, "unit_id": unit_id,
                  "imported_at": h.utcnow(), "import_identity": identity, "manifest_ref": manifest_ref,
                  "snapshot_root": directory + "/files", "files": files}
        _audit(checker.evidence_resolver)
        reference = _publish(project, directory + "/record.json", h.encoded(record), existing_winner=True)
        winner = h.read_ref(project, reference)
        require(h.same({key: value for key, value in winner.items() if key != "imported_at"},
                       {key: value for key, value in record.items() if key != "imported_at"}),
                "concurrent observation import differs")
        require(h.api().timestamp(winner["imported_at"]) <= h.api().timestamp(h.utcnow()), "import time is in the future")
        return reference


def _checks(manifest):
    checks = manifest.get("verification", {}).get("checks")
    require(isinstance(checks, list), "original checks must be a list")
    result = {}
    for check in checks:
        require(isinstance(check, dict) and isinstance(check.get("check_id"), str)
                and check["check_id"] and check["check_id"] not in result, "missing/duplicate original check identity")
        result[check["check_id"]] = check
    return result


def _blocking(*findings):
    rows = history().merged_findings(*findings)
    return any(row["status"] != "closed" and
               (row["severity"] in ("P0", "P1") or row["release_effect"] == "blocking") for row in rows)


def _review(review):
    h = history()
    require(isinstance(review, dict) and review.get("complete") is True
            and all(isinstance(review.get(key), str) and review[key].strip() for key in ("reviewer", "rationale")),
            "complete current owner review and rationale required")
    require(h.api().timestamp(review.get("reviewed_at")) <= h.api().timestamp(h.utcnow()), "review is in the future")
    require(all(isinstance(review.get(field, {}), dict) for field in ("preconditions", "reuse_eligibility")),
            "reviewed preconditions/reuse eligibility must be check maps")


def _selected_source(checker, source, original, request, inventory):
    """Read only the active proof closure, retaining immutable full membership."""
    h = history()
    files = source.get("files")
    require(isinstance(files, dict), "original source membership is missing")
    selected = {}
    probe = h.api().Checker(checker.project, original, evidence_cache=checker.evidence_resolver.cache)
    probe._history_hash_owner = h._snapshot_hash_owner.get()
    probe._history_snapshot_root = source["snapshot_root"]
    probe._history_overlay = {}
    archive = h._source_archive.get()
    if archive is not None:
        probe._history_source_archive = archive

    def member(logical):
        ref = files[logical]
        require(ref.get("path") == source["snapshot_root"] + "/" + logical, "original source membership changed")
        h.physical(checker.project, logical)
        path = h.archived_source_path(checker.project, ref)
        require(path.is_file() and h.api().hash_matches(ref["content_hash"], probe.file_hash(path)),
                "active original source is missing or changed: " + logical)
        selected[logical] = ref
        probe._history_overlay = dict(selected)
        return path

    def resolve_path(logical):
        h.physical(checker.project, logical)
        if logical.startswith(h.HISTORY + "/"):
            return h.physical(checker.project, logical)  # Immutable envelopes are validated by their own read_ref callers.
        if logical in files:
            return member(logical)
        children = {name: ref for name, ref in files.items() if name.startswith(logical.rstrip("/") + "/")}
        if children:
            for name in children:
                member(name)  # A selected directory always retains full original membership.
            return h.source_view_path(checker.project, source["snapshot_root"], dict(selected), logical, archive)
        path = h.physical(checker.project, source["snapshot_root"] + "/" + logical)
        require(not path.is_file(), "unrecorded original source cannot be substituted: " + logical)
        return path  # A genuinely absent planned input remains absent; never use today's project file.

    for artifact in original["artifacts"].values():
        resolve_path(artifact["path"])
    policy = original.get("evidence_storage", {}).get("policy_path", "forge/evidence-policy.json")
    if policy in files:
        resolve_path(policy)
    plan, all_checks = original["unit_plan"], _checks(original)
    units, checks = {request["unit_id"]}, set()
    pending_units = [request["unit_id"]]
    pending_checks = [key for key, row in plan["acceptance"].items() if row["owner_unit"] == request["unit_id"]]
    while pending_units or pending_checks:
        while pending_units:
            unit = pending_units.pop()
            for prior in plan["units"][unit]["construction_dependencies"]:
                if prior not in units:
                    units.add(prior)
                    pending_units.append(prior)
                    pending_checks.extend(plan["units"][prior]["required_check_ids"])
        if pending_checks:
            key = pending_checks.pop()
            if key not in checks:
                require(key in all_checks and key in plan["acceptance"], "unknown original prerequisite check")
                checks.add(key)
                allocation = plan["acceptance"][key]
                pending_checks.extend(allocation["prerequisite_checks"])
                prior_owner = allocation["owner_unit"]
                if prior_owner != request["unit_id"] and prior_owner not in units:
                    units.add(prior_owner)
                    pending_units.append(prior_owner)
                    pending_checks.extend(plan["units"][prior_owner]["required_check_ids"])
                for unit in allocation["prerequisite_units"]:
                    if unit not in units:
                        units.add(unit)
                        pending_units.append(unit)
                        pending_checks.extend(plan["units"][unit]["required_check_ids"])
    paths = set(inventory.get("execution_inputs", {}))
    for key in checks:
        paths.update(all_checks[key].get("evaluated_execution_inputs", {}))
    scope = {"implementation_paths": sorted(paths), "checks": [all_checks[key] for key in checks],
             "units": {unit: plan["units"][unit] for unit in units},
             "preconditions": [row for rows in request.get("review", {}).get("preconditions", {}).values()
                               if isinstance(rows, list) for row in rows if isinstance(row, dict) and row.get("status") == "established"]}
    accounting = original.get("evidence_accounting")
    if h.evidence_reference(accounting) is not None:
        scope["evidence_accounting"] = accounting
    h.referenced_paths(checker.project, scope, checker=probe, path_resolver=resolve_path)
    # Preserve externally resolved identities for optimistic transaction guards.
    probe._history_cache = checker._history_cache
    h.remember_evidence(probe)
    return {**source, "files": dict(selected)}


def _source(checker, request, inventory):
    h = history()
    source = h.read_ref(checker.project, request["source_ref"])
    require(isinstance(source, dict), "original source envelope must be an object")
    kind, unit = request["source_kind"], request["unit_id"]
    require(kind in ("legacy_archive", "external_observations"), "unknown review source kind")
    if kind == "legacy_archive":
        require(source.get("event") == "legacy_execution_archive" and source.get("version") == h.VERSION
                and source.get("acceptance") == "unverified_not_reusable", "expected retained legacy archive")
        require(request["source_ref"] in checker.manifest.get("legacy_history", []), "legacy source is not retained in current history")
    else:
        require(source.get("event") == SOURCE_EVENT and source.get("version") == VERSION
                and source.get("unit_id") == unit, "unsupported original observation import")
    original = h.read_ref(checker.project, source["manifest_ref"])
    require(isinstance(original, dict), "original manifest must be an object")
    require(kind != "legacy_archive" or h.legacy_format(original), "legacy source must preserve version 1")
    require(unit in original.get("unit_plan", {}).get("units", {}), "review unit absent from original observations")
    selected = source if review_source_requires_full(kind) else _selected_source(checker, source, original, request, inventory)
    frozen = h.historical_checker(checker.project, original, selected,
                                  cache=checker._history_cache, evidence_cache=checker.evidence_resolver.cache)
    checks = _checks(original)
    eligible = {key: check["acceptance"] for key, check in checks.items()
                if check.get("phase") in ("implementation", "both") and check.get("execution_status") != "not_applicable"}
    reference = original["verification"]["acceptance_ref"]
    require(reference.get("path") == "docs/qa-checklist.md", "original QA contract belongs to canonical QA")
    frozen.canonical_json(reference["path"], reference["heading"], eligible)
    plan = original["unit_plan"]
    frozen.canonical_json("docs/development-plan.md", plan["definition_ref"]["heading"], plan)
    for key, check in checks.items():
        if key in eligible:
            require(key in plan["acceptance"], "unallocated original execution check: " + key)
            require(frozen.reference_path(check.get("definition_ref")) == "docs/qa-checklist.md"
                    and key in frozen.reference(check["definition_ref"], "qa-checklist"), "original authored QA definition is missing: " + key)
    return source, original, frozen


def _original(checker, request):
    h = history()
    inventory = h.read_ref(checker.project, request["original_inventory_ref"])
    source, original, frozen = _source(checker, request, inventory)
    require(h.same(h.prepare_inventory(frozen, request["unit_id"], inventory), inventory),
            "original reviewed inventory differs from preserved original bytes")
    return source, original, frozen, inventory


def prepare_original_inventory(project, manifest, unit_id, source_kind, source_ref, inventory, *, evidence_cache=None):
    """Review preserved old bytes now without creating old execution facts."""
    h = history()
    checker = h.api().Checker(project, copy.deepcopy(manifest), evidence_cache=evidence_cache)
    checker._history_cache = {}
    with _scope(checker):
        _, _, frozen = _source(checker, {"unit_id": unit_id, "source_kind": source_kind, "source_ref": source_ref}, inventory)
        prepared = h.prepare_inventory(frozen, unit_id, inventory)
        _audit(frozen.evidence_resolver)
        return _stored(project, "reviewed-original-inventories", prepared)


def _definition(check):
    h = history()
    result = {key: copy.deepcopy(value) for key, value in check.items() if key not in h.EXECUTION_KEYS}
    # Review can establish reuse policy now; it cannot change the check itself.
    for key in ("reuse_policy", "dependency_review"):
        result.get("acceptance", {}).pop(key, None)
    return result


def _dependency_ids(manifest, check_id):
    pending, seen = [check_id], set()
    allocations = manifest["unit_plan"]["acceptance"]
    while pending:
        key = pending.pop()
        require(key in allocations, "unknown acceptance prerequisite: " + key)
        if key not in seen:
            seen.add(key)
            pending.extend(allocations[key]["prerequisite_checks"])
    return seen


def _applicable(original, current, old_inventory, inventory, key):
    """Per-check definitions; shared source selections stay conservative."""
    h = history()
    for field in ("inputs", "environment"):
        require(h.same(old_inventory[field], inventory[field]), "changed shared " + field)
    before, after = old_inventory["bindings"], inventory["bindings"]
    for field in set(before) | set(after):
        if field in ("qa", "acceptance", "unit"):
            continue
        require(h.same(before.get(field), after.get(field)), "changed shared binding: " + field)
    require(h.same({k: v for k, v in before["unit"].items() if k != "required_check_ids"},
                   {k: v for k, v in after["unit"].items() if k != "required_check_ids"}), "changed shared unit definition")
    old_checks, new_checks = _checks(original), _checks(current)
    prior_ids, current_ids = _dependency_ids(original, key), _dependency_ids(current, key)
    require(prior_ids == current_ids, "changed acceptance prerequisites")
    for dependency in current_ids:
        require(dependency in old_checks and dependency in new_checks, "missing original prerequisite definition")
        require(h.same(_definition(old_checks[dependency]), _definition(new_checks[dependency])),
                "changed check definition: " + dependency)
        require(h.same(original["unit_plan"]["acceptance"][dependency], current["unit_plan"]["acceptance"][dependency]),
                "changed acceptance allocation: " + dependency)
    expected = check_inputs.expected(inventory, key)
    for path, fingerprint in expected.items():
        require(old_inventory["execution_inputs"].get(path) == inventory["execution_inputs"].get(path)
                and old_inventory["execution_fingerprints"].get(path) == fingerprint,
                "changed execution dependency: " + path)
    # Removed original selections cannot silently disappear from acceptance.
    require(set(old_inventory["execution_inputs"]) <= set(inventory["execution_inputs"]), "original input selections were dropped")


def _runtime_record(checker, reference):
    h = history()
    require(reference is not None, "missing original runtime observation")
    if reference.get("path", "").startswith(h.HISTORY + "/"):
        return h.read_ref(checker.project, reference)
    require(checker.evidence_snapshot(reference, "implementation", "reviewed_runtime"), "original runtime receipt is missing or changed")
    return checker.evidence_json(reference)


def _runtime(checker, check, run, unit, inventory, executed):
    h = history()
    reference = check.get("runtime_observation_ref")
    runtime = _runtime_record(checker, reference)
    require(isinstance(runtime, dict), "original runtime observation must be an object")
    if runtime.get("event") == "runtime_observation":
        original_reference = checker._history_overlay.get(reference.get("path"), reference)
        runtime = h.validate_runtime_observation(checker.project, original_reference)
        observed = h.api().timestamp(runtime["observed_at"])
        require(h.api().timestamp(run["started_at"]) <= h.api().timestamp(runtime["started_at"]),
                "runtime probe predates original run")
    else:
        require(runtime.get("event") == "external_runtime_observation" and runtime.get("version") == VERSION,
                "unsupported independent runtime proof")
        require(runtime.get("unit_id") == unit and runtime.get("run_id") == check["run_id"],
                "independent runtime proof belongs to another execution")
        evidence = runtime.get("evidence")
        require(isinstance(evidence, list) and evidence and all(item in check["evidence"] for item in evidence),
                "independent runtime proof must bind original execution evidence")
        native = []
        for item in evidence:
            payload = checker.evidence_json(item)
            if isinstance(payload, dict):
                native.append(payload.get("runtime", payload))
        require(any(isinstance(value, dict) and all(value.get(field) == runtime.get(field)
                    for field in ("environment", "observed_at", "unit_id", "run_id")) for value in native),
                "independent runtime values are not established by original native evidence")
        observed = h.api().timestamp(runtime.get("observed_at"))
    require(h.api().timestamp(run["started_at"]) <= observed <= executed, "runtime observation outside original execution")
    require(isinstance(runtime.get("environment"), dict) and runtime["environment"]
            and h.same(runtime["environment"], inventory["environment"]), "original runtime identities differ or are unknown")


def _proof(checker, original, inventory, check, unit, reviewed, current_checker):
    h = history()
    require(check.get("execution_status") == "passed" and check.get("definition_status") == "prepared", "original check is not passed/prepared")
    require(isinstance(check.get("executor"), str) and check["executor"].strip(), "missing original executor")
    run = original.get("unit_runs", {}).get(unit)
    require(isinstance(run, dict) and isinstance(run.get("run_id"), str) and run["run_id"], "missing original run identity")
    require(check.get("run_id") == run["run_id"], "original observation belongs to another run")
    executed = h.api().timestamp(check.get("executed_at"))
    require(h.api().timestamp(run.get("started_at")) <= executed <= reviewed, "original execution chronology is invalid")
    if run.get("completed_at") is not None:
        require(executed <= h.api().timestamp(run["completed_at"]) <= reviewed, "original finish chronology is invalid")
    require(not _blocking(check.get("findings", []), run.get("findings", [])), "original blocking findings remain unresolved")
    require(check.get("evaluated_plan_hash") == original["artifacts"]["development-plan"]["content_hash"],
            "original observation does not bind its authored plan")
    evidence = check.get("evidence")
    require(isinstance(evidence, list) and evidence, "missing original execution evidence")
    _runtime(checker, check, run, unit, inventory, executed)
    hashes, _ = checker.source_inventory(check, "evaluated_source_hashes")
    paths = check_inputs.required_paths(checker, check)
    require(isinstance(hashes, dict) and paths <= set(hashes), "original source/test/config hashes are incomplete")
    for path, value in hashes.items():
        require(checker.snapshot(path, value, "implementation", "reviewed_original_source"), "original source hash differs: " + path)
    observed = check.get("evaluated_execution_inputs")
    expected = check_inputs.expected(inventory, check["check_id"])
    if observed is not None:
        require(h.same(observed, expected), "original observed execution inputs differ")
    else:
        # Older file hashes can prove files; they cannot prove a tree's members.
        for path, fingerprint in expected.items():
            require(fingerprint.get("mode") == "file" and fingerprint.get("exists") is True
                    and h.api().hash_matches(hashes.get(path), fingerprint.get("content_hash")),
                    "original execution input fact is unknown: " + path)
    for item in evidence:
        reference = h.evidence_reference(item)
        if reference is not None:
            require(reference["provenance"].get("unit_id") == unit and reference["provenance"].get("run_id") == run["run_id"],
                    "original evidence belongs to another run/unit")
        require(checker.evidence_snapshot(item, "implementation", "reviewed_original_evidence", checker.check_bindings(check, evidence=item)),
                "original evidence unreadable, corrupt, mismatched or unaccounted")
        if reference is not None:
            current_checker.evidence_resolver.resolve(reference)
            current_checker.evidence_accounting(reference)
    expected_kind = "security" if check.get("gate_id") == h.api().SECURITY_GATE else h.api().GATE_KINDS.get(check.get("gate_id"))
    require(expected_kind is None or expected_kind in {checker.evidence_kind(item) for item in evidence}, "wrong original evidence class")
    mode = check.get("acceptance", {}).get("evidence_mode")
    require(check.get("execution_mode") == mode and mode in ("component", "real_consumers"), "original execution mode differs")
    require(mode != "real_consumers" or any(checker.evidence_kind(item) == "integration" for item in evidence),
            "real-consumer acceptance requires integration evidence")


def _known_by(value, rows, run, *, ceiling=None):
    """A validated immutable envelope bounds existence, never execution time."""
    h = history()
    try:
        bound = h.api().timestamp(value)
        require(bound <= h.api().timestamp(h.utcnow()), "counterevidence bound is in the future")
        if ceiling is not None:
            require(bound <= h.api().timestamp(ceiling), "counterevidence bound postdates its retained decision")
        for observed in [run.get("started_at"), run.get("completed_at")] + [row.get("executed_at") for row in rows]:
            if observed is not None:
                require(h.api().timestamp(observed) <= bound, "counterevidence bound predates recorded execution facts")
        return value
    except (ValueError, TypeError):
        return None


def _counter_rows(checker, unit):
    h = history()
    rows = [(row, None) for row in checker.manifest["verification"]["checks"]]
    references = list(checker.manifest.get("attempt_history", {}).get(unit, []))
    current = checker.manifest.get("unit_runs", {}).get(unit, {}).get("attempt_ref")
    if current is not None and current not in references:
        references.append(current)
    for reference in references:
        attempt = h.read_ref(checker.project, reference)
        require(attempt.get("event") == "unit_attempt" and attempt.get("version") == h.VERSION and attempt.get("unit_id") == unit,
                "invalid retained counterevidence identity")
        observations = attempt.get("checks", [])
        bound = _known_by(attempt.get("captured_at"), observations, attempt.get("run", {}))
        rows.extend((row, bound) for row in observations)
    cache = getattr(checker, "_reviewed_counterevidence", None)
    sources = cache.get("_source_metadata") if cache is not None else None
    if sources is None:
        sources, metadata = [], {}
        def read(reference):
            identity = h.sha(h.encoded(reference))
            if identity not in metadata:
                metadata[identity] = h.read_ref(checker.project, reference)
            return metadata[identity]
        for review_unit, references in checker.manifest.get("reviewed_acceptance", {}).items():
            for reference in references:
                review = read(reference)
                require(review.get("event") == EVENT and review.get("version") == VERSION and review.get("unit_id") == review_unit,
                        "invalid retained review counterevidence identity")
                source = read(review["source_ref"])
                external = source.get("event") == SOURCE_EVENT
                require((external and source.get("version") == VERSION and source.get("unit_id") == review_unit)
                        or source.get("event") == "legacy_execution_archive" and source.get("version") == h.VERSION,
                        "invalid retained counterevidence source")
                sources.append((review, source, read(source["manifest_ref"])))
        if cache is not None:
            cache["_source_metadata"] = sources
    for review, source, original in sources:
        external = source.get("event") == SOURCE_EVENT
        owned = {key for key, allocation in original["unit_plan"]["acceptance"].items() if allocation["owner_unit"] == unit}
        observations = [check for key, check in _checks(original).items() if key in owned]
        bound = _known_by(source.get("imported_at" if external else "archived_at"), observations,
                          original.get("unit_runs", {}).get(unit, {}), ceiling=review.get("recorded_at"))
        rows.extend((row, bound) for row in observations)
    # A raw retained copy of the same undated observation does not erase its
    # independently recorded existence bound. No observation is rewritten.
    facts = lambda row: h.sha(h.encoded({key: value for key, value in row.items()
        if key == "check_id" or key in h.EXECUTION_KEYS - {"findings", "rationale", "seal_ref", "reused_from"}}))
    known = {}
    for row, bound in rows:
        if bound is not None:
            key = facts(row)
            if key not in known or h.api().timestamp(bound) < h.api().timestamp(known[key]):
                known[key] = bound
    rows = [(row, bound or known.get(facts(row))) for row, bound in rows]
    return rows


def _prerequisites(frozen, current, original, inventory, check, reviewed):
    """Original consumer facts remain distinct from today's accepted graph."""
    h = history()
    plan, checks = original["unit_plan"], _checks(original)
    owner = plan["acceptance"][check["check_id"]]["owner_unit"]
    pending_checks = list(plan["acceptance"][check["check_id"]]["prerequisite_checks"])
    pending_units = list(plan["acceptance"][check["check_id"]]["prerequisite_units"]) + list(plan["units"][owner]["construction_dependencies"])
    check_ids, unit_ids = set(), set()
    while pending_checks or pending_units:
        while pending_units:
            unit = pending_units.pop()
            require(unit in plan["units"] and unit != owner, "invalid original unit prerequisite")
            if unit not in unit_ids:
                unit_ids.add(unit)
                pending_checks.extend(plan["units"][unit]["required_check_ids"])
                pending_units.extend(plan["units"][unit]["construction_dependencies"])
        if pending_checks:
            key = pending_checks.pop()
            require(key in checks and key != check["check_id"], "invalid original check prerequisite")
            if key not in check_ids:
                check_ids.add(key)
                pending_checks.extend(plan["acceptance"][key]["prerequisite_checks"])
                pending_units.extend(plan["acceptance"][key]["prerequisite_units"])
                prior_owner = plan["acceptance"][key]["owner_unit"]
                if prior_owner != owner and prior_owner not in unit_ids:
                    pending_units.append(prior_owner)
    facts = {"checks": {}, "units": {}}
    executed = h.api().timestamp(check["executed_at"])
    validated_completions = {}
    for key in sorted(check_ids):
        prior = checks[key]
        unit = plan["acceptance"][key]["owner_unit"]
        run = original.get("unit_runs", {}).get(unit, {})
        if "completion_ref" in run:
            if unit not in validated_completions:
                validated_completions[unit] = h.validate_completion(frozen.project, run["completion_ref"],
                    cache=frozen._history_cache, evidence_cache=frozen.evidence_resolver.cache)[0]
            completion = validated_completions[unit]
            require(any(h.same(prior, row) for row in completion["checks"]), "original prerequisite differs from validated completion")
        else:
            actual = prior.get("evaluated_execution_inputs")
            if actual is None:
                hashes, _ = frozen.source_inventory(prior, "evaluated_source_hashes")
                paths = check_inputs.required_paths(frozen, prior)
                if not check_inputs.fine_grained(prior):
                    paths.update(plan["units"][unit]["implementation_paths"])
                require(paths <= set(hashes), "original prerequisite source facts are incomplete")
                selections = {path: {"mode": "file"} for path in paths}
            else:
                require(isinstance(actual, dict) and actual, "original prerequisite input facts are missing")
                selections = {path: {"mode": value["mode"]} for path, value in actual.items()}
            expected = h.execution_fingerprints(frozen, selections)
            observed = copy.deepcopy(inventory)
            observed.update(execution_inputs=selections, execution_fingerprints=expected,
                            check_execution_fingerprints={key: expected},
                            environment=_runtime_record(frozen, prior.get("runtime_observation_ref")).get("environment"))
            _proof(frozen, original, observed, prior, unit, reviewed, current)
        require(h.api().timestamp(prior["executed_at"]) <= executed, "original prerequisite evidence postdates consumer execution")
        facts["checks"][key] = {"unit_id": unit, "executed_at": prior["executed_at"]}
    for unit in sorted(unit_ids):
        run = original.get("unit_runs", {}).get(unit, {})
        times = [checks[key]["executed_at"] for key in plan["units"][unit]["required_check_ids"]]
        require(times, "original prerequisite unit has no observed required checks")
        facts["units"][unit] = {"recorded_status": run.get("status"), "observed_at": max(times, key=h.api().timestamp)}
        if run.get("completed_at"):
            require(h.api().timestamp(run["completed_at"]) <= executed, "original prerequisite completion postdates consumer")
            facts["units"][unit]["completed_at"] = run["completed_at"]
    return facts


def require_no_counterevidence(checker, unit, original_check):
    """All retained negative observations constrain every accepted source."""
    h = history()
    cache = getattr(checker, "_reviewed_counterevidence", None)
    if cache is not None and unit not in cache:
        cache[unit] = _counter_rows(checker, unit)
    rows = cache[unit] if cache is not None else _counter_rows(checker, unit)
    executed = h.api().timestamp(original_check["executed_at"])
    for row, known_by in rows:
        if row.get("check_id") != original_check["check_id"]:
            continue
        status = row.get("execution_status")
        negative = status in ("failed", "blocked") or status == "not_run" and any(
            row.get(field) for field in ("executor", "executed_at", "evidence"))
        if negative:
            try:
                newer = h.api().timestamp(row.get("executed_at")) >= executed
            except (ValueError, TypeError):
                newer = known_by is None or h.api().timestamp(known_by) >= executed
            require(not newer, "later or undated failed/ambiguous observation prevents reuse")
        elif status == "passed":
            fields = ("executor", "executed_at", "run_id", "evidence", "execution_mode", "evaluated_plan_hash",
                      "evaluated_source_hashes", "evaluated_execution_inputs", "source_inventory_ref", "runtime_observation_ref")
            different = any(not h.same(row.get(field), original_check.get(field)) for field in fields)
            if different:
                try:
                    newer = h.api().timestamp(row.get("executed_at")) >= executed
                except (ValueError, TypeError):
                    newer = True
                require(not newer, "distinct current/later execution must be validated on its own merits")


def _preconditions(checker, current_checker, review, key, check):
    """Owner enumerates prose-only prerequisites; hashes cannot prove completeness."""
    h = history()
    mapping = review.get("preconditions")
    require(isinstance(mapping, dict) and key in mapping and isinstance(mapping[key], list),
            "missing explicit owner review of original check preconditions")
    for condition in mapping[key]:
        require(isinstance(condition, dict) and set(condition) == {"source_ref", "observation_ref", "observed_at", "status"},
                "original precondition requires exact source/evidence/time/status facts")
        require(condition["status"] in ("established", "unknown"), "unsupported original precondition status")
        require(condition["status"] == "established", "original essential precondition is unknown")
        observed = h.api().timestamp(condition["observed_at"])
        require(observed <= h.api().timestamp(check["executed_at"]), "original precondition postdates execution")
        for label in ("source_ref", "observation_ref"):
            reference = condition[label]
            require(checker.evidence_snapshot(reference, "implementation", "reviewed_precondition"),
                    "original precondition " + label + " is missing or changed")
            external = h.evidence_reference(reference)
            if external is not None:
                current_checker.evidence_resolver.resolve(external)
                current_checker.evidence_accounting(external)
        native = checker.evidence_json(condition["observation_ref"])
        require(isinstance(native, dict) and native.get("observed_at") == condition["observed_at"],
                "original precondition date is not established by native evidence")


def diagnostic(metadata, limit=20):
    """Bound user-facing diagnostics while internal dependency truth stays whole."""
    allowed = {"current_applicability", "source_kind", "source_ref", "review_ref", "reviewed_at", "recorded_at", "original_run",
               "original_authority", "original_authority_status", "accepted_check_ids", "revalidation_check_ids", "reasons", "check_decisions"}
    result = {key: copy.deepcopy(value) for key, value in metadata.items() if key in allowed}
    for key in ("accepted_check_ids", "revalidation_check_ids", "reasons"):
        values = result.get(key, [])
        result[key + "_count"] = len(values)
        result[key] = [str(value)[:500] for value in values[:limit]]
    decisions = result.get("check_decisions", {})
    result["check_decision_count"] = len(decisions)
    result["check_decisions"] = {key: {**value, "reasons": [str(reason)[:500] for reason in value.get("reasons", [])[:limit]]}
                                 for key, value in list(decisions.items())[:limit]}
    return result


def _evaluate(checker, record, *, capturing=False):
    h = history()
    require(enabled(checker.manifest), "reviewed acceptance requires checker/unit contract 4")
    _review(record["review"])
    if not capturing:
        require(h.api().timestamp(record["review"]["reviewed_at"]) <= h.api().timestamp(record.get("recorded_at"))
                <= h.api().timestamp(h.utcnow()), "invalid system acceptance recording time")
    require(isinstance(record.get("authority_fields"), dict), "authority at review must be preserved")
    unit = record["unit_id"]
    require(unit in checker.manifest["unit_plan"]["units"], "reviewed unit disappeared")
    gaps = record.get("procedural_gaps")
    require(isinstance(gaps, list) and gaps and len(gaps) == len(set(gaps))
            and all(isinstance(gap, str) and gap.strip() for gap in gaps), "explicit original procedural gaps required")
    source, original, frozen, old_inventory = _original(checker, record)
    reviewed = h.api().timestamp(record["review"]["reviewed_at"])
    require(h.api().timestamp(source.get("archived_at", source.get("imported_at"))) <= reviewed,
            "current review predates original import/archive")
    current = h.prepare_inventory(checker, unit, record["current_inventory"])
    require(h.api().timestamp(old_inventory["review"]["reviewed_at"]) <= reviewed
            and h.api().timestamp(current["review"]["reviewed_at"]) <= reviewed,
            "acceptance decision predates an input owner review")
    old_checks, new_checks = _checks(original), _checks(checker.manifest)
    old_owned = {key for key, row in original["unit_plan"]["acceptance"].items() if row["owner_unit"] == unit}
    owned = {key for key, row in checker.manifest["unit_plan"]["acceptance"].items() if row["owner_unit"] == unit}
    require(old_owned <= set(old_checks) and owned <= set(new_checks), "allocated check observations are missing")
    decisions, accepted, prerequisite_facts = {}, {}, {}
    for key in sorted(old_owned | owned):
        outcome, reasons = "unresolved", []
        try:
            require(key in old_owned and key in owned, "original/current check has no matching owner allocation")
            original_check, check = old_checks[key], new_checks[key]
            require(original_check.get("acceptance", {}).get("reuse_policy") in (None, "deterministic_isolated"),
                    "original explicit fresh/live reuse policy cannot be overridden")
            policy = check["acceptance"].get("reuse_policy")
            require(policy in (None, "deterministic_isolated"), "fresh/live checks require current execution")
            require(policy == "deterministic_isolated" or record["review"].get("reuse_eligibility", {}).get(key) == "deterministic_isolated",
                    "missing current owner review of deterministic reuse eligibility")
            check_inputs.fine_grained(check)  # Validate supplied review; absent keeps whole-unit input fallback.
            _proof(frozen, original, old_inventory, original_check, unit, reviewed, checker)
            _preconditions(frozen, checker, record["review"], key, original_check)
            facts = _prerequisites(frozen, checker, original, old_inventory, original_check, reviewed)
            require_no_counterevidence(checker, unit, original_check)
            outcome = "needs_revalidation"
            _applicable(original, checker.manifest, old_inventory, current, key)
            require(not _blocking(check.get("findings", []), checker.manifest.get("unit_runs", {}).get(unit, {}).get("findings", [])),
                    "current blocking findings prevent acceptance")
            decisions[key] = {"original_check_id": key, "outcome": "applicable", "reasons": []}
            accepted[key] = copy.deepcopy(original_check)
            prerequisite_facts[key] = facts
            views = getattr(checker, "_reviewed_evidence_views", None)
            if views is None:
                views = checker._reviewed_evidence_views = {}
            for evidence in original_check["evidence"] + ([original_check["source_inventory_ref"]] if "source_inventory_ref" in original_check else []):
                views[h.sha(h.encoded(evidence))] = {"checker": frozen, "check": copy.deepcopy(original_check)}
        except (ValueError, OSError, KeyError, TypeError) as error:
            reasons.append(str(error))
            decisions[key] = {"original_check_id": key if key in old_owned else None, "outcome": outcome, "reasons": reasons}
    _audit(frozen.evidence_resolver)
    h.remember_evidence(frozen)
    for key, reference in frozen.evidence_resolver.references.items():
        existing = checker.evidence_resolver.references.get(key)
        require(existing is None or h.same(existing, reference), "review evidence identity conflict")
        checker.evidence_resolver.references[key] = copy.deepcopy(reference)
    return decisions, accepted, original, current, prerequisite_facts


def _scope(checker):
    h = history()
    stack = ExitStack()
    stack.enter_context(history_integrity_scope(checker.manifest))
    stack.enter_context(h.source_archive_scope(checker.project, checker.manifest.get("source_archive_index_ref"),
                                              checker.evidence_resolver.cache, policy_manifest=checker.manifest))
    stack.enter_context(h.snapshot_hash_scope(getattr(checker, "_history_hash_owner", None)))
    return stack


def capture(project, manifest, request, *, evidence_cache=None):
    h = history()
    require(isinstance(request, dict), "review request must be an object")
    expected = {"unit_id", "source_kind", "source_ref", "original_inventory_ref", "current_inventory", "review", "procedural_gaps"}
    require(set(request) == expected, "review request fields differ from the versioned contract")
    checker = h.api().Checker(project, copy.deepcopy(manifest), evidence_cache=evidence_cache)
    checker._history_cache = {}
    checker._reviewed_counterevidence = {}
    record = {"event": EVENT, "version": VERSION, **copy.deepcopy(request), "authority_fields": authority(manifest)}
    with _scope(checker):
        decisions, _, _, current, _ = _evaluate(checker, record, capturing=True)
        record["current_inventory"] = current
        record["check_decisions"] = decisions
        _audit(checker.evidence_resolver)
        identity = h.sha(h.encoded(record))
        record["recorded_at"] = h.utcnow()
        reference = _publish(project, h.HISTORY + "/reviewed-acceptance/" + identity + "/record.json",
                             h.encoded(record), existing_winner=True)
        winner = h.read_ref(project, reference)
        require(h.same({key: value for key, value in winner.items() if key != "recorded_at"},
                       {key: value for key, value in record.items() if key != "recorded_at"}),
                "concurrent acceptance capture differs")
        require(h.api().timestamp(record["review"]["reviewed_at"]) <= h.api().timestamp(winner.get("recorded_at"))
                <= h.api().timestamp(h.utcnow()), "invalid first acceptance recording time")
        return reference


def resolve(checker):
    """Resolve only latest reviews, never fall back to a previous apparent pass."""
    h = history()
    index = checker.manifest.get("reviewed_acceptance", {})
    require(isinstance(index, dict), "reviewed_acceptance must be a unit reference index")
    require(not index or enabled(checker.manifest), "reviewed acceptance requires checker/unit contract 4")
    if not hasattr(checker, "_history_cache"):
        checker._history_cache = {}
    checker._reviewed_counterevidence = {}
    checker._reviewed_evidence_views = {}
    result = {"checks": {}, "units": {}, "reviews": {}}
    with _scope(checker):
        for unit, references in index.items():
            require(isinstance(references, list) and references, "review history must retain nonempty original references")
            require(len({h.sha(h.encoded(reference)) for reference in references}) == len(references), "duplicate acceptance review reference")
            for reference in references:
                prior = h.read_ref(checker.project, reference)
                require(prior.get("event") == EVENT and prior.get("version") == VERSION and prior.get("unit_id") == unit,
                        "invalid/reassigned reviewed acceptance record")
            reference, record = references[-1], prior
            decisions, accepted, original, _, prerequisite_facts = _evaluate(checker, record)
            required = set(checker.manifest["unit_plan"]["units"][unit]["required_check_ids"])
            unresolved = sorted(key for key, decision in decisions.items() if decision["outcome"] != "applicable")
            applicable = required <= set(accepted)
            original_run = original.get("unit_runs", {}).get(unit, {})
            original_authority = original.get("implementation_gate")
            metadata = {"current_applicability": "applicable" if applicable else "needs_revalidation",
                        "source_kind": record["source_kind"], "source_ref": copy.deepcopy(record["source_ref"]),
                        "original_run": {key: original_run[key] for key in ("status", "run_id", "started_at", "completed_at") if key in original_run},
                        "source_run_matches_current": h.same(original_run, checker.manifest.get("unit_runs", {}).get(unit, {})),
                        "original_authority": {key: original_authority[key] for key in ("state", "prompt_id") if key in original_authority} if isinstance(original_authority, dict) else None,
                        "original_authority_status": "recorded" if original_authority else "unknown",
                        "reviewed_at": record["review"]["reviewed_at"], "recorded_at": record["recorded_at"],
                        "review_ref": copy.deepcopy(reference),
                        "accepted_check_ids": sorted(accepted), "revalidation_check_ids": unresolved,
                        "original_prerequisites": prerequisite_facts,
                        "check_decisions": decisions,
                        "reasons": [key + ": " + reason for key in unresolved for reason in decisions[key]["reasons"]]}
            result["reviews"][unit] = metadata
            result["checks"].update(accepted)
            if applicable:
                result["units"][unit] = {**copy.deepcopy(metadata), "check_ids": sorted(required)}
    return result
