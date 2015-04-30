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

from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers import nexenta
from cinder.volume.drivers.nexenta.nexentaedge import jsonrpc_ne as jsonrpc

LOG = logging.getLogger(__name__)

from oslo_config import cfg

NEXENTA_EDGE_OPTIONS = [
    cfg.StrOpt('nexenta_host',
               default='',
               help='IP address of NexentaEdge host'),
    cfg.IntOpt('nexenta_rest_port',
               default=8080,
               help='HTTP port to connect to Nexenta REST API server'),
    cfg.StrOpt('nexenta_rest_protocol',
               default='auto',
               help='Use http or https for REST connection (default auto)'),
    cfg.IntOpt('nexenta_iscsi_target_portal_port',
               default=3260,
               help='NexentaEdge target portal port'),
    cfg.StrOpt('nexenta_user',
               default='admin',
               help='User name to connect to NexentaEdge'),
    cfg.StrOpt('nexenta_password',
               default='nexenta',
               help='Password to connect to NexentaEdge',
               secret=True),
    cfg.StrOpt('nexenta_bucket',
               default='',
               help='NexentaEdge logical path of bucket for LUNs'),
    cfg.StrOpt('nexenta_service',
               default='',
               help='NexentaEdge iSCSI service name')
]

cfg.CONF.register_opts(NEXENTA_EDGE_OPTIONS)

# placeholder text formatting handler
def __(text):
    return text

class NexentaEdgeISCSIDriver(driver.ISCSIDriver):  # pylint: disable=R0921
    """Executes volume driver commands on NexentaEdge cluster.
    Version history:
        1.0.0 - Initial driver version.
    """

    VERSION = '1.0.0'

    LUN_BLOCKSIZE = 512
    LUN_CHUNKSIZE = 131072

    def __init__(self, *args, **kwargs):
        super(NexentaEdgeISCSIDriver, self).__init__(*args, **kwargs)
        if self.configuration:
            self.configuration.append_config_values(NEXENTA_EDGE_OPTIONS)
        self.restapi_protocol = self.configuration.nexenta_rest_protocol
        self.restapi_host = self.configuration.nexenta_host
        self.restapi_port = self.configuration.nexenta_rest_port
        self.restapi_user = self.configuration.nexenta_user
        self.restapi_password = self.configuration.nexenta_password
        self.bucket_path = self.configuration.nexenta_volume
        self.cluster, self.tenant, self.bucket = self.bucket_path.split('/')
        self.bucket_url = 'clusters/' + self.cluster + '/tenants/' + \
            self.tenant + '/buckets/' + self.bucket
        self.iscsi_target_portal_port = \
            self.configuration.nexenta_iscsi_target_portal_port

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

        self.restapi = jsonrpc.NexentaEdgeJSONProxy(
            protocol, self.restapi_host, self.restapi_port, '/',
            self.restapi_user, self.restapi_password, auto=auto)

        try:
            rsp = self.restapi.get('sysconfig/iscsi/status')
        except Exception as exc:
            LOG.error(__('Error reaching NexentaEdge host: %s') % self.restapi_host)
            LOG.error(str(exc));
            return exc

        self.target_name = rsp['value'].split('\n', 1)[0].split(' ')[2]

    def check_for_setup_error(self):
        self.restapi.get(self.bucket_url)

    def _get_lun_from_name(self, name):
        rsp = self.restapi.put('service/SVC/iscsi/number', {
            'objectPath': self.bucket_path + '/' + name
        });
        return rsp['number']

    def _get_provider_location(self, volume):
        return '%(host)s:%(port)s,1 %(name)s %(number)s' % {
            'host': self.restapi_host,
            'port': self.configuration.nexenta_iscsi_target_portal_port,
            'name': self.target_name,
            'number': self._get_lun_from_name(volume['name'])
        }

    def create_volume(self, volume):
        try:
            self.restapi.post('iscsi', {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'volSizeMB': int(volume['size']) * 1024,
                'blockSize': self.LUN_BLOCKSIZE,
                'chunkSize': self.LUN_CHUNKSIZE
            })

        except nexenta.NexentaException as e:
            LOG.error(__('Error while creating volume: %s') % unicode(e))
            raise

        return {'provider_location': self._get_provider_location(volume)}

    def delete_volume(self, volume):
        try:
            self.restapi.delete('iscsi',
                {'objectPath': self.bucket_path + '/' + volume['name']})

        except nexenta.NexentaException as e:
            LOG.error(__('Error while deleting: %s') % unicode(e))
            raise

    def extend_volume(self, volume, new_size):
        self.restapi.post('iscsi/resize',
            {'objectPath': self.bucket_path + '/' + volume['name'],
             'newSizeMB': new_size * 1024})

    def create_volume_from_snapshot(self, volume, snapshot):
        try:
            snap_url = self.bucket_url + '/snapviews/' + \
                snapshot['volume_name'] + '.snapview/snapshots/' + snapshot['name']
            snap_body = {
                'ss_tenant': self.tenant,
                'ss_bucket': self.bucket,
                'ss_object': volume['name']
            }
            self.restapi.post(snap_url, snap_body)

            self.restapi.post('iscsi', {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'volSizeMB': int(snapshot['volume_size']) * 1024,
                'blockSize': self.LUN_BLOCKSIZE,
                'chunkSize': self.LUN_CHUNKSIZE
            })

        except nexenta.NexentaException as e:
            LOG.error(__('Error while creating volume: %s') % unicode(e))
            raise

    def create_snapshot(self, snapshot):
        snap_url = self.bucket_url + \
            '/snapviews/' + snapshot['volume_name'] + '.snapview'
        snap_body = {
            'ss_bucket': self.bucket,
            'ss_object': snapshot['volume_name'],
            'ss_name': snapshot['name']
        }
        self.restapi.post(snap_url, snap_body)

    def delete_snapshot(self, snapshot):
        self.restapi.delete(
            self.bucket_url + '/snapviews/' + snapshot['volume_name'] +
            '.snapview/snapshots/' + snapshot['name'])

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

            self.restapi.post('iscsi', {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'volSizeMB': int(src_vref['size']) * 1024,
                'blockSize': self.LUN_BLOCKSIZE,
                'chunkSize': self.LUN_CHUNKSIZE,
            })

        except nexenta.NexentaException as e:
            LOG.error(__('Error creating cloned volume: %s') % unicode(e))
            raise

    def create_export(self, context, volume):
        return {'provider_location': self._get_provider_location(volume)}

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def initialize_connection(self, volume, connector):
        lunNumber = self._get_lun_from_name(volume['name'])

        target_portal = self.restapi_host + ':' + \
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
            'host': self.restapi_host,
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
