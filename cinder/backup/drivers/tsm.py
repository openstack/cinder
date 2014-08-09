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
run the backup and restore operations.
This version supports backup of block devices, e.g, FC, iSCSI, local as well as
regular files.

A prerequisite for using the IBM TSM backup service is configuring the
Cinder host for using TSM.
"""

import json
import os
import stat

from oslo.config import cfg

from cinder.backup.driver import BackupDriver
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder import utils

LOG = logging.getLogger(__name__)

tsm_opts = [
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
CONF.register_opts(tsm_opts)

VALID_BACKUP_MODES = ['image', 'file']


def _get_backup_metadata(backup, operation):
    """Return metadata persisted with backup object."""
    svc_metadata = backup['service_metadata']
    try:
        svc_dict = json.loads(svc_metadata)
        backup_path = svc_dict.get('backup_path')
        backup_mode = svc_dict.get('backup_mode')
    except TypeError:
        # for backwards compatibility
        vol_prefix = CONF.backup_tsm_volume_prefix
        backup_id = backup['id']
        backup_path = utils.make_dev_path('%s-%s' %
                                          (vol_prefix, backup_id))
        backup_mode = 'image'

    if backup_mode not in VALID_BACKUP_MODES:
        volume_id = backup['volume_id']
        backup_id = backup['id']
        err = (_('%(op)s: backup %(bck_id)s, volume %(vol_id)s failed. '
                 'Backup object has unexpected mode. Image or file '
                 'backups supported, actual mode is %(vol_mode)s.')
               % {'op': operation,
                  'bck_id': backup_id,
                  'vol_id': volume_id,
                  'vol_mode': backup_mode})
        LOG.error(err)
        raise exception.InvalidBackup(reason=err)
    return backup_path, backup_mode


def _image_mode(backup_mode):
    """True if backup is image type."""
    return backup_mode == 'image'


def _make_link(volume_path, backup_path, vol_id):
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
    except processutils.ProcessExecutionError as exc:
        err = (_('backup: %(vol_id)s failed to create device hardlink '
                 'from %(vpath)s to %(bpath)s.\n'
                 'stdout: %(out)s\n stderr: %(err)s')
               % {'vol_id': vol_id,
                  'vpath': volume_path,
                  'bpath': backup_path,
                  'out': exc.stdout,
                  'err': exc.stderr})
        LOG.error(err)
        raise exception.InvalidBackup(reason=err)


def _create_unique_device_link(backup_id, volume_path, volume_id, bckup_mode):
    """Create a consistent hardlink for the volume block device.

    Create a consistent hardlink using the backup id so TSM
    will be able to backup and restore to the same block device.

    :param backup_id: the backup id
    :param volume_path: real path of the backup/restore device
    :param volume_id: Volume id for backup or as restore target
    :param bckup_mode: TSM backup mode, either 'image' or 'file'
    :raises: InvalidBackup
    :returns str -- hardlink path of the volume block device
    """
    if _image_mode(bckup_mode):
        hardlink_path = utils.make_dev_path('%s-%s' %
                                            (CONF.backup_tsm_volume_prefix,
                                             backup_id))
    else:
        dir, volname = os.path.split(volume_path)
        hardlink_path = ('%s/%s-%s' %
                         (dir,
                          CONF.backup_tsm_volume_prefix,
                          backup_id))
    _make_link(volume_path, hardlink_path, volume_id)
    return hardlink_path


def _check_dsmc_output(output, check_attrs, exact_match=True):
    """Check dsmc command line utility output.

    Parse the output of the dsmc command and make sure that a given
    attribute is present, and that it has the proper value.
    TSM attribute has the format of "text : value".

    :param output: TSM output to parse
    :param check_attrs: text to identify in the output
    :param exact_match: if True, the check will pass only if the parsed
    value is equal to the value specified in check_attrs.  If false, the
    check will pass if the parsed value is greater than or equal to the
    value specified in check_attrs.  This is needed because for file
    backups, the parent directories may also be included the first a
    volume is backed up.
    :returns bool -- indicate if requited output attribute found in output
    """

    parsed_attrs = {}
    for line in output.split('\n'):
        # parse TSM output: look for "msg : value
        key, sep, val = line.partition(':')
        if sep is not None and key is not None and len(val.strip()) > 0:
            parsed_attrs[key] = val.strip()

    for ckey, cval in check_attrs.iteritems():
        if ckey not in parsed_attrs:
            return False
        elif exact_match and parsed_attrs[ckey] != cval:
            return False
        elif not exact_match and int(parsed_attrs[ckey]) < int(cval):
            return False

    return True


def _get_volume_realpath(volume_file, volume_id):
    """Get the real path for the volume block device.

    If the volume is not a block device or a regular file issue an
    InvalidBackup exception.

    :param volume_file: file object representing the volume
    :param volume_id: Volume id for backup or as restore target
    :raises: InvalidBackup
    :returns str -- real path of volume device
    :returns str -- backup mode to be used
    """

    try:
        # Get real path
        volume_path = os.path.realpath(volume_file.name)
        # Verify that path is a block device
        volume_mode = os.stat(volume_path).st_mode
        if stat.S_ISBLK(volume_mode):
            backup_mode = 'image'
        elif stat.S_ISREG(volume_mode):
            backup_mode = 'file'
        else:
            err = (_('backup: %(vol_id)s failed. '
                     '%(path)s is unexpected file type. Block or regular '
                     'files supported, actual file mode is %(vol_mode)s.')
                   % {'vol_id': volume_id,
                      'path': volume_path,
                      'vol_mode': volume_mode})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

    except AttributeError:
        err = (_('backup: %(vol_id)s failed. Cannot obtain real path '
                 'to volume at %(path)s.')
               % {'vol_id': volume_id,
                  'path': volume_file})
        LOG.error(err)
        raise exception.InvalidBackup(reason=err)
    except OSError:
        err = (_('backup: %(vol_id)s failed. '
                 '%(path)s is not a file.')
               % {'vol_id': volume_id,
                  'path': volume_path})
        LOG.error(err)
        raise exception.InvalidBackup(reason=err)
    return volume_path, backup_mode


def _cleanup_device_hardlink(hardlink_path, volume_path, volume_id):
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
    except processutils.ProcessExecutionError as exc:
        err = (_('backup: %(vol_id)s failed to remove backup hardlink'
                 ' from %(vpath)s to %(bpath)s.\n'
                 'stdout: %(out)s\n stderr: %(err)s.')
               % {'vol_id': volume_id,
                  'vpath': volume_path,
                  'bpath': hardlink_path,
                  'out': exc.stdout,
                  'err': exc.stderr})
        LOG.error(err)


class TSMBackupDriver(BackupDriver):
    """Provides backup, restore and delete of volumes backup for TSM."""

    DRIVER_VERSION = '1.0.0'

    def __init__(self, context, db_driver=None):
        super(TSMBackupDriver, self).__init__(context, db_driver)
        self.tsm_password = CONF.backup_tsm_password
        self.volume_prefix = CONF.backup_tsm_volume_prefix

    def _do_backup(self, backup_path, vol_id, backup_mode):
        """Perform the actual backup operation.

       :param backup_path: volume path
       :param vol_id: volume id
       :param backup_mode: file mode of source volume; 'image' or 'file'
       :raises: InvalidBackup
        """

        backup_attrs = {'Total number of objects backed up': '1'}
        compr_flag = 'yes' if CONF.backup_tsm_compression else 'no'

        backup_cmd = ['dsmc', 'backup']
        if _image_mode(backup_mode):
            backup_cmd.append('image')
        backup_cmd.extend(['-quiet',
                           '-compression=%s' % compr_flag,
                           '-password=%s' % self.tsm_password,
                           backup_path])

        out, err = utils.execute(*backup_cmd,
                                 run_as_root=True,
                                 check_exit_code=False)

        success = _check_dsmc_output(out, backup_attrs, exact_match=False)
        if not success:
            err = (_('backup: %(vol_id)s failed to obtain backup '
                     'success notification from server.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': vol_id,
                      'out': out,
                      'err': err})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

    def _do_restore(self, backup_path, restore_path, vol_id, backup_mode):
        """Perform the actual restore operation.

        :param backup_path: the path the backup was created from, this
        identifies the backup to tsm
        :param restore_path: volume path to restore into
        :param vol_id: volume id
        :param backup_mode: mode used to create the backup ('image' or 'file')
        :raises: InvalidBackup
        """

        restore_attrs = {'Total number of objects restored': '1'}
        restore_cmd = ['dsmc', 'restore']
        if _image_mode(backup_mode):
            restore_cmd.append('image')
            restore_cmd.append('-noprompt')  # suppress prompt
        else:
            restore_cmd.append('-replace=yes')  # suppress prompt

        restore_cmd.extend(['-quiet',
                            '-password=%s' % self.tsm_password,
                            backup_path])

        if restore_path != backup_path:
            restore_cmd.append(restore_path)

        out, err = utils.execute(*restore_cmd,
                                 run_as_root=True,
                                 check_exit_code=False)

        success = _check_dsmc_output(out, restore_attrs)
        if not success:
            err = (_('restore: %(vol_id)s failed.\n'
                     'stdout: %(out)s\n stderr: %(err)s.')
                   % {'vol_id': vol_id,
                      'out': out,
                      'err': err})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

    def backup(self, backup, volume_file, backup_metadata=False):
        """Backup the given volume to TSM.

        TSM performs a backup of a volume. The volume_file is used
        to determine the path of the block device that TSM will back-up.

        :param backup: backup information for volume
        :param volume_file: file object representing the volume
        :param backup_metadata: whether or not to backup volume metadata
        :raises InvalidBackup
        """

        # TODO(dosaboy): this needs implementing (see backup.drivers.ceph for
        #                an example)
        if backup_metadata:
            msg = _("Volume metadata backup requested but this driver does "
                    "not yet support this feature.")
            raise exception.InvalidBackup(reason=msg)

        backup_id = backup['id']
        volume_id = backup['volume_id']
        volume_path, backup_mode = _get_volume_realpath(volume_file,
                                                        volume_id)
        LOG.debug('Starting backup of volume: %(volume_id)s to TSM,'
                  ' volume path: %(volume_path)s, mode: %(mode)s.'
                  % {'volume_id': volume_id,
                     'volume_path': volume_path,
                     'mode': backup_mode})

        backup_path = _create_unique_device_link(backup_id,
                                                 volume_path,
                                                 volume_id,
                                                 backup_mode)

        service_metadata = {'backup_mode': backup_mode,
                            'backup_path': backup_path}
        self.db.backup_update(self.context,
                              backup_id,
                              {'service_metadata':
                               json.dumps(service_metadata)})

        try:
            self._do_backup(backup_path, volume_id, backup_mode)
        except processutils.ProcessExecutionError as exc:
            err = (_('backup: %(vol_id)s failed to run dsmc '
                     'on %(bpath)s.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'bpath': backup_path,
                      'out': exc.stdout,
                      'err': exc.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)
        except exception.Error as exc:
            err = (_('backup: %(vol_id)s failed to run dsmc '
                     'due to invalid arguments '
                     'on %(bpath)s.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'bpath': backup_path,
                      'out': exc.stdout,
                      'err': exc.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

        finally:
            _cleanup_device_hardlink(backup_path, volume_path, volume_id)

        LOG.debug('Backup %s finished.' % backup_id)

    def restore(self, backup, volume_id, volume_file):
        """Restore the given volume backup from TSM server.

        :param backup: backup information for volume
        :param volume_id: volume id
        :param volume_file: file object representing the volume
        :raises InvalidBackup
        """

        backup_id = backup['id']

        # backup_path is the path that was originally backed up.
        backup_path, backup_mode = _get_backup_metadata(backup, 'restore')

        LOG.debug('Starting restore of backup from TSM '
                  'to volume %(volume_id)s, '
                  'backup: %(backup_id)s, '
                  'mode: %(mode)s.' %
                  {'volume_id': volume_id,
                   'backup_id': backup_id,
                   'mode': backup_mode})

        # volume_path is the path to restore into.  This may
        # be different than the original volume.
        volume_path, unused = _get_volume_realpath(volume_file,
                                                   volume_id)

        restore_path = _create_unique_device_link(backup_id,
                                                  volume_path,
                                                  volume_id,
                                                  backup_mode)

        try:
            self._do_restore(backup_path, restore_path, volume_id, backup_mode)
        except processutils.ProcessExecutionError as exc:
            err = (_('restore: %(vol_id)s failed to run dsmc '
                     'on %(bpath)s.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'bpath': restore_path,
                      'out': exc.stdout,
                      'err': exc.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)
        except exception.Error as exc:
            err = (_('restore: %(vol_id)s failed to run dsmc '
                     'due to invalid arguments '
                     'on %(bpath)s.\n'
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'bpath': restore_path,
                      'out': exc.stdout,
                      'err': exc.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

        finally:
            _cleanup_device_hardlink(restore_path, volume_path, volume_id)

        LOG.debug('Restore %(backup_id)s to %(volume_id)s finished.'
                  % {'backup_id': backup_id,
                     'volume_id': volume_id})

    def delete(self, backup):
        """Delete the given backup from TSM server.

        :param backup: backup information for volume
        :raises InvalidBackup
        """

        delete_attrs = {'Total number of objects deleted': '1'}
        delete_path, backup_mode = _get_backup_metadata(backup, 'restore')
        volume_id = backup['volume_id']

        LOG.debug('Delete started for backup: %(backup)s, mode: %(mode)s.',
                  {'backup': backup['id'],
                   'mode': backup_mode})

        try:
            out, err = utils.execute('dsmc',
                                     'delete',
                                     'backup',
                                     '-quiet',
                                     '-noprompt',
                                     '-objtype=%s' % backup_mode,
                                     '-password=%s' % self.tsm_password,
                                     delete_path,
                                     run_as_root=True,
                                     check_exit_code=False)

        except processutils.ProcessExecutionError as exc:
            err = (_('delete: %(vol_id)s failed to run dsmc with '
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'out': exc.stdout,
                      'err': exc.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)
        except exception.Error as exc:
            err = (_('delete: %(vol_id)s failed to run dsmc '
                     'due to invalid arguments with '
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'out': exc.stdout,
                      'err': exc.stderr})
            LOG.error(err)
            raise exception.InvalidBackup(reason=err)

        success = _check_dsmc_output(out, delete_attrs)
        if not success:
            # log error if tsm cannot delete the backup object
            # but do not raise exception so that cinder backup
            # object can be removed.
            err = (_('delete: %(vol_id)s failed with '
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'vol_id': volume_id,
                      'out': out,
                      'err': err})
            LOG.error(err)

        LOG.debug('Delete %s finished.' % backup['id'])


def get_backup_driver(context):
    return TSMBackupDriver(context)
