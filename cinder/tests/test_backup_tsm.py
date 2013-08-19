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

import datetime
import os
import posix

from cinder.backup.drivers import tsm
from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils
from cinder import test
from cinder import utils

LOG = logging.getLogger(__name__)
SIM = None


class TSMBackupSimulator:
    # The simulator simulates the execution of the 'dsmc' command.
    # This allows the TSM backup test to succeed even if TSM is not installed.
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
            date = datetime.datetime.now()
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
            for idx, backup in enumerate(self._backup_list[path]):
                index = idx
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
        # simulates the execution of the dsmc command
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
        # simulates the execution of dsmc, rm, and ln commands
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


def fake_stat(path):
    # Simulate stat to retun the mode of a block device
    # make sure that st_mode (the first in the sequence(
    # matches the mode of a block device
    return posix.stat_result((25008, 5753, 5L, 1, 0, 6, 0,
                              1375881199, 1375881197, 1375881197))


class BackupTSMTestCase(test.TestCase):
    def setUp(self):
        super(BackupTSMTestCase, self).setUp()
        global SIM
        SIM = TSMBackupSimulator()
        self.sim = SIM
        self.ctxt = context.get_admin_context()
        self.driver = tsm.TSMBackupDriver(self.ctxt)
        self.stubs.Set(utils, 'execute', fake_exec)
        self.stubs.Set(os, 'stat', fake_stat)

    def tearDown(self):
        super(BackupTSMTestCase, self).tearDown()

    def _create_volume_db_entry(self, volume_id):
        vol = {'id': volume_id,
               'size': 1,
               'status': 'available'}
        return db.volume_create(self.ctxt, vol)['id']

    def _create_backup_db_entry(self, backup_id):
        backup = {'id': backup_id,
                  'size': 1,
                  'container': 'test-container',
                  'volume_id': '1234-5678-1234-8888'}
        return db.backup_create(self.ctxt, backup)['id']

    def test_backup(self):
        volume_id = '1234-5678-1234-8888'
        self._create_volume_db_entry(volume_id)

        backup_id1 = 123
        backup_id2 = 456
        self._create_backup_db_entry(backup_id1)
        self._create_backup_db_entry(backup_id2)

        volume_file = open('/dev/null', 'rw')

        # Create two backups of the volume
        backup1 = db.backup_get(self.ctxt, 123)
        self.driver.backup(backup1, volume_file)
        backup2 = db.backup_get(self.ctxt, 456)
        self.driver.backup(backup2, volume_file)

        # Create a backup that fails
        self._create_backup_db_entry(666)
        fail_back = db.backup_get(self.ctxt, 666)
        self.sim.error_injection('backup', 'fail')
        self.assertRaises(exception.InvalidBackup,
                          self.driver.backup, fail_back, volume_file)

        # Try to restore one, then the other
        backup1 = db.backup_get(self.ctxt, 123)
        self.driver.restore(backup1, volume_id, volume_file)
        self.driver.restore(backup2, volume_id, volume_file)

        # Delete both backups
        self.driver.delete(backup2)
        self.driver.delete(backup1)
