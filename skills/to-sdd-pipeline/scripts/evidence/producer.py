"""Bounded managed-producer wrapper; no shell, scheduler, or background daemon.

The wrapper reserves capacity before launching and stops its own process group
when observed output exceeds that reservation. It is not an OS sandbox: writes
outside the registered folder, unobserved rapid overwrites, or a deliberately
escaped process can bypass it. Required accounting/acceptance must still reject
incomplete evidence rather than describing this monitor as universal prevention.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import time

from .io import EvidenceError, _is_link, _parents, hash_file


class _WindowsJob:
    """Task-owned Windows job: closing/terminating it also stops helper children."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_longlong) for name in ("TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")] + [(name, wintypes.DWORD) for name in ("TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")]
        self.Counters = Counters
        kernel = self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise EvidenceError("cannot create a task-owned Windows process job")
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise EvidenceError("cannot configure Windows helper-process cleanup")

    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise EvidenceError("host prevents task-owned Windows process accounting; producer stopped")

    def active(self):
        result = self.Counters()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, self.ctypes.byref(result), self.ctypes.sizeof(result), None):
            raise EvidenceError("cannot verify task-owned Windows helper-process exit")
        return bool(result.ActiveProcesses)

    def stop(self):
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise EvidenceError("cannot stop task-owned Windows producer job")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _group_exists(identifier):
    try:
        os.killpg(identifier, 0)
        return True
    except ProcessLookupError:
        return False


