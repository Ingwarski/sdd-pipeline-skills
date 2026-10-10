"""Read-only resolution of prepared evidence. No transport, writes or extraction."""
from datetime import datetime
from pathlib import Path, PurePosixPath
import re
import stat
import os
import hashlib
import sys

from .io import hash_file, read_json, safe_relative, _parents, _open_regular, _verify_stable
from .identity import same_reference

SCHEMAS = frozenset({"evidence-bytes-v1", "evidence-json-v1", "source-inventory-v1",
                     "environment-v1", "sdd-receipt-v1", "sdd-result-v1", "archive-attachment-v1"})
HASH = re.compile(r"[0-9a-f]{64}")
IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")
JSON_LIMIT = 16 * 1024 * 1024


def evidence_reference(record):
    """Direct references and a named evidence_ref wrapper are both portable."""
    if isinstance(record, dict):
        if "evidence_ref" in record:
            return record["evidence_ref"]
        if "artifact_id" in record or "locator" in record or "version" in record and "sha256" in record:
            return record
    return None


def _regular(path):
    try:
        if sys.platform == "win32":
            # Windows path ctime can mean creation time. A descriptor supplies
            # the metadata-change clock required to invalidate hash/JSON memos
            # after equal-size edits whose modification time was restored.
            path, descriptor, info = _open_regular(path)
            try:
                _verify_stable(path, descriptor, info)
            finally:
                os.close(descriptor)
        else:
            _parents(path)
            info = path.lstat()
    except OSError as error:
        raise ValueError("prepared evidence missing/unreadable: " + str(path)) from error
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("prepared evidence must be a real regular file: " + str(path))
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _hash(value, label):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError(label + ": lowercase SHA-256 required")


