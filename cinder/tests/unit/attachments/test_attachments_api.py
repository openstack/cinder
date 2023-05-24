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

from unittest import mock

from cinder.compute import nova
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit import utils as tests_utils
from cinder.volume import api as volume_api
from cinder.volume import configuration as conf


class AttachmentManagerTestCase(test.TestCase):
    """Attachment related test for volume/api.py."""

    def setUp(self):
        """Setup test class."""
        super(AttachmentManagerTestCase, self).setUp()
        self.configuration = mock.Mock(conf.Configuration)
        self.context = context.get_admin_context()
        self.context.user_id = fake.USER_ID
        self.project_id = fake.PROJECT3_ID
        self.context.project_id = self.project_id
        self.volume_api = volume_api.API()
        self.user_context = context.RequestContext(
            user_id=fake.USER_ID,
            project_id=fake.PROJECT3_ID)

    def test_attachment_create_no_connector(self):
        """Test attachment_create no connector."""
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        aref = self.volume_api.attachment_create(self.context,
                                                 vref,
                                                 fake.UUID2)
        self.assertEqual(fake.UUID2, aref.instance_uuid)
        self.assertIsNone(aref.attach_time)
        self.assertEqual('reserved', aref.attach_status)
        self.assertEqual('null', aref.attach_mode)
        self.assertEqual(vref.id, aref.volume_id)
        self.assertEqual({}, aref.connection_info)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_update')
    def test_attachment_create_with_connector(self,
                                              mock_rpc_attachment_update):
        """Test attachment_create with connector."""
        volume_params = {'status': 'available'}
        connection_info = {'fake_key': 'fake_value',
                           'fake_key2': ['fake_value1', 'fake_value2']}
        mock_rpc_attachment_update.return_value = connection_info

        vref = tests_utils.create_volume(self.context, **volume_params)
        connector = {'fake': 'connector'}
        attachment = self.volume_api.attachment_create(self.context,
                                                       vref,
                                                       fake.UUID2,
                                                       connector)
        mock_rpc_attachment_update.assert_called_once_with(self.context,
                                                           mock.ANY,
                                                           connector,
                                                           mock.ANY)
        new_attachment = objects.VolumeAttachment.get_by_id(self.context,
                                                            attachment.id)
        self.assertEqual(connection_info, new_attachment.connection_info)

    @mock.patch.object(volume_api.API, 'attachment_deletion_allowed')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_delete')
    def test_attachment_delete_reserved(self,
                                        mock_rpc_attachment_delete,
                                        mock_allowed):
        """Test attachment_delete with reserved."""
        mock_allowed.return_value = None
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        aref = self.volume_api.attachment_create(self.context,
                                                 vref,
                                                 fake.UUID2)
        aobj = objects.VolumeAttachment.get_by_id(self.context,
                                                  aref.id)
        self.assertEqual('reserved', aref.attach_status)
        self.assertEqual(vref.id, aref.volume_id)
        self.volume_api.attachment_delete(self.context,
                                          aobj)
        mock_allowed.assert_called_once_with(self.context, aobj)

        # Since it's just reserved and never finalized, we should never make an
        # rpc call
        mock_rpc_attachment_delete.assert_not_called()

    @mock.patch.object(volume_api.API, 'attachment_deletion_allowed')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_delete')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_update')
    def test_attachment_create_update_and_delete(
            self,
            mock_rpc_attachment_update,
            mock_rpc_attachment_delete,
            mock_allowed):
        """Test attachment_delete."""
        mock_allowed.return_value = None
        volume_params = {'status': 'available'}
        connection_info = {'fake_key': 'fake_value',
                           'fake_key2': ['fake_value1', 'fake_value2']}
        mock_rpc_attachment_update.return_value = connection_info

        vref = tests_utils.create_volume(self.context, **volume_params)
        aref = self.volume_api.attachment_create(self.context,
                                                 vref,
                                                 fake.UUID2)
        aref = objects.VolumeAttachment.get_by_id(self.context,
                                                  aref.id)
        vref = objects.Volume.get_by_id(self.context,
                                        vref.id)

        connector = {'fake': 'connector',
                     'host': 'somehost'}
        self.volume_api.attachment_update(self.context,
                                          aref,
                                          connector)
        aref = objects.VolumeAttachment.get_by_id(self.context,
                                                  aref.id)
        self.assertEqual(connection_info, aref.connection_info)
        # We mock the actual call that updates the status
        # so force it here
        values = {'volume_id': vref.id,
                  'volume_host': vref.host,
                  'attach_status': 'attached',
                  'instance_uuid': fake.UUID2}
        aref = db.volume_attach(self.context, values)

        aref = objects.VolumeAttachment.get_by_id(self.context,
                                                  aref.id)
        self.assertEqual(vref.id, aref.volume_id)
        self.volume_api.attachment_delete(self.context,
                                          aref)

        mock_allowed.assert_called_once_with(self.context, aref)
        mock_rpc_attachment_delete.assert_called_once_with(self.context,
                                                           aref.id,
                                                           mock.ANY)

    def test_additional_attachment_create_no_connector(self):
        """Test attachment_create no connector."""
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        aref = self.volume_api.attachment_create(self.context,
                                                 vref,
                                                 fake.UUID2)
        self.assertEqual(fake.UUID2, aref.instance_uuid)
        self.assertIsNone(aref.attach_time)
        self.assertEqual('reserved', aref.attach_status)
        self.assertEqual('null', aref.attach_mode)
        self.assertEqual(vref.id, aref.volume_id)
        self.assertEqual({}, aref.connection_info)

        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attachment_create,
                          self.context,
                          vref,
                          fake.UUID1)
        self.volume_api.attachment_create(self.context,
                                          vref,
                                          fake.UUID2)
        vref = objects.Volume.get_by_id(self.context,
                                        vref.id)
        self.assertEqual(2, len(vref.volume_attachment))

    @mock.patch.object(volume_api.API, 'attachment_deletion_allowed')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_update')
    def test_attachment_create_reserve_delete(
            self,
            mock_rpc_attachment_update,
            mock_allowed):
        mock_allowed.return_value = None
        volume_params = {'status': 'available'}
        connector = {
            "initiator": "iqn.1993-08.org.debian:01:cad181614cec",
            "ip": "192.168.1.20",
            "platform": "x86_64",
            "host": "tempest-1",
            "os_type": "linux2",
            "multipath": False}

        connection_info = {'fake_key': 'fake_value',
                           'fake_key2': ['fake_value1', 'fake_value2']}
        mock_rpc_attachment_update.return_value = connection_info

        vref = tests_utils.create_volume(self.context, **volume_params)
        aref = self.volume_api.attachment_create(self.context,
                                                 vref,
                                                 fake.UUID2,
                                                 connector=connector)
        vref = objects.Volume.get_by_id(self.context,
                                        vref.id)
        # Need to set the status here because our mock isn't doing it for us
        vref.status = 'in-use'
        vref.save()

        # Now a second attachment acting as a reserve
        self.volume_api.attachment_create(self.context,
                                          vref,
                                          fake.UUID2)

        # We should now be able to delete the original attachment that gave us
        # 'in-use' status, and in turn we should revert to the outstanding
        # attachments reserve
        self.volume_api.attachment_delete(self.context,
                                          aref)
        mock_allowed.assert_called_once_with(self.context, aref)
        vref = objects.Volume.get_by_id(self.context,
                                        vref.id)
        self.assertEqual('reserved', vref.status)

    @mock.patch.object(volume_api.API, 'attachment_deletion_allowed')
    def test_reserve_reserve_delete(self, mock_allowed):
        """Test that we keep reserved status across multiple reserves."""
        mock_allowed.return_value = None
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        aref = self.volume_api.attachment_create(self.context,
                                                 vref,
                                                 fake.UUID2)
        vref = objects.Volume.get_by_id(self.context,
                                        vref.id)
        self.assertEqual('reserved', vref.status)

        self.volume_api.attachment_create(self.context,
                                          vref,
                                          fake.UUID2)
        vref = objects.Volume.get_by_id(self.context,
                                        vref.id)
        self.assertEqual('reserved', vref.status)
        self.volume_api.attachment_delete(self.context,
                                          aref)
        mock_allowed.assert_called_once_with(self.context, aref)
        vref = objects.Volume.get_by_id(self.context,
                                        vref.id)
        self.assertEqual('reserved', vref.status)
        self.assertEqual(1, len(vref.volume_attachment))

    def test_attachment_create_readonly_volume(self):
        """Test attachment_create on a readonly volume."""
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        self.volume_api.update_readonly_flag(self.context, vref, True)
        aref = self.volume_api.attachment_create(self.context,
                                                 vref,
                                                 fake.UUID2)
        self.assertEqual(fake.UUID2, aref.instance_uuid)
        self.assertIsNone(aref.attach_time)
        self.assertEqual('reserved', aref.attach_status)
        self.assertEqual('ro', aref.attach_mode)
        self.assertEqual(vref.id, aref.volume_id)
        self.assertEqual({}, aref.connection_info)

    def test_attachment_create_volume_in_error_state(self):
        """Test attachment_create volume in error state."""
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        vref.status = "error"
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attachment_create,
                          self.context,
                          vref,
                          fake.UUID2)

    def test_attachment_update_volume_in_error_state(self):
        """Test attachment_update volumem in error state."""
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        aref = self.volume_api.attachment_create(self.context,
                                                 vref,
                                                 fake.UUID2)
        self.assertEqual(fake.UUID2, aref.instance_uuid)
        self.assertIsNone(aref.attach_time)
        self.assertEqual('reserved', aref.attach_status)
        self.assertEqual(vref.id, aref.volume_id)
        self.assertEqual({}, aref.connection_info)
        vref.status = 'error'
        vref.save()
        connector = {'fake': 'connector',
                     'host': 'somehost'}
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attachment_update,
                          self.context,
                          aref,
                          connector)

    @mock.patch('cinder.db.sqlalchemy.api.volume_attachment_update',
                return_value={})
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_update',
                return_value={})
    @mock.patch.object(db.sqlalchemy.api, '_volume_type_get',
                       v2_fakes.fake_volume_type_get)
    def test_attachment_update_duplicate(self, mock_va_update, mock_db_upd):
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context,
                                         deleted=0,
                                         **volume_params)

        tests_utils.attach_volume(self.context,
                                  vref.id,
                                  fake.UUID1,
                                  'somehost',
                                  'somemountpoint')

        # Update volume with another attachment
        tests_utils.attach_volume(self.context,
                                  vref.id,
                                  fake.UUID2,
                                  'somehost2',
                                  'somemountpoint2')
        vref.refresh()

        # This attachment will collide with the first
        connector = {'host': 'somehost'}
        vref.volume_attachment[0]['connector'] = {'host': 'somehost'}
        vref.volume_attachment[0]['connection_info'] = {'c': 'd'}
        with mock.patch('cinder.objects.Volume.get_by_id', return_value=vref):
            with mock.patch.object(self.volume_api.volume_rpcapi,
                                   'attachment_update') as m_au:
                self.assertRaises(exception.InvalidVolume,
                                  self.volume_api.attachment_update,
                                  self.context,
                                  vref.volume_attachment[1],
                                  connector)
                m_au.assert_not_called()
        mock_va_update.assert_not_called()
        mock_db_upd.assert_not_called()

    def test_attachment_create_creating_volume(self):
        """Test attachment_create on a creating volume."""
        volume_params = {'status': 'creating'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attachment_create,
                          self.context,
                          vref,
                          fake.UUID1)

    def _get_attachment(self, with_instance_id=True):
        volume = fake_volume.fake_volume_obj(self.context, id=fake.VOLUME_ID)
        volume.volume_attachment = objects.VolumeAttachmentList()
        attachment = fake_volume.volume_attachment_ovo(
            self.context,
            volume_id=fake.VOLUME_ID,
            instance_uuid=fake.INSTANCE_ID if with_instance_id else None,
            connection_info='{"a": 1}')
        attachment.volume = volume
        return attachment

    @mock.patch('cinder.compute.nova.API.get_server_volume')
    def test_attachment_deletion_allowed_service_call(self, mock_get_server):
        """Service calls are never redirected."""
        self.context.service_roles = ['reader', 'service']
        attachment = self._get_attachment()
        self.volume_api.attachment_deletion_allowed(self.context, attachment)
        mock_get_server.assert_not_called()

    @mock.patch('cinder.compute.nova.API.get_server_volume')
    def test_attachment_deletion_allowed_service_call_different_service_name(
            self, mock_get_server):
        """Service calls are never redirected and role can be different.

        In this test we support 2 different service roles, the standard service
        and a custom one called captain_awesome, and passing the custom one
        works as expected.
        """
        self.override_config('service_token_roles',
                             ['service', 'captain_awesome'],
                             group='keystone_authtoken')

        self.context.service_roles = ['reader', 'captain_awesome']
        attachment = self._get_attachment()
        self.volume_api.attachment_deletion_allowed(self.context, attachment)
        mock_get_server.assert_not_called()

    @mock.patch('cinder.compute.nova.API.get_server_volume')
    def test_attachment_deletion_allowed_no_instance(self, mock_get_server):
        """Attachments with no instance id are never redirected."""
        attachment = self._get_attachment(with_instance_id=False)
        self.volume_api.attachment_deletion_allowed(self.context, attachment)
        mock_get_server.assert_not_called()

    @mock.patch('cinder.compute.nova.API.get_server_volume')
    def test_attachment_deletion_allowed_no_conn_info(self, mock_get_server):
        """Attachments with no connection information are never redirected."""
        attachment = self._get_attachment(with_instance_id=False)
        attachment.connection_info = None
        self.volume_api.attachment_deletion_allowed(self.context, attachment)

        mock_get_server.assert_not_called()

    def test_attachment_deletion_allowed_no_attachment(self):
        """For users don't allow operation with no attachment reference."""
        self.assertRaises(exception.ConflictNovaUsingAttachment,
                          self.volume_api.attachment_deletion_allowed,
                          self.context, None)

    @mock.patch('cinder.objects.VolumeAttachment.get_by_id',
                side_effect=exception.VolumeAttachmentNotFound(filter=''))
    def test_attachment_deletion_allowed_attachment_id_not_found(self,
                                                                 mock_get):
        """For users don't allow if attachment cannot be found."""
        attachment = self._get_attachment(with_instance_id=False)
        attachment.connection_info = None
        self.assertRaises(exception.ConflictNovaUsingAttachment,
                          self.volume_api.attachment_deletion_allowed,
                          self.context, fake.ATTACHMENT_ID)
        mock_get.assert_called_once_with(self.context, fake.ATTACHMENT_ID)

    def test_attachment_deletion_allowed_volume_no_attachments(self):
        """For users allow if volume has no attachments."""
        volume = tests_utils.create_volume(self.context)
        self.volume_api.attachment_deletion_allowed(self.context, None, volume)

    def test_attachment_deletion_allowed_multiple_attachment(self):
        """For users don't allow if volume has multiple attachments."""
        attachment = self._get_attachment()
        volume = attachment.volume
        volume.volume_attachment = objects.VolumeAttachmentList(
            objects=[attachment, attachment])
        self.assertRaises(exception.ConflictNovaUsingAttachment,
                          self.volume_api.attachment_deletion_allowed,
                          self.context, None, volume)

    @mock.patch('cinder.compute.nova.API.get_server_volume')
    def test_attachment_deletion_allowed_vm_not_found(self, mock_get_server):
        """Don't reject if instance doesn't exist"""
        mock_get_server.side_effect = nova.API.NotFound(404)
        attachment = self._get_attachment()
        self.volume_api.attachment_deletion_allowed(self.context, attachment)

        mock_get_server.assert_called_once_with(self.context, fake.INSTANCE_ID,
                                                fake.VOLUME_ID)

    @mock.patch('cinder.compute.nova.API.get_server_volume')
    def test_attachment_deletion_allowed_attachment_from_volume(
            self, mock_get_server):
        """Don't reject if instance doesn't exist"""
        mock_get_server.side_effect = nova.API.NotFound(404)
        attachment = self._get_attachment()
        volume = attachment.volume
        volume.volume_attachment = objects.VolumeAttachmentList(
            objects=[attachment])
        self.volume_api.attachment_deletion_allowed(self.context, None, volume)

        mock_get_server.assert_called_once_with(self.context, fake.INSTANCE_ID,
                                                volume.id)

    @mock.patch('cinder.objects.VolumeAttachment.get_by_id')
    def test_attachment_deletion_allowed_mismatched_volume_and_attach_id(
            self, mock_get_attatchment):
        """Reject if volume and attachment don't match."""
        attachment = self._get_attachment()
        volume = attachment.volume
        volume.volume_attachment = objects.VolumeAttachmentList(
            objects=[attachment])
        attachment2 = self._get_attachment()
        attachment2.volume_id = attachment.volume.id = fake.VOLUME2_ID
        self.assertRaises(exception.InvalidInput,
                          self.volume_api.attachment_deletion_allowed,
                          self.context, attachment2.id, volume)
        mock_get_attatchment.assert_called_once_with(self.context,
                                                     attachment2.id)

    @mock.patch('cinder.objects.VolumeAttachment.get_by_id')
    @mock.patch('cinder.compute.nova.API.get_server_volume')
    def test_attachment_deletion_allowed_not_found_attachment_id(
            self, mock_get_server, mock_get_attachment):
        """Don't reject if instance doesn't exist"""
        mock_get_server.side_effect = nova.API.NotFound(404)
        mock_get_attachment.return_value = self._get_attachment()

        self.volume_api.attachment_deletion_allowed(self.context,
                                                    fake.ATTACHMENT_ID)

        mock_get_attachment.assert_called_once_with(self.context,
                                                    fake.ATTACHMENT_ID)

        mock_get_server.assert_called_once_with(self.context, fake.INSTANCE_ID,
                                                fake.VOLUME_ID)

    @mock.patch('cinder.compute.nova.API.get_server_volume')
    def test_attachment_deletion_allowed_mismatch_id(self, mock_get_server):
        """Don't reject if attachment id on nova doesn't match"""
        mock_get_server.return_value.attachment_id = fake.ATTACHMENT2_ID
        attachment = self._get_attachment()
        self.volume_api.attachment_deletion_allowed(self.context, attachment)

        mock_get_server.assert_called_once_with(self.context, fake.INSTANCE_ID,
                                                fake.VOLUME_ID)

    @mock.patch('cinder.compute.nova.API.get_server_volume')
    def test_attachment_deletion_allowed_user_call_fails(self,
                                                         mock_get_server):
        """Fail user calls"""
        attachment = self._get_attachment()
        mock_get_server.return_value.attachment_id = attachment.id
        self.assertRaises(exception.ConflictNovaUsingAttachment,
                          self.volume_api.attachment_deletion_allowed,
                          self.context, attachment)

        mock_get_server.assert_called_once_with(self.context, fake.INSTANCE_ID,
                                                fake.VOLUME_ID)
