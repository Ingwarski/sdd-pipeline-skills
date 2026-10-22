"""Explicit isolation of preserved producer gaps, never accounting recovery.

The host attests coverage of helpers outside the native launch journal. Hashing
that assertion binds its bytes; it does not authenticate the reviewer or turn
limited external process observations into exact native process identities.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

from .io import EvidenceError, hash_file, safe_relative
from .policy import resolve_historical_policy


UNKNOWN_REASON = "managed output inventory is unknown; observed charges are lower bounds and its reservation remains held"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _text(value):
    return isinstance(value, str) and 0 < len(value) <= 4096 and not any(ord(c) < 32 for c in value)


def _amount(value):
    return type(value) is int and 0 <= value <= 2**63 - 1


def _inode(value):
    return type(value) is int and 0 <= value <= 2**64 - 1


def _time(value):
    try:
        return isinstance(value, str) and datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def validate_proof(value, attempt_id, original_record_sha256, *, read_files=False):
    required = {"version", "kind", "attempt_id", "original_record_sha256", "verifier", "observed_at", "external_disposition"}
    if (not isinstance(value, dict) or set(value) != required or type(value["version"]) is not int
            or value["version"] != 1 or value["kind"] != "producer-disposition"
            or value["attempt_id"] != attempt_id or value["original_record_sha256"] != original_record_sha256
            or not _text(value["verifier"]) or not _time(value["observed_at"])):
        raise EvidenceError("invalid quarantine disposition proof/binding")
    external = value["external_disposition"]
    if (not isinstance(external, dict) or set(external) != {"coverage", "journal", "proof", "limitations"}
            or external["coverage"] != "all-unregistered-helpers-and-resources" or not _text(external["limitations"])):
        raise EvidenceError("quarantine requires explicit external helper/resource disposition coverage and limitations")
    for key in ("journal", "proof"):
        ref = external[key]
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"} or not _text(ref["path"])
                or not Path(ref["path"]).is_absolute() or ".." in Path(ref["path"]).parts or not _hash(ref["sha256"])):
            raise EvidenceError("invalid quarantine external disposition reference")
        if read_files:
            if Path(ref["path"]).lstat().st_size > 1024 * 1024:
                raise EvidenceError("quarantine external disposition exceeds metadata read bound")
            if hash_file(Path(ref["path"]))[0] != ref["sha256"]:
                raise EvidenceError("quarantine disposition reference bytes changed")
    return value


def validate_quarantine_descriptor(value, policy=None):
    """Validate portable immutable fields without opening paths or a ledger."""
    fields = {"version", "kind", "project_id", "store_id", "ledger_id", "policy_sha256", "attempt_id",
              "run_id", "unit_id", "ordinal", "reservation_id", "output_id", "intent_id", "original_record_sha256",
              "uncertain", "reservation", "run", "disposition", "history_complete", "proof", "inventory", "inventory_sha256",
              "output_identity", "quarantined_at", "digest"}
    if (not isinstance(value, dict) or set(value) != fields or type(value["version"]) is not int or value["version"] != 1
            or value["kind"] != "quarantined-producer-gap" or value["disposition"] != "quarantined-unresolved"
            or value["history_complete"] is not False or not _amount(value["ordinal"]) or not _time(value["quarantined_at"])):
        raise EvidenceError("invalid immutable quarantine descriptor")
    for key in ("project_id", "store_id", "ledger_id", "attempt_id", "run_id", "unit_id", "reservation_id", "output_id"):
        if not _text(value[key]):
            raise EvidenceError("invalid quarantine identity: " + key)
    if value["intent_id"] is not None and not _text(value["intent_id"]):
        raise EvidenceError("invalid quarantine intent identity")
    for key in ("policy_sha256", "original_record_sha256", "inventory_sha256", "digest"):
        if not _hash(value[key]):
            raise EvidenceError("invalid quarantine hash: " + key)
    if digest({key: item for key, item in value.items() if key != "digest"}) != value["digest"]:
        raise EvidenceError("immutable quarantine descriptor digest changed")
    if policy is not None:
        if value["project_id"] != policy["project_id"] or value["store_id"] != policy["store_id"]:
            raise EvidenceError("quarantine project/store/policy binding changed")
        resolve_historical_policy(policy, value["policy_sha256"])
    uncertain = value["uncertain"]
    if (not isinstance(uncertain, dict) or set(uncertain) != {"reservation_id", "gross_bytes", "logical_files"}
            or uncertain["reservation_id"] != value["reservation_id"]
            or not _amount(uncertain["gross_bytes"]) or not _amount(uncertain["logical_files"])):
        raise EvidenceError("invalid quarantine uncertain floor")
    reservation = value["reservation"]
    numbers = {"bytes", "files", "local_bytes", "metadata_bytes", "metadata_files", "retained_bytes", "retained_objects"}
    if (not isinstance(reservation, dict) or set(reservation) != numbers | {"id", "run_id", "state", "created"}
            or reservation["id"] != value["reservation_id"] or reservation["run_id"] != value["run_id"]
            or reservation["state"] != "pending" or any(not _amount(reservation[k]) for k in numbers)
            or type(reservation["created"]) not in (int, float) or not math.isfinite(reservation["created"])):
        raise EvidenceError("invalid quarantine retained reservation")
    run = value["run"]
    if (not isinstance(run, dict) or set(run) != {"id", "unit_id", "ordinal", "gross_bytes", "gross_files", "migration", "status", "created"}
            or run["id"] != value["run_id"] or run["unit_id"] != value["unit_id"] or run["ordinal"] != value["ordinal"]
            or type(run["migration"]) is not int or run["migration"] != 0 or run["status"] != "incomplete"
            or any(not _amount(run[k]) for k in ("ordinal", "gross_bytes", "gross_files"))
            or run["gross_bytes"] < uncertain["gross_bytes"] or run["gross_files"] < uncertain["logical_files"]
            or type(run["created"]) not in (int, float) or not math.isfinite(run["created"])):
        raise EvidenceError("invalid quarantine original run")
    identity = value["output_identity"]
    if not isinstance(identity, list) or len(identity) != 2 or any(not _inode(i) for i in identity):
        raise EvidenceError("invalid quarantine output identity")
    inventory = value["inventory"]
    if not isinstance(inventory, list) or digest(inventory) != value["inventory_sha256"]:
        raise EvidenceError("invalid quarantine inventory binding")
    seen = set()
    for item in inventory:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256", "size", "identity"}
                or not _hash(item["sha256"]) or not _amount(item["size"])
                or not isinstance(item["identity"], list) or len(item["identity"]) != 2
                or any(not _inode(i) for i in item["identity"])):
            raise EvidenceError("invalid quarantine current inventory")
        safe_relative(item["path"])
        if item["path"] in seen:
            raise EvidenceError("duplicate quarantine inventory path")
        seen.add(item["path"])
    validate_proof(value["proof"], value["attempt_id"], value["original_record_sha256"])
    return value


def current_inventory(ledger, record):
    from .producer import _inventory
    from .producer_runtime import directory_identity
    root = Path(record["output_dir"])
    if directory_identity(root) != record["output_identity"]:
        raise EvidenceError("quarantine output directory identity changed")
    before = _inventory(root)
    if len(before) > ledger.policy["limits"]["metadata_stop_files"] or sum(x[2] for x in before.values()) > ledger.policy["limits"]["local_stop_bytes"]:
        raise EvidenceError("quarantine inventory exceeds bounded local inventory allowance")
    inventory = []
    for name, info in sorted(before.items()):
        sha, size = hash_file(root / name)
        if size != info[2]:
            raise EvidenceError("quarantine inventory changed during hashing")
        inventory.append({"path": name, "sha256": sha, "size": size, "identity": list(info[:2])})
    if _inventory(root) != before or directory_identity(root) != record["output_identity"]:
        raise EvidenceError("quarantine inventory changed during hashing")
    return inventory


def original_state(ledger, attempt, *, original_policy=None):
    from . import process_identity, producer_runtime as runtime
    from .producer import _group_exists
    # Existing quarantine validation reads through its exact historical policy.
    # No mutation or temporary reassignment of the live accounting policy occurs;
    # runtime.read retains every original session/reservation/ownership check.
    reader = ledger if original_policy is None else SimpleNamespace(connection=ledger.connection, policy=original_policy)
    record = runtime.read(reader, attempt)
    raw = ledger.connection.execute("SELECT record FROM producer_sessions WHERE id=?", (attempt,)).fetchone()[0]
    if record["status"] not in ("stopping", "terminal"):
        raise EvidenceError("quarantine requires an inactive failed producer record")
    owners = [record["coordinator"], record.get("guardian"), record.get("recovery_owner")]
    owners += [item["identity"] for item in record["processes"].values()]
    if any(owner is not None and process_identity.state(owner) != "gone" for owner in owners):
        raise EvidenceError("quarantine producer owner/helper exit cannot be verified")
    if os.name == "posix" and any(_group_exists(item["group"]) for item in record["processes"].values()):
        raise EvidenceError("quarantine helper process group still exists")
    # Quarantine never cleans paths. A registered resource must already be absent;
    # surviving diagnostic bytes can be inventoried only outside registered temp roots.
    for item in record["resources"]:
        path = Path(item["path"])
        if path.exists() or path.is_symlink():
            raise EvidenceError("quarantine registered resource disposition is incomplete")
    run = ledger.connection.execute("SELECT * FROM runs WHERE id=?", (record["run_id"],)).fetchone()
    reservation = ledger.connection.execute("SELECT * FROM reservations WHERE id=?", (record["reservation_id"],)).fetchone()
    uncertain = ledger.connection.execute("SELECT * FROM uncertain_generation WHERE reservation_id=?", (record["reservation_id"],)).fetchone()
    output = ledger.connection.execute("SELECT * FROM outputs WHERE id=?", (record.get("output_id"),)).fetchone()
    if (run is None or run["status"] != "incomplete" or run["unit_id"] != record["unit_id"] or run["migration"]
            or reservation is None or reservation["state"] != "pending" or uncertain is None
            or run["gross_bytes"] < uncertain["gross_bytes"] or run["gross_files"] < uncertain["logical_files"]
            or output is None or output["reconciled"] != 0):
        raise EvidenceError("quarantine original failed accounting binding is incomplete")
    return record, raw, dict(run), dict(reservation), dict(uncertain)


def build(ledger, attempt, proof):
    record, raw, run, reservation, uncertain = original_state(ledger, attempt)
    original_hash = hashlib.sha256(raw.encode()).hexdigest()
    proof = json.loads(canonical(proof))
    validate_proof(proof, attempt, original_hash, read_files=True)
    inventory = current_inventory(ledger, record)
    value = dict(version=1, kind="quarantined-producer-gap", project_id=ledger.project_id,
                 store_id=ledger.policy["store_id"], ledger_id=ledger._ledger_id, policy_sha256=digest(ledger.policy),
                 attempt_id=attempt, run_id=run["id"], unit_id=run["unit_id"], ordinal=run["ordinal"],
                 reservation_id=reservation["id"], output_id=record["output_id"], intent_id=record.get("intent_id"),
                 original_record_sha256=original_hash, uncertain=uncertain, reservation=reservation, run=run,
                 disposition="quarantined-unresolved", history_complete=False, proof=proof, inventory=inventory,
                 inventory_sha256=digest(inventory), output_identity=record["output_identity"],
                 quarantined_at=datetime.now(timezone.utc).isoformat())
    value["digest"] = digest(value)
    return validate_quarantine_descriptor(value, ledger.policy)


def validate_current(ledger, value):
    validate_quarantine_descriptor(value, ledger.policy)
    original_policy = resolve_historical_policy(ledger.policy, value["policy_sha256"])
    record, raw, run, reservation, uncertain = original_state(ledger, value["attempt_id"], original_policy=original_policy)
    if (value["ledger_id"] != ledger._ledger_id or hashlib.sha256(raw.encode()).hexdigest() != value["original_record_sha256"]
            or value["run_id"] != run["id"] or value["unit_id"] != run["unit_id"] or value["ordinal"] != run["ordinal"]
            or value["reservation"] != reservation or value["uncertain"] != uncertain or value["run"] != run
            or value["output_id"] != record["output_id"] or value["intent_id"] != record.get("intent_id")
            or value["output_identity"] != record["output_identity"]):
        raise EvidenceError("quarantine original accounting/session binding changed")
    validate_proof(value["proof"], value["attempt_id"], value["original_record_sha256"], read_files=True)
    if current_inventory(ledger, record) != value["inventory"]:
        raise EvidenceError("quarantine preserved output inventory changed")
    return value
