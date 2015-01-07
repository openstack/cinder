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
from oslo_concurrency import processutils as putils

from cinder import context
from cinder import exception
from cinder.tests.targets import test_tgt_driver as test_tgt
from cinder import utils
from cinder.volume.targets import lio


class TestLioAdmDriver(test_tgt.TestTgtAdmDriver):

    def setUp(self):
        super(TestLioAdmDriver, self).setUp()
        self.target = lio.LioAdm(root_helper=utils.get_root_helper(),
                                 configuration=self.configuration)
        self.fake_iscsi_scan = ('iqn.2010-10.org.openstack:'
                                'volume-83c2e877-feed-46be-8435-77884fe55b45')
        self.target.db = mock.MagicMock(
            volume_get=lambda x, y: {'provider_auth': 'IncomingUser foo bar'})

    def test_get_target(self):

        def _fake_execute(*args, **kwargs):
            return self.fake_iscsi_scan, None

        self.stubs.Set(utils,
                       'execute',
                       _fake_execute)

        self.assertEqual('iqn.2010-10.org.openstack:'
                         'volume-83c2e877-feed-46be-8435-77884fe55b45',
                         self.target._get_target('iqn.2010-10.org.openstack:'
                                                 'volume-83c2e877-feed-46be-'
                                                 '8435-77884fe55b45'))

    def test_verify_backing_lun(self):
        pass

    def test_get_target_chap_auth(self):
        pass

    def test_create_iscsi_target_already_exists(self):
        def _fake_execute(*args, **kwargs):
            raise putils.ProcessExecutionError(exit_code=1)

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
        chap_auth = 'chap foo bar'
        self.assertRaises(exception.ISCSITargetCreateFailed,
                          self.target.create_iscsi_target,
                          test_vol,
                          1,
                          0,
                          self.fake_volumes_dir,
                          chap_auth)

    @mock.patch.object(lio.LioAdm, 'create_iscsi_target')
    def test_ensure_export(self, _mock_create):

        ctxt = context.get_admin_context()
        self.target.ensure_export(ctxt,
                                  self.testvol_1,
                                  self.fake_volumes_dir)
        self.target.create_iscsi_target.assert_called_once_with(
            'iqn.2010-10.org.openstack:testvol',
            1, 0, self.fake_volumes_dir, 'IncomingUser foo bar',
            check_exit_code=False)
