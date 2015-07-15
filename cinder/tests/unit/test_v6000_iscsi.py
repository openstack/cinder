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
Tests for Violin Memory 6000 Series All-Flash Array iSCSI driver
"""

import mock
from oslo_utils import units

from cinder import context
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_vmem_client as vmemclient
from cinder.volume import configuration as conf
from cinder.volume.drivers.violin import v6000_common
from cinder.volume.drivers.violin import v6000_iscsi

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
    "host": "irrelevant"
}


class V6000ISCSIDriverTestCase(test.TestCase):
    """Test cases for VMEM iSCSI driver."""
    def setUp(self):
        super(V6000ISCSIDriverTestCase, self).setUp()
        self.conf = self.setup_configuration()
        self.driver = v6000_iscsi.V6000ISCSIDriver(configuration=self.conf)
        self.driver.common.container = 'myContainer'
        self.driver.device_id = 'ata-VIOLIN_MEMORY_ARRAY_23109R00000022'
        self.driver.gateway_iscsi_ip_addresses_mga = '1.2.3.4'
        self.driver.gateway_iscsi_ip_addresses_mgb = '1.2.3.4'
        self.driver.array_info = [{"node": 'hostname_mga',
                                   "addr": '1.2.3.4',
                                   "conn": self.driver.common.mga},
                                  {"node": 'hostname_mgb',
                                   "addr": '1.2.3.4',
                                   "conn": self.driver.common.mgb}]
        self.stats = {}
        self.driver.set_initialized()

    def tearDown(self):
        super(V6000ISCSIDriverTestCase, self).tearDown()

    def setup_configuration(self):
        config = mock.Mock(spec=conf.Configuration)
        config.volume_backend_name = 'v6000_iscsi'
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
        config.iscsi_port = 3260
        config.iscsi_target_prefix = 'iqn.2004-02.com.vmem:'
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
        bn = "/vshare/config/iscsi/enable"
        response = {bn: True}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        result = self.driver.check_for_setup_error()

        m_setup_func.assert_called_with()
        self.driver.common.vip.basic.get_node_values.assert_called_with(bn)
        self.assertTrue(result is None)

    @mock.patch.object(v6000_common.V6000Common, 'check_for_setup_error')
    def test_check_for_setup_error_iscsi_is_disabled(self, m_setup_func):
        bn = "/vshare/config/iscsi/enable"
        response = {bn: False}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        self.assertRaises(exception.ViolinInvalidBackendConfig,
                          self.driver.check_for_setup_error)

    @mock.patch.object(v6000_common.V6000Common, 'check_for_setup_error')
    def test_check_for_setup_error_no_iscsi_ips_for_mga(self, m_setup_func):
        bn = "/vshare/config/iscsi/enable"
        response = {bn: True}
        self.driver.gateway_iscsi_ip_addresses_mga = ''

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        self.assertRaises(exception.ViolinInvalidBackendConfig,
                          self.driver.check_for_setup_error)

    @mock.patch.object(v6000_common.V6000Common, 'check_for_setup_error')
    def test_check_for_setup_error_no_iscsi_ips_for_mgb(self, m_setup_func):
        bn = "/vshare/config/iscsi/enable"
        response = {bn: True}
        self.driver.gateway_iscsi_ip_addresses_mgb = ''

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

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
        target_name = self.driver.TARGET_GROUP_NAME
        tgt = self.driver.array_info[0]
        iqn = "%s%s:%s" % (self.conf.iscsi_target_prefix,
                           tgt['node'], target_name)
        volume = mock.MagicMock(spec=models.Volume)

        def getitem(name):
            return VOLUME[name]

        volume.__getitem__.side_effect = getitem

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver._get_iscsi_target = mock.Mock(return_value=tgt)
        self.driver._export_lun = mock.Mock(return_value=lun_id)

        props = self.driver.initialize_connection(volume, CONNECTOR)

        self.driver._get_iscsi_target.assert_called_once_with()
        self.driver._export_lun.assert_called_once_with(
            volume, CONNECTOR, igroup)
        self.driver.common.vip.basic.save_config.assert_called_with()
        self.assertEqual("1.2.3.4:3260", props['data']['target_portal'])
        self.assertEqual(iqn, props['data']['target_iqn'])
        self.assertEqual(lun_id, props['data']['target_lun'])
        self.assertEqual(volume['id'], props['data']['volume_id'])

    def test_initialize_connection_with_snapshot_object(self):
        lun_id = 1
        igroup = None
        target_name = self.driver.TARGET_GROUP_NAME
        tgt = self.driver.array_info[0]
        iqn = "%s%s:%s" % (self.conf.iscsi_target_prefix,
                           tgt['node'], target_name)
        snapshot = mock.MagicMock(spec=models.Snapshot)

        def getitem(name):
            return SNAPSHOT[name]

        snapshot.__getitem__.side_effect = getitem

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver._get_iscsi_target = mock.Mock(return_value=tgt)
        self.driver._export_snapshot = mock.Mock(return_value=lun_id)

        props = self.driver.initialize_connection(snapshot, CONNECTOR)

        self.driver._get_iscsi_target.assert_called_once_with()
        self.driver._export_snapshot.assert_called_once_with(
            snapshot, CONNECTOR, igroup)
        self.driver.common.vip.basic.save_config.assert_called_with()
        self.assertEqual("1.2.3.4:3260", props['data']['target_portal'])
        self.assertEqual(iqn, props['data']['target_iqn'])
        self.assertEqual(lun_id, props['data']['target_lun'])
        self.assertEqual(SNAPSHOT['id'], props['data']['volume_id'])

    def test_initialize_connection_with_igroups_enabled(self):
        self.conf.use_igroups = True
        lun_id = 1
        igroup = 'test-igroup-1'
        target_name = self.driver.TARGET_GROUP_NAME
        tgt = self.driver.array_info[0]
        iqn = "%s%s:%s" % (self.conf.iscsi_target_prefix,
                           tgt['node'], target_name)
        volume = mock.MagicMock(spec=models.Volume)

        def getitem(name):
            return VOLUME[name]

        volume.__getitem__.side_effect = getitem

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver.common._get_igroup = mock.Mock(return_value=igroup)
        self.driver._add_igroup_member = mock.Mock()
        self.driver._get_iscsi_target = mock.Mock(return_value=tgt)
        self.driver._export_lun = mock.Mock(return_value=lun_id)

        props = self.driver.initialize_connection(volume, CONNECTOR)

        self.driver.common._get_igroup.assert_called_once_with(
            volume, CONNECTOR)
        self.driver._add_igroup_member.assert_called_once_with(
            CONNECTOR, igroup)
        self.driver._get_iscsi_target.assert_called_once_with()
        self.driver._export_lun.assert_called_once_with(
            volume, CONNECTOR, igroup)
        self.driver.common.vip.basic.save_config.assert_called_once_with()
        self.assertEqual("1.2.3.4:3260", props['data']['target_portal'])
        self.assertEqual(iqn, props['data']['target_iqn'])
        self.assertEqual(lun_id, props['data']['target_lun'])
        self.assertEqual(volume['id'], props['data']['volume_id'])

    def test_terminate_connection(self):
        volume = mock.MagicMock(spec=models.Volume)

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver._unexport_lun = mock.Mock()

        result = self.driver.terminate_connection(volume, CONNECTOR)

        self.driver._unexport_lun.assert_called_once_with(volume)
        self.driver.common.vip.basic.save_config.assert_called_with()
        self.assertTrue(result is None)

    def test_terminate_connection_with_snapshot_object(self):
        snapshot = mock.MagicMock(spec=models.Snapshot)

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver._unexport_snapshot = mock.Mock()

        result = self.driver.terminate_connection(snapshot, CONNECTOR)

        self.driver._unexport_snapshot.assert_called_once_with(snapshot)
        self.driver.common.vip.basic.save_config.assert_called_with()
        self.assertTrue(result is None)

    def test_get_volume_stats(self):
        self.driver._update_stats = mock.Mock()
        self.driver._update_stats()

        result = self.driver.get_volume_stats(True)

        self.driver._update_stats.assert_called_with()
        self.assertEqual(self.driver.stats, result)

    def test_create_iscsi_target_group(self):
        target_name = self.driver.TARGET_GROUP_NAME
        bn = "/vshare/config/iscsi/target/%s" % target_name
        response1 = {}
        response2 = {'code': 0, 'message': 'success'}

        conf = {
            'basic.get_node_values.return_value': response1,
        }
        m_vshare = self.setup_mock_vshare(conf)

        self.driver.common.vip = m_vshare
        self.driver.common.mga = m_vshare
        self.driver.common.mgb = m_vshare
        self.driver.common._send_cmd_and_verify = mock.Mock(
            return_value=response2)
        self.driver.common._send_cmd = mock.Mock(return_value=response2)

        calls = [mock.call(self.driver.common.mga.iscsi.bind_ip_to_target, '',
                           target_name,
                           self.driver.gateway_iscsi_ip_addresses_mga),
                 mock.call(self.driver.common.mgb.iscsi.bind_ip_to_target, '',
                           target_name,
                           self.driver.gateway_iscsi_ip_addresses_mgb)]

        result = self.driver._create_iscsi_target_group()

        self.driver.common.vip.basic.get_node_values.assert_called_with(bn)
        self.driver.common._send_cmd_and_verify.assert_called_with(
            self.driver.common.vip.iscsi.create_iscsi_target,
            self.driver._wait_for_target_state, '',
            [target_name], [target_name])
        self.driver.common._send_cmd.assert_has_calls(calls)
        self.assertTrue(result is None)

    def test_export_lun(self):
        target_name = self.driver.TARGET_GROUP_NAME
        igroup = 'test-igroup-1'
        lun_id = '1'
        response = {'code': 0, 'message': ''}

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver.common._send_cmd_and_verify = mock.Mock(
            return_value=response)
        self.driver.common._get_lun_id = mock.Mock(return_value=lun_id)

        result = self.driver._export_lun(VOLUME, CONNECTOR, igroup)

        self.driver.common._send_cmd_and_verify.assert_called_with(
            self.driver.common.vip.lun.export_lun,
            self.driver.common._wait_for_export_state, '',
            [self.driver.common.container, VOLUME['id'], target_name,
             igroup, 'auto'], [VOLUME['id'], None, True])
        self.driver.common._get_lun_id.assert_called_with(VOLUME['id'])
        self.assertEqual(lun_id, result)

    def test_export_lun_fails_with_exception(self):
        igroup = 'test-igroup-1'
        lun_id = '1'
        response = {'code': 14000, 'message': 'Generic error'}
        failure = exception.ViolinBackendErr

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver.common._send_cmd_and_verify = mock.Mock(
            side_effect=failure(response['message']))
        self.driver._get_lun_id = mock.Mock(return_value=lun_id)

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
            self.driver.common._wait_for_export_state, '',
            [self.driver.common.container, VOLUME['id'], 'all', 'all', 'auto'],
            [VOLUME['id'], None, False])
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
        target_name = self.driver.TARGET_GROUP_NAME
        igroup = 'test-igroup-1'
        response = {'code': 0, 'message': ''}

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver.common._send_cmd = mock.Mock(return_value=response)
        self.driver.common._wait_for_export_state = mock.Mock()
        self.driver.common._get_snapshot_id = mock.Mock(return_value=lun_id)

        result = self.driver._export_snapshot(SNAPSHOT, CONNECTOR, igroup)

        self.driver.common._send_cmd.assert_called_with(
            self.driver.common.vip.snapshot.export_lun_snapshot, '',
            self.driver.common.container, SNAPSHOT['volume_id'],
            SNAPSHOT['id'], igroup, target_name, 'auto')
        self.driver.common._wait_for_export_state.assert_called_with(
            SNAPSHOT['volume_id'], SNAPSHOT['id'], state=True)
        self.driver.common._get_snapshot_id.assert_called_once_with(
            SNAPSHOT['volume_id'], SNAPSHOT['id'])

        self.assertEqual(lun_id, result)

    def test_unexport_snapshot(self):
        response = {'code': 0, 'message': ''}

        self.driver.common.vip = self.setup_mock_vshare()
        self.driver.common._send_cmd = mock.Mock(return_value=response)
        self.driver.common._wait_for_export_state = mock.Mock()

        result = self.driver._unexport_snapshot(SNAPSHOT)

        self.driver.common._send_cmd.assert_called_with(
            self.driver.common.vip.snapshot.unexport_lun_snapshot, '',
            self.driver.common.container, SNAPSHOT['volume_id'],
            SNAPSHOT['id'], 'all', 'all', 'auto', False)
        self.driver.common._wait_for_export_state.assert_called_with(
            SNAPSHOT['volume_id'], SNAPSHOT['id'], state=False)
        self.assertTrue(result is None)

    def test_add_igroup_member(self):
        igroup = 'test-group-1'
        response = {'code': 0, 'message': 'success'}

        conf = {
            'igroup.add_initiators.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        result = self.driver._add_igroup_member(CONNECTOR, igroup)

        self.driver.common.vip.igroup.add_initiators.assert_called_with(
            igroup, CONNECTOR['initiator'])
        self.assertTrue(result is None)

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

    def testGetShortName_LongName(self):
        long_name = "abcdefghijklmnopqrstuvwxyz1234567890"
        short_name = "abcdefghijklmnopqrstuvwxyz123456"
        self.assertEqual(short_name, self.driver._get_short_name(long_name))

    def testGetShortName_ShortName(self):
        long_name = "abcdef"
        short_name = "abcdef"
        self.assertEqual(short_name, self.driver._get_short_name(long_name))

    def testGetShortName_EmptyName(self):
        long_name = ""
        short_name = ""
        self.assertEqual(short_name, self.driver._get_short_name(long_name))

    def test_get_active_iscsi_ips(self):
        bn0 = "/net/interface/config/*"
        bn1 = ["/net/interface/state/eth4/addr/ipv4/1/ip",
               "/net/interface/state/eth4/flags/link_up"]
        response1 = {"/net/interface/config/eth4": "eth4"}
        response2 = {"/net/interface/state/eth4/addr/ipv4/1/ip": "1.1.1.1",
                     "/net/interface/state/eth4/flags/link_up": True}

        conf = {
            'basic.get_node_values.side_effect': [response1, response2],
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        results = self.driver._get_active_iscsi_ips(self.driver.common.vip)

        calls = [mock.call(bn0), mock.call(bn1)]
        self.driver.common.vip.basic.get_node_values.assert_has_calls(calls)
        self.assertEqual(1, len(results))
        self.assertEqual("1.1.1.1", results[0])

    def test_get_active_iscsi_ips_with_invalid_interfaces(self):
        response = {"/net/interface/config/lo": "lo",
                    "/net/interface/config/vlan10": "vlan10",
                    "/net/interface/config/eth1": "eth1",
                    "/net/interface/config/eth2": "eth2",
                    "/net/interface/config/eth3": "eth3"}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        result = self.driver._get_active_iscsi_ips(self.driver.common.vip)

        self.assertEqual(0, len(result))

    def test_get_active_iscsi_ips_with_no_interfaces(self):
        response = {}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        result = self.driver._get_active_iscsi_ips(self.driver.common.vip)

        self.assertEqual(0, len(result))

    def test_get_hostname(self):
        bn = '/system/hostname'
        response = {bn: 'MYHOST'}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        result = self.driver._get_hostname()

        self.driver.common.vip.basic.get_node_values.assert_called_with(bn)
        self.assertEqual("MYHOST", result)

    def test_get_hostname_mga(self):
        bn = '/system/hostname'
        response = {bn: 'MYHOST'}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver.common.mga = self.setup_mock_vshare(m_conf=conf)
        self.assertEqual("MYHOST", self.driver._get_hostname('mga'))

    def test_get_hostname_mgb(self):
        response = {"/system/hostname": "MYHOST"}
        bn = '/system/hostname'
        response = {bn: 'MYHOST'}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)
        self.driver.common.mgb = self.setup_mock_vshare(m_conf=conf)
        self.assertEqual("MYHOST", self.driver._get_hostname('mgb'))

    def test_get_hostname_query_fails(self):
        response = {}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.vip = self.setup_mock_vshare(m_conf=conf)

        self.assertEqual(self.conf.san_ip, self.driver._get_hostname())

    def test_wait_for_target_state(self):
        target = 'mytarget'
        bn = "/vshare/state/local/target/iscsi/%s" % target
        response = {bn: target}

        conf = {
            'basic.get_node_values.return_value': response,
        }
        self.driver.common.mga = self.setup_mock_vshare(m_conf=conf)
        self.driver.common.mgb = self.setup_mock_vshare(m_conf=conf)

        result = self.driver._wait_for_target_state(target)

        self.driver.common.mga.basic.get_node_values.assert_called_with(bn)
        self.driver.common.mgb.basic.get_node_values.assert_called_with(bn)
        self.assertTrue(result)
