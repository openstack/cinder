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
import os

from oslo.config import cfg

from cinder import exception
from cinder import flags
from cinder.openstack.common import log as logging
from cinder.volume.drivers import nfs

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('glusterfs_shares_config',
               default=None,
               help='File with the list of available gluster shares'),
    cfg.StrOpt('glusterfs_mount_point_base',
               default='$state_path/mnt',
               help='Base dir where gluster expected to be mounted'),
    cfg.StrOpt('glusterfs_disk_util',
               default='df',
               help='Use du or df for free space calculation'),
    cfg.BoolOpt('glusterfs_sparsed_volumes',
                default=True,
                help=('Create volumes as sparsed files which take no space.'
                      'If set to False volume is created as regular file.'
                      'In such case volume creation takes a lot of time.'))]

FLAGS = flags.FLAGS
FLAGS.register_opts(volume_opts)


class GlusterfsDriver(nfs.RemoteFsDriver):
    """Gluster based cinder driver. Creates file on Gluster share for using it
    as block device on hypervisor."""

    def __init__(self, *args, **kwargs):
        super(GlusterfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(GlusterfsDriver, self).do_setup(context)

        config = self.configuration.glusterfs_shares_config
        if not config:
            msg = (_("There's no Gluster config file configured (%s)") %
                   'glusterfs_shares_config')
            LOG.warn(msg)
            raise exception.GlusterfsException(msg)
        if not os.path.exists(config):
            msg = (_("Gluster config file at %(config)s doesn't exist") %
                   locals())
            LOG.warn(msg)
            raise exception.GlusterfsException(msg)

        try:
            self._execute('mount.glusterfs', check_exit_code=False)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise exception.GlusterfsException(
                    _('mount.glusterfs is not installed'))
            else:
                raise

    def check_for_setup_error(self):
        """Just to override parent behavior."""
        pass

    def create_cloned_volume(self, volume, src_vref):
        raise NotImplementedError()

    def create_volume(self, volume):
        """Creates a volume."""

        self._ensure_shares_mounted()

        volume['provider_location'] = self._find_share(volume['size'])

        LOG.info(_('casted to %s') % volume['provider_location'])

        self._do_create_volume(volume)

        return {'provider_location': volume['provider_location']}

    def delete_volume(self, volume):
        """Deletes a logical volume."""

        if not volume['provider_location']:
            LOG.warn(_('Volume %s does not have provider_location specified, '
                     'skipping'), volume['name'])
            return

        self._ensure_share_mounted(volume['provider_location'])

        mounted_path = self.local_path(volume)

        if not self._path_exists(mounted_path):
            volume = volume['name']

            LOG.warn(_('Trying to delete non-existing volume %(volume)s at '
                     'path %(mounted_path)s') % locals())
            return

        self._execute('rm', '-f', mounted_path, run_as_root=True)

    def ensure_export(self, ctx, volume):
        """Synchronously recreates an export for a logical volume."""
        self._ensure_share_mounted(volume['provider_location'])

    def create_export(self, ctx, volume):
        """Exports the volume. Can optionally return a Dictionary of changes
        to the volume object to be persisted."""
        pass

    def remove_export(self, ctx, volume):
        """Removes an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        data = {'export': volume['provider_location'],
                'name': volume['name']}
        return {
            'driver_volume_type': 'glusterfs',
            'data': data
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        pass

    def _do_create_volume(self, volume):
        """Create a volume on given glusterfs_share.
        :param volume: volume reference
        """
        volume_path = self.local_path(volume)
        volume_size = volume['size']

        if self.configuration.glusterfs_sparsed_volumes:
            self._create_sparsed_file(volume_path, volume_size)
        else:
            self._create_regular_file(volume_path, volume_size)

        self._set_rw_permissions_for_all(volume_path)

    def _ensure_shares_mounted(self):
        """Look for GlusterFS shares in the flags and try to mount them
           locally."""
        self._mounted_shares = []

        for share in self._load_shares_config():
            try:
                self._ensure_share_mounted(share)
                self._mounted_shares.append(share)
            except Exception, exc:
                LOG.warning(_('Exception during mounting %s') % (exc,))

        LOG.debug('Available shares %s' % str(self._mounted_shares))

    def _load_shares_config(self):
        return [share.strip() for share
                in open(self.configuration.glusterfs_shares_config)
                if share and not share.startswith('#')]

    def _ensure_share_mounted(self, glusterfs_share):
        """Mount GlusterFS share.
        :param glusterfs_share:
        """
        mount_path = self._get_mount_point_for_share(glusterfs_share)
        self._mount_glusterfs(glusterfs_share, mount_path, ensure=True)

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
            capacity = self._get_available_capacity(glusterfs_share)
            if capacity > greatest_size:
                greatest_share = glusterfs_share
                greatest_size = capacity

        if volume_size_for * 1024 * 1024 * 1024 > greatest_size:
            raise exception.GlusterfsNoSuitableShareFound(
                volume_size=volume_size_for)
        return greatest_share

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

        if self.configuration.glusterfs_disk_util == 'df':
            available = int(out.split()[3])
        else:
            size = int(out.split()[1])
            out, _ = self._execute('du', '-sb', '--apparent-size',
                                   '--exclude', '*snapshot*', mount_point,
                                   run_as_root=True)
            used = int(out.split()[0])
            available = size - used

        return available

    def _mount_glusterfs(self, glusterfs_share, mount_path, ensure=False):
        """Mount GlusterFS share to mount path."""
        if not self._path_exists(mount_path):
            self._execute('mkdir', '-p', mount_path)

        try:
            self._execute('mount', '-t', 'glusterfs', glusterfs_share,
                          mount_path, run_as_root=True)
        except exception.ProcessExecutionError as exc:
            if ensure and 'already mounted' in exc.stderr:
                LOG.warn(_("%s is already mounted"), glusterfs_share)
            else:
                raise
