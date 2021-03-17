#    Copyright (c) 2020 Open-E, Inc.
#    All Rights Reserved.
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


import json
from unittest import mock

import requests

from cinder import exception
from cinder.tests.unit import test
from cinder.volume.drivers.open_e.jovian_common import exception as jexc
from cinder.volume.drivers.open_e.jovian_common import rest_proxy

UUID_1 = '12345678-1234-1234-1234-000000000001'
UUID_2 = '12345678-1234-1234-1234-000000000002'
UUID_3 = '12345678-1234-1234-1234-000000000003'

CONFIG_OK = {
    'san_hosts': ['192.168.0.2'],
    'san_api_port': 82,
    'driver_use_ssl': 'true',
    'driver_ssl_cert_verify': True,
    'driver_ssl_cert_path': '/etc/cinder/joviandss.crt',
    'jovian_rest_send_repeats': 3,
    'jovian_recovery_delay': 60,
    'san_login': 'admin',
    'san_password': 'password',
    'jovian_ignore_tpath': [],
    'target_port': 3260,
    'jovian_pool': 'Pool-0',
    'iscsi_target_prefix': 'iqn.2020-04.com.open-e.cinder:',
    'chap_password_len': 12,
    'san_thin_provision': False,
    'jovian_block_size': '128K'

}

CONFIG_BAD_IP = {
    'san_hosts': ['asd'],
    'san_api_port': 82,
    'driver_use_ssl': 'true',
    'driver_ssl_cert_verify': True,
    'driver_ssl_cert_path': '/etc/cinder/joviandss.crt',
    'jovian_rest_send_repeats': 3,
    'jovian_recovery_delay': 60,
    'san_login': 'admin',
    'san_password': 'password',
    'jovian_ignore_tpath': [],
    'target_port': 3260,
    'jovian_pool': 'Pool-0',
    'iscsi_target_prefix': 'iqn.2020-04.com.open-e.cinder:',
    'chap_password_len': 12,
    'san_thin_provision': False,
    'jovian_block_size': '128K'

}

CONFIG_MULTIHOST = {
    'san_hosts': ['192.168.0.2', '192.168.0.3', '192.168.0.4'],
    'san_api_port': 82,
    'driver_use_ssl': 'true',
    'driver_ssl_cert_verify': True,
    'driver_ssl_cert_path': '/etc/cinder/joviandss.crt',
    'jovian_rest_send_repeats': 3,
    'jovian_recovery_delay': 60,
    'san_login': 'admin',
    'san_password': 'password',
    'jovian_ignore_tpath': [],
    'target_port': 3260,
    'jovian_pool': 'Pool-0',
    'iscsi_target_prefix': 'iqn.2020-04.com.open-e.cinder:',
    'chap_password_len': 12,
    'san_thin_provision': False,
    'jovian_block_size': '128K'

}


