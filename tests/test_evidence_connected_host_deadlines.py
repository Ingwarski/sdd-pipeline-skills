"""Deterministic queue deadlines; all clocks and session files stay in memory."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import inspect
import json
from pathlib import Path
import sys
import textwrap
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))

from evidence import connected_host as host
from evidence.io import EvidenceError


TIMEOUT = ("connected Drive is waiting for the active agent to service "
           "evidence_host.py next/respond; request timed out and was retained")


class MemoryPath:
    def __init__(self, files, name=""):
        self.files, self.name = files, name

    def __truediv__(self, name):
        return MemoryPath(self.files, name)

    def exists(self):
        self.files.probes.append((self.name, self.files.clock.wall, self.files.clock.elapsed))
        return self.name in self.files.data

    def unlink(self):
        self.files.removed.append(self.name)
        del self.files.data[self.name]


class FakeClock:
    def __init__(self):
        self.wall, self.elapsed = 100.0, 50.0
        self.sleeps = []
        self.on_sleep = None

    def time(self):
        return self.wall

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        # A guard makes a broken wait fail promptly without real sleeping.
        if len(self.sleeps) > 20:
            raise AssertionError("wait continued beyond the fake-clock bound")
        self.elapsed += 1.0
        if self.on_sleep:
            self.on_sleep()


class MemoryFiles:
    def __init__(self, clock):
        self.clock = clock
        self.data, self.probes, self.reads, self.removed = {}, [], [], []
        self.on_request = None

    def write(self, path, value):
        self.data[path.name] = host._bounded(value)
        if path.name == "request.json" and self.on_request:
            self.on_request(value)

    def read(self, path, maximum):
        self.reads.append(path.name)
        raw = self.data[path.name]
        if len(raw) > maximum:
            raise EvidenceError("fixture metadata exceeds bound")
        return json.loads(raw)

    def respond(self, request, **changes):
        response = {"version": 1, "session_id": request["session_id"],
                    "request_id": request["request_id"],
                    "request_sha256": hashlib.sha256(host._bounded(request)).hexdigest(),
                    "result": {"files": []}, "materialized_path": None,
                    "managed_original": False}
        response.update(changes)
        self.write(MemoryPath(self, "response.json"), response)


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.files = MemoryFiles(self.clock)
        # Bypass filesystem ownership acquisition only; exercise the shipped
        # _native request creation, waiting, binding and consumption unchanged.
        self.adapter = object.__new__(host.ConnectedHostAdapter)
        self.adapter.path = MemoryPath(self.files)
        self.adapter.session = {"version": 1, "session_id": "a" * 32}
        self.adapter.closed = False
        self.adapter.timeout_seconds = 10
        self.adapter.maximum = host.MAX_CONTROL_BYTES
        self.adapter._response_bytes = 0
        patches = self.enterContext(ExitStack())
        patches.enter_context(patch.object(host, "time", self.clock))
        patches.enter_context(patch.object(host, "atomic_json", self.files.write))
        patches.enter_context(patch.object(host, "read_json", self.files.read))

    def call(self, method=None):
        method = method or host.ConnectedHostAdapter._native
        return method(self.adapter, "list_folder", {"url": "fixture-folder"})

    def assert_retained(self, *, response=False):
        self.assertEqual({"request.json", "response.json"} if response else {"request.json"},
                         set(self.files.data))
        self.assertEqual([], self.files.removed)
        self.assertEqual([], self.files.reads)
        self.assertEqual(0, self.adapter._response_bytes)
        request = json.loads(self.files.data["request.json"])
        self.assertEqual(110.0, request["expires_at"])

    def test_forward_wall_jump_stops_without_another_response_poll(self):
        self.clock.on_sleep = lambda: setattr(self.clock, "wall", 111.0)
        with self.assertRaisesRegex(EvidenceError, "^" + TIMEOUT + "$"):
            self.call()
        self.assertEqual([0.05], self.clock.sleeps)
        self.assertFalse(any(wall >= 110.0 for name, wall, _ in self.files.probes
                             if name == "response.json"))
        self.assert_retained()

    def test_backward_wall_jump_cannot_extend_monotonic_deadline(self):
        def jump_backward():
            self.clock.wall = 1.0
            self.clock.elapsed = 60.0
        self.clock.on_sleep = jump_backward
        with self.assertRaisesRegex(EvidenceError, "^" + TIMEOUT + "$"):
            self.call()
        self.assertEqual([0.05], self.clock.sleeps)
        self.assertFalse(any(elapsed >= 60.0 for name, _, elapsed in self.files.probes
                             if name == "response.json"))
        self.assert_retained()

    def test_wall_expired_already_present_response_is_preserved(self):
        def late_response(request):
            self.files.respond(request)
            self.clock.wall = request["expires_at"]
        self.files.on_request = late_response
        with self.assertRaisesRegex(EvidenceError, "^" + TIMEOUT + "$"):
            self.call()
        self.assertEqual([], self.clock.sleeps)
        self.assert_retained(response=True)

    def test_monotonic_expired_response_after_sleep_is_preserved(self):
        def late_response():
            request = json.loads(self.files.data["request.json"])
            self.files.respond(request)
            self.clock.wall = 1.0
            self.clock.elapsed = 60.0
        self.clock.on_sleep = late_response
        with self.assertRaisesRegex(EvidenceError, "^" + TIMEOUT + "$"):
            self.call()
        self.assertEqual([0.05], self.clock.sleeps)
        self.assert_retained(response=True)

    def test_response_before_both_deadlines_is_accepted(self):
        def timely_response():
            self.clock.wall = 109.999
            self.clock.elapsed = 59.999
            self.files.respond(json.loads(self.files.data["request.json"]))
        self.clock.on_sleep = timely_response
        self.assertEqual({"files": []}, self.call())
        self.assertEqual([0.05], self.clock.sleeps)
        self.assertEqual({}, self.files.data)
        self.assertEqual(["response.json"], self.files.reads)
        self.assertEqual(["request.json", "response.json"], self.files.removed)

    def test_response_binding_guards_preserve_mismatched_queue(self):
        for field in ("session_id", "request_id", "request_sha256"):
            with self.subTest(field=field):
                self.files.data.clear()
                self.files.on_request = lambda request: self.files.respond(request, **{field: "wrong"})
                with self.assertRaisesRegex(EvidenceError, "does not match the pending request"):
                    self.call()
                self.assertEqual({"request.json", "response.json"}, set(self.files.data))
                self.assertEqual([], self.files.removed)
                self.adapter._response_bytes = 0

    def test_host_request_session_and_response_binding_guards_remain(self):
        request = {"version": 1, "session_id": "b" * 32, "request_id": "c" * 32,
                   "expires_at": 110.0}
        self.files.write(self.adapter.path / "request.json", request)
        before = dict(self.files.data)
        with patch.object(host, "_session", return_value=(self.adapter.path, self.adapter.session)):
            with self.assertRaisesRegex(EvidenceError, "request identity mismatch"):
                host.next_request("memory-session")
            with self.assertRaisesRegex(EvidenceError, "stale or mismatched"):
                host.respond("memory-session", request["request_id"], {})
            request["session_id"] = self.adapter.session["session_id"]
            self.files.write(self.adapter.path / "request.json", request)
            with self.assertRaisesRegex(EvidenceError, "stale or mismatched"):
                host.respond("memory-session", "d" * 32, {})
        self.assertEqual({"request.json"}, set(self.files.data))
        self.assertEqual([], self.files.removed)
        self.assertEqual(json.loads(before["request.json"])["expires_at"], request["expires_at"])

    def old_wait_method(self):
        # Execute the original source loop against the same deterministic
        # harness, proving the tests distinguish the old shipped behavior.
        source = inspect.getsource(host.ConnectedHostAdapter._native)
        start = source.index("        while ")
        end = source.index("        response = read_json", start)
        old_loop = ("        while not target.exists():\n"
                    "            if time.monotonic() >= deadline:\n"
                    "                raise EvidenceError(" + repr(TIMEOUT) + ")\n"
                    "            time.sleep(0.05)\n")
        source = source[:start] + old_loop + source[end:]
        namespace = {}
        exec(compile(textwrap.dedent(source), "<original-connected-host-wait>", "exec"),
             host.__dict__, namespace)
        return namespace["_native"]

    def test_source_negative_control_old_loop_polls_after_wall_expiry(self):
        self.clock.on_sleep = lambda: setattr(self.clock, "wall", 111.0)
        with self.assertRaisesRegex(EvidenceError, "^" + TIMEOUT + "$"):
            self.call(self.old_wait_method())
        self.assertGreater(len(self.clock.sleeps), 1)
        self.assertTrue(any(wall >= 110.0 for name, wall, _ in self.files.probes
                            if name == "response.json"))
        self.assert_retained()

    def test_source_negative_control_old_loop_consumes_expired_present_response(self):
        def late_response(request):
            self.files.respond(request)
            self.clock.wall = request["expires_at"]
        self.files.on_request = late_response
        self.assertEqual({"files": []}, self.call(self.old_wait_method()))
        self.assertEqual({}, self.files.data)
        self.assertEqual(["request.json", "response.json"], self.files.removed)


if __name__ == "__main__":
    unittest.main()
