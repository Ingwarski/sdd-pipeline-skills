"""SDK-owned, bounded Darwin observations. This registry grants no signal rights.

Only the inherited-FD observer invokes native queries and appends witnesses.
Sampling can miss short-lived intermediaries; missing evidence stays incomplete.
These cooperative observations are neither a kernel signature nor an OS sandbox.
"""
from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import subprocess
import tempfile
import select
import math
import time
import uuid

from . import darwin_observation as native, process_identity
from .io import EvidenceError

CAPABILITY = 'darwin-sdk-observed-writers-v1'
MAX_ROOTS, MAX_NODES, MAX_OBSERVATIONS, MAX_PENDING = 8, 128, 384, 128
MAX_SESSIONS = 16
DEFAULT_RUNTIME_FILES = 10000
MAX_REQUEST = 16384
SESSION_LIMIT = 768 * 1024
AUTHORITY = {'class': 'observe_only_no_signal', 'signal': False, 'group': False, 'adoption': False}
SOURCE_FILES = ('observed_writers.py', 'observed_writer_worker.py', 'darwin_observation.py', 'producer_runtime.py')
WARNINGS = ('Sampled discovery can miss fast forks or intermediary execs; missing chains block association.',
            'Observed genealogy grants no signaling, filesystem confinement, or complete write measurement.')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def sources():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def _valid_sources(value):
    return (type(value) is dict and set(value) == set(SOURCE_FILES)
            and all(type(digest) is str and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest)
                    for digest in value.values()))


def _validate_binding_shape(binding):
    keys = {'id', 'row', 'coordinator', 'run_id', 'unit_id', 'attempt_id'}
    row_keys = {'id', 'bytes', 'migration', 'metadata_bytes', 'metadata_files', 'cache_bytes',
                'owner_pid', 'owner_host', 'state', 'created'}
    if (type(binding) is not dict or set(binding) != keys or type(binding['row']) is not dict
            or set(binding['row']) != row_keys or not process_identity.valid_identity(binding['coordinator'])
            or binding['coordinator']['platform'] != 'darwin'
            or any(type(binding[k]) is not str or not 0 < len(binding[k]) <= 256 for k in ('id', 'run_id', 'unit_id', 'attempt_id'))):
        raise EvidenceError('invalid exact observer working-reservation binding')
    row = binding['row']
    birth = binding['coordinator']['created']
    if (row['id'] != binding['id'] or row['state'] != 'pending' or row['owner_pid'] != binding['coordinator']['pid']
            or row['owner_host'] != binding['coordinator']['host'] or type(row['bytes']) is not int or row['bytes'] <= 0
            or type(row['migration']) is not int or row['migration'] not in (0, 1)
            or any(type(row[k]) is not int or row[k] < 0 for k in ('metadata_bytes', 'metadata_files', 'cache_bytes'))
            or type(row['created']) not in (int, float) or not math.isfinite(row['created'])
            or row['created'] < birth['seconds'] + birth['microseconds'] / 1e6):
        raise EvidenceError('invalid working hold owner/birth/state/amount')
    return binding


def validate_registry(record, *, active_sources=True):
    history = record.get('observation_history', [])
    if type(history) is not list or len(history) + 1 > MAX_SESSIONS:
        raise EvidenceError('observer cumulative session bound exceeded')
    sessions, identifiers = [], set()
    for archived in history:
        if (type(archived) is not dict or set(archived) != {'sha256', 'session'}
                or archived['sha256'] != hashlib.sha256(canonical(archived['session']).encode()).hexdigest()):
            raise EvidenceError('immutable closed observer history digest changed')
        session = validate_session(archived['session'])
        if session['state'] != 'closed':
            raise EvidenceError('only CLOSED observer sessions may enter immutable history')
        sessions.append(session)
    current = record.get('observation_session')
    sessions.append(validate_session(current, current_sources=active_sources and type(current) is dict and current.get('state') != 'closed'))
    for session in sessions:
        key = session.get('session_id', canonical(session['observer']))
        if key in identifiers:
            raise EvidenceError('replayed observer session identity')
        identifiers.add(key)
        binding = session.get('working_binding')
        if (session['membership']['attempt_id'] != record['attempt_id']
                or binding and (any(binding[k] != record[k] for k in ('run_id', 'unit_id', 'attempt_id'))
                                or binding['coordinator'] != record['coordinator'])):
            raise EvidenceError('observer working hold changed native producer run binding')
    return sessions


def working_binding(ledger, record, reservation_id=None, *, session=None, require_active=True):
    if session is not None:
        binding = _validate_binding_shape(session['working_binding'])
        reservation_id = binding['id']
        if any(binding[k] != record[k] for k in ('run_id', 'unit_id', 'attempt_id')) or binding['coordinator'] != record['coordinator']:
            raise EvidenceError('working reservation producer/coordinator binding changed')
    if type(reservation_id) is not str or not 0 < len(reservation_id) <= 256:
        raise EvidenceError('explicit working reservation id required')
    row = ledger.connection.execute('SELECT * FROM working_reservations WHERE id=?', (reservation_id,)).fetchone()
    if row is None:
        raise EvidenceError('working reservation unknown')
    row = dict(row)
    if session is None:
        binding = dict(id=reservation_id, row=row, coordinator=copy.deepcopy(record['coordinator']),
                       run_id=record['run_id'], unit_id=record['unit_id'], attempt_id=record['attempt_id'])
        _validate_binding_shape(binding)
    if any(row[key] != binding['row'][key] for key in row if key != 'state'):
        raise EvidenceError('working reservation original row identity changed')
    if require_active:
        coordinator = binding['coordinator']
        if (row['state'] != 'pending' or process_identity.state(coordinator) != 'alive'
                or process_identity.identity(coordinator['pid']) != coordinator):
            raise EvidenceError('working reservation requires exact live coordinator and pending hold')
    elif row['state'] not in ('pending', 'settled', 'cancelled'):
        raise EvidenceError('closed working hold has unsupported disposition')
    return copy.deepcopy(binding)


def _ensure_hold_unshared(ledger, attempt, reservation_id):
    from .producer_runtime import MAX_RECORD
    for other in ledger.connection.execute('SELECT id,record FROM producer_sessions'):
        if other[0] == attempt:
            continue
        if type(other[1]) is not str or len(other[1].encode()) > MAX_RECORD:
            raise EvidenceError('other producer registry exceeds bounded claim scan')
        prior = json.loads(other[1])
        if prior.get('version') == 2:
            for existing in validate_registry(prior, active_sources=False):
                if existing.get('working_binding', {}).get('id') == reservation_id and existing['state'] != 'closed':
                    raise EvidenceError('working reservation already bound to another active attempt')


def semantic(snapshot):
    return {key: value for key, value in snapshot.items() if key != 'observed'}


def _remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise EvidenceError('observer operation deadline expired')
    return value


def exact_chain_sequences(session, root, leaf_sequence):
    """Root-to-leaf references to ACTUAL retained matching exec versions."""
    if type(leaf_sequence) is not int or not 1 <= leaf_sequence <= len(session['observations']):
        raise EvidenceError('invalid exact lineage leaf sequence')
    chain, sequence, seen = [], leaf_sequence, set()
    for _ in range(MAX_NODES):
        node = session['observations'][sequence - 1]['snapshot']
        if node['unique_id'] in seen:
            raise EvidenceError('exact retained lineage cycle')
        seen.add(node['unique_id']); chain.append(sequence)
        if node['unique_id'] == root:
            return list(reversed(chain))
        candidates = [item for item in session['observations']
                      if item['snapshot']['unique_id'] == node['original_parent_unique_id']
                      and item['snapshot']['idversion'] == node['original_parent_idversion']]
        if not candidates:
            raise EvidenceError('exact predecessor native observation was never retained')
        parent = candidates[-1]
        if (_birth(parent['snapshot']) > _birth(node)
                or any(parent['snapshot'][k] != node[k] for k in ('uid', 'boot_uuid'))):
            raise EvidenceError('exact retained lineage birth/UID/boot mismatch')
        sequence = parent['sequence']
    raise EvidenceError('exact retained lineage depth bound exceeded')


