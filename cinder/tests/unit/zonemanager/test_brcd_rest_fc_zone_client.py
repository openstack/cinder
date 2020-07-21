# Copyright 2020 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from unittest import mock

import ddt

from cinder.tests.unit import test
from cinder.zonemanager.drivers.brocade import brcd_rest_fc_zone_client as \
    rest_client
from cinder.zonemanager.drivers.brocade import fc_zone_constants


@ddt.ddt
class TestBrcdRestClient(test.TestCase):
    def setUp(self):
        super(TestBrcdRestClient, self).setUp()
        self.client = self._get_client()

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_login', mock.Mock())
    def _get_client(self,
                    ip=mock.sentinel.ipaddress,
                    user=mock.sentinel.username,
                    password=mock.sentinel.password,
                    port=mock.sentinel.port,
                    vfid=mock.sentinel.vfid,
                    protocol=mock.sentinel.protocol):
        return rest_client.BrcdRestFCZoneClient(ip, user, password, port, vfid,
                                                protocol)

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_login')
    def test_init(self, login_mock):
        res = rest_client.BrcdRestFCZoneClient(mock.sentinel.ipaddress,
                                               mock.sentinel.username,
                                               mock.sentinel.password,
                                               mock.sentinel.port,
                                               mock.sentinel.vfid,
                                               mock.sentinel.protocol)

        self.assertEqual(mock.sentinel.ipaddress, res.sw_ip)
        self.assertEqual(mock.sentinel.username, res.sw_user)
        self.assertEqual(mock.sentinel.password, res.sw_pwd)
        self.assertEqual(mock.sentinel.vfid, res.vfid)
        self.assertEqual(mock.sentinel.protocol, res.protocol)
        # Port parameter is not used by the class
        self.assertEqual('', res.status_code)
        self.assertIsNone(res.session)
        login_mock.assert_called_once_with()

    @ddt.data((False, '7.4.0'), (False, '8.2.0'),
              (True, '8.2.1'), (True, '9.0.0'))
    @ddt.unpack
    @mock.patch.object(rest_client.BrcdRestFCZoneClient,
                       '_get_firmware_version')
    def test_is_supported_firmware(self, expected, version, mock_get_fw):
        mock_get_fw.return_value = version

        res = self.client.is_supported_firmware()

        self.assertIs(expected, res)
        mock_get_fw.assert_called_once_with()

    @mock.patch.object(rest_client.BrcdRestFCZoneClient,
                       '_get_effective_zone_set')
    def test_get_active_zone_set(self, get_effective_mock):
        get_effective_mock.return_value = (mock.sentinel.active_zone_set,
                                           mock.sentinel.checksum)
        res = self.client.get_active_zone_set()
        self.assertEqual(mock.sentinel.active_zone_set, res)
        get_effective_mock.assert_called_once_with()

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_get_name_server')
    def test_get_nameserver_info(self, get_ns_mock):
        res = self.client.get_nameserver_info()
        self.assertEqual(get_ns_mock.return_value, res)
        get_ns_mock.assert_called_once_with()

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_add_zones')
    def test_add_zones(self, add_mock):
        self.client.add_zones(mock.sentinel.add_zone_map,
                              mock.sentinel.activate,
                              mock.sentinel.active_zone_set__not_used)
        add_mock.assert_called_once_with(mock.sentinel.add_zone_map,
                                         mock.sentinel.activate)

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_update_zones')
    def test_update_zones(self, update_mock):
        self.client.update_zones(mock.sentinel.zone_map,
                                 mock.sentinel.activate,
                                 mock.sentinel.operation,
                                 mock.sentinel.active_zone_set__not_used)
        update_mock.assert_called_once_with(mock.sentinel.zone_map,
                                            mock.sentinel.activate,
                                            mock.sentinel.operation)

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_delete_zones')
    def test_delete_zones(self, delete_mock):
        self.client.delete_zones(mock.sentinel.zone_names,
                                 mock.sentinel.activate,
                                 mock.sentinel.active_zone_set__not_used)
        delete_mock.assert_called_once_with(mock.sentinel.zone_names,
                                            mock.sentinel.activate)

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_logout')
    def test_cleanup(self, logout_mock):
        self.client.cleanup()
        logout_mock.assert_called_once_with()

    @ddt.data(200, 400)
    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_build_url')
    @mock.patch.object(rest_client, 'requests')
    def test__login(self, status_code, requests_mock, url_mock):
        session_mock = requests_mock.Session
        post_mock = session_mock.return_value.post
        post_mock.return_value.status_code = status_code
        post_mock.return_value.headers = {'Authorization': mock.sentinel.auth}

        adapter_mock = requests_mock.adapters.HTTPAdapter
        adapter_mock.return_value = 'adapter'

        client = self._get_client(protocol=fc_zone_constants.REST_HTTPS,
                                  user='username', password='password')
        expected_headers = {'User-Agent': 'OpenStack Zone Driver',
                            'Accept': 'application/yang-data+json',
                            'Content-Type': 'application/yang-data+json',
                            'Authorization': mock.sentinel.auth}
        try:
            res = client._login()
            self.assertEqual(200, res)
        except rest_client.exception.BrocadeZoningRestException:
            self.assertNotEqual(200, status_code)
            expected_headers['Authorization'] = ('Basic '
                                                 'dXNlcm5hbWU6cGFzc3dvcmQ=')
            del expected_headers['Content-Type']

        self.assertEqual(fc_zone_constants.HTTPS, client.protocol)
        session_mock.assert_called_once_with()
        self.assertEqual(requests_mock.Session.return_value, client.session)
        adapter_mock.assert_called_once_with(pool_connections=1,
                                             pool_maxsize=1)
        session_mock.return_value.mount.assert_called_once_with('https://',
                                                                'adapter')

        url_mock.assert_called_once_with('/rest/login')
        post_mock.assert_called_once_with(url_mock.return_value)

        self.assertEqual(expected_headers,
                         session_mock.return_value.headers)

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_build_url')
    def test_logout(self, url_mock):
        session = mock.Mock()
        session.post.return_value.status_code = 204
        self.client.session = session

        self.client._logout()

        url_mock.assert_called_once_with('/rest/logout')
        session.post.assert_called_once_with(url_mock.return_value)

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_build_url')
    def test_logout_fail(self, url_mock):
        session = mock.Mock()
        session.post.return_value.status_code = 400
        self.client.session = session

        self.assertRaises(rest_client.exception.BrocadeZoningRestException,
                          self.client._logout)
        url_mock.assert_called_once_with('/rest/logout')
        session.post.assert_called_once_with(url_mock.return_value)

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_build_url')
    def test_get_firmware_version(self, url_mock):
        session = mock.Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {
            'Response': {
                'fibrechannel-switch': {
                    'firmware-version': mock.sentinel.fw_version}}}
        self.client.session = session

        res = self.client._get_firmware_version()

        self.assertEqual(mock.sentinel.fw_version, res)

        url_mock.assert_called_once_with(
            '/rest/running/switch/fibrechannel-switch')
        session.get.assert_called_once_with(url_mock.return_value)
        session.get.return_value.json.assert_called_once_with()

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_build_url')
    def test_get_firmware_version_fail(self, url_mock):
        session = mock.Mock()
        session.get.return_value.status_code = 400
        self.client.session = session

        self.assertRaises(rest_client.exception.BrocadeZoningRestException,
                          self.client._get_firmware_version)

        url_mock.assert_called_once_with(
            '/rest/running/switch/fibrechannel-switch')
        session.get.assert_called_once_with(url_mock.return_value)
        session.get.return_value.json.assert_not_called()

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_build_url')
    def test__get_name_server(self, url_mock):
        session = mock.Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {
            'Response': {
                'fibrechannel-name-server': [
                    {'port-name': mock.sentinel.port1},
                    {'port-name': mock.sentinel.port2}]}}
        self.client.session = session

        res = self.client._get_name_server()

        self.assertEqual([mock.sentinel.port1, mock.sentinel.port2], res)

        url_mock.assert_called_once_with(
            '/rest/running/brocade-name-server/fibrechannel-name-server')
        session.get.assert_called_once_with(url_mock.return_value)
        session.get.return_value.json.assert_called_once_with()

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_build_url')
    def test__get_name_server_fail(self, url_mock):
        session = mock.Mock()
        session.get.return_value.status_code = 400
        self.client.session = session

        self.assertRaises(rest_client.exception.BrocadeZoningRestException,
                          self.client._get_name_server)

        url_mock.assert_called_once_with(
            '/rest/running/brocade-name-server/fibrechannel-name-server')
        session.get.assert_called_once_with(url_mock.return_value)
        session.get.return_value.json.assert_not_called()

    @ddt.data(([{'zone-name': 'zone1',
                 'member-entry': {'entry-name': 'entry1'}},
                {'zone-name': 'zone2',
                 'member-entry': {'entry-name': 'entry2'}}],
               {'zone1': 'entry1', 'zone2': 'entry2'}),
              ({'zone-name': 'zone1',
                'member-entry': {'entry-name': 'entry1'}},
               {'zone1': 'entry1'}),
              ({}, {}))
    @ddt.unpack
    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_build_url')
    def test_get_effective_zone_set(self, enabled_zone, expected_zones,
                                    url_mock):
        session = mock.Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {
            'Response': {
                'effective-configuration': {
                    'checksum': mock.sentinel.checksum,
                    'cfg-name': 'my-cfg',
                    'enabled-zone': enabled_zone}}}
        self.client.session = session

        res = self.client._get_effective_zone_set()

        expected = ({'active_zone_config': 'my-cfg' if expected_zones else '',
                     'zones': expected_zones},
                    mock.sentinel.checksum)
        self.assertEqual(expected, res)

        url_mock.assert_called_once_with(
            '/rest/running/zoning/effective-configuration')
        session.get.assert_called_once_with(url_mock.return_value)
        session.get.return_value.json.assert_called_once_with()

    @mock.patch.object(rest_client.BrcdRestFCZoneClient, '_build_url')
    def test_get_effective_zone_set_fail(self, url_mock):
        session = mock.Mock()
        session.get.return_value.status_code = 400
        self.client.session = session

        self.assertRaises(rest_client.exception.BrocadeZoningRestException,
                          self.client._get_effective_zone_set)

        url_mock.assert_called_once_with(
            '/rest/running/zoning/effective-configuration')
        session.get.assert_called_once_with(url_mock.return_value)
        session.get.return_value.json.assert_not_called()
