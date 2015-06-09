# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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

"""The volume encryption metadata extension."""

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder import db

authorize = extensions.extension_authorizer('volume',
                                            'volume_encryption_metadata')


class VolumeEncryptionMetadataTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.make_flat_dict('encryption', selector='encryption')
        return xmlutil.MasterTemplate(root, 1)


class VolumeEncryptionMetadataController(wsgi.Controller):
    """The volume encryption metadata API extension."""

    @wsgi.serializers(xml=VolumeEncryptionMetadataTemplate)
    def index(self, req, volume_id):
        """Returns the encryption metadata for a given volume."""
        context = req.environ['cinder.context']
        authorize(context)
        return db.volume_encryption_metadata_get(context, volume_id)

    @wsgi.serializers(xml=VolumeEncryptionMetadataTemplate)
    def show(self, req, volume_id, id):
        """Return a single encryption item."""
        encryption_item = self.index(req, volume_id)
        if encryption_item is not None:
            return encryption_item[id]
        else:
            return None


class Volume_encryption_metadata(extensions.ExtensionDescriptor):
    """Volume encryption metadata retrieval support."""

    name = "VolumeEncryptionMetadata"
    alias = "os-volume-encryption-metadata"
    namespace = ("http://docs.openstack.org/volume/ext/"
                 "os-volume-encryption-metadata/api/v1")
    updated = "2013-07-10T00:00:00+00:00"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            'encryption', VolumeEncryptionMetadataController(),
            parent=dict(member_name='volume', collection_name='volumes'))
        resources.append(res)
        return resources
