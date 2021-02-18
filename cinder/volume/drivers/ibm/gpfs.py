# Copyright IBM Corp. 2013 All Rights Reserved
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
GPFS Volume Driver.

"""
import math
import os
import re
import shutil

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import paramiko
import six

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder.objects import fields
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers import nfs
from cinder.volume.drivers import remotefs
from cinder.volume.drivers.san import san
from cinder.volume import volume_utils

GPFS_CLONE_MIN_RELEASE = 1200
GPFS_ENC_MIN_RELEASE = 1404
MIGRATION_ALLOWED_DEST_TYPE = ['GPFSDriver', 'GPFSNFSDriver']

LOG = logging.getLogger(__name__)


gpfs_opts = [
    cfg.StrOpt('gpfs_mount_point_base',
               help='Specifies the path of the GPFS directory where Block '
                    'Storage volume and snapshot files are stored.'),
    cfg.StrOpt('gpfs_images_dir',
               help='Specifies the path of the Image service repository in '
                    'GPFS.  Leave undefined if not storing images in GPFS.'),
    cfg.StrOpt('gpfs_images_share_mode',
               choices=['copy', 'copy_on_write', None],
               help='Specifies the type of image copy to be used.  Set this '
                    'when the Image service repository also uses GPFS so '
                    'that image files can be transferred efficiently from '
                    'the Image service to the Block Storage service. There '
                    'are two valid values: "copy" specifies that a full copy '
                    'of the image is made; "copy_on_write" specifies that '
                    'copy-on-write optimization strategy is used and '
                    'unmodified blocks of the image file are shared '
                    'efficiently.'),
    cfg.IntOpt('gpfs_max_clone_depth',
               default=0,
               help='Specifies an upper limit on the number of indirections '
                    'required to reach a specific block due to snapshots or '
                    'clones.  A lengthy chain of copy-on-write snapshots or '
                    'clones can have a negative impact on performance, but '
                    'improves space utilization.  0 indicates unlimited '
                    'clone depth.'),
    cfg.BoolOpt('gpfs_sparse_volumes',
                default=True,
                help=('Specifies that volumes are created as sparse files '
                      'which initially consume no space. If set to False, the '
                      'volume is created as a fully allocated file, in which '
                      'case, creation may take a significantly longer time.')),
    cfg.StrOpt('gpfs_storage_pool',
               default='system',
               help=('Specifies the storage pool that volumes are assigned '
                     'to. By default, the system storage pool is used.')),
]

gpfs_remote_ssh_opts = [
    cfg.ListOpt('gpfs_hosts',
                default=[],
                help='Comma-separated list of IP address or '
                     'hostnames of GPFS nodes.'),
    cfg.StrOpt('gpfs_user_login',
               default='root',
               help='Username for GPFS nodes.'),
    cfg.StrOpt('gpfs_user_password',
               default='',
               help='Password for GPFS node user.',
               secret=True),
    cfg.StrOpt('gpfs_private_key',
               default='',
               help='Filename of private key to use for SSH authentication.'),
    cfg.PortOpt('gpfs_ssh_port',
                default=22,
                help='SSH port to use.'),
    cfg.StrOpt('gpfs_hosts_key_file',
               default='$state_path/ssh_known_hosts',
               help='File containing SSH host keys for the gpfs nodes '
                    'with which driver needs to communicate. '
                    'Default=$state_path/ssh_known_hosts'),
    cfg.BoolOpt('gpfs_strict_host_key_policy',
                default=False,
                help='Option to enable strict gpfs host key checking while '
                     'connecting to gpfs nodes. Default=False'),
]

CONF = cfg.CONF
CONF.register_opts(gpfs_opts, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(gpfs_remote_ssh_opts, group=configuration.SHARED_CONF_GROUP)


class GPFSDriverUnsupportedOperation(exception.VolumeBackendAPIException):
    message = _("GPFS driver unsupported operation: %(msg)s")


def _different(difference_tuple):
    """Return true if two elements of a tuple are different."""
    if difference_tuple:
        member1, member2 = difference_tuple
        return member1 != member2
    else:
        return False


def _same_filesystem(path1, path2):
    """Return true if the two paths are in the same GPFS file system."""
    return os.lstat(path1).st_dev == os.lstat(path2).st_dev


def _sizestr(size_in_g):
    """Convert the specified size into a string value."""
    return '%sG' % size_in_g


@interface.volumedriver
class GPFSDriver(driver.CloneableImageVD,
                 driver.MigrateVD,
                 driver.BaseVD):
    """Implements volume functions using GPFS primitives.

    .. code-block:: none

     Version history:

       1.0.0 - Initial driver
       1.1.0 - Add volume retype, refactor volume migration
       1.2.0 - Add consistency group support
       1.3.0 - Add NFS based GPFS storage backend support
       1.3.1 - Add GPFS native encryption (encryption of data at rest) support
    """

    VERSION = "1.3.1"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "IBM_GPFS_CI"

    def __init__(self, *args, **kwargs):
        super(GPFSDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(gpfs_opts)
        self.gpfs_execute = self._gpfs_local_execute
        self._execute = utils.execute
        self.GPFS_PATH = ''

    @staticmethod
    def get_driver_options():
        return gpfs_opts

    def _gpfs_local_execute(self, *cmd, **kwargs):
        if 'run_as_root' not in kwargs:
            kwargs.update({'run_as_root': True})

        return utils.execute(*cmd, **kwargs)

    def _get_gpfs_state(self):
        """Return GPFS state information."""
        try:
            (out, err) = self.gpfs_execute(self.GPFS_PATH + 'mmgetstate', '-Y')
            return out
        except processutils.ProcessExecutionError as exc:
            LOG.error('Failed to issue mmgetstate command, error: %s.',
                      exc.stderr)
            raise exception.VolumeBackendAPIException(data=exc.stderr)

    def _check_gpfs_state(self):
        """Raise VolumeBackendAPIException if GPFS is not active."""
        out = self._get_gpfs_state()
        lines = out.splitlines()
        state_token = lines[0].split(':').index('state')
        gpfs_state = lines[1].split(':')[state_token]
        if gpfs_state != 'active':
            LOG.error('GPFS is not active.  Detailed output: %s.', out)
            raise exception.VolumeBackendAPIException(
                data=_('GPFS is not running, state: %s.') % gpfs_state)

    def _get_filesystem_from_path(self, path):
        """Return filesystem for specified path."""
        try:
            (out, err) = self.gpfs_execute('df', path)
            lines = out.splitlines()
            filesystem = lines[1].split()[0]
            return filesystem
        except processutils.ProcessExecutionError as exc:
            LOG.error('Failed to issue df command for path %(path)s, '
                      'error: %(error)s.',
                      {'path': path,
                       'error': exc.stderr})
            raise exception.VolumeBackendAPIException(data=exc.stderr)

    def _get_gpfs_cluster_id(self):
        """Return the id for GPFS cluster being used."""
        try:
            (out, err) = self.gpfs_execute(self.GPFS_PATH + 'mmlsconfig',
                                           'clusterId', '-Y')
            lines = out.splitlines()
            value_token = lines[0].split(':').index('value')
            cluster_id = lines[1].split(':')[value_token]
            return cluster_id
        except processutils.ProcessExecutionError as exc:
            LOG.error('Failed to issue mmlsconfig command, error: %s.',
                      exc.stderr)
            raise exception.VolumeBackendAPIException(data=exc.stderr)

    def _get_fileset_from_path(self, path):
        """Return the GPFS fileset for specified path."""
        fs_regex = re.compile(r'.*fileset.name:\s+(?P<fileset>\w+)', re.S)
        try:
            (out, err) = self.gpfs_execute(self.GPFS_PATH + 'mmlsattr', '-L',
                                           path)
        except processutils.ProcessExecutionError as exc:
            LOG.error('Failed to issue mmlsattr command on path %(path)s, '
                      'error: %(error)s',
                      {'path': path,
                       'error': exc.stderr})
            raise exception.VolumeBackendAPIException(data=exc.stderr)
        try:
            fileset = fs_regex.match(out).group('fileset')
            return fileset
        except AttributeError:
            msg = (_('Failed to find fileset for path %(path)s, command '
                     'output: %(cmdout)s.') %
                   {'path': path,
                    'cmdout': out})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _verify_gpfs_pool(self, storage_pool):
        """Return true if the specified pool is a valid GPFS storage pool."""
        try:
            self.gpfs_execute(self.GPFS_PATH + 'mmlspool', self._gpfs_device,
                              storage_pool)
            return True
        except processutils.ProcessExecutionError:
            return False

    def _update_volume_storage_pool(self, local_path, new_pool):
        """Set the storage pool for a volume to the specified value."""
        if new_pool is None:
            new_pool = 'system'

        if not self._verify_gpfs_pool(new_pool):
            msg = (_('Invalid storage pool %s requested.  Retype failed.') %
                   new_pool)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        try:
            self.gpfs_execute(self.GPFS_PATH + 'mmchattr', '-P', new_pool,
                              local_path)
            LOG.debug('Updated storage pool with mmchattr to %s.', new_pool)
            return True
        except processutils.ProcessExecutionError as exc:
            LOG.info('Could not update storage pool with mmchattr to '
                     '%(pool)s, error: %(error)s',
                     {'pool': new_pool,
                      'error': exc.stderr})
            return False

    def _get_gpfs_fs_release_level(self, path):
        """Return the GPFS version of the specified file system.

        The file system is specified by any valid path it contains.
        """
        filesystem = self._get_filesystem_from_path(path)
        try:
            (out, err) = self.gpfs_execute(self.GPFS_PATH + 'mmlsfs',
                                           filesystem, '-V', '-Y')
        except processutils.ProcessExecutionError as exc:
            LOG.error('Failed to issue mmlsfs command for path %(path)s, '
                      'error: %(error)s.',
                      {'path': path,
                       'error': exc.stderr})
            raise exception.VolumeBackendAPIException(data=exc.stderr)

        lines = out.splitlines()
        value_token = lines[0].split(':').index('data')
        fs_release_level_str = lines[1].split(':')[value_token]
        # at this point, release string looks like "13.23 (3.5.0.7)"
        # extract first token and convert to whole number value
        fs_release_level = int(float(fs_release_level_str.split()[0]) * 100)
        return filesystem, fs_release_level

    def _get_gpfs_cluster_release_level(self):
        """Return the GPFS version of current cluster."""
        try:
            (out, err) = self.gpfs_execute(self.GPFS_PATH + 'mmlsconfig',
                                           'minreleaseLeveldaemon',
                                           '-Y')
        except processutils.ProcessExecutionError as exc:
            LOG.error('Failed to issue mmlsconfig command, error: %s.',
                      exc.stderr)
            raise exception.VolumeBackendAPIException(data=exc.stderr)

        lines = out.splitlines()
        value_token = lines[0].split(':').index('value')
        min_release_level = lines[1].split(':')[value_token]
        return int(min_release_level)

    def _is_gpfs_path(self, directory):
        """Determine if the specified path is in a gpfs file system.

        If not part of a gpfs file system, raise ProcessExecutionError.
        """
        try:
            self.gpfs_execute(self.GPFS_PATH + 'mmlsattr', directory)
        except processutils.ProcessExecutionError as exc:
            LOG.error('Failed to issue mmlsattr command '
                      'for path %(path)s, '
                      'error: %(error)s.',
                      {'path': directory,
                       'error': exc.stderr})
            raise exception.VolumeBackendAPIException(data=exc.stderr)

    def _is_same_fileset(self, path1, path2):
        """Return true if the two paths are in the same GPFS fileset."""
        if self._get_fileset_from_path(path1) == \
                self._get_fileset_from_path(path2):
            return True
        return False

    def _same_cluster(self, host):
        """Return true if the host is a member of the same GPFS cluster."""
        dest_location = host['capabilities'].get('location_info')
        if self._stats['location_info'] == dest_location:
            return True
        return False

    def _set_rw_permission(self, path, modebits='660'):
        """Set permission bits for the path."""
        self.gpfs_execute('chmod', modebits, path)

    def _can_migrate_locally(self, host):
        """Return true if the host can migrate a volume locally."""
        if 'location_info' not in host['capabilities']:
            LOG.debug('Evaluate migration: no location info, '
                      'cannot migrate locally.')
            return None
        info = host['capabilities']['location_info']
        try:
            (dest_type, dest_id, dest_path) = info.split(':')
        except ValueError:
            LOG.debug('Evaluate migration: unexpected location info, '
                      'cannot migrate locally: %s.', info)
            return None
        if (dest_id != self._cluster_id or
                dest_type not in MIGRATION_ALLOWED_DEST_TYPE):
            LOG.debug('Evaluate migration: different destination driver or '
                      'cluster id in location info: %s.', info)
            return None

        LOG.debug('Evaluate migration: use local migration.')
        return dest_path

    def do_setup(self, ctxt):
        """Determine storage back end capabilities."""
        try:
            self._cluster_id = self._get_gpfs_cluster_id()
        except Exception as setup_exception:
            msg = (_('Could not find GPFS cluster id: %s.') %
                   setup_exception)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        try:
            gpfs_base = self.configuration.gpfs_mount_point_base
            self._gpfs_device = self._get_filesystem_from_path(gpfs_base)
        except Exception as setup_exception:
            msg = (_('Could not find GPFS file system device: %s.') %
                   setup_exception)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        pool = self.configuration.safe_get('gpfs_storage_pool')
        self._storage_pool = pool
        if not self._verify_gpfs_pool(self._storage_pool):
            msg = (_('Invalid storage pool %s specificed.') %
                   self._storage_pool)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        _gpfs_cluster_release_level = self._get_gpfs_cluster_release_level()
        if _gpfs_cluster_release_level >= GPFS_ENC_MIN_RELEASE:
            self._encryption_state = self._get_gpfs_encryption_status()
        else:
            LOG.info('Downlevel GPFS Cluster Detected. GPFS '
                     'encryption-at-rest feature not enabled in cluster '
                     'daemon level %(cur)s - must be at least at '
                     'level %(min)s.',
                     {'cur': _gpfs_cluster_release_level,
                      'min': GPFS_ENC_MIN_RELEASE})

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self._check_gpfs_state()

        if self.configuration.gpfs_mount_point_base is None:
            msg = _('Option gpfs_mount_point_base is not set correctly.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if(self.configuration.gpfs_images_share_mode and
           self.configuration.gpfs_images_dir is None):
            msg = _('Option gpfs_images_dir is not set correctly.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if(self.configuration.gpfs_images_share_mode == 'copy_on_write' and
           not _same_filesystem(self.configuration.gpfs_mount_point_base,
                                self.configuration.gpfs_images_dir)):
            msg = (_('gpfs_images_share_mode is set to copy_on_write, but '
                     '%(vol)s and %(img)s belong to different file '
                     'systems.') %
                   {'vol': self.configuration.gpfs_mount_point_base,
                    'img': self.configuration.gpfs_images_dir})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if(self.configuration.gpfs_images_share_mode == 'copy_on_write' and
           not self._is_same_fileset(self.configuration.gpfs_mount_point_base,
                                     self.configuration.gpfs_images_dir)):
            msg = (_('gpfs_images_share_mode is set to copy_on_write, but '
                     '%(vol)s and %(img)s belong to different filesets.') %
                   {'vol': self.configuration.gpfs_mount_point_base,
                    'img': self.configuration.gpfs_images_dir})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        _gpfs_cluster_release_level = self._get_gpfs_cluster_release_level()
        if _gpfs_cluster_release_level < GPFS_CLONE_MIN_RELEASE:
            msg = (_('Downlevel GPFS Cluster Detected.  GPFS Clone feature '
                     'not enabled in cluster daemon level %(cur)s - must '
                     'be at least at level %(min)s.') %
                   {'cur': _gpfs_cluster_release_level,
                    'min': GPFS_CLONE_MIN_RELEASE})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        for directory in [self.configuration.gpfs_mount_point_base,
                          self.configuration.gpfs_images_dir]:
            if directory is None:
                continue

            if not directory.startswith('/'):
                msg = (_('%s must be an absolute path.') % directory)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            if not os.path.isdir(directory):
                msg = (_('%s is not a directory.') % directory)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            # Check if GPFS is mounted
            self._verify_gpfs_path_state(directory)

            filesystem, fslevel = self._get_gpfs_fs_release_level(directory)
            if fslevel < GPFS_CLONE_MIN_RELEASE:
                msg = (_('The GPFS filesystem %(fs)s is not at the required '
                         'release level.  Current level is %(cur)s, must be '
                         'at least %(min)s.') %
                       {'fs': filesystem,
                        'cur': fslevel,
                        'min': GPFS_CLONE_MIN_RELEASE})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def _create_sparse_file(self, path, size):
        """Creates file with 0 disk usage."""

        sizestr = _sizestr(size)
        self.gpfs_execute('truncate', '-s', sizestr, path)

    def _allocate_file_blocks(self, path, size):
        """Preallocate file blocks by writing zeros."""

        block_size_mb = 1
        block_count = size * units.Gi / (block_size_mb * units.Mi)

        self.gpfs_execute('dd', 'if=/dev/zero', 'of=%s' % path,
                          'bs=%dM' % block_size_mb,
                          'count=%d' % block_count)

    def _gpfs_change_attributes(self, options, path):
        """Update GPFS attributes on the specified file."""

        cmd = [self.GPFS_PATH + 'mmchattr']
        cmd.extend(options)
        cmd.append(path)
        LOG.debug('Update volume attributes with mmchattr to %s.', options)
        self.gpfs_execute(*cmd)

    def _set_volume_attributes(self, volume, path, metadata):
        """Set various GPFS attributes for this volume."""

        set_pool = False
        options = []
        for item in metadata:
            if item == 'data_pool_name':
                options.extend(['-P', metadata[item]])
                set_pool = True
            elif item == 'replicas':
                options.extend(['-r', metadata[item], '-m', metadata[item]])
            elif item == 'dio':
                options.extend(['-D', metadata[item]])
            elif item == 'write_affinity_depth':
                options.extend(['--write-affinity-depth', metadata[item]])
            elif item == 'block_group_factor':
                options.extend(['--block-group-factor', metadata[item]])
            elif item == 'write_affinity_failure_group':
                options.extend(['--write-affinity-failure-group',
                               metadata[item]])

        # metadata value has precedence over value set in volume type
        if self.configuration.gpfs_storage_pool and not set_pool:
            options.extend(['-P', self.configuration.gpfs_storage_pool])

        if options:
            self._gpfs_change_attributes(options, path)

        fstype = None
        fslabel = None
        for item in metadata:
            if item == 'fstype':
                fstype = metadata[item]
            elif item == 'fslabel':
                fslabel = metadata[item]
        if fstype:
            self._mkfs(volume, fstype, fslabel)

    def create_volume(self, volume):
        """Creates a GPFS volume."""
        # Check if GPFS is mounted
        self._verify_gpfs_path_state(self.configuration.gpfs_mount_point_base)

        volume_path = self._get_volume_path(volume)
        volume_size = volume['size']

        # Create a sparse file first; allocate blocks later if requested
        self._create_sparse_file(volume_path, volume_size)
        self._set_rw_permission(volume_path)
        # Set the attributes prior to allocating any blocks so that
        # they are allocated according to the policy
        self._set_volume_attributes(volume, volume_path, volume.metadata)

        if not self.configuration.gpfs_sparse_volumes:
            self._allocate_file_blocks(volume_path, volume_size)

    def _create_volume_from_snapshot(self, volume, snapshot):
        snapshot_path = self._get_snapshot_path(snapshot)
        # check if the snapshot lies in the same CG as the volume to be created
        # if yes, clone the volume from the snapshot, else perform full copy
        clone = False
        ctxt = context.get_admin_context()
        snap_parent_vol = self.db.volume_get(ctxt, snapshot['volume_id'])
        if (volume['group_id'] ==
                snap_parent_vol['group_id']):
            clone = True
        volume_path = self._get_volume_path(volume)
        if clone:
            self._create_gpfs_copy(src=snapshot_path, dest=volume_path)
            self._gpfs_redirect(volume_path)
        else:
            self._gpfs_full_copy(snapshot_path, volume_path)

        self._set_rw_permission(volume_path)
        self._set_volume_attributes(volume, volume_path, volume.metadata)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a GPFS volume from a snapshot."""
        self._create_volume_from_snapshot(volume, snapshot)
        virt_size = self._resize_volume_file(volume, volume['size'])
        return {'size': math.ceil(virt_size / units.Gi)}

    def _get_volume_path(self, volume):
        return self.local_path(volume)

    def _create_cloned_volume(self, volume, src_vref):
        src = self._get_volume_path(src_vref)
        dest = self._get_volume_path(volume)
        if (volume['group_id'] == src_vref['group_id']):
            self._create_gpfs_clone(src, dest)
        else:
            self._gpfs_full_copy(src, dest)
        self._set_rw_permission(dest)
        self._set_volume_attributes(volume, dest, volume.metadata)

    def create_cloned_volume(self, volume, src_vref):
        """Create a GPFS volume from another volume."""
        self._create_cloned_volume(volume, src_vref)
        virt_size = self._resize_volume_file(volume, volume['size'])
        return {'size': math.ceil(virt_size / units.Gi)}

    def _delete_gpfs_file(self, fchild, mount_point=None):
        """Delete a GPFS file and cleanup clone children."""

        if mount_point is None:
            if not os.path.exists(fchild):
                return
        else:
            fchild_local_path = os.path.join(mount_point,
                                             os.path.basename(fchild))
            if not os.path.exists(fchild_local_path):
                return

        (out, err) = self.gpfs_execute(self.GPFS_PATH + 'mmclone', 'show',
                                       fchild)
        fparent = None
        delete_parent = False
        inode_regex = re.compile(
            r'.*\s+(?:yes|no)\s+\d+\s+(?P<inode>\d+)', re.M | re.S)
        match = inode_regex.match(out)
        if match:
            inode = match.group('inode')
            if mount_point is None:
                path = os.path.dirname(fchild)
            else:
                path = mount_point

            # -ignore_readdir_race is to prevent the command from exiting
            # with nonzero RC when some files in the directory are removed
            # by other delete operations. -quit is to end the execution as
            # soon as we get one filename; it is not expected that two or
            # more filenames found.
            (out, err) = self._execute('find', path, '-maxdepth', '1',
                                       '-ignore_readdir_race',
                                       '-inum', inode, '-print0', '-quit',
                                       run_as_root=True)
            if out:
                fparent = out.split('\0', 1)[0]

        if mount_point is None:
            self._execute(
                'rm', '-f', fchild, check_exit_code=False, run_as_root=True)
        else:
            self._execute(
                'rm', '-f', fchild_local_path, check_exit_code=False,
                run_as_root=True)

        # There is no need to check for volume references on this snapshot
        # because 'rm -f' itself serves as a simple and implicit check. If the
        # parent is referenced by another volume, GPFS doesn't allow deleting
        # it. 'rm -f' silently fails and the subsequent check on the path
        # indicates whether there are any volumes derived from that snapshot.
        # If there are such volumes, we quit recursion and let the other
        # volumes delete the snapshot later. If there are no references, rm
        # would succeed and the snapshot is deleted.
        if mount_point is None:
            if not os.path.exists(fchild) and fparent:
                delete_parent = True
        else:
            if not os.path.exists(fchild_local_path) and fparent:
                delete_parent = True

        if delete_parent:
            fpbase = os.path.basename(fparent)
            if fpbase.endswith('.snap') or fpbase.endswith('.ts'):
                if mount_point is None:
                    self._delete_gpfs_file(fparent)
                else:
                    fparent_remote_path = os.path.join(os.path.dirname(fchild),
                                                       fpbase)
                    fparent_mount_path = os.path.dirname(fparent)
                    self._delete_gpfs_file(fparent_remote_path,
                                           fparent_mount_path)

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        # Check if GPFS is mounted
        self._verify_gpfs_path_state(self.configuration.gpfs_mount_point_base)

        volume_path = self.local_path(volume)
        self._delete_gpfs_file(volume_path)

    def _gpfs_redirect(self, src):
        """Removes the copy_on_write dependency between src and parent.

        Remove the copy_on_write dependency between the src file and its
        immediate parent such that the length of dependency chain is reduced
        by 1.
        """
        max_depth = self.configuration.gpfs_max_clone_depth
        if max_depth == 0:
            return False
        (out, err) = self.gpfs_execute(self.GPFS_PATH + 'mmclone', 'show', src)
        depth_regex = re.compile(r'.*\s+no\s+(?P<depth>\d+)', re.M | re.S)
        match = depth_regex.match(out)
        if match:
            depth = int(match.group('depth'))
            if depth > max_depth:
                self.gpfs_execute(self.GPFS_PATH + 'mmclone', 'redirect', src)
                return True
        return False

    def _create_gpfs_clone(self, src, dest):
        """Create a GPFS file clone parent for the specified file."""
        snap = dest + ".snap"
        self._create_gpfs_snap(src, snap)
        self._create_gpfs_copy(snap, dest)
        if self._gpfs_redirect(src) and self._gpfs_redirect(dest):
            self._execute('rm', '-f', snap, run_as_root=True)

    def _create_gpfs_copy(self, src, dest):
        """Create a GPFS file clone copy for the specified file."""
        self.gpfs_execute(self.GPFS_PATH + 'mmclone', 'copy', src, dest)

    def _gpfs_full_copy(self, src, dest):
        """Create a full copy from src to dest."""
        self.gpfs_execute('cp', src, dest, check_exit_code=True)

    def _create_gpfs_snap(self, src, dest=None):
        """Create a GPFS file clone snapshot for the specified file."""
        if dest is None:
            self.gpfs_execute(self.GPFS_PATH + 'mmclone', 'snap', src)
        else:
            self.gpfs_execute(self.GPFS_PATH + 'mmclone', 'snap', src, dest)

    def _is_gpfs_parent_file(self, gpfs_file):
        """Return true if the specified file is a gpfs clone parent."""
        out, err = self.gpfs_execute(self.GPFS_PATH + 'mmclone', 'show',
                                     gpfs_file)
        ptoken = out.splitlines().pop().split()[0]
        return ptoken == 'yes'

    def create_snapshot(self, snapshot):
        """Creates a GPFS snapshot."""
        snapshot_path = self._get_snapshot_path(snapshot)
        volume_path = os.path.join(os.path.dirname(snapshot_path),
                                   snapshot.volume.name)
        self._create_gpfs_snap(src=volume_path, dest=snapshot_path)
        self._set_rw_permission(snapshot_path, modebits='640')
        self._gpfs_redirect(volume_path)

    def delete_snapshot(self, snapshot):
        """Deletes a GPFS snapshot."""
        # Rename the deleted snapshot to indicate it no longer exists in
        # cinder db. Attempt to delete the snapshot.  If the snapshot has
        # clone children, the delete will fail silently. When volumes that
        # are clone children are deleted in the future, the remaining ts
        # snapshots will also be deleted.
        snapshot_path = self._get_snapshot_path(snapshot)
        snapshot_ts_path = '%s.ts' % snapshot_path
        self.gpfs_execute('mv', snapshot_path, snapshot_ts_path)
        self.gpfs_execute('rm', '-f', snapshot_ts_path,
                          check_exit_code=False)

    def _get_snapshot_path(self, snapshot):
        snap_parent_vol_path = self.local_path(snapshot.volume)
        snapshot_path = os.path.join(os.path.dirname(snap_parent_vol_path),
                                     snapshot.name)
        return snapshot_path

    def local_path(self, volume):
        """Return the local path for the specified volume."""
        # Check if the volume is part of a consistency group and return
        # the local_path accordingly.
        if volume.group_id is not None:
            if volume_utils.is_group_a_cg_snapshot_type(volume.group):
                cgname = "consisgroup-%s" % volume.group_id
                volume_path = os.path.join(
                    self.configuration.gpfs_mount_point_base,
                    cgname,
                    volume.name
                )
                return volume_path

        volume_path = os.path.join(
            self.configuration.gpfs_mount_point_base,
            volume.name
        )
        return volume_path

    def _get_gpfs_encryption_status(self):
        """Determine if the backend is configured with key manager."""
        try:
            (out, err) = self.gpfs_execute(self.GPFS_PATH + 'mmlsfs',
                                           self._gpfs_device,
                                           '--encryption', '-Y')
            lines = out.splitlines()
            value_token = lines[0].split(':').index('data')
            encryption_status = lines[1].split(':')[value_token]
            return encryption_status
        except processutils.ProcessExecutionError as exc:
            LOG.error('Failed to issue mmlsfs command, error: %s.',
                      exc.stderr)
            raise exception.VolumeBackendAPIException(data=exc.stderr)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume, connector):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'gpfs',
            'data': {
                'name': volume['name'],
                'device_path': self.local_path(volume),
            }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Updating volume stats.")
        gpfs_base = self.configuration.gpfs_mount_point_base
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or 'GPFS'
        data["vendor_name"] = 'IBM'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = 'file'
        free, capacity = self._get_available_capacity(self.configuration.
                                                      gpfs_mount_point_base)
        data['total_capacity_gb'] = math.ceil(capacity / units.Gi)
        data['free_capacity_gb'] = math.ceil(free / units.Gi)
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        data['storage_pool'] = self._storage_pool
        data['location_info'] = ('GPFSDriver:%(cluster_id)s:%(root_path)s' %
                                 {'cluster_id': self._cluster_id,
                                  'root_path': gpfs_base})

        data['consistencygroup_support'] = 'True'
        data['consistent_group_snapshot_enabled'] = True

        if self._encryption_state.lower() == 'yes':
            data['gpfs_encryption_rest'] = 'True'

        self._stats = data

    def clone_image(self, context, volume,
                    image_location, image_meta,
                    image_service):
        """Create a volume from the specified image."""
        return self._clone_image(volume, image_location, image_meta['id'])

    def _is_cloneable(self, image_id):
        """Return true if the specified image can be cloned by GPFS."""
        if not((self.configuration.gpfs_images_dir and
                self.configuration.gpfs_images_share_mode)):
            reason = 'glance repository not configured to use GPFS'
            return False, reason, None

        image_path = os.path.join(self.configuration.gpfs_images_dir, image_id)
        try:
            self._is_gpfs_path(image_path)
        except processutils.ProcessExecutionError:
            reason = 'image file not in GPFS'
            return False, reason, None

        return True, None, image_path

    def _clone_image(self, volume, image_location, image_id):
        """Attempt to create a volume by efficiently copying image to volume.

        If both source and target are backed by gpfs storage and the source
        image is in raw format move the image to create a volume using either
        gpfs clone operation or with a file copy. If the image format is not
        raw, convert it to raw at the volume path.
        """
        # Check if GPFS is mounted
        self._verify_gpfs_path_state(self.configuration.gpfs_mount_point_base)

        cloneable_image, reason, image_path = self._is_cloneable(image_id)
        if not cloneable_image:
            LOG.debug('Image %(img)s not cloneable: %(reas)s.',
                      {'img': image_id, 'reas': reason})
            return (None, False)

        vol_path = self.local_path(volume)

        data = image_utils.qemu_img_info(image_path)

        # if image format is already raw either clone it or
        # copy it depending on config file settings
        if data.file_format == 'raw':
            if (self.configuration.gpfs_images_share_mode ==
                    'copy_on_write'):
                LOG.debug('Clone image to vol %s using mmclone.',
                          volume['id'])
                # if the image is not already a GPFS snap file make it so
                if not self._is_gpfs_parent_file(image_path):
                    self._create_gpfs_snap(image_path)

                self._create_gpfs_copy(image_path, vol_path)
            elif self.configuration.gpfs_images_share_mode == 'copy':
                LOG.debug('Clone image to vol %s using copyfile.',
                          volume['id'])
                shutil.copyfile(image_path, vol_path)

        # if image is not raw convert it to raw into vol_path destination
        else:
            LOG.debug('Clone image to vol %s using qemu convert.',
                      volume['id'])
            image_utils.convert_image(image_path, vol_path, 'raw')

        self._set_rw_permission(vol_path)
        self._resize_volume_file(volume, volume['size'])

        return {'provider_location': None}, True

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume.

        Note that cinder.volume.flows.create_volume will attempt to use
        clone_image to efficiently create volume from image when both
        source and target are backed by gpfs storage.  If that is not the
        case, this function is invoked and uses fetch_to_raw to create the
        volume.
        """
        # Check if GPFS is mounted
        self._verify_gpfs_path_state(self.configuration.gpfs_mount_point_base)

        LOG.debug('Copy image to vol %s using image_utils fetch_to_raw.',
                  volume['id'])
        image_utils.fetch_to_raw(context, image_service, image_id,
                                 self.local_path(volume),
                                 self.configuration.volume_dd_blocksize,
                                 size=volume['size'])
        self._resize_volume_file(volume, volume['size'])

    def _resize_volume_file(self, volume, new_size):
        """Resize volume file to new size."""
        vol_path = self.local_path(volume)
        try:
            image_utils.resize_image(vol_path, new_size, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            LOG.error("Failed to resize volume "
                      "%(volume_id)s, error: %(error)s.",
                      {'volume_id': volume['id'],
                       'error': exc.stderr})
            raise exception.VolumeBackendAPIException(data=exc.stderr)

        data = image_utils.qemu_img_info(vol_path)
        return data.virtual_size

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        self._resize_volume_file(volume, new_size)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        volume_utils.upload_volume(context,
                                   image_service,
                                   image_meta,
                                   self.local_path(volume),
                                   volume)

    def _migrate_volume(self, volume, host):
        """Migrate vol if source and dest are managed by same GPFS cluster."""
        LOG.debug('Migrate volume request %(vol)s to %(host)s.',
                  {'vol': volume['name'],
                   'host': host['host']})
        dest_path = self._can_migrate_locally(host)

        if dest_path is None:
            LOG.debug('Cannot migrate volume locally, use generic migration.')
            return (False, None)
        if dest_path == self.configuration.gpfs_mount_point_base:
            LOG.debug('Migration target is same cluster and path, '
                      'no work needed.')
            return (True, None)

        LOG.debug('Migration target is same cluster but different path, '
                  'move the volume file.')
        local_path = self._get_volume_path(volume)
        new_path = os.path.join(dest_path, volume['name'])
        try:
            self.gpfs_execute('mv', local_path, new_path)
            return (True, None)
        except processutils.ProcessExecutionError as exc:
            LOG.error('Driver-based migration of volume %(vol)s failed. '
                      'Move from %(src)s to %(dst)s failed with error: '
                      '%(error)s.',
                      {'vol': volume['name'],
                       'src': local_path,
                       'dst': new_path,
                       'error': exc.stderr})
            return (False, None)

    def migrate_volume(self, context, volume, host):
        """Attempt to migrate a volume to specified host."""
        return self._migrate_volume(volume, host)

    def retype(self, context, volume, new_type, diff, host):
        """Modify volume to be of new type."""
        LOG.debug('Retype volume request %(vol)s to be %(type)s '
                  '(host: %(host)s), diff %(diff)s.',
                  {'vol': volume['name'],
                   'type': new_type,
                   'host': host,
                   'diff': diff})

        retyped = False
        migrated = False
        pools = diff['extra_specs'].get('capabilities:storage_pool')

        backends = diff['extra_specs'].get('volume_backend_name')
        hosts = (volume['host'], host['host'])

        # if different backends let migration create a new volume and copy
        # data because the volume is considered to be substantially different
        if _different(backends):
            backend1, backend2 = backends
            LOG.debug('Retype request is for different backends, '
                      'use migration: %(backend1)s %(backend2)s.',
                      {'backend1': backend1, 'backend2': backend1})
            return False

        if _different(pools):
            old, new = pools
            LOG.debug('Retype pool attribute from %(old)s to %(new)s.',
                      {'old': old, 'new': new})
            retyped = self._update_volume_storage_pool(self.local_path(volume),
                                                       new)

        if _different(hosts):
            source, destination = hosts
            LOG.debug('Retype hosts migrate from: %(source)s to '
                      '%(destination)s.', {'source': source,
                                           'destination': destination})
            migrated, mdl_update = self._migrate_volume(volume, host)
            if migrated:
                updates = {'host': host['host']}
                self.db.volume_update(context, volume['id'], updates)

        return retyped or migrated

    def _mkfs(self, volume, filesystem, label=None):
        """Initialize volume to be specified filesystem type."""
        if filesystem == 'swap':
            cmd = ['mkswap']
        else:
            cmd = ['mkfs', '-t', filesystem]

        if filesystem in ('ext3', 'ext4'):
            cmd.append('-F')
        if label:
            if filesystem in ('msdos', 'vfat'):
                label_opt = '-n'
            else:
                label_opt = '-L'
            cmd.extend([label_opt, label])

        path = self.local_path(volume)
        cmd.append(path)
        try:
            self._execute(*cmd, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            exception_message = (_("mkfs failed on volume %(vol)s, "
                                   "error message was: %(err)s.")
                                 % {'vol': volume['name'], 'err': exc.stderr})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                data=exception_message)

    def _get_available_capacity(self, path):
        """Calculate available space on path."""
        # Check if GPFS is mounted
        try:
            self._verify_gpfs_path_state(path)
            mounted = True
        except exception.VolumeBackendAPIException:
            mounted = False

        # If GPFS is not mounted, return zero capacity. So that the volume
        # request can be scheduled to another volume service.
        if not mounted:
            return 0, 0

        out, err = self.gpfs_execute('df', '-P', '-B', '1', path,
                                     run_as_root=True)
        out = out.splitlines()[1]
        size = int(out.split()[1])
        available = int(out.split()[3])
        return available, size

    def _verify_gpfs_path_state(self, path):
        """Examine if GPFS is active and file system is mounted or not."""
        try:
            self._is_gpfs_path(path)
        except processutils.ProcessExecutionError:
            msg = (_('%s cannot be accessed. Verify that GPFS is active and '
                     'file system is mounted.') % path)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _create_consistencygroup(self, context, group):
        """Create consistency group of GPFS volumes."""
        cgname = "consisgroup-%s" % group['id']
        fsdev = self._gpfs_device
        cgpath = os.path.join(self.configuration.gpfs_mount_point_base,
                              cgname)
        try:
            self.gpfs_execute(self.GPFS_PATH + 'mmcrfileset', fsdev, cgname,
                              '--inode-space', 'new')
        except processutils.ProcessExecutionError as e:
            msg = (_('Failed to create consistency group: %(cgid)s. '
                     'Error: %(excmsg)s.') %
                   {'cgid': group['id'], 'excmsg': six.text_type(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        try:
            self.gpfs_execute(self.GPFS_PATH + 'mmlinkfileset', fsdev, cgname,
                              '-J', cgpath)
        except processutils.ProcessExecutionError as e:
            msg = (_('Failed to link fileset for the share %(cgname)s. '
                     'Error: %(excmsg)s.') %
                   {'cgname': cgname, 'excmsg': six.text_type(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        try:
            self.gpfs_execute('chmod', '770', cgpath)
        except processutils.ProcessExecutionError as e:
            msg = (_('Failed to set permissions for the consistency group '
                     '%(cgname)s. '
                     'Error: %(excmsg)s.') %
                   {'cgname': cgname, 'excmsg': six.text_type(e)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        model_update = {'status': fields.GroupStatus.AVAILABLE}
        return model_update

    def _delete_consistencygroup(self, context, group, volumes):
        """Delete consistency group of GPFS volumes."""
        cgname = "consisgroup-%s" % group['id']
        fsdev = self._gpfs_device
        delete_fileset = True

        model_update = {}
        model_update['status'] = group['status']

        try:
            self.gpfs_execute(self.GPFS_PATH + 'mmlsfileset', fsdev, cgname)
        except processutils.ProcessExecutionError as e:
            if e.exit_code == 2:
                msg = (_('The fileset associated with consistency group '
                         '%(cgname)s does not exist') %
                       {'cgname': cgname})
                LOG.info(msg)
                delete_fileset = False

        # Unlink and delete the fileset associated with the consistency group.
        # All of the volumes and volume snapshot data will also be deleted.
        if delete_fileset:
            try:
                self.gpfs_execute(self.GPFS_PATH + 'mmunlinkfileset', fsdev,
                                  cgname, '-f')
            except processutils.ProcessExecutionError as e:
                msg = (_('Failed to unlink fileset for consistency group '
                         '%(cgname)s. Error: %(excmsg)s.') %
                       {'cgname': cgname, 'excmsg': six.text_type(e)})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            try:
                self.gpfs_execute(self.GPFS_PATH + 'mmdelfileset',
                                  fsdev, cgname, '-f')
            except processutils.ProcessExecutionError as e:
                msg = (_('Failed to delete fileset for consistency group '
                         '%(cgname)s. Error: %(excmsg)s.') %
                       {'cgname': cgname, 'excmsg': six.text_type(e)})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        for volume_ref in volumes:
            volume_ref['status'] = 'deleted'

        model_update = {'status': group['status']}

        return None, None

    def _create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Create snapshot of a consistency group of GPFS volumes."""
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        snapshots_model_update = []

        try:
            for snapshot in snapshots:
                self.create_snapshot(snapshot)
        except exception.VolumeBackendAPIException as err:
            model_update['status'] = (
                fields.GroupStatus.ERROR)
            LOG.error("Failed to create the snapshot %(snap)s of "
                      "CGSnapshot. Exception: %(exception)s.",
                      {'snap': snapshot.name, 'exception': err})

        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot.id,
                 'status': model_update['status']})

        return model_update, snapshots_model_update

    def _delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Delete snapshot of a consistency group of GPFS volumes."""
        model_update = {'status': fields.GroupStatus.DELETED}
        snapshots_model_update = []

        try:
            for snapshot in snapshots:
                self.delete_snapshot(snapshot)
        except exception.VolumeBackendAPIException as err:
            model_update['status'] = (
                fields.GroupStatus.ERROR_DELETING)
            LOG.error("Failed to delete the snapshot %(snap)s of "
                      "CGSnapshot. Exception: %(exception)s.",
                      {'snap': snapshot.name, 'exception': err})

        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot.id,
                 'status': model_update['status']})

        return model_update, snapshots_model_update

    def _update_consistencygroup(self, context, group,
                                 add_volumes=None, remove_volumes=None):
        msg = _('Updating a consistency group is not supported.')
        LOG.error(msg)
        raise GPFSDriverUnsupportedOperation(msg=msg)

    def _create_consistencygroup_from_src(self, context, group, volumes,
                                          cgsnapshot=None, snapshots=None,
                                          source_cg=None, source_vols=None):
        msg = _('Creating a consistency group from any source consistency '
                'group or consistency group snapshot is not supported.')
        LOG.error(msg)
        raise GPFSDriverUnsupportedOperation(msg=msg)

    def create_group(self, ctxt, group):
        """Creates a group.

        :param ctxt: the context of the caller.
        :param group: the Group object of the group to be created.
        :returns: model_update
        """
        if volume_utils.is_group_a_cg_snapshot_type(group):
            return self._create_consistencygroup(ctxt, group)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()

    def delete_group(self, ctxt, group, volumes):
        """Deletes a group.

        :param ctxt: the context of the caller.
        :param group: the Group object of the group to be deleted.
        :param volumes: a list of Volume objects in the group.
        :returns: model_update, volumes_model_update
        """
        if volume_utils.is_group_a_cg_snapshot_type(group):
            return self._delete_consistencygroup(ctxt, group, volumes)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()

    def update_group(self, ctxt, group,
                     add_volumes=None, remove_volumes=None):
        """Updates a group.

        :param ctxt: the context of the caller.
        :param group: the Group object of the group to be updated.
        :param add_volumes: a list of Volume objects to be added.
        :param remove_volumes: a list of Volume objects to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update
        """

        if volume_utils.is_group_a_cg_snapshot_type(group):
            return self._update_consistencygroup(ctxt,
                                                 group,
                                                 add_volumes,
                                                 remove_volumes)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()

    def create_group_snapshot(self, ctxt, group_snapshot, snapshots):
        """Creates a group_snapshot.

        :param ctxt: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be created.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """
        if volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            return self._create_cgsnapshot(ctxt, group_snapshot, snapshots)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()

    def delete_group_snapshot(self, ctxt, group_snapshot, snapshots):
        """Deletes a group_snapshot.

        :param ctxt: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be deleted.
        :param snapshots: a list of snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """
        if volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            return self._delete_cgsnapshot(ctxt, group_snapshot, snapshots)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()

    def create_group_from_src(self, ctxt, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source.

        :param ctxt: the context of the caller.
        :param group: the Group object to be created.
        :param volumes: a list of Volume objects in the group.
        :param group_snapshot: the GroupSnapshot object as source.
        :param snapshots: a list of snapshot objects in group_snapshot.
        :param source_group: the Group object as source.
        :param source_vols: a list of volume objects in the source_group.
        :returns: model_update, volumes_model_update
        """
        if volume_utils.is_group_a_cg_snapshot_type(group):
            return self._create_consistencygroup_from_src(ctxt,
                                                          group,
                                                          volumes,
                                                          group_snapshot,
                                                          snapshots,
                                                          source_group,
                                                          source_vols)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()


