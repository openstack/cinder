# Copyright (c) 2014 Clinton Knight.  All rights reserved.
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

from cinder import exception
from cinder import test
import cinder.tests.unit.volume.drivers.netapp.fakes as na_fakes
import cinder.volume.drivers.netapp.common as na_common
import cinder.volume.drivers.netapp.dataontap.fc_cmode as fc_cmode
import cinder.volume.drivers.netapp.utils as na_utils


class NetAppDriverFactoryTestCase(test.TestCase):

    def setUp(self):
        super(NetAppDriverFactoryTestCase, self).setUp()
        self.mock_object(na_common, 'LOG')

    def test_new(self):

        self.mock_object(na_utils.OpenStackInfo, 'info',
                         return_value='fake_info')
        mock_create_driver = self.mock_object(na_common.NetAppDriver,
                                              'create_driver')

        config = na_fakes.create_configuration()
        config.netapp_storage_family = 'fake_family'
        config.netapp_storage_protocol = 'fake_protocol'

        kwargs = {'configuration': config}
        na_common.NetAppDriver(**kwargs)

        kwargs['app_version'] = 'fake_info'
        mock_create_driver.assert_called_with('fake_family', 'fake_protocol',
                                              *(), **kwargs)

    def test_new_missing_config(self):

        self.mock_object(na_utils.OpenStackInfo, 'info')
        self.mock_object(na_common.NetAppDriver, 'create_driver')

        self.assertRaises(exception.InvalidInput, na_common.NetAppDriver, **{})

    def test_new_missing_family(self):

        self.mock_object(na_utils.OpenStackInfo, 'info')
        self.mock_object(na_common.NetAppDriver, 'create_driver')

        config = na_fakes.create_configuration()
        config.netapp_storage_protocol = 'fake_protocol'
        config.netapp_storage_family = None

        kwargs = {'configuration': config}
        self.assertRaises(exception.InvalidInput,
                          na_common.NetAppDriver,
                          **kwargs)

    def test_new_missing_protocol(self):

        self.mock_object(na_utils.OpenStackInfo, 'info')
        self.mock_object(na_common.NetAppDriver, 'create_driver')

        config = na_fakes.create_configuration()
        config.netapp_storage_family = 'fake_family'

        kwargs = {'configuration': config}
        self.assertRaises(exception.InvalidInput,
                          na_common.NetAppDriver,
                          **kwargs)

    def test_create_driver(self):

        def get_full_class_name(obj):
            return obj.__module__ + '.' + obj.__class__.__name__

        kwargs = {
            'configuration': na_fakes.create_configuration(),
            'app_version': 'fake_info',
            'host': 'fakehost@fakebackend',
        }

        registry = na_common.NETAPP_UNIFIED_DRIVER_REGISTRY

        for family in registry:
            for protocol, full_class_name in registry[family].items():
                driver = na_common.NetAppDriver.create_driver(
                    family, protocol, **kwargs)
                self.assertEqual(full_class_name, get_full_class_name(driver))

    def test_create_driver_case_insensitive(self):

        kwargs = {
            'configuration': na_fakes.create_configuration(),
            'app_version': 'fake_info',
            'host': 'fakehost@fakebackend',
        }

        driver = na_common.NetAppDriver.create_driver('ONTAP_CLUSTER', 'FC',
                                                      **kwargs)

        self.assertIsInstance(driver, fc_cmode.NetAppCmodeFibreChannelDriver)

    def test_create_driver_invalid_family(self):

        kwargs = {
            'configuration': na_fakes.create_configuration(),
            'app_version': 'fake_info',
            'host': 'fakehost@fakebackend',
        }

        self.assertRaises(exception.InvalidInput,
                          na_common.NetAppDriver.create_driver,
                          'kardashian', 'iscsi', **kwargs)

    def test_create_driver_invalid_protocol(self):

        kwargs = {
            'configuration': na_fakes.create_configuration(),
            'app_version': 'fake_info',
            'host': 'fakehost@fakebackend',
        }

        self.assertRaises(exception.InvalidInput,
                          na_common.NetAppDriver.create_driver,
                          'ontap_7mode', 'carrier_pigeon', **kwargs)
