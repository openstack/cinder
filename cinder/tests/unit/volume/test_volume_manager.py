# Copyright 2019, Red Hat Inc.
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
"""Tests for Volume Manager Code."""

from unittest import mock

from cinder import exception
from cinder.message import message_field
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import volume as base
from cinder.volume import manager as vol_manager


class VolumeManagerTestCase(base.BaseVolumeTestCase):

    @mock.patch('cinder.message.api.API.create')
    @mock.patch('cinder.volume.volume_utils.require_driver_initialized')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                '_notify_about_snapshot_usage')
    def test_create_snapshot_driver_not_initialized_generates_user_message(
            self, fake_notify, fake_init, fake_msg_create):
        manager = vol_manager.VolumeManager()

        fake_init.side_effect = exception.CinderException()
        fake_snapshot = mock.MagicMock(id='22')
        fake_context = mock.MagicMock()
        fake_context.elevated.return_value = fake_context

        ex = self.assertRaises(exception.CinderException,
                               manager.create_snapshot,
                               fake_context,
                               fake_snapshot)

        # make sure a user message was generated
        fake_msg_create.assert_called_once_with(
            fake_context,
            action=message_field.Action.SNAPSHOT_CREATE,
            resource_type=message_field.Resource.VOLUME_SNAPSHOT,
            resource_uuid=fake_snapshot['id'],
            exception=ex,
            detail=message_field.Detail.SNAPSHOT_CREATE_ERROR)

    @mock.patch('cinder.message.api.API.create')
    @mock.patch('cinder.volume.volume_utils.require_driver_initialized')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                '_notify_about_snapshot_usage')
    def test_create_snapshot_metadata_update_failure_generates_user_message(
            self, fake_notify, fake_init, fake_msg_create):
        manager = vol_manager.VolumeManager()

        fake_driver = mock.MagicMock()
        fake_driver.create_snapshot.return_value = False
        manager.driver = fake_driver

        fake_vol_ref = mock.MagicMock()
        fake_vol_ref.bootable.return_value = True
        fake_db = mock.MagicMock()
        fake_db.volume_get.return_value = fake_vol_ref
        fake_exp = exception.CinderException()
        fake_db.volume_glance_metadata_copy_to_snapshot.side_effect = fake_exp
        manager.db = fake_db

        fake_snapshot = mock.MagicMock(id='86')
        fake_context = mock.MagicMock()
        fake_context.elevated.return_value = fake_context

        self.assertRaises(exception.CinderException,
                          manager.create_snapshot,
                          fake_context,
                          fake_snapshot)

        # make sure a user message was generated
        fake_msg_create.assert_called_once_with(
            fake_context,
            action=message_field.Action.SNAPSHOT_CREATE,
            resource_type=message_field.Resource.VOLUME_SNAPSHOT,
            resource_uuid=fake_snapshot['id'],
            exception=fake_exp,
            detail=message_field.Detail.SNAPSHOT_UPDATE_METADATA_FAILED)

    @mock.patch('cinder.message.api.API.create')
    @mock.patch('cinder.volume.volume_utils.require_driver_initialized')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                '_notify_about_snapshot_usage')
    def test_delete_snapshot_when_busy_generates_user_message(
            self, fake_notify, fake_init, fake_msg_create):
        manager = vol_manager.VolumeManager()

        fake_snapshot = mock.MagicMock(id='0', project_id='1')
        fake_context = mock.MagicMock()
        fake_context.elevated.return_value = fake_context
        fake_exp = exception.SnapshotIsBusy(snapshot_name='Fred')
        fake_init.side_effect = fake_exp

        manager.delete_snapshot(fake_context, fake_snapshot)

        # make sure a user message was generated
        fake_msg_create.assert_called_once_with(
            fake_context,
            action=message_field.Action.SNAPSHOT_DELETE,
            resource_type=message_field.Resource.VOLUME_SNAPSHOT,
            resource_uuid=fake_snapshot['id'],
            exception=fake_exp)

    @mock.patch('cinder.message.api.API.create')
    @mock.patch('cinder.volume.volume_utils.require_driver_initialized')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                '_notify_about_snapshot_usage')
    def test_delete_snapshot_general_exception_generates_user_message(
            self, fake_notify, fake_init, fake_msg_create):
        manager = vol_manager.VolumeManager()

        fake_snapshot = mock.MagicMock(id='0', project_id='1')
        fake_context = mock.MagicMock()
        fake_context.elevated.return_value = fake_context

        class LocalException(Exception):
            pass

        fake_exp = LocalException()
        # yeah, this isn't where it would be coming from in real life,
        # but it saves mocking out a bunch more stuff
        fake_init.side_effect = fake_exp

        self.assertRaises(LocalException,
                          manager.delete_snapshot,
                          fake_context,
                          fake_snapshot)

        # make sure a user message was generated
        fake_msg_create.assert_called_once_with(
            fake_context,
            action=message_field.Action.SNAPSHOT_DELETE,
            resource_type=message_field.Resource.VOLUME_SNAPSHOT,
            resource_uuid=fake_snapshot['id'],
            exception=fake_exp,
            detail=message_field.Detail.SNAPSHOT_DELETE_ERROR)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI')
    def test_attach_volume_local(self, mock_api):
        manager = vol_manager.VolumeManager()

        mock_initialize = self.mock_object(manager, 'initialize_connection')
        mock_connect = self.mock_object(manager, '_connect_device')

        ctxt = mock.sentinel.context
        vol = fake_volume.fake_volume_obj(ctxt)

        result = manager._attach_volume(ctxt, vol, mock.sentinel.properties,
                                        remote=False)

        mock_api.assert_not_called()
        mock_initialize.assert_called_once_with(ctxt, vol,
                                                mock.sentinel.properties)
        mock_connect.assert_called_once_with(mock_initialize.return_value)
        self.assertEqual(mock_connect.return_value, result)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI')
    def test_attach_volume_remote(self, mock_api):
        mock_rpc = mock_api.return_value

        manager = vol_manager.VolumeManager()
        mock_connect = self.mock_object(manager, '_connect_device')
        mock_initialize = self.mock_object(manager, 'initialize_connection')

        ctxt = mock.sentinel.context
        vol = fake_volume.fake_volume_obj(ctxt)

        result = manager._attach_volume(ctxt, vol, mock.sentinel.properties,
                                        remote=True)
        mock_api.assert_called_once_with()
        mock_initialize.assert_not_called()
        mock_rpc.initialize_connection.assert_called_once_with(
            ctxt, vol, mock.sentinel.properties)
        mock_connect.assert_called_once_with(
            mock_rpc.initialize_connection.return_value)
        self.assertEqual(mock_connect.return_value, result)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI')
    def test_attach_volume_fail_connect(self, mock_api):
        mock_initialize = mock_api.return_value.initialize_connection

        manager = vol_manager.VolumeManager()
        mock_detach = self.mock_object(manager, '_detach_volume')
        mock_connect = self.mock_object(manager, '_connect_device',
                                        side_effect=ValueError)

        ctxt = mock.sentinel.context
        vol = fake_volume.fake_volume_obj(ctxt)

        self.assertRaises(ValueError,
                          manager._attach_volume,
                          ctxt, vol, mock.sentinel.properties,
                          mock.sentinel.remote)

        mock_initialize.assert_called_once_with(ctxt, vol,
                                                mock.sentinel.properties)
        mock_connect.assert_called_once_with(mock_initialize.return_value)
        mock_detach.assert_called_once_with(
            ctxt, None, vol, mock.sentinel.properties, force=True,
            remote=mock.sentinel.remote)

    @mock.patch('cinder.volume.volume_utils.brick_attach_volume_encryptor')
    @mock.patch('cinder.volume.volume_types.is_encrypted')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI')
    def test_attach_volume_fail_decrypt(self, mock_api, mock_is_encrypted,
                                        mock_attach_encryptor):
        mock_initialize = mock_api.return_value.initialize_connection

        manager = vol_manager.VolumeManager()
        mock_detach = self.mock_object(manager, '_detach_volume')
        mock_connect = self.mock_object(manager, '_connect_device')
        mock_db = self.mock_object(manager.db,
                                   'volume_encryption_metadata_get')
        mock_attach_encryptor.side_effect = ValueError

        ctxt = mock.Mock()
        vol = fake_volume.fake_volume_obj(ctxt)

        self.assertRaises(ValueError,
                          manager._attach_volume,
                          ctxt, vol, mock.sentinel.properties,
                          mock.sentinel.remote, attach_encryptor=True)

        mock_initialize.assert_called_once_with(ctxt, vol,
                                                mock.sentinel.properties)
        mock_connect.assert_called_once_with(mock_initialize.return_value)
        mock_is_encrypted.assert_called_once_with(ctxt, vol.volume_type_id)
        mock_db.assert_called_once_with(ctxt.elevated.return_value, vol.id)
        mock_attach_encryptor.assert_called_once_with(
            ctxt, mock_connect.return_value, mock_db.return_value)

        mock_detach.assert_called_once_with(
            ctxt, mock_connect.return_value, vol, mock.sentinel.properties,
            force=True, remote=mock.sentinel.remote)

    @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs')
    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs',
                return_value={'qos_specs': None})
    def test_parse_connection_options_cacheable(self,
                                                mock_get_qos,
                                                mock_get_extra_specs):
        ctxt = mock.Mock()
        manager = vol_manager.VolumeManager()
        vol = fake_volume.fake_volume_obj(ctxt)
        vol.volume_type_id = fake.VOLUME_TYPE_ID

        # no 'cacheable' set by driver, should be extra spec
        conn_info = {"data": {}}
        mock_get_extra_specs.return_value = '<is> True'
        manager._parse_connection_options(ctxt, vol, conn_info)
        self.assertIn('cacheable', conn_info['data'])
        self.assertIs(conn_info['data']['cacheable'], True)

        # driver sets 'cacheable' False, should override extra spec
        conn_info = {"data": {"cacheable": False}}
        mock_get_extra_specs.return_value = '<is> True'
        manager._parse_connection_options(ctxt, vol, conn_info)
        self.assertIn('cacheable', conn_info['data'])
        self.assertIs(conn_info['data']['cacheable'], False)

        # driver sets 'cacheable' True, nothing in extra spec,
        # extra spec should override driver
        conn_info = {"data": {"cacheable": True}}
        mock_get_extra_specs.return_value = None
        manager._parse_connection_options(ctxt, vol, conn_info)
        self.assertIn('cacheable', conn_info['data'])
        self.assertIs(conn_info['data']['cacheable'], False)

        # driver sets 'cacheable' True, extra spec has False,
        # extra spec should override driver
        conn_info = {"data": {"cacheable": True}}
        mock_get_extra_specs.return_value = '<is> False'
        manager._parse_connection_options(ctxt, vol, conn_info)
        self.assertIn('cacheable', conn_info['data'])
        self.assertIs(conn_info['data']['cacheable'], False)
