"""Bounded POSIX current custody, distinct from historical physical identity.

Portable validators do no I/O. Native checks retain the original failed record;
the only substituted historical field is the uniformly changed device number.
Publication checks use the live Manager, including through a finite anonymous
guardian channel. A saved acknowledgement is never generation authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import select
import socket
import stat
import time
import uuid

from .io import EvidenceError, _open_regular, _verify_stable, _parents, _is_link
from .quarantine import (canonical, digest, _hash, _text, _amount, _inode, _time,
                         validate_quarantine_descriptor, validate_original)

ASSERTION_FIELDS = set('version kind operation_id project_id store_id ledger_id attempt_id reservation_id intent_id original_descriptor_digest original_record_sha256 original_policy_sha256 current_policy_sha256 coordinator_authority_sha256 root_path old_view new_view verifier observed_at purpose limitations'.split())
WITNESS_FIELDS = set('version kind operation_id project_id store_id ledger_id attempt_id run_id unit_id reservation_id output_id intent_id original_descriptor_digest original_record_sha256 original_policy_sha256 current_policy_sha256 coordinator_authority_sha256 root_path old_view new_view assertion validated_at history_complete same_volume_proven digest'.split())
MAXIMUM = 1024 * 1024
PUBLICATION_TIMEOUT = 600.0


def _keys(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise EvidenceError('invalid ' + label + ' fields')


def _uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _path(value):
    return (_text(value) and Path(value).is_absolute() and '..' not in Path(value).parts
            and str(Path(value)) == value and '\\' not in value)


def _bounded(value, policy):
    try:
        size = len(canonical(value))
    except (ValueError, TypeError, RecursionError) as exc:
        raise EvidenceError('custody metadata must be finite bounded JSON') from exc
    if size > min(policy['limits']['metadata_stop_bytes'], MAXIMUM):
        raise EvidenceError('custody metadata exceeds byte allowance')


def _views(old, new, descriptor, policy):
    _keys(old, {'root_identity', 'inventory_sha256', 'inventory'}, 'old view')
    if old != {'root_identity': descriptor['output_identity'],
               'inventory_sha256': descriptor['inventory_sha256'], 'inventory': descriptor['inventory']}:
        raise EvidenceError('custody original captured view differs')
    _keys(new, {'root', 'files'}, 'new view')
    root = new['root']
    _keys(root, {'identity', 'uid', 'mode', 'mtime_ns', 'ctime_ns'}, 'current root')
    def identity(value):
        return isinstance(value, list) and len(value) == 2 and all(_inode(x) for x in value)
    if (not identity(root['identity']) or root['identity'][0] == old['root_identity'][0]
            or root['identity'][1] != old['root_identity'][1] or root['mode'] != 0o700
            or any(not _amount(root[k]) for k in ('uid', 'mode', 'mtime_ns', 'ctime_ns'))):
        raise EvidenceError('invalid current root device/identity/metadata')
    files = new['files']
    if not isinstance(files, list) or len(files) != len(old['inventory']) or len(files) > policy['limits']['metadata_stop_files']:
        raise EvidenceError('current captured file inventory differs')
    if sum(item['size'] for item in old['inventory']) > policy['limits']['local_stop_bytes']:
        raise EvidenceError('custody inventory exceeds local byte allowance')
    if [item['path'] for item in old['inventory']] != sorted(item['path'] for item in old['inventory']):
        raise EvidenceError('original captured file inventory is not sorted')
    for entry, original in zip(files, old['inventory']):
        _keys(entry, {'path', 'identity', 'size', 'sha256', 'uid', 'mode', 'nlink', 'mtime_ns', 'ctime_ns'}, 'current file')
        if (not isinstance(original['path'], str) or '/' in original['path']
                or original['identity'][0] != old['root_identity'][0]
                or not identity(entry['identity']) or entry['identity'] != [root['identity'][0], original['identity'][1]]
                or any(entry[k] != original[k] for k in ('path', 'size', 'sha256'))
                or entry['uid'] != root['uid'] or entry['mode'] != 0o600 or entry['nlink'] != 1
                or any(not _amount(entry[k]) for k in ('size', 'uid', 'mode', 'nlink', 'mtime_ns', 'ctime_ns'))):
            raise EvidenceError('current file is not the exact uniform-device captured view')


def validate_device_custody_assertion(value, descriptor, policy):
    """Validate declared bytes only; no filesystem, clock, process or DB calls."""
    _bounded(descriptor, policy)
    validate_quarantine_descriptor(descriptor)
    # Callers supply the normalized, validated policy (Accounting, Manager and
    # Checker already own that validation). Do not call the policy loader here:
    # it reads packaged defaults and would make a portable validator perform IO.
    policies = {digest(policy)}
    lineage = policy.get('policy_lineage')
    if lineage:
        policies.add(lineage['base']['policy_sha256'])
        for i, step in enumerate(lineage['steps']):
            policies.add(digest({**step['policy'], 'policy_lineage': {
                'version': 1, 'base': lineage['base'], 'steps': lineage['steps'][:i + 1]}}))
    if (descriptor['project_id'] != policy['project_id'] or descriptor['store_id'] != policy['store_id']
            or descriptor['policy_sha256'] not in policies):
        raise EvidenceError('custody original policy/project/store binding changed')
    _bounded(value, policy)
    _keys(value, ASSERTION_FIELDS, 'custody assertion')
    if (type(value['version']) is not int or value['version'] != 1
            or value['kind'] != 'quarantine-device-current-custody-assertion'
            or not _uuid(value['operation_id']) or not _path(value['root_path'])
            or value['purpose'] != 'retain-quarantined-gap-for-fresh-distinct-runs'
            or not _text(value['verifier']) or not _text(value['limitations']) or not _time(value['observed_at'])):
        raise EvidenceError('invalid custody assertion identity/purpose/limitations')
    for key in ('project_id', 'store_id', 'ledger_id', 'attempt_id', 'reservation_id', 'intent_id'):
        if value[key] != descriptor[key] or not _text(value[key]):
            raise EvidenceError('custody assertion binding changed: ' + key)
    expected = {'original_descriptor_digest': descriptor['digest'], 'original_record_sha256': descriptor['original_record_sha256'],
                'original_policy_sha256': descriptor['policy_sha256'], 'current_policy_sha256': digest(policy)}
    if any(value[k] != v for k, v in expected.items()) or not _hash(value['coordinator_authority_sha256']):
        raise EvidenceError('custody assertion policy/descriptor/authority binding changed')
    _views(value['old_view'], value['new_view'], descriptor, policy)
    return value


def validate_quarantine_device_witness(value, descriptor, policy):
    _bounded(value, policy)
    _keys(value, WITNESS_FIELDS, 'custody witness')
    if (type(value['version']) is not int or value['version'] != 1
            or value['kind'] != 'quarantine-device-current-custody'
            or value['history_complete'] is not False or value['same_volume_proven'] is not False
            or not _time(value['validated_at']) or not _hash(value['digest'])
            or digest({k: v for k, v in value.items() if k != 'digest'}) != value['digest']):
        raise EvidenceError('invalid custody witness flags/digest')
    assertion = value['assertion']
    _keys(assertion, {'ref', 'payload', 'sha256'}, 'embedded assertion')
    _keys(assertion['ref'], {'path', 'sha256'}, 'assertion reference')
    payload = validate_device_custody_assertion(assertion['payload'], descriptor, policy)
    if (not _path(assertion['ref']['path']) or not _hash(assertion['sha256'])
            or not _hash(assertion['ref']['sha256'])):
        raise EvidenceError('invalid custody assertion reference/hash')
    # The reference hashes original file bytes, which may have whitespace. The
    # payload hash uses canonical bytes; both are bound, never conflated.
    if digest(payload) != assertion['sha256']:
        raise EvidenceError('embedded assertion SHA differs from canonical payload')
    for key in ASSERTION_FIELDS - {'version', 'kind', 'verifier', 'observed_at', 'purpose', 'limitations'}:
        if value[key] != payload[key]:
            raise EvidenceError('custody witness/assertion cross-binding changed: ' + key)
    for key in ('run_id', 'unit_id', 'output_id'):
        if value[key] != descriptor[key]:
            raise EvidenceError('custody witness original identity changed: ' + key)
    return value


def validate_device_custody_receipt(receipt, policy, quarantines):
    """Validate declared witness closure; existing scoped rules remain separate."""
    _bounded(receipt, policy)
    if receipt.get('version') != 3 or type(receipt.get('version')) is not int or receipt.get('kind') != 'scoped-known-generation-with-device-custody':
        raise EvidenceError('invalid custody receipt kind/version')
    flags = {'accounting_complete': False, 'incomplete': True, 'totals_are_lower_bounds': True,
             'history_complete': False, 'generation_ready': True}
    if any(type(receipt.get(k)) is not bool or receipt[k] is not v for k, v in flags.items()):
        raise EvidenceError('custody receipt must retain historical uncertainty')
    witnesses, bindings = receipt.get('quarantine_device_witnesses'), receipt.get('quarantine_device_catalog')
    if not isinstance(witnesses, list) or not witnesses or len(witnesses) > policy['limits']['metadata_stop_files'] or not isinstance(bindings, dict):
        raise EvidenceError('custody receipt requires witness/catalog closure')
    descriptors = {q['digest']: q for q in quarantines}
    result, operations, attempts, reservations = {}, set(), set(), set()
    for witness in witnesses:
        if not isinstance(witness, dict) or witness.get('original_descriptor_digest') not in descriptors:
            raise EvidenceError('custody receipt witness lacks original quarantine')
        validate_quarantine_device_witness(witness, descriptors[witness['original_descriptor_digest']], policy)
        ident = witness['original_descriptor_digest']
        if ident in result or witness['operation_id'] in operations or witness['attempt_id'] in attempts or witness['reservation_id'] in reservations:
            raise EvidenceError('duplicate custody witness binding')
        result[ident] = witness
        operations.add(witness['operation_id']); attempts.add(witness['attempt_id']); reservations.add(witness['reservation_id'])
        binding = bindings.get(ident)
        _keys(binding, {'root_key', 'sequence', 'segment_sha256', 'witness_digest'}, 'custody catalog binding')
        if (not _text(binding['root_key']) or not _amount(binding['sequence']) or binding['sequence'] < 1
                or not _hash(binding['segment_sha256']) or binding['witness_digest'] != witness['digest']):
            raise EvidenceError('custody receipt catalog binding differs')
    if set(bindings) != set(result):
        raise EvidenceError('custody receipt catalog closure differs')
    return result


def _metadata(info, *, root=False):
    result = {'identity': [info.st_dev, info.st_ino], 'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode),
              'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns}
    if not root:
        result['nlink'] = info.st_nlink
    return result


def scan_current(ledger, descriptor, record):
    if os.name != 'posix' or not hasattr(os, 'getuid'):
        raise EvidenceError('quarantine device revalidation requires POSIX')
    root = Path(record['output_dir'])
    if not _path(str(root)):
        raise EvidenceError('custody root must retain original absolute path')
    _parents(root / 'placeholder')
    parents = [(p, (p.lstat().st_dev, p.lstat().st_ino)) for p in root.parents]
    before = root.lstat()
    if (_is_link(before) or not stat.S_ISDIR(before.st_mode) or os.path.ismount(root)
            or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o700):
        raise EvidenceError('custody requires current owned private nonmount directory')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        initial = _metadata(before, root=True)
        if _metadata(os.fstat(fd), root=True) != initial:
            raise EvidenceError('custody root changed while opening')
        names = sorted(os.listdir(fd))
        expected = [item['path'] for item in descriptor['inventory']]
        if names != expected or len(names) > ledger.policy['limits']['metadata_stop_files']:
            raise EvidenceError('custody flat file inventory changed')
        files = []
        for name in names:
            path, handle, info = _open_regular(root / name)
            try:
                if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                        or info.st_nlink != 1 or info.st_dev != before.st_dev):
                    raise EvidenceError('custody file owner/mode/link/device changed')
                if info.st_size > ledger.policy['limits']['local_stop_bytes']:
                    raise EvidenceError('custody file exceeds local read bound')
                h, size = hashlib.sha256(), 0
                while block := os.read(handle, min(1024 * 1024, info.st_size - size + 1)):
                    h.update(block); size += len(block)
                    if size > info.st_size:
                        raise EvidenceError('custody file grew while reading')
                _verify_stable(path, handle, info)
                files.append(dict(path=name, size=size, sha256=h.hexdigest(), **_metadata(info)))
            finally:
                os.close(handle)
        _parents(root / 'placeholder')
        if (sorted(os.listdir(fd)) != names or _metadata(os.fstat(fd), root=True) != initial
                or _metadata(root.lstat(), root=True) != initial
                or any((p.lstat().st_dev, p.lstat().st_ino) != identity for p, identity in parents)):
            raise EvidenceError('custody directory/parent changed during scan')
        result = {'root': initial, 'files': files}
        _views({'root_identity': descriptor['output_identity'], 'inventory_sha256': descriptor['inventory_sha256'],
                'inventory': descriptor['inventory']}, result, descriptor, ledger.policy)
        return result
    finally:
        os.close(fd)


def verify_quarantine_device_current(ledger, descriptor, witness, *, coordinator_authority):
    validate_quarantine_device_witness(witness, descriptor, ledger.policy)
    record = validate_original(ledger, descriptor)
    if (not isinstance(coordinator_authority, dict) or digest(coordinator_authority) != witness['coordinator_authority_sha256']
            or str(Path(record['output_dir'])) != witness['root_path'] or witness['ledger_id'] != ledger._ledger_id):
        raise EvidenceError('custody native coordinator/path/ledger binding changed')
    if scan_current(ledger, descriptor, record) != witness['new_view']:
        raise EvidenceError('custody current captured view changed')
    if read_assertion(witness['assertion']['ref'], descriptor, ledger.policy) != witness['assertion']['payload']:
        raise EvidenceError('named custody assertion bytes changed')
    validate_original(ledger, descriptor)  # repeat owner/resource barrier
    return witness


def read_assertion(ref, descriptor, policy):
    _keys(ref, {'path', 'sha256'}, 'assertion reference')
    if not _path(ref['path']) or not _hash(ref['sha256']):
        raise EvidenceError('invalid named assertion reference')
    path, fd, info = _open_regular(Path(ref['path']))
    try:
        if os.name != 'posix' or info.st_uid != os.getuid() or info.st_size > min(MAXIMUM, policy['limits']['metadata_stop_bytes']):
            raise EvidenceError('assertion must be a bounded current-user owned POSIX file')
        raw = bytearray()
        while block := os.read(fd, min(65536, info.st_size - len(raw) + 1)):
            raw.extend(block)
            if len(raw) > info.st_size:
                raise EvidenceError('assertion changed during read')
        _verify_stable(path, fd, info)
    finally:
        os.close(fd)
    if hashlib.sha256(raw).hexdigest() != ref['sha256']:
        raise EvidenceError('named assertion SHA changed')
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise EvidenceError('duplicate assertion key')
            result[k] = v
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    validate_device_custody_assertion(value, descriptor, policy)
    return value


def build_witness(ledger, descriptor, assertion_ref, operation_id, authority):
    assertion = read_assertion(assertion_ref, descriptor, ledger.policy)
    if assertion['operation_id'] != operation_id:
        raise EvidenceError('custody operation differs from named assertion')
    value = {k: assertion[k] for k in ASSERTION_FIELDS - {'version', 'kind', 'verifier', 'observed_at', 'purpose', 'limitations'}}
    value.update(version=1, kind='quarantine-device-current-custody',
                 **{k: descriptor[k] for k in ('run_id', 'unit_id', 'output_id')},
                 assertion={'ref': assertion_ref, 'payload': assertion, 'sha256': digest(assertion)},
                 validated_at=datetime.now(timezone.utc).isoformat(), history_complete=False, same_volume_proven=False)
    value['digest'] = digest(value)
    return verify_quarantine_device_current(ledger, descriptor, value, coordinator_authority=authority)


class PublicationChannel:
    """One finite, private parent/guardian request stream, never a provider API."""
    def __init__(self, stream, *, deadline):
        self.stream, self.deadline, self.buffer = stream, deadline, b''
        self.seen = set()

    def close(self):
        self.stream.close()

    def check_deadline(self):
        if self.deadline <= time.monotonic():
            raise EvidenceError('publication verification deadline expired')

    def _line(self, timeout):
        if self.deadline <= time.monotonic():
            raise EvidenceError('publication verification deadline expired')
        end = min(self.deadline, time.monotonic() + timeout)
        while b'\n' not in self.buffer:
            remaining = end - time.monotonic()
            if remaining <= 0 or not select.select([self.stream], [], [], remaining)[0]:
                raise EvidenceError('publication verification deadline expired')
            block = self.stream.recv(65536)
            if not block:
                raise EvidenceError('publication verification channel lost')
            self.buffer += block
            if len(self.buffer) > MAXIMUM:
                raise EvidenceError('publication verification message exceeds bound')
        line, self.buffer = self.buffer.split(b'\n', 1)
        self.check_deadline()
        result = json.loads(line)
        self.check_deadline()
        return result

    def _send(self, value):
        raw = canonical(value) + b'\n'
        if len(raw) > MAXIMUM:
            raise EvidenceError('publication verification message exceeds bound')
        remaining = min(PUBLICATION_TIMEOUT, self.deadline - time.monotonic())
        if remaining <= 0:
            raise EvidenceError('publication verification deadline expired')
        self.stream.settimeout(remaining)
        try:
            self.stream.sendall(raw)
        finally:
            self.stream.settimeout(None)

    def request(self, ledger, intent_id, attempt_id, phase):
        nonce = str(uuid.uuid4())
        request = dict(version=1, phase=phase, nonce=nonce, intent_id=intent_id, attempt_id=attempt_id,
                       ledger_id=ledger._ledger_id)
        self._send(request)
        response = self._line(PUBLICATION_TIMEOUT)
        _keys(response, {'request', 'publication', 'error'}, 'publication response')
        if canonical(response['request']) != canonical(request) or response['error'] is not None:
            raise EvidenceError('publication verification rejected: ' + str(response['error']))
        if not isinstance(response['publication'], dict):
            raise EvidenceError('publication verification response missing coverage')
        return response['publication']

    def service(self, manager, ledger, intent_id, attempt_id, *, cancelled=False, timeout=.03):
        if not self.buffer and not select.select([self.stream], [], [], timeout)[0]:
            return
        request = self._line(PUBLICATION_TIMEOUT)
        error, publication = None, None
        try:
            _keys(request, {'version', 'phase', 'nonce', 'intent_id', 'attempt_id', 'ledger_id'}, 'publication request')
            if (type(request['version']) is not int or request['version'] != 1 or not _uuid(request['nonce'])
                    or request['phase'] not in ('guardian-launch', 'completion')
                    or request['intent_id'] != intent_id or request['attempt_id'] != attempt_id
                    or request['ledger_id'] != ledger._ledger_id or cancelled or request['nonce'] in self.seen):
                raise EvidenceError('publication request cancelled or rebound')
            self.seen.add(request['nonce'])
            publication = manager._producer_publication_coverage(ledger, intent_id, attempt_id=attempt_id, deadline=self.deadline)
        except (EvidenceError, OSError, ValueError, TypeError, KeyError) as exc:
            error = str(exc)
        self._send(dict(request=request, publication=publication, error=error))
