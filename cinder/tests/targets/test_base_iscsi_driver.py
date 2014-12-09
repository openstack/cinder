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
from oslo_config import cfg
from oslo_utils import timeutils

from cinder import context
from cinder import exception
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.targets import fake
from cinder.volume.targets import iscsi


class FakeIncompleteDriver(iscsi.ISCSITarget):
    def null_method():
        pass


class TestBaseISCSITargetDriver(test.TestCase):

    def setUp(self):
        super(TestBaseISCSITargetDriver, self).setUp()
        self.configuration = conf.Configuration(None)
        self.fake_project_id = 'ed2c1fd4-5fc0-11e4-aa15-123b93f75cba'
        self.fake_volume_id = 'ed2c2222-5fc0-11e4-aa15-123b93f75cba'
        self.target = fake.FakeTarget(root_helper=utils.get_root_helper(),
                                      configuration=self.configuration)
        self.testvol =\
            {'project_id': self.fake_project_id,
             'name': 'testvol',
             'size': 1,
             'id': self.fake_volume_id,
             'volume_type_id': None,
             'provider_location': '10.10.7.1:3260 '
                                  'iqn.2010-10.org.openstack:'
                                  'volume-%s 0' % self.fake_volume_id,
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
                           self.fake_volume_id,
             'target_lun': 0,
             'target_portal': '10.10.7.1:3260',
             'volume_id': self.fake_volume_id}

    def test_abc_methods_not_present_fails(self):
        configuration = conf.Configuration(cfg.StrOpt('iscsi_target_prefix',
                                                      default='foo',
                                                      help='you wish'))
        self.assertRaises(TypeError,
                          FakeIncompleteDriver,
                          configuration=configuration)

    def test_get_iscsi_properties(self):
        self.assertEqual(self.expected_iscsi_properties,
                         self.target._get_iscsi_properties(self.testvol))

    def test_get_iscsi_properties_multiple_targets(self):
        testvol = self.testvol.copy()
        expected_iscsi_properties = self.expected_iscsi_properties.copy()
        iqn = expected_iscsi_properties['target_iqn']
        testvol.update(
            {'provider_location': '10.10.7.1:3260;10.10.8.1:3260 '
                                  'iqn.2010-10.org.openstack:'
                                  'volume-%s 0' % self.fake_volume_id})
        expected_iscsi_properties.update(
            {'target_portals': ['10.10.7.1:3260', '10.10.8.1:3260'],
             'target_iqns': [iqn, iqn],
             'target_luns': [0, 0]})
        self.assertEqual(expected_iscsi_properties,
                         self.target._get_iscsi_properties(testvol))

    def test_build_iscsi_auth_string(self):
        auth_string = 'chap chap-user chap-password'
        self.assertEqual(auth_string,
                         self.target._iscsi_authentication('chap',
                                                           'chap-user',
                                                           'chap-password'))

    def test_do_iscsi_discovery(self):
        target_string = '127.0.0.1:3260,1 '\
                        'iqn.2010-10.org.openstack:'\
                        'volume-%s' % self.testvol['id']

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
                         self.target._do_iscsi_discovery(self.testvol))

    def test_remove_export(self):

        with mock.patch.object(self.target, '_get_target_and_lun') as \
                mock_get_target,\
                mock.patch.object(self.target, 'show_target'),\
                mock.patch.object(self.target, 'remove_iscsi_target') as \
                mock_remove_target:

            mock_get_target.return_value = (0, 1)
            iscsi_target, lun = mock_get_target.return_value
            ctxt = context.get_admin_context()
            self.target.remove_export(ctxt, self.testvol)
            mock_remove_target.assert_called_once_with(
                iscsi_target,
                lun,
                'ed2c2222-5fc0-11e4-aa15-123b93f75cba',
                'testvol')

    def test_remove_export_notfound(self):

        with mock.patch.object(self.target, '_get_target_and_lun') as \
                mock_get_target,\
                mock.patch.object(self.target, 'show_target'),\
                mock.patch.object(self.target, 'remove_iscsi_target'):

            mock_get_target.side_effect = exception.NotFound
            ctxt = context.get_admin_context()
            self.assertEqual(None, self.target.remove_export(ctxt,
                                                             self.testvol))

    def test_remove_export_show_error(self):

        with mock.patch.object(self.target, '_get_target_and_lun') as \
                mock_get_target,\
                mock.patch.object(self.target, 'show_target') as mshow,\
                mock.patch.object(self.target, 'remove_iscsi_target'):

            mock_get_target.return_value = (0, 1)
            iscsi_target, lun = mock_get_target.return_value
            mshow.side_effect = Exception
            ctxt = context.get_admin_context()
            self.assertEqual(None, self.target.remove_export(ctxt,
                                                             self.testvol))

    def test_initialize_connection(self):
        expected = {'driver_volume_type': 'iscsi',
                    'data': self.expected_iscsi_properties}
        self.assertEqual(expected,
                         self.target.initialize_connection(self.testvol, {}))

    def test_validate_connector(self):
        bad_connector = {'no_initiator': 'nada'}
        self.assertRaises(exception.InvalidConnectorException,
                          self.target.validate_connector,
                          bad_connector)

        connector = {'initiator': 'fake_init'}
        self.assertTrue(self.target.validate_connector,
                        connector)

    def test_show_target_error(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.target.show_target,
                          0, None)

        with mock.patch.object(self.target, '_get_target') as mock_get_target:
            mock_get_target.side_effect = exception.NotFound()
            self.assertRaises(exception.NotFound,
                              self.target.show_target, 0,
                              self.expected_iscsi_properties['target_iqn'])

    def test_iscsi_location(self):
        location = self.target._iscsi_location('portal', 1, 'target', 2)
        self.assertEqual('portal:3260,1 target 2', location)

        location = self.target._iscsi_location('portal', 1, 'target', 2,
                                               ['portal2'])
        self.assertEqual('portal:3260;portal2:3260,1 target 2', location)
