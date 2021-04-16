# Copyright 2021, Red Hat Inc.
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
"""Tests for User Facing Messages in Backup Operations."""

from unittest import mock

from cinder.backup import manager as backup_manager
from cinder import exception
from cinder.message import message_field
from cinder.scheduler import manager as sch_manager
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


class BackupUserMessagesTest(test.TestCase):

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager._run_backup')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    def test_backup_create_invalid_status(
            self, mock_notify, mock_working, mock_run,
            mock_msg_create, mock_get_vol, mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='available', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = {'status': 'backing-up'}.__getitem__
        mock_get_vol.return_value = mock_vol

        self.assertRaises(
            exception.InvalidBackup, manager.create_backup, fake_context,
            fake_backup)
        self.assertEqual(message_field.Action.BACKUP_CREATE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.BACKUP_INVALID_STATE)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager._run_backup')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    def test_backup_create_service_down(
            self, mock_notify, mock_working, mock_run, mock_msg_create,
            mock_get_vol, mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='creating', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = {'status': 'backing-up'}.__getitem__
        mock_get_vol.return_value = mock_vol
        mock_working.return_value = False

        mock_run.side_effect = exception.InvalidBackup(reason='test reason')
        self.assertRaises(
            exception.InvalidBackup, manager.create_backup, fake_context,
            fake_backup)
        self.assertEqual(message_field.Action.BACKUP_CREATE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.BACKUP_SERVICE_DOWN)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    @mock.patch(
        'cinder.backup.manager.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_cleanup_temp_volumes_snapshots_when_backup_created')
    def test_backup_create_device_error(
            self, mock_cleanup, mock_get_bak_dev, mock_get_conn, mock_notify,
            mock_working, mock_msg_create, mock_get_vol, mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='creating', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = {'status': 'backing-up'}.__getitem__
        mock_get_vol.return_value = mock_vol
        mock_working.return_value = True
        mock_get_bak_dev.side_effect = exception.InvalidVolume(
            reason="test reason")

        self.assertRaises(exception.InvalidVolume, manager.create_backup,
                          fake_context, fake_backup)
        self.assertEqual(message_field.Action.BACKUP_CREATE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.BACKUP_CREATE_DEVICE_ERROR)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    @mock.patch(
        'cinder.backup.manager.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_cleanup_temp_volumes_snapshots_when_backup_created')
    @mock.patch('cinder.backup.manager.BackupManager._attach_device')
    def test_backup_create_attach_error(
            self, mock_attach, mock_cleanup, mock_get_bak_dev, mock_get_conn,
            mock_notify, mock_working, mock_msg_create, mock_get_vol,
            mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='creating', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = {'status': 'backing-up'}.__getitem__
        mock_get_vol.return_value = mock_vol
        mock_working.return_value = True
        mock_attach.side_effect = exception.InvalidVolume(reason="test reason")

        self.assertRaises(exception.InvalidVolume, manager.create_backup,
                          fake_context, fake_backup)
        self.assertEqual(message_field.Action.BACKUP_CREATE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.ATTACH_ERROR)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    @mock.patch(
        'cinder.backup.manager.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_cleanup_temp_volumes_snapshots_when_backup_created')
    @mock.patch('cinder.backup.manager.BackupManager._attach_device')
    @mock.patch(
        'cinder.tests.unit.backup.fake_service.FakeBackupService.backup')
    @mock.patch('cinder.backup.manager.open')
    @mock.patch('cinder.backup.manager.BackupManager._detach_device')
    def test_backup_create_driver_error(
            self, mock_detach, mock_open, mock_backup, mock_attach,
            mock_cleanup, mock_get_bak_dev, mock_get_conn, mock_notify,
            mock_working, mock_msg_create, mock_get_vol, mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='creating', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = {'status': 'backing-up'}.__getitem__
        mock_get_vol.return_value = mock_vol
        mock_working.return_value = True
        mock_attach.return_value = {'device': {'path': '/dev/sdb'}}
        mock_backup.side_effect = exception.InvalidBackup(reason="test reason")

        self.assertRaises(exception.InvalidBackup, manager.create_backup,
                          fake_context, fake_backup)
        self.assertEqual(message_field.Action.BACKUP_CREATE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.BACKUP_CREATE_DRIVER_ERROR)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    @mock.patch(
        'cinder.backup.manager.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_cleanup_temp_volumes_snapshots_when_backup_created')
    @mock.patch('cinder.backup.manager.BackupManager._attach_device')
    @mock.patch(
        'cinder.tests.unit.backup.fake_service.FakeBackupService.backup')
    @mock.patch('cinder.backup.manager.open')
    @mock.patch('cinder.backup.manager.BackupManager._detach_device')
    def test_backup_create_detach_error(
            self, mock_detach, mock_open, mock_backup, mock_attach,
            mock_cleanup, mock_get_bak_dev, mock_get_conn, mock_notify,
            mock_working, mock_msg_create, mock_get_vol, mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='creating', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = {'status': 'backing-up'}.__getitem__
        mock_get_vol.return_value = mock_vol
        mock_working.return_value = True
        mock_attach.return_value = {'device': {'path': '/dev/sdb'}}
        mock_detach.side_effect = exception.InvalidVolume(reason="test reason")

        self.assertRaises(exception.InvalidVolume, manager.create_backup,
                          fake_context, fake_backup)
        self.assertEqual(message_field.Action.BACKUP_CREATE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.DETACH_ERROR)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    @mock.patch(
        'cinder.backup.manager.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_backup_device')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_cleanup_temp_volumes_snapshots_when_backup_created')
    @mock.patch('cinder.backup.manager.BackupManager._attach_device')
    @mock.patch(
        'cinder.tests.unit.backup.fake_service.FakeBackupService.backup')
    @mock.patch('cinder.backup.manager.open')
    @mock.patch('cinder.backup.manager.BackupManager._detach_device')
    def test_backup_create_cleanup_error(
            self, mock_detach, mock_open, mock_backup, mock_attach,
            mock_cleanup, mock_get_bak_dev, mock_get_conn, mock_notify,
            mock_working, mock_msg_create, mock_get_vol, mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='creating', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = {'status': 'backing-up'}.__getitem__
        mock_get_vol.return_value = mock_vol
        mock_working.return_value = True
        mock_attach.return_value = {'device': {'path': '/dev/sdb'}}
        mock_cleanup.side_effect = exception.InvalidVolume(
            reason="test reason")

        self.assertRaises(exception.InvalidVolume, manager.create_backup,
                          fake_context, fake_backup)
        self.assertEqual(message_field.Action.BACKUP_CREATE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.BACKUP_CREATE_CLEANUP_ERROR)

    @mock.patch('cinder.scheduler.host_manager.HostManager.'
                '_get_available_backup_service_host')
    @mock.patch('cinder.volume.volume_utils.update_backup_error')
    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.db.volume_get')
    @mock.patch('cinder.message.api.API.create')
    def test_backup_create_scheduling_error(
            self, mock_msg_create, mock_get_vol, mock_vol_update,
            mock_update_error, mock_get_backup_host):
        manager = sch_manager.SchedulerManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(id=fake.BACKUP_ID,
                                     volume_id=fake.VOLUME_ID)
        mock_get_vol.return_value = mock.MagicMock()
        exception.ServiceNotFound(service_id='cinder-backup')
        mock_get_backup_host.side_effect = exception.ServiceNotFound(
            service_id='cinder-backup')

        manager.create_backup(fake_context, fake_backup)
        mock_msg_create.assert_called_once_with(
            fake_context,
            action=message_field.Action.BACKUP_CREATE,
            resource_type=message_field.Resource.VOLUME_BACKUP,
            resource_uuid=fake_backup.id,
            detail=message_field.Detail.BACKUP_SCHEDULE_ERROR)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch(
        'cinder.backup.manager.BackupManager._notify_about_backup_usage')
    def test_backup_delete_invalid_state(
            self, mock_notify, mock_msg_create, mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='available', volume_id=fake.VOLUME_ID,
            snapshot_id=None)

        self.assertRaises(
            exception.InvalidBackup, manager.delete_backup, fake_context,
            fake_backup)
        self.assertEqual(message_field.Action.BACKUP_DELETE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.BACKUP_INVALID_STATE)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch(
        'cinder.backup.manager.BackupManager._notify_about_backup_usage')
    def test_backup_delete_service_down(
            self, mock_notify, mock_working, mock_msg_create,
            mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='deleting', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        mock_working.return_value = False

        self.assertRaises(
            exception.InvalidBackup, manager.delete_backup, fake_context,
            fake_backup)
        self.assertEqual(message_field.Action.BACKUP_DELETE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.BACKUP_SERVICE_DOWN)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager._is_our_backup')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch(
        'cinder.backup.manager.BackupManager._notify_about_backup_usage')
    def test_backup_delete_driver_error(
            self, mock_notify, mock_working, mock_our_back,
            mock_msg_create, mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='deleting', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        fake_backup.__getitem__.side_effect = (
            {'display_name': 'fail_on_delete'}.__getitem__)
        mock_working.return_value = True
        mock_our_back.return_value = True

        self.assertRaises(
            IOError, manager.delete_backup, fake_context,
            fake_backup)
        self.assertEqual(message_field.Action.BACKUP_DELETE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.BACKUP_DELETE_DRIVER_ERROR)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    def test_backup_restore_volume_invalid_state(
            self, mock_notify, mock_msg_create, mock_get_vol,
            mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='creating', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        fake_backup.__getitem__.side_effect = (
            {'status': 'restoring', 'size': 1}.__getitem__)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = (
            {'id': fake.VOLUME_ID, 'status': 'available',
             'size': 1}.__getitem__)
        mock_get_vol.return_value = mock_vol

        self.assertRaises(
            exception.InvalidVolume, manager.restore_backup,
            fake_context, fake_backup, fake.VOLUME_ID)
        mock_msg_create.assert_called_once_with(
            fake_context,
            action=message_field.Action.BACKUP_RESTORE,
            resource_type=message_field.Resource.VOLUME_BACKUP,
            resource_uuid=mock_vol.id,
            detail=message_field.Detail.VOLUME_INVALID_STATE)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    def test_backup_restore_backup_invalid_state(
            self, mock_notify, mock_msg_create, mock_get_vol,
            mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='creating', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        fake_backup.__getitem__.side_effect = (
            {'status': 'available', 'size': 1}.__getitem__)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = (
            {'status': 'restoring-backup', 'size': 1}.__getitem__)
        mock_get_vol.return_value = mock_vol

        self.assertRaises(
            exception.InvalidBackup, manager.restore_backup,
            fake_context, fake_backup, fake.VOLUME_ID)
        self.assertEqual(message_field.Action.BACKUP_RESTORE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.BACKUP_INVALID_STATE)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager._is_our_backup')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    @mock.patch(
        'cinder.backup.manager.volume_utils.brick_get_connector_properties')
    @mock.patch(
        'cinder.volume.rpcapi.VolumeAPI.secure_file_operations_enabled')
    @mock.patch('cinder.backup.manager.BackupManager._attach_device')
    @mock.patch('cinder.backup.manager.BackupManager._detach_device')
    def test_backup_restore_attach_error(
            self, mock_detach, mock_attach, mock_sec_opts, mock_get_conn,
            mock_notify, mock_working, mock_our_back, mock_msg_create,
            mock_get_vol, mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='creating', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        fake_backup.__getitem__.side_effect = (
            {'status': 'restoring', 'size': 1}.__getitem__)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = (
            {'status': 'restoring-backup', 'size': 1}.__getitem__)
        mock_get_vol.return_value = mock_vol
        mock_working.return_value = True
        mock_our_back.return_value = True
        mock_attach.side_effect = exception.InvalidBackup(
            reason="test reason")

        self.assertRaises(
            exception.InvalidBackup, manager.restore_backup,
            fake_context, fake_backup, fake.VOLUME_ID)
        self.assertEqual(message_field.Action.BACKUP_RESTORE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.ATTACH_ERROR)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager._is_our_backup')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    @mock.patch(
        'cinder.backup.manager.volume_utils.brick_get_connector_properties')
    @mock.patch(
        'cinder.volume.rpcapi.VolumeAPI.secure_file_operations_enabled')
    @mock.patch('cinder.backup.manager.BackupManager._attach_device')
    @mock.patch('cinder.backup.manager.open')
    @mock.patch(
        'cinder.tests.unit.backup.fake_service.FakeBackupService.restore')
    @mock.patch('cinder.backup.manager.BackupManager._detach_device')
    def test_backup_restore_driver_error(
            self, mock_detach, mock_restore, mock_open, mock_attach,
            mock_sec_opts, mock_get_conn, mock_notify, mock_working,
            mock_our_back, mock_msg_create, mock_get_vol, mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='creating', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        fake_backup.__getitem__.side_effect = (
            {'status': 'restoring', 'size': 1}.__getitem__)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = (
            {'status': 'restoring-backup', 'size': 1}.__getitem__)
        mock_get_vol.return_value = mock_vol
        mock_working.return_value = True
        mock_our_back.return_value = True
        mock_attach.return_value = {'device': {'path': '/dev/sdb'}}
        mock_restore.side_effect = exception.InvalidBackup(
            reason="test reason")

        self.assertRaises(
            exception.InvalidBackup, manager.restore_backup,
            fake_context, fake_backup, fake.VOLUME_ID)
        self.assertEqual(message_field.Action.BACKUP_RESTORE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.BACKUP_RESTORE_ERROR)

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    @mock.patch('cinder.message.api.API.create_from_request_context')
    @mock.patch('cinder.backup.manager.BackupManager._is_our_backup')
    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch('cinder.backup.manager.BackupManager.'
                '_notify_about_backup_usage')
    @mock.patch(
        'cinder.backup.manager.volume_utils.brick_get_connector_properties')
    @mock.patch(
        'cinder.volume.rpcapi.VolumeAPI.secure_file_operations_enabled')
    @mock.patch('cinder.backup.manager.BackupManager._attach_device')
    @mock.patch('cinder.backup.manager.open')
    @mock.patch(
        'cinder.tests.unit.backup.fake_service.FakeBackupService.restore')
    @mock.patch('cinder.backup.manager.BackupManager._detach_device')
    def test_backup_restore_detach_error(
            self, mock_detach, mock_restore, mock_open, mock_attach,
            mock_sec_opts, mock_get_conn, mock_notify, mock_working,
            mock_our_back, mock_msg_create, mock_get_vol, mock_vol_update):
        manager = backup_manager.BackupManager()
        fake_context = mock.MagicMock()
        fake_backup = mock.MagicMock(
            id=fake.BACKUP_ID, status='creating', volume_id=fake.VOLUME_ID,
            snapshot_id=None)
        fake_backup.__getitem__.side_effect = (
            {'status': 'restoring', 'size': 1}.__getitem__)
        mock_vol = mock.MagicMock()
        mock_vol.__getitem__.side_effect = (
            {'status': 'restoring-backup', 'size': 1}.__getitem__)
        mock_get_vol.return_value = mock_vol
        mock_working.return_value = True
        mock_our_back.return_value = True
        mock_attach.return_value = {'device': {'path': '/dev/sdb'}}
        mock_detach.side_effect = exception.InvalidBackup(
            reason="test reason")

        self.assertRaises(
            exception.InvalidBackup, manager.restore_backup,
            fake_context, fake_backup, fake.VOLUME_ID)
        self.assertEqual(message_field.Action.BACKUP_RESTORE,
                         fake_context.message_action)
        self.assertEqual(message_field.Resource.VOLUME_BACKUP,
                         fake_context.message_resource_type)
        self.assertEqual(fake_backup.id,
                         fake_context.message_resource_id)
        mock_msg_create.assert_called_with(
            fake_context,
            detail=message_field.Detail.DETACH_ERROR)
