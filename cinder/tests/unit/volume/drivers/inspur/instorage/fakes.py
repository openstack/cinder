# Copyright 2017 Inspur Corp.
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
"""Tests for the Inspur InStorage volume driver."""

import re

from oslo_concurrency import processutils
from oslo_utils import units
import six

from cinder import exception
from cinder import utils
from cinder.volume.drivers.inspur.instorage import instorage_const
from cinder.volume.drivers.inspur.instorage import instorage_fc
from cinder.volume.drivers.inspur.instorage import instorage_iscsi

MCS_POOLS = ['openstack', 'openstack1']


def get_test_pool(get_all=False):
    if get_all:
        return MCS_POOLS
    else:
        return MCS_POOLS[0]


class FakeInStorageMCSFcDriver(instorage_fc.InStorageMCSFCDriver):

    def __init__(self, *args, **kwargs):
        super(FakeInStorageMCSFcDriver, self).__init__(*args, **kwargs)

    def set_fake_storage(self, fake):
        self.fake_storage = fake

    def _run_ssh(self, cmd, check_exit_code=True, attempts=1):
        utils.check_ssh_injection(cmd)
        ret = self.fake_storage.execute_command(cmd, check_exit_code)

        return ret


class FakeInStorageMCSISCSIDriver(instorage_iscsi.InStorageMCSISCSIDriver):

    def __init__(self, *args, **kwargs):
        super(FakeInStorageMCSISCSIDriver, self).__init__(*args, **kwargs)

    def set_fake_storage(self, fake):
        self.fake_storage = fake

    def _run_ssh(self, cmd, check_exit_code=True, attempts=1):
        utils.check_ssh_injection(cmd)
        ret = self.fake_storage.execute_command(cmd, check_exit_code)

        return ret


