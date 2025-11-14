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
import urllib.parse

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex
from cinder.tests.unit.volume.drivers.dell_emc.powerflex import mocks
from cinder.volume import configuration
from cinder.volume.drivers.dell_emc.powerflex import options
from cinder.volume.drivers.dell_emc.powerflex import utils as flex_utils


class TestCreateClonedVolume(powerflex.TestPowerFlexDriver):
    """Test cases for ``PowerFlexDriver.create_cloned_volume()``"""
    def setUp(self):
        """Setup a test case environment.

        Creates fake volume objects and sets up the required API responses.
        """
        super(TestCreateClonedVolume, self).setUp()
        ctx = context.RequestContext('fake', 'fake', auth_token=True)

        self.src_volume = fake_volume.fake_volume_obj(
            ctx, **{'provider_id': fake.PROVIDER_ID})

        self.src_volume_name_2x_enc = urllib.parse.quote(
            urllib.parse.quote(
                flex_utils.id_to_base64(self.src_volume.id)
            )
        )

        self.new_volume_extras = {
            'volumeIdList': ['cloned'],
            'snapshotGroupId': 'cloned_snapshot'
        }

        self.new_volume = fake_volume.fake_volume_obj(
            ctx, **self.new_volume_extras
        )

        self.new_volume_name_2x_enc = urllib.parse.quote(
            urllib.parse.quote(
                flex_utils.id_to_base64(self.new_volume.id)
            )
        )
        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Volume/instances/getByName::' +
                self.src_volume_name_2x_enc: self.src_volume.id,
                'instances/System/action/snapshotVolumes': '{}'.format(
                    json.dumps(self.new_volume_extras)),
                'instances/Volume::cloned/action/setVolumeSize': None
            },
            self.RESPONSE_MODE.BadStatus: {
                'instances/System/action/snapshotVolumes':
                    self.BAD_STATUS_RESPONSE,
                'types/Volume/instances/getByName::' +
                    self.src_volume['provider_id']: self.BAD_STATUS_RESPONSE,
            },
            self.RESPONSE_MODE.Invalid: {
                'types/Volume/instances/getByName::' +
                    self.src_volume_name_2x_enc: None,
                'instances/System/action/snapshotVolumes':
                    mocks.MockHTTPSResponse(
                        {
                            'errorCode': 400,
                            'message': 'Invalid Volume Snapshot Test'
                        }, 400
                    ),
            },
        }

    def test_bad_login(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.new_volume, self.src_volume)

    def test_invalid_source_volume(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.new_volume, self.src_volume)

    def test_create_cloned_volume(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        self.driver.create_cloned_volume(self.new_volume, self.src_volume)

    def test_create_cloned_volume_larger_size(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        self.new_volume.size = 2
        self.driver.create_cloned_volume(self.new_volume, self.src_volume)

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._create_volume_from_source')
    def test_create_cloned_volume_not_image_cache(self, mock_create):
        """Test cloning when source volume is not an image cache entry."""
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        mock_create.return_value = {}

        # Mock volume_utils to indicate source volume is not an image cache
        # entry
        with mock.patch('cinder.volume.volume_utils.is_image_cache_entry',
                        return_value=False):
            self.driver.create_cloned_volume(self.new_volume, self.src_volume)

        # Should proceed directly to _create_volume_from_source
        mock_create.assert_called_once_with(self.new_volume, self.src_volume)

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._create_volume_from_source')
    def test_create_cloned_volume_image_cache_clone_limit_disabled(
            self, mock_create):
        """Test cloning when clone limit is disabled (set to 0)."""
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        mock_create.return_value = {}

        # Set clone limit to 0 (disabled)
        self.override_config(options.POWERFLEX_MAX_IMAGE_CACHE_VTREE_SIZE, 0,
                             configuration.SHARED_CONF_GROUP)

        # Mock volume_utils to indicate source volume is an image cache entry
        with mock.patch('cinder.volume.volume_utils.is_image_cache_entry',
                        return_value=True):
            self.driver.create_cloned_volume(self.new_volume, self.src_volume)

        # Should proceed directly to _create_volume_from_source
        mock_create.assert_called_once_with(self.new_volume, self.src_volume)

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._create_volume_from_source')
    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._get_client')
    def test_create_cloned_volume_image_cache_within_limit(self, mock_client,
                                                           mock_create):
        """Test cloning image cache volume when within clone limit."""
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        mock_create.return_value = {}

        # Set clone limit to 20
        self.override_config(options.POWERFLEX_MAX_IMAGE_CACHE_VTREE_SIZE, 20,
                             configuration.SHARED_CONF_GROUP)

        # Mock REST client and vtree statistics response
        mock_rest_client = mock.Mock()
        mock_client.return_value = mock_rest_client
        mock_rest_client.query_volume.return_value = {
            'vtreeId': 'test_vtree_id'
        }
        mock_rest_client.query_vtree_statistics.return_value = {
            'numOfVolumes': '10'  # Within limit
        }

        # Mock volume_utils to indicate source volume is an image cache entry
        with mock.patch('cinder.volume.volume_utils.is_image_cache_entry',
                        return_value=True):
            self.driver.create_cloned_volume(self.new_volume, self.src_volume)

        # Should query volume and vtree statistics and proceed to create
        mock_rest_client.query_volume.assert_called_once_with(
            self.src_volume.provider_id)
        mock_rest_client.query_vtree_statistics.assert_called_once_with(
            'test_vtree_id')
        mock_create.assert_called_once_with(self.new_volume, self.src_volume)

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._get_client')
    def test_create_cloned_volume_image_cache_limit_reached(self, mock_client):
        """Test cloning image cache volume when clone limit is reached."""
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)

        # Set clone limit to 20
        self.override_config(options.POWERFLEX_MAX_IMAGE_CACHE_VTREE_SIZE, 20,
                             configuration.SHARED_CONF_GROUP)

        # Mock REST client and vtree statistics response
        mock_rest_client = mock.Mock()
        mock_client.return_value = mock_rest_client
        mock_rest_client.query_volume.return_value = {
            'vtreeId': 'test_vtree_id'
        }
        mock_rest_client.query_vtree_statistics.return_value = {
            'numOfVolumes': '20'  # At limit
        }

        # Mock volume_utils to indicate source volume is an image cache entry
        with mock.patch('cinder.volume.volume_utils.is_image_cache_entry',
                        return_value=True):
            self.assertRaises(exception.SnapshotLimitReached,
                              self.driver.create_cloned_volume,
                              self.new_volume, self.src_volume)

        # Should query volume and vtree statistics but fail before create
        mock_rest_client.query_volume.assert_called_once_with(
            self.src_volume.provider_id)
        mock_rest_client.query_vtree_statistics.assert_called_once_with(
            'test_vtree_id')

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._create_volume_from_source')
    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._get_client')
    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.LOG')
    def test_create_cloned_volume_image_cache_stats_query_fails(
            self, mock_log, mock_client, mock_create):
        """Test cloning when volume statistics query fails."""
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        mock_create.return_value = {}

        # Set clone limit to 20
        self.override_config(options.POWERFLEX_MAX_IMAGE_CACHE_VTREE_SIZE, 20,
                             configuration.SHARED_CONF_GROUP)

        # Mock REST client to raise exception on query_volume
        mock_rest_client = mock.Mock()
        mock_client.return_value = mock_rest_client
        mock_rest_client.query_volume.side_effect = (
            exception.VolumeBackendAPIException(data="Query failed"))

        # Mock volume_utils to indicate source volume is an image cache entry
        with mock.patch('cinder.volume.volume_utils.is_image_cache_entry',
                        return_value=True):
            self.driver.create_cloned_volume(self.new_volume, self.src_volume)

        # Should attempt query, log warning, and proceed to create
        mock_rest_client.query_volume.assert_called_once_with(
            self.src_volume.provider_id)
        mock_log.warning.assert_called_once()
        mock_create.assert_called_once_with(self.new_volume, self.src_volume)

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._create_volume_from_source')
    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._get_client')
    def test_create_cloned_volume_image_cache_missing_stats_field(
            self, mock_client, mock_create):
        """Test cloning when statistics response missing expected field."""
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        mock_create.return_value = {}

        # Set clone limit to 20
        self.override_config(options.POWERFLEX_MAX_IMAGE_CACHE_VTREE_SIZE, 20,
                             configuration.SHARED_CONF_GROUP)

        # Mock REST client with response missing numOfVolumes
        mock_rest_client = mock.Mock()
        mock_client.return_value = mock_rest_client
        mock_rest_client.query_volume.return_value = {
            'vtreeId': 'test_vtree_id'
        }
        mock_rest_client.query_vtree_statistics.return_value = {
            'otherField': 'value'  # Missing numOfVolumes
        }

        # Mock volume_utils to indicate source volume is an image cache entry
        with mock.patch('cinder.volume.volume_utils.is_image_cache_entry',
                        return_value=True):
            self.driver.create_cloned_volume(self.new_volume, self.src_volume)

        # Should query volume and vtree statistics, default to 0, proceed
        mock_rest_client.query_volume.assert_called_once_with(
            self.src_volume.provider_id)
        mock_rest_client.query_vtree_statistics.assert_called_once_with(
            'test_vtree_id')
        mock_create.assert_called_once_with(self.new_volume, self.src_volume)
