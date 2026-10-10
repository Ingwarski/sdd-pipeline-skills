"""Generic opaque attachments retain restoration data; no Git restoration is executed."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/to-sdd-pipeline/scripts"))
from evidence.archive import build_pack
from evidence.importer import normalize
from evidence.io import EvidenceError, hash_file
from evidence.manager import Manager
from evidence.policy import load_defaults
from evidence.resolver import EvidenceResolver
from evidence.transports import LocalTransport

SEALED = "2026-01-01T12:00:00Z"
VERIFIED = "2026-01-02T08:30:00Z"


class RecordingLocalTransport(LocalTransport):
    def __init__(self, root):
        super().__init__(root)
        self.puts = []

    def put(self, key, source_path):
        result = super().put(key, source_path)
        self.puts.append(key)
        return result


class EvidenceImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-import-metadata-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.policy = load_defaults()
        self.policy.update(project_id="11111111-1111-4111-8111-111111111111", store_id="22222222-2222-4222-8222-222222222222", provider="local")
        self.policy["limits"]["free_space_reserve_bytes"] = 0
        self.transport = RecordingLocalTransport(self.base / "durable")
        self.manager = Manager(self.transport, self.base / "machine", self.policy)
        self.payload = b"Opaque synthetic Git recovery attachment bytes. No real repository contents.\n"
        self.original = self.base / "synthetic.bundle"
        self.original.write_bytes(self.payload)
        digest, size = hash_file(self.original)
        packed = build_pack([{"path": self.original, "sha256": digest, "size": size}], self.base / "preexisting.zip", 1024 * 1024, 10)
        locator = self.transport.put("existing/synthetic.zip", self.base / "preexisting.zip")
        self.restoration = {"format": "git-bundle", "version": 1, "prerequisite_commits": ["a" * 40],
            "heads": {"refs/heads/synthetic": "b" * 40}, "instructions": ["Review bundle prerequisites before manual restoration."]}
        self.attachment = {"display_name": "synthetic.bundle", "media_type": "application/octet-stream", "purpose": "opaque recovery attachment"}
        self.file = {"artifact_id": "opaque-synthetic-attachment", "sha256": digest, "size": size,
            "kind": "recovery-attachment", "schema": "archive-attachment-v1", "original_path": "recovery/synthetic.bundle",
            "provenance": {"run_id": "original-synthetic-run", "unit_id": "original-synthetic-unit", "executed_at": SEALED},
            "bindings": {"original_plan_hash": "c" * 64}, "verified_at": VERIFIED,
            "retention": {"sealed_at": SEALED, "class": "recovery"},
            "restoration_metadata": deepcopy(self.restoration), "attachment_metadata": deepcopy(self.attachment),
            "parts": [{"object": "archive", "member": packed["members"][0]["member"], "offset": 0, "length": size}]}
        self.mapping = {"version": 1, "objects": {"archive": {**packed, "locator": locator}}, "files": [self.file],
            "original_catalogs": ["original/synthetic-catalog.json"]}

    def normalized(self, mapping=None):
        return normalize(mapping or self.mapping, store_id=self.policy["store_id"], provider="local")

    def test_object_table_preserves_opaque_restoration_attachment_metadata_and_dependencies(self):
        dependency = deepcopy(self.normalized()[0][0])
        dependency["artifact_id"] = "historical-dependency"
        self.file["dependencies"] = [dependency]
        original = deepcopy(self.mapping)
        refs, _ = self.normalized()
        ref = refs[0]
        self.assertEqual(self.restoration, ref["restoration_metadata"])
        self.assertEqual(self.attachment, ref["attachment_metadata"])
        self.assertEqual([dependency], ref["dependencies"])
        self.assertEqual(original, self.mapping)
        ref["restoration_metadata"]["instructions"].append("Mutating returned metadata cannot modify input.")
        ref["dependencies"][0]["bindings"]["extra"] = "changed output"
        self.assertEqual(original, self.mapping)

    def test_adoption_and_cold_catalog_restore_preserve_original_metadata_times_and_payload(self):
        original_mapping = deepcopy(self.mapping)
        existing_bytes = (self.base / "durable/existing/synthetic.zip").read_bytes()
        before = len(self.transport.puts)
        refs = self.manager.import_archive(self.mapping)
        self.assertEqual(original_mapping, self.mapping)
        self.assertTrue(all(key.endswith(".json") for key in self.transport.puts[before:]))
        self.assertEqual(existing_bytes, (self.base / "durable/existing/synthetic.zip").read_bytes())
        self.original.unlink()
        cold = Manager(RecordingLocalTransport(self.base / "durable"), self.base / "cold-machine", self.policy)
        restored_ref = cold._catalog()["refs"][refs[0]["artifact_id"]]
        self.assertEqual(self.restoration, restored_ref["restoration_metadata"])
        self.assertEqual(self.attachment, restored_ref["attachment_metadata"])
        self.assertEqual(SEALED, restored_ref["provenance"]["executed_at"])
        self.assertEqual(SEALED, restored_ref["retention"]["sealed_at"])
        self.assertEqual(VERIFIED, restored_ref["historical_verified_at"])
        self.assertTrue(restored_ref["retention"]["imported"])
        prepared = cold.prepare([restored_ref])
        self.assertEqual(self.payload, EvidenceResolver(prepared).resolve(restored_ref).read_bytes())
        paths = cold.restore([restored_ref], self.base / "cold-restoration")
        self.assertEqual(self.payload, Path(paths[0]).read_bytes())

    def test_neutral_layout_preserves_same_opaque_metadata(self):
        refs, packs = self.normalized()
        neutral = {"version": 1, "refs": refs, "packs": packs}
        copied = deepcopy(neutral)
        result, _ = self.normalized(neutral)
        self.assertEqual(refs, result)
        self.assertEqual(copied, neutral)

    def test_explicit_original_verification_timestamp_is_preserved_and_conflicts_rejected(self):
        self.file["historical_verified_at"] = VERIFIED
        self.assertEqual(VERIFIED, self.normalized()[0][0]["historical_verified_at"])
        self.file["verified_at"] = "2026-01-03T08:30:00Z"
        with self.assertRaisesRegex(EvidenceError, "conflicting original verification"):
            self.normalized()

    def test_metadata_is_descriptive_object_and_unsupported_mapping_types_fail_clearly(self):
        for field in ("restoration_metadata", "attachment_metadata"):
            mapping = deepcopy(self.mapping)
            mapping["files"][0][field] = "not an opaque metadata object"
            with self.subTest(field=field), self.assertRaisesRegex(EvidenceError, "metadata"):
                self.normalized(mapping)
        for version in (True, 2, "1"):
            mapping = {**self.mapping, "version": version}
            with self.subTest(version=version), self.assertRaisesRegex(EvidenceError, "mapping"):
                self.normalized(mapping)

    def test_invalid_unreferenced_archive_metadata_cannot_enter_catalog(self):
        for change in ({"size": True}, {"sha256": "not-a-hash"}, {"original_bytes": -1}):
            mapping = deepcopy(self.mapping)
            mapping["objects"]["extra-unreferenced"] = deepcopy(mapping["objects"]["archive"])
            mapping["objects"]["extra-unreferenced"].update(change)
            with self.subTest(change=change), self.assertRaises(EvidenceError):
                self.normalized(mapping)
        mapping = deepcopy(self.mapping)
        mapping["objects"]["archive"]["members"].append(deepcopy(mapping["objects"]["archive"]["members"][0]))
        with self.assertRaisesRegex(EvidenceError, "duplicate"):
            self.normalized(mapping)

    def test_neutral_pack_cannot_silently_replace_conflicting_original_object(self):
        refs, packs = self.normalized()
        conflicting = deepcopy(packs)
        next(iter(conflicting.values()))["locator"]["object_id"] = "different-original-object"
        mapping = {**self.mapping, "packs": conflicting}
        with self.assertRaisesRegex(EvidenceError, "conflicting imported archive"):
            self.normalized(mapping)

    def test_same_mapping_dependencies_are_adopted_without_rebinding_original_metadata(self):
        dependency_file = deepcopy(self.file)
        dependency_file["artifact_id"] = "opaque-original-prerequisite"
        dependency_file["original_path"] = "recovery/prerequisite.bundle"
        self.mapping["files"].insert(0, dependency_file)
        originals, _ = self.normalized()
        original_dependency = deepcopy(originals[0])
        original_dependency["retention"].pop("imported")
        original_dependency["retention"].pop("migration_policy_established")
        self.file["dependencies"] = [original_dependency]
        self.file["dependencies"][0]["locator"].pop("offset")
        self.file["dependencies"][0]["locator"].pop("length")
        self.file["dependencies"][0]["locator"].pop("sha256")
        before = deepcopy(self.mapping)
        refs = self.manager.import_archive(self.mapping)
        prerequisite, attachment = refs
        self.assertEqual(prerequisite, attachment["dependencies"][0])
        self.assertEqual(SEALED, prerequisite["retention"]["sealed_at"])
        self.assertEqual(VERIFIED, prerequisite["historical_verified_at"])
        self.assertEqual(before, self.mapping)
        cold = Manager(RecordingLocalTransport(self.base / "durable"), self.base / "cold-dependencies", self.policy)
        catalog = cold._catalog()
        current = catalog["refs"][attachment["artifact_id"]]
        prepared = cold.prepare([current])
        resolver = EvidenceResolver(prepared)
        self.assertEqual(self.payload, resolver.resolve(current).read_bytes())
        self.assertIn(prerequisite["artifact_id"], resolver.visited)

    def test_dependency_identity_conflicts_and_missing_schemas_fail_before_adoption(self):
        refs, _ = self.normalized()
        dependency = deepcopy(refs[0])
        dependency["artifact_id"] = "missing-external-dependency"
        dependency["schema"] = "unsupported-schema"
        self.file["dependencies"] = [dependency]
        with self.assertRaisesRegex(ValueError, "unsupported evidence schema"):
            self.normalized()
        dependency_file = deepcopy(self.file)
        dependency_file.pop("dependencies")
        dependency_file["artifact_id"] = "original-prerequisite"
        self.mapping["files"].insert(0, dependency_file)
        original_dependency = self.normalized({**self.mapping, "files": [dependency_file]})[0][0]
        original_dependency["bindings"] = {"different-plan": "e" * 64}
        self.file["dependencies"] = [original_dependency]
        with self.assertRaisesRegex(EvidenceError, "conflicts with original"):
            self.normalized()

    def test_unassociated_packs_require_explicit_logical_file_or_opaque_attachment(self):
        mapping = deepcopy(self.mapping)
        mapping["files"] = []
        with self.assertRaisesRegex(EvidenceError, "add a logical file association or an opaque attachment"):
            self.normalized(mapping)
        mapping = deepcopy(self.mapping)
        extra = deepcopy(mapping["objects"]["archive"])
        extra["sha256"] = "f" * 64
        mapping["objects"]["orphan"] = extra
        with self.assertRaisesRegex(EvidenceError, "every archive pack"):
            self.normalized(mapping)
        mapping = deepcopy(self.mapping)
        mapping["refs"] = []
        with self.assertRaisesRegex(EvidenceError, "competing logical indexes"):
            self.normalized(mapping)
