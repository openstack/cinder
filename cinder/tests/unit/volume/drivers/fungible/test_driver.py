#    (c)  Copyright 2022 Fungible, Inc. All rights reserved.
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

import unittest
from unittest import mock
import uuid

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder.objects import fields
from cinder.tests.unit import fake_constants
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit.volume.drivers.fungible import test_adapter
from cinder import volume
from cinder.volume import configuration
from cinder.volume.drivers.fungible import constants
from cinder.volume.drivers.fungible import driver
from cinder.volume.drivers.fungible import rest_client
from cinder.volume.drivers.fungible import \
    swagger_api_client as swagger_client
from cinder.volume import volume_types
from cinder.volume import volume_utils

common_success_res = swagger_client.CommonResponseFields(
    status=True, message='healthy')
common_failure_res = swagger_client.CommonResponseFields(
    status=False, message='error')
success_uuid = swagger_client.ResponseDataWithCreateUuid(
    status=True, data={'uuid': 'mock_id'})
success_response = swagger_client.SuccessResponseFields(
    status=True, message="mock_message")
get_volume_details = swagger_client.ResponseDataWithCreateUuid(
    status=True,
    data={"dpu": "mock_dpu_uuid", "secy_dpu": "mock_dpu_uuid",
          "ports": {"mock_id": {"host_nqn": "mock_nqn",
                    "host_uuid": "mock_host_id", "transport": "TCP"}}})
get_topology = swagger_client.ResponseDpuDriveHierarchy(
    status=True,
    data={"mock_device_uuid": {
          "available": True, "dpus": [{"dataplane_ip": "mock_dataplae_ip",
                                       "uuid": "mock_dpu_uuid"}]}})
get_host_id_list = swagger_client.ResponseDataWithListOfHostUuids(
    status=True,
    data={"total_hosts_with_fac": 0, "total_hosts_without_fac": 1,
          "host_uuids": ["mock_host_id"]})
get_host_info = swagger_client.ResponseDataWithHostInfo(
    status=True,
    data={"host_uuid": "mock_host_id", "host_nqn": "mock_nqn",
          "fac_enabled": False})
fetch_hosts_with_ids = swagger_client.ResponseDataWithListOfHosts(
    status=True,
    data=[
        {
            "host_uuid": "mock_host_id", "host_nqn": "mock_nqn",
            "fac_enabled": False
        }
    ])
create_copy_task = swagger_client.ResponseCreateVolumeCopyTask(
    status=True, data={'task_uuid': 'mock_id'})
get_task_success = swagger_client.ResponseGetVolumeCopyTask(
    status=True, data={'task_state': 'SUCCESS'})


