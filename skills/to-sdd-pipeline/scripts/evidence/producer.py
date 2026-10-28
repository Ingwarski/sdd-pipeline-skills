"""Bounded managed-producer wrapper with a finite interruption guardian.

The wrapper reserves capacity before launching and stops its own process group
when observed output exceeds that reservation. It is not an OS sandbox: writes
outside the registered folder, unobserved rapid overwrites, or a deliberately
escaped process can bypass it. Required accounting/acceptance must still reject
incomplete evidence rather than describing this monitor as universal prevention.
"""
from __future__ import annotations

from contextlib import ExitStack

import os
import json
import sys
import threading
import uuid
from datetime import datetime, timezone
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


def _run_monitored(ledger, run_id: str, unit_id: str, output_dir, command: list,
                 reserve_bytes: int, reserve_files: int, *, timeout=3600,
                 poll_interval=0.25, complete_run=True, attempt=None, cancelled=None) -> dict:
    """Reserve, launch, monitor, stop, reconcile, and seal one managed attempt.

    The byte/file allowance includes ``producer.log``. Logs are never truncated;
    exceeding the allowance stops the responsible process and preserves partial
    observations with an incomplete status. ``SDD_EVIDENCE_OUTPUT_DIR`` names the
    registered folder for the producer. The command is an argv list, never shell
    source. Existing nonempty output folders are rejected. Parallel workers use
    ``complete_run=False``; their coordinator calls ``ledger.complete_run`` only
    after every worker has settled and every required output is reconciled.
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
    initial_output_identity = [root.lstat().st_dev, root.lstat().st_ino]
    if reserve_files < 1:
        raise EvidenceError("producer reservation must include its one log file")
    if attempt is None:
        reservation = ledger.reserve(run_id, unit_id, reserve_bytes, reserve_files,
                                     local_bytes=reserve_bytes, capacity_path=root)
        try:
            output_id = ledger.register_output(run_id, unit_id, root)
        except BaseException:
            ledger.cancel(reservation)
            raise
    else:
        from . import producer_runtime as runtime
        record = runtime.read(ledger, attempt)
        reservation, output_id = record['reservation_id'], record['output_id']
    process, job, problem, cleanup_problem, interrupted = None, None, None, None, None
    previous, gross_bytes, gross_files, last_inventory = {}, 0, 0, {}
    managed, exit_code, writers_stopped = None, None, False
    log = root / "producer.log"
    environment = os.environ.copy()
    environment["SDD_EVIDENCE_OUTPUT_DIR"] = str(root)

    def observe(*, check_limits=True):
        nonlocal previous, gross_bytes, gross_files, last_inventory
        current = _inventory(root)
        for name, value in current.items():
            old = previous.get(name)
            if old is None or value[:2] != old[:2] or value[2] < old[2]:
                gross_bytes += value[2]
                gross_files += 1
            elif value[2] > old[2]:
                gross_bytes += value[2] - old[2]
            elif value[3:] != old[3:]:
                # Observed same-length rewrites conservatively charge the whole
                # logical file again. Changes between polls remain unobservable.
                gross_bytes += value[2]
                gross_files += 1
        changed = current != previous
        previous = last_inventory = current
        if attempt is not None and changed:
            runtime.update(ledger, attempt, lambda v: v.update(observed_bytes=gross_bytes, observed_files=gross_files))
        if check_limits and (gross_bytes > reserve_bytes or gross_files > reserve_files):
            raise EvidenceError("producer exceeded its reserved aggregate output allowance")
        if check_limits and ledger._violations(ledger._totals(run_id, unit_id)):
            raise EvidenceError("producer cannot preserve aggregate resource/metadata limits")
        if check_limits and shutil.disk_usage(root).free < ledger.policy["limits"]["free_space_reserve_bytes"]:
            raise EvidenceError("producer cannot preserve configured free-space reserve")

    try:
        if cancelled is not None and cancelled.is_set():
            raise EvidenceError("producer coordinator stopped before launch; attempt incomplete")
        if os.name == "nt" and attempt is None:
            job = _WindowsJob()
        descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            ledger._check_publication_deadline()
            if attempt is None:
                process = subprocess.Popen(command, cwd=root, env=environment, stdout=handle, stderr=subprocess.STDOUT,
                    start_new_session=os.name == "posix",
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0)
                if job is not None:
                    job.assign(process)
            else:
                environment.update(SDD_PRODUCER_LEDGER=str(ledger.path), SDD_PRODUCER_ATTEMPT=attempt)
                environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + environment.get('PYTHONPATH', '')
                ledger._check_publication_deadline()
                managed = runtime.launch(ledger, attempt, command, cwd=root, env=environment,
                                         stdout=handle, stderr=subprocess.STDOUT)
                process, job = managed.process, managed.job
            deadline = time.monotonic() + timeout
            publication_end = ledger._publication_deadline()
            if publication_end is not None:
                deadline = min(deadline, publication_end)
            while (managed.poll() if managed else process.poll()) is None:
                if cancelled is not None and cancelled.is_set():
                    raise EvidenceError("producer coordinator stopped; attempt incomplete")
                observe()
                if time.monotonic() >= deadline:
                    raise EvidenceError("producer timeout expired")
                time.sleep(min(poll_interval, max(0.01, deadline - time.monotonic())))
            observe()
            exit_code = managed.poll() if managed else process.returncode
            if cancelled is not None and cancelled.is_set():
                problem = "producer coordinator stopped; attempt incomplete"
            elif exit_code:
                problem = "producer exited with code " + str(exit_code)
    except BaseException as exc:
        problem = str(exc) or type(exc).__name__
        if not isinstance(exc, (EvidenceError, OSError, subprocess.SubprocessError)):
            interrupted = exc
    finally:
        if attempt is not None:
            try:
                errors = runtime.stop_registered(ledger, attempt)
                if errors:
                    cleanup_problem = "; ".join(errors)
            except (EvidenceError, OSError) as exc:
                cleanup_problem = str(exc)
        if process is not None:
            try:
                if attempt is None or os.name == "nt":
                    _stop_owned(process, job)
                    writers_stopped = attempt is None
                else:
                    process.wait(timeout=5)
            except (EvidenceError, OSError, subprocess.SubprocessError) as exc:
                cleanup_problem = str(exc)
                problem = problem or cleanup_problem
        if job is not None:
            job.close()
        if process is not None and process.stdin:
            process.stdin.close()
        if attempt is not None:
            try:
                errors = runtime.verify_stopped(ledger, attempt)
                writers_stopped = not errors
                errors += runtime.cleanup_directories(ledger, attempt) if not errors else []
                if errors:
                    cleanup_problem = "; ".join(errors)
            except (EvidenceError, OSError) as exc:
                cleanup_problem = str(exc)
    # All task-owned writers have stopped before stable-byte accounting. Unsafe
    # outputs are preserved but cannot support completion or byte-hash claims.
    inventory_known = not cleanup_problem
    final_observation_problem = None if writers_stopped else "task-owned writer exit is not verified"
    try:
        observe(check_limits=False)
    except (EvidenceError, OSError) as exc:
        problem = problem or str(exc)
        final_observation_problem = "final inventory: " + str(exc)
        inventory_known = False
    stable_files, current_bytes = {}, 0
    try:
        if not writers_stopped and attempt is not None and runtime.read(ledger, attempt)['version'] == 2:
            raise EvidenceError('observed writer closure must precede stable hashes/settlement')
        for name in last_inventory:
            digest, size = hash_file(root / name)
            stable_files[name] = {"content_hash": digest, "size": size}
            current_bytes += size
        if _inventory(root) != last_inventory:
            raise EvidenceError("managed output changed during final hash pass")
        expected_identity = record['output_identity'] if attempt is not None else initial_output_identity
        if [root.lstat().st_dev, root.lstat().st_ino] != expected_identity:
            raise EvidenceError("managed output directory identity changed before final observation")
    except (EvidenceError, OSError) as exc:
        problem = problem or str(exc)
        final_observation_problem = "final hashes: " + str(exc)
        inventory_known = False
    # Charge at least every surviving file even if launch/monitoring failed.
    gross_bytes, gross_files = max(gross_bytes, current_bytes), max(gross_files, len(stable_files))
    final_observation_complete = final_observation_problem is None
    if attempt is not None:
        final_observation = {
            "version": 1, "complete": final_observation_complete,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "gross_bytes": gross_bytes, "gross_files": gross_files,
            "output_identity": record["output_identity"], "observations": stable_files,
            "problem": final_observation_problem,
            "enforcement": "sampled managed observations; unobserved rewrites and external writers remain outside the monitor",
        }
        try:
            # Persist before settlement. A later accounting/guardian fault must
            # not erase the monitor's original final inventory again.
            runtime.update(ledger, attempt, lambda value: value.update(final_observation=final_observation))
        except (EvidenceError, OSError) as exc:
            inventory_known = final_observation_complete = False
            final_observation_problem = "final observation could not be durably recorded: " + str(exc)
            problem = problem or final_observation_problem
            # Reject the oversized/failed proof explicitly. Preserve raw files,
            # charge a lower bound and retain the entire reservation; never
            # truncate a hashset and describe it as a complete observation.
            failure = {"version": 1, "complete": False, "problem": final_observation_problem,
                       "observed_at": final_observation["observed_at"],
                       "gross_bytes": gross_bytes, "gross_files": gross_files}
            runtime.update(ledger, attempt, lambda value: value.update(final_observation=failure))
    if inventory_known:
        settlement = ledger.settle(reservation, gross_bytes, gross_files, local_bytes=current_bytes)
    else:
        # Missing/replaced roots and live helper processes cannot be measured
        # completely. Persist the observed lower bound without freeing capacity.
        settlement = ledger.record_uncertain(reservation, gross_bytes, gross_files)
    if cancelled is not None and cancelled.is_set():
        problem = problem or "producer coordinator stopped; attempt incomplete"
    incomplete = bool(problem or cleanup_problem or settlement["incomplete"])
    if incomplete:
        ledger.mark_incomplete(run_id)
    if inventory_known:
        ledger.acknowledge_output(output_id)
    if not incomplete:
        if complete_run:
            try:
                ledger.complete_run(run_id)
            except (EvidenceError, OSError, ValueError, KeyError, TypeError) as exc:
                if ledger._publication_channel is None:
                    raise
                ledger.mark_incomplete(run_id)
                incomplete, problem = True, 'worker completion publication failed: ' + str(exc)
        try:
            ledger._check_publication_deadline()
        except EvidenceError as exc:
            ledger.mark_incomplete(run_id)
            incomplete, problem = True, str(exc)
    if interrupted is not None:
        raise interrupted
    return {"run_id": run_id, "unit_id": unit_id, "output_id": output_id,
            "accounting_mode": "managed-generation",
            "reservation_id": reservation, "status": "incomplete" if incomplete else "complete",
            "run_completion": "deferred" if not complete_run else "requested",
            "exit_code": exit_code if exit_code is not None else (process.returncode if process is not None else None),
            "problem": problem, "cleanup_problem": cleanup_problem,
            "final_observation_complete": final_observation_complete,
            "final_observation_problem": final_observation_problem,
            "gross_bytes": gross_bytes, "gross_files": gross_files,
            "observations": stable_files, "accounting": settlement,
            "enforcement": "task-owned process group and registered outputs; external writes and unobserved overwrites can bypass the monitor"}


def recover_producers(ledger, *, dry_run=True):
    """Inspect/recover abandoned attempts without granting execution acceptance."""
    from . import producer_runtime as runtime, process_identity
    actions = []
    for row in ledger.connection.execute('SELECT id FROM producer_sessions').fetchall():
        isolated = ledger.connection.execute('SELECT 1 FROM producer_quarantines WHERE attempt_id=?', (row[0],)).fetchone()
        if isolated:
            # Even a damaged isolation receipt never authorizes mutating the
            # original failed session. Report it retained until repaired.
            readiness = ledger.generation_readiness()
            descriptor = next((item for item in readiness['quarantines'] if item['attempt_id'] == row[0]), None)
            action = {'attempt_id': row[0], 'action': 'retained', 'incomplete': True,
                      'problem': readiness['problem'] or 'quarantine is not currently verifiable'}
            if descriptor is not None and readiness['ready']:
                action = {key: descriptor[key] for key in ('attempt_id', 'run_id', 'intent_id', 'reservation_id')}
                action.update(action='quarantined', incomplete=False, historical_uncertainty=True,
                              quarantine_digest=descriptor['digest'])
            actions.append(action)
            continue
        try:
            value = runtime.read(ledger, row[0])
        except (EvidenceError, ValueError, KeyError, TypeError) as exc:
            actions.append({'attempt_id': row[0], 'action': 'retained', 'incomplete': True,
                            'problem': str(exc)})
            continue
        action = {key: value.get(key) for key in ('attempt_id', 'run_id', 'intent_id', 'reservation_id')}
        if value['status'] == 'terminal':
            pending = ledger.connection.execute("SELECT state FROM reservations WHERE id=?", (value['reservation_id'],)).fetchone()
            from .observed_writers import disposition_problems
            external_problems = disposition_problems(value, ledger=ledger)
            action.update(action='terminal', incomplete=bool(external_problems) or pending is None or pending[0] == 'pending')
            if external_problems:
                action['problems'] = external_problems
        else:
            owner = value.get('guardian') or value['coordinator']
            status = process_identity.state(owner)
            if status == 'alive':
                action.update(action='active', incomplete=False)
            elif status == 'unknown':
                action.update(action='retained', incomplete=True, problem='producer ownership cannot be verified')
            elif dry_run:
                action.update(action='retained', incomplete=True, problem='abandoned producer requires applied recovery')
            else:
                # Concurrent recovery clients serialize cleanup using a short
                # SQLite claim bound to exact process identity, not wall time.
                claim = process_identity.identity()
                claimed = False
                def acquire(v):
                    nonlocal claimed
                    prior = v.get('recovery_owner')
                    if prior and process_identity.state(prior) != 'gone':
                        return
                    v['recovery_owner'] = claim
                    claimed = True
                runtime.update(ledger, value['attempt_id'], acquire)
                if not claimed:
                    action.update(action='retained', incomplete=True, problem='producer recovery already active or ownership unknown')
                else:
                    stage = 'reservation-state'
                    try:
                        reservation = ledger.connection.execute('SELECT state FROM reservations WHERE id=?', (value['reservation_id'],)).fetchone()
                        pending = reservation is None or reservation[0] == 'pending'
                        if pending:
                            # The monitor is verified gone and this caller owns
                            # the recovery claim. Preserve its known floor before
                            # cleanup can fail; cleanup never refunds this hold.
                            stage = 'record-uncertain'
                            ledger.record_uncertain(value['reservation_id'], value.get('observed_bytes', 0), value.get('observed_files', 0))
                        stage = 'mark-incomplete'
                        ledger.mark_incomplete(value['run_id'])
                        stage = 'stop-registered'
                        problems = runtime.stop_registered(ledger, value['attempt_id'])
                        stage = 'verify-stopped'
                        problems += runtime.verify_stopped(ledger, value['attempt_id'])
                        if not problems:
                            stage = 'cleanup-directories'
                            try:
                                problems += runtime.cleanup_directories(ledger, value['attempt_id'])
                            except (EvidenceError, OSError) as exc:
                                problems.append('producer recovery stage=' + stage + ' problem=' + str(exc))
                        def completed(v):
                            problem = '; '.join(problems) or None
                            v.update(status='terminal' if not problems else 'stopping', recovery_owner=None,
                                     recovery_problem=problem)
                            if problem:
                                v.setdefault('first_recovery_failure', {
                                    'problem': problem[:2048], 'observed_at': datetime.now(timezone.utc).isoformat()})
                        stage = 'persist-recovery'
                        runtime.update(ledger, value['attempt_id'], completed)
                        action.update(action='retained' if pending or problems else 'cleaned', incomplete=bool(pending or problems), problems=problems)
                    except (EvidenceError, OSError, ValueError) as exc:
                        message = ('producer recovery stage=' + stage + ' problem='
                                   + (str(exc) or type(exc).__name__))[:2048]
                        action.update(action='retained', incomplete=True, problem=message)
                        def failed(v):
                            v.update(status='stopping', recovery_problem=message)
                            # Keep the first failed recovery as an observation;
                            # later successful cleanup may clear only the current
                            # problem, never this original failure record.
                            v.setdefault('first_recovery_failure', {
                                'problem': message, 'observed_at': datetime.now(timezone.utc).isoformat()})
                        try:
                            runtime.update(ledger, value['attempt_id'], failed)
                        except (EvidenceError, OSError, ValueError) as record_error:
                            action['problem'] = message + '; recovery diagnostic persistence failed: ' + str(record_error)[:512]
                    finally:
                        def release(v):
                            if v.get('recovery_owner') == claim:
                                v['recovery_owner'] = None
                        runtime.update(ledger, value['attempt_id'], release)
        actions.append(action)
    return {'actions': actions, 'incomplete': any(a['incomplete'] for a in actions)}


def _recovery_failure_diagnostic(recovered, attempt):
    """Bound the target's actual recovery result without exposing session data."""
    target = next((item for item in recovered['actions'] if item.get('attempt_id') == attempt), None)
    if target is None:
        return json.dumps({'attempt_id': attempt[:128], 'problem': 'target recovery action is missing'}, sort_keys=True)
    problem = target.get('problem') or '; '.join(str(item) for item in target.get('problems', []))
    return json.dumps({'attempt_id': str(target.get('attempt_id', ''))[:128],
                       'action': str(target.get('action', ''))[:32],
                       'incomplete': bool(target.get('incomplete')),
                       'problem': str(problem)[:768]}, sort_keys=True, ensure_ascii=True)


