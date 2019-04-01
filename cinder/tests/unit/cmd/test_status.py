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

"""Unit tests for the cinder-status CLI interfaces."""

import mock
from oslo_config import cfg
from oslo_upgradecheck import upgradecheck as uc
import testtools

from cinder.cmd import status

import cinder.volume.manager as volume_manager

CONF = cfg.CONF


class TestCinderStatus(testtools.TestCase):
    """Test cases for the cinder-status upgrade check command."""

    def setUp(self):
        super(TestCinderStatus, self).setUp()
        self.checks = status.Checks()

        # Make sure configuration is initialized
        try:
            CONF([], project='cinder')
        except cfg.RequiredOptError:
            # Doesn't matter in this situation
            pass

        # Make sure our expected path is returned
        patcher = mock.patch.object(CONF, 'find_file')
        self.addCleanup(patcher.stop)
        self.find_file = patcher.start()
        self.find_file.return_value = '/etc/cinder/'

    def _set_config(self, key, value, group=None):
        CONF.set_override(key, value, group=group)
        self.addCleanup(CONF.clear_override, key, group=group)

    def _set_volume_driver(self, volume_driver, enabled_backend):
        CONF.register_opts(volume_manager.volume_backend_opts,
                           group=enabled_backend)
        CONF.set_override('enabled_backends', enabled_backend)
        CONF.set_override('volume_driver', volume_driver,
                          group=enabled_backend)
        self.addCleanup(CONF.clear_override, 'volume_driver',
                        group=enabled_backend)
        self.addCleanup(CONF.clear_override, 'enabled_backends')

    def test_check_backup_module(self):
        self._set_config(
            'backup_driver',
            'cinder.backup.drivers.swift.SwiftBackupDriver')
        result = self.checks._check_backup_module()
        self.assertEqual(uc.Code.SUCCESS, result.code)

    def test_check_backup_module_not_class(self):
        self._set_config('backup_driver', 'cinder.backup.drivers.swift')
        result = self.checks._check_backup_module()
        self.assertEqual(uc.Code.FAILURE, result.code)
        self.assertIn('requires the full path', result.details)

    def test_check_policy_file(self):
        with mock.patch.object(self.checks, '_file_exists') as fe:
            fe.return_value = False
            result = self.checks._check_policy_file()

        self.assertEqual(uc.Code.SUCCESS, result.code)

    def test_check_policy_file_exists(self):
        with mock.patch.object(self.checks, '_file_exists') as fe:
            fe.return_value = True
            result = self.checks._check_policy_file()

        self.assertEqual(uc.Code.WARNING, result.code)
        self.assertIn('policy.json file is present', result.details)

    def test_check_policy_file_custom_path(self):
        policy_path = '/my/awesome/configs/policy.yaml'
        self._set_config('policy_file', policy_path, group='oslo_policy')
        with mock.patch.object(self.checks, '_file_exists') as fe:
            fe.return_value = False
            result = self.checks._check_policy_file()
            fe.assert_called_with(policy_path)

        self.assertEqual(uc.Code.WARNING, result.code)
        self.assertIn(policy_path, result.details)

    def test_check_policy_file_custom_file(self):
        policy_path = 'mypolicy.yaml'
        self._set_config('policy_file', policy_path, group='oslo_policy')
        with mock.patch.object(self.checks, '_file_exists') as fe:
            fe.return_value = False
            result = self.checks._check_policy_file()
            fe.assert_called_with('/etc/cinder/%s' % policy_path)

        self.assertEqual(uc.Code.WARNING, result.code)
        self.assertIn(policy_path, result.details)

    def test_check_legacy_win_conf_fail(self):
        self._set_volume_driver(
            'cinder.volume.drivers.windows.windows.WindowsDriver',
            'winiscsi')
        result = self.checks._check_legacy_windows_config()
        self.assertEqual(uc.Code.FAILURE, result.code)
        self.assertIn('Please update to use', result.details)

    def test_check_legacy_win_conf_no_drivers(self):
        self._set_config('enabled_backends', None)
        result = self.checks._check_legacy_windows_config()
        self.assertEqual(uc.Code.SUCCESS, result.code)
