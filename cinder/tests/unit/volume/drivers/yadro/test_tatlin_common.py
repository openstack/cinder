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

from cinder.cmd import manage as cinder_manage
from cinder.exception import ManageExistingInvalidReference
from cinder.exception import VolumeBackendAPIException
from cinder.tests.unit.fake_constants import VOLUME_NAME
from cinder.volume import configuration
from cinder.volume.drivers.yadro.tatlin_client import TatlinAccessAPI
from cinder.volume.drivers.yadro.tatlin_client import TatlinClientCommon
from cinder.volume.drivers.yadro.tatlin_common import tatlin_opts
from cinder.volume.drivers.yadro.tatlin_common import TatlinCommonVolumeDriver
from cinder.volume.drivers.yadro.tatlin_exception import TatlinAPIException
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

RES_MAPPING_RESP = [
    {
        "resource_id": "62bbb941-ba4a-4101-927d-e527ce5ee011",
        "host_id": "5e37d335-8fff-4aee-840a-34749301a16a",
        "mapped_lun_id": 1
    }
]

POOL_LIST_RESPONCE = [
    {
        "id": "7e259486-deb8-4d11-8cb0-e2c5874aaa5e",
        "name": "cinder-pool",
        "status": "ready"
    }
]

OK_POOL_ID = '7e259486-deb8-4d11-8cb0-e2c5874aaa5e'

WRONG_POOL_ID = 'wrong-id'

ERROR_VOLUME = [
    {
        "ptyId": "f28ee814-22ed-4bb0-8b6a-f7ce9075034a",
        "id": "f28ee814-22ed-4bb0-8b6a-f7ce9075034a",
        "name": "cinder-volume-f28ee814-22ed-4bb0-8b6a-f7ce9075034a",
        "type": "block",
        "poolId": "92c05782-7529-479f-8db7-b9435e1e9a3d",
        "size": 16106127360,
        "maxModifySize": 95330557231104,
        "status": "error",
    }
]

READY_VOLUME = [
    {
        "ptyId": "f28ee814-22ed-4bb0-8b6a-f7ce9075034a",
        "id": "f28ee814-22ed-4bb0-8b6a-f7ce9075034a",
        "name": "cinder-volume-f28ee814-22ed-4bb0-8b6a-f7ce9075034a",
        "type": "block",
        "poolId": "92c05782-7529-479f-8db7-b9435e1e9a3d",
        "size": 16106127360,
        "maxModifySize": 95330557231104,
        "status": "ready",
    }
]

