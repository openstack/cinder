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

from http import HTTPStatus
from unittest import mock

import ddt
from oslo_serialization import jsonutils
import webob

from cinder.api.contrib import snapshot_actions
from cinder.api import microversions as mv
from cinder import context
from cinder import db
from cinder import exception
from cinder.objects import fields
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v3 import fakes as v3_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


def fake_snapshot_get(context, snapshot_id):
    snapshot = v3_fakes.fake_snapshot(snapshot_id)

    if snapshot_id == fake.SNAPSHOT_ID:
        snapshot['status'] = fields.SnapshotStatus.CREATING
    else:
        snapshot['status'] = fields.SnapshotStatus.ERROR
    return snapshot


@ddt.ddt
class SnapshotActionsTest(test.TestCase):

    def setUp(self):
        super(SnapshotActionsTest, self).setUp()
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)
        self.controller = snapshot_actions.SnapshotActionsController()

    @mock.patch('cinder.db.snapshot_update', autospec=True)
    @mock.patch('cinder.db.sqlalchemy.api._snapshot_get',
                side_effect=fake_snapshot_get)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_update_snapshot_status(self, metadata_get, *args):

        body = {'os-update_snapshot_status':
                {'status': fields.SnapshotStatus.AVAILABLE}}
        req = webob.Request.blank('/v3/%s/snapshots/%s/action' % (
            fake.PROJECT_ID, fake.SNAPSHOT_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        self.assertEqual(HTTPStatus.ACCEPTED, res.status_int)

    @mock.patch('cinder.db.sqlalchemy.api._snapshot_get',
                side_effect=fake_snapshot_get)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_update_snapshot_status_invalid_status(self, metadata_get, *args):
        body = {'os-update_snapshot_status': {'status': 'in-use'}}
        req = webob.Request.blank('/v3/%s/snapshots/%s/action' % (
            fake.PROJECT_ID, fake.SNAPSHOT_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        self.assertEqual(HTTPStatus.BAD_REQUEST, res.status_int)

    def test_update_snapshot_status_without_status(self):
        self.mock_object(db, 'snapshot_get', fake_snapshot_get)
        body = {'os-update_snapshot_status': {}}
        req = webob.Request.blank('/v3/%s/snapshots/%s/action' % (
            fake.PROJECT_ID, fake.SNAPSHOT_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        self.assertEqual(HTTPStatus.BAD_REQUEST, res.status_int)

    @mock.patch('cinder.db.snapshot_update', autospec=True)
    @mock.patch('cinder.db.sqlalchemy.api._snapshot_get',
                side_effect=fake_snapshot_get)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_update_snapshot_valid_progress(self, metadata_get, *args):
        body = {'os-update_snapshot_status':
                {'status': fields.SnapshotStatus.AVAILABLE,
                 'progress': '50%'}}
        req = webob.Request.blank('/v3/%s/snapshots/%s/action' % (
            fake.PROJECT_ID, fake.SNAPSHOT_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        self.assertEqual(HTTPStatus.ACCEPTED, res.status_int)

    @ddt.data(({'os-update_snapshot_status':
               {'status': fields.SnapshotStatus.AVAILABLE,
                'progress': '50'}}, exception.InvalidInput),
              ({'os-update_snapshot_status':
               {'status': fields.SnapshotStatus.AVAILABLE,
                'progress': '103%'}}, exception.InvalidInput),
              ({'os-update_snapshot_status':
               {'status': fields.SnapshotStatus.AVAILABLE,
                'progress': "   "}}, exception.InvalidInput),
              ({'os-update_snapshot_status':
               {'status': fields.SnapshotStatus.AVAILABLE,
                'progress': 50}}, exception.ValidationError))
    @ddt.unpack
    def test_update_snapshot_invalid_progress(self, body, exception_class):
        req = webob.Request.blank('/v3/%s/snapshots/%s/action' % (
            fake.PROJECT_ID, fake.SNAPSHOT_ID))
        req.api_version_request = mv.get_api_version(mv.BASE_VERSION)
        self.assertRaises(exception_class,
                          self.controller._update_snapshot_status,
                          req, body=body)
