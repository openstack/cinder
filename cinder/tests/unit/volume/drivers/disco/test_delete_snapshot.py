# (c) Copyright 2015 Industrial Technology Research Institute.
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

"""Test case for the delete snapshot function."""
import mock

from cinder import exception
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit.volume.drivers import disco


class DeleteSnapshotTestCase(disco.TestDISCODriver):
    """Test cases to delete DISCO volumes."""

    def setUp(self):
        """Initialise variables and mock functions."""
        super(DeleteSnapshotTestCase, self).setUp()

        # Mock snapshotDelete function.
        mock.patch.object(self.requester,
                          'snapshotDelete',
                          self.perform_disco_request).start()

        self.response = self.FAKE_RESPONSE['standard']['success']
        self.snapshot = fake_snapshot.fake_snapshot_obj(
            self.ctx, **{'volume': self.volume})

    def perform_disco_request(self, *cmd, **kwargs):
        """Mock function to delete a snapshot."""
        return self.response

    def test_delete_snapshot(self):
        """Delete a snapshot."""
        self.driver.delete_snapshot(self.snapshot)

    def test_delete_snapshot_fail(self):
        """Make the API returns an error while deleting."""
        self.response = self.FAKE_RESPONSE['standard']['fail']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_delete_snapshot)
