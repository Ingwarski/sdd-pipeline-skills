"""Read-only, per-operation classification of proved source-view payload paths.

This grants no acceptance, retention exception or quota refund. Manager still
counts all physical occupancy and logical membership; only exact payload aliases
are distinguished from control JSON. No project context means no exemptions.
"""
from copy import deepcopy
from pathlib import Path
import re

from . import policy as policies
from .io import EvidenceError, hash_file
from .resolver import EvidenceResolver, JSON_LIMIT, _regular


class _ControlResolver(EvidenceResolver):
    """The ordinary resolver, with one additional aggregate control-file bound."""
    def _json(self, path, maximum=JSON_LIMIT):
        path = Path(path)
        if path not in self.documents and len(self.documents) >= self.closure_limit:
            raise EvidenceError("source payload control-file allowance exhausted")
        return super()._json(path, maximum)


class SourcePayloadScope:
    def __init__(self, project, cache, policy):
        # Import the actual sibling history decoder, not a parallel descriptor
        # implementation. It performs no writes or transport calls at import.
        import sdd_history as history
        self.history = history
        self._policy_input = policy
        self.policy = policies.validate_policy(deepcopy(policy))
        self.resolver = _ControlResolver(cache)
        self.resolver.metadata_limit = self.policy["limits"]["metadata_stop_bytes"]
        self.resolver.closure_limit = self.policy["limits"]["metadata_stop_files"]
        self.cache = self.resolver.cache
        self.project = Path(project).resolve() if project is not None else None
        self.manifest, self.archives, self.controls, self.aliases = {}, {}, {}, {}
        self._eligible = False
        if self.project is None or not self.project.is_dir():
            return
        manifest_path = history.physical(self.project, "forge/sdd-manifest.json")
        if manifest_path.exists():
            self.manifest = self.resolver._json(manifest_path, history.SOURCE_INDEX_MAX_BYTES)
            history.require(isinstance(self.manifest, dict), "source payload project manifest must be an object")
        storage = self.manifest.get("evidence_storage", {})
        history.require(isinstance(storage, dict), "source payload storage declaration must be an object")
        policy_path = history.physical(self.project, storage.get("policy_path", "forge/evidence-policy.json"))
        if not policy_path.exists() and not policy_path.is_symlink():
            return  # Initial setup/projectless recovery remains conservative.
        checkout = policies.validate_policy(self.resolver._json(policy_path, policies.MAX_POLICY_BYTES))
        if any(checkout[key] != self.policy[key] for key in ("project_id", "store_id", "provider")):
            return
        if policies._digest(checkout) != policies._digest(self.policy):
            ancestor = policies.resolve_historical_policy(self.policy, policies._digest(checkout))
            history.require(history.same(ancestor, checkout), "source payload policy is not on the selected lineage")
            raw_hash = self._control_hash(policy_path)
            if "policy_lineage" in checkout:
                expected = history.sha(policies._setup_bytes(checkout))
            else:
                expected = self.policy["policy_lineage"]["base"]["raw_sha256"]
            history.require(raw_hash == expected, "source payload checkout raw policy differs from selected lineage")
        self._eligible = True

    def _control_hash(self, path):
        path = Path(path)
        signature = _regular(path)
        if path not in self.controls:
            self.controls[path] = (signature, hash_file(path)[0])
        saved, digest = self.controls[path]
        self.history.require(signature == saved and _regular(path) == saved,
                             "source payload control changed during operation: " + str(path))
        return digest

    def _read_ref(self, reference):
        h = self.history
        h.require(isinstance(reference, dict) and set(reference) == h.REF_KEYS,
                  "source payload native hash-bound reference required")
        path = h.physical(self.project, reference["path"])
        value = self.resolver._json(path, h.SOURCE_INDEX_MAX_BYTES)
        h.require(h.api().hash_matches(reference["content_hash"], self._control_hash(path)),
                  "source payload native metadata hash mismatch: " + reference["path"])
        return deepcopy(value)

    def _archive(self, index_ref):
        h = self.history
        h.require(isinstance(index_ref, dict) and set(index_ref) == h.REF_KEYS,
                  "source payload index reference required")
        h.require(isinstance(index_ref["path"], str) and isinstance(index_ref["content_hash"], str),
                  "source payload index path/hash must be text")
        key = (index_ref["path"], index_ref["content_hash"])
        if key not in self.archives:
            archive = h.SourceArchive(self.project, index_ref, self.cache,
                policy_manifest=self.manifest, _read_ref=self._read_ref)
            # One selected Manager admission budget across every old/new index.
            # Checkout may still be an exact limits-only predecessor.
            archive.resolver = self.resolver
            self.archives[key] = (archive, archive.expected_views())
        return self.archives[key]

    def payload_paths(self, candidate_json_paths):
        try:
            return self._payload_paths(candidate_json_paths)
        except (KeyError, TypeError, AttributeError, RecursionError) as error:
            raise EvidenceError("malformed source payload proof") from error

    def _payload_paths(self, candidate_json_paths):
        if not self._eligible:
            return set()
        self._audit_inputs()
        h = self.history
        groups, candidates = {}, set()
        for candidate in candidate_json_paths:
            path = Path(candidate).absolute()
            try:
                relative = path.relative_to(self.cache)
            except ValueError:
                continue
            parts = relative.parts
            if (len(parts) < 5 or parts[0] != "source-views" or parts[2] != "views"
                    or not re.fullmatch(r"[0-9a-f]{64}", parts[1])
                    or not re.fullmatch(r"[0-9a-f]{64}", parts[3])):
                continue  # Unknown paths always retain conservative metadata role.
            if parts[4] != "receipt.json" and (parts[4] != "files" or len(parts) < 6):
                continue
            candidates.add(path)
            groups[(parts[1], parts[3])] = self.cache / Path(*parts[:4])
        proved = set()
        for (index_hash, descriptor_hash), directory in sorted(groups.items()):
            receipt = self.resolver._json(directory / "receipt.json")
            h.require(isinstance(receipt, dict), "source payload view receipt must be an object")
            index_ref = receipt.get("index_ref")
            h.require(isinstance(index_ref, dict) and index_ref.get("content_hash") == index_hash,
                      "source payload index directory/reference mismatch")
            archive, expected = self._archive(index_ref)
            h.require(descriptor_hash in expected, "source payload view is not a complete supported original descriptor")
            root, files = expected[descriptor_hash]  # Never trust receipt.view.files.
            tree = archive.validate_view(root, files, force=True)
            h.require(tree.parent == directory, "source payload view directory/descriptor mismatch")
            for logical, frozen in files.items():
                source = archive.sources.get(frozen["path"])
                if source is None:
                    continue  # Unmapped private inputs have no ordinary payload exemption.
                reference = source["evidence_ref"]
                canonical = self.resolver.references[reference["artifact_id"]]
                h.require(canonical["schema"] == "evidence-bytes-v1"
                          and canonical["locator"]["store_id"] == self.policy["store_id"],
                          "source payload ordinary reference belongs to another store/schema")
                alias = tree / logical
                signature = _regular(alias)
                if alias in self.aliases:
                    h.require(self.aliases[alias] == signature, "source payload alias changed during operation")
                self.aliases[alias] = signature
                if alias in candidates:
                    proved.add(alias)
        self._audit_inputs()
        return proved

    def _audit_inputs(self):
        h = self.history
        h.require(h.same(policies.validate_policy(self._policy_input), self.policy),
                  "source payload selected policy changed during operation")
        for cache in (self.resolver.hashes, self.resolver.documents, self.controls):
            for path, (signature, _) in cache.items():
                h.require(_regular(path) == signature, "source payload proof input changed during operation: " + str(path))
        for path, signature in self.aliases.items():
            h.require(_regular(path) == signature, "source payload alias changed during operation: " + str(path))

    def audit(self):
        self._audit_inputs()
        for archive, _ in self.archives.values():
            archive.audit()
        self._audit_inputs()

    def control_paths(self):
        """Exact consumed proof controls; no parsing, mutation or fresh discovery.

        Manager combines these with its existing control records, so native
        metadata outside its state directory remains subject to admission.
        The retained signatures are checked by every repeatable audit().
        """
        return set(self.resolver.documents) | set(self.controls)
