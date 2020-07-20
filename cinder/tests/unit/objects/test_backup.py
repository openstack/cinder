#    Copyright 2015 Intel Corporation
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

import mock
from oslo_utils import timeutils
import pytz
import six

from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import objects as test_objects
from cinder.tests.unit import utils


fake_backup = {
    'id': fake.BACKUP_ID,
    'volume_id': fake.VOLUME_ID,
    'status': fields.BackupStatus.CREATING,
    'size': 1,
    'display_name': 'fake_name',
    'display_description': 'fake_description',
    'user_id': fake.USER_ID,
    'project_id': fake.PROJECT_ID,
    'temp_volume_id': None,
    'temp_snapshot_id': None,
    'snapshot_id': None,
    'data_timestamp': None,
    'restore_volume_id': None,
    'backup_metadata': {},
}

vol_props = {'status': 'available', 'size': 1}
fake_vol = fake_volume.fake_db_volume(**vol_props)
snap_props = {'status': fields.BackupStatus.AVAILABLE,
              'volume_id': fake_vol['id'],
              'expected_attrs': ['metadata']}
fake_snap = fake_snapshot.fake_db_snapshot(**snap_props)


class TestBackup(test_objects.BaseObjectsTestCase):

    @mock.patch('cinder.db.get_by_id', return_value=fake_backup)
    def test_get_by_id(self, backup_get):
        backup = objects.Backup.get_by_id(self.context, fake.USER_ID)
        self._compare(self, fake_backup, backup)
        backup_get.assert_called_once_with(self.context, models.Backup,
                                           fake.USER_ID)

    @mock.patch('cinder.db.sqlalchemy.api.model_query')
    def test_get_by_id_no_existing_id(self, model_query):
        query = mock.Mock()
        filter_by = mock.Mock()
        query_options = mock.Mock()
        filter_by.first.return_value = None
        query_options.filter_by.return_value = filter_by
        query.options.return_value = query_options
        model_query.return_value = query
        self.assertRaises(exception.BackupNotFound, objects.Backup.get_by_id,
                          self.context, 123)

    @mock.patch('cinder.db.backup_create', return_value=fake_backup)
    def test_create(self, backup_create):
        backup = objects.Backup(context=self.context)
        backup.create()
        self.assertEqual(fake_backup['id'], backup.id)
        self.assertEqual(fake_backup['volume_id'], backup.volume_id)

    @mock.patch('cinder.db.backup_update')
    def test_save(self, backup_update):
        backup = objects.Backup._from_db_object(
            self.context, objects.Backup(), fake_backup)
        backup.display_name = 'foobar'
        backup.save()
        backup_update.assert_called_once_with(self.context, backup.id,
                                              {'display_name': 'foobar'})

    @mock.patch('cinder.db.backup_metadata_update',
                return_value={'key1': 'value1'})
    @mock.patch('cinder.db.backup_update')
    def test_save_with_metadata(self, backup_update, metadata_update):
        backup = objects.Backup._from_db_object(
            self.context, objects.Backup(), fake_backup)

        backup.metadata = {'key1': 'value1'}
        self.assertEqual({'metadata': {'key1': 'value1'}},
                         backup.obj_get_changes())
        backup.save()
        metadata_update.assert_called_once_with(self.context, backup.id,
                                                {'key1': 'value1'}, True)

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=timeutils.utcnow())
    @mock.patch('cinder.db.sqlalchemy.api.backup_destroy')
    def test_destroy(self, backup_destroy, utcnow_mock):
        backup_destroy.return_value = {
            'status': fields.BackupStatus.DELETED,
            'deleted': True,
            'deleted_at': utcnow_mock.return_value}
        backup = objects.Backup(context=self.context, id=fake.BACKUP_ID)
        backup.destroy()
        self.assertTrue(backup_destroy.called)
        admin_context = backup_destroy.call_args[0][0]
        self.assertTrue(admin_context.is_admin)
        self.assertTrue(backup.deleted)
        self.assertEqual(fields.BackupStatus.DELETED, backup.status)
        self.assertEqual(utcnow_mock.return_value.replace(tzinfo=pytz.UTC),
                         backup.deleted_at)

    def test_obj_field_temp_volume_snapshot_id(self):
        backup = objects.Backup(context=self.context,
                                temp_volume_id='2',
                                temp_snapshot_id='3')
        self.assertEqual('2', backup.temp_volume_id)
        self.assertEqual('3', backup.temp_snapshot_id)

    def test_obj_field_snapshot_id(self):
        backup = objects.Backup(context=self.context,
                                snapshot_id='2')
        self.assertEqual('2', backup.snapshot_id)

    def test_obj_field_restore_volume_id(self):
        backup = objects.Backup(context=self.context,
                                restore_volume_id='2')
        self.assertEqual('2', backup.restore_volume_id)

    def test_obj_field_metadata(self):
        backup = objects.Backup(context=self.context,
                                metadata={'test_key': 'test_value'})
        self.assertEqual({'test_key': 'test_value'}, backup.metadata)

    @mock.patch('cinder.objects.backup.Backup.get_by_id',
                return_value=None)
    def test_obj_field_parent(self, mock_lzy_ld):
        backup = objects.Backup(context=self.context,
                                parent_id=None)
        self.assertIsNone(backup.parent)

        # Bug #1862635: should trigger a lazy load
        backup = objects.Backup(context=self.context,
                                parent_id=fake.UUID5)
        # need noqa here because of pyflakes issue #202
        _ = backup.parent  # noqa
        mock_lzy_ld.assert_called_once()

    def test_import_record(self):
        utils.replace_obj_loader(self, objects.Backup)
        backup = objects.Backup(context=self.context, id=fake.BACKUP_ID,
                                parent_id=None,
                                num_dependent_backups=0)
        export_string = backup.encode_record()
        imported_backup = objects.Backup.decode_record(export_string)

        # Make sure we don't lose data when converting from string
        self.assertDictEqual(self._expected_backup(backup), imported_backup)

    @mock.patch('cinder.db.get_by_id', return_value=fake_backup)
    def test_import_record_w_parent(self, backup_get):
        full_backup = objects.Backup.get_by_id(self.context, fake.USER_ID)
        self._compare(self, fake_backup, full_backup)

        utils.replace_obj_loader(self, objects.Backup)
        incr_backup = objects.Backup(context=self.context,
                                     id=fake.BACKUP2_ID,
                                     parent=full_backup,
                                     parent_id=full_backup['id'],
                                     num_dependent_backups=0)
        export_string = incr_backup.encode_record()
        imported_backup = objects.Backup.decode_record(export_string)

        # Make sure we don't lose data when converting from string
        self.assertDictEqual(self._expected_backup(incr_backup),
                             imported_backup)

    def test_import_record_additional_info(self):
        utils.replace_obj_loader(self, objects.Backup)
        backup = objects.Backup(context=self.context, id=fake.BACKUP_ID,
                                parent_id=None,
                                num_dependent_backups=0)
        extra_info = {'driver': {'key1': 'value1', 'key2': 'value2'}}
        extra_info_copy = extra_info.copy()
        export_string = backup.encode_record(extra_info=extra_info)
        imported_backup = objects.Backup.decode_record(export_string)

        # Dictionary passed should not be modified
        self.assertDictEqual(extra_info_copy, extra_info)

        # Make sure we don't lose data when converting from string and that
        # extra info is still there
        expected = self._expected_backup(backup)
        expected['extra_info'] = extra_info
        self.assertDictEqual(expected, imported_backup)

    def _expected_backup(self, backup):
        record = {name: field.to_primitive(backup, name, getattr(backup, name))
                  for name, field in backup.fields.items() if name != 'parent'}
        return record

    def test_import_record_additional_info_cant_overwrite(self):
        utils.replace_obj_loader(self, objects.Backup)
        backup = objects.Backup(context=self.context, id=fake.BACKUP_ID,
                                parent_id=None,
                                num_dependent_backups=0)
        export_string = backup.encode_record(id='fake_id')
        imported_backup = objects.Backup.decode_record(export_string)

        # Make sure the extra_info can't overwrite basic data
        self.assertDictEqual(self._expected_backup(backup), imported_backup)

    def test_import_record_decoding_error(self):
        export_string = '123456'
        self.assertRaises(exception.InvalidInput,
                          objects.Backup.decode_record,
                          export_string)

    def test_import_record_parsing_error(self):
        export_string = ''
        self.assertRaises(exception.InvalidInput,
                          objects.Backup.decode_record,
                          export_string)

    @mock.patch('cinder.db.sqlalchemy.api.backup_get')
    def test_refresh(self, backup_get):
        db_backup1 = fake_backup.copy()
        db_backup2 = db_backup1.copy()
        db_backup2['display_name'] = 'foobar'

        # On the second backup_get, return the backup with an updated
        # display_name
        backup_get.side_effect = [db_backup1, db_backup2]
        backup = objects.Backup.get_by_id(self.context, fake.BACKUP_ID)
        self._compare(self, db_backup1, backup)

        # display_name was updated, so a backup refresh should have a new value
        # for that field
        backup.refresh()
        self._compare(self, db_backup2, backup)
        if six.PY3:
            call_bool = mock.call.__bool__()
        else:
            call_bool = mock.call.__nonzero__()
        backup_get.assert_has_calls([mock.call(self.context, fake.BACKUP_ID),
                                     call_bool,
                                     mock.call(self.context, fake.BACKUP_ID)])


