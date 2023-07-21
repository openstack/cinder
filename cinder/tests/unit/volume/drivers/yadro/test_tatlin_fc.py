#  Copyright (C) 2021-2022 YADRO.
#  All rights reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import unittest
from unittest import mock

from cinder import exception
from cinder.tests.unit.volume.drivers.yadro import test_tatlin_client as tc
from cinder.volume import configuration
from cinder.volume.drivers.yadro import tatlin_client
from cinder.volume.drivers.yadro import tatlin_common
from cinder.volume.drivers.yadro import tatlin_fc
from cinder.volume.drivers.yadro import tatlin_utils


FC_PORTS_RESP = [
    {
        "id": "fc-sp-0-1000145290000320",
        "meta": {"tatlin-node": "sp-0", "type": "fc", "port-type": "active"},
        "params": {"ifname": "fc40", "wwpn": "10:00:14:52:90:00:03:20"}
    },
    {
        "id": "fc-sp-0-1000145290000321",
        "meta": {"tatlin-node": "sp-0", "type": "fc", "port-type": "active"},
        "params": {"ifname": "fc41", "wwpn": "10:00:14:52:90:00:03:21"}
    },
    {
        "id": "fc-sp-0-1000145290000310",
        "meta": {"tatlin-node": "sp-0", "type": "fc", "port-type": "active"},
        "params": {"ifname": "fc20", "wwpn": "10:00:14:52:90:00:03:10"}
    },
    {
        "id": "fc-sp-0-1000145290000311",
        "meta": {"tatlin-node": "sp-0", "type": "fc", "port-type": "active"},
        "params": {"ifname": "fc21", "wwpn": "10:00:14:52:90:00:03:11"}
    },
    {
        "id": "fc-sp-1-1000145290000390",
        "meta": {"tatlin-node": "sp-1", "type": "fc", "port-type": "active"},
        "params": {"ifname": "fc20", "wwpn": "10:00:14:52:90:00:03:90"}
    },
    {
        "id": "fc-sp-1-1000145290000391",
        "meta": {"tatlin-node": "sp-1", "type": "fc", "port-type": "active"},
        "params": {"ifname": "fc21", "wwpn": "10:00:14:52:90:00:03:91"}
    },
    {
        "id": "fc-sp-1-10001452900003a0",
        "meta": {"tatlin-node": "sp-1", "type": "fc", "port-type": "active"},
        "params": {"ifname": "fc40", "wwpn": "10:00:14:52:90:00:03:a0"}
    },
    {
        "id": "fc-sp-1-10001452900003a1",
        "meta": {"tatlin-node": "sp-1", "type": "fc", "port-type": "active"},
        "params": {"ifname": "fc41", "wwpn": "10:00:14:52:90:00:03:a1"}
    },
]

FC_PORTS_PORTALS = {
    'fc21': ['10:00:14:52:90:00:03:11', '10:00:14:52:90:00:03:91'],
    'fc20': ['10:00:14:52:90:00:03:10', '10:00:14:52:90:00:03:90'],
}

FC_TARGET_WWNS = [
    '1000145290000390',
    '1000145290000311',
    '1000145290000310',
    '1000145290000391',
]

FC_VOL_PORTS_RESP = [
    {
        "port": "fc21",
        "port_status": "healthy",
        "running": ["sp-0", "sp-1"],
        "wwn": ["10:00:14:52:90:00:03:11", "10:00:14:52:90:00:03:91"],
        "lun_index": tc.LUN_ID,
    },
    {
        "port": "fc20",
        "port_status": "healthy",
        "running": ["sp-0", "sp-1"],
        "wwn": ["10:00:14:52:90:00:03:10", "10:00:14:52:90:00:03:90"],
        "lun_index": tc.LUN_ID,
    },
    {
        "port": "fc40",
        "port_status": "healthy",
        "running": ["sp-0", "sp-1"],
        "wwn": ["10:00:14:52:90:00:03:09", "10:00:14:52:90:00:03:89"],
        "lun_index": tc.LUN_ID,
    },
]

