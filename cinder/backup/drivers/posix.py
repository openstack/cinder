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

"""Implementation of a backup service that uses a posix filesystem as the
   backend."""

import errno
import os
import os.path
import stat

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

from cinder.backup import chunkeddriver
from cinder import exception
from cinder import interface

LOG = logging.getLogger(__name__)

SHA_SIZE = 32768
# Multiple of SHA_SIZE, close to a characteristic OS max file system size.
BACKUP_FILE_SIZE = 61035 * 32768

posixbackup_service_opts = [
    cfg.IntOpt('backup_file_size',
               default=BACKUP_FILE_SIZE,
               help='The maximum size in bytes of the files used to hold '
                    'backups. If the volume being backed up exceeds this '
                    'size, then it will be backed up into multiple files.'
                    'backup_file_size must be a multiple of '
                    'backup_sha_block_size_bytes.'),
    cfg.IntOpt('backup_sha_block_size_bytes',
               default=SHA_SIZE,
               help='The size in bytes that changes are tracked '
                    'for incremental backups. backup_file_size has '
                    'to be multiple of backup_sha_block_size_bytes.'),
    cfg.BoolOpt('backup_enable_progress_timer',
                default=True,
                help='Enable or Disable the timer to send the periodic '
                     'progress notifications to Ceilometer when backing '
                     'up the volume to the backend storage. The '
                     'default value is True to enable the timer.'),
    cfg.StrOpt('backup_posix_path',
               default='$state_path/backup',
               help='Path specifying where to store backups.'),
    cfg.StrOpt('backup_container',
               help='Custom directory to use for backups.'),
]

CONF = cfg.CONF
CONF.register_opts(posixbackup_service_opts)


@interface.backupdriver
class PosixBackupDriver(chunkeddriver.ChunkedBackupDriver):
    """Provides backup, restore and delete using a Posix file system."""

    def __init__(self, context, db=None, backup_path=None):
        chunk_size_bytes = CONF.backup_file_size
        sha_block_size_bytes = CONF.backup_sha_block_size_bytes
        backup_default_container = CONF.backup_container
        enable_progress_timer = CONF.backup_enable_progress_timer
        super(PosixBackupDriver, self).__init__(context, chunk_size_bytes,
                                                sha_block_size_bytes,
                                                backup_default_container,
                                                enable_progress_timer,
                                                db)
        self.backup_path = backup_path
        if not backup_path:
            self.backup_path = CONF.backup_posix_path
        if not self.backup_path:
            raise exception.ConfigNotFound(path='backup_path')
        LOG.debug("Using backup repository: %s", self.backup_path)

    @staticmethod
    def get_driver_options():
        return posixbackup_service_opts

    def update_container_name(self, backup, container):
        if container is not None:
            return container
        id = backup['id']
        return os.path.join(id[0:2], id[2:4], id)

    def put_container(self, container):
        path = os.path.join(self.backup_path, container)
        if not os.path.exists(path):
            os.makedirs(path)
            permissions = (
                stat.S_IRUSR |
                stat.S_IWUSR |
                stat.S_IXUSR |
                stat.S_IRGRP |
                stat.S_IWGRP |
                stat.S_IXGRP)
            os.chmod(path, permissions)

    def get_container_entries(self, container, prefix):
        path = os.path.join(self.backup_path, container)
        return [i for i in os.listdir(path) if i.startswith(prefix)]

    def get_object_writer(self, container, object_name, extra_metadata=None):
        path = os.path.join(self.backup_path, container, object_name)
        f = open(path, 'wb')
        permissions = (
            stat.S_IRUSR |
            stat.S_IWUSR |
            stat.S_IRGRP |
            stat.S_IWGRP)
        os.chmod(path, permissions)
        return f

    def get_object_reader(self, container, object_name, extra_metadata=None):
        path = os.path.join(self.backup_path, container, object_name)
        return open(path, 'rb')

    def delete_object(self, container, object_name):
        # TODO(tbarron):  clean up the container path if it is empty
        path = os.path.join(self.backup_path, container, object_name)
        try:
            os.remove(path)
        except OSError as e:
            # Ignore exception if path does not exist.
            if e.errno != errno.ENOENT:
                raise

    def _generate_object_name_prefix(self, backup):
        timestamp = timeutils.utcnow().strftime("%Y%m%d%H%M%S")
        prefix = 'volume_%s_%s_backup_%s' % (backup.volume_id, timestamp,
                                             backup.id)
        LOG.debug('_generate_object_name_prefix: %s', prefix)
        return prefix

    def get_extra_metadata(self, backup, volume):
        return None


def get_backup_driver(context):
    return PosixBackupDriver(context)
