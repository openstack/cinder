# Copyright (c) 2016 EMC Corporation.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock

from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.dell_emc.vnx import driver


class TestVNXDriver(test.TestCase):
    def setUp(self):
        super(TestVNXDriver, self).setUp()
        self.configuration = conf.Configuration(None)
        self.fc_adapter_patcher = mock.patch(
            'cinder.volume.drivers.dell_emc.vnx.adapter.FCAdapter',
            autospec=True)
        self.fc_adapter_patcher.start()
        self.iscsi_adapter_patcher = mock.patch(
            'cinder.volume.drivers.dell_emc.vnx.adapter.ISCSIAdapter',
            autospec=True)
        self.iscsi_adapter_patcher.start()
        self.driver = None
        self.addCleanup(self.fc_adapter_patcher.stop)
        self.addCleanup(self.iscsi_adapter_patcher.stop)

    def _get_driver(self, protocol):
        self.configuration.storage_protocol = protocol
        drv = driver.VNXDriver(configuration=self.configuration,
                               active_backend_id=None)
        drv.do_setup(None)
        return drv

    def test_init_iscsi_driver(self):
        _driver = self._get_driver('iscsi')
        driver_name = str(_driver.adapter)
        self.assertIn('ISCSIAdapter', driver_name)
        self.assertEqual(driver.VNXDriver.VERSION, _driver.VERSION)

    def test_init_fc_driver(self):
        _driver = self._get_driver('FC')
        driver_name = str(_driver.adapter)
        self.assertIn('FCAdapter', driver_name)
        self.assertEqual(driver.VNXDriver.VERSION, _driver.VERSION)

    def test_create_volume(self):
        _driver = self._get_driver('iscsi')
        _driver.create_volume('fake_volume')
        _driver.adapter.create_volume.assert_called_once_with('fake_volume')

    def test_initialize_connection(self):
        _driver = self._get_driver('iscsi')
        _driver.initialize_connection('fake_volume', {'host': 'fake_host'})
        _driver.adapter.initialize_connection.assert_called_once_with(
            'fake_volume', {'host': 'fake_host'})

    def test_terminate_connection(self):
        _driver = self._get_driver('iscsi')
        _driver.terminate_connection('fake_volume', {'host': 'fake_host'})
        _driver.adapter.terminate_connection.assert_called_once_with(
            'fake_volume', {'host': 'fake_host'})

    def test_is_consistent_group_snapshot_enabled(self):
        _driver = self._get_driver('iscsi')
        _driver._stats = {'consistent_group_snapshot_enabled': True}
        self.assertTrue(_driver.is_consistent_group_snapshot_enabled())
        _driver._stats = {'consistent_group_snapshot_enabled': False}
        self.assertFalse(_driver.is_consistent_group_snapshot_enabled())
        self.assertFalse(_driver.is_consistent_group_snapshot_enabled())

    def test_enable_replication(self):
        _driver = self._get_driver('iscsi')
        _driver.enable_replication(None, 'group', 'volumes')

    def test_disable_replication(self):
        _driver = self._get_driver('iscsi')
        _driver.disable_replication(None, 'group', 'volumes')

    def test_failover_replication(self):
        _driver = self._get_driver('iscsi')
        _driver.failover_replication(None, 'group', 'volumes', 'backend_id')
