"""Portable policy contains identifiers and allowances, never credentials or paths."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import re
import uuid

from .io import EvidenceError, read_json


def load_defaults() -> dict:
    return read_json(Path(__file__).with_name("defaults.json"), 64 * 1024)


def _effective_policy(policy: dict) -> dict:
    if not isinstance(policy, dict) or type(policy.get("version")) is not int or policy.get("version") != 1:
        raise EvidenceError("unsupported evidence policy version; expected version 1")
    defaults = load_defaults()
    allowed = set(defaults) | {"project_id", "store_id", "provider"}
    if set(policy) - allowed:
        raise EvidenceError("unknown portable policy fields: " + ", ".join(sorted(set(policy) - allowed)))
    for key in ("project_id", "store_id"):
        try:
            value = policy[key]
            if not isinstance(value, str) or str(uuid.UUID(value)) != value:
                raise ValueError()
        except (KeyError, ValueError, AttributeError) as exc:
            raise EvidenceError(key + " must be a canonical UUID") from exc
    if policy.get("provider") not in ("local", "folder", "google-drive"):
        raise EvidenceError("provider must be local, folder, or google-drive")
    result = deepcopy(defaults)
    for key in ("project_id", "store_id", "provider"):
        result[key] = policy[key]
    for group in ("limits", "targets", "git_review", "retention"):
        values = policy.get(group, {})
        if not isinstance(values, dict) or set(values) - set(defaults[group]):
            raise EvidenceError("unknown or malformed policy group: " + group)
        result[group].update(values)
        for key, value in result[group].items():
            if group == "retention" and key == "drive_days" and value is None:
                continue
            minimum = 0 if key in ("free_space_reserve_bytes", "max_unit_retries") else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > 2**63 - 1:
                raise EvidenceError(group + "." + key + " must be an integer >= " + str(minimum))
    limits = result["limits"]
    for scope in ("run", "unit", "project_generation", "retained"):
        if limits[scope + "_warning_bytes"] > limits[scope + "_stop_bytes"]:
            raise EvidenceError(scope + " warning exceeds stop limit")
    if limits["cache_stop_bytes"] > limits["local_stop_bytes"]:
        raise EvidenceError("cache allowance exceeds combined local allowance")
    if limits["archive_pack_target_bytes"] > limits["archive_pack_stop_bytes"]:
        raise EvidenceError("archive pack target exceeds maximum")
    return result


LINEAGE_FIELD = "policy_lineage"
MAX_POLICY_LINEAGE_STEPS = 16
MAX_POLICY_BYTES = 1024 * 1024


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _setup_bytes(value):
    # Exact existing evidence_setup._write representation, including its newline.
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _bounded(value):
    try:
        _canonical(value)  # Reject NaN/Infinity and non-JSON ancestry before hashing.
        if len(_setup_bytes(value)) > MAX_POLICY_BYTES:
            raise EvidenceError("portable policy lineage exceeds 1 MiB")
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        raise EvidenceError("portable policy lineage is not bounded JSON") from error


def _raw_policy(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_POLICY_BYTES:
        raise EvidenceError("original portable policy must be at most 1 MiB of bytes")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError("duplicate portable policy field")
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise EvidenceError("invalid original portable policy JSON") from error


def _limit_changes(before, after):
    if {key: value for key, value in before.items() if key != "limits"} != {key: value for key, value in after.items() if key != "limits"}:
        raise EvidenceError("policy lineage permits only limits changes; identities/provider/retention must remain unchanged")
    return {key: {"from": before["limits"][key], "to": after["limits"][key]}
            for key in sorted(before["limits"]) if before["limits"][key] != after["limits"][key]}


def _policy_chain(policy):
    if not isinstance(policy, dict):
        raise EvidenceError("unsupported evidence policy")
    effective = _effective_policy({key: value for key, value in policy.items() if key != LINEAGE_FIELD})
    if LINEAGE_FIELD not in policy:
        return effective, [effective]
    _bounded(policy)
    lineage = policy[LINEAGE_FIELD]
    if (not isinstance(lineage, dict) or set(lineage) != {"version", "base", "steps"}
            or type(lineage.get("version")) is not int or lineage["version"] != 1
            or not isinstance(lineage.get("steps"), list) or not 1 <= len(lineage["steps"]) <= MAX_POLICY_LINEAGE_STEPS):
        raise EvidenceError("invalid bounded portable policy lineage")
    base = lineage["base"]
    if not isinstance(base, dict) or set(base) != {"raw_utf8", "raw_sha256", "policy_sha256"} or not isinstance(base.get("raw_utf8"), str):
        raise EvidenceError("invalid original portable policy snapshot")
    try:
        original_raw = base["raw_utf8"].encode("utf-8")
    except UnicodeError as error:
        raise EvidenceError("original policy snapshot is not UTF-8") from error
    original = _raw_policy(original_raw)
    if isinstance(original, dict) and LINEAGE_FIELD in original:
        raise EvidenceError("recursive portable policy lineage is forbidden")
    previous_effective = _effective_policy(original)
    if base["raw_sha256"] != hashlib.sha256(original_raw).hexdigest() or base["policy_sha256"] != _digest(previous_effective):
        raise EvidenceError("original policy raw/normalized identity changed")
    previous = previous_effective
    policies, steps, previous_digest = [deepcopy(previous)], [], None
    for step in lineage["steps"]:
        fields = {"from_policy_sha256", "from_raw_sha256", "previous_sha256", "policy", "changes", "digest"}
        if not isinstance(step, dict) or set(step) != fields:
            raise EvidenceError("invalid policy lineage transition fields")
        if (step["from_policy_sha256"] != _digest(previous)
                or step["from_raw_sha256"] != hashlib.sha256(original_raw if not steps else _setup_bytes(previous)).hexdigest()
                or step["previous_sha256"] != previous_digest
                or step["digest"] != _digest({key: value for key, value in step.items() if key != "digest"})):
            raise EvidenceError("policy lineage chain or raw/normalized identity changed")
        following = _effective_policy(step["policy"])
        if following != step["policy"]:
            raise EvidenceError("policy lineage snapshots must be fully normalized")
        changes = _limit_changes(previous_effective, following)
        if not changes or _canonical(step["changes"]) != _canonical(changes):
            raise EvidenceError("policy lineage exact limits diff changed or is empty")
        steps.append(deepcopy(step))
        previous = {**following, LINEAGE_FIELD: {"version": 1, "base": deepcopy(base), "steps": deepcopy(steps)}}
        policies.append(deepcopy(previous))
        previous_effective, previous_digest = following, step["digest"]
    if effective != previous_effective:
        raise EvidenceError("policy lineage does not reach the current policy")
    # Preserve the validated optional field exactly; never add it to v1 defaults.
    result = {**effective, LINEAGE_FIELD: deepcopy(lineage)}
    return result, policies


def validate_policy(policy: dict) -> dict:
    """Validate all ancestry before exposing a current or historical policy."""
    return _policy_chain(policy)[0]


def resolve_historical_policy(currentpolicy: dict, canonicalSHA: str) -> dict:
    """Resolve only exact full normalized policies on a complete current chain."""
    if not isinstance(canonicalSHA, str) or not re.fullmatch(r"[a-f0-9]{64}", canonicalSHA):
        raise EvidenceError("invalid historical policy digest")
    _, policies = _policy_chain(currentpolicy)
    for policy in policies:
        if _digest(policy) == canonicalSHA:
            return deepcopy(policy)
    raise EvidenceError("historical policy is not on the current validated lineage")


def append_policy_transition(previous_raw: bytes, candidate_effective: dict) -> dict:
    """Explicit supported setup appends one deterministic limits-only transition."""
    previous, _ = _policy_chain(_raw_policy(previous_raw))
    if not isinstance(candidate_effective, dict):
        raise EvidenceError("candidate portable policy must be an object")
    inherited = candidate_effective.get(LINEAGE_FIELD)
    if LINEAGE_FIELD in candidate_effective and (LINEAGE_FIELD not in previous or inherited != previous[LINEAGE_FIELD]):
        raise EvidenceError("candidate policy cannot replace its inherited lineage")
    following = _effective_policy({key: value for key, value in candidate_effective.items() if key != LINEAGE_FIELD})
    before = {key: value for key, value in previous.items() if key != LINEAGE_FIELD}
    changes = _limit_changes(before, following)
    if LINEAGE_FIELD in previous and previous_raw != _setup_bytes(previous):
        raise EvidenceError("lineage-bearing original policy bytes differ from supported setup serialization")
    if not changes:
        return deepcopy(previous)
    if LINEAGE_FIELD in previous:
        lineage = deepcopy(previous[LINEAGE_FIELD])
    else:
        lineage = {"version": 1, "base": {"raw_utf8": previous_raw.decode("utf-8"),
            "raw_sha256": hashlib.sha256(previous_raw).hexdigest(), "policy_sha256": _digest(previous)}, "steps": []}
    if len(lineage["steps"]) >= MAX_POLICY_LINEAGE_STEPS:
        raise EvidenceError("portable policy lineage exceeds 16 transitions")
    step = {"from_policy_sha256": _digest(previous), "from_raw_sha256": hashlib.sha256(previous_raw).hexdigest(),
            "previous_sha256": lineage["steps"][-1]["digest"] if lineage["steps"] else None,
            "policy": following, "changes": changes}
    step["digest"] = _digest(step)
    lineage["steps"].append(step)
    result = {**following, LINEAGE_FIELD: lineage}
    _bounded(result)
    return validate_policy(result)
