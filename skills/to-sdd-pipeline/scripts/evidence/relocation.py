"""Explicit storage relocation; immutable observation meaning never changes."""
from copy import deepcopy
from .io import EvidenceError
from .identity import same_reference
from .lifecycle import digest


def validate_storage_reference(original, stored):
    from .resolver import validate_reference
    validate_reference(original)
    validate_reference(stored)
    candidate = deepcopy(stored)
    candidate["locator"] = deepcopy(original["locator"])
    if not same_reference(original, candidate):
        raise EvidenceError("relocation changes original evidence content, provenance or obligations")
    for field in ("store_id", "provider"):
        if original["locator"].get(field) != stored["locator"].get(field):
            raise EvidenceError("relocation cannot change durable storage identity")
    return stored


def validate_relocation(original, relocation, previous=None):
    if (not isinstance(relocation, dict) or set(relocation) != {"version", "original_sha256", "previous_sha256", "storage_reference", "digest"}
            or type(relocation["version"]) is not int or relocation["version"] != 1
            or relocation["original_sha256"] != digest(original)
            or relocation["digest"] != digest({key: value for key, value in relocation.items() if key != "digest"})):
        raise EvidenceError("invalid storage relocation identity")
    if previous is not None and relocation["previous_sha256"] != previous["digest"]:
        raise EvidenceError("storage relocation ancestry changed")
    if previous is None and relocation["previous_sha256"] is not None:
        raise EvidenceError("initial storage relocation has unknown ancestry")
    validate_storage_reference(original, relocation["storage_reference"])
    return relocation


def create_relocation(original, stored, previous=None):
    validate_storage_reference(original, stored)
    value = {"version": 1, "original_sha256": digest(original),
        "previous_sha256": previous["digest"] if previous else None, "storage_reference": deepcopy(stored)}
    value["digest"] = digest(value)
    return value


def receipt_storage_reference(original, chain):
    if not isinstance(chain, list) or not 1 <= len(chain) <= 32:
        raise EvidenceError("bounded storage relocation chain required")
    previous = None
    for item in chain:
        previous = validate_relocation(original, item, previous)
    return previous["storage_reference"]
