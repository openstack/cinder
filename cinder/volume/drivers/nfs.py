# Copyright (c) 2012 NetApp, Inc.
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
import re

from oslo.config import cfg

from cinder.brick.remotefs import remotefs
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils
from cinder import units
from cinder import utils
from cinder.volume import driver

VERSION = '1.1.0'

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('nfs_shares_config',
               default='/etc/cinder/nfs_shares',
               help='File with the list of available nfs shares'),
    cfg.BoolOpt('nfs_sparsed_volumes',
                default=True,
                help=('Create volumes as sparsed files which take no space.'
                      'If set to False volume is created as regular file.'
                      'In such case volume creation takes a lot of time.')),
    cfg.FloatOpt('nfs_used_ratio',
                 default=0.95,
                 help=('Percent of ACTUAL usage of the underlying volume '
                       'before no new volumes can be allocated to the volume '
                       'destination.')),
    cfg.FloatOpt('nfs_oversub_ratio',
                 default=1.0,
                 help=('This will compare the allocated to available space on '
                       'the volume destination.  If the ratio exceeds this '
                       'number, the destination will no longer be valid.')),
    cfg.StrOpt('nfs_mount_point_base',
               default='$state_path/mnt',
               help=('Base dir containing mount points for nfs shares.')),
    cfg.StrOpt('nfs_mount_options',
               default=None,
               help=('Mount options passed to the nfs client. See section '
                     'of the nfs man page for details.')),
]

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
CONF.register_opts(volume_opts)
CONF.register_opts(nas_opts)


