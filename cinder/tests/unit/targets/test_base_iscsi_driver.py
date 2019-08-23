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

from cinder import context
from cinder import exception
from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.targets import fake
from cinder.volume.targets import iscsi


class FakeIncompleteDriver(iscsi.ISCSITarget):
    def null_method():
        pass


class TestBaseISCSITargetDriver(tf.TargetDriverFixture):

    def setUp(self):
        super(TestBaseISCSITargetDriver, self).setUp()
        self.target = fake.FakeTarget(root_helper=utils.get_root_helper(),
                                      configuration=self.configuration)
        self.target.db = mock.MagicMock(
            volume_get=mock.MagicMock(return_value={'provider_auth':
                                                    'CHAP otzL 234Z'}))

    def test_abc_methods_not_present_fails(self):
        configuration = conf.Configuration(cfg.StrOpt('target_prefix',
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
        with mock.patch.object(self.configuration,
                               'safe_get', return_value='127.0.0.1'),\
                mock.patch('cinder.utils.execute',
                           return_value=(self.target_string, '')):
            self.assertEqual(self.target_string,
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
            self.assertIsNone(self.target.remove_export(ctxt,
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
            self.assertIsNone(self.target.remove_export(ctxt,
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
        self.assertTrue(bool(self.target.validate_connector),
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

    def test_iscsi_location_IPv6(self):
        ip = 'fd00:fd00:fd00:3000::12'
        ip2 = 'fd00:fd00:fd00:3000::13'

        location = self.target._iscsi_location(ip, 1, 'target', 2)
        self.assertEqual('[%s]:3260,1 target 2' % ip, location)

        location = self.target._iscsi_location(ip, 1, 'target', 2, [ip2])
        self.assertEqual('[%s]:3260;[%s]:3260,1 target 2' % (ip, ip2),
                         location)

        # Mix of IPv6 (already with square brackets) and IPv4
        ip = '[' + ip + ']'
        location = self.target._iscsi_location(ip, 1, 'target', 2,
                                               ['192.168.1.1'])
        self.assertEqual(ip + ':3260;192.168.1.1:3260,1 target 2', location)

    def test_get_target_chap_auth(self):
        ctxt = context.get_admin_context()
        self.assertEqual(('otzL', '234Z'),
                         self.target._get_target_chap_auth(ctxt,
                                                           self.testvol))
        self.target.db.volume_get.assert_called_once_with(
            ctxt, self.testvol['id'])
