# Copyright (c) 2026 Dell Inc. or its subsidiaries.
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
from unittest import mock

from cinder.common import constants
from cinder import context
from cinder import exception
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex


class TestNVMe(powerflex.TestPowerFlexNVMeDriver):
    def setUp(self):
        """Setup a test case environment."""

        super(TestNVMe, self).setUp()

        self.client_mock = mock.MagicMock()
        self.driver._get_client = mock.MagicMock(return_value=self.client_mock)

        self.connector = {
            "nqn": "nqn.2014-08.org.nvmexpress:"
            "uuid:c470396a-2a3b-48ad-9c22-d3811fe1036d",
            "host": "hostname"}
        self.ctx = (
            context.RequestContext('fake', 'fake', True, auth_token=True))
        self.volume = fake_volume.fake_volume_obj(
            self.ctx, **{'provider_id': '3bd1f78800000019'})
        self.ips = ['192.168.10.10', '192.168.10.11']
        self.portals = [('192.168.10.10', 4420, 'tcp'),
                        ('192.168.10.11', 4420, 'tcp')]
        self.system_id = "1250de83018c2d0f"
        self.system_nqn = "nqn.1988-11.com.dell:powerflex:00:1250de83018c2d0f"
        self.host_id = "13bf228a00010001"
        self.host = {"name": "hostname"}

    def test_do_setup(self):
        self.driver.do_setup({})
        self.assertEqual(self.driver.storage_protocol,
                         constants.NVMEOF_TCP)

    @mock.patch("cinder.volume.drivers.dell_emc.powerflex.driver."
                "PowerFlexBaseDriver.check_for_setup_error")
    def test_check_for_setup_error(self, mock_super_check_for_setup_error):
        mock_super_check_for_setup_error.return_value = None
        self.driver._validate_nvme = mock.MagicMock(return_value=None)
        self.driver.check_for_setup_error()
        self.driver._validate_nvme.assert_called_once_with()

    def test__validate_nvme_version_success(self):
        self.driver.configuration = mock.MagicMock()
        self.driver.configuration.safe_get.return_value = True
        self.driver.primary_client = mock.MagicMock()
        self.driver.primary_client.query_rest_api_version.return_value = "4.0"
        self.driver._validate_nvme()

    def test__validate_nvme_version_invalid(self):
        self.driver.configuration = mock.MagicMock()
        self.driver.configuration.safe_get.return_value = True
        self.driver.primary_client = mock.MagicMock()
        self.driver.secondary_client = mock.MagicMock()
        self.driver.primary_client.query_rest_api_version.return_value = "3.9"

        ex = self.assertRaises(exception.VolumeDriverException,
                               self.driver._validate_nvme)

        self.assertIn("PowerFlex version 3.9 does not support NVMe-TCP.",
                      ex.msg)

    def test__validate_nvme_version_valid_and_secondary_configured(self):
        self.driver.configuration = mock.MagicMock()
        self.driver.configuration.safe_get.return_value = True
        self.driver.primary_client = mock.MagicMock()
        self.driver.secondary_client = mock.MagicMock()
        self.driver.primary_client.query_rest_api_version.return_value = "4.0"
        self.driver.secondary_client.is_configured = True

        ex = self.assertRaises(exception.InvalidInput,
                               self.driver._validate_nvme)
        self.assertIn(
            "PowerFlex does not support attaching "
            "replicated volumes to NVMe-TCP hosts.",
            ex.msg)

    def test_initialize_connection(self):
        self.driver._initialize_connection = mock.MagicMock()

        self.driver.initialize_connection(self.volume, self.connector)

        self.driver._initialize_connection.assert_called_once_with(
            self.volume, self.connector)

    def test__initialize_connection(self):
        self.driver._get_nvme_connection_properties = mock.MagicMock(
            return_value="connection_info")
        self.driver._create_host_and_attach = mock.MagicMock()

        result = self.driver._initialize_connection(
            self.volume, self.connector)

        self.assertEqual(result, "connection_info")
        self.driver._get_nvme_connection_properties.assert_called_with(
            self.volume.provider_id)
        self.driver._create_host_and_attach.assert_called_with(
            self.connector, self.volume)

    def test__initialize_connection_no_nqn(self):
        ex = self.assertRaises(exception.InvalidHost,
                               self.driver._initialize_connection,
                               self.volume,
                               {})
        self.assertIn("Host nqn is not configured.", ex.msg)

    def test__get_nvme_connection_properties(self):
        expected_volume_nguid = "3bd1f7880000001964b94e83018c2d0f"
        with mock.patch.object(self.driver,
                               '_get_nvme_targets',
                               return_value=(self.portals,
                                             self.system_id,
                                             self.system_nqn)):

            result = self.driver._get_nvme_connection_properties(
                self.volume.provider_id)

        self.assertEqual(
            result["driver_volume_type"], constants.NVMEOF_VARIANT_2)
        self.assertEqual(result["data"]["portals"], self.portals)
        self.assertEqual(result["data"]["target_nqn"], self.system_nqn)
        self.assertEqual(result["data"]["volume_nguid"], expected_volume_nguid)
        self.assertEqual(result["data"]["discard"], True)

    def test__get_nvme_targets_success(self):
        self.client_mock.query_SDTs.return_value = [
            {"ipList": [{"ip": self.ips[0]}, {"ip": self.ips[1]}]}]
        self.client_mock.query_system_id_nqn.return_value = \
            self.system_id, self.system_nqn
        portals, id, nqn = self.driver._get_nvme_targets()
        self.assertEqual(portals, self.portals)
        self.assertEqual(id, self.system_id)
        self.assertEqual(nqn, self.system_nqn)

    def test__get_nvme_targets_duplicate_portals(self):
        self.client_mock.query_SDTs.return_value = [
            {"ipList": [{"ip": self.ips[0]}], "nvmePort": 4420},
            {"ipList": [{"ip": self.ips[0]}, {"ip": self.ips[1]}],
             "nvmePort": 4420},
        ]
        self.client_mock.query_system_id_nqn.return_value = \
            self.system_id, self.system_nqn

        portals, id, nqn = self.driver._get_nvme_targets()

        self.assertEqual(portals, self.portals)
        self.assertEqual(id, self.system_id)
        self.assertEqual(nqn, self.system_nqn)

    def test__get_nvme_targets_failure(self):
        self.client_mock.query_SDTs.return_value = []
        ex = self.assertRaises(exception.VolumeBackendAPIException,
                               self.driver._get_nvme_targets)
        self.assertIn(
            "There are no accessible NVMe targets on the system.", ex.msg)

    def test__create_host_and_attach_success(self):
        self.driver._create_host_if_not_exist = mock.MagicMock(
            return_value=self.host_id)
        self.driver._attach_volume_to_host = mock.MagicMock()
        self.driver._check_volume_mapped = mock.MagicMock()
        self.driver._create_host_and_attach(self.connector, self.volume)

    def test__create_host_if_not_exist_host_exists(self):
        self.client_mock.query_host_by_nqn.return_value = self.host_id
        host_id = self.driver._create_host_if_not_exist('fake-nqn',
                                                        self.connector)
        self.assertEqual(host_id, self.host_id)
        self.client_mock.query_host_by_nqn.sssert_called_with(
            self.connector['nqn'])

    def test__create_host_if_not_exist_host_does_not_exist(self):
        self.client_mock.query_host_by_nqn.return_value = None
        self.client_mock.create_nvme_host.return_value = self.host_id

        host_id = self.driver._create_host_if_not_exist('fake-nqn',
                                                        self.connector)

        self.assertEqual(host_id, self.host_id)
        self.client_mock.create_nvme_host.assert_called_once_with(
            "hostname-NVMe-TCP", 'fake-nqn')

    def test__attach_volume_to_host_success(self):
        self.client_mock.query_sdc_by_id.return_value = self.host
        self.client_mock.query_volume.return_value = {
            "mappedSdcInfo": []
        }
        self.client_mock.map_volume.return_value = None

        self.driver._attach_volume_to_host(self.volume, self.host_id)

        self.client_mock.query_sdc_by_id.assert_called_once_with(
            self.host_id)
        self.client_mock.query_volume.assert_called_once_with(
            self.volume.provider_id)
        self.client_mock.map_volume.assert_called_once_with(
            self.volume.provider_id, self.host_id)

    def test__attach_volume_to_host_already_attached(self):
        self.client_mock.query_sdc_by_id.return_value = self.host
        self.client_mock.query_volume.return_value = {
            "mappedSdcInfo": [
                {
                    "sdcId": self.host_id
                }
            ]
        }

        self.driver._attach_volume_to_host(self.volume, self.host_id)

        self.client_mock.query_sdc_by_id.assert_called_once_with(
            self.host_id)
        self.client_mock.map_volume.assert_not_called()

    def test_terminate_connection(self):
        self.driver._terminate_connection = mock.MagicMock()

        self.driver.terminate_connection(self.volume, self.connector)

        self.driver._terminate_connection.assert_called_once_with(
            self.volume, self.connector)

    def test__terminate_connection_success(self):
        self.client_mock.query_host_by_nqn.return_value = self.host_id
        self.driver._detach_volume_from_host = mock.MagicMock()
        self.driver._check_volume_unmapped = mock.MagicMock()

        self.driver._terminate_connection(self.volume, self.connector)

        self.client_mock.query_host_by_nqn.assert_called_once_with(
            self.connector["nqn"])
        self.driver._detach_volume_from_host.assert_called_once_with(
            self.volume, self.host_id)
        self.driver._check_volume_unmapped.assert_called_once_with(
            self.host_id, self.volume.provider_id
        )

    def test__terminate_connection_no_connector(self):
        self.driver._detach_volume_from_host = mock.MagicMock()
        self.driver._terminate_connection(self.volume, None)
        self.driver._detach_volume_from_host.assert_called_once_with(
            self.volume
        )

    def test__terminate_connection_no_nqn(self):
        ex = self.assertRaises(exception.InvalidHost,
                               self.driver._terminate_connection,
                               self.volume,
                               {})
        self.assertIn("Host nqn is not configured.", ex.msg)

    def test__terminate_connection_multiattached(self):
        self.driver._is_multiattached_to_host = mock.MagicMock(
            return_value=True)

        self.driver._terminate_connection(self.volume, self.connector)

        self.client_mock.query_host_by_nqn.assert_not_called()
