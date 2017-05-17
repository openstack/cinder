#   Copyright 2012 OpenStack Foundation
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

import uuid

from oslo_serialization import jsonutils
from oslo_utils import timeutils
from six.moves import http_client
import webob

from cinder.api.contrib import volume_image_metadata
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder import volume


def fake_db_volume_get(*args, **kwargs):
    return {
        'id': kwargs.get('volume_id') or fake.VOLUME_ID,
        'host': 'host001',
        'status': 'available',
        'size': 5,
        'availability_zone': 'somewhere',
        'created_at': timeutils.utcnow(),
        'display_name': 'anothervolume',
        'display_description': 'Just another volume!',
        'volume_type_id': None,
        'snapshot_id': None,
        'project_id': fake.PROJECT_ID,
        'migration_status': None,
        '_name_id': fake.VOLUME2_ID,
        'attach_status': fields.VolumeAttachStatus.DETACHED,
    }


def fake_volume_api_get(*args, **kwargs):
    ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
    db_volume = fake_db_volume_get(volume_id=kwargs.get('volume_id'))
    return fake_volume.fake_volume_obj(ctx, **db_volume)


def fake_volume_get_all(*args, **kwargs):
    return objects.VolumeList(objects=[fake_volume_api_get(),
                                       fake_volume_api_get(
                                           volume_id=fake.VOLUME2_ID)])


def fake_volume_get_all_empty(*args, **kwargs):
    return objects.VolumeList(objects=[])


fake_image_metadata = {
    'image_id': fake.IMAGE_ID,
    'image_name': 'fake',
    'kernel_id': 'somekernel',
    'ramdisk_id': 'someramdisk',
}


def fake_get_volume_image_metadata(*args, **kwargs):
    return fake_image_metadata


def fake_get_volumes_image_metadata(*args, **kwargs):
    return {'fake': fake_image_metadata}


def return_empty_image_metadata(*args, **kwargs):
    return {}


def volume_metadata_delete(context, volume_id, key, meta_type):
    pass


def fake_create_volume_metadata(context, volume_id, metadata,
                                delete, meta_type):
    return fake_get_volume_image_metadata()


def return_volume_nonexistent(*args, **kwargs):
    raise exception.VolumeNotFound('bogus test message')


