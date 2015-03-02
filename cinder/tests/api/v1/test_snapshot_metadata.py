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

import uuid

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils
import webob

from cinder.api import extensions
from cinder.api.v1 import snapshot_metadata
from cinder.api.v1 import snapshots
from cinder import context
import cinder.db
from cinder import exception
from cinder import test
from cinder.tests.api import fakes
from cinder.tests import fake_snapshot
from cinder.tests import fake_volume


CONF = cfg.CONF


def return_create_snapshot_metadata_max(context,
                                        snapshot_id,
                                        metadata,
                                        delete):
    return stub_max_snapshot_metadata()


def return_create_snapshot_metadata(context, snapshot_id, metadata, delete):
    return stub_snapshot_metadata()


def return_create_snapshot_metadata_insensitive(context, snapshot_id,
                                                metadata, delete):
    return stub_snapshot_metadata_insensitive()


def return_new_snapshot_metadata(context, snapshot_id, metadata, delete):
    return stub_new_snapshot_metadata()


def return_snapshot_metadata(context, snapshot_id):
    if not isinstance(snapshot_id, str) or not len(snapshot_id) == 36:
        msg = 'id %s must be a uuid in return snapshot metadata' % snapshot_id
        raise Exception(msg)
    return stub_snapshot_metadata()


def return_empty_snapshot_metadata(context, snapshot_id):
    return {}


def return_empty_container_metadata(context, snapshot_id, metadata, delete):
    return {}


def delete_snapshot_metadata(context, snapshot_id, key):
    pass


def stub_snapshot_metadata():
    metadata = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
    }
    return metadata


def stub_snapshot_metadata_insensitive():
    metadata = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
        "KEY4": "value4",
    }
    return metadata


def stub_new_snapshot_metadata():
    metadata = {
        'key10': 'value10',
        'key99': 'value99',
        'KEY20': 'value20',
    }
    return metadata


def stub_max_snapshot_metadata():
    metadata = {"metadata": {}}
    for num in range(CONF.quota_metadata_items):
        metadata['metadata']['key%i' % num] = "blah"
    return metadata


def return_snapshot(context, snapshot_id):
    return {'id': '0cc3346e-9fef-4445-abe6-5d2b2690ec64',
            'name': 'fake',
            'status': 'available',
            'metadata': {}}


def return_volume(context, volume_id):
    return {'id': 'fake-vol-id',
            'size': 100,
            'name': 'fake',
            'host': 'fake-host',
            'status': 'available',
            'encryption_key_id': None,
            'volume_type_id': None,
            'migration_status': None,
            'metadata': {},
            'project_id': context.project_id}


def return_snapshot_nonexistent(context, snapshot_id):
    raise exception.SnapshotNotFound('bogus test message')


def fake_update_snapshot_metadata(self, context, snapshot, diff):
    pass


