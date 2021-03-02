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
import re
import sys

from os_brick.remotefs import windows_remotefs as remotefs_brick
from os_win import constants as os_win_const
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
from cinder import objects
from cinder import utils
from cinder.volume import configuration
from cinder.volume.drivers import remotefs as remotefs_drv
from cinder.volume import volume_utils

VERSION = '1.1.0'

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('smbfs_shares_config',
               default=r'C:\OpenStack\smbfs_shares.txt',
               help='File with the list of available smbfs shares.'),
    cfg.StrOpt('smbfs_default_volume_format',
               default='vhd',
               choices=['vhd', 'vhdx'],
               help=('Default format that will be used when creating volumes '
                     'if no volume format is specified.')),
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


class SmbfsException(exception.RemoteFSException):
    message = _("Unknown SMBFS exception.")


class SmbfsNoSharesMounted(exception.RemoteFSNoSharesMounted):
    message = _("No mounted SMBFS shares found.")


class SmbfsNoSuitableShareFound(exception.RemoteFSNoSuitableShareFound):
    message = _("There is no share which can host %(volume_size)sG.")


@interface.volumedriver
class WindowsSmbfsDriver(remotefs_drv.RevertToSnapshotMixin,
                         remotefs_drv.RemoteFSPoolMixin,
                         remotefs_drv.RemoteFSManageableVolumesMixin,
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
    CI_WIKI_NAME = "Cloudbase_Cinder_SMB3_CI"

    _MINIMUM_QEMU_IMG_VERSION = '1.6'

    _SUPPORTED_IMAGE_FORMATS = [_DISK_FORMAT_VHD,
                                _DISK_FORMAT_VHD_LEGACY,
                                _DISK_FORMAT_VHDX]
    _VALID_IMAGE_EXTENSIONS = [_DISK_FORMAT_VHD, _DISK_FORMAT_VHDX]
    _MANAGEABLE_IMAGE_RE = re.compile(
        r'.*\.(?:%s)$' % '|'.join(_VALID_IMAGE_EXTENSIONS),
        re.IGNORECASE)

    _always_use_temp_snap_when_cloning = False
    _thin_provisioning_support = True

    _vhd_type_mapping = {'thin': os_win_const.VHD_TYPE_DYNAMIC,
                         'thick': os_win_const.VHD_TYPE_FIXED}
    _vhd_qemu_subformat_mapping = {'thin': 'dynamic',
                                   'thick': 'fixed'}

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

        thin_enabled = (
            self.configuration.nas_volume_prov_type == 'thin')
        self._thin_provisioning_support = thin_enabled
        self._thick_provisioning_support = not thin_enabled

    @staticmethod
    def get_driver_options():
        return volume_opts

    def do_setup(self, context):
        self._check_os_platform()

        super(WindowsSmbfsDriver, self).do_setup(context)

        image_utils.check_qemu_img_version(self._MINIMUM_QEMU_IMG_VERSION)

        config = self.configuration.smbfs_shares_config
        if not config:
            msg = (_("SMBFS config file not set (smbfs_shares_config)."))
            LOG.error(msg)
            raise SmbfsException(msg)
        if not os.path.exists(config):
            msg = (_("SMBFS config file at %(config)s doesn't exist.") %
                   {'config': config})
            LOG.error(msg)
            raise SmbfsException(msg)
        if not os.path.isabs(self.base):
            msg = _("Invalid mount point base: %s") % self.base
            LOG.error(msg)
            raise SmbfsException(msg)

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
            raise SmbfsException(
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

    @coordination.synchronized('{self.driver_prefix}-{snapshot.volume.id}')
    def initialize_connection_snapshot(self, snapshot, connector):
        backing_file = self._get_snapshot_backing_file(snapshot)
        volume = snapshot.volume
        fmt = self.get_volume_format(volume)

        data = {'export': volume.provider_location,
                'format': fmt,
                'name': backing_file,
                'access_mode': 'ro'}

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
            raise SmbfsException(_msg)

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
        for ext in self._VALID_IMAGE_EXTENSIONS:
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
            if ext in self._VALID_IMAGE_EXTENSIONS:
                volume_format = ext
            else:
                # Hyper-V relies on file extensions so we're enforcing them.
                raise SmbfsException(
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

        vhd_type = self._get_vhd_type()

        self._vhdutils.create_vhd(volume_path, vhd_type,
                                  max_internal_size=volume_size_bytes,
                                  guid=volume.id)

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
        if self._is_volume_attached(snapshot.volume):
            LOG.debug("Snapshot is in-use. Performing Nova "
                      "assisted creation.")
        else:
            backing_file_full_path = os.path.join(
                self._local_volume_dir(snapshot.volume),
                backing_file)
            self._vhdutils.create_differencing_vhd(new_snap_path,
                                                   backing_file_full_path)

        # We're setting the backing file information in the DB as we may not
        # be able to query the image while it's in use due to file locks.
        #
        # When dealing with temporary snapshots created by the driver, we
        # may not receive an actual snapshot VO. We currently need this check
        # in order to avoid breaking the volume clone operation.
        #
        # TODO(lpetrut): remove this check once we'll start using db entries
        # for such temporary snapshots, most probably when we'll add support
        # for cloning in-use volumes.
        if isinstance(snapshot, objects.Snapshot):
            snapshot.metadata['backing_file'] = backing_file
            snapshot.save()
        else:
            LOG.debug("Received a '%s' object, skipping setting the backing "
                      "file in the DB.", type(snapshot))

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
        info_path = self._local_path_volume_info(snapshot.volume)
        snap_info = self._read_info_file(info_path, empty_if_missing=True)

        if snapshot.id not in snap_info:
            LOG.info('Snapshot record for %s is not present, allowing '
                     'snapshot_delete to proceed.', snapshot.id)
            return

        file_to_merge = snap_info[snapshot.id]
        deleting_latest_snap = utils.paths_normcase_equal(snap_info['active'],
                                                          file_to_merge)

        if not self._is_volume_attached(snapshot.volume):
            super(WindowsSmbfsDriver, self)._delete_snapshot(snapshot)
        else:
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
            if deleting_latest_snap:
                new_active_file_path = self._vhdutils.get_vhd_parent_path(
                    merged_img_path).lower()
                snap_info['active'] = os.path.basename(new_active_file_path)

            self._delete(merged_img_path)

            # TODO(lpetrut): drop snapshot info file usage.
            del(snap_info[snapshot.id])
            self._write_info_file(info_path, snap_info)

        if not isinstance(snapshot, objects.Snapshot):
            LOG.debug("Received a '%s' object, skipping setting the backing "
                      "file in the DB.", type(snapshot))
        elif not deleting_latest_snap:
            backing_file = snapshot['metadata'].get('backing_file')
            higher_snapshot = self._get_snapshot_by_backing_file(
                snapshot.volume, file_to_merge)
            # The snapshot objects should have a backing file set, unless
            # created before an upgrade. If the snapshot we're deleting
            # does not have a backing file set yet there is a newer one that
            # does, we're clearing it out so that it won't provide wrong info.
            if higher_snapshot:
                LOG.debug("Updating backing file reference (%(backing_file)s) "
                          "for higher snapshot: %(higher_snapshot_id)s.",
                          dict(backing_file=snapshot.metadata['backing_file'],
                               higher_snapshot_id=higher_snapshot.id))

                higher_snapshot.metadata['backing_file'] = (
                    snapshot.metadata['backing_file'])
                higher_snapshot.save()
            if not (higher_snapshot and backing_file):
                LOG.info(
                    "The deleted snapshot is not latest one, yet we could not "
                    "find snapshot backing file information in the DB. This "
                    "may happen after an upgrade. Certain operations against "
                    "this volume may be unavailable while it's in-use.")

    def _get_snapshot_by_backing_file(self, volume, backing_file):
        all_snapshots = objects.SnapshotList.get_all_for_volume(
            context.get_admin_context(), volume.id)
        for snapshot in all_snapshots:
            snap_backing_file = snapshot.metadata.get('backing_file')
            if utils.paths_normcase_equal(snap_backing_file or '',
                                          backing_file):
                return snapshot

    def _get_snapshot_backing_file(self, snapshot):
        backing_file = snapshot.metadata.get('backing_file')
        if not backing_file:
            LOG.info("Could not find the snapshot backing file in the DB. "
                     "This may happen after an upgrade. Attempting to "
                     "query the image as a fallback. This may fail if "
                     "the image is in-use.")
            backing_file = super(
                WindowsSmbfsDriver, self)._get_snapshot_backing_file(snapshot)

        return backing_file

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

            volume_utils.upload_volume(context,
                                       image_service,
                                       image_meta,
                                       upload_path,
                                       volume,
                                       root_file_fmt)
        finally:
            if temp_path:
                self._delete(temp_path)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        volume_path = self.local_path(volume)
        volume_format = self.get_volume_format(volume, qemu_format=True)
        volume_subformat = self._get_vhd_type(qemu_subformat=True)
        self._delete(volume_path)

        image_utils.fetch_to_volume_format(
            context, image_service, image_id,
            volume_path, volume_format,
            self.configuration.volume_dd_blocksize,
            volume_subformat)

        volume_path = self.local_path(volume)
        self._vhdutils.set_vhd_guid(volume_path, volume.id)
        self._vhdutils.resize_vhd(volume_path,
                                  volume.size * units.Gi,
                                  is_file_max_size=False)

    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size,
                                   src_encryption_key_id=None,
                                   new_encryption_key_id=None):
        """Copy data from snapshot to destination volume."""

        if new_encryption_key_id:
            msg = _("Encryption key %s was requested. Volume "
                    "encryption is not currently supported.")
            raise exception.NotSupportedOperation(
                message=msg % new_encryption_key_id)

        LOG.debug("snapshot: %(snap)s, volume: %(vol)s, "
                  "volume_size: %(size)s",
                  {'snap': snapshot.id,
                   'vol': volume.id,
                   'size': snapshot.volume_size})

        vol_dir = self._local_volume_dir(snapshot.volume)

        # Find the file which backs this file, which represents the point
        # when this snapshot was created.
        backing_file = self._get_snapshot_backing_file(snapshot)
        snapshot_path = os.path.join(vol_dir, backing_file)

        volume_path = self.local_path(volume)
        vhd_type = self._get_vhd_type()

        self._delete(volume_path)
        self._vhdutils.convert_vhd(snapshot_path,
                                   volume_path,
                                   vhd_type=vhd_type)
        self._vhdutils.set_vhd_guid(volume_path, volume.id)
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
            raise SmbfsException(
                msg % dict(pool_name=pool_name,
                           pool_mappings=self._pool_mappings))
        return share

    def _get_vhd_type(self, qemu_subformat=False):
        prov_type = self.configuration.nas_volume_prov_type

        if qemu_subformat:
            vhd_type = self._vhd_qemu_subformat_mapping[prov_type]
        else:
            vhd_type = self._vhd_type_mapping[prov_type]

        return vhd_type

    def _get_managed_vol_expected_path(self, volume, volume_location):
        fmt = self._vhdutils.get_vhd_format(volume_location['vol_local_path'])
        return os.path.join(volume_location['mountpoint'],
                            volume.name + ".%s" % fmt).lower()

    def manage_existing(self, volume, existing_ref):
        model_update = super(WindowsSmbfsDriver, self).manage_existing(
            volume, existing_ref)

        volume.provider_location = model_update['provider_location']
        volume_path = self.local_path(volume)

        self._vhdutils.set_vhd_guid(volume_path, volume.id)

        return model_update

    def _set_rw_permissions(self, path):
        # The SMBFS driver does not manage file permissions. We chose
        # to let this up to the deployer.
        pass

    def backup_use_temp_snapshot(self):
        return True
