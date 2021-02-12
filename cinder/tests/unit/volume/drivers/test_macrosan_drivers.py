# Copyright (c) 2019 MacroSAN Technologies Co., Ltd.
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
"""Tests for macrosan drivers."""
import os
import socket
from unittest import mock

from six.moves import UserDict

from cinder import exception
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.macrosan import devop_client
from cinder.volume.drivers.macrosan import driver
from cinder.volume import qos_specs
from cinder.volume import volume_types
from cinder.volume import volume_utils


test_volume = (
    UserDict({'name': 'volume-728ec287-bf30-4d2d-98a8-7f1bed3f59ce',
              'volume_name': 'test',
              'id': '728ec287-bf30-4d2d-98a8-7f1bed3f59ce',
              'provider_auth': None,
              'project_id': 'project',
              'display_name': 'test',
              'display_description': 'test',
              'host': 'controller@macrosan#MacroSAN',
              'size': 10,
              'provider_location':
              'macrosan uuid:0x00b34201-025b0000-46b35ae7-b7deec47'}))

test_volume.size = 10
test_volume.volume_type_id = '36674caf-5314-468a-a8cb-baab4f71fe44'
test_volume.volume_attachment = []

test_migrate_volume = {
    'name': 'volume-d42b436a-54cc-480a-916c-275b0258ef59',
    'size': 10,
    'volume_name': 'test',
    'id': 'd42b436a-54cc-480a-916c-275b0258ef59',
    'volume_id': 'd42b436a-54cc-480a-916c-275b0258ef59',
    'provider_auth': None,
    'project_id': 'project',
    'display_name': 'test',
    'display_description': 'test',
    'volume_type_id': '36674caf-5314-468a-a8cb-baab4f71fe44',
    '_name_id': None,
    'host': 'controller@macrosan#MacroSAN',
    'provider_location':
    'macrosan uuid:0x00b34201-00180000-9ac35425-9e288d9a'}

test_snap = {'name': 'volume-728ec287-bf30-4d2d-98a8-7f1bed3f59ce',
             'size': 10,
             'volume_name': 'test',
             'id': 'aa2419a3-c144-46af-831b-e0d914d3957b',
             'volume_id': '728ec287-bf30-4d2d-98a8-7f1bed3f59ce',
             'provider_auth': None,
             'project_id': 'project',
             'display_name': 'test',
             'display_description': 'test volume',
             'volume_type_id': '36674caf-5314-468a-a8cb-baab4f71fe44',
             'provider_location': 'pointid: 1',
             'volume_size': 10,
             'volume': test_volume}

test_connector = {'initiator': 'iqn.1993-08.org.debian:01:62027e12fbc',
                  'wwpns': ['500b342001001805', '500b342001004605'],
                  'wwnns': ['21000024ff2003ec', '21000024ff2003ed'],
                  'host': 'controller'
                  }

fake_fabric_mapping = {
    'switch1': {
        'target_port_wwn_list': ['500b342001001805', '500b342001004605'],
        'initiator_port_wwn_list': ['21000024ff2003ec', '21000024ff2003ed']
    }
}

expected_iscsi_properties = {'target_discovered': False,
                             'target_portal': '192.168.251.1:3260',
                             'target_iqn':
                             'iqn.2010-05.com.macrosan.target:controller',
                             'target_lun': 0,
                             'target_iqns':
                             ['iqn.2010-05.com.macrosan.target:controller',
                              'iqn.2010-05.com.macrosan.target:controller'],
                             'target_portals':
                             ['192.168.251.1:3260', '192.168.251.2:3260'],
                             'target_luns': [0, 0],
                             'volume_id':
                             '728ec287-bf30-4d2d-98a8-7f1bed3f59ce'
                             }

expected_iscsi_connection_data = {
    'client': 'devstack',
    'ports': [{'ip': '192.168.251.1',
               'port': 'eth-1:0:0',
               'port_name': 'iSCSI-Target-1:0:0',
               'target': 'iqn.2010-05.com.macrosan.target:controller'},
              {'ip': '192.168.251.2',
               'port': 'eth-2:0:0',
               'port_name': 'iSCSI-Target-2:0:0',
               'target': 'iqn.2010-05.com.macrosan.target:controller'}]}

