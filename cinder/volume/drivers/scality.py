# Copyright (c) 2015 Scality
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
Scality SOFS Volume Driver.
"""


import errno
import os

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
import six
from six.moves import urllib

from cinder import exception
from cinder.i18n import _, _LI
from cinder.image import image_utils
from cinder import utils
from cinder.volume.drivers import remotefs as remotefs_drv
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('scality_sofs_config',
               help='Path or URL to Scality SOFS configuration file'),
    cfg.StrOpt('scality_sofs_mount_point',
               default='$state_path/scality',
               help='Base dir where Scality SOFS shall be mounted'),
    cfg.StrOpt('scality_sofs_volume_dir',
               default='cinder/volumes',
               help='Path from Scality SOFS root to volume dir'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


class ScalityDriver(remotefs_drv.RemoteFSSnapDriver):
    """Scality SOFS cinder driver.

    Creates sparse files on SOFS for hypervisors to use as block
    devices.
    """

    driver_volume_type = 'scality'
    driver_prefix = 'scality_sofs'
    volume_backend_name = 'Scality_SOFS'
    VERSION = '2.0.0'

    def __init__(self, *args, **kwargs):
        super(ScalityDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)

        self.sofs_mount_point = self.configuration.scality_sofs_mount_point
        self.sofs_config = self.configuration.scality_sofs_config
        self.sofs_rel_volume_dir = self.configuration.scality_sofs_volume_dir
        self.sofs_abs_volume_dir = os.path.join(self.sofs_mount_point,
                                                self.sofs_rel_volume_dir)

        # The following config flag is used by RemoteFSDriver._do_create_volume
        # We want to use sparse file (ftruncated) without exposing this
        # as a config switch to customers.
        self.configuration.scality_sofs_sparsed_volumes = True

    def check_for_setup_error(self):
        """Sanity checks before attempting to mount SOFS."""

        # config is mandatory
        if not self.sofs_config:
            msg = _("Value required for 'scality_sofs_config'")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # config can be a file path or a URL, check it
        config = self.sofs_config
        if urllib.parse.urlparse(self.sofs_config).scheme == '':
            # turn local path into URL
            config = 'file://%s' % self.sofs_config
        try:
            urllib.request.urlopen(config, timeout=5).close()
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            msg = _("Can't access 'scality_sofs_config'"
                    ": %s") % six.text_type(e)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # mount.sofs must be installed
        if not os.access('/sbin/mount.sofs', os.X_OK):
            msg = _("Cannot execute /sbin/mount.sofs")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _load_shares_config(self, share_file=None):
        self.shares[self.sofs_rel_volume_dir] = None

    def _get_mount_point_for_share(self, share=None):
        # The _qemu_img_info_base() method from the RemoteFSSnapDriver class
        # expects files (volume) to be inside a subdir of the mount point.
        # So we have to append a dummy subdir.
        return self.sofs_abs_volume_dir + "/00"

    def _sofs_is_mounted(self):
        """Check if SOFS is already mounted at the expected location."""
        mount_path = self.sofs_mount_point.rstrip('/')
        for mount in volume_utils.read_proc_mounts():
            parts = mount.split()
            if (parts[0].endswith('fuse') and
                    parts[1].rstrip('/') == mount_path):
                return True
        return False

    @lockutils.synchronized('mount-sofs', 'cinder-sofs', external=True)
    def _ensure_share_mounted(self, share=None):
        """Mount SOFS if need be."""
        fileutils.ensure_tree(self.sofs_mount_point)

        if not self._sofs_is_mounted():
            self._execute('mount', '-t', 'sofs', self.sofs_config,
                          self.sofs_mount_point, run_as_root=True)
        if not self._sofs_is_mounted():
            msg = _("Cannot mount Scality SOFS, check syslog for errors")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        fileutils.ensure_tree(self.sofs_abs_volume_dir)

        # We symlink the '00' subdir to its parent dir to maintain
        # compatibility with previous version of this driver.
        try:
            os.symlink(".", self._get_mount_point_for_share())
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                if not os.path.islink(self._get_mount_point_for_share()):
                    raise
            else:
                raise

    def _ensure_shares_mounted(self):
        self._ensure_share_mounted()
        self._mounted_shares = [self.sofs_rel_volume_dir]

    def _find_share(self, volume_size_for):
        try:
            return self._mounted_shares[0]
        except IndexError:
            raise exception.RemoteFSNoSharesMounted()

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service."""
        stats = {
            'vendor_name': 'Scality',
            'driver_version': self.VERSION,
            'storage_protocol': 'scality',
            'total_capacity_gb': 'infinite',
            'free_capacity_gb': 'infinite',
            'reserved_percentage': 0,
        }
        backend_name = self.configuration.safe_get('volume_backend_name')
        stats['volume_backend_name'] = backend_name or self.volume_backend_name
        return stats

    @remotefs_drv.locked_volume_id_operation
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""

        # Find active qcow2 file
        active_file = self.get_active_image_from_info(volume)
        path = '%s/%s' % (self._get_mount_point_for_share(), active_file)
        sofs_rel_path = os.path.join(self.sofs_rel_volume_dir, "00",
                                     volume['name'])

        data = {'export': volume['provider_location'],
                'name': active_file,
                'sofs_path': sofs_rel_path}

        # Test file for raw vs. qcow2 format
        info = self._qemu_img_info(path, volume['name'])
        data['format'] = info.file_format
        if data['format'] not in ['raw', 'qcow2']:
            msg = _('%s must be a valid raw or qcow2 image.') % path
            raise exception.InvalidVolume(msg)

        return {
            'driver_volume_type': self.driver_volume_type,
            'data': data,
            'mount_point_base': self.sofs_mount_point
        }

    def _qemu_img_info(self, path, volume_name):
        return super(ScalityDriver, self)._qemu_img_info_base(
            path, volume_name, self.sofs_abs_volume_dir)

    @remotefs_drv.locked_volume_id_operation
    def extend_volume(self, volume, size_gb):
        volume_path = self.local_path(volume)

        info = self._qemu_img_info(volume_path, volume['name'])
        backing_fmt = info.file_format

        if backing_fmt not in ['raw', 'qcow2']:
            msg = _('Unrecognized backing format: %s')
            raise exception.InvalidVolume(msg % backing_fmt)

        # qemu-img can resize both raw and qcow2 files
        image_utils.resize_image(volume_path, size_gb)

    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size):
        """Copy data from snapshot to destination volume.

        This is done with a qemu-img convert to raw/qcow2 from the snapshot
        qcow2.
        """

        info_path = self._local_path_volume_info(snapshot['volume'])

        # For BC compat' with version < 2 of this driver
        try:
            snap_info = self._read_info_file(info_path)
        except IOError as exc:
            if exc.errno != errno.ENOENT:
                raise
            else:
                path_to_snap_img = self.local_path(snapshot)
        else:
            vol_path = self._local_volume_dir(snapshot['volume'])

            forward_file = snap_info[snapshot['id']]
            forward_path = os.path.join(vol_path, forward_file)

            # Find the file which backs this file, which represents the point
            # when this snapshot was created.
            img_info = self._qemu_img_info(forward_path,
                                           snapshot['volume']['name'])

            path_to_snap_img = os.path.join(vol_path, img_info.backing_file)

        LOG.debug("will copy from snapshot at %s", path_to_snap_img)

        path_to_new_vol = self.local_path(volume)
        out_format = 'raw'
        image_utils.convert_image(path_to_snap_img,
                                  path_to_new_vol,
                                  out_format,
                                  run_as_root=self._execute_as_root)

        self._set_rw_permissions_for_all(path_to_new_vol)

        image_utils.resize_image(path_to_new_vol, volume_size)

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume."""
        volume = self.db.volume_get(context, backup['volume_id'])
        volume_local_path = self.local_path(volume)
        LOG.info(_LI('Begin backup of volume %s.'), volume['name'])

        qemu_img_info = image_utils.qemu_img_info(volume_local_path)
        if qemu_img_info.file_format != 'raw':
            msg = _('Backup is only supported for raw-formatted '
                    'SOFS volumes.')
            raise exception.InvalidVolume(msg)

        if qemu_img_info.backing_file is not None:
            msg = _('Backup is only supported for SOFS volumes '
                    'without backing file.')
            raise exception.InvalidVolume(msg)

        with utils.temporary_chown(volume_local_path):
            with open(volume_local_path) as volume_file:
                backup_service.backup(backup, volume_file)

    def restore_backup(self, context, backup, volume, backup_service):
        """Restore an existing backup to a new or existing volume."""
        LOG.info(_LI('Restoring backup %(backup)s to volume %(volume)s.'),
                 {'backup': backup['id'], 'volume': volume['name']})
        volume_local_path = self.local_path(volume)
        with utils.temporary_chown(volume_local_path):
            with open(volume_local_path, 'wb') as volume_file:
                backup_service.restore(backup, volume['id'], volume_file)
