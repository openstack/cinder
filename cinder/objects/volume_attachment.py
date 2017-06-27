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

from oslo_serialization import jsonutils
from oslo_utils import versionutils
from oslo_versionedobjects import fields

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.objects import fields as c_fields


@base.CinderObjectRegistry.register
class VolumeAttachment(base.CinderPersistentObject, base.CinderObject,
                       base.CinderObjectDictCompat,
                       base.CinderComparableObject):
    # Version 1.0: Initial version
    # Version 1.1: Added volume relationship
    # Version 1.2: Added connection_info attribute
    VERSION = '1.2'

    OPTIONAL_FIELDS = ['volume']
    obj_extra_fields = ['project_id', 'volume_host']

    fields = {
        'id': fields.UUIDField(),
        'volume_id': fields.UUIDField(),
        'instance_uuid': fields.UUIDField(nullable=True),
        'attached_host': fields.StringField(nullable=True),
        'mountpoint': fields.StringField(nullable=True),

        'attach_time': fields.DateTimeField(nullable=True),
        'detach_time': fields.DateTimeField(nullable=True),

        'attach_status': c_fields.VolumeAttachStatusField(nullable=True),
        'attach_mode': fields.StringField(nullable=True),

        'volume': fields.ObjectField('Volume', nullable=False),
        'connection_info': c_fields.DictOfNullableField(nullable=True)
    }

    @property
    def project_id(self):
        return self.volume.project_id

    @property
    def volume_host(self):
        return self.volume.host

    @classmethod
    def _get_expected_attrs(cls, context, *args, **kwargs):
        return ['volume']

    def obj_make_compatible(self, primitive, target_version):
        """Make a object representation compatible with target version."""
        super(VolumeAttachment, self).obj_make_compatible(primitive,
                                                          target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 2):
            primitive.pop('connection_info', None)

    @classmethod
    def _from_db_object(cls, context, attachment, db_attachment,
                        expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = cls._get_expected_attrs(context)

        for name, field in attachment.fields.items():
            if name in cls.OPTIONAL_FIELDS:
                continue
            value = db_attachment.get(name)
            if isinstance(field, fields.IntegerField):
                value = value or 0
            if name == 'connection_info':
                attachment.connection_info = jsonutils.loads(
                    value) if value else None
            else:
                attachment[name] = value
        if 'volume' in expected_attrs:
            db_volume = db_attachment.get('volume')
            if db_volume:
                attachment.volume = objects.Volume._from_db_object(
                    context, objects.Volume(), db_volume)

        attachment._context = context
        attachment.obj_reset_changes()
        return attachment

    def obj_load_attr(self, attrname):
        if attrname not in self.OPTIONAL_FIELDS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        if attrname == 'volume':
            volume = objects.Volume.get_by_id(self._context, self.id)
            self.volume = volume

        self.obj_reset_changes(fields=[attrname])

    @staticmethod
    def _convert_connection_info_to_db_format(updates):
        properties = updates.pop('connection_info', None)
        if properties is not None:
            updates['connection_info'] = jsonutils.dumps(properties)

    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            if 'connection_info' in updates:
                self._convert_connection_info_to_db_format(updates)
            if 'volume' in updates:
                raise exception.ObjectActionError(action='save',
                                                  reason=_('volume changed'))

            db.volume_attachment_update(self._context, self.id, updates)
            self.obj_reset_changes()

    def finish_attach(self, instance_uuid, host_name,
                      mount_point, attach_mode='rw'):
        with self.obj_as_admin():
            db_volume, updated_values = db.volume_attached(
                self._context, self.id,
                instance_uuid, host_name,
                mount_point, attach_mode)
        self.update(updated_values)
        self.obj_reset_changes(updated_values.keys())
        return objects.Volume._from_db_object(self._context,
                                              objects.Volume(),
                                              db_volume)

    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already created'))
        updates = self.cinder_obj_get_changes()
        with self.obj_as_admin():
            db_attachment = db.volume_attach(self._context, updates)
        self._from_db_object(self._context, self, db_attachment)

    def destroy(self):
        updated_values = db.attachment_destroy(self._context, self.id)
        self.update(updated_values)
        self.obj_reset_changes(updated_values.keys())


@base.CinderObjectRegistry.register
class VolumeAttachmentList(base.ObjectListBase, base.CinderObject):
    # Version 1.0: Initial version
    # Version 1.1: Remove volume_id in get_by_host|instance
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('VolumeAttachment'),
    }

    @classmethod
    def get_all_by_volume_id(cls, context, volume_id):
        attachments = db.volume_attachment_get_all_by_volume_id(context,
                                                                volume_id)
        return base.obj_make_list(context,
                                  cls(context),
                                  objects.VolumeAttachment,
                                  attachments)

    @classmethod
    def get_all_by_host(cls, context, host, search_opts=None):
        attachments = db.volume_attachment_get_all_by_host(context,
                                                           host,
                                                           search_opts)
        return base.obj_make_list(context, cls(context),
                                  objects.VolumeAttachment, attachments)

    @classmethod
    def get_all_by_instance_uuid(cls, context,
                                 instance_uuid, search_opts=None):
        attachments = db.volume_attachment_get_all_by_instance_uuid(
            context, instance_uuid, search_opts)
        return base.obj_make_list(context, cls(context),
                                  objects.VolumeAttachment, attachments)

    @classmethod
    def get_all(cls, context, search_opts=None,
                marker=None, limit=None, offset=None,
                sort_keys=None, sort_direction=None):
        attachments = db.volume_attachment_get_all(
            context, search_opts, marker, limit, offset, sort_keys,
            sort_direction)
        return base.obj_make_list(context, cls(context),
                                  objects.VolumeAttachment, attachments)

    @classmethod
    def get_all_by_project(cls, context, project_id, search_opts=None,
                           marker=None, limit=None, offset=None,
                           sort_keys=None, sort_direction=None):
        attachments = db.volume_attachment_get_all_by_project(
            context, project_id, search_opts, marker, limit, offset, sort_keys,
            sort_direction)
        return base.obj_make_list(context, cls(context),
                                  objects.VolumeAttachment, attachments)
