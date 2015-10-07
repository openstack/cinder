# Copyright (c) 2013 - 2015 EMC Corporation.
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
from six.moves import urllib

from cinder import exception
from cinder.tests.unit.volume.drivers.emc import scaleio


class TestMisc(scaleio.TestScaleIODriver):
    DOMAIN_NAME = 'PD1'
    POOL_NAME = 'SP1'
    STORAGE_POOLS = ['{}:{}'.format(DOMAIN_NAME, POOL_NAME)]

    def setUp(self):
        """Set up the test case environment.

        Defines the mock HTTPS responses for the REST API calls.
        """
        super(TestMisc, self).setUp()

        self.domain_name_enc = urllib.parse.quote(self.DOMAIN_NAME)
        self.pool_name_enc = urllib.parse.quote(self.POOL_NAME)

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Domain/instances/getByName::' +
                self.domain_name_enc: '"{}"'.format(self.DOMAIN_NAME).encode(
                    'ascii',
                    'ignore'
                ),
                'types/Pool/instances/getByName::{},{}'.format(
                    self.DOMAIN_NAME,
                    self.POOL_NAME
                ): '"{}"'.format(self.POOL_NAME).encode('ascii', 'ignore'),
                'types/StoragePool/instances/action/querySelectedStatistics': {
                    '"{}"'.format(self.POOL_NAME): {
                        'capacityInUseInKb': 502,
                        'capacityLimitInKb': 1024,
                    },
                },
            },
            self.RESPONSE_MODE.BadStatus: {
                'types/Domain/instances/getByName::' +
                self.domain_name_enc: self.BAD_STATUS_RESPONSE,
            },
            self.RESPONSE_MODE.Invalid: {
                'types/Domain/instances/getByName::' +
                self.domain_name_enc: None,
            },
        }

    def test_valid_configuration(self):
        self.driver.check_for_setup_error()

    def test_both_storage_pool(self):
        """Both storage name and ID provided."""
        self.driver.storage_pool_id = "test_pool_id"
        self.driver.storage_pool_name = "test_pool_name"
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)

    def test_no_storage_pool(self):
        """No storage name or ID provided."""
        self.driver.storage_pool_name = None
        self.driver.storage_pool_id = None
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)

    def test_both_domain(self):
        self.driver.protection_domain_name = "test_domain_name"
        self.driver.protection_domain_id = "test_domain_id"
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)

    def test_no_storage_pools(self):
        """No storage pools."""
        self.driver.storage_pools = None
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)

    def test_volume_size_round_true(self):
        self.driver._check_volume_size(1)

    def test_volume_size_round_false(self):
        self.driver.configuration.set_override('sio_round_volume_capacity',
                                               override=False)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._check_volume_size, 1)

    def test_get_volume_stats_bad_status(self):
        self.driver.storage_pools = self.STORAGE_POOLS
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.get_volume_stats, True)

    def test_get_volume_stats_invalid_domain(self):
        self.driver.storage_pools = self.STORAGE_POOLS
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.get_volume_stats, True)

    def test_get_volume_stats(self):
        self.driver.storage_pools = self.STORAGE_POOLS
        self.driver.get_volume_stats(True)
