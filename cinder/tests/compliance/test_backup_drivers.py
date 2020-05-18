# Copyright 2016 Dell Inc.
# All Rights Reserved.
#
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
#

import ddt

from cinder.interface import backup_driver
from cinder.interface import util
from cinder.tests.unit import test

BACKUP_DRIVERS = util.get_backup_drivers()


@ddt.ddt
class TestBackupDrivers(test.TestCase):

    def test_backup_driver_decorator(self):
        """Sanity check on the decorator.

        The interface code is somewhat implicitly tested. We don't need unit
        tests for all of that code, but as a minimum we should make sure it
        returns at least one registered driver, else the compliance test will
        never even run.
        """
        self.assertGreater(len(BACKUP_DRIVERS), 0)

    @ddt.data(*BACKUP_DRIVERS)
    def test_backup_driver_compliance(self, driver):
        """Makes sure all backup drivers support the minimum requirements."""
        self.assertTrue(
            issubclass(driver.cls, backup_driver.BackupDriver),
            "Driver {} does not conform to minimum backup driver "
            "requirements!".format(driver.class_fqn))
