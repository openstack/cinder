# Copyright (c) 2021 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from unittest import mock
import uuid

import ddt
import requests.exceptions

from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.dell_emc.powerstore import MockResponse
from cinder.volume.drivers.dell_emc.powerstore import (
    exception as powerstore_exception)
from cinder.volume.drivers.dell_emc.powerstore import client


CLIENT_OPTIONS = {
    "rest_ip": "127.0.0.1",
    "rest_username": "fake_user",
    "rest_password": "fake_password",
    "verify_certificate": False,
    "certificate_path": None,
    "rest_api_connect_timeout": 60,
    "rest_api_read_timeout": 60
}

ISCSI_IP_POOL_RESP = [
    {
        "address": "1.2.3.4",
        "ip_port": {
            "target_iqn":
                "iqn.2022-07.com.dell:dellemc-powerstore-fake-iqn-1"
        },
    },
    {
        "address": "5.6.7.8",
        "ip_port": {
            "target_iqn":
                "iqn.2022-07.com.dell:dellemc-powerstore-fake-iqn-1"
        },
    },
]

NVME_IP_POOL_RESP = [
    {
        "address": "11.22.33.44"
    },
    {
        "address": "55.66.77.88"
    }
]

QOS_IO_RULE_PARAMS = {
    "name": "io-rule-6b6e5489-4b5b-4468-a1f7-32cec2ffa3bf",
    "type": "Absolute",
    "max_iops": "200",
    "max_bw": "18000",
    "burst_percentage": "50"
}

QOS_POLICY_PARAMS = {
    "name": "qos-policy-6b6e5489-4b5b-4468-a1f7-32cec2ffa3bf",
    "io_limit_rule_id": "9beb10ff-a00c-4d88-a7d9-692be2b3073f"
}

QOS_UPDATE_IO_RULE_PARAMS = {
    "type": "Absolute",
    "max_iops": "500",
    "max_bw": "225000",
    "burst_percentage": "89"
}

HOST_RESP = [
    {
        "id": "0381297d-7c64-41d0-9077-95f90aee3dac",
        "name": "test_host_lCdRMtul",
        "host_initiators": [
            {
                "port_name": "iqn.1994-05.com.dell:tpxskxiwttsh",
                "port_type": "iSCSI",
            }
        ],
        "host_connectivity": "Local_Only"
    },
    {
        "id": "accb64a9-833f-4f34-b866-bbf0de769024",
        "name": "vpi6190-iSCSI",
        "host_initiators": [
            {
                "port_name": "iqn.2016-04.com.open-iscsi:f5bc3538fe1e",
                "port_type": "iSCSI",
            }
        ],
        "host_connectivity": "Metro_Optimize_Local"
    },
]


