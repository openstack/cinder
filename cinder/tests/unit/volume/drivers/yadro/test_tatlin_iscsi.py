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

from unittest import mock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest import TestCase

from cinder.tests.unit.volume.drivers.yadro.test_tatlin_common import \
    MockResponse
from cinder.volume import configuration
from cinder.volume.drivers.yadro.tatlin_client import TatlinAccessAPI
from cinder.volume.drivers.yadro.tatlin_client import TatlinClientCommon
from cinder.volume.drivers.yadro.tatlin_common import tatlin_opts
from cinder.volume.drivers.yadro.tatlin_common import TatlinCommonVolumeDriver
from cinder.volume.drivers.yadro.tatlin_iscsi import TatlinISCSIVolumeDriver
from cinder.volume.drivers.yadro.tatlin_utils import TatlinVolumeConnections


OSMGR_ISCSI_PORTS = [
    {
        "id": "ip-sp-1-98039b04091a",
        "meta": {
            "tatlin-node": "sp-1",
            "type": "ip",
            "port-type": "active"
        },
        "params": {
            "dhcp": False,
            "ifname": "p30",
            "physical-port": "p30",
            "ipaddress": "172.20.101.65",
            "netmask": "24",
            "mtu": "1500",
            "gateway": "172.20.101.1",
            "roles": "",
            "iflabel": "",
            "wwpn": ""
        }
    },
    {
        "id": "ip-sp-0-b8599f1caf1b",
        "meta": {
            "tatlin-node": "sp-0",
            "type": "ip",
            "port-type": "active"
        },
        "params": {
            "dhcp": False,
            "ifname": "p31",
            "physical-port": "p31",
            "ipaddress": "172.20.101.66",
            "netmask": "24",
            "mtu": "1500",
            "gateway": "172.20.101.1",
            "roles": "",
            "iflabel": "",
            "wwpn": ""
        }
    },
    {
        "id": "ip-sp-1-98039b04091b",
        "meta": {
            "tatlin-node": "sp-1",
            "type": "ip",
            "port-type": "active"
        },
        "params": {
            "dhcp": False,
            "ifname": "p31",
            "physical-port": "p31",
            "ipaddress": "172.20.101.67",
            "netmask": "24",
            "mtu": "1500",
            "gateway": "172.20.101.1",
            "roles": "",
            "iflabel": "",
            "wwpn": ""
        }
    },
    {
        "id": "ip-sp-0-b8599f1caf1a",
        "meta": {
            "tatlin-node": "sp-0",
            "type": "ip",
            "port-type": "active"
        },
        "params": {
            "dhcp": False,
            "ifname": "p30",
            "physical-port": "p30",
            "ipaddress": "172.20.101.64",
            "netmask": "24",
            "mtu": "1500",
            "gateway": "172.20.101.1",
            "roles": "",
            "iflabel": "",
            "wwpn": ""
        }
    },
]

ISCSI_PORT_PORTALS = {
    'p30': ['172.20.101.65:3260', '172.20.101.64:3260'],
    'p31': ['172.20.101.66:3260', '172.20.101.67:3260']
}

RES_PORTS_RESP = [
    {
        "port": "fc20",
        "port_status": "healthy",
        "port_status_desc": "resource is available",
        "running": [
            "sp-0",
            "sp-1"
        ],
        "wwn": [
            "10:00:14:52:90:00:03:10",
            "10:00:14:52:90:00:03:90"
        ],
        "lun": "scsi-lun-fc20-5",
        "volume": "pty-vol-0d9627cb-c52e-49f1-878c-57c9bc3010c9",
        "lun_index": "5"
    }
]

ALL_HOSTS_RESP = [
    {
        "version": "d6a2d310d9adb16f0d24d5352b5c4837",
        "id": "5e37d335-8fff-4aee-840a-34749301a16a",
        "name": "victoria-fc",
        "port_type": "fc",
        "initiators": [
            "21:00:34:80:0d:6b:aa:e3",
            "21:00:34:80:0d:6b:aa:e2"
        ],
        "tags": [],
        "comment": "",
        "auth": {}
    }
]

RES_MAPPING_RESP = [
    {
        "resource_id": "62bbb941-ba4a-4101-927d-e527ce5ee011",
        "host_id": "5e37d335-8fff-4aee-840a-34749301a16a",
        "mapped_lun_id": 1
    }
]

