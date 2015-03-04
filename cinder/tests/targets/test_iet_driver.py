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
from oslo_concurrency import processutils as putils
from oslo_utils import timeutils

from cinder import context
from cinder import exception
from cinder.openstack.common import fileutils
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.targets import iet


class TestIetAdmDriver(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(TestIetAdmDriver, self).__init__(*args, **kwargs)
        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.iscsi_ip_address = '10.9.8.7'
        self.fake_project_id = 'ed2c1fd4-5fc0-11e4-aa15-123b93f75cba'
        self.fake_volume_id = '83c2e877-feed-46be-8435-77884fe55b45'
        self.target = iet.IetAdm(root_helper=utils.get_root_helper(),
                                 configuration=self.configuration)
        self.testvol =\
            {'project_id': self.fake_project_id,
             'name': 'testvol',
             'size': 1,
             'id': self.fake_volume_id,
             'volume_type_id': None,
             'provider_location': '10.9.8.7:3260 '
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

    def setUp(self):
        super(TestIetAdmDriver, self).setUp()
        self.fake_volumes_dir = tempfile.mkdtemp()
        fileutils.ensure_tree(self.fake_volumes_dir)
        self.addCleanup(self._cleanup)

        self.exec_patcher = mock.patch.object(utils, 'execute')
        self.mock_execute = self.exec_patcher.start()
        self.addCleanup(self.exec_patcher.stop)

    def _cleanup(self):
        if os.path.exists(self.fake_volumes_dir):
            shutil.rmtree(self.fake_volumes_dir)

    def test_get_target(self):
        tmp_file = StringIO.StringIO()
        tmp_file.write(
            'tid:1 name:iqn.2010-10.org.openstack:volume-83c2e877-feed-46be-8435-77884fe55b45\n'  # noqa
            '        sid:844427031282176 initiator:iqn.1994-05.com.redhat:5a6894679665\n'  # noqa
            '               cid:0 ip:10.9.8.7 state:active hd:none dd:none')
        tmp_file.seek(0)
        with mock.patch('__builtin__.open') as mock_open:
            mock_open.return_value = contextlib.closing(tmp_file)
            self.assertEqual('1',
                             self.target._get_target(
                                                     'iqn.2010-10.org.openstack:volume-83c2e877-feed-46be-8435-77884fe55b45'  # noqa
                                                    ))

            # Test the failure case: Failed to handle the config file
            mock_open.side_effect = StandardError()
            self.assertRaises(StandardError,
                              self.target._get_target,
                              '')

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('cinder.utils.temporary_chown')
    def test_get_target_chap_auth(self, mock_chown, mock_exists):
        tmp_file = StringIO.StringIO()
        tmp_file.write(
            'Target iqn.2010-10.org.openstack:volume-83c2e877-feed-46be-8435-77884fe55b45\n'  # noqa
            '    IncomingUser otzLy2UYbYfnP4zXLG5z 234Zweo38VGBBvrpK9nt\n'
            '    Lun 0 Path=/dev/stack-volumes-lvmdriver-1/volume-83c2e877-feed-46be-8435-77884fe55b45,Type=fileio\n'  # noqa
        )
        tmp_file.seek(0)
        test_vol = ('iqn.2010-10.org.openstack:'
                    'volume-83c2e877-feed-46be-8435-77884fe55b45')
        expected = ('otzLy2UYbYfnP4zXLG5z', '234Zweo38VGBBvrpK9nt')
        with mock.patch('__builtin__.open') as mock_open:
            ictx = context.get_admin_context()
            mock_open.return_value = contextlib.closing(tmp_file)
            self.assertEqual(expected,
                             self.target._get_target_chap_auth(ictx, test_vol))
            self.assertTrue(mock_open.called)

            # Test the failure case: Failed to handle the config file
            mock_open.side_effect = StandardError()
            self.assertRaises(StandardError,
                              self.target._get_target_chap_auth,
                              ictx,
                              test_vol)

    @mock.patch('cinder.volume.targets.iet.IetAdm._get_target',
                return_value=0)
    @mock.patch('cinder.utils.execute')
    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('cinder.utils.temporary_chown')
    def test_create_iscsi_target(self, mock_chown, mock_exists,
                                 mock_execute, mock_get_targ):
        mock_execute.return_value = ('', '')
        tmp_file = StringIO.StringIO()
        test_vol = ('iqn.2010-10.org.openstack:'
                    'volume-83c2e877-feed-46be-8435-77884fe55b45')
        with mock.patch('__builtin__.open') as mock_open:
            mock_open.return_value = contextlib.closing(tmp_file)
            self.assertEqual(
                0,
                self.target.create_iscsi_target(
                    test_vol,
                    0,
                    0,
                    self.fake_volumes_dir))
            self.assertTrue(mock_execute.called)
            self.assertTrue(mock_open.called)
            self.assertTrue(mock_get_targ.called)

            # Test the failure case: Failed to chown the config file
            mock_open.side_effect = putils.ProcessExecutionError
            self.assertRaises(exception.ISCSITargetCreateFailed,
                              self.target.create_iscsi_target,
                              test_vol,
                              0,
                              0,
                              self.fake_volumes_dir)

            # Test the failure case: Failed to set new auth
            mock_execute.side_effect = putils.ProcessExecutionError
            self.assertRaises(exception.ISCSITargetCreateFailed,
                              self.target.create_iscsi_target,
                              test_vol,
                              0,
                              0,
                              self.fake_volumes_dir)

    @mock.patch('cinder.utils.execute')
    @mock.patch('os.path.exists', return_value=True)
    def test_update_config_file_failure(self, mock_exists, mock_execute):
        test_vol = ('iqn.2010-10.org.openstack:'
                    'volume-83c2e877-feed-46be-8435-77884fe55b45')

        # Test the failure case: conf file does not exist
        mock_exists.return_value = False
        mock_execute.side_effect = putils.ProcessExecutionError
        self.assertRaises(exception.ISCSITargetCreateFailed,
                          self.target.update_config_file,
                          test_vol,
                          0,
                          self.fake_volumes_dir,
                          "foo bar")

    @mock.patch('cinder.volume.targets.iet.IetAdm._get_target',
                return_value=1)
    @mock.patch('cinder.utils.execute')
    def test_create_iscsi_target_already_exists(self, mock_execute,
                                                mock_get_targ):
        mock_execute.return_value = ('fake out', 'fake err')
        test_vol = 'iqn.2010-10.org.openstack:'\
                   'volume-83c2e877-feed-46be-8435-77884fe55b45'
        self.assertEqual(
            1,
            self.target.create_iscsi_target(
                test_vol,
                1,
                0,
                self.fake_volumes_dir))
        self.assertTrue(mock_get_targ.called)
        self.assertTrue(mock_execute.called)

    @mock.patch('cinder.volume.targets.iet.IetAdm._find_sid_cid_for_target',
                return_value=None)
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch.object(utils, 'execute')
    def test_remove_iscsi_target(self, mock_execute, mock_exists, mock_find):

        # Test the normal case
        self.target.remove_iscsi_target(1,
                                        0,
                                        self.testvol['id'],
                                        self.testvol['name'])
        mock_execute.assert_any_calls('ietadm',
                                      '--op',
                                      'delete',
                                      '--tid=1',
                                      run_as_root=True)

        # Test the failure case: putils.ProcessExecutionError
        mock_execute.side_effect = putils.ProcessExecutionError
        self.assertRaises(exception.ISCSITargetRemoveFailed,
                          self.target.remove_iscsi_target,
                          1,
                          0,
                          self.testvol['id'],
                          self.testvol['name'])

    def test_find_sid_cid_for_target(self):
        tmp_file = StringIO.StringIO()
        tmp_file.write(
            'tid:1 name:iqn.2010-10.org.openstack:volume-83c2e877-feed-46be-8435-77884fe55b45\n'  # noqa
            '        sid:844427031282176 initiator:iqn.1994-05.com.redhat:5a6894679665\n'  # noqa
            '               cid:0 ip:10.9.8.7 state:active hd:none dd:none')
        tmp_file.seek(0)
        with mock.patch('__builtin__.open') as mock_open:
            mock_open.return_value = contextlib.closing(tmp_file)
            self.assertEqual(('844427031282176', '0'),
                             self.target._find_sid_cid_for_target(
                                                     '1',
                                                     'iqn.2010-10.org.openstack:volume-83c2e877-feed-46be-8435-77884fe55b45',  # noqa
                                                     'volume-83c2e877-feed-46be-8435-77884fe55b45'  # noqa
                                                    ))

    @mock.patch('cinder.volume.targets.iet.IetAdm._get_target',
                return_value=1)
    @mock.patch('cinder.utils.execute')
    @mock.patch.object(iet.IetAdm, '_get_target_chap_auth')
    def test_create_export(self, mock_get_chap, mock_execute,
                           mock_get_targ):
        mock_execute.return_value = ('', '')
        mock_get_chap.return_value = ('QZJbisGmn9AL954FNF4D',
                                      'P68eE7u9eFqDGexd28DQ')
        expected_result = {'location': '10.9.8.7:3260,1 '
                           'iqn.2010-10.org.openstack:testvol 0',
                           'auth': 'CHAP '
                           'QZJbisGmn9AL954FNF4D P68eE7u9eFqDGexd28DQ'}
        ctxt = context.get_admin_context()
        self.assertEqual(expected_result,
                         self.target.create_export(ctxt,
                                                   self.testvol,
                                                   self.fake_volumes_dir))
        self.assertTrue(mock_execute.called)

    @mock.patch('cinder.volume.targets.iet.IetAdm._get_target',
                return_value=1)
    def test_ensure_export(self, mock_get_target):
        ctxt = context.get_admin_context()
        with mock.patch.object(self.target, 'create_iscsi_target'):
            self.target.ensure_export(ctxt,
                                      self.testvol,
                                      self.fake_volumes_dir)
            self.target.create_iscsi_target.assert_called_once_with(
                'iqn.2010-10.org.openstack:testvol',
                1, 0, self.fake_volumes_dir, None,
                portals_ips=[self.configuration.iscsi_ip_address],
                portals_port=int(self.configuration.iscsi_port),
                check_exit_code=False,
                old_name=None)
