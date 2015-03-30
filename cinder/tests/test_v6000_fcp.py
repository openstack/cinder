# Copyright 2014 Violin Memory, Inc.
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

"""
Tests for Violin Memory 6000 Series All-Flash Array Fibrechannel Driver
"""

import mock
from oslo_utils import units

from cinder import context
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import test
from cinder.tests import fake_vmem_client as vmemclient
from cinder.volume import configuration as conf
from cinder.volume.drivers.violin import v6000_common
from cinder.volume.drivers.violin import v6000_fcp

VOLUME_ID = "abcdabcd-1234-abcd-1234-abcdeffedcba"
VOLUME = {
    "name": "volume-" + VOLUME_ID,
    "id": VOLUME_ID,
    "display_name": "fake_volume",
    "size": 2,
    "host": "irrelevant",
    "volume_type": None,
    "volume_type_id": None,
}
SNAPSHOT_ID = "abcdabcd-1234-abcd-1234-abcdeffedcbb"
SNAPSHOT = {
    "name": "snapshot-" + SNAPSHOT_ID,
    "id": SNAPSHOT_ID,
    "volume_id": VOLUME_ID,
    "volume_name": "volume-" + VOLUME_ID,
    "volume_size": 2,
    "display_name": "fake_snapshot",
    "volume": VOLUME,
}
SRC_VOL_ID = "abcdabcd-1234-abcd-1234-abcdeffedcbc"
SRC_VOL = {
    "name": "volume-" + SRC_VOL_ID,
    "id": SRC_VOL_ID,
    "display_name": "fake_src_vol",
    "size": 2,
    "host": "irrelevant",
    "volume_type": None,
    "volume_type_id": None,
}
INITIATOR_IQN = "iqn.1111-22.org.debian:11:222"
CONNECTOR = {
    "initiator": INITIATOR_IQN,
    "host": "irrelevant",
    'wwpns': [u'50014380186b3f65', u'50014380186b3f67'],
}
FC_TARGET_WWPNS = [
    '31000024ff45fb22', '21000024ff45fb23',
    '51000024ff45f1be', '41000024ff45f1bf'
]
FC_INITIATOR_WWPNS = [
    '50014380186b3f65', '50014380186b3f67'
]
FC_FABRIC_MAP = {
    'fabricA':
        {'target_port_wwn_list': [FC_TARGET_WWPNS[0], FC_TARGET_WWPNS[1]],
         'initiator_port_wwn_list': [FC_INITIATOR_WWPNS[0]]},
    'fabricB':
        {'target_port_wwn_list': [FC_TARGET_WWPNS[2], FC_TARGET_WWPNS[3]],
         'initiator_port_wwn_list': [FC_INITIATOR_WWPNS[1]]}
}
FC_INITIATOR_TARGET_MAP = {
    FC_INITIATOR_WWPNS[0]: [FC_TARGET_WWPNS[0], FC_TARGET_WWPNS[1]],
    FC_INITIATOR_WWPNS[1]: [FC_TARGET_WWPNS[2], FC_TARGET_WWPNS[3]]
}


