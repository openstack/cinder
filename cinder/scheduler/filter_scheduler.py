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

from oslo_config import cfg
from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LW
from cinder.scheduler import driver
from cinder.scheduler import scheduler_options
from cinder.volume import utils

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

    def schedule_create_consistencygroup(self, context, group_id,
                                         request_spec_list,
                                         filter_properties_list):

        weighed_host = self._schedule_group(
            context,
            request_spec_list,
            filter_properties_list)

        if not weighed_host:
            raise exception.NoValidHost(reason="No weighed hosts available")

        host = weighed_host.obj.host

        updated_group = driver.group_update_db(context, group_id, host)

        self.volume_rpcapi.create_consistencygroup(context,
                                                   updated_group, host)

    def schedule_create_volume(self, context, request_spec, filter_properties):
        weighed_host = self._schedule(context, request_spec,
                                      filter_properties)

        if not weighed_host:
            raise exception.NoValidHost(reason="No weighed hosts available")

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

        msg = (_('Cannot place volume %(id)s on %(host)s')
               % {'id': request_spec['volume_id'], 'host': host})
        raise exception.NoValidHost(reason=msg)

    def find_retype_host(self, context, request_spec, filter_properties=None,
                         migration_policy='never'):
        """Find a host that can accept the volume with its new type."""
        filter_properties = filter_properties or {}
        current_host = request_spec['volume_properties']['host']

        # The volume already exists on this host, and so we shouldn't check if
        # it can accept the volume again in the CapacityFilter.
        filter_properties['vol_exists_on'] = current_host

        weighed_hosts = self._get_weighted_candidates(context, request_spec,
                                                      filter_properties)
        if not weighed_hosts:
            msg = (_('No valid hosts for volume %(id)s with type %(type)s')
                   % {'id': request_spec['volume_id'],
                      'type': request_spec['volume_type']})
            raise exception.NoValidHost(reason=msg)

        for weighed_host in weighed_hosts:
            host_state = weighed_host.obj
            if host_state.host == current_host:
                return host_state

        if utils.extract_host(current_host, 'pool') is None:
            # legacy volumes created before pool is introduced has no pool
            # info in host.  But host_state.host always include pool level
            # info. In this case if above exact match didn't work out, we
            # find host_state that are of the same host of volume being
            # retyped. In other words, for legacy volumes, retyping could
            # cause migration between pools on same host, which we consider
            # it is different from migration between hosts thus allow that
            # to happen even migration policy is 'never'.
            for weighed_host in weighed_hosts:
                host_state = weighed_host.obj
                backend = utils.extract_host(host_state.host, 'backend')
                if backend == current_host:
                    return host_state

        if migration_policy == 'never':
            msg = (_('Current host not valid for volume %(id)s with type '
                     '%(type)s, migration not allowed')
                   % {'id': request_spec['volume_id'],
                      'type': request_spec['volume_type']})
            raise exception.NoValidHost(reason=msg)

        top_host = self._choose_top_host(weighed_hosts, request_spec)
        return top_host.obj

    def get_pools(self, context, filters):
        # TODO(zhiteng) Add filters support
        return self.host_manager.get_pools(context)

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

        # If multiattach is enabled on a volume, we need to add
        # multiattach to extra specs, so that the capability
        # filtering is enabled.
        multiattach = volume_properties.get('multiattach', False)
        if multiattach and 'multiattach' not in resource_type.get(
                'extra_specs', {}):
            if 'extra_specs' not in resource_type:
                resource_type['extra_specs'] = {}

            resource_type['extra_specs'].update(
                multiattach='<is> True')

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

        LOG.debug("Filtered %s" % hosts)
        # weighted_host = WeightedHost() ... the best
        # host for the job.
        weighed_hosts = self.host_manager.get_weighed_hosts(hosts,
                                                            filter_properties)
        return weighed_hosts

    def _get_weighted_candidates_group(self, context, request_spec_list,
                                       filter_properties_list=None):
        """Finds hosts that supports the consistencygroup.

        Returns a list of hosts that meet the required specs,
        ordered by their fitness.
        """
        elevated = context.elevated()

        weighed_hosts = []
        index = 0
        for request_spec in request_spec_list:
            volume_properties = request_spec['volume_properties']
            # Since Cinder is using mixed filters from Oslo and it's own, which
            # takes 'resource_XX' and 'volume_XX' as input respectively,
            # copying 'volume_XX' to 'resource_XX' will make both filters
            # happy.
            resource_properties = volume_properties.copy()
            volume_type = request_spec.get("volume_type", None)
            resource_type = request_spec.get("volume_type", None)
            request_spec.update({'resource_properties': resource_properties})

            config_options = self._get_configuration_options()

            filter_properties = {}
            if filter_properties_list:
                filter_properties = filter_properties_list[index]
                if filter_properties is None:
                    filter_properties = {}
            self._populate_retry(filter_properties, resource_properties)

            # Add consistencygroup_support in extra_specs if it is not there.
            # Make sure it is populated in filter_properties
            if 'consistencygroup_support' not in resource_type.get(
                    'extra_specs', {}):
                resource_type['extra_specs'].update(
                    consistencygroup_support='<is> True')

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
            all_hosts = self.host_manager.get_all_host_states(elevated)
            if not all_hosts:
                return []

            # Filter local hosts based on requirements ...
            hosts = self.host_manager.get_filtered_hosts(all_hosts,
                                                         filter_properties)

            if not hosts:
                return []

            LOG.debug("Filtered %s" % hosts)

            # weighted_host = WeightedHost() ... the best
            # host for the job.
            temp_weighed_hosts = self.host_manager.get_weighed_hosts(
                hosts,
                filter_properties)
            if not temp_weighed_hosts:
                return []
            if index == 0:
                weighed_hosts = temp_weighed_hosts
            else:
                new_weighed_hosts = []
                for host1 in weighed_hosts:
                    for host2 in temp_weighed_hosts:
                        if host1.obj.host == host2.obj.host:
                            new_weighed_hosts.append(host1)
                weighed_hosts = new_weighed_hosts
                if not weighed_hosts:
                    return []

            index += 1

        return weighed_hosts

    def _schedule(self, context, request_spec, filter_properties=None):
        weighed_hosts = self._get_weighted_candidates(context, request_spec,
                                                      filter_properties)
        if not weighed_hosts:
            LOG.warning(_LW('No weighed hosts found for volume '
                            'with properties: %s'),
                        filter_properties['request_spec']['volume_type'])
            return None
        return self._choose_top_host(weighed_hosts, request_spec)

    def _schedule_group(self, context, request_spec_list,
                        filter_properties_list=None):
        weighed_hosts = self._get_weighted_candidates_group(
            context,
            request_spec_list,
            filter_properties_list)
        if not weighed_hosts:
            return None
        return self._choose_top_host_group(weighed_hosts, request_spec_list)

    def _choose_top_host(self, weighed_hosts, request_spec):
        top_host = weighed_hosts[0]
        host_state = top_host.obj
        LOG.debug("Choosing %s" % host_state.host)
        volume_properties = request_spec['volume_properties']
        host_state.consume_from_volume(volume_properties)
        return top_host

    def _choose_top_host_group(self, weighed_hosts, request_spec_list):
        top_host = weighed_hosts[0]
        host_state = top_host.obj
        LOG.debug("Choosing %s" % host_state.host)
        return top_host
