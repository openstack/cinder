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

from oslo_config import cfg
from oslo_utils import importutils

from cinder import context
from cinder import db
from cinder.db.sqlalchemy import api as sqla_db
from cinder import exception
from cinder.objects import fields
from cinder.objects import volume_attachment
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.tests.unit import utils as tests_utils
from cinder.volume import configuration as conf

CONF = cfg.CONF


class AttachmentManagerTestCase(test.TestCase):
    """Attachment related test for volume.manager.py."""

    def setUp(self):
        """Setup test class."""
        super(AttachmentManagerTestCase, self).setUp()
        self.manager = importutils.import_object(CONF.volume_manager)
        self.configuration = mock.Mock(conf.Configuration)
        self.context = context.get_admin_context()
        self.context.user_id = fake.USER_ID
        self.project_id = fake.PROJECT3_ID
        self.context.project_id = self.project_id
        self.manager.driver.set_initialized()
        self.manager.stats = {'allocated_capacity_gb': 100,
                              'pools': {}}

    @mock.patch.object(db.sqlalchemy.api, '_volume_type_get',
                       v2_fakes.fake_volume_type_get)
    @mock.patch('cinder.db.sqlalchemy.api.volume_type_qos_specs_get')
    @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs')
    def test_attachment_update(self, get_extra_specs, mock_type_get):
        """Test attachment_update."""
        volume_params = {'status': 'available'}
        connector = {
            "initiator": "iqn.1993-08.org.debian:01:cad181614cec",
            "ip": "192.168.1.20",
            "platform": "x86_64",
            "host": "tempest-1",
            "os_type": "linux2",
            "multipath": False}

        vref = tests_utils.create_volume(self.context, **volume_params)
        self.manager.create_volume(self.context, vref)
        values = {'volume_id': vref.id,
                  'attached_host': vref.host,
                  'attach_status': 'reserved',
                  'instance_uuid': fake.UUID1,
                  'attach_mode': 'rw'}
        attachment_ref = db.volume_attach(self.context, values)
        with mock.patch.object(
                self.manager, '_notify_about_volume_usage'),\
                mock.patch.object(
                self.manager.driver, 'attach_volume') as mock_attach:
            expected = {
                'encrypted': False,
                'qos_specs': None,
                'cacheable': False,
                'access_mode': 'rw',
                'driver_volume_type': 'iscsi',
                'attachment_id': attachment_ref.id}

            get_extra_specs.return_value = ''
            self.assertEqual(expected,
                             self.manager.attachment_update(
                                 self.context,
                                 vref,
                                 connector,
                                 attachment_ref.id))
            mock_attach.assert_called_once_with(self.context,
                                                vref,
                                                attachment_ref.instance_uuid,
                                                connector['host'],
                                                "na")
            expected = {
                'encrypted': False,
                'qos_specs': None,
                'cacheable': True,
                'access_mode': 'rw',
                'driver_volume_type': 'iscsi',
                'attachment_id': attachment_ref.id}

            get_extra_specs.return_value = '<is> True'
            self.assertEqual(expected,
                             self.manager.attachment_update(
                                 self.context,
                                 vref,
                                 connector,
                                 attachment_ref.id))

            new_attachment_ref = db.volume_attachment_get(self.context,
                                                          attachment_ref.id)
            self.assertEqual(attachment_ref.instance_uuid,
                             new_attachment_ref['instance_uuid'])
            self.assertEqual(connector['host'],
                             new_attachment_ref['attached_host'])
            self.assertEqual('na', new_attachment_ref['mountpoint'])
            self.assertEqual('rw', new_attachment_ref['attach_mode'])

            new_volume_ref = db.volume_get(self.context, vref.id)
            self.assertEqual('attaching', new_volume_ref.status)
            self.assertEqual(fields.VolumeAttachStatus.ATTACHING,
                             new_volume_ref.attach_status)

    def test_attachment_delete(self):
        """Test attachment_delete."""
        volume_params = {'status': 'available'}

        vref = tests_utils.create_volume(self.context, **volume_params)
        self.manager.create_volume(self.context, vref)
        values = {'volume_id': vref.id,
                  'volume_host': vref.host,
                  'attach_status': 'reserved',
                  'instance_uuid': fake.UUID1}
        attachment_ref = db.volume_attach(self.context, values)
        attachment_ref = db.volume_attachment_get(
            self.context,
            attachment_ref['id'])
        self.manager.attachment_delete(self.context,
                                       attachment_ref['id'],
                                       vref)
        self.assertRaises(exception.VolumeAttachmentNotFound,
                          db.volume_attachment_get,
                          self.context,
                          attachment_ref.id)

    def test_attachment_delete_multiple_attachments(self):
        volume_params = {'status': 'available'}
        vref = tests_utils.create_volume(self.context, **volume_params)
        attachment1 = volume_attachment.VolumeAttachment()
        attachment2 = volume_attachment.VolumeAttachment()

        attachment1.id = fake.UUID1
        attachment2.id = fake.UUID2

        @mock.patch('cinder.objects.VolumeAttachment.get_by_id',
                    side_effect=[attachment1, attachment2])
        @mock.patch.object(sqla_db, 'volume_admin_metadata_delete')
        @mock.patch.object(sqla_db, 'volume_detached')
        @mock.patch.object(self.context, 'elevated')
        @mock.patch.object(self.manager, '_connection_terminate')
        @mock.patch.object(self.manager.driver, 'remove_export')
        @mock.patch.object(self.manager.driver, 'detach_volume')
        def _test(mock_detach, mock_rm_export, mock_con_term, mock_elevated,
                  mock_db_detached, mock_db_meta_delete, mock_get_attachment):
            mock_elevated.return_value = self.context
            mock_con_term.return_value = False

            # test single attachment. This should call
            # detach and remove_export
            vref.volume_attachment.objects.append(attachment1)

            self.manager.attachment_delete(self.context, attachment1.id, vref)

            mock_detach.assert_called_once_with(self.context, vref,
                                                attachment1)
            mock_db_detached.called_once_with(self.context, vref,
                                              attachment1.id)
            mock_db_meta_delete.called_once_with(self.context, vref.id,
                                                 'attached_mode')
            mock_rm_export.assert_called_once_with(self.context, vref)

            # test more than 1 attachment. This should skip
            # detach and remove_export
            mock_con_term.return_value = True
            vref.volume_attachment.objects.append(attachment2)

            mock_detach.reset_mock()
            mock_rm_export.reset_mock()
            mock_db_detached.reset_mock()
            mock_db_meta_delete.reset_mock()

            self.manager.attachment_delete(self.context, attachment2.id, vref)

            mock_rm_export.assert_not_called()
            mock_db_detached.called_once_with(self.context, vref,
                                              attachment2.id)
            mock_db_meta_delete.called_once_with(self.context, vref.id,
                                                 'attached_mode')
        _test()

    def test_connection_terminate_no_connector_force_false(self):
        # Tests that calling _connection_terminate with an attachment that
        # does not have a connector will not call the driver and return None
        # if the force flag is False.
        attachment = mock.MagicMock(connector={})
        with mock.patch.object(self.manager.driver, '_initialized',
                               create=True, new=True):
            with mock.patch.object(self.manager.driver,
                                   'terminate_connection') as term_conn:
                has_shared_connection = self.manager._connection_terminate(
                    self.context, mock.sentinel.volume, attachment)
                self.assertIsNone(has_shared_connection)
                term_conn.assert_not_called()

    def test_connection_terminate_no_connector_force_true(self):
        # Tests that calling _connection_terminate with an attachment that
        # does not have a connector will call the driver when force is True.
        volume = mock.MagicMock()
        attachment = mock.MagicMock(connector={})
        with mock.patch.object(self.manager.driver, '_initialized',
                               create=True, new=True):
            with mock.patch.object(self.manager.driver,
                                   'terminate_connection') as term_conn:
                has_shared_connection = self.manager._connection_terminate(
                    self.context, volume, attachment, force=True)
                self.assertFalse(has_shared_connection)
                term_conn.assert_called_once_with(volume, {}, force=True)

    @mock.patch('cinder.objects.VolumeAttachment.get_by_id')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                '_notify_about_volume_usage')
    @mock.patch('cinder.volume.manager.VolumeManager._connection_terminate',
                return_value=None)
    @mock.patch('cinder.db.volume_detached')
    @mock.patch('cinder.db.volume_admin_metadata_delete')
    def test_attachment_delete_none_shared_connection(self, mock_meta_del,
                                                      mock_vol_detached,
                                                      mock_conn_term,
                                                      mock_notify,
                                                      mock_get_attachment):
        # Tests that attachment_delete does not call remove_export
        # if _connection_terminate returns None indicating there is nothing
        # to consider for the export.
        volume = mock.MagicMock()
        with mock.patch.object(self.manager.driver, '_initialized',
                               create=True, new=True):
            with mock.patch.object(self.manager.driver,
                                   'remove_export') as remove_export:
                self.manager.attachment_delete(
                    self.context, mock.sentinel.attachment_id, volume)
                mock_get_attachment.assert_called_once_with(
                    self.context, mock.sentinel.attachment_id)
                remove_export.assert_not_called()