RESOURCE_INFORMATION = {
    "ptyId": "62bbb941-ba4a-4101-927d-e527ce5ee011",
    "id": "62bbb941-ba4a-4101-927d-e527ce5ee011",
    "name": "res1",
    "type": "block",
    "poolId": "c46584c5-3113-4cc7-8a72-f9262f32c508",
    "size": 1073741824,
    "maxModifySize": 5761094647808,
    "status": "ready",
    "stat": {
        "used_capacity": 1073741824,
        "mapped_blocks": 0,
        "dedup_count": 0,
        "reduction_ratio": 0
    },
    "lbaFormat": "4kn",
    "volume_id": "pty-vol-62bbb941-ba4a-4101-927d-e527ce5ee011",
    "wwid": "naa.614529011650000c4000800000000004",
    "lun_id": "4",
    "cached": "true",
    "rCacheMode": "enabled",
    "wCacheMode": "enabled",
    "ports": [
        {
            "port": "fc21",
            "port_status": "healthy",
            "port_status_desc":
            "resource is available on all storage controllers",
            "running": [
                "sp-1",
                "sp-0"
            ],
            "wwn": [
                "10:00:14:52:90:00:03:91",
                "10:00:14:52:90:00:03:11"
            ],
            "lun": "scsi-lun-fc21-4",
            "volume": "pty-vol-62bbb941-ba4a-4101-927d-e527ce5ee011",
            "lun_index": "4"
        },
        {
            "port": "fc20",
            "port_status": "healthy",
            "port_status_desc":
            "resource is available on all storage controllers",
            "running": [
                "sp-1",
                "sp-0"
            ],
            "wwn": [
                "10:00:14:52:90:00:03:10",
                "10:00:14:52:90:00:03:90"
            ],
            "lun": "scsi-lun-fc20-4",
            "volume": "pty-vol-62bbb941-ba4a-4101-927d-e527ce5ee011",
            "lun_index": "4"
        }
    ],
    "volume_path": "/dev/mapper/dmc-89382c6c-7cf9-4ff8-bdbb-f438d20c960a",
    "blockSize": "4kn",
    "replication": {
        "is_enabled": False
    }
}

ALL_HOST_GROUP_RESP = [
    {
        "version": "20c28d21549fb7ec5777637f72f50043",
        "id": "314b5546-45da-4c8f-a24c-b615265fbc32",
        "name": "cinder-group",
        "host_ids": [
            "5e37d335-8fff-4aee-840a-34749301a16a"
        ],
        "tags": None,
        "comment": ""
    }
]

HOST_GROUP_RESP = {
    "version": "20c28d21549fb7ec5777637f72f50043",
    "id": "314b5546-45da-4c8f-a24c-b615265fbc32",
    "name": "cinder-group",
    "host_ids": [
        "5e37d335-8fff-4aee-840a-34749301a16a"
    ],
    "tags": None,
    "comment": ""
}

ISCSI_HOST_INFO = {
    "version": "8c516c292055283e8ec3b7676d42f149",
    "id": "5e37d335-8fff-4aee-840a-34749301a16a",
    "name": "iscsi-host",
    "port_type": "iscsi",
    "initiators": [
        "iqn.1994-05.com.redhat:4e5d7ab85a4c",
    ],
    "tags": None,
    "comment": "",
    "auth": {
        "auth_type": "none"
    }
}

POOL_NAME = 'cinder-pool'


def get_fake_tatlin_config():
    config = configuration.Configuration(
        tatlin_opts,
        configuration.SHARED_CONF_GROUP)
    config.san_ip = '127.0.0.1'
    config.san_password = 'pwd'
    config.san_login = 'admin'
    config.pool_name = POOL_NAME
    config.host_group = 'cinder-group'
    config.tat_api_retry_count = 1
    config.wait_interval = 1
    config.wait_retry_count = 3
    config.chap_username = 'chap_user'
    config.chap_password = 'chap_passwd'
    config.state_path = '/tmp'
    return config


class TatlinISCSIVolumeDriverTest(TestCase):
    @mock.patch.object(TatlinVolumeConnections, 'create_store')
    @mock.patch.object(TatlinAccessAPI, '_authenticate_access')
    def setUp(self, auth_access, create_store):
        access_api = TatlinAccessAPI('127.0.0.1', '443',
                                     'user', 'passwd', False)
        access_api._authenticate_access = MagicMock()
        self.client = TatlinClientCommon(access_api,
                                         api_retry_count=1,
                                         wait_interval=1,
                                         wait_retry_count=1)
        mock.patch.object(TatlinAccessAPI, '_authenticate_access')
        self.driver = TatlinISCSIVolumeDriver(
            configuration=get_fake_tatlin_config())
        self.driver._get_tatlin_client = MagicMock()
        self.driver._get_tatlin_client.return_value = self.client
        self.driver.do_setup(None)

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_success_find_current_host(self, sr_mock):

        sr_mock.side_effect = [
            (MockResponse(ALL_HOST_GROUP_RESP, 200)),
            (MockResponse(HOST_GROUP_RESP, 200)),
            (MockResponse(ISCSI_HOST_INFO, 200)),
        ]
        self.assertEqual(self.driver.find_current_host(
            {'initiator': 'iqn.1994-05.com.redhat:4e5d7ab85a4c'}),
            '5e37d335-8fff-4aee-840a-34749301a16a')

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_success_get_ports_portals(self, sr_mock):
        sr_mock.side_effect = [
            (MockResponse(OSMGR_ISCSI_PORTS, 200)),
        ]
        portals = self.driver._get_ports_portals()
        self.assertEqual(portals, ISCSI_PORT_PORTALS)

    @mock.patch.object(TatlinCommonVolumeDriver, '_update_qos')
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_success_initialize_connection(self, sr_mock, qos_mock):
        self.driver._get_ports_portals = Mock(return_value=OSMGR_ISCSI_PORTS)
        self.driver.find_current_host = Mock(
            return_value='5e37d335-8fff-4aee-840a-34749301a16a')
        self.driver.add_volume_to_host = Mock()
        sr_mock.side_effect = [
            (MockResponse(RESOURCE_INFORMATION, 200)),  # Get volume
            (MockResponse(RES_MAPPING_RESP, 200)),      # In vol on host
            (MockResponse(RES_PORTS_RESP, 200)),        # Get ports
            (MockResponse(ALL_HOSTS_RESP, 200)),        # Find mapped LUN
        ]
