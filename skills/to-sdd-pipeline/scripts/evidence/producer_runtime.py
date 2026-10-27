"""Private bounded producer journal and gated helpers. No persistent service.

Only explicitly registered helpers are recoverable. Arbitrary escaped writers
remain outside the managed-producer contract. Journals live in the accounting
DB, whose physical bytes already count towards metadata/local capacity.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

from .accounting import Accounting
from .io import EvidenceError, _is_link, _parents
from .policy import validate_policy
from . import process_identity

MAX_RECORD = 1024 * 1024
WORKER = Path(__file__).with_name('producer_worker.py')


def read(ledger, attempt):
    row = ledger.connection.execute('SELECT record FROM producer_sessions WHERE id=?', (attempt,)).fetchone()
    if row is None:
        raise EvidenceError('missing producer ownership record; recovery required')
    if len(row[0]) > MAX_RECORD:
        raise EvidenceError("producer ownership record exceeds metadata bound")
    value = json.loads(row[0])
    if not isinstance(value, dict) or value.get('attempt_id') != attempt or value.get('version') not in (1, 2):
        raise EvidenceError('invalid producer ownership record; recovery required')
    observed_keys = {'observation_session', 'observed_writers', 'observation_roots', 'observation_sessions', 'observation_history'}
    if value['version'] == 1 and any(key in value for key in observed_keys):
        raise EvidenceError('observed obligations require producer record version2')
    if value['version'] == 2:
        from .observed_writers import validate_registry
        validate_registry(value)
        if observed_keys.intersection(value) - {'observation_session', 'observation_history'}:
            raise EvidenceError('unknown observation registry fields')
    required = ('run_id', 'unit_id', 'reservation_id', 'coordinator', 'policy', 'output_dir',
                'output_identity', 'processes', 'resources', 'status')
    if (any(key not in value for key in required)
            or value['status'] not in ('launching', 'running', 'stopping', 'terminal')
            or not process_identity.valid_identity(value['coordinator'])
            or value.get('guardian') is not None and not process_identity.valid_identity(value['guardian'])
            or not isinstance(value['processes'], dict) or len(value['processes']) > 128
            or not isinstance(value['resources'], list) or len(value['resources']) > 128):
        raise EvidenceError('invalid producer ownership/binding; recovery required')
    stored_policy = validate_policy(value['policy'])
    if any(stored_policy[key] != ledger.policy[key] for key in ('project_id', 'store_id', 'provider')):
        raise EvidenceError('producer policy identity changed; recovery required')
    reservation = ledger.connection.execute('SELECT run_id,state FROM reservations WHERE id=?', (value['reservation_id'],)).fetchone()
    if reservation is None or reservation[0] != value['run_id']:
        raise EvidenceError('producer reservation binding changed; recovery required')
    if (stored_policy != ledger.policy and
            (value['status'] != 'terminal' or reservation[1] not in ('settled', 'cancelled'))):
        raise EvidenceError('unresolved producer policy changed; restore its original policy before recovery')
    if value.get('output_id') is not None:
        output = ledger.connection.execute('SELECT run_id,path FROM outputs WHERE id=?', (value['output_id'],)).fetchone()
        if output is None or tuple(output) != (value['run_id'], value['output_dir']):
            raise EvidenceError('producer output binding changed; recovery required')
    for item in value['processes'].values():
        if (not isinstance(item, dict) or not process_identity.valid_identity(item.get('identity'))
                or type(item.get('group')) is not int or item['group'] != item['identity']['pid']):
            raise EvidenceError('invalid helper ownership record; recovery required')
    for item in value['resources']:
        if (not isinstance(item, dict) or not isinstance(item.get('path'), str)
                or not isinstance(item.get('identity'), list) or len(item['identity']) != 2
                or any(type(n) is not int or n < 0 for n in item['identity'])
                or not Path(item['path']).is_absolute() or '..' in Path(item['path']).parts
                or Path(item['path']) == Path(value['output_dir'])
                or not Path(item['path']).is_relative_to(value['output_dir'])):
            raise EvidenceError('invalid temporary resource ownership; recovery required')
    return value


def update(ledger, attempt, change):
    with ledger._transaction():
        value = read(ledger, attempt)
        change(value)
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True)
        if len(encoded) > MAX_RECORD:
            raise EvidenceError('producer ownership record exceeds metadata bound')
        # Compare the stored bytes, not cached/normalized state. Keep validation,
        # the callback and the transaction even when no row write is needed.
        current = ledger.connection.execute('SELECT record FROM producer_sessions WHERE id=?', (attempt,)).fetchone()
        if current is None or current[0] != encoded:
            ledger.connection.execute('UPDATE producer_sessions SET record=? WHERE id=?', (encoded, attempt))
    return value


def directory_identity(root):
    _parents(Path(root) / 'placeholder')
    info = Path(root).lstat()
    if _is_link(info) or not Path(root).is_dir():
        raise EvidenceError('managed resource must be a regular directory')
    return [info.st_dev, info.st_ino]


def _environment_ledger():
    path, attempt = os.environ.get('SDD_PRODUCER_LEDGER'), os.environ.get('SDD_PRODUCER_ATTEMPT')
    if not path or not attempt:
        raise EvidenceError('managed helper requires an active producer session')
    # Policy is stored with the attempt; no provider credentials or product paths
    # are embedded in reusable scripts.
    import sqlite3
    connection = sqlite3.connect(path)
    try:
        row = connection.execute('SELECT record FROM producer_sessions WHERE id=?', (attempt,)).fetchone()
        if row is None:
            raise EvidenceError('managed helper has no producer ownership record')
        policy = json.loads(row[0])['policy']
    finally:
        connection.close()
    return Accounting(path, policy['project_id'], policy), attempt


def managed_group_identity(pid=None):
    """Inspect membership in this producer's existing POSIX launch gate.

    This is a current observation, not registration, adoption or containment.
    The target must share the caller's existing group/session. Exact native
    identities and membership are checked again immediately before return;
    ordinary process-exit/group-change races remain possible after the return.
    SQL records and database/WAL bytes are not mutated. SQLite may update read
    locks/read marks in its existing SHM; missing sidecars are never created.
    """
    if os.name != 'posix':
        raise EvidenceError('managed group inspection requires POSIX process groups')
    path, attempt = os.environ.get('SDD_PRODUCER_LEDGER'), os.environ.get('SDD_PRODUCER_ATTEMPT')
    if not path or not attempt:
        raise EvidenceError('managed group inspection requires an active producer session')
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise EvidenceError('managed group inspection requires the original absolute ledger path')
    _parents(path)
    # An active native ledger is in WAL mode with existing sidecars. Requiring
    # those files avoids a read-only open creating missing SQLite WAL/SHM files.
    for candidate in (path, Path(str(path) + '-wal'), Path(str(path) + '-shm')):
        try:
            info = candidate.lstat()
        except OSError as exc:
            raise EvidenceError('active producer ledger/sidecar is unavailable') from exc
        if _is_link(info) or not stat.S_ISREG(info.st_mode):
            raise EvidenceError('unsafe producer ledger/sidecar path')
    import sqlite3
    from types import SimpleNamespace
    connection = None
    try:
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, isolation_level=None)
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_TRANSACTION}
        connection.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
        connection.execute('BEGIN')
        row = connection.execute('SELECT record FROM producer_sessions WHERE id=?', (attempt,)).fetchone()
        if row is None or not isinstance(row[0], str) or len(row[0].encode('utf-8')) > MAX_RECORD:
            raise EvidenceError('missing or oversized producer ownership record')
        policy = validate_policy(json.loads(row[0])['policy'])
        view = SimpleNamespace(connection=connection, policy=policy)

        def active_record():
            value = read(view, attempt)
            identity = dict(connection.execute("SELECT key,value FROM identity WHERE key IN ('project_id','version')"))
            reservation = connection.execute('SELECT state FROM reservations WHERE id=?', (value['reservation_id'],)).fetchone()
            run = connection.execute('SELECT unit_id FROM runs WHERE id=?', (value['run_id'],)).fetchone()
            if (identity != {'project_id': policy['project_id'], 'version': '1'} or value['status'] != 'running'
                    or reservation is None or reservation[0] != 'pending' or value.get('output_id') is None
                    or run is None or run[0] != value['unit_id']):
                raise EvidenceError('managed group inspection requires original running producer bindings')
            if (process_identity.state(value.get('guardian')) != 'alive'
                    or process_identity.state(value['coordinator']) != 'alive'):
                raise EvidenceError('managed group inspection cannot verify live producer owners')
            if directory_identity(value['output_dir']) != value['output_identity']:
                raise EvidenceError('managed group inspection output identity changed')
            return value

        value = active_record()
        owner = process_identity.identity(os.getpid() if pid is None else pid)
        caller_group, caller_session = os.getpgrp(), os.getsid(0)
        if os.getpgid(owner['pid']) != caller_group or os.getsid(owner['pid']) != caller_session:
            raise EvidenceError('target is outside the caller managed process group/session')
        candidates = [item for item in value['processes'].values() if item['group'] == caller_group]
        if len(candidates) != 1:
            raise EvidenceError('caller has no unique recorded managed launch gate')
        anchor = candidates[0]['identity']

        def live_membership():
            if (process_identity.state(owner) != 'alive' or process_identity.state(anchor) != 'alive'
                    or anchor['pid'] != caller_group or caller_group != caller_session
                    or os.getpgrp() != caller_group or os.getsid(0) != caller_session
                    or os.getpgid(owner['pid']) != caller_group or os.getsid(owner['pid']) != caller_session
                    or os.getpgid(anchor['pid']) != caller_group or os.getsid(anchor['pid']) != caller_session):
                raise EvidenceError('managed owner/anchor identity or kernel group membership changed')

        live_membership()
        connection.execute('ROLLBACK')
        # Read the current journal again after releasing the initial snapshot,
        # so a concurrently stopped attempt cannot rely solely on stale running
        # metadata. This is still a read-only SQLite connection.
        latest = active_record()
        keys = ('run_id', 'unit_id', 'reservation_id', 'output_id', 'output_dir', 'output_identity', 'guardian', 'coordinator')
        latest_anchors = [item['identity'] for item in latest['processes'].values() if item['group'] == caller_group]
        if any(latest[key] != value[key] for key in keys) or latest_anchors != [anchor]:
            raise EvidenceError('managed group inspection binding changed during observation')
        live_membership()
        return {'version': 1, 'attempt_id': attempt, 'owner': owner, 'anchor': anchor,
                'group_id': caller_group, 'session_id': caller_session}
    except (sqlite3.Error, OSError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError('cannot inspect current managed group: ' + str(exc)) from exc
    finally:
        if connection is not None:
            connection.close()


class ManagedChild:
    def __init__(self, ledger, attempt, process, key, job=None, close_ledger=False):
        self.ledger, self.attempt, self.process, self.key = ledger, attempt, process, key
        self.job, self.close_ledger = job, close_ledger
        self.pid = process.pid

    def poll(self):
        item = read(self.ledger, self.attempt)['processes'][self.key]
        if 'exit_code' in item:
            return item['exit_code']
        code = self.process.poll()
        if code is not None:
            raise EvidenceError('managed launch gate exited before publishing its result')
        return None

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            code = self.poll()
            if code is not None:
                return code
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('managed helper', timeout)
            time.sleep(.02)

    def close(self):
        # Closing the pipe makes a POSIX gate stop its own anchored group. A
        # Windows Job closes with this handle or its owning process.
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        finally:
            if self.job:
                self.job.close()
            if self.close_ledger:
                self.ledger.close()


def launch(ledger, attempt, command, *, cwd, env, stdout=None, stderr=None, close_ledger=False):
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or '\0' in x for x in command):
        raise EvidenceError('managed helper requires argv strings')
    from .producer import _WindowsJob
    job = _WindowsJob() if os.name == 'nt' else None
    process = None
    try:
        process = subprocess.Popen([sys.executable, '-B', str(WORKER), 'gate'], cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
            start_new_session=os.name == 'posix',
            creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) if os.name == 'nt' else 0)
        if job:
            job.assign(process)  # Gate cannot execute user argv before assignment.
        owned = process_identity.identity(process.pid)
        key = str(uuid.uuid4())
        def register(value):
            if value['status'] != 'running' or len(value['processes']) >= 128:
                raise EvidenceError('producer stopped or managed helper limit reached')
            value['processes'][key] = {'identity': owned, 'group': process.pid, 'status': 'gated', 'sequence': len(value['processes'])}
        update(ledger, attempt, register)
        request = {'ledger': str(ledger.path), 'attempt': attempt, 'key': key,
                   'policy': ledger.policy, 'command': command}
        process.stdin.write((json.dumps(request) + '\n').encode())
        process.stdin.flush()
        return ManagedChild(ledger, attempt, process, key, job, close_ledger)
    except BaseException:
        if process:
            if process.stdin:
                process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if job:
            job.close()
        raise


def spawn_managed(command, *, cwd=None, stdout=None, stderr=None):
    """Launch an explicitly registered helper, including a separate POSIX session.

    Use inside a managed producer. Keep the returned handle until helper work is
    done; wait() returns payload status, while the guardian owns final cleanup.
    Ordinary descendants can instead stay in their parent's process group/job.
    """
    ledger, attempt = _environment_ledger()
    try:
        return launch(ledger, attempt, command, cwd=cwd or os.getcwd(), env=os.environ.copy(),
                      stdout=stdout, stderr=stderr, close_ledger=True)
    except BaseException:
        ledger.close()
        raise


def register_temporary_directory(path):
    """Register an empty temporary directory inside the reserved output root.

    Files remain evidence/diagnostics. Recovery only removes the verified empty
    directory after owned processes exit, never a populated profile or payload.
    """
    ledger, attempt = _environment_ledger()
    try:
        path = Path(path).absolute()
        value = read(ledger, attempt)
        root = Path(value['output_dir'])
        if path == root or not path.is_relative_to(root) or any(path.iterdir()):
            raise EvidenceError('temporary directory must be empty and inside the managed output root')
        resource = {'path': str(path), 'identity': directory_identity(path)}
        def register(value):
            if value['status'] != 'running' or len(value['resources']) >= 128:
                raise EvidenceError('producer stopped or managed resource limit reached')
            value['resources'].append(resource)
        update(ledger, attempt, register)
    finally:
        ledger.close()


def _helper_problem(stage, key, item, problem):
    """Keep a bounded exact ownership/operation diagnostic, never an absence proof."""
    return ('helper recovery stage=' + stage + ' key=' + str(key)[:128]
            + ' group=' + str(item['group'])
            + ' identity=' + json.dumps(item['identity'], sort_keys=True, ensure_ascii=True)
            + ' problem=' + str(problem)[:512])


def stop_registered(ledger, attempt):
    """Stop exact recorded gate identities; never signal a bare saved PID.

    POSIX gates remain session/group leaders until cleanup. There is a residual
    identity-check-to-killpg race on POSIX; this is cooperative ownership, not an
    OS sandbox against malicious PID/session replacement.
    """
    # Latch loss before stopping the original managed group containing the
    # observer. External rows are never added to processes or signal targets.
    from .observed_writers import lose_history
    lose_history(ledger, attempt, 'managed groups stopped before observer durable closure')
    value = update(ledger, attempt, lambda v: v.update(status='stopping'))
    problems = []
    for key, item in sorted(value['processes'].items(), key=lambda pair: pair[1].get('sequence', 0), reverse=True):
        owner = item['identity']
        status = process_identity.state(owner)
        if status == 'unknown':
            problems.append(_helper_problem('stop.identity', key, item, 'helper ownership cannot be verified'))
            continue
        if status == 'gone':
            # A lost anchor cannot authorize killing a reused process group.
            # The gate's EOF handler normally kills its own group; if a group
            # remains, retain the hold for inspection instead of guessing.
            if os.name == 'posix':
                from .producer import _group_exists
                try:
                    if _group_exists(item['group']):
                        problems.append(_helper_problem('stop.group-exists', key, item,
                                                        'helper group survived its ownership anchor'))
                except OSError as exc:
                    problems.append(_helper_problem('stop.group-exists', key, item, exc))
            continue
        if os.name == 'posix':
            stage = 'stop.getpgid'
            try:
                group = os.getpgid(owner['pid'])
                stage = 'stop.getsid'
                session = os.getsid(owner['pid'])
                if group != owner['pid'] or session != owner['pid']:
                    raise EvidenceError('recorded helper is no longer its session leader')
                stage = 'stop.identity-before-term'
                if process_identity.state(owner) != 'alive':
                    raise EvidenceError('helper identity changed before cleanup')
                stage = 'stop.sigterm'
                os.killpg(owner['pid'], signal.SIGTERM)
                time.sleep(.05)
                # The gate ignores TERM so it stays an ownership anchor until
                # this final group kill; payloads had a chance to exit/reap.
                stage = 'stop.identity-before-kill'
                status = process_identity.state(owner)
                if status == 'unknown':
                    raise EvidenceError('helper ownership cannot be verified')
                if status == 'alive':
                    stage = 'stop.sigkill'
                    os.killpg(owner['pid'], signal.SIGKILL)
            except ProcessLookupError:
                pass
            except (EvidenceError, OSError) as exc:
                problems.append(_helper_problem(stage, key, item, exc))
        elif process_identity.terminate(owner, force=True) == 'unknown':
            problems.append(_helper_problem('stop.terminate', key, item, 'helper termination could not verify ownership'))
    return problems


def cleanup_directories(ledger, attempt):
    value = read(ledger, attempt)
    from .observed_writers import disposition_problems
    problems = disposition_problems(value, ledger=ledger)
    if problems:
        return problems
    if directory_identity(value['output_dir']) != value['output_identity']:
        raise EvidenceError('managed output directory identity changed')
    for item in reversed(value['resources']):
        path = Path(item['path'])
        if not path.exists() and not path.is_symlink():
            continue
        if directory_identity(path) != item['identity']:
            problems.append('temporary resource identity changed: ' + str(path))
            continue
        try:
            path.rmdir()  # Atomic empty-only removal; payloads are preserved.
        except OSError:
            if not any(path.iterdir()):
                problems.append('temporary directory removal failed: ' + str(path))
    return problems


def watch_input(event):
    # Raw reads avoid a daemon owning BufferedReader's lock during Python exit.
    try:
        while os.read(sys.stdin.fileno(), 4096):
            event.set()
    finally:
        event.set()


def claim_guardian(ledger, attempt):
    def claim(value):
        if value['status'] != 'launching' or value.get('guardian') or value.get('recovery_owner'):
            raise EvidenceError('producer was already claimed/recovered; refusing delayed launch')
        row = ledger.connection.execute('SELECT state FROM reservations WHERE id=?', (value['reservation_id'],)).fetchone()
        if row is None or row[0] != 'pending' or value.get('output_id') is None:
            raise EvidenceError('producer has no original pending reservation/output')
        value.update(guardian=process_identity.identity(), status='running')
    return update(ledger, attempt, claim)


def gate():
    line = sys.stdin.buffer.readline(MAX_RECORD + 1)
    if not line or len(line) > MAX_RECORD:
        return 1
    request = json.loads(line)
    disconnected = threading.Event()
    threading.Thread(target=watch_input, args=(disconnected,), daemon=True).start()
    if os.name == 'posix':
        signal.signal(signal.SIGTERM, lambda *_: None)
    with Accounting(request['ledger'], request['policy']['project_id'], request['policy']) as ledger:
        record = read(ledger, request['attempt'])
        if (record['status'] != 'running' or disconnected.is_set()
                or process_identity.state(record['coordinator']) != 'alive'
                or process_identity.state(record['guardian']) != 'alive'):
            return 1
        # Restore normal TERM in payload; ignored signals otherwise survive exec.
        if os.name == 'posix':
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
        try:
            child = subprocess.Popen(request['command'], stdin=subprocess.DEVNULL)
        except OSError as exc:
            if os.name == 'posix':
                signal.signal(signal.SIGTERM, lambda *_: None)
            update(ledger, request['attempt'], lambda v: v['processes'][request['key']].update(exit_code=127, launch_problem=str(exc)))
            disconnected.wait()
            if os.name == 'posix':
                os.killpg(os.getpid(), signal.SIGKILL)
            return 127
        if os.name == 'posix':
            signal.signal(signal.SIGTERM, lambda *_: None)
        while not disconnected.is_set():
            code = child.poll()
            if code is not None:
                update(ledger, request['attempt'], lambda v: v['processes'][request['key']].update(exit_code=code))
                disconnected.wait()  # Keep group identity anchored until cleanup.
                break
            time.sleep(.02)
    if os.name == 'posix':
        os.killpg(os.getpid(), signal.SIGKILL)
    return 1


def verify_stopped(ledger, attempt, timeout=3):
    deadline = time.monotonic() + timeout
    while True:
        problems = []
        uncertain = False
        for key, item in read(ledger, attempt)['processes'].items():
            state = process_identity.state(item['identity'])
            if state != 'gone':
                problems.append(_helper_problem('verify.identity', key, item, 'helper exit cannot be verified: ' + state))
                uncertain |= state == 'unknown'
            elif os.name == 'posix':
                from .producer import _group_exists
                try:
                    if _group_exists(item['group']):
                        problems.append(_helper_problem('verify.group-exists', key, item, 'helper group exit cannot be verified'))
                except OSError as exc:
                    problems.append(_helper_problem('verify.group-exists', key, item, exc))
                    uncertain = True
        from .observed_writers import disposition_problems
        problems += disposition_problems(read(ledger, attempt), ledger=ledger, timeout=max(.001, deadline - time.monotonic()))
        # A denied/unknown probe remains a failed observation. Only a new
        # explicit recovery may supersede it with current native absence proof.
        if uncertain or not problems or time.monotonic() >= deadline:
            return problems
        time.sleep(.05)
