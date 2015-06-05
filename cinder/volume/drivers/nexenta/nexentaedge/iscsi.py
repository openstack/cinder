# Copyright 2014 Nexenta Systems, Inc.
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
:mod:`nexenta.iscsi` -- Driver to store volumes on NexentaEdge
=====================================================================
.. automodule:: nexenta.volume
.. moduleauthor:: Zohar Mamedov <zohar.mamedov@nexenta.com>
.. moduleauthor:: Kyle Schochenmaier <kyle.schochenmaier@nexenta.com>
"""

import json

from cinder.i18n import _LE
from cinder.volume import driver
from cinder.volume.drivers import nexenta
from cinder.volume.drivers.nexenta.nexentaedge import jsonrpc as jsonrpc
from oslo_log import log as logging
from oslo_config import cfg


NEXENTA_EDGE_OPTIONS = [
    cfg.StrOpt('nexenta_rest_address',
               default='',
               help='IP address of NexentaEdge management REST API endpoint'),
    cfg.IntOpt('nexenta_rest_port',
               default=8080,
               help='HTTP port to connect to NexentaEdge REST API endpoint'),
    cfg.StrOpt('nexenta_rest_protocol',
               default='auto',
               help='Use http or https for REST connection (default auto)'),
    cfg.IntOpt('nexenta_iscsi_target_portal_port',
               default=3260,
               help='NexentaEdge target portal port'),
    cfg.StrOpt('nexenta_rest_user',
               default='admin',
               help='User name to connect to NexentaEdge'),
    cfg.StrOpt('nexenta_rest_password',
               default='nexenta',
               help='Password to connect to NexentaEdge',
               secret=True),
    cfg.StrOpt('nexenta_lun_container',
               default='',
               help='NexentaEdge logical path of bucket for LUNs'),
    cfg.StrOpt('nexenta_iscsi_service',
               default='',
               help='NexentaEdge iSCSI service name'),
    cfg.StrOpt('nexenta_client_address',
               default='',
               help='NexentaEdge iSCSI Gateway client ' +
               'address for non-VIP service')
]

CONF = cfg.CONF
CONF.register_opts(NEXENTA_EDGE_OPTIONS)

LOG = logging.getLogger(__name__)


class NexentaEdgeISCSIDriver(driver.ISCSIDriver):  # pylint: disable=R0921
    """Executes volume driver commands on NexentaEdge cluster.
    Version history:
        1.0.0 - Initial driver version.
    """

    VERSION = '1.0.0'

    LUN_BLOCKSIZE = 4096
    LUN_CHUNKSIZE = 32768

    def __init__(self, *args, **kwargs):
        super(NexentaEdgeISCSIDriver, self).__init__(*args, **kwargs)
        if self.configuration:
            self.configuration.append_config_values(NEXENTA_EDGE_OPTIONS)
        self.restapi_protocol = self.configuration.nexenta_rest_protocol
        self.restapi_host = self.configuration.nexenta_rest_address
        self.restapi_port = self.configuration.nexenta_rest_port
        self.restapi_user = self.configuration.nexenta_rest_user
        self.restapi_password = self.configuration.nexenta_rest_password
        self.iscsi_service = self.configuration.nexenta_iscsi_service
        self.bucket_path = self.configuration.nexenta_lun_container
        self.cluster, self.tenant, self.bucket = self.bucket_path.split('/')
        self.bucket_url = 'clusters/' + self.cluster + '/tenants/' + \
            self.tenant + '/buckets/' + self.bucket
        self.iscsi_target_portal_port = \
            self.configuration.nexenta_iscsi_target_portal_port
        self.target_vip = None

    @property
    def backend_name(self):
        backend_name = None
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = self.__class__.__name__
        return backend_name

    def do_setup(self, context):
        if self.restapi_protocol == 'auto':
            protocol, auto = 'http', True
        else:
            protocol, auto = self.restapi_protocol, False

        try:
            self.restapi = jsonrpc.NexentaEdgeJSONProxy(
                protocol, self.restapi_host, self.restapi_port, '/',
                self.restapi_user, self.restapi_password, auto=auto)

            rsp = self.restapi.get('service/'
                                   + self.iscsi_service + '/iscsi/status')
            self.target_name = rsp['data'][rsp['data']
                .keys()[0]].split('\n', 1)[0].split(' ')[2]

            rsp = self.restapi.get('service/' + self.iscsi_service)
            if ('X-VIPS' in rsp['data']):
                vips = json.loads(rsp['data']['X-VIPS'])
                if (len(vips[0]) == 1):
                    self.target_vip = vips[0][0]['ip'].split('/', 1)[0]
                else:
                    self.target_vip = vips[0][1]['ip'].split('/', 1)[0]
            else:
                self.target_vip = self.configuration.safe_get(
                    'nexenta_client_address')
                if not self.target_vip:
                    LOG.error(_LE('No VIP configured for service %s')
                              % self.iscsi_service)
                    raise Exception('No service VIP configured and ' +
                                    'no nexenta_client_address')
        except Exception as exc:
            LOG.error(_LE('Error verifying iSCSI service %s on host %s')
                      % (self.iscsi_service, self.restapi_host))
            LOG.error(str(exc))
            raise

    def check_for_setup_error(self):
        try:
            self.restapi.get(self.bucket_url + '/objects/')
        except Exception as exc:
            LOG.error(_LE('Error verifying LUN container %s')
                      % self.bucket_path)
            LOG.error(str(exc))
            raise

    def _get_lun_number(self, volname):
        try:
            rsp = self.restapi.put(
                'service/' + self.iscsi_service + '/iscsi/number',
                {
                    'objectPath': self.bucket_path + '/' + volname
                })
        except Exception as exc:
            LOG.error(_LE('Error retrieving LUN %s number') % volname)
            LOG.error(str(exc))
            raise

        return rsp['data']

    def _get_target_address(self, volname):
        return self.target_vip

    def _get_provider_location(self, volume):
        return '%(host)s:%(port)s,1 %(name)s %(number)s' % {
            'host': self._get_target_address(volume['name']),
            'port': self.configuration.nexenta_iscsi_target_portal_port,
            'name': self.target_name,
            'number': self._get_lun_number(volume['name'])
        }

    def create_volume(self, volume):
        try:
            self.restapi.post('service/' + self.iscsi_service + '/iscsi', {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'volSizeMB': int(volume['size']) * 1024,
                'blockSize': self.LUN_BLOCKSIZE,
                'chunkSize': self.LUN_CHUNKSIZE
            })
        except nexenta.NexentaException as e:
            LOG.error(_LE('Error creating volume: %s') % unicode(e))
            raise

    def delete_volume(self, volume):
        try:
            self.restapi.delete('service/' + self.iscsi_service +
                                '/iscsi', {'objectPath': self.bucket_path +
                                           '/' + volume['name']})
        except nexenta.NexentaException as e:
            LOG.error(_LE('Error deleting volume: %s') % unicode(e))
            raise

    def extend_volume(self, volume, new_size):
        try:
            self.restapi.put('service/' + self.iscsi_service + '/iscsi/resize',
                             {'objectPath': self.bucket_path + '/' +
                              volume['name'], 'newSizeMB': new_size * 1024})
        except nexenta.NexentaException as e:
            LOG.error(_LE('Error extending volume: %s') % unicode(e))
            raise

    def create_volume_from_snapshot(self, volume, snapshot):
        try:
            self.restapi.put(
                'service/' + self.iscsi_service + '/iscsi/snapshot/clone',
                {
                    'objectPath': self.bucket_path + '/' +
                    snapshot['volume_name'],
                    'clonePath': self.bucket_path + '/' + volume['name'],
                    'snapName': snapshot['name']
                })
        except nexenta.NexentaException as e:
            LOG.error(_LE('Error cloning volume: %s') % unicode(e))
            raise

    def create_snapshot(self, snapshot):
        try:
            self.restapi.post(
                'service/' + self.iscsi_service + '/iscsi/snapshot',
                {
                    'objectPath': self.bucket_path + '/' +
                    snapshot['volume_name'],
                    'snapName': snapshot['name']
                })
        except nexenta.NexentaException as e:
            LOG.error(_LE('Error creating snapshot: %s') % unicode(e))
            raise

    def delete_snapshot(self, snapshot):
        try:
            self.restapi.delete(
                'service/' + self.iscsi_service + '/iscsi/snapshot',
                {
                    'objectPath': self.bucket_path + '/' +
                    snapshot['volume_name'],
                    'snapName': snapshot['name']
                })
        except nexenta.NexentaException as e:
            LOG.error(_LE('Error deleting snapshot: %s') % unicode(e))
            raise

    def create_cloned_volume(self, volume, src_vref):
        vol_url = self.bucket_url + '/objects/' + \
            src_vref['name'] + '/clone'
        clone_body = {
            'tenant_name': self.tenant,
            'bucket_name': self.bucket,
            'object_name': volume['name']
        }
        try:
            self.restapi.post(vol_url, clone_body)
            self.restapi.post('service/' + self.iscsi_service + '/iscsi', {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'volSizeMB': int(src_vref['size']) * 1024,
                'blockSize': self.LUN_BLOCKSIZE,
                'chunkSize': self.LUN_CHUNKSIZE,
            })
        except nexenta.NexentaException as e:
            LOG.error(_LE('Error creating cloned volume: %s') % unicode(e))
            raise

    def create_export(self, context, volume):
        return {'provider_location': self._get_provider_location(volume)}

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def initialize_connection(self, volume, connector):
        lunNumber = self._get_lun_number(volume['name'])

        target_portal = self._get_target_address(volume['name']) + ':' + \
            str(self.configuration.nexenta_iscsi_target_portal_port)
        return {
            'driver_volume_type': 'iscsi',
            'data': {
                'bucket_path': self.bucket_path,
                'target_discovered': True,
                'target_lun': lunNumber,
                'target_iqn': self.target_name,
                'target_portal': target_portal,
                'volume_id': volume['id'],
                'access_mode': 'rw'
            }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def local_path(self, volume):
        return self.bucket_path + '/' + volume['name']

    def backup_volume(self, context, backup, backup_service):
        raise NotImplementedError()

    def restore_backup(self, context, backup, volume, backup_service):
        raise NotImplementedError()

    def get_volume_stats(self, refresh=False):
        location_info = '%(driver)s:%(host)s:%(bucket)s' % {
            'driver': self.__class__.__name__,
            'host': self._get_target_address(None),
            'bucket': self.bucket_path
        }
        return {
            'vendor_name': 'Nexenta',
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'reserved_percentage': 0,
            'total_capacity_gb': 'infinite',
            'free_capacity_gb': 'infinite',
            'QoS_support': False,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': self.iscsi_target_portal_port,
            'restapi_url': self.restapi.url
        }
