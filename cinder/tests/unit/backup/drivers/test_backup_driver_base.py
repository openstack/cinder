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

import uuid

import mock
from oslo_serialization import jsonutils

from cinder.backup import driver
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder import test
from cinder.tests.unit.backup import fake_service
from cinder.volume import volume_types

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

    def _create_backup_db_entry(self, backupid, volid, size,
                                userid=str(uuid.uuid4()),
                                projectid=str(uuid.uuid4())):
        backup = {'id': backupid, 'size': size, 'volume_id': volid,
                  'user_id': userid, 'project_id': projectid}
        return db.backup_create(self.ctxt, backup)['id']

    def setUp(self):
        super(BackupBaseDriverTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

        self.volume_id = str(uuid.uuid4())
        self.backup_id = str(uuid.uuid4())

        self._create_backup_db_entry(self.backup_id, self.volume_id, 1)
        self._create_volume_db_entry(self.volume_id, 1)
        self.backup = objects.Backup.get_by_id(self.ctxt, self.backup_id)
        self.driver = fake_service.FakeBackupService(self.ctxt)

    def test_get_metadata(self):
        json_metadata = self.driver.get_metadata(self.volume_id)
        metadata = jsonutils.loads(json_metadata)
        self.assertEqual(2, metadata['version'])

    def test_put_metadata(self):
        metadata = {'version': 1}
        self.driver.put_metadata(self.volume_id, jsonutils.dumps(metadata))

    def test_get_put_metadata(self):
        json_metadata = self.driver.get_metadata(self.volume_id)
        self.driver.put_metadata(self.volume_id, json_metadata)

    def test_export_record(self):
        export_record = self.driver.export_record(self.backup)
        self.assertDictEqual({}, export_record)

    def test_import_record(self):
        export_record = {'key1': 'value1'}
        self.assertIsNone(self.driver.import_record(self.backup,
                                                    export_record))


class BackupMetadataAPITestCase(test.TestCase):

    def _create_volume_db_entry(self, id, size, display_name,
                                display_description):
        vol = {'id': id, 'size': size, 'status': 'available',
               'display_name': display_name,
               'display_description': display_description}
        return db.volume_create(self.ctxt, vol)['id']

    def setUp(self):
        super(BackupMetadataAPITestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.volume_id = str(uuid.uuid4())
        self.backup_id = str(uuid.uuid4())
        self.volume_display_name = 'vol-1'
        self.volume_display_description = 'test vol'
        self._create_volume_db_entry(self.volume_id, 1,
                                     self.volume_display_name,
                                     self.volume_display_description)
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
        self.assertEqual(set(), s1.symmetric_difference(s2))

        self._add_metadata(vol_glance_meta=True)

        meta = self.bak_meta_api.get(self.volume_id)
        s1 = set(jsonutils.loads(meta).keys())
        s2 = ['version', self.bak_meta_api.TYPE_TAG_VOL_BASE_META,
              self.bak_meta_api.TYPE_TAG_VOL_GLANCE_META]
        self.assertEqual(set(), s1.symmetric_difference(s2))

        self._add_metadata(vol_meta=True)

        meta = self.bak_meta_api.get(self.volume_id)
        s1 = set(jsonutils.loads(meta).keys())
        s2 = ['version', self.bak_meta_api.TYPE_TAG_VOL_BASE_META,
              self.bak_meta_api.TYPE_TAG_VOL_GLANCE_META,
              self.bak_meta_api.TYPE_TAG_VOL_META]
        self.assertEqual(set(), s1.symmetric_difference(s2))

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
        container = jsonutils.dumps({'version': 3})
        self.assertRaises(exception.BackupMetadataUnsupportedVersion,
                          self.bak_meta_api.put, self.volume_id, container)

    def test_v1_restore_factory(self):
        fact = self.bak_meta_api._v1_restore_factory()

        keys = [self.bak_meta_api.TYPE_TAG_VOL_BASE_META,
                self.bak_meta_api.TYPE_TAG_VOL_META,
                self.bak_meta_api.TYPE_TAG_VOL_GLANCE_META]

        self.assertEqual(set([]),
                         set(keys).symmetric_difference(set(fact.keys())))

        meta_container = {self.bak_meta_api.TYPE_TAG_VOL_BASE_META:
                          {'display_name': 'my-backed-up-volume',
                           'display_description': 'backed up description'},
                          self.bak_meta_api.TYPE_TAG_VOL_META: {},
                          self.bak_meta_api.TYPE_TAG_VOL_GLANCE_META: {}}

        # Emulate restore to new volume
        volume_id = str(uuid.uuid4())
        vol_name = 'restore_backup_%s' % (self.backup_id)
        self._create_volume_db_entry(volume_id, 1, vol_name, 'fake volume')

        for f in fact:
            func = fact[f][0]
            fields = fact[f][1]
            func(meta_container[f], volume_id, fields)

        vol = db.volume_get(self.ctxt, volume_id)
        self.assertEqual('my-backed-up-volume', vol['display_name'])
        self.assertEqual('backed up description', vol['display_description'])

    def test_v1_restore_factory_no_restore_name(self):
        fact = self.bak_meta_api._v1_restore_factory()

        keys = [self.bak_meta_api.TYPE_TAG_VOL_BASE_META,
                self.bak_meta_api.TYPE_TAG_VOL_META,
                self.bak_meta_api.TYPE_TAG_VOL_GLANCE_META]

        self.assertEqual(set([]),
                         set(keys).symmetric_difference(set(fact.keys())))

        meta_container = {self.bak_meta_api.TYPE_TAG_VOL_BASE_META:
                          {'display_name': 'my-backed-up-volume',
                           'display_description': 'backed up description'},
                          self.bak_meta_api.TYPE_TAG_VOL_META: {},
                          self.bak_meta_api.TYPE_TAG_VOL_GLANCE_META: {}}
        for f in fact:
            func = fact[f][0]
            fields = fact[f][1]
            func(meta_container[f], self.volume_id, fields)

        vol = db.volume_get(self.ctxt, self.volume_id)
        self.assertEqual(self.volume_display_name, vol['display_name'])
        self.assertEqual(self.volume_display_description,
                         vol['display_description'])

    def test_v2_restore_factory(self):
        fact = self.bak_meta_api._v2_restore_factory()

        keys = [self.bak_meta_api.TYPE_TAG_VOL_BASE_META,
                self.bak_meta_api.TYPE_TAG_VOL_META,
                self.bak_meta_api.TYPE_TAG_VOL_GLANCE_META]

        self.assertEqual(set([]),
                         set(keys).symmetric_difference(set(fact.keys())))

        volume_types.create(self.ctxt, 'faketype')
        vol_type = volume_types.get_volume_type_by_name(self.ctxt, 'faketype')

        meta_container = {self.bak_meta_api.TYPE_TAG_VOL_BASE_META:
                          {'encryption_key_id': '123',
                           'volume_type_id': vol_type.get('id'),
                           'display_name': 'vol-2',
                           'display_description': 'description'},
                          self.bak_meta_api.TYPE_TAG_VOL_META: {},
                          self.bak_meta_api.TYPE_TAG_VOL_GLANCE_META: {}}

        for f in fact:
            func = fact[f][0]
            fields = fact[f][1]
            func(meta_container[f], self.volume_id, fields)

        vol = db.volume_get(self.ctxt, self.volume_id)
        self.assertEqual(self.volume_display_name, vol['display_name'])
        self.assertEqual(self.volume_display_description,
                         vol['display_description'])
        self.assertEqual('123', vol['encryption_key_id'])

    def test_restore_vol_glance_meta(self):
        # Fields is an empty list for _restore_vol_glance_meta method.
        fields = []
        container = {}
        self.bak_meta_api._save_vol_glance_meta(container, self.volume_id)
        self.bak_meta_api._restore_vol_glance_meta(container, self.volume_id,
                                                   fields)
        self._add_metadata(vol_glance_meta=True)
        self.bak_meta_api._save_vol_glance_meta(container, self.volume_id)
        self.bak_meta_api._restore_vol_glance_meta(container, self.volume_id,
                                                   fields)

    def test_restore_vol_meta(self):
        # Fields is an empty list for _restore_vol_meta method.
        fields = []
        container = {}
        self.bak_meta_api._save_vol_meta(container, self.volume_id)
        # Extract volume metadata from container.
        metadata = container.get('volume-metadata', {})
        self.bak_meta_api._restore_vol_meta(metadata, self.volume_id,
                                            fields)
        self._add_metadata(vol_meta=True)
        self.bak_meta_api._save_vol_meta(container, self.volume_id)
        # Extract volume metadata from container.
        metadata = container.get('volume-metadata', {})
        self.bak_meta_api._restore_vol_meta(metadata, self.volume_id, fields)

    def test_restore_vol_base_meta(self):
        # Fields is a list with 'encryption_key_id' for
        # _restore_vol_base_meta method.
        fields = ['encryption_key_id']
        container = {}
        self.bak_meta_api._save_vol_base_meta(container, self.volume_id)
        self.bak_meta_api._restore_vol_base_meta(container, self.volume_id,
                                                 fields)

    def _create_encrypted_volume_db_entry(self, id, type_id, encrypted):
        if encrypted:
            key_id = str(uuid.uuid4())
            vol = {'id': id, 'size': 1, 'status': 'available',
                   'volume_type_id': type_id, 'encryption_key_id': key_id}
        else:
            vol = {'id': id, 'size': 1, 'status': 'available',
                   'volume_type_id': type_id, 'encryption_key_id': None}
        return db.volume_create(self.ctxt, vol)['id']

    def test_restore_encrypted_vol_to_different_volume_type(self):
        fields = ['encryption_key_id']
        container = {}

        # Create an encrypted volume
        enc_vol1_id = self._create_encrypted_volume_db_entry(str(uuid.uuid4()),
                                                             'enc_vol_type',
                                                             True)

        # Create a second encrypted volume, of a different volume type
        enc_vol2_id = self._create_encrypted_volume_db_entry(str(uuid.uuid4()),
                                                             'enc_vol_type2',
                                                             True)

        # Backup the first volume and attempt to restore to the second
        self.bak_meta_api._save_vol_base_meta(container, enc_vol1_id)
        self.assertRaises(exception.EncryptedBackupOperationFailed,
                          self.bak_meta_api._restore_vol_base_meta,
                          container[self.bak_meta_api.TYPE_TAG_VOL_BASE_META],
                          enc_vol2_id, fields)

    def test_restore_unencrypted_vol_to_different_volume_type(self):
        fields = ['encryption_key_id']
        container = {}

        # Create an unencrypted volume
        vol1_id = self._create_encrypted_volume_db_entry(str(uuid.uuid4()),
                                                         'vol_type1',
                                                         False)

        # Create a second unencrypted volume, of a different volume type
        vol2_id = self._create_encrypted_volume_db_entry(str(uuid.uuid4()),
                                                         'vol_type2',
                                                         False)

        # Backup the first volume and restore to the second
        self.bak_meta_api._save_vol_base_meta(container, vol1_id)
        self.bak_meta_api._restore_vol_base_meta(
            container[self.bak_meta_api.TYPE_TAG_VOL_BASE_META], vol2_id,
            fields)
        self.assertNotEqual(
            db.volume_get(self.ctxt, vol1_id)['volume_type_id'],
            db.volume_get(self.ctxt, vol2_id)['volume_type_id'])

    def test_restore_encrypted_vol_to_same_volume_type(self):
        fields = ['encryption_key_id']
        container = {}

        # Create an encrypted volume
        enc_vol1_id = self._create_encrypted_volume_db_entry(str(uuid.uuid4()),
                                                             'enc_vol_type',
                                                             True)

        # Create an encrypted volume of the same type
        enc_vol2_id = self._create_encrypted_volume_db_entry(str(uuid.uuid4()),
                                                             'enc_vol_type',
                                                             True)

        # Backup the first volume and restore to the second
        self.bak_meta_api._save_vol_base_meta(container, enc_vol1_id)
        self.bak_meta_api._restore_vol_base_meta(
            container[self.bak_meta_api.TYPE_TAG_VOL_BASE_META], enc_vol2_id,
            fields)

    def test_restore_encrypted_vol_to_none_type_source_type_unavailable(self):
        fields = ['encryption_key_id']
        container = {}
        enc_vol_id = self._create_encrypted_volume_db_entry(str(uuid.uuid4()),
                                                            'enc_vol_type',
                                                            True)
        undef_vol_id = self._create_encrypted_volume_db_entry(
            str(uuid.uuid4()), None, False)
        self.bak_meta_api._save_vol_base_meta(container, enc_vol_id)
        self.assertRaises(exception.EncryptedBackupOperationFailed,
                          self.bak_meta_api._restore_vol_base_meta,
                          container[self.bak_meta_api.TYPE_TAG_VOL_BASE_META],
                          undef_vol_id, fields)

    def test_restore_encrypted_vol_to_none_type_source_type_available(self):
        fields = ['encryption_key_id']
        container = {}
        db.volume_type_create(self.ctxt, {'id': 'enc_vol_type_id',
                                          'name': 'enc_vol_type'})
        enc_vol_id = self._create_encrypted_volume_db_entry(str(uuid.uuid4()),
                                                            'enc_vol_type_id',
                                                            True)
        undef_vol_id = self._create_encrypted_volume_db_entry(
            str(uuid.uuid4()), None, False)
        self.bak_meta_api._save_vol_base_meta(container, enc_vol_id)
        self.bak_meta_api._restore_vol_base_meta(
            container[self.bak_meta_api.TYPE_TAG_VOL_BASE_META], undef_vol_id,
            fields)
        self.assertEqual(
            db.volume_get(self.ctxt, undef_vol_id)['volume_type_id'],
            db.volume_get(self.ctxt, enc_vol_id)['volume_type_id'])

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
            mock_dumps.assert_called_once_with(data)
