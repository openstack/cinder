# Copyright 2013-2015 Blockbridge Networks, LLC.
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
Blockbridge EPS iSCSI Volume Driver
"""

import base64
import socket

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import units
import six
from six.moves import http_client
from six.moves import urllib

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.volume import driver
from cinder.volume import utils as volume_utils

LOG = logging.getLogger(__name__)

blockbridge_opts = [
    cfg.StrOpt("blockbridge_api_host",
               help=_("IP address/hostname of Blockbridge API.")),
    cfg.IntOpt("blockbridge_api_port",
               help=_("Override HTTPS port to connect to Blockbridge "
                      "API server.")),
    cfg.StrOpt("blockbridge_auth_scheme",
               default='token',
               choices=['token', 'password'],
               help=_("Blockbridge API authentication scheme (token "
                      "or password)")),
    cfg.StrOpt("blockbridge_auth_token",
               help=_("Blockbridge API token (for auth scheme 'token')"),
               secret=True),
    cfg.StrOpt("blockbridge_auth_user",
               help=_("Blockbridge API user (for auth scheme 'password')")),
    cfg.StrOpt("blockbridge_auth_password",
               help=_("Blockbridge API password (for auth scheme 'password')"),
               secret=True),
    cfg.DictOpt("blockbridge_pools",
                default={'OpenStack': '+openstack'},
                help=_("Defines the set of exposed pools and their associated "
                       "backend query strings")),
    cfg.StrOpt("blockbridge_default_pool",
               help=_("Default pool name if unspecified.")),
]

CONF = cfg.CONF
CONF.register_opts(blockbridge_opts)


class BlockbridgeAPIClient(object):
    _api_cfg = None

    def __init__(self, configuration=None):
        self.configuration = configuration

    def _get_api_cfg(self):
        if self._api_cfg:
            # return cached configuration
            return self._api_cfg

        if self.configuration.blockbridge_auth_scheme == 'password':
            user = self.configuration.safe_get('blockbridge_auth_user')
            pw = self.configuration.safe_get('blockbridge_auth_password')
            creds = "%s:%s" % (user, pw)
            if six.PY3:
                creds = creds.encode('utf-8')
                b64_creds = base64.encodestring(creds).decode('ascii')
            else:
                b64_creds = base64.encodestring(creds)
            authz = "Basic %s" % b64_creds.replace("\n", "")
        elif self.configuration.blockbridge_auth_scheme == 'token':
            token = self.configuration.blockbridge_auth_token or ''
            authz = "Bearer %s" % token

        # set and return cached api cfg
        self._api_cfg = {
            'host': self.configuration.blockbridge_api_host,
            'port': self.configuration.blockbridge_api_port,
            'base_url': '/api/cinder',
            'default_headers': {
                'User-Agent': ("cinder-volume/%s" %
                               BlockbridgeISCSIDriver.VERSION),
                'Accept': 'application/vnd.blockbridge-3+json',
                'Authorization': authz,
            },
        }

        return self._api_cfg

    def submit(self, rel_url, method='GET', params=None, user_id=None,
               project_id=None, req_id=None, action=None, **kwargs):
        """Submit a request to the configured API endpoint."""

        cfg = self._get_api_cfg()
        if cfg is None:
            msg = _("Failed to determine blockbridge API configuration")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # alter the url appropriately if an action is requested
        if action:
            rel_url += "/actions/%s" % action

        headers = cfg['default_headers'].copy()
        url = cfg['base_url'] + rel_url
        body = None

        # include user, project and req-id, if supplied
        tsk_ctx = []
        if user_id and project_id:
            tsk_ctx.append("ext_auth=keystone/%s/%s" % (project_id, user_id))
        if req_id:
            tsk_ctx.append("id=%s", req_id)

        if tsk_ctx:
            headers['X-Blockbridge-Task'] = ','.join(tsk_ctx)

        # encode params based on request method
        if method in ['GET', 'DELETE']:
            # For GET method add parameters to the URL
            if params:
                url += '?' + urllib.parse.urlencode(params)
        elif method in ['POST', 'PUT', 'PATCH']:
            body = jsonutils.dumps(params)
            headers['Content-Type'] = 'application/json'
        else:
            raise exception.UnknownCmd(cmd=method)

        # connect and execute the request
        connection = http_client.HTTPSConnection(cfg['host'], cfg['port'])
        connection.request(method, url, body, headers)
        response = connection.getresponse()

        # read response data
        rsp_body = response.read()
        rsp_data = jsonutils.loads(rsp_body)

        connection.close()

        code = response.status
        if code in [200, 201, 202, 204]:
            pass
        elif code == 401:
            raise exception.NotAuthorized(_("Invalid credentials"))
        elif code == 403:
            raise exception.NotAuthorized(_("Insufficient privileges"))
        else:
            raise exception.VolumeBackendAPIException(data=rsp_data['message'])

        return rsp_data


class BlockbridgeISCSIDriver(driver.ISCSIDriver):
    """Manages volumes hosted on Blockbridge EPS."""

    VERSION = '1.3.0'

    def __init__(self, *args, **kwargs):
        super(BlockbridgeISCSIDriver, self).__init__(*args, **kwargs)

        self.client = kwargs.get('client', None) or (
            BlockbridgeAPIClient(configuration=self.configuration))

        self.configuration.append_config_values(blockbridge_opts)
        self.hostname = socket.gethostname()

    def do_setup(self, context):
        """Set up the Blockbridge volume driver."""
        pass

    def check_for_setup_error(self):
        """Verify configuration is valid."""

        # ensure the host is configured
        if self.configuration.safe_get('blockbridge_api_host') is None:
            raise exception.InvalidInput(
                reason=_("Blockbridge api host not configured"))

        # ensure the auth scheme is valid and has the necessary configuration.
        auth_scheme = self.configuration.safe_get("blockbridge_auth_scheme")

        if auth_scheme == 'password':
            auth_user = self.configuration.safe_get('blockbridge_auth_user')
            auth_pw = self.configuration.safe_get('blockbridge_auth_password')
            if auth_user is None:
                raise exception.InvalidInput(
                    reason=_("Blockbridge user not configured (required for "
                             "auth scheme 'password')"))
            if auth_pw is None:
                raise exception.InvalidInput(
                    reason=_("Blockbridge password not configured (required "
                             "for auth scheme 'password')"))
        elif auth_scheme == 'token':
            token = self.configuration.safe_get('blockbridge_auth_token')
            if token is None:
                raise exception.InvalidInput(
                    reason=_("Blockbridge token not configured (required "
                             "for auth scheme 'token')"))
        else:
            raise exception.InvalidInput(
                reason=(_("Blockbridge configured with invalid auth scheme "
                          "'%(auth_scheme)s'") % {'auth_scheme': auth_scheme}))

        # ensure at least one pool is defined
        pools = self.configuration.safe_get('blockbridge_pools')
        if pools is None:
            raise exception.InvalidInput(
                reason=_("Blockbridge pools not configured"))

        default_pool = self.configuration.safe_get('blockbridge_default_pool')
        if default_pool and default_pool not in pools:
            raise exception.InvalidInput(
                reason=_("Blockbridge default pool does not exist"))

    def _vol_api_submit(self, vol_id, **kwargs):
        vol_id = urllib.parse.quote(vol_id, '')
        rel_url = "/volumes/%s" % vol_id

        return self.client.submit(rel_url, **kwargs)

    def _create_volume(self, vol_id, params, **kwargs):
        """Execute a backend volume create operation."""

        self._vol_api_submit(vol_id, method='PUT', params=params, **kwargs)

    def _delete_volume(self, vol_id, **kwargs):
        """Execute a backend volume delete operation."""

        self._vol_api_submit(vol_id, method='DELETE', **kwargs)

    def _extend_volume(self, vol_id, capacity, **kwargs):
        """Execute a backend volume grow operation."""

        params = kwargs.get('params', {})
        params['capacity'] = capacity

        self._vol_api_submit(vol_id, method='POST', action='grow',
                             params=params, **kwargs)

    def _snap_api_submit(self, vol_id, snap_id, **kwargs):
        vol_id = urllib.parse.quote(vol_id, '')
        snap_id = urllib.parse.quote(snap_id, '')
        rel_url = "/volumes/%s/snapshots/%s" % (vol_id, snap_id)

        return self.client.submit(rel_url, **kwargs)

    def _create_snapshot(self, vol_id, snap_id, params, **kwargs):
        """Execute a backend snapshot create operation."""

        self._snap_api_submit(vol_id, snap_id, method='PUT',
                              params=params, **kwargs)

    def _delete_snapshot(self, vol_id, snap_id, **kwargs):
        """Execute a backend snapshot delete operation."""

        return self._snap_api_submit(vol_id, snap_id, method='DELETE',
                                     **kwargs)

    def _export_api_submit(self, vol_id, ini_name, **kwargs):
        vol_id = urllib.parse.quote(vol_id, '')
        ini_name = urllib.parse.quote(ini_name, '')
        rel_url = "/volumes/%s/exports/%s" % (vol_id, ini_name)

        return self.client.submit(rel_url, **kwargs)

    def _create_export(self, vol_id, ini_name, params, **kwargs):
        """Execute a backend volume export operation."""

        return self._export_api_submit(vol_id, ini_name, method='PUT',
                                       params=params, **kwargs)

    def _delete_export(self, vol_id, ini_name, **kwargs):
        """Remove a previously created volume export."""

        self._export_api_submit(vol_id, ini_name, method='DELETE',
                                **kwargs)

    def _get_pool_stats(self, pool, query, **kwargs):
        """Retrieve pool statistics and capabilities."""

        pq = {
            'pool': pool,
            'query': query,
        }
        pq.update(kwargs)

        return self.client.submit('/status', params=pq)

    def _get_dbref_name(self, ref):
        display_name = ref.get('display_name')
        if not display_name:
            return ref.get('name')
        return display_name

    def _get_query_string(self, ctxt, volume):
        pools = self.configuration.blockbridge_pools
        default_pool = self.configuration.blockbridge_default_pool
        explicit_pool = volume_utils.extract_host(volume['host'], 'pool')

        pool_name = explicit_pool or default_pool
        if pool_name:
            return pools[pool_name]
        else:
            # no pool specified or defaulted -- just pick whatever comes out of
            # the dictionary first.
            return list(pools.values())[0]

    def create_volume(self, volume):
        """Create a volume on a Blockbridge EPS backend.

        :param volume: volume reference
        """

        ctxt = context.get_admin_context()
        create_params = {
            'name': self._get_dbref_name(volume),
            'query': self._get_query_string(ctxt, volume),
            'capacity': int(volume['size'] * units.Gi),
        }

        LOG.debug("Provisioning %(capacity)s byte volume "
                  "with query '%(query)s'", create_params, resource=volume)

        return self._create_volume(volume['id'],
                                   create_params,
                                   user_id=volume['user_id'],
                                   project_id=volume['project_id'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""

        create_params = {
            'name': self._get_dbref_name(volume),
            'src': {
                'volume_id': src_vref['id'],
            },
        }

        LOG.debug("Cloning source volume %(id)s", src_vref, resource=volume)

        return self._create_volume(volume['id'],
                                   create_params,
                                   user_id=volume['user_id'],
                                   project_id=volume['project_id'])

    def delete_volume(self, volume):
        """Remove an existing volume.

        :param volume: volume reference
        """

        LOG.debug("Removing volume %(id)s", volume, resource=volume)

        return self._delete_volume(volume['id'],
                                   user_id=volume['user_id'],
                                   project_id=volume['project_id'])

    def create_snapshot(self, snapshot):
        """Create snapshot of existing volume.

        :param snapshot: shapshot reference
        """

        create_params = {
            'name': self._get_dbref_name(snapshot),
        }

        LOG.debug("Creating snapshot of volume %(volume_id)s", snapshot,
                  resource=snapshot)

        return self._create_snapshot(snapshot['volume_id'],
                                     snapshot['id'],
                                     create_params,
                                     user_id=snapshot['user_id'],
                                     project_id=snapshot['project_id'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from existing snapshot.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """

        create_params = {
            'name': self._get_dbref_name(volume),
            'src': {
                'volume_id': snapshot['volume_id'],
                'snapshot_id': snapshot['id'],
            },
        }

        LOG.debug("Creating volume from snapshot %(id)s", snapshot,
                  resource=volume)

        return self._create_volume(volume['id'],
                                   create_params,
                                   user_id=volume['user_id'],
                                   project_id=volume['project_id'])

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot.

        :param snapshot: shapshot reference
        """

        LOG.debug("Deleting snapshot of volume %(volume_id)s", snapshot,
                  resource=snapshot)

        self._delete_snapshot(snapshot['volume_id'],
                              snapshot['id'],
                              user_id=snapshot['user_id'],
                              project_id=snapshot['project_id'])

    def create_export(self, _ctx, volume, connector):
        """Do nothing: target created during instance attachment."""
        pass

    def ensure_export(self, _ctx, volume):
        """Do nothing: target created during instance attachment."""
        pass

    def remove_export(self, _ctx, volume):
        """Do nothing: target created during instance attachment."""
        pass

    def initialize_connection(self, volume, connector, **kwargs):
        """Attach volume to initiator/host.

        Creates a profile for the initiator, and adds the new profile to the
        target ACL.

        """

        # generate a CHAP secret here -- there is no way to retrieve an
        # existing CHAP secret over the Blockbridge API, so it must be
        # supplied by the volume driver.
        export_params = {
            'chap_user': (
                kwargs.get('user', volume_utils.generate_username(16))),
            'chap_secret': (
                kwargs.get('password', volume_utils.generate_password(32))),
        }

        LOG.debug("Configuring export for %(initiator)s", connector,
                  resource=volume)

        rsp = self._create_export(volume['id'],
                                  connector['initiator'],
                                  export_params,
                                  user_id=volume['user_id'],
                                  project_id=volume['project_id'])

        # combine locally generated chap credentials with target iqn/lun to
        # present the attach properties.
        target_portal = "%s:%s" % (rsp['target_ip'], rsp['target_port'])

        properties = {
            'target_discovered': False,
            'target_portal': target_portal,
            'target_iqn': rsp['target_iqn'],
            'target_lun': rsp['target_lun'],
            'volume_id': volume['id'],
            'auth_method': 'CHAP',
            'auth_username': rsp['initiator_login'],
            'auth_password': export_params['chap_secret'],
        }

        LOG.debug("Attach properties: %(properties)s",
                  {'properties': properties})

        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Detach volume from the initiator.

        Removes initiator profile entry from target ACL.

        """

        LOG.debug("Unconfiguring export for %(initiator)s", connector,
                  resource=volume)

        self._delete_export(volume['id'],
                            connector['initiator'],
                            user_id=volume['user_id'],
                            project_id=volume['project_id'])

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""

        capacity = new_size * units.Gi

        LOG.debug("Extending volume to %(capacity)s bytes",
                  {'capacity': capacity}, resource=volume)

        self._extend_volume(volume['id'],
                            int(new_size * units.Gi),
                            user_id=volume['user_id'],
                            project_id=volume['project_id'])

    def get_volume_stats(self, refresh=False):
        if refresh:
            self._update_volume_stats()
        return self._stats

    def _update_volume_stats(self):
        if self.configuration:
            cfg_name = self.configuration.safe_get('volume_backend_name')
        backend_name = cfg_name or self.__class__.__name__

        driver_cfg = {
            'hostname': self.hostname,
            'version': self.VERSION,
            'backend_name': backend_name,
        }

        filter_function = self.get_filter_function()
        goodness_function = self.get_goodness_function()
        pools = []

        LOG.debug("Updating volume driver statistics",
                  resource={'type': 'driver', 'id': backend_name})

        for pool_name, query in self.configuration.blockbridge_pools.items():
            stats = self._get_pool_stats(pool_name, query, **driver_cfg)

            system_serial = stats.get('system_serial', 'unknown')
            free_capacity = stats.get('free_capacity', None)
            total_capacity = stats.get('total_capacity', None)
            provisioned_capacity = stats.get('provisioned_capacity', None)

            if free_capacity is None:
                free_capacity = 'unknown'
            else:
                free_capacity = int(free_capacity / units.Gi)

            if total_capacity is None:
                total_capacity = 'unknown'
            else:
                total_capacity = int(total_capacity / units.Gi)

            pool = {
                'pool_name': pool_name,
                'location_info': ('BlockbridgeDriver:%(sys_id)s:%(pool)s' %
                                  {'sys_id': system_serial,
                                   'pool': pool_name}),
                'max_over_subscription_ratio': (
                    self.configuration.safe_get('max_over_subscription_ratio')
                ),
                'free_capacity_gb': free_capacity,
                'total_capacity_gb': total_capacity,
                'reserved_percentage': 0,
                'thin_provisioning_support': True,
                'filter_function': filter_function,
                'goodness_function': goodness_function,
            }

            if provisioned_capacity is not None:
                pool['provisioned_capacity_gb'] = int(
                    provisioned_capacity / units.Gi
                )

            pools.append(pool)

        self._stats = {
            'volume_backend_name': backend_name,
            'vendor_name': 'Blockbridge',
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'pools': pools,
        }
