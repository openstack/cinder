# Copyright (c) 2012 - 2014 EMC Corporation, Inc.
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

import os
import random
import re
import time

from oslo.config import cfg
import six

from cinder import exception
from cinder.exception import EMCVnxCLICmdError
from cinder.i18n import _
from cinder.openstack.common import excutils
from cinder.openstack.common import jsonutils as json
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder.openstack.common import processutils
from cinder.openstack.common import timeutils
from cinder import utils
from cinder.volume.configuration import Configuration
from cinder.volume.drivers.san import san
from cinder.volume import manager
from cinder.volume import volume_types

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

INTERVAL_5_SEC = 5
INTERVAL_30_SEC = 30
INTERVAL_60_SEC = 60

NO_POLL = True

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
]

CONF.register_opts(loc_opts)


def log_enter_exit(func):
    def inner(self, *args, **kwargs):
        LOG.debug("Entering %(cls)s.%(method)s" %
                  {'cls': self.__class__.__name__,
                   'method': func.__name__})
        start = timeutils.utcnow()
        ret = func(self, *args, **kwargs)
        end = timeutils.utcnow()
        LOG.debug("Exiting %(cls)s.%(method)s. "
                  "Spent %(duration)s sec. "
                  "Return %(return)s" %
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
    POOL_NAME = PropertyDescriptor(
        '-name',
        'Pool Name:\s*(.*)\s*',
        'pool_name')

    POOL_ALL = [POOL_TOTAL_CAPACITY, POOL_FREE_CAPACITY]

    CLI_RESP_PATTERN_CG_NOT_FOUND = 'Cannot find'
    CLI_RESP_PATTERN_SNAP_NOT_FOUND = 'The specified snapshot does not exist'

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
            LOG.warn(_("san_secondary_ip is configured as "
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
            LOG.info(_("Using security file in %s for authentication") %
                     storage_vnx_security_file)
        # if there is a username/password provided, use those in the cmd line
        elif storage_username is not None and len(storage_username) > 0 and\
                storage_password is not None and len(storage_password) > 0:
            self.credentials = ('-user', storage_username,
                                '-password', storage_password,
                                '-scope', storage_auth_type)
            LOG.info(_("Plain text credentials are being used for "
                       "authentication"))
        else:
            LOG.info(_("Neither security file nor plain "
                       "text credentials are specified. Security file under "
                       "home directory will be used for authentication "
                       "if present."))

        self.iscsi_initiator_map = None
        if configuration.iscsi_initiators:
            self.iscsi_initiator_map = \
                json.loads(configuration.iscsi_initiators)
            LOG.info(_("iscsi_initiators: %s"), self.iscsi_initiator_map)

        # extra spec constants
        self.pool_spec = 'storagetype:pool'
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

    @log_enter_exit
    def create_lun_with_advance_feature(self, pool, name, size,
                                        provisioning, tiering,
                                        consistencygroup_id=None):
        command_create_lun = ['lun', '-create',
                              '-capacity', size,
                              '-sq', 'gb',
                              '-poolName', pool,
                              '-name', name]
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
        except EMCVnxCLICmdError as ex:
            with excutils.save_and_reraise_exception():
                self.delete_lun(name)
                LOG.error(_("Error on enable compression on lun %s.")
                          % six.text_type(ex))

        # handle consistency group
        try:
            if consistencygroup_id:
                self.add_lun_to_consistency_group(
                    consistencygroup_id, data['lun_id'])
        except EMCVnxCLICmdError as ex:
            with excutils.save_and_reraise_exception():
                self.delete_lun(name)
                LOG.error(_("Error on adding lun to consistency"
                            " group. %s") % six.text_type(ex))
        return data

    @log_enter_exit
    def create_lun_by_cmd(self, cmd, name):
        out, rc = self.command_execute(*cmd)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 4 and out.find('(0x712d8d04)') >= 0:
                LOG.warn(_('LUN already exists, LUN name %(name)s. '
                           'Message: %(msg)s') %
                         {'name': name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(cmd, rc, out)

        def lun_is_ready():
            data = self.get_lun_by_name(name)
            return data[self.LUN_STATE.key] == 'Ready' and \
                data[self.LUN_STATUS.key] == 'OK(0x0)' and \
                data[self.LUN_OPERATION.key] == 'None'

        self._wait_for_a_condition(lun_is_ready)
        lun = self.get_lun_by_name(name)
        return lun

    @log_enter_exit
    def delete_lun(self, name):

        command_delete_lun = ['lun', '-destroy',
                              '-name', name,
                              '-forceDetach',
                              '-o']
        # executing cli command to delete volume
        out, rc = self.command_execute(*command_delete_lun)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 9 and out.find("not exist") >= 0:
                LOG.warn(_("LUN is already deleted, LUN name %(name)s. "
                           "Message: %(msg)s") %
                         {'name': name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(command_delete_lun, rc, out)

    def _wait_for_a_condition(self, testmethod, timeout=None,
                              interval=INTERVAL_5_SEC):
        start_time = time.time()
        if timeout is None:
            timeout = self.timeout

        def _inner():
            try:
                testValue = testmethod()
            except Exception as ex:
                testValue = False
                LOG.debug('CommandLineHelper.'
                          '_wait_for_condition: %(method_name)s '
                          'execution failed for %(exception)s'
                          % {'method_name': testmethod.__name__,
                             'exception': ex.message})
            if testValue:
                raise loopingcall.LoopingCallDone()

            if int(time.time()) - start_time > timeout:
                msg = (_('CommandLineHelper._wait_for_condition: %s timeout')
                       % testmethod.__name__)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        timer = loopingcall.FixedIntervalLoopingCall(_inner)
        timer.start(interval=interval).wait()

    @log_enter_exit
    def expand_lun(self, name, new_size):

        command_expand_lun = ('lun', '-expand',
                              '-name', name,
                              '-capacity', new_size,
                              '-sq', 'gb',
                              '-o',
                              '-ignoreThresholds')
        out, rc = self.command_execute(*command_expand_lun)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 4 and out.find("(0x712d8e04)") >= 0:
                LOG.warn(_("LUN %(name)s is already expanded. "
                           "Message: %(msg)s") %
                         {'name': name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(command_expand_lun, rc, out)

    @log_enter_exit
    def expand_lun_and_wait(self, name, new_size):
        self.expand_lun(name, new_size)

        def lun_is_extented():
            data = self.get_lun_by_name(name)
            return new_size == data[self.LUN_CAPACITY.key]

        self._wait_for_a_condition(lun_is_extented)

    @log_enter_exit
    def lun_rename(self, lun_id, new_name):
        """This function used to rename a lun to match
        the expected name for the volume.
        """
        command_lun_rename = ('lun', '-modify',
                              '-l', lun_id,
                              '-newName', new_name,
                              '-o')

        out, rc = self.command_execute(*command_lun_rename)
        if rc != 0:
            raise EMCVnxCLICmdError(command_lun_rename, rc, out)

    @log_enter_exit
    def modify_lun_tiering(self, name, tiering):
        """This function used to modify a lun's tiering policy."""
        command_modify_lun = ['lun', '-modify',
                              '-name', name,
                              '-o']
        if tiering:
            command_modify_lun.extend(self.tiering_values[tiering])

            out, rc = self.command_execute(*command_modify_lun)
            if rc != 0:
                raise EMCVnxCLICmdError(command_modify_lun, rc, out)

    @log_enter_exit
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
                LOG.warn(_('Consistency group %(name)s already '
                           'exists. Message: %(msg)s') %
                         {'name': cg_name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(command_create_cg, rc, out)

    @log_enter_exit
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
                luns_of_cg = m.groups()[3].split(',')
                if luns_of_cg:
                    data['Luns'] = [lun.strip() for lun in luns_of_cg]
                LOG.debug("Found consistent group %s." % data['Name'])

        return data

    @log_enter_exit
    def add_lun_to_consistency_group(self, cg_name, lun_id):
        add_lun_to_cg_cmd = ('-np', 'snap', '-group',
                             '-addmember', '-id',
                             cg_name, '-res', lun_id)

        out, rc = self.command_execute(*add_lun_to_cg_cmd)
        if rc != 0:
            msg = (_("Can not add the lun %(lun)s to consistency "
                   "group %(cg_name)s.") % {'lun': lun_id,
                                            'cg_name': cg_name})
            LOG.error(msg)
            raise EMCVnxCLICmdError(add_lun_to_cg_cmd, rc, out)

        def add_lun_to_consistency_success():
            data = self.get_consistency_group_by_name(cg_name)
            if str(lun_id) in data['Luns']:
                LOG.debug(("Add lun %(lun)s to consistency "
                           "group %(cg_name)s successfully.") %
                          {'lun': lun_id, 'cg_name': cg_name})
                return True
            else:
                LOG.debug(("Adding lun %(lun)s to consistency "
                           "group %(cg_name)s.") %
                          {'lun': lun_id, 'cg_name': cg_name})
                return False

        self._wait_for_a_condition(add_lun_to_consistency_success,
                                   interval=INTERVAL_30_SEC)

    @log_enter_exit
    def delete_consistencygroup(self, cg_name):
        delete_cg_cmd = ('-np', 'snap', '-group',
                         '-destroy', '-id', cg_name)
        out, rc = self.command_execute(*delete_cg_cmd)
        if rc != 0:
            # Ignore the error if CG doesn't exist
            if rc == 13 and out.find(self.CLI_RESP_PATTERN_CG_NOT_FOUND) >= 0:
                LOG.warn(_("CG %(cg_name)s does not exist. "
                           "Message: %(msg)s") %
                         {'cg_name': cg_name, 'msg': out})
            elif rc == 1 and out.find("0x712d8801") >= 0:
                LOG.warn(_("CG %(cg_name)s is deleting. "
                           "Message: %(msg)s") %
                         {'cg_name': cg_name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(delete_cg_cmd, rc, out)
        else:
            LOG.info(_('Consistency group %s was deleted '
                       'successfully.') % cg_name)

    @log_enter_exit
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
                LOG.warn(_('Cgsnapshot name %(name)s already '
                           'exists. Message: %(msg)s') %
                         {'name': snap_name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(create_cg_snap_cmd, rc, out)

    @log_enter_exit
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
                LOG.warn(_('Snapshot %(name)s for consistency group '
                           'does not exist. Message: %(msg)s') %
                         {'name': snap_name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(delete_cg_snap_cmd, rc, out)

    @log_enter_exit
    def create_snapshot(self, volume_name, name):
        data = self.get_lun_by_name(volume_name)
        if data[self.LUN_ID.key] is not None:
            command_create_snapshot = ('snap', '-create',
                                       '-res', data[self.LUN_ID.key],
                                       '-name', name,
                                       '-allowReadWrite', 'yes',
                                       '-allowAutoDelete', 'no')

            out, rc = self.command_execute(*command_create_snapshot)
            if rc != 0:
                # Ignore the error that due to retry
                if (rc == 5 and
                        out.find("(0x716d8005)") >= 0):
                    LOG.warn(_('Snapshot %(name)s already exists. '
                               'Message: %(msg)s') %
                             {'name': name, 'msg': out})
                else:
                    raise EMCVnxCLICmdError(command_create_snapshot, rc, out)
        else:
            msg = _('Failed to get LUN ID for volume %s.') % volume_name
            raise exception.VolumeBackendAPIException(data=msg)

    @log_enter_exit
    def delete_snapshot(self, name):

        def delete_snapshot_success():
            command_delete_snapshot = ('snap', '-destroy',
                                       '-id', name,
                                       '-o')
            out, rc = self.command_execute(*command_delete_snapshot)
            if rc != 0:
                # Ignore the error that due to retry
                if rc == 5 and out.find("not exist") >= 0:
                    LOG.warn(_("Snapshot %(name)s may deleted already. "
                               "Message: %(msg)s") %
                             {'name': name, 'msg': out})
                    return True
                # The snapshot cannot be destroyed because it is
                # attached to a snapshot mount point. Wait
                elif rc == 3 and out.find("(0x716d8003)") >= 0:
                    LOG.warn(_("Snapshot %(name)s is in use, retry. "
                               "Message: %(msg)s") %
                             {'name': name, 'msg': out})
                    return False
                else:
                    raise EMCVnxCLICmdError(command_delete_snapshot, rc, out)
            else:
                LOG.info(_('Snapshot %s was deleted successfully.') %
                         name)
                return True

        self._wait_for_a_condition(delete_snapshot_success,
                                   interval=INTERVAL_30_SEC,
                                   timeout=INTERVAL_30_SEC * 3)

    @log_enter_exit
    def create_mount_point(self, primary_lun_name, name):

        command_create_mount_point = ('lun', '-create',
                                      '-type', 'snap',
                                      '-primaryLunName', primary_lun_name,
                                      '-name', name)

        out, rc = self.command_execute(*command_create_mount_point)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 4 and out.find("(0x712d8d04)") >= 0:
                LOG.warn(_("Mount point %(name)s already exists. "
                           "Message: %(msg)s") %
                         {'name': name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(command_create_mount_point, rc, out)

        return rc

    @log_enter_exit
    def attach_mount_point(self, name, snapshot_name):

        command_attach_mount_point = ('lun', '-attach',
                                      '-name', name,
                                      '-snapName', snapshot_name)

        out, rc = self.command_execute(*command_attach_mount_point)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 85 and out.find('(0x716d8055)') >= 0:
                LOG.warn(_("Snapshot %(snapname)s is attached to snapshot "
                           "mount point %(mpname)s already. "
                           "Message: %(msg)s") %
                         {'snapname': snapshot_name,
                          'mpname': name,
                          'msg': out})
            else:
                raise EMCVnxCLICmdError(command_attach_mount_point, rc, out)

        return rc

    @log_enter_exit
    def check_smp_not_attached(self, smp_name):
        """Ensure a snap mount point with snap become a LUN."""

        def _wait_for_sync_status():
            lun_list = ('lun', '-list', '-name', smp_name,
                        '-attachedSnapshot')
            out, rc = self.command_execute(*lun_list)
            if rc == 0:
                vol_details = out.split('\n')
                snap_name = vol_details[2].split(':')[1].strip()
            if (snap_name == 'N/A'):
                return True
            return False

        self._wait_for_a_condition(_wait_for_sync_status)

    @log_enter_exit
    def migrate_lun(self, src_id, dst_id, log_failure_as_error=True):
        command_migrate_lun = ('migrate', '-start',
                               '-source', src_id,
                               '-dest', dst_id,
                               '-rate', 'high',
                               '-o')
        # SP HA is not supported by LUN migration
        out, rc = self.command_execute(*command_migrate_lun,
                                       retry_disable=True)

        if 0 != rc:
            raise EMCVnxCLICmdError(command_migrate_lun, rc, out,
                                    log_failure_as_error)

        return rc

    @log_enter_exit
    def migrate_lun_with_verification(self, src_id,
                                      dst_id=None,
                                      dst_name=None):
        try:
            self.migrate_lun(src_id, dst_id, log_failure_as_error=False)
        except EMCVnxCLICmdError as ex:
            migration_succeed = False
            if self._is_sp_unavailable_error(ex.out):
                LOG.warn(_("Migration command may get network timeout. "
                           "Double check whether migration in fact "
                           "started successfully. Message: %(msg)s") %
                         {'msg': ex.out})
                command_migrate_list = ('migrate', '-list',
                                        '-source', src_id)
                rc = self.command_execute(*command_migrate_list)[1]
                if rc == 0:
                    migration_succeed = True

            if not migration_succeed:
                LOG.warn(_("Start migration failed. Message: %s") %
                         ex.out)
                LOG.debug("Delete temp LUN after migration "
                          "start failed. LUN: %s" % dst_name)
                if(dst_name is not None):
                    self.delete_lun(dst_name)
                return False

        # Set the proper interval to verify the migration status
        def migration_is_ready():
            mig_ready = False
            command_migrate_list = ('migrate', '-list',
                                    '-source', src_id)
            out, rc = self.command_execute(*command_migrate_list)
            LOG.debug("Migration output: %s" % out)
            if rc == 0:
                # parse the percentage
                out = re.split(r'\n', out)
                log = "Migration in process %s %%." % out[7].split(":  ")[1]
                LOG.debug(log)
            else:
                if re.search(r'The specified source LUN '
                             'is not currently migrating', out):
                    LOG.debug("Migration of LUN %s is finished." % src_id)
                    mig_ready = True
                else:
                    reason = _("Querying migrating status error.")
                    LOG.error(reason)
                    raise exception.VolumeBackendAPIException(
                        data="%(reason)s : %(output)s" %
                        {'reason': reason, 'output': out})
            return mig_ready

        self._wait_for_a_condition(migration_is_ready,
                                   interval=INTERVAL_30_SEC)

        return True

    @log_enter_exit
    def get_storage_group(self, name):

        # ALU/HLU as key/value map
        lun_map = {}

        data = {'storage_group_name': name,
                'storage_group_uid': None,
                'lunmap': lun_map}

        command_get_storage_group = ('storagegroup', '-list',
                                     '-gname', name)

        out, rc = self.command_execute(*command_get_storage_group)
        if rc != 0:
            raise EMCVnxCLICmdError(command_get_storage_group, rc, out)

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

    @log_enter_exit
    def create_storage_group(self, name):

        command_create_storage_group = ('storagegroup', '-create',
                                        '-gname', name)

        out, rc = self.command_execute(*command_create_storage_group)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 66 and out.find("name already in use") >= 0:
                LOG.warn(_('Storage group %(name)s already exists. '
                           'Message: %(msg)s') %
                         {'name': name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(command_create_storage_group, rc, out)

    @log_enter_exit
    def delete_storage_group(self, name):

        command_delete_storage_group = ('storagegroup', '-destroy',
                                        '-gname', name, '-o')

        out, rc = self.command_execute(*command_delete_storage_group)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 83 and out.find("group name or UID does not "
                                     "match any storage groups") >= 0:
                LOG.warn(_("Storage group %(name)s doesn't exist, "
                           "may have already been deleted. "
                           "Message: %(msg)s") %
                         {'name': name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(command_delete_storage_group, rc, out)

    @log_enter_exit
    def connect_host_to_storage_group(self, hostname, sg_name):

        command_host_connect = ('storagegroup', '-connecthost',
                                '-host', hostname,
                                '-gname', sg_name,
                                '-o')

        out, rc = self.command_execute(*command_host_connect)
        if rc != 0:
            raise EMCVnxCLICmdError(command_host_connect, rc, out)

    @log_enter_exit
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
                LOG.warn(_("Host %(host)s has already disconnected from "
                           "storage group %(sgname)s. Message: %(msg)s") %
                         {'host': hostname, 'sgname': sg_name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(command_host_disconnect, rc, out)

    @log_enter_exit
    def add_hlu_to_storage_group(self, hlu, alu, sg_name):

        command_add_hlu = ('storagegroup', '-addhlu',
                           '-hlu', hlu,
                           '-alu', alu,
                           '-gname', sg_name)

        out, rc = self.command_execute(*command_add_hlu)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 66 and \
                    re.search("LUN.*already.*added to.*Storage Group",
                              out) is not None:
                LOG.warn(_("LUN %(lun)s has already added to "
                           "Storage Group %(sgname)s. "
                           "Message: %(msg)s") %
                         {'lun': alu, 'sgname': sg_name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(command_add_hlu, rc, out)

    @log_enter_exit
    def remove_hlu_from_storagegroup(self, hlu, sg_name):

        command_remove_hlu = ('storagegroup', '-removehlu',
                              '-hlu', hlu,
                              '-gname', sg_name,
                              '-o')

        out, rc = self.command_execute(*command_remove_hlu)
        if rc != 0:
            # Ignore the error that due to retry
            if rc == 66 and\
                    out.find("No such Host LUN in this Storage Group") >= 0:
                LOG.warn(_("HLU %(hlu)s has already been removed from "
                           "%(sgname)s. Message: %(msg)s") %
                         {'hlu': hlu, 'sgname': sg_name, 'msg': out})
            else:
                raise EMCVnxCLICmdError(command_remove_hlu, rc, out)

    @log_enter_exit
    def get_iscsi_protocol_endpoints(self, device_sp):

        command_get_port = ('connection', '-getport',
                            '-sp', device_sp)

        out, rc = self.command_execute(*command_get_port)
        if rc != 0:
            raise EMCVnxCLICmdError(command_get_port, rc, out)

        re_port_wwn = 'Port WWN:\s*(.*)\s*'
        initiator_address = re.findall(re_port_wwn, out)

        return initiator_address

    @log_enter_exit
    def get_pool_name_of_lun(self, lun_name):
        data = self.get_lun_properties(
            ('-name', lun_name), self.LUN_WITH_POOL)
        return data.get('pool', '')

    @log_enter_exit
    def get_lun_by_name(self, name, properties=LUN_ALL):
        data = self.get_lun_properties(('-name', name), properties)
        return data

    @log_enter_exit
    def get_lun_by_id(self, lunid, properties=LUN_ALL):
        data = self.get_lun_properties(('-l', lunid), properties)
        return data

    @log_enter_exit
    def get_pool(self, name):
        data = self.get_pool_properties(('-name', name))
        return data

    @log_enter_exit
    def get_pool_properties(self, filter_option, properties=POOL_ALL):
        module_list = ('storagepool', '-list')
        data = self._get_lun_or_pool_properties(
            module_list, filter_option,
            base_properties=[self.POOL_NAME],
            adv_properties=properties)
        return data

    @log_enter_exit
    def get_lun_properties(self, filter_option, properties=LUN_ALL):
        module_list = ('lun', '-list')
        data = self._get_lun_or_pool_properties(
            module_list, filter_option,
            base_properties=[self.LUN_NAME, self.LUN_ID],
            adv_properties=properties)
        return data

    def _get_lun_or_pool_properties(self, module_list,
                                    filter_option,
                                    base_properties=tuple(),
                                    adv_properties=tuple()):
        # to do instance check
        command_get_lun = module_list + filter_option
        for prop in adv_properties:
            command_get_lun += (prop.option, )
        out, rc = self.command_execute(*command_get_lun)

        if rc != 0:
            raise EMCVnxCLICmdError(command_get_lun, rc, out)

        data = {}
        for baseprop in base_properties:
            data[baseprop.key] = self._get_property_value(out, baseprop)

        for prop in adv_properties:
            data[prop.key] = self._get_property_value(out, prop)

        LOG.debug('Return LUN or Pool properties. Data: %s' % data)
        return data

    def _get_property_value(self, out, propertyDescriptor):
        label = propertyDescriptor.label
        m = re.search(label, out)
        if m:
            if (propertyDescriptor.converter is not None):
                try:
                    return propertyDescriptor.converter(m.group(1))
                except ValueError:
                    LOG.error(_("Invalid value for %(key)s, "
                                "value is %(value)s.") %
                              {'key': propertyDescriptor.key,
                               'value': m.group(1)})
                    return None
            else:
                return m.group(1)
        else:
            LOG.debug('%s value is not found in the output.'
                      % propertyDescriptor.label)
            return None

    @log_enter_exit
    def check_lun_has_snap(self, lun_id):
        cmd = ('snap', '-list', '-res', lun_id)
        rc = self.command_execute(*cmd)[1]
        if rc == 0:
            LOG.debug("Find snapshots for %s." % lun_id)
            return True
        else:
            return False

    # Return a pool list
    @log_enter_exit
    def get_pool_list(self, no_poll=False):
        temp_cache = []
        cmd = ('-np', 'storagepool', '-list', '-availableCap', '-state') \
            if no_poll \
            else ('storagepool', '-list', '-availableCap', '-state')
        out, rc = self.command_execute(*cmd)
        if rc != 0:
            raise EMCVnxCLICmdError(cmd, rc, out)

        try:
            for pool in out.split('\n\n'):
                if len(pool.strip()) == 0:
                    continue
                obj = {}
                obj['name'] = self._get_property_value(pool, self.POOL_NAME)
                obj['free_space'] = self._get_property_value(
                    pool, self.POOL_FREE_CAPACITY)
                temp_cache.append(obj)
        except Exception as ex:
            LOG.error(_("Error happened during storage pool querying, %s.")
                      % ex)
            # NOTE: Do not want to continue raise the exception
            # as the pools may temporarly unavailable
            pass
        return temp_cache

    @log_enter_exit
    def get_array_serial(self, no_poll=False):
        """return array Serial No for pool backend."""
        data = {'array_serial': 'unknown'}

        command_get_array_serial = ('-np', 'getagent', '-serial') \
            if no_poll else ('getagent', '-serial')
        # Set the property timeout to get array serial
        out, rc = self.command_execute(*command_get_array_serial)
        if 0 == rc:
            m = re.search(r'Serial No:\s+(\w+)', out)
            if m:
                data['array_serial'] = m.group(1)
            else:
                LOG.warn(_("No array serial number returned, "
                           "set as unknown."))
        else:
            raise EMCVnxCLICmdError(command_get_array_serial, rc, out)

        return data

    @log_enter_exit
    def get_status_up_ports(self, storage_group_name):
        """Function to get ports whose status are up."""
        cmd_get_hba = ('storagegroup', '-list', '-gname', storage_group_name)
        out, rc = self.command_execute(*cmd_get_hba)
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
                raise EMCVnxCLICmdError(cmd_get_port, rc, out)
            for i, sp in enumerate(sps):
                wwn = self.get_port_wwn(sp, portid[i], out)
                if (wwn is not None) and (wwn not in wwns):
                    LOG.debug('Add wwn:%(wwn)s for sg:%(sg)s.'
                              % {'wwn': wwn,
                                 'sg': storage_group_name})
                    wwns.append(wwn)
        else:
            raise EMCVnxCLICmdError(cmd_get_hba, rc, out)
        return wwns

    @log_enter_exit
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
            raise EMCVnxCLICmdError(cmd_list_hba, rc, out)
        return wwns

    @log_enter_exit
    def get_port_wwn(self, sp, port_id, allports=None):
        wwn = None
        if allports is None:
            cmd_get_port = ('port', '-list', '-sp')
            out, rc = self.command_execute(*cmd_get_port)
            if 0 != rc:
                raise EMCVnxCLICmdError(cmd_get_port, rc, out)
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

    @log_enter_exit
    def get_fc_targets(self):
        fc_getport = ('port', '-list', '-sp')
        out, rc = self.command_execute(*fc_getport)
        if rc != 0:
            raise EMCVnxCLICmdError(fc_getport, rc, out)

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

    @log_enter_exit
    def get_iscsi_targets(self):
        cmd_getport = ('connection', '-getport', '-address', '-vlanid')
        out, rc = self.command_execute(*cmd_getport)
        if rc != 0:
            raise EMCVnxCLICmdError(cmd_getport, rc, out)

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

    @log_enter_exit
    def get_registered_spport_set(self, initiator_iqn, sgname):
        sg_list = ('storagegroup', '-list', '-gname', sgname)
        out, rc = self.command_execute(*sg_list)
        spport_set = set()
        if rc == 0:
            for m_spport in re.finditer(r'\n\s+%s\s+SP\s(A|B)\s+(\d+)' %
                                        initiator_iqn,
                                        out,
                                        flags=re.IGNORECASE):
                spport_set.add((m_spport.group(1), int(m_spport.group(2))))
                LOG.debug('See path %(path)s in %(sg)s'
                          % ({'path': m_spport.group(0),
                              'sg': sgname}))
        else:
            raise EMCVnxCLICmdError(sg_list, rc, out)
        return spport_set

    @log_enter_exit
    def ping_node(self, target_portal, initiator_ip):
        connection_pingnode = ('connection', '-pingnode', '-sp',
                               target_portal['SP'], '-portid',
                               target_portal['Port ID'], '-vportid',
                               target_portal['Virtual Port ID'],
                               '-address', initiator_ip)
        out, rc = self.command_execute(*connection_pingnode)
        if rc == 0:
            ping_ok = re.compile(r'Reply from %s' % initiator_ip)
            if re.match(ping_ok, out) is not None:
                LOG.debug("See available iSCSI target: %s",
                          connection_pingnode)
                return True
        LOG.warn(_("See unavailable iSCSI target: %s"), connection_pingnode)
        return False

    @log_enter_exit
    def find_avaialable_iscsi_target_one(self, hostname,
                                         preferred_sp,
                                         registered_spport_set):
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

        iscsi_targets = self.get_iscsi_targets()
        for target_sp in target_sps:
            target_portals = list(iscsi_targets[target_sp])
            random.shuffle(target_portals)
            for target_portal in target_portals:
                spport = (target_portal['SP'], target_portal['Port ID'])
                if spport not in registered_spport_set:
                    LOG.debug("Skip SP Port %(port)s since "
                              "no path from %(host)s is through it"
                              % {'port': spport,
                                 'host': hostname})
                    continue
                if iscsi_initiator_ips is not None:
                    for initiator_ip in iscsi_initiator_ips:
                        if self.ping_node(target_portal, initiator_ip):
                            return target_portal
                else:
                    LOG.debug("No iSCSI IP address of %(hostname)s is known. "
                              "Return a random iSCSI target portal %(portal)s."
                              %
                              {'hostname': hostname, 'portal': target_portal})
                    return target_portal

        return None

    def _is_sp_unavailable_error(self, out):
        error_pattern = '(^Error.*Message.*End of data stream.*)|'\
                        '(.*Message.*connection refused.*)|'\
                        '(^Error.*Message.*Service Unavailable.*)'
        pattern = re.compile(error_pattern)
        return pattern.match(out)

    @log_enter_exit
    def command_execute(self, *command, **kwargv):
        # NOTE: retry_disable need to be removed from kwargv
        # before it pass to utils.execute, otherwise exception will thrown
        retry_disable = kwargv.pop('retry_disable', False)
        if self._is_sp_alive(self.active_storage_ip):
            out, rc = self._command_execute_on_active_ip(*command, **kwargv)
            if not retry_disable and self._is_sp_unavailable_error(out):
                # When active sp is unavailble, swith to another sp
                # and set it to active
                if self._toggle_sp():
                    LOG.debug('EMC: Command Exception: %(rc) %(result)s. '
                              'Retry on another SP.' % {'rc': rc,
                                                        'result': out})
                    out, rc = self._command_execute_on_active_ip(*command,
                                                                 **kwargv)
        elif self._toggle_sp() and not retry_disable:
            # If active ip is not accessible, toggled to another sp
            out, rc = self._command_execute_on_active_ip(*command, **kwargv)
        else:
            # Active IP is inaccessible, and cannot toggle to another SP,
            # return Error
            out, rc = "Server Unavailable", 255

        LOG.debug('EMC: Command: %(command)s.'
                  % {'command': self.command + command})
        LOG.debug('EMC: Command Result: %(result)s.' %
                  {'result': out.replace('\n', '\\n')})

        return out, rc

    def _command_execute_on_active_ip(self, *command, **kwargv):
        if "check_exit_code" not in kwargv:
            kwargv["check_exit_code"] = True
        rc = 0
        out = ""
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
                LOG.debug('%s is unavaialbe' % ipaddr)
                return False
        LOG.debug('Ping SP %(spip)s Command Result: %(result)s.' %
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

        LOG.info(_('Toggle storage_vnx_ip_address from %(old)s to '
                   '%(new)s.') %
                 {'old': old_ip,
                  'new': self.primary_storage_ip})
        return True

    @log_enter_exit
    def get_enablers_on_array(self, no_poll=False):
        """The function would get all the enabler installed
        on array.
        """
        enablers = []
        cmd_list = ('-np', 'ndu', '-list') \
            if no_poll else ('ndu', '-list')
        out, rc = self.command_execute(*cmd_list)

        if rc != 0:
            raise EMCVnxCLICmdError(cmd_list, rc, out)
        else:
            enabler_pat = r'Name of the software package:\s*(\S+)\s*'
            for m in re.finditer(enabler_pat, out):
                enablers.append(m.groups()[0])

        LOG.debug('Enablers on array %s.' % enablers)
        return enablers

    @log_enter_exit
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
            raise EMCVnxCLICmdError(command_compression_cmd, rc, out)
        return rc, out


class EMCVnxCliBase(object):
    """This class defines the functions to use the native CLI functionality."""

    VERSION = '04.01.00'
    stats = {'driver_version': VERSION,
             'free_capacity_gb': 'unknown',
             'reserved_percentage': 0,
             'storage_protocol': None,
             'total_capacity_gb': 'unknown',
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
        self.timeout = self.configuration.default_timeout * 60
        self.max_luns_per_sg = self.configuration.max_luns_per_storage_group
        self.destroy_empty_sg = self.configuration.destroy_empty_storage_group
        self.itor_auto_reg = self.configuration.initiator_auto_registration
        # if zoning_mode is fabric, use lookup service to build itor_tgt_map
        self.zonemanager_lookup_service = None
        zm_conf = Configuration(manager.volume_manager_opts)
        if (zm_conf.safe_get('zoning_mode') == 'fabric' or
                self.configuration.safe_get('zoning_mode') == 'fabric'):
            from cinder.zonemanager.fc_san_lookup_service \
                import FCSanLookupService
            self.zonemanager_lookup_service = \
                FCSanLookupService(configuration=configuration)
        self.max_retries = 5
        if self.destroy_empty_sg:
            LOG.warn(_("destroy_empty_storage_group: True. "
                       "Empty storage group will be deleted "
                       "after volume is detached."))
        if not self.itor_auto_reg:
            LOG.info(_("initiator_auto_registration: False. "
                       "Initiator auto registration is not enabled. "
                       "Please register initiator manually."))
        self.hlu_set = set(xrange(1, self.max_luns_per_sg + 1))
        self._client = CommandLineHelper(self.configuration)
        self.array_serial = None

    def get_target_storagepool(self, volume, source_volume_name=None):
        raise NotImplementedError

    def dumps_provider_location(self, pl_dict):
        return '|'.join([k + '^' + pl_dict[k] for k in pl_dict])

    def get_array_serial(self):
        if not self.array_serial:
            self.array_serial = self._client.get_array_serial()
        return self.array_serial['array_serial']

    @log_enter_exit
    def create_volume(self, volume):
        """Creates a EMC volume."""
        volumesize = volume['size']
        volumename = volume['name']

        self._volume_creation_check(volume)
        # defining CLI command
        specs = self.get_volumetype_extraspecs(volume)
        pool = self.get_target_storagepool(volume)
        provisioning, tiering = self.get_extra_spec_value(specs)

        if not provisioning:
            provisioning = 'thick'

        LOG.info(_('Create Volume: %(volume)s  Size: %(size)s '
                   'pool: %(pool)s '
                   'provisioning: %(provisioning)s '
                   'tiering: %(tiering)s.')
                 % {'volume': volumename,
                    'size': volumesize,
                    'pool': pool,
                    'provisioning': provisioning,
                    'tiering': tiering})

        data = self._client.create_lun_with_advance_feature(
            pool, volumename, volumesize,
            provisioning, tiering, volume['consistencygroup_id'])
        pl_dict = {'system': self.get_array_serial(),
                   'type': 'lun',
                   'id': str(data['lun_id'])}
        model_update = {'provider_location':
                        self.dumps_provider_location(pl_dict)}
        volume['provider_location'] = model_update['provider_location']
        return model_update

    def _volume_creation_check(self, volume):
        """This function will perform the check on the
        extra spec before the volume can be created. The
        check is a common check between the array based
        and pool based backend.
        """

        specs = self.get_volumetype_extraspecs(volume)
        provisioning, tiering = self.get_extra_spec_value(specs)

        # step 1: check extra spec value
        if provisioning:
            self.check_extra_spec_value(
                provisioning,
                self._client.provisioning_values.keys())
        if tiering:
            self.check_extra_spec_value(
                tiering,
                self._client.tiering_values.keys())

        # step 2: check extra spec combination
        self.check_extra_spec_combination(specs)

    def check_extra_spec_value(self, extra_spec, valid_values):
        """check whether an extra spec's value is valid."""

        if not extra_spec or not valid_values:
            LOG.error(_('The given extra_spec or valid_values is None.'))
        elif extra_spec not in valid_values:
            msg = _("The extra_spec: %s is invalid.") % extra_spec
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return

    def get_extra_spec_value(self, extra_specs):
        """get EMC extra spec values."""
        provisioning = 'thick'
        tiering = None

        if self._client.provisioning_spec in extra_specs:
            provisioning = extra_specs[self._client.provisioning_spec].lower()
        if self._client.tiering_spec in extra_specs:
            tiering = extra_specs[self._client.tiering_spec].lower()

        return provisioning, tiering

    def check_extra_spec_combination(self, extra_specs):
        """check whether extra spec combination is valid."""

        provisioning, tiering = self.get_extra_spec_value(extra_specs)
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

    @log_enter_exit
    def delete_volume(self, volume):
        """Deletes an EMC volume."""
        self._client.delete_lun(volume['name'])

    @log_enter_exit
    def extend_volume(self, volume, new_size):
        """Extends an EMC volume."""
        self._client.expand_lun_and_wait(volume['name'], new_size)

    def _get_original_status(self, volume):
        if (volume['instance_uuid'] is None and
                volume['attached_host'] is None):
            return 'available'
        else:
            return 'in-use'

    def _is_valid_for_storage_assisted_migration(
            self, volume, host, new_type=None):
        """Check the src and dest volume to decide the mogration type."""
        false_ret = (False, None)

        if 'location_info' not in host['capabilities']:
            LOG.warn(_("Failed to get target_pool_name and "
                       "target_array_serial. 'location_info' "
                       "is not in host['capabilities']."))
            return false_ret

        # mandatory info should be ok
        info = host['capabilities']['location_info']
        LOG.debug("Host for migration is %s." % info)
        try:
            info_detail = info.split('|')
            target_pool_name = info_detail[0]
            target_array_serial = info_detail[1]
        except AttributeError:
            LOG.warn(_("Error on parsing target_pool_name/"
                       "target_array_serial."))
            return false_ret

        if len(target_pool_name) == 0:
            # if retype, try to get the pool of the volume
            # when it's array-based
            if new_type:
                if 'storagetype:pool' in new_type['extra_specs']\
                        and new_type['extra_specs']['storagetype:pool']\
                        is not None:
                    target_pool_name = \
                        new_type['extra_specs']['storagetype:pool']
                else:
                    target_pool_name = self._client.get_pool_name_of_lun(
                        volume['name'])

        if len(target_pool_name) == 0:
            LOG.debug("Skip storage-assisted migration because "
                      "it doesn't support array backend .")
            return false_ret
        # source and destination should be on same array
        array_serial = self._client.get_array_serial()
        if target_array_serial != array_serial['array_serial']:
            LOG.debug('Skip storage-assisted migration because '
                      'target and source backend are not managing'
                      'the same array.')
            return false_ret
        # same protocol should be used if volume is in-use
        if host['capabilities']['storage_protocol'] != self.protocol \
                and self._get_original_status(volume) == 'in-use':
            LOG.debug('Skip storage-assisted migration because '
                      'in-use volume can not be '
                      'migrate between diff protocol.')
            return false_ret

        return (True, target_pool_name)

    @log_enter_exit
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
            provisioning, tiering = self.get_extra_spec_value(
                new_type['extra_specs'])
        else:
            provisioning, tiering = self.get_extra_spec_value(
                self.get_volumetype_extraspecs(volume))

        self._client.create_lun_with_advance_feature(
            target_pool_name, new_volume_name, volume['size'],
            provisioning, tiering)

        dst_id = self.get_lun_id_by_name(new_volume_name)
        moved = self._client.migrate_lun_with_verification(
            src_id, dst_id, new_volume_name)

        return moved, {}

    @log_enter_exit
    def retype(self, ctxt, volume, new_type, diff, host):
        new_specs = new_type['extra_specs']
        new_provisioning, new_tiering = self.get_extra_spec_value(
            new_specs)

        # validate new_type
        if new_provisioning:
            self.check_extra_spec_value(
                new_provisioning,
                self._client.provisioning_values.keys())
        if new_tiering:
            self.check_extra_spec_value(
                new_tiering,
                self._client.tiering_values.keys())
        self.check_extra_spec_combination(new_specs)

        # check what changes are needed
        migration, tiering_change = self.determine_changes_when_retype(
            volume, new_type, host)

        # reject if volume has snapshot when migration is needed
        if migration and self._client.check_lun_has_snap(
                self.get_lun_id(volume)):
            LOG.debug('Driver is not able to do retype because the volume '
                      'has snapshot which is forbidden to migrate.')
            return False

        if migration:
            # check whether the migration is valid
            is_valid, target_pool_name = (
                self._is_valid_for_storage_assisted_migration(
                    volume, host, new_type))
            if is_valid:
                if self._migrate_volume(
                        volume, target_pool_name, new_type)[0]:
                    return True
                else:
                    LOG.warn(_('Storage-assisted migration failed during '
                               'retype.'))
                    return False
            else:
                # migration is invalid
                LOG.debug('Driver is not able to do retype due to '
                          'storage-assisted migration is not valid '
                          'in this stuation.')
                return False
        elif not migration and tiering_change:
            # modify lun to change tiering policy
            self._client.modify_lun_tiering(volume['name'], new_tiering)
            return True
        else:
            return True

    def determine_changes_when_retype(self, volume, new_type, host):
        migration = False
        tiering_change = False

        old_specs = self.get_volumetype_extraspecs(volume)
        old_provisioning, old_tiering = self.get_extra_spec_value(
            old_specs)
        old_pool = self.get_specific_extra_spec(
            old_specs,
            self._client.pool_spec)

        new_specs = new_type['extra_specs']
        new_provisioning, new_tiering = self.get_extra_spec_value(
            new_specs)
        new_pool = self.get_specific_extra_spec(
            new_specs,
            self._client.pool_spec)

        if volume['host'] != host['host'] or \
                old_provisioning != new_provisioning:
            migration = True
        elif new_pool and new_pool != old_pool:
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

    @log_enter_exit
    def update_volume_stats(self):
        """Update the common status share with pool and
        array backend.
        """
        if not self.determine_all_enablers_exist(self.enablers):
            self.enablers = self._client.get_enablers_on_array(NO_POLL)
        if '-Compression' in self.enablers:
            self.stats['compression_support'] = 'True'
        else:
            self.stats['compression_support'] = 'False'
        if '-FAST' in self.enablers:
            self.stats['fast_support'] = 'True'
        else:
            self.stats['fast_support'] = 'False'
        if '-Deduplication' in self.enablers:
            self.stats['deduplication_support'] = 'True'
        else:
            self.stats['deduplication_support'] = 'False'
        if '-ThinProvisioning' in self.enablers:
            self.stats['thinprovisioning_support'] = 'True'
        else:
            self.stats['thinprovisioning_support'] = 'False'
        if '-FASTCache' in self.enablers:
            self.stats['fast_cache_enabled'] = 'True'
        else:
            self.stats['fast_cache_enabled'] = 'False'
        if '-VNXSnapshots' in self.enablers:
            self.stats['consistencygroup_support'] = 'True'
        else:
            self.stats['consistencygroup_support'] = 'False'

        return self.stats

    @log_enter_exit
    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        volumename = volume['name']

        data = self._client.get_lun_by_name(volumename)

        device_id = data['lun_id']

        LOG.debug('Exiting EMCVnxCliBase.create_export: Volume: %(volume)s '
                  'Device ID: %(device_id)s'
                  % {'volume': volumename,
                     'device_id': device_id})

        return {'provider_location': device_id}

    @log_enter_exit
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        snapshotname = snapshot['name']
        volumename = snapshot['volume_name']

        LOG.info(_('Create snapshot: %(snapshot)s: volume: %(volume)s')
                 % {'snapshot': snapshotname,
                    'volume': volumename})

        self._client.create_snapshot(volumename, snapshotname)

    @log_enter_exit
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        snapshotname = snapshot['name']

        LOG.info(_('Delete Snapshot: %(snapshot)s')
                 % {'snapshot': snapshotname})

        self._client.delete_snapshot(snapshotname)

    @log_enter_exit
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        if snapshot['cgsnapshot_id']:
            snapshot_name = snapshot['cgsnapshot_id']
        else:
            snapshot_name = snapshot['name']
        source_volume_name = snapshot['volume_name']
        volume_name = volume['name']
        volume_size = snapshot['volume_size']

        # defining CLI command
        self._client.create_mount_point(source_volume_name, volume_name)

        # defining CLI command
        self._client.attach_mount_point(volume_name, snapshot_name)

        dest_volume_name = volume_name + '_dest'

        LOG.debug('Creating Temporary Volume: %s ' % dest_volume_name)
        pool_name = self.get_target_storagepool(volume, source_volume_name)
        try:
            self._volume_creation_check(volume)
            specs = self.get_volumetype_extraspecs(volume)
            provisioning, tiering = self.get_extra_spec_value(specs)
            self._client.create_lun_with_advance_feature(
                pool_name, dest_volume_name, volume_size,
                provisioning, tiering)
        except exception.VolumeBackendAPIException as ex:
            msg = (_('Command to create the temporary Volume %s failed')
                   % dest_volume_name)
            LOG.error(msg)
            raise ex

        source_vol_lun_id = self.get_lun_id(volume)
        temp_vol_lun_id = self.get_lun_id_by_name(dest_volume_name)

        LOG.debug('Migrating Mount Point Volume: %s ' % volume_name)
        self._client.migrate_lun_with_verification(source_vol_lun_id,
                                                   temp_vol_lun_id,
                                                   dest_volume_name)
        self._client.check_smp_not_attached(volume_name)
        data = self._client.get_lun_by_name(volume_name)
        pl_dict = {'system': self.get_array_serial(),
                   'type': 'lun',
                   'id': str(data['lun_id'])}
        model_update = {'provider_location':
                        self.dumps_provider_location(pl_dict)}
        volume['provider_location'] = model_update['provider_location']
        return model_update

    @log_enter_exit
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        source_volume_name = src_vref['name']
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
            'cgsnapshot_id': tmp_cgsnapshot_name,
            'consistencygroup_id': consistencygroup_id,
            'id': tmp_cgsnapshot_name
        }
        # Create temp Snapshot
        if consistencygroup_id:
            self._client.create_cgsnapshot(snapshot)
        else:
            self.create_snapshot(snapshot)

        # Create volume
        model_update = self.create_volume_from_snapshot(volume, snapshot)
        # Delete temp Snapshot
        if consistencygroup_id:
            self._client.delete_cgsnapshot(snapshot)
        else:
            self.delete_snapshot(snapshot)
        return model_update

    @log_enter_exit
    def create_consistencygroup(self, context, group):
        """Create a consistency group."""
        LOG.info(_('Start to create consistency group: %(group_name)s '
                   'id: %(id)s') %
                 {'group_name': group['name'], 'id': group['id']})

        model_update = {'status': 'available'}
        try:
            self._client.create_consistencygroup(context, group)
        except Exception:
            with excutils.save_and_reraise_exception():
                msg = (_('Create consistency group %s failed.')
                       % group['id'])
                LOG.error(msg)

        return model_update

    @log_enter_exit
    def delete_consistencygroup(self, driver, context, group):
        """Delete a consistency group."""
        cg_name = group['id']
        volumes = driver.db.volume_get_all_by_group(context, group['id'])

        model_update = {}
        model_update['status'] = group['status']
        LOG.info(_('Start to delete consistency group: %(cg_name)s')
                 % {'cg_name': cg_name})
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

    @log_enter_exit
    def create_cgsnapshot(self, driver, context, cgsnapshot):
        """Create a cgsnapshot (snap group)."""
        cgsnapshot_id = cgsnapshot['id']
        snapshots = driver.db.snapshot_get_all_for_cgsnapshot(
            context, cgsnapshot_id)

        model_update = {}
        LOG.info(_('Start to create cgsnapshot for consistency group'
                   ': %(group_name)s') %
                 {'group_name': cgsnapshot['consistencygroup_id']})

        try:
            self._client.create_cgsnapshot(cgsnapshot)
            for snapshot in snapshots:
                snapshot['status'] = 'available'
        except Exception:
            with excutils.save_and_reraise_exception():
                msg = (_('Create cg snapshot %s failed.')
                       % cgsnapshot_id)
                LOG.error(msg)

        model_update['status'] = 'available'

        return model_update, snapshots

    @log_enter_exit
    def delete_cgsnapshot(self, driver, context, cgsnapshot):
        """delete a cgsnapshot (snap group)."""
        cgsnapshot_id = cgsnapshot['id']
        snapshots = driver.db.snapshot_get_all_for_cgsnapshot(
            context, cgsnapshot_id)

        model_update = {}
        model_update['status'] = cgsnapshot['status']
        LOG.info(_('Delete cgsnapshot %(snap_name)s for consistency group: '
                   '%(group_name)s') % {'snap_name': cgsnapshot['id'],
                 'group_name': cgsnapshot['consistencygroup_id']})

        try:
            self._client.delete_cgsnapshot(cgsnapshot)
            for snapshot in snapshots:
                snapshot['status'] = 'deleted'
        except Exception:
            with excutils.save_and_reraise_exception():
                msg = (_('Delete cgsnapshot %s failed.')
                       % cgsnapshot_id)
                LOG.error(msg)

        return model_update, snapshots

    def get_lun_id_by_name(self, volume_name):
        data = self._client.get_lun_by_name(volume_name)
        return data['lun_id']

    def get_lun_id(self, volume):
        lun_id = None
        try:
            if volume.get('provider_location') is not None:
                lun_id = int(
                    volume['provider_location'].split('|')[2].split('^')[1])
            if not lun_id:
                LOG.debug('Lun id is not stored in provider location, '
                          'query it.')
                lun_id = self._client.get_lun_by_name(volume['name'])['lun_id']
        except Exception as ex:
            LOG.debug('Exception when getting lun id: %s.' % (ex))
            lun_id = self._client.get_lun_by_name(volume['name'])['lun_id']
        LOG.debug('Get lun_id: %s.' % (lun_id))
        return lun_id

    def get_lun_map(self, storage_group):
        data = self._client.get_storage_group(storage_group)
        return data['lunmap']

    def get_storage_group_uid(self, name):
        data = self._client.get_storage_group(name)
        return data['storage_group_uid']

    def assure_storage_group(self, storage_group):
        try:
            self._client.create_storage_group(storage_group)
        except EMCVnxCLICmdError as ex:
            if ex.out.find("Storage Group name already in use") == -1:
                raise ex

    def assure_host_in_storage_group(self, hostname, storage_group):
        try:
            self._client.connect_host_to_storage_group(hostname, storage_group)
        except EMCVnxCLICmdError as ex:
            if ex.rc == 83:
                # SG was not created or was destroyed by another concurrent
                # operation before connected.
                # Create SG and try to connect again
                LOG.warn(_('Storage Group %s is not found. Create it.'),
                         storage_group)
                self.assure_storage_group(storage_group)
                self._client.connect_host_to_storage_group(
                    hostname, storage_group)
            else:
                raise ex
        return hostname

    def find_device_details(self, volume, storage_group):
        """Returns the Host Device number for the volume."""

        host_lun_id = -1

        data = self._client.get_storage_group(storage_group)
        lun_map = data['lunmap']
        data = self._client.get_lun_by_name(volume['name'])
        allocated_lun_id = data['lun_id']
        owner_sp = data['owner']

        for lun in lun_map.iterkeys():
            if lun == int(allocated_lun_id):
                host_lun_id = lun_map[lun]
                LOG.debug('Host Lun Id : %s' % (host_lun_id))
                break

        LOG.debug('Owner SP : %s' % (owner_sp))

        device = {
            'hostlunid': host_lun_id,
            'ownersp': owner_sp,
            'lunmap': lun_map,
        }
        return device

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
            if rc != 0:
                raise EMCVnxCLICmdError(cmd_iscsi_setpath, rc, out)
        else:
            cmd_fc_setpath = ('storagegroup', '-gname', gname, '-setpath',
                              '-hbauid', initiator_uid, '-sp', sp,
                              '-spport', port_id,
                              '-ip', ip, '-host', host, '-o')
            out, rc = self._client.command_execute(*cmd_fc_setpath)
            if rc != 0:
                raise EMCVnxCLICmdError(cmd_fc_setpath, rc, out)

    def _register_iscsi_initiator(self, ip, host, initiator_uids):
        for initiator_uid in initiator_uids:
            iscsi_targets = self._client.get_iscsi_targets()
            LOG.info(_('Get ISCSI targets %(tg)s to register '
                       'initiator %(in)s.')
                     % ({'tg': iscsi_targets,
                         'in': initiator_uid}))

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
        for initiator_uid in initiator_uids:
            fc_targets = self._client.get_fc_targets()
            LOG.info(_('Get FC targets %(tg)s to register initiator %(in)s.')
                     % ({'tg': fc_targets,
                         'in': initiator_uid}))

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

    def _filter_unregistered_initiators(self, initiator_uids=tuple()):
        unregistered_initiators = []
        if not initiator_uids:
            return unregistered_initiators

        command_get_storage_group = ('storagegroup', '-list')
        out, rc = self._client.command_execute(*command_get_storage_group)

        if rc != 0:
            raise EMCVnxCLICmdError(command_get_storage_group, rc, out)

        for initiator_uid in initiator_uids:
            m = re.search(initiator_uid, out)
            if m is None:
                unregistered_initiators.append(initiator_uid)
        return unregistered_initiators

    def auto_register_initiator(self, connector):
        """Automatically register available initiators."""
        initiator_uids = []
        ip = connector['ip']
        host = connector['host']
        if self.protocol == 'iSCSI':
            initiator_uids = self._extract_iscsi_uids(connector)
            itors_toReg = self._filter_unregistered_initiators(initiator_uids)
            LOG.debug('iSCSI Initiators %(in)s of %(ins)s need registration.'
                      % ({'in': itors_toReg,
                         'ins': initiator_uids}))
            if not itors_toReg:
                LOG.debug('Initiators %s are already registered'
                          % initiator_uids)
                return
            self._register_iscsi_initiator(ip, host, itors_toReg)

        elif self.protocol == 'FC':
            initiator_uids = self._extract_fc_uids(connector)
            itors_toReg = self._filter_unregistered_initiators(initiator_uids)
            LOG.debug('FC Initiators %(in)s of %(ins)s need registration.'
                      % ({'in': itors_toReg,
                         'ins': initiator_uids}))
            if not itors_toReg:
                LOG.debug('Initiators %s are already registered.'
                          % initiator_uids)
                return
            self._register_fc_initiator(ip, host, itors_toReg)

    def assure_host_access(self, volumename, connector):
        hostname = connector['host']
        auto_registration_done = False
        try:
            self.get_storage_group_uid(hostname)
        except EMCVnxCLICmdError as ex:
            if ex.rc != 83:
                raise ex
            # Storage Group has not existed yet
            self.assure_storage_group(hostname)
            if self.itor_auto_reg:
                self.auto_register_initiator(connector)
                auto_registration_done = True
            else:
                self._client.connect_host_to_storage_group(hostname, hostname)

        if self.itor_auto_reg and not auto_registration_done:
            self.auto_register_initiator(connector)
            auto_registration_done = True

        lun_id = self.get_lun_id_by_name(volumename)
        lun_map = self.get_lun_map(hostname)
        if lun_id in lun_map:
            return lun_map[lun_id]
        used_hlus = lun_map.values()
        if len(used_hlus) >= self.max_luns_per_sg:
            msg = (_('Reach limitation set by configuration '
                     'option max_luns_per_storage_group. '
                     'Operation to add %(vol)s into '
                     'Storage Group %(sg)s is rejected.')
                   % {'vol': volumename, 'sg': hostname})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        candidate_hlus = self.filter_available_hlu_set(used_hlus)
        candidate_hlus = list(candidate_hlus)
        random.shuffle(candidate_hlus)
        for i, hlu in enumerate(candidate_hlus):
            if i >= self.max_retries:
                break
            try:
                self._client.add_hlu_to_storage_group(
                    hlu,
                    lun_id,
                    hostname)
                return hlu
            except EMCVnxCLICmdError as ex:
                # Retry
                continue

        msg = _("Failed to add %(vol)s into %(sg)s "
                "after %(retries)s tries.") % \
            {'vol': volumename,
             'sg': hostname,
             'retries': min(self.max_retries, len(candidate_hlus))}
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def vnx_get_iscsi_properties(self, volume, connector):
        storage_group = connector['host']
        device_info = self.find_device_details(volume, storage_group)
        owner_sp = device_info['ownersp']
        registered_spports = self._client.get_registered_spport_set(
            connector['initiator'],
            storage_group)
        target = self._client.find_avaialable_iscsi_target_one(
            storage_group, owner_sp,
            registered_spports)
        properties = {'target_discovered': True,
                      'target_iqn': 'unknown',
                      'target_portal': 'unknown',
                      'target_lun': 'unknown',
                      'volume_id': volume['id']}
        if target:
            properties = {'target_discovered': True,
                          'target_iqn': target['Port WWN'],
                          'target_portal': "%s:3260" % target['IP Address'],
                          'target_lun': device_info['hostlunid']}
            LOG.debug("iSCSI Properties: %s", properties)
            auth = volume['provider_auth']
            if auth:
                (auth_method, auth_username, auth_secret) = auth.split()
                properties['auth_method'] = auth_method
                properties['auth_username'] = auth_username
                properties['auth_password'] = auth_secret
        else:
            LOG.error(_('Failed to find an available iSCSI targets for %s.'),
                      storage_group)

        return properties

    def vnx_get_fc_properties(self, connector, device_number):
        ports = self.get_login_ports(connector)
        return {'target_lun': device_number,
                'target_discovered': True,
                'target_wwn': ports}

    @log_enter_exit
    def initialize_connection(self, volume, connector):
        volume_metadata = {}
        for metadata in volume['volume_admin_metadata']:
            volume_metadata[metadata['key']] = metadata['value']
        access_mode = volume_metadata.get('attached_mode')
        if access_mode is None:
            access_mode = ('ro'
                           if volume_metadata.get('readonly') == 'True'
                           else 'rw')
        LOG.debug('Volume %(vol)s Access mode is: %(access)s.'
                  % {'vol': volume['name'],
                     'access': access_mode})

        """Initializes the connection and returns connection info."""
        @lockutils.synchronized('emc-connection-' + connector['host'],
                                "emc-connection-", True)
        def do_initialize_connection():
            device_number = self.assure_host_access(
                volume['name'], connector)
            return device_number

        if self.protocol == 'iSCSI':
            do_initialize_connection()
            iscsi_properties = self.vnx_get_iscsi_properties(volume,
                                                             connector)
            iscsi_properties['access_mode'] = access_mode
            data = {'driver_volume_type': 'iscsi',
                    'data': iscsi_properties}
        elif self.protocol == 'FC':
            device_number = do_initialize_connection()
            fc_properties = self.vnx_get_fc_properties(connector,
                                                       device_number)
            fc_properties['volume_id'] = volume['id']
            fc_properties['access_mode'] = access_mode
            data = {'driver_volume_type': 'fibre_channel',
                    'data': fc_properties}

        return data

    @log_enter_exit
    def terminate_connection(self, volume, connector):
        """Disallow connection from connector."""

        @lockutils.synchronized('emc-connection-' + connector['host'],
                                "emc-connection-", True)
        def do_terminate_connection():
            hostname = connector['host']
            volume_name = volume['name']
            try:
                lun_map = self.get_lun_map(hostname)
            except EMCVnxCLICmdError as ex:
                if ex.rc == 83:
                    LOG.warn(_("Storage Group %s is not found. "
                               "terminate_connection() is unnecessary."),
                             hostname)
                    return True
            try:
                lun_id = self.get_lun_id(volume)
            except EMCVnxCLICmdError as ex:
                if ex.rc == 9:
                    LOG.warn(_("Volume %s is not found. "
                               "It has probably been removed in VNX.")
                             % volume_name)

            if lun_id in lun_map:
                self._client.remove_hlu_from_storagegroup(
                    lun_map[lun_id], hostname)
            else:
                LOG.warn(_("Volume %(vol)s was not in Storage Group %(sg)s.")
                         % {'vol': volume_name, 'sg': hostname})
            if self.destroy_empty_sg or self.zonemanager_lookup_service:
                try:
                    lun_map = self.get_lun_map(hostname)
                    if not lun_map:
                        LOG.debug("Storage Group %s was empty.", hostname)
                        if self.destroy_empty_sg:
                            LOG.info(_("Storage Group %s was empty, "
                                       "destroy it."), hostname)
                            self._client.disconnect_host_from_storage_group(
                                hostname, hostname)
                            self._client.delete_storage_group(hostname)
                        return True
                    else:
                        LOG.debug("Storage Group %s not empty,", hostname)
                        return False
                except Exception:
                    LOG.warn(_("Failed to destroy Storage Group %s."),
                             hostname)
            else:
                return False
        return do_terminate_connection()

    @log_enter_exit
    def adjust_fc_conn_info(self, conn_info, connector, remove_zone=None):
        target_wwns, itor_tgt_map = self.get_initiator_target_map(
            connector['wwpns'],
            self.get_status_up_ports(connector))
        if target_wwns:
            conn_info['data']['target_wwn'] = target_wwns
        if remove_zone is None or remove_zone:
            # Return initiator_target_map for initialize_connection (None)
            # Return initiator_target_map for terminate_connection when (True)
            # no volumes are in the storagegroup for host to use
            conn_info['data']['initiator_target_map'] = itor_tgt_map
        return conn_info

    @log_enter_exit
    def manage_existing_get_size(self, volume, ref):
        """Return size of volume to be managed by manage_existing.
        """
        # Check that the reference is valid
        if 'id' not in ref:
            reason = _('Reference must contain lun_id element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref,
                reason=reason)

        # Check for existence of the lun
        data = self._client.get_lun_by_id(ref['id'])
        if data is None:
            reason = _('Find no lun with the specified lun_id.')
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)
        return data['total_capacity_gb']

    @log_enter_exit
    def manage_existing(self, volume, ref):
        raise NotImplementedError

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


class EMCVnxCliPool(EMCVnxCliBase):

    def __init__(self, prtcl, configuration):
        super(EMCVnxCliPool, self).__init__(prtcl, configuration=configuration)
        self.storage_pool = configuration.storage_vnx_pool_name.strip()
        self._client.get_pool(self.storage_pool)

    def get_target_storagepool(self,
                               volume=None,
                               source_volume_name=None):
        pool_spec_id = "storagetype:pool"
        if volume is not None:
            specs = self.get_volumetype_extraspecs(volume)
            if specs and pool_spec_id in specs:
                expect_pool = specs[pool_spec_id].strip()
                if expect_pool != self.storage_pool:
                    msg = _("Storage pool %s is not supported"
                            " by this Cinder Volume") % expect_pool
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
        return self.storage_pool

    def is_pool_fastcache_enabled(self, storage_pool, no_poll=False):
        command_check_fastcache = None
        if no_poll:
            command_check_fastcache = ('-np', 'storagepool', '-list', '-name',
                                       storage_pool, '-fastcache')
        else:
            command_check_fastcache = ('storagepool', '-list', '-name',
                                       storage_pool, '-fastcache')
        out, rc = self._client.command_execute(*command_check_fastcache)

        if 0 != rc:
            raise EMCVnxCLICmdError(command_check_fastcache, rc, out)
        else:
            re_fastcache = 'FAST Cache:\s*(.*)\s*'
            m = re.search(re_fastcache, out)
            if m is not None:
                result = True if 'Enabled' == m.group(1) else False
            else:
                LOG.error(_("Error parsing output for FastCache Command."))
        return result

    @log_enter_exit
    def update_volume_stats(self):
        """Retrieve stats info."""
        self.stats = super(EMCVnxCliPool, self).update_volume_stats()
        data = self._client.get_pool(self.get_target_storagepool())
        self.stats['total_capacity_gb'] = data['total_capacity_gb']
        self.stats['free_capacity_gb'] = data['free_capacity_gb']

        array_serial = self._client.get_array_serial(NO_POLL)
        self.stats['location_info'] = ('%(pool_name)s|%(array_serial)s' %
                                       {'pool_name': self.storage_pool,
                                        'array_serial':
                                           array_serial['array_serial']})
        # check if this pool's fast_cache is really enabled
        if self.stats['fast_cache_enabled'] == 'True' and \
           not self.is_pool_fastcache_enabled(self.storage_pool, NO_POLL):
            self.stats['fast_cache_enabled'] = 'False'
        return self.stats

    @log_enter_exit
    def manage_existing(self, volume, ref):
        """Manage an existing lun in the array.

        The lun should be in a manageable pool backend, otherwise
        error would return.
        Rename the backend storage object so that it matches the,
        volume['name'] which is how drivers traditionally map between a
        cinder volume and the associated backend storage object.

        existing_ref:{
            'id':lun_id
        }
        """

        data = self._client.get_lun_by_id(
            ref['id'], self._client.LUN_WITH_POOL)
        if self.storage_pool != data['pool']:
            reason = _('The input lun is not in a manageable pool backend '
                       'by cinder')
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)
        self._client.lun_rename(ref['id'], volume['name'])


class EMCVnxCliArray(EMCVnxCliBase):

    def __init__(self, prtcl, configuration):
        super(EMCVnxCliArray, self).__init__(prtcl,
                                             configuration=configuration)
        self._update_pool_cache()

    def _update_pool_cache(self):
        LOG.debug("Updating Pool Cache")
        self.pool_cache = self._client.get_pool_list(NO_POLL)

    def get_target_storagepool(self, volume, source_volume_name=None):
        """Find the storage pool for given volume."""
        pool_spec_id = "storagetype:pool"
        specs = self.get_volumetype_extraspecs(volume)
        if specs and pool_spec_id in specs:
            return specs[pool_spec_id]
        elif source_volume_name:
            data = self._client.get_lun_by_name(source_volume_name,
                                                [self._client.LUN_POOL])
            if data is None:
                msg = _("Failed to find storage pool for source volume %s") \
                    % source_volume_name
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            return data[self._client.LUN_POOL.key]
        else:
            if len(self.pool_cache) > 0:
                pools = sorted(self.pool_cache,
                               key=lambda po: po['free_space'],
                               reverse=True)
                return pools[0]['name']

        msg = (_("Failed to find storage pool to create volume %s.")
               % volume['name'])
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    @log_enter_exit
    def update_volume_stats(self):
        """Retrieve stats info."""
        self.stats = super(EMCVnxCliArray, self).update_volume_stats()
        self._update_pool_cache()
        self.stats['total_capacity_gb'] = 'unknown'
        self.stats['free_capacity_gb'] = 'unknown'
        array_serial = self._client.get_array_serial(NO_POLL)
        self.stats['location_info'] = ('%(pool_name)s|%(array_serial)s' %
                                       {'pool_name': '',
                                        'array_serial':
                                        array_serial['array_serial']})
        self.stats['fast_cache_enabled'] = 'unknown'
        return self.stats

    @log_enter_exit
    def manage_existing(self, volume, ref):
        """Rename the backend storage object so that it matches the,
        volume['name'] which is how drivers traditionally map between a
        cinder volume and the associated backend storage object.

        existing_ref:{
            'id':lun_id
        }
        """

        self._client.lun_rename(ref['id'], volume['name'])


def getEMCVnxCli(prtcl, configuration=None):
    configuration.append_config_values(loc_opts)
    pool_name = configuration.safe_get("storage_vnx_pool_name")

    if pool_name is None or len(pool_name.strip()) == 0:
        return EMCVnxCliArray(prtcl, configuration=configuration)
    else:
        return EMCVnxCliPool(prtcl, configuration=configuration)
