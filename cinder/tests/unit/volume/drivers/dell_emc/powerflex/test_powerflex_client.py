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

import ddt
import requests.exceptions

from cinder import exception
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.dell_emc.powerflex import driver
from cinder.volume.drivers.dell_emc.powerflex import rest_client


@ddt.ddt
class TestPowerFlexClient(test.TestCase):

    params = {'protectionDomainId': '1',
              'storagePoolId': '1',
              'name': 'HlF355XlSg+xcORfS0afag==',
              'volumeType': 'ThinProvisioned',
              'volumeSizeInKb': '1048576',
              'compressionMethod': 'None'}

    expected_status_code = 500
    response_error = {"errorCode": "123", "message": "Error message"}

    def setUp(self):
        super(TestPowerFlexClient, self).setUp()
        self.status_code_ok = mock.Mock(status_code=http_client.OK)
        self.status_code_bad = mock.Mock(status_code=http_client.BAD_REQUEST)
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
        self.system_id = "1250de83018c2d0f"
        self.system_nqn = "nqn.1988-11.com.dell:powerflex:00:1250de83018c2d0f"
        self.host_id = "13bf228a00010001"
        self.host_nqn = "nqn.2014-08.org.nvmexpress:uuid:" \
            "fc9aaff0-09bb-4825-b590-4897d1a4eade"
        self.host_name = "hostname"

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

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.rest_client.LOG')
    def test_start_token_refresh_thread(self, mock_log):
        self.client._start_token_refresh_thread()
        mock_log.info.assert_called_once_with(
            "Start token refresh thread."
        )

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.rest_client.LOG')
    def test_refresh_token_periodically_success(self, mock_log):

        self.client._refresh_token = mock.Mock(return_value=True)
        expected_interval = self.client._refresh_token_periodically()
        self.assertEqual(expected_interval, 300)
        self.client._refresh_token.assert_called_once()

        succ_info = "Token refresh succeeded. Sleeping for %d seconds."
        mock_log.info.assert_called_once_with(succ_info, 300)

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.rest_client.LOG')
    def test_refresh_token_periodically_failure(self, mock_log):

        self.client._refresh_token = mock.Mock(return_value=False)
        expected_interval = self.client._refresh_token_periodically()
        self.assertEqual(expected_interval, 60)
        self.client._refresh_token.assert_called_once()

        fail_info = "Token refresh failed. Sleeping for %d seconds."
        mock_log.warning.assert_called_once_with(fail_info, 60)

    @mock.patch('requests.get')
    def test_refresh_token_success(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = "fake_token"
        self.assertTrue(self.client._refresh_token())
        self.assertEqual(self.client.rest_token, "fake_token")

    @mock.patch('requests.get')
    def test_refresh_token_exception(self, mock_get):
        mock_get.side_effect = (requests.exceptions.RequestException
                                ('Mocked request exception'))
        self.assertFalse(self.client._refresh_token())

    @mock.patch('requests.get')
    def test_refresh_token_value_error(self, mock_get):
        mock_get.return_value.json.side_effect = ValueError(
            'Mocked JSON decode error')
        self.assertFalse(self.client._refresh_token())

    @mock.patch('requests.get')
    def test_refresh_token_connection_error(self, mock_get):
        mock_get.side_effect = (requests.exceptions.ConnectionError
                                ('Mocked connection error'))
        self.assertFalse(self.client._refresh_token())

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

    def test_query_system_id_nqn_success(self):
        response = self._getJsonFile("query_system_id_nqn_response.json")

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_ok, response)):
            id, nqn = self.client.query_system_id_nqn()
            self.assertEqual(id, self.system_id)
            self.assertEqual(nqn, self.system_nqn)
            self.client.execute_powerflex_get_request.assert_called_with(
                "/types/System/instances"
            )

    def test_query_system_id_nqn_failure(self):
        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_bad,
                                             self.response_error)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.query_system_id_nqn)
            self.assertIn("Failed to query system nqn: Error message.", ex.msg)

    def test_query_SDTs_success(self):
        response = self._getJsonFile("query_sdts_response.json")

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_ok,
                                             response)):
            result = self.client.query_SDTs()
            self.assertEqual(result, response)
            self.assertEqual(result[0]["nvmePort"], 4420)
            self.assertIsNotNone(result[0]["ipList"])
            self.client.execute_powerflex_get_request.assert_called_with(
                "/types/Sdt/instances"
            )

    def test_query_SDTs_failure(self):
        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_bad,
                                             self.response_error)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.query_SDTs)
            self.assertIn("Failed to query SDTs: Error message.", ex.msg)

    def test_query_hosts_successful(self):
        response = self._getJsonFile("query_hosts_response.json")

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_ok,
                                             response)):
            result = self.client.query_hosts()
            self.assertEqual(result, response)
            self.client.execute_powerflex_get_request.assert_called_with(
                "/types/Host/instances"
            )

    def test_query_hosts_failure(self):
        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_bad,
                                             self.response_error)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.query_hosts)
            self.assertIn("Failed to query hosts: Error message.", ex.msg)

    def test_query_host_by_nqn_existing_nqn(self):
        response = self._getJsonFile("query_hosts_response.json")

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_ok,
                                             response)):
            result = self.client.query_host_by_nqn(self.host_nqn)
            self.assertEqual(result, self.host_id)

    def test_query_host_by_nqn_non_existing_nqn(self):
        nqn = "invalid_nqn"
        response = self._getJsonFile("query_hosts_response.json")

        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_ok,
                                             response)):
            self.assertIsNone(self.client.query_host_by_nqn(nqn))

    def test_create_nvme_host_success(self):
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_ok,
                                             {"id": self.host_id})):
            result = self.client.create_nvme_host(
                self.host_name, self.host_nqn)
            self.assertEqual(result, self.host_id)
            self.client.execute_powerflex_post_request.assert_called_with(
                "/types/Host/instances",
                {"nqn": self.host_nqn, "name": self.host_name}
            )

    def test_create_nvme_host_failure(self):
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad,
                                             self.response_error)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.create_nvme_host,
                                   self.host_nqn, self.host_name)
            self.assertIn("Failed to create nvme host: Error message.", ex.msg)

    @mock.patch("cinder.volume.drivers.dell_emc."
                "powerflex.rest_client.RestClient._get_protection_domain_id")
    @mock.patch.object(rest_client.RestClient,
                       'execute_powerflex_post_request')
    def test_init_powerflex_gen_type_success(self,
                                             mock_post,
                                             mock_get_domain_id):
        domain_name = "domain-A"
        domain_id = "domain-id-123"
        mock_get_domain_id.return_value = domain_id

        mock_response = mock.Mock()
        mock_response.status_code = http_client.OK
        mock_post.return_value = (mock_response, [{"genType": "EC"}])

        result = self.client.init_powerflex_gen_type(domain_name)

        self.assertEqual("EC", result)
        mock_get_domain_id.assert_called_once_with(domain_name)
        mock_post.assert_called_once_with(
            "/types/ProtectionDomain/instances/action/queryBySelectedIds",
            {"ids": [domain_id]}
        )

    @mock.patch("cinder.volume.drivers.dell_emc."
                "powerflex.rest_client.RestClient._get_protection_domain_id")
    @mock.patch.object(rest_client.RestClient,
                       'execute_powerflex_post_request')
    def test_init_powerflex_gen_type_multiple_pools_same_gen_type(
            self, mock_post, mock_get_domain_id):
        """Test that multiple pools with the same gen type are handled."""

        pools = [
            ("domain-A", "domain-id-1"),
            ("domain-B", "domain-id-2"),
            ("domain-C", "domain-id-3"),
        ]
        mock_get_domain_id.side_effect = [did for _, did in pools]

        mock_response = mock.Mock()
        mock_response.status_code = http_client.OK
        mock_post.side_effect = [
            (mock_response, [{"genType": "EC"}]),
            (mock_response, [{"genType": "EC"}]),
            (mock_response, [{"genType": "EC"}]),
        ]

        for domain_name, _ in pools:
            result = self.client.init_powerflex_gen_type(domain_name)
            self.assertEqual("EC", result)

        self.assertTrue(self.client.check_powerflex_ec_version())
        self.assertEqual(mock_get_domain_id.call_count, 3)
        self.assertEqual(mock_post.call_count, 3)

    @mock.patch("cinder.volume.drivers.dell_emc.powerflex."
                "rest_client.RestClient._get_protection_domain_id")
    @mock.patch.object(rest_client.RestClient,
                       'execute_powerflex_post_request')
    def test_init_powerflex_gen_type_failure(self,
                                             mock_post,
                                             mock_get_domain_id):
        domain_name = "domain-B"
        domain_id = "domain-id-456"
        mock_get_domain_id.return_value = domain_id

        mock_response = mock.Mock()
        mock_response.status_code = http_client.INTERNAL_SERVER_ERROR
        mock_post.return_value = (mock_response, [])

        ex = self.assertRaises(exception.VolumeBackendAPIException,
                               self.client.init_powerflex_gen_type,
                               domain_name
                               )

        self.assertIn(str(domain_id), str(ex))
        mock_get_domain_id.assert_called_once_with(domain_name)
        mock_post.assert_called_once()

    @ddt.data(
        ("EC", True),
        (None, False),
        ("Mirroring", False),
        ("eC", True),
    )
    @ddt.unpack
    def test_check_powerflex_ec_version(self, gen_type, expected):
        self.client.powerflex_gen_type = gen_type
        self.assertEqual(expected,
                         self.client.check_powerflex_ec_version())

    @mock.patch("cinder.volume.drivers.dell_emc.powerflex."
                "rest_client.RestClient._get_protection_domain_id")
    @mock.patch.object(rest_client.RestClient,
                       'execute_powerflex_post_request')
    def test_init_powerflex_gen_type_v4_backward_compat(
            self, mock_post, mock_get_domain_id):
        """Test backward compatibility with v4 non-EC (Mirroring) system.

        On a v4 PowerFlex system the protection domain genType is
        'Mirroring'. check_powerflex_ec_version() must return False so
        that legacy code paths (granularity rounding, temp snapshots,
        etc.) remain active.
        """

        domain_name = "domain-v4"
        domain_id = "domain-id-v4"
        mock_get_domain_id.return_value = domain_id

        mock_response = mock.Mock()
        mock_response.status_code = http_client.OK
        mock_post.return_value = (mock_response, [{"genType": "Mirroring"}])

        result = self.client.init_powerflex_gen_type(domain_name)

        self.assertEqual("Mirroring", result)
        self.assertFalse(self.client.check_powerflex_ec_version())
        mock_get_domain_id.assert_called_once_with(domain_name)
        mock_post.assert_called_once_with(
            "/types/ProtectionDomain/instances/action/queryBySelectedIds",
            {"ids": [domain_id]}
        )

    @mock.patch("cinder.volume.drivers.dell_emc."
                "powerflex.utils.id_to_base64", return_value="snap-encoded")
    @mock.patch.object(rest_client.RestClient,
                       'execute_powerflex_post_request')
    def test_snapshot_volume_from_source_true(self,
                                              mock_post,
                                              mock_id_to_base64):
        volume_id = "vol-123"
        snapshot_id = "snap-456"

        mock_response = mock.Mock()
        mock_response.status_code = http_client.OK
        mock_post.return_value = (mock_response,
                                  {"volumeIdList": ["snap-vol-789"]})

        result = self.client.snapshot_volume(volume_id,
                                             snapshot_id,
                                             from_source=True)

        self.assertEqual("snap-vol-789", result)
        mock_post.assert_called_once()
        mock_id_to_base64.assert_called_once_with(snapshot_id)

    # Tests for _get_response_message helper

    @ddt.data(
        ({"errorCode": "123", "message": "Some error"}, None, "Some error"),
        ({"errorCode": "123"}, None, "Unknown error"),
        ({"errorCode": "123"}, "Custom default", "Custom default"),
        (None, None, "Unknown error"),
        (None, "Custom default", "Custom default"),
        ({}, None, "Unknown error"),
    )
    @ddt.unpack
    def test_get_response_message(self, response, default, expected):
        if default is not None:
            result = self.client._get_response_message(response, default)
        else:
            result = self.client._get_response_message(response)
        self.assertEqual(result, expected)

    # Tests for NVMe GET methods with various error responses

    @ddt.data(
        ('query_system_id_nqn',
         {"httpStatusCode": 400, "errorCode": 999},
         "Failed to query system nqn: Unknown error."),
        ('query_SDTs',
         {"httpStatusCode": 400, "errorCode": 999},
         "Failed to query SDTs: Unknown error."),
        ('query_hosts',
         {"httpStatusCode": 400, "errorCode": 999},
         "Failed to query hosts: Unknown error."),
        ('query_system_id_nqn',
         {"errorCode": "123", "message": "Error message"},
         "Failed to query system nqn: Error message."),
        ('query_SDTs',
         {"errorCode": "123", "message": "Error message"},
         "Failed to query SDTs: Error message."),
        ('query_hosts',
         {"errorCode": "123", "message": "Error message"},
         "Failed to query hosts: Error message."),
    )
    @ddt.unpack
    def test_nvme_get_method_failure(self, method_name, response,
                                     expected_msg):
        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_bad,
                                             response)):
            method = getattr(self.client, method_name)
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   method)
            self.assertIn(expected_msg, ex.msg)

    # Tests for create_nvme_host with various failure responses

    @ddt.data(
        ({"httpStatusCode": 400, "errorCode": 999},
         "Failed to create nvme host: Unknown error."),
        (None,
         "Failed to create nvme host: Unknown error."),
        ({"errorCode": "123", "message": "Error message"},
         "Failed to create nvme host: Error message."),
    )
    @ddt.unpack
    def test_create_nvme_host_failure_responses(self, response,
                                                expected_msg):
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad,
                                             response)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.create_nvme_host,
                                   self.host_nqn, self.host_name)
            self.assertIn(expected_msg, ex.msg)

    # =========================================================================
    # Tests for non-PowerFlex error responses (e.g. proxy, rate limiter,
    # load balancer returning non-OK without errorCode).
    # These verify that errors are NOT silently swallowed.
    # =========================================================================

    @ddt.data(
        ({"some_field": "some_value"},
         "Failed to query volume: Unknown error."),
        ({"errorCode": "123", "message": "Error message"},
         "Failed to query volume: Error message."),
    )
    @ddt.unpack
    def test_query_volume_failure_bad_response(self, response,
                                               expected_msg):
        """Non-PowerFlex or standard error response must raise."""
        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_bad,
                                             response)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.query_volume,
                                   self.volume_id)
            self.assertIn(expected_msg, ex.msg)

    @ddt.data(
        {"some_field": "some_value"},
        None,
    )
    def test_create_volume_failure_bad_response(self, response):
        """Non-PowerFlex error or None response must still raise."""
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad,
                                             response)):
            with mock.patch.object(self.client,
                                   '_get_protection_domain_id',
                                   return_value='domain_id'):
                with mock.patch.object(self.client,
                                       'get_storage_pool_id',
                                       return_value='pool_id'):
                    ex = self.assertRaises(
                        exception.VolumeBackendAPIException,
                        self.client.create_volume,
                        'PD1', 'SP1', 'vol_id', 1,
                        'ThinProvisioned', 'None')
                    self.assertIn(
                        "Failed to create volume: Unknown error.",
                        ex.msg)

    @ddt.data(
        {"some_field": "some_value"},
        None,
    )
    def test_snapshot_volume_failure_bad_response(self, response):
        """Non-PowerFlex error or None response must still raise."""
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad,
                                             response)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.snapshot_volume,
                                   'vol_provider_id', 'snap_id')
            self.assertIn("Failed to create snapshot", ex.msg)

    @ddt.data(
        {"some_field": "some_value"},
        None,
    )
    def test_remove_volume_failure_bad_response(self, response):
        """Non-PowerFlex error or None response must still raise."""
        with mock.patch.object(self.client,
                               '_unmap_volume_from_all_sdcs'):
            with mock.patch.object(self.client,
                                   'execute_powerflex_post_request',
                                   return_value=(self.status_code_bad,
                                                 response)):
                ex = self.assertRaises(exception.VolumeBackendAPIException,
                                       self.client.remove_volume,
                                       self.volume_id)
                self.assertIn("Failed to delete volume", ex.msg)

    def test_rename_volume_failure_no_error_code(self):
        """Non-PowerFlex error (no errorCode) must still raise."""
        response_no_errorcode = {"some_field": "some_value"}
        volume = {"provider_id": self.volume_id}
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad,
                                             response_no_errorcode)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.rename_volume,
                                   volume, "new_name")
            self.assertIn("Failed to rename volume", ex.msg)

    @ddt.data(
        {"some_field": "some_value"},
        None,
    )
    def test_create_volumes_pair_failure_bad_response(self, response):
        """Non-PowerFlex error or None response must still raise."""
        with mock.patch.object(self.client,
                               '_get_replication_cg_id_by_name',
                               return_value='rcg_id'):
            with mock.patch.object(self.client,
                                   'execute_powerflex_post_request',
                                   return_value=(self.status_code_bad,
                                                 response)):
                ex = self.assertRaises(exception.VolumeBackendAPIException,
                                       self.client.create_volumes_pair,
                                       'rcg_name', 'src_id', 'dest_id')
                self.assertIn("Failed to create volumes pair", ex.msg)

    def test_query_vtree_statistics_failure_no_error_code(self):
        """Non-PowerFlex error (no errorCode) must still raise."""
        response_no_errorcode = {"some_field": "some_value"}
        with mock.patch.object(self.client,
                               'execute_powerflex_get_request',
                               return_value=(self.status_code_bad,
                                             response_no_errorcode)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.query_vtree_statistics,
                                   'vtree_id')
            self.assertIn("Failed to query vtree statistics", ex.msg)

    def test_unmap_volume_from_all_sdcs_failure_none_response(self):
        """POST with None response must still raise."""
        mapped_volume = {"mappedSdcInfo": [{"sdcId": "sdc1"}]}
        with mock.patch.object(self.client,
                               'query_volume',
                               return_value=mapped_volume):
            with mock.patch.object(self.client,
                                   'execute_powerflex_post_request',
                                   return_value=(self.status_code_bad, None)):
                ex = self.assertRaises(exception.VolumeBackendAPIException,
                                       self.client._unmap_volume_from_all_sdcs,
                                       self.volume_id)
                self.assertIn("Failed to unmap volume", ex.msg)

    def test_map_volume_failure_none_response(self):
        """POST with None response must still raise."""
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad, None)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.map_volume,
                                   self.volume_id, self.sdc_id)
            self.assertIn("Failed to map volume", ex.msg)

    def test_set_sdc_limits_failure_none_response(self):
        """POST with None response must still raise."""
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad, None)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.set_sdc_limits,
                                   self.volume_id, self.sdc_id)
            self.assertIn("Failed to set SDC limits: Unknown error.", ex.msg)

    def test_overwrite_volume_content_failure_none_response(self):
        """POST with None response must still raise."""
        volume = mock.Mock()
        volume.id = 'vol_id'
        volume.provider_id = 'vol_provider_id'
        snapshot = mock.Mock()
        snapshot.id = 'snap_id'
        snapshot.provider_id = 'snap_provider_id'
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad, None)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.overwrite_volume_content,
                                   volume, snapshot)
            self.assertIn("Failed to revert volume", ex.msg)

    def test_migrate_vtree_failure_no_error_code(self):
        """Non-PowerFlex error (no errorCode) must still raise."""
        response_no_errorcode = {"some_field": "some_value"}
        volume = mock.Mock()
        volume.id = 'vol_id'
        volume.provider_id = 'vol_provider_id'
        params = {"destSPId": "pool_id"}
        with mock.patch.object(self.client,
                               'execute_powerflex_post_request',
                               return_value=(self.status_code_bad,
                                             response_no_errorcode)):
            ex = self.assertRaises(exception.VolumeBackendAPIException,
                                   self.client.migrate_vtree,
                                   volume, params)
            self.assertIn("Failed to migrate volume", ex.msg)

    def test_failover_failback_replication_cg_failure_none_response(self):
        """POST with None response must still raise."""
        with mock.patch.object(self.client,
                               '_get_replication_cg_id_by_name',
                               return_value='rcg_id'):
            with mock.patch.object(self.client,
                                   'execute_powerflex_post_request',
                                   return_value=(self.status_code_bad, None)):
                ex = self.assertRaises(
                    exception.VolumeBackendAPIException,
                    self.client.failover_failback_replication_cg,
                    'rcg_name', False)
                self.assertIn("Failed to failover rcg", ex.msg)
