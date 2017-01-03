#   Copyright 2013, Red Hat, Inc.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import mock
from oslo_serialization import jsonutils
from six.moves import http_client
import webob

from cinder import context
from cinder import db
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake


def fake_snapshot_get(context, snapshot_id):
    snapshot = v2_fakes.fake_snapshot(snapshot_id)

    if snapshot_id == fake.SNAPSHOT_ID:
        snapshot['status'] = fields.SnapshotStatus.CREATING
    else:
        snapshot['status'] = fields.SnapshotStatus.ERROR
    return snapshot


class SnapshotActionsTest(test.TestCase):

    def setUp(self):
        super(SnapshotActionsTest, self).setUp()
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)

    @mock.patch('cinder.db.snapshot_update', autospec=True)
    @mock.patch('cinder.db.sqlalchemy.api._snapshot_get',
                side_effect=fake_snapshot_get)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_update_snapshot_status(self, metadata_get, *args):

        body = {'os-update_snapshot_status':
                {'status': fields.SnapshotStatus.AVAILABLE}}
        req = webob.Request.blank('/v2/%s/snapshots/%s/action' % (
            fake.PROJECT_ID, fake.SNAPSHOT_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        self.assertEqual(http_client.ACCEPTED, res.status_int)

    @mock.patch('cinder.db.sqlalchemy.api._snapshot_get',
                side_effect=fake_snapshot_get)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_update_snapshot_status_invalid_status(self, metadata_get, *args):
        body = {'os-update_snapshot_status': {'status': 'in-use'}}
        req = webob.Request.blank('/v2/%s/snapshots/%s/action' % (
            fake.PROJECT_ID, fake.SNAPSHOT_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    def test_update_snapshot_status_without_status(self):
        self.mock_object(db, 'snapshot_get', fake_snapshot_get)
        body = {'os-update_snapshot_status': {}}
        req = webob.Request.blank('/v2/%s/snapshots/%s/action' % (
            fake.PROJECT_ID, fake.SNAPSHOT_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
