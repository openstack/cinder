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
import io
from unittest import mock

from oslo_concurrency import processutils as putils

from cinder import context
from cinder import exception
from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume.targets import iet


class TestIetAdmDriver(tf.TargetDriverFixture):

    def setUp(self):
        super(TestIetAdmDriver, self).setUp()
        self.target = iet.IetAdm(root_helper=utils.get_root_helper(),
                                 configuration=self.configuration)

    def test_get_target(self):
        tmp_file = io.StringIO()
        tmp_file.write(
            'tid:1 name:iqn.2010-10.org.openstack:'
            'volume-83c2e877-feed-46be-8435-77884fe55b45\n'
            '        sid:844427031282176 initiator:'
            'iqn.1994-05.com.redhat:5a6894679665\n'
            '               cid:0 ip:10.9.8.7 state:active hd:none dd:none')
        tmp_file.seek(0)
        with mock.patch('builtins.open') as mock_open:
            mock_open.return_value = contextlib.closing(tmp_file)
            self.assertEqual('1',
                             self.target._get_target(
                                 'iqn.2010-10.org.openstack:'
                                 'volume-83c2e877-feed-46be-8435-77884fe55b45'
                             ))

            # Test the failure case: Failed to handle the config file
            mock_open.side_effect = MemoryError()
            self.assertRaises(MemoryError,
                              self.target._get_target,
                              '')

    @mock.patch('cinder.volume.targets.iet.IetAdm._get_target',
                return_value=0)
    @mock.patch('cinder.privsep.targets.iet.new_target')
    @mock.patch('cinder.privsep.targets.iet.new_logicalunit')
    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('cinder.utils.temporary_chown')
    @mock.patch.object(iet, 'LOG')
    def test_create_iscsi_target(self, mock_log, mock_chown, mock_exists,
                                 mock_new_logical_unit, mock_new_target,
                                 mock_get_targ):
        tmp_file = io.StringIO()
        with mock.patch('builtins.open') as mock_open:
            mock_open.return_value = contextlib.closing(tmp_file)
            self.assertEqual(
                0,
                self.target.create_iscsi_target(
                    self.test_vol,
                    0,
                    0,
                    self.fake_volumes_dir))
            self.assertTrue(mock_new_target.called)
            self.assertTrue(mock_open.called)
            self.assertTrue(mock_get_targ.called)
            self.assertTrue(mock_new_logical_unit.called)

            # Test the failure case: Failed to chown the config file
            mock_open.side_effect = putils.ProcessExecutionError
            self.assertRaises(exception.ISCSITargetCreateFailed,
                              self.target.create_iscsi_target,
                              self.test_vol,
                              0,
                              0,
                              self.fake_volumes_dir)

            # Test the failure case: Failed to set new auth
            mock_new_target.side_effect = putils.ProcessExecutionError
            self.assertRaises(exception.ISCSITargetCreateFailed,
                              self.target.create_iscsi_target,
                              self.test_vol,
                              0,
                              0,
                              self.fake_volumes_dir)

    @mock.patch('cinder.utils.execute')
    @mock.patch('os.path.exists', return_value=True)
    def test_update_config_file_failure(self, mock_exists, mock_execute):
        # Test the failure case: conf file does not exist
        mock_exists.return_value = False
        mock_execute.side_effect = putils.ProcessExecutionError
        self.assertRaises(exception.ISCSITargetCreateFailed,
                          self.target.update_config_file,
                          self.test_vol,
                          0,
                          self.fake_volumes_dir,
                          "foo bar")

    @mock.patch('cinder.volume.targets.iet.IetAdm._get_target',
                return_value=1)
    @mock.patch('cinder.privsep.targets.iet.new_target')
    @mock.patch('cinder.privsep.targets.iet.new_logicalunit')
    def test_create_iscsi_target_already_exists(
            self, mock_new_logical_unit, mock_new_target, mock_get_targ):
        self.assertEqual(
            1,
            self.target.create_iscsi_target(
                self.test_vol,
                1,
                0,
                self.fake_volumes_dir))
        self.assertTrue(mock_get_targ.called)
        self.assertTrue(mock_new_target.called)
        self.assertTrue(mock_new_logical_unit.called)

    @mock.patch('cinder.volume.targets.iet.IetAdm._find_sid_cid_for_target',
                return_value=None)
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('cinder.privsep.targets.iet.delete_logicalunit')
    @mock.patch('cinder.privsep.targets.iet.delete_target')
    def test_remove_iscsi_target(
            self, mock_delete_target,
            mock_delete_logicalunit, mock_exists, mock_find):

        # Test the normal case
        self.target.remove_iscsi_target(1,
                                        0,
                                        self.testvol['id'],
                                        self.testvol['name'])
        mock_delete_logicalunit.assert_called_once_with(1, 0)
        mock_delete_target.assert_called_once_with(1)

        # Test the failure case: putils.ProcessExecutionError
        mock_delete_logicalunit.side_effect = putils.ProcessExecutionError
        self.assertRaises(exception.ISCSITargetRemoveFailed,
                          self.target.remove_iscsi_target,
                          1,
                          0,
                          self.testvol['id'],
                          self.testvol['name'])

    @mock.patch('cinder.privsep.targets.iet.delete_target')
    def test_find_sid_cid_for_target(self, mock_delete_target):
        tmp_file = io.StringIO()
        tmp_file.write(
            'tid:1 name:iqn.2010-10.org.openstack:'
            'volume-83c2e877-feed-46be-8435-77884fe55b45\n'
            '        sid:844427031282176 initiator:'
            'iqn.1994-05.com.redhat:5a6894679665\n'
            '               cid:0 ip:10.9.8.7 state:active hd:none dd:none')
        tmp_file.seek(0)
        with mock.patch('builtins.open') as mock_open:
            mock_open.return_value = contextlib.closing(tmp_file)
            self.assertEqual(('844427031282176', '0'),
                             self.target._find_sid_cid_for_target(
                                 '1',
                                 'iqn.2010-10.org.openstack:'
                                 'volume-83c2e877-feed-46be-8435-77884fe55b45',
                                 'volume-83c2e877-feed-46be-8435-77884fe55b45'
            ))

    @mock.patch('cinder.volume.targets.iet.IetAdm._get_target',
                return_value=1)
    @mock.patch('cinder.privsep.targets.iet.new_target')
    @mock.patch('cinder.privsep.targets.iet.new_logicalunit')
    @mock.patch('cinder.privsep.targets.iet.new_auth')
    @mock.patch.object(iet.IetAdm, '_get_target_chap_auth')
    def test_create_export(
            self, mock_get_chap, mock_new_auth, mock_new_logicalunit,
            mock_new_target, mock_get_targ):
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
        self.assertTrue(mock_new_logicalunit.called)
        self.assertTrue(mock_new_target.called)

    @mock.patch('cinder.volume.targets.iet.IetAdm._get_target_chap_auth',
                return_value=None)
    @mock.patch('cinder.volume.targets.iet.IetAdm._get_target',
                return_value=1)
    def test_ensure_export(self, mock_get_targetm, mock_get_chap):
        ctxt = context.get_admin_context()
        with mock.patch.object(self.target, 'create_iscsi_target'):
            self.target.ensure_export(ctxt,
                                      self.testvol,
                                      self.fake_volumes_dir)
            self.target.create_iscsi_target.assert_called_once_with(
                'iqn.2010-10.org.openstack:testvol',
                1, 0, self.fake_volumes_dir, None,
                portals_ips=[self.configuration.target_ip_address],
                portals_port=int(self.configuration.target_port),
                check_exit_code=False,
                old_name=None)
