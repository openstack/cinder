# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from oslo.config import cfg

from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import fileutils
from cinder.openstack.common import log as logging
from cinder import units
from cinder.volume import driver

VERSION = 1.0
LOG = logging.getLogger(__name__)

gpfs_opts = [
    cfg.StrOpt('gpfs_mount_point_base',
               default=None,
               help='Path to the directory on GPFS mount point where '
                    'volumes are stored'),
    cfg.StrOpt('gpfs_images_dir',
               default=None,
               help='Path to GPFS Glance repository as mounted on '
                    'Nova nodes'),
    cfg.StrOpt('gpfs_images_share_mode',
               default=None,
               help='Set this if Glance image repo is on GPFS as well '
                    'so that the image bits can be transferred efficiently '
                    'between Glance and Cinder.  Valid values are copy or '
                    'copy_on_write. copy performs a full copy of the image, '
                    'copy_on_write efficiently shares unmodified blocks of '
                    'the image.'),
    cfg.IntOpt('gpfs_max_clone_depth',
               default=0,
               help='A lengthy chain of copy-on-write snapshots or clones '
                    'could have impact on performance.  This option limits '
                    'the number of indirections required to reach a specific '
                    'block. 0 indicates unlimited.'),
    cfg.BoolOpt('gpfs_sparse_volumes',
                default=True,
                help=('Create volumes as sparse files which take no space. '
                      'If set to False volume is created as regular file. '
                      'In this case volume creation may take a significantly '
                      'longer time.')),
]
CONF = cfg.CONF
CONF.register_opts(gpfs_opts)


