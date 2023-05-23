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

from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.dell_emc.powerstore import MockResponse
from cinder.volume.drivers.dell_emc.powerstore import client


CLIENT_OPTIONS = {
    "rest_ip": "127.0.0.1",
    "rest_username": "fake_user",
    "rest_password": "fake_password",
    "verify_certificate": False,
    "certificate_path": None
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
