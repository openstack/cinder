# Copyright (c) 2012 - 2015 EMC Corporation, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""
VNX CLI
"""
import math
import os
import random
import re
import time
import types

import eventlet
from oslo_concurrency import lockutils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils as json
from oslo_utils import excutils
from oslo_utils import timeutils
import six
import taskflow.engines
from taskflow.patterns import linear_flow
from taskflow import task
from taskflow.types import failure

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.openstack.common import loopingcall
from cinder import utils
from cinder.volume import configuration as config
from cinder.volume.drivers.san import san
from cinder.volume import manager
from cinder.volume import utils as vol_utils
from cinder.volume import volume_types

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


INTERVAL_5_SEC = 5
INTERVAL_20_SEC = 20
INTERVAL_30_SEC = 30
INTERVAL_60_SEC = 60

ENABLE_TRACE = False

loc_opts = [
    cfg.StrOpt('storage_vnx_authentication_type',
               default='global',
               help='VNX authentication scope type.'),
    cfg.StrOpt('storage_vnx_security_file_dir',
               default=None,
               help='Directory path that contains the VNX security file. '
               'Make sure the security file is generated first.'),
    cfg.StrOpt('naviseccli_path',
               default='',
               help='Naviseccli Path.'),
    cfg.StrOpt('storage_vnx_pool_name',
               default=None,
               help='Storage pool name.'),
    cfg.StrOpt('san_secondary_ip',
               default=None,
               help='VNX secondary SP IP Address.'),
    cfg.IntOpt('default_timeout',
               default=60 * 24 * 365,
               help='Default timeout for CLI operations in minutes. '
               'For example, LUN migration is a typical long '
               'running operation, which depends on the LUN size and '
               'the load of the array. '
               'An upper bound in the specific deployment can be set to '
               'avoid unnecessary long wait. '
               'By default, it is 365 days long.'),
    cfg.IntOpt('max_luns_per_storage_group',
               default=255,
               help='Default max number of LUNs in a storage group.'
               ' By default, the value is 255.'),
    cfg.BoolOpt('destroy_empty_storage_group',
                default=False,
                help='To destroy storage group '
                'when the last LUN is removed from it. '
                'By default, the value is False.'),
    cfg.StrOpt('iscsi_initiators',
               default='',
               help='Mapping between hostname and '
               'its iSCSI initiator IP addresses.'),
    cfg.BoolOpt('initiator_auto_registration',
                default=False,
                help='Automatically register initiators. '
                'By default, the value is False.'),
    cfg.BoolOpt('initiator_auto_deregistration',
                default=False,
                help='Automatically deregister initiators after the related '
                'storage group is destroyed. '
                'By default, the value is False.'),
    cfg.BoolOpt('check_max_pool_luns_threshold',
                default=False,
                help='Report free_capacity_gb as 0 when the limit to '
                'maximum number of pool LUNs is reached. '
                'By default, the value is False.'),
    cfg.BoolOpt('force_delete_lun_in_storagegroup',
                default=False,
                help='Delete a LUN even if it is in Storage Groups.')
]

CONF.register_opts(loc_opts)


def decorate_all_methods(method_decorator):
    """Applies decorator on the methods of a class.

    This is a class decorator, which will apply method decorator referred
    by method_decorator to all the public methods (without underscore as
    the prefix) in a class.
    """
    if not ENABLE_TRACE:
        return lambda cls: cls

    def _decorate_all_methods(cls):
        for attr_name, attr_val in cls.__dict__.items():
            if (isinstance(attr_val, types.FunctionType) and
                    not attr_name.startswith("_")):
                setattr(cls, attr_name, method_decorator(attr_val))
        return cls

    return _decorate_all_methods


def log_enter_exit(func):
    if not CONF.debug:
        return func

    def inner(self, *args, **kwargs):
        LOG.debug("Entering %(cls)s.%(method)s",
                  {'cls': self.__class__.__name__,
                   'method': func.__name__})
        start = timeutils.utcnow()
        ret = func(self, *args, **kwargs)
        end = timeutils.utcnow()
        LOG.debug("Exiting %(cls)s.%(method)s. "
                  "Spent %(duration)s sec. "
                  "Return %(return)s",
                  {'cls': self.__class__.__name__,
                   'duration': timeutils.delta_seconds(start, end),
                   'method': func.__name__,
                   'return': ret})
        return ret
    return inner


class PropertyDescriptor(object):
    def __init__(self, option, label, key, converter=None):
        self.option = option
        self.label = label
        self.key = key
        self.converter = converter


@decorate_all_methods(log_enter_exit)
class CommandLineHelper(object):

    LUN_STATE = PropertyDescriptor(
        '-state',
        'Current State:\s*(.*)\s*',
        'state')
    LUN_STATUS = PropertyDescriptor(
        '-status',
        'Status:\s*(.*)\s*',
        'status')
    LUN_OPERATION = PropertyDescriptor(
        '-opDetails',
        'Current Operation:\s*(.*)\s*',
        'operation')
    LUN_CAPACITY = PropertyDescriptor(
        '-userCap',
        'User Capacity \(GBs\):\s*(.*)\s*',
        'total_capacity_gb',
        float)
    LUN_OWNER = PropertyDescriptor(
        '-owner',
        'Current Owner:\s*SP\s*(.*)\s*',
        'owner')
    LUN_ATTACHEDSNAP = PropertyDescriptor(
        '-attachedSnapshot',
        'Attached Snapshot:\s*(.*)\s*',
        'attached_snapshot')
    LUN_NAME = PropertyDescriptor(
        '-name',
        'Name:\s*(.*)\s*',
        'lun_name')
    LUN_ID = PropertyDescriptor(
        '-id',
        'LOGICAL UNIT NUMBER\s*(\d+)\s*',
        'lun_id',
        int)
    LUN_POOL = PropertyDescriptor(
        '-poolName',
        'Pool Name:\s*(.*)\s*',
        'pool')

    LUN_ALL = [LUN_STATE, LUN_STATUS, LUN_OPERATION,
               LUN_CAPACITY, LUN_OWNER, LUN_ATTACHEDSNAP]

    LUN_WITH_POOL = [LUN_STATE, LUN_CAPACITY, LUN_OWNER,
                     LUN_ATTACHEDSNAP, LUN_POOL]

    POOL_TOTAL_CAPACITY = PropertyDescriptor(
        '-userCap',
        'User Capacity \(GBs\):\s*(.*)\s*',
        'total_capacity_gb',
        float)
    POOL_FREE_CAPACITY = PropertyDescriptor(
        '-availableCap',
        'Available Capacity *\(GBs\) *:\s*(.*)\s*',
        'free_capacity_gb',
        float)
    POOL_FAST_CACHE = PropertyDescriptor(
        '-fastcache',
        'FAST Cache:\s*(.*)\s*',
        'fast_cache_enabled',
        lambda value: 'True' if value == 'Enabled' else 'False')
    POOL_NAME = PropertyDescriptor(
        '-name',
        'Pool Name:\s*(.*)\s*',
        'pool_name')

    POOL_ALL = [POOL_TOTAL_CAPACITY, POOL_FREE_CAPACITY]

    MAX_POOL_LUNS = PropertyDescriptor(
        '-maxPoolLUNs',
        'Max. Pool LUNs:\s*(.*)\s*',
        'max_pool_luns',
        int)
    TOTAL_POOL_LUNS = PropertyDescriptor(
        '-numPoolLUNs',
        'Total Number of Pool LUNs:\s*(.*)\s*',
        'total_pool_luns',
        int)

    POOL_FEATURE_DEFAULT = (MAX_POOL_LUNS, TOTAL_POOL_LUNS)

    CLI_RESP_PATTERN_CG_NOT_FOUND = 'Cannot find'
    CLI_RESP_PATTERN_SNAP_NOT_FOUND = 'The specified snapshot does not exist'
    CLI_RESP_PATTERN_LUN_NOT_EXIST = 'The (pool lun) may not exist'
    CLI_RESP_PATTERN_SMP_NOT_ATTACHED = ('The specified Snapshot mount point '
                                         'is not currently attached.')
    CLI_RESP_PATTERN_SG_NAME_IN_USE = 'Storage Group name already in use'
    CLI_RESP_PATTERN_LUN_IN_SG_1 = 'contained in a Storage Group'
    CLI_RESP_PATTERN_LUN_IN_SG_2 = 'Host LUN/LUN mapping still exists'
    CLI_RESP_PATTERN_LUN_NOT_MIGRATING = ('The specified source LUN '
                                          'is not currently migrating')

    def __init__(self, configuration):
        configuration.append_config_values(san.san_opts)

        self.timeout = configuration.default_timeout * INTERVAL_60_SEC
        self.max_luns = configuration.max_luns_per_storage_group

        # Checking for existence of naviseccli tool
        navisecclipath = configuration.naviseccli_path
        if not os.path.exists(navisecclipath):
            err_msg = _('naviseccli_path: Could not find '
                        'NAVISECCLI tool %(path)s.') % {'path': navisecclipath}
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        self.command = (navisecclipath, '-address')
        self.active_storage_ip = configuration.san_ip
        self.primary_storage_ip = self.active_storage_ip
        self.secondary_storage_ip = configuration.san_secondary_ip
        if self.secondary_storage_ip == self.primary_storage_ip:
            LOG.warning(_LE("san_secondary_ip is configured as "
                            "the same value as san_ip."))
            self.secondary_storage_ip = None
        if not configuration.san_ip:
            err_msg = _('san_ip: Mandatory field configuration. '
                        'san_ip is not set.')
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        self.credentials = ()
        storage_username = configuration.san_login
        storage_password = configuration.san_password
        storage_auth_type = configuration.storage_vnx_authentication_type
        storage_vnx_security_file = configuration.storage_vnx_security_file_dir

        if storage_auth_type is None:
            storage_auth_type = 'global'
        elif storage_auth_type.lower() not in ('ldap', 'local', 'global'):
            err_msg = (_('Invalid VNX authentication type: %s')
                       % storage_auth_type)
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)
        # if there is security file path provided, use this security file
        if storage_vnx_security_file:
            self.credentials = ('-secfilepath', storage_vnx_security_file)
            LOG.info(_LI("Using security file in %s for authentication"),
                     storage_vnx_security_file)
        # if there is a username/password provided, use those in the cmd line
        elif storage_username is not None and len(storage_username) > 0 and\
                storage_password is not None and len(storage_password) > 0:
            self.credentials = ('-user', storage_username,
                                '-password', storage_password,
                                '-scope', storage_auth_type)
            LOG.info(_LI("Plain text credentials are being used for "
                         "authentication"))
        else:
            LOG.info(_LI("Neither security file nor plain "
                         "text credentials are specified. Security file under "
                         "home directory will be used for authentication "
                         "if present."))

        self.iscsi_initiator_map = None
        if configuration.iscsi_initiators:
            self.iscsi_initiator_map = \
                json.loads(configuration.iscsi_initiators)
            LOG.info(_LI("iscsi_initiators: %s"), self.iscsi_initiator_map)

        # extra spec constants
        self.tiering_spec = 'storagetype:tiering'
        self.provisioning_spec = 'storagetype:provisioning'
        self.provisioning_values = {
            'thin': ['-type', 'Thin'],
            'thick': ['-type', 'NonThin'],
            'compressed': ['-type', 'Thin'],
            'deduplicated': ['-type', 'Thin', '-deduplication', 'on']}
        self.tiering_values = {
            'starthighthenauto': [
                '-initialTier', 'highestAvailable',
                '-tieringPolicy', 'autoTier'],
            'auto': [
                '-initialTier', 'optimizePool',
                '-tieringPolicy', 'autoTier'],
            'highestavailable': [
                '-initialTier', 'highestAvailable',
                '-tieringPolicy', 'highestAvailable'],
            'lowestavailable': [
                '-initialTier', 'lowestAvailable',
                '-tieringPolicy', 'lowestAvailable'],
            'nomovement': [
                '-initialTier', 'optimizePool',
                '-tieringPolicy', 'noMovement']}

    def _raise_cli_error(self, cmd=None, rc=None, out='', **kwargs):
        raise exception.EMCVnxCLICmdError(cmd=cmd,
                                          rc=rc,
                                          out=out.split('\n'),
                                          **kwargs)

    def create_lun_with_advance_feature(self, pool, name, size,
                                        provisioning, tiering,
                                        consistencygroup_id=None,
                                        poll=True):
        command_create_lun = ['lun', '-create',
                              '-capacity', size,
                              '-sq', 'gb',
                              '-poolName', pool,
                              '-name', name]
        if not poll:
            command_create_lun = ['-np'] + command_create_lun
        # provisioning
        if provisioning:
            command_create_lun.extend(self.provisioning_values[provisioning])
        # tiering
        if tiering:
            command_create_lun.extend(self.tiering_values[tiering])

        # create lun
        data = self.create_lun_by_cmd(command_create_lun, name)

        # handle compression
        try:
            if provisioning == 'compressed':
                self.enable_or_disable_compression_on_lun(
                    name, 'on')
        except exception.EMCVnxCLICmdError as ex:
            with excutils.save_and_reraise_exception():
                self.delete_lun(name)
                LOG.error(_LE("Error on enable compression on lun %s."),
                          six.text_type(ex))

        # handle consistency group
        try:
            if consistencygroup_id:
                self.add_lun_to_consistency_group(
                    consistencygroup_id, data['lun_id'])
        except exception.EMCVnxCLICmdError as ex:
            with excutils.save_and_reraise_exception():
                self.delete_lun(name)
                LOG.error(_LE("Error on adding lun to consistency"
                              " group. %s"), six.text_type(ex))
        return data

    def create_lun_by_cmd(self, cmd, name):
        out, rc = self.command_execute(*cmd)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 4 and out.find('(0x712d8d04)') >= 0:
                LOG.warning(_LW('LUN already exists, LUN name %(name)s. '
                                'Message: %(msg)s'),
                            {'name': name, 'msg': out})
            else:
                self._raise_cli_error(cmd, rc, out)

        def _lun_state_validation(lun_data):
            lun_state = lun_data[self.LUN_STATE.key]
            if lun_state == 'Initializing':
                return False
            # Lun in Ready or Faulted state is eligible for IO access,
            # so if no lun operation, return success.
            elif lun_state in ['Ready', 'Faulted']:
                return lun_data[self.LUN_OPERATION.key] == 'None'
            # Raise exception if lun state is Offline, Invalid, Destroying
            # or other unexpected states.
            else:
                msg = _("Volume %(lun_name)s was created in VNX, but in"
                        " %(lun_state)s state."
                        ) % {'lun_name': lun_data[self.LUN_NAME.key],
                             'lun_state': lun_state}
                raise exception.VolumeBackendAPIException(data=msg)

        def lun_is_ready():
            try:
                data = self.get_lun_by_name(name, self.LUN_ALL, False)
            except exception.EMCVnxCLICmdError as ex:
                orig_out = "\n".join(ex.kwargs["out"])
                if orig_out.find(
                        self.CLI_RESP_PATTERN_LUN_NOT_EXIST) >= 0:
                    return False
                else:
                    raise ex
            return _lun_state_validation(data)

        self._wait_for_a_condition(lun_is_ready,
                                   None,
                                   INTERVAL_5_SEC,
                                   lambda ex:
                                   isinstance(ex, exception.EMCVnxCLICmdError))
        lun = self.get_lun_by_name(name, self.LUN_ALL, False)
        return lun

    def delete_lun(self, name):

        command_delete_lun = ['lun', '-destroy',
                              '-name', name,
                              '-forceDetach',
                              '-o']
        # executing cli command to delete volume
        out, rc = self.command_execute(*command_delete_lun)
        if rc != 0 or out.strip():
            # Ignore the error that due to retry
            if rc == 9 and self.CLI_RESP_PATTERN_LUN_NOT_EXIST in out:
                LOG.warning(_LW("LUN is already deleted, LUN name %(name)s. "
                                "Message: %(msg)s"),
                            {'name': name, 'msg': out})
            else:
                self._raise_cli_error(command_delete_lun, rc, out)

    def get_hlus(self, lun_id, poll=True):
        hlus = list()
        command_storage_group_list = ('storagegroup', '-list')
        out, rc = self.command_execute(*command_storage_group_list,
                                       poll=poll)
        if rc != 0:
            self._raise_cli_error(command_storage_group_list, rc, out)
        sg_name_p = re.compile(r'^\s*(?P<sg_name>[^\n\r]+)')
        hlu_alu_p = re.compile(r'HLU/ALU Pairs:'
                               r'\s*HLU Number\s*ALU Number'
                               r'\s*[-\s]*'
                               r'(\d|\s)*'
                               r'\s+(?P<hlu>\d+)( |\t)+%s' % lun_id)
        for sg_info in out.split('Storage Group Name:'):
            hlu_alu_m = hlu_alu_p.search(sg_info)
            if hlu_alu_m is None:
                continue
            sg_name_m = sg_name_p.search(sg_info)
            if sg_name_m:
                hlus.append((hlu_alu_m.group('hlu'),
                             sg_name_m.group('sg_name')))
        return hlus

    def _wait_for_a_condition(self, testmethod, timeout=None,
                              interval=INTERVAL_5_SEC,
                              ignorable_exception_arbiter=lambda ex: True):
        start_time = time.time()
        if timeout is None:
            timeout = self.timeout

        def _inner():
            try:
                test_value = testmethod()
            except Exception as ex:
                test_value = False
                with excutils.save_and_reraise_exception(
                        reraise=not ignorable_exception_arbiter(ex)):
                    LOG.debug('CommandLineHelper.'
                              '_wait_for_a_condition: %(method_name)s '
                              'execution failed for %(exception)s',
                              {'method_name': testmethod.__name__,
                               'exception': six.text_type(ex)})
            if test_value:
                raise loopingcall.LoopingCallDone()

            if int(time.time()) - start_time > timeout:
                msg = (_('CommandLineHelper._wait_for_a_condition: %s timeout')
                       % testmethod.__name__)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        timer = loopingcall.FixedIntervalLoopingCall(_inner)
        timer.start(interval=interval).wait()

    def expand_lun(self, name, new_size, poll=True):

        command_expand_lun = ('lun', '-expand',
                              '-name', name,
                              '-capacity', new_size,
                              '-sq', 'gb',
                              '-o',
                              '-ignoreThresholds')
        out, rc = self.command_execute(*command_expand_lun,
                                       poll=poll)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 4 and out.find("(0x712d8e04)") >= 0:
                LOG.warning(_LW("LUN %(name)s is already expanded. "
                                "Message: %(msg)s"),
                            {'name': name, 'msg': out})
            else:
                self._raise_cli_error(command_expand_lun, rc, out)

    def expand_lun_and_wait(self, name, new_size):
        self.expand_lun(name, new_size, poll=False)

        def lun_is_extented():
            data = self.get_lun_by_name(name, poll=False)
            return new_size == data[self.LUN_CAPACITY.key]

        self._wait_for_a_condition(lun_is_extented)

    def lun_rename(self, lun_id, new_name, poll=False):
        """This function used to rename a lun to match
        the expected name for the volume.
        """
        command_lun_rename = ('lun', '-modify',
                              '-l', lun_id,
                              '-newName', new_name,
                              '-o')

        out, rc = self.command_execute(*command_lun_rename,
                                       poll=poll)
        if rc != 0:
            self._raise_cli_error(command_lun_rename, rc, out)

    def modify_lun_tiering(self, name, tiering):
        """This function used to modify a lun's tiering policy."""
        command_modify_lun = ['lun', '-modify',
                              '-name', name,
                              '-o']
        if tiering:
            command_modify_lun.extend(self.tiering_values[tiering])

            out, rc = self.command_execute(*command_modify_lun)
            if rc != 0:
                self._raise_cli_error(command_modify_lun, rc, out)

    def create_consistencygroup(self, context, group):
        """create the consistency group."""
        cg_name = group['id']
        command_create_cg = ('-np', 'snap', '-group',
                             '-create',
                             '-name', cg_name,
                             '-allowSnapAutoDelete', 'no')

        out, rc = self.command_execute(*command_create_cg)
        if rc != 0:
            # Ignore the error if consistency group already exists
            if (rc == 33 and
                    out.find("(0x716d8021)") >= 0):
                LOG.warning(_LW('Consistency group %(name)s already '
                                'exists. Message: %(msg)s'),
                            {'name': cg_name, 'msg': out})
            else:
                self._raise_cli_error(command_create_cg, rc, out)

    def get_consistency_group_by_name(self, cg_name):
        cmd = ('snap', '-group', '-list', '-id', cg_name)
        data = {
            'Name': None,
            'Luns': None,
            'State': None
        }
        out, rc = self.command_execute(*cmd)
        if rc == 0:
            cg_pat = r"Name:(.*)\n"\
                     r"Description:(.*)\n"\
                     r"Allow auto delete:(.*)\n"\
                     r"Member LUN ID\(s\):(.*)\n"\
                     r"State:(.*)\n"
            for m in re.finditer(cg_pat, out):
                data['Name'] = m.groups()[0].strip()
                data['State'] = m.groups()[4].strip()
                # Handle case when no lun in cg Member LUN ID(s):  None
                luns_of_cg = m.groups()[3].replace('None', '').strip()
                data['Luns'] = ([lun.strip() for lun in luns_of_cg.split(',')]
                                if luns_of_cg else [])
                LOG.debug("Found consistent group %s.", data['Name'])

        return data

    def add_lun_to_consistency_group(self, cg_name, lun_id, poll=False):
        add_lun_to_cg_cmd = ('snap', '-group',
                             '-addmember', '-id',
                             cg_name, '-res', lun_id)

        out, rc = self.command_execute(*add_lun_to_cg_cmd, poll=poll)
        if rc != 0:
            LOG.error(_LE("Can not add the lun %(lun)s to consistency "
                          "group %(cg_name)s."), {'lun': lun_id,
                                                  'cg_name': cg_name})
            self._raise_cli_error(add_lun_to_cg_cmd, rc, out)

        def add_lun_to_consistency_success():
            data = self.get_consistency_group_by_name(cg_name)
            if str(lun_id) in data['Luns']:
                LOG.debug("Add lun %(lun)s to consistency "
                          "group %(cg_name)s successfully.",
                          {'lun': lun_id, 'cg_name': cg_name})
                return True
            else:
                LOG.debug("Adding lun %(lun)s to consistency "
                          "group %(cg_name)s.",
                          {'lun': lun_id, 'cg_name': cg_name})
                return False

        self._wait_for_a_condition(add_lun_to_consistency_success,
                                   interval=INTERVAL_30_SEC)

    def remove_luns_from_consistencygroup(self, cg_name, remove_ids,
                                          poll=False):
        """Removes LUN(s) from cg"""
        remove_luns_cmd = ('snap', '-group', '-rmmember',
                           '-id', cg_name,
                           '-res', ','.join(remove_ids))
        out, rc = self.command_execute(*remove_luns_cmd, poll=poll)
        if rc != 0:
            LOG.error(_LE("Can not remove LUNs %(luns)s in consistency "
                          "group %(cg_name)s."), {'luns': remove_ids,
                                                  'cg_name': cg_name})
            self._raise_cli_error(remove_luns_cmd, rc, out)

    def replace_luns_in_consistencygroup(self, cg_name, new_ids,
                                         poll=False):
        """Replaces LUN(s) with new_ids for cg"""
        replace_luns_cmd = ('snap', '-group', '-replmember',
                            '-id', cg_name,
                            '-res', ','.join(new_ids))
        out, rc = self.command_execute(*replace_luns_cmd, poll=poll)
        if rc != 0:
            LOG.error(_LE("Can not place new LUNs %(luns)s in consistency "
                          "group %(cg_name)s."), {'luns': new_ids,
                                                  'cg_name': cg_name})
            self._raise_cli_error(replace_luns_cmd, rc, out)

    def delete_consistencygroup(self, cg_name):
        delete_cg_cmd = ('-np', 'snap', '-group',
                         '-destroy', '-id', cg_name)
        out, rc = self.command_execute(*delete_cg_cmd)
        if rc != 0:
            # Ignore the error if CG doesn't exist
            if rc == 13 and out.find(self.CLI_RESP_PATTERN_CG_NOT_FOUND) >= 0:
                LOG.warning(_LW("CG %(cg_name)s does not exist. "
                                "Message: %(msg)s"),
                            {'cg_name': cg_name, 'msg': out})
            elif rc == 1 and out.find("0x712d8801") >= 0:
                LOG.warning(_LW("CG %(cg_name)s is deleting. "
                                "Message: %(msg)s"),
                            {'cg_name': cg_name, 'msg': out})
            else:
                self._raise_cli_error(delete_cg_cmd, rc, out)
        else:
            LOG.info(_LI('Consistency group %s was deleted '
                         'successfully.'), cg_name)

    def create_cgsnapshot(self, cgsnapshot):
        """Create a cgsnapshot (snap group)."""
        cg_name = cgsnapshot['consistencygroup_id']
        snap_name = cgsnapshot['id']
        create_cg_snap_cmd = ('-np', 'snap', '-create',
                              '-res', cg_name,
                              '-resType', 'CG',
                              '-name', snap_name,
                              '-allowReadWrite', 'yes',
                              '-allowAutoDelete', 'no')

        out, rc = self.command_execute(*create_cg_snap_cmd)
        if rc != 0:
            # Ignore the error if cgsnapshot already exists
            if (rc == 5 and
                    out.find("(0x716d8005)") >= 0):
                LOG.warning(_LW('Cgsnapshot name %(name)s already '
                                'exists. Message: %(msg)s'),
                            {'name': snap_name, 'msg': out})
            else:
                self._raise_cli_error(create_cg_snap_cmd, rc, out)

    def delete_cgsnapshot(self, cgsnapshot):
        """Delete a cgsnapshot (snap group)."""
        snap_name = cgsnapshot['id']
        delete_cg_snap_cmd = ('-np', 'snap', '-destroy',
                              '-id', snap_name, '-o')

        out, rc = self.command_execute(*delete_cg_snap_cmd)
        if rc != 0:
            # Ignore the error if cgsnapshot does not exist.
            if (rc == 5 and
                    out.find(self.CLI_RESP_PATTERN_SNAP_NOT_FOUND) >= 0):
                LOG.warning(_LW('Snapshot %(name)s for consistency group '
                                'does not exist. Message: %(msg)s'),
                            {'name': snap_name, 'msg': out})
            else:
                self._raise_cli_error(delete_cg_snap_cmd, rc, out)

    def create_snapshot(self, lun_id, name):
        if lun_id is not None:
            command_create_snapshot = ('snap', '-create',
                                       '-res', lun_id,
                                       '-name', name,
                                       '-allowReadWrite', 'yes',
                                       '-allowAutoDelete', 'no')

            out, rc = self.command_execute(*command_create_snapshot,
                                           poll=False)
            if rc != 0:
                # Ignore the error that due to retry
                if (rc == 5 and
                        out.find("(0x716d8005)") >= 0):
                    LOG.warning(_LW('Snapshot %(name)s already exists. '
                                    'Message: %(msg)s'),
                                {'name': name, 'msg': out})
                else:
                    self._raise_cli_error(command_create_snapshot, rc, out)
        else:
            msg = _('Failed to create snapshot as no LUN ID is specified')
            raise exception.VolumeBackendAPIException(data=msg)

    def delete_snapshot(self, name):

        def delete_snapshot_success():
            command_delete_snapshot = ('snap', '-destroy',
                                       '-id', name,
                                       '-o')
            out, rc = self.command_execute(*command_delete_snapshot,
                                           poll=True)
            if rc != 0:
                # Ignore the error that due to retry
                if rc == 5 and out.find("not exist") >= 0:
                    LOG.warning(_LW("Snapshot %(name)s may deleted already. "
                                    "Message: %(msg)s"),
                                {'name': name, 'msg': out})
                    return True
                # The snapshot cannot be destroyed because it is
                # attached to a snapshot mount point. Wait
                elif rc == 3 and out.find("(0x716d8003)") >= 0:
                    LOG.warning(_LW("Snapshot %(name)s is in use, retry. "
                                    "Message: %(msg)s"),
                                {'name': name, 'msg': out})
                    return False
                else:
                    self._raise_cli_error(command_delete_snapshot, rc, out)
            else:
                LOG.info(_LI('Snapshot %s was deleted successfully.'),
                         name)
                return True

        self._wait_for_a_condition(delete_snapshot_success,
                                   interval=INTERVAL_30_SEC,
                                   timeout=INTERVAL_30_SEC * 3)

    def create_mount_point(self, primary_lun_name, name):

        command_create_mount_point = ('lun', '-create',
                                      '-type', 'snap',
                                      '-primaryLunName', primary_lun_name,
                                      '-name', name)

        out, rc = self.command_execute(*command_create_mount_point,
                                       poll=False)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 4 and out.find("(0x712d8d04)") >= 0:
                LOG.warning(_LW("Mount point %(name)s already exists. "
                                "Message: %(msg)s"),
                            {'name': name, 'msg': out})
            else:
                self._raise_cli_error(command_create_mount_point, rc, out)

        return rc

    def attach_mount_point(self, name, snapshot_name):

        command_attach_mount_point = ('lun', '-attach',
                                      '-name', name,
                                      '-snapName', snapshot_name)

        out, rc = self.command_execute(*command_attach_mount_point)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 85 and out.find('(0x716d8055)') >= 0:
                LOG.warning(_LW("Snapshot %(snapname)s is attached to "
                                "snapshot mount point %(mpname)s already. "
                                "Message: %(msg)s"),
                            {'snapname': snapshot_name,
                             'mpname': name,
                             'msg': out})
            else:
                self._raise_cli_error(command_attach_mount_point, rc, out)

        return rc

    def detach_mount_point(self, smp_name):

        command_detach_mount_point = ('lun', '-detach',
                                      '-name', smp_name)

        out, rc = self.command_execute(*command_detach_mount_point)
        if rc != 0:
            # Ignore the error that due to retry
            if (rc == 162 and
                    out.find(self.CLI_RESP_PATTERN_SMP_NOT_ATTACHED) >= 0):
                LOG.warning(_LW("The specified Snapshot mount point %s is not "
                                "currently attached."), smp_name)
            else:
                self._raise_cli_error(command_detach_mount_point, rc, out)

        return rc

    def migrate_lun(self, src_id, dst_id):
        command_migrate_lun = ('migrate', '-start',
                               '-source', src_id,
                               '-dest', dst_id,
                               '-rate', 'high',
                               '-o')
        # SP HA is not supported by LUN migration
        out, rc = self.command_execute(*command_migrate_lun,
                                       retry_disable=True,
                                       poll=True)

        if 0 != rc:
            self._raise_cli_error(command_migrate_lun, rc, out)

        return rc

    def migrate_lun_with_verification(self, src_id,
                                      dst_id=None,
                                      dst_name=None):
        try:
            self.migrate_lun(src_id, dst_id)
        except exception.EMCVnxCLICmdError as ex:
            migration_succeed = False
            orig_out = "\n".join(ex.kwargs["out"])
            if self._is_sp_unavailable_error(orig_out):
                LOG.warning(_LW("Migration command may get network timeout. "
                                "Double check whether migration in fact "
                                "started successfully. Message: %(msg)s"),
                            {'msg': ex.kwargs["out"]})
                command_migrate_list = ('migrate', '-list',
                                        '-source', src_id)
                rc = self.command_execute(*command_migrate_list,
                                          poll=True)[1]
                if rc == 0:
                    migration_succeed = True

            if not migration_succeed:
                LOG.warning(_LW("Start migration failed. Message: %s"),
                            ex.kwargs["out"])
                if dst_name is not None:
                    LOG.warning(_LW("Delete temp LUN after migration "
                                    "start failed. LUN: %s"), dst_name)
                    self.delete_lun(dst_name)
                return False

        # Set the proper interval to verify the migration status
        def migration_is_ready(poll=False):
            mig_ready = False
            cmd_migrate_list = ('migrate', '-list', '-source', src_id)
            out, rc = self.command_execute(*cmd_migrate_list,
                                           poll=poll)
            LOG.debug("Migration output: %s", out)
            if rc == 0:
                # parse the percentage
                state = re.search(r'Current State:\s*([^\n]+)', out)
                percentage = re.search(r'Percent Complete:\s*([^\n]+)', out)
                if state is not None:
                    current_state = state.group(1)
                    percentage_complete = percentage.group(1)
                else:
                    self._raise_cli_error(cmd_migrate_list, rc, out)
                if ("FAULTED" in current_state or
                        "STOPPED" in current_state):
                    reason = _("Migration of LUN %s has been stopped or"
                               " faulted.") % src_id
                    raise exception.VolumeBackendAPIException(data=reason)
                if ("TRANSITIONING" in current_state or
                        "MIGRATING" in current_state):
                    LOG.debug("Migration of LUN %(src_id)s in process "
                              "%(percentage)s %%.",
                              {"src_id": src_id,
                               "percentage": percentage_complete})
            else:
                if re.search(self.CLI_RESP_PATTERN_LUN_NOT_MIGRATING, out):
                    LOG.debug("Migration of LUN %s is finished.", src_id)
                    mig_ready = True
                else:
                    self._raise_cli_error(cmd_migrate_list, rc, out)
            return mig_ready

        def migration_disappeared(poll=False):
            cmd_migrate_list = ('migrate', '-list', '-source', src_id)
            out, rc = self.command_execute(*cmd_migrate_list,
                                           poll=poll)
            if rc != 0:
                if re.search(self.CLI_RESP_PATTERN_LUN_NOT_MIGRATING, out):
                    LOG.debug("Migration of LUN %s is finished.", src_id)
                    return True
                else:
                    LOG.error(_LE("Failed to query migration status of LUN."),
                              src_id)
                    self._raise_cli_error(cmd_migrate_list, rc, out)
            return False

        eventlet.sleep(INTERVAL_30_SEC)

        try:
            if migration_is_ready(True):
                return True
            self._wait_for_a_condition(
                migration_is_ready,
                interval=INTERVAL_30_SEC,
                ignorable_exception_arbiter=lambda ex:
                type(ex) is not exception.VolumeBackendAPIException)
        # Migration cancellation for clean up
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Migration of LUN %s failed to complete."),
                          src_id)
                self.migration_cancel(src_id)
                self._wait_for_a_condition(migration_disappeared,
                                           interval=INTERVAL_30_SEC)

        return True

    # Cancel migration in case where status is faulted or stopped
    def migration_cancel(self, src_id):
        LOG.info(_LI("Cancelling Migration from LUN %s."), src_id)
        cmd_migrate_cancel = ('migrate', '-cancel', '-source', src_id,
                              '-o')
        out, rc = self.command_execute(*cmd_migrate_cancel)
        if rc != 0:
            self._raise_cli_error(cmd_migrate_cancel, rc, out)

    def get_storage_group(self, name, poll=True):

        # ALU/HLU as key/value map
        lun_map = {}

        data = {'storage_group_name': name,
                'storage_group_uid': None,
                'lunmap': lun_map,
                'raw_output': ''}

        command_get_storage_group = ('storagegroup', '-list',
                                     '-gname', name)

        out, rc = self.command_execute(*command_get_storage_group,
                                       poll=poll)
        if rc != 0:
            self._raise_cli_error(command_get_storage_group, rc, out)

        data['raw_output'] = out
        re_stroage_group_id = 'Storage Group UID:\s*(.*)\s*'
        m = re.search(re_stroage_group_id, out)
        if m is not None:
            data['storage_group_uid'] = m.group(1)

        re_HLU_ALU_pair = 'HLU\/ALU Pairs:\s*HLU Number' \
                          '\s*ALU Number\s*[-\s]*(?P<lun_details>(\d+\s*)+)'
        m = re.search(re_HLU_ALU_pair, out)
        if m is not None:
            lun_details = m.group('lun_details').strip()
            values = re.split('\s*', lun_details)
            while (len(values) >= 2):
                key = values.pop()
                value = values.pop()
                lun_map[int(key)] = int(value)

        return data

    def create_storage_group(self, name):

        command_create_storage_group = ('storagegroup', '-create',
                                        '-gname', name)

        out, rc = self.command_execute(*command_create_storage_group)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 66 and self.CLI_RESP_PATTERN_SG_NAME_IN_USE in out >= 0:
                LOG.warning(_LW('Storage group %(name)s already exists. '
                                'Message: %(msg)s'),
                            {'name': name, 'msg': out})
            else:
                self._raise_cli_error(command_create_storage_group, rc, out)

    def delete_storage_group(self, name):

        command_delete_storage_group = ('storagegroup', '-destroy',
                                        '-gname', name, '-o')

        out, rc = self.command_execute(*command_delete_storage_group)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 83 and out.find("group name or UID does not "
                                     "match any storage groups") >= 0:
                LOG.warning(_LW("Storage group %(name)s doesn't exist, "
                                "may have already been deleted. "
                                "Message: %(msg)s"),
                            {'name': name, 'msg': out})
            else:
                self._raise_cli_error(command_delete_storage_group, rc, out)

    def connect_host_to_storage_group(self, hostname, sg_name):

        command_host_connect = ('storagegroup', '-connecthost',
                                '-host', hostname,
                                '-gname', sg_name,
                                '-o')

        out, rc = self.command_execute(*command_host_connect)
        if rc != 0:
            self._raise_cli_error(command_host_connect, rc, out)

    def disconnect_host_from_storage_group(self, hostname, sg_name):
        command_host_disconnect = ('storagegroup', '-disconnecthost',
                                   '-host', hostname,
                                   '-gname', sg_name,
                                   '-o')

        out, rc = self.command_execute(*command_host_disconnect)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 116 and \
                re.search("host is not.*connected to.*storage group",
                          out) is not None:
                LOG.warning(_LW("Host %(host)s has already disconnected from "
                                "storage group %(sgname)s. Message: %(msg)s"),
                            {'host': hostname, 'sgname': sg_name, 'msg': out})
            else:
                self._raise_cli_error(command_host_disconnect, rc, out)

    def add_hlu_to_storage_group(self, hlu, alu, sg_name):
        """Adds a lun into storage group as specified hlu number.

        Return True if the hlu is as specified, otherwise False.
        """

        command_add_hlu = ('storagegroup', '-addhlu',
                           '-hlu', hlu,
                           '-alu', alu,
                           '-gname', sg_name)

        out, rc = self.command_execute(*command_add_hlu, poll=False)
        if rc != 0:
            # Do not need to consider the retry for add hlu
            # Retry is handled in the caller
            self._raise_cli_error(command_add_hlu, rc, out)

        return True

    def remove_hlu_from_storagegroup(self, hlu, sg_name, poll=False):

        command_remove_hlu = ('storagegroup', '-removehlu',
                              '-hlu', hlu,
                              '-gname', sg_name,
                              '-o')

        out, rc = self.command_execute(*command_remove_hlu, poll=poll)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 66 and\
                    out.find("No such Host LUN in this Storage Group") >= 0:
                LOG.warning(_LW("HLU %(hlu)s has already been removed from "
                                "%(sgname)s. Message: %(msg)s"),
                            {'hlu': hlu, 'sgname': sg_name, 'msg': out})
            else:
                self._raise_cli_error(command_remove_hlu, rc, out)

    def get_iscsi_protocol_endpoints(self, device_sp):

        command_get_port = ('connection', '-getport',
                            '-sp', device_sp)

        out, rc = self.command_execute(*command_get_port)
        if rc != 0:
            self._raise_cli_error(command_get_port, rc, out)

        re_port_wwn = 'Port WWN:\s*(.*)\s*'
        initiator_address = re.findall(re_port_wwn, out)

        return initiator_address

    def get_pool_name_of_lun(self, lun_name, poll=True):
        data = self.get_lun_properties(
            ('-name', lun_name), self.LUN_WITH_POOL, poll=poll)
        return data.get('pool', '')

    def get_lun_by_name(self, name, properties=LUN_ALL, poll=True):
        data = self.get_lun_properties(('-name', name),
                                       properties,
                                       poll=poll)
        return data

    def get_lun_by_id(self, lunid, properties=LUN_ALL, poll=True):
        data = self.get_lun_properties(('-l', lunid),
                                       properties, poll=poll)
        return data

    def get_pool(self, name, properties=POOL_ALL, poll=True):
        data = self.get_pool_properties(('-name', name),
                                        properties=properties,
                                        poll=poll)
        return data

    def get_pool_properties(self, filter_option, properties=POOL_ALL,
                            poll=True):
        module_list = ('storagepool', '-list')
        data = self._get_obj_properties(
            module_list, filter_option,
            base_properties=[self.POOL_NAME],
            adv_properties=properties,
            poll=poll)
        return data

    def get_lun_properties(self, filter_option, properties=LUN_ALL,
                           poll=True):
        module_list = ('lun', '-list')
        data = self._get_obj_properties(
            module_list, filter_option,
            base_properties=[self.LUN_NAME, self.LUN_ID],
            adv_properties=properties,
            poll=poll)
        return data

    def get_pool_feature_properties(self, properties=POOL_FEATURE_DEFAULT,
                                    poll=True):
        module_list = ("storagepool", '-feature', '-info')
        data = self._get_obj_properties(
            module_list, tuple(),
            base_properties=[],
            adv_properties=properties,
            poll=poll)
        return data

    def _get_obj_properties(self, module_list,
                            filter_option,
                            base_properties=tuple(),
                            adv_properties=tuple(),
                            poll=True):
        # to do instance check
        command_get = module_list + filter_option
        for prop in adv_properties:
            command_get += (prop.option, )
        out, rc = self.command_execute(*command_get, poll=poll)

        if rc != 0:
            self._raise_cli_error(command_get, rc, out)

        data = {}
        for baseprop in base_properties:
            data[baseprop.key] = self._get_property_value(out, baseprop)

        for prop in adv_properties:
            data[prop.key] = self._get_property_value(out, prop)

        LOG.debug('Return Object properties. Data: %s', data)
        return data

    def _get_property_value(self, out, propertyDescriptor):
        label = propertyDescriptor.label
        m = re.search(label, out)
        if m:
            if (propertyDescriptor.converter is not None):
                try:
                    return propertyDescriptor.converter(m.group(1))
                except ValueError:
                    LOG.error(_LE("Invalid value for %(key)s, "
                                  "value is %(value)s."),
                              {'key': propertyDescriptor.key,
                               'value': m.group(1)})
                    return None
            else:
                return m.group(1)
        else:
            LOG.debug('%s value is not found in the output.',
                      propertyDescriptor.label)
            return None

    def check_lun_has_snap(self, lun_id):
        cmd = ('snap', '-list', '-res', lun_id)
        rc = self.command_execute(*cmd, poll=False)[1]
        if rc == 0:
            LOG.debug("Find snapshots for %s.", lun_id)
            return True
        else:
            return False

    def get_pool_list(self, properties=POOL_ALL, poll=True):
        temp_cache = []
        list_cmd = ('storagepool', '-list')
        for prop in properties:
            list_cmd += (prop.option,)
        output_properties = [self.POOL_NAME] + properties
        out, rc = self.command_execute(*list_cmd, poll=poll)
        if rc != 0:
            self._raise_cli_error(list_cmd, rc, out)

        try:
            for pool in out.split('\n\n'):
                if len(pool.strip()) == 0:
                    continue
                obj = {}
                for prop in output_properties:
                    obj[prop.key] = self._get_property_value(pool, prop)
                temp_cache.append(obj)
        except Exception as ex:
            LOG.error(_LE("Error happened during storage pool querying, %s."),
                      ex)
            # NOTE: Do not want to continue raise the exception
            # as the pools may be temporarily unavailable
            pass
        return temp_cache

    def get_array_serial(self, poll=False):
        """return array Serial No for pool backend."""
        data = {'array_serial': 'unknown'}

        command_get_array_serial = ('getagent', '-serial')
        # Set the property timeout to get array serial
        out, rc = self.command_execute(*command_get_array_serial,
                                       poll=poll)
        if 0 == rc:
            m = re.search(r'Serial No:\s+(\w+)', out)
            if m:
                data['array_serial'] = m.group(1)
            else:
                LOG.warning(_LW("No array serial number returned, "
                                "set as unknown."))
        else:
            self._raise_cli_error(command_get_array_serial, rc, out)

        return data

    def get_status_up_ports(self, storage_group_name, poll=True):
        """Function to get ports whose status are up."""
        cmd_get_hba = ('storagegroup', '-list', '-gname', storage_group_name)
        out, rc = self.command_execute(*cmd_get_hba, poll=poll)
        wwns = []
        if 0 == rc:
            _re_hba_sp_pair = re.compile('((\w\w:){15}(\w\w)\s*' +
                                         '(SP\s[A-B]){1}\s*(\d*)\s*\n)')
            _all_hba_sp_pairs = re.findall(_re_hba_sp_pair, out)
            sps = [each[3] for each in _all_hba_sp_pairs]
            portid = [each[4] for each in _all_hba_sp_pairs]
            cmd_get_port = ('port', '-list', '-sp')
            out, rc = self.command_execute(*cmd_get_port)
            if 0 != rc:
                self._raise_cli_error(cmd_get_port, rc, out)
            for i, sp in enumerate(sps):
                wwn = self.get_port_wwn(sp, portid[i], out)
                if (wwn is not None) and (wwn not in wwns):
                    LOG.debug('Add wwn:%(wwn)s for sg:%(sg)s.',
                              {'wwn': wwn,
                               'sg': storage_group_name})
                    wwns.append(wwn)
        elif 83 == rc:
            LOG.warning(_LW("Storage Group %s is not found."),
                        storage_group_name)
        else:
            self._raise_cli_error(cmd_get_hba, rc, out)
        return wwns

    def get_login_ports(self, storage_group_name, connector_wwpns):

        cmd_list_hba = ('port', '-list', '-gname', storage_group_name)
        out, rc = self.command_execute(*cmd_list_hba)
        ports = []
        wwns = []
        connector_hba_list = []
        if 0 == rc and out.find('Information about each HBA:') != -1:
            hba_list = out.split('Information about each SPPORT:')[0].split(
                'Information about each HBA:')[1:]
            allports = out.split('Information about each SPPORT:')[1]
            hba_uid_pat = re.compile('HBA\sUID:\s*((\w\w:){15}(\w\w))')
            for each in hba_list:
                obj_search = re.search(hba_uid_pat, each)
                if obj_search and obj_search.group(1). \
                        replace(':', '')[16:].lower() in connector_wwpns:
                    connector_hba_list.append(each)
            port_pat = re.compile('SP Name:\s*(SP\s\w)\n\s*' +
                                  'SP Port ID:\s*(\w*)\n\s*' +
                                  'HBA Devicename:.*\n\s*' +
                                  'Trusted:.*\n\s*' +
                                  'Logged In:\s*YES\n')
            for each in connector_hba_list:
                ports.extend(re.findall(port_pat, each))
            ports = list(set(ports))
            for each in ports:
                wwn = self.get_port_wwn(each[0], each[1], allports)
                if wwn:
                    wwns.append(wwn)
        else:
            self._raise_cli_error(cmd_list_hba, rc, out)
        return wwns

    def get_port_wwn(self, sp, port_id, allports=None):
        wwn = None
        if allports is None:
            cmd_get_port = ('port', '-list', '-sp')
            out, rc = self.command_execute(*cmd_get_port)
            if 0 != rc:
                self._raise_cli_error(cmd_get_port, rc, out)
            else:
                allports = out
        _re_port_wwn = re.compile('SP Name:\s*' + sp +
                                  '\nSP Port ID:\s*' + port_id +
                                  '\nSP UID:\s*((\w\w:){15}(\w\w))' +
                                  '\nLink Status:         Up' +
                                  '\nPort Status:         Online')
        _obj_search = re.search(_re_port_wwn, allports)
        if _obj_search is not None:
            wwn = _obj_search.group(1).replace(':', '')[16:]
        return wwn

    def get_fc_targets(self):
        fc_getport = ('port', '-list', '-sp')
        out, rc = self.command_execute(*fc_getport)
        if rc != 0:
            self._raise_cli_error(fc_getport, rc, out)

        fc_target_dict = {'A': [], 'B': []}

        _fcport_pat = (r'SP Name:             SP\s(\w)\s*'
                       r'SP Port ID:\s*(\w*)\n'
                       r'SP UID:\s*((\w\w:){15}(\w\w))\s*'
                       r'Link Status:         Up\n'
                       r'Port Status:         Online\n')

        for m in re.finditer(_fcport_pat, out):
            sp = m.groups()[0]
            sp_port_id = m.groups()[1]
            fc_target_dict[sp].append({'SP': sp,
                                       'Port ID': sp_port_id})
        return fc_target_dict

    def get_iscsi_targets(self, poll=True):
        cmd_getport = ('connection', '-getport', '-address', '-vlanid')
        out, rc = self.command_execute(*cmd_getport, poll=poll)
        if rc != 0:
            self._raise_cli_error(cmd_getport, rc, out)

        iscsi_target_dict = {'A': [], 'B': []}
        iscsi_spport_pat = r'(A|B)\s*' + \
                           r'Port ID:\s+(\d+)\s*' + \
                           r'Port WWN:\s+(iqn\S+)'
        iscsi_vport_pat = r'Virtual Port ID:\s+(\d+)\s*' + \
                          r'VLAN ID:\s*\S*\s*' + \
                          r'IP Address:\s+(\S+)'
        for spport_content in re.split(r'^SP:\s+|\nSP:\s*', out):
            m_spport = re.match(iscsi_spport_pat, spport_content,
                                flags=re.IGNORECASE)
            if not m_spport:
                continue
            sp = m_spport.group(1)
            port_id = int(m_spport.group(2))
            iqn = m_spport.group(3)
            for m_vport in re.finditer(iscsi_vport_pat, spport_content):
                vport_id = int(m_vport.group(1))
                ip_addr = m_vport.group(2)
                if ip_addr.find('N/A') != -1:
                    LOG.debug("Skip port without IP Address: %s",
                              m_spport.group(0) + m_vport.group(0))
                    continue
                iscsi_target_dict[sp].append({'SP': sp,
                                              'Port ID': port_id,
                                              'Port WWN': iqn,
                                              'Virtual Port ID': vport_id,
                                              'IP Address': ip_addr})

        return iscsi_target_dict

    def get_registered_spport_set(self, initiator_iqn, sgname, sg_raw_out):
        spport_set = set()
        for m_spport in re.finditer(r'\n\s+%s\s+SP\s(A|B)\s+(\d+)' %
                                    initiator_iqn,
                                    sg_raw_out,
                                    flags=re.IGNORECASE):
            spport_set.add((m_spport.group(1), int(m_spport.group(2))))
            LOG.debug('See path %(path)s in %(sg)s',
                      {'path': m_spport.group(0),
                       'sg': sgname})
        return spport_set

    def ping_node(self, target_portal, initiator_ip):
        connection_pingnode = ('connection', '-pingnode', '-sp',
                               target_portal['SP'], '-portid',
                               target_portal['Port ID'], '-vportid',
                               target_portal['Virtual Port ID'],
                               '-address', initiator_ip,
                               '-count', '1')
        out, rc = self.command_execute(*connection_pingnode)
        if rc == 0:
            ping_ok = re.compile(r'Reply from %s' % initiator_ip)
            if re.match(ping_ok, out) is not None:
                LOG.debug("See available iSCSI target: %s",
                          connection_pingnode)
                return True
        LOG.warning(_LW("See unavailable iSCSI target: %s"),
                    connection_pingnode)
        return False

    def find_available_iscsi_targets(self, hostname,
                                     preferred_sp,
                                     registered_spport_set,
                                     all_iscsi_targets,
                                     multipath=False):
        if self.iscsi_initiator_map and hostname in self.iscsi_initiator_map:
            iscsi_initiator_ips = list(self.iscsi_initiator_map[hostname])
            random.shuffle(iscsi_initiator_ips)
        else:
            iscsi_initiator_ips = None
        # Check the targets on the owner first
        if preferred_sp == 'A':
            target_sps = ('A', 'B')
        else:
            target_sps = ('B', 'A')

        if multipath:
            target_portals = []
            for target_sp in target_sps:
                sp_portals = all_iscsi_targets[target_sp]
                for portal in sp_portals:
                    spport = (portal['SP'], portal['Port ID'])
                    if spport not in registered_spport_set:
                        LOG.debug("Skip SP Port %(port)s since "
                                  "no path from %(host)s is through it",
                                  {'port': spport,
                                   'host': hostname})
                        continue
                    target_portals.append(portal)
            return target_portals

        for target_sp in target_sps:
            target_portals = list(all_iscsi_targets[target_sp])
            random.shuffle(target_portals)
            for target_portal in target_portals:
                spport = (target_portal['SP'], target_portal['Port ID'])
                if spport not in registered_spport_set:
                    LOG.debug("Skip SP Port %(port)s since "
                              "no path from %(host)s is through it",
                              {'port': spport,
                               'host': hostname})
                    continue
                if iscsi_initiator_ips is not None:
                    for initiator_ip in iscsi_initiator_ips:
                        if self.ping_node(target_portal, initiator_ip):
                            return [target_portal]
                else:
                    LOG.debug("No iSCSI IP address of %(hostname)s is known. "
                              "Return a random target portal %(portal)s.",
                              {'hostname': hostname,
                               'portal': target_portal})
                    return [target_portal]

        return None

    def _is_sp_unavailable_error(self, out):
        error_pattern = '(^Error.*Message.*End of data stream.*)|'\
                        '(.*Message.*connection refused.*)|'\
                        '(^Error.*Message.*Service Unavailable.*)|'\
                        '(^A network error occurred while trying to'\
                        ' connect.* )|'\
                        '(^Exception: Error occurred because of time out\s*)'
        pattern = re.compile(error_pattern)
        return pattern.match(out)

    def command_execute(self, *command, **kwargv):
        """Executes command against the VNX array.

        When there is named parameter poll=False, the command will be sent
        alone with option -np.
        """
        # NOTE: retry_disable need to be removed from kwargv
        # before it pass to utils.execute, otherwise exception will thrown
        retry_disable = kwargv.pop('retry_disable', False)
        out, rc = self._command_execute_on_active_ip(*command, **kwargv)
        if not retry_disable and self._is_sp_unavailable_error(out):
            # When active sp is unavailble, swith to another sp
            # and set it to active and force a poll
            if self._toggle_sp():
                LOG.debug('EMC: Command Exception: %(rc) %(result)s. '
                          'Retry on another SP.', {'rc': rc,
                                                   'result': out})
                kwargv['poll'] = True
                out, rc = self._command_execute_on_active_ip(*command,
                                                             **kwargv)

        return out, rc

    def _command_execute_on_active_ip(self, *command, **kwargv):
        if "check_exit_code" not in kwargv:
            kwargv["check_exit_code"] = True
        rc = 0
        out = ""
        need_poll = kwargv.pop('poll', True)
        if "-np" not in command and not need_poll:
            command = ("-np",) + command

        try:
            active_ip = (self.active_storage_ip,)
            out, err = utils.execute(
                *(self.command
                  + active_ip
                  + self.credentials
                  + command),
                **kwargv)
        except processutils.ProcessExecutionError as pe:
            rc = pe.exit_code
            out = pe.stdout
            out = out.replace('\n', '\\n')

        LOG.debug('EMC: Command: %(command)s. Result: %(result)s.',
                  {'command': self.command + active_ip + command,
                   'result': out.replace('\n', '\\n')})

        return out, rc

    def _is_sp_alive(self, ipaddr):
        ping_cmd = ('ping', '-c', 1, ipaddr)
        try:
            out, err = utils.execute(*ping_cmd,
                                     check_exit_code=True)
        except processutils.ProcessExecutionError as pe:
            out = pe.stdout
            rc = pe.exit_code
            if rc != 0:
                LOG.debug('%s is unavaialbe', ipaddr)
                return False
        LOG.debug('Ping SP %(spip)s Command Result: %(result)s.',
                  {'spip': self.active_storage_ip, 'result': out})
        return True

    def _toggle_sp(self):
        """This function toggles the storage IP
        Address between primary IP and secondary IP, if no SP IP address has
        exchanged, return False, otherwise True will be returned.
        """
        if self.secondary_storage_ip is None:
            return False
        old_ip = self.active_storage_ip
        self.active_storage_ip = self.secondary_storage_ip if\
            self.active_storage_ip == self.primary_storage_ip else\
            self.primary_storage_ip

        LOG.info(_LI('Toggle storage_vnx_ip_address from %(old)s to '
                     '%(new)s.'),
                 {'old': old_ip,
                  'new': self.active_storage_ip})
        return True

    def get_enablers_on_array(self, poll=False):
        """The function would get all the enabler installed
        on array.
        """
        enablers = []
        cmd_list = ('ndu', '-list')
        out, rc = self.command_execute(*cmd_list, poll=poll)

        if rc != 0:
            self._raise_cli_error(cmd_list, rc, out)
        else:
            enabler_pat = r'Name of the software package:\s*(\S+)\s*'
            for m in re.finditer(enabler_pat, out):
                enablers.append(m.groups()[0])

        LOG.debug('Enablers on array %s.', enablers)
        return enablers

    def enable_or_disable_compression_on_lun(self, volumename, compression):
        """The function will enable or disable the compression
        on lun
        """
        lun_data = self.get_lun_by_name(volumename)

        command_compression_cmd = ('compression', '-' + compression,
                                   '-l', lun_data['lun_id'],
                                   '-ignoreThresholds', '-o')

        out, rc = self.command_execute(*command_compression_cmd)

        if 0 != rc:
            self._raise_cli_error(command_compression_cmd, rc, out)
        return rc, out

    def deregister_initiator(self, initiator_uid):
        """This function tries to deregister initiators on VNX."""
        command_deregister = ('port', '-removeHBA',
                              '-hbauid', initiator_uid,
                              '-o')
        out, rc = self.command_execute(*command_deregister)
        return rc, out

    def is_pool_fastcache_enabled(self, storage_pool, poll=False):
        command_check_fastcache = ('storagepool', '-list', '-name',
                                   storage_pool, '-fastcache')
        out, rc = self.command_execute(*command_check_fastcache, poll=poll)

        if 0 != rc:
            self._raise_cli_error(command_check_fastcache, rc, out)
        else:
            re_fastcache = 'FAST Cache:\s*(.*)\s*'
            m = re.search(re_fastcache, out)
            if m is not None:
                result = True if 'Enabled' == m.group(1) else False
            else:
                LOG.error(_LE("Error parsing output for FastCache Command."))
        return result


