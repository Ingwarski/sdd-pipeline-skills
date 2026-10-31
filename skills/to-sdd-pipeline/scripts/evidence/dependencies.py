"""Read-only, conservative evidence dependency discovery for lifecycle cleanup.

This inventory is derived metadata, never an acceptance verdict. A storage
coordinator must bind it to its complete participant registry and catalog before
using it to plan deletion. In particular, a serialized ``complete`` flag has no
meaning here. Unreadable or unsupported dependency metadata blocks deletion.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .identity import same_reference
from .io import EvidenceError, _is_link, _open_regular, _parents, _unique_pairs, _verify_stable, safe_relative
from .resolver import SCHEMAS, evidence_reference, validate_reference


HISTORY = "forge/unit-history"
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_METADATA_BYTES = 128 * 1024 * 1024
MAX_FILES = 100000
MAX_NODES = 1000000
MAX_DEPTH = 64
MAX_CACHE_BYTES = 256 * 1024
MAX_CACHE_DOCUMENT_BYTES = 64 * 1024
HASH = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")
_DIGEST_EXCLUDED = frozenset({"digest", "statistics", "parse_cache", "catalog_revision"})
_OPAQUE_SCHEMAS = frozenset({"evidence-bytes-v1", "archive-attachment-v1"})
_JSON_ROLES = frozenset({"receipt", "source_manifest", "unit_sequence_exceptions",
                        "execution_contexts", "unit_history", "completion_history",
                        "attempt_history", "legacy_history", "reviewed_acceptance"})


def _json_reference(reference, relative):
    """Preserve the verifier's explicit schema and case-insensitive JSON rules."""
    schema = reference.get("schema")
    if "schema" in reference:
        if not isinstance(schema, str) or schema not in SCHEMAS:
            raise EvidenceError("unsupported local evidence schema")
        if schema in _OPAQUE_SCHEMAS:
            return False
        return True
    # Native immutable envelope readers decode JSON independently of suffix.
    return (Path(relative).suffix.lower() == ".json"
            or (relative.startswith(HISTORY + "/") and "/files/" not in relative))


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def inventory_digest(inventory):
    """Stable source/edge identity; a catalog publication is not a source edit."""
    return hashlib.sha256(_canonical({key: value for key, value in inventory.items()
                                     if key not in _DIGEST_EXCLUDED})).hexdigest()


def _hash(value):
    match = HASH.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise EvidenceError("dependency reference requires a SHA-256 identity")
    return match.group(1).lower()


def _path(project, relative):
    safe_relative(relative)
    path = project.joinpath(*relative.split("/"))
    _parents(path)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if _is_link(info):
            raise EvidenceError("dependency path is a link: " + relative)
    return path


def _read(path, limit=MAX_DOCUMENT_BYTES):
    path, fd, before = _open_regular(path)
    try:
        if before.st_size > limit:
            raise EvidenceError("dependency metadata exceeds byte allowance")
        data = bytearray()
        while True:
            block = os.read(fd, min(1024 * 1024, limit + 1 - len(data)))
            if not block:
                break
            data.extend(block)
            if len(data) > limit:
                raise EvidenceError("dependency metadata exceeds byte allowance")
        _verify_stable(path, fd, before)
        if len(data) != before.st_size:
            raise EvidenceError("dependency metadata length changed")
        return bytes(data)
    finally:
        os.close(fd)


def _encoded(value, encoding):
    options = {"sort_keys": True, "ensure_ascii": True, "allow_nan": False}
    if encoding == "sorted_indent2":
        return (json.dumps(value, indent=2, **options) + "\n").encode()
    if encoding == "sorted_default":
        return json.dumps(value, **options).encode()
    if encoding == "sorted_compact":
        return json.dumps(value, separators=(",", ":"), **options).encode()
    raise ValueError("unsupported dependency parse cache encoding")


