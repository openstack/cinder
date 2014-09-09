# Copyright (c) 2012 NetApp, Inc.
# Copyright (c) 2014 Red Hat, Inc.
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

import hashlib
import json
import os
import re
import tempfile

from oslo.config import cfg

from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils
from cinder.openstack.common import units
from cinder.volume import driver

LOG = logging.getLogger(__name__)

nas_opts = [
    cfg.StrOpt('nas_ip',
               default='',
               help='IP address or Hostname of NAS system.'),
    cfg.StrOpt('nas_login',
               default='admin',
               help='User name to connect to NAS system.'),
    cfg.StrOpt('nas_password',
               default='',
               help='Password to connect to NAS system.',
               secret=True),
    cfg.IntOpt('nas_ssh_port',
               default=22,
               help='SSH port to use to connect to NAS system.'),
    cfg.StrOpt('nas_private_key',
               default='',
               help='Filename of private key to use for SSH authentication.'),
]

CONF = cfg.CONF
CONF.register_opts(nas_opts)


class RemoteFSDriver(driver.VolumeDriver):
    """Common base for drivers that work like NFS."""

    driver_volume_type = None
    driver_prefix = None
    volume_backend_name = None
    SHARE_FORMAT_REGEX = r'.+:/.+'

    def __init__(self, *args, **kwargs):
        super(RemoteFSDriver, self).__init__(*args, **kwargs)
        self.shares = {}
        self._mounted_shares = []

    def check_for_setup_error(self):
        """Just to override parent behavior."""
        pass

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        :param volume: volume reference
        :param connector: connector reference
        """
        data = {'export': volume['provider_location'],
                'name': volume['name']}
        if volume['provider_location'] in self.shares:
            data['options'] = self.shares[volume['provider_location']]
        return {
            'driver_volume_type': self.driver_volume_type,
            'data': data,
            'mount_point_base': self._get_mount_point_base()
        }

    def _get_mount_point_base(self):
        """Returns the mount point base for the remote fs.

           This method facilitates returning mount point base
           for the specific remote fs. Override this method
           in the respective driver to return the entry to be
           used while attach/detach using brick in cinder.
           If not overridden then it returns None without
           raising exception to continue working for cases
           when not used with brick.
        """
        LOG.debug("Driver specific implementation needs to return"
                  " mount_point_base.")
        return None

    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume reference
        """
        self._ensure_shares_mounted()

        volume['provider_location'] = self._find_share(volume['size'])

        LOG.info(_('casted to %s') % volume['provider_location'])

        self._do_create_volume(volume)

        return {'provider_location': volume['provider_location']}

    def _do_create_volume(self, volume):
        """Create a volume on given remote share.

        :param volume: volume reference
        """
        volume_path = self.local_path(volume)
        volume_size = volume['size']

        if getattr(self.configuration,
                   self.driver_prefix + '_sparsed_volumes'):
            self._create_sparsed_file(volume_path, volume_size)
        else:
            self._create_regular_file(volume_path, volume_size)

        self._set_rw_permissions_for_all(volume_path)

    def _ensure_shares_mounted(self):
        """Look for remote shares in the flags and tries to mount them
        locally.
        """
        mounted_shares = []

        self._load_shares_config(getattr(self.configuration,
                                         self.driver_prefix +
                                         '_shares_config'))

        for share in self.shares.keys():
            try:
                self._ensure_share_mounted(share)
                mounted_shares.append(share)
            except Exception as exc:
                LOG.error(_('Exception during mounting %s') % (exc,))

        self._mounted_shares = mounted_shares

        LOG.debug('Available shares %s' % self._mounted_shares)

    def create_cloned_volume(self, volume, src_vref):
        raise NotImplementedError()

    def delete_volume(self, volume):
        """Deletes a logical volume.

        :param volume: volume reference
        """
        if not volume['provider_location']:
            LOG.warn(_('Volume %s does not have provider_location specified, '
                     'skipping'), volume['name'])
            return

        self._ensure_share_mounted(volume['provider_location'])

        mounted_path = self.local_path(volume)

        self._delete(mounted_path)

    def ensure_export(self, ctx, volume):
        """Synchronously recreates an export for a logical volume."""
        self._ensure_share_mounted(volume['provider_location'])

    def create_export(self, ctx, volume):
        """Exports the volume. Can optionally return a Dictionary of changes
        to the volume object to be persisted.
        """
        pass

    def remove_export(self, ctx, volume):
        """Removes an export for a logical volume."""
        pass

    def delete_snapshot(self, snapshot):
        """Do nothing for this driver, but allow manager to handle deletion
           of snapshot in error state.
        """
        pass

    def _delete(self, path):
        # Note(lpetrut): this method is needed in order to provide
        # interoperability with Windows as it will be overridden.
        self._execute('rm', '-f', path, run_as_root=True)

    def _create_sparsed_file(self, path, size):
        """Creates file with 0 disk usage."""
        self._execute('truncate', '-s', '%sG' % size,
                      path, run_as_root=True)

    def _create_regular_file(self, path, size):
        """Creates regular file of given size. Takes a lot of time for large
        files.
        """

        block_size_mb = 1
        block_count = size * units.Gi / (block_size_mb * units.Mi)

        self._execute('dd', 'if=/dev/zero', 'of=%s' % path,
                      'bs=%dM' % block_size_mb,
                      'count=%d' % block_count,
                      run_as_root=True)

    def _create_qcow2_file(self, path, size_gb):
        """Creates a QCOW2 file of a given size."""

        self._execute('qemu-img', 'create', '-f', 'qcow2',
                      '-o', 'preallocation=metadata',
                      path, str(size_gb * units.Gi),
                      run_as_root=True)

    def _set_rw_permissions_for_all(self, path):
        """Sets 666 permissions for the path."""
        self._execute('chmod', 'ugo+rw', path, run_as_root=True)

    def _set_rw_permissions_for_owner(self, path):
        """Sets read-write permissions to the owner for the path."""
        self._execute('chmod', 'u+rw', path, run_as_root=True)

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume
        :param volume: volume reference
        """
        remotefs_share = volume['provider_location']
        return os.path.join(self._get_mount_point_for_share(remotefs_share),
                            volume['name'])

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 self.local_path(volume),
                                 self.configuration.volume_dd_blocksize,
                                 size=volume['size'])

        # NOTE (leseb): Set the virtual size of the image
        # the raw conversion overwrote the destination file
        # (which had the correct size)
        # with the fetched glance image size,
        # thus the initial 'size' parameter is not honored
        # this sets the size to the one asked in the first place by the user
        # and then verify the final virtual size
        image_utils.resize_image(self.local_path(volume), volume['size'])

        data = image_utils.qemu_img_info(self.local_path(volume))
        virt_size = data.virtual_size / units.Gi
        if virt_size != volume['size']:
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=(_("Expected volume size was %d") % volume['size'])
                + (_(" but size is now %d") % virt_size))

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        image_utils.upload_volume(context,
                                  image_service,
                                  image_meta,
                                  self.local_path(volume))

    def _read_config_file(self, config_file):
        # Returns list of lines in file
        with open(config_file) as f:
            return f.readlines()

    def _load_shares_config(self, share_file):
        self.shares = {}

        for share in self._read_config_file(share_file):
            # A configuration line may be either:
            #  host:/vol_name
            # or
            #  host:/vol_name -o options=123,rw --other
            if not share.strip():
                # Skip blank or whitespace-only lines
                continue
            if share.startswith('#'):
                continue

            share_info = share.split(' ', 1)
            # results in share_info =
            #  [ 'address:/vol', '-o options=123,rw --other' ]

            share_address = share_info[0].strip().decode('unicode_escape')
            share_opts = share_info[1].strip() if len(share_info) > 1 else None

            if not re.match(self.SHARE_FORMAT_REGEX, share_address):
                LOG.warn(_("Share %s ignored due to invalid format.  Must be "
                           "of form address:/export.") % share_address)
                continue

            self.shares[share_address] = share_opts

        LOG.debug("shares loaded: %s", self.shares)

    def _get_mount_point_for_share(self, path):
        raise NotImplementedError()

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        pass

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, update the stats first.
        """
        if refresh or not self._stats:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.volume_backend_name
        data['vendor_name'] = 'Open Source'
        data['driver_version'] = self.get_version()
        data['storage_protocol'] = self.driver_volume_type

        self._ensure_shares_mounted()

        global_capacity = 0
        global_free = 0
        for share in self._mounted_shares:
            capacity, free, used = self._get_capacity_info(share)
            global_capacity += capacity
            global_free += free

        data['total_capacity_gb'] = global_capacity / float(units.Gi)
        data['free_capacity_gb'] = global_free / float(units.Gi)
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        self._stats = data

    def _do_mount(self, cmd, ensure, share):
        """Finalize mount command.

        :param cmd: command to do the actual mount
        :param ensure: boolean to allow remounting a share with a warning
        :param share: description of the share for error reporting
        """
        try:
            self._execute(*cmd, run_as_root=True)
        except putils.ProcessExecutionError as exc:
            if ensure and 'already mounted' in exc.stderr:
                LOG.warn(_("%s is already mounted"), share)
            else:
                raise

    def _get_capacity_info(self, share):
        raise NotImplementedError()

    def _find_share(self, volume_size_in_gib):
        raise NotImplementedError()

    def _ensure_share_mounted(self, share):
        raise NotImplementedError()


