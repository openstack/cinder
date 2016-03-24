# Copyright (c) 2011 Citrix Systems, Inc.
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

import glanceclient.exc


NOW_GLANCE_FORMAT = "2010-10-11T10:30:22"


IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                    'container_format', 'checksum', 'id',
                    'name', 'created_at', 'updated_at',
                    'deleted', 'status',
                    'min_disk', 'min_ram', 'is_public']


class StubGlanceClient(object):

    def __init__(self, images=None):
        self._images = []
        _images = images or []
        map(lambda image: self.create(**image), _images)

        # NOTE(bcwaldon): HACK to get client.images.* to work
        self.images = lambda: None
        for fn in ('list', 'get', 'data', 'create', 'update', 'upload',
                   'delete'):
            setattr(self.images, fn, getattr(self, fn))

        self.schemas = lambda: None
        setattr(self.schemas, 'get', getattr(self, 'schemas_get'))

    # TODO(bcwaldon): implement filters
    def list(self, filters=None, marker=None, limit=30):
        if marker is None:
            index = 0
        else:
            for index, image in enumerate(self._images):
                if image.id == str(marker):
                    index += 1
                    break
            else:
                raise glanceclient.exc.BadRequest('Marker not found')

        return self._images[index:index + limit]

    def get(self, image_id):
        for image in self._images:
            if image.id == str(image_id):
                return image
        raise glanceclient.exc.NotFound(image_id)

    def data(self, image_id):
        image = self.get(image_id)
        if getattr(image, 'size', 0):
            return ['*' * image.size]
        else:
            return []

    def create(self, **metadata):
        metadata['created_at'] = NOW_GLANCE_FORMAT
        metadata['updated_at'] = NOW_GLANCE_FORMAT

        self._images.append(FakeImage(metadata))

        try:
            image_id = str(metadata['id'])
        except KeyError:
            # auto-generate an id if one wasn't provided
            image_id = str(len(self._images))

        self._images[-1].id = image_id

        return self._images[-1]

    def update(self, image_id, **metadata):
        for i, image in enumerate(self._images):
            if image.id == str(image_id):
                for k, v in metadata.items():
                    if k == 'data':
                        setattr(self._images[i], 'size', len(v))
                    else:
                        setattr(self._images[i], k, v)
                return self._images[i]
        raise glanceclient.exc.NotFound(image_id)

    def delete(self, image_id):
        for i, image in enumerate(self._images):
            if image.id == image_id:
                del self._images[i]
                return
        raise glanceclient.exc.NotFound(image_id)

    def upload(self, image_id, data):
        for i, image in enumerate(self._images):
            if image.id == image_id:
                setattr(self._images[i], 'size', len(data))
                return
        raise glanceclient.exc.NotFound(image_id)

    def schemas_get(self, schema_name):
        if schema_name != 'image':
            raise glanceclient.exc.NotFound()
        return FakeSchema()


class FakeImage(object):
    def __init__(self, metadata):
        raw = dict.fromkeys(IMAGE_ATTRIBUTES)
        raw.update(metadata)
        self.__dict__['raw'] = raw

    def __getattr__(self, key):
        try:
            return self.__dict__['raw'][key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        try:
            self.__dict__['raw'][key] = value
        except KeyError:
            raise AttributeError(key)

    def keys(self):
        return self.__dict__['raw'].keys()


class FakeSchema(object):
    def is_base_property(self, key):
        if key in IMAGE_ATTRIBUTES:
            return True
        else:
            return False