def _history_membership(project):
    """Bounded, no-follow membership including unpublished/orphan envelopes."""
    base = _path(project, HISTORY)
    if not base.exists():
        return {HISTORY: None}, []
    memberships, documents, pending, count = {}, [], [HISTORY], 0
    while pending:
        relative = pending.pop()
        path = _path(project, relative)
        if not path.is_dir():
            raise EvidenceError("history metadata root is not a directory: " + relative)
        names = sorted(child.name for child in path.iterdir())
        memberships[relative] = names
        for name in names:
            child_relative = relative + "/" + name
            child = _path(project, child_relative)
            info = child.lstat()
            count += 1
            if count > MAX_FILES:
                raise EvidenceError("history membership exceeds file allowance")
            if stat.S_ISDIR(info.st_mode):
                pending.append(child_relative)
            elif not stat.S_ISREG(info.st_mode):
                raise EvidenceError("history contains a nonregular dependency: " + child_relative)
            elif child.suffix.lower() == ".json" and "/files/" not in child_relative:
                documents.append(child_relative)
        if sorted(child.name for child in path.iterdir()) != names:
            raise EvidenceError("history membership changed during discovery")
    return memberships, sorted(documents, key=lambda value: (not value.endswith("/record.json"), value))


class _Collector:
    def __init__(self, project, manifest_path, catalog, resolve_external, prior_index, retirement):
        original = Path(project).absolute()
        self.project = original.resolve(strict=True)
        if original != self.project or original.is_symlink() or not self.project.is_dir():
            raise EvidenceError("dependency discovery requires a canonical project directory")
        if not isinstance(catalog, dict) or not isinstance(catalog.get("refs"), dict):
            raise EvidenceError("dependency discovery requires a validated evidence catalog")
        self.catalog, self.resolve_external, self.retirement = catalog, resolve_external, retirement
        self.result = {"version": 1, "project_id": catalog.get("project_id"), "store_id": catalog.get("store_id"),
            "manifest_path": safe_relative(manifest_path), "inputs": {}, "history_membership": {},
            "directory_membership": {},
            "roots": [], "edges": [], "reasons": {}, "blockers": [], "json_artifacts": {},
            "catalog_revision": {"root_key": catalog.get("root_key"), "sequence": catalog.get("sequence")},
            "statistics": {"metadata_bytes": 0, "json_parses": 0, "parse_cache_hits": 0,
                           "external_json_reads": 0, "opaque_evidence_leaves": 0}, "parse_cache": {}}
        if not all(isinstance(self.result[key], str) and self.result[key]
                   for key in ("project_id", "store_id")):
            raise EvidenceError("dependency discovery requires project/store identity")
        self.documents, self.overlays, self.source_mappings = {}, {}, {}
        self.roots, self.edges, self.visited, self.active = set(), set(), set(), set()
        self.reasons, self.nodes, self.cache_bytes = {}, 0, 0
        self.previous_cache = prior_index.get("parse_cache", {}) if isinstance(prior_index, dict) else {}
        if not isinstance(self.previous_cache, dict) or len(self.previous_cache) > 4096:
            self.previous_cache = {}
        self.optional_paths = frozenset()

    def block(self, message):
        if len(self.result["blockers"]) < 100:
            message = str(message)[:1000]
            if message not in self.result["blockers"]:
                self.result["blockers"].append(message)

    def attempt(self, operation, label):
        try:
            return operation()
        except (ValueError, OSError, KeyError, TypeError, AttributeError, RecursionError) as error:
            self.block(label + ": " + str(error))
            return None

    def cached(self, digest):
        item = self.previous_cache.get(digest)
        if not isinstance(item, dict) or set(item) != {"encoding", "value"}:
            return None
        try:
            raw = _encoded(item["value"], item["encoding"])
            # The decoded value itself must reproduce the original bytes/hash;
            # a forged edge list or claimed source hash is never a cache hit.
            if len(raw) <= MAX_CACHE_DOCUMENT_BYTES and hashlib.sha256(raw).hexdigest() == digest:
                self.result["statistics"]["parse_cache_hits"] += 1
                self.save_cache(digest, item["value"], raw)
                return deepcopy(item["value"])
        except (ValueError, TypeError, RecursionError):
            pass
        return None

    def save_cache(self, digest, document, raw):
        if len(raw) > MAX_CACHE_DOCUMENT_BYTES or digest in self.result["parse_cache"]:
            return
        for encoding in ("sorted_indent2", "sorted_default", "sorted_compact"):
            if _encoded(document, encoding) == raw:
                item = {"encoding": encoding, "value": deepcopy(document)}
                size = len(_canonical(item))
                if self.cache_bytes + size <= MAX_CACHE_BYTES:
                    self.result["parse_cache"][digest] = item
                    self.cache_bytes += size
                break

    def parse(self, raw):
        self.result["statistics"]["metadata_bytes"] += len(raw)
        if self.result["statistics"]["metadata_bytes"] > MAX_TOTAL_METADATA_BYTES:
            raise EvidenceError("combined dependency metadata exceeds byte allowance")
        digest = hashlib.sha256(raw).hexdigest()
        cached = self.cached(digest)
        if cached is not None:
            return cached
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(EvidenceError("non-finite JSON dependency")))
        self.result["statistics"]["json_parses"] += 1
        self.save_cache(digest, document, raw)
        return document

    def local_document(self, relative, expected=None):
        if relative in self.documents:
            if expected is not None and self.result["inputs"][relative]["sha256"] != _hash(expected):
                raise EvidenceError("conflicting local dependency identity: " + relative)
            return self.documents[relative]
        raw = _read(_path(self.project, relative))
        digest = hashlib.sha256(raw).hexdigest()
        if expected is not None and digest != _hash(expected):
            raise EvidenceError("changed local dependency: " + relative)
        document = self.parse(raw)
        self.result["inputs"][relative] = {"sha256": digest, "size": len(raw)}
        self.documents[relative] = document
        return document

    def remember_overlay(self, record):
        if not isinstance(record, dict) or "snapshot_root" not in record or "files" not in record:
            return
        root, files = safe_relative(record["snapshot_root"]), record["files"]
        if not root.startswith(HISTORY + "/") or not isinstance(files, dict):
            raise EvidenceError("unsupported historical snapshot membership")
        for logical, reference in files.items():
            safe_relative(logical)
            if (not isinstance(reference, dict) or set(reference) != {"path", "content_hash"}
                    or reference["path"] != root + "/" + logical):
                raise EvidenceError("changed historical snapshot member identity")
            _hash(reference["content_hash"])
        self.overlays[root] = files
        manifest_ref = record.get("manifest_ref")
        if isinstance(manifest_ref, dict) and isinstance(manifest_ref.get("path"), str):
            self.overlays[manifest_ref["path"]] = files

    def remember_sources(self, record):
        if not isinstance(record, dict) or record.get("event") != "unit_source_archive_index":
            return
        required = {"event", "version", "records"}
        if (record.get("version") != 1 or not isinstance(record.get("records"), list)
                or not required <= set(record) <= required | {"objects", "encoding", "view_strategy"}
                or record.get("encoding", "inline") not in ("inline", "sha_objects_v1")
                or record.get("view_strategy", "private_copy") not in ("private_copy", "shared_cache_links")):
            raise EvidenceError("unsupported source archive dependency index")
        objects = record.get("objects", {})
        compact = record.get("encoding") == "sha_objects_v1"
        if (not isinstance(objects, dict) or compact != ("objects" in record)
                or len(record["records"]) > MAX_FILES):
            raise EvidenceError("source archive objects/membership is invalid")
        used_objects, seen_roots = set(), set()
        for entry in record["records"]:
            if (not isinstance(entry, dict) or set(entry) != {"record_ref", "snapshot_root", "sources"}
                    or not isinstance(entry.get("sources"), list)):
                raise EvidenceError("source archive mappings are missing")
            original = self.local_document(entry["record_ref"]["path"], entry["record_ref"]["content_hash"])
            self.remember_overlay(original)
            root = safe_relative(entry["snapshot_root"])
            if root != original.get("snapshot_root") or root in seen_roots:
                raise EvidenceError("source archive original snapshot identity differs")
            seen_roots.add(root)
            originals = {ref["path"]: ref for ref in original["files"].values()}
            mapped_paths = set()
            for source in entry["sources"]:
                expected_keys = {"path", "content_hash", "object_key"} if compact else {"path", "content_hash", "evidence_ref"}
                if not isinstance(source, dict) or set(source) != expected_keys:
                    raise EvidenceError("unsupported source archive member")
                relative = safe_relative(source["path"])
                reference = objects.get(source.get("object_key")) if "object_key" in source else source.get("evidence_ref")
                validate_reference(reference)
                if (relative in mapped_paths or originals.get(relative) != {key: source[key] for key in ("path", "content_hash")}
                        or reference["schema"] != "evidence-bytes-v1"
                        or _hash(source["content_hash"]) != reference["sha256"]):
                    raise EvidenceError("source archive content identity differs")
                mapped_paths.add(relative)
                if compact:
                    key = source["object_key"]
                    if key != reference["sha256"]:
                        raise EvidenceError("source archive object key differs")
                    used_objects.add(key)
                previous = self.source_mappings.get(relative)
                if previous is not None and not same_reference(previous, reference):
                    raise EvidenceError("conflicting source archive mappings: " + relative)
                self.source_mappings[relative] = reference
            if (compact or record.get("view_strategy") == "shared_cache_links") and mapped_paths != set(originals):
                raise EvidenceError("complete source archive membership required")
        if used_objects != set(objects):
            raise EvidenceError("unused source archive objects are ambiguous")

    def edge(self, origin, target, reason):
        self.edges.add((origin, target, reason))
        if len(self.edges) > MAX_FILES:
            raise EvidenceError("dependency edges exceed metadata allowance")

    def managed(self, reference, origin, overlay, *, json_hint=False, depth=0):
        if depth > MAX_DEPTH or len(self.roots) > MAX_FILES:
            raise EvidenceError("managed dependency closure exceeds metadata allowance")
        validate_reference(reference)
        ident = reference["artifact_id"]
        self.roots.add(ident)
        self.reasons.setdefault(ident, set()).add(origin)
        self.edge(origin, "artifact:" + ident, "required evidence")
        current = self.catalog["refs"].get(ident)
        if current is None:
            raise EvidenceError("required evidence is absent from active catalog: " + ident)
        validate_reference(current)
        if not same_reference(current, reference):
            aliases = self.catalog.get("reference_aliases", {}).get(ident, [])
            if not isinstance(aliases, list) or not any(same_reference(alias, reference) for alias in aliases):
                raise EvidenceError("required evidence reference conflicts with catalog: " + ident)
        if current["locator"]["store_id"] != self.result["store_id"]:
            raise EvidenceError("required evidence belongs to another store: " + ident)
        marker = ("artifact", ident, id(overlay), json_hint)
        if marker in self.active:
            raise EvidenceError("cyclic evidence dependency: " + ident)
        if marker in self.visited:
            return
        self.active.add(marker)
        try:
            for dependency in current.get("dependencies", []):
                self.managed(dependency, "artifact:" + ident, overlay, depth=depth + 1)
            if current["schema"] not in ("evidence-bytes-v1", "archive-attachment-v1") or json_hint:
                document = self.cached(current["sha256"])
                if document is None:
                    if not callable(self.resolve_external):
                        raise EvidenceError("required JSON evidence has no verified resolver: " + ident)
                    payload = self.resolve_external(deepcopy(reference))
                    raw = payload if isinstance(payload, bytes) else _read(Path(payload))
                    if len(raw) != current["size"] or hashlib.sha256(raw).hexdigest() != current["sha256"]:
                        raise EvidenceError("required JSON evidence changed: " + ident)
                    self.result["statistics"]["external_json_reads"] += 1
                    document = self.parse(raw)
                if current["schema"] not in ("evidence-bytes-v1", "archive-attachment-v1"):
                    if not isinstance(document, dict):
                        raise EvidenceError("required evidence JSON must be an object: " + ident)
                    if current["schema"] == "source-inventory-v1" and (type(document.get("version")) is not int
                            or document["version"] != 1 or not isinstance(document.get("source_hashes"), dict)):
                        raise EvidenceError("unsupported source inventory dependency metadata")
                    if current["schema"] == "environment-v1" and (type(document.get("version")) is not int
                            or document["version"] != 1):
                        raise EvidenceError("unsupported environment dependency metadata")
                self.walk(document, "artifact:" + ident, overlay, depth=depth + 1)
                # A byte-schema source snapshot can be JSON because of its
                # original receipt role. Preserve that interpretation by exact
                # immutable identity after its owning scope is retired.
                self.result["json_artifacts"][ident] = {
                    "sha256": current["sha256"], "size": current["size"]}
            else:
                self.result["statistics"]["opaque_evidence_leaves"] += 1
            self.visited.add(marker)
        finally:
            self.active.remove(marker)

    def local_reference(self, reference, origin, overlay, *, membership=False, json_hint=False, depth=0):
        relative, expected = safe_relative(reference["path"]), _hash(reference["content_hash"])
        # Evaluate before replacing a logical reference with its frozen path:
        # snapshot member bindings intentionally contain only path and hash.
        declared_json = _json_reference(reference, relative)
        if json_hint and reference.get("schema") in _OPAQUE_SCHEMAS:
            raise EvidenceError("JSON receipt role has an opaque evidence schema")
        json_hint = json_hint or declared_json
        if overlay is not None and relative in overlay:
            reference = overlay[relative]
            if _hash(reference["content_hash"]) != expected:
                raise EvidenceError("historical reference differs from frozen source: " + relative)
            relative = reference["path"]
        if relative in self.optional_paths:
            if membership:
                return
            raise EvidenceError("required input/proof is classified as optional: " + relative)
        self.edge(origin, "local:" + relative, "snapshot membership" if membership else "required local reference")
        source = self.source_mappings.get(relative)
        if source is not None:
            if source["sha256"] != expected:
                raise EvidenceError("source archive reference identity differs: " + relative)
            self.managed(source, "local:" + relative, overlay,
                         json_hint=json_hint, depth=depth + 1)
            return
        path = _path(self.project, relative)
        if not path.is_file():
            raise EvidenceError("missing local dependency: " + relative)
        if not json_hint:
            return  # Opaque local bytes cannot contain schema-defined evidence edges.
        document = self.local_document(relative, expected)
        self.walk_document(relative, document, overlay, depth=depth + 1)

    def walk_document(self, relative, document, overlay=None, *, depth=0):
        if relative.lower().endswith("/record.json") and relative.startswith(HISTORY + "/"):
            events = {"unit_execution_context": 2, "unit_completion": 2, "unit_attempt": 2,
                      "legacy_execution_archive": 2, "completion_applicability": 2,
                      "manifest_candidate": 2, "manifest_activation": 2, "runtime_observation": 2,
                      "sealed_check": 1, "external_check_observations": 1,
                      "reviewed_unit_acceptance": 1, "external_runtime_observation": 1,
                      "unit_source_archive_index": 1, "unit_source_view": 1,
                      "optional_diagnostic_review": 1}
            if (not isinstance(document, dict) or document.get("event") not in events
                    or type(document.get("version")) is not int
                    or document["version"] != events[document["event"]]):
                raise EvidenceError("unsupported retained history record: " + relative)
        selected = self.overlays.get(relative, overlay)
        marker = ("local", relative, id(selected))
        if marker in self.visited:
            return
        if marker in self.active:
            return  # The first traversal still visits every sibling edge.
        self.active.add(marker)
        try:
            self.walk(document, "local:" + relative, selected, depth=depth + 1)
            self.visited.add(marker)
        finally:
            self.active.remove(marker)

    def declared_path(self, relative, origin, overlay, *, depth):
        """Read declared existing JSON sources; planned absent paths are leaves."""
        if depth > MAX_DEPTH:
            raise EvidenceError("declared source traversal exceeds depth allowance")
        if not isinstance(relative, str):
            return
        try:
            safe_relative(relative)
        except ValueError:
            return  # Incidental URLs/observed machine paths are not project refs.
        if overlay is not None and relative in overlay:
            self.local_reference(overlay[relative], origin, overlay, depth=depth + 1)
            return
        if overlay is not None:
            descendants = [reference for logical, reference in overlay.items()
                           if logical.startswith(relative.rstrip("/") + "/")]
            if descendants:
                for reference in descendants:
                    self.local_reference(reference, origin, overlay, depth=depth + 1)
                return
        if relative in self.optional_paths:
            raise EvidenceError("required input/proof is classified as optional: " + relative)
        try:
            path = _path(self.project, relative)
        except FileNotFoundError:
            return
        if not path.exists():
            return
        if path.is_dir():
            if relative == HISTORY or relative.startswith(HISTORY + "/"):
                return  # Exact retained history traversal owns these directories.
            names = sorted(child.name for child in path.iterdir())
            self.result["directory_membership"][relative] = names
            if len(self.result["directory_membership"]) > MAX_FILES:
                raise EvidenceError("declared source directories exceed allowance")
            for name in names:
                self.declared_path(relative + "/" + name, origin, overlay, depth=depth + 1)
        elif path.suffix.lower() == ".json":
            self.edge(origin, "local:" + relative, "declared JSON source")
            self.walk_document(relative, self.local_document(relative), overlay, depth=depth + 1)

    def walk(self, value, origin, overlay=None, *, json_hint=False, depth=0):
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            raise EvidenceError("dependency traversal exceeds bounded metadata allowance")
        if isinstance(value, list):
            for item in value:
                self.walk(item, origin, overlay, json_hint=json_hint, depth=depth + 1)
            return
        if not isinstance(value, dict):
            return
        external = evidence_reference(value)
        if external is not None:
            if json_hint and external.get("schema") in _OPAQUE_SCHEMAS:
                raise EvidenceError("JSON receipt role has an opaque evidence schema")
            self.managed(external, origin, overlay, depth=depth + 1)
            if external is value:
                return
            value = {key: child for key, child in value.items() if key != "evidence_ref"}
        if isinstance(value.get("path"), str) and "content_hash" in value:
            self.local_reference(value, origin, overlay, json_hint=json_hint, depth=depth + 1)
            json_hint = False
            value = {key: child for key, child in value.items() if key not in ("path", "content_hash")}
        event = value.get("event")
        if event == "optional_diagnostic_review":
            # Member hashes describe intentionally retained *metadata*, not a
            # fresh requirement to preserve the optional member's payload.
            for member in value.get("members", []):
                self.local_reference(member["record_ref"], origin, overlay, depth=depth + 1)
            return
        if event == "unit_source_archive_index":
            self.remember_sources(value)
            for entry in value["records"]:
                self.local_reference(entry["record_ref"], origin, overlay, depth=depth + 1)
                for source in entry["sources"]:
                    relative = source["path"]
                    if relative not in self.optional_paths:
                        self.managed(self.source_mappings[relative], "local:" + relative,
                                     self.overlays.get(entry["snapshot_root"], overlay),
                                     json_hint=Path(relative).suffix.lower() == ".json", depth=depth + 1)
            return
        if "snapshot_root" in value and "files" in value:
            self.remember_overlay(value)
            overlay = value["files"]
            omitted = self.retirement.members(value) if self.retirement is not None else frozenset()
            for logical, reference in overlay.items():
                if logical not in omitted:
                    self.local_reference(reference, origin, overlay, membership=True, depth=depth + 1)
            value = {key: child for key, child in value.items() if key != "files"}
        for key, child in value.items():
            # Unlike execution-scoped traversal, inactive history is included.
            if key in ("source_hashes", "evaluated_source_hashes") and isinstance(child, dict):
                for relative, digest in child.items():
                    self.local_reference({"path": relative, "content_hash": digest}, origin, overlay, depth=depth + 1)
            elif key in ("implementation_paths", "required_source_paths", "render_dependencies") and isinstance(child, list):
                for relative in child:
                    self.declared_path(relative, origin, overlay, depth=depth + 1)
            elif isinstance(child, str) and (key in ("path", "source", "destination")
                    or key.endswith("_path") or key.endswith("_root")):
                self.declared_path(child, origin, overlay, depth=depth + 1)
            role_json = (key in _JSON_ROLES or key.endswith("_receipt") or key.endswith("_ref")
                         or event == "manifest_activation" and key in ("before", "after"))
            self.walk(child, origin, overlay, json_hint=json_hint or role_json, depth=depth + 1)

    def run(self):
        manifest = self.attempt(lambda: self.local_document(self.result["manifest_path"]), "manifest")
        if not isinstance(manifest, dict):
            self.block("current manifest must be an object")
            return self.finish()
        for key in ("unit_contract_version", "checker_contract_version"):
            if key in manifest and (type(manifest[key]) is not int or manifest[key] not in (1, 2, 3, 4)):
                self.block("unsupported manifest contract: " + key)
        requested_retirement, self.retirement = self.retirement, None
        def review():
            from .diagnostics import OptionalReview, load_review
            loaded = load_review(self.project, manifest)
            if requested_retirement is not None:
                if not isinstance(requested_retirement, OptionalReview) or loaded is None:
                    raise EvidenceError("retirement must be the validated current diagnostic review")
                if requested_retirement.project != self.project or requested_retirement.record != loaded.record:
                    raise EvidenceError("retirement differs from current diagnostic review")
            self.retirement = loaded
            self.optional_paths = loaded.optional_paths if loaded is not None else frozenset()
        self.attempt(review, "optional diagnostics")
        listing = self.attempt(lambda: _history_membership(self.project), "history membership")
        documents = []
        if listing is not None:
            self.result["history_membership"], documents = listing
        for relative in documents:
            document = self.attempt(lambda relative=relative: self.local_document(relative), "history " + relative)
            if document is not None:
                self.attempt(lambda document=document: self.remember_overlay(document), "snapshot metadata")
                self.attempt(lambda document=document: self.remember_sources(document), "source archive metadata")
        source_index = manifest.get("source_archive_index_ref")
        if isinstance(source_index, dict):
            self.attempt(lambda: self.remember_sources(self.local_document(
                source_index["path"], source_index["content_hash"])), "current source archive index")
        self.attempt(lambda: self.walk_document(self.result["manifest_path"], manifest), "current dependencies")
        for relative in documents:
            if relative in self.documents:
                self.attempt(lambda relative=relative: self.walk_document(relative, self.documents[relative]),
                             "historical dependencies " + relative)
        if self.retirement is not None:
            self.attempt(self.retirement.audit, "optional diagnostic review changed")
        self.attempt(lambda: assert_unchanged(self.project, self.finish(), allow_blockers=True), "discovery changed")
        return self.finish()

    def finish(self):
        self.result["roots"] = sorted(self.roots)
        self.result["edges"] = [{"from": source, "to": target, "reason": reason}
                                for source, target, reason in sorted(self.edges)]
        self.result["reasons"] = {ident: sorted(reasons) for ident, reasons in sorted(self.reasons.items())}
        self.result["json_artifacts"] = dict(sorted(self.result["json_artifacts"].items()))
        self.result["blockers"] = sorted(self.result["blockers"])
        self.result["statistics"]["nodes"] = self.nodes
        self.result["digest"] = inventory_digest(self.result)
        if len(_canonical(self.result)) > MAX_TOTAL_METADATA_BYTES:
            raise EvidenceError("dependency inventory exceeds metadata allowance")
        return self.result


