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
from oslo_utils import versionutils
from oslo_versionedobjects import fields

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.objects import cleanable
from cinder.objects import fields as c_fields
from cinder.volume import volume_types


CONF = cfg.CONF


@base.CinderObjectRegistry.register
class Snapshot(cleanable.CinderCleanableObject, base.CinderObject,
               base.CinderObjectDictCompat, base.CinderComparableObject,
               base.ClusteredObject):
    # Version 1.0: Initial version
    # Version 1.1: Changed 'status' field to use SnapshotStatusField
    # Version 1.2: This object is now cleanable (adds rows to workers table)
    # Version 1.3: SnapshotStatusField now includes "unmanaging"
    # Version 1.4: SnapshotStatusField now includes "backing-up"
    # Version 1.5: SnapshotStatusField now includes "restoring"
    # Version 1.6: Added use_quota
    VERSION = '1.6'

    # NOTE(thangp): OPTIONAL_FIELDS are fields that would be lazy-loaded. They
    # are typically the relationship in the sqlalchemy object.
    OPTIONAL_FIELDS = ('volume', 'metadata', 'cgsnapshot', 'group_snapshot')

    # NOTE: When adding a field obj_make_compatible needs to be updated
    fields = {
        'id': fields.UUIDField(),

        'user_id': fields.StringField(nullable=True),
        'project_id': fields.StringField(nullable=True),

        # TODO: (Y release) Change nullable to False
        'use_quota': fields.BooleanField(default=True, nullable=True),
        'volume_id': fields.UUIDField(nullable=True),
        'cgsnapshot_id': fields.UUIDField(nullable=True),
        'group_snapshot_id': fields.UUIDField(nullable=True),
        'status': c_fields.SnapshotStatusField(nullable=True),
        'progress': fields.StringField(nullable=True),
        'volume_size': fields.IntegerField(nullable=True),

        'display_name': fields.StringField(nullable=True),
        'display_description': fields.StringField(nullable=True),

        'encryption_key_id': fields.UUIDField(nullable=True),
        'volume_type_id': fields.UUIDField(nullable=True),

        'provider_location': fields.StringField(nullable=True),
        'provider_id': fields.StringField(nullable=True),
        'metadata': fields.DictOfStringsField(),
        'provider_auth': fields.StringField(nullable=True),

        'volume': fields.ObjectField('Volume', nullable=True),
        'cgsnapshot': fields.ObjectField('CGSnapshot', nullable=True),
        'group_snapshot': fields.ObjectField('GroupSnapshot', nullable=True),
    }

    @property
    def cluster_name(self):
        return self.volume.cluster_name

    @classmethod
    def _get_expected_attrs(cls, context, *args, **kwargs):
        return 'metadata',

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
        self.metadata = kwargs.get('metadata', {})

        self._reset_metadata_tracking()

    def obj_reset_changes(self, fields=None):
        super(Snapshot, self).obj_reset_changes(fields)
        self._reset_metadata_tracking(fields=fields)

    def _reset_metadata_tracking(self, fields=None):
        if fields is None or 'metadata' in fields:
            self._orig_metadata = (dict(self.metadata)
                                   if self.obj_attr_is_set('metadata') else {})

    # TODO: (Y release) remove method
    @classmethod
    def _obj_from_primitive(cls, context, objver, primitive):
        primitive['versioned_object.data'].setdefault('use_quota', True)
        obj = super(Snapshot, Snapshot)._obj_from_primitive(context, objver,
                                                            primitive)
        obj._reset_metadata_tracking()
        return obj

    def obj_what_changed(self):
        changes = super(Snapshot, self).obj_what_changed()
        if hasattr(self, 'metadata') and self.metadata != self._orig_metadata:
            changes.add('metadata')

        return changes

    def obj_make_compatible(self, primitive, target_version):
        """Make a Snapshot representation compatible with a target version."""
        super(Snapshot, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        # TODO: (Y release) remove next 2 lines & method if nothing else below
        if target_version < (1, 6):
            primitive.pop('use_quota', None)

    @classmethod
    def _from_db_object(cls, context, snapshot, db_snapshot,
                        expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for name, field in snapshot.fields.items():
            if name in cls.OPTIONAL_FIELDS:
                continue
            value = db_snapshot.get(name)
            if isinstance(field, fields.IntegerField):
                value = value if value is not None else 0
            setattr(snapshot, name, value)

        if 'volume' in expected_attrs:
            volume = objects.Volume(context)
            volume._from_db_object(context, volume, db_snapshot['volume'])
            snapshot.volume = volume
        if snapshot.cgsnapshot_id and 'cgsnapshot' in expected_attrs:
            cgsnapshot = objects.CGSnapshot(context)
            cgsnapshot._from_db_object(context, cgsnapshot,
                                       db_snapshot['cgsnapshot'])
            snapshot.cgsnapshot = cgsnapshot
        if snapshot.group_snapshot_id and 'group_snapshot' in expected_attrs:
            group_snapshot = objects.GroupSnapshot(context)
            group_snapshot._from_db_object(context, group_snapshot,
                                           db_snapshot['group_snapshot'])
            snapshot.group_snapshot = group_snapshot

        if 'metadata' in expected_attrs:
            metadata = db_snapshot.get('snapshot_metadata')
            if metadata is None:
                raise exception.MetadataAbsent()
            snapshot.metadata = {item['key']: item['value']
                                 for item in metadata}
        snapshot._context = context
        snapshot.obj_reset_changes()
        return snapshot

    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already created'))
        updates = self.cinder_obj_get_changes()

        if 'volume' in updates:
            raise exception.ObjectActionError(action='create',
                                              reason=_('volume assigned'))
        if 'cgsnapshot' in updates:
            raise exception.ObjectActionError(action='create',
                                              reason=_('cgsnapshot assigned'))
        if 'cluster' in updates:
            raise exception.ObjectActionError(
                action='create', reason=_('cluster assigned'))
        if 'group_snapshot' in updates:
            raise exception.ObjectActionError(
                action='create',
                reason=_('group_snapshot assigned'))
        if ('volume_type_id' not in updates or
                updates['volume_type_id'] is None):
            updates['volume_type_id'] = (
                volume_types.get_default_volume_type()['id'])

        # TODO: (Y release) remove setting use_quota default, it's set by ORM
        updates.setdefault('use_quota', True)
        db_snapshot = db.snapshot_create(self._context, updates)
        self._from_db_object(self._context, self, db_snapshot)

    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            if 'volume' in updates:
                raise exception.ObjectActionError(action='save',
                                                  reason=_('volume changed'))
            if 'cgsnapshot' in updates:
                # NOTE(xyang): Allow this to pass if 'cgsnapshot' is
                # set to None. This is to support backward compatibility.
                if updates.get('cgsnapshot'):
                    raise exception.ObjectActionError(
                        action='save', reason=_('cgsnapshot changed'))
            if 'group_snapshot' in updates:
                raise exception.ObjectActionError(
                    action='save', reason=_('group_snapshot changed'))

            if 'cluster' in updates:
                raise exception.ObjectActionError(
                    action='save', reason=_('cluster changed'))

            if 'metadata' in updates:
                # Metadata items that are not specified in the
                # self.metadata will be deleted
                metadata = updates.pop('metadata', None)
                self.metadata = db.snapshot_metadata_update(self._context,
                                                            self.id, metadata,
                                                            True)

            db.snapshot_update(self._context, self.id, updates)

        self.obj_reset_changes()

    def destroy(self):
        with self.obj_as_admin():
            updated_values = db.snapshot_destroy(self._context, self.id)
        self.update(updated_values)
        self.obj_reset_changes(updated_values.keys())

    def obj_load_attr(self, attrname):
        if attrname not in self.OPTIONAL_FIELDS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        if attrname == 'volume':
            self.volume = objects.Volume.get_by_id(self._context,
                                                   self.volume_id)

        if attrname == 'cgsnapshot':
            if self.cgsnapshot_id is None:
                self.cgsnapshot = None
            else:
                self.cgsnapshot = objects.CGSnapshot.get_by_id(
                    self._context, self.cgsnapshot_id)
        if attrname == 'group_snapshot':
            if self.group_snapshot_id is None:
                self.group_snapshot = None
            else:
                self.group_snapshot = objects.GroupSnapshot.get_by_id(
                    self._context,
                    self.group_snapshot_id)

        self.obj_reset_changes(fields=[attrname])

    def delete_metadata_key(self, context, key):
        db.snapshot_metadata_delete(context, self.id, key)
        md_was_changed = 'metadata' in self.obj_what_changed()

        del self.metadata[key]
        self._orig_metadata.pop(key, None)

        if not md_was_changed:
            self.obj_reset_changes(['metadata'])

    @classmethod
    def snapshot_data_get_for_project(cls, context, project_id,
                                      volume_type_id=None, host=None):
        return db.snapshot_data_get_for_project(context, project_id,
                                                volume_type_id,
                                                host=host)

    @staticmethod
    def _is_cleanable(status, obj_version):
        # Before 1.2 we didn't have workers table, so cleanup wasn't supported.
        if obj_version and obj_version < 1.2:
            return False
        return status == 'creating'

    @property
    def host(self):
        """All cleanable VO must have a host property/attribute."""
        return self.volume.host


@base.CinderObjectRegistry.register
class SnapshotList(base.ObjectListBase, base.CinderObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Snapshot'),
    }

    @classmethod
    def get_all(cls, context, filters, marker=None, limit=None,
                sort_keys=None, sort_dirs=None, offset=None):
        """Get all snapshot given some search_opts (filters).

        Special filters accepted are host and cluster_name, that refer to the
        volume's fields.
        """
        snapshots = db.snapshot_get_all(context, filters, marker, limit,
                                        sort_keys, sort_dirs, offset)
        expected_attrs = Snapshot._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Snapshot,
                                  snapshots, expected_attrs=expected_attrs)

    @classmethod
    def get_by_host(cls, context, host, filters=None):
        snapshots = db.snapshot_get_all_by_host(context, host, filters)
        expected_attrs = Snapshot._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Snapshot,
                                  snapshots, expected_attrs=expected_attrs)

    @classmethod
    def get_all_by_project(cls, context, project_id, search_opts, marker=None,
                           limit=None, sort_keys=None, sort_dirs=None,
                           offset=None):
        snapshots = db.snapshot_get_all_by_project(
            context, project_id, search_opts, marker, limit, sort_keys,
            sort_dirs, offset)
        expected_attrs = Snapshot._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Snapshot,
                                  snapshots, expected_attrs=expected_attrs)

    @classmethod
    def get_all_for_volume(cls, context, volume_id):
        snapshots = db.snapshot_get_all_for_volume(context, volume_id)
        expected_attrs = Snapshot._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Snapshot,
                                  snapshots, expected_attrs=expected_attrs)

    @classmethod
    def get_all_active_by_window(cls, context, begin, end):
        snapshots = db.snapshot_get_all_active_by_window(context, begin, end)
        expected_attrs = Snapshot._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Snapshot,
                                  snapshots, expected_attrs=expected_attrs)

    @classmethod
    def get_all_for_cgsnapshot(cls, context, cgsnapshot_id):
        snapshots = db.snapshot_get_all_for_cgsnapshot(context, cgsnapshot_id)
        expected_attrs = Snapshot._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Snapshot,
                                  snapshots, expected_attrs=expected_attrs)

    @classmethod
    def get_all_for_group_snapshot(cls, context, group_snapshot_id):
        snapshots = db.snapshot_get_all_for_group_snapshot(
            context, group_snapshot_id)
        expected_attrs = Snapshot._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Snapshot,
                                  snapshots, expected_attrs=expected_attrs)

    @classmethod
    def get_snapshot_summary(cls, context, project_only, filters=None):
        summary = db.get_snapshot_summary(context, project_only, filters)
        return summary
