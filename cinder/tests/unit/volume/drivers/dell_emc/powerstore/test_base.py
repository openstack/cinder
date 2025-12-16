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
import uuid

from cinder import exception
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerstore
from cinder.volume.drivers.dell_emc.powerstore import utils

PS_CLIENT = (
    "cinder.volume.drivers.dell_emc.powerstore.client."
    "PowerStoreClient"
)
PS_ADAPTER = (
    "cinder.volume.drivers.dell_emc.powerstore.adapter."
    "CommonAdapter"
)


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
                "PowerStoreClient.get_array_version")
    def test_configuration_nvme_not_supported(self, mock_version):
        mock_version.return_value = "2.0.0.0"
        self.nvme_driver.do_setup({})
        self.assertRaises(exception.InvalidInput,
                          self.nvme_driver.check_for_setup_error)

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
                "PowerStoreClient.get_array_version")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def test_configuration_with_replication(self,
                                            mock_chap,
                                            mock_version):
        replication_device = [
            {
                "backend_id": "repl_1",
                "san_ip": "127.0.0.2",
                "san_login": "test_1",
                "san_password": "test_2"
            }
        ]
        mock_version.return_value = "3.0.0.0"
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
                "PowerStoreClient.get_array_version")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def test_configuration_with_replication_failed_over(self,
                                                        mock_chap,
                                                        mock_version):
        replication_device = [
            {
                "backend_id": "repl_1",
                "san_ip": "127.0.0.2",
                "san_login": "test_1",
                "san_password": "test_2"
            }
        ]
        mock_version.return_value = "3.0.0.0"
        self._override_shared_conf("replication_device",
                                   override=replication_device)
        self.driver.do_setup({})
        self.driver.check_for_setup_error()
        self.driver.active_backend_id = "repl_1"
        self.assertFalse(self.driver.replication_enabled)


