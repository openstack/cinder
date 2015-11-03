# Copyright (c) 2013 Red Hat, Inc.
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

import errno
import os
import stat

from os_brick.remotefs import remotefs as remotefs_brick
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.image import image_utils
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers import remotefs as remotefs_drv

LOG = logging.getLogger(__name__)


volume_opts = [
    cfg.StrOpt('glusterfs_shares_config',
               default='/etc/cinder/glusterfs_shares',
               help='File with the list of available gluster shares'),
    cfg.StrOpt('glusterfs_mount_point_base',
               default='$state_path/mnt',
               help='Base dir containing mount points for gluster shares.'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


class GlusterfsDriver(remotefs_drv.RemoteFSSnapDriver,
                      driver.ExtendVD):
    """Gluster based cinder driver.

    Creates file on Gluster share for using it as block device on hypervisor.

    Operations such as create/delete/extend volume/snapshot use locking on a
    per-process basis to prevent multiple threads from modifying qcow2 chains
    or the snapshot .info file simultaneously.
    """

    driver_volume_type = 'glusterfs'
    driver_prefix = 'glusterfs'
    volume_backend_name = 'GlusterFS'
    VERSION = '1.3.0'

    def __init__(self, execute=processutils.execute, *args, **kwargs):
        self._remotefsclient = None
        super(GlusterfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)
        root_helper = utils.get_root_helper()
        self.base = getattr(self.configuration,
                            'glusterfs_mount_point_base',
                            CONF.glusterfs_mount_point_base)
        self._remotefsclient = remotefs_brick.RemoteFsClient(
            'glusterfs', root_helper, execute,
            glusterfs_mount_point_base=self.base)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(GlusterfsDriver, self).do_setup(context)

        config = self.configuration.glusterfs_shares_config
        if not config:
            msg = (_("There's no Gluster config file configured (%s)") %
                   'glusterfs_shares_config')
            LOG.warning(msg)
            raise exception.GlusterfsException(msg)
        if not os.path.exists(config):
            msg = (_("Gluster config file at %(config)s doesn't exist") %
                   {'config': config})
            LOG.warning(msg)
            raise exception.GlusterfsException(msg)

        self.shares = {}

        try:
            self._execute('mount.glusterfs', check_exit_code=False)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise exception.GlusterfsException(
                    _('mount.glusterfs is not installed'))
            else:
                raise

        self._refresh_mounts()

    def _unmount_shares(self):
        self._load_shares_config(self.configuration.glusterfs_shares_config)
        for share in self.shares.keys():
            try:
                self._do_umount(True, share)
            except Exception as exc:
                LOG.warning(_LW('Exception during unmounting %s'), exc)

    def _do_umount(self, ignore_not_mounted, share):
        mount_path = self._get_mount_point_for_share(share)
        command = ['umount', mount_path]
        try:
            self._execute(*command, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            if ignore_not_mounted and 'not mounted' in exc.stderr:
                LOG.info(_LI("%s is already umounted"), share)
            else:
                LOG.error(_LE("Failed to umount %(share)s, reason=%(stderr)s"),
                          {'share': share, 'stderr': exc.stderr})
                raise

    def _refresh_mounts(self):
        try:
            self._unmount_shares()
        except processutils.ProcessExecutionError as exc:
            if 'target is busy' in exc.stderr:
                LOG.warning(_LW("Failed to refresh mounts, reason=%s"),
                            exc.stderr)
            else:
                raise

        self._ensure_shares_mounted()

    def _qemu_img_info(self, path, volume_name):
        return super(GlusterfsDriver, self)._qemu_img_info_base(
            path, volume_name, self.configuration.glusterfs_mount_point_base)

    def check_for_setup_error(self):
        """Just to override parent behavior."""
        pass

    def _local_volume_dir(self, volume):
        hashed = self._get_hash_str(volume['provider_location'])
        path = '%s/%s' % (self.configuration.glusterfs_mount_point_base,
                          hashed)
        return path

    def _active_volume_path(self, volume):
        volume_dir = self._local_volume_dir(volume)
        path = os.path.join(volume_dir,
                            self.get_active_image_from_info(volume))
        return path

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        super(GlusterfsDriver, self)._update_volume_stats()
        data = self._stats

        global_capacity = data['total_capacity_gb']
        global_free = data['free_capacity_gb']

        thin_enabled = self.configuration.nas_volume_prov_type == 'thin'
        if thin_enabled:
            provisioned_capacity = self._get_provisioned_capacity()
        else:
            provisioned_capacity = round(global_capacity - global_free, 2)

        data['provisioned_capacity_gb'] = provisioned_capacity
        data['max_over_subscription_ratio'] = (
            self.configuration.max_over_subscription_ratio)
        data['thin_provisioning_support'] = thin_enabled
        data['thick_provisioning_support'] = not thin_enabled

        self._stats = data

    @remotefs_drv.locked_volume_id_operation
    def create_volume(self, volume):
        """Creates a volume."""

        self._ensure_shares_mounted()

        volume['provider_location'] = self._find_share(volume['size'])

        LOG.info(_LI('casted to %s'), volume['provider_location'])

        self._do_create_volume(volume)

        return {'provider_location': volume['provider_location']}

    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size):
        """Copy data from snapshot to destination volume.

        This is done with a qemu-img convert to raw/qcow2 from the snapshot
        qcow2.
        """

        LOG.debug("snapshot: %(snap)s, volume: %(vol)s, "
                  "volume_size: %(size)s",
                  {'snap': snapshot['id'],
                   'vol': volume['id'],
                   'size': volume_size})

        info_path = self._local_path_volume_info(snapshot['volume'])
        snap_info = self._read_info_file(info_path)
        vol_path = self._local_volume_dir(snapshot['volume'])
        forward_file = snap_info[snapshot['id']]
        forward_path = os.path.join(vol_path, forward_file)

        # Find the file which backs this file, which represents the point
        # when this snapshot was created.
        img_info = self._qemu_img_info(forward_path,
                                       snapshot['volume']['name'])
        path_to_snap_img = os.path.join(vol_path, img_info.backing_file)

        path_to_new_vol = self._local_path_volume(volume)

        LOG.debug("will copy from snapshot at %s", path_to_snap_img)

        if self.configuration.nas_volume_prov_type == 'thin':
            out_format = 'qcow2'
        else:
            out_format = 'raw'

        image_utils.convert_image(path_to_snap_img,
                                  path_to_new_vol,
                                  out_format)

        self._set_rw_permissions_for_all(path_to_new_vol)

    @remotefs_drv.locked_volume_id_operation
    def delete_volume(self, volume):
        """Deletes a logical volume."""

        if not volume['provider_location']:
            LOG.warning(_LW('Volume %s does not have '
                            'provider_location specified, '
                            'skipping'), volume['name'])
            return

        self._ensure_share_mounted(volume['provider_location'])

        mounted_path = self._active_volume_path(volume)

        self._execute('rm', '-f', mounted_path, run_as_root=True)

        # If an exception (e.g. timeout) occurred during delete_snapshot, the
        # base volume may linger around, so just delete it if it exists
        base_volume_path = self._local_path_volume(volume)
        fileutils.delete_if_exists(base_volume_path)

        info_path = self._local_path_volume_info(volume)
        fileutils.delete_if_exists(info_path)

    def _get_matching_backing_file(self, backing_chain, snapshot_file):
        return next(f for f in backing_chain
                    if f.get('backing-filename', '') == snapshot_file)

    def ensure_export(self, ctx, volume):
        """Synchronously recreates an export for a logical volume."""

        self._ensure_share_mounted(volume['provider_location'])

    def create_export(self, ctx, volume, connector):
        """Exports the volume."""
        pass

    def remove_export(self, ctx, volume):
        """Removes an export for a logical volume."""

        pass

    def validate_connector(self, connector):
        pass

    @remotefs_drv.locked_volume_id_operation
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""

        # Find active qcow2 file
        active_file = self.get_active_image_from_info(volume)
        path = '%s/%s/%s' % (self.configuration.glusterfs_mount_point_base,
                             self._get_hash_str(volume['provider_location']),
                             active_file)

        data = {'export': volume['provider_location'],
                'name': active_file}
        if volume['provider_location'] in self.shares:
            data['options'] = self.shares[volume['provider_location']]

        # Test file for raw vs. qcow2 format
        info = self._qemu_img_info(path, volume['name'])
        data['format'] = info.file_format
        if data['format'] not in ['raw', 'qcow2']:
            msg = _('%s must be a valid raw or qcow2 image.') % path
            raise exception.InvalidVolume(msg)

        return {
            'driver_volume_type': 'glusterfs',
            'data': data,
            'mount_point_base': self._get_mount_point_base()
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        pass

    @remotefs_drv.locked_volume_id_operation
    def extend_volume(self, volume, size_gb):
        volume_path = self._active_volume_path(volume)

        info = self._qemu_img_info(volume_path, volume['name'])
        backing_fmt = info.file_format

        if backing_fmt not in ['raw', 'qcow2']:
            msg = _('Unrecognized backing format: %s')
            raise exception.InvalidVolume(msg % backing_fmt)

        # qemu-img can resize both raw and qcow2 files
        image_utils.resize_image(volume_path, size_gb)

    def _do_create_volume(self, volume):
        """Create a volume on given glusterfs_share.

        :param volume: volume reference
        """

        volume_path = self.local_path(volume)
        volume_size = volume['size']

        LOG.debug("creating new volume at %s", volume_path)

        if os.path.exists(volume_path):
            msg = _('file already exists at %s') % volume_path
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        if self.configuration.nas_volume_prov_type == 'thin':
            self._create_qcow2_file(volume_path, volume_size)
        else:
            try:
                self._fallocate(volume_path, volume_size)
            except processutils.ProcessExecutionError as exc:
                if 'Operation not supported' in exc.stderr:
                    LOG.warning(_LW('Fallocate not supported by current '
                                    'version of glusterfs. So falling '
                                    'back to dd.'))
                    self._create_regular_file(volume_path, volume_size)
                else:
                    fileutils.delete_if_exists(volume_path)
                    raise

        self._set_rw_permissions_for_all(volume_path)

    def _ensure_shares_mounted(self):
        """Mount all configured GlusterFS shares."""

        self._mounted_shares = []

        self._load_shares_config(self.configuration.glusterfs_shares_config)

        for share in self.shares.keys():
            try:
                self._ensure_share_mounted(share)
                self._mounted_shares.append(share)
            except Exception as exc:
                LOG.error(_LE('Exception during mounting %s'), exc)

        LOG.debug('Available shares: %s', self._mounted_shares)

    def _ensure_share_mounted(self, glusterfs_share):
        """Mount GlusterFS share.

        :param glusterfs_share: string
        """
        mount_path = self._get_mount_point_for_share(glusterfs_share)
        self._mount_glusterfs(glusterfs_share)

        # Ensure we can write to this share
        group_id = os.getegid()
        current_group_id = utils.get_file_gid(mount_path)
        current_mode = utils.get_file_mode(mount_path)

        if group_id != current_group_id:
            cmd = ['chgrp', group_id, mount_path]
            self._execute(*cmd, run_as_root=True)

        if not (current_mode & stat.S_IWGRP):
            cmd = ['chmod', 'g+w', mount_path]
            self._execute(*cmd, run_as_root=True)

        self._ensure_share_writable(mount_path)

    def _find_share(self, volume_size_for):
        """Choose GlusterFS share among available ones for given volume size.

        Current implementation looks for greatest capacity.
        :param volume_size_for: int size in GB
        """

        if not self._mounted_shares:
            raise exception.GlusterfsNoSharesMounted()

        greatest_size = 0
        greatest_share = None

        for glusterfs_share in self._mounted_shares:
            capacity = self._get_available_capacity(glusterfs_share)[0]
            if capacity > greatest_size:
                greatest_share = glusterfs_share
                greatest_size = capacity

        if volume_size_for * units.Gi > greatest_size:
            raise exception.GlusterfsNoSuitableShareFound(
                volume_size=volume_size_for)
        return greatest_share

    def _mount_glusterfs(self, glusterfs_share):
        """Mount GlusterFS share to mount path."""
        mnt_flags = []
        if self.shares.get(glusterfs_share) is not None:
            mnt_flags = self.shares[glusterfs_share].split()
        try:
            self._remotefsclient.mount(glusterfs_share, mnt_flags)
        except processutils.ProcessExecutionError:
            LOG.error(_LE("Mount failure for %(share)s."),
                      {'share': glusterfs_share})
            raise

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume.

        Allow a backup to occur only if no snapshots exist.
        Check both Cinder and the file on-disk.  The latter is only
        a safety mechanism to prevent further damage if the snapshot
        information is already inconsistent.
        """

        snapshots = self.db.snapshot_get_all_for_volume(context,
                                                        backup['volume_id'])
        snap_error_msg = _('Backup is not supported for GlusterFS '
                           'volumes with snapshots.')
        if len(snapshots) > 0:
            raise exception.InvalidVolume(snap_error_msg)

        volume = self.db.volume_get(context, backup['volume_id'])

        active_file_path = self._active_volume_path(volume)

        info = self._qemu_img_info(active_file_path, volume['name'])

        if info.backing_file is not None:
            LOG.error(_LE('No snapshots found in database, but %(path)s has '
                          'backing file %(backing_file)s!'),
                      {'path': active_file_path,
                       'backing_file': info.backing_file})
            raise exception.InvalidVolume(snap_error_msg)

        if info.file_format != 'raw':
            msg = _('Backup is only supported for raw-formatted '
                    'GlusterFS volumes.')
            raise exception.InvalidVolume(msg)

        return super(GlusterfsDriver, self).backup_volume(
            context, backup, backup_service)
