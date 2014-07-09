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
        self._mounted_shares = []

        self._load_shares_config(getattr(self.configuration,
                                         self.driver_prefix +
                                         '_shares_config'))

        for share in self.shares.keys():
            try:
                self._ensure_share_mounted(share)
                self._mounted_shares.append(share)
            except Exception as exc:
                LOG.warning(_('Exception during mounting %s') % (exc,))

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

        self._execute('rm', '-f', mounted_path, run_as_root=True)

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
        raise NotImplementedError()

    def _local_path_volume(self, volume):
        path_to_disk = '%s/%s' % (
            self._local_volume_dir(volume),
            volume['name'])

        return path_to_disk

    def _local_path_volume_info(self, volume):
        return '%s%s' % (self._local_path_volume(volume), '.info')

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

    def _qemu_img_commit(self, path):
        return self._execute('qemu-img', 'commit', path, run_as_root=True)

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
