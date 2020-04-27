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

import json
import socket
from unittest import mock

import ddt
from oslo_config import cfg

from cinder import exception
from cinder.tests.unit import test
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
                          group=self.backend)
        CONF.set_override('netapp_transport_type', 'https',
                          group=self.backend)
        CONF.set_override('netapp_login', 'fake_user',
                          group=self.backend)
        CONF.set_override('netapp_password', 'fake_password',
                          group=self.backend)
        CONF.set_override('netapp_server_hostname', 'fake_hostname',
                          group=self.backend)
        CONF.set_override('netapp_server_port', 8866,
                          group=self.backend)
        CONF.set_override('netapp_api_trace_pattern', "fake_regex",
                          group=self.backend)

    def test_get_backend_configuration(self):
        self.mock_object(utils, 'CONF')
        CONF.set_override('netapp_vserver', 'fake_vserver',
                          group=self.backend)
        utils.CONF.list_all_sections.return_value = [self.backend]

        config = utils.get_backend_configuration(self.backend)

        self.assertEqual('fake_vserver', config.netapp_vserver)

    def test_get_backend_configuration_different_backend_name(self):
        self.mock_object(utils, 'CONF')
        CONF.set_override('netapp_vserver', 'fake_vserver',
                          group=self.backend)
        CONF.set_override('volume_backend_name', 'fake_backend_name',
                          group=self.backend)
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
                         return_value=self.config)

        utils.get_client_for_backend(self.backend)

        self.mock_cmode_client.assert_called_once_with(
            hostname='fake_hostname', password='fake_password',
            username='fake_user', transport_type='https', port=8866,
            trace=mock.ANY, vserver=None, api_trace_pattern="fake_regex")

    def test_get_client_for_backend_with_vserver(self):
        self.mock_object(utils, 'get_backend_configuration',
                         return_value=self.config)

        CONF.set_override('netapp_vserver', 'fake_vserver',
                          group=self.backend)

        utils.get_client_for_backend(self.backend)

        self.mock_cmode_client.assert_called_once_with(
            hostname='fake_hostname', password='fake_password',
            username='fake_user', transport_type='https', port=8866,
            trace=mock.ANY, vserver='fake_vserver',
            api_trace_pattern="fake_regex")


@ddt.ddt
class NetAppDataOntapUtilsTestCase(test.TestCase):

    def test_build_ems_log_message_0(self):

        self.mock_object(
            socket, 'gethostname', return_value='fake_hostname')

        result = utils.build_ems_log_message_0(
            'fake_driver_name', 'fake_app_version')

        expected = {
            'computer-name': 'fake_hostname',
            'event-source': 'Cinder driver fake_driver_name',
            'app-version': 'fake_app_version',
            'category': 'provisioning',
            'log-level': '5',
            'auto-support': 'false',
            'event-id': '0',
            'event-description': 'OpenStack Cinder connected to cluster node',
        }
        self.assertEqual(expected, result)

    def test_build_ems_log_message_1(self):

        self.mock_object(
            socket, 'gethostname', return_value='fake_hostname')
        aggregate_pools = ['aggr1', 'aggr2']
        flexvol_pools = ['vol1', 'vol2']

        result = utils.build_ems_log_message_1(
            'fake_driver_name', 'fake_app_version', 'fake_vserver',
            flexvol_pools, aggregate_pools)

        pool_info = {
            'pools': {
                'vserver': 'fake_vserver',
                'aggregates': aggregate_pools,
                'flexvols': flexvol_pools,
            },
        }
        self.assertDictEqual(pool_info,
                             json.loads(result['event-description']))

        result['event-description'] = ''
        expected = {
            'computer-name': 'fake_hostname',
            'event-source': 'Cinder driver fake_driver_name',
            'app-version': 'fake_app_version',
            'category': 'provisioning',
            'log-level': '5',
            'auto-support': 'false',
            'event-id': '1',
            'event-description': '',
        }
        self.assertEqual(expected, result)
