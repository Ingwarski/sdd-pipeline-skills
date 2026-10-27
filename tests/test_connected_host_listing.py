"""Pure native-tool fixtures for LIST discovery and fresh selected-object reads."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))

from evidence.connected_host import ConnectedHostAdapter
from evidence.io import EvidenceError
from evidence.transports import ConnectedDriveTransport


def row(index=0, **changes):
    return {"id": "object-" + str(index), "name": "packs/" + str(index), "size": "7",
            "parents": ["selected-folder"], "mimeType": "application/octet-stream",
            "trashed": False, **changes}


class ListingTests(unittest.TestCase):
    def setUp(self):
        self.rows = [row()]
        self.live = {"object-0": row()}
        self.extra = {}
        self.revoked = False
        self.adapter = object.__new__(ConnectedHostAdapter)
        self.adapter.max_objects = 1000
        self.adapter.maximum = 1024 * 1024
        self.adapter.lock = threading.Lock()
        self.adapter._folder = None
        self.adapter._native = Mock(side_effect=self.native)
        self.transport = object.__new__(ConnectedDriveTransport)
        self.transport.adapter = self.adapter
        self.transport.folder_id = "selected-folder"
        self.transport.max_objects = 1000
        self.transport.max_metadata_bytes = 1024 * 1024

    def native(self, tool, arguments, **requirements):
        if tool == "list_folder":
            return copy.deepcopy({"files": self.rows, **self.extra})
        if tool == "get_file_metadata":
            if self.revoked:
                raise EvidenceError("fixture permission revoked")
            return {"file": copy.deepcopy(self.live[arguments["fileId"]])}
        self.fail("unexpected selected-object effect: " + tool)

    def calls(self):
        return [call.args[0] for call in self.adapter._native.call_args_list]

    def request(self, operation="list", **values):
        return self.adapter({"version": 1, "folder_id": "selected-folder",
                             "operation": operation, **values})

    def test_fifty_complete_matches_use_one_native_list_and_no_metadata_gets(self):
        self.rows = [row(index) for index in range(50)]
        values = self.transport.inventory("packs/")
        self.assertEqual(50, len(values))
        self.assertEqual({7}, {value["size"] for value in values})
        self.assertEqual(["list_folder"], self.calls())

    def test_exact_key_lookup_still_gets_only_matching_stable_id(self):
        self.rows = [row(index) for index in range(50)]
        value = self.request("lookup", key="packs/0")
        self.assertEqual("object-0", value["objects"][0]["object_id"])
        self.assertEqual(["list_folder", "get_file_metadata"], self.calls())
        self.assertEqual("object-0", self.adapter._native.call_args.args[1]["fileId"])

    def test_incomplete_or_unknown_fields_fall_back_to_live_metadata(self):
        for field in ("mimeType", "size"):
            for unknown in (False, True):
                with self.subTest(field=field, unknown=unknown):
                    self.rows = [row()]
                    if unknown:
                        self.rows[0][field] = None
                    else:
                        del self.rows[0][field]
                    self.adapter._native.reset_mock()
                    self.assertEqual(7, self.request(prefix="packs/")["objects"][0]["size"])
                    self.assertEqual(["list_folder", "get_file_metadata"], self.calls())

    def test_actual_connector_shape_fifty_rows_uses_one_list_zero_gets(self):
        self.rows = [{"id": "object-" + str(index), "title": "packs/" + str(index), "size": "7",
                      "mime_type": "application/octet-stream", "parent_ids": None,
                      "file_or_folder": "file"} for index in range(50)]
        self.assertEqual(50, len(self.transport.inventory("packs/")))
        self.assertEqual(["list_folder"], self.calls())

    def test_unknown_parent_and_trashed_are_advisory_discovery_only(self):
        for field in ("parents", "trashed"):
            for unknown in (False, True):
                with self.subTest(field=field, unknown=unknown):
                    self.rows = [row()]
                    if unknown:
                        self.rows[0][field] = None
                    else:
                        del self.rows[0][field]
                    self.adapter._native.reset_mock()
                    self.assertEqual(7, self.request(prefix="packs/")["objects"][0]["size"])
                    self.assertEqual(["list_folder"], self.calls())

    def test_complete_native_aliases_zero_size_and_unrelated_rows(self):
        self.rows = [{"file_id": "object-0", "title": "packs/0", "size": 0,
                      "mime_type": "application/octet-stream", "parent_ids": ["selected-folder"],
                      "trashed": False}, row(1, name="other/1")]
        self.assertEqual([{"object_id": "object-0", "key": "packs/0", "size": 0}],
                         self.request(prefix="packs/")["objects"])
        self.assertEqual(["list_folder"], self.calls())

    def test_complete_invalid_metadata_never_falls_back_or_enters_inventory(self):
        changes = ({"id": "unsafe/id"}, {"parents": ["foreign-folder"]},
                   {"parents": "selected-folder"}, {"mimeType": "application/vnd.google-apps.document"},
                   {"mimeType": ""}, {"mimeType": 7}, {"trashed": True}, {"trashed": "false"},
                   {"file_or_folder": "folder"}, {"file_or_folder": False},
                   {"size": True}, {"size": -1}, {"size": "1.2"}, {"size": "-1"},
                   {"name": "packs/../unsafe"})
        for change in changes:
            with self.subTest(change=change):
                self.rows = [row(**change)]
                self.adapter._native.reset_mock()
                with self.assertRaises(EvidenceError):
                    self.request(prefix="packs/")
                self.assertEqual(["list_folder"], self.calls())

    def test_duplicate_ids_and_keys_remain_rejected(self):
        for duplicate in (row(), row(1, name="packs/0")):
            with self.subTest(duplicate=duplicate):
                self.rows = [row(), duplicate]
                with self.assertRaisesRegex(EvidenceError, "repeat|duplicate"):
                    self.transport.inventory("packs/")

    def test_partial_continuation_and_saturated_results_remain_rejected(self):
        for extra in ({"partial": True}, {"truncated": True}, {"has_more": True},
                      {"incompleteSearch": True}, {"incomplete_search": True},
                      {"nextPageToken": "next"}, {"next_page_token": "next"}):
            with self.subTest(extra=extra):
                self.extra = extra
                with self.assertRaisesRegex(EvidenceError, "saturated or partial"):
                    self.request(prefix="packs/")
        self.extra = {}
        self.rows = [row(index) for index in range(1000)]
        with self.assertRaisesRegex(EvidenceError, "saturated or partial"):
            self.request(prefix="packs/")

    def test_page_token_object_limit_metadata_bound_and_bad_rows_remain_rejected(self):
        with self.assertRaisesRegex(EvidenceError, "continuation"):
            self.request(prefix="packs/", page_token="unsupported")
        with self.assertRaisesRegex(EvidenceError, "object bound"):
            self.request(prefix="packs/", max_objects=0)
        self.transport.max_metadata_bytes = 20
        with self.assertRaisesRegex(EvidenceError, "invalid bounded JSON"):
            self.transport.inventory("packs/")
        for invalid in (None, "row", {}):
            with self.subTest(invalid=invalid):
                self.rows = [invalid]
                with self.assertRaises(EvidenceError):
                    self.request(prefix="packs/")

    def test_each_list_is_fresh_and_caller_witness_cannot_replace_native_page(self):
        self.assertEqual(7, self.request(prefix="packs/")["objects"][0]["size"])
        self.rows = [row(1, size=9)]
        result = self.request(prefix="packs/", objects=[row()], metadata_verified=True)
        self.assertEqual([{"object_id": "object-1", "key": "packs/1", "size": 9}], result["objects"])
        self.assertEqual(["list_folder", "list_folder"], self.calls())

    def test_selected_stat_uses_live_size_and_rejects_changed_identity(self):
        locator = self.transport.inventory("packs/")[0]
        self.live["object-0"]["size"] = "70"
        self.assertEqual(70, self.transport.stat(locator)["size"])
        self.live["object-0"]["id"] = "substituted"
        with self.assertRaisesRegex(EvidenceError, "different stable ID"):
            self.transport.stat(locator)
        self.assertEqual(["list_folder", "get_file_metadata", "get_file_metadata"], self.calls())

    def test_selected_get_rejects_rename_move_native_conversion_trash_and_revocation(self):
        locator = self.transport.inventory("packs/")[0]
        for change in ({"name": "packs/renamed"}, {"parents": ["foreign-folder"]},
                       {"mimeType": "application/vnd.google-apps.document"}, {"trashed": True}, None):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                self.live["object-0"] = row(**(change or {}))
                self.revoked = change is None
                destination = Path(directory) / "original"
                with self.assertRaises(EvidenceError):
                    self.transport.get(locator, destination, 7)
                self.assertFalse(destination.exists())
        self.assertNotIn("fetch", self.calls())

    def test_direct_download_and_delete_still_get_metadata_before_effect(self):
        self.live["object-0"] = row(name="packs/renamed")
        for operation in ("download_original", "delete"):
            with self.subTest(operation=operation):
                self.adapter._native.reset_mock()
                with self.assertRaisesRegex(EvidenceError, "immutable key"):
                    self.request(operation, object_id="object-0", key="packs/0", max_bytes=7)
                expected = ["get_file_metadata"] if operation == "download_original" else ["list_folder", "get_file_metadata"]
                self.assertEqual(expected, self.calls())

    def test_discovery_hint_cannot_authorize_foreign_selected_stat_get_or_delete(self):
        self.rows = [{"id": "object-0", "title": "packs/0", "size": "7",
                      "mime_type": "application/octet-stream", "parent_ids": None,
                      "file_or_folder": "file"}]
        locator = self.transport.inventory("packs/")[0]
        self.live["object-0"] = row(parents=["foreign-folder"])
        with self.assertRaisesRegex(EvidenceError, "outside the selected"):
            self.transport.stat(locator)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(EvidenceError, "outside the selected"):
                self.transport.get(locator, Path(directory) / "original", 7)
        with self.assertRaisesRegex(EvidenceError, "outside the selected"):
            self.transport.delete(locator)
        self.assertNotIn("fetch", self.calls())
        self.assertNotIn("delete_file", self.calls())


if __name__ == "__main__":
    unittest.main()
