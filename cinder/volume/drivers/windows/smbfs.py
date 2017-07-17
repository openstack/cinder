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

from os_brick.remotefs import windows_remotefs as remotefs_brick
from os_win import utilsfactory
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import units

from cinder import context
from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import utils
from cinder.volume import configuration
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
                     'information about volume disk space allocation.'),
               deprecated_for_removal=True,
               deprecated_since="11.0.0",
               deprecated_reason="This allocation file is no longer used."),
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
                 default=None,
                 help=('Percent of ACTUAL usage of the underlying volume '
                       'before no new volumes can be allocated to the volume '
                       'destination.'),
                 deprecated_for_removal=True),
    cfg.FloatOpt('smbfs_oversub_ratio',
                 default=None,
                 help=('This will compare the allocated to available space on '
                       'the volume destination.  If the ratio exceeds this '
                       'number, the destination will no longer be valid.'),
                 deprecated_for_removal=True),
    cfg.StrOpt('smbfs_mount_point_base',
               default=r'C:\OpenStack\_mnt',
               help=('Base dir containing mount points for smbfs shares.')),
    cfg.DictOpt('smbfs_pool_mappings',
                default={},
                help=('Mappings between share locations and pool names. '
                      'If not specified, the share names will be used as '
                      'pool names. Example: '
                      '//addr/share:pool_name,//addr/share2:pool_name2')),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts, group=configuration.SHARED_CONF_GROUP)

# TODO(lpetrut): drop the following default values. The according
# smbfs driver opts are getting deprecated but we want to preserve
# their defaults until we completely remove them.
CONF.set_default('max_over_subscription_ratio', 1)
CONF.set_default('reserved_percentage', 5)


