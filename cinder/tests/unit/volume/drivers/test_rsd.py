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

import sys
from unittest import mock

import fixtures

from cinder import exception
from cinder.i18n import _
from cinder.tests.unit import test
from cinder.tests.unit.volume import test_driver


MOCK_URL = "http://www.mock.url.com:4242"
MOCK_USER = "mock_user"
MOCK_PASSWORD = "mock_password"


class MockHTTPError(Exception):
    def __init__(self, msg):
        super(MockHTTPError, self).__init__(msg)


class MockConnectionError(Exception):
    def __init__(self, msg):
        super(MockConnectionError, self).__init__(msg)


class MockResourceNotFoundError(Exception):
    def __init__(self, msg):
        super(MockResourceNotFoundError, self).__init__(msg)


class MockBadRequestError(Exception):
    def __init__(self, msg):
        super(MockBadRequestError, self).__init__(msg)
        self.body = {
            "@Message.ExtendedInfo":
            [{"Message":
              "Cannot delete source snapshot volume when "
              "other clone volumes are based on this snapshot."}]}


class MockInvalidParameterValueError(Exception):
    def __init__(self, msg):
        super(MockInvalidParameterValueError, self).__init__(msg)


fake_RSDLib = mock.Mock()
fake_rsd_lib = mock.Mock()
fake_rsd_lib.RSDLib = mock.MagicMock(return_value=fake_RSDLib)
fake_sushy = mock.Mock()
fake_sushy.exceptions = mock.Mock()
fake_sushy.exceptions.HTTPError = MockHTTPError
fake_sushy.exceptions.ConnectionError = MockConnectionError
fake_sushy.exceptions.ResourceNotFoundError = MockResourceNotFoundError
fake_sushy.exceptions.BadRequestError = MockBadRequestError
fake_sushy.exceptions.InvalidParameterValueError = (
    MockInvalidParameterValueError)

sys.modules['rsd_lib'] = fake_rsd_lib
sys.modules['sushy'] = fake_sushy

from cinder.volume.drivers import rsd as rsd_driver  # noqa


