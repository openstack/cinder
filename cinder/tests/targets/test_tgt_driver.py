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
import tempfile
import time

import mock
from oslo_concurrency import processutils as putils
from oslo_utils import timeutils

from cinder import context
from cinder import exception
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.targets import tgt
from cinder.volume import utils as vutils


class TestTgtAdmDriver(test.TestCase):

    def setUp(self):
        super(TestTgtAdmDriver, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.iscsi_ip_address = '10.9.8.7'
        self.fake_volumes_dir = tempfile.mkdtemp()
        self.iscsi_target_prefix = 'iqn.2010-10.org.openstack:'
        self.fake_project_id = 'ed2c1fd4-5fc0-11e4-aa15-123b93f75cba'
        self.fake_volume_id = '83c2e877-feed-46be-8435-77884fe55b45'
        self.stubs.Set(self.configuration, 'safe_get', self.fake_safe_get)
        self.target = tgt.TgtAdm(root_helper=utils.get_root_helper(),
                                 configuration=self.configuration)
        self.testvol =\
            {'project_id': self.fake_project_id,
             'name': 'volume-%s' % self.fake_volume_id,
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

        self.testvol_path = \
            '/dev/stack-volumes-lvmdriver-1/'\
            'volume-83c2e877-feed-46be-8435-77884fe55b45'

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
             'target_portal': '10.9.8.7:3260',
             'volume_id': self.fake_volume_id}

        self.fake_iscsi_scan =\
            ('Target 1: iqn.2010-10.org.openstack:volume-83c2e877-feed-46be-8435-77884fe55b45\n'  # noqa
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
             '            Backing store path: /dev/stack-volumes-lvmdriver-1/volume-83c2e877-feed-46be-8435-77884fe55b45\n'  # noqa
             '            Backing store flags:\n'
             '    Account information:\n'
             '        mDVpzk8cZesdahJC9h73\n'
             '    ACL information:\n'
             '        ALL"\n')

    def fake_safe_get(self, value):
        if value == 'volumes_dir':
            return self.fake_volumes_dir
        elif value == 'iscsi_protocol':
            return self.configuration.iscsi_protocol
        elif value == 'iscsi_target_prefix':
            return self.iscsi_target_prefix

    def test_iscsi_protocol(self):
        self.assertEqual(self.target.iscsi_protocol, 'iscsi')

    def test_get_target(self):

        def _fake_execute(*args, **kwargs):
            return self.fake_iscsi_scan, None

        self.stubs.Set(utils,
                       'execute',
                       _fake_execute)

        self.assertEqual('1',
                         self.target._get_target('iqn.2010-10.org.openstack:'
                                                 'volume-83c2e877-feed-46be-'
                                                 '8435-77884fe55b45'))

    def test_verify_backing_lun(self):

        def _fake_execute(*args, **kwargs):
            return self.fake_iscsi_scan, None

        self.stubs.Set(utils,
                       'execute',
                       _fake_execute)

        self.assertTrue(self.target._verify_backing_lun(
            'iqn.2010-10.org.openstack:'
            'volume-83c2e877-feed-46be-'
            '8435-77884fe55b45', '1'))

        # Test the failure case
        bad_scan = self.fake_iscsi_scan.replace('LUN: 1', 'LUN: 3')

        def _fake_execute_bad_lun(*args, **kwargs):
            return bad_scan, None

        self.stubs.Set(utils,
                       'execute',
                       _fake_execute_bad_lun)

        self.assertFalse(self.target._verify_backing_lun(
            'iqn.2010-10.org.openstack:'
            'volume-83c2e877-feed-46be-'
            '8435-77884fe55b45', '1'))

    @mock.patch.object(time, 'sleep')
    @mock.patch.object(utils, 'execute')
    def test_recreate_backing_lun(self, mock_execute, mock_sleep):

        test_vol = 'iqn.2010-10.org.openstack:'\
                   'volume-83c2e877-feed-46be-8435-77884fe55b45'
        mock_execute.return_value = ('out', 'err')
        self.target._recreate_backing_lun(test_vol, '1',
                                          self.testvol['name'],
                                          self.testvol_path)

        expected_command = ('tgtadm', '--lld', 'iscsi', '--op', 'new',
                            '--mode', 'logicalunit', '--tid', '1',
                            '--lun', '1', '-b',
                            '/dev/stack-volumes-lvmdriver-1/'
                            'volume-83c2e877-feed-46be-8435-77884fe55b45')

        mock_execute.assert_called_once_with(*expected_command,
                                             run_as_root=True)

        # Test the failure case
        mock_execute.side_effect = putils.ProcessExecutionError
        self.assertFalse(self.target._recreate_backing_lun(
            test_vol,
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

    def test_get_target_chap_auth(self):
        persist_file =\
            '<target iqn.2010-10.org.openstack:volume-83c2e877-feed-46be-8435-77884fe55b45>\n'\
            '    backing-store /dev/stack-volumes-lvmdriver-1/volume-83c2e877-feed-46be-8435-77884fe55b45\n'\
            '    driver iscsi\n'\
            '    incominguser otzLy2UYbYfnP4zXLG5z 234Zweo38VGBBvrpK9nt\n'\
            '    write-cache on\n'\
            '</target>'
        test_vol =\
            'iqn.2010-10.org.openstack:'\
            'volume-83c2e877-feed-46be-8435-77884fe55b45'
        with open(os.path.join(self.fake_volumes_dir,
                               test_vol.split(':')[1]),
                  'wb') as tmp_file:
            tmp_file.write(persist_file)
        ctxt = context.get_admin_context()
        expected = ('otzLy2UYbYfnP4zXLG5z', '234Zweo38VGBBvrpK9nt')
        self.assertEqual(expected,
                         self.target._get_target_chap_auth(ctxt, test_vol))

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

    def test_create_iscsi_target(self):

        def _fake_execute(*args, **kwargs):
            return '', ''

        self.stubs.Set(utils,
                       'execute',
                       _fake_execute)

        self.stubs.Set(self.target,
                       '_get_target',
                       lambda x: 1)

        self.stubs.Set(self.target,
                       '_verify_backing_lun',
                       lambda x, y: True)

        test_vol = 'iqn.2010-10.org.openstack:'\
                   'volume-83c2e877-feed-46be-8435-77884fe55b45'
        self.assertEqual(
            1,
            self.target.create_iscsi_target(
                test_vol,
                1,
                0,
                self.fake_volumes_dir))

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

        self.stubs.Set(utils,
                       'execute',
                       _fake_execute)

        self.stubs.Set(self.target,
                       '_get_target',
                       lambda x: 1)

        self.stubs.Set(self.target,
                       '_verify_backing_lun',
                       lambda x, y: True)

        test_vol = 'iqn.2010-10.org.openstack:'\
                   'volume-83c2e877-feed-46be-8435-77884fe55b45'
        self.assertEqual(
            1,
            self.target.create_iscsi_target(
                test_vol,
                1,
                0,
                self.fake_volumes_dir))

    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('os.path.exists', return_value=True)
    @mock.patch.object(utils, 'execute')
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
                stderr='this isnt the error your looking for',
                cmd='tgt-admin --force --delete')

        mock_exec.side_effect = _fake_execute

        test_vol_id = '83c2e877-feed-46be-8435-77884fe55b45'
        test_vol_name = 'volume-83c2e877-feed-46be-8435-77884fe55b45'

        with mock.patch.object(self.target, '_get_target', return_value=False):
            self.assertEqual(
                None,
                self.target.remove_iscsi_target(
                    1,
                    0,
                    test_vol_id,
                    test_vol_name))

            mock_exec.side_effect = _fake_execute_wrong_message
            self.assertRaises(exception.ISCSITargetRemoveFailed,
                              self.target.remove_iscsi_target,
                              1,
                              0,
                              test_vol_id,
                              test_vol_name)

    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('os.path.exists', return_value=True)
    @mock.patch.object(utils, 'execute')
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
                stderr='this isnt the error your looking for',
                cmd='tgt-admin --force --delete')

        mock_exec.side_effect = _fake_execute

        test_vol_id = '83c2e877-feed-46be-8435-77884fe55b45'
        test_vol_name = 'volume-83c2e877-feed-46be-8435-77884fe55b45'

        with mock.patch.object(self.target, '_get_target', return_value=False):
            self.assertEqual(
                None,
                self.target.remove_iscsi_target(
                    1,
                    0,
                    test_vol_id,
                    test_vol_name))

            mock_exec.side_effect = _fake_execute_wrong_message
            self.assertRaises(exception.ISCSITargetRemoveFailed,
                              self.target.remove_iscsi_target,
                              1,
                              0,
                              test_vol_id,
                              test_vol_name)

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

    @mock.patch.object(utils, 'execute')
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

        test_vol = 'iqn.2010-10.org.openstack:'\
                   'volume-83c2e877-feed-46be-8435-77884fe55b45'

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
        calls = [mock.call('tgt-admin', '--force', '--delete', test_vol,
                           run_as_root=True),
                 mock.call('tgt-admin', '--delete', test_vol,
                           run_as_root=True)]

        mock_execute.assert_has_calls(calls)

    def test_create_export(self):

        def _fake_execute(*args, **kwargs):
            return '', ''

        self.stubs.Set(utils,
                       'execute',
                       _fake_execute)

        self.stubs.Set(self.target,
                       '_get_target',
                       lambda x: 1)

        self.stubs.Set(self.target,
                       '_verify_backing_lun',
                       lambda x, y: True)

        self.stubs.Set(self.target,
                       '_get_target_chap_auth',
                       lambda x, y: None)
        self.stubs.Set(vutils,
                       'generate_username',
                       lambda: 'QZJbisGmn9AL954FNF4D')
        self.stubs.Set(vutils,
                       'generate_password',
                       lambda: 'P68eE7u9eFqDGexd28DQ')

        expected_result = {'location': '10.9.8.7:3260,1 '
                           'iqn.2010-10.org.openstack:'
                           'volume-83c2e877-feed-46be-8435-77884fe55b45 1',
                           'auth': 'CHAP '
                           'QZJbisGmn9AL954FNF4D P68eE7u9eFqDGexd28DQ'}

        ctxt = context.get_admin_context()
        self.assertEqual(expected_result,
                         self.target.create_export(ctxt,
                                                   self.testvol,
                                                   self.fake_volumes_dir))

        self.stubs.Set(self.target,
                       '_get_target_chap_auth',
                       lambda x, y: ('otzLy2UYbYfnP4zXLG5z',
                                     '234Zweo38VGBBvrpK9nt'))

        expected_result['auth'] = ('CHAP '
                                   'otzLy2UYbYfnP4zXLG5z 234Zweo38VGBBvrpK9nt')

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
        test_vol = 'iqn.2010-10.org.openstack:'\
                   'volume-83c2e877-feed-46be-8435-77884fe55b45'
        _mock_create.assert_called_once_with(
            test_vol,
            0, 1, self.fake_volumes_dir, ('foo', 'bar'),
            check_exit_code=False,
            old_name=None,
            portals_ips=[self.configuration.iscsi_ip_address],
            portals_port=self.configuration.iscsi_port)
