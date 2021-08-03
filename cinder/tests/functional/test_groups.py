# Copyright 2016 EMC Corporation
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

from oslo_utils import uuidutils

from cinder.tests.functional import functional_helpers
from cinder.volume import configuration


class GroupsTest(functional_helpers._FunctionalTestBase):
    _vol_type_name = 'functional_test_type'
    _grp_type_name = 'functional_grp_test_type'
    _osapi_version = '3.20'

    def setUp(self):
        super(GroupsTest, self).setUp()
        self.volume_type = self.api.create_type(self._vol_type_name)
        self.group_type = self.api.create_group_type(self._grp_type_name)
        self.group1 = self.api.post_group(
            {'group': {'group_type': self.group_type['id'],
             'volume_types': [self.volume_type['id']]}})

    def _get_flags(self):
        f = super(GroupsTest, self)._get_flags()
        f['volume_driver'] = (
            {'v': 'cinder.tests.fake_driver.FakeLoggingVolumeDriver',
             'g': configuration.SHARED_CONF_GROUP})
        f['default_volume_type'] = {'v': self._vol_type_name}
        f['default_group_type'] = {'v': self._grp_type_name}
        return f

    def test_get_groups_summary(self):
        """Simple check that listing groups works."""
        grps = self.api.get_groups(False)
        self.assertIsNotNone(grps)

    def test_get_groups(self):
        """Simple check that listing groups works."""
        grps = self.api.get_groups()
        self.assertIsNotNone(grps)

    def test_reset_group_status(self):
        """Reset group status"""
        found_group = self._poll_group_while(self.group1['id'],
                                             ['creating'])
        self.assertEqual('available', found_group['status'])
        self.api.reset_group(self.group1['id'],
                             {"reset_status": {"status": "error"}})

        group = self.api.get_group(self.group1['id'])
        self.assertEqual("error", group['status'])

    def test_create_and_delete_group(self):
        """Creates and deletes a group."""

        # Create group
        created_group = self.api.post_group(
            {'group': {'group_type': self.group_type['id'],
                       'volume_types': [self.volume_type['id']]}})
        self.assertTrue(uuidutils.is_uuid_like(created_group['id']))
        created_group_id = created_group['id']

        # Check it's there
        found_group = self._poll_group_while(created_group_id,
                                             ['creating'])
        self.assertEqual(created_group_id, found_group['id'])
        self.assertEqual(self.group_type['id'], found_group['group_type'])
        self.assertEqual('available', found_group['status'])

        # Create volume
        created_volume = self.api.post_volume(
            {'volume': {'size': 1,
                        'group_id': created_group_id,
                        'volume_type': self.volume_type['id']}})
        self.assertTrue(uuidutils.is_uuid_like(created_volume['id']))
        created_volume_id = created_volume['id']

        # Check it's there
        found_volume = self.api.get_volume(created_volume_id)
        self.assertEqual(created_volume_id, found_volume['id'])
        self.assertEqual(self._vol_type_name, found_volume['volume_type'])
        self.assertEqual(created_group_id, found_volume['group_id'])

        # Wait (briefly) for creation. Delay is due to the 'message queue'
        found_volume = self._poll_volume_while(created_volume_id, ['creating'])

        # It should be available...
        self.assertEqual('available', found_volume['status'])

        # Delete the original group
        self.api.delete_group(created_group_id,
                              {'delete': {'delete-volumes': True}})

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_volume = self._poll_volume_while(created_volume_id, ['deleting'])
        found_group = self._poll_group_while(created_group_id, ['deleting'])

        # Should be gone
        self.assertIsNone(found_volume)
        self.assertIsNone(found_group)
