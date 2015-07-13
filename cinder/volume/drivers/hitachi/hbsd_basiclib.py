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

import inspect
import os
import shlex

from oslo_concurrency import lockutils
from oslo_concurrency import processutils as putils
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _, _LE
from cinder import utils

SMPL = 1
COPY = 2
PAIR = 3
PSUS = 4
PSUE = 5
UNKN = 0xff

FULL = 'Full copy'
THIN = 'Thin copy'

DEFAULT_TRY_RANGE = range(3)
MAX_PROCESS_WAITTIME = 86400
DEFAULT_PROCESS_WAITTIME = 900

GETSTORAGEARRAY_ONCE = 100

WARNING_ID = 300

DEFAULT_GROUP_RANGE = [0, 65535]

NAME_PREFIX = 'HBSD-'

NORMAL_VOLUME_TYPE = 'Normal'

LOCK_DIR = '/var/lock/hbsd/'

LOG = logging.getLogger(__name__)

HBSD_INFO_MSG = {
    1: _('The parameter of the storage backend. '
         '(config_group: %(config_group)s)'),
    3: _('The storage backend can be used. (config_group: %(config_group)s)'),
    4: _('The volume %(volume_id)s is managed successfully. (LDEV: %(ldev)s)'),
    5: _('The volume %(volume_id)s is unmanaged successfully. '
         '(LDEV: %(ldev)s)'),
}

HBSD_WARN_MSG = {
    301: _('A LUN (HLUN) was not found. (LDEV: %(ldev)s)'),
    302: _('Failed to specify a logical device for the volume '
           '%(volume_id)s to be unmapped.'),
    303: _('An iSCSI CHAP user could not be deleted. (username: %(user)s)'),
    304: _('Failed to specify a logical device to be deleted. '
           '(method: %(method)s, id: %(id)s)'),
    305: _('The logical device for specified %(type)s %(id)s '
           'was already deleted.'),
    306: _('A host group could not be deleted. (port: %(port)s, '
           'gid: %(gid)s, name: %(name)s)'),
    307: _('An iSCSI target could not be deleted. (port: %(port)s, '
           'tno: %(tno)s, alias: %(alias)s)'),
    308: _('A host group could not be added. (port: %(port)s, '
           'name: %(name)s)'),
    309: _('An iSCSI target could not be added. '
           '(port: %(port)s, alias: %(alias)s, reason: %(reason)s)'),
    310: _('Failed to unmap a logical device. (LDEV: %(ldev)s, '
           'reason: %(reason)s)'),
    311: _('A free LUN (HLUN) was not found. Add a different host'
           ' group. (LDEV: %(ldev)s)'),
    312: _('Failed to get a storage resource. The system will attempt '
           'to get the storage resource again. (resource: %(resource)s)'),
    313: _('Failed to delete a logical device. (LDEV: %(ldev)s, '
           'reason: %(reason)s)'),
    314: _('Failed to map a logical device. (LDEV: %(ldev)s, LUN: %(lun)s, '
           'port: %(port)s, id: %(id)s)'),
    315: _('Failed to perform a zero-page reclamation. '
           '(LDEV: %(ldev)s, reason: %(reason)s)'),
    316: _('Failed to assign the iSCSI initiator IQN. (port: %(port)s, '
           'reason: %(reason)s)'),
}

