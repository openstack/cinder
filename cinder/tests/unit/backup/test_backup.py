# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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
"""Tests for Backup code."""

import copy
import os
from unittest import mock
import uuid

import ddt
from eventlet import tpool
from os_brick.initiator.connectors import fake as fake_connectors
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_service import loopingcall
from oslo_utils import importutils
from oslo_utils import timeutils

import cinder
from cinder.backup import api
from cinder.backup import manager
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder.tests import fake_driver
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.tests.unit import utils
from cinder.volume import rpcapi as volume_rpcapi


CONF = cfg.CONF


class FakeBackupException(Exception):
    pass


class BaseBackupTest(test.TestCase):
    def setUp(self):
        super(BaseBackupTest, self).setUp()
        self.backup_mgr = importutils.import_object(CONF.backup_manager)
        self.backup_mgr.host = 'testhost'
        self.backup_mgr.is_initialized = True
        self.ctxt = context.get_admin_context()

        paths = ['cinder.volume.rpcapi.VolumeAPI.delete_snapshot',
                 'cinder.volume.rpcapi.VolumeAPI.delete_volume',
                 'cinder.volume.rpcapi.VolumeAPI.detach_volume',
                 'cinder.volume.rpcapi.VolumeAPI.'
                 'secure_file_operations_enabled']
        self.volume_patches = {}
        self.volume_mocks = {}
        for path in paths:
            name = path.split('.')[-1]
            self.volume_patches[name] = mock.patch(path)
            self.volume_mocks[name] = self.volume_patches[name].start()
            self.addCleanup(self.volume_patches[name].stop)

    def _create_backup_db_entry(self, volume_id=str(uuid.uuid4()),
                                restore_volume_id=None,
                                display_name='test_backup',
                                display_description='this is a test backup',
                                container='volumebackups',
                                status=fields.BackupStatus.CREATING,
                                size=1,
                                object_count=0,
                                project_id=str(uuid.uuid4()),
                                service=None,
                                temp_volume_id=None,
                                temp_snapshot_id=None,
                                snapshot_id=None,
                                metadata=None,
                                parent_id=None,
                                encryption_key_id=None):
        """Create a backup entry in the DB.

        Return the entry ID
        """
        kwargs = {}
        kwargs['volume_id'] = volume_id
        kwargs['restore_volume_id'] = restore_volume_id
        kwargs['user_id'] = str(uuid.uuid4())
        kwargs['project_id'] = project_id
        kwargs['host'] = 'testhost'
        kwargs['availability_zone'] = '1'
        kwargs['display_name'] = display_name
        kwargs['display_description'] = display_description
        kwargs['container'] = container
        kwargs['status'] = status
        kwargs['fail_reason'] = ''
        kwargs['service'] = service or CONF.backup_driver
        kwargs['snapshot_id'] = snapshot_id
        kwargs['parent_id'] = parent_id
        kwargs['size'] = size
        kwargs['object_count'] = object_count
        kwargs['temp_volume_id'] = temp_volume_id
        kwargs['temp_snapshot_id'] = temp_snapshot_id
        kwargs['metadata'] = metadata or {}
        kwargs['encryption_key_id'] = encryption_key_id
        backup = objects.Backup(context=self.ctxt, **kwargs)
        backup.create()
        return backup

    def _create_volume_db_entry(self, display_name='test_volume',
                                display_description='this is a test volume',
                                status='backing-up',
                                previous_status='available',
                                size=1,
                                host='testhost',
                                encryption_key_id=None,
                                project_id=None):
        """Create a volume entry in the DB.

        Return the entry ID
        """
        vol = {}
        vol['size'] = size
        vol['host'] = host
        vol['user_id'] = fake.USER_ID
        vol['project_id'] = project_id or fake.PROJECT_ID
        vol['status'] = status
        vol['display_name'] = display_name
        vol['display_description'] = display_description
        vol['attach_status'] = fields.VolumeAttachStatus.DETACHED
        vol['availability_zone'] = '1'
        vol['previous_status'] = previous_status
        vol['encryption_key_id'] = encryption_key_id
        vol['volume_type_id'] = fake.VOLUME_TYPE_ID
        volume = objects.Volume(context=self.ctxt, **vol)
        volume.create()
        return volume.id

    def _create_snapshot_db_entry(self, display_name='test_snapshot',
                                  display_description='test snapshot',
                                  status=fields.SnapshotStatus.AVAILABLE,
                                  size=1,
                                  volume_id=str(uuid.uuid4()),
                                  provider_location=None):
        """Create a snapshot entry in the DB.

        Return the entry ID.
        """
        kwargs = {}
        kwargs['size'] = size
        kwargs['user_id'] = fake.USER_ID
        kwargs['project_id'] = fake.PROJECT_ID
        kwargs['status'] = status
        kwargs['display_name'] = display_name
        kwargs['display_description'] = display_description
        kwargs['volume_id'] = volume_id
        kwargs['cgsnapshot_id'] = None
        kwargs['volume_size'] = size
        kwargs['metadata'] = {}
        kwargs['provider_location'] = provider_location
        kwargs['volume_type_id'] = fake.VOLUME_TYPE_ID
        snapshot_obj = objects.Snapshot(context=self.ctxt, **kwargs)
        snapshot_obj.create()
        return snapshot_obj

    def _create_volume_attach(self, volume_id):
        values = {'volume_id': volume_id,
                  'attach_status': fields.VolumeAttachStatus.ATTACHED, }
        attachment = db.volume_attach(self.ctxt, values)
        db.volume_attached(self.ctxt, attachment['id'], None, 'testhost',
                           '/dev/vd0')

    def _create_exported_record_entry(self, vol_size=1, exported_id=None):
        """Create backup metadata export entry."""
        vol_id = self._create_volume_db_entry(status='available',
                                              size=vol_size)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.AVAILABLE, volume_id=vol_id)

        if exported_id is not None:
            backup.id = exported_id

        export = self.backup_mgr.export_record(self.ctxt, backup)
        return export

    def _create_export_record_db_entry(self,
                                       volume_id=str(uuid.uuid4()),
                                       status=fields.BackupStatus.CREATING,
                                       project_id=str(uuid.uuid4()),
                                       backup_id=None):
        """Create a backup entry in the DB.

        Return the entry ID
        """
        kwargs = {}
        kwargs['volume_id'] = volume_id
        kwargs['user_id'] = fake.USER_ID
        kwargs['project_id'] = project_id
        kwargs['status'] = status
        if backup_id:
            kwargs['id'] = backup_id
        backup = objects.BackupImport(context=self.ctxt, **kwargs)
        backup.create()
        return backup