class TestOpenEJovianRESTProxy(test.TestCase):

    def start_patches(self, patches):
        for p in patches:
            p.start()

    def stop_patches(self, patches):
        for p in patches:
            p.stop()

    def test_init(self):

        self.assertRaises(exception.InvalidConfigurationValue,
                          rest_proxy.JovianRESTProxy,
                          CONFIG_BAD_IP)

    def test_get_base_url(self):

        proxy = rest_proxy.JovianRESTProxy(CONFIG_OK)

        url = proxy._get_base_url()

        exp = '{proto}://{host}:{port}/api/v3'.format(
            proto='https',
            host='192.168.0.2',
            port='82')
        self.assertEqual(exp, url)

    def test_next_host(self):

        proxy = rest_proxy.JovianRESTProxy(CONFIG_MULTIHOST)

        self.assertEqual(0, proxy.active_host)
        proxy._next_host()

        self.assertEqual(1, proxy.active_host)
        proxy._next_host()

        self.assertEqual(2, proxy.active_host)
        proxy._next_host()

        self.assertEqual(0, proxy.active_host)

    def test_request(self):

        proxy = rest_proxy.JovianRESTProxy(CONFIG_MULTIHOST)

        patches = [
            mock.patch.object(requests, "Request", return_value="request"),
            mock.patch.object(proxy.session,
                              "prepare_request",
                              return_value="out_data"),
            mock.patch.object(proxy, "_send", return_value="out_data")]

        addr = 'https://192.168.0.2:82/api/v3/pools/Pool-0'

        self.start_patches(patches)
        proxy.request('GET', '/pools/Pool-0')

        requests.Request.assert_called_once_with('GET', addr)
        self.stop_patches(patches)

    def test_request_host_failure(self):

        proxy = rest_proxy.JovianRESTProxy(CONFIG_MULTIHOST)

        patches = [
            mock.patch.object(requests, "Request", return_value="request"),
            mock.patch.object(proxy.session,
                              "prepare_request",
                              return_value="out_data"),
            mock.patch.object(proxy, "_send", return_value="out_data")]

        request_expected = [
            mock.call('GET',
                      'https://192.168.0.2:82/api/v3/pools/Pool-0'),
            mock.call('GET',
                      'https://192.168.0.3:82/api/v3/pools/Pool-0'),
            mock.call('GET',
                      'https://192.168.0.4:82/api/v3/pools/Pool-0')]

        self.start_patches(patches)

        proxy._send.side_effect = [
            requests.exceptions.ConnectionError(),
            requests.exceptions.ConnectionError(),
            "out_data"]

        proxy.request('GET', '/pools/Pool-0')
        self.assertEqual(2, proxy.active_host)
        requests.Request.assert_has_calls(request_expected)

        self.stop_patches(patches)

    def test_pool_request(self):

        proxy = rest_proxy.JovianRESTProxy(CONFIG_OK)

        patches = [mock.patch.object(proxy, "request")]

        req = '/pools/Pool-0/volumes'

        self.start_patches(patches)
        proxy.pool_request('GET', '/volumes')

        proxy.request.assert_called_once_with('GET', req, json_data=None)
        self.stop_patches(patches)

    def test_send(self):

        proxy = rest_proxy.JovianRESTProxy(CONFIG_MULTIHOST)

        json_data = {"data": [{"available": "949998694400",
                               "status": 26,
                               "name": "Pool-0",
                               "scan": None,
                               "encryption": {"enabled": False},
                               "iostats": {"read": "0",
                                           "write": "0",
                                           "chksum": "0"},
                               "vdevs": [{}],
                               "health": "ONLINE",
                               "operation": "none",
                               "id": "12413634663904564349",
                               "size": "996432412672"}],
                     "error": None}
        session_ret = mock.Mock()
        session_ret.text = json.dumps(json_data)
        session_ret.status_code = 200
        patches = [mock.patch.object(proxy.session,
                                     "send",
                                     return_value=session_ret)]

        pr = 'prepared_request'

        self.start_patches(patches)
        ret = proxy._send(pr)

        proxy.session.send.assert_called_once_with(pr)

        self.assertEqual(0, proxy.active_host)

        self.assertEqual(200, ret['code'])
        self.assertEqual(json_data['data'], ret['data'])
        self.assertEqual(json_data['error'], ret['error'])
        self.stop_patches(patches)

    def test_send_connection_error(self):

        proxy = rest_proxy.JovianRESTProxy(CONFIG_MULTIHOST)

        json_data = {"data": None,
                     "error": None}

        session_ret = mock.Mock()
        session_ret.text = json.dumps(json_data)
        session_ret.status_code = 200
        patches = [mock.patch.object(proxy.session, "send")]

        pr = 'prepared_request'

        self.start_patches(patches)

        side_effect = [requests.exceptions.ConnectionError()] * 4
        side_effect += [session_ret]

        proxy.session.send.side_effect = side_effect

        send_expected = [mock.call(pr)] * 4

        ret = proxy._send(pr)

        proxy.session.send.assert_has_calls(send_expected)

        self.assertEqual(0, proxy.active_host)

        self.assertEqual(200, ret['code'])
        self.assertEqual(json_data['data'], ret['data'])
        self.assertEqual(json_data['error'], ret['error'])
        self.stop_patches(patches)

    def test_send_mixed_error(self):

        proxy = rest_proxy.JovianRESTProxy(CONFIG_MULTIHOST)

        json_data = {"data": None,
                     "error": None}

        session_ret = mock.Mock()
        session_ret.text = json.dumps(json_data)
        session_ret.status_code = 200
        patches = [mock.patch.object(proxy.session, "send")]

        pr = 'prepared_request'

        self.start_patches(patches)

        side_effect = [requests.exceptions.ConnectionError()] * 4
        side_effect += [jexc.JDSSOSException()] * 4
        side_effect += [session_ret]

        proxy.session.send.side_effect = side_effect

        send_expected = [mock.call(pr)] * 7

        self.assertRaises(jexc.JDSSOSException, proxy._send, pr)

        proxy.session.send.assert_has_calls(send_expected)

        self.assertEqual(0, proxy.active_host)

    def test_handle_500(self):

        error = {"class": "exceptions.OSError",
                 "errno": 17,
                 "message": ""}

        json_data = {"data": None,
                     "error": error}

        session_ret = mock.Mock()
        session_ret.text = json.dumps(json_data)
        session_ret.status_code = 500

        self.assertRaises(jexc.JDSSOSException,
                          rest_proxy.JovianRESTProxy._handle_500,
                          session_ret)

        session_ret.status_code = 200
        json_data = {"data": None,
                     "error": None}

        session_ret.text = json.dumps(json_data)
        self.assertIsNone(rest_proxy.JovianRESTProxy._handle_500(session_ret))