def _birth(snapshot):
    created = snapshot['identity']['created']
    return created['seconds'], created['microseconds']


def _validate_target(value):
    keys = {'path', 'sha256', 'size', 'identity', 'mtime_ns', 'ctime_ns', 'scope'}
    if (type(value) is not dict or set(value) != keys or type(value['path']) is not str
            or not Path(value['path']).is_absolute() or '..' in Path(value['path']).parts
            or type(value['scope']) is not str or not Path(value['path']).is_relative_to(value['scope'])
            or Path(value['scope']) == Path('/') or type(value['sha256']) is not str
            or len(value['sha256']) != 64 or any(c not in '0123456789abcdef' for c in value['sha256'])
            or type(value['size']) is not int or not 0 < value['size'] <= 512 * 1024 * 1024
            or type(value['identity']) is not list or len(value['identity']) != 2
            or any(type(n) is not int or n < 0 for n in value['identity'])
            or any(type(value[k]) is not int or value[k] < 0 for k in ('mtime_ns', 'ctime_ns'))):
        raise EvidenceError('invalid declared target executable source identity')
    return value


def target_descriptor(request):
    """Hash the actual declared executable; this is not a kernel lineage witness.

    The nearest lexical .app directory (or executable parent) is solely a
    conservative candidate classifier. Matching its path NEVER grants ownership.
    """
    expected_hash = None
    if type(request) is dict and set(request) == {'path', 'sha256'}:
        path, expected_hash = request['path'], request['sha256']
    elif type(request) is str:
        path = request
    else:
        raise EvidenceError('expected target executable must be path or path/sha256 declaration')
    if type(path) is not str or not Path(path).is_absolute() or '..' in Path(path).parts:
        raise EvidenceError('target executable requires an absolute canonical path')
    path = Path(path)
    if path.resolve(strict=True) != path:
        raise EvidenceError('target executable path must resolve without aliases')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not before.st_mode & 0o111 or not 0 < before.st_size <= 512 * 1024 * 1024:
            raise EvidenceError('target must be a bounded regular executable')
        digest, count, deadline = hashlib.sha256(), 0, time.monotonic() + 5
        while True:
            if time.monotonic() >= deadline:
                raise EvidenceError('target executable hash deadline expired')
            data = os.read(descriptor, 1024 * 1024)
            if not data:
                break
            count += len(data)
            if count > before.st_size:
                raise EvidenceError('target executable grew during source hashing')
            digest.update(data)
        after = os.fstat(descriptor)
        fields = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if fields(before) != fields(after) or fields(after) != fields(path.lstat()) or count != before.st_size:
            raise EvidenceError('target executable source changed during hashing')
    finally:
        os.close(descriptor)
    sha = digest.hexdigest()
    if expected_hash is not None and expected_hash != sha:
        raise EvidenceError('declared target executable hash mismatch')
    scope = next((parent for parent in path.parents if parent.name.endswith('.app')), path.parent)
    value = dict(path=str(path), sha256=sha, size=count, identity=[before.st_dev, before.st_ino],
                 mtime_ns=before.st_mtime_ns, ctime_ns=before.st_ctime_ns, scope=str(scope))
    return _validate_target(value)


def verify_target(target):
    _validate_target(target)
    info = Path(target['path']).lstat()
    if (not stat.S_ISREG(info.st_mode) or [info.st_dev, info.st_ino] != target['identity']
            or info.st_size != target['size'] or info.st_mtime_ns != target['mtime_ns']
            or info.st_ctime_ns != target['ctime_ns']):
        raise EvidenceError('declared target executable bytes/identity changed')


def _pid(pid):
    if type(pid) is not int or not 0 < pid < 2**31:
        raise EvidenceError('observer request needs a positive numeric PID')
    return pid


