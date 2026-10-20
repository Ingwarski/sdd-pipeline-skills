"""Local process identities for scoped, restart-safe resource recovery.

An identity is a process-birth observation, not authorization to stop a process;
the caller must bind it to a resource that the managed run owns. Unknown or
foreign identities fail closed. No function here signals an entire process group.

Linux signals use a pidfd; kernels without that facility require external
recovery rather than an unsafe PID-only fallback. Windows checks creation time
on the same opened handle used for termination. macOS has no equivalent process
handle for kill(2): libproc's precise birth time is checked twice immediately
before the signal, but a final check-to-signal race remains. Callers must retain
their launch/gate ownership controls; this helper is not a universal OS sandbox.
"""
from __future__ import annotations

import ctypes
import errno
from functools import lru_cache
import os
from pathlib import Path
import signal
import socket
import sys
import uuid

from .io import EvidenceError


def _pid(value):
    return type(value) is int and 0 < value <= 2**31 - 1


def _integer(value, *, maximum=2**64 - 1, positive=False):
    return type(value) is int and (0 < value if positive else 0 <= value) and value <= maximum


def _created_valid(value, platform):
    if not isinstance(value, dict):
        return False
    if platform == "linux":
        if set(value) != {"boot_id", "start_ticks"} or not _integer(value["start_ticks"]):
            return False
        try:
            return isinstance(value["boot_id"], str) and str(uuid.UUID(value["boot_id"])) == value["boot_id"]
        except ValueError:
            return False
    if platform == "darwin":
        return (set(value) == {"seconds", "microseconds"}
                and _integer(value["seconds"], positive=True)
                and _integer(value["microseconds"], maximum=999999))
    if platform == "win32":
        return set(value) == {"ticks"} and _integer(value["ticks"], positive=True)
    return False


def valid_identity(record, *, local=False):
    """Validate portable structure; local=True also requires this host/platform."""
    return (type(local) is bool and isinstance(record, dict)
            and set(record) == {"version", "host", "platform", "pid", "created"}
            and type(record["version"]) is int and record["version"] == 1
            and isinstance(record["host"], str) and 0 < len(record["host"]) <= 255
            and not any(ord(character) < 32 or ord(character) == 127 for character in record["host"])
            and isinstance(record["platform"], str)
            and (not local or (record["host"] == socket.gethostname() and record["platform"] == sys.platform))
            and _pid(record["pid"])
            and _created_valid(record["created"], record["platform"]))


def _bounded_bytes(path, maximum):
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise EvidenceError("process identity exceeds its read bound")
    return data


def _read_linux(pid):
    try:
        raw = _bounded_bytes(Path("/proc") / str(pid) / "stat", 65536)
    except (FileNotFoundError, ProcessLookupError):
        return None
    # comm can contain spaces and parentheses. Fields after the final closing
    # parenthesis start at field 3; starttime is field 22.
    closing = raw.rfind(b")")
    opening = raw.find(b"(")
    fields = raw[closing + 1:].split()
    if opening <= 0 or closing <= opening or len(fields) < 20 or int(raw[:opening].strip()) != pid:
        raise EvidenceError("invalid Linux process identity")
    if fields[0] in (b"Z", b"X", b"x"):
        return None  # Exited/zombie processes cannot remain active writers.
    result = {"boot_id": _bounded_bytes(Path("/proc/sys/kernel/random/boot_id"), 64).decode("ascii").strip(),
              "start_ticks": int(fields[19])}
    if not _created_valid(result, "linux"):
        raise EvidenceError("invalid Linux process creation identity")
    return result


class _DarwinBSDInfo(ctypes.Structure):
    # SDK sys/proc_info.h: struct proc_bsdinfo, PROC_PIDTBSDINFO=3.
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid",
        "rgid", "svuid", "svgid", "reserved")]
    _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ("nfiles", "pgid", "jobc", "tdev", "tpgid")]
    _fields_ += [("nice", ctypes.c_int32), ("seconds", ctypes.c_uint64), ("microseconds", ctypes.c_uint64)]


@lru_cache(maxsize=1)
def _darwin_library():
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    library.proc_pidinfo.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int)
    library.proc_pidinfo.restype = ctypes.c_int
    return library


def _read_darwin(pid):
    result = _DarwinBSDInfo()
    ctypes.set_errno(0)
    count = _darwin_library().proc_pidinfo(pid, 3, 0, ctypes.byref(result), ctypes.sizeof(result))
    if count != ctypes.sizeof(result):
        error = ctypes.get_errno()
        if error == errno.ESRCH:
            return None
        raise OSError(error or errno.EIO, "cannot read precise macOS process identity")
    if result.pid != pid:
        raise EvidenceError("macOS process identity changed during query")
    if result.status == 5:  # SZOMB from sys/proc.h.
        return None
    created = {"seconds": result.seconds, "microseconds": result.microseconds}
    if not _created_valid(created, "darwin"):
        raise EvidenceError("invalid macOS process creation identity")
    return created