class FakeInStorage(object):

    def __init__(self, pool_name):
        self._flags = {'instorage_mcs_volpool_name': pool_name}
        self._volumes_list = {}
        self._hosts_list = {}
        self._mappings_list = {}
        self._lcmappings_list = {}
        self._lcconsistgrp_list = {}
        self._rcrelationship_list = {}
        self._partnership_list = {}
        self._partnershipcandidate_list = {}
        self._system_list = {'instorage-mcs-sim':
                             {'id': '0123456789ABCDEF',
                              'name': 'instorage-mcs-sim'},
                             'aux-mcs-sim': {'id': 'ABCDEF0123456789',
                                             'name': 'aux-mcs-sim'}}
        self._other_pools = {'openstack2': {}, 'openstack3': {}}
        self._next_cmd_error = {
            'lsportip': '',
            'lsfabric': '',
            'lsiscsiauth': '',
            'lsnodecanister': '',
            'mkvdisk': '',
            'lsvdisk': '',
            'lslcmap': '',
            'prestartlcmap': '',
            'startlcmap': '',
            'rmlcmap': '',
            'lslicense': '',
            'lsguicapabilities': '',
            'lshost': '',
            'lsrcrelationship': ''
        }
        self._errors = {
            'CMMVC5701E': ('', 'CMMVC5701E No object ID was specified.'),
            'CMMVC6035E': ('', 'CMMVC6035E The action failed as the '
                               'object already exists.'),
            'CMMVC5753E': ('', 'CMMVC5753E The specified object does not '
                               'exist or is not a suitable candidate.'),
            'CMMVC5707E': ('', 'CMMVC5707E Required parameters are missing.'),
            'CMMVC6581E': ('', 'CMMVC6581E The command has failed because '
                               'the maximum number of allowed iSCSI '
                               'qualified names (IQNs) has been reached, '
                               'or the IQN is already assigned or is not '
                               'valid.'),
            'CMMVC5754E': ('', 'CMMVC5754E The specified object does not '
                               'exist, or the name supplied does not meet '
                               'the naming rules.'),
            'CMMVC6071E': ('', 'CMMVC6071E The VDisk-to-host mapping was '
                               'not created because the VDisk is already '
                               'mapped to a host.'),
            'CMMVC5879E': ('', 'CMMVC5879E The VDisk-to-host mapping was '
                               'not created because a VDisk is already '
                               'mapped to this host with this SCSI LUN.'),
            'CMMVC5840E': ('', 'CMMVC5840E The virtual disk (VDisk) was '
                               'not deleted because it is mapped to a '
                               'host or because it is part of a LocalCopy '
                               'or Remote Copy mapping, or is involved in '
                               'an image mode migrate.'),
            'CMMVC6527E': ('', 'CMMVC6527E The name that you have entered '
                               'is not valid. The name can contain letters, '
                               'numbers, spaces, periods, dashes, and '
                               'underscores. The name must begin with a '
                               'letter or an underscore. The name must not '
                               'begin or end with a space.'),
            'CMMVC5871E': ('', 'CMMVC5871E The action failed because one or '
                               'more of the configured port names is in a '
                               'mapping.'),
            'CMMVC5924E': ('', 'CMMVC5924E The LocalCopy mapping was not '
                               'created because the source and target '
                               'virtual disks (VDisks) are different sizes.'),
            'CMMVC6303E': ('', 'CMMVC6303E The create failed because the '
                               'source and target VDisks are the same.'),
            'CMMVC7050E': ('', 'CMMVC7050E The command failed because at '
                               'least one node in the I/O group does not '
                               'support compressed VDisks.'),
            'CMMVC6430E': ('', 'CMMVC6430E The command failed because the '
                               'target and source managed disk groups must '
                               'be different.'),
            'CMMVC6353E': ('', 'CMMVC6353E The command failed because the '
                               'copy specified does not exist.'),
            'CMMVC6446E': ('', 'The command failed because the managed disk '
                               'groups have different extent sizes.'),
            # Catch-all for invalid state transitions:
            'CMMVC5903E': ('', 'CMMVC5903E The LocalCopy mapping was not '
                               'changed because the mapping or consistency '
                               'group is another state.'),
            'CMMVC5709E': ('', 'CMMVC5709E [-%(VALUE)s] is not a supported '
                               'parameter.'),
            'CMMVC5982E': ('', 'CMMVC5982E The operation was not performed '
                               'because it is not valid given the current '
                               'relationship state.'),
            'CMMVC5963E': ('', 'CMMVC5963E No direction has been defined.'),

        }
        self._lc_transitions = {'begin': {'make': 'idle_or_copied'},
                                'idle_or_copied': {'prepare': 'preparing',
                                                   'delete': 'end',
                                                   'delete_force': 'end'},
                                'preparing': {'flush_failed': 'stopped',
                                              'wait': 'prepared'},
                                'end': None,
                                'stopped': {'prepare': 'preparing',
                                            'delete_force': 'end'},
                                'prepared': {'stop': 'stopped',
                                             'start': 'copying'},
                                'copying': {'wait': 'idle_or_copied',
                                            'stop': 'stopping'},
                                # Assume the worst case where stopping->stopped
                                # rather than stopping idle_or_copied
                                'stopping': {'wait': 'stopped'},
                                }

        self._lc_cg_transitions = {'begin': {'make': 'empty'},
                                   'empty': {'add': 'idle_or_copied'},
                                   'idle_or_copied': {'prepare': 'preparing',
                                                      'delete': 'end',
                                                      'delete_force': 'end'},
                                   'preparing': {'flush_failed': 'stopped',
                                                 'wait': 'prepared'},
                                   'end': None,
                                   'stopped': {'prepare': 'preparing',
                                               'delete_force': 'end'},
                                   'prepared': {'stop': 'stopped',
                                                'start': 'copying',
                                                'delete_force': 'end',
                                                'delete': 'end'},
                                   'copying': {'wait': 'idle_or_copied',
                                               'stop': 'stopping',
                                               'delete_force': 'end',
                                               'delete': 'end'},
                                   # Assume the case where stopping->stopped
                                   # rather than stopping idle_or_copied
                                   'stopping': {'wait': 'stopped'},
                                   }
        self._rc_transitions = {'inconsistent_stopped':
                                {'start': 'inconsistent_copying',
                                 'stop': 'inconsistent_stopped',
                                 'delete': 'end',
                                 'delete_force': 'end'},
                                'inconsistent_copying': {
                                    'wait': 'consistent_synchronized',
                                    'start': 'inconsistent_copying',
                                    'stop': 'inconsistent_stopped',
                                    'delete': 'end',
                                    'delete_force': 'end'},
                                'consistent_synchronized': {
                                    'start': 'consistent_synchronized',
                                    'stop': 'consistent_stopped',
                                    'stop_access': 'idling',
                                    'delete': 'end',
                                    'delete_force': 'end'},
                                'consistent_stopped':
                                {'start': 'consistent_synchronized',
                                 'stop': 'consistent_stopped',
                                 'delete': 'end',
                                 'delete_force': 'end'},
                                'end': None,
                                'idling': {
                                    'start': 'inconsistent_copying',
                                    'stop': 'inconsistent_stopped',
                                    'stop_access': 'idling',
                                    'delete': 'end',
                                    'delete_force': 'end'},
                                }

    def _state_transition(self, function, lcmap):
        if (function == 'wait' and
                'wait' not in self._lc_transitions[lcmap['status']]):
            return ('', '')

        if lcmap['status'] == 'copying' and function == 'wait':
            if lcmap['copyrate'] != '0':
                if lcmap['progress'] == '0':
                    lcmap['progress'] = '50'
                else:
                    lcmap['progress'] = '100'
                    lcmap['status'] = 'idle_or_copied'
            return ('', '')
        else:
            try:
                curr_state = lcmap['status']
                lcmap['status'] = self._lc_transitions[curr_state][function]
                return ('', '')
            except Exception:
                return self._errors['CMMVC5903E']

    def _lc_cg_state_transition(self, function, lc_consistgrp):
        if (function == 'wait' and
                'wait' not in self._lc_transitions[lc_consistgrp['status']]):
            return ('', '')

        try:
            curr_state = lc_consistgrp['status']
            new_state = self._lc_cg_transitions[curr_state][function]
            lc_consistgrp['status'] = new_state
            return ('', '')
        except Exception:
            return self._errors['CMMVC5903E']

    # Find an unused ID
    @staticmethod
    def _find_unused_id(d):
        ids = []
        for v in d.values():
            ids.append(int(v['id']))
        ids.sort()
        for index, n in enumerate(ids):
            if n > index:
                return six.text_type(index)
        return six.text_type(len(ids))

    # Check if name is valid
    @staticmethod
    def _is_invalid_name(name):
        if re.match(r'^[a-zA-Z_][\w._-]*$', name):
            return False
        return True

    # Convert argument string to dictionary
    @staticmethod
    def _cmd_to_dict(arg_list):
        no_param_args = [
            'autodelete',
            'bytes',
            'compressed',
            'force',
            'nohdr',
            'nofmtdisk',
            'async',
            'access',
            'start'
        ]
        one_param_args = [
            'chapsecret',
            'cleanrate',
            'copy',
            'copyrate',
            'delim',
            'intier',
            'filtervalue',
            'grainsize',
            'hbawwpn',
            'host',
            'iogrp',
            'iscsiname',
            'mdiskgrp',
            'name',
            'rsize',
            'scsi',
            'size',
            'source',
            'target',
            'unit',
            'vdisk',
            'warning',
            'wwpn',
            'primary',
            'consistgrp',
            'master',
            'aux',
            'cluster',
            'linkbandwidthmbits',
            'backgroundcopyrate'
        ]
        no_or_one_param_args = [
            'autoexpand',
        ]

        # Handle the special case of lsnode which is a two-word command
        # Use the one word version of the command internally
        if arg_list[0] in ('mcsinq', 'mcsop'):
            if arg_list[1] == 'lsnode':
                if len(arg_list) > 4:  # e.g. mcsinq lsnode -delim ! <node id>
                    ret = {'cmd': 'lsnode', 'node_id': arg_list[-1]}
                else:
                    ret = {'cmd': 'lsnodecanister'}
            else:
                ret = {'cmd': arg_list[1]}
            arg_list.pop(0)
        else:
            ret = {'cmd': arg_list[0]}

        skip = False
        for i in range(1, len(arg_list)):
            if skip:
                skip = False
                continue
            # Check for a quoted command argument for volumes and strip
            # quotes so that the simulater can match it later. Just
            # match against test naming convensions for now.
            if arg_list[i][0] == '"' and ('volume' in arg_list[i] or
                                          'snapshot' in arg_list[i]):
                arg_list[i] = arg_list[i][1:-1]
            if arg_list[i][0] == '-':
                if arg_list[i][1:] in no_param_args:
                    ret[arg_list[i][1:]] = True
                elif arg_list[i][1:] in one_param_args:
                    ret[arg_list[i][1:]] = arg_list[i + 1]
                    skip = True
                elif arg_list[i][1:] in no_or_one_param_args:
                    if i == (len(arg_list) - 1) or arg_list[i + 1][0] == '-':
                        ret[arg_list[i][1:]] = True
                    else:
                        ret[arg_list[i][1:]] = arg_list[i + 1]
                        skip = True
                else:
                    raise exception.InvalidInput(
                        reason='unrecognized argument %s' % arg_list[i])
            else:
                ret['obj'] = arg_list[i]
        return ret

    @staticmethod
    def _print_info_cmd(rows, delim=' ', nohdr=False, **kwargs):
        """Generic function for printing information."""
        if nohdr:
            del rows[0]

        for index in range(len(rows)):
            rows[index] = delim.join(rows[index])
        return ('%s' % '\n'.join(rows), '')

    @staticmethod
    def _print_info_obj_cmd(header, row, delim=' ', nohdr=False):
        """Generic function for printing information for a specific object."""
        objrows = []
        for idx, val in enumerate(header):
            objrows.append([val, row[idx]])

        if nohdr:
            for index in range(len(objrows)):
                objrows[index] = ' '.join(objrows[index][1:])
        for index in range(len(objrows)):
            objrows[index] = delim.join(objrows[index])
        return ('%s' % '\n'.join(objrows), '')

    @staticmethod
    def _convert_bytes_units(bytestr):
        num = int(bytestr)
        unit_array = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        unit_index = 0

        while num > 1024:
            num = num / 1024
            unit_index += 1

        return '%d%s' % (num, unit_array[unit_index])

    @staticmethod
    def _convert_units_bytes(num, unit):
        unit_array = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        unit_index = 0

        while unit.lower() != unit_array[unit_index].lower():
            num = num * 1024
            unit_index += 1

        return six.text_type(num)

    def _cmd_lslicense(self, **kwargs):
        rows = [None] * 3
        rows[0] = ['used_compression_capacity', '0.08']
        rows[1] = ['license_compression_capacity', '0']
        if self._next_cmd_error['lslicense'] == 'no_compression':
            self._next_cmd_error['lslicense'] = ''
            rows[2] = ['license_compression_enclosures', '0']
        else:
            rows[2] = ['license_compression_enclosures', '1']
        return self._print_info_cmd(rows=rows, **kwargs)

    def _cmd_lsguicapabilities(self, **kwargs):
        rows = [None] * 2
        if self._next_cmd_error['lsguicapabilities'] == 'no_compression':
            self._next_cmd_error['lsguicapabilities'] = ''
            rows[0] = ['license_scheme', '0']
        else:
            rows[0] = ['license_scheme', '1813']
        rows[1] = ['product_key', instorage_const.DEV_MODEL_INSTORAGE]
        return self._print_info_cmd(rows=rows, **kwargs)

    # Print mostly made-up stuff in the correct syntax
    def _cmd_lssystem(self, **kwargs):
        rows = [None] * 3
        rows[0] = ['id', '0123456789ABCDEF']
        rows[1] = ['name', 'instorage-mcs-sim']
        rows[2] = ['code_level', '3.1.1.0 (build 87.0.1311291000)']
        return self._print_info_cmd(rows=rows, **kwargs)

    def _cmd_lssystem_aux(self, **kwargs):
        rows = [None] * 3
        rows[0] = ['id', 'ABCDEF0123456789']
        rows[1] = ['name', 'aux-mcs-sim']
        rows[2] = ['code_level', '3.1.1.0 (build 87.0.1311291000)']
        return self._print_info_cmd(rows=rows, **kwargs)

    # Print mostly made-up stuff in the correct syntax, assume -bytes passed
    def _cmd_lsmdiskgrp(self, **kwargs):
        pool_num = len(self._flags['instorage_mcs_volpool_name'])
        rows = []
        rows.append(['id', 'name', 'status', 'mdisk_count',
                     'vdisk_count', 'capacity', 'extent_size',
                     'free_capacity', 'virtual_capacity', 'used_capacity',
                     'real_capacity', 'overallocation', 'warning',
                     'in_tier', 'in_tier_status'])
        for i in range(pool_num):
            row_data = [str(i + 1),
                        self._flags['instorage_mcs_volpool_name'][i], 'online',
                        '1', six.text_type(len(self._volumes_list)),
                        '3573412790272', '256', '3529926246400',
                        '1693247906775',
                        '26843545600', '38203734097', '47', '80', 'auto',
                        'inactive']
            rows.append(row_data)
        rows.append([str(pool_num + 1), 'openstack2', 'online',
                     '1', '0', '3573412790272', '256',
                     '3529432325160', '1693247906775', '26843545600',
                     '38203734097', '47', '80', 'auto', 'inactive'])
        rows.append([str(pool_num + 2), 'openstack3', 'online',
                     '1', '0', '3573412790272', '128',
                     '3529432325160', '1693247906775', '26843545600',
                     '38203734097', '47', '80', 'auto', 'inactive'])
        if 'obj' not in kwargs:
            return self._print_info_cmd(rows=rows, **kwargs)
        else:
            pool_name = kwargs['obj'].strip('\'\"')
            if pool_name == kwargs['obj']:
                raise exception.InvalidInput(
                    reason='obj missing quotes %s' % kwargs['obj'])
            elif pool_name in self._flags['instorage_mcs_volpool_name']:
                for each_row in rows:
                    if pool_name in each_row:
                        row = each_row
                        break
            elif pool_name == 'openstack2':
                row = rows[-2]
            elif pool_name == 'openstack3':
                row = rows[-1]
            else:
                return self._errors['CMMVC5754E']
            objrows = []
            for idx, val in enumerate(rows[0]):
                objrows.append([val, row[idx]])
            if 'nohdr' in kwargs:
                for index in range(len(objrows)):
                    objrows[index] = ' '.join(objrows[index][1:])

            if 'delim' in kwargs:
                for index in range(len(objrows)):
                    objrows[index] = kwargs['delim'].join(objrows[index])

            return ('%s' % '\n'.join(objrows), '')

    # Print mostly made-up stuff in the correct syntax
    def _cmd_lsnodecanister(self, **kwargs):
        rows = [None] * 3
        rows[0] = ['id', 'name', 'UPS_serial_number', 'WWNN', 'status',
                   'IO_group_id', 'IO_group_name', 'config_node',
                   'UPS_unique_id', 'hardware', 'iscsi_name', 'iscsi_alias',
                   'panel_name', 'enclosure_id', 'canister_id',
                   'enclosure_serial_number']
        rows[1] = [
            '1',
            'node1',
            '',
            '123456789ABCDEF0',
            'online',
            '0',
            'io_grp0',
            'yes',
            '123456789ABCDEF0',
            '100',
            'iqn.1982-01.com.inspur:1234.sim.node1',
            '',
            '01-1',
            '1',
            '1',
            '0123ABC']
        rows[2] = [
            '2',
            'node2',
            '',
            '123456789ABCDEF1',
            'online',
            '0',
            'io_grp0',
            'no',
            '123456789ABCDEF1',
            '100',
            'iqn.1982-01.com.inspur:1234.sim.node2',
            '',
            '01-2',
            '1',
            '2',
            '0123ABC']

        if self._next_cmd_error['lsnodecanister'] == 'header_mismatch':
            rows[0].pop(2)
            self._next_cmd_error['lsnodecanister'] = ''
        if self._next_cmd_error['lsnodecanister'] == 'remove_field':
            for row in rows:
                row.pop(0)
            self._next_cmd_error['lsnodecanister'] = ''

        return self._print_info_cmd(rows=rows, **kwargs)

    # Print information of every single node of MCS
    def _cmd_lsnode(self, **kwargs):
        node_infos = dict()
        node_infos['1'] = r'''id!1
name!node1
port_id!500507680210C744
port_status!active
port_speed!8Gb
port_id!500507680220C744
port_status!active
port_speed!8Gb
'''
        node_infos['2'] = r'''id!2
name!node2
port_id!500507680220C745
port_status!active
port_speed!8Gb
port_id!500507680230C745
port_status!inactive
port_speed!N/A
'''
        node_id = kwargs.get('node_id', None)
        stdout = node_infos.get(node_id, '')
        return stdout, ''

    # Print made up stuff for the ports
    def _cmd_lsportfc(self, **kwargs):
        node_1 = [None] * 7
        node_1[0] = ['id', 'fc_io_port_id', 'port_id', 'type',
                     'port_speed', 'node_id', 'node_name', 'WWPN',
                     'nportid', 'status', 'attachment']
        node_1[1] = ['0', '1', '1', 'fc', '8Gb', '1', 'node1',
                     '5005076802132ADE', '012E00', 'active', 'switch']
        node_1[2] = ['1', '2', '2', 'fc', '8Gb', '1', 'node1',
                     '5005076802232ADE', '012E00', 'active', 'switch']
        node_1[3] = ['2', '3', '3', 'fc', '8Gb', '1', 'node1',
                     '5005076802332ADE', '9B0600', 'active', 'switch']
        node_1[4] = ['3', '4', '4', 'fc', '8Gb', '1', 'node1',
                     '5005076802432ADE', '012A00', 'active', 'switch']
        node_1[5] = ['4', '5', '5', 'fc', '8Gb', '1', 'node1',
                     '5005076802532ADE', '014A00', 'active', 'switch']
        node_1[6] = ['5', '6', '4', 'ethernet', 'N/A', '1', 'node1',
                     '5005076802632ADE', '000000',
                     'inactive_unconfigured', 'none']

        node_2 = [None] * 7
        node_2[0] = ['id', 'fc_io_port_id', 'port_id', 'type',
                     'port_speed', 'node_id', 'node_name', 'WWPN',
                     'nportid', 'status', 'attachment']
        node_2[1] = ['6', '7', '7', 'fc', '8Gb', '2', 'node2',
                     '5005086802132ADE', '012E00', 'active', 'switch']
        node_2[2] = ['7', '8', '8', 'fc', '8Gb', '2', 'node2',
                     '5005086802232ADE', '012E00', 'active', 'switch']
        node_2[3] = ['8', '9', '9', 'fc', '8Gb', '2', 'node2',
                     '5005086802332ADE', '9B0600', 'active', 'switch']
        node_2[4] = ['9', '10', '10', 'fc', '8Gb', '2', 'node2',
                     '5005086802432ADE', '012A00', 'active', 'switch']
        node_2[5] = ['10', '11', '11', 'fc', '8Gb', '2', 'node2',
                     '5005086802532ADE', '014A00', 'active', 'switch']
        node_2[6] = ['11', '12', '12', 'ethernet', 'N/A', '2', 'node2',
                     '5005086802632ADE', '000000',
                     'inactive_unconfigured', 'none']
        node_infos = [node_1, node_2]
        node_id = int(kwargs['filtervalue'].split('=')[1]) - 1

        return self._print_info_cmd(rows=node_infos[node_id], **kwargs)

    # Print mostly made-up stuff in the correct syntax
    def _cmd_lsportip(self, **kwargs):
        if self._next_cmd_error['lsportip'] == 'ip_no_config':
            self._next_cmd_error['lsportip'] = ''
            ip_addr1 = ''
            ip_addr2 = ''
            gw = ''
        else:
            ip_addr1 = '1.234.56.78'
            ip_addr2 = '1.234.56.79'
            ip_addr3 = '1.234.56.80'
            ip_addr4 = '1.234.56.81'
            gw = '1.234.56.1'

        rows = [None] * 17
        rows[0] = ['id', 'node_id', 'node_name', 'IP_address', 'mask',
                   'gateway', 'IP_address_6', 'prefix_6', 'gateway_6', 'MAC',
                   'duplex', 'state', 'speed', 'failover', 'link_state']
        rows[1] = ['1', '1', 'node1', ip_addr1, '255.255.255.0',
                   gw, '', '', '', '01:23:45:67:89:00', 'Full',
                   'online', '1Gb/s', 'no', 'active']
        rows[2] = ['1', '1', 'node1', '', '', '', '', '', '',
                   '01:23:45:67:89:00', 'Full', 'online', '1Gb/s', 'yes', '']
        rows[3] = ['2', '1', 'node1', ip_addr3, '255.255.255.0',
                   gw, '', '', '', '01:23:45:67:89:01', 'Full',
                   'configured', '1Gb/s', 'no', 'active']
        rows[4] = ['2', '1', 'node1', '', '', '', '', '', '',
                   '01:23:45:67:89:01', 'Full', 'unconfigured', '1Gb/s',
                   'yes', 'inactive']
        rows[5] = ['3', '1', 'node1', '', '', '', '', '', '', '', '',
                   'unconfigured', '', 'no', '']
        rows[6] = ['3', '1', 'node1', '', '', '', '', '', '', '', '',
                   'unconfigured', '', 'yes', '']
        rows[7] = ['4', '1', 'node1', '', '', '', '', '', '', '', '',
                   'unconfigured', '', 'no', '']
        rows[8] = ['4', '1', 'node1', '', '', '', '', '', '', '', '',
                   'unconfigured', '', 'yes', '']
        rows[9] = ['1', '2', 'node2', ip_addr2, '255.255.255.0',
                   gw, '', '', '', '01:23:45:67:89:02', 'Full',
                   'online', '1Gb/s', 'no', '']
        rows[10] = ['1', '2', 'node2', '', '', '', '', '', '',
                    '01:23:45:67:89:02', 'Full', 'online', '1Gb/s', 'yes', '']
        rows[11] = ['2', '2', 'node2', ip_addr4, '255.255.255.0',
                    gw, '', '', '', '01:23:45:67:89:03', 'Full',
                    'configured', '1Gb/s', 'no', 'inactive']
        rows[12] = ['2', '2', 'node2', '', '', '', '', '', '',
                    '01:23:45:67:89:03', 'Full', 'unconfigured', '1Gb/s',
                    'yes', '']
        rows[13] = ['3', '2', 'node2', '', '', '', '', '', '', '', '',
                    'unconfigured', '', 'no', '']
        rows[14] = ['3', '2', 'node2', '', '', '', '', '', '', '', '',
                    'unconfigured', '', 'yes', '']
        rows[15] = ['4', '2', 'node2', '', '', '', '', '', '', '', '',
                    'unconfigured', '', 'no', '']
        rows[16] = ['4', '2', 'node2', '', '', '', '', '', '', '', '',
                    'unconfigured', '', 'yes', '']

        if self._next_cmd_error['lsportip'] == 'header_mismatch':
            rows[0].pop(2)
            self._next_cmd_error['lsportip'] = ''
        if self._next_cmd_error['lsportip'] == 'remove_field':
            for row in rows:
                row.pop(1)
            self._next_cmd_error['lsportip'] = ''

        return self._print_info_cmd(rows=rows, **kwargs)

    def _cmd_lsfabric(self, **kwargs):
        if self._next_cmd_error['lsfabric'] == 'no_hosts':
            return ('', '')
        host_name = kwargs['host'].strip('\'\"') if 'host' in kwargs else None
        target_wwpn = kwargs['wwpn'] if 'wwpn' in kwargs else None
        host_infos = []
        for hv in self._hosts_list.values():
            if (not host_name) or (hv['host_name'] == host_name):
                if not target_wwpn or target_wwpn in hv['wwpns']:
                    host_infos.append(hv)
                    break
        if not len(host_infos):
            return ('', '')
        rows = []
        rows.append(['remote_wwpn', 'remote_nportid', 'id', 'node_name',
                     'local_wwpn', 'local_port', 'local_nportid', 'state',
                     'name', 'cluster_name', 'type'])
        for host_info in host_infos:
            for wwpn in host_info['wwpns']:
                rows.append([wwpn, '123456', host_info['id'], 'nodeN',
                             'AABBCCDDEEFF0011', '1', '0123ABC', 'active',
                             host_info['host_name'], '', 'host'])
        if self._next_cmd_error['lsfabric'] == 'header_mismatch':
            rows[0].pop(0)
            self._next_cmd_error['lsfabric'] = ''
        if self._next_cmd_error['lsfabric'] == 'remove_field':
            for row in rows:
                row.pop(0)
            self._next_cmd_error['lsfabric'] = ''
        if self._next_cmd_error['lsfabric'] == 'remove_rows':
            rows = []
        return self._print_info_cmd(rows=rows, **kwargs)

    def _get_lcmap_info(self, vol_name):
        ret_vals = {
            'fc_id': '',
            'fc_name': '',
            'lc_map_count': '0',
        }
        for lcmap in self._lcmappings_list.values():
            if ((lcmap['source'] == vol_name) or
                    (lcmap['target'] == vol_name)):
                ret_vals['fc_id'] = lcmap['id']
                ret_vals['fc_name'] = lcmap['name']
                ret_vals['lc_map_count'] = '1'
        return ret_vals

    # List information about vdisks
    def _cmd_lsvdisk(self, **kwargs):
        rows = []
        rows.append(['id', 'name', 'IO_group_id', 'IO_group_name',
                     'status', 'mdisk_grp_id', 'mdisk_grp_name',
                     'capacity', 'type', 'FC_id', 'FC_name', 'RC_id',
                     'RC_name', 'vdisk_UID', 'lc_map_count', 'copy_count',
                     'fast_write_state', 'se_copy_count', 'RC_change'])

        for vol in self._volumes_list.values():
            if (('filtervalue' not in kwargs) or
                (kwargs['filtervalue'] == 'name=' + vol['name']) or
                    (kwargs['filtervalue'] == 'vdisk_UID=' + vol['uid'])):
                lcmap_info = self._get_lcmap_info(vol['name'])

                if 'bytes' in kwargs:
                    cap = self._convert_bytes_units(vol['capacity'])
                else:
                    cap = vol['capacity']
                rows.append([six.text_type(vol['id']), vol['name'],
                             vol['IO_group_id'],
                             vol['IO_group_name'], 'online', '0',
                             get_test_pool(),
                             cap, 'striped',
                             lcmap_info['fc_id'], lcmap_info['fc_name'],
                             '', '', vol['uid'],
                             lcmap_info['lc_map_count'], '1', 'empty',
                             '1', 'no'])
        if 'obj' not in kwargs:
            return self._print_info_cmd(rows=rows, **kwargs)
        else:
            if kwargs['obj'] not in self._volumes_list:
                return self._errors['CMMVC5754E']
            vol = self._volumes_list[kwargs['obj']]
            lcmap_info = self._get_lcmap_info(vol['name'])
            cap = vol['capacity']
            cap_u = vol['used_capacity']
            cap_r = vol['real_capacity']
            cap_f = vol['free_capacity']
            if 'bytes' not in kwargs:
                for item in [cap, cap_u, cap_r, cap_f]:
                    item = self._convert_bytes_units(item)
            rows = []

            rows.append(['id', six.text_type(vol['id'])])
            rows.append(['name', vol['name']])
            rows.append(['IO_group_id', vol['IO_group_id']])
            rows.append(['IO_group_name', vol['IO_group_name']])
            rows.append(['status', 'online'])
            rows.append(['capacity', cap])
            rows.append(['formatted', vol['formatted']])
            rows.append(['mdisk_id', ''])
            rows.append(['mdisk_name', ''])
            rows.append(['FC_id', lcmap_info['fc_id']])
            rows.append(['FC_name', lcmap_info['fc_name']])
            rows.append(['RC_id', vol['RC_id']])
            rows.append(['RC_name', vol['RC_name']])
            rows.append(['vdisk_UID', vol['uid']])
            rows.append(['throttling', '0'])

            if self._next_cmd_error['lsvdisk'] == 'blank_pref_node':
                rows.append(['preferred_node_id', ''])
                self._next_cmd_error['lsvdisk'] = ''
            elif self._next_cmd_error['lsvdisk'] == 'no_pref_node':
                self._next_cmd_error['lsvdisk'] = ''
            else:
                rows.append(['preferred_node_id', '1'])
            rows.append(['fast_write_state', 'empty'])
            rows.append(['cache', 'readwrite'])
            rows.append(['udid', ''])
            rows.append(['lc_map_count', lcmap_info['lc_map_count']])
            rows.append(['sync_rate', '50'])
            rows.append(['copy_count', '1'])
            rows.append(['se_copy_count', '0'])
            rows.append(['mirror_write_priority', 'latency'])
            rows.append(['RC_change', 'no'])

            for copy in vol['copies'].values():
                rows.append(['copy_id', copy['id']])
                rows.append(['status', copy['status']])
                rows.append(['primary', copy['primary']])
                rows.append(['mdisk_grp_id', copy['mdisk_grp_id']])
                rows.append(['mdisk_grp_name', copy['mdisk_grp_name']])
                rows.append(['type', 'striped'])
                rows.append(['used_capacity', cap_u])
                rows.append(['real_capacity', cap_r])
                rows.append(['free_capacity', cap_f])
                rows.append(['in_tier', copy['in_tier']])
                rows.append(['compressed_copy', copy['compressed_copy']])
                rows.append(['autoexpand', vol['autoexpand']])
                rows.append(['warning', vol['warning']])
                rows.append(['grainsize', vol['grainsize']])

            if 'nohdr' in kwargs:
                for index in range(len(rows)):
                    rows[index] = ' '.join(rows[index][1:])

            if 'delim' in kwargs:
                for index in range(len(rows)):
                    rows[index] = kwargs['delim'].join(rows[index])
            return ('%s' % '\n'.join(rows), '')

    def _cmd_lsiogrp(self, **kwargs):
        rows = [None] * 6
        rows[0] = ['id', 'name', 'node_count', 'vdisk_count', 'host_count']
        rows[1] = ['0', 'io_grp0', '2', '0', '4']
        rows[2] = ['1', 'io_grp1', '2', '0', '4']
        rows[3] = ['2', 'io_grp2', '0', '0', '4']
        rows[4] = ['3', 'io_grp3', '0', '0', '4']
        rows[5] = ['4', 'recovery_io_grp', '0', '0', '0']
        return self._print_info_cmd(rows=rows, **kwargs)

    # List information about hosts
    def _cmd_lshost(self, **kwargs):
        if 'obj' not in kwargs:
            rows = []
            rows.append(['id', 'name', 'port_count', 'iogrp_count', 'status'])

            found = False
            # Sort hosts by names to give predictable order for tests
            # depend on it.
            for host_name in sorted(self._hosts_list.keys()):
                host = self._hosts_list[host_name]
                filterstr = 'name=' + host['host_name']
                if (('filtervalue' not in kwargs) or
                        (kwargs['filtervalue'] == filterstr)):
                    rows.append([host['id'], host['host_name'], '1', '4',
                                 'offline'])
                    found = True
            if found:
                return self._print_info_cmd(rows=rows, **kwargs)
            else:
                return ('', '')
        else:
            if self._next_cmd_error['lshost'] == 'missing_host':
                self._next_cmd_error['lshost'] = ''
                return self._errors['CMMVC5754E']
            elif self._next_cmd_error['lshost'] == 'bigger_troubles':
                return self._errors['CMMVC6527E']
            host_name = kwargs['obj'].strip('\'\"')
            if host_name not in self._hosts_list:
                return self._errors['CMMVC5754E']
            if (self._next_cmd_error['lshost'] == 'fail_fastpath' and
                    host_name == 'DifferentHost'):
                return self._errors['CMMVC5701E']
            host = self._hosts_list[host_name]
            rows = []
            rows.append(['id', host['id']])
            rows.append(['name', host['host_name']])
            rows.append(['port_count', '1'])
            rows.append(['type', 'generic'])
            rows.append(['mask', '1111'])
            rows.append(['iogrp_count', '4'])
            rows.append(['status', 'online'])
            for port in host['iscsi_names']:
                rows.append(['iscsi_name', port])
                rows.append(['node_logged_in_count', '0'])
                rows.append(['state', 'offline'])
            for port in host['wwpns']:
                rows.append(['WWPN', port])
                rows.append(['node_logged_in_count', '0'])
                rows.append(['state', 'active'])

            if 'nohdr' in kwargs:
                for index in range(len(rows)):
                    rows[index] = ' '.join(rows[index][1:])

            if 'delim' in kwargs:
                for index in range(len(rows)):
                    rows[index] = kwargs['delim'].join(rows[index])

            return ('%s' % '\n'.join(rows), '')

    # List iSCSI authorization information about hosts
    def _cmd_lsiscsiauth(self, **kwargs):
        if self._next_cmd_error['lsiscsiauth'] == 'no_info':
            self._next_cmd_error['lsiscsiauth'] = ''
            return ('', '')
        rows = []
        rows.append(['type', 'id', 'name', 'iscsi_auth_method',
                     'iscsi_chap_secret'])

        for host in self._hosts_list.values():
            method = 'none'
            secret = ''
            if 'chapsecret' in host:
                method = 'chap'
                secret = host['chapsecret']
            rows.append(['host', host['id'], host['host_name'], method,
                         secret])
        return self._print_info_cmd(rows=rows, **kwargs)

    # List information about host->vdisk mappings
    def _cmd_lshostvdiskmap(self, **kwargs):
        host_name = kwargs['obj'].strip('\'\"')

        if host_name not in self._hosts_list:
            return self._errors['CMMVC5754E']

        rows = []
        rows.append(['id', 'name', 'SCSI_id', 'vdisk_id', 'vdisk_name',
                     'vdisk_UID'])

        for mapping in self._mappings_list.values():
            if (host_name == '') or (mapping['host'] == host_name):
                volume = self._volumes_list[mapping['vol']]
                rows.append([mapping['id'], mapping['host'],
                             mapping['lun'], volume['id'],
                             volume['name'], volume['uid']])

        return self._print_info_cmd(rows=rows, **kwargs)

    # List information about vdisk->host mappings
    def _cmd_lsvdiskhostmap(self, **kwargs):
        mappings_found = 0
        vdisk_name = kwargs['obj'].strip('\'\"')

        if vdisk_name not in self._volumes_list:
            return self._errors['CMMVC5753E']

        rows = []
        rows.append(['id name', 'SCSI_id', 'host_id', 'host_name', 'vdisk_UID',
                     'IO_group_id', 'IO_group_name'])

        for mapping in self._mappings_list.values():
            if (mapping['vol'] == vdisk_name):
                mappings_found += 1
                volume = self._volumes_list[mapping['vol']]
                host = self._hosts_list[mapping['host']]
                rows.append([volume['id'], mapping['lun'], host['id'],
                             host['host_name'], volume['uid'],
                             volume['IO_group_id'], volume['IO_group_name']])

        if mappings_found:
            return self._print_info_cmd(rows=rows, **kwargs)
        else:
            return ('', '')

    def _cmd_lsvdisklcmappings(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5707E']
        vdisk = kwargs['obj']
        rows = []
        rows.append(['id', 'name'])
        for v in self._lcmappings_list.values():
            if v['source'] == vdisk or v['target'] == vdisk:
                rows.append([v['id'], v['name']])
        return self._print_info_cmd(rows=rows, **kwargs)

    def _cmd_lslcmap(self, **kwargs):
        rows = []
        rows.append(['id', 'name', 'source_vdisk_id', 'source_vdisk_name',
                     'target_vdisk_id', 'target_vdisk_name', 'group_id',
                     'group_name', 'status', 'progress', 'copy_rate',
                     'clean_progress', 'incremental', 'partner_FC_id',
                     'partner_FC_name', 'restoring', 'start_time',
                     'rc_controlled'])

        # Assume we always get a filtervalue argument
        filter_key = kwargs['filtervalue'].split('=')[0]
        filter_value = kwargs['filtervalue'].split('=')[1]
        to_delete = []
        for k, v in self._lcmappings_list.items():
            if six.text_type(v[filter_key]) == filter_value:
                source = self._volumes_list[v['source']]
                target = self._volumes_list[v['target']]
                self._state_transition('wait', v)

                if self._next_cmd_error['lslcmap'] == 'speed_up':
                    self._next_cmd_error['lslcmap'] = ''
                    curr_state = v['status']
                    while self._state_transition('wait', v) == ("", ""):
                        if curr_state == v['status']:
                            break
                        curr_state = v['status']

                if ((v['status'] == 'idle_or_copied' and v['autodelete'] and
                     v['progress'] == '100') or (v['status'] == 'end')):
                    to_delete.append(k)
                else:
                    rows.append([v['id'], v['name'], source['id'],
                                 source['name'], target['id'], target['name'],
                                 '', '', v['status'], v['progress'],
                                 v['copyrate'], '100', 'off', '', '', 'no', '',
                                 'no'])

        for d in to_delete:
            del self._lcmappings_list[d]

        return self._print_info_cmd(rows=rows, **kwargs)

    def _cmd_lslcconsistgrp(self, **kwargs):
        rows = []

        if 'obj' not in kwargs:
            rows.append(['id', 'name', 'status' 'start_time'])

            for lcconsistgrp in self._lcconsistgrp_list.values():
                rows.append([lcconsistgrp['id'],
                             lcconsistgrp['name'],
                             lcconsistgrp['status'],
                             lcconsistgrp['start_time']])
            return self._print_info_cmd(rows=rows, **kwargs)
        else:
            lcconsistgrp = None
            cg_id = 0
            for cg_id in self._lcconsistgrp_list.keys():
                if self._lcconsistgrp_list[cg_id]['name'] == kwargs['obj']:
                    lcconsistgrp = self._lcconsistgrp_list[cg_id]
            rows = []
            rows.append(['id', six.text_type(cg_id)])
            rows.append(['name', lcconsistgrp['name']])
            rows.append(['status', lcconsistgrp['status']])
            rows.append(['autodelete',
                         six.text_type(lcconsistgrp['autodelete'])])
            rows.append(['start_time',
                         six.text_type(lcconsistgrp['start_time'])])

            for lcmap_id in lcconsistgrp['lcmaps'].keys():
                rows.append(['FC_mapping_id', six.text_type(lcmap_id)])
                rows.append(['FC_mapping_name',
                             lcconsistgrp['lcmaps'][lcmap_id]])

            if 'delim' in kwargs:
                for index in range(len(rows)):
                    rows[index] = kwargs['delim'].join(rows[index])
            self._lc_cg_state_transition('wait', lcconsistgrp)
            return ('%s' % '\n'.join(rows), '')

    def _cmd_lsvdiskcopy(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5804E']
        name = kwargs['obj']
        vol = self._volumes_list[name]
        rows = []
        rows.append(['vdisk_id', 'vdisk_name', 'copy_id', 'status', 'sync',
                     'primary', 'mdisk_grp_id', 'mdisk_grp_name', 'capacity',
                     'type', 'se_copy', 'in_tier', 'in_tier_status',
                     'compressed_copy'])
        for copy in vol['copies'].values():
            rows.append([vol['id'], vol['name'], copy['id'],
                         copy['status'], copy['sync'], copy['primary'],
                         copy['mdisk_grp_id'], copy['mdisk_grp_name'],
                         vol['capacity'], 'striped', 'yes', copy['in_tier'],
                         'inactive', copy['compressed_copy']])
        if 'copy' not in kwargs:
            return self._print_info_cmd(rows=rows, **kwargs)
        else:
            copy_id = kwargs['copy'].strip('\'\"')
            if copy_id not in vol['copies']:
                return self._errors['CMMVC6353E']
            copy = vol['copies'][copy_id]
            rows = []
            rows.append(['vdisk_id', vol['id']])
            rows.append(['vdisk_name', vol['name']])
            rows.append(['capacity', vol['capacity']])
            rows.append(['copy_id', copy['id']])
            rows.append(['status', copy['status']])
            rows.append(['sync', copy['sync']])
            copy['sync'] = 'yes'
            rows.append(['primary', copy['primary']])
            rows.append(['mdisk_grp_id', copy['mdisk_grp_id']])
            rows.append(['mdisk_grp_name', copy['mdisk_grp_name']])
            rows.append(['in_tier', copy['in_tier']])
            rows.append(['in_tier_status', 'inactive'])
            rows.append(['compressed_copy', copy['compressed_copy']])
            rows.append(['autoexpand', vol['autoexpand']])

            if 'delim' in kwargs:
                for index in range(len(rows)):
                    rows[index] = kwargs['delim'].join(rows[index])

            return ('%s' % '\n'.join(rows), '')

    # list vdisk sync process
    def _cmd_lsvdisksyncprogress(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5804E']
        name = kwargs['obj']
        copy_id = kwargs.get('copy', None)
        vol = self._volumes_list[name]
        rows = []
        rows.append(['vdisk_id', 'vdisk_name', 'copy_id', 'progress',
                     'estimated_completion_time'])
        copy_found = False
        for copy in vol['copies'].values():
            if not copy_id or copy_id == copy['id']:
                copy_found = True
                row = [vol['id'], name, copy['id']]
                if copy['sync'] == 'yes':
                    row.extend(['100', ''])
                else:
                    row.extend(['50', '140210115226'])
                    copy['sync'] = 'yes'
                rows.append(row)
        if not copy_found:
            return self._errors['CMMVC5804E']
        return self._print_info_cmd(rows=rows, **kwargs)

    def _cmd_lsrcrelationship(self, **kwargs):
        rows = []
        rows.append(['id', 'name', 'master_cluster_id', 'master_cluster_name',
                     'master_vdisk_id', 'master_vdisk_name', 'aux_cluster_id',
                     'aux_cluster_name', 'aux_vdisk_id', 'aux_vdisk_name',
                     'consistency_group_id', 'primary',
                     'consistency_group_name', 'state', 'bg_copy_priority',
                     'progress', 'freeze_time', 'status', 'sync',
                     'copy_type', 'cycling_mode', 'cycle_period_seconds',
                     'master_change_vdisk_id', 'master_change_vdisk_name',
                     'aux_change_vdisk_id', 'aux_change_vdisk_name'])

        # Assume we always get a filtervalue argument
        filter_key = kwargs['filtervalue'].split('=')[0]
        filter_value = kwargs['filtervalue'].split('=')[1]
        for k, v in self._rcrelationship_list.items():
            if six.text_type(v[filter_key]) == filter_value:
                self._rc_state_transition('wait', v)

                if self._next_cmd_error['lsrcrelationship'] == 'speed_up':
                    self._next_cmd_error['lsrcrelationship'] = ''
                    curr_state = v['status']
                    while self._rc_state_transition('wait', v) == ("", ""):
                        if curr_state == v['status']:
                            break
                        curr_state = v['status']

                rows.append([v['id'], v['name'], v['master_cluster_id'],
                             v['master_cluster_name'], v['master_vdisk_id'],
                             v['master_vdisk_name'], v['aux_cluster_id'],
                             v['aux_cluster_name'], v['aux_vdisk_id'],
                             v['aux_vdisk_name'], v['consistency_group_id'],
                             v['primary'], v['consistency_group_name'],
                             v['state'], v['bg_copy_priority'], v['progress'],
                             v['freeze_time'], v['status'], v['sync'],
                             v['copy_type'], v['cycling_mode'],
                             v['cycle_period_seconds'],
                             v['master_change_vdisk_id'],
                             v['master_change_vdisk_name'],
                             v['aux_change_vdisk_id'],
                             v['aux_change_vdisk_name']])

        return self._print_info_cmd(rows=rows, **kwargs)

    def _cmd_lspartnershipcandidate(self, **kwargs):
        rows = [None] * 4
        master_sys = self._system_list['instorage-mcs-sim']
        aux_sys = self._system_list['aux-mcs-sim']
        rows[0] = ['id', 'configured', 'name']
        rows[1] = [master_sys['id'], 'no', master_sys['name']]
        rows[2] = [aux_sys['id'], 'no', aux_sys['name']]
        rows[3] = ['0123456789001234', 'no', 'fake_mcs']
        return self._print_info_cmd(rows=rows, **kwargs)

    def _cmd_lspartnership(self, **kwargs):
        rows = []
        rows.append(['id', 'name', 'location', 'partnership',
                     'type', 'cluster_ip', 'event_log_sequence'])

        master_sys = self._system_list['instorage-mcs-sim']
        if master_sys['name'] not in self._partnership_list:
            local_info = {}
            local_info['id'] = master_sys['id']
            local_info['name'] = master_sys['name']
            local_info['location'] = 'local'
            local_info['type'] = ''
            local_info['cluster_ip'] = ''
            local_info['event_log_sequence'] = ''
            local_info['chap_secret'] = ''
            local_info['linkbandwidthmbits'] = ''
            local_info['backgroundcopyrate'] = ''
            local_info['partnership'] = ''
            self._partnership_list[master_sys['id']] = local_info

        # Assume we always get a filtervalue argument
        filter_key = kwargs['filtervalue'].split('=')[0]
        filter_value = kwargs['filtervalue'].split('=')[1]
        for k, v in self._partnership_list.items():
            if six.text_type(v[filter_key]) == filter_value:
                rows.append([v['id'], v['name'], v['location'],
                             v['partnership'], v['type'], v['cluster_ip'],
                             v['event_log_sequence']])
        return self._print_info_cmd(rows=rows, **kwargs)

    def _get_mdiskgrp_id(self, mdiskgrp):
        grp_num = len(self._flags['instorage_mcs_volpool_name'])
        if mdiskgrp in self._flags['instorage_mcs_volpool_name']:
            for i in range(grp_num):
                if mdiskgrp == self._flags['instorage_mcs_volpool_name'][i]:
                    return i + 1
        elif mdiskgrp == 'openstack2':
            return grp_num + 1
        elif mdiskgrp == 'openstack3':
            return grp_num + 2
        else:
            return None

    # Create a vdisk
    def _cmd_mkvdisk(self, **kwargs):
        # We only save the id/uid, name, and size - all else will be made up
        volume_info = {}
        volume_info['id'] = self._find_unused_id(self._volumes_list)
        volume_info['uid'] = ('ABCDEF' * 3) + ('0' * 14) + volume_info['id']

        mdiskgrp = kwargs['mdiskgrp'].strip('\'\"')
        if mdiskgrp == kwargs['mdiskgrp']:
            raise exception.InvalidInput(
                reason='mdiskgrp missing quotes %s' % kwargs['mdiskgrp'])
        mdiskgrp_id = self._get_mdiskgrp_id(mdiskgrp)
        volume_info['mdisk_grp_name'] = mdiskgrp
        volume_info['mdisk_grp_id'] = str(mdiskgrp_id)

        if 'name' in kwargs:
            volume_info['name'] = kwargs['name'].strip('\'\"')
        else:
            volume_info['name'] = 'vdisk' + volume_info['id']

        # Assume size and unit are given, store it in bytes
        capacity = int(kwargs['size'])
        unit = kwargs['unit']
        volume_info['capacity'] = self._convert_units_bytes(capacity, unit)
        volume_info['IO_group_id'] = kwargs['iogrp']
        volume_info['IO_group_name'] = 'io_grp%s' % kwargs['iogrp']
        volume_info['RC_name'] = ''
        volume_info['RC_id'] = ''

        if 'intier' in kwargs:
            if kwargs['intier'] == 'on':
                volume_info['in_tier'] = 'on'
            else:
                volume_info['in_tier'] = 'off'

        if 'rsize' in kwargs:
            volume_info['formatted'] = 'no'
            # Fake numbers
            volume_info['used_capacity'] = '786432'
            volume_info['real_capacity'] = '21474816'
            volume_info['free_capacity'] = '38219264'
            if 'warning' in kwargs:
                volume_info['warning'] = kwargs['warning'].rstrip('%')
            else:
                volume_info['warning'] = '80'
            if 'autoexpand' in kwargs:
                volume_info['autoexpand'] = 'on'
            else:
                volume_info['autoexpand'] = 'off'
            if 'grainsize' in kwargs:
                volume_info['grainsize'] = kwargs['grainsize']
            else:
                volume_info['grainsize'] = '32'
            if 'compressed' in kwargs:
                volume_info['compressed_copy'] = 'yes'
            else:
                volume_info['compressed_copy'] = 'no'
        else:
            volume_info['used_capacity'] = volume_info['capacity']
            volume_info['real_capacity'] = volume_info['capacity']
            volume_info['free_capacity'] = '0'
            volume_info['warning'] = ''
            volume_info['autoexpand'] = ''
            volume_info['grainsize'] = ''
            volume_info['compressed_copy'] = 'no'
            volume_info['formatted'] = 'yes'
            if 'nofmtdisk' in kwargs:
                if kwargs['nofmtdisk']:
                    volume_info['formatted'] = 'no'

        vol_cp = {'id': '0',
                  'status': 'online',
                  'sync': 'yes',
                  'primary': 'yes',
                  'mdisk_grp_id': str(mdiskgrp_id),
                  'mdisk_grp_name': mdiskgrp,
                  'in_tier': volume_info['in_tier'],
                  'compressed_copy': volume_info['compressed_copy']}
        volume_info['copies'] = {'0': vol_cp}

        if volume_info['name'] in self._volumes_list:
            return self._errors['CMMVC6035E']
        else:
            self._volumes_list[volume_info['name']] = volume_info
            return ('Virtual Disk, id [%s], successfully created' %
                    (volume_info['id']), '')

    # Delete a vdisk
    def _cmd_rmvdisk(self, **kwargs):
        force = True if 'force' in kwargs else False

        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        vol_name = kwargs['obj'].strip('\'\"')

        if vol_name not in self._volumes_list:
            return self._errors['CMMVC5753E']

        if not force:
            for mapping in self._mappings_list.values():
                if mapping['vol'] == vol_name:
                    return self._errors['CMMVC5840E']
            for lcmap in self._lcmappings_list.values():
                if ((lcmap['source'] == vol_name) or
                        (lcmap['target'] == vol_name)):
                    return self._errors['CMMVC5840E']

        del self._volumes_list[vol_name]
        return ('', '')

    def _cmd_expandvdisksize(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        vol_name = kwargs['obj'].strip('\'\"')

        # Assume unit is gb
        if 'size' not in kwargs:
            return self._errors['CMMVC5707E']
        size = int(kwargs['size'])

        if vol_name not in self._volumes_list:
            return self._errors['CMMVC5753E']

        curr_size = int(self._volumes_list[vol_name]['capacity'])
        addition = size * units.Gi
        self._volumes_list[vol_name]['capacity'] = (
            six.text_type(curr_size + addition))
        return ('', '')

    def _add_port_to_host(self, host_info, **kwargs):
        if 'iscsiname' in kwargs:
            added_key = 'iscsi_names'
            added_val = kwargs['iscsiname'].strip('\'\"')
        elif 'hbawwpn' in kwargs:
            added_key = 'wwpns'
            added_val = kwargs['hbawwpn'].strip('\'\"')
        else:
            return self._errors['CMMVC5707E']

        host_info[added_key].append(added_val)

        for v in self._hosts_list.values():
            if v['id'] == host_info['id']:
                continue
            for port in v[added_key]:
                if port == added_val:
                    return self._errors['CMMVC6581E']
        return ('', '')

    # Make a host
    def _cmd_mkhost(self, **kwargs):
        host_info = {}
        host_info['id'] = self._find_unused_id(self._hosts_list)

        if 'name' in kwargs:
            host_name = kwargs['name'].strip('\'\"')
        else:
            host_name = 'host' + six.text_type(host_info['id'])

        if self._is_invalid_name(host_name):
            return self._errors['CMMVC6527E']

        if host_name in self._hosts_list:
            return self._errors['CMMVC6035E']

        host_info['host_name'] = host_name
        host_info['iscsi_names'] = []
        host_info['wwpns'] = []

        out, err = self._add_port_to_host(host_info, **kwargs)
        if not len(err):
            self._hosts_list[host_name] = host_info
            return ('Host, id [%s], successfully created' %
                    (host_info['id']), '')
        else:
            return (out, err)

    # Add ports to an existing host
    def _cmd_addhostport(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        host_name = kwargs['obj'].strip('\'\"')

        if host_name not in self._hosts_list:
            return self._errors['CMMVC5753E']

        host_info = self._hosts_list[host_name]
        return self._add_port_to_host(host_info, **kwargs)

    # Change host properties
    def _cmd_chhost(self, **kwargs):
        if 'chapsecret' not in kwargs:
            return self._errors['CMMVC5707E']
        secret = kwargs['obj'].strip('\'\"')

        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        host_name = kwargs['obj'].strip('\'\"')

        if host_name not in self._hosts_list:
            return self._errors['CMMVC5753E']

        self._hosts_list[host_name]['chapsecret'] = secret
        return ('', '')

    # Remove a host
    def _cmd_rmhost(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']

        host_name = kwargs['obj'].strip('\'\"')
        if host_name not in self._hosts_list:
            return self._errors['CMMVC5753E']

        for v in self._mappings_list.values():
            if (v['host'] == host_name):
                return self._errors['CMMVC5871E']

        del self._hosts_list[host_name]
        return ('', '')

    # Create a vdisk-host mapping
    def _cmd_mkvdiskhostmap(self, **kwargs):
        mapping_info = {}
        mapping_info['id'] = self._find_unused_id(self._mappings_list)
        if 'host' not in kwargs:
            return self._errors['CMMVC5707E']
        mapping_info['host'] = kwargs['host'].strip('\'\"')

        if 'scsi' in kwargs:
            mapping_info['lun'] = kwargs['scsi'].strip('\'\"')
        else:
            mapping_info['lun'] = mapping_info['id']

        if 'obj' not in kwargs:
            return self._errors['CMMVC5707E']
        mapping_info['vol'] = kwargs['obj'].strip('\'\"')

        if mapping_info['vol'] not in self._volumes_list:
            return self._errors['CMMVC5753E']

        if mapping_info['host'] not in self._hosts_list:
            return self._errors['CMMVC5754E']

        if mapping_info['vol'] in self._mappings_list:
            return self._errors['CMMVC6071E']

        for v in self._mappings_list.values():
            if ((v['host'] == mapping_info['host']) and
                    (v['lun'] == mapping_info['lun'])):
                return self._errors['CMMVC5879E']

        for v in self._mappings_list.values():
            if (v['vol'] == mapping_info['vol']) and ('force' not in kwargs):
                return self._errors['CMMVC6071E']

        self._mappings_list[mapping_info['id']] = mapping_info
        return ('Virtual Disk to Host map, id [%s], successfully created'
                % (mapping_info['id']), '')

    # Delete a vdisk-host mapping
    def _cmd_rmvdiskhostmap(self, **kwargs):
        if 'host' not in kwargs:
            return self._errors['CMMVC5707E']
        host = kwargs['host'].strip('\'\"')

        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        vol = kwargs['obj'].strip('\'\"')

        mapping_ids = []
        for v in self._mappings_list.values():
            if v['vol'] == vol:
                mapping_ids.append(v['id'])
        if not mapping_ids:
            return self._errors['CMMVC5753E']

        this_mapping = None
        for mapping_id in mapping_ids:
            if self._mappings_list[mapping_id]['host'] == host:
                this_mapping = mapping_id
        if this_mapping is None:
            return self._errors['CMMVC5753E']

        del self._mappings_list[this_mapping]
        return ('', '')

    # Create a LocalCopy mapping
    def _cmd_mklcmap(self, **kwargs):
        source = ''
        target = ''
        copyrate = kwargs['copyrate'] if 'copyrate' in kwargs else '50'

        if 'source' not in kwargs:
            return self._errors['CMMVC5707E']
        source = kwargs['source'].strip('\'\"')
        if source not in self._volumes_list:
            return self._errors['CMMVC5754E']

        if 'target' not in kwargs:
            return self._errors['CMMVC5707E']
        target = kwargs['target'].strip('\'\"')
        if target not in self._volumes_list:
            return self._errors['CMMVC5754E']

        if source == target:
            return self._errors['CMMVC6303E']

        if (self._volumes_list[source]['capacity'] !=
                self._volumes_list[target]['capacity']):
            return self._errors['CMMVC5754E']

        lcmap_info = {}
        lcmap_info['source'] = source
        lcmap_info['target'] = target
        lcmap_info['id'] = self._find_unused_id(self._lcmappings_list)
        lcmap_info['name'] = 'lcmap' + lcmap_info['id']
        lcmap_info['copyrate'] = copyrate
        lcmap_info['progress'] = '0'
        lcmap_info['autodelete'] = True if 'autodelete' in kwargs else False
        lcmap_info['status'] = 'idle_or_copied'

        # Add lcmap to consistency group
        if 'consistgrp' in kwargs:
            consistgrp = kwargs['consistgrp']

            # if is digit, assume is cg id, else is cg name
            cg_id = 0
            if not consistgrp.isdigit():
                for consistgrp_key in self._lcconsistgrp_list.keys():
                    if (self._lcconsistgrp_list[consistgrp_key]['name'] ==
                            consistgrp):
                        cg_id = consistgrp_key
                        lcmap_info['consistgrp'] = consistgrp_key
                        break
            else:
                if int(consistgrp) in self._lcconsistgrp_list.keys():
                    cg_id = int(consistgrp)

            # If can't find exist consistgrp id, return not exist error
            if not cg_id:
                return self._errors['CMMVC5754E']

            lcmap_info['consistgrp'] = cg_id
            # Add lcmap to consistgrp
            self._lcconsistgrp_list[cg_id]['lcmaps'][lcmap_info['id']] = (
                lcmap_info['name'])
            self._lc_cg_state_transition('add',
                                         self._lcconsistgrp_list[cg_id])

        self._lcmappings_list[lcmap_info['id']] = lcmap_info

        return('LocalCopy Mapping, id [' + lcmap_info['id'] +
               '], successfully created', '')

    def _cmd_prestartlcmap(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        id_num = kwargs['obj']

        if self._next_cmd_error['prestartlcmap'] == 'bad_id':
            id_num = -1
            self._next_cmd_error['prestartlcmap'] = ''

        try:
            lcmap = self._lcmappings_list[id_num]
        except KeyError:
            return self._errors['CMMVC5753E']

        return self._state_transition('prepare', lcmap)

    def _cmd_startlcmap(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        id_num = kwargs['obj']

        if self._next_cmd_error['startlcmap'] == 'bad_id':
            id_num = -1
            self._next_cmd_error['startlcmap'] = ''

        try:
            lcmap = self._lcmappings_list[id_num]
        except KeyError:
            return self._errors['CMMVC5753E']

        return self._state_transition('start', lcmap)

    def _cmd_stoplcmap(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        id_num = kwargs['obj']

        try:
            lcmap = self._lcmappings_list[id_num]
        except KeyError:
            return self._errors['CMMVC5753E']

        return self._state_transition('stop', lcmap)

    def _cmd_rmlcmap(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        id_num = kwargs['obj']
        force = True if 'force' in kwargs else False

        if self._next_cmd_error['rmlcmap'] == 'bad_id':
            id_num = -1
            self._next_cmd_error['rmlcmap'] = ''

        try:
            lcmap = self._lcmappings_list[id_num]
        except KeyError:
            return self._errors['CMMVC5753E']

        function = 'delete_force' if force else 'delete'
        ret = self._state_transition(function, lcmap)
        if lcmap['status'] == 'end':
            del self._lcmappings_list[id_num]
        return ret

    def _cmd_chlcmap(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5707E']
        id_num = kwargs['obj']

        try:
            lcmap = self._lcmappings_list[id_num]
        except KeyError:
            return self._errors['CMMVC5753E']

        for key in ['name', 'copyrate', 'autodelete']:
            if key in kwargs:
                lcmap[key] = kwargs[key]
        return ('', '')

    # Create a LocalCopy mapping
    def _cmd_mklcconsistgrp(self, **kwargs):
        lcconsistgrp_info = {}
        lcconsistgrp_info['id'] = self._find_unused_id(self._lcconsistgrp_list)

        if 'name' in kwargs:
            lcconsistgrp_info['name'] = kwargs['name'].strip('\'\"')
        else:
            lcconsistgrp_info['name'] = 'lccstgrp' + lcconsistgrp_info['id']

        if 'autodelete' in kwargs:
            lcconsistgrp_info['autodelete'] = True
        else:
            lcconsistgrp_info['autodelete'] = False
        lcconsistgrp_info['status'] = 'empty'
        lcconsistgrp_info['start_time'] = None
        lcconsistgrp_info['lcmaps'] = {}

        self._lcconsistgrp_list[lcconsistgrp_info['id']] = lcconsistgrp_info

        return('LocalCopy Consistency Group, id [' + lcconsistgrp_info['id'] +
               '], successfully created', '')

    def _cmd_prestartlcconsistgrp(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        cg_name = kwargs['obj']

        cg_id = 0
        for cg_id in self._lcconsistgrp_list.keys():
            if cg_name == self._lcconsistgrp_list[cg_id]['name']:
                break

        return self._lc_cg_state_transition('prepare',
                                            self._lcconsistgrp_list[cg_id])

    def _cmd_startlcconsistgrp(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        cg_name = kwargs['obj']

        cg_id = 0
        for cg_id in self._lcconsistgrp_list.keys():
            if cg_name == self._lcconsistgrp_list[cg_id]['name']:
                break

        return self._lc_cg_state_transition('start',
                                            self._lcconsistgrp_list[cg_id])

    def _cmd_stoplcconsistgrp(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        id_num = kwargs['obj']

        try:
            lcconsistgrps = self._lcconsistgrp_list[id_num]
        except KeyError:
            return self._errors['CMMVC5753E']

        return self._lc_cg_state_transition('stop', lcconsistgrps)

    def _cmd_rmlcconsistgrp(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        cg_name = kwargs['obj']
        force = True if 'force' in kwargs else False

        cg_id = 0
        for cg_id in self._lcconsistgrp_list.keys():
            if cg_name == self._lcconsistgrp_list[cg_id]['name']:
                break
        if not cg_id:
            return self._errors['CMMVC5753E']
        lcconsistgrps = self._lcconsistgrp_list[cg_id]

        function = 'delete_force' if force else 'delete'
        ret = self._lc_cg_state_transition(function, lcconsistgrps)
        if lcconsistgrps['status'] == 'end':
            del self._lcconsistgrp_list[cg_id]
        return ret

    def _cmd_migratevdisk(self, **kwargs):
        if 'mdiskgrp' not in kwargs or 'vdisk' not in kwargs:
            return self._errors['CMMVC5707E']
        mdiskgrp = kwargs['mdiskgrp'].strip('\'\"')
        vdisk = kwargs['vdisk'].strip('\'\"')

        if vdisk in self._volumes_list:
            curr_mdiskgrp = self._volumes_list
        else:
            for pool in self._other_pools:
                if vdisk in pool:
                    curr_mdiskgrp = pool
                    break
            else:
                return self._errors['CMMVC5754E']

        if mdiskgrp == self._flags['instorage_mcs_volpool_name']:
            tgt_mdiskgrp = self._volumes_list
        elif mdiskgrp == 'openstack2':
            tgt_mdiskgrp = self._other_pools['openstack2']
        elif mdiskgrp == 'openstack3':
            tgt_mdiskgrp = self._other_pools['openstack3']
        else:
            return self._errors['CMMVC5754E']

        if curr_mdiskgrp == tgt_mdiskgrp:
            return self._errors['CMMVC6430E']

        vol = curr_mdiskgrp[vdisk]
        tgt_mdiskgrp[vdisk] = vol
        del curr_mdiskgrp[vdisk]
        return ('', '')

    def _cmd_addvdiskcopy(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        vol_name = kwargs['obj'].strip('\'\"')
        if vol_name not in self._volumes_list:
            return self._errors['CMMVC5753E']
        vol = self._volumes_list[vol_name]
        if 'mdiskgrp' not in kwargs:
            return self._errors['CMMVC5707E']
        mdiskgrp = kwargs['mdiskgrp'].strip('\'\"')
        if mdiskgrp == kwargs['mdiskgrp']:
            raise exception.InvalidInput(
                reason='mdiskgrp missing quotes %s') % kwargs['mdiskgrp']

        copy_info = {}
        copy_info['id'] = self._find_unused_id(vol['copies'])
        copy_info['status'] = 'online'
        copy_info['sync'] = 'no'
        copy_info['primary'] = 'no'
        copy_info['mdisk_grp_name'] = mdiskgrp
        copy_info['mdisk_grp_id'] = str(self._get_mdiskgrp_id(mdiskgrp))

        if 'intier' in kwargs:
            if kwargs['intier'] == 'on':
                copy_info['in_tier'] = 'on'
            else:
                copy_info['in_tier'] = 'off'
        if 'rsize' in kwargs:
            if 'compressed' in kwargs:
                copy_info['compressed_copy'] = 'yes'
            else:
                copy_info['compressed_copy'] = 'no'
        vol['copies'][copy_info['id']] = copy_info
        return ('Vdisk [%(vid)s] copy [%(cid)s] successfully created' %
                {'vid': vol['id'], 'cid': copy_info['id']}, '')

    def _cmd_rmvdiskcopy(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        vol_name = kwargs['obj'].strip('\'\"')
        if 'copy' not in kwargs:
            return self._errors['CMMVC5707E']
        copy_id = kwargs['copy'].strip('\'\"')
        if vol_name not in self._volumes_list:
            return self._errors['CMMVC5753E']
        vol = self._volumes_list[vol_name]
        if copy_id not in vol['copies']:
            return self._errors['CMMVC6353E']
        del vol['copies'][copy_id]

        return ('', '')

    def _cmd_chvdisk(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        vol_name = kwargs['obj'].strip('\'\"')
        vol = self._volumes_list[vol_name]
        kwargs.pop('obj')

        params = ['name', 'warning', 'udid',
                  'autoexpand', 'intier', 'primary']
        for key, value in kwargs.items():
            if key == 'intier':
                vol['in_tier'] = value
                continue
            if key == 'warning':
                vol['warning'] = value.rstrip('%')
                continue
            if key == 'name':
                vol['name'] = value
                del self._volumes_list[vol_name]
                self._volumes_list[value] = vol
            if key == 'primary':
                copies = self._volumes_list[vol_name]['copies']
                if value == '0':
                    copies['0']['primary'] = 'yes'
                    copies['1']['primary'] = 'no'
                elif value == '1':
                    copies['0']['primary'] = 'no'
                    copies['1']['primary'] = 'yes'
                else:
                    err = self._errors['CMMVC6353E'][1] % {'VALUE': key}
                    return ('', err)
            if key in params:
                vol[key] = value
            else:
                err = self._errors['CMMVC5709E'][1] % {'VALUE': key}
                return ('', err)
        return ('', '')

    def _cmd_movevdisk(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        vol_name = kwargs['obj'].strip('\'\"')
        vol = self._volumes_list[vol_name]

        if 'iogrp' not in kwargs:
            return self._errors['CMMVC5707E']

        iogrp = kwargs['iogrp']
        if iogrp.isdigit():
            vol['IO_group_id'] = iogrp
            vol['IO_group_name'] = 'io_grp%s' % iogrp
        else:
            vol['IO_group_id'] = iogrp[6:]
            vol['IO_group_name'] = iogrp
        return ('', '')

    def _cmd_addvdiskaccess(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        return ('', '')

    def _cmd_rmvdiskaccess(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        return ('', '')

    def _add_host_to_list(self, connector):
        host_info = {}
        host_info['id'] = self._find_unused_id(self._hosts_list)
        host_info['host_name'] = connector['host']
        host_info['iscsi_names'] = []
        host_info['wwpns'] = []
        if 'initiator' in connector:
            host_info['iscsi_names'].append(connector['initiator'])
        if 'wwpns' in connector:
            host_info['wwpns'] = host_info['wwpns'] + connector['wwpns']
        self._hosts_list[connector['host']] = host_info

    def _host_in_list(self, host_name):
        for k in self._hosts_list:
            if k.startswith(host_name):
                return k
        return None

    # Replication related command
    # Create a remote copy
    def _cmd_mkrcrelationship(self, **kwargs):
        master_vol = ''
        aux_vol = ''
        aux_cluster = ''
        master_sys = self._system_list['instorage-mcs-sim']
        aux_sys = self._system_list['aux-mcs-sim']

        if 'master' not in kwargs:
            return self._errors['CMMVC5707E']
        master_vol = kwargs['master'].strip('\'\"')
        if master_vol not in self._volumes_list:
            return self._errors['CMMVC5754E']

        if 'aux' not in kwargs:
            return self._errors['CMMVC5707E']
        aux_vol = kwargs['aux'].strip('\'\"')
        if aux_vol not in self._volumes_list:
            return self._errors['CMMVC5754E']

        if 'cluster' not in kwargs:
            return self._errors['CMMVC5707E']
        aux_cluster = kwargs['cluster'].strip('\'\"')
        if aux_cluster != aux_sys['name']:
            return self._errors['CMMVC5754E']

        if (self._volumes_list[master_vol]['capacity'] !=
                self._volumes_list[aux_vol]['capacity']):
            return self._errors['CMMVC5754E']
        rcrel_info = {}
        rcrel_info['id'] = self._find_unused_id(self._rcrelationship_list)
        rcrel_info['name'] = 'rcrel' + rcrel_info['id']
        rcrel_info['master_cluster_id'] = master_sys['id']
        rcrel_info['master_cluster_name'] = master_sys['name']
        rcrel_info['master_vdisk_id'] = self._volumes_list[master_vol]['id']
        rcrel_info['master_vdisk_name'] = master_vol
        rcrel_info['aux_cluster_id'] = aux_sys['id']
        rcrel_info['aux_cluster_name'] = aux_sys['name']
        rcrel_info['aux_vdisk_id'] = self._volumes_list[aux_vol]['id']
        rcrel_info['aux_vdisk_name'] = aux_vol
        rcrel_info['primary'] = 'master'
        rcrel_info['consistency_group_id'] = ''
        rcrel_info['consistency_group_name'] = ''
        rcrel_info['state'] = 'inconsistent_stopped'
        rcrel_info['bg_copy_priority'] = '50'
        rcrel_info['progress'] = '0'
        rcrel_info['freeze_time'] = ''
        rcrel_info['status'] = 'online'
        rcrel_info['sync'] = ''
        rcrel_info['copy_type'] = 'async' if 'async' in kwargs else 'sync'
        rcrel_info['cycling_mode'] = ''
        rcrel_info['cycle_period_seconds'] = '300'
        rcrel_info['master_change_vdisk_id'] = ''
        rcrel_info['master_change_vdisk_name'] = ''
        rcrel_info['aux_change_vdisk_id'] = ''
        rcrel_info['aux_change_vdisk_name'] = ''

        self._rcrelationship_list[rcrel_info['name']] = rcrel_info
        self._volumes_list[master_vol]['RC_name'] = rcrel_info['name']
        self._volumes_list[master_vol]['RC_id'] = rcrel_info['id']
        self._volumes_list[aux_vol]['RC_name'] = rcrel_info['name']
        self._volumes_list[aux_vol]['RC_id'] = rcrel_info['id']
        return('RC Relationship, id [' + rcrel_info['id'] +
               '], successfully created', '')

    def _cmd_startrcrelationship(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        id_num = kwargs['obj']

        primary_vol = None
        if 'primary' in kwargs:
            primary_vol = kwargs['primary'].strip('\'\"')

        try:
            rcrel = self._rcrelationship_list[id_num]
        except KeyError:
            return self._errors['CMMVC5753E']

        if rcrel['state'] == 'idling' and not primary_vol:
            return self._errors['CMMVC5963E']

        self._rc_state_transition('start', rcrel)
        if primary_vol:
            self._rcrelationship_list[id_num]['primary'] = primary_vol
        return ('', '')

    def _cmd_stoprcrelationship(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        id_num = kwargs['obj']
        force_access = True if 'access' in kwargs else False

        try:
            rcrel = self._rcrelationship_list[id_num]
        except KeyError:
            return self._errors['CMMVC5753E']

        function = 'stop_access' if force_access else 'stop'
        self._rc_state_transition(function, rcrel)
        if force_access:
            self._rcrelationship_list[id_num]['primary'] = ''
        return ('', '')

    def _cmd_switchrcrelationship(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5707E']
        id_num = kwargs['obj']

        try:
            rcrel = self._rcrelationship_list[id_num]
        except KeyError:
            return self._errors['CMMVC5753E']

        if rcrel['state'] == instorage_const.REP_CONSIS_SYNC:
            rcrel['primary'] = kwargs['primary']
            return ('', '')
        else:
            return self._errors['CMMVC5753E']

    def _cmd_rmrcrelationship(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        id_num = kwargs['obj']
        force = True if 'force' in kwargs else False

        try:
            rcrel = self._rcrelationship_list[id_num]
        except KeyError:
            return self._errors['CMMVC5753E']

        function = 'delete_force' if force else 'delete'
        self._rc_state_transition(function, rcrel)
        if rcrel['state'] == 'end':
            self._volumes_list[rcrel['master_vdisk_name']]['RC_name'] = ''
            self._volumes_list[rcrel['master_vdisk_name']]['RC_id'] = ''
            self._volumes_list[rcrel['aux_vdisk_name']]['RC_name'] = ''
            self._volumes_list[rcrel['aux_vdisk_name']]['RC_id'] = ''
            del self._rcrelationship_list[id_num]

        return ('', '')

    def _rc_state_transition(self, function, rcrel):
        if (function == 'wait' and
                'wait' not in self._rc_transitions[rcrel['state']]):
            return ('', '')

        if rcrel['state'] == 'inconsistent_copying' and function == 'wait':
            if rcrel['progress'] == '0':
                rcrel['progress'] = '50'
            else:
                rcrel['progress'] = '100'
                rcrel['state'] = 'consistent_synchronized'
            return ('', '')
        else:
            try:
                curr_state = rcrel['state']
                rcrel['state'] = self._rc_transitions[curr_state][function]
                return ('', '')
            except Exception:
                return self._errors['CMMVC5982E']

    def _cmd_mkippartnership(self, **kwargs):
        if 'clusterip' not in kwargs:
            return self._errors['CMMVC5707E']
        clusterip = kwargs['master'].strip('\'\"')

        if 'linkbandwidthmbits' not in kwargs:
            return self._errors['CMMVC5707E']
        bandwidth = kwargs['linkbandwidthmbits'].strip('\'\"')

        if 'backgroundcopyrate' not in kwargs:
            return self._errors['CMMVC5707E']
        copyrate = kwargs['backgroundcopyrate'].strip('\'\"')

        if clusterip == '192.168.10.21':
            partner_info_id = self._system_list['instorage-mcs-sim']['id']
            partner_info_name = self._system_list['instorage-mcs-sim']['name']
        else:
            partner_info_id = self._system_list['aux-mcs-sim']['id']
            partner_info_name = self._system_list['aux-mcs-sim']['name']

        partner_info = {}
        partner_info['id'] = partner_info_id
        partner_info['name'] = partner_info_name
        partner_info['location'] = 'remote'
        partner_info['type'] = 'ipv4'
        partner_info['cluster_ip'] = clusterip
        partner_info['event_log_sequence'] = ''
        partner_info['chap_secret'] = ''
        partner_info['linkbandwidthmbits'] = bandwidth
        partner_info['backgroundcopyrate'] = copyrate
        partner_info['partnership'] = 'fully_configured'

        self._partnership_list[partner_info['id']] = partner_info
        return('', '')

    def _cmd_mkfcpartnership(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        peer_sys = kwargs['obj']

        if 'linkbandwidthmbits' not in kwargs:
            return self._errors['CMMVC5707E']
        bandwidth = kwargs['linkbandwidthmbits'].strip('\'\"')

        if 'backgroundcopyrate' not in kwargs:
            return self._errors['CMMVC5707E']
        copyrate = kwargs['backgroundcopyrate'].strip('\'\"')

        partner_info = {}
        partner_info['id'] = self._system_list[peer_sys]['id']
        partner_info['name'] = peer_sys
        partner_info['location'] = 'remote'
        partner_info['type'] = 'fc'
        partner_info['cluster_ip'] = ''
        partner_info['event_log_sequence'] = ''
        partner_info['chap_secret'] = ''
        partner_info['linkbandwidthmbits'] = bandwidth
        partner_info['backgroundcopyrate'] = copyrate
        partner_info['partnership'] = 'fully_configured'
        self._partnership_list[partner_info['id']] = partner_info
        return('', '')

    def _cmd_chpartnership(self, **kwargs):
        if 'obj' not in kwargs:
            return self._errors['CMMVC5701E']
        peer_sys = kwargs['obj']
        if peer_sys not in self._partnership_list:
            return self._errors['CMMVC5753E']

        partner_state = ('fully_configured' if 'start' in kwargs
                         else 'fully_configured_stopped')
        self._partnership_list[peer_sys]['partnership'] = partner_state
        return('', '')

    # The main function to run commands on the management simulator
    def execute_command(self, cmd, check_exit_code=True):
        try:
            kwargs = self._cmd_to_dict(cmd)
        except IndexError:
            return self._errors['CMMVC5707E']

        command = kwargs.pop('cmd')
        func = getattr(self, '_cmd_' + command)
        out, err = func(**kwargs)

        if (check_exit_code) and (len(err) != 0):
            raise processutils.ProcessExecutionError(exit_code=1,
                                                     stdout=out,
                                                     stderr=err,
                                                     cmd=' '.join(cmd))

        return (out, err)

    # After calling this function, the next call to the specified command will
    # result in in the error specified
    def error_injection(self, cmd, error):
        self._next_cmd_error[cmd] = error

    def change_vdiskcopy_attr(self, vol_name, key, value, copy="primary"):
        if copy == 'primary':
            self._volumes_list[vol_name]['copies']['0'][key] = value
        elif copy == 'secondary':
            self._volumes_list[vol_name]['copies']['1'][key] = value
        else:
            msg = "The copy should be primary or secondary"
            raise exception.InvalidInput(reason=msg)
