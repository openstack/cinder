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

import mock
from oslo_config import cfg

from cinder import context
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
        self.patch('cinder.volume.utils.clear_volume', autospec=True)
        self.expected_status = 'available'
        self.service_id = 1
        self.user_context = context.RequestContext(user_id=fake.USER_ID,
                                                   project_id=fake.PROJECT_ID)

        volume_types.create(self.context,
                            "fake_vol_type",
                            {},
                            description="fake_type")
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
        else:
            return self.default_vol_type

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
