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


def _json_blocks(text):
    """Read actual fenced JSON, excluding nested examples inside other fences."""
    blocks = []
    fence, language, contents = None, None, []
    for line in text.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is None:
            if marker:
                fence, language, contents = marker[1], marker[2].strip(), []
        elif marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
            if language == "json":
                blocks.append("\n".join(contents))
            fence, language, contents = None, None, []
        else:
            contents.append(line)
    return blocks


def _has_structured_declaration(checker):
    """Recognize reserved JSON declarations, not prose or localized headings."""
    path = checker.path("docs/architecture.md", no_links=True)
    before = checker.file_hash(path)
    text = path.read_text(encoding="utf-8")
    _require(checker.file_hash(path) == before, "architecture changed during validation")
    for block in _json_blocks(text):
        try:
            value = json.loads(block)
        except ValueError:
            continue
        if isinstance(value, dict) and {"version", "mechanisms"} <= set(value):
            return True
    return False


def validate_architecture_construction(checker, obligations=None):
    """Validate the owner's declaration without requiring future units/checks."""
    architecture = checker.artifacts.get("architecture", {})
    if "construction_ref" not in architecture:
        _require(not _has_structured_declaration(checker),
                 "declared architecture mechanisms require the owner's construction_ref")
        return None
    reference = architecture["construction_ref"]
    _require(isinstance(reference, dict) and reference.get("path") == "docs/architecture.md",
             "mechanism definitions belong to docs/architecture.md")
    text = checker.section(reference["path"], reference.get("heading")).decode("utf-8")
    blocks = _json_blocks(text)
    _require(len(blocks) == 1, "architecture section needs one canonical JSON block")
    try:
        definition = json.loads(blocks[0], object_pairs_hook=_unique_object)
    except ValueError as error:
        raise ValueError("construction: invalid canonical JSON: " + str(error)) from error
    _require(isinstance(definition, dict) and type(definition.get("version")) is int and
             definition["version"] == 1, "unsupported mechanism version")
    mechanisms = definition.get("mechanisms")
    _require(isinstance(mechanisms, dict) and mechanisms and
             all(isinstance(key, str) and key and key == key.strip() for key in mechanisms),
             "nonempty mechanism definitions required")
    if obligations is None:
        obligations = {item["id"] for owner in ("prd", "screen-map")
                       for item in checker.artifacts.get(owner, {}).get("traceability", {}).get("definitions", [])
                       if item.get("kind") in ("requirement", "state") and item.get("required")}
    for key, mechanism in mechanisms.items():
        _require(isinstance(mechanism, dict) and type(mechanism.get("required")) is bool,
                 key + ": required flag missing")
        bound = _strings(mechanism.get("obligation_ids"), key + " obligations")
        _require(bound <= obligations, key + ": unknown/nonrequired obligation")
        paths = _strings(mechanism.get("source_paths"), key + " source paths")
        for path in paths:
            checker.path(path)  # Planned files need not exist yet.
            _require(PurePosixPath(path).as_posix() == path,
                     key + ": use canonical repository-relative source paths")
    return mechanisms


def validate_construction(checker, plan, obligations, contributions, checks):
    """Check optional v1 declarations after the existing unit/QA contract checks.

    Architecture owns canonical mechanism definitions. The plan owns allocations.
    Only legacy sources without a declaration can omit the plan allocation. No
    production files must exist during planning; no dependency edges are added.
    """
    present = {key for key in ("construction_ref", "construction") if key in plan}
    architecture = checker.artifacts.get("architecture", {})
    mechanisms = validate_architecture_construction(checker, obligations)
    if mechanisms is None:
        _require(not present, "plan construction requires the architecture owner's construction_ref")
        return
    reference = architecture["construction_ref"]
    _require(len(present) == 2, "declared architecture requires construction_ref and construction together")
    _require(plan["construction_ref"] == reference,
             "plan construction_ref differs from the architecture owner's reference")
    allocations = plan["construction"]
    _require(isinstance(allocations, dict), "allocations must be an object")
    _require(set(allocations) <= set(mechanisms), "allocation refers to an unknown mechanism")

    for key, mechanism in mechanisms.items():
        bound, paths = set(mechanism["obligation_ids"]), set(mechanism["source_paths"])
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