class FungibleDriverTest(unittest.TestCase):
    def setUp(self):
        super(FungibleDriverTest, self).setUp()
        self.configuration = mock.Mock(spec=configuration.Configuration)
        self.configuration.san_ip = '127.0.0.1'
        self.configuration.san_api_port = 443
        self.configuration.san_login = 'admin'
        self.configuration.san_password = 'password'
        self.configuration.nvme_connect_port = 4420
        self.configuration.api_enable_ssl = False
        self.driver = driver.FungibleDriver(configuration=self.configuration)
        self.driver.do_setup(context=None)
        self.context = context.get_admin_context()
        self.api_exception = swagger_client.ApiException(
            status=400,
            reason="Bad Request",
            http_resp=self.get_api_exception_response())

    @staticmethod
    def get_volume():
        volume = fake_volume.fake_volume_obj(mock.MagicMock())
        volume.size = 1
        volume.provider_id = fake_constants.UUID1
        volume.migration_status = ''
        volume.id = str(uuid.uuid4())
        volume.display_name = 'volume'
        volume.host = 'mock_host_name'
        volume.volume_type_id = fake_constants.VOLUME_TYPE_ID
        volume.metadata = {}
        return volume

    @staticmethod
    def get_snapshot():
        snapshot = fake_snapshot.fake_snapshot_obj(mock.MagicMock())
        snapshot.display_name = 'snapshot'
        snapshot.provider_id = fake_constants.UUID1
        snapshot.id = str(uuid.uuid4())
        snapshot.volume = FungibleDriverTest.get_volume()
        return snapshot

    @staticmethod
    def get_connector():
        return {"nqn": "mock_nqn"}

    @staticmethod
    def get_specs():
        return {
            constants.FSC_SPACE_ALLOCATION_POLICY: "write_optimized",
            constants.FSC_COMPRESSION: "true",
            constants.FSC_QOS_BAND: "gold",
            constants.FSC_SNAPSHOTS: "false",
            constants.FSC_BLK_SIZE: "4096"
        }

    @staticmethod
    def get_metadata():
        return {
            constants.FSC_SPACE_ALLOCATION_POLICY: "write_optimized",
            constants.FSC_COMPRESSION: "false",
            constants.FSC_QOS_BAND: "bronze",
            constants.FSC_EC_SCHEME: constants.EC_4_2
        }

    @staticmethod
    def get_api_exception_response():
        return test_adapter.MockResource(
            status=False,
            data='{"error_message":"mock_error_message","status":false}')

    '''@staticmethod
    def get_volume_details():
        return {
            "data": {
                "ports": {
                    "mock_id": {
                        "host_nqn": "mock_nqn",
                        "ip": "127.0.0.1"
                    }
                }
            }
        }'''

    def test_get_driver_options(self):
        self.assertIsNotNone(self.driver.get_driver_options())

    def test_volume_stats(self):
        self.assertIsNotNone(self.driver.get_volume_stats())

    @mock.patch.object(swagger_client.ApigatewayApi, 'get_fc_health')
    def test_check_for_setup_error_success(self, mock_success_response):
        mock_success_response.return_value = common_success_res
        result = self.driver.check_for_setup_error()
        self.assertIsNone(result)

    @mock.patch.object(swagger_client.ApigatewayApi, 'get_fc_health')
    def test_check_for_setup_error_fail(self, mock_staus):
        mock_staus.return_value = common_failure_res
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.check_for_setup_error()

    @mock.patch.object(rest_client.RestClient, 'check_for_setup_error')
    def test_check_for_setup_error_exception(self, mock_staus):
        mock_staus.side_effect = Exception("mock exception")
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.check_for_setup_error()

    @mock.patch.object(rest_client.RestClient, 'check_for_setup_error')
    def test_check_for_setup_error_api_exception(self, mock_exception):
        mock_exception.side_effect = self.api_exception
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.check_for_setup_error()

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_get_volume_stats_without_volume_type(self, mock_get_volume_type):
        volume = self.get_volume()
        volume.volume_type_id = "mock_id"
        mock_get_volume_type.return_value = {"extra_specs": self.get_specs()}
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver._get_volume_type_extra_specs(self, volume=volume)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_get_volume_stats_with_volume_type(self, mock_get_volume_type):
        volume = {"volume_type_id": "mock_id"}
        extra_specs = self.get_specs()
        extra_specs.update({constants.FSC_VOL_TYPE: constants.VOLUME_TYPE_RAW})
        mock_get_volume_type.return_value = {"extra_specs": extra_specs}
        self.assertIsNotNone(
            self.driver._get_volume_type_extra_specs(self, volume=volume))

    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    def test_create_volume(self, mock_create_volume):
        volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        mock_create_volume.return_value = success_uuid
        ret = self.driver.create_volume(volume)
        self.assertIsNotNone(ret)
        self.assertEqual(volume['size'], ret['size'])

    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    def test_create_ec_volume_8_2(self, mock_create_volume):
        volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{constants.FSC_EC_SCHEME: "8_2"},
                          constants.VOLUME_TYPE_EC])
        mock_create_volume.return_value = success_uuid
        ret = self.driver.create_volume(volume)
        self.assertIsNotNone(ret)
        self.assertEqual(volume['size'], ret['size'])

    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    def test_create_replicated_volume(self, mock_create_volume):
        volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_REPLICA])
        ret = self.driver.create_volume(volume)
        mock_create_volume.return_value = success_uuid
        self.assertIsNotNone(ret)
        self.assertEqual(volume['size'], ret['size'])

    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    def test_create_volume_with_specs(self, mock_create_volume):
        volume = self.get_volume()
        mock_ret = self.get_specs()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[mock_ret, constants.VOLUME_TYPE_EC])
        mock_create_volume.return_value = success_uuid
        ret = self.driver.create_volume(volume)
        self.assertIsNotNone(ret)
        self.assertEqual(volume['size'], ret['size'])

    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    def test_create_volume_with_metadata(self, mock_create_volume):
        volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        mock_create_volume.return_value = success_uuid
        volume['metadata'].update(self.get_metadata())
        ret = self.driver.create_volume(volume)
        self.assertIsNotNone(ret)
        self.assertEqual(volume['size'], ret['size'])

    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    def test_create_volume_with_fault_domains(self, mock_create_volume):
        volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_RAW])
        volume['metadata'].update(self.get_metadata())
        volume['metadata'].update({constants.FSC_FD_IDS: 'fake_id1, fake_id2'})
        volume['metadata'].update(
            {constants.FSC_FD_OP: constants.FSC_FD_OPS[0]})
        mock_create_volume.return_value = success_uuid
        ret = self.driver.create_volume(volume)
        self.assertIsNotNone(ret)
        self.assertEqual(volume['size'], ret['size'])

    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    def test_negative_create_volume_with_fault_domains(
            self, mock_create_volume):
        volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_RAW])
        volume['metadata'].update(self.get_metadata())
        volume['metadata'].update(
            {constants.FSC_FD_IDS: 'fake_id1,fake_id2,fake_id3'})
        volume['metadata'].update({constants.FSC_FD_OP: 'mock_value'})
        mock_create_volume.return_value = success_uuid
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_volume(volume)

    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    def test_negative_create_volume_without_fault_domains_op(
            self, mock_create_volume):
        volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_RAW])
        volume['metadata'].update(self.get_metadata())
        volume['metadata'].update({constants.FSC_FD_IDS: 'fake_id1,fake_id2'})
        mock_create_volume.return_value = success_uuid
        ret = self.driver.create_volume(volume)
        self.assertIsNotNone(ret)
        self.assertEqual(volume['size'], ret['size'])

    def test_negative_create_volume_with_metadata(self):
        volume = self.get_volume()
        volume['metadata'].update(self.get_specs())
        volume['metadata'].update({constants.FSC_QOS_BAND: 'wrong value'})
        volume['metadata'].update(
            {constants.FSC_SPACE_ALLOCATION_POLICY: 'wrong value'})
        volume['metadata'].update({constants.FSC_COMPRESSION: 'wrong value'})
        volume['metadata'].update({constants.FSC_EC_SCHEME: 'wrong value'})
        volume['metadata'].update({constants.FSC_SNAPSHOTS: 'wrong value'})
        volume['metadata'].update({constants.FSC_BLK_SIZE: 'wrong value'})
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_volume(volume)

    def test_negative_encrypted_create_volume(self):
        volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        volume['metadata'].update(self.get_metadata())
        volume['metadata'].update({constants.FSC_KMIP_SECRET_KEY: 'fake key'})
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_volume(volume)

    def test_negative_create_volume_with_specs(self):
        volume = self.get_volume()
        mock_ret = self.get_specs()
        mock_ret.update({constants.FSC_QOS_BAND: 'wrong value'})
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[mock_ret, constants.VOLUME_TYPE_EC])
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_volume(volume)

    @mock.patch.object(rest_client.RestClient, 'create_volume')
    def test_negative_create_volume_api_exception(self, mock_create_volume):
        volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        mock_create_volume.side_effect = self.api_exception
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_volume(volume)

    @mock.patch.object(swagger_client.StorageApi, 'delete_volume')
    def test_delete_volume(self, mock_delete_volume):
        volume = self.get_volume()
        mock_delete_volume.return_value = success_response
        self.assertIsNone(self.driver.delete_volume(volume))

    @mock.patch.object(rest_client.RestClient, 'delete_volume')
    def test_negative_delete_volume_exception(self, mock_delete_volume):
        mock_volume = self.get_volume()
        mock_volume['provider_id'] = fake_constants.UUID1
        mock_delete_volume.side_effect = Exception("mock exception")
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.delete_volume(mock_volume)

    def test_negative_delete_volume_without_provider_id(self):
        volume = self.get_volume()
        volume['provider_id'] = None
        self.assertIsNone(self.driver.delete_volume(volume))

    def test_negative_delete_volume_without_provider_id_attr(self):
        volume = self.get_volume()
        del volume.provider_id
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.delete_volume(volume)

    @mock.patch.object(swagger_client.StorageApi, 'delete_volume')
    def test_negative_delete_volume_api_exception(self, mock_delete_volume):
        volume = self.get_volume()
        mock_delete_volume.side_effect = self.api_exception
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.delete_volume(volume)

    @mock.patch.object(swagger_client.StorageApi, 'get_volume')
    @mock.patch.object(swagger_client.StorageApi, 'attach_volume')
    @mock.patch.object(swagger_client.TopologyApi, 'get_host_id_list')
    @mock.patch.object(swagger_client.TopologyApi, 'get_host_info')
    @mock.patch.object(swagger_client.TopologyApi, 'get_hierarchical_topology')
    def test_initialize_connection(
            self, mock_get_topology, mock_get_host_info, mock_get_host_id_list,
            mock_attach_volume, mock_get_volume):
        mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        connector = self.get_connector()
        mock_attach_volume.return_value = success_uuid
        mock_get_volume.return_value = get_volume_details
        mock_get_host_id_list.return_value = get_host_id_list
        mock_get_host_info.return_value = get_host_info
        mock_get_topology.return_value = get_topology
        conn_info = self.driver.initialize_connection(mock_volume, connector)
        self.assertIsNotNone(conn_info)
        self.assertEqual(conn_info.get("driver_volume_type"), "nvmeof")
        self.assertIsNotNone(conn_info.get("data"))
        self.assertEqual(
            conn_info.get("data").get("vol_uuid"), fake_constants.UUID1)
        self.assertEqual(conn_info.get("data").get("host_nqn"),
                         self.get_connector().get("nqn"))
        '''Add more validation here'''

    def test_negative_initialize_connection_without_nqn(self):
        mock_volume = self.get_volume()
        connector = {}
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.initialize_connection(mock_volume, connector)

    def test_negative_initialize_connection_without_provider_id(self):
        mock_volume = {}
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        connector = self.get_connector()
        mock_volume["provider_id"] = None
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.initialize_connection(mock_volume, connector)

    @mock.patch.object(swagger_client.StorageApi, 'attach_volume')
    def test_negative_initialize_connection_api_exception(
            self, mock_attach_volume):
        mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        connector = self.get_connector()
        mock_attach_volume.side_effect = self.api_exception
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.initialize_connection(mock_volume, connector)

    @mock.patch.object(swagger_client.StorageApi, 'attach_volume')
    def test_initialize_connection_exception(self, mock_attach_volume):
        mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        connector = self.get_connector()
        mock_attach_volume.side_effect = Exception("mock exception")
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.initialize_connection(mock_volume, connector)

    @mock.patch.object(swagger_client.StorageApi, 'get_volume')
    @mock.patch.object(swagger_client.StorageApi, 'attach_volume')
    @mock.patch.object(swagger_client.TopologyApi, 'get_host_id_list')
    @mock.patch.object(swagger_client.TopologyApi, 'get_host_info')
    @mock.patch.object(swagger_client.TopologyApi, 'get_hierarchical_topology')
    def test_initialize_connection_iops_connection(
            self, mock_get_topology, mock_get_host_info, mock_get_host_id_list,
            mock_attach_volume, mock_get_volume):
        mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        connector = self.get_connector()
        mock_attach_volume.return_value = success_uuid
        mock_get_volume.return_value = get_volume_details
        mock_get_host_id_list.return_value = get_host_id_list
        mock_get_host_info.return_value = get_host_info
        mock_get_topology.return_value = get_topology
        connector[constants.FSC_IOPS_IMG_MIG] = True
        conn_info = self.driver.initialize_connection(mock_volume, connector)
        self.assertIsNotNone(conn_info)

    @mock.patch.object(swagger_client.StorageApi, 'get_volume')
    @mock.patch.object(swagger_client.StorageApi, 'attach_volume')
    @mock.patch.object(swagger_client.TopologyApi, 'get_host_id_list')
    @mock.patch.object(swagger_client.TopologyApi, 'get_host_info')
    @mock.patch.object(swagger_client.TopologyApi, 'get_hierarchical_topology')
    def test_initialize_connection_iops_migration(
            self, mock_get_topology, mock_get_host_info, mock_get_host_id_list,
            mock_attach_volume, mock_get_volume):
        mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        connector = self.get_connector()
        mock_attach_volume.return_value = success_uuid
        mock_get_volume.return_value = get_volume_details
        mock_get_host_id_list.return_value = get_host_id_list
        mock_get_host_info.return_value = get_host_info
        mock_get_topology.return_value = get_topology
        mock_volume['migration_status'] = "migrating"
        conn_info = self.driver.initialize_connection(mock_volume, connector)
        self.assertIsNotNone(conn_info)

    @mock.patch.object(swagger_client.StorageApi, 'get_volume')
    @mock.patch.object(swagger_client.StorageApi, 'delete_port')
    @mock.patch.object(swagger_client.TopologyApi, 'get_host_id_list')
    @mock.patch.object(swagger_client.TopologyApi, 'fetch_hosts_with_ids')
    def test_terminate_connection(
            self, mock_fetch_hosts_with_ids, mock_get_host_id_list,
            mock_detach_volume, mock_get_volume):
        mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        connector = self.get_connector()
        mock_get_volume.return_value = get_volume_details
        mock_get_host_id_list.return_value = get_host_id_list
        mock_fetch_hosts_with_ids.return_value = fetch_hosts_with_ids
        mock_detach_volume.return_value = success_uuid
        self.assertIsNone(self.driver.terminate_connection(
            mock_volume, connector))

    def test_negative_terminate_connection_without_provider_id(self):
        mock_volume = {}
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        connector = self.get_connector()
        mock_volume["provider_id"] = None
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.terminate_connection(mock_volume, connector)

    @mock.patch.object(swagger_client.StorageApi, 'get_volume')
    @mock.patch.object(swagger_client.StorageApi, 'delete_port')
    @mock.patch.object(swagger_client.TopologyApi, 'get_host_id_list')
    @mock.patch.object(swagger_client.TopologyApi, 'fetch_hosts_with_ids')
    def test_terminate_connection_force_detach(
            self, mock_fetch_hosts_with_ids, mock_get_host_id_list,
            mock_detach_volume, mock_get_volume):
        mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        mock_get_volume.return_value = get_volume_details
        mock_get_host_id_list.return_value = get_host_id_list
        mock_fetch_hosts_with_ids.return_value = fetch_hosts_with_ids
        mock_detach_volume.return_value = success_uuid
        connector = None
        self.assertIsNone(self.driver.terminate_connection(
            mock_volume, connector))

    @mock.patch.object(swagger_client.StorageApi, 'get_volume')
    def test_negative_terminate_connection_without_nqn(self, mock_get_volume):
        mock_volume = self.get_volume()
        mock_get_volume.return_value = get_volume_details
        connector = {}
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.terminate_connection(mock_volume, connector)

    @mock.patch.object(rest_client.RestClient, 'get_volume_detail')
    def test_negative_terminate_connection_without_port(self, mock_output):
        mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        connector = self.get_connector()
        mock_output.return_value = {'data': {'ports': None}}
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.terminate_connection(mock_volume, connector)

    @mock.patch.object(rest_client.RestClient, 'get_volume_detail')
    def test_negative_terminate_connection_with_invalid_port(
            self, mock_output):
        mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        connector = self.get_connector()
        mock_output.return_value = get_volume_details
        connector['nqn'] = "dummy_nqn"
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.terminate_connection(mock_volume, connector)

    @mock.patch.object(swagger_client.StorageApi, 'get_volume')
    @mock.patch.object(swagger_client.StorageApi, 'delete_port')
    def test_negative_terminate_connection_api_exception(
            self, mock_detach_volume, mock_get_volume):
        mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        connector = self.get_connector()
        mock_get_volume.return_value = get_volume_details
        mock_detach_volume.side_effect = self.api_exception
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.terminate_connection(mock_volume, connector)

    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    def test_create_volume_from_ec_snapshot(self, mock_create_volume):
        mock_snapshot = self.get_snapshot()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        mock_snapshot.volume = self.get_volume()
        mock_snapshot.provider_id = fake_constants.UUID1
        mock_volume2 = self.get_volume()
        mock_create_volume.return_value = success_uuid
        new_vol_ret = self.driver.create_volume_from_snapshot(
            mock_volume2, mock_snapshot)
        self.assertIsNotNone(new_vol_ret)
        self.assertEqual(mock_volume2['size'], new_vol_ret['size'])

    @mock.patch.object(rest_client.RestClient, 'create_volume')
    def test_create_volume_from_snapshot_exception(
            self, mock_get_volume_detail):
        mock_volume = self.get_volume()
        mock_snapshot = self.get_snapshot()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        mock_get_volume_detail.side_effect = Exception("mock exception")
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_volume_from_snapshot(mock_volume, mock_snapshot)

    @mock.patch.object(rest_client.RestClient, 'create_volume')
    def test_create_volume_from_snapshot_APIException(
            self, mock_create_volume):
        mock_volume = self.get_volume()
        mock_snapshot = self.get_snapshot()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        mock_create_volume.side_effect = self.api_exception
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_volume_from_snapshot(mock_volume, mock_snapshot)

    @mock.patch.object(swagger_client.StorageApi, 'delete_volume_copy_task')
    @mock.patch.object(swagger_client.StorageApi, 'delete_snapshot')
    @mock.patch.object(swagger_client.StorageApi, 'get_volume_copy_task')
    @mock.patch.object(swagger_client.StorageApi, 'create_volume_copy_task')
    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    @mock.patch.object(swagger_client.StorageApi, 'create_snapshot')
    def test_create_cloned_ec_volume(
            self, mock_create_snapshot, mock_create_volume,
            mock_create_volume_copy_task, mock_get_task, mock_delete_snapshot,
            mock_delete_task):
        target_mock_volume = self.get_volume()
        source_mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        mock_create_snapshot.return_value = success_uuid
        mock_create_volume.return_value = success_uuid
        mock_create_volume_copy_task.return_value = create_copy_task
        mock_get_task.return_value = get_task_success
        mock_delete_snapshot.return_value = success_response
        mock_delete_task.return_value = success_response
        self.assertIsNotNone(self.driver.create_cloned_volume(
            target_mock_volume, source_mock_volume))

    @mock.patch.object(swagger_client.StorageApi, 'delete_volume_copy_task')
    @mock.patch.object(swagger_client.StorageApi, 'delete_snapshot')
    @mock.patch.object(swagger_client.StorageApi, 'get_volume_copy_task')
    @mock.patch.object(swagger_client.StorageApi, 'create_volume_copy_task')
    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    @mock.patch.object(swagger_client.StorageApi, 'create_snapshot')
    def test_create_cloned_ec_volume_delete_task_exception(
            self, mock_create_snapshot, mock_create_volume,
            mock_create_volume_copy_task, mock_get_task, mock_delete_snapshot,
            mock_delete_task):
        target_mock_volume = self.get_volume()
        source_mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        mock_create_snapshot.return_value = success_uuid
        mock_create_volume.return_value = success_uuid
        mock_create_volume_copy_task.return_value = create_copy_task
        mock_get_task.return_value = get_task_success
        mock_delete_snapshot.return_value = success_response
        mock_delete_task.side_effect = self.api_exception
        self.assertIsNotNone(self.driver.create_cloned_volume(
            target_mock_volume, source_mock_volume))

    @mock.patch.object(swagger_client.StorageApi, 'get_volume_copy_task')
    @mock.patch.object(swagger_client.StorageApi, 'create_volume_copy_task')
    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    def test_create_cloned_ec_volume_get_task_api_exception(
            self, mock_create_volume, mock_create_volume_copy_task,
            mock_get_task):
        target_mock_volume = self.get_volume()
        source_mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        mock_create_volume.return_value = success_uuid
        mock_create_volume_copy_task.return_value = create_copy_task
        mock_get_task.side_effect = self.api_exception
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_cloned_volume(
                target_mock_volume, source_mock_volume)

    @mock.patch.object(rest_client.RestClient, 'copy_volume')
    @mock.patch.object(swagger_client.StorageApi, 'create_volume')
    def test_create_cloned_ec_volume_copy_task_exception(
            self, mock_create_volume, mock_create_volume_copy_task):
        target_mock_volume = self.get_volume()
        source_mock_volume = self.get_volume()
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        mock_create_volume.return_value = success_uuid
        mock_create_volume_copy_task.side_effect = Exception("mock exception")
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_cloned_volume(
                target_mock_volume, source_mock_volume)

    def test_create_clone_in_use_volume(self):
        target_mock_volume = self.get_volume()
        source_mock_volume = self.get_volume()
        source_mock_volume['attach_status'] = "attached"
        self.driver._get_volume_type_extra_specs = mock.Mock(
            return_value=[{}, constants.VOLUME_TYPE_EC])
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_cloned_volume(
                target_mock_volume, source_mock_volume)

    @mock.patch.object(swagger_client.StorageApi, 'create_snapshot')
    def test_create_snapshot(self, mock_create_snapshot):
        mock_volume = self.get_volume()
        snapshot = self.get_snapshot()
        snapshot['volume'] = mock_volume
        mock_create_snapshot.return_value = success_uuid
        ret = self.driver.create_snapshot(snapshot)
        self.assertIsNotNone(ret)

    def test_negative_create_snapshot_without_provider_id(self):
        mock_volume = self.get_volume()
        snapshot = self.get_snapshot()
        snapshot['volume'] = mock_volume
        snapshot['volume']['provider_id'] = None
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_snapshot(snapshot)

    def test_negative_create_snapshot_without_provider_id_attr(self):
        mock_volume = self.get_volume()
        snapshot = self.get_snapshot()
        snapshot.volume = mock_volume
        del snapshot.volume.provider_id
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_snapshot(snapshot)

    @mock.patch.object(rest_client.RestClient, 'create_snapshot')
    def test_negative_create_snapshot_exception(self, mock_create_snapshot):
        snapshot = self.get_snapshot()
        mock_volume = self.get_volume()
        mock_volume['provider_id'] = fake_constants.UUID1
        snapshot['volume'] = mock_volume
        mock_create_snapshot.side_effect = Exception("mock exception")
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_snapshot(snapshot)

    @mock.patch.object(rest_client.RestClient, 'create_snapshot')
    def test_negative_create_snapshot_api_exception(
            self, mock_create_snapshot):
        mock_volume = self.get_volume()
        snapshot = self.get_snapshot()
        snapshot.volume = mock_volume
        mock_create_snapshot.side_effect = self.api_exception
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.create_snapshot(snapshot)

    @mock.patch.object(swagger_client.StorageApi, 'delete_snapshot')
    def test_delete_snapshot(self, mock_delete_snapshot):
        mock_volume = self.get_volume()
        snapshot = self.get_snapshot()
        snapshot['volume'] = mock_volume
        mock_delete_snapshot.return_value = success_response
        self.assertIsNone(self.driver.delete_snapshot(snapshot))

    def test_negative_delete_snapshot_without_provider_id(self):
        snapshot = self.get_snapshot()
        snapshot['provider_id'] = None
        self.assertIsNone(self.driver.delete_snapshot(snapshot))

    def test_negative_delete_snapshot_without_provider_id_attr(self):
        mock_volume = self.get_volume()
        snapshot = self.get_snapshot()
        snapshot.volume = mock_volume
        del snapshot.provider_id
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.delete_snapshot(snapshot)

    @mock.patch.object(rest_client.RestClient, 'delete_snapshot')
    def test_negative_delete_snapshot_exception(self, mock_delete_snapshot):
        snapshot = self.get_snapshot()
        mock_volume = self.get_volume()
        mock_volume['provider_id'] = fake_constants.UUID1
        snapshot['volume'] = mock_volume
        mock_delete_snapshot.side_effect = Exception("mock exception")
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.delete_snapshot(snapshot)

    @mock.patch.object(rest_client.RestClient, 'delete_snapshot')
    def test_negative_delete_snapshot_api_exception(
            self, mock_delete_snapshot):
        mock_volume = self.get_volume()
        snapshot = self.get_snapshot()
        snapshot['volume'] = mock_volume
        mock_delete_snapshot.side_effect = self.api_exception
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.delete_snapshot(snapshot)

    @mock.patch.object(swagger_client.StorageApi, 'update_volume')
    def test_extend_ec_volume_success(self, mock_update_volume):
        mock_volume = self.get_volume()
        new_size = 100
        mock_update_volume.return_value = success_response
        ret = self.driver.extend_volume(mock_volume, new_size)
        self.assertIsNone(ret)

    def test_negative_extend_volume_without_provider_id(self):
        mock_volume = self.get_volume()
        new_size = 100
        mock_volume['provider_id'] = None
        self.assertIsNone(self.driver.extend_volume(mock_volume, new_size))

    def test_negative_extend_volume__without_provider_id_attr(self):
        mock_volume = self.get_volume()
        new_size = 100
        del mock_volume.provider_id
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.extend_volume(mock_volume, new_size)

    @mock.patch.object(swagger_client.StorageApi, 'update_volume')
    def test_extend_volume_exception(self, mock_update_volume):
        mock_volume = self.get_volume()
        new_size = 100
        mock_update_volume.side_effect = Exception("mock exception")
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.extend_volume(mock_volume, new_size)

    @mock.patch.object(swagger_client.StorageApi, 'update_volume')
    def test_extend_volume_api_exception(self, mock_update_volume):
        mock_volume = self.get_volume()
        new_size = 100
        mock_update_volume.side_effect = self.api_exception
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.extend_volume(mock_volume, new_size)

    @mock.patch.object(swagger_client.StorageApi, 'update_volume')
    def test_update_migrated_volume_success(self, mock_rename_volume):
        source_mock_volume = self.get_volume()
        destination_mock_volume = self.get_volume()
        source_mock_volume['host'] = "FSC1"
        destination_mock_volume['host'] = "FSC1"
        mock_rename_volume.return_value = success_response
        self.assertIsNotNone(self.driver.update_migrated_volume(
            self.context, source_mock_volume, destination_mock_volume,
            fields.VolumeStatus.AVAILABLE))

    @mock.patch.object(swagger_client.StorageApi, 'update_volume')
    def test_update_migrated_volume_without_destination_provider_id(
            self, mock_rename_volume):
        source_mock_volume = self.get_volume()
        destination_mock_volume = self.get_volume()
        destination_mock_volume['provider_id'] = None
        mock_rename_volume.side_effect = success_response
        self.assertIsNotNone(self.driver.update_migrated_volume(
            self.context, source_mock_volume, destination_mock_volume,
            fields.VolumeStatus.AVAILABLE))

    @mock.patch.object(swagger_client.StorageApi, 'update_volume')
    def test_update_migrated_volume_without_source_provider_id(
            self, mock_rename_volume):
        source_mock_volume = self.get_volume()
        destination_mock_volume = self.get_volume()
        source_mock_volume['provider_id'] = None
        mock_rename_volume.return_value = success_response
        self.assertIsNotNone(self.driver.update_migrated_volume(
            self.context, source_mock_volume, destination_mock_volume,
            fields.VolumeStatus.AVAILABLE))

    @mock.patch.object(rest_client.RestClient, 'rename_volume')
    def test_update_migrated_volume_api_exception(self, mock_rename_volume):
        source_mock_volume = self.get_volume()
        destination_mock_volume = self.get_volume()
        mock_rename_volume[0].side_effect = self.api_exception
        mock_rename_volume[1].return_value = success_response
        self.assertIsNotNone(self.driver.update_migrated_volume(
            self.context, source_mock_volume, destination_mock_volume,
            fields.VolumeStatus.AVAILABLE))

    @mock.patch.object(swagger_client.StorageApi, 'update_volume')
    def test_update_migrated_volume_backend_exception(
            self, mock_rename_volume):
        source_mock_volume = self.get_volume()
        destination_mock_volume = self.get_volume()
        source_mock_volume['provider_id'] = None
        mock_rename_volume.side_effect = self.api_exception
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.update_migrated_volume(
                self.context, source_mock_volume, destination_mock_volume,
                fields.VolumeStatus.AVAILABLE)

    @mock.patch.object(swagger_client.StorageApi, 'update_volume')
    def test_update_migrated_volume_exception(self, mock_rename_volume):
        source_mock_volume = self.get_volume()
        destination_mock_volume = self.get_volume()
        source_mock_volume['provider_id'] = None
        mock_rename_volume.side_effect = Exception("mock exception")
        with self.assertRaises(exception.VolumeBackendAPIException):
            self.driver.update_migrated_volume(
                self.context, source_mock_volume, destination_mock_volume,
                fields.VolumeStatus.AVAILABLE)

    @mock.patch.object(volume.driver.BaseVD, '_detach_volume')
    @mock.patch.object(image_utils, 'upload_volume')
    @mock.patch.object(volume.driver.BaseVD, '_attach_volume')
    @mock.patch.object(volume_utils, 'brick_get_connector_properties')
    def test_copy_volume_to_image(
            self, mock_get_connector, mock_attach_volume,
            mock_upload_volume, mock_detach):
        mock_volume = self.get_volume()
        image_service = fake_image.FakeImageService()
        self.configuration.use_multipath_for_image_xfer = False
        self.configuration.enforce_multipath_for_image_xfer = False
        local_path = 'dev/sda'
        mock_get_connector.return_value = {}
        attach_info = {'device': {'path': local_path},
                       'conn': {'driver_volume_type': 'nvme',
                                'data': {}, }}
        mock_attach_volume.return_value = [attach_info, mock_volume]
        mock_upload_volume.return_value = None
        mock_detach.return_value = None
        self.driver.wait_for_device = mock.Mock(
            return_value=True)
        self.assertIsNone(
            self.driver.copy_volume_to_image(
                self.context, mock_volume, image_service,
                fake_constants.IMAGE_ID))

    @mock.patch.object(volume.driver.BaseVD, '_detach_volume')
    @mock.patch.object(image_utils, 'fetch_to_raw')
    @mock.patch.object(volume.driver.BaseVD, '_attach_volume')
    @mock.patch.object(volume_utils, 'brick_get_connector_properties')
    def test_copy_image_to_volume(
            self, mock_get_connector, mock_attach_volume,
            mock_fetch_to_raw, mock_detach):
        mock_volume = self.get_volume()
        image_service = fake_image.FakeImageService()
        self.configuration.use_multipath_for_image_xfer = False
        self.configuration.enforce_multipath_for_image_xfer = False
        self.configuration.volume_dd_blocksize = 8
        local_path = 'dev/sda'
        mock_get_connector.return_value = {}
        attach_info = {'device': {'path': local_path},
                       'conn': {'driver_volume_type': 'nvme',
                                'data': {}, }}
        mock_attach_volume.return_value = [attach_info, mock_volume]
        mock_fetch_to_raw.return_value = None
        mock_detach.return_value = None
        self.driver.wait_for_device = mock.Mock(
            return_value=True)
        self.assertIsNone(
            self.driver.copy_image_to_volume(
                self.context, mock_volume, image_service,
                fake_constants.IMAGE_ID))


if __name__ == '__main__':
    unittest.main()
