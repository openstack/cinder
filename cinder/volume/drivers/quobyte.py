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
import shutil

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import fnmatch

from cinder import compute
from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import utils
from cinder.volume import configuration
from cinder.volume.drivers import remotefs as remotefs_drv

VERSION = '1.1.11'

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('quobyte_volume_url',
               help=('Quobyte URL to the Quobyte volume using e.g. a DNS SRV'
                     ' record (preferred) or a host list (alternatively) like'
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
    cfg.BoolOpt('quobyte_volume_from_snapshot_cache',
                default=False,
                help=('Create a cache of volumes from merged snapshots to '
                      'speed up creation of multiple volumes from a single '
                      'snapshot.')),
    cfg.BoolOpt('quobyte_overlay_volumes',
                default=False,
                help=('Create new volumes from the volume_from_snapshot_cache'
                      ' by creating overlay files instead of full copies. This'
                      ' speeds up the creation of volumes from this cache.'
                      ' This feature requires the options'
                      ' quobyte_qcow2_volumes and'
                      ' quobyte_volume_from_snapshot_cache to be set to'
                      ' True. If one of these is set to False this option is'
                      ' ignored.'))
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


    .. code-block:: none

      Version history:

        1.0   - Initial driver.
        1.1   - Adds optional insecure NAS settings
        1.1.1 - Removes getfattr calls from driver
        1.1.2 - Fixes a bug in the creation of cloned volumes
        1.1.3 - Explicitely mounts Quobyte volumes w/o xattrs
        1.1.4 - Fixes capability to configure redundancy in quobyte_volume_url
        1.1.5 - Enables extension of volumes with snapshots
        1.1.6 - Optimizes volume creation
        1.1.7 - Support fuse subtype based Quobyte mount validation
        1.1.8 - Adds optional snapshot merge caching
        1.1.9 - Support for Qemu >= 2.10.0
        1.1.10 - Adds overlay based volumes for snapshot merge caching
        1.1.11 - NAS secure ownership & permissions are now False by default

    """

    driver_volume_type = 'quobyte'
    driver_prefix = 'quobyte'
    volume_backend_name = 'Quobyte'
    VERSION = VERSION

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Quobyte_CI"

    QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME = "volume_from_snapshot_cache"

    def __init__(self, execute=processutils.execute, *args, **kwargs):
        super(QuobyteDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)

        # Used to manage snapshots which are currently attached to a VM.
        self._nova = None

    @staticmethod
    def get_driver_options():
        return volume_opts

    def _create_regular_file(self, path, size):
        """Creates a regular file of given size in GiB using fallocate."""
        self._fallocate_file(path, size)

    @coordination.synchronized('{self.driver_prefix}-{snapshot.id}')
    def _delete_snapshot(self, snapshot):
        cache_path = self._local_volume_from_snap_cache_path(snapshot)
        if os.access(cache_path, os.F_OK):
            self._remove_from_vol_cache(
                cache_path,
                ".parent-" + snapshot.id, snapshot.volume)
        super(QuobyteDriver, self)._delete_snapshot(snapshot)

    def _ensure_volume_from_snap_cache(self, mount_path):
        """This expects the Quobyte volume to be mounted & available"""
        cache_path = os.path.join(mount_path,
                                  self.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME)
        if not os.access(cache_path, os.F_OK):
            LOG.info("Volume from snapshot cache directory does not exist, "
                     "creating the directory %(volcache)s",
                     {'volcache': cache_path})
            fileutils.ensure_tree(cache_path)
        if not (os.access(cache_path, os.R_OK)
                and os.access(cache_path, os.W_OK)
                and os.access(cache_path, os.X_OK)):
            msg = _("Insufficient permissions for Quobyte volume from "
                    "snapshot cache directory at %(cpath)s. Please update "
                    "permissions.") % {'cpath': cache_path}
            raise exception.VolumeDriverException(msg)
        LOG.debug("Quobyte volume from snapshot cache directory validated ok")

    def _fallocate_file(self, path, size):
        """Calls fallocate on the given path with the given size in GiB."""
        self._execute('fallocate', '-l', '%sGiB' % size,
                      path, run_as_root=self._execute_as_root)

    def _get_backing_chain_for_path(self, volume, path):
        raw_chain = super(QuobyteDriver, self)._get_backing_chain_for_path(
            volume, path)
        # NOTE(kaisers): if the last element resides in the cache snip it off,
        # as the RemoteFS driver cannot handle it.
        if len(raw_chain) and (self.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME in
                               raw_chain[-1]['filename']):
            del raw_chain[-1]
        return raw_chain

    def _local_volume_from_snap_cache_path(self, snapshot):
        path_to_disk = os.path.join(
            self._local_volume_dir(snapshot.volume),
            self.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME,
            snapshot.id)

        return path_to_disk

    def _qemu_img_info_base(self, path, volume_name, basedir,
                            force_share=True,
                            run_as_root=False):
        # NOTE(kaisers): This uses a specialized backing file template in
        # order to allow for backing files in the volume_from_snapshot_cache.
        backing_file_template = remotefs_drv.BackingFileTemplate(
            "(#basedir/[0-9a-f]+/)?("
            "#volname(.(tmp-snap-)?[0-9a-f-]+)?#valid_ext|"
            "%(cache)s/(tmp-snap-)?[0-9a-f-]+(.(child-|parent-)"
            "[0-9a-f-]+)?)$" % {
                'cache': self.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME
            })
        return super(QuobyteDriver, self)._qemu_img_info_base(
            path, volume_name, basedir, ext_bf_template=backing_file_template,
            force_share=True)

    def _remove_from_vol_cache(self, cache_file_path, ref_suffix, volume):
        """Removes a reference and possibly volume from the volume cache

        This method removes the ref_id reference (soft link) from the cache.
        If no other references exist the cached volume itself is removed,
        too.

        :param cache_file_path file path to the volume in the cache
        :param ref_suffix The id based suffix of the cache file reference
        :param volume The volume whose share defines the cache to address
        """
        # NOTE(kaisers): As the cache_file_path may be a relative path we use
        # cache dir and file name to ensure absolute paths in all operations.
        cache_path = os.path.join(self._local_volume_dir(volume),
                                  self.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME)
        cache_file_name = os.path.basename(cache_file_path)
        # delete the reference
        LOG.debug("Deleting cache reference %(cfp)s%(rs)s",
                  {"cfp": cache_file_path, "rs": ref_suffix})
        fileutils.delete_if_exists(os.path.join(cache_path,
                                                cache_file_name + ref_suffix))

        # If no other reference exists, remove the cache entry.
        for file in os.listdir(cache_path):
            if fnmatch.fnmatch(file, cache_file_name + ".*"):
                # found another reference file, keep cache entry
                LOG.debug("Cached volume %(file)s still has at least one "
                          "reference: %(ref)s",
                          {"file": cache_file_name, "ref": file})
                return
        # No other reference found, remove cache entry
        LOG.debug("Removing cached volume %(cvol)s as no more references for "
                  "this cached volume exist.",
                  {"cvol": os.path.join(cache_path, cache_file_name)})
        fileutils.delete_if_exists(os.path.join(cache_path, cache_file_name))

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(QuobyteDriver, self).do_setup(context)

        self.set_nas_security_options(is_new_cinder_install=False)
        self.shares = {}  # address : options
        self._nova = compute.API()
        self.base = self.configuration.quobyte_mount_point_base
        if self.configuration.quobyte_overlay_volumes:
            if not (self.configuration.quobyte_qcow2_volumes and
                    self.configuration.quobyte_volume_from_snapshot_cache):
                self.configuration.quobyte_overlay_volumes = False
                LOG.warning("Configuration of quobyte_qcow2_volumes and "
                            "quobyte_volume_from_snapshot_cache is "
                            "incompatible with "
                            "quobyte_overlay_volumes=True. "
                            "quobyte_overlay_volumes "
                            "setting will be ignored.")

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

        LOG.debug("nas_secure_file_* settings are %(ops)s (ownership) and "
                  "%(perm)s (permissions).",
                  {'ops': self.configuration.nas_secure_file_operations,
                   'perm': self.configuration.nas_secure_file_permissions}
                  )

        if self.configuration.nas_secure_file_operations == 'auto':
            LOG.debug("Mapping 'auto' value to 'false' for"
                      " nas_secure_file_operations.")
            self.configuration.nas_secure_file_operations = 'false'

        if self.configuration.nas_secure_file_permissions == 'auto':
            LOG.debug("Mapping 'auto' value to 'false' for"
                      " nas_secure_file_permissions.")
            self.configuration.nas_secure_file_permissions = 'false'

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

    def _qemu_img_info(self, path, volume_name, force_share=True):
        return self._qemu_img_info_base(
            path, volume_name, self.configuration.quobyte_mount_point_base,
            force_share=True)

    @utils.synchronized('quobyte', external=False)
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        return self._create_cloned_volume(volume, src_vref,
                                          src_vref.obj_context)

    @coordination.synchronized(
        '{self.driver_prefix}-{snapshot.id}-{volume.id}')
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

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size):
        """Copy data from snapshot to destination volume.

        This is done with a qemu-img convert to raw/qcow2 from the snapshot
        qcow2. If the quobyte_volume_from_snapshot_cache is active the result
        is written into the cache and all volumes created from this
        snapshot id are created directly from the cache.
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
        img_info = self._qemu_img_info(forward_path, snapshot.volume.name)
        path_to_snap_img = os.path.join(vol_path, img_info.backing_file)

        path_to_new_vol = self._local_path_volume(volume)
        path_to_cached_vol = self._local_volume_from_snap_cache_path(snapshot)

        LOG.debug("will copy from snapshot at %s", path_to_snap_img)

        if self.configuration.quobyte_qcow2_volumes:
            out_format = 'qcow2'
        else:
            out_format = 'raw'

        if not self.configuration.quobyte_volume_from_snapshot_cache:
            LOG.debug("Creating direct copy from snapshot")
            image_utils.convert_image(path_to_snap_img,
                                      path_to_new_vol,
                                      out_format,
                                      run_as_root=self._execute_as_root)
        else:
            # create the volume via volume cache
            if not os.access(path_to_cached_vol, os.F_OK):
                LOG.debug("Caching volume %(volpath)s from snapshot.",
                          {'volpath': path_to_cached_vol})
                image_utils.convert_image(path_to_snap_img,
                                          path_to_cached_vol,
                                          out_format,
                                          run_as_root=self._execute_as_root)
                if self.configuration.quobyte_overlay_volumes:
                    # NOTE(kaisers): Create a parent symlink to track the
                    # existence of the parent
                    os.symlink(path_to_snap_img, path_to_cached_vol
                               + '.parent-' + snapshot.id)
            if self.configuration.quobyte_overlay_volumes:
                self._create_overlay_volume_from_snapshot(volume,
                                                          snapshot,
                                                          volume_size,
                                                          out_format)
            else:
                # Copy volume from cache
                LOG.debug("Copying volume %(volpath)s from cache",
                          {'volpath': path_to_new_vol})
                shutil.copyfile(path_to_cached_vol, path_to_new_vol)
                # Note(kaisers): As writes beyond EOF are sequentialized with
                # FUSE we call fallocate here to optimize performance:
                self._fallocate_file(path_to_new_vol, volume_size)
        self._set_rw_permissions(path_to_new_vol)

    def _create_overlay_volume_from_snapshot(self, volume, snapshot,
                                             volume_size, out_format):
        """Creates an overlay volume based on a parent in the cache

        Besides the overlay volume this also creates a softlink in the cache
        that  links to the child volume file of the cached volume. This can
        be used to track the cached volumes child volume and marks the fact
        that this child still exists. The softlink is deleted when
        the child is deleted.
        """
        rel_path = os.path.join(
            self.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME, snapshot.id)
        command = ['qemu-img', 'create', '-f', 'qcow2', '-o',
                   'backing_file=%s,backing_fmt=%s' %
                   (rel_path, out_format), self._local_path_volume(volume),
                   "%dG" % volume_size]
        self._execute(*command, run_as_root=self._execute_as_root)
        os.symlink(self._local_path_volume(volume),
                   self._local_volume_from_snap_cache_path(snapshot)
                   + '.child-' + volume.id)

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def delete_volume(self, volume):
        """Deletes a logical volume."""

        if not volume.provider_location:
            LOG.warning('Volume %s does not have provider_location '
                        'specified, skipping', volume.name)
            return

        self._ensure_share_mounted(volume.provider_location)

        volume_dir = self._local_volume_dir(volume)
        active_image = self.get_active_image_from_info(volume)
        mounted_path = os.path.join(volume_dir, active_image)
        if os.access(self.local_path(volume), os.F_OK):
            img_info = self._qemu_img_info(self.local_path(volume),
                                           volume.name)
            if (img_info.backing_file and
                    (self.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME in
                        img_info.backing_file)):
                # This is an overlay volume, call cache cleanup
                self._remove_from_vol_cache(img_info.backing_file,
                                            ".child-" + volume.id, volume)

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

        for share in self.shares:
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
                fileutils.ensure_tree(mount_path)

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
                    mounted = True
                else:
                    raise

        if mounted:
            self._validate_volume(mount_path)
            if self.configuration.quobyte_volume_from_snapshot_cache:
                self._ensure_volume_from_snap_cache(mount_path)

    def _validate_volume(self, mount_path):
        """Runs a number of tests on the expect Quobyte mount"""
        partitions = psutil.disk_partitions(all=True)
        for p in partitions:
            if mount_path == p.mountpoint:
                if (p.device.startswith("quobyte@") or
                        (p.fstype == "fuse.quobyte")):
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
