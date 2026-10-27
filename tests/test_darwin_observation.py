"""Observation-only ABI, adversarial genealogy and direct owned-child checks."""
import copy
import ctypes
import errno
import json
import os
from pathlib import Path
import select
import socket
import sys
import time
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/to-sdd-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
from evidence import darwin_observation as native
from evidence import process_identity

BOOT = "12121212-1212-4212-8212-121212121212"
EXE = "23232323-2323-4323-8323-232323232323"


def receipt(pid=100, unique="1000", parent="900", *, birth=100, version=10, parent_version=9, stamp=1000):
    return {"version": 1, "identity": {"version": 1, "host": "fixture-host", "platform": "darwin", "pid": pid,
                                     "created": {"seconds": birth, "microseconds": 123}},
            "boot_uuid": BOOT, "uid": 501, "current_ppid": 99, "pgid": 100, "status": "alive",
            "unique_id": unique, "original_parent_unique_id": parent, "idversion": version,
            "original_parent_idversion": parent_version, "executable_uuid": EXE,
            "query": {"api": "libproc.proc_pidinfo", "flavor": 18, "arg": 1, "abi": native.ABI,
                      "size": 192, "returned_size": 192, "errno": 0, "native_status": 2},
            "observed": {"wall_time_ns": str((1000 + stamp) * 10**9), "monotonic_ns": str(stamp)}}


def anchored(max_nodes=256, **kwargs):
    graph = native.LineageGraph(max_nodes, **kwargs)
    root = receipt()
    graph.add_root(root, expected_identity=root["identity"], expected_unique_id=root["unique_id"])
    return graph


class SnapshotValidationTests(unittest.TestCase):
    def test_roundtrip_and_lossless_uint64(self):
        item = receipt(unique=str(2**64 - 1), parent=str(2**64 - 2))
        self.assertTrue(native.valid_snapshot(json.loads(json.dumps(item))))
        self.assertIs(type(item["unique_id"]), str)

    def test_strict_shape_and_types(self):
        bad = [None, [], {}, {**receipt(), "extra": 0}]
        for field in ("uid", "current_ppid", "pgid", "idversion", "original_parent_idversion", "version"):
            bad.append({**receipt(), field: True})
        for field in ("unique_id", "original_parent_unique_id"):
            for value in (0, 123, "0", "01", "-1", "1.0", "1e1", str(2**64), "9" * 5000, "١"):
                bad.append({**receipt(), field: value})
        for value in (None, [], "", "not-uuid", "00000000-0000-0000-0000-000000000000"):
            bad.append({**receipt(), "boot_uuid": value})
        for value in bad:
            with self.subTest(value=str(value)[:160]):
                self.assertFalse(native.valid_snapshot(value))

    def test_nested_abi_chronology_and_zombie_guards(self):
        modifications = [("identity", "pid", 0), ("identity", "host", "bad\nhost"),
                         ("query", "flavor", 17), ("query", "size", 136),
                         ("query", "returned_size", 191), ("query", "errno", errno.EIO),
                         ("query", "arg", 2), ("query", "arg", True),
                         ("query", "native_status", 99), ("query", "api", "ps"),
                         ("query", "abi", "other"), ("observed", "monotonic_ns", "0"),
                         ("observed", "wall_time_ns", "1")]
        for outer, key, value in modifications:
            item = receipt();item[outer][key] = value
            with self.subTest(outer=outer, key=key, value=value):
                self.assertFalse(native.valid_snapshot(item))
        item = receipt();item["status"] = "zombie";item["query"]["native_status"] = 5
        self.assertTrue(native.valid_snapshot(item))
        item["query"]["arg"] = 0
        self.assertFalse(native.valid_snapshot(item))
        for field, value in (("current_ppid", 100), ("pgid", 0), ("idversion", 0),
                             ("original_parent_unique_id", "1000")):
            self.assertFalse(native.valid_snapshot({**receipt(), field: value}))

    def test_no_mutating_or_core_liveness_api(self):
        for name in ("terminate", "register", "kill", "identity", "state", "managed_group_identity"):
            self.assertFalse(hasattr(native, name))


