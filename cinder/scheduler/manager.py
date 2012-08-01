# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 OpenStack, LLC.
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

"""
Scheduler Service
"""

import functools

from cinder import db
from cinder import flags
from cinder.openstack.common import log as logging
from cinder import manager
from cinder.openstack.common import cfg
from cinder.openstack.common import excutils
from cinder.openstack.common import importutils


LOG = logging.getLogger(__name__)

scheduler_driver_opt = cfg.StrOpt('scheduler_driver',
        default='cinder.scheduler.simple.SimpleScheduler',
        help='Default driver to use for the scheduler')

FLAGS = flags.FLAGS
FLAGS.register_opt(scheduler_driver_opt)


class SchedulerManager(manager.Manager):
    """Chooses a host to create volumes"""

    RPC_API_VERSION = '1.0'

    def __init__(self, scheduler_driver=None, *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = FLAGS.scheduler_driver
        self.driver = importutils.import_object(scheduler_driver)
        super(SchedulerManager, self).__init__(*args, **kwargs)

    def __getattr__(self, key):
        """Converts all method calls to use the schedule method"""
        # NOTE(russellb) Because of what this is doing, we must be careful
        # when changing the API of the scheduler drivers, as that changes
        # the rpc API as well, and the version should be updated accordingly.
        return functools.partial(self._schedule, key)

    def get_host_list(self, context):
        """Get a list of hosts from the HostManager."""
        return self.driver.get_host_list()

    def get_service_capabilities(self, context):
        """Get the normalized set of capabilities for this zone."""
        return self.driver.get_service_capabilities()

    def update_service_capabilities(self, context, service_name=None,
            host=None, capabilities=None, **kwargs):
        """Process a capability update from a service node."""
        if capabilities is None:
            capabilities = {}
        self.driver.update_service_capabilities(service_name, host,
                capabilities)

    def _schedule(self, method, context, topic, *args, **kwargs):
        """Tries to call schedule_* method on the driver to retrieve host.
        Falls back to schedule(context, topic) if method doesn't exist.
        """
        driver_method_name = 'schedule_%s' % method
        try:
            driver_method = getattr(self.driver, driver_method_name)
            args = (context,) + args
        except AttributeError, e:
            LOG.warning(_("Driver Method %(driver_method_name)s missing: "
                       "%(e)s. Reverting to schedule()") % locals())
            driver_method = self.driver.schedule
            args = (context, topic, method) + args

        try:
            return driver_method(*args, **kwargs)
        except Exception:
            with excutils.save_and_reraise_exception():
                volume_id = kwargs.get('volume_id')
                db.volume_update(context, volume_id, {'status': 'error'})
