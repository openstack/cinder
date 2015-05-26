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
from cinder.tests.unit.targets import targets_fixture as tf
from cinder import utils
from cinder.volume.targets import lio


class TestLioAdmDriver(tf.TargetDriverFixture):

    def setUp(self):
        super(TestLioAdmDriver, self).setUp()

        with mock.patch.object(lio.LioAdm, '_verify_rtstool'):
            self.target = lio.LioAdm(root_helper=utils.get_root_helper(),
                                     configuration=self.configuration)
        self.target.db = mock.MagicMock(
            volume_get=lambda x, y: {'provider_auth': 'IncomingUser foo bar'})

    def test_get_target(self):
        with mock.patch('cinder.utils.execute',
                        return_value=(self.test_vol, None)):
            self.assertEqual(self.test_vol,
                             self.target._get_target(self.test_vol))

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
        self.assertEqual(('foo', 'bar'),
                         self.target._get_target_chap_auth(ctxt,
                                                           self.test_vol))

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch('cinder.utils.execute')
    @mock.patch.object(lio.LioAdm, '_get_target')
    def test_create_iscsi_target(self, mget_target, mexecute, mpersist_cfg):

        mget_target.return_value = 1
        # create_iscsi_target sends volume_name instead of volume_id on error
        self.assertEqual(
            1,
            self.target.create_iscsi_target(
                self.test_vol,
                1,
                0,
                self.fake_volumes_dir))
        mpersist_cfg.assert_called_once_with(self.volume_name)

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch('cinder.utils.execute',
                side_effect=putils.ProcessExecutionError)
    @mock.patch.object(lio.LioAdm, '_get_target')
    def test_create_iscsi_target_already_exists(self, mget_target, mexecute,
                                                mpersist_cfg):
        chap_auth = ('foo', 'bar')
        self.assertRaises(exception.ISCSITargetCreateFailed,
                          self.target.create_iscsi_target,
                          self.test_vol,
                          1,
                          0,
                          self.fake_volumes_dir,
                          chap_auth)
        self.assertEqual(0, mpersist_cfg.call_count)

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch('cinder.utils.execute')
    def test_remove_iscsi_target(self, mexecute, mpersist_cfg):
        # Test the normal case
        self.target.remove_iscsi_target(0,
                                        0,
                                        self.testvol['id'],
                                        self.testvol['name'])
        mexecute.assert_called_once_with('cinder-rtstool',
                                         'delete',
                                         self.iscsi_target_prefix +
                                         self.testvol['name'],
                                         run_as_root=True)

        mpersist_cfg.assert_called_once_with(self.fake_volume_id)

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

        _mock_create.assert_called_once_with(
            self.iscsi_target_prefix + 'testvol',
            0, 0, self.fake_volumes_dir, ('foo', 'bar'),
            check_exit_code=False,
            old_name=None)

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch('cinder.utils.execute')
    @mock.patch.object(lio.LioAdm, '_get_iscsi_properties')
    def test_initialize_connection(self, mock_get_iscsi, mock_execute,
                                   mpersist_cfg):
        target_id = self.iscsi_target_prefix + 'volume-' + self.fake_volume_id
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
            self.expected_iscsi_properties['auth_username'],
            '2FE0CQ8J196R', connector['initiator'],
            run_as_root=True)

        mpersist_cfg.assert_called_once_with(self.fake_volume_id)

        # Test the failure case: putils.ProcessExecutionError
        mock_execute.side_effect = putils.ProcessExecutionError
        self.assertRaises(exception.ISCSITargetAttachFailed,
                          self.target.initialize_connection,
                          self.testvol,
                          connector)

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch('cinder.utils.execute')
    def test_terminate_connection(self, _mock_execute, mpersist_cfg):

        target_id = self.iscsi_target_prefix + 'volume-' + self.fake_volume_id

        connector = {'initiator': 'fake_init'}
        self.target.terminate_connection(self.testvol,
                                         connector)
        _mock_execute.assert_called_once_with(
            'cinder-rtstool', 'delete-initiator', target_id,
            connector['initiator'],
            run_as_root=True)

        mpersist_cfg.assert_called_once_with(self.fake_volume_id)

    @mock.patch.object(lio.LioAdm, '_persist_configuration')
    @mock.patch('cinder.utils.execute')
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
