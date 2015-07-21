# Copyright (c) 2010 OpenStack Foundation
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

from oslo_config import cfg
from oslo_utils import importutils
from oslo_utils import timeutils

from cinder import db
from cinder.i18n import _
from cinder.volume import rpcapi as volume_rpcapi


scheduler_driver_opts = [
    cfg.StrOpt('scheduler_host_manager',
               default='cinder.scheduler.host_manager.HostManager',
               help='The scheduler host manager class to use'),
    cfg.IntOpt('scheduler_max_attempts',
               default=3,
               help='Maximum number of attempts to schedule an volume'),
]

CONF = cfg.CONF
CONF.register_opts(scheduler_driver_opts)


def volume_update_db(context, volume_id, host):
    """Set the host and set the scheduled_at field of a volume.

    :returns: A Volume with the updated fields set properly.
    """
    values = {'host': host, 'scheduled_at': timeutils.utcnow()}
    return db.volume_update(context, volume_id, values)


def group_update_db(context, group, host):
    """Set the host and the scheduled_at field of a consistencygroup.

    :returns: A Consistencygroup with the updated fields set properly.
    """
    group.update({'host': host, 'updated_at': timeutils.utcnow()})
    group.save()
    return group


class Scheduler(object):
    """The base class that all Scheduler classes should inherit from."""

    def __init__(self):
        self.host_manager = importutils.import_object(
            CONF.scheduler_host_manager)
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()

    def is_ready(self):
        """Returns True if Scheduler is ready to accept requests.

        This is to handle scheduler service startup when it has no volume hosts
        stats and will fail all the requests.
        """

        return self.host_manager.has_all_capabilities()

    def update_service_capabilities(self, service_name, host, capabilities):
        """Process a capability update from a service node."""
        self.host_manager.update_service_capabilities(service_name,
                                                      host,
                                                      capabilities)

    def host_passes_filters(self, context, volume_id, host, filter_properties):
        """Check if the specified host passes the filters."""
        raise NotImplementedError(_("Must implement host_passes_filters"))

    def find_retype_host(self, context, request_spec, filter_properties=None,
                         migration_policy='never'):
        """Find a host that can accept the volume with its new type."""
        raise NotImplementedError(_("Must implement find_retype_host"))

    def schedule(self, context, topic, method, *_args, **_kwargs):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_("Must implement a fallback schedule"))

    def schedule_create_volume(self, context, request_spec, filter_properties):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_("Must implement schedule_create_volume"))

    def schedule_create_consistencygroup(self, context, group,
                                         request_spec_list,
                                         filter_properties_list):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_(
            "Must implement schedule_create_consistencygroup"))

    def get_pools(self, context, filters):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_(
            "Must implement schedule_get_pools"))
