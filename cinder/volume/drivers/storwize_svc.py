# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
# Copyright 2012 OpenStack LLC.
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
# Authors:
#   Ronen Kat <ronenkat@il.ibm.com>
#   Avishay Traeger <avishay@il.ibm.com>

"""
Volume driver for IBM Storwize family and SVC storage systems.

Notes:
1. If you specify both a password and a key file, this driver will use the
   key file only.
2. When using a key file for authentication, it is up to the user or
   system administrator to store the private key in a safe manner.
3. The defaults for creating volumes are "-rsize 2% -autoexpand
   -grainsize 256 -warning 0".  These can be changed in the configuration
   file or by using volume types(recommended only for advanced users).

Limitations:
1. The driver expects CLI output in English, error messages may be in a
   localized format.
2. Clones and creating volumes from snapshots, where the source and target
   are of different sizes, is not supported.

"""

import random
import re
import string
import time

from oslo.config import cfg

from cinder import context
from cinder import exception
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import strutils
from cinder import utils
from cinder.volume.drivers.san import san
from cinder.volume import volume_types

VERSION = 1.1
LOG = logging.getLogger(__name__)

storwize_svc_opts = [
    cfg.StrOpt('storwize_svc_volpool_name',
               default='volpool',
               help='Storage system storage pool for volumes'),
    cfg.IntOpt('storwize_svc_vol_rsize',
               default=2,
               help='Storage system space-efficiency parameter for volumes '
                    '(percentage)'),
    cfg.IntOpt('storwize_svc_vol_warning',
               default=0,
               help='Storage system threshold for volume capacity warnings '
                    '(percentage)'),
    cfg.BoolOpt('storwize_svc_vol_autoexpand',
                default=True,
                help='Storage system autoexpand parameter for volumes '
                     '(True/False)'),
    cfg.IntOpt('storwize_svc_vol_grainsize',
               default=256,
               help='Storage system grain size parameter for volumes '
                    '(32/64/128/256)'),
    cfg.BoolOpt('storwize_svc_vol_compression',
                default=False,
                help='Storage system compression option for volumes'),
    cfg.BoolOpt('storwize_svc_vol_easytier',
                default=True,
                help='Enable Easy Tier for volumes'),
    cfg.IntOpt('storwize_svc_flashcopy_timeout',
               default=120,
               help='Maximum number of seconds to wait for FlashCopy to be '
                    'prepared. Maximum value is 600 seconds (10 minutes).'),
    cfg.StrOpt('storwize_svc_connection_protocol',
               default='iSCSI',
               help='Connection protocol (iSCSI/FC)'),
    cfg.BoolOpt('storwize_svc_multipath_enabled',
                default=False,
                help='Connect with multipath (currently FC-only)'),
    cfg.BoolOpt('storwize_svc_multihostmap_enabled',
                default=True,
                help='Allows vdisk to multi host mapping'),
]