def run_producer(ledger, run_id: str, unit_id: str, output_dir, command: list,
                 reserve_bytes: int, reserve_files: int, *, timeout=3600,
                 poll_interval=.25, complete_run=True, intent_id=None, manager=None):
    """Public producer entry; quarantined history needs a live Manager source."""
    previous = ledger._publication_manager
    quarantined = bool(ledger.connection.execute('SELECT 1 FROM producer_quarantines LIMIT 1').fetchone())
    if quarantined and (manager is None or intent_id is None or os.name != 'posix'):
        raise EvidenceError('quarantined producer requires its live POSIX Manager and durable intent')
    deadline = time.monotonic() + timeout if type(timeout) in (int, float) else time.monotonic()
    if manager is not None:
        if ledger.path != manager.state / 'accounting.sqlite' or ledger.policy != manager.policy:
            raise EvidenceError('producer Manager differs from original accounting home/policy')
        ledger._publication_manager = (manager, intent_id, deadline if quarantined else None)
    try:
        with ExitStack() as cleanup:
            return _run_producer(ledger, run_id, unit_id, output_dir, command, reserve_bytes, reserve_files,
                timeout=timeout, poll_interval=poll_interval, complete_run=complete_run, intent_id=intent_id,
                manager=manager, publication_deadline=deadline, publication_cleanup=cleanup)
    finally:
        ledger._publication_manager = previous


