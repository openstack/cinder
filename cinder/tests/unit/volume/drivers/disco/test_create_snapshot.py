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

"""Test case for the function create snapshot."""


import copy
import mock
import time

from cinder import db
from cinder import exception
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import utils as utils
from cinder.tests.unit.volume.drivers import disco


class CreateSnapshotTestCase(disco.TestDISCODriver):
    """Test cases for DISCO connector."""

    def get_fake_volume(self, ctx, id):
        """Return fake volume from db calls."""
        return self.volume

    def setUp(self):
        """Initialise variables and mock functions."""
        super(CreateSnapshotTestCase, self).setUp()

        self.snapshot = fake_snapshot.fake_snapshot_obj(
            self.ctx, **{'volume': self.volume})

        # Mock db call in the cinder driver
        self.mock_object(db.sqlalchemy.api, 'volume_get',
                         self.get_fake_volume)

        mock.patch.object(self.requester,
                          'snapshotCreate',
                          self.snapshot_request).start()

        mock.patch.object(self.requester,
                          'snapshotDetail',
                          self.snapshot_detail_request).start()

        snapshot_detail_response = {
            'status': 0,
            'snapshotInfoResult':
                {'snapshotId': 1234,
                 'description': 'a description',
                 'createTime': '',
                 'expireTime': '',
                 'isDeleted': False,
                 'status': 0}
        }

        snap_success = copy.deepcopy(snapshot_detail_response)
        snap_pending = copy.deepcopy(snapshot_detail_response)
        snap_fail = copy.deepcopy(snapshot_detail_response)
        snap_response_fail = copy.deepcopy(snapshot_detail_response)
        snap_success['snapshotInfoResult']['status'] = (
            self.DETAIL_OPTIONS['success'])
        snap_pending['snapshotInfoResult']['status'] = (
            self.DETAIL_OPTIONS['pending'])
        snap_fail['snapshotInfoResult']['status'] = (
            self.DETAIL_OPTIONS['failure'])
        snap_response_fail['status'] = 1

        self.FAKE_RESPONSE['snapshot_detail'] = {
            'success': snap_success,
            'fail': snap_fail,
            'pending': snap_pending,
            'request_fail': snap_response_fail}

        self.response = (
            self.FAKE_RESPONSE['standard']['success'])
        self.response['result'] = 1234

        self.response_detail = (
            self.FAKE_RESPONSE['snapshot_detail']['success'])
        self.test_pending = False

        self.test_pending_count = 0

    def snapshot_request(self, *cmd, **kwargs):
        """Mock function for the createSnapshot call."""
        return self.response

    def snapshot_detail_request(self, *cmd, **kwargs):
        """Mock function for the snapshotDetail call."""
        if self.test_pending:
            if self.test_pending_count == 0:
                self.test_pending_count += 1
                return self.FAKE_RESPONSE['snapshot_detail']['pending']
            else:
                return self.FAKE_RESPONSE['snapshot_detail']['success']
        else:
            return self.response_detail

    def test_create_snapshot(self):
        """Normal test case."""
        expected = 1234
        actual = self.driver.create_snapshot(self.volume)
        self.assertEqual(expected, actual['provider_location'])

    def test_create_snapshot_fail(self):
        """Request to DISCO failed."""
        self.response = self.FAKE_RESPONSE['standard']['fail']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_snapshot)

    def test_create_snapshot_fail_not_immediate(self):
        """Request to DISCO failed when monitoring the snapshot details."""
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.response_detail = (
            self.FAKE_RESPONSE['snapshot_detail']['fail'])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_snapshot)

    def test_create_snapshot_fail_not_immediate_response_fail(self):
        """Request to get the snapshot details returns a failure."""
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.response_detail = (
            self.FAKE_RESPONSE['snapshot_detail']['request_fail'])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_snapshot)

    def test_create_snapshot_detail_pending(self):
        """Request to get the snapshot detail return pending then success."""
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.test_pending = True
        self.test_create_snapshot()

    @mock.patch.object(time, 'time')
    def test_create_snapshot_timeout(self, mock_time):
        """Snapshot request timeout."""
        timeout = 3
        mock_time.side_effect = utils.generate_timeout_series(timeout)
        self.driver.configuration.disco_snapshot_check_timeout = timeout
        self.response = self.FAKE_RESPONSE['standard']['success']
        self.response_detail = (
            self.FAKE_RESPONSE['snapshot_detail']['pending'])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_snapshot)
