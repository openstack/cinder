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


class TestVolumeCreateFromSource(powerstore.TestPowerStoreDriver):
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_appliance_id_by_name")
    def setUp(self, mock_appliance, mock_chap):
        super(TestVolumeCreateFromSource, self).setUp()
        mock_appliance.return_value = "A1"
        self.driver.check_for_setup_error()
        self.volume = fake_volume.fake_volume_obj(
            {},
            host="host@backend#test-appliance",
            provider_id="fake_id",
            size=8
        )
        self.source_volume = fake_volume.fake_volume_obj(
            {},
            host="host@backend#test-appliance",
            provider_id="fake_id_1",
            size=8
        )
        self.source_snapshot = fake_snapshot.fake_snapshot_obj(
            {},
            provider_id="fake_id_2",
            volume_size=8
        )

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.clone_volume_or_snapshot")
    def test_create_cloned_volume(self, mock_create_cloned):
        mock_create_cloned.return_value = self.volume.provider_id
        self.driver.create_cloned_volume(self.volume, self.source_volume)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.extend_volume")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.clone_volume_or_snapshot")
    def test_create_cloned_volume_extended(self,
                                           mock_create_cloned,
                                           mock_extend):
        mock_create_cloned.return_value = self.volume.provider_id
        self.volume.size = 16
        self.driver.create_cloned_volume(self.volume, self.source_volume)
        mock_extend.assert_called_once()

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.clone_volume_or_snapshot")
    def test_create_volume_from_snapshot(self, mock_create_from_snap):
        mock_create_from_snap.return_value = self.volume.provider_id
        self.driver.create_volume_from_snapshot(self.volume,
                                                self.source_snapshot)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.extend_volume")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.clone_volume_or_snapshot")
    def test_create_volume_from_snapshot_extended(self,
                                                  mock_create_from_snap,
                                                  mock_extend):
        mock_create_from_snap.return_value = self.volume.provider_id
        self.volume.size = 16
        self.driver.create_volume_from_snapshot(self.volume,
                                                self.source_snapshot)
        mock_extend.assert_called_once()

    @mock.patch("requests.request")
    def test_create_volume_from_source_bad_status(self, mock_create_request):
        mock_create_request.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.adapter._create_volume_from_source,
            self.volume,
            self.source_volume
        )
        self.assertIn("Failed to create clone", error.msg)

    @mock.patch("requests.request")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.clone_volume_or_snapshot")
    def test_create_volume_from_source_extende_bad_status(
            self,
            mock_create_from_source,
            mock_extend_request
    ):
        mock_extend_request.return_value = powerstore.MockResponse(rc=400)
        self.volume.size = 16
        error = self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.adapter._create_volume_from_source,
            self.volume,
            self.source_volume
        )
        self.assertIn("Failed to extend PowerStore volume", error.msg)
