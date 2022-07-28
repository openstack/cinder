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
from unittest import TestCase

import requests
from requests import codes

from cinder.exception import NotAuthorized
from cinder.exception import VolumeBackendAPIException
from cinder.tests.unit.fake_constants import VOLUME_NAME
from cinder.tests.unit.volume.drivers.yadro.test_tatlin_common import \
    DummyVolume
from cinder.tests.unit.volume.drivers.yadro.test_tatlin_common import \
    MockResponse
from cinder.volume.drivers.yadro import tatlin_api
from cinder.volume.drivers.yadro.tatlin_client import InitTatlinClient
from cinder.volume.drivers.yadro.tatlin_client import TatlinAccessAPI
from cinder.volume.drivers.yadro.tatlin_client import TatlinClientCommon
from cinder.volume.drivers.yadro.tatlin_client import TatlinClientV23
from cinder.volume.drivers.yadro.tatlin_client import TatlinClientV25
from cinder.volume.drivers.yadro.tatlin_exception import TatlinAPIException


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

POOL_LIST_RESPONCE = [
    {
        "id": "7e259486-deb8-4d11-8cb0-e2c5874aaa5e",
        "name": "cinder-pool",
        "status": "ready"
    }
]

VOL_ID = 'cinder-volume-id'

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


class TatlinClientTest(TestCase):
    @mock.patch.object(TatlinAccessAPI, '_authenticate_access')
    def setUp(self, auth_access):
        self.access_api = TatlinAccessAPI('127.0.0.1', 443,
                                          'user', 'passwd', False)
        self.client = TatlinClientV25(self.access_api,
                                      api_retry_count=1,
                                      wait_interval=1,
                                      wait_retry_count=1)

    @mock.patch.object(TatlinAccessAPI, '_authenticate_access')
    @mock.patch.object(TatlinAccessAPI, 'get_tatlin_version')
    def test_different_client_versions(self, version, auth):
        version.side_effect = [(2, 2), (2, 3), (2, 4), (2, 5), (3, 0)]
        args = ['1.2.3.4', 443, 'username', 'password', True, 1, 1, 1]
        self.assertIsInstance(InitTatlinClient(*args), TatlinClientV23)
        self.assertIsInstance(InitTatlinClient(*args), TatlinClientV23)
        self.assertIsInstance(InitTatlinClient(*args), TatlinClientV25)
        self.assertIsInstance(InitTatlinClient(*args), TatlinClientV25)
        self.assertIsInstance(InitTatlinClient(*args), TatlinClientV25)

    @mock.patch.object(requests, 'packages')
    @mock.patch.object(requests, 'session')
    def test_authenticate_success(self, session, packages):
        session().post.return_value = MockResponse({'token': 'ABC'},
                                                   codes.ok)
        TatlinAccessAPI('127.0.0.1', 443, 'user', 'passwd', False)
        session().post.assert_called_once_with(
            'https://127.0.0.1:443/auth/login',
            data={'user': 'user', 'secret': 'passwd'},
            verify=False
        )
        session().headers.update.assert_any_call({'X-Auth-Token': 'ABC'})

        TatlinAccessAPI('127.0.0.1', 443, 'user', 'passwd', True)
        session().headers.update.assert_any_call({'X-Auth-Token': 'ABC'})

    @mock.patch.object(requests, 'session')
    def test_authenticate_fail(self, session):
        session().post.return_value = MockResponse(
            {}, codes.unauthorized)
        self.assertRaises(NotAuthorized,
                          TatlinAccessAPI,
                          '127.0.0.1', 443, 'user', 'passwd', False)

    @mock.patch.object(TatlinAccessAPI, '_authenticate_access')
    @mock.patch.object(requests, 'session')
    def test_send_request(self, session, auth):
        session().request.side_effect = [
            MockResponse({}, codes.ok),
            MockResponse({}, codes.unauthorized),
            MockResponse({}, codes.ok)]

        access_api = TatlinAccessAPI('127.0.0.1', 443, 'user', 'passwd', True)
        access_api.session = session()
        access_api.send_request(tatlin_api.ALL_RESOURCES, {}, 'GET')
        access_api.session.request.assert_called_once_with(
            'GET',
            'https://127.0.0.1:443/' + tatlin_api.ALL_RESOURCES,
            json={},
            verify=True
        )

        access_api.send_request(tatlin_api.ALL_RESOURCES, {}, 'GET')
        self.assertEqual(auth.call_count, 2)
        access_api.session.request.assert_called_with(
            'GET',
            'https://127.0.0.1:443/' + tatlin_api.ALL_RESOURCES,
            json={},
            verify=True
        )

    @mock.patch.object(TatlinAccessAPI, '_authenticate_access')
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_get_tatlin_version(self, send_request, auth):
        send_request.return_value = MockResponse({'build-version': '2.3.0-44'},
                                                 codes.ok)
        access_api = TatlinAccessAPI('127.0.0.1', 443, 'user', 'passwd', True)
        self.assertEqual(access_api.get_tatlin_version(), (2, 3))
        send_request.assert_called_once()

        self.assertEqual(access_api.get_tatlin_version(), (2, 3))
        send_request.assert_called_once()

    @mock.patch.object(TatlinClientCommon, '_is_vol_on_host')
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_add_volume_to_host(self,
                                send_request,
                                is_on_host):
        vol = DummyVolume('62bbb941-ba4a-4101-927d-e527ce5ee011')

        # Success volume already on host
        is_on_host.side_effect = [True]
        self.client.add_vol_to_host(vol.name_id, 10)
        send_request.assert_not_called()

        # Success volume added
        is_on_host.side_effect = [False, True]
        send_request.side_effect = [(MockResponse({}, codes.ok)), ]
        self.client.add_vol_to_host(vol.name_id, 10)

        # Error adding volume to host
        is_on_host.side_effect = [False]
        send_request.side_effect = [
            TatlinAPIException(codes.internal_server_error, ''),
        ]

        with self.assertRaises(TatlinAPIException):
            self.client.add_vol_to_host(vol.name_id, 10)

        # Added successfull but not on host
        is_on_host.side_effect = [False, False]
        send_request.side_effect = [(MockResponse({}, codes.ok)), ]

        with self.assertRaises(VolumeBackendAPIException):
            self.client.add_vol_to_host(vol.name_id, 10)

    @mock.patch.object(TatlinClientCommon, '_is_vol_on_host')
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_remove_volume_to_host(self,
                                   send_request,
                                   is_on_host):
        vol = DummyVolume('62bbb941-ba4a-4101-927d-e527ce5ee011')

        # Success volume not on host
        is_on_host.side_effect = [False]
        self.client.remove_vol_from_host(vol.name_id, 10)
        send_request.assert_not_called()

        # Success volume removed
        is_on_host.side_effect = [True, False]
        send_request.side_effect = [(MockResponse({}, codes.ok)), ]
        self.client.remove_vol_from_host(vol.name_id, 10)

        # Remove from host rise an error
        is_on_host.side_effect = [True, False]
        send_request.side_effect = [
            TatlinAPIException(codes.internal_server_error, ''),
        ]
        with self.assertRaises(TatlinAPIException):
            self.client.remove_vol_from_host(vol.name_id, 10)

        # Removed successfull but still on host
        is_on_host.side_effect = [True, True]
        send_request.side_effect = [(MockResponse({}, codes.ok)), ]

        with self.assertRaises(VolumeBackendAPIException):
            self.client.remove_vol_from_host(vol.name_id, 10)

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_is_volume_exist_success(self, send_request):
        send_request.side_effect = [
            (MockResponse(RESOURCE_INFORMATION, codes.ok)),
        ]
        vol = DummyVolume('62bbb941-ba4a-4101-927d-e527ce5ee011')
        result = self.client.is_volume_exists(vol.name_id)
        self.assertTrue(result)

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_is_volume_exist_not_found(self, send_request):
        send_request.return_value = MockResponse(
            RESOURCE_INFORMATION, codes.not_found)
        vol = DummyVolume('62bbb941-ba4a-4101-927d-e527ce5ee011')
        result = self.client.is_volume_exists(vol.name_id)
        self.assertFalse(result)

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_is_volume_exist_unknown_error(self, send_request):
        send_request.return_value = MockResponse(
            {}, codes.internal_server_error)
        vol = DummyVolume('62bbb941-ba4a-4101-927d-e527ce5ee011')
        with self.assertRaises(VolumeBackendAPIException):
            self.client.is_volume_exists(vol.name_id)

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_delete_volume(self, send_request):
        vol = DummyVolume('62bbb941-ba4a-4101-927d-e527ce5ee011')
        # Success delete
        send_request.side_effect = [(MockResponse({}, codes.ok)), ]
        self.client.delete_volume(vol.name_id)

        # Volume does't exist
        send_request.side_effect = [(MockResponse({}, 404)), ]
        self.client.delete_volume(vol.name_id)

        # Volume delete error
        send_request.side_effect = [
            (MockResponse({}, codes.internal_server_error)),
        ]
        with self.assertRaises(TatlinAPIException):
            self.client.delete_volume(vol.name_id)

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_extend_volume(self, send_request):
        vol = DummyVolume('62bbb941-ba4a-4101-927d-e527ce5ee011')
        # Success delete
        send_request.side_effect = [(MockResponse({}, codes.ok)), ]
        self.client.extend_volume(vol.name_id, 20000)

        # Error
        send_request.side_effect = [
            (MockResponse({}, codes.internal_server_error)),
        ]
        with self.assertRaises(VolumeBackendAPIException):
            self.client.extend_volume(vol.name_id, 20000)

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_is_volume_ready(self, send_request):
        send_request.side_effect = [(MockResponse(READY_VOLUME, codes.ok)), ]
        self.assertTrue(self.client.is_volume_ready(VOLUME_NAME))

        send_request.side_effect = [
            (MockResponse(ERROR_VOLUME, codes.ok))
        ]
        self.assertFalse(self.client.is_volume_ready(VOLUME_NAME))

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_get_host_group_id_success(self, send_request):
        send_request.return_value = MockResponse(
            ALL_HOST_GROUP_RESP, codes.ok)
        self.assertEqual(self.client.get_host_group_id('cinder-group'),
                         '314b5546-45da-4c8f-a24c-b615265fbc32')

    @mock.patch.object(TatlinClientCommon,
                       'is_volume_exists',
                       return_value=True)
    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_get_resource_ports_array(self, send_request, *args):
        send_request.return_value = MockResponse(RES_PORTS_RESP, codes.ok)

        self.assertListEqual(self.client.get_resource_ports_array(VOL_ID),
                             ["fc20"])

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_get_resource_mapping_negative(self, send_request):
        send_request.return_value = MockResponse(
            {}, codes.internal_server_error)
        self.assertRaises(VolumeBackendAPIException,
                          self.client.get_resource_mapping)

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_get_pool_id_by_name(self, send_request, *args):
        send_request.return_value = MockResponse(POOL_LIST_RESPONCE, codes.ok)
        self.assertEqual(self.client.get_pool_id_by_name('cinder-pool'),
                         '7e259486-deb8-4d11-8cb0-e2c5874aaa5e')

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_get_all_hosts(self, send_request):
        send_request.return_value = MockResponse({}, codes.ok)
        self.client.get_all_hosts()

    @mock.patch.object(TatlinAccessAPI, 'send_request')
    def test_get_all_hosts_negative(self, send_request):
        send_request.return_value = MockResponse(
            {}, codes.internal_server_error)
        self.assertRaises(VolumeBackendAPIException,
                          self.client.get_all_hosts)