@ddt.ddt
class BackupTestCase(BaseBackupTest):
    """Test Case for backups."""

    @mock.patch.object(cinder.tests.fake_driver.FakeLoggingVolumeDriver,
                       'set_initialized')
    @mock.patch.object(cinder.tests.fake_driver.FakeLoggingVolumeDriver,
                       'do_setup')
    @mock.patch.object(cinder.tests.fake_driver.FakeLoggingVolumeDriver,
                       'check_for_setup_error')
    @mock.patch.object(cinder.db.sqlalchemy.api, '_volume_type_get_by_name',
                       v2_fakes.fake_volume_type_get)
    @mock.patch('cinder.context.get_admin_context')
    def test_init_host(self, mock_get_admin_context, mock_check, mock_setup,
                       mock_set_initialized):
        """Test stuck volumes and backups.

        Make sure stuck volumes and backups are reset to correct
        states when backup_manager.init_host() is called
        """
        def get_admin_context():
            return self.ctxt

        self.override_config('backup_service_inithost_offload', False)
        self.override_config('periodic_interval', 0)

        vol1_id = self._create_volume_db_entry()
        self._create_volume_attach(vol1_id)
        db.volume_update(self.ctxt, vol1_id, {'status': 'backing-up'})
        vol2_id = self._create_volume_db_entry()
        self._create_volume_attach(vol2_id)
        db.volume_update(self.ctxt, vol2_id, {'status': 'restoring-backup'})
        vol3_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol3_id, {'status': 'available'})
        vol4_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol4_id, {'status': 'backing-up'})
        temp_vol_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, temp_vol_id, {'status': 'available'})
        vol5_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol5_id, {'status': 'backing-up'})
        temp_snap = self._create_snapshot_db_entry()
        temp_snap.status = fields.SnapshotStatus.AVAILABLE
        temp_snap.save()

        backup1 = self._create_backup_db_entry(
            status=fields.BackupStatus.CREATING, volume_id=vol1_id)
        backup2 = self._create_backup_db_entry(
            status=fields.BackupStatus.RESTORING,
            restore_volume_id=vol2_id)
        backup3 = self._create_backup_db_entry(
            status=fields.BackupStatus.DELETING, volume_id=vol3_id)
        self._create_backup_db_entry(status=fields.BackupStatus.CREATING,
                                     volume_id=vol4_id,
                                     temp_volume_id=temp_vol_id)
        self._create_backup_db_entry(status=fields.BackupStatus.CREATING,
                                     volume_id=vol5_id,
                                     temp_snapshot_id=temp_snap.id)

        mock_get_admin_context.side_effect = get_admin_context
        self.volume = importutils.import_object(CONF.volume_manager)
        self.backup_mgr.init_host()

        vol1 = db.volume_get(self.ctxt, vol1_id)
        self.assertEqual('available', vol1['status'])
        vol2 = db.volume_get(self.ctxt, vol2_id)
        self.assertEqual('error_restoring', vol2['status'])
        vol3 = db.volume_get(self.ctxt, vol3_id)
        self.assertEqual('available', vol3['status'])
        vol4 = db.volume_get(self.ctxt, vol4_id)
        self.assertEqual('available', vol4['status'])
        vol5 = db.volume_get(self.ctxt, vol5_id)
        self.assertEqual('available', vol5['status'])

        backup1 = db.backup_get(self.ctxt, backup1.id)
        self.assertEqual(fields.BackupStatus.ERROR, backup1['status'])
        backup2 = db.backup_get(self.ctxt, backup2.id)
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup2['status'])
        self.assertRaises(exception.BackupNotFound,
                          db.backup_get,
                          self.ctxt,
                          backup3.id)

        temp_vol = objects.Volume.get_by_id(self.ctxt, temp_vol_id)
        self.volume_mocks['delete_volume'].assert_called_once_with(
            self.ctxt, temp_vol)
        self.assertTrue(self.volume_mocks['detach_volume'].called)

    @mock.patch('cinder.objects.backup.BackupList.get_all_by_host')
    @mock.patch('cinder.manager.ThreadPoolManager._add_to_threadpool')
    def test_init_host_with_service_inithost_offload(self,
                                                     mock_add_threadpool,
                                                     mock_get_all_by_host):
        vol1_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol1_id, {'status': 'available'})
        backup1 = self._create_backup_db_entry(
            status=fields.BackupStatus.DELETING, volume_id=vol1_id)

        vol2_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol2_id, {'status': 'available'})
        backup2 = self._create_backup_db_entry(
            status=fields.BackupStatus.DELETING, volume_id=vol2_id)
        mock_get_all_by_host.return_value = [backup1, backup2]
        self.backup_mgr.init_host()
        calls = [mock.call(self.backup_mgr.delete_backup, mock.ANY, backup1),
                 mock.call(self.backup_mgr.delete_backup, mock.ANY, backup2)]
        mock_add_threadpool.assert_has_calls(calls, any_order=True)
        # 3 calls because 1 is always made to handle encryption key migration.
        self.assertEqual(3, mock_add_threadpool.call_count)

    @mock.patch('cinder.keymgr.migration.migrate_fixed_key')
    @mock.patch('cinder.objects.BackupList.get_all_by_host')
    @mock.patch('cinder.manager.ThreadPoolManager._add_to_threadpool')
    def test_init_host_key_migration(self,
                                     mock_add_threadpool,
                                     mock_get_all_by_host,
                                     mock_migrate_fixed_key):

        self.backup_mgr.init_host()
        mock_add_threadpool.assert_called_once_with(
            mock_migrate_fixed_key,
            backups=mock_get_all_by_host())

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall')
    @ddt.data(123456, 654321)
    def test_setup_backup_backend_uses_new_config(
            self, new_cfg_value, mock_FILC):
        # previously used CONF.periodic_interval; see Bug #1828748
        new_cfg_name = 'backup_driver_init_check_interval'

        self.addCleanup(CONF.clear_override, new_cfg_name)
        CONF.set_override(new_cfg_name, new_cfg_value)
        mock_init_loop = mock.MagicMock()
        mock_init_loop.start.side_effect = loopingcall.LoopingCallDone()
        mock_FILC.return_value = mock_init_loop
        self.backup_mgr.setup_backup_backend(self.ctxt)
        mock_init_loop.start.assert_called_once_with(interval=new_cfg_value)

    @mock.patch('cinder.objects.service.Service.get_minimum_rpc_version')
    @mock.patch('cinder.objects.service.Service.get_minimum_obj_version')
    @mock.patch('cinder.rpc.LAST_RPC_VERSIONS', {'cinder-backup': '1.3',
                                                 'cinder-volume': '1.7'})
    def test_reset(self, get_min_obj, get_min_rpc):
        old_version = objects.base.OBJ_VERSIONS.versions[-2]

        with mock.patch('cinder.rpc.LAST_OBJ_VERSIONS',
                        {'cinder-volume': old_version,
                         'cinder-scheduler': old_version,
                         'cinder-backup': old_version}):
            backup_mgr = manager.BackupManager()

        backup_rpcapi = backup_mgr.backup_rpcapi
        volume_rpcapi = backup_mgr.volume_rpcapi
        self.assertEqual('1.3', backup_rpcapi.client.version_cap)
        self.assertEqual(old_version,
                         backup_rpcapi.client.serializer._base.version_cap)
        self.assertEqual('1.7', volume_rpcapi.client.version_cap)
        self.assertEqual(old_version,
                         volume_rpcapi.client.serializer._base.version_cap)
        get_min_obj.return_value = objects.base.OBJ_VERSIONS.get_current()
        backup_mgr.reset()

        backup_rpcapi = backup_mgr.backup_rpcapi
        volume_rpcapi = backup_mgr.volume_rpcapi
        self.assertEqual(get_min_rpc.return_value,
                         backup_rpcapi.client.version_cap)
        self.assertEqual(get_min_obj.return_value,
                         backup_rpcapi.client.serializer._base.version_cap)
        self.assertIsNone(backup_rpcapi.client.serializer._base.manifest)
        self.assertEqual(get_min_rpc.return_value,
                         volume_rpcapi.client.version_cap)
        self.assertEqual(get_min_obj.return_value,
                         volume_rpcapi.client.serializer._base.version_cap)
        self.assertIsNone(volume_rpcapi.client.serializer._base.manifest)

    @ddt.data(True, False)
    def test_is_working(self, initialized):
        self.backup_mgr.is_initialized = initialized
        self.assertEqual(initialized, self.backup_mgr.is_working())

    def test_cleanup_incomplete_backup_operations_with_exceptions(self):
        """Test cleanup resilience in the face of exceptions."""

        fake_backup_list = [{'id': fake.BACKUP_ID},
                            {'id': fake.BACKUP2_ID},
                            {'id': fake.BACKUP3_ID}]
        mock_backup_get_by_host = self.mock_object(
            objects.BackupList, 'get_all_by_host')
        mock_backup_get_by_host.return_value = fake_backup_list

        mock_backup_cleanup = self.mock_object(
            self.backup_mgr, '_cleanup_one_backup')
        mock_backup_cleanup.side_effect = [Exception]

        mock_temp_cleanup = self.mock_object(
            self.backup_mgr, '_cleanup_temp_volumes_snapshots_for_one_backup')
        mock_temp_cleanup.side_effect = [Exception]

        self.assertIsNone(
            self.backup_mgr._cleanup_incomplete_backup_operations(
                self.ctxt))

        self.assertEqual(len(fake_backup_list), mock_backup_cleanup.call_count)
        self.assertEqual(len(fake_backup_list), mock_temp_cleanup.call_count)

    @mock.patch('cinder.objects.BackupList')
    @mock.patch.object(manager.BackupManager, '_cleanup_one_backup')
    @mock.patch.object(manager.BackupManager,
                       '_cleanup_temp_volumes_snapshots_for_one_backup')
    def test_cleanup_non_primary_process(self, temp_cleanup_mock,
                                         backup_cleanup_mock, backup_ovo_mock):
        """Test cleanup doesn't run on non primary processes."""
        self.backup_mgr._process_number = 2

        self.backup_mgr._cleanup_incomplete_backup_operations(self.ctxt)

        backup_ovo_mock.get_all_by_host.assert_not_called()
        backup_cleanup_mock.assert_not_called()
        temp_cleanup_mock.assert_not_called()

    def test_cleanup_one_backing_up_volume(self):
        """Test cleanup_one_volume for volume status 'backing-up'."""

        volume_id = self._create_volume_db_entry(status='backing-up',
                                                 previous_status='available')
        volume = db.volume_get(self.ctxt, volume_id)

        self.backup_mgr._cleanup_one_volume(self.ctxt, volume)

        volume = db.volume_get(self.ctxt, volume_id)
        self.assertEqual('available', volume['status'])

    def test_cleanup_one_restoring_backup_volume(self):
        """Test cleanup_one_volume for volume status 'restoring-backup'."""

        volume_id = self._create_volume_db_entry(status='restoring-backup')
        volume = db.volume_get(self.ctxt, volume_id)

        self.backup_mgr._cleanup_one_volume(self.ctxt, volume)

        volume = db.volume_get(self.ctxt, volume_id)
        self.assertEqual('error_restoring', volume['status'])

    def test_cleanup_one_creating_backup(self):
        """Test cleanup_one_backup for volume status 'creating'."""

        vol1_id = self._create_volume_db_entry()
        self._create_volume_attach(vol1_id)
        db.volume_update(self.ctxt, vol1_id, {'status': 'backing-up', })

        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.CREATING,
            volume_id=vol1_id)

        self.backup_mgr._cleanup_one_backup(self.ctxt, backup)

        self.assertEqual(fields.BackupStatus.ERROR, backup.status)
        volume = objects.Volume.get_by_id(self.ctxt, vol1_id)
        self.assertEqual('available', volume.status)

    def test_cleanup_one_restoring_backup(self):
        """Test cleanup_one_backup for volume status 'restoring'."""

        vol1_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol1_id, {'status': 'restoring-backup', })

        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.RESTORING,
            restore_volume_id=vol1_id)

        self.backup_mgr._cleanup_one_backup(self.ctxt, backup)

        self.assertEqual(fields.BackupStatus.AVAILABLE, backup.status)
        volume = objects.Volume.get_by_id(self.ctxt, vol1_id)
        self.assertEqual('error_restoring', volume.status)

    def test_cleanup_one_deleting_backup(self):
        """Test cleanup_one_backup for backup status 'deleting'."""
        self.override_config('backup_service_inithost_offload', False)

        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.DELETING)

        self.backup_mgr._cleanup_one_backup(self.ctxt, backup)

        self.assertRaises(exception.BackupNotFound,
                          db.backup_get,
                          self.ctxt,
                          backup.id)

    def test_cleanup_one_deleting_encrypted_backup(self):
        """Test cleanup of backup status 'deleting' (encrypted)."""
        self.override_config('backup_service_inithost_offload', False)

        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.DELETING,
            encryption_key_id=fake.ENCRYPTION_KEY_ID)

        self.backup_mgr._cleanup_one_backup(self.ctxt, backup)

        backup = db.backup_get(self.ctxt, backup.id)
        self.assertIsNotNone(backup)
        self.assertEqual(fields.BackupStatus.ERROR_DELETING,
                         backup.status)

    def test_detach_all_attachments_handles_exceptions(self):
        """Test detach_all_attachments with exceptions."""

        mock_log = self.mock_object(manager, 'LOG')
        self.volume_mocks['detach_volume'].side_effect = [Exception]

        fake_attachments = [
            {
                'id': fake.ATTACHMENT_ID,
                'attached_host': 'testhost',
                'instance_uuid': None,
            },
            {
                'id': fake.ATTACHMENT2_ID,
                'attached_host': 'testhost',
                'instance_uuid': None,
            }
        ]
        fake_volume = {
            'id': fake.VOLUME3_ID,
            'volume_attachment': fake_attachments
        }

        self.backup_mgr._detach_all_attachments(self.ctxt,
                                                fake_volume)

        self.assertEqual(len(fake_attachments), mock_log.exception.call_count)

    @ddt.data(KeyError, exception.VolumeNotFound)
    def test_cleanup_temp_volumes_snapshots_for_one_backup_volume_not_found(
            self, err):
        """Ensure we handle missing volume for a backup."""

        mock_volume_get = self.mock_object(db, 'volume_get')
        mock_volume_get.side_effect = [err]

        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.CREATING)

        self.assertIsNone(
            self.backup_mgr._cleanup_temp_volumes_snapshots_for_one_backup(
                self.ctxt,
                backup))

    def test_cleanup_temp_snapshot_for_one_backup_not_found(self):
        """Ensure we handle missing temp snapshot for a backup."""

        vol1_id = self._create_volume_db_entry()
        self._create_volume_attach(vol1_id)
        db.volume_update(self.ctxt, vol1_id, {'status': 'backing-up'})
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.ERROR,
            volume_id=vol1_id,
            temp_snapshot_id=fake.SNAPSHOT_ID)

        self.assertIsNone(
            self.backup_mgr._cleanup_temp_volumes_snapshots_for_one_backup(
                self.ctxt,
                backup))

        self.assertFalse(self.volume_mocks['delete_snapshot'].called)
        self.assertIsNone(backup.temp_snapshot_id)

        backup.destroy()
        db.volume_destroy(self.ctxt, vol1_id)

    def test_cleanup_temp_volume_for_one_backup_not_found(self):
        """Ensure we handle missing temp volume for a backup."""

        vol1_id = self._create_volume_db_entry()
        self._create_volume_attach(vol1_id)
        db.volume_update(self.ctxt, vol1_id, {'status': 'backing-up'})
        backup = self._create_backup_db_entry(status=fields.BackupStatus.ERROR,
                                              volume_id=vol1_id,
                                              temp_volume_id=fake.VOLUME4_ID)

        self.assertIsNone(
            self.backup_mgr._cleanup_temp_volumes_snapshots_for_one_backup(
                self.ctxt,
                backup))

        self.assertFalse(self.volume_mocks['delete_volume'].called)
        self.assertIsNone(backup.temp_volume_id)

        backup.destroy()
        db.volume_destroy(self.ctxt, vol1_id)

    def test_create_backup_with_bad_volume_status(self):
        """Test creating a backup from a volume with a bad status."""
        vol_id = self._create_volume_db_entry(status='restoring', size=1)
        backup = self._create_backup_db_entry(volume_id=vol_id)
        self.assertRaises(exception.InvalidVolume,
                          self.backup_mgr.create_backup,
                          self.ctxt,
                          backup)

    def test_create_backup_with_bad_backup_status(self):
        """Test creating a backup with a backup with a bad status."""
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.AVAILABLE, volume_id=vol_id)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.create_backup,
                          self.ctxt,
                          backup)

    def test_create_backup_with_error(self):
        """Test error handling when error occurs during backup creation."""
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(volume_id=vol_id)

        mock_run_backup = self.mock_object(self.backup_mgr, '_run_backup')
        mock_run_backup.side_effect = FakeBackupException(str(uuid.uuid4()))
        self.assertRaises(FakeBackupException,
                          self.backup_mgr.create_backup,
                          self.ctxt,
                          backup)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('available', vol['status'])
        self.assertEqual('error_backing-up', vol['previous_status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.ERROR, backup['status'])
        self.assertTrue(mock_run_backup.called)

    @mock.patch('cinder.backup.manager.BackupManager._run_backup')
    def test_create_backup_aborted(self, run_backup_mock):
        """Test error handling when abort occurs during backup creation."""
        def my_run_backup(*args, **kwargs):
            backup.destroy()
            with backup.as_read_deleted():
                original_refresh()

        run_backup_mock.side_effect = my_run_backup
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(volume_id=vol_id)
        original_refresh = backup.refresh

        self.backup_mgr.create_backup(self.ctxt, backup)

        self.assertTrue(run_backup_mock.called)

        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        self.assertEqual('available', vol.status)
        self.assertEqual('backing-up', vol['previous_status'])
        # Make sure we didn't set the backup to available after it was deleted
        with backup.as_read_deleted():
            backup.refresh()
        self.assertEqual(fields.BackupStatus.DELETED, backup.status)

    @mock.patch('cinder.backup.manager.BackupManager._run_backup',
                side_effect=FakeBackupException(str(uuid.uuid4())))
    def test_create_backup_with_snapshot_error(self, mock_run_backup):
        """Test error handling when error occurs during backup creation."""
        vol_id = self._create_volume_db_entry(size=1)
        snapshot = self._create_snapshot_db_entry(status='backing-up',
                                                  volume_id=vol_id)
        backup = self._create_backup_db_entry(volume_id=vol_id,
                                              snapshot_id=snapshot.id)
        self.assertRaises(FakeBackupException,
                          self.backup_mgr.create_backup,
                          self.ctxt,
                          backup)

        snapshot.refresh()
        self.assertEqual('available', snapshot.status)

        backup.refresh()
        self.assertEqual(fields.BackupStatus.ERROR, backup.status)
        self.assertTrue(mock_run_backup.called)

    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.utils.temporary_chown')
    @mock.patch('builtins.open', wraps=open)
    @mock.patch.object(os.path, 'isdir', return_value=False)
    def test_create_backup(self, mock_isdir, mock_open, mock_temporary_chown,
                           mock_get_backup_device, mock_get_conn):
        """Test normal backup creation."""
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size)
        backup = self._create_backup_db_entry(volume_id=vol_id)

        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        backup_device_dict = {'backup_device': vol, 'secure_enabled': False,
                              'is_snapshot': False, }
        mock_get_backup_device.return_value = (
            objects.BackupDeviceInfo.from_primitive(backup_device_dict,
                                                    self.ctxt,
                                                    ['admin_metadata',
                                                     'metadata']))
        attach_info = {'device': {'path': '/dev/null'}}
        mock_detach_device = self.mock_object(self.backup_mgr,
                                              '_detach_device')
        mock_attach_device = self.mock_object(self.backup_mgr,
                                              '_attach_device')
        mock_attach_device.return_value = attach_info
        properties = {}
        mock_get_conn.return_value = properties

        self.backup_mgr.create_backup(self.ctxt, backup)

        mock_temporary_chown.assert_called_once_with('/dev/null')
        mock_attach_device.assert_called_once_with(self.ctxt, vol,
                                                   properties, False)
        mock_get_backup_device.assert_called_once_with(self.ctxt, backup, vol)
        mock_get_conn.assert_called_once_with()
        mock_detach_device.assert_called_once_with(self.ctxt, attach_info,
                                                   vol, properties, False,
                                                   force=True,
                                                   ignore_errors=True)

        mock_open.assert_called_once_with('/dev/null', 'rb')
        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        self.assertEqual('available', vol['status'])
        self.assertEqual('backing-up', vol['previous_status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup['status'])
        self.assertEqual(vol_size, backup['size'])
        self.assertIsNone(backup.encryption_key_id)

    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.utils.temporary_chown')
    @mock.patch('builtins.open')
    @mock.patch.object(os.path, 'isdir', return_value=True)
    def test_create_backup_set_parent_id_to_none(self, mock_isdir, mock_open,
                                                 mock_chown,
                                                 mock_backup_device,
                                                 mock_brick):
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size)
        backup = self._create_backup_db_entry(volume_id=vol_id,
                                              parent_id='mock')

        with mock.patch.object(self.backup_mgr, 'service') as \
                mock_service:
            mock_service.return_value.backup.return_value = (
                {'parent_id': None})
            with mock.patch.object(self.backup_mgr, '_detach_device'):
                device_path = '/fake/disk/path/'
                attach_info = {'device': {'path': device_path}}
                mock_attach_device = self.mock_object(self.backup_mgr,
                                                      '_attach_device')
                mock_attach_device.return_value = attach_info
                properties = {}
                mock_brick.return_value = properties
                mock_open.return_value = open('/dev/null', 'rb')
                mock_brick.return_value = properties

                self.backup_mgr.create_backup(self.ctxt, backup)

        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup.status)
        self.assertEqual(vol_size, backup.size)
        self.assertIsNone(backup.parent_id)

    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.utils.temporary_chown')
    @mock.patch('builtins.open')
    @mock.patch.object(os.path, 'isdir', return_value=True)
    def test_create_backup_set_parent_id(self, mock_isdir, mock_open,
                                         mock_chown, mock_backup_device,
                                         mock_brick):
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size)
        backup = self._create_backup_db_entry(volume_id=vol_id)
        parent_backup = self._create_backup_db_entry(size=vol_size)

        with mock.patch.object(self.backup_mgr, 'service') as \
                mock_service:
            mock_service.return_value.backup.return_value = (
                {'parent_id': parent_backup.id})
            with mock.patch.object(self.backup_mgr, '_detach_device'):
                device_path = '/fake/disk/path/'
                attach_info = {'device': {'path': device_path}}
                mock_attach_device = self.mock_object(self.backup_mgr,
                                                      '_attach_device')
                mock_attach_device.return_value = attach_info
                properties = {}
                mock_brick.return_value = properties
                mock_open.return_value = open('/dev/null', 'rb')
                mock_brick.return_value = properties

                self.backup_mgr.create_backup(self.ctxt, backup)

        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup.status)
        self.assertEqual(vol_size, backup.size)
        self.assertEqual(parent_backup.id, backup.parent_id)

    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.utils.temporary_chown')
    @mock.patch('builtins.open')
    @mock.patch.object(os.path, 'isdir', return_value=True)
    def test_create_backup_fail_with_excep(self, mock_isdir, mock_open,
                                           mock_chown, mock_backup_device,
                                           mock_brick):
        vol_id = self._create_volume_db_entry()
        backup = self._create_backup_db_entry(volume_id=vol_id)

        with mock.patch.object(self.backup_mgr, 'service') as \
                mock_service:
            mock_service.return_value.backup.side_effect = (
                FakeBackupException('fake'))
            with mock.patch.object(self.backup_mgr, '_detach_device'):
                device_path = '/fake/disk/path/'
                attach_info = {'device': {'path': device_path}}

                mock_attach_device = self.mock_object(self.backup_mgr,
                                                      '_attach_device')
                mock_attach_device.return_value = attach_info
                properties = {}
                mock_brick.return_value = properties
                mock_open.return_value = open('/dev/null', 'rb')
                mock_brick.return_value = properties

                self.assertRaises(FakeBackupException,
                                  self.backup_mgr.create_backup,
                                  self.ctxt, backup)

        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('available', vol.status)
        self.assertEqual('error_backing-up', vol.previous_status)
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.ERROR, backup.status)

    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.utils.temporary_chown')
    @mock.patch('builtins.open')
    @mock.patch.object(os.path, 'isdir', return_value=True)
    def test_run_backup_with_dir_device_path(self, mock_isdir,
                                             mock_open,
                                             mock_chown,
                                             mock_backup_device,
                                             mock_brick):
        backup_service = mock.Mock()
        backup_service.backup = mock.Mock(
            return_value=mock.sentinel.backup_update)
        self.backup_mgr.service = lambda x: backup_service

        vol_id = self._create_volume_db_entry()
        backup = self._create_backup_db_entry(volume_id=vol_id)
        volume = objects.Volume.get_by_id(self.ctxt, vol_id)

        # device_path is represented by a directory
        device_path = '/fake/disk/path/'
        attach_info = {'device': {'path': device_path}}
        self.backup_mgr._attach_device = mock.Mock(
            return_value=attach_info)
        self.backup_mgr._detach_device = mock.Mock()
        output = self.backup_mgr._run_backup(self.ctxt, backup, volume)

        mock_chown.assert_not_called()
        mock_open.assert_not_called()
        backup_service.backup.assert_called_once_with(
            backup, device_path)
        self.assertEqual(mock.sentinel.backup_update, output)

    @mock.patch('cinder.backup.manager.BackupManager._run_backup')
    @ddt.data((fields.SnapshotStatus.BACKING_UP, 'available'),
              (fields.SnapshotStatus.BACKING_UP, 'in-use'),
              (fields.SnapshotStatus.AVAILABLE, 'available'),
              (fields.SnapshotStatus.AVAILABLE, 'in-use'))
    @ddt.unpack
    def test_create_backup_with_snapshot(self, snapshot_status, volume_status,
                                         mock_run_backup):
        vol_id = self._create_volume_db_entry(status=volume_status)
        snapshot = self._create_snapshot_db_entry(volume_id=vol_id,
                                                  status=snapshot_status)
        backup = self._create_backup_db_entry(volume_id=vol_id,
                                              snapshot_id=snapshot.id)
        if snapshot_status == fields.SnapshotStatus.BACKING_UP:
            self.backup_mgr.create_backup(self.ctxt, backup)

            vol = objects.Volume.get_by_id(self.ctxt, vol_id)
            snapshot = objects.Snapshot.get_by_id(self.ctxt, snapshot.id)

            self.assertEqual(volume_status, vol.status)
            self.assertEqual(fields.SnapshotStatus.AVAILABLE, snapshot.status)
        else:
            self.assertRaises(exception.InvalidSnapshot,
                              self.backup_mgr.create_backup, self.ctxt, backup)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.remove_export_snapshot')
    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.utils.temporary_chown')
    @mock.patch('builtins.open')
    @mock.patch.object(os.path, 'isdir', return_value=False)
    def test_create_backup_with_temp_snapshot(self, mock_isdir,
                                              mock_open,
                                              mock_temporary_chown,
                                              mock_get_backup_device,
                                              mock_get_conn,
                                              mock_remove_export_snapshot):
        """Test backup in-use volume using temp snapshot."""
        self.override_config('backup_use_same_host', True)
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size,
                                              previous_status='in-use')
        backup = self._create_backup_db_entry(volume_id=vol_id)
        snap = self._create_snapshot_db_entry(volume_id=vol_id)

        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        mock_get_backup_device.return_value = (
            objects.BackupDeviceInfo.from_primitive({
                'backup_device': snap, 'secure_enabled': False,
                'is_snapshot': True, },
                self.ctxt, expected_attrs=['metadata']))

        attach_info = {
            'device': {'path': '/dev/null'},
            'conn': {'data': {}},
            'connector': fake_connectors.FakeConnector(None)}
        mock_terminate_connection_snapshot = self.mock_object(
            volume_rpcapi.VolumeAPI,
            'terminate_connection_snapshot')
        mock_initialize_connection_snapshot = self.mock_object(
            volume_rpcapi.VolumeAPI,
            'initialize_connection_snapshot')
        mock_connect_device = self.mock_object(
            manager.BackupManager,
            '_connect_device')
        mock_connect_device.return_value = attach_info
        properties = {}
        mock_get_conn.return_value = properties
        mock_open.return_value = open('/dev/null', 'rb')

        self.backup_mgr.create_backup(self.ctxt, backup)
        mock_temporary_chown.assert_called_once_with('/dev/null')
        mock_initialize_connection_snapshot.assert_called_once_with(
            self.ctxt, snap, properties)
        mock_get_backup_device.assert_called_once_with(self.ctxt, backup, vol)
        mock_get_conn.assert_called_once_with()
        mock_terminate_connection_snapshot.assert_called_once_with(
            self.ctxt, snap, properties, force=True)
        mock_remove_export_snapshot.assert_called_once_with(
            self.ctxt, mock.ANY, sync=True)
        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        self.assertEqual('in-use', vol['status'])
        self.assertEqual('backing-up', vol['previous_status'])
        backup = objects.Backup.get_by_id(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup.status)
        self.assertEqual(vol_size, backup.size)

    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver, 'create_snapshot')
    def test_create_temp_snapshot(self, mock_create_snapshot):
        volume_manager = importutils.import_object(CONF.volume_manager)
        volume_manager.driver.set_initialized()
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size,
                                              previous_status='in-use')
        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        mock_create_snapshot.return_value = {'provider_id':
                                             'fake_provider_id'}

        temp_snap = volume_manager.driver._create_temp_snapshot(
            self.ctxt, vol)

        self.assertEqual('available', temp_snap['status'])
        self.assertEqual('fake_provider_id', temp_snap['provider_id'])

    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver,
                       'create_cloned_volume')
    def test_create_temp_cloned_volume(self, mock_create_cloned_volume):
        volume_manager = importutils.import_object(CONF.volume_manager)
        volume_manager.driver.set_initialized()
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size,
                                              previous_status='in-use')
        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        mock_create_cloned_volume.return_value = {'provider_id':
                                                  'fake_provider_id'}

        temp_vol = volume_manager.driver._create_temp_cloned_volume(
            self.ctxt, vol)

        self.assertEqual('available', temp_vol['status'])
        self.assertEqual('fake_provider_id', temp_vol['provider_id'])

    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver,
                       'create_volume_from_snapshot')
    def test_create_temp_volume_from_snapshot(self, mock_create_vol_from_snap):
        volume_manager = importutils.import_object(CONF.volume_manager)
        volume_manager.driver.set_initialized()
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size,
                                              previous_status='in-use')
        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        snap = self._create_snapshot_db_entry(volume_id=vol_id)
        mock_create_vol_from_snap.return_value = {'provider_id':
                                                  'fake_provider_id'}

        temp_vol = volume_manager.driver._create_temp_volume_from_snapshot(
            self.ctxt, vol, snap)

        self.assertEqual('available', temp_vol['status'])
        self.assertEqual('fake_provider_id', temp_vol['provider_id'])

    @mock.patch('cinder.volume.volume_utils.notify_about_backup_usage')
    def test_create_backup_with_notify(self, notify):
        """Test normal backup creation with notifications."""
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size)
        backup = self._create_backup_db_entry(volume_id=vol_id)

        self.mock_object(self.backup_mgr, '_run_backup')
        self.backup_mgr.create_backup(self.ctxt, backup)
        self.assertEqual(2, notify.call_count)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.volume.volume_utils.clone_encryption_key')
    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    def test_create_backup_encrypted_volume(self,
                                            mock_connector_properties,
                                            mock_clone_encryption_key,
                                            mock_get_backup_device):
        """Test backup of encrypted volume.

        Test whether the volume's encryption key ID is cloned and
        saved in the backup.
        """
        vol_id = self._create_volume_db_entry(encryption_key_id=fake.UUID1)
        backup = self._create_backup_db_entry(volume_id=vol_id)

        self.mock_object(self.backup_mgr, '_detach_device')
        mock_attach_device = self.mock_object(self.backup_mgr,
                                              '_attach_device')
        mock_attach_device.return_value = {'device': {'path': '/dev/null'}}
        mock_clone_encryption_key.return_value = fake.UUID2

        self.backup_mgr.create_backup(self.ctxt, backup)
        mock_clone_encryption_key.assert_called_once_with(self.ctxt,
                                                          mock.ANY,
                                                          fake.UUID1)
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fake.UUID2, backup.encryption_key_id)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.volume.volume_utils.clone_encryption_key')
    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    def test_create_backup_encrypted_volume_again(self,
                                                  mock_connector_properties,
                                                  mock_clone_encryption_key,
                                                  mock_get_backup_device):
        """Test backup of encrypted volume.

        Test when the backup already has a clone of the volume's encryption
        key ID.
        """
        vol_id = self._create_volume_db_entry(encryption_key_id=fake.UUID1)
        backup = self._create_backup_db_entry(volume_id=vol_id,
                                              encryption_key_id=fake.UUID2)

        self.mock_object(self.backup_mgr, '_detach_device')
        mock_attach_device = self.mock_object(self.backup_mgr,
                                              '_attach_device')
        mock_attach_device.return_value = {'device': {'path': '/dev/null'}}

        self.backup_mgr.create_backup(self.ctxt, backup)
        mock_clone_encryption_key.assert_not_called()

    def test_restore_backup_with_bad_volume_status(self):
        """Test error handling.

        Test error handling when restoring a backup to a volume
        with a bad status.
        """
        vol_id = self._create_volume_db_entry(status='available', size=1)
        backup = self._create_backup_db_entry(volume_id=vol_id)
        self.assertRaises(exception.InvalidVolume,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup,
                          vol_id)
        backup = db.backup_get(self.ctxt, backup.id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('error_restoring', vol['status'])
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup['status'])

    def test_restore_backup_with_bad_backup_status(self):
        """Test error handling.

        Test error handling when restoring a backup with a backup
        with a bad status.
        """
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=1)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.AVAILABLE, volume_id=vol_id)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup,
                          vol_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('error', vol['status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.ERROR, backup['status'])

    def test_restore_backup_with_driver_error(self):
        """Test error handling when an error occurs during backup restore."""
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=1)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.RESTORING, volume_id=vol_id)

        mock_run_restore = self.mock_object(
            self.backup_mgr,
            '_run_restore')
        mock_run_restore.side_effect = FakeBackupException('fake')
        self.assertRaises(FakeBackupException,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup,
                          vol_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('error_restoring', vol['status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup['status'])
        self.assertTrue(mock_run_restore.called)

    def test_restore_backup_with_driver_cancellation(self):
        """Test error handling when a restore is cancelled."""
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=1)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.RESTORING, volume_id=vol_id)

        mock_run_restore = self.mock_object(
            self.backup_mgr,
            '_run_restore')
        mock_run_restore.side_effect = exception.BackupRestoreCancel(
            vol_id=vol_id, back_id=backup.id)
        # We shouldn't raise an exception on the call, it's OK to cancel
        self.backup_mgr.restore_backup(self.ctxt, backup, vol_id)
        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        self.assertEqual('error', vol.status)
        backup.refresh()
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup.status)
        self.assertTrue(mock_run_restore.called)

    def test_restore_backup_with_creating_volume(self):
        """Test restore backup with a creating volume."""
        vol_id = self._create_volume_db_entry(
            status=fields.VolumeStatus.CREATING,
            size=1)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.RESTORING, volume_id=vol_id)
        mock_run_restore = self.mock_object(
            self.backup_mgr,
            '_run_restore')
        self.backup_mgr.restore_backup(self.ctxt, backup, vol_id)
        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        self.assertEqual(fields.VolumeStatus.AVAILABLE, vol.status)
        self.assertIsNotNone(vol.launched_at)
        backup.refresh()
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup.status)
        self.assertTrue(mock_run_restore.called)

    def test_restore_backup_canceled_with_creating_volume(self):
        """Test restore backup with a creating volume."""
        vol_id = self._create_volume_db_entry(
            status=fields.VolumeStatus.CREATING,
            size=1)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.RESTORING, volume_id=vol_id)
        mock_run_restore = self.mock_object(
            self.backup_mgr,
            '_run_restore')
        mock_run_restore.side_effect = exception.BackupRestoreCancel(
            vol_id=vol_id, back_id=backup.id)
        # We shouldn't raise an exception on the call, it's OK to cancel
        self.backup_mgr.restore_backup(self.ctxt, backup, vol_id)
        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        self.assertEqual(fields.VolumeStatus.ERROR, vol.status)
        backup.refresh()
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup.status)
        self.assertTrue(mock_run_restore.called)

    def test_restore_backup_with_bad_service(self):
        """Test error handling.

        Test error handling when attempting a restore of a backup
        with a different service to that used to create the backup.
        """
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=1)
        service = 'cinder.tests.backup.bad_service'
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.RESTORING, volume_id=vol_id,
            service=service)

        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup,
                          vol_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('error', vol['status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup['status'])

    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.utils.temporary_chown')
    @mock.patch('builtins.open', wraps=open)
    @mock.patch.object(os.path, 'isdir', return_value=False)
    @ddt.data({'os_name': 'nt', 'exp_open_mode': 'rb+'},
              {'os_name': 'posix', 'exp_open_mode': 'wb'})
    @ddt.unpack
    def test_restore_backup(self, mock_isdir, mock_open,
                            mock_temporary_chown, mock_get_conn,
                            os_name, exp_open_mode):
        """Test normal backup restoration."""
        vol_size = 1
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=vol_size)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.RESTORING, volume_id=vol_id)

        properties = {}
        mock_get_conn.return_value = properties
        mock_secure_enabled = (
            self.volume_mocks['secure_file_operations_enabled'])
        mock_secure_enabled.return_value = False
        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        attach_info = {'device': {'path': '/dev/null'}}
        mock_detach_device = self.mock_object(self.backup_mgr,
                                              '_detach_device')
        mock_attach_device = self.mock_object(self.backup_mgr,
                                              '_attach_device')
        mock_attach_device.return_value = attach_info

        with mock.patch('os.name', os_name):
            self.backup_mgr.restore_backup(self.ctxt, backup, vol_id)

        mock_open.assert_called_once_with('/dev/null', exp_open_mode)
        mock_temporary_chown.assert_called_once_with('/dev/null')
        mock_get_conn.assert_called_once_with()
        vol.status = 'available'
        vol.obj_reset_changes()
        mock_secure_enabled.assert_called_once_with(self.ctxt, vol)
        mock_attach_device.assert_called_once_with(self.ctxt, vol,
                                                   properties)
        mock_detach_device.assert_called_once_with(self.ctxt, attach_info,
                                                   vol, properties, force=True)

        vol = objects.Volume.get_by_id(self.ctxt, vol_id)
        self.assertEqual('available', vol['status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertNotEqual(backup.id, vol.metadata.get('src_backup_id'))
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup['status'])

    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.utils.temporary_chown')
    @mock.patch('builtins.open', wraps=open)
    @mock.patch.object(os.path, 'isdir', return_value=False)
    @ddt.data({'os_name': 'nt', 'exp_open_mode': 'rb+'},
              {'os_name': 'posix', 'exp_open_mode': 'wb'})
    @ddt.unpack
    def test_restore_backup_new_volume(self,
                                       mock_isdir,
                                       mock_open,
                                       mock_temporary_chown,
                                       mock_get_conn,
                                       os_name,
                                       exp_open_mode):
        """Test normal backup restoration."""
        vol_size = 1
        vol_id = self._create_volume_db_entry(
            status='restoring-backup', size=vol_size)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.RESTORING, volume_id=vol_id)
        vol2_id = self._create_volume_db_entry(
            status='restoring-backup', size=vol_size)
        backup2 = self._create_backup_db_entry(
            status=fields.BackupStatus.RESTORING, volume_id=vol2_id)
        vol2 = objects.Volume.get_by_id(self.ctxt, vol2_id)

        properties = {}
        mock_get_conn.return_value = properties
        mock_secure_enabled = (
            self.volume_mocks['secure_file_operations_enabled'])
        mock_secure_enabled.return_value = False
        new_vol_id = self._create_volume_db_entry(
            status='restoring-backup', size=vol_size)
        vol = objects.Volume.get_by_id(self.ctxt, new_vol_id)
        attach_info = {'device': {'path': '/dev/null'}}
        mock_attach_device = self.mock_object(self.backup_mgr,
                                              '_attach_device')
        self.mock_object(self.backup_mgr, '_detach_device')
        mock_attach_device.return_value = attach_info

        with mock.patch('os.name', os_name):
            self.backup_mgr.restore_backup(self.ctxt, backup, new_vol_id)

        backup.status = "restoring"
        db.backup_update(self.ctxt, backup.id, {"status": "restoring"})
        vol.status = 'available'
        vol.obj_reset_changes()
        with mock.patch('os.name', os_name):
            self.backup_mgr.restore_backup(self.ctxt, backup, vol2_id)

        vol2.refresh()
        old_src_backup_id = vol2.metadata["src_backup_id"]
        self.assertEqual(backup.id, old_src_backup_id)
        vol2.status = 'restoring-backup'
        db.volume_update(self.ctxt, vol2.id, {"status": "restoring-backup"})
        vol2.obj_reset_changes()

        with mock.patch('os.name', os_name):
            self.backup_mgr.restore_backup(self.ctxt, backup2, vol2_id)

        vol2.status = 'available'
        vol2.obj_reset_changes()
        vol.refresh()
        vol2.refresh()
        self.assertEqual('available', vol.status)
        backup.refresh()
        self.assertEqual(backup.id, vol.metadata["src_backup_id"])
        self.assertNotEqual(old_src_backup_id, vol2.metadata["src_backup_id"])
        self.assertEqual(backup2.id, vol2.metadata["src_backup_id"])
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup['status'])

    @mock.patch('cinder.volume.volume_utils.notify_about_backup_usage')
    def test_restore_backup_with_notify(self, notify):
        """Test normal backup restoration with notifications."""
        vol_size = 1
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=vol_size)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.RESTORING, volume_id=vol_id)
        self.backup_mgr._run_restore = mock.Mock()

        self.backup_mgr.restore_backup(self.ctxt, backup, vol_id)
        self.assertEqual(2, notify.call_count)

    @mock.patch('cinder.volume.volume_utils.clone_encryption_key')
    @mock.patch('cinder.volume.volume_utils.delete_encryption_key')
    @mock.patch(
        'cinder.tests.unit.backup.fake_service.FakeBackupService.restore')
    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    def test_restore_backup_encrypted_volume(self,
                                             mock_connector_properties,
                                             mock_backup_driver_restore,
                                             mock_delete_encryption_key,
                                             mock_clone_encryption_key):
        """Test restore of encrypted volume.

        Test restoring a volume from its own backup. In this situation,
        the volume's encryption key ID shouldn't change.
        """
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              encryption_key_id=fake.UUID1)
        backup = self._create_backup_db_entry(
            volume_id=vol_id,
            status=fields.BackupStatus.RESTORING,
            encryption_key_id=fake.UUID2)

        self.mock_object(self.backup_mgr, '_detach_device')
        mock_attach_device = self.mock_object(self.backup_mgr,
                                              '_attach_device')
        mock_attach_device.return_value = {'device': {'path': '/dev/null'}}

        self.backup_mgr.restore_backup(self.ctxt, backup, vol_id)
        volume = db.volume_get(self.ctxt, vol_id)
        self.assertEqual(fake.UUID1, volume.encryption_key_id)
        mock_clone_encryption_key.assert_not_called()
        mock_delete_encryption_key.assert_not_called()

    @mock.patch('cinder.volume.volume_utils.clone_encryption_key')
    @mock.patch('cinder.volume.volume_utils.delete_encryption_key')
    @mock.patch(
        'cinder.tests.unit.backup.fake_service.FakeBackupService.restore')
    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    def test_restore_backup_new_encrypted_volume(self,
                                                 mock_connector_properties,
                                                 mock_backup_driver_restore,
                                                 mock_delete_encryption_key,
                                                 mock_clone_encryption_key):
        """Test restore of encrypted volume.

        Test handling of encryption key IDs when retoring to another
        encrypted volume, i.e. a volume whose key ID is different from
        the volume originally backed up.
        - The volume's prior encryption key ID is deleted.
        - The volume is assigned a fresh clone of the backup's encryption
          key ID.
        """
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              encryption_key_id=fake.UUID1)
        backup = self._create_backup_db_entry(
            volume_id=vol_id,
            status=fields.BackupStatus.RESTORING,
            encryption_key_id=fake.UUID2)

        self.mock_object(self.backup_mgr, '_detach_device')
        mock_attach_device = self.mock_object(self.backup_mgr,
                                              '_attach_device')
        mock_attach_device.return_value = {'device': {'path': '/dev/null'}}
        mock_clone_encryption_key.return_value = fake.UUID3

        # Mimic the driver's side effect where it updates the volume's
        # metadata. For backups of encrypted volumes, this will essentially
        # overwrite the volume's encryption key ID prior to the restore.
        def restore_side_effect(backup, volume_id, volume_file):
            db.volume_update(self.ctxt,
                             volume_id,
                             {'encryption_key_id': fake.UUID4})
        mock_backup_driver_restore.side_effect = restore_side_effect

        self.backup_mgr.restore_backup(self.ctxt, backup, vol_id)

        # Volume's original encryption key ID should be deleted
        mock_delete_encryption_key.assert_called_once_with(self.ctxt,
                                                           mock.ANY,
                                                           fake.UUID1)

        # Backup's encryption key ID should have been cloned
        mock_clone_encryption_key.assert_called_once_with(self.ctxt,
                                                          mock.ANY,
                                                          fake.UUID2)

        # Volume should have the cloned backup key ID
        volume = db.volume_get(self.ctxt, vol_id)
        self.assertEqual(fake.UUID3, volume.encryption_key_id)

        # Backup's key ID should not have changed
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fake.UUID2, backup.encryption_key_id)

    @mock.patch('cinder.volume.volume_utils.clone_encryption_key')
    @mock.patch('cinder.volume.volume_utils.delete_encryption_key')
    @mock.patch(
        'cinder.tests.unit.backup.fake_service.FakeBackupService.restore')
    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    def test_restore_backup_glean_key_id(self,
                                         mock_connector_properties,
                                         mock_backup_driver_restore,
                                         mock_delete_encryption_key,
                                         mock_clone_encryption_key):
        """Test restore of encrypted volume.

        Test restoring a backup that was created prior to when the encryption
        key ID is saved in the backup DB. The backup encryption key ID is
        gleaned from the restored volume.
        """
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              encryption_key_id=fake.UUID1)
        backup = self._create_backup_db_entry(
            volume_id=vol_id,
            status=fields.BackupStatus.RESTORING)

        self.mock_object(self.backup_mgr, '_detach_device')
        mock_attach_device = self.mock_object(self.backup_mgr,
                                              '_attach_device')
        mock_attach_device.return_value = {'device': {'path': '/dev/null'}}
        mock_clone_encryption_key.return_value = fake.UUID3

        # Mimic the driver's side effect where it updates the volume's
        # metadata. For backups of encrypted volumes, this will essentially
        # overwrite the volume's encryption key ID prior to the restore.
        def restore_side_effect(backup, volume_id, volume_file):
            db.volume_update(self.ctxt,
                             volume_id,
                             {'encryption_key_id': fake.UUID4})
        mock_backup_driver_restore.side_effect = restore_side_effect

        self.backup_mgr.restore_backup(self.ctxt, backup, vol_id)

        # Volume's original encryption key ID should be deleted
        mock_delete_encryption_key.assert_called_once_with(self.ctxt,
                                                           mock.ANY,
                                                           fake.UUID1)

        # Backup's encryption key ID should have been cloned from
        # the value restored from the metadata.
        mock_clone_encryption_key.assert_called_once_with(self.ctxt,
                                                          mock.ANY,
                                                          fake.UUID4)

        # Volume should have the cloned backup key ID
        volume = db.volume_get(self.ctxt, vol_id)
        self.assertEqual(fake.UUID3, volume.encryption_key_id)

        # Backup's key ID should have been gleaned from value restored
        # from the backup's metadata
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fake.UUID4, backup.encryption_key_id)

    def test_delete_backup_with_bad_backup_status(self):
        """Test error handling.

        Test error handling when deleting a backup with a backup
        with a bad status.
        """
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.AVAILABLE, volume_id=vol_id)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.delete_backup,
                          self.ctxt,
                          backup)
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.ERROR, backup['status'])

    def test_delete_backup_with_error(self):
        """Test error handling when an error occurs during backup deletion."""
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.DELETING,
            display_name='fail_on_delete', volume_id=vol_id)
        self.assertRaises(IOError,
                          self.backup_mgr.delete_backup,
                          self.ctxt,
                          backup)
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.ERROR, backup['status'])

    def test_delete_backup_with_bad_service(self):
        """Test error handling.

        Test error handling when attempting a delete of a backup
        with a different service to that used to create the backup.
        """
        vol_id = self._create_volume_db_entry(size=1)
        service = 'cinder.tests.backup.bad_service'
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.DELETING, volume_id=vol_id,
            service=service)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.delete_backup,
                          self.ctxt,
                          backup)
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual(fields.BackupStatus.ERROR, backup['status'])

    def test_delete_backup_with_no_service(self):
        """Test error handling.

        Test error handling when attempting a delete of a backup
        with no service defined for that backup, relates to bug #1162908
        """
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.DELETING, volume_id=vol_id)
        backup.service = None
        backup.save()
        self.backup_mgr.delete_backup(self.ctxt, backup)

    def test_delete_backup(self):
        """Test normal backup deletion."""
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.DELETING, volume_id=vol_id,
            service='cinder.tests.unit.backup.fake_service.FakeBackupService')
        self.backup_mgr.delete_backup(self.ctxt, backup)
        self.assertRaises(exception.BackupNotFound,
                          db.backup_get,
                          self.ctxt,
                          backup.id)

        ctxt_read_deleted = context.get_admin_context('yes')
        backup = db.backup_get(ctxt_read_deleted, backup.id)
        self.assertTrue(backup.deleted)
        self.assertGreaterEqual(timeutils.utcnow(), backup.deleted_at)
        self.assertEqual(fields.BackupStatus.DELETED, backup.status)

    @mock.patch('cinder.volume.volume_utils.delete_encryption_key')
    def test_delete_backup_of_encrypted_volume(self,
                                               mock_delete_encryption_key):
        """Test deletion of backup of encrypted volume"""
        vol_id = self._create_volume_db_entry(
            encryption_key_id=fake.UUID1)
        backup = self._create_backup_db_entry(
            volume_id=vol_id,
            status=fields.BackupStatus.DELETING,
            encryption_key_id=fake.UUID2)
        self.backup_mgr.delete_backup(self.ctxt, backup)
        mock_delete_encryption_key.assert_called_once_with(self.ctxt,
                                                           mock.ANY,
                                                           fake.UUID2)
        ctxt_read_deleted = context.get_admin_context('yes')
        backup = db.backup_get(ctxt_read_deleted, backup.id)
        self.assertTrue(backup.deleted)
        self.assertIsNone(backup.encryption_key_id)

    @mock.patch('cinder.volume.volume_utils.notify_about_backup_usage')
    def test_delete_backup_with_notify(self, notify):
        """Test normal backup deletion with notifications."""
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.DELETING, volume_id=vol_id)
        self.backup_mgr.delete_backup(self.ctxt, backup)
        self.assertEqual(2, notify.call_count)

    def test_list_backup(self):
        project_id = fake.PROJECT_ID
        backups = db.backup_get_all_by_project(self.ctxt, project_id)
        self.assertEqual(0, len(backups))

        self._create_backup_db_entry()
        b2 = self._create_backup_db_entry(project_id=project_id)
        backups = db.backup_get_all_by_project(self.ctxt, project_id)
        self.assertEqual(1, len(backups))
        self.assertEqual(b2.id, backups[0].id)

    def test_backup_get_all_by_project_with_deleted(self):
        """Test deleted backups.

        Test deleted backups don't show up in backup_get_all_by_project.
        Unless context.read_deleted is 'yes'.
        """
        project_id = fake.PROJECT2_ID
        backups = db.backup_get_all_by_project(self.ctxt, project_id)
        self.assertEqual(0, len(backups))

        backup_keep = self._create_backup_db_entry(project_id=project_id)
        backup = self._create_backup_db_entry(project_id=project_id)
        db.backup_destroy(self.ctxt, backup.id)

        backups = db.backup_get_all_by_project(self.ctxt, project_id)
        self.assertEqual(1, len(backups))
        self.assertEqual(backup_keep.id, backups[0].id)

        ctxt_read_deleted = context.get_admin_context('yes')
        backups = db.backup_get_all_by_project(ctxt_read_deleted, project_id)
        self.assertEqual(2, len(backups))

    def test_backup_get_all_by_host_with_deleted(self):
        """Test deleted backups.

        Test deleted backups don't show up in backup_get_all_by_project.
        Unless context.read_deleted is 'yes'
        """
        backups = db.backup_get_all_by_host(self.ctxt, 'testhost')
        self.assertEqual(0, len(backups))

        backup_keep = self._create_backup_db_entry()
        backup = self._create_backup_db_entry()
        db.backup_destroy(self.ctxt, backup.id)

        backups = db.backup_get_all_by_host(self.ctxt, 'testhost')
        self.assertEqual(1, len(backups))
        self.assertEqual(backup_keep.id, backups[0].id)

        ctxt_read_deleted = context.get_admin_context('yes')
        backups = db.backup_get_all_by_host(ctxt_read_deleted, 'testhost')
        self.assertEqual(2, len(backups))

    def test_export_record_with_bad_service(self):
        """Test error handling.

        Test error handling when attempting an export of a backup
        record with a different service to that used to create the backup.
        """
        vol_id = self._create_volume_db_entry(size=1)
        service = 'cinder.tests.backup.bad_service'
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.AVAILABLE, volume_id=vol_id,
            service=service)

        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.export_record,
                          self.ctxt,
                          backup)

    def test_export_record_with_bad_backup_status(self):
        """Test error handling.

        Test error handling when exporting a backup record with a backup
        with a bad status.
        """
        vol_id = self._create_volume_db_entry(status='available',
                                              size=1)
        backup = self._create_backup_db_entry(status=fields.BackupStatus.ERROR,
                                              volume_id=vol_id)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.export_record,
                          self.ctxt,
                          backup)

    def test_export_record(self):
        """Test normal backup record export."""
        service = 'cinder.tests.unit.backup.fake_service.FakeBackupService'
        vol_size = 1
        vol_id = self._create_volume_db_entry(status='available',
                                              size=vol_size)
        backup = self._create_backup_db_entry(
            status=fields.BackupStatus.AVAILABLE, volume_id=vol_id,
            service=service)

        export = self.backup_mgr.export_record(self.ctxt, backup)
        self.assertEqual(service, export['backup_service'])
        self.assertIn('backup_url', export)

    def test_import_record_with_verify_not_implemented(self):
        """Test normal backup record import.

        Test the case when import succeeds for the case that the
        driver does not support verify.
        """
        vol_size = 1
        backup_id = fake.BACKUP4_ID
        export = self._create_exported_record_entry(vol_size=vol_size,
                                                    exported_id=backup_id)
        imported_record = self._create_export_record_db_entry(
            backup_id=backup_id)
        backup_hosts = []
        self.backup_mgr.import_record(self.ctxt,
                                      imported_record,
                                      export['backup_service'],
                                      export['backup_url'],
                                      backup_hosts)
        backup = db.backup_get(self.ctxt, imported_record.id)
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup['status'])
        self.assertEqual(vol_size, backup['size'])

    def test_import_record_with_wrong_id(self):
        """Test normal backup record import.

        Test the case when import succeeds for the case that the
        driver does not support verify.
        """
        vol_size = 1
        export = self._create_exported_record_entry(vol_size=vol_size)
        imported_record = self._create_export_record_db_entry()
        backup_hosts = []
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.import_record,
                          self.ctxt,
                          imported_record,
                          export['backup_service'],
                          export['backup_url'],
                          backup_hosts)

    def test_import_record_with_bad_service(self):
        """Test error handling.

        Test error handling when attempting an import of a backup
        record with a different service to that used to create the backup.
        """
        export = self._create_exported_record_entry()
        export['backup_service'] = 'cinder.tests.unit.backup.bad_service'
        imported_record = self._create_export_record_db_entry()

        # Test the case where the additional hosts list is empty
        backup_hosts = []
        self.assertRaises(exception.ServiceNotFound,
                          self.backup_mgr.import_record,
                          self.ctxt,
                          imported_record,
                          export['backup_service'],
                          export['backup_url'],
                          backup_hosts)

        # Test that the import backup keeps calling other hosts to find a
        # suitable host for the backup service
        backup_hosts = ['fake1', 'fake2']
        backup_hosts_expect = list(backup_hosts)
        BackupAPI_import = 'cinder.backup.rpcapi.BackupAPI.import_record'
        with mock.patch(BackupAPI_import) as _mock_backup_import:
            self.backup_mgr.import_record(self.ctxt,
                                          imported_record,
                                          export['backup_service'],
                                          export['backup_url'],
                                          backup_hosts)

            next_host = backup_hosts_expect.pop()
            _mock_backup_import.assert_called_once_with(
                self.ctxt,
                next_host,
                imported_record,
                export['backup_service'],
                export['backup_url'],
                backup_hosts_expect)

    def test_import_record_with_invalid_backup(self):
        """Test error handling.

        Test error handling when attempting an import of a backup
        record where the backup driver returns an exception.
        """
        export = self._create_exported_record_entry()
        backup_driver = self.backup_mgr.service(self.ctxt)
        _mock_record_import_class = ('%s.%s.%s' %
                                     (backup_driver.__module__,
                                      backup_driver.__class__.__name__,
                                      'import_record'))
        imported_record = self._create_export_record_db_entry()
        backup_hosts = []
        with mock.patch(_mock_record_import_class) as _mock_record_import:
            _mock_record_import.side_effect = FakeBackupException('fake')
            self.assertRaises(exception.InvalidBackup,
                              self.backup_mgr.import_record,
                              self.ctxt,
                              imported_record,
                              export['backup_service'],
                              export['backup_url'],
                              backup_hosts)
            self.assertTrue(_mock_record_import.called)
        backup = db.backup_get(self.ctxt, imported_record.id)
        self.assertEqual(fields.BackupStatus.ERROR, backup['status'])

    def test_not_supported_driver_to_force_delete(self):
        """Test force delete check method for not supported drivers."""
        self.override_config('backup_driver',
                             'cinder.backup.drivers.ceph.CephBackupDriver')
        self.backup_mgr = importutils.import_object(CONF.backup_manager)
        result = self.backup_mgr.check_support_to_force_delete(self.ctxt)
        self.assertFalse(result)

    @mock.patch('cinder.backup.drivers.nfs.NFSBackupDriver.'
                '_init_backup_repo_path', return_value=None)
    @mock.patch('cinder.backup.drivers.nfs.NFSBackupDriver.'
                'check_for_setup_error', return_value=None)
    def test_check_support_to_force_delete(self, mock_check_configuration,
                                           mock_init_backup_repo_path):
        """Test force delete check method for supported drivers."""
        self.override_config('backup_driver',
                             'cinder.backup.drivers.nfs.NFSBackupDriver')
        self.backup_mgr = importutils.import_object(CONF.backup_manager)
        result = self.backup_mgr.check_support_to_force_delete(self.ctxt)
        self.assertTrue(result)

    def test_backup_has_dependent_backups(self):
        """Test backup has dependent backups.

        Test the query of has_dependent_backups in backup object is correct.
        """
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size)
        backup = self._create_backup_db_entry(volume_id=vol_id)
        self.assertFalse(backup.has_dependent_backups)

    def test_default_tpool_size(self):
        """Test we can set custom tpool size."""
        tpool._nthreads = 20
        self.assertListEqual([], tpool._threads)

        self.backup_mgr = importutils.import_object(CONF.backup_manager)

        self.assertEqual(60, tpool._nthreads)
        self.assertListEqual([], tpool._threads)

    def test_tpool_size(self):
        """Test we can set custom tpool size."""
        self.assertNotEqual(100, tpool._nthreads)
        self.assertListEqual([], tpool._threads)

        self.override_config('backup_native_threads_pool_size', 100)
        self.backup_mgr = importutils.import_object(CONF.backup_manager)

        self.assertEqual(100, tpool._nthreads)
        self.assertListEqual([], tpool._threads)

    @mock.patch('cinder.backup.manager.BackupManager._run_restore')
    def test_backup_max_operations_restore(self, mock_restore):
        mock_sem = self.mock_object(self.backup_mgr, '_semaphore')
        vol_id = self._create_volume_db_entry(
            status=fields.VolumeStatus.RESTORING_BACKUP)
        backup = self._create_backup_db_entry(
            volume_id=vol_id, status=fields.BackupStatus.RESTORING)

        self.backup_mgr.restore_backup(self.ctxt, backup, vol_id)

        self.assertEqual(1, mock_sem.__enter__.call_count)
        self.assertEqual(1, mock_restore.call_count)
        self.assertEqual(1, mock_sem.__exit__.call_count)

    @mock.patch('cinder.backup.manager.BackupManager._run_backup')
    def test_backup_max_operations_backup(self, mock_backup):
        mock_sem = self.mock_object(self.backup_mgr, '_semaphore')
        vol_id = self._create_volume_db_entry(
            status=fields.VolumeStatus.BACKING_UP)
        backup = self._create_backup_db_entry(
            volume_id=vol_id, status=fields.BackupStatus.CREATING)

        self.backup_mgr.create_backup(self.ctxt, backup)

        self.assertEqual(1, mock_sem.__enter__.call_count)
        self.assertEqual(1, mock_backup.call_count)
        self.assertEqual(1, mock_sem.__exit__.call_count)