expected_initr_port_map_tgtexist = {
    '21:00:00:24:ff:20:03:ec': [{'port_name': 'FC-Target-1:1:1',
                                 'wwn': '50:0b:34:20:01:00:18:05'},
                                {'port_name': 'FC-Target-2:1:1',
                                 'wwn': '50:0b:34:20:01:00:46:05'}],
    '21:00:00:24:ff:20:03:ed': [{'port_name': 'FC-Target-1:1:1',
                                 'wwn': '50:0b:34:20:01:00:18:05'},
                                {'port_name': 'FC-Target-2:1:1',
                                 'wwn': '50:0b:34:20:01:00:46:05'}]}

expected_initr_port_map_tgtnotexist = {'21:00:00:24:ff:20:03:ec': [],
                                       '21:00:00:24:ff:20:03:ed': []}

expected_fctgtexist_properties = {'target_lun': 0,
                                  'target_discovered': True,
                                  'target_wwn':
                                  ['500b342001001805', '500b342001004605'],
                                  'volume_id':
                                  '728ec287-bf30-4d2d-98a8-7f1bed3f59ce'
                                  }


class FakeMacroSANFCDriver(driver.MacroSANFCDriver):
    """Fake MacroSAN Storage, Rewrite some methods of MacroSANFCDriver."""
    def do_setup(self):
        self.client = FakeClient(self.sp1_ipaddr, self.sp2_ipaddr,
                                 self.username + self.passwd)
        self.fcsan_lookup_service = FCSanLookupService()

    @property
    def _self_node_wwns(self):
        return ['21000024ff2003ec', '21000024ff2003ed']

    def _snapshot_name(self, snapshotid):
        return "aa2419a3c14446af831be0d914d3957"

    def _get_client_name(self, host):
        return 'devstack'


class FCSanLookupService(object):
    def get_device_mapping_from_network(self, initiator_list,
                                        target_list):
        return fake_fabric_mapping


class DummyBrickGetConnector(object):
    def connect_volume(self, fake_con_data):
        return {'path': '/dev/mapper/3600b3429d72e349d93bad6597d0000df'}

    def disconnect_volume(self, fake_con_data, fake_device):
        return None


class FakeMacroSANISCSIDriver(driver.MacroSANISCSIDriver):
    """Fake MacroSAN Storage, Rewrite some methods of MacroSANISCSIDriver."""
    def do_setup(self):
        self.client = FakeClient(self.sp1_ipaddr, self.sp2_ipaddr,
                                 self.username + self.passwd)
        self.device_uuid = '0x00b34201-028100eb-4922a092-1d54b755'

    @property
    def _self_node_wwns(self):
        return ["iqn.1993-08.org.debian:01:62027e12fbc"]

    def _snapshot_name(self, snapshotid):
        return "aa2419a3c14446af831be0d914d3957"

    def _get_iscsi_ports(self, dev_client, host):
        if self.client.cmd_fail:
            raise exception.VolumeBackendAPIException(data='Command failed.')
        else:
            return [{'ip': '192.168.251.1', 'port_name': 'iSCSI-Target-1:0:0',
                     'port': 'eth-1:0:0',
                     'target': 'iqn.2010-05.com.macrosan.target:controller'},
                    {'ip': '192.168.251.2', 'port_name': 'iSCSI-Target-2:0:0',
                     'port': 'eth-2:0:0',
                     'target': 'iqn.2010-05.com.macrosan.target:controller'}]

    def _get_client_name(self, host):
        return 'devstack'

    def _attach_volume(self, context, volume, properties, remote=False):
        return super(FakeMacroSANISCSIDriver, self)._attach_volume(
            context, volume, properties, remote)

    def _detach_volume(self, context, attach_info, volume,
                       properties, force=False, remote=False,
                       ignore_errors=True):
        return super(FakeMacroSANISCSIDriver, self)._detach_volume(
            context, attach_info, volume, properties, force, remote,
            ignore_errors)


