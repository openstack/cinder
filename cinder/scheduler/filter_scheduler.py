# Copyright (c) 2011 Intel Corporation
# Copyright (c) 2011 OpenStack, LLC.
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
The FilterScheduler is for creating volumes.
You can customize this scheduler by specifying your own volume Filters and
Weighing Functions.
"""

import operator

from cinder import exception
from cinder import flags
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.scheduler import driver
from cinder.scheduler import scheduler_options


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class FilterScheduler(driver.Scheduler):
    """Scheduler that can be used for filtering and weighing."""
    def __init__(self, *args, **kwargs):
        super(FilterScheduler, self).__init__(*args, **kwargs)
        self.cost_function_cache = None
        self.options = scheduler_options.SchedulerOptions()

    def schedule(self, context, topic, method, *args, **kwargs):
        """The schedule() contract requires we return the one
        best-suited host for this request.
        """
        self._schedule(context, topic, *args, **kwargs)

    def _get_configuration_options(self):
        """Fetch options dictionary. Broken out for testing."""
        return self.options.get_configuration()

    def populate_filter_properties(self, request_spec, filter_properties):
        """Stuff things into filter_properties.  Can be overridden in a
        subclass to add more data.
        """
        vol = request_spec['volume_properties']
        filter_properties['size'] = vol['size']
        filter_properties['availability_zone'] = vol.get('availability_zone')
        filter_properties['user_id'] = vol.get('user_id')
        filter_properties['metadata'] = vol.get('metadata')

    def schedule_create_volume(self, context, request_spec, filter_properties):
        weighed_host = self._schedule(context, request_spec,
                                      filter_properties)

        if not weighed_host:
            raise exception.NoValidHost(reason="")

        host = weighed_host.obj.host
        volume_id = request_spec['volume_id']
        snapshot_id = request_spec['snapshot_id']
        image_id = request_spec['image_id']

        updated_volume = driver.volume_update_db(context, volume_id, host)
        self.volume_rpcapi.create_volume(context, updated_volume, host,
                                         snapshot_id, image_id)

    def _schedule(self, context, request_spec, filter_properties=None):
        """Returns a list of hosts that meet the required specs,
        ordered by their fitness.
        """
        elevated = context.elevated()

        volume_properties = request_spec['volume_properties']
        # Since Nova is using mixed filters from Oslo and it's own, which
        # takes 'resource_XX' and 'instance_XX' as input respectively, copying
        # 'instance_XX' to 'resource_XX' will make both filters happy.
        resource_properties = volume_properties.copy()
        volume_type = request_spec.get("volume_type", None)
        resource_type = request_spec.get("volume_type", None)
        request_spec.update({'resource_properties': resource_properties})

        config_options = self._get_configuration_options()

        if filter_properties is None:
            filter_properties = {}
        filter_properties.update({'context': context,
                                  'request_spec': request_spec,
                                  'config_options': config_options,
                                  'volume_type': volume_type,
                                  'resource_type': resource_type})

        self.populate_filter_properties(request_spec,
                                        filter_properties)

        # Find our local list of acceptable hosts by filtering and
        # weighing our options. we virtually consume resources on
        # it so subsequent selections can adjust accordingly.

        # Note: remember, we are using an iterator here. So only
        # traverse this list once.
        hosts = self.host_manager.get_all_host_states(elevated)

        # Filter local hosts based on requirements ...
        hosts = self.host_manager.get_filtered_hosts(hosts,
                                                     filter_properties)
        if not hosts:
            return None

        LOG.debug(_("Filtered %(hosts)s") % locals())
        # weighted_host = WeightedHost() ... the best
        # host for the job.
        weighed_hosts = self.host_manager.get_weighed_hosts(hosts,
                                                            filter_properties)
        best_host = weighed_hosts[0]
        LOG.debug(_("Choosing %(best_host)s") % locals())
        best_host.obj.consume_from_volume(volume_properties)
        return best_host
