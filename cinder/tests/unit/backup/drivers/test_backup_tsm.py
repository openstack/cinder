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
#
"""
Tests for volume backup to IBM Tivoli Storage Manager (TSM).
"""

import json
import mock
import posix

from oslo_concurrency import processutils as putils
from oslo_utils import timeutils

from cinder.backup.drivers import tsm
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder import test
from cinder.tests.unit import fake_constants as fake

SIM = None
VOLUME_PATH = '/dev/null'


class TSMBackupSimulator(object):
    """Simulates TSM dsmc command.

    The simulator simulates the execution of the 'dsmc' command.
    This allows the TSM backup test to succeed even if TSM is not installed.
    """
    def __init__(self):
        self._backup_list = {}
        self._hardlinks = []
        self._next_cmd_error = {
            'backup': '',
        }
        self._intro_msg = ('IBM Tivoli Storage Manager\n'
                           'Command Line Backup-Archive Client Interface\n'
                           '...\n\n')

    def _cmd_backup(self, **kwargs):
        # simulates the execution of the dsmc backup command
        ret_msg = self._intro_msg
        path = kwargs['path']

        ret_msg += ('Image backup of volume \'%s\'\n\n'
                    'Total number of objects inspected:  1\n'
                    % path)

        if self._next_cmd_error['backup'] == 'fail':
            ret_msg += ('ANS1228E Sending of object \'%s\' '
                        'failed\n' % path)
            ret_msg += ('ANS1063E The specified path is not a valid file '
                        'system or logical volume name.')
            self._next_cmd_error['backup'] = ''
            retcode = 12
        else:
            ret_msg += 'Total number of objects backed up:  1'
            if path not in self._backup_list:
                self._backup_list[path] = []
            else:
                self._backup_list[path][-1]['active'] = False
            date = timeutils.utcnow()
            datestr = date.strftime("%m/%d/%Y %H:%M:%S")
            self._backup_list[path].append({'date': datestr, 'active': True})
            retcode = 0

        return (ret_msg, '', retcode)

    def _backup_exists(self, path):
        if path not in self._backup_list:
            return ('ANS4000E Error processing \'%s\': file space does '
                    'not exist.' % path)

        return 'OK'

    def _cmd_restore(self, **kwargs):

        ret_msg = self._intro_msg
        path = kwargs['path']
        exists = self._backup_exists(path)

        if exists == 'OK':
            ret_msg += ('Total number of objects restored:  1\n'
                        'Total number of objects failed:  0')
            retcode = 0
        else:
            ret_msg += exists
            retcode = 12

        return (ret_msg, '', retcode)

    def _cmd_delete(self, **kwargs):
        # simulates the execution of the dsmc delete command
        ret_msg = self._intro_msg
        path = kwargs['path']
        exists = self._backup_exists(path)

        if exists == 'OK':
            ret_msg += ('Total number of objects deleted:  1\n'
                        'Total number of objects failed:  0')
            retcode = 0
            index = len(self._backup_list[path]) - 1
            del self._backup_list[path][index]
            if not len(self._backup_list[path]):
                del self._backup_list[path]
        else:
            ret_msg += exists
            retcode = 12

        return (ret_msg, '', retcode)

    def _cmd_to_dict(self, arg_list):
        """Convert command for kwargs (assumes a properly formed command)."""
        ret = {'cmd': arg_list[0],
               'type': arg_list[1],
               'path': arg_list[-1]}

        for i in range(2, len(arg_list) - 1):
            arg = arg_list[i].split('=')
            if len(arg) == 1:
                ret[arg[0]] = True
            else:
                ret[arg[0]] = arg[1]

        return ret

    def _exec_dsmc_cmd(self, cmd):
        """Simulates the execution of the dsmc command."""
        cmd_switch = {'backup': self._cmd_backup,
                      'restore': self._cmd_restore,
                      'delete': self._cmd_delete}

        kwargs = self._cmd_to_dict(cmd)
        if kwargs['cmd'] != 'dsmc' or kwargs['type'] not in cmd_switch:
            raise putils.ProcessExecutionError(exit_code=1,
                                               stdout='',
                                               stderr='Not dsmc command',
                                               cmd=' '.join(cmd))
        out, err, ret = cmd_switch[kwargs['type']](**kwargs)
        return (out, err, ret)

    def exec_cmd(self, cmd):
        """Simulates the execution of dsmc, rm, and ln commands."""
        if cmd[0] == 'dsmc':
            out, err, ret = self._exec_dsmc_cmd(cmd)
        elif cmd[0] == 'ln':
            dest = cmd[2]
            out = ''
            if dest in self._hardlinks:
                err = ('ln: failed to create hard link `%s\': '
                       'File exists' % dest)
                ret = 1
            else:
                self._hardlinks.append(dest)
                err = ''
                ret = 0
        elif cmd[0] == 'rm':
            dest = cmd[2]
            out = ''
            if dest not in self._hardlinks:
                err = ('rm: cannot remove `%s\': No such file or '
                       'directory' % dest)
                ret = 1
            else:
                index = self._hardlinks.index(dest)
                del self._hardlinks[index]
                err = ''
                ret = 0
        else:
            raise putils.ProcessExecutionError(exit_code=1,
                                               stdout='',
                                               stderr='Unsupported command',
                                               cmd=' '.join(cmd))
        return (out, err, ret)

    def error_injection(self, cmd, error):
        self._next_cmd_error[cmd] = error


