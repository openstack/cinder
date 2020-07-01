#    Copyright 2015 Intel Corporation
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
from oslo_serialization import base64
from oslo_serialization import jsonutils
from oslo_utils import versionutils
from oslo_versionedobjects import fields

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.objects import fields as c_fields


CONF = cfg.CONF


@base.CinderObjectRegistry.register
class Backup(base.CinderPersistentObject, base.CinderObject,
             base.CinderObjectDictCompat, base.CinderComparableObject):
    # Version 1.0: Initial version
    # Version 1.1: Add new field num_dependent_backups and extra fields
    #              is_incremental and has_dependent_backups.
    # Version 1.2: Add new field snapshot_id and data_timestamp.
    # Version 1.3: Changed 'status' field to use BackupStatusField
    # Version 1.4: Add restore_volume_id
    # Version 1.5: Add metadata
    # Version 1.6: Add encryption_key_id
    # Version 1.7: Add parent
    VERSION = '1.7'

    OPTIONAL_FIELDS = ('metadata', 'parent')

    fields = {
        'id': fields.UUIDField(),

        'user_id': fields.StringField(),
        'project_id': fields.StringField(),

        'volume_id': fields.UUIDField(),
        'host': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'container': fields.StringField(nullable=True),
        'parent_id': fields.StringField(nullable=True),
        'parent': fields.ObjectField('Backup', nullable=True),
        'status': c_fields.BackupStatusField(nullable=True),
        'fail_reason': fields.StringField(nullable=True),
        'size': fields.IntegerField(nullable=True),

        'display_name': fields.StringField(nullable=True),
        'display_description': fields.StringField(nullable=True),

        # NOTE(dulek): Metadata field is used to store any strings by backup
        # drivers, that's why it can't be DictOfStringsField.
        'service_metadata': fields.StringField(nullable=True),
        'service': fields.StringField(nullable=True),

        'object_count': fields.IntegerField(nullable=True),

        'temp_volume_id': fields.StringField(nullable=True),
        'temp_snapshot_id': fields.StringField(nullable=True),
        'num_dependent_backups': fields.IntegerField(nullable=True),
        'snapshot_id': fields.StringField(nullable=True),
        'data_timestamp': fields.DateTimeField(nullable=True),
        'restore_volume_id': fields.StringField(nullable=True),
        'metadata': fields.DictOfStringsField(nullable=True),
        'encryption_key_id': fields.StringField(nullable=True),
    }

    obj_extra_fields = ['name', 'is_incremental', 'has_dependent_backups']

    def __init__(self, *args, **kwargs):
        super(Backup, self).__init__(*args, **kwargs)
        self._orig_metadata = {}

        self._reset_metadata_tracking()

    def _reset_metadata_tracking(self, fields=None):
        if fields is None or 'metadata' in fields:
            self._orig_metadata = (dict(self.metadata)
                                   if self.obj_attr_is_set('metadata') else {})

    @classmethod
    def _get_expected_attrs(cls, context, *args, **kwargs):
        return 'metadata',

    @property
    def name(self):
        return CONF.backup_name_template % self.id

    @property
    def is_incremental(self):
        return bool(self.parent_id)

    @property
    def has_dependent_backups(self):
        return bool(self.num_dependent_backups)

    def obj_make_compatible(self, primitive, target_version):
        """Make an object representation compatible with a target version."""
        added_fields = (((1, 7), ('parent',)),)

        super(Backup, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        for version, remove_fields in added_fields:
            if target_version < version:
                for obj_field in remove_fields:
                    primitive.pop(obj_field, None)

    @classmethod
    def _from_db_object(cls, context, backup, db_backup, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for name, field in backup.fields.items():
            if name in cls.OPTIONAL_FIELDS:
                continue
            value = db_backup.get(name)
            if isinstance(field, fields.IntegerField):
                value = value if value is not None else 0
            backup[name] = value

        if 'metadata' in expected_attrs:
            metadata = db_backup.get('backup_metadata')
            if metadata is None:
                raise exception.MetadataAbsent()
            backup.metadata = {item['key']: item['value']
                               for item in metadata}

        backup._context = context
        backup.obj_reset_changes()
        return backup

    def obj_reset_changes(self, fields=None):
        super(Backup, self).obj_reset_changes(fields)
        self._reset_metadata_tracking(fields=fields)

    def obj_load_attr(self, attrname):
        if attrname not in self.OPTIONAL_FIELDS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())
        if attrname == 'parent':
            if self.parent_id:
                self.parent = self.get_by_id(self._context, self.parent_id)
            else:
                self.parent = None
        self.obj_reset_changes(fields=[attrname])

    def obj_what_changed(self):
        changes = super(Backup, self).obj_what_changed()
        if hasattr(self, 'metadata') and self.metadata != self._orig_metadata:
            changes.add('metadata')

        return changes

    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.cinder_obj_get_changes()

        db_backup = db.backup_create(self._context, updates)
        self._from_db_object(self._context, self, db_backup)

    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            if 'metadata' in updates:
                metadata = updates.pop('metadata', None)
                self.metadata = db.backup_metadata_update(self._context,
                                                          self.id, metadata,
                                                          True)
            updates.pop('parent', None)
            db.backup_update(self._context, self.id, updates)

        self.obj_reset_changes()

    def destroy(self):
        with self.obj_as_admin():
            updated_values = db.backup_destroy(self._context, self.id)
        self.update(updated_values)
        self.obj_reset_changes(updated_values.keys())

    @staticmethod
    def decode_record(backup_url):
        """Deserialize backup metadata from string into a dictionary.

        :raises InvalidInput:
        """
        try:
            return jsonutils.loads(base64.decode_as_text(backup_url))
        except TypeError:
            msg = _("Can't decode backup record.")
        except ValueError:
            msg = _("Can't parse backup record.")
        raise exception.InvalidInput(reason=msg)

    def encode_record(self, **kwargs):
        """Serialize backup object, with optional extra info, into a string."""
        # We don't want to export extra fields and we want to force lazy
        # loading, so we can't use dict(self) or self.obj_to_primitive
        record = {name: field.to_primitive(self, name, getattr(self, name))
                  for name, field in self.fields.items() if name != 'parent'}
        # We must update kwargs instead of record to ensure we don't overwrite
        # "real" data from the backup
        kwargs.update(record)
        retval = jsonutils.dump_as_bytes(kwargs)
        return base64.encode_as_text(retval)


@base.CinderObjectRegistry.register
class BackupList(base.ObjectListBase, base.CinderObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Backup'),
    }

    @classmethod
    def get_all(cls, context, filters=None, marker=None, limit=None,
                offset=None, sort_keys=None, sort_dirs=None):
        backups = db.backup_get_all(context, filters, marker, limit, offset,
                                    sort_keys, sort_dirs)
        expected_attrs = Backup._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Backup,
                                  backups, expected_attrs=expected_attrs)

    @classmethod
    def get_all_by_host(cls, context, host):
        backups = db.backup_get_all_by_host(context, host)
        expected_attrs = Backup._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Backup,
                                  backups, expected_attrs=expected_attrs)

    @classmethod
    def get_all_by_project(cls, context, project_id, filters=None,
                           marker=None, limit=None, offset=None,
                           sort_keys=None, sort_dirs=None):
        backups = db.backup_get_all_by_project(context, project_id, filters,
                                               marker, limit, offset,
                                               sort_keys, sort_dirs)
        expected_attrs = Backup._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Backup,
                                  backups, expected_attrs=expected_attrs)

    @classmethod
    def get_all_by_volume(
            cls, context, volume_id, vol_project_id, filters=None):
        backups = db.backup_get_all_by_volume(
            context, volume_id, vol_project_id, filters)
        expected_attrs = Backup._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Backup,
                                  backups, expected_attrs=expected_attrs)

    @classmethod
    def get_all_active_by_window(cls, context, begin, end):
        backups = db.backup_get_all_active_by_window(context, begin, end)
        expected_attrs = Backup._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context), objects.Backup,
                                  backups, expected_attrs=expected_attrs)


