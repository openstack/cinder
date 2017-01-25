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
import json
import mock
from simplejson import scanner
from six.moves import http_client

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
        fake_response.status_code = http_client.OK
        self.my_client.invoke_service = mock.Mock(return_value=fake_response)
        self.my_client.api_version = '01.52.9000.1'

    @ddt.data(http_client.OK, http_client.CREATED,
              http_client.NON_AUTHORITATIVE_INFORMATION,
              http_client.NO_CONTENT)
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

    @ddt.data(('30', 'storage array password.*?incorrect'),
              ('authFailPassword', 'storage array password.*?incorrect'),
              ('unknown', None))
    @ddt.unpack
    def test_eval_response_422(self, ret_code, exc_regex):
        status_code = http_client.UNPROCESSABLE_ENTITY
        fake_resp = mock.Mock()
        fake_resp.text = "fakeError"
        fake_resp.json = mock.Mock(return_value={'retcode': ret_code})
        fake_resp.status_code = status_code
        exc_regex = exc_regex if exc_regex is not None else fake_resp.text

        with self.assertRaisesRegexp(es_exception.WebServiceException,
                                     exc_regex) as exc:
            self.my_client._eval_response(fake_resp)
            self.assertEqual(status_code, exc.status_code)

    def test_eval_response_424(self):
        status_code = http_client.FAILED_DEPENDENCY
        fake_resp = mock.Mock()
        fake_resp.status_code = status_code
        fake_resp.text = "Fake Error Message"

        with self.assertRaisesRegex(es_exception.WebServiceException,
                                    "The storage-system is offline") as exc:
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

    def test_get_host_group_by_name(self):
        groups = copy.deepcopy(eseries_fake.HOST_GROUPS)
        group = groups[0]
        self.mock_object(self.my_client, 'list_host_groups',
                         return_value=groups)

        result = self.my_client.get_host_group_by_name(group['label'])

        self.assertEqual(group, result)

    def test_move_volume_mapping_via_symbol(self):
        invoke = self.mock_object(self.my_client, '_invoke', return_value='ok')
        host_ref = 'host'
        cluster_ref = 'cluster'
        lun_id = 10
        expected_data = {'lunMappingRef': host_ref, 'lun': lun_id,
                         'mapRef': cluster_ref}

        result = self.my_client.move_volume_mapping_via_symbol(host_ref,
                                                               cluster_ref,
                                                               lun_id)

        invoke.assert_called_once_with('POST', '/storage-systems/{system-id}/'
                                               'symbol/moveLUNMapping',
                                       expected_data)

        self.assertEqual({'lun': lun_id}, result)

    def test_move_volume_mapping_via_symbol_fail(self):
        self.mock_object(self.my_client, '_invoke', return_value='failure')

        self.assertRaises(
            exception.NetAppDriverException,
            self.my_client.move_volume_mapping_via_symbol, '1', '2', 10)

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
                         return_value=[volume_mapping_1, volume_mapping_2])

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
                         return_value=[volume_mapping_1, volume_mapping_2])

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
                         return_value=[volume_mapping_1, volume_mapping_2])

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
            return_value=(eseries_fake.FAKE_ASUP_DATA['operating-mode'],
                          eseries_fake.FAKE_ABOUT_RESPONSE['version']))
        self.mock_object(
            self.my_client, 'get_asup_info',
            return_value=eseries_fake.GET_ASUP_RETURN)
        self.mock_object(
            self.my_client, 'set_counter', return_value={'value': 1})
        mock_invoke = self.mock_object(
            self.my_client, '_invoke',
            return_value=eseries_fake.FAKE_ASUP_DATA)

        client.RestClient.add_autosupport_data(
            self.my_client,
            eseries_fake.FAKE_KEY,
            eseries_fake.FAKE_ASUP_DATA
        )

        mock_invoke.assert_called_with(*eseries_fake.FAKE_POST_INVOKE_DATA)

    @ddt.data((eseries_fake.FAKE_SERIAL_NUMBERS,
               eseries_fake.HARDWARE_INVENTORY),
              (eseries_fake.FAKE_DEFAULT_SERIAL_NUMBER, {}),
              (eseries_fake.FAKE_SERIAL_NUMBER,
               eseries_fake.HARDWARE_INVENTORY_SINGLE_CONTROLLER))
    @ddt.unpack
    def test_get_asup_info_serial_numbers(self, expected_serial_numbers,
                                          controllers):
        self.mock_object(
            client.RestClient, 'list_hardware_inventory',
            return_value=controllers)
        self.mock_object(
            client.RestClient, 'list_storage_system', return_value={})

        sn = client.RestClient.get_asup_info(self.my_client)['serial_numbers']

        self.assertEqual(expected_serial_numbers, sn)

    def test_get_asup_info_model_name(self):
        self.mock_object(
            client.RestClient, 'list_hardware_inventory',
            return_value=eseries_fake.HARDWARE_INVENTORY)
        self.mock_object(
            client.RestClient, 'list_storage_system',
            return_value=eseries_fake.STORAGE_SYSTEM)

        model_name = client.RestClient.get_asup_info(self.my_client)['model']

        self.assertEqual(eseries_fake.HARDWARE_INVENTORY['controllers'][0]
                         ['modelName'], model_name)

    def test_get_asup_info_model_name_empty_controllers_list(self):
        self.mock_object(
            client.RestClient, 'list_hardware_inventory', return_value={})
        self.mock_object(
            client.RestClient, 'list_storage_system', return_value={})

        model_name = client.RestClient.get_asup_info(self.my_client)['model']

        self.assertEqual(eseries_fake.FAKE_DEFAULT_MODEL, model_name)

    def test_get_eseries_api_info(self):
        fake_invoke_service = mock.Mock()
        fake_invoke_service.json = mock.Mock(
            return_value=eseries_fake.FAKE_ABOUT_RESPONSE)
        self.mock_object(
            client.RestClient, '_get_resource_url',
            return_value=eseries_fake.FAKE_RESOURCE_URL)
        self.mock_object(
            self.my_client, 'invoke_service', return_value=fake_invoke_service)

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
        status_code = http_client.NOT_FOUND
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
        status_code = http_client.UNPROCESSABLE_ENTITY
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
        self.assertDictEqual(expected_volume, updated_volume)

    def test_get_pool_operation_progress(self):
        fake_pool = copy.deepcopy(eseries_fake.STORAGE_POOL)
        fake_response = copy.deepcopy(eseries_fake.FAKE_POOL_ACTION_PROGRESS)
        self.my_client._invoke = mock.Mock(return_value=fake_response)

        response = self.my_client.get_pool_operation_progress(fake_pool['id'])

        url = self.my_client.RESOURCE_PATHS.get('pool_operation_progress')
        self.my_client._invoke.assert_called_once_with('GET', url,
                                                       **{'object-id':
                                                          fake_pool['id']})
        self.assertEqual(fake_response, response)

    def test_extend_volume(self):
        new_capacity = 10
        fake_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=True)
        self.my_client._invoke = mock.Mock(return_value=fake_volume)

        expanded_volume = self.my_client.expand_volume(fake_volume['id'],
                                                       new_capacity, False)

        url = self.my_client.RESOURCE_PATHS.get('volume_expand')
        body = {'expansionSize': new_capacity, 'sizeUnit': 'gb'}
        self.my_client._invoke.assert_called_once_with('POST', url, body,
                                                       **{'object-id':
                                                          fake_volume['id']})
        self.assertEqual(fake_volume, expanded_volume)

    def test_extend_volume_thin(self):
        new_capacity = 10
        fake_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.my_client.features = mock.Mock()
        self.my_client.features.SSC_API_V2 = na_utils.FeatureState(
            supported=True)
        self.my_client._invoke = mock.Mock(return_value=fake_volume)

        expanded_volume = self.my_client.expand_volume(fake_volume['id'],
                                                       new_capacity, True)

        url = self.my_client.RESOURCE_PATHS.get('thin_volume_expand')
        body = {'newVirtualSize': new_capacity, 'sizeUnit': 'gb',
                'newRepositorySize': new_capacity}
        self.my_client._invoke.assert_called_once_with('POST', url, body,
                                                       **{'object-id':
                                                          fake_volume['id']})
        self.assertEqual(fake_volume, expanded_volume)

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
                                                          fake_volume['id']})

    def test_list_snapshot_group(self):
        grp = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        invoke = self.mock_object(self.my_client, '_invoke', return_value=grp)
        fake_ref = 'fake'

        result = self.my_client.list_snapshot_group(fake_ref)

        self.assertEqual(grp, result)
        invoke.assert_called_once_with(
            'GET', self.my_client.RESOURCE_PATHS['snapshot_group'],
            **{'object-id': fake_ref})

    def test_list_snapshot_groups(self):
        grps = [copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)]
        invoke = self.mock_object(self.my_client, '_invoke', return_value=grps)

        result = self.my_client.list_snapshot_groups()

        self.assertEqual(grps, result)
        invoke.assert_called_once_with(
            'GET', self.my_client.RESOURCE_PATHS['snapshot_groups'])

    def test_delete_snapshot_group(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        fake_ref = 'fake'

        self.my_client.delete_snapshot_group(fake_ref)

        invoke.assert_called_once_with(
            'DELETE', self.my_client.RESOURCE_PATHS['snapshot_group'],
            **{'object-id': fake_ref})

    @ddt.data((None, None, None, None, None), ('1', 50, 75, 32, 'purgepit'))
    @ddt.unpack
    def test_create_snapshot_group(self, pool_id, repo, warn, limit, policy):
        vol = copy.deepcopy(eseries_fake.SNAPSHOT_VOLUME)
        invoke = self.mock_object(self.my_client, '_invoke', return_value=vol)
        snap_grp = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)

        result = self.my_client.create_snapshot_group(
            snap_grp['label'], snap_grp['id'], pool_id, repo, warn, limit,
            policy)

        self.assertEqual(vol, result)
        invoke.assert_called_once_with(
            'POST', self.my_client.RESOURCE_PATHS['snapshot_groups'],
            {'baseMappableObjectId': snap_grp['id'], 'name': snap_grp['label'],
                'storagePoolId': pool_id, 'repositoryPercentage': repo,
                'warningThreshold': warn, 'autoDeleteLimit': limit,
             'fullPolicy': policy})

    def test_list_snapshot_volumes(self):
        vols = [copy.deepcopy(eseries_fake.SNAPSHOT_VOLUME)]
        invoke = self.mock_object(self.my_client, '_invoke', return_value=vols)

        result = self.my_client.list_snapshot_volumes()

        self.assertEqual(vols, result)
        invoke.assert_called_once_with(
            'GET', self.my_client.RESOURCE_PATHS['snapshot_volumes'])

    def test_delete_snapshot_volume(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        fake_ref = 'fake'

        self.my_client.delete_snapshot_volume(fake_ref)

        invoke.assert_called_once_with(
            'DELETE', self.my_client.RESOURCE_PATHS['snapshot_volume'],
            **{'object-id': fake_ref})

    @ddt.data((None, None, None, None), ('1', 50, 75, 'readWrite'))
    @ddt.unpack
    def test_create_snapshot_volume(self, pool_id, repo, warn, mode):
        vol = copy.deepcopy(eseries_fake.SNAPSHOT_VOLUME)
        invoke = self.mock_object(self.my_client, '_invoke', return_value=vol)

        result = self.my_client.create_snapshot_volume(
            vol['basePIT'], vol['label'], vol['id'], pool_id,
            repo, warn, mode)

        self.assertEqual(vol, result)
        invoke.assert_called_once_with(
            'POST', self.my_client.RESOURCE_PATHS['snapshot_volumes'],
            mock.ANY)

    def test_update_snapshot_volume(self):
        snap_id = '1'
        label = 'name'
        pct = 99
        vol = copy.deepcopy(eseries_fake.SNAPSHOT_VOLUME)
        invoke = self.mock_object(self.my_client, '_invoke', return_value=vol)

        result = self.my_client.update_snapshot_volume(snap_id, label, pct)

        self.assertEqual(vol, result)
        invoke.assert_called_once_with(
            'POST', self.my_client.RESOURCE_PATHS['snapshot_volume'],
            {'name': label, 'fullThreshold': pct}, **{'object-id': snap_id})

    def test_create_snapshot_image(self):
        img = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        invoke = self.mock_object(self.my_client, '_invoke', return_value=img)
        grp_id = '1'

        result = self.my_client.create_snapshot_image(grp_id)

        self.assertEqual(img, result)
        invoke.assert_called_once_with(
            'POST', self.my_client.RESOURCE_PATHS['snapshot_images'],
            {'groupId': grp_id})

    def test_list_snapshot_image(self):
        img = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        invoke = self.mock_object(self.my_client, '_invoke', return_value=img)
        fake_ref = 'fake'

        result = self.my_client.list_snapshot_image(fake_ref)

        self.assertEqual(img, result)
        invoke.assert_called_once_with(
            'GET', self.my_client.RESOURCE_PATHS['snapshot_image'],
            **{'object-id': fake_ref})

    def test_list_snapshot_images(self):
        imgs = [copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)]
        invoke = self.mock_object(self.my_client, '_invoke', return_value=imgs)

        result = self.my_client.list_snapshot_images()

        self.assertEqual(imgs, result)
        invoke.assert_called_once_with(
            'GET', self.my_client.RESOURCE_PATHS['snapshot_images'])

    def test_delete_snapshot_image(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        fake_ref = 'fake'

        self.my_client.delete_snapshot_image(fake_ref)

        invoke.assert_called_once_with(
            'DELETE', self.my_client.RESOURCE_PATHS['snapshot_image'],
            **{'object-id': fake_ref})

    def test_create_consistency_group(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        name = 'fake'

        self.my_client.create_consistency_group(name)

        invoke.assert_called_once_with(
            'POST', self.my_client.RESOURCE_PATHS['cgroups'], mock.ANY)

    def test_list_consistency_group(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        ref = 'fake'

        self.my_client.get_consistency_group(ref)

        invoke.assert_called_once_with(
            'GET', self.my_client.RESOURCE_PATHS['cgroup'],
            **{'object-id': ref})

    def test_list_consistency_groups(self):
        invoke = self.mock_object(self.my_client, '_invoke')

        self.my_client.list_consistency_groups()

        invoke.assert_called_once_with(
            'GET', self.my_client.RESOURCE_PATHS['cgroups'])

    def test_delete_consistency_group(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        ref = 'fake'

        self.my_client.delete_consistency_group(ref)

        invoke.assert_called_once_with(
            'DELETE', self.my_client.RESOURCE_PATHS['cgroup'],
            **{'object-id': ref})

    def test_add_consistency_group_member(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        vol_id = eseries_fake.VOLUME['id']
        cg_id = eseries_fake.FAKE_CONSISTENCY_GROUP['id']

        self.my_client.add_consistency_group_member(vol_id, cg_id)

        invoke.assert_called_once_with(
            'POST', self.my_client.RESOURCE_PATHS['cgroup_members'],
            mock.ANY, **{'object-id': cg_id})

    def test_remove_consistency_group_member(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        vol_id = eseries_fake.VOLUME['id']
        cg_id = eseries_fake.FAKE_CONSISTENCY_GROUP['id']

        self.my_client.remove_consistency_group_member(vol_id, cg_id)

        invoke.assert_called_once_with(
            'DELETE', self.my_client.RESOURCE_PATHS['cgroup_member'],
            **{'object-id': cg_id, 'vol-id': vol_id})

    def test_create_consistency_group_snapshot(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        path = self.my_client.RESOURCE_PATHS.get('cgroup_snapshots')
        cg_id = eseries_fake.FAKE_CONSISTENCY_GROUP['id']

        self.my_client.create_consistency_group_snapshot(cg_id)

        invoke.assert_called_once_with('POST', path, **{'object-id': cg_id})

    @ddt.data(0, 32)
    def test_delete_consistency_group_snapshot(self, seq_num):
        invoke = self.mock_object(self.my_client, '_invoke')
        path = self.my_client.RESOURCE_PATHS.get('cgroup_snapshot')
        cg_id = eseries_fake.FAKE_CONSISTENCY_GROUP['id']

        self.my_client.delete_consistency_group_snapshot(cg_id, seq_num)

        invoke.assert_called_once_with(
            'DELETE', path, **{'object-id': cg_id, 'seq-num': seq_num})

    def test_get_consistency_group_snapshots(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        path = self.my_client.RESOURCE_PATHS.get('cgroup_snapshots')
        cg_id = eseries_fake.FAKE_CONSISTENCY_GROUP['id']

        self.my_client.get_consistency_group_snapshots(cg_id)

        invoke.assert_called_once_with(
            'GET', path, **{'object-id': cg_id})

    def test_create_cg_snapshot_view(self):
        cg_snap_view = copy.deepcopy(
            eseries_fake.FAKE_CONSISTENCY_GROUP_SNAPSHOT_VOLUME)
        view = copy.deepcopy(eseries_fake.SNAPSHOT_VOLUME)
        invoke = self.mock_object(self.my_client, '_invoke',
                                  return_value=cg_snap_view)
        list_views = self.mock_object(
            self.my_client, 'list_cg_snapshot_views', return_value=[view])
        name = view['name']
        snap_id = view['basePIT']
        path = self.my_client.RESOURCE_PATHS.get('cgroup_cgsnap_views')
        cg_id = eseries_fake.FAKE_CONSISTENCY_GROUP['id']

        self.my_client.create_cg_snapshot_view(cg_id, name, snap_id)

        invoke.assert_called_once_with(
            'POST', path, mock.ANY, **{'object-id': cg_id})
        list_views.assert_called_once_with(cg_id, cg_snap_view['cgViewRef'])

    def test_create_cg_snapshot_view_not_found(self):
        cg_snap_view = copy.deepcopy(
            eseries_fake.FAKE_CONSISTENCY_GROUP_SNAPSHOT_VOLUME)
        view = copy.deepcopy(eseries_fake.SNAPSHOT_VOLUME)
        invoke = self.mock_object(self.my_client, '_invoke',
                                  return_value=cg_snap_view)
        list_views = self.mock_object(
            self.my_client, 'list_cg_snapshot_views', return_value=[view])
        del_view = self.mock_object(self.my_client, 'delete_cg_snapshot_view')
        name = view['name']
        # Ensure we don't get a match on the retrieved views
        snap_id = None
        path = self.my_client.RESOURCE_PATHS.get('cgroup_cgsnap_views')
        cg_id = eseries_fake.FAKE_CONSISTENCY_GROUP['id']

        self.assertRaises(
            exception.NetAppDriverException,
            self.my_client.create_cg_snapshot_view, cg_id, name, snap_id)

        invoke.assert_called_once_with(
            'POST', path, mock.ANY, **{'object-id': cg_id})
        list_views.assert_called_once_with(cg_id, cg_snap_view['cgViewRef'])
        del_view.assert_called_once_with(cg_id, cg_snap_view['id'])

    def test_list_cg_snapshot_views(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        path = self.my_client.RESOURCE_PATHS.get('cgroup_snapshot_views')
        cg_id = eseries_fake.FAKE_CONSISTENCY_GROUP['id']
        view_id = 'id'

        self.my_client.list_cg_snapshot_views(cg_id, view_id)

        invoke.assert_called_once_with(
            'GET', path, **{'object-id': cg_id, 'view-id': view_id})

    def test_delete_cg_snapshot_view(self):
        invoke = self.mock_object(self.my_client, '_invoke')
        path = self.my_client.RESOURCE_PATHS.get('cgroup_snap_view')
        cg_id = eseries_fake.FAKE_CONSISTENCY_GROUP['id']
        view_id = 'id'

        self.my_client.delete_cg_snapshot_view(cg_id, view_id)

        invoke.assert_called_once_with(
            'DELETE', path, **{'object-id': cg_id, 'view-id': view_id})

    @ddt.data('00.00.00.00', '01.52.9000.2', '01.52.9001.2', '01.51.9000.3',
              '01.51.9001.3', '01.51.9010.5', '0.53.9000.3', '0.53.9001.4')
    def test_api_version_not_support_asup(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         return_value=('proxy', api_version))

        client.RestClient._init_features(self.my_client)

        self.assertFalse(self.my_client.features.AUTOSUPPORT.supported)

    @ddt.data('01.52.9000.3', '01.52.9000.4', '01.52.8999.2',
              '01.52.8999.3', '01.53.8999.3', '01.53.9000.2',
              '02.51.9000.3', '02.52.8999.3', '02.51.8999.2')
    def test_api_version_supports_asup(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         return_value=('proxy', api_version))

        client.RestClient._init_features(self.my_client)

        self.assertTrue(self.my_client.features.AUTOSUPPORT)

    @ddt.data('00.00.00.00', '01.52.9000.2', '01.52.9001.2', '01.51.9000.3',
              '01.51.9001.3', '01.51.9010.5', '0.53.9000.3', '0.53.9001.4')
    def test_api_version_not_support_chap(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         return_value=('proxy', api_version))

        client.RestClient._init_features(self.my_client)

        self.assertFalse(self.my_client.features.CHAP_AUTHENTICATION)

    @ddt.data('01.53.9000.15', '01.53.9000.16', '01.53.8999.15',
              '01.54.8999.16', '01.54.9010.15', '01.54.9090.15',
              '02.52.9000.15', '02.53.8999.15', '02.54.8999.14')
    def test_api_version_supports_chap(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         return_value=('proxy', api_version))

        client.RestClient._init_features(self.my_client)

        self.assertTrue(self.my_client.features.CHAP_AUTHENTICATION)

    @ddt.data('00.00.00.00', '01.52.9000.1', '01.52.9001.2', '00.53.9001.3',
              '01.53.9090.1', '1.53.9010.14', '0.53.9011.15')
    def test_api_version_not_support_ssc_api(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         return_value=('proxy', api_version))

        client.RestClient._init_features(self.my_client)

        self.assertFalse(self.my_client.features.SSC_API_V2.supported)

    @ddt.data('01.53.9000.1', '01.53.9000.5', '01.53.8999.1',
              '01.53.9010.20', '01.53.9010.17', '01.54.9000.1',
              '02.51.9000.3', '02.52.8999.3', '02.51.8999.2')
    def test_api_version_supports_ssc_api(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         return_value=('proxy', api_version))

        client.RestClient._init_features(self.my_client)

        self.assertTrue(self.my_client.features.SSC_API_V2.supported)

    @ddt.data('00.00.00.00', '01.52.9000.5', '01.52.9001.2', '00.53.9001.3',
              '01.52.9090.1', '1.52.9010.7', '0.53.9011.7')
    def test_api_version_not_support_1_3(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         return_value=('proxy', api_version))

        client.RestClient._init_features(self.my_client)

        self.assertFalse(self.my_client.features.REST_1_3_RELEASE.supported)

    @ddt.data('01.53.9000.1', '01.53.9000.5', '01.53.8999.1',
              '01.54.9010.20', '01.54.9000.1', '02.51.9000.3',
              '02.52.8999.3', '02.51.8999.2')
    def test_api_version_1_3(self, api_version):

        self.mock_object(client.RestClient,
                         'get_eseries_api_info',
                         return_value=('proxy', api_version))

        client.RestClient._init_features(self.my_client)

        self.assertTrue(self.my_client.features.REST_1_3_RELEASE.supported)

    def test_invoke_bad_content_type(self):
        """Tests the invoke behavior with a non-JSON response"""
        fake_response = mock.Mock()
        fake_response.json = mock.Mock(side_effect=scanner.JSONDecodeError(
            '', '{}', 1))
        fake_response.status_code = http_client.FAILED_DEPENDENCY
        fake_response.text = "Fake Response"
        self.mock_object(self.my_client, 'invoke_service',
                         return_value=fake_response)

        self.assertRaises(es_exception.WebServiceException,
                          self.my_client._invoke, 'GET',
                          eseries_fake.FAKE_ENDPOINT_HTTP)

    def test_list_backend_store(self):
        path = self.my_client.RESOURCE_PATHS.get('persistent-store')
        fake_store = copy.deepcopy(eseries_fake.FAKE_BACKEND_STORE)
        invoke = self.mock_object(
            self.my_client, '_invoke', return_value=fake_store)
        expected = json.loads(fake_store.get('value'))

        result = self.my_client.list_backend_store('key')

        self.assertEqual(expected, result)
        invoke.assert_called_once_with('GET', path, key='key')

    def test_save_backend_store(self):
        path = self.my_client.RESOURCE_PATHS.get('persistent-stores')
        fake_store = copy.deepcopy(eseries_fake.FAKE_BACKEND_STORE)
        key = 'key'
        invoke = self.mock_object(self.my_client, '_invoke')

        self.my_client.save_backend_store(key, fake_store)

        invoke.assert_called_once_with('POST', path, mock.ANY)


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
                         return_value=eseries_fake.FAKE_INVOC_MSG)
        result = self.webclient.invoke_service()

        self.assertIsNotNone(result)
