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
from oslo_policy import policy as oslo_policy

from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.policies import attachments as attachment_policy
from cinder.policies import base as base_policy
from cinder import policy
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

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_delete')
    def test_attachment_delete_reserved(self,
                                        mock_rpc_attachment_delete):
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

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_delete')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_update')
    def test_attachment_create_update_and_delete(
            self,
            mock_rpc_attachment_update,
            mock_rpc_attachment_delete):
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

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_update')
    def test_attachment_create_reserve_delete(
            self,
            mock_rpc_attachment_update):
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
        vref = objects.Volume.get_by_id(self.context,
                                        vref.id)
        self.assertEqual('reserved', vref.status)

    def test_reserve_reserve_delete(self):
        """Test that we keep reserved status across multiple reserves."""
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
        vref = objects.Volume.get_by_id(self.context,
                                        vref.id)
        self.assertEqual('reserved', vref.status)
        self.assertEqual(1, len(vref.volume_attachment))

    def test_attachment_create_bootable_multiattach_policy(self):
        """Test attachment_create no connector."""
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        vref.multiattach = True
        vref.bootable = True
        vref.status = 'in-use'

        rules = {
            attachment_policy.MULTIATTACH_BOOTABLE_VOLUME_POLICY: base_policy.RULE_ADMIN_API  # noqa
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        self.addCleanup(policy.reset)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.volume_api.attachment_create,
                          self.user_context,
                          vref,
                          fake.UUID2)

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
