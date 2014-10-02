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
import time

from oslo.config import cfg

from cinder.brick.remotefs import remotefs as remotefs_brick
from cinder import compute
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder.openstack.common import fileutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder.openstack.common import units
from cinder import utils
from cinder.volume.drivers import remotefs as remotefs_drv

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('glusterfs_shares_config',
               default='/etc/cinder/glusterfs_shares',
               help='File with the list of available gluster shares'),
    cfg.BoolOpt('glusterfs_sparsed_volumes',
                default=True,
                help=('Create volumes as sparsed files which take no space.'
                      'If set to False volume is created as regular file.'
                      'In such case volume creation takes a lot of time.')),
    cfg.BoolOpt('glusterfs_qcow2_volumes',
                default=False,
                help=('Create volumes as QCOW2 files rather than raw files.')),
    cfg.StrOpt('glusterfs_mount_point_base',
               default='$state_path/mnt',
               help='Base dir containing mount points for gluster shares.'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)
CONF.import_opt('volume_name_template', 'cinder.db')


class GlusterfsDriver(remotefs_drv.RemoteFSSnapDriver):
    """Gluster based cinder driver. Creates file on Gluster share for using it
    as block device on hypervisor.

    Operations such as create/delete/extend volume/snapshot use locking on a
    per-process basis to prevent multiple threads from modifying qcow2 chains
    or the snapshot .info file simultaneously.
    """

    driver_volume_type = 'glusterfs'
    driver_prefix = 'glusterfs'
    volume_backend_name = 'GlusterFS'
    VERSION = '1.2.0'

    def __init__(self, execute=processutils.execute, *args, **kwargs):
        self._remotefsclient = None
        super(GlusterfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)
        self._nova = None
        self.base = getattr(self.configuration,
                            'glusterfs_mount_point_base',
                            CONF.glusterfs_mount_point_base)
        self._remotefsclient = remotefs_brick.RemoteFsClient(
            'glusterfs',
            execute,
            glusterfs_mount_point_base=self.base)

    def set_execute(self, execute):
        super(GlusterfsDriver, self).set_execute(execute)
        if self._remotefsclient:
            self._remotefsclient.set_execute(execute)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(GlusterfsDriver, self).do_setup(context)

        self._nova = compute.API()

        config = self.configuration.glusterfs_shares_config
        if not config:
            msg = (_("There's no Gluster config file configured (%s)") %
                   'glusterfs_shares_config')
            LOG.warn(msg)
            raise exception.GlusterfsException(msg)
        if not os.path.exists(config):
            msg = (_("Gluster config file at %(config)s doesn't exist") %
                   {'config': config})
            LOG.warn(msg)
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
                LOG.warning(_('Exception during unmounting %s') % (exc))

    def _do_umount(self, ignore_not_mounted, share):
        mount_path = self._get_mount_point_for_share(share)
        command = ['umount', mount_path]
        try:
            self._execute(*command, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            if ignore_not_mounted and 'not mounted' in exc.stderr:
                LOG.info(_("%s is already umounted"), share)
            else:
                LOG.error(_("Failed to umount %(share)s, reason=%(stderr)s"),
                          {'share': share, 'stderr': exc.stderr})
                raise

    def _refresh_mounts(self):
        try:
            self._unmount_shares()
        except processutils.ProcessExecutionError as exc:
            if 'target is busy' in exc.stderr:
                LOG.warn(_("Failed to refresh mounts, reason=%s") %
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

    @utils.synchronized('glusterfs', external=False)
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        self._create_cloned_volume(volume, src_vref)

    @utils.synchronized('glusterfs', external=False)
    def create_volume(self, volume):
        """Creates a volume."""

        self._ensure_shares_mounted()

        volume['provider_location'] = self._find_share(volume['size'])

        LOG.info(_('casted to %s') % volume['provider_location'])

        self._do_create_volume(volume)

        return {'provider_location': volume['provider_location']}

    @utils.synchronized('glusterfs', external=False)
    def create_volume_from_snapshot(self, volume, snapshot):
        self._create_volume_from_snapshot(volume, snapshot)

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

        if self.configuration.glusterfs_qcow2_volumes:
            out_format = 'qcow2'
        else:
            out_format = 'raw'

        image_utils.convert_image(path_to_snap_img,
                                  path_to_new_vol,
                                  out_format)

        self._set_rw_permissions_for_all(path_to_new_vol)

    @utils.synchronized('glusterfs', external=False)
    def delete_volume(self, volume):
        """Deletes a logical volume."""

        if not volume['provider_location']:
            LOG.warn(_('Volume %s does not have provider_location specified, '
                     'skipping'), volume['name'])
            return

        self._ensure_share_mounted(volume['provider_location'])

        volume_dir = self._local_volume_dir(volume)
        mounted_path = os.path.join(volume_dir,
                                    self.get_active_image_from_info(volume))

        self._execute('rm', '-f', mounted_path, run_as_root=True)

        # If an exception (e.g. timeout) occurred during delete_snapshot, the
        # base volume may linger around, so just delete it if it exists
        base_volume_path = self._local_path_volume(volume)
        fileutils.delete_if_exists(base_volume_path)

        info_path = self._local_path_volume_info(volume)
        fileutils.delete_if_exists(info_path)

    @utils.synchronized('glusterfs', external=False)
    def create_snapshot(self, snapshot):
        """Apply locking to the create snapshot operation."""

        return self._create_snapshot(snapshot)

    def _get_matching_backing_file(self, backing_chain, snapshot_file):
        return next(f for f in backing_chain
                    if f.get('backing-filename', '') == snapshot_file)

    @utils.synchronized('glusterfs', external=False)
    def delete_snapshot(self, snapshot):
        """Apply locking to the delete snapshot operation."""
        self._delete_snapshot(snapshot)

    def _delete_snapshot_online(self, context, snapshot, info):
        # Update info over the course of this method
        # active file never changes
        info_path = self._local_path_volume(snapshot['volume']) + '.info'
        snap_info = self._read_info_file(info_path)

        if info['active_file'] == info['snapshot_file']:
            # blockRebase/Pull base into active
            # info['base'] => snapshot_file

            file_to_delete = info['base_file']
            if info['base_id'] is None:
                # Passing base=none to blockRebase ensures that
                # libvirt blanks out the qcow2 backing file pointer
                new_base = None
            else:
                new_base = info['new_base_file']
                snap_info[info['base_id']] = info['snapshot_file']

            delete_info = {'file_to_merge': new_base,
                           'merge_target_file': None,  # current
                           'type': 'qcow2',
                           'volume_id': snapshot['volume']['id']}

            del(snap_info[snapshot['id']])
        else:
            # blockCommit snapshot into base
            # info['base'] <= snapshot_file
            # delete record of snapshot
            file_to_delete = info['snapshot_file']

            delete_info = {'file_to_merge': info['snapshot_file'],
                           'merge_target_file': info['base_file'],
                           'type': 'qcow2',
                           'volume_id': snapshot['volume']['id']}

            del(snap_info[snapshot['id']])

        try:
            self._nova.delete_volume_snapshot(
                context,
                snapshot['id'],
                delete_info)
        except Exception as e:
            LOG.error(_('Call to Nova delete snapshot failed'))
            LOG.exception(e)
            raise e

        # Loop and wait for result
        # Nova will call Cinderclient to update the status in the database
        # An update of progress = '90%' means that Nova is done
        seconds_elapsed = 0
        increment = 1
        timeout = 7200
        while True:
            s = db.snapshot_get(context, snapshot['id'])

            if s['status'] == 'deleting':
                if s['progress'] == '90%':
                    # Nova tasks completed successfully
                    break
                else:
                    msg = ('status of snapshot %s is '
                           'still "deleting"... waiting') % snapshot['id']
                    LOG.debug(msg)
                    time.sleep(increment)
                    seconds_elapsed += increment
            else:
                msg = _('Unable to delete snapshot %(id)s, '
                        'status: %(status)s.') % {'id': snapshot['id'],
                                                  'status': s['status']}
                raise exception.GlusterfsException(msg)

            if 10 < seconds_elapsed <= 20:
                increment = 2
            elif 20 < seconds_elapsed <= 60:
                increment = 5
            elif 60 < seconds_elapsed:
                increment = 10

            if seconds_elapsed > timeout:
                msg = _('Timed out while waiting for Nova update '
                        'for deletion of snapshot %(id)s.') %\
                    {'id': snapshot['id']}
                raise exception.GlusterfsException(msg)

        # Write info file updated above
        self._write_info_file(info_path, snap_info)

        # Delete stale file
        path_to_delete = os.path.join(
            self._local_volume_dir(snapshot['volume']), file_to_delete)
        self._execute('rm', '-f', path_to_delete, run_as_root=True)

    def ensure_export(self, ctx, volume):
        """Synchronously recreates an export for a logical volume."""

        self._ensure_share_mounted(volume['provider_location'])

    def create_export(self, ctx, volume):
        """Exports the volume."""
        pass

    def remove_export(self, ctx, volume):
        """Removes an export for a logical volume."""

        pass

    def validate_connector(self, connector):
        pass

    @utils.synchronized('glusterfs', external=False)
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

    @utils.synchronized('glusterfs', external=False)
    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        self._copy_volume_to_image(context, volume, image_service,
                                   image_meta)

    @utils.synchronized('glusterfs', external=False)
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
        """Create a volume on given glusterfs_share.

        :param volume: volume reference
        """

        volume_path = self.local_path(volume)
        volume_size = volume['size']

        LOG.debug("creating new volume at %s" % volume_path)

        if os.path.exists(volume_path):
            msg = _('file already exists at %s') % volume_path
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        if self.configuration.glusterfs_qcow2_volumes:
            self._create_qcow2_file(volume_path, volume_size)
        else:
            if self.configuration.glusterfs_sparsed_volumes:
                self._create_sparsed_file(volume_path, volume_size)
            else:
                self._create_regular_file(volume_path, volume_size)

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
                LOG.error(_('Exception during mounting %s') % (exc,))

        LOG.debug('Available shares: %s' % self._mounted_shares)

    def _ensure_share_mounted(self, glusterfs_share):
        """Mount GlusterFS share.
        :param glusterfs_share: string
        """
        mount_path = self._get_mount_point_for_share(glusterfs_share)
        self._mount_glusterfs(glusterfs_share, mount_path, ensure=True)

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

    def _mount_glusterfs(self, glusterfs_share, mount_path, ensure=False):
        """Mount GlusterFS share to mount path."""
        # TODO(eharney): make this fs-agnostic and factor into remotefs
        self._execute('mkdir', '-p', mount_path)

        command = ['mount', '-t', 'glusterfs', glusterfs_share,
                   mount_path]
        if self.shares.get(glusterfs_share) is not None:
            command.extend(self.shares[glusterfs_share].split())

        self._do_mount(command, ensure, glusterfs_share)

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

        volume_dir = self._local_volume_dir(volume)
        active_file_path = os.path.join(
            volume_dir,
            self.get_active_image_from_info(volume))

        info = self._qemu_img_info(active_file_path, volume['name'])

        if info.backing_file is not None:
            msg = _('No snapshots found in database, but '
                    '%(path)s has backing file '
                    '%(backing_file)s!') % {'path': active_file_path,
                                            'backing_file': info.backing_file}
            LOG.error(msg)
            raise exception.InvalidVolume(snap_error_msg)

        if info.file_format != 'raw':
            msg = _('Backup is only supported for raw-formatted '
                    'GlusterFS volumes.')
            raise exception.InvalidVolume(msg)

        return super(GlusterfsDriver, self).backup_volume(
            context, backup, backup_service)

    def _create_snapshot_online(self, snapshot, backing_filename,
                                new_snap_path):
        # Perform online snapshot via Nova
        context = snapshot['context']

        self._do_create_snapshot(snapshot,
                                 backing_filename,
                                 new_snap_path)

        connection_info = {
            'type': 'qcow2',
            'new_file': os.path.basename(new_snap_path),
            'snapshot_id': snapshot['id']
        }

        try:
            result = self._nova.create_volume_snapshot(
                context,
                snapshot['volume_id'],
                connection_info)
            LOG.debug('nova call result: %s' % result)
        except Exception as e:
            LOG.error(_('Call to Nova to create snapshot failed'))
            LOG.exception(e)
            raise e

        # Loop and wait for result
        # Nova will call Cinderclient to update the status in the database
        # An update of progress = '90%' means that Nova is done
        seconds_elapsed = 0
        increment = 1
        timeout = 600
        while True:
            s = db.snapshot_get(context, snapshot['id'])

            if s['status'] == 'creating':
                if s['progress'] == '90%':
                    # Nova tasks completed successfully
                    break

                time.sleep(increment)
                seconds_elapsed += increment
            elif s['status'] == 'error':

                msg = _('Nova returned "error" status '
                        'while creating snapshot.')
                raise exception.RemoteFSException(msg)

            LOG.debug('Status of snapshot %(id)s is now %(status)s' % {
                'id': snapshot['id'],
                'status': s['status']
            })

            if 10 < seconds_elapsed <= 20:
                increment = 2
            elif 20 < seconds_elapsed <= 60:
                increment = 5
            elif 60 < seconds_elapsed:
                increment = 10

            if seconds_elapsed > timeout:
                msg = _('Timed out while waiting for Nova update '
                        'for creation of snapshot %s.') % snapshot['id']
                raise exception.RemoteFSException(msg)
