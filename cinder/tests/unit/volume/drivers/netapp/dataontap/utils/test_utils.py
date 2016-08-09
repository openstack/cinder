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


import ddt
import mock
from oslo_config import cfg

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.netapp.dataontap.utils import fakes
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap.utils import utils

CONF = cfg.CONF


@ddt.ddt
class NetAppCDOTDataMotionTestCase(test.TestCase):

    def setUp(self):
        super(NetAppCDOTDataMotionTestCase, self).setUp()
        self.backend = 'backend1'
        self.mock_cmode_client = self.mock_object(client_cmode, 'Client')
        self.config = fakes.get_fake_cmode_config(self.backend)
        CONF.set_override('volume_backend_name', self.backend,
                          group=self.backend, enforce_type=True)
        CONF.set_override('netapp_transport_type', 'https',
                          group=self.backend, enforce_type=True)
        CONF.set_override('netapp_login', 'fake_user',
                          group=self.backend, enforce_type=True)
        CONF.set_override('netapp_password', 'fake_password',
                          group=self.backend, enforce_type=True)
        CONF.set_override('netapp_server_hostname', 'fake_hostname',
                          group=self.backend, enforce_type=True)
        CONF.set_override('netapp_server_port', 8866,
                          group=self.backend, enforce_type=True)

    def test_get_backend_configuration(self):
        self.mock_object(utils, 'CONF')
        CONF.set_override('netapp_vserver', 'fake_vserver',
                          group=self.backend, enforce_type=True)
        utils.CONF.list_all_sections.return_value = [self.backend]

        config = utils.get_backend_configuration(self.backend)

        self.assertEqual('fake_vserver', config.netapp_vserver)

    def test_get_backend_configuration_different_backend_name(self):
        self.mock_object(utils, 'CONF')
        CONF.set_override('netapp_vserver', 'fake_vserver',
                          group=self.backend, enforce_type=True)
        CONF.set_override('volume_backend_name', 'fake_backend_name',
                          group=self.backend, enforce_type=True)
        utils.CONF.list_all_sections.return_value = [self.backend]

        config = utils.get_backend_configuration(self.backend)

        self.assertEqual('fake_vserver', config.netapp_vserver)
        self.assertEqual('fake_backend_name', config.volume_backend_name)

    @ddt.data([], ['fake_backend1', 'fake_backend2'])
    def test_get_backend_configuration_not_configured(self, conf_sections):
        self.mock_object(utils, 'CONF')
        utils.CONF.list_all_sections.return_value = conf_sections

        self.assertRaises(exception.ConfigNotFound,
                          utils.get_backend_configuration,
                          self.backend)

    def test_get_client_for_backend(self):
        self.mock_object(utils, 'get_backend_configuration',
                         mock.Mock(return_value=self.config))

        utils.get_client_for_backend(self.backend)

        self.mock_cmode_client.assert_called_once_with(
            hostname='fake_hostname', password='fake_password',
            username='fake_user', transport_type='https', port=8866,
            trace=mock.ANY, vserver=None)

    def test_get_client_for_backend_with_vserver(self):
        self.mock_object(utils, 'get_backend_configuration',
                         mock.Mock(return_value=self.config))

        CONF.set_override('netapp_vserver', 'fake_vserver',
                          group=self.backend, enforce_type=True)

        utils.get_client_for_backend(self.backend)

        self.mock_cmode_client.assert_called_once_with(
            hostname='fake_hostname', password='fake_password',
            username='fake_user', transport_type='https', port=8866,
            trace=mock.ANY, vserver='fake_vserver')
