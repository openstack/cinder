# Copyright (c) 2026 Dell Inc. or its subsidiaries.
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


class TestMetro(powerstore.TestPowerStoreDriver):
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_array_version")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_chap_config")
    def setUp(self, mock_chap, mock_version):
        super(TestMetro, self).setUp()
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
        self._override_shared_conf("powerstore_host_connectivity",
                                   override="Metro_Optimize_Local")
        self._override_shared_conf("powerstore_nvme", override=False)
        mock_version.return_value = "3.0.0.0"
        self.driver.do_setup({})
        self.driver.check_for_setup_error()

        # mockup a metro volume
        self.metro_volume_type = fake_volume.fake_volume_type_obj(
            self.context,
            extra_specs={'replication_enabled': '<is> True',
                         'powerstore:metro': '<is> True'}
        )
        self.metro_volume = fake_volume.fake_volume_obj(
            self.context,
            host="host@backend",
            provider_id="fake_provider_id_1",
            size=8,
            replication_status="enabled",
            volume_type_id = self.metro_volume_type.id,
        )
        self.metro_volume.volume_type = self.metro_volume_type

        # mockup a non-metro volume
        self.volume_type = fake_volume.fake_volume_type_obj(
            self.context
        )
        self.volume = fake_volume.fake_volume_obj(
            self.context,
            host="host@backend",
            provider_id="fake_provider_id_2",
            size=8,
            replication_status="disabled",
            volume_type_id = self.volume_type.id,
        )
        self.volume.volume_type = self.volume_type

        self.connector = {
            "host": self.metro_volume.host,
            "wwnns": ['200000620b3eedd6', '200000620b3eedd5'],
            "wwpns": ['100000620b3eedd6', '100000620b3eedd5'],
            "initiator": "iqn.2016-04.com.open-iscsi:35a92c7fdb47",
        }

        self.snapshot = fake_snapshot.fake_snapshot_obj(
            self.context,
            volume=self.metro_volume,
            volume_size=8
        )

        self.host = {
            "name": "fake_host",
            "id": "fake_id",
            "host_connectivity": "Metro_Optimize_Both"
        }

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.configure_metro")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.create_volume")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_cluster_name")
    def test_create_volume_is_metro_volume(self,
                                           mock_get_cluster_name,
                                           mock_create_volume,
                                           mock_configure_metro):
        self.assertTrue(self.metro_volume.is_replicated())
        mock_get_cluster_name.return_value = "fake_cluster"
        mock_create_volume.return_value = "fake_provider_id_1"
        mock_configure_metro.return_value = "fake_metro_session_id"
        expected_updates = {
            "provider_id": "fake_provider_id_1",
            "replication_status": 'enabled',
        }
        updates = self.driver.create_volume(self.metro_volume)
        mock_create_volume.assert_called_once_with(
            self.metro_volume.name,
            self.metro_volume.size * (1024 ** 3),
            None, None)
        self.assertEqual(updates, expected_updates)
        mock_configure_metro.assert_called_once_with(
            "fake_provider_id_1", "fake_cluster"
        )

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter.create_volume")
    def test_create_volume_not_metro_volume(self,
                                            mock_create_volume):
        self.assertFalse(self.volume.is_replicated())
        self.driver.create_volume(self.volume)
        mock_create_volume.assert_called_once_with(
            self.volume, None)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter.delete_volume")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.wait_for_end_metro")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.end_metro")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_replication_session_id")
    def test_delete_volume_success(self,
                                   mock_get_session_id,
                                   mock_end_metro,
                                   mock_wait_for_end_metro,
                                   mock_adapter_delete_volume):
        mock_get_session_id.return_value = "fake_session_id"
        self.driver.delete_volume(self.metro_volume)
        mock_get_session_id.assert_called_once_with(
            self.metro_volume.provider_id
        )
        mock_end_metro.assert_called_once_with(
            self.metro_volume.provider_id)
        mock_wait_for_end_metro.assert_called_once_with("fake_session_id")
        mock_adapter_delete_volume.assert_called_once_with(
            self.metro_volume
        )

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter.delete_volume")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.wait_for_end_metro")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.end_metro")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_replication_session_id")
    def test_delete_volume_session_not_found(self,
                                             mock_get_session_id,
                                             mock_end_metro,
                                             mock_wait_for_end_metro,
                                             mock_adapter_delete_volume):
        mock_get_session_id.side_effect = exception.VolumeBackendAPIException(
            data="Failed to query PowerStore Replication sessions."
        )
        self.driver.delete_volume(self.metro_volume)
        mock_end_metro.assert_not_called()
        mock_wait_for_end_metro.assert_not_called()
        mock_adapter_delete_volume.assert_called_once_with(
            self.metro_volume
        )

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter.initialize_connection")
    def test_initialize_connection_metro_volume(
            self, mock_adapetr_initialize_connection):
        self.driver.initialize_connection(self.metro_volume, self.connector)
        mock_adapetr_initialize_connection.assert_called_with(
            self.metro_volume, self.connector
        )
        self.assertEqual(mock_adapetr_initialize_connection.call_count, 2)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter.terminate_connection")
    def test_terminate_connection_metro_volume(
            self, mock_adapetr_terminate_connection):
        self.driver.terminate_connection(self.metro_volume, self.connector)
        mock_adapetr_terminate_connection.assert_called_with(
            self.metro_volume, self.connector
        )
        self.assertEqual(mock_adapetr_terminate_connection.call_count, 2)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_replication_session_state")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_replication_session_id")
    def test_extend_volume_metro_not_paused(self,
                                            mock_get_session_id,
                                            mock_get_session_state):
        mock_get_session_id.return_value = "fake_session_id"
        mock_get_session_state.return_value = "not_paused"
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.extend_volume,
                          self.metro_volume,
                          17)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.extend_volume")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_replication_session_state")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_replication_session_id")
    def test_extend_volume_metro_paused(self,
                                        mock_get_session_id,
                                        mock_get_session_state,
                                        mock_extend_volume):
        mock_get_session_id.return_value = "fake_session_id"
        mock_get_session_state.return_value = "Paused"
        self.driver.extend_volume(self.metro_volume, 17)
        mock_extend_volume.assert_called_once_with(
            self.metro_volume.provider_id, 17 * (1024**3)
        )

    def test_create_volume_from_source_not_supported(self):
        self.assertRaises(exception.NotSupportedOperation,
                          self.driver.create_volume_from_snapshot,
                          self.metro_volume,
                          "fake_source")

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_replication_session_state")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_replication_session_id")
    def test_revert_to_snapshot_not_paused(self,
                                           mock_get_session_id,
                                           mock_get_session_state):
        mock_get_session_id.return_value = "fake_session_id"
        mock_get_session_state.return_value = "not_paused"
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.revert_to_snapshot,
                          self.context,
                          self.metro_volume,
                          self.snapshot)

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.restore_from_snapshot")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_snapshot_id_by_name")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_replication_session_state")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.get_volume_replication_session_id")
    def test_revert_to_snapshot_paused(self,
                                       mock_get_session_id,
                                       mock_get_session_state,
                                       mock_get_snapshot_id_by_name,
                                       mock_restore_from_snapshot):
        mock_get_session_id.return_value = "fake_session_id"
        mock_get_session_state.return_value = "Paused"
        mock_get_snapshot_id_by_name.return_value = "fake_snapshot_id"
        self.driver.revert_to_snapshot(self.context,
                                       self.metro_volume,
                                       self.snapshot)
        mock_restore_from_snapshot.assert_called_once_with(
            self.metro_volume.provider_id, "fake_snapshot_id"
        )

    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "FibreChannelAdapter._get_connection_properties")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter._attach_volume_to_host")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.client."
                "PowerStoreClient.modify_host_connectivity")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter._modify_host_initiators")
    @mock.patch("cinder.volume.drivers.dell_emc.powerstore.adapter."
                "CommonAdapter._filter_hosts_by_initiators")
    def test_initialize_connection_modify_host_connectivity(
            self,
            mock_adapter_filter,
            mock_adapter_modify_host_initiators,
            mock_modify_host_connectivity,
            mock_attach_volume_to_host,
            mock_get_connection_properties):
        mock_adapter_filter.return_value = self.host
        mock_get_connection_properties.return_value = "fake_conn_properties"
        self.driver.initialize_connection(self.metro_volume, self.connector)
        self.assertEqual(mock_adapter_filter.call_count, 2)
        mock_adapter_filter.assert_called_with(
            ['10:00:00:62:0b:3e:ed:d6', '10:00:00:62:0b:3e:ed:d5']
        )
        mock_modify_host_connectivity.assert_has_calls(
            [mock.call('fake_id', 'Metro_Optimize_Remote'),
             mock.call('fake_id', 'Metro_Optimize_Local')]
        )