class NativeQueryTests(unittest.TestCase):
    def query(self, callback, pid=100, include_zombie=True):
        library = Mock();library.proc_pidinfo.side_effect = callback
        with patch.object(native.sys, "platform", "darwin"), patch.object(native, "_boot_uuid", return_value=BOOT), \
                patch.object(native, "_library", return_value=library):
            return native.read_snapshot(pid, include_zombie)

    @staticmethod
    def fill(pid, flavor, arg, pointer, size):
        data = pointer._obj
        data.bsd.pid, data.bsd.ppid, data.bsd.pgid = pid, 99, 100
        data.bsd.uid, data.bsd.status = os.geteuid(), 2
        data.bsd.seconds, data.bsd.microseconds = 100, 123
        data.unique.unique_id, data.unique.parent_unique_id = 1000, 900
        data.unique.idversion, data.unique.parent_idversion = 10, 9
        import uuid
        data.unique.executable_uuid[:] = uuid.UUID(EXE).bytes
        return 192

    def test_exact_abi_and_entry_arguments(self):
        native._check_layout()
        seen = []
        def fill(*args):
            seen.append((args[0], args[1], args[2], args[4]))
            return self.fill(*args)
        item = self.query(fill)
        self.assertEqual(seen, [(100, 18, 1, 192)])
        self.assertTrue(native.valid_snapshot(item))
        self.assertEqual(item["query"]["returned_size"], 192)
        self.assertNotIn("sid", item)
        self.assertNotIn("original_parent_pid", item)

    def test_only_zero_count_esrch_is_none(self):
        def missing(*args):
            ctypes.set_errno(errno.ESRCH);return 0
        self.assertIsNone(self.query(missing))
        for count, error in ((0, 0), (0, errno.EPERM), (0, errno.EIO), (191, 0),
                             (193, 0), (191, errno.ESRCH), (-1, errno.ESRCH), (192, errno.EIO)):
            def failure(*args, count=count, error=error):
                ctypes.set_errno(error);return count
            with self.subTest(count=count, error=error), self.assertRaises(native.ObservationError):
                self.query(failure)

    def test_unsupported_does_not_fallback(self):
        for error in (errno.EINVAL, errno.ENOTSUP, errno.ENOSYS):
            def unsupported(*args, error=error):
                ctypes.set_errno(error);return 0
            with self.subTest(error=error), self.assertRaises(native.UnsupportedObservation):
                self.query(unsupported)
        with patch.object(native.sys, "platform", "linux"), self.assertRaises(native.UnsupportedObservation):
            native.read_snapshot(100)

    def test_rejects_pid_uid_birth_reserved_and_unknown_status(self):
        mutations = [("bsd", "pid", 101), ("bsd", "uid", os.geteuid() + 1),
                     ("bsd", "microseconds", 1000000), ("bsd", "seconds", 0),
                     ("bsd", "status", 99), ("bsd", "reserved", 1),
                     ("unique", "unique_id", 0), ("unique", "parent_unique_id", 0),
                     ("unique", "reserved2", 1), ("unique", "reserved3", 1)]
        for structure, field, value in mutations:
            def invalid(*args, structure=structure, field=field, value=value):
                self.fill(*args);setattr(getattr(args[3]._obj, structure), field, value);return 192
            with self.subTest(field=field), self.assertRaises(native.ObservationError):
                self.query(invalid)

    def test_bad_arguments_never_query(self):
        with patch.object(native, "_library") as library:
            for pid in (True, None, "100", 0, -1, 2**31):
                with self.subTest(pid=pid), self.assertRaises(native.ObservationError):
                    native.read_snapshot(pid)
            with self.assertRaises(native.ObservationError):
                native.read_snapshot(100, 1)
            library.assert_not_called()

    def test_layout_mismatch_is_unsupported(self):
        with patch.object(native.ctypes, "sizeof", return_value=7), self.assertRaises(native.UnsupportedObservation):
            native._check_layout()