@interface.volumedriver
class GPFSRemoteDriver(GPFSDriver, san.SanDriver):
    """GPFS cinder driver extension.

    This extends the capability of existing GPFS cinder driver
    to be able to run the driver when cinder volume service
    is not running on GPFS node where as Nova Compute is a GPFS
    client. This deployment is typically in Container based
    OpenStack environment.
    """

    VERSION = "1.0"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "IBM_GPFS_CI"

    def __init__(self, *args, **kwargs):
        super(GPFSRemoteDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(gpfs_remote_ssh_opts)
        self.configuration.san_login = self.configuration.gpfs_user_login
        self.configuration.san_password = (
            self.configuration.gpfs_user_password)
        self.configuration.san_private_key = (
            self.configuration.gpfs_private_key)
        self.configuration.san_ssh_port = self.configuration.gpfs_ssh_port
        self.gpfs_execute = self._gpfs_remote_execute
        self.GPFS_PATH = '/usr/lpp/mmfs/bin/'

    @staticmethod
    def get_driver_options():
        return gpfs_opts + gpfs_remote_ssh_opts

    def _gpfs_remote_execute(self, *cmd, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', None)
        return self._run_ssh(cmd, check_exit_code)

    def do_setup(self, ctxt):
        self.configuration.san_ip = self._get_active_gpfs_node_ip()
        super(GPFSRemoteDriver, self).do_setup(ctxt)

    def _get_active_gpfs_node_ip(self):
        """Set the san_ip to active gpfs node IP"""
        active_gpfs_node_ip = None
        gpfs_node_ips = self.configuration.gpfs_hosts
        ssh = paramiko.SSHClient()

        # Validate good config setting here.
        # Paramiko handles the case where the file is inaccessible.
        if not self.configuration.gpfs_hosts_key_file:
            raise exception.ParameterNotFound(param='gpfs_hosts_key_file')
        elif not os.path.isfile(self.configuration.gpfs_hosts_key_file):
            # If using the default path, just create the file.
            if CONF.state_path in self.configuration.gpfs_hosts_key_file:
                open(self.configuration.gpfs_hosts_key_file, 'a').close()
            else:
                msg = (_("Unable to find ssh_hosts_key_file: %s") %
                       self.configuration.gpfs_hosts_key_file)
                raise exception.InvalidInput(reason=msg)

        ssh.load_host_keys(self.configuration.gpfs_hosts_key_file)
        if self.configuration.gpfs_strict_host_key_policy:
            ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if ((not self.configuration.gpfs_user_password) and
                (not self.configuration.gpfs_private_key)):
            msg = _("Specify a password or private_key")
            raise exception.VolumeDriverException(msg)
        for ip in gpfs_node_ips:
            try:
                if self.configuration.gpfs_user_password:
                    ssh.connect(ip,
                                port=self.configuration.gpfs_ssh_port,
                                username=self.configuration.gpfs_user_login,
                                password=self.configuration.gpfs_user_password,
                                timeout=self.configuration.ssh_conn_timeout)
                elif self.configuration.gpfs_private_key:
                    pkfile = os.path.expanduser(
                        self.configuration.gpfs_private_key)
                    privatekey = paramiko.RSAKey.from_private_key_file(pkfile)
                    ssh.connect(ip,
                                port=self.configuration.gpfs_ssh_port,
                                username=self.configuration.gpfs_user_login,
                                pkey=privatekey,
                                timeout=self.configuration.ssh_conn_timeout)
            except Exception as e:
                LOG.info("Cannot connect to GPFS node %(ip)s. "
                         "Error is: %(err)s. "
                         "Continuing to next node",
                         {'ip': ip, 'err': e})
                continue
            try:
                # check if GPFS state is active on the node
                (out, __) = processutils.ssh_execute(ssh, self.GPFS_PATH +
                                                     'mmgetstate -Y')
                lines = out.splitlines()
                state_token = lines[0].split(':').index('state')
                gpfs_state = lines[1].split(':')[state_token]
                if gpfs_state != 'active':
                    LOG.info("GPFS is not active on node %(ip)s. "
                             "Continuing to next node",
                             {'ip': ip})
                    continue
                # check if filesystem is mounted on the node
                processutils.ssh_execute(
                    ssh,
                    'df ' + self.configuration.gpfs_mount_point_base)
            except processutils.ProcessExecutionError as e:
                LOG.info("GPFS is not active on node %(ip)s. "
                         "Error is: %(err)s. "
                         "Continuing to next node",
                         {'ip': ip, 'err': e})
                continue
            # set the san_ip to the active gpfs node IP
            LOG.debug("Setting active GPFS node IP to %s", ip)
            active_gpfs_node_ip = ip
            break
        else:
            msg = _("No GPFS node is active")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return active_gpfs_node_ip


@interface.volumedriver
class GPFSNFSDriver(GPFSDriver, nfs.NfsDriver, san.SanDriver):
    """GPFS cinder driver extension.

    This extends the capability of existing GPFS cinder driver
    to be able to create cinder volumes when cinder volume service
    is not running on GPFS node.
    """

    VERSION = "1.0"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "IBM_GPFS_CI"

    def __init__(self, *args, **kwargs):
        self._context = None
        self._storage_pool = None
        self._cluster_id = None
        super(GPFSNFSDriver, self).__init__(*args, **kwargs)
        self.gpfs_execute = self._gpfs_remote_execute
        self.configuration.append_config_values(remotefs.nas_opts)
        self.configuration.san_ip = self.configuration.nas_host
        self.configuration.san_login = self.configuration.nas_login
        self.configuration.san_password = self.configuration.nas_password
        self.configuration.san_private_key = (
            self.configuration.nas_private_key)
        self.configuration.san_ssh_port = self.configuration.nas_ssh_port
        self.GPFS_PATH = '/usr/lpp/mmfs/bin/'

    def _gpfs_remote_execute(self, *cmd, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', None)
        return self._run_ssh(cmd, check_exit_code)

    def do_setup(self, context):
        super(GPFSNFSDriver, self).do_setup(context)
        self._context = context

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Enter _update_volume_stats.")
        gpfs_base = self.configuration.gpfs_mount_point_base
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or 'GPFSNFS'
        data['vendor_name'] = 'IBM'
        data['driver_version'] = self.get_version()
        data['storage_protocol'] = 'file'

        self._ensure_shares_mounted()

        global_capacity = 0
        global_free = 0
        for share in self._mounted_shares:
            capacity, free, _used = self._get_capacity_info(share)
            global_capacity += capacity
            global_free += free

        data['total_capacity_gb'] = global_capacity / float(units.Gi)
        data['free_capacity_gb'] = global_free / float(units.Gi)
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        data['storage_pool'] = self._storage_pool
        data['location_info'] = ('GPFSNFSDriver:%(cluster_id)s:%(root_path)s' %
                                 {'cluster_id': self._cluster_id,
                                  'root_path': gpfs_base})

        data['consistencygroup_support'] = 'True'
        data['consistent_group_snapshot_enabled'] = True
        self._stats = data
        LOG.debug("Exit _update_volume_stats.")

    def _get_volume_path(self, volume):
        """Returns remote GPFS path for the given volume."""
        export_path = self.configuration.gpfs_mount_point_base
        if volume.group_id is not None:
            if volume_utils.is_group_a_cg_snapshot_type(volume.group):
                cgname = "consisgroup-%s" % volume.group_id
                return os.path.join(export_path, cgname, volume.name)
        return os.path.join(export_path, volume.name)

    def local_path(self, volume):
        """Returns the local path for the specified volume."""
        remotefs_share = volume['provider_location']
        base_local_path = self._get_mount_point_for_share(remotefs_share)

        # Check if the volume is part of a consistency group and return
        # the local_path accordingly.
        if volume.group_id is not None:
            if volume_utils.is_group_a_cg_snapshot_type(volume.group):
                cgname = "consisgroup-%s" % volume.group_id
                return os.path.join(base_local_path, cgname, volume.name)
        return os.path.join(base_local_path, volume.name)

    def _get_snapshot_path(self, snapshot):
        """Returns remote GPFS path for the given snapshot."""
        snap_parent_vol = self.db.volume_get(self._context,
                                             snapshot['volume_id'])
        snap_parent_vol_path = self._get_volume_path(snap_parent_vol)
        snapshot_path = os.path.join(os.path.dirname(snap_parent_vol_path),
                                     snapshot['name'])
        return snapshot_path

    def create_volume(self, volume):
        """Creates a GPFS volume."""
        super(GPFSNFSDriver, self).create_volume(volume)
        volume['provider_location'] = self._find_share(volume)
        return {'provider_location': volume['provider_location']}

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        # Check if GPFS is mounted
        self._verify_gpfs_path_state(self.configuration.gpfs_mount_point_base)

        volume_path = self._get_volume_path(volume)
        mount_point = os.path.dirname(self.local_path(volume))
        # Delete all dependent snapshots, the snapshot will get deleted
        # if the link count goes to zero, else rm will fail silently
        self._delete_gpfs_file(volume_path, mount_point)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a GPFS volume from a snapshot."""
        self._create_volume_from_snapshot(volume, snapshot)
        volume['provider_location'] = self._find_share(volume)
        self._resize_volume_file(volume, volume['size'])
        return {'provider_location': volume['provider_location']}

    def create_cloned_volume(self, volume, src_vref):
        """Create a GPFS volume from another volume."""
        self._create_cloned_volume(volume, src_vref)
        volume['provider_location'] = self._find_share(volume)
        self._resize_volume_file(volume, volume['size'])
        return {'provider_location': volume['provider_location']}
