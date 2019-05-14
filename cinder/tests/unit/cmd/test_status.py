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

from oslo_config import cfg
from oslo_upgradecheck import upgradecheck as uc
import testtools

from cinder.cmd import status

CONF = cfg.CONF


class TestCinderStatus(testtools.TestCase):
    """Test cases for the cinder-status upgrade check command."""

    def setUp(self):
        super(TestCinderStatus, self).setUp()
        self.checks = status.Checks()

    def _set_backup_driver(self, driver_path):
        CONF.set_override('backup_driver', driver_path)
        self.addCleanup(CONF.clear_override, 'backup_driver')

    def test_check_backup_module(self):
        self._set_backup_driver(
            'cinder.backup.drivers.swift.SwiftBackupDriver')
        result = self.checks._check_backup_module()
        self.assertEqual(uc.Code.SUCCESS, result.code)

    def test_check_backup_module_not_class(self):
        self._set_backup_driver('cinder.backup.drivers.swift')
        result = self.checks._check_backup_module()
        self.assertEqual(uc.Code.FAILURE, result.code)
        self.assertIn('requires the full path', result.details)
