"""Fresh catalog locators reduce lookups without caching admission or readback."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_evidence_transports as fixtures
from evidence.connected_host import ConnectedHostAdapter
from evidence.io import EvidenceError
from evidence.manager import Manager, canonical
from evidence.policy import load_defaults
from evidence.transports import ConnectedDriveTransport


class CatalogFixture(fixtures.ConnectedFixture):
    def __init__(self):
        super().__init__()
        self.page_size = None
        self.list_transform = None
        self.metadata_transform = None

    def __call__(self, request):
        if request['operation'] != 'list':
            result = super().__call__(request)
            if request['operation'] == 'metadata' and self.metadata_transform:
                return self.metadata_transform(request, result)
            return result
        self.requests.append(dict(request))
        rows = [self.metadata(key) for key, item in self.objects.items()
                if item['key'].startswith(request.get('prefix', ''))]
        rows.reverse()  # Sorting is a transport duty, never provider ordering.
        if self.list_transform:
            rows = self.list_transform(request, rows)
        start = int(request['page_token']) if request.get('page_token') else 0
        end = start + self.page_size if self.page_size else len(rows)
        return {'objects': rows[start:end], 'next_page_token': str(end) if end < len(rows) else None}


def seed_catalog(manager, adapter):
    def add(key, value):
        data = canonical(value)
        identity = 'object-' + str(len(adapter.objects) + 1)
        adapter.objects[identity] = {'key': key, 'bytes': data}
        return {'object_id': identity, 'key': key, 'size': len(data)}, hashlib.sha256(data).hexdigest()
    authority, _ = add(manager.prefix + 'authority/coordinator.json', {
        'version': 1, 'project_id': manager.policy['project_id'], 'store_id': manager.policy['store_id'],
        'coordinator': manager.coordinator})
    segments, roots = [], []
    for number in (1, 2):
        value = {'version': 1, 'generation': {str(number): {
            'run_id': 'run-' + str(number), 'unit_id': 'unit', 'gross_bytes': number, 'logical_files': number}}}
        digest = hashlib.sha256(canonical(value)).hexdigest()
        locator, _ = add(manager.prefix + 'indexes/' + digest + '.json', value)
        segments.append({'sha256': digest, 'size': locator['size'], 'locator': locator})
        value = {'version': 1, 'project_id': manager.policy['project_id'], 'store_id': manager.policy['store_id'],
                 'sequence': number, 'coordinator': manager.coordinator, 'segments': list(segments)}
        digest = hashlib.sha256(canonical(value)).hexdigest()
        locator, _ = add(manager.prefix + 'roots/' + str(number).zfill(12) + '-' + digest + '.json', value)
        roots.append(locator)
    orphan, _ = add(manager.prefix + 'indexes/orphan.json', {'version': 1, 'unused': 'historical index still charged'})
    return {'authority': authority, 'roots': roots, 'segments': segments, 'orphan': orphan}


class CatalogInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='sdd-catalog-inventory-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.adapter = CatalogFixture()
        self.policy = {**load_defaults(), 'project_id': '11111111-1111-4111-8111-111111111111',
                       'store_id': '22222222-2222-4222-8222-222222222222', 'provider': 'google-drive'}
        self.policy['limits']['free_space_reserve_bytes'] = 0
        self.transport = ConnectedDriveTransport(self.adapter, 'fixture-folder', state_dir=self.root / 'transfers')
        self.manager = Manager(self.transport, self.root / 'home', self.policy)
        self.objects = seed_catalog(self.manager, self.adapter)
        self.adapter.requests.clear()

    def counts(self):
        return Counter(request['operation'] for request in self.adapter.requests)

    def test_inventory_returns_complete_validated_sorted_metadata_and_keys_stay_strings(self):
        self.adapter.page_size = 2
        inventory = self.transport.inventory(self.manager.prefix)
        expected = sorted((self.adapter.metadata(identity) for identity in self.adapter.objects),
                          key=lambda item: item['key'])
        self.assertEqual(expected, inventory)
        self.assertEqual(3, self.counts()['list'])
        self.adapter.requests.clear()
        keys = self.transport.keys(self.manager.prefix)
        self.assertEqual([item['key'] for item in inventory], keys)
        self.assertTrue(all(type(key) is str for key in keys))
        self.assertEqual(3, self.counts()['list'], 'keys must perform a fresh complete enumeration')

    def test_duplicate_key_or_id_across_pages_is_rejected(self):
        self.adapter.page_size = 1
        for change in ('key', 'object_id'):
            with self.subTest(change=change):
                def duplicate(request, rows):
                    rows[1] = {**rows[1], change: rows[0][change]}
                    return rows
                self.adapter.list_transform = duplicate
                with self.assertRaisesRegex(EvidenceError, 'duplicate'):
                    self.transport.inventory(self.manager.prefix)

    def test_invalid_metadata_outside_prefix_and_repeated_token_still_fail(self):
        for change in ({'object_id': ''}, {'size': True}, {'key': 'other/project'}, {'sha256': 'bad'}):
            with self.subTest(change=change):
                self.adapter.list_transform = lambda request, rows: [{**rows[0], **change}]
                with self.assertRaises(EvidenceError):
                    self.transport.inventory(self.manager.prefix)
        original = self.adapter
        def repeated(request):
            if request['operation'] == 'list':
                return {'objects': [], 'next_page_token': 'same-page'}
            return original(request)
        transport = ConnectedDriveTransport(repeated, 'fixture-folder', state_dir=self.root / 'repeated')
        with self.assertRaisesRegex(EvidenceError, 'repeated'):
            transport.inventory()

    def test_combined_listing_object_and_byte_bounds_remain_enforced(self):
        self.transport.max_objects = 2
        with self.assertRaisesRegex(EvidenceError, 'object bound'):
            self.transport.inventory(self.manager.prefix)
        self.transport.max_objects = 100
        self.adapter.page_size = 1
        self.transport.max_metadata_bytes = 500
        with self.assertRaisesRegex(EvidenceError, 'combined metadata bound'):
            self.transport.inventory(self.manager.prefix)

    def test_native_truncated_partial_and_saturated_listing_remains_rejected(self):
        native = object.__new__(ConnectedHostAdapter)
        native.max_objects = 100
        for extra in ({'truncated': True}, {'partial': True}, {'has_more': True},
                      {'incompleteSearch': True}, {'next_page_token': 'unavailable'},
                      {'files': [{'id': str(index)} for index in range(101)]}):
            with self.subTest(extra=extra):
                native._native = lambda *args, **kwargs: {'files': [], **extra}
                original = self.adapter
                def adapter(request):
                    if request['operation'] == 'list':
                        return native._search('fixture-folder', prefix=request['prefix'])
                    return original(request)
                transport = ConnectedDriveTransport(adapter, 'fixture-folder', state_dir=self.root / 'native')
                with self.assertRaises(EvidenceError):
                    transport.inventory(self.manager.prefix)

    def test_catalog_keeps_totals_downloads_and_every_fresh_stat_without_lookup(self):
        catalog = self.manager._catalog()
        self.assertEqual({'list': 4, 'metadata': 14, 'download_original': 4}, dict(self.counts()))
        self.assertEqual(6, catalog['metadata_files'])
        self.assertEqual(sum(len(value['bytes']) for value in self.adapter.objects.values()), catalog['metadata_bytes'])
        self.assertEqual(1616, catalog['metadata_bytes'], 'same synthetic bytes as preserved pre-edit baseline')
        self.assertEqual(self.objects['roots'][-1]['key'], catalog['root_key'])
        metadata_ids = [request['object_id'] for request in self.adapter.requests if request['operation'] == 'metadata']
        for identity in self.adapter.objects:
            self.assertIn(identity, metadata_ids, 'every root/index/authority requires fresh admission stat')
        downloads = [request for request in self.adapter.requests if request['operation'] == 'download_original']
        self.assertEqual(4, len(downloads))
        self.assertTrue(all(request['bypass_cache'] is True for request in downloads))

    def test_keys_only_transport_fallback_preserves_catalog_and_metadata_totals(self):
        class KeysOnly:
            inventory = None
            def __getattr__(self, name):
                return getattr(self.transport, name)
        fallback = KeysOnly()
        fallback.transport = self.transport
        manager = Manager(fallback, self.root / 'fallback-home', self.policy)
        catalog = manager._catalog()
        self.assertEqual(6, catalog['metadata_files'])
        self.assertEqual(1616, catalog['metadata_bytes'])
        self.assertEqual(10, self.counts()['lookup'])
        self.assertEqual(4, self.counts()['download_original'])

    def test_fresh_stat_growth_of_historical_root_or_orphan_index_blocks_admission(self):
        for locator in (self.objects['roots'][0], self.objects['orphan']):
            with self.subTest(locator=locator):
                def grow(request, value):
                    return {**value, 'size': self.manager.limits['metadata_stop_bytes'] + 1} \
                        if request['object_id'] == locator['object_id'] else value
                self.adapter.metadata_transform = grow
                with self.assertRaisesRegex(EvidenceError, 'catalog/history/index|metadata allowance'):
                    self.manager._catalog()
                self.assertTrue(any(request['operation'] == 'metadata' and request['object_id'] == locator['object_id']
                                    for request in self.adapter.requests))

    def test_fresh_stat_changed_stable_identity_or_key_is_rejected(self):
        for change in ({'object_id': 'substituted'}, {'key': 'other/renamed-object'}):
            with self.subTest(change=change):
                self.adapter.metadata_transform = lambda request, value: {**value, **change}
                with self.assertRaisesRegex(EvidenceError, 'identity|key'):
                    self.manager._catalog()

    def test_missing_index_membership_and_ambiguous_authority_still_block(self):
        missing = self.objects['segments'][0]['locator']['key']
        self.adapter.list_transform = lambda request, rows: [row for row in rows if row['key'] != missing]
        with self.assertRaisesRegex(EvidenceError, 'index missing'):
            self.manager._catalog()
        self.adapter.list_transform = None
        self.adapter.objects['extra-authority'] = {'key': self.manager.prefix + 'authority/second.json', 'bytes': b'{}'}
        with self.assertRaisesRegex(EvidenceError, 'ambiguous'):
            self.manager._catalog()

    def test_standalone_authority_and_repeated_catalog_calls_use_fresh_listings(self):
        self.assertEqual(self.manager.coordinator, self.manager._generation_authority()['coordinator'])
        self.assertEqual(1, self.counts()['list'])
        self.manager._generation_authority()
        self.assertEqual(2, self.counts()['list'])
        self.adapter.objects['extra-authority'] = {'key': self.manager.prefix + 'authority/second.json', 'bytes': b'{}'}
        with self.assertRaisesRegex(EvidenceError, 'ambiguous'):
            self.manager._generation_authority()
        self.assertEqual(3, self.counts()['list'])
        del self.adapter.objects['extra-authority']
        self.adapter.requests.clear()
        self.manager._catalog()
        self.manager._catalog()
        self.assertEqual(8, self.counts()['list'])
        self.assertEqual(28, self.counts()['metadata'])
        self.assertEqual(8, self.counts()['download_original'])

    def test_publication_keeps_fresh_string_concurrency_fence(self):
        catalog = self.manager._catalog(mutation=True)
        self.adapter.objects['concurrent-root'] = {'key': self.manager.prefix + 'roots/999999999999-new.json', 'bytes': b'{}'}
        self.adapter.requests.clear()
        with self.assertRaisesRegex(EvidenceError, 'catalog changed'):
            self.manager._publish(catalog, {'version': 1})
        self.assertEqual(1, self.counts()['list'])
        self.assertEqual(0, self.counts()['upload'])
        self.assertEqual(0, self.counts()['download_original'])

    def test_publication_original_readbacks_and_hash_verification_are_not_skipped(self):
        catalog = self.manager._catalog(mutation=True)
        self.adapter.requests.clear()
        self.manager._publish(catalog, {'version': 1})
        self.assertEqual(2, self.counts()['upload'])
        self.assertEqual(2, self.counts()['download_original'])
        self.assertTrue(all(request['bypass_cache'] for request in self.adapter.requests
                            if request['operation'] == 'download_original'))
        catalog = self.manager._catalog(mutation=True)
        self.adapter.corrupt_download = True
        with self.assertRaisesRegex(EvidenceError, 'readback corrupt'):
            self.manager._publish(catalog, {'version': 1, 'unique': 'corrupted independent original'})


if __name__ == '__main__':
    unittest.main()
