"""Optional labels bind retained observations; tests do not authenticate UI facts."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("observation_receipts", ROOT / "skills/to-sdd-pipeline/scripts/observation_receipts.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Sources:
    def __init__(self):
        self.payloads = {}
        self.artifacts = {"screen-map": {"traceability": {"definitions": [
            {"id": key, "kind": "state"} for key in ("STATE-04", "STATE-08")
        ]}}}

    def add(self, path, value):
        data = json.dumps(value, sort_keys=True).encode()
        self.payloads[path] = (hashlib.sha256(data).hexdigest(), deepcopy(value))
        return {"path": path, "content_hash": self.payloads[path][0]}

    def evidence_snapshot(self, ref, *_args):
        return isinstance(ref, dict) and ref.get("path") in self.payloads and ref.get("content_hash") == self.payloads[ref["path"]][0]

    def evidence_json(self, ref):
        return deepcopy(self.payloads[ref["path"]][1])


class ObservationReceiptTests(unittest.TestCase):
    def setUp(self):
        self.sources = Sources()
        self.time = "2020-01-01T10:00:00Z"
        self.observed = {"observed_at": self.time, "state_id": "STATE-04", "fixture": "mixed", "result": "saved"}
        self.capture = self.sources.add("observations.json", {"captures": [self.observed]})
        self.row = {"action_name": "Capture a reference", "observed_state_id": "STATE-04", "fixture_id": "mixed", "observed_result": "saved", "observed_at": self.time,
                    "observation_source_index": 0, "observation_pointer": "/captures/0"}
        self.original = {"observed_at": self.time, "interactions_checked": [{"observation_tag": "save-pending", "observed_at": self.time}], "original_observation_refs": [self.capture]}
        self.original_ref = self.sources.add("original-browser.json", self.original)
        self.correction = {"version": 1, "event": "observation_metadata_correction", "original_receipt": self.original_ref,
                           "observed_at": self.time, "corrected_at": "2020-01-02T10:00:00Z", "reviewer": "Fixture reviewer", "reason": "Action label described the wrong observed state", "new_execution": False,
                           "corrections": [{**self.row, "interaction_index": 0}]}

    def validate(self, value):
        return module.validate_observation_receipt(self.sources, value)

    def test_legacy_action_tag_is_not_automatically_interpreted_as_state(self):
        self.validate(self.original)
        self.validate({"result": "passed"})
        self.validate({"interactions_checked": ["Save", "Undo"]})
        self.validate({"interactions_checked": "legacy narrative"})

    def test_structured_labels_match_existing_observation_without_copying_payload(self):
        self.validate({"interactions_checked": [self.row], "original_observation_refs": [self.capture]})

    def test_wrong_state_fixture_or_result_is_rejected(self):
        for key, wrong in (("observed_state_id", "STATE-08"), ("fixture_id", "empty"), ("observed_result", "pending")):
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, "differs"):
                self.validate({"interactions_checked": [{**self.row, key: wrong}], "original_observation_refs": [self.capture]})

    def test_unknown_state_and_partial_labels_are_rejected(self):
        for row in ({**self.row, "observed_state_id": "STATE-99"}, {"action_name": "Capture"}):
            with self.assertRaises(ValueError):
                self.validate({"interactions_checked": [row]})

    def test_changed_or_missing_original_bytes_are_rejected(self):
        for ref in ({**self.capture, "content_hash": "0" * 64}, {"path": "missing.json", "content_hash": "0" * 64}):
            with self.assertRaisesRegex(ValueError, "unreadable or changed"):
                self.validate({"interactions_checked": [self.row], "original_observation_refs": [ref]})

    def test_bad_pointer_and_noninteger_source_index_are_rejected(self):
        for update in ({"observation_pointer": "/captures/99"}, {"observation_pointer": "/captures/00"}, {"observation_pointer": "/bad~2"}, {"observation_source_index": True}):
            with self.assertRaises(ValueError):
                self.validate({"interactions_checked": [{**self.row, **update}], "original_observation_refs": [self.capture]})

    def test_metadata_correction_preserves_original_record_and_times(self):
        before = deepcopy(self.sources.payloads)
        self.validate(self.correction)
        self.assertEqual(before, self.sources.payloads)

    def test_correction_cannot_refresh_observation_or_claim_execution(self):
        for update in ({"observed_at": "2020-01-02T10:00:00Z"}, {"new_execution": True}, {"candidate_id": "other"}, {"result": "passed"}, {"corrected_at": "2019-01-02T10:00:00Z"}, {"corrected_at": "2999-01-02T10:00:00Z"}, {"corrected_at": "2020-01-02T10:00:00"}):
            with self.assertRaises(ValueError):
                self.validate({**self.correction, **update})

    def test_correction_cannot_change_interaction_time_result_or_bindings(self):
        for update in ({"observed_at": "2020-01-02T10:00:00Z"}, {"observed_result": "pending"}, {"candidate_id": "other"}, {"interaction_index": True}):
            with self.assertRaises(ValueError):
                self.validate({**self.correction, "corrections": [{**self.correction["corrections"][0], **update}]})

    def test_correction_requires_original_receipt_hash_reviewer_and_unique_target(self):
        for update in ({"original_receipt": {**self.original_ref, "content_hash": "0" * 64}}, {"reviewer": ""}, {"corrections": self.correction["corrections"] * 2}):
            with self.assertRaises(ValueError):
                self.validate({**self.correction, **update})

    def test_prose_and_expected_state_are_not_machine_observation_truth(self):
        legacy = self.sources.add("prose.json", {"captures": [{"observed_at": self.time, "expected_state": "STATE-08", "dom": "STATE-08 pending"}]})
        self.validate({"interactions_checked": [self.row], "original_observation_refs": [legacy]})


if __name__ == "__main__":
    unittest.main()
