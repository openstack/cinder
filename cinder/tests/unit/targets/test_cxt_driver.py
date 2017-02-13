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

import os
import sys

import mock

from cinder import context
from cinder import test
from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume.targets import cxt


class TestCxtAdmDriver(tf.TargetDriverFixture):
    def setUp(self):
        super(TestCxtAdmDriver, self).setUp()
        self.cxt_subdir = cxt.CxtAdm.cxt_subdir
        self.target = cxt.CxtAdm(root_helper=utils.get_root_helper(),
                                 configuration=self.configuration)
        self.VG = 'stack-volumes-lvmdriver-1'
        self.fake_iscsi_scan = \
            ('\n'
             'TARGET: iqn.2010-10.org.openstack:%(vol)s, id=1, login_ip=0\n'
             '        PortalGroup=1@10.9.8.7:3260,timeout=0\n'
             '        TargetDevice=/dev/%(vg)s/%(vol)s'
             ',BLK,PROD=CHISCSI '
             'Target,SN=0N0743000000000,ID=0D074300000000000000000,'
             'WWN=:W00743000000000\n'
             % {'vol': self.VOLUME_NAME, 'vg': self.VG})

    def test_get_target(self):
        with mock.patch.object(self.target, '_get_volumes_dir',
                               return_value=self.fake_volumes_dir),\
            mock.patch('cinder.utils.execute',
                       return_value=(self.fake_iscsi_scan, None)) as m_exec:
            self.assertEqual(
                '1',
                self.target._get_target(
                    'iqn.2010-10.org.openstack:volume-%s' % self.VOLUME_ID
                )
            )
            self.assertTrue(m_exec.called)

    @test.testtools.skipIf(sys.platform == "darwin", "SKIP on OSX")
    @mock.patch('cinder.volume.targets.cxt.CxtAdm._get_target',
                return_value=1)
    @mock.patch('cinder.utils.execute')
    def test_create_iscsi_target(self, mock_execute, mock_get_targ):
        mock_execute.return_value = ('', '')
        with mock.patch.object(self.target, '_get_volumes_dir') as mock_get:
            mock_get.return_value = self.fake_volumes_dir
            self.assertEqual(
                1,
                self.target.create_iscsi_target(
                    self.test_vol,
                    1,
                    0,
                    self.fake_volumes_dir,
                    portals_ips=[self.configuration.iscsi_ip_address]))
            self.assertTrue(mock_get.called)
            self.assertTrue(mock_execute.called)
            self.assertTrue(mock_get_targ.called)

    @test.testtools.skipIf(sys.platform == "darwin", "SKIP on OSX")
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

    @test.testtools.skipIf(sys.platform == "darwin", "SKIP on OSX")
    @mock.patch('cinder.volume.targets.cxt.CxtAdm._get_target',
                return_value=1)
    @mock.patch('cinder.utils.execute', return_value=('fake out', 'fake err'))
    def test_create_iscsi_target_already_exists(self, mock_execute,
                                                mock_get_targ):
        with mock.patch.object(self.target, '_get_volumes_dir') as mock_get:
            mock_get.return_value = self.fake_volumes_dir
            self.assertEqual(
                1,
                self.target.create_iscsi_target(
                    self.test_vol,
                    1,
                    0,
                    self.fake_volumes_dir,
                    portals_ips=[self.configuration.iscsi_ip_address]))
            self.assertTrue(mock_get.called)
            self.assertTrue(mock_get_targ.called)
            self.assertTrue(mock_execute.called)

    @test.testtools.skipIf(sys.platform == "darwin", "SKIP on OSX")
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
                                                       self.testvol,
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
                                      self.testvol,
                                      self.fake_volumes_dir)
            self.target.create_iscsi_target.assert_called_once_with(
                'iqn.2010-10.org.openstack:testvol',
                1, 0, self.fake_volumes_dir, fake_creds,
                check_exit_code=False,
                old_name=None,
                portals_ips=[self.configuration.iscsi_ip_address],
                portals_port=self.configuration.iscsi_port)
