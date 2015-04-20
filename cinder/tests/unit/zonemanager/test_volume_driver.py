#    (c) Copyright 2012-2014 Hewlett-Packard Development Company, L.P.
#    All Rights Reserved.
#
#    Copyright 2014 OpenStack Foundation
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


"""Unit tests for Volume Manager."""

import mock

from cinder import test
from cinder.tests.unit import fake_driver
from cinder import utils
from cinder.volume import configuration as conf
from cinder.zonemanager.drivers.brocade import brcd_fc_zone_driver
from cinder.zonemanager import fc_zone_manager


class TestVolumeDriver(test.TestCase):

    def setUp(self):
        super(TestVolumeDriver, self).setUp()
        self.driver = fake_driver.FakeFibreChannelDriver()
        brcd_fc_zone_driver.BrcdFCZoneDriver = mock.Mock()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.driver = None

    def __init__(self, *args, **kwargs):
        super(TestVolumeDriver, self).__init__(*args, **kwargs)

    @mock.patch('oslo_config.cfg._is_opt_registered', return_value=False)
    @mock.patch.object(utils, 'require_driver_initialized')
    def test_initialize_connection_with_decorator(self, utils_mock, opt_mock):
        utils_mock.return_value = True
        with mock.patch.object(fc_zone_manager.ZoneManager, 'add_connection')\
                as add_zone_mock:
            with mock.patch.object(conf.Configuration, 'safe_get')\
                    as mock_safe_get:
                mock_safe_get.return_value = 'fabric'
                conn_info = self.driver.initialize_connection(None, None)
                init_target_map = conn_info['data']['initiator_target_map']
                add_zone_mock.assert_called_once_with(init_target_map)

    @mock.patch.object(utils, 'require_driver_initialized')
    def test_initialize_connection_no_decorator(self, utils_mock):
        utils_mock.return_value = True
        with mock.patch.object(fc_zone_manager.ZoneManager, 'add_connection')\
                as add_zone_mock:
            with mock.patch.object(conf.Configuration, 'safe_get')\
                    as mock_safe_get:
                mock_safe_get.return_value = 'fabric'
                self.driver.no_zone_initialize_connection(None, None)
                assert not add_zone_mock.called

    @mock.patch('oslo_config.cfg._is_opt_registered', return_value=False)
    @mock.patch.object(utils, 'require_driver_initialized')
    def test_terminate_connection_with_decorator(self, utils_mock, opt_mock):
        utils_mock.return_value = True
        with mock.patch.object(fc_zone_manager.ZoneManager,
                               'delete_connection') as remove_zone_mock:
            with mock.patch.object(conf.Configuration, 'safe_get')\
                    as mock_safe_get:
                mock_safe_get.return_value = 'fabric'
                conn_info = self.driver.terminate_connection(None, None)
                init_target_map = conn_info['data']['initiator_target_map']
                remove_zone_mock.assert_called_once_with(init_target_map)

    @mock.patch.object(utils, 'require_driver_initialized')
    def test_terminate_connection_no_decorator(self, utils_mock):
        utils_mock.return_value = True
        with mock.patch.object(fc_zone_manager.ZoneManager,
                               'delete_connection') as remove_zone_mock:
            with mock.patch.object(conf.Configuration, 'safe_get')\
                    as mock_safe_get:
                mock_safe_get.return_value = 'fabric'
                self.driver.no_zone_terminate_connection(None, None)
                assert not remove_zone_mock.called
