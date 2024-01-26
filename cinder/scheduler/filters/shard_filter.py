# Copyright (c) 2020 SAP SE
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
import time

from keystoneauth1 import exceptions as kse
from keystoneauth1 import loading as ks_loading
from oslo_config import cfg
from oslo_log import log as logging

from cinder import db
from cinder.scheduler import filters
from cinder.service_auth import SERVICE_USER_GROUP
from cinder import utils as cinder_utils
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)
CONF = cfg.CONF

_SERVICE_AUTH = None
KEYSTONE_GROUP = 'keystone'


# register keystone config options so we can create an adapter for it easily
ks_loading.register_session_conf_options(CONF, KEYSTONE_GROUP)
ks_loading.register_auth_conf_options(CONF, KEYSTONE_GROUP)
keystone_opts = ks_loading.get_adapter_conf_options()
cfg.set_defaults(keystone_opts,
                 valid_interfaces=['internal', 'public'],
                 service_type='identity')
CONF.register_opts(keystone_opts, group=KEYSTONE_GROUP)

CSI_CLUSTER_METADATA_KEY = 'cinder.csi.openstack.org/cluster'


class ShardFilter(filters.BaseBackendFilter):
    """Filters backends by shard of the project

    Every project has tags assigned, which define the vCenter the project is
    in. This filter filters out any backend that's not configured for the shard
    of a project.

    Alternatively the project may have the "sharding_enabled" tag set, which
    enables the project for backends in all shards.
    """

    # project shards do not change within a request
    run_filter_once_per_request = True

    _PROJECT_SHARD_CACHE = {}
    _PROJECT_SHARD_CACHE_RETENTION_TIME = 10 * 60
    _SHARD_PREFIX = 'vc-'
    _CAPABILITY_NAME = 'vcenter-shard'
    _ALL_SHARDS = "sharding_enabled"

    def _get_keystone_adapter(self):
        """Return a keystone adapter

        This needs [service_user] for the auth.
        """
        global _SERVICE_AUTH

        if _SERVICE_AUTH is None:
            _SERVICE_AUTH = ks_loading.load_auth_from_conf_options(
                CONF, group=SERVICE_USER_GROUP)
            if _SERVICE_AUTH is None:
                # This indicates a misconfiguration so log a warning and
                # return the user_auth.
                LOG.error('Unable to load auth from %(group)s '
                          'configuration. Ensure "auth_type" is set.',
                          {'group': SERVICE_USER_GROUP})
                return

        ksa_session = ks_loading.load_session_from_conf_options(
            CONF,
            KEYSTONE_GROUP,
            auth=_SERVICE_AUTH)

        return ks_loading.load_adapter_from_conf_options(
            CONF, KEYSTONE_GROUP, session=ksa_session, auth=_SERVICE_AUTH,
            min_version=(3, 0), max_version=(3, 'latest'))

    def _update_cache(self):
        """Update the cache with infos from keystone

        Ask keystone for the list of projects to save the interesting tags
        of each project in the cache.
        """
        adap = self._get_keystone_adapter()
        if not adap:
            return

        # NOTE: the same code exists in nova
        url = '/projects'
        while url:
            try:
                resp = adap.get(url, raise_exc=False)
            except kse.EndpointNotFound:
                LOG.error(
                    "Keystone identity service version 3.0 was not found. "
                    "This might be because your endpoint points to the v2.0 "
                    "versioned endpoint which is not supported. Please fix "
                    "this.")
                return
            except kse.ClientException:
                LOG.error("Unable to contact keystone to update project tags "
                          "cache")
                return

            resp.raise_for_status()

            data = resp.json()
            for project in data['projects']:
                project_id = project['id']
                shards = [t for t in project['tags']
                          if t.startswith(self._SHARD_PREFIX)
                          or t == self._ALL_SHARDS]
                self._PROJECT_SHARD_CACHE[project_id] = shards

            url = data['links']['next']

        self._PROJECT_SHARD_CACHE['last_modified'] = time.time()

    @cinder_utils.synchronized('update-shard-cache')
    def _get_shards(self, project_id):
        # expire the cache 10min after last write
        last_modified = self._PROJECT_SHARD_CACHE.get('last_modified', 0)
        time_diff = time.time() - last_modified
        if time_diff > self._PROJECT_SHARD_CACHE_RETENTION_TIME:
            self._PROJECT_SHARD_CACHE = {}

        if project_id not in self._PROJECT_SHARD_CACHE:
            self._update_cache()

        return self._PROJECT_SHARD_CACHE.get(project_id)

    def _extract_shard_from_host(self, host):
        """Extract the shard from the host."""

        # get the string starting with the shard from the host
        # vc-d-X@backend#pool
        shard_plus = host[host.find(self._SHARD_PREFIX):]
        # Now get only the shard. This is the string until the next @
        return shard_plus[:shard_plus.find('@')]

    def _is_vmware(self, backend_state):
        if backend_state.vendor_name != 'VMware':
            return False
        return True

    def filter_all(self, filter_obj_list, filter_properties):
        backends = self._filter_by_k8s_cluster(filter_obj_list,
                                               filter_properties)

        return [b for b in backends if
                self._backend_passes(b, filter_properties)]

    def _filter_by_k8s_cluster(self, backends, filter_properties):
        spec = filter_properties.get('request_spec', {})
        vol_props = spec.get('volume_properties', {})
        project_id = vol_props.get('project_id', None)
        metadata = vol_props.get('metadata', {})

        is_vmware = any(self._is_vmware(b) for b in backends)
        if (not metadata or not project_id
                or spec.get('snapshot_id')
                or spec.get('operation') == 'find_backend_for_connector'
                or not is_vmware):
            return backends

        cluster_name = metadata.get(CSI_CLUSTER_METADATA_KEY)
        if not cluster_name:
            return backends

        availability_zone = filter_properties.get('availability_zone')
        query_filters = None
        if availability_zone:
            query_filters = {'availability_zone': availability_zone}

        results = db.get_hosts_by_volume_metadata(
            key=CSI_CLUSTER_METADATA_KEY,
            value=cluster_name,
            filters=query_filters)

        if not results:
            return backends

        k8s_hosts = dict(results)

        def _is_k8s_host(b):
            host = volume_utils.extract_host(b.host, 'host')
            if host in k8s_hosts:
                return True
            else:
                LOG.debug('%(backend)s not in the allowed '
                          'K8S hosts %(k8s_hosts)s.',
                          {'backend': b,
                           'k8s_hosts': k8s_hosts})
                return False

        return [
            b for b in backends if
            (not self._is_vmware(b) or _is_k8s_host(b))
        ]

    def _backend_passes(self, backend_state, filter_properties):
        # We only need the shard filter for vmware based pools
        if not self._is_vmware(backend_state):
            LOG.info(
                "Shard Filter ignoring backend %s as it's not "
                "vmware based driver", backend_state.backend_id)
            return True

        spec = filter_properties.get('request_spec', {})
        vol = spec.get('volume_properties', {})
        project_id = vol.get('project_id', None)

        volid = None
        if spec:
            volid = spec.get('volume_id')

        if spec.get('snapshot_id'):
            # Snapshots always use the same host as the volume.
            LOG.debug('Ignoring snapshot.')
            return True

        if spec.get('operation') == 'find_backend_for_connector':
            # We don't care about shards here, as we want to move a volume to
            # an instance sitting in a specific vCenter. Shards are only used
            # if we don't know where the volume is needed.
            LOG.debug('Ignoring find_backend_for_connector scheduling.')
            return True

        if spec.get('operation') == 'retype_volume':
            # The backend can only be on the same shard as
            # the volume is currently on.
            vol_shard = self._extract_shard_from_host(vol['host'])
            backend_shard = self._extract_shard_from_host(backend_state.host)
            if vol_shard == backend_shard:
                return True
            else:
                return False

        # allow an override of the automatic shard-detection like nova does for
        # its compute-hosts
        scheduler_hints = filter_properties.get('scheduler_hints') or {}
        if self._CAPABILITY_NAME in scheduler_hints:
            shards = set([scheduler_hints[self._CAPABILITY_NAME]])
            LOG.debug('Using overridden shards %(shards)s for scheduling.',
                      {'shards': shards})
        else:
            if project_id is None:
                LOG.debug('Could not determine the project for volume %(id)s.',
                          {'id': volid})
                return False

            shards = self._get_shards(project_id)
            if shards is None:
                LOG.error('Failure retrieving shards for project '
                          '%(project_id)s.',
                          {'project_id': project_id})
                return False

        if not len(shards):
            LOG.error('Project %(project_id)s is not assigned to any shard.',
                      {'project_id': project_id})
            return False

        # set extra_capabilities in the cinder-volume.conf, so we can filter on
        # them here.
        configured_shards_set = set()
        cap = backend_state.capabilities.get(self._CAPABILITY_NAME)
        if cap is not None:
            configured_shards_set.update(cap.split(','))

        if not configured_shards_set:
            LOG.error('%(backend)s does not have any capability starting with '
                      '%(shard_prefix)s.',
                      {'backend': backend_state,
                       'shard_prefix': self._SHARD_PREFIX})
            return False

        if self._ALL_SHARDS in shards:
            LOG.debug('project enabled for all shards %(project_shards)s.',
                      {'project_shards': shards})
            return True
        elif configured_shards_set & set(shards):
            LOG.debug('%(backend)s shard %(backend_shards)s found in project '
                      'shards %(project_shards)s.',
                      {'backend': backend_state,
                       'backend_shards': configured_shards_set,
                       'project_shards': shards})
            return True
        else:
            LOG.debug('%(backend)s shard %(backend_shards)s not found in '
                      'project shards %(project_shards)s.',
                      {'backend': backend_state,
                       'backend_shards': configured_shards_set,
                       'project_shards': shards})
            return False
