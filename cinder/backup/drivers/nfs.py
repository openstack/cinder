# Copyright (C) 2015 Tom Barron <tpb@dyncloud.net>
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
import os.path

from oslo_config import cfg
from oslo_log import log as logging

from cinder.backup import chunkeddriver
from cinder.brick.remotefs import remotefs as remotefs_brick
from cinder import exception
from cinder.i18n import _
from cinder import utils

LOG = logging.getLogger(__name__)


SHA_SIZE = 32768
# Multiple of SHA_SIZE, close to a characteristic OS max file system size.
BACKUP_FILE_SIZE = 61035 * 32768

nfsbackup_service_opts = [
    cfg.IntOpt('backup_file_size',
               default=BACKUP_FILE_SIZE,
               help='The maximum size in bytes of the files used to hold '
                    'backups. If the volume being backed up exceeds this '
                    'size, then it will be backed up into multiple files. '
                    'backup_file_size must be a multiple of '
                    'backup_sha_block_size_bytes.'),
    cfg.IntOpt('backup_sha_block_size_bytes',
               default=SHA_SIZE,
               help='The size in bytes that changes are tracked '
                    'for incremental backups. backup_file_size '
                    'has to be multiple of backup_sha_block_size_bytes.'),
    cfg.BoolOpt('backup_enable_progress_timer',
                default=True,
                help='Enable or Disable the timer to send the periodic '
                     'progress notifications to Ceilometer when backing '
                     'up the volume to the backend storage. The '
                     'default value is True to enable the timer.'),
    cfg.StrOpt('backup_mount_point_base',
               default='$state_path/backup_mount',
               help='Base dir containing mount point for NFS share.'),
    cfg.StrOpt('backup_share',
               default=None,
               help='NFS share in fqdn:path, ipv4addr:path, '
                    'or "[ipv6addr]:path" format.'),
    cfg.StrOpt('backup_mount_options',
               default=None,
               help=('Mount options passed to the NFS client. See NFS '
                     'man page for details.')),
    cfg.StrOpt('backup_container',
               help='Custom container to use for backups.'),
]

CONF = cfg.CONF
CONF.register_opts(nfsbackup_service_opts)


class NFSBackupDriver(chunkeddriver.ChunkedBackupDriver):
    """Provides backup, restore and delete using NFS supplied repository."""

    def __init__(self, context, db_driver=None):
        self._check_configuration()
        chunk_size_bytes = CONF.backup_file_size
        sha_block_size_bytes = CONF.backup_sha_block_size_bytes
        backup_default_container = CONF.backup_container
        enable_progress_timer = CONF.backup_enable_progress_timer
        super(NFSBackupDriver, self).__init__(context, chunk_size_bytes,
                                              sha_block_size_bytes,
                                              backup_default_container,
                                              enable_progress_timer,
                                              db_driver)
        self.backup_mount_point_base = CONF.backup_mount_point_base
        self.backup_share = CONF.backup_share
        self.mount_options = CONF.backup_mount_options or {}
        self.backup_path = self._init_backup_repo_path()
        LOG.debug("Using NFS backup repository: %s", self.backup_path)

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

    def update_container_name(self, backup, container):
        if container is not None:
            return container
        id = backup['id']
        return os.path.join(id[0:2], id[2:4], id)

    def put_container(self, container):
        path = os.path.join(self.backup_path, container)
        if not os.path.exists(path):
            os.makedirs(path)
            os.chmod(path, 0o770)

    def get_container_entries(self, container, prefix):
        path = os.path.join(self.backup_path, container)
        return [i for i in os.listdir(path) if i.startswith(prefix)]

    def get_object_writer(self, container, object_name, extra_metadata=None):
        path = os.path.join(self.backup_path, container, object_name)
        file = open(path, 'w')
        os.chmod(path, 0o660)
        return file

    def get_object_reader(self, container, object_name, extra_metadata=None):
        path = os.path.join(self.backup_path, container, object_name)
        return open(path, 'r')

    def delete_object(self, container, object_name):
        # TODO(tbarron):  clean up the container path if it is empty
        path = os.path.join(self.backup_path, container, object_name)
        os.remove(path)

    def _generate_object_name_prefix(self, backup):
        return 'backup'

    def get_extra_metadata(self, backup, volume):
        return None


def get_backup_driver(context):
    return NFSBackupDriver(context)
