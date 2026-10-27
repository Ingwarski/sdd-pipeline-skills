"""Bounded, observation-only Darwin genealogy; never a signal capability.

The public libproc entry accepts a private XNU flavor. Its reviewed ABI comes
from apple-oss-distributions/xnu commit ac9718fb1af618d5ce8678d0dc6e8a58f252216f,
bsd/sys/proc_info_private.h (41-56,138-144), bsd/kern/proc_info.c
(1445-1454,2075-2091,2142-2171), and public sys/proc_info.h. Availability is
probed on every query; no fallback to PS, ordinary birth-only or PID matching.
A structurally valid receipt is not proof it came from a trusted observer.
Callers must protect provenance and bind the root to their actual managed launch.
"""
from __future__ import annotations

import copy
import ctypes
import errno
from functools import lru_cache
import json
import os
import socket
import sys
import time
import uuid

from .io import EvidenceError
from .process_identity import valid_identity

FLAVOR = 18
ABI = "xnu-proc_bsdinfowithuniqid-192-v1"
MAX_SNAPSHOT_BYTES = 4096
_U64 = 2**64 - 1
_I31 = 2**31 - 1


class ObservationError(EvidenceError):
    """Unknown, denied or inconsistent native observation; never absence."""


class UnsupportedObservation(ObservationError):
    """Platform, library, flavor or layout is unsupported."""


class _BSD(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint32) for n in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid",
        "rgid", "svuid", "svgid", "reserved")]
    _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
    _fields_ += [(n, ctypes.c_uint32) for n in ("nfiles", "pgid", "jobc", "tdev", "tpgid")]
    _fields_ += [("nice", ctypes.c_int32), ("seconds", ctypes.c_uint64), ("microseconds", ctypes.c_uint64)]


class _Unique(ctypes.Structure):
    _fields_ = [("executable_uuid", ctypes.c_ubyte * 16), ("unique_id", ctypes.c_uint64),
                ("parent_unique_id", ctypes.c_uint64), ("idversion", ctypes.c_int32),
                ("parent_idversion", ctypes.c_int32), ("reserved2", ctypes.c_uint64),
                ("reserved3", ctypes.c_uint64)]


class _Combined(ctypes.Structure):
    _fields_ = [("bsd", _BSD), ("unique", _Unique)]


def _check_layout():
    expected = ((_BSD, 136, {"flags": 0, "status": 4, "xstatus": 8, "pid": 12, "ppid": 16,
                              "uid": 20, "gid": 24, "ruid": 28, "rgid": 32, "svuid": 36,
                              "svgid": 40, "reserved": 44, "comm": 48, "name": 64,
                              "nfiles": 96, "pgid": 100, "jobc": 104, "tdev": 108,
                              "tpgid": 112, "nice": 116, "seconds": 120, "microseconds": 128}),
                (_Unique, 56, {"executable_uuid": 0, "unique_id": 16, "parent_unique_id": 24,
                               "idversion": 32, "parent_idversion": 36, "reserved2": 40, "reserved3": 48}),
                (_Combined, 192, {"bsd": 0, "unique": 136}))
    if ctypes.sizeof(ctypes.c_void_p) != 8 or sys.byteorder != "little":
        raise UnsupportedObservation("Darwin observation requires reviewed 64-bit little-endian ABI")
    for structure, size, offsets in expected:
        if (ctypes.sizeof(structure) != size or ctypes.alignment(structure) != 8
                or set(n for n, _ in structure._fields_) != set(offsets)
                or any(getattr(structure, n).offset != o for n, o in offsets.items())):
            raise UnsupportedObservation("Darwin observation ABI layout mismatch")


@lru_cache(maxsize=1)
def _library():
    try:
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        library.proc_pidinfo.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int)
        library.proc_pidinfo.restype = ctypes.c_int
        return library
    except (OSError, AttributeError) as error:
        raise UnsupportedObservation("Darwin libproc entry unavailable") from error


@lru_cache(maxsize=1)
def _boot_uuid():
    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        function = libc.sysctlbyname
        function.argtypes = (ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t)
        function.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(64)
        size = ctypes.c_size_t(64)
        ctypes.set_errno(0)
        result = function(b"kern.bootsessionuuid", buffer, ctypes.byref(size), None, 0)
        if result != 0 or size.value != 37 or buffer.raw[36:37] != b"\0":
            raise UnsupportedObservation("cannot establish bounded Darwin boot session UUID")
        return str(uuid.UUID(buffer.raw[:36].decode("ascii")))
    except (OSError, AttributeError, UnicodeError, ValueError) as error:
        raise UnsupportedObservation("Darwin boot session UUID unavailable") from error


def _integer(value, maximum=_U64, minimum=0):
    return type(value) is int and minimum <= value <= maximum


def _decimal(value, minimum=1):
    return (type(value) is str and 0 < len(value) <= 20 and value.isascii()
            and value.isdecimal() and str(int(value)) == value and minimum <= int(value) <= _U64)


def _uuid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value and uuid.UUID(value).int != 0
    except (ValueError, AttributeError):
        return False


