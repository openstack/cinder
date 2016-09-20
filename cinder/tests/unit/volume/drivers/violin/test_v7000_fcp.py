# Copyright 2015 Violin Memory, Inc.
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
Tests for Violin Memory 7000 Series All-Flash Array Fibrechannel Driver
"""

import mock

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.violin \
    import fake_vmem_client as vmemclient
from cinder.volume import configuration as conf
from cinder.volume.drivers.violin import v7000_common
from cinder.volume.drivers.violin import v7000_fcp

VOLUME_ID = "abcdabcd-1234-abcd-1234-abcdeffedcba"
VOLUME = {
    "name": "volume-" + VOLUME_ID,
    "id": VOLUME_ID,
    "display_name": "fake_volume",
    "size": 2,
    "host": "myhost",
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
    "host": "myhost",
    "volume_type": None,
    "volume_type_id": None,
}
INITIATOR_IQN = "iqn.1111-22.org.debian:11:222"
CONNECTOR = {
    "initiator": INITIATOR_IQN,
    "host": "irrelevant",
    'wwpns': ['50014380186b3f65', '50014380186b3f67'],
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

PHY_DEVICES_RESPONSE = {
    'data':
    {'physical_devices':
        [{'availsize': 1099504287744,
          'availsize_mb': 524284,
          'category': 'Virtual Device',
          'connection_type': 'block',
          'firmware': 'v1.0',
          'guid': '3cc4d6dd-166d-77d2-4967-00005463f597',
          'inquiry_string': '000002122b000032BKSC    OTHDISK-MFCN01  v1.0',
          'is_foreign': True,
          'name': 'BKSC:OTHDISK-MFCN01.000',
          'object_id': '84b834fb-1f4d-5d3b-b7ae-5796f9868151',
          'owner': 'example.com',
          'pool': None,
          'product': 'OTHDISK-MFCN01',
          'scsi_address':
          {'adapter': '98',
           'channel': '0',
           'id': '0',
           'lun': '0',
           'object_id': '6e0106fc-9c1c-52a2-95c9-396b7a653ac1'},
          'size': 1099504287744,
          'size_mb': 1048569,
          'type': 'Direct-Access',
          'usedsize': 0,
          'usedsize_mb': 0,
          'vendor': 'BKSC',
          'wwid': 'BKSC    OTHDISK-MFCN01  v1.0-0-0-00'},
         {'availsize': 1099504287744,
          'availsize_mb': 524284,
          'category': 'Virtual Device',
          'connection_type': 'block',
          'firmware': 'v1.0',
          'guid': '283b2694-192b-4745-6768-00005463f673',
          'inquiry_string': '000002122b000032BKSC    OTHDISK-MFCN08  v1.0',
          'is_foreign': False,
          'name': 'BKSC:OTHDISK-MFCN08.000',
          'object_id': '8555b888-bf43-5083-a433-f0c7b0282370',
          'owner': 'example.com',
          'pool':
          {'name': 'mga-pool',
           'object_id': '0818d3de-4437-535f-9cac-cc100a2c9313'},
          'product': 'OTHDISK-MFCN08',
          'scsi_address':
          {'adapter': '98',
           'channel': '0',
           'id': '11',
           'lun': '0',
           'object_id': '6e0106fc-9c1c-52a2-95c9-396b7a653ac1'},
          'size': 1099504287744,
          'size_mb': 1048569,
          'type': 'Direct-Access',
          'usedsize': 0,
          'usedsize_mb': 0,
          'vendor': 'BKSC',
          'wwid': 'BKSC    OTHDISK-MFCN08  v1.0-0-0-00'},
         {'availsize': 1099504287744,
          'availsize_mb': 1048569,
          'category': 'Virtual Device',
          'connection_type': 'block',
          'firmware': 'v1.0',
          'guid': '7f47db19-019c-707d-0df1-00005463f949',
          'inquiry_string': '000002122b000032BKSC    OTHDISK-MFCN09  v1.0',
          'is_foreign': False,
          'name': 'BKSC:OTHDISK-MFCN09.000',
          'object_id': '62a98898-f8b8-5837-af2b-764f5a72e291',
          'owner': 'a.b.c.d',
          'pool':
          {'name': 'mga-pool',
           'object_id': '0818d3de-4437-535f-9cac-cc100a2c9313'},
          'product': 'OTHDISK-MFCN09',
          'scsi_address':
          {'adapter': '98',
           'channel': '0',
           'id': '12',
           'lun': '0',
           'object_id': '6e0106fc-9c1c-52a2-95c9-396b7a653ac1'},
          'size': 1099504287744,
          'size_mb': 524284,
          'type': 'Direct-Access',
          'usedsize': 0,
          'usedsize_mb': 0,
          'vendor': 'BKSC',
          'wwid': 'BKSC    OTHDISK-MFCN09  v1.0-0-0-00'}],
        'total_physical_devices': 3},
    'msg': 'Successful',
    'success': True
}

# The FC_INFO dict returned by the backend is keyed on
# object_id of the FC adapter and the values are the
# wwmns
FC_INFO = {
    '1a3cdb6a-383d-5ba6-a50b-4ba598074510': ['2100001b9745e25e'],
    '4a6bc10a-5547-5cc0-94f2-76222a8f8dff': ['2100001b9745e230'],
    'b21bfff5-d89e-51ff-9920-d990a061d722': ['2100001b9745e25f'],
    'b508cc6b-f78a-51f9-81cf-47c1aaf53dd1': ['2100001b9745e231']
}

CLIENT_INFO = {
    'FCPolicy':
    {'AS400enabled': False,
     'VSAenabled': False,
     'initiatorWWPNList': ['50-01-43-80-18-6b-3f-66',
                           '50-01-43-80-18-6b-3f-64']},
    'FibreChannelDevices':
    [{'access': 'ReadWrite',
      'id': 'v0000004',
      'initiatorWWPN': '*',
      'lun': '8',
      'name': 'abcdabcd-1234-abcd-1234-abcdeffedcba',
      'sizeMB': 10240,
      'targetWWPN': '*',
      'type': 'SAN'}]
}

CLIENT_INFO1 = {
    'FCPolicy':
    {'AS400enabled': False,
     'VSAenabled': False,
     'initiatorWWPNList': ['50-01-43-80-18-6b-3f-66',
                           '50-01-43-80-18-6b-3f-64']},
    'FibreChannelDevices': []
}


class V7000FCPDriverTestCase(test.TestCase):
    """Test cases for VMEM FCP driver."""
    def setUp(self):
        super(V7000FCPDriverTestCase, self).setUp()
        self.conf = self.setup_configuration()
        self.driver = v7000_fcp.V7000FCPDriver(configuration=self.conf)
        self.driver.common.container = 'myContainer'
        self.driver.device_id = 'ata-VIOLIN_MEMORY_ARRAY_23109R00000022'
        self.driver.gateway_fc_wwns = FC_TARGET_WWPNS
        self.stats = {}
        self.driver.set_initialized()

    def setup_configuration(self):
        config = mock.Mock(spec=conf.Configuration)
        config.volume_backend_name = 'v7000_fcp'
        config.san_ip = '8.8.8.8'
        config.san_login = 'admin'
        config.san_password = ''
        config.san_thin_provision = False
        config.san_is_local = False
        config.request_timeout = 300
        config.container = 'myContainer'
        return config

    def setup_mock_concerto(self, m_conf=None):
        """Create a fake Concerto communication object."""
        _m_concerto = mock.Mock(name='Concerto',
                                version='1.1.1',
                                spec=vmemclient.mock_client_conf)

        if m_conf:
            _m_concerto.configure_mock(**m_conf)

        return _m_concerto

    @mock.patch.object(v7000_common.V7000Common, 'check_for_setup_error')
    def test_check_for_setup_error(self, m_setup_func):
        """No setup errors are found."""
        result = self.driver.check_for_setup_error()
        m_setup_func.assert_called_with()
        self.assertIsNone(result)

    @mock.patch.object(v7000_common.V7000Common, 'check_for_setup_error')
    def test_check_for_setup_error_no_wwn_config(self, m_setup_func):
        """No wwns were found during setup."""
        self.driver.gateway_fc_wwns = []
        failure = exception.ViolinInvalidBackendConfig
        self.assertRaises(failure, self.driver.check_for_setup_error)

    def test_create_volume(self):
        """Volume created successfully."""
        self.driver.common._create_lun = mock.Mock()

        result = self.driver.create_volume(VOLUME)

        self.driver.common._create_lun.assert_called_with(VOLUME)
        self.assertIsNone(result)

    def test_create_volume_from_snapshot(self):
        self.driver.common._create_volume_from_snapshot = mock.Mock()

        result = self.driver.create_volume_from_snapshot(VOLUME, SNAPSHOT)

        self.driver.common._create_volume_from_snapshot.assert_called_with(
            SNAPSHOT, VOLUME)

        self.assertIsNone(result)

    def test_create_cloned_volume(self):
        self.driver.common._create_lun_from_lun = mock.Mock()

        result = self.driver.create_cloned_volume(VOLUME, SRC_VOL)

        self.driver.common._create_lun_from_lun.assert_called_with(
            SRC_VOL, VOLUME)
        self.assertIsNone(result)

    def test_delete_volume(self):
        """Volume deleted successfully."""
        self.driver.common._delete_lun = mock.Mock()

        result = self.driver.delete_volume(VOLUME)

        self.driver.common._delete_lun.assert_called_with(VOLUME)
        self.assertIsNone(result)

    def test_extend_volume(self):
        """Volume extended successfully."""
        new_size = 10
        self.driver.common._extend_lun = mock.Mock()

        result = self.driver.extend_volume(VOLUME, new_size)

        self.driver.common._extend_lun.assert_called_with(VOLUME, new_size)
        self.assertIsNone(result)

    def test_create_snapshot(self):
        self.driver.common._create_lun_snapshot = mock.Mock()

        result = self.driver.create_snapshot(SNAPSHOT)
        self.driver.common._create_lun_snapshot.assert_called_with(SNAPSHOT)
        self.assertIsNone(result)

    def test_delete_snapshot(self):
        self.driver.common._delete_lun_snapshot = mock.Mock()

        result = self.driver.delete_snapshot(SNAPSHOT)
        self.driver.common._delete_lun_snapshot.assert_called_with(SNAPSHOT)
        self.assertIsNone(result)

    def test_get_volume_stats(self):
        self.driver._update_volume_stats = mock.Mock()
        self.driver._update_volume_stats()

        result = self.driver.get_volume_stats(True)

        self.driver._update_volume_stats.assert_called_with()
        self.assertEqual(self.driver.stats, result)

    @mock.patch('socket.gethostbyaddr')
    def test_update_volume_stats(self, mock_gethost):
        """Test Update Volume Stats.

        Makes a mock query to the backend to collect stats on all physical
        devices.
        """

        def gethostbyaddr(addr):
            if addr == '8.8.8.8' or addr == 'example.com':
                return ('example.com', [], ['8.8.8.8'])
            else:
                return ('a.b.c.d', [], addr)
        mock_gethost.side_effect = gethostbyaddr

        backend_name = self.conf.volume_backend_name
        vendor_name = "Violin Memory, Inc."
        tot_gb = 2046
        free_gb = 1022

        phy_devices = "/batch/physicalresource/physicaldevice"

        conf = {
            'basic.get.side_effect': [PHY_DEVICES_RESPONSE, ],
        }

        self.driver.common.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        result = self.driver._update_volume_stats()

        calls = [mock.call(phy_devices)]
        self.driver.common.vmem_mg.basic.get.assert_has_calls(calls)
        self.assertEqual(tot_gb, self.driver.stats['total_capacity_gb'])
        self.assertEqual(free_gb, self.driver.stats['free_capacity_gb'])
        self.assertEqual(backend_name,
                         self.driver.stats['volume_backend_name'])
        self.assertEqual(vendor_name, self.driver.stats['vendor_name'])
        self.assertIsNone(result)

    def test_get_active_fc_targets(self):
        """Test Get Active FC Targets.

        Makes a mock query to the backend to collect all the physical
        adapters and extract the WWNs.
        """

        conf = {
            'adapter.get_fc_info.return_value': FC_INFO,
        }

        self.driver.common.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        result = self.driver._get_active_fc_targets()

        self.assertEqual({'2100001b9745e230', '2100001b9745e25f',
                          '2100001b9745e231', '2100001b9745e25e'},
                         set(result))

    def test_initialize_connection(self):
        lun_id = 1
        target_wwns = self.driver.gateway_fc_wwns
        init_targ_map = {}

        conf = {
            'client.create_client.return_value': None,
        }
        self.driver.common.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._export_lun = mock.Mock(return_value=lun_id)
        self.driver._build_initiator_target_map = mock.Mock(
            return_value=(target_wwns, init_targ_map))

        props = self.driver.initialize_connection(VOLUME, CONNECTOR)

        self.driver.common.vmem_mg.client.create_client.assert_called_with(
            name=CONNECTOR['host'], proto='FC', fc_wwns=CONNECTOR['wwpns'])
        self.driver._export_lun.assert_called_with(VOLUME, CONNECTOR)
        self.driver._build_initiator_target_map.assert_called_with(
            CONNECTOR)
        self.assertEqual("fibre_channel", props['driver_volume_type'])
        self.assertTrue(props['data']['target_discovered'])
        self.assertEqual(self.driver.gateway_fc_wwns,
                         props['data']['target_wwn'])
        self.assertEqual(lun_id, props['data']['target_lun'])

    def test_terminate_connection(self):
        target_wwns = self.driver.gateway_fc_wwns
        init_targ_map = {}

        self.driver.common.vmem_mg = self.setup_mock_concerto()
        self.driver._unexport_lun = mock.Mock()
        self.driver._is_initiator_connected_to_array = mock.Mock(
            return_value=False)
        self.driver._build_initiator_target_map = mock.Mock(
            return_value=(target_wwns, init_targ_map))

        props = self.driver.terminate_connection(VOLUME, CONNECTOR)

        self.driver._unexport_lun.assert_called_with(VOLUME, CONNECTOR)
        self.driver._is_initiator_connected_to_array.assert_called_with(
            CONNECTOR)
        self.driver._build_initiator_target_map.assert_called_with(
            CONNECTOR)
        self.assertEqual("fibre_channel", props['driver_volume_type'])
        self.assertEqual(target_wwns, props['data']['target_wwn'])
        self.assertEqual(init_targ_map, props['data']['initiator_target_map'])

    def test_export_lun(self):
        lun_id = '1'
        response = {'success': True, 'msg': 'Assign SAN client successfully'}

        conf = {
            'client.get_client_info.return_value': CLIENT_INFO,
        }
        self.driver.common.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        self.driver.common._send_cmd_and_verify = mock.Mock(
            return_value=response)

        self.driver._get_lun_id = mock.Mock(return_value=lun_id)

        result = self.driver._export_lun(VOLUME, CONNECTOR)

        self.driver.common._send_cmd_and_verify.assert_called_with(
            self.driver.common.vmem_mg.lun.assign_lun_to_client,
            self.driver._is_lun_id_ready,
            'Assign SAN client successfully',
            [VOLUME['id'], CONNECTOR['host'], "ReadWrite"],
            [VOLUME['id'], CONNECTOR['host']])
        self.driver._get_lun_id.assert_called_with(
            VOLUME['id'], CONNECTOR['host'])
        self.assertEqual(lun_id, result)

    def test_export_lun_fails_with_exception(self):
        lun_id = '1'
        response = {'status': False, 'msg': 'Generic error'}
        failure = exception.ViolinBackendErr

        self.driver.common.vmem_mg = self.setup_mock_concerto()
        self.driver.common._send_cmd_and_verify = mock.Mock(
            side_effect=exception.ViolinBackendErr(response['msg']))
        self.driver._get_lun_id = mock.Mock(return_value=lun_id)

        self.assertRaises(failure, self.driver._export_lun, VOLUME, CONNECTOR)

    def test_unexport_lun(self):
        response = {'success': True, 'msg': 'Unassign SAN client successfully'}

        self.driver.common.vmem_mg = self.setup_mock_concerto()
        self.driver.common._send_cmd = mock.Mock(
            return_value=response)

        result = self.driver._unexport_lun(VOLUME, CONNECTOR)

        self.driver.common._send_cmd.assert_called_with(
            self.driver.common.vmem_mg.lun.unassign_client_lun,
            "Unassign SAN client successfully",
            VOLUME['id'], CONNECTOR['host'], True)
        self.assertIsNone(result)

    def test_get_lun_id(self):

        conf = {
            'client.get_client_info.return_value': CLIENT_INFO,
        }
        self.driver.common.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        result = self.driver._get_lun_id(VOLUME['id'], CONNECTOR['host'])

        self.assertEqual(8, result)

    def test_is_lun_id_ready(self):
        lun_id = '1'
        self.driver.common.vmem_mg = self.setup_mock_concerto()

        self.driver._get_lun_id = mock.Mock(return_value=lun_id)

        result = self.driver._is_lun_id_ready(
            VOLUME['id'], CONNECTOR['host'])
        self.assertTrue(result)

    def test_build_initiator_target_map(self):
        """Successfully build a map when zoning is enabled."""
        expected_targ_wwns = FC_TARGET_WWPNS

        self.driver.lookup_service = mock.Mock()
        (self.driver.lookup_service.get_device_mapping_from_network.
         return_value) = FC_FABRIC_MAP

        result = self.driver._build_initiator_target_map(CONNECTOR)
        (targ_wwns, init_targ_map) = result

        (self.driver.lookup_service.get_device_mapping_from_network.
         assert_called_with(CONNECTOR['wwpns'], self.driver.gateway_fc_wwns))
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
        conf = {
            'client.get_client_info.return_value': CLIENT_INFO,
        }
        self.driver.common.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        self.assertTrue(self.driver._is_initiator_connected_to_array(
            CONNECTOR))
        self.driver.common.vmem_mg.client.get_client_info.assert_called_with(
            CONNECTOR['host'])

    def test_is_initiator_connected_to_array_empty_response(self):
        """Successfully finds no initiators with remaining active sessions."""
        conf = {
            'client.get_client_info.return_value': CLIENT_INFO1
        }
        self.driver.common.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        self.assertFalse(self.driver._is_initiator_connected_to_array(
            CONNECTOR))