class LineageGraphTests(unittest.TestCase):
    def test_exact_root_and_defensive_copies(self):
        item = receipt()
        for identity, unique in (({**item["identity"], "pid": 200}, "1000"), (item["identity"], "1001")):
            with self.assertRaises(native.ObservationError):
                native.LineageGraph().add_root(item, expected_identity=identity, expected_unique_id=unique)
        graph = anchored();chain = graph.lineage("1000");chain[0]["uid"] = 1
        self.assertEqual(graph.lineage("1000")[0]["uid"], 501)
        with self.assertRaises(native.ObservationError):
            graph.add_root(item, expected_identity=item["identity"], expected_unique_id="1000")
        with self.assertRaises(native.ObservationError):
            native.LineageGraph().ingest(item)

    def test_out_of_order_actual_intermediary_promotes_pending(self):
        graph = anchored()
        child = receipt(102, "1002", "1001", birth=102, version=12, parent_version=11)
        child["current_ppid"] = 1  # Current PPID cannot supply the missing edge.
        self.assertIsNone(graph.ingest(child));self.assertEqual(graph.pending(), ("1002",))
        parent = receipt(101, "1001", "1000", birth=101, version=11, parent_version=10, stamp=999)
        graph.ingest(parent)
        self.assertEqual([n["unique_id"] for n in graph.lineage("1002")], ["1000", "1001", "1002"])
        self.assertEqual(graph.pending(), ())
        child["identity"]["pid"] = 777  # Inputs are copied too.
        self.assertEqual(graph.lineage("1002")[-1]["identity"]["pid"], 102)

    def test_parent_version_unknown_remains_pending(self):
        graph = anchored()
        child = receipt(101, "1001", "1000", birth=101, version=11, parent_version=12)
        self.assertIsNone(graph.ingest(child))
        self.assertEqual(graph.pending(), ("1001",))

    def test_reused_pid_and_unique_collision_do_not_overwrite(self):
        graph = anchored()
        for item in (receipt(100, "2000", "1000", birth=101, parent_version=10),
                     receipt(101, "1000", "900", birth=101)):
            with self.assertRaises(native.ObservationError): graph.ingest(item)
        self.assertEqual(len(graph.lineage("1000")), 1)

    def test_mutated_token_host_uid_boot_and_chronology_reject(self):
        for field, value in (("uid", 502), ("boot_uuid", EXE), ("original_parent_unique_id", "901"),
                             ("original_parent_idversion", 8)):
            graph = anchored();item = receipt(stamp=1001);item[field] = value
            with self.subTest(field=field), self.assertRaises(native.ObservationError): graph.ingest(item)
        for container, field, value in (("identity", "host", "foreign"), ("identity", "pid", 101),
                                       ("observed", "monotonic_ns", "999"),
                                       ("observed", "wall_time_ns", str(10**9))):
            graph = anchored();item = receipt(stamp=1001);item[container][field] = value
            with self.subTest(field=field), self.assertRaises(native.ObservationError): graph.ingest(item)
        graph = anchored();item = receipt(stamp=1001);item["identity"]["created"]["microseconds"] = 124
        with self.assertRaises(native.ObservationError): graph.ingest(item)

    def test_cycles_and_parent_birth_after_child_are_transactional(self):
        graph = anchored()
        a = receipt(101, "1001", "1002", birth=101, version=11, parent_version=12)
        graph.ingest(a)
        b = receipt(102, "1002", "1001", birth=101, version=12, parent_version=11)
        with self.assertRaises(native.ObservationError): graph.ingest(b)
        self.assertIsNone(graph.lineage("1002"));self.assertEqual(graph.pending(), ("1001",))
        graph = anchored();a = receipt(101, "1001", "1002", birth=101, version=11, parent_version=12)
        graph.ingest(a)
        b = receipt(102, "1002", "1000", birth=102, version=12, parent_version=10)
        with self.assertRaisesRegex(native.ObservationError, "birth"): graph.ingest(b)

    def test_reparent_and_new_group_observations_preserve_only_genealogy(self):
        graph = anchored()
        item = receipt(101, "1001", "1000", birth=101, version=11, parent_version=10)
        graph.ingest(item)
        item = copy.deepcopy(item);item["current_ppid"] = 1;item["pgid"] = 101
        item["observed"] = {"monotonic_ns": "1001", "wall_time_ns": str(2001*10**9)}
        self.assertEqual(len(graph.ingest(item)), 2)
        self.assertEqual(graph.lineage("1001")[-1]["pgid"], 101)

    def test_exec_version_and_zombie_transitions(self):
        graph = anchored();item = receipt(stamp=1001, version=11);item["executable_uuid"] = BOOT
        graph.ingest(item)
        child = receipt(101, "1001", "1000", birth=101, version=12, parent_version=10)
        self.assertEqual(len(graph.ingest(child)), 2)  # Retained actual earlier exec version.
        zombie = receipt(stamp=1002, version=11);zombie["executable_uuid"] = BOOT
        zombie["status"] = "zombie";zombie["query"]["native_status"] = 5
        graph.ingest(zombie)
        with self.assertRaises(native.ObservationError): graph.ingest(receipt(stamp=1003, version=11))
        for item in (receipt(stamp=1001, version=9), {**receipt(stamp=1001), "executable_uuid": BOOT}):
            with self.assertRaises(native.ObservationError): anchored().ingest(item)

    def test_strict_bounds_and_idempotence(self):
        for bound in (True, 0, 257, -1):
            with self.assertRaises(native.ObservationError): native.LineageGraph(bound)
        graph = anchored(1)
        self.assertEqual(len(graph.ingest(receipt())), 1)
        with self.assertRaises(native.ObservationError):
            graph.ingest(receipt(101, "1001", "1000", birth=101, parent_version=10))
        graph = anchored(max_updates=1)
        with self.assertRaises(native.ObservationError): graph.ingest(receipt(stamp=1001))


