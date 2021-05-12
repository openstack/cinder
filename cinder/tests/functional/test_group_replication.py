# Copyright (C) 2017 Dell Inc. or its subsidiaries.
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

from cinder.objects import fields
from cinder.tests.functional import functional_helpers
from cinder.volume import configuration


class GroupReplicationTest(functional_helpers._FunctionalTestBase):
    _vol_type_name = 'functional_test_type'
    _grp_type_name = 'functional_grp_test_type'
    _osapi_version = '3.38'

    def setUp(self):
        super(GroupReplicationTest, self).setUp()
        self.volume_type = self.api.create_type(self._vol_type_name)
        extra_specs = {"replication_enabled": "<is> True"}
        self.api.create_volume_type_extra_specs(self.volume_type['id'],
                                                extra_specs=extra_specs)
        self.volume_type = self.api.get_type(self.volume_type['id'])
        self.group_type = self.api.create_group_type(self._grp_type_name)
        grp_specs = {"group_replication_enabled": "<is> True"}
        self.api.create_group_type_specs(self.group_type['id'],
                                         group_specs=grp_specs)
        self.group_type = self.api.get_group_type(self.group_type['id'])

    def _get_flags(self):
        f = super(GroupReplicationTest, self)._get_flags()
        f['volume_driver'] = (
            {'v': 'cinder.tests.fake_driver.FakeLoggingVolumeDriver',
             'g': configuration.SHARED_CONF_GROUP})
        f['default_volume_type'] = {'v': self._vol_type_name}
        f['default_group_type'] = {'v': self._grp_type_name}
        return f

    def test_group_replication(self):
        """Tests group replication APIs."""

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

        # Test enable replication group
        self.api.enable_group_replication(created_group_id,
                                          {'enable_replication': {}})

        found_volume = self._poll_volume_while(
            created_volume_id, [fields.ReplicationStatus.ENABLING],
            status_field='replication_status')
        found_group = self._poll_group_while(
            created_group_id, [fields.ReplicationStatus.ENABLING],
            status_field='replication_status')

        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         found_group['replication_status'])
        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         found_volume['replication_status'])

        # Test list replication group targets
        targets = self.api.list_group_replication_targets(
            created_group_id, {'list_replication_targets': {}})
        self.assertEqual({'replication_targets': []}, targets)

        # Test failover replication group
        self.api.failover_group_replication(
            created_group_id,
            {'failover_replication': {'secondary_backend_id': 'backend1',
                                      'allow_attached_volume': False}})

        found_volume = self._poll_volume_while(
            created_volume_id, [fields.ReplicationStatus.FAILING_OVER],
            status_field='replication_status')
        found_group = self._poll_group_while(
            created_group_id, [fields.ReplicationStatus.FAILING_OVER],
            status_field='replication_status')

        self.assertEqual(fields.ReplicationStatus.FAILED_OVER,
                         found_group['replication_status'])
        self.assertEqual(fields.ReplicationStatus.FAILED_OVER,
                         found_volume['replication_status'])

        # Test failback replication group
        self.api.failover_group_replication(
            created_group_id,
            {'failover_replication': {'secondary_backend_id': 'default',
                                      'allow_attached_volume': False}})

        found_volume = self._poll_volume_while(
            created_volume_id, [fields.ReplicationStatus.FAILING_OVER],
            status_field='replication_status')
        found_group = self._poll_group_while(
            created_group_id, [fields.ReplicationStatus.FAILING_OVER],
            status_field='replication_status')

        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         found_group['replication_status'])
        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         found_volume['replication_status'])

        # Test disable replication group
        self.api.disable_group_replication(created_group_id,
                                           {'disable_replication': {}})

        found_volume = self._poll_volume_while(
            created_volume_id, [fields.ReplicationStatus.DISABLING],
            status_field='replication_status')
        found_group = self._poll_group_while(
            created_group_id, [fields.ReplicationStatus.DISABLING],
            status_field='replication_status')

        self.assertEqual(fields.ReplicationStatus.DISABLED,
                         found_group['replication_status'])
        self.assertEqual(fields.ReplicationStatus.DISABLED,
                         found_volume['replication_status'])

        # Delete the original group
        self.api.delete_group(created_group_id,
                              {'delete': {'delete-volumes': True}})

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_volume = self._poll_volume_while(created_volume_id, ['deleting'])
        found_group = self._poll_group_while(created_group_id, ['deleting'])

        # Should be gone
        self.assertIsNone(found_volume)
        self.assertIsNone(found_group)
