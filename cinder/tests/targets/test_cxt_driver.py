# Copyright 2015 Chelsio Communications Inc.
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

import contextlib
import os
import shutil
import StringIO
import tempfile

import mock
from oslo_utils import timeutils

from cinder import context
from cinder.openstack.common import fileutils
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.targets import cxt


class TestCxtAdmDriver(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(TestCxtAdmDriver, self).__init__(*args, **kwargs)
        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.iscsi_ip_address = '10.9.8.7'
        self.cxt_subdir = cxt.CxtAdm.cxt_subdir
        self.fake_id_1 = 'ed2c1fd4-5fc0-11e4-aa15-123b93f75cba'
        self.fake_id_2 = 'ed2c2222-5fc0-11e4-aa15-123b93f75cba'
        self.target = cxt.CxtAdm(root_helper=utils.get_root_helper(),
                                 configuration=self.configuration)
        self.fake_volume = 'volume-83c2e877-feed-46be-8435-77884fe55b45'
        self.testvol_1 =\
            {'project_id': self.fake_id_1,
             'name': 'testvol',
             'size': 1,
             'id': self.fake_id_2,
             'volume_type_id': None,
             'provider_location': '10.9.8.7:3260 '
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

        self.fake_iscsi_scan =\
            ('\n'
             'TARGET: iqn.2010-10.org.openstack:%s, id=1, login_ip=0\n'  # noqa
             '        PortalGroup=1@10.9.8.7:3260,timeout=0\n'
             '        TargetDevice=/dev/stack-volumes-lvmdriver-1/%s,BLK,PROD=CHISCSI Target,SN=0N0743000000000,ID=0D074300000000000000000,WWN=:W00743000000000\n'  # noqa
             % (self.fake_volume, self.fake_volume))

    def setUp(self):
        super(TestCxtAdmDriver, self).setUp()
        self.fake_base_dir = tempfile.mkdtemp()
        self.fake_volumes_dir = os.path.join(self.fake_base_dir,
                                             self.cxt_subdir)
        fileutils.ensure_tree(self.fake_volumes_dir)
        self.addCleanup(self._cleanup)

        self.exec_patcher = mock.patch.object(utils, 'execute')
        self.mock_execute = self.exec_patcher.start()
        self.addCleanup(self.exec_patcher.stop)

    def _cleanup(self):
        if os.path.exists(self.fake_base_dir):
            shutil.rmtree(self.fake_base_dir)

    @mock.patch('cinder.utils.execute')
    def test_get_target(self, mock_execute):
        mock_execute.return_value = (self.fake_iscsi_scan, None)
        with mock.patch.object(self.target, '_get_volumes_dir') as mock_get:
            mock_get.return_value = self.fake_volumes_dir
            self.assertEqual('1',
                             self.target._get_target(
                                                     'iqn.2010-10.org.openstack:volume-83c2e877-feed-46be-8435-77884fe55b45'  # noqa
                                                    ))
            self.assertTrue(mock_execute.called)

    def test_get_target_chap_auth(self):
        tmp_file = StringIO.StringIO()
        tmp_file.write(
            'target:\n'
            '        TargetName=iqn.2010-10.org.openstack:volume-83c2e877-feed-46be-8435-77884fe55b45\n'  # noqa
            '        TargetDevice=/dev/stack-volumes-lvmdriver-1/volume-83c2e877-feed-46be-8435-77884fe55b45\n'  # noqa
            '        PortalGroup=1@10.9.8.7:3260\n'
            '        AuthMethod=CHAP\n'
            '        Auth_CHAP_Policy=Oneway\n'
            '        Auth_CHAP_Initiator="otzLy2UYbYfnP4zXLG5z":"234Zweo38VGBBvrpK9nt"\n'  # noqa
        )
        tmp_file.seek(0)
        test_vol = ('iqn.2010-10.org.openstack:'
                    'volume-83c2e877-feed-46be-8435-77884fe55b45')
        expected = ('otzLy2UYbYfnP4zXLG5z', '234Zweo38VGBBvrpK9nt')
        with mock.patch('__builtin__.open') as mock_open:
            ctx = context.get_admin_context()
            mock_open.return_value = contextlib.closing(tmp_file)
            self.assertEqual(expected,
                             self.target._get_target_chap_auth(ctx, test_vol))
            self.assertTrue(mock_open.called)

    def test_get_target_chap_auth_negative(self):
        test_vol =\
            'iqn.2010-10.org.openstack:'\
            'volume-83c2e877-feed-46be-8435-77884fe55b45'
        with mock.patch('__builtin__.open') as mock_open:
            e = IOError()
            e.errno = 123
            mock_open.side_effect = e
            ctxt = context.get_admin_context()
            self.assertRaises(IOError,
                              self.target._get_target_chap_auth,
                              ctxt, test_vol)
            mock_open.side_effect = StandardError()
            self.assertRaises(StandardError,
                              self.target._get_target_chap_auth,
                              ctxt, test_vol)

    @mock.patch('cinder.volume.targets.cxt.CxtAdm._get_target',
                return_value=1)
    @mock.patch('cinder.utils.execute')
    def test_create_iscsi_target(self, mock_execute, mock_get_targ):
        mock_execute.return_value = ('', '')
        with mock.patch.object(self.target, '_get_volumes_dir') as mock_get:
            mock_get.return_value = self.fake_volumes_dir
            test_vol = 'iqn.2010-10.org.openstack:'\
                       'volume-83c2e877-feed-46be-8435-77884fe55b45'
            self.assertEqual(
                1,
                self.target.create_iscsi_target(
                    test_vol,
                    1,
                    0,
                    self.fake_volumes_dir,
                    portals_ips=[self.configuration.iscsi_ip_address]))
            self.assertTrue(mock_get.called)
            self.assertTrue(mock_execute.called)
            self.assertTrue(mock_get_targ.called)

    @mock.patch('cinder.volume.targets.cxt.CxtAdm._get_target',
                return_value=1)
    @mock.patch('cinder.utils.execute', return_value=('fake out', 'fake err'))
    def test_create_iscsi_target_port_ips(self, mock_execute, mock_get_targ):
        ips = ['10.0.0.15', '127.0.0.1']
        port = 3261
        mock_execute.return_value = ('', '')
        with mock.patch.object(self.target, '_get_volumes_dir') as mock_get:
            mock_get.return_value = self.fake_volumes_dir
            test_vol = 'iqn.2010-10.org.openstack:'\
                       'volume-83c2e877-feed-46be-8435-77884fe55b45'
            self.assertEqual(
                1,
                self.target.create_iscsi_target(
                    test_vol,
                    1,
                    0,
                    self.fake_volumes_dir,
                    portals_port=port,
                    portals_ips=ips))

            self.assertTrue(mock_get.called)
            self.assertTrue(mock_execute.called)
            self.assertTrue(mock_get_targ.called)

            file_path = os.path.join(self.fake_volumes_dir,
                                     test_vol.split(':')[1])

            expected_cfg = {
                'name': test_vol,
                'device': self.fake_volumes_dir,
                'ips': ','.join(map(lambda ip: '%s:%s' % (ip, port), ips)),
                'spaces': ' ' * 14,
                'spaces2': ' ' * 23}

            expected_file = ('\n%(spaces)starget:'
                             '\n%(spaces2)sTargetName=%(name)s'
                             '\n%(spaces2)sTargetDevice=%(device)s'
                             '\n%(spaces2)sPortalGroup=1@%(ips)s'
                             '\n%(spaces)s   ') % expected_cfg

            with open(file_path, 'r') as cfg_file:
                result = cfg_file.read()
                self.assertEqual(expected_file, result)

    @mock.patch('cinder.volume.targets.cxt.CxtAdm._get_target',
                return_value=1)
    @mock.patch('cinder.utils.execute', return_value=('fake out', 'fake err'))
    def test_create_iscsi_target_already_exists(self, mock_execute,
                                                mock_get_targ):
        mock_execute.return_value = ('fake out', 'fake err')
        with mock.patch.object(self.target, '_get_volumes_dir') as mock_get:
            mock_get.return_value = self.fake_volumes_dir
            test_vol = 'iqn.2010-10.org.openstack:'\
                       'volume-83c2e877-feed-46be-8435-77884fe55b45'
            self.assertEqual(
                1,
                self.target.create_iscsi_target(
                    test_vol,
                    1,
                    0,
                    self.fake_volumes_dir,
                    portals_ips=[self.configuration.iscsi_ip_address]))
            self.assertTrue(mock_get.called)
            self.assertTrue(mock_get_targ.called)
            self.assertTrue(mock_execute.called)

    @mock.patch('cinder.volume.targets.cxt.CxtAdm._get_target',
                return_value=1)
    @mock.patch('cinder.utils.execute')
    @mock.patch.object(cxt.CxtAdm, '_get_target_chap_auth')
    def test_create_export(self, mock_chap, mock_execute,
                           mock_get_targ):
        mock_execute.return_value = ('', '')
        mock_chap.return_value = ('QZJbisGmn9AL954FNF4D',
                                  'P68eE7u9eFqDGexd28DQ')
        with mock.patch.object(self.target, '_get_volumes_dir') as mock_get:
            mock_get.return_value = self.fake_volumes_dir

            expected_result = {'location': '10.9.8.7:3260,1 '
                               'iqn.2010-10.org.openstack:testvol 0',
                               'auth': 'CHAP '
                               'QZJbisGmn9AL954FNF4D P68eE7u9eFqDGexd28DQ'}

            ctxt = context.get_admin_context()
            self.assertEqual(expected_result,
                             self.target.create_export(ctxt,
                                                       self.testvol_1,
                                                       self.fake_volumes_dir))
            self.assertTrue(mock_get.called)
            self.assertTrue(mock_execute.called)

    @mock.patch('cinder.volume.targets.cxt.CxtAdm._get_target_chap_auth')
    def test_ensure_export(self, mock_get_chap):
        fake_creds = ('asdf', 'qwert')
        mock_get_chap.return_value = fake_creds
        ctxt = context.get_admin_context()
        with mock.patch.object(self.target, 'create_iscsi_target'):
            self.target.ensure_export(ctxt,
                                      self.testvol_1,
                                      self.fake_volumes_dir)
            self.target.create_iscsi_target.assert_called_once_with(
                'iqn.2010-10.org.openstack:testvol',
                1, 0, self.fake_volumes_dir, fake_creds,
                check_exit_code=False,
                old_name=None,
                portals_ips=[self.configuration.iscsi_ip_address],
                portals_port=self.configuration.iscsi_port)
