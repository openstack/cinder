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

"""Test cases for create cloned volume."""

import copy
import mock
import six
import time


from cinder import exception
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils as utils
from cinder.tests.unit.volume.drivers import disco


class CreateCloneVolumeTestCase(disco.TestDISCODriver):
    """Test cases for DISCO connector."""

    def setUp(self):
        """Initialise variables and mock functions."""
        super(CreateCloneVolumeTestCase, self).setUp()

        self.dest_volume = fake_volume.fake_volume_obj(self.ctx)
        # Create mock functions for all the call done by the driver."""
        mock.patch.object(self.requester,
                          'volumeClone',
                          self.clone_request).start()

        mock.patch.object(self.requester,
                          'cloneDetail',
                          self.clone_detail_request).start()

        mock.patch.object(self.requester,
                          'volumeDetailByName',
                          self.volume_detail_request).start()

        self.volume_detail_response = {
            'status': 0,
            'volumeInfoResult':
                {'volumeId': 1234567}
        }

        clone_success = (
            copy.deepcopy(self.FAKE_RESPONSE['standard']['success']))
        clone_pending = (
            copy.deepcopy(self.FAKE_RESPONSE['standard']['success']))
        clone_fail = (
            copy.deepcopy(self.FAKE_RESPONSE['standard']['success']))
        clone_response_fail = (
            copy.deepcopy(self.FAKE_RESPONSE['standard']['success']))

        clone_success['result'] = (
            six.text_type(self.DETAIL_OPTIONS['success']))
        clone_pending['result'] = (
            six.text_type(self.DETAIL_OPTIONS['pending']))
        clone_fail['result'] = (
            six.text_type(self.DETAIL_OPTIONS['failure']))
        clone_response_fail['status'] = 1

        self.FAKE_RESPONSE['clone_detail'] = {
            'success': clone_success,
            'fail': clone_fail,
            'pending': clone_pending,
            'request_fail': clone_response_fail
        }

        self.response = self.FAKE_RESPONSE['standard']['success']
        self.response['result'] = '1234'

        self.response_detail = (
            self.FAKE_RESPONSE['clone_detail']['success'])
        self.test_pending = False
        self.test_pending_count = 0

    def clone_request(self, *cmd, **kwargs):
        """Mock function for the createVolumeFromSnapshot function."""
        return self.response

    def clone_detail_request(self, *cmd, **kwargs):
        """Mock function for the restoreDetail function."""
        if self.test_pending:
            if self.test_pending_count == 0:
                self.test_pending_count += 1
                return self.FAKE_RESPONSE['clone_detail']['pending']
            else:
                return self.FAKE_RESPONSE['clone_detail']['success']
        else:
            return self.response_detail

    def volume_detail_request(self, *cmd, **kwargs):
        """Mock function for the volumeDetail function."""
        return self.volume_detail_response

    def test_create_cloned_volume(self):
        """Normal case."""
        expected = 1234567
        actual = self.driver.create_cloned_volume(self.dest_volume,
                                                  self.volume)
        self.assertEqual(expected, actual['provider_location'])

    def test_create_clone_volume_fail(self):
        """Clone volume request to DISCO fails."""
        self.response = self.FAKE_RESPONSE['standard']['fail']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_cloned_volume)

    def test_create_cloned_volume_fail_not_immediate(self):
        """Get clone detail returns that the clone fails."""
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.response_detail = (
            self.FAKE_RESPONSE['clone_detail']['fail'])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_cloned_volume)

    def test_create_cloned_volume_fail_not_immediate_response_fail(self):
        """Get clone detail request to DISCO fails."""
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.response_detail = (
            self.FAKE_RESPONSE['clone_detail']['request_fail'])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_cloned_volume)

    def test_create_cloned_volume_fail_not_immediate_request_fail(self):
        """Get clone detail returns the task is pending then complete."""
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.test_pending = True
        self.test_create_cloned_volume()

    @mock.patch.object(time, 'time')
    def test_create_cloned_volume_timeout(self, mock_time):
        """Clone request timeout."""
        timeout = 3
        mock_time.side_effect = utils.generate_timeout_series(timeout)
        self.driver.configuration.disco_clone_check_timeout = timeout
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.response_detail = (
            self.FAKE_RESPONSE['clone_detail']['pending'])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_cloned_volume)

    def test_create_cloned_volume_volume_detail_fail(self):
        """Get volume detail request to DISCO fails."""
        self.volume_detail_response['status'] = 1
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_cloned_volume)
