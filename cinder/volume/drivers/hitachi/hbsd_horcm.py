# Copyright (C) 2014, 2015, Hitachi, Ltd.
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

import functools
import os
import re
import shlex
import threading
import time

from oslo_concurrency import processutils as putils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _LE, _LI, _LW
from cinder import utils
from cinder.volume.drivers.hitachi import hbsd_basiclib as basic_lib

GETSTORAGEARRAY_ONCE = 100
MAX_SNAPSHOT_COUNT = 1021
SNAP_LAST_PATH_SSB = '0xB958,0x020A'
HOST_IO_SSB = '0xB958,0x0233'
INVALID_LUN_SSB = '0x2E20,0x0000'
INTERCEPT_LDEV_SSB = '0x2E22,0x0001'
HOSTGROUP_INSTALLED = '0xB956,0x3173'
RESOURCE_LOCKED = 'SSB=0x2E11,0x2205'

LDEV_STATUS_WAITTIME = 120
LUN_DELETE_WAITTIME = basic_lib.DEFAULT_PROCESS_WAITTIME
LUN_DELETE_INTERVAL = 3
EXEC_MAX_WAITTIME = 30
EXEC_RETRY_INTERVAL = 5
HORCM_WAITTIME = 1
PAIR_TYPE = ('HORC', 'MRCF', 'QS')
PERMITTED_TYPE = ('CVS', 'HDP', 'HDT')

RAIDCOM_LOCK_FILE = basic_lib.LOCK_DIR + 'raidcom_'
HORCMGR_LOCK_FILE = basic_lib.LOCK_DIR + 'horcmgr_'
RESOURCE_LOCK_FILE = basic_lib.LOCK_DIR + 'raidcom_resource_'

STATUS_TABLE = {
    'SMPL': basic_lib.SMPL,
    'COPY': basic_lib.COPY,
    'RCPY': basic_lib.COPY,
    'PAIR': basic_lib.PAIR,
    'PFUL': basic_lib.PAIR,
    'PSUS': basic_lib.PSUS,
    'PFUS': basic_lib.PSUS,
    'SSUS': basic_lib.PSUS,
    'PSUE': basic_lib.PSUE,
}
NOT_SET = '-'
HORCM_RUNNING = 1
COPY_GROUP = basic_lib.NAME_PREFIX + '%s%s%03X%d'
SNAP_NAME = basic_lib.NAME_PREFIX + 'snap'
LDEV_NAME = basic_lib.NAME_PREFIX + 'ldev-%d-%d'
MAX_MUNS = 3

EX_ENAUTH = 202
EX_ENOOBJ = 205
EX_CMDRJE = 221
EX_CMDIOE = 237
EX_INVCMD = 240
EX_INVMOD = 241
EX_ENODEV = 246
EX_ENOENT = 247
EX_OPTINV = 248
EX_ATTDBG = 250
EX_ATTHOR = 251
EX_COMERR = 255
EX_UNKOWN = -1

NO_SUCH_DEVICE = (EX_ENODEV, EX_ENOENT)

COMMAND_IO_TO_RAID = (EX_CMDRJE, EX_CMDIOE, EX_INVCMD, EX_INVMOD, EX_OPTINV)

HORCM_ERROR = (EX_ATTDBG, EX_ATTHOR, EX_COMERR)

MAX_HOSTGROUPS = 254
MAX_HLUN = 2047

