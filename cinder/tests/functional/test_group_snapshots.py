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

from cinder.objects import fields
from cinder.tests.functional import functional_helpers
from cinder.volume import configuration


class GroupSnapshotsTest(functional_helpers._FunctionalTestBase):
    _vol_type_name = 'functional_test_type'
    _grp_type_name = 'functional_grp_test_type'
    osapi_version_major = '3'
    osapi_version_minor = '19'

    def setUp(self):
        super(GroupSnapshotsTest, self).setUp()
        self.volume_type = self.api.create_type(self._vol_type_name)
        self.group_type = self.api.create_group_type(self._grp_type_name)

    def _get_flags(self):
        f = super(GroupSnapshotsTest, self)._get_flags()
        f['volume_driver'] = (
            {'v': 'cinder.tests.fake_driver.FakeLoggingVolumeDriver',
             'g': configuration.SHARED_CONF_GROUP})
        f['default_volume_type'] = {'v': self._vol_type_name}
        f['default_group_type'] = {'v': self._grp_type_name}
        return f

    def test_get_group_snapshots_summary(self):
        """Simple check that listing group snapshots works."""
        grp_snaps = self.api.get_group_snapshots(False)
        self.assertIsNotNone(grp_snaps)

    def test_get_group_snapshots(self):
        """Simple check that listing group snapshots works."""
        grp_snaps = self.api.get_group_snapshots()
        self.assertIsNotNone(grp_snaps)

    def test_create_and_delete_group_snapshot(self):
        """Creates and deletes a group snapshot."""

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

        # Create group snapshot
        created_group_snapshot = self.api.post_group_snapshot(
            {'group_snapshot': {'group_id': created_group_id}})
        self.assertTrue(uuidutils.is_uuid_like(created_group_snapshot['id']))
        created_group_snapshot_id = created_group_snapshot['id']

        # Check it's there
        found_group_snapshot = self._poll_group_snapshot_while(
            created_group_snapshot_id, [fields.GroupSnapshotStatus.CREATING])
        self.assertEqual(created_group_snapshot_id, found_group_snapshot['id'])
        self.assertEqual(created_group_id,
                         found_group_snapshot['group_id'])
        self.assertEqual(fields.GroupSnapshotStatus.AVAILABLE,
                         found_group_snapshot['status'])

        # Delete the group snapshot
        self.api.delete_group_snapshot(created_group_snapshot_id)

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_group_snapshot = self._poll_group_snapshot_while(
            created_group_snapshot_id, [fields.GroupSnapshotStatus.DELETING])

        # Delete the original group
        self.api.delete_group(created_group_id,
                              {'delete': {'delete-volumes': True}})

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_volume = self._poll_volume_while(created_volume_id, ['deleting'])
        found_group = self._poll_group_while(created_group_id, ['deleting'])

        # Should be gone
        self.assertIsNone(found_group_snapshot)
        self.assertIsNone(found_volume)
        self.assertIsNone(found_group)

    def test_create_group_from_group_snapshot(self):
        """Creates a group from a group snapshot."""

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

        # Create group snapshot
        created_group_snapshot = self.api.post_group_snapshot(
            {'group_snapshot': {'group_id': created_group_id}})
        self.assertTrue(uuidutils.is_uuid_like(created_group_snapshot['id']))
        created_group_snapshot_id = created_group_snapshot['id']

        # Check it's there
        found_group_snapshot = self._poll_group_snapshot_while(
            created_group_snapshot_id, ['creating'])
        self.assertEqual(created_group_snapshot_id, found_group_snapshot['id'])
        self.assertEqual(created_group_id,
                         found_group_snapshot['group_id'])
        self.assertEqual('available', found_group_snapshot['status'])

        # Create group from group snapshot
        created_group_from_snap = self.api.post_group_from_src(
            {'create-from-src': {
                'group_snapshot_id': created_group_snapshot_id}})
        self.assertTrue(uuidutils.is_uuid_like(created_group_from_snap['id']))
        created_group_from_snap_id = created_group_from_snap['id']

        # Check it's there
        found_volumes = self.api.get_volumes()
        self._poll_volume_while(found_volumes[0], ['creating'])
        self._poll_volume_while(found_volumes[1], ['creating'])
        found_group_from_snap = self._poll_group_while(
            created_group_from_snap_id, ['creating'])
        self.assertEqual(created_group_from_snap_id,
                         found_group_from_snap['id'])
        self.assertEqual(created_group_snapshot_id,
                         found_group_from_snap['group_snapshot_id'])
        self.assertEqual(self.group_type['id'],
                         found_group_from_snap['group_type'])
        self.assertEqual('available', found_group_from_snap['status'])

        # Delete the group from snap
        self.api.delete_group(created_group_from_snap_id,
                              {'delete': {'delete-volumes': True}})

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_group_from_snap = self._poll_group_while(
            created_group_from_snap_id, ['deleting'])

        # Delete the group snapshot
        self.api.delete_group_snapshot(created_group_snapshot_id)

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_group_snapshot = self._poll_group_snapshot_while(
            created_group_snapshot_id, [fields.GroupSnapshotStatus.DELETING])

        # Delete the original group
        self.api.delete_group(created_group_id,
                              {'delete': {'delete-volumes': True}})

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_volume = self._poll_volume_while(created_volume_id, ['deleting'])
        found_group = self._poll_group_while(created_group_id, ['deleting'])

        # Should be gone
        self.assertIsNone(found_group_from_snap)
        self.assertIsNone(found_group_snapshot)
        self.assertIsNone(found_volume)
        self.assertIsNone(found_group)

    def test_create_group_from_source_group(self):
        """Creates a group from a source group."""

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

        # Test create group from source group
        created_group_from_group = self.api.post_group_from_src(
            {'create-from-src': {
                'source_group_id': created_group_id}})
        self.assertTrue(uuidutils.is_uuid_like(created_group_from_group['id']))
        created_group_from_group_id = created_group_from_group['id']

        # Check it's there
        found_volumes = self.api.get_volumes()
        self._poll_volume_while(found_volumes[0], ['creating'])
        self._poll_volume_while(found_volumes[1], ['creating'])
        found_group_from_group = self._poll_group_while(
            created_group_from_group_id, ['creating'])
        self.assertEqual(created_group_from_group_id,
                         found_group_from_group['id'])
        self.assertEqual(created_group_id,
                         found_group_from_group['source_group_id'])
        self.assertEqual(self.group_type['id'],
                         found_group_from_group['group_type'])
        self.assertEqual('available', found_group_from_group['status'])

        # Delete the group from group
        self.api.delete_group(created_group_from_group_id,
                              {'delete': {'delete-volumes': True}})

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_group_from_group = self._poll_group_while(
            created_group_from_group_id, ['deleting'])

        # Delete the original group
        self.api.delete_group(created_group_id,
                              {'delete': {'delete-volumes': True}})

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_volume = self._poll_volume_while(created_volume_id, ['deleting'])
        found_group = self._poll_group_while(created_group_id, ['deleting'])

        # Should be gone
        self.assertIsNone(found_group_from_group)
        self.assertIsNone(found_volume)
        self.assertIsNone(found_group)

    def test_reset_group_snapshot(self):
        # Create group
        group1 = self.api.post_group(
            {'group': {'group_type': self.group_type['id'],
                       'volume_types': [self.volume_type['id']]}})
        self.assertTrue(uuidutils.is_uuid_like(group1['id']))
        group_id = group1['id']
        self._poll_group_while(group_id, ['creating'])

        # Create volume
        created_volume = self.api.post_volume(
            {'volume': {'size': 1,
                        'group_id': group_id,
                        'volume_type': self.volume_type['id']}})
        self.assertTrue(uuidutils.is_uuid_like(created_volume['id']))
        created_volume_id = created_volume['id']
        self._poll_volume_while(created_volume_id, ['creating'])

        # Create group snapshot
        group_snapshot1 = self.api.post_group_snapshot(
            {'group_snapshot': {'group_id': group_id}})
        self.assertTrue(uuidutils.is_uuid_like(group_snapshot1['id']))
        group_snapshot_id = group_snapshot1['id']

        self._poll_group_snapshot_while(group_snapshot_id,
                                        fields.GroupSnapshotStatus.CREATING)

        group_snapshot1 = self.api.get_group_snapshot(group_snapshot_id)
        self.assertEqual(fields.GroupSnapshotStatus.AVAILABLE,
                         group_snapshot1['status'])

        # reset group snapshot status
        self.api.reset_group_snapshot(group_snapshot_id, {"reset_status": {
            "status": fields.GroupSnapshotStatus.ERROR}})

        group_snapshot1 = self.api.get_group_snapshot(group_snapshot_id)
        self.assertEqual(fields.GroupSnapshotStatus.ERROR,
                         group_snapshot1['status'])

        # Delete group, volume and group snapshot
        self.api.delete_group_snapshot(group_snapshot_id)
        found_group_snapshot = self._poll_group_snapshot_while(
            group_snapshot_id, [fields.GroupSnapshotStatus.DELETING])
        self.api.delete_group(group_id,
                              {'delete': {'delete-volumes': True}})

        found_volume = self._poll_volume_while(created_volume_id, ['deleting'])
        found_group = self._poll_group_while(group_id, ['deleting'])

        # Created resources should be gone
        self.assertIsNone(found_group_snapshot)
        self.assertIsNone(found_volume)
        self.assertIsNone(found_group)