HBSD_ERR_MSG = {
    600: _('The command %(cmd)s failed. (ret: %(ret)s, stdout: %(out)s, '
           'stderr: %(err)s)'),
    601: _('A parameter is invalid. (%(param)s)'),
    602: _('A parameter value is invalid. (%(meta)s)'),
    603: _('Failed to acquire a resource lock. (serial: %(serial)s, '
           'inst: %(inst)s, ret: %(ret)s, stderr: %(err)s)'),
    604: _('Cannot set both hitachi_serial_number and hitachi_unit_name.'),
    605: _('Either hitachi_serial_number or hitachi_unit_name is required.'),
    615: _('A pair could not be created. The maximum number of pair is '
           'exceeded. (copy method: %(copy_method)s, P-VOL: %(pvol)s)'),
    616: _('A pair cannot be deleted. (P-VOL: %(pvol)s, S-VOL: %(svol)s)'),
    617: _('The specified operation is not supported. The volume size '
           'must be the same as the source %(type)s. (volume: %(volume_id)s)'),
    618: _('The volume %(volume_id)s could not be extended. '
           'The volume type must be Normal.'),
    619: _('The volume %(volume_id)s to be mapped was not found.'),
    624: _('The %(type)s %(id)s source to be replicated was not found.'),
    631: _('Failed to create a file. (file: %(file)s, ret: %(ret)s, '
           'stderr: %(err)s)'),
    632: _('Failed to open a file. (file: %(file)s, ret: %(ret)s, '
           'stderr: %(err)s)'),
    633: _('%(file)s: Permission denied.'),
    636: _('Failed to add the logical device.'),
    637: _('The method %(method)s is timed out. (timeout value: %(timeout)s)'),
    640: _('A pool could not be found. (pool id: %(pool_id)s)'),
    641: _('The host group or iSCSI target could not be added.'),
    642: _('An iSCSI CHAP user could not be added. (username: %(user)s)'),
    643: _('The iSCSI CHAP user %(user)s does not exist.'),
    648: _('There are no resources available for use. '
           '(resource: %(resource)s)'),
    649: _('The host group or iSCSI target was not found.'),
    650: _('The resource %(resource)s was not found.'),
    651: _('The IP Address was not found.'),
    653: _('The creation of a logical device could not be '
           'completed. (LDEV: %(ldev)s)'),
    654: _('A volume status is invalid. (status: %(status)s)'),
    655: _('A snapshot status is invalid. (status: %(status)s)'),
    659: _('A host group is invalid. (host group: %(gid)s)'),
    660: _('The specified %(desc)s is busy.'),
    700: _('There is no designation of the %(param)s. '
           'The specified storage is essential to manage the volume.'),
    701: _('There is no designation of the ldev. '
           'The specified ldev is essential to manage the volume.'),
    702: _('The specified ldev %(ldev)s could not be managed. '
           'The volume type must be DP-VOL.'),
    703: _('The specified ldev %(ldev)s could not be managed. '
           'The ldev size must be in multiples of gigabyte.'),
    704: _('The specified ldev %(ldev)s could not be managed. '
           'The ldev must not be mapping.'),
    705: _('The specified ldev %(ldev)s could not be managed. '
           'The ldev must not be paired.'),
    706: _('The volume %(volume_id)s could not be unmanaged. '
           'The volume type must be %(volume_type)s.'),
}


def set_msg(msg_id, **kwargs):
    if msg_id < WARNING_ID:
        msg_header = 'MSGID%04d-I:' % msg_id
        msg_body = HBSD_INFO_MSG.get(msg_id)
    else:
        msg_header = 'MSGID%04d-W:' % msg_id
        msg_body = HBSD_WARN_MSG.get(msg_id)

    return '%(header)s %(body)s' % {'header': msg_header,
                                    'body': msg_body % kwargs}


def output_err(msg_id, **kwargs):
    msg = HBSD_ERR_MSG.get(msg_id) % kwargs

    LOG.error(_LE("MSGID%(id)04d-E: %(msg)s"), {'id': msg_id, 'msg': msg})

    return msg


def get_process_lock(file):
    if not os.access(file, os.W_OK):
        msg = output_err(633, file=file)
        raise exception.HBSDError(message=msg)
    return lockutils.InterProcessLock(file)


def create_empty_file(filename):
    if not os.path.exists(filename):
        try:
            utils.execute('touch', filename)
        except putils.ProcessExecutionError as ex:
            msg = output_err(
                631, file=filename, ret=ex.exit_code, err=ex.stderr)
            raise exception.HBSDError(message=msg)


class FileLock(lockutils.InterProcessLock):

    def __init__(self, name, lock_object):
        self.lock_object = lock_object

        super(FileLock, self).__init__(name)

    def __enter__(self):
        self.lock_object.acquire()

        try:
            ret = super(FileLock, self).__enter__()
        except Exception:
            with excutils.save_and_reraise_exception():
                self.lock_object.release()

        return ret

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super(FileLock, self).__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.lock_object.release()


class NopLock(object):

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class HBSDBasicLib(object):

    def __init__(self, conf=None):
        self.conf = conf

    def exec_command(self, cmd, args=None, printflag=True):
        if printflag:
            if args:
                LOG.debug('cmd: %(cmd)s, args: %(args)s',
                          {'cmd': cmd, 'args': args})
            else:
                LOG.debug('cmd: %s', cmd)

        cmd = [cmd]

        if args:
            if six.PY2 and isinstance(args, six.text_type):
                cmd += shlex.split(args.encode())
            else:
                cmd += shlex.split(args)

        try:
            stdout, stderr = utils.execute(*cmd, run_as_root=True)
            ret = 0
        except putils.ProcessExecutionError as e:
            ret = e.exit_code
            stdout = e.stdout
            stderr = e.stderr

            LOG.debug('cmd: %s', cmd)
            LOG.debug('from: %s', inspect.stack()[2])
            LOG.debug('ret: %d', ret)
            LOG.debug('stdout: %s', stdout.replace(os.linesep, ' '))
            LOG.debug('stderr: %s', stderr.replace(os.linesep, ' '))

        return ret, stdout, stderr

    def set_pair_flock(self):
        return NopLock()

    def set_horcmgr_flock(self):
        return NopLock()

    def discard_zero_page(self, ldev):
        pass

    def output_param_to_log(self, conf):
        pass

    def connect_storage(self):
        pass

    def get_max_hostgroups(self):
        pass

    def restart_pair_horcm(self):
        pass
