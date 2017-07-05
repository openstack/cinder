# Copyright (C) 2016, Hitachi, Ltd.
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
"""HORCM interface module for Hitachi VSP Driver."""

import functools
import math
import os
import re

from oslo_config import cfg
from oslo_config import types
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import timeutils
from oslo_utils import units
import six
from six.moves import range

from cinder import coordination
from cinder import exception
from cinder import utils as cinder_utils
from cinder.volume import configuration
from cinder.volume.drivers.hitachi import vsp_common as common
from cinder.volume.drivers.hitachi import vsp_utils as utils

_GETSTORAGEARRAY_ONCE = 1000
_LU_PATH_DEFINED = 'SSB=0xB958,0x015A'
_ANOTHER_LDEV_MAPPED = 'SSB=0xB958,0x0947'
_NOT_LOCKED = 'SSB=0x2E11,0x2205'
_LOCK_WAITTIME = 2 * 60 * 60
NORMAL_STS = 'NML'
_LDEV_STATUS_WAITTIME = 120
_LDEV_CHECK_INTERVAL = 1
_LDEV_CREATED = ['-check_status', NORMAL_STS]
_LDEV_DELETED = ['-check_status', 'NOT', 'DEFINED']
_LUN_MAX_WAITTIME = 50
_LUN_RETRY_INTERVAL = 1
FULL_ATTR = 'MRCF'
THIN_ATTR = 'QS'
VVOL_ATTR = 'VVOL'
_PERMITTED_TYPES = set(['CVS', 'HDP', 'HDT'])
_PAIR_ATTRS = set([FULL_ATTR, THIN_ATTR])
_CHECK_KEYS = ('vol_type', 'vol_size', 'num_port', 'vol_attr', 'sts')
_HORCM_WAITTIME = 1
_EXEC_MAX_WAITTIME = 30
_EXTEND_WAITTIME = 10 * 60
_EXEC_RETRY_INTERVAL = 5
_HORCM_NO_RETRY_ERRORS = [
    'SSB=0x2E10,0x9705',
    'SSB=0x2E10,0x9706',
    'SSB=0x2E10,0x9707',
    'SSB=0x2E11,0x8303',
    'SSB=0x2E30,0x0007',
    'SSB=0xB956,0x3173',
    'SSB=0xB956,0x31D7',
    'SSB=0xB956,0x31D9',
    'SSB=0xB957,0x4188',
    _LU_PATH_DEFINED,
    'SSB=0xB958,0x015E',
]

SMPL = 1
PVOL = 2
SVOL = 3

COPY = 2
PAIR = 3
PSUS = 4
PSUE = 5
UNKN = 0xff

_STATUS_TABLE = {
    'SMPL': SMPL,
    'COPY': COPY,
    'RCPY': COPY,
    'PAIR': PAIR,
    'PFUL': PAIR,
    'PSUS': PSUS,
    'PFUS': PSUS,
    'SSUS': PSUS,
    'PSUE': PSUE,
}

_NOT_SET = '-'

_SMPL_STAUS = set([_NOT_SET, 'SMPL'])

_HORCM_RUNNING = 1
_COPY_GROUP = utils.DRIVER_PREFIX + '-%s%s%03X%d'
_SNAP_NAME = utils.DRIVER_PREFIX + '-SNAP'
_LDEV_NAME = utils.DRIVER_PREFIX + '-LDEV-%d-%d'
_PAIR_TARGET_NAME_BODY = 'pair00'
_PAIR_TARGET_NAME = utils.TARGET_PREFIX + _PAIR_TARGET_NAME_BODY
_MAX_MUNS = 3

_SNAP_HASH_SIZE = 8

ALL_EXIT_CODE = set(range(256))
HORCM_EXIT_CODE = set(range(128))
EX_ENAUTH = 202
EX_ENOOBJ = 205
EX_CMDRJE = 221
EX_ENLDEV = 227
EX_CMDIOE = 237
EX_ENOGRP = 239
EX_INVCMD = 240
EX_INVMOD = 241
EX_ENORMT = 242
EX_ENODEV = 246
EX_ENOENT = 247
EX_OPTINV = 248
EX_ATTDBG = 250
EX_ATTHOR = 251
EX_INVARG = 253
EX_COMERR = 255
_NO_SUCH_DEVICE = [EX_ENOGRP, EX_ENODEV, EX_ENOENT]
_INVALID_RANGE = [EX_ENLDEV, EX_INVARG]
_HORCM_ERROR = set([EX_ENORMT, EX_ATTDBG, EX_ATTHOR, EX_COMERR])
_COMMAND_IO_TO_RAID = set(
    [EX_CMDRJE, EX_CMDIOE, EX_INVCMD, EX_INVMOD, EX_OPTINV])

_DEFAULT_PORT_BASE = 31000

_HORCMGR = 0
_PAIR_HORCMGR = 1
_INFINITE = "-"

_HORCM_PATTERNS = {
    'gid': {
        'pattern': re.compile(r"ID +(?P<gid>\d+)\(0x\w+\)"),
        'type': six.text_type,
    },
    'ldev': {
        'pattern': re.compile(r"^LDEV +: +(?P<ldev>\d+)", re.M),
        'type': int,
    },
    'lun': {
        'pattern': re.compile(r"LUN +(?P<lun>\d+)\(0x\w+\)"),
        'type': six.text_type,
    },
    'num_port': {
        'pattern': re.compile(r"^NUM_PORT +: +(?P<num_port>\d+)", re.M),
        'type': int,
    },
    'pair_gid': {
        'pattern': re.compile(
            r"^CL\w-\w+ +(?P<pair_gid>\d+) +%s " % _PAIR_TARGET_NAME, re.M),
        'type': six.text_type,
    },
    'ports': {
        'pattern': re.compile(r"^PORTs +: +(?P<ports>.+)$", re.M),
        'type': list,
    },
    'vol_attr': {
        'pattern': re.compile(r"^VOL_ATTR +: +(?P<vol_attr>.+)$", re.M),
        'type': list,
    },
    'vol_size': {
        'pattern': re.compile(
            r"^VOL_Capacity\(BLK\) +: +(?P<vol_size>\d+)""", re.M),
        'type': int,
    },
    'vol_type': {
        'pattern': re.compile(r"^VOL_TYPE +: +(?P<vol_type>.+)$", re.M),
        'type': six.text_type,
    },
    'sts': {
        'pattern': re.compile(r"^STS +: +(?P<sts>.+)", re.M),
        'type': six.text_type,
    },
    'undefined_ldev': {
        'pattern': re.compile(
            r"^ +\d+ +(?P<undefined_ldev>\d+) +- +- +NOT +DEFINED", re.M),
        'type': int,
    },
}

LDEV_SEP_PATTERN = re.compile(r'\ +:\ +')
CMD_PATTERN = re.compile(r"((?:^|\n)HORCM_CMD\n)")

horcm_opts = [
    cfg.ListOpt(
        'vsp_horcm_numbers',
        item_type=types.Integer(min=0, max=2047),
        default=[200, 201],
        help='Command Control Interface instance numbers in the format of '
             '\'xxx,yyy\'. The second one is for Shadow Image operation and '
             'the first one is for other purposes.'),
    cfg.StrOpt(
        'vsp_horcm_user',
        help='Name of the user on the storage system.'),
    cfg.StrOpt(
        'vsp_horcm_password',
        secret=True,
        help='Password corresponding to vsp_horcm_user.'),
    cfg.BoolOpt(
        'vsp_horcm_add_conf',
        default=True,
        help='If True, the driver will create or update the Command Control '
             'Interface configuration file as needed.'),
    cfg.ListOpt(
        'vsp_horcm_pair_target_ports',
        help='IDs of the storage ports used to copy volumes by Shadow Image '
             'or Thin Image. To specify multiple ports, connect them by '
             'commas (e.g. CL1-A,CL2-A).'),
]

