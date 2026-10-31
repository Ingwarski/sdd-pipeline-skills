"""Versioned, catalog-backed evidence obligations; never an acceptance cache."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import tempfile

from .io import EvidenceError, atomic_json, hash_file, read_json

ROLES = frozenset(("required_proof", "investigation", "optional_diagnostic"))
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def review_record(value):
    from .manager import timestamp
    if (not isinstance(value, dict) or set(value) != {"reviewer", "reviewed_at", "rationale"}
            or any(not isinstance(value[field], str) or not value[field].strip() for field in value)):
        raise EvidenceError("lifecycle review requires reviewer, reviewed_at and rationale")
    if timestamp(value["reviewed_at"]) > datetime.now(timezone.utc):
        raise EvidenceError("lifecycle review cannot be in the future")
    return deepcopy(value)


def empty_state():
    return {"version": 1, "adopted": False, "automatic_cleanup": False,
        "participants": {}, "classifications": {}, "ever_referenced": [], "events": []}


def apply_event(state, event, references):
    """Replay immutable administrative events while retaining their original facts."""
    from .manager import timestamp
    if not isinstance(event, dict) or event.get("version") != 1 or type(event.get("version")) is not int:
        raise EvidenceError("unsupported lifecycle event")
    if event.get("digest") != digest({key: value for key, value in event.items() if key != "digest"}):
        raise EvidenceError("lifecycle event identity changed")
    if event.get("previous") != (state["events"][-1] if state["events"] else None):
        raise EvidenceError("lifecycle event ancestry changed")
    recorded = timestamp(event.get("recorded_at"))
    if recorded > datetime.now(timezone.utc):
        raise EvidenceError("lifecycle decision time is in the future")
    action = event.get("action")
    common = {"version", "action", "recorded_at", "previous", "digest"}
    if action in ("adopt", "classify", "retire"):
        review = review_record(event.get("review"))
        if timestamp(review["reviewed_at"]) > recorded:
            raise EvidenceError("lifecycle decision predates its review")
        common.add("review")
    if action == "adopt":
        if state["adopted"] or set(event) != common | {"automatic_cleanup"} or type(event["automatic_cleanup"]) is not bool:
            raise EvidenceError("lifecycle adoption must be unique and explicit")
        state["adopted"], state["automatic_cleanup"] = True, event["automatic_cleanup"]
        state["adoption_review"] = deepcopy(event["review"])
        state["adoption_review_digest"] = digest(event["review"])
    elif not state["adopted"]:
        raise EvidenceError("lifecycle event precedes adoption")
    elif action == "checkpoint":
        if set(event) != common | {"participant_id", "inventory"}:
            raise EvidenceError("invalid lifecycle checkpoint")
        participant = event["participant_id"]
        if not isinstance(participant, str) or not ID.fullmatch(participant):
            raise EvidenceError("invalid lifecycle participant identity")
        inventory = event["inventory"]
        from .dependencies import inventory_digest
        if (not isinstance(inventory, dict) or inventory.get("version") != 1
                or inventory.get("digest") != inventory_digest(inventory) or inventory.get("blockers")
                or not isinstance(inventory.get("roots"), list)
                or any(ident not in references for ident in inventory["roots"])):
            raise EvidenceError("lifecycle checkpoint lacks a complete computed inventory")
        previous = state["participants"].get(participant)
        if previous and previous.get("retired"):
            raise EvidenceError("retired participant identity cannot be reused")
        state["participants"][participant] = {"inventory": deepcopy(inventory), "retired": False,
            "recorded_at": event["recorded_at"]}
        state["ever_referenced"] = sorted(set(state["ever_referenced"]) | set(inventory["roots"]))
    elif action == "classify":
        if (set(event) != common | {"artifacts", "role", "purpose_complete"}
                or event["role"] not in ROLES or type(event["purpose_complete"]) is not bool
                or not isinstance(event["artifacts"], dict) or not event["artifacts"]):
            raise EvidenceError("invalid lifecycle classification")
        if event["role"] == "investigation" and event["purpose_complete"]:
            raise EvidenceError("resolve investigation into proof or optional diagnostics")
        for ident, expected in event["artifacts"].items():
            if ident not in references or digest(references[ident]) != expected:
                raise EvidenceError("classification original evidence identity changed")
            state["classifications"][ident] = {"role": event["role"],
                "purpose_complete": event["purpose_complete"], "review": deepcopy(event["review"]),
                "recorded_at": event["recorded_at"], "reference_sha256": expected}
    elif action == "retire":
        if set(event) != common | {"participant_id"} or event["participant_id"] not in state["participants"]:
            raise EvidenceError("retirement requires a registered participant scope")
        state["participants"][event["participant_id"]]["retired"] = True
        state["participants"][event["participant_id"]]["retirement"] = deepcopy(event["review"])
    else:
        raise EvidenceError("unknown lifecycle event action")
    state["events"].append(event["digest"])


def event(state, action, **fields):
    value = {"version": 1, "action": action, "recorded_at": now(),
        "previous": state["events"][-1] if state["events"] else None, **fields}
    value["digest"] = digest(value)
    return value


class LifecycleMixin:
    """Storage mutation entrypoints. All live-project facts come from the collector."""

    def _lifecycle_bindings(self):
        path = self.state / "lifecycle-bindings.json"
        value = read_json(path, self.limits["metadata_stop_bytes"]) if path.exists() else {"version": 1, "participants": {}}
        if not isinstance(value, dict) or set(value) != {"version", "participants"} or value["version"] != 1 or not isinstance(value["participants"], dict):
            raise EvidenceError("invalid machine-local lifecycle bindings")
        return value

    def _lifecycle_binding(self, participant_id, manifest_path=None):
        if not isinstance(participant_id, str) or not ID.fullmatch(participant_id):
            raise EvidenceError("invalid lifecycle participant identity")
        if self.project is None:
            raise EvidenceError("lifecycle operations require an explicit project")
        from .io import safe_relative
        return {"project": str(self.project), "manifest_path": safe_relative(manifest_path or "forge/sdd-manifest.json"),
            "host": socket.gethostname()}

    def _store_lifecycle_binding(self, participant_id, binding):
        bindings = self._lifecycle_bindings()
        prior = bindings["participants"].get(participant_id)
        if prior is not None and prior != binding:
            raise EvidenceError("participant binding changed; register a distinct identity")
        bindings["participants"][participant_id] = binding
        atomic_json(self.state / "lifecycle-bindings.json", bindings)

    def _lifecycle_collect(self, binding, catalog, prior=None):
        from .dependencies import collect_project, assert_unchanged
        if binding.get("host") != socket.gethostname():
            raise EvidenceError("lifecycle participant is unavailable on this host")
        project = Path(binding["project"])
        if not project.is_dir() or project.resolve() != project or project.is_symlink():
            raise EvidenceError("lifecycle participant project is unavailable or unsafe")
        catalog = self._lifecycle_recoverable_catalog(catalog)
        def resolve(reference):
            return self.read_lifecycle_metadata(reference, catalog=catalog)
        inventory = collect_project(project, manifest_path=binding["manifest_path"], catalog=catalog,
            resolve_external=resolve, prior_index=prior)
        if inventory.get("blockers"):
            raise EvidenceError("lifecycle inventory incomplete: " + "; ".join(inventory["blockers"]))
        if inventory.get("project_id") != self.policy["project_id"] or inventory.get("store_id") != self.policy["store_id"]:
            raise EvidenceError("participant inventory belongs to a different project/store")
        if prior:
            from .dependencies import HISTORY
            for relative, expected in prior.get("inputs", {}).items():
                if relative.startswith(HISTORY + "/") and relative.endswith(".json") and "/files/" not in relative:
                    if inventory.get("inputs", {}).get(relative) != expected:
                        raise EvidenceError("retained immutable history envelope changed or disappeared: " + relative)
        assert_unchanged(project, inventory)
        return inventory

    def _lifecycle_recoverable_catalog(self, catalog):
        # Interrupted physical deletion may leave the original safely restorable.
        # Discovery may protect it immediately; reactivation independently verifies it.
        references = dict(catalog["refs"])
        for ident, ref in catalog.get("retired_refs", {}).items():
            storage = self._storage_reference(catalog, ref)
            if all(part["pack_sha256"] in catalog["packs"]
                    for part in storage["locator"].get("segments") or [storage["locator"]]):
                references.setdefault(ident, ref)
        return {**catalog, "refs": references}

    def lifecycle_status(self, *, catalog=None):
        catalog = catalog or self._catalog()
        state = catalog.get("lifecycle", empty_state())
        local = self._lifecycle_bindings()["participants"]
        return {"adopted": state["adopted"], "automatic_cleanup": state["automatic_cleanup"],
            "adoption_review_digest": state.get("adoption_review_digest"),
            "local_participants": sorted(key for key, value in local.items() if self.project is not None and
                value.get("project") == str(self.project) and value.get("host") == socket.gethostname()),
            "participants": {key: {"retired": value["retired"],
                "manifest_path": value["inventory"]["manifest_path"],
                "inventory_digest": value["inventory"]["digest"],
                "root_count": len(value["inventory"]["roots"])} for key, value in state["participants"].items()},
            "catalog_revision": {"root_key": catalog["root_key"], "sequence": catalog["sequence"]}}

    def lifecycle_participant(self):
        state = self._catalog().get("lifecycle", empty_state())
        return self._lifecycle_bound_participant(state)

    def _lifecycle_bound_participant(self, state):
        if not state["adopted"] or self.project is None:
            return None
        matches = [key for key, value in self._lifecycle_bindings()["participants"].items()
            if value.get("project") == str(self.project) and value.get("host") == socket.gethostname()
            and key in state["participants"] and not state["participants"][key]["retired"]]
        if len(matches) > 1:
            raise EvidenceError("ambiguous lifecycle participant binding")
        return matches[0] if matches else None

    def _lifecycle_writer_guard(self, catalog):
        state = catalog.get("lifecycle", empty_state())
        if state["adopted"] and self._lifecycle_bound_participant(state) is None:
            raise EvidenceError("lifecycle writer must register its project participant before publication")

    def adopt_lifecycle(self, participant_id, *, manifest_path="forge/sdd-manifest.json", review, automatic_cleanup=True):
        review = review_record(review)
        if type(automatic_cleanup) is not bool:
            raise EvidenceError("automatic cleanup choice must be Boolean")
        with self.locked():
            catalog = self._catalog(mutation=True)
            if catalog.get("pending_deletions") or (self.state / "pruning.json").exists():
                raise EvidenceError("reconcile legacy deletion intent before lifecycle adoption")
            state = deepcopy(catalog.get("lifecycle", empty_state()))
            binding = self._lifecycle_binding(participant_id, manifest_path)
            if state["adopted"]:
                if state.get("adoption_review_digest") != digest(review) or state["automatic_cleanup"] != automatic_cleanup:
                    raise EvidenceError("evidence lifecycle already adopted with a different decision")
                previous = state["participants"].get(participant_id)
                if previous is None or previous["retired"]:
                    raise EvidenceError("adoption retry does not match its original participant")
                inventory = self._lifecycle_collect(binding, catalog, previous["inventory"])
                if inventory["digest"] != previous["inventory"]["digest"]:
                    raise EvidenceError("adoption retry inputs changed; checkpoint explicitly")
                self._store_lifecycle_binding(participant_id, binding)
                return self.lifecycle_status(catalog=catalog)
            inventory = self._lifecycle_collect(binding, catalog)
            self._verify_lifecycle_roots(catalog, inventory["roots"])
            from .dependencies import assert_unchanged
            assert_unchanged(Path(binding["project"]), inventory)
            first = event(state, "adopt", review=review, automatic_cleanup=automatic_cleanup)
            apply_event(state, first, catalog["refs"])
            second = event(state, "checkpoint", participant_id=participant_id, inventory=inventory)
            apply_event(state, second, catalog["refs"])
            self._publish(catalog, {"version": 1, "lifecycle_events": [first, second]})
            self._store_lifecycle_binding(participant_id, binding)
            return self.lifecycle_status()

    def _verify_lifecycle_roots(self, catalog, roots):
        """Once-only adoption readback: a warm cache cannot hide lost proof packs."""
        from .archive import verify_pack
        from .identity import same_reference
        from .resolver import validate_reference
        packs, visited, queue = {}, set(), list(roots)
        while queue:
            ident = queue.pop()
            if ident in visited:
                continue
            visited.add(ident)
            reference = catalog["refs"].get(ident)
            if reference is None:
                raise EvidenceError("adoption proof is absent from authoritative storage")
            validate_reference(reference)
            for child in reference.get("dependencies", []):
                target = catalog["refs"].get(child["artifact_id"])
                aliases = catalog.get("reference_aliases", {}).get(child["artifact_id"], [])
                if target is None or not any(same_reference(child, candidate) for candidate in [target] + aliases):
                    raise EvidenceError("adoption proof dependency identity changed")
                queue.append(child["artifact_id"])
            storage = self._storage_reference(catalog, reference)
            offset = 0
            for part in storage["locator"].get("segments") or [storage["locator"]]:
                pack = catalog["packs"].get(part["pack_sha256"])
                if pack is None or pack["locator"]["object_id"] != part["object_id"] or pack["size"] != part["pack_size"]:
                    raise EvidenceError("adoption proof archive identity changed")
                member = next((item for item in pack["members"] if item["member"] == part["member"]), None)
                if (member is None or member["sha256"] != part.get("sha256", reference["sha256"])
                        or member["size"] != part.get("length", reference["size"]) or part.get("offset", 0) != offset):
                    raise EvidenceError("adoption proof archive member binding changed")
                offset += member["size"]
                packs[part["pack_sha256"]] = pack
            if offset != reference["size"]:
                raise EvidenceError("adoption proof original length differs")
        for pack in packs.values():
            peak = pack["size"] + pack["original_bytes"] + 65536
            with self._working(peak), tempfile.TemporaryDirectory(dir=self.staging, prefix="lifecycle-adopt-") as temp:
                archive = Path(temp) / "readback.pack"
                self._transport_call("get", pack["locator"], archive, pack["size"])
                verify_pack(archive, pack["sha256"], pack["size"], pack["members"], max_bytes=pack["original_bytes"],
                    max_files=self.limits["migration_batch_stop_files"],
                    max_decoder_memory_bytes=self.limits.get("archive_decoder_memory_bytes", 128 * 1024 * 1024))

    def checkpoint_lifecycle(self, participant_id, *, manifest_path=None, dry_run=False, cleanup=True):
        with self.locked():
            catalog = self._catalog(mutation=True)
            state = catalog.get("lifecycle", empty_state())
            if not state["adopted"]:
                raise EvidenceError("lifecycle adoption required")
            saved_binding = self._lifecycle_bindings()["participants"].get(participant_id)
            binding = self._lifecycle_binding(participant_id, manifest_path or (saved_binding or {}).get("manifest_path"))
            if saved_binding is not None and saved_binding != binding:
                raise EvidenceError("participant binding changed; register a distinct identity")
            previous = state["participants"].get(participant_id)
            if previous and previous["retired"]:
                raise EvidenceError("retired participant cannot publish new dependencies")
            inventory = self._lifecycle_collect(binding, catalog, (previous or {}).get("inventory"))
            changed = previous is None or previous["inventory"]["digest"] != inventory["digest"]
            if changed and not dry_run:
                restored = [catalog["retired_refs"][ident] for ident in inventory["roots"] if ident not in catalog["refs"]]
                cancelled = set()
                if restored:
                    self.prepare(restored, catalog=self._lifecycle_recoverable_catalog(catalog), reverify_durable=True)
                    for ref in restored:
                        storage = self._storage_reference(catalog, ref)
                        cancelled.update(part["pack_sha256"] for part in storage["locator"].get("segments") or [storage["locator"]])
                value = event(state, "checkpoint", participant_id=participant_id, inventory=inventory)
                segment = {"version": 1, "lifecycle_events": [value]}
                if restored:
                    segment.update(refs=restored, cancelled_deletions=sorted(cancelled & set(catalog.get("pending_deletions", {}))))
                self._publish(catalog, segment)
            if not dry_run:
                self._store_lifecycle_binding(participant_id, binding)
            actions = []
            if cleanup and state["automatic_cleanup"] and not dry_run:
                actions = self.cleanup_lifecycle(dry_run=False)
            return {"participant_id": participant_id, "changed": changed, "inventory_digest": inventory["digest"],
                "statistics": inventory.get("statistics", {}), "dry_run": dry_run, "actions": actions}

    def classify_lifecycle(self, artifact_ids, *, role, review, purpose_complete=False):
        review = review_record(review)
        if role not in ROLES or type(purpose_complete) is not bool or role == "investigation" and purpose_complete:
            raise EvidenceError("invalid lifecycle role/purpose completion")
        with self.locked():
            catalog = self._catalog(mutation=True)
            state = catalog.get("lifecycle", empty_state())
            if not state["adopted"]:
                raise EvidenceError("lifecycle adoption required")
            identifiers = sorted(set(artifact_ids))
            if not identifiers or any(ident not in catalog["refs"] for ident in identifiers):
                raise EvidenceError("classification requires registered active evidence")
            if all(state["classifications"].get(ident, {}).get("role") == role and
                    state["classifications"][ident]["purpose_complete"] == purpose_complete and
                    state["classifications"][ident]["review"] == review for ident in identifiers):
                return {"artifact_ids": identifiers, "role": role, "purpose_complete": purpose_complete, "changed": False}
            value = event(state, "classify", review=review, role=role, purpose_complete=purpose_complete,
                artifacts={ident: digest(catalog["refs"][ident]) for ident in identifiers})
            self._publish(catalog, {"version": 1, "lifecycle_events": [value]})
            return {"artifact_ids": identifiers, "role": role, "purpose_complete": purpose_complete}

    def retire_lifecycle_scope(self, participant_id, *, review):
        review = review_record(review)
        with self.locked():
            catalog = self._catalog(mutation=True)
            state = catalog.get("lifecycle", empty_state())
            if not state["adopted"] or participant_id not in state["participants"]:
                raise EvidenceError("retirement requires a registered lifecycle scope")
            self._lifecycle_producer_guard(catalog)
            if state["participants"][participant_id]["retired"]:
                return {"participant_id": participant_id, "retired": True, "changed": False}
            self._publish(catalog, {"version": 1, "lifecycle_events": [event(state, "retire",
                participant_id=participant_id, review=review)]})
            return {"participant_id": participant_id, "retired": True, "changed": True}

    def _lifecycle_producer_guard(self, catalog):
        if any(not item.get("settled") for item in catalog.get("generation_intents", {}).values()):
            raise EvidenceError("active or unresolved producer holds prevent permanent deletion")
        if catalog.get("unreconciled_packs"):
            raise EvidenceError("unreconciled archive publication prevents permanent deletion")
        for path in self.state.glob("archive-*.json"):
            if path.name.endswith(".deletion.json"):
                continue
            value = read_json(path, self.limits["metadata_stop_bytes"])
            if value.get("status") != "complete":
                raise EvidenceError("unfinished archive publication prevents permanent deletion")

    def _lifecycle_inventory(self, catalog):
        state = catalog.get("lifecycle", empty_state())
        if not state["adopted"]:
            raise EvidenceError("lifecycle adoption required for permanent deletion")
        self._lifecycle_producer_guard(catalog)
        bindings = self._lifecycle_bindings()["participants"]
        protected, reasons, checks = set(), {}, []
        recorded_edges, json_artifacts = {}, {}
        for value in state["participants"].values():
            for edge in value["inventory"].get("edges", []):
                recorded_edges.setdefault(edge["from"], set()).add(edge["to"])
            for ident, original in value["inventory"].get("json_artifacts", {}).items():
                previous = json_artifacts.setdefault(ident, original)
                if previous != original:
                    raise EvidenceError("retained JSON source type has conflicting original identity")
        for participant, value in state["participants"].items():
            if value["retired"]:
                continue
            binding = bindings.get(participant)
            if binding is None:
                raise EvidenceError("registered lifecycle participant is unavailable: " + participant)
            current = self._lifecycle_collect(binding, catalog, value["inventory"])
            if current["digest"] != value["inventory"]["digest"]:
                raise EvidenceError("participant records changed; checkpoint before deletion: " + participant)
            checks.append((binding, current))
            for ident in current["roots"]:
                protected.add(ident)
                reasons.setdefault(ident, []).append("participant:" + participant)
        for ident, ref in catalog["refs"].items():
            if (ref["retention"].get("protections") or ref["kind"] in ("approval", "authorization", "approved-baseline", "unresolved-failure")
                    or ref["retention"].get("imported") and ident not in state["classifications"]):
                protected.add(ident)
                reasons.setdefault(ident, []).append("explicit-or-unresolved-protection")
            role = state["classifications"].get(ident)
            reason = None
            if role is None and ident not in state["ever_referenced"]:
                reason = "unclassified-or-unpublished"
            elif role is not None and (role["role"] == "investigation" or not role["purpose_complete"]):
                reason = "purpose-not-complete"
            elif role is not None and role["role"] == "required_proof" and ident not in state["ever_referenced"]:
                reason = "unpublished-proof"
            if reason:
                protected.add(ident)
                reasons.setdefault(ident, []).append(reason)
        queue = list(protected)
        while queue:
            ident = queue.pop()
            ref = catalog["refs"].get(ident)
            if ref is None:
                raise EvidenceError("required evidence was retired or is missing")
            children = list(ref.get("dependencies", []))
            # Past parsed context can preserve native local-reference indirection
            # after its scope retires. It supplies dependency edges only: it can
            # never turn a previously rooted artifact into a current root/pass.
            pending, visited = ["artifact:" + ident], set()
            while pending:
                node = pending.pop()
                if node in visited:
                    continue
                visited.add(node)
                for target in recorded_edges.get(node, ()):
                    if target.startswith("artifact:"):
                        child_id = target.removeprefix("artifact:")
                        if child_id != ident:
                            child = catalog["refs"].get(child_id)
                            if child is None:
                                raise EvidenceError("retained contextual dependency is missing")
                            children.append(child)
                    else:
                        pending.append(target)
            typed_json = json_artifacts.get(ident)
            if typed_json is not None and typed_json != {"sha256": ref["sha256"], "size": ref["size"]}:
                raise EvidenceError("retained JSON source type does not match original bytes")
            source_json = typed_json is not None or (ref.get("kind") == "source_snapshot" and
                Path(ref.get("original_path", "")).suffix.lower() == ".json")
            if source_json or ref["schema"] not in ("evidence-bytes-v1", "archive-attachment-v1"):
                from .resolver import payload_references, JSON_LIMIT
                metadata = self.read_lifecycle_metadata(ref, catalog=catalog)
                children.extend(payload_references(read_json(metadata, min(JSON_LIMIT, self.limits["metadata_stop_bytes"])),
                    "evidence-json-v1" if source_json else ref["schema"]))
            for child in children:
                key = child["artifact_id"]
                from .identity import same_reference
                target = catalog["refs"].get(key)
                aliases = catalog.get("reference_aliases", {}).get(key, [])
                if target is None or not any(same_reference(child, candidate) for candidate in [target] + aliases):
                    raise EvidenceError("retained evidence dependency original identity changed")
                if key not in protected:
                    protected.add(key)
                    reasons.setdefault(key, []).append("required-by:" + ident)
                    queue.append(key)
        candidates = set(catalog["refs"]) - protected
        return {"candidates": sorted(candidates), "reasons": reasons, "checks": checks,
            "root_key": catalog["root_key"], "sequence": catalog["sequence"]}

    def _lifecycle_recheck(self, inventory, catalog):
        from .dependencies import assert_unchanged
        for binding, snapshot in inventory["checks"]:
            assert_unchanged(Path(binding["project"]), snapshot)
        roots = self._transport_call("keys", self.prefix + "roots/")
        current = max((item if isinstance(item, str) else item["key"] for item in roots), default=None)
        if current != catalog["root_key"]:
            raise EvidenceError("catalog changed before lifecycle deletion")

    def cleanup_lifecycle(self, *, dry_run=True):
        with self.locked():
            catalog = self._catalog(mutation=True)
            inventory = self._lifecycle_inventory(catalog)
            retired = inventory["candidates"]
            actions = [{"artifact_id": ident, "action": "retire", "dry_run": dry_run,
                "reason": "purpose-complete-with-no-remaining-obligation"} for ident in retired]
            remaining = {ident: ref for ident, ref in catalog["refs"].items() if ident not in retired}
            used = set()
            for ref in remaining.values():
                storage = self._storage_reference(catalog, ref)
                used.update(seg["pack_sha256"] for seg in storage["locator"].get("segments") or [storage["locator"]])
            packs = {key: pack for key, pack in catalog["packs"].items() if key not in used}
            if dry_run:
                actions.extend({"pack": key, "action": "delete-pack", "dry_run": True,
                    "encoded_bytes": pack["size"]} for key, pack in packs.items())
                return actions
            self._lifecycle_recheck(inventory, catalog)
            journal = self.state / "lifecycle-pruning.json"
            if retired or packs:
                intent = {"version": 1, "retired": retired, "packs": packs, "done": []}
                atomic_json(journal, intent)
                if retired or set(packs) - set(catalog.get("pending_deletions", {})):
                    self._publish(catalog, {"version": 1, "retired": retired, "deletion_intent": list(packs)})
                    catalog = self._catalog(mutation=True)
            elif journal.exists():
                intent = read_json(journal, self.limits["metadata_stop_bytes"])
            else:
                return actions
            return actions + self._resume_lifecycle_pruning(catalog, intent, journal)

    def _resume_lifecycle_pruning(self, catalog, intent, journal):
        results, completed = [], []
        inventory = self._lifecycle_inventory(catalog)
        for key, pack in intent["packs"].items():
            if key not in catalog.get("pending_deletions", {}):
                if key not in intent["done"]:
                    intent["done"].append(key)
                continue
            if key in intent["done"]:
                if key in catalog["packs"]:
                    completed.append(key)
                continue
            # A newly registered consumer can protect a still-present pack after interruption.
            for ref in catalog["refs"].values():
                storage = self._storage_reference(catalog, ref)
                if any(seg["pack_sha256"] == key for seg in storage["locator"].get("segments") or [storage["locator"]]):
                    raise EvidenceError("archive became required before interrupted deletion resumed")
            self._lifecycle_recheck(inventory, catalog)
            try:
                self._transport_call("delete", pack["locator"])
                intent["done"].append(key)
                completed.append(key)
                atomic_json(journal, intent)
                results.append({"pack": key, "action": "deleted", "verified": True, "freed_bytes": pack["size"]})
            except (OSError, EvidenceError) as error:
                results.append({"pack": key, "action": "delete-failed", "reason": str(error)})
        if completed:
            self._publish(catalog, {"version": 1, "deleted_packs": completed})
        if len(intent["done"]) == len(intent["packs"]):
            journal.unlink()
        return results

    def relocate_lifecycle_pack(self, pack_sha256, *, dry_run=True):
        """Repack surviving original members; published observations remain immutable."""
        from .archive import verify_pack
        from .relocation import create_relocation
        with self.locked():
            catalog = self._catalog(mutation=True)
            original_pack = catalog["packs"].get(pack_sha256)
            if original_pack is None:
                for path in self.state.glob("lifecycle-relocate-*.json"):
                    previous = read_json(path, self.limits["metadata_stop_bytes"])
                    if (previous.get("source_pack") == pack_sha256 and previous.get("status") == "complete"
                            and previous.get("relocations") and all(any(item["digest"] == expected
                                for item in catalog.get("storage_relocations", {}).get(ident, []))
                                for ident, expected in previous["relocations"].items())):
                        return {"pack": pack_sha256, "dry_run": dry_run, "action": "already-relocated", "actions": []}
                raise EvidenceError("relocation requires a registered archive pack")
            survivors, members = {}, {}
            for ident, reference in catalog["refs"].items():
                storage = self._storage_reference(catalog, reference)
                selected = [part for part in storage["locator"].get("segments") or [storage["locator"]]
                    if part["pack_sha256"] == pack_sha256]
                if selected:
                    survivors[ident] = storage
                    for part in selected:
                        member = next((item for item in original_pack["members"] if item["member"] == part["member"]), None)
                        if member is None:
                            raise EvidenceError("relocation original member is absent")
                        members[member["sha256"]] = member
            result = {"pack": pack_sha256, "dry_run": dry_run, "retained_artifacts": sorted(survivors),
                "retained_original_bytes": sum(member["size"] for member in members.values()), "actions": []}
            if not survivors:
                result["action"] = "unused-pack-use-lifecycle-cleanup"
                self._lifecycle_inventory(catalog)
                if not dry_run:
                    result["actions"] = self.cleanup_lifecycle(dry_run=False)
                return result
            if len(members) == len(original_pack["members"]):
                self._lifecycle_inventory(catalog)
                result["action"] = "no-disposable-pack-members"
                return result
            result["action"] = "relocate-surviving-members"
            operation = digest({"pack": pack_sha256, "members": sorted(members),
                "references": {key: digest(catalog["refs"][key]) for key in survivors}})
            journal = self.state / ("lifecycle-relocate-" + operation + ".json")
            checkpoint = {"version": 1, "path": str(journal), "migration": True, "packs": {},
                "status": "capturing", "source_pack": pack_sha256}
            discovery = catalog
            if journal.exists():
                previous = read_json(journal, self.limits["metadata_stop_bytes"])
                if any(previous.get(field) != checkpoint[field] for field in ("version", "path", "migration", "source_pack")):
                    raise EvidenceError("relocation recovery journal identity changed")
                checkpoint = previous
                expected = {self.prefix + "packs/" + item["sha256"] + ".zip": item["size"]
                    for item in list(checkpoint["packs"].values()) + ([checkpoint["pending_pack"]] if checkpoint.get("pending_pack") else [])}
                # Only this exact deterministic repack may recover its unpublished
                # upload. Any unrelated producer or unknown object still blocks.
                discovery = {**catalog, "unreconciled_packs": {key: value for key, value in catalog.get("unreconciled_packs", {}).items()
                    if expected.get(value.get("key")) != value.get("size")}}
            inventory = self._lifecycle_inventory(discovery)
            if dry_run:
                return result
            atomic_json(journal, checkpoint)
            peak = original_pack["size"] + original_pack["original_bytes"] + sum(item["size"] for item in members.values()) * 3 + 65536
            self._capacity(peak, migration=True)
            with self._working(peak, migration=True), tempfile.TemporaryDirectory(dir=self.staging, prefix="lifecycle-relocate-") as temp:
                temp = Path(temp).resolve()
                archive = temp / "original.pack"
                extracted = temp / "members"
                self._transport_call("get", original_pack["locator"], archive, original_pack["size"])
                verify_pack(archive, original_pack["sha256"], original_pack["size"], original_pack["members"],
                    destination=extracted, max_bytes=original_pack["original_bytes"],
                    max_files=self.limits["migration_batch_stop_files"],
                    max_decoder_memory_bytes=self.limits.get("archive_decoder_memory_bytes", 128 * 1024 * 1024))
                replacements = self._pack([{**member, "path": extracted / member["sha256"]} for member in members.values()], checkpoint)
            relocations = {}
            for ident, storage in survivors.items():
                stored = deepcopy(storage)
                locator = stored["locator"]
                parts = locator.get("segments") or [locator]
                for part in parts:
                    if part["pack_sha256"] != pack_sha256:
                        continue
                    original_member = next(item for item in original_pack["members"] if item["member"] == part["member"])
                    replacement_member = next(item for item in replacements["members"] if item["sha256"] == original_member["sha256"])
                    part.update(object_id=replacements["locator"]["object_id"], key=replacements["locator"]["key"],
                        pack_sha256=replacements["sha256"], pack_size=replacements["size"], member=replacement_member["member"])
                if locator.get("segments"):
                    locator["object_id"] = locator["segments"][0]["object_id"]
                chain = catalog["storage_relocations"].get(ident, [])
                relocations[ident] = create_relocation(catalog["refs"][ident], stored, chain[-1] if chain else None)
            prospective = {**catalog, "packs": {**catalog["packs"], replacements["sha256"]: replacements},
                "storage_relocations": {**catalog["storage_relocations"], **{ident:
                    catalog["storage_relocations"].get(ident, []) + [value] for ident, value in relocations.items()}}}
            # Independently reconstruct each original through the proposed mapping before committing it.
            self.prepare([catalog["refs"][ident] for ident in survivors], catalog=prospective, reverify_durable=True)
            self._lifecycle_recheck(inventory, catalog)
            self._publish(catalog, {"version": 1, "packs": {replacements["sha256"]: replacements},
                "storage_relocations": relocations})
            checkpoint["status"] = "complete"
            checkpoint["relocations"] = {ident: value["digest"] for ident, value in relocations.items()}
            atomic_json(journal, checkpoint)
            result["replacement_pack"] = replacements["sha256"]
            result["actions"] = self.cleanup_lifecycle(dry_run=False)
            result["net_encoded_bytes_freed"] = sum(item.get("freed_bytes", 0) for item in result["actions"]) - replacements["size"]
            return result
