# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""Tests for Volume connection test cases."""

import ddt
import mock

from cinder import context
from cinder import db
from cinder import exception
from cinder.message import message_field
from cinder import objects
from cinder.objects import fields
from cinder.tests import fake_driver
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base
import cinder.volume
import cinder.volume.targets
import cinder.volume.targets.iscsi


@ddt.ddt
class DiscardFlagTestCase(base.BaseVolumeTestCase):

    def setUp(self):
        super(DiscardFlagTestCase, self).setUp()
        self.volume.driver = mock.MagicMock()

    @ddt.data(dict(config_discard_flag=True,
                   driver_discard_flag=None,
                   expected_flag=True),
              dict(config_discard_flag=False,
                   driver_discard_flag=None,
                   expected_flag=None),
              dict(config_discard_flag=True,
                   driver_discard_flag=True,
                   expected_flag=True),
              dict(config_discard_flag=False,
                   driver_discard_flag=True,
                   expected_flag=True),
              dict(config_discard_flag=False,
                   driver_discard_flag=False,
                   expected_flag=False),
              dict(config_discard_flag=None,
                   driver_discard_flag=True,
                   expected_flag=True),
              dict(config_discard_flag=None,
                   driver_discard_flag=False,
                   expected_flag=False))
    @ddt.unpack
    def test_initialize_connection_discard_flag(self,
                                                config_discard_flag,
                                                driver_discard_flag,
                                                expected_flag):
        self.volume.driver.create_export.return_value = None
        connector = {'ip': 'IP', 'initiator': 'INITIATOR'}

        conn_info = {
            'driver_volume_type': 'iscsi',
            'data': {'access_mode': 'rw',
                     'encrypted': False}
        }

        if driver_discard_flag is not None:
            conn_info['data']['discard'] = driver_discard_flag

        self.volume.driver.initialize_connection.return_value = conn_info

        def _safe_get(key):
            if key is 'report_discard_supported':
                return config_discard_flag
            else:
                return None

        self.volume.driver.configuration.safe_get.side_effect = _safe_get

        with mock.patch.object(objects, 'Volume') as mock_vol:
            volume = tests_utils.create_volume(self.context)
            volume.volume_type_id = None
            mock_vol.get_by_id.return_value = volume

            conn_info = self.volume.initialize_connection(self.context,
                                                          volume,
                                                          connector)

        self.assertEqual(expected_flag, conn_info['data'].get('discard'))