@ddt.ddt
class BackupAPITestCase(BaseBackupTest):
    def setUp(self):
        super(BackupAPITestCase, self).setUp()
        self.api = api.API()

    def test_get_all_wrong_all_tenants_value(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.api.get_all, self.ctxt, {'all_tenants': 'bad'})

    @mock.patch.object(objects, 'BackupList')
    def test_get_all_no_all_tenants_value(self, mock_backuplist):
        result = self.api.get_all(self.ctxt, {'key': 'value'})
        self.assertFalse(mock_backuplist.get_all.called)
        self.assertEqual(mock_backuplist.get_all_by_project.return_value,
                         result)
        mock_backuplist.get_all_by_project.assert_called_once_with(
            self.ctxt, self.ctxt.project_id, {'key': 'value'}, None, None,
            None, None, None)

    @mock.patch.object(objects, 'BackupList')
    @ddt.data(False, 'false', '0', 0, 'no')
    def test_get_all_false_value_all_tenants(
            self, false_value, mock_backuplist):
        result = self.api.get_all(self.ctxt, {'all_tenants': false_value,
                                              'key': 'value'})
        self.assertFalse(mock_backuplist.get_all.called)
        self.assertEqual(mock_backuplist.get_all_by_project.return_value,
                         result)
        mock_backuplist.get_all_by_project.assert_called_once_with(
            self.ctxt, self.ctxt.project_id, {'key': 'value'}, None, None,
            None, None, None)

    @mock.patch.object(objects, 'BackupList')
    @ddt.data(True, 'true', '1', 1, 'yes')
    def test_get_all_true_value_all_tenants(
            self, true_value, mock_backuplist):
        result = self.api.get_all(self.ctxt, {'all_tenants': true_value,
                                              'key': 'value'})
        self.assertFalse(mock_backuplist.get_all_by_project.called)
        self.assertEqual(mock_backuplist.get_all.return_value,
                         result)
        mock_backuplist.get_all.assert_called_once_with(
            self.ctxt, {'key': 'value'}, None, None, None, None, None)

    @mock.patch.object(objects, 'BackupList')
    def test_get_all_true_value_all_tenants_non_admin(self, mock_backuplist):
        ctxt = context.RequestContext(uuid.uuid4(), uuid.uuid4())
        result = self.api.get_all(ctxt, {'all_tenants': '1',
                                         'key': 'value'})
        self.assertFalse(mock_backuplist.get_all.called)
        self.assertEqual(mock_backuplist.get_all_by_project.return_value,
                         result)
        mock_backuplist.get_all_by_project.assert_called_once_with(
            ctxt, ctxt.project_id, {'key': 'value'}, None, None, None, None,
            None)

    @mock.patch.object(api.API, '_get_available_backup_service_host',
                       return_value='fake_host')
    @mock.patch.object(db, 'backup_create',
                       side_effect=db_exc.DBError())
    def test_create_when_failed_to_create_backup_object(
            self, mock_create,
            mock_get_service):

        # Create volume in admin context
        volume_id = utils.create_volume(self.ctxt)['id']

        # Will try to backup from a different context
        new_context = copy.copy(self.ctxt)
        new_context.user_id = fake.USER3_ID
        new_context.project_id = fake.USER3_ID

        # The opposite side of this test case is a "NotImplementedError:
        # Cannot load 'id' in the base class" being raised.
        # More detailed, in the try clause, if backup.create() failed
        # with DB exception, backup.id won't be assigned. However,
        # in the except clause, backup.destroy() is invoked to do cleanup,
        # which internally tries to access backup.id.
        self.assertRaises(db_exc.DBError, self.api.create,
                          context=new_context,
                          name="test_backup",
                          description="test backup description",
                          volume_id=volume_id,
                          container='volumebackups')

    @mock.patch.object(api.API, '_get_available_backup_service_host',
                       return_value='fake_host')
    @mock.patch.object(objects.Backup, '__init__',
                       side_effect=exception.InvalidInput(
                           reason='Failed to new'))
    def test_create_when_failed_to_new_backup_object(self, mock_new,
                                                     mock_get_service):
        volume_id = utils.create_volume(self.ctxt)['id']

        # The opposite side of this test case is that a "UnboundLocalError:
        # local variable 'backup' referenced before assignment" is raised.
        # More detailed, in the try clause, backup = objects.Backup(...)
        # raises exception, so 'backup' is not assigned. But in the except
        # clause, 'backup' is referenced to invoke cleanup methods.
        self.assertRaises(exception.InvalidInput, self.api.create,
                          context=self.ctxt,
                          name="test_backup",
                          description="test backup description",
                          volume_id=volume_id,
                          container='volumebackups')

    @mock.patch.object(api.API, '_get_available_backup_service_host',
                       return_value='fake_host')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.create_backup')
    def test_create_backup_from_snapshot_with_volume_in_use(
            self, mock_create, mock_get_service):
        self.ctxt.user_id = 'fake_user'
        self.ctxt.project_id = 'fake_project'
        volume_id = self._create_volume_db_entry(status='in-use')
        snapshot = self._create_snapshot_db_entry(volume_id=volume_id)
        backup = self.api.create(self.ctxt, None, None, volume_id, None,
                                 snapshot_id=snapshot.id)

        self.assertEqual(fields.BackupStatus.CREATING, backup.status)
        volume = objects.Volume.get_by_id(self.ctxt, volume_id)
        snapshot = objects.Snapshot.get_by_id(self.ctxt, snapshot.id)
        self.assertEqual(fields.SnapshotStatus.BACKING_UP, snapshot.status)
        self.assertEqual('in-use', volume.status)

    @mock.patch.object(api.API, '_get_available_backup_service_host',
                       return_value='fake_host')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.create_backup')
    @ddt.data(True, False)
    def test_create_backup_resource_status(self, is_snapshot, mock_create,
                                           mock_get_service):
        self.ctxt.user_id = 'fake_user'
        self.ctxt.project_id = 'fake_project'
        volume_id = self._create_volume_db_entry(status='available')
        snapshot = self._create_snapshot_db_entry(volume_id=volume_id)
        if is_snapshot:
            self.api.create(self.ctxt, None, None, volume_id, None,
                            snapshot_id=snapshot.id)
            volume = objects.Volume.get_by_id(self.ctxt, volume_id)
            snapshot = objects.Snapshot.get_by_id(self.ctxt, snapshot.id)

            self.assertEqual('backing-up', snapshot.status)
            self.assertEqual('available', volume.status)
        else:
            self.api.create(self.ctxt, None, None, volume_id, None)
            volume = objects.Volume.get_by_id(self.ctxt, volume_id)
            snapshot = objects.Snapshot.get_by_id(self.ctxt, snapshot.id)

            self.assertEqual('available', snapshot.status)
            self.assertEqual('backing-up', volume.status)

    @mock.patch('cinder.backup.api.API._get_available_backup_service_host')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.restore_backup')
    def test_restore_volume(self,
                            mock_rpcapi_restore,
                            mock_get_backup_host):
        volume_id = self._create_volume_db_entry(status='available',
                                                 size=1)
        backup = self._create_backup_db_entry(size=1,
                                              status='available')
        mock_get_backup_host.return_value = 'testhost'
        self.api.restore(self.ctxt, backup.id, volume_id)
        backup = objects.Backup.get_by_id(self.ctxt, backup.id)
        self.assertEqual(volume_id, backup.restore_volume_id)

    @mock.patch.object(objects.Backup, 'decode_record')
    @mock.patch.object(quota.QUOTAS, 'commit')
    @mock.patch.object(quota.QUOTAS, 'rollback')
    @mock.patch.object(quota.QUOTAS, 'reserve')
    def test__get_import_backup_invalid_backup(
            self, mock_reserve, mock_rollback, mock_commit, mock_decode):

        backup = self._create_backup_db_entry(size=1,
                                              status='available')
        mock_decode.return_value = {'id': backup.id,
                                    'project_id': backup.project_id,
                                    'user_id': backup.user_id,
                                    'volume_id': backup.volume_id,
                                    'size': 1}
        mock_reserve.return_value = 'fake_reservation'

        self.assertRaises(exception.InvalidBackup,
                          self.api._get_import_backup,
                          self.ctxt, 'fake_backup_url')
        mock_reserve.assert_called_with(
            self.ctxt, backups=1, backup_gigabytes=1)
        mock_rollback.assert_called_with(self.ctxt, "fake_reservation")

    @mock.patch('cinder.objects.BackupList.get_all_by_volume')
    @mock.patch.object(quota.QUOTAS, 'rollback')
    @mock.patch.object(quota.QUOTAS, 'reserve')
    def test_create_backup_failed_with_empty_backup_objects(
            self, mock_reserve, mock_rollback, mock_get_backups):
        backups = mock.Mock()
        backups.objects = []
        mock_get_backups.return_value = backups
        is_incremental = True
        self.ctxt.user_id = 'fake_user'
        self.ctxt.project_id = 'fake_project'
        mock_reserve.return_value = 'fake_reservation'

        volume_id = self._create_volume_db_entry(status='available',
                                                 host='testhost#rbd',
                                                 size=1,
                                                 project_id="vol_proj_id")
        self.assertRaises(exception.InvalidBackup,
                          self.api.create,
                          self.ctxt,
                          None, None,
                          volume_id, None,
                          incremental=is_incremental)
        mock_rollback.assert_called_with(self.ctxt, "fake_reservation")
        mock_get_backups.assert_called_once_with(
            self.ctxt, volume_id, 'vol_proj_id',
            filters={'project_id': 'fake_project'})

    @mock.patch('cinder.db.backup_get_all_by_volume',
                return_value=[v2_fakes.fake_backup('fake-1')])
    @mock.patch('cinder.backup.rpcapi.BackupAPI.create_backup')
    @mock.patch.object(api.API, '_get_available_backup_service_host',
                       return_value='fake_host')
    @mock.patch.object(quota.QUOTAS, 'rollback')
    @mock.patch.object(quota.QUOTAS, 'reserve')
    def test_create_backup_failed_with_backup_status_not_available(
            self, mock_reserve, mock_rollback, mock_get_service,
            mock_createi, mock_get_backups):

        is_incremental = True
        self.ctxt.user_id = 'fake_user'
        self.ctxt.project_id = 'fake_project'
        mock_reserve.return_value = 'fake_reservation'

        volume_id = self._create_volume_db_entry(status='available',
                                                 host='testhost#rbd',
                                                 size=1)
        self.assertRaises(exception.InvalidBackup,
                          self.api.create,
                          self.ctxt,
                          None, None,
                          volume_id, None,
                          incremental=is_incremental)
        mock_rollback.assert_called_with(self.ctxt, "fake_reservation")
