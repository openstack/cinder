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
import functools
import traceback

from oslo_log import log as logging
from oslo_versionedobjects import base
from oslo_versionedobjects import fields
import six

from cinder import exception
from cinder import objects


LOG = logging.getLogger('object')
remotable = base.remotable
remotable_classmethod = base.remotable_classmethod
obj_make_list = base.obj_make_list


class CinderObjectRegistry(base.VersionedObjectRegistry):
    def registration_hook(self, cls, index):
        setattr(objects, cls.obj_name(), cls)


@CinderObjectRegistry.register
class CinderObject(base.VersionedObject):
    # NOTE(thangp): OBJ_PROJECT_NAMESPACE needs to be set so that nova,
    # cinder, and other objects can exist on the same bus and be distinguished
    # from one another.
    OBJ_PROJECT_NAMESPACE = 'cinder'


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
            return getattr(self, key)


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


class ObjectListBase(base.ObjectListBase):
    pass


class CinderObjectSerializer(base.VersionedObjectSerializer):
    OBJ_BASE_CLASS = CinderObject


def serialize_args(fn):
    """Decorator that will do the arguments serialization before remoting."""
    def wrapper(obj, *args, **kwargs):
        for kw in kwargs:
            value_arg = kwargs.get(kw)
            if kw == 'exc_val' and value_arg:
                kwargs[kw] = str(value_arg)
            elif kw == 'exc_tb' and (
                    not isinstance(value_arg, six.string_types) and value_arg):
                kwargs[kw] = ''.join(traceback.format_tb(value_arg))
            elif isinstance(value_arg, datetime.datetime):
                kwargs[kw] = value_arg.isoformat()
        if hasattr(fn, '__call__'):
            return fn(obj, *args, **kwargs)
        # NOTE(danms): We wrap a descriptor, so use that protocol
        return fn.__get__(None, obj)(*args, **kwargs)

    # NOTE(danms): Make this discoverable
    wrapper.remotable = getattr(fn, 'remotable', False)
    wrapper.original_fn = fn
    return (functools.wraps(fn)(wrapper) if hasattr(fn, '__call__')
            else classmethod(wrapper))