class VolumeConnectionTestCase(base.BaseVolumeTestCase):
    @mock.patch.object(cinder.volume.targets.iscsi.ISCSITarget,
                       '_get_target_chap_auth')
    @mock.patch.object(db, 'volume_admin_metadata_get')
    @mock.patch.object(db.sqlalchemy.api, 'volume_get')
    @mock.patch.object(db, 'volume_update')
    def test_initialize_connection_fetchqos(self,
                                            _mock_volume_update,
                                            _mock_volume_get,
                                            _mock_volume_admin_metadata_get,
                                            mock_get_target):
        """Make sure initialize_connection returns correct information."""
        _fake_admin_meta = [{'key': 'fake-key', 'value': 'fake-value'}]
        _fake_volume = {'volume_type_id': fake.VOLUME_TYPE_ID,
                        'name': 'fake_name',
                        'host': 'fake_host',
                        'id': fake.VOLUME_ID,
                        'volume_admin_metadata': _fake_admin_meta}
        fake_volume_obj = fake_volume.fake_volume_obj(self.context,
                                                      **_fake_volume)

        _mock_volume_get.return_value = _fake_volume
        _mock_volume_update.return_value = _fake_volume
        _mock_volume_admin_metadata_get.return_value = {
            'fake-key': 'fake-value'}

        connector = {'ip': 'IP', 'initiator': 'INITIATOR'}
        qos_values = {'consumer': 'front-end',
                      'specs': {
                          'key1': 'value1',
                          'key2': 'value2'}
                      }

        with mock.patch.object(cinder.volume.volume_types,
                               'get_volume_type_qos_specs') as type_qos, \
            mock.patch.object(cinder.tests.fake_driver.FakeLoggingVolumeDriver,
                              'initialize_connection') as driver_init:
            type_qos.return_value = dict(qos_specs=qos_values)
            driver_init.return_value = {'data': {}}
            mock_get_target.return_value = None
            qos_specs_expected = {'key1': 'value1',
                                  'key2': 'value2'}
            # initialize_connection() passes qos_specs that is designated to
            # be consumed by front-end or both front-end and back-end
            conn_info = self.volume.initialize_connection(
                self.context, fake_volume_obj, connector,)
            self.assertDictEqual(qos_specs_expected,
                                 conn_info['data']['qos_specs'])

            qos_values.update({'consumer': 'both'})
            conn_info = self.volume.initialize_connection(
                self.context, fake_volume_obj, connector)
            self.assertDictEqual(qos_specs_expected,
                                 conn_info['data']['qos_specs'])
            # initialize_connection() skips qos_specs that is designated to be
            # consumed by back-end only
            qos_values.update({'consumer': 'back-end'})
            type_qos.return_value = dict(qos_specs=qos_values)
            conn_info = self.volume.initialize_connection(
                self.context, fake_volume_obj, connector)
            self.assertIsNone(conn_info['data']['qos_specs'])

    @mock.patch.object(cinder.volume.targets.iscsi.ISCSITarget,
                       '_get_target_chap_auth')
    @mock.patch.object(db, 'volume_admin_metadata_get')
    @mock.patch.object(db.sqlalchemy.api, 'volume_get')
    @mock.patch.object(db, 'volume_update')
    def test_initialize_connection_qos_per_gb(self,
                                              _mock_volume_update,
                                              _mock_volume_get,
                                              _mock_volume_admin_metadata_get,
                                              mock_get_target):
        """QoS test with no minimum value."""
        _fake_admin_meta = [{'key': 'fake-key', 'value': 'fake-value'}]
        _fake_volume = {'size': 3,
                        'volume_type_id': fake.VOLUME_TYPE_ID,
                        'name': 'fake_name',
                        'host': 'fake_host',
                        'id': fake.VOLUME_ID,
                        'volume_admin_metadata': _fake_admin_meta}
        fake_volume_obj = fake_volume.fake_volume_obj(self.context,
                                                      **_fake_volume)

        _mock_volume_get.return_value = _fake_volume
        _mock_volume_update.return_value = _fake_volume
        _mock_volume_admin_metadata_get.return_value = {
            'fake-key': 'fake-value'}

        connector = {'ip': 'IP', 'initiator': 'INITIATOR'}
        qos_values = {'consumer': 'front-end',
                      'specs': {
                          'write_iops_sec_per_gb': 30,
                          'read_iops_sec_per_gb': 7700,
                          'total_iops_sec_per_gb': 300000,
                          'read_bytes_sec_per_gb': 10,
                          'write_bytes_sec_per_gb': 40,
                          'total_bytes_sec_per_gb': 1048576}
                      }

        with mock.patch.object(cinder.volume.volume_types,
                               'get_volume_type_qos_specs') as type_qos, \
            mock.patch.object(cinder.tests.fake_driver.FakeLoggingVolumeDriver,
                              'initialize_connection') as driver_init:
            type_qos.return_value = dict(qos_specs=qos_values)
            driver_init.return_value = {'data': {}}
            mock_get_target.return_value = None
            qos_specs_expected = {'write_iops_sec': 90,
                                  'read_iops_sec': 23100,
                                  'total_iops_sec': 900000,
                                  'read_bytes_sec': 30,
                                  'write_bytes_sec': 120,
                                  'total_bytes_sec': 3145728}
            # initialize_connection() passes qos_specs that is designated to
            # be consumed by front-end or both front-end and back-end
            conn_info = self.volume.initialize_connection(
                self.context, fake_volume_obj, connector,)
            self.assertDictEqual(qos_specs_expected,
                                 conn_info['data']['qos_specs'])

            qos_values.update({'consumer': 'both'})
            conn_info = self.volume.initialize_connection(
                self.context, fake_volume_obj, connector)
            self.assertDictEqual(qos_specs_expected,
                                 conn_info['data']['qos_specs'])

    @mock.patch.object(cinder.volume.targets.iscsi.ISCSITarget,
                       '_get_target_chap_auth')
    @mock.patch.object(db, 'volume_admin_metadata_get')
    @mock.patch.object(db.sqlalchemy.api, 'volume_get')
    @mock.patch.object(db, 'volume_update')
    def test_initialize_connection_qos_per_gb_with_min_small(
            self, _mock_volume_update, _mock_volume_get,
            _mock_volume_admin_metadata_get, mock_get_target):
        """QoS test when volume size results in using minimum."""
        _fake_admin_meta = [{'key': 'fake-key', 'value': 'fake-value'}]
        _fake_volume = {'size': 1,
                        'volume_type_id': fake.VOLUME_TYPE_ID,
                        'name': 'fake_name',
                        'host': 'fake_host',
                        'id': fake.VOLUME_ID,
                        'volume_admin_metadata': _fake_admin_meta}
        fake_volume_obj = fake_volume.fake_volume_obj(self.context,
                                                      **_fake_volume)

        _mock_volume_get.return_value = _fake_volume
        _mock_volume_update.return_value = _fake_volume
        _mock_volume_admin_metadata_get.return_value = {
            'fake-key': 'fake-value'}

        connector = {'ip': 'IP', 'initiator': 'INITIATOR'}
        qos_values = {'consumer': 'front-end',
                      'specs': {
                          'write_iops_sec_per_gb_min': 800,
                          'write_iops_sec_per_gb': 30,
                          'read_iops_sec_per_gb_min': 23100,
                          'read_iops_sec_per_gb': 7700,
                          'total_iops_sec_per_gb_min': 900000,
                          'total_iops_sec_per_gb': 300000,
                          'total_iops_sec_max': 15000000,
                          'read_bytes_sec_per_gb_min': 30,
                          'read_bytes_sec_per_gb': 10,
                          'write_bytes_sec_per_gb_min': 120,
                          'write_bytes_sec_per_gb': 40,
                          'total_bytes_sec_per_gb_min': 3145728,
                          'total_bytes_sec_per_gb': 1048576}
                      }

        with mock.patch.object(cinder.volume.volume_types,
                               'get_volume_type_qos_specs') as type_qos, \
            mock.patch.object(cinder.tests.fake_driver.FakeLoggingVolumeDriver,
                              'initialize_connection') as driver_init:
            type_qos.return_value = dict(qos_specs=qos_values)
            driver_init.return_value = {'data': {}}
            mock_get_target.return_value = None
            qos_specs_expected = {'write_iops_sec': 800,
                                  'read_iops_sec': 23100,
                                  'total_iops_sec': 900000,
                                  'read_bytes_sec': 30,
                                  'write_bytes_sec': 120,
                                  'total_bytes_sec': 3145728}
            # initialize_connection() passes qos_specs that is designated to
            # be consumed by front-end or both front-end and back-end
            conn_info = self.volume.initialize_connection(
                self.context, fake_volume_obj, connector,)
            self.assertDictEqual(qos_specs_expected,
                                 conn_info['data']['qos_specs'])

            qos_values.update({'consumer': 'both'})
            conn_info = self.volume.initialize_connection(
                self.context, fake_volume_obj, connector)
            self.assertDictEqual(qos_specs_expected,
                                 conn_info['data']['qos_specs'])

    @mock.patch.object(cinder.volume.targets.iscsi.ISCSITarget,
                       '_get_target_chap_auth')
    @mock.patch.object(db, 'volume_admin_metadata_get')
    @mock.patch.object(db.sqlalchemy.api, 'volume_get')
    @mock.patch.object(db, 'volume_update')
    def test_initialize_connection_qos_per_gb_with_min_large(
            self, _mock_volume_update, _mock_volume_get,
            _mock_volume_admin_metadata_get, mock_get_target):
        """QoS test when volume size results in using per-gb values."""
        _fake_admin_meta = [{'key': 'fake-key', 'value': 'fake-value'}]
        _fake_volume = {'size': 100,
                        'volume_type_id': fake.VOLUME_TYPE_ID,
                        'name': 'fake_name',
                        'host': 'fake_host',
                        'id': fake.VOLUME_ID,
                        'volume_admin_metadata': _fake_admin_meta}
        fake_volume_obj = fake_volume.fake_volume_obj(self.context,
                                                      **_fake_volume)

        _mock_volume_get.return_value = _fake_volume
        _mock_volume_update.return_value = _fake_volume
        _mock_volume_admin_metadata_get.return_value = {
            'fake-key': 'fake-value'}

        connector = {'ip': 'IP', 'initiator': 'INITIATOR'}
        qos_values = {'consumer': 'front-end',
                      'specs': {
                          'write_iops_sec_per_gb_min': 800,
                          'write_iops_sec_per_gb': 30,
                          'read_iops_sec_per_gb_min': 23100,
                          'read_iops_sec_per_gb': 7700,
                          'total_iops_sec_per_gb_min': 900000,
                          'total_iops_sec_per_gb': 300000,
                          'total_iops_sec_max': 15000000,
                          'read_bytes_sec_per_gb_min': 30,
                          'read_bytes_sec_per_gb': 10,
                          'write_bytes_sec_per_gb_min': 120,
                          'write_bytes_sec_per_gb': 40,
                          'total_bytes_sec_per_gb_min': 3145728,
                          'total_bytes_sec_per_gb': 1048576}
                      }

        with mock.patch.object(cinder.volume.volume_types,
                               'get_volume_type_qos_specs') as type_qos, \
            mock.patch.object(cinder.tests.fake_driver.FakeLoggingVolumeDriver,
                              'initialize_connection') as driver_init:
            type_qos.return_value = dict(qos_specs=qos_values)
            driver_init.return_value = {'data': {}}
            mock_get_target.return_value = None
            qos_specs_expected = {'write_iops_sec': 3000,
                                  'read_iops_sec': 770000,
                                  'total_iops_sec': 15000000,
                                  'read_bytes_sec': 1000,
                                  'write_bytes_sec': 4000,
                                  'total_bytes_sec': 104857600}
            # initialize_connection() passes qos_specs that is designated to
            # be consumed by front-end or both front-end and back-end
            conn_info = self.volume.initialize_connection(
                self.context, fake_volume_obj, connector,)
            self.assertDictEqual(qos_specs_expected,
                                 conn_info['data']['qos_specs'])

            qos_values.update({'consumer': 'both'})
            conn_info = self.volume.initialize_connection(
                self.context, fake_volume_obj, connector)
            self.assertDictEqual(qos_specs_expected,
                                 conn_info['data']['qos_specs'])

    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver, 'create_export')
    def test_initialize_connection_export_failure(self,
                                                  _mock_create_export):
        """Test exception path for create_export failure."""
        volume = tests_utils.create_volume(
            self.context, admin_metadata={'fake-key': 'fake-value'},
            volume_type_id=fake.VOLUME_TYPE_ID, **self.volume_params)
        _mock_create_export.side_effect = exception.CinderException

        connector = {'ip': 'IP', 'initiator': 'INITIATOR'}

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.initialize_connection,
                          self.context, volume, connector)

    def test_initialize_connection_maintenance(self):
        """Test initialize connection in maintenance."""
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.initialize_connection,
                          self.context,
                          volume,
                          None)


