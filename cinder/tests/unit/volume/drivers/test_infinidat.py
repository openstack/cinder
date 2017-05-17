# Copyright 2016 Infinidat Ltd.
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
"""Unit tests for INFINIDAT InfiniBox volume driver."""

import mock
from oslo_utils import units

from cinder import exception
from cinder import test
from cinder.volume import configuration
from cinder.volume.drivers import infinidat


TEST_WWN_1 = '00:11:22:33:44:55:66:77'
TEST_WWN_2 = '11:11:22:33:44:55:66:77'

test_volume = mock.Mock(id=1, size=1)
test_snapshot = mock.Mock(id=2, volume=test_volume)
test_clone = mock.Mock(id=3, size=1)
test_connector = dict(wwpns=[TEST_WWN_1])


class FakeInfinisdkException(Exception):
    pass


class InfiniboxDriverTestCase(test.TestCase):
    def setUp(self):
        super(InfiniboxDriverTestCase, self).setUp()

        # create mock configuration
        self.configuration = mock.Mock(spec=configuration.Configuration)
        self.configuration.san_ip = 'mockbox'
        self.configuration.infinidat_pool_name = 'mockpool'
        self.configuration.san_thin_provision = 'thin'
        self.configuration.san_login = 'user'
        self.configuration.san_password = 'pass'
        self.configuration.volume_backend_name = 'mock'
        self.configuration.volume_dd_blocksize = '1M'
        self.configuration.use_multipath_for_image_xfer = False
        self.configuration.num_volume_device_scan_tries = 1
        self.configuration.san_is_local = False

        self.driver = infinidat.InfiniboxVolumeDriver(
            configuration=self.configuration)
        self._system = self._infinibox_mock()
        infinisdk = self.patch("cinder.volume.drivers.infinidat.infinisdk")
        capacity = self.patch("cinder.volume.drivers.infinidat.capacity")
        capacity.byte = 1
        capacity.GiB = units.Gi
        infinisdk.core.exceptions.InfiniSDKException = FakeInfinisdkException
        infinisdk.InfiniBox.return_value = self._system
        self.driver.do_setup(None)

    def _infinibox_mock(self):
        result = mock.Mock()
        self._mock_volume = mock.Mock()
        self._mock_volume.has_children.return_value = False
        self._mock_volume.get_logical_units.return_value = []
        self._mock_volume.create_child.return_value = self._mock_volume
        self._mock_host = mock.Mock()
        self._mock_host.get_luns.return_value = []
        self._mock_host.map_volume().get_lun.return_value = 1
        self._mock_pool = mock.Mock()
        self._mock_pool.get_free_physical_capacity.return_value = units.Gi
        self._mock_pool.get_physical_capacity.return_value = units.Gi
        result.volumes.safe_get.return_value = self._mock_volume
        result.volumes.create.return_value = self._mock_volume
        result.pools.safe_get.return_value = self._mock_pool
        result.hosts.safe_get.return_value = self._mock_host
        result.hosts.create.return_value = self._mock_host
        result.components.nodes.get_all.return_value = []
        return result

    def _raise_infinisdk(self, *args, **kwargs):
        raise FakeInfinisdkException()

    def test_get_volume_stats_refreshes(self):
        result = self.driver.get_volume_stats()
        self.assertEqual(1, result["free_capacity_gb"])
        # change the "free space" in the pool
        self._mock_pool.get_free_physical_capacity.return_value = 0
        # no refresh - free capacity should stay the same
        result = self.driver.get_volume_stats(refresh=False)
        self.assertEqual(1, result["free_capacity_gb"])
        # refresh - free capacity should change to 0
        result = self.driver.get_volume_stats(refresh=True)
        self.assertEqual(0, result["free_capacity_gb"])

    def test_get_volume_stats_pool_not_found(self):
        self._system.pools.safe_get.return_value = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.get_volume_stats)

    def test_initialize_connection(self):
        self._system.hosts.safe_get.return_value = None
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_initialize_connection_host_exists(self):
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_initialize_connection_mapping_exists(self):
        mock_mapping = mock.Mock()
        mock_mapping.get_volume.return_value = self._mock_volume
        mock_mapping.get_lun.return_value = 888
        self._mock_host.get_luns.return_value = [mock_mapping]
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(888, result["data"]["target_lun"])

    def test_initialize_connection_multiple_hosts(self):
        connector = {'wwpns': [TEST_WWN_1, TEST_WWN_2]}
        result = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_initialize_connection_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidVolume,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_connection_create_fails(self):
        self._system.hosts.safe_get.return_value = None
        self._system.hosts.create.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_connection_map_fails(self):
        self._mock_host.map_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_terminate_connection(self):
        self.driver.terminate_connection(test_volume, test_connector)

    def test_terminate_connection_delete_host(self):
        self._mock_host.get_luns.return_value = [object()]
        self.driver.terminate_connection(test_volume, test_connector)
        self.assertEqual(0, self._mock_host.safe_delete.call_count)
        self._mock_host.get_luns.return_value = []
        self.driver.terminate_connection(test_volume, test_connector)
        self.assertEqual(1, self._mock_host.safe_delete.call_count)

    def test_terminate_connection_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidVolume,
                          self.driver.terminate_connection,
                          test_volume, test_connector)

    def test_terminate_connection_api_fail(self):
        self._mock_host.unmap_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          test_volume, test_connector)

    def test_create_volume(self):
        self.driver.create_volume(test_volume)

    def test_create_volume_pool_not_found(self):
        self._system.pools.safe_get.return_value = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume, test_volume)

    def test_create_volume_api_fail(self):
        self._system.pools.safe_get.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, test_volume)

    def test_delete_volume(self):
        self.driver.delete_volume(test_volume)

    def test_delete_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        # should not raise an exception
        self.driver.delete_volume(test_volume)

    def test_delete_volume_with_children(self):
        self._mock_volume.has_children.return_value = True
        self.assertRaises(exception.VolumeIsBusy,
                          self.driver.delete_volume, test_volume)

    def test_extend_volume(self):
        self.driver.extend_volume(test_volume, 2)

    def test_extend_volume_api_fail(self):
        self._mock_volume.resize.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, test_volume, 2)

    def test_create_snapshot(self):
        self.driver.create_snapshot(test_snapshot)

    def test_create_snapshot_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidVolume,
                          self.driver.create_snapshot, test_snapshot)

    def test_create_snapshot_api_fail(self):
        self._mock_volume.create_snapshot.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, test_snapshot)

    @mock.patch("cinder.volume.utils.copy_volume")
    @mock.patch("cinder.utils.brick_get_connector")
    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    def test_create_volume_from_snapshot(self, *mocks):
        self.driver.create_volume_from_snapshot(test_clone, test_snapshot)

    def test_create_volume_from_snapshot_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidSnapshot,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    def test_create_volume_from_snapshot_create_fails(self):
        self._mock_volume.create_child.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    def test_create_volume_from_snapshot_map_fails(self, *mocks):
        self._mock_host.map_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    @mock.patch("cinder.volume.utils.copy_volume")
    @mock.patch("cinder.utils.brick_get_connector")
    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    def test_create_volume_from_snapshot_delete_clone_fails(self, *mocks):
        self._mock_volume.delete.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    def test_delete_snapshot(self):
        self.driver.delete_snapshot(test_snapshot)

    def test_delete_snapshot_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        # should not raise an exception
        self.driver.delete_snapshot(test_snapshot)

    def test_delete_snapshot_api_fail(self):
        self._mock_volume.safe_delete.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot, test_snapshot)

    @mock.patch("cinder.volume.utils.copy_volume")
    @mock.patch("cinder.utils.brick_get_connector")
    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    def test_create_cloned_volume(self, *mocks):
        self.driver.create_cloned_volume(test_clone, test_volume)

    def test_create_cloned_volume_volume_already_mapped(self):
        mock_mapping = mock.Mock()
        mock_mapping.get_volume.return_value = self._mock_volume
        self._mock_volume.get_logical_units.return_value = [mock_mapping]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          test_clone, test_volume)

    def test_create_cloned_volume_create_fails(self):
        self._system.volumes.create.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          test_clone, test_volume)

    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    def test_create_cloned_volume_map_fails(self, *mocks):
        self._mock_host.map_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          test_clone, test_volume)
