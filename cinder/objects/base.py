#    Copyright 2015 IBM Corp.
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

"""Cinder common internal object model"""

from collections import abc
import contextlib
import datetime

from oslo_log import log as logging
from oslo_utils import versionutils
from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects


LOG = logging.getLogger('object')
obj_make_list = base.obj_make_list


class CinderObjectVersionsHistory(dict):
    """Helper class that maintains objects version history.

    Current state of object versions is aggregated in a single version number
    that explicitly identifies a set of object versions. That way a service
    is able to report what objects it supports using a single string and all
    the newer services will know exactly what that mean for a single object.
    """

    def __init__(self):
        super(CinderObjectVersionsHistory, self).__init__()
        # NOTE(dulek): This is our pre-history and a starting point - Liberty.
        # We want Mitaka to be able to talk to Liberty services, so we need to
        # handle backporting to these objects versions (although I don't expect
        # we've made a lot of incompatible changes inside the objects).
        #
        # If an object doesn't exist in Liberty, RPC API compatibility layer
        # shouldn't send it or convert it to a dictionary.
        #
        # Please note that we do not need to add similar entires for each
        # release. Liberty is here just for historical reasons.
        self.versions = ['1.38']
        self['1.38'] = {
            'Backup': '1.7',
            'BackupDeviceInfo': '1.0',
            'BackupImport': '1.7',
            'BackupList': '1.0',
            'CleanupRequest': '1.0',
            'CGSnapshot': '1.1',
            'CGSnapshotList': '1.0',
            'Cluster': '1.1',
            'ClusterList': '1.0',
            'ConsistencyGroup': '1.4',
            'ConsistencyGroupList': '1.1',
            'Group': '1.2',
            'GroupList': '1.0',
            'GroupSnapshot': '1.0',
            'GroupSnapshotList': '1.0',
            'GroupType': '1.0',
            'GroupTypeList': '1.0',
            'LogLevel': '1.0',
            'LogLevelList': '1.0',
            'ManageableSnapshot': '1.0',
            'ManageableSnapshotList': '1.0',
            'ManageableVolume': '1.0',
            'ManageableVolumeList': '1.0',
            'QualityOfServiceSpecs': '1.0',
            'QualityOfServiceSpecsList': '1.0',
            'RequestSpec': '1.5',
            'Service': '1.6',
            'ServiceList': '1.1',
            'Snapshot': '1.5',
            'SnapshotList': '1.0',
            'Volume': '1.8',
            'VolumeAttachment': '1.3',
            'VolumeAttachmentList': '1.1',
            'VolumeList': '1.1',
            'VolumeProperties': '1.1',
            'VolumeType': '1.3',
            'VolumeTypeList': '1.1',
        }

    def get_current(self):
        return self.versions[-1]

    def get_current_versions(self):
        return self[self.get_current()]

    def add(self, ver, updates):
        if ver in self.versions:
            msg = 'Version %s already exists in history.' % ver
            raise exception.ProgrammingError(reason=msg)

        self[ver] = self[self.get_current()].copy()
        self.versions.append(ver)
        self[ver].update(updates)


OBJ_VERSIONS = CinderObjectVersionsHistory()
# NOTE(dulek): You should add a new version here each time you bump a version
# of any object. As a second parameter you need to specify only what changed.

