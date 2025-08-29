# Copyright (c) 2025 NetApp, Inc. All rights reserved.
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

import copy
from unittest import mock
from unittest.mock import patch
import uuid

import ddt

from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.netapp.dataontap.client import (
    fakes as fake_client)
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as fake
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap.client import client_cmode_rest
from cinder.volume.drivers.netapp.dataontap.client.client_cmode_rest_asar2\
    import RestClientASAr2
from cinder.volume.drivers.netapp import utils as netapp_utils


CONNECTION_INFO = {'hostname': 'hostname',
                   'transport_type': 'https',
                   'port': 443,
                   'username': 'admin',
                   'password': 'passw0rd',
                   'vserver': 'fake_vserver',
                   'ssl_cert_path': 'fake_ca',
                   'api_trace_pattern': 'fake_regex',
                   'private_key_file': 'fake_private_key.pem',
                   'certificate_file': 'fake_cert.pem',
                   'ca_certificate_file': 'fake_ca_cert.crt',
                   'certificate_host_validation': 'False',
                   'is_disaggregated': 'True',  # ASA r2 is disaggregated
                   }


@ddt.ddt
class NetAppRestCmodeASAr2ClientTestCase(test.TestCase):

    def setUp(self):
        super(NetAppRestCmodeASAr2ClientTestCase, self).setUp()

        # Setup Client mocks
        self.mock_object(client_cmode.Client, '_init_ssh_client')
        # store the original reference so we can call it later in
        # test__get_cluster_nodes_info
        self.original_get_cluster_nodes_info = (
            client_cmode.Client._get_cluster_nodes_info)
        self.mock_object(client_cmode.Client, '_get_cluster_nodes_info',
                         return_value=fake.HYBRID_SYSTEM_NODES_INFO)
        self.mock_object(client_cmode.Client, 'get_ontap_version',
                         return_value=(9, 16, 1))
        self.mock_object(client_cmode.Client,
                         'get_ontapi_version',
                         return_value=(0, 0))

        # Setup RestClient mocks
        self.mock_object(client_cmode_rest.RestClient, '_init_ssh_client')

        self.original_get_cluster_nodes_info = (
            client_cmode_rest.RestClient._get_cluster_nodes_info)

        if not hasattr(client_cmode_rest.RestClient,
                       '_get_cluster_nodes_info'):
            setattr(client_cmode_rest.RestClient,
                    '_get_cluster_nodes_info',
                    None)
        self.original_get_cluster_nodes_info = (
            client_cmode_rest.RestClient._get_cluster_nodes_info)

        self.mock_object(client_cmode_rest.RestClient,
                         '_get_cluster_nodes_info',
                         return_value=fake.HYBRID_SYSTEM_NODES_INFO)
        self.mock_object(client_cmode_rest.RestClient, 'get_ontap_version',
                         return_value=(9, 16, 1))

        # Setup ASA r2 specific mocks
        self.mock_object(RestClientASAr2, '_init_ssh_client')
        self.mock_object(RestClientASAr2, '_get_cluster_nodes_info',
                         return_value=fake.HYBRID_SYSTEM_NODES_INFO)
        self.mock_object(RestClientASAr2, 'get_ontap_version',
                         return_value=(9, 16, 1))

        with mock.patch.object(RestClientASAr2,
                               'get_ontap_version',
                               return_value=(9, 16, 1)):
            self.client = RestClientASAr2(**CONNECTION_INFO)

        self.client.ssh_client = mock.MagicMock()
        self.client.connection = mock.MagicMock()
        self.connection = self.client.connection

        self.vserver = CONNECTION_INFO['vserver']
        self.fake_volume = str(uuid.uuid4())
        self.fake_lun = str(uuid.uuid4())

    def _mock_api_error(self, code='fake'):
        return mock.Mock(side_effect=netapp_api.NaApiError(code=code))

    def test_initialization(self):
        """Test ASA r2 client initialization."""
        self.assertIsInstance(self.client, RestClientASAr2)
        self.assertIsInstance(self.client,
                              client_cmode_rest.RestClient)

    def test_init_asar2_features(self):
        """Test ASA r2 specific features initialization."""
        # Test that _init_asar2_features is called during initialization
        with mock.patch.object(RestClientASAr2,
                               '_init_asar2_features') as mock_init:
            with mock.patch.object(RestClientASAr2,
                                   'get_ontap_version',
                                   return_value=(9, 16, 1)):
                RestClientASAr2(**CONNECTION_INFO)

                mock_init.assert_called_once()

    @ddt.data(True, False)
    def test_get_ontapi_version(self, cached):
        """Test that ASA r2 returns (0, 0) for ONTAPI version."""
        result = self.client.get_ontapi_version(cached=cached)
        expected = (0, 0)
        self.assertEqual(expected, result)

    def test_getattr_missing_method(self):
        """Test __getattr__ behavior for missing methods."""
        result = getattr(self.client, 'nonexistent_method', None)
        self.assertIsNone(result)

    def test_send_request_inherits_from_parent(self):
        """Test that send_request inherits behavior from parent class."""
        expected = 'fake_response'
        mock_get_records = self.mock_object(
            self.client, 'get_records',
            mock.Mock(return_value=expected))

        res = self.client.send_request(
            fake_client.FAKE_ACTION_ENDPOINT, 'get',
            body=fake_client.FAKE_BODY,
            query=fake_client.FAKE_HTTP_QUERY, enable_tunneling=False)

        self.assertEqual(expected, res)
        mock_get_records.assert_called_once_with(
            fake_client.FAKE_ACTION_ENDPOINT,
            fake_client.FAKE_HTTP_QUERY, False, 10000)

    def test_send_request_post_inherits_from_parent(self):
        """Test that send_request POST inherits behavior from parent class."""
        expected = (201, 'fake_response')
        mock_invoke = self.mock_object(
            self.client.connection, 'invoke_successfully',
            mock.Mock(return_value=expected))

        res = self.client.send_request(
            fake_client.FAKE_ACTION_ENDPOINT, 'post',
            body=fake_client.FAKE_BODY,
            query=fake_client.FAKE_HTTP_QUERY, enable_tunneling=False)

        self.assertEqual(expected[1], res)
        mock_invoke.assert_called_once_with(
            fake_client.FAKE_ACTION_ENDPOINT, 'post',
            body=fake_client.FAKE_BODY,
            query=fake_client.FAKE_HTTP_QUERY, enable_tunneling=False)

    @ddt.data(
        {'enable_tunneling': True},
        {'enable_tunneling': False}
    )
    @ddt.unpack
    def test_get_records_inherits_from_parent(self, enable_tunneling):
        """Test that get_records inherits behavior from parent class."""
        api_responses = [
            (200, fake_client.VOLUME_GET_ITER_RESPONSE_REST_PAGE),
            (200, fake_client.VOLUME_GET_ITER_RESPONSE_REST_PAGE),
            (200, fake_client.VOLUME_GET_ITER_RESPONSE_REST_LAST_PAGE),
        ]

        self.mock_object(
            self.client.connection, 'invoke_successfully',
            side_effect=copy.deepcopy(api_responses))

        query = {
            'fields': 'name'
        }

        result = self.client.get_records(
            '/storage/volumes/', query=query,
            enable_tunneling=enable_tunneling,
            max_page_length=10)

        num_records = result['num_records']
        self.assertEqual(28, num_records)
        self.assertEqual(28, len(result['records']))

        expected_records = []
        expected_records.extend(api_responses[0][1]['records'])
        expected_records.extend(api_responses[1][1]['records'])
        expected_records.extend(api_responses[2][1]['records'])

        self.assertEqual(expected_records, result['records'])

    def test_send_ems_log_message_inherits_from_parent(self):
        """Test send_ems_log_message inherits behavior"""
        message_dict = {
            'computer-name': '25-dev-vm',
            'event-source': 'Cinder driver NetApp_iSCSI_ASAr2_direct',
            'app-version': 'dummy app version',
            'category': 'provisioning',
            'log-level': '5',
            'auto-support': 'false',
            'event-id': '1',
            'event-description':
                '{"pools": {"vserver": "vserver_name",'
                + '"aggregates": [], "flexvols": ["flexvol_01"]}}'
        }

        body = {
            'computer_name': message_dict['computer-name'],
            'event_source': message_dict['event-source'],
            'app_version': message_dict['app-version'],
            'category': message_dict['category'],
            'severity': 'notice',
            'autosupport_required': message_dict['auto-support'] == 'true',
            'event_id': message_dict['event-id'],
            'event_description': message_dict['event-description'],
        }

        self.mock_object(self.client, '_get_ems_log_destination_vserver',
                         return_value='vserver_name')
        self.mock_object(self.client, 'send_request')

        self.client.send_ems_log_message(message_dict)

        self.client.send_request.assert_called_once_with(
            '/support/ems/application-logs', 'post', body=body)

    def test_inheritance_all_parent_methods_available(self):
        """Test that ASA r2 client has access to all parent methods."""
        # Test that common parent methods are available
        parent_methods = [
            'send_request', 'get_records', 'send_ems_log_message'
        ]

        for method_name in parent_methods:
            self.assertTrue(hasattr(self.client, method_name),
                            f"Method {method_name} should be available")
            self.assertTrue(callable(getattr(self.client, method_name)),
                            f"Method {method_name} should be callable")

    def test_asar2_specific_ontapi_not_supported(self):
        """Test that ASA r2 specifically doesn't support ONTAPI."""
        # This is a key differentiator for ASA r2
        result = self.client.get_ontapi_version()
        self.assertEqual((0, 0), result)

        # No change for cached version
        result_cached = self.client.get_ontapi_version(cached=True)
        self.assertEqual((0, 0), result_cached)

    def test_disaggregated_platform_connection_info(self):
        """Test ASA r2 client works with disaggregated platform settings."""
        # Verify the connection info includes disaggregated flag
        self.assertEqual('True', CONNECTION_INFO['is_disaggregated'])

        # Test that client can be initialized with disaggregated settings
        disaggregated_info = CONNECTION_INFO.copy()
        disaggregated_info['is_disaggregated'] = 'True'

        with mock.patch.object(RestClientASAr2, 'get_ontap_version',
                               return_value=(9, 18, 1)):
            client = RestClientASAr2(**disaggregated_info)
            self.assertIsInstance(client, RestClientASAr2)

    def test_get_cluster_info_success(self):
        """Test successful cluster info retrieval."""
        expected_response = fake_client.GET_CLUSTER_INFO_RESPONSE_REST

        self.mock_object(self.client, 'send_request',
                         return_value=expected_response)

        result = self.client.get_cluster_info()

        expected_query = {'fields': 'name,disaggregated'}
        self.client.send_request.assert_called_once_with(
            '/cluster', 'get', query=expected_query, enable_tunneling=False)
        self.assertEqual(expected_response, result)

    def test_get_cluster_info_exception(self):
        """Test exception handling during cluster info retrieval."""
        self.mock_object(self.client, 'send_request',
                         side_effect=Exception("API error"))

        result = self.client.get_cluster_info()

        expected_query = {'fields': 'name,disaggregated'}
        self.client.send_request.assert_called_once_with(
            '/cluster', 'get', query=expected_query, enable_tunneling=False)
        self.assertIsNone(result)

    def test_get_cluster_info_empty_response(self):
        """Test cluster info retrieval with empty response."""
        self.mock_object(self.client, 'send_request',
                         return_value={})

        result = self.client.get_cluster_info()

        expected_query = {'fields': 'name,disaggregated'}
        self.client.send_request.assert_called_once_with(
            '/cluster', 'get', query=expected_query, enable_tunneling=False)
        self.assertEqual({}, result)

    def test_get_cluster_info_netapp_api_error(self):
        """Test NetApp API error handling during cluster info retrieval."""
        self.mock_object(self.client, 'send_request',
                         side_effect=netapp_api.NaApiError("NetApp API error"))

        result = self.client.get_cluster_info()

        expected_query = {'fields': 'name,disaggregated'}
        self.client.send_request.assert_called_once_with(
            '/cluster', 'get', query=expected_query, enable_tunneling=False)
        self.assertIsNone(result)

    def test_get_cluster_capacity_success(self):
        """Test successful cluster capacity retrieval."""
        expected_response = fake_client.GET_CLUSTER_CAPACITY_RESPONSE_REST

        self.mock_object(self.client, 'send_request',
                         return_value=expected_response)

        result = self.client.get_cluster_capacity()

        expected_query =\
            {'fields': 'block_storage.size,block_storage.available'}
        self.client.send_request.assert_called_once_with(
            '/storage/cluster', 'get',
            query=expected_query, enable_tunneling=False)

        expected_capacity = {
            'size-total': float(expected_response['block_storage']['size']),
            'size-available':
                float(expected_response['block_storage']['available'])
        }
        self.assertEqual(expected_capacity, result)

    def test_get_cluster_capacity_no_response(self):
        """Test cluster capacity retrieval with no response."""
        self.mock_object(self.client, 'send_request',
                         return_value=None)

        result = self.client.get_cluster_capacity()

        expected_query =\
            {'fields': 'block_storage.size,block_storage.available'}
        self.client.send_request.assert_called_once_with(
            '/storage/cluster', 'get',
            query=expected_query, enable_tunneling=False)
        self.assertEqual({}, result)

    def test_get_cluster_capacity_missing_block_storage(self):
        """Test cluster capacity retrieval with missing block_storage."""
        response = {'some_other_field': 'value'}

        self.mock_object(self.client, 'send_request',
                         return_value=response)

        result = self.client.get_cluster_capacity()

        expected_query =\
            {'fields': 'block_storage.size,block_storage.available'}
        self.client.send_request.assert_called_once_with(
            '/storage/cluster', 'get',
            query=expected_query, enable_tunneling=False)

        expected_capacity = {
            'size-total': 0.0,
            'size-available': 0.0
        }
        self.assertEqual(expected_capacity, result)

    def test_get_cluster_capacity_partial_block_storage(self):
        """Test cluster capacity retrieval with partial block_storage."""
        response = {
            'block_storage': {
                'size': 1000000000,
                # missing 'available' field
            }
        }

        self.mock_object(self.client, 'send_request',
                         return_value=response)

        result = self.client.get_cluster_capacity()

        expected_query =\
            {'fields': 'block_storage.size,block_storage.available'}
        self.client.send_request.assert_called_once_with(
            '/storage/cluster', 'get',
            query=expected_query, enable_tunneling=False)

        expected_capacity = {
            'size-total': 1000000000.0,
            'size-available': 0.0
        }
        self.assertEqual(expected_capacity, result)

    def test_get_cluster_capacity_exception(self):
        """Test exception handling during cluster capacity retrieval."""
        self.mock_object(self.client, 'send_request',
                         side_effect=Exception("API error"))

        self.assertRaises(netapp_utils.NetAppDriverException,
                          self.client.get_cluster_capacity)

        expected_query =\
            {'fields': 'block_storage.size,block_storage.available'}
        self.client.send_request.assert_called_once_with(
            '/storage/cluster', 'get',
            query=expected_query, enable_tunneling=False)

    def test_get_cluster_capacity_netapp_api_error(self):
        """Test NetApp API error handling during cluster capacity retrieval."""
        self.mock_object(self.client, 'send_request',
                         side_effect=netapp_api.NaApiError("NetApp API error"))

        self.assertRaises(netapp_utils.NetAppDriverException,
                          self.client.get_cluster_capacity)

        expected_query =\
            {'fields': 'block_storage.size,block_storage.available'}
        self.client.send_request.assert_called_once_with(
            '/storage/cluster', 'get', query=expected_query,
            enable_tunneling=False)

    def test_get_aggregate_disk_types_success(self):
        """Test successful aggregate disk types retrieval."""
        expected_response =\
            fake_client.GET_AGGREGATE_STORAGE_TYPES_RESPONSE_REST

        self.mock_object(self.client, 'send_request',
                         return_value=expected_response)

        result = self.client.get_aggregate_disk_types()

        expected_query = {'fields': 'name,block_storage.storage_type'}
        self.client.send_request.assert_called_once_with(
            '/storage/aggregates', 'get', query=expected_query,
            enable_tunneling=False)
        # Should return array of storage types
        self.assertEqual(['ssd'], result)

    def test_get_aggregate_disk_types_multiple_records(self):
        """Test aggregate disk types retrieval with multiple records."""
        expected_response =\
            fake_client.GET_AGGREGATE_STORAGE_TYPES_MULTIPLE_RESPONSE_REST

        self.mock_object(self.client, 'send_request',
                         return_value=expected_response)

        result = self.client.get_aggregate_disk_types()

        expected_query = {'fields': 'name,block_storage.storage_type'}
        self.client.send_request.assert_called_once_with(
            '/storage/aggregates', 'get', query=expected_query,
            enable_tunneling=False)
        # Should return array with all storage types including duplicates
        self.assertEqual(['ssd', 'ssd'], result)

    def test_get_aggregate_disk_types_empty_records(self):
        """Test aggregate disk types retrieval with empty records."""
        expected_response =\
            fake_client.GET_AGGREGATE_STORAGE_TYPES_EMPTY_RESPONSE_REST

        self.mock_object(self.client, 'send_request',
                         return_value=expected_response)

        result = self.client.get_aggregate_disk_types()

        expected_query = {'fields': 'name,block_storage.storage_type'}
        self.client.send_request.assert_called_once_with(
            '/storage/aggregates', 'get', query=expected_query,
            enable_tunneling=False)
        self.assertIsNone(result)

    def test_get_aggregate_disk_types_missing_block_storage(self):
        """Test aggregate disk types retrieval with missing block_storage."""
        response = {
            "records": [
                {
                    "uuid": "3e5e2865-af43-4d82-a808-8a7222cf0369",
                    "name": "dataFA_2_p0_i1",
                    # missing block_storage field
                }
            ],
            "num_records": 1
        }

        self.mock_object(self.client, 'send_request',
                         return_value=response)

        result = self.client.get_aggregate_disk_types()

        expected_query = {'fields': 'name,block_storage.storage_type'}
        self.client.send_request.assert_called_once_with(
            '/storage/aggregates', 'get', query=expected_query,
            enable_tunneling=False)

        self.assertEqual([], result)

    def test_get_aggregate_disk_types_missing_storage_type(self):
        """Test aggregate disk types retrieval with missing storage_type."""
        response = {
            "records": [
                {
                    "uuid": "3e5e2865-af43-4d82-a808-8a7222cf0369",
                    "name": "dataFA_2_p0_i1",
                    "block_storage": {
                        "primary": {
                            "disk_class": "solid_state",
                            "disk_type": "ssd"
                        }
                        # missing storage_type field
                    }
                }
            ],
            "num_records": 1
        }

        self.mock_object(self.client, 'send_request',
                         return_value=response)

        result = self.client.get_aggregate_disk_types()

        expected_query = {'fields': 'name,block_storage.storage_type'}
        self.client.send_request.assert_called_once_with(
            '/storage/aggregates', 'get', query=expected_query,
            enable_tunneling=False)

        self.assertEqual([], result)

    def test_get_aggregate_disk_types_netapp_api_error(self):
        """Test NetApp API error handling."""
        self.mock_object(self.client, 'send_request',
                         side_effect=netapp_api.NaApiError("NetApp API error"))

        self.assertRaises(netapp_utils.NetAppDriverException,
                          self.client.get_aggregate_disk_types)

        expected_query = {'fields': 'name,block_storage.storage_type'}
        self.client.send_request.assert_called_once_with(
            '/storage/aggregates', 'get', query=expected_query,
            enable_tunneling=False)

    def test_get_performance_counter_info_not_supported(self):
        """Performance counter info raises NetAppDriverException."""
        self.assertRaises(netapp_utils.NetAppDriverException,
                          self.client.get_performance_counter_info,
                          'system', 'cpu_busy')

    def test_get_performance_instance_uuids_not_supported(self):
        """Performance instance UUIDs raises NetAppDriverException."""
        self.assertRaises(netapp_utils.NetAppDriverException,
                          self.client.get_performance_instance_uuids,
                          'system', 'node1')

    def test_get_performance_counters_not_supported(self):
        """Performance counters raises NetAppDriverException."""
        self.assertRaises(netapp_utils.NetAppDriverException,
                          self.client.get_performance_counters,
                          'system', ['uuid1'], ['cpu_busy'])

    def test_create_lun(self):
        metadata = copy.deepcopy(fake_client.LUN_GET_ITER_RESULT[0])
        name = fake.LUN_NAME
        size = 2048
        initial_size = size
        qos_policy_group_is_adaptive = False

        self.mock_object(self.client, '_validate_qos_policy_group')
        self.mock_object(self.client, 'send_request')

        body = {
            'name': name,
            'space.size': str(initial_size),
            'os_type': metadata['OsType'],
            'qos_policy.name': fake.QOS_POLICY_GROUP_NAME
        }

        self.client.create_lun(
            fake.VOLUME_NAME, fake.LUN_NAME, size, metadata,
            qos_policy_group_name=fake.QOS_POLICY_GROUP_NAME,
            qos_policy_group_is_adaptive=qos_policy_group_is_adaptive)

        self.client.send_request.assert_called_once_with(
            '/storage/luns', 'post', body=body)

    @patch('cinder.volume.drivers.netapp.dataontap.client.'
           'client_cmode_rest_asar2.RestClientASAr2.send_request')
    def test_create_lun_handles_qos_policy(self, mock_send_request):
        mock_send_request.return_value = None

        self.client.create_lun(fake_client.VOLUME_NAME,
                               fake_client.LUN_NAME,
                               1024,
                               {"OsType": "linux"},
                               qos_policy_group_name=(
                                   fake.QOS_POLICY_GROUP_NAME),
                               )

        mock_send_request.assert_called_once_with(
            '/storage/luns', 'post', body={
                'name': fake_client.LUN_NAME.replace("-", "_"),
                'space.size': '1024',
                'os_type': 'linux',
                'qos_policy.name': fake.QOS_POLICY_GROUP_NAME
            }
        )

    @patch('cinder.volume.drivers.netapp.dataontap.client.'
           'client_cmode_rest_asar2.RestClientASAr2.send_request')
    def test_create_lun_raises_error_on_failure(self, mock_send_request):
        mock_send_request.side_effect = netapp_api.NaApiError
        self.assertRaises(
            netapp_api.NaApiError,
            self.client.create_lun,
            fake.VOLUME_NAME, fake.LUN_NAME, 1024, {"OsType": "linux"}
        )

    @patch('cinder.volume.drivers.netapp.dataontap.client.'
           'client_cmode_rest_asar2.RestClientASAr2.send_request')
    def test_destroy_lun(self, mock_send_request):
        mock_send_request.return_value = None

        self.client.destroy_lun(fake.LUN_PATH, force=True)
        lun_name = self.client._get_backend_lun_or_namespace(
            fake.LUN_PATH
        )

        mock_send_request.assert_called_once_with(
            '/storage/luns/', 'delete', query={
                'name': lun_name,
                'allow_delete_while_mapped': 'true',
            }
        )

    @patch('cinder.volume.drivers.netapp.dataontap.client.'
           'client_cmode_rest_asar2.RestClientASAr2.send_request')
    def test_destroy_lun_handles_non_forced_deletion(self, mock_send_request):
        mock_send_request.return_value = None

        self.client.destroy_lun(fake.LUN_PATH, force=False)
        lun_name = self.client._get_backend_lun_or_namespace(
            fake.LUN_PATH
        )

        mock_send_request.assert_called_once_with(
            '/storage/luns/', 'delete', query={
                'name': lun_name,
            }
        )

    @patch('cinder.volume.drivers.netapp.dataontap.client.'
           'client_cmode_rest_asar2.RestClientASAr2.send_request')
    def test_destroy_lun_raises_error_on_failure(self, mock_send_request):
        mock_send_request.side_effect = netapp_api.NaApiError
        self.assertRaises(
            netapp_api.NaApiError,
            self.client.destroy_lun,
            fake.LUN_PATH, force=True,
        )

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest_asar2.RestClientASAr2.send_request')
    def test_create_namespace(self, mock_send_request):
        self.client.create_namespace(fake_client.VOLUME_NAME,
                                     fake_client.NAMESPACE_NAME,
                                     2048, {'OsType': 'linux'}
                                     )

        mock_send_request.assert_called_once_with(
            '/storage/namespaces', 'post', body={
                'name': fake_client.NAMESPACE_NAME,
                'space.size': '2048',
                'os_type': 'linux'
            }
        )

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest_asar2.RestClientASAr2.send_request')
    def test_destroy_namespace(self, mock_send_request):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=fake.NAMESPACE_NAME)
        self.client.destroy_namespace(fake.PATH_NAMESPACE, force=True)
        mock_send_request.assert_called_once_with(
            '/storage/namespaces', 'delete', query={
                'name': fake.NAMESPACE_NAME,
                'svm': self.client.vserver,
                'allow_delete_while_mapped': 'true'
            }
        )

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest.RestClient.map_lun')
    def test_map_lun(self, mock_super_map_lun):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=fake.LUN_NAME
        )
        mock_super_map_lun.return_value = 'result'

        result = self.client.map_lun(fake.LUN_PATH, 'igroup1', 42)

        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            fake.LUN_PATH
        )
        mock_super_map_lun.assert_called_once_with(fake.LUN_NAME,
                                                   'igroup1',
                                                   42)
        self.assertEqual(result, 'result')

    @mock.patch('cinder.volume.drivers.netapp.dataontap.'
                'client.client_cmode_rest.RestClient.get_lun_map')
    def test_get_lun_map(self, mock_super_get_lun_map):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=fake.LUN_NAME)
        mock_super_get_lun_map.return_value = [
            {'initiator-group': 'igroup1', 'lun-id': 1, 'vserver': 'svm1'}
        ]

        result = self.client.get_lun_map(fake.LUN_NAME)

        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            fake.LUN_NAME
        )
        mock_super_get_lun_map.assert_called_once_with(fake.LUN_NAME)
        self.assertEqual(result, [
            {'initiator-group': 'igroup1', 'lun-id': 1, 'vserver': 'svm1'}
        ])

    @mock.patch('cinder.volume.drivers.netapp.dataontap.'
                'client.client_cmode_rest.RestClient.unmap_lun')
    def test_unmap_lun(self, mock_super_unmap_lun):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=fake.LUN_NAME
        )
        self.client.unmap_lun(fake.LUN_NAME, fake.IGROUP1, )
        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            fake.LUN_NAME
        )
        mock_super_unmap_lun.assert_called_once_with(
            fake.LUN_NAME, fake.IGROUP1
        )

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest.RestClient.get_lun_by_args')
    def test_get_lun_by_args_with_path(self, mock_super_get_lun_by_args):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=fake.LUN_NAME
        )
        mock_super_get_lun_by_args.return_value = 'result'

        path_arg = {'path': fake.LUN_PATH}
        result = self.client.get_lun_by_args(path=path_arg)

        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            path_arg
        )
        self.assertEqual(path_arg['path'], fake.LUN_NAME)
        mock_super_get_lun_by_args.assert_called_once_with(path=path_arg)
        self.assertEqual(result, 'result')

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest.RestClient.get_lun_by_args')
    def test_get_lun_by_args_without_path(self, mock_super_get_lun_by_args):
        mock_super_get_lun_by_args.return_value = 'result'
        result = self.client.get_lun_by_args(path=None)
        mock_super_get_lun_by_args.assert_called_once_with(path=None)
        self.assertEqual(result, 'result')

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest.RestClient.map_namespace')
    def test_maps_namespace(self, mock_super_map_namespace):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=fake.NAMESPACE_NAME
        )
        mock_super_map_namespace.return_value = 'namespace-uuid'

        result = self.client.map_namespace(fake.PATH_NAMESPACE, fake.SUBSYSTEM)

        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            fake.PATH_NAMESPACE
        )
        mock_super_map_namespace.assert_called_once_with(
            fake.NAMESPACE_NAME, fake.SUBSYSTEM
        )
        self.assertEqual(result, 'namespace-uuid')

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest.RestClient.map_namespace')
    def test_maps_namespace_with_path_containing_hyphens(
            self, mock_super_map_namespace):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value='name_space_2')
        mock_super_map_namespace.return_value = 'uuid-2'

        result = self.client.map_namespace('/vol/vol1/name-space-2',
                                           'subsystem2')

        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            '/vol/vol1/name-space-2')
        mock_super_map_namespace.assert_called_once_with(
            'name_space_2', 'subsystem2')
        self.assertEqual(result, 'uuid-2')

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest.RestClient.unmap_namespace')
    def test_unmaps_namespace_with_valid_path_and_subsystem(
            self, mock_super_unmap_namespace):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=fake.NAMESPACE_NAME)

        self.client.unmap_namespace(fake.PATH_NAMESPACE, fake.SUBSYSTEM)

        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            fake.PATH_NAMESPACE
        )
        mock_super_unmap_namespace.assert_called_once_with(
            fake.NAMESPACE_NAME, fake.SUBSYSTEM
        )

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest.RestClient.unmap_namespace')
    def test_unmaps_namespace_with_path_containing_special_characters(
            self, mock_super_unmap_namespace):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value='namespace_special')

        self.client.unmap_namespace('/vol/vol1/namespace-special',
                                    'subsystem2')

        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            '/vol/vol1/namespace-special')
        mock_super_unmap_namespace.assert_called_once_with(
            'namespace_special',
            'subsystem2'
        )

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest.RestClient.get_namespace_map')
    def test_get_namespace_map(self, mock_super_get_namespace_map):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=fake.NAMESPACE_NAME
        )
        mock_super_get_namespace_map.return_value = {
            'namespace_map': 'details'}

        result = self.client.get_namespace_map(fake.PATH_NAMESPACE)

        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            fake.PATH_NAMESPACE
        )
        mock_super_get_namespace_map.assert_called_once_with(
            fake.NAMESPACE_NAME)
        self.assertEqual(result, {'namespace_map': 'details'})

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest.RestClient.get_namespace_map')
    def test_get_namespace_map_with_path_containing_special_characters(
            self, mock_super_get_namespace_map):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value='namespace_special')
        mock_super_get_namespace_map.return_value = {
            'namespace_map': 'special_details'}

        result = self.client.get_namespace_map('/vol/vol1/namespace-special')

        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            '/vol/vol1/namespace-special')
        mock_super_get_namespace_map.assert_called_once_with(
            'namespace_special')
        self.assertEqual(result, {
            'namespace_map': 'special_details'
        })

    @mock.patch('cinder.volume.drivers.netapp.dataontap.client.'
                'client_cmode_rest.RestClient.get_namespace_map')
    def test_returns_none_when_namespace_map_not_found(
            self, mock_super_get_namespace_map):
        mock_super_get_namespace_map.return_value = None
        result = self.client.get_namespace_map('/vol/vol1/namespace3')

        mock_super_get_namespace_map.assert_called_once_with('namespace3')
        self.assertIsNone(result)

    @mock.patch(
        'cinder.volume.drivers.netapp.dataontap.client.'
        'client_cmode_rest_asar2.RestClientASAr2._lun_update_by_path')
    def test_resizes_lun(self, mock_lun_update_by_path):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=fake.LUN_NAME)

        self.client.do_direct_resize(fake.LUN_PATH, 10)

        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            fake.LUN_PATH)
        mock_lun_update_by_path.assert_called_once_with(
            fake.LUN_NAME, {'name': fake.LUN_NAME, 'space.size': 10})

    @mock.patch(
        'cinder.volume.drivers.netapp.dataontap.client.'
        'client_cmode_rest_asar2.RestClientASAr2._lun_update_by_path'
    )
    def test_resize_lun_with_invalid_path(self, mock_lun_update_by_path):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=None)
        self.client.do_direct_resize('/vol/vol1/invalid_lun', 53)
        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            '/vol/vol1/invalid_lun')
        mock_lun_update_by_path.assert_not_called()

    @mock.patch('cinder.volume.drivers.netapp.dataontap.'
                'client.client_cmode_rest_asar2.RestClientASAr2.send_request')
    def test_resizes_namespace(self, mock_send_request):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=fake.NAMESPACE_NAME)

        self.client.namespace_resize(fake.PATH_NAMESPACE, fake.SIZE)

        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            fake.PATH_NAMESPACE)
        mock_send_request.assert_called_once_with(
            '/storage/namespaces',
            'patch',
            body={'space.size': fake.SIZE},
            query={'name': fake.NAMESPACE_NAME}
        )

    @mock.patch('cinder.volume.drivers.netapp.dataontap.'
                'client.client_cmode_rest_asar2.RestClientASAr2.send_request')
    def test_resize_namespace_with_invalid_path(self, mock_send_request):
        self.client._get_backend_lun_or_namespace = mock.Mock(
            return_value=None)
        self.client.namespace_resize('/vol/vol1/invalid_namespace', 5368)
        self.client._get_backend_lun_or_namespace.assert_called_once_with(
            '/vol/vol1/invalid_namespace')
        mock_send_request.assert_not_called()
