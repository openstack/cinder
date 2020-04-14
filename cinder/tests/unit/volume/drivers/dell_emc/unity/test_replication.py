# Copyright (c) 2016 - 2019 Dell Inc. or its subsidiaries.
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

import unittest
from unittest import mock

import ddt

from cinder import exception
from cinder.volume import configuration as conf
from cinder.volume.drivers.dell_emc.unity import adapter as unity_adapter
from cinder.volume.drivers.dell_emc.unity import driver
from cinder.volume.drivers.dell_emc.unity import replication
from cinder.volume.drivers.san.san import san_opts


@ddt.ddt
class UnityReplicationTest(unittest.TestCase):
    @ddt.data({'version': '1.0.0', 'protocol': 'FC',
               'expected': unity_adapter.FCAdapter},
              {'version': '2.0.0', 'protocol': 'iSCSI',
               'expected': unity_adapter.ISCSIAdapter})
    @ddt.unpack
    def test_init_adapter(self, version, protocol, expected):
        a = replication.init_adapter(version, protocol)
        self.assertIsInstance(a, expected)
        self.assertEqual(version, a.version)


@ddt.ddt
class UnityReplicationDeviceTest(unittest.TestCase):
    def setUp(self):
        self.config = conf.Configuration(san_opts,
                                         config_group='unity-backend')
        self.config.san_ip = '1.1.1.1'
        self.config.san_login = 'user1'
        self.config.san_password = 'password1'
        self.driver = driver.UnityDriver(configuration=self.config)

        conf_dict = {'backend_id': 'secondary_unity', 'san_ip': '2.2.2.2'}
        self.mock_adapter = mock.MagicMock(is_setup=False)

        def mock_do_setup(*args):
            self.mock_adapter.is_setup = True

        self.mock_adapter.do_setup = mock.MagicMock(side_effect=mock_do_setup)
        with mock.patch('cinder.volume.drivers.dell_emc.unity.'
                        'replication.init_adapter',
                        return_value=self.mock_adapter):
            self.replication_device = replication.ReplicationDevice(
                conf_dict, self.driver)

    @ddt.data(
        {
            'conf_dict': {
                'backend_id': 'secondary_unity',
                'san_ip': '2.2.2.2'
            },
            'expected': [
                'secondary_unity', '2.2.2.2', 'user1', 'password1', 60
            ]
        },
        {
            'conf_dict': {
                'backend_id': 'secondary_unity',
                'san_ip': '2.2.2.2',
                'san_login': 'user2',
                'san_password': 'password2',
                'max_time_out_of_sync': 180
            },
            'expected': [
                'secondary_unity', '2.2.2.2', 'user2', 'password2', 180
            ]
        },
    )
    @ddt.unpack
    def test_init(self, conf_dict, expected):
        self.driver.configuration.replication_device = conf_dict
        device = replication.ReplicationDevice(conf_dict, self.driver)

        self.assertListEqual(
            [device.backend_id, device.san_ip, device.san_login,
             device.san_password, device.max_time_out_of_sync],
            expected)

        self.assertIs(self.driver, device.driver)

    @ddt.data(
        {
            'conf_dict': {'san_ip': '2.2.2.2'},
        },
        {
            'conf_dict': {'backend_id': '  ', 'san_ip': '2.2.2.2'},
        },
        {
            'conf_dict': {'backend_id': 'secondary_unity'},
        },
        {
            'conf_dict': {'backend_id': 'secondary_unity', 'san_ip': '  '},
        },
        {
            'conf_dict': {
                'backend_id': 'secondary_unity',
                'san_ip': '2.2.2.2',
                'san_login': 'user2',
                'san_password': 'password2',
                'max_time_out_of_sync': 'NOT_A_NUMBER'
            },
        },
    )
    @ddt.unpack
    def test_init_raise(self, conf_dict):
        self.driver.configuration.replication_device = conf_dict
        self.assertRaisesRegex(exception.InvalidConfigurationValue,
                               'Value .* is not valid for configuration '
                               'option "unity-backend.replication_device"',
                               replication.ReplicationDevice,
                               conf_dict, self.driver)

    @ddt.data(
        {
            'conf_dict': {
                'backend_id': 'secondary_unity',
                'san_ip': '2.2.2.2'
            },
            'expected': [
                '2.2.2.2', 'user1', 'password1'
            ]
        },
        {
            'conf_dict': {
                'backend_id': 'secondary_unity',
                'san_ip': '2.2.2.2',
                'san_login': 'user2',
                'san_password': 'password2',
                'max_time_out_of_sync': 180
            },
            'expected': [
                '2.2.2.2', 'user2', 'password2'
            ]
        },
    )
    @ddt.unpack
    def test_device_conf(self, conf_dict, expected):
        self.driver.configuration.replication_device = conf_dict
        device = replication.ReplicationDevice(conf_dict, self.driver)

        c = device.device_conf
        self.assertListEqual([c.san_ip, c.san_login, c.san_password],
                             expected)

    def test_setup_adapter(self):
        self.replication_device.setup_adapter()

        # Not call adapter.do_setup after initial setup done.
        self.replication_device.setup_adapter()

        self.mock_adapter.do_setup.assert_called_once()

    def test_setup_adapter_fail(self):
        def f(*args):
            raise exception.VolumeBackendAPIException('adapter setup failed')

        self.mock_adapter.do_setup = mock.MagicMock(side_effect=f)

        with self.assertRaises(exception.VolumeBackendAPIException):
            self.replication_device.setup_adapter()

    def test_adapter(self):
        self.assertIs(self.mock_adapter, self.replication_device.adapter)
        self.mock_adapter.do_setup.assert_called_once()

    def test_destination_pool(self):
        self.mock_adapter.storage_pools_map = {'pool-1': 'pool-1'}
        self.assertEqual('pool-1', self.replication_device.destination_pool)