# On each release we should drop backward compatibility with -2 release, since
# rolling upgrades only needs to support compatibility with previous release.
# So if we are in N release we can remove history from L and earlier.
# Example of how to keep track of this:
#     # TODO: (T release) remove up to next TODO (was added in R release) and
#     #       update CinderObjectVersionsHistory
#     OBJ_VERSIONS.add('1.34', {'VolumeAttachment': '1.3'})
#     OBJ_VERSIONS.add('1.35', {'Backup': '1.6', 'BackupImport': '1.6'})
#
#     # TODO: (U release) remove up to next TODO (was added in S release) and
#     #       update CinderObjectVersionsHistory
#     OBJ_VERSIONS.add('1.36', {'RequestSpec': '1.4'})
#     OBJ_VERSIONS.add('1.37', {'RequestSpec': '1.5'})
#     OBJ_VERSIONS.add('1.38', {'Backup': '1.7', 'BackupImport': '1.7'})
# When we reach T release we remove versions 1.34 and 1.35 and update __init__
# method in CinderObjectVerseionsHistory to bump VolumeAttachment to 1.3,
# Backup to 1.6 and BackupImport to 1.6, and changing the versions list to
# '1.35' and the self['<versioname>'] = { to self['1.35'] = {


# TODO: (Z release) remove up to next TODO  and update
#       CinderObjectVersionsHistory (was added in X release)
OBJ_VERSIONS.add('1.39', {'Volume': '1.9', 'Snapshot': '1.6'})


class CinderObjectRegistry(base.VersionedObjectRegistry):
    def registration_hook(self, cls, index):
        """Hook called when registering a class.

        This method takes care of adding the class to cinder.objects namespace.

        Should registering class have a method called cinder_ovo_cls_init it
        will be called to support class initialization.  This is convenient
        for all persistent classes that need to register their models.
        """
        setattr(objects, cls.obj_name(), cls)

        # If registering class has a callable initialization method, call it.
        if isinstance(getattr(cls, 'cinder_ovo_cls_init', None),
                      abc.Callable):
            cls.cinder_ovo_cls_init()


class CinderObject(base.VersionedObject):
    # NOTE(thangp): OBJ_PROJECT_NAMESPACE needs to be set so that nova,
    # cinder, and other objects can exist on the same bus and be distinguished
    # from one another.
    OBJ_PROJECT_NAMESPACE = 'cinder'

    def cinder_obj_get_changes(self):
        """Returns a dict of changed fields with tz unaware datetimes.

        Any timezone aware datetime field will be converted to UTC timezone
        and returned as timezone unaware datetime.

        This will allow us to pass these fields directly to a db update
        method as they can't have timezone information.
        """
        # Get dirtied/changed fields
        changes = self.obj_get_changes()

        # Look for datetime objects that contain timezone information
        for k, v in changes.items():
            if isinstance(v, datetime.datetime) and v.tzinfo:
                # Remove timezone information and adjust the time according to
                # the timezone information's offset.
                changes[k] = v.replace(tzinfo=None) - v.utcoffset()

        # Return modified dict
        return changes

    def obj_make_compatible(self, primitive, target_version):
        _log_backport(self, target_version)
        super(CinderObject, self).obj_make_compatible(primitive,
                                                      target_version)

    def __contains__(self, name):
        # We're using obj_extra_fields to provide aliases for some fields while
        # in transition period. This override is to make these aliases pass
        # "'foo' in obj" tests.
        return name in self.obj_extra_fields or super(CinderObject,
                                                      self).__contains__(name)


class CinderObjectDictCompat(base.VersionedObjectDictCompat):
    """Mix-in to provide dictionary key access compat.

    If an object needs to support attribute access using
    dictionary items instead of object attributes, inherit
    from this class. This should only be used as a temporary
    measure until all callers are converted to use modern
    attribute access.

    NOTE(berrange) This class will eventually be deleted.
    """

    def get(self, key, value=base._NotSpecifiedSentinel):
        """For backwards-compatibility with dict-based objects.

        NOTE(danms): May be removed in the future.
        """
        if key not in self.obj_fields:
            # NOTE(jdg): There are a number of places where we rely on the
            # old dictionary version and do a get(xxx, None).
            # The following preserves that compatibility but in
            # the future we'll remove this shim altogether so don't
            # rely on it.
            LOG.debug('Cinder object %(object_name)s has no '
                      'attribute named: %(attribute_name)s',
                      {'object_name': self.__class__.__name__,
                       'attribute_name': key})
            return None
        if (value != base._NotSpecifiedSentinel and
                key not in self.obj_extra_fields and
                not self.obj_attr_is_set(key)):
            return value
        else:
            try:
                return getattr(self, key)
            except (exception.ObjectActionError, NotImplementedError):
                # Exception when haven't set a value for non-lazy
                # loadable attribute, but to mimic typical dict 'get'
                # behavior we should still return None
                return None


