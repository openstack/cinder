# Copyright (c) 2014 Cloudbase Solutions SRL
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


import os
import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LI
from cinder.image import image_utils
from cinder.volume.drivers import remotefs as remotefs_drv
from cinder.volume.drivers import smbfs
from cinder.volume.drivers.windows import remotefs
from cinder.volume.drivers.windows import vhdutils
from cinder.volume.drivers.windows import windows_utils

VERSION = '1.1.0'

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.set_default('smbfs_shares_config', r'C:\OpenStack\smbfs_shares.txt')
CONF.set_default('smbfs_allocation_info_file_path',
                 r'C:\OpenStack\allocation_data.txt')
CONF.set_default('smbfs_mount_point_base', r'C:\OpenStack\_mnt')
CONF.set_default('smbfs_default_volume_format', 'vhd')


class WindowsSmbfsDriver(smbfs.SmbfsDriver):
    VERSION = VERSION
    _MINIMUM_QEMU_IMG_VERSION = '1.6'

    def __init__(self, *args, **kwargs):
        super(WindowsSmbfsDriver, self).__init__(*args, **kwargs)
        self.base = getattr(self.configuration,
                            'smbfs_mount_point_base',
                            CONF.smbfs_mount_point_base)
        opts = getattr(self.configuration,
                       'smbfs_mount_options',
                       CONF.smbfs_mount_options)
        self._remotefsclient = remotefs.WindowsRemoteFsClient(
            'cifs', root_helper=None, smbfs_mount_point_base=self.base,
            smbfs_mount_options=opts)
        self.vhdutils = vhdutils.VHDUtils()
        self._windows_utils = windows_utils.WindowsUtils()

    def do_setup(self, context):
        self._check_os_platform()
        super(WindowsSmbfsDriver, self).do_setup(context)

    def _check_os_platform(self):
        if sys.platform != 'win32':
            _msg = _("This system platform (%s) is not supported. This "
                     "driver supports only Win32 platforms.") % sys.platform
            raise exception.SmbfsException(_msg)

    def _do_create_volume(self, volume):
        volume_path = self.local_path(volume)
        volume_format = self.get_volume_format(volume)
        volume_size_bytes = volume['size'] * units.Gi

        if os.path.exists(volume_path):
            err_msg = _('File already exists at: %s') % volume_path
            raise exception.InvalidVolume(err_msg)

        if volume_format not in (self._DISK_FORMAT_VHD,
                                 self._DISK_FORMAT_VHDX):
            err_msg = _("Unsupported volume format: %s ") % volume_format
            raise exception.InvalidVolume(err_msg)

        self.vhdutils.create_dynamic_vhd(volume_path, volume_size_bytes)

    def _ensure_share_mounted(self, smbfs_share):
        mnt_options = {}
        if self.shares.get(smbfs_share) is not None:
            mnt_flags = self.shares[smbfs_share]
            mnt_options = self.parse_options(mnt_flags)[1]
        self._remotefsclient.mount(smbfs_share, mnt_options)

    def _delete(self, path):
        fileutils.delete_if_exists(path)

    def _get_capacity_info(self, smbfs_share):
        """Calculate available space on the SMBFS share.

        :param smbfs_share: example //172.18.194.100/var/smbfs
        """
        total_size, total_available = self._remotefsclient.get_capacity_info(
            smbfs_share)
        total_allocated = self._get_total_allocated(smbfs_share)
        return_value = [total_size, total_available, total_allocated]
        LOG.info(_LI('Smb share %(share)s Total size %(size)s '
                     'Total allocated %(allocated)s'),
                 {'share': smbfs_share, 'size': total_size,
                  'allocated': total_allocated})
        return [float(x) for x in return_value]

    def _img_commit(self, snapshot_path):
        self.vhdutils.merge_vhd(snapshot_path)
        self._delete(snapshot_path)

    def _rebase_img(self, image, backing_file, volume_format):
        # Relative path names are not supported in this case.
        image_dir = os.path.dirname(image)
        backing_file_path = os.path.join(image_dir, backing_file)
        self.vhdutils.reconnect_parent(image, backing_file_path)

    def _qemu_img_info(self, path, volume_name=None):
        # This code expects to deal only with relative filenames.
        # As this method is needed by the upper class and qemu-img does
        # not fully support vhdx images, for the moment we'll use Win32 API
        # for retrieving image information.
        parent_path = self.vhdutils.get_vhd_parent_path(path)
        file_format = os.path.splitext(path)[1][1:].lower()

        if parent_path:
            backing_file_name = os.path.split(parent_path)[1].lower()
        else:
            backing_file_name = None

        class ImageInfo(object):
            def __init__(self, image, backing_file):
                self.image = image
                self.backing_file = backing_file
                self.file_format = file_format

        return ImageInfo(os.path.basename(path),
                         backing_file_name)

    def _do_create_snapshot(self, snapshot, backing_file, new_snap_path):
        backing_file_full_path = os.path.join(
            self._local_volume_dir(snapshot['volume']),
            backing_file)
        self.vhdutils.create_differencing_vhd(new_snap_path,
                                              backing_file_full_path)

    def _do_extend_volume(self, volume_path, size_gb, volume_name=None):
        self.vhdutils.resize_vhd(volume_path, size_gb * units.Gi)

    @remotefs_drv.locked_volume_id_operation
    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""

        # If snapshots exist, flatten to a temporary image, and upload it

        active_file = self.get_active_image_from_info(volume)
        active_file_path = os.path.join(self._local_volume_dir(volume),
                                        active_file)
        backing_file = self.vhdutils.get_vhd_parent_path(active_file_path)
        root_file_fmt = self.get_volume_format(volume)

        temp_path = None

        try:
            if backing_file or root_file_fmt == self._DISK_FORMAT_VHDX:
                temp_file_name = '%s.temp_image.%s.%s' % (
                    volume['id'],
                    image_meta['id'],
                    self._DISK_FORMAT_VHD)
                temp_path = os.path.join(self._local_volume_dir(volume),
                                         temp_file_name)

                self.vhdutils.convert_vhd(active_file_path, temp_path)
                upload_path = temp_path
            else:
                upload_path = active_file_path

            image_utils.upload_volume(context,
                                      image_service,
                                      image_meta,
                                      upload_path,
                                      self._DISK_FORMAT_VHD)
        finally:
            if temp_path:
                self._delete(temp_path)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        volume_path = self.local_path(volume)
        volume_format = self.get_volume_format(volume, qemu_format=True)
        self._delete(volume_path)

        image_utils.fetch_to_volume_format(
            context, image_service, image_id,
            volume_path, volume_format,
            self.configuration.volume_dd_blocksize)

        self._extend_vhd_if_needed(self.local_path(volume), volume['size'])

    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size):
        """Copy data from snapshot to destination volume."""

        LOG.debug("snapshot: %(snap)s, volume: %(vol)s, "
                  "volume_size: %(size)s",
                  {'snap': snapshot['id'],
                   'vol': volume['id'],
                   'size': snapshot['volume_size']})

        info_path = self._local_path_volume_info(snapshot['volume'])
        snap_info = self._read_info_file(info_path)
        vol_dir = self._local_volume_dir(snapshot['volume'])

        forward_file = snap_info[snapshot['id']]
        forward_path = os.path.join(vol_dir, forward_file)

        # Find the file which backs this file, which represents the point
        # when this snapshot was created.
        img_info = self._qemu_img_info(forward_path)
        snapshot_path = os.path.join(vol_dir, img_info.backing_file)

        volume_path = self.local_path(volume)
        self._delete(volume_path)
        self.vhdutils.convert_vhd(snapshot_path,
                                  volume_path)
        self._extend_vhd_if_needed(volume_path, volume_size)

    def _extend_vhd_if_needed(self, vhd_path, new_size_gb):
        old_size_bytes = self.vhdutils.get_vhd_size(vhd_path)['VirtualSize']
        new_size_bytes = new_size_gb * units.Gi

        # This also ensures we're not attempting to shrink the image.
        is_resize_needed = self._windows_utils.is_resize_needed(
            vhd_path, new_size_bytes, old_size_bytes)
        if is_resize_needed:
            self.vhdutils.resize_vhd(vhd_path, new_size_bytes)
