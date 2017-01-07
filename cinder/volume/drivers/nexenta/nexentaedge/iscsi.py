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

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.nexenta.nexentaedge import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils as nexenta_utils


LOG = logging.getLogger(__name__)


@interface.volumedriver
class NexentaEdgeISCSIDriver(driver.ISCSIDriver):
    """Executes volume driver commands on NexentaEdge cluster.

    Version history:
        1.0.0 - Initial driver version.
        1.0.1 - Moved opts to options.py.
        1.0.2 - Added HA support.
    """

    VERSION = '1.0.2'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Nexenta_Edge_CI"

    # TODO(smcginnis) Either remove this if CI requirements are met, or
    # remove this driver in the Pike release per normal deprecation
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        super(NexentaEdgeISCSIDriver, self).__init__(*args, **kwargs)
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_ISCSI_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_DATASET_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_EDGE_OPTS)
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
        self.ha_vip = None

    @property
    def backend_name(self):
        backend_name = None
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = self.__class__.__name__
        return backend_name

    def do_setup(self, context):
        def get_ip(host):
            hm = host[0 if len(host) == 1 else 1]['ip'].split('/', 1)
            return {
                'ip': hm[0],
                'mask': hm[1] if len(hm) > 1 else '32'
            }

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

            target_vip = self.configuration.safe_get(
                'nexenta_client_address')
            rsp = self.restapi.get('service/' + self.iscsi_service)
            if 'X-VIPS' in rsp['data']:
                vips = json.loads(rsp['data']['X-VIPS'])
                vips = [get_ip(host) for host in vips]
                if target_vip:
                    found = False
                    for host in vips:
                        if target_vip == host['ip']:
                            self.ha_vip = '/'.join((host['ip'], host['mask']))
                            found = True
                            break
                    if not found:
                        raise exception.VolumeBackendAPIException(
                            message=_("nexenta_client_address doesn't match "
                                      "any VIPs provided by service: {}"
                                      ).format(
                                ", ".join([host['ip'] for host in vips])))
                else:
                    if len(vips) == 1:
                        target_vip = vips[0]['ip']
                        self.ha_vip = '/'.join(
                            (vips[0]['ip'], vips[0]['mask']))
            if not target_vip:
                LOG.error(_LE('No VIP configured for service %s'),
                          self.iscsi_service)
                raise exception.VolumeBackendAPIException(
                    message=_('No service VIP configured and '
                              'no nexenta_client_address'))
            self.target_vip = target_vip
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
        data = {
            'objectPath': self.bucket_path + '/' + volume['name'],
            'volSizeMB': int(volume['size']) * units.Ki,
            'blockSize': self.blocksize,
            'chunkSize': self.chunksize
        }
        if self.ha_vip:
            data['vip'] = self.ha_vip
        try:
            self.restapi.post('service/' + self.iscsi_service + '/iscsi', data)
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating volume'))

    def delete_volume(self, volume):
        try:
            self.restapi.delete('service/' + self.iscsi_service +
                                '/iscsi', {'objectPath': self.bucket_path +
                                           '/' + volume['name']})
        except exception.VolumeBackendAPIException:
            LOG.info(
                _LI('Volume was already deleted from appliance, skipping.'),
                resource=volume)

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
        if volume['size'] > src_vref['size']:
            self.extend_volume(volume, volume['size'])

    def create_export(self, context, volume, connector=None):
        return {'provider_location': self._get_provider_location(volume)}

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def local_path(self, volume):
        raise NotImplementedError

    def get_volume_stats(self, refresh=False):
        resp = self.restapi.get('system/stats')
        summary = resp['stats']['summary']
        total = nexenta_utils.str2gib_size(summary['total_capacity'])
        free = nexenta_utils.str2gib_size(summary['total_available'])

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
            'total_capacity_gb': total,
            'free_capacity_gb': free,
            'QoS_support': False,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': self.iscsi_target_port,
            'restapi_url': self.restapi.url
        }
