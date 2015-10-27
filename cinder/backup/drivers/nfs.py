# Copyright (C) 2015 Tom Barron <tpb@dyncloud.net>
# Copyright (C) 2015 Kevin Fox <kevin@efox.cc>
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

"""Implementation of a backup service that uses NFS storage as the backend."""

from os_brick.remotefs import remotefs as remotefs_brick
from oslo_config import cfg
from oslo_log import log as logging

from cinder.backup.drivers import posix
from cinder import exception
from cinder.i18n import _
from cinder import utils

LOG = logging.getLogger(__name__)


nfsbackup_service_opts = [
    cfg.StrOpt('backup_mount_point_base',
               default='$state_path/backup_mount',
               help='Base dir containing mount point for NFS share.'),
    cfg.StrOpt('backup_share',
               help='NFS share in hostname:path, ipv4addr:path, '
                    'or "[ipv6addr]:path" format.'),
    cfg.StrOpt('backup_mount_options',
               help=('Mount options passed to the NFS client. See NFS '
                     'man page for details.')),
]

CONF = cfg.CONF
CONF.register_opts(nfsbackup_service_opts)


class NFSBackupDriver(posix.PosixBackupDriver):
    """Provides backup, restore and delete using NFS supplied repository."""

    def __init__(self, context, db_driver=None):
        self._check_configuration()
        self.backup_mount_point_base = CONF.backup_mount_point_base
        self.backup_share = CONF.backup_share
        self.mount_options = CONF.backup_mount_options or {}
        backup_path = self._init_backup_repo_path()
        LOG.debug("Using NFS backup repository: %s", backup_path)
        super(NFSBackupDriver, self).__init__(context,
                                              backup_path=backup_path)

    @staticmethod
    def _check_configuration():
        """Raises error if any required configuration flag is missing."""
        required_flags = ['backup_share']
        for flag in required_flags:
            if not getattr(CONF, flag, None):
                raise exception.ConfigNotFound(_(
                    'Required flag %s is not set') % flag)

    def _init_backup_repo_path(self):
        remotefsclient = remotefs_brick.RemoteFsClient(
            'nfs',
            utils.get_root_helper(),
            nfs_mount_point_base=self.backup_mount_point_base,
            nfs_mount_options=self.mount_options)
        remotefsclient.mount(self.backup_share)
        return remotefsclient.get_mount_point(self.backup_share)


def get_backup_driver(context):
    return NFSBackupDriver(context)