def native_capability_fixture():
    """Direct fork child only; pipe release and unconditional waitpid, no signals.

    Never orphan a grandchild merely to test reparenting: this fixture promises
    it can reap every child it creates. Reparent handling is exercised purely.
    """
    if sys.platform != "darwin":
        raise native.UnsupportedObservation("native owned-child fixture requires Darwin")
    release_r, release_w = os.pipe()
    ready_r, ready_w = os.pipe()
    child = None
    result = {"signals_sent": False, "children_created": [], "children_reaped": [], "snapshots": {}}
    try:
        parent = native.read_snapshot(os.getpid())
        child = os.fork()
        if child == 0:
            try:
                os.close(release_w);os.close(ready_r)
                os.write(ready_w, b"R");os.close(ready_w)
                os.read(release_r, 1)
            finally:
                os._exit(0)
        result["children_created"].append(child)
        os.close(release_r);release_r = None
        os.close(ready_w);ready_w = None
        if not select.select([ready_r], [], [], 3)[0] or os.read(ready_r, 1) != b"R":
            raise RuntimeError("owned child readiness timeout")
        live = native.read_snapshot(child)
        if live is None:
            raise RuntimeError("owned live child unexpectedly missing")
        if live["identity"] != process_identity.identity(child):
            raise RuntimeError("combined birth disagrees with existing live identity")
        if live["original_parent_unique_id"] != parent["unique_id"] or live["original_parent_idversion"] != parent["idversion"]:
            raise RuntimeError("owned child original native parent mismatch")
        graph = native.LineageGraph()
        graph.add_root(parent, expected_identity=parent["identity"], expected_unique_id=parent["unique_id"])
        if graph.ingest(live) is None:
            raise RuntimeError("actual native owned-child chain unresolved")
        result["snapshots"].update(parent=parent, live_child=live)
        os.close(release_w);release_w = None
        deadline = time.monotonic() + 3
        zombie = None
        while time.monotonic() < deadline:
            zombie = native.read_snapshot(child)
            if zombie is not None and zombie["status"] == "zombie": break
            time.sleep(.005)
        if zombie is None or zombie["status"] != "zombie":
            raise RuntimeError("owned zombie observation timeout")
        if zombie["identity"] != live["identity"] or zombie["unique_id"] != live["unique_id"]:
            raise RuntimeError("owned zombie native token drift")
        if graph.ingest(zombie) is None:
            raise RuntimeError("actual native zombie chain unresolved")
        if native.read_snapshot(child, False) is not None:
            raise RuntimeError("non-zombie query unexpectedly returned zombie")
        if process_identity._read_darwin(child) is not None:
            raise RuntimeError("existing core live identity accepted zombie")
        result["snapshots"]["zombie_child"] = zombie
    finally:
        for fd in (release_w, release_r, ready_w, ready_r):
            if fd is not None:
                try: os.close(fd)
                except OSError: pass
        if child is not None and child > 0:
            waited, status = os.waitpid(child, 0)
            result["children_reaped"].append(waited)
            result["child_wait_status"] = status
    result["after_reap"] = native.read_snapshot(child)
    if result["after_reap"] is not None:
        raise RuntimeError("reaped child is not numerically absent")
    result["status"] = "pass"
    return result


