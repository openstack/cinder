# Copyright 2011 Justin Santa Barbara
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

from cinder.tests.functional.api import client
from cinder.tests.functional import functional_helpers
from cinder.volume import configuration


class VolumesTest(functional_helpers._FunctionalTestBase):
    _vol_type_name = 'functional_test_type'

    def setUp(self):
        super(VolumesTest, self).setUp()
        self.api.create_type(self._vol_type_name)

    def _get_flags(self):
        f = super(VolumesTest, self)._get_flags()
        f['volume_driver'] = (
            {'v': 'cinder.tests.fake_driver.FakeLoggingVolumeDriver',
             'g': configuration.SHARED_CONF_GROUP})
        f['default_volume_type'] = {'v': self._vol_type_name}
        return f

    def test_get_volumes_summary(self):
        """Simple check that listing volumes works."""
        volumes = self.api.get_volumes(False)
        self.assertIsNotNone(volumes)

    def test_get_volumes(self):
        """Simple check that listing volumes works."""
        volumes = self.api.get_volumes()
        self.assertIsNotNone(volumes)

    def test_create_and_delete_volume(self):
        """Creates and deletes a volume."""

        # Create volume
        created_volume = self.api.post_volume({'volume': {'size': 1}})
        self.assertTrue(uuidutils.is_uuid_like(created_volume['id']))
        created_volume_id = created_volume['id']

        # Check it's there
        found_volume = self.api.get_volume(created_volume_id)
        self.assertEqual(created_volume_id, found_volume['id'])
        self.assertEqual(self._vol_type_name, found_volume['volume_type'])

        # It should also be in the all-volume list
        volumes = self.api.get_volumes()
        volume_names = [volume['id'] for volume in volumes]
        self.assertIn(created_volume_id, volume_names)

        # Wait (briefly) for creation. Delay is due to the 'message queue'
        found_volume = self._poll_volume_while(created_volume_id, ['creating'])

        # It should be available...
        self.assertEqual('available', found_volume['status'])

        # Delete the volume
        self.api.delete_volume(created_volume_id)

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_volume = self._poll_volume_while(created_volume_id, ['deleting'])

        # Should be gone
        self.assertIsNone(found_volume)

    def test_create_no_volume_type(self):
        """Verify volume_type is not None"""

        # Create volume
        created_volume = self.api.post_volume({'volume': {'size': 1}})
        self.assertTrue(uuidutils.is_uuid_like(created_volume['id']))
        created_volume_id = created_volume['id']

        # Wait (briefly) for creation. Delay is due to the 'message queue'
        found_volume = self._poll_volume_while(created_volume_id, ['creating'])
        self.assertEqual('available', found_volume['status'])

        # It should have a volume_type
        self.assertIsNotNone(found_volume['volume_type'])

        # Delete the volume
        self.api.delete_volume(created_volume_id)
        found_volume = self._poll_volume_while(created_volume_id, ['deleting'])
        self.assertIsNone(found_volume)

    def test_create_volume_default_type(self):
        """Verify that the configured default_volume_type is used"""

        my_vol_type_name = 'default_type'
        self.api.create_type(my_vol_type_name)
        self.flags(default_volume_type=my_vol_type_name)

        # Create volume
        created_volume = self.api.post_volume({'volume': {'size': 1}})
        self.assertTrue(uuidutils.is_uuid_like(created_volume['id']))
        created_volume_id = created_volume['id']

        # Wait (briefly) for creation. Delay is due to the 'message queue'
        found_volume = self._poll_volume_while(created_volume_id, ['creating'])
        self.assertEqual('available', found_volume['status'])

        # It should have the default volume_type
        self.assertEqual(my_vol_type_name, found_volume['volume_type'])

        # Delete the volume
        self.api.delete_volume(created_volume_id)
        found_volume = self._poll_volume_while(created_volume_id, ['deleting'])
        self.assertIsNone(found_volume)

    def test_create_volume_bad_default_type(self):
        """Verify non-existent default volume type errors out."""

        # configure a non-existent default type
        self.flags(default_volume_type='non-existent-type')

        # Create volume and verify it errors out with 500 status
        self.assertRaises(client.OpenStackApiException500,
                          self.api.post_volume, {'volume': {'size': 1}})

    def test_create_volume_default_type_set_none(self):
        """Verify None default volume type errors out."""

        # configure None default type
        self.flags(default_volume_type=None)

        # Create volume and verify it errors out with 500 status
        self.assertRaises(client.OpenStackApiException500,
                          self.api.post_volume, {'volume': {'size': 1}})

    def test_create_volume_specified_type(self):
        """Verify volume_type is not default."""

        my_vol_type_name = 'my_specified_type'
        my_vol_type_id = self.api.create_type(my_vol_type_name)['id']

        # Create volume
        created_volume = self.api.post_volume(
            {'volume': {'size': 1,
                        'volume_type': my_vol_type_id}})
        self.assertTrue(uuidutils.is_uuid_like(created_volume['id']))
        created_volume_id = created_volume['id']

        # Wait (briefly) for creation. Delay is due to the 'message queue'
        found_volume = self._poll_volume_while(created_volume_id, ['creating'])
        self.assertEqual('available', found_volume['status'])

        # It should have the specified volume_type
        self.assertEqual(my_vol_type_name, found_volume['volume_type'])

        # Delete the volume and test type
        self.api.delete_volume(created_volume_id)
        found_volume = self._poll_volume_while(created_volume_id, ['deleting'])
        self.assertIsNone(found_volume)
        self.api.delete_type(my_vol_type_id)

    def test_create_volume_from_source_vol_inherits_voltype(self):
        src_vol_type_name = 'source_vol_type'
        src_vol_type_id = self.api.create_type(src_vol_type_name)['id']

        # Create source volume
        src_volume = self.api.post_volume(
            {'volume': {'size': 1,
                        'volume_type': src_vol_type_id}})
        self.assertTrue(uuidutils.is_uuid_like(src_volume['id']))
        src_volume_id = src_volume['id']

        # Wait (briefly) for creation. Delay is due to the 'message queue'
        src_volume = self._poll_volume_while(src_volume_id, ['creating'])
        self.assertEqual('available', src_volume['status'])

        # Create a new volume using src_volume, do not specify a volume_type
        new_volume = self.api.post_volume(
            {'volume': {'size': 1,
                        'source_volid': src_volume_id}})
        new_volume_id = new_volume['id']

        # Wait for creation ...
        new_volume = self._poll_volume_while(new_volume_id, ['creating'])
        self.assertEqual('available', new_volume['status'])

        # It should have the same type as the source volume
        self.assertEqual(src_vol_type_name, new_volume['volume_type'])

        # Delete the volumes and test type
        self.api.delete_volume(src_volume_id)
        found_volume = self._poll_volume_while(src_volume_id, ['deleting'])
        self.assertIsNone(found_volume)
        self.api.delete_volume(new_volume_id)
        found_volume = self._poll_volume_while(new_volume_id, ['deleting'])
        self.assertIsNone(found_volume)
        self.api.delete_type(src_vol_type_id)

    def test_create_volume_from_snapshot_inherits_voltype(self):
        src_vol_type_name = 'a_very_new_vol_type'
        src_vol_type_id = self.api.create_type(src_vol_type_name)['id']

        # Create source volume
        src_volume = self.api.post_volume(
            {'volume': {'size': 1,
                        'volume_type': src_vol_type_id}})
        src_volume_id = src_volume['id']

        # Wait (briefly) for creation. Delay is due to the 'message queue'
        src_volume = self._poll_volume_while(src_volume_id, ['creating'])
        self.assertEqual('available', src_volume['status'])

        # Create a snapshot of src_volume
        snapshot = self.api.post_snapshot(
            {'snapshot': {'volume_id': src_volume_id,
                          'name': 'test_snapshot'}})
        self.assertEqual(src_volume_id, snapshot['volume_id'])
        snapshot_id = snapshot['id']

        # make sure the snapshot is ready
        snapshot = self._poll_snapshot_while(snapshot_id, ['creating'])
        self.assertEqual('available', snapshot['status'])

        # create a new volume from the snapshot, do not specify a volume_type
        new_volume = self.api.post_volume(
            {'volume': {'size': 1,
                        'snapshot_id': snapshot_id}})
        new_volume_id = new_volume['id']

        # Wait for creation ...
        new_volume = self._poll_volume_while(new_volume_id, ['creating'])
        self.assertEqual('available', new_volume['status'])

        # Finally, here's the whole point of this test:
        self.assertEqual(src_vol_type_name, new_volume['volume_type'])

        # Delete the snapshot, volumes, and test type
        self.api.delete_snapshot(snapshot_id)
        snapshot = self._poll_snapshot_while(snapshot_id, ['deleting'])
        self.assertIsNone(snapshot)

        self.api.delete_volume(src_volume_id)
        src_volume = self._poll_volume_while(src_volume_id, ['deleting'])
        self.assertIsNone(src_volume)

        self.api.delete_volume(new_volume_id)
        new_volume = self._poll_volume_while(new_volume_id, ['deleting'])
        self.assertIsNone(new_volume)

        self.api.delete_type(src_vol_type_id)

    def test_create_volume_with_metadata(self):
        """Creates a volume with metadata."""

        # Create volume
        metadata = {'key1': 'value1',
                    'key2': 'value2',
                    'volume/created/by': 'cinder'}
        created_volume = self.api.post_volume(
            {'volume': {'size': 1,
                        'metadata': metadata}})
        self.assertTrue(uuidutils.is_uuid_like(created_volume['id']))
        created_volume_id = created_volume['id']

        # Check it's there and metadata present
        found_volume = self.api.get_volume(created_volume_id)
        self.assertEqual(created_volume_id, found_volume['id'])
        self.assertEqual(metadata, found_volume['metadata'])

    def test_create_volume_in_availability_zone(self):
        """Creates a volume in availability_zone."""

        # Create volume
        availability_zone = 'nova'
        created_volume = self.api.post_volume(
            {'volume': {'size': 1,
                        'availability_zone': availability_zone}})
        self.assertTrue(uuidutils.is_uuid_like(created_volume['id']))
        created_volume_id = created_volume['id']

        # Check it's there and availability zone present
        found_volume = self.api.get_volume(created_volume_id)
        self.assertEqual(created_volume_id, found_volume['id'])
        self.assertEqual(availability_zone, found_volume['availability_zone'])

    def test_create_and_update_volume(self):
        # Create vol1
        created_volume = self.api.post_volume({'volume': {
            'size': 1, 'name': 'vol1'}})
        self.assertEqual('vol1', created_volume['name'])
        created_volume_id = created_volume['id']

        # update volume
        body = {'volume': {'name': 'vol-one'}}
        updated_volume = self.api.put_volume(created_volume_id, body)
        self.assertEqual('vol-one', updated_volume['name'])

        # check for update
        found_volume = self.api.get_volume(created_volume_id)
        self.assertEqual(created_volume_id, found_volume['id'])
        self.assertEqual('vol-one', found_volume['name'])
