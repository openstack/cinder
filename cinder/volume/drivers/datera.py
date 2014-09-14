# Copyright 2014 Datera
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

from oslo.config import cfg
import requests

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import units
from cinder.volume.drivers.san import san

LOG = logging.getLogger(__name__)

d_opts = [
    cfg.StrOpt('datera_api_token',
               default=None,
               help='Datera API token.'),
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
CONF.register_opts(d_opts)


class DateraDriver(san.SanISCSIDriver):
    """The OpenStack Datera Driver

    Version history:
        1.0 - Initial driver
    """
    VERSION = '1.0'

    def __init__(self, *args, **kwargs):
        super(DateraDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(d_opts)
        self.num_replicas = self.configuration.datera_num_replicas
        self.cluster_stats = {}

    def create_volume(self, volume):
        """Create a logical volume."""
        params = {
            'name': volume['display_name'] or volume['id'],
            'size': str(volume['size'] * units.Gi),
            'uuid': volume['id'],
            'numReplicas': self.num_replicas
        }
        self._issue_api_request('volumes', 'post', body=params)

    def create_cloned_volume(self, volume, src_vref):
        data = {
            'name': volume['display_name'] or volume['id'],
            'uuid': volume['id'],
            'clone_uuid': src_vref['id'],
            'numReplicas': self.num_replicas
        }
        self._issue_api_request('volumes', 'post', body=data)

    def delete_volume(self, volume):
        try:
            self._issue_api_request('volumes', 'delete', volume['id'])
        except exception.NotFound:
            msg = _("Tried to delete volume %s, but it was not found in the "
                    "Datera cluster. Continuing with delete.")
            LOG.info(msg, volume['id'])

    def _do_export(self, context, volume):
        """Gets the associated account, retrieves CHAP info and updates."""
        if volume['provider_location']:
            return {'provider_location': volume['provider_location']}

        export = self._issue_api_request(
            'volumes', action='export', method='post',
            body={'ctype': 'TC_BLOCK_ISCSI'}, resource=volume['id'])

        # NOTE(thingee): Refer to the Datera test for a stub of what this looks
        # like. We're just going to pull the first IP that the Datera cluster
        # makes available for the portal.
        iscsi_portal = export['_ipColl'][0] + ':3260'
        iqn = export['targetIds'].itervalues().next()['ids'][0]['id']

        provider_location = '%s %s %s' % (iscsi_portal, iqn, 1)
        model_update = {'provider_location': provider_location}
        return model_update

    def ensure_export(self, context, volume):
        return self._do_export(context, volume)

    def create_export(self, context, volume):
        return self._do_export(context, volume)

    def detach_volume(self, context, volume):
        try:
            self._issue_api_request('volumes', 'delete', resource=volume['id'],
                                    action='export')
        except exception.NotFound:
            msg = _("Tried to delete export for volume %s, but it was not "
                    "found in the Datera cluster. Continuing with volume "
                    "detach")
            LOG.info(msg, volume['id'])

    def delete_snapshot(self, snapshot):
        try:
            self._issue_api_request('snapshots', 'delete', snapshot['id'])
        except exception.NotFound:
            msg = _("Tried to delete snapshot %s, but was not found in Datera "
                    "cluster. Continuing with delete.")
            LOG.info(msg, snapshot['id'])

    def create_snapshot(self, snapshot):
        data = {
            'uuid': snapshot['id'],
            'parentUUID': snapshot['volume_id']
        }
        self._issue_api_request('snapshots', 'post', body=data)

    def create_volume_from_snapshot(self, volume, snapshot):
        data = {
            'name': volume['display_name'] or volume['id'],
            'uuid': volume['id'],
            'snapshot_uuid': snapshot['id'],
            'numReplicas': self.num_replicas
        }
        self._issue_api_request('volumes', 'post', body=data)

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
                LOG.error('Failed to get updated stats from Datera cluster.')
                pass

        return self.cluster_stats

    def extend_volume(self, volume, new_size):
        data = {
            'size': str(new_size * units.Gi)
        }
        self._issue_api_request('volumes', 'put', body=data,
                                resource=volume['id'])

    def _update_cluster_stats(self):
        LOG.debug("Updating cluster stats info.")

        results = self._issue_api_request('cluster')

        if 'uuid' not in results:
            LOG.error(_('Failed to get updated stats from Datera Cluster.'))

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

    def _issue_api_request(self, resource_type, method='get', resource=None,
                           body=None, action=None):
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
        header = {'Content-Type': 'application/json; charset=utf-8'}

        if api_token:
            header['Auth-Token'] = api_token

        LOG.debug("Payload for Datera API call: %s", payload)

        client_cert = self.configuration.driver_client_cert
        client_cert_key = self.configuration.driver_client_cert_key
        protocol = 'http'
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
                    'to the following reason: %s') % ex.message
            LOG.error(msg)
            raise exception.DateraAPIException(msg)

        data = response.json()
        LOG.debug("Results of Datera API call: %s", data)
        if not response.ok:
            if response.status_code == 404:
                raise exception.NotFound(data['message'])
            else:
                msg = _('Request to Datera cluster returned bad status:'
                        ' %(status)s | %(reason)s') % {
                            'status': response.status_code,
                            'reason': response.reason}
                LOG.error(msg)
                raise exception.DateraAPIException(msg)

        return data
