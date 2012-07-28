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
Scheduler base class that all Schedulers should inherit from
"""

from cinder import db
from cinder import flags
from cinder.openstack.common import log as logging
from cinder.openstack.common import cfg
from cinder.openstack.common import importutils
from cinder.openstack.common import rpc
from cinder.openstack.common import timeutils
from cinder import utils


LOG = logging.getLogger(__name__)

scheduler_driver_opts = [
    cfg.StrOpt('scheduler_host_manager',
               default='cinder.scheduler.host_manager.HostManager',
               help='The scheduler host manager class to use'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(scheduler_driver_opts)


def cast_to_volume_host(context, host, method, update_db=True, **kwargs):
    """Cast request to a volume host queue"""

    if update_db:
        volume_id = kwargs.get('volume_id', None)
        if volume_id is not None:
            now = timeutils.utcnow()
            db.volume_update(context, volume_id,
                    {'host': host, 'scheduled_at': now})
    rpc.cast(context,
             rpc.queue_get_for(context, FLAGS.volume_topic, host),
             {"method": method, "args": kwargs})
    LOG.debug(_("Casted '%(method)s' to host '%(host)s'") % locals())


def cast_to_host(context, topic, host, method, update_db=True, **kwargs):
    """Generic cast to host"""

    topic_mapping = {
            "volume": cast_to_volume_host}

    func = topic_mapping.get(topic)
    if func:
        func(context, host, method, update_db=update_db, **kwargs)
    else:
        rpc.cast(context,
                 rpc.queue_get_for(context, topic, host),
                 {"method": method, "args": kwargs})
        LOG.debug(_("Casted '%(method)s' to %(topic)s '%(host)s'")
                % locals())


class Scheduler(object):
    """The base class that all Scheduler classes should inherit from."""

    def __init__(self):
        self.host_manager = importutils.import_object(
                FLAGS.scheduler_host_manager)

    def get_host_list(self):
        """Get a list of hosts from the HostManager."""
        return self.host_manager.get_host_list()

    def get_service_capabilities(self):
        """Get the normalized set of capabilities for the services.
        """
        return self.host_manager.get_service_capabilities()

    def update_service_capabilities(self, service_name, host, capabilities):
        """Process a capability update from a service node."""
        self.host_manager.update_service_capabilities(service_name,
                host, capabilities)

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""

        services = db.service_get_all_by_topic(context, topic)
        return [service['host']
                for service in services
                if utils.service_is_up(service)]

    def schedule(self, context, topic, method, *_args, **_kwargs):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_("Must implement a fallback schedule"))