def _stop_owned(process, job=None):
    """Terminate only this launch's process tree and wait before reporting exit."""
    if job is not None:
        if job.active():
            job.stop()
        process.wait(timeout=5)
        deadline = time.monotonic() + 5
        while job.active() and time.monotonic() < deadline:
            time.sleep(0.05)
        if job.active():
            raise EvidenceError("task-owned Windows helper processes did not exit")
        return
    if os.name == "posix":
        if _group_exists(process.pid):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if _group_exists(process.pid):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        deadline = time.monotonic() + 2
        while _group_exists(process.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if _group_exists(process.pid):
            os.killpg(process.pid, signal.SIGKILL)
            deadline = time.monotonic() + 2
            while _group_exists(process.pid) and time.monotonic() < deadline:
                time.sleep(0.05)
        if _group_exists(process.pid):
            raise EvidenceError("task-owned helper process group has not exited")
    else:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


def _inventory(root):
    _parents(root / "placeholder")
    if not root.is_dir() or _is_link(root.lstat()):
        raise EvidenceError("managed output directory was replaced or linked")
    result = {}
    for directory, subdirs, files in os.walk(root, followlinks=False):
        for name in subdirs:
            info = (Path(directory) / name).lstat()
            if _is_link(info) or not stat.S_ISDIR(info.st_mode):
                raise EvidenceError("unsafe managed output subdirectory")
        for name in files:
            path = Path(directory) / name
            info = path.lstat()
            if _is_link(info) or not stat.S_ISREG(info.st_mode):
                raise EvidenceError("unsafe managed output file: " + str(path))
            result[path.relative_to(root).as_posix()] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return result


def run_producer(ledger, run_id: str, unit_id: str, output_dir, command: list,
                 reserve_bytes: int, reserve_files: int, *, timeout=3600,
                 poll_interval=0.25) -> dict:
    """Reserve, launch, monitor, stop, reconcile, and seal one managed attempt.

    The byte/file allowance includes ``producer.log``. Logs are never truncated;
    exceeding the allowance stops the responsible process and preserves partial
    observations with an incomplete status. ``SDD_EVIDENCE_OUTPUT_DIR`` names the
    registered folder for the producer. The command is an argv list, never shell
    source. Existing nonempty output folders are rejected.
    """
    if not isinstance(command, list) or not command or any(not isinstance(value, str) or not value or "\0" in value for value in command):
        raise EvidenceError("producer command must be a nonempty argv list")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 86400:
        raise EvidenceError("producer timeout must be > 0 and <= 86400 seconds")
    if not 0.01 <= poll_interval <= 10:
        raise EvidenceError("producer poll interval must be between 0.01 and 10 seconds")
    root = Path(output_dir).absolute()
    if not root.is_dir() or _is_link(root.lstat()) or any(root.iterdir()):
        raise EvidenceError("producer needs a registered empty regular output directory")
    if reserve_files < 1:
        raise EvidenceError("producer reservation must include its one log file")
    reservation = ledger.reserve(run_id, unit_id, reserve_bytes, reserve_files,
                                 local_bytes=reserve_bytes, capacity_path=root)
    try:
        output_id = ledger.register_output(run_id, unit_id, root)
    except BaseException:
        ledger.cancel(reservation)
        raise
    process, job, problem, cleanup_problem, interrupted = None, None, None, None, None
    previous, gross_bytes, gross_files, last_inventory = {}, 0, 0, {}
    log = root / "producer.log"
    environment = os.environ.copy()
    environment["SDD_EVIDENCE_OUTPUT_DIR"] = str(root)

    def observe():
        nonlocal previous, gross_bytes, gross_files, last_inventory
        current = _inventory(root)
        for name, value in current.items():
            old = previous.get(name)
            if old is None or value[:2] != old[:2] or value[2] < old[2]:
                gross_bytes += value[2]
                gross_files += 1
            elif value[2] > old[2]:
                gross_bytes += value[2] - old[2]
            elif name != "producer.log" and value[3:] != old[3:]:
                # Observed same-length rewrites conservatively charge the whole
                # logical file again. Changes between polls remain unobservable.
                gross_bytes += value[2]
                gross_files += 1
        previous = last_inventory = current
        if gross_bytes > reserve_bytes or gross_files > reserve_files:
            raise EvidenceError("producer exceeded its reserved aggregate output allowance")
        if shutil.disk_usage(root).free < ledger.policy["limits"]["free_space_reserve_bytes"]:
            raise EvidenceError("producer cannot preserve configured free-space reserve")

    try:
        if os.name == "nt":
            job = _WindowsJob()
        descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            process = subprocess.Popen(command, cwd=root, env=environment, stdout=handle, stderr=subprocess.STDOUT,
                                       start_new_session=os.name == "posix",
                                       creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0)
            if job is not None:
                job.assign(process)
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                observe()
                if time.monotonic() >= deadline:
                    raise EvidenceError("producer timeout expired")
                time.sleep(min(poll_interval, max(0.01, deadline - time.monotonic())))
            observe()
            if process.returncode:
                problem = "producer exited with code " + str(process.returncode)
    except BaseException as exc:
        problem = str(exc) or type(exc).__name__
        if not isinstance(exc, (EvidenceError, OSError, subprocess.SubprocessError)):
            interrupted = exc
    finally:
        if process is not None:
            try:
                _stop_owned(process, job)
            except (EvidenceError, OSError, subprocess.SubprocessError) as exc:
                cleanup_problem = str(exc)
                problem = problem or cleanup_problem
        if job is not None:
            job.close()
    # All task-owned writers have stopped before stable-byte accounting. Unsafe
    # outputs are preserved but cannot support completion or byte-hash claims.
    try:
        observe()
    except EvidenceError as exc:
        problem = problem or str(exc)
    stable_files, current_bytes = {}, 0
    try:
        for name in last_inventory:
            digest, size = hash_file(root / name)
            stable_files[name] = {"content_hash": digest, "size": size}
            current_bytes += size
    except EvidenceError as exc:
        problem = problem or str(exc)
    # Charge at least every surviving file even if launch/monitoring failed.
    gross_bytes, gross_files = max(gross_bytes, current_bytes), max(gross_files, len(stable_files))
    settlement = ledger.settle(reservation, gross_bytes, gross_files, local_bytes=current_bytes)
    incomplete = bool(problem or cleanup_problem or settlement["incomplete"])
    if incomplete:
        ledger.mark_incomplete(run_id)
    else:
        ledger.acknowledge_output(output_id)
        ledger.complete_run(run_id)
    if interrupted is not None:
        raise interrupted
    return {"run_id": run_id, "unit_id": unit_id, "output_id": output_id,
            "accounting_mode": "managed-generation",
            "reservation_id": reservation, "status": "incomplete" if incomplete else "complete",
            "exit_code": process.returncode if process is not None else None,
            "problem": problem, "cleanup_problem": cleanup_problem,
            "gross_bytes": gross_bytes, "gross_files": gross_files,
            "observations": stable_files, "accounting": settlement,
            "enforcement": "task-owned process group and registered outputs; external writes and unobserved overwrites can bypass the monitor"}
