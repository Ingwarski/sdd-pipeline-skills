"""Explicit, invocation-local deferral of unusable legacy payload integrity.

This module never validates a historical acceptance result or caches a verdict.
The caller still reads and verifies the archive and original manifest metadata.
All current evidence, contexts, attempts and completions retain their validators.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import re

from evidence.io import safe_relative


_mode = ContextVar("sdd_legacy_payload_integrity", default=None)
_state = ContextVar("sdd_legacy_payload_integrity_report", default=None)
_HASH = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


def policy_mode(manifest):
    """An explicit current policy; older records retain every-gate integrity."""
    if "history_integrity" not in manifest:
        return "every_gate"
    versions = tuple(manifest.get(key) for key in ("checker_contract_version", "unit_contract_version"))
    if any(type(value) is not int for value in versions) or versions not in ((3, 3), (4, 4)):
        raise ValueError("history integrity policy requires checker and unit contracts 3 or 4")
    policy = manifest["history_integrity"]
    if (not isinstance(policy, dict) or set(policy) != {"legacy_payloads"}
            or policy["legacy_payloads"] not in ("every_gate", "audit_only")):
        raise ValueError("history_integrity requires legacy_payloads: every_gate or audit_only")
    return policy["legacy_payloads"]


def review_source_requires_full(source_kind):
    """Reviewed proof does not broaden the existing legacy-only deferral policy."""
    return source_kind != "legacy_archive" or _mode.get() != "audit_only"


class IntegrityScope:
    def __init__(self, selected, effective, *, root, state):
        self.selected = selected
        self.effective = effective
        self.is_root = root
        self.state = state

    def report(self):
        deferred = self.state["deferred"]
        return {
            "legacy_payloads": self.selected,
            "effective_legacy_payloads": self.effective,
            "deferred_archive_count": len(deferred),
            "deferred_snapshot_files": sum(deferred.values()),
            "legacy_payload_status": "not_audited_this_gate" if deferred else "no_payload_checks_deferred",
            "last_full_payload_verification": None,
            "scope": "Only unusable legacy payload bytes may be deferred; metadata and current acceptance dependencies remain verified. A null last verification time means unknown.",
        }


@contextmanager
def history_integrity_scope(manifest, *, force_full=False):
    """Share the selected policy with nested history gates for this call only.

    Full audits and release/migration callers use force_full. A nested operation
    can strengthen its parent scope, never weaken it. Policy is validated even
    when the effective scope has already been forced to full integrity.
    """
    selected = policy_mode(manifest)
    inherited = _mode.get()
    root = inherited is None
    effective = "every_gate" if force_full else inherited or selected
    state = {"deferred": {}, "selected": selected} if root else _state.get()
    mode_token = _mode.set(effective)
    state_token = _state.set(state)
    try:
        yield IntegrityScope(selected if root else state.get("selected", selected),
                             effective, root=root, state=state)
    finally:
        _state.reset(state_token)
        _mode.reset(mode_token)


def _reference(reference):
    if not isinstance(reference, dict) or set(reference) != {"path", "content_hash"}:
        raise ValueError("hash-bound legacy reference required")
    safe_relative(reference["path"])
    if not isinstance(reference["content_hash"], str) or not _HASH.fullmatch(reference["content_hash"]):
        raise ValueError("invalid legacy content hash")


def defer_legacy_payload(reference, record):
    """Return True only for an explicitly deferred unusable legacy archive.

    Metadata was independently read through read_ref before this call. Validate
    every declared logical member without following, statting or opening payload
    paths. No file omission, evidence expiry, deletion or acceptance is authorised.
    """
    if _mode.get() != "audit_only":
        return False
    _reference(reference)
    if (not isinstance(record, dict) or record.get("event") != "legacy_execution_archive"
            or type(record.get("version")) is not int or record["version"] != 2
            or record.get("acceptance") != "unverified_not_reusable"):
        raise ValueError("only unusable legacy archive payloads may be deferred")
    _reference(record.get("manifest_ref"))
    root = safe_relative(record.get("snapshot_root"))
    files = record.get("files")
    if not isinstance(files, dict):
        raise ValueError("legacy snapshot membership must be an object")
    for logical, member in files.items():
        safe_relative(logical)
        _reference(member)
        if member["path"] != root + "/" + logical:
            raise ValueError("legacy snapshot path must preserve logical identity")
    state = _state.get()
    if state is None:
        raise ValueError("legacy payload deferral requires an active gate scope")
    key = (reference["path"], reference["content_hash"])
    if key in state["deferred"] and state["deferred"][key] != len(files):
        raise ValueError("legacy membership changed during gate")
    state["deferred"][key] = len(files)
    return True