class GPFSDriver(driver.VolumeDriver):

    """Implements volume functions using GPFS primitives."""

    def __init__(self, *args, **kwargs):
        super(GPFSDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(gpfs_opts)

    def _get_gpfs_state(self):
        (out, _) = self._execute('mmgetstate', '-Y', run_as_root=True)
        return out

    def _check_gpfs_state(self):
        out = self._get_gpfs_state()
        lines = out.splitlines()
        state_token = lines[0].split(':').index('state')
        gpfs_state = lines[1].split(':')[state_token]
        if gpfs_state != 'active':
            LOG.error(_('GPFS is not active.  Detailed output: %s') % out)
            exception_message = (_("GPFS is not running - state: %s") %
                                 gpfs_state)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _is_gpfs_path(self, directory):
        self._execute('mmlsattr', directory, run_as_root=True)

    def _is_samefs(self, p1, p2):
        if os.lstat(p1).st_dev == os.lstat(p2).st_dev:
            return True
        return False

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self._check_gpfs_state()

        if(self.configuration.gpfs_mount_point_base is None):
            msg = _('Option gpfs_mount_point_base is not set correctly.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if(self.configuration.gpfs_images_share_mode and
           self.configuration.gpfs_images_share_mode not in ['copy_on_write',
                                                             'copy']):
            msg = _('Option gpfs_images_share_mode is not set correctly.')
            LOG.warn(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if(self.configuration.gpfs_images_share_mode and
           self.configuration.gpfs_images_dir is None):
            msg = _('Option gpfs_images_dir is not set correctly.')
            LOG.warn(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if(self.configuration.gpfs_images_share_mode == 'copy_on_write' and
           not self._is_samefs(self.configuration.gpfs_mount_point_base,
                               self.configuration.gpfs_images_dir)):
            msg = (_('gpfs_images_share_mode is set to copy_on_write, but '
                     '%(vol)s and %(img)s belong to different file systems') %
                   {'vol': self.configuration.gpfs_mount_point_base,
                    'img': self.configuration.gpfs_images_dir})
            LOG.warn(msg)
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

            try:
                # check that configured directories are on GPFS
                self._is_gpfs_path(directory)
            except exception.ProcessExecutionError:
                msg = (_('%s is not on GPFS. Perhaps GPFS not mounted.') %
                       directory)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def _create_sparse_file(self, path, size):
        """Creates file with 0 disk usage."""

        sizestr = self._sizestr(size)
        self._execute('truncate', '-s', sizestr, path, run_as_root=True)
        self._execute('chmod', '666', path, run_as_root=True)

    def _create_regular_file(self, path, size):
        """Creates regular file of given size."""

        block_size_mb = 1
        block_count = size * units.GiB / (block_size_mb * units.MiB)

        self._execute('dd', 'if=/dev/zero', 'of=%s' % path,
                      'bs=%dM' % block_size_mb,
                      'count=%d' % block_count,
                      run_as_root=True)
        self._execute('chmod', '666', path, run_as_root=True)

    def create_volume(self, volume):
        """Creates a GPFS volume."""
        volume_path = self.local_path(volume)
        volume_size = volume['size']

        if self.configuration.gpfs_sparse_volumes:
            self._create_sparse_file(volume_path, volume_size)
        else:
            self._create_regular_file(volume_path, volume_size)

        v_metadata = volume.get('volume_metadata')
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
        self._gpfs_redirect(volume_path)
        data = image_utils.qemu_img_info(volume_path)
        return {'size': math.ceil(data.virtual_size / 1024.0 ** 3)}

    def create_cloned_volume(self, volume, src_vref):
        src = self.local_path(src_vref)
        dest = self.local_path(volume)
        self._create_gpfs_clone(src, dest)
        data = image_utils.qemu_img_info(dest)
        return {'size': math.ceil(data.virtual_size / 1024.0 ** 3)}

    def _delete_gpfs_file(self, fchild):
        if not os.path.exists(fchild):
            return
        (out, err) = self._execute('mmclone', 'show', fchild, run_as_root=True)
        fparent = None
        reInode = re.compile(
            '.*\s+(?:yes|no)\s+\d+\s+(?P<inode>\d+)', re.M | re.S)
        match = reInode.match(out)
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
            if (fpbase.startswith('snapshot-') or fpbase.endswith('.snap')):
                self._delete_gpfs_file(fparent)

    def delete_volume(self, volume):
        """Deletes a logical volume."""
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
        reDepth = re.compile('.*\s+no\s+(?P<depth>\d+)', re.M | re.S)
        match = reDepth.match(out)
        if match:
            depth = int(match.group('depth'))
            if depth > max_depth:
                self._execute('mmclone', 'redirect', src, run_as_root=True)
                return True
        return False

    def _create_gpfs_clone(self, src, dest):
        snap = dest + ".snap"
        self._create_gpfs_snap(src, snap)
        self._create_gpfs_copy(snap, dest)
        if(self._gpfs_redirect(src) and self._gpfs_redirect(dest)):
            self._execute('rm', '-f', snap, run_as_root=True)

    def _create_gpfs_copy(self, src, dest, modebits='666'):
        self._execute('mmclone', 'copy', src, dest, run_as_root=True)
        self._execute('chmod', modebits, dest, run_as_root=True)

    def _create_gpfs_snap(self, src, dest=None, modebits='644'):
        if dest is None:
            self._execute('mmclone', 'snap', src, run_as_root=True)
            self._execute('chmod', modebits, src, run_as_root=True)
        else:
            self._execute('mmclone', 'snap', src, dest, run_as_root=True)
            self._execute('chmod', modebits, dest, run_as_root=True)

    def _is_gpfs_parent_file(self, gpfs_file):
        out, _ = self._execute('mmclone', 'show', gpfs_file, run_as_root=True)
        ptoken = out.splitlines().pop().split()[0]
        return ptoken == 'yes'

    def create_snapshot(self, snapshot):
        """Creates a GPFS snapshot."""
        snapshot_path = self.local_path(snapshot)
        volume_path = os.path.join(self.configuration.gpfs_mount_point_base,
                                   snapshot['volume_name'])
        self._create_gpfs_snap(src=volume_path, dest=snapshot_path)

    def delete_snapshot(self, snapshot):
        """Deletes a GPFS snapshot."""
        # A snapshot file is deleted as a part of delete_volume when
        # all volumes derived from it are deleted.

    def local_path(self, volume):
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
        """Get volume status.

        If 'refresh' is True, or stats have never been updated, run update
        the stats first.
        """
        if not self._stats or refresh:
            self._update_volume_status()

        return self._stats

    def _update_volume_status(self):
        """Retrieve status info from volume group."""

        LOG.debug("Updating volume status")
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or 'GPFS'
        data["vendor_name"] = 'IBM'
        data["driver_version"] = '1.0'
        data["storage_protocol"] = 'file'
        free, capacity = self._get_available_capacity(self.configuration.
                                                      gpfs_mount_point_base)
        data['total_capacity_gb'] = math.ceil(capacity / 1024.0 ** 3)
        data['free_capacity_gb'] = math.ceil(free / 1024.0 ** 3)
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        self._stats = data

    def _sizestr(self, size_in_g):
        if int(size_in_g) == 0:
            return '100M'
        return '%sG' % size_in_g

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        return self._gpfs_fetch_to_raw(context, image_service, image_id,
                                       self.local_path(volume))

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        image_utils.upload_volume(context,
                                  image_service,
                                  image_meta,
                                  self.local_path(volume))

    def _mkfs(self, volume, fs, label=None):
        if fs == 'swap':
            cmd = ['mkswap']
        else:
            cmd = ['mkfs', '-t', fs]

        if fs in ('ext3', 'ext4'):
            cmd.append('-F')
        if label:
            if fs in ('msdos', 'vfat'):
                label_opt = '-n'
            else:
                label_opt = '-L'
            cmd.extend([label_opt, label])

        path = self.local_path(volume)
        cmd.append(path)
        try:
            self._execute(*cmd, run_as_root=True)
        except exception.ProcessExecutionError as exc:
            exception_message = (_("mkfs failed on volume %(vol)s, "
                                   "error message was: %(err)s")
                                 % {'vol': volume['name'], 'err': exc.stderr})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                data=exception_message)

    def _get_available_capacity(self, path):
        """Calculate available space on path."""
        out, _ = self._execute('df', '-P', '-B', '1', path,
                               run_as_root=True)
        out = out.splitlines()[1]
        size = int(out.split()[1])
        available = int(out.split()[3])
        return available, size

    def _gpfs_fetch(self, context, image_service, image_id, path, _user_id,
                    _project_id):
        if not (self.configuration.gpfs_images_share_mode and
                self.configuration.gpfs_images_dir and
                os.path.exists(
                    os.path.join(self.configuration.gpfs_images_dir,
                                 image_id))):
            with fileutils.remove_path_on_error(path):
                with open(path, "wb") as image_file:
                    image_service.download(context, image_id, image_file)
        else:
            image_path = os.path.join(self.configuration.gpfs_images_dir,
                                      image_id)
            if self.configuration.gpfs_images_share_mode == 'copy_on_write':
                # check if the image is a GPFS snap file
                if not self._is_gpfs_parent_file(image_path):
                    self._create_gpfs_snap(image_path, modebits='666')
                self._execute('ln', '-s', image_path, path, run_as_root=True)
            else:  # copy
                self._execute('cp', image_path, path, run_as_root=True)
                self._execute('chmod', '666', path, run_as_root=True)

    def _gpfs_fetch_to_raw(self, context, image_service, image_id, dest,
                           user_id=None, project_id=None):
        if (self.configuration.image_conversion_dir and not
                os.path.exists(self.configuration.image_conversion_dir)):
            os.makedirs(self.configuration.image_conversion_dir)

        tmp = "%s.part" % dest
        with fileutils.remove_path_on_error(tmp):
            self._gpfs_fetch(context, image_service, image_id, tmp, user_id,
                             project_id)

            data = image_utils.qemu_img_info(tmp)
            fmt = data.file_format
            if fmt is None:
                msg = _("'qemu-img info' parsing failed.")
                LOG.error(msg)
                raise exception.ImageUnacceptable(
                    reason=msg,
                    image_id=image_id)

            backing_file = data.backing_file
            if backing_file is not None:
                msg = (_("fmt = %(fmt)s backed by: %(backing_file)s") %
                       {'fmt': fmt, 'backing_file': backing_file})
                LOG.error(msg)
                raise exception.ImageUnacceptable(
                    image_id=image_id,
                    reason=msg)

            LOG.debug("%s was %s, converting to raw" % (image_id, fmt))
            image_utils.convert_image(tmp, dest, 'raw')

            data = image_utils.qemu_img_info(dest)
            if data.file_format != "raw":
                msg = (_("Converted to raw, but format is now %s") %
                       data.file_format)
                LOG.error(msg)
                raise exception.ImageUnacceptable(
                    image_id=image_id,
                    reason=msg)
            os.unlink(tmp)
            return {'size': math.ceil(data.virtual_size / 1024.0 ** 3)}
