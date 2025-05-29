# Copyright (c) 2025 Dell Inc. or its subsidiaries.
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

import ddt

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex


class DictToObject:
    def __init__(self, dictionary):
        for key, value in dictionary.items():
            setattr(self, key, value)

    def get(self, key):
        return self.__dict__.get(key)


@ddt.ddt
class TestSDC(powerflex.TestPowerFlexDriver):
    def setUp(self):
        """Setup a test case environment."""

        super(TestSDC, self).setUp()

        self.client_mock = mock.MagicMock()
        self.driver._get_client = mock.MagicMock(return_value=self.client_mock)

        self.connector = {
            "sdc_guid": "028888FA-502A-4FAC-A888-1FA3B256358C",
            "host": "hostname"}
        self.host_id = "13bf228a00010001"
        self.host = {"name": "hostname"}
        self.ctx = (
            context.RequestContext('fake', 'fake', True, auth_token=True))

        self.attachment1 = DictToObject(fake_volume.fake_db_volume_attachment(
            **{
                'attach_status': 'attached',
                'attached_host': self.host['name']
            }
        ))
        self.attachment2 = DictToObject(fake_volume.fake_db_volume_attachment(
            **{
                'attach_status': 'attached',
                'attached_host': self.host['name']
            }
        ))
        self.volume = fake_volume.fake_volume_obj(
            self.ctx, **{'provider_id': '3bd1f78800000019',
                         'size': 8})

    def test_initialize_connection(self):
        self.driver._initialize_connection = mock.MagicMock()

        self.driver.initialize_connection(self.volume, self.connector)

        self.driver._initialize_connection.assert_called_once_with(
            self.volume, self.connector, self.volume.size)

    def test__initialize_connection(self):
        self.client_mock.query_sdc_id_by_guid.return_value = self.host_id
        self.driver._attach_volume_to_host = mock.MagicMock()
        self.driver._check_volume_mapped = mock.MagicMock()

        result = self.driver._initialize_connection(
            self.volume, self.connector, self.volume.size)

        self.assertEqual(result['driver_volume_type'], "scaleio")
        self.driver._attach_volume_to_host.assert_called_with(
            self.volume, self.host_id)
        self.driver._check_volume_mapped.assert_called_with(
            self.host_id, self.volume.provider_id)

    def test__initialize_connection_no_connector(self):
        self.assertRaises(exception.InvalidHost,
                          self.driver._initialize_connection,
                          self.volume,
                          {},
                          self.volume.size)

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

    def test__check_volume_mapped_success(self):
        self.client_mock.query_sdc_volumes.return_value = [
            'vol1', 'vol2', self.volume.id]

        self.driver._check_volume_mapped(self.host_id, self.volume.id)

        self.client_mock.query_sdc_volumes.assert_called_once_with(
            self.host_id)

    def test__check_volume_mapped_fail(self):
        self.client_mock.query_sdc_volumes.return_value = []

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._check_volume_mapped,
                          self.host_id, self.volume.id)

    def test__check_volume_mapped_with_retry(self):
        self.client_mock.query_sdc_volumes.side_effect = [
            [],
            [self.volume.id]
        ]
        self.driver._check_volume_mapped('sdc_id', self.volume.id)
        self.assertEqual(self.client_mock.query_sdc_volumes.call_count, 2)

    def test_terminate_connection(self):
        self.driver._terminate_connection = mock.MagicMock()

        self.driver.terminate_connection(self.volume, self.connector)

        self.driver._terminate_connection.assert_called_once_with(
            self.volume, self.connector)

    def test__terminate_connection_success(self):
        self.client_mock.query_sdc_id_by_guid.return_value = self.host_id
        self.driver._detach_volume_from_host = mock.MagicMock(
            return_valure=None)

        self.driver._terminate_connection(self.volume, self.connector)

        self.client_mock.query_sdc_id_by_guid.assert_called_once_with(
            self.connector["sdc_guid"])
        self.driver._detach_volume_from_host.assert_called_once_with(
            self.volume, self.host_id)

    def test__terminate_connection_no_connector(self):
        self.assertRaises(exception.InvalidHost,
                          self.driver._terminate_connection,
                          self.volume,
                          {})

    def test__terminate_connection_multiattached(self):
        self.driver._is_multiattached_to_host = mock.MagicMock(
            return_valure=False)

        self.driver._terminate_connection(self.volume, self.connector)

        self.client_mock.query_sdc_id_by_guid.assert_not_called()

    def test__is_multiattached_to_host_false(self):

        result = self.driver._is_multiattached_to_host(
            [self.attachment1], self.host['name'])

        self.assertFalse(result)

    def test__is_multiattached_to_host_true(self):

        result = self.driver._is_multiattached_to_host(
            [self.attachment1, self.attachment2],
            self.host['name'])

        self.assertTrue(result)

    @ddt.data("13bf228a00010001", None)
    def test__detach_volume_from_host_detached_1(self, host_id):
        self.client_mock.query_volume.return_value = {
            "mappedSdcInfo": []
        }

        self.driver._detach_volume_from_host(self.volume, host_id)

        self.client_mock.unmap_volume.assert_not_called()

    def test__detach_volume_from_host_detached_2(self):
        self.client_mock.query_volume.return_value = {
            "mappedSdcInfo": [
                {
                    "sdcId": "fake_id"
                }
            ]
        }
        self.client_mock.query_sdc_by_id.return_value = self.host

        self.driver._detach_volume_from_host(self.volume, self.host_id)

        self.client_mock.query_sdc_by_id.assert_called_once_with(self.host_id)
        self.client_mock.unmap_volume.assert_not_called()

    def test__detach_volume_from_host_with_hostid(self):
        self.client_mock.query_volume.return_value = {
            "mappedSdcInfo": [
                {
                    "sdcId": self.host_id
                }
            ]
        }
        self.client_mock.query_sdc_by_id.return_value = self.host

        self.driver._detach_volume_from_host(self.volume, self.host_id)

        self.client_mock.query_sdc_by_id.assert_called_once_with(self.host_id)
        self.client_mock.unmap_volume.assert_called_once_with(
            self.volume.provider_id, self.host_id)

    def test__detach_volume_from_host_without_hostid(self):
        self.client_mock.query_volume.return_value = {
            "mappedSdcInfo": [
                {
                    "sdcId": self.host_id
                }
            ]
        }
        self.client_mock.query_sdc_by_id.return_value = self.host

        self.driver._detach_volume_from_host(self.volume)

        self.client_mock.query_sdc_by_id.assert_not_called()
        self.client_mock.unmap_volume.assert_called_once_with(
            self.volume.provider_id)

    def test__check_volume_unmapped_success(self):
        self.client_mock.query_sdc_volumes.return_value = []

        self.driver._check_volume_unmapped(self.host_id, self.volume.id)

        self.client_mock.query_sdc_volumes.assert_called_once_with(
            self.host_id)

    def test__check_volume_unmapped_fail(self):
        self.client_mock.query_sdc_volumes.return_value = [
            'vol1', 'vol2', self.volume.id]

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._check_volume_unmapped,
                          self.host_id, self.volume.id)

    def test__check_volume_unmapped_with_retry(self):
        self.client_mock.query_sdc_volumes.side_effect = [
            [self.volume.id],
            []
        ]
        self.driver._check_volume_unmapped('sdc_id', self.volume.id)
        self.assertEqual(self.client_mock.query_sdc_volumes.call_count, 2)
