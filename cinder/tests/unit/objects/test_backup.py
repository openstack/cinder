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

from cinder import context
from cinder import exception
from cinder import objects
from cinder.tests.unit import fake_volume
from cinder.tests.unit import objects as test_objects
from cinder.tests.unit import utils


fake_backup = {
    'id': '1',
    'volume_id': 'fake_id',
    'status': "creating",
    'size': 1,
    'display_name': 'fake_name',
    'display_description': 'fake_description',
    'user_id': 'fake_user',
    'project_id': 'fake_project',
    'temp_volume_id': None,
    'temp_snapshot_id': None,
}


class TestBackup(test_objects.BaseObjectsTestCase):
    def setUp(self):
        super(TestBackup, self).setUp()
        # NOTE (e0ne): base tests contains original RequestContext from
        # oslo_context. We change it to our RequestContext implementation
        # to have 'elevated' method
        self.context = context.RequestContext(self.user_id, self.project_id,
                                              is_admin=False)

    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], obj[field])

    @mock.patch('cinder.db.backup_get', return_value=fake_backup)
    def test_get_by_id(self, backup_get):
        backup = objects.Backup.get_by_id(self.context, 1)
        self._compare(self, fake_backup, backup)

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
        backup = objects.Backup(context=self.context, id=1)
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

    def test_import_record(self):
        utils.replace_obj_loader(self, objects.Backup)
        backup = objects.Backup(context=self.context, id=1, parent_id=None,
                                num_dependent_backups=0)
        export_string = backup.encode_record()
        imported_backup = objects.Backup.decode_record(export_string)

        # Make sure we don't lose data when converting from string
        self.assertDictEqual(self._expected_backup(backup), imported_backup)

    def test_import_record_additional_info(self):
        utils.replace_obj_loader(self, objects.Backup)
        backup = objects.Backup(context=self.context, id=1, parent_id=None,
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
        backup = objects.Backup(context=self.context, id=1, parent_id=None,
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
