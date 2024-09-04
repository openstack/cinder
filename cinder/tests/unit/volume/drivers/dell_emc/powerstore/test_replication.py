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

from cinder import exception
from cinder.objects import fields
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerstore
from cinder.volume.drivers.dell_emc.powerstore import client


class TestReplication(powerstore.TestPowerStoreDriver):
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_array_version")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def setUp(self, mock_chap, mock_version):
        super(TestReplication, self).setUp()
        self.replication_backend_id = "repl_1"
        replication_device = [
            {
                "backend_id": self.replication_backend_id,
                "san_ip": "127.0.0.2",
                "san_login": "test_1",
                "san_password": "test_2"
            }
        ]
        self._override_shared_conf("replication_device",
                                   override=replication_device)
        mock_version.return_value = "3.0.0.0"
        self.driver.do_setup({})
        self.driver.check_for_setup_error()
        self.volume = fake_volume.fake_volume_obj(
            self.context,
            host="host@backend",
            provider_id="fake_id",
            size=8,
            replication_status="enabled"
        )

    def test_failover_host_no_volumes(self):
        self.driver.failover_host({}, [], self.replication_backend_id)
        self.assertEqual(self.replication_backend_id,
                         self.driver.active_backend_id)

    def test_failover_host_invalid_secondary_id(self):
        error = self.assertRaises(exception.InvalidReplicationTarget,
                                  self.driver.failover_host,
                                  {}, [], "invalid_id")
        self.assertIn("is not a valid choice", error.msg)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "NVMEoFAdapter.failover_host")
    def test_failover_valid_secondary_id(self, mock_adapter_failover):
        volumes = [self.volume]
        mock_adapter_failover.return_value = (volumes, None)

        result = self.driver.failover({}, volumes, self.replication_backend_id)

        self.assertEqual(result, (self.replication_backend_id, volumes, None))
        self.driver.adapter.failover_host.assert_called_once_with(
            volumes, None, False)

    def test_failover_invalid_secondary_id(self):
        volumes = [self.volume]
        secondary_id = "invalid_id"
        self.driver.active_backend_id = None

        self.assertRaises(exception.InvalidReplicationTarget,
                          self.driver.failover,
                          {}, volumes, secondary_id, None)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "NVMEoFAdapter.failover_host")
    def test_failover_is_failback(self, mock_adapter_failover):
        volumes = [self.volume]
        mock_adapter_failover.return_value = (volumes, None)
        secondary_id = "default"
        self.driver.active_backend_id = self.replication_backend_id

        result = self.driver.failover({}, volumes, secondary_id, None)

        self.assertEqual(result, (secondary_id, volumes, None))
        self.driver.adapter.failover_host.assert_called_once_with(
            volumes, None, True)

    def test_failover_completed_failback(self):
        self.driver.failover_completed({}, None)
        self.assertEqual(self.driver.active_backend_id, "default")

    def test_failover_completed_failover(self):
        self.driver.replication_devices = [{"backend_id":
                                            self.replication_backend_id}]
        self.driver.failover_completed({}, "failed over")
        self.assertEqual(self.driver.active_backend_id,
                         self.replication_backend_id)

    def test_failover_completed_invalid_target(self):
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.driver.failover_completed,
                          {}, "invalid_target")

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.wait_for_failover_completion")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.failover_volume_replication_session")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_replication_session_id")
    def test_failover_volume(self,
                             mock_rep_session,
                             mock_failover,
                             mock_wait_failover):
        updates = self.driver.adapter.failover_volume(self.volume,
                                                      is_failback=False)
        self.assertIsNone(updates)

    @mock.patch("requests.request")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.failover_volume_replication_session")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_replication_session_id")
    def test_failover_volume_already_failed_over(self,
                                                 mock_rep_session,
                                                 mock_failover,
                                                 mock_wait_failover):
        mock_wait_failover.return_value = powerstore.MockResponse(
            content={
                "response_body": {
                    "messages": [
                        {
                            "code": client.SESSION_ALREADY_FAILED_OVER_ERROR,
                        },
                    ],
                },
            },
            rc=200
        )
        updates = self.driver.adapter.failover_volume(self.volume,
                                                      is_failback=False)
        self.assertIsNone(updates)

    @mock.patch("requests.request")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.failover_volume_replication_session")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_replication_session_id")
    def test_failover_volume_failover_error(self,
                                            mock_rep_session,
                                            mock_failover,
                                            mock_wait_failover):
        mock_wait_failover.return_value = powerstore.MockResponse(
            content={
                "state": "FAILED",
                "response_body": None,
            },
            rc=200
        )
        updates = self.driver.adapter.failover_volume(self.volume,
                                                      is_failback=False)
        self.assertEqual(self.volume.id, updates["volume_id"])
        self.assertEqual(fields.ReplicationStatus.FAILOVER_ERROR,
                         updates["updates"]["replication_status"])
