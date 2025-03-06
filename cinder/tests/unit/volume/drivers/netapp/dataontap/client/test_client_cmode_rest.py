# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2015 Dustin Schoenbrun. All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
# Copyright (c) 2016 Mike Rooney. All rights reserved.
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
import uuid

import ddt
from oslo_utils import units

from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.netapp.dataontap.client import (
    fakes as fake_client)
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as fake
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_base
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap.client import client_cmode_rest
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
                   'certificate_host_validation': 'False'
                   }


@ddt.ddt
class NetAppRestCmodeClientTestCase(test.TestCase):

    def setUp(self):
        super(NetAppRestCmodeClientTestCase, self).setUp()

        # Setup Client mocks
        self.mock_object(client_cmode.Client, '_init_ssh_client')
        # store the original reference so we can call it later in
        # test__get_cluster_nodes_info
        self.original_get_cluster_nodes_info = (
            client_cmode.Client._get_cluster_nodes_info)
        self.mock_object(client_cmode.Client, '_get_cluster_nodes_info',
                         return_value=fake.HYBRID_SYSTEM_NODES_INFO)
        self.mock_object(client_cmode.Client, 'get_ontap_version',
                         return_value=(9, 11, 1))
        self.mock_object(client_cmode.Client,
                         'get_ontapi_version',
                         return_value=(1, 20))

        # Setup RestClient mocks
        self.mock_object(client_cmode_rest.RestClient, '_init_ssh_client')
        # store the original reference so we can call it later in
        # test__get_cluster_nodes_info
        self.original_get_cluster_nodes_info = (
            client_cmode_rest.RestClient._get_cluster_nodes_info)

        # Temporary fix because the function is under implementation
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
                         return_value=(9, 11, 1))
        with mock.patch.object(client_cmode_rest.RestClient,
                               'get_ontap_version',
                               return_value=(9, 11, 1)):
            self.client = client_cmode_rest.RestClient(**CONNECTION_INFO)

        self.client.ssh_client = mock.MagicMock()
        self.client.connection = mock.MagicMock()
        self.connection = self.client.connection

        self.vserver = CONNECTION_INFO['vserver']
        self.fake_volume = str(uuid.uuid4())
        self.fake_lun = str(uuid.uuid4())
        # this line interferes in test__get_cluster_nodes_info
        # self.mock_send_request = self.mock_object(
        #    self.client, 'send_request')

    def _mock_api_error(self, code='fake'):
        return mock.Mock(side_effect=netapp_api.NaApiError(code=code))

    def test_send_request(self):
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

    def test_send_request_post(self):
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

    def test_send_request_wait(self):
        expected = (202, fake_client.JOB_RESPONSE_REST)
        mock_invoke = self.mock_object(
            self.client.connection, 'invoke_successfully',
            mock.Mock(return_value=expected))

        mock_wait = self.mock_object(
            self.client, '_wait_job_result',
            mock.Mock(return_value=expected[1]))

        res = self.client.send_request(
            fake_client.FAKE_ACTION_ENDPOINT, 'post',
            body=fake_client.FAKE_BODY,
            query=fake_client.FAKE_HTTP_QUERY, enable_tunneling=False)

        self.assertEqual(expected[1], res)
        mock_invoke.assert_called_once_with(
            fake_client.FAKE_ACTION_ENDPOINT, 'post',
            body=fake_client.FAKE_BODY,
            query=fake_client.FAKE_HTTP_QUERY, enable_tunneling=False)
        mock_wait.assert_called_once_with(
            expected[1]['job']['_links']['self']['href'][4:])

    @ddt.data(True, False)
    def test_get_records(self, enable_tunneling):
        api_responses = [
            (200, fake_client.VOLUME_GET_ITER_RESPONSE_REST_PAGE),
            (200, fake_client.VOLUME_GET_ITER_RESPONSE_REST_PAGE),
            (200, fake_client.VOLUME_GET_ITER_RESPONSE_REST_LAST_PAGE),
        ]

        mock_invoke = self.mock_object(
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

        next_tag = result.get('next')
        self.assertIsNone(next_tag)

        expected_query = copy.deepcopy(query)
        expected_query['max_records'] = 10

        next_url_1 = api_responses[0][1]['_links']['next']['href'][4:]
        next_url_2 = api_responses[1][1]['_links']['next']['href'][4:]

        mock_invoke.assert_has_calls([
            mock.call('/storage/volumes/', 'get', query=expected_query,
                      enable_tunneling=enable_tunneling),
            mock.call(next_url_1, 'get', query=None,
                      enable_tunneling=enable_tunneling),
            mock.call(next_url_2, 'get', query=None,
                      enable_tunneling=enable_tunneling),
        ])

    def test_get_records_single_page(self):

        api_response = (
            200, fake_client.VOLUME_GET_ITER_RESPONSE_REST_LAST_PAGE)
        mock_invoke = self.mock_object(self.client.connection,
                                       'invoke_successfully',
                                       return_value=api_response)

        query = {
            'fields': 'name'
        }

        result = self.client.get_records(
            '/storage/volumes/', query=query, max_page_length=10)

        num_records = result['num_records']
        self.assertEqual(8, num_records)
        self.assertEqual(8, len(result['records']))

        next_tag = result.get('next')
        self.assertIsNone(next_tag)

        args = copy.deepcopy(query)
        args['max_records'] = 10

        mock_invoke.assert_has_calls([
            mock.call('/storage/volumes/', 'get', query=args,
                      enable_tunneling=True),
        ])

    def test_get_records_not_found(self):

        api_response = (200, fake_client.NO_RECORDS_RESPONSE_REST)
        mock_invoke = self.mock_object(self.client.connection,
                                       'invoke_successfully',
                                       return_value=api_response)

        result = self.client.get_records('/storage/volumes/')

        num_records = result['num_records']
        self.assertEqual(0, num_records)
        self.assertEqual(0, len(result['records']))

        args = {
            'max_records': client_cmode_rest.DEFAULT_MAX_PAGE_LENGTH
        }

        mock_invoke.assert_has_calls([
            mock.call('/storage/volumes/', 'get', query=args,
                      enable_tunneling=True),
        ])

    def test_get_records_timeout(self):
        # To simulate timeout, max_records is 30, but the API returns less
        # records and fill the 'next url' pointing to the next page.
        max_records = 30
        api_responses = [
            (200, fake_client.VOLUME_GET_ITER_RESPONSE_REST_PAGE),
            (200, fake_client.VOLUME_GET_ITER_RESPONSE_REST_PAGE),
            (200, fake_client.VOLUME_GET_ITER_RESPONSE_REST_LAST_PAGE),
        ]

        mock_invoke = self.mock_object(
            self.client.connection, 'invoke_successfully',
            side_effect=copy.deepcopy(api_responses))

        query = {
            'fields': 'name'
        }

        result = self.client.get_records(
            '/storage/volumes/', query=query, max_page_length=max_records)

        num_records = result['num_records']
        self.assertEqual(28, num_records)
        self.assertEqual(28, len(result['records']))

        expected_records = []
        expected_records.extend(api_responses[0][1]['records'])
        expected_records.extend(api_responses[1][1]['records'])
        expected_records.extend(api_responses[2][1]['records'])

        self.assertEqual(expected_records, result['records'])

        next_tag = result.get('next', None)
        self.assertIsNone(next_tag)

        args1 = copy.deepcopy(query)
        args1['max_records'] = max_records

        next_url_1 = api_responses[0][1]['_links']['next']['href'][4:]
        next_url_2 = api_responses[1][1]['_links']['next']['href'][4:]

        mock_invoke.assert_has_calls([
            mock.call('/storage/volumes/', 'get', query=args1,
                      enable_tunneling=True),
            mock.call(next_url_1, 'get', query=None, enable_tunneling=True),
            mock.call(next_url_2, 'get', query=None, enable_tunneling=True),
        ])

    def test__get_unique_volume(self):
        api_response = fake_client.VOLUME_GET_ITER_STYLE_RESPONSE_REST

        result = self.client._get_unique_volume(api_response["records"])

        expected = fake_client.VOLUME_FLEXGROUP_STYLE_REST
        self.assertEqual(expected, result)

    def test__get_unique_volume_raise_exception(self):
        api_response = fake_client.VOLUME_GET_ITER_SAME_STYLE_RESPONSE_REST

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client._get_unique_volume,
                          api_response["records"])

    @ddt.data(fake.REST_FIELDS, None)
    def test__get_volume_by_args(self, fields):
        mock_get_unique_vol = self.mock_object(
            self.client, '_get_unique_volume',
            return_value=fake_client.VOLUME_GET_ITER_SSC_RESPONSE_STR_REST)
        mock_send_request = self.mock_object(
            self.client, 'send_request',
            return_value=fake_client.VOLUME_GET_ITER_SSC_RESPONSE_REST)

        volume = self.client._get_volume_by_args(
            vol_name=fake.VOLUME_NAME, vol_path=fake.VOLUME_PATH,
            vserver=fake.VSERVER_NAME, fields=fields)

        self.assertEqual(fake_client.VOLUME_GET_ITER_SSC_RESPONSE_STR_REST,
                         volume)
        mock_get_unique_vol.assert_called_once_with(
            fake_client.VOLUME_GET_ITER_SSC_RESPONSE_REST['records'])
        expected_query = {
            'type': 'rw',
            'style': 'flex*',
            'is_svm_root': 'false',
            'error_state.is_inconsistent': 'false',
            'state': 'online',
            'name': fake.VOLUME_NAME,
            'nas.path': fake.VOLUME_PATH,
            'svm.name': fake.VSERVER_NAME,
            'fields': 'name,style' if not fields else fields,
        }
        mock_send_request.assert_called_once_with('/storage/volumes/', 'get',
                                                  query=expected_query)

    @ddt.data(False, True)
    def test_get_flexvol(self, is_flexgroup):

        if is_flexgroup:
            api_response = \
                fake_client.VOLUME_GET_ITER_SSC_RESPONSE_FLEXGROUP_REST
            volume_response = \
                fake_client.VOLUME_GET_ITER_SSC_RESPONSE_STR_FLEXGROUP_REST
        else:
            api_response = fake_client.VOLUME_GET_ITER_SSC_RESPONSE_REST
            volume_response = \
                fake_client.VOLUME_GET_ITER_SSC_RESPONSE_STR_REST

        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        mock_get_unique_vol = self.mock_object(
            self.client, '_get_volume_by_args', return_value=volume_response)

        result = self.client.get_flexvol(
            flexvol_name=fake_client.VOLUME_NAMES[0],
            flexvol_path='/%s' % fake_client.VOLUME_NAMES[0])

        fields = ('aggregates.name,name,svm.name,nas.path,'
                  'type,guarantee.honored,guarantee.type,'
                  'space.snapshot.reserve_percent,space.size,'
                  'qos.policy.name,snapshot_policy,language,style')
        mock_get_unique_vol.assert_called_once_with(
            vol_name=fake_client.VOLUME_NAMES[0],
            vol_path='/%s' % fake_client.VOLUME_NAMES[0], fields=fields)

        if is_flexgroup:
            self.assertEqual(fake_client.VOLUME_INFO_SSC_FLEXGROUP, result)
        else:
            self.assertEqual(fake_client.VOLUME_INFO_SSC, result)

    def test_list_flexvols(self):
        api_response = fake_client.VOLUME_GET_ITER_LIST_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client.list_flexvols()

        query = {
            'type': 'rw',
            'style': 'flex*',  # Match both 'flexvol' and 'flexgroup'
            'is_svm_root': 'false',
            'error_state.is_inconsistent': 'false',
            # 'is-invalid': 'false',
            'state': 'online',
            'fields': 'name'
        }

        self.client.send_request.assert_called_once_with(
            '/storage/volumes/', 'get', query=query)
        self.assertEqual(list(fake_client.VOLUME_NAMES), result)

    def test_list_flexvols_not_found(self):
        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client.list_flexvols()
        self.assertEqual([], result)

    def test_is_flexvol_mirrored(self):

        api_response = fake_client.GET_NUM_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client.is_flexvol_mirrored(
            fake_client.VOLUME_NAMES[0], fake_client.VOLUME_VSERVER_NAME)

        query = {
            'source.path': fake_client.VOLUME_VSERVER_NAME +
            ':' + fake_client.VOLUME_NAMES[0],
            'state': 'snapmirrored',
            'return_records': 'false',
        }

        self.client.send_request.assert_called_once_with(
            '/snapmirror/relationships/', 'get', query=query)
        self.assertTrue(result)

    def test_is_flexvol_mirrored_not_mirrored(self):

        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client.is_flexvol_mirrored(
            fake_client.VOLUME_NAMES[0], fake_client.VOLUME_VSERVER_NAME)

        self.assertFalse(result)

    def test_is_flexvol_mirrored_api_error(self):

        self.mock_object(self.client,
                         'send_request',
                         side_effect=self._mock_api_error())

        result = self.client.is_flexvol_mirrored(
            fake_client.VOLUME_NAMES[0], fake_client.VOLUME_VSERVER_NAME)

        self.assertFalse(result)

    def test_is_flexvol_encrypted(self):

        api_response = fake_client.GET_NUM_RECORDS_RESPONSE_REST
        self.client.features.add_feature('FLEXVOL_ENCRYPTION')
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client.is_flexvol_encrypted(
            fake_client.VOLUME_NAME, fake_client.VOLUME_VSERVER_NAME)

        query = {
            'encryption.enabled': 'true',
            'name': fake_client.VOLUME_NAME,
            'svm.name': fake_client.VOLUME_VSERVER_NAME,
            'return_records': 'false',
        }

        self.client.send_request.assert_called_once_with(
            '/storage/volumes/', 'get', query=query)

        self.assertTrue(result)

    def test_is_flexvol_encrypted_unsupported_version(self):

        self.client.features.add_feature('FLEXVOL_ENCRYPTION', supported=False)
        result = self.client.is_flexvol_encrypted(
            fake_client.VOLUME_NAMES[0], fake_client.VOLUME_VSERVER_NAME)

        self.assertFalse(result)

    def test_is_flexvol_encrypted_no_records_found(self):

        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client.is_flexvol_encrypted(
            fake_client.VOLUME_NAMES[0], fake_client.VOLUME_VSERVER_NAME)

        self.assertFalse(result)

    def test_is_flexvol_encrypted_api_error(self):

        self.mock_object(self.client,
                         'send_request',
                         side_effect=self._mock_api_error())

        result = self.client.is_flexvol_encrypted(
            fake_client.VOLUME_NAMES[0], fake_client.VOLUME_VSERVER_NAME)

        self.assertFalse(result)

    @ddt.data({'types': {'FCAL'}, 'expected': ['FCAL']},
              {'types': {'SATA', 'SSD'}, 'expected': ['SATA', 'SSD']},)
    @ddt.unpack
    def test_get_aggregate_disk_types(self, types, expected):

        mock_get_aggregate_disk_types = self.mock_object(
            self.client, '_get_aggregate_disk_types', return_value=types)

        result = self.client.get_aggregate_disk_types(
            fake_client.VOLUME_AGGREGATE_NAME)

        self.assertCountEqual(expected, result)
        mock_get_aggregate_disk_types.assert_called_once_with(
            fake_client.VOLUME_AGGREGATE_NAME)

    def test_get_aggregate_disk_types_not_found(self):

        mock_get_aggregate_disk_types = self.mock_object(
            self.client, '_get_aggregate_disk_types', return_value=set())

        result = self.client.get_aggregate_disk_types(
            fake_client.VOLUME_AGGREGATE_NAME)

        self.assertIsNone(result)
        mock_get_aggregate_disk_types.assert_called_once_with(
            fake_client.VOLUME_AGGREGATE_NAME)

    def test_get_aggregate_disk_types_api_not_found(self):

        api_error = netapp_api.NaApiError()
        self.mock_object(self.client,
                         'send_request',
                         side_effect=api_error)

        result = self.client.get_aggregate_disk_types(
            fake_client.VOLUME_AGGREGATE_NAME)

        self.assertIsNone(result)

    def test__get_aggregates(self):

        api_response = fake_client.AGGR_GET_ITER_RESPONSE_REST
        mock_send_request = self.mock_object(self.client,
                                             'send_request',
                                             return_value=api_response)

        result = self.client._get_aggregates()

        mock_send_request.assert_has_calls(
            [mock.call('/storage/aggregates', 'get', query={},
                       enable_tunneling=False)])
        self.assertEqual(result, api_response['records'])

    def test__get_aggregates_with_filters(self):

        api_response = fake_client.AGGR_GET_ITER_RESPONSE_REST
        mock_send_request = self.mock_object(self.client,
                                             'send_request',
                                             return_value=api_response)
        query = {
            'fields': 'space.block_storage.size,space.block_storage.available',
            'name': ','.join(fake_client.VOLUME_AGGREGATE_NAMES),
        }

        result = self.client._get_aggregates(
            aggregate_names=fake_client.VOLUME_AGGREGATE_NAMES,
            fields=query['fields'])

        mock_send_request.assert_has_calls([
            mock.call('/storage/aggregates', 'get', query=query,
                      enable_tunneling=False)])
        self.assertEqual(result, api_response['records'])

    def test__get_aggregates_not_found(self):

        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        mock_send_request = self.mock_object(self.client,
                                             'send_request',
                                             return_value=api_response)

        result = self.client._get_aggregates()

        mock_send_request.assert_has_calls([
            mock.call('/storage/aggregates', 'get', query={},
                      enable_tunneling=False)])
        self.assertEqual([], result)

    def test_get_aggregate_none_specified(self):

        result = self.client.get_aggregate('')

        self.assertEqual({}, result)

    def test_get_aggregate(self):

        api_response = [fake_client.AGGR_GET_ITER_RESPONSE_REST['records'][1]]

        mock__get_aggregates = self.mock_object(self.client,
                                                '_get_aggregates',
                                                return_value=api_response)

        response = self.client.get_aggregate(fake_client.VOLUME_AGGREGATE_NAME)

        fields = ('name,block_storage.primary.raid_type,'
                  'block_storage.storage_type,home_node.name')
        mock__get_aggregates.assert_has_calls([
            mock.call(
                aggregate_names=[fake_client.VOLUME_AGGREGATE_NAME],
                fields=fields)])

        expected = {
            'name': fake_client.VOLUME_AGGREGATE_NAME,
            'raid-type': 'raid0',
            'is-hybrid': False,
            'node-name': fake_client.NODE_NAME,
        }
        self.assertEqual(expected, response)

    def test_get_aggregate_not_found(self):

        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client.get_aggregate(fake_client.VOLUME_AGGREGATE_NAME)

        self.assertEqual({}, result)

    def test_get_aggregate_api_error(self):

        self.mock_object(self.client,
                         'send_request',
                         side_effect=self._mock_api_error())

        result = self.client.get_aggregate(fake_client.VOLUME_AGGREGATE_NAME)

        self.assertEqual({}, result)

    def test_get_aggregate_api_not_found(self):

        api_error = netapp_api.NaApiError(code=netapp_api.REST_API_NOT_FOUND)

        self.mock_object(self.client,
                         'send_request',
                         side_effect=api_error)

        result = self.client.get_aggregate(fake_client.VOLUME_AGGREGATE_NAME)

        self.assertEqual({}, result)

    @ddt.data(True, False)
    def test_is_qos_min_supported(self, supported):
        self.client.features.add_feature('test', supported=supported)
        mock_name = self.mock_object(netapp_utils,
                                     'qos_min_feature_name',
                                     return_value='test')
        result = self.client.is_qos_min_supported(True, 'node')

        mock_name.assert_called_once_with(True, 'node')
        self.assertEqual(result, supported)

    def test_is_qos_min_supported_invalid_node(self):
        mock_name = self.mock_object(netapp_utils,
                                     'qos_min_feature_name',
                                     return_value='invalid_feature')
        result = self.client.is_qos_min_supported(True, 'node')

        mock_name.assert_called_once_with(True, 'node')
        self.assertFalse(result)

    def test_is_qos_min_supported_none_node(self):
        result = self.client.is_qos_min_supported(True, None)

        self.assertFalse(result)

    def test_get_flexvol_dedupe_info(self):

        api_response = fake_client.VOLUME_GET_ITER_SSC_RESPONSE_REST
        mock_send_request = self.mock_object(self.client,
                                             'send_request',
                                             return_value=api_response)

        result = self.client.get_flexvol_dedupe_info(
            fake_client.VOLUME_NAMES[0])

        query = {
            'efficiency.volume_path': '/vol/%s' % fake_client.VOLUME_NAMES[0],
            'fields': 'efficiency.state,efficiency.compression'
        }

        mock_send_request.assert_called_once_with(
            '/storage/volumes', 'get', query=query)
        self.assertEqual(
            fake_client.VOLUME_DEDUPE_INFO_SSC_NO_LOGICAL_DATA, result)

    def test_get_flexvol_dedupe_info_no_logical_data_values(self):

        api_response = fake_client.VOLUME_GET_ITER_SSC_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client.get_flexvol_dedupe_info(
            fake_client.VOLUME_NAMES[0])

        self.assertEqual(fake_client.VOLUME_DEDUPE_INFO_SSC_NO_LOGICAL_DATA,
                         result)

    def test_get_flexvol_dedupe_info_not_found(self):

        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client.get_flexvol_dedupe_info(
            fake_client.VOLUME_NAMES[0])

        self.assertEqual(fake_client.VOLUME_DEDUPE_INFO_SSC_NO_LOGICAL_DATA,
                         result)

    def test_get_flexvol_dedupe_info_api_error(self):

        self.mock_object(self.client,
                         'send_request',
                         side_effect=self._mock_api_error())

        result = self.client.get_flexvol_dedupe_info(
            fake_client.VOLUME_NAMES[0])

        self.assertEqual(fake_client.VOLUME_DEDUPE_INFO_SSC_NO_LOGICAL_DATA,
                         result)

    def test_get_flexvol_dedupe_info_api_insufficient_privileges(self):

        api_error = netapp_api.NaApiError(code=netapp_api.EAPIPRIVILEGE)
        self.mock_object(self.client,
                         'send_request',
                         side_effect=api_error)

        result = self.client.get_flexvol_dedupe_info(
            fake_client.VOLUME_NAMES[0])

        self.assertEqual(fake_client.VOLUME_DEDUPE_INFO_SSC_NO_LOGICAL_DATA,
                         result)

    def test_get_lun_list(self):
        response = fake_client.LUN_GET_ITER_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=response)

        expected_result = fake_client.LUN_GET_ITER_RESULT
        luns = self.client.get_lun_list()

        self.assertEqual(expected_result, luns)
        self.assertEqual(2, len(luns))

    def test_get_lun_list_no_records(self):
        response = fake_client.NO_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=response)

        luns = self.client.get_lun_list()

        self.assertEqual([], luns)

    def test_get_lun_sizes_by_volume(self):
        volume_name = fake_client.VOLUME_NAME
        query = {
            'location.volume.name': volume_name,
            'fields': 'space.size,name'
        }
        response = fake_client.LUN_GET_ITER_REST
        expected_result = []
        for lun in fake_client.LUN_GET_ITER_RESULT:
            expected_result.append({
                'size': lun['Size'],
                'path': lun['Path'],
            })

        self.mock_object(self.client,
                         'send_request',
                         return_value=response)

        luns = self.client.get_lun_sizes_by_volume(volume_name)

        self.assertEqual(expected_result, luns)
        self.assertEqual(2, len(luns))
        self.client.send_request.assert_called_once_with(
            '/storage/luns/', 'get', query=query)

    def test_get_lun_sizes_by_volume_no_records(self):
        volume_name = fake_client.VOLUME_NAME
        query = {
            'location.volume.name': volume_name,
            'fields': 'space.size,name'
        }
        response = fake_client.NO_RECORDS_RESPONSE_REST

        self.mock_object(self.client,
                         'send_request',
                         return_value=response)

        luns = self.client.get_lun_sizes_by_volume(volume_name)

        self.assertEqual([], luns)
        self.client.send_request.assert_called_once_with(
            '/storage/luns/', 'get', query=query)

    def test_get_lun_by_args(self):
        response = fake_client.LUN_GET_ITER_REST
        mock_send_request = self.mock_object(
            self.client, 'send_request', return_value=response)

        lun_info_args = {
            'vserver': fake.VSERVER_NAME,
            'path': fake.LUN_PATH,
            'uuid': fake.UUID1,
        }

        luns = self.client.get_lun_by_args(**lun_info_args)

        query = {
            'svm.name': fake.VSERVER_NAME,
            'name': fake.LUN_PATH,
            'uuid': fake.UUID1,
            'fields': 'svm.name,location.volume.name,space.size,'
                      'location.qtree.name,name,os_type,'
                      'space.scsi_thin_provisioning_support_enabled,'
                      'space.guarantee.requested,uuid'
        }

        mock_send_request.assert_called_once_with(
            '/storage/luns/', 'get', query=query)

        self.assertEqual(2, len(luns))

    def test_get_lun_by_args_no_lun_found(self):
        response = fake_client.NO_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=response)

        luns = self.client.get_lun_by_args()

        self.assertEqual([], luns)

    def test_get_lun_by_args_with_one_arg(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        response = fake_client.LUN_GET_ITER_REST
        mock_send_request = self.mock_object(
            self.client, 'send_request', return_value=response)

        luns = self.client.get_lun_by_args(path=path)

        query = {
            'name': path,
            'fields': 'svm.name,location.volume.name,space.size,'
                      'location.qtree.name,name,os_type,'
                      'space.scsi_thin_provisioning_support_enabled,'
                      'space.guarantee.requested,uuid'
        }

        mock_send_request.assert_called_once_with(
            '/storage/luns/', 'get', query=query)

        self.assertEqual(2, len(luns))

    def test_get_file_sizes_by_dir(self):
        volume = fake_client.VOLUME_ITEM_SIMPLE_RESPONSE_REST
        query = {
            'type': 'file',
            'fields': 'size,name'
        }
        response = fake_client.FILE_DIRECTORY_GET_ITER_REST
        expected_result = fake_client.FILE_DIRECTORY_GET_ITER_RESULT_REST

        self.mock_object(self.client,
                         '_get_volume_by_args',
                         return_value=volume)
        self.mock_object(self.client,
                         'send_request',
                         return_value=response)

        files = self.client.get_file_sizes_by_dir(volume['name'])

        self.assertEqual(expected_result, files)
        self.assertEqual(2, len(files))
        self.client.send_request.assert_called_once_with(
            f'/storage/volumes/{volume["uuid"]}/files',
            'get', query=query)

    def test_get_file_sizes_by_dir_no_records(self):
        volume = fake_client.VOLUME_ITEM_SIMPLE_RESPONSE_REST
        query = {
            'type': 'file',
            'fields': 'size,name'
        }

        api_error = netapp_api.NaApiError(code=netapp_api.REST_NO_SUCH_FILE)

        self.mock_object(self.client,
                         '_get_volume_by_args',
                         return_value=volume)
        self.mock_object(self.client,
                         'send_request',
                         side_effect=api_error)

        files = self.client.get_file_sizes_by_dir(volume['name'])

        self.assertEqual([], files)
        self.assertEqual(0, len(files))
        self.client.send_request.assert_called_once_with(
            f'/storage/volumes/{volume["uuid"]}/files',
            'get', query=query)

    def test_get_file_sizes_by_dir_exception(self):
        volume = fake_client.VOLUME_ITEM_SIMPLE_RESPONSE_REST
        api_error = netapp_api.NaApiError(code=0)

        self.mock_object(self.client,
                         '_get_volume_by_args',
                         return_value=volume)
        self.mock_object(self.client,
                         'send_request',
                         side_effect=api_error)
        self.assertRaises(netapp_api.NaApiError,
                          self.client.get_file_sizes_by_dir,
                          volume['name'])

    @ddt.data({'junction_path': '/fake/vol'},
              {'name': 'fake_volume'},
              {'junction_path': '/fake/vol', 'name': 'fake_volume'})
    def test_get_volume_state(self, kwargs):
        query_args = {}
        query_args['fields'] = 'state'

        if 'name' in kwargs:
            query_args['name'] = kwargs['name']
        if 'junction_path' in kwargs:
            query_args['nas.path'] = kwargs['junction_path']

        response = fake_client.VOLUME_GET_ITER_STATE_RESPONSE_REST
        mock_send_request = self.mock_object(
            self.client, 'send_request', return_value=response)

        state = self.client.get_volume_state(**kwargs)

        mock_send_request.assert_called_once_with(
            '/storage/volumes/', 'get', query=query_args)

        self.assertEqual(fake_client.VOLUME_STATE_ONLINE, state)

    def test_delete_snapshot(self):
        volume = fake_client.VOLUME_GET_ITER_SSC_RESPONSE_STR_REST
        self.mock_object(
            self.client, '_get_volume_by_args',
            return_value=volume)
        snap_name = fake.SNAPSHOT["name"]
        self.mock_object(self.client, 'send_request')

        self.client.delete_snapshot(volume["name"], snap_name)

        self.client._get_volume_by_args.assert_called_once_with(
            vol_name=volume["name"])
        self.client.send_request.assert_called_once_with(
            f'/storage/volumes/{volume["uuid"]}/snapshots'
            f'?name={snap_name}', 'delete')

    def test_get_operational_lif_addresses(self):
        expected_result = ['1.2.3.4', '99.98.97.96']
        api_response = fake_client.GET_OPERATIONAL_LIF_ADDRESSES_RESPONSE_REST

        mock_send_request = self.mock_object(self.client,
                                             'send_request',
                                             return_value=api_response)
        address_list = self.client.get_operational_lif_addresses()

        query = {
            'state': 'up',
            'fields': 'ip.address',
        }

        mock_send_request.assert_called_once_with(
            '/network/ip/interfaces/', 'get', query=query)

        self.assertEqual(expected_result, address_list)

    def test__list_vservers(self):
        api_response = fake_client.VSERVER_DATA_LIST_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)
        result = self.client._list_vservers()
        query = {
            'fields': 'name',
        }
        self.client.send_request.assert_has_calls([
            mock.call('/svm/svms', 'get', query=query,
                      enable_tunneling=False)])
        self.assertListEqual(
            [fake_client.VSERVER_NAME, fake_client.VSERVER_NAME_2], result)

    def test_list_vservers_not_found(self):
        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)
        result = self.client._list_vservers()
        self.assertListEqual([], result)

    def test_get_ems_log_destination_vserver(self):
        mock_list_vservers = self.mock_object(
            self.client,
            '_list_vservers',
            return_value=[fake_client.VSERVER_NAME])
        result = self.client._get_ems_log_destination_vserver()
        mock_list_vservers.assert_called_once_with()
        self.assertEqual(fake_client.VSERVER_NAME, result)

    def test_get_ems_log_destination_vserver_not_found(self):
        mock_list_vservers = self.mock_object(
            self.client,
            '_list_vservers',
            return_value=[])

        self.assertRaises(exception.NotFound,
                          self.client._get_ems_log_destination_vserver)

        mock_list_vservers.assert_called_once_with()

    def test_send_ems_log_message(self):

        message_dict = {
            'computer-name': '25-dev-vm',
            'event-source': 'Cinder driver NetApp_iSCSI_Cluster_direct',
            'app-version': '20.1.0.dev|vendor|Linux-5.4.0-120-generic-x86_64',
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

    @ddt.data('cp_phase_times', 'domain_busy')
    def test_get_performance_counter_info(self, counter_name):

        response1 = fake_client.PERF_COUNTER_LIST_INFO_WAFL_RESPONSE_REST
        response2 = fake_client.PERF_COUNTER_TABLE_ROWS_WAFL

        object_name = 'wafl'

        mock_send_request = self.mock_object(
            self.client, 'send_request',
            side_effect=[response1, response2])

        result = self.client.get_performance_counter_info(object_name,
                                                          counter_name)

        expected = {
            'name': 'cp_phase_times',
            'base-counter': 'total_cp_msecs',
            'labels': fake_client.PERF_COUNTER_TOTAL_CP_MSECS_LABELS_RESULT,
        }

        query1 = {
            'counter_schemas.name': counter_name,
            'fields': 'counter_schemas.*'
        }

        query2 = {
            'counters.name': counter_name,
            'fields': 'counters.*'
        }

        if counter_name == 'domain_busy':
            expected['name'] = 'domain_busy'
            expected['labels'] = (
                fake_client.PERF_COUNTER_TOTAL_CP_MSECS_LABELS_REST)
            query1['counter_schemas.name'] = 'domain_busy_percent'
            query2['counters.name'] = 'domain_busy_percent'

        self.assertEqual(expected, result)

        mock_send_request.assert_has_calls([
            mock.call(f'/cluster/counter/tables/{object_name}',
                      'get', query=query1, enable_tunneling=False),
            mock.call(f'/cluster/counter/tables/{object_name}/rows',
                      'get', query=query2, enable_tunneling=False),
        ])

    def test_get_performance_counter_info_not_found_rows(self):
        response1 = fake_client.PERF_COUNTER_LIST_INFO_WAFL_RESPONSE_REST
        response2 = fake_client.NO_RECORDS_RESPONSE_REST

        object_name = 'wafl'
        counter_name = 'cp_phase_times'

        self.mock_object(
            self.client, 'send_request',
            side_effect=[response1, response2])

        result = self.client.get_performance_counter_info(object_name,
                                                          counter_name)

        expected = {
            'name': 'cp_phase_times',
            'base-counter': 'total_cp_msecs',
            'labels': [],
        }
        self.assertEqual(expected, result)

    def test_get_performance_instance_uuids(self):
        response = fake_client.PERF_COUNTER_TABLE_ROWS_WAFL

        mock_send_request = self.mock_object(
            self.client, 'send_request',
            return_value=response)

        object_name = 'wafl'
        result = self.client.get_performance_instance_uuids(
            object_name, fake_client.NODE_NAME)

        expected = [fake_client.NODE_NAME + ':wafl']
        self.assertEqual(expected, result)

        query = {
            'id': fake_client.NODE_NAME + ':*',
        }
        mock_send_request.assert_called_once_with(
            f'/cluster/counter/tables/{object_name}/rows',
            'get', query=query, enable_tunneling=False)

    def test_get_performance_counters(self):
        response = fake_client.PERF_GET_INSTANCES_PROCESSOR_RESPONSE_REST

        mock_send_request = self.mock_object(
            self.client, 'send_request',
            return_value=response)

        instance_uuids = [
            fake_client.NODE_NAME + ':processor0',
            fake_client.NODE_NAME + ':processor1',
        ]
        object_name = 'processor'
        counter_names = ['domain_busy', 'processor_elapsed_time']
        rest_counter_names = ['domain_busy_percent', 'elapsed_time']
        result = self.client.get_performance_counters(object_name,
                                                      instance_uuids,
                                                      counter_names)

        expected = fake_client.PERF_COUNTERS_PROCESSOR_EXPECTED
        self.assertEqual(expected, result)

        query = {
            'id': '|'.join(instance_uuids),
            'counters.name': '|'.join(rest_counter_names),
            'fields': 'id,counter_table.name,counters.*',
        }

        mock_send_request.assert_called_once_with(
            f'/cluster/counter/tables/{object_name}/rows',
            'get', query=query, enable_tunneling=False)

    def test_get_aggregate_capacities(self):
        aggr1_capacities = {
            'percent-used': 50,
            'size-available': 100.0,
            'size-total': 200.0,
        }
        aggr2_capacities = {
            'percent-used': 75,
            'size-available': 125.0,
            'size-total': 500.0,
        }
        mock_get_aggregate_capacity = self.mock_object(
            self.client, '_get_aggregate_capacity',
            side_effect=[aggr1_capacities, aggr2_capacities])

        result = self.client.get_aggregate_capacities(['aggr1', 'aggr2'])

        expected = {
            'aggr1': aggr1_capacities,
            'aggr2': aggr2_capacities,
        }
        self.assertEqual(expected, result)
        mock_get_aggregate_capacity.assert_has_calls([
            mock.call('aggr1'),
            mock.call('aggr2'),
        ])

    def test_get_aggregate_capacities_not_found(self):
        mock_get_aggregate_capacity = self.mock_object(
            self.client, '_get_aggregate_capacity', side_effect=[{}, {}])

        result = self.client.get_aggregate_capacities(['aggr1', 'aggr2'])

        expected = {
            'aggr1': {},
            'aggr2': {},
        }
        self.assertEqual(expected, result)
        mock_get_aggregate_capacity.assert_has_calls([
            mock.call('aggr1'),
            mock.call('aggr2'),
        ])

    def test_get_aggregate_capacities_not_list(self):
        result = self.client.get_aggregate_capacities('aggr1')
        self.assertEqual({}, result)

    def test__get_aggregate_capacity(self):
        api_response = fake_client.AGGR_GET_ITER_RESPONSE_REST['records']
        mock_get_aggregates = self.mock_object(self.client,
                                               '_get_aggregates',
                                               return_value=api_response)

        result = self.client._get_aggregate_capacity(
            fake_client.VOLUME_AGGREGATE_NAME)

        fields = ('space.block_storage.available,space.block_storage.size,'
                  'space.block_storage.used')
        mock_get_aggregates.assert_has_calls([
            mock.call(aggregate_names=[fake_client.VOLUME_AGGREGATE_NAME],
                      fields=fields)])

        available = float(fake_client.AGGR_SIZE_AVAILABLE)
        total = float(fake_client.AGGR_SIZE_TOTAL)
        used = float(fake_client.AGGR_SIZE_USED)
        percent_used = int((used * 100) // total)

        expected = {
            'percent-used': percent_used,
            'size-available': available,
            'size-total': total,
        }
        self.assertEqual(expected, result)

    def test__get_aggregate_capacity_not_found(self):

        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client._get_aggregate_capacity(
            fake_client.VOLUME_AGGREGATE_NAME)

        self.assertEqual({}, result)

    def test__get_aggregate_capacity_api_error(self):

        self.mock_object(self.client,
                         'send_request',
                         side_effect=self._mock_api_error())

        result = self.client._get_aggregate_capacity(
            fake_client.VOLUME_AGGREGATE_NAME)

        self.assertEqual({}, result)

    def test__get_aggregate_capacity_api_not_found(self):

        api_error = netapp_api.NaApiError(code=netapp_api.REST_API_NOT_FOUND)
        self.mock_object(
            self.client, 'send_request', side_effect=api_error)

        result = self.client._get_aggregate_capacity(
            fake_client.VOLUME_AGGREGATE_NAME)

        self.assertEqual({}, result)

    def test_get_node_for_aggregate(self):

        api_response = fake_client.AGGR_GET_ITER_RESPONSE_REST['records']
        mock_get_aggregates = self.mock_object(self.client,
                                               '_get_aggregates',
                                               return_value=api_response)

        result = self.client.get_node_for_aggregate(
            fake_client.VOLUME_AGGREGATE_NAME)

        fields = 'home_node.name'
        mock_get_aggregates.assert_has_calls([
            mock.call(
                aggregate_names=[fake_client.VOLUME_AGGREGATE_NAME],
                fields=fields)])

        self.assertEqual(fake_client.NODE_NAME, result)

    def test_get_node_for_aggregate_none_requested(self):
        result = self.client.get_node_for_aggregate(None)
        self.assertIsNone(result)

    def test_get_node_for_aggregate_api_not_found(self):
        api_error = netapp_api.NaApiError(code=netapp_api.REST_API_NOT_FOUND)
        self.mock_object(self.client,
                         'send_request',
                         side_effect=api_error)

        result = self.client.get_node_for_aggregate(
            fake_client.VOLUME_AGGREGATE_NAME)

        self.assertIsNone(result)

    def test_get_node_for_aggregate_api_error(self):

        self.mock_object(self.client,
                         'send_request',
                         self._mock_api_error())

        self.assertRaises(netapp_api.NaApiError,
                          self.client.get_node_for_aggregate,
                          fake_client.VOLUME_AGGREGATE_NAME)

    def test_get_node_for_aggregate_not_found(self):

        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client.get_node_for_aggregate(
            fake_client.VOLUME_AGGREGATE_NAME)

        self.assertIsNone(result)

    @ddt.data(None, {'legacy': 'fake'}, {})
    def test_provision_qos_policy_group_invalid_policy_info(self, policy_info):
        self.mock_object(self.client, '_validate_qos_policy_group')
        self.mock_object(self.client, '_get_qos_first_policy_group_by_name')
        self.mock_object(self.client, '_create_qos_policy_group')
        self.mock_object(self.client, '_modify_qos_policy_group')

        self.client.provision_qos_policy_group(policy_info, False)

        self.client._validate_qos_policy_group.assert_not_called()
        self.client._get_qos_first_policy_group_by_name.assert_not_called()
        self.client._create_qos_policy_group.assert_not_called()
        self.client._modify_qos_policy_group.assert_not_called()

    @ddt.data(True, False)
    def test_provision_qos_policy_group_qos_policy_create(self, is_adaptive):
        policy_info = fake.QOS_POLICY_GROUP_INFO
        policy_spec = fake.QOS_POLICY_GROUP_SPEC
        if is_adaptive:
            policy_info = fake.ADAPTIVE_QOS_POLICY_GROUP_INFO
            policy_spec = fake.ADAPTIVE_QOS_SPEC

        self.mock_object(self.client, '_validate_qos_policy_group')
        self.mock_object(self.client, '_get_qos_first_policy_group_by_name',
                         return_value=None)
        self.mock_object(self.client, '_create_qos_policy_group')
        self.mock_object(self.client, '_modify_qos_policy_group')

        self.client.provision_qos_policy_group(policy_info, True)

        self.client._validate_qos_policy_group.assert_called_once_with(
            is_adaptive, spec=policy_spec, qos_min_support=True)
        (self.client._get_qos_first_policy_group_by_name.
            assert_called_once_with(policy_spec['policy_name']))
        self.client._create_qos_policy_group.assert_called_once_with(
            policy_spec, is_adaptive)
        self.client._modify_qos_policy_group.assert_not_called()

    @ddt.data(True, False)
    def test_provision_qos_policy_group_qos_policy_modify(self, is_adaptive):
        policy_rest_item = fake.QOS_POLICY_BY_NAME_RESPONSE_REST['records'][0]
        policy_info = fake.QOS_POLICY_GROUP_INFO
        policy_spec = fake.QOS_POLICY_GROUP_SPEC
        if is_adaptive:
            policy_info = fake.ADAPTIVE_QOS_POLICY_GROUP_INFO
            policy_spec = fake.ADAPTIVE_QOS_SPEC

        self.mock_object(self.client, '_validate_qos_policy_group')
        self.mock_object(self.client, '_get_qos_first_policy_group_by_name',
                         return_value=policy_rest_item)
        self.mock_object(self.client, '_create_qos_policy_group')
        self.mock_object(self.client, '_modify_qos_policy_group')

        self.client.provision_qos_policy_group(policy_info, True)

        self.client._validate_qos_policy_group.assert_called_once_with(
            is_adaptive, spec=policy_spec, qos_min_support=True)
        (self.client._get_qos_first_policy_group_by_name.
            assert_called_once_with(policy_spec['policy_name']))
        self.client._create_qos_policy_group.assert_not_called()
        self.client._modify_qos_policy_group.assert_called_once_with(
            policy_spec, is_adaptive, policy_rest_item)

    @ddt.data(True, False)
    def test__get_qos_first_policy_group_by_name(self, is_empty):
        qos_rest_records = []
        qos_item = fake.QOS_POLICY_BY_NAME_RESPONSE_REST['records'][0]
        if not is_empty:
            qos_rest_records = fake.QOS_POLICY_BY_NAME_RESPONSE_REST['records']

        self.mock_object(self.client, '_get_qos_policy_group_by_name',
                         return_value=qos_rest_records)

        result = self.client._get_qos_first_policy_group_by_name(
            qos_item['name'])

        self.client._get_qos_policy_group_by_name.assert_called_once_with(
            qos_item['name']
        )
        if not is_empty:
            self.assertEqual(qos_item, result)
        else:
            self.assertTrue(result is None)

    @ddt.data(True, False)
    def test__get_qos_policy_group_by_name(self, is_empty):
        qos_rest_response = {}
        qos_rest_records = []
        qos_name = fake.QOS_POLICY_BY_NAME_RESPONSE_REST['records'][0]['name']
        if not is_empty:
            qos_rest_response = fake.QOS_POLICY_BY_NAME_RESPONSE_REST
            qos_rest_records = qos_rest_response['records']

        self.mock_object(self.client, 'send_request',
                         return_value=qos_rest_response)

        result = self.client._get_qos_policy_group_by_name(qos_name)

        self.client.send_request.assert_called_once_with(
            '/storage/qos/policies/', 'get', query={'name': qos_name})
        self.assertEqual(qos_rest_records, result)

    @ddt.data(True, False)
    def test__qos_spec_to_api_args(self, is_adaptive):
        policy_spec = copy.deepcopy(fake.QOS_POLICY_GROUP_SPEC)
        expected_args = fake.QOS_POLICY_GROUP_API_ARGS_REST
        if is_adaptive:
            policy_spec = fake.ADAPTIVE_QOS_SPEC
            expected_args = fake.ADAPTIVE_QOS_API_ARGS_REST

        result = self.client._qos_spec_to_api_args(
            policy_spec, is_adaptive, vserver=fake.VSERVER_NAME)

        self.assertEqual(expected_args, result)

    def test__qos_spec_to_api_args_bps(self):
        policy_spec = copy.deepcopy(fake.QOS_POLICY_GROUP_SPEC_BPS)
        expected_args = fake.QOS_POLICY_GROUP_API_ARGS_REST_BPS

        result = self.client._qos_spec_to_api_args(
            policy_spec, False, vserver=fake.VSERVER_NAME)

        self.assertEqual(expected_args, result)

    @ddt.data('100IOPS', '100iops', '100B/s', '100b/s')
    def test__sanitize_qos_spec_value(self, value):
        result = self.client._sanitize_qos_spec_value(value)

        self.assertEqual(100, result)

    @ddt.data(True, False)
    def test__create_qos_policy_group(self, is_adaptive):
        self.client.vserver = fake.VSERVER_NAME
        policy_spec = fake.QOS_POLICY_GROUP_SPEC
        body_args = fake.QOS_POLICY_GROUP_API_ARGS_REST
        if is_adaptive:
            policy_spec = fake.ADAPTIVE_QOS_SPEC
            body_args = fake.ADAPTIVE_QOS_API_ARGS_REST

        self.mock_object(self.client, '_qos_spec_to_api_args',
                         return_value=body_args)
        self.mock_object(self.client, 'send_request')

        self.client._create_qos_policy_group(policy_spec, is_adaptive)

        self.client._qos_spec_to_api_args.assert_called_once_with(
            policy_spec, is_adaptive, vserver=fake.VSERVER_NAME)
        self.client.send_request.assert_called_once_with(
            '/storage/qos/policies/', 'post', body=body_args,
            enable_tunneling=False)

    @ddt.data((False, False), (False, True), (True, False), (True, True))
    @ddt.unpack
    def test__modify_qos_policy_group(self, is_adaptive, same_name):
        self.client.vserver = fake.VSERVER_NAME
        policy_spec = fake.QOS_POLICY_GROUP_SPEC
        body_args = copy.deepcopy(fake.QOS_POLICY_GROUP_API_ARGS_REST)
        if is_adaptive:
            policy_spec = fake.ADAPTIVE_QOS_SPEC
            body_args = copy.deepcopy(fake.ADAPTIVE_QOS_API_ARGS_REST)

        expected_body_args = copy.deepcopy(body_args)
        qos_group_item = copy.deepcopy(
            fake.QOS_POLICY_BY_NAME_RESPONSE_REST['records'][0])
        if same_name:
            qos_group_item['name'] = policy_spec['policy_name']
            expected_body_args.pop('name')

        self.mock_object(self.client, '_qos_spec_to_api_args',
                         return_value=body_args)
        self.mock_object(self.client, 'send_request')

        self.client._modify_qos_policy_group(
            policy_spec, is_adaptive, qos_group_item)

        self.client._qos_spec_to_api_args.assert_called_once_with(
            policy_spec, is_adaptive)
        self.client.send_request.assert_called_once_with(
            f'/storage/qos/policies/{qos_group_item["uuid"]}', 'patch',
            body=expected_body_args, enable_tunneling=False)

    def test_get_vol_by_junc_vserver(self):
        api_response = fake_client.VOLUME_LIST_SIMPLE_RESPONSE_REST
        volume_response = fake_client.VOLUME_ITEM_SIMPLE_RESPONSE_REST
        file_path = f'/vol/{fake_client.VOLUME_NAMES[0]}/cinder-vol'

        self.mock_object(self.client, 'send_request',
                         return_value=api_response)
        self.mock_object(self.client, '_get_unique_volume',
                         return_value=volume_response)

        result = self.client.get_vol_by_junc_vserver(
            fake_client.VOLUME_VSERVER_NAME, file_path)

        query = {
            'type': 'rw',
            'style': 'flex*',
            'is_svm_root': 'false',
            'error_state.is_inconsistent': 'false',
            'state': 'online',
            'nas.path': file_path,
            'svm.name': fake_client.VOLUME_VSERVER_NAME,
            'fields': 'name,style'
        }

        self.client.send_request.assert_called_once_with(
            '/storage/volumes/', 'get', query=query)
        self.client._get_unique_volume.assert_called_once_with(
            api_response["records"])

        self.assertEqual(volume_response['name'], result)

    def test_file_assign_qos(self):
        volume = fake_client.VOLUME_GET_ITER_SSC_RESPONSE_STR_REST
        self.mock_object(
            self.client, '_get_volume_by_args',
            return_value=volume)
        self.mock_object(self.client, 'send_request')

        self.client.file_assign_qos(
            volume['name'], fake.QOS_POLICY_GROUP_NAME, True, fake.VOLUME_NAME)

        self.client._get_volume_by_args.assert_called_once_with(volume['name'])
        body = {'qos_policy.name': fake.QOS_POLICY_GROUP_NAME}
        self.client.send_request.assert_called_once_with(
            f'/storage/volumes/{volume["uuid"]}/files/{fake.VOLUME_NAME}',
            'patch', body=body, enable_tunneling=False)

    @ddt.data(None, {})
    def test_mark_qos_policy_group_for_deletion_invalid_policy(self,
                                                               policy_info):
        self.mock_object(self.client, '_rename_qos_policy_group')
        self.mock_object(self.client, 'remove_unused_qos_policy_groups')

        self.client.mark_qos_policy_group_for_deletion(policy_info, False)

        self.client._rename_qos_policy_group.assert_not_called()
        if policy_info is None:
            self.client.remove_unused_qos_policy_groups.assert_not_called()
        else:
            (self.client.remove_unused_qos_policy_groups
             .assert_called_once_with())

    @ddt.data((False, False), (False, True), (True, False), (True, True))
    @ddt.unpack
    def test_mark_qos_policy_group_for_deletion(self, is_adaptive, has_error):
        policy_info = fake.QOS_POLICY_GROUP_INFO
        if is_adaptive:
            policy_info = fake.ADAPTIVE_QOS_POLICY_GROUP_INFO
        current_name = policy_info['spec']['policy_name']
        deleted_name = client_base.DELETED_PREFIX + current_name

        self.mock_object(self.client, 'remove_unused_qos_policy_groups')
        if has_error:
            self.mock_object(self.client, '_rename_qos_policy_group',
                             side_effect=self._mock_api_error())
        else:
            self.mock_object(self.client, '_rename_qos_policy_group')

        self.client.mark_qos_policy_group_for_deletion(
            policy_info, is_adaptive)

        self.client._rename_qos_policy_group.assert_called_once_with(
            current_name, deleted_name)
        self.client.remove_unused_qos_policy_groups.assert_called_once_with()

    def test__rename_qos_policy_group(self):
        self.mock_object(self.client, 'send_request')
        new_policy_name = 'fake_new_policy'

        self.client._rename_qos_policy_group(fake.QOS_POLICY_GROUP_NAME,
                                             new_policy_name)

        body = {'name': new_policy_name}
        query = {'name': fake.QOS_POLICY_GROUP_NAME}
        self.client.send_request.assert_called_once_with(
            '/storage/qos/policies/', 'patch', body=body, query=query,
            enable_tunneling=False)

    def test_remove_unused_qos_policy_groups(self):
        deleted_preffix = f'{client_base.DELETED_PREFIX}*'

        self.mock_object(self.client, 'send_request')

        self.client.remove_unused_qos_policy_groups()

        query = {'name': deleted_preffix}
        self.client.send_request.assert_called_once_with(
            '/storage/qos/policies', 'delete', query=query)

    def test_create_lun(self):
        metadata = copy.deepcopy(fake_client.LUN_GET_ITER_RESULT[0])
        path = f'/vol/{fake.VOLUME_NAME}/{fake.LUN_NAME}'
        size = 2048
        initial_size = size
        qos_policy_group_is_adaptive = False

        self.mock_object(self.client, '_validate_qos_policy_group')
        self.mock_object(self.client, 'send_request')

        body = {
            'name': path,
            'space.size': str(initial_size),
            'os_type': metadata['OsType'],
            'space.guarantee.requested': metadata['SpaceReserved'],
            'space.scsi_thin_provisioning_support_enabled':
                metadata['SpaceAllocated'],
            'qos_policy.name': fake.QOS_POLICY_GROUP_NAME
        }

        self.client.create_lun(
            fake.VOLUME_NAME, fake.LUN_NAME, size, metadata,
            qos_policy_group_name=fake.QOS_POLICY_GROUP_NAME,
            qos_policy_group_is_adaptive=qos_policy_group_is_adaptive)

        self.client._validate_qos_policy_group.assert_called_once_with(
            qos_policy_group_is_adaptive)
        self.client.send_request.assert_called_once_with(
            '/storage/luns', 'post', body=body)

    def test_do_direct_resize(self):
        lun_path = f'/vol/{fake_client.VOLUME_NAMES[0]}/cinder-lun'
        new_size_bytes = '1073741824'
        body = {'name': lun_path, 'space.size': new_size_bytes}

        self.mock_object(self.client, '_lun_update_by_path')

        self.client.do_direct_resize(lun_path, new_size_bytes)

        self.client._lun_update_by_path.assert_called_once_with(lun_path, body)

    @ddt.data(True, False)
    def test__get_lun_by_path(self, is_empty):
        lun_path = f'/vol/{fake_client.VOLUME_NAMES[0]}/cinder-lun'
        lun_response = fake_client.LUN_GET_ITER_REST
        lun_records = fake_client.LUN_GET_ITER_REST['records']
        if is_empty:
            lun_response = {}
            lun_records = []

        self.mock_object(self.client, 'send_request',
                         return_value=lun_response)

        result = self.client._get_lun_by_path(lun_path)

        query = {'name': lun_path}
        self.client.send_request.assert_called_once_with(
            '/storage/luns', 'get', query=query)
        self.assertEqual(result, lun_records)

    @ddt.data(True, False)
    def test__get_first_lun_by_path(self, is_empty):
        lun_path = f'/vol/{fake_client.VOLUME_NAMES[0]}/cinder-lun'
        lun_records = fake_client.LUN_GET_ITER_REST['records']
        lun_item = lun_records[0]
        if is_empty:
            lun_records = []

        self.mock_object(self.client, '_get_lun_by_path',
                         return_value=lun_records)

        result = self.client._get_first_lun_by_path(lun_path)

        self.client._get_lun_by_path.assert_called_once_with(
            lun_path, fields=None)
        if is_empty:
            self.assertTrue(result is None)
        else:
            self.assertEqual(result, lun_item)

    def test__lun_update_by_path(self):
        lun_path = f'/vol/{fake_client.VOLUME_NAMES[0]}/cinder-lun'
        lun_item = fake_client.LUN_GET_ITER_REST['records'][0]
        new_size_bytes = '1073741824'
        body = {
            'name': lun_path,
            'space.guarantee.requested': 'True',
            'space.size': new_size_bytes
        }

        self.mock_object(self.client, '_get_first_lun_by_path',
                         return_value=lun_item)
        self.mock_object(self.client, 'send_request')

        self.client._lun_update_by_path(lun_path, body)

        self.client._get_first_lun_by_path.assert_called_once_with(lun_path)
        self.client.send_request.assert_called_once_with(
            f'/storage/luns/{lun_item["uuid"]}', 'patch', body=body)

    def test__lun_update_by_path_not_found(self):
        lun_path = f'/vol/{fake_client.VOLUME_NAMES[0]}/cinder-lun'
        lun_item = None
        new_size_bytes = '1073741824'
        body = {
            'name': lun_path,
            'space.guarantee.requested': 'True',
            'space.size': new_size_bytes
        }

        self.mock_object(self.client, '_get_first_lun_by_path',
                         return_value=lun_item)
        self.mock_object(self.client, 'send_request')

        self.assertRaises(
            netapp_api.NaApiError,
            self.client._lun_update_by_path,
            lun_path,
            body
        )

        self.client._get_first_lun_by_path.assert_called_once_with(lun_path)
        self.client.send_request.assert_not_called()

    def test__validate_qos_policy_group_unsupported_qos(self):
        is_adaptive = True
        self.client.features.ADAPTIVE_QOS = False

        self.assertRaises(
            netapp_utils.NetAppDriverException,
            self.client._validate_qos_policy_group,
            is_adaptive
        )

    def test__validate_qos_policy_group_no_spec(self):
        is_adaptive = True
        self.client.features.ADAPTIVE_QOS = True

        result = self.client._validate_qos_policy_group(is_adaptive)

        self.assertTrue(result is None)

    def test__validate_qos_policy_group_unsupported_feature(self):
        is_adaptive = True
        self.client.features.ADAPTIVE_QOS = True
        spec = {
            'min_throughput': fake.MIN_IOPS_REST
        }

        self.assertRaises(
            netapp_utils.NetAppDriverException,
            self.client._validate_qos_policy_group,
            is_adaptive,
            spec=spec,
            qos_min_support=False
        )

    @ddt.data(True, False)
    def test__validate_qos_policy_group(self, is_adaptive):
        self.client.features.ADAPTIVE_QOS = True
        spec = {
            'max_throughput': fake.MAX_IOPS_REST,
            'min_throughput': fake.MIN_IOPS_REST
        }

        self.client._validate_qos_policy_group(
            is_adaptive, spec=spec, qos_min_support=True)

    def test_delete_file(self):
        """Delete file at path."""
        path_to_file = fake.VOLUME_PATH
        volume_response = fake_client.VOLUME_LIST_SIMPLE_RESPONSE_REST
        volume_item = fake_client.VOLUME_ITEM_SIMPLE_RESPONSE_REST

        volume_name = path_to_file.split('/')[2]
        relative_path = '/'.join(path_to_file.split('/')[3:])

        query = {
            'type': 'rw',
            'style': 'flex*',  # Match both 'flexvol' and 'flexgroup'
            'is_svm_root': 'false',
            'error_state.is_inconsistent': 'false',
            'state': 'online',
            'name': volume_name,
            'fields': 'name,style'
        }
        self.mock_object(self.client, 'send_request',
                         return_value=volume_response)
        self.mock_object(self.client, '_get_unique_volume',
                         return_value=volume_item)
        self.client.delete_file(path_to_file)

        relative_path = relative_path.replace('/', '%2F').replace('.', '%2E')

        self.client.send_request.assert_has_calls([
            mock.call('/storage/volumes/', 'get', query=query),
            mock.call(f'/storage/volumes/{volume_item["uuid"]}'
                      + f'/files/{relative_path}', 'delete')
        ])

        self.client._get_unique_volume.assert_called_once_with(
            volume_response['records'])

    def test_get_igroup_by_initiators_none_found(self):
        initiator = 'initiator'
        expected_response = fake_client.NO_RECORDS_RESPONSE_REST

        self.mock_object(self.client, 'send_request',
                         return_value=expected_response)

        igroup_list = self.client.get_igroup_by_initiators([initiator])

        self.assertEqual([], igroup_list)

    def test_get_igroup_by_initiators(self):
        initiators = ['iqn.1993-08.org.fake:01:5b67769f5c5e']
        expected_igroup = [{
            'initiator-group-os-type': 'linux',
            'initiator-group-type': 'iscsi',
            'initiator-group-name':
                'openstack-e6bf1584-bfb3-4cdb-950d-525bf6f26b53'
        }]

        expected_query = {
            'svm.name': fake_client.VOLUME_VSERVER_NAME,
            'initiators.name': ' '.join(initiators),
            'fields': 'name,protocol,os_type'
        }

        self.mock_object(self.client, 'send_request',
                         return_value=fake_client.IGROUP_GET_ITER_REST)

        igroup_list = self.client.get_igroup_by_initiators(initiators)
        self.client.send_request.assert_called_once_with(
            '/protocols/san/igroups', 'get', query=expected_query)
        self.assertEqual(expected_igroup, igroup_list)

    def test_get_igroup_by_initiators_multiple(self):
        initiators = ['iqn.1993-08.org.fake:01:5b67769f5c5e',
                      'iqn.1993-08.org.fake:02:5b67769f5c5e']

        expected_igroup = [{
            'initiator-group-os-type': 'linux',
            'initiator-group-type': 'iscsi',
            'initiator-group-name':
                'openstack-e6bf1584-bfb3-4cdb-950d-525bf6f26b53'
        }]

        expected_query = {
            'svm.name': fake_client.VOLUME_VSERVER_NAME,
            'initiators.name': ' '.join(initiators),
            'fields': 'name,protocol,os_type'
        }

        self.mock_object(self.client, 'send_request',
                         return_value=fake_client.IGROUP_GET_ITER_INITS_REST)

        igroup_list = self.client.get_igroup_by_initiators(initiators)
        self.client.send_request.assert_called_once_with(
            '/protocols/san/igroups', 'get', query=expected_query)
        self.assertEqual(expected_igroup, igroup_list)

    def test_get_igroup_by_initiators_multiple_records(self):
        initiators = ['iqn.1993-08.org.fake:01:5b67769f5c5e']
        expected_element = {
            'initiator-group-os-type': 'linux',
            'initiator-group-type': 'iscsi',
            'initiator-group-name':
                'openstack-e6bf1584-bfb3-4cdb-950d-525bf6f26b53'
        }
        expected_igroup = [expected_element, expected_element]

        self.mock_object(self.client, 'send_request',
                         return_value=fake_client.IGROUP_GET_ITER_MULT_REST)

        igroup_list = self.client.get_igroup_by_initiators(initiators)
        self.assertEqual(expected_igroup, igroup_list)

    def test_add_igroup_initiator(self):
        igroup = 'fake_igroup'
        initiator = 'fake_initator'

        mock_return = fake_client.IGROUP_GET_ITER_REST
        expected_uuid = fake_client.IGROUP_GET_ITER_REST['records'][0]['uuid']
        mock_send_request = self.mock_object(self.client, 'send_request',
                                             return_value = mock_return)

        self.client.add_igroup_initiator(igroup, initiator)

        expected_body = {
            'name': initiator
        }
        mock_send_request.assert_has_calls([
            mock.call('/protocols/san/igroups/' +
                      expected_uuid + '/initiators',
                      'post', body=expected_body)])

    def test_create_igroup(self):
        igroup = 'fake_igroup'
        igroup_type = 'fake_type'
        os_type = 'fake_os'

        body = {
            'name': igroup,
            'protocol': igroup_type,
            'os_type': os_type,
        }

        self.mock_object(self.client, 'send_request')
        self.client.create_igroup(igroup, igroup_type, os_type)
        self.client.send_request.assert_called_once_with(
            '/protocols/san/igroups', 'post', body=body)

    @ddt.data(None, 0, 4095)
    def test_map_lun(self, lun_id):
        fake_record = fake_client.GET_LUN_MAP_REST['records'][0]
        path = fake_record['lun']['name']
        igroup_name = fake_record['igroup']['name']

        mock_send_request = self.mock_object(
            self.client, 'send_request',
            return_value=fake_client.GET_LUN_MAP_REST)

        result = self.client.map_lun(path, igroup_name, lun_id)

        self.assertEqual(0, result)
        expected_body = {
            'lun.name': path,
            'igroup.name': igroup_name,
        }
        if lun_id is not None:
            expected_body['logical_unit_number'] = lun_id

        mock_send_request.assert_has_calls([
            mock.call('/protocols/san/lun-maps', 'post',
                      body=expected_body, query={'return_records': 'true'})])

    def test_get_lun_map(self):
        fake_record = fake_client.GET_LUN_MAP_REST['records'][0]
        path = fake_record['lun']['name']

        expected_lun_map = [{
            'initiator-group': fake_record['igroup']['name'],
            'lun-id': fake_record['logical_unit_number'],
            'vserver': fake_record['svm']['name'],
        }]

        expected_query = {
            'lun.name': path,
            'fields': 'igroup.name,logical_unit_number,svm.name',
        }

        self.mock_object(self.client, 'send_request',
                         return_value=fake_client.GET_LUN_MAP_REST)

        lun_map = self.client.get_lun_map(path)
        self.assertEqual(observed=lun_map, expected=expected_lun_map)
        self.client.send_request.assert_called_once_with(
            '/protocols/san/lun-maps', 'get', query=expected_query)

    def test_get_lun_map_no_luns_mapped(self):
        fake_record = fake_client.GET_LUN_MAP_REST['records'][0]
        path = fake_record['lun']['name']

        expected_lun_map = []
        expected_query = {
            'lun.name': path,
            'fields': 'igroup.name,logical_unit_number,svm.name',
        }

        self.mock_object(self.client, 'send_request',
                         return_value = fake_client.NO_RECORDS_RESPONSE_REST)

        lun_map = self.client.get_lun_map(path)
        self.assertEqual(observed=lun_map, expected=expected_lun_map)
        self.client.send_request.assert_called_once_with(
            '/protocols/san/lun-maps', 'get', query=expected_query)

    def test_get_fc_target_wwpns(self):
        fake_record = fake_client.FC_INTERFACE_REST['records'][0]
        expected_wwpns = [fake_record['wwpn']]
        expected_query = {
            'fields': 'wwpn'
        }
        self.mock_object(self.client, 'send_request',
                         return_value = fake_client.FC_INTERFACE_REST)
        wwpns = self.client.get_fc_target_wwpns()
        self.assertEqual(observed=wwpns, expected=expected_wwpns)
        self.client.send_request.assert_called_once_with(
            '/network/fc/interfaces', 'get', query=expected_query)

    def test_get_fc_target_wwpns_not_found(self):
        expected_wwpns = []
        expected_query = {
            'fields': 'wwpn'
        }
        self.mock_object(self.client, 'send_request',
                         return_value = fake_client.NO_RECORDS_RESPONSE_REST)
        wwpns = self.client.get_fc_target_wwpns()
        self.assertEqual(observed=wwpns, expected=expected_wwpns)
        self.client.send_request.assert_called_once_with(
            '/network/fc/interfaces', 'get', query=expected_query)

    def test_unmap_lun(self):
        get_uuid_response = fake_client.GET_LUN_MAP_REST
        mock_send_request = self.mock_object(
            self.client, 'send_request',
            side_effect=[get_uuid_response, None])

        self.client.unmap_lun(fake_client.LUN_NAME_PATH,
                              fake_client.IGROUP_NAME)

        query_uuid = {
            'igroup.name': fake_client.IGROUP_NAME,
            'lun.name': fake_client.LUN_NAME_PATH,
            'fields': 'lun.uuid,igroup.uuid'
        }

        lun_uuid = get_uuid_response['records'][0]['lun']['uuid']
        igroup_uuid = get_uuid_response['records'][0]['igroup']['uuid']

        mock_send_request.assert_has_calls([
            mock.call('/protocols/san/lun-maps', 'get', query=query_uuid),
            mock.call(f'/protocols/san/lun-maps/{lun_uuid}/{igroup_uuid}',
                      'delete'),
        ])

    def test_unmap_lun_with_api_error(self):
        get_uuid_response = fake_client.GET_LUN_MAP_REST
        mock_send_request = self.mock_object(
            self.client, 'send_request',
            side_effect=[get_uuid_response, netapp_api.NaApiError()])

        self.assertRaises(netapp_api.NaApiError,
                          self.client.unmap_lun,
                          fake_client.LUN_NAME_PATH,
                          fake_client.IGROUP_NAME)

        query_uuid = {
            'igroup.name': fake_client.IGROUP_NAME,
            'lun.name': fake_client.LUN_NAME_PATH,
            'fields': 'lun.uuid,igroup.uuid'
        }

        lun_uuid = get_uuid_response['records'][0]['lun']['uuid']
        igroup_uuid = get_uuid_response['records'][0]['igroup']['uuid']

        mock_send_request.assert_has_calls([
            mock.call('/protocols/san/lun-maps', 'get', query=query_uuid),
            mock.call(f'/protocols/san/lun-maps/{lun_uuid}/{igroup_uuid}',
                      'delete'),
        ])

    def test_unmap_lun_invalid_input(self):
        get_uuid_response = fake_client.NO_RECORDS_RESPONSE_REST
        mock_send_request = self.mock_object(
            self.client, 'send_request',
            side_effect=[get_uuid_response,
                         None])

        self.client.unmap_lun(fake_client.LUN_NAME_PATH,
                              fake_client.IGROUP_NAME)

        query_uuid = {
            'igroup.name': fake_client.IGROUP_NAME,
            'lun.name': fake_client.LUN_NAME_PATH,
            'fields': 'lun.uuid,igroup.uuid'
        }

        mock_send_request.assert_called_once_with(
            '/protocols/san/lun-maps', 'get', query=query_uuid)

    def test_unmap_lun_not_mapped_in_group(self):
        get_uuid_response = fake_client.GET_LUN_MAP_REST

        # Exception REST_NO_SUCH_LUN_MAP is handled inside the function
        # and should not be re-raised
        mock_send_request = self.mock_object(
            self.client, 'send_request',
            side_effect=[
                get_uuid_response,
                netapp_api.NaApiError(
                    code=netapp_api.REST_NO_SUCH_LUN_MAP)])

        self.client.unmap_lun(fake_client.LUN_NAME_PATH,
                              fake_client.IGROUP_NAME)

        query_uuid = {
            'igroup.name': fake_client.IGROUP_NAME,
            'lun.name': fake_client.LUN_NAME_PATH,
            'fields': 'lun.uuid,igroup.uuid'
        }

        lun_uuid = get_uuid_response['records'][0]['lun']['uuid']
        igroup_uuid = get_uuid_response['records'][0]['igroup']['uuid']

        mock_send_request.assert_has_calls([
            mock.call('/protocols/san/lun-maps', 'get', query=query_uuid),
            mock.call(f'/protocols/san/lun-maps/{lun_uuid}/{igroup_uuid}',
                      'delete'),
        ])

    def test_has_luns_mapped_to_initiators(self):
        initiators = ['iqn.2005-03.org.open-iscsi:49ebe8a87d1']
        api_response = fake_client.GET_LUN_MAPS
        mock_send_request = self.mock_object(
            self.client, 'send_request', return_value=api_response)

        self.assertTrue(self.client.has_luns_mapped_to_initiators(initiators))

        query = {
            'initiators.name': ' '.join(initiators),
            'fields': 'lun_maps'
        }

        mock_send_request.assert_called_once_with(
            '/protocols/san/igroups', 'get', query=query)

    def test_has_luns_mapped_to_initiators_no_records(self):
        initiators = ['iqn.2005-03.org.open-iscsi:49ebe8a87d1']
        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        mock_send_request = self.mock_object(
            self.client, 'send_request', return_value=api_response)

        self.assertFalse(self.client.has_luns_mapped_to_initiators(initiators))

        query = {
            'initiators.name': ' '.join(initiators),
            'fields': 'lun_maps'
        }

        mock_send_request.assert_called_once_with(
            '/protocols/san/igroups', 'get', query=query)

    def test_has_luns_mapped_to_initiators_not_mapped(self):
        initiators = ['iqn.2005-03.org.open-iscsi:49ebe8a87d1']
        api_response = fake_client.GET_LUN_MAPS_NO_MAPS
        mock_send_request = self.mock_object(
            self.client, 'send_request', return_value=api_response)

        self.assertFalse(self.client.has_luns_mapped_to_initiators(initiators))

        query = {
            'initiators.name': ' '.join(initiators),
            'fields': 'lun_maps'
        }

        mock_send_request.assert_called_once_with(
            '/protocols/san/igroups', 'get', query=query)

    def test_iscsi_service_details(self):
        fake_record = fake_client.GET_ISCSI_SERVICE_DETAILS_REST['records'][0]
        expected_iqn = fake_record['target']['name']
        expected_query = {
            'fields': 'target.name'
        }
        mock_send_request = self.mock_object(
            self.client, 'send_request',
            return_value=fake_client.GET_ISCSI_SERVICE_DETAILS_REST)
        iqn = self.client.get_iscsi_service_details()
        self.assertEqual(expected_iqn, iqn)
        mock_send_request.assert_called_once_with(
            '/protocols/san/iscsi/services', 'get', query=expected_query)

    def test_iscsi_service_details_not_found(self):
        expected_iqn = None
        expected_query = {
            'fields': 'target.name'
        }
        mock_send_request = self.mock_object(
            self.client, 'send_request',
            return_value=fake_client.NO_RECORDS_RESPONSE_REST)
        iqn = self.client.get_iscsi_service_details()
        self.assertEqual(expected_iqn, iqn)
        mock_send_request.assert_called_once_with(
            '/protocols/san/iscsi/services', 'get', query=expected_query)

    def test_check_iscsi_initiator_exists(self):
        fake_record = fake_client.CHECK_ISCSI_INITIATOR_REST['records'][0]
        iqn = fake_record['initiator']
        expected_query = {
            'initiator': iqn
        }
        mock_send_request = self.mock_object(
            self.client, 'send_request',
            return_value=fake_client.CHECK_ISCSI_INITIATOR_REST)
        initiator_exists = self.client.check_iscsi_initiator_exists(iqn)
        self.assertEqual(expected=True, observed=initiator_exists)
        mock_send_request.assert_called_once_with(
            '/protocols/san/iscsi/credentials', 'get',
            query=expected_query)

    def test_check_iscsi_initiator_exists_not_found(self):
        fake_record = fake_client.CHECK_ISCSI_INITIATOR_REST['records'][0]
        iqn = fake_record['initiator']
        expected_query = {
            'initiator': iqn
        }
        mock_send_request = self.mock_object(
            self.client, 'send_request',
            return_value=fake_client.NO_RECORDS_RESPONSE_REST)
        initiator_exists = self.client.check_iscsi_initiator_exists(iqn)
        self.assertEqual(expected=False, observed=initiator_exists)
        mock_send_request.assert_called_once_with(
            '/protocols/san/iscsi/credentials', 'get',
            query=expected_query)

    def test_get_iscsi_target_details(self):
        fake_record = fake_client.GET_ISCSI_TARGET_DETAILS_REST['records'][0]
        expected_details = [{
            'address': fake_record['ip']['address'],
            'port': 3260,
            'tpgroup-tag': None,
            'interface-enabled': fake_record['enabled'],
        }]
        expected_query = {
            'services': 'data_iscsi',
            'fields': 'ip.address,enabled'
        }
        mock_send_request = self.mock_object(
            self.client, 'send_request',
            return_value=fake_client.GET_ISCSI_TARGET_DETAILS_REST)
        details = self.client.get_iscsi_target_details()
        self.assertEqual(expected_details, details)
        mock_send_request.assert_called_once_with('/network/ip/interfaces',
                                                  'get', query=expected_query)

    def test_get_iscsi_target_details_no_details(self):
        expected_details = []
        expected_query = {
            'services': 'data_iscsi',
            'fields': 'ip.address,enabled'
        }
        mock_send_request = self.mock_object(
            self.client, 'send_request',
            return_value=fake_client.NO_RECORDS_RESPONSE_REST)
        details = self.client.get_iscsi_target_details()
        self.assertEqual(expected_details, details)
        mock_send_request.assert_called_once_with('/network/ip/interfaces',
                                                  'get', query=expected_query)

    def test_move_lun(self):
        fake_cur_path = '/vol/fake_vol/fake_lun_cur'
        fake_new_path = '/vol/fake_vol/fake_lun_new'
        expected_query = {
            'svm.name': self.vserver,
            'name': fake_cur_path,
        }
        expected_body = {
            'name': fake_new_path,
        }
        mock_send_request = self.mock_object(self.client, 'send_request')
        self.client.move_lun(fake_cur_path, fake_new_path)
        mock_send_request.assert_called_once_with(
            '/storage/luns/', 'patch', query=expected_query,
            body=expected_body)

    @ddt.data(True, False)
    def test_clone_file_snapshot(self, overwrite_dest):
        fake_volume = fake_client.VOLUME_ITEM_SIMPLE_RESPONSE_REST
        self.client.features.BACKUP_CLONE_PARAM = True

        fake_name = fake.NFS_VOLUME['name']
        fake_new_name = fake.SNAPSHOT_NAME
        api_version = (1, 19)

        expected_body = {
            'volume': {
                'uuid': fake_volume['uuid'],
                'name': fake_volume['name']
            },
            'source_path': fake_name,
            'destination_path': fake_new_name,
            'is_backup': True
        }
        if overwrite_dest:
            api_version = (1, 20)
            expected_body['overwrite_destination'] = True

        self.mock_object(self.client, 'send_request')
        self.mock_object(self.client, '_get_volume_by_args',
                         return_value=fake_volume)
        self.mock_object(self.client.connection, 'get_api_version',
                         return_value=api_version)

        self.client.clone_file(
            fake_volume['name'], fake_name, fake_new_name, fake.VSERVER_NAME,
            is_snapshot=True, dest_exists=overwrite_dest)

        self.client.send_request.assert_has_calls([
            mock.call('/storage/file/clone', 'post', body=expected_body),
        ])

    def test_clone_lun(self):
        self.client.vserver = fake.VSERVER_NAME

        expected_body = {
            'svm': {
                'name': fake.VSERVER_NAME
            },
            'name': f'/vol/{fake.VOLUME_NAME}/{fake.SNAPSHOT_NAME}',
            'clone': {
                'source': {
                    'name': f'/vol/{fake.VOLUME_NAME}/{fake.LUN_NAME}',
                }
            },
            'space': {
                'guarantee': {
                    'requested': True,
                }
            },
            'qos_policy': {
                'name': fake.QOS_POLICY_GROUP_NAME,
            }
        }

        mock_send_request = self.mock_object(
            self.client, 'send_request', return_value=None)
        mock_validate_policy = self.mock_object(
            self.client, '_validate_qos_policy_group')

        self.client.clone_lun(
            volume=fake.VOLUME_NAME, name=fake.LUN_NAME,
            new_name=fake.SNAPSHOT_NAME,
            qos_policy_group_name=fake.QOS_POLICY_GROUP_NAME,
            is_snapshot=True)

        mock_validate_policy.assert_called_once_with(False)
        mock_send_request.assert_called_once_with(
            '/storage/luns', 'post', body=expected_body)

    @ddt.data(True, False)
    def test_destroy_lun(self, force=True):
        path = f'/vol/{fake_client.VOLUME_NAME}/{fake_client.FILE_NAME}'

        query = {}
        query['name'] = path
        query['svm'] = fake_client.VOLUME_VSERVER_NAME
        if force:
            query['allow_delete_while_mapped'] = 'true'

        self.mock_object(self.client, 'send_request')

        self.client.destroy_lun(path, force)

        self.client.send_request.assert_called_once_with('/storage/luns/',
                                                         'delete', query=query)

    def test_get_flexvol_capacity(self, ):

        api_response = fake_client.VOLUME_GET_ITER_CAPACITY_RESPONSE_REST
        volume_response = api_response['records'][0]
        mock_get_unique_vol = self.mock_object(
            self.client, '_get_volume_by_args', return_value=volume_response)

        capacity = self.client.get_flexvol_capacity(
            flexvol_path=fake.VOLUME_PATH, flexvol_name=fake.VOLUME_NAME)

        mock_get_unique_vol.assert_called_once_with(
            vol_name=fake.VOLUME_NAME, vol_path=fake.VOLUME_PATH,
            fields='name,space.available,space.afs_total')
        self.assertEqual(float(fake_client.VOLUME_SIZE_TOTAL),
                         capacity['size-total'])
        self.assertEqual(float(fake_client.VOLUME_SIZE_AVAILABLE),
                         capacity['size-available'])

    def test_get_flexvol_capacity_not_found(self):

        self.mock_object(
            self.client, '_get_volume_by_args',
            side_effect=exception.VolumeBackendAPIException(data="fake"))

        self.assertRaises(netapp_utils.NetAppDriverException,
                          self.client.get_flexvol_capacity,
                          flexvol_path='fake_path')

    def test_check_api_permissions(self):

        mock_log = self.mock_object(client_cmode_rest.LOG, 'warning')
        self.mock_object(self.client, 'check_cluster_api', return_value=True)

        self.client.check_api_permissions()

        self.client.check_cluster_api.assert_has_calls(
            [mock.call(key) for key in client_cmode_rest.SSC_API_MAP.keys()])
        self.assertEqual(0, mock_log.call_count)

    def test_check_api_permissions_failed_ssc_apis(self):

        def check_cluster_api(api):
            if api != '/storage/volumes':
                return False
            return True

        self.mock_object(self.client, 'check_cluster_api',
                         side_effect=check_cluster_api)

        mock_log = self.mock_object(client_cmode_rest.LOG, 'warning')

        self.client.check_api_permissions()

        self.assertEqual(1, mock_log.call_count)

    def test_check_api_permissions_failed_volume_api(self):

        def check_cluster_api(api):
            if api == '/storage/volumes':
                return False
            return True

        self.mock_object(self.client, 'check_cluster_api',
                         side_effect=check_cluster_api)

        mock_log = self.mock_object(client_cmode_rest.LOG, 'warning')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.check_api_permissions)

        self.assertEqual(0, mock_log.call_count)

    def test_check_cluster_api(self):

        endpoint_api = '/storage/volumes'
        endpoint_request = '/storage/volumes?return_records=false'
        mock_send_request = self.mock_object(self.client,
                                             'send_request',
                                             return_value=True)

        result = self.client.check_cluster_api(endpoint_api)

        mock_send_request.assert_has_calls([mock.call(endpoint_request, 'get',
                                            enable_tunneling=False)])
        self.assertTrue(result)

    def test_check_cluster_api_error(self):

        endpoint_api = '/storage/volumes'
        api_error = netapp_api.NaApiError(code=netapp_api.REST_UNAUTHORIZED)

        self.mock_object(self.client, 'send_request',
                         side_effect=[api_error])

        result = self.client.check_cluster_api(endpoint_api)

        self.assertFalse(result)

    def test_get_provisioning_options_from_flexvol(self):

        self.mock_object(self.client, 'get_flexvol',
                         return_value=fake_client.VOLUME_INFO_SSC)
        self.mock_object(self.client, 'get_flexvol_dedupe_info',
                         return_value=fake_client.VOLUME_DEDUPE_INFO_SSC)

        expected_prov_opts = {
            'aggregate': ['fake_aggr1'],
            'compression_enabled': False,
            'dedupe_enabled': True,
            'language': 'c.utf_8',
            'size': 1,
            'snapshot_policy': 'default',
            'snapshot_reserve': '5',
            'space_guarantee_type': 'none',
            'volume_type': 'rw',
            'is_flexgroup': False,
        }

        actual_prov_opts = self.client.get_provisioning_options_from_flexvol(
            fake_client.VOLUME_NAME)

        self.assertEqual(expected_prov_opts, actual_prov_opts)

    def test_flexvol_exists(self):

        api_response = fake_client.GET_NUM_RECORDS_RESPONSE_REST
        mock_send_request = self.mock_object(self.client,
                                             'send_request',
                                             return_value=api_response)

        result = self.client.flexvol_exists(fake_client.VOLUME_NAME)

        query = {
            'name': fake_client.VOLUME_NAME,
            'return_records': 'false'
        }

        mock_send_request.assert_has_calls([
            mock.call('/storage/volumes/', 'get', query=query)])
        self.assertTrue(result)

    def test_flexvol_exists_not_found(self):

        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        self.assertFalse(self.client.flexvol_exists(fake_client.VOLUME_NAME))

    @ddt.data(fake_client.VOLUME_AGGREGATE_NAME,
              [fake_client.VOLUME_AGGREGATE_NAME],
              [fake_client.VOLUME_AGGREGATE_NAMES[0],
               fake_client.VOLUME_AGGREGATE_NAMES[1]])
    def test_create_volume_async(self, aggregates):
        self.mock_object(self.client, 'send_request')

        self.client.create_volume_async(
            fake_client.VOLUME_NAME, aggregates, 100, volume_type='dp')

        body = {
            'name': fake_client.VOLUME_NAME,
            'size': 100 * units.Gi,
            'type': 'dp'
        }

        if isinstance(aggregates, list):
            body['style'] = 'flexgroup'
            body['aggregates'] = [{'name': aggr} for aggr in aggregates]
        else:
            body['style'] = 'flexvol'
            body['aggregates'] = [{'name': aggregates}]

        self.client.send_request.assert_called_once_with(
            '/storage/volumes/', 'post', body=body, wait_on_accepted=False)

    @ddt.data('dp', 'rw', None)
    def test_create_volume_async_with_extra_specs(self, volume_type):
        self.mock_object(self.client, 'send_request')

        aggregates = [fake_client.VOLUME_AGGREGATE_NAME]
        snapshot_policy = 'default'
        size = 100
        space_guarantee_type = 'volume'
        language = 'en-US'
        snapshot_reserve = 15

        self.client.create_volume_async(
            fake_client.VOLUME_NAME, aggregates, size,
            space_guarantee_type=space_guarantee_type, language=language,
            snapshot_policy=snapshot_policy, snapshot_reserve=snapshot_reserve,
            volume_type=volume_type)

        body = {
            'name': fake_client.VOLUME_NAME,
            'size': size * units.Gi,
            'type': volume_type,
            'guarantee': {'type': space_guarantee_type},
            'space': {'snapshot': {'reserve_percent': str(snapshot_reserve)}},
            'language': language,
        }

        if isinstance(aggregates, list):
            body['style'] = 'flexgroup'
            body['aggregates'] = [{'name': aggr} for aggr in aggregates]
        else:
            body['style'] = 'flexvol'
            body['aggregates'] = [{'name': aggregates}]

        if volume_type == 'dp':
            snapshot_policy = None
        else:
            body['nas'] = {'path': '/%s' % fake_client.VOLUME_NAME}

        if snapshot_policy is not None:
            body['snapshot_policy'] = {'name': snapshot_policy}

        self.client.send_request.assert_called_once_with(
            '/storage/volumes/', 'post', body=body, wait_on_accepted=False)

    def test_create_flexvol(self):
        aggregates = [fake_client.VOLUME_AGGREGATE_NAME]
        size = 100

        mock_response = {
            'job': {
                'uuid': fake.JOB_UUID,
            }
        }

        self.mock_object(self.client, 'send_request',
                         return_value=mock_response)

        expected_response = {
            'status': None,
            'jobid': fake.JOB_UUID,
            'error-code': None,
            'error-message': None
        }

        response = self.client.create_volume_async(fake_client.VOLUME_NAME,
                                                   aggregates, size_gb = size)
        self.assertEqual(expected_response, response)

    def test_enable_volume_dedupe_async(self):
        query = {
            'name': fake_client.VOLUME_NAME,
            'fields': 'uuid,style',
        }

        # This is needed because the first calling to send_request inside
        # enable_volume_dedupe_async must return a valid uuid for the given
        # volume name.
        mock_response = {
            'records': [
                {
                    'uuid': fake.JOB_UUID,
                    'name': fake_client.VOLUME_NAME,
                    "style": 'flexgroup',
                }
            ],
            "num_records": 1,
        }

        body = {
            'efficiency': {'dedupe': 'background'}
        }

        mock_send_request = self.mock_object(self.client, 'send_request',
                                             return_value=mock_response)

        call_list = [mock.call('/storage/volumes/',
                               'patch', body=body, query=query,
                               wait_on_accepted=False)]

        self.client.enable_volume_dedupe_async(fake_client.VOLUME_NAME)
        mock_send_request.assert_has_calls(call_list)

    def test_enable_volume_compression_async(self):
        query = {
            'name': fake_client.VOLUME_NAME,
        }

        # This is needed because the first calling to send_request inside
        # enable_volume_compression_async must return a valid uuid for the
        # given volume name.
        mock_response = {
            'records': [
                {
                    'uuid': fake.JOB_UUID,
                    'name': fake_client.VOLUME_NAME,
                    "style": 'flexgroup',
                }
            ],
            "num_records": 1,
        }

        body = {
            'efficiency': {'compression': 'background'}
        }

        mock_send_request = self.mock_object(self.client, 'send_request',
                                             return_value=mock_response)

        call_list = [mock.call('/storage/volumes/',
                               'patch', body=body, query=query,
                               wait_on_accepted=False)]

        self.client.enable_volume_compression_async(fake_client.VOLUME_NAME)
        mock_send_request.assert_has_calls(call_list)

    def test__get_snapmirrors(self):

        api_response = fake_client.SNAPMIRROR_GET_ITER_RESPONSE_REST
        mock_send_request = self.mock_object(self.client,
                                             'send_request',
                                             return_value=api_response)

        result = self.client._get_snapmirrors(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        query = {
            'source.path': (fake_client.SM_SOURCE_VSERVER + ':' +
                            fake_client.SM_SOURCE_VOLUME),
            'destination.path': (fake_client.SM_DEST_VSERVER +
                                 ':' + fake_client.SM_DEST_VOLUME),
            'fields': 'state,source.svm.name,source.path,destination.svm.name,'
                      'destination.path,transfer.state,transfer.end_time,'
                      'lag_time,healthy,uuid'
        }

        mock_send_request.assert_called_once_with('/snapmirror/relationships',
                                                  'get', query=query)
        self.assertEqual(1, len(result))

    def test__get_snapmirrors_not_found(self):

        api_response = fake_client.NO_RECORDS_RESPONSE_REST
        mock_send_request = self.mock_object(self.client,
                                             'send_request',
                                             return_value=api_response)

        result = self.client._get_snapmirrors(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        query = {
            'source.path': (fake_client.SM_SOURCE_VSERVER + ':' +
                            fake_client.SM_SOURCE_VOLUME),
            'destination.path': (fake_client.SM_DEST_VSERVER +
                                 ':' + fake_client.SM_DEST_VOLUME),
            'fields': 'state,source.svm.name,source.path,destination.svm.name,'
                      'destination.path,transfer.state,transfer.end_time,'
                      'lag_time,healthy,uuid'
        }

        mock_send_request.assert_called_once_with('/snapmirror/relationships',
                                                  'get', query=query)
        self.assertEqual([], result)

    def test_get_snapmirrors(self):

        api_response = fake_client.SNAPMIRROR_GET_ITER_RESPONSE_REST
        mock_send_request = self.mock_object(self.client,
                                             'send_request',
                                             return_value=api_response)

        result = self.client.get_snapmirrors(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        expected = fake_client.REST_GET_SNAPMIRRORS_RESPONSE

        query = {
            'source.path': (fake_client.SM_SOURCE_VSERVER + ':' +
                            fake_client.SM_SOURCE_VOLUME),
            'destination.path': (fake_client.SM_DEST_VSERVER +
                                 ':' + fake_client.SM_DEST_VOLUME),
            'fields': 'state,source.svm.name,source.path,destination.svm.name,'
                      'destination.path,transfer.state,transfer.end_time,'
                      'lag_time,healthy,uuid'
        }

        mock_send_request.assert_called_once_with('/snapmirror/relationships',
                                                  'get', query=query)
        self.assertEqual(expected, result)

    @ddt.data({'policy': 'fake_policy'},
              {'policy': None})
    @ddt.unpack
    def test_create_snapmirror(self, policy):
        api_responses = [
            {
                "job": {
                    "uuid": fake_client.FAKE_UUID,
                },
            },
        ]
        self.mock_object(self.client, 'send_request',
                         side_effect = copy.deepcopy(api_responses))
        self.client.create_snapmirror(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME,
            policy=policy)

        body = {
            'source': {
                'path': (fake_client.SM_SOURCE_VSERVER + ':' +
                         fake_client.SM_SOURCE_VOLUME),
            },
            'destination': {
                'path': (fake_client.SM_DEST_VSERVER + ':' +
                         fake_client.SM_DEST_VOLUME)
            }
        }

        if policy:
            body['policy'] = {'name': policy}
        self.client.send_request.assert_has_calls([
            mock.call('/snapmirror/relationships/', 'post', body=body)])

    @ddt.data(
        {
            'policy': None,
            'sm_source_cg': fake_client.SM_SOURCE_CG,
            'sm_destination_cg': fake_client.SM_DESTINATION_CG,
        },
        {
            'policy': None,
            'sm_source_cg': None,
            'sm_destination_cg': None,
        },
        {
            'policy': 'AutomatedFailOver',
            'sm_source_cg': fake_client.SM_SOURCE_CG,
            'sm_destination_cg': fake_client.SM_DESTINATION_CG,
        },
        {
            'policy': 'AutomatedFailOver',
            'sm_source_cg': None,
            'sm_destination_cg': None,
        },
    )
    @ddt.unpack
    def test_create_snapmirror_active_sync(self, policy,
                                           sm_source_cg, sm_destination_cg):
        """Tests creation of snapmirror with active sync"""
        api_responses = [
            {
                "job": {
                    "uuid": fake_client.FAKE_UUID,
                },
            },
        ]
        body = {}
        self.mock_object(self.client, 'send_request',
                         side_effect = copy.deepcopy(api_responses))
        self.client.create_snapmirror(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME,
            sm_source_cg, sm_destination_cg,
            policy=policy)

        if sm_source_cg is not None and sm_destination_cg is not None:
            body = {
                'source': {
                    'path':
                        fake_client.SM_SOURCE_VSERVER + ':/cg/' +
                        sm_source_cg,
                    'consistency_group_volumes': [
                        {'name': fake_client.SM_SOURCE_VOLUME}]
                },
                'destination': {
                        'path': fake_client.SM_DEST_VSERVER + ':/cg/' +
                        sm_destination_cg,
                        'consistency_group_volumes': [
                            {'name': fake_client.SM_DEST_VOLUME}]
                }
            }
        else:
            body = {
                'source': {
                    'path': fake_client.SM_SOURCE_VSERVER + ':' +
                    fake_client.SM_SOURCE_VOLUME
                },
                'destination': {
                    'path': fake_client.SM_DEST_VSERVER + ':' +
                    fake_client.SM_DEST_VOLUME
                },
            }

        if policy:
            body['policy'] = {'name': policy}
        if bool(body):
            self.client.send_request.assert_has_calls([
                mock.call('/snapmirror/relationships/', 'post', body=body)])

    def test_create_snapmirror_already_exists(self):
        api_responses = netapp_api.NaApiError(
            code=netapp_api.REST_ERELATION_EXISTS)
        self.mock_object(self.client, 'send_request',
                         side_effect=api_responses)

        response = self.client.create_snapmirror(
            fake_client.SM_SOURCE_VSERVER,
            fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER,
            fake_client.SM_DEST_VOLUME,
            schedule=None,
            policy=None,
            relationship_type='data_protection')
        self.assertIsNone(response)
        self.assertTrue(self.client.send_request.called)

    def test_create_snapmirror_error(self):
        self.mock_object(self.client, 'send_request',
                         side_effect=netapp_api.NaApiError(code=123))

        self.assertRaises(netapp_api.NaApiError,
                          self.client.create_snapmirror,
                          fake_client.SM_SOURCE_VSERVER,
                          fake_client.SM_SOURCE_VOLUME,
                          fake_client.SM_DEST_VSERVER,
                          fake_client.SM_DEST_VOLUME,
                          schedule=None,
                          policy=None,
                          relationship_type='data_protection')
        self.assertTrue(self.client.send_request.called)

    def test_create_ontap_consistency_group(self):
        """Tests creation of consistency group for active sync policies"""
        api_responses = [
            {
                "job": {
                    "uuid": fake_client.FAKE_UUID,
                },
            },
        ]
        self.mock_object(self.client, 'send_request',
                         side_effect = copy.deepcopy(api_responses))
        self.client.create_ontap_consistency_group(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_SOURCE_CG)

        body = {
            'svm': {
                'name': fake_client.SM_SOURCE_VSERVER
            },
            'name': fake_client.SM_SOURCE_CG,
            'volumes': [{
                'name': fake_client.SM_SOURCE_VOLUME,
                "provisioning_options": {"action": "add"}
            }]
        }
        self.client.send_request.assert_has_calls([
            mock.call('/application/consistency-groups/', 'post', body=body)])

    def test__set_snapmirror_state(self):
        api_responses = [
            fake_client.SNAPMIRROR_GET_ITER_RESPONSE_REST,
            {
                "job":
                {
                    "uuid": fake_client.FAKE_UUID
                },
                "num_records": 1
            }
        ]

        expected_body = {'state': 'snapmirrored'}
        self.mock_object(self.client,
                         'send_request',
                         side_effect=copy.deepcopy(api_responses))

        result = self.client._set_snapmirror_state(
            'snapmirrored',
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        self.client.send_request.assert_has_calls([
            mock.call('/snapmirror/relationships/' + fake_client.FAKE_UUID,
                      'patch', body=expected_body, wait_on_accepted=True)])

        expected = {
            'operation-id': None,
            'status': None,
            'jobid': fake_client.FAKE_UUID,
            'error-code': None,
            'error-message': None,
            'relationship-uuid': fake_client.FAKE_UUID
        }
        self.assertEqual(expected, result)

    def test_initialize_snapmirror(self):

        expected_job = {
            'operation-id': None,
            'status': None,
            'jobid': fake_client.FAKE_UUID,
            'error-code': None,
            'error-message': None,
        }

        mock_set_snapmirror_state = self.mock_object(
            self.client,
            '_set_snapmirror_state',
            return_value=expected_job)

        result = self.client.initialize_snapmirror(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        mock_set_snapmirror_state.assert_called_once_with(
            'snapmirrored',
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME,
            wait_result=False)

        self.assertEqual(expected_job, result)

    @ddt.data(True, False)
    def test_abort_snapmirror(self, clear_checkpoint):

        self.mock_object(
            self.client, 'get_snapmirrors',
            return_value=fake_client.REST_GET_SNAPMIRRORS_RESPONSE)
        responses = [fake_client.TRANSFERS_GET_ITER_REST, None, None]
        self.mock_object(self.client, 'send_request',
                         side_effect=copy.deepcopy(responses))

        self.client.abort_snapmirror(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME,
            clear_checkpoint=clear_checkpoint)

        body = {'state': 'hard_aborted' if clear_checkpoint else 'aborted'}
        query = {'state': 'transferring'}
        self.client.send_request.assert_has_calls([
            mock.call('/snapmirror/relationships/' +
                      fake_client.FAKE_UUID + '/transfers/', 'get',
                      query=query),
            mock.call('/snapmirror/relationships/' +
                      fake_client.FAKE_UUID + '/transfers/' +
                      fake_client.FAKE_UUID, 'patch', body=body)])
        self.client.get_snapmirrors.assert_called_once_with(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

    def test_abort_snapmirror_no_transfer_in_progress(self):

        self.mock_object(self.client, 'send_request',
                         return_value=fake_client.NO_RECORDS_RESPONSE_REST)
        self.mock_object(
            self.client, 'get_snapmirrors',
            return_value=fake_client.REST_GET_SNAPMIRRORS_RESPONSE)

        self.assertRaises(netapp_api.NaApiError,
                          self.client.abort_snapmirror,
                          fake_client.SM_SOURCE_VSERVER,
                          fake_client.SM_SOURCE_VOLUME,
                          fake_client.SM_DEST_VSERVER,
                          fake_client.SM_DEST_VOLUME,
                          clear_checkpoint=True)

        query = {'state': 'transferring'}
        self.client.send_request.assert_has_calls([
            mock.call('/snapmirror/relationships/' + fake_client.FAKE_UUID +
                      '/transfers/', 'get', query=query)])

    def test_delete_snapmirror(self):

        response_list = [fake_client.SNAPMIRROR_GET_ITER_RESPONSE_REST,
                         fake_client.JOB_RESPONSE_REST,
                         fake_client.JOB_SUCCESSFUL_REST]

        self.mock_object(self.client, 'send_request',
                         side_effect=copy.deepcopy(response_list))

        self.client.delete_snapmirror(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        query_uuid = {}
        query_uuid['source.path'] = (fake_client.SM_SOURCE_VSERVER + ':' +
                                     fake_client.SM_SOURCE_VOLUME)
        query_uuid['destination.path'] = (fake_client.SM_DEST_VSERVER + ':' +
                                          fake_client.SM_DEST_VOLUME)
        query_uuid['fields'] = 'uuid'

        query_delete = {"destination_only": "true"}
        self.client.send_request.assert_has_calls([
            mock.call('/snapmirror/relationships/', 'get', query=query_uuid),
            mock.call('/snapmirror/relationships/' + fake_client.FAKE_UUID,
                      'delete', query=query_delete)])

    def test_delete_snapmirror_timeout(self):
        # when a timeout happens, an exception is thrown by send_request
        api_error = netapp_api.NaRetryableError()
        self.mock_object(self.client, 'send_request',
                         side_effect=api_error)

        self.assertRaises(netapp_api.NaRetryableError,
                          self.client.delete_snapmirror,
                          fake_client.SM_SOURCE_VSERVER,
                          fake_client.SM_SOURCE_VOLUME,
                          fake_client.SM_DEST_VSERVER,
                          fake_client.SM_DEST_VOLUME)

    @ddt.data('async', 'sync')
    def test_resume_snapmirror(self, snapmirror_policy):
        snapmirror_response = copy.deepcopy(
            fake_client.SNAPMIRROR_GET_ITER_RESPONSE_REST)
        snapmirror_response['records'][0]['policy'] = {
            'type': snapmirror_policy}

        if snapmirror_policy == 'async':
            snapmirror_response['state'] = 'snapmirrored'
        elif snapmirror_policy == 'sync':
            snapmirror_response['state'] = 'in_sync'

        response_list = [snapmirror_response,
                         fake_client.JOB_RESPONSE_REST,
                         snapmirror_response]

        self.mock_object(self.client, 'send_request',
                         side_effect=copy.deepcopy(response_list))

        self.client.resync_snapmirror(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        query_uuid = {}
        query_uuid['source.path'] = (fake_client.SM_SOURCE_VSERVER + ':' +
                                     fake_client.SM_SOURCE_VOLUME)
        query_uuid['destination.path'] = (fake_client.SM_DEST_VSERVER + ':' +
                                          fake_client.SM_DEST_VOLUME)
        query_uuid['fields'] = 'uuid,policy.type'

        body_resync = {}
        if snapmirror_policy == 'async':
            body_resync['state'] = 'snapmirrored'
        elif snapmirror_policy == 'sync':
            body_resync['state'] = 'in_sync'

        self.client.send_request.assert_has_calls([
            mock.call('/snapmirror/relationships/', 'get', query=query_uuid),
            mock.call('/snapmirror/relationships/' + fake_client.FAKE_UUID,
                      'patch', body=body_resync)])

    def test_resume_snapmirror_not_found(self):
        query_uuid = {}
        query_uuid['source.path'] = (fake_client.SM_SOURCE_VSERVER + ':' +
                                     fake_client.SM_SOURCE_VOLUME)
        query_uuid['destination.path'] = (fake_client.SM_DEST_VSERVER + ':' +
                                          fake_client.SM_DEST_VOLUME)
        query_uuid['fields'] = 'uuid,policy.type'

        self.mock_object(
            self.client, 'send_request',
            return_value={'records': []})

        self.assertRaises(
            netapp_api.NaApiError,
            self.client.resume_snapmirror,
            fake_client.SM_SOURCE_VSERVER,
            fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER,
            fake_client.SM_DEST_VOLUME)

        self.client.send_request.assert_called_once_with(
            '/snapmirror/relationships/', 'get', query=query_uuid)

    def test_resume_snapmirror_api_error(self):
        query_resume = {}
        query_resume['source.path'] = (fake_client.SM_SOURCE_VSERVER + ':' +
                                       fake_client.SM_SOURCE_VOLUME)
        query_resume['destination.path'] = (fake_client.SM_DEST_VSERVER + ':' +
                                            fake_client.SM_DEST_VOLUME)

        query_uuid = copy.deepcopy(query_resume)
        query_uuid['fields'] = 'uuid,policy.type'

        api_error = netapp_api.NaApiError(code=0)
        self.mock_object(
            self.client, 'send_request',
            side_effect=[fake_client.SNAPMIRROR_GET_ITER_RESPONSE_REST,
                         api_error])

        self.assertRaises(netapp_api.NaApiError,
                          self.client.resume_snapmirror,
                          fake_client.SM_SOURCE_VSERVER,
                          fake_client.SM_SOURCE_VOLUME,
                          fake_client.SM_DEST_VSERVER,
                          fake_client.SM_DEST_VOLUME)

    @ddt.data(True, False)
    def test_release_snapmirror(self, relationship_info_only):

        response_list = [fake_client.SNAPMIRROR_GET_ITER_RESPONSE_REST,
                         fake_client.JOB_RESPONSE_REST,
                         fake_client.JOB_SUCCESSFUL_REST]

        self.mock_object(self.client, 'send_request',
                         side_effect=copy.deepcopy(response_list))

        self.client.release_snapmirror(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME,
            relationship_info_only)

        query_uuid = {}
        query_uuid['list_destinations_only'] = 'true'
        query_uuid['source.path'] = (fake_client.SM_SOURCE_VSERVER + ':' +
                                     fake_client.SM_SOURCE_VOLUME)
        query_uuid['destination.path'] = (fake_client.SM_DEST_VSERVER + ':' +
                                          fake_client.SM_DEST_VOLUME)
        query_uuid['fields'] = 'uuid'

        query_release = {}
        if relationship_info_only:
            # release WITHOUT removing related snapshots
            query_release['source_info_only'] = 'true'
        else:
            # release and REMOVING all related snapshots
            query_release['source_only'] = 'true'

        self.client.send_request.assert_has_calls([
            mock.call('/snapmirror/relationships/', 'get', query=query_uuid),
            mock.call('/snapmirror/relationships/' + fake_client.FAKE_UUID,
                      'delete', query=query_release)])

    def test_release_snapmirror_timeout(self):
        # when a timeout happens, an exception is thrown by send_request
        api_error = netapp_api.NaRetryableError()
        self.mock_object(self.client, 'send_request',
                         side_effect=api_error)

        self.assertRaises(netapp_api.NaRetryableError,
                          self.client.release_snapmirror,
                          fake_client.SM_SOURCE_VSERVER,
                          fake_client.SM_SOURCE_VOLUME,
                          fake_client.SM_DEST_VSERVER,
                          fake_client.SM_DEST_VOLUME)

    @ddt.data('async', 'sync')
    def test_resync_snapmirror(self, snapmirror_policy):

        snapmirror_response = copy.deepcopy(
            fake_client.SNAPMIRROR_GET_ITER_RESPONSE_REST)
        snapmirror_response['records'][0]['policy'] = {
            'type': snapmirror_policy}

        if snapmirror_policy == 'async':
            snapmirror_response['state'] = 'snapmirrored'
        elif snapmirror_policy == 'sync':
            snapmirror_response['state'] = 'in_sync'

        response_list = [snapmirror_response,
                         fake_client.JOB_RESPONSE_REST,
                         snapmirror_response]

        self.mock_object(self.client, 'send_request',
                         side_effect=copy.deepcopy(response_list))

        self.client.resync_snapmirror(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        query_uuid = {}
        query_uuid['source.path'] = (fake_client.SM_SOURCE_VSERVER + ':' +
                                     fake_client.SM_SOURCE_VOLUME)
        query_uuid['destination.path'] = (fake_client.SM_DEST_VSERVER + ':' +
                                          fake_client.SM_DEST_VOLUME)
        query_uuid['fields'] = 'uuid,policy.type'

        body_resync = {}
        if snapmirror_policy == 'async':
            body_resync['state'] = 'snapmirrored'
        elif snapmirror_policy == 'sync':
            body_resync['state'] = 'in_sync'

        self.client.send_request.assert_has_calls([
            mock.call('/snapmirror/relationships/', 'get', query=query_uuid),
            mock.call('/snapmirror/relationships/' + fake_client.FAKE_UUID,
                      'patch', body=body_resync)])

    def test_resync_snapmirror_timeout(self):
        api_error = netapp_api.NaRetryableError()
        self.mock_object(self.client, 'resume_snapmirror',
                         side_effect=api_error)

        self.assertRaises(netapp_api.NaRetryableError,
                          self.client.resync_snapmirror,
                          fake_client.SM_SOURCE_VSERVER,
                          fake_client.SM_SOURCE_VOLUME,
                          fake_client.SM_DEST_VSERVER,
                          fake_client.SM_DEST_VOLUME)

    def test_quiesce_snapmirror(self):

        expected_job = {
            'operation-id': None,
            'status': None,
            'jobid': fake_client.FAKE_UUID,
            'error-code': None,
            'error-message': None,
            'relationship-uuid': fake_client.FAKE_UUID,
        }

        mock_set_snapmirror_state = self.mock_object(
            self.client,
            '_set_snapmirror_state',
            return_value=expected_job)

        result = self.client.quiesce_snapmirror(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        mock_set_snapmirror_state.assert_called_once_with(
            'paused',
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        self.assertEqual(expected_job, result)

    def test_break_snapmirror(self):
        fake_snapmirror = fake_client.REST_GET_SNAPMIRRORS_RESPONSE
        fake_uuid = fake_snapmirror[0]['uuid']
        fake_body = {'state': 'broken_off'}

        self.mock_object(self.client, 'send_request')

        mock_get_snap = self.mock_object(
            self.client, '_get_snapmirrors',
            mock.Mock(return_value=fake_snapmirror))

        self.client.break_snapmirror(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        mock_get_snap.assert_called_once()
        self.client.send_request.assert_called_once_with(
            f'/snapmirror/relationships/{fake_uuid}', 'patch', body=fake_body)

    def test_break_snapmirror_not_found(self):
        self.mock_object(
            self.client, 'send_request',
            return_value={'records': []})

        self.assertRaises(
            netapp_utils.NetAppDriverException,
            self.client.break_snapmirror,
            fake_client.SM_SOURCE_VSERVER,
            fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER,
            fake_client.SM_DEST_VOLUME)

    def test__break_snapmirror_error(self):
        fake_snapmirror = fake_client.REST_GET_SNAPMIRRORS_RESPONSE
        self.mock_object(self.client, '_get_snapmirrors',
                         return_value=fake_snapmirror)
        self.mock_object(self.client, 'send_request',
                         side_effect=self._mock_api_error())
        self.assertRaises(netapp_api.NaApiError,
                          self.client.break_snapmirror,
                          fake_client.SM_SOURCE_VSERVER,
                          fake_client.SM_SOURCE_VOLUME,
                          fake_client.SM_DEST_VSERVER,
                          fake_client.SM_DEST_VOLUME)

    def test__break_snapmirror_exception(self):
        fake_snapmirror = copy.deepcopy(
            fake_client.REST_GET_SNAPMIRRORS_RESPONSE)
        fake_snapmirror[0]['transferring-state'] = 'error'

        self.mock_object(
            self.client, '_get_snapmirrors',
            mock.Mock(return_value=fake_snapmirror))

        self.assertRaises(netapp_utils.NetAppDriverException,
                          self.client.break_snapmirror,
                          fake_client.SM_SOURCE_VSERVER,
                          fake_client.SM_SOURCE_VOLUME,
                          fake_client.SM_DEST_VSERVER,
                          fake_client.SM_DEST_VOLUME)

    def test_update_snapmirror(self):

        snapmirrors = fake_client.REST_GET_SNAPMIRRORS_RESPONSE
        self.mock_object(self.client, 'send_request')
        self.mock_object(self.client, 'get_snapmirrors',
                         return_value=snapmirrors)

        self.client.update_snapmirror(
            fake_client.SM_SOURCE_VSERVER, fake_client.SM_SOURCE_VOLUME,
            fake_client.SM_DEST_VSERVER, fake_client.SM_DEST_VOLUME)

        self.client.send_request.assert_has_calls([
            mock.call('/snapmirror/relationships/' +
                      snapmirrors[0]['uuid'] + '/transfers/', 'post',
                      wait_on_accepted=False)])

    def test_update_snapmirror_no_records(self):

        self.mock_object(self.client, 'send_request')
        self.mock_object(self.client, 'get_snapmirrors',
                         return_value=[])

        self.assertRaises(netapp_utils.NetAppDriverException,
                          self.client.update_snapmirror,
                          fake_client.SM_SOURCE_VSERVER,
                          fake_client.SM_SOURCE_VOLUME,
                          fake_client.SM_DEST_VSERVER,
                          fake_client.SM_DEST_VOLUME)

        self.client.send_request.assert_not_called()

    def test_update_snapmirror_exception(self):

        snapmirrors = fake_client.REST_GET_SNAPMIRRORS_RESPONSE
        api_error = netapp_api.NaApiError(
            code=netapp_api.REST_UPDATE_SNAPMIRROR_FAILED)
        self.mock_object(self.client, 'send_request',
                         side_effect=api_error)
        self.mock_object(self.client, 'get_snapmirrors',
                         return_value=snapmirrors)

        self.assertRaises(netapp_api.NaApiError,
                          self.client.update_snapmirror,
                          fake_client.SM_SOURCE_VSERVER,
                          fake_client.SM_SOURCE_VOLUME,
                          fake_client.SM_DEST_VSERVER,
                          fake_client.SM_DEST_VOLUME)

        self.client.send_request.assert_has_calls([
            mock.call('/snapmirror/relationships/' +
                      snapmirrors[0]['uuid'] + '/transfers/', 'post',
                      wait_on_accepted=False)])

    def test_mount_flexvol(self):
        volumes = fake_client.VOLUME_GET_ITER_SSC_RESPONSE_REST
        self.mock_object(self.client, 'send_request',
                         side_effect=[volumes, None])

        fake_path = '/fake_path'
        fake_vol_name = volumes['records'][0]['name']

        body = {
            'nas.path': fake_path
        }
        query = {
            'name': fake_vol_name
        }

        self.client.mount_flexvol(fake_client.VOLUME_NAME,
                                  junction_path=fake_path)

        self.client.send_request.assert_has_calls([
            mock.call('/storage/volumes', 'patch', body=body, query=query)])

    def test_mount_flexvol_default_junction_path(self):
        volumes = fake_client.VOLUME_GET_ITER_SSC_RESPONSE_REST
        self.mock_object(self.client, 'send_request',
                         side_effect=[volumes, None])

        fake_vol_name = volumes['records'][0]['name']
        body = {
            'nas.path': '/' + fake_client.VOLUME_NAME
        }
        query = {
            'name': fake_vol_name
        }

        self.client.mount_flexvol(fake_client.VOLUME_NAME)

        self.client.send_request.assert_has_calls([
            mock.call('/storage/volumes', 'patch', body=body, query=query)])

    def test_get_cluster_name(self):
        query = {'fields': 'name'}

        self.mock_object(
            self.client, 'send_request',
            return_value=fake_client.GET_CLUSTER_NAME_RESPONSE_REST)

        result = self.client.get_cluster_name()

        self.client.send_request.assert_called_once_with(
            '/cluster', 'get', query=query, enable_tunneling=False)
        self.assertEqual(
            fake_client.GET_CLUSTER_NAME_RESPONSE_REST['name'], result)

    @ddt.data(
        (fake_client.VSERVER_NAME, fake_client.VSERVER_NAME_2),
        (fake_client.VSERVER_NAME, None),
        (None, fake_client.VSERVER_NAME_2),
        (None, None))
    @ddt.unpack
    def test_get_vserver_peers(self, svm_name, peer_svm_name):
        query = {
            'fields': 'svm.name,state,peer.svm.name,peer.cluster.name,'
                      'applications'
        }
        if peer_svm_name:
            query['name'] = peer_svm_name
        if svm_name:
            query['svm.name'] = svm_name

        vserver_info = fake_client.GET_VSERVER_PEERS_RECORDS_REST[0]

        expected_result = [{
            'vserver': vserver_info['svm']['name'],
            'peer-vserver': vserver_info['peer']['svm']['name'],
            'peer-state': vserver_info['state'],
            'peer-cluster': vserver_info['peer']['cluster']['name'],
            'applications': vserver_info['applications'],
        }]

        self.mock_object(
            self.client, 'send_request',
            return_value=fake_client.GET_VSERVER_PEERS_RESPONSE_REST)

        result = self.client.get_vserver_peers(
            vserver_name=svm_name, peer_vserver_name=peer_svm_name)

        self.client.send_request.assert_called_once_with(
            '/svm/peers', 'get', query=query, enable_tunneling=False)
        self.assertEqual(expected_result, result)

    def test_get_vserver_peers_empty(self):
        vserver_peers_response = copy.deepcopy(
            fake_client.GET_VSERVER_PEERS_RESPONSE_REST)
        vserver_peers_response['records'] = []
        vserver_peers_response['num_records'] = 0
        query = {
            'fields': 'svm.name,state,peer.svm.name,peer.cluster.name,'
                      'applications'
        }
        self.mock_object(
            self.client, 'send_request', return_value=vserver_peers_response)

        result = self.client.get_vserver_peers()

        self.client.send_request.assert_called_once_with(
            '/svm/peers', 'get', query=query, enable_tunneling=False)
        self.assertEqual([], result)

    @ddt.data(['snapmirror', 'lun_copy'], None)
    def test_create_vserver_peer(self, applications):
        body = {
            'svm.name': fake_client.VSERVER_NAME,
            'name': fake_client.VSERVER_NAME_2,
            'applications': applications if applications else ['snapmirror']
        }

        self.mock_object(self.client, 'send_request')

        self.client.create_vserver_peer(
            fake_client.VSERVER_NAME, fake_client.VSERVER_NAME_2,
            vserver_peer_application=applications)

        self.client.send_request.assert_called_once_with(
            '/svm/peers', 'post', body=body, enable_tunneling=False)

    @ddt.data(
        (fake.VOLUME_NAME, fake.LUN_NAME),
        (None, fake.LUN_NAME),
        (fake.VOLUME_NAME, None),
        (None, None)
    )
    @ddt.unpack
    def test_start_lun_move(self, src_vol, dest_lun):
        src_lun = f'src-lun-{fake.LUN_NAME}'
        dest_vol = f'dest-vol-{fake.VOLUME_NAME}'

        src_path = f'/vol/{src_vol if src_vol else dest_vol}/{src_lun}'
        dest_path = f'/vol/{dest_vol}/{dest_lun if dest_lun else src_lun}'
        body = {'name': dest_path}

        self.mock_object(self.client, '_lun_update_by_path')

        result = self.client.start_lun_move(
            src_lun, dest_vol, src_ontap_volume=src_vol,
            dest_lun_name=dest_lun)

        self.client._lun_update_by_path.assert_called_once_with(
            src_path, body)
        self.assertEqual(dest_path, result)

    @ddt.data(fake_client.LUN_GET_MOVEMENT_REST, None)
    def test_get_lun_move_status(self, lun_moved):
        dest_path = f'/vol/{fake.VOLUME_NAME}/{fake.LUN_NAME}'
        move_status = None
        if lun_moved:
            move_progress = lun_moved['movement']['progress']
            move_status = {
                'job-status': move_progress['state'],
                'last-failure-reason': move_progress['failure']['message']
            }

        self.mock_object(self.client, '_get_first_lun_by_path',
                         return_value=lun_moved)

        result = self.client.get_lun_move_status(dest_path)

        self.client._get_first_lun_by_path.assert_called_once_with(
            dest_path, fields='movement.progress')
        self.assertEqual(move_status, result)

    @ddt.data(
        (fake.VOLUME_NAME, fake.LUN_NAME),
        (None, fake.LUN_NAME),
        (fake.VOLUME_NAME, None),
        (None, None)
    )
    @ddt.unpack
    def test_start_lun_copy(self, src_vol, dest_lun):
        src_lun = f'src-lun-{fake.LUN_NAME}'
        dest_vol = f'dest-vol-{fake.VOLUME_NAME}'
        dest_vserver = f'dest-vserver-{fake.VSERVER_NAME}'

        src_path = f'/vol/{src_vol if src_vol else dest_vol}/{src_lun}'
        dest_path = f'/vol/{dest_vol}/{dest_lun if dest_lun else src_lun}'
        body = {
            'name': dest_path,
            'copy.source.name': src_path,
            'svm.name': dest_vserver
        }

        self.mock_object(self.client, 'send_request')

        result = self.client.start_lun_copy(
            src_lun, dest_vol, dest_vserver,
            src_ontap_volume=src_vol, src_vserver=fake_client.VSERVER_NAME,
            dest_lun_name=dest_lun)

        self.client.send_request.assert_called_once_with(
            '/storage/luns', 'post', body=body, enable_tunneling=False)
        self.assertEqual(dest_path, result)

    @ddt.data(fake_client.LUN_GET_COPY_REST, None)
    def test_get_lun_copy_status(self, lun_copied):
        dest_path = f'/vol/{fake.VOLUME_NAME}/{fake.LUN_NAME}'
        copy_status = None
        if lun_copied:
            copy_progress = lun_copied['copy']['source']['progress']
            copy_status = {
                'job-status': copy_progress['state'],
                'last-failure-reason': copy_progress['failure']['message']
            }

        self.mock_object(self.client, '_get_first_lun_by_path',
                         return_value=lun_copied)

        result = self.client.get_lun_copy_status(dest_path)

        self.client._get_first_lun_by_path.assert_called_once_with(
            dest_path, fields='copy.source.progress')
        self.assertEqual(copy_status, result)

    def test_cancel_lun_copy(self):
        dest_path = f'/vol/{fake_client.VOLUME_NAME}/{fake_client.FILE_NAME}'

        query = {
            'name': dest_path,
            'svm.name': fake_client.VSERVER_NAME
        }

        self.mock_object(self.client, 'send_request')

        self.client.cancel_lun_copy(dest_path)

        self.client.send_request.assert_called_once_with('/storage/luns/',
                                                         'delete', query=query)

    def test_cancel_lun_copy_exception(self):
        dest_path = f'/vol/{fake_client.VOLUME_NAME}/{fake_client.FILE_NAME}'
        query = {
            'name': dest_path,
            'svm.name': fake_client.VSERVER_NAME
        }

        self.mock_object(self.client, 'send_request',
                         side_effect=self._mock_api_error())

        self.assertRaises(
            netapp_utils.NetAppDriverException,
            self.client.cancel_lun_copy,
            dest_path)
        self.client.send_request.assert_called_once_with('/storage/luns/',
                                                         'delete', query=query)

    # TODO(rfluisa): Add ddt data with None values for optional parameters to
    # improve coverage.
    def test_start_file_copy(self):
        volume = fake_client.VOLUME_ITEM_SIMPLE_RESPONSE_REST
        file_name = fake_client.FILE_NAME
        dest_ontap_volume = fake_client.VOLUME_NAME
        src_ontap_volume = dest_ontap_volume
        dest_file_name = file_name
        response = {'job': {'uuid': 'fake-uuid'}}

        body = {
            'files_to_copy': [
                {
                    'source': {
                        'path': f'{src_ontap_volume}/{file_name}',
                        'volume': {
                            'uuid': volume['uuid']
                        }
                    },
                    'destination': {
                        'path': f'{dest_ontap_volume}/{dest_file_name}',
                        'volume': {
                            'uuid': volume['uuid']
                        }
                    }
                }
            ]
        }

        self.mock_object(self.client, '_get_volume_by_args',
                         return_value=volume)
        self.mock_object(self.client, 'send_request',
                         return_value=response)

        result = self.client.start_file_copy(
            file_name, dest_ontap_volume, src_ontap_volume=src_ontap_volume,
            dest_file_name=dest_file_name)

        self.client.send_request.assert_called_once_with(
            '/storage/file/copy', 'post', body=body, enable_tunneling=False)
        self.assertEqual(response['job']['uuid'], result)

    # TODO(rfluisa): Add ddt data with None values for possible api responses
    # to improve coverage.
    def test_get_file_copy_status(self):
        job_uuid = fake_client.FAKE_UUID
        query = {}
        query['fields'] = '*'
        response = {
            'state': 'fake-state',
            'error': {
                'message': 'fake-error-message'
            }
        }
        expected_result = {
            'job-status': response['state'],
            'last-failure-reason': response['error']['message']
        }

        self.mock_object(self.client, 'send_request', return_value=response)
        result = self.client.get_file_copy_status(job_uuid)

        self.client.send_request.assert_called_once_with(
            f'/cluster/jobs/{job_uuid}', 'get', query=query,
            enable_tunneling=False)
        self.assertEqual(expected_result, result)

    @ddt.data(('success', 'complete'), ('failure', 'destroyed'))
    @ddt.unpack
    def test_get_file_copy_status_translate_state(self, from_state, to_state):
        job_uuid = fake_client.FAKE_UUID
        query = {}
        query['fields'] = '*'
        response = {
            'state': from_state,
            'error': {
                'message': 'fake-error-message'
            }
        }
        expected_result = {
            'job-status': to_state,
            'last-failure-reason': response['error']['message']
        }

        self.mock_object(self.client, 'send_request', return_value=response)
        result = self.client.get_file_copy_status(job_uuid)

        self.client.send_request.assert_called_once_with(
            f'/cluster/jobs/{job_uuid}', 'get', query=query,
            enable_tunneling=False)
        self.assertEqual(expected_result, result)

    def test_rename_file(self):
        volume = fake_client.VOLUME_ITEM_SIMPLE_RESPONSE_REST
        orig_file_name = f'/vol/{fake_client.VOLUME_NAMES[0]}/cinder-vol'
        new_file_name = f'/vol/{fake_client.VOLUME_NAMES[0]}/new-cinder-vol'
        body = {'path': new_file_name.split('/')[3]}

        self.mock_object(self.client, 'send_request')
        self.mock_object(self.client, '_get_volume_by_args',
                         return_value=volume)

        self.client.rename_file(orig_file_name, new_file_name)

        orig_file_name = orig_file_name.split('/')[3]
        self.client.send_request.assert_called_once_with(
            f'/storage/volumes/{volume["uuid"]}/files/{orig_file_name}',
            'patch', body=body)
        self.client._get_volume_by_args.assert_called_once_with(
            vol_name=fake_client.VOLUME_NAMES[0])

    def test_get_namespace_list(self):
        response = fake_client.GET_NAMESPACE_RESPONSE_REST

        fake_query = {
            'svm.name': 'fake_vserver',
            'fields': 'svm.name,location.volume.name,space.size,'
                      'location.qtree.name,name,os_type,'
                      'space.guarantee.requested,uuid'
        }

        expected_result = [
            {
                'Vserver': 'fake_vserver1',
                'Volume': 'fake_vol_001',
                'Size': 999999,
                'Qtree': '',
                'Path': '/vol/fake_vol_001/test',
                'OsType': 'linux',
                'SpaceReserved': True,
                'UUID': 'fake_uuid1'
            },
            {
                'Vserver': 'fake_vserver2',
                'Volume': 'fake_vol_002',
                'Size': 8888888,
                'Qtree': '',
                'Path': '/vol/fake_vol_002/test',
                'OsType': 'linux',
                'SpaceReserved': True,
                'UUID': 'fake_uuid2'
            },
        ]

        self.mock_object(self.client, 'send_request', return_value=response)

        result = self.client.get_namespace_list()

        self.client.send_request.assert_called_once_with(
            '/storage/namespaces/', 'get', query=fake_query)
        self.assertEqual(expected_result, result)

    def test_get_namespace_list_no_response(self):
        response = fake_client.NO_RECORDS_RESPONSE_REST
        fake_query = {
            'svm.name': 'fake_vserver',
            'fields': 'svm.name,location.volume.name,space.size,'
                      'location.qtree.name,name,os_type,'
                      'space.guarantee.requested,uuid'
        }

        self.mock_object(self.client, 'send_request', return_value=response)

        result = self.client.get_namespace_list()

        self.client.send_request.assert_called_once_with(
            '/storage/namespaces/', 'get', query=fake_query)
        self.assertEqual([], result)

    def test_destroy_namespace(self):

        fake_query = {
            'name': '/vol/fake_vol_001/test',
            'svm': 'fake_vserver'
        }

        self.mock_object(self.client, 'send_request')

        self.client.destroy_namespace('/vol/fake_vol_001/test', force=False)

        self.client.send_request.assert_called_once_with(
            '/storage/namespaces', 'delete', query=fake_query)

    def test_destroy_namespace_force_true(self):

        fake_query = {
            'name': '/vol/fake_vol_001/test',
            'svm': 'fake_vserver',
            'allow_delete_while_mapped': 'true'
        }

        self.mock_object(self.client, 'send_request')

        self.client.destroy_namespace('/vol/fake_vol_001/test', force=True)

        self.client.send_request.assert_called_once_with(
            '/storage/namespaces', 'delete', query=fake_query)

    def test_clone_namespace(self):

        fake_body = {
            'svm': {
                'name': 'fake_vserver'
            },
            'name': '/vol/fake_volume/fake_new_name',
            'clone': {
                'source': {
                    'name': '/vol/fake_volume/fake_name',
                }
            }
        }

        self.mock_object(self.client, 'send_request')

        self.client.clone_namespace('fake_volume',
                                    'fake_name',
                                    'fake_new_name')

        self.client.send_request.assert_called_once_with(
            '/storage/namespaces', 'post', body=fake_body)

    def test_get_namespace_by_args(self):
        response = fake_client.GET_NAMESPACE_RESPONSE_REST

        lun_info_args = {
            'vserver': fake.VSERVER_NAME,
            'path': fake.LUN_PATH,
            'uuid': fake.UUID1}

        fake_query = {
            'fields': 'svm.name,location.volume.name,space.size,'
                      'location.qtree.name,name,os_type,'
                      'space.guarantee.requested,uuid,space.block_size',
            'svm.name': fake.VSERVER_NAME,
            'name': fake.LUN_PATH,
            'uuid': fake.UUID1,
        }

        expected_result = [
            {
                'Vserver': 'fake_vserver1',
                'Volume': 'fake_vol_001',
                'Size': 999999,
                'Qtree': '',
                'Path': '/vol/fake_vol_001/test',
                'OsType': 'linux',
                'SpaceReserved': True,
                'UUID': 'fake_uuid1',
                'BlockSize': 9999
            },
            {
                'Vserver': 'fake_vserver2',
                'Volume': 'fake_vol_002',
                'Size': 8888888,
                'Qtree': '',
                'Path': '/vol/fake_vol_002/test',
                'OsType': 'linux',
                'SpaceReserved': True,
                'UUID': 'fake_uuid2',
                'BlockSize': 8888
            },
        ]

        self.mock_object(self.client, 'send_request', return_value=response)

        result = self.client.get_namespace_by_args(**lun_info_args)

        self.client.send_request.assert_called_once_with(
            '/storage/namespaces', 'get', query=fake_query)
        self.assertEqual(expected_result, result)

    def test_get_namespace_by_args_no_response(self):
        response = fake_client.NO_RECORDS_RESPONSE_REST

        lun_info_args = {
            'vserver': fake.VSERVER_NAME,
            'path': fake.LUN_PATH,
            'uuid': fake.UUID1}

        fake_query = {
            'fields': 'svm.name,location.volume.name,space.size,'
                      'location.qtree.name,name,os_type,'
                      'space.guarantee.requested,uuid,space.block_size',
            'svm.name': fake.VSERVER_NAME,
            'name': fake.LUN_PATH,
            'uuid': fake.UUID1,
        }

        self.mock_object(self.client, 'send_request', return_value=response)

        result = self.client.get_namespace_by_args(**lun_info_args)

        self.client.send_request.assert_called_once_with(
            '/storage/namespaces', 'get', query=fake_query)
        self.assertEqual([], result)

    def test_namespace_resize(self):
        fake_body = {'space.size': 9999}
        fake_query = {'name': fake.LUN_PATH}

        self.mock_object(self.client, 'send_request')

        self.client.namespace_resize(fake.LUN_PATH, 9999)

        self.client.send_request.assert_called_once_with(
            '/storage/namespaces', 'patch', body=fake_body, query=fake_query)

    def test_get_namespace_sizes_by_volume(self):
        response = fake_client.GET_NAMESPACE_RESPONSE_REST

        fake_query = {
            'location.volume.name': 'fake_volume',
            'fields': 'space.size,name'
        }

        expected_result = [
            {
                'path': '/vol/fake_vol_001/test',
                'size': 999999,
            },
            {
                'path': '/vol/fake_vol_002/test',
                'size': 8888888,
            },
        ]

        self.mock_object(self.client, 'send_request', return_value=response)

        result = self.client.get_namespace_sizes_by_volume('fake_volume')

        self.client.send_request.assert_called_once_with(
            '/storage/namespaces', 'get', query=fake_query)
        self.assertEqual(expected_result, result)

    def test_get_namespace_sizes_by_volume_no_response(self):
        response = fake_client.NO_RECORDS_RESPONSE_REST

        fake_query = {
            'location.volume.name': 'fake_volume',
            'fields': 'space.size,name'
        }

        self.mock_object(self.client, 'send_request', return_value=response)

        result = self.client.get_namespace_sizes_by_volume('fake_volume')

        self.client.send_request.assert_called_once_with(
            '/storage/namespaces', 'get', query=fake_query)
        self.assertEqual([], result)

    def test_create_namespace(self):
        """Issues API request for creating namespace on volume."""
        self.mock_object(self.client, 'send_request')

        self.client.create_namespace(
            fake_client.VOLUME_NAME, fake_client.NAMESPACE_NAME,
            fake_client.VOLUME_SIZE_TOTAL, {'OsType': 'linux'})

        path = f'/vol/{fake_client.VOLUME_NAME}/{fake_client.NAMESPACE_NAME}'
        body = {
            'name': path,
            'space.size': str(fake_client.VOLUME_SIZE_TOTAL),
            'os_type': 'linux',
        }
        self.client.send_request.assert_called_once_with(
            '/storage/namespaces', 'post', body=body)

    def test_create_namespace_error(self):
        api_error = netapp_api.NaApiError(code=0)
        self.mock_object(self.client, 'send_request', side_effect=api_error)

        self.assertRaises(
            netapp_api.NaApiError,
            self.client.create_namespace,
            fake_client.VOLUME_NAME, fake_client.NAMESPACE_NAME,
            fake_client.VOLUME_SIZE_TOTAL, {'OsType': 'linux'})

    def test_get_subsystem_by_host(self):
        response = fake_client.GET_SUBSYSTEM_RESPONSE_REST
        self.mock_object(self.client, 'send_request',
                         return_value=response)

        res = self.client.get_subsystem_by_host(fake_client.HOST_NQN)

        expected_res = [
            {'name': fake_client.SUBSYSTEM, 'os_type': 'linux'}]
        self.assertEqual(expected_res, res)
        query = {
            'svm.name': self.client.vserver,
            'hosts.nqn': fake_client.HOST_NQN,
            'fields': 'name,os_type',
            'name': 'openstack-*',
        }
        self.client.send_request.assert_called_once_with(
            '/protocols/nvme/subsystems', 'get', query=query)

    def test_create_subsystem(self):
        self.mock_object(self.client, 'send_request')

        self.client.create_subsystem(fake_client.SUBSYSTEM, 'linux',
                                     fake_client.HOST_NQN)

        body = {
            'svm.name': self.client.vserver,
            'name': fake_client.SUBSYSTEM,
            'os_type': 'linux',
            'hosts': [{'nqn': fake_client.HOST_NQN}]
        }
        self.client.send_request.assert_called_once_with(
            '/protocols/nvme/subsystems', 'post', body=body)

    def test_get_namespace_map(self):
        response = fake_client.GET_SUBSYSTEM_MAP_RESPONSE_REST
        self.mock_object(self.client, 'send_request',
                         return_value=response)

        res = self.client.get_namespace_map(fake_client.NAMESPACE_NAME)

        expected_res = [
            {'subsystem': fake_client.SUBSYSTEM,
             'uuid': fake_client.FAKE_UUID,
             'vserver': fake_client.VSERVER_NAME}]
        self.assertEqual(expected_res, res)
        query = {
            'namespace.name': fake_client.NAMESPACE_NAME,
            'fields': 'subsystem.name,namespace.uuid,svm.name',
        }
        self.client.send_request.assert_called_once_with(
            '/protocols/nvme/subsystem-maps', 'get', query=query)

    def test_map_namespace(self):
        response = fake_client.GET_SUBSYSTEM_MAP_RESPONSE_REST
        self.mock_object(self.client, 'send_request',
                         return_value=response)

        res = self.client.map_namespace(fake_client.NAMESPACE_NAME,
                                        fake_client.SUBSYSTEM)

        self.assertEqual(fake_client.FAKE_UUID, res)
        body = {
            'namespace.name': fake_client.NAMESPACE_NAME,
            'subsystem.name': fake_client.SUBSYSTEM
        }
        self.client.send_request.assert_called_once_with(
            '/protocols/nvme/subsystem-maps', 'post', body=body,
            query={'return_records': 'true'})

    def test_map_namespace_error(self):
        api_error = netapp_api.NaApiError(code=0)
        self.mock_object(self.client, 'send_request', side_effect=api_error)

        self.assertRaises(
            netapp_api.NaApiError,
            self.client.map_namespace,
            fake_client.VOLUME_NAME, fake_client.SUBSYSTEM)

    @ddt.data(
        {'response': fake_client.GET_SUBSYSTEM_RESPONSE_REST,
         'expected': fake_client.TARGET_NQN},
        {'response': fake_client.NO_RECORDS_RESPONSE_REST,
         'expected': None})
    @ddt.unpack
    def test_get_nvme_subsystem_nqn(self, response, expected):
        self.mock_object(self.client, 'send_request',
                         return_value=response)

        res = self.client.get_nvme_subsystem_nqn(fake_client.SUBSYSTEM)

        self.assertEqual(expected, res)
        query = {
            'fields': 'target_nqn',
            'name': fake_client.SUBSYSTEM,
            'svm.name': self.client.vserver
        }
        self.client.send_request.assert_called_once_with(
            '/protocols/nvme/subsystems', 'get', query=query)

    def test_get_nvme_target_portals(self):
        response = fake_client.GET_INTERFACES_NVME_REST
        self.mock_object(self.client, 'send_request',
                         return_value=response)

        res = self.client.get_nvme_target_portals()

        expected = ["10.10.10.10"]
        self.assertEqual(expected, res)
        query = {
            'services': 'data_nvme_tcp',
            'fields': 'ip.address',
            'enabled': 'true',
        }
        self.client.send_request.assert_called_once_with(
            '/network/ip/interfaces', 'get', query=query)

    def test_unmap_namespace(self):
        self.mock_object(self.client, 'send_request')

        self.client.unmap_namespace(fake_client.NAMESPACE_NAME,
                                    fake_client.SUBSYSTEM)

        query = {
            'subsystem.name': fake_client.SUBSYSTEM,
            'namespace.name': fake_client.NAMESPACE_NAME,
        }
        self.client.send_request.assert_called_once_with(
            '/protocols/nvme/subsystem-maps', 'delete', query=query)
