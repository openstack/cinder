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

import json
import uuid
from xml.dom import minidom

from oslo_serialization import jsonutils
from oslo_utils import timeutils
import webob

from cinder.api import common
from cinder.api.contrib import volume_image_metadata
from cinder.api.openstack import wsgi
from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes
from cinder import volume


def fake_volume_get(*args, **kwargs):
    return {
        'id': 'fake',
        'host': 'host001',
        'status': 'available',
        'size': 5,
        'availability_zone': 'somewhere',
        'created_at': timeutils.utcnow(),
        'attach_status': None,
        'display_name': 'anothervolume',
        'display_description': 'Just another volume!',
        'volume_type_id': None,
        'snapshot_id': None,
        'project_id': 'fake',
    }


def fake_volume_get_all(*args, **kwargs):
    return [fake_volume_get()]


fake_image_metadata = {
    'image_id': 'someid',
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
        self.stubs.Set(volume.API, 'get', fake_volume_get)
        self.stubs.Set(volume.API, 'get_all', fake_volume_get_all)
        self.stubs.Set(volume.API, 'get_volume_image_metadata',
                       fake_get_volume_image_metadata)
        self.stubs.Set(volume.API, 'get_volumes_image_metadata',
                       fake_get_volumes_image_metadata)
        self.stubs.Set(db, 'volume_get', fake_volume_get)
        self.UUID = uuid.uuid4()
        self.controller = (volume_image_metadata.
                           VolumeImageMetadataController())

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.accept = self.content_type
        res = req.get_response(fakes.wsgi_app())
        return res

    def _get_image_metadata(self, body):
        return json.loads(body)['volume']['volume_image_metadata']

    def _get_image_metadata_list(self, body):
        return [
            volume['volume_image_metadata']
            for volume in json.loads(body)['volumes']
        ]

    def _create_volume_and_glance_metadata(self):
        ctxt = context.get_admin_context()
        db.volume_create(ctxt, {'id': 'fake', 'status': 'available',
                                'host': 'test', 'provider_location': '',
                                'size': 1})
        db.volume_glance_metadata_create(ctxt, 'fake', 'image_id', 'someid')
        db.volume_glance_metadata_create(ctxt, 'fake', 'image_name', 'fake')
        db.volume_glance_metadata_create(ctxt, 'fake', 'kernel_id',
                                         'somekernel')
        db.volume_glance_metadata_create(ctxt, 'fake', 'ramdisk_id',
                                         'someramdisk')

    def test_get_volume(self):
        self._create_volume_and_glance_metadata()
        res = self._make_request('/v2/fake/volumes/%s' % self.UUID)
        self.assertEqual(200, res.status_int)
        self.assertEqual(fake_image_metadata,
                         self._get_image_metadata(res.body))

    def test_list_detail_volumes(self):
        self._create_volume_and_glance_metadata()
        res = self._make_request('/v2/fake/volumes/detail')
        self.assertEqual(200, res.status_int)
        self.assertEqual(fake_image_metadata,
                         self._get_image_metadata_list(res.body)[0])

    def test_list_detail_volumes_with_limit(self):
        ctxt = context.get_admin_context()
        db.volume_create(ctxt, {'id': 'fake', 'status': 'available',
                                'host': 'test', 'provider_location': '',
                                'size': 1})
        db.volume_glance_metadata_create(ctxt, 'fake', 'key1', 'value1')
        db.volume_glance_metadata_create(ctxt, 'fake', 'key2', 'value2')
        res = self._make_request('/v2/fake/volumes/detail?limit=1')
        self.assertEqual(200, res.status_int)
        self.assertEqual({'key1': 'value1', 'key2': 'value2'},
                         self._get_image_metadata_list(res.body)[0])

    def test_create_image_metadata(self):
        self.stubs.Set(volume.API, 'get_volume_image_metadata',
                       return_empty_image_metadata)
        self.stubs.Set(db, 'volume_metadata_update',
                       fake_create_volume_metadata)

        body = {"os-set_image_metadata": {"metadata": fake_image_metadata}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        self.assertEqual(fake_image_metadata,
                         json.loads(res.body)["metadata"])

    def test_create_with_keys_case_insensitive(self):
        # If the keys in uppercase_and_lowercase, should return the one
        # which server added
        self.stubs.Set(volume.API, 'get_volume_image_metadata',
                       return_empty_image_metadata)
        self.stubs.Set(db, 'volume_metadata_update',
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

        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        self.assertEqual(fake_image_metadata,
                         json.loads(res.body)["metadata"])

    def test_create_empty_body(self):
        req = fakes.HTTPRequest.blank('/v2/fake/volumes/1/action')
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, 1, None)

    def test_create_nonexistent_volume(self):
        self.stubs.Set(volume.API, 'get', return_volume_nonexistent)

        req = fakes.HTTPRequest.blank('/v2/fake/volumes/1/action')
        req.method = 'POST'
        req.content_type = "application/json"
        body = {"os-set_image_metadata": {
            "metadata": {"image_name": "fake"}}
        }
        req.body = jsonutils.dumps(body)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.create, req, 1, body)

    def test_invalid_metadata_items_on_create(self):
        self.stubs.Set(db, 'volume_metadata_update',
                       fake_create_volume_metadata)
        req = fakes.HTTPRequest.blank('/v2/fake/volumes/1/action')
        req.method = 'POST'
        req.headers["content-type"] = "application/json"

        data = {"os-set_image_metadata": {
            "metadata": {"a" * 260: "value1"}}
        }

        # Test for long key
        req.body = jsonutils.dumps(data)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, 1, data)

        # Test for long value
        data = {"os-set_image_metadata": {
            "metadata": {"key": "v" * 260}}
        }
        req.body = jsonutils.dumps(data)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, req, 1, data)

        # Test for empty key.
        data = {"os-set_image_metadata": {
            "metadata": {"": "value1"}}
        }
        req.body = jsonutils.dumps(data)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, 1, data)

    def test_delete(self):
        self.stubs.Set(db, 'volume_metadata_delete',
                       volume_metadata_delete)

        body = {"os-unset_image_metadata": {
            "key": "ramdisk_id"}
        }
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)

    def test_delete_meta_not_found(self):
        data = {"os-unset_image_metadata": {
            "key": "invalid_id"}
        }
        req = fakes.HTTPRequest.blank('/v2/fake/volumes/1/action')
        req.method = 'POST'
        req.body = jsonutils.dumps(data)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, 1, data)

    def test_delete_nonexistent_volume(self):
        self.stubs.Set(db, 'volume_metadata_delete',
                       return_volume_nonexistent)

        body = {"os-unset_image_metadata": {
            "key": "fake"}
        }
        req = fakes.HTTPRequest.blank('/v2/fake/volumes/1/action')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, 1, body)

    def test_show_image_metadata(self):
        body = {"os-show_image_metadata": None}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        self.assertEqual(fake_image_metadata,
                         json.loads(res.body)["metadata"])


class ImageMetadataXMLDeserializer(common.MetadataXMLDeserializer):
    metadata_node_name = "volume_image_metadata"


class VolumeImageMetadataXMLTest(VolumeImageMetadataTest):
    content_type = 'application/xml'

    def _get_image_metadata(self, body):
        deserializer = wsgi.XMLDeserializer()
        volume = deserializer.find_first_child_named(
            minidom.parseString(body), 'volume')
        image_metadata = deserializer.find_first_child_named(
            volume, 'volume_image_metadata')
        return wsgi.MetadataXMLDeserializer().extract_metadata(image_metadata)

    def _get_image_metadata_list(self, body):
        deserializer = wsgi.XMLDeserializer()
        volumes = deserializer.find_first_child_named(
            minidom.parseString(body), 'volumes')
        volume_list = deserializer.find_children_named(volumes, 'volume')
        image_metadata_list = [
            deserializer.find_first_child_named(
                volume, 'volume_image_metadata'
            )
            for volume in volume_list]
        return map(wsgi.MetadataXMLDeserializer().extract_metadata,
                   image_metadata_list)