class TestBackupList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.db.backup_get_all', return_value=[fake_backup])
    def test_get_all(self, backup_get_all):
        backups = objects.BackupList.get_all(self.context)
        self.assertEqual(1, len(backups))
        TestBackup._compare(self, fake_backup, backups[0])

    @mock.patch('cinder.db.backup_get_all_by_project',
                return_value=[fake_backup])
    def test_get_all_by_project(self, get_all_by_project):
        backups = objects.BackupList.get_all_by_project(
            self.context, self.project_id)
        self.assertEqual(1, len(backups))
        TestBackup._compare(self, fake_backup, backups[0])

    @mock.patch('cinder.db.backup_get_all_by_host',
                return_value=[fake_backup])
    def test_get_all_by_host(self, get_all_by_host):
        backups = objects.BackupList.get_all_by_host(self.context, "fake_host")
        self.assertEqual(1, len(backups))
        TestBackup._compare(self, fake_backup, backups[0])

    @mock.patch('cinder.db.backup_get_all', return_value=[fake_backup])
    def test_get_all_tenants(self, backup_get_all):
        search_opts = {'all_tenants': 1}
        backups = objects.BackupList.get_all(self.context, search_opts)
        self.assertEqual(1, len(backups))
        TestBackup._compare(self, fake_backup, backups[0])

    @mock.patch('cinder.db.backup_get_all_by_volume',
                return_value=[fake_backup])
    def test_get_all_by_volume(self, get_all_by_volume):
        backups = objects.BackupList.get_all_by_volume(
            self.context, fake.VOLUME_ID, 'fake_proj')
        self.assertEqual(1, len(backups))
        get_all_by_volume.assert_called_once_with(self.context,
                                                  fake.VOLUME_ID,
                                                  'fake_proj',
                                                  None)
        TestBackup._compare(self, fake_backup, backups[0])


