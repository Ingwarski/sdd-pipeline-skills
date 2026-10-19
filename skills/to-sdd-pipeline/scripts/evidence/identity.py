"""Version 1 reference compatibility for an obsolete administrative flag only."""
import json
from copy import deepcopy

from .io import EvidenceError


def reference_identity(reference):
    """Retain typed immutable meaning, excluding legacy imported-policy acknowledgement.

    The original flag was administrative state mistakenly embedded in references.
    Its Boolean value never establishes pruning authority; catalog policy records do.
    """
    nodes, references = 0, 0
    def normalize(value, depth=0, reference_position=False):
        nonlocal nodes, references
        nodes += 1
        if depth > 64 or nodes > 1000000:
            raise EvidenceError("reference identity exceeds validation bounds")
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise EvidenceError("reference identity requires JSON object keys")
            ref = (reference_position and type(value.get("version")) is int and value["version"] == 1 and
                   "artifact_id" in value and "sha256" in value and "locator" in value and "retention" in value)
            omit = False
            if ref:
                references += 1
                if references > 10000:
                    raise EvidenceError("reference identity closure exceeds validation bounds")
                retention = value["retention"]
                if not isinstance(retention, dict):
                    raise EvidenceError("reference retention must be an object")
                for flag in ("imported", "migration_policy_established"):
                    if flag in retention and type(retention[flag]) is not bool:
                        raise EvidenceError("unsupported imported retention flag: " + flag)
                omit = retention.get("imported") is True
            result = {}
            for key, child in value.items():
                if key == "retention" and omit:
                    child = {field: item for field, item in child.items() if field != "migration_policy_established"}
                if key == "dependencies" and ref:
                    if not isinstance(child, list):
                        raise EvidenceError("reference dependencies must be a list")
                    result[key] = [normalize(item, depth + 2, True) for item in child]
                else:
                    result[key] = normalize(child, depth + 1)
            return result
        if isinstance(value, list):
            return [normalize(child, depth + 1) for child in value]
        if value is not None and type(value) not in (str, int, float, bool):
            raise EvidenceError("reference identity requires JSON data")
        return value
    try:
        return json.dumps(normalize(reference, reference_position=True), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        if isinstance(error, EvidenceError):
            raise
        raise EvidenceError("invalid reference identity") from error


def same_reference(left, right):
    return reference_identity(left) == reference_identity(right)


def same_imported_original(original, adopted):
    """Compare a preserved pre-adoption reference with its registered imported form.

    Only storage selection and administrative import flags may differ. Content,
    object IDs, provenance, bindings, retention age and dependencies remain exact.
    Callers must separately bind the exact original alias to a verified catalog.
    """
    from .resolver import validate_reference
    if not isinstance(adopted, dict) or adopted.get("retention", {}).get("imported") is not True:
        return False
    count = 0
    def normalize(ref, depth=0):
        nonlocal count
        count += 1
        if depth > 32 or count > 10000:
            raise EvidenceError("imported reference identity exceeds validation bounds")
        validate_reference(ref)
        reference_identity(ref)  # Reject invalid flag types and non-JSON values.
        value = deepcopy(ref)
        value.setdefault("original_path", None)
        for key in ("imported", "migration_policy_established"):
            value["retention"].pop(key, None)
        locator = value["locator"]
        locator.pop("store_id", None)
        locator.pop("provider", None)
        if locator.get("segments") is not None:
            locator.pop("object_id", None)
        else:
            locator.setdefault("offset", 0)
            locator.setdefault("length", value["size"])
            locator.setdefault("sha256", value["sha256"])
        if "dependencies" in value:
            value["dependencies"] = [normalize(child, depth + 1) for child in value["dependencies"]]
        return value
    return reference_identity(normalize(original)) == reference_identity(normalize(adopted))