def valid_snapshot(value, *, local=False):
    """Strict bounded JSON shape validation, not authentication or authority."""
    keys = {"version", "identity", "boot_uuid", "uid", "current_ppid", "pgid", "status",
            "unique_id", "original_parent_unique_id", "idversion", "original_parent_idversion",
            "executable_uuid", "query", "observed"}
    if type(local) is not bool or type(value) is not dict or set(value) != keys:
        return False
    identity, query, observed = value["identity"], value["query"], value["observed"]
    if not (type(value["version"]) is int and value["version"] == 1
            and valid_identity(identity, local=local) and identity["platform"] == "darwin"
            and _uuid(value["boot_uuid"]) and _uuid(value["executable_uuid"])
            and _integer(value["uid"], 2**32 - 1)
            and _integer(value["current_ppid"], _I31) and value["current_ppid"] != identity["pid"]
            and _integer(value["pgid"], _I31, 1)
            and type(value["status"]) is str and value["status"] in ("alive", "zombie")
            and _decimal(value["unique_id"]) and _decimal(value["original_parent_unique_id"])
            and value["unique_id"] != value["original_parent_unique_id"]
            and _integer(value["idversion"], _I31, -2**31) and value["idversion"] != 0
            and _integer(value["original_parent_idversion"], _I31, -2**31)
            and value["original_parent_idversion"] != 0):
        return False
    if (type(query) is not dict or set(query) != {"api", "flavor", "arg", "abi", "size", "returned_size", "errno", "native_status"}
            or query["api"] != "libproc.proc_pidinfo" or query["abi"] != ABI
            or any(type(query[k]) is not int for k in ("flavor", "arg", "size", "returned_size", "errno", "native_status"))
            or query["flavor"] != FLAVOR or query["arg"] not in (0, 1)
            or query["size"] != 192 or query["returned_size"] != 192 or query["errno"] != 0
            or query["native_status"] not in (1, 2, 3, 4, 5)
            or (query["native_status"] == 5) != (value["status"] == "zombie")
            or (value["status"] == "zombie" and query["arg"] != 1)):
        return False
    if (type(observed) is not dict or set(observed) != {"wall_time_ns", "monotonic_ns"}
            or not all(_decimal(v) for v in observed.values())):
        return False
    birth_ns = identity["created"]["seconds"] * 10**9 + identity["created"]["microseconds"] * 1000
    if birth_ns > int(observed["wall_time_ns"]):
        return False
    if local and (value["uid"] != os.geteuid() or value["boot_uuid"] != _boot_uuid()):
        return False
    try:
        return len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode("ascii")) <= MAX_SNAPSHOT_BYTES
    except (TypeError, ValueError, OverflowError):
        return False


def read_snapshot(pid, include_zombie=True):
    """Return a native receipt, or None ONLY for numeric ESRCH.

    include_zombie=False may return ESRCH for an unreaped zombie: it is not an
    absence probe. Use the default True for numeric absence observations.
    Zombie identities here are observation-only; core live identity is unchanged.
    """
    if type(pid) is not int or not 0 < pid <= _I31 or type(include_zombie) is not bool:
        raise ObservationError("positive integer PID and boolean include_zombie required")
    if sys.platform != "darwin":
        raise UnsupportedObservation("Darwin native observation unavailable on this platform")
    _check_layout()
    boot = _boot_uuid()
    data = _Combined()
    ctypes.set_errno(0)
    count = _library().proc_pidinfo(pid, FLAVOR, int(include_zombie), ctypes.byref(data), ctypes.sizeof(data))
    error = ctypes.get_errno()
    if count == 0 and error == errno.ESRCH:
        return None
    if count != 192 or error != 0:
        kind = UnsupportedObservation if error in (errno.EINVAL, errno.ENOTSUP, errno.ENOSYS) else ObservationError
        raise kind(f"Darwin combined query failed: returned_size={count}, errno={error}, expected_size=192")
    b, u = data.bsd, data.unique
    if b.pid != pid or b.uid != os.geteuid() or b.reserved or u.reserved2 or u.reserved3:
        raise ObservationError("Darwin PID/UID or reserved ABI fields mismatch")
    value = {
        "version": 1, "identity": {"version": 1, "host": socket.gethostname(), "platform": "darwin", "pid": pid,
                                  "created": {"seconds": b.seconds, "microseconds": b.microseconds}},
        "boot_uuid": boot, "uid": b.uid, "current_ppid": b.ppid, "pgid": b.pgid,
        "status": "zombie" if b.status == 5 else "alive", "unique_id": str(u.unique_id),
        "original_parent_unique_id": str(u.parent_unique_id), "idversion": u.idversion,
        "original_parent_idversion": u.parent_idversion,
        "executable_uuid": str(uuid.UUID(bytes=bytes(u.executable_uuid))),
        "query": {"api": "libproc.proc_pidinfo", "flavor": FLAVOR, "arg": int(include_zombie), "abi": ABI,
                  "size": 192, "returned_size": count, "errno": error, "native_status": b.status},
        "observed": {"wall_time_ns": str(time.time_ns()), "monotonic_ns": str(time.monotonic_ns())}}
    if not valid_snapshot(value, local=True):
        raise ObservationError("invalid Darwin combined process observation")
    return value