class VolumeImageMetadataTest(test.TestCase):
    content_type = 'application/json'

    def setUp(self):
        super(VolumeImageMetadataTest, self).setUp()
        self.mock_object(volume.api.API, 'get', fake_volume_api_get)
        self.mock_object(volume.api.API, 'get_all', fake_volume_get_all)
        self.mock_object(volume.api.API, 'get_volume_image_metadata',
                         fake_get_volume_image_metadata)
        self.mock_object(volume.api.API, 'get_volumes_image_metadata',
                         fake_get_volumes_image_metadata)
        self.UUID = uuid.uuid4()
        self.controller = (volume_image_metadata.
                           VolumeImageMetadataController())
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.accept = self.content_type
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        return res

    def _get_image_metadata(self, body):
        return jsonutils.loads(body)['volume']['volume_image_metadata']

    def _get_image_metadata_list(self, body):
        return [
            volume['volume_image_metadata']
            for volume in jsonutils.loads(body)['volumes']
            if volume.get('volume_image_metadata')
        ]

    def _create_volume_and_glance_metadata(self):
        ctxt = context.get_admin_context()
        # create a bootable volume
        db.volume_create(ctxt, {'id': fake.VOLUME_ID, 'status': 'available',
                                'host': 'test', 'provider_location': '',
                                'size': 1})
        db.volume_glance_metadata_create(ctxt, fake.VOLUME_ID,
                                         'image_id', fake.IMAGE_ID)
        db.volume_glance_metadata_create(ctxt, fake.VOLUME_ID,
                                         'image_name', 'fake')
        db.volume_glance_metadata_create(ctxt, fake.VOLUME_ID, 'kernel_id',
                                         'somekernel')
        db.volume_glance_metadata_create(ctxt, fake.VOLUME_ID, 'ramdisk_id',
                                         'someramdisk')

        # create a unbootable volume
        db.volume_create(ctxt, {'id': fake.VOLUME2_ID, 'status': 'available',
                                'host': 'test', 'provider_location': '',
                                'size': 1})

    def test_get_volume(self):
        self._create_volume_and_glance_metadata()
        res = self._make_request('/v2/%s/volumes/%s' % (
            fake.PROJECT_ID, self.UUID))
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(fake_image_metadata,
                         self._get_image_metadata(res.body))

    def test_list_detail_volumes(self):
        self._create_volume_and_glance_metadata()
        res = self._make_request('/v2/%s/volumes/detail' % fake.PROJECT_ID)
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(fake_image_metadata,
                         self._get_image_metadata_list(res.body)[0])

    def test_list_detail_empty_volumes(self):
        def fake_dont_call_this(*args, **kwargs):
            fake_dont_call_this.called = True
        fake_dont_call_this.called = False
        self.mock_object(volume.api.API, 'get_list_volumes_image_metadata',
                         fake_dont_call_this)
        self.mock_object(volume.api.API, 'get_all',
                         fake_volume_get_all_empty)

        res = self._make_request('/v2/%s/volumes/detail' % fake.PROJECT_ID)
        self.assertEqual(http_client.OK, res.status_int)
        self.assertFalse(fake_dont_call_this.called)

    def test_list_detail_volumes_with_limit(self):
        ctxt = context.get_admin_context()
        db.volume_create(ctxt, {'id': fake.VOLUME_ID, 'status': 'available',
                                'host': 'test', 'provider_location': '',
                                'size': 1})
        db.volume_glance_metadata_create(ctxt, fake.VOLUME_ID,
                                         'key1', 'value1')
        db.volume_glance_metadata_create(ctxt, fake.VOLUME_ID,
                                         'key2', 'value2')
        res = self._make_request('/v2/%s/volumes/detail?limit=1'
                                 % fake.PROJECT_ID)
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual({'key1': 'value1', 'key2': 'value2'},
                         self._get_image_metadata_list(res.body)[0])

    def test_create_image_metadata(self):
        self.mock_object(volume.api.API, 'get_volume_image_metadata',
                         return_empty_image_metadata)
        self.mock_object(db, 'volume_metadata_update',
                         fake_create_volume_metadata)

        body = {"os-set_image_metadata": {"metadata": fake_image_metadata}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(fake_image_metadata,
                         jsonutils.loads(res.body)["metadata"])

    def test_create_with_keys_case_insensitive(self):
        # If the keys in uppercase_and_lowercase, should return the one
        # which server added
        self.mock_object(volume.api.API, 'get_volume_image_metadata',
                         return_empty_image_metadata)
        self.mock_object(db, 'volume_metadata_update',
                         fake_create_volume_metadata)

        body = {
            "os-set_image_metadata": {
                "metadata": {
                    "Image_Id": "someid",
                    "image_name": "fake",
                    "Kernel_id": "somekernel",
                    "ramdisk_id": "someramdisk"
                },
            },
        }

        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(fake_image_metadata,
                         jsonutils.loads(res.body)["metadata"])

    def test_create_empty_body(self):
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, fake.VOLUME_ID, None)

    def test_create_nonexistent_volume(self):
        self.mock_object(volume.api.API, 'get', return_volume_nonexistent)

        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"os-set_image_metadata": {
            "metadata": {"image_name": "fake"}}
        }
        req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.VolumeNotFound,
                          self.controller.create, req, fake.VOLUME_ID, body)

    def test_invalid_metadata_items_on_create(self):
        self.mock_object(db, 'volume_metadata_update',
                         fake_create_volume_metadata)
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        data = {"os-set_image_metadata": {
            "metadata": {"a" * 260: "value1"}}
        }

        # Test for long key
        req.body = jsonutils.dump_as_bytes(data)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, fake.VOLUME_ID, data)

        # Test for long value
        data = {"os-set_image_metadata": {
            "metadata": {"key": "v" * 260}}
        }
        req.body = jsonutils.dump_as_bytes(data)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, fake.VOLUME_ID, data)

        # Test for empty key.
        data = {"os-set_image_metadata": {
            "metadata": {"": "value1"}}
        }
        req.body = jsonutils.dump_as_bytes(data)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, fake.VOLUME_ID, data)

    def test_delete(self):
        self.mock_object(db, 'volume_metadata_delete',
                         volume_metadata_delete)

        body = {"os-unset_image_metadata": {
            "key": "ramdisk_id"}
        }
        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        self.assertEqual(http_client.OK, res.status_int)

    def test_delete_meta_not_found(self):
        data = {"os-unset_image_metadata": {
            "key": "invalid_id"}
        }
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(data)
        req.headers["content-type"] = "application/json"

        self.assertRaises(exception.GlanceMetadataNotFound,
                          self.controller.delete, req, fake.VOLUME_ID, data)

    def test_delete_nonexistent_volume(self):
        self.mock_object(db, 'volume_metadata_delete',
                         return_volume_nonexistent)

        body = {"os-unset_image_metadata": {
            "key": "fake"}
        }
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(exception.GlanceMetadataNotFound,
                          self.controller.delete, req, fake.VOLUME_ID, body)

    def test_show_image_metadata(self):
        body = {"os-show_image_metadata": None}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(fake_image_metadata,
                         jsonutils.loads(res.body)["metadata"])
