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
from oslo_config import cfg
from oslo_serialization import jsonutils
import webob

from cinder.api import extensions
from cinder.api.v1 import volume_metadata
from cinder.api.v1 import volumes
import cinder.db
from cinder import exception as exc
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v1 import stubs
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder import volume


CONF = cfg.CONF


def return_create_volume_metadata_max(context, volume_id, metadata, delete):
    return stub_max_volume_metadata(volume_id)


def return_create_volume_metadata(context, volume_id, metadata, delete,
                                  meta_type):
    return stub_volume_metadata(volume_id)


def return_new_volume_metadata(context, volume_id, metadata,
                               delete, meta_type):
    return stub_new_volume_metadata(volume_id)


def return_create_volume_metadata_insensitive(context, volume_id,
                                              metadata, delete,
                                              meta_type):
    return stub_volume_metadata_insensitive(volume_id)


def return_volume_metadata(context, volume_id):
    return stub_volume_metadata(volume_id)


def return_empty_volume_metadata(context, volume_id):
    if volume_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.VolumeNotFound(volume_id)
    return {}


def return_empty_container_metadata(context, volume_id, metadata,
                                    delete, meta_type):
    if volume_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.VolumeNotFound(volume_id)
    return {}


def delete_volume_metadata(context, volume_id, key, meta_type):
    if volume_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.VolumeNotFound(volume_id)
    pass


def stub_volume_metadata(volume_id):
    if volume_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.VolumeNotFound(volume_id)
    metadata = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
    }
    return metadata


def stub_new_volume_metadata(volume_id):
    if volume_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.VolumeNotFound(volume_id)
    metadata = {
        'key10': 'value10',
        'key99': 'value99',
        'KEY20': 'value20',
    }
    return metadata


def stub_volume_metadata_insensitive(volume_id):
    if volume_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.VolumeNotFound(volume_id)
    metadata = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
        "KEY4": "value4",
    }
    return metadata


def stub_max_volume_metadata(volume_id):
    if volume_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.VolumeNotFound(volume_id)
    metadata = {"metadata": {}}
    for num in range(CONF.quota_metadata_items):
        metadata['metadata']['key%i' % num] = "blah"
    return metadata


def get_volume(self, context, volume_id, *args, **kwargs):
    if volume_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exc.VolumeNotFound('bogus test message')
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