class TestManageExisting(powerstore.TestPowerStoreDriver):
    @mock.patch(PS_CLIENT + ".get_volume_details_by_id")
    @mock.patch(PS_CLIENT + ".volume_is_mapped", return_value=False)
    def test_manage_existing_iscsi_success(self, mock_mapped, mock_get):
        self.driver.adapter.storage_protocol = utils.PROTOCOL_ISCSI
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(self.context, name="cinder-vol",
                                          id=vid)
        mock_get.return_value = {
            "id": "ps-id-1",
            "name": "ps-vol-1",
            "size": 1024**3,
            "state": "Ready",
            "type": "Primary",
            "is_replication_destination": False,
            "migration_session_id": None,
            "metro_replication_session_id": None,
        }
        res = self.driver.manage_existing(vol, {"source-id": "ps-id-1"})
        self.assertEqual({"provider_id": "ps-id-1"}, res)

    @mock.patch(PS_CLIENT + ".get_volume_details_by_id")
    @mock.patch(PS_CLIENT + ".volume_is_mapped", return_value=False)
    def test_manage_existing_fc_success(self, mock_mapped, mock_get):
        self.driver.adapter.storage_protocol = utils.PROTOCOL_FC
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(self.context, name="cinder-vol",
                                          id=vid)
        mock_get.return_value = {
            "id": "ps-id-fc",
            "name": "ps-vol-fc",
            "size": 1024**3,
            "state": "Healthy",
            "type": "Clone",
            "is_replication_destination": False,
            "migration_session_id": None,
            "metro_replication_session_id": None,
        }
        res = self.driver.manage_existing(vol, {"source-id": "ps-id-fc"})
        self.assertEqual({"provider_id": "ps-id-fc"}, res)

    @mock.patch(PS_CLIENT + ".get_volume_details_by_id")
    @mock.patch(PS_CLIENT + ".volume_is_mapped", return_value=False)
    def test_manage_existing_nvme_success(self, mock_mapped, mock_get):
        self.driver.adapter.storage_protocol = utils.PROTOCOL_NVME
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        mock_get.return_value = {
            "id": "ps-id-nvme",
            "name": "ps-vol-nvme",
            "size": 2 * 1024 ** 3,
            "state": "Available",
            "type": "Primary",
            "is_replication_destination": False,
            "migration_session_id": None,
            "metro_replication_session_id": None,
        }
        res = self.driver.manage_existing(vol, {"source-id": "ps-id-nvme"})
        self.assertEqual({"provider_id": "ps-id-nvme"}, res)

    @mock.patch(PS_CLIENT + ".get_volume_details_by_name")
    @mock.patch(PS_CLIENT + ".volume_is_mapped", return_value=False)
    def test_manage_existing_by_name_success(self, mock_mapped, mock_get):
        self.driver.adapter.storage_protocol = utils.PROTOCOL_ISCSI
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        mock_get.return_value = {
            "id": "ps-id-2",
            "name": "ps-vol-2",
            "size": 2 * 1024 ** 3,
            "state": "Healthy",
            "type": "Clone",
            "is_replication_destination": False,
            "migration_session_id": None,
            "metro_replication_session_id": None,
        }
        res = self.driver.manage_existing(
            vol,
            {"source-name": "ps-vol-2"},
        )
        self.assertEqual({"provider_id": "ps-id-2"}, res)

    def test_manage_existing_invalid_ref(self):
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing,
            vol,
            {},
        )

    def test_manage_existing_both_source_id_and_name(self):
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing,
            vol,
            {"source-id": "ps-id-1", "source-name": "ps-name-1"},
        )

    @mock.patch(PS_CLIENT + ".get_volume_details_by_id")
    def test_manage_existing_migration_session_blocked(self, mock_get):
        self.driver.adapter.storage_protocol = utils.PROTOCOL_ISCSI
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        mock_get.return_value = {
            "id": "ps-id-4",
            "name": "ps-vol-4",
            "size": 1024 ** 3,
            "state": "Ready",
            "type": "Primary",
            "is_replication_destination": False,
            "migration_session_id": "sess",
            "metro_replication_session_id": None,
        }
        self.assertRaises(
            exception.InvalidVolume,
            self.driver.manage_existing,
            vol,
            {"source-id": "ps-id-4"},
        )

    @mock.patch(PS_CLIENT + ".get_volume_details_by_id")
    def test_manage_existing_metro_session_blocked(self, mock_get):
        self.driver.adapter.storage_protocol = utils.PROTOCOL_ISCSI
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        mock_get.return_value = {
            "id": "ps-id-5",
            "name": "ps-vol-5",
            "size": 1024 ** 3,
            "state": "Ready",
            "type": "Primary",
            "is_replication_destination": False,
            "migration_session_id": None,
            "metro_replication_session_id": "metro",
        }
        self.assertRaises(
            exception.InvalidVolume,
            self.driver.manage_existing,
            vol,
            {"source-id": "ps-id-5"},
        )

    @mock.patch(PS_CLIENT + ".get_volume_details_by_id")
    def test_manage_existing_unsupported_type(self, mock_get):
        self.driver.adapter.storage_protocol = utils.PROTOCOL_ISCSI
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        mock_get.return_value = {
            "id": "ps-id-6",
            "name": "ps-vol-6",
            "size": 1024 ** 3,
            "state": "Ready",
            "type": "Snapshot",
            "is_replication_destination": False,
            "migration_session_id": None,
            "metro_replication_session_id": None,
        }
        self.assertRaises(
            exception.InvalidVolume,
            self.driver.manage_existing,
            vol,
            {"source-id": "ps-id-6"},
        )

    @mock.patch(PS_CLIENT + ".get_volume_details_by_id")
    def test_manage_existing_unsupported_state(self, mock_get):
        self.driver.adapter.storage_protocol = utils.PROTOCOL_ISCSI
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        mock_get.return_value = {
            "id": "ps-id-7",
            "name": "ps-vol-7",
            "size": 1024 ** 3,
            "state": "Busy",
            "type": "Primary",
            "is_replication_destination": False,
            "migration_session_id": None,
            "metro_replication_session_id": None,
        }
        self.assertRaises(
            exception.InvalidVolume,
            self.driver.manage_existing,
            vol,
            {"source-id": "ps-id-7"},
        )

    @mock.patch(PS_CLIENT + ".get_volume_details_by_id")
    def test_manage_existing_replication_destination_blocked(self, mock_get):
        self.driver.adapter.storage_protocol = utils.PROTOCOL_ISCSI
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        mock_get.return_value = {
            "id": "ps-id-8",
            "name": "ps-vol-8",
            "size": 1024 ** 3,
            "state": "Ready",
            "type": "Primary",
            "is_replication_destination": True,
            "migration_session_id": None,
            "metro_replication_session_id": None,
        }
        self.assertRaises(
            exception.InvalidVolume,
            self.driver.manage_existing,
            vol,
            {"source-id": "ps-id-8"},
        )

    @mock.patch(PS_CLIENT + ".volume_is_mapped", return_value=True)
    @mock.patch(PS_CLIENT + ".get_volume_details_by_id")
    def test_manage_existing_mapped_blocked(self, mock_get, mock_mapped):
        self.driver.adapter.storage_protocol = utils.PROTOCOL_ISCSI
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        mock_get.return_value = {
            "id": "ps-id-9",
            "name": "ps-vol-9",
            "size": 1024 ** 3,
            "state": "Ready",
            "type": "Primary",
            "is_replication_destination": False,
            "migration_session_id": None,
            "metro_replication_session_id": None,
        }
        self.assertRaises(
            exception.InvalidVolume,
            self.driver.manage_existing,
            vol,
            {"source-id": "ps-id-9"},
        )

    @mock.patch(PS_CLIENT + ".get_volume_details_by_id")
    def test_manage_existing_get_size_by_id_rounding(self, mock_get):
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        mock_get.return_value = {
            "id": "ps-id-12",
            "size": 1024 ** 3,
        }
        self.assertEqual(
            1,
            self.driver.manage_existing_get_size(
                vol,
                {"source-id": "ps-id-12"},
            ),
        )
        mock_get.return_value = {
            "id": "ps-id-12",
            "size": (1024 ** 3) + 1,
        }
        self.assertEqual(
            2,
            self.driver.manage_existing_get_size(
                vol,
                {"source-id": "ps-id-12"},
            ),
        )
        mock_get.return_value = {
            "id": "ps-id-12",
            "size": 0,
        }
        self.assertEqual(
            0,
            self.driver.manage_existing_get_size(
                vol,
                {"source-id": "ps-id-12"},
            ),
        )

    @mock.patch(PS_CLIENT + ".get_volume_details_by_name")
    def test_manage_existing_get_size_by_name(self, mock_get):
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        mock_get.return_value = {
            "id": "ps-id-13",
            "size": 3 * 1024 ** 3,
        }
        self.assertEqual(
            3,
            self.driver.manage_existing_get_size(
                vol,
                {"source-name": "ps-vol-13"},
            ),
        )

    @mock.patch(PS_CLIENT + ".get_volume_details_by_id")
    def test_manage_existing_get_size_missing(self, mock_get):
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        mock_get.return_value = {
            "id": "ps-id-14",
            "size": None,
        }
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.manage_existing_get_size,
            vol,
            {"source-id": "ps-id-14"},
        )

    def test_manage_existing_get_size_invalid_ref(self):
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size,
            vol,
            {},
        )

    def test_manage_existing_get_size_both_source_id_and_name(self):
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size,
            vol,
            {"source-id": "ps-id-1", "source-name": "ps-name-1"},
        )

    def test_unmanage_no_array_calls(self):
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        with mock.patch.object(
            self.driver.adapter.client,
            "delete_volume_or_snapshot",
        ) as del_mock, mock.patch.object(
            self.driver.adapter.client,
            "detach_volume_from_host",
        ) as det_mock:
            res = self.driver.unmanage(vol)
            self.assertEqual({}, res)
            del_mock.assert_not_called()
            det_mock.assert_not_called()

    def test_driver_passthroughs(self):
        vid = str(uuid.uuid4())
        vol = fake_volume.fake_volume_obj(
            self.context,
            name="cinder-vol",
            id=vid,
        )
        with mock.patch.object(
            self.driver.adapter,
            "manage_existing",
            return_value={"provider_id": "P"},
        ) as m1, mock.patch.object(
            self.driver.adapter.client,
            "get_volume_details_by_id",
            return_value={
                "id": "P",
                "size": 7 * (1024 ** 3),
            },
        ) as g1:
            self.assertEqual(
                {"provider_id": "P"},
                self.driver.manage_existing(
                    vol,
                    {"source-id": "P"},
                ),
            )
            self.assertEqual(
                7,
                self.driver.manage_existing_get_size(
                    vol,
                    {"source-id": "P"},
                ),
            )
            self.assertEqual({}, self.driver.unmanage(vol))
            m1.assert_called_once()
            g1.assert_called_once()
