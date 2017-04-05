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
        self.assertFalse(found_volume)

    def test_create_volume_with_metadata(self):
        """Creates a volume with metadata."""

        # Create volume
        metadata = {'key1': 'value1',
                    'key2': 'value2'}
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
