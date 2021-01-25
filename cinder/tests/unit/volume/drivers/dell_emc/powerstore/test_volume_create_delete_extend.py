# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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

from cinder import exception
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerstore
from cinder.volume.drivers.dell_emc.powerstore import client


class TestVolumeCreateDeleteExtend(powerstore.TestPowerStoreDriver):
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def setUp(self, mock_chap):
        super(TestVolumeCreateDeleteExtend, self).setUp()
        self.driver.check_for_setup_error()
        self.volume = fake_volume.fake_volume_obj(
            self.context,
            host="host@backend",
            provider_id="fake_id",
            size=8
        )

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.create_volume")
    def test_create_volume(self, mock_create):
        mock_create.return_value = "fake_id"
        self.driver.create_volume(self.volume)

    @mock.patch("requests.request")
    def test_create_volume_bad_status(self, mock_create_request):
        mock_create_request.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.create_volume,
                                  self.volume)
        self.assertIn("Failed to create PowerStore volume", error.msg)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter._detach_volume_from_hosts")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.delete_volume_or_snapshot")
    def test_delete_volume(self, mock_delete, mock_detach):
        self.driver.delete_volume(self.volume)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter._detach_volume_from_hosts")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.delete_volume_or_snapshot")
    def test_delete_volume_no_provider_id(self, mock_delete, mock_detach):
        self.volume.provider_id = None
        self.driver.delete_volume(self.volume)
        mock_detach.assert_not_called()
        mock_delete.assert_not_called()

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter._detach_volume_from_hosts")
    @mock.patch("requests.request")
    def test_delete_volume_not_found(self, mock_delete_request, mock_detach):
        mock_delete_request.return_value = powerstore.MockResponse(rc=404)
        self.driver.delete_volume(self.volume)

    @mock.patch("requests.request")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_mapped_hosts")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.delete_volume_or_snapshot")
    def test_delete_volume_detach_not_found(self,
                                            mock_delete,
                                            mock_mapped_hosts,
                                            mock_detach_request):
        mock_mapped_hosts.return_value = ["fake_host_id"]
        mock_detach_request.return_value = powerstore.MockResponse(
            content={},
            rc=404
        )
        self.driver.delete_volume(self.volume)

    @mock.patch("requests.request")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_mapped_hosts")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.delete_volume_or_snapshot")
    def test_delete_volume_detach_not_mapped(self,
                                             mock_delete,
                                             mock_mapped_hosts,
                                             mock_detach_request):
        mock_mapped_hosts.return_value = ["fake_host_id"]
        mock_detach_request.return_value = powerstore.MockResponse(
            content={
                "messages": [
                    {
                        "code": client.VOLUME_NOT_MAPPED_ERROR,
                    },
                ],
            },
            rc=422
        )
        self.driver.delete_volume(self.volume)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter._detach_volume_from_hosts")
    @mock.patch("requests.request")
    def test_delete_volume_bad_status(self, mock_delete, mock_detach):
        mock_delete.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.delete_volume,
                                  self.volume)
        self.assertIn("Failed to delete PowerStore volume", error.msg)

    @mock.patch("requests.request")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_mapped_hosts")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.delete_volume_or_snapshot")
    def test_delete_volume_detach_bad_status(self,
                                             mock_delete,
                                             mock_mapped_hosts,
                                             mock_detach_request):
        mock_mapped_hosts.return_value = ["fake_host_id"]
        mock_detach_request.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.delete_volume,
                                  self.volume)
        self.assertIn("Failed to detach PowerStore volume", error.msg)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.extend_volume")
    def test_extend_volume(self, mock_extend):
        self.driver.extend_volume(self.volume, 16)

    @mock.patch("requests.request")
    def test_extend_volume_bad_status(self, mock_extend_request):
        mock_extend_request.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.extend_volume,
                                  self.volume,
                                  16)
        self.assertIn("Failed to extend PowerStore volume", error.msg)
