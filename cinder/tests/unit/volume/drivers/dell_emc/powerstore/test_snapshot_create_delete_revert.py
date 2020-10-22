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
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerstore


class TestSnapshotCreateDelete(powerstore.TestPowerStoreDriver):
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_appliance_id_by_name")
    def setUp(self, mock_appliance, mock_chap):
        super(TestSnapshotCreateDelete, self).setUp()
        mock_appliance.return_value = "A1"
        self.driver.check_for_setup_error()
        self.volume = fake_volume.fake_volume_obj(
            {},
            host="host@backend#test-appliance",
            provider_id="fake_id",
            size=8
        )
        self.snapshot = fake_snapshot.fake_snapshot_obj(
            {},
            provider_id="fake_id_1",
            volume=self.volume
        )

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.create_snapshot")
    def test_create_snapshot(self, mock_create):
        mock_create.return_value = self.snapshot.provider_id
        self.driver.create_snapshot(self.snapshot)

    @mock.patch("requests.request")
    def test_create_snapshot_bad_status(self, mock_create_request):
        mock_create_request.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_snapshot,
            self.snapshot
        )
        self.assertIn("Failed to create snapshot", error.msg)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.delete_volume_or_snapshot")
    def test_delete_snapshot(self, mock_delete):
        self.driver.delete_snapshot(self.snapshot)

    @mock.patch("requests.request")
    def test_delete_snapshot_bad_status(self, mock_delete):
        mock_delete.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.delete_snapshot,
            self.snapshot
        )
        self.assertIn("Failed to delete PowerStore snapshot", error.msg)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.restore_from_snapshot")
    def test_revert_to_snapshot(self, mock_revert):
        self.driver.revert_to_snapshot({}, self.volume, self.snapshot)

    @mock.patch("requests.request")
    def test_revert_to_snapshot_bad_status(self, mock_revert):
        mock_revert.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.revert_to_snapshot,
            {},
            self.volume,
            self.snapshot
        )
        self.assertIn("Failed to restore PowerStore volume", error.msg)
