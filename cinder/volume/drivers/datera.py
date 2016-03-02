# Copyright 2016 Datera
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
from oslo_utils import excutils
from oslo_utils import units
import requests
import six

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder import utils
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

d_opts = [
    cfg.StrOpt('datera_api_port',
               default='7717',
               help='Datera API port.'),
    cfg.StrOpt('datera_api_version',
               default='2',
               help='Datera API version.'),
    cfg.StrOpt('datera_num_replicas',
               default='1',
               help='Number of replicas to create of an inode.')
]


CONF = cfg.CONF
CONF.import_opt('driver_use_ssl', 'cinder.volume.driver')
CONF.register_opts(d_opts)

DEFAULT_STORAGE_NAME = 'storage-1'
DEFAULT_VOLUME_NAME = 'volume-1'


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
        2.0 - Update For Datera API v2
    """
    VERSION = '2.0'

    def __init__(self, *args, **kwargs):
        super(DateraDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(d_opts)
        self.num_replicas = self.configuration.datera_num_replicas
        self.username = self.configuration.san_login
        self.password = self.configuration.san_password
        self.auth_token = None
        self.cluster_stats = {}
        self.datera_api_token = None

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
            results = self._issue_api_request('login', 'put', body=body,
                                              sensitive=True)
            self.datera_api_token = results['key']
        except exception.NotAuthorized:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Logging into the Datera cluster failed. Please '
                              'check your username and password set in the '
                              'cinder.conf and start the cinder-volume '
                              'service again.'))

    def _get_lunid(self):
        return 0

    def do_setup(self, context):
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
        if result['storage_instances'][DEFAULT_STORAGE_NAME]['volumes'][
                DEFAULT_VOLUME_NAME]['op_state'] == 'available':
            return
        else:
            raise exception.VolumeDriverException(
                message=_('Resource not ready.'))

    def _create_resource(self, resource, resource_type, body):
        type_id = resource.get('volume_type_id', None)

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
            # Handle updating QOS Policies
            if resource_type == 'app_instances':
                url = ('app_instances/{}/storage_instances/{}/volumes/{'
                       '}/performance_policy')
                url = url.format(
                    resource['id'],
                    DEFAULT_STORAGE_NAME,
                    DEFAULT_VOLUME_NAME)
                if type_id is not None:
                    policies = self._get_policies_by_volume_type(type_id)
                    if policies:
                        self._issue_api_request(url, 'post', body=policies)
            if result['storage_instances'][DEFAULT_STORAGE_NAME]['volumes'][
                    DEFAULT_VOLUME_NAME]['op_state'] == 'available':
                return
            self._wait_for_resource(resource['id'], resource_type)

    def create_volume(self, volume):
        """Create a logical volume."""
        # Generate App Instance, Storage Instance and Volume
        # Volume ID will be used as the App Instance Name
        # Storage Instance and Volumes will have standard names
        app_params = (
            {
                'create_mode': "openstack",
                'uuid': str(volume['id']),
                'name': str(volume['id']),
                'access_control_mode': 'allow_all',
                'storage_instances': {
                    DEFAULT_STORAGE_NAME: {
                        'name': DEFAULT_STORAGE_NAME,
                        'volumes': {
                            DEFAULT_VOLUME_NAME: {
                                'name': DEFAULT_VOLUME_NAME,
                                'size': volume['size'],
                                'replica_count': int(self.num_replicas),
                                'snapshot_policies': {
                                }
                            }
                        }
                    }
                }
            })
        self._create_resource(volume, 'app_instances', body=app_params)

    def extend_volume(self, volume, new_size):
        # Offline App Instance, if necessary
        reonline = False
        app_inst = self._issue_api_request(
            "app_instances/{}".format(volume['id']))
        if app_inst['admin_state'] == 'online':
            reonline = True
            self.detach_volume(None, volume)
        # Change Volume Size
        app_inst = volume['id']
        storage_inst = DEFAULT_STORAGE_NAME
        data = {
            'size': new_size
        }
        self._issue_api_request(
            'app_instances/{}/storage_instances/{}/volumes/{}'.format(
                app_inst, storage_inst, DEFAULT_VOLUME_NAME),
            method='put', body=data)
        # Online Volume, if it was online before
        if reonline:
            self.create_export(None, volume)

    def create_cloned_volume(self, volume, src_vref):
        clone_src_template = ("/app_instances/{}/storage_instances/{"
                              "}/volumes/{}")
        src = clone_src_template.format(src_vref['id'], DEFAULT_STORAGE_NAME,
                                        DEFAULT_VOLUME_NAME)
        data = {
            'create_mode': 'openstack',
            'name': str(volume['id']),
            'uuid': str(volume['id']),
            'clone_src': src,
            'access_control_mode': 'allow_all'
        }
        self._issue_api_request('app_instances', 'post', body=data)

    def delete_volume(self, volume):
        self.detach_volume(None, volume)
        app_inst = volume['id']
        try:
            self._issue_api_request('app_instances/{}'.format(app_inst),
                                    method='delete')
        except exception.NotFound:
            msg = _LI("Tried to delete volume %s, but it was not found in the "
                      "Datera cluster. Continuing with delete.")
            LOG.info(msg, volume['id'])

    def ensure_export(self, context, volume, connector):
        """Gets the associated account, retrieves CHAP info and updates."""
        return self.create_export(context, volume, connector)

    def create_export(self, context, volume, connector):
        url = "app_instances/{}".format(volume['id'])
        data = {
            'admin_state': 'online'
        }
        app_inst = self._issue_api_request(url, method='put', body=data)
        storage_instance = app_inst['storage_instances'][
            DEFAULT_STORAGE_NAME]

        portal = storage_instance['access']['ips'][0] + ':3260'
        iqn = storage_instance['access']['iqn']

        # Portal, IQN, LUNID
        provider_location = '%s %s %s' % (portal, iqn, self._get_lunid())
        return {'provider_location': provider_location}

    def detach_volume(self, context, volume, attachment=None):
        url = "app_instances/{}".format(volume['id'])
        data = {
            'admin_state': 'offline',
            'force': True
        }
        try:
            self._issue_api_request(url, method='put', body=data)
        except exception.NotFound:
            msg = _LI("Tried to detach volume %s, but it was not found in the "
                      "Datera cluster. Continuing with detach.")
            LOG.info(msg, volume['id'])

    def create_snapshot(self, snapshot):
        url_template = ('app_instances/{}/storage_instances/{}/volumes/{'
                        '}/snapshots')
        url = url_template.format(snapshot['volume_id'],
                                  DEFAULT_STORAGE_NAME,
                                  DEFAULT_VOLUME_NAME)

        snap_params = {
            'uuid': snapshot['id'],
        }
        self._issue_api_request(url, method='post', body=snap_params)

    def delete_snapshot(self, snapshot):
        snap_temp = ('app_instances/{}/storage_instances/{}/volumes/{'
                     '}/snapshots')
        snapu = snap_temp.format(snapshot['volume_id'],
                                 DEFAULT_STORAGE_NAME,
                                 DEFAULT_VOLUME_NAME)

        snapshots = self._issue_api_request(snapu, method='get')

        try:
            for ts, snap in snapshots.items():
                if snap['uuid'] == snapshot['id']:
                    url_template = snapu + '/{}'
                    url = url_template.format(ts)
                    self._issue_api_request(url, method='delete')
                    break
            else:
                raise exception.NotFound
        except exception.NotFound:
            msg = _LI("Tried to delete snapshot %s, but was not found in "
                      "Datera cluster. Continuing with delete.")
            LOG.info(msg, snapshot['id'])

    def create_volume_from_snapshot(self, volume, snapshot):
        snap_temp = ('app_instances/{}/storage_instances/{}/volumes/{'
                     '}/snapshots')
        snapu = snap_temp.format(snapshot['volume_id'],
                                 DEFAULT_STORAGE_NAME,
                                 DEFAULT_VOLUME_NAME)

        snapshots = self._issue_api_request(snapu, method='get')
        for ts, snap in snapshots.items():
            if snap['uuid'] == snapshot['id']:
                found_ts = ts
                break
        else:
            raise exception.NotFound

        src = ('/app_instances/{}/storage_instances/{}/volumes/{'
               '}/snapshots/{}'.format(
                   snapshot['volume_id'],
                   DEFAULT_STORAGE_NAME,
                   DEFAULT_VOLUME_NAME,
                   found_ts))
        app_params = (
            {
                'create_mode': 'openstack',
                'uuid': str(volume['id']),
                'name': str(volume['id']),
                'clone_src': src,
                'access_control_mode': 'allow_all'
            })
        self._issue_api_request(
            'app_instances',
            method='post',
            body=app_params)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update first.
        The name is a bit misleading as
        the majority of the data here is cluster
        data.
        """
        if refresh or not self.cluster_stats:
            try:
                self._update_cluster_stats()
            except exception.DateraAPIException:
                LOG.error(_LE('Failed to get updated stats from Datera '
                              'cluster.'))
        return self.cluster_stats

    def _update_cluster_stats(self):
        LOG.debug("Updating cluster stats info.")

        results = self._issue_api_request('system')

        if 'uuid' not in results:
            LOG.error(_LE('Failed to get updated stats from Datera Cluster.'))

        backend_name = self.configuration.safe_get('volume_backend_name')
        stats = {
            'volume_backend_name': backend_name or 'Datera',
            'vendor_name': 'Datera',
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'total_capacity_gb': int(results['total_capacity']) / units.Gi,
            'free_capacity_gb': int(results['available_capacity']) / units.Gi,
            'reserved_percentage': 0,
        }

        self.cluster_stats = stats

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
        api_token = self.datera_api_token
        api_version = self.configuration.datera_api_version

        payload = json.dumps(body, ensure_ascii=False)
        payload.encode('utf-8')

        if not sensitive:
            LOG.debug("Payload for Datera API call: %s", payload)

        header = {'Content-Type': 'application/json; charset=utf-8'}

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
            msg = _(
                'Failed to make a request to Datera cluster endpoint due '
                'to the following reason: %s') % six.text_type(
                ex.message)
            LOG.error(msg)
            raise exception.DateraAPIException(msg)

        data = response.json()
        if not sensitive:
            LOG.debug("Results of Datera API call: %s", data)

        if not response.ok:
            LOG.debug(("Datera Response URL: %s\n"
                       "Datera Response Payload: %s\n"
                       "Response Object: %s\n"),
                      response.url,
                      payload,
                      vars(response))
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
