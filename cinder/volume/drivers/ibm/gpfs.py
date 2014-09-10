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

from oslo.config import cfg

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder.openstack.common import fileutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder.openstack.common import units
from cinder import utils
from cinder.volume import driver

GPFS_CLONE_MIN_RELEASE = 1200

LOG = logging.getLogger(__name__)


gpfs_opts = [
    cfg.StrOpt('gpfs_mount_point_base',
               default=None,
               help='Specifies the path of the GPFS directory where Block '
                    'Storage volume and snapshot files are stored.'),
    cfg.StrOpt('gpfs_images_dir',
               default=None,
               help='Specifies the path of the Image service repository in '
                    'GPFS.  Leave undefined if not storing images in GPFS.'),
    cfg.StrOpt('gpfs_images_share_mode',
               default=None,
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
CONF = cfg.CONF
CONF.register_opts(gpfs_opts)


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
    if int(size_in_g) == 0:
        # return 100M size on zero input for testing
        return '100M'
    return '%sG' % size_in_g


class GPFSDriver(driver.VolumeDriver):
    """Implements volume functions using GPFS primitives.

    Version history:
    1.0.0 - Initial driver
    1.1.0 - Add volume retype, refactor volume migration
    """

    VERSION = "1.1.0"

    def __init__(self, *args, **kwargs):
        super(GPFSDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(gpfs_opts)

    def _get_gpfs_state(self):
        """Return GPFS state information."""
        try:
            (out, err) = self._execute('mmgetstate', '-Y', run_as_root=True)
            return out
        except processutils.ProcessExecutionError as exc:
            LOG.error(_('Failed to issue mmgetstate command, error: %s.') %
                      exc.stderr)
            raise exception.VolumeBackendAPIException(data=exc.stderr)

    def _check_gpfs_state(self):
        """Raise VolumeBackendAPIException if GPFS is not active."""
        out = self._get_gpfs_state()
        lines = out.splitlines()
        state_token = lines[0].split(':').index('state')
        gpfs_state = lines[1].split(':')[state_token]
        if gpfs_state != 'active':
            LOG.error(_('GPFS is not active.  Detailed output: %s.') % out)
            exception_message = (_('GPFS is not running, state: %s.') %
                                 gpfs_state)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _get_filesystem_from_path(self, path):
        """Return filesystem for specified path."""
        try:
            (out, err) = self._execute('df', path, run_as_root=True)
            lines = out.splitlines()
            filesystem = lines[1].split()[0]
            return filesystem
        except processutils.ProcessExecutionError as exc:
            LOG.error(_('Failed to issue df command for path %(path)s, '
                        'error: %(error)s.') %
                      {'path': path,
                       'error': exc.stderr})
            raise exception.VolumeBackendAPIException(data=exc.stderr)

    def _get_gpfs_cluster_id(self):
        """Return the id for GPFS cluster being used."""
        try:
            (out, err) = self._execute('mmlsconfig', 'clusterId', '-Y',
                                       run_as_root=True)
            lines = out.splitlines()
            value_token = lines[0].split(':').index('value')
            cluster_id = lines[1].split(':')[value_token]
            return cluster_id
        except processutils.ProcessExecutionError as exc:
            LOG.error(_('Failed to issue mmlsconfig command, error: %s.') %
                      exc.stderr)
            raise exception.VolumeBackendAPIException(data=exc.stderr)

    def _get_fileset_from_path(self, path):
        """Return the GPFS fileset for specified path."""
        fs_regex = re.compile(r'.*fileset.name:\s+(?P<fileset>\w+)', re.S)
        try:
            (out, err) = self._execute('mmlsattr', '-L', path,
                                       run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            LOG.error(_('Failed to issue mmlsattr command on path %(path)s, '
                        'error: %(error)s') %
                      {'path': path,
                       'error': exc.stderr})
            raise exception.VolumeBackendAPIException(data=exc.stderr)
        try:
            fileset = fs_regex.match(out).group('fileset')
            return fileset
        except AttributeError as exc:
            msg = (_('Failed to find fileset for path %(path)s, command '
                     'output: %(cmdout)s.') %
                   {'path': path,
                    'cmdout': out})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _verify_gpfs_pool(self, storage_pool):
        """Return true if the specified pool is a valid GPFS storage pool."""
        try:
            self._execute('mmlspool', self._gpfs_device, storage_pool,
                          run_as_root=True)
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
            self._execute('mmchattr', '-P', new_pool, local_path,
                          run_as_root=True)
            LOG.debug('Updated storage pool with mmchattr to %s.' % new_pool)
            return True
        except processutils.ProcessExecutionError as exc:
            LOG.info('Could not update storage pool with mmchattr to '
                     '%(pool)s, error: %(error)s' %
                     {'pool': new_pool,
                      'error': exc.stderr})
            return False

    def _get_gpfs_fs_release_level(self, path):
        """Return the GPFS version of the specified file system.

        The file system is specified by any valid path it contains.
        """
        filesystem = self._get_filesystem_from_path(path)
        try:
            (out, err) = self._execute('mmlsfs', filesystem, '-V', '-Y',
                                       run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            LOG.error(_('Failed to issue mmlsfs command for path %(path)s, '
                        'error: %(error)s.') %
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
            (out, err) = self._execute('mmlsconfig', 'minreleaseLeveldaemon',
                                       '-Y', run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            LOG.error(_('Failed to issue mmlsconfig command, error: %s.') %
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
            self._execute('mmlsattr', directory, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            LOG.error(_('Failed to issue mmlsattr command for path %(path)s, '
                        'error: %(error)s.') %
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
        self._execute('chmod', modebits, path, run_as_root=True)

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
                      'cannot migrate locally: %s.' % info)
            return None
        if dest_type != 'GPFSDriver' or dest_id != self._cluster_id:
            LOG.debug('Evaluate migration: different destination driver or '
                      'cluster id in location info: %s.' % info)
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

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self._check_gpfs_state()

        if self.configuration.gpfs_mount_point_base is None:
            msg = _('Option gpfs_mount_point_base is not set correctly.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if (self.configuration.gpfs_images_share_mode and
            self.configuration.gpfs_images_share_mode not in ['copy_on_write',
                                                              'copy']):
            msg = _('Option gpfs_images_share_mode is not set correctly.')
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
        if not _gpfs_cluster_release_level >= GPFS_CLONE_MIN_RELEASE:
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

            filesystem, fslevel = \
                self._get_gpfs_fs_release_level(directory)
            if not fslevel >= GPFS_CLONE_MIN_RELEASE:
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
        self._execute('truncate', '-s', sizestr, path, run_as_root=True)

    def _allocate_file_blocks(self, path, size):
        """Preallocate file blocks by writing zeros."""

        block_size_mb = 1
        block_count = size * units.Gi / (block_size_mb * units.Mi)

        self._execute('dd', 'if=/dev/zero', 'of=%s' % path,
                      'bs=%dM' % block_size_mb,
                      'count=%d' % block_count,
                      run_as_root=True)

    def _gpfs_change_attributes(self, options, path):
        """Update GPFS attributes on the specified file."""

        cmd = ['mmchattr']
        cmd.extend(options)
        cmd.append(path)
        LOG.debug('Update volume attributes with mmchattr to %s.' % options)
        self._execute(*cmd, run_as_root=True)

    def _set_volume_attributes(self, path, metadata):
        """Set various GPFS attributes for this volume."""

        set_pool = False
        options = []
        for item in metadata:
            if item['key'] == 'data_pool_name':
                options.extend(['-P', item['value']])
                set_pool = True
            elif item['key'] == 'replicas':
                options.extend(['-r', item['value'], '-m', item['value']])
            elif item['key'] == 'dio':
                options.extend(['-D', item['value']])
            elif item['key'] == 'write_affinity_depth':
                options.extend(['--write-affinity-depth', item['value']])
            elif item['key'] == 'block_group_factor':
                options.extend(['--block-group-factor', item['value']])
            elif item['key'] == 'write_affinity_failure_group':
                options.extend(['--write-affinity-failure-group',
                               item['value']])

        # metadata value has precedence over value set in volume type
        if self.configuration.gpfs_storage_pool and not set_pool:
            options.extend(['-P', self.configuration.gpfs_storage_pool])

        if options:
            self._gpfs_change_attributes(options, path)

    def create_volume(self, volume):
        """Creates a GPFS volume."""
        # Check if GPFS is mounted
        self._verify_gpfs_path_state(self.configuration.gpfs_mount_point_base)

        volume_path = self.local_path(volume)
        volume_size = volume['size']

        # Create a sparse file first; allocate blocks later if requested
        self._create_sparse_file(volume_path, volume_size)
        self._set_rw_permission(volume_path)
        # Set the attributes prior to allocating any blocks so that
        # they are allocated according to the policy
        v_metadata = volume.get('volume_metadata')
        self._set_volume_attributes(volume_path, v_metadata)

        if not self.configuration.gpfs_sparse_volumes:
            self._allocate_file_blocks(volume_path, volume_size)

        fstype = None
        fslabel = None
        for item in v_metadata:
            if item['key'] == 'fstype':
                fstype = item['value']
            elif item['key'] == 'fslabel':
                fslabel = item['value']
        if fstype:
            self._mkfs(volume, fstype, fslabel)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a GPFS volume from a snapshot."""

        volume_path = self.local_path(volume)
        snapshot_path = self.local_path(snapshot)
        self._create_gpfs_copy(src=snapshot_path, dest=volume_path)
        self._set_rw_permission(volume_path)
        self._gpfs_redirect(volume_path)
        virt_size = self._resize_volume_file(volume, volume['size'])
        return {'size': math.ceil(virt_size / units.Gi)}

    def create_cloned_volume(self, volume, src_vref):
        """Create a GPFS volume from another volume."""

        src = self.local_path(src_vref)
        dest = self.local_path(volume)
        self._create_gpfs_clone(src, dest)
        self._set_rw_permission(dest)
        virt_size = self._resize_volume_file(volume, volume['size'])
        return {'size': math.ceil(virt_size / units.Gi)}

    def _delete_gpfs_file(self, fchild):
        """Delete a GPFS file and cleanup clone children."""

        if not os.path.exists(fchild):
            return
        (out, err) = self._execute('mmclone', 'show', fchild, run_as_root=True)
        fparent = None
        inode_regex = re.compile(
            r'.*\s+(?:yes|no)\s+\d+\s+(?P<inode>\d+)', re.M | re.S)
        match = inode_regex.match(out)
        if match:
            inode = match.group('inode')
            path = os.path.dirname(fchild)
            (out, err) = self._execute('find', path, '-maxdepth', '1',
                                       '-inum', inode, run_as_root=True)
            if out:
                fparent = out.split('\n', 1)[0]
        self._execute(
            'rm', '-f', fchild, check_exit_code=False, run_as_root=True)

        # There is no need to check for volume references on this snapshot
        # because 'rm -f' itself serves as a simple and implicit check. If the
        # parent is referenced by another volume, GPFS doesn't allow deleting
        # it. 'rm -f' silently fails and the subsequent check on the path
        # indicates whether there are any volumes derived from that snapshot.
        # If there are such volumes, we quit recursion and let the other
        # volumes delete the snapshot later. If there are no references, rm
        # would succeed and the snapshot is deleted.
        if not os.path.exists(fchild) and fparent:
            fpbase = os.path.basename(fparent)
            if fpbase.endswith('.snap') or fpbase.endswith('.ts'):
                self._delete_gpfs_file(fparent)

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
        (out, err) = self._execute('mmclone', 'show', src, run_as_root=True)
        depth_regex = re.compile(r'.*\s+no\s+(?P<depth>\d+)', re.M | re.S)
        match = depth_regex.match(out)
        if match:
            depth = int(match.group('depth'))
            if depth > max_depth:
                self._execute('mmclone', 'redirect', src, run_as_root=True)
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
        self._execute('mmclone', 'copy', src, dest, run_as_root=True)

    def _create_gpfs_snap(self, src, dest=None):
        """Create a GPFS file clone snapshot for the specified file."""
        if dest is None:
            self._execute('mmclone', 'snap', src, run_as_root=True)
        else:
            self._execute('mmclone', 'snap', src, dest, run_as_root=True)

    def _is_gpfs_parent_file(self, gpfs_file):
        """Return true if the specified file is a gpfs clone parent."""
        out, err = self._execute('mmclone', 'show', gpfs_file,
                                 run_as_root=True)
        ptoken = out.splitlines().pop().split()[0]
        return ptoken == 'yes'

    def create_snapshot(self, snapshot):
        """Creates a GPFS snapshot."""
        snapshot_path = self.local_path(snapshot)
        volume_path = os.path.join(self.configuration.gpfs_mount_point_base,
                                   snapshot['volume_name'])
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
        snapshot_path = self.local_path(snapshot)
        snapshot_ts_path = '%s.ts' % snapshot_path
        self._execute('mv', snapshot_path, snapshot_ts_path, run_as_root=True)
        self._execute('rm', '-f', snapshot_ts_path,
                      check_exit_code=False, run_as_root=True)

    def local_path(self, volume):
        """Return the local path for the specified volume."""
        return os.path.join(self.configuration.gpfs_mount_point_base,
                            volume['name'])

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'local',
            'data': {
                'name': volume['name'],
                'device_path': self.local_path(volume),
            }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, or stats have never been updated, run update
        the stats first.
        """
        if not self._stats or refresh:
            self._update_volume_stats()

        return self._stats

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

        data['reserved_percentage'] = 0
        self._stats = data

    def clone_image(self, volume, image_location, image_id, image_meta):
        """Create a volume from the specified image."""
        return self._clone_image(volume, image_location, image_id)

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
            LOG.debug('Image %(img)s not cloneable: %(reas)s.' %
                      {'img': image_id, 'reas': reason})
            return (None, False)

        vol_path = self.local_path(volume)
        # if the image is not already a GPFS snap file make it so
        if not self._is_gpfs_parent_file(image_path):
            self._create_gpfs_snap(image_path)

        data = image_utils.qemu_img_info(image_path)

        # if image format is already raw either clone it or
        # copy it depending on config file settings
        if data.file_format == 'raw':
            if (self.configuration.gpfs_images_share_mode ==
                    'copy_on_write'):
                LOG.debug('Clone image to vol %s using mmclone.' %
                          volume['id'])
                self._create_gpfs_copy(image_path, vol_path)
            elif self.configuration.gpfs_images_share_mode == 'copy':
                LOG.debug('Clone image to vol %s using copyfile.' %
                          volume['id'])
                shutil.copyfile(image_path, vol_path)

        # if image is not raw convert it to raw into vol_path destination
        else:
            LOG.debug('Clone image to vol %s using qemu convert.' %
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

        LOG.debug('Copy image to vol %s using image_utils fetch_to_raw.' %
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
            LOG.error(_("Failed to resize volume "
                        "%(volume_id)s, error: %(error)s.") %
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
        image_utils.upload_volume(context,
                                  image_service,
                                  image_meta,
                                  self.local_path(volume))

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume."""
        volume = self.db.volume_get(context, backup['volume_id'])
        volume_path = self.local_path(volume)
        LOG.debug('Begin backup of volume %s.' % volume['name'])

        # create a snapshot that will be used as the backup source
        backup_path = '%s_%s' % (volume_path, backup['id'])
        self._create_gpfs_clone(volume_path, backup_path)
        self._gpfs_redirect(volume_path)

        try:
            with utils.temporary_chown(backup_path):
                with fileutils.file_open(backup_path) as backup_file:
                    backup_service.backup(backup, backup_file)
        finally:
            # clean up snapshot file.  If it is a clone parent, delete
            # will fail silently, but be cleaned up when volume is
            # eventually removed.  This ensures we do not accumulate
            # more than gpfs_max_clone_depth snap files.
            self._delete_gpfs_file(backup_path)

    def restore_backup(self, context, backup, volume, backup_service):
        """Restore an existing backup to a new or existing volume."""
        LOG.debug('Begin restore of backup %s.' % backup['id'])

        volume_path = self.local_path(volume)
        with utils.temporary_chown(volume_path):
            with fileutils.file_open(volume_path, 'wb') as volume_file:
                backup_service.restore(backup, volume['id'], volume_file)

    def _migrate_volume(self, volume, host):
        """Migrate vol if source and dest are managed by same GPFS cluster."""
        LOG.debug('Migrate volume request %(vol)s to %(host)s.' %
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
        local_path = self.local_path(volume)
        new_path = os.path.join(dest_path, volume['name'])
        try:
            self._execute('mv', local_path, new_path, run_as_root=True)
            return (True, None)
        except processutils.ProcessExecutionError as exc:
            LOG.error(_('Driver-based migration of volume %(vol)s failed. '
                        'Move from %(src)s to %(dst)s failed with error: '
                        '%(error)s.') %
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
                  '(host: %(host)s), diff %(diff)s.' %
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
            LOG.debug('Retype request is for different backends, '
                      'use migration: %s %s.' % backends)
            return False

        if _different(pools):
            old, new = pools
            LOG.debug('Retype pool attribute from %s to %s.' % pools)
            retyped = self._update_volume_storage_pool(self.local_path(volume),
                                                       new)

        if _different(hosts):
            LOG.debug('Retype hosts migrate from: %s to %s.' % hosts)
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

        out, err = self._execute('df', '-P', '-B', '1', path,
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
