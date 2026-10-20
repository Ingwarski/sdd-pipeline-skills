"""Reference intent must not be inferred from ordinary application metadata."""
import copy
import unittest

import test_evidence_checker as fixture
from evidence.resolver import evidence_reference, payload_references, validate_reference


class EvidenceReferenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.EvidenceCheckerTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_version_hash_metadata_and_contained_records_are_not_external(self):
        for schema in (None, [], {}, 1, True, "environment-v1", "unrelated-schema"):
            with self.subTest(schema=schema):
                record = {"version": "12.3", "sha256": "a" * 64, "schema": schema,
                          "path": "/opt/synthetic-browser/metadata.json"}
                self.assertIsNone(evidence_reference(record))
                self.assertEqual([], list(payload_references({"runtime": record})))
        contained = {"path": "forge/result.json", "content_hash": "a" * 64,
                     "schema": "sdd-result-v1"}
        self.assertIsNone(evidence_reference(contained))

    def test_direct_and_wrapped_references_keep_verified_dependency_closure(self):
        ref = self.fixture.prepare({"synthetic": True})
        self.assertIs(ref, evidence_reference(ref))
        self.assertIs(ref, evidence_reference({"evidence_ref": ref}))
        resolver = fixture.EvidenceResolver(self.fixture.cache)
        for record in (ref, {"evidence_ref": ref}):
            self.assertEqual([ref], list(payload_references({"capture": record})))
            resolver.validate_json_payload({"capture": record})
        (self.fixture.cache / "objects" / ref["sha256"]).unlink()
        with self.assertRaises(ValueError):
            fixture.EvidenceResolver(self.fixture.cache).validate_json_payload({"capture": ref})

    def test_malformed_explicit_references_fail_instead_of_becoming_metadata(self):
        for record in ({"artifact_id": "missing-fields"}, {"locator": {}},
                       *({"evidence_ref": value} for value in (None, False, 1, "bad", [], {}))):
            with self.subTest(record=record), self.assertRaises(ValueError):
                fixture.EvidenceResolver(self.fixture.cache).validate_json_payload({"capture": record})

    def test_non_string_schemas_fail_with_validation_errors(self):
        ref = self.fixture.prepare({"synthetic": True})
        for schema in (None, [], {}, 1, True):
            malformed = {**copy.deepcopy(ref), "schema": schema}
            for operation in (lambda: validate_reference(malformed),
                              lambda: list(payload_references({}, schema)),
                              lambda: fixture.EvidenceResolver(self.fixture.cache).json(malformed)):
                with self.subTest(schema=schema), self.assertRaises(ValueError):
                    operation()


if __name__ == "__main__":
    unittest.main()
