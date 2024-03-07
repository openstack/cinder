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
