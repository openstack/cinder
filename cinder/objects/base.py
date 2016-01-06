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

import contextlib
import datetime

from oslo_log import log as logging
from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects


LOG = logging.getLogger('object')
remotable = base.remotable
remotable_classmethod = base.remotable_classmethod
obj_make_list = base.obj_make_list


class CinderObjectRegistry(base.VersionedObjectRegistry):
    def registration_hook(self, cls, index):
        setattr(objects, cls.obj_name(), cls)
        # For Versioned Object Classes that have a model store the model in
        # a Class attribute named model
        try:
            cls.model = db.get_model_for_versioned_object(cls)
        except (ImportError, AttributeError):
            pass


class CinderObject(base.VersionedObject):
    # NOTE(thangp): OBJ_PROJECT_NAMESPACE needs to be set so that nova,
    # cinder, and other objects can exist on the same bus and be distinguished
    # from one another.
    OBJ_PROJECT_NAMESPACE = 'cinder'

    # NOTE(thangp): As more objects are added to cinder, each object should
    # have a custom map of version compatibility.  This just anchors the base
    # version compatibility.
    VERSION_COMPATIBILITY = {'7.0.0': '1.0'}

    Not = db.Not
    Case = db.Case

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

    @base.remotable_classmethod
    def get_by_id(cls, context, id, *args, **kwargs):
        # To get by id we need to have a model and for the model to
        # have an id field
        if 'id' not in cls.fields:
            msg = (_('VersionedObject %s cannot retrieve object by id.') %
                   (cls.obj_name()))
            raise NotImplementedError(msg)

        model = db.get_model_for_versioned_object(cls)
        orm_obj = db.get_by_id(context, model, id, *args, **kwargs)
        kargs = {}
        if hasattr(cls, 'DEFAULT_EXPECTED_ATTR'):
            kargs = {'expected_attrs': getattr(cls, 'DEFAULT_EXPECTED_ATTR')}
        return cls._from_db_object(context, cls(context), orm_obj, **kargs)

    def conditional_update(self, values, expected_values=None, filters=(),
                           save_all=False, session=None, reflect_changes=True):
        """Compare-and-swap update.

           A conditional object update that, unlike normal update, will SAVE
           the contents of the update to the DB.

           Update will only occur in the DB and the object if conditions are
           met.

           If no expected_values are passed in we will default to make sure
           that all fields have not been changed in the DB. Since we cannot
           know the original value in the DB for dirty fields in the object
           those will be excluded.

           We have 4 different condition types we can use in expected_values:
            - Equality:  {'status': 'available'}
            - Inequality: {'status': vol_obj.Not('deleting')}
            - In range: {'status': ['available', 'error']
            - Not in range: {'status': vol_obj.Not(['in-use', 'attaching'])

           Method accepts additional filters, which are basically anything that
           can be passed to a sqlalchemy query's filter method, for example:
           [~sql.exists().where(models.Volume.id == models.Snapshot.volume_id)]

           We can select values based on conditions using Case objects in the
           'values' argument. For example:
           has_snapshot_filter = sql.exists().where(
               models.Snapshot.volume_id == models.Volume.id)
           case_values = volume.Case([(has_snapshot_filter, 'has-snapshot')],
                                     else_='no-snapshot')
           volume.conditional_update({'status': case_values},
                                     {'status': 'available'}))

            And we can use DB fields using model class attribute for example to
            store previous status in the corresponding field even though we
            don't know which value is in the db from those we allowed:
            volume.conditional_update({'status': 'deleting',
                                       'previous_status': volume.model.status},
                                      {'status': ('available', 'error')})

           :param values: Dictionary of key-values to update in the DB.
           :param expected_values: Dictionary of conditions that must be met
                                   for the update to be executed.
           :param filters: Iterable with additional filters
           :param save_all: Object may have changes that are not in the DB,
                            this will say whether we want those changes saved
                            as well.
           :param session: Session to use for the update
           :param reflect_changes: If we want changes made in the database to
                                   be reflected in the versioned object.  This
                                   may mean in some cases that we have to
                                   reload the object from the database.
           :returns number of db rows that were updated, which can be used as a
                    boolean, since it will be 0 if we couldn't update the DB
                    and 1 if we could, because we are using unique index id.
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
                                       expected, filters)

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

        for field in self.fields:
            # Only update attributes that are already set.  We do not want to
            # unexpectedly trigger a lazy-load.
            if self.obj_attr_is_set(field):
                if self[field] != current[field]:
                    self[field] = current[field]
        self.obj_reset_changes()

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
    fields = {
        'created_at': fields.DateTimeField(nullable=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'deleted_at': fields.DateTimeField(nullable=True),
        'deleted': fields.BooleanField(default=False),
    }

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


class CinderComparableObject(base.ComparableVersionedObject):
    def __eq__(self, obj):
        if hasattr(obj, 'obj_to_primitive'):
            return self.obj_to_primitive() == obj.obj_to_primitive()
        return False


class ObjectListBase(base.ObjectListBase):
    pass


class CinderObjectSerializer(base.VersionedObjectSerializer):
    OBJ_BASE_CLASS = CinderObject
