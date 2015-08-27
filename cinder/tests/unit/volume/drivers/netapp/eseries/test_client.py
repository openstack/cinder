# Copyright (c) 2014 Alex Meade
# Copyright (c) 2015 Yogesh Kshirsagar
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

import copy

import mock

from cinder import test
from cinder.tests.unit.volume.drivers.netapp.eseries import fakes as \
    eseries_fake
from cinder.volume.drivers.netapp.eseries import client


class NetAppEseriesClientDriverTestCase(test.TestCase):
    """Test case for NetApp e-series client."""

    def setUp(self):
        super(NetAppEseriesClientDriverTestCase, self).setUp()
        self.mock_log = mock.Mock()
        self.mock_object(client, 'LOG', self.mock_log)
        self.fake_password = 'mysecret'

        # Inject fake netapp_lib module classes.
        eseries_fake.mock_netapp_lib([client])

        self.my_client = client.RestClient('http', 'host', '80', '/test',
                                           'user', self.fake_password,
                                           system_id='fake_sys_id')
        self.my_client.client._endpoint = eseries_fake.FAKE_ENDPOINT_HTTP
        self.mock_object(self.my_client, '_eval_response')

        fake_response = mock.Mock()
        fake_response.status_code = 200
        self.my_client.invoke_service = mock.Mock(return_value=fake_response)

    def test_register_storage_system_does_not_log_password(self):
        self.my_client.register_storage_system([], password=self.fake_password)
        for call in self.mock_log.debug.mock_calls:
            __, args, __ = call
            self.assertNotIn(self.fake_password, args[0])

    def test_update_stored_system_password_does_not_log_password(self):
        self.my_client.update_stored_system_password(
            password=self.fake_password)
        for call in self.mock_log.debug.mock_calls:
            __, args, __ = call
            self.assertNotIn(self.fake_password, args[0])

    def test_list_target_wwpns(self):
        fake_hardware_inventory = copy.deepcopy(
            eseries_fake.HARDWARE_INVENTORY)

        mock_hardware_inventory = mock.Mock(
            return_value=fake_hardware_inventory)
        self.mock_object(self.my_client, 'list_hardware_inventory',
                         mock_hardware_inventory)
        expected_wwpns = [eseries_fake.WWPN, eseries_fake.WWPN_2]

        actual_wwpns = self.my_client.list_target_wwpns()

        self.assertEqual(expected_wwpns, actual_wwpns)

    def test_list_target_wwpns_single_wwpn(self):
        fake_hardware_inventory = copy.deepcopy(
            eseries_fake.HARDWARE_INVENTORY)

        fake_hardware_inventory['fibrePorts'] = [
            fake_hardware_inventory['fibrePorts'][0]
        ]
        mock_hardware_inventory = mock.Mock(
            return_value=fake_hardware_inventory)
        self.mock_object(self.my_client, 'list_hardware_inventory',
                         mock_hardware_inventory)
        expected_wwpns = [eseries_fake.WWPN]

        actual_wwpns = self.my_client.list_target_wwpns()

        self.assertEqual(expected_wwpns, actual_wwpns)

    def test_list_target_wwpns_no_wwpn(self):
        fake_hardware_inventory = copy.deepcopy(
            eseries_fake.HARDWARE_INVENTORY)

        fake_hardware_inventory['fibrePorts'] = []
        mock_hardware_inventory = mock.Mock(
            return_value=fake_hardware_inventory)
        self.mock_object(self.my_client, 'list_hardware_inventory',
                         mock_hardware_inventory)
        expected_wwpns = []

        actual_wwpns = self.my_client.list_target_wwpns()

        self.assertEqual(expected_wwpns, actual_wwpns)

    def test_create_host_from_ports_fc(self):
        label = 'fake_host'
        host_type = 'linux'
        port_type = 'fc'
        port_ids = [eseries_fake.WWPN, eseries_fake.WWPN_2]
        expected_ports = [
            {'type': port_type, 'port': eseries_fake.WWPN, 'label': mock.ANY},
            {'type': port_type, 'port': eseries_fake.WWPN_2,
             'label': mock.ANY}]
        mock_create_host = self.mock_object(self.my_client, 'create_host')

        self.my_client.create_host_with_ports(label, host_type, port_ids,
                                              port_type)

        mock_create_host.assert_called_once_with(label, host_type,
                                                 expected_ports, None)

    def test_host_from_ports_with_no_ports_provided_fc(self):
        label = 'fake_host'
        host_type = 'linux'
        port_type = 'fc'
        port_ids = []
        expected_ports = []
        mock_create_host = self.mock_object(self.my_client, 'create_host')

        self.my_client.create_host_with_ports(label, host_type, port_ids,
                                              port_type)

        mock_create_host.assert_called_once_with(label, host_type,
                                                 expected_ports, None)

    def test_create_host_from_ports_iscsi(self):
        label = 'fake_host'
        host_type = 'linux'
        port_type = 'iscsi'
        port_ids = [eseries_fake.INITIATOR_NAME,
                    eseries_fake.INITIATOR_NAME_2]
        expected_ports = [
            {'type': port_type, 'port': eseries_fake.INITIATOR_NAME,
             'label': mock.ANY},
            {'type': port_type, 'port': eseries_fake.INITIATOR_NAME_2,
             'label': mock.ANY}]
        mock_create_host = self.mock_object(self.my_client, 'create_host')

        self.my_client.create_host_with_ports(label, host_type, port_ids,
                                              port_type)

        mock_create_host.assert_called_once_with(label, host_type,
                                                 expected_ports, None)

    def test_get_volume_mappings_for_volume(self):
        volume_mapping_1 = copy.deepcopy(eseries_fake.VOLUME_MAPPING)
        volume_mapping_2 = copy.deepcopy(eseries_fake.VOLUME_MAPPING)
        volume_mapping_2['volumeRef'] = '2'
        self.mock_object(self.my_client, 'get_volume_mappings',
                         mock.Mock(return_value=[volume_mapping_1,
                                                 volume_mapping_2]))

        mappings = self.my_client.get_volume_mappings_for_volume(
            eseries_fake.VOLUME)

        self.assertEqual([volume_mapping_1], mappings)

    def test_get_volume_mappings_for_host(self):
        volume_mapping_1 = copy.deepcopy(
            eseries_fake.VOLUME_MAPPING)
        volume_mapping_2 = copy.deepcopy(eseries_fake.VOLUME_MAPPING)
        volume_mapping_2['volumeRef'] = '2'
        volume_mapping_2['mapRef'] = 'hostRef'
        self.mock_object(self.my_client, 'get_volume_mappings',
                         mock.Mock(return_value=[volume_mapping_1,
                                                 volume_mapping_2]))

        mappings = self.my_client.get_volume_mappings_for_host(
            'hostRef')

        self.assertEqual([volume_mapping_2], mappings)

    def test_get_volume_mappings_for_hostgroup(self):
        volume_mapping_1 = copy.deepcopy(
            eseries_fake.VOLUME_MAPPING)
        volume_mapping_2 = copy.deepcopy(eseries_fake.VOLUME_MAPPING)
        volume_mapping_2['volumeRef'] = '2'
        volume_mapping_2['mapRef'] = 'hostGroupRef'
        self.mock_object(self.my_client, 'get_volume_mappings',
                         mock.Mock(return_value=[volume_mapping_1,
                                                 volume_mapping_2]))

        mappings = self.my_client.get_volume_mappings_for_host_group(
            'hostGroupRef')

        self.assertEqual([volume_mapping_2], mappings)

    def test_to_pretty_dict_string(self):
        dict = {
            'foo': 'bar',
            'fu': {
                'nested': 'boo'
            }
        }
        expected_dict_string = ("""{
  "foo": "bar",
  "fu": {
    "nested": "boo"
  }
}""")

        dict_string = self.my_client._to_pretty_dict_string(dict)

        self.assertEqual(expected_dict_string, dict_string)

    def test_log_http_request(self):
        mock_log = self.mock_object(client, 'LOG')
        verb = "POST"
        url = "/v2/test/me"
        headers = {"Content-Type": "application/json"}
        headers_string = """{
  "Content-Type": "application/json"
}"""
        body = {}
        body_string = "{}"

        self.my_client._log_http_request(verb, url, headers, body)

        args = mock_log.debug.call_args
        log_message, log_params = args[0]
        final_msg = log_message % log_params
        self.assertIn(verb, final_msg)
        self.assertIn(url, final_msg)
        self.assertIn(headers_string, final_msg)
        self.assertIn(body_string, final_msg)

    def test_log_http_request_no_body(self):
        mock_log = self.mock_object(client, 'LOG')
        verb = "POST"
        url = "/v2/test/me"
        headers = {"Content-Type": "application/json"}
        headers_string = """{
  "Content-Type": "application/json"
}"""
        body = None
        body_string = ""

        self.my_client._log_http_request(verb, url, headers, body)

        args = mock_log.debug.call_args
        log_message, log_params = args[0]
        final_msg = log_message % log_params
        self.assertIn(verb, final_msg)
        self.assertIn(url, final_msg)
        self.assertIn(headers_string, final_msg)
        self.assertIn(body_string, final_msg)

    def test_log_http_response(self):
        mock_log = self.mock_object(client, 'LOG')
        status = "200"
        headers = {"Content-Type": "application/json"}
        headers_string = """{
  "Content-Type": "application/json"
}"""
        body = {}
        body_string = "{}"

        self.my_client._log_http_response(status, headers, body)

        args = mock_log.debug.call_args
        log_message, log_params = args[0]
        final_msg = log_message % log_params
        self.assertIn(status, final_msg)
        self.assertIn(headers_string, final_msg)
        self.assertIn(body_string, final_msg)

    def test_log_http_response_no_body(self):
        mock_log = self.mock_object(client, 'LOG')
        status = "200"
        headers = {"Content-Type": "application/json"}
        headers_string = """{
  "Content-Type": "application/json"
}"""
        body = None
        body_string = ""

        self.my_client._log_http_response(status, headers, body)

        args = mock_log.debug.call_args
        log_message, log_params = args[0]
        final_msg = log_message % log_params
        self.assertIn(status, final_msg)
        self.assertIn(headers_string, final_msg)
        self.assertIn(body_string, final_msg)