def fake_exec(*cmd, **kwargs):
    # Support only bool
    check_exit_code = kwargs.pop('check_exit_code', True)
    global SIM

    out, err, ret = SIM.exec_cmd(cmd)
    if ret and check_exit_code:
        raise putils.ProcessExecutionError(
            exit_code=-1,
            stdout=out,
            stderr=err,
            cmd=' '.join(cmd))
    return (out, err)


def fake_stat_image(path):
    # Simulate stat to return the mode of a block device
    # make sure that st_mode (the first in the sequence(
    # matches the mode of a block device
    return posix.stat_result((25008, 5753, 5, 1, 0, 6, 0,
                              1375881199, 1375881197, 1375881197))


def fake_stat_file(path):
    # Simulate stat to return the mode of a block device
    # make sure that st_mode (the first in the sequence(
    # matches the mode of a block device
    return posix.stat_result((33188, 5753, 5, 1, 0, 6, 0,
                              1375881199, 1375881197, 1375881197))


def fake_stat_illegal(path):
    # Simulate stat to return the mode of a block device
    # make sure that st_mode (the first in the sequence(
    # matches the mode of a block device
    return posix.stat_result((17407, 5753, 5, 1, 0, 6, 0,
                              1375881199, 1375881197, 1375881197))


@mock.patch('cinder.utils.execute', fake_exec)
class BackupTSMTestCase(test.TestCase):
    def setUp(self):
        super(BackupTSMTestCase, self).setUp()
        global SIM
        SIM = TSMBackupSimulator()
        self.sim = SIM
        self.ctxt = context.get_admin_context()
        self.driver = tsm.TSMBackupDriver(self.ctxt)

    def _create_volume_db_entry(self, volume_id):
        vol = {'id': volume_id,
               'size': 1,
               'status': 'available'}
        return db.volume_create(self.ctxt, vol)['id']

    def _create_backup_db_entry(self, backup_id, mode):
        if mode == 'file':
            backup_path = VOLUME_PATH
        else:
            backup_path = '/dev/backup-%s' % backup_id
        service_metadata = json.dumps({'backup_mode': mode,
                                       'backup_path': backup_path})
        backup = {'id': backup_id,
                  'size': 1,
                  'container': 'test-container',
                  'volume_id': fake.VOLUME_ID,
                  'service_metadata': service_metadata,
                  'user_id': fake.USER_ID,
                  'project_id': fake.PROJECT_ID,
                  }
        return db.backup_create(self.ctxt, backup)['id']

    @mock.patch.object(tsm.os, 'stat', fake_stat_image)
    @mock.patch('cinder.privsep.path.symlink')
    def test_backup_image(self, mock_symlink):
        volume_id = fake.VOLUME_ID
        mode = 'image'
        self._create_volume_db_entry(volume_id)

        backup_id1 = fake.BACKUP_ID
        backup_id2 = fake.BACKUP2_ID
        backup_id3 = fake.BACKUP3_ID
        self._create_backup_db_entry(backup_id1, mode)
        self._create_backup_db_entry(backup_id2, mode)
        self._create_backup_db_entry(backup_id3, mode)

        with open(VOLUME_PATH, 'w+') as volume_file:
            # Create two backups of the volume
            backup1 = objects.Backup.get_by_id(self.ctxt, backup_id1)
            self.driver.backup(backup1, volume_file)
            backup2 = objects.Backup.get_by_id(self.ctxt, backup_id2)
            self.driver.backup(backup2, volume_file)

            # Create a backup that fails
            fail_back = objects.Backup.get_by_id(self.ctxt, backup_id3)
            self.sim.error_injection('backup', 'fail')
            self.assertRaises(exception.InvalidBackup,
                              self.driver.backup, fail_back, volume_file)

            # Try to restore one, then the other
            self.driver.restore(backup1, volume_id, volume_file)
            self.driver.restore(backup2, volume_id, volume_file)

            # Delete both backups
            self.driver.delete_backup(backup2)
            self.driver.delete_backup(backup1)

    @mock.patch.object(tsm.os, 'stat', fake_stat_file)
    @mock.patch('cinder.privsep.path.symlink')
    def test_backup_file(self, mock_symlink):
        volume_id = fake.VOLUME_ID
        mode = 'file'
        self._create_volume_db_entry(volume_id)

        self._create_backup_db_entry(fake.BACKUP_ID, mode)
        self._create_backup_db_entry(fake.BACKUP2_ID, mode)

        with open(VOLUME_PATH, 'w+') as volume_file:
            # Create two backups of the volume
            backup1 = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
            self.driver.backup(backup1, volume_file)
            backup2 = objects.Backup.get_by_id(self.ctxt, fake.BACKUP2_ID)
            self.driver.backup(backup2, volume_file)

            # Create a backup that fails
            self._create_backup_db_entry(fake.BACKUP3_ID, mode)
            fail_back = objects.Backup.get_by_id(self.ctxt, fake.BACKUP3_ID)
            self.sim.error_injection('backup', 'fail')
            self.assertRaises(exception.InvalidBackup,
                              self.driver.backup, fail_back, volume_file)

            # Try to restore one, then the other
            self.driver.restore(backup1, volume_id, volume_file)
            self.driver.restore(backup2, volume_id, volume_file)

            # Delete both backups
            self.driver.delete_backup(backup1)
            self.driver.delete_backup(backup2)

    @mock.patch.object(tsm.os, 'stat', fake_stat_illegal)
    def test_backup_invalid_mode(self):
        volume_id = fake.VOLUME_ID
        mode = 'illegal'
        self._create_volume_db_entry(volume_id)

        self._create_backup_db_entry(fake.BACKUP_ID, mode)

        with open(VOLUME_PATH, 'w+') as volume_file:
            # Create two backups of the volume
            backup1 = objects.Backup.get_by_id(self.ctxt, fake.BACKUP_ID)
            self.assertRaises(exception.InvalidBackup,
                              self.driver.backup, backup1, volume_file)

            self.assertRaises(exception.InvalidBackup,
                              self.driver.restore,
                              backup1,
                              volume_id,
                              volume_file)

            self.assertRaises(exception.InvalidBackup,
                              self.driver.delete_backup, backup1)