def _run_producer(ledger, run_id: str, unit_id: str, output_dir, command: list,
                 reserve_bytes: int, reserve_files: int, *, timeout=3600,
                 poll_interval=.25, complete_run=True, intent_id=None, manager=None, publication_deadline=None,
                 publication_cleanup=None):
    """Monitor in a finite guardian outside the coordinator's process group.

    Coordinator EOF/cancellation stops this attempt, settles measured output and
    preserves failure. If the guardian dies too, resume keeps unknown charges
    reserved. No retry or product authorization is inferred from cleanup.
    """
    from . import producer_runtime as runtime, process_identity
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x or '\0' in x for x in command):
        raise EvidenceError('producer command must be a nonempty argv list')
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 86400:
        raise EvidenceError('producer timeout must be > 0 and <= 86400 seconds')
    if isinstance(poll_interval, bool) or not isinstance(poll_interval, (int, float)) or not .01 <= poll_interval <= 10:
        raise EvidenceError('producer poll interval must be between 0.01 and 10 seconds')
    root = Path(output_dir).absolute()
    fingerprint = runtime.directory_identity(root)
    if any(root.iterdir()) or reserve_files < 1:
        raise EvidenceError('producer needs an empty regular output directory and allowance for its log')
    recovery = recover_producers(ledger, dry_run=False)
    if recovery['incomplete']:
        raise EvidenceError('producer recovery incomplete; held capacity and resources require reconciliation')
    attempt = str(uuid.uuid4())
    coordinator = process_identity.identity()
    # Reserve bounded journal headroom before launch; actual DB bytes are already
    # included in the ledger's combined metadata/local accounting.
    value = dict(version=1, attempt_id=attempt, run_id=run_id, unit_id=unit_id,
        reservation_id=None, output_id=None, intent_id=intent_id,
        coordinator=coordinator, guardian=None, status='launching', processes={}, resources=[],
        output_dir=str(root), output_identity=fingerprint, policy=ledger.policy)
    reservation = ledger.reserve(run_id, unit_id, reserve_bytes, reserve_files,
        local_bytes=reserve_bytes, metadata_bytes=runtime.MAX_RECORD * 3, capacity_path=root,
        producer_record=value)
    try:
        output_id = ledger.register_output(run_id, unit_id, root)
        runtime.update(ledger, attempt, lambda v: v.update(output_id=output_id))
    except BaseException:
        ledger.cancel(reservation)
        runtime.update(ledger, attempt, lambda v: v.update(status='terminal'))
        raise
    request = dict(ledger=str(ledger.path), attempt=attempt, command=command,
                   reserve_bytes=reserve_bytes, reserve_files=reserve_files, timeout=timeout,
                   poll_interval=poll_interval, complete_run=complete_run)
    publication_parent, publication_child = None, None
    if ledger.connection.execute('SELECT 1 FROM producer_quarantines LIMIT 1').fetchone():
        if manager is None or intent_id is None or os.name != 'posix':
            raise EvidenceError('quarantined producer requires its live POSIX Manager and durable intent')
        import socket
        from .quarantine_device import PublicationChannel
        parent, publication_child = socket.socketpair()
        publication_cleanup.callback(parent.close)
        publication_cleanup.callback(publication_child.close)
        publication_parent = PublicationChannel(parent, deadline=publication_deadline)
        request.update(publication_fd=publication_child.fileno(), publication_deadline=publication_deadline)
    process = None
    interrupted = None
    try:
        process = subprocess.Popen([sys.executable, '-B', str(runtime.WORKER), 'guardian'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=os.name == 'posix',
            creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) if os.name == 'nt' else 0,
            **({'pass_fds': (publication_child.fileno(),)} if publication_child is not None else {}))
        if publication_child is not None:
            publication_child.close()
        process.stdin.write((json.dumps(request) + '\n').encode())
        process.stdin.flush()
        while process.poll() is None:
            if publication_parent is not None:
                try:
                    publication_parent.service(manager, ledger, intent_id, attempt)
                except EvidenceError as exc:
                    if str(exc) != 'publication verification channel lost':
                        raise
                    publication_parent.close()
                    publication_parent = None
            else:
                time.sleep(.03)
    except BaseException as exc:
        interrupted = exc
    finally:
        if process is not None:
            if process.stdin:
                process.stdin.close()  # Also requests cancellation after interrupt.
            try:
                until = time.monotonic() + 15
                while process.poll() is None and time.monotonic() < until:
                    if publication_parent is not None:
                        try:
                            publication_parent.service(manager, ledger, intent_id, attempt, cancelled=True)
                        except (EvidenceError, OSError, ValueError):
                            publication_parent.close()
                            publication_parent = None
                    else:
                        time.sleep(.03)
                process.wait(timeout=max(.01, until - time.monotonic()))
            except subprocess.TimeoutExpired:
                # Never kill the surviving monitor just to shorten cancellation.
                raise EvidenceError('producer guardian cleanup still active; inspect/reconcile before retry')
        else:
            ledger.settle(reservation, 0, 0)
            ledger.mark_incomplete(run_id)
            ledger.acknowledge_output(output_id)
            runtime.update(ledger, attempt, lambda v: v.update(status='terminal'))
        if publication_parent is not None:
            publication_parent.close()
        if publication_child is not None:
            publication_child.close()
    value = runtime.read(ledger, attempt)
    if process is not None and value.get('guardian') is None:
        # The request never reached a claimed guardian. It could not pass a
        # payload gate. Close the unused hold only with the original empty root.
        if runtime.directory_identity(root) == fingerprint and not any(root.iterdir()):
            ledger.settle(reservation, 0, 0)
            ledger.mark_incomplete(run_id)
            ledger.acknowledge_output(output_id)
            runtime.update(ledger, attempt, lambda v: v.update(status='terminal'))
        else:
            ledger.record_uncertain(reservation, 0, 0)
    if interrupted is not None:
        raise interrupted
    value = runtime.read(ledger, attempt)
    if value.get('result') is None:
        recovered = recover_producers(ledger, dry_run=False)
        raise EvidenceError('producer guardian stopped without a terminal result; recovery incomplete=' + str(recovered['incomplete'])
                            + '; recovery action=' + _recovery_failure_diagnostic(recovered, attempt))
    result = value['result']
    if result.pop('observations_in_final_observation', False):
        result['observations'] = value['final_observation']['observations']
    if result.pop('observations_in_ledger', False):
        result['observations'] = {row['path']: {'content_hash': row['digest'], 'size': row['bytes']}
            for row in ledger.connection.execute('SELECT path,digest,bytes FROM observations WHERE output_id=?', (value['output_id'],))}
    if process.returncode != 0:
        raise EvidenceError('producer guardian failed after result publication; inspect its recovery record')
    return result


