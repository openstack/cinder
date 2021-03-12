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
    def test_configuration(self, mock_chap):
        self.driver.check_for_setup_error()

    def test_configuration_rest_parameters_not_set(self):
        self.driver.adapter.client.rest_ip = None
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_metrics")
    def test_update_volume_stats(self,
                                 mock_metrics,
                                 mock_chap):
        mock_metrics.return_value = {
            "physical_total": 2147483648,
            "physical_used": 1073741824,
        }
        self.driver.check_for_setup_error()
        self.driver._update_volume_stats()

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    @mock.patch("requests.request")
    def test_update_volume_stats_bad_status(self,
                                            mock_metrics,
                                            mock_chap):
        mock_metrics.return_value = powerstore.MockResponse(rc=400)
        self.driver.check_for_setup_error()
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver._update_volume_stats)
        self.assertIn("Failed to query PowerStore metrics", error.msg)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def test_configuration_with_replication(self, mock_chap):
        replication_device = [
            {
                "backend_id": "repl_1",
                "san_ip": "127.0.0.2",
                "san_login": "test_1",
                "san_password": "test_2"
            }
        ]
        self._override_shared_conf("replication_device",
                                   override=replication_device)
        self.driver.do_setup({})
        self.driver.check_for_setup_error()
        self.assertEqual(2, len(self.driver.adapters))

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def test_configuration_with_replication_2_rep_devices(self, mock_chap):
        device = {
            "backend_id": "repl_1",
            "san_ip": "127.0.0.2",
            "san_login": "test_1",
            "san_password": "test_2"
        }
        replication_device = [device] * 2
        self._override_shared_conf("replication_device",
                                   override=replication_device)
        self.driver.do_setup({})
        error = self.assertRaises(exception.InvalidInput,
                                  self.driver.check_for_setup_error)
        self.assertIn("PowerStore driver does not support more than one "
                      "replication device.", error.msg)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def test_configuration_with_replication_failed_over(self, mock_chap):
        replication_device = [
            {
                "backend_id": "repl_1",
                "san_ip": "127.0.0.2",
                "san_login": "test_1",
                "san_password": "test_2"
            }
        ]
        self._override_shared_conf("replication_device",
                                   override=replication_device)
        self.driver.do_setup({})
        self.driver.check_for_setup_error()
        self.driver.active_backend_id = "repl_1"
        self.assertFalse(self.driver.replication_enabled)
