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

"""Test case for the create volume function."""

import mock

from cinder import exception
from cinder.tests.unit.volume.drivers import disco


class CreateVolumeTestCase(disco.TestDISCODriver):
    """Test cases for DISCO connector."""

    def setUp(self):
        """Prepare variables and mock functions."""
        super(CreateVolumeTestCase, self).setUp()

        # Mock the method volumeCreate.
        mock.patch.object(self.requester,
                          'volumeCreate',
                          self.perform_disco_request).start()

        self.response = self.FAKE_RESPONSE['standard']['success']

    def perform_disco_request(self, *cmd, **kwargs):
        """Mock function for the suds client."""
        return self.response

    def test_create_volume(self):
        """Normal case."""
        expected = '1234567'
        self.response['result'] = expected
        ret = self.driver.create_volume(self.volume)
        actual = ret['provider_location']
        self.assertEqual(expected, actual)

    def test_create_volume_fail(self):
        """Request to DISCO failed."""
        self.response = self.FAKE_RESPONSE['standard']['fail']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_volume)
