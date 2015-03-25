# Copyright (c) 2014 Quobyte Inc.
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

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging

from cinder import compute
from cinder import exception
from cinder.i18n import _, _LI, _LW
from cinder.image import image_utils
from cinder.openstack.common import fileutils
from cinder import utils
from cinder.volume.drivers import remotefs as remotefs_drv

VERSION = '1.0'

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('quobyte_volume_url',
               default=None,
               help=('URL to the Quobyte volume e.g.,'
                     ' quobyte://<DIR host>/<volume name>')),
    cfg.StrOpt('quobyte_client_cfg',
               default=None,
               help=('Path to a Quobyte Client configuration file.')),
    cfg.BoolOpt('quobyte_sparsed_volumes',
                default=True,
                help=('Create volumes as sparse files which take no space.'
                      ' If set to False, volume is created as regular file.'
                      'In such case volume creation takes a lot of time.')),
    cfg.BoolOpt('quobyte_qcow2_volumes',
                default=True,
                help=('Create volumes as QCOW2 files rather than raw files.')),
    cfg.StrOpt('quobyte_mount_point_base',
               default='$state_path/mnt',
               help=('Base dir containing the mount point'
                     ' for the Quobyte volume.')),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


class QuobyteDriver(remotefs_drv.RemoteFSSnapDriver):
    """Cinder driver for Quobyte USP.

    Volumes are stored as files on the mounted Quobyte volume. The hypervisor
    will expose them as block devices.

    Unlike other similar drivers, this driver uses exactly one Quobyte volume
    because Quobyte USP is a distributed storage system. To add or remove
    capacity, administrators can add or remove storage servers to/from the
    volume.

    For different types of volumes e.g., SSD vs. rotating disks,
    use multiple backends in Cinder.

    Note: To be compliant with the inherited RemoteFSSnapDriver, Quobyte
          volumes are also referred to as shares.

    Version history:
        1.0   - Initial driver.
    """

    driver_volume_type = 'quobyte'
    driver_prefix = 'quobyte'
    volume_backend_name = 'Quobyte'
    VERSION = VERSION

    def __init__(self, execute=processutils.execute, *args, **kwargs):
        super(QuobyteDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)

        # Used to manage snapshots which are currently attached to a VM.
        self._nova = None

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        self.set_nas_security_options(is_new_cinder_install=False)
        super(QuobyteDriver, self).do_setup(context)

        self.shares = {}  # address : options
        self._nova = compute.API()

    def check_for_setup_error(self):
        if not self.configuration.quobyte_volume_url:
            msg = (_LW("There's no Quobyte volume configured (%s). Example:"
                       " quobyte://<DIR host>/<volume name>") %
                   'quobyte_volume_url')
            LOG.warn(msg)
            raise exception.VolumeDriverException(msg)

        # Check if mount.quobyte is installed
        try:
            self._execute('mount.quobyte', check_exit_code=False,
                          run_as_root=False)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise exception.VolumeDriverException(
                    'mount.quobyte is not installed')
            else:
                raise exc

    def set_nas_security_options(self, is_new_cinder_install):
        self.configuration.nas_secure_file_operations = 'true'
        self.configuration.nas_secure_file_permissions = 'true'
        self._execute_as_root = False

    def _qemu_img_info(self, path, volume_name):
        return super(QuobyteDriver, self)._qemu_img_info_base(
            path, volume_name, self.configuration.quobyte_mount_point_base)

    @utils.synchronized('quobyte', external=False)
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        self._create_cloned_volume(volume, src_vref)

    @utils.synchronized('quobyte', external=False)
    def create_volume(self, volume):
        return super(QuobyteDriver, self).create_volume(volume)

    @utils.synchronized('quobyte', external=False)
    def create_volume_from_snapshot(self, volume, snapshot):
        return self._create_volume_from_snapshot(volume, snapshot)

    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size):
        """Copy data from snapshot to destination volume.

        This is done with a qemu-img convert to raw/qcow2 from the snapshot
        qcow2.
        """

        LOG.debug("snapshot: %(snap)s, volume: %(vol)s, "
                  "volume_size: %(size)s"
                  % {'snap': snapshot['id'],
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

        LOG.debug("will copy from snapshot at %s" % path_to_snap_img)

        if self.configuration.quobyte_qcow2_volumes:
            out_format = 'qcow2'
        else:
            out_format = 'raw'

        image_utils.convert_image(path_to_snap_img,
                                  path_to_new_vol,
                                  out_format,
                                  run_as_root=self._execute_as_root)

        self._set_rw_permissions_for_all(path_to_new_vol)

    @utils.synchronized('quobyte', external=False)
    def delete_volume(self, volume):
        """Deletes a logical volume."""

        if not volume['provider_location']:
            LOG.warn(_LW('Volume %s does not have provider_location '
                     'specified, skipping'), volume['name'])
            return

        self._ensure_share_mounted(volume['provider_location'])

        volume_dir = self._local_volume_dir(volume)
        mounted_path = os.path.join(volume_dir,
                                    self.get_active_image_from_info(volume))

        self._execute('rm', '-f', mounted_path,
                      run_as_root=self._execute_as_root)

        # If an exception (e.g. timeout) occurred during delete_snapshot, the
        # base volume may linger around, so just delete it if it exists
        base_volume_path = self._local_path_volume(volume)
        fileutils.delete_if_exists(base_volume_path)

        info_path = self._local_path_volume_info(volume)
        fileutils.delete_if_exists(info_path)

    @utils.synchronized('quobyte', external=False)
    def create_snapshot(self, snapshot):
        """Apply locking to the create snapshot operation."""

        return self._create_snapshot(snapshot)

    @utils.synchronized('quobyte', external=False)
    def delete_snapshot(self, snapshot):
        """Apply locking to the delete snapshot operation."""
        self._delete_snapshot(snapshot)

    @utils.synchronized('quobyte', external=False)
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""

        # Find active qcow2 file
        active_file = self.get_active_image_from_info(volume)
        path = '%s/%s/%s' % (self.configuration.quobyte_mount_point_base,
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
            'driver_volume_type': 'quobyte',
            'data': data,
            'mount_point_base': self.configuration.quobyte_mount_point_base
        }

    @utils.synchronized('quobyte', external=False)
    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        self._copy_volume_to_image(context, volume, image_service,
                                   image_meta)

    @utils.synchronized('quobyte', external=False)
    def extend_volume(self, volume, size_gb):
        volume_path = self.local_path(volume)
        volume_filename = os.path.basename(volume_path)

        # Ensure no snapshots exist for the volume
        active_image = self.get_active_image_from_info(volume)
        if volume_filename != active_image:
            msg = _('Extend volume is only supported for this'
                    ' driver when no snapshots exist.')
            raise exception.InvalidVolume(msg)

        info = self._qemu_img_info(volume_path, volume['name'])
        backing_fmt = info.file_format

        if backing_fmt not in ['raw', 'qcow2']:
            msg = _('Unrecognized backing format: %s')
            raise exception.InvalidVolume(msg % backing_fmt)

        # qemu-img can resize both raw and qcow2 files
        image_utils.resize_image(volume_path, size_gb)

    def _do_create_volume(self, volume):
        """Create a volume on given Quobyte volume.

        :param volume: volume reference
        """
        volume_path = self.local_path(volume)
        volume_size = volume['size']

        if self.configuration.quobyte_qcow2_volumes:
            self._create_qcow2_file(volume_path, volume_size)
        else:
            if self.configuration.quobyte_sparsed_volumes:
                self._create_sparsed_file(volume_path, volume_size)
            else:
                self._create_regular_file(volume_path, volume_size)

        self._set_rw_permissions_for_all(volume_path)

    def _load_shares_config(self, share_file=None):
        """Put 'quobyte_volume_url' into the 'shares' list.
        :param share_file: string, Not used because the user has to specify the
                                   the Quobyte volume directly.
        """
        self.shares = {}

        url = self.configuration.quobyte_volume_url

        # Strip quobyte:// from the URL
        protocol = self.driver_volume_type + "://"
        if url.startswith(protocol):
            url = url[len(protocol):]

        self.shares[url] = None  # None = No extra mount options.

        LOG.debug("Quobyte Volume URL set to: %s", self.shares)

    def _ensure_share_mounted(self, quobyte_volume):
        """Mount Quobyte volume.
        :param quobyte_volume: string
        """
        mount_path = self._get_mount_point_for_share(quobyte_volume)
        self._mount_quobyte(quobyte_volume, mount_path, ensure=True)

    @utils.synchronized('quobyte_ensure', external=False)
    def _ensure_shares_mounted(self):
        """Mount the Quobyte volume.

        Used for example by RemoteFsDriver._update_volume_stats
        """
        self._mounted_shares = []

        self._load_shares_config()

        for share in self.shares.keys():
            try:
                self._ensure_share_mounted(share)
                self._mounted_shares.append(share)
            except Exception as exc:
                LOG.warning(_LW('Exception during mounting %s'), exc)

        LOG.debug('Available shares %s', self._mounted_shares)

    def _find_share(self, volume_size_in_gib):
        """Returns the mounted Quobyte volume.

        Multiple shares are not supported because the virtualization of
        multiple storage devices is taken care of at the level of Quobyte USP.

        For different types of volumes e.g., SSD vs. rotating disks, use
        multiple backends in Cinder.

        :param volume_size_in_gib: int size in GB. Ignored by this driver.
        """

        if not self._mounted_shares:
            raise exception.NotFound()

        assert len(self._mounted_shares) == 1, 'There must be exactly' \
            ' one Quobyte volume.'
        target_volume = self._mounted_shares[0]

        LOG.debug('Selected %s as target Quobyte volume.' % target_volume)

        return target_volume

    def _get_mount_point_for_share(self, quobyte_volume):
        """Return mount point for Quobyte volume.
        :param quobyte_volume: Example: storage-host/openstack-volumes
        """
        return os.path.join(self.configuration.quobyte_mount_point_base,
                            self._get_hash_str(quobyte_volume))

    # open() wrapper to mock reading from /proc/mount.
    @staticmethod
    def read_proc_mount():  # pragma: no cover
        return open('/proc/mounts')

    def _mount_quobyte(self, quobyte_volume, mount_path, ensure=False):
        """Mount Quobyte volume to mount path."""
        mounted = False
        for l in QuobyteDriver.read_proc_mount():
            if l.split()[1] == mount_path:
                mounted = True
                break

        if mounted:
            try:
                os.stat(mount_path)
            except OSError as exc:
                if exc.errno == errno.ENOTCONN:
                    mounted = False
                    try:
                        LOG.info(_LI('Fixing previous mount %s which was not'
                                     ' unmounted correctly.') % mount_path)
                        self._execute('umount.quobyte', mount_path,
                                      run_as_root=False)
                    except processutils.ProcessExecutionError as exc:
                        LOG.warn(_LW("Failed to unmount previous mount: %s"),
                                 exc)
                else:
                    # TODO(quobyte): Extend exc analysis in here?
                    LOG.warn(_LW("Unknown error occurred while checking mount"
                                 " point: %s Trying to continue."), exc)

        if not mounted:
            if not os.path.isdir(mount_path):
                self._execute('mkdir', '-p', mount_path)

            command = ['mount.quobyte', quobyte_volume, mount_path]
            if self.configuration.quobyte_client_cfg:
                command.extend(['-c', self.configuration.quobyte_client_cfg])

            try:
                LOG.info(_LI('Mounting volume: %s ...') % quobyte_volume)
                self._execute(*command, run_as_root=False)
                LOG.info(_LI('Mounting volume: %s succeeded') % quobyte_volume)
                mounted = True
            except processutils.ProcessExecutionError as exc:
                if ensure and 'already mounted' in exc.stderr:
                    LOG.warn(_LW("%s is already mounted"), quobyte_volume)
                else:
                    raise

        if mounted:
            self._validate_volume(mount_path)

    def _validate_volume(self, mount_path):
        """Wraps execute calls for checking validity of a Quobyte volume"""
        command = ['getfattr', "-n", "quobyte.info", mount_path]
        try:
            self._execute(*command, run_as_root=False)
        except processutils.ProcessExecutionError as exc:
            msg = (_("The mount %(mount_path)s is not a valid"
                     " Quobyte USP volume. Error: %(exc)s")
                   % {'mount_path': mount_path, 'exc': exc})
            raise exception.VolumeDriverException(msg)

        if not os.access(mount_path, os.W_OK | os.X_OK):
            LOG.warn(_LW("Volume is not writable. Please broaden the file"
                         " permissions. Mount: %s"), mount_path)
