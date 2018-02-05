# Copyright 2014 IBM Corp.
# Copyright 2012 OpenStack Foundation
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

"""Tests for the IBM FlashSystem volume driver."""

import mock
from oslo_concurrency import processutils
from oslo_utils import units
import six

import random
import re

from cinder import context
from cinder import exception
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.ibm import flashsystem_fc
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types


class FlashSystemManagementSimulator(object):
    def __init__(self):
        # Default protocol is FC
        self._protocol = 'FC'
        self._volumes_list = {}
        self._hosts_list = {}
        self._mappings_list = {}
        self._next_cmd_error = {
            'lsnode': '',
            'lssystem': '',
            'lsmdiskgrp': ''
        }
        self._errors = {
            # CMMVC50000 is a fake error which indicates that command has not
            # got expected results. This error represents kinds of CLI errors.
            'CMMVC50000': ('', 'CMMVC50000 The command can not be executed '
                               'successfully.'),
            'CMMVC6045E': ('', 'CMMVC6045E The action failed, as the '
                               '-force flag was not entered.'),
            'CMMVC6071E': ('', 'CMMVC6071E The VDisk-to-host mapping '
                               'was not created because the VDisk is '
                               'already mapped to a host.')
        }
        self._multi_host_map_error = None
        self._multi_host_map_errors = ['CMMVC6045E', 'CMMVC6071E']

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

    @staticmethod
    def _is_invalid_name(name):
        if re.match(r'^[a-zA-Z_][\w ._-]*$', name):
            return False
        return True

    @staticmethod
    def _cmd_to_dict(arg_list):
        no_param_args = [
            'bytes',
            'force'
        ]
        one_param_args = [
            'delim',
            'hbawwpn',
            'host',
            'iogrp',
            'iscsiname',
            'mdiskgrp',
            'name',
            'scsi',
            'size',
            'unit'
        ]

        # All commands should begin with svcinfo or svctask
        if arg_list[0] not in ('svcinfo', 'svctask') or len(arg_list) < 2:
            raise exception.InvalidInput(reason=six.text_type(arg_list))
        ret = {'cmd': arg_list[1]}

        skip = False
        for i in range(2, len(arg_list)):
            if skip:
                skip = False
                continue
            if arg_list[i][0] == '-':
                param = arg_list[i][1:]
                if param in no_param_args:
                    ret[param] = True
                elif param in one_param_args:
                    ret[param] = arg_list[i + 1]
                    skip = True
                else:
                    raise exception.InvalidInput(
                        reason=('unrecognized argument %s') % arg_list[i])
            else:
                ret['obj'] = arg_list[i]
        return ret

    @staticmethod
    def _print_cmd_info(rows, delim=' ', nohdr=False, **kwargs):
        """Generic function for printing information."""
        if nohdr:
            del rows[0]
        for index in range(len(rows)):
            rows[index] = delim.join(rows[index])
        return ('%s' % '\n'.join(rows), '')

    @staticmethod
    def _convert_units_bytes(num, unit):
        unit_array = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        unit_index = 0

        while unit.lower() != unit_array[unit_index].lower():
            num = num * 1024
            unit_index += 1

        return six.text_type(num)

    def _cmd_lshost(self, **kwargs):
        """lshost command.

        svcinfo lshost -delim !
        svcinfo lshost -delim ! <host>
        """
        if 'obj' not in kwargs:
            rows = []
            rows.append(['id', 'name', 'port_count', 'iogrp_count', 'status'])
            for host in self._hosts_list.values():
                rows.append([host['id'], host['host_name'], '1', '1',
                            'degraded'])
            if len(rows) > 1:
                return self._print_cmd_info(rows=rows, **kwargs)
            else:
                return ('', '')
        else:
            host_name = kwargs['obj'].strip('\'\"')
            if host_name not in self._hosts_list:
                return self._errors['CMMVC50000']
            host = self._hosts_list[host_name]
            rows = []
            rows.append(['id', host['id']])
            rows.append(['name', host['host_name']])
            rows.append(['port_count', '1'])
            rows.append(['type', 'generic'])
            rows.append(['mask', '1111'])
            rows.append(['iogrp_count', '1'])
            rows.append(['status', 'degraded'])
            for port in host['iscsi_names']:
                rows.append(['iscsi_name', port])
                rows.append(['node_logged_in_count', '0'])
                rows.append(['state', 'offline'])
            for port in host['wwpns']:
                rows.append(['WWPN', port])
                rows.append(['node_logged_in_count', '0'])
                rows.append(['state', 'active'])

            if 'delim' in kwargs:
                for index in range(len(rows)):
                    rows[index] = kwargs['delim'].join(rows[index])

            return ('%s' % '\n'.join(rows), '')

    def _cmd_lshostvdiskmap(self, **kwargs):
        """svcinfo lshostvdiskmap -delim ! <host_name>"""

        if 'obj' not in kwargs:
            return self._errors['CMMVC50000']

        host_name = kwargs['obj'].strip('\'\"')
        if host_name not in self._hosts_list:
            return self._errors['CMMVC50000']

        rows = []
        rows.append(['id', 'name', 'SCSI_id', 'vdisk_id', 'vdisk_name',
                     'vdisk_UID'])

        for mapping in self._mappings_list.values():
            if (host_name == '') or (mapping['host'] == host_name):
                volume = self._volumes_list[mapping['vol']]
                rows.append([mapping['id'], mapping['host'],
                            mapping['lun'], volume['id'],
                            volume['name'], volume['vdisk_UID']])

        return self._print_cmd_info(rows=rows, **kwargs)

    def _cmd_lsmdiskgrp(self, **kwargs):
        """svcinfo lsmdiskgrp -gui -bytes -delim ! <pool>"""

        status = 'online'
        if self._next_cmd_error['lsmdiskgrp'] == 'error':
            self._next_cmd_error['lsmdiskgrp'] = ''
            return self._errors['CMMVC50000']

        if self._next_cmd_error['lsmdiskgrp'] == 'status=offline':
            self._next_cmd_error['lsmdiskgrp'] = ''
            status = 'offline'

        rows = [None] * 2
        rows[0] = ['id', 'status', 'mdisk_count', 'vdisk_count', 'capacity',
                   'free_capacity', 'virtual_capacity', 'used_capacity',
                   'real_capacity', 'encrypted', 'type', 'encrypt']
        rows[1] = ['0', status, '1', '0', '3573412790272',
                   '3529432325160', '1693247906775', '277841182',
                   '38203734097', 'no', 'parent', 'no']

        if kwargs['obj'] == 'mdiskgrp0':
            row = rows[1]
        else:
            return self._errors['CMMVC50000']

        objrows = []
        for idx, val in enumerate(rows[0]):
            objrows.append([val, row[idx]])

        if 'delim' in kwargs:
            for index in range(len(objrows)):
                objrows[index] = kwargs['delim'].join(objrows[index])

        return ('%s' % '\n'.join(objrows), '')

    def _cmd_lsnode(self, **kwargs):
        """lsnode command.

        svcinfo lsnode -delim !
        svcinfo lsnode -delim ! <node>
        """

        if self._protocol == 'FC' or self._protocol == 'both':
            port_status = 'active'
        else:
            port_status = 'unconfigured'

        rows1 = [None] * 7
        rows1[0] = ['name', 'node1']
        rows1[1] = ['port_id', '000000000000001']
        rows1[2] = ['port_status', port_status]
        rows1[3] = ['port_speed', '8Gb']
        rows1[4] = ['port_id', '000000000000001']
        rows1[5] = ['port_status', port_status]
        rows1[6] = ['port_speed', '8Gb']

        rows2 = [None] * 7
        rows2[0] = ['name', 'node2']
        rows2[1] = ['port_id', '000000000000002']
        rows2[2] = ['port_status', port_status]
        rows2[3] = ['port_speed', '8Gb']
        rows2[4] = ['port_id', '000000000000002']
        rows2[5] = ['port_status', port_status]
        rows2[6] = ['port_speed', 'N/A']

        rows3 = [None] * 3
        rows3[0] = ['id', 'name', 'UPS_serial_number', 'WWNN', 'status',
                    'IO_group_id', 'IO_group_name', 'config_node',
                    'UPS_unique_id', 'hardware', 'iscsi_name', 'iscsi_alias',
                    'panel_name', 'enclosure_id', 'canister_id',
                    'enclosure_serial_number']
        rows3[1] = ['1', 'node1', '', '0123456789ABCDEF', 'online', '0',
                    'io_grp0', 'yes', '', 'TR1', 'naa.0123456789ABCDEF', '',
                    '01-1', '1', '1', 'H441028']
        rows3[2] = ['2', 'node2', '', '0123456789ABCDEF', 'online', '0',
                    'io_grp0', 'no', '', 'TR1', 'naa.0123456789ABCDEF', '',
                    '01-2', '1', '2', 'H441028']

        if self._next_cmd_error['lsnode'] == 'error':
            self._next_cmd_error['lsnode'] = ''
            return self._errors['CMMVC50000']

        rows = None
        if 'obj' not in kwargs:
            rows = rows3
        elif kwargs['obj'] == '1':
            rows = rows1
        elif kwargs['obj'] == '2':
            rows = rows2
        else:
            return self._errors['CMMVC50000']

        if self._next_cmd_error['lsnode'] == 'header_mismatch':
            rows[0].pop(2)
            self._next_cmd_error['lsnode'] = ''

        return self._print_cmd_info(rows=rows, delim=kwargs.get('delim', None))

    def _cmd_lssystem(self, **kwargs):
        """svcinfo lssystem -delim !"""

        open_access_enabled = 'off'

        if self._next_cmd_error['lssystem'] == 'error':
            self._next_cmd_error['lssystem'] = ''
            return self._errors['CMMVC50000']

        if self._next_cmd_error['lssystem'] == 'open_access_enabled=on':
            self._next_cmd_error['lssystem'] = ''
            open_access_enabled = 'on'

        rows = [None] * 3
        rows[0] = ['id', '0123456789ABCDEF']
        rows[1] = ['name', 'flashsystem_1.2.3.4']
        rows[2] = ['open_access_enabled', open_access_enabled]

        return self._print_cmd_info(rows=rows, **kwargs)

    def _cmd_lsportfc(self, **kwargs):
        """svcinfo lsportfc"""

        if self._protocol == 'FC' or self._protocol == 'both':
            status = 'active'
        else:
            status = 'unconfigured'

        rows = [None] * 3
        rows[0] = ['id', 'canister_id', 'adapter_id', 'port_id', 'type',
                   'port_speed', 'node_id', 'node_name', 'WWPN',
                   'nportid', 'status', 'attachment', 'topology']
        rows[1] = ['0', '1', '1', '1', 'fc',
                   '8Gb', '1', 'node_1', 'AABBCCDDEEFF0011',
                   '000000', status, 'host', 'al']
        rows[2] = ['1', '1', '1', '1', 'fc',
                   '8Gb', '1', 'node_1', 'AABBCCDDEEFF0010',
                   '000000', status, 'host', 'al']
        return self._print_cmd_info(rows=rows, **kwargs)

    def _cmd_lsportip(self, **kwargs):
        """svcinfo lsportip"""

        if self._protocol == 'iSCSI' or self._protocol == 'both':
            IP_address1 = '192.168.1.10'
            IP_address2 = '192.168.1.11'
            state = 'online'
            speed = '8G'
        else:
            IP_address1 = ''
            IP_address2 = ''
            state = ''
            speed = ''

        rows = [None] * 3
        rows[0] = ['id', 'node_id', 'node_name', 'canister_id', 'adapter_id',
                   'port_id', 'IP_address', 'mask', 'gateway', 'IP_address_6',
                   'prefix_6', 'gateway_6', 'MAC', 'duplex', 'state', 'speed',
                   'failover', 'link_state', 'host', 'host_6', 'vlan',
                   'vlan_6', 'adapter_location', 'adapter_port_id']
        rows[1] = ['1', '1', 'node1', '0', '0',
                   '0', IP_address1, '', '', '',
                   '0', '', '11:22:33:44:55:AA', '', state, speed,
                   'no', 'active', '', '', '', '', '0', '0']
        rows[2] = ['2', '2', 'node2', '0', '0',
                   '0', IP_address2, '', '', '',
                   '0', '', '11:22:33:44:55:BB', '', state, speed,
                   'no', 'active', '', '', '', '', '0', '0']

        return self._print_cmd_info(rows=rows, **kwargs)

    def _cmd_lsvdisk(self, **kwargs):
        """cmd: svcinfo lsvdisk -gui -bytes -delim ! <vdisk_name>"""

        if 'obj' not in kwargs or (
                'delim' not in kwargs) or (
                'bytes' not in kwargs):
            return self._errors['CMMVC50000']

        if kwargs['obj'] not in self._volumes_list:
            return self._errors['CMMVC50000']

        vol = self._volumes_list[kwargs['obj']]

        rows = []
        rows.append(['id', vol['id']])
        rows.append(['name', vol['name']])
        rows.append(['status', vol['status']])
        rows.append(['capacity', vol['capacity']])
        rows.append(['vdisk_UID', vol['vdisk_UID']])
        rows.append(['udid', ''])
        rows.append(['open_access_scsi_id', '1'])
        rows.append(['parent_mdisk_grp_id', '0'])
        rows.append(['parent_mdisk_grp_name', 'mdiskgrp0'])

        for index in range(len(rows)):
            rows[index] = kwargs['delim'].join(rows[index])
        return ('%s' % '\n'.join(rows), '')

    def _cmd_lsvdiskhostmap(self, **kwargs):
        """svcinfo lsvdiskhostmap -delim ! <vdisk_name>"""

        if 'obj' not in kwargs or (
                'delim' not in kwargs):
            return self._errors['CMMVC50000']

        vdisk_name = kwargs['obj']
        if vdisk_name not in self._volumes_list:
            return self._errors['CMMVC50000']

        rows = []
        rows.append(['id', 'name', 'SCSI_id', 'host_id', 'host_name',
                     'vdisk_UID', 'IO_group_id', 'IO_group_name'])

        mappings_found = 0
        for mapping in self._mappings_list.values():
            if (mapping['vol'] == vdisk_name):
                mappings_found += 1
                volume = self._volumes_list[mapping['vol']]
                host = self._hosts_list[mapping['host']]
                rows.append([volume['id'], volume['name'], '1', host['id'],
                            host['host_name'], volume['vdisk_UID'],
                            '0', 'mdiskgrp0'])

        if mappings_found:
            return self._print_cmd_info(rows=rows, **kwargs)
        else:
            return ('', '')

    def _cmd_expandvdisksize(self, **kwargs):
        """svctask expandvdisksize -size <size> -unit gb <vdisk_name>"""

        if 'obj' not in kwargs:
            return self._errors['CMMVC50000']
        vol_name = kwargs['obj'].strip('\'\"')

        if 'size' not in kwargs:
            return self._errors['CMMVC50000']
        size = int(kwargs['size'])

        if vol_name not in self._volumes_list:
            return self._errors['CMMVC50000']

        curr_size = int(self._volumes_list[vol_name]['capacity'])
        addition = size * units.Gi
        self._volumes_list[vol_name]['capacity'] = six.text_type(
            curr_size + addition)
        return ('', '')

    def _cmd_mkvdisk(self, **kwargs):
        """mkvdisk command.

        svctask mkvdisk -name <name> -mdiskgrp <mdiskgrp> -iogrp <iogrp>
        -size <size> -unit <unit>
        """

        if 'name' not in kwargs or (
                'size' not in kwargs) or (
                'unit' not in kwargs):
            return self._errors['CMMVC50000']

        vdisk_info = {}
        vdisk_info['id'] = self._find_unused_id(self._volumes_list)
        vdisk_info['name'] = kwargs['name'].strip('\'\"')
        vdisk_info['status'] = 'online'
        vdisk_info['capacity'] = self._convert_units_bytes(
            int(kwargs['size']), kwargs['unit'])
        vdisk_info['vdisk_UID'] = ('60050760') + ('0' * 14) + vdisk_info['id']

        if vdisk_info['name'] in self._volumes_list:
            return self._errors['CMMVC50000']
        else:
            self._volumes_list[vdisk_info['name']] = vdisk_info
            return ('Virtual Disk, id [%s], successfully created' %
                    (vdisk_info['id']), '')

    def _cmd_chvdisk(self, **kwargs):
        """chvdisk command

        svcask chvdisk -name <new_name_arg> -udid <vdisk_udid>
        -open_access_scsi_id <vdisk_scsi_id> <vdisk_name> <vdisk_id>
        """

        if 'obj' not in kwargs:
            return self._errors['CMMVC50000']

        source_name = kwargs['obj'].strip('\'\"')
        dest_name = kwargs['name'].strip('\'\"')
        vol = self._volumes_list[source_name]
        vol['name'] = dest_name
        del self._volumes_list[source_name]
        self._volumes_list[dest_name] = vol
        return ('', '')

    def _cmd_rmvdisk(self, **kwargs):
        """svctask rmvdisk -force <vdisk_name>"""

        if 'obj' not in kwargs:
            return self._errors['CMMVC50000']

        vdisk_name = kwargs['obj'].strip('\'\"')

        if vdisk_name not in self._volumes_list:
            return self._errors['CMMVC50000']

        del self._volumes_list[vdisk_name]
        return ('', '')

    def _add_port_to_host(self, host_info, **kwargs):
        if 'iscsiname' in kwargs:
            added_key = 'iscsi_names'
            added_val = kwargs['iscsiname'].strip('\'\"')
        elif 'hbawwpn' in kwargs:
            added_key = 'wwpns'
            added_val = kwargs['hbawwpn'].strip('\'\"')
        else:
            return self._errors['CMMVC50000']

        host_info[added_key].append(added_val)

        for v in self._hosts_list.values():
            if v['id'] == host_info['id']:
                continue
            for port in v[added_key]:
                if port == added_val:
                    return self._errors['CMMVC50000']
        return ('', '')

    def _cmd_mkhost(self, **kwargs):
        """mkhost command.

        svctask mkhost -force -hbawwpn <wwpn> -name <host_name>
        svctask mkhost -force -iscsiname <initiator> -name <host_name>
        """

        if 'name' not in kwargs:
            return self._errors['CMMVC50000']

        host_name = kwargs['name'].strip('\'\"')
        if self._is_invalid_name(host_name):
            return self._errors['CMMVC50000']
        if host_name in self._hosts_list:
            return self._errors['CMMVC50000']

        host_info = {}
        host_info['id'] = self._find_unused_id(self._hosts_list)
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

    def _cmd_addhostport(self, **kwargs):
        """addhostport command.

        svctask addhostport -force -hbawwpn <wwpn> <host>
        svctask addhostport -force -iscsiname <initiator> <host>
        """

        if 'obj' not in kwargs:
            return self._errors['CMMVC50000']
        host_name = kwargs['obj'].strip('\'\"')

        if host_name not in self._hosts_list:
            return self._errors['CMMVC50000']

        host_info = self._hosts_list[host_name]
        return self._add_port_to_host(host_info, **kwargs)

    def _cmd_rmhost(self, **kwargs):
        """svctask rmhost <host>"""

        if 'obj' not in kwargs:
            return self._errors['CMMVC50000']

        host_name = kwargs['obj'].strip('\'\"')
        if host_name not in self._hosts_list:
            return self._errors['CMMVC50000']

        for v in self._mappings_list.values():
            if (v['host'] == host_name):
                return self._errors['CMMVC50000']

        del self._hosts_list[host_name]
        return ('', '')

    def _cmd_mkvdiskhostmap(self, **kwargs):
        """svctask mkvdiskhostmap -host <host> -scsi <lun> <vdisk_name>"""

        mapping_info = {}
        mapping_info['id'] = self._find_unused_id(self._mappings_list)

        if 'host' not in kwargs or (
                'scsi' not in kwargs) or (
                'obj' not in kwargs):
            return self._errors['CMMVC50000']
        mapping_info['host'] = kwargs['host'].strip('\'\"')
        mapping_info['lun'] = kwargs['scsi'].strip('\'\"')
        mapping_info['vol'] = kwargs['obj'].strip('\'\"')

        if mapping_info['vol'] not in self._volumes_list:
            return self._errors['CMMVC50000']

        if mapping_info['host'] not in self._hosts_list:
            return self._errors['CMMVC50000']

        for v in self._mappings_list.values():
            if (v['vol'] == mapping_info['vol']) and ('force' not in kwargs):
                return self._errors[self._multi_host_map_error or 'CMMVC50000']

            if ((v['host'] == mapping_info['host']) and
                    (v['lun'] == mapping_info['lun'])):
                return self._errors['CMMVC50000']

            if (v['lun'] == mapping_info['lun']) and ('force' not in kwargs):
                return self._errors['CMMVC50000']

        self._mappings_list[mapping_info['id']] = mapping_info
        return ('Virtual Disk to Host map, id [%s], successfully created'
                % (mapping_info['id']), '')

    def _cmd_rmvdiskhostmap(self, **kwargs):
        """svctask rmvdiskhostmap -host <host> <vdisk_name>"""

        if 'host' not in kwargs or 'obj' not in kwargs:
            return self._errors['CMMVC50000']
        host = kwargs['host'].strip('\'\"')
        vdisk = kwargs['obj'].strip('\'\"')

        mapping_ids = []
        for v in self._mappings_list.values():
            if v['vol'] == vdisk:
                mapping_ids.append(v['id'])
        if not mapping_ids:
            return self._errors['CMMVC50000']

        this_mapping = None
        for mapping_id in mapping_ids:
            if self._mappings_list[mapping_id]['host'] == host:
                this_mapping = mapping_id
        if this_mapping is None:
            return self._errors['CMMVC50000']

        del self._mappings_list[this_mapping]
        return ('', '')

    def set_protocol(self, protocol):
        self._protocol = protocol

    def execute_command(self, cmd, check_exit_code=True):
        try:
            kwargs = self._cmd_to_dict(cmd)
        except exception.InvalidInput:
            return self._errors['CMMVC50000']

        command = kwargs.pop('cmd')
        func = getattr(self, '_cmd_' + command)
        out, err = func(**kwargs)

        if (check_exit_code) and (len(err) != 0):
            raise processutils.ProcessExecutionError(exit_code=1,
                                                     stdout=out,
                                                     stderr=err,
                                                     cmd=command)
        return (out, err)

    def error_injection(self, cmd, error):
        self._next_cmd_error[cmd] = error


