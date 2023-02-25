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

from cinder import exception
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
        self.target.share_targets = False
        fake_nvmet_lib.reset_mock()

    def test_supports_shared(self):
        self.assertTrue(self.target.SHARED_TARGET_SUPPORT)

    @mock.patch.object(nvmet.nvmeof.NVMeOF, 'initialize_connection')
    @mock.patch.object(nvmet.NVMET, '_map_volume')
    def test_initialize_connection_non_shared(self, mock_map, mock_init_conn):
        """Non shared initialize doesn't do anything (calls NVMeOF)."""
        res = self.target.initialize_connection(mock.sentinel.volume,
                                                mock.sentinel.connector)
        self.assertEqual(mock_init_conn.return_value, res)
        mock_init_conn.assert_called_once_with(mock.sentinel.volume,
                                               mock.sentinel.connector)
        mock_map.assert_not_called()

    @mock.patch.object(nvmet.NVMET, '_get_nvme_uuid')
    @mock.patch('os.path.exists')
    @mock.patch.object(nvmet.NVMET, '_get_connection_properties')
    @mock.patch.object(nvmet.nvmeof.NVMeOF, 'initialize_connection')
    @mock.patch.object(nvmet.NVMET, '_map_volume')
    def test_initialize_connection_shared(
            self, mock_map, mock_init_conn, mock_get_conn_props, mock_exists,
            mock_uuid):
        """When sharing, the initialization maps the volume."""
        self.mock_object(self.target, 'share_targets', True)
        mock_map.return_value = (mock.sentinel.nqn, mock.sentinel.nsid)
        vol = mock.Mock()
        res = self.target.initialize_connection(vol, mock.sentinel.connector)

        expected = {'driver_volume_type': 'nvmeof',
                    'data': mock_get_conn_props.return_value}
        self.assertEqual(expected, res)

        mock_init_conn.assert_not_called()
        mock_exists.assert_called_once_with(vol.provider_location)
        mock_map.assert_called_once_with(vol,
                                         vol.provider_location,
                                         mock.sentinel.connector)
        mock_uuid.assert_called_once_with(vol)
        mock_get_conn_props.assert_called_once_with(
            mock.sentinel.nqn,
            self.target.target_ips,
            self.target.target_port,
            self.target.nvme_transport_type,
            mock.sentinel.nsid,
            mock_uuid.return_value)

    @mock.patch.object(nvmet.NVMET, '_get_nvme_uuid')
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch.object(nvmet.NVMET, '_get_connection_properties')
    @mock.patch.object(nvmet.nvmeof.NVMeOF, 'initialize_connection')
    @mock.patch.object(nvmet.NVMET, '_map_volume')
    def test_initialize_connection_shared_no_path(
            self, mock_map, mock_init_conn, mock_get_conn_props, mock_exists,
            mock_uuid):
        """Fails if the provided path is not present in the system."""
        self.mock_object(self.target, 'share_targets', True)
        mock_map.return_value = (mock.sentinel.nqn, mock.sentinel.nsid)
        vol = mock.Mock()
        self.assertRaises(exception.InvalidConfigurationValue,
                          self.target.initialize_connection,
                          vol, mock.sentinel.connector)

        mock_init_conn.assert_not_called()
        mock_exists.assert_called_once_with(vol.provider_location)
        mock_map.assert_not_called()
        mock_uuid.assert_not_called()
        mock_get_conn_props.assert_not_called()

    @mock.patch.object(nvmet.NVMET, 'get_nvmeof_location')
    @mock.patch.object(nvmet.NVMET, '_map_volume')
    def test_create_export(self, mock_map, mock_location):
        """When not sharing, the export maps the volume."""
        mock_map.return_value = (mock.sentinel.nqn, mock.sentinel.nsid)

        res = self.target.create_export(mock.sentinel.context,
                                        mock.sentinel.vol,
                                        mock.sentinel.volume_path)

        self.assertEqual({'location': mock_location.return_value, 'auth': ''},
                         res)
        mock_map.assert_called_once_with(mock.sentinel.vol,
                                         mock.sentinel.volume_path)
        mock_location.assert_called_once_with(mock.sentinel.nqn,
                                              self.target.target_ips,
                                              self.target.target_port,
                                              self.target.nvme_transport_type,
                                              mock.sentinel.nsid)

    @mock.patch.object(nvmet.NVMET, 'get_nvmeof_location')
    @mock.patch.object(nvmet.NVMET, '_map_volume')
    def test_create_export_shared(self, mock_map, mock_location):
        """When sharing, the export just stores the volume path as location."""
        self.mock_object(self.target, 'share_targets', True)

        res = self.target.create_export(mock.sentinel.context,
                                        mock.sentinel.vol,
                                        mock.sentinel.volume_path)

        self.assertEqual({'location': mock.sentinel.volume_path, 'auth': ''},
                         res)
        mock_map.assert_not_called()
        mock_location.assert_not_called()

    @mock.patch('oslo_concurrency.lockutils.lock')
    @mock.patch.object(nvmet.NVMET, '_get_nvme_uuid')
    @mock.patch.object(nvmet.NVMET, '_ensure_port_exports')
    @mock.patch.object(nvmet.NVMET, '_ensure_subsystem_exists')
    @mock.patch.object(nvmet.NVMET, '_get_target_nqn')
    def test__map_volume(self, mock_nqn, mock_subsys, mock_port, mock_uuid,
                         mock_lock):
        """Normal volume mapping."""
        vol = mock.Mock()
        res = self.target._map_volume(vol, mock.sentinel.volume_path,
                                      mock.sentinel.connector)

        expected = (mock_nqn.return_value, mock_subsys.return_value)
        self.assertEqual(res, expected)

        mock_nqn.assert_called_once_with(vol.id, mock.sentinel.connector)
        mock_uuid.assert_called_once_with(vol)
        mock_subsys.assert_called_once_with(mock_nqn.return_value,
                                            mock.sentinel.volume_path,
                                            mock_uuid.return_value)
        mock_port.assert_called_once_with(mock_nqn.return_value,
                                          self.target.target_ips,
                                          self.target.target_port,
                                          self.target.nvme_transport_type,
                                          self.target.nvmet_port_id)
        mock_lock.assert_called()

    @ddt.data((ValueError, None), (None, IndexError))
    @ddt.unpack
    @mock.patch('oslo_concurrency.lockutils.lock')
    @mock.patch.object(nvmet.NVMET, '_get_nvme_uuid')
    @mock.patch.object(nvmet.NVMET, '_ensure_port_exports')
    @mock.patch.object(nvmet.NVMET, '_ensure_subsystem_exists')
    @mock.patch.object(nvmet.NVMET, '_get_target_nqn')
    def test__map_volume_error(self, subsys_effect, port_effect, mock_nqn,
                               mock_subsys, mock_port, mock_uuid, mock_lock):
        """Failing create target executing subsystem or port creation."""
        mock_subsys.side_effect = subsys_effect
        mock_port.side_effect = port_effect
        mock_nqn.return_value = mock.sentinel.nqn
        mock_uuid.return_value = mock.sentinel.uuid
        vol = mock.Mock()

        self.assertRaises(nvmet.NVMETTargetAddError,
                          self.target._map_volume,
                          vol,
                          mock.sentinel.volume_path,
                          mock.sentinel.connector)

        mock_nqn.assert_called_once_with(vol.id, mock.sentinel.connector)
        mock_uuid.assert_called_once_with(vol)
        mock_subsys.assert_called_once_with(mock.sentinel.nqn,
                                            mock.sentinel.volume_path,
                                            mock.sentinel.uuid)
        if subsys_effect:
            mock_port.assert_not_called()
        else:
            mock_port.assert_called_once_with(mock.sentinel.nqn,
                                              self.target.target_ips,
                                              self.target.target_port,
                                              self.target.nvme_transport_type,
                                              self.target.nvmet_port_id)
        mock_lock.assert_called()

    @mock.patch.object(nvmet.NVMET, '_ensure_namespace_exists')
    @mock.patch.object(priv_nvmet, 'Subsystem')
    def test__ensure_subsystem_exists_already_exists(self, mock_subsys,
                                                     mock_namespace):
        """Skip subsystem creation if already exists."""
        nqn = 'nqn.nvme-subsystem-1-uuid'
        res = self.target._ensure_subsystem_exists(nqn,
                                                   mock.sentinel.vol_path,
                                                   mock.sentinel.uuid)
        self.assertEqual(mock_namespace.return_value, res)
        mock_subsys.assert_called_once_with(nqn)
        mock_subsys.setup.assert_not_called()
        mock_namespace.assert_called_once_with(mock_subsys.return_value,
                                               mock.sentinel.vol_path,
                                               mock.sentinel.uuid)

    @mock.patch.object(nvmet.NVMET, '_ensure_namespace_exists')
    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch.object(priv_nvmet, 'Subsystem')
    def test__ensure_subsystem_exists(self, mock_subsys, mock_uuid,
                                      mock_namespace):
        """Create subsystem when it doesn't exist."""
        mock_subsys.side_effect = priv_nvmet.NotFound
        mock_uuid.return_value = 'uuid'
        nqn = 'nqn.nvme-subsystem-1-uuid'
        self.target._ensure_subsystem_exists(nqn,
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
                            'nsid': self.target.nvmet_ns_id}],
            'nqn': nqn
        }
        mock_subsys.setup.assert_called_once_with(expected_section)
        mock_namespace.assert_not_called()

    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    def test__namespace_dict(self, mock_uuid):
        """For not shared nguid is randomly generated."""
        res = self.target._namespace_dict(mock.sentinel.uuid,
                                          mock.sentinel.volume_path,
                                          mock.sentinel.ns_id)
        expected = {"device": {"nguid": str(mock_uuid.return_value),
                               "uuid": mock.sentinel.uuid,
                               "path": mock.sentinel.volume_path},
                    "enable": 1,
                    "nsid": mock.sentinel.ns_id}
        self.assertEqual(expected, res)
        mock_uuid.assert_called_once()

    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    def test__namespace_dict_shared(self, mock_uuid):
        """For shared uuid = nguid."""
        self.mock_object(self.target, 'share_targets', True)
        res = self.target._namespace_dict(mock.sentinel.uuid,
                                          mock.sentinel.volume_path,
                                          mock.sentinel.ns_id)
        expected = {"device": {"nguid": mock.sentinel.uuid,
                               "uuid": mock.sentinel.uuid,
                               "path": mock.sentinel.volume_path},
                    "enable": 1,
                    "nsid": mock.sentinel.ns_id}
        self.assertEqual(expected, res)
        mock_uuid.assert_not_called

    def test__ensure_namespace_exist_exists(self):
        """Nothing to do if the namespace is already mapped."""
        base_path = '/dev/stack-volumes-lvmdriver-1/volume-'
        volume_path = f'{base_path}uuid2'
        subsys = mock.Mock()
        ns_other = mock.Mock(**{'get_attr.return_value': f'{base_path}uuid1'})
        ns_found = mock.Mock(**{'get_attr.return_value': volume_path})
        # nw_other appears twice to confirm we stop when found
        subsys.namespaces = [ns_other, ns_found, ns_other]
        res = self.target._ensure_namespace_exists(subsys, volume_path,
                                                   mock.sentinel.uuid)
        self.assertEqual(ns_found.nsid, res)
        ns_other.get_attr.assert_called_once_with('device', 'path')
        ns_found.get_attr.assert_called_once_with('device', 'path')

    @mock.patch.object(priv_nvmet, 'Namespace')
    @mock.patch.object(nvmet.NVMET, '_namespace_dict')
    @mock.patch.object(nvmet.NVMET, '_get_available_namespace_id')
    def test__ensure_namespace_exist_create(self, mock_get_nsid, mock_ns_dict,
                                            mock_ns):
        """Create the namespace when the path is not mapped yet."""
        base_path = '/dev/stack-volumes-lvmdriver-1/volume-'
        subsys = mock.Mock()
        ns_other = mock.Mock(**{'get_attr.return_value': f'{base_path}uuid1'})
        subsys.namespaces = [ns_other]
        res = self.target._ensure_namespace_exists(subsys,
                                                   mock.sentinel.volume_path,
                                                   mock.sentinel.uuid)
        self.assertEqual(mock_get_nsid.return_value, res)
        ns_other.get_attr.assert_called_once_with('device', 'path')
        mock_get_nsid.assert_called_once_with(subsys)
        mock_ns_dict.assert_called_once_with(mock.sentinel.uuid,
                                             mock.sentinel.volume_path,
                                             mock_get_nsid.return_value)
        mock_ns.setup.assert_called_once_with(subsys,
                                              mock_ns_dict.return_value)

    def test__get_available_namespace_id(self):
        """For non shared we always return the value from the config."""
        res = self.target._get_available_namespace_id(mock.Mock())
        self.assertEqual(self.target.nvmet_ns_id, res)

    def test__get_available_namespace_id_none_used(self):
        """For shared, on empty subsystem return the configured value."""
        self.mock_object(self.target, 'share_targets', True)
        subsys = mock.Mock(namespaces=[])
        res = self.target._get_available_namespace_id(subsys)
        self.assertEqual(self.target.nvmet_ns_id, res)

    def test__get_available_namespace_id_no_gaps(self):
        """For shared, if there are no gaps in ids return next."""
        self.mock_object(self.target, 'share_targets', True)
        expected = self.target.nvmet_ns_id + 2
        subsys = mock.Mock(namespaces=[mock.Mock(nsid=expected - 1),
                                       mock.Mock(nsid=expected - 2)])
        res = self.target._get_available_namespace_id(subsys)
        self.assertEqual(expected, res)

    def test__get_available_namespace_id_gap_value(self):
        """For shared, if there is a gap any of them is valid."""
        self.mock_object(self.target, 'share_targets', True)
        lower = self.target.nvmet_ns_id
        subsys = mock.Mock(namespaces=[mock.Mock(nsid=lower + 3),
                                       mock.Mock(nsid=lower)])
        res = self.target._get_available_namespace_id(subsys)
        self.assertTrue(res in [lower + 2, lower + 1])

    @mock.patch.object(priv_nvmet, 'Port')
    def test__ensure_port_exports_already_does(self, mock_port):
        """Skips port creation and subsystem export since they both exist."""
        nqn = 'nqn.nvme-subsystem-1-uuid'
        port_id = 1
        mock_port.return_value.subsystems = [nqn]
        self.target._ensure_port_exports(nqn,
                                         [mock.sentinel.addr],
                                         mock.sentinel.port,
                                         mock.sentinel.transport,
                                         port_id)
        mock_port.assert_called_once_with(port_id)
        mock_port.setup.assert_not_called()
        mock_port.return_value.add_subsystem.assert_not_called()

    @mock.patch.object(priv_nvmet, 'Port')
    def test__ensure_port_exports_port_exists_not_exported(self, mock_port):
        """Skips port creation if exists but exports subsystem."""
        nqn = 'nqn.nvme-subsystem-1-vol-2-uuid'
        port_id = 1
        mock_port.return_value.subsystems = ['nqn.nvme-subsystem-1-vol-1-uuid']
        self.target._ensure_port_exports(nqn,
                                         [mock.sentinel.addr],
                                         mock.sentinel.port,
                                         mock.sentinel.transport,
                                         port_id)
        mock_port.assert_called_once_with(port_id)
        mock_port.setup.assert_not_called()
        mock_port.return_value.add_subsystem.assert_called_once_with(nqn)

    @mock.patch.object(priv_nvmet, 'Port')
    def test__ensure_port_exports_port(self, mock_port):
        """Creates the port and export the subsystem when they don't exist."""
        nqn = 'nqn.nvme-subsystem-1-vol-2-uuid'
        port_id = 1
        mock_port.side_effect = priv_nvmet.NotFound
        self.target._ensure_port_exports(nqn,
                                         [mock.sentinel.addr,
                                          mock.sentinel.addr2],
                                         mock.sentinel.port,
                                         mock.sentinel.transport,
                                         port_id)
        new_port1 = {'addr': {'adrfam': 'ipv4',
                              'traddr': mock.sentinel.addr,
                              'treq': 'not specified',
                              'trsvcid': mock.sentinel.port,
                              'trtype': mock.sentinel.transport},
                     'portid': port_id,
                     'referrals': [],
                     'subsystems': [nqn]}
        new_port2 = new_port1.copy()
        new_port2['portid'] = port_id + 1
        new_port2['addr'] = new_port1['addr'].copy()
        new_port2['addr']['traddr'] = mock.sentinel.addr2

        self.assertEqual(2, mock_port.call_count)
        self.assertEqual(2, mock_port.setup.call_count)
        mock_port.assert_has_calls([
            mock.call(port_id),
            mock.call.setup(self.target._nvmet_root, new_port1),
            mock.call(port_id + 1),
            mock.call.setup(self.target._nvmet_root, new_port2)
        ])
        mock_port.return_value.assert_not_called()

    @mock.patch.object(nvmet.NVMET, '_locked_unmap_volume')
    def test_terminate_connection(self, mock_unmap):
        """For non shared there's nothing to do."""
        self.target.terminate_connection(mock.sentinel.vol,
                                         mock.sentinel.connector)
        mock_unmap.assert_not_called()

    @mock.patch.object(nvmet.NVMET, '_locked_unmap_volume')
    def test_terminate_connection_shared(self, mock_unmap):
        """For shared the volume must be unmapped."""
        self.mock_object(self.target, 'share_targets', True)
        vol = mock.Mock()
        self.target.terminate_connection(vol,
                                         mock.sentinel.connector)
        mock_unmap.assert_called_once_with(vol,
                                           mock.sentinel.connector)

    @mock.patch.object(nvmet.NVMET, '_locked_unmap_volume')
    def test_remove_export(self, mock_unmap):
        """For non shared the volume must be unmapped."""
        vol = mock.Mock()
        self.target.remove_export(mock.sentinel.context,
                                  vol)
        mock_unmap.assert_called_once_with(vol)

    @mock.patch.object(nvmet.NVMET, '_locked_unmap_volume')
    def test_remove_export_shared(self, mock_unmap):
        """For shared there's nothing to do."""
        self.mock_object(self.target, 'share_targets', True)
        self.target.remove_export(mock.sentinel.context,
                                  mock.sentinel.vol)
        mock_unmap.assert_not_called()

    @mock.patch('oslo_concurrency.lockutils.lock')
    @mock.patch.object(nvmet.NVMET, '_get_nqns_for_location', return_value=[])
    @mock.patch.object(nvmet.NVMET, '_get_target_nqn')
    @mock.patch.object(nvmet.NVMET, '_unmap_volume')
    def test__locked_unmap_volume_no_nqn(self, mock_unmap, mock_nqn, mock_nqns,
                                         mock_lock):
        """Nothing to do with no subsystem when sharing and no connector."""
        self.mock_object(self.target, 'share_targets', True)

        vol = mock.Mock()
        self.target._locked_unmap_volume(vol, connector=None)

        mock_lock.assert_called()
        mock_nqn.assert_not_called()
        mock_nqns.assert_called_once_with(vol.provider_location)
        mock_unmap.assert_not_called()

    @mock.patch('oslo_concurrency.lockutils.lock')
    @mock.patch.object(nvmet.NVMET, '_get_nqns_for_location')
    @mock.patch.object(nvmet.NVMET, '_get_target_nqn')
    @mock.patch.object(nvmet.NVMET, '_unmap_volume')
    def test__locked_unmap_volume_non_shared(self, mock_unmap, mock_nqn,
                                             mock_nqns, mock_lock):
        """Unmap locked with non sharing and no connector."""
        vol = mock.Mock()
        self.target._locked_unmap_volume(vol, connector=None)

        mock_lock.assert_called()
        mock_nqn.assert_called_once_with(vol.id, None)
        mock_nqns.assert_not_called()
        mock_unmap.assert_called_once_with(vol, mock_nqn.return_value)

    @mock.patch('oslo_concurrency.lockutils.lock')
    @mock.patch.object(nvmet.NVMET, '_get_nqns_for_location')
    @mock.patch.object(nvmet.NVMET, '_get_target_nqn')
    @mock.patch.object(nvmet.NVMET, '_unmap_volume')
    def test__locked_unmap_volume_shared_multiple(self, mock_unmap, mock_nqn,
                                                  mock_nqns, mock_lock):
        """Unmap locked with sharing and no connector, having multiple nqns."""
        self.mock_object(self.target, 'share_targets', True)
        vol = mock.Mock()
        mock_nqns.return_value = [mock.sentinel.nqn1, mock.sentinel.nqn2]

        self.target._locked_unmap_volume(vol, connector=None)

        mock_lock.assert_called()
        mock_nqn.assert_not_called()
        mock_nqns.assert_called_once_with(vol.provider_location)

        expected = [mock.call(vol, mock.sentinel.nqn1),
                    mock.call(vol, mock.sentinel.nqn2)]
        mock_unmap.assert_has_calls(expected)
        self.assertEqual(2, mock_unmap.call_count)

    @mock.patch.object(nvmet.NVMET, '_get_target_nqn')
    @mock.patch.object(priv_nvmet, 'Subsystem')
    def test__unmap_volume_no_subsys(self, mock_subsys, mock_nqn):
        """Nothing to do it there is no subsystem."""
        mock_subsys.side_effect = priv_nvmet.NotFound
        vol = mock.Mock()
        # This port is used just to confirm we don't reach that part
        port = mock.Mock(subsystems=[mock.sentinel.port])
        self.mock_object(priv_nvmet.Root, 'ports', [port])

        self.target._unmap_volume(vol, mock.sentinel.nqn)
        mock_subsys.assert_called_once_with(mock.sentinel.nqn)

        port.remove_subsystem.assert_not_called()

    @mock.patch.object(priv_nvmet, 'Subsystem')
    def test__unmap_volume_not_shared(self, mock_subsys):
        """Non shared assumes the subsystem is empty."""
        vol = mock.Mock()
        # The ns is used to confirm we don't check it
        ns = mock.Mock(**{'get_attr.return_value': vol.provider_location})
        subsys = mock_subsys.return_value
        subsys.nqn = mock.sentinel.nqn
        subsys.namespaces = [ns]

        port = mock.Mock(subsystems=[subsys.nqn])
        self.mock_object(priv_nvmet.Root, 'ports', [port])

        self.target._unmap_volume(vol, mock.sentinel.nqn)

        mock_subsys.assert_called_once_with(mock.sentinel.nqn)

        ns.get_attr.assert_not_called()
        ns.delete.assert_not_called()

        port.remove_subsystem.assert_called_once_with(mock.sentinel.nqn)
        subsys.delete.assert_called_once_with()

    @mock.patch.object(priv_nvmet, 'Subsystem')
    def test__unmap_volume_shared_more_ns(self, mock_subsys):
        """For shared don't unexport subsys if there are other ns."""
        self.mock_object(self.target, 'share_targets', True)
        vol = mock.Mock()

        ns = mock.Mock(**{'get_attr.return_value': vol.provider_location})
        subsys = mock_subsys.return_value
        subsys.namespaces = [ns]

        # Use this port to confirm we don't reach that point
        port = mock.Mock(subsystems=[subsys])
        self.mock_object(priv_nvmet.Root, 'ports', [port])

        self.target._unmap_volume(vol, mock.sentinel.nqn)

        mock_subsys.assert_called_once_with(mock.sentinel.nqn)

        ns.get_attr.assert_called_once_with('device', 'path')
        ns.delete.assert_called_once_with()

        port.remove_subsystem.assert_not_called()
        mock_subsys.return_value.delete.assert_not_called()

    @mock.patch('oslo_concurrency.lockutils.lock')
    @mock.patch.object(nvmet.NVMET, '_get_target_nqn')
    @mock.patch.object(priv_nvmet, 'Subsystem')
    def test__unmap_volume_shared_last_ns(self, mock_subsys, mock_nqn,
                                          mock_lock):
        """For shared unexport subsys if there are no other ns."""
        self.mock_object(self.target, 'share_targets', True)
        vol = mock.Mock()

        ns = mock.Mock(**{'get_attr.return_value': vol.provider_location})
        nss = [ns]
        ns.delete.side_effect = nss.clear
        subsys = mock_subsys.return_value
        subsys.nqn = mock.sentinel.nqn
        subsys.namespaces = nss

        port = mock.Mock(subsystems=[subsys.nqn])
        self.mock_object(priv_nvmet.Root, 'ports', [port])

        self.target._unmap_volume(vol, mock.sentinel.nqn)

        mock_subsys.assert_called_once_with(mock.sentinel.nqn)

        ns.get_attr.assert_called_once_with('device', 'path')
        ns.delete.assert_called_once_with()

        port.remove_subsystem.assert_called_once_with(mock.sentinel.nqn)
        mock_subsys.return_value.delete.assert_called_once_with()

    def test__get_target_nqn(self):
        """Non shared uses volume id for subsystem name."""
        res = self.target._get_target_nqn('volume_id', None)
        self.assertEqual('nqn.nvme-subsystem-1-volume_id', res)

    def test__get_target_nqn_shared(self):
        """Shared uses connector's hostname for subsystem name."""
        self.mock_object(self.target, 'share_targets', True)
        res = self.target._get_target_nqn('volume_id', {'host': 'localhost'})
        self.assertEqual('nqn.nvme-subsystem-1-localhost', res)

    def test__get_nvme_uuid(self):
        vol = mock.Mock()
        res = self.target._get_nvme_uuid(vol)
        self.assertEqual(vol.name_id, res)

    def test__get_nqns_for_location_no_subsystems(self):
        self.mock_object(self.target._nvmet_root, 'subsystems', iter([]))
        res = self.target._get_nqns_for_location(mock.sentinel.location)
        self.assertListEqual([], res)

    def test__get_nqns_for_location_no_subsystems_found(self):
        ns1 = mock.Mock(**{'get_attr.return_value': mock.sentinel.location1})
        subsys1 = mock.Mock(namespaces=iter([ns1]))

        ns2 = mock.Mock(**{'get_attr.return_value': mock.sentinel.location2})
        subsys2 = mock.Mock(namespaces=iter([ns2]))

        subsys = iter([subsys1, subsys2])
        self.mock_object(self.target._nvmet_root, 'subsystems', subsys)

        res = self.target._get_nqns_for_location(mock.sentinel.location3)

        self.assertListEqual([], res)
        ns1.get_attr.assert_called_once_with('device', 'path')
        ns2.get_attr.assert_called_once_with('device', 'path')

    def test__get_nqns_for_location_subsystems_found(self):
        ns1 = mock.Mock(**{'get_attr.return_value': mock.sentinel.location1})
        subsys1 = mock.Mock(namespaces=iter([ns1]))

        ns2 = mock.Mock(**{'get_attr.return_value': mock.sentinel.location2})
        ns1b = mock.Mock(**{'get_attr.return_value': mock.sentinel.location1})
        ns3 = mock.Mock(**{'get_attr.return_value': mock.sentinel.location3})
        subsys2 = mock.Mock(namespaces=iter([ns2, ns1b, ns3]))

        ns4 = mock.Mock(**{'get_attr.return_value': mock.sentinel.location4})
        subsys3 = mock.Mock(namespaces=iter([ns4]))

        subsys4 = mock.Mock(namespaces=iter([]))

        subsys = iter([subsys1, subsys2, subsys3, subsys4])
        self.mock_object(self.target._nvmet_root, 'subsystems', subsys)

        res = self.target._get_nqns_for_location(mock.sentinel.location1)

        self.assertListEqual([subsys1.nqn, subsys2.nqn, subsys4.nqn], res)
        ns1.get_attr.assert_called_once_with('device', 'path')
        ns2.get_attr.assert_called_once_with('device', 'path')
        ns1b.get_attr.assert_called_once_with('device', 'path')
        ns3.get_attr.assert_not_called()
        ns4.get_attr.assert_called_once_with('device', 'path')
