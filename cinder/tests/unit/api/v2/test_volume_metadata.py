# Copyright 2013 OpenStack Foundation.
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

from oslo_config import cfg
from oslo_serialization import jsonutils
import webob

from cinder.api import extensions
from cinder.api.v2 import volume_metadata
from cinder.api.v2 import volumes
from cinder import db
from cinder import exception
from cinder import objects
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder import volume
from cinder.volume import api as volume_api


CONF = cfg.CONF


def return_create_volume_metadata_max(context, volume_id, metadata, delete):
    return fake_max_volume_metadata()


def return_create_volume_metadata(context, volume_id, metadata,
                                  delete, meta_type):
    return fake_volume_metadata()


def return_new_volume_metadata(context, volume_id, metadata,
                               delete, meta_type):
    return fake_new_volume_metadata()


def return_create_volume_metadata_insensitive(context, snapshot_id,
                                              metadata, delete,
                                              meta_type):
    return fake_volume_metadata_insensitive()


def return_volume_metadata(context, volume_id):
    return fake_volume_metadata()


def fake_volume_metadata():
    metadata = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
    }
    return metadata


def fake_new_volume_metadata():
    metadata = {
        'key10': 'value10',
        'key99': 'value99',
        'KEY20': 'value20',
    }
    return metadata


def fake_volume_metadata_insensitive():
    metadata = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
        "KEY4": "value4",
    }
    return metadata


def fake_max_volume_metadata():
    metadata = {"metadata": {}}
    for num in range(CONF.quota_metadata_items):
        metadata['metadata']['key%i' % num] = "blah"
    return metadata


def get_volume(*args, **kwargs):
    vol = {'name': 'fake',
           'metadata': {},
           'project_id': fake.PROJECT_ID
           }
    return fake_volume.fake_volume_obj(args[0], **vol)


def return_volume_nonexistent(*args, **kwargs):
    raise exception.VolumeNotFound('bogus test message')