class RemoteFSSnapDriver(RemoteFSDriver):
    """Base class for remotefs drivers implementing qcow2 snapshots.

       Driver must implement:
         _local_volume_dir(self, volume)
    """

    def __init__(self, *args, **kwargs):
        self._remotefsclient = None
        self.base = None
        super(RemoteFSSnapDriver, self).__init__(*args, **kwargs)

    def _local_volume_dir(self, volume):
        share = volume['provider_location']
        local_dir = self._get_mount_point_for_share(share)
        return local_dir

    def _local_path_volume(self, volume):
        path_to_disk = os.path.join(
            self._local_volume_dir(volume),
            volume['name'])

        return path_to_disk

    def _get_new_snap_path(self, snapshot):
        vol_path = self.local_path(snapshot['volume'])
        snap_path = '%s.%s' % (vol_path, snapshot['id'])
        return snap_path

    def _local_path_volume_info(self, volume):
        return '%s%s' % (self.local_path(volume), '.info')

    def _read_file(self, filename):
        """This method is to make it easier to stub out code for testing.

        Returns a string representing the contents of the file.
        """

        with open(filename, 'r') as f:
            return f.read()

    def _write_info_file(self, info_path, snap_info):
        if 'active' not in snap_info.keys():
            msg = _("'active' must be present when writing snap_info.")
            raise exception.RemoteFSException(msg)

        with open(info_path, 'w') as f:
            json.dump(snap_info, f, indent=1, sort_keys=True)

    def _qemu_img_info_base(self, path, volume_name, basedir):
        """Sanitize image_utils' qemu_img_info.

        This code expects to deal only with relative filenames.
        """

        info = image_utils.qemu_img_info(path)
        if info.image:
            info.image = os.path.basename(info.image)
        if info.backing_file:
            backing_file_template = \
                "(%(basedir)s/[0-9a-f]+/)?%" \
                "(volname)s(.(tmp-snap-)?[0-9a-f-]+)?$" % {
                    'basedir': basedir,
                    'volname': volume_name
                }
            if not re.match(backing_file_template, info.backing_file):
                msg = _("File %(path)s has invalid backing file "
                        "%(bfile)s, aborting.") % {'path': path,
                                                   'bfile': info.backing_file}
                raise exception.RemoteFSException(msg)

            info.backing_file = os.path.basename(info.backing_file)

        return info

    def _qemu_img_info(self, path, volume_name):
        raise NotImplementedError()

    def _img_commit(self, path):
        self._execute('qemu-img', 'commit', path, run_as_root=True)
        self._delete(path)

    def _rebase_img(self, image, backing_file, volume_format):
        self._execute('qemu-img', 'rebase', '-u', '-b', backing_file, image,
                      '-F', volume_format, run_as_root=True)

    def _read_info_file(self, info_path, empty_if_missing=False):
        """Return dict of snapshot information.

           :param: info_path: path to file
           :param: empty_if_missing: True=return empty dict if no file
        """

        if not os.path.exists(info_path):
            if empty_if_missing is True:
                return {}

        return json.loads(self._read_file(info_path))

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

        info = self._qemu_img_info(path, volume['name'])
        new_info = {}
        new_info['filename'] = os.path.basename(path)
        new_info['backing-filename'] = info.backing_file

        output.append(new_info)

        while new_info['backing-filename']:
            filename = new_info['backing-filename']
            path = os.path.join(self._local_volume_dir(volume), filename)
            info = self._qemu_img_info(path, volume['name'])
            backing_filename = info.backing_file
            new_info = {}
            new_info['filename'] = filename
            new_info['backing-filename'] = backing_filename

            output.append(new_info)

        return output

    def _get_hash_str(self, base_str):
        """Return a string that represents hash of base_str
        (in a hex format).
        """
        return hashlib.md5(base_str).hexdigest()

    def _get_mount_point_for_share(self, share):
        """Return mount point for share.
        :param share: example 172.18.194.100:/var/fs
        """
        return self._remotefsclient.get_mount_point(share)

    def _get_available_capacity(self, share):
        """Calculate available space on the share.
        :param share: example 172.18.194.100:/var/fs
        """
        mount_point = self._get_mount_point_for_share(share)

        out, _ = self._execute('df', '--portability', '--block-size', '1',
                               mount_point, run_as_root=True)
        out = out.splitlines()[1]

        size = int(out.split()[1])
        available = int(out.split()[3])

        return available, size

    def _get_capacity_info(self, remotefs_share):
        available, size = self._get_available_capacity(remotefs_share)
        return size, available, size - available

    def _get_mount_point_base(self):
        return self.base

    def _ensure_share_writable(self, path):
        """Ensure that the Cinder user can write to the share.

        If not, raise an exception.

        :param path: path to test
        :raises: RemoteFSException
        :returns: None
        """

        prefix = '.cinder-write-test-' + str(os.getpid()) + '-'

        try:
            tempfile.NamedTemporaryFile(prefix=prefix, dir=path)
        except OSError:
            msg = _('Share at %(dir)s is not writable by the '
                    'Cinder volume service. Snapshot operations will not be '
                    'supported.') % {'dir': path}
            raise exception.RemoteFSException(msg)

    def _copy_volume_to_image(self, context, volume, image_service,
                              image_meta):
        """Copy the volume to the specified image."""

        # If snapshots exist, flatten to a temporary image, and upload it

        active_file = self.get_active_image_from_info(volume)
        active_file_path = os.path.join(self._local_volume_dir(volume),
                                        active_file)
        info = self._qemu_img_info(active_file_path, volume['name'])
        backing_file = info.backing_file

        root_file_fmt = info.file_format

        tmp_params = {
            'prefix': '%s.temp_image.%s' % (volume['id'], image_meta['id']),
            'suffix': '.img'
        }
        with image_utils.temporary_file(**tmp_params) as temp_path:
            if backing_file or (root_file_fmt != 'raw'):
                # Convert due to snapshots
                # or volume data not being stored in raw format
                #  (upload_volume assumes raw format input)
                image_utils.convert_image(active_file_path, temp_path, 'raw')
                upload_path = temp_path
            else:
                upload_path = active_file_path

            image_utils.upload_volume(context,
                                      image_service,
                                      image_meta,
                                      upload_path)

    def get_active_image_from_info(self, volume):
        """Returns filename of the active image from the info file."""

        info_file = self._local_path_volume_info(volume)

        snap_info = self._read_info_file(info_file, empty_if_missing=True)

        if not snap_info:
            # No info file = no snapshots exist
            vol_path = os.path.basename(self.local_path(volume))
            return vol_path

        return snap_info['active']

    def _create_cloned_volume(self, volume, src_vref):
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
        self._create_snapshot(temp_snapshot)
        try:
            self._copy_volume_from_snapshot(temp_snapshot,
                                            volume_info,
                                            volume['size'])

        finally:
            self._delete_snapshot(temp_snapshot)

        return {'provider_location': src_vref['provider_location']}

    def _delete_stale_snapshot(self, snapshot):
        info_path = self._local_path_volume_info(snapshot['volume'])
        snap_info = self._read_info_file(info_path)

        snapshot_file = snap_info[snapshot['id']]
        active_file = self.get_active_image_from_info(snapshot['volume'])
        snapshot_path = os.path.join(
            self._local_volume_dir(snapshot['volume']), snapshot_file)
        if (snapshot_file == active_file):
            return

        LOG.info(_('Deleting stale snapshot: %s') % snapshot['id'])
        self._delete(snapshot_path)
        del(snap_info[snapshot['id']])
        self._write_info_file(info_path, snap_info)

    def _delete_snapshot(self, snapshot):
        """Delete a snapshot.

        If volume status is 'available', delete snapshot here in Cinder
        using qemu-img.

        If volume status is 'in-use', calculate what qcow2 files need to
        merge, and call to Nova to perform this operation.

        :raises: InvalidVolume if status not acceptable
        :raises: RemotefsException(msg) if operation fails
        :returns: None

        """

        LOG.debug('Deleting snapshot %s:' % snapshot['id'])

        volume_status = snapshot['volume']['status']
        if volume_status not in ['available', 'in-use']:
            msg = _('Volume status must be "available" or "in-use".')
            raise exception.InvalidVolume(msg)

        self._ensure_share_writable(
            self._local_volume_dir(snapshot['volume']))

        # Determine the true snapshot file for this snapshot
        # based on the .info file
        info_path = self._local_path_volume_info(snapshot['volume'])
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
        LOG.debug('snapshot_file for this snap is: %s' % snapshot_file)
        snapshot_path = os.path.join(
            self._local_volume_dir(snapshot['volume']),
            snapshot_file)

        snapshot_path_img_info = self._qemu_img_info(
            snapshot_path,
            snapshot['volume']['name'])

        vol_path = self._local_volume_dir(snapshot['volume'])

        # Find what file has this as its backing file
        active_file = self.get_active_image_from_info(snapshot['volume'])
        active_file_path = os.path.join(vol_path, active_file)

        if volume_status == 'in-use':
            # Online delete
            context = snapshot['context']

            base_file = snapshot_path_img_info.backing_file
            if base_file is None:
                # There should always be at least the original volume
                # file as base.
                msg = _('No backing file found for %s, allowing snapshot '
                        'to be deleted.') % snapshot_path
                LOG.warn(msg)

                # Snapshot may be stale, so just delete it and update ther
                # info file instead of blocking
                return self._delete_stale_snapshot(snapshot)

            base_path = os.path.join(
                self._local_volume_dir(snapshot['volume']), base_file)
            base_file_img_info = self._qemu_img_info(
                base_path,
                snapshot['volume']['name'])
            new_base_file = base_file_img_info.backing_file

            base_id = None
            for key, value in snap_info.iteritems():
                if value == base_file and key != 'active':
                    base_id = key
                    break
            if base_id is None:
                # This means we are deleting the oldest snapshot
                msg = 'No %(base_id)s found for %(file)s' % {
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

            self._img_commit(snapshot_path)

            # Remove snapshot_file from info
            del(snap_info[snapshot['id']])
            # Active file has changed
            snap_info['active'] = base_file
            self._write_info_file(info_path, snap_info)
        else:
            #      T0        |      T1        |     T2         |       T3
            #     base       |  snapshot_file |  higher_file   |  highest_file
            # (guaranteed to | (being deleted)|(guaranteed to  |   (may exist,
            #   exist, not   |                | exist, being   |    needs ptr
            #   used here)   |                | committed down)|  update if so)

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
                raise exception.RemoteFSException(msg)

            higher_id = next((i for i in snap_info
                              if snap_info[i] == higher_file
                              and i != 'active'),
                             None)
            if higher_id is None:
                msg = _('No snap found with %s as backing file.') %\
                    higher_file
                raise exception.RemoteFSException(msg)

            # Is there a file depending on higher_file?
            highest_file = next((os.path.basename(f['filename'])
                                for f in backing_chain
                                if f.get('backing-filename', '') ==
                                higher_file),
                                None)
            if highest_file is None:
                msg = 'No file depends on %s.' % higher_file
                LOG.debug(msg)

            # Committing higher_file into snapshot_file
            # And update pointer in highest_file
            higher_file_path = os.path.join(vol_path, higher_file)
            self._img_commit(higher_file_path)
            if highest_file is not None:
                highest_file_path = os.path.join(vol_path, highest_file)
                snapshot_file_fmt = snapshot_path_img_info.file_format
                self._rebase_img(highest_file_path, snapshot_file,
                                 snapshot_file_fmt)

            # Remove snapshot_file from info
            del(snap_info[snapshot['id']])
            snap_info[higher_id] = snapshot_file
            if higher_file == active_file:
                if highest_file is not None:
                    msg = _('Check condition failed: '
                            '%s expected to be None.') % 'highest_file'
                    raise exception.RemoteFSException(msg)
                # Active file has changed
                snap_info['active'] = snapshot_file

            self._write_info_file(info_path, snap_info)

    def _create_volume_from_snapshot(self, volume, snapshot):
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
                                        volume['size'])

        return {'provider_location': volume['provider_location']}

    def _copy_volume_from_snapshot(self, snapshot, volume, volume_size):
        raise NotImplementedError()

    def _do_create_snapshot(self, snapshot, backing_filename,
                            new_snap_path):
        """Create a QCOW2 file backed by another file.

        :param snapshot: snapshot reference
        :param backing_filename: filename of file that will back the
            new qcow2 file
        :param new_snap_path: filename of new qcow2 file
        """

        backing_path_full_path = os.path.join(
            self._local_volume_dir(snapshot['volume']),
            backing_filename)

        command = ['qemu-img', 'create', '-f', 'qcow2', '-o',
                   'backing_file=%s' % backing_path_full_path, new_snap_path]
        self._execute(*command, run_as_root=True)

        info = self._qemu_img_info(backing_path_full_path,
                                   snapshot['volume']['name'])
        backing_fmt = info.file_format

        command = ['qemu-img', 'rebase', '-u',
                   '-b', backing_filename,
                   '-F', backing_fmt,
                   new_snap_path]
        self._execute(*command, run_as_root=True)

        self._set_rw_permissions_for_all(new_snap_path)

    def _create_snapshot(self, snapshot):
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

        info_path = self._local_path_volume_info(snapshot['volume'])
        snap_info = self._read_info_file(info_path, empty_if_missing=True)
        backing_filename = self.get_active_image_from_info(
            snapshot['volume'])
        new_snap_path = self._get_new_snap_path(snapshot)

        if status == 'in-use':
            self._create_snapshot_online(snapshot,
                                         backing_filename,
                                         new_snap_path)
        else:
            self._do_create_snapshot(snapshot,
                                     backing_filename,
                                     new_snap_path)

        snap_info['active'] = os.path.basename(new_snap_path)
        snap_info[snapshot['id']] = os.path.basename(new_snap_path)
        self._write_info_file(info_path, snap_info)

    def _create_snapshot_online(self, snapshot, backing_filename,
                                new_snap_path):
        raise NotImplementedError()

    def _delete_snapshot_online(self, context, snapshot, info):
        raise NotImplementedError()
