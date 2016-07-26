# (c) Copyright 2016 Industrial Technology Research Institute.
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

"""Test case for the function manage_existing."""

import mock

from cinder import exception
from cinder.tests.unit.volume.drivers import disco


class ManageExistingTestCase(disco.TestDISCODriver):
    """Test cases for Disco connector."""

    def setUp(self):
        """Initialize variables and mock functions."""
        super(ManageExistingTestCase, self).setUp()

        # Mock function to extract volume information by its ID
        mock.patch.object(self.requester,
                          'volumeDetail',
                          self.perform_disco_request).start()

        # Mock function to extract volume information by its Name
        mock.patch.object(self.requester,
                          'volumeDetailByName',
                          self.perform_disco_request).start()

        self.response = {'volumeInfoResult': {
                         'volumeName': 'abcdefg',
                         'volumeId': 1234567,
                         'volSizeMb': 2
                         },
                         'status': 0
                         }

        self.existing_ref_no_identification = {}
        self.existing_ref_with_id = {'source-id': 1234567}
        self.existing_ref_with_name = {'source-name': 'abcdefg'}
        self.existing_ref_no_identification = self.existing_ref_with_id

    def perform_disco_request(self, *args, **kwargs):
        """Mock volumeDetail/volumeDetailByName function from rest client."""
        return self.response

    def call_manage_existing(self):
        """Manage an existing volume."""
        self.driver.manage_existing(
            self.volume,
            self.existing_ref_no_identification)

    def test_manage_existing_no_identification(self):
        """Manage an existing volume, no id/name."""
        self.existing_ref_no_identification = {}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.call_manage_existing)

    def test_manage_existing_case_id(self):
        """Manage an existing volume, by its id."""
        expected = {'display_name': 'abcdefg'}
        ret = self.driver.manage_existing(self.volume,
                                          self.existing_ref_with_id)
        actual = {'display_name': ret['display_name']}
        self.assertEqual(expected, actual)

    def test_manage_existing_case_name(self):
        """Manage an existing volume, by its name."""
        expected = {'provider_location': 1234567}
        ret = self.driver.manage_existing(self.volume,
                                          self.existing_ref_with_name)
        actual = {'provider_location': ret['provider_location']}
        self.assertEqual(expected, actual)

    def test_manage_existing_get_size(self):
        """Get size of an existing volume."""
        self.driver.manage_existing_get_size(
            self.volume,
            self.existing_ref_no_identification)

    def test_manage_existing_get_size_no_identification(self):
        """Error while getting size of an existing volume, no id/name."""
        self.existing_ref_no_identification = {}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_manage_existing_get_size)

    def test_manage_existing_get_size_case_id(self):
        """Get size of an existing volume, by its id."""
        expected = 2
        ret = self.driver.manage_existing_get_size(self.volume,
                                                   self.existing_ref_with_id)
        self.assertEqual(expected, ret)

    def test_manage_existing_get_size_case_name(self):
        """Get size of an existing volume, by its name."""
        expected = 2
        ret = self.driver.manage_existing_get_size(self.volume,
                                                   self.existing_ref_with_name)
        self.assertEqual(expected, ret)

    def test_manage_existing_case_id_fail(self):
        """Request to DISCO failed."""
        self.response['status'] = 1
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_manage_existing_case_id)

    def test_manage_existing_case_name_fail(self):
        """Request to DISCO failed."""
        self.response['status'] = 1
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_manage_existing_case_name)

    def test_manage_existing_get_size_case_id_fail(self):
        """Request to DISCO failed."""
        self.response['status'] = 1
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_manage_existing_get_size_case_id)

    def test_manage_existing_get_size_case_name_fail(self):
        """Request to DISCO failed."""
        self.response['status'] = 1
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_manage_existing_get_size_case_name)
