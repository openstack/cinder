# Copyright (c) 2024 Dell Inc. or its subsidiaries.
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
import pathlib
from unittest import mock

import requests.exceptions
from requests.models import Response

from cinder import exception
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.dell_emc.powerflex import driver
from cinder.volume.drivers.dell_emc.powerflex import rest_client


class TestPowerFlexClient(test.TestCase):

    params = {'protectionDomainId': '1',
              'storagePoolId': '1',
              'name': 'HlF355XlSg+xcORfS0afag==',
              'volumeType': 'ThinProvisioned',
              'volumeSizeInKb': '1048576',
              'compressionMethod': 'None'}

    expected_status_code = 500
    status_code_ok = mock.Mock(status_code=http_client.OK)
    status_code_bad = mock.Mock(status_code=http_client.BAD_REQUEST)
    response_error = {"errorCode": "123", "message": "Error message"}

    def setUp(self):
        super(TestPowerFlexClient, self).setUp()
        self.configuration = conf.Configuration(driver.powerflex_opts,
                                                conf.SHARED_CONF_GROUP)
        self._set_overrides()
        self.client = rest_client.RestClient(self.configuration)
        self.client.do_setup()

        self.mockup_file_base = (
            str(pathlib.Path.cwd())
            + "/cinder/tests/unit/volume/drivers/dell_emc/powerflex/mockup/"
        )
        self.sdc_id = "01f7117d0000000b"
        self.sdc_guid = "028888FA-502A-4FAC-A888-1FA3B256358C"
        self.volume_id = "3bd1f78800000019"

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

    def _getJsonFile(self, filename):
        f = open(self.mockup_file_base + filename)
        data = json.load(f)
        f.close()
        return data

    def test_query_sdc_id_by_guid_valid(self):
        response = self._getJsonFile("query_sdc_instances_response.json")

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_ok,
                                             response)):
            result = self.client.query_sdc_id_by_guid(self.sdc_guid)
            self.assertEqual(result, self.sdc_id)
            self.client.execute_powerflex_get_request.assert_called_with(
                '/types/Sdc/instances'
            )

    def test_query_sdc_id_by_guid_invalid(self):
        response = self._getJsonFile("query_sdc_instances_response.json")

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_ok,
                                             response)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.query_sdc_id_by_guid,
                                   "invalid_guid")
            self.assertIn(
                "Failed to query SDC by guid invalid_guid: Not Found.",
                ex.msg)

    def test_query_sdc_id_by_guid_exception(self):

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_bad,
                                             self.response_error)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.query_sdc_id_by_guid,
                                   self.sdc_guid)
            self.assertIn(
                "Failed to query SDC: Error message.", ex.msg)

    def test_query_sdc_by_id_success(self):
        response = self._getJsonFile("query_sdc_by_id_response.json")

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_ok,
                                             response)):
            result = self.client.query_sdc_by_id(self.sdc_id)
            self.assertEqual(result, response)
            self.client.execute_powerflex_get_request.assert_called_with(
                '/instances/Sdc::%(sdc_id)s',
                sdc_id=self.sdc_id
            )

    def test_query_sdc_by_id_failure(self):
        host_id = "invalid_id"

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_bad,
                                             self.response_error)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.query_sdc_by_id,
                                   host_id)
            self.assertIn(
                f"Failed to query SDC id {host_id}: Error message.", ex.msg)

    def test_map_volume_success(self):
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_ok,
                                             {})):
            self.client.map_volume(self.volume_id, self.sdc_id)
            self.client.execute_powerflex_post_request.assert_called_with(
                f"/instances/Volume::{self.volume_id}/action/addMappedSdc",
                {"sdcId": self.sdc_id,
                 "allowMultipleMappings": "True"},
            )

    def test_map_volume_failure(self):
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad,
                                             self.response_error)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.map_volume,
                                   self.volume_id, self.sdc_id)
            self.assertIn(
                ("Failed to map volume %(vol_id)s to SDC %(sdc_id)s"
                 % {"vol_id": self.volume_id, "sdc_id": self.sdc_id}),
                ex.msg)

    def test_unmap_volume_success(self):
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_ok,
                                             {})):
            self.client.unmap_volume(self.volume_id, self.sdc_id)
            self.client.execute_powerflex_post_request.assert_called_with(
                f"/instances/Volume::{self.volume_id}/action/removeMappedSdc",
                {"sdcId": self.sdc_id}
            )

    def test_unmap_volume_host_none_success(self):
        with mock.patch.object(self.client,
                               '_unmap_volume_from_all_sdcs',
                               return_value=None):
            self.client.unmap_volume(self.volume_id)
            self.client._unmap_volume_from_all_sdcs.assert_called_with(
                self.volume_id,
            )

    def test_unmap_volume_failure(self):
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad,
                                             self.response_error)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.unmap_volume,
                                   self.volume_id, self.sdc_id)
            self.assertIn(
                ("Failed to unmap volume %(vol_id)s from SDC %(host_id)s"
                 % {"vol_id": self.volume_id, "host_id": self.sdc_id}),
                ex.msg)

    def test_query_sdc_volumes_success(self):
        response = self._getJsonFile("query_sdc_volumes_response.json")

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_ok,
                                             response)):
            result = self.client.query_sdc_volumes(self.sdc_id)
            self.assertEqual(result, ['694a2d140000000b', '694a2d1300000009'])
            self.client.execute_powerflex_get_request.assert_called_with(
                f'/instances/Sdc::{self.sdc_id}/relationships/Volume'
            )

    def test_query_sdc_volumes_failure(self):
        host_id = "invalid_id"

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_bad,
                                             self.response_error)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.query_sdc_volumes,
                                   host_id)
            self.assertIn(
                "Failed to query SDC volumes: Error message.", ex.msg)

    def test_set_sdc_limits_bandwith(self):
        bandwidth_limit = 100

        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_ok,
                                             {})):

            self.client.set_sdc_limits(
                self.volume_id, self.sdc_id, bandwidth_limit=bandwidth_limit)
            url = ("/instances/Volume::%(vol_id)s/action/"
                   "setMappedSdcLimits" % {'vol_id': self.volume_id})
            params = {'sdcId': self.sdc_id,
                      'bandwidthLimitInKbps': bandwidth_limit}
            self.client.execute_powerflex_post_request.assert_called_once_with(
                url, params)

    def test_set_sdc_limits_iops(self):
        iops_limit = 10000

        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_ok,
                                             {})):

            self.client.set_sdc_limits(
                self.volume_id, self.sdc_id, iops_limit=iops_limit)
            url = ("/instances/Volume::%(vol_id)s/action/"
                   "setMappedSdcLimits" % {'vol_id': self.volume_id})
            params = {'sdcId': self.sdc_id,
                      'iopsLimit': iops_limit}
            self.client.execute_powerflex_post_request.assert_called_once_with(
                url, params)

    def test_set_sdc_limits_failure(self):
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad,
                                             self.response_error)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.set_sdc_limits,
                                   self.volume_id, self.sdc_id)
            self.assertIn(
                "Failed to set SDC limits: Error message.",
                ex.msg)
