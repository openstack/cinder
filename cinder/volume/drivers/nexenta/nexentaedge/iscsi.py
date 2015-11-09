# Copyright 2015 Nexenta Systems, Inc.
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

from cinder import exception
from cinder.i18n import _, _LE
from cinder.volume import driver
from cinder.volume.drivers.nexenta.nexentaedge import jsonrpc


nexenta_edge_opts = [
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
               help='NexentaEdge iSCSI Gateway client '
               'address for non-VIP service'),
    cfg.StrOpt('nexenta_blocksize',
               default=4096,
               help='NexentaEdge iSCSI LUN block size'),
    cfg.StrOpt('nexenta_chunksize',
               default=16384,
               help='NexentaEdge iSCSI LUN object chunk size')
]

CONF = cfg.CONF
CONF.register_opts(nexenta_edge_opts)

LOG = logging.getLogger(__name__)


class NexentaEdgeISCSIDriver(driver.ISCSIDriver):
    """Executes volume driver commands on NexentaEdge cluster.

    Version history:
        1.0.0 - Initial driver version.
    """

    VERSION = '1.0.0'

    def __init__(self, *args, **kwargs):
        super(NexentaEdgeISCSIDriver, self).__init__(*args, **kwargs)
        if self.configuration:
            self.configuration.append_config_values(nexenta_edge_opts)
        self.restapi_protocol = self.configuration.nexenta_rest_protocol
        self.restapi_host = self.configuration.nexenta_rest_address
        self.restapi_port = self.configuration.nexenta_rest_port
        self.restapi_user = self.configuration.nexenta_rest_user
        self.restapi_password = self.configuration.nexenta_rest_password
        self.iscsi_service = self.configuration.nexenta_iscsi_service
        self.bucket_path = self.configuration.nexenta_lun_container
        self.blocksize = self.configuration.nexenta_blocksize
        self.chunksize = self.configuration.nexenta_chunksize
        self.cluster, self.tenant, self.bucket = self.bucket_path.split('/')
        self.bucket_url = ('clusters/' + self.cluster + '/tenants/' +
                           self.tenant + '/buckets/' + self.bucket)
        self.iscsi_target_port = (self.configuration.
                                  nexenta_iscsi_target_portal_port)
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
            data_keys = rsp['data'][list(rsp['data'].keys())[0]]
            self.target_name = data_keys.split('\n', 1)[0].split(' ')[2]

            rsp = self.restapi.get('service/' + self.iscsi_service)
            if 'X-VIPS' in rsp['data']:
                vips = json.loads(rsp['data']['X-VIPS'])
                if len(vips[0]) == 1:
                    self.target_vip = vips[0][0]['ip'].split('/', 1)[0]
                else:
                    self.target_vip = vips[0][1]['ip'].split('/', 1)[0]
            else:
                self.target_vip = self.configuration.safe_get(
                    'nexenta_client_address')
                if not self.target_vip:
                    LOG.error(_LE('No VIP configured for service %s'),
                              self.iscsi_service)
                    raise exception.VolumeBackendAPIException(
                        _('No service VIP configured and '
                          'no nexenta_client_address'))
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error verifying iSCSI service %(serv)s on '
                              'host %(hst)s'), {'serv': self.iscsi_service,
                              'hst': self.restapi_host})

    def check_for_setup_error(self):
        try:
            self.restapi.get(self.bucket_url + '/objects/')
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error verifying LUN container %(bkt)s'),
                              {'bkt': self.bucket_path})

    def _get_lun_number(self, volname):
        try:
            rsp = self.restapi.put(
                'service/' + self.iscsi_service + '/iscsi/number',
                {
                    'objectPath': self.bucket_path + '/' + volname
                })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error retrieving LUN %(vol)s number'),
                              {'vol': volname})

        return rsp['data']

    def _get_target_address(self, volname):
        return self.target_vip

    def _get_provider_location(self, volume):
        return '%(host)s:%(port)s,1 %(name)s %(number)s' % {
            'host': self._get_target_address(volume['name']),
            'port': self.iscsi_target_port,
            'name': self.target_name,
            'number': self._get_lun_number(volume['name'])
        }

    def create_volume(self, volume):
        try:
            self.restapi.post('service/' + self.iscsi_service + '/iscsi', {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'volSizeMB': int(volume['size']) * units.Ki,
                'blockSize': self.blocksize,
                'chunkSize': self.chunksize
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating volume'))

    def delete_volume(self, volume):
        try:
            self.restapi.delete('service/' + self.iscsi_service +
                                '/iscsi', {'objectPath': self.bucket_path +
                                           '/' + volume['name']})
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error deleting volume'))

    def extend_volume(self, volume, new_size):
        try:
            self.restapi.put('service/' + self.iscsi_service + '/iscsi/resize',
                             {'objectPath': self.bucket_path +
                              '/' + volume['name'],
                              'newSizeMB': new_size * units.Ki})
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error extending volume'))

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
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error cloning volume'))

    def create_snapshot(self, snapshot):
        try:
            self.restapi.post(
                'service/' + self.iscsi_service + '/iscsi/snapshot',
                {
                    'objectPath': self.bucket_path + '/' +
                    snapshot['volume_name'],
                    'snapName': snapshot['name']
                })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating snapshot'))

    def delete_snapshot(self, snapshot):
        try:
            self.restapi.delete(
                'service/' + self.iscsi_service + '/iscsi/snapshot',
                {
                    'objectPath': self.bucket_path + '/' +
                    snapshot['volume_name'],
                    'snapName': snapshot['name']
                })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error deleting snapshot'))

    def create_cloned_volume(self, volume, src_vref):
        vol_url = (self.bucket_url + '/objects/' +
                   src_vref['name'] + '/clone')
        clone_body = {
            'tenant_name': self.tenant,
            'bucket_name': self.bucket,
            'object_name': volume['name']
        }
        try:
            self.restapi.post(vol_url, clone_body)
            self.restapi.post('service/' + self.iscsi_service + '/iscsi', {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'volSizeMB': int(src_vref['size']) * units.Ki,
                'blockSize': self.blocksize,
                'chunkSize': self.chunksize
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating cloned volume'))

    def create_export(self, context, volume, connector=None):
        return {'provider_location': self._get_provider_location(volume)}

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def local_path(self, volume):
        raise NotImplementedError

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
            'total_capacity_gb': 'unknown',
            'free_capacity_gb': 'unknown',
            'QoS_support': False,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': self.iscsi_target_port,
            'restapi_url': self.restapi.url
        }
