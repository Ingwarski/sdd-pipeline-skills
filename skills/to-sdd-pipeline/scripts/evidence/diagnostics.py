"""Owner-reviewed optional historical diagnostics; never a proof substitute.

The review preserves exact original membership. Only bulk historical validation
and prepared views may omit its members. Any active input or proof access to an
omitted member still fails, including while its original bytes remain present.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from .io import read_json, safe_relative
from .policy import validate_policy


_active = ContextVar("sdd_optional_diagnostics", default=None)
MAX_MEMBERS = 10000


def _history():
    import sdd_check
    return sdd_check.history_api()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _policy(project, manifest):
    h = _history()
    storage = manifest.get("evidence_storage", {})
    _require(isinstance(storage, dict), "optional diagnostics require declared evidence storage")
    relative = storage.get("policy_path", "forge/evidence-policy.json")
    safe_relative(relative)
    return validate_policy(read_json(h.physical(project, relative), 1024 * 1024))


class OptionalReview:
    def __init__(self, project, manifest, reference, *, document=None):
        h = _history()
        self.project = Path(project).resolve()
        self.reference = deepcopy(reference)
        self.record = deepcopy(document) if document is not None else h.read_ref(self.project, reference)
        record = self.record
        _require(isinstance(record, dict) and set(record) == {
            "event", "version", "project_id", "store_id", "review", "recorded_at", "members"}
            and record.get("event") == "optional_diagnostic_review"
            and type(record.get("version")) is int and record["version"] == 1,
            "unsupported optional diagnostic review")
        policy = _policy(self.project, manifest)
        self.identity = (policy["project_id"], policy["store_id"])
        _require((record["project_id"], record["store_id"]) == self.identity,
            "optional diagnostic review belongs to another project/store")
        review = record["review"]
        _require(isinstance(review, dict) and set(review) == {"reviewer", "reviewed_at", "rationale"}
            and all(isinstance(review.get(key), str) and review[key].strip()
                    for key in ("reviewer", "rationale")), "optional diagnostics need an owner review and rationale")
        _require(h.api().timestamp(review["reviewed_at"]) <= h.api().timestamp(record["recorded_at"])
            <= h.api().timestamp(h.utcnow()), "optional diagnostic review chronology is invalid")
        members = record["members"]
        _require(isinstance(members, list) and len(members) <= MAX_MEMBERS,
            "bounded optional diagnostic member list required")
        self.originals, self.by_record, paths = {}, {}, set()
        self.seen = set()
        for member in members:
            _require(isinstance(member, dict) and set(member) == {
                "record_ref", "logical_path", "content_hash", "rationale"}
                and isinstance(member["rationale"], str) and member["rationale"].strip(),
                "exact optional diagnostic member and rationale required")
            reference = member["record_ref"]
            original = h.read_ref(self.project, reference)
            _require(isinstance(original, dict) and original.get("event") in h.SOURCE_ARCHIVE_EVENTS
                and type(original.get("version")) is int
                and original.get("version") == (1 if original.get("event") in (
                    "sealed_check", "external_check_observations") else h.VERSION),
                "optional diagnostic must bind a native original history envelope")
            logical = safe_relative(member["logical_path"])
            root = safe_relative(original.get("snapshot_root"))
            frozen = original.get("files", {}).get(logical)
            _require(isinstance(frozen, dict) and set(frozen) == h.REF_KEYS
                and frozen["path"] == root + "/" + logical
                and frozen["content_hash"] == member["content_hash"]
                and isinstance(member["content_hash"], str)
                and re.fullmatch(r"(?:sha256:)?[a-fA-F0-9]{64}", member["content_hash"]),
                "optional diagnostic changed original member identity")
            safe_relative(frozen["path"])
            _require(frozen["path"] not in paths, "duplicate optional diagnostic member")
            paths.add(frozen["path"])
            identity = _key(original)
            self.originals[_key(reference)] = (deepcopy(reference), original)
            self.by_record.setdefault(identity, set()).add(logical)
        self.optional_paths = frozenset(paths)
        self.guarded_paths = self.optional_paths | frozenset(str(parent)
            for path in paths for parent in PurePosixPath(path).parents if str(parent) != ".")

    def members(self, record):
        """Exact reviewed membership; a changed envelope receives no exemption."""
        return frozenset(self.by_record.get(_key(record), ()))

    def audit(self):
        h = _history()
        if self.reference is not None:
            _require(h.same(h.read_ref(self.project, self.reference), self.record),
                "optional diagnostic review changed during validation")
        for reference, original in self.originals.values():
            _require(h.same(h.read_ref(self.project, reference), original),
                "optional diagnostic original changed during validation")


def load_review(project, manifest):
    """Read-only public review loader for dependency discovery."""
    policy = manifest.get("history_integrity", {})
    if not isinstance(policy, dict) or "optional_diagnostics_ref" not in policy:
        return None
    return OptionalReview(project, manifest, policy["optional_diagnostics_ref"])


def optional_members(project, manifest, record):
    selected = load_review(project, manifest)
    return selected.members(record) if selected is not None else frozenset()


@contextmanager
def scope(project, manifest):
    prior = _active.get()
    reference = manifest.get("history_integrity", {}).get("optional_diagnostics_ref") if isinstance(
        manifest.get("history_integrity", {}), dict) else None
    if prior is not None:
        _require(project is None or Path(project).resolve() == prior.project,
            "optional diagnostic scope cannot cross projects")
        # Historical manifests retain their old policy; current outer adoption
        # controls optional bulk material, without changing those manifests.
        if reference is not None:
            if reference != prior.reference:
                original = load_review(prior.project, manifest)
                _require(original is not None and all(names <= prior.by_record.get(key, set())
                    for key, names in original.by_record.items()), "conflicting optional diagnostic review scope")
        yield prior
        return
    if reference is None:
        yield None
        return
    _require(project is not None, "optional diagnostic review requires the actual project")
    selected = load_review(project, manifest)
    token = _active.set(selected)
    try:
        yield selected
    finally:
        try:
            selected.audit()
        finally:
            _active.reset(token)


def effective_files(project, record):
    selected = _active.get()
    files = record.get("files", {})
    if selected is None:
        return files
    _require(Path(project).resolve() == selected.project, "optional diagnostic projection belongs to another project")
    omitted = selected.members(record)
    selected.seen.update(record["files"][name]["path"] for name in omitted)
    return {name: frozen for name, frozen in files.items() if name not in omitted}


def guard_path(project, relative):
    selected = _active.get()
    if selected is None:
        return
    _require(Path(project).resolve() == selected.project, "optional diagnostic access belongs to another project")
    safe_relative(relative)
    _require(relative not in selected.guarded_paths,
        "active input/proof requires a member classified as optional diagnostic: " + relative)


def report():
    selected = _active.get()
    if selected is None:
        return {}
    return {"optional_diagnostics": {"review_ref": deepcopy(selected.reference),
        "reviewed_members": len(selected.optional_paths), "bulk_members_not_required": len(selected.seen),
        "status": "optional_payloads_not_audited", "acceptance_substitute": False}}


def _acceptance(report):
    """Only semantic gates, never timings or optional-payload reporting."""
    return {"result": report.get("result"), "issues": report.get("issues", []),
        "implementation_progress": report.get("implementation_progress")}


def capture_review(project, manifest, members, review, *, evidence_cache=None):
    """Capture reviewed optional members after a full withholding comparison.

    This writes only the new immutable review. The caller separately activates
    its reference through the project's authorized lifecycle adoption.
    """
    h = _history()
    policy = _policy(project, manifest)
    document = {"event": "optional_diagnostic_review", "version": 1,
        "project_id": policy["project_id"], "store_id": policy["store_id"],
        "review": deepcopy(review), "recorded_at": h.utcnow(), "members": deepcopy(members)}
    selected = OptionalReview(project, manifest, None, document=document)
    previous = load_review(project, manifest)
    if previous is not None:
        _require(previous.optional_paths <= selected.optional_paths,
            "optional diagnostic adoption cannot drop a prior retained review")
    with h.source_archive_scope(project, manifest.get("source_archive_index_ref"), evidence_cache,
                                policy_manifest=manifest):
        for member in document["members"]:
            original = h.read_ref(project, member["record_ref"])
            frozen = original["files"][member["logical_path"]]
            if previous is not None and frozen["path"] in previous.optional_paths:
                continue
            path = h.archived_source_path(project, frozen)
            _require(path.is_file() and h.api().hash_matches(frozen["content_hash"], h.sha(path.read_bytes())),
                "new optional diagnostic review requires verified original bytes")
    baseline = h.api().Checker(project, deepcopy(manifest), evidence_cache=evidence_cache).run("release", audit=True)
    # No publication is needed to compare behavior: the exact candidate review
    # is active only inside this read-only scope and required reads are denied.
    token = _active.set(selected)
    try:
        probe_manifest = deepcopy(manifest)
        probe_manifest.get("history_integrity", {}).pop("optional_diagnostics_ref", None)
        probe = h.api().Checker(project, probe_manifest, evidence_cache=evidence_cache).run("release", audit=True)
        _require(_acceptance(baseline) == _acceptance(probe),
            "optional diagnostic withholding changes acceptance or supported audit")
        selected.audit()
    finally:
        _active.reset(token)
    return h.store_record(project, "diagnostics", document)
