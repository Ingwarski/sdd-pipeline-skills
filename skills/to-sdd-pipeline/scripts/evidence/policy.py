"""Portable policy contains identifiers and allowances, never credentials or paths."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import uuid

from .io import EvidenceError, read_json


def load_defaults() -> dict:
    return read_json(Path(__file__).with_name("defaults.json"), 64 * 1024)


def validate_policy(policy: dict) -> dict:
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
