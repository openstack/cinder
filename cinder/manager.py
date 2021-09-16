# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Base Manager class.

Managers are responsible for a certain aspect of the system.  It is a logical
grouping of code relating to a portion of the system.  In general other
components should be using the manager to make changes to the components that
it is responsible for.

For example, other components that need to deal with volumes in some way,
should do so by calling methods on the VolumeManager instead of directly
changing fields in the database.  This allows us to keep all of the code
relating to volumes in the same place.

We have adopted a basic strategy of Smart managers and dumb data, which means
rather than attaching methods to data objects, components should call manager
methods that act on the data.

Methods on managers that can be executed locally should be called directly. If
a particular method must execute on a remote host, this should be done via rpc
to the service that wraps the manager

Managers should be responsible for most of the db access, and
non-implementation specific data.  Anything implementation specific that can't
be generalized should be done by the Driver.

In general, we prefer to have one manager with multiple drivers for different
implementations, but sometimes it makes sense to have multiple managers.  You
can think of it this way: Abstract different overall strategies at the manager
level(FlatNetwork vs VlanNetwork), and different implementations at the driver
level(LinuxNetDriver vs CiscoNetDriver).

Managers will often provide methods for initial setup of a host or periodic
tasks to a wrapping service.

This module provides Manager, a base class for managers.

