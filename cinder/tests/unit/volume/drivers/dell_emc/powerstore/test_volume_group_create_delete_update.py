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
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerstore


class TestVolumeGroupCreateDeleteUpdate(powerstore.TestPowerStoreDriver):
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def setUp(self, mock_chap):
        super(TestVolumeGroupCreateDeleteUpdate, self).setUp()
        self.driver.check_for_setup_error()
        self.volume1 = fake_volume.fake_volume_obj(
            self.context,
            host="host@backend",
            provider_id="fake_id",
            size=8
        )
        self.volume2 = fake_volume.fake_volume_obj(
            self.context,
            host="host@backend",
            provider_id="fake_id",
            size=8
        )
        self.group = fake_group.fake_group_obj(
            self.context,
        )

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.create_vg")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_create_volume_group(self, mock_is_cg, mock_create):
        mock_create.return_value = "fake_id"
        mock_is_cg.return_value = True
        self.driver.create_group(self.context, self.group)

    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_create_volume_group_fallback_to_generic(self, mock_is_cg):
        mock_is_cg.return_value = False
        self.assertRaises(NotImplementedError,
                          self.driver.create_group,
                          self.context,
                          self.group)

    @mock.patch("requests.request")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_create_volume_group_bad_status(self,
                                            mock_is_cg,
                                            mock_create_request):
        mock_create_request.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.create_group,
                                  self.context,
                                  self.group)
        self.assertIn("Failed to create PowerStore volume group", error.msg)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.delete_volume_or_snapshot")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_id_by_name")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_delete_volume_group(self, mock_is_cg, mock_get_id, mock_delete):
        self.driver.delete_group(self.context, self.group, [])

    @mock.patch("requests.request")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_id_by_name")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_delete_volume_group_bad_status(self,
                                            mock_is_cg,
                                            mock_get_id,
                                            mock_delete):
        mock_delete.return_value = powerstore.MockResponse(rc=400)
        error = self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.delete_group,
            self.context,
            self.group,
            []
        )
        self.assertIn("Failed to delete PowerStore volume group", error.msg)

    @mock.patch("cinder.objects.volume.Volume.is_replicated")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_update_volume_group_add_replicated_volumes(self,
                                                        mock_is_cg,
                                                        mock_replicated):
        mock_replicated.return_value = True
        self.assertRaises(exception.InvalidVolume,
                          self.driver.update_group,
                          self.context,
                          self.group,
                          [self.volume1],
                          [])

    @mock.patch("requests.request")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_id_by_name")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_update_volume_group_add_volumes_bad_status(self,
                                                        mock_is_cg,
                                                        mock_get_vg_id,
                                                        mock_add_volumes):
        mock_add_volumes.return_value = powerstore.MockResponse(rc=400)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.update_group,
                          self.context,
                          self.group,
                          [self.volume1],
                          [])

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.remove_volumes_from_vg")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.add_volumes_to_vg")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_vg_id_by_name")
    @mock.patch("cinder.volume.volume_utils.is_group_a_cg_snapshot_type")
    def test_update_volume_group_add_remove_volumes(self,
                                                    mock_is_cg,
                                                    mock_get_vg_id,
                                                    mock_add_volumes,
                                                    mock_remove_volumes):
        self.driver.update_group(self.context,
                                 self.group,
                                 add_volumes=[self.volume1],
                                 remove_volumes=[self.volume2])
