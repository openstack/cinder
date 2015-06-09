# Copyright 2011 Justin Santa Barbara
# Copyright 2012 OpenStack Foundation
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

"""Implementation of a fake image service."""

import copy
import datetime
import uuid

from oslo_log import log as logging

from cinder import exception
import cinder.image.glance


LOG = logging.getLogger(__name__)


class _FakeImageService(object):
    """Mock (fake) image service for unit testing."""

    def __init__(self):
        self.images = {}
        # NOTE(justinsb): The OpenStack API can't upload an image?
        # So, make sure we've got one..
        timestamp = datetime.datetime(2011, 1, 1, 1, 2, 3)

        image1 = {'id': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                  'name': 'fakeimage123456',
                  'created_at': timestamp,
                  'updated_at': timestamp,
                  'deleted_at': None,
                  'deleted': False,
                  'status': 'active',
                  'is_public': False,
                  'container_format': 'raw',
                  'disk_format': 'raw',
                  'properties': {'kernel_id': 'nokernel',
                                 'ramdisk_id': 'nokernel',
                                 'architecture': 'x86_64'}}

        image2 = {'id': 'a2459075-d96c-40d5-893e-577ff92e721c',
                  'name': 'fakeimage123456',
                  'created_at': timestamp,
                  'updated_at': timestamp,
                  'deleted_at': None,
                  'deleted': False,
                  'status': 'active',
                  'is_public': True,
                  'container_format': 'ami',
                  'disk_format': 'ami',
                  'properties': {'kernel_id': 'nokernel',
                                 'ramdisk_id': 'nokernel'}}

        image3 = {'id': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                  'name': 'fakeimage123456',
                  'created_at': timestamp,
                  'updated_at': timestamp,
                  'deleted_at': None,
                  'deleted': False,
                  'status': 'active',
                  'is_public': True,
                  'container_format': None,
                  'disk_format': None,
                  'properties': {'kernel_id': 'nokernel',
                                 'ramdisk_id': 'nokernel'}}

        image4 = {'id': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'name': 'fakeimage123456',
                  'created_at': timestamp,
                  'updated_at': timestamp,
                  'deleted_at': None,
                  'deleted': False,
                  'status': 'active',
                  'is_public': True,
                  'container_format': 'ami',
                  'disk_format': 'ami',
                  'properties': {'kernel_id': 'nokernel',
                                 'ramdisk_id': 'nokernel'}}

        image5 = {'id': 'c905cedb-7281-47e4-8a62-f26bc5fc4c77',
                  'name': 'fakeimage123456',
                  'created_at': timestamp,
                  'updated_at': timestamp,
                  'deleted_at': None,
                  'deleted': False,
                  'status': 'active',
                  'is_public': True,
                  'container_format': 'ami',
                  'disk_format': 'ami',
                  'properties': {
                      'kernel_id': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                      'ramdisk_id': None}}

        image6 = {'id': 'a440c04b-79fa-479c-bed1-0b816eaec379',
                  'name': 'fakeimage6',
                  'created_at': timestamp,
                  'updated_at': timestamp,
                  'deleted_at': None,
                  'deleted': False,
                  'status': 'active',
                  'is_public': False,
                  'container_format': 'ova',
                  'disk_format': 'vhd',
                  'properties': {'kernel_id': 'nokernel',
                                 'ramdisk_id': 'nokernel',
                                 'architecture': 'x86_64',
                                 'auto_disk_config': 'False'}}

        image7 = {'id': '70a599e0-31e7-49b7-b260-868f441e862b',
                  'name': 'fakeimage7',
                  'created_at': timestamp,
                  'updated_at': timestamp,
                  'deleted_at': None,
                  'deleted': False,
                  'status': 'active',
                  'is_public': False,
                  'container_format': 'ova',
                  'disk_format': 'vhd',
                  'properties': {'kernel_id': 'nokernel',
                                 'ramdisk_id': 'nokernel',
                                 'architecture': 'x86_64',
                                 'auto_disk_config': 'True'}}

        self.create(None, image1)
        self.create(None, image2)
        self.create(None, image3)
        self.create(None, image4)
        self.create(None, image5)
        self.create(None, image6)
        self.create(None, image7)
        self._imagedata = {}
        super(_FakeImageService, self).__init__()

    # TODO(bcwaldon): implement optional kwargs such as limit, sort_dir
    def detail(self, context, **kwargs):
        """Return list of detailed image information."""
        return copy.deepcopy(self.images.values())

    def download(self, context, image_id, data):
        self.show(context, image_id)
        data.write(self._imagedata.get(image_id, ''))

    def show(self, context, image_id):
        """Get data about specified image.

        Returns a dict containing image data for the given opaque image id.

        """
        image = self.images.get(str(image_id))
        if image:
            return copy.deepcopy(image)
        LOG.warning('Unable to find image id %s. Have images: %s',
                    image_id, self.images)
        raise exception.ImageNotFound(image_id=image_id)

    def create(self, context, metadata, data=None):
        """Store the image data and return the new image id.

        :raises: Duplicate if the image already exist.

        """
        image_id = str(metadata.get('id', uuid.uuid4()))
        metadata['id'] = image_id
        if image_id in self.images:
            raise exception.Duplicate()
        self.images[image_id] = copy.deepcopy(metadata)
        if data:
            self._imagedata[image_id] = data.read()
        return self.images[image_id]

    def update(self, context, image_id, metadata, data=None,
               purge_props=False):
        """Replace the contents of the given image with the new data.

        :raises: ImageNotFound if the image does not exist.

        """
        if not self.images.get(image_id):
            raise exception.ImageNotFound(image_id=image_id)
        if purge_props:
            self.images[image_id] = copy.deepcopy(metadata)
        else:
            image = self.images[image_id]
            try:
                image['properties'].update(metadata.pop('properties'))
            except Exception:
                pass
            image.update(metadata)
        return self.images[image_id]

    def delete(self, context, image_id):
        """Delete the given image.

        :raises: ImageNotFound if the image does not exist.

        """
        removed = self.images.pop(image_id, None)
        if not removed:
            raise exception.ImageNotFound(image_id=image_id)

    def get_location(self, context, image_id):
        if image_id in self.images:
            return 'fake_location'
        return None

_fakeImageService = _FakeImageService()


def FakeImageService():
    return _fakeImageService


def FakeImageService_reset():
    global _fakeImageService
    _fakeImageService = _FakeImageService()


def stub_out_image_service(stubs):
    stubs.Set(cinder.image.glance, 'get_remote_image_service',
              lambda x, y: (FakeImageService(), y))
    stubs.Set(cinder.image.glance, 'get_default_image_service',
              lambda: FakeImageService())
