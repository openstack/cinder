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

import ddt
import mock
from oslo_config import cfg
from oslo_upgradecheck import upgradecheck as uc
import testtools

from cinder.cmd import status

CONF = cfg.CONF


@ddt.ddt
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

    def test_check_periodic_interval_default(self):
        # default value is 60
        self._set_config('periodic_interval', 60)
        result = self.checks._check_periodic_interval()
        self.assertEqual(uc.Code.SUCCESS, result.code)

    def test_check_periodic_interval_not_default(self):
        # default value is 60
        self._set_config('periodic_interval', 22)
        result = self.checks._check_periodic_interval()
        self.assertEqual(uc.Code.WARNING, result.code)
        self.assertIn('New configuration options have been introduced',
                      result.details)

    @ddt.data(['cinder.quota.DbQuotaDriver', True],
              ['cinder.quota.NestedDbQuotaDriver', False])
    @ddt.unpack
    def test_nested_quota_driver(self, driver, should_pass):
        self._set_config('quota_driver', driver)
        result = self.checks._check_nested_quota()
        if should_pass:
            expected = uc.Code.SUCCESS
        else:
            expected = uc.Code.WARNING
        self.assertEqual(expected, result.code)