def validate_session(value, *, current_sources=False):
    fields = {'version', 'capability', 'state', 'observer', 'owner', 'membership', 'source_sha256',
              'roots', 'observations', 'writers', 'pending', 'working_roots', 'errors', 'lost_history',
              'sequence', 'closure', 'warnings', 'observer_snapshot', 'owner_snapshot',
              'owner_executable', 'observer_executable', 'observer_python_version', 'ipc_paths'}
    optional_fields = {'working_binding', 'runtime_file_limit', 'session_id', 'cleanup_barrier', 'excluded_candidates'}
    if (type(value) is not dict or not fields <= set(value) <= fields | optional_fields
            or bool({'working_binding', 'runtime_file_limit', 'session_id'} & set(value)) and not {'working_binding', 'runtime_file_limit', 'session_id'} <= set(value) or type(value['version']) is not int or value['version'] != 1
            or value['capability'] != CAPABILITY or value['state'] not in ('arming', 'observing', 'closing', 'closed', 'failed')
            or not process_identity.valid_identity(value['observer']) or not process_identity.valid_identity(value['owner'])
            or type(value['lost_history']) is not bool or type(value['sequence']) is not int or value['sequence'] < 0
            or value['warnings'] != list(WARNINGS) or not _valid_sources(value['source_sha256'])
            or current_sources and value['source_sha256'] != sources()):
        raise EvidenceError('invalid observed-writer session/source binding')
    if 'working_binding' in value:
        _validate_binding_shape(value['working_binding'])
        if (type(value['session_id']) is not str or len(value['session_id']) != 36
                or type(value['runtime_file_limit']) is not int or not 1 <= value['runtime_file_limit'] <= 50000):
            raise EvidenceError('invalid bounded observer session/runtime file limit')
    if (not native.valid_snapshot(value['observer_snapshot']) or not native.valid_snapshot(value['owner_snapshot'])
            or value['observer_snapshot']['identity'] != value['observer']
            or value['owner_snapshot']['identity'] != value['owner']
            or value['observer_snapshot']['original_parent_unique_id'] != value['owner_snapshot']['unique_id']
            or value['observer_snapshot']['original_parent_idversion'] != value['owner_snapshot']['idversion']
            or value['observer_snapshot']['current_ppid'] != value['owner']['pid']
            or type(value['owner_executable']) is not str or not value['owner_executable'].startswith('/')
            or Path(value['owner_executable']).name.lower() not in ('node', 'nodejs')
            or type(value['observer_executable']) is not str or not value['observer_executable'].startswith('/')
            or type(value['observer_python_version']) is not str or len(value['observer_python_version']) > 256):
        raise EvidenceError('invalid authenticated observer native source identities')
    for key, limit in (('roots', MAX_ROOTS), ('writers', MAX_NODES), ('pending', MAX_PENDING), ('working_roots', 16), ('ipc_paths', 128)):
        if type(value[key]) is not dict or len(value[key]) > limit:
            raise EvidenceError('invalid observed-writer bounded map: ' + key)
    if (type(value['observations']) is not list or len(value['observations']) > MAX_OBSERVATIONS
            or type(value['errors']) is not list or len(value['errors']) > 16
            or any(type(item) is not str or len(item) > 512 for item in value['errors'])
            or len(canonical(value).encode()) > SESSION_LIMIT):
        raise EvidenceError('observed-writer metadata bound exceeded')
    membership = value['membership']
    if (type(membership) is not dict or set(membership) != {'version', 'attempt_id', 'owner', 'anchor', 'group_id', 'session_id'}
            or membership['owner'] != value['owner'] or membership['version'] != 1
            or not process_identity.valid_identity(membership['anchor'])
            or membership['group_id'] != membership['anchor']['pid'] or membership['session_id'] != membership['group_id']):
        raise EvidenceError('invalid observed-writer managed membership binding')
    for sequence, item in enumerate(value['observations'], 1):
        if (type(item) is not dict or set(item) != {'sequence', 'snapshot', 'executable'} or item['sequence'] != sequence
                or not native.valid_snapshot(item['snapshot']) or type(item['executable']) is not str
                or not item['executable'].startswith('/') or len(item['executable']) > 4096):
            raise EvidenceError('invalid immutable native observation')
    if value['sequence'] != len(value['observations']):
        raise EvidenceError('native observer sequence changed')
    for key, item in value['roots'].items():
        if (type(item) is not dict or set(item) not in ({'pid', 'identity', 'unique_id', 'observation_sequence', 'writable_root_refs'},
                                      {'pid', 'identity', 'unique_id', 'observation_sequence', 'writable_root_refs', 'target_executable'})
                or key != item['unique_id'] or not process_identity.valid_identity(item['identity'])
                or item['pid'] != item['identity']['pid'] or type(item['observation_sequence']) is not int
                or not 1 <= item['observation_sequence'] <= value['sequence']
                or type(item['writable_root_refs']) is not list or not item['writable_root_refs']
                or any(ref not in value['working_roots'] for ref in item['writable_root_refs'])):
            raise EvidenceError('invalid observation root binding')
        if 'target_executable' in item:
            _validate_target(item['target_executable'])
        witness = value['observations'][item['observation_sequence'] - 1]['snapshot']
        if (witness['identity'] != item['identity'] or witness['unique_id'] != key
                or witness['original_parent_unique_id'] != value['owner_snapshot']['unique_id']
                or witness['original_parent_idversion'] != value['owner_snapshot']['idversion']
                or witness['current_ppid'] != value['owner']['pid']
                or any(witness[k] != value['owner_snapshot'][k] for k in ('uid', 'boot_uuid', 'pgid'))):
            raise EvidenceError('observation root witness/owner changed')
    for key, item in value['writers'].items():
        if (type(item) is not dict or set(item) not in ({'authority', 'root', 'identity', 'unique_id', 'observation_sequence'},
                                      {'authority', 'root', 'identity', 'unique_id', 'observation_sequence', 'lineage_observation_sequences'})
                or item['authority'] != AUTHORITY or key != item['unique_id'] or item['root'] not in value['roots']
                or not process_identity.valid_identity(item['identity'])
                or type(item['observation_sequence']) is not int or not 1 <= item['observation_sequence'] <= value['sequence']):
            raise EvidenceError('invalid no-signal external writer row')
        witness = value['observations'][item['observation_sequence'] - 1]['snapshot']
        if witness['identity'] != item['identity'] or witness['unique_id'] != key:
            raise EvidenceError('external writer witness changed')
        exact = exact_chain_sequences(value, item['root'], item['observation_sequence'])
        if 'lineage_observation_sequences' in item and item['lineage_observation_sequences'] != exact:
            raise EvidenceError('writer exact predecessor observation references changed')
    for key, item in value['pending'].items():
        if (type(key) is not str or type(item) is not dict or set(item) != {'pid', 'reason'}
                or type(item['pid']) is not int or not 0 < item['pid'] < 2**31
                or type(item['reason']) is not str or len(item['reason']) > 256):
            raise EvidenceError('invalid pending observation obligation')
    for key, item in value['working_roots'].items():
        if (type(item) is not dict or set(item) != {'ref', 'path', 'identity', 'parent', 'parent_identity', 'uid', 'mode', 'purpose', 'budget_bytes'}
                or item['ref'] != key or not isinstance(item['identity'], list) or len(item['identity']) != 2
                or not isinstance(item['parent_identity'], list) or len(item['parent_identity']) != 2
                or any(type(n) is not int or n < 0 for n in item['identity'] + item['parent_identity'])
                or type(item['uid']) is not int or item['mode'] != 0o700
                or type(item['budget_bytes']) is not int or item['budget_bytes'] < 1
                or type(item['purpose']) is not str or not 0 < len(item['purpose']) <= 128
                or type(item['path']) is not str or type(item['parent']) is not str
                or Path(item['path']).parent != Path(item['parent']) or not Path(item['path']).name.startswith('sdd-observed-')):
            raise EvidenceError('invalid SDK-created working-root reference')
    for path, item in value['ipc_paths'].items():
        if (type(item) is not dict or set(item) != {'identity', 'kind', 'target', 'root_ref'}
                or item['root_ref'] not in value['working_roots'] or item['kind'] not in ('socket', 'symlink')
                or type(item['identity']) is not list or len(item['identity']) != 2
                or any(type(n) is not int or n < 0 for n in item['identity'])
                or type(path) is not str or not Path(path).is_relative_to(value['working_roots'][item['root_ref']]['path'])
                or item['kind'] == 'socket' and item['target'] is not None
                or item['kind'] == 'symlink' and (type(item['target']) is not str or len(item['target']) > 4096)):
            raise EvidenceError('invalid separate observed IPC path')
    exclusions = value.get('excluded_candidates', {})
    if type(exclusions) is not dict or len(exclusions) > 128:
        raise EvidenceError('excluded candidate receipt bound exceeded')
    for key, excluded in exclusions.items():
        if (type(excluded) is not dict or set(excluded) != {'chain', 'executable', 'ancestor_executable', 'roots'}
                or type(excluded['chain']) is not list or not 1 <= len(excluded['chain']) <= 32
                or any(not native.valid_snapshot(node) for node in excluded['chain'])
                or excluded['chain'][0]['unique_id'] != key or type(excluded['executable']) is not str
                or not excluded['executable'].startswith('/') or type(excluded['ancestor_executable']) is not str
                or not excluded['ancestor_executable'].startswith('/') or type(excluded['roots']) is not list
                or not excluded['roots'] or any(root not in value['roots'] or 'target_executable' not in value['roots'][root] for root in excluded['roots'])):
            raise EvidenceError('invalid non-task ancestry exclusion')
        if any(not Path(excluded['executable']).is_relative_to(value['roots'][root]['target_executable']['scope'])
               or not Path(excluded['ancestor_executable']).is_relative_to(value['roots'][root]['target_executable']['scope'])
               for root in excluded['roots']):
            raise EvidenceError('excluded app receipt does not match declared target scope')
        chain = excluded['chain']
        for child, parent in zip(chain, chain[1:]):
            if (child['original_parent_unique_id'] != parent['unique_id']
                    or child['original_parent_idversion'] != parent['idversion']
                    or _birth(parent) > _birth(child)
                    or any(child[k] != parent[k] for k in ('uid', 'boot_uuid'))
                    or any(child['identity'][k] != parent['identity'][k] for k in ('host', 'platform'))):
                raise EvidenceError('excluded candidate lacks full original-parent version chain')
        oldest = min(_birth(value['observations'][value['roots'][root]['observation_sequence'] - 1]['snapshot'])
                     for root in excluded['roots'])
        protected = [value['owner'], value['observer'], value['membership']['anchor']]
        if 'working_binding' in value:
            protected.append(value['working_binding']['coordinator'])
        protected += [root['identity'] for root in value['roots'].values()]
        protected += [writer['identity'] for writer in value['writers'].values()]
        if _birth(chain[-1]) >= oldest or any(node['identity'] in protected for node in chain):
            raise EvidenceError('excluded candidate reaches a protected or non-older ancestor')
    barrier = value.get('cleanup_barrier')
    if barrier is not None:
        if (type(barrier) is not dict or set(barrier) != {'valid', 'sequence', 'root_refs', 'numeric_absent', 'roots_no_handles', 'closed'}
                or type(barrier['valid']) is not bool or type(barrier['sequence']) is not int
                or not 0 <= barrier['sequence'] <= value['sequence']
                or barrier['root_refs'] != sorted(value['working_roots'])
                or barrier['numeric_absent'] is not True or barrier['roots_no_handles'] is not True
                or barrier['closed'] is not False or value['state'] not in ('closing', 'closed', 'failed')
                or barrier['valid'] and (barrier['sequence'] != value['sequence'] or value['pending'] or value['errors'] or value['lost_history'])
                or value['state'] == 'closed' and not barrier['valid']):
            raise EvidenceError('invalid pre-cleanup barrier; it is never a completion receipt')
    if value['state'] == 'closed' and (value['lost_history'] or value['errors'] or value['pending']
                                      or not value['roots'] or value['closure'] is None):
        raise EvidenceError('closed observer retains unresolved obligations')
    if value['closure'] is not None and (type(value['closure']) is not dict
            or set(value['closure']) != {'sequence', 'numeric_absent', 'roots_no_handles'}
            or value['closure']['sequence'] != value['sequence'] or value['closure']['numeric_absent'] is not True
            or value['closure']['roots_no_handles'] is not True):
        raise EvidenceError('invalid observer closure barrier')
    # Rebuild only from immutable SDK witnesses. A writer row cannot bypass a
    # missing original-parent version merely by naming an existing root.
    for root, item in value['roots'].items():
        graph = native.LineageGraph(MAX_NODES, max_updates=4096)
        first = value['observations'][item['observation_sequence'] - 1]['snapshot']
        graph.add_root(first, expected_identity=item['identity'], expected_unique_id=root)
        for observation in value['observations'][item['observation_sequence']:]:
            graph.ingest(observation['snapshot'])
        for writer in value['writers'].values():
            if writer['root'] == root and graph.lineage(writer['unique_id']) is None:
                raise EvidenceError('writer has no complete immutable original-parent version chain')
    return value