@ddt.ddt
class VolumeAttachDetachTestCase(base.BaseVolumeTestCase):

    def setUp(self):
        super(VolumeAttachDetachTestCase, self).setUp()
        self.patch('cinder.volume.utils.clear_volume', autospec=True)
        self.user_context = context.RequestContext(user_id=fake.USER_ID,
                                                   project_id=fake.PROJECT_ID)

    @ddt.data(False, True)
    def test_run_attach_detach_volume_for_instance(self, volume_object):
        """Make sure volume can be attached and detached from instance."""
        mountpoint = "/dev/sdf"
        # attach volume to the instance then to detach
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = tests_utils.create_volume(self.user_context,
                                           **self.volume_params)
        with volume.obj_as_admin():
            volume.admin_metadata['readonly'] = True
            volume.save()
        volume_id = volume.id
        self.volume.create_volume(self.user_context,
                                  volume=volume)
        volume_passed = volume if volume_object else None
        attachment = self.volume.attach_volume(self.user_context,
                                               volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro',
                                               volume=volume_passed)
        attachment2 = self.volume.attach_volume(self.user_context,
                                                volume_id,
                                                instance_uuid, None,
                                                mountpoint, 'ro',
                                                volume=volume_passed)
        self.assertEqual(attachment.id, attachment2.id)
        vol = objects.Volume.get_by_id(self.context, volume_id)
        self.assertEqual("in-use", vol.status)
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment.attach_status)
        self.assertEqual(mountpoint, attachment.mountpoint)
        self.assertEqual(instance_uuid, attachment.instance_uuid)
        self.assertIsNone(attachment.attached_host)
        admin_metadata = vol.volume_admin_metadata
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)

        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        volume = volume if volume_object else vol
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume=volume)
        self.volume.detach_volume(self.context, volume_id,
                                  attachment.id,
                                  volume=volume_passed)
        vol = objects.Volume.get_by_id(self.context, volume_id)
        self.assertEqual('available', vol.status)

        self.volume.delete_volume(self.context, volume)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    @mock.patch('cinder.volume.manager.LOG', mock.Mock())
    def test_initialize_connection(self):
        volume = mock.Mock(save=mock.Mock(side_effect=Exception))
        with mock.patch.object(self.volume, 'driver') as driver_mock:
            self.assertRaises(exception.ExportFailure,
                              self.volume.initialize_connection, self.context,
                              volume, mock.Mock())
        driver_mock.remove_export.assert_called_once_with(mock.ANY, volume)

    def test_run_attach_detach_2volumes_for_instance(self):
        """Make sure volume can be attached and detached from instance."""
        # attach first volume to the instance
        mountpoint1 = "/dev/vdc"
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume1 = tests_utils.create_volume(
            self.context, admin_metadata={'readonly': 'True'},
            **self.volume_params)
        volume1_id = volume1['id']
        self.volume.create_volume(self.context, volume1)
        attachment = self.volume.attach_volume(self.context, volume1_id,
                                               instance_uuid, None,
                                               mountpoint1, 'ro')
        vol1 = db.volume_get(context.get_admin_context(), volume1_id)
        self.assertEqual("in-use", vol1['status'])
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint1, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol1['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)

        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume1, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume1)

        # attach 2nd volume to the instance
        mountpoint2 = "/dev/vdd"
        volume2 = tests_utils.create_volume(
            self.context, admin_metadata={'readonly': 'False'},
            **self.volume_params)
        volume2_id = volume2['id']
        self.volume.create_volume(self.context, volume2)
        attachment2 = self.volume.attach_volume(self.context, volume2_id,
                                                instance_uuid, None,
                                                mountpoint2, 'rw')
        vol2 = db.volume_get(context.get_admin_context(), volume2_id)
        self.assertEqual("in-use", vol2['status'])
        self.assertEqual('attached', attachment2['attach_status'])
        self.assertEqual(mountpoint2, attachment2['mountpoint'])
        self.assertEqual(instance_uuid, attachment2['instance_uuid'])
        self.assertIsNone(attachment2['attached_host'])
        admin_metadata = vol2['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='False', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)

        connector = {'initiator': 'iqn.2012-07.org.fake:02'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume2, connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume2)

        # detach first volume and then 2nd volume
        self.volume.detach_volume(self.context, volume1_id, attachment['id'])
        vol1 = db.volume_get(self.context, volume1_id)
        self.assertEqual('available', vol1['status'])

        self.volume.delete_volume(self.context, volume1)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume1_id)

        self.volume.detach_volume(self.context, volume2_id, attachment2['id'])
        vol2 = db.volume_get(self.context, volume2_id)
        self.assertEqual('available', vol2['status'])

        self.volume.delete_volume(self.context, volume2)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume2_id)

    def test_detach_invalid_attachment_id(self):
        """Make sure if the attachment id isn't found we raise."""
        attachment_id = "notfoundid"
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=False,
                                           **self.volume_params)
        self.volume.detach_volume(self.context, volume['id'],
                                  attachment_id)
        volume = db.volume_get(self.context, volume['id'])
        self.assertEqual('available', volume['status'])

        instance_uuid = '12345678-1234-5678-1234-567812345678'
        attached_host = 'fake_host'
        mountpoint = '/dev/fake'
        tests_utils.attach_volume(self.context, volume['id'],
                                  instance_uuid, attached_host,
                                  mountpoint)
        self.volume.detach_volume(self.context, volume['id'],
                                  attachment_id)
        volume = db.volume_get(self.context, volume['id'])
        self.assertEqual('in-use', volume['status'])

    def test_detach_no_attachments(self):
        self.volume_params['status'] = 'detaching'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=False,
                                           **self.volume_params)
        self.volume.detach_volume(self.context, volume['id'])
        volume = db.volume_get(self.context, volume['id'])
        self.assertEqual('available', volume['status'])

    def test_run_attach_detach_volume_for_instance_no_attachment_id(self):
        """Make sure volume can be attached and detached from instance."""
        mountpoint = "/dev/sdf"
        # attach volume to the instance then to detach
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        instance_uuid_2 = '12345678-4321-8765-4321-567812345678'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=True,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        attachment = self.volume.attach_volume(self.context, volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)
        attachment2 = self.volume.attach_volume(self.context, volume_id,
                                                instance_uuid_2, None,
                                                mountpoint, 'ro')

        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])
        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume)

        self.assertRaises(exception.InvalidVolume,
                          self.volume.detach_volume,
                          self.context, volume_id)

        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('in-use', vol['status'])

        self.volume.detach_volume(self.context, volume_id, attachment2['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('available', vol['status'])

        attachment = self.volume.attach_volume(self.context, volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro')
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('in-use', vol['status'])
        self.volume.detach_volume(self.context, volume_id)
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('available', vol['status'])

        self.volume.delete_volume(self.context, volume)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_detach_multiattach_volume_for_instances(self):
        """Make sure volume can be attached to multiple instances."""
        mountpoint = "/dev/sdf"
        # attach volume to the instance then to detach
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=True,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        attachment = self.volume.attach_volume(self.context, volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])

        instance2_uuid = '12345678-1234-5678-1234-567812345000'
        mountpoint2 = "/dev/sdx"
        attachment2 = self.volume.attach_volume(self.context, volume_id,
                                                instance2_uuid, None,
                                                mountpoint2, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment2['attach_status'])
        self.assertEqual(mountpoint2, attachment2['mountpoint'])
        self.assertEqual(instance2_uuid, attachment2['instance_uuid'])
        self.assertIsNone(attachment2['attached_host'])
        self.assertNotEqual(attachment, attachment2)

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume)
        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('in-use', vol['status'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume)

        self.volume.detach_volume(self.context, volume_id, attachment2['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('available', vol['status'])

        self.volume.delete_volume(self.context, volume)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_twice_multiattach_volume_for_instances(self):
        """Make sure volume can be attached to multiple instances."""
        mountpoint = "/dev/sdf"
        # attach volume to the instance then to detach
        instance_uuid = '12345678-1234-5678-1234-567812345699'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=True,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        attachment = self.volume.attach_volume(self.context, volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])

        mountpoint2 = "/dev/sdx"
        attachment2 = self.volume.attach_volume(self.context, volume_id,
                                                instance_uuid, None,
                                                mountpoint2, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertEqual('attached', attachment2['attach_status'])
        self.assertEqual(mountpoint, attachment2['mountpoint'])
        self.assertEqual(instance_uuid, attachment2['instance_uuid'])
        self.assertIsNone(attachment2['attached_host'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume)

    def test_attach_detach_not_multiattach_volume_for_instances(self):
        """Make sure volume can't be attached to more than one instance."""
        mountpoint = "/dev/sdf"
        # attach volume to the instance then to detach
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=False,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        attachment = self.volume.attach_volume(self.context, volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertFalse(vol['multiattach'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])

        instance2_uuid = '12345678-1234-5678-1234-567812345000'
        mountpoint2 = "/dev/sdx"
        self.assertRaises(exception.InvalidVolume,
                          self.volume.attach_volume,
                          self.context,
                          volume_id,
                          instance2_uuid,
                          None,
                          mountpoint2, 'ro')

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume)
        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('available', vol['status'])

        self.volume.delete_volume(self.context, volume)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_detach_volume_for_host(self):
        """Make sure volume can be attached and detached from host."""
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(
            self.context,
            admin_metadata={'readonly': 'False'},
            **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        attachment = self.volume.attach_volume(self.context, volume_id, None,
                                               'fake_host', mountpoint, 'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host', attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='False', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)

        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume, connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume)
        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual("available", vol['status'])

        self.volume.delete_volume(self.context, volume)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_detach_multiattach_volume_for_hosts(self):
        """Make sure volume can be attached and detached from hosts."""
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(
            self.context,
            admin_metadata={'readonly': 'False'},
            multiattach=True,
            **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        attachment = self.volume.attach_volume(self.context, volume_id, None,
                                               'fake_host', mountpoint, 'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host', attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='False', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume, connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])

        mountpoint2 = "/dev/sdx"
        attachment2 = self.volume.attach_volume(self.context, volume_id, None,
                                                'fake_host2', mountpoint2,
                                                'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment2['attach_status'])
        self.assertEqual(mountpoint2, attachment2['mountpoint'])
        self.assertIsNone(attachment2['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host2', attachment2['attached_host'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume)
        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual("in-use", vol['status'])

        self.volume.detach_volume(self.context, volume_id, attachment2['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual("available", vol['status'])

        self.volume.delete_volume(self.context, volume)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_twice_multiattach_volume_for_hosts(self):
        """Make sure volume can be attached and detached from hosts."""
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(
            self.context,
            admin_metadata={'readonly': 'False'},
            multiattach=True,
            **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        attachment = self.volume.attach_volume(self.context, volume_id, None,
                                               'fake_host', mountpoint, 'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host', attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='False', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume, connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])

        mountpoint2 = "/dev/sdx"
        attachment2 = self.volume.attach_volume(self.context, volume_id, None,
                                                'fake_host', mountpoint2,
                                                'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertEqual('attached', attachment2['attach_status'])
        self.assertEqual(mountpoint, attachment2['mountpoint'])
        self.assertIsNone(attachment2['instance_uuid'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume)

    def test_run_attach_detach_not_multiattach_volume_for_hosts(self):
        """Make sure volume can't be attached to more than one host."""
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(
            self.context,
            admin_metadata={'readonly': 'False'},
            multiattach=False,
            **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        attachment = self.volume.attach_volume(self.context, volume_id, None,
                                               'fake_host', mountpoint, 'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertFalse(vol['multiattach'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host', attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='False', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume, connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])

        mountpoint2 = "/dev/sdx"
        self.assertRaises(exception.InvalidVolume,
                          self.volume.attach_volume,
                          self.context,
                          volume_id,
                          None,
                          'fake_host2',
                          mountpoint2,
                          'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host', attachment['attached_host'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume)
        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('available', vol['status'])

        self.volume.delete_volume(self.context, volume)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_detach_volume_with_attach_mode(self):
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        volume_id = volume['id']
        db.volume_update(self.context, volume_id, {'status': 'available', })
        self.volume.attach_volume(self.context, volume_id, instance_uuid,
                                  None, mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        attachment = vol['volume_attachment'][0]
        self.assertEqual('in-use', vol['status'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         vol['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume, connector)

        self.assertEqual('ro', conn_info['data']['access_mode'])

        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        attachment = vol['volume_attachment']
        self.assertEqual('available', vol['status'])
        self.assertEqual(fields.VolumeAttachStatus.DETACHED,
                         vol['attach_status'])
        self.assertEqual([], attachment)
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('True', admin_metadata[0]['value'])

        self.volume.attach_volume(self.context, volume_id, None,
                                  'fake_host', mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        attachment = vol['volume_attachment'][0]
        self.assertEqual('in-use', vol['status'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         vol['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        self.assertEqual('fake-host', attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])

        self.volume.detach_volume(self.context, volume_id,
                                  attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        attachment = vol['volume_attachment']
        self.assertEqual('available', vol['status'])
        self.assertEqual(fields.VolumeAttachStatus.DETACHED,
                         vol['attach_status'])
        self.assertEqual([], attachment)
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('True', admin_metadata[0]['value'])

        self.volume.delete_volume(self.context, volume)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_manager_attach_detach_volume_with_wrong_attach_mode(self):
        # Not allow using 'read-write' mode attach readonly volume
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        self.assertRaises(exception.InvalidVolumeAttachMode,
                          self.volume.attach_volume,
                          self.context,
                          volume_id,
                          instance_uuid,
                          None,
                          mountpoint,
                          'rw')

        # Assert a user message was created
        self.volume.message_api.create.assert_called_once_with(
            self.context, message_field.Action.ATTACH_VOLUME,
            resource_uuid=volume['id'],
            exception=mock.ANY)

        attachment = objects.VolumeAttachmentList.get_all_by_volume_id(
            context.get_admin_context(), volume_id)[0]
        self.assertEqual(fields.VolumeAttachStatus.ERROR_ATTACHING,
                         attachment.attach_status)
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(fields.VolumeAttachStatus.DETACHED,
                         vol['attach_status'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)

        db.volume_update(self.context, volume_id, {'status': 'available'})
        self.assertRaises(exception.InvalidVolumeAttachMode,
                          self.volume.attach_volume,
                          self.context,
                          volume_id,
                          None,
                          'fake_host',
                          mountpoint,
                          'rw')
        attachment = objects.VolumeAttachmentList.get_all_by_volume_id(
            context.get_admin_context(), volume_id)[0]
        self.assertEqual(fields.VolumeAttachStatus.ERROR_ATTACHING,
                         attachment.attach_status)
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(fields.VolumeAttachStatus.DETACHED,
                         vol['attach_status'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictEqual(expected, ret)

    def test_run_api_attach_detach_volume_with_wrong_attach_mode(self):
        # Not allow using 'read-write' mode attach readonly volume
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolumeAttachMode,
                          volume_api.attach,
                          self.context,
                          volume,
                          instance_uuid,
                          None,
                          mountpoint,
                          'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(fields.VolumeAttachStatus.DETACHED,
                         vol['attach_status'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('True', admin_metadata[0]['value'])

        db.volume_update(self.context, volume_id, {'status': 'available'})
        self.assertRaises(exception.InvalidVolumeAttachMode,
                          volume_api.attach,
                          self.context,
                          volume,
                          None,
                          'fake_host',
                          mountpoint,
                          'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(fields.VolumeAttachStatus.DETACHED,
                         vol['attach_status'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('True', admin_metadata[0]['value'])

    def test_detach_volume_while_uploading_to_image_is_in_progress(self):
        # If instance is booted from volume with 'Terminate on Delete' flag
        # set, and when we delete instance then it tries to delete volume
        # even it is in 'uploading' state.
        # It is happening because detach call is setting volume status to
        # 'available'.
        mountpoint = "/dev/sdf"
        # Attach volume to the instance
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        self.volume.attach_volume(self.context, volume_id, instance_uuid,
                                  None, mountpoint, 'ro')
        # Change volume status to 'uploading'
        db.volume_update(self.context, volume_id, {'status': 'uploading'})
        # Call detach api
        self.volume.detach_volume(self.context, volume_id)
        vol = db.volume_get(self.context, volume_id)
        # Check that volume status is 'uploading'
        self.assertEqual("uploading", vol['status'])
        self.assertEqual(fields.VolumeAttachStatus.DETACHED,
                         vol['attach_status'])

    def test_volume_attach_in_maintenance(self):
        """Test attach the volume in maintenance."""
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          self.context,
                          volume, None, None, None, None)

    def test_volume_detach_in_maintenance(self):
        """Test detach the volume in maintenance."""
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.detach,
                          self.context,
                          volume, None)