@decorate_all_methods(log_enter_exit)
class EMCVnxCliBase(object):
    """This class defines the functions to use the native CLI functionality."""

    VERSION = '05.03.05'
    stats = {'driver_version': VERSION,
             'storage_protocol': None,
             'vendor_name': 'EMC',
             'volume_backend_name': None,
             'compression_support': 'False',
             'fast_support': 'False',
             'deduplication_support': 'False',
             'thinprovisioning_support': 'False'}
    enablers = []

    def __init__(self, prtcl, configuration=None):
        self.protocol = prtcl
        self.configuration = configuration
        self.max_luns_per_sg = self.configuration.max_luns_per_storage_group
        self.destroy_empty_sg = self.configuration.destroy_empty_storage_group
        self.itor_auto_reg = self.configuration.initiator_auto_registration
        self.itor_auto_dereg = self.configuration.initiator_auto_deregistration
        self.check_max_pool_luns_threshold = (
            self.configuration.check_max_pool_luns_threshold)
        # if zoning_mode is fabric, use lookup service to build itor_tgt_map
        self.zonemanager_lookup_service = None
        zm_conf = config.Configuration(manager.volume_manager_opts)
        if (zm_conf.safe_get('zoning_mode') == 'fabric' or
                self.configuration.safe_get('zoning_mode') == 'fabric'):
            from cinder.zonemanager import fc_san_lookup_service as fc_service
            self.zonemanager_lookup_service = \
                fc_service.FCSanLookupService(configuration=configuration)
        self.max_retries = 5
        if self.destroy_empty_sg:
            LOG.warning(_LW("destroy_empty_storage_group: True. "
                            "Empty storage group will be deleted "
                            "after volume is detached."))
        if not self.itor_auto_reg:
            LOG.info(_LI("initiator_auto_registration: False. "
                         "Initiator auto registration is not enabled. "
                         "Please register initiator manually."))
        self.hlu_set = set(xrange(1, self.max_luns_per_sg + 1))
        self._client = CommandLineHelper(self.configuration)
        self.array_serial = None
        if self.protocol == 'iSCSI':
            self.iscsi_targets = self._client.get_iscsi_targets(poll=True)
        self.hlu_cache = {}
        self.force_delete_lun_in_sg = (
            self.configuration.force_delete_lun_in_storagegroup)
        if self.force_delete_lun_in_sg:
            LOG.warning(_LW("force_delete_lun_in_storagegroup=True"))

    def get_target_storagepool(self, volume, source_volume=None):
        raise NotImplementedError

    def get_array_serial(self):
        if not self.array_serial:
            self.array_serial = self._client.get_array_serial()
        return self.array_serial['array_serial']

    def _construct_store_spec(self, volume, snapshot):
            if snapshot['cgsnapshot_id']:
                snapshot_name = snapshot['cgsnapshot_id']
            else:
                snapshot_name = snapshot['name']
            source_volume_name = snapshot['volume_name']
            volume_name = volume['name']
            volume_size = snapshot['volume_size']
            dest_volume_name = volume_name + '_dest'

            pool_name = self.get_target_storagepool(volume, snapshot['volume'])
            specs = self.get_volumetype_extraspecs(volume)
            provisioning, tiering = self._get_extra_spec_value(specs)
            store_spec = {
                'source_vol_name': source_volume_name,
                'volume': volume,
                'snap_name': snapshot_name,
                'dest_vol_name': dest_volume_name,
                'pool_name': pool_name,
                'provisioning': provisioning,
                'tiering': tiering,
                'volume_size': volume_size,
                'client': self._client
            }
            return store_spec

    def create_volume(self, volume):
        """Creates a EMC volume."""
        volume_size = volume['size']
        volume_name = volume['name']

        self._volume_creation_check(volume)
        # defining CLI command
        specs = self.get_volumetype_extraspecs(volume)
        pool = self.get_target_storagepool(volume)
        provisioning, tiering = self._get_extra_spec_value(specs)

        if not provisioning:
            provisioning = 'thick'

        LOG.info(_LI('Create Volume: %(volume)s  Size: %(size)s '
                     'pool: %(pool)s '
                     'provisioning: %(provisioning)s '
                     'tiering: %(tiering)s.'),
                 {'volume': volume_name,
                  'size': volume_size,
                  'pool': pool,
                  'provisioning': provisioning,
                  'tiering': tiering})

        data = self._client.create_lun_with_advance_feature(
            pool, volume_name, volume_size,
            provisioning, tiering, volume['consistencygroup_id'], False)
        model_update = {'provider_location':
                        self._build_provider_location_for_lun(data['lun_id'])}

        return model_update

    def _volume_creation_check(self, volume):
        """Checks on extra spec before the volume can be created."""
        specs = self.get_volumetype_extraspecs(volume)
        self._get_and_validate_extra_specs(specs)

    def _get_and_validate_extra_specs(self, specs):
        """Checks on extra specs combinations."""
        if "storagetype:pool" in specs:
            LOG.warning(_LW("Extra spec key 'storagetype:pool' is obsoleted "
                            "since driver version 5.1.0. This key will be "
                            "ignored."))

        provisioning, tiering = self._get_extra_spec_value(specs)
        # step 1: check extra spec value
        if provisioning:
            self._check_extra_spec_value(
                provisioning,
                self._client.provisioning_values.keys())
        if tiering:
            self._check_extra_spec_value(
                tiering,
                self._client.tiering_values.keys())

        # step 2: check extra spec combination
        self._check_extra_spec_combination(provisioning, tiering)
        return provisioning, tiering

    def _check_extra_spec_value(self, extra_spec, valid_values):
        """Checks whether an extra spec's value is valid."""

        if not extra_spec or not valid_values:
            LOG.error(_LE('The given extra_spec or valid_values is None.'))
        elif extra_spec not in valid_values:
            msg = _("The extra_spec: %s is invalid.") % extra_spec
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return

    def _get_extra_spec_value(self, extra_specs):
        """Gets EMC extra spec values."""
        provisioning = 'thick'
        tiering = None

        if self._client.provisioning_spec in extra_specs:
            provisioning = extra_specs[self._client.provisioning_spec].lower()
        if self._client.tiering_spec in extra_specs:
            tiering = extra_specs[self._client.tiering_spec].lower()

        return provisioning, tiering

    def _check_extra_spec_combination(self, provisioning, tiering):
        """Checks whether extra spec combination is valid."""
        enablers = self.enablers
        # check provisioning and tiering
        # deduplicated and tiering can not be both enabled
        if provisioning == 'deduplicated' and tiering is not None:
            msg = _("deduplicated and auto tiering can't be both enabled.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        elif provisioning == 'compressed' and '-Compression' not in enablers:
            msg = _("Compression Enabler is not installed. "
                    "Can not create compressed volume.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        elif provisioning == 'deduplicated' and \
                '-Deduplication' not in enablers:
            msg = _("Deduplication Enabler is not installed."
                    " Can not create deduplicated volume")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        elif provisioning in ['thin', 'deduplicated', 'compressed'] and \
                '-ThinProvisioning' not in enablers:
            msg = _("ThinProvisioning Enabler is not installed. "
                    "Can not create thin volume")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        elif tiering is not None and '-FAST' not in enablers:
            msg = _("FAST VP Enabler is not installed. "
                    "Can't set tiering policy for the volume")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return

    def delete_volume(self, volume):
        """Deletes an EMC volume."""
        try:
            self._client.delete_lun(volume['name'])
        except exception.EMCVnxCLICmdError as ex:
            orig_out = "\n".join(ex.kwargs["out"])
            if (self.force_delete_lun_in_sg and
                    (self._client.CLI_RESP_PATTERN_LUN_IN_SG_1 in orig_out or
                     self._client.CLI_RESP_PATTERN_LUN_IN_SG_2 in orig_out)):
                LOG.warning(_LW('LUN corresponding to %s is still '
                                'in some Storage Groups.'
                                'Try to bring the LUN out of Storage Groups '
                                'and retry the deletion.'),
                            volume['name'])
                lun_id = self.get_lun_id(volume)
                for hlu, sg in self._client.get_hlus(lun_id):
                    self._client.remove_hlu_from_storagegroup(hlu, sg)
                self._client.delete_lun(volume['name'])
            else:
                with excutils.save_and_reraise_exception():
                    # Reraise the original exceiption
                    pass

    def extend_volume(self, volume, new_size):
        """Extends an EMC volume."""
        self._client.expand_lun_and_wait(volume['name'], new_size)

    def _get_original_status(self, volume):
        if not volume['volume_attachment']:
            return 'available'
        else:
            return 'in-use'

    def _is_valid_for_storage_assisted_migration(
            self, volume, host, new_type=None):
        """Check the src and dest volume to decide the migration type."""
        false_ret = (False, None)

        if 'location_info' not in host['capabilities']:
            LOG.warning(_LW("Failed to get target_pool_name and "
                            "target_array_serial. 'location_info' "
                            "is not in host['capabilities']."))
            return false_ret

        # mandatory info should be ok
        info = host['capabilities']['location_info']
        LOG.debug("Host for migration is %s.", info)
        try:
            info_detail = info.split('|')
            target_pool_name = info_detail[0]
            target_array_serial = info_detail[1]
        except AttributeError:
            LOG.warning(_LW("Error on parsing target_pool_name/"
                            "target_array_serial."))
            return false_ret

        # source and destination should be on same array
        array_serial = self.get_array_serial()
        if target_array_serial != array_serial:
            LOG.debug('Skip storage-assisted migration because '
                      'target and source backend are not managing'
                      'the same array.')
            return false_ret

        if len(target_pool_name) == 0:
            # Destination host is using a legacy driver
            LOG.warning(_LW("Didn't get the pool information of the "
                            "host %(s). Storage assisted Migration is not "
                            "supported. The host may be using a legacy "
                            "driver."),
                        host['name'])
            return false_ret

        # Same protocol should be used if volume is in-use
        if host['capabilities']['storage_protocol'] != self.protocol \
                and self._get_original_status(volume) == 'in-use':
            LOG.debug('Skip storage-assisted migration because '
                      'in-use volume can not be '
                      'migrate between different protocols.')
            return false_ret

        return (True, target_pool_name)

    def migrate_volume(self, ctxt, volume, host, new_type=None):
        """Leverage the VNX on-array migration functionality.

        This method is invoked at the source backend.
        """
        false_ret = (False, None)
        is_valid, target_pool_name = \
            self._is_valid_for_storage_assisted_migration(
                volume, host, new_type)
        if not is_valid:
            return false_ret

        return self._migrate_volume(volume, target_pool_name, new_type)

    def _migrate_volume(self, volume, target_pool_name, new_type=None):
        LOG.debug("Starting real storage-assisted migration...")
        # first create a new volume with same name and size of source volume
        volume_name = volume['name']
        new_volume_name = "%(src)s-%(ts)s" % {'src': volume_name,
                                              'ts': int(time.time())}
        src_id = self.get_lun_id(volume)

        provisioning = 'thick'
        tiering = None
        if new_type:
            provisioning, tiering = self._get_extra_spec_value(
                new_type['extra_specs'])
        else:
            provisioning, tiering = self._get_extra_spec_value(
                self.get_volumetype_extraspecs(volume))

        data = self._client.create_lun_with_advance_feature(
            target_pool_name, new_volume_name, volume['size'],
            provisioning, tiering)

        dst_id = data['lun_id']
        moved = self._client.migrate_lun_with_verification(
            src_id, dst_id, new_volume_name)

        return moved, {}

    def retype(self, ctxt, volume, new_type, diff, host):
        new_specs = new_type['extra_specs']

        new_provisioning, new_tiering = (
            self._get_and_validate_extra_specs(new_specs))

        # Check what changes are needed
        migration, tiering_change = self.determine_changes_when_retype(
            volume, new_type, host)

        # Reject if volume has snapshot when migration is needed
        if migration and self._client.check_lun_has_snap(
                self.get_lun_id(volume)):
            LOG.debug('Driver is not able to do retype because the volume '
                      'has snapshot which is forbidden to migrate.')
            return False

        if migration:
            # Check whether the migration is valid
            is_valid, target_pool_name = (
                self._is_valid_for_storage_assisted_migration(
                    volume, host, new_type))
            if is_valid:
                if self._migrate_volume(
                        volume, target_pool_name, new_type)[0]:
                    return True
                else:
                    LOG.warning(_LW('Storage-assisted migration failed during '
                                    'retype.'))
                    return False
            else:
                # Migration is invalid
                LOG.debug('Driver is not able to do retype due to '
                          'storage-assisted migration is not valid '
                          'in this situation.')
                return False
        elif tiering_change:
            # Modify lun to change tiering policy
            self._client.modify_lun_tiering(volume['name'], new_tiering)
            return True
        else:
            return True

    def determine_changes_when_retype(self, volume, new_type, host):
        migration = False
        tiering_change = False

        old_specs = self.get_volumetype_extraspecs(volume)
        old_provisioning, old_tiering = self._get_extra_spec_value(
            old_specs)

        new_specs = new_type['extra_specs']
        new_provisioning, new_tiering = self._get_extra_spec_value(
            new_specs)

        if volume['host'] != host['host'] or \
                old_provisioning != new_provisioning:
            migration = True

        if new_tiering != old_tiering:
            tiering_change = True
        return migration, tiering_change

    def get_specific_extra_spec(self, specs, key):
        return specs.get(key, None)

    def determine_all_enablers_exist(self, enablers):
        """Determine all wanted enablers whether exist."""
        wanted = ['-ThinProvisioning',
                  '-Deduplication',
                  '-FAST',
                  '-Compression']
        for each in wanted:
            if each not in enablers:
                return False
        return True

    def _build_pool_stats(self, pool):
        pool_stats = {}
        pool_stats['pool_name'] = pool['pool_name']
        pool_stats['total_capacity_gb'] = pool['total_capacity_gb']
        pool_stats['reserved_percentage'] = 0
        pool_stats['free_capacity_gb'] = pool['free_capacity_gb']
        # Some extra capacity will be used by meta data of pool LUNs.
        # The overhead is about LUN_Capacity * 0.02 + 3 GB
        # reserved_percentage will be used to make sure the scheduler
        # takes the overhead into consideration.
        # Assume that all the remaining capacity is to be used to create
        # a thick LUN, reserved_percentage is estimated as follows:
        reserved = (((0.02 * pool['free_capacity_gb'] + 3) /
                     (1.02 * pool['total_capacity_gb'])) * 100)
        pool_stats['reserved_percentage'] = int(math.ceil(min(reserved, 100)))
        if self.check_max_pool_luns_threshold:
            pool_feature = self._client.get_pool_feature_properties(poll=False)
            if (pool_feature['max_pool_luns']
                    <= pool_feature['total_pool_luns']):
                LOG.warning(_LW("Maximum number of Pool LUNs, %s, "
                                "have been created. "
                                "No more LUN creation can be done."),
                            pool_feature['max_pool_luns'])
                pool_stats['free_capacity_gb'] = 0

        array_serial = self.get_array_serial()
        pool_stats['location_info'] = ('%(pool_name)s|%(array_serial)s' %
                                       {'pool_name': pool['pool_name'],
                                        'array_serial': array_serial})
        # Check if this pool's fast_cache is enabled
        if 'fast_cache_enabled' not in pool:
            pool_stats['fast_cache_enabled'] = 'False'
        else:
            pool_stats['fast_cache_enabled'] = pool['fast_cache_enabled']

        # Copy advanced feature stats from backend stats
        pool_stats['compression_support'] = self.stats['compression_support']
        pool_stats['fast_support'] = self.stats['fast_support']
        pool_stats['deduplication_support'] = (
            self.stats['deduplication_support'])
        pool_stats['thinprovisioning_support'] = (
            self.stats['thinprovisioning_support'])
        pool_stats['consistencygroup_support'] = (
            self.stats['consistencygroup_support'])

        return pool_stats

    @log_enter_exit
    def update_volume_stats(self):
        """Gets the common stats shared by pool and array backend."""
        if not self.determine_all_enablers_exist(self.enablers):
            self.enablers = self._client.get_enablers_on_array()

        self.stats['compression_support'] = (
            'True' if '-Compression' in self.enablers else 'False')

        self.stats['fast_support'] = (
            'True' if '-FAST' in self.enablers else 'False')

        self.stats['deduplication_support'] = (
            'True' if '-Deduplication' in self.enablers else 'False')

        self.stats['thinprovisioning_support'] = (
            'True' if '-ThinProvisioning' in self.enablers else 'False')

        self.stats['consistencygroup_support'] = (
            'True' if '-VNXSnapshots' in self.enablers else 'False')

        if self.protocol == 'iSCSI':
            self.iscsi_targets = self._client.get_iscsi_targets(poll=False)

        return self.stats

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        snapshot_name = snapshot['name']
        volume_name = snapshot['volume_name']
        volume = snapshot['volume']
        LOG.info(_LI('Create snapshot: %(snapshot)s: volume: %(volume)s'),
                 {'snapshot': snapshot_name,
                  'volume': volume_name})
        lun_id = self.get_lun_id(volume)
        self._client.create_snapshot(lun_id, snapshot_name)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        snapshot_name = snapshot['name']

        LOG.info(_LI('Delete Snapshot: %(snapshot)s'),
                 {'snapshot': snapshot_name})

        self._client.delete_snapshot(snapshot_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Constructs a work flow to create a volume from snapshot.

        This flow will do the following:

        1. Create a snap mount point (SMP) for the snapshot.
        2. Attach the snapshot to the SMP created in the first step.
        3. Create a temporary lun prepare for migration.
        4. Start a migration between the SMP and the temp lun.
        """
        self._volume_creation_check(volume)
        flow_name = 'create_volume_from_snapshot'
        work_flow = linear_flow.Flow(flow_name)
        store_spec = self._construct_store_spec(volume, snapshot)
        work_flow.add(CreateSMPTask(),
                      AttachSnapTask(),
                      CreateDestLunTask(),
                      MigrateLunTask())
        flow_engine = taskflow.engines.load(work_flow,
                                            store=store_spec)
        flow_engine.run()
        new_lun_id = flow_engine.storage.fetch('new_lun_id')
        model_update = {'provider_location':
                        self._build_provider_location_for_lun(new_lun_id)}
        volume_host = volume['host']
        host = vol_utils.extract_host(volume_host, 'backend')
        host_and_pool = vol_utils.append_host(host, store_spec['pool_name'])
        if volume_host != host_and_pool:
            model_update['host'] = host_and_pool

        return model_update

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        self._volume_creation_check(volume)
        source_volume_name = src_vref['name']
        source_lun_id = self.get_lun_id(src_vref)
        volume_size = src_vref['size']
        consistencygroup_id = src_vref['consistencygroup_id']
        snapshot_name = 'tmp-snap-%s' % volume['id']
        tmp_cgsnapshot_name = None
        if consistencygroup_id:
            tmp_cgsnapshot_name = 'tmp-cgsnapshot-%s' % volume['id']

        snapshot = {
            'name': snapshot_name,
            'volume_name': source_volume_name,
            'volume_size': volume_size,
            'volume': src_vref,
            'cgsnapshot_id': tmp_cgsnapshot_name,
            'consistencygroup_id': consistencygroup_id,
            'id': tmp_cgsnapshot_name
        }
        store_spec = self._construct_store_spec(volume, snapshot)
        flow_name = 'create_cloned_volume'
        work_flow = linear_flow.Flow(flow_name)
        store_spec.update({'snapshot': snapshot})
        store_spec.update({'source_lun_id': source_lun_id})
        work_flow.add(CreateSnapshotTask(),
                      CreateSMPTask(),
                      AttachSnapTask(),
                      CreateDestLunTask(),
                      MigrateLunTask())
        flow_engine = taskflow.engines.load(work_flow,
                                            store=store_spec)
        flow_engine.run()
        new_lun_id = flow_engine.storage.fetch('new_lun_id')
        # Delete temp Snapshot
        if consistencygroup_id:
            self._client.delete_cgsnapshot(snapshot)
        else:
            self.delete_snapshot(snapshot)

        model_update = {'provider_location':
                        self._build_provider_location_for_lun(new_lun_id)}
        volume_host = volume['host']
        host = vol_utils.extract_host(volume_host, 'backend')
        host_and_pool = vol_utils.append_host(host, store_spec['pool_name'])
        if volume_host != host_and_pool:
            model_update['host'] = host_and_pool

        return model_update

    def dumps_provider_location(self, pl_dict):
        return '|'.join([k + '^' + pl_dict[k] for k in pl_dict])

    def _build_provider_location_for_lun(self, lun_id):
        pl_dict = {'system': self.get_array_serial(),
                   'type': 'lun',
                   'id': six.text_type(lun_id),
                   'version': self.VERSION}
        return self.dumps_provider_location(pl_dict)

    def _extract_provider_location_for_lun(self, provider_location, key='id'):
        """Extacts value of the specified field from provider_location string.

        :param provider_location: provider_location string
        :param key: field name of the value that to be extracted
        :return: value of the specified field if it exists, otherwise,
                 None is returned
        """

        kvps = provider_location.split('|')
        for kvp in kvps:
            fields = kvp.split('^')
            if len(fields) == 2 and fields[0] == key:
                return fields[1]

    def _consistencygroup_creation_check(self, group):
        """Check extra spec for consistency group."""

        if group.get('volume_type_id') is not None:
            for id in group['volume_type_id'].split(","):
                if id:
                    provisioning, tiering = self._get_extra_spec_value(
                        volume_types.get_volume_type_extra_specs(id))
                    if provisioning == 'compressed':
                        msg = _("Failed to create consistency group %s "
                                "because VNX consistency group cannot "
                                "accept compressed LUNs as members."
                                ) % group['id']
                        raise exception.VolumeBackendAPIException(data=msg)

    def create_consistencygroup(self, context, group):
        """Creates a consistency group."""
        LOG.info(_LI('Start to create consistency group: %(group_name)s '
                     'id: %(id)s'),
                 {'group_name': group['name'], 'id': group['id']})

        self._consistencygroup_creation_check(group)

        model_update = {'status': 'available'}
        try:
            self._client.create_consistencygroup(context, group)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Create consistency group %s failed.'),
                          group['id'])

        return model_update

    def delete_consistencygroup(self, driver, context, group):
        """Deletes a consistency group."""
        cg_name = group['id']
        volumes = driver.db.volume_get_all_by_group(context, group['id'])

        model_update = {}
        model_update['status'] = group['status']
        LOG.info(_LI('Start to delete consistency group: %(cg_name)s'),
                 {'cg_name': cg_name})
        try:
            self._client.delete_consistencygroup(cg_name)
        except Exception:
            with excutils.save_and_reraise_exception():
                msg = (_('Delete consistency group %s failed.')
                       % cg_name)
                LOG.error(msg)

        for volume_ref in volumes:
            try:
                self._client.delete_lun(volume_ref['name'])
                volume_ref['status'] = 'deleted'
            except Exception:
                volume_ref['status'] = 'error_deleting'
                model_update['status'] = 'error_deleting'

        return model_update, volumes

    def update_consistencygroup(self, context,
                                group,
                                add_volumes,
                                remove_volumes):
        """Adds or removes LUN(s) to/from an existing consistency group"""
        model_update = {'status': 'available'}
        cg_name = group['id']
        add_ids = [six.text_type(self.get_lun_id(vol))
                   for vol in add_volumes] if add_volumes else []
        remove_ids = [six.text_type(self.get_lun_id(vol))
                      for vol in remove_volumes] if remove_volumes else []

        data = self._client.get_consistency_group_by_name(cg_name)
        ids_curr = data['Luns']
        ids_later = []

        if ids_curr:
            ids_later.extend(ids_curr)
        ids_later.extend(add_ids)
        for remove_id in remove_ids:
            if remove_id in ids_later:
                ids_later.remove(remove_id)
            else:
                LOG.warning(_LW("LUN with id %(remove_id)s is not present "
                                "in cg %(cg_name)s, skip it."),
                            {'remove_id': remove_id, 'cg_name': cg_name})
        # Remove all from cg
        if not ids_later:
            self._client.remove_luns_from_consistencygroup(cg_name,
                                                           ids_curr)
        else:
            self._client.replace_luns_in_consistencygroup(cg_name,
                                                          ids_later)
        return model_update, None, None

    def create_cgsnapshot(self, driver, context, cgsnapshot):
        """Creates a cgsnapshot (snap group)."""
        cgsnapshot_id = cgsnapshot['id']
        snapshots = driver.db.snapshot_get_all_for_cgsnapshot(
            context, cgsnapshot_id)

        model_update = {}
        LOG.info(_LI('Start to create cgsnapshot for consistency group'
                     ': %(group_name)s'),
                 {'group_name': cgsnapshot['consistencygroup_id']})

        try:
            self._client.create_cgsnapshot(cgsnapshot)
            for snapshot in snapshots:
                snapshot['status'] = 'available'
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Create cg snapshot %s failed.'),
                          cgsnapshot_id)

        model_update['status'] = 'available'

        return model_update, snapshots

    def delete_cgsnapshot(self, driver, context, cgsnapshot):
        """Deletes a cgsnapshot (snap group)."""
        cgsnapshot_id = cgsnapshot['id']
        snapshots = driver.db.snapshot_get_all_for_cgsnapshot(
            context, cgsnapshot_id)

        model_update = {}
        model_update['status'] = cgsnapshot['status']
        LOG.info(_LI('Delete cgsnapshot %(snap_name)s for consistency group: '
                     '%(group_name)s'), {'snap_name': cgsnapshot['id'],
                 'group_name': cgsnapshot['consistencygroup_id']})

        try:
            self._client.delete_cgsnapshot(cgsnapshot)
            for snapshot in snapshots:
                snapshot['status'] = 'deleted'
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Delete cgsnapshot %s failed.'),
                          cgsnapshot_id)

        return model_update, snapshots

    def get_lun_id_by_name(self, volume_name):
        data = self._client.get_lun_by_name(volume_name)
        return data['lun_id']

    def get_lun_id(self, volume):
        lun_id = None
        try:
            provider_location = volume.get('provider_location')
            if provider_location:
                lun_id = self._extract_provider_location_for_lun(
                    provider_location,
                    'id')
            if lun_id:
                lun_id = int(lun_id)
            else:
                LOG.debug('Lun id is not stored in provider location, '
                          'query it.')
                lun_id = self._client.get_lun_by_name(volume['name'])['lun_id']
        except Exception as ex:
            LOG.debug('Exception when getting lun id: %s.', six.text_type(ex))
            lun_id = self._client.get_lun_by_name(volume['name'])['lun_id']
        LOG.debug('Get lun_id: %s.', lun_id)
        return lun_id

    def get_lun_map(self, storage_group):
        data = self._client.get_storage_group(storage_group)
        return data['lunmap']

    def get_storage_group_uid(self, name):
        data = self._client.get_storage_group(name)
        return data['storage_group_uid']

    def assure_storage_group(self, storage_group):
        self._client.create_storage_group(storage_group)

    def assure_host_in_storage_group(self, hostname, storage_group):
        try:
            self._client.connect_host_to_storage_group(hostname, storage_group)
        except exception.EMCVnxCLICmdError as ex:
            if ex.kwargs["rc"] == 83:
                # SG was not created or was destroyed by another concurrent
                # operation before connected.
                # Create SG and try to connect again
                LOG.warning(_LW('Storage Group %s is not found. Create it.'),
                            storage_group)
                self.assure_storage_group(storage_group)
                self._client.connect_host_to_storage_group(
                    hostname, storage_group)
            else:
                raise ex
        return hostname

    def get_lun_owner(self, volume):
        """Returns SP owner of the volume."""
        data = self._client.get_lun_by_name(volume['name'],
                                            poll=False)
        owner_sp = data['owner']
        LOG.debug('Owner SP : %s', owner_sp)
        return owner_sp

    def filter_available_hlu_set(self, used_hlus):
        used_hlu_set = set(used_hlus)
        return self.hlu_set - used_hlu_set

    def _extract_iscsi_uids(self, connector):
        if 'initiator' not in connector:
            if self.protocol == 'iSCSI':
                msg = (_('Host %s has no iSCSI initiator')
                       % connector['host'])
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                return ()
        return [connector['initiator']]

    def _extract_fc_uids(self, connector):
        if 'wwnns' not in connector or 'wwpns' not in connector:
            if self.protocol == 'FC':
                msg = _('Host %s has no FC initiators') % connector['host']
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                return ()
        wwnns = connector['wwnns']
        wwpns = connector['wwpns']
        wwns = [(node + port).upper() for node, port in zip(wwnns, wwpns)]
        return map(lambda wwn: re.sub(r'\S\S',
                                      lambda m: m.group(0) + ':',
                                      wwn,
                                      len(wwn) / 2 - 1),
                   wwns)

    def _exec_command_setpath(self, initiator_uid, sp, port_id,
                              ip, host, vport_id=None):
        gname = host
        if vport_id is not None:
            cmd_iscsi_setpath = ('storagegroup', '-gname', gname, '-setpath',
                                 '-hbauid', initiator_uid, '-sp', sp,
                                 '-spport', port_id, '-spvport', vport_id,
                                 '-ip', ip, '-host', host, '-o')
            out, rc = self._client.command_execute(*cmd_iscsi_setpath)
        else:
            cmd_fc_setpath = ('storagegroup', '-gname', gname, '-setpath',
                              '-hbauid', initiator_uid, '-sp', sp,
                              '-spport', port_id,
                              '-ip', ip, '-host', host, '-o')
            out, rc = self._client.command_execute(*cmd_fc_setpath)
        if rc != 0:
            LOG.warning(_LW("Failed to register %(itor)s to SP%(sp)s "
                            "port %(portid)s because: %(msg)s."),
                        {'itor': initiator_uid,
                         'sp': sp,
                         'portid': port_id,
                         'msg': out})

    def _register_iscsi_initiator(self, ip, host, initiator_uids):
        iscsi_targets = self.iscsi_targets
        for initiator_uid in initiator_uids:
            LOG.info(_LI('Get ISCSI targets %(tg)s to register '
                         'initiator %(in)s.'),
                     {'tg': iscsi_targets,
                      'in': initiator_uid})

            target_portals_SPA = list(iscsi_targets['A'])
            target_portals_SPB = list(iscsi_targets['B'])

            for pa in target_portals_SPA:
                sp = 'A'
                port_id = pa['Port ID']
                vport_id = pa['Virtual Port ID']
                self._exec_command_setpath(initiator_uid, sp, port_id,
                                           ip, host, vport_id)

            for pb in target_portals_SPB:
                sp = 'B'
                port_id = pb['Port ID']
                vport_id = pb['Virtual Port ID']
                self._exec_command_setpath(initiator_uid, sp, port_id,
                                           ip, host, vport_id)

    def _register_fc_initiator(self, ip, host, initiator_uids):
        fc_targets = self._client.get_fc_targets()
        for initiator_uid in initiator_uids:
            LOG.info(_LI('Get FC targets %(tg)s to register '
                         'initiator %(in)s.'),
                     {'tg': fc_targets,
                      'in': initiator_uid})

            target_portals_SPA = list(fc_targets['A'])
            target_portals_SPB = list(fc_targets['B'])

            for pa in target_portals_SPA:
                sp = 'A'
                port_id = pa['Port ID']
                self._exec_command_setpath(initiator_uid, sp, port_id,
                                           ip, host)

            for pb in target_portals_SPB:
                sp = 'B'
                port_id = pb['Port ID']
                self._exec_command_setpath(initiator_uid, sp, port_id,
                                           ip, host)

    def _deregister_initiators(self, connector):
        initiator_uids = []
        try:
            if self.protocol == 'iSCSI':
                initiator_uids = self._extract_iscsi_uids(connector)
            elif self.protocol == 'FC':
                initiator_uids = self._extract_fc_uids(connector)
        except exception.VolumeBackendAPIException:
            LOG.warning(_LW("Failed to extract initiators of %s, so ignore "
                            "deregistration operation."),
                        connector['host'])
        if initiator_uids:
            for initiator_uid in initiator_uids:
                rc, out = self._client.deregister_initiator(initiator_uid)
                if rc != 0:
                    LOG.warning(_LW("Failed to deregister %(itor)s "
                                    "because: %(msg)s."),
                                {'itor': initiator_uid,
                                 'msg': out})

    def _filter_unregistered_initiators(self, initiator_uids, sgdata):
        unregistered_initiators = []
        if not initiator_uids:
            return unregistered_initiators

        out = sgdata['raw_output']

        for initiator_uid in initiator_uids:
            m = re.search(initiator_uid, out)
            if m is None:
                unregistered_initiators.append(initiator_uid)
        return unregistered_initiators

    def auto_register_initiator(self, connector, sgdata):
        """Automatically registers available initiators.

        Returns True if has registered initiator otherwise returns False.
        """
        initiator_uids = []
        ip = connector['ip']
        host = connector['host']
        if self.protocol == 'iSCSI':
            initiator_uids = self._extract_iscsi_uids(connector)
            if sgdata is not None:
                itors_toReg = self._filter_unregistered_initiators(
                    initiator_uids,
                    sgdata)
            else:
                itors_toReg = initiator_uids

            if len(itors_toReg) == 0:
                return False

            LOG.info(_LI('iSCSI Initiators %(in)s of %(ins)s '
                         'need registration.'),
                     {'in': itors_toReg,
                      'ins': initiator_uids})
            self._register_iscsi_initiator(ip, host, itors_toReg)
            return True

        elif self.protocol == 'FC':
            initiator_uids = self._extract_fc_uids(connector)
            if sgdata is not None:
                itors_toReg = self._filter_unregistered_initiators(
                    initiator_uids,
                    sgdata)
            else:
                itors_toReg = initiator_uids

            if len(itors_toReg) == 0:
                return False

            LOG.info(_LI('FC Initiators %(in)s of %(ins)s need registration'),
                     {'in': itors_toReg,
                      'ins': initiator_uids})
            self._register_fc_initiator(ip, host, itors_toReg)
            return True

    def assure_host_access(self, volume, connector):
        hostname = connector['host']
        volumename = volume['name']
        auto_registration_done = False
        try:
            sgdata = self._client.get_storage_group(hostname,
                                                    poll=False)
        except exception.EMCVnxCLICmdError as ex:
            if ex.kwargs["rc"] != 83:
                raise ex
            # Storage Group has not existed yet
            self.assure_storage_group(hostname)
            if self.itor_auto_reg:
                self.auto_register_initiator(connector, None)
                auto_registration_done = True
            else:
                self._client.connect_host_to_storage_group(hostname, hostname)

            sgdata = self._client.get_storage_group(hostname,
                                                    poll=True)

        if self.itor_auto_reg and not auto_registration_done:
            new_registerred = self.auto_register_initiator(connector, sgdata)
            if new_registerred:
                sgdata = self._client.get_storage_group(hostname,
                                                        poll=True)

        lun_id = self.get_lun_id(volume)
        tried = 0
        while tried < self.max_retries:
            tried += 1
            lun_map = sgdata['lunmap']
            used_hlus = lun_map.values()
            candidate_hlus = self.filter_available_hlu_set(used_hlus)
            candidate_hlus = list(candidate_hlus)

            if len(candidate_hlus) != 0:
                hlu = candidate_hlus[random.randint(0,
                                                    len(candidate_hlus) - 1)]
                try:
                    self._client.add_hlu_to_storage_group(
                        hlu,
                        lun_id,
                        hostname)

                    if hostname not in self.hlu_cache:
                        self.hlu_cache[hostname] = {}
                    self.hlu_cache[hostname][lun_id] = hlu
                    return hlu, sgdata
                except exception.EMCVnxCLICmdError as ex:
                    LOG.debug("Add HLU to storagegroup failed, retry %s",
                              tried)
            elif tried == 1:
                # The first try didn't get the in time data,
                # so we need a retry
                LOG.debug("Did not find candidate HLUs, retry %s",
                          tried)
            else:
                msg = (_('Reach limitation set by configuration '
                         'option max_luns_per_storage_group. '
                         'Operation to add %(vol)s into '
                         'Storage Group %(sg)s is rejected.')
                       % {'vol': volumename, 'sg': hostname})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            # Need a full poll to get the real in time data
            # Query storage group with poll for retry
            sgdata = self._client.get_storage_group(hostname, poll=True)
            self.hlu_cache[hostname] = sgdata['lunmap']
            if lun_id in sgdata['lunmap']:
                hlu = sgdata['lunmap'][lun_id]
                return hlu, sgdata

        msg = _("Failed to add %(vol)s into %(sg)s "
                "after %(retries)s tries.") % \
            {'vol': volumename,
             'sg': hostname,
             'retries': tried}
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def vnx_get_iscsi_properties(self, volume, connector, hlu, sg_raw_output):
        storage_group = connector['host']
        multipath = connector.get('multipath', False)
        owner_sp = self.get_lun_owner(volume)
        registered_spports = self._client.get_registered_spport_set(
            connector['initiator'],
            storage_group,
            sg_raw_output)
        targets = self._client.find_available_iscsi_targets(
            storage_group, owner_sp,
            registered_spports,
            self.iscsi_targets,
            multipath)

        properties = {}

        if not multipath:
            properties = {'target_discovered': False,
                          'target_iqn': 'unknown',
                          'target_portal': 'unknown',
                          'target_lun': 'unknown',
                          'volume_id': volume['id']}
            if targets:
                properties['target_discovered'] = True
                properties['target_iqn'] = targets[0]['Port WWN']
                properties['target_portal'] = \
                    "%s:3260" % targets[0]['IP Address']
                properties['target_lun'] = hlu

                auth = volume['provider_auth']
                if auth:
                    (auth_method, auth_username, auth_secret) = auth.split()
                    properties['auth_method'] = auth_method
                    properties['auth_username'] = auth_username
                    properties['auth_password'] = auth_secret
        else:
            properties = {'target_discovered': False,
                          'target_iqns': None,
                          'target_portals': None,
                          'target_luns': None,
                          'volume_id': volume['id']}
            if targets:
                properties['target_discovered'] = True
                properties['target_iqns'] = [t['Port WWN'] for t in targets]
                properties['target_portals'] = [
                    "%s:3260" % t['IP Address'] for t in targets]
                properties['target_luns'] = [hlu] * len(targets)

        if not targets:
            LOG.error(_LE('Failed to find available iSCSI targets for %s.'),
                      storage_group)

        return properties

    def vnx_get_fc_properties(self, connector, device_number):
        fc_properties = {'target_lun': device_number,
                         'target_dicovered': True,
                         'target_wwn': None}
        if self.zonemanager_lookup_service is None:
            fc_properties['target_wwn'] = self.get_login_ports(connector)
        else:
            target_wwns, itor_tgt_map = self.get_initiator_target_map(
                connector['wwpns'],
                self.get_status_up_ports(connector))
            fc_properties['target_wwn'] = target_wwns
            fc_properties['initiator_target_map'] = itor_tgt_map
        return fc_properties

    def initialize_connection(self, volume, connector):
        volume_metadata = {}
        for metadata in volume['volume_admin_metadata']:
            volume_metadata[metadata['key']] = metadata['value']
        access_mode = volume_metadata.get('attached_mode')
        if access_mode is None:
            access_mode = ('ro'
                           if volume_metadata.get('readonly') == 'True'
                           else 'rw')
        LOG.debug('Volume %(vol)s Access mode is: %(access)s.',
                  {'vol': volume['name'],
                   'access': access_mode})

        """Initializes the connection and returns connection info."""
        @lockutils.synchronized('emc-connection-' + connector['host'],
                                "emc-connection-", True)
        def do_initialize_connection():
            return self.assure_host_access(
                volume, connector)

        if self.protocol == 'iSCSI':
            (device_number, sg_data) = do_initialize_connection()
            iscsi_properties = self.vnx_get_iscsi_properties(
                volume,
                connector,
                device_number,
                sg_data['raw_output']
            )
            iscsi_properties['access_mode'] = access_mode
            data = {'driver_volume_type': 'iscsi',
                    'data': iscsi_properties}
        elif self.protocol == 'FC':
            (device_number, sg_data) = do_initialize_connection()
            fc_properties = self.vnx_get_fc_properties(connector,
                                                       device_number)
            fc_properties['volume_id'] = volume['id']
            fc_properties['access_mode'] = access_mode
            data = {'driver_volume_type': 'fibre_channel',
                    'data': fc_properties}

        return data

    def terminate_connection(self, volume, connector):
        """Disallow connection from connector."""
        @lockutils.synchronized('emc-connection-' + connector['host'],
                                "emc-connection-", True)
        def do_terminate_connection():
            hostname = connector['host']
            volume_name = volume['name']
            lun_id = self.get_lun_id(volume)
            lun_map = None
            conn_info = None
            if (hostname in self.hlu_cache and
                    lun_id in self.hlu_cache[hostname] and
                    not self.destroy_empty_sg and
                    not self.zonemanager_lookup_service):
                hlu = self.hlu_cache[hostname][lun_id]
                self._client.remove_hlu_from_storagegroup(hlu, hostname,
                                                          poll=True)
                self.hlu_cache[hostname].pop(lun_id)
            else:
                try:
                    lun_map = self.get_lun_map(hostname)
                    self.hlu_cache[hostname] = lun_map
                except exception.EMCVnxCLICmdError as ex:
                    if ex.kwargs["rc"] == 83:
                        LOG.warning(_LW("Storage Group %s is not found. "
                                        "terminate_connection() is "
                                        "unnecessary."),
                                    hostname)
                if lun_id in lun_map:
                    self._client.remove_hlu_from_storagegroup(
                        lun_map[lun_id], hostname)
                    lun_map.pop(lun_id)
                else:
                    LOG.warning(_LW("Volume %(vol)s was not in Storage Group"
                                    " %(sg)s."),
                                {'vol': volume_name, 'sg': hostname})

            if self.protocol == 'FC':
                conn_info = {'driver_volume_type': 'fibre_channel',
                             'data': {}}
                if self.zonemanager_lookup_service and not lun_map:
                    target_wwns, itor_tgt_map = self.get_initiator_target_map(
                        connector['wwpns'],
                        self.get_status_up_ports(connector))
                    conn_info['data']['initiator_target_map'] = itor_tgt_map

            if self.destroy_empty_sg and not lun_map:
                try:
                    LOG.info(_LI("Storage Group %s was empty."), hostname)
                    self._client.disconnect_host_from_storage_group(
                        hostname, hostname)
                    self._client.delete_storage_group(hostname)
                    if self.itor_auto_dereg:
                        self._deregister_initiators(connector)
                except Exception:
                    LOG.warning(_LW("Failed to destroy Storage Group %s."),
                                hostname)
                    try:
                        self._client.connect_host_to_storage_group(
                            hostname, hostname)
                    except Exception:
                        LOG.warning(_LW("Fail to connect host %(host)s "
                                        "back to storage group %(sg)s."),
                                    {'host': hostname, 'sg': hostname})
            return conn_info
        return do_terminate_connection()

    def manage_existing_get_size(self, volume, ref):
        """Returns size of volume to be managed by manage_existing."""

        # Check that the reference is valid
        if 'id' not in ref:
            reason = _('Reference must contain lun_id element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref,
                reason=reason)

        # Check for existence of the lun
        data = self._client.get_lun_by_id(
            ref['id'],
            properties=self._client.LUN_WITH_POOL)
        if data is None:
            reason = _('Find no lun with the specified id %s.') % ref['id']
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)

        pool = self.get_target_storagepool(volume, None)
        if pool and data['pool'] != pool:
            reason = (_('The input lun %(lun_id)s is in pool %(poolname)s '
                        'which is not managed by the host %(host)s.')
                      % {'lun_id': ref['id'],
                         'poolname': data['pool'],
                         'host': volume['host']})
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)
        return data['total_capacity_gb']

    def manage_existing(self, volume, ref):
        """Imports the existing backend storage object as a volume.

        Renames the backend storage object so that it matches the,
        volume['name'] which is how drivers traditionally map between a
        cinder volume and the associated backend storage object.

        existing_ref:{
            'id':lun_id
        }
        """

        self._client.lun_rename(ref['id'], volume['name'])
        model_update = {'provider_location':
                        self._build_provider_location_for_lun(ref['id'])}

        return model_update

    def find_iscsi_protocol_endpoints(self, device_sp):
        """Returns the iSCSI initiators for a SP."""
        return self._client.get_iscsi_protocol_endpoints(device_sp)

    def get_login_ports(self, connector):
        return self._client.get_login_ports(connector['host'],
                                            connector['wwpns'])

    def get_status_up_ports(self, connector):
        return self._client.get_status_up_ports(connector['host'])

    def get_initiator_target_map(self, fc_initiators, fc_targets):
        target_wwns = []
        itor_tgt_map = {}

        if self.zonemanager_lookup_service:
            mapping = \
                self.zonemanager_lookup_service. \
                get_device_mapping_from_network(fc_initiators, fc_targets)
            for each in mapping:
                map_d = mapping[each]
                target_wwns.extend(map_d['target_port_wwn_list'])
                for initiator in map_d['initiator_port_wwn_list']:
                    itor_tgt_map[initiator] = map_d['target_port_wwn_list']
        return list(set(target_wwns)), itor_tgt_map

    def get_volumetype_extraspecs(self, volume):
        specs = {}

        type_id = volume['volume_type_id']
        if type_id is not None:
            specs = volume_types.get_volume_type_extra_specs(type_id)

        return specs

    def get_pool(self, volume):
        """Returns the pool name of a volume."""

        data = self._client.get_lun_by_name(volume['name'],
                                            [self._client.LUN_POOL],
                                            poll=False)
        return data.get(self._client.LUN_POOL.key)

    def unmanage(self, volume):
        """Unmanages a volume"""
        pass


@decorate_all_methods(log_enter_exit)
class EMCVnxCliPool(EMCVnxCliBase):

    def __init__(self, prtcl, configuration):
        super(EMCVnxCliPool, self).__init__(prtcl, configuration=configuration)
        self.storage_pool = configuration.storage_vnx_pool_name.strip()
        self._client.get_pool(self.storage_pool)

    def get_target_storagepool(self,
                               volume,
                               source_volume=None):
        return self.storage_pool

    def update_volume_stats(self):
        """Retrieves stats info."""
        super(EMCVnxCliPool, self).update_volume_stats()
        if '-FASTCache' in self.enablers:
            properties = [self._client.POOL_FREE_CAPACITY,
                          self._client.POOL_TOTAL_CAPACITY,
                          self._client.POOL_FAST_CACHE]
        else:
            properties = [self._client.POOL_FREE_CAPACITY,
                          self._client.POOL_TOTAL_CAPACITY]

        pool = self._client.get_pool(self.storage_pool,
                                     properties=properties,
                                     poll=False)
        self.stats['pools'] = [self._build_pool_stats(pool)]
        return self.stats


@decorate_all_methods(log_enter_exit)
class EMCVnxCliArray(EMCVnxCliBase):

    def __init__(self, prtcl, configuration):
        super(EMCVnxCliArray, self).__init__(prtcl,
                                             configuration=configuration)

    def get_target_storagepool(self, volume, source_volume=None):
        pool = vol_utils.extract_host(volume['host'], 'pool')

        # For new created volume that is not from snapshot or cloned,
        # just use the pool selected by scheduler
        if not source_volume:
            return pool

        # For volume created from snapshot or cloned from volume, the pool to
        # use depends on the source volume version. If the source volume is
        # created by older version of driver which doesn't support pool
        # scheduler, use the pool where the source volume locates. Otherwise,
        # use the pool selected by scheduler
        provider_location = source_volume.get('provider_location')

        if (provider_location and
                self._extract_provider_location_for_lun(provider_location,
                                                        'version')):
            return pool
        else:
            LOG.warning(_LW("The source volume is a legacy volume. "
                            "Create volume in the pool where the source "
                            "volume %s is created."),
                        source_volume['name'])
            data = self._client.get_lun_by_name(source_volume['name'],
                                                [self._client.LUN_POOL],
                                                poll=False)
            if data is None:
                msg = (_("Failed to find storage pool for source volume %s.")
                       % source_volume['name'])
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            return data[self._client.LUN_POOL.key]

    def update_volume_stats(self):
        """Retrieves stats info."""
        super(EMCVnxCliArray, self).update_volume_stats()
        if '-FASTCache' in self.enablers:
            properties = [self._client.POOL_FREE_CAPACITY,
                          self._client.POOL_TOTAL_CAPACITY,
                          self._client.POOL_FAST_CACHE]
        else:
            properties = [self._client.POOL_FREE_CAPACITY,
                          self._client.POOL_TOTAL_CAPACITY]
        pool_list = self._client.get_pool_list(properties, False)

        self.stats['pools'] = map(lambda pool: self._build_pool_stats(pool),
                                  pool_list)
        return self.stats


def getEMCVnxCli(prtcl, configuration=None):
    configuration.append_config_values(loc_opts)
    pool_name = configuration.safe_get("storage_vnx_pool_name")

    if pool_name is None or len(pool_name.strip()) == 0:
        return EMCVnxCliArray(prtcl, configuration=configuration)
    else:
        return EMCVnxCliPool(prtcl, configuration=configuration)


class CreateSMPTask(task.Task):
    """Creates a snap mount point (SMP) for the source snapshot.

    Reversion strategy: Delete the SMP.
    """
    def execute(self, client, volume, source_vol_name, *args, **kwargs):
        LOG.debug('CreateSMPTask.execute')
        client.create_mount_point(source_vol_name, volume['name'])

    def revert(self, result, client, volume, *args, **kwargs):
        LOG.debug('CreateSMPTask.revert')
        if isinstance(result, failure.Failure):
            return
        else:
            LOG.warning(_LW('CreateSMPTask.revert: delete mount point %s'),
                        volume['name'])
            client.delete_lun(volume['name'])


class AttachSnapTask(task.Task):
    """Attaches the snapshot to the SMP created before.

    Reversion strategy: Detach the SMP.
    """
    def execute(self, client, volume, snap_name, *args, **kwargs):
        LOG.debug('AttachSnapTask.execute')
        client.attach_mount_point(volume['name'], snap_name)

    def revert(self, result, client, volume, *args, **kwargs):
        LOG.debug('AttachSnapTask.revert')
        if isinstance(result, failure.Failure):
            return
        else:
            LOG.warning(_LW('AttachSnapTask.revert: detach mount point %s'),
                        volume['name'])
            client.detach_mount_point(volume['name'])


class CreateDestLunTask(task.Task):
    """Creates a destination lun for migration.

    Reversion strategy: Delete the temp destination lun.
    """
    def __init__(self):
        super(CreateDestLunTask, self).__init__(provides='lun_data')

    def execute(self, client, pool_name, dest_vol_name, volume_size,
                provisioning, tiering, *args, **kwargs):
        LOG.debug('CreateDestLunTask.execute')
        data = client.create_lun_with_advance_feature(
            pool_name, dest_vol_name, volume_size,
            provisioning, tiering)
        return data

    def revert(self, result, client, dest_vol_name, *args, **kwargs):
        LOG.debug('CreateDestLunTask.revert')
        if isinstance(result, failure.Failure):
            return
        else:
            LOG.warning(_LW('CreateDestLunTask.revert: delete temp lun %s'),
                        dest_vol_name)
            client.delete_lun(dest_vol_name)


class MigrateLunTask(task.Task):
    """Starts a migration between the SMP and the temp lun.

    Reversion strategy: None
    """
    def __init__(self):
        super(MigrateLunTask, self).__init__(provides='new_lun_id')

    def execute(self, client, dest_vol_name, volume, lun_data,
                *args, **kwargs):
        LOG.debug('MigrateLunTask.execute')
        new_vol_name = volume['name']
        new_vol_lun_id = client.get_lun_by_name(new_vol_name)['lun_id']
        dest_vol_lun_id = lun_data['lun_id']

        LOG.info(_LI('Migrating Mount Point Volume: %s'), new_vol_name)

        migrated = client.migrate_lun_with_verification(new_vol_lun_id,
                                                        dest_vol_lun_id,
                                                        None)
        if not migrated:
            msg = (_LE("Migrate volume failed between source vol %(src)s"
                       " and dest vol %(dst)s."),
                   {'src': new_vol_name, 'dst': dest_vol_name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return new_vol_lun_id

    def revert(self, *args, **kwargs):
        pass


class CreateSnapshotTask(task.Task):
    """Creates a snapshot/cgsnapshot of a volume.

    Reversion Strategy: Delete the created snapshot/cgsnapshot.
    """
    def execute(self, client, snapshot, source_lun_id, *args, **kwargs):
        LOG.debug('CreateSnapshotTask.execute')
        # Create temp Snapshot
        if snapshot['consistencygroup_id']:
            client.create_cgsnapshot(snapshot)
        else:
            snapshot_name = snapshot['name']
            volume_name = snapshot['volume_name']
            LOG.info(_LI('Create snapshot: %(snapshot)s: volume: %(volume)s'),
                     {'snapshot': snapshot_name,
                      'volume': volume_name})
            client.create_snapshot(source_lun_id, snapshot_name)

    def revert(self, result, client, snapshot, *args, **kwargs):
        LOG.debug('CreateSnapshotTask.revert')
        if isinstance(result, failure.Failure):
            return
        else:
            if snapshot['consistencygroup_id']:
                LOG.warning(_LW('CreateSnapshotTask.revert: '
                                'delete temp cgsnapshot %s'),
                            snapshot['consistencygroup_id'])
                client.delete_cgsnapshot(snapshot)
            else:
                LOG.warning(_LW('CreateSnapshotTask.revert: '
                                'delete temp snapshot %s'),
                            snapshot['name'])
                client.delete_snapshot(snapshot['name'])
