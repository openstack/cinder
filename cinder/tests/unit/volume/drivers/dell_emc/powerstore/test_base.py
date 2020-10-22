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
from cinder.tests.unit.volume.drivers.dell_emc import powerstore


class TestBase(powerstore.TestPowerStoreDriver):
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_appliance_id_by_name")
    def test_configuration(self, mock_appliance, mock_chap):
        mock_appliance.return_value = "A1"
        self.driver.check_for_setup_error()

    def test_configuration_rest_parameters_not_set(self):
        self.driver.adapter.client.rest_ip = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def test_configuration_appliances_not_set(self):
        self.driver.adapter.appliances = {}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    @mock.patch("requests.request")
    def test_configuration_appliance_not_found(self, mock_get_request):
        mock_get_request.return_value = powerstore.MockResponse()
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.check_for_setup_error)
        self.assertIn("not found", error.msg)

    @mock.patch("requests.request")
    def test_configuration_appliance_bad_status(self, mock_get_request):
        mock_get_request.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.check_for_setup_error)
        self.assertIn("Failed to query PowerStore appliances.", error.msg)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_appliance_id_by_name")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_appliance_metrics")
    def test_update_volume_stats(self,
                                 mock_metrics,
                                 mock_appliance,
                                 mock_chap):
        mock_appliance.return_value = "A1"
        mock_metrics.return_value = {
            "physical_total": 2147483648,
            "physical_used": 1073741824,
        }
        self.driver.check_for_setup_error()
        self.driver._update_volume_stats()

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_appliance_id_by_name")
    @mock.patch("requests.request")
    def test_update_volume_stats_bad_status(self,
                                            mock_metrics,
                                            mock_appliance,
                                            mock_chap):
        mock_appliance.return_value = "A1"
        mock_metrics.return_value = powerstore.MockResponse(rc=400)
        self.driver.check_for_setup_error()
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver._update_volume_stats)
        self.assertIn("Failed to query metrics", error.msg)
