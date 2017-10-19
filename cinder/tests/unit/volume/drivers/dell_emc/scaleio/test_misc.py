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

import ddt
import mock
from six.moves import urllib

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import scaleio
from cinder.tests.unit.volume.drivers.dell_emc.scaleio import mocks
from cinder.volume import configuration


@ddt.ddt
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
        self.ctx = context.RequestContext('fake', 'fake', auth_token=True)

        self.volume = fake_volume.fake_volume_obj(
            self.ctx, **{'name': 'vol1', 'provider_id': fake.PROVIDER_ID}
        )
        self.new_volume = fake_volume.fake_volume_obj(
            self.ctx, **{'name': 'vol2', 'provider_id': fake.PROVIDER2_ID}
        )

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
                    "test_pool"
                ): {
                    'name': 'test_pool',
                    'protectionDomainId': 'test_domain',
                },
                'instances/ProtectionDomain::{}'.format(
                    "test_domain"
                ): {
                    'name': 'test_domain',
                },
            },
            self.RESPONSE_MODE.BadStatus: {
                'types/Domain/instances/getByName::' +
                self.domain_name_enc: self.BAD_STATUS_RESPONSE,
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
                self.domain_name_enc: None,
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
        self.driver.check_for_setup_error()

    def test_both_storage_pool(self):
        """Both storage name and ID provided.

        INVALID
        """
        self.driver.configuration.sio_storage_pool_id = "test_pool_id"
        self.driver.configuration.sio_storage_pool_name = "test_pool_name"
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)

    def test_no_storage_pool(self):
        """No storage name or ID provided.

        VALID as storage_pools are defined
        """
        self.driver.configuration.sio_storage_pool_name = None
        self.driver.configuration.sio_storage_pool_id = None
        self.driver.check_for_setup_error()

    def test_both_domain(self):
        """Both domain and ID are provided

        INVALID
        """
        self.driver.configuration.sio_protection_domain_name = (
            "test_domain_name")
        self.driver.configuration.sio_protection_domain_id = (
            "test_domain_id")
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)

    def test_no_storage_pools(self):
        """No storage pools.

        VALID as domain and storage pool names are provided
        """
        self.driver.storage_pools = None
        self.driver.check_for_setup_error()

    def test_volume_size_round_true(self):
        self.driver._check_volume_size(1)

    def test_volume_size_round_false(self):
        self.override_config('sio_round_volume_capacity', False,
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
                'instances/StoragePool::{}'.format(
                    self.STORAGE_POOL_NAME
                ): '"{}"'.format(self.STORAGE_POOL_ID),
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
        'cinder.volume.drivers.dell_emc.scaleio.driver.ScaleIODriver.'
        '_rename_volume',
        return_value=None)
    def test_update_migrated_volume(self, mock_rename):
        test_vol = self.driver.update_migrated_volume(
            self.ctx, self.volume, self.new_volume, 'available')
        mock_rename.assert_called_with(self.new_volume, self.volume['id'])
        self.assertEqual({'_name_id': None, 'provider_location': None},
                         test_vol)

    @mock.patch(
        'cinder.volume.drivers.dell_emc.scaleio.driver.ScaleIODriver.'
        '_rename_volume',
        return_value=None)
    def test_update_unavailable_migrated_volume(self, mock_rename):
        test_vol = self.driver.update_migrated_volume(
            self.ctx, self.volume, self.new_volume, 'unavailable')
        self.assertFalse(mock_rename.called)
        self.assertEqual({'_name_id': fake.VOLUME_ID,
                          'provider_location': None},
                         test_vol)

    @mock.patch(
        'cinder.volume.drivers.dell_emc.scaleio.driver.ScaleIODriver.'
        '_rename_volume',
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
        rc = self.driver._rename_volume(
            self.volume, self.new_volume['id'])
        self.assertIsNone(rc)

    def test_rename_volume_illegal_syntax(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        rc = self.driver._rename_volume(
            self.volume, self.new_volume['id'])
        self.assertIsNone(rc)

    def test_rename_volume_non_sio(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        rc = self.driver._rename_volume(
            self.volume, self.new_volume['id'])
        self.assertIsNone(rc)

    def test_default_provisioning_type_unspecified(self):
        empty_storage_type = {}
        self.assertEqual(
            'thin',
            self.driver._find_provisioning_type(empty_storage_type))

    @ddt.data((True, 'thin'), (False, 'thick'))
    @ddt.unpack
    def test_default_provisioning_type_thin(self, config_provisioning_type,
                                            expected_provisioning_type):
        self.override_config('san_thin_provision', config_provisioning_type,
                             configuration.SHARED_CONF_GROUP)
        self.driver = mocks.ScaleIODriver(configuration=self.configuration)
        empty_storage_type = {}
        self.assertEqual(
            expected_provisioning_type,
            self.driver._find_provisioning_type(empty_storage_type))
