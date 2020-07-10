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

import json
from unittest import mock

import ddt

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex
from cinder.tests.unit.volume.drivers.dell_emc.powerflex import mocks
from cinder.volume import configuration


@ddt.ddt
class TestMisc(powerflex.TestPowerFlexDriver):

    DOMAIN_ID = '1'
    POOL_ID = '1'

    def setUp(self):
        """Set up the test case environment.

        Defines the mock HTTPS responses for the REST API calls.
        """
        super(TestMisc, self).setUp()
        self.ctx = context.RequestContext('fake', 'fake', auth_token=True)

        self.volume = fake_volume.fake_volume_obj(
            self.ctx, **{'name': 'vol1', 'provider_id': fake.PROVIDER_ID}
        )
        self.new_volume = fake_volume.fake_volume_obj(
            self.ctx, **{'name': 'vol2', 'provider_id': fake.PROVIDER2_ID}
        )

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Domain/instances/getByName::{}'.format(
                    self.PROT_DOMAIN_NAME
                ): '"{}"'.format(self.PROT_DOMAIN_ID),
                'types/Pool/instances/getByName::{},{}'.format(
                    self.PROT_DOMAIN_ID,
                    self.STORAGE_POOL_NAME
                ): '"{}"'.format(self.STORAGE_POOL_ID),
                'types/StoragePool/instances/action/querySelectedStatistics': {
                    '"{}"'.format(self.STORAGE_POOL_NAME): {
                        'capacityAvailableForVolumeAllocationInKb': 5000000,
                        'capacityLimitInKb': 16000000,
                        'spareCapacityInKb': 6000000,
                        'thickCapacityInUseInKb': 266,
                        'thinCapacityAllocatedInKm': 0,
                        'snapCapacityInUseInKb': 266,
                    },
                },
                'instances/Volume::{}/action/setVolumeName'.format(
                    self.volume['provider_id']):
                        self.new_volume['provider_id'],
                'instances/Volume::{}/action/setVolumeName'.format(
                    self.new_volume['provider_id']):
                        self.volume['provider_id'],
                'version': '"{}"'.format('2.0.1'),
                'instances/StoragePool::{}'.format(
                    self.STORAGE_POOL_ID
                ): {
                    'name': self.STORAGE_POOL_NAME,
                    'id': self.STORAGE_POOL_ID,
                    'protectionDomainId': self.PROT_DOMAIN_ID,
                    'zeroPaddingEnabled': 'true',
                },
                'instances/ProtectionDomain::{}'.format(
                    self.PROT_DOMAIN_ID
                ): {
                    'name': self.PROT_DOMAIN_NAME,
                    'id': self.PROT_DOMAIN_ID
                },
            },
            self.RESPONSE_MODE.BadStatus: {
                'types/Domain/instances/getByName::' +
                self.PROT_DOMAIN_NAME: self.BAD_STATUS_RESPONSE,
                'instances/Volume::{}/action/setVolumeName'.format(
                    self.volume['provider_id']): mocks.MockHTTPSResponse(
                    {
                        'message': 'Invalid volume.',
                        'httpStatusCode': 400,
                        'errorCode': self.VOLUME_NOT_FOUND_ERROR
                    }, 400),
            },
            self.RESPONSE_MODE.Invalid: {
                'types/Domain/instances/getByName::' +
                self.PROT_DOMAIN_NAME: None,
                'instances/Volume::{}/action/setVolumeName'.format(
                    self.volume['provider_id']): mocks.MockHTTPSResponse(
                    {
                        'message': 'Invalid volume.',
                        'httpStatusCode': 400,
                        'errorCode': 0
                    }, 400),
            },
        }

    def test_valid_configuration(self):
        self.driver.storage_pools = self.STORAGE_POOLS
        self.driver.check_for_setup_error()

    def test_no_storage_pools(self):
        """No storage pools.

        INVALID Storage pools must be set
        """
        self.driver.storage_pools = None
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)

    def test_invalid_storage_pools(self):
        """Invalid storage pools data"""
        self.driver.storage_pools = "test"
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)

    def test_volume_size_round_true(self):
        self.driver._check_volume_size(1)

    def test_volume_size_round_false(self):
        self.override_config('powerflex_round_volume_capacity', False,
                             configuration.SHARED_CONF_GROUP)
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

    def _setup_valid_variant_property(self, property):
        """Setup valid response that returns a variety of property name

        """
        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.ValidVariant: {
                'types/Domain/instances/getByName::{}'.format(
                    self.PROT_DOMAIN_NAME
                ): '"{}"'.format(self.PROT_DOMAIN_ID),
                'types/Pool/instances/getByName::{},{}'.format(
                    self.PROT_DOMAIN_ID,
                    self.STORAGE_POOL_NAME
                ): '"{}"'.format(self.STORAGE_POOL_ID),
                'instances/ProtectionDomain::{}'.format(
                    self.PROT_DOMAIN_ID
                ): {
                    'name': self.PROT_DOMAIN_NAME,
                    'id': self.PROT_DOMAIN_ID
                },
                'instances/StoragePool::{}'.format(
                    self.STORAGE_POOL_ID
                ): {
                    'name': self.STORAGE_POOL_NAME,
                    'id': self.STORAGE_POOL_ID,
                    'protectionDomainId': self.PROT_DOMAIN_ID,
                    'zeroPaddingEnabled': 'true',
                },
                'types/StoragePool/instances/action/querySelectedStatistics': {
                    '"{}"'.format(self.STORAGE_POOL_NAME): {
                        'capacityAvailableForVolumeAllocationInKb': 5000000,
                        'capacityLimitInKb': 16000000,
                        'spareCapacityInKb': 6000000,
                        'thickCapacityInUseInKb': 266,
                        'snapCapacityInUseInKb': 266,
                        property: 0,
                    },
                },
                'instances/Volume::{}/action/setVolumeName'.format(
                    self.volume['provider_id']):
                        self.new_volume['provider_id'],
                'instances/Volume::{}/action/setVolumeName'.format(
                    self.new_volume['provider_id']):
                        self.volume['provider_id'],
                'version': '"{}"'.format('2.0.1'),
            }
        }

    def test_get_volume_stats_with_varying_properties(self):
        """Test getting volume stats with various property names

        In SIO 3.0, a property was renamed.
        The change is backwards compatible for now but this tests
        ensures that the driver is tolerant of that change
        """
        self.driver.storage_pools = self.STORAGE_POOLS
        self._setup_valid_variant_property("thinCapacityAllocatedInKb")
        self.set_https_response_mode(self.RESPONSE_MODE.ValidVariant)
        self.driver.get_volume_stats(True)
        self._setup_valid_variant_property("nonexistentProperty")
        self.set_https_response_mode(self.RESPONSE_MODE.ValidVariant)
        self.driver.get_volume_stats(True)

    @mock.patch(
        'cinder.volume.drivers.dell_emc.powerflex.rest_client.RestClient.'
        'rename_volume',
        return_value=None)
    def test_update_migrated_volume(self, mock_rename):
        test_vol = self.driver.update_migrated_volume(
            self.ctx, self.volume, self.new_volume, 'available')
        mock_rename.assert_called_with(self.new_volume, self.volume['id'])
        self.assertEqual({'_name_id': None, 'provider_location': None},
                         test_vol)

    @mock.patch(
        'cinder.volume.drivers.dell_emc.powerflex.rest_client.RestClient.'
        'rename_volume',
        return_value=None)
    def test_update_unavailable_migrated_volume(self, mock_rename):
        test_vol = self.driver.update_migrated_volume(
            self.ctx, self.volume, self.new_volume, 'unavailable')
        self.assertFalse(mock_rename.called)
        self.assertEqual({'_name_id': fake.VOLUME_ID,
                          'provider_location': None},
                         test_vol)

    @mock.patch(
        'cinder.volume.drivers.dell_emc.powerflex.rest_client.RestClient.'
        'rename_volume',
        side_effect=exception.VolumeBackendAPIException(data='Error!'))
    def test_fail_update_migrated_volume(self, mock_rename):
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.update_migrated_volume,
            self.ctx,
            self.volume,
            self.new_volume,
            'available'
        )
        mock_rename.assert_called_with(self.volume, "ff" + self.volume['id'])

    def test_rename_volume(self):
        rc = self.driver.primary_client.rename_volume(
            self.volume, self.new_volume['id'])
        self.assertIsNone(rc)

    def test_rename_volume_illegal_syntax(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        rc = self.driver.primary_client.rename_volume(
            self.volume, self.new_volume['id'])
        self.assertIsNone(rc)

    def test_rename_volume_non_sio(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        rc = self.driver.primary_client.rename_volume(
            self.volume, self.new_volume['id'])
        self.assertIsNone(rc)

    def test_default_provisioning_type_unspecified(self):
        empty_storage_type = {}
        provisioning, compression = (
            self.driver._get_provisioning_and_compression(
                empty_storage_type,
                self.PROT_DOMAIN_NAME,
                self.STORAGE_POOL_NAME)
        )
        self.assertEqual('ThinProvisioned', provisioning)

    @ddt.data((True, 'ThinProvisioned'), (False, 'ThickProvisioned'))
    @ddt.unpack
    def test_default_provisioning_type_thin(self, config_provisioning_type,
                                            expected_provisioning_type):
        self.override_config('san_thin_provision', config_provisioning_type,
                             configuration.SHARED_CONF_GROUP)
        self.driver = mocks.PowerFlexDriver(configuration=self.configuration)
        self.driver.do_setup({})
        self.driver.primary_client = mocks.PowerFlexClient(self.configuration)
        self.driver.primary_client.do_setup()
        empty_storage_type = {}
        provisioning, compression = (
            self.driver._get_provisioning_and_compression(
                empty_storage_type,
                self.PROT_DOMAIN_NAME,
                self.STORAGE_POOL_NAME)
        )
        self.assertEqual(expected_provisioning_type, provisioning)

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.rest_client.'
                'RestClient.query_rest_api_version',
                return_value="3.0")
    def test_get_volume_stats_v3(self, mock_version):
        self.driver.storage_pools = self.STORAGE_POOLS
        zero_data = {
            'types/StoragePool/instances/action/querySelectedStatistics':
                mocks.MockHTTPSResponse(content=json.dumps(
                    {'"{}"'.format(self.STORAGE_POOL_NAME): {
                        'snapCapacityInUseInKb': 0,
                        'thickCapacityInUseInKb': 0,
                        'netCapacityInUseInKb': 0,
                        'netUnusedCapacityInKb': 0,
                        'thinCapacityAllocatedInKb': 0}
                     }
                ))
        }
        with self.custom_response_mode(**zero_data):
            stats = self.driver.get_volume_stats(True)
            for s in ["total_capacity_gb",
                      "free_capacity_gb",
                      "provisioned_capacity_gb"]:
                self.assertEqual(0, stats[s])

        data = {
            'types/StoragePool/instances/action/querySelectedStatistics':
                mocks.MockHTTPSResponse(content=json.dumps(
                    {'"{}"'.format(self.STORAGE_POOL_NAME): {
                        'snapCapacityInUseInKb': 2097152,
                        'thickCapacityInUseInKb': 67108864,
                        'netCapacityInUseInKb': 34578432,
                        'netUnusedCapacityInKb': 102417408,
                        'thinCapacityAllocatedInKb': 218103808}
                     }
                ))
        }
        with self.custom_response_mode(**data):
            stats = self.driver.get_volume_stats(True)
            self.assertEqual(130, stats['total_capacity_gb'])
            self.assertEqual(97, stats['free_capacity_gb'])
            self.assertEqual(137, stats['provisioned_capacity_gb'])