class FakeClient(devop_client.Client):
    def __init__(self, sp1_ip, sp2_ip, secret_key):
        self.cmd_fail = False
        self.tgt_notexist = False

    def get_raid_list(self, pool):
        return [{'name': 'RAID-1', 'free_cap': 1749}]

    def get_client(self, name):
        return True

    def create_lun(self, name, owner, pool, raids, lun_mode, size, lun_params):
        return True

    def get_pool_cap(self, pool):
        return 1862, 1749, 0

    def delete_lun(self, name):
        return True

    def setup_snapshot_resource(self, name, res_size, raids):
        pass

    def snapshot_resource_exists(self, name):
        return True

    def create_snapshot_point(self, lun_name, snapshot_name):
        if self.cmd_fail:
            raise exception.VolumeBackendAPIException(data='Command failed')
        else:
            return True

    def disable_snapshot(self, volume_name):
        if self.cmd_fail:
            raise exception.VolumeBackendAPIException(data='Command failed')
        else:
            return True

    def delete_snapshot_resource(self, volume_name):
        if self.cmd_fail:
            raise exception.VolumeBackendAPIException(data='Command failed')
        else:
            return True

    def snapshot_point_exists(self, lun_name, pointid):
        return True

    def lun_exists(self, name):
        return True

    def snapshot_enabled(self, lun_name):
        return True

    def create_snapshot_view(self, view_name, lun_name, pointid):
        if self.cmd_fail:
            raise exception.VolumeBackendAPIException(data='Command failed')
        else:
            return True

    def get_snapshot_pointid(self, lun_name, snapshot_name):
        if self.cmd_fail:
            raise exception.VolumeBackendAPIException(data='Command failed')
        else:
            return 1

    def delete_snapshot_view(self, view_name):
        return True

    def delete_snapshot_point(self, lun_name, pointid):
        return True

    def copy_volume_from_view(self, lun_name, view_name):
        return True

    def snapshot_copy_task_completed(self, lun_name):
        return True

    def extend_lun(self, name, raids, size):
        return True

    def initiator_exists(self, initr_wwn):
        return True

    def get_device_uuid(self):
        return '0x00b34201-025b0000-46b35ae7-b7deec47'

    def is_initiator_mapped_to_client(self, initr_wwn, client_name):
        return True

    def unmap_lun_to_it(self, lun_name, initr_wwn, tgt_port_name):
        if self.cmd_fail:
            raise exception.VolumeBackendAPIException('Command failed.')
        else:
            return None

    def map_lun_to_it(self, lun_name, initr_wwn, tgt_port_name, lun_id=-1):
        if self.cmd_fail:
            raise exception.VolumeBackendAPIException('Command failed.')
        else:
            return None

    def map_target_to_initiator(self, tgt_port_name, initr_wwn):
        return True

    def get_it_unused_id_list(self, it_type, initr_wwn, tgt_port_name):
        if self.cmd_fail:
            raise exception.VolumeBackendAPIException('Command failed.')
        else:
            return [i for i in range(511)]

    def enable_lun_qos(self, name, strategy):
        if self.cmd_fail:
            raise Exception()
        else:
            return None

    def get_fc_initr_mapped_ports(self, initr_wwns):
        return {'21:00:00:24:ff:20:03:ec':
                [{'wwn': '50:0b:34:20:01:00:18:05',
                  'port_name': 'FC-Target-1:1:1'},
                 {'wwn': '50:0b:34:20:01:00:46:05',
                  'port_name': 'FC-Target-2:1:1'}],
                '21:00:00:24:ff:20:03:ed':
                [{'wwn': '50:0b:34:20:01:00:18:05',
                  'port_name': 'FC-Target-1:1:1'},
                 {'wwn': '50:0b:34:20:01:00:46:05',
                  'port_name': 'FC-Target-2:1:1'}]
                }

    def get_fc_ports(self):
        if self.tgt_notexist:
            return [{'sp': 1, 'refcnt': 0,
                     'port_name': 'FC-Target-1:1:1',
                     'initr': '', 'online': 0,
                     'wwn': '50:0b:34:20:01:00:18:05',
                     'port': 'FC-1:1:1'},
                    {'sp': 2, 'refcnt': 0,
                     'port_name': 'FC-Target-2:1:1',
                     'initr': '', 'online': 0,
                     'wwn': '50:0b:34:20:01:00:46:05',
                     'port': 'FC-2:1:1'},
                    ]
        else:
            return [{'sp': 1, 'refcnt': 0,
                     'port_name': 'FC-Target-1:1:1',
                     'initr': '', 'online': 1,
                     'wwn': '50:0b:34:20:01:00:18:05',
                     'port': 'FC-1:1:1'},
                    {'sp': 2, 'refcnt': 0,
                     'port_name': 'FC-Target-2:1:1',
                     'initr': '', 'online': 1,
                     'wwn': '50:0b:34:20:01:00:46:05',
                     'port': 'FC-2:1:1'},
                    ]

    def get_lun_uuid(self, lun_name):
        return '0x00b34201-025b0000-46b35ae7-b7deec47'

    def get_lun_name(self, lun_uuid):
        if lun_uuid == "0x00b34201-025b0000-46b35ae7-b7deec47":
            return '728ec287-bf30-4d2d-98a8-7f1bed3f59ce'
        if lun_uuid == "0x00b34201-00180000-9ac35425-9e288d9a":
            return 'd42b436a-54cc-480a-916c-275b0258ef59'

    def get_lun_name_from_rename_file(self, name):
        return None

    def backup_lun_name_to_rename_file(self, cur_name, original_name):
        return None

    def get_lun_id(self, tgt_name, lun_name, type='FC'):
        return 0

    def get_view_lun_id(self, tgt_name, view_name, type='FC'):
        return 0


