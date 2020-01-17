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

from cinder.scheduler import filters
from cinder.service_auth import SERVICE_USER_GROUP
from cinder import utils as cinder_utils


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


class ShardFilter(filters.BaseBackendFilter):
    """Filters backends by shard of the project

    Every project has tags assigned, which define the vCenter the project is
    in. This filter filters out any backend that's not configured for the shard
    of a project.
    """

    # project shards do not change within a request
    run_filter_once_per_request = True

    _PROJECT_SHARD_CACHE = {}
    _PROJECT_SHARD_CACHE_RETENTION_TIME = 10 * 60
    _SHARD_PREFIX = 'vc-'
    _CAPABILITY_NAME = 'vcenter-shard'

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
                          if t.startswith(self._SHARD_PREFIX)]
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

    def backend_passes(self, backend_state, filter_properties):
        spec = filter_properties.get('request_spec', {})
        vol = spec.get('volume_properties', {})
        project_id = vol.get('project_id', None)

        volid = None
        if spec:
            volid = spec.get('volume_id')

        if project_id is None:
            LOG.debug('Could not determine the project for volume %(id)s.',
                      {'id': volid})
            return False

        shards = self._get_shards(project_id)
        if shards is None:
            LOG.error('Failure retrieving shards for project %(project_id)s.',
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

        if configured_shards_set & set(shards):
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