class RSDClientTestCase(test.TestCase):

    def setUp(self):
        super(RSDClientTestCase, self).setUp()
        self.mock_rsd_lib = mock.Mock()
        self.mock_rsd_lib._rsd_api_version = "2.4.0"
        self.mock_rsd_lib._redfish_version = "1.1.0"
        self.mock_rsd_lib_factory = mock.MagicMock(
            return_value=self.mock_rsd_lib)
        fake_RSDLib.factory = self.mock_rsd_lib_factory

        self.rsd_client = rsd_driver.RSDClient(self.mock_rsd_lib)
        self.uuid = "84cff9ea-de0f-4841-8645-58620adf49b2"
        self.url = "/redfish/v1/Resource/Type"
        self.resource_url = self.url + "/" + self.uuid

    def _generate_rsd_storage_objects(self):
        self._mock_stor_obj_1 = mock.Mock()
        self._mock_stor_obj_2 = mock.Mock()
        self._mock_stor_obj_3 = mock.Mock()

        self._mock_drive_obj_1 = mock.Mock()
        self._mock_drive_obj_2 = mock.Mock()
        self._mock_drive_obj_3 = mock.Mock()

        self._mock_drive_obj_1.protocol = "NVMe"
        self._mock_drive_obj_2.protocol = "Blank"
        self._mock_drive_obj_3.protocol = ""

        self._mock_stor_obj_1.drives.get_members = mock.MagicMock(
            return_value=[self._mock_drive_obj_1])

        self._mock_stor_obj_2.drives.get_members = mock.MagicMock(
            return_value=[self._mock_drive_obj_2])

        self._mock_stor_obj_3.drives.get_members = mock.MagicMock(
            return_value=[self._mock_drive_obj_3])

        self._mock_stor_collection = [self._mock_stor_obj_1,
                                      self._mock_stor_obj_2,
                                      self._mock_stor_obj_3]

    def test_initialize(self):
        rsd_client = rsd_driver.RSDClient.initialize(MOCK_URL, MOCK_USER,
                                                     MOCK_PASSWORD,
                                                     verify=True)
        self.assertIsInstance(rsd_client, rsd_driver.RSDClient)

    def test_initialize_rsd_api_incorrect_version(self):
        self.mock_rsd_lib._rsd_api_version = "2.3.0"
        rsd_client_init = rsd_driver.RSDClient.initialize
        self.assertRaises(exception.VolumeBackendAPIException,
                          rsd_client_init, MOCK_URL, MOCK_USER,
                          MOCK_PASSWORD, False)

    def test_initialize_rsd_api_higher_version(self):
        self.mock_rsd_lib._rsd_api_version = "2.5.0"
        rsd_client = rsd_driver.RSDClient.initialize(MOCK_URL, MOCK_USER,
                                                     MOCK_PASSWORD,
                                                     verify=True)
        self.assertIsInstance(rsd_client, rsd_driver.RSDClient)

    def test_initialize_rsd_lib_incorrect_version(self):
        self.mock_rsd_lib._redfish_version = "1.0.0"
        rsd_client_init = rsd_driver.RSDClient.initialize
        self.assertRaises(exception.VolumeBackendAPIException,
                          rsd_client_init, MOCK_URL, MOCK_USER,
                          MOCK_PASSWORD, False)

    def test_initialize_rsd_lib_higher_version(self):
        self.mock_rsd_lib._redfish_version = "1.5.0"
        rsd_client = rsd_driver.RSDClient.initialize(MOCK_URL, MOCK_USER,
                                                     MOCK_PASSWORD,
                                                     verify=True)
        self.assertIsInstance(rsd_client, rsd_driver.RSDClient)

    def test_initialize_invalid_credentials(self):
        self.mock_rsd_lib_factory.side_effect = (
            fixtures._fixtures.timeout.TimeoutException)
        rsd_client_init = rsd_driver.RSDClient.initialize
        self.assertRaises(exception.VolumeBackendAPIException,
                          rsd_client_init, MOCK_URL, MOCK_USER,
                          MOCK_PASSWORD, False)

    def test_get_storage(self):
        mock_stor_serv = mock.Mock()
        self.mock_rsd_lib.get_storage_service = mock.MagicMock(
            return_value=mock_stor_serv)

        stor_serv = self.rsd_client._get_storage(self.resource_url)

        self.assertEqual(mock_stor_serv, stor_serv)
        self.mock_rsd_lib.get_storage_service.assert_called_with(self.url)

    def test_get_storages(self):
        self._generate_rsd_storage_objects()
        get_mem = self.mock_rsd_lib.get_storage_service_collection.return_value
        get_mem.get_members.return_value = self._mock_stor_collection

        storages = self.rsd_client._get_storages()

        self.assertEqual([self._mock_stor_obj_1], storages)

    def test_get_storages_non_nvme(self):
        self._generate_rsd_storage_objects()
        get_mem = self.mock_rsd_lib.get_storage_service_collection.return_value
        get_mem.get_members.return_value = self._mock_stor_collection

        storages = self.rsd_client._get_storages(False)

        self.assertEqual([self._mock_stor_obj_1, self._mock_stor_obj_2,
                          self._mock_stor_obj_3], storages)

    def test_get_storages_empty_storage(self):
        self._generate_rsd_storage_objects()
        get_mem = self.mock_rsd_lib.get_storage_service_collection.return_value
        get_mem.get_members.return_value = []

        storages = self.rsd_client._get_storages()

        self.assertEqual([], storages)

    def test_get_storages_empty_drive(self):
        self._generate_rsd_storage_objects()
        get_mem = self.mock_rsd_lib.get_storage_service_collection.return_value
        get_mem.get_members.return_value = self._mock_stor_collection

        self._mock_stor_obj_1.drives.get_members = mock.MagicMock(
            return_value=[])

        storages = self.rsd_client._get_storages()

        self.assertEqual([], storages)

    def test_get_volume(self):
        mock_stor_serv = mock.Mock()
        mock_vol_serv = mock.Mock()
        self.mock_rsd_lib.get_storage_service = mock.MagicMock(
            return_value=mock_stor_serv)
        mock_stor_serv.volumes.get_member = mock.MagicMock(
            return_value=mock_vol_serv)

        vol_serv = self.rsd_client._get_volume(self.resource_url)

        self.assertEqual(mock_vol_serv, vol_serv)
        self.mock_rsd_lib.get_storage_service.assert_called_with(self.url)
        mock_stor_serv.volumes.get_member.assert_called_with(self.resource_url)

    def test_get_providing_pool(self):
        mock_providing_pool_collection = mock.Mock()
        mock_providing_pool_collection.path = mock.Mock()
        mock_providing_pool = mock.Mock()
        mock_providing_pool.get_members = mock.Mock(
            return_value=[mock_providing_pool_collection])
        mock_volume = mock.Mock()
        mock_volume.capacity_sources = [mock.Mock()]
        mock_volume.capacity_sources[0].providing_pools = [mock_providing_pool]

        provider_pool = self.rsd_client._get_providing_pool(mock_volume)

        self.assertEqual(mock_providing_pool_collection.path, provider_pool)

    def test_get_providing_pool_no_capacity(self):
        mock_volume = mock.Mock()
        mock_volume.capacity_sources = []

        self.assertRaises(exception.ValidationError,
                          self.rsd_client._get_providing_pool,
                          mock_volume)

    def test_get_providing_pool_no_pools(self):
        mock_volume = mock.Mock()
        mock_volume.capacity_sources = [mock.Mock()]
        mock_volume.capacity_sources[0].providing_pools = []

        self.assertRaises(exception.ValidationError,
                          self.rsd_client._get_providing_pool,
                          mock_volume)

    def test_get_providing_pool_too_many_pools(self):
        mock_volume = mock.Mock()
        mock_volume.capacity_sources = [mock.Mock()]
        mock_volume.capacity_sources[0].providing_pools = [mock.Mock(),
                                                           mock.Mock()]

        self.assertRaises(exception.ValidationError,
                          self.rsd_client._get_providing_pool,
                          mock_volume)

    def test_create_vol_or_snap(self):
        mock_stor = mock.Mock()
        size_in_bytes = 10737418240
        mock_stor.volumes.create_volume = mock.Mock(
            return_value=self.resource_url)

        stor_url = self.rsd_client._create_vol_or_snap(mock_stor,
                                                       size_in_bytes)

        self.assertEqual(self.resource_url, stor_url)
        mock_stor.volumes.create_volume.assert_called_with(
            size_in_bytes, capacity_sources=None, replica_infos=None)

    def test_create_vol_or_snap_stor_pool(self):
        mock_stor = mock.Mock()
        size_in_bytes = 10737418240
        stor_uuid = "/redfish/v1/StorageService/NvMeoE1/StoragePools/2"
        expected_capacity = [{
            "ProvidingPools": [{
                "@odata.id": stor_uuid
            }]
        }]
        mock_stor.volumes.create_volume = mock.Mock(
            return_value=self.resource_url)

        stor_url = self.rsd_client._create_vol_or_snap(mock_stor,
                                                       size_in_bytes,
                                                       pool_url=stor_uuid)

        self.assertEqual(self.resource_url, stor_url)
        mock_stor.volumes.create_volume.assert_called_with(
            size_in_bytes,
            capacity_sources=expected_capacity,
            replica_infos=None)

    def test_create_vol_or_snap_source_snap(self):
        mock_stor = mock.Mock()
        size_in_bytes = 10737418240
        stor_uuid = "/redfish/v1/StorageService/NvMeoE1/StoragePools/2"
        expected_replica = [{
            "ReplicaType": "Clone",
            "Replica": {"@odata.id": stor_uuid}
        }]
        mock_stor.volumes.create_volume = mock.Mock(
            return_value=self.resource_url)

        stor_url = self.rsd_client._create_vol_or_snap(mock_stor,
                                                       size_in_bytes,
                                                       source_snap=stor_uuid)

        self.assertEqual(self.resource_url, stor_url)
        mock_stor.volumes.create_volume.assert_called_with(
            size_in_bytes,
            capacity_sources=None,
            replica_infos=expected_replica)

    def test_create_vol_or_snap_source_vol(self):
        mock_stor = mock.Mock()
        size_in_bytes = 10737418240
        stor_uuid = "/redfish/v1/StorageService/NvMeoE1/StoragePools/2"
        expected_replica = [{
            "ReplicaType": "Snapshot",
            "Replica": {"@odata.id": stor_uuid}
        }]
        mock_stor.volumes.create_volume = mock.Mock(
            return_value=self.resource_url)

        stor_url = self.rsd_client._create_vol_or_snap(mock_stor,
                                                       size_in_bytes,
                                                       source_vol=stor_uuid)

        self.assertEqual(self.resource_url, stor_url)
        mock_stor.volumes.create_volume.assert_called_with(
            size_in_bytes,
            capacity_sources=None,
            replica_infos=expected_replica)

    def test_create_vol_or_snap_source_snap_vol(self):
        mock_stor = mock.Mock()
        size_in_bytes = 10737418240
        stor_uuid = "/redfish/v1/StorageService/NvMeoE1/StoragePools/2"
        mock_stor.volumes.create_volume = mock.Mock(
            return_value=self.resource_url)

        self.assertRaises(exception.InvalidInput,
                          self.rsd_client._create_vol_or_snap,
                          mock_stor, size_in_bytes, source_snap=stor_uuid,
                          source_vol=stor_uuid)

    def test_create_volume(self):
        self._generate_rsd_storage_objects()
        size_in_Gb = 10
        expected_size_in_bytes = 10737418240
        self._mock_stor_obj_1.volumes.create_volume = mock.Mock(
            return_value=self.resource_url)
        self.rsd_client._get_storages = mock.Mock(
            return_value=[self._mock_stor_obj_1])

        stor_url = self.rsd_client.create_volume(size_in_Gb)

        self._mock_stor_obj_1.volumes.create_volume.assert_called_with(
            expected_size_in_bytes, capacity_sources=None, replica_infos=None)
        self.assertEqual(self.resource_url, stor_url)

    def test_create_volume_no_storage(self):
        self._generate_rsd_storage_objects()
        size_in_Gb = 10
        self.rsd_client._get_storages = mock.Mock(
            return_value=[])

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rsd_client.create_volume, size_in_Gb)

    def test_create_volume_multiple_storages(self):
        self._generate_rsd_storage_objects()
        size_in_Gb = 10
        expected_size_in_bytes = 10737418240
        mock_resp = mock.Mock()
        mock_resp.status = "404"
        self._mock_stor_obj_1.volumes.create_volume = mock.Mock(
            return_value=self.resource_url)
        self._mock_stor_obj_2.volumes.create_volume = mock.Mock(
            side_effect=MockHTTPError("HTTP Error"))
        self._mock_stor_obj_3.volumes.create_volume = mock.Mock(
            side_effect=MockConnectionError("Connection Error"))
        self.rsd_client._get_storages = mock.Mock(
            return_value=[self._mock_stor_obj_3,
                          self._mock_stor_obj_2,
                          self._mock_stor_obj_1])

        stor_url = self.rsd_client.create_volume(size_in_Gb)

        self._mock_stor_obj_1.volumes.create_volume.assert_called_with(
            expected_size_in_bytes, capacity_sources=None,
            replica_infos=None)
        self.assertEqual(self.resource_url, stor_url)

    def test_clone_volume(self):
        mock_volume = mock.Mock()
        mock_volume.capacity_bytes = 10737418240
        mock_volume.capacity_sources = [mock.Mock()]
        mock_volume.capacity_sources[0].providing_pools = [mock.Mock()]
        mock_storage = mock.Mock()
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_storage = mock.Mock(return_value=mock_storage)
        self.rsd_client._create_vol_or_snap = mock.Mock(
            return_value=self.resource_url)
        self.rsd_client._get_providing_pool = mock.Mock(
            return_value=self.resource_url)

        vol_url, snap_url = self.rsd_client.clone_volume(self.resource_url)

        self.assertEqual(self.resource_url, vol_url)
        self.assertEqual(self.resource_url, snap_url)
        self.rsd_client._create_vol_or_snap.assert_called_with(
            mock.ANY, 10737418240, pool_url=self.resource_url,
            source_snap=self.resource_url)

    def test_clone_volume_size_increase(self):
        mock_volume = mock.Mock()
        mock_volume.capacity_bytes = 10737418240
        new_size = 20
        mock_volume.capacity_sources = [mock.Mock()]
        mock_volume.capacity_sources[0].providing_pools = [mock.Mock()]
        mock_storage = mock.Mock()
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_storage = mock.Mock(return_value=mock_storage)
        self.rsd_client._create_vol_or_snap = mock.Mock(
            return_value=self.resource_url)
        self.rsd_client._get_providing_pool = mock.Mock(
            return_value=self.resource_url)

        vol_url, snap_url = self.rsd_client.clone_volume(self.resource_url,
                                                         new_size)

        self.assertEqual(self.resource_url, vol_url)
        self.assertEqual(self.resource_url, snap_url)
        self.rsd_client._create_vol_or_snap.assert_called_with(
            mock.ANY, 21474836480, pool_url=self.resource_url,
            source_snap=self.resource_url)

    def test_clone_volume_fail(self):
        mock_volume = mock.Mock()
        mock_volume.capacity_bytes = 10737418240
        mock_volume.capacity_sources = [mock.Mock()]
        mock_volume.capacity_sources[0].providing_pools = [mock.Mock()]
        mock_storage = mock.Mock()
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_storage = mock.Mock(return_value=mock_storage)
        self.rsd_client.delete_vol_or_snap = mock.Mock()
        self.rsd_client._create_vol_or_snap = mock.Mock(
            return_value=self.resource_url,
            side_effect=[None, exception.InvalidInput(
                reason=(_("_create_vol_or_snap failed")))])
        self.rsd_client._get_providing_pool = mock.Mock(
            return_value=self.resource_url)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rsd_client.clone_volume,
                          self.resource_url)
        self.rsd_client.delete_vol_or_snap.assert_called_once()

    def test_create_volume_from_snap(self):
        mock_snap = mock.Mock()
        mock_storage = mock.Mock()
        mock_snap.capacity_bytes = 10737418240
        self.rsd_client._get_storage = mock.Mock(return_value=mock_storage)
        self.rsd_client._get_volume = mock.Mock(return_value=mock_snap)
        self.rsd_client._get_providing_pool = mock.Mock(
            return_value=self.resource_url)
        self.rsd_client._create_vol_or_snap = mock.Mock(
            return_value=self.resource_url)

        volume_url = self.rsd_client.create_volume_from_snap(self.resource_url)

        self.assertEqual(self.resource_url, volume_url)
        self.rsd_client._create_vol_or_snap.assert_called_with(
            mock.ANY,
            10737418240,
            pool_url=self.resource_url,
            source_snap=self.resource_url)

    def test_create_volume_from_snap_with_size(self):
        mock_snap = mock.Mock()
        mock_storage = mock.Mock()
        mock_snap.capacity_bytes = 10737418240
        expected_capacity_bytes = 21474836480
        self.rsd_client._get_storage = mock.Mock(return_value=mock_storage)
        self.rsd_client._get_volume = mock.Mock(return_value=mock_snap)
        self.rsd_client._get_providing_pool = mock.Mock(
            return_value=self.resource_url)
        self.rsd_client._create_vol_or_snap = mock.Mock(
            return_value=self.resource_url)

        volume_url = self.rsd_client.create_volume_from_snap(
            self.resource_url, 20)

        self.assertEqual(self.resource_url, volume_url)
        self.rsd_client._create_vol_or_snap.assert_called_with(
            mock.ANY,
            expected_capacity_bytes,
            pool_url=self.resource_url,
            source_snap=self.resource_url)

    def test_create_volume_from_snap_create_failed(self):
        mock_snap = mock.Mock()
        mock_storage = mock.Mock()
        mock_snap.capacity_bytes = 10737418240
        self.rsd_client._get_storage = mock.Mock(return_value=mock_storage)
        self.rsd_client._get_volume = mock.Mock(return_value=mock_snap)
        self.rsd_client._get_providing_pool = mock.Mock(
            return_value=self.resource_url)
        self.rsd_client._create_vol_or_snap = mock.Mock(
            return_value=self.resource_url,
            side_effect=[exception.InvalidInput(
                reason=_("_create_vol_or_snap failed."))])

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rsd_client.create_volume_from_snap,
            self.resource_url)

    def test_delete_vol_or_snap(self):
        mock_volume = mock.Mock()
        mock_volume.links.endpoints = []
        mock_volume.delete = mock.Mock()
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)

        self.rsd_client.delete_vol_or_snap(self.resource_url)

        mock_volume.delete.assert_called_once()

    def test_delete_vol_or_snap_failed_delete(self):
        mock_volume = mock.Mock()
        mock_volume.links.endpoints = []
        mock_volume.delete = mock.Mock(side_effect=[
            RuntimeError("delete error")])
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rsd_client.delete_vol_or_snap,
            self.resource_url)

    def test_delete_vol_or_snap_non_exist(self):
        mock_volume = mock.Mock()
        mock_volume.links.endpoints = []
        mock_volume.delete = mock.Mock()
        self.rsd_client._get_volume = mock.Mock(
            side_effect=MockResourceNotFoundError("volume doesn't exist!"))

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rsd_client.delete_vol_or_snap,
                          self.resource_url,
                          ignore_non_exist=True)
        mock_volume.delete.assert_not_called()

    def test_delete_vol_or_snap_has_endpoints(self):
        mock_volume = mock.Mock()
        mock_volume.links.endpoints = [mock.Mock()]
        mock_volume.delete = mock.Mock()
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.rsd_client.delete_vol_or_snap,
                          self.resource_url)
        mock_volume.delete.assert_not_called()

    def test_delete_vol_or_snap_has_deps(self):
        mock_volume = mock.Mock()
        mock_volume.links.endpoints = [mock.Mock()]
        mock_volume.delete = mock.Mock(
            side_effect=MockBadRequestError("busy!"))
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client.delete_vol_or_snap = mock.Mock(
            side_effect=[None, exception.VolumeBackendAPIException(
                data="error")])

        self.rsd_client.delete_vol_or_snap(self.resource_url)
        self.rsd_client.delete_vol_or_snap.assert_called_once()

    def test_attach_volume_to_node_invalid_vol_url(self):
        self.rsd_client._get_volume = mock.Mock(side_effect=[
            RuntimeError("_get_volume failed")])
        self.rsd_client._get_node = mock.Mock()

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rsd_client.attach_volume_to_node,
            self.resource_url,
            self.resource_url)
        self.rsd_client._get_volume.assert_called_once()
        self.rsd_client._get_node.assert_not_called()

    def test_attach_volume_to_node_invalid_node_url(self):
        mock_volume = mock.Mock()
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_node = mock.Mock(side_effect=[
            RuntimeError("_get_node failed")])

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rsd_client.attach_volume_to_node,
            self.resource_url,
            self.resource_url)
        self.rsd_client._get_volume.assert_called_once()
        self.rsd_client._get_node.assert_called_once()

    def test_attach_volume_to_node_already_attached(self):
        mock_volume = mock.Mock()
        mock_node = mock.Mock()
        mock_volume.links.endpoints = [mock.Mock()]
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_node = mock.Mock(return_value=mock_node)

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.rsd_client.attach_volume_to_node,
            self.resource_url,
            self.resource_url)
        self.rsd_client._get_volume.assert_called_once()
        self.rsd_client._get_node.assert_called_once()

    @mock.patch('time.sleep')
    def test_attach_volume_to_node_too_few_endpoints(self, mock_sleep):
        mock_volume = mock.Mock()
        mock_node = mock.Mock()
        mock_volume.links.endpoints = []
        mock_node.detach_endpoint = mock.Mock()
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_node = mock.Mock(return_value=mock_node)
        self.rsd_client._get_nqn_endpoints = mock.Mock(return_value=[])

        self.assertRaises(
            rsd_driver.RSDRetryableException,
            self.rsd_client.attach_volume_to_node,
            self.resource_url,
            self.resource_url)
        self.assertEqual(5, mock_node.attach_endpoint.call_count)
        self.assertEqual(5, mock_node.detach_endpoint.call_count)

    @mock.patch('time.sleep')
    def test_attach_volume_to_node_too_many_endpoints(self, mock_sleep):
        mock_volume = mock.Mock()
        mock_node = mock.Mock()
        mock_volume.links.endpoints = []
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_node = mock.Mock(return_value=mock_node)
        self.rsd_client._get_nqn_endpoints = mock.Mock(return_value=[
                                                       mock.Mock(),
                                                       mock.Mock()])

        self.assertRaises(
            rsd_driver.RSDRetryableException,
            self.rsd_client.attach_volume_to_node,
            self.resource_url,
            self.resource_url)
        self.assertEqual(5, mock_node.attach_endpoint.call_count)
        self.assertEqual(5, mock_node.detach_endpoint.call_count)

    @mock.patch('time.sleep')
    def test_attach_volume_to_node_too_few_ip_transport(self, mock_sleep):
        mock_volume = mock.Mock()
        mock_node = mock.Mock()
        mock_target_nqn = mock.Mock()
        v_endpoints = {"IPTransportDetails": []}
        mock_v_endpoints = [(mock_target_nqn, v_endpoints)]
        mock_volume.links.endpoints = []
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_node = mock.Mock(return_value=mock_node)
        self.rsd_client._get_nqn_endpoints = mock.Mock(
            return_value=mock_v_endpoints)

        self.assertRaises(
            rsd_driver.RSDRetryableException,
            self.rsd_client.attach_volume_to_node,
            self.resource_url,
            self.resource_url)
        self.assertEqual(5, mock_node.attach_endpoint.call_count)
        self.assertEqual(5, mock_node.detach_endpoint.call_count)

    @mock.patch('time.sleep')
    def test_attach_volume_to_node_too_many_ip_transport(self, mock_sleep):
        mock_volume = mock.Mock()
        mock_node = mock.Mock()
        mock_target_nqn = mock.Mock()
        v_endpoints = {"IPTransportDetails": [mock.Mock(), mock.Mock()]}
        mock_v_endpoints = [(mock_target_nqn, v_endpoints)]
        mock_volume.links.endpoints = []
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_node = mock.Mock(return_value=mock_node)
        self.rsd_client._get_nqn_endpoints = mock.Mock(
            return_value=mock_v_endpoints)

        self.assertRaises(
            rsd_driver.RSDRetryableException,
            self.rsd_client.attach_volume_to_node,
            self.resource_url,
            self.resource_url)
        self.assertEqual(5, mock_node.attach_endpoint.call_count)
        self.assertEqual(5, mock_node.detach_endpoint.call_count)

    @mock.patch('time.sleep')
    def test_attach_volume_to_node_no_n_endpoints(self, mock_sleep):
        mock_volume = mock.Mock()
        mock_node = mock.Mock()
        mock_target_nqn = mock.Mock()
        mock_ip = '0.0.0.0'
        mock_port = 5446
        target_ip = {"Address": mock_ip}
        ip_transport = {"IPv4Address": target_ip, "Port": mock_port}
        v_endpoints = {"IPTransportDetails": [ip_transport]}
        mock_v_endpoints = [(mock_target_nqn, v_endpoints)]
        mock_volume.links.endpoints = []
        mock_node_system = mock.Mock()
        mock_node_system.json = {"Links": {"Endpoints": []}}
        self.mock_rsd_lib.get_system = mock.MagicMock(
            return_value=mock_node_system)
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_node = mock.Mock(return_value=mock_node)
        self.rsd_client._get_nqn_endpoints = mock.Mock(side_effect=[
                                                       mock_v_endpoints, [],
                                                       mock_v_endpoints, [],
                                                       mock_v_endpoints, [],
                                                       mock_v_endpoints, [],
                                                       mock_v_endpoints, []])

        self.assertRaises(
            rsd_driver.RSDRetryableException,
            self.rsd_client.attach_volume_to_node,
            self.resource_url,
            self.resource_url)
        self.assertEqual(5, mock_node.attach_endpoint.call_count)
        self.assertEqual(5, mock_node.detach_endpoint.call_count)

    @mock.patch('time.sleep')
    def test_attach_volume_to_node_retry_attach(self, mock_sleep):
        mock_volume = mock.Mock()
        mock_node = mock.Mock()
        mock_target_nqn = mock.Mock()
        mock_ip = '0.0.0.0'
        mock_port = 5446
        mock_host_nqn = 'host_nqn'
        target_ip = {"Address": mock_ip}
        ip_transport = {"IPv4Address": target_ip, "Port": mock_port}
        v_endpoints = {"IPTransportDetails": [ip_transport]}
        mock_v_endpoints = [(mock_target_nqn, v_endpoints)]
        mock_n_endpoints = [(mock_host_nqn, v_endpoints)]
        mock_volume.links.endpoints = []
        mock_node_system = mock.Mock()
        mock_node_system.json = {"Links": {"Endpoints": []}}
        self.mock_rsd_lib.get_system = mock.MagicMock(
            return_value=mock_node_system)
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_node = mock.Mock(return_value=mock_node)
        self.rsd_client._get_nqn_endpoints = mock.Mock(side_effect=[
                                                       mock_v_endpoints,
                                                       mock_n_endpoints])
        mock_node.attach_endpoint = mock.Mock(side_effect=[
            MockInvalidParameterValueError("invalid resource"), None])

        ret_tuple = self.rsd_client.attach_volume_to_node(self.resource_url,
                                                          self.resource_url)

        self.assertEqual((mock_ip, mock_port, mock_target_nqn,
                          mock_host_nqn), ret_tuple)
        self.assertEqual(2, mock_node.attach_endpoint.call_count)
        mock_node.detach_endpoint.assert_not_called()

    @mock.patch('time.sleep')
    def test_attach_volume_to_node_retry_post_attach(self, mock_sleep):
        mock_volume = mock.Mock()
        mock_node = mock.Mock()
        mock_target_nqn = mock.Mock()
        mock_ip = '0.0.0.0'
        mock_port = 5446
        mock_host_nqn = 'host_nqn'
        target_ip = {"Address": mock_ip}
        ip_transport = {"IPv4Address": target_ip, "Port": mock_port}
        v_endpoints = {"IPTransportDetails": [ip_transport]}
        mock_v_endpoints = [(mock_target_nqn, v_endpoints)]
        mock_n_endpoints = [(mock_host_nqn, v_endpoints)]
        mock_volume.links.endpoints = []
        mock_node_system = mock.Mock()
        mock_node_system.json = {"Links": {"Endpoints": []}}
        self.mock_rsd_lib.get_system = mock.MagicMock(
            return_value=mock_node_system)
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_node = mock.Mock(return_value=mock_node)
        self.rsd_client._get_nqn_endpoints = mock.Mock(side_effect=[
                                                       mock_v_endpoints,
                                                       [],
                                                       mock_v_endpoints,
                                                       mock_n_endpoints])

        ret_tuple = self.rsd_client.attach_volume_to_node(self.resource_url,
                                                          self.resource_url)

        self.assertEqual((mock_ip, mock_port, mock_target_nqn, mock_host_nqn),
                         ret_tuple)
        self.assertEqual(2, mock_node.attach_endpoint.call_count)
        mock_node.detach_endpoint.assert_called_once()

    def test_attach_volume_to_node(self):
        mock_volume = mock.Mock()
        mock_node = mock.Mock()
        mock_target_nqn = mock.Mock()
        mock_ip = '0.0.0.0'
        mock_port = 5446
        mock_host_nqn = 'host_nqn'
        target_ip = {"Address": mock_ip}
        ip_transport = {"IPv4Address": target_ip, "Port": mock_port}
        v_endpoints = {"IPTransportDetails": [ip_transport]}
        mock_v_endpoints = [(mock_target_nqn, v_endpoints)]
        mock_n_endpoints = [(mock_host_nqn, v_endpoints)]
        mock_volume.links.endpoints = []
        mock_node_system = mock.Mock()
        mock_node_system.json = {"Links": {"Endpoints": []}}
        self.mock_rsd_lib.get_system = mock.MagicMock(
            return_value=mock_node_system)
        self.rsd_client._get_volume = mock.Mock(return_value=mock_volume)
        self.rsd_client._get_node = mock.Mock(return_value=mock_node)
        self.rsd_client._get_nqn_endpoints = mock.Mock(side_effect=[
                                                       mock_v_endpoints,
                                                       mock_n_endpoints])

        ret_tuple = self.rsd_client.attach_volume_to_node(self.resource_url,
                                                          self.resource_url)

        self.assertEqual((mock_ip, mock_port, mock_target_nqn, mock_host_nqn),
                         ret_tuple)
        mock_node.attach_endpoint.assert_called_once()
        mock_node.detach_endpoint.assert_not_called()

    def test_get_node_url_by_uuid(self):
        mock_node = mock.Mock()
        mock_node.path = self.resource_url
        mock_node_system = mock.Mock()
        mock_node_system.uuid = self.uuid
        self.mock_rsd_lib.get_system = mock.MagicMock(
            return_value=mock_node_system)
        get_mem = self.mock_rsd_lib.get_node_collection.return_value
        get_mem.get_members.return_value = [mock_node]

        node_url = self.rsd_client.get_node_url_by_uuid(self.uuid.lower())

        self.assertEqual(self.resource_url, node_url)

    def test_get_node_url_by_uuid_uuid_not_present(self):
        mock_node = mock.Mock()
        mock_node.path = self.resource_url
        mock_node_system = mock.Mock()
        mock_node_system.uuid = self.uuid
        self.mock_rsd_lib.get_system = mock.MagicMock(
            return_value=mock_node_system)
        get_mem = self.mock_rsd_lib.get_node_collection.return_value
        get_mem.get_members.return_value = []

        node_url = self.rsd_client.get_node_url_by_uuid(self.uuid.lower())

        self.assertEqual("", node_url)

    def test_get_node_url_by_uuid_multiple_uuids(self):
        mock_node = mock.Mock()
        mock_node.path = self.resource_url
        mock_node_system = mock.Mock()
        mock_node_system.uuid = self.uuid
        second_uuid = "9f9244dd-59a1-4532-b548-df784c7"
        mock_node_dummy = mock.Mock()
        mock_node_dummy.path = self.url + "/" + second_uuid
        mock_node_dummy_system = mock.Mock()
        mock_node_dummy_system.uuid = second_uuid
        self.mock_rsd_lib.get_system = mock.MagicMock(
            side_effect=[mock_node_dummy_system, mock_node_system])
        get_mem = self.mock_rsd_lib.get_node_collection.return_value
        get_mem.get_members.return_value = [mock_node_dummy, mock_node]

        node_url = self.rsd_client.get_node_url_by_uuid(self.uuid.lower())

        self.assertEqual(self.resource_url, node_url)

    def test_get_node_url_by_uuid_exception(self):
        mock_node = mock.Mock()
        mock_node.path = self.resource_url
        mock_node_system = mock.Mock()
        mock_node_system.uuid = self.uuid
        self.mock_rsd_lib.get_system = mock.MagicMock(
            return_value=mock_node_system)
        get_mem = self.mock_rsd_lib.get_node_collection.return_value
        get_mem.get_members.side_effect = [RuntimeError("Mock Exception")]

        node_url = self.rsd_client.get_node_url_by_uuid(self.uuid.lower())

        self.assertEqual("", node_url)

    def test_get_stats(self):
        mock_str_pool_1 = mock.Mock()
        mock_str_pool_2 = mock.Mock()
        mock_str_pool_3 = mock.Mock()
        mock_str_pool_1.capacity.allocated_bytes = 10737418240
        mock_str_pool_2.capacity.allocated_bytes = 21474836480
        mock_str_pool_3.capacity.allocated_bytes = 32212254720
        mock_str_pool_1.capacity.consumed_bytes = 5368709120
        mock_str_pool_2.capacity.consumed_bytes = 10737418240
        mock_str_pool_3.capacity.consumed_bytes = 21474836480

        self._generate_rsd_storage_objects()
        self._mock_stor_obj_1.storage_pools.get_members = mock.Mock(
            return_value=[mock_str_pool_1])
        self._mock_stor_obj_2.storage_pools.get_members = mock.Mock(
            return_value=[mock_str_pool_2])
        self._mock_stor_obj_3.storage_pools.get_members = mock.Mock(
            return_value=[mock_str_pool_3])
        self._mock_stor_obj_1.volumes.members_identities = [mock.Mock()]
        self._mock_stor_obj_2.volumes.members_identities = [mock.Mock(),
                                                            mock.Mock()]
        self._mock_stor_obj_3.volumes.members_identities = [mock.Mock(),
                                                            mock.Mock(),
                                                            mock.Mock()]
        self.rsd_client._get_storages = mock.Mock(
            return_value=self._mock_stor_collection)
        stat_tuple = self.rsd_client.get_stats()

        self.assertEqual((25.0, 60.0, 35.0, 6), stat_tuple)

    def test_get_stats_fail(self):
        self.rsd_client._get_storages = mock.Mock()
        self.rsd_client._get_storages.side_effect = [
            RuntimeError("Connection Error")]

        stat_tuple = self.rsd_client.get_stats()

        self.assertEqual((0, 0, 0, 0), stat_tuple)


