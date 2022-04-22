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

import ddt
from oslo_utils import timeutils

from cinder import context
from cinder import exception
from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume.targets import nvmeof


class FakeNVMeOFDriver(nvmeof.NVMeOF):
    def __init__(self, *args, **kwargs):
        super(FakeNVMeOFDriver, self).__init__(*args, **kwargs)

    def delete_nvmeof_target(self, target_name):
        pass


@ddt.ddt
class TestNVMeOFDriver(tf.TargetDriverFixture):

    def setUp(self):
        super(TestNVMeOFDriver, self).setUp()

        self.configuration.target_protocol = 'nvmet_rdma'
        self.target = FakeNVMeOFDriver(root_helper=utils.get_root_helper(),
                                       configuration=self.configuration)

        self.target_ip = self.configuration.target_ip_address
        self.target_port = self.configuration.target_port
        self.nvmet_subsystem_name = self.configuration.target_prefix
        self.nvmet_ns_id = self.configuration.nvmet_ns_id
        self.nvmet_port_id = self.configuration.nvmet_port_id
        self.nvme_transport_type = 'rdma'

        self.fake_volume_id = 'c446b9a2-c968-4260-b95f-a18a7b41c004'
        self.testvol_path = (
            '/dev/stack-volumes-lvmdriver-1/volume-%s' % self.fake_volume_id)
        self.fake_project_id = 'ed2c1fd4-5555-1111-aa15-123b93f75cba'
        self.testvol = (
            {'project_id': self.fake_project_id,
             'name': 'testvol',
             'size': 1,
             'id': self.fake_volume_id,
             'volume_type_id': None,
             'provider_location':
                 self.target.get_nvmeof_location(
                     "ngn.%s-%s" % (
                         self.nvmet_subsystem_name,
                         self.fake_volume_id),
                     [self.target_ip],
                     self.target_port,
                     self.nvme_transport_type,
                     self.nvmet_ns_id
                 ),
             'provider_auth': None,
             'provider_geometry': None,
             'created_at': timeutils.utcnow(),
             'host': 'fake_host@lvm#lvm'})

    @mock.patch.object(nvmeof.NVMeOF, '_get_connection_properties_from_vol')
    def test_initialize_connection(self, mock_get_conn):
        mock_connector = {'initiator': 'fake_init'}
        mock_testvol = self.testvol
        expected_return = {
            'driver_volume_type': 'nvmeof',
            'data': mock_get_conn.return_value
        }
        self.assertEqual(expected_return,
                         self.target.initialize_connection(mock_testvol,
                                                           mock_connector))
        mock_get_conn.assert_called_once_with(mock_testvol)

    @mock.patch.object(FakeNVMeOFDriver, 'create_nvmeof_target')
    def test_create_export(self, mock_create_nvme_target):
        ctxt = context.get_admin_context()
        self.target.create_export(ctxt, self.testvol, self.testvol_path)
        mock_create_nvme_target.assert_called_once_with(
            self.fake_volume_id,
            self.configuration.target_prefix,
            [self.target_ip],
            self.target_port,
            self.nvme_transport_type,
            self.nvmet_port_id,
            self.nvmet_ns_id,
            self.testvol_path
        )

    @mock.patch.object(FakeNVMeOFDriver, 'delete_nvmeof_target')
    def test_remove_export(self, mock_delete_nvmeof_target):
        ctxt = context.get_admin_context()
        self.target.remove_export(ctxt, self.testvol)
        mock_delete_nvmeof_target.assert_called_once_with(
            self.testvol
        )

    @mock.patch.object(nvmeof.NVMeOF, '_get_nvme_uuid')
    @mock.patch.object(nvmeof.NVMeOF, '_get_connection_properties')
    def test__get_connection_properties(self, mock_get_conn_props, mock_uuid):
        """Test connection properties from a volume."""
        res = self.target._get_connection_properties_from_vol(self.testvol)
        self.assertEqual(mock_get_conn_props.return_value, res)
        mock_uuid.assert_called_once_with(self.testvol)
        mock_get_conn_props.assert_called_once_with(
            f'ngn.{self.nvmet_subsystem_name}-{self.fake_volume_id}',
            [self.target_ip],
            str(self.target_port),
            self.nvme_transport_type,
            str(self.nvmet_ns_id),
            mock_uuid.return_value)

    @mock.patch.object(nvmeof.NVMeOF, '_get_nvme_uuid')
    @mock.patch.object(nvmeof.NVMeOF, '_get_connection_properties')
    def test__get_connection_properties_multiple_addresses(
            self, mock_get_conn_props, mock_uuid):
        """Test connection properties from a volume with multiple ips."""
        self.testvol['provider_location'] = self.target.get_nvmeof_location(
            f"ngn.{self.nvmet_subsystem_name}-{self.fake_volume_id}",
            [self.target_ip, '127.0.0.1'],
            self.target_port,
            self.nvme_transport_type,
            self.nvmet_ns_id
        )

        res = self.target._get_connection_properties_from_vol(self.testvol)
        self.assertEqual(mock_get_conn_props.return_value, res)
        mock_uuid.assert_called_once_with(self.testvol)
        mock_get_conn_props.assert_called_once_with(
            f'ngn.{self.nvmet_subsystem_name}-{self.fake_volume_id}',
            [self.target_ip, '127.0.0.1'],
            str(self.target_port),
            self.nvme_transport_type,
            str(self.nvmet_ns_id),
            mock_uuid.return_value)

    def test__get_connection_properties_old(self):
        """Test connection properties with the old NVMe-oF format."""
        nqn = f'ngn.{self.nvmet_subsystem_name}-{self.fake_volume_id}'
        expected_return = {
            'target_portal': self.target_ip,
            'target_port': str(self.target_port),
            'nqn': nqn,
            'transport_type': self.nvme_transport_type,
            'ns_id': str(self.nvmet_ns_id)
        }
        res = self.target._get_connection_properties(nqn,
                                                     [self.target_ip],
                                                     str(self.target_port),
                                                     self.nvme_transport_type,
                                                     str(self.nvmet_ns_id),
                                                     mock.sentinel.uuid)
        self.assertEqual(expected_return, res)

    @ddt.data(('rdma', 'RoCEv2'), ('tcp', 'tcp'))
    @ddt.unpack
    def test__get_connection_properties_new(
            self, transport, expected_transport):
        """Test connection properties with the new NVMe-oF format."""
        nqn = f'ngn.{self.nvmet_subsystem_name}-{self.fake_volume_id}'
        self.configuration.nvmeof_conn_info_version = 2

        expected_return = {
            'target_nqn': nqn,
            'vol_uuid': mock.sentinel.uuid,
            'ns_id': str(self.nvmet_ns_id),
            'portals': [(self.target_ip,
                         str(self.target_port),
                         expected_transport)],
        }
        res = self.target._get_connection_properties(nqn,
                                                     [self.target_ip],
                                                     str(self.target_port),
                                                     transport,
                                                     str(self.nvmet_ns_id),
                                                     mock.sentinel.uuid)
        self.assertEqual(expected_return, res)

    def test_validate_connector(self):
        mock_connector = {'initiator': 'fake_init'}
        self.assertTrue(self.target.validate_connector(mock_connector))

    def test_validate_connector_not_found(self):
        mock_connector = {'fake_init'}
        self.assertRaises(exception.InvalidConnectorException,
                          self.target.validate_connector,
                          mock_connector)

    def test_invalid_target_protocol(self):
        self.configuration.target_protocol = 'iser'
        self.assertRaises(nvmeof.UnsupportedNVMETProtocol,
                          FakeNVMeOFDriver,
                          root_helper=utils.get_root_helper(),
                          configuration=self.configuration)

    def test_invalid_secondary_ips_old_conn_info_combination(self):
        """Secondary IPS are only supported with new connection information."""
        self.configuration.target_secondary_ip_addresses = ['127.0.0.1']
        self.configuration.nvmeof_conn_info_version = 1
        self.assertRaises(exception.InvalidConfigurationValue,
                          FakeNVMeOFDriver,
                          root_helper=utils.get_root_helper(),
                          configuration=self.configuration)

    def test_valid_secondary_ips_old_conn_info_combination(self):
        """Secondary IPS are supported with new connection information."""
        self.configuration.target_secondary_ip_addresses = ['127.0.0.1']
        self.configuration.nvmeof_conn_info_version = 2
        FakeNVMeOFDriver(root_helper=utils.get_root_helper(),
                         configuration=self.configuration)

    def test_are_same_connector(self):
        res = self.target.are_same_connector({'nqn': 'nvme'}, {'nqn': 'nvme'})
        self.assertTrue(res)

    @ddt.data(({}, {}), ({}, {'nqn': 'nvmE'}), ({'nqn': 'nvmeE'}, {}),
              ({'nqn': 'nvme1'}, {'nqn': 'nvme2'}))
    @ddt.unpack
    def test_are_same_connector_different(self, a_conn_props, b_conn_props):
        res = self.target.are_same_connector(a_conn_props, b_conn_props)
        self.assertFalse(bool(res))

    def test_get_nvmeof_location(self):
        """Serialize connection information into location."""
        result = self.target.get_nvmeof_location(
            'ngn.subsys_name-vol_id', ['127.0.0.1'], 4420, 'tcp', 10)

        expected = '127.0.0.1:4420 tcp ngn.subsys_name-vol_id 10'
        self.assertEqual(expected, result)

    def test_get_nvmeof_location_multiple_ips(self):
        """Serialize connection information with multiple ips into location."""
        result = self.target.get_nvmeof_location(
            'ngn.subsys_name-vol_id', ['127.0.0.1', '192.168.1.1'], 4420,
            'tcp', 10)

        expected = '127.0.0.1,192.168.1.1:4420 tcp ngn.subsys_name-vol_id 10'
        self.assertEqual(expected, result)