def executable_path(pid):
    _pid(pid)
    library = native._library()
    function = library.proc_pidpath
    function.argtypes, function.restype = (ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32), ctypes.c_int
    buffer = ctypes.create_string_buffer(4096)
    ctypes.set_errno(0)
    count = function(pid, buffer, len(buffer))
    if count <= 0 or count >= len(buffer) or ctypes.get_errno():
        raise EvidenceError('native executable observation unavailable')
    result = os.fsdecode(buffer.value)
    if not result.startswith('/') or '\0' in result:
        raise EvidenceError('invalid native executable path')
    return result


def child_pids(pid):
    """Public libproc.h proc_listchildpids, bounded to known native parents."""
    _pid(pid)
    function = native._library().proc_listchildpids
    function.argtypes, function.restype = (ctypes.c_int, ctypes.c_void_p, ctypes.c_int), ctypes.c_int
    buffer = (ctypes.c_int * (MAX_NODES + 1))()
    ctypes.set_errno(0)
    count = function(pid, buffer, ctypes.sizeof(buffer))
    # Unlike proc_listpids (bytes), Apple's proc_listchildpids wrapper divides
    # the native byte return by sizeof(int), returning a PID COUNT.
    if count < 0 or ctypes.get_errno() or count >= len(buffer):
        raise EvidenceError('native child enumeration failed or exceeded bound')
    return tuple(sorted(set(child for child in buffer[:count] if child > 0)))


