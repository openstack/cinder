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

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.objects import fields
from cinder import utils

CONF = cfg.CONF
OPTIONAL_FIELDS = []
LOG = logging.getLogger(__name__)


class Volume(base.CinderPersistentObject, base.CinderObject,
             base.CinderObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.UUIDField(),
        '_name_id': fields.UUIDField(nullable=True),
        'ec2_id': fields.UUIDField(nullable=True),
        'user_id': fields.UUIDField(nullable=True),
        'project_id': fields.UUIDField(nullable=True),

        'snapshot_id': fields.UUIDField(nullable=True),

        'host': fields.StringField(nullable=True),
        'size': fields.IntegerField(),
        'availability_zone': fields.StringField(),
        'status': fields.StringField(),
        'attach_status': fields.StringField(),
        'migration_status': fields.StringField(nullable=True),

        'scheduled_at': fields.DateTimeField(nullable=True),
        'launched_at': fields.DateTimeField(nullable=True),
        'terminated_at': fields.DateTimeField(nullable=True),

        'display_name': fields.StringField(nullable=True),
        'display_description': fields.StringField(nullable=True),

        'provider_id': fields.UUIDField(nullable=True),
        'provider_location': fields.StringField(nullable=True),
        'provider_auth': fields.StringField(nullable=True),
        'provider_geometry': fields.StringField(nullable=True),

        'volume_type_id': fields.UUIDField(nullable=True),
        'source_volid': fields.UUIDField(nullable=True),
        'encryption_key_id': fields.UUIDField(nullable=True),

        'consistencygroup_id': fields.UUIDField(nullable=True),

        'deleted': fields.BooleanField(default=False),
        'bootable': fields.BooleanField(default=False),

        'replication_status': fields.StringField(nullable=True),
        'replication_extended_status': fields.StringField(nullable=True),
        'replication_driver_data': fields.StringField(nullable=True),
    }

    # NOTE(thangp): obj_extra_fields is used to hold properties that are not
    # usually part of the model
    obj_extra_fields = ['name', 'name_id']

    @property
    def name_id(self):
        return self.id if not self._name_id else self._name_id

    @name_id.setter
    def name_id(self, value):
        self._name_id = value

    @property
    def name(self):
        return CONF.volume_name_template % self.name_id

    def __init__(self, *args, **kwargs):
        super(Volume, self).__init__(*args, **kwargs)

    def obj_make_compatible(self, primitive, target_version):
        """Make an object representation compatible with a target version."""
        target_version = utils.convert_version_to_tuple(target_version)

    @staticmethod
    def _from_db_object(context, volume, db_volume):
        for name, field in volume.fields.items():
            value = db_volume[name]
            if isinstance(field, fields.IntegerField):
                value = value or 0
            volume[name] = value

        volume._context = context
        volume.obj_reset_changes()
        return volume

    @base.remotable_classmethod
    def get_by_id(cls, context, id):
        db_volume = db.volume_get(context, id)
        return cls._from_db_object(context, cls(context), db_volume)

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already created'))
        updates = self.obj_get_changes()
        db_volume = db.volume_create(context, updates)
        self._from_db_object(context, self, db_volume)

    @base.remotable
    def save(self, context):
        updates = self.obj_get_changes()
        if updates:
            db.volume_update(context, self.id, updates)

        self.obj_reset_changes()

    @base.remotable
    def destroy(self, context):
        db.volume_destroy(context, self.id)


class VolumeList(base.ObjectListBase, base.CinderObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Volume'),
    }
    child_versions = {
        '1.0': '1.0'
    }

    @base.remotable_classmethod
    def get_all(cls, context, marker, limit, sort_key, sort_dir,
                filters=None):
        volumes = db.volume_get_all(context, marker, limit, sort_key,
                                    sort_dir, filters=filters)
        return base.obj_make_list(context, cls(context), objects.Volume,
                                  volumes)
