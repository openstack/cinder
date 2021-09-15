# Copyright 2011 OpenStack Foundation
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

from http import HTTPStatus
from unittest import mock
import uuid

import ddt
from oslo_serialization import jsonutils
import webob

from cinder.api import extensions
from cinder.api.v2 import snapshots
from cinder.api.v3 import snapshot_metadata
from cinder import context
import cinder.db
from cinder import exception
from cinder.objects import fields
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v3 import fakes as v3_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder import volume


def return_create_snapshot_metadata(context, snapshot_id, metadata, delete):
    return fake_snapshot_metadata()


def return_create_snapshot_metadata_insensitive(context, snapshot_id,
                                                metadata, delete):
    return fake_snapshot_metadata_insensitive()


def return_new_snapshot_metadata(context, snapshot_id, metadata, delete):
    return fake_new_snapshot_metadata()


def fake_snapshot_metadata():
    metadata = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
    }
    return metadata


def fake_snapshot_metadata_insensitive():
    metadata = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
        "KEY4": "value4",
    }
    return metadata


def fake_new_snapshot_metadata():
    metadata = {
        'key10': 'value10',
        'key99': 'value99',
        'KEY20': 'value20',
    }
    return metadata


def return_snapshot(context, snapshot_id):
    return {'id': '0cc3346e-9fef-4445-abe6-5d2b2690ec64',
            'name': 'fake',
            'status': 'available',
            'metadata': {}}


# First argument needs to be self to receive the context argument in the right
# variable, as this'll be used to replace the original API.get method which
# receives self as the first argument.
def fake_get(self, context, *args, **kwargs):
    vol = {'id': fake.VOLUME_ID,
           'size': 100,
           'name': 'fake',
           'host': 'fake-host',
           'status': 'available',
           'encryption_key_id': None,
           'volume_type_id': fake.VOLUME_TYPE_ID,
           'migration_status': None,
           'availability_zone': 'fake-zone',
           'attach_status': fields.VolumeAttachStatus.DETACHED,
           'metadata': {}}
    return fake_volume.fake_volume_obj(context, **vol)


def return_snapshot_nonexistent(context, snapshot_id):
    raise exception.SnapshotNotFound(snapshot_id=snapshot_id)


