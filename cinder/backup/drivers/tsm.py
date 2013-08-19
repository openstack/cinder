# Copyright 2013 IBM Corp
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

"""Backup driver for IBM Tivoli Storage Manager (TSM).

Implementation of a backup service that uses IBM Tivoli Storage Manager (TSM)
as the backend. The driver uses TSM command line dsmc utility to
run an image backup and restore.
This version supports backup of block devices, e.g, FC, iSCSI, local.

A prerequisite for using the IBM TSM backup service is configuring the
Cinder host for using TSM.
"""

import os
import stat

from oslo.config import cfg

from cinder.backup.driver import BackupDriver
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder import utils

LOG = logging.getLogger(__name__)

tsmbackup_service_opts = [
    cfg.StrOpt('backup_tsm_volume_prefix',
               default='backup',
               help='Volume prefix for the backup id when backing up to TSM'),
    cfg.StrOpt('backup_tsm_password',
               default='password',
               help='TSM password for the running username'),
    cfg.BoolOpt('backup_tsm_compression',
                default=True,
                help='Enable or Disable compression for backups'),
]

CONF = cfg.CONF
CONF.register_opts(tsmbackup_service_opts)


class TSMBackupDriver(BackupDriver):
    """Provides backup, restore and delete of volumes backup for TSM."""

    DRIVER_VERSION = '1.0.0'

    def __init__(self, context, db_driver=None):
        self.context = context
        self.tsm_password = CONF.backup_tsm_password
        self.volume_prefix = CONF.backup_tsm_volume_prefix
        super(TSMBackupDriver, self).__init__(db_driver)

    def _make_link(self, volume_path, backup_path, vol_id):
        """Create a hard link for the volume block device.

        The IBM TSM client performs an image backup on a block device.
        The name of the block device is the backup prefix plus the backup id

        :param volume_path: real device path name for volume
        :param backup_path: path name TSM will use as volume to backup
        :param vol_id: id of volume to backup (for reporting)

        :raises: InvalidBackup
        """

        try:
            utils.execute('ln', volume_path, backup_path,
                          run_as_root=True,
                          check_exit_code=True)
        except processutils.ProcessExecutionError as e:
            err = (_('backup: %(vol_id)s Failed to create device hardlink '
                     'from %(vpath)s to %(bpath)s.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': vol_id,
                      'vpath': volume_path,
                      'bpath': backup_path,
                      'out': e.stdout,
                      'err': e.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

    def _check_dsmc_output(self, output, check_attrs):
        """Check dsmc command line utility output.

        Parse the output of the dsmc command and make sure that a given
        attribute is present, and that it has the proper value.
        TSM attribute has the format of "text : value".

        :param output: TSM output to parse
        :param check_attrs: text to identify in the output
        :returns bool -- indicate if requited output attribute found in output
        """

        parsed_attrs = {}
        for line in output.split('\n'):
            # parse TSM output: look for "msg : value
            key, sep, val = line.partition(':')
            if (sep is not None and key is not None and len(val.strip()) > 0):
                parsed_attrs[key] = val.strip()

        for k, v in check_attrs.iteritems():
            if k not in parsed_attrs or parsed_attrs[k] != v:
                return False
        return True

    def _do_backup(self, backup_path, vol_id):
        """Perform the actual backup operation.

       :param backup_path: volume path
       :param vol_id: volume id
       :raises: InvalidBackup
        """

        backup_attrs = {'Total number of objects backed up': '1'}
        compr_flag = 'yes' if CONF.backup_tsm_compression else 'no'

        out, err = utils.execute('dsmc',
                                 'backup',
                                 'image',
                                 '-quiet',
                                 '-compression=%s' % compr_flag,
                                 '-password=%s' % CONF.backup_tsm_password,
                                 backup_path,
                                 run_as_root=True,
                                 check_exit_code=False)

        success = self._check_dsmc_output(out, backup_attrs)
        if not success:
            err = (_('backup: %(vol_id)s Failed to obtain backup '
                     'success notification from server.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': vol_id,
                      'out': out,
                      'err': err})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

    def _do_restore(self, restore_path, vol_id):
        """Perform the actual restore operation.

        :param restore_path: volume path
        :param vol_id: volume id
        :raises: InvalidBackup
        """

        restore_attrs = {'Total number of objects restored': '1'}
        out, err = utils.execute('dsmc',
                                 'restore',
                                 'image',
                                 '-quiet',
                                 '-password=%s' % self.tsm_password,
                                 '-noprompt',
                                 restore_path,
                                 run_as_root=True,
                                 check_exit_code=False)

        success = self._check_dsmc_output(out, restore_attrs)
        if not success:
            err = (_('restore: %(vol_id)s Failed.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': vol_id,
                      'out': out,
                      'err': err})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

    def _get_volume_realpath(self, volume_file, volume_id):
        """Get the real path for the volume block device.

        If the volume is not a block device then issue an
        InvalidBackup exsception.

        :param volume_file: file object representing the volume
        :param volume_id: Volume id for backup or as restore target
        :raises: InvalidBackup
        :returns str -- real path of volume device
        """

        try:
            # Get real path
            volume_path = os.path.realpath(volume_file.name)
            # Verify that path is a block device
            volume_mode = os.stat(volume_path).st_mode
            if not stat.S_ISBLK(volume_mode):
                err = (_('backup: %(vol_id)s Failed. '
                         '%(path)s is not a block device.')
                       % {'vol_id': volume_id,
                          'path': volume_path})
                LOG.error(err)
                raise exception.InvalidBackup(reason=err)
        except AttributeError as e:
            err = (_('backup: %(vol_id)s Failed. Cannot obtain real path '
                     'to device %(path)s.')
                   % {'vol_id': volume_id,
                      'path': volume_file})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)
        except OSError as e:
            err = (_('backup: %(vol_id)s Failed. '
                     '%(path)s is not a file.')
                   % {'vol_id': volume_id,
                      'path': volume_path})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)
        return volume_path

    def _create_device_link_using_backupid(self,
                                           backup_id,
                                           volume_path,
                                           volume_id):
        """Create a consistent hardlink for the volume block device.

        Create a consistent hardlink using the backup id so TSM
        will be able to backup and restore to the same block device.

        :param backup_id: the backup id
        :param volume_path: real path of the backup/restore device
        :param volume_id: Volume id for backup or as restore target
        :raises: InvalidBackup
        :returns str -- hardlink path of the volume block device
        """

        hardlink_path = utils.make_dev_path('%s-%s' %
                                            (self.volume_prefix,
                                             backup_id))
        self._make_link(volume_path, hardlink_path, volume_id)
        return hardlink_path

    def _cleanup_device_hardlink(self,
                                 hardlink_path,
                                 volume_path,
                                 volume_id):
        """Remove the hardlink for the volume block device.

        :param hardlink_path: hardlink to the volume block device
        :param volume_path: real path of the backup/restore device
        :param volume_id: Volume id for backup or as restore target
        """

        try:
            utils.execute('rm',
                          '-f',
                          hardlink_path,
                          run_as_root=True)
        except processutils.ProcessExecutionError as e:
            err = (_('backup: %(vol_id)s Failed to remove backup hardlink'
                     ' from %(vpath)s to %(bpath)s.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'vpath': volume_path,
                      'bpath': hardlink_path,
                      'out': e.stdout,
                      'err': e.stderr})
            LOG.error(err)

    def backup(self, backup, volume_file):
        """Backup the given volume to TSM.

        TSM performs an image backup of a volume. The volume_file is
        used to determine the path of the block device that TSM will
        back-up.

        :param backup: backup information for volume
        :param volume_file: file object representing the volume
        :raises InvalidBackup
        """

        backup_id = backup['id']
        volume_id = backup['volume_id']
        volume_path = self._get_volume_realpath(volume_file, volume_id)

        LOG.debug(_('starting backup of volume: %(volume_id)s to TSM,'
                    ' volume path: %(volume_path)s,')
                  % {'volume_id': volume_id,
                     'volume_path': volume_path})

        backup_path = \
            self._create_device_link_using_backupid(backup_id,
                                                    volume_path,
                                                    volume_id)
        try:
            self._do_backup(backup_path, volume_id)
        except processutils.ProcessExecutionError as e:
            err = (_('backup: %(vol_id)s Failed to run dsmc '
                     'on %(bpath)s.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'bpath': backup_path,
                      'out': e.stdout,
                      'err': e.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)
        except exception.Error as e:
            err = (_('backup: %(vol_id)s Failed to run dsmc '
                     'due to invalid arguments '
                     'on %(bpath)s.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'bpath': backup_path,
                      'out': e.stdout,
                      'err': e.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

        finally:
            self._cleanup_device_hardlink(backup_path,
                                          volume_path,
                                          volume_id)

        LOG.debug(_('backup %s finished.') % backup_id)

    def restore(self, backup, volume_id, volume_file):
        """Restore the given volume backup from TSM server.

        :param backup: backup information for volume
        :param volume_id: volume id
        :param volume_file: file object representing the volume
        :raises InvalidBackup
        """

        backup_id = backup['id']
        volume_path = self._get_volume_realpath(volume_file, volume_id)

        LOG.debug(_('restore: starting restore of backup from TSM'
                    ' to volume %(volume_id)s, '
                    ' backup: %(backup_id)s')
                  % {'volume_id': volume_id,
                     'backup_id': backup_id})

        restore_path = \
            self._create_device_link_using_backupid(backup_id,
                                                    volume_path,
                                                    volume_id)

        try:
            self._do_restore(restore_path, volume_id)
        except processutils.ProcessExecutionError as e:
            err = (_('restore: %(vol_id)s Failed to run dsmc '
                     'on %(bpath)s.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'bpath': restore_path,
                      'out': e.stdout,
                      'err': e.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)
        except exception.Error as e:
            err = (_('restore: %(vol_id)s Failed to run dsmc '
                     'due to invalid arguments '
                     'on %(bpath)s.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'bpath': restore_path,
                      'out': e.stdout,
                      'err': e.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

        finally:
            self._cleanup_device_hardlink(restore_path,
                                          volume_path,
                                          volume_id)

        LOG.debug(_('restore %(backup_id)s to %(volume_id)s finished.')
                  % {'backup_id': backup_id,
                     'volume_id': volume_id})

    def delete(self, backup):
        """Delete the given backup from TSM server.

        :param backup: backup information for volume
        :raises InvalidBackup
        """

        delete_attrs = {'Total number of objects deleted': '1'}

        volume_id = backup['volume_id']
        backup_id = backup['id']
        LOG.debug('delete started, backup: %s',
                  backup['id'])

        volume_path = utils.make_dev_path('%s-%s' %
                                          (self.volume_prefix, backup_id))

        try:
            out, err = utils.execute('dsmc',
                                     'delete',
                                     'backup',
                                     '-quiet',
                                     '-noprompt',
                                     '-objtype=image',
                                     '-deltype=all',
                                     '-password=%s' % self.tsm_password,
                                     volume_path,
                                     run_as_root=True,
                                     check_exit_code=False)

        except processutils.ProcessExecutionError as e:
            err = (_('delete: %(vol_id)s Failed to run dsmc with '
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'out': e.stdout,
                      'err': e.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)
        except exception.Error as e:
            err = (_('restore: %(vol_id)s Failed to run dsmc '
                     'due to invalid arguments with '
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'out': e.stdout,
                      'err': e.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

        success = self._check_dsmc_output(out, delete_attrs)
        if not success:
            err = (_('delete: %(vol_id)s Failed with '
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'out': out,
                      'err': err})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

        LOG.debug(_('delete %s finished') % backup['id'])


def get_backup_driver(context):
    return TSMBackupDriver(context)