HOST_WWNS = [
    '21000024ff7f35b7',
    '21000024ff7f35b6',
]

INITIATOR_TARGET_MAP = {
    '21000024ff7f35b7': FC_TARGET_WWNS,
    '21000024ff7f35b6': FC_TARGET_WWNS,
}

FC_CONNECTOR = {'wwpns': HOST_WWNS, 'host': 'myhost'}

FC_CONNECTOR_2 = {'wwpns': ['123', '456'], 'host': 'myhost'}

VOLUME_DATA = {
    'discard': False,
    'target_discovered': True,
    'target_lun': tc.LUN_ID,
    'target_wwn': [
        '10:00:14:52:90:00:03:11',
        '10:00:14:52:90:00:03:91',
        '10:00:14:52:90:00:03:10',
        '10:00:14:52:90:00:03:90',
    ],
    'initiator_target_map': INITIATOR_TARGET_MAP,
}


def get_fake_tatlin_config():
    config = configuration.Configuration(
        tatlin_common.tatlin_opts,
        configuration.SHARED_CONF_GROUP)
    config.san_ip = '127.0.0.1'
    config.san_password = 'pwd'
    config.san_login = 'admin'
    config.pool_name = tc.POOL_NAME
    config.host_group = 'cinder-group'
    config.tat_api_retry_count = 1
    config.wait_interval = 1
    config.wait_retry_count = 3
    config.chap_username = 'chap_user'
    config.chap_password = 'chap_passwd'
    config.state_path = '/tmp'
    config.export_ports = 'fc20,fc21'
    return config


