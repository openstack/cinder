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

import inspect
import json
import os
import sys

import decorator
from os_brick.remotefs import windows_remotefs as remotefs_brick
from os_win import utilsfactory
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LI, _LW
from cinder.image import image_utils
from cinder import interface
from cinder.volume.drivers import remotefs as remotefs_drv

VERSION = '1.1.0'

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('smbfs_shares_config',
               default=r'C:\OpenStack\smbfs_shares.txt',
               help='File with the list of available smbfs shares.'),
    cfg.StrOpt('smbfs_allocation_info_file_path',
               default=r'C:\OpenStack\allocation_data.txt',
               help=('The path of the automatically generated file containing '
                     'information about volume disk space allocation.')),
    cfg.StrOpt('smbfs_default_volume_format',
               default='vhd',
               choices=['vhd', 'vhdx'],
               help=('Default format that will be used when creating volumes '
                     'if no volume format is specified.')),
    cfg.BoolOpt('smbfs_sparsed_volumes',
                default=True,
                help=('Create volumes as sparsed files which take no space '
                      'rather than regular files when using raw format, '
                      'in which case volume creation takes lot of time.')),
    cfg.FloatOpt('smbfs_used_ratio',
                 default=0.95,
                 help=('Percent of ACTUAL usage of the underlying volume '
                       'before no new volumes can be allocated to the volume '
                       'destination.')),
    cfg.FloatOpt('smbfs_oversub_ratio',
                 default=1.0,
                 help=('This will compare the allocated to available space on '
                       'the volume destination.  If the ratio exceeds this '
                       'number, the destination will no longer be valid.')),
    cfg.StrOpt('smbfs_mount_point_base',
               default=r'C:\OpenStack\_mnt',
               help=('Base dir containing mount points for smbfs shares.')),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


def update_allocation_data(delete=False):
    @decorator.decorator
    def wrapper(func, inst, *args, **kwargs):
        ret_val = func(inst, *args, **kwargs)

        call_args = inspect.getcallargs(func, inst, *args, **kwargs)
        volume = call_args['volume']
        requested_size = call_args.get('size_gb', None)

        if delete:
            allocated_size_gb = None
        else:
            allocated_size_gb = requested_size or volume.size

        inst.update_disk_allocation_data(volume, allocated_size_gb)
        return ret_val
    return wrapper


