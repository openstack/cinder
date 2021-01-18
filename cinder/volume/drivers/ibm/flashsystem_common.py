# Copyright 2015 IBM Corporation.
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
Volume driver for IBM FlashSystem storage systems.

Limitations:
1. Cinder driver only works when open_access_enabled=off.

"""

import re
import string

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import units
import six

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import volume_types
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)

FLASHSYSTEM_VOLPOOL_NAME = 'mdiskgrp0'
FLASHSYSTEM_VOL_IOGRP = 0

flashsystem_opts = [
    cfg.StrOpt('flashsystem_connection_protocol',
               default='FC',
               help='Connection protocol should be FC. '
                    '(Default is FC.)'),
    cfg.BoolOpt('flashsystem_multihostmap_enabled',
                default=True,
                help='Allows vdisk to multi host mapping. '
                     '(Default is True)')
]

CONF = cfg.CONF
CONF.register_opts(flashsystem_opts, group=configuration.SHARED_CONF_GROUP)


class FlashSystemDriver(san.SanDriver,
                        driver.ManageableVD,
                        driver.BaseVD):
    """IBM FlashSystem volume driver.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver
        1.0.1 - Code clean up
        1.0.2 - Add lock into vdisk map/unmap, connection
                initialize/terminate
        1.0.3 - Initial driver for iSCSI
        1.0.4 - Split Flashsystem driver into common and FC
        1.0.5 - Report capability of volume multiattach
        1.0.6 - Fix bug #1469581, add I/T mapping check in
                terminate_connection
        1.0.7 - Fix bug #1505477, add host name check in
                _find_host_exhaustive for FC
        1.0.8 - Fix bug #1572743, multi-attach attribute
                should not be hardcoded, only in iSCSI
        1.0.9 - Fix bug #1570574, Cleanup host resource
                leaking, changes only in iSCSI
        1.0.10 - Fix bug #1585085, add host name check in
                 _find_host_exhaustive for iSCSI
        1.0.11 - Update driver to use ABC metaclasses
        1.0.12 - Update driver to support Manage/Unmanage
                 existing volume
    """

    VERSION = "1.0.12"

    # TODO(jsbryant) Remove driver in the 'U' release if CI is not fixed.
    SUPPORTED = False

    MULTI_HOST_MAP_ERRORS = ['CMMVC6045E', 'CMMVC6071E']

    def __init__(self, *args, **kwargs):
        super(FlashSystemDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(flashsystem_opts)
        self._storage_nodes = {}
        self._protocol = None
        self._context = None
        self._system_name = None
        self._system_id = None
        self._check_lock_interval = 5
        self._vdisk_copy_in_progress = set()
        self._vdisk_copy_lock = None

    @staticmethod
    def get_driver_options():
        return flashsystem_opts

    def _ssh(self, ssh_cmd, check_exit_code=True):
        try:
            return self._run_ssh(ssh_cmd, check_exit_code)
        except processutils.ProcessExecutionError as e:
            msg = (_('CLI Exception output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s')
                   % {'cmd': ssh_cmd, 'out': e.stdout,
                      'err': e.stderr})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _append_dict(self, dict_, key, value):
        key, value = key.strip(), value.strip()
        obj = dict_.get(key, None)
        if obj is None:
            dict_[key] = value
        elif isinstance(obj, list):
            obj.append(value)
            dict_[key] = obj
        else:
            dict_[key] = [obj, value]
        return dict_

    def _assert_ssh_return(self, test, fun, ssh_cmd, out, err):
        self._driver_assert(test,
                            (_('%(fun)s: Failed with unexpected CLI output.\n '
                               'Command: %(cmd)s\n stdout: %(out)s\n '
                               'stderr: %(err)s')
                             % {'fun': fun, 'cmd': ssh_cmd,
                                'out': six.text_type(out),
                                'err': six.text_type(err)}))

    def _build_default_params(self):
        return {'protocol': self.configuration.flashsystem_connection_protocol}

    def _build_initiator_target_map(self, initiator_wwpns, target_wwpns):
        map = {}
        for i_wwpn in initiator_wwpns:
            idx = six.text_type(i_wwpn)
            map[idx] = []
            for t_wwpn in target_wwpns:
                map[idx].append(t_wwpn)
        return map

    def _check_vdisk_params(self, params):
        raise NotImplementedError()

    def _connector_to_hostname_prefix(self, connector):
        """Translate connector info to storage system host name.

        Translate a host's name and IP to the prefix of its hostname on the
        storage subsystem.  We create a host name from the host and
        IP address, replacing any invalid characters (at most 55 characters),
        and adding a random 8-character suffix to avoid collisions. The total
        length should be at most 63 characters.

        """

        # Build cleanup translation tables for host names
        invalid_ch_in_host = ''
        for num in range(0, 128):
            ch = six.text_type(chr(num))
            if not ch.isalnum() and ch not in [' ', '.', '-', '_']:
                invalid_ch_in_host = invalid_ch_in_host + ch

        host_name = connector['host']
        if isinstance(host_name, six.text_type):
            unicode_host_name_filter = {ord(six.text_type(char)): u'-'
                                        for char in invalid_ch_in_host}
            host_name = host_name.translate(unicode_host_name_filter)
        elif isinstance(host_name, str):
            string_host_name_filter = string.maketrans(
                invalid_ch_in_host, '-' * len(invalid_ch_in_host))
            host_name = host_name.translate(string_host_name_filter)
        else:
            msg = _('_create_host: Can not translate host name. Host name '
                    'is not unicode or string.')
            LOG.error(msg)
            raise exception.NoValidBackend(reason=msg)

        host_name = six.text_type(host_name)

        # FlashSystem family doesn't like hostname that starts with number.
        if not re.match('^[A-Za-z]', host_name):
            host_name = '_' + host_name

        return host_name[:55]

    def _copy_vdisk_data(self, src_vdisk_name, src_vdisk_id,
                         dest_vdisk_name, dest_vdisk_id):
        """Copy data from src vdisk to dest vdisk.

        To be able to copy data between vdisks, we must ensure that both
        vdisks have been mapped to host. If vdisk has not been mapped,
        it must be mapped firstly. When data copy completed, vdisk
        should be restored to previous mapped or non-mapped status.
        """

        LOG.debug('enter: _copy_vdisk_data: %(src)s -> %(dest)s.',
                  {'src': src_vdisk_name, 'dest': dest_vdisk_name})

        connector = volume_utils.brick_get_connector_properties()
        (src_map, src_lun_id) = self._is_vdisk_map(
            src_vdisk_name, connector)
        (dest_map, dest_lun_id) = self._is_vdisk_map(
            dest_vdisk_name, connector)

        src_map_device = None
        src_properties = None
        dest_map_device = None
        dest_properties = None

        try:
            if not src_map:
                src_lun_id = self._map_vdisk_to_host(src_vdisk_name,
                                                     connector)
            if not dest_map:
                dest_lun_id = self._map_vdisk_to_host(dest_vdisk_name,
                                                      connector)
            src_properties = self._get_vdisk_map_properties(
                connector, src_lun_id, src_vdisk_name,
                src_vdisk_id, self._get_vdisk_params(None))
            src_map_device = self._scan_device(src_properties)

            dest_properties = self._get_vdisk_map_properties(
                connector, dest_lun_id, dest_vdisk_name,
                dest_vdisk_id, self._get_vdisk_params(None))
            dest_map_device = self._scan_device(dest_properties)

            src_vdisk_attr = self._get_vdisk_attributes(src_vdisk_name)

            # vdisk capacity is bytes, translate into MB
            size_in_mb = int(src_vdisk_attr['capacity']) / units.Mi
            volume_utils.copy_volume(
                src_map_device['path'],
                dest_map_device['path'],
                size_in_mb,
                self.configuration.volume_dd_blocksize)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to copy %(src)s to %(dest)s.',
                          {'src': src_vdisk_name, 'dest': dest_vdisk_name})
        finally:
            if not dest_map:
                self._unmap_vdisk_from_host(dest_vdisk_name, connector)
                self._remove_device(dest_properties, dest_map_device)
            if not src_map:
                self._unmap_vdisk_from_host(src_vdisk_name, connector)
                self._remove_device(src_properties, src_map_device)

        LOG.debug(
            'leave: _copy_vdisk_data: %(src)s -> %(dest)s.',
            {'src': src_vdisk_name, 'dest': dest_vdisk_name})

    def _create_and_copy_vdisk_data(self, src_vdisk_name, src_vdisk_id,
                                    dest_vdisk_name, dest_vdisk_id,
                                    dest_vdisk_size=None):
        if dest_vdisk_size is None:
            vdisk_attr = self._get_vdisk_attributes(src_vdisk_name)
            self._driver_assert(
                vdisk_attr is not None,
                (_('_create_and_copy_vdisk_data: Failed to get attributes for '
                   'vdisk %s.') % src_vdisk_name))
            dest_vdisk_size = vdisk_attr['capacity']

        self._create_vdisk(dest_vdisk_name, dest_vdisk_size, 'b', None)

        # create a timer to lock vdisk that will be used to data copy
        timer = loopingcall.FixedIntervalLoopingCall(
            self._set_vdisk_copy_in_progress,
            [src_vdisk_name, dest_vdisk_name])
        timer.start(interval=self._check_lock_interval).wait()

        try:
            self._copy_vdisk_data(src_vdisk_name, src_vdisk_id,
                                  dest_vdisk_name, dest_vdisk_id)
        finally:
            self._unset_vdisk_copy_in_progress(
                [src_vdisk_name, dest_vdisk_name])

    def _create_host(self, connector):
        raise NotImplementedError()

    def _create_vdisk(self, name, size, unit, opts):
        """Create a new vdisk."""

        LOG.debug('enter: _create_vdisk: vdisk %s.', name)

        ssh_cmd = ['svctask', 'mkvdisk', '-name', name, '-mdiskgrp',
                   FLASHSYSTEM_VOLPOOL_NAME, '-iogrp',
                   six.text_type(FLASHSYSTEM_VOL_IOGRP),
                   '-size', six.text_type(size), '-unit', unit]
        out, err = self._ssh(ssh_cmd)
        self._assert_ssh_return(out.strip(), '_create_vdisk',
                                ssh_cmd, out, err)

        # Ensure that the output is as expected
        match_obj = re.search(
            r'Virtual Disk, id \[([0-9]+)\], successfully created', out)

        self._driver_assert(
            match_obj is not None,
            (_('_create_vdisk %(name)s - did not find '
               'success message in CLI output.\n '
               'stdout: %(out)s\n stderr: %(err)s')
             % {'name': name, 'out': six.text_type(out),
                'err': six.text_type(err)}))

        LOG.debug('leave: _create_vdisk: vdisk %s.', name)

    def _delete_host(self, host_name):
        """Delete a host on the storage system."""

        LOG.debug('enter: _delete_host: host %s.', host_name)

        ssh_cmd = ['svctask', 'rmhost', host_name]
        out, err = self._ssh(ssh_cmd)
        # No output should be returned from rmhost
        self._assert_ssh_return(
            (not out.strip()),
            '_delete_host', ssh_cmd, out, err)

        LOG.debug('leave: _delete_host: host %s.', host_name)

    def _delete_vdisk(self, name, force):
        """Deletes existing vdisks."""

        LOG.debug('enter: _delete_vdisk: vdisk %s.', name)

        # Try to delete volume only if found on the storage
        vdisk_defined = self._is_vdisk_defined(name)
        if not vdisk_defined:
            LOG.warning('warning: Tried to delete vdisk %s but '
                        'it does not exist.', name)
            return

        ssh_cmd = ['svctask', 'rmvdisk', '-force', name]
        if not force:
            ssh_cmd.remove('-force')
        out, err = self._ssh(ssh_cmd)
        # No output should be returned from rmvdisk
        self._assert_ssh_return(
            (not out.strip()),
            ('_delete_vdisk %(name)s') % {'name': name},
            ssh_cmd, out, err)

        LOG.debug('leave: _delete_vdisk: vdisk %s.', name)

    def _driver_assert(self, assert_condition, exception_message):
        """Internal assertion mechanism for CLI output."""
        if not assert_condition:
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _execute_command_and_parse_attributes(self, ssh_cmd):
        """Execute command on the FlashSystem and parse attributes.

        Exception is raised if the information from the system
        can not be obtained.

        """

        LOG.debug(
            'enter: _execute_command_and_parse_attributes: '
            'command: %s.', six.text_type(ssh_cmd))

        try:
            out, err = self._ssh(ssh_cmd)
        except processutils.ProcessExecutionError:
            LOG.warning('Failed to run command: %s.', ssh_cmd)
            # Does not raise exception when command encounters error.
            # Only return and the upper logic decides what to do.
            return None

        self._assert_ssh_return(
            out,
            '_execute_command_and_parse_attributes', ssh_cmd, out, err)

        attributes = {}
        for attrib_line in out.split('\n'):
            # If '!' not found, return the string and two empty strings
            attrib_name, foo, attrib_value = attrib_line.partition('!')
            if attrib_name is not None and attrib_name.strip():
                self._append_dict(attributes, attrib_name, attrib_value)

        LOG.debug(
            'leave: _execute_command_and_parse_attributes: '
            'command: %(cmd)s attributes: %(attr)s.',
            {'cmd': six.text_type(ssh_cmd),
             'attr': six.text_type(attributes)})

        return attributes

    def _find_host_exhaustive(self, connector, hosts):
        raise NotImplementedError()

    def _get_hdr_dic(self, header, row, delim):
        """Return CLI row data as a dictionary indexed by names from header.

        The strings are converted to columns using the delimiter in delim.
        """

        attributes = header.split(delim)
        values = row.split(delim)
        self._driver_assert(
            len(values) == len(attributes),
            (_('_get_hdr_dic: attribute headers and values do not match.\n '
               'Headers: %(header)s\n Values: %(row)s.')
             % {'header': six.text_type(header), 'row': six.text_type(row)}))
        dic = {a: v for a, v in zip(attributes, values)}
        return dic

    def _get_host_from_connector(self, connector):
        """List the hosts defined in the storage.

        Return the host name with the given connection info, or None if there
        is no host fitting that information.

        """

        LOG.debug('enter: _get_host_from_connector: %s.', connector)

        # Get list of host in the storage
        ssh_cmd = ['svcinfo', 'lshost', '-delim', '!']
        out, err = self._ssh(ssh_cmd)

        if not out.strip():
            return None

        # If we have FC information, we have a faster lookup option
        hostname = None

        host_lines = out.strip().split('\n')
        self._assert_ssh_return(
            host_lines,
            '_get_host_from_connector', ssh_cmd, out, err)
        header = host_lines.pop(0).split('!')
        self._assert_ssh_return(
            'name' in header,
            '_get_host_from_connector', ssh_cmd, out, err)
        name_index = header.index('name')
        hosts = [x.split('!')[name_index] for x in host_lines]
        hostname = self._find_host_exhaustive(connector, hosts)

        LOG.debug('leave: _get_host_from_connector: host %s.', hostname)

        return hostname

    def _get_hostvdisk_mappings(self, host_name):
        """Return the defined storage mappings for a host."""

        return_data = {}
        ssh_cmd = ['svcinfo', 'lshostvdiskmap', '-delim', '!', host_name]
        out, err = self._ssh(ssh_cmd)

        mappings = out.strip().split('\n')
        if mappings:
            header = mappings.pop(0)
            for mapping_line in mappings:
                mapping_data = self._get_hdr_dic(header, mapping_line, '!')
                return_data[mapping_data['vdisk_name']] = mapping_data

        return return_data

    def _get_node_data(self):
        """Get and verify node configuration."""

        # Get storage system name and id
        ssh_cmd = ['svcinfo', 'lssystem', '-delim', '!']
        attributes = self._execute_command_and_parse_attributes(ssh_cmd)
        if not attributes or ('name' not in attributes):
            msg = _('Could not get system name.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        self._system_name = attributes['name']
        self._system_id = attributes['id']

        # Validate value of open_access_enabled flag, for now only
        # support when open_access_enabled is off
        if not attributes or ('open_access_enabled' not in attributes) or (
                attributes['open_access_enabled'] != 'off'):
            msg = _('open_access_enabled is not off.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Validate that the array exists
        pool = FLASHSYSTEM_VOLPOOL_NAME
        ssh_cmd = ['svcinfo', 'lsmdiskgrp', '-bytes', '-delim', '!', pool]
        attributes = self._execute_command_and_parse_attributes(ssh_cmd)
        if not attributes:
            msg = _('Unable to parse attributes.')
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)
        if ('status' not in attributes) or (
                attributes['status'] == 'offline'):
            msg = (_('Array does not exist or is offline. '
                     'Current status of array is %s.')
                   % attributes['status'])
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        # Get the iSCSI names of the FlashSystem nodes
        ssh_cmd = ['svcinfo', 'lsnode', '-delim', '!']
        out, err = self._ssh(ssh_cmd)
        self._assert_ssh_return(
            out.strip(), '_get_config_data', ssh_cmd, out, err)

        nodes = out.strip().splitlines()
        self._assert_ssh_return(nodes, '_get_node_data', ssh_cmd, out, err)
        header = nodes.pop(0)
        for node_line in nodes:
            try:
                node_data = self._get_hdr_dic(header, node_line, '!')
            except exception.VolumeBackendAPIException:
                with excutils.save_and_reraise_exception():
                    self._log_cli_output_error('_get_node_data',
                                               ssh_cmd, out, err)
            try:
                node = {
                    'id': node_data['id'],
                    'name': node_data['name'],
                    'IO_group': node_data['IO_group_id'],
                    'WWNN': node_data['WWNN'],
                    'status': node_data['status'],
                    'WWPN': [],
                    'protocol': None,
                    'iscsi_name': node_data['iscsi_name'],
                    'config_node': node_data['config_node'],
                    'ipv4': [],
                    'ipv6': [],
                }
                if node['status'] == 'online':
                    self._storage_nodes[node['id']] = node
            except KeyError:
                self._handle_keyerror('lsnode', header)

    def _get_vdisk_attributes(self, vdisk_ref):
        """Return vdisk attributes

        Exception is raised if the information from system can not be
        parsed/matched to a single vdisk.

        :param vdisk_ref: vdisk name or vdisk id
        """

        ssh_cmd = [
            'svcinfo', 'lsvdisk', '-bytes', '-delim', '!', vdisk_ref]

        return self._execute_command_and_parse_attributes(ssh_cmd)

    def _get_vdisk_map_properties(
            self, connector, lun_id, vdisk_name, vdisk_id, vdisk_params):
        raise NotImplementedError()

    def _get_vdiskhost_mappings(self, vdisk_name):
        """Return the defined storage mappings for a vdisk."""

        return_data = {}
        ssh_cmd = ['svcinfo', 'lsvdiskhostmap', '-delim', '!', vdisk_name]
        out, err = self._ssh(ssh_cmd)

        mappings = out.strip().split('\n')
        if mappings:
            header = mappings.pop(0)
            for mapping_line in mappings:
                mapping_data = self._get_hdr_dic(header, mapping_line, '!')
                return_data[mapping_data['host_name']] = mapping_data

        return return_data

    def _get_vdisk_params(self, type_id):
        params = self._build_default_params()
        if type_id:
            ctxt = context.get_admin_context()
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            specs = volume_type.get('extra_specs')
            for k, value in specs.items():
                # Get the scope, if using scope format
                key_split = k.split(':')
                if len(key_split) == 1:
                    scope = None
                    key = key_split[0]
                else:
                    scope = key_split[0]
                    key = key_split[1]

                # We generally do not look at capabilities in the driver, but
                # protocol is a special case where the user asks for a given
                # protocol and we want both the scheduler and the driver to act
                # on the value.
                if ((not scope or scope == 'capabilities') and
                        key == 'storage_protocol'):
                    scope = None
                    key = 'protocol'

                # Anything keys that the driver should look at should have the
                # 'drivers' scope.
                if scope and scope != "drivers":
                    continue

                if key in params:
                    this_type = type(params[key]).__name__
                    if this_type == 'int':
                        value = int(value)
                    elif this_type == 'bool':
                        value = strutils.bool_from_string(value)
                    params[key] = value

        self._check_vdisk_params(params)

        return params

    def _handle_keyerror(self, function, header):
        msg = (_('Did not find expected column in %(fun)s: %(hdr)s.')
               % {'fun': function, 'hdr': header})
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def _is_vdisk_defined(self, vdisk_name):
        """Check if vdisk is defined."""
        LOG.debug('enter: _is_vdisk_defined: vdisk %s.', vdisk_name)

        vdisk_attributes = self._get_vdisk_attributes(vdisk_name)

        LOG.debug(
            'leave: _is_vdisk_defined: vdisk %(vol)s with %(str)s.',
            {'vol': vdisk_name, 'str': vdisk_attributes is not None})

        if vdisk_attributes is None:
            return False
        else:
            return True

    def _is_vdisk_copy_in_progress(self, vdisk_name):
        LOG.debug(
            '_is_vdisk_copy_in_progress: %(vdisk)s: %(vdisk_in_progress)s.',
            {'vdisk': vdisk_name,
             'vdisk_in_progress':
             six.text_type(self._vdisk_copy_in_progress)})
        if vdisk_name not in self._vdisk_copy_in_progress:
            LOG.debug(
                '_is_vdisk_copy_in_progress: '
                'vdisk copy is not in progress.')
            raise loopingcall.LoopingCallDone(retvalue=True)

    def _is_vdisk_map(self, vdisk_name, connector):
        """Check if vdisk is mapped.

        If map, return True and lun id.
        If not map, return False and expected lun id.

        """

        LOG.debug('enter: _is_vdisk_map: %(src)s.', {'src': vdisk_name})

        map_flag = False
        result_lun = '-1'

        host_name = self._get_host_from_connector(connector)
        if host_name is None:
            return (map_flag, int(result_lun))

        mapping_data = self._get_hostvdisk_mappings(host_name)

        if vdisk_name in mapping_data:
            map_flag = True
            result_lun = mapping_data[vdisk_name]['SCSI_id']
        else:
            lun_used = [int(v['SCSI_id']) for v in mapping_data.values()]
            lun_used.sort()

            # Start from 1 due to problems with lun id being 0.
            result_lun = 1
            for lun_id in lun_used:
                if result_lun < lun_id:
                    break
                elif result_lun == lun_id:
                    result_lun += 1

        LOG.debug(
            'leave: _is_vdisk_map: %(src)s '
            'mapped %(map_flag)s %(result_lun)s.',
            {'src': vdisk_name,
             'map_flag': six.text_type(map_flag),
             'result_lun': result_lun})

        return (map_flag, int(result_lun))

    def _log_cli_output_error(self, function, cmd, out, err):
        LOG.error('%(fun)s: Failed with unexpected CLI output.\n '
                  'Command: %(cmd)s\nstdout: %(out)s\nstderr: %(err)s\n',
                  {'fun': function,
                   'cmd': cmd,
                   'out': six.text_type(out),
                   'err': six.text_type(err)})

    def _manage_input_check(self, existing_ref):
        """Verify the input of manage function."""
        # Check that the reference is valid
        if 'source-name' in existing_ref:
            manage_source = existing_ref['source-name']
            vdisk = self._get_vdisk_attributes(manage_source)
        elif 'source-id' in existing_ref:
            manage_source = existing_ref['source-id']
            vdisk = self._get_vdisk_attributes(manage_source)
        else:
            reason = _('Reference must contain source-id or '
                       'source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        if vdisk is None:
            reason = (_('No vdisk with the ID specified by ref %s.')
                      % manage_source)
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        return vdisk

    def _cli_except(self, fun, cmd, out, err, exc_list):
        """Raise if stderr contains an unexpected error code"""
        if not err:
            return None
        if not isinstance(exc_list, (tuple, list)):
            exc_list = [exc_list]

        try:
            err_type = [e for e in exc_list
                        if err.startswith(e)].pop()
        except IndexError:
            msg = _(
                '%(fun)s: encountered unexpected CLI error, '
                'expected one of: %(errors)s'
            ) % {'fun': fun,
                 'errors': ', '.join(exc_list)}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return {'code': err_type, 'message': err.strip(err_type).strip()}

    @utils.synchronized('flashsystem-map', external=True)
    def _map_vdisk_to_host(self, vdisk_name, connector):
        """Create a mapping between a vdisk to a host."""

        LOG.debug(
            'enter: _map_vdisk_to_host: vdisk %(vdisk_name)s to '
            'host %(host)s.',
            {'vdisk_name': vdisk_name, 'host': connector})

        # Check if a host object is defined for this host name
        host_name = self._get_host_from_connector(connector)
        if host_name is None:
            # Host does not exist - add a new host to FlashSystem
            host_name = self._create_host(connector)
            # Verify that create_new_host succeeded
            self._driver_assert(
                host_name is not None,
                (_('_create_host failed to return the host name.')))

        (map_flag, result_lun) = self._is_vdisk_map(vdisk_name, connector)

        # Volume is not mapped to host, create a new LUN
        if not map_flag:
            ssh_cmd = ['svctask', 'mkvdiskhostmap', '-host', host_name,
                       '-scsi', six.text_type(result_lun), vdisk_name]
            out, err = self._ssh(ssh_cmd, check_exit_code=False)
            map_error = self._cli_except('_map_vdisk_to_host',
                                         ssh_cmd,
                                         out,
                                         err,
                                         self.MULTI_HOST_MAP_ERRORS)
            if map_error:
                if not self.configuration.flashsystem_multihostmap_enabled:
                    msg = _(
                        'flashsystem_multihostmap_enabled is set '
                        'to False, failing requested multi-host map. '
                        '(%(code)s %(message)s)'
                    ) % map_error
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

                for i in range(len(ssh_cmd)):
                    if ssh_cmd[i] == 'mkvdiskhostmap':
                        ssh_cmd.insert(i + 1, '-force')

                # try to map one volume to multiple hosts
                out, err = self._ssh(ssh_cmd)
                LOG.info('Volume %s is mapping to multiple hosts.',
                         vdisk_name)
                self._assert_ssh_return(
                    'successfully created' in out,
                    '_map_vdisk_to_host', ssh_cmd, out, err)
            else:
                self._assert_ssh_return(
                    'successfully created' in out,
                    '_map_vdisk_to_host', ssh_cmd, out, err)

        LOG.debug(
            ('leave: _map_vdisk_to_host: LUN %(result_lun)s, vdisk '
             '%(vdisk_name)s, host %(host_name)s.'),
            {'result_lun': result_lun,
             'vdisk_name': vdisk_name, 'host_name': host_name})

        return int(result_lun)

    def _port_conf_generator(self, cmd):
        ssh_cmd = cmd + ['-delim', '!']
        out, err = self._ssh(ssh_cmd)

        if not out.strip():
            return
        port_lines = out.strip().split('\n')
        if not port_lines:
            return

        header = port_lines.pop(0)
        yield header
        for portip_line in port_lines:
            try:
                port_data = self._get_hdr_dic(header, portip_line, '!')
            except exception.VolumeBackendAPIException:
                with excutils.save_and_reraise_exception():
                    self._log_cli_output_error('_port_conf_generator',
                                               ssh_cmd, out, err)
            yield port_data

    def _remove_device(self, properties, device):
        LOG.debug('enter: _remove_device')

        if not properties or not device:
            LOG.warning('_remove_device: invalid properties or device.')
            return

        use_multipath = self.configuration.use_multipath_for_image_xfer
        device_scan_attempts = self.configuration.num_volume_device_scan_tries
        protocol = properties['driver_volume_type']
        connector = volume_utils.brick_get_connector(
            protocol,
            use_multipath=use_multipath,
            device_scan_attempts=
            device_scan_attempts,
            conn=properties)

        connector.disconnect_volume(properties['data'], device)

        LOG.debug('leave: _remove_device')

    def _rename_vdisk(self, vdisk_name, new_name):
        """Rename vdisk"""
        # Try to rename volume only if found on the storage
        vdisk_defined = self._is_vdisk_defined(vdisk_name)
        if not vdisk_defined:
            LOG.warning('warning: Tried to rename vdisk %s but '
                        'it does not exist.', vdisk_name)
            return
        ssh_cmd = [
            'svctask', 'chvdisk', '-name', new_name, vdisk_name]
        out, err = self._ssh(ssh_cmd)
        # No output should be returned from chvdisk
        self._assert_ssh_return(
            (not out.strip()),
            '_rename_vdisk %(name)s' % {'name': vdisk_name},
            ssh_cmd, out, err)

        LOG.info('Renamed %(vdisk)s to %(newname)s .',
                 {'vdisk': vdisk_name, 'newname': new_name})

    def _scan_device(self, properties):
        LOG.debug('enter: _scan_device')

        use_multipath = self.configuration.use_multipath_for_image_xfer
        device_scan_attempts = self.configuration.num_volume_device_scan_tries
        protocol = properties['driver_volume_type']
        connector = volume_utils.brick_get_connector(
            protocol,
            use_multipath=use_multipath,
            device_scan_attempts=
            device_scan_attempts,
            conn=properties)
        device = connector.connect_volume(properties['data'])
        host_device = device['path']

        if not connector.check_valid_device(host_device):
            msg = (_('Unable to access the backend storage '
                     'via the path %(path)s.') % {'path': host_device})
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('leave: _scan_device')
        return device

    @utils.synchronized('flashsystem-unmap', external=True)
    def _unmap_vdisk_from_host(self, vdisk_name, connector):
        if 'host' in connector:
            host_name = self._get_host_from_connector(connector)
            self._driver_assert(
                host_name is not None,
                (_('_get_host_from_connector failed to return the host name '
                   'for connector.')))
        else:
            host_name = None

        # Check if vdisk-host mapping exists, remove if it does. If no host
        # name was given, but only one mapping exists, we can use that.
        mapping_data = self._get_vdiskhost_mappings(vdisk_name)
        if not mapping_data:
            LOG.warning('_unmap_vdisk_from_host: No mapping of volume '
                        '%(vol_name)s to any host found.',
                        {'vol_name': vdisk_name})
            return host_name
        if host_name is None:
            if len(mapping_data) > 1:
                LOG.warning('_unmap_vdisk_from_host: Multiple mappings of '
                            'volume %(vdisk_name)s found, no host '
                            'specified.',
                            {'vdisk_name': vdisk_name})
                return
            else:
                host_name = list(mapping_data.keys())[0]
        else:
            if host_name not in mapping_data:
                LOG.error('_unmap_vdisk_from_host: No mapping of volume '
                          '%(vol_name)s to host %(host_name)s found.',
                          {'vol_name': vdisk_name, 'host_name': host_name})
                return host_name

        # We have a valid host_name now
        ssh_cmd = ['svctask', 'rmvdiskhostmap',
                   '-host', host_name, vdisk_name]
        out, err = self._ssh(ssh_cmd)
        # Verify CLI behaviour - no output is returned from rmvdiskhostmap
        self._assert_ssh_return(
            (not out.strip()),
            '_unmap_vdisk_from_host', ssh_cmd, out, err)

        # If this host has no more mappings, delete it
        mapping_data = self._get_hostvdisk_mappings(host_name)
        if not mapping_data:
            self._delete_host(host_name)

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Updating volume stats.")

        data = {
            'vendor_name': 'IBM',
            'driver_version': self.VERSION,
            'storage_protocol': self._protocol,
            'total_capacity_gb': 0,
            'free_capacity_gb': 0,
            'reserved_percentage': self.configuration.reserved_percentage,
            'QoS_support': False,
            'multiattach': self.configuration.flashsystem_multihostmap_enabled,
        }

        pool = FLASHSYSTEM_VOLPOOL_NAME
        backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = '%s_%s' % (self._system_name, pool)
        data['volume_backend_name'] = backend_name

        ssh_cmd = ['svcinfo', 'lsmdiskgrp', '-bytes', '-delim', '!', pool]
        attributes = self._execute_command_and_parse_attributes(ssh_cmd)
        if not attributes:
            msg = _('_update_volume_stats: Could not get storage pool data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        data['total_capacity_gb'] = (
            float(attributes['capacity']) / units.Gi)
        data['free_capacity_gb'] = (
            float(attributes['free_capacity']) / units.Gi)
        data['easytier_support'] = False  # Do not support easy tier
        data['location_info'] = (
            'FlashSystemDriver:%(sys_id)s:%(pool)s'
            % {'sys_id': self._system_id, 'pool': pool})

        self._stats = data

    def _set_vdisk_copy_in_progress(self, vdisk_list):
        LOG.debug(
            '_set_vdisk_copy_in_progress: %(vdisk)s: %(vdisk_in_progress)s.',
            {'vdisk': six.text_type(vdisk_list),
             'vdisk_in_progress':
             six.text_type(self._vdisk_copy_in_progress)})
        get_lock = True
        self._vdisk_copy_lock.acquire()
        for vdisk in vdisk_list:
            if vdisk in self._vdisk_copy_in_progress:
                get_lock = False
                break
        if get_lock:
            self._vdisk_copy_in_progress.update(vdisk_list)
        self._vdisk_copy_lock.release()
        if get_lock:
            LOG.debug(
                '_set_vdisk_copy_in_progress: %s.',
                six.text_type(self._vdisk_copy_in_progress))
            raise loopingcall.LoopingCallDone(retvalue=True)

    def _unset_vdisk_copy_in_progress(self, vdisk_list):
        LOG.debug(
            '_unset_vdisk_copy_in_progress: %(vdisk)s: %(vdisk_in_progress)s.',
            {'vdisk': six.text_type(vdisk_list),
             'vdisk_in_progress':
             six.text_type(self._vdisk_copy_in_progress)})
        self._vdisk_copy_lock.acquire()
        for vdisk in vdisk_list:
            if vdisk in self._vdisk_copy_in_progress:
                self._vdisk_copy_in_progress.remove(vdisk)
        self._vdisk_copy_lock.release()

    def _wait_vdisk_copy_completed(self, vdisk_name):
        timer = loopingcall.FixedIntervalLoopingCall(
            self._is_vdisk_copy_in_progress, vdisk_name)
        timer.start(interval=self._check_lock_interval).wait()

    def check_for_setup_error(self):
        """Ensure that the flags are set properly."""
        LOG.debug('enter: check_for_setup_error')

        # Check that we have the system ID information
        if self._system_name is None:
            msg = (
                _('check_for_setup_error: Unable to determine system name.'))
            raise exception.VolumeBackendAPIException(data=msg)
        if self._system_id is None:
            msg = _('check_for_setup_error: Unable to determine system id.')
            raise exception.VolumeBackendAPIException(data=msg)

        required_flags = ['san_ip', 'san_ssh_port', 'san_login']
        for flag in required_flags:
            if not self.configuration.safe_get(flag):
                msg = (_('%s is not set.') % flag)
                raise exception.InvalidInput(reason=msg)

        # Ensure that either password or keyfile were set
        if not (self.configuration.san_password or
                self.configuration.san_private_key):
            msg = _('check_for_setup_error: Password or SSH private key '
                    'is required for authentication: set either '
                    'san_password or san_private_key option.')
            raise exception.InvalidInput(reason=msg)

        params = self._build_default_params()
        self._check_vdisk_params(params)

        LOG.debug('leave: check_for_setup_error')

    def create_volume(self, volume):
        """Create volume."""
        vdisk_name = volume['name']
        vdisk_params = self._get_vdisk_params(volume['volume_type_id'])
        vdisk_size = six.text_type(volume['size'])
        return self._create_vdisk(vdisk_name, vdisk_size, 'gb', vdisk_params)

    def delete_volume(self, volume):
        """Delete volume."""
        vdisk_name = volume['name']
        self._wait_vdisk_copy_completed(vdisk_name)
        self._delete_vdisk(vdisk_name, False)

    def extend_volume(self, volume, new_size):
        """Extend volume."""
        LOG.debug('enter: extend_volume: volume %s.', volume['name'])

        vdisk_name = volume['name']
        self._wait_vdisk_copy_completed(vdisk_name)

        extend_amt = int(new_size) - volume['size']
        ssh_cmd = (['svctask', 'expandvdisksize', '-size',
                   six.text_type(extend_amt), '-unit', 'gb', vdisk_name])
        out, err = self._ssh(ssh_cmd)
        # No output should be returned from expandvdisksize
        self._assert_ssh_return(
            (not out.strip()),
            'extend_volume', ssh_cmd, out, err)

        LOG.debug('leave: extend_volume: volume %s.', volume['name'])

    def create_snapshot(self, snapshot):
        """Create snapshot from volume."""

        LOG.debug(
            'enter: create_snapshot: create %(snap)s from %(vol)s.',
            {'snap': snapshot['name'], 'vol': snapshot['volume']['name']})

        status = snapshot['volume']['status']
        if status not in ['available', 'in-use']:
            msg = (_(
                'create_snapshot: Volume status must be "available" or '
                '"in-use" for snapshot. The invalid status is %s.') % status)
            raise exception.InvalidVolume(msg)

        self._create_and_copy_vdisk_data(snapshot['volume']['name'],
                                         snapshot['volume']['id'],
                                         snapshot['name'],
                                         snapshot['id'])

        LOG.debug(
            'leave: create_snapshot: create %(snap)s from %(vol)s.',
            {'snap': snapshot['name'], 'vol': snapshot['volume']['name']})

    def delete_snapshot(self, snapshot):
        """Delete snapshot."""

        LOG.debug(
            'enter: delete_snapshot: delete %(snap)s.',
            {'snap': snapshot['name']})

        self._wait_vdisk_copy_completed(snapshot['name'])

        self._delete_vdisk(snapshot['name'], False)

        LOG.debug(
            'leave: delete_snapshot: delete %(snap)s.',
            {'snap': snapshot['name']})

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create volume from snapshot."""

        LOG.debug(
            'enter: create_volume_from_snapshot: create %(vol)s from '
            '%(snap)s.', {'vol': volume['name'], 'snap': snapshot['name']})

        if volume['size'] < snapshot['volume_size']:
            msg = _('create_volume_from_snapshot: Volume is smaller than '
                    'snapshot.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        status = snapshot['status']
        if status != 'available':
            msg = (_('create_volume_from_snapshot: Snapshot status '
                     'must be "available" for creating volume. '
                     'The invalid status is: %s.') % status)
            raise exception.InvalidSnapshot(msg)

        self._create_and_copy_vdisk_data(
            snapshot['name'],
            snapshot['id'],
            volume['name'],
            volume['id'],
            dest_vdisk_size=volume['size'] * units.Gi
        )

        LOG.debug(
            'leave: create_volume_from_snapshot: create %(vol)s from '
            '%(snap)s.', {'vol': volume['name'], 'snap': snapshot['name']})

    def create_cloned_volume(self, volume, src_volume):
        """Create volume from a source volume."""

        LOG.debug('enter: create_cloned_volume: create %(vol)s from %(src)s.',
                  {'src': src_volume['name'], 'vol': volume['name']})

        if src_volume['size'] > volume['size']:
            msg = _('create_cloned_volume: Source volume larger than '
                    'destination volume')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        self._create_and_copy_vdisk_data(
            src_volume['name'],
            src_volume['id'],
            volume['name'],
            volume['id'],
            dest_vdisk_size=volume['size'] * units.Gi
        )

        LOG.debug('leave: create_cloned_volume: create %(vol)s from %(src)s.',
                  {'src': src_volume['name'], 'vol': volume['name']})

    def manage_existing(self, volume, existing_ref):
        """Manages an existing vdisk.

        Renames the vdisk to match the expected name for the volume.
        """
        LOG.debug('enter: manage_existing: volume %(vol)s ref %(ref)s.',
                  {'vol': volume, 'ref': existing_ref})
        vdisk = self._manage_input_check(existing_ref)
        new_name = 'volume-' + volume['id']
        self._rename_vdisk(vdisk['name'], new_name)
        LOG.debug('leave: manage_existing: volume %(vol)s ref %(ref)s.',
                  {'vol': volume, 'ref': existing_ref})
        return

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing."""
        vdisk = self._manage_input_check(existing_ref)
        if self._get_vdiskhost_mappings(vdisk['name']):
            reason = _('The specified vdisk is mapped to a host.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        return int(vdisk['capacity']) / units.Gi

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management."""
        LOG.debug('unmanage: volume %(vol)s is no longer managed by cinder.',
                  {'vol': volume})
