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

from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume.targets import lio
from cinder.volume.targets import tgt


class TestIserTgtDriver(tf.TargetDriverFixture):
    """Unit tests for the iSER TGT flow"""

    def setUp(self):
        super(TestIserTgtDriver, self).setUp()
        self.configuration.iscsi_protocol = 'iser'
        self.target = tgt.TgtAdm(root_helper=utils.get_root_helper(),
                                 configuration=self.configuration)

    def test_iscsi_protocol(self):
        self.assertEqual('iser', self.target.iscsi_protocol)

    @mock.patch.object(tgt.TgtAdm, '_get_iscsi_properties')
    def test_initialize_connection(self, mock_get_iscsi):

        connector = {'initiator': 'fake_init'}

        mock_get_iscsi.return_value = {}
        expected_return = {'driver_volume_type': 'iser',
                           'data': {}}
        self.assertEqual(expected_return,
                         self.target.initialize_connection(self.testvol,
                                                           connector))


class TestIserLioAdmDriver(tf.TargetDriverFixture):
    """Unit tests for the iSER LIO flow"""
    def setUp(self):
        super(TestIserLioAdmDriver, self).setUp()
        self.configuration.iscsi_protocol = 'iser'
        with mock.patch.object(lio.LioAdm, '_verify_rtstool'):
            self.target = lio.LioAdm(root_helper=utils.get_root_helper(),
                                     configuration=self.configuration)
        self.target.db = mock.MagicMock(
            volume_get=lambda x, y: {'provider_auth': 'IncomingUser foo bar'})

    def test_iscsi_protocol(self):
        self.assertEqual('iser', self.target.iscsi_protocol)

    @mock.patch('cinder.utils.execute')
    @mock.patch.object(lio.LioAdm, '_get_iscsi_properties')
    def test_initialize_connection(self, mock_get_iscsi, mock_execute):

        connector = {'initiator': 'fake_init'}

        mock_get_iscsi.return_value = {}
        ret = self.target.initialize_connection(self.testvol, connector)
        driver_volume_type = ret['driver_volume_type']
        self.assertEqual('iser', driver_volume_type)
