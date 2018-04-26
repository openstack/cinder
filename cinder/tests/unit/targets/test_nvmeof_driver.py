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

from oslo_utils import timeutils

from cinder import context
from cinder import exception
from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume.targets import nvmeof


class FakeNVMeOFDriver(nvmeof.NVMeOF):
    def __init__(self, *args, **kwargs):
        super(FakeNVMeOFDriver, self).__init__(*args, **kwargs)

    def create_nvmeof_target(
            self, target_name, target_ip, target_port,
            transport_type, ns_id, volume_path):
        pass

    def delete_nvmeof_target(self, target_name):
        pass


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
                     self.target_ip,
                     self.target_port,
                     self.nvme_transport_type,
                     self.nvmet_ns_id
                 ),
             'provider_auth': None,
             'provider_geometry': None,
             'created_at': timeutils.utcnow(),
             'host': 'fake_host@lvm#lvm'})

    def test_initialize_connection(self):
        mock_connector = {'initiator': 'fake_init'}
        mock_testvol = self.testvol
        expected_return = {
            'driver_volume_type': 'nvmeof',
            'data': self.target._get_connection_properties(mock_testvol)
        }
        self.assertEqual(expected_return,
                         self.target.initialize_connection(mock_testvol,
                                                           mock_connector))

    @mock.patch.object(FakeNVMeOFDriver, 'create_nvmeof_target')
    def test_create_export(self, mock_create_nvme_target):
        ctxt = context.get_admin_context()
        self.target.create_export(ctxt, self.testvol, self.testvol_path)
        mock_create_nvme_target.assert_called_once_with(
            self.fake_volume_id,
            self.configuration.target_prefix,
            self.target_ip,
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

    def test_get_connection_properties(self):
        expected_return = {
            'target_portal': self.target_ip,
            'target_port': str(self.target_port),
            'nqn': "ngn.%s-%s" % (
                self.nvmet_subsystem_name, self.fake_volume_id),
            'transport_type': self.nvme_transport_type,
            'ns_id': str(self.nvmet_ns_id)
        }
        self.assertEqual(expected_return,
                         self.target._get_connection_properties(self.testvol))

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
        self.assertRaises(exception.UnsupportedNVMETProtocol,
                          FakeNVMeOFDriver,
                          root_helper=utils.get_root_helper(),
                          configuration=self.configuration)
