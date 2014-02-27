# Copyright 2013 Canonical Ltd.
# All Rights Reserved.
#
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
""" Tests for the backup service base driver. """

import mock
import uuid

from cinder.backup import driver
from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import jsonutils
from cinder import test


_backup_db_fields = ['id', 'user_id', 'project_id',
                     'volume_id', 'host', 'availability_zone',
                     'display_name', 'display_description',
                     'container', 'status', 'fail_reason',
                     'service_metadata', 'service', 'size',
                     'object_count']


class BackupBaseDriverTestCase(test.TestCase):

    def _create_volume_db_entry(self, id, size):
        vol = {'id': id, 'size': size, 'status': 'available'}
        return db.volume_create(self.ctxt, vol)['id']

    def _create_backup_db_entry(self, backupid, volid, size):
        backup = {'id': backupid, 'size': size, 'volume_id': volid}
        return db.backup_create(self.ctxt, backup)['id']

    def setUp(self):
        super(BackupBaseDriverTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

        self.volume_id = str(uuid.uuid4())
        self.backup_id = str(uuid.uuid4())

        self._create_backup_db_entry(self.backup_id, self.volume_id, 1)
        self._create_volume_db_entry(self.volume_id, 1)
        self.backup = db.backup_get(self.ctxt, self.backup_id)
        self.driver = driver.BackupDriver(self.ctxt)

    def test_backup(self):
        self.assertRaises(NotImplementedError,
                          self.driver.backup, self.backup, self.volume_id)

    def test_restore(self):
        self.assertRaises(NotImplementedError,
                          self.driver.restore, self.backup, self.volume_id,
                          None)

    def test_delete(self):
        self.assertRaises(NotImplementedError,
                          self.driver.delete, self.backup)

    def test_get_metadata(self):
        json_metadata = self.driver.get_metadata(self.volume_id)
        metadata = jsonutils.loads(json_metadata)
        self.assertEqual(metadata['version'], 1)

    def test_put_metadata(self):
        metadata = {'version': 1}
        self.driver.put_metadata(self.volume_id, jsonutils.dumps(metadata))

    def test_get_put_metadata(self):
        json_metadata = self.driver.get_metadata(self.volume_id)
        self.driver.put_metadata(self.volume_id, json_metadata)

    def test_export_record(self):
        export_string = self.driver.export_record(self.backup)
        export_dict = jsonutils.loads(export_string.decode("base64"))
        # Make sure we don't lose data when converting to string
        for key in _backup_db_fields:
            self.assertTrue(key in export_dict)
            self.assertEqual(self.backup[key], export_dict[key])

    def test_import_record(self):
        export_string = self.driver.export_record(self.backup)
        imported_backup = self.driver.import_record(export_string)
        # Make sure we don't lose data when converting from string
        for key in _backup_db_fields:
            self.assertTrue(key in imported_backup)
            self.assertEqual(imported_backup[key], self.backup[key])

    def test_verify(self):
        self.assertRaises(NotImplementedError,
                          self.driver.verify, self.backup)

    def tearDown(self):
        super(BackupBaseDriverTestCase, self).tearDown()


class BackupMetadataAPITestCase(test.TestCase):

    def _create_volume_db_entry(self, id, size):
        vol = {'id': id, 'size': size, 'status': 'available'}
        return db.volume_create(self.ctxt, vol)['id']

    def setUp(self):
        super(BackupMetadataAPITestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.volume_id = str(uuid.uuid4())
        self._create_volume_db_entry(self.volume_id, 1)
        self.bak_meta_api = driver.BackupMetadataAPI(self.ctxt)

    def _add_metadata(self, vol_meta=False, vol_glance_meta=False):
        if vol_meta:
            # Add some VolumeMetadata
            db.volume_metadata_update(self.ctxt, self.volume_id,
                                      {'fee': 'fi'}, False)
            db.volume_metadata_update(self.ctxt, self.volume_id,
                                      {'fo': 'fum'}, False)

        if vol_glance_meta:
            # Add some GlanceMetadata
            db.volume_glance_metadata_create(self.ctxt, self.volume_id,
                                             'disk_format', 'bare')
            db.volume_glance_metadata_create(self.ctxt, self.volume_id,
                                             'container_type', 'ovf')

    def test_get(self):
        # Volume won't have anything other than base by default
        meta = self.bak_meta_api.get(self.volume_id)
        s1 = set(jsonutils.loads(meta).keys())
        s2 = ['version', self.bak_meta_api.TYPE_TAG_VOL_BASE_META]
        self.assertEqual(s1.symmetric_difference(s2), set())

        self._add_metadata(vol_glance_meta=True)

        meta = self.bak_meta_api.get(self.volume_id)
        s1 = set(jsonutils.loads(meta).keys())
        s2 = ['version', self.bak_meta_api.TYPE_TAG_VOL_BASE_META,
              self.bak_meta_api.TYPE_TAG_VOL_GLANCE_META]
        self.assertEqual(s1.symmetric_difference(s2), set())

        self._add_metadata(vol_meta=True)

        meta = self.bak_meta_api.get(self.volume_id)
        s1 = set(jsonutils.loads(meta).keys())
        s2 = ['version', self.bak_meta_api.TYPE_TAG_VOL_BASE_META,
              self.bak_meta_api.TYPE_TAG_VOL_GLANCE_META,
              self.bak_meta_api.TYPE_TAG_VOL_META]
        self.assertEqual(s1.symmetric_difference(s2), set())

    def test_put(self):
        meta = self.bak_meta_api.get(self.volume_id)
        self.bak_meta_api.put(self.volume_id, meta)

        self._add_metadata(vol_glance_meta=True)
        meta = self.bak_meta_api.get(self.volume_id)
        self.bak_meta_api.put(self.volume_id, meta)

        self._add_metadata(vol_meta=True)
        meta = self.bak_meta_api.get(self.volume_id)
        self.bak_meta_api.put(self.volume_id, meta)

    def test_put_invalid_version(self):
        container = jsonutils.dumps({'version': 2})
        self.assertRaises(exception.BackupMetadataUnsupportedVersion,
                          self.bak_meta_api.put, self.volume_id, container)

    def test_v1_restore_factory(self):
        fact = self.bak_meta_api._v1_restore_factory()

        keys = [self.bak_meta_api.TYPE_TAG_VOL_BASE_META,
                self.bak_meta_api.TYPE_TAG_VOL_META,
                self.bak_meta_api.TYPE_TAG_VOL_GLANCE_META]

        self.assertEqual(set(keys).symmetric_difference(set(fact.keys())),
                         set([]))

        for f in fact:
            func = fact[f][0]
            fields = fact[f][1]
            func({}, self.volume_id, fields)

    def test_restore_vol_glance_meta(self):
        fields = {}
        container = {}
        self.bak_meta_api._save_vol_glance_meta(container, self.volume_id)
        self.bak_meta_api._restore_vol_glance_meta(container, self.volume_id,
                                                   fields)
        self._add_metadata(vol_glance_meta=True)
        self.bak_meta_api._save_vol_glance_meta(container, self.volume_id)
        self.bak_meta_api._restore_vol_glance_meta(container, self.volume_id,
                                                   fields)

    def test_restore_vol_meta(self):
        fields = {}
        container = {}
        self.bak_meta_api._save_vol_meta(container, self.volume_id)
        self.bak_meta_api._restore_vol_meta(container, self.volume_id, fields)
        self._add_metadata(vol_meta=True)
        self.bak_meta_api._save_vol_meta(container, self.volume_id)
        self.bak_meta_api._restore_vol_meta(container, self.volume_id, fields)

    def test_restore_vol_base_meta(self):
        fields = {}
        container = {}
        self.bak_meta_api._save_vol_base_meta(container, self.volume_id)
        self.bak_meta_api._restore_vol_base_meta(container, self.volume_id,
                                                 fields)

    def test_filter(self):
        metadata = {'a': 1, 'b': 2, 'c': 3}
        self.assertEqual(metadata, self.bak_meta_api._filter(metadata, []))
        self.assertEqual({'b': 2}, self.bak_meta_api._filter(metadata, ['b']))
        self.assertEqual({}, self.bak_meta_api._filter(metadata, ['d']))
        self.assertEqual({'a': 1, 'b': 2},
                         self.bak_meta_api._filter(metadata, ['a', 'b']))

    def test_save_vol_glance_meta(self):
        container = {}
        self.bak_meta_api._save_vol_glance_meta(container, self.volume_id)

    def test_save_vol_meta(self):
        container = {}
        self.bak_meta_api._save_vol_meta(container, self.volume_id)

    def test_save_vol_base_meta(self):
        container = {}
        self.bak_meta_api._save_vol_base_meta(container, self.volume_id)

    def test_is_serializable(self):
        data = {'foo': 'bar'}
        if self.bak_meta_api._is_serializable(data):
            jsonutils.dumps(data)

    def test_is_not_serializable(self):
        data = {'foo': 'bar'}
        with mock.patch.object(jsonutils, 'dumps') as mock_dumps:
            mock_dumps.side_effect = TypeError
            self.assertFalse(self.bak_meta_api._is_serializable(data))
            mock_dumps.assert_called_once()

    def tearDown(self):
        super(BackupMetadataAPITestCase, self).tearDown()
