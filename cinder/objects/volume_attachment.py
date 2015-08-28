#    Copyright 2015 SimpliVity Corp.
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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_versionedobjects import fields

from cinder import db
from cinder import objects
from cinder.objects import base

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


@base.CinderObjectRegistry.register
class VolumeAttachment(base.CinderPersistentObject, base.CinderObject,
                       base.CinderObjectDictCompat,
                       base.CinderComparableObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.UUIDField(),
        'volume_id': fields.UUIDField(),
        'instance_uuid': fields.UUIDField(nullable=True),
        'attached_host': fields.StringField(nullable=True),
        'mountpoint': fields.StringField(nullable=True),

        'attach_time': fields.DateTimeField(nullable=True),
        'detach_time': fields.DateTimeField(nullable=True),

        'attach_status': fields.StringField(nullable=True),
        'attach_mode': fields.StringField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, attachment, db_attachment):
        for name, field in attachment.fields.items():
            value = db_attachment.get(name)
            if isinstance(field, fields.IntegerField):
                value = value or 0
            attachment[name] = value

        attachment._context = context
        attachment.obj_reset_changes()
        return attachment

    @base.remotable_classmethod
    def get_by_id(cls, context, id):
        db_attach = db.volume_attachment_get(context, id)
        return cls._from_db_object(context, cls(context), db_attach)

    @base.remotable
    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            db.volume_attachment_update(self._context, self.id, updates)
            self.obj_reset_changes()


@base.CinderObjectRegistry.register
class VolumeAttachmentList(base.ObjectListBase, base.CinderObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('VolumeAttachment'),
    }

    child_versions = {
        '1.0': '1.0',
    }

    @base.remotable_classmethod
    def get_all_by_volume_id(cls, context, volume_id):
        attachments = db.volume_attachment_get_used_by_volume_id(context,
                                                                 volume_id)
        return base.obj_make_list(context, cls(context),
                                  objects.VolumeAttachment, attachments)

    @base.remotable_classmethod
    def get_all_by_host(cls, context, volume_id, host):
        attachments = db.volume_attachment_get_by_host(context, volume_id,
                                                       host)
        return base.obj_make_list(context, cls(context),
                                  objects.VolumeAttachment, attachments)

    @base.remotable_classmethod
    def get_all_by_instance_uuid(cls, context, volume_id, instance_uuid):
        attachments = db.volume_attachment_get_by_instance_uuid(
            context, volume_id, instance_uuid)
        return base.obj_make_list(context, cls(context),
                                  objects.VolumeAttachment, attachments)