class BackupDeviceInfoTestCase(test_objects.BaseObjectsTestCase):
    def setUp(self):
        super(BackupDeviceInfoTestCase, self).setUp()
        self.vol_obj = fake_volume.fake_volume_obj(self.context, **vol_props)
        self.snap_obj = fake_snapshot.fake_snapshot_obj(self.context,
                                                        **snap_props)
        self.backup_device_dict = {'secure_enabled': False,
                                   'is_snapshot': False, }

    @mock.patch('cinder.db.volume_get', return_value=fake_vol)
    def test_from_primitive_with_volume(self, mock_fake_vol):
        vol_obj = self.vol_obj
        self.backup_device_dict['backup_device'] = vol_obj
        backup_device_info = objects.BackupDeviceInfo.from_primitive(
            self.backup_device_dict, self.context)
        self.assertFalse(backup_device_info.is_snapshot)
        self.assertEqual(self.backup_device_dict['secure_enabled'],
                         backup_device_info.secure_enabled)
        self.assertEqual(vol_obj, backup_device_info.volume)

        self.backup_device_dict['backup_device'] = fake_vol
        backup_device_info = objects.BackupDeviceInfo.from_primitive(
            self.backup_device_dict, self.context)
        vol_obj_from_db = objects.Volume._from_db_object(self.context,
                                                         objects.Volume(),
                                                         fake_vol)
        self.assertEqual(vol_obj_from_db, backup_device_info.volume)

    @mock.patch('cinder.db.snapshot_get', return_value=fake_snap)
    def test_from_primitive_with_snapshot(self, mock_fake_snap):
        snap_obj = self.snap_obj
        self.backup_device_dict['is_snapshot'] = True
        self.backup_device_dict['backup_device'] = snap_obj
        backup_device_info = objects.BackupDeviceInfo.from_primitive(
            self.backup_device_dict, self.context, expected_attrs=['metadata'])
        self.assertTrue(backup_device_info.is_snapshot)
        self.assertEqual(self.backup_device_dict['secure_enabled'],
                         backup_device_info.secure_enabled)
        self.assertEqual(snap_obj, backup_device_info.snapshot)

        self.backup_device_dict['backup_device'] = fake_snap
        backup_device_info = objects.BackupDeviceInfo.from_primitive(
            self.backup_device_dict, self.context, expected_attrs=['metadata'])
        self.assertEqual(snap_obj, backup_device_info.snapshot)

    @mock.patch('cinder.db.volume_get', return_value=fake_vol)
    def test_to_primitive_with_volume(self, mock_fake_vol):
        vol_obj = self.vol_obj
        self.backup_device_dict['backup_device'] = fake_vol
        backup_device_info = objects.BackupDeviceInfo()
        backup_device_info.volume = vol_obj
        backup_device_info.secure_enabled = (
            self.backup_device_dict['secure_enabled'])

        backup_device_ret_dict = backup_device_info.to_primitive(self.context)
        self.assertEqual(self.backup_device_dict['secure_enabled'],
                         backup_device_ret_dict['secure_enabled'])
        self.assertFalse(backup_device_ret_dict['is_snapshot'])
        self.assertEqual(self.backup_device_dict['backup_device'],
                         backup_device_ret_dict['backup_device'])

    @mock.patch('cinder.db.snapshot_get', return_value=fake_snap)
    def test_to_primitive_with_snapshot(self, mock_fake_snap):
        snap_obj = self.snap_obj
        backup_device_info = objects.BackupDeviceInfo()
        backup_device_info.snapshot = snap_obj
        backup_device_info.secure_enabled = (
            self.backup_device_dict['secure_enabled'])

        backup_device_ret_dict = backup_device_info.to_primitive(self.context)
        self.assertEqual(self.backup_device_dict['secure_enabled'],
                         backup_device_ret_dict['secure_enabled'])
        self.assertTrue(backup_device_ret_dict['is_snapshot'])
        # NOTE(sborkows): since volume in sqlalchemy snapshot is a sqlalchemy
        # object too, to compare snapshots we need to convert their volumes to
        # dicts.
        snap_actual_dict = fake_snap
        snap_ref_dict = backup_device_ret_dict['backup_device']
        snap_actual_dict['volume'] = self.vol_obj.obj_to_primitive()
        snap_ref_dict['volume'] = snap_ref_dict['volume']
        self.assertEqual(snap_actual_dict, snap_ref_dict)

    def test_is_snapshot_both_volume_and_snapshot_raises_error(self):
        snap = self.snap_obj
        vol = self.vol_obj
        backup_device_info = objects.BackupDeviceInfo()
        backup_device_info.snapshot = snap
        backup_device_info.volume = vol
        backup_device_info.secure_enabled = (
            self.backup_device_dict['secure_enabled'])
        self.assertRaises(exception.ProgrammingError, getattr,
                          backup_device_info, 'is_snapshot')

    def test_is_snapshot_neither_volume_nor_snapshot_raises_error(self):
        backup_device_info = objects.BackupDeviceInfo()
        backup_device_info.secure_enabled = (
            self.backup_device_dict['secure_enabled'])
        self.assertRaises(exception.ProgrammingError, getattr,
                          backup_device_info, 'is_snapshot')

    def test_device_obj_with_volume(self):
        vol = self.vol_obj
        backup_device_info = objects.BackupDeviceInfo()
        backup_device_info.volume = vol
        backup_device_info.secure_enabled = (
            self.backup_device_dict['secure_enabled'])
        backup_device_obj = backup_device_info.device_obj
        self.assertIsInstance(backup_device_obj, objects.Volume)
        self.assertEqual(vol, backup_device_obj)

    def test_device_obj_with_snapshot(self):
        snap = self.snap_obj
        backup_device_info = objects.BackupDeviceInfo()
        backup_device_info.snapshot = snap
        backup_device_info.secure_enabled = (
            self.backup_device_dict['secure_enabled'])
        backup_device_obj = backup_device_info.device_obj
        self.assertIsInstance(backup_device_obj, objects.Snapshot)
        self.assertEqual(snap, backup_device_obj)
