"""Optional observation labels/corrections; structural agreement is not UI proof."""
from datetime import datetime


LABELS = ("action_name", "observed_state_id", "fixture_id", "observed_result")


def validate_observation_receipt(checker, receipt):
    """Validate declared structured labels without upgrading legacy evidence.

    Detailed observations stay in existing original_observation_refs. A correction
    is a separate receipt, not a replacement execution or rewritten original.
    """
    def require(condition, message):
        if not condition:
            raise ValueError("observation receipt: " + message)

    def stamp(value):
        require(isinstance(value, str), "timezone-aware observation time required")
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(value.tzinfo is not None and value.utcoffset() is not None, "timezone-aware observation time required")
        return value

    def read(ref):
        require(checker.evidence_snapshot(ref, "design", "observation_receipt"), "unreadable or changed original observation reference")
        return checker.evidence_json(ref)

    def select(document, pointer):
        require(isinstance(pointer, str) and pointer.startswith("/") and len(pointer) <= 1024, "bounded JSON pointer required")
        tokens = pointer[1:].split("/")
        require(len(tokens) <= 32, "JSON pointer is too deep")
        for token in tokens:
            # JSON Pointer escapes only '~0' and '~1'; do not interpret paths/code.
            for index, char in enumerate(token):
                if char == "~":
                    require(index + 1 < len(token) and token[index + 1] in "01", "invalid JSON pointer escape")
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(document, list):
                require(token.isascii() and token.isdecimal() and (token == "0" or not token.startswith("0")), "invalid observation array index")
                index = int(token)
                require(index < len(document), "observation array index out of range")
                document = document[index]
            else:
                require(isinstance(document, dict) and token in document, "observation pointer does not resolve")
                document = document[token]
        require(isinstance(document, dict), "observation pointer must select an object")
        return document

    require(isinstance(receipt, dict), "receipt must be an object")
    states = {
        item.get("id")
        for artifact in getattr(checker, "artifacts", {}).values()
        for item in artifact.get("traceability", {}).get("definitions", [])
        if item.get("kind") == "state"
    }

    def labels(row, sources):
        require(isinstance(row, dict), "observation entry must be an object")
        if not any(key in row for key in LABELS + ("observation_source_index", "observation_pointer")):
            return
        require(all(isinstance(row.get(key), str) and row[key].strip() for key in LABELS), "structured labels require action, observed state, fixture and result")
        require(not states or row["observed_state_id"] in states, "observed state ID is not canonical")
        stamp(row.get("observed_at"))
        linked = "observation_source_index" in row or "observation_pointer" in row
        if not linked:
            return
        index = row.get("observation_source_index")
        require(isinstance(sources, list) and type(index) is int and 0 <= index < len(sources), "original observation source index does not resolve")
        observed = select(read(sources[index]), row.get("observation_pointer"))
        require(observed.get("observed_at") == row["observed_at"], "original observation time was changed")
        aliases = {
            "observed_state_id": ("observed_state_id", "state_id"),
            "fixture_id": ("fixture_id", "fixture"),
            "observed_result": ("observed_result", "result"),
        }
        for key, names in aliases.items():
            for name in names:
                if name in observed:
                    require(row[key] == observed[name], key + " differs from the structured original observation")
        # expected_state, action tags and DOM/prose are not observed-state proof.

    if receipt.get("event") == "observation_metadata_correction":
        require(type(receipt.get("version")) is int and receipt["version"] == 1, "version 1 metadata correction required")
        require(receipt.get("new_execution") is False, "metadata correction must not claim new execution")
        require(all(isinstance(receipt.get(key), str) and receipt[key].strip() for key in ("reviewer", "reason")), "correction reviewer and reason required")
        original = read(receipt.get("original_receipt"))
        require(isinstance(original, dict) and original.get("event") != "observation_metadata_correction", "correction must reference the original receipt, not another correction")
        for key in ("candidate_id", "prototype_tree_hash", "visual_target_hash", "preview_url", "browser_kind", "result"):
            if key in receipt:
                require(receipt[key] == original.get(key), "metadata correction cannot change original " + key)
        require(receipt.get("observed_at") == original.get("observed_at"), "original receipt observation time was changed")
        corrected = stamp(receipt.get("corrected_at"))
        require(stamp(receipt.get("observed_at")) <= corrected <= datetime.now().astimezone(), "invalid correction time")
        rows = original.get("interactions_checked")
        corrections = receipt.get("corrections")
        require(isinstance(rows, list) and isinstance(corrections, list) and corrections, "original interactions and nonempty corrections required")
        seen = set()
        allowed = set(LABELS) | {"interaction_index", "observed_at", "observation_source_index", "observation_pointer"}
        for row in corrections:
            require(isinstance(row, dict) and set(row) <= allowed, "correction may change observation labels only")
            index = row.get("interaction_index")
            require(type(index) is int and 0 <= index < len(rows) and index not in seen, "correction interaction index is invalid or duplicated")
            seen.add(index)
            require(isinstance(rows[index], dict) and row.get("observed_at") == rows[index].get("observed_at"), "original interaction time was changed")
            require(stamp(row.get("observed_at")) <= corrected, "correction precedes original interaction")
            require(all(key in row for key in LABELS), "correction needs separate action/state/fixture/result labels")
            labels(row, original.get("original_observation_refs"))
        return

    rows = receipt.get("interactions_checked", [])
    if not isinstance(rows, list):
        return  # Undeclared legacy shapes make no new structured-label claim.
    for row in rows:
        if isinstance(row, dict):
            labels(row, receipt.get("original_observation_refs"))
