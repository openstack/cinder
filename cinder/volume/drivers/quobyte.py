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
import psutil

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils

from cinder import compute
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import utils
from cinder.volume import configuration
from cinder.volume.drivers import remotefs as remotefs_drv

VERSION = '1.1.6'

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('quobyte_volume_url',
               help=('Quobyte URL to the Quobyte volume e.g.,'
                     ' quobyte://<DIR host1>, <DIR host2>/<volume name>')),
    cfg.StrOpt('quobyte_client_cfg',
               help=('Path to a Quobyte Client configuration file.')),
    cfg.BoolOpt('quobyte_sparsed_volumes',
                default=True,
                help=('Create volumes as sparse files which take no space.'
                      ' If set to False, volume is created as regular file.')),
    cfg.BoolOpt('quobyte_qcow2_volumes',
                default=True,
                help=('Create volumes as QCOW2 files rather than raw files.')),
    cfg.StrOpt('quobyte_mount_point_base',
               default='$state_path/mnt',
               help=('Base dir containing the mount point'
                     ' for the Quobyte volume.')),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class QuobyteDriver(remotefs_drv.RemoteFSSnapDriverDistributed):
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
        1.1   - Adds optional insecure NAS settings
        1.1.1 - Removes getfattr calls from driver
        1.1.2 - Fixes a bug in the creation of cloned volumes
        1.1.3 - Explicitely mounts Quobyte volumes w/o xattrs
        1.1.4 - Fixes capability to configure redundancy in quobyte_volume_url
        1.1.5 - Enables extension of volumes with snapshots
        1.1.6 - Optimizes volume creation

    """

    driver_volume_type = 'quobyte'
    driver_prefix = 'quobyte'
    volume_backend_name = 'Quobyte'
    VERSION = VERSION

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Quobyte_CI"

    def __init__(self, execute=processutils.execute, *args, **kwargs):
        super(QuobyteDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)

        # Used to manage snapshots which are currently attached to a VM.
        self._nova = None

    def _create_regular_file(self, path, size):
        """Creates a regular file of given size in GiB."""
        self._execute('fallocate', '-l', '%sG' % size,
                      path, run_as_root=self._execute_as_root)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(QuobyteDriver, self).do_setup(context)

        self.set_nas_security_options(is_new_cinder_install=False)
        self.shares = {}  # address : options
        self._nova = compute.API()

    def check_for_setup_error(self):
        if not self.configuration.quobyte_volume_url:
            msg = (_("There's no Quobyte volume configured (%s). Example:"
                     " quobyte://<DIR host>/<volume name>") %
                   'quobyte_volume_url')
            LOG.warning(msg)
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
                raise

    def set_nas_security_options(self, is_new_cinder_install):
        self._execute_as_root = False

        LOG.debug("nas_secure_file_* settings are %(ops)s and %(perm)s",
                  {'ops': self.configuration.nas_secure_file_operations,
                   'perm': self.configuration.nas_secure_file_permissions}
                  )

        if self.configuration.nas_secure_file_operations == 'auto':
            """Note (kaisers): All previous Quobyte driver versions ran with
            secure settings hardcoded to 'True'. Therefore the default 'auto'
            setting can safely be mapped to the same, secure, setting.
            """
            LOG.debug("Mapping 'auto' value to 'true' for"
                      " nas_secure_file_operations.")
            self.configuration.nas_secure_file_operations = 'true'

        if self.configuration.nas_secure_file_permissions == 'auto':
            """Note (kaisers): All previous Quobyte driver versions ran with
            secure settings hardcoded to 'True'. Therefore the default 'auto'
            setting can safely be mapped to the same, secure, setting.
            """
            LOG.debug("Mapping 'auto' value to 'true' for"
                      " nas_secure_file_permissions.")
            self.configuration.nas_secure_file_permissions = 'true'

        if self.configuration.nas_secure_file_operations == 'false':
            LOG.warning("The NAS file operations will be run as "
                        "root, allowing root level access at the storage "
                        "backend.")
            self._execute_as_root = True
        else:
            LOG.info("The NAS file operations will be run as"
                     " non privileged user in secure mode. Please"
                     " ensure your libvirtd settings have been configured"
                     " accordingly (see section 'OpenStack' in the Quobyte"
                     " Manual.")

        if self.configuration.nas_secure_file_permissions == 'false':
            LOG.warning("The NAS file permissions mode will be 666 "
                        "(allowing other/world read & write access).")

    def _qemu_img_info(self, path, volume_name):
        return super(QuobyteDriver, self)._qemu_img_info_base(
            path, volume_name, self.configuration.quobyte_mount_point_base)

    @utils.synchronized('quobyte', external=False)
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        return self._create_cloned_volume(volume, src_vref)

    def _create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        Snapshot must not be the active snapshot. (offline)
        """

        LOG.debug('Creating volume %(vol)s from snapshot %(snap)s',
                  {'vol': volume.id, 'snap': snapshot.id})

        if snapshot.status != 'available':
            msg = _('Snapshot status must be "available" to clone. '
                    'But is: %(status)s') % {'status': snapshot.status}

            raise exception.InvalidSnapshot(msg)

        self._ensure_shares_mounted()

        volume.provider_location = self._find_share(volume)

        self._copy_volume_from_snapshot(snapshot,
                                        volume,
                                        volume.size)

        return {'provider_location': volume.provider_location}

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

        LOG.debug("snapshot: %(snap)s, volume: %(vol)s, ",
                  {'snap': snapshot.id,
                   'vol': volume.id,
                   'size': volume_size})

        info_path = self._local_path_volume_info(snapshot.volume)
        snap_info = self._read_info_file(info_path)
        vol_path = self._local_volume_dir(snapshot.volume)
        forward_file = snap_info[snapshot.id]
        forward_path = os.path.join(vol_path, forward_file)

        self._ensure_shares_mounted()
        # Find the file which backs this file, which represents the point
        # when this snapshot was created.
        img_info = self._qemu_img_info(forward_path,
                                       snapshot.volume.name)
        path_to_snap_img = os.path.join(vol_path, img_info.backing_file)

        path_to_new_vol = self._local_path_volume(volume)

        LOG.debug("will copy from snapshot at %s", path_to_snap_img)

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

        if not volume.provider_location:
            LOG.warning('Volume %s does not have provider_location '
                        'specified, skipping', volume.name)
            return

        self._ensure_share_mounted(volume.provider_location)

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
                             self._get_hash_str(volume.provider_location),
                             active_file)

        data = {'export': volume.provider_location,
                'name': active_file}
        if volume.provider_location in self.shares:
            data['options'] = self.shares[volume.provider_location]

        # Test file for raw vs. qcow2 format
        info = self._qemu_img_info(path, volume.name)
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

        info = self._qemu_img_info(volume_path, volume.name)
        backing_fmt = info.file_format

        if backing_fmt not in ['raw', 'qcow2']:
            msg = _('Unrecognized backing format: %s')
            raise exception.InvalidVolume(msg % backing_fmt)

        # qemu-img can resize both raw and qcow2 files
        active_path = os.path.join(
            self._get_mount_point_for_share(volume.provider_location),
            self.get_active_image_from_info(volume))
        image_utils.resize_image(active_path, size_gb)

    def _do_create_volume(self, volume):
        """Create a volume on given Quobyte volume.

        :param volume: volume reference
        """
        volume_path = self.local_path(volume)
        volume_size = volume.size

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

        :param share_file: string, Not used because the user has to specify
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
                LOG.warning('Exception during mounting %s', exc)

        LOG.debug('Available shares %s', self._mounted_shares)

    def _find_share(self, volume):
        """Returns the mounted Quobyte volume.

        Multiple shares are not supported because the virtualization of
        multiple storage devices is taken care of at the level of Quobyte USP.

        For different types of volumes e.g., SSD vs. rotating disks, use
        multiple backends in Cinder.

        :param volume: the volume to be created.
        """

        if not self._mounted_shares:
            raise exception.NotFound()

        assert len(self._mounted_shares) == 1, 'There must be exactly' \
            ' one Quobyte volume.'
        target_volume = self._mounted_shares[0]

        LOG.debug('Selected %s as target Quobyte volume.', target_volume)

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
                        LOG.info('Fixing previous mount %s which was not'
                                 ' unmounted correctly.', mount_path)
                        self._execute('umount.quobyte', mount_path,
                                      run_as_root=self._execute_as_root)
                    except processutils.ProcessExecutionError as exc:
                        LOG.warning("Failed to unmount previous mount: "
                                    "%s", exc)
                else:
                    # TODO(quobyte): Extend exc analysis in here?
                    LOG.warning("Unknown error occurred while checking "
                                "mount point: %s Trying to continue.",
                                exc)

        if not mounted:
            if not os.path.isdir(mount_path):
                self._execute('mkdir', '-p', mount_path)

            command = ['mount.quobyte', '--disable-xattrs',
                       quobyte_volume, mount_path]
            if self.configuration.quobyte_client_cfg:
                command.extend(['-c', self.configuration.quobyte_client_cfg])

            try:
                LOG.info('Mounting volume: %s ...', quobyte_volume)
                self._execute(*command, run_as_root=self._execute_as_root)
                LOG.info('Mounting volume: %s succeeded', quobyte_volume)
                mounted = True
            except processutils.ProcessExecutionError as exc:
                if ensure and 'already mounted' in exc.stderr:
                    LOG.warning("%s is already mounted", quobyte_volume)
                else:
                    raise

        if mounted:
            self._validate_volume(mount_path)

    def _validate_volume(self, mount_path):
        """Runs a number of tests on the expect Quobyte mount"""
        partitions = psutil.disk_partitions(all=True)
        for p in partitions:
            if mount_path == p.mountpoint:
                if p.device.startswith("quobyte@"):
                    try:
                        statresult = os.stat(mount_path)
                        if statresult.st_size == 0:
                            # client looks healthy
                            if not os.access(mount_path,
                                             os.W_OK | os.X_OK):
                                LOG.warning("Volume is not writable. "
                                            "Please broaden the file"
                                            " permissions."
                                            " Mount: %s",
                                            mount_path)
                            return  # we're happy here
                        else:
                            msg = (_("The mount %(mount_path)s is not a "
                                     "valid Quobyte volume. Stale mount?")
                                   % {'mount_path': mount_path})
                        raise exception.VolumeDriverException(msg)
                    except Exception as exc:
                        msg = (_("The mount %(mount_path)s is not a valid"
                                 " Quobyte volume. Error: %(exc)s . "
                                 " Possibly a Quobyte client crash?")
                               % {'mount_path': mount_path, 'exc': exc})
                        raise exception.VolumeDriverException(msg)
                else:
                    msg = (_("The mount %(mount_path)s is not a valid"
                             " Quobyte volume according to partition list.")
                           % {'mount_path': mount_path})
                    raise exception.VolumeDriverException(msg)
        msg = (_("No matching Quobyte mount entry for %(mount_path)s"
                 " could be found for validation in partition list.")
               % {'mount_path': mount_path})
        raise exception.VolumeDriverException(msg)
