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
import time

import mock
from oslo_concurrency import processutils as putils

from cinder import context
from cinder import exception
from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume.targets import tgt
from cinder.volume import utils as vutils


class TestTgtAdmDriver(tf.TargetDriverFixture):

    def setUp(self):
        super(TestTgtAdmDriver, self).setUp()
        self.configuration.get = mock.Mock(side_effect=self.fake_get)

        self.target = tgt.TgtAdm(root_helper=utils.get_root_helper(),
                                 configuration=self.configuration)
        self.testvol_path = \
            '/dev/stack-volumes-lvmdriver-1/%s' % self.VOLUME_NAME

        self.fake_iscsi_scan =\
            ('Target 1: %(test_vol)s\n'
             '    System information:\n'
             '        Driver: iscsi\n'
             '        State: ready\n'
             '    I_T nexus information:\n'
             '    LUN information:\n'
             '        LUN: 0\n'
             '            Type: controller\n'
             '            SCSI ID: IET     00010000\n'
             '            SCSI SN: beaf10\n'
             '            Size: 0 MB, Block size: 1\n'
             '            Online: Yes\n'
             '            Removable media: No\n'
             '            Prevent removal: No\n'
             '            Readonly: No\n'
             '            SWP: No\n'
             '            Thin-provisioning: No\n'
             '            Backing store type: null\n'
             '            Backing store path: None\n'
             '            Backing store flags:\n'
             '        LUN: 1\n'
             '            Type: disk\n'
             '            SCSI ID: IET     00010001\n'
             '            SCSI SN: beaf11\n'
             '            Size: 1074 MB, Block size: 512\n'
             '            Online: Yes\n'
             '            Removable media: No\n'
             '            Prevent removal: No\n'
             '            Readonly: No\n'
             '            SWP: No\n'
             '            Thin-provisioning: No\n'
             '            Backing store type: rdwr\n'
             '            Backing store path: %(bspath)s\n'
             '            Backing store flags:\n'
             '    Account information:\n'
             '        mDVpzk8cZesdahJC9h73\n'
             '    ACL information:\n'
             '        ALL"\n' % {'test_vol': self.test_vol,
                                 'bspath': self.testvol_path})

    def fake_get(self, value, default):
        if value in ('iscsi_target_flags', 'iscsi_write_cache'):
            return getattr(self, value, default)

    def test_iscsi_protocol(self):
        self.assertEqual('iscsi', self.target.iscsi_protocol)

    def test_get_target(self):
        with mock.patch('cinder.utils.execute',
                        return_value=(self.fake_iscsi_scan, None)):
            iqn = self.test_vol
            self.assertEqual('1', self.target._get_target(iqn))

    def test_verify_backing_lun(self):
        iqn = self.test_vol

        with mock.patch('cinder.utils.execute',
                        return_value=(self.fake_iscsi_scan, None)):
            self.assertTrue(self.target._verify_backing_lun(iqn, '1'))

        # Test the failure case
        bad_scan = self.fake_iscsi_scan.replace('LUN: 1', 'LUN: 3')

        with mock.patch('cinder.utils.execute',
                        return_value=(bad_scan, None)):
            self.assertFalse(self.target._verify_backing_lun(iqn, '1'))

    @mock.patch.object(time, 'sleep')
    @mock.patch('cinder.utils.execute')
    def test_recreate_backing_lun(self, mock_execute, mock_sleep):
        mock_execute.return_value = ('out', 'err')
        self.target._recreate_backing_lun(self.test_vol, '1',
                                          self.testvol['name'],
                                          self.testvol_path)

        expected_command = ('tgtadm', '--lld', 'iscsi', '--op', 'new',
                            '--mode', 'logicalunit', '--tid', '1',
                            '--lun', '1', '-b',
                            self.testvol_path)

        mock_execute.assert_called_once_with(*expected_command,
                                             run_as_root=True)

        # Test the failure case
        mock_execute.side_effect = putils.ProcessExecutionError
        self.assertFalse(self.target._recreate_backing_lun(
            self.test_vol,
            '1',
            self.testvol['name'],
            self.testvol_path))

    def test_get_iscsi_target(self):
        ctxt = context.get_admin_context()
        expected = 0
        self.assertEqual(expected,
                         self.target._get_iscsi_target(ctxt,
                                                       self.testvol['id']))

    def test_get_target_and_lun(self):
        lun = 1
        iscsi_target = 0
        ctxt = context.get_admin_context()
        expected = (iscsi_target, lun)
        self.assertEqual(expected,
                         self.target._get_target_and_lun(ctxt, self.testvol))

    def test_create_iscsi_target(self):
        with mock.patch('cinder.utils.execute', return_value=('', '')),\
                mock.patch.object(self.target, '_get_target',
                                  side_effect=lambda x: 1),\
                mock.patch.object(self.target, '_verify_backing_lun',
                                  side_effect=lambda x, y: True):
            self.assertEqual(
                1,
                self.target.create_iscsi_target(
                    self.test_vol,
                    1,
                    0,
                    self.fake_volumes_dir))

    def test_create_iscsi_target_content(self):

        self.iscsi_target_flags = 'foo'
        self.iscsi_write_cache = 'bar'

        mock_open = mock.mock_open()
        with mock.patch('cinder.utils.execute', return_value=('', '')),\
                mock.patch.object(self.target, '_get_target',
                                  side_effect=lambda x: 1),\
                mock.patch.object(self.target, '_verify_backing_lun',
                                  side_effect=lambda x, y: True),\
                mock.patch('cinder.volume.targets.tgt.open',
                           mock_open, create=True):
            self.assertEqual(
                1,
                self.target.create_iscsi_target(
                    self.test_vol,
                    1,
                    0,
                    self.testvol_path,
                    chap_auth=('chap_foo', 'chap_bar')))

        mock_open.assert_called_once_with(
            os.path.join(self.fake_volumes_dir, self.test_vol.split(':')[1]),
            'w+')
        expected = ('\n<target iqn.2010-10.org.openstack:volume-%(id)s>\n'
                    '    backing-store %(bspath)s\n'
                    '    driver iscsi\n'
                    '    incominguser chap_foo chap_bar\n'
                    '    bsoflags foo\n'
                    '    write-cache bar\n'
                    '</target>\n' % {'id': self.VOLUME_ID,
                                     'bspath': self.testvol_path})
        self.assertEqual(expected,
                         mock_open.return_value.write.call_args[0][0])

    def test_create_iscsi_target_already_exists(self):
        def _fake_execute(*args, **kwargs):
            if 'update' in args:
                raise putils.ProcessExecutionError(
                    exit_code=1,
                    stdout='',
                    stderr='target already exists',
                    cmd='tgtad --lld iscsi --op show --mode target')
            else:
                return 'fake out', 'fake err'

        with mock.patch.object(self.target, '_get_target',
                               side_effect=lambda x: 1),\
                mock.patch.object(self.target, '_verify_backing_lun',
                                  side_effect=lambda x, y: True),\
                mock.patch('cinder.utils.execute', _fake_execute):
            self.assertEqual(
                1,
                self.target.create_iscsi_target(
                    self.test_vol,
                    1,
                    0,
                    self.fake_volumes_dir))

    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('cinder.utils.execute')
    @mock.patch('os.unlink', return_value=None)
    def test_delete_target_not_found(self,
                                     mock_unlink,
                                     mock_exec,
                                     mock_pathexists,
                                     mock_isfile):
        def _fake_execute(*args, **kwargs):
            raise putils.ProcessExecutionError(
                exit_code=1,
                stdout='',
                stderr='can\'t find the target',
                cmd='tgt-admin --force --delete')

        def _fake_execute_wrong_message(*args, **kwargs):
            raise putils.ProcessExecutionError(
                exit_code=1,
                stdout='',
                stderr='this is not the error you are looking for',
                cmd='tgt-admin --force --delete')

        mock_exec.side_effect = _fake_execute

        with mock.patch.object(self.target, '_get_target', return_value=False):
            self.assertEqual(
                None,
                self.target.remove_iscsi_target(
                    1,
                    0,
                    self.VOLUME_ID,
                    self.VOLUME_NAME))

            mock_exec.side_effect = _fake_execute_wrong_message
            self.assertRaises(exception.ISCSITargetRemoveFailed,
                              self.target.remove_iscsi_target,
                              1,
                              0,
                              self.VOLUME_ID,
                              self.VOLUME_NAME)

    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('cinder.utils.execute')
    @mock.patch('os.unlink', return_value=None)
    def test_delete_target_acl_not_found(self,
                                         mock_unlink,
                                         mock_exec,
                                         mock_pathexists,
                                         mock_isfile):
        def _fake_execute(*args, **kwargs):
            raise putils.ProcessExecutionError(
                exit_code=1,
                stdout='',
                stderr='this access control rule does not exist',
                cmd='tgt-admin --force --delete')

        def _fake_execute_wrong_message(*args, **kwargs):
            raise putils.ProcessExecutionError(
                exit_code=1,
                stdout='',
                stderr='this is not the error you are looking for',
                cmd='tgt-admin --force --delete')

        mock_exec.side_effect = _fake_execute

        with mock.patch.object(self.target, '_get_target', return_value=False):
            self.assertEqual(
                None,
                self.target.remove_iscsi_target(
                    1,
                    0,
                    self.VOLUME_ID,
                    self.VOLUME_NAME))

            mock_exec.side_effect = _fake_execute_wrong_message
            self.assertRaises(exception.ISCSITargetRemoveFailed,
                              self.target.remove_iscsi_target,
                              1,
                              0,
                              self.VOLUME_ID,
                              self.VOLUME_NAME)

    @mock.patch.object(tgt.TgtAdm, '_get_iscsi_properties')
    def test_initialize_connection(self, mock_get_iscsi):

        connector = {'initiator': 'fake_init'}

        # Test the normal case
        mock_get_iscsi.return_value = 'foo bar'
        expected_return = {'driver_volume_type': 'iscsi',
                           'data': 'foo bar'}
        self.assertEqual(expected_return,
                         self.target.initialize_connection(self.testvol,
                                                           connector))

    @mock.patch('cinder.utils.execute')
    @mock.patch.object(tgt.TgtAdm, '_get_target')
    @mock.patch.object(os.path, 'exists')
    @mock.patch.object(os.path, 'isfile')
    @mock.patch.object(os, 'unlink')
    def test_remove_iscsi_target(self,
                                 mock_unlink,
                                 mock_isfile,
                                 mock_path_exists,
                                 mock_get_target,
                                 mock_execute):

        # Test the failure case: path does not exist
        mock_path_exists.return_value = None
        self.assertEqual(None,
                         self.target.remove_iscsi_target(
                             0,
                             1,
                             self.testvol['id'],
                             self.testvol['name']))

        # Test the normal case
        mock_path_exists.return_value = True
        mock_isfile.return_value = True
        self.target.remove_iscsi_target(0,
                                        1,
                                        self.testvol['id'],
                                        self.testvol['name'])
        calls = [mock.call('tgt-admin', '--force', '--delete',
                           self.iscsi_target_prefix + self.testvol['name'],
                           run_as_root=True),
                 mock.call('tgt-admin', '--delete',
                           self.iscsi_target_prefix + self.testvol['name'],
                           run_as_root=True)]

        mock_execute.assert_has_calls(calls)

    def test_create_export(self):
        expected_result = {'location': '10.9.8.7:3260,1 ' +
                           self.iscsi_target_prefix +
                           self.testvol['name'] + ' 1',
                           'auth': 'CHAP QZJb P68e'}

        with mock.patch('cinder.utils.execute', return_value=('', '')),\
                mock.patch.object(self.target, '_get_target',
                                  side_effect=lambda x: 1),\
                mock.patch.object(self.target, '_verify_backing_lun',
                                  side_effect=lambda x, y: True),\
                mock.patch.object(self.target, '_get_target_chap_auth',
                                  side_effect=lambda x, y: None) as m_chap,\
                mock.patch.object(vutils, 'generate_username',
                                  side_effect=lambda: 'QZJb'),\
                mock.patch.object(vutils, 'generate_password',
                                  side_effect=lambda: 'P68e'):

            ctxt = context.get_admin_context()
            self.assertEqual(expected_result,
                             self.target.create_export(ctxt,
                                                       self.testvol,
                                                       self.fake_volumes_dir))

            m_chap.side_effect = lambda x, y: ('otzL', '234Z')

            expected_result['auth'] = ('CHAP otzL 234Z')

            self.assertEqual(expected_result,
                             self.target.create_export(ctxt,
                                                       self.testvol,
                                                       self.fake_volumes_dir))

    @mock.patch.object(tgt.TgtAdm, '_get_target_chap_auth')
    @mock.patch.object(tgt.TgtAdm, 'create_iscsi_target')
    def test_ensure_export(self, _mock_create, mock_get_chap):
        ctxt = context.get_admin_context()
        mock_get_chap.return_value = ('foo', 'bar')
        self.target.ensure_export(ctxt,
                                  self.testvol,
                                  self.fake_volumes_dir)

        _mock_create.assert_called_once_with(
            self.iscsi_target_prefix + self.testvol['name'],
            0, 1, self.fake_volumes_dir, ('foo', 'bar'),
            check_exit_code=False,
            old_name=None,
            portals_ips=[self.configuration.iscsi_ip_address],
            portals_port=self.configuration.iscsi_port)
