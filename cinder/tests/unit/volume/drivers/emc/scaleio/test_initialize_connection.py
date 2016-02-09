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
import mock

from cinder import context
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.emc import scaleio


class TestInitializeConnection(scaleio.TestScaleIODriver):
    def setUp(self):
        """Setup a test case environment."""

        super(TestInitializeConnection, self).setUp()
        self.connector = {}
        self.ctx = (
            context.RequestContext('fake', 'fake', True, auth_token=True))
        self.volume = fake_volume.fake_volume_obj(self.ctx)

    def test_only_qos(self):
        qos = {'maxIOPS': 1000, 'maxBWS': 3000}
        extraspecs = {}
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertEqual(1000, connection_properties['iopsLimit'])
        self.assertEqual(3000, connection_properties['bandwidthLimit'])

    def test_no_qos(self):
        qos = {}
        extraspecs = {}
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertIsNone(connection_properties['iopsLimit'])
        self.assertIsNone(connection_properties['bandwidthLimit'])

    def test_only_extraspecs(self):
        qos = {}
        extraspecs = {'sio:iops_limit': 2000, 'sio:bandwidth_limit': 4000}
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertEqual(2000, connection_properties['iopsLimit'])
        self.assertEqual(4000, connection_properties['bandwidthLimit'])

    def test_qos_and_extraspecs(self):
        qos = {'maxIOPS': 1000, 'maxBWS': 3000}
        extraspecs = {'sio:iops_limit': 2000, 'sio:bandwidth_limit': 4000}
        connection_properties = (
            self._initialize_connection(qos, extraspecs)['data'])
        self.assertEqual(1000, connection_properties['iopsLimit'])
        self.assertEqual(3000, connection_properties['bandwidthLimit'])

    def _initialize_connection(self, qos, extraspecs):
        self.driver._get_volumetype_qos = mock.MagicMock()
        self.driver._get_volumetype_qos.return_value = qos
        self.driver._get_volumetype_extraspecs = mock.MagicMock()
        self.driver._get_volumetype_extraspecs.return_value = extraspecs
        return self.driver.initialize_connection(self.volume, self.connector)