@ddt.ddt
class UnityReplicationManagerTest(unittest.TestCase):
    def setUp(self):
        self.config = conf.Configuration(san_opts,
                                         config_group='unity-backend')
        self.config.san_ip = '1.1.1.1'
        self.config.san_login = 'user1'
        self.config.san_password = 'password1'
        self.config.replication_device = [
            {'backend_id': 'secondary_unity', 'san_ip': '2.2.2.2'}
        ]
        self.driver = driver.UnityDriver(configuration=self.config)

        self.replication_manager = replication.ReplicationManager()

    @mock.patch('cinder.volume.drivers.dell_emc.unity.'
                'replication.ReplicationDevice.setup_adapter')
    def test_do_setup(self, mock_setup_adapter):
        self.replication_manager.do_setup(self.driver)
        calls = [mock.call(), mock.call()]

        default_device = self.replication_manager.default_device
        self.assertEqual('1.1.1.1', default_device.san_ip)
        self.assertEqual('user1', default_device.san_login)
        self.assertEqual('password1', default_device.san_password)

        devices = self.replication_manager.replication_devices
        self.assertEqual(1, len(devices))
        self.assertIn('secondary_unity', devices)
        rep_device = devices['secondary_unity']
        self.assertEqual('2.2.2.2', rep_device.san_ip)
        self.assertEqual('user1', rep_device.san_login)
        self.assertEqual('password1', rep_device.san_password)

        self.assertTrue(self.replication_manager.is_replication_configured)

        self.assertTrue(
            self.replication_manager.active_backend_id is None
            or self.replication_manager.active_backend_id == 'default')

        self.assertFalse(self.replication_manager.is_service_failed_over)

        active_adapter = self.replication_manager.active_adapter
        calls.append(mock.call())
        self.assertIs(default_device.adapter, active_adapter)
        calls.append(mock.call())
        mock_setup_adapter.assert_has_calls(calls)

    @mock.patch('cinder.volume.drivers.dell_emc.unity.'
                'replication.ReplicationDevice.setup_adapter')
    def test_do_setup_replication_not_configured(self, mock_setup_adapter):
        self.driver.configuration.replication_device = None

        self.replication_manager.do_setup(self.driver)
        calls = [mock.call()]

        default_device = self.replication_manager.default_device
        self.assertEqual('1.1.1.1', default_device.san_ip)
        self.assertEqual('user1', default_device.san_login)
        self.assertEqual('password1', default_device.san_password)

        devices = self.replication_manager.replication_devices
        self.assertEqual(0, len(devices))

        self.assertFalse(self.replication_manager.is_replication_configured)

        self.assertTrue(
            self.replication_manager.active_backend_id is None
            or self.replication_manager.active_backend_id == 'default')

        self.assertFalse(self.replication_manager.is_service_failed_over)

        active_adapter = self.replication_manager.active_adapter
        calls.append(mock.call())
        self.assertIs(default_device.adapter, active_adapter)
        calls.append(mock.call())

        mock_setup_adapter.assert_has_calls(calls)

    @mock.patch('cinder.volume.drivers.dell_emc.unity.'
                'replication.ReplicationDevice.setup_adapter')
    def test_do_setup_failed_over(self, mock_setup_adapter):
        self.driver = driver.UnityDriver(configuration=self.config,
                                         active_backend_id='secondary_unity')

        self.replication_manager.do_setup(self.driver)
        calls = [mock.call()]

        default_device = self.replication_manager.default_device
        self.assertEqual('1.1.1.1', default_device.san_ip)
        self.assertEqual('user1', default_device.san_login)
        self.assertEqual('password1', default_device.san_password)

        devices = self.replication_manager.replication_devices
        self.assertEqual(1, len(devices))
        self.assertIn('secondary_unity', devices)
        rep_device = devices['secondary_unity']
        self.assertEqual('2.2.2.2', rep_device.san_ip)
        self.assertEqual('user1', rep_device.san_login)
        self.assertEqual('password1', rep_device.san_password)

        self.assertTrue(self.replication_manager.is_replication_configured)

        self.assertEqual('secondary_unity',
                         self.replication_manager.active_backend_id)

        self.assertTrue(self.replication_manager.is_service_failed_over)

        active_adapter = self.replication_manager.active_adapter
        calls.append(mock.call())
        self.assertIs(rep_device.adapter, active_adapter)
        calls.append(mock.call())

        mock_setup_adapter.assert_has_calls(calls)

    @ddt.data(
        {
            'rep_device': [{
                'backend_id': 'default', 'san_ip': '2.2.2.2'
            }]
        },
        {
            'rep_device': [{
                'backend_id': 'secondary_unity', 'san_ip': '2.2.2.2'
            }, {
                'backend_id': 'default', 'san_ip': '3.3.3.3'
            }]
        },
        {
            'rep_device': [{
                'backend_id': 'secondary_unity', 'san_ip': '2.2.2.2'
            }, {
                'backend_id': 'third_unity', 'san_ip': '3.3.3.3'
            }]
        },
    )
    @ddt.unpack
    @mock.patch('cinder.volume.drivers.dell_emc.unity.'
                'replication.ReplicationDevice.setup_adapter')
    def test_do_setup_raise_invalid_rep_device(self, mock_setup_adapter,
                                               rep_device):
        self.driver.configuration.replication_device = rep_device

        self.assertRaises(exception.InvalidConfigurationValue,
                          self.replication_manager.do_setup,
                          self.driver)

    @mock.patch('cinder.volume.drivers.dell_emc.unity.'
                'replication.ReplicationDevice.setup_adapter')
    def test_do_setup_raise_invalid_active_backend_id(self,
                                                      mock_setup_adapter):
        self.driver = driver.UnityDriver(configuration=self.config,
                                         active_backend_id='third_unity')

        self.assertRaises(exception.InvalidConfigurationValue,
                          self.replication_manager.do_setup,
                          self.driver)

    @mock.patch('cinder.volume.drivers.dell_emc.unity.'
                'replication.ReplicationDevice.setup_adapter')
    def test_failover_service(self, mock_setup_adapter):

        self.assertIsNone(self.replication_manager.active_backend_id)

        self.replication_manager.do_setup(self.driver)
        self.replication_manager.active_adapter

        self.assertEqual('default',
                         self.replication_manager.active_backend_id)

        self.replication_manager.failover_service('secondary_unity')
        self.assertEqual('secondary_unity',
                         self.replication_manager.active_backend_id)
