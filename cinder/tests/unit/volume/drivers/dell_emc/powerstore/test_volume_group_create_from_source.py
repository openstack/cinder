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

from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_group_snapshot
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerstore


class TestVolumeGroupCreateFromSource(powerstore.TestPowerStoreDriver):
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def setUp(self, mock_chap):
        super(TestVolumeGroupCreateFromSource, self).setUp()
        self.driver.check_for_setup_error()
        self.volume = fake_volume.fake_volume_obj(
            self.context,
            host="host@backend",
            provider_id="fake_id",
            size=8
        )
        self.source_volume = fake_volume.fake_volume_obj(
            self.context,
            host="host@backend",
            provider_id="fake_id",
            size=8
        )
        self.source_volume_snap = fake_snapshot.fake_snapshot_obj(
            self.context,
            volume=self.source_volume,
            volume_size=8
        )
        self.group = fake_group.fake_group_obj(
            self.context,
        )
        self.source_group = fake_group.fake_group_obj(
            self.context,
        )
        self.source_group_snap = fake_group_snapshot.fake_group_snapshot_obj(
            self.context
        )
        self.source_group_snap.group = self.source_group

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.rename_volume")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_id_by_name")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.clone_vg_or_vg_snapshot")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_id_by_name")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_create_volume_group_clone(self,
                                       mock_is_cg,
                                       mock_get_group_id,
                                       mock_clone,
                                       mock_get_volume_id,
                                       mock_rename):
        mock_get_volume_id.return_value = "fake_id"
        group_updates, volume_updates = self.driver.create_group_from_src(
            self.context,
            self.group,
            volumes=[self.volume],
            source_group=self.source_group,
            source_vols=[self.source_volume]
        )
        self.assertEqual(1, len(volume_updates))
        self.assertEqual("fake_id", volume_updates[0]["provider_id"])

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.rename_volume")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_id_by_name")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.clone_vg_or_vg_snapshot")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_snapshot_id_by_name")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_id_by_name")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_create_volume_group_from_snapshot(self,
                                               mock_is_cg,
                                               mock_get_group_id,
                                               mock_get_snapshot_id,
                                               mock_clone,
                                               mock_get_volume_id,
                                               mock_rename):
        mock_get_volume_id.return_value = "fake_id"
        group_updates, volume_updates = self.driver.create_group_from_src(
            self.context,
            self.group,
            volumes=[self.volume],
            snapshots=[self.source_volume_snap],
            group_snapshot=self.source_group_snap
        )
        self.assertEqual(1, len(volume_updates))
        self.assertEqual("fake_id", volume_updates[0]["provider_id"])
