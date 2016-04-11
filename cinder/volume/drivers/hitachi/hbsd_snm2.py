# Copyright (C) 2014, Hitachi, Ltd.
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

import re
import shlex
import threading
import time

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _LE, _LW
from cinder import utils
from cinder.volume.drivers.hitachi import hbsd_basiclib as basic_lib

LOG = logging.getLogger(__name__)

SNM2_ENV = ('LANG=C STONAVM_HOME=/usr/stonavm '
            'LD_LIBRARY_PATH=/usr/stonavm/lib '
            'STONAVM_RSP_PASS=on STONAVM_ACT=on')

MAX_HOSTGROUPS = 127
MAX_HOSTGROUPS_ISCSI = 254
MAX_HLUN = 2047
EXEC_LOCK_PATH_BASE = basic_lib.LOCK_DIR + 'hsnm_'
EXEC_TIMEOUT = 10
EXEC_INTERVAL = 1

CHAP_TIMEOUT = 5
PAIRED = 12
DUMMY_LU = -1


class HBSDSNM2(basic_lib.HBSDBasicLib):

    def __init__(self, conf):
        super(HBSDSNM2, self).__init__(conf=conf)

        self.unit_name = conf.hitachi_unit_name
        self.hsnm_lock = threading.Lock()
        self.hsnm_lock_file = ('%s%s'
                               % (EXEC_LOCK_PATH_BASE, self.unit_name))
        copy_speed = conf.hitachi_copy_speed
        if copy_speed <= 2:
            self.pace = 'slow'
        elif copy_speed == 3:
            self.pace = 'normal'
        else:
            self.pace = 'prior'

    def _wait_for_exec_hsnm(self, args, printflag, noretry, timeout, start):
        lock = basic_lib.get_process_lock(self.hsnm_lock_file)
        with self.hsnm_lock, lock:
            ret, stdout, stderr = self.exec_command('env', args=args,
                                                    printflag=printflag)

        if not ret or noretry:
            raise loopingcall.LoopingCallDone((ret, stdout, stderr))

        if time.time() - start >= timeout:
            LOG.error(_LE("snm2 command timeout."))
            raise loopingcall.LoopingCallDone((ret, stdout, stderr))

        if (re.search('DMEC002047', stderr)
                or re.search('DMEC002048', stderr)
                or re.search('DMED09000A', stderr)
                or re.search('DMED090026', stderr)
                or re.search('DMED0E002B', stderr)
                or re.search('DMER03006A', stderr)
                or re.search('DMER030080', stderr)
                or re.search('DMER0300B8', stderr)
                or re.search('DMER0800CF', stderr)
                or re.search('DMER0800D[0-6D]', stderr)
                or re.search('DMES052602', stderr)):
            LOG.error(_LE("Unexpected error occurs in snm2."))
            raise loopingcall.LoopingCallDone((ret, stdout, stderr))

    def exec_hsnm(self, command, args, printflag=True, noretry=False,
                  timeout=EXEC_TIMEOUT, interval=EXEC_INTERVAL):
        args = '%s %s %s' % (SNM2_ENV, command, args)

        loop = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_exec_hsnm, args, printflag,
            noretry, timeout, time.time())

        return loop.start(interval=interval).wait()

    def _execute_with_exception(self, cmd, args, **kwargs):
        ret, stdout, stderr = self.exec_hsnm(cmd, args, **kwargs)
        if ret:
            cmds = '%(cmd)s %(args)s' % {'cmd': cmd, 'args': args}
            msg = basic_lib.output_err(
                600, cmd=cmds, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDError(data=msg)

        return ret, stdout, stderr

    def _execute_and_return_stdout(self, cmd, args, **kwargs):
        result = self._execute_with_exception(cmd, args, **kwargs)

        return result[1]

    def get_comm_version(self):
        ret, stdout, stderr = self.exec_hsnm('auman', '-help')
        m = re.search('Version (\d+).(\d+)', stdout)
        if not m:
            msg = basic_lib.output_err(
                600, cmd='auman', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        return '%s.%s' % (m.group(1), m.group(2))

    def add_used_hlun(self, command, port, gid, used_list, ldev):
        unit = self.unit_name
        ret, stdout, stderr = self.exec_hsnm(command,
                                             '-unit %s -refer' % unit)
        if ret:
            msg = basic_lib.output_err(
                600, cmd=command, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        lines = stdout.splitlines()
        for line in lines[2:]:
            line = shlex.split(line)
            if not line:
                continue
            if line[0] == port and int(line[1][0:3]) == gid:
                if int(line[2]) not in used_list:
                    used_list.append(int(line[2]))
                if int(line[3]) == ldev:
                    hlu = int(line[2])
                    LOG.warning(_LW('ldev(%(ldev)d) is already mapped '
                                    '(hlun: %(hlu)d)'),
                                {'ldev': ldev, 'hlu': hlu})
                    return hlu
        return None

    def _get_lu(self, lu=None):
        # When 'lu' is 0, it should be true. So, it cannot remove 'is None'.
        if lu is None:
            args = '-unit %s' % self.unit_name
        else:
            args = '-unit %s -lu %s' % (self.unit_name, lu)

        return self._execute_and_return_stdout('auluref', args)

    def get_unused_ldev(self, ldev_range):
        start = ldev_range[0]
        end = ldev_range[1]
        unit = self.unit_name

        ret, stdout, stderr = self.exec_hsnm('auluref', '-unit %s' % unit)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='auluref', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        free_ldev = start
        lines = stdout.splitlines()
        found = False
        for line in lines[2:]:
            line = shlex.split(line)
            if not line:
                continue
            ldev_num = int(line[0])
            if free_ldev > ldev_num:
                continue
            if free_ldev == ldev_num:
                free_ldev += 1
            else:
                found = True
                break
            if free_ldev > end:
                break
        else:
            found = True

        if not found:
            msg = basic_lib.output_err(648, resource='LDEV')
            raise exception.HBSDError(message=msg)

        return free_ldev

    def get_hgname_gid(self, port, host_grp_name):
        unit = self.unit_name
        ret, stdout, stderr = self.exec_hsnm('auhgdef',
                                             '-unit %s -refer' % unit)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='auhgdef', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        lines = stdout.splitlines()
        is_target_port = False
        for line in lines:
            line = shlex.split(line)
            if not line:
                continue
            if line[0] == 'Port' and line[1] == port:
                is_target_port = True
                continue
            if is_target_port:
                if line[0] == 'Port':
                    break
                if not line[0].isdigit():
                    continue
                gid = int(line[0])
                if line[1] == host_grp_name:
                    return gid
        return None

    def get_unused_gid(self, group_range, port):
        start = group_range[0]
        end = group_range[1]
        unit = self.unit_name

        ret, stdout, stderr = self.exec_hsnm('auhgdef',
                                             '-unit %s -refer' % unit)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='auhgdef', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        lines = stdout.splitlines()
        is_target_port = False
        free_gid = start
        found = False
        for line in lines:
            line = shlex.split(line)
            if not line:
                continue
            if line[0] == 'Port' and line[1] == port:
                is_target_port = True
                continue
            if is_target_port:
                if line[0] == 'Port':
                    found = True
                    break
                if not line[0].isdigit():
                    continue

                gid = int(line[0])
                if free_gid > gid:
                    continue
                if free_gid == gid:
                    free_gid += 1
                else:
                    found = True
                    break
                if free_gid > end or free_gid > MAX_HOSTGROUPS:
                    break
        else:
            found = True

        if not found:
            msg = basic_lib.output_err(648, resource='GID')
            raise exception.HBSDError(message=msg)

        return free_gid

    def comm_set_target_wwns(self, target_ports):
        unit = self.unit_name
        ret, stdout, stderr = self.exec_hsnm('aufibre1',
                                             '-unit %s -refer' % unit)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='aufibre1', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        lines = stdout.splitlines()
        target_wwns = {}
        for line in lines[3:]:
            if re.match('Transfer', line):
                break

            line = shlex.split(line)
            if len(line) < 4:
                continue

            port = '%s%s' % (line[0], line[1])
            if target_ports:
                if port in target_ports:
                    target_wwns[port] = line[3]
            else:
                target_wwns[port] = line[3]

        LOG.debug('target wwns: %s', target_wwns)
        return target_wwns

    def get_hostgroup_from_wwns(self, hostgroups, port, wwns, buf, login):
        for pt in wwns:
            for line in buf[port]['assigned']:
                hgname = shlex.split(line[38:])[1][4:]
                if not re.match(basic_lib.NAME_PREFIX, hgname):
                    continue
                if pt.search(line[38:54]):
                    wwn = line[38:54]
                    gid = int(shlex.split(line[38:])[1][0:3])
                    is_detected = None
                    if login:
                        for line in buf[port]['detected']:
                            if pt.search(line[38:54]):
                                is_detected = True
                                break
                        else:
                            is_detected = False
                    hostgroups.append({'port': six.text_type(port), 'gid': gid,
                                       'initiator_wwn': wwn,
                                       'detected': is_detected})

    def comm_get_hostgroup_info(self, hgs, wwns, target_ports, login=True):
        unit = self.unit_name
        ret, stdout, stderr = self.exec_hsnm('auhgwwn',
                                             '-unit %s -refer' % unit)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='auhgwwn', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        security_ports = []
        patterns = []
        for wwn in wwns:
            pt = re.compile(wwn, re.IGNORECASE)
            patterns.append(pt)

        lines = stdout.splitlines()
        buf = {}
        _buffer = []
        port = None
        security = None
        for line in lines:
            if re.match('Port', line):
                port = shlex.split(line)[1]
                if target_ports and port not in target_ports:
                    port = None
                else:
                    security = True if shlex.split(line)[5] == 'ON' else False
                    buf[port] = {'detected': [], 'assigned': [],
                                 'assignable': []}
                    if security:
                        security_ports.append(port)
                continue
            if port and security:
                if re.search('Detected WWN', line):
                    _buffer = buf[port]['detected']
                    continue
                elif re.search('Assigned WWN', line):
                    _buffer = buf[port]['assigned']
                    continue
                elif re.search('Assignable WWN', line):
                    _buffer = buf[port]['assignable']
                    continue
                _buffer.append(line)

        hostgroups = []
        for port in buf.keys():
            self.get_hostgroup_from_wwns(
                hostgroups, port, patterns, buf, login)

        for hostgroup in hostgroups:
            hgs.append(hostgroup)

        return security_ports

    def comm_delete_lun_core(self, command, hostgroups, lun):
        unit = self.unit_name

        no_lun_cnt = 0
        deleted_hostgroups = []
        for hostgroup in hostgroups:
            LOG.debug('comm_delete_lun: hostgroup is %s', hostgroup)
            port = hostgroup['port']
            gid = hostgroup['gid']
            ctl_no = port[0]
            port_no = port[1]

            is_deleted = False
            for deleted in deleted_hostgroups:
                if port == deleted['port'] and gid == deleted['gid']:
                    is_deleted = True
            if is_deleted:
                continue
            ret, stdout, stderr = self.exec_hsnm(command,
                                                 '-unit %s -refer' % unit)
            if ret:
                msg = basic_lib.output_err(
                    600, cmd=command, ret=ret, out=stdout, err=stderr)
                raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

            lines = stdout.splitlines()
            for line in lines[2:]:
                line = shlex.split(line)
                if not line:
                    continue
                if (line[0] == port and int(line[1][0:3]) == gid
                        and int(line[3]) == lun):
                    hlu = int(line[2])
                    break
            else:
                no_lun_cnt += 1
                if no_lun_cnt == len(hostgroups):
                    raise exception.HBSDNotFound
                else:
                    continue

            opt = '-unit %s -rm %s %s %d %d %d' % (unit, ctl_no, port_no,
                                                   gid, hlu, lun)
            ret, stdout, stderr = self.exec_hsnm(command, opt)
            if ret:
                msg = basic_lib.output_err(
                    600, cmd=command, ret=ret, out=stdout, err=stderr)
                raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

            deleted_hostgroups.append({'port': port, 'gid': gid})
            LOG.debug('comm_delete_lun is over (%d)', lun)

    def comm_delete_lun(self, hostgroups, ldev):
        self.comm_delete_lun_core('auhgmap', hostgroups, ldev)

    def comm_delete_lun_iscsi(self, hostgroups, ldev):
        self.comm_delete_lun_core('autargetmap', hostgroups, ldev)

    def comm_add_ldev(self, pool_id, ldev, capacity, is_vvol):
        unit = self.unit_name

        if is_vvol:
            command = 'aureplicationvvol'
            opt = ('-unit %s -add -lu %d -size %dg'
                   % (unit, ldev, capacity))
        else:
            command = 'auluadd'
            opt = ('-unit %s -lu %d -dppoolno %d -size %dg'
                   % (unit, ldev, pool_id, capacity))

        ret, stdout, stderr = self.exec_hsnm(command, opt)
        if ret:
            if (re.search('DMEC002047', stderr)
                    or re.search('DMES052602', stderr)
                    or re.search('DMED09000A', stderr)):
                raise exception.HBSDNotFound
            else:
                msg = basic_lib.output_err(
                    600, cmd=command, ret=ret, out=stdout, err=stderr)
                raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_add_hostgrp(self, port, gid, host_grp_name):
        unit = self.unit_name
        ctl_no = port[0]
        port_no = port[1]

        opt = '-unit %s -add %s %s -gno %d -gname %s' % (unit, ctl_no,
                                                         port_no, gid,
                                                         host_grp_name)
        ret, stdout, stderr = self.exec_hsnm('auhgdef', opt)
        if ret:
            raise exception.HBSDNotFound

    def comm_del_hostgrp(self, port, gid, host_grp_name):
        unit = self.unit_name
        ctl_no = port[0]
        port_no = port[1]
        opt = '-unit %s -rm %s %s -gname %s' % (unit, ctl_no, port_no,
                                                host_grp_name)
        ret, stdout, stderr = self.exec_hsnm('auhgdef', opt)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='auhgdef', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_add_hbawwn(self, port, gid, wwn):
        unit = self.unit_name
        ctl_no = port[0]
        port_no = port[1]
        opt = '-unit %s -set -permhg %s %s %s -gno %d' % (unit, ctl_no,
                                                          port_no, wwn, gid)
        ret, stdout, stderr = self.exec_hsnm('auhgwwn', opt)
        if ret:
            opt = '-unit %s -assign -permhg %s %s %s -gno %d' % (unit, ctl_no,
                                                                 port_no, wwn,
                                                                 gid)
            ret, stdout, stderr = self.exec_hsnm('auhgwwn', opt)
            if ret:
                msg = basic_lib.output_err(
                    600, cmd='auhgwwn', ret=ret, out=stdout, err=stderr)
                raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_add_lun(self, command, hostgroups, ldev, is_once=False):
        unit = self.unit_name
        tmp_hostgroups = hostgroups[:]
        used_list = []
        is_ok = False
        hlu = None
        old_hlu = None
        for hostgroup in hostgroups:
            port = hostgroup['port']
            gid = hostgroup['gid']
            hlu = self.add_used_hlun(command, port, gid, used_list, ldev)
            # When 'hlu' or 'old_hlu' is 0, it should be true.
            # So, it cannot remove 'is not None'.
            if hlu is not None:
                if old_hlu is not None and old_hlu != hlu:
                    msg = basic_lib.output_err(648, resource='LUN (HLUN)')
                    raise exception.HBSDError(message=msg)
                is_ok = True
                hostgroup['lun'] = hlu
                tmp_hostgroups.remove(hostgroup)
                old_hlu = hlu
            else:
                hlu = old_hlu

        if not used_list:
            hlu = 0
        elif hlu is None:
            for i in range(MAX_HLUN + 1):
                if i not in used_list:
                    hlu = i
                    break
            else:
                raise exception.HBSDNotFound

        ret = 0
        stdout = None
        stderr = None
        invalid_hgs_str = None
        for hostgroup in tmp_hostgroups:
            port = hostgroup['port']
            gid = hostgroup['gid']
            ctl_no = port[0]
            port_no = port[1]
            if not hostgroup['detected']:
                if invalid_hgs_str:
                    invalid_hgs_str = '%s, %s:%d' % (invalid_hgs_str,
                                                     port, gid)
                else:
                    invalid_hgs_str = '%s:%d' % (port, gid)
                continue
            opt = '-unit %s -add %s %s %d %d %d' % (unit, ctl_no, port_no,
                                                    gid, hlu, ldev)
            ret, stdout, stderr = self.exec_hsnm(command, opt)
            if ret == 0:
                is_ok = True
                hostgroup['lun'] = hlu
                if is_once:
                    break
            else:
                LOG.warning(basic_lib.set_msg(
                    314, ldev=ldev, lun=hlu, port=port, id=gid))

        if not is_ok:
            if stderr:
                msg = basic_lib.output_err(
                    600, cmd=command, ret=ret, out=stdout, err=stderr)
                raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
            else:
                msg = basic_lib.output_err(659, gid=invalid_hgs_str)
                raise exception.HBSDError(message=msg)

    def comm_delete_ldev(self, ldev, is_vvol):
        unit = self.unit_name

        if is_vvol:
            command = 'aureplicationvvol'
            opt = '-unit %s -rm -lu %d' % (unit, ldev)
        else:
            command = 'auludel'
            opt = '-unit %s -lu %d -f' % (unit, ldev)

        ret, stdout, stderr = self.exec_hsnm(command, opt,
                                             timeout=30, interval=3)
        if ret:
            if (re.search('DMEC002048', stderr)
                    or re.search('DMED090026', stderr)):
                raise exception.HBSDNotFound
            msg = basic_lib.output_err(
                600, cmd=command, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        return ret

    def comm_extend_ldev(self, ldev, old_size, new_size):
        unit = self.unit_name
        command = 'auluchgsize'
        options = '-unit %s -lu %d -size %dg' % (unit, ldev, new_size)

        ret, stdout, stderr = self.exec_hsnm(command, options)
        if ret:
            msg = basic_lib.output_err(
                600, cmd=command, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def delete_chap_user(self, port):
        unit = self.unit_name
        ctl_no = port[0]
        port_no = port[1]
        auth_username = self.conf.hitachi_auth_user

        opt = '-unit %s -rm %s %s -user %s' % (unit, ctl_no, port_no,
                                               auth_username)
        return self.exec_hsnm('auchapuser', opt)

    def _wait_for_add_chap_user(self, cmd, auth_username,
                                auth_password, start):
        # Don't move 'import pexpect' to the beginning of the file so that
        # a tempest can work.
        import pexpect

        lock = basic_lib.get_process_lock(self.hsnm_lock_file)
        with self.hsnm_lock, lock:
            try:
                child = pexpect.spawn(cmd)
                child.expect('Secret: ', timeout=CHAP_TIMEOUT)
                child.sendline(auth_password)
                child.expect('Re-enter Secret: ',
                             timeout=CHAP_TIMEOUT)
                child.sendline(auth_password)
                child.expect('The CHAP user information has '
                             'been added successfully.',
                             timeout=CHAP_TIMEOUT)
            except Exception:
                if time.time() - start >= EXEC_TIMEOUT:
                    msg = basic_lib.output_err(642, user=auth_username)
                    raise exception.HBSDError(message=msg)
            else:
                raise loopingcall.LoopingCallDone(True)

    def set_chap_authention(self, port, gid):
        ctl_no = port[0]
        port_no = port[1]
        unit = self.unit_name
        auth_username = self.conf.hitachi_auth_user
        auth_password = self.conf.hitachi_auth_password
        add_chap_user = self.conf.hitachi_add_chap_user
        assign_flag = True
        added_flag = False
        opt = '-unit %s -refer %s %s -user %s' % (unit, ctl_no, port_no,
                                                  auth_username)
        ret, stdout, stderr = self.exec_hsnm('auchapuser', opt, noretry=True)

        if ret:
            if not add_chap_user:
                msg = basic_lib.output_err(643, user=auth_username)
                raise exception.HBSDError(message=msg)

            root_helper = utils.get_root_helper()
            cmd = ('%s env %s auchapuser -unit %s -add %s %s '
                   '-tno %d -user %s' % (root_helper, SNM2_ENV, unit, ctl_no,
                                         port_no, gid, auth_username))

            LOG.debug('Add CHAP user')
            loop = loopingcall.FixedIntervalLoopingCall(
                self._wait_for_add_chap_user, cmd,
                auth_username, auth_password, time.time())

            added_flag = loop.start(interval=EXEC_INTERVAL).wait()

        else:
            lines = stdout.splitlines()[4:]
            for line in lines:
                if int(shlex.split(line)[0][0:3]) == gid:
                    assign_flag = False
                    break

        if assign_flag:
            opt = '-unit %s -assign %s %s -tno %d -user %s' % (unit, ctl_no,
                                                               port_no, gid,
                                                               auth_username)
            ret, stdout, stderr = self.exec_hsnm('auchapuser', opt)
            if ret:
                if added_flag:
                    _ret, _stdout, _stderr = self.delete_chap_user(port)
                    if _ret:
                        LOG.warning(basic_lib.set_msg(
                            303, user=auth_username))

                msg = basic_lib.output_err(
                    600, cmd='auchapuser', ret=ret, out=stdout, err=stderr)
                raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        return added_flag

    def comm_add_hostgrp_iscsi(self, port, gid, target_alias, target_iqn):
        auth_method = self.conf.hitachi_auth_method
        unit = self.unit_name
        ctl_no = port[0]
        port_no = port[1]
        if auth_method:
            auth_arg = '-authmethod %s -mutual disable' % auth_method
        else:
            auth_arg = '-authmethod None'

        opt = '-unit %s -add %s %s -tno %d' % (unit, ctl_no, port_no, gid)
        opt = '%s -talias %s -iname %s %s' % (opt, target_alias, target_iqn,
                                              auth_arg)
        ret, stdout, stderr = self.exec_hsnm('autargetdef', opt)

        if ret:
            raise exception.HBSDNotFound

    def delete_iscsi_target(self, port, _target_no, target_alias):
        unit = self.unit_name
        ctl_no = port[0]
        port_no = port[1]
        opt = '-unit %s -rm %s %s -talias %s' % (unit, ctl_no, port_no,
                                                 target_alias)
        return self.exec_hsnm('autargetdef', opt)

    def comm_set_hostgrp_reportportal(self, port, target_alias):
        unit = self.unit_name
        ctl_no = port[0]
        port_no = port[1]
        opt = '-unit %s -set %s %s -talias %s' % (unit, ctl_no, port_no,
                                                  target_alias)
        opt = '%s -ReportFullPortalList enable' % opt
        ret, stdout, stderr = self.exec_hsnm('autargetopt', opt)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='autargetopt', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_add_initiator(self, port, gid, host_iqn):
        unit = self.unit_name
        ctl_no = port[0]
        port_no = port[1]
        opt = '-unit %s -add %s %s -tno %d -iname %s' % (unit, ctl_no,
                                                         port_no, gid,
                                                         host_iqn)
        ret, stdout, stderr = self.exec_hsnm('autargetini', opt)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='autargetini', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_get_hostgroup_info_iscsi(self, hgs, host_iqn, target_ports):
        unit = self.unit_name
        ret, stdout, stderr = self.exec_hsnm('autargetini',
                                             '-unit %s -refer' % unit)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='autargetini', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        security_ports = []
        lines = stdout.splitlines()
        hostgroups = []
        security = True
        for line in lines:
            if not shlex.split(line):
                continue
            if re.match('Port', line):
                line = shlex.split(line)
                port = line[1]
                security = True if line[4] == 'ON' else False
                continue

            if target_ports and port not in target_ports:
                continue

            if security:
                if (host_iqn in shlex.split(line[72:]) and
                        re.match(basic_lib.NAME_PREFIX,
                                 shlex.split(line)[0][4:])):
                    gid = int(shlex.split(line)[0][0:3])
                    hostgroups.append(
                        {'port': port, 'gid': gid, 'detected': True})
                    LOG.debug('Find port=%(port)s gid=%(gid)d',
                              {'port': port, 'gid': gid})
                if port not in security_ports:
                    security_ports.append(port)

        for hostgroup in hostgroups:
            hgs.append(hostgroup)

        return security_ports

    def comm_get_iscsi_ip(self, port):
        unit = self.unit_name
        ret, stdout, stderr = self.exec_hsnm('auiscsi',
                                             '-unit %s -refer' % unit)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='auiscsi', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        lines = stdout.splitlines()
        is_target_port = False
        for line in lines:
            line_array = shlex.split(line)
            if not line_array:
                continue
            if line_array[0] == 'Port' and line_array[1] != 'Number':
                if line_array[1] == port:
                    is_target_port = True
                else:
                    is_target_port = False
                continue
            if is_target_port and re.search('IPv4 Address', line):
                ip_addr = shlex.split(line)[3]
                break
            if is_target_port and re.search('Port Number', line):
                ip_port = shlex.split(line)[3]
        else:
            msg = basic_lib.output_err(651)
            raise exception.HBSDError(message=msg)

        return ip_addr, ip_port

    def comm_get_target_iqn(self, port, gid):
        unit = self.unit_name
        ret, stdout, stderr = self.exec_hsnm('autargetdef',
                                             '-unit %s -refer' % unit)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='autargetdef', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        is_target_host = False
        tmp_port = None
        lines = stdout.splitlines()
        for line in lines:
            line = shlex.split(line)
            if not line:
                continue

            if line[0] == "Port":
                tmp_port = line[1]
                continue

            if port != tmp_port:
                continue

            gid_tmp = line[0][0:3]
            if gid_tmp.isdigit() and int(gid_tmp) == gid:
                is_target_host = True
                continue
            if is_target_host and line[0] == "iSCSI":
                target_iqn = line[3]
                break
        else:
            msg = basic_lib.output_err(650, resource='IQN')
            raise exception.HBSDError(message=msg)

        return target_iqn

    def get_unused_gid_iscsi(self, group_range, port):
        start = group_range[0]
        end = min(group_range[1], MAX_HOSTGROUPS_ISCSI)
        unit = self.unit_name

        ret, stdout, stderr = self.exec_hsnm('autargetdef',
                                             '-unit %s -refer' % unit)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='autargetdef', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        used_list = []
        tmp_port = None
        lines = stdout.splitlines()
        for line in lines:
            line = shlex.split(line)
            if not line:
                continue

            if line[0] == "Port":
                tmp_port = line[1]
                continue

            if port != tmp_port:
                continue

            if line[0][0:3].isdigit():
                gid = int(line[0][0:3])
                if start <= gid <= end:
                    used_list.append(gid)
        if not used_list:
            return start

        for gid in range(start, end + 1):
            if gid not in used_list:
                break
        else:
            msg = basic_lib.output_err(648, resource='GID')
            raise exception.HBSDError(message=msg)

        return gid

    def get_gid_from_targetiqn(self, target_iqn, target_alias, port):
        unit = self.unit_name
        ret, stdout, stderr = self.exec_hsnm('autargetdef',
                                             '-unit %s -refer' % unit)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='autargetdef', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        gid = None
        tmp_port = None
        found_alias_full = False
        found_alias_part = False
        lines = stdout.splitlines()
        for line in lines:
            line = shlex.split(line)
            if not line:
                continue

            if line[0] == "Port":
                tmp_port = line[1]
                continue

            if port != tmp_port:
                continue

            if line[0][0:3].isdigit():
                tmp_gid = int(line[0][0:3])
                if re.match(basic_lib.NAME_PREFIX, line[0][4:]):
                    found_alias_part = True
                if line[0][4:] == target_alias:
                    found_alias_full = True
                continue

            if line[0] == "iSCSI":
                if line[3] == target_iqn:
                    gid = tmp_gid
                    break
                else:
                    found_alias_part = False

        if found_alias_full and gid is None:
            msg = basic_lib.output_err(641)
            raise exception.HBSDError(message=msg)

        # When 'gid' is 0, it should be true.
        # So, it cannot remove 'is not None'.
        if not found_alias_part and gid is not None:
            msg = basic_lib.output_err(641)
            raise exception.HBSDError(message=msg)

        return gid

    def comm_get_dp_pool(self, pool_id):
        unit = self.unit_name
        ret, stdout, stderr = self.exec_hsnm('audppool',
                                             '-unit %s -refer -g' % unit,
                                             printflag=False)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='audppool', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        lines = stdout.splitlines()
        for line in lines[2:]:
            tc_cc = re.search('\s(\d+\.\d) GB\s+(\d+\.\d) GB\s', line)
            pool_tmp = re.match('\s*\d+', line)
            if (pool_tmp and tc_cc
                    and int(pool_tmp.group(0)) == pool_id):
                total_gb = int(float(tc_cc.group(1)))
                free_gb = total_gb - int(float(tc_cc.group(2)))
                return total_gb, free_gb

        msg = basic_lib.output_err(640, pool_id=pool_id)
        raise exception.HBSDError(message=msg)

    def is_detected(self, port, wwn):
        hgs = []
        self.comm_get_hostgroup_info(hgs, [wwn], [port], login=True)
        return hgs[0]['detected']

    def pairoperate(self, opr, pvol, svol, is_vvol, args=None):
        unit = self.unit_name
        method = '-ss' if is_vvol else '-si'
        opt = '-unit %s -%s %s -pvol %d -svol %d' % (unit, opr, method,
                                                     pvol, svol)
        if args:
            opt = '%s %s' % (opt, args)
        ret, stdout, stderr = self.exec_hsnm('aureplicationlocal', opt)
        if ret:
            opt = '%s %s' % ('aureplicationlocal', opt)
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_create_pair(self, pvol, svol, is_vvol):
        if not is_vvol:
            args = '-compsplit -pace %s' % self.pace
            method = basic_lib.FULL
        else:
            pool = self.conf.hitachi_thin_pool_id
            args = ('-localrepdppoolno %d -localmngdppoolno %d '
                    '-compsplit -pace %s' % (pool, pool, self.pace))
            method = basic_lib.THIN
        try:
            self.pairoperate('create', pvol, svol, is_vvol, args=args)
        except exception.HBSDCmdError as ex:
            if (re.search('DMER0300B8', ex.stderr)
                    or re.search('DMER0800CF', ex.stderr)
                    or re.search('DMER0800D[0-6D]', ex.stderr)
                    or re.search('DMER03006A', ex.stderr)
                    or re.search('DMER030080', ex.stderr)):
                msg = basic_lib.output_err(615, copy_method=method, pvol=pvol)
                raise exception.HBSDBusy(message=msg)
            else:
                raise

    def _comm_pairevtwait(self, pvol, svol, is_vvol):
        unit = self.unit_name
        if not is_vvol:
            pairname = 'SI_LU%04d_LU%04d' % (pvol, svol)
            method = '-si'
        else:
            pairname = 'SS_LU%04d_LU%04d' % (pvol, svol)
            method = '-ss'
        opt = ('-unit %s -evwait %s -pairname %s -gname Ungrouped -nowait' %
               (unit, method, pairname))
        ret, stdout, stderr = self.exec_hsnm('aureplicationmon',
                                             opt, noretry=True)

        return ret

    def _wait_for_pair_status(self, pvol, svol, is_vvol,
                              status, timeout, start):
        if self._comm_pairevtwait(pvol, svol, is_vvol) in status:
            raise loopingcall.LoopingCallDone()

        if time.time() - start >= timeout:
            msg = basic_lib.output_err(
                637, method='_wait_for_pair_status', timeout=timeout)
            raise exception.HBSDError(message=msg)

    def comm_pairevtwait(self, pvol, svol, is_vvol, status, timeout, interval):
        loop = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_pair_status, pvol, svol, is_vvol,
            status, timeout, time.time())

        loop.start(interval=interval).wait()

    def delete_pair(self, pvol, svol, is_vvol):
        self.pairoperate('simplex', pvol, svol, is_vvol)

    def trans_status_hsnm2raid(self, str):
        status = None
        obj = re.search('Split\((.*)%\)', str)
        if obj:
            status = basic_lib.PSUS
        obj = re.search('Paired\((.*)%\)', str)
        if obj:
            status = basic_lib.PAIR
        return status

    def get_paired_info(self, ldev, only_flag=False):
        opt_base = '-unit %s -refer' % self.unit_name
        if only_flag:
            opt_base = '%s -ss' % opt_base

        opt = '%s -pvol %d' % (opt_base, ldev)
        ret, stdout, stderr = self.exec_hsnm('aureplicationlocal',
                                             opt, noretry=True)
        if ret == 0:
            lines = stdout.splitlines()
            pair_info = {'pvol': ldev, 'svol': []}
            for line in lines[1:]:
                status = self.trans_status_hsnm2raid(line)
                if re.search('SnapShot', line[100:]):
                    is_vvol = True
                else:
                    is_vvol = False
                line = shlex.split(line)
                if not line:
                    break
                svol = int(line[2])
                pair_info['svol'].append({'lun': svol,
                                          'status': status,
                                          'is_vvol': is_vvol})
            return pair_info

        opt = '%s -svol %d' % (opt_base, ldev)
        ret, stdout, stderr = self.exec_hsnm('aureplicationlocal',
                                             opt, noretry=True)
        if ret == 1:
            return {'pvol': None, 'svol': []}
        lines = stdout.splitlines()
        status = self.trans_status_hsnm2raid(lines[1])
        if re.search('SnapShot', lines[1][100:]):
            is_vvol = True
        else:
            is_vvol = False
        line = shlex.split(lines[1])
        pvol = int(line[1])

        return {'pvol': pvol, 'svol': [{'lun': ldev,
                                        'status': status,
                                        'is_vvol': is_vvol}]}

    def create_lock_file(self):
        basic_lib.create_empty_file(self.hsnm_lock_file)

    def get_hostgroup_luns(self, port, gid):
        list = []
        self.add_used_hlun('auhgmap', port, gid, list, DUMMY_LU)

        return list

    def get_ldev_size_in_gigabyte(self, ldev, existing_ref):
        param = 'unit_name'
        if param not in existing_ref:
            msg = basic_lib.output_err(700, param=param)
            raise exception.HBSDError(data=msg)
        storage = existing_ref.get(param)
        if storage != self.conf.hitachi_unit_name:
            msg = basic_lib.output_err(648, resource=param)
            raise exception.HBSDError(data=msg)

        try:
            stdout = self._get_lu(ldev)
        except exception.HBSDError:
            with excutils.save_and_reraise_exception():
                basic_lib.output_err(648, resource='LDEV')

        lines = stdout.splitlines()
        line = lines[2]

        splits = shlex.split(line)

        vol_type = splits[len(splits) - 1]
        if basic_lib.NORMAL_VOLUME_TYPE != vol_type:
            msg = basic_lib.output_err(702, ldev=ldev)
            raise exception.HBSDError(data=msg)

        dppool = splits[5]
        if 'N/A' == dppool:
            msg = basic_lib.output_err(702, ldev=ldev)
            raise exception.HBSDError(data=msg)

        # Hitachi storage calculates volume sizes in a block unit, 512 bytes.
        # So, units.Gi is divided by 512.
        size = int(splits[1])
        if size % (units.Gi / 512):
            msg = basic_lib.output_err(703, ldev=ldev)
            raise exception.HBSDError(data=msg)

        num_port = int(splits[len(splits) - 2])
        if num_port:
            msg = basic_lib.output_err(704, ldev=ldev)
            raise exception.HBSDError(data=msg)

        return size / (units.Gi / 512)
