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

"""Test case for create volume from snapshot."""

import copy
import mock
import time

from cinder import exception
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import utils as utils
from cinder.tests.unit.volume.drivers import disco


class CreateVolumeFromSnapshotTestCase(disco.TestDISCODriver):
    """Test cases for the create volume from snapshot of DISCO connector."""

    def setUp(self):
        """Initialise variables and mock functions."""
        super(CreateVolumeFromSnapshotTestCase, self).setUp()

        self.snapshot = fake_snapshot.fake_snapshot_obj(
            self.ctx, **{'volume': self.volume})

        # Mock restoreFromSnapshot, restoreDetail
        # and volume detail since they are in the function path
        mock.patch.object(self.requester,
                          'restoreFromSnapshot',
                          self.restore_request).start()

        mock.patch.object(self.requester,
                          'restoreDetail',
                          self.restore_detail_request).start()

        mock.patch.object(self.requester,
                          'volumeDetailByName',
                          self.volume_detail_request).start()

        restore_detail_response = {
            'status': 0,
            'restoreInfoResult':
                {'restoreId': 1234,
                 'startTime': '',
                 'statusPercent': '',
                 'volumeName': 'aVolumeName',
                 'snapshotId': 1234,
                 'status': 0}
        }

        self.volume_detail_response = {
            'status': 0,
            'volumeInfoResult':
                {'volumeId': 1234567}
        }

        rest_success = copy.deepcopy(restore_detail_response)
        rest_pending = copy.deepcopy(restore_detail_response)
        rest_fail = copy.deepcopy(restore_detail_response)
        rest_response_fail = copy.deepcopy(restore_detail_response)
        rest_success['restoreInfoResult']['status'] = (
            self.DETAIL_OPTIONS['success'])
        rest_pending['restoreInfoResult']['status'] = (
            self.DETAIL_OPTIONS['pending'])
        rest_fail['restoreInfoResult']['status'] = (
            self.DETAIL_OPTIONS['failure'])
        rest_response_fail['status'] = 1

        self.FAKE_RESPONSE['restore_detail'] = {
            'success': rest_success,
            'fail': rest_fail,
            'pending': rest_pending,
            'request_fail': rest_response_fail
        }

        self.response = self.FAKE_RESPONSE['standard']['success']
        self.response['result'] = '1234'

        self.response_detail = (
            self.FAKE_RESPONSE['restore_detail']['success'])
        self.test_pending = False

        self.test_pending_count = 0

    def restore_request(self, *cmd, **kwargs):
        """Mock function for the createVolumeFromSnapshot function."""
        return self.response

    def restore_detail_request(self, *cmd, **kwargs):
        """Mock function for the restoreDetail function."""
        if self.test_pending:
            if self.test_pending_count == 0:
                self.test_pending_count += 1
                return self.FAKE_RESPONSE['restore_detail']['pending']
            else:
                return self.FAKE_RESPONSE['restore_detail']['success']
        else:
            return self.response_detail

    def volume_detail_request(self, *cmd, **kwargs):
        """Mock function for the volumeDetail function."""
        return self.volume_detail_response

    def test_create_volume_from_snapshot(self):
        """Normal case."""
        expected = 1234567
        actual = self.driver.create_volume_from_snapshot(self.volume,
                                                         self.snapshot)
        self.assertEqual(expected, actual['provider_location'])

    def test_create_volume_from_snapshot_fail(self):
        """Create volume from snapshot request fails."""
        self.response = self.FAKE_RESPONSE['standard']['fail']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_volume_from_snapshot)

    def test_create_volume_from_snapshot_fail_not_immediate(self):
        """Get restore details request fails."""
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.response_detail = (
            self.FAKE_RESPONSE['restore_detail']['fail'])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_volume_from_snapshot)

    def test_create_volume_from_snapshot_fail_detail_response_fail(self):
        """Get restore details reports that restore operation fails."""
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.response_detail = (
            self.FAKE_RESPONSE['restore_detail']['request_fail'])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_volume_from_snapshot)

    def test_create_volume_from_snapshot_fail_not_immediate_resp_fail(self):
        """Get restore details reports that the task is pending, then done."""
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.test_pending = True
        self.test_create_volume_from_snapshot()

    @mock.patch.object(time, 'time')
    def test_create_volume_from_snapshot_timeout(self, mock_time):
        """Create volume from snapshot task timeout."""
        timeout = 3
        mock_time.side_effect = utils.generate_timeout_series(timeout)
        self.driver.configuration.disco_restore_check_timeout = timeout
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.response_detail = (
            self.FAKE_RESPONSE['restore_detail']['pending'])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_volume_from_snapshot)

    def test_create_volume_from_snapshot_volume_detail_fail(self):
        """Cannot get the newly created volume information."""
        self.volume_detail_response['status'] = 1
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_volume_from_snapshot)
