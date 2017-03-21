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

import mock

from cinder import exception
from cinder.message import message_field
from cinder.tests.unit import volume as base
from cinder.volume import manager as vol_manager


class VolumeManagerTestCase(base.BaseVolumeTestCase):

    @mock.patch('cinder.message.api.API.create')
    @mock.patch('cinder.utils.require_driver_initialized')
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
    @mock.patch('cinder.utils.require_driver_initialized')
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
    @mock.patch('cinder.utils.require_driver_initialized')
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
    @mock.patch('cinder.utils.require_driver_initialized')
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
