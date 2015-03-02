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
from oslo_utils import timeutils

from cinder import context
from cinder import exception
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.targets import lio


class TestLioAdmDriver(test.TestCase):

    def setUp(self):
        super(TestLioAdmDriver, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.safe_get = mock.Mock(side_effect=self.fake_safe_get)
        self.configuration.iscsi_ip_address = '10.9.8.7'
        self.fake_volumes_dir = '/tmp/tmpfile'
        self.iscsi_target_prefix = 'iqn.2010-10.org.openstack:'
        self.fake_project_id = 'ed2c1fd4-5fc0-11e4-aa15-123b93f75cba'
        self.fake_volume_id = '83c2e877-feed-46be-8435-77884fe55b45'
        with mock.patch.object(lio.LioAdm, '_verify_rtstool'):
            self.target = lio.LioAdm(root_helper=utils.get_root_helper(),
                                     configuration=self.configuration)
        self.fake_iscsi_scan = ('iqn.2010-10.org.openstack:'
                                'volume-83c2e877-feed-46be-8435-77884fe55b45')
        self.target.db = mock.MagicMock(
            volume_get=lambda x, y: {'provider_auth': 'IncomingUser foo bar'})

        self.testvol =\
            {'project_id': self.fake_project_id,
             'name': 'volume-%s' % self.fake_volume_id,
             'size': 1,
             'id': self.fake_volume_id,
             'volume_type_id': None,
             'provider_location': '10.9.8.7:3260 '
                                  'iqn.2010-10.org.openstack:'
                                  'volume-%s 0' % self.fake_volume_id,
             'provider_auth': 'CHAP c76370d66b 2FE0CQ8J196R',
             'provider_geometry': '512 512',
             'created_at': timeutils.utcnow(),
             'host': 'fake_host@lvm#lvm'}

    def fake_safe_get(self, value):
        if value == 'volumes_dir':
            return self.fake_volumes_dir
        elif value == 'iscsi_protocol':
            return self.configuration.iscsi_protocol
        elif value == 'iscsi_target_prefix':
            return self.iscsi_target_prefix

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

    def test_get_iscsi_target(self):
        ctxt = context.get_admin_context()
        expected = 0
        self.assertEqual(expected,
                         self.target._get_iscsi_target(ctxt,
                                                       self.testvol['id']))

    def test_get_target_and_lun(self):
        lun = 0
        iscsi_target = 0
        ctxt = context.get_admin_context()
        expected = (iscsi_target, lun)
        self.assertEqual(expected,
                         self.target._get_target_and_lun(ctxt, self.testvol))

    def test_get_target_chap_auth(self):
        ctxt = context.get_admin_context()
        test_vol = 'iqn.2010-10.org.openstack:'\
                   'volume-83c2e877-feed-46be-8435-77884fe55b45'

        self.assertEqual(('foo', 'bar'),
                         self.target._get_target_chap_auth(ctxt, test_vol))

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(lio.LioAdm, '_get_target')
    def test_create_iscsi_target(self, mget_target, mexecute, mpersist_cfg):

        mget_target.return_value = 1
        # create_iscsi_target sends volume_name instead of volume_id on error
        volume_name = 'volume-83c2e877-feed-46be-8435-77884fe55b45'
        test_vol = 'iqn.2010-10.org.openstack:' + volume_name
        self.assertEqual(
            1,
            self.target.create_iscsi_target(
                test_vol,
                1,
                0,
                self.fake_volumes_dir))
        mpersist_cfg.assert_called_once_with(volume_name)

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(lio.LioAdm, '_get_target')
    def test_create_iscsi_target_already_exists(self, mget_target, mexecute,
                                                mpersist_cfg):
        mexecute.side_effect = putils.ProcessExecutionError

        test_vol = 'iqn.2010-10.org.openstack:'\
                   'volume-83c2e877-feed-46be-8435-77884fe55b45'
        chap_auth = ('foo', 'bar')
        self.assertRaises(exception.ISCSITargetCreateFailed,
                          self.target.create_iscsi_target,
                          test_vol,
                          1,
                          0,
                          self.fake_volumes_dir,
                          chap_auth)
        self.assertEqual(0, mpersist_cfg.call_count)

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch.object(utils, 'execute')
    def test_remove_iscsi_target(self, mexecute, mpersist_cfg):

        volume_id = '83c2e877-feed-46be-8435-77884fe55b45'
        test_vol = 'iqn.2010-10.org.openstack:volume-' + volume_id

        # Test the normal case
        self.target.remove_iscsi_target(0,
                                        0,
                                        self.testvol['id'],
                                        self.testvol['name'])
        mexecute.assert_called_once_with('cinder-rtstool',
                                         'delete',
                                         test_vol,
                                         run_as_root=True)

        mpersist_cfg.assert_called_once_with(volume_id)

        # Test the failure case: putils.ProcessExecutionError
        mexecute.side_effect = putils.ProcessExecutionError
        self.assertRaises(exception.ISCSITargetRemoveFailed,
                          self.target.remove_iscsi_target,
                          0,
                          0,
                          self.testvol['id'],
                          self.testvol['name'])

        # Ensure there have been no more calls to persist configuration
        self.assertEqual(1, mpersist_cfg.call_count)

    @mock.patch.object(lio.LioAdm, '_get_target_chap_auth')
    @mock.patch.object(lio.LioAdm, 'create_iscsi_target')
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
            0, 0, self.fake_volumes_dir, ('foo', 'bar'),
            check_exit_code=False,
            old_name=None)

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(lio.LioAdm, '_get_iscsi_properties')
    def test_initialize_connection(self, mock_get_iscsi, mock_execute,
                                   mpersist_cfg):
        volume_id = '83c2e877-feed-46be-8435-77884fe55b45'
        target_id = 'iqn.2010-10.org.openstack:volume-' + volume_id
        connector = {'initiator': 'fake_init'}

        # Test the normal case
        mock_get_iscsi.return_value = 'foo bar'
        expected_return = {'driver_volume_type': 'iscsi',
                           'data': 'foo bar'}
        self.assertEqual(expected_return,
                         self.target.initialize_connection(self.testvol,
                                                           connector))

        mock_execute.assert_called_once_with(
            'cinder-rtstool', 'add-initiator', target_id,
            'c76370d66b', '2FE0CQ8J196R',
            connector['initiator'],
            run_as_root=True)

        mpersist_cfg.assert_called_once_with(volume_id)

        # Test the failure case: putils.ProcessExecutionError
        mock_execute.side_effect = putils.ProcessExecutionError
        self.assertRaises(exception.ISCSITargetAttachFailed,
                          self.target.initialize_connection,
                          self.testvol,
                          connector)

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch.object(utils, 'execute')
    def test_terminate_connection(self, _mock_execute, mpersist_cfg):

        volume_id = '83c2e877-feed-46be-8435-77884fe55b45'
        target_id = 'iqn.2010-10.org.openstack:volume-' + volume_id

        connector = {'initiator': 'fake_init'}
        self.target.terminate_connection(self.testvol,
                                         connector)
        _mock_execute.assert_called_once_with(
            'cinder-rtstool', 'delete-initiator', target_id,
            connector['initiator'],
            run_as_root=True)

        mpersist_cfg.assert_called_once_with(volume_id)

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch.object(utils, 'execute')
    def test_terminate_connection_fail(self, _mock_execute, mpersist_cfg):

        _mock_execute.side_effect = putils.ProcessExecutionError
        connector = {'initiator': 'fake_init'}
        self.assertRaises(exception.ISCSITargetDetachFailed,
                          self.target.terminate_connection,
                          self.testvol,
                          connector)
        self.assertEqual(0, mpersist_cfg.call_count)

    def test_iscsi_protocol(self):
        self.assertEqual(self.target.iscsi_protocol, 'iscsi')
