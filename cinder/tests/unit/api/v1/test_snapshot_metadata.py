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
import mock
from oslo_serialization import jsonutils
import webob

from cinder.api import extensions
from cinder.api.v1 import snapshot_metadata
from cinder.api.v1 import snapshots
from cinder import context
import cinder.db
from cinder import exception as exc
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder import volume


def return_create_snapshot_metadata(context, snapshot_id, metadata, delete):
    return stub_snapshot_metadata(snapshot_id)


def return_create_snapshot_metadata_insensitive(context, snapshot_id,
                                                metadata, delete):
    return stub_snapshot_metadata_insensitive(snapshot_id)


def return_new_snapshot_metadata(context, snapshot_id, metadata, delete):
    return stub_new_snapshot_metadata(snapshot_id)


def return_empty_container_metadata(context, snapshot_id, metadata, delete):
    if snapshot_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.SnapshotNotFound(snapshot_id)
    return {}


def stub_snapshot_metadata(snapshot_id):
    if snapshot_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.SnapshotNotFound(snapshot_id)
    metadata = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
    }
    return metadata


def stub_snapshot_metadata_insensitive(snapshot_id):
    if snapshot_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.SnapshotNotFound(snapshot_id)
    metadata = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
        "KEY4": "value4",
    }
    return metadata


def stub_new_snapshot_metadata(snapshot_id):
    if snapshot_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.SnapshotNotFound(snapshot_id)
    metadata = {
        'key10': 'value10',
        'key99': 'value99',
        'KEY20': 'value20',
    }
    return metadata


def return_snapshot(context, snapshot_id):
    if snapshot_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.SnapshotNotFound(snapshot_id)
    return {'id': '0cc3346e-9fef-4445-abe6-5d2b2690ec64',
            'name': 'fake',
            'status': 'available',
            'metadata': {}}


def stub_get(self, context, volume_id, *args, **kwargs):
    if volume_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.VolumeNotFound(volume_id)
    vol = {'id': volume_id,
           'size': 100,
           'name': 'fake',
           'host': 'fake-host',
           'status': 'available',
           'encryption_key_id': None,
           'volume_type_id': None,
           'migration_status': None,
           'availability_zone': 'zone1:host1',
           'attach_status': fields.VolumeAttachStatus.DETACHED}
    return fake_volume.fake_volume_obj(context, **vol)


def fake_update_snapshot_metadata(self, context, snapshot, diff):
    pass