@ddt.ddt
class SnapshotMetaDataTest(test.TestCase):

    def setUp(self):
        super(SnapshotMetaDataTest, self).setUp()
        self.volume_api = cinder.volume.api.API()
        self.mock_object(volume.api.API, 'get', fake_get)
        self.mock_object(cinder.db.sqlalchemy.api, 'volume_type_get',
                         v3_fakes.fake_volume_type_get)
        self.mock_object(scheduler_rpcapi.SchedulerAPI, 'create_snapshot')
        self.mock_object(cinder.db, 'snapshot_get', return_snapshot)
        self.mock_object(self.volume_api, 'update_snapshot_metadata')
        self.patch('cinder.objects.volume.Volume.refresh')
        self.patch('cinder.quota.QuotaEngine.reserve')

        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.snapshot_controller = snapshots.SnapshotsController(self.ext_mgr)
        self.controller = snapshot_metadata.Controller()
        self.req_id = str(uuid.uuid4())
        self.url = '/v3/%s/snapshots/%s/metadata' % (
            fake.PROJECT_ID, self.req_id)
        self.ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

        snap = {"volume_id": fake.VOLUME_ID,
                "display_name": "Volume Test Name",
                "description": "Volume Test Desc",
                "metadata": {}}
        body = {"snapshot": snap}
        req = fakes.HTTPRequest.blank('/v3/snapshots')
        req.environ['cinder.context'] = self.ctx
        self.snapshot_controller.create(req, body=body)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_index(self, snapshot_get_by_id):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_obj['metadata'] = {'key1': 'value1',
                                    'key2': 'value2',
                                    'key3': 'value3'}
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url)
        req.environ['cinder.context'] = self.ctx
        res_dict = self.controller.index(req, self.req_id)

        expected = {
            'metadata': {
                'key1': 'value1',
                'key2': 'value2',
                'key3': 'value3',
            },
        }
        self.assertEqual(expected, res_dict)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_index_nonexistent_snapshot(self, snapshot_get_by_id):
        snapshot_get_by_id.side_effect = \
            exception.SnapshotNotFound(snapshot_id=self.req_id)

        req = fakes.HTTPRequest.blank(self.url)
        req.environ['cinder.context'] = self.ctx
        self.assertRaises(exception.SnapshotNotFound,
                          self.controller.index, req, self.url)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_index_no_data(self, snapshot_get_by_id):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url)
        req.environ['cinder.context'] = self.ctx
        res_dict = self.controller.index(req, self.req_id)
        expected = {'metadata': {}}
        self.assertEqual(expected, res_dict)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_show(self, snapshot_get_by_id):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_obj['metadata'] = {'key2': 'value2'}
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key2')
        req.environ['cinder.context'] = self.ctx
        res_dict = self.controller.show(req, self.req_id, 'key2')
        expected = {'meta': {'key2': 'value2'}}
        self.assertEqual(expected, res_dict)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_show_nonexistent_snapshot(self, snapshot_get_by_id):
        snapshot_get_by_id.side_effect = \
            exception.SnapshotNotFound(snapshot_id=self.req_id)

        req = fakes.HTTPRequest.blank(self.url + '/key2')
        req.environ['cinder.context'] = self.ctx
        self.assertRaises(exception.SnapshotNotFound,
                          self.controller.show, req, self.req_id, 'key2')

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_show_meta_not_found(self, snapshot_get_by_id):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key6')
        req.environ['cinder.context'] = self.ctx
        self.assertRaises(exception.SnapshotMetadataNotFound,
                          self.controller.show, req, self.req_id, 'key6')

    @mock.patch('cinder.db.snapshot_metadata_delete')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_delete(self, snapshot_get_by_id, snapshot_metadata_delete):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_obj['metadata'] = {'key2': 'value2'}
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key2')
        req.environ['cinder.context'] = self.ctx
        req.method = 'DELETE'
        res = self.controller.delete(req, self.req_id, 'key2')

        self.assertEqual(HTTPStatus.OK, res.status_int)

    def test_delete_nonexistent_snapshot(self):
        self.mock_object(cinder.db, 'snapshot_get',
                         return_snapshot_nonexistent)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.environ['cinder.context'] = self.ctx
        req.method = 'DELETE'
        self.assertRaises(exception.SnapshotNotFound,
                          self.controller.delete, req, self.req_id, 'key1')

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_delete_meta_not_found(self, snapshot_get_by_id):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key6')
        req.environ['cinder.context'] = self.ctx
        req.method = 'DELETE'
        self.assertRaises(exception.SnapshotMetadataNotFound,
                          self.controller.delete, req, self.req_id, 'key6')

    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_create(self, snapshot_get_by_id, volume_get_by_id,
                    snapshot_update):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(self.ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj

        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)

        req = fakes.HTTPRequest.blank('/v3/snapshot_metadata')
        req.environ['cinder.context'] = self.ctx
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"metadata": {"key1": "value1",
                             "key2": "value2",
                             "key3": "value3"}}
        req.body = jsonutils.dump_as_bytes(body)
        res_dict = self.controller.create(req, self.req_id, body)
        self.assertEqual(body, res_dict)

    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_create_with_keys_in_uppercase_and_lowercase(
            self, snapshot_get_by_id, snapshot_update):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        # if the keys in uppercase_and_lowercase, should return the one
        # which server added
        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata_insensitive)

        req = fakes.HTTPRequest.blank('/v3/snapshot_metadata')
        req.environ['cinder.context'] = self.ctx
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"metadata": {"key1": "value1",
                             "KEY1": "value1",
                             "key2": "value2",
                             "KEY2": "value2",
                             "key3": "value3",
                             "KEY4": "value4"}}
        expected = {"metadata": {"key1": "value1",
                                 "key2": "value2",
                                 "key3": "value3",
                                 "KEY4": "value4"}}
        req.body = jsonutils.dump_as_bytes(body)
        res_dict = self.controller.create(req, self.req_id, body)
        self.assertEqual(expected, res_dict)

    def test_create_empty_body(self):
        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.environ['cinder.context'] = self.ctx
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, self.req_id, None)

    def test_create_item_empty_key(self):
        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        body = {"meta": {"": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, self.req_id, body)

    def test_create_item_key_too_long(self):
        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        body = {"meta": {("a" * 260): "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req, self.req_id, body)

    def test_create_nonexistent_snapshot(self):
        self.mock_object(cinder.db, 'snapshot_get',
                         return_snapshot_nonexistent)
        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)

        req = fakes.HTTPRequest.blank('/v3/snapshot_metadata')
        req.environ['cinder.context'] = self.ctx
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"metadata": {"key9": "value9"}}
        req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.SnapshotNotFound,
                          self.controller.create, req, self.req_id, body)

    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_all(self, snapshot_get_by_id, snapshot_update):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': []
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_new_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {
            'metadata': {
                'key10': 'value10',
                'key99': 'value99',
                'KEY20': 'value20',
            },
        }
        req.body = jsonutils.dump_as_bytes(expected)
        res_dict = self.controller.update_all(req, self.req_id, expected)

        self.assertEqual(expected, res_dict)

    @mock.patch('cinder.db.snapshot_update',
                return_value={'key10': 'value10',
                              'key99': 'value99',
                              'KEY20': 'value20'})
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_all_with_keys_in_uppercase_and_lowercase(
            self, snapshot_get_by_id, snapshot_update):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_new_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        req.content_type = "application/json"
        body = {
            'metadata': {
                'key10': 'value10',
                'KEY10': 'value10',
                'key99': 'value99',
                'KEY20': 'value20',
            },
        }
        expected = {
            'metadata': {
                'key10': 'value10',
                'key99': 'value99',
                'KEY20': 'value20',
            },
        }
        req.body = jsonutils.dump_as_bytes(expected)
        res_dict = self.controller.update_all(req, self.req_id, body)

        self.assertEqual(expected, res_dict)

    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_all_empty_container(self, snapshot_get_by_id,
                                        snapshot_update):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': []
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_value={})
        req = fakes.HTTPRequest.blank(self.url)
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': {}}
        req.body = jsonutils.dump_as_bytes(expected)
        res_dict = self.controller.update_all(req, self.req_id, expected)

        self.assertEqual(expected, res_dict)

    def test_update_all_malformed_container(self):
        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'meta': {}}
        req.body = jsonutils.dump_as_bytes(expected)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update_all, req, self.req_id,
                          expected)

    def test_update_all_malformed_data(self):
        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': ['asdf']}
        req.body = jsonutils.dump_as_bytes(expected)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update_all, req, self.req_id,
                          expected)

    def test_update_all_nonexistent_snapshot(self):
        self.mock_object(cinder.db, 'snapshot_get',
                         return_snapshot_nonexistent)
        req = fakes.HTTPRequest.blank(self.url)
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        req.content_type = "application/json"
        body = {'metadata': {'key10': 'value10'}}
        req.body = jsonutils.dump_as_bytes(body)

        self.assertRaises(exception.SnapshotNotFound,
                          self.controller.update_all, req, '100', body)

    @mock.patch('cinder.db.snapshot_metadata_update', return_value=dict())
    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_item(self, snapshot_get_by_id,
                         snapshot_update, snapshot_metadata_update):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"
        res_dict = self.controller.update(req, self.req_id, 'key1', body)
        expected = {'meta': {'key1': 'value1'}}
        self.assertEqual(expected, res_dict)

    def test_update_item_nonexistent_snapshot(self):
        self.mock_object(cinder.db, 'snapshot_get',
                         return_snapshot_nonexistent)
        req = fakes.HTTPRequest.blank(
            '/v3/%s/snapshots/asdf/metadata/key1' % fake.PROJECT_ID)
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(exception.SnapshotNotFound,
                          self.controller.update, req, self.req_id, 'key1',
                          body)

    def test_update_item_empty_body(self):
        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.req_id, 'key1',
                          None)

    @mock.patch('cinder.db.sqlalchemy.api._snapshot_get')
    @mock.patch('cinder.db.snapshot_metadata_update', autospec=True)
    def test_update_item_empty_key(self, metadata_update, snapshot_get):
        snapshot_get.return_value = fake_get
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        body = {"meta": {"": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.req_id, '', body)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_item_key_too_long(self, snapshot_get_by_id):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        body = {"meta": {("a" * 260): "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update,
                          req, self.req_id, ("a" * 260), body)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_item_value_too_long(self, snapshot_get_by_id):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        body = {"meta": {"key1": ("a" * 260)}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update,
                          req, self.req_id, "key1", body)

    @ddt.data({"meta": {"key1": "value1", "key2": "value2"}},
              {"meta": {"key1": None}})
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_invalid_metadata(self, body, snapshot_get_by_id):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.req_id, 'key1',
                          body)

    def test_update_item_body_uri_mismatch(self):
        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/bad')
        req.environ['cinder.context'] = self.ctx
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.req_id, 'bad',
                          body)

    @ddt.data({"metadata": {"a" * 260: "value1"}},
              {"metadata": {"key": "v" * 260}},
              {"metadata": {"": "value1"}},
              {"metadata": {"key": None}})
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_invalid_metadata_items_on_create(self, data, snapshot_get_by_id):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.mock_object(cinder.db, 'snapshot_metadata_update',
                         return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.environ['cinder.context'] = self.ctx
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        exc = webob.exc.HTTPBadRequest
        if (len(list(data['metadata'].keys())[0]) > 255 or
                (list(data['metadata'].values())[0] is not None and
                    len(list(data['metadata'].values())[0]) > 255)):
            exc = webob.exc.HTTPRequestEntityTooLarge

        req.body = jsonutils.dump_as_bytes(data)
        self.assertRaises(exc, self.controller.create, req, self.req_id, data)