@ddt.ddt
class TestClient(test.TestCase):

    def setUp(self):
        super(TestClient, self).setUp()

        self.client = client.PowerStoreClient(**CLIENT_OPTIONS)
        self.fake_volume = str(uuid.uuid4())

    @ddt.data(("iSCSI", ISCSI_IP_POOL_RESP),
              ("NVMe", NVME_IP_POOL_RESP))
    @ddt.unpack
    @mock.patch("requests.request")
    def test_get_ip_pool_address(self, protocol, ip_pool, mock_request):
        mock_request.return_value = MockResponse(ip_pool, rc=200)
        response = self.client.get_ip_pool_address(protocol)
        mock_request.assert_called_once()
        self.assertEqual(response, ip_pool)

    @mock.patch("requests.request")
    def test_get_volume_nguid(self, mock_request):
        mock_request.return_value = MockResponse(
            content={
                "nguid": "nguid.76e02b0999y439958ttf546800ea7fe8"
            },
            rc=200
        )
        self.assertEqual(self.client.get_volume_nguid(self.fake_volume),
                         "76e02b0999y439958ttf546800ea7fe8")

    @mock.patch("requests.request")
    def test_get_array_version(self, mock_request):
        mock_request.return_value = MockResponse(
            content=[
                {
                    "release_version": "3.0.0.0",
                }
            ],
            rc=200
        )
        self.assertEqual(self.client.get_array_version(),
                         "3.0.0.0")

    @mock.patch("requests.request")
    def test_get_qos_policy_id_by_name(self, mock_request):
        mock_request.return_value = MockResponse(
            content=[
                {
                    "id": "d69f7131-4617-4bae-89f8-a540a6bda94b",
                }
            ],
            rc=200
        )
        self.assertEqual(
            self.client.get_qos_policy_id_by_name("qos-"
                                                  "policy-6b6e5489"
                                                  "-4b5b-4468-a1f7-"
                                                  "32cec2ffa3bf"),
            "d69f7131-4617-4bae-89f8-a540a6bda94b")

    @mock.patch("requests.request")
    def test_get_qos_policy_id_by_name_exception(self, mock_request):
        mock_request.return_value = MockResponse(rc=400)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.client.get_qos_policy_id_by_name,
            "qos-policy-6b6e5489-4b5b-4468-a1f7-32cec2ffa3bf")

    @mock.patch("requests.request")
    def test_create_qos_io_rule(self, mock_request):
        mock_request.return_value = MockResponse(
            content={
                "id": "9beb10ff-a00c-4d88-a7d9-692be2b3073f"
            },
            rc=200
        )
        self.assertEqual(
            self.client.create_qos_io_rule(QOS_IO_RULE_PARAMS),
            "9beb10ff-a00c-4d88-a7d9-692be2b3073f")

    @mock.patch("requests.request")
    def test_create_duplicate_qos_io_rule(self, mock_request):
        mock_request.return_value = MockResponse(
            content={
                "messages": [
                    {
                        "code": "0xE0A0E0010009",
                        "severity": "Error",
                        "message_l10n": "The rule name "
                        "io-rule-9899a65f-70fe-46c9-8f6c-22625c7e19df "
                        "is already used by another rule. "
                        "It needs to be unique (case-insensitive). "
                        "Please use a different name.",
                        "arguments": [
                            "io-rule-6b6e5489-4b5b-4468-a1f7-32cec2ffa3bf"
                        ]
                    }
                ]
            },
            rc=400
        )
        self.assertRaises(
            powerstore_exception.DellPowerStoreQoSIORuleExists,
            self.client.create_qos_io_rule,
            QOS_IO_RULE_PARAMS)

    @mock.patch("requests.request")
    def test_create_duplicate_qos_io_rule_with_unexpected_error(
            self, mock_request):
        mock_request.return_value = MockResponse(
            content={
                "messages": [
                    {
                        "code": "0xE0101001000C",
                        "severity": "Error",
                        "message_l10n": "The system encountered unexpected "
                                        "backend errors. "
                                        "Please contact support."
                    }
                ]
            },
            rc=400
        )
        self.assertRaises(
            powerstore_exception.DellPowerStoreQoSIORuleExists,
            self.client.create_qos_io_rule,
            QOS_IO_RULE_PARAMS)

    @mock.patch("requests.request")
    def test_create_qos_policy(self, mock_request):
        mock_request.return_value = MockResponse(
            content={
                "id": "d69f7131-4617-4bae-89f8-a540a6bda94b",
            },
            rc=200
        )
        self.assertEqual(
            self.client.create_qos_policy(QOS_POLICY_PARAMS),
            "d69f7131-4617-4bae-89f8-a540a6bda94b")

    @mock.patch("requests.request")
    def test_create_duplicate_qos_policy(self, mock_request):
        mock_request.return_value = MockResponse(
            content={
                "messages": [
                    {
                        "code": "0xE02020010004",
                        "severity": "Error",
                        "message_l10n": "The new policy name qos-policy-"
                                        "6b6e5489-4b5b-4468-a1f7-32cec2ffa3bf "
                                        "is in use. It must be unique "
                                        "regardless of character cases.",
                        "arguments": [
                            "qos-policy-6b6e5489-4b5b-4468-a1f7-32cec2ffa3bf"
                        ]
                    }
                ]
            },
            rc=400
        )
        self.assertRaises(
            powerstore_exception.DellPowerStoreQoSPolicyExists,
            self.client.create_qos_policy,
            QOS_POLICY_PARAMS)

    @mock.patch("requests.request")
    def test_update_volume_with_qos_policy(self, mock_request):
        mock_request.return_value = MockResponse(rc=200)
        self.client.update_volume_with_qos_policy(
            "fake_volume_id",
            "qos-policy-6b6e5489-4b5b-4468-a1f7-32cec2ffa3bf")
        mock_request.assert_called_once()

    @mock.patch("requests.request")
    def test_update_volume_with_qos_policy_exception(self, mock_request):
        mock_request.return_value = MockResponse(rc=400)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.update_volume_with_qos_policy,
                          "fake_volume_id",
                          "qos-policy-6b6e5489-4b5b-4468-a1f7-32cec2ffa3bf")

    @mock.patch("requests.request")
    def test_update_qos_io_rule(self, mock_request):
        mock_request.return_value = MockResponse(rc=200)
        self.client.update_qos_io_rule(
            "io-rule-6b6e5489-4b5b-4468-a1f7-32cec2ffa3bf",
            QOS_UPDATE_IO_RULE_PARAMS)
        mock_request.assert_called_once()

    @mock.patch("requests.request")
    def test_update_qos_io_rule_exception(self, mock_request):
        mock_request.return_value = MockResponse(rc=400)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.update_qos_io_rule,
                          "io-rule-6b6e5489-4b5b-4468-a1f7-32cec2ffa3bf",
                          QOS_UPDATE_IO_RULE_PARAMS)

    @mock.patch("requests.request")
    def test_get_request_timeout_exception(self, mock_request):
        mock_request.return_value = MockResponse(
            rc=501
        )
        error = self.assertRaises(
            exception.VolumeBackendAPIException,
            self.client.get_array_version)
        self.assertEqual('Bad or unexpected response from the '
                         'storage volume backend API: Failed to '
                         'query PowerStore array version.',
                         error.msg)

    @mock.patch("requests.request")
    def test_send_get_request_connect_timeout_exception(self,
                                                        mock_request):
        mock_request.side_effect = requests.exceptions.ConnectTimeout()
        r, resp = self.client._send_request("GET",
                                            "/api/version")
        self.assertEqual(500, r.status_code)

    @mock.patch("requests.request")
    def test_send_get_request_read_timeout_exception(self,
                                                     mock_request):
        mock_request.side_effect = requests.exceptions.ReadTimeout()
        r, resp = self.client._send_request("GET",
                                            "/api/version")
        self.assertEqual(500, r.status_code)

    @mock.patch("requests.request")
    def test_send_post_request_connect_timeout_exception(self,
                                                         mock_request):
        params = {}
        mock_request.side_effect = requests.exceptions.ConnectTimeout()
        r, resp = self.client._send_request("POST",
                                            "/metrics/generate",
                                            params)
        self.assertEqual(500, r.status_code)

    @mock.patch("requests.request")
    def test_send_post_request_read_timeout_exception(self,
                                                      mock_request):
        params = {}
        mock_request.side_effect = requests.exceptions.ReadTimeout()
        r, resp = self.client._send_request("POST",
                                            "/metrics/generate",
                                            params)
        self.assertEqual(500, r.status_code)

    @mock.patch('requests.request')
    def test_get_all_hosts_success(self, mock_request):
        mock_request.return_value = MockResponse(
            content=HOST_RESP,
            rc=200
        )
        response = self.client.get_all_hosts('iSCSI')
        self.assertEqual(response, HOST_RESP)

    @mock.patch('requests.request')
    def test_get_all_hosts_failure(self, mock_request):
        mock_request.return_value = MockResponse(rc=500)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.get_all_hosts,
                          "iSCSI")

    @mock.patch('requests.request')
    def test_create_host_success(self, mock_request):
        mock_request.return_value = MockResponse(
            content=HOST_RESP[1],
            rc=200
        )
        response = self.client.create_host(
            'vpi6190-iSCSI',
            'iqn.2016-04.com.open-iscsi:f5bc3538fe1e',
            'Metro_Optimize_Local')
        self.assertEqual(response, HOST_RESP[1])

    @mock.patch('requests.request')
    def test_create_host_failure(self, mock_request):
        mock_request.return_value = MockResponse(rc=500)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.create_host,
                          'host1',
                          'port1')

    @mock.patch('cinder.volume.drivers.dell_emc.powerstore.'
                'client.PowerStoreClient._send_post_request')
    def test_configure_metro_with_remote_appliance_name(
            self, mock_send_post_request):
        r = MockResponse(
            rc=200,
            content={"metro_replication_session_id": "1234"}
        )
        mock_send_post_request.return_value = (r, r.json())
        volume_id = "123"
        remote_system_name = "system1"
        remote_appliance_name = "appliance1"

        result = self.client.configure_metro(
            volume_id, remote_system_name, remote_appliance_name)

        mock_send_post_request.assert_called_once_with(
            "/volume/123/configure_metro",
            {
                "remote_system_id": "name:system1",
                "remote_appliance_id": "name:appliance1"
            }
        )
        self.assertEqual(result, "1234")

    @mock.patch('cinder.volume.drivers.dell_emc.powerstore.'
                'client.PowerStoreClient._send_post_request')
    def test_configure_metro_without_remote_appliance_name(
            self, mock_send_post_request):
        r = MockResponse(
            rc=200,
            content={"metro_replication_session_id": "5678"}
        )
        mock_send_post_request.return_value = (r, r.json())
        volume_id = "456"
        remote_system_name = "system2"

        result = self.client.configure_metro(
            volume_id, remote_system_name)

        mock_send_post_request.assert_called_once_with(
            "/volume/456/configure_metro",
            {
                "remote_system_id": "name:system2",
                "remote_appliance_id": None
            }
        )
        self.assertEqual(result, "5678")

    @mock.patch('cinder.volume.drivers.dell_emc.powerstore.'
                'client.PowerStoreClient._send_post_request')
    def test_configure_metro_with_failed_request(self, mock_send_post_request):
        r = MockResponse(rc=500)
        mock_send_post_request.return_value = (r, None)
        volume_id = "789"
        remote_system_name = "system3"

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.configure_metro,
                          volume_id, remote_system_name)

        mock_send_post_request.assert_called_once_with(
            "/volume/789/configure_metro",
            {
                "remote_system_id": "name:system3",
                "remote_appliance_id": None
            }
        )

    @mock.patch('cinder.volume.drivers.dell_emc.powerstore.'
                'client.PowerStoreClient._send_post_request')
    def test_end_metro_success(self, mock_send_post_request):
        mock_send_post_request.return_value = (
            MockResponse(rc=200),
            None
        )

        self.client.end_metro("volume_id", delete_remote_volume=True)

        mock_send_post_request.assert_called_once_with(
            "/volume/volume_id/end_metro",
            payload={"delete_remote_volume": True},
        )

    @mock.patch('cinder.volume.drivers.dell_emc.powerstore.'
                'client.PowerStoreClient._send_post_request')
    def test_end_metro_failure(self, mock_send_post_request):
        mock_send_post_request.return_value = (
            MockResponse(rc=500),
            None
        )

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.end_metro,
                          "volume_id",
                          False)

        mock_send_post_request.assert_called_once_with(
            "/volume/volume_id/end_metro",
            payload={"delete_remote_volume": False},
        )

    @mock.patch('cinder.volume.drivers.dell_emc.powerstore.'
                'client.PowerStoreClient._send_get_request')
    def test_get_replication_session_state_success(
            self, mock_send_get_request):
        r = MockResponse(
            rc=200,
            content={'state': 'OK'}
        )
        mock_send_get_request.return_value = (r, r.json())
        state = self.client.get_replication_session_state('rep_session_id')
        self.assertEqual(state, 'OK')

    @mock.patch('cinder.volume.drivers.dell_emc.powerstore.'
                'client.PowerStoreClient._send_get_request')
    def test_get_replication_session_state_failure(
            self, mock_send_get_request):
        mock_send_get_request.return_value = (
            MockResponse(rc=404),
            None
        )
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.get_replication_session_state,
                          'rep_session_id')

    @mock.patch('cinder.volume.drivers.dell_emc.powerstore.'
                'client.PowerStoreClient._send_get_request')
    def test_get_cluster_name_success(self, mock_send_get_request):
        r = MockResponse(
            rc=200,
            content=[{'name': 'cluster_name'}]
        )
        mock_send_get_request.return_value = (r, r.json())
        result = self.client.get_cluster_name()
        self.assertEqual(result, 'cluster_name')

    @mock.patch('cinder.volume.drivers.dell_emc.powerstore.'
                'client.PowerStoreClient._send_get_request')
    def test_get_cluster_name_failure(self, mock_send_get_request):
        mock_send_get_request.return_value = (
            MockResponse(rc=404),
            None
        )
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.get_cluster_name)

    @mock.patch('cinder.volume.drivers.dell_emc.powerstore.'
                'client.PowerStoreClient._send_patch_request')
    def test_modify_host_connectivity_success(
            self, _send_patch_request):
        _send_patch_request.return_value = (
            MockResponse(rc=200),
            None
        )
        self.client.modify_host_connectivity('host_id', 'Local_Only')
        _send_patch_request.assert_called_once_with(
            "/host/host_id",
            payload={"host_connectivity": "Local_Only"}
        )

    @mock.patch('cinder.volume.drivers.dell_emc.powerstore.'
                'client.PowerStoreClient._send_patch_request')
    def test_modify_host_connectivity_failure(
            self, _send_patch_request):
        _send_patch_request.return_value = (
            MockResponse(rc=500),
            None
        )
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.modify_host_connectivity,
                          'host_id',
                          'Local_Only')
