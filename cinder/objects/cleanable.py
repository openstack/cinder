# Copyright (c) 2016 Red Hat, Inc.
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

import collections
import inspect

import decorator
from oslo_utils import versionutils

from cinder import db
from cinder import exception
from cinder.objects import base
from cinder import service
from cinder.volume import rpcapi as vol_rpcapi


class CinderCleanableObject(base.CinderPersistentObject):
    """Base class for cleanable OVO resources.

    All cleanable objects must have a host property/attribute.
    """
    worker = None

    cleanable_resource_types = set()

    @classmethod
    def get_rpc_api(cls):
        # By default assume all resources are handled by c-vol services
        return vol_rpcapi.VolumeAPI

    @classmethod
    def cinder_ovo_cls_init(cls):
        """Called on OVO registration, sets set of cleanable resources."""
        # First call persistent object method to store the DB model
        super(CinderCleanableObject, cls).cinder_ovo_cls_init()

        # Add this class to the set of resources
        cls.cleanable_resource_types.add(cls.obj_name())

    @classmethod
    def get_pinned_version(cls):
        # We pin the version by the last service that gets updated, which is
        # c-vol or c-bak
        min_obj_vers_str = cls.get_rpc_api().determine_obj_version_cap()

        # Get current pinned down version for this object
        version = base.OBJ_VERSIONS[min_obj_vers_str][cls.__name__]
        return versionutils.convert_version_to_int(version)

    @staticmethod
    def _is_cleanable(status, obj_version):
        """Check if a specific status for a specific OBJ version is cleanable.

        Each CinderCleanableObject class should implement this method and
        return True for cleanable status for versions equal or higher to the
        ones where the functionality was added.

        :returns: Whether to create a workers DB entry or not
        :param obj_version: Min object version running in the cloud or None if
                            current version.
        :type obj_version: float
        """
        return False

    def is_cleanable(self, pinned=False):
        """Check if cleanable VO status is cleanable.

        :param pinned: If we should check against pinned version or current
                       version.
        :type pinned: bool
        :returns: Whether this needs a workers DB entry or not
        """
        if pinned:
            obj_version = self.get_pinned_version()
        else:
            obj_version = None
        return self._is_cleanable(self.status, obj_version)

    def create_worker(self, pinned=True):
        """Create a worker entry at the API."""
        # This method is mostly called from the rpc layer, therefore it checks
        # if it's cleanable given current pinned version.
        if not self.is_cleanable(pinned):
            return False

        resource_type = self.__class__.__name__

        entry_in_db = False

        # This will only loop on very rare race conditions
        while not entry_in_db:
            try:
                # On the common case there won't be an entry in the DB, that's
                # why we try to create first.
                db.worker_create(self._context, status=self.status,
                                 resource_type=resource_type,
                                 resource_id=self.id)
                entry_in_db = True
            except exception.WorkerExists:
                try:
                    db.worker_update(self._context, None,
                                     filters={'resource_type': resource_type,
                                              'resource_id': self.id},
                                     service_id=None,
                                     status=self.status)
                    entry_in_db = True
                except exception.WorkerNotFound:
                    pass
        return entry_in_db

    def set_worker(self):
        worker = self.worker

        service_id = service.Service.service_id
        resource_type = self.__class__.__name__

        if worker:
            if worker.cleaning:
                return
        else:
            try:
                worker = db.worker_get(self._context,
                                       resource_type=resource_type,
                                       resource_id=self.id)
            except exception.WorkerNotFound:
                # If the call didn't come from an RPC call we still have to
                # create the entry in the DB.
                try:
                    self.worker = db.worker_create(self._context,
                                                   status=self.status,
                                                   resource_type=resource_type,
                                                   resource_id=self.id,
                                                   service_id=service_id)
                    return
                except exception.WorkerExists:
                    # If 2 cleanable operations are competing for this resource
                    # and the other one created the entry first that one won
                    raise exception.CleanableInUse(type=resource_type,
                                                   id=self.id)

        # If we have to claim this work or if the status has changed we have
        # to update DB.
        if (worker.service_id != service_id or worker.status != self.status):
            try:
                db.worker_update(
                    self._context, worker.id,
                    filters={'service_id': worker.service_id,
                             'status': worker.status,
                             'race_preventer': worker.race_preventer,
                             'updated_at': worker.updated_at},
                    service_id=service_id,
                    status=self.status,
                    orm_worker=worker)
            except exception.WorkerNotFound:
                self.worker = None
                raise exception.CleanableInUse(type=self.__class__.__name__,
                                               id=self.id)
        self.worker = worker

    def unset_worker(self):
        if self.worker:
            db.worker_destroy(self._context, id=self.worker.id,
                              status=self.worker.status,
                              service_id=self.worker.service_id)
            self.worker = None

    # NOTE(geguileo): To be compatible with decorate v3.4.x and v4.0.x
    decorate = staticmethod(getattr(decorator, 'decorate',
                            lambda f, w: decorator.decorator(w, f)))

    @staticmethod
    def set_workers(*decorator_args):
        """Decorator that adds worker DB rows for cleanable versioned  objects.

        By default will take care of all cleanable objects, but we can limit
        which objects we want by passing the name of the arguments we want
        to be added.
        """
        def _decorator(f):
            def wrapper(f, *args, **kwargs):
                if decorator_args:
                    call_args = inspect.getcallargs(f, *args, **kwargs)
                    candidates = [call_args[obj] for obj in decorator_args]
                else:
                    candidates = list(args)
                    candidates.extend(kwargs.values())
                cleanables = [cand for cand in candidates
                              if (isinstance(cand, CinderCleanableObject)
                                  and cand.is_cleanable(pinned=False))]
                try:
                    # Create the entries in the workers table
                    for cleanable in cleanables:
                        cleanable.set_worker()

                    # Call the function
                    result = f(*args, **kwargs)
                finally:
                    # Remove entries from the workers table
                    for cleanable in cleanables:
                        # NOTE(geguileo): We check that the status has changed
                        # to avoid removing the worker entry when we finished
                        # the operation due to an unexpected exception and also
                        # when this process stops because the main process has
                        # stopped.
                        if (cleanable.worker and
                                cleanable.status != cleanable.worker.status):
                            try:
                                cleanable.unset_worker()
                            except Exception:
                                pass
                return result
            return CinderCleanableObject.decorate(f, wrapper)

        # If we don't have optional decorator arguments the argument in
        # decorator_args is the function we have to decorate
        if len(decorator_args) == 1 and isinstance(
                decorator_args[0], collections.Callable):
            function = decorator_args[0]
            decorator_args = None
            return _decorator(function)
        return _decorator

    def refresh(self):
        # We want to keep the worker entry on refresh
        worker = self.worker
        super(CinderCleanableObject, self).refresh()
        self.worker = worker
