"""Immutable policy ancestry and quarantine compatibility on synthetic metadata."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/to-sdd-pipeline/scripts'
sys.path.insert(0, str(SCRIPTS))
from evidence import policy as policies
from evidence.io import EvidenceError
from evidence.quarantine import digest, validate_quarantine_descriptor


def setup_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode('utf-8')


def effective(value):
    return {key: deepcopy(item) for key, item in value.items() if key != 'policy_lineage'}


def policy_fixture():
    value = policies.load_defaults()
    value.update(project_id=str(uuid.uuid4()), store_id=str(uuid.uuid4()), provider='local')
    return policies.validate_policy(value)


def descriptor_fixture(policy):
    # Metadata validation only: these nonexistent references are never opened.
    root = Path(tempfile.gettempdir()).resolve() / 'sdd-synthetic-lineage-proof'
    raw = b'{"status":"incomplete","observations":{},"retained":true}'
    original_hash = hashlib.sha256(raw).hexdigest()
    attempt, reservation = str(uuid.uuid4()), str(uuid.uuid4())
    value = {'version': 1, 'kind': 'quarantined-producer-gap',
             'project_id': policy['project_id'], 'store_id': policy['store_id'],
             'ledger_id': str(uuid.uuid4()), 'policy_sha256': digest(policy), 'attempt_id': attempt,
             'run_id': 'old-failed-run', 'unit_id': 'unit', 'ordinal': 0,
             'reservation_id': reservation, 'output_id': str(uuid.uuid4()), 'intent_id': str(uuid.uuid4()),
             'original_record_sha256': original_hash,
             'uncertain': {'reservation_id': reservation, 'gross_bytes': 600, 'logical_files': 2},
             'reservation': {'id': reservation, 'run_id': 'old-failed-run', 'state': 'pending',
                             'bytes': 512, 'files': 10, 'local_bytes': 512, 'metadata_bytes': 1024,
                             'metadata_files': 1, 'retained_bytes': 0, 'retained_objects': 0, 'created': 1.0},
             'run': {'id': 'old-failed-run', 'unit_id': 'unit', 'ordinal': 0, 'gross_bytes': 600,
                     'gross_files': 2, 'migration': 0, 'status': 'incomplete', 'created': 1.0},
             'disposition': 'quarantined-unresolved', 'history_complete': False,
             'proof': {'version': 1, 'kind': 'producer-disposition', 'attempt_id': attempt,
                       'original_record_sha256': original_hash, 'verifier': 'synthetic-host',
                       'observed_at': '2026-10-22T00:00:00+00:00', 'external_disposition': {
                           'coverage': 'all-unregistered-helpers-and-resources',
                           'journal': {'path': str(root / 'journal.json'), 'sha256': 'a' * 64},
                           'proof': {'path': str(root / 'proof.json'), 'sha256': 'b' * 64},
                           'limitations': 'Synthetic metadata only; original accounting remains unknown.'}},
             'inventory': [], 'inventory_sha256': digest([]), 'output_identity': [1, 2],
             'quarantined_at': '2026-10-22T00:00:00+00:00'}
    value['digest'] = digest(value)
    return value


class PolicyLineageTests(unittest.TestCase):
    def setUp(self):
        self.base = policy_fixture()
        # Arbitrary original version1 formatting is preserved once, byte for byte.
        self.raw = (json.dumps(self.base, sort_keys=False, indent=4) + '\n\n').encode()

    def transition(self, previous, key='max_unit_retries', increase=1, raw=None, inherited=False):
        candidate = deepcopy(previous) if inherited else effective(previous)
        candidate['limits'][key] += increase
        return policies.append_policy_transition(raw if raw is not None else setup_bytes(previous), candidate)

    def chain(self):
        first = self.transition(self.base, raw=self.raw)
        second = self.transition(first, key='unit_stop_files', increase=7)
        return first, second

    def test_no_lineage_v1_validation_and_resolution_remain_unchanged(self):
        self.assertNotIn('policy_lineage', policies.validate_policy(self.base))
        self.assertEqual(self.base, policies.resolve_historical_policy(self.base, digest(self.base)))
        with self.assertRaises(EvidenceError): policies.resolve_historical_policy(self.base, 'a' * 64)

    def test_original_raw_anchor_and_exact_first_diff_are_bound(self):
        before = deepcopy(self.base)
        first = self.transition(self.base, raw=self.raw)
        lineage = first['policy_lineage']; step = lineage['steps'][0]
        self.assertEqual(lineage['base'], {'raw_utf8': self.raw.decode(), 'raw_sha256': hashlib.sha256(self.raw).hexdigest(), 'policy_sha256': digest(self.base)})
        self.assertEqual(step['from_policy_sha256'], digest(self.base))
        self.assertEqual(step['from_raw_sha256'], hashlib.sha256(self.raw).hexdigest())
        self.assertIsNone(step['previous_sha256'])
        self.assertEqual(step['changes'], {'max_unit_retries': {'from': self.base['limits']['max_unit_retries'], 'to': first['limits']['max_unit_retries']}})
        self.assertEqual(step['policy'], effective(first))
        self.assertEqual(step['digest'], digest({key: value for key, value in step.items() if key != 'digest'}))
        self.assertEqual(self.base, before)

    def test_multiple_transitions_resolve_exact_full_prefix_not_effective_only(self):
        first, second = self.chain()
        self.assertEqual(policies.resolve_historical_policy(second, digest(self.base)), self.base)
        self.assertEqual(policies.resolve_historical_policy(second, digest(first)), first)
        self.assertEqual(policies.resolve_historical_policy(second, digest(second)), second)
        with self.assertRaises(EvidenceError): policies.resolve_historical_policy(second, digest(effective(first)))
        step = second['policy_lineage']['steps'][1]
        self.assertEqual(step['from_policy_sha256'], digest(first))
        self.assertEqual(step['from_raw_sha256'], hashlib.sha256(setup_bytes(first)).hexdigest())
        self.assertEqual(step['previous_sha256'], first['policy_lineage']['steps'][0]['digest'])

    def test_resolved_ancestor_is_detached_from_current_and_subsequent_resolves(self):
        first, second = self.chain(); before = setup_bytes(second)
        resolved = policies.resolve_historical_policy(second, digest(first))
        resolved['policy_lineage']['base']['raw_utf8'] = 'tampered caller copy'
        resolved['limits']['max_unit_retries'] = 999
        self.assertEqual(before, setup_bytes(second))
        self.assertEqual(policies.resolve_historical_policy(second, digest(first)), first)

    def test_descriptors_created_before_and_after_first_transition_remain_byte_exact(self):
        first, second = self.chain()
        for original_policy in (self.base, first):
            descriptor = descriptor_fixture(original_policy); original = setup_bytes(descriptor)
            self.assertEqual(validate_quarantine_descriptor(descriptor, policy=original_policy), descriptor)
            self.assertEqual(validate_quarantine_descriptor(descriptor, policy=second), descriptor)
            self.assertEqual(setup_bytes(descriptor), original)
            self.assertEqual(descriptor['reservation']['bytes'], 512)
            self.assertEqual(descriptor['uncertain']['gross_bytes'], 600)
            self.assertFalse(descriptor['history_complete'])

    def test_descriptor_from_fork_or_foreign_identity_never_gains_compatibility(self):
        first, second = self.chain()
        fork = self.transition(self.base, key='max_unit_retries', increase=2, raw=self.raw)
        foreign = deepcopy(first); foreign['project_id'] = str(uuid.uuid4())
        for policy in (fork, foreign):
            descriptor = descriptor_fixture(policy)
            with self.assertRaises(EvidenceError): validate_quarantine_descriptor(descriptor, policy=second)

    def test_full_tail_is_validated_before_resolving_a_valid_base_digest(self):
        _, current = self.chain()
        mutations = [lambda p: p['policy_lineage']['steps'][-1].update(digest='a' * 64),
                     lambda p: p['policy_lineage']['steps'][-1].update(previous_sha256='a' * 64),
                     lambda p: p['policy_lineage']['steps'][-1].update(from_raw_sha256='a' * 64),
                     lambda p: p['policy_lineage']['steps'][-1].update(from_policy_sha256='a' * 64),
                     lambda p: p['policy_lineage']['base'].update(raw_sha256='a' * 64),
                     lambda p: p['policy_lineage']['base'].update(policy_sha256='a' * 64),
                     lambda p: p['policy_lineage']['steps'].reverse(),
                     lambda p: p['policy_lineage']['steps'].pop(),
                     lambda p: p['policy_lineage']['steps'].append(deepcopy(p['policy_lineage']['steps'][-1])),
                     lambda p: p['limits'].update(max_unit_retries=999),
                     lambda p: p['policy_lineage'].update(unrecognized=True)]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                broken = deepcopy(current); mutate(broken)
                with self.assertRaises(EvidenceError): policies.resolve_historical_policy(broken, digest(self.base))
                with self.assertRaises(EvidenceError): policies.validate_policy(broken)

    def test_resealed_semantic_forgery_still_fails_exact_diff_and_identity_validation(self):
        first, _ = self.chain()
        for key in ('retention', 'provider', 'changes', 'normalized'):
            with self.subTest(key=key):
                broken = deepcopy(first); step = broken['policy_lineage']['steps'][0]
                if key == 'retention':
                    step['policy']['retention']['local_days'] += 1; broken['retention']['local_days'] += 1
                elif key == 'provider': step['policy']['provider'] = 'folder'; broken['provider'] = 'folder'
                elif key == 'changes': step['changes']['max_unit_retries']['from'] += 1
                else: del step['policy']['targets']
                step['digest'] = digest({name: value for name, value in step.items() if name != 'digest'})
                with self.assertRaises(EvidenceError): policies.resolve_historical_policy(broken, digest(self.base))

    def test_transition_permits_limits_only_and_preserves_inputs_on_denial(self):
        first, _ = self.chain()
        mutations = [lambda p: p.update(project_id=str(uuid.uuid4())), lambda p: p.update(store_id=str(uuid.uuid4())),
                     lambda p: p.update(provider='folder'), lambda p: p['retention'].update(local_days=999),
                     lambda p: p['targets'].update(manifest_bytes=p['targets']['manifest_bytes'] + 1),
                     lambda p: p['git_review'].update(blob_bytes=p['git_review']['blob_bytes'] + 1)]
        for previous, raw in ((self.base, self.raw), (first, setup_bytes(first))):
            for mutate in mutations:
                candidate = effective(previous); mutate(candidate); before = deepcopy(candidate)
                with self.assertRaises(EvidenceError): policies.append_policy_transition(raw, candidate)
                self.assertEqual(candidate, before)

    def test_equal_inherited_lineage_is_allowed_but_replacement_or_null_is_not(self):
        first, _ = self.chain()
        self.assertEqual(self.transition(first, inherited=True), self.transition(first))
        for lineage in (None, {}, {'version': 1, 'base': {}, 'steps': []}):
            candidate = deepcopy(first); candidate['policy_lineage'] = lineage
            candidate['limits']['max_unit_retries'] += 1
            with self.assertRaises(EvidenceError): policies.append_policy_transition(setup_bytes(first), candidate)

    def test_noop_adds_no_step_or_optional_field_and_replay_is_identical(self):
        self.assertEqual(policies.append_policy_transition(self.raw, deepcopy(self.base)), self.base)
        first, _ = self.chain()
        self.assertEqual(policies.append_policy_transition(setup_bytes(first), effective(first)), first)
        self.assertEqual(self.transition(self.base, raw=self.raw), first)

    def test_only_first_raw_anchor_may_have_arbitrary_original_format(self):
        first, _ = self.chain(); candidate = effective(first); candidate['limits']['max_unit_retries'] += 1
        for raw in (json.dumps(first, indent=4).encode(), json.dumps(first, separators=(',', ':')).encode(),
                    setup_bytes(first).rstrip(b'\n'), b' ' + setup_bytes(first)):
            with self.assertRaises(EvidenceError): policies.append_policy_transition(raw, candidate)
        self.assertEqual(self.transition(first), policies.append_policy_transition(setup_bytes(first), candidate))

    def test_sixteen_transitions_are_bounded_and_seventeenth_does_not_mutate(self):
        current = self.base
        for index in range(16): current = self.transition(current, raw=self.raw if index == 0 else None)
        self.assertEqual(len(current['policy_lineage']['steps']), 16)
        before = setup_bytes(current)
        with self.assertRaises(EvidenceError): self.transition(current)
        self.assertEqual(setup_bytes(current), before)
        self.assertEqual(policies.resolve_historical_policy(current, digest(self.base)), self.base)

    def test_one_mib_policy_bound_and_oversized_original_are_enforced(self):
        raw = b' ' * (1024 * 1024) + self.raw
        with self.assertRaises(EvidenceError): self.transition(self.base, raw=raw)
        # The original fits but embedding escaped original text exceeds total policy bound.
        almost = b'\n' * (600 * 1024) + self.raw
        with self.assertRaises(EvidenceError): self.transition(self.base, raw=almost)

    def test_duplicate_json_fields_invalid_utf8_and_recursive_ancestry_are_denied(self):
        for raw in (b'{"version":1,"version":1}', b'\xff', b'null', b'[]'):
            with self.assertRaises(EvidenceError): self.transition(self.base, raw=raw)
        first, _ = self.chain(); broken = deepcopy(first)
        broken['policy_lineage']['base']['raw_utf8'] = setup_bytes(first).decode()
        with self.assertRaises(EvidenceError): policies.validate_policy(broken)

    def test_resealed_boolean_integer_alias_in_exact_diff_is_denied(self):
        base = deepcopy(self.base); base['limits']['max_unit_retries'] = 0
        first = self.transition(base)
        for key, replacement in (('from', False), ('to', True)):
            broken = deepcopy(first); step = broken['policy_lineage']['steps'][0]
            step['changes']['max_unit_retries'][key] = replacement
            step['digest'] = digest({name: value for name, value in step.items() if name != 'digest'})
            with self.assertRaises(EvidenceError): policies.validate_policy(broken)

    def test_reverting_effective_limits_does_not_alias_full_historical_policy(self):
        first, _ = self.chain()
        reverted = policies.append_policy_transition(setup_bytes(first), deepcopy(self.base))
        self.assertEqual(effective(reverted), self.base)
        self.assertNotEqual(digest(reverted), digest(self.base))
        self.assertEqual(len(reverted['policy_lineage']['steps']), 2)
        self.assertEqual(policies.resolve_historical_policy(reverted, digest(first)), first)
        self.assertEqual(policies.resolve_historical_policy(reverted, digest(self.base)), self.base)

    def test_exact_raw_receipt_binding_is_not_relaxed_by_ancestor_resolution(self):
        from test_sdd_check import sdd
        _, current = self.chain()
        receipt = {'version': 1, 'project_id': self.base['project_id'],
                   'policy_sha256': hashlib.sha256(self.raw).hexdigest(), 'runs': {}}
        original_receipt = deepcopy(receipt)
        with tempfile.TemporaryDirectory(prefix='sdd-lineage-receipt-') as directory:
            project = Path(directory).resolve(); (project / 'forge').mkdir()
            path = project / 'forge/evidence-policy.json'; path.write_bytes(self.raw)
            manifest = {'evidence_storage': {'policy_path': 'forge/evidence-policy.json'},
                        'evidence_accounting': receipt}
            sdd.Checker(project, manifest).evidence_accounting()
            path.write_bytes(setup_bytes(current))
            self.assertEqual(policies.resolve_historical_policy(current, digest(self.base)), self.base)
            with self.assertRaisesRegex(ValueError, 'another project or policy'):
                sdd.Checker(project, manifest).evidence_accounting()
            self.assertEqual(receipt, original_receipt)

    def test_unknown_or_noncanonical_digest_is_not_a_history_alias(self):
        first, second = self.chain()
        for wanted in ('', 'A' * 64, 'sha256:' + digest(first), 'a' * 63, 'a' * 64, None):
            with self.assertRaises(EvidenceError): policies.resolve_historical_policy(second, wanted)
