# Copyright 2015 Datera
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

import json

from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
from oslo_utils import excutils
from oslo_utils import units
import requests
import six

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

d_opts = [
    cfg.StrOpt('datera_api_token',
               help='DEPRECATED: This will be removed in the Liberty release. '
                    'Use san_login and san_password instead. This directly '
                    'sets the Datera API token.'),
    cfg.StrOpt('datera_api_port',
               default='7717',
               help='Datera API port.'),
    cfg.StrOpt('datera_api_version',
               default='1',
               help='Datera API version.'),
    cfg.StrOpt('datera_num_replicas',
               default='3',
               help='Number of replicas to create of an inode.')
]


CONF = cfg.CONF
CONF.import_opt('driver_client_cert_key', 'cinder.volume.driver')
CONF.import_opt('driver_client_cert', 'cinder.volume.driver')
CONF.import_opt('driver_use_ssl', 'cinder.volume.driver')
CONF.register_opts(d_opts)


def _authenticated(func):
    """Ensure the driver is authenticated to make a request.

    In do_setup() we fetch an auth token and store it. If that expires when
    we do API request, we'll fetch a new one.
    """
    def func_wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except exception.NotAuthorized:
            # Prevent recursion loop. After the self arg is the
            # resource_type arg from _issue_api_request(). If attempt to
            # login failed, we should just give up.
            if args[0] == 'login':
                raise

            # Token might've expired, get a new one, try again.
            self._login()
            return func(self, *args, **kwargs)
    return func_wrapper


