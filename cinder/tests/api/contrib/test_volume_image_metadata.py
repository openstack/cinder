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

from oslo_utils import timeutils
import webob

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder import db
from cinder import test
from cinder.tests.api import fakes
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

    def test_get_volume(self):
        res = self._make_request('/v2/fake/volumes/%s' % self.UUID)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(self._get_image_metadata(res.body),
                         fake_image_metadata)

    def test_list_detail_volumes(self):
        res = self._make_request('/v2/fake/volumes/detail')
        self.assertEqual(res.status_int, 200)
        self.assertEqual(self._get_image_metadata_list(res.body)[0],
                         fake_image_metadata)


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
