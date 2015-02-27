#    (c) Copyright 2014 Brocade Communications Systems Inc.
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


"""Unit tests for FC Zone Manager."""

import mock

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.zonemanager.drivers import fc_zone_driver
from cinder.zonemanager import fc_zone_manager

fabric_name = 'BRCD_FAB_3'
init_target_map = {'10008c7cff523b01': ['20240002ac000a50']}
fabric_map = {'BRCD_FAB_3': ['20240002ac000a50']}
target_list = ['20240002ac000a50']


class TestFCZoneManager(test.TestCase):

    @mock.patch('oslo_config.cfg._is_opt_registered', return_value=False)
    def setUp(self, opt_mock):
        super(TestFCZoneManager, self).setUp()
        config = conf.Configuration(None)
        config.fc_fabric_names = fabric_name

        def fake_build_driver(self):
            self.driver = mock.Mock(fc_zone_driver.FCZoneDriver)

        self.stubs.Set(fc_zone_manager.ZoneManager, '_build_driver',
                       fake_build_driver)

        self.zm = fc_zone_manager.ZoneManager(configuration=config)
        self.configuration = conf.Configuration(None)
        self.configuration.fc_fabric_names = fabric_name
        self.driver = mock.Mock(fc_zone_driver.FCZoneDriver)

    def __init__(self, *args, **kwargs):
        super(TestFCZoneManager, self).__init__(*args, **kwargs)

    @mock.patch('oslo_config.cfg._is_opt_registered', return_value=False)
    def test_add_connection(self, opt_mock):
        with mock.patch.object(self.zm.driver, 'add_connection')\
                as add_connection_mock:
            self.zm.driver.get_san_context.return_value = fabric_map
            self.zm.add_connection(init_target_map)
            self.zm.driver.get_san_context.assert_called_once_with(target_list)
            add_connection_mock.assert_called_once_with(fabric_name,
                                                        init_target_map)

    @mock.patch('oslo_config.cfg._is_opt_registered', return_value=False)
    def test_add_connection_error(self, opt_mock):
        with mock.patch.object(self.zm.driver, 'add_connection')\
                as add_connection_mock:
            add_connection_mock.side_effect = exception.FCZoneDriverException
            self.assertRaises(exception.ZoneManagerException,
                              self.zm.add_connection, init_target_map)

    @mock.patch('oslo_config.cfg._is_opt_registered', return_value=False)
    def test_delete_connection(self, opt_mock):
        with mock.patch.object(self.zm.driver, 'delete_connection')\
                as delete_connection_mock:
            self.zm.driver.get_san_context.return_value = fabric_map
            self.zm.delete_connection(init_target_map)
            self.zm.driver.get_san_context.assert_called_once_with(target_list)
            delete_connection_mock.assert_called_once_with(fabric_name,
                                                           init_target_map)

    @mock.patch('oslo_config.cfg._is_opt_registered', return_value=False)
    def test_delete_connection_error(self, opt_mock):
        with mock.patch.object(self.zm.driver, 'delete_connection')\
                as del_connection_mock:
            del_connection_mock.side_effect = exception.FCZoneDriverException
            self.assertRaises(exception.ZoneManagerException,
                              self.zm.delete_connection, init_target_map)
