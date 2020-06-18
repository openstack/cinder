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
"""Tests for Volume retype Code."""

from unittest import mock

from oslo_config import cfg

from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.policies import volume_actions as vol_action_policies
from cinder import quota
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base
from cinder.volume import volume_types


QUOTAS = quota.QUOTAS

CONF = cfg.CONF


class VolumeRetypeTestCase(base.BaseVolumeTestCase):
    """Verify multiattach retype restrictions."""

    def setUp(self):
        super(VolumeRetypeTestCase, self).setUp()
        self.patch('cinder.volume.volume_utils.clear_volume', autospec=True)
        self.expected_status = 'available'
        self.service_id = 1
        self.user_context = context.RequestContext(user_id=fake.USER_ID,
                                                   project_id=fake.PROJECT_ID)

        volume_types.create(self.context,
                            "fake_vol_type",
                            {},
                            description="fake_type")
        volume_types.create(self.context,
                            "fake_vol_type2",
                            {},
                            description="fake_type2")
        volume_types.create(self.context,
                            "multiattach-type",
                            {'multiattach': "<is> True"},
                            description="test-multiattach")
        volume_types.create(self.context,
                            "multiattach-type2",
                            {'multiattach': "<is> True"},
                            description="test-multiattach")
        self.default_vol_type = objects.VolumeType.get_by_name_or_id(
            self.context,
            'fake_vol_type')
        self.fake_vol_type2 = objects.VolumeType.get_by_name_or_id(
            self.context,
            'fake_vol_type2')
        self.multiattach_type = objects.VolumeType.get_by_name_or_id(
            self.context,
            'multiattach-type')
        self.multiattach_type2 = objects.VolumeType.get_by_name_or_id(
            self.context,
            'multiattach-type2')

    def fake_get_vtype(self, context, identifier):
        if identifier == "multiattach-type":
            return self.multiattach_type
        elif identifier == 'multiattach-type2':
            return self.multiattach_type2
        elif identifier == 'fake_vol_type2':
            return self.fake_vol_type2
        else:
            return self.default_vol_type

    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.retype')
    @mock.patch('cinder.context.RequestContext.authorize')
    @mock.patch.object(volume_types, 'get_by_name_or_id')
    def test_retype_has_az(self, _mock_get_types, mock_authorize, mock_rpc):
        """Verify retype has az in request spec."""
        _mock_get_types.side_effect = self.fake_get_vtype

        vol = tests_utils.create_volume(
            self.context,
            volume_type_id=self.default_vol_type.id,
            status='available',
            availability_zone='nova')

        self.volume_api.retype(self.user_context,
                               vol,
                               'fake_vol_type2')

        mock_authorize.assert_called_once_with(
            vol_action_policies.RETYPE_POLICY, target_obj=mock.ANY)

        fake_spec = {
            'volume_properties': mock.ANY,
            'volume_id': mock.ANY,
            'volume_type': mock.ANY,
            'migration_policy': mock.ANY,
            'quota_reservations': mock.ANY,
            'old_reservations': mock.ANY,
            'availability_zones': ['nova'],
        }

        mock_rpc.assert_called_once_with(
            self.user_context, mock.ANY,
            request_spec=fake_spec,
            filter_properties=mock.ANY
        )

    @mock.patch('cinder.context.RequestContext.authorize')
    def test_non_multi_to_multi_retype(self, mock_authorize):
        """Test going from non-multiattach type to multiattach"""

        vol = tests_utils.create_volume(self.context,
                                        volume_type_id=
                                        self.default_vol_type.id)

        self.assertFalse(vol.multiattach)
        self.volume_api.retype(self.user_context,
                               vol,
                               'multiattach-type')
        vol.refresh()
        self.assertTrue(vol.multiattach)

        mock_authorize.assert_has_calls(
            [mock.call(vol_action_policies.RETYPE_POLICY, target_obj=mock.ANY)
             ])

    @mock.patch('cinder.context.RequestContext.authorize')
    def test_multi_to_non_multi_retype(self, mock_authorize):
        """Test going from multiattach to a non-multiattach type"""

        vol = tests_utils.create_volume(self.context,
                                        multiattach=True,
                                        volume_type_id=
                                        self.multiattach_type.id)

        self.assertTrue(vol.multiattach)
        self.volume_api.retype(self.user_context,
                               vol,
                               'fake_vol_type')
        vol.refresh()
        self.assertFalse(vol.multiattach)

        mock_authorize.assert_has_calls(
            [mock.call(vol_action_policies.RETYPE_POLICY, target_obj=mock.ANY)
             ])

    @mock.patch('cinder.context.RequestContext.authorize')
    def test_in_use_volume_retype(self, mock_authorize):
        """Test trying to retype an in-use volume"""

        vol = tests_utils.create_volume(self.context,
                                        volume_type_id=
                                        self.multiattach_type.id)
        vol.update({'status': 'in-use'})
        vol.save()
        self.assertRaises(exception.InvalidInput,
                          self.volume_api.retype,
                          self.context,
                          vol,
                          'multiattach-type')
        mock_authorize.assert_has_calls(
            [mock.call(vol_action_policies.RETYPE_POLICY, target_obj=mock.ANY),
             ])

    @mock.patch('cinder.context.RequestContext.authorize')
    def test_multiattach_to_multiattach_retype(self, mock_authorize):
        """Test going from multiattach to multiattach"""

        vol = tests_utils.create_volume(self.context,
                                        multiattach=True,
                                        volume_type_id=
                                        self.multiattach_type.id)

        self.assertTrue(vol.multiattach)
        self.volume_api.retype(self.user_context,
                               vol,
                               'multiattach-type2')
        vol.refresh()
        self.assertTrue(vol.multiattach)

        mock_authorize.assert_has_calls(
            [mock.call(vol_action_policies.RETYPE_POLICY, target_obj=mock.ANY)
             ])

    def test_retype_driver_not_initialized(self):
        volume = tests_utils.create_volume(
            self.context,
            host=CONF.host,
            status='available',
            volume_type_id=self.default_vol_type.id)

        host_obj = {'host': CONF.host, 'capabilities': {}}

        self.volume.driver._initialized = False
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.retype,
                          self.context, volume,
                          self.multiattach_type.id, host_obj,
                          migration_policy='on-demand')

        volume.refresh()
        self.assertEqual('available', volume.status)

    def test_retype_with_volume_type_resize_limits(self):

        def _create_min_max_size_dict(min_size, max_size):
            return {volume_types.MIN_SIZE_KEY: min_size,
                    volume_types.MAX_SIZE_KEY: max_size}

        def _setup_volume_types():
            spec_dict = _create_min_max_size_dict(2, 4)
            sized_vol_type_dict = {'name': 'limit_type',
                                   'extra_specs': spec_dict}
            db.volume_type_create(self.context, sized_vol_type_dict)
            self.sized_vol_type = db.volume_type_get_by_name(
                self.context, sized_vol_type_dict['name'])

            unsized_vol_type_dict = {'name': 'unsized_type', 'extra_specs': {}}
            db.volume_type_create(context.get_admin_context(),
                                  unsized_vol_type_dict)
            self.unsized_vol_type = db.volume_type_get_by_name(
                self.context, unsized_vol_type_dict['name'])

        _setup_volume_types()
        volume_1 = tests_utils.create_volume(
            self.context,
            host=CONF.host,
            status='available',
            volume_type_id=self.default_vol_type.id,
            size=1)
        volume_3 = tests_utils.create_volume(
            self.context,
            host=CONF.host,
            status='available',
            volume_type_id=self.default_vol_type.id,
            size=3)
        volume_9 = tests_utils.create_volume(
            self.context,
            host=CONF.host,
            status='available',
            volume_type_id=self.default_vol_type.id,
            size=9)

        self.assertRaises(exception.InvalidInput,
                          self.volume_api.retype,
                          self.context, volume_1,
                          'limit_type',
                          migration_policy='on-demand')
        self.assertRaises(exception.InvalidInput,
                          self.volume_api.retype,
                          self.context, volume_9,
                          'limit_type',
                          migration_policy='on-demand')
        self.volume_api.retype(self.context, volume_3,
                               'limit_type', migration_policy='on-demand')