def collect_project(project, *, manifest_path="forge/sdd-manifest.json", catalog,
                    resolve_external, prior_index=None, retirement=None):
    """Collect a fresh bounded inventory; incomplete discovery retains evidence.

    ``resolve_external`` returns independently prepared original bytes or a
    regular path. It is invoked only when JSON bytes are needed for discovery;
    binary proof is retained by its catalog identity without downloading it.
    ``prior_index`` supplies only hash-verifiable parsed JSON, never roots or a
    prior completeness assertion. This function performs no writes/network I/O.
    ``json_artifacts`` binds successfully decoded JSON to its immutable bytes;
    it is derived dependency metadata, not evidence of test acceptance.
    """
    return _Collector(project, manifest_path, catalog, resolve_external, prior_index, retirement).run()


def assert_unchanged(project, inventory, *, allow_blockers=False):
    """Recheck a newly collected inventory's local inputs, not its authority.

    The coordinator still must recheck complete participant/catalog revisions.
    This function does not turn an arbitrary supplied inventory into a complete
    dependency discovery and must not replace ``collect_project`` at planning.
    """
    root = Path(project).resolve(strict=True)
    if (not isinstance(inventory, dict) or inventory.get("version") != 1
            or inventory.get("digest") != inventory_digest(inventory)):
        raise EvidenceError("dependency inventory identity is invalid")
    if inventory.get("blockers") and not allow_blockers:
        raise EvidenceError("dependency discovery is incomplete: " + "; ".join(inventory["blockers"][:3]))
    inputs = inventory.get("inputs")
    if not isinstance(inputs, dict) or len(inputs) > MAX_FILES:
        raise EvidenceError("dependency inventory input membership is invalid")
    for relative, previous in inputs.items():
        raw = _read(_path(root, relative))
        if not isinstance(previous, dict) or previous != {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}:
            raise EvidenceError("dependency input changed: " + relative)
    current, _ = _history_membership(root)
    if current != inventory.get("history_membership"):
        raise EvidenceError("history membership changed after discovery")
    for relative, names in inventory.get("directory_membership", {}).items():
        path = _path(root, relative)
        if not path.is_dir() or sorted(child.name for child in path.iterdir()) != names:
            raise EvidenceError("declared source membership changed after discovery: " + relative)