class RemoteFsDriver(driver.VolumeDriver):
    """Common base for drivers that work like NFS."""

    VERSION = "0.0.0"

    def __init__(self, *args, **kwargs):
        super(RemoteFsDriver, self).__init__(*args, **kwargs)
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
        LOG.debug(_("Driver specific implementation needs to return"
                    " mount_point_base."))
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
        block_count = size * units.GiB / (block_size_mb * units.MiB)

        self._execute('dd', 'if=/dev/zero', 'of=%s' % path,
                      'bs=%dM' % block_size_mb,
                      'count=%d' % block_count,
                      run_as_root=True)

    def _create_qcow2_file(self, path, size_gb):
        """Creates a QCOW2 file of a given size."""

        self._execute('qemu-img', 'create', '-f', 'qcow2',
                      '-o', 'preallocation=metadata',
                      path, str(size_gb * units.GiB),
                      run_as_root=True)

    def _set_rw_permissions_for_all(self, path):
        """Sets 666 permissions for the path."""
        self._execute('chmod', 'ugo+rw', path, run_as_root=True)

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume
        :param volume: volume reference
        """
        nfs_share = volume['provider_location']
        return os.path.join(self._get_mount_point_for_share(nfs_share),
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
        virt_size = data.virtual_size / units.GiB
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

            if not re.match(r'.+:/.+', share_address):
                LOG.warn("Share %s ignored due to invalid format.  Must be of "
                         "form address:/export." % share_address)
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

        data['total_capacity_gb'] = global_capacity / float(units.GiB)
        data['free_capacity_gb'] = global_free / float(units.GiB)
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

    def _get_capacity_info(self, nfs_share):
        raise NotImplementedError()

    def _find_share(self, volume_size_in_gib):
        raise NotImplementedError()

    def _ensure_share_mounted(self, nfs_share):
        raise NotImplementedError()


class NfsDriver(RemoteFsDriver):
    """NFS based cinder driver. Creates file on NFS share for using it
    as block device on hypervisor.
    """

    driver_volume_type = 'nfs'
    driver_prefix = 'nfs'
    volume_backend_name = 'Generic_NFS'
    VERSION = VERSION

    def __init__(self, execute=putils.execute, *args, **kwargs):
        self._remotefsclient = None
        super(NfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)
        root_helper = utils.get_root_helper()
        # base bound to instance is used in RemoteFsConnector.
        self.base = getattr(self.configuration,
                            'nfs_mount_point_base',
                            CONF.nfs_mount_point_base)
        opts = getattr(self.configuration,
                       'nfs_mount_options',
                       CONF.nfs_mount_options)
        self._remotefsclient = remotefs.RemoteFsClient(
            'nfs', root_helper, execute=execute,
            nfs_mount_point_base=self.base,
            nfs_mount_options=opts)

    def set_execute(self, execute):
        super(NfsDriver, self).set_execute(execute)
        if self._remotefsclient:
            self._remotefsclient.set_execute(execute)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(NfsDriver, self).do_setup(context)

        config = self.configuration.nfs_shares_config
        if not config:
            msg = (_("There's no NFS config file configured (%s)") %
                   'nfs_shares_config')
            LOG.warn(msg)
            raise exception.NfsException(msg)
        if not os.path.exists(config):
            msg = (_("NFS config file at %(config)s doesn't exist") %
                   {'config': config})
            LOG.warn(msg)
            raise exception.NfsException(msg)
        if not self.configuration.nfs_oversub_ratio > 0:
            msg = _("NFS config 'nfs_oversub_ratio' invalid.  Must be > 0: "
                    "%s") % self.configuration.nfs_oversub_ratio

            LOG.error(msg)
            raise exception.NfsException(msg)

        if ((not self.configuration.nfs_used_ratio > 0) and
                (self.configuration.nfs_used_ratio <= 1)):
            msg = _("NFS config 'nfs_used_ratio' invalid.  Must be > 0 "
                    "and <= 1.0: %s") % self.configuration.nfs_used_ratio
            LOG.error(msg)
            raise exception.NfsException(msg)

        self.shares = {}  # address : options

        # Check if mount.nfs is installed
        try:
            self._execute('mount.nfs', check_exit_code=False, run_as_root=True)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise exception.NfsException('mount.nfs is not installed')
            else:
                raise exc

    def _ensure_share_mounted(self, nfs_share):
        mnt_flags = []
        if self.shares.get(nfs_share) is not None:
            mnt_flags = self.shares[nfs_share].split()
        self._remotefsclient.mount(nfs_share, mnt_flags)

    def _find_share(self, volume_size_in_gib):
        """Choose NFS share among available ones for given volume size.

        For instances with more than one share that meets the criteria, the
        share with the least "allocated" space will be selected.

        :param volume_size_in_gib: int size in GB
        """

        if not self._mounted_shares:
            raise exception.NfsNoSharesMounted()

        target_share = None
        target_share_reserved = 0

        for nfs_share in self._mounted_shares:
            if not self._is_share_eligible(nfs_share, volume_size_in_gib):
                continue
            total_size, total_available, total_allocated = \
                self._get_capacity_info(nfs_share)
            if target_share is not None:
                if target_share_reserved > total_allocated:
                    target_share = nfs_share
                    target_share_reserved = total_allocated
            else:
                target_share = nfs_share
                target_share_reserved = total_allocated

        if target_share is None:
            raise exception.NfsNoSuitableShareFound(
                volume_size=volume_size_in_gib)

        LOG.debug(_('Selected %s as target nfs share.'), target_share)

        return target_share

    def _is_share_eligible(self, nfs_share, volume_size_in_gib):
        """Verifies NFS share is eligible to host volume with given size.

        First validation step: ratio of actual space (used_space / total_space)
        is less than 'nfs_used_ratio'. Second validation step: apparent space
        allocated (differs from actual space used when using sparse files)
        and compares the apparent available
        space (total_available * nfs_oversub_ratio) to ensure enough space is
        available for the new volume.

        :param nfs_share: nfs share
        :param volume_size_in_gib: int size in GB
        """

        used_ratio = self.configuration.nfs_used_ratio
        oversub_ratio = self.configuration.nfs_oversub_ratio
        requested_volume_size = volume_size_in_gib * units.GiB

        total_size, total_available, total_allocated = \
            self._get_capacity_info(nfs_share)
        apparent_size = max(0, total_size * oversub_ratio)
        apparent_available = max(0, apparent_size - total_allocated)
        used = (total_size - total_available) / total_size
        if used > used_ratio:
            # NOTE(morganfainberg): We check the used_ratio first since
            # with oversubscription it is possible to not have the actual
            # available space but be within our oversubscription limit
            # therefore allowing this share to still be selected as a valid
            # target.
            LOG.debug(_('%s is above nfs_used_ratio'), nfs_share)
            return False
        if apparent_available <= requested_volume_size:
            LOG.debug(_('%s is above nfs_oversub_ratio'), nfs_share)
            return False
        if total_allocated / total_size >= oversub_ratio:
            LOG.debug(_('%s reserved space is above nfs_oversub_ratio'),
                      nfs_share)
            return False
        return True

    def _get_mount_point_for_share(self, nfs_share):
        """Needed by parent class."""
        return self._remotefsclient.get_mount_point(nfs_share)

    def _get_capacity_info(self, nfs_share):
        """Calculate available space on the NFS share.

        :param nfs_share: example 172.18.194.100:/var/nfs
        """

        mount_point = self._get_mount_point_for_share(nfs_share)

        df, _ = self._execute('stat', '-f', '-c', '%S %b %a', mount_point,
                              run_as_root=True)
        block_size, blocks_total, blocks_avail = map(float, df.split())
        total_available = block_size * blocks_avail
        total_size = block_size * blocks_total

        du, _ = self._execute('du', '-sb', '--apparent-size', '--exclude',
                              '*snapshot*', mount_point, run_as_root=True)
        total_allocated = float(du.split()[0])
        return total_size, total_available, total_allocated

    def _get_mount_point_base(self):
        return self.base
