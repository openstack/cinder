# Copyright (c) 2019, Red Hat, Inc.
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

from unittest import mock

from cinder.interface import util
from cinder.tests.unit import test


class GetDriversTestCase(test.TestCase):
    def test_get_volume_drivers(self):
        # Just ensure that it doesn't raise an exception
        drivers = util.get_volume_drivers()
        self.assertNotEqual(0, len(drivers))
        for driver in drivers:
            self.assertIsInstance(driver, util.DriverInfo)

    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.get_driver_options')
    def test_get_volume_drivers_fail(self, driver_opt):
        driver_opt.side_effect = ValueError
        self.assertRaises(ValueError, util.get_volume_drivers)

    def test_get_backup_drivers(self):
        # Just ensure that it doesn't raise an exception
        drivers = util.get_backup_drivers()
        self.assertNotEqual(0, len(drivers))
        for driver in drivers:
            self.assertIsInstance(driver, util.DriverInfo)

    @mock.patch('cinder.backup.drivers.ceph.CephBackupDriver.'
                'get_driver_options')
    def test_get_backup_drivers_fail(self, driver_opt):
        driver_opt.side_effect = ValueError
        self.assertRaises(ValueError, util.get_backup_drivers)

    def test_get_fczm_drivers(self):
        # Just ensure that it doesn't raise an exception
        drivers = util.get_fczm_drivers()
        self.assertNotEqual(0, len(drivers))
        for driver in drivers:
            self.assertIsInstance(driver, util.DriverInfo)

    @mock.patch('cinder.zonemanager.drivers.cisco.cisco_fc_zone_driver.'
                'CiscoFCZoneDriver.get_driver_options')
    def test_get_fczm_drivers_fail(self, driver_opt):
        driver_opt.side_effect = ValueError
        self.assertRaises(ValueError, util.get_fczm_drivers)