def candidate_pids():
    """Bounded native UID-filtered enumeration; no PS adoption or group claims."""
    function = native._library().proc_listpids
    function.argtypes, function.restype = (ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int), ctypes.c_int
    capacity = 4096
    buffer = (ctypes.c_int * (capacity + 1))()
    ctypes.set_errno(0)
    count = function(4, os.geteuid(), buffer, ctypes.sizeof(buffer))  # PROC_UID_ONLY
    if count < 0 or ctypes.get_errno() or count % ctypes.sizeof(ctypes.c_int) or count >= ctypes.sizeof(buffer):
        raise EvidenceError('native candidate enumeration failed or exceeded bound')
    return tuple(sorted(set(pid for pid in buffer[:count // ctypes.sizeof(ctypes.c_int)] if pid > 0)))


def _resource_current(item):
    from .producer_runtime import directory_identity
    path, parent = Path(item['path']), Path(item['parent'])
    if parent != Path(tempfile.gettempdir()).resolve() or path.parent != parent:
        raise EvidenceError('working root is outside actual OS temporary directory')
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700 or info.st_dev != parent.stat().st_dev
            or directory_identity(path) != item['identity'] or directory_identity(parent) != item['parent_identity']):
        raise EvidenceError('SDK working-root identity/owner/mode/mount changed')


def _bounded_usage(path, *, deadline, max_entries=4096, ipc=None):
    """Read names and metadata only, with directory FDs and no link traversal."""
    root = Path(path)
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    total, count = 0, 0
    base = root.lstat()
    def visit(fd, depth, directory):
        nonlocal total, count
        if depth > 32:
            raise EvidenceError('working-root directory depth bound exceeded')
        with os.scandir(fd) as entries:
            for entry in entries:
                if time.monotonic() >= deadline:
                    raise EvidenceError('working-root capacity sampling deadline expired')
                count += 1
                if count > max_entries:
                    raise EvidenceError('working-root entry bound exceeded')
                info = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
                if info.st_uid != os.geteuid() or info.st_dev != base.st_dev:
                    raise EvidenceError('working-root foreign owner or mount crossing')
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, flags, dir_fd=fd)
                    try:
                        opened = os.fstat(child)
                        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                            raise EvidenceError('working-root directory changed during observation')
                        visit(child, depth + 1, directory / entry.name)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or stat.S_ISSOCK(info.st_mode):
                    # Count link bytes without following their targets. This is a
                    # capacity sample, never evidence of write isolation.
                    total += info.st_size
                    if ipc is not None and (stat.S_ISLNK(info.st_mode) or stat.S_ISSOCK(info.st_mode)):
                        ipc[str(directory / entry.name)] = dict(identity=[info.st_dev, info.st_ino],
                            kind='symlink' if stat.S_ISLNK(info.st_mode) else 'socket',
                            target=os.readlink(entry.name, dir_fd=fd) if stat.S_ISLNK(info.st_mode) else None)
                else:
                    raise EvidenceError('unsupported working-root file type')
    descriptor = os.open(root, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (base.st_dev, base.st_ino):
            raise EvidenceError('working-root identity changed before capacity sample')
        visit(descriptor, 0, root)
    finally:
        os.close(descriptor)
    return total, count


def _no_handles(item, timeout, *, allow_absent=False, require_empty=True):
    path = Path(item['path'])
    if allow_absent and not path.exists() and not path.is_symlink():
        # Exact SDK-created path was removed after the browser exit. A missing
        # numeric path cannot be an open directory namespace; parent substitution
        # and linked paths remain blockers. The original inode is never reused.
        from .producer_runtime import directory_identity
        if directory_identity(Path(item['parent'])) != item['parent_identity']:
            raise EvidenceError('working-root parent changed after removal')
        return
    _resource_current(item)
    try:
        result = _bounded_lsof(item['path'], timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceError('working-root handle query failed') from exc
    if result[0] != 1 or result[1].strip() or result[2].strip():
        raise EvidenceError('working-root handles absent cannot be verified')
    _resource_current(item)
    if require_empty and any(path.iterdir()):
        raise EvidenceError('working-root payload must be cleaned before closure/settlement')


def _bounded_lsof(path, timeout):
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(['/usr/sbin/lsof', '-nP', '-t', '+D', path], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    chunks = {process.stdout.fileno(): bytearray(), process.stderr.fileno(): bytearray()}
    opened = set(chunks)
    try:
        for fd in opened:
            os.set_blocking(fd, False)
        while opened:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EvidenceError('working-root handle query deadline expired')
            ready, _, _ = select.select(list(opened), [], [], min(.05, remaining))
            for fd in ready:
                data = os.read(fd, MAX_REQUEST + 1)
                if not data:
                    opened.remove(fd)
                else:
                    chunks[fd].extend(data)
                    if sum(map(len, chunks.values())) > MAX_REQUEST:
                        raise EvidenceError('working-root handle query exceeds byte bound')
        process.wait(timeout=max(.001, deadline - time.monotonic()))
        return process.returncode, bytes(chunks[process.stdout.fileno()]), bytes(chunks[process.stderr.fileno()])
    finally:
        if process.poll() is None:
            process.kill()  # Only this directly created query child, never a writer.
            process.wait(timeout=1)
        process.stdout.close(); process.stderr.close()


def _session_disposition(session, record, *, ledger, timeout=3, allow_removed=True, require_active_hold=False):
    """Read-only fresh terminal barrier, also used by recovery and quarantine."""
    validate_session(session)
    problems = []
    if 'working_binding' in session:
        try:
            if ledger is None:
                raise EvidenceError('observer working disposition needs original accounting view')
            working_binding(ledger, record, session=session, require_active=require_active_hold or session['state'] != 'closed')
        except (EvidenceError, OSError) as exc:
            problems.append('working hold disposition: ' + str(exc))
    if session['state'] != 'closed' or session['lost_history'] or session['errors'] or session['pending']:
        problems.append('observed-writer history/closure is incomplete: ' + session['state'])
    deadline = time.monotonic() + timeout
    targets = {item['pid']: item['identity'] for item in session['roots'].values()}
    targets.update({item['identity']['pid']: item['identity'] for item in session['writers'].values()})
    # Never send these PIDs to terminate/killpg. Numeric ESRCH is stricter than
    # saved birth gone: a reused PID or unreaped zombie remains a blocker.
    for pid, identity in targets.items():
        try:
            if time.monotonic() >= deadline:
                raise EvidenceError('external disposition deadline expired')
            current = native.read_snapshot(pid, include_zombie=True)
            if current is not None:
                problems.append('observed writer numeric PID still present: ' + str(pid))
        except (EvidenceError, OSError) as exc:
            problems.append('external observation unavailable: ' + str(exc)[:256])
    for item in session['working_roots'].values():
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EvidenceError('working-root disposition deadline expired')
            _no_handles(item, remaining, allow_absent=allow_removed and session['state'] == 'closed' and session['closure'] is not None)
        except (EvidenceError, OSError) as exc:
            problems.append('working-root disposition: ' + str(exc)[:256])
    return problems


def disposition_problems(record, *, ledger=None, timeout=3, allow_removed=True, require_active_hold=False):
    """All immutable prior sessions and the current session remain obligations."""
    if record.get('version') == 1:
        return []
    sessions = validate_registry(record, active_sources=False)
    deadline, problems = time.monotonic() + timeout, []
    for index, session in enumerate(sessions):
        problems += _session_disposition(session, record, ledger=ledger,
            timeout=max(.001, deadline - time.monotonic()),
            allow_removed=allow_removed or index < len(sessions) - 1,
            require_active_hold=require_active_hold and index == len(sessions) - 1)
    return problems


def lose_history(ledger, attempt, reason):
    from .producer_runtime import update
    def change(record):
        if record['version'] == 1:
            return
        session = record['observation_session']
        if session['state'] == 'closed':
            return
        session['state'], session['lost_history'] = 'failed', True
        if session.get('cleanup_barrier') is not None:
            session['cleanup_barrier']['valid'] = False
        message = str(reason)[:512]
        if message not in session['errors'] and len(session['errors']) < 16:
            session['errors'].append(message)
    return update(ledger, attempt, change)


class Observer:
    """Internal worker only. No public interface accepts native witness JSON."""
    def __init__(self, ledger, attempt, owner_pid, working_reservation_id, *, runtime_file_limit=DEFAULT_RUNTIME_FILES):
        from .producer_runtime import managed_group_identity, read, update
        self.ledger, self.attempt, self.owner_pid = ledger, attempt, _pid(owner_pid)
        if os.getppid() != owner_pid:
            raise EvidenceError('observer is not a direct child of owner Node')
        membership = managed_group_identity(owner_pid)
        mine, owner = native.read_snapshot(os.getpid()), native.read_snapshot(owner_pid)
        if (mine is None or owner is None or mine['identity'] != process_identity.identity()
                or owner['identity'] != membership['owner'] or mine['current_ppid'] != owner_pid
                or mine['original_parent_unique_id'] != owner['unique_id']
                or mine['original_parent_idversion'] != owner['idversion']
                or mine['pgid'] != membership['group_id'] or owner['pgid'] != membership['group_id']
                or any(mine[k] != owner[k] for k in ('uid', 'boot_uuid'))
                or os.getsid(0) != membership['session_id'] or os.getsid(owner_pid) != membership['session_id']):
            raise EvidenceError('observer native parent/birth/group/session mismatch')
        owner_executable, observer_executable = executable_path(owner_pid), executable_path(os.getpid())
        if Path(owner_executable).name.lower() not in ('node', 'nodejs'):
            raise EvidenceError('observer owner executable is not Node')
        self.owner_snapshot, self.graphs, self.latest = owner, {}, {}
        self.last_census = 0.0
        record = read(ledger, attempt)
        if (type(runtime_file_limit) is not int or not 1 <= runtime_file_limit <= min(50000, ledger.policy['limits']['unit_stop_files'])):
            raise EvidenceError('runtime file limit exceeds bounded policy unit allowance')
        binding = working_binding(ledger, record, working_reservation_id)
        _ensure_hold_unshared(ledger, attempt, working_reservation_id)
        if record['version'] == 2:
            prior_sessions = validate_registry(record)
            if any(session['state'] != 'closed' for session in prior_sessions):
                raise EvidenceError('observation sessions cannot be replayed/adopted before prior closure')
            problems = disposition_problems(record, ledger=ledger)
            if problems or native.read_snapshot(prior_sessions[-1]['observer']['pid']) is not None:
                raise EvidenceError('previous observer closure/disposition not currently verified')
            if len(prior_sessions) >= MAX_SESSIONS:
                raise EvidenceError('observer cumulative session bound exceeded')
        initial = dict(version=1, capability=CAPABILITY, state='arming', observer=mine['identity'],
                       owner=owner['identity'], membership=membership, source_sha256=sources(), roots={}, observations=[],
                       writers={}, pending={}, working_roots={}, errors=[], lost_history=False, sequence=0,
                       closure=None, warnings=list(WARNINGS), observer_snapshot=mine, owner_snapshot=owner,
                       owner_executable=owner_executable, observer_executable=observer_executable,
                       observer_python_version=sys.version[:256], ipc_paths={}, working_binding=binding,
                       runtime_file_limit=runtime_file_limit, session_id=str(uuid.uuid4()),
                       cleanup_barrier=None, excluded_candidates={})
        validate_session(initial, current_sources=True)
        def arm(current):
            stable = ('version', 'run_id', 'unit_id', 'reservation_id', 'coordinator', 'guardian',
                      'output_id', 'output_dir', 'output_identity', 'policy', 'observation_session', 'observation_history')
            if current['status'] != 'running' or any(current.get(key) != record.get(key) for key in stable):
                raise EvidenceError('observation sessions cannot be replayed/adopted')
            # Recheck the exact pending row and competing claims inside the same
            # serialized SQLite transaction that installs this observation session.
            if working_binding(ledger, current, working_reservation_id) != binding:
                raise EvidenceError('working reservation changed before observer arming')
            _ensure_hold_unshared(ledger, attempt, working_reservation_id)
            if current['version'] == 2:
                prior = current['observation_session']
                current.setdefault('observation_history', []).append(dict(
                    sha256=hashlib.sha256(canonical(prior).encode()).hexdigest(), session=copy.deepcopy(prior)))
            current['version'], current['observation_session'] = 2, initial
            validate_registry(current)
        update(ledger, attempt, arm)
        self.value = read(ledger, attempt)['observation_session']

    def _commit(self, change):
        from .producer_runtime import update
        def apply(record):
            current = record.get('observation_session')
            if current != self.value or current['observer'] != process_identity.identity():
                raise EvidenceError('observer history changed or ownership lost')
            prior = copy.deepcopy(current) if (current.get('cleanup_barrier') or {}).get('valid') else None
            change(current)
            if prior is not None and (any(current[key] != prior[key] for key in
                    ('roots', 'writers', 'pending', 'observations', 'working_roots', 'excluded_candidates'))
                    or current['errors'] or current['lost_history']):
                current['cleanup_barrier']['valid'] = False
                current['state'] = 'failed'
                message = 'new native candidate or failure invalidated pre-cleanup barrier'
                if message not in current['errors'] and len(current['errors']) < 16:
                    current['errors'].append(message)
            validate_session(current, current_sources=True)
        value = update(self.ledger, self.attempt, apply)
        self.value = value['observation_session']

    def fail(self, reason, *, lost=False):
        message = str(reason)[:512]
        def change(session):
            session['state'], session['lost_history'] = 'failed', session['lost_history'] or lost
            if message not in session['errors'] and len(session['errors']) < 16:
                session['errors'].append(message)
        self._commit(change)

    def _active(self, *, allow_closing=False):
        from .producer_runtime import managed_group_identity
        if (self.value['state'] not in (('arming', 'observing', 'closing') if allow_closing else ('arming', 'observing')) or os.getppid() != self.owner_pid
                or managed_group_identity(self.owner_pid) != self.value['membership']):
            raise EvidenceError('observer active managed ownership changed')
        if self.value['source_sha256'] != sources():
            raise EvidenceError('active observer source bytes changed')
        from .producer_runtime import read
        working_binding(self.ledger, read(self.ledger, self.attempt), session=self.value)
        owner = native.read_snapshot(self.owner_pid)
        if owner is None or semantic(owner) != semantic(self.owner_snapshot):
            raise EvidenceError('owner Node native identity/executable changed')

    def allocate(self, purpose, budget_bytes):
        self._active()
        if (type(purpose) is not str or not 0 < len(purpose) <= 128 or type(budget_bytes) is not int
                or not 1 <= budget_bytes <= self.ledger.policy['limits']['local_stop_bytes']
                or len(self.value['working_roots']) >= 16):
            raise EvidenceError('invalid observed working-root allocation/budget')
        from .producer_runtime import directory_identity, read
        record = read(self.ledger, self.attempt)
        binding = working_binding(self.ledger, record, session=self.value)
        if budget_bytes + sum(item['budget_bytes'] for item in self.value['working_roots'].values()) > binding['row']['bytes']:
            raise EvidenceError('working-root allocations exceed original held local allowance')
        parent = Path(tempfile.gettempdir()).resolve()
        path = Path(tempfile.mkdtemp(prefix='sdd-observed-', dir=parent))
        path.chmod(0o700)
        ref = str(uuid.uuid4())
        item = dict(ref=ref, path=str(path), identity=directory_identity(path), parent=str(parent),
                    parent_identity=directory_identity(parent), uid=os.geteuid(), mode=0o700,
                    purpose=purpose, budget_bytes=budget_bytes)
        try:
            _resource_current(item)
            self._commit(lambda s: s['working_roots'].update({ref: item}))
        except BaseException:
            path.rmdir()  # Empty, just created here. Never removes caller data.
            raise
        return copy.deepcopy(item)

    def _append(self, session, snapshot, executable):
        if len(session['observations']) >= MAX_OBSERVATIONS:
            raise EvidenceError('immutable native observation bound exceeded')
        session['sequence'] += 1
        session['observations'].append(dict(sequence=session['sequence'], snapshot=snapshot, executable=executable))
        return session['sequence']

    def register_root(self, pid, expected_identity, expected_executable, refs, expected_target_executable=None):
        self._active()
        _pid(pid)
        if (not process_identity.valid_identity(expected_identity) or expected_identity['pid'] != pid
                or type(expected_executable) is not str or not expected_executable.startswith('/')
                or type(refs) is not list or not refs or len(refs) > 16 or len(set(refs)) != len(refs)
                or any(ref not in self.value['working_roots'] for ref in refs)
                or any(set(refs).intersection(root['writable_root_refs']) for root in self.value['roots'].values())
                or len(self.value['roots']) >= MAX_ROOTS):
            raise EvidenceError('invalid root identity/executable/working-root request')
        pending = 'root:' + str(pid)
        self._commit(lambda s: s['pending'].update({pending: dict(pid=pid, reason='root registration not durably acknowledged')}))
        snapshot = native.read_snapshot(pid)
        owner = native.read_snapshot(self.owner_pid)
        if (snapshot is None or owner is None or semantic(owner) != semantic(self.owner_snapshot)
                or snapshot['identity'] != expected_identity or snapshot['status'] != 'alive'
                or snapshot['current_ppid'] != self.owner_pid or snapshot['original_parent_unique_id'] != owner['unique_id']
                or snapshot['original_parent_idversion'] != owner['idversion']
                or any(snapshot[k] != owner[k] for k in ('uid', 'boot_uuid', 'pgid'))
                or os.getsid(pid) != self.value['membership']['session_id'] or executable_path(pid) != expected_executable):
            raise EvidenceError('root native direct-parent/birth/executable/group proof failed')
        confirmed = native.read_snapshot(pid)
        if confirmed is None or semantic(confirmed) != semantic(snapshot):
            raise EvidenceError('root changed during native executable proof')
        for ref in refs:
            _resource_current(self.value['working_roots'][ref])
        target = target_descriptor(expected_target_executable) if expected_target_executable is not None else None
        graph = native.LineageGraph(MAX_NODES, max_updates=4096)
        graph.add_root(snapshot, expected_identity=expected_identity, expected_unique_id=snapshot['unique_id'])
        key = snapshot['unique_id']
        if key in self.graphs:
            raise EvidenceError('root registration cannot be replayed')
        def commit(session):
            sequence = self._append(session, snapshot, expected_executable)
            session['roots'][key] = dict(pid=pid, identity=expected_identity, unique_id=key,
                                        observation_sequence=sequence, writable_root_refs=refs)
            if target is not None:
                session['roots'][key]['target_executable'] = target
            session['pending'].pop(pending)
            session['state'] = 'observing'
        self._commit(commit)  # ACK is permitted only after this transaction commits.
        self.graphs[key], self.latest[key] = graph, semantic(snapshot)
        return dict(root=key, sequence=self.value['sequence'], durable=True)

    def _potential_candidate(self, snapshot):
        targets = [(key, root, root['target_executable']) for key, root in self.value['roots'].items()
                   if 'target_executable' in root]
        if not targets:
            return False
        oldest_any = min(_birth(self.value['observations'][root['observation_sequence'] - 1]['snapshot'])
                         for _, root, _ in targets)
        if _birth(snapshot) < oldest_any:
            return False  # A process born before every task root cannot descend from one.
        exe = executable_path(snapshot['identity']['pid'])
        matching = [key for key, root, target in targets if Path(exe).is_relative_to(target['scope'])]
        if not matching:
            return False
        confirmed = native.read_snapshot(snapshot['identity']['pid'])
        if confirmed is None or semantic(confirmed) != semantic(snapshot) or executable_path(snapshot['identity']['pid']) != exe:
            raise EvidenceError('potential target-app candidate changed during fresh executable observation')
        oldest = min(_birth(self.value['observations'][self.value['roots'][key]['observation_sequence'] - 1]['snapshot'])
                     for key in matching)
        if _birth(snapshot) < oldest:
            return False
        if snapshot['unique_id'] in self.value.get('excluded_candidates', {}):
            return False
        # Exact fresh original-parent edges to an older unrelated app process
        # exclude concurrent normal-app helpers. A missing/reparented/exec-changed
        # intermediary cannot be guessed from its PID or current parent metadata.
        protected = [self.value['owner'], self.value['observer'], self.value['membership']['anchor']]
        if 'working_binding' in self.value:
            protected.append(self.value['working_binding']['coordinator'])
        protected += [root['identity'] for root in self.value['roots'].values()]
        protected += [writer['identity'] for writer in self.value['writers'].values()]
        chain, current, seen = [snapshot], snapshot, {snapshot['unique_id']}
        for _ in range(31):
            try:
                parent = native.read_snapshot(current['current_ppid'])
                if (parent is None or parent['unique_id'] != current['original_parent_unique_id']
                        or parent['idversion'] != current['original_parent_idversion']
                        or parent['unique_id'] in seen or parent['identity'] in protected
                        or any(parent[k] != snapshot[k] for k in ('uid', 'boot_uuid'))
                        or _birth(parent) > _birth(current)):
                    break
                seen.add(parent['unique_id']); chain.append(parent)
                if _birth(parent) < oldest:
                    parent_exe = executable_path(parent['identity']['pid'])
                    if not any(Path(parent_exe).is_relative_to(self.value['roots'][key]['target_executable']['scope']) for key in matching):
                        break
                    confirmed_parent = native.read_snapshot(parent['identity']['pid'])
                    if confirmed_parent is None or semantic(confirmed_parent) != semantic(parent):
                        break
                    excluded = dict(chain=chain, executable=exe, ancestor_executable=parent_exe, roots=matching)
                    self._commit(lambda s: s.setdefault('excluded_candidates', {}).update({snapshot['unique_id']: excluded}))
                    return False
                current = parent
            except (EvidenceError, OSError):
                break
        return True

    def observe(self, pid, *, required=True):
        _pid(pid)
        snapshot = native.read_snapshot(pid)
        key = 'pid:' + str(pid)
        if required and key not in self.value['pending'] and (snapshot is None or snapshot['unique_id'] not in self.value['writers'] and snapshot['unique_id'] not in self.value['roots']):
            self._commit(lambda s: s['pending'].update({key: dict(pid=pid, reason='required native lineage pending')}))
        if snapshot is None:
            return False  # An absent required candidate has no historical chain.
        unique = snapshot['unique_id']
        matches = [root for root, graph in self.graphs.items()
                   if unique == root or graph.lineage(snapshot['original_parent_unique_id']) is not None
                   or required]
        if not matches:
            if not self._potential_candidate(snapshot):
                return False
            required = True
            if key not in self.value['pending']:
                self._commit(lambda s: s['pending'].update({key: dict(pid=pid, reason='new target-app process lacks complete observed original-parent chain')}))
            matches = list(self.graphs)
        if self.latest.get(unique) == semantic(snapshot):
            return any(graph.lineage(unique) is not None for graph in self.graphs.values())
        exe = executable_path(pid)
        if unique in self.value['roots'] and 'target_executable' in self.value['roots'][unique]:
            target = self.value['roots'][unique]['target_executable']
            if exe == target['path']:
                verify_target(target)
        confirmed = native.read_snapshot(pid)
        if confirmed is None or semantic(confirmed) != semantic(snapshot) or executable_path(pid) != exe:
            raise EvidenceError('native birth/executable changed during observation')
        resolved = []
        for root in matches:
            if self.graphs[root].ingest(snapshot) is not None:
                resolved.append(root)
        if len(resolved) > 1:
            raise EvidenceError('ambiguous native observation root')
        def commit(session):
            sequence = self._append(session, snapshot, exe)
            if resolved:
                session['pending'].pop(key, None)
                if unique not in session['roots']:
                    session['writers'][unique] = dict(authority=dict(AUTHORITY), root=resolved[0],
                        identity=snapshot['identity'], unique_id=unique, observation_sequence=sequence,
                        lineage_observation_sequences=exact_chain_sequences(session, resolved[0], sequence))
            else:
                session['pending'][key] = dict(pid=pid, reason='full original-parent unique-ID/version chain missing')
            # A newly seen intermediary can complete an older immutable chain.
            for root, graph in self.graphs.items():
                for prior in reversed(session['observations']):
                    node = prior['snapshot']
                    if node['unique_id'] in session['roots'] or node['unique_id'] in session['writers']:
                        continue
                    if graph.lineage(node['unique_id']) is not None:
                        session['writers'][node['unique_id']] = dict(authority=dict(AUTHORITY), root=root,
                            identity=node['identity'], unique_id=node['unique_id'], observation_sequence=prior['sequence'],
                            lineage_observation_sequences=exact_chain_sequences(session, root, prior['sequence']))
                        session['pending'].pop('pid:' + str(node['identity']['pid']), None)
        self._commit(commit)
        self.latest[unique] = semantic(snapshot)
        return bool(resolved)

    def sample(self, *, force_census=False, deadline=None):
        if deadline is not None:
            _remaining(deadline)
        self._active(allow_closing=True)
        if deadline is not None:
            _remaining(deadline)
        if not self.graphs:
            return
        # Fast breadth-first direct-child discovery runs continuously while the
        # private command pipe is idle. The lower-frequency UID census can find
        # a reparented child only if its complete genuine chain was sampled.
        known = {item['pid'] for item in self.value['roots'].values()}
        known.update(item['identity']['pid'] for item in self.value['writers'].values())
        known.update(item['pid'] for item in self.value['pending'].values())
        queue, scanned = list(sorted(known)), set()
        while queue:
            if deadline is not None:
                _remaining(deadline)
            pid = queue.pop(0)
            if pid in scanned:
                continue
            if len(scanned) >= MAX_NODES:
                raise EvidenceError('native sampler node bound exceeded')
            scanned.add(pid)
            self.observe(pid, required=False)
            for child in child_pids(pid):
                if deadline is not None:
                    _remaining(deadline)
                self.observe(child, required=True)
                if child not in scanned:
                    queue.append(child)
        if force_census or time.monotonic() - self.last_census >= .25:
            if self.value.get('cleanup_barrier') is None and self.value['state'] != 'closing':
                self.check_working_capacity(deadline=deadline)
            for pid in candidate_pids():
                if deadline is not None:
                    _remaining(deadline)
                self.observe(pid, required=False)
            self.last_census = time.monotonic()
        if self.value['state'] == 'failed':
            raise EvidenceError('post-barrier native sampling invalidated cleanup readiness')

    def check_working_capacity(self, *, deadline=None):
        if self.value['state'] == 'closing' or self.value.get('cleanup_barrier') is not None:
            return  # Caller owns guarded content deletion after prepare ACK.
        from .producer_runtime import read
        record = read(self.ledger, self.attempt)
        binding = working_binding(self.ledger, record, session=self.value)
        deadline = min(time.monotonic() + .25, deadline) if deadline is not None else time.monotonic() + .25
        total_bytes, total_files = 0, 0
        seen_ipc = {}
        for ref, item in self.value['working_roots'].items():
            _resource_current(item)
            current_ipc = {}
            size, count = _bounded_usage(item['path'], deadline=deadline, max_entries=self.value['runtime_file_limit'], ipc=current_ipc)
            for path, ipc in current_ipc.items():
                ipc['root_ref'] = ref
                if ipc['kind'] == 'symlink':
                    target = Path(os.path.normpath(os.path.join(str(Path(path).parent), ipc['target'])))
                    if not any(target.is_relative_to(root['path']) for root in self.value['working_roots'].values()):
                        raise EvidenceError('IPC symlink target has no declared SDK working-root reference')
                if path in self.value['ipc_paths'] and self.value['ipc_paths'][path] != ipc:
                    raise EvidenceError('observed IPC path identity changed')
                seen_ipc[path] = ipc
            if size > item['budget_bytes']:
                raise EvidenceError('SDK working root exceeded declared byte budget')
            total_bytes += size; total_files += count
        if total_bytes > binding['row']['bytes'] or total_files > self.value['runtime_file_limit']:
            raise EvidenceError('runtime working roots exceeded separate held capacity/file limit')
        additions = {path: item for path, item in seen_ipc.items() if path not in self.value['ipc_paths']}
        if additions:
            self._commit(lambda s: s['ipc_paths'].update(additions))

    def _cleanup_checks(self, timeout, *, require_empty):
        from .producer_runtime import read
        record = read(self.ledger, self.attempt)
        working_binding(self.ledger, record, session=self.value)
        if (not self.value['roots'] or self.value['pending'] or self.value['errors'] or self.value['lost_history']
                or self.value['state'] not in ('observing', 'closing')):
            raise EvidenceError('cleanup preparation retains pending/errors/lost history')
        deadline = time.monotonic() + timeout
        # Prior CLOSED sessions retain their independent immutable obligations.
        if record.get('observation_history'):
            prior = copy.deepcopy(record)
            archived = prior['observation_history'].pop()
            prior['observation_session'] = archived['session']
            problems = disposition_problems(prior, ledger=self.ledger, timeout=max(.001, deadline - time.monotonic()))
            if problems:
                raise EvidenceError('prior observer disposition incomplete: ' + '; '.join(problems))
        targets = {root['pid']: root['identity'] for root in self.value['roots'].values()}
        targets.update({writer['identity']['pid']: writer['identity'] for writer in self.value['writers'].values()})
        for pid, identity in targets.items():
            if time.monotonic() >= deadline:
                raise EvidenceError('cleanup native disposition deadline expired')
            if native.read_snapshot(pid, include_zombie=True) is not None:
                raise EvidenceError('cleanup requires exact birth gone and numeric ESRCH: ' + str(pid))
        for item in self.value['working_roots'].values():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EvidenceError('cleanup root/handle deadline expired')
            _resource_current(item)
            _no_handles(item, remaining, allow_absent=False, require_empty=require_empty)
            _resource_current(item)

    def prepare_cleanup(self, timeout):
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise EvidenceError('cleanup preparation timeout must be bounded by 30 seconds')
        deadline = time.monotonic() + timeout
        self._active()
        self.sample(force_census=True, deadline=deadline)
        self._cleanup_checks(_remaining(deadline), require_empty=False)
        # A second forced census immediately precedes the durable barrier. It
        # cannot turn a pending candidate into an empty successful registry.
        self.sample(force_census=True, deadline=deadline)
        self._cleanup_checks(_remaining(deadline), require_empty=False)
        barrier = dict(valid=True, sequence=self.value['sequence'], root_refs=sorted(self.value['working_roots']),
                       numeric_absent=True, roots_no_handles=True, closed=False)
        self._commit(lambda s: s.update(state='closing', cleanup_barrier=barrier))
        return dict(ready=True, root_refs=barrier['root_refs'], sequence=barrier['sequence'], closed=False)

    def close(self, timeout):
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise EvidenceError('observer closure timeout must be bounded by 30 seconds')
        deadline = time.monotonic() + timeout
        self._active(allow_closing=True)
        first_problem = None
        while True:
            try:
                self.sample(force_census=True, deadline=deadline)
                self._cleanup_checks(_remaining(deadline), require_empty=True)
                # Re-observe current processes once more after handle/root checks.
                self.sample(force_census=True, deadline=deadline)
                self._cleanup_checks(_remaining(deadline), require_empty=True)
                closure = dict(sequence=self.value['sequence'], numeric_absent=True, roots_no_handles=True)
                self._commit(lambda s: s.update(state='closed', closure=closure))
                return dict(closed=True, durable=True, sequence=self.value['sequence'])
            except (EvidenceError, OSError) as exc:
                first_problem = first_problem or str(exc)
                if self.value['state'] == 'failed' or time.monotonic() >= deadline:
                    raise EvidenceError('observer closure incomplete: ' + first_problem[:1024]) from exc
                time.sleep(min(.05, max(.001, deadline - time.monotonic())))

    def request(self, value):
        """Strict commands deliberately have no kernel witness/snapshot argument."""
        if type(value) is not dict or type(value.get('command')) is not str or len(canonical(value)) > MAX_REQUEST:
            raise EvidenceError('invalid bounded observer command')
        command = value['command']
        fields = {'allocate_root': {'command', 'purpose', 'budget_bytes'},
                  'register_root': {'command', 'pid', 'expected_identity', 'expected_executable', 'writable_root_refs'},
                  'observe_pid': {'command', 'pid'}, 'close': {'command', 'timeout'},
                  'prepare_cleanup': {'command', 'timeout'}}
        if command not in fields or (set(value) != fields[command] and not
                (command == 'register_root' and set(value) == fields[command] | {'expected_target_executable'})):
            raise EvidenceError('unknown observer command or caller-submitted witness')
        if command == 'allocate_root':
            return self.allocate(value['purpose'], value['budget_bytes'])
        if command == 'register_root':
            return self.register_root(value['pid'], value['expected_identity'], value['expected_executable'], value['writable_root_refs'], value.get('expected_target_executable'))
        if command == 'observe_pid':
            self._active()
            return dict(associated=self.observe(value['pid']))
        if command == 'prepare_cleanup':
            return self.prepare_cleanup(value['timeout'])
        return self.close(value['timeout'])
