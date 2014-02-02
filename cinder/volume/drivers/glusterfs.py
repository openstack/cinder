# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import hashlib
import json
import os
import re
import stat
import tempfile
import time

from oslo.config import cfg

from cinder import compute
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder import units
from cinder import utils
from cinder.volume.drivers import nfs

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('glusterfs_shares_config',
               default='/etc/cinder/glusterfs_shares',
               help='File with the list of available gluster shares'),
    cfg.StrOpt('glusterfs_disk_util',
               default='df',
               help='Use du or df for free space calculation'),
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


class GlusterfsDriver(nfs.RemoteFsDriver):
    """Gluster based cinder driver. Creates file on Gluster share for using it
    as block device on hypervisor.

    Operations such as create/delete/extend volume/snapshot use locking on a
    per-process basis to prevent multiple threads from modifying qcow2 chains
    or the snapshot .info file simultaneously.
    """

    driver_volume_type = 'glusterfs'
    driver_prefix = 'glusterfs'
    volume_backend_name = 'GlusterFS'
    VERSION = '1.1.0'

    def __init__(self, *args, **kwargs):
        super(GlusterfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)
        self._nova = None

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

        self._ensure_shares_mounted()

    def check_for_setup_error(self):
        """Just to override parent behavior."""
        pass

    def _local_volume_dir(self, volume):
        hashed = self._get_hash_str(volume['provider_location'])
        path = '%s/%s' % (self.configuration.glusterfs_mount_point_base,
                          hashed)
        return path

    def _local_path_volume(self, volume):
        path_to_disk = '%s/%s' % (
            self._local_volume_dir(volume),
            volume['name'])

        return path_to_disk

    def _local_path_volume_info(self, volume):
        return '%s%s' % (self._local_path_volume(volume), '.info')

    def _qemu_img_info(self, path):
        """Sanitize image_utils' qemu_img_info.

        This code expects to deal only with relative filenames.
        """

        info = image_utils.qemu_img_info(path)
        if info.image:
            info.image = os.path.basename(info.image)
        if info.backing_file:
            info.backing_file = os.path.basename(info.backing_file)

        return info

    def get_active_image_from_info(self, volume):
        """Returns filename of the active image from the info file."""

        info_file = self._local_path_volume_info(volume)

        snap_info = self._read_info_file(info_file, empty_if_missing=True)

        if snap_info == {}:
            # No info file = no snapshots exist
            vol_path = os.path.basename(self._local_path_volume(volume))
            return vol_path

        return snap_info['active']

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""

        LOG.info(_('Cloning volume %(src)s to volume %(dst)s') %
                 {'src': src_vref['id'],
                  'dst': volume['id']})

        if src_vref['status'] != 'available':
            msg = _("Volume status must be 'available'.")
            raise exception.InvalidVolume(msg)

        volume_name = CONF.volume_name_template % volume['id']

        volume_info = {'provider_location': src_vref['provider_location'],
                       'size': src_vref['size'],
                       'id': volume['id'],
                       'name': volume_name,
                       'status': src_vref['status']}
        temp_snapshot = {'volume_name': volume_name,
                         'size': src_vref['size'],
                         'volume_size': src_vref['size'],
                         'name': 'clone-snap-%s' % src_vref['id'],
                         'volume_id': src_vref['id'],
                         'id': 'tmp-snap-%s' % src_vref['id'],
                         'volume': src_vref}
        self.create_snapshot(temp_snapshot)
        try:
            self._copy_volume_from_snapshot(temp_snapshot,
                                            volume_info,
                                            src_vref['size'])

        finally:
            self.delete_snapshot(temp_snapshot)

        return {'provider_location': src_vref['provider_location']}

    @utils.synchronized('glusterfs', external=False)
    def create_volume(self, volume):
        """Creates a volume."""

        self._ensure_shares_mounted()

        volume['provider_location'] = self._find_share(volume['size'])

        LOG.info(_('casted to %s') % volume['provider_location'])

        self._do_create_volume(volume)

        return {'provider_location': volume['provider_location']}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        Snapshot must not be the active snapshot. (offline)
        """

        if snapshot['status'] != 'available':
            msg = _('Snapshot status must be "available" to clone.')
            raise exception.InvalidSnapshot(msg)

        self._ensure_shares_mounted()

        volume['provider_location'] = self._find_share(volume['size'])

        self._do_create_volume(volume)

        self._copy_volume_from_snapshot(snapshot,
                                        volume,
                                        snapshot['volume_size'])

        return {'provider_location': volume['provider_location']}

    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size):
        """Copy data from snapshot to destination volume.

        This is done with a qemu-img convert to raw/qcow2 from the snapshot
        qcow2.
        """

        LOG.debug(_("snapshot: %(snap)s, volume: %(vol)s, "
                    "volume_size: %(size)s")
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
        img_info = self._qemu_img_info(forward_path)
        path_to_snap_img = os.path.join(vol_path, img_info.backing_file)

        path_to_new_vol = self._local_path_volume(volume)

        LOG.debug(_("will copy from snapshot at %s") % path_to_snap_img)

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

        mounted_path = self.local_path(volume)

        self._execute('rm', '-f', mounted_path, run_as_root=True)

    @utils.synchronized('glusterfs', external=False)
    def create_snapshot(self, snapshot):
        """Create a snapshot.

        If volume is attached, call to Nova to create snapshot,
        providing a qcow2 file.
        Otherwise, create locally with qemu-img.

        A file named volume-<uuid>.info is stored with the volume
        data and is a JSON table which contains a mapping between
        Cinder snapshot UUIDs and filenames, as these associations
        will change as snapshots are deleted.


        Basic snapshot operation:

        1. Initial volume file:
            volume-1234

        2. Snapshot created:
            volume-1234  <- volume-1234.aaaa

            volume-1234.aaaa becomes the new "active" disk image.
            If the volume is not attached, this filename will be used to
            attach the volume to a VM at volume-attach time.
            If the volume is attached, the VM will switch to this file as
            part of the snapshot process.

            Note that volume-1234.aaaa represents changes after snapshot
            'aaaa' was created.  So the data for snapshot 'aaaa' is actually
            in the backing file(s) of volume-1234.aaaa.

            This file has a qcow2 header recording the fact that volume-1234 is
            its backing file.  Delta changes since the snapshot was created are
            stored in this file, and the backing file (volume-1234) does not
            change.

            info file: { 'active': 'volume-1234.aaaa',
                         'aaaa':   'volume-1234.aaaa' }

        3. Second snapshot created:
            volume-1234 <- volume-1234.aaaa <- volume-1234.bbbb

            volume-1234.bbbb now becomes the "active" disk image, recording
            changes made to the volume.

            info file: { 'active': 'volume-1234.bbbb',
                         'aaaa':   'volume-1234.aaaa',
                         'bbbb':   'volume-1234.bbbb' }

        4. First snapshot deleted:
            volume-1234 <- volume-1234.aaaa(* now with bbbb's data)

            volume-1234.aaaa is removed (logically) from the snapshot chain.
            The data from volume-1234.bbbb is merged into it.

            (*) Since bbbb's data was committed into the aaaa file, we have
                "removed" aaaa's snapshot point but the .aaaa file now
                represents snapshot with id "bbbb".


            info file: { 'active': 'volume-1234.bbbb',
                         'bbbb':   'volume-1234.aaaa'   (* changed!)
                       }

        5. Second snapshot deleted:
            volume-1234

            volume-1234.bbbb is removed from the snapshot chain, as above.
            The base image, volume-1234, becomes the active image for this
            volume again.  If in-use, the VM begins using the volume-1234.bbbb
            file immediately as part of the snapshot delete process.

            info file: { 'active': 'volume-1234' }

        For the above operations, Cinder handles manipulation of qcow2 files
        when the volume is detached.  When attached, Cinder creates and deletes
        qcow2 files, but Nova is responsible for transitioning the VM between
        them and handling live transfers of data between files as required.
        """

        status = snapshot['volume']['status']
        if status not in ['available', 'in-use']:
            msg = _('Volume status must be "available" or "in-use"'
                    ' for snapshot. (is %s)') % status
            raise exception.InvalidVolume(msg)

        if status == 'in-use':
            # Perform online snapshot via Nova
            context = snapshot['context']

            backing_filename = self.get_active_image_from_info(
                snapshot['volume'])
            path_to_disk = self._local_path_volume(snapshot['volume'])
            new_snap_path = '%s.%s' % (
                self._local_path_volume(snapshot['volume']),
                snapshot['id'])

            self._create_qcow2_snap_file(snapshot,
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
                LOG.debug(_('nova call result: %s') % result)
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
                    raise exception.GlusterfsException(msg)

                LOG.debug(_('Status of snapshot %(id)s is now %(status)s') % {
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
                    raise exception.GlusterfsException(msg)

            info_path = self._local_path_volume(snapshot['volume']) + '.info'
            snap_info = self._read_info_file(info_path, empty_if_missing=True)
            snap_info['active'] = os.path.basename(new_snap_path)
            snap_info[snapshot['id']] = os.path.basename(new_snap_path)
            self._write_info_file(info_path, snap_info)

            return

        LOG.debug(_('create snapshot: %s') % snapshot)
        LOG.debug(_('volume id: %s') % snapshot['volume_id'])

        path_to_disk = self._local_path_volume(snapshot['volume'])
        snap_id = snapshot['id']
        self._create_snapshot(snapshot, path_to_disk, snap_id)

    def _create_qcow2_snap_file(self, snapshot, backing_filename,
                                new_snap_path):
        """Create a QCOW2 file backed by another file.

        :param snapshot: snapshot reference
        :param backing_filename: filename of file that will back the
            new qcow2 file
        :param new_snap_path: filename of new qcow2 file
        """

        backing_path_full_path = '%s/%s' % (
            self._local_volume_dir(snapshot['volume']),
            backing_filename)

        command = ['qemu-img', 'create', '-f', 'qcow2', '-o',
                   'backing_file=%s' % backing_path_full_path, new_snap_path]
        self._execute(*command, run_as_root=True)

        info = self._qemu_img_info(backing_path_full_path)
        backing_fmt = info.file_format

        command = ['qemu-img', 'rebase', '-u',
                   '-b', backing_filename,
                   '-F', backing_fmt,
                   new_snap_path]
        self._execute(*command, run_as_root=True)

    def _create_snapshot(self, snapshot, path_to_disk, snap_id):
        """Create snapshot (offline case)."""

        # Requires volume status = 'available'

        new_snap_path = '%s.%s' % (path_to_disk, snapshot['id'])

        backing_filename = self.get_active_image_from_info(snapshot['volume'])

        self._create_qcow2_snap_file(snapshot,
                                     backing_filename,
                                     new_snap_path)

        # Update info file

        info_path = self._local_path_volume_info(snapshot['volume'])
        snap_info = self._read_info_file(info_path,
                                         empty_if_missing=True)

        snap_info['active'] = os.path.basename(new_snap_path)
        snap_info[snapshot['id']] = os.path.basename(new_snap_path)
        self._write_info_file(info_path, snap_info)

    def _read_file(self, filename):
        """This method is to make it easier to stub out code for testing.

        Returns a string representing the contents of the file.
        """

        with open(filename, 'r') as f:
            return f.read()

    def _read_info_file(self, info_path, empty_if_missing=False):
        """Return dict of snapshot information."""

        if not os.path.exists(info_path):
            if empty_if_missing is True:
                return {}

        return json.loads(self._read_file(info_path))

    def _write_info_file(self, info_path, snap_info):
        if 'active' not in snap_info.keys():
            msg = _("'active' must be present when writing snap_info.")
            raise exception.GlusterfsException(msg)

        with open(info_path, 'w') as f:
            json.dump(snap_info, f, indent=1, sort_keys=True)

    def _get_matching_backing_file(self, backing_chain, snapshot_file):
        return next(f for f in backing_chain
                    if f.get('backing-filename', '') == snapshot_file)

    @utils.synchronized('glusterfs', external=False)
    def delete_snapshot(self, snapshot):
        """Delete a snapshot.

        If volume status is 'available', delete snapshot here in Cinder
        using qemu-img.

        If volume status is 'in-use', calculate what qcow2 files need to
        merge, and call to Nova to perform this operation.

        :raises: InvalidVolume if status not acceptable
        :raises: GlusterfsException(msg) if operation fails
        :returns: None

        """

        LOG.debug(_('deleting snapshot %s') % snapshot['id'])

        volume_status = snapshot['volume']['status']
        if volume_status not in ['available', 'in-use']:
            msg = _('Volume status must be "available" or "in-use".')
            raise exception.InvalidVolume(msg)

        self._ensure_share_writable(
            self._local_volume_dir(snapshot['volume']))

        # Determine the true snapshot file for this snapshot
        #  based on the .info file
        info_path = self._local_path_volume(snapshot['volume']) + '.info'
        snap_info = self._read_info_file(info_path, empty_if_missing=True)

        if snapshot['id'] not in snap_info:
            # If snapshot info file is present, but snapshot record does not
            # exist, do not attempt to delete.
            # (This happens, for example, if snapshot_create failed due to lack
            # of permission to write to the share.)
            LOG.info(_('Snapshot record for %s is not present, allowing '
                       'snapshot_delete to proceed.') % snapshot['id'])
            return

        snapshot_file = snap_info[snapshot['id']]
        LOG.debug(_('snapshot_file for this snap is %s') % snapshot_file)

        snapshot_path = '%s/%s' % (self._local_volume_dir(snapshot['volume']),
                                   snapshot_file)

        snapshot_path_img_info = self._qemu_img_info(snapshot_path)

        vol_path = self._local_volume_dir(snapshot['volume'])

        # Find what file has this as its backing file
        active_file = self.get_active_image_from_info(snapshot['volume'])
        active_file_path = '%s/%s' % (vol_path, active_file)

        if volume_status == 'in-use':
            # Online delete
            context = snapshot['context']

            base_file = snapshot_path_img_info.backing_file
            if base_file is None:
                # There should always be at least the original volume
                # file as base.
                msg = _('No base file found for %s.') % snapshot_path
                raise exception.GlusterfsException(msg)

            base_path = os.path.join(
                self._local_volume_dir(snapshot['volume']), base_file)
            base_file_img_info = self._qemu_img_info(base_path)
            new_base_file = base_file_img_info.backing_file

            base_id = None
            info_path = self._local_path_volume(snapshot['volume']) + '.info'
            snap_info = self._read_info_file(info_path)
            for key, value in snap_info.iteritems():
                if value == base_file and key != 'active':
                    base_id = key
                    break
            if base_id is None:
                # This means we are deleting the oldest snapshot
                msg = _('No %(base_id)s found for %(file)s') % {
                    'base_id': 'base_id',
                    'file': snapshot_file}
                LOG.debug(msg)

            online_delete_info = {
                'active_file': active_file,
                'snapshot_file': snapshot_file,
                'base_file': base_file,
                'base_id': base_id,
                'new_base_file': new_base_file
            }

            return self._delete_snapshot_online(context,
                                                snapshot,
                                                online_delete_info)

        if snapshot_file == active_file:
            # Need to merge snapshot_file into its backing file
            # There is no top file
            #      T0       |        T1         |
            #     base      |   snapshot_file   | None
            # (guaranteed to|  (being deleted)  |
            #    exist)     |                   |

            base_file = snapshot_path_img_info.backing_file

            self._qemu_img_commit(snapshot_path)
            self._execute('rm', '-f', snapshot_path, run_as_root=True)

            # Remove snapshot_file from info
            info_path = self._local_path_volume(snapshot['volume']) + '.info'
            snap_info = self._read_info_file(info_path)

            del(snap_info[snapshot['id']])
            # Active file has changed
            snap_info['active'] = base_file
            self._write_info_file(info_path, snap_info)
        else:
            #    T0         |      T1        |     T2         |       T3
            #    base       |  snapshot_file |  higher_file   |  highest_file
            #(guaranteed to | (being deleted)|(guaranteed to  |  (may exist,
            #  exist, not   |                | exist, being   |needs ptr update
            #  used here)   |                | committed down)|     if so)

            backing_chain = self._get_backing_chain_for_path(
                snapshot['volume'], active_file_path)
            # This file is guaranteed to exist since we aren't operating on
            # the active file.
            higher_file = next((os.path.basename(f['filename'])
                                for f in backing_chain
                                if f.get('backing-filename', '') ==
                                snapshot_file),
                               None)
            if higher_file is None:
                msg = _('No file found with %s as backing file.') %\
                    snapshot_file
                raise exception.GlusterfsException(msg)

            snap_info = self._read_info_file(info_path)
            higher_id = next((i for i in snap_info
                              if snap_info[i] == higher_file
                              and i != 'active'),
                             None)
            if higher_id is None:
                msg = _('No snap found with %s as backing file.') %\
                    higher_file
                raise exception.GlusterfsException(msg)

            # Is there a file depending on higher_file?
            highest_file = next((os.path.basename(f['filename'])
                                for f in backing_chain
                                if f.get('backing-filename', '') ==
                                higher_file),
                                None)
            if highest_file is None:
                msg = _('No file depends on %s.') % higher_file
                LOG.debug(msg)

            # Committing higher_file into snapshot_file
            # And update pointer in highest_file
            higher_file_path = '%s/%s' % (vol_path, higher_file)
            self._qemu_img_commit(higher_file_path)
            if highest_file is not None:
                highest_file_path = '%s/%s' % (vol_path, highest_file)
                info = self._qemu_img_info(snapshot_path)
                snapshot_file_fmt = info.file_format

                backing_fmt = ('-F', snapshot_file_fmt)
                self._execute('qemu-img', 'rebase', '-u',
                              '-b', snapshot_file,
                              highest_file_path, *backing_fmt,
                              run_as_root=True)
            self._execute('rm', '-f', higher_file_path, run_as_root=True)

            # Remove snapshot_file from info
            info_path = self._local_path_volume(snapshot['volume']) + '.info'
            snap_info = self._read_info_file(info_path)
            del(snap_info[snapshot['id']])
            snap_info[higher_id] = snapshot_file
            if higher_file == active_file:
                if highest_file is not None:
                    msg = _('Check condition failed: '
                            '%s expected to be None.') % 'highest_file'
                    raise exception.GlusterfsException(msg)
                # Active file has changed
                snap_info['active'] = snapshot_file
            self._write_info_file(info_path, snap_info)

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
        timeout = 600
        while True:
            s = db.snapshot_get(context, snapshot['id'])

            if s['status'] == 'deleting':
                if s['progress'] == '90%':
                    # Nova tasks completed successfully
                    break
                else:
                    msg = _('status of snapshot %s is '
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

    def _get_backing_chain_for_path(self, volume, path):
        """Returns list of dicts containing backing-chain information.

        Includes 'filename', and 'backing-filename' for each
        applicable entry.

        Consider converting this to use --backing-chain and --output=json
        when environment supports qemu-img 1.5.0.

        :param volume: volume reference
        :param path: path to image file at top of chain

        """

        output = []

        info = self._qemu_img_info(path)
        new_info = {}
        new_info['filename'] = os.path.basename(path)
        new_info['backing-filename'] = info.backing_file

        output.append(new_info)

        while new_info['backing-filename']:
            filename = new_info['backing-filename']
            path = os.path.join(self._local_volume_dir(volume), filename)
            info = self._qemu_img_info(path)
            backing_filename = info.backing_file
            new_info = {}
            new_info['filename'] = filename
            new_info['backing-filename'] = backing_filename

            output.append(new_info)

        return output

    def _qemu_img_commit(self, path):
        return self._execute('qemu-img', 'commit', path, run_as_root=True)

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
        info = self._qemu_img_info(path)
        data['format'] = info.file_format
        if data['format'] not in ['raw', 'qcow2']:
            msg = _('%s must be a valid raw or qcow2 image.') % path
            raise exception.InvalidVolume(msg)

        return {
            'driver_volume_type': 'glusterfs',
            'data': data
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        pass

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""

        # If snapshots exist, flatten to a temporary image, and upload it

        active_file = self.get_active_image_from_info(volume)
        active_file_path = '%s/%s' % (self._local_volume_dir(volume),
                                      active_file)
        info = self._qemu_img_info(active_file_path)
        backing_file = info.backing_file
        if backing_file:
            snapshots_exist = True
        else:
            snapshots_exist = False

        root_file_fmt = info.file_format

        temp_path = None

        try:
            if snapshots_exist or (root_file_fmt != 'raw'):
                # Convert due to snapshots
                # or volume data not being stored in raw format
                #  (upload_volume assumes raw format input)
                temp_path = '%s/%s.temp_image.%s' % (
                    self._local_volume_dir(volume),
                    volume['id'],
                    image_meta['id'])

                image_utils.convert_image(active_file_path, temp_path, 'raw')
                upload_path = temp_path
            else:
                upload_path = active_file_path

            image_utils.upload_volume(context,
                                      image_service,
                                      image_meta,
                                      upload_path)
        finally:
            if temp_path is not None:
                self._execute('rm', '-f', temp_path)

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

        info = self._qemu_img_info(volume_path)
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

        LOG.debug(_("creating new volume at %s") % volume_path)

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
                LOG.warning(_('Exception during mounting %s') % (exc,))

        LOG.debug(_('Available shares: %s') % str(self._mounted_shares))

    def _ensure_share_writable(self, path):
        """Ensure that the Cinder user can write to the share.

        If not, raise an exception.

        :param path: path to test
        :raises: GlusterfsException
        :returns: None
        """

        prefix = '.cinder-write-test-' + str(os.getpid()) + '-'

        try:
            tempfile.NamedTemporaryFile(prefix=prefix, dir=path)
        except OSError:
            msg = _('GlusterFS share at %(dir)s is not writable by the '
                    'Cinder volume service. Snapshot operations will not be '
                    'supported.') % {'dir': path}
            raise exception.GlusterfsException(msg)

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

        if volume_size_for * units.GiB > greatest_size:
            raise exception.GlusterfsNoSuitableShareFound(
                volume_size=volume_size_for)
        return greatest_share

    def _get_hash_str(self, base_str):
        """Return a string that represents hash of base_str
        (in a hex format).
        """
        return hashlib.md5(base_str).hexdigest()

    def _get_mount_point_for_share(self, glusterfs_share):
        """Return mount point for share.
        :param glusterfs_share: example 172.18.194.100:/var/glusterfs
        """
        return os.path.join(self.configuration.glusterfs_mount_point_base,
                            self._get_hash_str(glusterfs_share))

    def _get_available_capacity(self, glusterfs_share):
        """Calculate available space on the GlusterFS share.
        :param glusterfs_share: example 172.18.194.100:/var/glusterfs
        """
        mount_point = self._get_mount_point_for_share(glusterfs_share)

        out, _ = self._execute('df', '--portability', '--block-size', '1',
                               mount_point, run_as_root=True)
        out = out.splitlines()[1]

        available = 0

        size = int(out.split()[1])
        if self.configuration.glusterfs_disk_util == 'df':
            available = int(out.split()[3])
        else:
            out, _ = self._execute('du', '-sb', '--apparent-size',
                                   '--exclude', '*snapshot*', mount_point,
                                   run_as_root=True)
            used = int(out.split()[0])
            available = size - used

        return available, size

    def _get_capacity_info(self, glusterfs_share):
        available, size = self._get_available_capacity(glusterfs_share)
        return size, available, size - available

    def _mount_glusterfs(self, glusterfs_share, mount_path, ensure=False):
        """Mount GlusterFS share to mount path."""
        self._execute('mkdir', '-p', mount_path)

        command = ['mount', '-t', 'glusterfs', glusterfs_share,
                   mount_path]
        if self.shares.get(glusterfs_share) is not None:
            command.extend(self.shares[glusterfs_share].split())

        self._do_mount(command, ensure, glusterfs_share)