def _guardian():
    from .accounting import Accounting
    from . import producer_runtime as runtime, process_identity
    request = json.loads(sys.stdin.buffer.readline(runtime.MAX_RECORD + 1))
    cancelled = threading.Event()
    threading.Thread(target=runtime.watch_input, args=(cancelled,), daemon=True).start()
    # Read the policy without trusting any environment-specific global defaults.
    import sqlite3
    connection = sqlite3.connect(request['ledger'])
    try:
        policy = json.loads(connection.execute('SELECT record FROM producer_sessions WHERE id=?', (request['attempt'],)).fetchone()[0])['policy']
    finally:
        connection.close()
    with Accounting(request['ledger'], policy['project_id'], policy) as ledger:
        attempt = request['attempt']
        publication_channel = None
        if 'publication_fd' in request:
            import socket
            from .quarantine_device import PublicationChannel
            publication_channel = PublicationChannel(socket.socket(fileno=request['publication_fd']),
                                                       deadline=request['publication_deadline'])
            original = runtime.read(ledger, attempt)
            ledger._publication_channel = (publication_channel, original.get('intent_id'), attempt, 'guardian-launch')
        value = runtime.claim_guardian(ledger, attempt)
        if process_identity.state(value['coordinator']) != 'alive':
            cancelled.set()
        try:
            if ledger.connection.execute('SELECT 1 FROM producer_quarantines LIMIT 1').fetchone():
                ledger.require_generation_ready()
            if publication_channel is not None:
                ledger._publication_channel = (publication_channel, value.get('intent_id'), attempt, 'completion')
            result = _run_monitored(ledger, value['run_id'], value['unit_id'], value['output_dir'], request['command'],
                request['reserve_bytes'], request['reserve_files'], timeout=request['timeout'],
                poll_interval=request['poll_interval'], complete_run=request['complete_run'], attempt=attempt, cancelled=cancelled)
            if (not request['complete_run'] and result['status'] == 'complete'
                    and ledger.connection.execute('SELECT 1 FROM producer_quarantines LIMIT 1').fetchone()):
                # Deferring the shared run seal does not defer this worker's
                # completion authority. Preserve its measured settlement/final
                # observation if the fresh publication check cannot succeed.
                try:
                    ledger.require_generation_ready()
                except (EvidenceError, OSError, ValueError, KeyError, TypeError) as exc:
                    ledger.mark_incomplete(value['run_id'])
                    result['status'] = 'incomplete'
                    result['problem'] = 'deferred worker completion publication failed: ' + str(exc)
            result['attempt_id'] = attempt
            # The original final observation was persisted before settlement,
            # including failed cleanup. Reference it instead of duplicating its
            # potentially large map in the result or discarding failed hashes.
            result['observations'] = {}
            current = runtime.read(ledger, attempt)
            result['observations_in_final_observation'] = 'observations' in current.get('final_observation', {})
            result['observations_in_ledger'] = False
            if result['status'] == 'complete':
                try:
                    ledger._check_publication_deadline()
                except EvidenceError as exc:
                    ledger.mark_incomplete(value['run_id'])
                    result.update(status='incomplete', problem=str(exc))
            runtime.update(ledger, attempt, lambda v: v.update(status='stopping' if result['cleanup_problem'] else 'terminal', result=result))
        except BaseException as exc:
            runtime.update(ledger, attempt, lambda v: v.update(guardian_problem=str(exc) or type(exc).__name__))
            return 1
        finally:
            if publication_channel is not None:
                publication_channel.close()
    return 0
