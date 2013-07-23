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
from cinder.openstack.common import log as logging
from cinder.volume.drivers import nfs

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('glusterfs_shares_config',
               default='/etc/cinder/glusterfs_shares',
               help='File with the list of available gluster shares'),
    cfg.StrOpt('glusterfs_mount_point_base',
               default='$state_path/mnt',
               help='Base dir containing mount points for gluster shares'),
    cfg.StrOpt('glusterfs_disk_util',
               default='df',
               help='Use du or df for free space calculation'),
    cfg.BoolOpt('glusterfs_sparsed_volumes',
                default=True,
                help=('Create volumes as sparsed files which take no space.'
                      'If set to False volume is created as regular file.'
                      'In such case volume creation takes a lot of time.'))]
VERSION = '1.0'

CONF = cfg.CONF
CONF.register_opts(volume_opts)


class GlusterfsDriver(nfs.RemoteFsDriver):
    """Gluster based cinder driver. Creates file on Gluster share for using it
    as block device on hypervisor.
    """

    driver_volume_type = 'glusterfs'
    driver_prefix = 'glusterfs'
    volume_backend_name = 'GlusterFS'
    version = VERSION

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

    def check_for_setup_error(self):
        """Just to override parent behavior."""
        pass

    def _ensure_share_mounted(self, glusterfs_share):
        """Mount GlusterFS share.
        :param glusterfs_share: string
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
            capacity = self._get_available_capacity(glusterfs_share)[0]
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
