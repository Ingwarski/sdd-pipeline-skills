"""Declarative adoption; no provider-specific recovery code or payload uploads."""
from copy import deepcopy
import re

from .io import EvidenceError, safe_relative
from .resolver import validate_reference

PRESERVED = ("restoration_metadata", "attachment_metadata", "dependencies", "historical_verified_at")


def _integer(value, label):
    if type(value) is not int or value < 0:
        raise EvidenceError(label + " must be a nonnegative integer")
    return value


def _digest(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise EvidenceError(label + " requires a lowercase SHA-256")
    return value


def _pack(record):
    if not isinstance(record, dict):
        raise EvidenceError("imported archive must be an object")
    digest = _digest(record.get("sha256"), "archive identity")
    size = _integer(record.get("size"), "archive size")
    locator = record.get("locator") or {"object_id": record.get("object_id"), "key": record.get("key"), "size": size}
    if not isinstance(locator, dict) or not isinstance(locator.get("object_id"), str) or not locator["object_id"] or any(ord(c) < 32 for c in locator["object_id"]):
        raise EvidenceError("imported archive requires a stable object identity")
    safe_relative(locator.get("key"))
    if "size" in locator and _integer(locator["size"], "locator size") != size:
        raise EvidenceError("archive and locator sizes differ")
    members = record.get("members")
    if not isinstance(members, list):
        raise EvidenceError("imported archive members must be a list")
    names, total = set(), 0
    for member in members:
        if not isinstance(member, dict):
            raise EvidenceError("imported archive member must be an object")
        name = safe_relative(member.get("member"))
        if name in names:
            raise EvidenceError("duplicate imported archive member")
        names.add(name)
        _digest(member.get("sha256"), "member identity")
        total += _integer(member.get("size"), "member size")
    if "original_bytes" in record and _integer(record["original_bytes"], "archive original bytes") != total:
        raise EvidenceError("archive original byte total differs from members")
    return {**deepcopy(record), "sha256": digest, "size": size, "locator": deepcopy(locator),
            "members": deepcopy(members), "original_bytes": total}


def _same_original(reference):
    """Storage adoption flags may change; original evidence identities never do."""
    value = deepcopy(reference)
    value.setdefault("original_path", None)
    for key in ("imported", "migration_policy_established"):
        value["retention"].pop(key, None)
    locator = value["locator"]
    locator.pop("store_id", None)
    locator.pop("provider", None)
    if locator.get("segments") is not None:
        locator.pop("object_id", None)  # Each split segment already carries its identity.
    else:
        locator.setdefault("offset", 0)
        locator.setdefault("length", value["size"])
        locator.setdefault("sha256", value["sha256"])
    value["dependencies"] = [(dep.get("artifact_id"), dep.get("sha256"), dep.get("size")) for dep in value.get("dependencies", [])]
    return value


def _normalize_dependencies(refs):
    indexed = {ref["artifact_id"]: ref for ref in refs}
    active, complete = set(), set()
    def validate_external(ref, depth):
        if depth > 32:
            raise EvidenceError("imported dependency closure exceeds validation bounds")
        validate_reference(ref)
        target = indexed.get(ref["artifact_id"])
        if target is not None and _same_original(ref) != _same_original(target):
            raise EvidenceError("imported dependency conflicts with original evidence identity")
        for dependency in ref.get("dependencies", []):
            validate_external(dependency, depth + 1)
    def visit(identity, depth=0):
        if depth > 32 or identity in active:
            raise EvidenceError("cyclic or excessive imported dependency closure")
        if identity in complete:
            return indexed[identity]
        active.add(identity)
        ref = indexed[identity]
        resolved = []
        for dependency in ref.get("dependencies", []):
            validate_external(dependency, depth + 1)
            target = indexed.get(dependency["artifact_id"])
            if target is None:
                resolved.append(deepcopy(dependency))
                continue
            if _same_original(dependency) != _same_original(target):
                raise EvidenceError("imported dependency conflicts with original evidence identity")
            resolved.append(deepcopy(visit(target["artifact_id"], depth + 1)))
        if "dependencies" in ref:
            ref["dependencies"] = resolved
        active.remove(identity)
        complete.add(identity)
        return ref
    for identity in indexed:
        visit(identity)

def normalize(mapping, *, store_id, provider):
    """Accept neutral refs/packs or an object table with logical file associations."""
    if not isinstance(mapping, dict) or type(mapping.get("version")) is not int or mapping["version"] != 1:
        raise EvidenceError("unsupported adoption mapping; expected version 1")
    packs, refs = {}, []
    objects = mapping.get("objects", {})
    neutral = mapping.get("packs", {})
    if "refs" in mapping and "files" in mapping:
        raise EvidenceError("adoption must choose refs or files, not competing logical indexes")
    records = mapping.get("refs", mapping.get("files", []))
    if not isinstance(objects, dict) or not isinstance(neutral, dict) or not isinstance(records, list):
        raise EvidenceError("adoption requires object/pack tables and a logical record list")
    if (objects or neutral) and not records:
        raise EvidenceError("incomplete adoption mapping: add a logical file association or an opaque attachment for every archive pack")
    def register(pack):
        previous = packs.get(pack["sha256"])
        if previous is not None and previous != pack:
            raise EvidenceError("conflicting imported archive identity")
        packs[pack["sha256"]] = pack
    for obj in objects.values():
        register(_pack(obj))
    for pack in neutral.values():
        register(_pack(pack))
    for record in records:
        if not isinstance(record, dict):
            raise EvidenceError("imported logical record must be an object")
        if "locator" in record:
            ref = deepcopy(record)
        else:
            parts = record.get("parts")
            if not isinstance(parts, list) or not parts:
                raise EvidenceError("imported file requires nonempty original archive parts")
            segments = []
            for part in parts:
                if not isinstance(part, dict) or not isinstance(part.get("object"), str) or part["object"] not in objects:
                    raise EvidenceError("imported part refers to an unknown archive object")
                obj = objects[part["object"]]
                pack = packs[obj["sha256"]]
                member = next((m for m in pack["members"] if m["member"] == part.get("member")), None)
                if member is None:
                    raise EvidenceError("imported member absent from original catalog")
                safe_relative(part["member"])
                segments.append({"object_id": pack["locator"]["object_id"], "key": pack["locator"]["key"],
                    "pack_sha256": pack["sha256"], "pack_size": pack["size"], "member": part["member"],
                    "offset": part.get("offset", 0), "length": part.get("length", member["size"]), "sha256": member["sha256"]})
            locator = segments[0] if len(segments) == 1 else {"object_id": segments[0]["object_id"], "segments": segments}
            ref = {"version": 1, "artifact_id": record.get("artifact_id"), "sha256": record.get("sha256"), "size": record.get("size"),
                   "kind": record.get("kind", "recovery-attachment"), "schema": record.get("schema", "archive-attachment-v1"),
                   "provenance": deepcopy(record.get("provenance")), "bindings": deepcopy(record.get("bindings", {})),
                   "original_path": record.get("original_path"), "locator": locator,
                   "retention": deepcopy(record.get("retention"))}
            for field in PRESERVED:
                if field in record:
                    ref[field] = deepcopy(record[field])
            if "verified_at" in record:
                if "historical_verified_at" in ref and ref["historical_verified_at"] != record["verified_at"]:
                    raise EvidenceError("conflicting original verification timestamps")
                ref["historical_verified_at"] = record["verified_at"]
        if not isinstance(ref.get("locator"), dict) or not isinstance(ref.get("retention"), dict):
            raise EvidenceError("imported reference requires locator and original retention")
        for field in ("restoration_metadata", "attachment_metadata"):
            if field in ref and not isinstance(ref[field], dict):
                raise EvidenceError(field + " must be opaque descriptive metadata")
        ref["locator"].update(store_id=store_id, provider=provider)
        ref["retention"]["imported"] = True
        ref["retention"]["migration_policy_established"] = False
        validate_reference(ref)
        refs.append(ref)
    if len({r["artifact_id"] for r in refs}) != len(refs):
        raise EvidenceError("duplicate logical imported artifact identity")
    _normalize_dependencies(refs)
    associated_packs = set()
    for ref in refs:
        for segment in ref["locator"].get("segments") or [ref["locator"]]:
            associated_packs.add(segment["pack_sha256"])
            pack = packs.get(segment["pack_sha256"])
            if pack is None or (pack["size"], pack["locator"]["object_id"]) != (segment["pack_size"], segment["object_id"]):
                raise EvidenceError("imported reference lacks original archive closure")
    if set(packs) - associated_packs:
        raise EvidenceError("incomplete adoption mapping: add a logical file association or an opaque attachment for every archive pack")
    return refs, packs