class MacroSANISCSIDriverTestCase(test.TestCase):
    def setUp(self):
        super(MacroSANISCSIDriverTestCase, self).setUp()
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.san_ip = "172.192.251.1, 172.192.251.2"
        self.configuration.san_login = "openstack"
        self.configuration.san_password = "passwd"
        self.configuration.macrosan_sdas_ipaddrs = None
        self.configuration.macrosan_replication_ipaddrs = None
        self.configuration.san_thin_provision = False
        self.configuration.macrosan_pool = 'Pool-1'
        self.configuration.macrosan_thin_lun_extent_size = 8
        self.configuration.macrosan_thin_lun_low_watermark = 8
        self.configuration.macrosan_thin_lun_high_watermark = 40
        self.configuration.macrosan_force_unmap_itl = False
        self.configuration.macrosan_snapshot_resource_ratio = 0.3
        self.configuration.macrosan_log_timing = True
        self.configuration.macrosan_client = \
            ['devstack; device1; "eth-1:0:0"; "eth-2:0:0"']
        self.configuration.macrosan_client_default = "eth-1:0:0;eth-2:0:0"
        self.driver = FakeMacroSANISCSIDriver(configuration=self.configuration)
        self.driver.do_setup()

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_create_volume(self, mock_volume_type, mock_qos):
        ret = self.driver.create_volume(test_volume)
        actual = ret['provider_location']
        self.assertEqual(test_volume['provider_location'], actual)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_create_qos_volume(self, mock_volume_type, mock_qos):
        test_volume.volume_type_id = 'a2ed23e0-76c4-426f-a574-a1327275e725'
        ret = self.driver.create_volume(test_volume)
        actual = ret['provider_location']
        self.assertEqual(test_volume['provider_location'], actual)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_delete_volume(self, mock_volume_type, mock_qos):
        self.driver.delete_volume(test_volume)

    def test_create_snapshot(self):
        self.driver.client.snappoid = True
        ret = self.driver.create_snapshot(test_snap)
        actual = ret['provider_location']
        self.assertEqual(test_snap['provider_location'], actual)

    def test_delete_snapshot(self):
        self.driver.delete_snapshot(test_snap)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    @mock.patch.object(socket, 'gethostname', return_value='controller')
    @mock.patch.object(volume_utils, 'brick_get_connector',
                       return_value=DummyBrickGetConnector())
    @mock.patch.object(volume_utils, 'copy_volume', return_value=None)
    @mock.patch.object(os.path, 'realpath', return_value=None)
    def test_create_volume_from_snapshot(self, mock_volume_type, mock_qos,
                                         mock_hostname,
                                         mock_brick_get_connector,
                                         mock_copy_volume,
                                         mock_os_path):
        ret = self.driver.create_volume_from_snapshot(test_volume, test_snap)
        actual = ret['provider_location']
        self.assertEqual(test_volume['provider_location'], actual)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    @mock.patch.object(socket, 'gethostname', return_value='controller')
    @mock.patch.object(volume_utils, 'brick_get_connector',
                       return_value=DummyBrickGetConnector())
    @mock.patch.object(volume_utils, 'copy_volume', return_value=None)
    @mock.patch.object(os.path, 'realpath', return_value=None)
    def test_create_cloned_volume(self, mock_volume_types, mock_qos,
                                  mock_hostname,
                                  mock_brick_get_connector,
                                  mock_copy_volume,
                                  mock_os_path):
        self.driver.client.snappoid = True
        ret = self.driver.create_cloned_volume(test_volume, test_volume)
        actual = ret['provider_location']
        self.assertEqual(test_volume['provider_location'], actual)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_extend_volume(self, mock_volume_type, mock_qos):
        self.driver.extend_volume(test_volume, 15)

    def test_update_migrated_volume(self):
        expected = {'_name_id':
                    test_migrate_volume['id'],
                    'provider_location':
                    test_migrate_volume['provider_location']}
        ret = self.driver.update_migrated_volume("", test_volume,
                                                 test_migrate_volume)
        self.assertEqual(expected, ret)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_initialize_connection(self, mock_volume_type, mock_qos):
        ret = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(expected_iscsi_properties, ret['data'])

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_terminate_connection(self, mock_volume_type, mock_qos):
        ret = self.driver.terminate_connection(test_volume, test_connector)
        self.assertEqual({'driver_volume_type': 'iSCSI',
                          'data': expected_iscsi_connection_data}, ret)

    def test_get_raid_list(self):
        expected = ["RAID-1"]
        ret = self.driver.get_raid_list(20)
        self.assertEqual(expected, ret)

    def test_get_volume_stats(self):
        ret = self.driver.get_volume_stats(True)
        expected = "iSCSI"
        self.assertEqual(expected, ret['storage_protocol'])

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_create_qos_volume_fail(self, mock_volume_type, mock_qos):
        test_volume.volume_type_id = 'a2ed23e0-76c4-426f-a574-a1327275e725'
        self.driver.client.cmd_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, test_volume)

    def test_create_snapshot_fail(self):
        self.driver.client.cmd_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, test_snap)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    @mock.patch.object(socket, 'gethostname', return_value='controller')
    @mock.patch.object(volume_utils, 'brick_get_connector',
                       return_value=DummyBrickGetConnector())
    @mock.patch.object(volume_utils, 'copy_volume', return_value=None)
    @mock.patch.object(os.path, 'realpath', return_value=None)
    def test_create_volume_from_snapshot_fail(self, mock_volume_type,
                                              mock_qos, mock_hostname,
                                              mock_brick_get_connector,
                                              mock_copy_volume,
                                              mock_os_path):
        self.driver.client.cmd_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_volume, test_snap)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    @mock.patch.object(socket, 'gethostname', return_value='controller')
    @mock.patch.object(volume_utils, 'brick_get_connector',
                       return_value=DummyBrickGetConnector())
    @mock.patch.object(volume_utils, 'copy_volume', return_value=None)
    @mock.patch.object(os.path, 'realpath', return_value=None)
    def test_create_cloned_volume_fail(self, mock_volume_types, mock_qos,
                                       mock_hostname,
                                       mock_brick_get_connector,
                                       mock_copy_volume,
                                       mock_os_path):
        self.driver.client.cmd_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          test_volume, test_volume)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_initialize_connection_fail(self, mock_volume_type, mock_qos):
        self.driver.client.cmd_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_terminate_connection_fail(self, mock_volume_type, mock_qos):
        self.driver.client.cmd_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          test_volume, test_connector)

    def test_get_raid_list_fail(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.get_raid_list, 2000)


