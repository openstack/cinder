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

import time

from oslo_log import log as logging
import testtools

from cinder import service
from cinder.tests import fake_driver
from cinder.tests.integrated.api import client
from cinder.tests.integrated import integrated_helpers


LOG = logging.getLogger(__name__)


class VolumesTest(integrated_helpers._IntegratedTestBase):
    def setUp(self):
        super(VolumesTest, self).setUp()
        fake_driver.LoggingVolumeDriver.clear_logs()

    def _start_api_service(self):
        self.osapi = service.WSGIService("osapi_volume")
        self.osapi.start()
        self.auth_url = 'http://%s:%s/v2' % (self.osapi.host, self.osapi.port)
        LOG.warn(self.auth_url)

    def _get_flags(self):
        f = super(VolumesTest, self)._get_flags()
        f['volume_driver'] = 'cinder.tests.fake_driver.LoggingVolumeDriver'
        return f

    def test_get_volumes_summary(self):
        """Simple check that listing volumes works."""
        volumes = self.api.get_volumes(False)
        for volume in volumes:
            LOG.debug("volume: %s" % volume)

    def test_get_volumes(self):
        """Simple check that listing volumes works."""
        volumes = self.api.get_volumes()
        for volume in volumes:
            LOG.debug("volume: %s" % volume)

    def _poll_while(self, volume_id, continue_states, max_retries=5):
        """Poll (briefly) while the state is in continue_states."""
        retries = 0
        while True:
            try:
                found_volume = self.api.get_volume(volume_id)
            except client.OpenStackApiNotFoundException:
                found_volume = None
                LOG.debug("Got 404, proceeding")
                break

            LOG.debug("Found %s" % found_volume)

            self.assertEqual(volume_id, found_volume['id'])

            if found_volume['status'] not in continue_states:
                break

            time.sleep(1)
            retries = retries + 1
            if retries > max_retries:
                break
        return found_volume

    @testtools.skip('This test is failing: bug 1173266')
    def test_create_and_delete_volume(self):
        """Creates and deletes a volume."""

        # Create volume
        created_volume = self.api.post_volume({'volume': {'size': 1}})
        LOG.debug("created_volume: %s" % created_volume)
        self.assertTrue(created_volume['id'])
        created_volume_id = created_volume['id']

        # Check it's there
        found_volume = self.api.get_volume(created_volume_id)
        self.assertEqual(created_volume_id, found_volume['id'])

        # It should also be in the all-volume list
        volumes = self.api.get_volumes()
        volume_names = [volume['id'] for volume in volumes]
        self.assertIn(created_volume_id, volume_names)

        # Wait (briefly) for creation. Delay is due to the 'message queue'
        found_volume = self._poll_while(created_volume_id, ['creating'])

        # It should be available...
        self.assertEqual('available', found_volume['status'])

        # Delete the volume
        self.api.delete_volume(created_volume_id)

        # Wait (briefly) for deletion. Delay is due to the 'message queue'
        found_volume = self._poll_while(created_volume_id, ['deleting'])

        # Should be gone
        self.assertFalse(found_volume)

        LOG.debug("Logs: %s" % fake_driver.LoggingVolumeDriver.all_logs())

        create_actions = fake_driver.LoggingVolumeDriver.logs_like(
            'create_volume',
            id=created_volume_id)
        LOG.debug("Create_Actions: %s" % create_actions)

        self.assertEqual(1, len(create_actions))
        create_action = create_actions[0]
        self.assertEqual(create_action['id'], created_volume_id)
        self.assertEqual(create_action['availability_zone'], 'nova')
        self.assertEqual(create_action['size'], 1)

        export_actions = fake_driver.LoggingVolumeDriver.logs_like(
            'create_export',
            id=created_volume_id)
        self.assertEqual(1, len(export_actions))
        export_action = export_actions[0]
        self.assertEqual(export_action['id'], created_volume_id)
        self.assertEqual(export_action['availability_zone'], 'nova')

        delete_actions = fake_driver.LoggingVolumeDriver.logs_like(
            'delete_volume',
            id=created_volume_id)
        self.assertEqual(1, len(delete_actions))
        delete_action = export_actions[0]
        self.assertEqual(delete_action['id'], created_volume_id)

    def test_create_volume_with_metadata(self):
        """Creates a volume with metadata."""

        # Create volume
        metadata = {'key1': 'value1',
                    'key2': 'value2'}
        created_volume = self.api.post_volume(
            {'volume': {'size': 1,
                        'metadata': metadata}})
        LOG.debug("created_volume: %s" % created_volume)
        self.assertTrue(created_volume['id'])
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
        LOG.debug("created_volume: %s" % created_volume)
        self.assertTrue(created_volume['id'])
        created_volume_id = created_volume['id']

        # Check it's there and availability zone present
        found_volume = self.api.get_volume(created_volume_id)
        self.assertEqual(created_volume_id, found_volume['id'])
        self.assertEqual(availability_zone, found_volume['availability_zone'])

    def test_create_and_update_volume(self):
        # Create vol1
        created_volume = self.api.post_volume({'volume': {
            'size': 1, 'name': 'vol1'}})
        self.assertEqual(created_volume['name'], 'vol1')
        created_volume_id = created_volume['id']

        # update volume
        body = {'volume': {'name': 'vol-one'}}
        updated_volume = self.api.put_volume(created_volume_id, body)
        self.assertEqual(updated_volume['name'], 'vol-one')

        # check for update
        found_volume = self.api.get_volume(created_volume_id)
        self.assertEqual(created_volume_id, found_volume['id'])
        self.assertEqual(found_volume['name'], 'vol-one')