class DateraDriver(san.SanISCSIDriver):
    """The OpenStack Datera Driver

    Version history:
        1.0 - Initial driver
        1.1 - Look for lun-0 instead of lun-1.
    """
    VERSION = '1.1'

    def __init__(self, *args, **kwargs):
        super(DateraDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(d_opts)
        self.num_replicas = self.configuration.datera_num_replicas
        self.username = self.configuration.san_login
        self.password = self.configuration.san_password
        self.auth_token = None
        self.cluster_stats = {}

    def do_setup(self, context):
        # If any of the deprecated options are set, we'll warn the operator to
        # use the new authentication method.
        DEPRECATED_OPTS = [
            self.configuration.driver_client_cert_key,
            self.configuration.driver_client_cert,
            self.configuration.datera_api_token
        ]

        if any(DEPRECATED_OPTS):
            msg = _LW("Client cert verification and datera_api_token are "
                      "deprecated in the Datera driver, and will be removed "
                      "in the Liberty release. Please set the san_login and "
                      "san_password in your cinder.conf instead.")
            versionutils.report_deprecated_feature(LOG, msg)
            return

        # If we can't authenticate through the old and new method, just fail
        # now.
        if not all([self.username, self.password]):
            msg = _("san_login and/or san_password is not set for Datera "
                    "driver in the cinder.conf. Set this information and "
                    "start the cinder-volume service again.")
            LOG.error(msg)
            raise exception.InvalidInput(msg)

        self._login()

    @utils.retry(exception.VolumeDriverException, retries=3)
    def _wait_for_resource(self, id, resource_type):
        result = self._issue_api_request(resource_type, 'get', id)
        if result['status'] == 'available':
            return
        else:
            raise exception.VolumeDriverException(message=
                                                  _('Resource not ready.'))

    def _create_resource(self, resource, resource_type, body):
        type_id = resource.get('volume_type_id', None)
        if resource_type == 'volumes':
            if type_id is not None:
                policies = self._get_policies_by_volume_type(type_id)
                if policies:
                    body.update(policies)

        result = None
        try:
            result = self._issue_api_request(resource_type, 'post', body=body)
        except exception.Invalid:
            if resource_type == 'volumes' and type_id:
                LOG.error(_LE("Creation request failed. Please verify the "
                              "extra-specs set for your volume types are "
                              "entered correctly."))
            raise
        else:
            if result['status'] == 'available':
                return
            self._wait_for_resource(resource['id'], resource_type)

    def create_volume(self, volume):
        """Create a logical volume."""
        body = {
            'name': volume['display_name'] or volume['id'],
            'size': str(volume['size'] * units.Gi),
            'uuid': volume['id'],
            'numReplicas': self.num_replicas
        }
        self._create_resource(volume, 'volumes', body)

    def create_cloned_volume(self, volume, src_vref):
        body = {
            'name': volume['display_name'] or volume['id'],
            'uuid': volume['id'],
            'clone_uuid': src_vref['id'],
            'numReplicas': self.num_replicas
        }
        self._create_resource(volume, 'volumes', body)

    def delete_volume(self, volume):
        try:
            self._issue_api_request('volumes', 'delete', volume['id'])
        except exception.NotFound:
            LOG.info(_LI("Tried to delete volume %s, but it was not found in "
                         "the Datera cluster. Continuing with delete."),
                     volume['id'])

    def _do_export(self, context, volume):
        """Gets the associated account, retrieves CHAP info and updates."""
        portal = None
        iqn = None
        datera_volume = self._issue_api_request('volumes',
                                                resource=volume['id'])
        if len(datera_volume['targets']) == 0:
            export = self._issue_api_request(
                'volumes', action='export', method='post',
                body={'ctype': 'TC_BLOCK_ISCSI'}, resource=volume['id'])

            portal = "%s:3260" % export['endpoint_addrs'][0]

            iqn = export['endpoint_idents'][0]
        else:
            export = self._issue_api_request(
                'export_configs',
                resource=datera_volume['targets'][0]
            )
            portal = export['endpoint_addrs'][0] + ':3260'
            iqn = export['endpoint_idents'][0]

        provider_location = '%s %s %s' % (portal, iqn, 0)
        return {'provider_location': provider_location}

    def ensure_export(self, context, volume):
        return self._do_export(context, volume)

    def create_export(self, context, volume, connector):
        return self._do_export(context, volume)

    def detach_volume(self, context, volume, attachment=None):
        try:
            self._issue_api_request('volumes', 'delete', resource=volume['id'],
                                    action='export')
        except exception.NotFound:
            LOG.info(_LI("Tried to delete export for volume %s, but it was "
                         "not found in the Datera cluster. Continuing with "
                         "volume detach"), volume['id'])

    def delete_snapshot(self, snapshot):
        try:
            self._issue_api_request('snapshots', 'delete', snapshot['id'])
        except exception.NotFound:
            LOG.info(_LI("Tried to delete snapshot %s, but was not found in "
                         "Datera cluster. Continuing with delete."),
                     snapshot['id'])

    def create_snapshot(self, snapshot):
        body = {
            'uuid': snapshot['id'],
            'parentUUID': snapshot['volume_id']
        }
        self._create_resource(snapshot, 'snapshots', body)

    def create_volume_from_snapshot(self, volume, snapshot):
        body = {
            'name': volume['display_name'] or volume['id'],
            'uuid': volume['id'],
            'snapshot_uuid': snapshot['id'],
            'numReplicas': self.num_replicas
        }
        self._create_resource(volume, 'volumes', body)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update first.
        The name is a bit misleading as
        the majority of the data here is cluster
        data.
        """
        if refresh:
            try:
                self._update_cluster_stats()
            except exception.DateraAPIException:
                LOG.error(_LE('Failed to get updated stats from Datera '
                              'cluster.'))
                pass

        return self.cluster_stats

    def extend_volume(self, volume, new_size):
        body = {
            'size': str(new_size * units.Gi)
        }
        self._issue_api_request('volumes', 'put', body=body,
                                resource=volume['id'])

    def _update_cluster_stats(self):
        LOG.debug("Updating cluster stats info.")

        results = self._issue_api_request('cluster')

        if 'uuid' not in results:
            LOG.error(_LE('Failed to get updated stats from Datera Cluster.'))

        backend_name = self.configuration.safe_get('volume_backend_name')
        stats = {
            'volume_backend_name': backend_name or 'Datera',
            'vendor_name': 'Datera',
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'total_capacity_gb': int(results['totalRawSpace']),
            'free_capacity_gb': int(results['availableSpace']),
            'reserved_percentage': 0,
        }

        self.cluster_stats = stats

    def _login(self):
        """Use the san_login and san_password to set self.auth_token."""
        body = {
            'name': self.username,
            'password': self.password
        }

        # Unset token now, otherwise potential expired token will be sent
        # along to be used for authorization when trying to login.
        self.auth_token = None

        try:
            LOG.debug('Getting Datera auth token.')
            results = self._issue_api_request('login', 'post', body=body,
                                              sensitive=True)
            self.auth_token = results['key']
        except exception.NotAuthorized:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Logging into the Datera cluster failed. Please '
                              'check your username and password set in the '
                              'cinder.conf and start the cinder-volume'
                              'service again.'))

    def _get_policies_by_volume_type(self, type_id):
        """Get extra_specs and qos_specs of a volume_type.

        This fetches the scoped keys from the volume type. Anything set from
         qos_specs will override key/values set from extra_specs.
        """
        ctxt = context.get_admin_context()
        volume_type = volume_types.get_volume_type(ctxt, type_id)
        specs = volume_type.get('extra_specs')

        policies = {}
        for key, value in specs.items():
            if ':' in key:
                fields = key.split(':')
                key = fields[1]
                policies[key] = value

        qos_specs_id = volume_type.get('qos_specs_id')
        if qos_specs_id is not None:
            qos_kvs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']
            if qos_kvs:
                policies.update(qos_kvs)
        return policies

    @_authenticated
    def _issue_api_request(self, resource_type, method='get', resource=None,
                           body=None, action=None, sensitive=False):
        """All API requests to Datera cluster go through this method.

        :param resource_type: the type of the resource
        :param method: the request verb
        :param resource: the identifier of the resource
        :param body: a dict with options for the action_type
        :param action: the action to perform
        :returns: a dict of the response from the Datera cluster
        """
        host = self.configuration.san_ip
        port = self.configuration.datera_api_port
        api_token = self.configuration.datera_api_token
        api_version = self.configuration.datera_api_version

        payload = json.dumps(body, ensure_ascii=False)
        payload.encode('utf-8')

        if not sensitive:
            LOG.debug("Payload for Datera API call: %s", payload)

        header = {
            'Content-Type': 'application/json; charset=utf-8',
            'auth-token': self.auth_token
        }

        protocol = 'http'
        if self.configuration.driver_use_ssl:
            protocol = 'https'

        # TODO(thingee): Auth method through Auth-Token is deprecated. Remove
        # this and client cert verification stuff in the Liberty release.
        if api_token:
            header['Auth-Token'] = api_token

        client_cert = self.configuration.driver_client_cert
        client_cert_key = self.configuration.driver_client_cert_key
        cert_data = None

        if client_cert:
            protocol = 'https'
            cert_data = (client_cert, client_cert_key)

        connection_string = '%s://%s:%s/v%s/%s' % (protocol, host, port,
                                                   api_version, resource_type)

        if resource is not None:
            connection_string += '/%s' % resource
        if action is not None:
            connection_string += '/%s' % action

        LOG.debug("Endpoint for Datera API call: %s", connection_string)
        try:
            response = getattr(requests, method)(connection_string,
                                                 data=payload, headers=header,
                                                 verify=False, cert=cert_data)
        except requests.exceptions.RequestException as ex:
            msg = _('Failed to make a request to Datera cluster endpoint due '
                    'to the following reason: %s') % six.text_type(ex.message)
            LOG.error(msg)
            raise exception.DateraAPIException(msg)

        data = response.json()
        if not sensitive:
            LOG.debug("Results of Datera API call: %s", data)

        if not response.ok:
            if response.status_code == 404:
                raise exception.NotFound(data['message'])
            elif response.status_code in [403, 401]:
                raise exception.NotAuthorized()
            elif response.status_code == 400 and 'invalidArgs' in data:
                msg = _('Bad request sent to Datera cluster:'
                        'Invalid args: %(args)s | %(message)s') % {
                            'args': data['invalidArgs']['invalidAttrs'],
                            'message': data['message']}
                raise exception.Invalid(msg)
            else:
                msg = _('Request to Datera cluster returned bad status:'
                        ' %(status)s | %(reason)s') % {
                            'status': response.status_code,
                            'reason': response.reason}
                LOG.error(msg)
                raise exception.DateraAPIException(msg)

        return data