class StorwizeSVCDriver(san.SanISCSIDriver):
    """IBM Storwize V7000 and SVC iSCSI/FC volume driver.

    Version history:
    1.0 - Initial driver
    1.1 - FC support, create_cloned_volume, volume type support,
          get_volume_stats, minor bug fixes

    """

    """====================================================================="""
    """ SETUP                                                               """
    """====================================================================="""

    def __init__(self, *args, **kwargs):
        super(StorwizeSVCDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(storwize_svc_opts)
        self._storage_nodes = {}
        self._enabled_protocols = set()
        self._compression_enabled = False
        self._context = None

        # Build cleanup translation tables for host names
        invalid_ch_in_host = ''
        for num in range(0, 128):
            ch = str(chr(num))
            if (not ch.isalnum() and ch != ' ' and ch != '.'
                and ch != '-' and ch != '_'):
                invalid_ch_in_host = invalid_ch_in_host + ch
        self._string_host_name_filter = string.maketrans(
            invalid_ch_in_host, '-' * len(invalid_ch_in_host))

        self._unicode_host_name_filter = dict((ord(unicode(char)), u'-')
                                              for char in invalid_ch_in_host)

    def _get_iscsi_ip_addrs(self):
        generator = self._port_conf_generator('svcinfo lsportip')
        header = next(generator, None)
        if not header:
            return

        for port_data in generator:
            try:
                port_node_id = port_data['node_id']
                port_ipv4 = port_data['IP_address']
                port_ipv6 = port_data['IP_address_6']
                state = port_data['state']
            except KeyError:
                self._handle_keyerror('lsportip', header)

            if port_node_id in self._storage_nodes and (
                    state == 'configured' or state == 'online'):
                node = self._storage_nodes[port_node_id]
                if len(port_ipv4):
                    node['ipv4'].append(port_ipv4)
                if len(port_ipv6):
                    node['ipv6'].append(port_ipv6)

    def _get_fc_wwpns(self):
        for key in self._storage_nodes:
            node = self._storage_nodes[key]
            ssh_cmd = 'svcinfo lsnode -delim ! %s' % node['id']
            raw = self._run_ssh(ssh_cmd)
            resp = CLIResponse(raw, delim='!', with_header=False)
            wwpns = set(node['WWPN'])
            for i, s in resp.select('port_id', 'port_status'):
                if 'unconfigured' != s:
                    wwpns.add(i)
            node['WWPN'] = list(wwpns)
            LOG.info(_('WWPN on node %(node)s: %(wwpn)s')
                     % {'node': node['id'], 'wwpn': node['WWPN']})

    def do_setup(self, ctxt):
        """Check that we have all configuration details from the storage."""

        LOG.debug(_('enter: do_setup'))
        self._context = ctxt

        # Validate that the pool exists
        ssh_cmd = 'svcinfo lsmdiskgrp -delim ! -nohdr'
        out, err = self._run_ssh(ssh_cmd)
        self._assert_ssh_return(len(out.strip()), 'do_setup',
                                ssh_cmd, out, err)
        search_text = '!%s!' % self.configuration.storwize_svc_volpool_name
        if search_text not in out:
            raise exception.InvalidInput(
                reason=(_('pool %s doesn\'t exist')
                        % self.configuration.storwize_svc_volpool_name))

        # Check if compression is supported
        self._compression_enabled = False
        try:
            ssh_cmd = 'svcinfo lslicense -delim !'
            out, err = self._run_ssh(ssh_cmd)
            license_lines = out.strip().split('\n')
            for license_line in license_lines:
                name, foo, value = license_line.partition('!')
                if name in ('license_compression_enclosures',
                            'license_compression_capacity') and value != '0':
                    self._compression_enabled = True
                    break
        except exception.ProcessExecutionError:
            LOG.exception(_('Failed to get license information.'))

        # Get the iSCSI and FC names of the Storwize/SVC nodes
        ssh_cmd = 'svcinfo lsnode -delim !'
        out, err = self._run_ssh(ssh_cmd)
        self._assert_ssh_return(len(out.strip()), 'do_setup',
                                ssh_cmd, out, err)

        nodes = out.strip().split('\n')
        self._assert_ssh_return(len(nodes),
                                'do_setup', ssh_cmd, out, err)
        header = nodes.pop(0)
        for node_line in nodes:
            try:
                node_data = self._get_hdr_dic(header, node_line, '!')
            except exception.VolumeBackendAPIException:
                with excutils.save_and_reraise_exception():
                    self._log_cli_output_error('do_setup',
                                               ssh_cmd, out, err)
            node = {}
            try:
                node['id'] = node_data['id']
                node['name'] = node_data['name']
                node['IO_group'] = node_data['IO_group_id']
                node['iscsi_name'] = node_data['iscsi_name']
                node['WWNN'] = node_data['WWNN']
                node['status'] = node_data['status']
                node['WWPN'] = []
                node['ipv4'] = []
                node['ipv6'] = []
                node['enabled_protocols'] = []
                if node['status'] == 'online':
                    self._storage_nodes[node['id']] = node
            except KeyError:
                self._handle_keyerror('lsnode', header)

        # Get the iSCSI IP addresses and WWPNs of the Storwize/SVC nodes
        self._get_iscsi_ip_addrs()
        self._get_fc_wwpns()

        # For each node, check what connection modes it supports.  Delete any
        # nodes that do not support any types (may be partially configured).
        to_delete = []
        for k, node in self._storage_nodes.iteritems():
            if ((len(node['ipv4']) or len(node['ipv6']))
                    and len(node['iscsi_name'])):
                node['enabled_protocols'].append('iSCSI')
                self._enabled_protocols.add('iSCSI')
            if len(node['WWPN']):
                node['enabled_protocols'].append('FC')
                self._enabled_protocols.add('FC')
            if not len(node['enabled_protocols']):
                to_delete.append(k)

        for delkey in to_delete:
            del self._storage_nodes[delkey]

        # Make sure we have at least one node configured
        self._driver_assert(len(self._storage_nodes),
                            _('do_setup: No configured nodes'))

        LOG.debug(_('leave: do_setup'))

    def _build_default_opts(self):
        # Ignore capitalization
        protocol = self.configuration.storwize_svc_connection_protocol
        if protocol.lower() == 'fc':
            protocol = 'FC'
        elif protocol.lower() == 'iscsi':
            protocol = 'iSCSI'

        opt = {'rsize': self.configuration.storwize_svc_vol_rsize,
               'warning': self.configuration.storwize_svc_vol_warning,
               'autoexpand': self.configuration.storwize_svc_vol_autoexpand,
               'grainsize': self.configuration.storwize_svc_vol_grainsize,
               'compression': self.configuration.storwize_svc_vol_compression,
               'easytier': self.configuration.storwize_svc_vol_easytier,
               'protocol': protocol,
               'multipath': self.configuration.storwize_svc_multipath_enabled}
        return opt

    def check_for_setup_error(self):
        """Ensure that the flags are set properly."""
        LOG.debug(_('enter: check_for_setup_error'))

        required_flags = ['san_ip', 'san_ssh_port', 'san_login',
                          'storwize_svc_volpool_name']
        for flag in required_flags:
            if not self.configuration.safe_get(flag):
                raise exception.InvalidInput(reason=_('%s is not set') % flag)

        # Ensure that either password or keyfile were set
        if not (self.configuration.san_password or
                self.configuration.san_private_key):
            raise exception.InvalidInput(
                reason=_('Password or SSH private key is required for '
                         'authentication: set either san_password or '
                         'san_private_key option'))

        # Check that flashcopy_timeout is not more than 10 minutes
        flashcopy_timeout = self.configuration.storwize_svc_flashcopy_timeout
        if not (flashcopy_timeout > 0 and flashcopy_timeout <= 600):
            raise exception.InvalidInput(
                reason=_('Illegal value %d specified for '
                         'storwize_svc_flashcopy_timeout: '
                         'valid values are between 0 and 600')
                % flashcopy_timeout)

        opts = self._build_default_opts()
        self._check_vdisk_opts(opts)

        LOG.debug(_('leave: check_for_setup_error'))

    """====================================================================="""
    """ INITIALIZE/TERMINATE CONNECTIONS                                    """
    """====================================================================="""

    def ensure_export(self, ctxt, volume):
        """Check that the volume exists on the storage.

        The system does not "export" volumes as a Linux iSCSI target does,
        and therefore we just check that the volume exists on the storage.
        """
        volume_defined = self._is_vdisk_defined(volume['name'])
        if not volume_defined:
            LOG.error(_('ensure_export: Volume %s not found on storage')
                      % volume['name'])

    def create_export(self, ctxt, volume):
        model_update = None
        return model_update

    def remove_export(self, ctxt, volume):
        pass

    def _add_chapsecret_to_host(self, host_name):
        """Generate and store a randomly-generated CHAP secret for the host."""

        chap_secret = utils.generate_password()
        ssh_cmd = ('svctask chhost -chapsecret "%(chap_secret)s" %(host_name)s'
                   % {'chap_secret': chap_secret, 'host_name': host_name})
        out, err = self._run_ssh(ssh_cmd)
        # No output should be returned from chhost
        self._assert_ssh_return(len(out.strip()) == 0,
                                '_add_chapsecret_to_host', ssh_cmd, out, err)
        return chap_secret

    def _get_chap_secret_for_host(self, host_name):
        """Return the CHAP secret for the given host."""

        LOG.debug(_('enter: _get_chap_secret_for_host: host name %s')
                  % host_name)

        ssh_cmd = 'svcinfo lsiscsiauth -delim !'
        out, err = self._run_ssh(ssh_cmd)

        if not len(out.strip()):
            return None

        host_lines = out.strip().split('\n')
        self._assert_ssh_return(len(host_lines), '_get_chap_secret_for_host',
                                ssh_cmd, out, err)

        header = host_lines.pop(0).split('!')
        self._assert_ssh_return('name' in header, '_get_chap_secret_for_host',
                                ssh_cmd, out, err)
        self._assert_ssh_return('iscsi_auth_method' in header,
                                '_get_chap_secret_for_host', ssh_cmd, out, err)
        self._assert_ssh_return('iscsi_chap_secret' in header,
                                '_get_chap_secret_for_host', ssh_cmd, out, err)
        name_index = header.index('name')
        method_index = header.index('iscsi_auth_method')
        secret_index = header.index('iscsi_chap_secret')

        chap_secret = None
        host_found = False
        for line in host_lines:
            info = line.split('!')
            if info[name_index] == host_name:
                host_found = True
                if info[method_index] == 'chap':
                    chap_secret = info[secret_index]

        self._assert_ssh_return(host_found, '_get_chap_secret_for_host',
                                ssh_cmd, out, err)

        LOG.debug(_('leave: _get_chap_secret_for_host: host name '
                    '%(host_name)s with secret %(chap_secret)s')
                  % {'host_name': host_name, 'chap_secret': chap_secret})

        return chap_secret

    def _connector_to_hostname_prefix(self, connector):
        """Translate connector info to storage system host name.

        Translate a host's name and IP to the prefix of its hostname on the
        storage subsystem.  We create a host name host name from the host and
        IP address, replacing any invalid characters (at most 55 characters),
        and adding a random 8-character suffix to avoid collisions. The total
        length should be at most 63 characters.

        """

        host_name = connector['host']
        if isinstance(host_name, unicode):
            host_name = host_name.translate(self._unicode_host_name_filter)
        elif isinstance(host_name, str):
            host_name = host_name.translate(self._string_host_name_filter)
        else:
            msg = _('_create_host: Cannot clean host name. Host name '
                    'is not unicode or string')
            LOG.error(msg)
            raise exception.NoValidHost(reason=msg)

        host_name = str(host_name)
        return host_name[:55]

    def _find_host_from_wwpn(self, connector):
        for wwpn in connector['wwpns']:
            ssh_cmd = 'svcinfo lsfabric -wwpn %s -delim !' % wwpn
            out, err = self._run_ssh(ssh_cmd)

            if not len(out.strip()):
                # This WWPN is not in use
                continue

            host_lines = out.strip().split('\n')
            header = host_lines.pop(0).split('!')
            self._assert_ssh_return('remote_wwpn' in header and
                                    'name' in header,
                                    '_find_host_from_wwpn',
                                    ssh_cmd, out, err)
            rmt_wwpn_idx = header.index('remote_wwpn')
            name_idx = header.index('name')

            wwpns = map(lambda x: x.split('!')[rmt_wwpn_idx], host_lines)

            if wwpn in wwpns:
                # All the wwpns will be the mapping for the same
                # host from this WWPN-based query. Just pick
                # the name from first line.
                hostname = host_lines[0].split('!')[name_idx]
                return hostname

        # Didn't find a host
        return None

    def _find_host_exhaustive(self, connector, hosts):
        for host in hosts:
            ssh_cmd = 'svcinfo lshost -delim ! %s' % host
            out, err = self._run_ssh(ssh_cmd)
            self._assert_ssh_return(len(out.strip()),
                                    '_find_host_exhaustive',
                                    ssh_cmd, out, err)
            for attr_line in out.split('\n'):
                # If '!' not found, return the string and two empty strings
                attr_name, foo, attr_val = attr_line.partition('!')
                if (attr_name == 'iscsi_name' and
                    'initiator' in connector and
                    attr_val == connector['initiator']):
                        return host
                elif (attr_name == 'WWPN' and
                      'wwpns' in connector and
                      attr_val.lower() in
                      map(str.lower, map(str, connector['wwpns']))):
                        return host
        return None

    def _get_host_from_connector(self, connector):
        """List the hosts defined in the storage.

        Return the host name with the given connection info, or None if there
        is no host fitting that information.

        """

        prefix = self._connector_to_hostname_prefix(connector)
        LOG.debug(_('enter: _get_host_from_connector: prefix %s') % prefix)

        # Get list of host in the storage
        ssh_cmd = 'svcinfo lshost -delim !'
        out, err = self._run_ssh(ssh_cmd)

        if not len(out.strip()):
            return None

        # If we have FC information, we have a faster lookup option
        hostname = None
        if 'wwpns' in connector:
            hostname = self._find_host_from_wwpn(connector)

        # If we don't have a hostname yet, try the long way
        if not hostname:
            host_lines = out.strip().split('\n')
            self._assert_ssh_return(len(host_lines),
                                    '_get_host_from_connector',
                                    ssh_cmd, out, err)
            header = host_lines.pop(0).split('!')
            self._assert_ssh_return('name' in header,
                                    '_get_host_from_connector',
                                    ssh_cmd, out, err)
            name_index = header.index('name')
            hosts = map(lambda x: x.split('!')[name_index], host_lines)
            hostname = self._find_host_exhaustive(connector, hosts)

        LOG.debug(_('leave: _get_host_from_connector: host %s') % hostname)

        return hostname

    def _create_host(self, connector):
        """Create a new host on the storage system.

        We create a host name and associate it with the given connection
        information.

        """

        LOG.debug(_('enter: _create_host: host %s') % connector['host'])

        rand_id = str(random.randint(0, 99999999)).zfill(8)
        host_name = '%s-%s' % (self._connector_to_hostname_prefix(connector),
                               rand_id)

        # Get all port information from the connector
        ports = []
        if 'initiator' in connector:
            ports.append('-iscsiname %s' % connector['initiator'])
        if 'wwpns' in connector:
            for wwpn in connector['wwpns']:
                ports.append('-hbawwpn %s' % wwpn)

        # When creating a host, we need one port
        self._driver_assert(len(ports), _('_create_host: No connector ports'))
        port1 = ports.pop(0)
        ssh_cmd = ('svctask mkhost -force %(port1)s -name "%(host_name)s"' %
                   {'port1': port1, 'host_name': host_name})
        out, err = self._run_ssh(ssh_cmd)
        self._assert_ssh_return('successfully created' in out,
                                '_create_host', ssh_cmd, out, err)

        # Add any additional ports to the host
        for port in ports:
            ssh_cmd = ('svctask addhostport -force %s %s' % (port, host_name))
            out, err = self._run_ssh(ssh_cmd)

        LOG.debug(_('leave: _create_host: host %(host)s - %(host_name)s') %
                  {'host': connector['host'], 'host_name': host_name})
        return host_name

    def _get_hostvdisk_mappings(self, host_name):
        """Return the defined storage mappings for a host."""

        return_data = {}
        ssh_cmd = 'svcinfo lshostvdiskmap -delim ! %s' % host_name
        out, err = self._run_ssh(ssh_cmd)

        mappings = out.strip().split('\n')
        if len(mappings):
            header = mappings.pop(0)
            for mapping_line in mappings:
                mapping_data = self._get_hdr_dic(header, mapping_line, '!')
                return_data[mapping_data['vdisk_name']] = mapping_data

        return return_data

    def _map_vol_to_host(self, volume_name, host_name):
        """Create a mapping between a volume to a host."""

        LOG.debug(_('enter: _map_vol_to_host: volume %(volume_name)s to '
                    'host %(host_name)s')
                  % {'volume_name': volume_name, 'host_name': host_name})

        # Check if this volume is already mapped to this host
        mapping_data = self._get_hostvdisk_mappings(host_name)

        mapped_flag = False
        result_lun = '-1'
        if volume_name in mapping_data:
            mapped_flag = True
            result_lun = mapping_data[volume_name]['SCSI_id']
        else:
            lun_used = []
            for k, v in mapping_data.iteritems():
                lun_used.append(int(v['SCSI_id']))
            lun_used.sort()
            # Assume all luns are taken to this point, and then try to find
            # an unused one
            result_lun = str(len(lun_used))
            for index, n in enumerate(lun_used):
                if n > index:
                    result_lun = str(index)
                    break

        # Volume is not mapped to host, create a new LUN
        if not mapped_flag:
            ssh_cmd = ('svctask mkvdiskhostmap -host %(host_name)s -scsi '
                       '%(result_lun)s %(volume_name)s' %
                       {'host_name': host_name,
                        'result_lun': result_lun,
                        'volume_name': volume_name})
            out, err = self._run_ssh(ssh_cmd, check_exit_code=False)
            if err and err.startswith('CMMVC6071E'):
                if not self.configuration.storwize_svc_multihostmap_enabled:
                    LOG.error(_('storwize_svc_multihostmap_enabled is set '
                                'to Flase, Not allow multi host mapping'))
                    exception_msg = 'CMMVC6071E The VDisk-to-host mapping '\
                                    'was not created because the VDisk is '\
                                    'already mapped to a host.\n"'
                    raise exception.CinderException(data=exception_msg)
                ssh_cmd = ssh_cmd.replace('mkvdiskhostmap',
                                          'mkvdiskhostmap -force')
                # try to map one volume to multiple hosts
                out, err = self._run_ssh(ssh_cmd)
                LOG.warn(_('volume %s mapping to multi host') % volume_name)
                self._assert_ssh_return('successfully created' in out,
                                        '_map_vol_to_host', ssh_cmd, out, err)
            else:
                self._assert_ssh_return('successfully created' in out,
                                        '_map_vol_to_host', ssh_cmd, out, err)
        LOG.debug(_('leave: _map_vol_to_host: LUN %(result_lun)s, volume '
                    '%(volume_name)s, host %(host_name)s') %
                  {'result_lun': result_lun,
                   'volume_name': volume_name,
                   'host_name': host_name})
        return result_lun

    def _delete_host(self, host_name):
        """Delete a host on the storage system."""

        LOG.debug(_('enter: _delete_host: host %s ') % host_name)

        ssh_cmd = 'svctask rmhost %s ' % host_name
        out, err = self._run_ssh(ssh_cmd)
        # No output should be returned from rmhost
        self._assert_ssh_return(len(out.strip()) == 0,
                                '_delete_host', ssh_cmd, out, err)

        LOG.debug(_('leave: _delete_host: host %s ') % host_name)

    def _get_conn_fc_wwpns(self, host_name):
        wwpns = []
        cmd = 'svcinfo lsfabric -host %s' % host_name
        generator = self._port_conf_generator(cmd)
        header = next(generator, None)
        if not header:
            return wwpns

        for port_data in generator:
            try:
                wwpns.append(port_data['local_wwpn'])
            except KeyError as e:
                self._handle_keyerror('lsfabric', header)

        return wwpns

    def initialize_connection(self, volume, connector):
        """Perform the necessary work so that an iSCSI/FC connection can
        be made.

        To be able to create an iSCSI/FC connection from a given host to a
        volume, we must:
        1. Translate the given iSCSI name or WWNN to a host name
        2. Create new host on the storage system if it does not yet exist
        3. Map the volume to the host if it is not already done
        4. Return the connection information for relevant nodes (in the
           proper I/O group)

        """

        LOG.debug(_('enter: initialize_connection: volume %(vol)s with '
                    'connector %(conn)s') % {'vol': str(volume),
                                             'conn': str(connector)})

        vol_opts = self._get_vdisk_params(volume['volume_type_id'])
        host_name = connector['host']
        volume_name = volume['name']

        # Check if a host object is defined for this host name
        host_name = self._get_host_from_connector(connector)
        if host_name is None:
            # Host does not exist - add a new host to Storwize/SVC
            host_name = self._create_host(connector)
            # Verify that create_new_host succeeded
            self._driver_assert(
                host_name is not None,
                _('_create_host failed to return the host name.'))

        if vol_opts['protocol'] == 'iSCSI':
            chap_secret = self._get_chap_secret_for_host(host_name)
            if chap_secret is None:
                chap_secret = self._add_chapsecret_to_host(host_name)

        volume_attributes = self._get_vdisk_attributes(volume_name)
        lun_id = self._map_vol_to_host(volume_name, host_name)

        self._driver_assert(volume_attributes is not None,
                            _('initialize_connection: Failed to get attributes'
                              ' for volume %s') % volume_name)

        try:
            preferred_node = volume_attributes['preferred_node_id']
            IO_group = volume_attributes['IO_group_id']
        except KeyError as e:
                LOG.error(_('Did not find expected column name in '
                            'lsvdisk: %s') % str(e))
                exception_msg = (_('initialize_connection: Missing volume '
                                   'attribute for volume %s') % volume_name)
                raise exception.VolumeBackendAPIException(data=exception_msg)

        try:
            # Get preferred node and other nodes in I/O group
            preferred_node_entry = None
            io_group_nodes = []
            for k, node in self._storage_nodes.iteritems():
                if vol_opts['protocol'] not in node['enabled_protocols']:
                    continue
                if node['id'] == preferred_node:
                    preferred_node_entry = node
                if node['IO_group'] == IO_group:
                    io_group_nodes.append(node)

            if not len(io_group_nodes):
                exception_msg = (_('initialize_connection: No node found in '
                                   'I/O group %(gid)s for volume %(vol)s') %
                                 {'gid': IO_group, 'vol': volume_name})
                raise exception.VolumeBackendAPIException(data=exception_msg)

            if not preferred_node_entry and not vol_opts['multipath']:
                # Get 1st node in I/O group
                preferred_node_entry = io_group_nodes[0]
                LOG.warn(_('initialize_connection: Did not find a preferred '
                           'node for volume %s') % volume_name)

            properties = {}
            properties['target_discovered'] = False
            properties['target_lun'] = lun_id
            properties['volume_id'] = volume['id']
            if vol_opts['protocol'] == 'iSCSI':
                type_str = 'iscsi'
                # We take the first IP address for now. Ideally, OpenStack will
                # support iSCSI multipath for improved performance.
                if len(preferred_node_entry['ipv4']):
                    ipaddr = preferred_node_entry['ipv4'][0]
                else:
                    ipaddr = preferred_node_entry['ipv6'][0]
                properties['target_portal'] = '%s:%s' % (ipaddr, '3260')
                properties['target_iqn'] = preferred_node_entry['iscsi_name']
                properties['auth_method'] = 'CHAP'
                properties['auth_username'] = connector['initiator']
                properties['auth_password'] = chap_secret
            else:
                type_str = 'fibre_channel'
                conn_wwpns = self._get_conn_fc_wwpns(host_name)
                if not vol_opts['multipath']:
                    if preferred_node_entry['WWPN'] in conn_wwpns:
                        properties['target_wwn'] = preferred_node_entry['WWPN']
                    else:
                        properties['target_wwn'] = conn_wwpns[0]
                else:
                    properties['target_wwn'] = conn_wwpns
        except Exception:
            with excutils.save_and_reraise_exception():
                self.terminate_connection(volume, connector)
                LOG.error(_('initialize_connection: Failed to collect return '
                            'properties for volume %(vol)s and connector '
                            '%(conn)s.\n') % {'vol': str(volume),
                                              'conn': str(connector)})

        LOG.debug(_('leave: initialize_connection:\n volume: %(vol)s\n '
                    'connector %(conn)s\n properties: %(prop)s')
                  % {'vol': str(volume),
                     'conn': str(connector),
                     'prop': str(properties)})

        return {'driver_volume_type': type_str, 'data': properties, }

    def terminate_connection(self, volume, connector, **kwargs):
        """Cleanup after an iSCSI connection has been terminated.

        When we clean up a terminated connection between a given connector
        and volume, we:
        1. Translate the given connector to a host name
        2. Remove the volume-to-host mapping if it exists
        3. Delete the host if it has no more mappings (hosts are created
           automatically by this driver when mappings are created)
        """
        LOG.debug(_('enter: terminate_connection: volume %(vol)s with '
                    'connector %(conn)s') % {'vol': str(volume),
                                             'conn': str(connector)})

        vol_name = volume['name']
        host_name = self._get_host_from_connector(connector)
        # Verify that _get_host_from_connector returned the host.
        # This should always succeed as we terminate an existing connection.
        self._driver_assert(
            host_name is not None,
            _('_get_host_from_connector failed to return the host name '
              'for connector'))

        # Check if vdisk-host mapping exists, remove if it does
        mapping_data = self._get_hostvdisk_mappings(host_name)
        if vol_name in mapping_data:
            ssh_cmd = 'svctask rmvdiskhostmap -host %s %s' % \
                (host_name, vol_name)
            out, err = self._run_ssh(ssh_cmd)
            # Verify CLI behaviour - no output is returned from
            # rmvdiskhostmap
            self._assert_ssh_return(len(out.strip()) == 0,
                                    'terminate_connection', ssh_cmd, out, err)
            del mapping_data[vol_name]
        else:
            LOG.error(_('terminate_connection: No mapping of volume '
                        '%(vol_name)s to host %(host_name)s found') %
                      {'vol_name': vol_name, 'host_name': host_name})

        # If this host has no more mappings, delete it
        if not mapping_data:
            self._delete_host(host_name)

        LOG.debug(_('leave: terminate_connection: volume %(vol)s with '
                    'connector %(conn)s') % {'vol': str(volume),
                                             'conn': str(connector)})

    """====================================================================="""
    """ VOLUMES/SNAPSHOTS                                                   """
    """====================================================================="""

    def _get_vdisk_attributes(self, vdisk_name):
        """Return vdisk attributes, or None if vdisk does not exist

        Exception is raised if the information from system can not be
        parsed/matched to a single vdisk.
        """

        ssh_cmd = 'svcinfo lsvdisk -bytes -delim ! %s ' % vdisk_name
        return self._execute_command_and_parse_attributes(ssh_cmd)

    def _get_vdisk_fc_mappings(self, vdisk_name):
        """Return FlashCopy mappings that this vdisk is associated with."""

        ssh_cmd = 'svcinfo lsvdiskfcmappings -nohdr %s' % vdisk_name
        out, err = self._run_ssh(ssh_cmd)

        mapping_ids = []
        if (len(out.strip())):
            lines = out.strip().split('\n')
            for line in lines:
                mapping_ids.append(line.split()[0])
        return mapping_ids

    def _get_vdisk_params(self, type_id):
        opts = self._build_default_opts()
        if type_id:
            ctxt = context.get_admin_context()
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            specs = volume_type.get('extra_specs')
            for k, value in specs.iteritems():
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
                if scope == 'capabilities' and key == 'storage_protocol':
                    scope = None
                    key = 'protocol'
                    words = value.split()
                    self._driver_assert(words and
                                        len(words) == 2 and
                                        words[0] == '<in>',
                                        _('protocol must be specified as '
                                          '\'<in> iSCSI\' or \'<in> FC\''))
                    del words[0]
                    value = words[0]

                # Anything keys that the driver should look at should have the
                # 'drivers' scope.
                if scope and scope != "drivers":
                    continue

                if key in opts:
                    this_type = type(opts[key]).__name__
                    if this_type == 'int':
                        value = int(value)
                    elif this_type == 'bool':
                        value = strutils.bool_from_string(value)
                    opts[key] = value

        self._check_vdisk_opts(opts)
        return opts

    def _create_vdisk(self, name, size, units, opts):
        """Create a new vdisk."""

        LOG.debug(_('enter: _create_vdisk: vdisk %s ') % name)

        model_update = None
        autoex = '-autoexpand' if opts['autoexpand'] else ''
        easytier = '-easytier on' if opts['easytier'] else '-easytier off'

        # Set space-efficient options
        if opts['rsize'] == -1:
            ssh_cmd_se_opt = ''
        else:
            ssh_cmd_se_opt = (
                '-rsize %(rsize)d%% %(autoex)s -warning %(warn)d%%' %
                {'rsize': opts['rsize'],
                 'autoex': autoex,
                 'warn': opts['warning']})
            if opts['compression']:
                ssh_cmd_se_opt = ssh_cmd_se_opt + ' -compressed'
            else:
                ssh_cmd_se_opt = ssh_cmd_se_opt + (
                    ' -grainsize %d' % opts['grainsize'])

        ssh_cmd = ('svctask mkvdisk -name %(name)s -mdiskgrp %(mdiskgrp)s '
                   '-iogrp 0 -size %(size)s -unit '
                   '%(unit)s %(easytier)s %(ssh_cmd_se_opt)s'
                   % {'name': name,
                   'mdiskgrp': self.configuration.storwize_svc_volpool_name,
                   'size': size, 'unit': units, 'easytier': easytier,
                   'ssh_cmd_se_opt': ssh_cmd_se_opt})
        out, err = self._run_ssh(ssh_cmd)
        self._assert_ssh_return(len(out.strip()), '_create_vdisk',
                                ssh_cmd, out, err)

        # Ensure that the output is as expected
        match_obj = re.search('Virtual Disk, id \[([0-9]+)\], '
                              'successfully created', out)
        # Make sure we got a "successfully created" message with vdisk id
        self._driver_assert(
            match_obj is not None,
            _('_create_vdisk %(name)s - did not find '
              'success message in CLI output.\n '
              'stdout: %(out)s\n stderr: %(err)s')
            % {'name': name, 'out': str(out), 'err': str(err)})

        LOG.debug(_('leave: _create_vdisk: volume %s ') % name)

    def _make_fc_map(self, source, target, full_copy):
        copyflag = '' if full_copy else '-copyrate 0'
        fc_map_cli_cmd = ('svctask mkfcmap -source %(src)s -target %(tgt)s '
                          '-autodelete %(copyflag)s' %
                          {'src': source,
                           'tgt': target,
                           'copyflag': copyflag})
        out, err = self._run_ssh(fc_map_cli_cmd)
        self._driver_assert(
            len(out.strip()),
            _('create FC mapping from %(source)s to %(target)s - '
              'did not find success message in CLI output.\n'
              ' stdout: %(out)s\n stderr: %(err)s\n')
            % {'source': source,
               'target': target,
               'out': str(out),
               'err': str(err)})

        # Ensure that the output is as expected
        match_obj = re.search('FlashCopy Mapping, id \[([0-9]+)\], '
                              'successfully created', out)
        # Make sure we got a "successfully created" message with vdisk id
        self._driver_assert(
            match_obj is not None,
            _('create FC mapping from %(source)s to %(target)s - '
              'did not find success message in CLI output.\n'
              ' stdout: %(out)s\n stderr: %(err)s\n')
            % {'source': source,
               'target': target,
               'out': str(out),
               'err': str(err)})

        try:
            fc_map_id = match_obj.group(1)
            self._driver_assert(
                fc_map_id is not None,
                _('create FC mapping from %(source)s to %(target)s - '
                  'did not find mapping id in CLI output.\n'
                  ' stdout: %(out)s\n stderr: %(err)s\n')
                % {'source': source,
                   'target': target,
                   'out': str(out),
                   'err': str(err)})
        except IndexError:
            self._driver_assert(
                False,
                _('create FC mapping from %(source)s to %(target)s - '
                  'did not find mapping id in CLI output.\n'
                  ' stdout: %(out)s\n stderr: %(err)s\n')
                % {'source': source,
                   'target': target,
                   'out': str(out),
                   'err': str(err)})
        return fc_map_id

    def _call_prepare_fc_map(self, fc_map_id, source, target):
        try:
            out, err = self._run_ssh('svctask prestartfcmap %s' % fc_map_id)
        except exception.ProcessExecutionError as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_('_prepare_fc_map: Failed to prepare FlashCopy '
                            'from %(source)s to %(target)s.\n'
                            'stdout: %(out)s\n stderr: %(err)s')
                          % {'source': source,
                             'target': target,
                             'out': e.stdout,
                             'err': e.stderr})

    def _prepare_fc_map(self, fc_map_id, source, target):
        self._call_prepare_fc_map(fc_map_id, source, target)
        mapping_ready = False
        wait_time = 5
        # Allow waiting of up to timeout (set as parameter)
        timeout = self.configuration.storwize_svc_flashcopy_timeout
        max_retries = (timeout / wait_time) + 1
        for try_number in range(1, max_retries):
            mapping_attrs = self._get_flashcopy_mapping_attributes(fc_map_id)
            if (mapping_attrs is None or
                    'status' not in mapping_attrs):
                break
            if mapping_attrs['status'] == 'prepared':
                mapping_ready = True
                break
            elif mapping_attrs['status'] == 'stopped':
                self._call_prepare_fc_map(fc_map_id, source, target)
            elif mapping_attrs['status'] != 'preparing':
                # Unexpected mapping status
                exception_msg = (_('Unexecpted mapping status %(status)s '
                                   'for mapping %(id)s. Attributes: '
                                   '%(attr)s')
                                 % {'status': mapping_attrs['status'],
                                    'id': fc_map_id,
                                    'attr': mapping_attrs})
                raise exception.VolumeBackendAPIException(data=exception_msg)
            # Need to wait for mapping to be prepared, wait a few seconds
            time.sleep(wait_time)

        if not mapping_ready:
            exception_msg = (_('Mapping %(id)s prepare failed to complete '
                               'within the allotted %(to)d seconds timeout. '
                               'Terminating.')
                             % {'id': fc_map_id,
                                'to': timeout})
            LOG.error(_('_prepare_fc_map: Failed to start FlashCopy '
                        'from %(source)s to %(target)s with '
                        'exception %(ex)s')
                      % {'source': source,
                         'target': target,
                         'ex': exception_msg})
            raise exception.InvalidSnapshot(
                reason=_('_prepare_fc_map: %s') % exception_msg)

    def _start_fc_map(self, fc_map_id, source, target):
        try:
            out, err = self._run_ssh('svctask startfcmap %s' % fc_map_id)
        except exception.ProcessExecutionError as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_('_start_fc_map: Failed to start FlashCopy '
                            'from %(source)s to %(target)s.\n'
                            'stdout: %(out)s\n stderr: %(err)s')
                          % {'source': source,
                             'target': target,
                             'out': e.stdout,
                             'err': e.stderr})

    def _run_flashcopy(self, source, target, full_copy=True):
        """Create a FlashCopy mapping from the source to the target."""

        LOG.debug(_('enter: _run_flashcopy: execute FlashCopy from source '
                    '%(source)s to target %(target)s') %
                  {'source': source, 'target': target})

        fc_map_id = self._make_fc_map(source, target, full_copy)
        try:
            self._prepare_fc_map(fc_map_id, source, target)
            self._start_fc_map(fc_map_id, source, target)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._delete_vdisk(target, True)

        LOG.debug(_('leave: _run_flashcopy: FlashCopy started from '
                    '%(source)s to %(target)s') %
                  {'source': source, 'target': target})

    def _create_copy(self, src_vdisk, tgt_vdisk, full_copy, opts, src_id,
                     from_vol):
        """Create a new snapshot using FlashCopy."""

        LOG.debug(_('enter: _create_copy: snapshot %(tgt_vdisk)s from '
                    'vdisk %(src_vdisk)s') %
                  {'tgt_vdisk': tgt_vdisk, 'src_vdisk': src_vdisk})

        src_vdisk_attributes = self._get_vdisk_attributes(src_vdisk)
        if src_vdisk_attributes is None:
            exception_msg = (
                _('_create_copy: Source vdisk %s does not exist')
                % src_vdisk)
            LOG.error(exception_msg)
            if from_vol:
                raise exception.VolumeNotFound(exception_msg,
                                               volume_id=src_id)
            else:
                raise exception.SnapshotNotFound(exception_msg,
                                                 snapshot_id=src_id)

        self._driver_assert(
            'capacity' in src_vdisk_attributes,
            _('_create_copy: cannot get source vdisk '
              '%(src)s capacity from vdisk attributes '
              '%(attr)s')
            % {'src': src_vdisk,
               'attr': src_vdisk_attributes})

        src_vdisk_size = src_vdisk_attributes['capacity']
        self._create_vdisk(tgt_vdisk, src_vdisk_size, 'b', opts)
        self._run_flashcopy(src_vdisk, tgt_vdisk, full_copy)

        LOG.debug(_('leave: _create_copy: snapshot %(tgt_vdisk)s from '
                    'vdisk %(src_vdisk)s') %
                  {'tgt_vdisk': tgt_vdisk, 'src_vdisk': src_vdisk})

    def _get_flashcopy_mapping_attributes(self, fc_map_id):
        LOG.debug(_('enter: _get_flashcopy_mapping_attributes: mapping %s')
                  % fc_map_id)

        fc_ls_map_cmd = 'svcinfo lsfcmap -filtervalue id=%s -delim !' % \
            fc_map_id
        out, err = self._run_ssh(fc_ls_map_cmd)
        if not len(out.strip()):
            return None

        # Get list of FlashCopy mappings
        # We expect zero or one line if mapping does not exist,
        # two lines if it does exist, otherwise error
        lines = out.strip().split('\n')
        self._assert_ssh_return(len(lines) <= 2,
                                '_get_flashcopy_mapping_attributes',
                                fc_ls_map_cmd, out, err)

        if len(lines) == 2:
            attributes = self._get_hdr_dic(lines[0], lines[1], '!')
        else:  # 0 or 1 lines
            attributes = None

        LOG.debug(_('leave: _get_flashcopy_mapping_attributes: mapping '
                    '%(fc_map_id)s, attributes %(attributes)s') %
                  {'fc_map_id': fc_map_id, 'attributes': attributes})

        return attributes

    def _is_vdisk_defined(self, vdisk_name):
        """Check if vdisk is defined."""
        LOG.debug(_('enter: _is_vdisk_defined: vdisk %s ') % vdisk_name)
        vdisk_attributes = self._get_vdisk_attributes(vdisk_name)
        LOG.debug(_('leave: _is_vdisk_defined: vdisk %(vol)s with %(str)s ')
                  % {'vol': vdisk_name,
                     'str': vdisk_attributes is not None})
        if vdisk_attributes is None:
            return False
        else:
            return True

    def _delete_vdisk(self, name, force):
        """Deletes existing vdisks.

        It is very important to properly take care of mappings before deleting
        the disk:
        1. If no mappings, then it was a vdisk, and can be deleted
        2. If it is the source of a flashcopy mapping and copy_rate is 0, then
           it is a vdisk that has a snapshot.  If the force flag is set,
           delete the mapping and the vdisk, otherwise set the mapping to
           copy and wait (this will allow users to delete vdisks that have
           snapshots if/when the upper layers allow it).
        3. If it is the target of a mapping and copy_rate is 0, it is a
           snapshot, and we should properly stop the mapping and delete.
        4. If it is the source/target of a mapping and copy_rate is not 0, it
           is a clone or vdisk created from a snapshot.  We wait for the copy
           to complete (the mapping will be autodeleted) and then delete the
           vdisk.

        """

        LOG.debug(_('enter: _delete_vdisk: vdisk %s') % name)

        # Try to delete volume only if found on the storage
        vdisk_defined = self._is_vdisk_defined(name)
        if not vdisk_defined:
            LOG.info(_('warning: Tried to delete vdisk %s but it does not '
                       'exist.') % name)
            return

        # Ensure vdisk has no FlashCopy mappings
        mapping_ids = self._get_vdisk_fc_mappings(name)
        while len(mapping_ids):
            wait_for_copy = False
            for map_id in mapping_ids:
                attrs = self._get_flashcopy_mapping_attributes(map_id)
                if not attrs:
                    continue
                source = attrs['source_vdisk_name']
                target = attrs['target_vdisk_name']
                copy_rate = attrs['copy_rate']
                status = attrs['status']

                if copy_rate == '0':
                    # Case #2: A vdisk that has snapshots
                    if source == name:
                            ssh_cmd = ('svctask chfcmap -copyrate 50 '
                                       '-autodelete on %s' % map_id)
                            out, err = self._run_ssh(ssh_cmd)
                            wait_for_copy = True
                    # Case #3: A snapshot
                    else:
                        msg = (_('Vdisk %(name)s not involved in '
                                 'mapping %(src)s -> %(tgt)s') %
                               {'name': name, 'src': source, 'tgt': target})
                        self._driver_assert(target == name, msg)
                        if status in ['copying', 'prepared']:
                            self._run_ssh('svctask stopfcmap %s' % map_id)
                        elif status == 'stopping':
                            wait_for_copy = True
                        else:
                            self._run_ssh('svctask rmfcmap -force %s' % map_id)
                # Case 4: Copy in progress - wait and will autodelete
                else:
                    if status == 'prepared':
                        self._run_ssh('svctask stopfcmap %s' % map_id)
                        self._run_ssh('svctask rmfcmap -force %s' % map_id)
                    elif status == 'idle_or_copied':
                        # Prepare failed
                        self._run_ssh('svctask rmfcmap -force %s' % map_id)
                    else:
                        wait_for_copy = True
            if wait_for_copy:
                time.sleep(5)
            mapping_ids = self._get_vdisk_fc_mappings(name)

        forceflag = '-force' if force else ''
        cmd_params = {'frc': forceflag, 'name': name}
        ssh_cmd = 'svctask rmvdisk %(frc)s %(name)s' % cmd_params
        out, err = self._run_ssh(ssh_cmd)
        # No output should be returned from rmvdisk
        self._assert_ssh_return(len(out.strip()) == 0,
                                ('_delete_vdisk %(name)s')
                                % {'name': name},
                                ssh_cmd, out, err)
        LOG.debug(_('leave: _delete_vdisk: vdisk %s') % name)

    def create_volume(self, volume):
        opts = self._get_vdisk_params(volume['volume_type_id'])
        return self._create_vdisk(volume['name'], str(volume['size']), 'gb',
                                  opts)

    def delete_volume(self, volume):
        self._delete_vdisk(volume['name'], False)

    def create_snapshot(self, snapshot):
        source_vol = self.db.volume_get(self._context, snapshot['volume_id'])
        opts = self._get_vdisk_params(source_vol['volume_type_id'])
        self._create_copy(src_vdisk=snapshot['volume_name'],
                          tgt_vdisk=snapshot['name'],
                          full_copy=False,
                          opts=opts,
                          src_id=snapshot['volume_id'],
                          from_vol=True)

    def delete_snapshot(self, snapshot):
        self._delete_vdisk(snapshot['name'], False)

    def create_volume_from_snapshot(self, volume, snapshot):
        if volume['size'] != snapshot['volume_size']:
            exception_message = (_('create_volume_from_snapshot: '
                                   'Source and destination size differ.'))
            raise exception.VolumeBackendAPIException(data=exception_message)

        opts = self._get_vdisk_params(volume['volume_type_id'])
        self._create_copy(src_vdisk=snapshot['name'],
                          tgt_vdisk=volume['name'],
                          full_copy=True,
                          opts=opts,
                          src_id=snapshot['id'],
                          from_vol=False)

    def create_cloned_volume(self, tgt_volume, src_volume):
        if src_volume['size'] != tgt_volume['size']:
            exception_message = (_('create_cloned_volume: '
                                   'Source and destination size differ.'))
            raise exception.VolumeBackendAPIException(data=exception_message)

        opts = self._get_vdisk_params(tgt_volume['volume_type_id'])
        self._create_copy(src_vdisk=src_volume['name'],
                          tgt_vdisk=tgt_volume['name'],
                          full_copy=True,
                          opts=opts,
                          src_id=src_volume['id'],
                          from_vol=True)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        opts = self._get_vdisk_params(volume['volume_type_id'])
        if opts['protocol'] == 'iSCSI':
            # Implemented in base iSCSI class
            return super(StorwizeSVCDriver, self).copy_image_to_volume(
                    context, volume, image_service, image_id)
        else:
            raise NotImplementedError()

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        opts = self._get_vdisk_params(volume['volume_type_id'])
        if opts['protocol'] == 'iSCSI':
            # Implemented in base iSCSI class
            return super(StorwizeSVCDriver, self).copy_volume_to_image(
                    context, volume, image_service, image_meta)
        else:
            raise NotImplementedError()

    """====================================================================="""
    """ MISC/HELPERS                                                        """
    """====================================================================="""

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If we haven't gotten stats yet or 'refresh' is True,
        run update the stats first."""
        if not self._stats or refresh:
            self._update_volume_status()

        return self._stats

    def _update_volume_status(self):
        """Retrieve status info from volume group."""

        LOG.debug(_("Updating volume status"))
        data = {}

        data['vendor_name'] = 'IBM'
        data['driver_version'] = '1.1'
        data['storage_protocol'] = list(self._enabled_protocols)

        data['total_capacity_gb'] = 0  # To be overwritten
        data['free_capacity_gb'] = 0   # To be overwritten
        data['reserved_percentage'] = 0
        data['QoS_support'] = False

        pool = self.configuration.storwize_svc_volpool_name
        #Get storage system name
        ssh_cmd = 'svcinfo lssystem -delim !'
        attributes = self._execute_command_and_parse_attributes(ssh_cmd)
        if not attributes or not attributes['name']:
            exception_message = (_('_update_volume_status: '
                                   'Could not get system name'))
            raise exception.VolumeBackendAPIException(data=exception_message)

        backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = '%s_%s' % (attributes['name'], pool)
        data['volume_backend_name'] = backend_name

        ssh_cmd = 'svcinfo lsmdiskgrp -bytes -delim ! %s' % pool
        attributes = self._execute_command_and_parse_attributes(ssh_cmd)
        if not attributes:
            LOG.error(_('Could not get pool data from the storage'))
            exception_message = (_('_update_volume_status: '
                                   'Could not get storage pool data'))
            raise exception.VolumeBackendAPIException(data=exception_message)

        data['total_capacity_gb'] = (float(attributes['capacity']) /
                                    (1024 ** 3))
        data['free_capacity_gb'] = (float(attributes['free_capacity']) /
                                    (1024 ** 3))
        data['easytier_support'] = attributes['easy_tier'] in ['on', 'auto']
        data['compression_support'] = self._compression_enabled

        self._stats = data

    def _port_conf_generator(self, cmd):
        ssh_cmd = '%s -delim !' % cmd
        out, err = self._run_ssh(ssh_cmd)

        if not len(out.strip()):
            return
        port_lines = out.strip().split('\n')
        if not len(port_lines):
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

    def _check_vdisk_opts(self, opts):
        # Check that rsize is either -1 or between 0 and 100
        if not (opts['rsize'] >= -1 and opts['rsize'] <= 100):
            raise exception.InvalidInput(
                reason=_('Illegal value specified for storwize_svc_vol_rsize: '
                         'set to either a percentage (0-100) or -1'))

        # Check that warning is either -1 or between 0 and 100
        if not (opts['warning'] >= -1 and opts['warning'] <= 100):
            raise exception.InvalidInput(
                reason=_('Illegal value specified for '
                         'storwize_svc_vol_warning: '
                         'set to a percentage (0-100)'))

        # Check that grainsize is 32/64/128/256
        if opts['grainsize'] not in [32, 64, 128, 256]:
            raise exception.InvalidInput(
                reason=_('Illegal value specified for '
                         'storwize_svc_vol_grainsize: set to either '
                         '32, 64, 128, or 256'))

        # Check that compression is supported
        if opts['compression'] and not self._compression_enabled:
            raise exception.InvalidInput(
                reason=_('System does not support compression'))

        # Check that rsize is set if compression is set
        if opts['compression'] and opts['rsize'] == -1:
            raise exception.InvalidInput(
                reason=_('If compression is set to True, rsize must '
                         'also be set (not equal to -1)'))

        # Check that the requested protocol is enabled
        if opts['protocol'] not in self._enabled_protocols:
            raise exception.InvalidInput(
                reason=_('Illegal value %(prot)s specified for '
                         'storwize_svc_connection_protocol: '
                         'valid values are %(enabled)s')
                % {'prot': opts['protocol'],
                   'enabled': ','.join(self._enabled_protocols)})

        # Check that multipath is only enabled for fc
        if opts['protocol'] != 'FC' and opts['multipath']:
            raise exception.InvalidInput(
                reason=_('Multipath is currently only supported for FC '
                         'connections and not iSCSI.  (This is a Nova '
                         'limitation.)'))

    def _execute_command_and_parse_attributes(self, ssh_cmd):
        """Execute command on the Storwize/SVC and parse attributes.

        Exception is raised if the information from the system
        can not be obtained.

        """

        LOG.debug(_('enter: _execute_command_and_parse_attributes: '
                    ' command %s') % ssh_cmd)

        try:
            out, err = self._run_ssh(ssh_cmd)
        except exception.ProcessExecutionError as e:
            # Didn't get details from the storage, return None
            LOG.error(_('CLI Exception output:\n command: %(cmd)s\n '
                        'stdout: %(out)s\n stderr: %(err)s') %
                      {'cmd': ssh_cmd,
                       'out': e.stdout,
                       'err': e.stderr})
            return None

        self._assert_ssh_return(len(out),
                                '_execute_command_and_parse_attributes',
                                ssh_cmd, out, err)
        attributes = {}
        for attrib_line in out.split('\n'):
            # If '!' not found, return the string and two empty strings
            attrib_name, foo, attrib_value = attrib_line.partition('!')
            if attrib_name is not None and len(attrib_name.strip()):
                attributes[attrib_name] = attrib_value

        LOG.debug(_('leave: _execute_command_and_parse_attributes:\n'
                    'command: %(cmd)s\n'
                    'attributes: %(attr)s')
                  % {'cmd': ssh_cmd,
                     'attr': str(attributes)})

        return attributes

    def _get_hdr_dic(self, header, row, delim):
        """Return CLI row data as a dictionary indexed by names from header.
        string. The strings are converted to columns using the delimiter in
        delim.
        """

        attributes = header.split(delim)
        values = row.split(delim)
        self._driver_assert(
            len(values) ==
            len(attributes),
            _('_get_hdr_dic: attribute headers and values do not match.\n '
              'Headers: %(header)s\n Values: %(row)s')
            % {'header': str(header),
               'row': str(row)})
        dic = {}
        for attribute, value in map(None, attributes, values):
            dic[attribute] = value
        return dic

    def _log_cli_output_error(self, function, cmd, out, err):
        LOG.error(_('%(fun)s: Failed with unexpected CLI output.\n '
                    'Command: %(cmd)s\nstdout: %(out)s\nstderr: %(err)s\n')
                  % {'fun': function, 'cmd': cmd,
                     'out': str(out), 'err': str(err)})

    def _driver_assert(self, assert_condition, exception_message):
        """Internal assertion mechanism for CLI output."""
        if not assert_condition:
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _assert_ssh_return(self, test, fun, ssh_cmd, out, err):
        self._driver_assert(
            test,
            _('%(fun)s: Failed with unexpected CLI output.\n '
              'Command: %(cmd)s\n stdout: %(out)s\n stderr: %(err)s')
            % {'fun': fun,
               'cmd': ssh_cmd,
               'out': str(out),
               'err': str(err)})

    def _handle_keyerror(self, function, header):
        msg = (_('Did not find expected column in %(fun)s: %(hdr)s') %
               {'fun': function, 'hdr': header})
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(
            data=msg)


class CLIResponse(object):
    '''Parse SVC CLI output and generate iterable'''

    def __init__(self, raw, delim='!', with_header=True):
        super(CLIResponse, self).__init__()
        self.raw = raw
        self.delim = delim
        self.with_header = with_header
        self.result = self._parse()

    def select(self, *keys):
        for a in self.result:
            vs = []
            for k in keys:
                v = a.get(k, None)
                if isinstance(v, basestring):
                    v = [v]
                if isinstance(v, list):
                    vs.append(v)
            for item in zip(*vs):
                yield item

    def __getitem__(self, key):
        return self.result[key]

    def __iter__(self):
        for a in self.result:
            yield a

    def __len__(self):
        return len(self.result)

    def _parse(self):
        def get_reader(content, delim):
            for line in content.lstrip().splitlines():
                line = line.strip()
                if line:
                    yield line.split(delim)
                else:
                    yield []

        if isinstance(self.raw, basestring):
            stdout, stderr = self.raw, ''
        else:
            stdout, stderr = self.raw
        reader = get_reader(stdout, self.delim)
        result = []

        if self.with_header:
            hds = tuple()
            for row in reader:
                hds = row
                break
            for row in reader:
                cur = dict()
                for k, v in zip(hds, row):
                    CLIResponse.append_dict(cur, k, v)
                result.append(cur)
        else:
            cur = dict()
            for row in reader:
                if row:
                    CLIResponse.append_dict(cur, row[0], ' '.join(row[1:]))
                elif cur:  # start new section
                    result.append(cur)
                    cur = dict()
            if cur:
                result.append(cur)
        return result

    @staticmethod
    def append_dict(dict_, key, value):
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
