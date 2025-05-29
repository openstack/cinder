# Copyright (c) 2015 EMC Corporation.
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

from cinder import context
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex
from cinder.tests.unit.volume.drivers.dell_emc.powerflex import mocks


class TestInitializeConnection(powerflex.TestPowerFlexDriver):
    def setUp(self):
        """Setup a test case environment."""

        super(TestInitializeConnection, self).setUp()
        self.connector = {'sdc_guid': 'fake_guid'}
        self.ctx = (
            context.RequestContext('fake', 'fake', True, auth_token=True))
        self.volume = fake_volume.fake_volume_obj(
            self.ctx, **{'provider_id': fake.PROVIDER_ID})
        self.sdc = {
            "id": "sdc1",
        }
        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Sdc/instances':
                [{'id': "sdc1", 'sdcGuid': 'fake_guid'}],
                'instances/Volume::{}/action/setMappedSdcLimits'.format(
                    self.volume.provider_id
                ): mocks.MockHTTPSResponse({}, 200),
            },
        }

    def test_only_qos(self):
        qos = {'maxIOPS': 1000, 'maxBWS': 2048}
        extraspecs = {}
        self._initialize_connection(qos, extraspecs)['data']
        self.driver.primary_client.set_sdc_limits.assert_called_once_with(
            self.volume.provider_id, self.sdc["id"], '2048', '1000')

    def test_no_qos(self):
        qos = {}
        extraspecs = {}
        self._initialize_connection(qos, extraspecs)['data']
        self.driver.primary_client.set_sdc_limits.assert_not_called

    def test_qos_scaling_and_max(self):
        qos = {'maxIOPS': 100, 'maxBWS': 2048, 'maxIOPSperGB': 10,
               'maxBWSperGB': 128}
        extraspecs = {}
        self.volume.size = 8
        self._initialize_connection(qos, extraspecs)['data']
        self.driver.primary_client.set_sdc_limits.assert_called_once_with(
            self.volume.provider_id, self.sdc["id"], '1024', '80')

        self.volume.size = 24
        self._initialize_connection(qos, extraspecs)['data']
        self.driver.primary_client.set_sdc_limits.assert_called_once_with(
            self.volume.provider_id, self.sdc["id"], '2048', '100')

    def test_qos_scaling_no_max(self):
        qos = {'maxIOPSperGB': 10, 'maxBWSperGB': 128}
        extraspecs = {}
        self.volume.size = 8
        self._initialize_connection(qos, extraspecs)['data']
        self.driver.primary_client.set_sdc_limits.assert_called_once_with(
            self.volume.provider_id, self.sdc["id"], '1024', '80')

    def test_qos_round_up(self):
        qos = {'maxBWS': 2000, 'maxBWSperGB': 100}
        extraspecs = {}
        self.volume.size = 8
        self._initialize_connection(qos, extraspecs)['data']
        self.driver.primary_client.set_sdc_limits.assert_called_once_with(
            self.volume.provider_id, self.sdc["id"], '1024', None)

        self.volume.size = 24
        self._initialize_connection(qos, extraspecs)['data']
        self.driver.primary_client.set_sdc_limits.assert_called_once_with(
            self.volume.provider_id, self.sdc["id"], '2048', None)

    def test_vol_id(self):
        extraspecs = qos = {}
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertEqual(fake.PROVIDER_ID,
                         connection_properties['scaleIO_volume_id'])

    def _initialize_connection(self, qos, extraspecs):
        self.driver._get_volumetype_qos = mock.MagicMock()
        self.driver._get_volumetype_qos.return_value = qos
        self.driver._get_volumetype_extraspecs = mock.MagicMock()
        self.driver._get_volumetype_extraspecs.return_value = extraspecs
        self.driver._attach_volume_to_host = mock.MagicMock(
            return_value=None
        )
        self.driver._check_volume_mapped = mock.MagicMock(
            return_value=None
        )
        self.driver.primary_client.set_sdc_limits = mock.MagicMock()
        res = self.driver.initialize_connection(self.volume, self.connector)
        self.driver._get_volumetype_extraspecs.assert_called_once_with(
            self.volume)
        self.driver._attach_volume_to_host.assert_called_once_with(
            self.volume, self.sdc['id'])
        self.driver._check_volume_mapped.assert_called_once_with(
            self.sdc['id'], self.volume.provider_id)
        return res
