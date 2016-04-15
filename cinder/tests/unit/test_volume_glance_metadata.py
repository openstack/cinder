# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack Foundation
# Copyright 2011 University of Southern California
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
Unit Tests for volume types extra specs code
"""

from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder import test
from cinder.tests.unit import fake_constants as fake


class VolumeGlanceMetadataTestCase(test.TestCase):

    def setUp(self):
        super(VolumeGlanceMetadataTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        objects.register_all()

    def test_vol_glance_metadata_bad_vol_id(self):
        ctxt = context.get_admin_context()
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_glance_metadata_create,
                          ctxt, fake.VOLUME_ID, 'key1', 'value1')
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_glance_metadata_get, ctxt, fake.VOLUME_ID)
        db.volume_glance_metadata_delete_by_volume(ctxt, fake.VOLUME2_ID)

    def test_vol_update_glance_metadata(self):
        ctxt = context.get_admin_context()
        db.volume_create(ctxt, {'id': fake.VOLUME_ID})
        db.volume_create(ctxt, {'id': fake.VOLUME2_ID})
        db.volume_glance_metadata_create(ctxt, fake.VOLUME_ID, 'key1',
                                         'value1')
        db.volume_glance_metadata_create(ctxt, fake.VOLUME2_ID, 'key1',
                                         'value1')
        db.volume_glance_metadata_create(ctxt, fake.VOLUME2_ID, 'key2',
                                         'value2')
        db.volume_glance_metadata_create(ctxt, fake.VOLUME2_ID, 'key3', 123)

        expected_metadata_1 = {'volume_id': fake.VOLUME_ID,
                               'key': 'key1',
                               'value': 'value1'}

        metadata = db.volume_glance_metadata_get(ctxt, fake.VOLUME_ID)
        self.assertEqual(1, len(metadata))
        for key, value in expected_metadata_1.items():
            self.assertEqual(value, metadata[0][key])

        expected_metadata_2 = ({'volume_id': fake.VOLUME2_ID,
                                'key': 'key1',
                                'value': 'value1'},
                               {'volume_id': fake.VOLUME2_ID,
                                'key': 'key2',
                                'value': 'value2'},
                               {'volume_id': fake.VOLUME2_ID,
                                'key': 'key3',
                                'value': '123'})

        metadata = db.volume_glance_metadata_get(ctxt, fake.VOLUME2_ID)
        self.assertEqual(3, len(metadata))
        for expected, meta in zip(expected_metadata_2, metadata):
            for key, value in expected.items():
                self.assertEqual(value, meta[key])

        self.assertRaises(exception.GlanceMetadataExists,
                          db.volume_glance_metadata_create,
                          ctxt, fake.VOLUME_ID, 'key1', 'value1a')

        metadata = db.volume_glance_metadata_get(ctxt, fake.VOLUME_ID)
        self.assertEqual(1, len(metadata))
        for key, value in expected_metadata_1.items():
            self.assertEqual(value, metadata[0][key])

    def test_vols_get_glance_metadata(self):
        ctxt = context.get_admin_context()
        db.volume_create(ctxt, {'id': fake.VOLUME_ID})
        db.volume_create(ctxt, {'id': fake.VOLUME2_ID})
        db.volume_create(ctxt, {'id': '3'})
        db.volume_glance_metadata_create(ctxt, fake.VOLUME_ID, 'key1',
                                         'value1')
        db.volume_glance_metadata_create(ctxt, fake.VOLUME2_ID, 'key2',
                                         'value2')
        db.volume_glance_metadata_create(ctxt, fake.VOLUME2_ID, 'key22',
                                         'value22')

        metadata = db.volume_glance_metadata_get_all(ctxt)
        self.assertEqual(3, len(metadata))
        self._assert_metadata_equals(fake.VOLUME_ID, 'key1', 'value1',
                                     metadata[0])
        self._assert_metadata_equals(fake.VOLUME2_ID, 'key2', 'value2',
                                     metadata[1])
        self._assert_metadata_equals(fake.VOLUME2_ID, 'key22', 'value22',
                                     metadata[2])

    def _assert_metadata_equals(self, volume_id, key, value, observed):
        self.assertEqual(volume_id, observed.volume_id)
        self.assertEqual(key, observed.key)
        self.assertEqual(value, observed.value)

    def test_vol_delete_glance_metadata(self):
        ctxt = context.get_admin_context()
        db.volume_create(ctxt, {'id': fake.VOLUME_ID})
        db.volume_glance_metadata_delete_by_volume(ctxt, fake.VOLUME_ID)
        db.volume_glance_metadata_create(ctxt, fake.VOLUME_ID, 'key1',
                                         'value1')
        db.volume_glance_metadata_delete_by_volume(ctxt, fake.VOLUME_ID)
        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_glance_metadata_get, ctxt, fake.VOLUME_ID)

    def test_vol_glance_metadata_copy_to_snapshot(self):
        ctxt = context.get_admin_context()
        db.volume_create(ctxt, {'id': fake.VOLUME_ID})
        snap = objects.Snapshot(ctxt, volume_id=fake.VOLUME_ID)
        snap.create()
        db.volume_glance_metadata_create(ctxt, fake.VOLUME_ID, 'key1',
                                         'value1')
        db.volume_glance_metadata_copy_to_snapshot(ctxt, snap.id,
                                                   fake.VOLUME_ID)

        expected_meta = {'snapshot_id': snap.id,
                         'key': 'key1',
                         'value': 'value1'}

        for meta in db.volume_snapshot_glance_metadata_get(ctxt, snap.id):
            for (key, value) in expected_meta.items():
                self.assertEqual(value, meta[key])
        snap.destroy()

    def test_vol_glance_metadata_copy_from_volume_to_volume(self):
        ctxt = context.get_admin_context()
        db.volume_create(ctxt, {'id': fake.VOLUME_ID})
        db.volume_create(ctxt, {'id': fake.VOLUME2_ID,
                                'source_volid': fake.VOLUME_ID})
        db.volume_glance_metadata_create(ctxt, fake.VOLUME_ID, 'key1',
                                         'value1')
        db.volume_glance_metadata_copy_from_volume_to_volume(ctxt,
                                                             fake.VOLUME_ID,
                                                             fake.VOLUME2_ID)

        expected_meta = {'key': 'key1',
                         'value': 'value1'}

        for meta in db.volume_glance_metadata_get(ctxt, fake.VOLUME2_ID):
            for (key, value) in expected_meta.items():
                self.assertEqual(value, meta[key])

    def test_volume_glance_metadata_copy_to_volume(self):
        vol1 = db.volume_create(self.ctxt, {})
        vol2 = db.volume_create(self.ctxt, {})
        db.volume_glance_metadata_create(self.ctxt, vol1['id'], 'm1', 'v1')
        snapshot = objects.Snapshot(self.ctxt, volume_id=vol1['id'])
        snapshot.create()
        db.volume_glance_metadata_copy_to_snapshot(self.ctxt, snapshot.id,
                                                   vol1['id'])
        db.volume_glance_metadata_copy_to_volume(self.ctxt, vol2['id'],
                                                 snapshot.id)
        metadata = db.volume_glance_metadata_get(self.ctxt, vol2['id'])
        metadata = {m['key']: m['value'] for m in metadata}
        self.assertEqual({'m1': 'v1'}, metadata)

    def test_volume_snapshot_glance_metadata_get_nonexistent(self):
        vol = db.volume_create(self.ctxt, {})
        snapshot = objects.Snapshot(self.ctxt, volume_id=vol['id'])
        snapshot.create()
        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_snapshot_glance_metadata_get,
                          self.ctxt, snapshot.id)
        snapshot.destroy()
