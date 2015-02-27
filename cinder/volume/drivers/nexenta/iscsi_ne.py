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
:mod:`nexenta.iscsi` -- Driver to store volumes on Nexenta Appliance
=====================================================================
.. automodule:: nexenta.volume
.. moduleauthor:: Zohar Mamedov <zohar.mamedov@nexenta.com>
"""

from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.image import image_utils
from cinder.volume import driver
from cinder.volume.drivers import nexenta
from cinder.volume.drivers.nexenta import jsonrpc
from cinder.volume.drivers.nexenta import options

from oslo_serialization import jsonutils

import os
import base64
import tempfile

LOG = logging.getLogger(__name__)


class NexentaEdgeISCSIDriver(driver.ISCSIDriver):  # pylint: disable=R0921
    """Executes volume driver commands on Nexenta Edge cluster.
    Version history:
        1.0.0 - Initial driver version.
    """

    VERSION = '1.0.0'

    LUN_BLOCKSIZE = 512
    LUN_CHUNKSIZE = 131072

    def __init__(self, *args, **kwargs):
        super(NexentaEdgeISCSIDriver, self).__init__(*args, **kwargs)
        self.nms = None
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTIONS)
            self.configuration.append_config_values(
                options.NEXENTA_ISCSI_OPTIONS)
            self.configuration.append_config_values(
                options.NEXENTA_VOLUME_OPTIONS)
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
        self.restapi = jsonrpc.NexentaEdgeResourceProxy(
            protocol, self.restapi_host, self.restapi_port, '/',
            self.restapi_user, self.restapi_password, auto=auto)
        rsp = self.restapi.get('sysconfig/iscsi/status')
        self.target_name = rsp['value'].split('\n', 1)[0].split(' ')[2]

    def check_for_setup_error(self):
        self.restapi.get(self.bucket_url)

    def _get_provider_location(self, volume, namemap):
        number = 0
        if namemap is None:
            number = self._get_lun_from_name(volume['name'])
        else:
            number = namemap[volume['name']]
        return '%(host)s:%(port)s,1 %(name)s %(number)s' % {
            'host': self.restapi_host,
            'port': self.configuration.nexenta_iscsi_target_portal_port,
            'name': self.target_name,
            'number': number
        }

    def _get_bucket_name_map(self):
        rsp = self.restapi.get(self.bucket_url)
        if not (('bucketMetadata' in rsp) and
                ('X-Name-Map' in rsp['bucketMetadata'])):
            LOG.error(_('Bucket metadata missing name mapping'))
            raise nexenta.NexentaException('Bucket metadata ' +
                                           'missing name mapping')
        namemap = jsonutils.loads(rsp['bucketMetadata']['X-Name-Map'])
        return namemap

    def _set_bucket_name_map(self, namemap):
        self.restapi.put(
            self.bucket_url,
            {'optionsObject': {'X-Name-Map': jsonutils.dumps(namemap)}})

    def _verify_name_in_map(self, namemap, name):
        if not (name in namemap):
            LOG.error(_('Bucket metadata map missing volume name'))
            raise nexenta.NexentaException('Bucket metadata ' +
                                           'map missing volume name')

    def _get_lun_from_name(self, name):
        namemap = self._get_bucket_name_map()
        self._verify_name_in_map(namemap, name)
        return namemap[name]

    def _allocate_lun_number(self, namemap):
        if namemap is None:
            LOG.error(_('Failed to allocate LUN number: '
                        'Received None name_map object'))
            raise nexenta.NexentaException('None name_map object')
        lunNumber = None
        for i in range(1, 256):
            exists = False
            for k, v in namemap.iteritems():
                if i == v:
                    exists = True
                    break
            if not exists:
                lunNumber = i
                break
        if lunNumber is None:
            LOG.error(_('Failed to allocate LUN number: '
                        'All 255 lun numbers used, WOW!'))
            raise nexenta.NexentaException('All 255 lun numbers used')
        return lunNumber

    def create_volume(self, volume):
        lunNumber = 0
        try:
            namemap = self._get_bucket_name_map()
        except nexenta.NexentaException as e:
            if (str(e) == 'Bucket metadata missing name mapping'):
                namemap = {}
                lunNumber = 1
            else:
                raise

        if not lunNumber == 1:
            lunNumber = self._allocate_lun_number(namemap)

        try:
            self.restapi.post('iscsi', {
                'objectPath': self.bucket_path + '/' + str(lunNumber),
                'volSizeMB': int(volume['size']) * 1024,
                'blockSize': self.LUN_BLOCKSIZE,
                'chunkSize': self.LUN_CHUNKSIZE,
                'number': lunNumber
            })

            namemap[volume['name']] = lunNumber
            self._set_bucket_name_map(namemap)

        except nexenta.NexentaException as e:
            LOG.error(_('Error while creating volume: %s'), str(e))
            raise

        return {'provider_location': self._get_provider_location(volume,
                namemap)}

    def delete_volume(self, volume):
        namemap = self._get_bucket_name_map()
        self._verify_name_in_map(namemap, volume['name'])
        lunNumber = namemap[volume['name']]
        try:
            self.restapi.delete(
                'iscsi/' + str(lunNumber),
                {'objectPath': self.bucket_path + '/' + str(lunNumber)})

            namemap.pop(volume['name'])
            self._set_bucket_name_map(namemap)

        except nexenta.NexentaException as e:
            LOG.error(_('Error while deleting: %s'), str(e))
            raise

    def extend_volume(self, volume, new_size):
        lunNumber = self._get_lun_from_name(volume['name'])
        self.restapi.post(
            'iscsi/' + str(lunNumber) + '/resize',
            {'objectPath': self.bucket_path + '/' + str(lunNumber),
             'newSizeMB': new_size * 1024})

    def create_volume_from_snapshot(self, volume, snapshot):
        newLun = 0
        namemap = self._get_bucket_name_map()
        self._verify_name_in_map(namemap, snapshot['volume_name'])
        lunNumber = namemap[snapshot['volume_name']]

        newLun = self._allocate_lun_number(namemap)
        namemap[volume['name']] = newLun

        try:
            snap_url = self.bucket_url + '/snapviews/' + \
                str(lunNumber) + '.snapview/snapshots/' + snapshot['name']
            snap_body = {
                'ss_tenant': self.tenant,
                'ss_bucket': self.bucket,
                'ss_object': str(newLun)
            }
            self.restapi.post(snap_url, snap_body)

            self.restapi.post('iscsi', {
                'objectPath': self.bucket_path + '/' + str(newLun),
                'volSizeMB': int(snapshot['volume_size']) * 1024,
                'blockSize': self.LUN_BLOCKSIZE,
                'chunkSize': self.LUN_CHUNKSIZE,
                'number': newLun
            })

            self._set_bucket_name_map(namemap)

        except nexenta.NexentaException as e:
            LOG.error(_('Error while creating volume: %s'), str(e))
            raise

    def create_snapshot(self, snapshot):
        lunNumber = self._get_lun_from_name(snapshot['volume_name'])
        snap_url = self.bucket_url + \
            '/snapviews/' + str(lunNumber) + '.snapview'
        snap_body = {
            'ss_bucket': self.bucket,
            'ss_object': str(lunNumber),
            'ss_name': snapshot['name']
        }
        self.restapi.post(snap_url, snap_body)

    def delete_snapshot(self, snapshot):
        lunNumber = self._get_lun_from_name(snapshot['volume_name'])
        self.restapi.delete(
            self.bucket_url + '/snapviews/' + str(lunNumber) +
            '.snapview/snapshots/' + snapshot['name'])

    def create_cloned_volume(self, volume, src_vref):
        namemap = self._get_bucket_name_map()
        self._verify_name_in_map(namemap, src_vref['name'])

        vol_url = self.bucket_url + '/objects/' + \
            str(namemap[src_vref['name']]) + '/clone'
        newLun = self._allocate_lun_number(namemap)
        clone_body = {
            'tenant_name': self.tenant,
            'bucket_name': self.bucket,
            'object_name': str(newLun)
        }

        try:
            self.restapi.post(vol_url, clone_body)

            self.restapi.post('iscsi', {
                'objectPath': self.bucket_path + '/' + str(newLun),
                'volSizeMB': int(src_vref['size']) * 1024,
                'blockSize': self.LUN_BLOCKSIZE,
                'chunkSize': self.LUN_CHUNKSIZE,
                'number': newLun
            })

            namemap[volume['name']] = newLun
            self._set_bucket_name_map(namemap)

        except nexenta.NexentaException as e:
            LOG.error(_('Error creating cloned volume: %s'), str(e))
            raise

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        namemap = self._get_bucket_name_map()
        lunNumber = self._allocate_lun_number(namemap)
        with tempfile.NamedTemporaryFile(dir='/tmp') as tmp:
            image_utils.fetch_to_raw(context,
                                     image_service,
                                     image_id,
                                     tmp.name,
                                     self.configuration.volume_dd_blocksize,
                                     size=volume['size'])
            obj_f = open(tmp.name, "rb")
            for x in range(0, os.path.getsize(tmp.name) /
                           (self.LUN_CHUNKSIZE)):
                obj_data = obj_f.read(self.LUN_CHUNKSIZE)
                data64 = base64.b64encode(obj_data, None)
                payload = {'data': data64}
                url = self.bucket_url + '/objects/' + str(lunNumber) + \
                    '?offsetSize=' + str(x * self.LUN_CHUNKSIZE) + \
                    '?bufferSize=' + str(len(data64))
                try:
                    self.restapi.post(url, payload)
                except nexenta.NexentaException as e:
                    LOG.error(_('Error copying Image to Volume: %s'), str(e))
                    pass

        try:
            self.restapi.post('iscsi/' + str(lunNumber) + '/resize', {
                'objectPath': self.bucket_path + '/' + str(lunNumber),
                'newSizeMB': int(volume['size']) * 1024,
            })

            namemap[volume['name']] = lunNumber
            self._set_bucket_name_map(namemap)

        except nexenta.NexentaException as e:
            LOG.error(_('Error while creating Volume from Image: %s'), str(e))
            pass

    def create_export(self, context, volume):
        return {'provider_location': self._get_provider_location(volume, None)}

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def initialize_connection(self, volume, connector):
        lunNumber = self._get_lun_from_name(volume['name'])
        try:
            rsp = self.restapi.get('iscsi?number=' + str(lunNumber))
        except nexenta.NexentaException as e:
            raise

        target_portal = self.restapi_host + ':' + \
            str(self.configuration.nexenta_iscsi_target_portal_port)
        return {
            'driver_volume_type': 'iscsi',
            'data': {
                'bucket_path': self.bucket_path,
                'target_discovered': True,
                'target_lun': rsp['luns'][0]['number'],
                'target_iqn': self.target_name,
                'target_portal': target_portal,
                'volume_id': volume['id'],
                'access_mode': 'rw'
            }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def local_path(self, volume):
        return self.bucket_path + '/' + \
            str(self._get_lun_from_name(volume['name']))

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
