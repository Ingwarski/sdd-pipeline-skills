"""Compact observation payloads with explicit file dependencies, never verdicts.

Use only for measured observation data. Authority, settlement, acceptance and
history receipts retain their own schemas. Required diagnostics remain separate
declared evidence; a stdout hash is not a substitute for their original bytes.
"""
import copy
import hashlib
import json

from evidence.io import safe_relative


SCHEMA = "sdd-observation-v1"


def snapshot_dependencies(document):
    """None means ordinary JSON; a typed payload has a closed dependency list."""
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        return None
    if not {"schema", "observations", "dependencies"} <= set(document) or set(document) - {
            "schema", "observations", "dependencies", "transport"}:
        raise ValueError("typed observation has missing or unknown fields")
    dependencies = document["dependencies"]
    if not isinstance(dependencies, list):
        raise ValueError("observation dependencies must be a list")
    seen = set()
    for reference in dependencies:
        if not isinstance(reference, dict) or set(reference) != {"path", "content_hash"}:
            raise ValueError("observation dependency must be a hash-bound file reference")
        path = safe_relative(reference["path"])
        digest = reference["content_hash"]
        if (not isinstance(digest, str) or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)):
            raise ValueError("observation dependency needs an original SHA-256")
        if path in seen:
            raise ValueError("duplicate observation dependency")
        seen.add(path)
    if "transport" in document:
        transport = document["transport"]
        if (not isinstance(transport, dict) or set(transport) != {"stdout_sha256", "stdout_bytes"}
                or type(transport["stdout_bytes"]) is not int or transport["stdout_bytes"] < 0
                or not isinstance(transport["stdout_sha256"], str)
                or len(transport["stdout_sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in transport["stdout_sha256"])):
            raise ValueError("invalid observation transport identity")
    return copy.deepcopy(dependencies)


def encode_observation(observations, *, dependencies=(), stdout=None):
    """Encode supplied observations once; do not prune, infer or pass assertions.

    Optional stdout is identified by original UTF-8 bytes without embedding a
    second copy. This helper does not write files or replace required raw logs.
    """
    record = {"schema": SCHEMA, "observations": observations,
              "dependencies": list(dependencies)}
    if stdout is not None:
        if not isinstance(stdout, (str, bytes)):
            raise ValueError("stdout must be original bytes or text")
        data = stdout.encode("utf-8") if isinstance(stdout, str) else stdout
        record["transport"] = {"stdout_sha256": hashlib.sha256(data).hexdigest(),
                               "stdout_bytes": len(data)}
    snapshot_dependencies(record)
    return (json.dumps(record, ensure_ascii=False, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")
