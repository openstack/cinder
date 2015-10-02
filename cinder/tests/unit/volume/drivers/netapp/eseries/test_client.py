# Copyright (c) 2014 Alex Meade
# Copyright (c) 2015 Yogesh Kshirsagar
# Copyright (c) 2015 Michael Price
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

import ddt
import mock

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.netapp.eseries import fakes as \
    eseries_fake
from cinder.volume.drivers.netapp.eseries import exception as es_exception


from cinder.volume.drivers.netapp.eseries import client
from cinder.volume.drivers.netapp import utils as na_utils


@ddt.ddt
class NetAppEseriesClientDriverTestCase(test.TestCase):
    """Test case for NetApp e-series client."""

    def setUp(self):
        super(NetAppEseriesClientDriverTestCase, self).setUp()
        self.mock_log = mock.Mock()
        self.mock_object(client, 'LOG', self.mock_log)
        self.fake_password = 'mysecret'

        self.my_client = client.RestClient('http', 'host', '80', '/test',
                                           'user', self.fake_password,
                                           system_id='fake_sys_id')
        self.my_client._endpoint = eseries_fake.FAKE_ENDPOINT_HTTP

        fake_response = mock.Mock()
        fake_response.status_code = 200
        self.my_client.invoke_service = mock.Mock(return_value=fake_response)
        self.my_client.api_version = '01.52.9000.1'

    @ddt.data(200, 201, 203, 204)
    def test_eval_response_success(self, status_code):
        fake_resp = mock.Mock()
        fake_resp.status_code = status_code

        self.assertIsNone(self.my_client._eval_response(fake_resp))

    @ddt.data(300, 400, 404, 500)
    def test_eval_response_failure(self, status_code):
        fake_resp = mock.Mock()
        fake_resp.status_code = status_code
        expected_msg = "Response error code - %s." % status_code

        with self.assertRaisesRegex(es_exception.WebServiceException,
                                    expected_msg) as exc:
            self.my_client._eval_response(fake_resp)

            self.assertEqual(status_code, exc.status_code)

    def test_eval_response_422(self):
        status_code = 422
        resp_text = "Fake Error Message"
        fake_resp = mock.Mock()
        fake_resp.status_code = status_code
        fake_resp.text = resp_text
        expected_msg = "Response error - %s." % resp_text

        with self.assertRaisesRegex(es_exception.WebServiceException,
                                    expected_msg) as exc:
            self.my_client._eval_response(fake_resp)

            self.assertEqual(status_code, exc.status_code)

    def test_register_storage_system_does_not_log_password(self):
        self.my_client._eval_response = mock.Mock()
        self.my_client.register_storage_system([], password=self.fake_password)
        for call in self.mock_log.debug.mock_calls:
            __, args, __ = call
            self.assertNotIn(self.fake_password, args[0])

    def test_update_stored_system_password_does_not_log_password(self):
        self.my_client._eval_response = mock.Mock()
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

    def test_add_autosupport_data(self):
        self.mock_object(
            client.RestClient, 'get_eseries_api_info',
            mock.Mock(return_value=(
                eseries_fake.FAKE_ASUP_DATA['operating-mode'],
                eseries_fake.FAKE_ABOUT_RESPONSE['version'])))
        self.mock_object(
            self.my_client, 'get_firmware_version',
            mock.Mock(
                return_value=eseries_fake.FAKE_ABOUT_RESPONSE['version']))
        self.mock_object(
            self.my_client, 'get_serial_numbers',
            mock.Mock(return_value=eseries_fake.FAKE_SERIAL_NUMBERS))
        self.mock_object(
            self.my_client, 'get_model_name',
            mock.Mock(
                return_value=eseries_fake.FAKE_CONTROLLERS[0]['modelName']))
        self.mock_object(
            self.my_client, 'set_counter',
            mock.Mock(return_value={'value': 1}))
        mock_invoke = self.mock_object(
            self.my_client, '_invoke',
            mock.Mock(return_value=eseries_fake.FAKE_ASUP_DATA))

        client.RestClient.add_autosupport_data(
            self.my_client,
            eseries_fake.FAKE_KEY,
            eseries_fake.FAKE_ASUP_DATA
        )

        mock_invoke.assert_called_with(*eseries_fake.FAKE_POST_INVOKE_DATA)

    @ddt.data((eseries_fake.FAKE_SERIAL_NUMBERS,
               eseries_fake.FAKE_CONTROLLERS),
              (eseries_fake.FAKE_DEFAULT_SERIAL_NUMBER, []),
              (eseries_fake.FAKE_SERIAL_NUMBER,
              eseries_fake.FAKE_SINGLE_CONTROLLER))
    @ddt.unpack
    def test_get_serial_numbers(self, expected_serial_numbers, controllers):
        self.mock_object(
            client.RestClient, '_get_controllers',
            mock.Mock(return_value=controllers))

        serial_numbers = client.RestClient.get_serial_numbers(self.my_client)

        self.assertEqual(expected_serial_numbers, serial_numbers)

    def test_get_model_name(self):
        self.mock_object(
            client.RestClient, '_get_controllers',
            mock.Mock(return_value=eseries_fake.FAKE_CONTROLLERS))

        model = client.RestClient.get_model_name(self.my_client)

        self.assertEqual(eseries_fake.FAKE_CONTROLLERS[0]['modelName'],
                         model)

    def test_get_model_name_empty_controllers_list(self):
        self.mock_object(
            client.RestClient, '_get_controllers',
            mock.Mock(return_value=[]))

        model = client.RestClient.get_model_name(self.my_client)

        self.assertEqual(eseries_fake.FAKE_DEFAULT_MODEL, model)

    def test_get_eseries_api_info(self):
        fake_invoke_service = mock.Mock()
        fake_invoke_service.json = mock.Mock(
            return_value=eseries_fake.FAKE_ABOUT_RESPONSE)
        self.mock_object(
            client.RestClient, '_get_resource_url',
            mock.Mock(return_value=eseries_fake.FAKE_RESOURCE_URL))
        self.mock_object(
            self.my_client, 'invoke_service',
            mock.Mock(return_value=fake_invoke_service))

        eseries_info = client.RestClient.get_eseries_api_info(
            self.my_client, verify=False)

        self.assertEqual((eseries_fake.FAKE_ASUP_DATA['operating-mode'],
                          eseries_fake.FAKE_ABOUT_RESPONSE['version']),
                         eseries_info)

    def test_list_ssc_storage_pools(self):
        self.my_client.features = mock.Mock()
        self.my_client._invoke = mock.Mock(
            return_value=eseries_fake.SSC_POOLS)

        pools = client.RestClient.list_ssc_storage_pools(self.my_client)

        self.assertEqual(eseries_fake.SSC_POOLS, pools)

    def test_get_ssc_storage_pool(self):
        fake_pool = eseries_fake.SSC_POOLS[0]
        self.my_client.features = mock.Mock()
        self.my_client._invoke = mock.Mock(
            return_value=fake_pool)

        pool = client.RestClient.get_ssc_storage_pool(self.my_client,
                                                      fake_pool['poolId'])

        self.assertEqual(fake_pool, pool)

    @ddt.data(('volumes', True), ('volumes', False),
              ('volume', True), ('volume', False))
    @ddt.unpack
    def test_get_volume_api_path(self, path_key, ssc_available):
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=ssc_available)
        expected_key = 'ssc_' + path_key if ssc_available else path_key
        expected = self.my_client.RESOURCE_PATHS.get(expected_key)

        actual = self.my_client._get_volume_api_path(path_key)

        self.assertEqual(expected, actual)

    @ddt.data(True, False)
    def test_get_volume_api_path_invalid(self, ssc_available):
        key = 'invalidKey'
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=ssc_available)

        self.assertRaises(KeyError, self.my_client._get_volume_api_path, key)

    def test_list_volumes(self):
        url = client.RestClient.RESOURCE_PATHS['ssc_volumes']
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=True)
        self.my_client._invoke = mock.Mock(
            return_value=eseries_fake.VOLUMES)

        volumes = client.RestClient.list_volumes(self.my_client)

        self.assertEqual(eseries_fake.VOLUMES, volumes)
        self.my_client._invoke.assert_called_once_with('GET', url)

    @ddt.data(client.RestClient.ID, client.RestClient.WWN,
              client.RestClient.NAME)
    def test_list_volume_v1(self, uid_field_name):
        url = client.RestClient.RESOURCE_PATHS['volumes']
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=False)
        fake_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.my_client._invoke = mock.Mock(
            return_value=eseries_fake.VOLUMES)

        volume = client.RestClient.list_volume(self.my_client,
                                               fake_volume[uid_field_name])

        self.my_client._invoke.assert_called_once_with('GET', url)
        self.assertEqual(fake_volume, volume)

    def test_list_volume_v1_not_found(self):
        url = client.RestClient.RESOURCE_PATHS['volumes']
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=False)
        self.my_client._invoke = mock.Mock(
            return_value=eseries_fake.VOLUMES)

        self.assertRaises(exception.VolumeNotFound,
                          client.RestClient.list_volume,
                          self.my_client, 'fakeId')
        self.my_client._invoke.assert_called_once_with('GET', url)

    def test_list_volume_v2(self):
        url = client.RestClient.RESOURCE_PATHS['ssc_volume']
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=True)
        fake_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.my_client._invoke = mock.Mock(return_value=fake_volume)

        volume = client.RestClient.list_volume(self.my_client,
                                               fake_volume['id'])

        self.my_client._invoke.assert_called_once_with('GET', url,
                                                       **{'object-id':
                                                          mock.ANY})
        self.assertEqual(fake_volume, volume)

    def test_list_volume_v2_not_found(self):
        status_code = 404
        url = client.RestClient.RESOURCE_PATHS['ssc_volume']
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=True)
        msg = "Response error code - %s." % status_code
        self.my_client._invoke = mock.Mock(
            side_effect=es_exception.WebServiceException(message=msg,
                                                         status_code=
                                                         status_code))

        self.assertRaises(exception.VolumeNotFound,
                          client.RestClient.list_volume,
                          self.my_client, 'fakeId')
        self.my_client._invoke.assert_called_once_with('GET', url,
                                                       **{'object-id':
                                                          mock.ANY})

    def test_list_volume_v2_failure(self):
        status_code = 422
        url = client.RestClient.RESOURCE_PATHS['ssc_volume']
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=True)
        msg = "Response error code - %s." % status_code
        self.my_client._invoke = mock.Mock(
            side_effect=es_exception.WebServiceException(message=msg,
                                                         status_code=
                                                         status_code))

        self.assertRaises(es_exception.WebServiceException,
                          client.RestClient.list_volume, self.my_client,
                          'fakeId')
        self.my_client._invoke.assert_called_once_with('GET', url,
                                                       **{'object-id':
                                                          mock.ANY})

    def test_create_volume_V1(self):
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=False)
        create_volume = self.my_client._invoke = mock.Mock(
            return_value=eseries_fake.VOLUME)

        volume = client.RestClient.create_volume(self.my_client,
                                                 'fakePool', '1', 1)

        args, kwargs = create_volume.call_args
        verb, url, body = args
        # Ensure the correct API was used
        self.assertEqual('/storage-systems/{system-id}/volumes', url)
        self.assertEqual(eseries_fake.VOLUME, volume)

    def test_create_volume_V2(self):
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=True)
        create_volume = self.my_client._invoke = mock.Mock(
            return_value=eseries_fake.VOLUME)

        volume = client.RestClient.create_volume(self.my_client,
                                                 'fakePool', '1', 1)

        args, kwargs = create_volume.call_args
        verb, url, body = args
        # Ensure the correct API was used
        self.assertIn('/storage-systems/{system-id}/ssc/volumes', url,
                      'The legacy API was used!')
        self.assertEqual(eseries_fake.VOLUME, volume)

    def test_create_volume_unsupported_specs(self):
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=False)
        self.my_client.api_version = '01.52.9000.1'

        self.assertRaises(exception.NetAppDriverException,
                          client.RestClient.create_volume, self.my_client,
                          '1', 'label', 1, read_cache=True)

    @ddt.data(True, False)
    def test_update_volume(self, ssc_api_enabled):
        label = 'updatedName'
        fake_volume = copy.deepcopy(eseries_fake.VOLUME)
        expected_volume = copy.deepcopy(fake_volume)
        expected_volume['name'] = label
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=ssc_api_enabled)
        self.my_client._invoke = mock.Mock(return_value=expected_volume)

        updated_volume = self.my_client.update_volume(fake_volume['id'],
                                                      label)

        if ssc_api_enabled:
            url = self.my_client.RESOURCE_PATHS.get('ssc_volume')
        else:
            url = self.my_client.RESOURCE_PATHS.get('volume')

        self.my_client._invoke.assert_called_once_with('POST', url,
                                                       {'name': label},
                                                       **{'object-id':
                                                          fake_volume['id']}
                                                       )
        self.assertDictMatch(expected_volume, updated_volume)

    def test_extend_volume(self):
        new_capacity = 10
        fake_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=True)
        self.my_client._invoke = mock.Mock(return_value=fake_volume)

        expanded_volume = self.my_client.expand_volume(fake_volume['id'],
                                                       new_capacity)

        url = self.my_client.RESOURCE_PATHS.get('ssc_volume')
        body = {'newSize': new_capacity, 'sizeUnit': 'gb'}
        self.my_client._invoke.assert_called_once_with('POST', url, body,
                                                       **{'object-id':
                                                          fake_volume['id']})
        self.assertEqual(fake_volume, expanded_volume)

    def test_extend_volume_unsupported(self):
        new_capacity = 10
        min_version = 1
        fake_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=False, minimum_version=min_version)
        self.my_client._invoke = mock.Mock(return_value=fake_volume)

        self.assertRaises(exception.NetAppDriverException,
                          self.my_client.expand_volume, fake_volume['id'],
                          new_capacity)

    @ddt.data(True, False)
    def test_delete_volume(self, ssc_api_enabled):
        fake_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=ssc_api_enabled)
        self.my_client._invoke = mock.Mock()

        self.my_client.delete_volume(fake_volume['id'])

        if ssc_api_enabled:
            url = self.my_client.RESOURCE_PATHS.get('ssc_volume')
        else:
            url = self.my_client.RESOURCE_PATHS.get('volume')

        self.my_client._invoke.assert_called_once_with('DELETE', url,
                                                       **{'object-id':
                                                          fake_volume['id']}
                                                       )

    @ddt.data('00.00.00.00', '01.52.9000.2', '01.52.9001.2', '01.51.9000.3',
              '01.51.9001.3', '01.51.9010.5', '0.53.9000.3', '0.53.9001.4')
    def test_api_version_not_support_asup(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         mock.Mock(return_value=('proxy', api_version)))

        client.RestClient._init_features(self.my_client)

        self.assertFalse(self.my_client.features.AUTOSUPPORT.supported)

    @ddt.data('01.52.9000.3', '01.52.9000.4', '01.52.8999.2',
              '01.52.8999.3', '01.53.8999.3', '01.53.9000.2',
              '02.51.9000.3', '02.52.8999.3', '02.51.8999.2')
    def test_api_version_supports_asup(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         mock.Mock(return_value=('proxy', api_version)))

        client.RestClient._init_features(self.my_client)

        self.assertTrue(self.my_client.features.AUTOSUPPORT.supported)

    @ddt.data('00.00.00.00', '01.52.9000.1', '01.52.9001.2', '00.53.9001.3',
              '01.53.9090.1', '1.53.9010.14', '0.53.9011.15')
    def test_api_version_not_support_ssc_api(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         mock.Mock(return_value=('proxy', api_version)))

        client.RestClient._init_features(self.my_client)

        self.assertFalse(self.my_client.features.SSC_API_V2.supported)

    @ddt.data('01.53.9000.1', '01.53.9000.5', '01.53.8999.1',
              '01.53.9010.20', '01.53.9010.17', '01.54.9000.1',
              '02.51.9000.3', '02.52.8999.3', '02.51.8999.2')
    def test_api_version_supports_ssc_api(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         mock.Mock(return_value=('proxy', api_version)))

        client.RestClient._init_features(self.my_client)

        self.assertTrue(self.my_client.features.SSC_API_V2.supported)


