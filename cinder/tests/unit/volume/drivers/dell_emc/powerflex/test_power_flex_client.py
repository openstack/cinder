# Copyright (c) 2021 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import http.client as http_client
import json
from unittest import mock

import ddt
import requests.exceptions
from requests.models import Response

from cinder.tests.unit.volume.drivers.dell_emc import powerflex
from cinder.volume import configuration as conf
from cinder.volume.drivers.dell_emc.powerflex import driver
from cinder.volume.drivers.dell_emc.powerflex import rest_client


@ddt.ddt
class TestPowerFlexClient(powerflex.TestPowerFlexDriver):

    params = {'protectionDomainId': '1',
              'storagePoolId': '1',
              'name': 'HlF355XlSg+xcORfS0afag==',
              'volumeType': 'ThinProvisioned',
              'volumeSizeInKb': '1048576',
              'compressionMethod': 'None'}

    expected_status_code = 500

    def setUp(self):
        super(TestPowerFlexClient, self).setUp()
        self.configuration = conf.Configuration(driver.powerflex_opts,
                                                conf.SHARED_CONF_GROUP)
        self._set_overrides()
        self.client = rest_client.RestClient(self.configuration)
        self.client.do_setup()

    def _set_overrides(self):
        # Override the defaults to fake values
        self.override_config('san_ip', override='127.0.0.1',
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('powerflex_rest_server_port', override='8888',
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('san_login', override='test',
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('san_password', override='pass',
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('powerflex_storage_pools',
                             override='PD1:SP1',
                             group=conf.SHARED_CONF_GROUP)
        self.override_config('max_over_subscription_ratio',
                             override=5.0, group=conf.SHARED_CONF_GROUP)
        self.override_config('powerflex_server_api_version',
                             override='2.0.0', group=conf.SHARED_CONF_GROUP)
        self.override_config('rest_api_connect_timeout',
                             override=120, group=conf.SHARED_CONF_GROUP)
        self.override_config('rest_api_read_timeout',
                             override=120, group=conf.SHARED_CONF_GROUP)

    @mock.patch("requests.get")
    def test_rest_get_request_connect_timeout_exception(self, mock_request):
        mock_request.side_effect = (requests.
                                    exceptions.ConnectTimeout
                                    ('Fake Connect Timeout Exception'))
        r, res = (self.client.
                  execute_powerflex_get_request(url="/version", **{}))
        self.assertEqual(self.expected_status_code, r.status_code)
        self.assertEqual(self.expected_status_code, res['errorCode'])
        (self.assertEqual
         ('The request to URL /version failed with timeout exception '
          'Fake Connect Timeout Exception', res['message']))

    @mock.patch("requests.get")
    def test_rest_get_request_read_timeout_exception(self, mock_request):
        mock_request.side_effect = (requests.exceptions.ReadTimeout
                                    ('Fake Read Timeout Exception'))
        r, res = (self.client.
                  execute_powerflex_get_request(url="/version", **{}))
        self.assertEqual(self.expected_status_code, r.status_code)
        self.assertEqual(self.expected_status_code, res['errorCode'])
        (self.assertEqual
         ('The request to URL /version failed with timeout exception '
          'Fake Read Timeout Exception', res['message']))

    @mock.patch("requests.post")
    def test_rest_post_request_connect_timeout_exception(self, mock_request):
        mock_request.side_effect = (requests.exceptions.ConnectTimeout
                                    ('Fake Connect Timeout Exception'))
        r, res = (self.client.execute_powerflex_post_request
                  (url="/types/Volume/instances", params=self.params, **{}))
        self.assertEqual(self.expected_status_code, r.status_code)
        self.assertEqual(self.expected_status_code, res['errorCode'])
        (self.assertEqual
         ('The request to URL /types/Volume/instances failed with '
          'timeout exception Fake Connect Timeout Exception', res['message']))

    @mock.patch("requests.post")
    def test_rest_post_request_read_timeout_exception(self, mock_request):
        mock_request.side_effect = (requests.exceptions.ReadTimeout
                                    ('Fake Read Timeout Exception'))
        r, res = (self.client.execute_powerflex_post_request
                  (url="/types/Volume/instances", params=self.params, **{}))
        self.assertEqual(self.expected_status_code, r.status_code)
        self.assertEqual(self.expected_status_code, res['errorCode'])
        (self.assertEqual
         ('The request to URL /types/Volume/instances failed with '
          'timeout exception Fake Read Timeout Exception', res['message']))

    @mock.patch("requests.get")
    def test_response_check_read_timeout_exception_1(self, mock_request):
        r = requests.Response
        r.status_code = http_client.UNAUTHORIZED
        mock_request.side_effect = [r, (requests.exceptions.ReadTimeout
                                    ('Fake Read Timeout Exception'))]
        r, res = (self.client.
                  execute_powerflex_get_request(url="/version", **{}))
        self.assertEqual(self.expected_status_code, r.status_code)
        self.assertEqual(self.expected_status_code, res['errorCode'])
        (self.assertEqual
         ('The request to URL /version failed with '
          'timeout exception Fake Read Timeout Exception', res['message']))

    @mock.patch("requests.get")
    def test_response_check_read_timeout_exception_2(self, mock_request):
        res1 = requests.Response
        res1.status_code = http_client.UNAUTHORIZED
        res2 = Response()
        res2.status_code = 200
        res2._content = str.encode(json.dumps('faketoken'))
        mock_request.side_effect = [res1, res2,
                                    (requests.exceptions.ReadTimeout
                                     ('Fake Read Timeout Exception'))]
        r, res = (self.client.
                  execute_powerflex_get_request(url="/version", **{}))
        self.assertEqual(self.expected_status_code, r.status_code)
        self.assertEqual(self.expected_status_code, res['errorCode'])
        (self.assertEqual
         ('The request to URL /version failed with '
          'timeout exception Fake Read Timeout Exception', res['message']))

    @mock.patch("requests.post")
    @mock.patch("requests.get")
    def test_response_check_read_timeout_exception_3(self, mock_post_request,
                                                     mock_get_request):
        r = requests.Response
        r.status_code = http_client.UNAUTHORIZED
        mock_post_request.side_effect = r
        mock_get_request.side_effect = (requests.exceptions.ReadTimeout
                                        ('Fake Read Timeout Exception'))
        r, res = (self.client.execute_powerflex_post_request
                  (url="/types/Volume/instances", params=self.params, **{}))
        self.assertEqual(self.expected_status_code, r.status_code)
        self.assertEqual(self.expected_status_code, res['errorCode'])
        (self.assertEqual
         ('The request to URL /types/Volume/instances failed with '
          'timeout exception Fake Read Timeout Exception', res['message']))
