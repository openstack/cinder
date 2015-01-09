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

import mock
from oslo.utils import timeutils
from oslo_concurrency import processutils as putils

from cinder import context
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
        self.fake_id_1 = 'ed2c1fd4-5fc0-11e4-aa15-123b93f75cba'
        self.fake_id_2 = 'ed2c2222-5fc0-11e4-aa15-123b93f75cba'
        self.stubs.Set(self.configuration, 'safe_get', self.fake_safe_get)
        self.target = tgt.TgtAdm(root_helper=utils.get_root_helper(),
                                 configuration=self.configuration)
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

    def test_get_target_chap_auth(self):
        persist_file =\
            '<target iqn.2010-10.org.openstack:volume-83c2e877-feed-46be-8435-77884fe55b45>\n'\
            '    backing-store /dev/stack-volumes-lvmdriver-1/volume-83c2e877-feed-46be-8435-77884fe55b45\n'\
            '    lld iscsi\n'\
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
        expected = ('otzLy2UYbYfnP4zXLG5z', '234Zweo38VGBBvrpK9nt')
        self.assertEqual(expected, self.target._get_target_chap_auth(test_vol))

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

    def test_create_create_export(self):

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

        self.stubs.Set(vutils,
                       'generate_username',
                       lambda: 'QZJbisGmn9AL954FNF4D')
        self.stubs.Set(vutils,
                       'generate_password',
                       lambda: 'P68eE7u9eFqDGexd28DQ')

        expected_result = {'location': '10.9.8.7:3260,1 '
                           'iqn.2010-10.org.openstack:testvol 1',
                           'auth': 'CHAP '
                           'QZJbisGmn9AL954FNF4D P68eE7u9eFqDGexd28DQ'}

        ctxt = context.get_admin_context()
        self.assertEqual(expected_result,
                         self.target.create_export(ctxt,
                                                   self.testvol_1,
                                                   self.fake_volumes_dir))