@ddt.ddt
class TestWebserviceClientTestCase(test.TestCase):

    def setUp(self):
        """sets up the mock tests"""
        super(TestWebserviceClientTestCase, self).setUp()
        self.mock_log = mock.Mock()
        self.mock_object(client, 'LOG', self.mock_log)
        self.webclient = client.WebserviceClient('http', 'host', '80',
                                                 '/test', 'user', '****')

    @ddt.data({'params': {'host': None, 'scheme': 'https', 'port': '80'}},
              {'params': {'host': 'host', 'scheme': None, 'port': '80'}},
              {'params': {'host': 'host', 'scheme': 'http', 'port': None}})
    @ddt.unpack
    def test__validate_params_value_error(self, params):
        """Tests various scenarios for ValueError in validate method"""
        self.assertRaises(exception.InvalidInput,
                          self.webclient._validate_params, **params)

    def test_invoke_service_no_endpoint_error(self):
        """Tests Exception and Log error if no endpoint is provided"""
        self.webclient._endpoint = None
        log_error = 'Unexpected error while invoking web service'

        self.assertRaises(exception.NetAppDriverException,
                          self.webclient.invoke_service)
        self.assertTrue(self.mock_log.exception.find(log_error))

    def test_invoke_service(self):
        """Tests if invoke_service evaluates the right response"""
        self.webclient._endpoint = eseries_fake.FAKE_ENDPOINT_HTTP
        self.mock_object(self.webclient.conn, 'request',
                         mock.Mock(return_value=eseries_fake.FAKE_INVOC_MSG))
        result = self.webclient.invoke_service()

        self.assertIsNotNone(result)