class RSDDriverTestCase(test_driver.BaseDriverTestCase):
    driver_name = "cinder.volume.drivers.rsd.RSDDriver"

    def setUp(self):
        super(RSDDriverTestCase, self).setUp()
        self.mock_volume = mock.MagicMock()
        self.mock_dict = {'size': 10}
        self.volume.driver.rsdClient = mock.MagicMock()
        self.rsd_client = self.volume.driver.rsdClient
        self.uuid = "84cff9ea-de0f-4841-8645-58620adf49b2"
        self.url = "/redfish/v1/Storage/StorageService"
        self.resource_url = self.url + "/" + self.uuid

    def test_create_volume(self):
        self.rsd_client.create_volume = mock.Mock(
            return_value=self.resource_url)

        vol_update = self.volume.driver.create_volume(self.mock_dict)

        self.assertEqual({'provider_location': self.resource_url}, vol_update)

    def test_delete_volume(self):
        self.rsd_client.delete_vol_or_snap = mock.Mock(
            return_value=True)
        self.mock_dict['provider_location'] = self.resource_url
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__
        self.mock_volume.metadata.get = mock.Mock(
            return_value=self.resource_url)

        self.assertIsNone(self.volume.driver.delete_volume(self.mock_volume))
        self.rsd_client.delete_vol_or_snap.assert_called()
        self.assertEqual(2, self.rsd_client.delete_vol_or_snap.call_count)

    def test_delete_volume_no_snapshot(self):
        self.rsd_client.delete_vol_or_snap = mock.Mock(
            return_value=True)
        self.mock_dict['provider_location'] = self.resource_url
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__
        self.mock_volume.metadata.get = mock.Mock(return_value=None)

        self.assertIsNone(self.volume.driver.delete_volume(self.mock_volume))
        self.rsd_client.delete_vol_or_snap.assert_called_once()

    def test_delete_volume_no_volume_url(self):
        self.rsd_client.delete_vol_or_snap = mock.Mock(
            return_value=True)
        self.mock_dict['provider_location'] = None
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__

        self.assertIsNone(self.volume.driver.delete_volume(self.mock_volume))
        self.rsd_client.delete_vol_or_snap.assert_not_called()

    def test_delete_volume_busy_volume(self):
        self.rsd_client.delete_vol_or_snap = mock.Mock(
            side_effect=[exception.VolumeIsBusy(
                volume_name=self.mock_volume.name)])

        self.mock_dict['provider_location'] = self.resource_url
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__

        self.assertRaises(exception.VolumeIsBusy,
                          self.volume.driver.delete_volume, self.mock_volume)
        self.rsd_client.delete_vol_or_snap.assert_called_once()

    def test_delete_volume_snap_deletion_error(self):
        self.rsd_client.delete_vol_or_snap = mock.Mock(
            side_effect=[None, exception.VolumeBackendAPIException(
                data="error")])
        self.mock_dict['provider_location'] = self.resource_url
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.driver.delete_volume, self.mock_volume)
        self.rsd_client.delete_vol_or_snap.assert_called()
        self.assertEqual(2, self.rsd_client.delete_vol_or_snap.call_count)

    def test_get_volume_stats_refresh(self):
        ret_tuple = (25.0, 60.0, 35.0, 6)
        self.rsd_client.get_stats = mock.Mock(return_value=ret_tuple)
        expected_stats = {'driver_version': '1.0.0',
                          'pools': [{
                              'allocated_capacity_gb': 35.0,
                              'free_capacity_gb': 25.0,
                              'multiattach': False,
                              'pool_name': 'RSD',
                              'thick_provisioning_support': True,
                              'thin_provisioning_support': True,
                              'total_capacity_gb': 60.0}],
                          'storage_protocol': 'nvmeof',
                          'vendor_name': 'Intel',
                          'volume_backend_name': 'RSD'}

        stats = self.volume.driver.get_volume_stats(refresh=True)
        self.assertEqual(expected_stats, stats)

    def test_initialize_connection(self):
        mock_connector = {'system uuid':
                          "281bbc50-e76f-40e7-a757-06b916a83d6f"}
        self.mock_dict['provider_location'] = self.resource_url
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__
        self.rsd_client.get_node_url_by_uuid = mock.Mock(
            return_value=self.resource_url)
        ret_tuple = ("0.0.0.0", 5467, "target.mock.nqn", "initiator.mock.nqn")
        self.rsd_client.attach_volume_to_node = mock.Mock(
            return_value=ret_tuple)
        expected_conn_info = {
            'driver_volume_type': 'nvmeof',
            'data': {
                'transport_type': 'rdma',
                'host_nqn': "initiator.mock.nqn",
                'nqn': "target.mock.nqn",
                'target_port': 5467,
                'target_portal': "0.0.0.0",
            }
        }

        conn_info = self.volume.driver.initialize_connection(self.mock_volume,
                                                             mock_connector)

        self.assertEqual(expected_conn_info, conn_info)

    def test_initialize_connection_node_not_found(self):
        mock_connector = {'system uuid':
                          "281bbc50-e76f-40e7-a757-06b916a83d6f"}
        self.mock_dict['provider_location'] = self.resource_url
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__
        self.rsd_client.get_node_url_by_uuid = mock.Mock(
            return_value="")
        ret_tuple = ("0.0.0.0", 5467, "target.mock.nqn", "initiator.mock.nqn")
        self.rsd_client.attach_volume_to_node = mock.Mock(
            return_value=ret_tuple)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.driver.initialize_connection,
                          self.mock_volume, mock_connector)
        self.rsd_client.attach_volume_to_node.assert_not_called()
        self.rsd_client.get_node_url_by_uuid.assert_called_once()

    def test_initialize_connection_no_system_uuid(self):
        mock_connector = {}
        self.mock_dict['provider_location'] = self.resource_url
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__
        self.rsd_client.get_node_url_by_uuid = mock.Mock(
            return_value=self.resource_url)
        ret_tuple = ("0.0.0.0", 5467, "target.mock.nqn", "initiator.mock.nqn")
        self.rsd_client.attach_volume_to_node = mock.Mock(
            return_value=ret_tuple)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.driver.initialize_connection,
                          self.mock_volume, mock_connector)
        self.rsd_client.attach_volume_to_node.assert_not_called()
        self.rsd_client.get_node_url_by_uuid.assert_not_called()

    def test_terminate_connection(self):
        mock_connector = {'system uuid':
                          "281bbc50-e76f-40e7-a757-06b916a83d6f"}
        self.mock_dict['provider_location'] = self.resource_url
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__
        self.rsd_client.get_node_url_by_uuid = mock.Mock(
            return_value=self.resource_url)

        self.volume.driver.terminate_connection(self.mock_volume,
                                                mock_connector)

        self.rsd_client.get_node_url_by_uuid.assert_called_once()
        self.rsd_client.detach_volume_from_node.assert_called_once()

    def test_terminate_connection_no_node(self):
        mock_connector = {'system uuid':
                          "281bbc50-e76f-40e7-a757-06b916a83d6f"}
        self.mock_dict['provider_location'] = self.resource_url
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__
        self.rsd_client.get_node_url_by_uuid = mock.Mock(
            return_value="")

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.driver.terminate_connection,
                          self.mock_volume, mock_connector)
        self.rsd_client.get_node_url_by_uuid.assert_called_once()
        self.rsd_client.detach_volume_from_node.assert_not_called()

    def test_terminate_connection_no_connector(self):
        mock_connector = None
        self.mock_dict['provider_location'] = self.resource_url
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__
        self.rsd_client.get_node_url_by_uuid = mock.Mock(
            return_value=self.resource_url)

        self.volume.driver.terminate_connection(
            self.mock_volume, mock_connector)
        self.rsd_client.detach_all_node_connections_for_volume. \
            assert_called_once()
        self.rsd_client.get_node_url_by_uuid.assert_not_called()
        self.rsd_client.detach_volume_from_node.assert_not_called()

    def test_terminate_connection_no_system_uuid(self):
        mock_connector = {}
        self.mock_dict['provider_location'] = self.resource_url
        self.mock_volume.__getitem__.side_effect = self.mock_dict.__getitem__
        self.rsd_client.get_node_url_by_uuid = mock.Mock(
            return_value=self.resource_url)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.driver.terminate_connection,
                          self.mock_volume, mock_connector)
        self.rsd_client.get_node_url_by_uuid.assert_not_called()
        self.rsd_client.detach_volume_from_node.assert_not_called()

    def test_create_volume_from_snapshot(self):
        mock_snap = mock.Mock()
        mock_snap.provider_location = self.resource_url
        mock_snap.volume_size = 10
        self.mock_volume.size = 10
        self.rsd_client.create_volume_from_snap = mock.Mock(
            return_value=self.resource_url)
        self.rsd_client.delete_vol_or_snap = mock.Mock()

        ret_dict = self.volume.driver.create_volume_from_snapshot(
            self.mock_volume, mock_snap)

        self.assertEqual({'provider_location': self.resource_url}, ret_dict)
        self.rsd_client.create_volume_from_snap.assert_called_once()
        self.rsd_client.extend_volume.assert_not_called()
        self.rsd_client.delete_vol_or_snap.assert_not_called()

    def test_create_volume_from_snapshot_diff_size(self):
        mock_snap = mock.Mock()
        mock_snap.provider_location = self.resource_url
        mock_snap.volume_size = 10
        self.mock_volume.size = 20
        self.rsd_client.create_volume_from_snap = mock.Mock(
            return_value=self.resource_url)
        self.rsd_client.extend_volume = mock.Mock()
        self.rsd_client.delete_vol_or_snap = mock.Mock()

        ret_dict = self.volume.driver.create_volume_from_snapshot(
            self.mock_volume, mock_snap)

        self.assertEqual({'provider_location': self.resource_url}, ret_dict)
        self.rsd_client.create_volume_from_snap.assert_called_once()
        self.rsd_client.extend_volume.assert_called_once()
        self.rsd_client.delete_vol_or_snap.assert_not_called()

    def test_create_volume_from_snapshot_diff_size_fail(self):
        mock_snap = mock.Mock()
        mock_snap.provider_location = self.resource_url
        mock_snap.volume_size = 10
        self.mock_volume.size = 20
        self.rsd_client.create_volume_from_snap = mock.Mock(
            return_value=self.resource_url)
        self.rsd_client.extend_volume = mock.Mock(
            side_effect=[exception.VolumeBackendAPIException(
                data="extend fail")])
        self.rsd_client.delete_vol_or_snap = mock.Mock()

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.driver.create_volume_from_snapshot,
                          self.mock_volume, mock_snap)

        self.rsd_client.create_volume_from_snap.assert_called_once()
        self.rsd_client.extend_volume.assert_called_once()
        self.rsd_client.delete_vol_or_snap.assert_called_once()

    def test_delete_snapshot(self):
        mock_snap = mock.Mock()
        mock_snap.provider_location = self.resource_url
        mock_snap.name = "mock_snapshot"
        self.rsd_client.delete_vol_or_snap = mock.Mock(return_value=True)

        self.volume.driver.delete_snapshot(mock_snap)

        self.rsd_client.delete_vol_or_snap.assert_called_once()

    def test_delete_snapshot_no_url(self):
        mock_snap = mock.Mock()
        mock_snap.provider_location = ""
        mock_snap.name = "mock_snapshot"
        self.rsd_client.delete_vol_or_snap = mock.Mock(return_value=True)

        self.volume.driver.delete_snapshot(mock_snap)

        self.rsd_client.delete_vol_or_snap.assert_not_called()

    def test_delete_snapshot_unable_to_delete(self):
        mock_snap = mock.Mock()
        mock_snap.provider_location = self.resource_url
        mock_snap.name = "mock_snapshot"
        self.rsd_client.delete_vol_or_snap = mock.Mock(
            side_effect=[exception.SnapshotIsBusy(
                snapshot_name=mock_snap.name)])

        self.assertRaises(exception.SnapshotIsBusy,
                          self.volume.driver.delete_snapshot, mock_snap)

        self.rsd_client.delete_vol_or_snap.assert_called_once()

    def test_create_cloned_volume(self):
        mock_vref = mock.Mock()
        mock_vref.provider_location = self.resource_url
        mock_vref.size = 10
        self.mock_volume.size = 10
        self.rsd_client.clone_volume = mock.Mock(
            return_value=(self.resource_url, self.resource_url))
        self.rsd_client.extend_volume = mock.Mock()
        self.rsd_client.delete_vol_or_snap = mock.Mock()

        self.volume.driver.create_cloned_volume(self.mock_volume, mock_vref)

        self.rsd_client.clone_volume.assert_called_once()
        self.rsd_client.extend_volume.assert_not_called()
        self.rsd_client.delete_vol_or_snap.assert_not_called()

    def test_create_cloned_volume_extend_vol(self):
        mock_vref = mock.Mock()
        mock_vref.provider_location = self.resource_url
        mock_vref.size = 20
        self.mock_volume.size = 10
        self.rsd_client.clone_volume = mock.Mock(
            return_value=(self.resource_url, self.resource_url))
        self.rsd_client.extend_volume = mock.Mock()
        self.rsd_client.delete_vol_or_snap = mock.Mock()

        self.volume.driver.create_cloned_volume(self.mock_volume, mock_vref)

        self.rsd_client.clone_volume.assert_called_once()
        self.rsd_client.extend_volume.assert_called_once()
        self.rsd_client.delete_vol_or_snap.assert_not_called()

    def test_create_cloned_volume_extend_vol_fail(self):
        mock_vref = mock.Mock()
        mock_vref.provider_location = self.resource_url
        mock_vref.size = 20
        self.mock_volume.size = 10
        self.rsd_client.clone_volume = mock.Mock(
            return_value=(self.resource_url, self.resource_url))
        self.rsd_client.extend_volume = mock.Mock(
            side_effect=exception.VolumeBackendAPIException(
                data="extend fail"))
        self.rsd_client.delete_vol_or_snap = mock.Mock()

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.driver.create_cloned_volume,
                          self.mock_volume, mock_vref)

        self.rsd_client.clone_volume.assert_called_once()
        self.rsd_client.extend_volume.assert_called_once()
        self.assertEqual(2, self.rsd_client.delete_vol_or_snap.call_count)
