"""Validate declared construction allocations, not inferred architecture semantics."""

import json
from pathlib import PurePosixPath
import re


def _require(condition, message):
    if not condition:
        raise ValueError("construction: " + message)


def _strings(value, label):
    _require(isinstance(value, list) and value and
             all(isinstance(item, str) and item and item == item.strip() for item in value),
             label + ": nonempty ID/path list required")
    _require(len(value) == len(set(value)), label + ": duplicate entries")
    return set(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def validate_construction(checker, plan, obligations, contributions, checks):
    """Check optional v1 declarations after the existing unit/QA contract checks.

    Architecture owns canonical mechanism definitions. The plan owns allocations.
    Missing declarations remain compatible with legacy plans. No production files
    must exist during planning, and this validator does not add dependency edges.
    """
    present = {key for key in ("construction_ref", "construction") if key in plan}
    if not present:
        return
    _require(len(present) == 2, "construction_ref and construction must occur together")
    reference = plan["construction_ref"]
    _require(isinstance(reference, dict) and reference.get("path") == "docs/architecture.md",
             "mechanism definitions belong to docs/architecture.md")
    text = checker.section(reference["path"], reference.get("heading")).decode("utf-8")
    blocks = re.findall(r"```json\s*\n(.*?)\n```", text, re.S)
    _require(len(blocks) == 1, "architecture section needs one canonical JSON block")
    definition = json.loads(blocks[0], object_pairs_hook=_unique_object)
    _require(isinstance(definition, dict) and type(definition.get("version")) is int and
             definition["version"] == 1, "unsupported mechanism version")
    mechanisms = definition.get("mechanisms")
    _require(isinstance(mechanisms, dict) and mechanisms and
             all(isinstance(key, str) and key and key == key.strip() for key in mechanisms),
             "nonempty mechanism definitions required")
    allocations = plan["construction"]
    _require(isinstance(allocations, dict), "allocations must be an object")
    _require(set(allocations) <= set(mechanisms), "allocation refers to an unknown mechanism")

    for key, mechanism in mechanisms.items():
        _require(isinstance(mechanism, dict) and type(mechanism.get("required")) is bool,
                 key + ": required flag missing")
        bound = _strings(mechanism.get("obligation_ids"), key + " obligations")
        _require(bound <= obligations, key + ": unknown/nonrequired obligation")
        paths = _strings(mechanism.get("source_paths"), key + " source paths")
        for path in paths:
            checker.path(path)  # Validate confinement without requiring planned files.
            _require(PurePosixPath(path).as_posix() == path,
                     key + ": use canonical repository-relative source paths")
        if key not in allocations:
            _require(not mechanism["required"], key + ": required mechanism has no allocation")
            continue
        allocation = allocations[key]
        _require(isinstance(allocation, dict), key + ": allocation must be an object")
        owner = allocation.get("owner_unit")
        _require(isinstance(owner, str) and owner in plan["units"],
                 key + ": mechanism has no valid owner unit")
        unit = plan["units"][owner]
        _require(paths <= set(unit["implementation_paths"]),
                 key + ": mechanism source path is not owned by " + owner)
        _require(all((owner, obligation) in contributions for obligation in bound),
                 key + ": owner lacks implements link for a mechanism obligation")
        check_ids = _strings(allocation.get("check_ids"), key + " checks")
        _require(check_ids <= set(plan["acceptance"]) and check_ids <= set(checks),
                 key + ": unknown acceptance check")
        covered_obligations, covered_paths = set(), set()
        for check_id in check_ids:
            acceptance = plan["acceptance"][check_id]
            qa = checks[check_id]["acceptance"]
            _require(acceptance["owner_unit"] == owner,
                     key + ": construction check belongs to another unit: " + check_id)
            _require(qa["required"] is True and check_id in unit["required_check_ids"],
                     key + ": construction check must be required by its owner: " + check_id)
            covered_obligations.update(acceptance["obligation_ids"])
            covered_paths.update(qa["required_source_paths"])
        _require(bound <= covered_obligations,
                 key + ": construction checks omit a mechanism obligation")
        _require(paths <= covered_paths,
                 key + ": construction checks omit a mechanism source path")
