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

import os
import stat

from os_brick import exception as brick_exception
from os_brick.remotefs import remotefs as remotefs_brick
from oslo_concurrency import processutils as putils
from oslo_config import cfg
from oslo_log import log as logging

from cinder.backup.drivers import posix
from cinder import exception
from cinder import interface
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
    cfg.IntOpt('backup_mount_attempts',
               min=1,
               default=3,
               help='The number of attempts to mount NFS shares before '
                    'raising an error.'),
]

CONF = cfg.CONF
CONF.register_opts(nfsbackup_service_opts)


@interface.backupdriver
class NFSBackupDriver(posix.PosixBackupDriver):
    """Provides backup, restore and delete using NFS supplied repository."""

    def __init__(self, context):
        self.backup_mount_point_base = CONF.backup_mount_point_base
        self.backup_share = CONF.backup_share
        self.mount_options = CONF.backup_mount_options
        self._execute = putils.execute
        self._root_helper = utils.get_root_helper()
        backup_path = self._init_backup_repo_path()
        LOG.debug("Using NFS backup repository: %s", backup_path)
        super().__init__(context, backup_path=backup_path)

    def check_for_setup_error(self):
        """Raises error if any required configuration flag is missing."""
        required_flags = ['backup_share']
        for flag in required_flags:
            val = getattr(CONF, flag, None)
            if not val:
                raise exception.InvalidConfigurationValue(option=flag,
                                                          value=val)

    def _init_backup_repo_path(self):
        if self.backup_share is None:
            LOG.info("_init_backup_repo_path: "
                     "backup_share is not set in configuration")
            return

        remotefsclient = remotefs_brick.RemoteFsClient(
            'nfs',
            self._root_helper,
            nfs_mount_point_base=self.backup_mount_point_base,
            nfs_mount_options=self.mount_options)

        @utils.retry(
            (brick_exception.BrickException, putils.ProcessExecutionError),
            retries=CONF.backup_mount_attempts)
        def mount():
            remotefsclient.mount(self.backup_share)

        mount()
        # Ensure we can write to this share
        mount_path = remotefsclient.get_mount_point(self.backup_share)

        group_id = os.getegid()
        current_group_id = utils.get_file_gid(mount_path)
        current_mode = utils.get_file_mode(mount_path)

        if group_id != current_group_id:
            cmd = ['chgrp', '-R', group_id, mount_path]
            self._execute(*cmd, root_helper=self._root_helper,
                          run_as_root=True)

        if not (current_mode & stat.S_IWGRP):
            cmd = ['chmod', '-R', 'g+w', mount_path]
            self._execute(*cmd, root_helper=self._root_helper,
                          run_as_root=True)

        return mount_path