class MacroSANFCDriverTestCase(test.TestCase):
    def setUp(self):
        super(MacroSANFCDriverTestCase, self).setUp()
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.san_ip = \
            "172.192.251.1, 172.192.251.2"
        self.configuration.san_login = "openstack"
        self.configuration.san_password = "passwd"
        self.configuration.macrosan_sdas_ipaddrs = None
        self.configuration.macrosan_replication_ipaddrs = None
        self.configuration.san_thin_provision = False
        self.configuration.macrosan_pool = 'Pool-1'
        self.configuration.macrosan_thin_lun_extent_size = 8
        self.configuration.macrosan_thin_lun_low_watermark = 8
        self.configuration.macrosan_thin_lun_high_watermark = 40
        self.configuration.macrosan_force_unmap_itl = False
        self.configuration.macrosan_snapshot_resource_ratio = 0.3
        self.configuration.macrosan_log_timing = True
        self.configuration.macrosan_host_name = 'devstack'
        self.configuration.macrosan_fc_use_sp_port_nr = 1
        self.configuration.macrosan_fc_keep_mapped_ports = True
        self.configuration.macrosan_host_name = 'devstack'
        self.configuration.macrosan_client = \
            ['devstack; device1; "eth-1:0:0"; "eth-2:0:0"']
        self.configuration.macrosan_client_default = \
            "eth-1:0:0;eth-2:0:0"
        self.driver = FakeMacroSANFCDriver(configuration=self.configuration)
        self.driver.do_setup()

    def test_get_initr_port_map_tgtnotexist(self):
        self.driver.client.tgt_notexist = True
        ret = self.driver._get_initr_port_map(self.driver.client,
                                              test_connector['wwpns'])
        self.assertEqual(expected_initr_port_map_tgtnotexist, ret)

    def test_get_initr_port_map_tgtexist(self):
        ret = self.driver._get_initr_port_map(self.driver.client,
                                              test_connector['wwpns'])
        self.assertEqual(expected_initr_port_map_tgtexist, ret)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_initialize_connection(self, mock_volume_types, mock_qos):
        ret = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(expected_fctgtexist_properties, ret['data'])

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_terminate_connection(self, mock_volume_types, mock_qos):
        ret = self.driver.terminate_connection(test_volume, test_connector)
        self.assertEqual({'driver_volume_type': 'fibre_channel', 'data': {}},
                         ret)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    @mock.patch.object(socket, 'gethostname', return_value='controller')
    @mock.patch.object(volume_utils, 'brick_get_connector',
                       return_value=DummyBrickGetConnector())
    @mock.patch.object(volume_utils, 'copy_volume', return_value=None)
    @mock.patch.object(os.path, 'realpath', return_value=None)
    def test_create_volume_from_snapshot(self, mock_volume_types, mock_qos,
                                         mock_hostname,
                                         mock_brick_get_connector,
                                         mock_copy_volume,
                                         mock_os_path):
        ret = self.driver.create_volume_from_snapshot(test_volume, test_snap)
        actual = ret['provider_location']
        self.assertEqual(test_volume['provider_location'], actual)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={
                           'qos_specs_id':
                               '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                           'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    @mock.patch.object(socket, 'gethostname', return_value='controller')
    @mock.patch.object(volume_utils, 'brick_get_connector',
                       return_value=DummyBrickGetConnector())
    @mock.patch.object(volume_utils, 'copy_volume', return_value=None)
    @mock.patch.object(os.path, 'realpath', return_value=None)
    def test_create_cloned_volume(self, mock_volume_types, mock_qos,
                                  mock_hostname,
                                  mock_brick_get_connector,
                                  mock_copy_volume,
                                  mock_os_path):
        self.driver.client.snappoid = True
        ret = self.driver.create_cloned_volume(test_volume, test_volume)
        actual = ret['provider_location']
        self.assertEqual(test_volume['provider_location'], actual)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    @mock.patch.object(socket, 'gethostname', return_value='controller')
    @mock.patch.object(volume_utils, 'brick_get_connector',
                       return_value=DummyBrickGetConnector())
    @mock.patch.object(volume_utils, 'copy_volume', return_value=None)
    @mock.patch.object(os.path, 'realpath', return_value=None)
    def test_create_volume_from_snapshot_fail(self, mock_volume_types,
                                              mock_qos,
                                              mock_hostname,
                                              mock_brick_get_connector,
                                              mock_copy_volume,
                                              mock_os_path):
        self.driver.client.cmd_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_volume, test_snap)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    @mock.patch.object(socket, 'gethostname', return_value='controller')
    @mock.patch.object(volume_utils, 'brick_get_connector',
                       return_value=DummyBrickGetConnector())
    @mock.patch.object(volume_utils, 'copy_volume', return_value=None)
    @mock.patch.object(os.path, 'realpath', return_value=None)
    def test_create_cloned_volume_fail(self, mock_volume_types, mock_qos,
                                       mock_hostname,
                                       mock_brick_get_connector,
                                       mock_copy_volume,
                                       mock_os_path):
        self.driver.client.cmd_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          test_volume, test_volume)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_initialize_connection_fail(self, mock_volume_types, mock_qos):
        self.driver.client.cmd_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'qos_specs_id':
                                     '99f3d240-1b20-4b7b-9321-c6b8b86243ff',
                                     'extra_specs': {}})
    @mock.patch.object(qos_specs, 'get_qos_specs',
                       return_value={'specs': {'qos-strategy': 'QoS-1'}})
    def test_terminate_connection_fail(self, mock_volume_types, mock_qos):
        self.driver.client.cmd_fail = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          test_volume, test_connector)
