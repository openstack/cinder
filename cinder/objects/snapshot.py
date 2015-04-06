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
# NOTE(thangp): OPTIONAL_FIELDS are fields that would be lazy-loaded. They are
# typically the relationship in the sqlalchemy object.
OPTIONAL_FIELDS = ['volume', 'metadata']
LOG = logging.getLogger(__name__)


class Snapshot(base.CinderPersistentObject, base.CinderObject,
               base.CinderObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.UUIDField(),

        'user_id': fields.UUIDField(nullable=True),
        'project_id': fields.UUIDField(nullable=True),

        'volume_id': fields.UUIDField(),
        'cgsnapshot_id': fields.UUIDField(nullable=True),
        'status': fields.StringField(nullable=True),
        'progress': fields.StringField(nullable=True),
        'volume_size': fields.IntegerField(),

        'display_name': fields.StringField(nullable=True),
        'display_description': fields.StringField(nullable=True),

        'encryption_key_id': fields.UUIDField(nullable=True),
        'volume_type_id': fields.UUIDField(nullable=True),

        'provider_location': fields.StringField(nullable=True),
        'provider_id': fields.UUIDField(nullable=True),
        'metadata': fields.DictOfStringsField(),

        'volume': fields.ObjectField('Volume', nullable=True),
    }

    # NOTE(thangp): obj_extra_fields is used to hold properties that are not
    # usually part of the model
    obj_extra_fields = ['name', 'volume_name']

    @property
    def name(self):
        return CONF.snapshot_name_template % self.id

    @property
    def volume_name(self):
        return self.volume.name

    def __init__(self, *args, **kwargs):
        super(Snapshot, self).__init__(*args, **kwargs)
        self._orig_metadata = {}

        self._reset_metadata_tracking()

    def obj_reset_changes(self, fields=None):
        super(Snapshot, self).obj_reset_changes(fields)
        self._reset_metadata_tracking(fields=fields)

    def _reset_metadata_tracking(self, fields=None):
        if fields is None or 'metadata' in fields:
            self._orig_metadata = (dict(self.metadata)
                                   if 'metadata' in self else {})

    def obj_what_changed(self):
        changes = super(Snapshot, self).obj_what_changed()
        if 'metadata' in self and self.metadata != self._orig_metadata:
            changes.add('metadata')

        return changes

    def obj_make_compatible(self, primitive, target_version):
        """Make an object representation compatible with a target version."""
        target_version = utils.convert_version_to_tuple(target_version)

    @staticmethod
    def _from_db_object(context, snapshot, db_snapshot, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for name, field in snapshot.fields.items():
            if name in OPTIONAL_FIELDS:
                continue
            value = db_snapshot.get(name)
            if isinstance(field, fields.IntegerField):
                value = value if value is not None else 0
            snapshot[name] = value

        if 'volume' in expected_attrs:
            volume = objects.Volume(context)
            volume._from_db_object(context, volume, db_snapshot['volume'])
            snapshot.volume = volume
        if 'metadata' in expected_attrs:
            snapshot.metadata = db.snapshot_metadata_get(context,
                                                         db_snapshot['id'])

        snapshot._context = context
        snapshot.obj_reset_changes()
        return snapshot

    @base.remotable_classmethod
    def get_by_id(cls, context, id):
        db_snapshot = db.snapshot_get(context, id)
        return cls._from_db_object(context, cls(context), db_snapshot,
                                   expected_attrs=['metadata'])

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already created'))
        updates = self.obj_get_changes()

        if 'volume' in updates:
            raise exception.ObjectActionError(action='create',
                                              reason=_('volume assigned'))

        db_snapshot = db.snapshot_create(context, updates)
        self._from_db_object(context, self, db_snapshot)

    @base.remotable
    def save(self, context):
        updates = self.obj_get_changes()
        if updates:
            if 'volume' in updates:
                raise exception.ObjectActionError(action='save',
                                                  reason=_('volume changed'))

            if 'metadata' in updates:
                # Metadata items that are not specified in the
                # self.metadata will be deleted
                metadata = updates.pop('metadata', None)
                self.metadata = db.snapshot_metadata_update(context, self.id,
                                                            metadata, True)

            db.snapshot_update(context, self.id, updates)

        self.obj_reset_changes()

    @base.remotable
    def destroy(self, context):
        db.snapshot_destroy(context, self.id)

    def obj_load_attr(self, attrname):
        if attrname not in OPTIONAL_FIELDS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        if attrname == 'volume':
            self.volume = objects.Volume.get_by_id(self._context,
                                                   self.volume_id)

        self.obj_reset_changes(fields=[attrname])

    def delete_metadata_key(self, context, key):
        db.snapshot_metadata_delete(context, self.id, key)
        md_was_changed = 'metadata' in self.obj_what_changed()

        del self.metadata[key]
        self._orig_metadata.pop(key, None)

        if not md_was_changed:
            self.obj_reset_changes(['metadata'])


class SnapshotList(base.ObjectListBase, base.CinderObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Snapshot'),
    }
    child_versions = {
        '1.0': '1.0'
    }

    @base.remotable_classmethod
    def get_all(cls, context):
        snapshots = db.snapshot_get_all(context)
        return base.obj_make_list(context, cls(), objects.Snapshot,
                                  snapshots,
                                  expected_attrs=['metadata'])

    @base.remotable_classmethod
    def get_all_by_project(cls, context, project_id):
        snapshots = db.snapshot_get_all_by_project(context, project_id)
        return base.obj_make_list(context, cls(context), objects.Snapshot,
                                  snapshots, expected_attrs=['metadata'])

    @base.remotable_classmethod
    def get_all_for_volume(cls, context, volume_id):
        snapshots = db.snapshot_get_all_for_volume(context, volume_id)
        return base.obj_make_list(context, cls(context), objects.Snapshot,
                                  snapshots, expected_attrs=['metadata'])