class VolumeMetaDataTest(test.TestCase):

    def setUp(self):
        super(VolumeMetaDataTest, self).setUp()
        self.volume_api = volume_api.API()
        self.mock_object(volume.api.API, 'get', get_volume)
        self.mock_object(db, 'volume_metadata_get',
                         return_volume_metadata)
        self.mock_object(db, 'service_get_all',
                         return_value=v2_fakes.fake_service_get_all_by_topic(
                             None, None),
                         autospec=True)
        self.mock_object(self.volume_api, 'update_volume_metadata')

        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.volume_controller = volumes.VolumeController(self.ext_mgr)
        self.controller = volume_metadata.Controller()
        self.req_id = fake.REQUEST_ID
        self.url = '/v2/%s/volumes/%s/metadata' % (
            fake.PROJECT_ID, self.req_id)

        vol = {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1",
               "metadata": {},
               "volume_type": self.vt['id']}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/%s/volumes' % fake.PROJECT_ID)
        self.volume_controller.create(req, body=body)

    def test_index(self):
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

    def test_index_nonexistent_volume(self):
        self.mock_object(db, 'volume_metadata_get',
                         return_volume_nonexistent)
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(exception.VolumeNotFound,
                          self.controller.index, req, self.url)

    def test_index_no_data(self):
        self.mock_object(db, 'volume_metadata_get',
                         return_value={})
        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.index(req, self.req_id)
        expected = {'metadata': {}}
        self.assertEqual(expected, res_dict)

    def test_show(self):
        req = fakes.HTTPRequest.blank(self.url + '/key2')
        res_dict = self.controller.show(req, self.req_id, 'key2')
        expected = {'meta': {'key2': 'value2'}}
        self.assertEqual(expected, res_dict)

    def test_show_nonexistent_volume(self):
        self.mock_object(db, 'volume_metadata_get',
                         return_volume_nonexistent)
        req = fakes.HTTPRequest.blank(self.url + '/key2')
        self.assertRaises(exception.VolumeNotFound,
                          self.controller.show, req, self.req_id, 'key2')

    def test_show_meta_not_found(self):
        self.mock_object(db, 'volume_metadata_get',
                         return_value={})
        req = fakes.HTTPRequest.blank(self.url + '/key6')
        self.assertRaises(exception.VolumeMetadataNotFound,
                          self.controller.show, req, self.req_id, 'key6')

    @mock.patch.object(db, 'volume_metadata_delete')
    @mock.patch.object(db, 'volume_metadata_get')
    def test_delete(self, metadata_get, metadata_delete):
        fake_volume = objects.Volume(id=self.req_id, status='available')
        fake_context = mock.Mock()
        metadata_get.side_effect = return_volume_metadata
        req = fakes.HTTPRequest.blank(self.url + '/key2')
        req.method = 'DELETE'
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            res = self.controller.delete(req, self.req_id, 'key2')
            self.assertEqual(HTTPStatus.OK, res.status_int)
            get_volume.assert_called_once_with(fake_context, self.req_id)

    @mock.patch.object(db, 'volume_metadata_delete')
    @mock.patch.object(db, 'volume_metadata_get')
    def test_delete_volume_maintenance(self, metadata_get, metadata_delete):
        fake_volume = objects.Volume(id=self.req_id, status='maintenance')
        fake_context = mock.Mock()
        metadata_get.side_effect = return_volume_metadata
        req = fakes.HTTPRequest.blank(self.url + '/key2')
        req.method = 'DELETE'
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            self.assertRaises(exception.InvalidVolume,
                              self.controller.delete, req,
                              self.req_id, 'key2')
            get_volume.assert_called_once_with(fake_context, self.req_id)

    @mock.patch.object(db, 'volume_metadata_delete')
    @mock.patch.object(db, 'volume_metadata_get')
    def test_delete_nonexistent_volume(self, metadata_get, metadata_delete):
        fake_volume = objects.Volume(id=self.req_id, status='available')
        fake_context = mock.Mock()
        metadata_get.side_effect = return_volume_metadata
        metadata_delete.side_effect = return_volume_nonexistent
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'DELETE'
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            self.assertRaises(exception.VolumeNotFound,
                              self.controller.delete, req,
                              self.req_id, 'key1')
            get_volume.assert_called_once_with(fake_context, self.req_id)

    def test_delete_meta_not_found(self):
        self.mock_object(db, 'volume_metadata_get',
                         return_value={})
        req = fakes.HTTPRequest.blank(self.url + '/key6')
        req.method = 'DELETE'
        self.assertRaises(exception.VolumeMetadataNotFound,
                          self.controller.delete, req, self.req_id, 'key6')

    @mock.patch.object(db, 'volume_metadata_update')
    @mock.patch.object(db, 'volume_metadata_get')
    def test_create(self, metadata_get, metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_get.return_value = {}
        metadata_update.side_effect = return_create_volume_metadata
        req = fakes.HTTPRequest.blank('/v2/volume_metadata')
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
            res_dict = self.controller.create(req, self.req_id, body=body)
            self.assertEqual(body, res_dict)

    @mock.patch.object(db, 'volume_metadata_update')
    @mock.patch.object(db, 'volume_metadata_get')
    def test_create_volume_maintenance(self, metadata_get, metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'maintenance'}
        fake_context = mock.Mock()
        metadata_get.return_value = {}
        metadata_update.side_effect = return_create_volume_metadata
        req = fakes.HTTPRequest.blank('/v2/volume_metadata')
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
            self.assertRaises(exception.InvalidVolume,
                              self.controller.create,
                              req, self.req_id, body=body)

    @mock.patch.object(db, 'volume_metadata_update')
    @mock.patch.object(db, 'volume_metadata_get')
    def test_create_with_keys_in_uppercase_and_lowercase(self, metadata_get,
                                                         metadata_update):
        # if the keys in uppercase_and_lowercase, should return the one
        # which server added
        fake_volume = {'id': self.req_id, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_get.return_value = {}
        metadata_update.side_effect = return_create_volume_metadata_insensitive

        req = fakes.HTTPRequest.blank('/v2/volume_metadata')
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
            res_dict = self.controller.create(req, self.req_id, body=body)
            self.assertEqual(expected, res_dict)

    def test_create_empty_body(self):
        self.mock_object(db, 'volume_metadata_update',
                         return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, self.req_id, body=None)

    def test_create_metadata_keys_value_none(self):
        self.mock_object(db, 'volume_metadata_update',
                         return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'POST'
        req.headers["content-type"] = "application/json"
        body = {"meta": {"key": None}}
        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, self.req_id, body=body)

    def test_create_item_empty_key(self):
        self.mock_object(db, 'volume_metadata_update',
                         return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, self.req_id, body=body)

    def test_create_item_key_too_long(self):
        self.mock_object(db, 'volume_metadata_update',
                         return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {("a" * 260): "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          req, self.req_id, body=body)

    def test_create_nonexistent_volume(self):
        self.mock_object(volume.api.API, 'get',
                         return_volume_nonexistent)
        self.mock_object(db, 'volume_metadata_get',
                         return_volume_metadata)
        self.mock_object(db, 'volume_metadata_update',
                         return_create_volume_metadata)

        req = fakes.HTTPRequest.blank('/v2/volume_metadata')
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"metadata": {"key9": "value9"}}
        req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.VolumeNotFound,
                          self.controller.create, req, self.req_id, body=body)

    @mock.patch.object(db, 'volume_metadata_update')
    def test_update_all(self, metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'available'}
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
            res_dict = self.controller.update_all(req, self.req_id,
                                                  body=expected)
            self.assertEqual(expected, res_dict)
            get_volume.assert_called_once_with(fake_context, self.req_id)

    @mock.patch.object(db, 'volume_metadata_update')
    def test_update_all_volume_maintenance(self, metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'maintenance'}
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
            self.assertRaises(exception.InvalidVolume,
                              self.controller.update_all, req,
                              self.req_id, body=expected)
            self.assertFalse(metadata_update.called)
            get_volume.assert_called_once_with(fake_context, self.req_id)

    @mock.patch.object(db, 'volume_metadata_update')
    @mock.patch.object(db, 'volume_metadata_get')
    def test_update_all_with_keys_in_uppercase_and_lowercase(self,
                                                             metadata_get,
                                                             metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'available'}
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
            res_dict = self.controller.update_all(req, self.req_id, body=body)
            self.assertEqual(expected, res_dict)
            get_volume.assert_called_once_with(fake_context, self.req_id)

    @mock.patch.object(db, 'volume_metadata_update')
    def test_update_all_empty_container(self, metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'available'}
        fake_context = mock.Mock()
        metadata_update.return_value = {}
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': {}}
        req.body = jsonutils.dump_as_bytes(expected)
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            res_dict = self.controller.update_all(req, self.req_id,
                                                  body=expected)
            self.assertEqual(expected, res_dict)
            get_volume.assert_called_once_with(fake_context, self.req_id)

    def test_update_all_malformed_container(self):
        self.mock_object(db, 'volume_metadata_update',
                         return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'meta': {}}
        req.body = jsonutils.dump_as_bytes(expected)

        self.assertRaises(exception.ValidationError,
                          self.controller.update_all, req, self.req_id,
                          body=expected)

    def test_update_all_malformed_data(self):
        self.mock_object(db, 'volume_metadata_update',
                         return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        expected = {'metadata': ['asdf']}
        req.body = jsonutils.dump_as_bytes(expected)

        self.assertRaises(exception.ValidationError,
                          self.controller.update_all, req, self.req_id,
                          body=expected)

    def test_update_all_nonexistent_volume(self):
        self.mock_object(db, 'volume_get', return_volume_nonexistent)
        req = fakes.HTTPRequest.blank(self.url)
        req.method = 'PUT'
        req.content_type = "application/json"
        body = {'metadata': {'key10': 'value10'}}
        req.body = jsonutils.dump_as_bytes(body)

        self.assertRaises(exception.VolumeNotFound,
                          self.controller.update_all, req, '100', body=body)

    @mock.patch.object(db, 'volume_metadata_update')
    def test_update_item(self, metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'available'}
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
            res_dict = self.controller.update(req, self.req_id, 'key1',
                                              body=body)
            expected = {'meta': {'key1': 'value1'}}
            self.assertEqual(expected, res_dict)
            get_volume.assert_called_once_with(fake_context, self.req_id)

    def test_update_metadata_item_keys_value_none(self):
        self.mock_object(db, 'volume_metadata_update',
                         return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"a": None}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(exception.ValidationError,
                          self.controller.update,
                          req, self.req_id, 'key1', body=body)

    @mock.patch.object(db, 'volume_metadata_update')
    def test_update_item_volume_maintenance(self, metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'maintenance'}
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
            self.assertRaises(exception.InvalidVolume,
                              self.controller.update, req,
                              self.req_id, 'key1', body=body)
            self.assertFalse(metadata_update.called)
            get_volume.assert_called_once_with(fake_context, self.req_id)

    def test_update_item_nonexistent_volume(self):
        self.mock_object(db, 'volume_get',
                         return_volume_nonexistent)
        req = fakes.HTTPRequest.blank(
            '/v2/%s/volumes/asdf/metadata/key1' % fake.PROJECT_ID)
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(exception.VolumeNotFound,
                          self.controller.update, req, self.req_id, 'key1',
                          body=body)

    def test_update_item_empty_body(self):
        self.mock_object(db, 'volume_metadata_update',
                         return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        req.headers["content-type"] = "application/json"

        self.assertRaises(exception.ValidationError,
                          self.controller.update, req, self.req_id, 'key1',
                          body=None)

    @mock.patch.object(db, 'volume_metadata_update')
    def test_update_item_empty_key(self, metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'available'}
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
            self.assertRaises(exception.ValidationError,
                              self.controller.update, req, self.req_id,
                              '', body=body)
            self.assertFalse(metadata_update.called)

    @mock.patch.object(db, 'volume_metadata_update')
    def test_update_item_key_too_long(self, metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'available'}
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
            self.assertRaises(exception.ValidationError,
                              self.controller.update,
                              req, self.req_id, ("a" * 260), body=body)
            self.assertFalse(metadata_update.called)

    @mock.patch.object(db, 'volume_metadata_update')
    def test_update_item_value_too_long(self, metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'available'}
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
            self.assertRaises(exception.ValidationError,
                              self.controller.update,
                              req, self.req_id, "key1", body=body)
            self.assertFalse(metadata_update.called)

    def test_update_item_too_many_keys(self):
        self.mock_object(db, 'volume_metadata_update',
                         return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/key1')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1", "key2": "value2"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(exception.ValidationError,
                          self.controller.update, req, self.req_id, 'key1',
                          body=body)

    def test_update_item_body_uri_mismatch(self):
        self.mock_object(db, 'volume_metadata_update',
                         return_create_volume_metadata)
        req = fakes.HTTPRequest.blank(self.url + '/bad')
        req.method = 'PUT'
        body = {"meta": {"key1": "value1"}}
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, self.req_id, 'bad',
                          body=body)

    @mock.patch.object(db, 'volume_metadata_update')
    def test_invalid_metadata_items_on_create(self, metadata_update):
        fake_volume = {'id': self.req_id, 'status': 'available'}
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
            self.assertRaises(exception.ValidationError,
                              self.controller.create, req, self.req_id,
                              body=data)

        # test for long value
        data = {"metadata": {"key": "v" * 260}}
        req.body = jsonutils.dump_as_bytes(data)
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            self.assertRaises(exception.ValidationError,
                              self.controller.create, req, self.req_id,
                              body=data)

        # test for empty key.
        data = {"metadata": {"": "value1"}}
        req.body = jsonutils.dump_as_bytes(data)
        req.environ['cinder.context'] = fake_context

        with mock.patch.object(self.controller.volume_api,
                               'get') as get_volume:
            get_volume.return_value = fake_volume
            self.assertRaises(exception.ValidationError,
                              self.controller.create, req, self.req_id,
                              body=data)