@unittest.skipUnless(sys.platform == "darwin", "actual native Darwin fixture unavailable on this platform")
class ActualDarwinTests(unittest.TestCase):
    def test_owned_child_live_zombie_and_reap(self):
        result = native_capability_fixture()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["children_created"], result["children_reaped"])
        self.assertIsNone(result["after_reap"])
        self.assertFalse(result["signals_sent"])


def native_exec_fixture():
    """A direct child execs its own interpreter, stays pipe-held, then is reaped."""
    if sys.platform != "darwin":
        raise native.UnsupportedObservation("native exec fixture requires Darwin")
    release_r, release_w = os.pipe()
    ready_r, ready_w = os.pipe()
    child = None
    result = {"signals_sent": False, "children_created": [], "children_reaped": []}
    try:
        child = os.fork()
        if child == 0:
            try:
                os.close(release_w);os.close(ready_r)
                os.write(ready_w, b"R")
                if os.read(release_r, 1) != b"E": os._exit(0)
                os.set_inheritable(release_r, True);os.set_inheritable(ready_w, True)
                code = f"import os;os.write({ready_w},b'E');os.read({release_r},1)"
                os.execv(sys.executable, [sys.executable, "-B", "-c", code])
            finally:
                os._exit(70)
        result["children_created"].append(child)
        os.close(release_r);release_r = None
        os.close(ready_w);ready_w = None
        if not select.select([ready_r], [], [], 3)[0] or os.read(ready_r, 1) != b"R":
            raise RuntimeError("owned exec child readiness timeout")
        before = native.read_snapshot(child)
        if before is None: raise RuntimeError("owned pre-exec child missing")
        graph = native.LineageGraph()
        graph.add_root(before, expected_identity=before["identity"], expected_unique_id=before["unique_id"])
        os.write(release_w, b"E")
        if not select.select([ready_r], [], [], 3)[0] or os.read(ready_r, 1) != b"E":
            raise RuntimeError("owned exec child acknowledgement timeout")
        after = native.read_snapshot(child)
        if after is None or before["identity"] != after["identity"] or before["unique_id"] != after["unique_id"]:
            raise RuntimeError("native birth/unique token not preserved across controlled exec")
        if after["idversion"] <= before["idversion"]:
            raise RuntimeError("controlled exec did not increase native idversion")
        graph.ingest(after)
        result.update(before_exec=before, after_exec=after)
    finally:
        for fd in (release_w, release_r, ready_w, ready_r):
            if fd is not None:
                try: os.close(fd)
                except OSError: pass
        if child is not None and child > 0:
            waited, status = os.waitpid(child, 0)
            result["children_reaped"].append(waited);result["child_wait_status"] = status
    result["after_reap"] = native.read_snapshot(child)
    if result["after_reap"] is not None: raise RuntimeError("reaped exec child not numerically absent")
    result["status"] = "pass"
    return result


@unittest.skipUnless(sys.platform == "darwin", "actual native Darwin fixture unavailable on this platform")
class ActualDarwinExecTests(unittest.TestCase):
    def test_owned_exec_keeps_birth_and_unique_token(self):
        result = native_exec_fixture()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["children_created"], result["children_reaped"])


if __name__ == "__main__":
    unittest.main()