class FlashSystemFakeDriver(flashsystem_fc.FlashSystemFCDriver):
    def __init__(self, *args, **kwargs):
        super(FlashSystemFakeDriver, self).__init__(*args, **kwargs)

    def set_fake_storage(self, fake):
        self.fake_storage = fake

    def _ssh(self, cmd, check_exit_code=True):
        utils.check_ssh_injection(cmd)
        ret = self.fake_storage.execute_command(cmd, check_exit_code)
        return ret


class FlashSystemDriverTestCase(test.TestCase):

    def _set_flag(self, flag, value):
        group = self.driver.configuration.config_group
        self.driver.configuration.set_override(flag, value, group)

    def _reset_flags(self):
        self.driver.configuration.local_conf.reset()
        for k, v in self._def_flags.items():
            self._set_flag(k, v)

    def _generate_vol_info(self,
                           vol_name,
                           vol_size=10,
                           vol_status='available'):
        rand_id = six.text_type(random.randint(10000, 99999))
        if not vol_name:
            vol_name = 'test_volume%s' % rand_id

        return {'name': vol_name,
                'size': vol_size,
                'id': '%s' % rand_id,
                'volume_type_id': None,
                'status': vol_status,
                'mdisk_grp_name': 'mdiskgrp0'}

    def _generate_snap_info(self,
                            vol_name,
                            vol_id,
                            vol_size,
                            vol_status,
                            snap_status='available'):
        rand_id = six.text_type(random.randint(10000, 99999))
        return {'name': 'test_snap_%s' % rand_id,
                'id': rand_id,
                'volume': {'name': vol_name,
                           'id': vol_id,
                           'size': vol_size,
                           'status': vol_status},
                'volume_size': vol_size,
                'status': snap_status,
                'mdisk_grp_name': 'mdiskgrp0'}

    def setUp(self):
        super(FlashSystemDriverTestCase, self).setUp()

        self._def_flags = {'san_ip': 'hostname',
                           'san_login': 'username',
                           'san_password': 'password',
                           'flashsystem_connection_protocol': 'FC',
                           'flashsystem_multihostmap_enabled': True}

        self.connector = {
            'host': 'flashsystem',
            'wwnns': ['0123456789abcdef', '0123456789abcdeg'],
            'wwpns': ['abcd000000000001', 'abcd000000000002'],
            'initiator': 'iqn.123456'}

        self.alt_connector = {
            'host': 'other',
            'wwnns': ['0123456789fedcba', '0123456789badcfe'],
            'wwpns': ['dcba000000000001', 'dcba000000000002'],
            'initiator': 'iqn.654321'
        }

        self.sim = FlashSystemManagementSimulator()
        self.driver = FlashSystemFakeDriver(
            configuration=conf.Configuration(None))
        self.driver.set_fake_storage(self.sim)

        self._reset_flags()
        self.ctxt = context.get_admin_context()
        self.driver.do_setup(None)
        self.driver.check_for_setup_error()

        self.sleeppatch = mock.patch('eventlet.greenthread.sleep')
        self.sleeppatch.start()

    def tearDown(self):
        self.sleeppatch.stop()
        super(FlashSystemDriverTestCase, self).tearDown()

    def test_flashsystem_do_setup(self):
        # case 1: cmd lssystem encounters error
        self.sim.error_injection('lssystem', 'error')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, None)

        # case 2: open_access_enabled is not off
        self.sim.error_injection('lssystem', 'open_access_enabled=on')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, None)

        # case 3: cmd lsmdiskgrp encounters error
        self.sim.error_injection('lsmdiskgrp', 'error')
        self.assertRaises(exception.InvalidInput,
                          self.driver.do_setup, None)

        # case 4: status is not online
        self.sim.error_injection('lsmdiskgrp', 'status=offline')
        self.assertRaises(exception.InvalidInput,
                          self.driver.do_setup, None)

        # case 5: cmd lsnode encounters error
        self.sim.error_injection('lsnode', 'error')
        self.assertRaises(processutils.ProcessExecutionError,
                          self.driver.do_setup, None)

        # case 6: cmd lsnode header does not match
        self.sim.error_injection('lsnode', 'header_mismatch')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, None)

        # case 7: set as FC
        self.sim.set_protocol('FC')
        self.driver.do_setup(None)
        self.assertEqual('FC', self.driver._protocol)

        # case 8: no configured nodes available
        self.sim.set_protocol('unknown')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, None)

        # clear environment
        self.sim.set_protocol('FC')
        self.driver.do_setup(None)

    def test_flashsystem_check_for_setup_error(self):
        self._set_flag('san_ip', '')
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)
        self._reset_flags()

        self._set_flag('san_ssh_port', '')
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)
        self._reset_flags()

        self._set_flag('san_login', '')
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)
        self._reset_flags()

        self._set_flag('san_password', None)
        self._set_flag('san_private_key', None)
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)
        self._reset_flags()

        self._set_flag('flashsystem_connection_protocol', 'foo')
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)
        self._reset_flags()

        # clear environment
        self.driver.do_setup(None)

    def test_flashsystem_validate_connector(self):
        conn_neither = {'host': 'host'}
        conn_iscsi = {'host': 'host', 'initiator': 'foo'}
        conn_fc = {'host': 'host', 'wwpns': 'bar'}
        conn_both = {'host': 'host', 'initiator': 'foo', 'wwpns': 'bar'}

        protocol = self.driver._protocol

        # case 1: when protocol is FC
        self.driver._protocol = 'FC'
        self.driver.validate_connector(conn_fc)
        self.driver.validate_connector(conn_both)
        self.assertRaises(exception.InvalidConnectorException,
                          self.driver.validate_connector, conn_iscsi)
        self.assertRaises(exception.InvalidConnectorException,
                          self.driver.validate_connector, conn_neither)

        # clear environment
        self.driver._protocol = protocol

    def test_flashsystem_volumes(self):
        # case 1: create volume
        vol = self._generate_vol_info(None)
        self.driver.create_volume(vol)

        # Check whether volume is created successfully
        attributes = self.driver._get_vdisk_attributes(vol['name'])
        attr_size = float(attributes['capacity']) / units.Gi
        self.assertEqual(float(vol['size']), attr_size)

        # case 2: create volume with empty returning value
        with mock.patch.object(FlashSystemFakeDriver,
                               '_ssh') as mock_ssh:
            mock_ssh.return_value = ("", "")
            vol1 = self._generate_vol_info(None)
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.create_volume, vol1)

        # case 3: create volume with error returning value
        with mock.patch.object(FlashSystemFakeDriver,
                               '_ssh') as mock_ssh:
            mock_ssh.return_value = ("CMMVC6070E",
                                     "An invalid or duplicated "
                                     "parameter has been detected.")
            vol2 = self._generate_vol_info(None)
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.create_volume, vol2)

        # case 4: delete volume
        self.driver.delete_volume(vol)

        # case 5: delete volume that doesn't exist (expected not fail)
        vol_no_exist = self._generate_vol_info(None)
        self.driver.delete_volume(vol_no_exist)

    def test_flashsystem_extend_volume(self):
        vol = self._generate_vol_info(None)
        self.driver.create_volume(vol)
        self.driver.extend_volume(vol, '200')
        attrs = self.driver._get_vdisk_attributes(vol['name'])
        vol_size = int(attrs['capacity']) / units.Gi
        self.assertAlmostEqual(vol_size, 200)

        # clear environment
        self.driver.delete_volume(vol)

    def test_flashsystem_connection(self):
        # case 1: initialize_connection/terminate_connection for good path
        vol1 = self._generate_vol_info(None)
        self.driver.create_volume(vol1)
        self.driver.initialize_connection(vol1, self.connector)
        self.driver.terminate_connection(vol1, self.connector)

        # case 2: when volume is not existed
        vol2 = self._generate_vol_info(None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          vol2, self.connector)

        # case 3: _get_vdisk_map_properties raises exception
        with mock.patch.object(flashsystem_fc.FlashSystemFCDriver,
                               '_get_vdisk_map_properties') as get_properties:
            get_properties.side_effect = (
                exception.VolumeBackendAPIException(data=''))
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.initialize_connection,
                              vol1, self.connector)

        # case 4: terminate_connection with no host
        with mock.patch.object(flashsystem_fc.FlashSystemFCDriver,
                               '_get_hostvdisk_mappings') as mock_host:
            mock_host.return_value = {}
            vol3 = self._generate_vol_info(None)
            self.driver.create_volume(vol3)
            self.driver.initialize_connection(vol3, self.connector)
            return_value = self.driver.terminate_connection(vol3,
                                                            self.connector)
            self.assertNotEqual({}, return_value['data'])

        # case 5: terminate_connection with host
        vol4 = self._generate_vol_info(None)
        self.driver.create_volume(vol4)
        self.driver.initialize_connection(vol4, self.connector)
        vol5 = self._generate_vol_info(None)
        self.driver.create_volume(vol5)
        self.driver.initialize_connection(vol5, self.connector)
        return_value = self.driver.terminate_connection(vol4,
                                                        self.connector)
        self.assertEqual({}, return_value['data'])

        # clear environment
        self.driver.delete_volume(vol1)
        self.driver.delete_volume(vol2)
        self.driver.delete_volume(vol3)
        self.driver.delete_volume(vol4)
        self.driver.delete_volume(vol5)

    @mock.patch.object(flashsystem_fc.FlashSystemFCDriver,
                       '_create_and_copy_vdisk_data')
    def test_flashsystem_create_snapshot(self, _create_and_copy_vdisk_data):
        # case 1: good path
        vol1 = self._generate_vol_info(None)
        snap1 = self._generate_snap_info(vol1['name'],
                                         vol1['id'],
                                         vol1['size'],
                                         vol1['status'])
        self.driver.create_snapshot(snap1)

        # case 2: when volume status is error
        vol2 = self._generate_vol_info(None, vol_status='error')
        snap2 = self._generate_snap_info(vol2['name'],
                                         vol2['id'],
                                         vol2['size'],
                                         vol2['status'])
        self.assertRaises(exception.InvalidVolume,
                          self.driver.create_snapshot, snap2)

    @mock.patch.object(flashsystem_fc.FlashSystemFCDriver,
                       '_delete_vdisk')
    def test_flashsystem_delete_snapshot(self, _delete_vdisk):
        vol1 = self._generate_vol_info(None)
        snap1 = self._generate_snap_info(vol1['name'],
                                         vol1['id'],
                                         vol1['size'],
                                         vol1['status'])
        self.driver.delete_snapshot(snap1)

    @mock.patch.object(flashsystem_fc.FlashSystemFCDriver,
                       '_create_and_copy_vdisk_data')
    def test_flashsystem_create_volume_from_snapshot(
            self, _create_and_copy_vdisk_data):
        # case 1: good path
        vol = self._generate_vol_info(None)
        snap = self._generate_snap_info(vol['name'],
                                        vol['id'],
                                        vol['size'],
                                        vol['status'])
        self.driver.create_volume_from_snapshot(vol, snap)

        # case 2: when size does not match
        vol = self._generate_vol_info(None, vol_size=100)
        snap = self._generate_snap_info(vol['name'],
                                        vol['id'],
                                        200,
                                        vol['status'])
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume_from_snapshot,
                          vol, snap)

        # case 3: when snapshot status is not available
        vol = self._generate_vol_info(None)
        snap = self._generate_snap_info(vol['name'],
                                        vol['id'],
                                        vol['size'],
                                        vol['status'],
                                        snap_status='error')
        self.assertRaises(exception.InvalidSnapshot,
                          self.driver.create_volume_from_snapshot,
                          vol, snap)

    @mock.patch.object(flashsystem_fc.FlashSystemFCDriver,
                       '_create_and_copy_vdisk_data')
    def test_flashsystem_create_cloned_volume(
            self, _create_and_copy_vdisk_data):
        # case 1: good path
        vol1 = self._generate_vol_info(None)
        vol2 = self._generate_vol_info(None)
        self.driver.create_cloned_volume(vol2, vol1)

        # case 2: destination larger than source
        vol1 = self._generate_vol_info(None, vol_size=10)
        vol2 = self._generate_vol_info(None, vol_size=20)
        self.driver.create_cloned_volume(vol2, vol1)

        # case 3: destination smaller than source
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_cloned_volume,
                          vol1, vol2)

    def test_flashsystem_get_volume_stats(self):
        # case 1: good path
        self._set_flag('reserved_percentage', 25)
        self._set_flag('flashsystem_multihostmap_enabled', False)
        pool = 'mdiskgrp0'
        backend_name = 'flashsystem_1.2.3.4' + '_' + pool

        stats = self.driver.get_volume_stats()

        self.assertEqual(25, stats['reserved_percentage'])
        self.assertEqual('IBM', stats['vendor_name'])
        self.assertEqual('FC', stats['storage_protocol'])
        self.assertEqual(backend_name, stats['volume_backend_name'])
        self.assertEqual(False, stats['multiattach'])

        self._reset_flags()

        # case 2: when lsmdiskgrp returns error
        self.sim.error_injection('lsmdiskgrp', 'error')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.get_volume_stats, refresh=True)

    @mock.patch.object(flashsystem_fc.FlashSystemFCDriver,
                       '_copy_vdisk_data')
    def test_flashsystem_create_and_copy_vdisk_data(self, _copy_vdisk_data):
        # case 1: when volume does not exist
        vol1 = self._generate_vol_info(None)
        vol2 = self._generate_vol_info(None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._create_and_copy_vdisk_data,
                          vol1['name'], vol1['id'], vol2['name'], vol2['id'])

        # case 2: good path
        self.driver.create_volume(vol1)
        self.driver._create_and_copy_vdisk_data(
            vol1['name'], vol1['id'], vol2['name'], vol2['id'])
        self.driver.delete_volume(vol1)
        self.driver.delete_volume(vol2)

        # case 3: _copy_vdisk_data raises exception
        self.driver.create_volume(vol1)
        _copy_vdisk_data.side_effect = (
            exception.VolumeBackendAPIException(data=''))
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver._create_and_copy_vdisk_data,
            vol1['name'], vol1['id'], vol2['name'], vol2['id'])
        self.assertEqual(set(), self.driver._vdisk_copy_in_progress)

        # clear environment
        self.driver.delete_volume(vol1)
        self.driver.delete_volume(vol2)

    @mock.patch.object(volume_utils, 'copy_volume')
    @mock.patch.object(flashsystem_fc.FlashSystemFCDriver, '_scan_device')
    @mock.patch.object(flashsystem_fc.FlashSystemFCDriver, '_remove_device')
    @mock.patch.object(utils, 'brick_get_connector_properties')
    def test_flashsystem_copy_vdisk_data(self,
                                         _connector,
                                         _remove_device,
                                         _scan_device,
                                         copy_volume):

        connector = _connector.return_value = self.connector
        vol1 = self._generate_vol_info(None)
        vol2 = self._generate_vol_info(None)
        self.driver.create_volume(vol1)
        self.driver.create_volume(vol2)

        # case 1: no mapped before copy
        self.driver._copy_vdisk_data(
            vol1['name'], vol1['id'], vol2['name'], vol2['id'])
        (v1_mapped, lun) = self.driver._is_vdisk_map(vol1['name'], connector)
        (v2_mapped, lun) = self.driver._is_vdisk_map(vol2['name'], connector)
        self.assertFalse(v1_mapped)
        self.assertFalse(v2_mapped)

        # case 2: mapped before copy
        self.driver.initialize_connection(vol1, connector)
        self.driver.initialize_connection(vol2, connector)
        self.driver._copy_vdisk_data(
            vol1['name'], vol1['id'], vol2['name'], vol2['id'])
        (v1_mapped, lun) = self.driver._is_vdisk_map(vol1['name'], connector)
        (v2_mapped, lun) = self.driver._is_vdisk_map(vol2['name'], connector)
        self.assertTrue(v1_mapped)
        self.assertTrue(v2_mapped)
        self.driver.terminate_connection(vol1, connector)
        self.driver.terminate_connection(vol2, connector)

        # case 3: no mapped before copy, raise exception when scan
        _scan_device.side_effect = exception.VolumeBackendAPIException(data='')
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver._copy_vdisk_data,
            vol1['name'], vol1['id'], vol2['name'], vol2['id'])
        (v1_mapped, lun) = self.driver._is_vdisk_map(vol1['name'], connector)
        (v2_mapped, lun) = self.driver._is_vdisk_map(vol2['name'], connector)
        self.assertFalse(v1_mapped)
        self.assertFalse(v2_mapped)

        # case 4: no mapped before copy, raise exception when copy
        copy_volume.side_effect = exception.VolumeBackendAPIException(data='')
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver._copy_vdisk_data,
            vol1['name'], vol1['id'], vol2['name'], vol2['id'])
        (v1_mapped, lun) = self.driver._is_vdisk_map(vol1['name'], connector)
        (v2_mapped, lun) = self.driver._is_vdisk_map(vol2['name'], connector)
        self.assertFalse(v1_mapped)
        self.assertFalse(v2_mapped)

        # clear environment
        self.driver.delete_volume(vol1)
        self.driver.delete_volume(vol2)

    def test_flashsystem_connector_to_hostname_prefix(self):
        # Invalid characters will be translated to '-'

        # case 1: host name is unicode with invalid characters
        conn = {'host': u'unicode.test}.abc{.abc'}
        self.assertEqual(u'unicode.test-.abc-.abc',
                         self.driver._connector_to_hostname_prefix(conn))

        # case 2: host name is string with invalid characters
        conn = {'host': 'string.test}.abc{.abc'}
        self.assertEqual('string.test-.abc-.abc',
                         self.driver._connector_to_hostname_prefix(conn))

        # case 3: host name is neither unicode nor string
        conn = {'host': 12345}
        self.assertRaises(exception.NoValidBackend,
                          self.driver._connector_to_hostname_prefix,
                          conn)

        # case 4: host name started with number will be translated
        conn = {'host': '192.168.1.1'}
        self.assertEqual('_192.168.1.1',
                         self.driver._connector_to_hostname_prefix(conn))

    def test_flashsystem_create_host(self):
        # case 1: create host
        conn = {
            'host': 'flashsystem',
            'wwnns': ['0123456789abcdef', '0123456789abcdeg'],
            'wwpns': ['abcd000000000001', 'abcd000000000002'],
            'initiator': 'iqn.123456'}
        host = self.driver._create_host(conn)

        # case 2: create host that already exists
        self.assertRaises(processutils.ProcessExecutionError,
                          self.driver._create_host,
                          conn)

        # case 3: delete host
        self.driver._delete_host(host)

        # case 4: create host with empty ports
        conn = {'host': 'flashsystem', 'wwpns': []}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._create_host,
                          conn)

    def test_flashsystem_find_host_exhaustive(self):
        # case 1: create host and find it
        conn1 = {
            'host': 'flashsystem-01',
            'wwnns': ['1111111111abcdef', '1111111111abcdeg'],
            'wwpns': ['1111111111000001', '1111111111000002'],
            'initiator': 'iqn.111111'}
        conn2 = {
            'host': 'flashsystem-02',
            'wwnns': ['2222222222abcdef', '2222222222abcdeg'],
            'wwpns': ['2222222222000001', '2222222222000002'],
            'initiator': 'iqn.222222'}
        conn3 = {
            'host': 'flashsystem-03',
            'wwnns': ['3333333333abcdef', '3333333333abcdeg'],
            'wwpns': ['3333333333000001', '3333333333000002'],
            'initiator': 'iqn.333333'}
        host1 = self.driver._create_host(conn1)
        host2 = self.driver._create_host(conn2)
        self.assertEqual(
            host2,
            self.driver._find_host_exhaustive(conn2, [host1, host2]))
        self.assertIsNone(self.driver._find_host_exhaustive(conn3,
                                                            [host1, host2]))

        # case 2: hosts contains non-existent host info
        with mock.patch.object(FlashSystemFakeDriver,
                               '_ssh') as mock_ssh:
            mock_ssh.return_value = ("pass", "")
            self.driver._find_host_exhaustive(conn1, [host2])
            self.assertFalse(mock_ssh.called)

        # clear environment
        self.driver._delete_host(host1)
        self.driver._delete_host(host2)

    def test_flashsystem_get_vdisk_params(self):
        # case 1: use default params
        self.driver._get_vdisk_params(None)

        # case 2: use extra params from type
        opts1 = {'storage_protocol': 'FC'}
        opts2 = {'capabilities:storage_protocol': 'FC'}
        opts3 = {'storage_protocol': 'iSCSI'}
        type1 = volume_types.create(self.ctxt, 'opts1', opts1)
        type2 = volume_types.create(self.ctxt, 'opts2', opts2)
        type3 = volume_types.create(self.ctxt, 'opts3', opts3)
        self.assertEqual(
            'FC',
            self.driver._get_vdisk_params(type1['id'])['protocol'])
        self.assertEqual(
            'FC',
            self.driver._get_vdisk_params(type2['id'])['protocol'])
        self.assertRaises(exception.InvalidInput,
                          self.driver._get_vdisk_params,
                          type3['id'])

        # clear environment
        volume_types.destroy(self.ctxt, type1['id'])
        volume_types.destroy(self.ctxt, type2['id'])

    def test_flashsystem_map_vdisk_to_host(self):
        # case 1: no host found
        vol1 = self._generate_vol_info(None)
        self.driver.create_volume(vol1)
        self.assertEqual(
            # lun id shoud begin with 1
            1,
            self.driver._map_vdisk_to_host(vol1['name'], self.connector))

        # case 2: host already exists
        vol2 = self._generate_vol_info(None)
        self.driver.create_volume(vol2)
        self.assertEqual(
            # lun id shoud be sequential
            2,
            self.driver._map_vdisk_to_host(vol2['name'], self.connector))

        # case 3: test if already mapped
        self.assertEqual(
            1,
            self.driver._map_vdisk_to_host(vol1['name'], self.connector))

        # case 4: multi-host mapping, good path
        for error in self.sim._multi_host_map_errors:
            self.sim._multi_host_map_error = error
            self.assertEqual(
                1,
                self.driver._map_vdisk_to_host(
                    vol1['name'], self.alt_connector
                )
            )
            self.driver._unmap_vdisk_from_host(
                vol1['name'], self.alt_connector
            )
        self.sim._multi_host_map_error = None

        # case 5: multi-host mapping, bad path
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver._map_vdisk_to_host, vol1['name'], self.alt_connector)

        # clean environment
        self.driver._unmap_vdisk_from_host(vol1['name'], self.connector)
        self.driver._unmap_vdisk_from_host(vol2['name'], self.connector)
        self.driver.delete_volume(vol1)
        self.driver.delete_volume(vol2)

        # case 4: If there is no vdisk mapped to host, host should be removed
        self.assertIsNone(self.driver._get_host_from_connector(self.connector))

    def test_flashsystem_manage_existing(self):
        # case 1: manage a vdisk good path
        kwargs = {'name': u'unmanage-vol-01', 'size': u'1', 'unit': 'gb'}
        self.sim._cmd_mkvdisk(**kwargs)
        vol1 = self._generate_vol_info(None)
        existing_ref = {'source-name': u'unmanage-vol-01'}
        self.driver.manage_existing(vol1, existing_ref)
        self.driver.delete_volume(vol1)

        # case 2: manage a vdisk not exist
        vol1 = self._generate_vol_info(None)
        existing_ref = {'source-name': u'unmanage-vol-01'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, vol1, existing_ref)

        # case 3: manage a vdisk without name and uid
        kwargs = {'name': u'unmanage-vol-01', 'size': u'1', 'unit': 'gb'}
        self.sim._cmd_mkvdisk(**kwargs)
        vol1 = self._generate_vol_info(None)
        existing_ref = {}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, vol1, existing_ref)
        vdisk1 = {'obj': u'unmanage-vol-01'}
        self.sim._cmd_rmvdisk(**vdisk1)

    @mock.patch.object(flashsystem_fc.FlashSystemFCDriver,
                       '_get_vdiskhost_mappings')
    def test_flashsystem_manage_existing_get_size_mapped(
            self,
            _get_vdiskhost_mappings_mock):
        # manage a vdisk with mappings
        _get_vdiskhost_mappings_mock.return_value = {'mapped': u'yes'}
        kwargs = {'name': u'unmanage-vol-01', 'size': u'1', 'unit': 'gb'}
        self.sim._cmd_mkvdisk(**kwargs)
        vol1 = self._generate_vol_info(None)
        existing_ref = {'source-name': u'unmanage-vol-01'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          vol1,
                          existing_ref)

        # clean environment
        vdisk1 = {'obj': u'unmanage-vol-01'}
        self.sim._cmd_rmvdisk(**vdisk1)

    def test_flashsystem_manage_existing_get_size_bad_ref(self):
        # bad existing_ref
        vol1 = self._generate_vol_info(None, None)
        existing_ref = {}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, vol1,
                          existing_ref)

    def test_flashsystem_manage_existing_get_size_vdisk_not_exist(self):
        # vdisk not exist
        vol1 = self._generate_vol_info(None)
        existing_ref = {'source-name': u'unmanage-vol-01'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          vol1,
                          existing_ref)

    def test_flashsystem_manage_existing_get_size(self):
        # good path
        kwargs = {'name': u'unmanage-vol-01', 'size': u'10001', 'unit': 'gb'}
        self.sim._cmd_mkvdisk(**kwargs)
        vol1 = self._generate_vol_info(None)
        existing_ref = {'source-name': u'unmanage-vol-01'}
        vdisk_size = self.driver.manage_existing_get_size(vol1, existing_ref)
        self.assertEqual(10001, vdisk_size)

        # clean environment
        vdisk1 = {'obj': u'unmanage-vol-01'}
        self.sim._cmd_rmvdisk(**vdisk1)
