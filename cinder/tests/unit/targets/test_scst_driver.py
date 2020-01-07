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

from unittest import mock

from cinder import context
from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume.targets import scst
from cinder.volume import volume_utils


class TestSCSTAdmDriver(tf.TargetDriverFixture):

    def setUp(self):
        super(TestSCSTAdmDriver, self).setUp()
        self.target = scst.SCSTAdm(root_helper=utils.get_root_helper(),
                                   configuration=self.configuration)

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

    @mock.patch('cinder.privsep.targets.scst.run_scstadmin')
    def test_target_attribute(self, mock_privsep):
        mock_privsep.return_value = (self.fake_iscsi_attribute_scan, None)
        self.assertEqual(str(1), self.target._target_attribute(
            'iqn.2010-10.org.openstack:'
            'volume-ed2c2222-5fc0-11e4-aa15-123b93f75cba'))

    def test_single_lun_get_target_and_lun(self):
        ctxt = context.get_admin_context()
        self.assertEqual((0, 1), self.target._get_target_and_lun(
            ctxt, self.testvol))

    @mock.patch.object(utils, 'execute')
    @mock.patch.object(scst.SCSTAdm, '_get_group')
    @mock.patch.object(scst.SCSTAdm, 'scst_execute')
    def test_multi_lun_get_target_and_lun(self, mock_execute, mock_get_group,
                                          mock_scst_execute):
        mock_execute.return_value = (self.fake_list_group, None)
        mock_get_group.return_value = self.fake_list_group

        ctxt = context.get_admin_context()
        with mock.patch.object(self.target, 'target_name',
                               return_value='iqn.2010-10.org.openstack:'
                                            'volume-vedams'):
            self.assertEqual((0, 3), self.target._get_target_and_lun(
                ctxt, self.testvol))

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

        ctxt = context.get_admin_context()
        expected_result = {'location': '10.9.8.7:3260,1 '
                           'iqn.2010-10.org.openstack:'
                           'volume-ed2c2222-5fc0-11e4-aa15-123b93f75cba 1',
                           'auth': 'CHAP '
                           'QZJbisGmn9AL954FNF4D P68eE7u9eFqDGexd28DQ'}

        with mock.patch.object(self.target, '_get_target_and_lun',
                               side_effect=_fake_get_target_and_lun),\
                mock.patch.object(self.target, '_get_target_chap_auth',
                                  side_effect=_fake_get_target_chap_auth),\
                mock.patch.object(self.target, 'initiator_iqn',
                                  return_value='iqn.1993-08.org.debian:'
                                               '01:626bf14ebdc'),\
                mock.patch.object(self.target, '_iscsi_location',
                                  side_effect=_fake_iscsi_location),\
                mock.patch.object(self.target, 'target_driver',
                                  return_value='iscsi'),\
                mock.patch.object(volume_utils, 'generate_username',
                                  side_effect=lambda: 'QZJbisGmn9AL954FNF4D'),\
                mock.patch.object(volume_utils, 'generate_password',
                                  side_effect=lambda: 'P68eE7u9eFqDGexd28DQ'):
            self.assertEqual(expected_result,
                             self.target.create_export(ctxt,
                                                       self.testvol,
                                                       self.fake_volumes_dir))

    @mock.patch('cinder.utils.execute')
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

        with mock.patch.object(self.target, 'create_iscsi_target'),\
                mock.patch.object(self.target, '_get_target_chap_auth',
                                  side_effect=_fake_get_target_chap_auth),\
                mock.patch.object(self.target, '_get_target_and_lun',
                                  side_effect=_fake_get_target_and_lun):
            self.target.ensure_export(ctxt,
                                      self.testvol,
                                      self.fake_volumes_dir)
            self.target.create_iscsi_target.assert_called_once_with(
                'iqn.2010-10.org.openstack:testvol',
                'ed2c2222-5fc0-11e4-aa15-123b93f75cba',
                0, 1, self.fake_volumes_dir, _fake_get_target_chap_auth())

    @mock.patch('cinder.utils.execute')
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

        with mock.patch.object(self.target, 'create_iscsi_target'),\
                mock.patch.object(self.target, '_get_target_chap_auth',
                                  side_effect=_fake_get_target_chap_auth),\
                mock.patch.object(self.target, '_get_target_and_lun',
                                  side_effect=_fake_get_target_and_lun):
            self.target.ensure_export(ctxt,
                                      self.testvol,
                                      self.fake_volumes_dir)
            self.target.create_iscsi_target.assert_called_once_with(
                'iqn.2010-10.org.openstack:testvol',
                'ed2c2222-5fc0-11e4-aa15-123b93f75cba',
                0, 1, self.fake_volumes_dir, None)

    def test_iscsi_location(self):
        location = self.target._iscsi_location('portal', 1, 'target', 2)
        self.assertEqual('portal:3260,1 target 2', location)

    def test_iscsi_location_IPv6(self):
        ip = 'fd00:fd00:fd00:3000::12'
        location = self.target._iscsi_location(ip, 1, 'target', 2)
        self.assertEqual('[%s]:3260,1 target 2' % ip, location)

        ip = '[' + ip + ']'
        location = self.target._iscsi_location(ip, 1, 'target', 2)
        self.assertEqual(ip + ':3260,1 target 2', location)