class CinderPersistentObject(object):
    """Mixin class for Persistent objects.

    This adds the fields that we use in common for all persistent objects.
    """
    OPTIONAL_FIELDS = []

    Not = db.Not
    Case = db.Case

    fields = {
        'created_at': fields.DateTimeField(nullable=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'deleted_at': fields.DateTimeField(nullable=True),
        'deleted': fields.BooleanField(default=False,
                                       nullable=True),
    }

    @classmethod
    def cinder_ovo_cls_init(cls):
        """This method is called on OVO registration and sets the DB model."""
        # Persistent Versioned Objects Classes should have a DB model, and if
        # they don't, then we have a problem and we must raise an exception on
        # registration.
        try:
            cls.model = db.get_model_for_versioned_object(cls)
        except (ImportError, AttributeError):
            msg = _("Couldn't find ORM model for Persistent Versioned "
                    "Object %s.") % cls.obj_name()
            LOG.exception("Failed to initialize object.")
            raise exception.ProgrammingError(reason=msg)

    @contextlib.contextmanager
    def obj_as_admin(self):
        """Context manager to make an object call as an admin.

        This temporarily modifies the context embedded in an object to
        be elevated() and restores it after the call completes. Example
        usage:

           with obj.obj_as_admin():
               obj.save()
        """
        if self._context is None:
            raise exception.OrphanedObjectError(method='obj_as_admin',
                                                objtype=self.obj_name())

        original_context = self._context
        self._context = self._context.elevated()
        try:
            yield
        finally:
            self._context = original_context

    @contextlib.contextmanager
    def as_read_deleted(self, mode='yes'):
        """Context manager to make OVO with modified read deleted context.

        This temporarily modifies the context embedded in an object to
        have a different `read_deleted` parameter.

        Parameter mode accepts most of the same parameters as our `model_query`
        DB method.  We support 'yes', 'no', and 'only'.

        usage:

           with obj.as_read_deleted():
               obj.refresh()
           if obj.status = 'deleted':
               ...
        """
        if self._context is None:
            raise exception.OrphanedObjectError(method='as_read_deleted',
                                                objtype=self.obj_name())

        original_mode = self._context.read_deleted
        self._context.read_deleted = mode
        try:
            yield
        finally:
            self._context.read_deleted = original_mode

    @classmethod
    def _get_expected_attrs(cls, context, *args, **kwargs):
        return None

    @classmethod
    def get_by_id(cls, context, id, *args, **kwargs):
        # To get by id we need to have a model and for the model to
        # have an id field
        if 'id' not in cls.fields:
            msg = (_('VersionedObject %s cannot retrieve object by id.') %
                   (cls.obj_name()))
            raise NotImplementedError(msg)

        orm_obj = db.get_by_id(context, cls.model, id, *args, **kwargs)
        # We pass parameters because fields to expect may depend on them
        expected_attrs = cls._get_expected_attrs(context, *args, **kwargs)
        kargs = {}
        if expected_attrs:
            kargs = {'expected_attrs': expected_attrs}
        return cls._from_db_object(context, cls(context), orm_obj, **kargs)

    def update_single_status_where(self, new_status,
                                   expected_status, filters=()):
        values = {'status': new_status}
        expected_status = {'status': expected_status}
        return self.conditional_update(values, expected_status, filters)

    def conditional_update(self, values, expected_values=None, filters=(),
                           save_all=False, session=None, reflect_changes=True,
                           order=None):
        """Compare-and-swap update.

        A conditional object update that, unlike normal update, will SAVE the
        contents of the update to the DB.

        Update will only occur in the DB and the object if conditions are met.

        If no expected_values are passed in we will default to make sure that
        all fields have not been changed in the DB. Since we cannot know the
        original value in the DB for dirty fields in the object those will be
        excluded.

        We have 4 different condition types we can use in expected_values:
         - Equality:  {'status': 'available'}
         - Inequality: {'status': vol_obj.Not('deleting')}
         - In range: {'status': ['available', 'error']
         - Not in range: {'status': vol_obj.Not(['in-use', 'attaching'])

        Method accepts additional filters, which are basically anything that
        can be passed to a sqlalchemy query's filter method, for example:

        .. code-block:: python

         [~sql.exists().where(models.Volume.id == models.Snapshot.volume_id)]

        We can select values based on conditions using Case objects in the
        'values' argument. For example:

        .. code-block:: python

         has_snapshot_filter = sql.exists().where(
             models.Snapshot.volume_id == models.Volume.id)
         case_values = volume.Case([(has_snapshot_filter, 'has-snapshot')],
                                   else_='no-snapshot')
         volume.conditional_update({'status': case_values},
                                   {'status': 'available'}))

        And we can use DB fields using model class attribute for example to
        store previous status in the corresponding field even though we don't
        know which value is in the db from those we allowed:

        .. code-block:: python

         volume.conditional_update({'status': 'deleting',
                                    'previous_status': volume.model.status},
                                   {'status': ('available', 'error')})

        :param values: Dictionary of key-values to update in the DB.
        :param expected_values: Dictionary of conditions that must be met for
                                the update to be executed.
        :param filters: Iterable with additional filters
        :param save_all: Object may have changes that are not in the DB, this
                         will say whether we want those changes saved as well.
        :param session: Session to use for the update
        :param reflect_changes: If we want changes made in the database to be
                                reflected in the versioned object.  This may
                                mean in some cases that we have to reload the
                                object from the database.
        :param order: Specific order of fields in which to update the values
        :returns: number of db rows that were updated, which can be used as a
                  boolean, since it will be 0 if we couldn't update the DB and
                  1 if we could, because we are using unique index id.
        """
        if 'id' not in self.fields:
            msg = (_('VersionedObject %s does not support conditional update.')
                   % (self.obj_name()))
            raise NotImplementedError(msg)

        # If no conditions are set we will require object in DB to be unchanged
        if expected_values is None:
            changes = self.obj_what_changed()

            expected = {key: getattr(self, key)
                        for key in self.fields.keys()
                        if self.obj_attr_is_set(key) and key not in changes and
                        key not in self.OPTIONAL_FIELDS}
        else:
            # Set the id in expected_values to limit conditional update to only
            # change this object
            expected = expected_values.copy()
            expected['id'] = self.id

        # If we want to save any additional changes the object has besides the
        # ones referred in values
        if save_all:
            changes = self.cinder_obj_get_changes()
            changes.update(values)
            values = changes

        result = db.conditional_update(self._context, self.model, values,
                                       expected, filters, order=order)

        # If we were able to update the DB then we need to update this object
        # as well to reflect new DB contents and clear the object's dirty flags
        # for those fields.
        if result and reflect_changes:
            # If we have used a Case, a db field or an expression in values we
            # don't know which value was used, so we need to read the object
            # back from the DB
            if any(isinstance(v, self.Case) or db.is_orm_value(v)
                   for v in values.values()):
                # Read back object from DB
                obj = type(self).get_by_id(self._context, self.id)
                db_values = obj.obj_to_primitive()['versioned_object.data']
                # Only update fields were changes were requested
                values = {field: db_values[field]
                          for field, value in values.items()}

            # NOTE(geguileo): We don't use update method because our objects
            # will eventually move away from VersionedObjectDictCompat
            for key, value in values.items():
                setattr(self, key, value)
            self.obj_reset_changes(values.keys())
        return result

    def refresh(self):
        # To refresh we need to have a model and for the model to have an id
        # field
        if 'id' not in self.fields:
            msg = (_('VersionedObject %s cannot retrieve object by id.') %
                   (self.obj_name()))
            raise NotImplementedError(msg)

        current = self.get_by_id(self._context, self.id)

        # Copy contents retrieved from the DB into self
        my_data = vars(self)
        my_data.clear()
        my_data.update(vars(current))

    @classmethod
    def exists(cls, context, id_):
        return db.resource_exists(context, cls.model, id_)


class CinderComparableObject(base.ComparableVersionedObject):
    def __eq__(self, obj):
        if hasattr(obj, 'obj_to_primitive'):
            return self.obj_to_primitive() == obj.obj_to_primitive()
        return False

    def __ne__(self, other):
        return not self.__eq__(other)


class ObjectListBase(base.ObjectListBase):
    def obj_make_compatible(self, primitive, target_version):
        _log_backport(self, target_version)
        super(ObjectListBase, self).obj_make_compatible(primitive,
                                                        target_version)


class ClusteredObject(object):
    @property
    def service_topic_queue(self):
        return self.cluster_name or self.host

    @property
    def is_clustered(self):
        return bool(self.cluster_name)

    def assert_not_frozen(self):
        ctxt = self._context.elevated()
        if db.is_backend_frozen(ctxt, self.host, self.cluster_name):
            msg = _('Modification operations are not allowed on frozen '
                    'storage backends.')
            raise exception.InvalidInput(reason=msg)

    # The object's resource backend depends on whether it's clustered.
    resource_backend = service_topic_queue


class CinderObjectSerializer(base.VersionedObjectSerializer):
    OBJ_BASE_CLASS = CinderObject

    def __init__(self, version_cap=None):
        super(CinderObjectSerializer, self).__init__()
        self.version_cap = version_cap

        # NOTE(geguileo): During upgrades we will use a manifest to ensure that
        # all objects are properly backported.  This allows us to properly
        # backport child objects to the right version even if parent version
        # has not been bumped.
        if not version_cap or version_cap == OBJ_VERSIONS.get_current():
            self.manifest = None
        else:
            if version_cap not in OBJ_VERSIONS:
                raise exception.CappedVersionUnknown(version=version_cap)
            self.manifest = OBJ_VERSIONS[version_cap]

    def _get_capped_obj_version(self, obj):
        objname = obj.obj_name()
        version_dict = OBJ_VERSIONS.get(self.version_cap, {})
        version_cap = version_dict.get(objname, None)

        if version_cap:
            cap_tuple = versionutils.convert_version_to_tuple(version_cap)
            obj_tuple = versionutils.convert_version_to_tuple(obj.VERSION)
            if cap_tuple > obj_tuple:
                # NOTE(dulek): Do not set version cap to be higher than actual
                # object version as we don't support "forwardporting" of
                # objects. If service will receive an object that's too old it
                # should handle it explicitly.
                version_cap = None

        return version_cap

    def serialize_entity(self, context, entity):
        if isinstance(entity, (tuple, list, set, dict)):
            entity = self._process_iterable(context, self.serialize_entity,
                                            entity)
        elif (hasattr(entity, 'obj_to_primitive') and
              isinstance(entity.obj_to_primitive, abc.Callable)):
            # NOTE(dulek): Backport outgoing object to the capped version.
            backport_ver = self._get_capped_obj_version(entity)
            entity = entity.obj_to_primitive(backport_ver, self.manifest)
        return entity


def _log_backport(ovo, target_version):
    """Log backported versioned objects."""
    if target_version and target_version != ovo.VERSION:
        LOG.debug('Backporting %(obj_name)s from version %(src_vers)s '
                  'to version %(dst_vers)s',
                  {'obj_name': ovo.obj_name(),
                   'src_vers': ovo.VERSION,
                   'dst_vers': target_version})
