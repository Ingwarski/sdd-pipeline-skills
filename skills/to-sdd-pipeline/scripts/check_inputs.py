"""Declared per-check dependencies. No inferred omissions or execution claims."""
import copy


def require(condition, message):
    if not condition:
        raise ValueError(message)


def enabled(manifest):
    return (manifest.get("checker_contract_version"), manifest.get("unit_contract_version")) == (3, 3)


def source_sets(checker):
    verification = checker.manifest.get("verification", {})
    groups = verification.get("source_sets", {})
    if not groups:
        require("source_sets_ref" not in verification, "source sets reference has no definitions")
        return {}
    require(enabled(checker.manifest), "named source sets require checker/unit contract 3")
    require(isinstance(groups, dict), "source_sets must map names to path lists")
    reference = verification.get("source_sets_ref", {})
    require(reference.get("path") == "docs/qa-checklist.md", "source sets belong to canonical QA")
    checker.canonical_json(reference["path"], reference["heading"], groups)
    for key, paths in groups.items():
        require(isinstance(key, str) and key.strip() and isinstance(paths, list) and paths
                and all(isinstance(path, str) and path for path in paths)
                and len(paths) == len(set(paths)), "source set needs a name and unique nonempty paths")
        for path in paths:
            checker.path(path, no_links=True)
    return groups


def required_paths(checker, check, groups=None):
    acceptance = check["acceptance"]
    paths = acceptance.get("required_source_paths", [])
    require(isinstance(paths, list) and all(isinstance(path, str) and path for path in paths)
            and len(paths) == len(set(paths)), "required_source_paths must contain unique paths")
    names = acceptance.get("source_set_ids", [])
    require(isinstance(names, list) and all(isinstance(name, str) and name for name in names)
            and len(names) == len(set(names)), "source_set_ids must contain unique names")
    require(not names or enabled(checker.manifest), "named source sets require checker/unit contract 3")
    groups = source_sets(checker) if groups is None else groups
    require(set(names) <= set(groups), "unknown source set")
    resolved = set(paths)
    for name in names:
        resolved.update(groups[name])
    require(resolved, "check must declare at least one required source path")
    for path in resolved:
        checker.path(path, no_links=True)
    return resolved


def fine_grained(check):
    review = check.get("acceptance", {}).get("dependency_review")
    if review is None:
        return False
    require(isinstance(review, dict) and review.get("complete") is True
            and all(isinstance(review.get(key), str) and review[key].strip()
                    for key in ("reviewer", "rationale")), "per-check dependencies need complete owner review")
    return True


def fingerprints(checker, unit_id, inventory, check_id=None):
    """A tree selection retains all membership; uncertainty keeps the whole unit."""
    checks = {check["check_id"]: check for check in checker.manifest["verification"]["checks"]}
    allocations = checker.manifest["unit_plan"]["acceptance"]
    groups = source_sets(checker)
    whole = inventory["execution_fingerprints"]
    selections = inventory["execution_inputs"]
    result = {}
    for key, allocation in allocations.items():
        if allocation["owner_unit"] != unit_id or check_id is not None and key != check_id:
            continue
        check = checks[key]
        if not fine_grained(check):
            result[key] = copy.deepcopy(whole)
            continue
        paths = required_paths(checker, check, groups)
        # Required prerequisite paths remain explicit inputs even when declared by
        # another check. Consumers cannot reuse stale shared dependencies.
        pending, visited = list(allocation["prerequisite_checks"]), set()
        while pending:
            prior = pending.pop()
            require(prior in checks and prior in allocations, "unknown check prerequisite")
            if prior in visited:
                continue
            visited.add(prior)
            paths.update(required_paths(checker, checks[prior], groups))
            pending.extend(allocations[prior]["prerequisite_checks"])
        pending_units = list(allocation["prerequisite_units"]) + list(checker.manifest["unit_plan"]["units"][unit_id]["construction_dependencies"])
        seen_units = set()
        while pending_units:
            prior = pending_units.pop()
            if prior in seen_units:
                continue
            seen_units.add(prior)
            prior_unit = checker.manifest["unit_plan"]["units"][prior]
            paths.update(prior_unit["implementation_paths"])
            pending_units.extend(prior_unit["construction_dependencies"])
        selected = set()
        for path in paths:
            matches = {source for source, selection in selections.items()
                       if source == path or selection["mode"] == "tree"
                       and path.startswith(source.rstrip("/") + "/")}
            require(matches, "per-check inventory omits declared dependency: " + path)
            selected.update(matches)
        result[key] = {path: copy.deepcopy(whole[path]) for path in sorted(selected)}
    return result


def expected(inventory, check_id):
    return inventory.get("check_execution_fingerprints", {}).get(check_id, inventory["execution_fingerprints"])


def changed_checks(previous, current, check_ids):
    """Current applicability diagnostics; this never creates an accepted result."""
    check_ids = list(check_ids)
    if any(previous.get(field) != current.get(field) for field in ("inputs", "environment", "bindings")):
        return check_ids
    changed = {path for path in set(previous["execution_fingerprints"]) | set(current["execution_fingerprints"])
               if previous["execution_fingerprints"].get(path) != current["execution_fingerprints"].get(path)
               or previous["execution_inputs"].get(path) != current["execution_inputs"].get(path)}
    covered = {path for key in check_ids for path in expected(current, key)}
    if changed - covered:
        return check_ids  # Unknown ownership retains conservative whole-unit revalidation.
    return [key for key in check_ids if expected(previous, key) != expected(current, key)]