@interface.volumedriver
class WindowsSmbfsDriver(remotefs_drv.RemoteFSSnapDriver):
    VERSION = VERSION

    driver_volume_type = 'smbfs'
    driver_prefix = 'smbfs'
    volume_backend_name = 'Generic_SMBFS'
    SHARE_FORMAT_REGEX = r'//.+/.+'
    VERSION = VERSION

    _DISK_FORMAT_VHD = 'vhd'
    _DISK_FORMAT_VHD_LEGACY = 'vpc'
    _DISK_FORMAT_VHDX = 'vhdx'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Microsoft_iSCSI_CI"

    _MINIMUM_QEMU_IMG_VERSION = '1.6'

    _SUPPORTED_IMAGE_FORMATS = [_DISK_FORMAT_VHD, _DISK_FORMAT_VHDX]
    _VALID_IMAGE_EXTENSIONS = _SUPPORTED_IMAGE_FORMATS

    def __init__(self, *args, **kwargs):
        self._remotefsclient = None
        super(WindowsSmbfsDriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(volume_opts)

        self.base = getattr(self.configuration,
                            'smbfs_mount_point_base',
                            CONF.smbfs_mount_point_base)
        self._remotefsclient = remotefs_brick.WindowsRemoteFsClient(
            'cifs', root_helper=None, smbfs_mount_point_base=self.base,
            local_path_for_loopback=True)

        self._vhdutils = utilsfactory.get_vhdutils()
        self._pathutils = utilsfactory.get_pathutils()
        self._smbutils = utilsfactory.get_smbutils()

        self._alloc_info_file_path = (
            self.configuration.smbfs_allocation_info_file_path)

    def do_setup(self, context):
        self._check_os_platform()

        image_utils.check_qemu_img_version(self._MINIMUM_QEMU_IMG_VERSION)

        config = self.configuration.smbfs_shares_config
        if not config:
            msg = (_("SMBFS config file not set (smbfs_shares_config)."))
            LOG.error(msg)
            raise exception.SmbfsException(msg)
        if not os.path.exists(config):
            msg = (_("SMBFS config file at %(config)s doesn't exist.") %
                   {'config': config})
            LOG.error(msg)
            raise exception.SmbfsException(msg)
        if not os.path.isabs(self.base):
            msg = _("Invalid mount point base: %s") % self.base
            LOG.error(msg)
            raise exception.SmbfsException(msg)
        if not self.configuration.smbfs_oversub_ratio > 0:
            msg = _(
                "SMBFS config 'smbfs_oversub_ratio' invalid.  Must be > 0: "
                "%s") % self.configuration.smbfs_oversub_ratio

            LOG.error(msg)
            raise exception.SmbfsException(msg)

        if not 0 < self.configuration.smbfs_used_ratio <= 1:
            msg = _("SMBFS config 'smbfs_used_ratio' invalid.  Must be > 0 "
                    "and <= 1.0: %s") % self.configuration.smbfs_used_ratio
            LOG.error(msg)
            raise exception.SmbfsException(msg)

        self.shares = {}  # address : options
        self._ensure_shares_mounted()
        self._setup_allocation_data()

    @remotefs_drv.locked_volume_id_operation
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        :param volume: volume reference
        :param connector: connector reference
        """
        # Find active image
        active_file = self.get_active_image_from_info(volume)
        fmt = self.get_volume_format(volume)

        data = {'export': volume.provider_location,
                'format': fmt,
                'name': active_file}
        if volume.provider_location in self.shares:
            data['options'] = self.shares[volume.provider_location]
        return {
            'driver_volume_type': self.driver_volume_type,
            'data': data,
            'mount_point_base': self._get_mount_point_base()
        }

    def _check_os_platform(self):
        if sys.platform != 'win32':
            _msg = _("This system platform (%s) is not supported. This "
                     "driver supports only Win32 platforms.") % sys.platform
            raise exception.SmbfsException(_msg)

    def _setup_allocation_data(self):
        if not os.path.exists(self._alloc_info_file_path):
            fileutils.ensure_tree(
                os.path.dirname(self._alloc_info_file_path))
            self._allocation_data = {}
            self._update_allocation_data_file()
        else:
            with open(self._alloc_info_file_path, 'r') as f:
                self._allocation_data = json.load(f)

    def update_disk_allocation_data(self, volume, virtual_size_gb=None):
        volume_name = volume.name
        smbfs_share = volume.provider_location
        if smbfs_share:
            share_hash = self._get_hash_str(smbfs_share)
        else:
            return

        share_alloc_data = self._allocation_data.get(share_hash, {})
        old_virtual_size = share_alloc_data.get(volume_name, 0)
        total_allocated = share_alloc_data.get('total_allocated', 0)

        if virtual_size_gb:
            share_alloc_data[volume_name] = virtual_size_gb
            total_allocated += virtual_size_gb - old_virtual_size
        elif share_alloc_data.get(volume_name):
            # The volume is deleted.
            del share_alloc_data[volume_name]
            total_allocated -= old_virtual_size

        share_alloc_data['total_allocated'] = total_allocated
        self._allocation_data[share_hash] = share_alloc_data
        self._update_allocation_data_file()

    def _update_allocation_data_file(self):
        with open(self._alloc_info_file_path, 'w') as f:
            json.dump(self._allocation_data, f)

    def _get_total_allocated(self, smbfs_share):
        share_hash = self._get_hash_str(smbfs_share)
        share_alloc_data = self._allocation_data.get(share_hash, {})
        total_allocated = share_alloc_data.get('total_allocated', 0) << 30
        return float(total_allocated)

    def _find_share(self, volume_size_in_gib):
        """Choose SMBFS share among available ones for given volume size.

        For instances with more than one share that meets the criteria, the
        share with the least "allocated" space will be selected.

        :param volume_size_in_gib: int size in GB
        """

        if not self._mounted_shares:
            raise exception.SmbfsNoSharesMounted()

        target_share = None
        target_share_reserved = 0

        for smbfs_share in self._mounted_shares:
            if not self._is_share_eligible(smbfs_share, volume_size_in_gib):
                continue
            total_allocated = self._get_total_allocated(smbfs_share)
            if target_share is not None:
                if target_share_reserved > total_allocated:
                    target_share = smbfs_share
                    target_share_reserved = total_allocated
            else:
                target_share = smbfs_share
                target_share_reserved = total_allocated

        if target_share is None:
            raise exception.SmbfsNoSuitableShareFound(
                volume_size=volume_size_in_gib)

        LOG.debug('Selected %s as target smbfs share.', target_share)

        return target_share

    def _is_share_eligible(self, smbfs_share, volume_size_in_gib):
        """Verifies SMBFS share is eligible to host volume with given size.

        First validation step: ratio of actual space (used_space / total_space)
        is less than 'smbfs_used_ratio'. Second validation step: apparent space
        allocated (differs from actual space used when using sparse files)
        and compares the apparent available
        space (total_available * smbfs_oversub_ratio) to ensure enough space is
        available for the new volume.

        :param smbfs_share: smbfs share
        :param volume_size_in_gib: int size in GB
        """

        used_ratio = self.configuration.smbfs_used_ratio
        oversub_ratio = self.configuration.smbfs_oversub_ratio
        requested_volume_size = volume_size_in_gib * units.Gi

        total_size, total_available, total_allocated = \
            self._get_capacity_info(smbfs_share)

        apparent_size = max(0, total_size * oversub_ratio)
        apparent_available = max(0, apparent_size - total_allocated)
        used = (total_size - total_available) / total_size

        if used > used_ratio:
            LOG.debug('%s is above smbfs_used_ratio.', smbfs_share)
            return False
        if apparent_available <= requested_volume_size:
            LOG.debug('%s is above smbfs_oversub_ratio.', smbfs_share)
            return False
        if total_allocated / total_size >= oversub_ratio:
            LOG.debug('%s reserved space is above smbfs_oversub_ratio.',
                      smbfs_share)
            return False
        return True

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume.

        :param volume: volume reference
        """
        volume_path_template = self._get_local_volume_path_template(volume)
        volume_path = self._lookup_local_volume_path(volume_path_template)
        if volume_path:
            return volume_path

        # The image does not exist, so retrieve the volume format
        # in order to build the path.
        fmt = self.get_volume_format(volume)
        volume_path = volume_path_template + '.' + fmt
        return volume_path

    def _get_local_volume_path_template(self, volume):
        local_dir = self._local_volume_dir(volume)
        local_path_template = os.path.join(local_dir, volume.name)
        return local_path_template

    def _lookup_local_volume_path(self, volume_path_template):
        for ext in self._SUPPORTED_IMAGE_FORMATS:
            volume_path = (volume_path_template + '.' + ext
                           if ext else volume_path_template)
            if os.path.exists(volume_path):
                return volume_path

    def _get_new_snap_path(self, snapshot):
        vol_path = self.local_path(snapshot.volume)
        snap_path, ext = os.path.splitext(vol_path)
        snap_path += '.' + snapshot.id + ext
        return snap_path

    def get_volume_format(self, volume, qemu_format=False):
        volume_path_template = self._get_local_volume_path_template(volume)
        volume_path = self._lookup_local_volume_path(volume_path_template)

        if volume_path:
            ext = os.path.splitext(volume_path)[1].strip('.').lower()
            if ext in self._SUPPORTED_IMAGE_FORMATS:
                volume_format = ext
            else:
                # Hyper-V relies on file extensions so we're enforcing them.
                raise exception.SmbfsException(
                    _("Invalid image file extension: %s") % ext)
        else:
            volume_format = (
                self._get_volume_format_spec(volume) or
                self.configuration.smbfs_default_volume_format)

        if qemu_format and volume_format == self._DISK_FORMAT_VHD:
            volume_format = self._DISK_FORMAT_VHD_LEGACY
        elif volume_format == self._DISK_FORMAT_VHD_LEGACY:
            volume_format = self._DISK_FORMAT_VHD

        return volume_format

    def _get_volume_format_spec(self, volume):
        vol_type = volume.volume_type
        extra_specs = {}
        if vol_type and vol_type.extra_specs:
            extra_specs = vol_type.extra_specs

        extra_specs.update(volume.metadata or {})

        return (extra_specs.get('volume_format') or
                self.configuration.smbfs_default_volume_format)

    @remotefs_drv.locked_volume_id_operation
    @update_allocation_data()
    def create_volume(self, volume):
        return super(WindowsSmbfsDriver, self).create_volume(volume)

    def _do_create_volume(self, volume):
        volume_path = self.local_path(volume)
        volume_format = self.get_volume_format(volume)
        volume_size_bytes = volume.size * units.Gi

        if os.path.exists(volume_path):
            err_msg = _('File already exists at: %s') % volume_path
            raise exception.InvalidVolume(err_msg)

        if volume_format not in self._SUPPORTED_IMAGE_FORMATS:
            err_msg = _("Unsupported volume format: %s ") % volume_format
            raise exception.InvalidVolume(err_msg)

        self._vhdutils.create_dynamic_vhd(volume_path, volume_size_bytes)

    def _ensure_share_mounted(self, smbfs_share):
        mnt_flags = None
        if self.shares.get(smbfs_share) is not None:
            mnt_flags = self.shares[smbfs_share]
        self._remotefsclient.mount(smbfs_share, mnt_flags)

    @remotefs_drv.locked_volume_id_operation
    @update_allocation_data(delete=True)
    def delete_volume(self, volume):
        """Deletes a logical volume."""
        if not volume.provider_location:
            LOG.warning(_LW('Volume %s does not have provider_location '
                            'specified, skipping.'), volume.name)
            return

        self._ensure_share_mounted(volume.provider_location)
        volume_dir = self._local_volume_dir(volume)
        mounted_path = os.path.join(volume_dir,
                                    self.get_active_image_from_info(volume))
        if os.path.exists(mounted_path):
            self._delete(mounted_path)
        else:
            LOG.debug("Skipping deletion of volume %s as it does not exist.",
                      mounted_path)

        info_path = self._local_path_volume_info(volume)
        self._delete(info_path)

    def _delete(self, path):
        fileutils.delete_if_exists(path)

    def _get_capacity_info(self, smbfs_share):
        """Calculate available space on the SMBFS share.

        :param smbfs_share: example //172.18.194.100/var/smbfs
        """
        total_size, total_available = self._smbutils.get_share_capacity_info(
            smbfs_share)
        total_allocated = self._get_total_allocated(smbfs_share)
        return_value = [total_size, total_available, total_allocated]
        LOG.info(_LI('Smb share %(share)s Total size %(size)s '
                     'Total allocated %(allocated)s'),
                 {'share': smbfs_share, 'size': total_size,
                  'allocated': total_allocated})
        return [float(x) for x in return_value]

    def _img_commit(self, snapshot_path):
        self._vhdutils.merge_vhd(snapshot_path)

    def _rebase_img(self, image, backing_file, volume_format):
        # Relative path names are not supported in this case.
        image_dir = os.path.dirname(image)
        backing_file_path = os.path.join(image_dir, backing_file)
        self._vhdutils.reconnect_parent_vhd(image, backing_file_path)

    def _qemu_img_info(self, path, volume_name=None):
        # This code expects to deal only with relative filenames.
        # As this method is needed by the upper class and qemu-img does
        # not fully support vhdx images, for the moment we'll use Win32 API
        # for retrieving image information.
        parent_path = self._vhdutils.get_vhd_parent_path(path)
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
            self._local_volume_dir(snapshot.volume),
            backing_file)
        self._vhdutils.create_differencing_vhd(new_snap_path,
                                               backing_file_full_path)

    def _create_snapshot_online(self, snapshot, backing_filename,
                                new_snap_path):
        msg = _("This driver does not support snapshotting in-use volumes.")
        raise exception.SmbfsException(msg)

    def _delete_snapshot_online(self, context, snapshot, info):
        msg = _("This driver does not support deleting in-use snapshots.")
        raise exception.SmbfsException(msg)

    @remotefs_drv.locked_volume_id_operation
    @update_allocation_data()
    def extend_volume(self, volume, size_gb):
        LOG.info(_LI('Extending volume %s.'), volume.id)

        self._check_extend_volume_support(volume, size_gb)
        self._extend_volume(volume, size_gb)

    def _extend_volume(self, volume, size_gb):
        volume_path = self.local_path(volume)

        LOG.info(_LI('Resizing file %(volume_path)s to %(size_gb)sGB.'),
                 dict(volume_path=volume_path, size_gb=size_gb))

        self._vhdutils.resize_vhd(volume_path, size_gb * units.Gi,
                                  is_file_max_size=False)

    def _check_extend_volume_support(self, volume, size_gb):
        volume_path = self.local_path(volume)
        active_file = self.get_active_image_from_info(volume)
        active_file_path = os.path.join(self._local_volume_dir(volume),
                                        active_file)

        if active_file_path != volume_path:
            msg = _('Extend volume is only supported for this '
                    'driver when no snapshots exist.')
            raise exception.InvalidVolume(msg)

        extend_by = int(size_gb) - volume.size
        if not self._is_share_eligible(volume.provider_location,
                                       extend_by):
            raise exception.ExtendVolumeError(reason='Insufficient space to '
                                              'extend volume %s to %sG.'
                                              % (volume.id, size_gb))

    @remotefs_drv.locked_volume_id_operation
    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""

        # If snapshots exist, flatten to a temporary image, and upload it

        active_file = self.get_active_image_from_info(volume)
        active_file_path = os.path.join(self._local_volume_dir(volume),
                                        active_file)
        backing_file = self._vhdutils.get_vhd_parent_path(active_file_path)
        root_file_fmt = self.get_volume_format(volume)

        temp_path = None

        try:
            if backing_file or root_file_fmt == self._DISK_FORMAT_VHDX:
                temp_file_name = '%s.temp_image.%s.%s' % (
                    volume.id,
                    image_meta['id'],
                    self._DISK_FORMAT_VHD)
                temp_path = os.path.join(self._local_volume_dir(volume),
                                         temp_file_name)

                self._vhdutils.convert_vhd(active_file_path, temp_path)
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

        self._vhdutils.resize_vhd(self.local_path(volume),
                                  volume.size * units.Gi,
                                  is_file_max_size=False)

    @remotefs_drv.locked_volume_id_operation
    @update_allocation_data()
    def create_volume_from_snapshot(self, volume, snapshot):
        return self._create_volume_from_snapshot(volume, snapshot)

    @remotefs_drv.locked_volume_id_operation
    @update_allocation_data()
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        return self._create_cloned_volume(volume, src_vref)

    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size):
        """Copy data from snapshot to destination volume."""

        LOG.debug("snapshot: %(snap)s, volume: %(vol)s, "
                  "volume_size: %(size)s",
                  {'snap': snapshot.id,
                   'vol': volume.id,
                   'size': snapshot.volume_size})

        info_path = self._local_path_volume_info(snapshot.volume)
        snap_info = self._read_info_file(info_path)
        vol_dir = self._local_volume_dir(snapshot.volume)

        forward_file = snap_info[snapshot.id]
        forward_path = os.path.join(vol_dir, forward_file)

        # Find the file which backs this file, which represents the point
        # when this snapshot was created.
        img_info = self._qemu_img_info(forward_path)
        snapshot_path = os.path.join(vol_dir, img_info.backing_file)

        volume_path = self.local_path(volume)
        self._delete(volume_path)
        self._vhdutils.convert_vhd(snapshot_path,
                                   volume_path)
        self._vhdutils.resize_vhd(volume_path, volume_size * units.Gi,
                                  is_file_max_size=False)