def _size(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(label + ": nonnegative integer required")


def _member(value):
    try:
        safe_relative(value)
    except ValueError as error:
        raise ValueError("unsafe archive member: " + str(value)) from error


def validate_reference(ref):
    if not isinstance(ref, dict) or type(ref.get("version")) is not int or ref["version"] != 1:
        raise ValueError("unsupported evidence reference version")
    if not isinstance(ref.get("artifact_id"), str) or not IDENTITY.fullmatch(ref["artifact_id"]):
        raise ValueError("invalid evidence artifact identity")
    _hash(ref.get("sha256"), "original content")
    _size(ref.get("size"), "original size")
    if not isinstance(ref.get("kind"), str) or not ref["kind"]:
        raise ValueError("evidence kind required")
    if ref.get("schema") not in SCHEMAS:
        raise ValueError("unsupported evidence schema: " + str(ref.get("schema")))
    if not isinstance(ref.get("provenance"), dict) or not ref["provenance"]:
        raise ValueError("original evidence provenance required")
    if not isinstance(ref.get("bindings"), dict):
        raise ValueError("evidence bindings must be an object")
    locator = ref.get("locator")
    if not isinstance(locator, dict) or not isinstance(locator.get("store_id"), str) or not IDENTITY.fullmatch(locator["store_id"]):
        raise ValueError("stable storage identity required")
    if locator.get("provider") not in ("local", "managed_local", "folder", "google_drive", "google-drive", "rclone", "connected_drive"):
        raise ValueError("unsupported evidence provider")
    segments = locator.get("segments")
    objects = segments if segments is not None else [locator]
    if not isinstance(objects, list) or not objects or len(objects) > 10000:
        raise ValueError("bounded nonempty archive locator required")
    offset = 0
    for item in objects:
        if not isinstance(item, dict) or not isinstance(item.get("object_id"), str) or not item["object_id"] or "\x00" in item["object_id"]:
            raise ValueError("stable archive object identity required")
        _hash(item.get("pack_sha256"), "archive hash")
        _size(item.get("pack_size"), "archive size")
        _member(item.get("member"))
        if segments is not None:
            _size(item.get("offset"), "segment offset")
            _size(item.get("length"), "segment length")
            _hash(item.get("sha256"), "segment content")
            if item["offset"] != offset or item["length"] == 0:
                raise ValueError("split evidence must cover original bytes contiguously")
            offset += item["length"]
    if segments is not None and offset != ref["size"]:
        raise ValueError("split evidence size differs from original")
    retention = ref.get("retention")
    if not isinstance(retention, dict) or not isinstance(retention.get("class"), str) or not retention["class"]:
        raise ValueError("retention classification required")
    try:
        sealed = datetime.fromisoformat(retention["sealed_at"].replace("Z", "+00:00"))
        if sealed.tzinfo is None:
            raise ValueError("timezone required")
    except (KeyError, AttributeError, TypeError, ValueError) as error:
        raise ValueError("original sealing time with timezone required") from error
    dependencies = ref.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ValueError("evidence reference dependencies must be a list")
    return ref


class EvidenceResolver:
    """Prepared original bytes plus verified readback receipts, bounded per invocation."""
    def __init__(self, cache_path=None):
        self.cache = Path(cache_path).absolute() if cache_path is not None else None
        # macOS exposes its actual user temp directory through a system /var alias.
        # Normalize only those OS aliases, retaining all task-selected links for rejection.
        if self.cache is not None and sys.platform == "darwin" and len(self.cache.parts) > 1 and self.cache.parts[1] in ("var", "tmp"):
            alias = Path("/") / self.cache.parts[1]
            canonical = Path("/private") / self.cache.parts[1]
            if alias.is_symlink() and alias.resolve() == canonical:
                self.cache = canonical.joinpath(*self.cache.parts[2:])
        self.hashes, self.documents, self.segment_hashes = {}, {}, {}
        self.references = {}
        self.metadata_limit, self.closure_limit, self.json_bytes = 128 * 1024 * 1024, 10000, 0
        self.active = set()
        self.visited, self.resolved_paths = set(), {}

    def _path(self, category, name):
        if self.cache is None:
            raise ValueError("evidence preparation required: pass --evidence-cache outside the repository")
        current = self.cache
        for component in (category, name):
            if current.exists() and (current.is_symlink() or getattr(current.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ValueError("prepared evidence cache contains a link/reparse point")
            current /= component
        _regular(current)
        return current

    def _json(self, path):
        before = _regular(path)
        if path not in self.documents:
            if self.json_bytes + before[2] > self.metadata_limit:
                raise ValueError("combined prepared metadata exceeds validation allowance")
            self.documents[path] = (before, read_json(path, min(JSON_LIMIT, self.metadata_limit)))
            self.json_bytes += before[2]
        saved, value = self.documents[path]
        if before != saved or _regular(path) != saved:
            raise ValueError("prepared evidence changed during validation: " + str(path))
        return value

    def resolve(self, ref):
        root = not self.active
        if root:
            self.visited.clear()
        path = self._resolve(ref)
        if root:
            # A shared DAG is visited once, then all its prepared inputs are rechecked.
            for key in self.visited:
                original = self.resolved_paths[key]
                if _regular(original) != self.hashes[original][0]:
                    raise ValueError("prepared evidence changed during validation: " + key)
                receipt = self._path("receipts", key + ".json")
                if _regular(receipt) != self.documents[receipt][0]:
                    raise ValueError("prepared receipt changed during validation: " + key)
        return path

    def _resolve(self, ref):
        validate_reference(ref)
        key = ref["artifact_id"]
        if key in self.active:
            raise ValueError("cyclic evidence reference closure")
        if key in self.references and not same_reference(self.references[key], ref):
            raise ValueError("artifact identity refers to conflicting evidence")
        if len(self.active) >= 32 or len(self.references) >= self.closure_limit and key not in self.references:
            raise ValueError("evidence reference closure exceeds validation bounds")
        self.references[key] = ref
        if key in self.visited:
            return self.resolved_paths[key]
        self.active.add(key)
        try:
            receipt = self._json(self._path("receipts", key + ".json"))
            if not isinstance(receipt, dict) or not same_reference({k: v for k, v in receipt.items() if k != "verified_archive"}, ref):
                raise ValueError("prepared receipt identity/reference mismatch: " + key)
            archive = receipt.get("verified_archive")
            archives = archive if isinstance(archive, list) else [archive]
            locator = ref["locator"]
            segments = locator.get("segments")
            locators = segments if segments is not None else [locator]
            for item in locators:
                match = [entry for entry in archives if isinstance(entry, dict) and entry.get("sha256") == item["pack_sha256"] and entry.get("size") == item["pack_size"] and entry.get("object_id") == item["object_id"]]
                if len(match) != 1:
                    raise ValueError("missing verified archive closure: " + key)
                members = match[0].get("members")
                if not isinstance(members, list) or len({x.get("member") for x in members if isinstance(x, dict)}) != len(members):
                    raise ValueError("invalid or duplicate verified archive member closure")
                expected = {"artifact_id": key, "member": item["member"], "sha256": item["sha256"] if segments is not None else ref["sha256"], "size": item["length"] if segments is not None else ref["size"]}
                original = [member for member in members if isinstance(member, dict) and
                    all(member.get(field) == expected[field] for field in ("member", "sha256", "size")) and
                    (member.get("artifact_id") == key or key in member.get("artifact_ids", []))]
                if len(original) != 1:
                    raise ValueError("missing verified original member closure: " + key)
            path = self._path("objects", ref["sha256"])
            before = _regular(path)
            if path not in self.hashes:
                self.hashes[path] = (before, hash_file(path))
            saved, actual = self.hashes[path]
            if before != saved or _regular(path) != saved:
                raise ValueError("prepared evidence changed during validation: " + key)
            if actual != (ref["sha256"], ref["size"]):
                raise ValueError("prepared original bytes hash/size mismatch: " + key)
            segment_key = (path, tuple((segment["offset"], segment["length"], segment["sha256"]) for segment in segments)) if segments is not None else None
            if segments is not None and segment_key not in self.segment_hashes:
                path, descriptor, descriptor_info = _open_regular(path)
                try:
                    signature = (descriptor_info.st_dev, descriptor_info.st_ino, descriptor_info.st_size,
                                 descriptor_info.st_mtime_ns, descriptor_info.st_ctime_ns)
                    if not stat.S_ISREG(descriptor_info.st_mode) or signature != saved:
                        raise ValueError("split evidence changed while opening")
                    for segment in segments:
                        remaining, digest = segment["length"], hashlib.sha256()
                        while remaining:
                            block = os.read(descriptor, min(1024 * 1024, remaining))
                            if not block:
                                raise ValueError("split evidence truncated during validation")
                            digest.update(block)
                            remaining -= len(block)
                        if digest.hexdigest() != segment["sha256"]:
                            raise ValueError("split evidence segment bytes mismatch")
                    _verify_stable(path, descriptor, descriptor_info)
                    if _regular(path) != saved:
                        raise ValueError("split evidence changed during validation")
                    self.segment_hashes[segment_key] = saved
                finally:
                    os.close(descriptor)
            for dependency in ref.get("dependencies", []):
                self.resolve(dependency)
            if ref["schema"] not in ("evidence-bytes-v1", "archive-attachment-v1"):
                self._validate_payload(ref, self._json(path))
            self.resolved_paths[key] = path
            self.visited.add(key)
            return path
        finally:
            self.active.remove(key)

    def _validate_payload(self, ref, value):
        if not isinstance(value, dict):
            raise ValueError("evidence JSON payload must be an object")
        if ref["schema"] == "source-inventory-v1":
            if type(value.get("version")) is not int or value["version"] != 1 or not isinstance(value.get("source_hashes"), dict):
                raise ValueError("unsupported source inventory schema")
        elif ref["schema"] == "environment-v1" and (type(value.get("version")) is not int or value["version"] != 1):
            raise ValueError("unsupported environment schema")
        visited = 0
        def closure(record, depth=0):
            nonlocal visited
            visited += 1
            if depth > 64 or visited > 1000000:
                raise ValueError("JSON evidence reference closure exceeds validation bounds")
            if isinstance(record, dict):
                nested = evidence_reference(record)
                if nested is not None:
                    self.resolve(nested)
                for key, child in record.items():
                    # Sibling captures remain required even when this object wraps a ref.
                    # Superseded payloads are resolved when a current claim needs them.
                    if key not in ("evidence_ref", "history", "run_history", "superseded"):
                        closure(child, depth + 1)
            elif isinstance(record, list):
                for child in record:
                    closure(child, depth + 1)
        closure(value)
        return value

    def json(self, ref):
        if ref.get("schema") not in SCHEMAS - {"evidence-bytes-v1", "archive-attachment-v1"}:
            raise ValueError("evidence schema is not a JSON record")
        return self._json(self.resolve(ref))

    @staticmethod
    def validate_bindings(ref, expected):
        for key, value in expected.items():
            if key not in ref["bindings"] or ref["bindings"][key] != value:
                raise ValueError("stale or missing evidence binding: " + key)
