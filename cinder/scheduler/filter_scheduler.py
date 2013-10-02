# Copyright (c) 2011 Intel Corporation
# Copyright (c) 2011 OpenStack Foundation
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

from oslo.config import cfg

from cinder import exception
from cinder.openstack.common import log as logging
from cinder.scheduler import driver
from cinder.scheduler import scheduler_options

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class FilterScheduler(driver.Scheduler):
    """Scheduler that can be used for filtering and weighing."""
    def __init__(self, *args, **kwargs):
        super(FilterScheduler, self).__init__(*args, **kwargs)
        self.cost_function_cache = None
        self.options = scheduler_options.SchedulerOptions()
        self.max_attempts = self._max_attempts()

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
        filter_properties['qos_specs'] = vol.get('qos_specs')

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
        self._post_select_populate_filter_properties(filter_properties,
                                                     weighed_host.obj)

        # context is not serializable
        filter_properties.pop('context', None)

        self.volume_rpcapi.create_volume(context, updated_volume, host,
                                         request_spec, filter_properties,
                                         allow_reschedule=True,
                                         snapshot_id=snapshot_id,
                                         image_id=image_id)

    def host_passes_filters(self, context, host, request_spec,
                            filter_properties):
        """Check if the specified host passes the filters."""
        weighed_hosts = self._get_weighted_candidates(context, request_spec,
                                                      filter_properties)
        for weighed_host in weighed_hosts:
            host_state = weighed_host.obj
            if host_state.host == host:
                return host_state

        msg = (_('cannot place volume %(id)s on %(host)s')
               % {'id': request_spec['volume_id'], 'host': host})
        raise exception.NoValidHost(reason=msg)

    def _post_select_populate_filter_properties(self, filter_properties,
                                                host_state):
        """Add additional information to the filter properties after a host has
        been selected by the scheduling process.
        """
        # Add a retry entry for the selected volume backend:
        self._add_retry_host(filter_properties, host_state.host)

    def _add_retry_host(self, filter_properties, host):
        """Add a retry entry for the selected volume backend. In the event that
        the request gets re-scheduled, this entry will signal that the given
        backend has already been tried.
        """
        retry = filter_properties.get('retry', None)
        if not retry:
            return
        hosts = retry['hosts']
        hosts.append(host)

    def _max_attempts(self):
        max_attempts = CONF.scheduler_max_attempts
        if max_attempts < 1:
            msg = _("Invalid value for 'scheduler_max_attempts', "
                    "must be >=1")
            raise exception.InvalidParameterValue(err=msg)
        return max_attempts

    def _log_volume_error(self, volume_id, retry):
        """If the request contained an exception from a previous volume
        create operation, log it to aid debugging
        """
        exc = retry.pop('exc', None)  # string-ified exception from volume
        if not exc:
            return  # no exception info from a previous attempt, skip

        hosts = retry.get('hosts', None)
        if not hosts:
            return  # no previously attempted hosts, skip

        last_host = hosts[-1]
        msg = _("Error scheduling %(volume_id)s from last vol-service: "
                "%(last_host)s : %(exc)s") % {
                    'volume_id': volume_id,
                    'last_host': last_host,
                    'exc': exc,
                }
        LOG.error(msg)

    def _populate_retry(self, filter_properties, properties):
        """Populate filter properties with history of retries for this
        request. If maximum retries is exceeded, raise NoValidHost.
        """
        max_attempts = self.max_attempts
        retry = filter_properties.pop('retry', {})

        if max_attempts == 1:
            # re-scheduling is disabled.
            return

        # retry is enabled, update attempt count:
        if retry:
            retry['num_attempts'] += 1
        else:
            retry = {
                'num_attempts': 1,
                'hosts': []  # list of volume service hosts tried
            }
        filter_properties['retry'] = retry

        volume_id = properties.get('volume_id')
        self._log_volume_error(volume_id, retry)

        if retry['num_attempts'] > max_attempts:
            msg = _("Exceeded max scheduling attempts %(max_attempts)d for "
                    "volume %(volume_id)s") % {
                        'max_attempts': max_attempts,
                        'volume_id': volume_id,
                    }
            raise exception.NoValidHost(reason=msg)

    def _get_weighted_candidates(self, context, request_spec,
                                 filter_properties=None):
        """Returns a list of hosts that meet the required specs,
        ordered by their fitness.
        """
        elevated = context.elevated()

        volume_properties = request_spec['volume_properties']
        # Since Cinder is using mixed filters from Oslo and it's own, which
        # takes 'resource_XX' and 'volume_XX' as input respectively, copying
        # 'volume_XX' to 'resource_XX' will make both filters happy.
        resource_properties = volume_properties.copy()
        volume_type = request_spec.get("volume_type", None)
        resource_type = request_spec.get("volume_type", None)
        request_spec.update({'resource_properties': resource_properties})

        config_options = self._get_configuration_options()

        if filter_properties is None:
            filter_properties = {}
        self._populate_retry(filter_properties, resource_properties)

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
            return []

        LOG.debug(_("Filtered %s") % hosts)
        # weighted_host = WeightedHost() ... the best
        # host for the job.
        weighed_hosts = self.host_manager.get_weighed_hosts(hosts,
                                                            filter_properties)
        return weighed_hosts

    def _schedule(self, context, request_spec, filter_properties=None):
        weighed_hosts = self._get_weighted_candidates(context, request_spec,
                                                      filter_properties)
        if not weighed_hosts:
            return None
        best_host = weighed_hosts[0]
        LOG.debug(_("Choosing %s") % best_host)
        volume_properties = request_spec['volume_properties']
        best_host.obj.consume_from_volume(volume_properties)
        return best_host
