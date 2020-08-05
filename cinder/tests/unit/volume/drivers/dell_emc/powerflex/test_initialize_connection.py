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


class TestInitializeConnection(powerflex.TestPowerFlexDriver):
    def setUp(self):
        """Setup a test case environment."""

        super(TestInitializeConnection, self).setUp()
        self.connector = {}
        self.ctx = (
            context.RequestContext('fake', 'fake', True, auth_token=True))
        self.volume = fake_volume.fake_volume_obj(
            self.ctx, **{'provider_id': fake.PROVIDER_ID})

    def test_only_qos(self):
        qos = {'maxIOPS': 1000, 'maxBWS': 2048}
        extraspecs = {}
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertEqual(1000, int(connection_properties['iopsLimit']))
        self.assertEqual(2048, int(connection_properties['bandwidthLimit']))

    def test_no_qos(self):
        qos = {}
        extraspecs = {}
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertIsNone(connection_properties['iopsLimit'])
        self.assertIsNone(connection_properties['bandwidthLimit'])

    def test_qos_scaling_and_max(self):
        qos = {'maxIOPS': 100, 'maxBWS': 2048, 'maxIOPSperGB': 10,
               'maxBWSperGB': 128}
        extraspecs = {}
        self.volume.size = 8
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertEqual(80, int(connection_properties['iopsLimit']))
        self.assertEqual(1024, int(connection_properties['bandwidthLimit']))

        self.volume.size = 24
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertEqual(100, int(connection_properties['iopsLimit']))
        self.assertEqual(2048, int(connection_properties['bandwidthLimit']))

    def test_qos_scaling_no_max(self):
        qos = {'maxIOPSperGB': 10, 'maxBWSperGB': 128}
        extraspecs = {}
        self.volume.size = 8
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertEqual(80, int(connection_properties['iopsLimit']))
        self.assertEqual(1024, int(connection_properties['bandwidthLimit']))

    def test_qos_round_up(self):
        qos = {'maxBWS': 2000, 'maxBWSperGB': 100}
        extraspecs = {}
        self.volume.size = 8
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertEqual(1024, int(connection_properties['bandwidthLimit']))

        self.volume.size = 24
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertEqual(2048, int(connection_properties['bandwidthLimit']))

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
        return self.driver.initialize_connection(self.volume, self.connector)
