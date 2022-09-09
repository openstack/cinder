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
import six

from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.netapp.dataontap.client import (
    fakes as fake_client)
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as fake
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap.client import client_cmode_rest


CONNECTION_INFO = {'hostname': 'hostname',
                   'transport_type': 'https',
                   'port': 443,
                   'username': 'admin',
                   'password': 'passw0rd',
                   'vserver': 'fake_vserver',
                   'ssl_cert_path': 'fake_ca',
                   'api_trace_pattern': 'fake_regex'}


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
        self.fake_volume = six.text_type(uuid.uuid4())
        self.fake_lun = six.text_type(uuid.uuid4())
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