class SnapshotMetaDataTest(test.TestCase):

    def setUp(self):
        super(SnapshotMetaDataTest, self).setUp()
        self.volume_api = cinder.volume.api.API()
        self.stubs.Set(cinder.db, 'volume_get', return_volume)
        self.stubs.Set(cinder.db, 'snapshot_get', return_snapshot)
        self.stubs.Set(cinder.db, 'snapshot_metadata_get',
                       return_snapshot_metadata)

        self.stubs.Set(self.volume_api, 'update_snapshot_metadata',
                       fake_update_snapshot_metadata)

        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.snapshot_controller = snapshots.SnapshotsController(self.ext_mgr)
        self.controller = snapshot_metadata.Controller()
        self.req_id = str(uuid.uuid4())
        self.url = '/v1/fake/snapshots/%s/metadata' % self.req_id

        snap = {"volume_size": 100,
                "volume_id": "fake-vol-id",
                "display_name": "Volume Test Name",
                "display_description": "Volume Test Desc",
                "availability_zone": "zone1:host1",
                "host": "fake-host",
                "metadata": {}}
        body = {"snapshot": snap}
        req = fakes.HTTPRequest.blank('/v1/snapshots')
        self.snapshot_controller.create(req, body)

    @mock.patch('cinder.db.snapshot_metadata_get',
                return_value={'key1': 'value1',
                              'key2': 'value2',
                              'key3': 'value3'})
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_index(self, snapshot_get_by_id, snapshot_metadata_get):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url)
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
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.index, req, self.url)

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_index_no_data(self, snapshot_get_by_id, snapshot_metadata_get):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.index(req, self.req_id)
        expected = {'metadata': {}}
        self.assertEqual(expected, res_dict)

    @mock.patch('cinder.db.snapshot_metadata_get',
                return_value={'key2': 'value2'})
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_show(self, snapshot_get_by_id, snapshot_metadata_get):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key2')
        res_dict = self.controller.show(req, self.req_id, 'key2')
        expected = {'meta': {'key2': 'value2'}}
        self.assertEqual(expected, res_dict)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_show_nonexistent_snapshot(self, snapshot_get_by_id):
        snapshot_get_by_id.side_effect = \
            exception.SnapshotNotFound(snapshot_id=self.req_id)

        req = fakes.HTTPRequest.blank(self.url + '/key2')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, self.req_id, 'key2')

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_show_meta_not_found(self, snapshot_get_by_id,
                                 snapshot_metadata_get):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key6')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, self.req_id, 'key6')

    @mock.patch('cinder.db.snapshot_metadata_delete')
    @mock.patch('cinder.db.snapshot_metadata_get',
                return_value={'key2': 'value2'})
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_delete(self, snapshot_get_by_id, snapshot_metadata_get,
                    snapshot_metadata_delete):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key2')
        req.method = 'DELETE'
        res = self.controller.delete(req, self.req_id, 'key2')

        self.assertEqual(200, res.status_int)

    def test_delete_nonexistent_snapshot(self):
        self.stubs.Set(cinder.db, 'snapshot_get',
                       return_snapshot_nonexistent)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, self.req_id, 'key1')

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_delete_meta_not_found(self, snapshot_get_by_id,
                                   snapshot_metadata_get):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key6')
        req.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPNotFound,
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
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_get',
                       return_empty_snapshot_metadata)
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)

        req = fakes.HTTPRequest.blank('/v1/snapshot_metadata')
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"metadata": {"key1": "value1",
                             "key2": "value2",
                             "key3": "value3"}}
        req.body = jsonutils.dumps(body)
        res_dict = self.controller.create(req, self.req_id, body)
        self.assertEqual(body, res_dict)

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_create_with_keys_in_uppercase_and_lowercase(
            self, snapshot_get_by_id, snapshot_update, snapshot_metadata_get):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        # if the keys in uppercase_and_lowercase, should return the one
        # which server added
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata_insensitive)

        req = fakes.HTTPRequest.blank('/v1/snapshot_metadata')
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
        req.body = jsonutils.dumps(body)
        res_dict = self.controller.create(req, self.req_id, body)
        self.assertEqual(expected, res_dict)

    def test_create_empty_body(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, self.req_id, None)

    def test_create_item_empty_key(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"": "value1"}}
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, self.req_id, body)

    def test_create_item_key_too_long(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {("a" * 260): "value1"}}
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req, self.req_id, body)

    def test_create_nonexistent_snapshot(self):
        self.stubs.Set(cinder.db, 'snapshot_get',
                       return_snapshot_nonexistent)
        self.stubs.Set(cinder.db, 'snapshot_metadata_get',
                       return_snapshot_metadata)
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)

        req = fakes.HTTPRequest.blank('/v1/snapshot_metadata')
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"metadata": {"key9": "value9"}}
        req.body = jsonutils.dumps(body)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.create, req, self.req_id, body)

    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_all(self, snapshot_get_by_id, snapshot_update):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': []
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_new_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {
            'metadata': {
                'key10': 'value10',
                'key99': 'value99',
                'KEY20': 'value20',
            },
        }
        req.body = jsonutils.dumps(expected)
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
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_get',
                       return_create_snapshot_metadata)
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_new_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
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
        req.body = jsonutils.dumps(expected)
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
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_empty_container_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': {}}
        req.body = jsonutils.dumps(expected)
        res_dict = self.controller.update_all(req, self.req_id, expected)

        self.assertEqual(expected, res_dict)

    def test_update_all_malformed_container(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'meta': {}}
        req.body = jsonutils.dumps(expected)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update_all, req, self.req_id,
                          expected)

    def test_update_all_malformed_data(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': ['asdf']}
        req.body = jsonutils.dumps(expected)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update_all, req, self.req_id,
                          expected)

    def test_update_all_nonexistent_snapshot(self):
        self.stubs.Set(cinder.db, 'snapshot_get', return_snapshot_nonexistent)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        body = {'metadata': {'key10': 'value10'}}
        req.body = jsonutils.dumps(body)

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update_all, req, '100', body)

    @mock.patch('cinder.db.snapshot_metadata_update', return_value=dict())
    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_item(self, snapshot_get_by_id, snapshot_metadata_get,
                         snapshot_update, snapshot_metadata_update):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res_dict = self.controller.update(req, self.req_id, 'key1', body)
        expected = {'meta': {'key1': 'value1'}}
        self.assertEqual(expected, res_dict)

    def test_update_item_nonexistent_snapshot(self):
        self.stubs.Set(cinder.db, 'snapshot_get',
                       return_snapshot_nonexistent)
        req = fakes.HTTPRequest.blank(
            '/v1.1/fake/snapshots/asdf/metadata/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update, req, self.req_id, 'key1',
                          body)

    def test_update_item_empty_body(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.req_id, 'key1',
                          None)

    def test_update_item_empty_key(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"": "value1"}}
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.req_id, '', body)

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_item_key_too_long(self, snapshot_get_by_id,
                                      snapshot_metadata_get):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {("a" * 260): "value1"}}
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update,
                          req, self.req_id, ("a" * 260), body)

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_item_value_too_long(self, snapshot_get_by_id,
                                        snapshot_metadata_get):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": ("a" * 260)}}
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update,
                          req, self.req_id, "key1", body)

    def test_update_item_too_many_keys(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1", "key2": "value2"}}
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.req_id, 'key1',
                          body)

    def test_update_item_body_uri_mismatch(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/bad')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.req_id, 'bad',
                          body)

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_invalid_metadata_items_on_create(self, snapshot_get_by_id,
                                              snapshot_metadata_get):
        snapshot = {
            'id': self.req_id,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext('admin', 'fake', True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        # test for long key
        data = {"metadata": {"a" * 260: "value1"}}
        req.body = jsonutils.dumps(data)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, self.req_id, data)

        # test for long value
        data = {"metadata": {"key": "v" * 260}}
        req.body = jsonutils.dumps(data)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, self.req_id, data)

        # test for empty key.
        data = {"metadata": {"": "value1"}}
        req.body = jsonutils.dumps(data)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, self.req_id, data)
