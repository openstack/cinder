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

"""The FilterScheduler is for creating volumes.

You can customize this scheduler by specifying your own volume Filters and
Weighing Functions.
"""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from cinder import exception
from cinder.i18n import _
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
        """Schedule contract that returns best-suited host for this request."""
        self._schedule(context, topic, *args, **kwargs)

    def _get_configuration_options(self):
        """Fetch options dictionary. Broken out for testing."""
        return self.options.get_configuration()

    def populate_filter_properties(self, request_spec, filter_properties):
        """Stuff things into filter_properties.

        Can be overridden in a subclass to add more data.
        """
        vol = request_spec['volume_properties']
        filter_properties['size'] = vol['size']
        filter_properties['availability_zone'] = vol.get('availability_zone')
        filter_properties['user_id'] = vol.get('user_id')
        filter_properties['metadata'] = vol.get('metadata')
        filter_properties['qos_specs'] = vol.get('qos_specs')

    def schedule_create_group(self, context, group,
                              group_spec,
                              request_spec_list,
                              group_filter_properties,
                              filter_properties_list):
        weighed_backend = self._schedule_generic_group(
            context,
            group_spec,
            request_spec_list,
            group_filter_properties,
            filter_properties_list)

        if not weighed_backend:
            raise exception.NoValidBackend(reason=_("No weighed backends "
                                                    "available"))

        backend = weighed_backend.obj

        updated_group = driver.generic_group_update_db(context, group,
                                                       backend.host,
                                                       backend.cluster_name)

        self.volume_rpcapi.create_group(context, updated_group)

    def schedule_create_volume(self, context, request_spec, filter_properties):
        backend = self._schedule(context, request_spec, filter_properties)

        if not backend:
            raise exception.NoValidBackend(reason=_("No weighed backends "
                                                    "available"))

        backend = backend.obj
        volume_id = request_spec['volume_id']

        updated_volume = driver.volume_update_db(
            context, volume_id,
            backend.host,
            backend.cluster_name,
            availability_zone=backend.service['availability_zone'])
        self._post_select_populate_filter_properties(filter_properties,
                                                     backend)

        # context is not serializable
        filter_properties.pop('context', None)

        self.volume_rpcapi.create_volume(context, updated_volume, request_spec,
                                         filter_properties,
                                         allow_reschedule=True)

    def backend_passes_filters(self, context, backend, request_spec,
                               filter_properties):
        """Check if the specified backend passes the filters."""
        weighed_backends = self._get_weighted_candidates(context, request_spec,
                                                         filter_properties)
        # If backend has no pool defined we will ignore it in the comparison
        ignore_pool = not bool(utils.extract_host(backend, 'pool'))
        for weighed_backend in weighed_backends:
            backend_id = weighed_backend.obj.backend_id
            if ignore_pool:
                backend_id = utils.extract_host(backend_id)
            if backend_id == backend:
                return weighed_backend.obj

        reason_param = {'resource': 'volume',
                        'id': '??id missing??',
                        'backend': backend}
        for resource in ['volume', 'group', 'snapshot']:
            resource_id = request_spec.get('%s_id' % resource, None)
            if resource_id:
                reason_param.update({'resource': resource, 'id': resource_id})
                break
        raise exception.NoValidBackend(_('Cannot place %(resource)s %(id)s '
                                         'on %(backend)s.') % reason_param)

    def find_retype_backend(self, context, request_spec,
                            filter_properties=None, migration_policy='never'):
        """Find a backend that can accept the volume with its new type."""
        filter_properties = filter_properties or {}
        backend = (request_spec['volume_properties'].get('cluster_name')
                   or request_spec['volume_properties']['host'])

        # The volume already exists on this backend, and so we shouldn't check
        # if it can accept the volume again in the CapacityFilter.
        filter_properties['vol_exists_on'] = backend

        weighed_backends = self._get_weighted_candidates(context, request_spec,
                                                         filter_properties)
        if not weighed_backends:
            raise exception.NoValidBackend(
                reason=_('No valid backends for volume %(id)s with type '
                         '%(type)s') % {'id': request_spec['volume_id'],
                                        'type': request_spec['volume_type']})

        for weighed_backend in weighed_backends:
            backend_state = weighed_backend.obj
            if backend_state.backend_id == backend:
                return backend_state

        if utils.extract_host(backend, 'pool') is None:
            # legacy volumes created before pool is introduced has no pool
            # info in host.  But host_state.host always include pool level
            # info. In this case if above exact match didn't work out, we
            # find host_state that are of the same host of volume being
            # retyped. In other words, for legacy volumes, retyping could
            # cause migration between pools on same host, which we consider
            # it is different from migration between hosts thus allow that
            # to happen even migration policy is 'never'.
            for weighed_backend in weighed_backends:
                backend_state = weighed_backend.obj
                new_backend = utils.extract_host(backend_state.backend_id,
                                                 'backend')
                if new_backend == backend:
                    return backend_state

        if migration_policy == 'never':
            raise exception.NoValidBackend(
                reason=_('Current backend not valid for volume %(id)s with '
                         'type %(type)s, migration not allowed') %
                {'id': request_spec['volume_id'],
                 'type': request_spec['volume_type']})

        top_backend = self._choose_top_backend(weighed_backends, request_spec)
        return top_backend.obj

    def get_pools(self, context, filters):
        return self.host_manager.get_pools(context, filters)

    def _post_select_populate_filter_properties(self, filter_properties,
                                                backend_state):
        """Populate filter properties with additional information.

        Add additional information to the filter properties after a backend has
        been selected by the scheduling process.
        """
        # Add a retry entry for the selected volume backend:
        self._add_retry_backend(filter_properties, backend_state.backend_id)

    def _add_retry_backend(self, filter_properties, backend):
        """Add a retry entry for the selected volume backend.

        In the event that the request gets re-scheduled, this entry will signal
        that the given backend has already been tried.
        """
        retry = filter_properties.get('retry', None)
        if not retry:
            return
        # TODO(geguileo): In P - change to only use backends
        for key in ('hosts', 'backends'):
            backends = retry.get(key)
            if backends is not None:
                backends.append(backend)

    def _max_attempts(self):
        max_attempts = CONF.scheduler_max_attempts
        if max_attempts < 1:
            raise exception.InvalidParameterValue(
                err=_("Invalid value for 'scheduler_max_attempts', "
                      "must be >=1"))
        return max_attempts

    def _log_volume_error(self, volume_id, retry):
        """Log requests with exceptions from previous volume operations."""
        exc = retry.pop('exc', None)  # string-ified exception from volume
        if not exc:
            return  # no exception info from a previous attempt, skip

        # TODO(geguileo): In P - change to hosts = retry.get('backends')
        backends = retry.get('backends', retry.get('hosts'))
        if not backends:
            return  # no previously attempted hosts, skip

        last_backend = backends[-1]
        LOG.error("Error scheduling %(volume_id)s from last vol-service: "
                  "%(last_backend)s : %(exc)s",
                  {'volume_id': volume_id,
                   'last_backend': last_backend,
                   'exc': exc})

    def _populate_retry(self, filter_properties, request_spec):
        """Populate filter properties with history of retries for request.

        If maximum retries is exceeded, raise NoValidBackend.
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
                'backends': [],  # list of volume service backends tried
                'hosts': []  # TODO(geguileo): Remove in P and leave backends
            }
        filter_properties['retry'] = retry

        resource_id = request_spec.get(
            'volume_id') or request_spec.get("group_id")
        self._log_volume_error(resource_id, retry)

        if retry['num_attempts'] > max_attempts:
            raise exception.NoValidBackend(
                reason=_("Exceeded max scheduling attempts %(max_attempts)d "
                         "for resource %(resource_id)s") %
                {'max_attempts': max_attempts,
                 'resource_id': resource_id})

    def _get_weighted_candidates(self, context, request_spec,
                                 filter_properties=None):
        """Return a list of backends that meet required specs.

        Returned list is ordered by their fitness.
        """
        elevated = context.elevated()

        # Since Cinder is using mixed filters from Oslo and it's own, which
        # takes 'resource_XX' and 'volume_XX' as input respectively, copying
        # 'volume_XX' to 'resource_XX' will make both filters happy.
        volume_type = request_spec.get("volume_type")
        resource_type = volume_type if volume_type is not None else {}

        config_options = self._get_configuration_options()

        if filter_properties is None:
            filter_properties = {}
        self._populate_retry(filter_properties,
                             request_spec)

        request_spec_dict = jsonutils.to_primitive(request_spec)

        filter_properties.update({'context': context,
                                  'request_spec': request_spec_dict,
                                  'config_options': config_options,
                                  'volume_type': volume_type,
                                  'resource_type': resource_type})

        self.populate_filter_properties(request_spec,
                                        filter_properties)

        # If multiattach is enabled on a volume, we need to add
        # multiattach to extra specs, so that the capability
        # filtering is enabled.
        multiattach = request_spec['volume_properties'].get('multiattach',
                                                            False)
        if multiattach and 'multiattach' not in resource_type.get(
                'extra_specs', {}):
            if 'extra_specs' not in resource_type:
                resource_type['extra_specs'] = {}

            resource_type['extra_specs'].update(
                multiattach='<is> True')

        # Revert volume consumed capacity if it's a rescheduled request
        retry = filter_properties.get('retry', {})
        if retry.get('backends', []):
            self.host_manager.revert_volume_consumed_capacity(
                retry['backends'][-1],
                request_spec['volume_properties']['size'])
        # Find our local list of acceptable backends by filtering and
        # weighing our options. we virtually consume resources on
        # it so subsequent selections can adjust accordingly.

        # Note: remember, we are using an iterator here. So only
        # traverse this list once.
        backends = self.host_manager.get_all_backend_states(elevated)

        # Filter local hosts based on requirements ...
        backends = self.host_manager.get_filtered_backends(backends,
                                                           filter_properties)
        if not backends:
            return []

        LOG.debug("Filtered %s", backends)
        # weighted_backends = WeightedHost() ... the best
        # backend for the job.
        weighed_backends = self.host_manager.get_weighed_backends(
            backends, filter_properties)
        return weighed_backends

    def _get_weighted_candidates_generic_group(
            self, context, group_spec, request_spec_list,
            group_filter_properties=None,
            filter_properties_list=None):
        """Finds backends that supports the group.

        Returns a list of backends that meet the required specs,
        ordered by their fitness.
        """
        elevated = context.elevated()

        backends_by_group_type = self._get_weighted_candidates_by_group_type(
            context, group_spec, group_filter_properties)

        weighed_backends = []
        backends_by_vol_type = []
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
            self._populate_retry(filter_properties, request_spec)

            # Add group_support in extra_specs if it is not there.
            # Make sure it is populated in filter_properties
            # if 'group_support' not in resource_type.get(
            #         'extra_specs', {}):
            #     resource_type['extra_specs'].update(
            #         group_support='<is> True')

            filter_properties.update({'context': context,
                                      'request_spec': request_spec,
                                      'config_options': config_options,
                                      'volume_type': volume_type,
                                      'resource_type': resource_type})

            self.populate_filter_properties(request_spec,
                                            filter_properties)

            # Find our local list of acceptable backends by filtering and
            # weighing our options. we virtually consume resources on
            # it so subsequent selections can adjust accordingly.

            # Note: remember, we are using an iterator here. So only
            # traverse this list once.
            all_backends = self.host_manager.get_all_backend_states(elevated)
            if not all_backends:
                return []

            # Filter local backends based on requirements ...
            backends = self.host_manager.get_filtered_backends(
                all_backends, filter_properties)

            if not backends:
                return []

            LOG.debug("Filtered %s", backends)

            # weighted_backend = WeightedHost() ... the best
            # backend for the job.
            temp_weighed_backends = self.host_manager.get_weighed_backends(
                backends,
                filter_properties)
            if not temp_weighed_backends:
                return []
            if index == 0:
                backends_by_vol_type = temp_weighed_backends
            else:
                backends_by_vol_type = self._find_valid_backends(
                    backends_by_vol_type, temp_weighed_backends)
                if not backends_by_vol_type:
                    return []

            index += 1

        # Find backends selected by both the group type and volume types.
        weighed_backends = self._find_valid_backends(backends_by_vol_type,
                                                     backends_by_group_type)

        return weighed_backends

    def _find_valid_backends(self, backend_list1, backend_list2):
        new_backends = []
        for backend1 in backend_list1:
            for backend2 in backend_list2:
                # Should schedule creation of group on backend level,
                # not pool level.
                if (utils.extract_host(backend1.obj.backend_id) ==
                        utils.extract_host(backend2.obj.backend_id)):
                    new_backends.append(backend1)
        if not new_backends:
            return []
        return new_backends

    def _get_weighted_candidates_by_group_type(
            self, context, group_spec,
            group_filter_properties=None):
        """Finds backends that supports the group type.

        Returns a list of backends that meet the required specs,
        ordered by their fitness.
        """
        elevated = context.elevated()

        weighed_backends = []
        volume_properties = group_spec['volume_properties']
        # Since Cinder is using mixed filters from Oslo and it's own, which
        # takes 'resource_XX' and 'volume_XX' as input respectively,
        # copying 'volume_XX' to 'resource_XX' will make both filters
        # happy.
        resource_properties = volume_properties.copy()
        group_type = group_spec.get("group_type", None)
        resource_type = group_spec.get("group_type", None)
        group_spec.update({'resource_properties': resource_properties})

        config_options = self._get_configuration_options()

        if group_filter_properties is None:
            group_filter_properties = {}
        self._populate_retry(group_filter_properties, resource_properties)

        group_filter_properties.update({'context': context,
                                        'request_spec': group_spec,
                                        'config_options': config_options,
                                        'group_type': group_type,
                                        'resource_type': resource_type})

        self.populate_filter_properties(group_spec,
                                        group_filter_properties)

        # Find our local list of acceptable backends by filtering and
        # weighing our options. we virtually consume resources on
        # it so subsequent selections can adjust accordingly.

        # Note: remember, we are using an iterator here. So only
        # traverse this list once.
        all_backends = self.host_manager.get_all_backend_states(elevated)
        if not all_backends:
            return []

        # Filter local backends based on requirements ...
        backends = self.host_manager.get_filtered_backends(
            all_backends, group_filter_properties)

        if not backends:
            return []

        LOG.debug("Filtered %s", backends)

        # weighted_backends = WeightedHost() ... the best backend for the job.
        weighed_backends = self.host_manager.get_weighed_backends(
            backends,
            group_filter_properties)
        if not weighed_backends:
            return []

        return weighed_backends

    def _schedule(self, context, request_spec, filter_properties=None):
        weighed_backends = self._get_weighted_candidates(context, request_spec,
                                                         filter_properties)
        # When we get the weighed_backends, we clear those backends that don't
        # match the resource's backend (it could be assigend from group,
        # snapshot or volume).
        resource_backend = request_spec.get('resource_backend')
        if weighed_backends and resource_backend:
            resource_backend_has_pool = bool(utils.extract_host(
                resource_backend, 'pool'))
            # Get host name including host@backend#pool info from
            # weighed_backends.
            for backend in weighed_backends[::-1]:
                backend_id = (
                    backend.obj.backend_id if resource_backend_has_pool
                    else utils.extract_host(backend.obj.backend_id)
                )
                if backend_id != resource_backend:
                    weighed_backends.remove(backend)
        if not weighed_backends:
            LOG.warning('No weighed backend found for volume '
                        'with properties: %s',
                        filter_properties['request_spec'].get('volume_type'))
            return None
        return self._choose_top_backend(weighed_backends, request_spec)

    def _schedule_generic_group(self, context, group_spec, request_spec_list,
                                group_filter_properties=None,
                                filter_properties_list=None):
        weighed_backends = self._get_weighted_candidates_generic_group(
            context,
            group_spec,
            request_spec_list,
            group_filter_properties,
            filter_properties_list)
        if not weighed_backends:
            return None
        return self._choose_top_backend_generic_group(weighed_backends)

    def _choose_top_backend(self, weighed_backends, request_spec):
        top_backend = weighed_backends[0]
        backend_state = top_backend.obj
        LOG.debug("Choosing %s", backend_state.backend_id)
        volume_properties = request_spec['volume_properties']
        backend_state.consume_from_volume(volume_properties)
        return top_backend

    def _choose_top_backend_generic_group(self, weighed_backends):
        top_backend = weighed_backends[0]
        backend_state = top_backend.obj
        LOG.debug("Choosing %s", backend_state.backend_id)
        return top_backend