DEFAULT_PORT_BASE = 31000

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('hitachi_horcm_numbers',
               default='200,201',
               help='Instance numbers for HORCM'),
    cfg.StrOpt('hitachi_horcm_user',
               help='Username of storage system for HORCM'),
    cfg.StrOpt('hitachi_horcm_password',
               help='Password of storage system for HORCM',
               secret=True),
    cfg.BoolOpt('hitachi_horcm_add_conf',
                default=True,
                help='Add to HORCM configuration'),
    cfg.IntOpt('hitachi_horcm_resource_lock_timeout',
               default=600,
               help='Timeout until a resource lock is released, in seconds. '
                    'The value must be between 0 and 7200.'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


def horcm_synchronized(function):
    @functools.wraps(function)
    def wrapper(*args, **kargs):
        if len(args) == 1:
            inst = args[0].conf.hitachi_horcm_numbers[0]
            raidcom_obj_lock = args[0].raidcom_lock
        else:
            inst = args[1]
            raidcom_obj_lock = args[0].raidcom_pair_lock
        raidcom_lock_file = '%s%d' % (RAIDCOM_LOCK_FILE, inst)
        lock = basic_lib.get_process_lock(raidcom_lock_file)
        with raidcom_obj_lock, lock:
            return function(*args, **kargs)
    return wrapper


def storage_synchronized(function):
    @functools.wraps(function)
    def wrapper(*args, **kargs):
        serial = args[0].conf.hitachi_serial_number
        resource_lock = args[0].resource_lock
        resource_lock_file = '%s%s' % (RESOURCE_LOCK_FILE, serial)
        lock = basic_lib.get_process_lock(resource_lock_file)
        with resource_lock, lock:
            return function(*args, **kargs)
    return wrapper


class HBSDHORCM(basic_lib.HBSDBasicLib):

    def __init__(self, conf):
        super(HBSDHORCM, self).__init__(conf=conf)

        self.copy_groups = [None] * MAX_MUNS
        self.raidcom_lock = threading.Lock()
        self.raidcom_pair_lock = threading.Lock()
        self.horcmgr_lock = threading.Lock()
        self.horcmgr_flock = None
        self.resource_lock = threading.Lock()

    def check_param(self):
        numbers = self.conf.hitachi_horcm_numbers.split(',')
        if len(numbers) != 2:
            msg = basic_lib.output_err(601, param='hitachi_horcm_numbers')
            raise exception.HBSDError(message=msg)
        for i in numbers:
            if not i.isdigit():
                msg = basic_lib.output_err(601, param='hitachi_horcm_numbers')
                raise exception.HBSDError(message=msg)
        self.conf.hitachi_horcm_numbers = [int(num) for num in numbers]
        inst = self.conf.hitachi_horcm_numbers[0]
        pair_inst = self.conf.hitachi_horcm_numbers[1]
        if inst == pair_inst:
            msg = basic_lib.output_err(601, param='hitachi_horcm_numbers')
            raise exception.HBSDError(message=msg)
        for param in ('hitachi_horcm_user', 'hitachi_horcm_password'):
            if not getattr(self.conf, param):
                msg = basic_lib.output_err(601, param=param)
                raise exception.HBSDError(message=msg)
        if self.conf.hitachi_thin_pool_id == self.conf.hitachi_pool_id:
            msg = basic_lib.output_err(601, param='hitachi_thin_pool_id')
            raise exception.HBSDError(message=msg)
        resource_lock_timeout = self.conf.hitachi_horcm_resource_lock_timeout
        if not ((resource_lock_timeout >= 0) and
                (resource_lock_timeout <= 7200)):
            msg = basic_lib.output_err(
                601, param='hitachi_horcm_resource_lock_timeout')
            raise exception.HBSDError(message=msg)
        for opt in volume_opts:
            getattr(self.conf, opt.name)

    def set_copy_groups(self, host_ip):
        serial = self.conf.hitachi_serial_number
        inst = self.conf.hitachi_horcm_numbers[1]

        for mun in range(MAX_MUNS):
            copy_group = COPY_GROUP % (host_ip, serial, inst, mun)
            self.copy_groups[mun] = copy_group

    def set_pair_flock(self):
        inst = self.conf.hitachi_horcm_numbers[1]
        name = '%s%d' % (HORCMGR_LOCK_FILE, inst)
        self.horcmgr_flock = basic_lib.FileLock(name, self.horcmgr_lock)
        return self.horcmgr_flock

    def check_horcm(self, inst):
        args = 'HORCMINST=%d horcmgr -check' % inst
        ret, _stdout, _stderr = self.exec_command('env', args=args,
                                                  printflag=False)
        return ret

    def shutdown_horcm(self, inst):
        ret, stdout, stderr = self.exec_command(
            'horcmshutdown.sh', args=six.text_type(inst), printflag=False)
        return ret

    def start_horcm(self, inst):
        return self.exec_command('horcmstart.sh', args=six.text_type(inst),
                                 printflag=False)

    def _wait_for_horcm_shutdown(self, inst):
        if self.check_horcm(inst) != HORCM_RUNNING:
            raise loopingcall.LoopingCallDone()

        if self.shutdown_horcm(inst):
            LOG.error(_LE("Failed to shutdown horcm."))
            raise loopingcall.LoopingCallDone()

    @horcm_synchronized
    def restart_horcm(self, inst=None):
        if inst is None:
            inst = self.conf.hitachi_horcm_numbers[0]

        loop = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_horcm_shutdown, inst)

        loop.start(interval=HORCM_WAITTIME).wait()

        ret, stdout, stderr = self.start_horcm(inst)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='horcmstart.sh', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def restart_pair_horcm(self):
        inst = self.conf.hitachi_horcm_numbers[1]
        self.restart_horcm(inst=inst)

    def setup_horcmgr(self, host_ip):
        pair_inst = self.conf.hitachi_horcm_numbers[1]
        self.set_copy_groups(host_ip)
        if self.conf.hitachi_horcm_add_conf:
            self.create_horcmconf()
            self.create_horcmconf(inst=pair_inst)
        self.restart_horcm()
        with self.horcmgr_flock:
            self.restart_pair_horcm()
        ret, stdout, stderr = self.comm_login()
        if ret:
            msg = basic_lib.output_err(
                600, cmd='raidcom -login', ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def _wait_for_exec_horcm(self, cmd, args, printflag, start):
        if cmd == 'raidcom':
            serial = self.conf.hitachi_serial_number
            inst = self.conf.hitachi_horcm_numbers[0]
            raidcom_obj_lock = self.raidcom_lock
            args = '%s -s %s -I%d' % (args, serial, inst)
        else:
            inst = self.conf.hitachi_horcm_numbers[1]
            raidcom_obj_lock = self.raidcom_pair_lock
            args = '%s -ISI%d' % (args, inst)
        user = self.conf.hitachi_horcm_user
        passwd = self.conf.hitachi_horcm_password
        raidcom_lock_file = '%s%d' % (RAIDCOM_LOCK_FILE, inst)
        lock = basic_lib.get_process_lock(raidcom_lock_file)

        with raidcom_obj_lock, lock:
            ret, stdout, stderr = self.exec_command(cmd, args=args,
                                                    printflag=printflag)

        # The resource group may be locked by other software.
        # Therefore, wait until the lock is released.
        if (RESOURCE_LOCKED in stderr and
            (time.time() - start <
             self.conf.hitachi_horcm_resource_lock_timeout)):
            return

        if not ret or ret <= 127:
            raise loopingcall.LoopingCallDone((ret, stdout, stderr))

        if time.time() - start >= EXEC_MAX_WAITTIME:
            LOG.error(_LE("horcm command timeout."))
            raise loopingcall.LoopingCallDone((ret, stdout, stderr))

        if (ret == EX_ENAUTH and
                not re.search("-login %s %s" % (user, passwd), args)):
            _ret, _stdout, _stderr = self.comm_login()
            if _ret:
                LOG.error(_LE("Failed to authenticate user."))
                raise loopingcall.LoopingCallDone((ret, stdout, stderr))

        elif ret in HORCM_ERROR:
            _ret = 0
            with raidcom_obj_lock, lock:
                if self.check_horcm(inst) != HORCM_RUNNING:
                    _ret, _stdout, _stderr = self.start_horcm(inst)
            if _ret and _ret != HORCM_RUNNING:
                LOG.error(_LE("Failed to start horcm."))
                raise loopingcall.LoopingCallDone((ret, stdout, stderr))

        elif ret not in COMMAND_IO_TO_RAID:
            LOG.error(_LE("Unexpected error occurs in horcm."))
            raise loopingcall.LoopingCallDone((ret, stdout, stderr))

    def exec_raidcom(self, cmd, args, printflag=True):
        loop = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_exec_horcm, cmd, args, printflag, time.time())

        return loop.start(interval=EXEC_RETRY_INTERVAL).wait()

    def comm_login(self):
        rmi_user = self.conf.hitachi_horcm_user
        rmi_pass = self.conf.hitachi_horcm_password
        args = '-login %s %s' % (rmi_user, rmi_pass)
        return self.exec_raidcom('raidcom', args, printflag=False)

    def comm_reset_status(self):
        self.exec_raidcom('raidcom', 'reset command_status')

    def comm_get_status(self):
        return self.exec_raidcom('raidcom', 'get command_status')

    def get_command_error(self, stdout):
        lines = stdout.splitlines()
        line = shlex.split(lines[1])
        return int(line[3])

    def comm_get_ldev(self, ldev):
        opt = 'get ldev -ldev_id %s' % ldev
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        return stdout

    def add_used_hlun(self, port, gid, used_list):
        opt = 'get lun -port %s-%d' % (port, gid)
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        lines = stdout.splitlines()
        for line in lines[1:]:
            lun = int(shlex.split(line)[3])
            if lun not in used_list:
                used_list.append(lun)

    def get_unused_ldev(self, ldev_range):
        start = ldev_range[0]
        end = ldev_range[1]

        while start < end:
            if end - start + 1 > GETSTORAGEARRAY_ONCE:
                cnt = GETSTORAGEARRAY_ONCE
            else:
                cnt = end - start + 1
            opt = 'get ldev -ldev_id %d -cnt %d' % (start, cnt)
            ret, stdout, stderr = self.exec_raidcom('raidcom', opt,
                                                    printflag=False)
            if ret:
                opt = 'raidcom %s' % opt
                msg = basic_lib.output_err(
                    600, cmd=opt, ret=ret, out=stdout, err=stderr)
                raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

            lines = stdout.splitlines()
            ldev_num = None
            for line in lines:
                if re.match("LDEV :", line):
                    ldev_num = int(shlex.split(line)[2])
                    continue
                if re.match("VOL_TYPE : NOT DEFINED", line):
                    return ldev_num

            start += GETSTORAGEARRAY_ONCE
        else:
            msg = basic_lib.output_err(648, resource='LDEV')
            raise exception.HBSDError(message=msg)

    def get_hgname_gid(self, port, host_grp_name):
        opt = 'get host_grp -port %s -key host_grp' % port
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        lines = stdout.splitlines()
        for line in lines[1:]:
            line = shlex.split(line)
            if line[2] == host_grp_name:
                return int(line[1])
        return None

    def get_unused_gid(self, range, port):
        _min = range[0]
        _max = range[1]
        opt = 'get host_grp -port %s -key host_grp' % port
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        lines = stdout.splitlines()
        free_gid = None
        for line in lines[_min + 1:]:
            line = shlex.split(line)
            if int(line[1]) > _max:
                break
            if line[2] == '-':
                free_gid = int(line[1])
                break
        if free_gid is None:
            msg = basic_lib.output_err(648, resource='GID')
            raise exception.HBSDError(message=msg)
        return free_gid

    def comm_set_target_wwns(self, target_ports):
        opt = 'get port'
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        target_wwns = {}
        lines = stdout.splitlines()
        for line in lines[1:]:
            line = shlex.split(line)
            port = line[0][:5]
            if target_ports and port not in target_ports:
                continue

            target_wwns[port] = line[10]
        LOG.debug('target wwns: %s', target_wwns)
        return target_wwns

    def comm_get_hbawwn(self, hostgroups, wwns, port, is_detected):
        opt = 'get host_grp -port %s' % port
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        lines = stdout.splitlines()
        found_wwns = 0
        for line in lines[1:]:
            line = shlex.split(line)
            if not re.match(basic_lib.NAME_PREFIX, line[2]):
                continue
            gid = line[1]
            opt = 'get hba_wwn -port %s-%s' % (port, gid)
            ret, stdout, stderr = self.exec_raidcom(
                'raidcom', opt, printflag=False)
            if ret:
                opt = 'raidcom %s' % opt
                msg = basic_lib.output_err(
                    600, cmd=opt, ret=ret, out=stdout, err=stderr)
                raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

            lines = stdout.splitlines()
            for line in lines[1:]:
                hba_info = shlex.split(line)

                if hba_info[3] in wwns:
                    hostgroups.append({'port': six.text_type(port),
                                       'gid': int(hba_info[1]),
                                       'initiator_wwn': hba_info[3],
                                       'detected': is_detected})
                    found_wwns += 1
                if len(wwns) == found_wwns:
                    break

            if len(wwns) == found_wwns:
                break

    def comm_chk_login_wwn(self, wwns, port):
        opt = 'get port -port %s' % port
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt,
                                                printflag=False)

        if ret:
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        lines = stdout.splitlines()
        for line in lines[1:]:
            login_info = shlex.split(line)
            if login_info[1] in wwns:
                return True
        else:
            return False

    def comm_get_hostgroup_info(self, hgs, wwns, target_ports, login=True):
        security_ports = []
        hostgroups = []

        opt = 'get port'
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        lines = stdout.splitlines()

        for line in lines[1:]:
            line = shlex.split(line)
            port = line[0][:5]
            if target_ports and port not in target_ports:
                continue
            security = True if line[7] == 'Y' else False

            is_detected = None
            if login:
                is_detected = self.comm_chk_login_wwn(wwns, port)

            if security:
                self.comm_get_hbawwn(hostgroups, wwns, port, is_detected)
                security_ports.append(port)

        for hostgroup in hostgroups:
            hgs.append(hostgroup)

        return security_ports

    def _get_lun(self, port, gid, ldev):
        lun = None

        opt = 'get lun -port %s-%d' % (port, gid)
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        lines = stdout.splitlines()
        for line in lines[1:]:
            line = shlex.split(line)
            if line[5] == six.text_type(ldev):
                lun = int(line[3])
                break

        return lun

    def _wait_for_delete_lun(self, hostgroup, ldev, start):
        opt = 'delete lun -port %s-%d -ldev_id %d' % (hostgroup['port'],
                                                      hostgroup['gid'], ldev)
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt)
        if not ret:
            raise loopingcall.LoopingCallDone()

        if (re.search('SSB=%s' % SNAP_LAST_PATH_SSB, stderr) and
                not self.comm_get_snapshot(ldev) or
                re.search('SSB=%s' % HOST_IO_SSB, stderr)):
            LOG.warning(basic_lib.set_msg(310, ldev=ldev, reason=stderr))

            if time.time() - start >= LUN_DELETE_WAITTIME:
                msg = basic_lib.output_err(
                    637, method='_wait_for_delete_lun',
                    timeout=LUN_DELETE_WAITTIME)
                raise exception.HBSDError(message=msg)
        else:
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_delete_lun_core(self, hostgroup, ldev):
        loop = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_delete_lun, hostgroup, ldev, time.time())

        loop.start(interval=LUN_DELETE_INTERVAL).wait()

    def comm_delete_lun(self, hostgroups, ldev):
        deleted_hostgroups = []
        no_ldev_cnt = 0
        for hostgroup in hostgroups:
            port = hostgroup['port']
            gid = hostgroup['gid']
            is_deleted = False
            for deleted in deleted_hostgroups:
                if port == deleted['port'] and gid == deleted['gid']:
                    is_deleted = True
            if is_deleted:
                continue
            try:
                self.comm_delete_lun_core(hostgroup, ldev)
            except exception.HBSDCmdError as ex:
                no_ldev_cnt += 1
                if ex.ret == EX_ENOOBJ:
                    if no_ldev_cnt != len(hostgroups):
                        continue
                    raise exception.HBSDNotFound
                else:
                    raise
            deleted_hostgroups.append({'port': port, 'gid': gid})

    def _check_ldev_status(self, ldev, status):
        opt = ('get ldev -ldev_id %s -check_status %s -time %s' %
               (ldev, status, LDEV_STATUS_WAITTIME))
        ret, _stdout, _stderr = self.exec_raidcom('raidcom', opt)
        return ret

    # Don't remove a storage_syncronized decorator.
    # It is need to avoid comm_add_ldev() and comm_delete_ldev() are
    # executed concurrently.
    @storage_synchronized
    def comm_add_ldev(self, pool_id, ldev, capacity, is_vvol):
        emulation = 'OPEN-V'
        if is_vvol:
            opt = ('add ldev -pool snap -ldev_id %d '
                   '-capacity %dG -emulation %s'
                   % (ldev, capacity, emulation))
        else:
            opt = ('add ldev -pool %d -ldev_id %d '
                   '-capacity %dG -emulation %s'
                   % (pool_id, ldev, capacity, emulation))

        self.comm_reset_status()
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt)
        if ret:
            if re.search('SSB=%s' % INTERCEPT_LDEV_SSB, stderr):
                raise exception.HBSDNotFound

            msg = basic_lib.output_err(
                600, cmd='raidcom %s' % opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        if self._check_ldev_status(ldev, "NML"):
            msg = basic_lib.output_err(653, ldev=ldev)
            raise exception.HBSDError(message=msg)

    def comm_add_hostgrp(self, port, gid, host_grp_name):
        opt = 'add host_grp -port %s-%d -host_grp_name %s' % (port, gid,
                                                              host_grp_name)
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt)
        if ret:
            if re.search('SSB=%s' % HOSTGROUP_INSTALLED, stderr):
                raise exception.HBSDNotFound

            msg = basic_lib.output_err(
                600, cmd='raidcom %s' % opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_del_hostgrp(self, port, gid, host_grp_name):
        opt = 'delete host_grp -port %s-%d %s' % (port, gid, host_grp_name)
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='raidcom %s' % opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_add_hbawwn(self, port, gid, wwn):
        opt = 'add hba_wwn -port %s-%s -hba_wwn %s' % (port, gid, wwn)
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='raidcom %s' % opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    @storage_synchronized
    def comm_add_lun(self, unused_command, hostgroups, ldev, is_once=False):
        tmp_hostgroups = hostgroups[:]
        is_ok = False
        used_list = []
        lun = None
        old_lun = None

        for hostgroup in hostgroups:
            port = hostgroup['port']
            gid = hostgroup['gid']
            self.add_used_hlun(port, gid, used_list)
            lun = self._get_lun(port, gid, ldev)

            # When 'lun' or 'old_lun' is 0, it should be true.
            # So, it cannot remove 'is not None'.
            if lun is not None:
                if old_lun is not None and old_lun != lun:
                    msg = basic_lib.output_err(648, resource='LUN (HLUN)')
                    raise exception.HBSDError(message=msg)
                is_ok = True
                hostgroup['lun'] = lun
                tmp_hostgroups.remove(hostgroup)
                old_lun = lun

            if is_once:
                # When 'lun' is 0, it should be true.
                # So, it cannot remove 'is not None'.
                if lun is not None:
                    return
                elif len(used_list) < MAX_HLUN + 1:
                    break
                else:
                    tmp_hostgroups.remove(hostgroup)
                    if tmp_hostgroups:
                        used_list = []

        if not used_list:
            lun = 0
        elif lun is None:
            for i in range(MAX_HLUN + 1):
                if i not in used_list:
                    lun = i
                    break
            else:
                raise exception.HBSDNotFound

        opt = None
        ret = 0
        stdout = None
        stderr = None
        invalid_hgs_str = None

        for hostgroup in tmp_hostgroups:
            port = hostgroup['port']
            gid = hostgroup['gid']
            if not hostgroup['detected']:
                if invalid_hgs_str:
                    invalid_hgs_str = '%s, %s:%d' % (invalid_hgs_str,
                                                     port, gid)
                else:
                    invalid_hgs_str = '%s:%d' % (port, gid)
                continue
            opt = 'add lun -port %s-%d -ldev_id %d -lun_id %d' % (
                port, gid, ldev, lun)
            ret, stdout, stderr = self.exec_raidcom('raidcom', opt)
            if not ret:
                is_ok = True
                hostgroup['lun'] = lun
                if is_once:
                    break
            else:
                LOG.warning(basic_lib.set_msg(
                    314, ldev=ldev, lun=lun, port=port, id=gid))

        if not is_ok:
            if stderr:
                opt = 'raidcom %s' % opt
                msg = basic_lib.output_err(
                    600, cmd=opt, ret=ret, out=stdout, err=stderr)
                raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
            else:
                msg = basic_lib.output_err(659, gid=invalid_hgs_str)
                raise exception.HBSDError(message=msg)

    # Don't remove a storage_syncronized decorator.
    # It is need to avoid comm_add_ldev() and comm_delete_ldev() are
    # executed concurrently.
    @storage_synchronized
    def comm_delete_ldev(self, ldev, is_vvol):
        ret = -1
        stdout = ""
        stderr = ""
        self.comm_reset_status()
        opt = 'delete ldev -ldev_id %d' % ldev
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt)
        if ret:
            if re.search('SSB=%s' % INVALID_LUN_SSB, stderr):
                raise exception.HBSDNotFound

            msg = basic_lib.output_err(
                600, cmd='raidcom %s' % opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        ret, stdout, stderr = self.comm_get_status()
        if ret or self.get_command_error(stdout):
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_extend_ldev(self, ldev, old_size, new_size):
        extend_size = new_size - old_size
        opt = 'extend ldev -ldev_id %d -capacity %dG' % (ldev, extend_size)
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='raidcom %s' % opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_get_dp_pool(self, pool_id):
        opt = 'get dp_pool'
        ret, stdout, stderr = self.exec_raidcom('raidcom', opt,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % opt
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

        lines = stdout.splitlines()
        for line in lines[1:]:
            if int(shlex.split(line)[0]) == pool_id:
                free_gb = int(shlex.split(line)[3]) / 1024
                total_gb = int(shlex.split(line)[4]) / 1024
                return total_gb, free_gb

        msg = basic_lib.output_err(640, pool_id=pool_id)
        raise exception.HBSDError(message=msg)

    def comm_modify_ldev(self, ldev):
        args = 'modify ldev -ldev_id %d -status discard_zero_page' % ldev
        ret, stdout, stderr = self.exec_raidcom('raidcom', args)
        if ret:
            LOG.warning(basic_lib.set_msg(315, ldev=ldev, reason=stderr))

    def is_detected(self, port, wwn):
        return self.comm_chk_login_wwn([wwn], port)

    def discard_zero_page(self, ldev):
        try:
            self.comm_modify_ldev(ldev)
        except Exception as ex:
            LOG.warning(_LW('Failed to discard zero page: %s'), ex)

    def comm_add_snapshot(self, pvol, svol):
        pool = self.conf.hitachi_thin_pool_id
        copy_size = self.conf.hitachi_copy_speed
        args = ('add snapshot -ldev_id %d %d -pool %d '
                '-snapshot_name %s -copy_size %d'
                % (pvol, svol, pool, SNAP_NAME, copy_size))
        ret, stdout, stderr = self.exec_raidcom('raidcom', args)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='raidcom %s' % args, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_delete_snapshot(self, ldev):
        args = 'delete snapshot -ldev_id %d' % ldev
        ret, stdout, stderr = self.exec_raidcom('raidcom', args)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='raidcom %s' % args, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_modify_snapshot(self, ldev, op):
        args = ('modify snapshot -ldev_id %d -snapshot_data %s' % (ldev, op))
        ret, stdout, stderr = self.exec_raidcom('raidcom', args)
        if ret:
            msg = basic_lib.output_err(
                600, cmd='raidcom %s' % args, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def _wait_for_snap_status(self, pvol, svol, status, timeout, start):
        if (self.get_snap_pvol_status(pvol, svol) in status and
                self.get_snap_svol_status(svol) in status):
            raise loopingcall.LoopingCallDone()

        if time.time() - start >= timeout:
            msg = basic_lib.output_err(
                637, method='_wait_for_snap_status', timuout=timeout)
            raise exception.HBSDError(message=msg)

    def wait_snap(self, pvol, svol, status, timeout, interval):
        loop = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_snap_status, pvol,
            svol, status, timeout, time.time())

        loop.start(interval=interval).wait()

    def comm_get_snapshot(self, ldev):
        args = 'get snapshot -ldev_id %d' % ldev
        ret, stdout, stderr = self.exec_raidcom('raidcom', args,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % args
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        return stdout

    def check_snap_count(self, ldev):
        stdout = self.comm_get_snapshot(ldev)
        if not stdout:
            return
        lines = stdout.splitlines()
        if len(lines) >= MAX_SNAPSHOT_COUNT + 1:
            msg = basic_lib.output_err(
                615, copy_method=basic_lib.THIN, pvol=ldev)
            raise exception.HBSDBusy(message=msg)

    def get_snap_pvol_status(self, pvol, svol):
        stdout = self.comm_get_snapshot(pvol)
        if not stdout:
            return basic_lib.SMPL
        lines = stdout.splitlines()
        for line in lines[1:]:
            line = shlex.split(line)
            if int(line[6]) == svol:
                return STATUS_TABLE[line[2]]
        else:
            return basic_lib.SMPL

    def get_snap_svol_status(self, ldev):
        stdout = self.comm_get_snapshot(ldev)
        if not stdout:
            return basic_lib.SMPL
        lines = stdout.splitlines()
        line = shlex.split(lines[1])
        return STATUS_TABLE[line[2]]

    @horcm_synchronized
    def create_horcmconf(self, inst=None):
        if inst is None:
            inst = self.conf.hitachi_horcm_numbers[0]

        serial = self.conf.hitachi_serial_number
        filename = '/etc/horcm%d.conf' % inst

        port = DEFAULT_PORT_BASE + inst

        found = False

        if not os.path.exists(filename):
            file_str = """
HORCM_MON
#ip_address        service         poll(10ms)     timeout(10ms)
127.0.0.1 %16d               6000              3000
HORCM_CMD
""" % port
        else:
            file_str = utils.read_file_as_root(filename)

            lines = file_str.splitlines()
            for line in lines:
                if re.match(r'\\\\.\\CMD-%s:/dev/sd' % serial, line):
                    found = True
                    break

        if not found:
            insert_str = r'\\\\.\\CMD-%s:/dev/sd' % serial
            file_str = re.sub(r'(\n\bHORCM_CMD.*|^\bHORCM_CMD.*)',
                              r'\1\n%s\n' % insert_str, file_str)

            try:
                utils.execute('tee', filename, process_input=file_str,
                              run_as_root=True)
            except putils.ProcessExecutionError as ex:
                msg = basic_lib.output_err(
                    632, file=filename, ret=ex.exit_code, err=ex.stderr)
                raise exception.HBSDError(message=msg)

    def comm_get_copy_grp(self):
        ret, stdout, stderr = self.exec_raidcom('raidcom', 'get copy_grp',
                                                printflag=False)
        if ret:
            opt = 'raidcom get copy_grp'
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        return stdout

    def comm_add_copy_grp(self, copy_group, pvol_group, svol_group, mun):
        args = ('add copy_grp -copy_grp_name %s %s %s -mirror_id %d'
                % (copy_group, pvol_group, svol_group, mun))
        ret, stdout, stderr = self.exec_raidcom('raidcom', args,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % args
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_delete_copy_grp(self, copy_group):
        args = 'delete copy_grp -copy_grp_name %s' % copy_group
        ret, stdout, stderr = self.exec_raidcom('raidcom', args,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % args
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_get_device_grp(self, group_name):
        args = 'get device_grp -device_grp_name %s' % group_name
        ret, stdout, stderr = self.exec_raidcom('raidcom', args,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % args
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        return stdout

    def comm_add_device_grp(self, group_name, ldev_name, ldev):
        args = ('add device_grp -device_grp_name %s %s -ldev_id %d'
                % (group_name, ldev_name, ldev))
        ret, stdout, stderr = self.exec_raidcom('raidcom', args,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % args
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_delete_device_grp(self, group_name, ldev):
        args = ('delete device_grp -device_grp_name %s -ldev_id %d'
                % (group_name, ldev))
        ret, stdout, stderr = self.exec_raidcom('raidcom', args,
                                                printflag=False)
        if ret:
            opt = 'raidcom %s' % args
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_paircreate(self, copy_group, ldev_name):
        args = ('-g %s -d %s -split -fq quick -c %d -vl'
                % (copy_group, ldev_name, self.conf.hitachi_copy_speed))
        ret, stdout, stderr = self.exec_raidcom('paircreate', args)
        if ret:
            opt = 'paircreate %s' % args
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_pairsplit(self, copy_group, ldev_name):
        args = '-g %s -d %s -S' % (copy_group, ldev_name)
        ret, stdout, stderr = self.exec_raidcom('pairsplit', args)
        if ret:
            opt = 'pairsplit %s' % args
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)

    def comm_pairevtwait(self, copy_group, ldev_name, check_svol):
        if not check_svol:
            option = '-nowait'
        else:
            option = '-nowaits'
        args = '-g %s -d %s %s' % (copy_group, ldev_name, option)
        ret, stdout, stderr = self.exec_raidcom('pairevtwait', args,
                                                printflag=False)
        if ret > 127:
            opt = 'pairevtwait %s' % args
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        return ret

    def comm_pairdisplay(self, copy_group, ldev_name=None):
        if not ldev_name:
            args = '-g %s -CLI' % copy_group
        else:
            args = '-g %s -d %s -CLI' % (copy_group, ldev_name)
        ret, stdout, stderr = self.exec_raidcom('pairdisplay', args,
                                                printflag=False)
        if ret and ret not in NO_SUCH_DEVICE:
            opt = 'pairdisplay %s' % args
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        return ret, stdout, stderr

    def check_copy_grp(self, copy_group):
        stdout = self.comm_get_copy_grp()
        lines = stdout.splitlines()
        count = 0
        for line in lines[1:]:
            line = shlex.split(line)
            if line[0] == copy_group:
                count += 1
                if count == 2:
                    break
        return count

    def check_device_grp(self, group_name, ldev, ldev_name=None):
        stdout = self.comm_get_device_grp(group_name)
        lines = stdout.splitlines()
        for line in lines[1:]:
            line = shlex.split(line)
            if int(line[2]) == ldev:
                if not ldev_name:
                    return True
                else:
                    return line[1] == ldev_name
        else:
            return False

    def is_smpl(self, copy_group, ldev_name):
        ret, stdout, stderr = self.comm_pairdisplay(copy_group,
                                                    ldev_name=ldev_name)
        if not stdout:
            return True

        lines = stdout.splitlines()
        for line in lines[1:]:
            line = shlex.split(line)
            if line[9] in [NOT_SET, 'SMPL']:
                return True
        else:
            return False

    def get_copy_groups(self):
        copy_groups = []
        stdout = self.comm_get_copy_grp()
        lines = stdout.splitlines()
        for line in lines[1:]:
            line = shlex.split(line)
            if line[0] in self.copy_groups and line[0] not in copy_groups:
                copy_groups.append(line[0])
        return copy_groups

    def get_matched_copy_group(self, pvol, svol, ldev_name):
        for copy_group in self.get_copy_groups():
            pvol_group = '%sP' % copy_group
            if self.check_device_grp(pvol_group, pvol, ldev_name=ldev_name):
                return copy_group
        else:
            return None

    def get_paired_info(self, ldev, only_flag=False):
        paired_info = {'pvol': None, 'svol': []}
        pvol = None
        is_svol = False

        stdout = self.comm_get_snapshot(ldev)
        if stdout:
            lines = stdout.splitlines()
            line = shlex.split(lines[1])
            status = STATUS_TABLE.get(line[2], basic_lib.UNKN)

            if line[1] == 'P-VOL':
                pvol = ldev
                svol = int(line[6])
            else:
                is_svol = True
                pvol = int(line[6])
                svol = ldev

                if status == basic_lib.PSUS:
                    status = self.get_snap_pvol_status(pvol, svol)

            svol_info = {'lun': svol, 'status': status, 'is_vvol': True}
            paired_info['svol'].append(svol_info)
            paired_info['pvol'] = pvol

        if only_flag or is_svol:
            return paired_info

        for copy_group in self.get_copy_groups():
            ldev_name = None
            pvol_status = basic_lib.UNKN
            svol_status = basic_lib.UNKN

            ret, stdout, stderr = self.comm_pairdisplay(copy_group)
            if not stdout:
                continue

            lines = stdout.splitlines()
            for line in lines[1:]:
                line = shlex.split(line)
                if line[9] not in ['P-VOL', 'S-VOL']:
                    continue

                ldev0 = int(line[8])
                ldev1 = int(line[12])
                if ldev not in [ldev0, ldev1]:
                    continue

                ldev_name = line[1]

                if line[9] == 'P-VOL':
                    pvol = ldev0
                    svol = ldev1
                    pvol_status = STATUS_TABLE.get(line[10], basic_lib.UNKN)
                else:
                    svol = ldev0
                    pvol = ldev1
                    svol_status = STATUS_TABLE.get(line[10], basic_lib.UNKN)

                if svol == ldev:
                    is_svol = True

            if not ldev_name:
                continue

            pvol_group = '%sP' % copy_group
            pvol_ok = self.check_device_grp(pvol_group, pvol,
                                            ldev_name=ldev_name)

            svol_group = '%sS' % copy_group
            svol_ok = self.check_device_grp(svol_group, svol,
                                            ldev_name=ldev_name)

            if pvol_ok and svol_ok:
                if pvol_status == basic_lib.PSUS:
                    status = svol_status
                else:
                    status = pvol_status

                svol_info = {'lun': svol, 'status': status, 'is_vvol': False}
                paired_info['svol'].append(svol_info)

                if is_svol:
                    break

        # When 'pvol' is 0, it should be true.
        # So, it cannot remove 'is not None'.
        if pvol is not None and paired_info['pvol'] is None:
            paired_info['pvol'] = pvol

        return paired_info

    def add_pair_config(self, pvol, svol, copy_group, ldev_name, mun):
        pvol_group = '%sP' % copy_group
        svol_group = '%sS' % copy_group
        self.comm_add_device_grp(pvol_group, ldev_name, pvol)
        self.comm_add_device_grp(svol_group, ldev_name, svol)
        nr_copy_groups = self.check_copy_grp(copy_group)
        if nr_copy_groups == 1:
            self.comm_delete_copy_grp(copy_group)
        if nr_copy_groups != 2:
            self.comm_add_copy_grp(copy_group, pvol_group, svol_group, mun)

    def delete_pair_config(self, pvol, svol, copy_group, ldev_name):
        pvol_group = '%sP' % copy_group
        svol_group = '%sS' % copy_group
        if self.check_device_grp(pvol_group, pvol, ldev_name=ldev_name):
            self.comm_delete_device_grp(pvol_group, pvol)
        if self.check_device_grp(svol_group, svol, ldev_name=ldev_name):
            self.comm_delete_device_grp(svol_group, svol)

    def _wait_for_pair_status(self, copy_group, ldev_name,
                              status, timeout, check_svol, start):
        if self.comm_pairevtwait(copy_group, ldev_name,
                                 check_svol) in status:
            raise loopingcall.LoopingCallDone()

        if time.time() - start >= timeout:
            msg = basic_lib.output_err(
                637, method='_wait_for_pair_status', timout=timeout)
            raise exception.HBSDError(message=msg)

    def wait_pair(self, copy_group, ldev_name, status, timeout,
                  interval, check_svol=False):
        loop = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_pair_status, copy_group, ldev_name,
            status, timeout, check_svol, time.time())

        loop.start(interval=interval).wait()

    def comm_create_pair(self, pvol, svol, is_vvol):
        timeout = basic_lib.DEFAULT_PROCESS_WAITTIME
        interval = self.conf.hitachi_copy_check_interval
        if not is_vvol:
            restart = False
            create = False
            ldev_name = LDEV_NAME % (pvol, svol)
            mun = 0
            for mun in range(MAX_MUNS):
                copy_group = self.copy_groups[mun]
                pvol_group = '%sP' % copy_group

                if not self.check_device_grp(pvol_group, pvol):
                    break
            else:
                msg = basic_lib.output_err(
                    615, copy_method=basic_lib.FULL, pvol=pvol)
                raise exception.HBSDBusy(message=msg)
            try:
                self.add_pair_config(pvol, svol, copy_group, ldev_name, mun)
                self.restart_pair_horcm()
                restart = True
                self.comm_paircreate(copy_group, ldev_name)
                create = True
                self.wait_pair(copy_group, ldev_name, [basic_lib.PSUS],
                               timeout, interval)
                self.wait_pair(copy_group, ldev_name,
                               [basic_lib.PSUS, basic_lib.COPY],
                               timeout, interval, check_svol=True)
            except Exception:
                with excutils.save_and_reraise_exception():
                    if create:
                        try:
                            self.wait_pair(copy_group, ldev_name,
                                           [basic_lib.PSUS], timeout,
                                           interval)
                            self.wait_pair(copy_group, ldev_name,
                                           [basic_lib.PSUS], timeout,
                                           interval, check_svol=True)
                        except Exception as ex:
                            LOG.warning(_LW('Failed to create pair: %s'), ex)

                        try:
                            self.comm_pairsplit(copy_group, ldev_name)
                            self.wait_pair(
                                copy_group, ldev_name,
                                [basic_lib.SMPL], timeout,
                                self.conf.hitachi_async_copy_check_interval)
                        except Exception as ex:
                            LOG.warning(_LW('Failed to create pair: %s'), ex)

                    if self.is_smpl(copy_group, ldev_name):
                        try:
                            self.delete_pair_config(pvol, svol, copy_group,
                                                    ldev_name)
                        except Exception as ex:
                            LOG.warning(_LW('Failed to create pair: %s'), ex)

                    if restart:
                        try:
                            self.restart_pair_horcm()
                        except Exception as ex:
                            LOG.warning(_LW('Failed to restart horcm: %s'), ex)

        else:
            self.check_snap_count(pvol)
            self.comm_add_snapshot(pvol, svol)

            try:
                self.wait_snap(pvol, svol, [basic_lib.PAIR], timeout, interval)
                self.comm_modify_snapshot(svol, 'create')
                self.wait_snap(pvol, svol, [basic_lib.PSUS], timeout, interval)
            except Exception:
                with excutils.save_and_reraise_exception():
                    try:
                        self.comm_delete_snapshot(svol)
                        self.wait_snap(
                            pvol, svol, [basic_lib.SMPL], timeout,
                            self.conf.hitachi_async_copy_check_interval)
                    except Exception as ex:
                        LOG.warning(_LW('Failed to create pair: %s'), ex)

    def delete_pair(self, pvol, svol, is_vvol):
        timeout = basic_lib.DEFAULT_PROCESS_WAITTIME
        interval = self.conf.hitachi_async_copy_check_interval
        if not is_vvol:
            ldev_name = LDEV_NAME % (pvol, svol)
            copy_group = self.get_matched_copy_group(pvol, svol, ldev_name)
            if not copy_group:
                return
            try:
                self.comm_pairsplit(copy_group, ldev_name)
                self.wait_pair(copy_group, ldev_name, [basic_lib.SMPL],
                               timeout, interval)
            finally:
                if self.is_smpl(copy_group, ldev_name):
                    self.delete_pair_config(pvol, svol, copy_group, ldev_name)
        else:
            self.comm_delete_snapshot(svol)
            self.wait_snap(pvol, svol, [basic_lib.SMPL], timeout, interval)

    def comm_raidqry(self):
        ret, stdout, stderr = self.exec_command('raidqry', '-h')
        if ret:
            opt = 'raidqry -h'
            msg = basic_lib.output_err(
                600, cmd=opt, ret=ret, out=stdout, err=stderr)
            raise exception.HBSDCmdError(message=msg, ret=ret, err=stderr)
        return stdout

    def get_comm_version(self):
        stdout = self.comm_raidqry()
        lines = stdout.splitlines()
        return shlex.split(lines[1])[1]

    def output_param_to_log(self, conf):
        for opt in volume_opts:
            if not opt.secret:
                value = getattr(conf, opt.name)
                LOG.info(_LI('\t%(name)-35s : %(value)s'),
                         {'name': opt.name, 'value': value})

    def create_lock_file(self):
        inst = self.conf.hitachi_horcm_numbers[0]
        pair_inst = self.conf.hitachi_horcm_numbers[1]
        serial = self.conf.hitachi_serial_number
        raidcom_lock_file = '%s%d' % (RAIDCOM_LOCK_FILE, inst)
        raidcom_pair_lock_file = '%s%d' % (RAIDCOM_LOCK_FILE, pair_inst)
        horcmgr_lock_file = '%s%d' % (HORCMGR_LOCK_FILE, pair_inst)
        resource_lock_file = '%s%s' % (RESOURCE_LOCK_FILE, serial)

        basic_lib.create_empty_file(raidcom_lock_file)
        basic_lib.create_empty_file(raidcom_pair_lock_file)
        basic_lib.create_empty_file(horcmgr_lock_file)
        basic_lib.create_empty_file(resource_lock_file)

    def connect_storage(self):
        properties = utils.brick_get_connector_properties()
        self.setup_horcmgr(properties['ip'])

    def get_max_hostgroups(self):
        """return the maximum value of hostgroup id."""
        return MAX_HOSTGROUPS

    def get_hostgroup_luns(self, port, gid):
        list = []
        self.add_used_hlun(port, gid, list)

        return list

    def get_ldev_size_in_gigabyte(self, ldev, existing_ref):
        param = 'serial_number'

        if param not in existing_ref:
            msg = basic_lib.output_err(700, param=param)
            raise exception.HBSDError(data=msg)

        storage = existing_ref.get(param)
        if storage != self.conf.hitachi_serial_number:
            msg = basic_lib.output_err(648, resource=param)
            raise exception.HBSDError(data=msg)

        stdout = self.comm_get_ldev(ldev)
        if not stdout:
            msg = basic_lib.output_err(648, resource='LDEV')
            raise exception.HBSDError(data=msg)

        sts_line = vol_type = ""
        vol_attrs = []
        size = num_port = 1

        lines = stdout.splitlines()
        for line in lines:
            if line.startswith("STS :"):
                sts_line = line

            elif line.startswith("VOL_TYPE :"):
                vol_type = shlex.split(line)[2]

            elif line.startswith("VOL_ATTR :"):
                vol_attrs = shlex.split(line)[2:]

            elif line.startswith("VOL_Capacity(BLK) :"):
                size = int(shlex.split(line)[2])

            elif line.startswith("NUM_PORT :"):
                num_port = int(shlex.split(line)[2])

        if 'NML' not in sts_line:
            msg = basic_lib.output_err(648, resource='LDEV')

            raise exception.HBSDError(data=msg)

        if 'OPEN-V' not in vol_type:
            msg = basic_lib.output_err(702, ldev=ldev)
            raise exception.HBSDError(data=msg)

        if 'HDP' not in vol_attrs:
            msg = basic_lib.output_err(702, ldev=ldev)
            raise exception.HBSDError(data=msg)

        for vol_attr in vol_attrs:
            if vol_attr == ':':
                continue

            if vol_attr in PAIR_TYPE:
                msg = basic_lib.output_err(705, ldev=ldev)
                raise exception.HBSDError(data=msg)

            if vol_attr not in PERMITTED_TYPE:
                msg = basic_lib.output_err(702, ldev=ldev)
                raise exception.HBSDError(data=msg)

        # Hitachi storage calculates volume sizes in a block unit, 512 bytes.
        # So, units.Gi is divided by 512.
        if size % (units.Gi / 512):
            msg = basic_lib.output_err(703, ldev=ldev)
            raise exception.HBSDError(data=msg)

        if num_port:
            msg = basic_lib.output_err(704, ldev=ldev)
            raise exception.HBSDError(data=msg)

        return size / (units.Gi / 512)