@lru_cache(maxsize=1)
def _windows_kernel():
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _windows_error():
    return ctypes.get_last_error()


def _windows_open(kernel, pid, *, terminate=False):
    # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION; no termination right for
    # state/identity queries. Add it only when explicitly stopping an owned run.
    handle = kernel.OpenProcess(0x100000 | 0x1000 | (0x0001 if terminate else 0), False, pid)
    if not handle:
        error = _windows_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: nonexistent PID.
            return None
        raise OSError(error, "cannot open process identity handle")
    return handle


def _windows_created(kernel, handle):
    from ctypes import wintypes
    status = kernel.WaitForSingleObject(handle, 0)
    if status == 0:  # WAIT_OBJECT_0, including a process whose exit code is 259.
        return None
    if status != 258:  # WAIT_TIMEOUT
        raise OSError(_windows_error(), "cannot verify process handle liveness")
    creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time),
                                  ctypes.byref(kernel_time), ctypes.byref(user_time)):
        raise OSError(_windows_error(), "cannot read process creation time")
    created = {"ticks": (creation.dwHighDateTime << 32) | creation.dwLowDateTime}
    if not _created_valid(created, "win32"):
        raise EvidenceError("invalid Windows process creation identity")
    return created


def _read_windows(pid):
    kernel = _windows_kernel()
    handle = _windows_open(kernel, pid)
    if handle is None:
        return None
    try:
        return _windows_created(kernel, handle)
    finally:
        kernel.CloseHandle(handle)


def _read(pid):
    if sys.platform == "linux":
        return _read_linux(pid)
    if sys.platform == "darwin":
        return _read_darwin(pid)
    if sys.platform == "win32":
        return _read_windows(pid)
    raise EvidenceError("process identity is unavailable on this platform")


def identity(pid=None):
    """Read a JSON-serializable local process birth identity; never signal it."""
    pid = os.getpid() if pid is None else pid
    if not _pid(pid):
        raise EvidenceError("process identity requires a positive integer PID")
    try:
        created = _read(pid)
    except (OSError, ValueError) as error:
        raise EvidenceError("cannot establish process creation identity: " + str(error)) from error
    if created is None:
        raise EvidenceError("process exited before its identity could be recorded")
    return {"version": 1, "host": socket.gethostname(), "platform": sys.platform,
            "pid": pid, "created": created}


def state(record):
    """Return alive, gone (including a replaced PID), or unknown; never signal."""
    if not valid_identity(record, local=True):
        return "unknown"
    try:
        created = _read(record["pid"])
    except (OSError, ValueError):
        return "unknown"
    return "alive" if created == record["created"] else "gone"


def _terminate_linux(record, sig):
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return "unknown"
    try:
        descriptor = os.pidfd_open(record["pid"], 0)
    except ProcessLookupError:
        return "gone"
    try:
        # Open first, then verify birth. Even if the process exits afterward,
        # the descriptor cannot be redirected to a recycled PID.
        status = state(record)
        if status != "alive":
            return status
        try:
            signal.pidfd_send_signal(descriptor, sig, None, 0)
        except ProcessLookupError:
            return "gone"
        return "signalled"
    finally:
        os.close(descriptor)


def _terminate_windows(record):
    kernel = _windows_kernel()
    handle = _windows_open(kernel, record["pid"], terminate=True)
    if handle is None:
        return "gone"
    try:
        if _windows_created(kernel, handle) != record["created"]:
            return "gone"
        if not kernel.TerminateProcess(handle, 1):
            if _windows_created(kernel, handle) is None:
                return "gone"
            raise OSError(_windows_error(), "cannot terminate owned process")
        return "signalled"
    finally:
        kernel.CloseHandle(handle)


def terminate(record, *, force=False):
    """Signal this owned process only; callers must wait for verified exit.

    Returns signalled/gone/unknown. force selects SIGKILL instead of SIGTERM on
    POSIX. Windows uses TerminateProcess in either case; graceful cancellation
    must occur through the managed command's own cooperative channel first.
    """
    if not valid_identity(record, local=True) or type(force) is not bool or record["pid"] in (1, os.getpid()):
        return "unknown"
    try:
        if sys.platform == "win32":
            return _terminate_windows(record)
        sig = signal.SIGKILL if force else signal.SIGTERM
        if sys.platform == "linux":
            return _terminate_linux(record, sig)
        if sys.platform == "darwin":
            # There is no pidfd equivalent for kill(2) here. Repeat the precise
            # birth query immediately before signalling; see module limitation.
            for _ in range(2):
                status = state(record)
                if status != "alive":
                    return status
            try:
                os.kill(record["pid"], sig)
            except ProcessLookupError:
                return "gone"
            return "signalled"
    except (OSError, ValueError):
        return "unknown"
    return "unknown"
