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
import tempfile

import mock
from oslo_utils import timeutils

from cinder import context
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.targets import scst
from cinder.volume import utils as vutils


class TestSCSTAdmDriver(test.TestCase):

    def setUp(self):
        super(TestSCSTAdmDriver, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.iscsi_ip_address = '10.9.8.7'
        self.fake_volumes_dir = tempfile.mkdtemp()
        self.fake_id_1 = 'ed2c1fd4-5fc0-11e4-aa15-123b93f75cba'
        self.fake_id_2 = 'ed2c2222-5fc0-11e4-aa15-123b93f75cba'
        self.fake_id_3 = 'ed2c3333-5fc0-11e4-aa15-123b93f75cba'
        self.fake_id_4 = 'ed2c4444-5fc0-11e4-aa15-123b93f75cba'
        self.stubs.Set(self.configuration, 'safe_get', self.fake_safe_get)

        self.target = scst.SCSTAdm(root_helper=utils.get_root_helper(),
                                   configuration=self.configuration)
        self.testvol_1 =\
            {'project_id': self.fake_id_1,
             'name': 'testvol',
             'size': 1,
             'id': self.fake_id_2,
             'volume_type_id': None,
             'provider_location': '10.9.8.7:3260 '
                                  'iqn.2010-10.org.openstack:'
                                  'volume-%s 1' % self.fake_id_2,
             'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                              'c76370d66b 2FE0CQ8J196R',
             'provider_geometry': '512 512',
             'created_at': timeutils.utcnow(),
             'host': 'fake_host@lvm#lvm'}
        self.testvol_2 =\
            {'project_id': self.fake_id_3,
             'name': 'testvol2',
             'size': 1,
             'id': self.fake_id_4,
             'volume_type_id': None,
             'provider_location': '10.9.8.7:3260 '
                                  'iqn.2010-10.org.openstack:'
                                  'volume-%s 2' % self.fake_id_4,
             'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                              'c76370d66b 2FE0CQ8J196R',
             'provider_geometry': '512 512',
             'created_at': timeutils.utcnow(),
             'host': 'fake_host@lvm#lvm'}

        self.fake_iscsi_scan = \
            ('Collecting current configuration: done.\n'
             'Driver Target\n'
             '----------------------------------------------\n'
             'iscsi iqn.2010-10.org.openstack:'
             'volume-ed2c2222-5fc0-11e4-aa15-123b93f75cba\n'
             'All done.\n')

        self.fake_iscsi_attribute_scan = \
            ('Collecting current configuration: done.\n'
             'Attribute      Value     Writable      KEY\n'
             '------------------------------------------\n'
             'rel_tgt_id     1         Yes           Yes\n'
             'Dynamic attributes available\n'
             '----------------------------\n'
             'IncomingUser\n'
             'OutgoingUser\n'
             'allowed_portal\n'
             'LUN CREATE attributes available\n'
             '-------------------------------\n'
             'read_only\n'
             'All done.\n')
        self.fake_list_group = \
            ('org.openstack:volume-vedams\n'
             'Collecting current configuration: done.\n'
             'Driver: iscsi\n'
             'Target: iqn.2010-10.org.openstack:volume-vedams\n'
             'Driver/target \'iscsi/iqn.2010-10.org.openstack:volume-vedams\''
             'has no associated LUNs.\n'
             'Group: iqn.1993-08.org.debian:01:626bf14ebdc\n'
             'Assigned LUNs:\n'
             'LUN  Device\n'
             '------------------\n'
             '1    1b67387810256\n'
             '2    2a0f1cc9cd595\n'
             'Assigned Initiators:\n'
             'Initiator\n'
             '-------------------------------------\n'
             'iqn.1993-08.org.debian:01:626bf14ebdc\n'
             'All done.\n')

        self.target.db = mock.MagicMock(
            volume_get=lambda x, y: {'provider_auth': 'IncomingUser foo bar'})

    def fake_safe_get(self, value):
        if value == 'volumes_dir':
            return self.fake_volumes_dir

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(scst.SCSTAdm, '_target_attribute')
    @mock.patch.object(scst.SCSTAdm, 'scst_execute')
    def test_get_target(self, mock_execute,
                        mock_target_attribute,
                        mock_scst_execute):
        mock_target_attribute.return_value = 1
        mock_execute.return_value = (self.fake_iscsi_scan, None)
        expected = 1
        self.assertEqual(expected, self.target._get_target(
            'iqn.2010-10.org.openstack:'
            'volume-ed2c2222-5fc0-11e4-aa15-123b93f75cba'))

    @mock.patch.object(utils, 'execute')
    def test_target_attribute(self, mock_execute):
        mock_execute.return_value = (self.fake_iscsi_attribute_scan, None)
        self.assertEqual(str(1), self.target._target_attribute(
            'iqn.2010-10.org.openstack:'
            'volume-ed2c2222-5fc0-11e4-aa15-123b93f75cba'))

    def test_single_lun_get_target_and_lun(self):
        ctxt = context.get_admin_context()
        self.assertEqual((0, 1), self.target._get_target_and_lun(
            ctxt, self.testvol_1))

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(scst.SCSTAdm, '_get_group')
    @mock.patch.object(scst.SCSTAdm, 'scst_execute')
    def test_multi_lun_get_target_and_lun(self, mock_execute, mock_get_group,
                                          mock_scst_execute):
        mock_execute.return_value = (self.fake_list_group, None)
        mock_get_group.return_value = self.fake_list_group

        self.stubs.Set(self.target,
                       'target_name',
                       'iqn.2010-10.org.openstack:volume-vedams')
        ctxt = context.get_admin_context()

        self.assertEqual((0, 3), self.target._get_target_and_lun(
            ctxt, self.testvol_1))

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(scst.SCSTAdm, '_get_target')
    @mock.patch.object(scst.SCSTAdm, 'scst_execute')
    def test_create_iscsi_target(self, mock_execute, mock_get_target,
                                 mock_scst_execute):
        mock_execute.return_value = (None, None)
        mock_get_target.return_value = 1

        self.assertEqual(1,
                         self.target.create_iscsi_target(
                             'iqn.2010-10.org.openstack:'
                             'volume-ed2c2222-5fc0-11e4-aa15-123b93f75cba',
                             'vol1',
                             0, 1, self.fake_volumes_dir))

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(scst.SCSTAdm, '_get_target')
    @mock.patch.object(scst.SCSTAdm, 'scst_execute')
    def test_create_export(self, mock_execute,
                           mock_get_target,
                           mock_scst_execute):
        mock_execute.return_value = (None, None)
        mock_scst_execute.return_value = (None, None)
        mock_get_target.return_value = 1

        def _fake_get_target_and_lun(*args, **kwargs):
            return 0, 1

        def _fake_iscsi_location(*args, **kwargs):
            return '10.9.8.7:3260,1 iqn.2010-10.org.openstack:' \
                   'volume-ed2c2222-5fc0-11e4-aa15-123b93f75cba 1'

        def _fake_get_target_chap_auth(*args, **kwargs):
            return ('QZJbisGmn9AL954FNF4D', 'P68eE7u9eFqDGexd28DQ')

        self.stubs.Set(self.target,
                       '_get_target_and_lun',
                       _fake_get_target_and_lun)

        self.stubs.Set(self.target,
                       'initiator_iqn',
                       'iqn.1993-08.org.debian:01:626bf14ebdc')
        self.stubs.Set(self.target,
                       '_iscsi_location',
                       _fake_iscsi_location)
        self.stubs.Set(self.target,
                       '_get_target_chap_auth',
                       _fake_get_target_chap_auth)
        self.stubs.Set(self.target,
                       'target_driver',
                       'iscsi')
        self.stubs.Set(self.target,
                       'initiator_iqn',
                       'iqn.1993-08.org.debian:01:626bf14ebdc')
        self.stubs.Set(vutils,
                       'generate_username',
                       lambda: 'QZJbisGmn9AL954FNF4D')
        self.stubs.Set(vutils,
                       'generate_password',
                       lambda: 'P68eE7u9eFqDGexd28DQ')

        ctxt = context.get_admin_context()
        expected_result = {'location': '10.9.8.7:3260,1 '
                           'iqn.2010-10.org.openstack:'
                           'volume-ed2c2222-5fc0-11e4-aa15-123b93f75cba 1',
                           'auth': 'CHAP '
                           'QZJbisGmn9AL954FNF4D P68eE7u9eFqDGexd28DQ'}
        self.assertEqual(expected_result,
                         self.target.create_export(ctxt,
                                                   self.testvol_1,
                                                   self.fake_volumes_dir))

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(scst.SCSTAdm, '_get_target')
    @mock.patch.object(scst.SCSTAdm, 'scst_execute')
    def test_ensure_export(self, mock_execute,
                           mock_get_target,
                           mock_scst_execute):
        mock_execute.return_value = (None, None)
        mock_scst_execute.return_value = (None, None)
        mock_get_target.return_value = 1
        ctxt = context.get_admin_context()

        def _fake_get_target_and_lun(*args, **kwargs):
            return 0, 1

        def _fake_get_target_chap_auth(*args, **kwargs):
            return ('QZJbisGmn9AL954FNF4D', 'P68eE7u9eFqDGexd28DQ')

        self.stubs.Set(self.target,
                       '_get_target_chap_auth',
                       _fake_get_target_chap_auth)
        self.stubs.Set(self.target,
                       '_get_target_and_lun',
                       _fake_get_target_and_lun)

        with mock.patch.object(self.target, 'create_iscsi_target'):
            self.target.ensure_export(ctxt,
                                      self.testvol_1,
                                      self.fake_volumes_dir)
            self.target.create_iscsi_target.assert_called_once_with(
                'iqn.2010-10.org.openstack:testvol',
                'ed2c2222-5fc0-11e4-aa15-123b93f75cba',
                0, 1, self.fake_volumes_dir, _fake_get_target_chap_auth())

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(scst.SCSTAdm, '_get_target')
    @mock.patch.object(scst.SCSTAdm, 'scst_execute')
    def test_ensure_export_chap(self, mock_execute,
                                mock_get_target,
                                mock_scst_execute):
        mock_execute.return_value = (None, None)
        mock_scst_execute.return_value = (None, None)
        mock_get_target.return_value = 1
        ctxt = context.get_admin_context()

        def _fake_get_target_and_lun(*args, **kwargs):
            return 0, 1

        def _fake_get_target_chap_auth(*args, **kwargs):
            return None

        self.stubs.Set(self.target,
                       '_get_target_chap_auth',
                       _fake_get_target_chap_auth)
        self.stubs.Set(self.target,
                       '_get_target_and_lun',
                       _fake_get_target_and_lun)

        with mock.patch.object(self.target, 'create_iscsi_target'):
            self.target.ensure_export(ctxt,
                                      self.testvol_1,
                                      self.fake_volumes_dir)
            self.target.create_iscsi_target.assert_called_once_with(
                'iqn.2010-10.org.openstack:testvol',
                'ed2c2222-5fc0-11e4-aa15-123b93f75cba',
                0, 1, self.fake_volumes_dir, None)