ONLINE_VOLUME = [
    {
        "ptyId": "f28ee814-22ed-4bb0-8b6a-f7ce9075034a",
        "id": "f28ee814-22ed-4bb0-8b6a-f7ce9075034a",
        "name": "cinder-volume-f28ee814-22ed-4bb0-8b6a-f7ce9075034a",
        "type": "block",
        "poolId": "92c05782-7529-479f-8db7-b9435e1e9a3d",
        "size": 16106127360,
        "maxModifySize": 95330557231104,
        "status": "online",
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

POOL_NAME = 'cinder-pool'


class MockResponse:
    def __init__(self, json_data, status_code):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data


class DummyVolume(object):
    def __init__(self, volid, volsize=1):
        self.id = volid
        self._name_id = None
        self.size = volsize
        self.status = None
        self.__volume_type_id = 1
        self.attach_status = None
        self.volume_attachment = None
        self.provider_location = None
        self.name = None
        self.metadata = {}

    @property
    def name_id(self):
        return self.id if not self._name_id else self._name_id

    @property
    def name(self):
        return self.name_id

    @property
    def volume_type_id(self):
        return self.__volume_type_id

    @name_id.setter
    def name_id(self, value):
        self._name_id = value

    @name.setter
    def name(self, value):
        self._name_id = value

    @volume_type_id.setter
    def volume_type_id(self, value):
        self.__volume_type_id = value


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


class TatlinCommonVolumeDriverTest(TestCase):
    @mock.patch.object(TatlinVolumeConnections, 'create_store')
    @mock.patch.object(TatlinAccessAPI, '_authenticate_access')
    def setUp(self, auth_access, create_store):
        access_api = TatlinAccessAPI('127.0.0.1', '443',
                                     'user', 'passwd', False)
        access_api._authenticate_access = MagicMock()
        self.client = TatlinClientCommon(access_api,
                                         api_retry_count=1,
                                         wait_interval=1,
                                         wait_retry_count=3)
        self.driver = TatlinCommonVolumeDriver(
            configuration=get_fake_tatlin_config())
        self.driver._get_tatlin_client = MagicMock()
        self.driver._get_tatlin_client.return_value = self.client
        self.driver.do_setup(None)

    @mock.patch.object(TatlinClientCommon, 'delete_volume')
    @mock.patch.object(TatlinClientCommon, 'is_volume_exists')
    def test_delete_volume_ok(self, is_volume_exist, delete_volume):
        cinder_manage.cfg.CONF.set_override('lock_path', '/tmp/locks',
                                            group='oslo_concurrency')
        is_volume_exist.side_effect = [True, False, False]
        self.driver.delete_volume(DummyVolume(VOLUME_NAME))

    @mock.patch.object(TatlinClientCommon, 'delete_volume')
    @mock.patch.object(TatlinClientCommon, 'is_volume_exists')
    def test_delete_volume_ok_404(self, is_volume_exist, delete_volume):
        cinder_manage.cfg.CONF.set_override('lock_path', '/tmp/locks',
                                            group='oslo_concurrency')
        is_volume_exist.side_effect = [False]
        self.driver.delete_volume(DummyVolume(VOLUME_NAME))

    @mock.patch.object(TatlinClientCommon, 'delete_volume')
    @mock.patch.object(TatlinClientCommon, 'is_volume_exists')
    def test_delete_volume_error_500(self, is_volume_exist, delete_volume):
        cinder_manage.cfg.CONF.set_override('lock_path', '/tmp/locks',
                                            group='oslo_concurrency')
        is_volume_exist.return_value = True
        delete_volume.side_effect = TatlinAPIException(500, 'ERROR')
        with self.assertRaises(VolumeBackendAPIException):
            self.driver.delete_volume(DummyVolume(VOLUME_NAME))

    @mock.patch.object(TatlinCommonVolumeDriver, '_update_qos')
    @mock.patch.object(TatlinClientCommon, 'is_volume_ready')
    @mock.patch.object(TatlinClientCommon, 'extend_volume')
    @mock.patch.object(TatlinClientCommon, 'is_volume_exists')
    def test_extend_volume_ok(self,
                              is_volume_exist,
                              extend_volume,
                              is_volume_ready,
                              update_qos):
        cinder_manage.cfg.CONF.set_override('lock_path', '/tmp/locks',
                                            group='oslo_concurrency')
        is_volume_ready.return_value = True
        is_volume_exist.return_value = True
        self.driver.extend_volume(DummyVolume(VOLUME_NAME), 10)

    @mock.patch('time.sleep')
    @mock.patch.object(TatlinCommonVolumeDriver, '_update_qos')
    @mock.patch.object(TatlinClientCommon, 'is_volume_ready')
    @mock.patch.object(TatlinClientCommon, 'extend_volume')
    @mock.patch.object(TatlinClientCommon, 'is_volume_exists')
    def test_extend_volume_error_not_ready(self,
                                           is_volume_exist,
                                           extend_volume,
                                           is_volume_ready,
                                           update_qos,
                                           sleeper):
        cinder_manage.cfg.CONF.set_override('lock_path', '/tmp/locks',
                                            group='oslo_concurrency')
        is_volume_ready.return_value = False
        is_volume_exist.return_value = True
        with self.assertRaises(VolumeBackendAPIException):
            self.driver.extend_volume(DummyVolume(VOLUME_NAME), 10)

    @mock.patch.object(TatlinClientCommon,
                       'is_volume_ready',
                       return_value=True)
    def test_wait_volume_reay_success(self, is_ready):
        self.driver.wait_volume_ready(DummyVolume('cinder_volume'))

    @mock.patch.object(TatlinCommonVolumeDriver, '_update_qos')
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_succeess_manage_existing(self, sendMock, qosMock):
        sendMock.side_effect = [
            (MockResponse([{'id': '1', 'poolId': OK_POOL_ID}], 200)),
            (MockResponse(POOL_LIST_RESPONCE, 200))
        ]
        self.driver.manage_existing(DummyVolume(VOLUME_NAME), {
            'source-name': 'existing-resource'
        })

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_fail_manage_existing_volume_not_found(self, sendMock):
        self.driver.tatlin_api._send_request = Mock()
        sendMock.side_effect = [
            (MockResponse([{}], 404)),
        ]

        with self.assertRaises(ManageExistingInvalidReference):
            self.driver.manage_existing(DummyVolume('new-vol-id'), {
                'source-name': 'existing-resource'
            })
            self.driver.tatlin_api.get_volume_info.assert_called_once()
            self.driver.tatlin_api.get_pool_id_by_name.assert_not_called()

    @mock.patch.object(TatlinCommonVolumeDriver, '_update_qos')
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_fail_manage_existing_wrong_pool(self, sendMock, qosMock):
        sendMock.side_effect = [
            (MockResponse([{'id': '1', 'poolId': WRONG_POOL_ID}], 200)),
            (MockResponse(POOL_LIST_RESPONCE, 200))
        ]

        with self.assertRaises(ManageExistingInvalidReference):
            self.driver.manage_existing(DummyVolume('new-vol-id'), {
                'source-name': 'existing-resource'
            })
            self.driver.tatlin_api.get_volume_info.assert_called_once()
            self.driver.tatlin_api.get_pool_id_by_name.assert_called_once()

    @mock.patch.object(TatlinClientCommon, 'get_resource_count')
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_success_create_volume(self, send_requst, object_count):
        self.driver._stats['overall_resource_count'] = 1
        object_count.side_effect = [(1, 1)]
        send_requst.side_effect = [
            (MockResponse(POOL_LIST_RESPONCE, 200)),      # Get pool id
            (MockResponse({}, 200)),                      # Create volume
            (MockResponse(READY_VOLUME, 200)),          # Is volume ready
            (MockResponse(READY_VOLUME, 200))           # Is volume ready
        ]
        self.driver._update_qos = Mock()
        self.driver.create_volume(DummyVolume(VOLUME_NAME))

    @mock.patch.object(TatlinClientCommon, 'get_resource_count')
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_fail_create_volume_400(self, send_request, object_count):
        self.driver._stats['overall_resource_count'] = 1
        object_count.side_effect = [(1, 1)]
        send_request.side_effect = [
            (MockResponse(POOL_LIST_RESPONCE, 200)),
            (MockResponse({}, 500)),
            (MockResponse({}, 400))
        ]
        with self.assertRaises(VolumeBackendAPIException):
            self.driver.create_volume(DummyVolume(VOLUME_NAME))
            self.driver.tatlin_api.create_volume.assert_called_once()

    @mock.patch('time.sleep')
    @mock.patch.object(TatlinClientCommon, 'get_resource_count')
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_fail_volume_not_ready_create_volume(self, sendMock,
                                                 volume_count, sleeper):
        self.driver._stats['overall_resource_count'] = 1
        volume_count.side_effect = [(1, 1)]
        sendMock.side_effect = [
            (MockResponse(POOL_LIST_RESPONCE, 200)),
            (MockResponse({}, 200)),
            (MockResponse(ERROR_VOLUME, 200)),
            (MockResponse(ERROR_VOLUME, 200)),
            (MockResponse(ERROR_VOLUME, 200)),
        ]
        with self.assertRaises(VolumeBackendAPIException):
            self.driver.create_volume(DummyVolume(VOLUME_NAME))

    @mock.patch.object(TatlinCommonVolumeDriver, '_get_ports_portals')
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_fail_create_export(self, sendMock, portsMock):
        sendMock.side_effect = [
            (MockResponse(OSMGR_ISCSI_PORTS, 200)),
        ]

        portsMock.side_effect = [
            ISCSI_PORT_PORTALS
        ]
        self.driver._is_all_ports_assigned = Mock(return_value=True)
        with self.assertRaises(NotImplementedError):
            self.driver.create_export(None, DummyVolume(VOLUME_NAME), None)

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_find_mapped_lun(self, sendMock):
        sendMock.side_effect = [
            (MockResponse(RES_MAPPING_RESP, 200)),
        ]

        self.driver.find_current_host = Mock(
            return_value='5e37d335-8fff-4aee-840a-34749301a16a')
        self.driver._find_mapped_lun(
            '62bbb941-ba4a-4101-927d-e527ce5ee011', '')

    @mock.patch.object(TatlinCommonVolumeDriver, '_update_qos')
    @mock.patch.object(TatlinCommonVolumeDriver, 'wait_volume_online')
    @mock.patch.object(TatlinClientCommon, 'add_vol_to_host')
    @mock.patch.object(TatlinClientCommon,
                       'is_volume_exists',
                       return_value=True)
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_add_volume_to_host(self,
                                *args):
        vol = DummyVolume('62bbb941-ba4a-4101-927d-e527ce5ee011')
        self.driver.add_volume_to_host(
            vol, '5e37d335-8fff-4aee-840a-34749301a16a'
        )
