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
from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_group_snapshot
from cinder.tests.unit.volume.drivers.dell_emc import powerstore


class TestVolumeGroupSnapshotCreateDelete(powerstore.TestPowerStoreDriver):
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def setUp(self, mock_chap):
        super(TestVolumeGroupSnapshotCreateDelete, self).setUp()
        self.driver.check_for_setup_error()
        self.group = fake_group.fake_group_obj(
            self.context,
        )
        self.group_snapshot = fake_group_snapshot.fake_group_snapshot_obj(
            self.context
        )
        self.group_snapshot.group = self.group

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.create_vg_snapshot")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_id_by_name")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_create_volume_group_snapshot(self,
                                          mock_is_cg,
                                          mock_get_id,
                                          mock_create):
        self.driver.create_group_snapshot(self.context,
                                          self.group_snapshot,
                                          [])

    @mock.patch("requests.request")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_id_by_name")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_create_volume_group_snapshot_bad_status(self,
                                                     mock_is_cg,
                                                     mock_get_id,
                                                     mock_create):
        mock_create.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.create_group_snapshot,
                                  self.context,
                                  self.group_snapshot,
                                  [])
        self.assertIn("Failed to create snapshot", error.msg)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.delete_volume_or_snapshot")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_snapshot_id_by_name")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_id_by_name")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_delete_volume_group_snapshot(self,
                                          mock_is_cg,
                                          mock_get_group_id,
                                          mock_get_snapshot_id,
                                          mock_delete):
        self.driver.delete_group_snapshot(self.context,
                                          self.group_snapshot,
                                          [])

    @mock.patch("requests.request")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_snapshot_id_by_name")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_id_by_name")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_delete_volume_group_snapshot_bad_status(self,
                                                     mock_is_cg,
                                                     mock_get_group_id,
                                                     mock_get_snapshot_id,
                                                     mock_delete):
        mock_delete.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.delete_group_snapshot,
                                  self.context,
                                  self.group_snapshot,
                                  [])
        self.assertIn("Failed to delete PowerStore volume group snapshot",
                      error.msg)
