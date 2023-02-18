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

from cinder.tests.unit.privsep.targets import fake_nvmet_lib
from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume.targets import nvmet
# This must go after fake_nvmet_lib has been imported (thus the noqa)
from cinder.privsep.targets import nvmet as priv_nvmet  # noqa


@ddt.ddt
class TestNVMETDriver(tf.TargetDriverFixture):

    def setUp(self):
        super(TestNVMETDriver, self).setUp()

        self.configuration.target_prefix = 'nvme-subsystem-1'
        self.configuration.target_protocol = 'nvmet_rdma'
        self.target = nvmet.NVMET(root_helper=utils.get_root_helper(),
                                  configuration=self.configuration)
        fake_nvmet_lib.reset_mock()

    @mock.patch.object(nvmet.NVMET, '_get_nvme_uuid')
    @mock.patch.object(nvmet.NVMET, 'get_nvmeof_location')
    @mock.patch.object(nvmet.NVMET, '_ensure_port_exports')
    @mock.patch.object(nvmet.NVMET, '_ensure_subsystem_exists')
    @mock.patch.object(nvmet.NVMET, '_get_target_nqn')
    def test_create_export(self, mock_nqn, mock_subsys, mock_port,
                           mock_location, mock_uuid):
        """Normal create target execution."""
        mock_nqn.return_value = mock.sentinel.nqn
        mock_uuid.return_value = mock.sentinel.uuid
        vol = mock.Mock()

        res = self.target.create_export(mock.sentinel.context,
                                        vol,
                                        mock.sentinel.volume_path)

        self.assertEqual({'location': mock_location.return_value, 'auth': ''},
                         res)
        mock_nqn.assert_called_once_with(vol.id)
        mock_uuid.assert_called_once_with(vol)
        mock_subsys.assert_called_once_with(mock.sentinel.nqn,
                                            self.target.nvmet_ns_id,
                                            mock.sentinel.volume_path,
                                            mock.sentinel.uuid)
        mock_port.assert_called_once_with(mock.sentinel.nqn,
                                          self.target.target_ip,
                                          self.target.target_port,
                                          self.target.nvme_transport_type,
                                          self.target.nvmet_port_id)

        mock_location.assert_called_once_with(mock.sentinel.nqn,
                                              self.target.target_ip,
                                              self.target.target_port,
                                              self.target.nvme_transport_type,
                                              self.target.nvmet_ns_id)

    @ddt.data((ValueError, None), (None, IndexError))
    @ddt.unpack
    @mock.patch.object(nvmet.NVMET, '_get_nvme_uuid')
    @mock.patch.object(nvmet.NVMET, 'get_nvmeof_location')
    @mock.patch.object(nvmet.NVMET, '_ensure_port_exports')
    @mock.patch.object(nvmet.NVMET, '_ensure_subsystem_exists')
    @mock.patch.object(nvmet.NVMET, '_get_target_nqn')
    def test_create_export_error(self, subsys_effect, port_effect,
                                 mock_nqn, mock_subsys, mock_port,
                                 mock_location, mock_uuid):
        """Failing create target executing subsystem or port creation."""
        mock_subsys.side_effect = subsys_effect
        mock_port.side_effect = port_effect
        mock_nqn.return_value = mock.sentinel.nqn
        mock_uuid.return_value = mock.sentinel.uuid
        vol = mock.Mock()

        self.assertRaises(nvmet.NVMETTargetAddError,
                          self.target.create_export,
                          mock.sentinel.context,
                          vol,
                          mock.sentinel.volume_path)

        mock_nqn.assert_called_once_with(vol.id)
        mock_uuid.assert_called_once_with(vol)
        mock_subsys.assert_called_once_with(mock.sentinel.nqn,
                                            self.target.nvmet_ns_id,
                                            mock.sentinel.volume_path,
                                            mock.sentinel.uuid)
        if subsys_effect:
            mock_port.assert_not_called()
        else:
            mock_port.assert_called_once_with(mock.sentinel.nqn,
                                              self.target.target_ip,
                                              self.target.target_port,
                                              self.target.nvme_transport_type,
                                              self.target.nvmet_port_id)
        mock_location.assert_not_called()

    @mock.patch.object(priv_nvmet, 'Subsystem')
    def test__ensure_subsystem_exists_already_exists(self, mock_subsys):
        """Skip subsystem creation if already exists."""
        nqn = 'nqn.nvme-subsystem-1-uuid'
        self.target._ensure_subsystem_exists(nqn, mock.sentinel.ns_id,
                                             mock.sentinel.vol_path,
                                             mock.sentinel.uuid)
        mock_subsys.assert_called_once_with(nqn)
        mock_subsys.setup.assert_not_called()

    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch.object(priv_nvmet, 'Subsystem')
    def test__ensure_subsystem_exists(self, mock_subsys, mock_uuid):
        """Create subsystem when it doesn't exist."""
        mock_subsys.side_effect = priv_nvmet.NotFound
        mock_uuid.return_value = 'uuid'
        nqn = 'nqn.nvme-subsystem-1-uuid'
        self.target._ensure_subsystem_exists(nqn, mock.sentinel.ns_id,
                                             mock.sentinel.vol_path,
                                             mock.sentinel.uuid)
        mock_subsys.assert_called_once_with(nqn)
        expected_section = {
            'allowed_hosts': [],
            'attr': {'allow_any_host': '1'},
            'namespaces': [{'device': {'nguid': 'uuid',
                                       'uuid': mock.sentinel.uuid,
                                       'path': mock.sentinel.vol_path},
                            'enable': 1,
                            'nsid': mock.sentinel.ns_id}],
            'nqn': nqn
        }
        mock_subsys.setup.assert_called_once_with(expected_section)

    @mock.patch.object(priv_nvmet, 'Port')
    def test__ensure_port_exports_already_does(self, mock_port):
        """Skips port creation and subsystem export since they both exist."""
        nqn = 'nqn.nvme-subsystem-1-uuid'
        mock_port.return_value.subsystems = [nqn]
        self.target._ensure_port_exports(nqn,
                                         mock.sentinel.addr,
                                         mock.sentinel.port,
                                         mock.sentinel.transport,
                                         mock.sentinel.port_id)
        mock_port.assert_called_once_with(mock.sentinel.port_id)
        mock_port.setup.assert_not_called()
        mock_port.return_value.add_subsystem.assert_not_called()

    @mock.patch.object(priv_nvmet, 'Port')
    def test__ensure_port_exports_port_exists_not_exported(self, mock_port):
        """Skips port creation if exists but exports subsystem."""
        nqn = 'nqn.nvme-subsystem-1-vol-2-uuid'
        mock_port.return_value.subsystems = ['nqn.nvme-subsystem-1-vol-1-uuid']
        self.target._ensure_port_exports(nqn,
                                         mock.sentinel.addr,
                                         mock.sentinel.port,
                                         mock.sentinel.transport,
                                         mock.sentinel.port_id)
        mock_port.assert_called_once_with(mock.sentinel.port_id)
        mock_port.setup.assert_not_called()
        mock_port.return_value.add_subsystem.assert_called_once_with(nqn)

    @mock.patch.object(priv_nvmet, 'Port')
    def test__ensure_port_exports_port(self, mock_port):
        """Creates the port and export the subsystem when they don't exist."""
        nqn = 'nqn.nvme-subsystem-1-vol-2-uuid'
        mock_port.side_effect = priv_nvmet.NotFound
        self.target._ensure_port_exports(nqn,
                                         mock.sentinel.addr,
                                         mock.sentinel.port,
                                         mock.sentinel.transport,
                                         mock.sentinel.port_id)
        mock_port.assert_called_once_with(mock.sentinel.port_id)
        new_port = {'addr': {'adrfam': 'ipv4',
                             'traddr': mock.sentinel.addr,
                             'treq': 'not specified',
                             'trsvcid': mock.sentinel.port,
                             'trtype': mock.sentinel.transport},
                    'portid': mock.sentinel.port_id,
                    'referrals': [],
                    'subsystems': [nqn]}
        mock_port.setup.assert_called_once_with(self.target._nvmet_root,
                                                new_port)
        mock_port.return_value.assert_not_called()

    @mock.patch.object(nvmet.NVMET, 'delete_nvmeof_target')
    def test_remove_export(self, mock_delete_target):
        """Test that the nvmeof class calls the nvmet method."""
        res = self.target.remove_export(mock.sentinel.ctxt,
                                        mock.sentinel.volume)
        self.assertEqual(mock_delete_target.return_value, res)
        mock_delete_target.assert_called_once_with(mock.sentinel.volume)

    @mock.patch.object(priv_nvmet, 'Subsystem')
    @mock.patch.object(nvmet.NVMET, '_get_target_nqn')
    def test_delete_nvmeof_target_nothing_present(self, mock_nqn, mock_subsys):
        """Delete doesn't do anything because there is nothing to do."""
        mock_nqn.return_value = mock.sentinel.nqn
        mock_subsys.side_effect = priv_nvmet.NotFound

        port1 = mock.Mock(subsystems=[])
        port2 = mock.Mock(subsystems=['subs1'])
        self.mock_object(priv_nvmet.Root, 'ports', [port1, port2])

        volume = mock.Mock(id='vol-uuid')
        self.target.delete_nvmeof_target(volume)

        mock_nqn.assert_called_once_with(volume.id)
        port1.remove_subsystem.assert_not_called()
        port2.remove_subsystem.assert_not_called()
        mock_subsys.delete.assert_not_called()

    @mock.patch.object(priv_nvmet, 'Subsystem')
    @mock.patch.object(nvmet.NVMET, '_get_target_nqn')
    def test_delete_nvmeof_target(self, mock_nqn, mock_subsys):
        """Delete removes subsystems from port and the subsystem."""
        mock_nqn.return_value = mock.sentinel.nqn

        port1 = mock.Mock(subsystems=[])
        port2 = mock.Mock(subsystems=[mock.sentinel.nqn])
        port3 = mock.Mock(subsystems=['subs1'])
        self.mock_object(priv_nvmet.Root, 'ports', [port1, port2, port3])

        volume = mock.Mock(id='vol-uuid')
        self.target.delete_nvmeof_target(volume)

        mock_nqn.assert_called_once_with(volume.id)
        port1.remove_subsystem.assert_not_called()
        port2.remove_subsystem.assert_called_once_with(mock.sentinel.nqn)
        port3.remove_subsystem.assert_not_called()
        mock_subsys.assert_called_once_with(mock.sentinel.nqn)
        mock_subsys.return_value.delete.assert_called_once_with()

    @mock.patch.object(priv_nvmet, 'Root')
    def test__get_available_nvmf_subsystems(self, mock_root):
        res = self.target._get_available_nvmf_subsystems()
        mock_dump = mock_root.return_value.dump
        self.assertEqual(mock_dump.return_value, res)
        mock_dump.assert_called_once_with()

    def test__get_target_nqn(self):
        res = self.target._get_target_nqn('volume_id')
        self.assertEqual('nqn.nvme-subsystem-1-volume_id', res)

    def test__get_nvme_uuid(self):
        vol = mock.Mock()
        res = self.target._get_nvme_uuid(vol)
        self.assertEqual(vol.name_id, res)
