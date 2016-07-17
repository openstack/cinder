# Copyright 2016 EMC Corporation
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

import ddt

import mock

from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import snapshots
from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume

UUID = '00000000-0000-0000-0000-000000000001'
INVALID_UUID = '00000000-0000-0000-0000-000000000002'


@ddt.ddt
class SnapshotApiTest(test.TestCase):
    def setUp(self):
        super(SnapshotApiTest, self).setUp()
        self.controller = snapshots.SnapshotsController()
        self.ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

    @ddt.data('3.14', '3.13')
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_snapshot_show(self, max_ver, snapshot_get_by_id, volume_get_by_id,
                           snapshot_metadata_get):
        snapshot = {
            'id': UUID,
            'volume_id': fake.VOLUME_ID,
            'status': fields.SnapshotStatus.AVAILABLE,
            'volume_size': 100,
            'display_name': 'Default name',
            'display_description': 'Default description',
            'expected_attrs': ['metadata'],
            'group_snapshot_id': None,
        }
        ctx = context.RequestContext(fake.PROJECT_ID, fake.USER_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % UUID)
        req.api_version_request = api_version.APIVersionRequest(max_ver)
        resp_dict = self.controller.show(req, UUID)

        self.assertIn('snapshot', resp_dict)
        self.assertEqual(UUID, resp_dict['snapshot']['id'])
        self.assertIn('updated_at', resp_dict['snapshot'])
        if max_ver == '3.14':
            self.assertIn('group_snapshot_id', resp_dict['snapshot'])
        elif max_ver == '3.13':
            self.assertNotIn('group_snapshot_id', resp_dict['snapshot'])

    def test_snapshot_show_invalid_id(self):
        snapshot_id = INVALID_UUID
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % snapshot_id)
        self.assertRaises(exception.SnapshotNotFound,
                          self.controller.show, req, snapshot_id)
