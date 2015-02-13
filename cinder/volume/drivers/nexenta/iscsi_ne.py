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

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers import nexenta
from cinder.volume.drivers.nexenta import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils

import os
import base64


class NexentaEdgeISCSIDriver(driver.ISCSIDriver):  # pylint: disable=R0921
    """Executes volume driver commands on Nexenta Edge cluster.
    Version history:
        1.0.0 - Initial driver version.
    """

    VERSION = '1.0.0'

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
            self.tenant + '/buckets'
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

    def check_for_setup_error(self):
        self.restapi.get(self.bucket_url, {'bucketName':self.bucket})

    def _get_provider_location(self, volume):
        return '%(host)s:%(port)s,1 %(name)s' % {
            'host': self.restapi_host,
            'port': self.configuration.nexenta_iscsi_target_portal_port,
            'name': self.configuration.nexenta_target_prefix
        }

    def create_volume(self, volume):
        lunNumber = volume['name'] #FIXME - need name <-> number mapping
        try:
            rsp = self.restapi.post('iscsi', {
                'objectPath' : self.bucket_path + '/' + lunNumber,
                'volSizeMB' : int(volume['size']) * 1024,
                'blockSize' : 4096,
                'chunkSize' : 4096,
                'number'    : lunNumber
            })
        except nexenta.NexentaException, e:
            LOG.error(_('Error while creating volume: %s'), str(e))
            return
        return {'provider_location': self._get_provider_location(volume)}

    def delete_volume(self, volume):
        lunNumber = volume['name'] #FIXME - need name <-> number mapping
        try:
            rsp = self.restapi.delete('iscsi/' + lunNumber, None) 
        except nexenta.NexentaException, e:
            LOG.error(_('Error while deleting: %s'), str(e))
            pass

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        pass

    def create_volume_from_snapshot(self, volume, snapshot):
        lunNumber = snapshot['volume_name'] #FIXME name - number mapping
        newLunNumber = lunNumber + 1 #FIXME
        snap_url = self.bucket_url + '/' + self.bucket + '/snapviews/' + \
            lunNumber + '.snapview/snapshots/' + snapshot['name']
        snap_body = { 'ss_tenant' : self.tenant,
                      'ss_bucket' : self.bucket,
                      'ss_object' : str(newLunNumber)
            }
        rsp = self.restapi.post(snap_url, snap_body)

        try:
            rsp = self.restapi.post('iscsi', {
                'objectPath' : self.bucket_path + '/' + newLunNumber,
                'volSizeMB' : int(snapshot['volume_size']) * 1024,
                'blockSize' : 4096,
                'chunkSize' : 4096
            })
        except nexenta.NexentaException, e:
            LOG.error(_('Error while creating volume: %s'), str(e))
            return

    def create_snapshot(self, snapshot):
        lunNumber = snapshot['volume_name'] #FIXME name - number mapping
        snap_url = self.bucket_url + '/' + self.bucket + \
            '/snapviews/' + lunNumber + '.snapview'
        snap_body = { 'ss_bucket' : self.bucket,
                      'ss_object' : lunNumber,
                      'ss_name' : snapshot['name']
            }
        rsp = self.restapi.post(snap_url, snap_body)

    def delete_snapshot(self, snapshot):
        lunNumber = snapshot['volume_name'] #FIXME name - number mapping
        try:
            rsp = self.restapi.delete(self.bucket_url + '/' + \
                self.bucket + '/snapviews/' + lunNumber + \
                 '.snapview/snapshots/' + snapshot['name'])
        except nexenta.NexentaException, e:
            LOG.error(_('Error while deleting snapshot: %s'), str(e))
            pass

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        vol_url = self.bucket_url + '/objects/' + src_vref['volume_name']
        clone_body = { 'tenant_name' : self.tenant,
                      'bucket_name' : self.bucket,
                      'object_name' : volume['name']
            }

        try:
            rsp = self.restapi.post(vol_url, clone_body)
        except nexenta.NexentaException, e:
            LOG.error(_('Error while cloning Volume from Volume: %s'), str(e))
            pass


    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume.
        Can optionally return a Dictionary of changes to the volume
        object to be persisted.
        """
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        rsp = self.restapi.get('iscsi?number=' + lunNumber, None)

        return {
            'driver_volume_type': 'iscsi',
            'data': {
                'bucket_path': self.bucket_path,
                'target_discovered': True,
                'target_lun': rsp['luns'][0]['number'],
                'target_iqn': self.configuration.nexenta_target_prefix,
                'target_portal': self.restapi_host + ':' + str(self.configuration.nexenta_iscsi_target_portal_port),
                'volume_id': volume['id'],
                'access_mode': 'rw'
            }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        pass

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume. """
        tmp_dir = '/tmp' #self.configuration.volume_tmp_dir
        with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp:
            image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 tmp.name,
                                 self.configuration.volume_dd_blocksize,
                                 size=volume['size'])
            obj_f = open(tmp.name, "rb")
            chunkSize = 128 * 4096 
            for x in range (0, os.path.getsize(tmp.name) / (chunkSize)):
                obj_data = obj_f.read(chunkSize)
                data64 = base64.b64encode(obj_data, None)
                payload = { 'data' : data64 }
                url = self.bucket_url + '/' + self.bucket + '/objects/' + volume['name'] + '?offsetSize=' + str(x *chunkSize) + '?bufferSize=' + str(len(data64))
                try:
                    rsp = self.restapi.post(url, payload)
                except nexenta.NexentaException, e:
                    LOG.error(_('Error while copying Image to Volume: %s'), str(e))
                    pass
        
        try:
            rsp = self.restapi.post('iscsi/-1/resize', {
                'objectPath' : self.bucket_path + '/' + volume['name'],
                'newSizeMB' : int(volume['size']) * 1024,
            })
        except nexenta.NexentaException, e:
            LOG.error(_('Error while creating Volume from Image: %s'), str(e))
            pass
        '''image_id is vol.img  && must be our predefined name, else exc
        clone /cltest/test/bk1/vol.img -> clone_body.
        image_meta = image_service.show(context, image_id)
        if image_meta['name'] != 'p_linux':
            vol_img = image_meta['name']
        else:
        vol_img = "vol.img"
        vol_url = self.bucket_url + '/' + self.bucket  + '/objects/' + vol_img 
        clone_body = { 'tenant_name' : self.tenant,
                      'bucket_name' : self.bucket,
                      'object_name' : volume['name']
            }
        try:
            rsp = self.restapi.post(vol_url, clone_body)
            rsp = self.restapi.post('iscsi/-1/resize', {
                'objectPath' : self.bucket_path + '/' + volume['name'],
                'newSizeMB' : int(volume['size']) * 1024,
            })
        except nexenta.NexentaException, e:
            LOG.error(_('Error while creating Volume from Image: %s'), str(e))
            pass
        '''

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        image_utils.upload_volume(context,
                                  image_service,
                                  image_meta,
                                  self.local_path(volume))

    def local_path(self, volume):
        """Return local path to existing local volume.
        """
        #return self.bucket_url + "/bk1/volumes/" + volume['name']
        return '/v1/' + self.tenant + '/' + self.bucket + '/' + volume['name'] 

    def clone_image(self, volume, image_location, image_id, image_meta):
        """Create a volume efficiently from an existing image.
        image_location is a string whose format depends on the
        image service backend in use. The driver should use it
        to determine whether cloning is possible.
        image_id is a string which represents id of the image.
        It can be used by the driver to introspect internal
        stores or registry to do an efficient image clone.
        Returns a dict of volume properties eg. provider_location,
        boolean indicating whether cloning occurred
        """
        return None, False

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume."""
        raise NotImplementedError()

    def restore_backup(self, context, backup, volume, backup_service):
        """Restore an existing backup to a new or existing volume."""
        raise NotImplementedError()

    def get_volume_stats(self, refresh=False):
        """Get volume stats.
        If 'refresh' is True, run update the stats first.
        """

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
