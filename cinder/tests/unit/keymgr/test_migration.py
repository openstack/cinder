# Copyright 2017 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Tests for encryption key migration."""

import mock
from oslo_config import cfg

from cinder import db
from cinder.keymgr import migration
from cinder import objects
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base

CONF = cfg.CONF

FIXED_KEY_ID = '00000000-0000-0000-0000-000000000000'


class KeyMigrationTestCase(base.BaseVolumeTestCase):
    def setUp(self):
        super(KeyMigrationTestCase, self).setUp()
        self.conf = CONF
        self.fixed_key = '1' * 64
        self.conf.import_opt(name='fixed_key',
                             module_str='cinder.keymgr.conf_key_mgr',
                             group='key_manager')
        self.conf.set_override('fixed_key',
                               self.fixed_key,
                               group='key_manager')
        self.conf.set_override('backend',
                               'barbican',
                               group='key_manager')
        self.my_vols = []

    def tearDown(self):
        for vol in objects.VolumeList.get_all(self.context):
            self.volume.delete_volume(self.context, vol)
        super(KeyMigrationTestCase, self).tearDown()

    def create_volume(self, key_id=FIXED_KEY_ID):
        vol = tests_utils.create_volume(self.context, host=self.conf.host)
        vol_id = self.volume.create_volume(self.context, vol)
        if key_id:
            db.volume_update(self.context,
                             vol_id,
                             {'encryption_key_id': key_id})
        self.my_vols = objects.VolumeList.get_all_by_host(self.context,
                                                          self.conf.host)
        # Return a fully baked Volume object (not the partially baked 'vol'
        # and not the DB object).
        return next((v for v in self.my_vols if v.id == vol_id))

    @mock.patch('cinder.keymgr.migration.KeyMigrator._migrate_keys')
    @mock.patch('cinder.keymgr.migration.KeyMigrator._log_migration_status')
    def test_no_fixed_key(self,
                          mock_log_migration_status,
                          mock_migrate_keys):
        self.create_volume()
        self.conf.set_override('fixed_key', None, group='key_manager')
        migration.migrate_fixed_key(self.my_vols, conf=self.conf)
        mock_migrate_keys.assert_not_called()
        mock_log_migration_status.assert_not_called()

    @mock.patch('cinder.keymgr.migration.KeyMigrator._migrate_keys')
    @mock.patch('cinder.keymgr.migration.KeyMigrator._log_migration_status')
    def test_using_conf_key_manager(self,
                                    mock_log_migration_status,
                                    mock_migrate_keys):
        self.create_volume()
        self.conf.set_override('backend',
                               'some.ConfKeyManager',
                               group='key_manager')
        migration.migrate_fixed_key(self.my_vols, conf=self.conf)
        mock_migrate_keys.assert_not_called()
        mock_log_migration_status.assert_not_called()

    @mock.patch('cinder.keymgr.migration.KeyMigrator._migrate_keys')
    @mock.patch('cinder.keymgr.migration.KeyMigrator._log_migration_status')
    def test_using_barbican_module_path(self,
                                        mock_log_migration_status,
                                        mock_migrate_keys):
        # Verify the long-hand method of specifying the Barbican backend
        # is properly parsed.
        self.create_volume()
        self.conf.set_override(
            'backend',
            'castellan.key_manager.barbican_key_manager.BarbicanKeyManager',
            group='key_manager')
        migration.migrate_fixed_key(self.my_vols, conf=self.conf)
        mock_migrate_keys.assert_called_once_with(self.my_vols)
        mock_log_migration_status.assert_called_once_with()

    @mock.patch('cinder.keymgr.migration.KeyMigrator._migrate_keys')
    @mock.patch('cinder.keymgr.migration.KeyMigrator._log_migration_status')
    def test_using_unsupported_key_manager(self,
                                           mock_log_migration_status,
                                           mock_migrate_keys):
        self.create_volume()
        self.conf.set_override('backend',
                               'some.OtherKeyManager',
                               group='key_manager')
        migration.migrate_fixed_key(self.my_vols, conf=self.conf)
        mock_migrate_keys.assert_not_called()
        mock_log_migration_status.assert_called_once_with()

    @mock.patch('cinder.keymgr.migration.KeyMigrator._migrate_keys')
    @mock.patch('cinder.keymgr.migration.KeyMigrator._log_migration_status')
    def test_no_volumes(self,
                        mock_log_migration_status,
                        mock_migrate_keys):
        migration.migrate_fixed_key(self.my_vols, conf=self.conf)
        mock_migrate_keys.assert_not_called()
        mock_log_migration_status.assert_called_once_with()

    @mock.patch('cinder.keymgr.migration.KeyMigrator._migrate_volume_key')
    @mock.patch('barbicanclient.client.Client')
    def test_fail_no_barbican_client(self,
                                     mock_barbican_client,
                                     mock_migrate_volume_key):
        self.create_volume()
        mock_barbican_client.side_effect = Exception
        migration.migrate_fixed_key(self.my_vols, conf=self.conf)
        mock_migrate_volume_key.assert_not_called()

    @mock.patch('cinder.keymgr.migration.KeyMigrator._migrate_volume_key')
    @mock.patch('barbicanclient.client.Client')
    def test_fail_too_many_errors(self,
                                  mock_barbican_client,
                                  mock_migrate_volume_key):
        for n in range(0, (migration.MAX_KEY_MIGRATION_ERRORS + 3)):
            self.create_volume()
        mock_migrate_volume_key.side_effect = Exception
        migration.migrate_fixed_key(self.my_vols, conf=self.conf)
        self.assertEqual(mock_migrate_volume_key.call_count,
                         (migration.MAX_KEY_MIGRATION_ERRORS + 1))

    @mock.patch('cinder.keymgr.migration.KeyMigrator._migrate_keys')
    def test_migration_status_more_to_migrate(self,
                                              mock_migrate_keys):
        mock_log = self.mock_object(migration, 'LOG')
        self.create_volume()
        migration.migrate_fixed_key(self.my_vols, conf=self.conf)

        # Look for one warning (more to migrate) and no info log messages.
        mock_log.info.assert_not_called()
        self.assertEqual(mock_log.warning.call_count, 1)

    @mock.patch('cinder.keymgr.migration.KeyMigrator._migrate_keys')
    def test_migration_status_all_done(self,
                                       mock_migrate_keys):
        mock_log = self.mock_object(migration, 'LOG')
        self.create_volume(key_id=fake.ENCRYPTION_KEY_ID)
        migration.migrate_fixed_key(self.my_vols, conf=self.conf)

        # Look for one info (all done) and no warning log messages.
        mock_log.warning.assert_not_called()
        self.assertEqual(mock_log.info.call_count, 1)

    @mock.patch(
        'cinder.keymgr.migration.KeyMigrator._update_encryption_key_id')
    @mock.patch('barbicanclient.client.Client')
    def test_migrate_fixed_key_volumes(self,
                                       mock_barbican_client,
                                       mock_update_encryption_key_id):
        # Create two volumes with fixed key ID that needs to be migrated, and
        # a couple of volumes with key IDs that don't need to be migrated,
        # or no key ID.
        vol_1 = self.create_volume()
        self.create_volume(key_id=fake.UUID1)
        self.create_volume(key_id=None)
        vol_2 = self.create_volume()
        self.create_volume(key_id=fake.UUID2)

        migration.migrate_fixed_key(self.my_vols, conf=self.conf)
        calls = [mock.call(vol_1), mock.call(vol_2)]
        mock_update_encryption_key_id.assert_has_calls(calls, any_order=True)
        self.assertEqual(mock_update_encryption_key_id.call_count, len(calls))

    @mock.patch('barbicanclient.client.Client')
    def test_update_encryption_key_id(self,
                                      mock_barbican_client):
        vol = self.create_volume()

        snap_ids = [fake.SNAPSHOT_ID, fake.SNAPSHOT2_ID, fake.SNAPSHOT3_ID]
        for snap_id in snap_ids:
            tests_utils.create_snapshot(self.context, vol.id, id=snap_id)

        # Barbican's secret.store() returns a URI that contains the
        # secret's key ID at the end.
        secret_ref = 'http://some/path/' + fake.ENCRYPTION_KEY_ID
        mock_secret = mock.MagicMock()
        mock_secret.store.return_value = secret_ref

        mock_barbican_client.return_value.secrets.create.return_value \
            = mock_secret

        migration.migrate_fixed_key(self.my_vols, conf=self.conf)
        vol_db = db.volume_get(self.context, vol.id)
        self.assertEqual(fake.ENCRYPTION_KEY_ID, vol_db['encryption_key_id'])

        for snap_id in snap_ids:
            snap_db = db.snapshot_get(self.context, snap_id)
            self.assertEqual(fake.ENCRYPTION_KEY_ID,
                             snap_db['encryption_key_id'])