class SnapshotMetaDataTest(test.TestCase):

    def setUp(self):
        super(SnapshotMetaDataTest, self).setUp()
        self.volume_api = cinder.volume.api.API()
        self.stubs.Set(volume.api.API, 'get', stub_get)
        self.stubs.Set(cinder.db, 'snapshot_get', return_snapshot)

        self.stubs.Set(self.volume_api, 'update_snapshot_metadata',
                       fake_update_snapshot_metadata)
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.snapshot_controller = snapshots.SnapshotsController(self.ext_mgr)
        self.controller = snapshot_metadata.Controller()
        self.url = '/v1/%s/snapshots/%s/metadata' % (
            fake.PROJECT_ID, fake.SNAPSHOT_ID)

        snap = {"volume_size": 100,
                "volume_id": fake.VOLUME_ID,
                "display_name": "Snapshot Test Name",
                "display_description": "Snapshot Test Desc",
                "availability_zone": "zone1:host1",
                "host": "fake-host",
                "metadata": {}}
        body = {"snapshot": snap}
        req = fakes.HTTPRequest.blank('/v1/snapshots')
        self.snapshot_controller.create(req, body)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_index(self, snapshot_get_by_id):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_obj['metadata'] = {'key1': 'value1',
                                    'key2': 'value2',
                                    'key3': 'value3'}
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.index(req, fake.SNAPSHOT_ID)

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
            exc.SnapshotNotFound(snapshot_id=fake.WILL_NOT_BE_FOUND_ID)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(exc.SnapshotNotFound,
                          self.controller.index, req, self.url)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_index_no_data(self, snapshot_get_by_id):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.index(req, fake.SNAPSHOT_ID)
        expected = {'metadata': {}}
        self.assertEqual(expected, res_dict)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_show(self, snapshot_get_by_id):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_obj['metadata'] = {'key2': 'value2'}
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key2')
        res_dict = self.controller.show(req, fake.SNAPSHOT_ID, 'key2')
        expected = {'meta': {'key2': 'value2'}}
        self.assertEqual(expected, res_dict)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_show_nonexistent_snapshot(self, snapshot_get_by_id):
        snapshot_get_by_id.side_effect = \
            exc.SnapshotNotFound(snapshot_id=fake.WILL_NOT_BE_FOUND_ID)

        req = fakes.HTTPRequest.blank(self.url + '/key2')
        self.assertRaises(exc.SnapshotNotFound,
                          self.controller.show, req, fake.SNAPSHOT_ID, 'key2')

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_show_meta_not_found(self, snapshot_get_by_id):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key6')
        self.assertRaises(exc.SnapshotMetadataNotFound,
                          self.controller.show, req, fake.SNAPSHOT_ID, 'key6')

    @mock.patch('cinder.db.snapshot_metadata_delete')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_delete(self, snapshot_get_by_id, snapshot_metadata_delete):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_obj['metadata'] = {'key2': 'value2'}
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key2')
        req.method = 'DELETE'
        res = self.controller.delete(req, fake.SNAPSHOT_ID, 'key2')

        self.assertEqual(200, res.status_int)

    def test_delete_nonexistent_snapshot(self):
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'DELETE'
        self.assertRaises(exc.SnapshotNotFound,
                          self.controller.delete, req,
                          fake.WILL_NOT_BE_FOUND_ID, 'key1')

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_delete_meta_not_found(self, snapshot_get_by_id):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key6')
        req.method = 'DELETE'
        self.assertRaises(exc.SnapshotMetadataNotFound,
                          self.controller.delete, req,
                          fake.SNAPSHOT_ID, 'key6')

    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_create(self, snapshot_get_by_id, volume_get_by_id,
                    snapshot_update):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)

        req = fakes.HTTPRequest.blank('/v1/snapshot_metadata')
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"metadata": {"key1": "value1",
                             "key2": "value2",
                             "key3": "value3"}}
        req.body = jsonutils.dump_as_bytes(body)
        res_dict = self.controller.create(req, fake.SNAPSHOT_ID, body)
        self.assertEqual(body, res_dict)

    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_create_with_keys_in_uppercase_and_lowercase(
            self, snapshot_get_by_id, snapshot_update):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
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
        req.body = jsonutils.dump_as_bytes(body)
        res_dict = self.controller.create(req, fake.SNAPSHOT_ID, body)
        self.assertEqual(expected, res_dict)

    def test_create_empty_body(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, fake.SNAPSHOT_ID, None)

    def test_create_item_empty_key(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, fake.SNAPSHOT_ID, body)

    def test_create_item_key_too_long(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {("a" * 260): "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req, fake.SNAPSHOT_ID, body)

    def test_create_nonexistent_snapshot(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)

        req = fakes.HTTPRequest.blank('/v1/snapshot_metadata')
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"metadata": {"key9": "value9"}}
        req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exc.SnapshotNotFound,
                          self.controller.create, req,
                          fake.WILL_NOT_BE_FOUND_ID, body)

    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_all(self, snapshot_get_by_id, snapshot_update):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': []
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
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
        req.body = jsonutils.dump_as_bytes(expected)
        res_dict = self.controller.update_all(req, fake.SNAPSHOT_ID, expected)

        self.assertEqual(expected, res_dict)

    @mock.patch('cinder.db.snapshot_update',
                return_value={'key10': 'value10',
                              'key99': 'value99',
                              'KEY20': 'value20'})
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_all_with_keys_in_uppercase_and_lowercase(
            self, snapshot_get_by_id, snapshot_update):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

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
        req.body = jsonutils.dump_as_bytes(expected)
        res_dict = self.controller.update_all(req, fake.SNAPSHOT_ID, body)

        self.assertEqual(expected, res_dict)

    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_all_empty_container(self, snapshot_get_by_id,
                                        snapshot_update):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': []
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_empty_container_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': {}}
        req.body = jsonutils.dump_as_bytes(expected)
        res_dict = self.controller.update_all(req, fake.SNAPSHOT_ID, expected)

        self.assertEqual(expected, res_dict)

    def test_update_all_malformed_container(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'meta': {}}
        req.body = jsonutils.dump_as_bytes(expected)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update_all, req, fake.SNAPSHOT_ID,
                          expected)

    @mock.patch('cinder.db.sqlalchemy.api._snapshot_get')
    @mock.patch('cinder.db.snapshot_metadata_update', autospec=True)
    def test_update_all_malformed_data(self, metadata_update, snapshot_get):
        snapshot_get.return_value = stub_get
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': ['asdf']}
        req.body = jsonutils.dump_as_bytes(expected)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update_all, req, fake.SNAPSHOT_ID,
                          expected)

    def test_update_all_nonexistent_snapshot(self):
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        body = {'metadata': {'key10': 'value10'}}
        req.body = jsonutils.dump_as_bytes(body)

        self.assertRaises(exc.SnapshotNotFound,
                          self.controller.update_all, req,
                          fake.WILL_NOT_BE_FOUND_ID, body)

    @mock.patch('cinder.db.snapshot_metadata_update', return_value=dict())
    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_item(self, snapshot_get_by_id,
                         snapshot_update, snapshot_metadata_update):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"
        res_dict = self.controller.update(req, fake.SNAPSHOT_ID, 'key1', body)
        expected = {'meta': {'key1': 'value1'}}
        self.assertEqual(expected, res_dict)

    def test_update_item_nonexistent_snapshot(self):
        req = fakes.HTTPRequest.blank(
            '/v1.1/fake/snapshots/asdf/metadata/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(exc.SnapshotNotFound,
                          self.controller.update, req,
                          fake.WILL_NOT_BE_FOUND_ID, 'key1',
                          body)

    def test_update_item_empty_body(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req,
                          fake.SNAPSHOT_ID, 'key1',
                          None)

    @mock.patch('cinder.db.sqlalchemy.api._snapshot_get')
    @mock.patch('cinder.db.snapshot_metadata_update', autospec=True)
    def test_update_item_empty_key(self, metadata_update, snapshot_get):
        snapshot_get.return_value = stub_get
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req,
                          fake.SNAPSHOT_ID, '', body)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_item_key_too_long(self, snapshot_get_by_id):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {("a" * 260): "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update,
                          req, fake.SNAPSHOT_ID, ("a" * 260), body)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_update_item_value_too_long(self, snapshot_get_by_id):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": ("a" * 260)}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update,
                          req, fake.SNAPSHOT_ID, "key1", body)

    def test_update_item_too_many_keys(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1", "key2": "value2"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req,
                          fake.SNAPSHOT_ID, 'key1',
                          body)

    def test_update_item_body_uri_mismatch(self):
        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/bad')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, fake.SNAPSHOT_ID, 'bad',
                          body)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_invalid_metadata_items_on_create(self, snapshot_get_by_id):
        snapshot = {
            'id': fake.SNAPSHOT_ID,
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        snapshot_get_by_id.return_value = snapshot_obj

        self.stubs.Set(cinder.db, 'snapshot_metadata_update',
                       return_create_snapshot_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        # test for long key
        data = {"metadata": {"a" * 260: "value1"}}
        req.body = jsonutils.dump_as_bytes(data)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, fake.SNAPSHOT_ID, data)

        # test for long value
        data = {"metadata": {"key": "v" * 260}}
        req.body = jsonutils.dump_as_bytes(data)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, fake.SNAPSHOT_ID, data)

        # test for empty key.
        data = {"metadata": {"": "value1"}}
        req.body = jsonutils.dump_as_bytes(data)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, fake.SNAPSHOT_ID, data)
