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


from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import periodic_task

from cinder.db import base
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import version

from eventlet import greenpool


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class PeriodicTasks(periodic_task.PeriodicTasks):
    def __init__(self):
        super(PeriodicTasks, self).__init__(CONF)


class Manager(base.Base, PeriodicTasks):
    # Set RPC API version to 1.0 by default.
    RPC_API_VERSION = '1.0'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, host=None, db_driver=None):
        if not host:
            host = CONF.host
        self.host = host
        self.additional_endpoints = []
        super(Manager, self).__init__(db_driver)

    def periodic_tasks(self, context, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        return self.run_periodic_tasks(context, raise_on_error=raise_on_error)

    def init_host(self):
        """Handle initialization if this is a standalone service.

        A hook point for services to execute tasks before the services are made
        available (i.e. showing up on RPC and starting to accept RPC calls) to
        other components.  Child classes should override this method.

        """
        pass

    def init_host_with_rpc(self):
        """A hook for service to do jobs after RPC is ready.

        Like init_host(), this method is a hook where services get a chance
        to execute tasks that *need* RPC. Child classes should override
        this method.

        """
        pass

    def service_version(self):
        return version.version_string()

    def service_config(self):
        config = {}
        for key in CONF:
            config[key] = CONF.get(key, None)
        return config

    def is_working(self):
        """Method indicating if service is working correctly.

        This method is supposed to be overriden by subclasses and return if
        manager is working correctly.
        """
        return True


class SchedulerDependentManager(Manager):
    """Periodically send capability updates to the Scheduler services.

    Services that need to update the Scheduler of their capabilities
    should derive from this class. Otherwise they can derive from
    manager.Manager directly. Updates are only sent after
    update_service_capabilities is called with non-None values.

    """

    def __init__(self, host=None, db_driver=None, service_name='undefined'):
        self.last_capabilities = None
        self.service_name = service_name
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        self._tp = greenpool.GreenPool()
        super(SchedulerDependentManager, self).__init__(host, db_driver)

    def update_service_capabilities(self, capabilities):
        """Remember these capabilities to send on next periodic update."""
        self.last_capabilities = capabilities

    @periodic_task.periodic_task
    def _publish_service_capabilities(self, context):
        """Pass data back to the scheduler at a periodic interval."""
        if self.last_capabilities:
            LOG.debug('Notifying Schedulers of capabilities ...')
            self.scheduler_rpcapi.update_service_capabilities(
                context,
                self.service_name,
                self.host,
                self.last_capabilities)

    def _add_to_threadpool(self, func, *args, **kwargs):
        self._tp.spawn_n(func, *args, **kwargs)
