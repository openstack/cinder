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
from oslo_config import cfg

from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils as tests_utils
from cinder.volume import api as volume_api
from cinder.volume import configuration as conf

CONF = cfg.CONF


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

    @mock.patch('cinder.volume.api.check_policy')
    def test_attachment_create_no_connector(self, mock_policy):
        """Test attachment_create no connector."""
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        aref = self.volume_api.attachment_create(self.context,
                                                 vref,
                                                 fake.UUID2)
        self.assertEqual(fake.UUID2, aref.instance_uuid)
        self.assertIsNone(aref.attach_time)
        self.assertEqual('reserved', aref.attach_status)
        self.assertIsNone(aref.attach_mode)
        self.assertEqual(vref.id, aref.volume_id)
        self.assertEqual({}, aref.connection_info)

    @mock.patch('cinder.volume.api.check_policy')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_update')
    def test_attachment_create_with_connector(self,
                                              mock_rpc_attachment_update,
                                              mock_policy):
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

    @mock.patch('cinder.volume.api.check_policy')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_delete')
    def test_attachment_delete_reserved(self,
                                        mock_rpc_attachment_delete,
                                        mock_policy):
        """Test attachment_delete with reserved."""
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

        # Since it's just reserved and never finalized, we should never make an
        # rpc call
        mock_rpc_attachment_delete.assert_not_called()

    @mock.patch('cinder.volume.api.check_policy')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_delete')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_update')
    def test_attachment_create_update_and_delete(
            self,
            mock_rpc_attachment_update,
            mock_rpc_attachment_delete,
            mock_policy):
        """Test attachment_delete."""
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

        connector = {'fake': 'connector'}
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

        mock_rpc_attachment_delete.assert_called_once_with(self.context,
                                                           aref.id,
                                                           mock.ANY)

    @mock.patch('cinder.volume.api.check_policy')
    def test_additional_attachment_create_no_connector(self, mock_policy):
        """Test attachment_create no connector."""
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        aref = self.volume_api.attachment_create(self.context,
                                                 vref,
                                                 fake.UUID2)
        self.assertEqual(fake.UUID2, aref.instance_uuid)
        self.assertIsNone(aref.attach_time)
        self.assertEqual('reserved', aref.attach_status)
        self.assertIsNone(aref.attach_mode)
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