class V6000FCPDriverTestCase(test.TestCase):
    """Test cases for VMEM FCP driver."""
    def setUp(self):
        super(V6000FCPDriverTestCase, self).setUp()
        self.conf = self.setup_configuration()
        self.driver = v6000_fcp.V6000FCDriver(configuration=self.conf)
        self.driver.common.container = 'myContainer'
        self.driver.device_id = 'ata-VIOLIN_MEMORY_ARRAY_23109R00000022'
        self.driver.gateway_fc_wwns = FC_TARGET_WWPNS
        self.stats = {}
        self.driver.set_initialized()

    def tearDown(self):
        super(V6000FCPDriverTestCase, self).tearDown()

    def setup_configuration(self):
        config = mock.Mock(spec=conf.Configuration)
        config.volume_backend_name = 'v6000_fcp'
        config.san_ip = '1.1.1.1'
        config.san_login = 'admin'
        config.san_password = ''
        config.san_thin_provision = False
        config.san_is_local = False
        config.gateway_mga = '2.2.2.2'
        config.gateway_mgb = '3.3.3.3'
        config.use_igroups = False
        config.request_timeout = 300
        config.container = 'myContainer'
        return config

    def setup_mock_vshare(self, m_conf=None):
        """Create a fake VShare communication object."""
        _m_vshare = mock.Mock(name='VShare',
                              version='1.1.1',
                              spec=vmemclient.mock_client_conf)

        if m_conf:
            _m_vshare.configure_mock(**m_conf)

        return _m_vshare

    @mock.patch.object(v6000_common.V6000Common, 'check_for_setup_error')
    def test_check_for_setup_error(self, m_setup_func):
        """No setup errors are found."""
        result = self.driver.check_for_setup_error()
        m_setup_func.assert_called_with()
        self.assertTrue(result is None)

    @mock.patch.object(v6000_common.V6000Common, 'check_for_setup_error')
    def test_check_for_setup_error_no_wwn_config(self, m_setup_func):
        """No wwns were found during setup."""
        self.driver.gateway_fc_wwns = []
        self.assertRaises(exception.ViolinInvalidBackendConfig,
                          self.driver.check_for_setup_error)

    def test_create_volume(self):
        """Volume created successfully."""
        self.driver.common._create_lun = mock.Mock()

        result = self.driver.create_volume(VOLUME)

        self.driver.common._create_lun.assert_called_with(VOLUME)
        self.assertTrue(result is None)

    def test_delete_volume(self):
        """Volume deleted successfully."""
        self.driver.common._delete_lun = mock.Mock()

        result = self.driver.delete_volume(VOLUME)

        self.driver.common._delete_lun.assert_called_with(VOLUME)
        self.assertTrue(result is None)

    def test_create_snapshot(self):
        """Snapshot created successfully."""
        self.driver.common._create_lun_snapshot = mock.Mock()

        result = self.driver.create_snapshot(SNAPSHOT)

        self.driver.common._create_lun_snapshot.assert_called_with(SNAPSHOT)
        self.assertTrue(result is None)

    def test_delete_snapshot(self):
        """Snapshot deleted successfully."""
        self.driver.common._delete_lun_snapshot = mock.Mock()

        result = self.driver.delete_snapshot(SNAPSHOT)

        self.driver.common._delete_lun_snapshot.assert_called_with(SNAPSHOT)
        self.assertTrue(result is None)

    @mock.patch.object(context, 'get_admin_context')
    def test_create_volume_from_snapshot(self, m_context_func):
        """Volume created from a snapshot successfully."""
        m_context_func.return_value = None
        self.driver.common._create_lun = mock.Mock()
        self.driver.copy_volume_data = mock.Mock()

        result = self.driver.create_volume_from_snapshot(VOLUME, SNAPSHOT)

        m_context_func.assert_called_with()
        self.driver.common._create_lun.assert_called_with(VOLUME)
        self.driver.copy_volume_data.assert_called_with(None, SNAPSHOT, VOLUME)
        self.assertTrue(result is None)

    @mock.patch.object(context, 'get_admin_context')
    def test_create_cloned_volume(self, m_context_func):
        """Volume clone created successfully."""
        m_context_func.return_value = None
        self.driver.common._create_lun = mock.Mock()
        self.driver.copy_volume_data = mock.Mock()

        result = self.driver.create_cloned_volume(VOLUME, SRC_VOL)

        m_context_func.assert_called_with()
        self.driver.common._create_lun.assert_called_with(VOLUME)
        self.driver.copy_volume_data.assert_called_with(None, SRC_VOL, VOLUME)
        self.assertTrue(result is None)

    def test_initialize_connection(self):
        lun_id = 1
        igroup = None
        target_wwns = self.driver.gateway_fc_wwns
        init_targ_map = {}
        volume = mock.Mock(spec=models.Volume)

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver._export_lun = mock.Mock(return_value=lun_id)
        self.driver._build_initiator_target_map = mock.Mock(
            return_value=(target_wwns, init_targ_map))

        props = self.driver.initialize_connection(volume, CONNECTOR)

        self.driver._export_lun.assert_called_with(volume, CONNECTOR, igroup)
        self.driver.common.vip.basic.save_config.assert_called_with()
        self.driver._build_initiator_target_map.assert_called_with(
            CONNECTOR)
        self.assertEqual("fibre_channel", props['driver_volume_type'])
        self.assertTrue(props['data']['target_discovered'])
        self.assertEqual(target_wwns, props['data']['target_wwn'])
        self.assertEqual(lun_id, props['data']['target_lun'])
        self.assertEqual(init_targ_map, props['data']['initiator_target_map'])

    def test_initialize_connection_with_snapshot_object(self):
        lun_id = 1
        igroup = None
        target_wwns = self.driver.gateway_fc_wwns
        init_targ_map = {}
        snapshot = mock.Mock(spec=models.Snapshot)

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver._export_snapshot = mock.Mock(return_value=lun_id)
        self.driver._build_initiator_target_map = mock.Mock(
            return_value=(target_wwns, init_targ_map))

        props = self.driver.initialize_connection(snapshot, CONNECTOR)

        self.driver._export_snapshot.assert_called_with(
            snapshot, CONNECTOR, igroup)
        self.driver.common.vip.basic.save_config.assert_called_with()
        self.driver._build_initiator_target_map.assert_called_with(
            CONNECTOR)
        self.assertEqual("fibre_channel", props['driver_volume_type'])
        self.assertTrue(props['data']['target_discovered'])
        self.assertEqual(target_wwns, props['data']['target_wwn'])
        self.assertEqual(lun_id, props['data']['target_lun'])
        self.assertEqual(init_targ_map, props['data']['initiator_target_map'])

    def test_terminate_connection(self):
        target_wwns = self.driver.gateway_fc_wwns
        init_targ_map = {}
        volume = mock.Mock(spec=models.Volume)

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver._unexport_lun = mock.Mock()
        self.driver._is_initiator_connected_to_array = mock.Mock(
            return_value=False)
        self.driver._build_initiator_target_map = mock.Mock(
            return_value=(target_wwns, init_targ_map))

        props = self.driver.terminate_connection(volume, CONNECTOR)

        self.driver._unexport_lun.assert_called_with(volume)
        self.driver.common.vip.basic.save_config.assert_called_with()
        self.driver._is_initiator_connected_to_array.assert_called_with(
            CONNECTOR)
        self.driver._build_initiator_target_map.assert_called_with(
            CONNECTOR)
        self.assertEqual("fibre_channel", props['driver_volume_type'])
        self.assertEqual(target_wwns, props['data']['target_wwn'])
        self.assertEqual(init_targ_map, props['data']['initiator_target_map'])

    def test_terminate_connection_snapshot_object(self):
        target_wwns = self.driver.gateway_fc_wwns
        init_targ_map = {}
        snapshot = mock.Mock(spec=models.Snapshot)

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver._unexport_snapshot = mock.Mock()
        self.driver._is_initiator_connected_to_array = mock.Mock(
            return_value=False)
        self.driver._build_initiator_target_map = mock.Mock(
            return_value=(target_wwns, init_targ_map))

        props = self.driver.terminate_connection(snapshot, CONNECTOR)

        self.assertEqual("fibre_channel", props['driver_volume_type'])
        self.assertEqual(target_wwns, props['data']['target_wwn'])
        self.assertEqual(init_targ_map, props['data']['initiator_target_map'])

    def test_get_volume_stats(self):
        self.driver._update_stats = mock.Mock()
        self.driver._update_stats()

        result = self.driver.get_volume_stats(True)

        self.driver._update_stats.assert_called_with()
        self.assertEqual(self.driver.stats, result)

    def test_export_lun(self):
        lun_id = '1'
        igroup = 'test-igroup-1'
        response = {'code': 0, 'message': ''}

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver.common._send_cmd_and_verify = mock.Mock(
            return_value=response)
        self.driver.common._get_lun_id = mock.Mock(return_value=lun_id)

        result = self.driver._export_lun(VOLUME, CONNECTOR, igroup)

        self.driver.common._send_cmd_and_verify.assert_called_with(
            self.driver.common.vip.lun.export_lun,
            self.driver.common._wait_for_export_config, '',
            [self.driver.common.container, VOLUME['id'], 'all',
             igroup, 'auto'], [VOLUME['id'], 'state=True'])
        self.driver.common._get_lun_id.assert_called_with(VOLUME['id'])
        self.assertEqual(lun_id, result)

    def test_export_lun_fails_with_exception(self):
        lun_id = '1'
        igroup = 'test-igroup-1'
        response = {'code': 14000, 'message': 'Generic error'}
        failure = exception.ViolinBackendErr

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver.common._send_cmd_and_verify = mock.Mock(
            side_effect=failure(response['message']))
        self.driver.common._get_lun_id = mock.Mock(return_value=lun_id)

        self.assertRaises(failure, self.driver._export_lun,
                          VOLUME, CONNECTOR, igroup)

    def test_unexport_lun(self):
        response = {'code': 0, 'message': ''}

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver.common._send_cmd_and_verify = mock.Mock(
            return_value=response)

        result = self.driver._unexport_lun(VOLUME)

        self.driver.common._send_cmd_and_verify.assert_called_with(
            self.driver.common.vip.lun.unexport_lun,
            self.driver.common._wait_for_export_config, '',
            [self.driver.common.container, VOLUME['id'], 'all', 'all', 'auto'],
            [VOLUME['id'], 'state=False'])
        self.assertTrue(result is None)

    def test_unexport_lun_fails_with_exception(self):
        response = {'code': 14000, 'message': 'Generic error'}
        failure = exception.ViolinBackendErr

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver.common._send_cmd_and_verify = mock.Mock(
            side_effect=failure(response['message']))

        self.assertRaises(failure, self.driver._unexport_lun, VOLUME)

    def test_export_snapshot(self):
        lun_id = '1'
        igroup = 'test-igroup-1'
        response = {'code': 0, 'message': ''}

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver.common._send_cmd = mock.Mock(return_value=response)
        self.driver.common._wait_for_export_config = mock.Mock()
        self.driver.common._get_snapshot_id = mock.Mock(return_value=lun_id)

        result = self.driver._export_snapshot(SNAPSHOT, CONNECTOR, igroup)

        self.driver.common._send_cmd.assert_called_with(
            self.driver.common.vip.snapshot.export_lun_snapshot, '',
            self.driver.common.container, SNAPSHOT['volume_id'],
            SNAPSHOT['id'], igroup, 'all', 'auto')
        self.driver.common._wait_for_export_config.assert_called_with(
            SNAPSHOT['volume_id'], SNAPSHOT['id'], state=True)
        self.driver.common._get_snapshot_id.assert_called_once_with(
            SNAPSHOT['volume_id'], SNAPSHOT['id'])
        self.assertEqual(lun_id, result)

    def test_unexport_snapshot(self):
        response = {'code': 0, 'message': ''}

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver.common._send_cmd = mock.Mock(return_value=response)
        self.driver.common._wait_for_export_config = mock.Mock()

        result = self.driver._unexport_snapshot(SNAPSHOT)

        self.driver.common._send_cmd.assert_called_with(
            self.driver.common.vip.snapshot.unexport_lun_snapshot, '',
            self.driver.common.container, SNAPSHOT['volume_id'],
            SNAPSHOT['id'], 'all', 'all', 'auto', False)
        self.driver.common._wait_for_export_config.assert_called_with(
            SNAPSHOT['volume_id'], SNAPSHOT['id'], state=False)
        self.assertTrue(result is None)

    def test_add_igroup_member(self):
        igroup = 'test-group-1'
        response = {'code': 0, 'message': 'success'}
        wwpns = ['wwn.50:01:43:80:18:6b:3f:65', 'wwn.50:01:43:80:18:6b:3f:67']

        conf = {
            'igroup.add_initiators.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        self.driver._convert_wwns_openstack_to_vmem = mock.Mock(
            return_value=wwpns)

        result = self.driver._add_igroup_member(CONNECTOR, igroup)

        self.driver._convert_wwns_openstack_to_vmem.assert_called_with(
            CONNECTOR['wwpns'])
        self.driver.common.vip.igroup.add_initiators.assert_called_with(
            igroup, wwpns)
        self.assertTrue(result is None)

    def test_build_initiator_target_map(self):
        """Successfully build a map when zoning is enabled."""
        expected_targ_wwns = FC_TARGET_WWPNS

        self.driver.lookup_service = mock.Mock()
        self.driver.lookup_service.get_device_mapping_from_network.\
            return_value = FC_FABRIC_MAP

        (targ_wwns, init_targ_map) = \
            self.driver._build_initiator_target_map(CONNECTOR)

        self.driver.lookup_service.get_device_mapping_from_network.\
            assert_called_with(CONNECTOR['wwpns'], self.driver.gateway_fc_wwns)
        self.assertEqual(set(expected_targ_wwns), set(targ_wwns))

        i = FC_INITIATOR_WWPNS[0]
        self.assertIn(FC_TARGET_WWPNS[0], init_targ_map[i])
        self.assertIn(FC_TARGET_WWPNS[1], init_targ_map[i])
        self.assertEqual(2, len(init_targ_map[i]))

        i = FC_INITIATOR_WWPNS[1]
        self.assertIn(FC_TARGET_WWPNS[2], init_targ_map[i])
        self.assertIn(FC_TARGET_WWPNS[3], init_targ_map[i])
        self.assertEqual(2, len(init_targ_map[i]))

        self.assertEqual(2, len(init_targ_map))

    def test_build_initiator_target_map_no_lookup_service(self):
        """Successfully build a map when zoning is disabled."""
        expected_targ_wwns = FC_TARGET_WWPNS
        expected_init_targ_map = {
            CONNECTOR['wwpns'][0]: FC_TARGET_WWPNS,
            CONNECTOR['wwpns'][1]: FC_TARGET_WWPNS
        }
        self.driver.lookup_service = None

        targ_wwns, init_targ_map = self.driver._build_initiator_target_map(
            CONNECTOR)

        self.assertEqual(expected_targ_wwns, targ_wwns)
        self.assertEqual(expected_init_targ_map, init_targ_map)

    def test_is_initiator_connected_to_array(self):
        """Successfully finds an initiator with remaining active session."""
        converted_wwpns = ['50:01:43:80:18:6b:3f:65',
                           '50:01:43:80:18:6b:3f:67']
        prefix = "/vshare/config/export/container"
        bn = "%s/%s/lun/**" % (prefix, self.driver.common.container)
        resp_binding0 = "%s/%s/lun/%s/target/hba-a1/initiator/%s" \
            % (prefix, self.driver.common.container, VOLUME['id'],
               converted_wwpns[0])
        resp_binding1 = "%s/%s/lun/%s/target/hba-a1/initiator/%s" \
            % (prefix, self.driver.common.container, VOLUME['id'],
               converted_wwpns[1])
        response = {
            resp_binding0: converted_wwpns[0],
            resp_binding1: converted_wwpns[1]
        }

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._convert_wwns_openstack_to_vmem = mock.Mock(
            return_value=converted_wwpns)

        self.assertTrue(self.driver._is_initiator_connected_to_array(
            CONNECTOR))
        self.driver.common.vip.basic.get_node_values.assert_called_with(bn)

    def test_is_initiator_connected_to_array_empty_response(self):
        """Successfully finds no initiators with remaining active sessions."""
        converted_wwpns = ['50:01:43:80:18:6b:3f:65',
                           '50:01:43:80:18:6b:3f:67']
        response = {}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver._convert_wwns_openstack_to_vmem = mock.Mock(
            return_value=converted_wwpns)

        self.assertFalse(self.driver._is_initiator_connected_to_array(
            CONNECTOR))

    def test_update_stats(self):
        backend_name = self.conf.volume_backend_name
        vendor_name = "Violin Memory, Inc."
        tot_bytes = 100 * units.Gi
        free_bytes = 50 * units.Gi
        bn0 = '/cluster/state/master_id'
        bn1 = "/vshare/state/global/1/container/myContainer/total_bytes"
        bn2 = "/vshare/state/global/1/container/myContainer/free_bytes"
        response1 = {bn0: '1'}
        response2 = {bn1: tot_bytes, bn2: free_bytes}

        conf = {
            'basic.get_node_values.side_effect': [response1, response2],
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        result = self.driver._update_stats()

        calls = [mock.call(bn0), mock.call([bn1, bn2])]
        self.driver.common.vip.basic.get_node_values.assert_has_calls(calls)
        self.assertEqual(100, self.driver.stats['total_capacity_gb'])
        self.assertEqual(50, self.driver.stats['free_capacity_gb'])
        self.assertEqual(backend_name,
                         self.driver.stats['volume_backend_name'])
        self.assertEqual(vendor_name, self.driver.stats['vendor_name'])
        self.assertTrue(result is None)

    def test_update_stats_fails_data_query(self):
        backend_name = self.conf.volume_backend_name
        vendor_name = "Violin Memory, Inc."
        bn0 = '/cluster/state/master_id'
        response1 = {bn0: '1'}
        response2 = {}

        conf = {
            'basic.get_node_values.side_effect': [response1, response2],
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        self.assertTrue(self.driver._update_stats() is None)
        self.assertEqual(0, self.driver.stats['total_capacity_gb'])
        self.assertEqual(0, self.driver.stats['free_capacity_gb'])
        self.assertEqual(backend_name,
                         self.driver.stats['volume_backend_name'])
        self.assertEqual(vendor_name, self.driver.stats['vendor_name'])

    def test_update_stats_fails_data_query_but_has_cached_stats(self):
        """Stats query to backend fails, but cached stats are available. """
        backend_name = self.conf.volume_backend_name
        vendor_name = "Violin Memory, Inc."
        bn0 = '/cluster/state/master_id'
        response1 = {bn0: '1'}
        response2 = {}

        # fake cached stats, from a previous stats query
        self.driver.stats = {'free_capacity_gb': 50, 'total_capacity_gb': 100}

        conf = {
            'basic.get_node_values.side_effect': [response1, response2],
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        self.assertIsNone(self.driver._update_stats())
        self.assertEqual(100, self.driver.stats['total_capacity_gb'])
        self.assertEqual(50, self.driver.stats['free_capacity_gb'])
        self.assertEqual(backend_name,
                         self.driver.stats['volume_backend_name'])
        self.assertEqual(vendor_name, self.driver.stats['vendor_name'])

    def test_get_active_fc_targets(self):
        bn0 = '/vshare/state/global/*'
        response0 = {'/vshare/state/global/1': 1,
                     '/vshare/state/global/2': 2}
        bn1 = '/vshare/state/global/1/target/fc/**'
        response1 = {'/vshare/state/global/1/target/fc/hba-a1/wwn':
                     'wwn.21:00:00:24:ff:45:fb:22'}
        bn2 = '/vshare/state/global/2/target/fc/**'
        response2 = {'/vshare/state/global/2/target/fc/hba-a1/wwn':
                     'wwn.21:00:00:24:ff:45:e2:30'}
        wwpns = ['21000024ff45fb22', '21000024ff45e230']

        conf = {
            'basic.get_node_values.side_effect':
            [response0, response1, response2],
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        result = self.driver._get_active_fc_targets()

        calls = [mock.call(bn0), mock.call(bn1), mock.call(bn2)]
        self.driver.common.vip.basic.get_node_values.assert_has_calls(
            calls, any_order=True)
        self.assertEqual(wwpns, result)

    def test_convert_wwns_openstack_to_vmem(self):
        vmem_wwns = ['wwn.50:01:43:80:18:6b:3f:65']
        openstack_wwns = ['50014380186b3f65']
        result = self.driver._convert_wwns_openstack_to_vmem(openstack_wwns)
        self.assertEqual(vmem_wwns, result)

    def test_convert_wwns_vmem_to_openstack(self):
        vmem_wwns = ['wwn.50:01:43:80:18:6b:3f:65']
        openstack_wwns = ['50014380186b3f65']
        result = self.driver._convert_wwns_vmem_to_openstack(vmem_wwns)
        self.assertEqual(openstack_wwns, result)