class volumeMetaDataTest(test.TestCase):

    def setUp(self):
        super(volumeMetaDataTest, self).setUp()
        self.volume_api = cinder.volume.api.API()
        self.stubs.Set(volume.api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(cinder.db, 'volume_metadata_get',
                       return_volume_metadata)
        self.patch(
            'cinder.db.service_get_all', autospec=True,
            return_value=stubs.stub_service_get_all(None))

        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.volume_controller = volumes.VolumeController(self.ext_mgr)
        self.controller = volume_metadata.Controller()
        self.url = '/v1/%s/volumes/%s/metadata' % (
            fake.PROJECT_ID, fake.VOLUME_ID)

        vol = {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1",
               "metadata": {}}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        self.volume_controller.create(req, body)

    def test_index(self):
        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.index(req, fake.VOLUME_ID)

        expected = {
            'metadata': {
                'key1': 'value1',
                'key2': 'value2',
                'key3': 'value3',
            },
        }
        self.assertEqual(expected, res_dict)

    def test_index_nonexistent_volume(self):
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(exc.VolumeNotFound,
                          self.controller.index,
                          req, fake.WILL_NOT_BE_FOUND_ID)

    def test_index_no_metadata(self):
        self.stubs.Set(cinder.db, 'volume_metadata_get',
                       return_empty_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.index(req, fake.VOLUME_ID)
        expected = {'metadata': {}}
        self.assertEqual(expected, res_dict)

    def test_show(self):
        req = fakes.HTTPRequest.blank(self.url + '/key2')
        res_dict = self.controller.show(req, fake.VOLUME_ID, 'key2')
        expected = {'meta': {'key2': 'value2'}}
        self.assertEqual(expected, res_dict)

    def test_show_nonexistent_volume(self):
        req = fakes.HTTPRequest.blank(self.url + '/key2')
        self.assertRaises(exc.VolumeNotFound,
                          self.controller.show, req,
                          fake.WILL_NOT_BE_FOUND_ID, 'key2')

    def test_show_meta_not_found(self):
        self.stubs.Set(cinder.db, 'volume_metadata_get',
                       return_empty_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key6')
        self.assertRaises(exc.VolumeMetadataNotFound,
                          self.controller.show, req, fake.VOLUME_ID, 'key6')

    @mock.patch.object(cinder.db, 'volume_metadata_delete')
    @mock.patch.object(cinder.db, 'volume_metadata_get')
    def test_delete(self, metadata_get, metadata_delete):
        fake_volume = objects.Volume(id=fake.VOLUME_ID, status='available')
        fake_context = mock.Mock()
        metadata_get.side_effect = return_volume_metadata
        metadata_delete.side_effect = delete_volume_metadata
        req = fakes.HTTPRequest.blank(self.url + '/key2')
        req.method = 'DELETE'
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            res = self.controller.delete(req, fake.VOLUME_ID, 'key2')
            self.assertEqual(200, res.status_int)
            get_volume.assert_called_with(fake_context, fake.VOLUME_ID)

    @mock.patch.object(cinder.db, 'volume_metadata_get')
    def test_delete_nonexistent_volume(self, metadata_get):
        fake_context = mock.Mock()
        metadata_get.side_effect = return_volume_metadata
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'DELETE'
        req.environ['cinder.context'] = fake_context

        self.assertRaises(exc.VolumeNotFound, self.controller.delete,
                          req, fake.WILL_NOT_BE_FOUND_ID, 'key1')

    def test_delete_meta_not_found(self):
        self.stubs.Set(cinder.db, 'volume_metadata_get',
                       return_empty_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key6')
        req.method = 'DELETE'
        self.assertRaises(exc.VolumeMetadataNotFound,
                          self.controller.delete, req, fake.VOLUME_ID, 'key6')

    @mock.patch.object(cinder.db, 'volume_metadata_update')
    @mock.patch.object(cinder.db, 'volume_metadata_get')
    def test_create(self, metadata_get, metadata_update):
        fake_volume = {'id': fake.VOLUME_ID, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_get.side_effect = return_empty_volume_metadata
        metadata_update.side_effect = return_create_volume_metadata
        req = fakes.HTTPRequest.blank('/v1/volume_metadata')
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"metadata": {"key1": "value1",
                             "key2": "value2",
                             "key3": "value3", }}
        req.body = jsonutils.dump_as_bytes(body)
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            res_dict = self.controller.create(req, fake.VOLUME_ID, body)
            self.assertEqual(body, res_dict)

    @mock.patch.object(cinder.db, 'volume_metadata_update')
    @mock.patch.object(cinder.db, 'volume_metadata_get')
    def test_create_with_keys_in_uppercase_and_lowercase(self, metadata_get,
                                                         metadata_update):
        # if the keys in uppercase_and_lowercase, should return the one
        # which server added
        fake_volume = {'id': fake.VOLUME_ID, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_get.side_effect = return_empty_volume_metadata
        metadata_update.side_effect = return_create_volume_metadata_insensitive

        req = fakes.HTTPRequest.blank('/v1/volume_metadata')
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
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            res_dict = self.controller.create(req, fake.VOLUME_ID, body)
            self.assertEqual(expected, res_dict)

    def test_create_empty_body(self):
        self.stubs.Set(cinder.db, 'volume_metadata_update',
                       return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, fake.VOLUME_ID, None)

    def test_create_item_empty_key(self):
        self.stubs.Set(cinder.db, 'volume_metadata_update',
                       return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, fake.VOLUME_ID, body)

    def test_create_item_key_too_long(self):
        self.stubs.Set(cinder.db, 'volume_metadata_update',
                       return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {("a" * 260): "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req, fake.VOLUME_ID, body)

    def test_create_nonexistent_volume(self):
        self.stubs.Set(cinder.db, 'volume_metadata_get',
                       return_volume_metadata)
        self.stubs.Set(cinder.db, 'volume_metadata_update',
                       return_create_volume_metadata)

        req = fakes.HTTPRequest.blank('/v1/volume_metadata')
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"metadata": {"key9": "value9"}}
        req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exc.VolumeNotFound,
                          self.controller.create, req,
                          fake.WILL_NOT_BE_FOUND_ID, body)

    @mock.patch.object(cinder.db, 'volume_metadata_update')
    def test_update_all(self, metadata_update):
        fake_volume = {'id': fake.VOLUME_ID, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_update.side_effect = return_new_volume_metadata
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
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            res_dict = self.controller.update_all(req, fake.VOLUME_ID,
                                                  expected)
            self.assertEqual(expected, res_dict)
            get_volume.assert_called_once_with(fake_context, fake.VOLUME_ID)

    @mock.patch.object(cinder.db, 'volume_metadata_update')
    @mock.patch.object(cinder.db, 'volume_metadata_get')
    def test_update_all_with_keys_in_uppercase_and_lowercase(self,
                                                             metadata_get,
                                                             metadata_update):
        fake_volume = {'id': fake.VOLUME_ID, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_get.side_effect = return_create_volume_metadata
        metadata_update.side_effect = return_new_volume_metadata
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
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            res_dict = self.controller.update_all(req, fake.VOLUME_ID, body)
            self.assertEqual(expected, res_dict)
            get_volume.assert_called_once_with(fake_context, fake.VOLUME_ID)

    @mock.patch.object(cinder.db, 'volume_metadata_update')
    def test_update_all_empty_container(self, metadata_update):
        fake_volume = {'id': fake.VOLUME_ID, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_update.side_effect = return_empty_container_metadata
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': {}}
        req.body = jsonutils.dump_as_bytes(expected)
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            res_dict = self.controller.update_all(req, fake.VOLUME_ID,
                                                  expected)
            self.assertEqual(expected, res_dict)
            get_volume.assert_called_once_with(fake_context, fake.VOLUME_ID)

    @mock.patch.object(cinder.db, 'volume_metadata_update')
    def test_update_item_value_too_long(self, metadata_update):
        fake_volume = {'id': fake.VOLUME_ID, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_update.side_effect = return_create_volume_metadata
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": ("a" * 260)}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                              self.controller.update,
                              req, fake.VOLUME_ID, "key1", body)
            self.assertFalse(metadata_update.called)
            get_volume.assert_called_once_with(fake_context, fake.VOLUME_ID)

    def test_update_all_malformed_container(self):
        self.stubs.Set(cinder.db, 'volume_metadata_update',
                       return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'meta': {}}
        req.body = jsonutils.dump_as_bytes(expected)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update_all, req, fake.VOLUME_ID,
                          expected)

    @mock.patch.object(cinder.db, 'volume_metadata_update')
    def test_update_all_malformed_data(self, metadata_update):
        fake_volume = {'id': fake.VOLUME_ID, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_update.side_effect = return_create_volume_metadata
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': ['asdf']}
        req.body = jsonutils.dump_as_bytes(expected)
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.controller.update_all, req, fake.VOLUME_ID,
                              expected)

    def test_update_all_nonexistent_volume(self):
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        body = {'metadata': {'key10': 'value10'}}
        req.body = jsonutils.dump_as_bytes(body)

        self.assertRaises(exc.VolumeNotFound,
                          self.controller.update_all, req,
                          fake.WILL_NOT_BE_FOUND_ID, body)

    @mock.patch.object(cinder.db, 'volume_metadata_update')
    def test_update_item(self, metadata_update):
        fake_volume = {'id': fake.VOLUME_ID, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_update.side_effect = return_create_volume_metadata
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            res_dict = self.controller.update(req, fake.VOLUME_ID, 'key1',
                                              body)
            expected = {'meta': {'key1': 'value1'}}
            self.assertEqual(expected, res_dict)
            get_volume.assert_called_once_with(fake_context, fake.VOLUME_ID)

    def test_update_item_nonexistent_volume(self):
        req = fakes.HTTPRequest.blank(
            '/v1.1/%s/volumes/%s/metadata/key1' % (
                fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID))
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(exc.VolumeNotFound,
                          self.controller.update, req,
                          fake.WILL_NOT_BE_FOUND_ID, 'key1',
                          body)

    def test_update_item_empty_body(self):
        self.stubs.Set(cinder.db, 'volume_metadata_update',
                       return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, fake.VOLUME_ID, 'key1',
                          None)

    @mock.patch.object(cinder.db, 'volume_metadata_update')
    def test_update_item_empty_key(self, metadata_update):
        fake_volume = {'id': fake.VOLUME_ID, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_update.side_effect = return_create_volume_metadata
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.controller.update, req, fake.VOLUME_ID,
                              '', body)
            self.assertFalse(metadata_update.called)
            get_volume.assert_called_once_with(fake_context, fake.VOLUME_ID)

    @mock.patch.object(cinder.db, 'volume_metadata_update')
    def test_update_item_key_too_long(self, metadata_update):
        fake_volume = {'id': fake.VOLUME_ID, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_update.side_effect = return_create_volume_metadata
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {("a" * 260): "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                              self.controller.update,
                              req, fake.VOLUME_ID, ("a" * 260), body)
            self.assertFalse(metadata_update.called)
            get_volume.assert_called_once_with(fake_context, fake.VOLUME_ID)

    def test_update_item_too_many_keys(self):
        self.stubs.Set(cinder.db, 'volume_metadata_update',
                       return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1", "key2": "value2"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, fake.VOLUME_ID, 'key1',
                          body)

    def test_update_item_body_uri_mismatch(self):
        self.stubs.Set(cinder.db, 'volume_metadata_update',
                       return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/bad')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, fake.VOLUME_ID, 'bad',
                          body)

    @mock.patch.object(cinder.db, 'volume_metadata_update')
    def test_invalid_metadata_items_on_create(self, metadata_update):
        fake_volume = {'id': fake.VOLUME_ID, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_update.side_effect = return_create_volume_metadata
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        # test for long key
        data = {"metadata": {"a" * 260: "value1"}}
        req.body = jsonutils.dump_as_bytes(data)
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                              self.controller.create, req,
                              fake.VOLUME_ID, data)

        # test for long value
        data = {"metadata": {"key": "v" * 260}}
        req.body = jsonutils.dump_as_bytes(data)
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                              self.controller.create, req,
                              fake.VOLUME_ID, data)

        # test for empty key.
        data = {"metadata": {"": "value1"}}
        req.body = jsonutils.dump_as_bytes(data)
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.controller.create, req,
                              fake.VOLUME_ID, data)