_REQUIRED_HORCM_OPTS = [
    'vsp_horcm_user',
    'vsp_horcm_password',
]

CONF = cfg.CONF
CONF.register_opts(horcm_opts, group=configuration.SHARED_CONF_GROUP)

LOG = logging.getLogger(__name__)
MSG = utils.VSPMsg


def horcmgr_synchronized(func):
    """Synchronize CCI operations per CCI instance."""
    @functools.wraps(func)
    def wrap(self, *args, **kwargs):
        """Synchronize CCI operations per CCI instance."""
        @coordination.synchronized(self.lock[args[0]])
        def func_locked(*_args, **_kwargs):
            """Execute the wrapped function in a synchronized section."""
            return func(*_args, **_kwargs)
        return func_locked(self, *args, **kwargs)
    return wrap


def _is_valid_target(target, target_name, target_ports, is_pair):
    """Return True if the specified target is valid, False otherwise."""
    if is_pair:
        return (target[:utils.PORT_ID_LENGTH] in target_ports and
                target_name == _PAIR_TARGET_NAME)
    if (target[:utils.PORT_ID_LENGTH] not in target_ports or
            not target_name.startswith(utils.TARGET_PREFIX) or
            target_name == _PAIR_TARGET_NAME):
        return False
    return True


def find_value(stdout, key):
    """Return the first match from the given raidcom command output."""
    match = _HORCM_PATTERNS[key]['pattern'].search(stdout)
    if match:
        if _HORCM_PATTERNS[key]['type'] is list:
            return [
                value.strip() for value in
                LDEV_SEP_PATTERN.split(match.group(key))]
        return _HORCM_PATTERNS[key]['type'](match.group(key))
    return None


def _run_horcmgr(inst):
    """Return 1 if the CCI instance is running."""
    result = utils.execute(
        'env', 'HORCMINST=%s' % inst, 'horcmgr', '-check')
    return result[0]


def _run_horcmshutdown(inst):
    """Stop the CCI instance and return 0 if successful."""
    result = utils.execute('horcmshutdown.sh', inst)
    return result[0]


def _run_horcmstart(inst):
    """Start the CCI instance and return 0 if successful."""
    result = utils.execute('horcmstart.sh', inst)
    return result[0]


def _check_ldev(ldev_info, ldev, existing_ref):
    """Check if the LDEV meets the criteria for being managed by the driver."""
    if ldev_info['sts'] != NORMAL_STS:
        msg = utils.output_log(MSG.INVALID_LDEV_FOR_MANAGE)
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)
    vol_attr = set(ldev_info['vol_attr'])
    if (not ldev_info['vol_type'].startswith('OPEN-V') or
            len(vol_attr) < 2 or not vol_attr.issubset(_PERMITTED_TYPES)):
        msg = utils.output_log(MSG.INVALID_LDEV_ATTR_FOR_MANAGE, ldev=ldev,
                               ldevtype=utils.NVOL_LDEV_TYPE)
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)
    # Hitachi storage calculates volume sizes in a block unit, 512 bytes.
    if ldev_info['vol_size'] % utils.GIGABYTE_PER_BLOCK_SIZE:
        msg = utils.output_log(MSG.INVALID_LDEV_SIZE_FOR_MANAGE, ldev=ldev)
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)
    if ldev_info['num_port']:
        msg = utils.output_log(MSG.INVALID_LDEV_PORT_FOR_MANAGE, ldev=ldev)
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)