"""

from eventlet import greenpool
from eventlet import tpool
from oslo_config import cfg
import oslo_config.types
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import periodic_task
from oslo_utils import timeutils

from cinder import context
from cinder import db
from cinder.db import base
from cinder import exception
from cinder import objects
from cinder import rpc
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class PeriodicTasks(periodic_task.PeriodicTasks):
    def __init__(self):
        super(PeriodicTasks, self).__init__(CONF)


class Manager(base.Base, PeriodicTasks):
    # Set RPC API version to 1.0 by default.
    RPC_API_VERSION = '1.0'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(
        self,
        host: oslo_config.types.HostAddress = None,
        cluster=None,
        **_kwargs,
    ):
        if not host:
            host = CONF.host
        self.host: oslo_config.types.HostAddress = host
        self.cluster = cluster
        self.additional_endpoints: list = []
        self.availability_zone = CONF.storage_availability_zone
        super().__init__()

    def _set_tpool_size(self, nthreads: int) -> None:
        # NOTE(geguileo): Until PR #472 is merged we have to be very careful
        # not to call "tpool.execute" before calling this method.
        tpool.set_num_threads(nthreads)

    @property
    def service_topic_queue(self):
        return self.cluster or self.host

    def init_host(self, service_id, added_to_cluster=None):
        """Handle initialization if this is a standalone service.

        A hook point for services to execute tasks before the services are made
        available (i.e. showing up on RPC and starting to accept RPC calls) to
        other components.  Child classes should override this method.

        :param service_id: ID of the service where the manager is running.
        :param added_to_cluster: True when a host's cluster configuration has
                                 changed from not being defined or being '' to
                                 any other value and the DB service record
                                 reflects this new value.
        """
        pass

    def init_host_with_rpc(self):
        """A hook for service to do jobs after RPC is ready.

        Like init_host(), this method is a hook where services get a chance
        to execute tasks that *need* RPC. Child classes should override
        this method.

        """
        pass

    def is_working(self):
        """Method indicating if service is working correctly.

        This method is supposed to be overridden by subclasses and return if
        manager is working correctly.
        """
        return True

    def reset(self):
        """Method executed when SIGHUP is caught by the process.

        We're utilizing it to reset RPC API version pins to avoid restart of
        the service when rolling upgrade is completed.
        """
        LOG.info('Resetting cached RPC version pins.')
        rpc.LAST_OBJ_VERSIONS = {}
        rpc.LAST_RPC_VERSIONS = {}

    def set_log_levels(self, context, log_request):
        utils.set_log_levels(log_request.prefix, log_request.level)

    def get_log_levels(self, context, log_request):
        levels = utils.get_log_levels(log_request.prefix)
        log_levels = [objects.LogLevel(context, prefix=prefix, level=level)
                      for prefix, level in levels.items()]
        return objects.LogLevelList(context, objects=log_levels)


class ThreadPoolManager(Manager):
    def __init__(self, *args, **kwargs):
        self._tp = greenpool.GreenPool()
        super(ThreadPoolManager, self).__init__(*args, **kwargs)

    def _add_to_threadpool(self, func, *args, **kwargs):
        self._tp.spawn_n(func, *args, **kwargs)


class SchedulerDependentManager(ThreadPoolManager):
    """Periodically send capability updates to the Scheduler services.

    Services that need to update the Scheduler of their capabilities
    should derive from this class. Otherwise they can derive from
    manager.Manager directly. Updates are only sent after
    update_service_capabilities is called with non-None values.

    """

    def __init__(
        self,
        host=None,
        service_name='undefined',
        cluster=None,
        *args,
        **kwargs,
    ):
        self.last_capabilities = None
        self.service_name = service_name
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        super().__init__(host, cluster=cluster, *args, **kwargs)

    def update_service_capabilities(self, capabilities):
        """Remember these capabilities to send on next periodic update."""
        self.last_capabilities = capabilities

    def _publish_service_capabilities(self, context):
        """Pass data back to the scheduler at a periodic interval."""
        if self.last_capabilities:
            LOG.debug('Notifying Schedulers of capabilities ...')
            self.scheduler_rpcapi.update_service_capabilities(
                context,
                self.service_name,
                self.host,
                self.last_capabilities,
                self.cluster)
            try:
                self.scheduler_rpcapi.notify_service_capabilities(
                    context,
                    self.service_name,
                    self.service_topic_queue,
                    self.last_capabilities)
            except exception.ServiceTooOld as e:
                # This means we have Newton's c-sch in the deployment, so
                # rpcapi cannot send the message. We can safely ignore the
                # error. Log it because it shouldn't happen after upgrade.
                msg = ("Failed to notify about cinder-volume service "
                       "capabilities for host %(host)s. This is normal "
                       "during a live upgrade. Error: %(e)s")
                LOG.warning(msg, {'host': self.host, 'e': e})

    def reset(self):
        super(SchedulerDependentManager, self).reset()
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()


class CleanableManager(object):
    def do_cleanup(self,
                   context: context.RequestContext,
                   cleanup_request: objects.CleanupRequest) -> None:
        LOG.info('Initiating service %s cleanup',
                 cleanup_request.service_id)

        # If the 'until' field in the cleanup request is not set, we default to
        # this very moment.
        until = cleanup_request.until or timeutils.utcnow()
        keep_entry: bool = False

        to_clean = db.worker_get_all(
            context,
            resource_type=cleanup_request.resource_type,
            resource_id=cleanup_request.resource_id,
            service_id=cleanup_request.service_id,
            until=until)

        for clean in to_clean:
            original_service_id = clean.service_id
            original_time = clean.updated_at
            # Try to do a soft delete to mark the entry as being cleaned up
            # by us (setting service id to our service id).
            res = db.worker_claim_for_cleanup(context,
                                              claimer_id=self.service_id,
                                              orm_worker=clean)

            # Claim may fail if entry is being cleaned by another service, has
            # been removed (finished cleaning) by another service or the user
            # started a new cleanable operation.
            # In any of these cases we don't have to do cleanup or remove the
            # worker entry.
            if not res:
                continue

            # Try to get versioned object for resource we have to cleanup
            try:
                vo_cls = getattr(objects, clean.resource_type)
                vo = vo_cls.get_by_id(context, clean.resource_id)
                # Set the worker DB entry in the VO and mark it as being a
                # clean operation
                clean.cleaning = True
                vo.worker = clean
            except exception.NotFound:
                LOG.debug('Skipping cleanup for non existent %(type)s %(id)s.',
                          {'type': clean.resource_type,
                           'id': clean.resource_id})
            else:
                # Resource status should match
                if vo.status != clean.status:
                    LOG.debug('Skipping cleanup for mismatching work on '
                              '%(type)s %(id)s: %(exp_sts)s <> %(found_sts)s.',
                              {'type': clean.resource_type,
                               'id': clean.resource_id,
                               'exp_sts': clean.status,
                               'found_sts': vo.status})
                else:
                    LOG.info('Cleaning %(type)s with id %(id)s and status '
                             '%(status)s',
                             {'type': clean.resource_type,
                              'id': clean.resource_id,
                              'status': clean.status},
                             resource=vo)
                    try:
                        # Some cleanup jobs are performed asynchronously, so
                        # we don't delete the worker entry, they'll take care
                        # of it
                        keep_entry = self._do_cleanup(context, vo)
                    except Exception:
                        LOG.exception('Could not perform cleanup.')
                        # Return the worker DB entry to the original service
                        db.worker_update(context, clean.id,
                                         service_id=original_service_id,
                                         updated_at=original_time)
                        continue

            # The resource either didn't exist or was properly cleaned, either
            # way we can remove the entry from the worker table if the cleanup
            # method doesn't want to keep the entry (for example for delayed
            # deletion).
            if not keep_entry and not db.worker_destroy(context, id=clean.id):
                LOG.warning('Could not remove worker entry %s.', clean.id)

        LOG.info('Service %s cleanup completed.', cleanup_request.service_id)

    def _do_cleanup(self, ctxt: context.RequestContext, vo_resource) -> bool:
        return False

    def init_host(self, service_id, added_to_cluster=None, **kwargs):
        ctxt = context.get_admin_context()
        self.service_id = service_id
        # TODO(geguileo): Once we don't support MySQL 5.5 anymore we can remove
        # call to workers_init.
        db.workers_init()
        cleanup_request = objects.CleanupRequest(service_id=service_id)
        self.do_cleanup(ctxt, cleanup_request)