@base.CinderObjectRegistry.register
class BackupImport(Backup):
    """Special object for Backup Imports.

    This class should not be used for anything but Backup creation when
    importing backups to the DB.

    On creation it allows to specify the ID for the backup, since it's the
    reference used in parent_id it is imperative that this is preserved.

    Backup Import objects get promoted to standard Backups when the import is
    completed.
    """

    def create(self):
        updates = self.cinder_obj_get_changes()

        db_backup = db.backup_create(self._context, updates)
        self._from_db_object(self._context, self, db_backup)


@base.CinderObjectRegistry.register
class BackupDeviceInfo(base.CinderObject, base.CinderObjectDictCompat,
                       base.CinderComparableObject):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'volume': fields.ObjectField('Volume', nullable=True),
        'snapshot': fields.ObjectField('Snapshot', nullable=True),
        'secure_enabled': fields.BooleanField(default=False),
    }
    obj_extra_fields = ['is_snapshot', 'device_obj']

    @property
    def is_snapshot(self):
        if self.obj_attr_is_set('snapshot') == self.obj_attr_is_set('volume'):
            msg = _("Either snapshot or volume field should be set.")
            raise exception.ProgrammingError(message=msg)
        return self.obj_attr_is_set('snapshot')

    @property
    def device_obj(self):
        return self.snapshot if self.is_snapshot else self.volume

    # FIXME(sborkows): This should go away in early O as we stop supporting
    # backward compatibility with M.
    @classmethod
    def from_primitive(cls, primitive, context, expected_attrs=None):
        backup_device = BackupDeviceInfo()
        if primitive['is_snapshot']:
            if isinstance(primitive['backup_device'], objects.Snapshot):
                backup_device.snapshot = primitive['backup_device']
            else:
                backup_device.snapshot = objects.Snapshot._from_db_object(
                    context, objects.Snapshot(), primitive['backup_device'],
                    expected_attrs=expected_attrs)
        else:
            if isinstance(primitive['backup_device'], objects.Volume):
                backup_device.volume = primitive['backup_device']
            else:
                backup_device.volume = objects.Volume._from_db_object(
                    context, objects.Volume(), primitive['backup_device'],
                    expected_attrs=expected_attrs)
        backup_device.secure_enabled = primitive['secure_enabled']
        return backup_device

    # FIXME(sborkows): This should go away in early O as we stop supporting
    # backward compatibility with M.
    def to_primitive(self, context):
        backup_device = (db.snapshot_get(context, self.snapshot.id)
                         if self.is_snapshot
                         else db.volume_get(context, self.volume.id))
        primitive = {'backup_device': backup_device,
                     'secure_enabled': self.secure_enabled,
                     'is_snapshot': self.is_snapshot}
        return primitive