class VSPHORCM(common.VSPCommon):
    """HORCM interface class for Hitachi VSP Driver."""

    def __init__(self, conf, storage_protocol, db):
        """Initialize instance variables."""
        super(VSPHORCM, self).__init__(conf, storage_protocol, db)
        self.conf.append_config_values(horcm_opts)

        self._copy_groups = [None] * _MAX_MUNS
        self._pair_targets = []
        self._pattern = {
            'pool': None,
            'p_pool': None,
        }

    def run_raidcom(self, *args, **kwargs):
        """Run a raidcom command and return its output."""
        if 'success_code' not in kwargs:
            kwargs['success_code'] = HORCM_EXIT_CODE
        cmd = ['raidcom'] + list(args) + [
            '-s', self.conf.vsp_storage_id,
            '-I%s' % self.conf.vsp_horcm_numbers[_HORCMGR]]
        return self.run_and_verify_storage_cli(*cmd, **kwargs)

    def _run_pair_cmd(self, command, *args, **kwargs):
        """Run a pair-related CCI command and return its output."""
        kwargs['horcmgr'] = _PAIR_HORCMGR
        if 'success_code' not in kwargs:
            kwargs['success_code'] = HORCM_EXIT_CODE
        cmd = [command] + list(args) + [
            '-IM%s' % self.conf.vsp_horcm_numbers[_PAIR_HORCMGR]]
        return self.run_and_verify_storage_cli(*cmd, **kwargs)

    def run_storage_cli(self, *cmd, **kwargs):
        """Run a CCI command and return its output."""
        interval = kwargs.pop('interval', _EXEC_RETRY_INTERVAL)
        flag = {'ignore_enauth': True}

        def _wait_for_horcm_execution(start_time, flag, *cmd, **kwargs):
            """Run a CCI command and raise its output."""
            ignore_error = kwargs.pop('ignore_error', [])
            no_retry_error = ignore_error + _HORCM_NO_RETRY_ERRORS
            success_code = kwargs.pop('success_code', HORCM_EXIT_CODE)
            timeout = kwargs.pop('timeout', _EXEC_MAX_WAITTIME)
            horcmgr = kwargs.pop('horcmgr', _HORCMGR)
            do_login = kwargs.pop('do_login', False)

            result = utils.execute(*cmd, **kwargs)
            if _NOT_LOCKED in result[2] and not utils.check_timeout(
                    start_time, _LOCK_WAITTIME):
                LOG.debug(
                    "The resource group to which the operation object "
                    "belongs is being locked by other software.")
                return
            if (result[0] in success_code or
                    utils.check_timeout(start_time, timeout) or
                    utils.check_ignore_error(no_retry_error, result[2])):
                raise loopingcall.LoopingCallDone(result)
            if result[0] == EX_ENAUTH:
                if not self._retry_login(flag['ignore_enauth'], do_login):
                    raise loopingcall.LoopingCallDone(result)
                flag['ignore_enauth'] = False
            elif result[0] in _HORCM_ERROR:
                if not self._start_horcmgr(horcmgr):
                    raise loopingcall.LoopingCallDone(result)
            elif result[0] not in _COMMAND_IO_TO_RAID:
                raise loopingcall.LoopingCallDone(result)

        loop = loopingcall.FixedIntervalLoopingCall(
            _wait_for_horcm_execution, timeutils.utcnow(),
            flag, *cmd, **kwargs)
        return loop.start(interval=interval).wait()

    def _retry_login(self, ignore_enauth, do_login):
        """Return True if login to CCI succeeds, False otherwise."""
        if not ignore_enauth:
            if not do_login:
                result = self._run_raidcom_login(do_raise=False)

            if do_login or result[0]:
                utils.output_log(MSG.HORCM_LOGIN_FAILED,
                                 user=self.conf.vsp_horcm_user)
                return False

        return True

    def _run_raidcom_login(self, do_raise=True):
        """Log in to CCI and return its output."""
        return self.run_raidcom(
            '-login', self.conf.vsp_horcm_user,
            self.conf.vsp_horcm_password,
            do_raise=do_raise, do_login=True)

    @horcmgr_synchronized
    def _restart_horcmgr(self, horcmgr):
        """Restart the CCI instance."""
        inst = self.conf.vsp_horcm_numbers[horcmgr]

        def _wait_for_horcm_shutdown(start_time, inst):
            """Stop the CCI instance and raise True if it stops."""
            if _run_horcmgr(inst) != _HORCM_RUNNING:
                raise loopingcall.LoopingCallDone()
            if (_run_horcmshutdown(inst) and
                    _run_horcmgr(inst) == _HORCM_RUNNING or
                    utils.check_timeout(
                        start_time, utils.DEFAULT_PROCESS_WAITTIME)):
                raise loopingcall.LoopingCallDone(False)

        loop = loopingcall.FixedIntervalLoopingCall(
            _wait_for_horcm_shutdown, timeutils.utcnow(), inst)
        if not loop.start(interval=_HORCM_WAITTIME).wait():
            msg = utils.output_log(
                MSG.HORCM_SHUTDOWN_FAILED,
                inst=self.conf.vsp_horcm_numbers[horcmgr])
            raise exception.VSPError(msg)

        ret = _run_horcmstart(inst)
        if ret and ret != _HORCM_RUNNING:
            msg = utils.output_log(
                MSG.HORCM_RESTART_FAILED,
                inst=self.conf.vsp_horcm_numbers[horcmgr])
            raise exception.VSPError(msg)

    @coordination.synchronized('{self.lock[create_ldev]}')
    def create_ldev(self, size, is_vvol=False):
        """Create an LDEV of the specified size and the specified type."""
        ldev = super(VSPHORCM, self).create_ldev(size, is_vvol=is_vvol)
        self._check_ldev_status(ldev)
        return ldev

    def _check_ldev_status(self, ldev, delete=False):
        """Wait until the LDEV status changes to the specified status."""
        if not delete:
            args = _LDEV_CREATED
            msg_id = MSG.LDEV_CREATION_WAIT_TIMEOUT
        else:
            args = _LDEV_DELETED
            msg_id = MSG.LDEV_DELETION_WAIT_TIMEOUT

        def _wait_for_ldev_status(start_time, ldev, *args):
            """Raise True if the LDEV is in the specified status."""
            result = self.run_raidcom(
                'get', 'ldev', '-ldev_id', ldev, *args, do_raise=False)
            if not result[0]:
                raise loopingcall.LoopingCallDone()
            if utils.check_timeout(start_time, _LDEV_STATUS_WAITTIME):
                raise loopingcall.LoopingCallDone(False)

        loop = loopingcall.FixedIntervalLoopingCall(
            _wait_for_ldev_status, timeutils.utcnow(), ldev, *args)
        if not loop.start(interval=_LDEV_CHECK_INTERVAL).wait():
            msg = utils.output_log(msg_id, ldev=ldev)
            raise exception.VSPError(msg)

    def create_ldev_on_storage(self, ldev, size, is_vvol):
        """Create an LDEV on the storage system."""
        args = ['add', 'ldev', '-ldev_id', ldev, '-capacity', '%sG' % size,
                '-emulation', 'OPEN-V', '-pool']
        if is_vvol:
            args.append('snap')
        else:
            args.append(self.conf.vsp_pool)
        self.run_raidcom(*args)

    def get_unused_ldev(self):
        """Find an unused LDEV and return its LDEV number."""
        if not self.storage_info['ldev_range']:
            ldev_info = self.get_ldev_info(
                ['ldev'], '-ldev_list', 'undefined', '-cnt', '1')
            ldev = ldev_info.get('ldev')
        else:
            ldev = self._find_unused_ldev_by_range()
        # When 'ldev' is 0, it should be true.
        # Therefore, it cannot remove 'is None'.
        if ldev is None:
            msg = utils.output_log(MSG.NO_AVAILABLE_RESOURCE, resource='LDEV')
            raise exception.VSPError(msg)
        return ldev

    def _find_unused_ldev_by_range(self):
        """Return the LDEV number of an unused LDEV in the LDEV range."""
        success_code = HORCM_EXIT_CODE.union(_INVALID_RANGE)
        start, end = self.storage_info['ldev_range'][:2]

        while start <= end:
            if end - start + 1 > _GETSTORAGEARRAY_ONCE:
                cnt = _GETSTORAGEARRAY_ONCE
            else:
                cnt = end - start + 1

            ldev_info = self.get_ldev_info(
                ['undefined_ldev'], '-ldev_id', start, '-cnt', cnt,
                '-key', 'front_end', success_code=success_code)
            ldev = ldev_info.get('undefined_ldev')
            # When 'ldev' is 0, it should be true.
            # Therefore, it cannot remove 'is not None'.
            if ldev is not None:
                return ldev

            start += _GETSTORAGEARRAY_ONCE

        return None

    def get_ldev_info(self, keys, *args, **kwargs):
        """Return a dictionary of LDEV-related items."""
        data = {}
        result = self.run_raidcom('get', 'ldev', *args, **kwargs)
        for key in keys:
            data[key] = find_value(result[1], key)
        return data

    def copy_on_storage(self, pvol, size, metadata, sync):
        """Check if the LDEV can be copied on the storage."""
        ldev_info = self.get_ldev_info(['sts', 'vol_attr'], '-ldev_id', pvol)
        if ldev_info['sts'] != NORMAL_STS:
            msg = utils.output_log(MSG.INVALID_LDEV_STATUS_FOR_COPY, ldev=pvol)
            raise exception.VSPError(msg)

        if VVOL_ATTR in ldev_info['vol_attr']:
            raise exception.VSPNotSupported()
        return super(VSPHORCM, self).copy_on_storage(pvol, size, metadata,
                                                     sync)

    @coordination.synchronized('{self.lock[create_pair]}')
    def create_pair_on_storage(self, pvol, svol, is_thin):
        """Create a copy pair on the storage."""
        path_list = []
        vol_type, pair_info = self._get_vol_type_and_pair_info(pvol)
        if vol_type == SVOL:
            self._delete_pair_based_on_svol(
                pair_info['pvol'], pair_info['svol_info'],
                no_restart=True)
        if vol_type != PVOL:
            self._initialize_pair_connection(pvol)
            path_list.append(pvol)
        try:
            self._initialize_pair_connection(svol)
            path_list.append(svol)
            self._create_pair_on_storage_core(pvol, svol, is_thin, vol_type)
        except exception.VSPError:
            with excutils.save_and_reraise_exception():
                for ldev in path_list:
                    try:
                        self._terminate_pair_connection(ldev)
                    except exception.VSPError:
                        utils.output_log(MSG.UNMAP_LDEV_FAILED, ldev=ldev)

    def _create_pair_on_storage_core(self, pvol, svol, is_thin, vol_type):
        """Create a copy pair on the storage depending on the copy method."""
        if is_thin:
            self._create_thin_copy_pair(pvol, svol)

        else:
            self._create_full_copy_pair(pvol, svol, vol_type)

    def _create_thin_copy_pair(self, pvol, svol):
        """Create a THIN copy pair on the storage."""
        snapshot_name = _SNAP_NAME + six.text_type(svol % _SNAP_HASH_SIZE)
        self.run_raidcom(
            'add', 'snapshot', '-ldev_id', pvol, svol, '-pool',
            self.conf.vsp_thin_pool, '-snapshot_name',
            snapshot_name, '-copy_size', self.conf.vsp_copy_speed)
        try:
            self.wait_thin_copy(svol, PAIR)
            self.run_raidcom(
                'modify', 'snapshot', '-ldev_id', svol,
                '-snapshot_data', 'create')
            self.wait_thin_copy(svol, PSUS)
        except exception.VSPError:
            with excutils.save_and_reraise_exception():
                interval = self.conf.vsp_async_copy_check_interval
                try:
                    self._delete_thin_copy_pair(pvol, svol, interval)
                except exception.VSPError:
                    utils.output_log(MSG.DELETE_TI_PAIR_FAILED, pvol=pvol,
                                     svol=svol)

    def _create_full_copy_pair(self, pvol, svol, vol_type):
        """Create a FULL copy pair on the storage."""
        mun = 0

        if vol_type == PVOL:
            mun = self._get_unused_mun(pvol)

        copy_group = self._copy_groups[mun]
        ldev_name = _LDEV_NAME % (pvol, svol)
        restart = False
        create = False

        try:
            self._add_pair_config(pvol, svol, copy_group, ldev_name, mun)
            self._restart_horcmgr(_PAIR_HORCMGR)
            restart = True
            self._run_pair_cmd(
                'paircreate', '-g', copy_group, '-d', ldev_name,
                '-c', self.conf.vsp_copy_speed,
                '-vl', '-split', '-fq', 'quick')
            create = True

            self._wait_full_copy(svol, set([PSUS, COPY]))
        except exception.VSPError:
            with excutils.save_and_reraise_exception():
                if create:
                    try:
                        self._wait_full_copy(svol, set([PAIR, PSUS, PSUE]))
                    except exception.VSPError:
                        utils.output_log(MSG.WAIT_SI_PAIR_STATUS_FAILED,
                                         pvol=pvol, svol=svol)

                    interval = self.conf.vsp_async_copy_check_interval

                    try:
                        self._delete_full_copy_pair(pvol, svol, interval)
                    except exception.VSPError:
                        utils.output_log(MSG.DELETE_SI_PAIR_FAILED, pvol=pvol,
                                         svol=svol)

                try:
                    if self._is_smpl(svol):
                        self._delete_pair_config(
                            pvol, svol, copy_group, ldev_name)
                except exception.VSPError:
                    utils.output_log(MSG.DELETE_DEVICE_GRP_FAILED, pvol=pvol,
                                     svol=svol)

                if restart:
                    try:
                        self._restart_horcmgr(_PAIR_HORCMGR)
                    except exception.VSPError:
                        utils.output_log(
                            MSG.HORCM_RESTART_FOR_SI_FAILED,
                            inst=self.conf.vsp_horcm_numbers[1])

    def _get_unused_mun(self, ldev):
        """Return the number of an unused mirror unit."""
        pair_list = []

        for mun in range(_MAX_MUNS):
            pair_info = self._get_full_copy_pair_info(ldev, mun)
            if not pair_info:
                return mun

            pair_list.append((pair_info['svol_info'], mun))

        for svol_info, mun in pair_list:
            if svol_info['is_psus']:
                self._delete_pair_based_on_svol(
                    ldev, svol_info, no_restart=True)
                return mun

        utils.output_log(MSG.NO_AVAILABLE_MIRROR_UNIT,
                         copy_method=utils.FULL, pvol=ldev)
        raise exception.VSPBusy()

    def _get_vol_type_and_pair_info(self, ldev):
        """Return a tuple of the LDEV's Shadow Image pair status and info."""
        ldev_info = self.get_ldev_info(['sts', 'vol_attr'], '-ldev_id', ldev)
        if ldev_info['sts'] != NORMAL_STS:
            return (SMPL, None)

        if THIN_ATTR in ldev_info['vol_attr']:
            return (PVOL, None)

        if FULL_ATTR in ldev_info['vol_attr']:
            pair_info = self._get_full_copy_pair_info(ldev, 0)
            if not pair_info:
                return (PVOL, None)

            if pair_info['pvol'] != ldev:
                return (SVOL, pair_info)

            return (PVOL, None)

        return (SMPL, None)

    def _get_full_copy_info(self, ldev):
        """Return a tuple of P-VOL and S-VOL's info of a Shadow Image pair."""
        vol_type, pair_info = self._get_vol_type_and_pair_info(ldev)
        svol_info = []

        if vol_type == SMPL:
            return (None, None)

        elif vol_type == SVOL:
            return (pair_info['pvol'], [pair_info['svol_info']])

        for mun in range(_MAX_MUNS):
            pair_info = self._get_full_copy_pair_info(ldev, mun)
            if pair_info:
                svol_info.append(pair_info['svol_info'])

        return (ldev, svol_info)

    @coordination.synchronized('{self.lock[create_pair]}')
    def delete_pair(self, ldev, all_split=True):
        """Delete the specified LDEV in a synchronized section."""
        super(VSPHORCM, self).delete_pair(ldev, all_split=all_split)

    def delete_pair_based_on_pvol(self, pair_info, all_split):
        """Disconnect all volume pairs to which the specified P-VOL belongs."""
        svols = []
        restart = False

        try:
            for svol_info in pair_info['svol_info']:
                if svol_info['is_thin'] or not svol_info['is_psus']:
                    svols.append(six.text_type(svol_info['ldev']))
                    continue

                self.delete_pair_from_storage(
                    pair_info['pvol'], svol_info['ldev'], False)

                restart = True

                self._terminate_pair_connection(svol_info['ldev'])

            if not svols:
                self._terminate_pair_connection(pair_info['pvol'])

        finally:
            if restart:
                self._restart_horcmgr(_PAIR_HORCMGR)

        if all_split and svols:
            utils.output_log(
                MSG.UNABLE_TO_DELETE_PAIR, pvol=pair_info['pvol'],
                svol=', '.join(svols))
            raise exception.VSPBusy()

    def delete_pair_based_on_svol(self, pvol, svol_info):
        """Disconnect all volume pairs to which the specified S-VOL belongs."""
        self._delete_pair_based_on_svol(pvol, svol_info)

    def _delete_pair_based_on_svol(self, pvol, svol_info, no_restart=False):
        """Disconnect all volume pairs to which the specified S-VOL belongs."""
        do_restart = False

        if not svol_info['is_psus']:
            utils.output_log(MSG.UNABLE_TO_DELETE_PAIR, pvol=pvol,
                             svol=svol_info['ldev'])
            raise exception.VSPBusy()

        try:
            self.delete_pair_from_storage(
                pvol, svol_info['ldev'], svol_info['is_thin'])
            do_restart = True
            self._terminate_pair_connection(svol_info['ldev'])
            self._terminate_pair_connection(pvol)
        finally:
            if not no_restart and do_restart:
                self._restart_horcmgr(_PAIR_HORCMGR)

    def delete_pair_from_storage(self, pvol, svol, is_thin):
        """Disconnect the volume pair that consists of the specified LDEVs."""
        interval = self.conf.vsp_async_copy_check_interval
        if is_thin:
            self._delete_thin_copy_pair(pvol, svol, interval)
        else:
            self._delete_full_copy_pair(pvol, svol, interval)

    def _delete_thin_copy_pair(self, pvol, svol, interval):
        """Disconnect a THIN volume pair."""
        result = self.run_raidcom(
            'get', 'snapshot', '-ldev_id', svol)
        if not result[1]:
            return
        mun = result[1].splitlines()[1].split()[5]
        self.run_raidcom(
            'unmap', 'snapshot', '-ldev_id', svol,
            success_code=ALL_EXIT_CODE)
        self.run_raidcom(
            'delete', 'snapshot', '-ldev_id', pvol, '-mirror_id', mun)
        self._wait_thin_copy_deleting(svol, interval=interval)

    def _wait_thin_copy_deleting(self, ldev, **kwargs):
        """Wait until the LDEV is no longer in a THIN volume pair."""
        interval = kwargs.pop(
            'interval', self.conf.vsp_async_copy_check_interval)

        def _wait_for_thin_copy_smpl(start_time, ldev, **kwargs):
            """Raise True if the LDEV is no longer in a THIN volume pair."""
            timeout = kwargs.pop('timeout', utils.DEFAULT_PROCESS_WAITTIME)
            ldev_info = self.get_ldev_info(
                ['sts', 'vol_attr'], '-ldev_id', ldev)
            if (ldev_info['sts'] != NORMAL_STS or
                    THIN_ATTR not in ldev_info['vol_attr']):
                raise loopingcall.LoopingCallDone()
            if utils.check_timeout(start_time, timeout):
                raise loopingcall.LoopingCallDone(False)

        loop = loopingcall.FixedIntervalLoopingCall(
            _wait_for_thin_copy_smpl, timeutils.utcnow(), ldev, **kwargs)
        if not loop.start(interval=interval).wait():
            msg = utils.output_log(MSG.TI_PAIR_STATUS_WAIT_TIMEOUT, svol=ldev)
            raise exception.VSPError(msg)

    def _delete_full_copy_pair(self, pvol, svol, interval):
        """Disconnect a FULL volume pair."""
        stdout = self._run_pairdisplay(
            '-d', self.conf.vsp_storage_id, svol, 0)
        if not stdout:
            return

        copy_group = stdout.splitlines()[2].split()[0]
        ldev_name = _LDEV_NAME % (pvol, svol)

        if stdout.splitlines()[1].split()[9] != 'P-VOL':
            self._restart_horcmgr(_PAIR_HORCMGR)
        try:
            self._run_pair_cmd(
                'pairsplit', '-g', copy_group, '-d', ldev_name, '-S')
            self._wait_full_copy(svol, set([SMPL]), interval=interval)
        finally:
            if self._is_smpl(svol):
                self._delete_pair_config(pvol, svol, copy_group, ldev_name)

    def _initialize_pair_connection(self, ldev):
        """Initialize server-volume connection for volume copy."""
        port, gid = None, None

        for port, gid in self._pair_targets:
            try:
                targets = {
                    'list': [(port, gid)],
                    'lun': {},
                }
                return self.map_ldev(targets, ldev)
            except exception.VSPError:
                utils.output_log(MSG.MAP_LDEV_FAILED, ldev=ldev, port=port,
                                 id=gid, lun=None)

        msg = utils.output_log(MSG.NO_MAPPING_FOR_LDEV, ldev=ldev)
        raise exception.VSPError(msg)

    def _terminate_pair_connection(self, ldev):
        """Terminate server-volume connection for volume copy."""
        targets = {
            'list': [],
        }
        ldev_info = self.get_ldev_info(['sts', 'vol_attr'], '-ldev_id', ldev)
        if (ldev_info['sts'] == NORMAL_STS and
                FULL_ATTR in ldev_info['vol_attr'] or
                self._get_thin_copy_svol_status(ldev) != SMPL):
            LOG.debug(
                'The specified LDEV has pair. Therefore, unmapping '
                'operation was skipped. '
                '(LDEV: %(ldev)s, vol_attr: %(info)s)',
                {'ldev': ldev, 'info': ldev_info['vol_attr']})
            return
        self._find_mapped_targets_from_storage(
            targets, ldev, self.storage_info['controller_ports'], is_pair=True)
        self.unmap_ldev(targets, ldev)

    def check_param(self):
        """Check parameter values and consistency among them."""
        super(VSPHORCM, self).check_param()
        utils.check_opts(self.conf, horcm_opts)
        insts = self.conf.vsp_horcm_numbers
        if len(insts) != 2 or insts[_HORCMGR] == insts[_PAIR_HORCMGR]:
            msg = utils.output_log(MSG.INVALID_PARAMETER,
                                   param='vsp_horcm_numbers')
            raise exception.VSPError(msg)
        if (not self.conf.vsp_target_ports and
                not self.conf.vsp_horcm_pair_target_ports):
            msg = utils.output_log(MSG.INVALID_PARAMETER,
                                   param='vsp_target_ports or '
                                   'vsp_horcm_pair_target_ports')
            raise exception.VSPError(msg)
        utils.output_log(MSG.SET_CONFIG_VALUE, object='LDEV range',
                         value=self.storage_info['ldev_range'])
        for opt in _REQUIRED_HORCM_OPTS:
            if not self.conf.safe_get(opt):
                msg = utils.output_log(MSG.INVALID_PARAMETER, param=opt)
                raise exception.VSPError(msg)

    def _set_copy_groups(self, host_ip):
        """Initialize an instance variable for Shadow Image copy groups."""
        serial = self.conf.vsp_storage_id
        inst = self.conf.vsp_horcm_numbers[_PAIR_HORCMGR]

        for mun in range(_MAX_MUNS):
            copy_group = _COPY_GROUP % (host_ip, serial, inst, mun)
            self._copy_groups[mun] = copy_group
        utils.output_log(MSG.SET_CONFIG_VALUE, object='copy group list',
                         value=self._copy_groups)

    def connect_storage(self):
        """Prepare for using the storage."""
        self._set_copy_groups(CONF.my_ip)

        if self.conf.vsp_horcm_add_conf:
            self._create_horcm_conf()
            self._create_horcm_conf(horcmgr=_PAIR_HORCMGR)
        self._restart_horcmgr(_HORCMGR)
        self._restart_horcmgr(_PAIR_HORCMGR)
        self._run_raidcom_login()
        super(VSPHORCM, self).connect_storage()

        self._pattern['p_pool'] = re.compile(
            (r"^%03d +\S+ +\d+ +\d+ +(?P<tp_cap>\d+) +\d+ +\d+ +\d+ +\w+ +"
             r"\d+ +(?P<tl_cap>\d+)") % self.storage_info['pool_id'], re.M)
        self._pattern['pool'] = re.compile(
            r"^%03d +\S+ +\d+ +\S+ +\w+ +\d+ +\w+ +\d+ +(?P<vcap>\S+)" %
            self.storage_info['pool_id'], re.M)

    def _find_lun(self, ldev, port, gid):
        """Return LUN determined by the given arguments."""
        result = self.run_raidcom(
            'get', 'lun', '-port', '-'.join([port, gid]))
        match = re.search(
            r'^%(port)s +%(gid)s +\S+ +(?P<lun>\d+) +1 +%(ldev)s ' % {
                'port': port, 'gid': gid, 'ldev': ldev}, result[1], re.M)
        if match:
            return match.group('lun')
        return None

    def _find_mapped_targets_from_storage(self, targets, ldev,
                                          target_ports, is_pair=False):
        """Update port-gid list for the specified LDEV."""
        ldev_info = self.get_ldev_info(['ports'], '-ldev_id', ldev)
        if not ldev_info['ports']:
            return
        for ports_strings in ldev_info['ports']:
            ports = ports_strings.split()
            if _is_valid_target(ports[0], ports[2], target_ports, is_pair):
                targets['list'].append(ports[0])

    def find_mapped_targets_from_storage(self, targets, ldev, target_ports):
        """Update port-gid list for the specified LDEV."""
        self._find_mapped_targets_from_storage(targets, ldev, target_ports)

    def get_unmap_targets_list(self, target_list, mapped_list):
        """Return a list of IDs of ports that need to be disconnected."""
        unmap_list = []
        for mapping_info in mapped_list:
            if (mapping_info[:utils.PORT_ID_LENGTH],
                    mapping_info.split('-')[2]) in target_list:
                unmap_list.append(mapping_info)
        return unmap_list

    def unmap_ldev(self, targets, ldev):
        """Delete the LUN between the specified LDEV and port-gid."""
        interval = _LUN_RETRY_INTERVAL
        success_code = HORCM_EXIT_CODE.union([EX_ENOOBJ])
        timeout = utils.DEFAULT_PROCESS_WAITTIME
        for target in targets['list']:
            self.run_raidcom(
                'delete', 'lun', '-port', target, '-ldev_id', ldev,
                interval=interval, success_code=success_code, timeout=timeout)
            LOG.debug(
                'Deleted logical unit path of the specified logical '
                'device. (LDEV: %(ldev)s, target: %(target)s)',
                {'ldev': ldev, 'target': target})

    def find_all_mapped_targets_from_storage(self, targets, ldev):
        """Add all port-gids connected with the LDEV to the list."""
        ldev_info = self.get_ldev_info(['ports'], '-ldev_id', ldev)
        if ldev_info['ports']:
            for port in ldev_info['ports']:
                targets['list'].append(port.split()[0])

    def delete_target_from_storage(self, port, gid):
        """Delete the host group or the iSCSI target from the port."""
        result = self.run_raidcom(
            'delete', 'host_grp', '-port',
            '-'.join([port, gid]), do_raise=False)
        if result[0]:
            utils.output_log(MSG.DELETE_TARGET_FAILED, port=port, id=gid)

    def _run_add_lun(self, ldev, port, gid, lun=None):
        """Create a LUN between the specified LDEV and port-gid."""
        args = ['add', 'lun', '-port', '-'.join([port, gid]), '-ldev_id', ldev]
        ignore_error = [_LU_PATH_DEFINED]
        if lun:
            args.extend(['-lun_id', lun])
            ignore_error = [_ANOTHER_LDEV_MAPPED]
        result = self.run_raidcom(
            *args, ignore_error=ignore_error,
            interval=_LUN_RETRY_INTERVAL, timeout=_LUN_MAX_WAITTIME)
        if not lun:
            if result[0] == EX_CMDRJE:
                lun = self._find_lun(ldev, port, gid)
                LOG.debug(
                    'A logical unit path has already been defined in the '
                    'specified logical device. (LDEV: %(ldev)s, '
                    'port: %(port)s, gid: %(gid)s, lun: %(lun)s)',
                    {'ldev': ldev, 'port': port, 'gid': gid, 'lun': lun})
            else:
                lun = find_value(result[1], 'lun')
        elif _ANOTHER_LDEV_MAPPED in result[2]:
            utils.output_log(MSG.MAP_LDEV_FAILED, ldev=ldev, port=port, id=gid,
                             lun=lun)
            return None
        LOG.debug(
            'Created logical unit path to the specified logical device. '
            '(LDEV: %(ldev)s, port: %(port)s, '
            'gid: %(gid)s, lun: %(lun)s)',
            {'ldev': ldev, 'port': port, 'gid': gid, 'lun': lun})
        return lun

    def map_ldev(self, targets, ldev):
        """Create the path between the server and the LDEV and return LUN."""
        port, gid = targets['list'][0]
        lun = self._run_add_lun(ldev, port, gid)
        targets['lun'][port] = True
        for port, gid in targets['list'][1:]:
            try:
                lun2 = self._run_add_lun(ldev, port, gid, lun=lun)
                if lun2 is not None:
                    targets['lun'][port] = True
            except exception.VSPError:
                utils.output_log(MSG.MAP_LDEV_FAILED, ldev=ldev, port=port,
                                 id=gid, lun=lun)
        return lun

    def extend_ldev(self, ldev, old_size, new_size):
        """Extend the specified LDEV to the specified new size."""
        timeout = _EXTEND_WAITTIME
        self.run_raidcom('extend', 'ldev', '-ldev_id', ldev, '-capacity',
                         '%sG' % (new_size - old_size), timeout=timeout)

    def get_pool_info(self):
        """Return the total and free capacity of the storage pool."""
        result = self.run_raidcom('get', 'dp_pool')
        p_pool_match = self._pattern['p_pool'].search(result[1])

        result = self.run_raidcom('get', 'pool', '-key', 'opt')
        pool_match = self._pattern['pool'].search(result[1])

        if not p_pool_match or not pool_match:
            msg = utils.output_log(MSG.POOL_NOT_FOUND,
                                   pool=self.storage_info['pool_id'])
            raise exception.VSPError(msg)

        tp_cap = float(p_pool_match.group('tp_cap')) / units.Ki
        tl_cap = float(p_pool_match.group('tl_cap')) / units.Ki
        vcap = 'infinite' if pool_match.group('vcap') == _INFINITE else (
            int(pool_match.group('vcap')))

        if vcap == 'infinite':
            return 'unknown', 'unknown'
        else:
            total_gb = int(math.floor(tp_cap * (vcap / 100.0)))
            free_gb = int(math.floor(total_gb - tl_cap))
            return total_gb, free_gb

    def discard_zero_page(self, volume):
        """Return the volume's no-data pages to the storage pool."""
        ldev = utils.get_ldev(volume)
        try:
            self.run_raidcom(
                'modify', 'ldev', '-ldev_id', ldev,
                '-status', 'discard_zero_page')
        except exception.VSPError:
            utils.output_log(MSG.DISCARD_ZERO_PAGE_FAILED, ldev=ldev)

    def wait_thin_copy(self, ldev, status, **kwargs):
        """Wait until the S-VOL status changes to the specified status."""
        interval = kwargs.pop(
            'interval', self.conf.vsp_copy_check_interval)

        def _wait_for_thin_copy_status(start_time, ldev, status, **kwargs):
            """Raise True if the S-VOL is in the specified status."""
            timeout = kwargs.pop('timeout', utils.DEFAULT_PROCESS_WAITTIME)
            if self._get_thin_copy_svol_status(ldev) == status:
                raise loopingcall.LoopingCallDone()
            if utils.check_timeout(start_time, timeout):
                raise loopingcall.LoopingCallDone(False)

        loop = loopingcall.FixedIntervalLoopingCall(
            _wait_for_thin_copy_status, timeutils.utcnow(),
            ldev, status, **kwargs)
        if not loop.start(interval=interval).wait():
            msg = utils.output_log(MSG.TI_PAIR_STATUS_WAIT_TIMEOUT, svol=ldev)
            raise exception.VSPError(msg)

    def _get_thin_copy_svol_status(self, ldev):
        """Return the status of the S-VOL in a THIN volume pair."""
        result = self.run_raidcom(
            'get', 'snapshot', '-ldev_id', ldev)
        if not result[1]:
            return SMPL
        return _STATUS_TABLE.get(result[1].splitlines()[1].split()[2], UNKN)

    def _create_horcm_conf(self, horcmgr=_HORCMGR):
        """Create a CCI configuration file."""
        inst = self.conf.vsp_horcm_numbers[horcmgr]
        serial = self.conf.vsp_storage_id
        filename = '/etc/horcm%s.conf' % inst
        port = _DEFAULT_PORT_BASE + inst
        found = False
        if not os.path.exists(filename):
            file_str = """
HORCM_MON
#ip_address        service         poll(10ms)     timeout(10ms)
127.0.0.1 %16d               6000              3000
HORCM_CMD
""" % port
        else:
            file_str = cinder_utils.read_file_as_root(filename)
            if re.search(r'^\\\\.\\CMD-%s:/dev/sd$' % serial, file_str, re.M):
                found = True
        if not found:
            repl_str = r'\1\\\\.\\CMD-%s:/dev/sd\n' % serial
            file_str = CMD_PATTERN.sub(repl_str, file_str)
            result = utils.execute('tee', filename, process_input=file_str)
            if result[0]:
                msg = utils.output_log(
                    MSG.CREATE_HORCM_CONF_FILE_FAILED, file=filename,
                    ret=result[0], err=result[2])
                raise exception.VSPError(msg)

    def init_cinder_hosts(self, **kwargs):
        """Initialize server-storage connection."""
        targets = {
            'info': {},
            'list': [],
            'iqns': {},
        }
        super(VSPHORCM, self).init_cinder_hosts(targets=targets)
        if self.storage_info['pair_ports']:
            targets['info'] = {}
            ports = self._get_pair_ports()
            for port in ports:
                targets['info'][port] = True
        self._init_pair_targets(targets['info'])

    def _init_pair_targets(self, targets_info):
        """Initialize server-storage connection for volume copy."""
        for port in targets_info.keys():
            if not targets_info[port]:
                continue
            result = self.run_raidcom('get', 'host_grp', '-port', port)
            gid = find_value(result[1], 'pair_gid')
            if not gid:
                try:
                    connector = {
                        'ip': _PAIR_TARGET_NAME_BODY,
                        'wwpns': [_PAIR_TARGET_NAME_BODY],
                    }
                    target_name, gid = self.create_target_to_storage(
                        port, connector, None)
                    utils.output_log(MSG.OBJECT_CREATED,
                                     object='a target for pair operation',
                                     details='port: %(port)s, gid: %(gid)s, '
                                     'target_name: %(target)s' %
                                     {'port': port, 'gid': gid,
                                      'target': target_name})
                except exception.VSPError:
                    utils.output_log(MSG.CREATE_HOST_GROUP_FAILED, port=port)
                    continue
            self._pair_targets.append((port, gid))

        if not self._pair_targets:
            msg = utils.output_log(MSG.ADD_PAIR_TARGET_FAILED)
            raise exception.VSPError(msg)
        self._pair_targets.sort(reverse=True)
        utils.output_log(MSG.SET_CONFIG_VALUE,
                         object='port-gid list for pair operation',
                         value=self._pair_targets)

    @coordination.synchronized('{self.lock[create_ldev]}')
    def delete_ldev_from_storage(self, ldev):
        """Delete the specified LDEV from the storage."""
        self._delete_ldev_from_storage(ldev)
        self._check_ldev_status(ldev, delete=True)

    def _delete_ldev_from_storage(self, ldev):
        """Delete the specified LDEV from the storage."""
        result = self.run_raidcom(
            'get', 'ldev', '-ldev_id', ldev, *_LDEV_DELETED, do_raise=False)
        if not result[0]:
            utils.output_log(MSG.LDEV_NOT_EXIST, ldev=ldev)
            return
        self.run_raidcom('delete', 'ldev', '-ldev_id', ldev)

    def _run_pairdisplay(self, *args):
        """Execute Shadow Image pairdisplay command."""
        result = self._run_pair_cmd(
            'pairdisplay', '-CLI', *args, do_raise=False,
            success_code=HORCM_EXIT_CODE.union(_NO_SUCH_DEVICE))
        return result[1]

    def _check_copy_grp(self, copy_group):
        """Return the number of device groups in the specified copy group."""
        count = 0
        result = self.run_raidcom('get', 'copy_grp')
        for line in result[1].splitlines()[1:]:
            line = line.split()
            if line[0] == copy_group:
                count += 1
                if count == 2:
                    break
        return count

    def _check_device_grp(self, group_name, ldev, ldev_name=None):
        """Return True if the LDEV is in the device group, False otherwise."""
        result = self.run_raidcom(
            'get', 'device_grp', '-device_grp_name', group_name)
        for line in result[1].splitlines()[1:]:
            line = line.split()
            if int(line[2]) == ldev:
                if not ldev_name:
                    return True
                else:
                    return line[1] == ldev_name
        return False

    def _is_smpl(self, ldev):
        """Return True if the status of the LDEV is SMPL, False otherwise."""
        stdout = self._run_pairdisplay(
            '-d', self.conf.vsp_storage_id, ldev, 0)
        if not stdout:
            return True
        return stdout.splitlines()[2].split()[9] in _SMPL_STAUS

    def _get_full_copy_pair_info(self, ldev, mun):
        """Return info of the Shadow Image volume pair."""
        stdout = self._run_pairdisplay(
            '-d', self.conf.vsp_storage_id, ldev, mun)
        if not stdout:
            return None
        line = stdout.splitlines()[2].split()
        if not line[8].isdigit() or not line[12].isdigit():
            return None
        pvol, svol = int(line[12]), int(line[8])
        LOG.debug(
            'Full copy pair status. (P-VOL: %(pvol)s, S-VOL: %(svol)s, '
            'status: %(status)s)',
            {'pvol': pvol, 'svol': svol, 'status': line[10]})
        return {
            'pvol': pvol,
            'svol_info': {
                'ldev': svol,
                'is_psus': line[10] == "SSUS",
                'is_thin': False,
            },
        }

    def _get_thin_copy_info(self, ldev):
        """Return info of the Thin Image volume pair."""
        result = self.run_raidcom(
            'get', 'snapshot', '-ldev_id', ldev)
        if not result[1]:
            return (None, None)

        line = result[1].splitlines()[1].split()
        is_psus = _STATUS_TABLE.get(line[2]) == PSUS
        if line[1] == "P-VOL":
            pvol, svol = ldev, int(line[6])
        else:
            pvol, svol = int(line[6]), ldev
        LOG.debug(
            'Thin copy pair status. (P-VOL: %(pvol)s, S-VOL: %(svol)s, '
            'status: %(status)s)',
            {'pvol': pvol, 'svol': svol, 'status': line[2]})
        return (pvol, [{'ldev': svol, 'is_thin': True, 'is_psus': is_psus}])

    def get_pair_info(self, ldev):
        """Return info of the volume pair."""
        pair_info = {}
        ldev_info = self.get_ldev_info(['sts', 'vol_attr'], '-ldev_id', ldev)
        if ldev_info['sts'] != NORMAL_STS or _PAIR_ATTRS.isdisjoint(
                ldev_info['vol_attr']):
            return None

        if FULL_ATTR in ldev_info['vol_attr']:
            pvol, svol_info = self._get_full_copy_info(ldev)
            # When 'pvol' is 0, it should be true.
            # Therefore, it cannot remove 'is not None'.
            if pvol is not None:
                pair_info['pvol'] = pvol
                pair_info.setdefault('svol_info', [])
                pair_info['svol_info'].extend(svol_info)

        if THIN_ATTR in ldev_info['vol_attr']:
            pvol, svol_info = self._get_thin_copy_info(ldev)
            # When 'pvol' is 0, it should be true.
            # Therefore, it cannot remove 'is not None'.
            if pvol is not None:
                pair_info['pvol'] = pvol
                pair_info.setdefault('svol_info', [])
                pair_info['svol_info'].extend(svol_info)

        return pair_info

    def _get_pair_ports(self):
        """Return a list of ports used for volume pair management."""
        return (self.storage_info['pair_ports'] or
                self.storage_info['controller_ports'])

    def _add_pair_config(self, pvol, svol, copy_group, ldev_name, mun):
        """Create device groups and a copy group for the SI volume pair."""
        pvol_group = copy_group + 'P'
        svol_group = copy_group + 'S'
        self.run_raidcom(
            'add', 'device_grp', '-device_grp_name',
            pvol_group, ldev_name, '-ldev_id', pvol)
        self.run_raidcom(
            'add', 'device_grp', '-device_grp_name',
            svol_group, ldev_name, '-ldev_id', svol)
        nr_copy_groups = self._check_copy_grp(copy_group)
        if nr_copy_groups == 1:
            self.run_raidcom(
                'delete', 'copy_grp', '-copy_grp_name', copy_group)
        if nr_copy_groups != 2:
            self.run_and_verify_storage_cli(
                'raidcom', 'add', 'copy_grp', '-copy_grp_name',
                copy_group, pvol_group, svol_group, '-mirror_id', mun,
                '-s', self.conf.vsp_storage_id,
                '-IM%s' % self.conf.vsp_horcm_numbers[_HORCMGR],
                success_code=HORCM_EXIT_CODE)

    def _delete_pair_config(self, pvol, svol, copy_group, ldev_name):
        """Delete specified LDEVs from Shadow Image device groups."""
        pvol_group = copy_group + 'P'
        svol_group = copy_group + 'S'
        if self._check_device_grp(pvol_group, pvol, ldev_name=ldev_name):
            self.run_raidcom(
                'delete', 'device_grp', '-device_grp_name',
                pvol_group, '-ldev_id', pvol)
        if self._check_device_grp(svol_group, svol, ldev_name=ldev_name):
            self.run_raidcom(
                'delete', 'device_grp', '-device_grp_name',
                svol_group, '-ldev_id', svol)

    def _wait_full_copy(self, ldev, status, **kwargs):
        """Wait until the LDEV status changes to the specified status."""
        interval = kwargs.pop(
            'interval', self.conf.vsp_copy_check_interval)

        def _wait_for_full_copy_pair_status(start_time, ldev,
                                            status, **kwargs):
            """Raise True if the LDEV is in the specified status."""
            timeout = kwargs.pop('timeout', utils.DEFAULT_PROCESS_WAITTIME)
            if self._run_pairevtwait(ldev) in status:
                raise loopingcall.LoopingCallDone()
            if utils.check_timeout(start_time, timeout):
                raise loopingcall.LoopingCallDone(False)

        loop = loopingcall.FixedIntervalLoopingCall(
            _wait_for_full_copy_pair_status, timeutils.utcnow(),
            ldev, status, **kwargs)
        if not loop.start(interval=interval).wait():
            msg = utils.output_log(MSG.SI_PAIR_STATUS_WAIT_TIMEOUT, svol=ldev)
            raise exception.VSPError(msg)

    def wait_full_copy_completion(self, pvol, svol):
        """Wait until the Shadow Image volume copy has finished."""
        self._wait_full_copy(svol, set([PSUS, PSUE]),
                             timeout=utils.MAX_PROCESS_WAITTIME)
        if self._run_pairevtwait(svol) == PSUE:
            msg = utils.output_log(MSG.VOLUME_COPY_FAILED,
                                   copy_method=utils.FULL, pvol=pvol,
                                   svol=svol)
            raise exception.VSPError(msg)

    def _run_pairevtwait(self, ldev):
        """Execute Shadow Image pairevtwait command."""
        result = self._run_pair_cmd(
            'pairevtwait', '-d', self.conf.vsp_storage_id,
            ldev, '-nowaits')
        return result[0]

    def get_ldev_size_in_gigabyte(self, ldev, existing_ref):
        """Return the size[GB] of the specified LDEV."""
        ldev_info = self.get_ldev_info(
            _CHECK_KEYS, '-ldev_id', ldev, do_raise=False)
        _check_ldev(ldev_info, ldev, existing_ref)
        # Hitachi storage calculates volume sizes in a block unit, 512 bytes.
        return ldev_info['vol_size'] / utils.GIGABYTE_PER_BLOCK_SIZE

    def get_pool_id(self):
        """Return the pool number of vsp_pool."""
        pool_id = super(VSPHORCM, self).get_pool_id()
        if pool_id is None:
            pool = self.conf.vsp_pool
            result = self.run_raidcom('get', 'pool', '-key', 'opt')
            for line in result[1].splitlines()[1:]:
                line = line.split()
                if line[3] == pool:
                    return int(line[0])
        return pool_id

    def config_lock(self):
        """Initialize lock resource names."""
        for key in ['create_ldev', 'create_pair']:
            self.lock[key] = '_'.join([key, self.conf.vsp_storage_id])
        self.lock[_HORCMGR] = (
            'horcmgr_%s' % self.conf.vsp_horcm_numbers[_HORCMGR])
        self.lock[_PAIR_HORCMGR] = (
            'horcmgr_%s' % self.conf.vsp_horcm_numbers[_PAIR_HORCMGR])

    @horcmgr_synchronized
    def _start_horcmgr(self, horcmgr):
        """Start the CCI instance and return True if successful."""
        inst = self.conf.vsp_horcm_numbers[horcmgr]
        ret = 0
        if _run_horcmgr(inst) != _HORCM_RUNNING:
            ret = _run_horcmstart(inst)
        if ret and ret != _HORCM_RUNNING:
            utils.output_log(MSG.HORCM_START_FAILED, inst=inst)
            return False
        return True

    def output_param_to_log(self):
        """Output configuration parameter values to the log file."""
        super(VSPHORCM, self).output_param_to_log()
        utils.output_opts(self.conf, horcm_opts)

    def get_storage_cli_info(self):
        """Return a tuple of the storage CLI name and its version."""
        version = 'N/A'
        result = utils.execute('raidqry', '-h')
        match = re.search(r'^Ver&Rev: +(?P<version>\S+)', result[1], re.M)
        if match:
            version = match.group('version')
        return ('Command Control Interface', version)

    def check_vvol(self, ldev):
        """Return True if the specified LDEV is V-VOL, False otherwise."""
        ldev_info = self.get_ldev_info(['sts', 'vol_attr'], '-ldev_id', ldev)
        if ldev_info['sts'] != NORMAL_STS:
            return False
        return VVOL_ATTR in ldev_info['vol_attr']
