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

    def _test_create_cloned_volume_image_cache(self, vtree_volumes,
                                               expect_raises,
                                               max_size=20,
                                               vtree_id='test_vtree_id'):
        """Helper for image cache vTree clone limit tests.

        Sets up mocks for query_volume and query_vtree_volumes, then
        calls create_cloned_volume and verifies the expected outcome.

        :param vtree_volumes: list of volume dicts for query_vtree_volumes
        :param expect_raises: True if SnapshotLimitReached should be raised
        :param max_size: powerflex_max_image_cache_vtree_size config value
        :param vtree_id: vtree ID returned by query_volume
        """
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        self.override_config(options.POWERFLEX_MAX_IMAGE_CACHE_VTREE_SIZE,
                             max_size, configuration.SHARED_CONF_GROUP)

        with mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                        'PowerFlexDriver._get_client') as mock_client, \
             mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                        'PowerFlexDriver._create_volume_from_source'
                        ) as mock_create:
            mock_create.return_value = {}
            mock_rest_client = mock.Mock()
            mock_client.return_value = mock_rest_client
            mock_rest_client.query_volume.return_value = {
                'vtreeId': vtree_id
            }
            mock_rest_client.query_vtree_volumes.return_value = vtree_volumes

            with mock.patch(
                    'cinder.volume.volume_utils.is_image_cache_entry',
                    return_value=True):
                if expect_raises:
                    self.assertRaises(
                        exception.SnapshotLimitReached,
                        self.driver.create_cloned_volume,
                        self.new_volume, self.src_volume)
                else:
                    self.driver.create_cloned_volume(self.new_volume,
                                                     self.src_volume)

            mock_rest_client.query_volume.assert_called_once_with(
                self.src_volume.provider_id)
            mock_rest_client.query_vtree_volumes.assert_called_once_with(
                vtree_id)
            if expect_raises:
                mock_create.assert_not_called()
            else:
                mock_create.assert_called_once_with(self.new_volume,
                                                    self.src_volume)

    def test_create_cloned_volume_image_cache_within_limit(self):
        """Test cloning image cache volume when within clone limit.

        10 direct children with max_size=20: 10 < 20, no raise.
        """
        src_provider_id = self.src_volume.provider_id
        vtree_volumes = [
            {'id': 'root_vol', 'ancestorVolumeId': None},
        ] + [
            {'id': 'child_%d' % i, 'ancestorVolumeId': src_provider_id}
            for i in range(10)
        ]
        self._test_create_cloned_volume_image_cache(vtree_volumes,
                                                    expect_raises=False,
                                                    max_size=20)

    def test_create_cloned_volume_image_cache_limit_reached(self):
        """Test cloning image cache volume when clone limit is reached.

        20 direct children with max_size=20: 20 >= 20, raises.
        """
        src_provider_id = self.src_volume.provider_id
        vtree_volumes = [
            {'id': 'root_vol', 'ancestorVolumeId': None},
        ] + [
            {'id': 'child_%d' % i, 'ancestorVolumeId': src_provider_id}
            for i in range(20)
        ]
        self._test_create_cloned_volume_image_cache(vtree_volumes,
                                                    expect_raises=True,
                                                    max_size=20)

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._create_volume_from_source')
    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._get_client')
    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.LOG')
    def test_create_cloned_volume_image_cache_query_fails(
            self, mock_log, mock_client, mock_create):
        """Test cloning when vtree volumes query fails.

        On VolumeBackendAPIException, log warning and proceed with clone.
        """
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

    def test_create_cloned_volume_image_cache_excludes_grandchildren(self):
        """Test that grandchildren of the cache volume are not counted.

        2 direct children + 8 grandchildren with max_size=3:
        only 2 direct children counted, 2 < 3 so no raise.
        If grandchildren were incorrectly counted (2+1=3 >= 3),
        the test would fail, proving they are excluded.
        """
        src_provider_id = self.src_volume.provider_id
        vtree_volumes = [
            {'id': 'root_vol', 'ancestorVolumeId': None},
            {'id': 'child_1', 'ancestorVolumeId': src_provider_id},
            {'id': 'child_2', 'ancestorVolumeId': src_provider_id},
            {'id': 'grandchild_1', 'ancestorVolumeId': 'child_1'},
            {'id': 'grandchild_2', 'ancestorVolumeId': 'child_1'},
            {'id': 'grandchild_3', 'ancestorVolumeId': 'child_1'},
            {'id': 'grandchild_4', 'ancestorVolumeId': 'child_1'},
            {'id': 'grandchild_5', 'ancestorVolumeId': 'child_2'},
            {'id': 'grandchild_6', 'ancestorVolumeId': 'child_2'},
            {'id': 'grandchild_7', 'ancestorVolumeId': 'child_2'},
            {'id': 'grandchild_8', 'ancestorVolumeId': 'child_2'},
        ]
        self._test_create_cloned_volume_image_cache(vtree_volumes,
                                                    expect_raises=False,
                                                    max_size=3)

    def test_create_cloned_volume_image_cache_filtering_edge_cases(self):
        """Test comprehensive filtering edge cases.

        6 volumes total, only 2 are direct children, max_size=3:
        2 < 3 so no raise. If any non-child volume were incorrectly
        counted (2+1=3 >= 3), the test would fail. This validates:
        - Root volume with ancestorVolumeId=None is excluded
        - Volumes missing ancestorVolumeId field are excluded
        - Volumes with None ancestorVolumeId value are excluded
        - Orphan volumes (unknown parent) are excluded
        - Only exact matches to src_provider_id are counted
        """
        src_provider_id = self.src_volume.provider_id
        vtree_volumes = [
            {'id': 'root_vol', 'ancestorVolumeId': None},
            {'id': 'root_no_field'},
            {'id': 'root_none_value', 'ancestorVolumeId': None},
            {'id': 'child_1', 'ancestorVolumeId': src_provider_id},
            {'id': 'child_2', 'ancestorVolumeId': src_provider_id},
            {'id': 'orphan', 'ancestorVolumeId': 'unknown_parent'},
        ]
        self._test_create_cloned_volume_image_cache(vtree_volumes,
                                                    expect_raises=False,
                                                    max_size=3)

    def test_create_cloned_volume_image_cache_vtree_volumes_api_call(self):
        """Integration: verify query_vtree_volumes called with correct ID.

        Validates the full flow from query_volume (to get vtreeId) through
        query_vtree_volumes (to get volume list for filtering).
        """
        src_provider_id = self.src_volume.provider_id
        vtree_volumes = [
            {'id': 'root', 'ancestorVolumeId': None},
            {'id': 'child_1', 'ancestorVolumeId': src_provider_id},
        ]
        self._test_create_cloned_volume_image_cache(
            vtree_volumes, expect_raises=False,
            max_size=20, vtree_id='specific_vtree_id_123')

    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._create_volume_from_source')
    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.'
                'PowerFlexDriver._get_client')
    @mock.patch('cinder.volume.drivers.dell_emc.powerflex.driver.LOG')
    def test_create_cloned_volume_image_cache_vtree_volumes_query_fails(
            self, mock_log, mock_client, mock_create):
        """Test cloning when query_vtree_volumes fails.

        query_volume succeeds but query_vtree_volumes raises
        VolumeBackendAPIException. Should log warning and proceed.
        """
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        mock_create.return_value = {}

        self.override_config(options.POWERFLEX_MAX_IMAGE_CACHE_VTREE_SIZE, 20,
                             configuration.SHARED_CONF_GROUP)

        mock_rest_client = mock.Mock()
        mock_client.return_value = mock_rest_client
        mock_rest_client.query_volume.return_value = {
            'vtreeId': 'test_vtree_id'
        }
        mock_rest_client.query_vtree_volumes.side_effect = (
            exception.VolumeBackendAPIException(data="VTree query failed"))

        with mock.patch('cinder.volume.volume_utils.is_image_cache_entry',
                        return_value=True):
            self.driver.create_cloned_volume(self.new_volume, self.src_volume)

        mock_rest_client.query_volume.assert_called_once_with(
            self.src_volume.provider_id)
        mock_rest_client.query_vtree_volumes.assert_called_once_with(
            'test_vtree_id')
        mock_log.warning.assert_called_once()
        mock_create.assert_called_once_with(self.new_volume, self.src_volume)
