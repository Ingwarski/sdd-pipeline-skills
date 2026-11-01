"""Conservative lifecycle discovery on isolated synthetic metadata and bytes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/to-sdd-pipeline/scripts"))
from evidence.dependencies import collect_project, assert_unchanged, inventory_digest
from evidence.io import EvidenceError
from evidence.policy import load_defaults


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


class EvidenceDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-dependency-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "project"
        self.root.mkdir()
        self.catalog = {"project_id": "11111111-1111-4111-8111-111111111111",
            "store_id": "22222222-2222-4222-8222-222222222222", "refs": {},
            "sequence": 3, "root_key": "synthetic/catalog/3"}
        self.payloads, self.reads = {}, []
        self.manifest = {"checker_contract_version": 3, "unit_contract_version": 3}

    def write(self, relative, value):
        raw = value if isinstance(value, bytes) else encoded(value)
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {"path": relative, "content_hash": hashlib.sha256(raw).hexdigest()}

    def evidence(self, name, value, schema="evidence-json-v1"):
        raw = value if isinstance(value, bytes) else encoded(value)
        digest = hashlib.sha256(raw).hexdigest()
        ref = {"version": 1, "artifact_id": name, "sha256": digest, "size": len(raw),
            "kind": "synthetic-result", "schema": schema,
            "provenance": {"run_id": "synthetic-run", "unit_id": "U-1"}, "bindings": {},
            "locator": {"provider": "local", "store_id": self.catalog["store_id"],
                "object_id": "synthetic-pack-" + name, "pack_sha256": "a" * 64,
                "pack_size": len(raw) + 500, "member": "objects/" + digest},
            "retention": {"sealed_at": "2020-01-01T00:00:00Z", "class": "current_acceptance"}}
        self.catalog["refs"][name], self.payloads[name] = deepcopy(ref), raw
        return ref

    def resolve(self, ref):
        self.reads.append(ref["artifact_id"])
        return self.payloads[ref["artifact_id"]]

    def collect(self, **kwargs):
        self.write("forge/sdd-manifest.json", self.manifest)
        return collect_project(self.root, catalog=self.catalog, resolve_external=self.resolve, **kwargs)

    def test_nested_and_inactive_managed_references_are_all_kept(self):
        nested = self.evidence("nested", {"observation": "original"})
        previous = self.evidence("previous", b"synthetic older result", "evidence-bytes-v1")
        parent = self.evidence("parent", {"evidence": [nested], "history": [previous]})
        self.manifest["verification"] = {"checks": [{"evidence": [parent]}]}
        result = self.collect()
        self.assertEqual([], result["blockers"])
        self.assertEqual(["nested", "parent", "previous"], result["roots"])
        self.assertNotIn("previous", self.reads, "opaque binary proof should not be downloaded for discovery")
        self.assertTrue(result["reasons"]["nested"])
        assert_unchanged(self.root, result)

    def test_orphan_interrupted_history_and_local_json_closure_are_kept(self):
        retained = self.evidence("unpublished-attempt", {"observed": "failed"})
        receipt = self.write("forge/evidence/result.json", {"superseded": [retained]})
        self.write("forge/unit-history/attempts/orphan/record.json",
            {"event": "unit_attempt", "version": 2, "status": "blocked", "evidence": [receipt]})
        result = self.collect()
        self.assertEqual([], result["blockers"])
        self.assertEqual(["unpublished-attempt"], result["roots"])
        self.assertIn(receipt["path"], result["inputs"])

    def test_current_declared_json_source_is_followed(self):
        ref = self.evidence("configured-proof", b"proof", "evidence-bytes-v1")
        self.write("config/fixture.JSON", {"evidence": [ref]})
        self.manifest["implementation_paths"] = ["config"]
        result = self.collect()
        self.assertEqual([], result["blockers"])
        self.assertEqual(["configured-proof"], result["roots"])
        self.write("config/extra.json", {})
        with self.assertRaisesRegex(EvidenceError, "membership changed"):
            assert_unchanged(self.root, result)

    def test_local_json_suffix_and_explicit_supported_schemas_keep_nested_proof(self):
        required = self.evidence("required", b"required proof", "evidence-bytes-v1")
        cases = [("receipt.JSON", None), ("receipt.data", "evidence-json-v1"),
                 ("source.data", "source-inventory-v1"), ("environment.data", "environment-v1"),
                 ("receipt.data", "sdd-receipt-v1"), ("result.data", "sdd-result-v1")]
        for name, schema in cases:
            with self.subTest(name=name, schema=schema):
                reference = self.write("forge/evidence/" + name,
                    {"version": 1, "source_hashes": {}, "evidence": [required]})
                if schema is not None:
                    reference["schema"] = schema
                self.manifest["evidence"] = [reference]
                result = self.collect()
                self.assertEqual([], result["blockers"])
                self.assertEqual(["required"], result["roots"])
                self.assertIn(reference["path"], result["inputs"])

    def test_json_receipt_roles_and_native_refs_ignore_file_extension(self):
        required = self.evidence("required", b"required proof", "evidence-bytes-v1")
        reference = self.write("forge/evidence/receipt.data", {"evidence": [required]})
        cases = [{"implementation_gate": {"prompt_receipt": reference}},
                 {"active_baseline": {"approval_receipt": reference}},
                 {"design_execution": {"source_manifest": reference}},
                 {"design_review": {"receipt": reference}},
                 {"prototype_promotions": [{"receipt": reference}]},
                 {"unit_sequence_exceptions": [reference]},
                 {"legacy_history": [reference]},
                 {"reviewed_acceptance": {"U-1": [reference]}},
                 {"execution_contexts": {"U-1": reference}},
                 {"context_ref": reference}]
        for manifest in cases:
            with self.subTest(role=next(iter(manifest))):
                self.manifest = manifest
                result = self.collect()
                self.assertEqual([], result["blockers"])
                self.assertEqual(["required"], result["roots"])

    def test_unknown_or_malformed_declared_json_never_becomes_an_opaque_leaf(self):
        reference = self.write("forge/evidence/receipt.data", b"not JSON")
        for schema in ("evidence-json-v1", "future-json-v2", None):
            with self.subTest(schema=schema):
                self.manifest["evidence"] = [{**reference, "schema": schema}]
                self.assertTrue(self.collect()["blockers"])
        self.manifest["evidence"] = [{**reference, "schema": "evidence-bytes-v1"}]
        self.assertEqual([], self.collect()["blockers"])
        self.manifest = {"implementation_gate": {"prompt_receipt": {
            **reference, "schema": "evidence-bytes-v1"}}}
        self.assertIn("opaque evidence schema", str(self.collect()["blockers"]))

    def test_changed_manifest_or_new_history_invalidates_inventory(self):
        result = self.collect()
        self.write("forge/sdd-manifest.json", {**self.manifest, "revision": "changed"})
        with self.assertRaisesRegex(EvidenceError, "input changed"):
            assert_unchanged(self.root, result)
        result = self.collect()
        self.write("forge/unit-history/attempts/new/record.json", {"event": "unit_attempt", "version": 2})
        with self.assertRaisesRegex(EvidenceError, "membership changed"):
            assert_unchanged(self.root, result)

    def test_missing_conflicting_or_unsupported_metadata_blocks(self):
        self.manifest["receipt"] = {"path": "forge/missing.json", "content_hash": "a" * 64}
        result = self.collect()
        self.assertTrue(result["blockers"])
        with self.assertRaisesRegex(EvidenceError, "incomplete"):
            assert_unchanged(self.root, result)
        self.manifest.pop("receipt")
        self.write("forge/unit-history/attempts/future/record.json", {"event": "unit_attempt", "version": 999})
        result = self.collect()
        self.assertIn("unsupported retained history", str(result["blockers"]))

    def test_managed_catalog_identity_and_required_json_bytes_are_checked(self):
        ref = self.evidence("one", {"fact": True})
        self.manifest["evidence"] = [ref]
        self.payloads["one"] = b"changed original"
        self.assertIn("JSON evidence changed", str(self.collect()["blockers"]))
        self.catalog["refs"].clear()
        self.assertIn("absent from active catalog", str(self.collect()["blockers"]))

    def test_cache_never_trusts_serialized_roots_or_a_complete_flag(self):
        ref = self.evidence("one", {"value": 1})
        self.manifest["evidence"] = [ref]
        first = self.collect()
        self.reads.clear()
        candidate = deepcopy(first)
        candidate.update(roots=[], reasons={}, complete=True)
        second = self.collect(prior_index=candidate)
        self.assertEqual(["one"], second["roots"])
        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual([], self.reads)
        self.assertGreater(second["statistics"]["parse_cache_hits"], 0)
        self.assertEqual(0, second["statistics"]["json_parses"])

    def test_forged_parsed_cache_cannot_hide_an_edge(self):
        child = self.evidence("child", b"required", "evidence-bytes-v1")
        parent = self.evidence("parent", {"evidence": [child]})
        self.manifest["evidence"] = [parent]
        first = self.collect()
        forged = deepcopy(first)
        forged["parse_cache"][parent["sha256"]]["value"] = {}
        self.reads.clear()
        second = self.collect(prior_index=forged)
        self.assertEqual(["child", "parent"], second["roots"])
        self.assertIn("parent", self.reads)

    def test_catalog_publication_and_statistics_do_not_change_source_digest(self):
        first = self.collect()
        self.catalog["sequence"] += 1
        self.catalog["root_key"] = "synthetic/catalog/4"
        second = self.collect(prior_index=first)
        self.assertEqual(first["digest"], second["digest"])
        self.assertNotEqual(first["catalog_revision"], second["catalog_revision"])
        self.assertEqual(second["digest"], inventory_digest(second))

    def test_local_reference_cycles_keep_all_edges_and_symlinks_block(self):
        # Ordinary source metadata can be cyclic; visiting a back-edge must
        # neither recurse indefinitely nor suppress its remaining siblings.
        child = self.evidence("cycle-proof", b"proof", "evidence-bytes-v1")
        self.write("config/a.json", {"source_path": "config/b.json"})
        self.write("config/b.json", {"source_path": "config/a.json", "evidence": [child]})
        self.manifest["source_path"] = "config/a.json"
        result = self.collect()
        self.assertEqual([], result["blockers"])
        self.assertIn("cycle-proof", result["roots"])
        self.manifest.pop("source_path")
        target = self.root / "forge/unit-history/symlink"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.symlink_to(self.root / "config", target_is_directory=True)
        except OSError:
            self.skipTest("host does not support synthetic symlinks")
        self.assertIn("link", str(self.collect()["blockers"]))

    def source_archive(self, *, optional=False, report_path="report.json", schema=None, receipt_role=False):
        required = self.evidence("required", {"report": "original"})
        nested_json = self.evidence("source-json", {"evidence": [required]}, "evidence-bytes-v1")
        diagnostic = self.evidence("diagnostic", b"optional detailed diagnostic", "evidence-bytes-v1")
        root = "forge/unit-history/legacy/synthetic/files"
        files = {report_path: {"path": root + "/" + report_path, "content_hash": nested_json["sha256"]},
                 "debug.bin": {"path": root + "/debug.bin", "content_hash": diagnostic["sha256"]}}
        record = {"event": "legacy_execution_archive", "version": 2, "snapshot_root": root, "files": files}
        if schema is not None or receipt_role:
            reference = {"path": report_path, "content_hash": nested_json["sha256"]}
            if schema is not None:
                reference["schema"] = schema
            record["prompt_receipt" if receipt_role else "evidence"] = reference
        record_ref = self.write("forge/unit-history/legacy/synthetic/record.json", record)
        archive = {"event": "unit_source_archive_index", "version": 1, "encoding": "sha_objects_v1",
            "objects": {nested_json["sha256"]: nested_json, diagnostic["sha256"]: diagnostic},
            "records": [{"record_ref": record_ref, "snapshot_root": root, "sources": [
                {**files[report_path], "object_key": nested_json["sha256"]},
                {**files["debug.bin"], "object_key": diagnostic["sha256"]}]}]}
        self.manifest["source_archive_index_ref"] = self.write("forge/unit-history/source-indexes/synthetic/record.json", archive)
        if optional:
            policy = {**load_defaults(), "project_id": self.catalog["project_id"],
                "store_id": self.catalog["store_id"], "provider": "local"}
            self.write("forge/evidence-policy.json", policy)
            self.manifest["evidence_storage"] = {"policy_path": "forge/evidence-policy.json"}
            review = {"event": "optional_diagnostic_review", "version": 1,
                "project_id": self.catalog["project_id"], "store_id": self.catalog["store_id"],
                "review": {"reviewer": "synthetic-owner", "reviewed_at": "2020-01-01T00:00:00Z", "rationale": "Synthetic optional data review"},
                "recorded_at": "2020-01-01T00:00:00Z", "members": [{"record_ref": record_ref,
                    "logical_path": "debug.bin", "content_hash": diagnostic["sha256"], "rationale": "Not required for this synthetic claim"}]}
            reference = self.write("forge/unit-history/diagnostics/synthetic/record.json", review)
            self.manifest["history_integrity"] = {"legacy_payloads": "every_gate", "optional_diagnostics_ref": reference}
        return files, diagnostic

    def test_archived_source_json_is_scanned_without_fetching_binary_sources(self):
        self.source_archive()
        result = self.collect()
        self.assertEqual([], result["blockers"])
        self.assertEqual(["diagnostic", "required", "source-json"], result["roots"])
        self.assertNotIn("diagnostic", self.reads)

    def test_archived_json_recognition_preserves_declared_schema_and_receipt_role(self):
        cases = [("report.JSON", None, False), ("report.data", "evidence-json-v1", False),
                 ("receipt.data", None, True)]
        for path, schema, role in cases:
            with self.subTest(path=path, schema=schema, receipt_role=role):
                self.source_archive(report_path=path, schema=schema, receipt_role=role)
                result = self.collect()
                self.assertEqual([], result["blockers"])
                self.assertEqual(["diagnostic", "required", "source-json"], result["roots"])
                self.assertNotIn("diagnostic", self.reads)

    def test_contextual_json_identity_is_digest_bound_and_rediscovered_from_bytes(self):
        self.source_archive(report_path="receipt.data", receipt_role=True)
        first = self.collect()
        reference = self.catalog["refs"]["source-json"]
        self.assertEqual({"sha256": reference["sha256"], "size": reference["size"]},
                         first["json_artifacts"]["source-json"])
        self.assertNotIn("diagnostic", first["json_artifacts"])
        changed = deepcopy(first)
        changed["json_artifacts"]["source-json"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(EvidenceError, "inventory identity"):
            assert_unchanged(self.root, changed)
        candidate = deepcopy(first)
        candidate["json_artifacts"].clear()
        self.reads.clear()
        second = self.collect(prior_index=candidate)
        self.assertEqual(first["json_artifacts"], second["json_artifacts"])
        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual([], self.reads, "hash-verified cached JSON retains the same derived identity")

    def test_prior_json_type_claim_cannot_promote_opaque_evidence(self):
        reference = self.evidence("opaque", b"opaque proof", "evidence-bytes-v1")
        self.manifest["evidence"] = [reference]
        first = self.collect()
        self.assertEqual({}, first["json_artifacts"])
        candidate = deepcopy(first)
        candidate["json_artifacts"] = {"opaque": {
            "sha256": reference["sha256"], "size": reference["size"]}}
        second = self.collect(prior_index=candidate)
        self.assertEqual({}, second["json_artifacts"])
        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual([], self.reads)

    def test_source_index_json_uses_its_original_snapshot_overlay(self):
        root = "forge/unit-history/legacy/overlay/files"
        old = self.write(root + "/src/code.txt", b"Original synthetic input\n")
        snapshot = self.evidence("archived-json", {"source_hashes": {
            "src/code.txt": old["content_hash"]}}, "evidence-bytes-v1")
        frozen = {"path": root + "/report.json", "content_hash": snapshot["sha256"]}
        record_ref = self.write("forge/unit-history/legacy/overlay/record.json", {
            "event": "legacy_execution_archive", "version": 2, "snapshot_root": root,
            "files": {"src/code.txt": old, "report.json": frozen}})
        index = {"event": "unit_source_archive_index", "version": 1, "records": [{
            "record_ref": record_ref, "snapshot_root": root,
            "sources": [{**frozen, "evidence_ref": snapshot}]}]}
        self.manifest["source_archive_index_ref"] = self.write("forge/unit-history/source-indexes/overlay/record.json", index)
        result = self.collect()
        self.assertEqual([], result["blockers"])
        self.assertEqual(["archived-json"], result["roots"])

    def test_source_index_cannot_hide_foreign_or_unused_object_mappings(self):
        self.source_archive()
        reference = self.manifest["source_archive_index_ref"]
        document = json.loads((self.root / reference["path"]).read_text())
        unused = self.evidence("unmapped", b"unmapped", "evidence-bytes-v1")
        document["objects"][unused["sha256"]] = unused
        self.manifest["source_archive_index_ref"] = self.write(reference["path"], document)
        self.assertIn("unused source archive objects", str(self.collect()["blockers"]))

    def test_review_omits_only_optional_membership_and_keeps_review_metadata(self):
        self.source_archive(optional=True)
        result = self.collect()
        self.assertEqual([], result["blockers"])
        self.assertEqual(["required", "source-json"], result["roots"])
        self.assertIn("forge/unit-history/diagnostics/synthetic/record.json", result["inputs"])
        self.assertIn("forge/unit-history/legacy/synthetic/record.json", result["inputs"])

    def test_optional_membership_cannot_remove_an_independent_active_reference(self):
        _, diagnostic = self.source_archive(optional=True)
        self.manifest["evidence"] = [diagnostic]
        result = self.collect()
        self.assertEqual([], result["blockers"])
        self.assertIn("diagnostic", result["roots"])

    def test_optional_member_still_used_as_active_path_blocks_cleanup(self):
        files, _ = self.source_archive(optional=True)
        self.manifest["evidence"] = [files["debug.bin"]]
        result = self.collect()
        self.assertIn("required input/proof is classified as optional", str(result["blockers"]))

    def test_arbitrary_retirement_dict_is_not_an_exemption(self):
        self.source_archive()
        result = self.collect(retirement={"optional_paths": ["anything"]})
        self.assertTrue(result["blockers"])
        self.assertIn("diagnostic", result["roots"])

    def test_completed_native_unit_inventory_is_read_only_and_complete(self):
        import test_unit_history as fixtures
        fixture = fixtures.UnitHistoryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.capture_alpha()
        project = fixture.p.root.resolve()
        before = {path.relative_to(project).as_posix(): path.read_bytes()
                  for path in project.rglob("*") if path.is_file()}
        result = collect_project(project, catalog=self.catalog, resolve_external=self.resolve)
        self.assertEqual([], result["blockers"])
        self.assertGreater(len(result["inputs"]), 1)
        self.assertTrue(any("/completions/" in path for path in result["inputs"]))
        self.assertEqual(before, {path.relative_to(project).as_posix(): path.read_bytes()
                                 for path in project.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
