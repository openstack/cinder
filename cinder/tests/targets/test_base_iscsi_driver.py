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

from oslo_config import cfg
from oslo_utils import timeutils

from cinder import exception
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.targets import iscsi


class FakeDriver(iscsi.ISCSITarget):
    def __init__(self, *args, **kwargs):
        super(FakeDriver, self).__init__(*args, **kwargs)

    def create_export(self, context, vref):
        pass

    def ensure_export(self, context, vref, vol_path):
        pass

    def remove_export(self, context, vref):
        pass

    def terminate_connection(self, vref, **kwargs):
        pass


class FakeIncompleteDriver(iscsi.ISCSITarget):
    def null_method():
        pass


class TestBaseISCSITargetDriver(test.TestCase):

    def setUp(self):
        super(TestBaseISCSITargetDriver, self).setUp()
        self.configuration = conf.Configuration(None)
        self.fake_id_1 = 'ed2c1fd4-5fc0-11e4-aa15-123b93f75cba'
        self.fake_id_2 = 'ed2c2222-5fc0-11e4-aa15-123b93f75cba'
        self.target = FakeDriver(root_helper=utils.get_root_helper(),
                                 configuration=self.configuration)
        self.testvol_1 =\
            {'project_id': self.fake_id_1,
             'name': 'testvol',
             'size': 1,
             'id': self.fake_id_2,
             'volume_type_id': None,
             'provider_location': '10.10.7.1:3260 '
                                  'iqn.2010-10.org.openstack:'
                                  'volume-%s 0' % self.fake_id_2,
             'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                              'c76370d66b 2FE0CQ8J196R',
             'provider_geometry': '512 512',
             'created_at': timeutils.utcnow(),
             'host': 'fake_host@lvm#lvm'}

        self.expected_iscsi_properties = \
            {'auth_method': 'CHAP',
             'auth_password': '2FE0CQ8J196R',
             'auth_username': 'stack-1-a60e2611875f40199931f2c76370d66b',
             'encrypted': False,
             'logical_block_size': '512',
             'physical_block_size': '512',
             'target_discovered': False,
             'target_iqn': 'iqn.2010-10.org.openstack:volume-%s' %
                           self.fake_id_2,
             'target_lun': 0,
             'target_portal': '10.10.7.1:3260',
             'volume_id': self.fake_id_2}

    def test_abc_methods_not_present_fails(self):
        configuration = conf.Configuration(cfg.StrOpt('iscsi_target_prefix',
                                                      default='foo',
                                                      help='you wish'))
        self.assertRaises(TypeError,
                          FakeIncompleteDriver,
                          configuration=configuration)

    def test_get_iscsi_properties(self):
        self.assertEqual(self.expected_iscsi_properties,
                         self.target._get_iscsi_properties(self.testvol_1))

    def test_build_iscsi_auth_string(self):
        auth_string = 'chap chap-user chap-password'
        self.assertEqual(auth_string,
                         self.target._iscsi_authentication('chap',
                                                           'chap-user',
                                                           'chap-password'))

    def test_do_iscsi_discovery(self):
        target_string = '127.0.0.1:3260,1 '\
                        'iqn.2010-10.org.openstack:'\
                        'volume-%s' % self.testvol_1['id']

        def _fake_execute(*args, **kwargs):
            return target_string, None

        def _fake_safe_get(val):
            return '127.0.0.1'

        self.stubs.Set(self.configuration,
                       'safe_get',
                       _fake_safe_get)

        self.stubs.Set(utils,
                       'execute',
                       _fake_execute)

        self.assertEqual(target_string,
                         self.target._do_iscsi_discovery(self.testvol_1))

    def test_initialize_connection(self):
        expected = {'driver_volume_type': 'iscsi',
                    'data': self.expected_iscsi_properties}
        self.assertEqual(expected,
                         self.target.initialize_connection(self.testvol_1, {}))

    def test_validate_connector(self):
        bad_connector = {'no_initiator': 'nada'}
        self.assertRaises(exception.InvalidConnectorException,
                          self.target.validate_connector,
                          bad_connector)

        connector = {'initiator': 'fake_init'}
        self.assertTrue(self.target.validate_connector,
                        connector)
