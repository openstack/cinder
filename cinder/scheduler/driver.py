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

from cinder.i18n import _
from cinder import objects
from cinder.volume import rpcapi as volume_rpcapi


scheduler_driver_opts = [
    cfg.StrOpt('scheduler_host_manager',
               default='cinder.scheduler.host_manager.HostManager',
               help='The scheduler host manager class to use'),
    cfg.IntOpt('scheduler_max_attempts',
               default=3,
               help='Maximum number of attempts to schedule a volume'),
]

CONF = cfg.CONF
CONF.register_opts(scheduler_driver_opts)


def volume_update_db(context, volume_id, host, cluster_name):
    """Set the host, cluster_name, and set the scheduled_at field of a volume.

    :returns: A Volume with the updated fields set properly.
    """
    volume = objects.Volume.get_by_id(context, volume_id)
    volume.host = host
    volume.cluster_name = cluster_name
    volume.scheduled_at = timeutils.utcnow()
    volume.save()

    # A volume object is expected to be returned, as it is used by
    # filter_scheduler.
    return volume


def generic_group_update_db(context, group, host, cluster_name):
    """Set the host and the scheduled_at field of a group.

    :returns: A Group with the updated fields set properly.
    """
    group.update({'host': host, 'updated_at': timeutils.utcnow(),
                  'cluster_name': cluster_name})
    group.save()
    return group


class Scheduler(object):
    """The base class that all Scheduler classes should inherit from."""

    def __init__(self):
        self.host_manager = importutils.import_object(
            CONF.scheduler_host_manager)
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()

    def reset(self):
        """Reset volume RPC API object to load new version pins."""
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()

    def is_ready(self):
        """Returns True if Scheduler is ready to accept requests.

        This is to handle scheduler service startup when it has no volume hosts
        stats and will fail all the requests.
        """

        return self.host_manager.has_all_capabilities()

    def update_service_capabilities(self, service_name, host, capabilities,
                                    cluster_name, timestamp):
        """Process a capability update from a service node."""
        self.host_manager.update_service_capabilities(service_name,
                                                      host,
                                                      capabilities,
                                                      cluster_name,
                                                      timestamp)

    def notify_service_capabilities(self, service_name, backend,
                                    capabilities, timestamp):
        """Notify capability update from a service node."""
        self.host_manager.notify_service_capabilities(service_name,
                                                      backend,
                                                      capabilities,
                                                      timestamp)

    def host_passes_filters(self, context, backend, request_spec,
                            filter_properties):
        """Check if the specified backend passes the filters."""
        raise NotImplementedError(_("Must implement backend_passes_filters"))

    def find_retype_host(self, context, request_spec, filter_properties=None,
                         migration_policy='never'):
        """Find a backend that can accept the volume with its new type."""
        raise NotImplementedError(_("Must implement find_retype_backend"))

    # NOTE(geguileo): For backward compatibility with out of tree Schedulers
    # we don't change host_passes_filters or find_retype_host method names but
    # create an "alias" for them with the right name instead.
    backend_passes_filters = host_passes_filters
    find_retype_backend = find_retype_host

    def schedule(self, context, topic, method, *_args, **_kwargs):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_("Must implement a fallback schedule"))

    def schedule_create_volume(self, context, request_spec, filter_properties):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_("Must implement schedule_create_volume"))

    def schedule_create_group(self, context, group,
                              group_spec,
                              request_spec_list,
                              group_filter_properties,
                              filter_properties_list):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_(
            "Must implement schedule_create_group"))

    def get_pools(self, context, filters):
        """Must override schedule method for scheduler to work."""
        raise NotImplementedError(_(
            "Must implement schedule_get_pools"))
