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
import six

from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import objects as test_objects
from cinder.tests.unit import utils


fake_backup = {
    'id': fake.backup_id,
    'volume_id': fake.volume_id,
    'status': fields.BackupStatus.CREATING,
    'size': 1,
    'display_name': 'fake_name',
    'display_description': 'fake_description',
    'user_id': fake.user_id,
    'project_id': fake.project_id,
    'temp_volume_id': None,
    'temp_snapshot_id': None,
    'snapshot_id': None,
    'data_timestamp': None,
    'restore_volume_id': None,
}


class TestBackup(test_objects.BaseObjectsTestCase):

    @mock.patch('cinder.db.get_by_id', return_value=fake_backup)
    def test_get_by_id(self, backup_get):
        backup = objects.Backup.get_by_id(self.context, fake.user_id)
        self._compare(self, fake_backup, backup)
        backup_get.assert_called_once_with(self.context, models.Backup,
                                           fake.user_id)

    @mock.patch('cinder.db.sqlalchemy.api.model_query')
    def test_get_by_id_no_existing_id(self, model_query):
        query = mock.Mock()
        filter_by = mock.Mock()
        filter_by.first.return_value = None
        query.filter_by.return_value = filter_by
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

    @mock.patch('cinder.db.backup_destroy')
    def test_destroy(self, backup_destroy):
        backup = objects.Backup(context=self.context, id=fake.backup_id)
        backup.destroy()
        self.assertTrue(backup_destroy.called)
        admin_context = backup_destroy.call_args[0][0]
        self.assertTrue(admin_context.is_admin)

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

    def test_import_record(self):
        utils.replace_obj_loader(self, objects.Backup)
        backup = objects.Backup(context=self.context, id=fake.backup_id,
                                parent_id=None,
                                num_dependent_backups=0)
        export_string = backup.encode_record()
        imported_backup = objects.Backup.decode_record(export_string)

        # Make sure we don't lose data when converting from string
        self.assertDictEqual(self._expected_backup(backup), imported_backup)

    def test_import_record_additional_info(self):
        utils.replace_obj_loader(self, objects.Backup)
        backup = objects.Backup(context=self.context, id=fake.backup_id,
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
                  for name, field in backup.fields.items()}
        return record

    def test_import_record_additional_info_cant_overwrite(self):
        utils.replace_obj_loader(self, objects.Backup)
        backup = objects.Backup(context=self.context, id=fake.backup_id,
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
        backup = objects.Backup.get_by_id(self.context, fake.backup_id)
        self._compare(self, db_backup1, backup)

        # display_name was updated, so a backup refresh should have a new value
        # for that field
        backup.refresh()
        self._compare(self, db_backup2, backup)
        if six.PY3:
            call_bool = mock.call.__bool__()
        else:
            call_bool = mock.call.__nonzero__()
        backup_get.assert_has_calls([mock.call(self.context, fake.backup_id),
                                     call_bool,
                                     mock.call(self.context, fake.backup_id)])


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
    def test_get_all_for_volume(self, get_all_by_host):
        fake_volume_obj = fake_volume.fake_volume_obj(self.context)

        backups = objects.BackupList.get_all_by_host(self.context,
                                                     fake_volume_obj.id)
        self.assertEqual(1, len(backups))
        TestBackup._compare(self, fake_backup, backups[0])

    @mock.patch('cinder.db.backup_get_all', return_value=[fake_backup])
    def test_get_all_tenants(self, backup_get_all):
        search_opts = {'all_tenants': 1}
        backups = objects.BackupList.get_all(self.context, search_opts)
        self.assertEqual(1, len(backups))
        TestBackup._compare(self, fake_backup, backups[0])