class LineageGraph:
    """Pure bounded receipt graph. Verified genealogy grants NO resource rights.

    Ingest only actual protected native receipts. Missing parents/versions remain
    pending; this class cannot discover missing intermediaries or authenticate JSON.
    Keep one graph per managed launch. Reused numeric PIDs are rejected, rather
    than replacing the old token. Exec versions are retained in bounded history.
    """
    def __init__(self, max_nodes=256, *, max_updates=4096):
        if not _integer(max_nodes, 256, 1) or not _integer(max_updates, 65536, 1):
            raise ObservationError("invalid lineage graph bounds")
        self._max_nodes, self._max_updates = max_nodes, max_updates
        self._nodes, self._pids, self._versions = {}, {}, {}
        self._root, self._updates = None, 0

    def add_root(self, snapshot, *, expected_identity, expected_unique_id):
        if self._root is not None or self._nodes:
            raise ObservationError("lineage root must be first and unique")
        if (not valid_snapshot(snapshot) or not valid_identity(expected_identity)
                or snapshot["identity"] != expected_identity or snapshot["unique_id"] != expected_unique_id
                or snapshot["status"] != "alive"):
            raise ObservationError("root does not match exact managed identity and unique ID")
        self._root = snapshot["unique_id"]
        try:
            return self.ingest(snapshot)
        except Exception:
            self._root = None
            raise

    def ingest(self, snapshot):
        if not valid_snapshot(snapshot):
            raise ObservationError("invalid native lineage receipt")
        if self._root is None:
            raise ObservationError("managed root is not anchored")
        key, pid = snapshot["unique_id"], snapshot["identity"]["pid"]
        prior = self._nodes.get(key)
        if prior == snapshot:
            return self.lineage(key)
        if self._updates >= self._max_updates or (prior is None and len(self._nodes) >= self._max_nodes):
            raise ObservationError("lineage graph bound exceeded")
        if pid in self._pids and self._pids[pid] != key:
            raise ObservationError("reused PID cannot overwrite a previous native token")
        if self._nodes:
            root = self._nodes[self._root]
            if any(snapshot[k] != root[k] for k in ("boot_uuid", "uid")) or any(
                    snapshot["identity"][k] != root["identity"][k] for k in ("host", "platform")):
                raise ObservationError("lineage host/boot/UID mismatch")
        if prior:
            immutable = ("identity", "boot_uuid", "uid", "unique_id", "original_parent_unique_id", "original_parent_idversion")
            if any(prior[k] != snapshot[k] for k in immutable):
                raise ObservationError("native process token or lineage changed")
            if any(int(snapshot["observed"][k]) <= int(prior["observed"][k]) for k in ("monotonic_ns", "wall_time_ns")):
                raise ObservationError("native observation chronology regressed")
            if prior["status"] == "zombie" and snapshot["status"] != "zombie":
                raise ObservationError("zombie cannot become alive")
            changed_exec = prior["executable_uuid"] != snapshot["executable_uuid"]
            if snapshot["idversion"] < prior["idversion"] or (changed_exec and snapshot["idversion"] == prior["idversion"]):
                raise ObservationError("exec version chronology inconsistent")
        candidate = dict(self._nodes)
        candidate[key] = snapshot
        self._check_edges(candidate)
        versions = set(self._versions.get(key, ())) | {snapshot["idversion"]}
        if len(versions) > 32:
            raise ObservationError("native exec history bound exceeded")
        self._nodes[key] = copy.deepcopy(snapshot)
        self._pids[pid], self._versions[key] = key, versions
        self._updates += 1
        return self.lineage(key)

    @staticmethod
    def _check_edges(nodes):
        for key, node in nodes.items():
            seen = {key}
            parent_id = node["original_parent_unique_id"]
            child = node
            while parent_id in nodes:
                if parent_id in seen:
                    raise ObservationError("native lineage cycle")
                seen.add(parent_id)
                parent = nodes[parent_id]
                birth = lambda n: (n["identity"]["created"]["seconds"], n["identity"]["created"]["microseconds"])
                if birth(parent) > birth(child):
                    raise ObservationError("parent birth follows child birth")
                child, parent_id = parent, parent["original_parent_unique_id"]

    def lineage(self, unique_id):
        """Root-to-node receipt copies, or None when an exact edge is missing."""
        if not _decimal(unique_id) or self._root is None:
            return None
        chain, key = [], unique_id
        for _ in range(self._max_nodes):
            node = self._nodes.get(key)
            if node is None:
                return None
            chain.append(copy.deepcopy(node))
            if key == self._root:
                return list(reversed(chain))
            parent = node["original_parent_unique_id"]
            if node["original_parent_idversion"] not in self._versions.get(parent, ()):
                return None
            key = parent
        raise ObservationError("native lineage depth bound exceeded")

    def pending(self):
        return tuple(sorted(key for key in self._nodes if self.lineage(key) is None))