class TatlinFCVolumeDriverTest(unittest.TestCase):
    @mock.patch.object(tatlin_utils.TatlinVolumeConnections,
                       'create_store')
    @mock.patch.object(tatlin_client.TatlinAccessAPI,
                       '_authenticate_access')
    def setUp(self, auth_access, create_store):
        access_api = tatlin_client.TatlinAccessAPI(
            '127.0.0.1', '443', 'user', 'passwd', False)
        access_api._authenticate_access = mock.MagicMock()
        self.client = tatlin_client.TatlinClientCommon(
            access_api, api_retry_count=1, wait_interval=1, wait_retry_count=1)
        mock.patch.object(tatlin_client.TatlinAccessAPI,
                          '_authenticate_access')
        self.driver = tatlin_fc.TatlinFCVolumeDriver(
            configuration=get_fake_tatlin_config())
        self.driver._get_tatlin_client = mock.MagicMock()
        self.driver._get_tatlin_client.return_value = self.client
        self.driver.do_setup(None)

    @mock.patch.object(tatlin_fc.fczm_utils, 'add_fc_zone')
    @mock.patch.object(tatlin_common.TatlinCommonVolumeDriver,
                       '_is_cinder_host_connection')
    @mock.patch.object(tatlin_fc.TatlinFCVolumeDriver,
                       '_create_volume_data')
    @mock.patch.object(tatlin_common.TatlinCommonVolumeDriver,
                       '_find_mapped_lun')
    @mock.patch.object(tatlin_common.TatlinCommonVolumeDriver,
                       'add_volume_to_host')
    @mock.patch.object(tatlin_fc.TatlinFCVolumeDriver,
                       'find_current_host')
    def test_initialize_connection(self,
                                   find_current_host,
                                   add_volume_to_host,
                                   find_mapped_lun,
                                   create_volume_data,
                                   is_cinder_connection,
                                   add_fc_zone):
        find_current_host.return_value = tc.HOST_ID
        find_mapped_lun.return_value = tc.LUN_ID
        is_cinder_connection.return_value = False
        create_volume_data.return_value = VOLUME_DATA
        volume = tc.DummyVolume(tc.VOL_ID)
        connector = FC_CONNECTOR
        data = self.driver.initialize_connection(volume, FC_CONNECTOR)
        self.assertDictEqual(
            data,
            {'driver_volume_type': 'fibre_channel', 'data': VOLUME_DATA}
        )
        find_current_host.assert_called_once()
        add_volume_to_host.assert_called_once_with(volume, tc.HOST_ID)
        is_cinder_connection.assert_called_once_with(connector)
        create_volume_data.assert_called_once_with(volume, connector)
        add_fc_zone.assert_called_once_with(data)

    @mock.patch.object(tatlin_fc.TatlinFCVolumeDriver,
                       '_create_volume_data')
    @mock.patch.object(tatlin_common.TatlinCommonVolumeDriver,
                       'add_volume_to_host')
    @mock.patch.object(tatlin_common.TatlinCommonVolumeDriver,
                       '_find_mapped_lun')
    @mock.patch.object(tatlin_fc.TatlinFCVolumeDriver,
                       'find_current_host')
    @mock.patch.object(tatlin_utils.TatlinVolumeConnections,
                       'increment')
    @mock.patch.object(tatlin_common.TatlinCommonVolumeDriver,
                       '_is_cinder_host_connection')
    def test_initialize_connection_cinder_attachement(self,
                                                      is_cinder_connection,
                                                      increment, *args):
        is_cinder_connection.return_value = True
        volume = tc.DummyVolume(tc.VOL_ID)
        self.driver.initialize_connection(volume, FC_CONNECTOR)
        is_cinder_connection.assert_called_once_with(FC_CONNECTOR)
        increment.assert_called_once_with(tc.VOL_ID)

    @mock.patch.object(tatlin_client.TatlinClientCommon,
                       'get_port_portal')
    def test_get_ports_portals(self, get_port_portal):
        get_port_portal.return_value = FC_PORTS_RESP
        pp = self.driver._get_ports_portals()
        self.assertDictEqual(pp, FC_PORTS_PORTALS)

    @mock.patch.object(tatlin_client.TatlinClientCommon,
                       'get_all_hosts')
    def test_find_current_host(self, get_all_hosts):
        get_all_hosts.return_value = tc.ALL_HOSTS_RESP
        host_id = self.driver.find_current_host(FC_CONNECTOR)
        self.assertEqual(host_id, tc.HOST_ID)

    @mock.patch.object(tatlin_client.TatlinClientCommon,
                       'get_all_hosts')
    def test_find_current_host_not_found(self,
                                         get_all_hosts):
        get_all_hosts.return_value = tc.ALL_HOSTS_RESP
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.find_current_host, FC_CONNECTOR_2)

    @mock.patch.object(tatlin_fc.TatlinFCVolumeDriver,
                       '_build_initiator_target_map')
    @mock.patch.object(tatlin_fc.TatlinFCVolumeDriver,
                       '_get_ports_portals')
    @mock.patch.object(tatlin_client.TatlinClientCommon,
                       'get_volume_ports')
    @mock.patch.object(tatlin_common.TatlinCommonVolumeDriver,
                       '_find_mapped_lun')
    def test_create_volume_data(self,
                                find_lun,
                                volume_ports,
                                ports_portals,
                                build_map):
        find_lun.return_value = tc.LUN_ID
        volume_ports.return_value = FC_VOL_PORTS_RESP
        ports_portals.return_value = FC_PORTS_PORTALS
        build_map.return_value = INITIATOR_TARGET_MAP
        volume = tc.DummyVolume(tc.VOL_ID)
        connector = FC_CONNECTOR
        data = self.driver._create_volume_data(volume, connector)
        self.assertEqual(data['target_lun'], tc.LUN_ID)
        self.assertEqual(sorted(data['target_wwn']), sorted(FC_TARGET_WWNS))
        self.assertDictEqual(data['initiator_target_map'],
                             INITIATOR_TARGET_MAP)

    @mock.patch.object(tatlin_fc.fczm_utils, 'remove_fc_zone')
    @mock.patch.object(tatlin_client.TatlinClientCommon,
                       'get_resource_mapping')
    @mock.patch.object(tatlin_fc.TatlinFCVolumeDriver,
                       '_create_volume_data')
    @mock.patch.object(tatlin_fc.TatlinFCVolumeDriver,
                       'find_current_host')
    @mock.patch.object(tatlin_common.TatlinCommonVolumeDriver,
                       '_is_cinder_host_connection')
    @mock.patch.object(tatlin_common.TatlinCommonVolumeDriver,
                       'remove_volume_from_host')
    def test_terminate_connection(self,
                                  remove_host,
                                  is_cinder,
                                  find_host,
                                  create_data,
                                  resource_mapping,
                                  remove_fc_zone):
        is_cinder.return_value = True
        find_host.return_value = tc.HOST_ID
        resource_mapping.return_value = tc.RES_MAPPING_RESP
        volume = tc.DummyVolume(tc.VOL_ID)
        connector = FC_CONNECTOR
        self.driver.terminate_connection(volume, connector)
        remove_host.assert_called_once_with(volume, tc.HOST_ID)
        remove_fc_zone.assert_not_called()

    @mock.patch.object(tatlin_fc.fczm_utils, 'remove_fc_zone')
    @mock.patch.object(tatlin_client.TatlinClientCommon,
                       'get_resource_mapping')
    @mock.patch.object(tatlin_fc.TatlinFCVolumeDriver,
                       '_create_volume_data')
    @mock.patch.object(tatlin_fc.TatlinFCVolumeDriver,
                       'find_current_host')
    @mock.patch.object(tatlin_common.TatlinCommonVolumeDriver,
                       '_is_cinder_host_connection')
    @mock.patch.object(tatlin_common.TatlinCommonVolumeDriver,
                       'remove_volume_from_host')
    def test_terminate_connection_with_zone_removal(self,
                                                    remove_host,
                                                    is_cinder,
                                                    find_host,
                                                    create_data,
                                                    resource_mapping,
                                                    remove_fc_zone):
        is_cinder.return_value = True
        find_host.return_value = tc.HOST_ID_2
        resource_mapping.side_effect = [
            tc.RES_MAPPING_RESP,
            tc.RES_MAPPING_RESP2,
        ]
        create_data.return_value = VOLUME_DATA
        volume = tc.DummyVolume(tc.VOL_ID)
        connector = FC_CONNECTOR
        self.driver.terminate_connection(volume, connector)
        remove_host.assert_called_once_with(volume, tc.HOST_ID_2)
        remove_fc_zone.assert_called_once_with({
            'driver_volume_type': 'fibre_channel',
            'data': VOLUME_DATA,
        })

    def test_build_initiator_target_map(self):
        self.driver._lookup_service = None
        connector = FC_CONNECTOR
        targets = FC_TARGET_WWNS
        itmap = self.driver._build_initiator_target_map(targets, connector)
        self.assertListEqual(sorted(itmap.keys()),
                             sorted(INITIATOR_TARGET_MAP.keys()))
        for initiator in itmap:
            self.assertListEqual(sorted(itmap[initiator]),
                                 sorted(INITIATOR_TARGET_MAP[initiator]))

    def test_build_initiator_target_map_with_lookup(self):
        lookup_service = mock.MagicMock()
        lookup_service.get_device_mapping_from_network.return_value = {
            'san-1': {
                'initiator_port_wwn_list': HOST_WWNS,
                'target_port_wwn_list': FC_TARGET_WWNS,
            },
        }
        self.driver._lookup_service = lookup_service
        connector = FC_CONNECTOR
        targets = FC_TARGET_WWNS
        itmap = self.driver._build_initiator_target_map(targets, connector)
        self.assertListEqual(sorted(itmap.keys()),
                             sorted(INITIATOR_TARGET_MAP.keys()))
        for initiator in itmap:
            self.assertListEqual(sorted(itmap[initiator]),
                                 sorted(INITIATOR_TARGET_MAP[initiator]))
        lookup_service.get_device_mapping_from_network.assert_called_once_with(
            connector['wwpns'], targets)
