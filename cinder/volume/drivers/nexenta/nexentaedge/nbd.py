# Copyright 2016 Nexenta Systems, Inc.
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
import os
import six
import socket

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder.image import image_utils
from cinder import interface
from cinder import utils as cinder_utils
from cinder.volume import driver
from cinder.volume.drivers.nexenta.nexentaedge import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils as nexenta_utils
from cinder.volume import utils as volutils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class NexentaEdgeNBDDriver(driver.VolumeDriver):
    """Executes commands relating to NBD Volumes.

    Version history:
        1.0.0 - Initial driver version.
    """

    VERSION = '1.0.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Nexenta_Edge_CI"

    def __init__(self, vg_obj=None, *args, **kwargs):
        LOG.debug('NexentaEdgeNBDDriver. Trying to initialize.')
        super(NexentaEdgeNBDDriver, self).__init__(*args, **kwargs)

        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_DATASET_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_EDGE_OPTS)
        self.restapi_protocol = self.configuration.nexenta_rest_protocol
        self.restapi_host = self.configuration.nexenta_rest_address
        self.restapi_port = self.configuration.nexenta_rest_port
        self.restapi_user = self.configuration.nexenta_rest_user
        self.restapi_password = self.configuration.nexenta_rest_password
        self.bucket_path = self.configuration.nexenta_lun_container
        self.blocksize = self.configuration.nexenta_blocksize
        self.chunksize = self.configuration.nexenta_chunksize
        self.cluster, self.tenant, self.bucket = self.bucket_path.split('/')
        self.bucket_url = ('clusters/' + self.cluster + '/tenants/' +
                           self.tenant + '/buckets/' + self.bucket)
        self.hostname = socket.gethostname()
        self.symlinks_dir = self.configuration.nexenta_nbd_symlinks_dir
        self.reserved_percentage = self.configuration.reserved_percentage
        LOG.debug('NexentaEdgeNBDDriver. Initialized successfully.')

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
            protocol, self.restapi_host, self.restapi_port, '',
            self.restapi_user, self.restapi_password, auto=auto)

    def check_for_setup_error(self):
        try:
            if not self.symlinks_dir:
                msg = _("nexenta_nbd_symlinks_dir option is not specified")
                raise exception.NexentaException(message=msg)
            if not os.path.exists(self.symlinks_dir):
                msg = _("NexentaEdge NBD symlinks directory doesn't exist")
                raise exception.NexentaException(message=msg)
            self.restapi.get(self.bucket_url + '/objects/')
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error verifying container %(bkt)s'),
                              {'bkt': self.bucket_path})

    def _get_nbd_devices(self, host):
        try:
            rsp = self.restapi.get('sysconfig/nbd/devices' +
                                   self._get_remote_url(host))
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error getting NBD list'))
        return json.loads(rsp['value'])

    def _get_nbd_number(self, volume):
        host = volutils.extract_host(volume['host'], 'host')
        nbds = self._get_nbd_devices(host)
        for dev in nbds:
            if dev['objectPath'] == self.bucket_path + '/' + volume['name']:
                return dev['number']
        return -1

    def _get_host_info(self, host):
        try:
            res = self.restapi.get('system/stats')
            servers = res['stats']['servers']
            for sid in servers:
                if host == sid or host == servers[sid]['hostname']:
                    return servers[sid]
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error getting host info'))
        raise exception.VolumeBackendAPIException(
            data=_('No %s hostname in NEdge cluster') % host)

    def _get_remote_url(self, host):
        return '?remote=' + (
            six.text_type(self._get_host_info(host)['ipv6addr']))

    def _get_symlink_path(self, number):
        return os.path.join(self.symlinks_dir, 'nbd' + six.text_type(number))

    def local_path(self, volume):
        number = self._get_nbd_number(volume)
        if number == -1:
            msg = _('No NBD device for volume %s') % volume['name']
            raise exception.VolumeBackendAPIException(data=msg)
        return self._get_symlink_path(number)

    def create_volume(self, volume):
        LOG.debug('Create volume')
        host = volutils.extract_host(volume['host'], 'host')
        try:
            self.restapi.post('nbd' + self._get_remote_url(host), {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'volSizeMB': int(volume['size']) * units.Ki,
                'blockSize': self.blocksize,
                'chunkSize': self.chunksize
            })
            number = self._get_nbd_number(volume)
            cinder_utils.execute(
                'ln', '--symbolic', '--force',
                '/dev/nbd' + six.text_type(number),
                self._get_symlink_path(number), run_as_root=True,
                check_exit_code=True)
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating volume'))

    def delete_volume(self, volume):
        LOG.debug('Delete volume')
        number = self._get_nbd_number(volume)
        if number == -1:
            LOG.info(_LI('Volume %(volume)s does not exist at %(path)s '
                         'path') % {
                'volume': volume['name'],
                'path': self.bucket_path
            })
            return
        host = volutils.extract_host(volume['host'], 'host')
        try:
            self.restapi.delete('nbd' + self._get_remote_url(host), {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'number': number
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error deleting volume'))

    def extend_volume(self, volume, new_size):
        LOG.debug('Extend volume')
        host = volutils.extract_host(volume['host'], 'host')
        try:
            self.restapi.put('nbd/resize' + self._get_remote_url(host), {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'newSizeMB': new_size * units.Ki
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error extending volume'))

    def create_snapshot(self, snapshot):
        LOG.debug('Create snapshot')
        try:
            self.restapi.post('nbd/snapshot', {
                'objectPath': self.bucket_path + '/' + snapshot['volume_name'],
                'snapName': snapshot['name']
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating snapshot'))

    def delete_snapshot(self, snapshot):
        LOG.debug('Delete snapshot')
        # There is no way to figure out whether a snapshot exists in current
        # version of the API. This REST function always reports OK even a
        # snapshot doesn't exist.
        try:
            self.restapi.delete('nbd/snapshot', {
                'objectPath': self.bucket_path + '/' + snapshot['volume_name'],
                'snapName': snapshot['name']
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error deleting snapshot'))

    def create_volume_from_snapshot(self, volume, snapshot):
        LOG.debug('Create volume from snapshot')
        host = volutils.extract_host(volume['host'], 'host')
        remotehost = self._get_remote_url(host)
        try:
            self.restapi.put('nbd/snapshot/clone' + remotehost, {
                'objectPath': self.bucket_path + '/' + snapshot['volume_name'],
                'snapName': snapshot['name'],
                'clonePath': self.bucket_path + '/' + volume['name']
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error cloning snapshot'))
        if volume['size'] > snapshot['volume_size']:
            self.extend_volume(volume, volume['size'])

    def create_cloned_volume(self, volume, src_vref):
        LOG.debug('Create cloned volume')
        vol_url = (self.bucket_url + '/objects/' +
                   src_vref['name'] + '/clone')
        clone_body = {
            'tenant_name': self.tenant,
            'bucket_name': self.bucket,
            'object_name': volume['name']
        }
        host = volutils.extract_host(volume['host'], 'host')
        size = volume['size'] if volume['size'] > src_vref['size'] else (
            src_vref['size'])
        try:
            self.restapi.post(vol_url, clone_body)
            self.restapi.post('nbd' + self._get_remote_url(host), {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'volSizeMB': int(size) * units.Ki,
                'blockSize': self.blocksize,
                'chunkSize': self.chunksize
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating cloned volume'))

    def migrate_volume(self, ctxt, volume, host, thin=False, mirror_count=0):
        raise NotImplementedError

    def get_volume_stats(self, refresh=False):
        LOG.debug('Get volume stats')
        try:
            resp = self.restapi.get('system/stats')
            location_info = '%(driver)s:%(host)s:%(bucket)s' % {
                'driver': self.__class__.__name__,
                'host': self.hostname,
                'bucket': self.bucket_path
            }
            summary = resp['stats']['summary']
            total = nexenta_utils.str2gib_size(summary['total_capacity'])
            free = nexenta_utils.str2gib_size(summary['total_available'])
            return {
                'vendor_name': 'Nexenta',
                'driver_version': self.VERSION,
                'storage_protocol': 'NBD',
                'reserved_percentage': self.reserved_percentage,
                'total_capacity_gb': total,
                'free_capacity_gb': free,
                'QoS_support': False,
                'volume_backend_name': self.backend_name,
                'location_info': location_info,
                'restapi_url': self.restapi.url
            }
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating snapshot'))

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        LOG.debug('Copy image to volume')
        image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 self.local_path(volume),
                                 self.configuration.volume_dd_blocksize,
                                 size=volume['size'])

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        LOG.debug('Copy volume to image')
        image_utils.upload_volume(context,
                                  image_service,
                                  image_meta,
                                  self.local_path(volume))

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector, vg=None):
        pass

    def remove_export(self, context, volume):
        pass

    def validate_connector(self, connector):
        LOG.debug('Validate connector')
        try:
            res = self.restapi.get('system/stats')
            servers = res['stats']['servers']
            for sid in servers:
                if (connector['host'] == sid or
                        connector['host'] == servers[sid]['hostname']):
                    return
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error retrieving cluster stats'))
        raise exception.VolumeBackendAPIException(
            data=_('No %s hostname in NEdge cluster') % connector['host'])

    def initialize_connection(self, volume, connector, initiator_data=None):
        LOG.debug('Initialize connection')
        return {
            'driver_volume_type': 'local',
            'data': {'device_path': self.local_path(volume)},
        }
