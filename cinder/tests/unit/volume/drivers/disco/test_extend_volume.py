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

"""Test cases for the extend volume feature."""

import mock

from cinder import exception
from cinder.tests.unit.volume.drivers import disco


class VolumeExtendTestCase(disco.TestDISCODriver):
    """Test cases for DISCO connector."""

    def setUp(self):
        """Initialise variables and mock functions."""
        super(VolumeExtendTestCase, self).setUp()

        # Mock function to extend a volume.
        mock.patch.object(self.requester,
                          'volumeExtend',
                          self.perform_disco_request).start()

        self.response = self.FAKE_RESPONSE['standard']['success']
        self.new_size = 5

    def perform_disco_request(self, *cmd, **kwargs):
        """Mock volumExtend function from suds client."""
        return self.response

    def test_extend_volume(self):
        """Extend a volume, normal case."""
        self.driver.extend_volume(self.volume, self.new_size)

    def test_extend_volume_fail(self):
        """Request to DISCO failed."""
        self.response = self.FAKE_RESPONSE['standard']['fail']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_extend_volume)
