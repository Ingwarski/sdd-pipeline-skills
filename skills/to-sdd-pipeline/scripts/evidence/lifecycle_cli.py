"""Explicit project adoption and automatic managed lifecycle checkpoints.

These helpers belong to the mutating storage/history commands, never the
read-only checker. The durable coordinator computes deletion dependencies.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .io import EvidenceError, atomic_json, hash_file, read_json, safe_relative


COMMANDS = (
    "lifecycle-adopt", "lifecycle-checkpoint", "lifecycle-classify",
    "lifecycle-retire", "lifecycle-cleanup", "lifecycle-relocate", "lifecycle-status",
)


def arguments(parser, name):
    if name == "lifecycle-adopt":
        parser.add_argument("--participant", required=True)
        parser.add_argument("--manifest", default="forge/sdd-manifest.json")
        parser.add_argument("--review", required=True, help="Owner review metadata JSON")
        parser.add_argument("--optional-members", help="Exact reviewed historical diagnostic members; JSON list")
        parser.add_argument("--manual-cleanup", action="store_true")
    elif name == "lifecycle-checkpoint":
        parser.add_argument("--participant")
        parser.add_argument("--manifest")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--no-cleanup", action="store_true")
    elif name == "lifecycle-classify":
        parser.add_argument("--role", required=True,
                            choices=("required_proof", "investigation", "optional_diagnostic"))
        parser.add_argument("--purpose-complete", action="store_true")
        parser.add_argument("--review", required=True)
    elif name == "lifecycle-retire":
        parser.add_argument("--participant", required=True)
        parser.add_argument("--review", required=True)
    elif name in ("lifecycle-cleanup", "lifecycle-relocate"):
        parser.add_argument("--apply", action="store_true")
        if name == "lifecycle-relocate":
            parser.add_argument("--pack-sha256", required=True)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _selected_json(path, manager):
    return read_json(Path(path).expanduser().resolve(), manager.limits["metadata_stop_bytes"])


def _manifest_path(manager, relative):
    if manager.project is None:
        raise EvidenceError("lifecycle adoption requires the actual --project")
    import sdd_history
    return sdd_history.physical(manager.project, safe_relative(relative))


def adopt(manager, *, participant_id, manifest_path, review, members, automatic_cleanup):
    """Keep an exact resumable candidate; never migrate another project.

    A catalog publication can succeed before a transport acknowledgement fails.
    The candidate remains installed on that boundary, rather than rolling back
    the old-client guard while the store may already have adopted version 2.
    """
    from . import diagnostics
    import sdd_history
    if not isinstance(members, list) or not isinstance(review, dict):
        raise EvidenceError("lifecycle adoption requires review metadata and a member list")
    selected = _manifest_path(manager, manifest_path)
    request = {"version": 1, "project_id": manager.policy["project_id"],
               "store_id": manager.policy["store_id"], "participant_id": participant_id,
               "manifest_path": manifest_path, "review": review, "members": members,
               "automatic_cleanup": automatic_cleanup}
    key = _digest(request)
    # Machine-owned transaction state remains outside the consuming repository.
    journal_path = manager.state / ("lifecycle-adoption-" + key + ".json")
    with manager.locked():
        if journal_path.exists():
            journal = read_json(journal_path, manager.limits["metadata_stop_bytes"])
            if journal.get("request") != request:
                raise EvidenceError("lifecycle adoption journal differs from its request")
            original, candidate = journal["original"], journal["candidate"]
            if _digest(candidate) != journal.get("candidate_digest"):
                raise EvidenceError("lifecycle adoption candidate journal changed")
            current = hash_file(selected)[0]
            if current not in (journal["original_hash"], journal.get("installed_hash")):
                raise EvidenceError("manifest changed during lifecycle adoption; retain the journal and review the conflict")
        else:
            before = hash_file(selected)[0]
            original = read_json(selected, manager.limits["metadata_stop_bytes"])
            if hash_file(selected)[0] != before:
                raise EvidenceError("manifest changed while preparing lifecycle adoption")
            reference = diagnostics.capture_review(manager.project, original, members, review,
                                                   evidence_cache=manager.cache)
            candidate = deepcopy(original)
            policy = deepcopy(candidate.get("history_integrity", {"legacy_payloads": "every_gate"}))
            policy["optional_diagnostics_ref"] = reference
            candidate["history_integrity"] = policy
            with diagnostics.scope(manager.project, candidate):
                observations = sdd_history.candidate_hashes(manager.project, candidate,
                                                           evidence_cache=manager.cache)
            journal = {"version": 1, "request": request, "original_hash": before,
                       "original": original, "candidate": candidate,
                       "candidate_digest": _digest(candidate), "observed_hashes": observations,
                       "status": "prepared"}
            manager._capacity(len(_canonical(journal)) * 4 + 65536)
            atomic_json(journal_path, journal)
            current = hash_file(selected)[0]
            if current != before:
                raise EvidenceError("manifest changed before lifecycle activation; candidate retained")
        if current == journal["original_hash"]:
            # Persist the exact expected candidate bytes before replacement, so
            # a crash after replacement is recognizable on the next invocation.
            encoded = (json.dumps(candidate, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")
            journal["installed_hash"] = hashlib.sha256(encoded).hexdigest()
            atomic_json(journal_path, journal)
            if hash_file(selected)[0] != current:
                raise EvidenceError("manifest changed before lifecycle activation")
            atomic_json(selected, candidate)
            if hash_file(selected)[0] != journal["installed_hash"]:
                raise EvidenceError("lifecycle candidate serialization changed")
        else:
            # Re-run the read-only review validation on retries too. This never
            # substitutes today's facts for the original preserved observations.
            diagnostics.load_review(manager.project, candidate)
        if journal["status"] != "adopted":
            with diagnostics.scope(manager.project, candidate):
                observations = sdd_history.candidate_hashes(manager.project, candidate,
                                                           evidence_cache=manager.cache)
            if observations != journal["observed_hashes"]:
                raise EvidenceError("project evidence or inputs changed during lifecycle adoption; candidate retained for review")
        result = manager.adopt_lifecycle(participant_id, manifest_path=manifest_path,
                                         review=review, automatic_cleanup=automatic_cleanup)
        journal["status"] = "adopted"
        atomic_json(journal_path, journal)
        return {"result": "adopted", "participant_id": participant_id,
                "optional_diagnostics_ref": candidate["history_integrity"]["optional_diagnostics_ref"],
                "new_execution": False, "lifecycle": result}


def _automatic_cleanup(manager):
    if not manager.lifecycle_status()["automatic_cleanup"]:
        return {"status": "manual_cleanup_selected"}
    try:
        return manager.cleanup_lifecycle(dry_run=False)
    except (ValueError, OSError, KeyError, TypeError) as error:
        return {"status": "cleanup_deferred", "reason": str(error)}


def execute(args, manager):
    command = args.command
    if command == "lifecycle-adopt":
        return adopt(manager, participant_id=args.participant, manifest_path=args.manifest,
                     review=_selected_json(args.review, manager),
                     members=_selected_json(args.optional_members, manager) if args.optional_members else [],
                     automatic_cleanup=not args.manual_cleanup)
    if command == "lifecycle-checkpoint":
        participant = args.participant or manager.lifecycle_participant()
        if not participant:
            raise EvidenceError("no lifecycle participant is bound to this project; explicitly adopt/register it first")
        return manager.checkpoint_lifecycle(participant, manifest_path=args.manifest,
                                            dry_run=args.dry_run, cleanup=not args.no_cleanup)
    if command == "lifecycle-classify":
        if not args.artifact:
            raise EvidenceError("classify requires at least one --artifact")
        result = manager.classify_lifecycle(args.artifact, role=args.role,
                                            review=_selected_json(args.review, manager),
                                            purpose_complete=args.purpose_complete)
        updated = checkpoint(manager)
        if updated.get("status") == "not_adopted":
            updated = _automatic_cleanup(manager)
        return {"classification": result, "checkpoint": updated}
    if command == "lifecycle-retire":
        result = manager.retire_lifecycle_scope(args.participant, review=_selected_json(args.review, manager))
        return {"retirement": result, "cleanup": _automatic_cleanup(manager)}
    if command == "lifecycle-cleanup":
        return manager.cleanup_lifecycle(dry_run=not args.apply)
    if command == "lifecycle-relocate":
        return manager.relocate_lifecycle_pack(args.pack_sha256, dry_run=not args.apply)
    return manager.lifecycle_status()


def checkpoint(manager, *, manifest_path=None):
    """A failed cleanup/index refresh does not erase a successful operation."""
    try:
        if manager.project is None:
            return {"status": "not_adopted"}
        selected = _manifest_path(manager, manifest_path or "forge/sdd-manifest.json")
        if not selected.is_file():
            return {"status": "not_adopted"}
        manifest = read_json(selected, manager.limits["metadata_stop_bytes"])
        marker = isinstance(manifest.get("history_integrity"), dict) and manifest["history_integrity"].get("optional_diagnostics_ref")
        if not marker and not (manager.state / "lifecycle-bindings.json").exists():
            return {"status": "not_adopted"}
        participant = manager.lifecycle_participant()
        if participant is None:
            return {"status": "not_adopted"}
        return manager.checkpoint_lifecycle(participant, manifest_path=manifest_path)
    except (ValueError, OSError, KeyError, TypeError) as error:
        return {"status": "cleanup_deferred", "reason": str(error)}