@interface.volumedriver
class WindowsSmbfsDriver(remotefs_drv.RemoteFSPoolMixin,
                         remotefs_drv.RemoteFSSnapDriverDistributed):
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

    _always_use_temp_snap_when_cloning = False
    _thin_provisioning_support = True

    def __init__(self, *args, **kwargs):
        self._remotefsclient = None
        super(WindowsSmbfsDriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(volume_opts)

        self.base = getattr(self.configuration,
                            'smbfs_mount_point_base')
        self._remotefsclient = remotefs_brick.WindowsRemoteFsClient(
            'cifs', root_helper=None, smbfs_mount_point_base=self.base,
            local_path_for_loopback=True)

        self._vhdutils = utilsfactory.get_vhdutils()
        self._pathutils = utilsfactory.get_pathutils()
        self._smbutils = utilsfactory.get_smbutils()
        self._diskutils = utilsfactory.get_diskutils()

    def do_setup(self, context):
        self._check_os_platform()

        if self.configuration.smbfs_oversub_ratio is not None:
            self.configuration.max_over_subscription_ratio = (
                self.configuration.smbfs_oversub_ratio)
        if self.configuration.smbfs_used_ratio is not None:
            self.configuration.reserved_percentage = (
                1 - self.configuration.smbfs_used_ratio) * 100

        super(WindowsSmbfsDriver, self).do_setup(context)

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
        if not self.configuration.max_over_subscription_ratio > 0:
            msg = _(
                "SMBFS config 'max_over_subscription_ratio' invalid. "
                "Must be > 0: %s"
            ) % self.configuration.max_over_subscription_ratio

            LOG.error(msg)
            raise exception.SmbfsException(msg)

        if not 0 <= self.configuration.reserved_percentage <= 100:
            msg = _(
                "SMBFS config 'reserved_percentage' invalid. "
                "Must be > 0 and <= 100: %s"
            ) % self.configuration.reserved_percentage
            LOG.error(msg)
            raise exception.SmbfsException(msg)

        self.shares = {}  # address : options
        self._ensure_shares_mounted()
        self._setup_pool_mappings()

    def _setup_pool_mappings(self):
        self._pool_mappings = self.configuration.smbfs_pool_mappings

        pools = list(self._pool_mappings.values())
        duplicate_pools = set([pool for pool in pools
                               if pools.count(pool) > 1])
        if duplicate_pools:
            msg = _("Found multiple mappings for pools %(pools)s. "
                    "Requested pool mappings: %(pool_mappings)s")
            raise exception.SmbfsException(
                msg % dict(pools=duplicate_pools,
                           pool_mappings=self._pool_mappings))

        shares_missing_mappings = (
            set(self.shares).difference(set(self._pool_mappings)))
        for share in shares_missing_mappings:
            msg = ("No pool name was requested for share %(share)s "
                   "Using the share name instead.")
            LOG.warning(msg, dict(share=share))

            self._pool_mappings[share] = self._get_share_name(share)

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
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

    def _get_total_allocated(self, smbfs_share):
        pool_name = self._get_pool_name_from_share(smbfs_share)
        host = "#".join([self.host, pool_name])

        vol_sz_sum = self.db.volume_data_get_for_host(
            context=context.get_admin_context(),
            host=host)[1]
        return float(vol_sz_sum * units.Gi)

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
                extra_specs.get('smbfs:volume_format') or
                self.configuration.smbfs_default_volume_format)

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
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

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def delete_volume(self, volume):
        """Deletes a logical volume."""
        if not volume.provider_location:
            LOG.warning('Volume %s does not have provider_location '
                        'specified, skipping.', volume.name)
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
        mount_point = self._get_mount_point_for_share(smbfs_share)
        total_size, total_available = self._diskutils.get_disk_capacity(
            mount_point)
        total_allocated = self._get_total_allocated(smbfs_share)
        return_value = [total_size, total_available, total_allocated]
        LOG.info('Smb share %(share)s Total size %(size)s '
                 'Total allocated %(allocated)s',
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
        if snapshot.volume.status == 'in-use':
            LOG.debug("Snapshot is in-use. Performing Nova "
                      "assisted creation.")
            return

        backing_file_full_path = os.path.join(
            self._local_volume_dir(snapshot.volume),
            backing_file)
        self._vhdutils.create_differencing_vhd(new_snap_path,
                                               backing_file_full_path)

    def _extend_volume(self, volume, size_gb):
        self._check_extend_volume_support(volume, size_gb)

        volume_path = self._local_path_active_image(volume)

        LOG.info('Resizing file %(volume_path)s to %(size_gb)sGB.',
                 dict(volume_path=volume_path, size_gb=size_gb))

        self._vhdutils.resize_vhd(volume_path, size_gb * units.Gi,
                                  is_file_max_size=False)

    def _delete_snapshot(self, snapshot):
        # NOTE(lpetrut): We're slightly diverging from the super class
        # workflow. The reason is that we cannot query in-use vhd/x images,
        # nor can we add or remove images from a vhd/x chain in this case.
        volume_status = snapshot.volume.status
        if volume_status != 'in-use':
            return super(WindowsSmbfsDriver, self)._delete_snapshot(snapshot)

        info_path = self._local_path_volume_info(snapshot.volume)
        snap_info = self._read_info_file(info_path, empty_if_missing=True)

        if snapshot.id not in snap_info:
            LOG.info('Snapshot record for %s is not present, allowing '
                     'snapshot_delete to proceed.', snapshot.id)
            return

        file_to_merge = snap_info[snapshot.id]
        delete_info = {'file_to_merge': file_to_merge,
                       'volume_id': snapshot.volume.id}
        self._nova_assisted_vol_snap_delete(
            snapshot._context, snapshot, delete_info)

        # At this point, the image file should no longer be in use, so we
        # may safely query it so that we can update the 'active' image
        # reference, if needed.
        merged_img_path = os.path.join(
            self._local_volume_dir(snapshot.volume),
            file_to_merge)
        if utils.paths_normcase_equal(snap_info['active'], file_to_merge):
            new_active_file_path = self._vhdutils.get_vhd_parent_path(
                merged_img_path).lower()
            snap_info['active'] = os.path.basename(new_active_file_path)

        self._delete(merged_img_path)

        # TODO(lpetrut): drop snapshot info file usage.
        del(snap_info[snapshot.id])
        self._write_info_file(info_path, snap_info)

    def _check_extend_volume_support(self, volume, size_gb):
        snapshots_exist = self._snapshots_exist(volume)
        fmt = self.get_volume_format(volume)

        if snapshots_exist and fmt == self._DISK_FORMAT_VHD:
            msg = _('Extending volumes backed by VHD images is not supported '
                    'when snapshots exist. Please use VHDX images.')
            raise exception.InvalidVolume(msg)

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
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
            if backing_file:
                temp_file_name = '%s.temp_image.%s.%s' % (
                    volume.id,
                    image_meta['id'],
                    root_file_fmt)
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
                                      root_file_fmt)
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

    def _copy_volume_image(self, src_path, dest_path):
        self._pathutils.copy(src_path, dest_path)

    def _get_share_name(self, share):
        return share.replace('/', '\\').lstrip('\\').split('\\', 1)[1]

    def _get_pool_name_from_share(self, share):
        return self._pool_mappings[share]

    def _get_share_from_pool_name(self, pool_name):
        mappings = {pool: share
                    for share, pool in self._pool_mappings.items()}
        share = mappings.get(pool_name)

        if not share:
            msg = _("Could not find any share for pool %(pool_name)s. "
                    "Pool mappings: %(pool_mappings)s.")
            raise exception.SmbfsException(
                msg % dict(pool_name=pool_name,
                           pool_mappings=self._pool_mappings))
        return share
