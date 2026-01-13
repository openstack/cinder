# Copyright 2025 VAST Data Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import datetime
from unittest import mock
from unittest.mock import MagicMock
from unittest.mock import patch

import ddt
from oslo_utils import timeutils
from oslo_utils import units

from cinder import exception
from cinder import objects
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.vastdata import driver
from cinder.volume.drivers.vastdata import utils as vast_utils


CONN_UUID = "a8f5f167-1b3f-4d5c-9a0f-b6c57e3f8e2d"
CONN_HOST_NAME = "openstack"
HOST_NQN = (
    "nqn.2014-08.org.nvmexpress:uuid:"
    "3e7d1f8a-2b49-4c6f-ae3d-9f1c5b8e7d2a"
)
SUBSYSTEM_NQN = (
    "nqn.2024-08.com.vastdata:"
    "d8caad74-e2b3-5541-b5b3-080dda47873b:default:myblock"
)
NOW = timeutils.utcnow()


@ddt.ddt
class VASTVolumeDriverTestCase(test.TestCase):

    def _create_mocked_rest_api(self):
        """Create a mock REST API object with subresources and methods."""
        mock_rest_api = mock.MagicMock()

        # Create mock sub resources with their methods
        subresources = [
            "views",
            "view_policies",
            "capacity_metrics",
            "quotas",
            "vip_pools",
            "snapshots",
            "vtasks",
            "volumes",
            "blockhostmappings",
            "globalsnapstreams",
            "blockhosts",
        ]
        methods = [
            "list",
            "create",
            "update",
            "delete",
            "one",
            "ensure",
            "vips"
        ]

        for subresource in subresources:
            mock_subresource = MagicMock()
            setattr(mock_rest_api, subresource, mock_subresource)

            for method in methods:
                mock_method = MagicMock()
                setattr(mock_subresource, method, mock_method)

        return mock_rest_api

    def _create_mock_volume(self, **updates):
        return fake_volume.fake_volume_obj(
            self.fake_conf,
            **updates,
        )

    def _create_mock_attachmentlist(self, volume, count=1):
        if not count:
            return objects.VolumeAttachmentList(objects=[])
        attachment = {
            "id": "d3b07384-d9a7-4f46-b6a2-46a1b5e7f6c3",
            "volume_id": volume.id,
            "attach_status": "attached",
            "attached_host": CONN_HOST_NAME,
        }
        attach_objects = [
            objects.VolumeAttachment(**attachment) for _ in range(count)
        ]
        attachment = objects.VolumeAttachmentList(objects=attach_objects)
        return attachment

    def _create_mock_connector(self, **updates):
        connector = {
            "uuid": updates.get("uuid", CONN_UUID),
            "nqn": updates.get("nqn", HOST_NQN),
            "host": updates.get("host", CONN_HOST_NAME),
        }
        return connector

    def _create_mock_snapshot(self, **updates):
        return fake_snapshot.fake_snapshot_obj(self.fake_conf, **updates)

    @mock.patch(
        "cinder.volume.drivers.vastdata.rest.RestApi.do_setup",
    )
    def setUp(self, m_do_setup):
        super(VASTVolumeDriverTestCase, self).setUp()
        self.fake_conf = conf.Configuration(
            driver.VASTDATA_OPTS, conf.SHARED_CONF_GROUP
        )
        self.fake_conf.set_default("volume_backend_name", "vast")
        self.fake_conf.set_default("vast_subsystem", "subsystem")
        self.fake_conf.set_default("vast_vippool_name", "vippool")
        self.fake_conf.set_default("vast_volume_prefix", "openstack-vol-")
        self.fake_conf.set_default("vast_snapshot_prefix", "openstack-snap-")
        self.fake_conf.set_default("san_login", "username")
        self.fake_conf.set_default("san_api_port", "443")
        self.fake_conf.set_default("san_password", "password")
        self.fake_conf.set_default("san_ip", "host")
        self._driver = driver.VASTVolumeDriver(
            configuration=self.fake_conf, plugin_version="1.0"
        )
        self._driver.do_setup(self.fake_conf)
        self._rest = self._driver.rest
        m_do_setup.assert_called_once()

    def test_do_setup_ok(self):
        self.assertEqual(self._driver.backend_name, "vast")
        self.assertEqual(self._driver.vippool_name, "vippool")
        self.assertEqual(self._driver.subsystem, "subsystem")
        self.assertEqual(
            self._rest.session.base_url,
            "https://host:443/api/v4"
        )
        self.assertFalse(self._rest.session.ssl_verify)
        self.assertEqual(self._rest.session.username, "username")
        self.assertEqual(self._rest.session.password, "password")
        self.assertEqual(self._rest.session.token, "")

    @ddt.data("vast_subsystem", "vast_vippool_name")
    def test_do_setup_missing_required_fields(self, missing_field):
        self.fake_conf.set_default(missing_field, None)
        _driver = driver.VASTVolumeDriver(
            configuration=self.fake_conf, plugin_version="1.0"
        )
        self.assertRaises(exception.InvalidConfigurationValue,
                          _driver.do_setup, self.fake_conf)

    def test_get_driver_options(self):
        self.assertIsNotNone(self._driver.get_driver_options())

    def test_check_for_setup_error(self):
        self.assertIsNone(self._driver.check_for_setup_error())

    def test_create_volume(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        mock_rest.views.get_subsystem.return_value = vast_utils.Bunch(id=1)
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.create_volume(volume)
        mock_rest.volumes.ensure.assert_called_once_with(
            name=f"openstack-vol-{volume.id}", view_id=1, size=1073741824
        )

    def test_delete_volume_no_vast_volume(self):
        """Test volume not found on VAST"""
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        mock_rest.volumes.one.return_value = None
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.delete_volume(volume)
        mock_rest.volumes.delete_by_id.assert_not_called()
        (
            mock_rest.rest.globalsnapstreams.
            ensure_snapshot_stream_deleted
            .assert_not_called()
        )

    def test_delete_volume_cloned_from_volume(self):
        """Test delete volume

        also deletes GSS when it is cloned from another volume
        """
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume(
            source_volid="d3b07384-d9a7-4f46-b6a2-46a1b5e7f6c3",
        )
        mock_rest.volumes.one.return_value = vast_utils.Bunch(id=1)
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.delete_volume(volume)
        mock_rest.volumes.delete_by_id.assert_called_once_with(1)
        (
            mock_rest.globalsnapstreams
            .ensure_snapshot_stream_deleted
            .assert_called_once_with(volume_id=volume.id)
        )

    def test_delete_volume_cloned_from_snapshot(self):
        """Test delete volume

          also deletes GSS when it is cloned from snapshot
          """
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume(
            snapshot_id="d3b07384-d9a7-4f46-b6a2-46a1b5e7f6c3",
        )
        mock_rest.volumes.one.return_value = vast_utils.Bunch(id=1)
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.delete_volume(volume)
        mock_rest.volumes.delete_by_id.assert_called_once_with(1)
        (
            mock_rest.globalsnapstreams
            .ensure_snapshot_stream_deleted
            .assert_called_once_with(volume_id=volume.id)
        )

    def test_delete_volume(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        mock_rest.volumes.one.return_value = vast_utils.Bunch(id=1)
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.delete_volume(volume)
        mock_rest.volumes.delete_by_id.assert_called_once_with(1)
        (
            mock_rest.globalsnapstreams
            .ensure_snapshot_stream_deleted.assert_not_called()
        )

    def test_get_volume_stats(self):
        """Test retrieving volume stats with and without refresh."""
        mock_rest = self._create_mocked_rest_api()

        mock_metrics = vast_utils.Bunch(
            logical_space=500 * units.Gi,
            logical_space_in_use=200 * units.Gi
        )
        mock_rest.capacity_metrics.get.return_value = mock_metrics

        with patch.object(self._driver, "rest", mock_rest):
            stats = self._driver.get_volume_stats(refresh=True)

        expected_stats = {
            "volume_backend_name": self._driver.backend_name,
            "vendor_name": "VAST Data",
            "driver_version": self._driver.VERSION,
            "storage_protocol": "nvmeof",
            "pools": [{
                "pool_name": self._driver.backend_name,
                "total_capacity_gb": 500.0,
                "free_capacity_gb": 300.0,
                "reserved_percentage": (
                    self._driver.configuration.reserved_percentage
                ),
                "QoS_support": False,
                "multiattach": True,
                "thin_provisioning_support": False,
                "consistent_group_snapshot_enabled": False,
            }]
        }

        self.assertEqual(stats, expected_stats)
        self.assertEqual(self._driver._stats, expected_stats)
        mock_rest.capacity_metrics.get.assert_called_once()

    def test_get_volume_stats_no_refresh(self):
        """Test retrieving cached volume stats when refresh=False."""
        mock_rest = self._create_mocked_rest_api()
        # First call with refresh=True to populate the cache
        mock_metrics = vast_utils.Bunch(
            logical_space=500 * units.Gi,
            logical_space_in_use=200 * units.Gi
        )
        mock_rest.capacity_metrics.get.return_value = mock_metrics
        with patch.object(self._driver, "rest", mock_rest):
            # First call with refresh=True
            stats1 = self._driver.get_volume_stats(refresh=True)
            # Second call with refresh=False should return cached data
            stats2 = self._driver.get_volume_stats(refresh=False)

        # The stats should be the same
        self.assertEqual(stats1, stats2)
        mock_rest.capacity_metrics.get.assert_called_once()

    def test_ensure_export(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        mock_rest.volumes.one.return_value = vast_utils.Bunch(id=1)
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.ensure_export(self.fake_conf, volume)
        mock_rest.volumes.one.assert_called_once_with(name__endswith=volume.id)

    def test_ensure_export_not_found(self):
        """Test volume not found on VAST"""
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        mock_rest.volumes.one.return_value = None
        with patch.object(self._driver, "rest", mock_rest):
            self.assertRaises(
                exception.VolumeNotFound,
                self._driver.ensure_export,
                self.fake_conf,
                volume,
            )

    def test_remove_export(self):
        volume = self._create_mock_volume()
        self.assertIsNone(self._driver.remove_export(self.fake_conf, volume))

    def test_create_export(self):
        volume = self._create_mock_volume()
        self.assertIsNone(
            self._driver.create_export(
                self.fake_conf, volume, None
            )
        )

    def test_extend_volume(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        mock_rest.volumes.one.return_value = vast_utils.Bunch(id=1)
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.extend_volume(volume, 50)
        mock_rest.volumes.update.assert_called_once_with(1, size=53687091200)

    def test_initialize_connection(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        connector = self._create_mock_connector()
        mock_rest.volumes.one.return_value = vast_utils.Bunch(
            id=1,
            view_id=5,
            uuid="d3b07384-d9a7-4f46-b6a2-46a1b5e7f6c3",
            nguid="3e7d1f8a-2b49-4c6f-ae3d-9f1c5b8e7d2a",
        )
        mock_rest.views.get_subsystem_by_id.return_value = vast_utils.Bunch(
            id=5,
            nqn=SUBSYSTEM_NQN,
            tenant_id=1,
        )
        mock_rest.vip_pools.get_vips.return_value = [
            "1.1.1.1",
            "2.2.2.2",
            "3.3.3.3",
            "4.4.4.4",
        ]
        mock_rest.blockhosts.ensure.return_value = vast_utils.Bunch(
            id=4,
            nqn=HOST_NQN,
        )
        with patch.object(self._driver, "rest", mock_rest):
            connection_info = self._driver.initialize_connection(
                volume, connector
            )
        self.assertDictEqual(
            connection_info,
            {
                "driver_volume_type": "nvmeof",
                "data": {
                    "target_nqn": SUBSYSTEM_NQN,
                    "host_nqn": HOST_NQN,
                    "portals": [
                        ("3.3.3.3", 4420, "tcp"),
                        ("1.1.1.1", 4420, "tcp"),
                        ("2.2.2.2", 4420, "tcp"),
                        ("4.4.4.4", 4420, "tcp"),
                    ],
                    "volume_nguid": "3e7d1f8a-2b49-4c6f-ae3d-9f1c5b8e7d2a",
                    "volume_uuid": "d3b07384-d9a7-4f46-b6a2-46a1b5e7f6c3",
                },
            },
        )
        mock_rest.volumes.one.assert_called_once_with(name__endswith=volume.id)
        mock_rest.views.get_subsystem_by_id.assert_called_once_with(entry_id=5)
        mock_rest.vip_pools.get_vips.assert_called_once_with("vippool")
        mock_rest.blockhosts.ensure.assert_called_once_with(
            name=CONN_HOST_NAME,
            nqn=HOST_NQN,
            tenant_id=1,
        )
        mock_rest.blockhostmappings.ensure_map.assert_called_once_with(
            volume_id=1,
            host_id=4,
        )

    def test_initialize_connection_no_nqn(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        connector = self._create_mock_connector(nqn=None)
        mock_rest.volumes.one.return_value = vast_utils.Bunch(
            id=1,
            view_id=5,
            uuid="d3b07384-d9a7-4f46-b6a2-46a1b5e7f6c3",
            nguid="3e7d1f8a-2b49-4c6f-ae3d-9f1c5b8e7d2a",
        )
        mock_rest.views.get_subsystem_by_id.return_value = vast_utils.Bunch(
            id=5,
            nqn=SUBSYSTEM_NQN,
            tenant_id=1,
        )
        with patch.object(self._driver, "rest", mock_rest):
            self.assertRaises(
                exception.VolumeDriverException,
                self._driver.initialize_connection,
                volume,
                connector,
            )

    def test_initialize_connection_more_vips(self):
        """Test 16 random vips should be choosen from the list of 20 vips."""
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        connector = self._create_mock_connector()
        mock_rest.volumes.one.return_value = vast_utils.Bunch(
            id=1,
            view_id=5,
            uuid="d3b07384-d9a7-4f46-b6a2-46a1b5e7f6c3",
            nguid="3e7d1f8a-2b49-4c6f-ae3d-9f1c5b8e7d2a",
        )
        mock_rest.views.get_subsystem_by_id.return_value = vast_utils.Bunch(
            id=5,
            nqn=SUBSYSTEM_NQN,
            tenant_id=1,
        )
        mock_rest.vip_pools.get_vips.return_value = [
            "192.168.1.1",
            "192.168.1.2",
            "192.168.1.3",
            "192.168.1.4",
            "192.168.1.5",
            "192.168.1.6",
            "192.168.1.7",
            "192.168.1.8",
            "192.168.1.9",
            "192.168.1.10",
            "192.168.1.11",
            "192.168.1.12",
            "192.168.1.13",
            "192.168.1.14",
            "192.168.1.15",
            "192.168.1.16",
            "192.168.1.17",
            "192.168.1.18",
            "192.168.1.19",
            "192.168.1.20",
        ]
        mock_rest.blockhosts.ensure.return_value = vast_utils.Bunch(
            id=4,
            nqn=HOST_NQN,
        )
        with patch.object(self._driver, "rest", mock_rest):
            connection_info = self._driver.initialize_connection(
                volume, connector
            )
        self.assertDictEqual(
            connection_info,
            {
                "driver_volume_type": "nvmeof",
                "data": {
                    "target_nqn": SUBSYSTEM_NQN,
                    "host_nqn": HOST_NQN,
                    "portals": [
                        ("192.168.1.10", 4420, "tcp"),
                        ("192.168.1.4", 4420, "tcp"),
                        ("192.168.1.14", 4420, "tcp"),
                        ("192.168.1.17", 4420, "tcp"),
                        ("192.168.1.6", 4420, "tcp"),
                        ("192.168.1.8", 4420, "tcp"),
                        ("192.168.1.16", 4420, "tcp"),
                        ("192.168.1.9", 4420, "tcp"),
                        ("192.168.1.19", 4420, "tcp"),
                        ("192.168.1.5", 4420, "tcp"),
                        ("192.168.1.13", 4420, "tcp"),
                        ("192.168.1.1", 4420, "tcp"),
                        ("192.168.1.11", 4420, "tcp"),
                        ("192.168.1.18", 4420, "tcp"),
                        ("192.168.1.20", 4420, "tcp"),
                        ("192.168.1.3", 4420, "tcp"),
                    ],
                    "volume_nguid": "3e7d1f8a-2b49-4c6f-ae3d-9f1c5b8e7d2a",
                    "volume_uuid": "d3b07384-d9a7-4f46-b6a2-46a1b5e7f6c3",
                },
            },
        )
        assert len(connection_info["data"]["portals"]) == 16
        mock_rest.volumes.one.assert_called_once_with(name__endswith=volume.id)
        mock_rest.views.get_subsystem_by_id.assert_called_once_with(entry_id=5)
        mock_rest.vip_pools.get_vips.assert_called_once_with("vippool")
        mock_rest.blockhosts.ensure.assert_called_once_with(
            name=CONN_HOST_NAME,
            nqn=HOST_NQN,
            tenant_id=1,
        )
        mock_rest.blockhostmappings.ensure_map.assert_called_once_with(
            volume_id=1,
            host_id=4,
        )

    def test_terminate_connection(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        connector = self._create_mock_connector()
        mock_rest.volumes.one.return_value = vast_utils.Bunch(
            id=1,
        )
        volume.multiattach = False
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.terminate_connection(volume, connector)

        mock_rest.blockhostmappings.ensure_unmap.assert_called_once_with(
            volume__id=1,
            block_host__name=CONN_HOST_NAME,
        )

    def test_terminate_connection_no_volume(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        connector = self._create_mock_connector()
        mock_rest.volumes.one.return_value = None
        volume.multiattach = True
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.terminate_connection(volume, connector)
        mock_rest.blockhostmappings.ensure_unmap.assert_not_called()

    def test_terminate_connection_multiattach_one_instance(self):
        """Test volume should be unmapped when

        it is attached to one instance.
        """
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume(multiattach=True)
        connector = self._create_mock_connector()
        attachment = self._create_mock_attachmentlist(
            volume=volume,
        )
        volume.volume_attachment = attachment
        mock_rest.volumes.one.return_value = vast_utils.Bunch(
            id=1,
        )
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.terminate_connection(volume, connector)
        mock_rest.blockhostmappings.ensure_unmap.assert_called_once_with(
            volume__id=1,
            block_host__name=CONN_HOST_NAME,
        )

    def test_terminate_connection_multiattach_two_instances(self):
        """Test volume should not be unmapped when

        it is attached to two instances.
        """
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume(multiattach=True)
        connector = self._create_mock_connector()
        attachment = self._create_mock_attachmentlist(
            volume=volume,
            count=2,
        )
        volume.volume_attachment = attachment
        mock_rest.volumes.one.return_value = vast_utils.Bunch(
            id=1,
        )
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.terminate_connection(volume, connector)
        mock_rest.blockhostmappings.ensure_unmap.assert_not_called()

    def test_terminate_connection_no_attachment(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume(multiattach=True)
        connector = self._create_mock_connector()
        attachment = self._create_mock_attachmentlist(volume=volume, count=0)
        volume.volume_attachment = attachment
        mock_rest.volumes.one.return_value = vast_utils.Bunch(
            id=1,
        )
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.terminate_connection(volume, connector)
        mock_rest.blockhostmappings.ensure_unmap.assert_called_once_with(
            volume__id=1,
            block_host__name=CONN_HOST_NAME,
        )

    def test_create_volume_from_snapshot_volume_exists(self):
        """Test no calls to VMS. Volume exists

        and has the same size as snap.
        """
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        snapshot = self._create_mock_snapshot()
        mock_rest.volumes.one.return_value = vast_utils.Bunch(
            id=1,
        )
        mock_rest.snapshots.one.return_value = vast_utils.Bunch(
            id=2,
        )
        mock_rest.views.get_subsystem.return_value = vast_utils.Bunch(
            id=5,
        )
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.create_volume_from_snapshot(volume, snapshot)

        mock_rest.snapshots.clone_volume.assert_not_called()
        mock_rest.volumes.update.assert_not_called()

    def test_create_volume_from_snapshot_volume_exists_update_size(self):
        """Test no calls to VMS. Volume exists but need to update size."""
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume(size=8)
        snapshot = self._create_mock_snapshot()
        mock_rest.volumes.one.return_value = vast_utils.Bunch(
            id=1,
        )
        mock_rest.snapshots.one.return_value = vast_utils.Bunch(
            id=2,
        )
        mock_rest.snapshots.clone_volume.return_value = vast_utils.Bunch(
            id=10,
        )
        mock_rest.views.get_subsystem.return_value = vast_utils.Bunch(
            id=5,
        )
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.create_volume_from_snapshot(volume, snapshot)

        mock_rest.snapshots.clone_volume.assert_not_called()
        mock_rest.volumes.update.assert_called_once_with(1, size=8589934592)

    def test_create_volume_from_snapshot_not_found(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        snapshot = self._create_mock_snapshot()
        mock_rest.snapshots.one.return_value = None
        with patch.object(self._driver, "rest", mock_rest):
            self.assertRaises(
                exception.SnapshotNotFound,
                self._driver.create_volume_from_snapshot,
                volume,
                snapshot,
            )

    def test_create_volume_from_snapshot(self):
        """Test no calls to VMS. Volume exists but need to update size."""
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume(size=8)
        snapshot = self._create_mock_snapshot()
        mock_rest.volumes.one.return_value = None
        mock_rest.snapshots.one.return_value = vast_utils.Bunch(
            id=2,
        )
        mock_rest.snapshots.clone_volume.return_value = vast_utils.Bunch(
            id=10,
        )
        mock_rest.views.get_subsystem.return_value = vast_utils.Bunch(
            id=5,
        )
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.create_volume_from_snapshot(volume, snapshot)

        mock_rest.snapshots.clone_volume.assert_called_once_with(
            snapshot_id=2,
            target_subsystem_id=5,
            target_volume_path=f"openstack-vol-{volume.id}",
        )
        mock_rest.volumes.update.assert_called_once_with(10, size=8589934592)

    @patch("oslo_utils.timeutils.utcnow", MagicMock(return_value=NOW))
    def test_create_cloned_volume_the_same_size(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        source_volume = self._create_mock_volume(
            id="d3b07384-d9a7-4f46-b6a2-46a1b5e7f6c3"
        )

        def _return_volume(name__endswith):
            if name__endswith == volume.id:
                return vast_utils.Bunch(
                    id=1,
                    name=f"openstack-vol-{volume.id}",
                    view_id=10,
                )
            elif name__endswith == source_volume.id:
                return vast_utils.Bunch(
                    id=100,
                    name=f"openstack-vol-{source_volume.id}",
                    view_id=10,
                )
            raise ValueError("Invalid 'name__endswith'")

        mock_rest.volumes.one.side_effect = _return_volume
        mock_rest.snapshots.clone_volume.return_value = vast_utils.Bunch(
            id=10,
        )
        mock_rest.views.get_subsystem_by_id.return_value = vast_utils.Bunch(
            id=5,
            path="/foo/bar",
            tenant_id=20,
        )
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.create_cloned_volume(volume, source_volume)
        expiration_time = NOW + datetime.timedelta(minutes=5)
        mock_rest.snapshots.ensure.assert_called_once_with(
            name=f"openstack-snap-{source_volume.id}",
            path=f"/foo/bar/openstack-vol-{source_volume.id}",
            tenant_id=20,
            expiration_time=expiration_time.isoformat(),
        )
        mock_rest.snapshots.clone_volume.assert_not_called()
        mock_rest.volumes.update.assert_not_called()

    @patch("oslo_utils.timeutils.utcnow", MagicMock(return_value=NOW))
    def test_create_cloned_volume_the_diffent_size(self):
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume(size=20)
        source_volume = self._create_mock_volume(
            id="d3b07384-d9a7-4f46-b6a2-46a1b5e7f6c3"
        )

        def _return_volume(name__endswith):
            if name__endswith == source_volume.id:
                return vast_utils.Bunch(
                    id=1,
                    name=f"openstack-vol-{source_volume.id}",
                    view_id=10,
                )
            return None

        mock_rest.volumes.one.side_effect = _return_volume
        mock_rest.snapshots.ensure.return_value = vast_utils.Bunch(
            id=54,
        )
        mock_rest.snapshots.clone_volume.return_value = vast_utils.Bunch(
            id=10,
        )
        mock_rest.views.get_subsystem_by_id.return_value = vast_utils.Bunch(
            id=20,
            path="/foo/bar",
            tenant_id=20,
        )
        mock_rest.views.get_subsystem.return_value = vast_utils.Bunch(
            id=5,
            path="/foo/bar",
            tenant_id=20,
        )
        with patch.object(self._driver, "rest", mock_rest):
            self._driver.create_cloned_volume(volume, source_volume)
        expiration_time = NOW + datetime.timedelta(minutes=5)
        mock_rest.snapshots.ensure.assert_called_once_with(
            name=f"openstack-snap-{source_volume.id}",
            path=f"/foo/bar/openstack-vol-{source_volume.id}",
            tenant_id=20,
            expiration_time=expiration_time.isoformat(),
        )
        mock_rest.snapshots.clone_volume.assert_called_once_with(
            snapshot_id=54,
            target_subsystem_id=5,
            target_volume_path=f"openstack-vol-{volume.id}",
        )
        mock_rest.volumes.update.assert_called_once_with(
            10,
            size=21474836480,
        )

    def test_create_snapshot(self):
        """Test creating a snapshot from a volume."""
        mock_rest = self._create_mocked_rest_api()
        volume = self._create_mock_volume()
        snapshot = self._create_mock_snapshot(volume=volume)
        vast_volume = vast_utils.Bunch(
            id=1,
            name=f"openstack-vol-{volume.id}",
            view_id=5,
        )
        subsystem = vast_utils.Bunch(
            id=5,
            path="/foo/bar",
            tenant_id=20,
        )
        mock_rest.volumes.one.return_value = vast_volume
        mock_rest.views.get_subsystem_by_id.return_value = subsystem
        snap_name = vast_utils.make_snapshot_name(snapshot, self.fake_conf)

        with patch.object(self._driver, "rest", mock_rest):
            self._driver.create_snapshot(snapshot)

        destination_path = vast_utils.concatenate_paths_abs(
            subsystem.path,
            vast_volume.name,
        )

        mock_rest.snapshots.ensure.assert_called_once_with(
            name=snap_name,
            path=destination_path,
            tenant_id=subsystem.tenant_id,
        )

    def test_delete_snapshot(self):
        """Test deleting a snapshot without active streams."""
        mock_rest = self._create_mocked_rest_api()
        snapshot = self._create_mock_snapshot()

        # Create a mock VAST snapshot object
        mock_vast_snap = mock.MagicMock()
        mock_vast_snap.id = "vast-snap-123"
        mock_vast_snap.name = "vast-snapshot-name"

        # Mock has_not_finished_streams to return False (no active streams)
        mock_rest.snapshots.has_not_finished_streams.return_value = False

        with patch.object(self._driver, "rest", mock_rest):
            with patch.object(
                self._driver,
                "_get_vast_snapshot",
                return_value=mock_vast_snap
            ):
                self._driver.delete_snapshot(snapshot)

        # Verify the snapshot was checked for active streams
        mock_rest.snapshots.has_not_finished_streams.assert_called_once_with(
            mock_vast_snap.id
        )
        # Verify the snapshot was deleted by ID
        mock_rest.snapshots.delete_by_id.assert_called_once_with(
            mock_vast_snap.id
        )

    def test_delete_snapshot_with_active_streams(self):
        """Test snapshot deletion with active streams raises exception."""
        mock_rest = self._create_mocked_rest_api()
        snapshot = self._create_mock_snapshot()

        # Create a mock VAST snapshot object
        mock_vast_snap = mock.MagicMock()
        mock_vast_snap.id = "vast-snap-123"
        mock_vast_snap.name = "vast-snapshot-name"

        # Mock has_not_finished_streams to return True (has active streams)
        mock_rest.snapshots.has_not_finished_streams.return_value = True

        with patch.object(self._driver, "rest", mock_rest):
            with patch.object(
                self._driver,
                "_get_vast_snapshot",
                return_value=mock_vast_snap
            ):
                # Should raise VolumeDriverException
                exc = self.assertRaises(
                    exception.VolumeDriverException,
                    self._driver.delete_snapshot,
                    snapshot
                )
                # Verify the exception message contains relevant information
                self.assertIn("Cannot delete snapshot", str(exc))
                self.assertIn("active streams", str(exc))

        # Verify the snapshot was checked for active streams
        mock_rest.snapshots.has_not_finished_streams.assert_called_once_with(
            mock_vast_snap.id
        )
        # Verify delete was NOT called
        mock_rest.snapshots.delete_by_id.assert_not_called()
