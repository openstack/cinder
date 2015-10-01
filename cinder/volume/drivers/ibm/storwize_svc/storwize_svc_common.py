# Copyright 2014 IBM Corp.
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

import random
import re
import time
import unicodedata


from eventlet import greenthread
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import strutils
import six

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume import qos_specs
from cinder.volume import utils
from cinder.volume import volume_types

INTERVAL_1_SEC = 1
DEFAULT_TIMEOUT = 15
LOG = logging.getLogger(__name__)


class StorwizeSSH(object):
    """SSH interface to IBM Storwize family and SVC storage systems."""
    def __init__(self, run_ssh):
        self._ssh = run_ssh

    def _run_ssh(self, ssh_cmd):
        try:
            return self._ssh(ssh_cmd)
        except processutils.ProcessExecutionError as e:
            msg = (_('CLI Exception output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': e.stdout,
                    'err': e.stderr})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def run_ssh_info(self, ssh_cmd, delim='!', with_header=False):
        """Run an SSH command and return parsed output."""
        raw = self._run_ssh(ssh_cmd)
        return CLIResponse(raw, ssh_cmd=ssh_cmd, delim=delim,
                           with_header=with_header)

    def run_ssh_assert_no_output(self, ssh_cmd):
        """Run an SSH command and assert no output returned."""
        out, err = self._run_ssh(ssh_cmd)
        if len(out.strip()) != 0:
            msg = (_('Expected no output from CLI command %(cmd)s, '
                     'got %(out)s.') % {'cmd': ' '.join(ssh_cmd), 'out': out})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def run_ssh_check_created(self, ssh_cmd):
        """Run an SSH command and return the ID of the created object."""
        out, err = self._run_ssh(ssh_cmd)
        try:
            match_obj = re.search(r'\[([0-9]+)\],? successfully created', out)
            return match_obj.group(1)
        except (AttributeError, IndexError):
            msg = (_('Failed to parse CLI output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': out,
                    'err': err})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def lsnode(self, node_id=None):
        with_header = True
        ssh_cmd = ['svcinfo', 'lsnode', '-delim', '!']
        if node_id:
            with_header = False
            ssh_cmd.append(node_id)
        return self.run_ssh_info(ssh_cmd, with_header=with_header)

    def lslicense(self):
        ssh_cmd = ['svcinfo', 'lslicense', '-delim', '!']
        return self.run_ssh_info(ssh_cmd)[0]

    def lssystem(self):
        ssh_cmd = ['svcinfo', 'lssystem', '-delim', '!']
        return self.run_ssh_info(ssh_cmd)[0]

    def lsmdiskgrp(self, pool):
        ssh_cmd = ['svcinfo', 'lsmdiskgrp', '-bytes', '-delim', '!',
                   '"%s"' % pool]
        return self.run_ssh_info(ssh_cmd)[0]

    def lsiogrp(self):
        ssh_cmd = ['svcinfo', 'lsiogrp', '-delim', '!']
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lsportip(self):
        ssh_cmd = ['svcinfo', 'lsportip', '-delim', '!']
        return self.run_ssh_info(ssh_cmd, with_header=True)

    @staticmethod
    def _create_port_arg(port_type, port_name):
        if port_type == 'initiator':
            port = ['-iscsiname']
        else:
            port = ['-hbawwpn']
        port.append(port_name)
        return port

    def mkhost(self, host_name, port_type, port_name):
        port = self._create_port_arg(port_type, port_name)
        ssh_cmd = ['svctask', 'mkhost', '-force'] + port
        ssh_cmd += ['-name', '"%s"' % host_name]
        return self.run_ssh_check_created(ssh_cmd)

    def addhostport(self, host, port_type, port_name):
        port = self._create_port_arg(port_type, port_name)
        ssh_cmd = ['svctask', 'addhostport', '-force'] + port + ['"%s"' % host]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lshost(self, host=None):
        with_header = True
        ssh_cmd = ['svcinfo', 'lshost', '-delim', '!']
        if host:
            with_header = False
            ssh_cmd.append('"%s"' % host)
        return self.run_ssh_info(ssh_cmd, with_header=with_header)

    def add_chap_secret(self, secret, host):
        ssh_cmd = ['svctask', 'chhost', '-chapsecret', secret, '"%s"' % host]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lsiscsiauth(self):
        ssh_cmd = ['svcinfo', 'lsiscsiauth', '-delim', '!']
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lsfabric(self, wwpn=None, host=None):
        ssh_cmd = ['svcinfo', 'lsfabric', '-delim', '!']
        if wwpn:
            ssh_cmd.extend(['-wwpn', wwpn])
        elif host:
            ssh_cmd.extend(['-host', '"%s"' % host])
        else:
            msg = (_('Must pass wwpn or host to lsfabric.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def mkvdiskhostmap(self, host, vdisk, lun, multihostmap):
        """Map vdisk to host.

        If vdisk already mapped and multihostmap is True, use the force flag.
        """
        ssh_cmd = ['svctask', 'mkvdiskhostmap', '-host', '"%s"' % host,
                   '-scsi', lun, vdisk]
        out, err = self._ssh(ssh_cmd, check_exit_code=False)
        if 'successfully created' in out:
            return
        if not err:
            msg = (_('Did not find success message nor error for %(fun)s: '
                     '%(out)s.') % {'out': out, 'fun': ssh_cmd})
            raise exception.VolumeBackendAPIException(data=msg)
        if err.startswith('CMMVC6071E'):
            if not multihostmap:
                LOG.error(_LE('storwize_svc_multihostmap_enabled is set '
                              'to False, not allowing multi host mapping.'))
                raise exception.VolumeDriverException(
                    message=_('CMMVC6071E The VDisk-to-host mapping was not '
                              'created because the VDisk is already mapped '
                              'to a host.\n"'))

        ssh_cmd.insert(ssh_cmd.index('mkvdiskhostmap') + 1, '-force')
        return self.run_ssh_check_created(ssh_cmd)

    def rmvdiskhostmap(self, host, vdisk):
        ssh_cmd = ['svctask', 'rmvdiskhostmap', '-host', '"%s"' % host, vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lsvdiskhostmap(self, vdisk):
        ssh_cmd = ['svcinfo', 'lsvdiskhostmap', '-delim', '!', vdisk]
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lshostvdiskmap(self, host):
        ssh_cmd = ['svcinfo', 'lshostvdiskmap', '-delim', '!', '"%s"' % host]
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def rmhost(self, host):
        ssh_cmd = ['svctask', 'rmhost', '"%s"' % host]
        self.run_ssh_assert_no_output(ssh_cmd)

    def mkvdisk(self, name, size, units, pool, opts, params):
        ssh_cmd = ['svctask', 'mkvdisk', '-name', name, '-mdiskgrp',
                   '"%s"' % pool, '-iogrp', six.text_type(opts['iogrp']),
                   '-size', size, '-unit', units] + params
        return self.run_ssh_check_created(ssh_cmd)

    def rmvdisk(self, vdisk, force=True):
        ssh_cmd = ['svctask', 'rmvdisk']
        if force:
            ssh_cmd += ['-force']
        ssh_cmd += [vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lsvdisk(self, vdisk):
        """Return vdisk attributes or None if it doesn't exist."""
        ssh_cmd = ['svcinfo', 'lsvdisk', '-bytes', '-delim', '!', vdisk]
        out, err = self._ssh(ssh_cmd, check_exit_code=False)
        if not len(err):
            return CLIResponse((out, err), ssh_cmd=ssh_cmd, delim='!',
                               with_header=False)[0]
        if err.startswith('CMMVC5754E'):
            return None
        msg = (_('CLI Exception output:\n command: %(cmd)s\n '
                 'stdout: %(out)s\n stderr: %(err)s.') %
               {'cmd': ssh_cmd,
                'out': out,
                'err': err})
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def lsvdisks_from_filter(self, filter_name, value):
        """Performs an lsvdisk command, filtering the results as specified.

        Returns an iterable for all matching vdisks.
        """
        ssh_cmd = ['svcinfo', 'lsvdisk', '-bytes', '-delim', '!',
                   '-filtervalue', '%s=%s' % (filter_name, value)]
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def chvdisk(self, vdisk, params):
        ssh_cmd = ['svctask', 'chvdisk'] + params + [vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def movevdisk(self, vdisk, iogrp):
        ssh_cmd = ['svctask', 'movevdisk', '-iogrp', iogrp, vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def expandvdisksize(self, vdisk, amount):
        ssh_cmd = (
            ['svctask', 'expandvdisksize', '-size', six.text_type(amount),
             '-unit', 'gb', vdisk])
        self.run_ssh_assert_no_output(ssh_cmd)

    def mkfcmap(self, source, target, full_copy, consistgrp=None):
        ssh_cmd = ['svctask', 'mkfcmap', '-source', source, '-target',
                   target, '-autodelete']
        if not full_copy:
            ssh_cmd.extend(['-copyrate', '0'])
        if consistgrp:
            ssh_cmd.extend(['-consistgrp', consistgrp])
        out, err = self._ssh(ssh_cmd, check_exit_code=False)
        if 'successfully created' not in out:
            msg = (_('CLI Exception output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': out,
                    'err': err})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        try:
            match_obj = re.search(r'FlashCopy Mapping, id \[([0-9]+)\], '
                                  'successfully created', out)
            fc_map_id = match_obj.group(1)
        except (AttributeError, IndexError):
            msg = (_('Failed to parse CLI output:\n command: %(cmd)s\n '
                     'stdout: %(out)s\n stderr: %(err)s.') %
                   {'cmd': ssh_cmd,
                    'out': out,
                    'err': err})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return fc_map_id

    def prestartfcmap(self, fc_map_id):
        ssh_cmd = ['svctask', 'prestartfcmap', fc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def startfcmap(self, fc_map_id):
        ssh_cmd = ['svctask', 'startfcmap', fc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def prestartfcconsistgrp(self, fc_consist_group):
        ssh_cmd = ['svctask', 'prestartfcconsistgrp', fc_consist_group]
        self.run_ssh_assert_no_output(ssh_cmd)

    def startfcconsistgrp(self, fc_consist_group):
        ssh_cmd = ['svctask', 'startfcconsistgrp', fc_consist_group]
        self.run_ssh_assert_no_output(ssh_cmd)

    def stopfcconsistgrp(self, fc_consist_group):
        ssh_cmd = ['svctask', 'stopfcconsistgrp', fc_consist_group]
        self.run_ssh_assert_no_output(ssh_cmd)

    def chfcmap(self, fc_map_id, copyrate='50', autodel='on'):
        ssh_cmd = ['svctask', 'chfcmap', '-copyrate', copyrate,
                   '-autodelete', autodel, fc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def stopfcmap(self, fc_map_id):
        ssh_cmd = ['svctask', 'stopfcmap', fc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def rmfcmap(self, fc_map_id):
        ssh_cmd = ['svctask', 'rmfcmap', '-force', fc_map_id]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lsvdiskfcmappings(self, vdisk):
        ssh_cmd = ['svcinfo', 'lsvdiskfcmappings', '-delim', '!', vdisk]
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lsfcmap(self, fc_map_id):
        ssh_cmd = ['svcinfo', 'lsfcmap', '-filtervalue',
                   'id=%s' % fc_map_id, '-delim', '!']
        return self.run_ssh_info(ssh_cmd, with_header=True)

    def lsfcconsistgrp(self, fc_consistgrp):
        ssh_cmd = ['svcinfo', 'lsfcconsistgrp', '-delim', '!', fc_consistgrp]
        out, err = self._ssh(ssh_cmd)
        return CLIResponse((out, err), ssh_cmd=ssh_cmd, delim='!',
                           with_header=False)

    def mkfcconsistgrp(self, fc_consist_group):
        ssh_cmd = ['svctask', 'mkfcconsistgrp', '-name', fc_consist_group]
        return self.run_ssh_check_created(ssh_cmd)

    def rmfcconsistgrp(self, fc_consist_group):
        ssh_cmd = ['svctask', 'rmfcconsistgrp', '-force', fc_consist_group]
        return self.run_ssh_assert_no_output(ssh_cmd)

    def addvdiskcopy(self, vdisk, dest_pool, params):
        ssh_cmd = (['svctask', 'addvdiskcopy'] + params + ['-mdiskgrp',
                   '"%s"' % dest_pool, vdisk])
        return self.run_ssh_check_created(ssh_cmd)

    def lsvdiskcopy(self, vdisk, copy_id=None):
        ssh_cmd = ['svcinfo', 'lsvdiskcopy', '-delim', '!']
        with_header = True
        if copy_id:
            ssh_cmd += ['-copy', copy_id]
            with_header = False
        ssh_cmd += [vdisk]
        return self.run_ssh_info(ssh_cmd, with_header=with_header)

    def lsvdisksyncprogress(self, vdisk, copy_id):
        ssh_cmd = ['svcinfo', 'lsvdisksyncprogress', '-delim', '!',
                   '-copy', copy_id, vdisk]
        return self.run_ssh_info(ssh_cmd, with_header=True)[0]

    def rmvdiskcopy(self, vdisk, copy_id):
        ssh_cmd = ['svctask', 'rmvdiskcopy', '-copy', copy_id, vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def addvdiskaccess(self, vdisk, iogrp):
        ssh_cmd = ['svctask', 'addvdiskaccess', '-iogrp', iogrp, vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def rmvdiskaccess(self, vdisk, iogrp):
        ssh_cmd = ['svctask', 'rmvdiskaccess', '-iogrp', iogrp, vdisk]
        self.run_ssh_assert_no_output(ssh_cmd)

    def lsportfc(self, node_id):
        ssh_cmd = ['svcinfo', 'lsportfc', '-delim', '!',
                   '-filtervalue', 'node_id=%s' % node_id]
        return self.run_ssh_info(ssh_cmd, with_header=True)


class StorwizeHelpers(object):

    # All the supported QoS key are saved in this dict. When a new
    # key is going to add, three values MUST be set:
    # 'default': to indicate the value, when the parameter is disabled.
    # 'param': to indicate the corresponding parameter in the command.
    # 'type': to indicate the type of this value.
    svc_qos_keys = {'IOThrottling': {'default': '0',
                                     'param': 'rate',
                                     'type': int}}

    def __init__(self, run_ssh):
        self.ssh = StorwizeSSH(run_ssh)
        self.check_fcmapping_interval = 3

    @staticmethod
    def handle_keyerror(cmd, out):
        msg = (_('Could not find key in output of command %(cmd)s: %(out)s.')
               % {'out': out, 'cmd': cmd})
        raise exception.VolumeBackendAPIException(data=msg)

    def compression_enabled(self):
        """Return whether or not compression is enabled for this system."""
        resp = self.ssh.lslicense()
        keys = ['license_compression_enclosures',
                'license_compression_capacity']
        for key in keys:
            if resp.get(key, '0') != '0':
                return True
        return False

    def get_system_info(self):
        """Return system's name, ID, and code level."""
        resp = self.ssh.lssystem()
        level = resp['code_level']
        match_obj = re.search('([0-9].){3}[0-9]', level)
        if match_obj is None:
            msg = _('Failed to get code level (%s).') % level
            raise exception.VolumeBackendAPIException(data=msg)
        code_level = match_obj.group().split('.')
        return {'code_level': tuple([int(x) for x in code_level]),
                'system_name': resp['name'],
                'system_id': resp['id']}

    def get_pool_attrs(self, pool):
        """Return attributes for the specified pool."""
        return self.ssh.lsmdiskgrp(pool)

    def get_available_io_groups(self):
        """Return list of available IO groups."""
        iogrps = []
        resp = self.ssh.lsiogrp()
        for iogrp in resp:
            try:
                if int(iogrp['node_count']) > 0:
                    iogrps.append(int(iogrp['id']))
            except KeyError:
                self.handle_keyerror('lsiogrp', iogrp)
            except ValueError:
                msg = (_('Expected integer for node_count, '
                         'svcinfo lsiogrp returned: %(node)s.') %
                       {'node': iogrp['node_count']})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        return iogrps

    def get_node_info(self):
        """Return dictionary containing information on system's nodes."""
        nodes = {}
        resp = self.ssh.lsnode()
        for node_data in resp:
            try:
                if node_data['status'] != 'online':
                    continue
                node = {}
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
                nodes[node['id']] = node
            except KeyError:
                self.handle_keyerror('lsnode', node_data)
        return nodes

    def add_iscsi_ip_addrs(self, storage_nodes):
        """Add iSCSI IP addresses to system node information."""
        resp = self.ssh.lsportip()
        for ip_data in resp:
            try:
                state = ip_data['state']
                if ip_data['node_id'] in storage_nodes and (
                        state == 'configured' or state == 'online'):
                    node = storage_nodes[ip_data['node_id']]
                    if len(ip_data['IP_address']):
                        node['ipv4'].append(ip_data['IP_address'])
                    if len(ip_data['IP_address_6']):
                        node['ipv6'].append(ip_data['IP_address_6'])
            except KeyError:
                self.handle_keyerror('lsportip', ip_data)

    def add_fc_wwpns(self, storage_nodes):
        """Add FC WWPNs to system node information."""
        for key in storage_nodes:
            node = storage_nodes[key]
            wwpns = set(node['WWPN'])
            resp = self.ssh.lsportfc(node_id=node['id'])
            for port_info in resp:
                if (port_info['type'] == 'fc' and
                        port_info['status'] == 'active'):
                    wwpns.add(port_info['WWPN'])
            node['WWPN'] = list(wwpns)
            LOG.info(_LI('WWPN on node %(node)s: %(wwpn)s.'),
                     {'node': node['id'], 'wwpn': node['WWPN']})

    def add_chap_secret_to_host(self, host_name):
        """Generate and store a randomly-generated CHAP secret for the host."""
        chap_secret = utils.generate_password()
        self.ssh.add_chap_secret(chap_secret, host_name)
        return chap_secret

    def get_chap_secret_for_host(self, host_name):
        """Generate and store a randomly-generated CHAP secret for the host."""
        resp = self.ssh.lsiscsiauth()
        host_found = False
        for host_data in resp:
            try:
                if host_data['name'] == host_name:
                    host_found = True
                    if host_data['iscsi_auth_method'] == 'chap':
                        return host_data['iscsi_chap_secret']
            except KeyError:
                self.handle_keyerror('lsiscsiauth', host_data)
        if not host_found:
            msg = _('Failed to find host %s.') % host_name
            raise exception.VolumeBackendAPIException(data=msg)
        return None

    def get_conn_fc_wwpns(self, host):
        wwpns = set()
        resp = self.ssh.lsfabric(host=host)
        for wwpn in resp.select('local_wwpn'):
            if wwpn is not None:
                wwpns.add(wwpn)
        return list(wwpns)

    def get_host_from_connector(self, connector):
        """Return the Storwize host described by the connector."""
        LOG.debug('Enter: get_host_from_connector: %s.', connector)

        # If we have FC information, we have a faster lookup option
        host_name = None
        if 'wwpns' in connector:
            for wwpn in connector['wwpns']:
                resp = self.ssh.lsfabric(wwpn=wwpn)
                for wwpn_info in resp:
                    try:
                        if (wwpn_info['remote_wwpn'] and
                                wwpn_info['name'] and
                                wwpn_info['remote_wwpn'].lower() ==
                                wwpn.lower()):
                            host_name = wwpn_info['name']
                    except KeyError:
                        self.handle_keyerror('lsfabric', wwpn_info)

        if host_name:
            LOG.debug('Leave: get_host_from_connector: host %s.', host_name)
            return host_name

        # That didn't work, so try exhaustive search
        hosts_info = self.ssh.lshost()
        found = False
        for name in hosts_info.select('name'):
            resp = self.ssh.lshost(host=name)
            if 'initiator' in connector:
                for iscsi in resp.select('iscsi_name'):
                    if iscsi == connector['initiator']:
                        host_name = name
                        found = True
                        break
            elif 'wwpns' in connector and len(connector['wwpns']):
                connector_wwpns = [str(x).lower() for x in connector['wwpns']]
                for wwpn in resp.select('WWPN'):
                    if wwpn and wwpn.lower() in connector_wwpns:
                        host_name = name
                        found = True
                        break
            if found:
                break

        LOG.debug('Leave: get_host_from_connector: host %s.', host_name)
        return host_name

    def create_host(self, connector):
        """Create a new host on the storage system.

        We create a host name and associate it with the given connection
        information.  The host name will be a cleaned up version of the given
        host name (at most 55 characters), plus a random 8-character suffix to
        avoid collisions. The total length should be at most 63 characters.
        """
        LOG.debug('Enter: create_host: host %s.', connector['host'])

        # Before we start, make sure host name is a string and that we have at
        # least one port.
        host_name = connector['host']
        if not isinstance(host_name, six.string_types):
            msg = _('create_host: Host name is not unicode or string.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        ports = []
        if 'initiator' in connector:
            ports.append(['initiator', '%s' % connector['initiator']])
        if 'wwpns' in connector:
            for wwpn in connector['wwpns']:
                ports.append(['wwpn', '%s' % wwpn])
        if not len(ports):
            msg = _('create_host: No initiators or wwpns supplied.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        # Build a host name for the Storwize host - first clean up the name
        if isinstance(host_name, six.text_type):
            host_name = unicodedata.normalize('NFKD', host_name).encode(
                'ascii', 'replace').decode('ascii')

        for num in range(0, 128):
            ch = str(chr(num))
            if not ch.isalnum() and ch not in [' ', '.', '-', '_']:
                host_name = host_name.replace(ch, '-')

        # Storwize doesn't like hostname that doesn't starts with letter or _.
        if not re.match('^[A-Za-z]', host_name):
            host_name = '_' + host_name

        # Add a random 8-character suffix to avoid collisions
        rand_id = str(random.randint(0, 99999999)).zfill(8)
        host_name = '%s-%s' % (host_name[:55], rand_id)

        # Create a host with one port
        port = ports.pop(0)
        self.ssh.mkhost(host_name, port[0], port[1])

        # Add any additional ports to the host
        for port in ports:
            self.ssh.addhostport(host_name, port[0], port[1])

        LOG.debug('Leave: create_host: host %(host)s - %(host_name)s.',
                  {'host': connector['host'], 'host_name': host_name})
        return host_name

    def delete_host(self, host_name):
        self.ssh.rmhost(host_name)

    def map_vol_to_host(self, volume_name, host_name, multihostmap):
        """Create a mapping between a volume to a host."""

        LOG.debug('Enter: map_vol_to_host: volume %(volume_name)s to '
                  'host %(host_name)s.',
                  {'volume_name': volume_name, 'host_name': host_name})

        # Check if this volume is already mapped to this host
        mapped = False
        luns_used = []
        result_lun = '-1'
        resp = self.ssh.lshostvdiskmap(host_name)
        for mapping_info in resp:
            luns_used.append(int(mapping_info['SCSI_id']))
            if mapping_info['vdisk_name'] == volume_name:
                mapped = True
                result_lun = mapping_info['SCSI_id']

        if not mapped:
            # Find unused lun
            luns_used.sort()
            result_lun = str(len(luns_used))
            for index, n in enumerate(luns_used):
                if n > index:
                    result_lun = str(index)
                    break
            self.ssh.mkvdiskhostmap(host_name, volume_name, result_lun,
                                    multihostmap)

        LOG.debug('Leave: map_vol_to_host: LUN %(result_lun)s, volume '
                  '%(volume_name)s, host %(host_name)s.',
                  {'result_lun': result_lun,
                   'volume_name': volume_name,
                   'host_name': host_name})
        return int(result_lun)

    def unmap_vol_from_host(self, volume_name, host_name):
        """Unmap the volume and delete the host if it has no more mappings."""

        LOG.debug('Enter: unmap_vol_from_host: volume %(volume_name)s from '
                  'host %(host_name)s.',
                  {'volume_name': volume_name, 'host_name': host_name})

        # Check if the mapping exists
        resp = self.ssh.lsvdiskhostmap(volume_name)
        if not len(resp):
            LOG.warning(_LW('unmap_vol_from_host: No mapping of volume '
                            '%(vol_name)s to any host found.'),
                        {'vol_name': volume_name})
            return
        if host_name is None:
            if len(resp) > 1:
                LOG.warning(_LW('unmap_vol_from_host: Multiple mappings of '
                                'volume %(vol_name)s found, no host '
                                'specified.'), {'vol_name': volume_name})
                return
            else:
                host_name = resp[0]['host_name']
        else:
            found = False
            for h in resp.select('host_name'):
                if h == host_name:
                    found = True
            if not found:
                LOG.warning(_LW('unmap_vol_from_host: No mapping of volume '
                                '%(vol_name)s to host %(host)s found.'),
                            {'vol_name': volume_name, 'host': host_name})
        # We now know that the mapping exists
        self.ssh.rmvdiskhostmap(host_name, volume_name)

        LOG.debug('Leave: unmap_vol_from_host: volume %(volume_name)s from '
                  'host %(host_name)s.',
                  {'volume_name': volume_name, 'host_name': host_name})
        return host_name

    def check_host_mapped_vols(self, host_name):
        return self.ssh.lshostvdiskmap(host_name)

    @staticmethod
    def build_default_opts(config):
        # Ignore capitalization
        protocol = config.storwize_svc_connection_protocol
        if protocol.lower() == 'fc':
            protocol = 'FC'
        elif protocol.lower() == 'iscsi':
            protocol = 'iSCSI'

        cluster_partner = config.storwize_svc_stretched_cluster_partner
        opt = {'rsize': config.storwize_svc_vol_rsize,
               'warning': config.storwize_svc_vol_warning,
               'autoexpand': config.storwize_svc_vol_autoexpand,
               'grainsize': config.storwize_svc_vol_grainsize,
               'compression': config.storwize_svc_vol_compression,
               'easytier': config.storwize_svc_vol_easytier,
               'protocol': protocol,
               'multipath': config.storwize_svc_multipath_enabled,
               'iogrp': config.storwize_svc_vol_iogrp,
               'qos': None,
               'stretched_cluster': cluster_partner,
               'replication': False,
               'nofmtdisk': config.storwize_svc_vol_nofmtdisk}
        return opt

    @staticmethod
    def check_vdisk_opts(state, opts):
        # Check that grainsize is 32/64/128/256
        if opts['grainsize'] not in [32, 64, 128, 256]:
            raise exception.InvalidInput(
                reason=_('Illegal value specified for '
                         'storwize_svc_vol_grainsize: set to either '
                         '32, 64, 128, or 256.'))

        # Check that compression is supported
        if opts['compression'] and not state['compression_enabled']:
            raise exception.InvalidInput(
                reason=_('System does not support compression.'))

        # Check that rsize is set if compression is set
        if opts['compression'] and opts['rsize'] == -1:
            raise exception.InvalidInput(
                reason=_('If compression is set to True, rsize must '
                         'also be set (not equal to -1).'))

        # Check that the requested protocol is enabled
        if opts['protocol'] not in state['enabled_protocols']:
            raise exception.InvalidInput(
                reason=_('Illegal value %(prot)s specified for '
                         'storwize_svc_connection_protocol: '
                         'valid values are %(enabled)s.')
                % {'prot': opts['protocol'],
                   'enabled': ','.join(state['enabled_protocols'])})

        if opts['iogrp'] not in state['available_iogrps']:
            avail_grps = ''.join(str(e) for e in state['available_iogrps'])
            raise exception.InvalidInput(
                reason=_('I/O group %(iogrp)d is not valid; available '
                         'I/O groups are %(avail)s.')
                % {'iogrp': opts['iogrp'],
                   'avail': avail_grps})

        if opts['nofmtdisk'] and opts['rsize'] != -1:
            raise exception.InvalidInput(
                reason=_('If nofmtdisk is set to True, rsize must '
                         'also be set to -1.'))

    def _get_opts_from_specs(self, opts, specs):
        qos = {}
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
                words = value.split()
                if not (words and len(words) == 2 and words[0] == '<in>'):
                    LOG.error(_LE('Protocol must be specified as '
                                  '\'<in> iSCSI\' or \'<in> FC\'.'))
                del words[0]
                value = words[0]

            # We generally do not look at capabilities in the driver, but
            # replication is a special case where the user asks for
            # a volume to be replicated, and we want both the scheduler and
            # the driver to act on the value.
            if ((not scope or scope == 'capabilities') and
               key == 'replication'):
                scope = None
                key = 'replication'
                words = value.split()
                if not (words and len(words) == 2 and words[0] == '<is>'):
                    LOG.error(_LE('Replication must be specified as '
                                  '\'<is> True\' or \'<is> False\'.'))
                del words[0]
                value = words[0]

            # Add the QoS.
            if scope and scope == 'qos':
                if key in self.svc_qos_keys.keys():
                    try:
                        type_fn = self.svc_qos_keys[key]['type']
                        value = type_fn(value)
                        qos[key] = value
                    except ValueError:
                        continue

            # Any keys that the driver should look at should have the
            # 'drivers' scope.
            if scope and scope != 'drivers':
                continue
            if key in opts:
                this_type = type(opts[key]).__name__
                if this_type == 'int':
                    value = int(value)
                elif this_type == 'bool':
                    value = strutils.bool_from_string(value)
                opts[key] = value
        if len(qos) != 0:
            opts['qos'] = qos
        return opts

    def _get_qos_from_volume_metadata(self, volume_metadata):
        """Return the QoS information from the volume metadata."""
        qos = {}
        for i in volume_metadata:
            k = i.get('key', None)
            value = i.get('value', None)
            key_split = k.split(':')
            if len(key_split) == 1:
                scope = None
                key = key_split[0]
            else:
                scope = key_split[0]
                key = key_split[1]
            # Add the QoS.
            if scope and scope == 'qos':
                if key in self.svc_qos_keys.keys():
                    try:
                        type_fn = self.svc_qos_keys[key]['type']
                        value = type_fn(value)
                        qos[key] = value
                    except ValueError:
                        continue
        return qos

    def _wait_for_a_condition(self, testmethod, timeout=None,
                              interval=INTERVAL_1_SEC):
        start_time = time.time()
        if timeout is None:
            timeout = DEFAULT_TIMEOUT

        def _inner():
            try:
                testValue = testmethod()
            except Exception as ex:
                testValue = False
                LOG.debug('Helper.'
                          '_wait_for_condition: %(method_name)s '
                          'execution failed for %(exception)s.',
                          {'method_name': testmethod.__name__,
                           'exception': ex.message})
            if testValue:
                raise loopingcall.LoopingCallDone()

            if int(time.time()) - start_time > timeout:
                msg = (_('CommandLineHelper._wait_for_condition: %s timeout.')
                       % testmethod.__name__)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        timer = loopingcall.FixedIntervalLoopingCall(_inner)
        timer.start(interval=interval).wait()

    def get_vdisk_params(self, config, state, type_id, volume_type=None,
                         volume_metadata=None):
        """Return the parameters for creating the vdisk.

        Takes volume type and defaults from config options into account.
        """
        opts = self.build_default_opts(config)
        ctxt = context.get_admin_context()
        if volume_type is None and type_id is not None:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
        if volume_type:
            qos_specs_id = volume_type.get('qos_specs_id')
            specs = dict(volume_type).get('extra_specs')

            # NOTE(vhou): We prefer the qos_specs association
            # and over-ride any existing
            # extra-specs settings if present
            if qos_specs_id is not None:
                kvs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']
                # Merge the qos_specs into extra_specs and qos_specs has higher
                # priority than extra_specs if they have different values for
                # the same key.
                specs.update(kvs)
            opts = self._get_opts_from_specs(opts, specs)
        if (opts['qos'] is None and config.storwize_svc_allow_tenant_qos
                and volume_metadata):
            qos = self._get_qos_from_volume_metadata(volume_metadata)
            if len(qos) != 0:
                opts['qos'] = qos

        self.check_vdisk_opts(state, opts)
        return opts

    @staticmethod
    def _get_vdisk_create_params(opts):
        easytier = 'on' if opts['easytier'] else 'off'
        if opts['rsize'] == -1:
            params = []
            if opts['nofmtdisk']:
                params.append('-nofmtdisk')
        else:
            params = ['-rsize', '%s%%' % str(opts['rsize']),
                      '-autoexpand', '-warning',
                      '%s%%' % str(opts['warning'])]
            if not opts['autoexpand']:
                params.remove('-autoexpand')

            if opts['compression']:
                params.append('-compressed')
            else:
                params.extend(['-grainsize', str(opts['grainsize'])])

        params.extend(['-easytier', easytier])
        return params

    def create_vdisk(self, name, size, units, pool, opts):
        LOG.debug('Enter: create_vdisk: vdisk %s.', name)
        params = self._get_vdisk_create_params(opts)
        self.ssh.mkvdisk(name, size, units, pool, opts, params)
        LOG.debug('Leave: _create_vdisk: volume %s.', name)

    def get_vdisk_attributes(self, vdisk):
        attrs = self.ssh.lsvdisk(vdisk)
        return attrs

    def is_vdisk_defined(self, vdisk_name):
        """Check if vdisk is defined."""
        attrs = self.get_vdisk_attributes(vdisk_name)
        return attrs is not None

    def find_vdisk_copy_id(self, vdisk, pool):
        resp = self.ssh.lsvdiskcopy(vdisk)
        for copy_id, mdisk_grp in resp.select('copy_id', 'mdisk_grp_name'):
            if mdisk_grp == pool:
                return copy_id
        msg = _('Failed to find a vdisk copy in the expected pool.')
        LOG.error(msg)
        raise exception.VolumeDriverException(message=msg)

    def get_vdisk_copy_attrs(self, vdisk, copy_id):
        return self.ssh.lsvdiskcopy(vdisk, copy_id=copy_id)[0]

    def get_vdisk_copies(self, vdisk):
        copies = {'primary': None,
                  'secondary': None}

        resp = self.ssh.lsvdiskcopy(vdisk)
        for copy_id, status, sync, primary, mdisk_grp in (
            resp.select('copy_id', 'status', 'sync',
                        'primary', 'mdisk_grp_name')):
            copy = {'copy_id': copy_id,
                    'status': status,
                    'sync': sync,
                    'primary': primary,
                    'mdisk_grp_name': mdisk_grp,
                    'sync_progress': None}
            if copy['sync'] != 'yes':
                progress_info = self.ssh.lsvdisksyncprogress(vdisk, copy_id)
                copy['sync_progress'] = progress_info['progress']
            if copy['primary'] == 'yes':
                copies['primary'] = copy
            else:
                copies['secondary'] = copy
        return copies

    def _prepare_fc_map(self, fc_map_id, timeout):
        self.ssh.prestartfcmap(fc_map_id)
        mapping_ready = False
        wait_time = 5
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
                self.ssh.prestartfcmap(fc_map_id)
            elif mapping_attrs['status'] != 'preparing':
                msg = (_('Unexecpted mapping status %(status)s for mapping '
                         '%(id)s. Attributes: %(attr)s.')
                       % {'status': mapping_attrs['status'],
                          'id': fc_map_id,
                          'attr': mapping_attrs})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            greenthread.sleep(wait_time)

        if not mapping_ready:
            msg = (_('Mapping %(id)s prepare failed to complete within the'
                     'allotted %(to)d seconds timeout. Terminating.')
                   % {'id': fc_map_id,
                      'to': timeout})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def start_fc_consistgrp(self, fc_consistgrp):
        self.ssh.startfcconsistgrp(fc_consistgrp)

    def create_fc_consistgrp(self, fc_consistgrp):
        self.ssh.mkfcconsistgrp(fc_consistgrp)

    def delete_fc_consistgrp(self, fc_consistgrp):
        self.ssh.rmfcconsistgrp(fc_consistgrp)

    def stop_fc_consistgrp(self, fc_consistgrp):
        self.ssh.stopfcconsistgrp(fc_consistgrp)

    def run_consistgrp_snapshots(self, fc_consistgrp, snapshots, state,
                                 config, timeout):
        cgsnapshot = {'status': 'available'}
        try:
            for snapshot in snapshots:
                opts = self.get_vdisk_params(config, state,
                                             snapshot['volume_type_id'])
                self.create_flashcopy_to_consistgrp(snapshot['volume_name'],
                                                    snapshot['name'],
                                                    fc_consistgrp,
                                                    config, opts)
                snapshot['status'] = 'available'

            self.prepare_fc_consistgrp(fc_consistgrp, timeout)
            self.start_fc_consistgrp(fc_consistgrp)
            # There is CG limitation that could not create more than 128 CGs.
            # After start CG, we delete CG to avoid CG limitation.
            # Cinder general will maintain the CG and snapshots relationship.
            self.delete_fc_consistgrp(fc_consistgrp)
        except exception.VolumeBackendAPIException as err:
            for snapshot in snapshots:
                snapshot['status'] = 'error'
            cgsnapshot['status'] = 'error'
            # Release cg
            self.delete_fc_consistgrp(fc_consistgrp)
            LOG.error(_LE("Failed to create CGSnapshot. "
                          "Exception: %s."), err)

        return cgsnapshot, snapshots

    def delete_consistgrp_snapshots(self, fc_consistgrp, snapshots):
        """Delete flashcopy maps and consistent group."""
        cgsnapshot = {'status': 'available'}
        try:
            for snapshot in snapshots:
                self.ssh.rmvdisk(snapshot['name'], True)
                snapshot['status'] = 'deleted'
        except exception.VolumeBackendAPIException as err:
            for snapshot in snapshots:
                snapshot['status'] = 'error_deleting'
            cgsnapshot['status'] = 'error_deleting'
            LOG.error(_LE("Failed to delete the snapshot %(snap)s of "
                          "CGSnapshot. Exception: %(exception)s."),
                      {'snap': snapshot['name'], 'exception': err})
        return cgsnapshot, snapshots

    def prepare_fc_consistgrp(self, fc_consistgrp, timeout):
        """Prepare FC Consistency Group."""
        self.ssh.prestartfcconsistgrp(fc_consistgrp)

        def prepare_fc_consistgrp_success():
            mapping_ready = False
            mapping_attrs = self._get_flashcopy_consistgrp_attr(fc_consistgrp)
            if (mapping_attrs is None or
                    'status' not in mapping_attrs):
                pass
            if mapping_attrs['status'] == 'prepared':
                mapping_ready = True
            elif mapping_attrs['status'] == 'stopped':
                self.ssh.prestartfcconsistgrp(fc_consistgrp)
            elif mapping_attrs['status'] != 'preparing':
                msg = (_('Unexpected mapping status %(status)s for mapping'
                         '%(id)s. Attributes: %(attr)s.') %
                       {'status': mapping_attrs['status'],
                        'id': fc_consistgrp,
                        'attr': mapping_attrs})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            return mapping_ready
        self._wait_for_a_condition(prepare_fc_consistgrp_success, timeout)

    def run_flashcopy(self, source, target, timeout, full_copy=True):
        """Create a FlashCopy mapping from the source to the target."""
        LOG.debug('Enter: run_flashcopy: execute FlashCopy from source '
                  '%(source)s to target %(target)s.',
                  {'source': source, 'target': target})

        fc_map_id = self.ssh.mkfcmap(source, target, full_copy)
        self._prepare_fc_map(fc_map_id, timeout)
        self.ssh.startfcmap(fc_map_id)

        LOG.debug('Leave: run_flashcopy: FlashCopy started from '
                  '%(source)s to %(target)s.',
                  {'source': source, 'target': target})

    def create_flashcopy_to_consistgrp(self, source, target, consistgrp,
                                       config, opts, full_copy=False,
                                       pool=None):
        """Create a FlashCopy mapping and add to consistent group."""
        LOG.debug('Enter: create_flashcopy_to_consistgrp: create FlashCopy'
                  ' from source %(source)s to target %(target)s'
                  'Then add the flashcopy to %(cg)s.',
                  {'source': source, 'target': target, 'cg': consistgrp})

        src_attrs = self.get_vdisk_attributes(source)
        if src_attrs is None:
            msg = (_('create_copy: Source vdisk %(src)s '
                     'does not exist.') % {'src': source})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        src_size = src_attrs['capacity']
        # In case we need to use a specific pool
        if not pool:
            pool = config.storwize_svc_volpool_name
        self.create_vdisk(target, src_size, 'b', pool, opts)

        self.ssh.mkfcmap(source, target, full_copy, consistgrp)

        LOG.debug('Leave: create_flashcopy_to_consistgrp: '
                  'FlashCopy started from  %(source)s to %(target)s.',
                  {'source': source, 'target': target})

    def _get_vdisk_fc_mappings(self, vdisk):
        """Return FlashCopy mappings that this vdisk is associated with."""
        mapping_ids = []
        resp = self.ssh.lsvdiskfcmappings(vdisk)
        for id in resp.select('id'):
            mapping_ids.append(id)
        return mapping_ids

    def _get_flashcopy_mapping_attributes(self, fc_map_id):
        resp = self.ssh.lsfcmap(fc_map_id)
        if not len(resp):
            return None
        return resp[0]

    def _get_flashcopy_consistgrp_attr(self, fc_map_id):
        resp = self.ssh.lsfcconsistgrp(fc_map_id)
        if not len(resp):
            return None
        return resp[0]

    def _check_vdisk_fc_mappings(self, name, allow_snaps=True):
        """FlashCopy mapping check helper."""
        LOG.debug('Loopcall: _check_vdisk_fc_mappings(), vdisk %s.', name)
        mapping_ids = self._get_vdisk_fc_mappings(name)
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
                if source == name:
                    # Vdisk with snapshots. Return False if snapshot
                    # not allowed.
                    if not allow_snaps:
                        raise loopingcall.LoopingCallDone(retvalue=False)
                    self.ssh.chfcmap(map_id, copyrate='50', autodel='on')
                    wait_for_copy = True
                else:
                    # A snapshot
                    if target != name:
                        msg = (_('Vdisk %(name)s not involved in '
                                 'mapping %(src)s -> %(tgt)s.') %
                               {'name': name, 'src': source, 'tgt': target})
                        LOG.error(msg)
                        raise exception.VolumeDriverException(message=msg)
                    if status in ['copying', 'prepared']:
                        self.ssh.stopfcmap(map_id)
                        # Need to wait for the fcmap to change to
                        # stopped state before remove fcmap
                        wait_for_copy = True
                    elif status in ['stopping', 'preparing']:
                        wait_for_copy = True
                    else:
                        self.ssh.rmfcmap(map_id)
            # Case 4: Copy in progress - wait and will autodelete
            else:
                if status == 'prepared':
                    self.ssh.stopfcmap(map_id)
                    self.ssh.rmfcmap(map_id)
                elif status == 'idle_or_copied':
                    # Prepare failed
                    self.ssh.rmfcmap(map_id)
                else:
                    wait_for_copy = True
        if not wait_for_copy or not len(mapping_ids):
            raise loopingcall.LoopingCallDone(retvalue=True)

    def ensure_vdisk_no_fc_mappings(self, name, allow_snaps=True):
        """Ensure vdisk has no flashcopy mappings."""
        timer = loopingcall.FixedIntervalLoopingCall(
            self._check_vdisk_fc_mappings, name, allow_snaps)
        # Create a timer greenthread. The default volume service heart
        # beat is every 10 seconds. The flashcopy usually takes hours
        # before it finishes. Don't set the sleep interval shorter
        # than the heartbeat. Otherwise volume service heartbeat
        # will not be serviced.
        LOG.debug('Calling _ensure_vdisk_no_fc_mappings: vdisk %s.',
                  name)
        ret = timer.start(interval=self.check_fcmapping_interval).wait()
        timer.stop()
        return ret

    def delete_vdisk(self, vdisk, force):
        """Ensures that vdisk is not part of FC mapping and deletes it."""
        LOG.debug('Enter: delete_vdisk: vdisk %s.', vdisk)
        if not self.is_vdisk_defined(vdisk):
            LOG.info(_LI('Tried to delete non-existent vdisk %s.'), vdisk)
            return
        self.ensure_vdisk_no_fc_mappings(vdisk)
        self.ssh.rmvdisk(vdisk, force=force)
        LOG.debug('Leave: delete_vdisk: vdisk %s.', vdisk)

    def create_copy(self, src, tgt, src_id, config, opts,
                    full_copy, pool=None):
        """Create a new snapshot using FlashCopy."""
        LOG.debug('Enter: create_copy: snapshot %(src)s to %(tgt)s.',
                  {'tgt': tgt, 'src': src})

        src_attrs = self.get_vdisk_attributes(src)
        if src_attrs is None:
            msg = (_('create_copy: Source vdisk %(src)s (%(src_id)s) '
                     'does not exist.') % {'src': src, 'src_id': src_id})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        src_size = src_attrs['capacity']
        # In case we need to use a specific pool
        if not pool:
            pool = config.storwize_svc_volpool_name
        self.create_vdisk(tgt, src_size, 'b', pool, opts)
        timeout = config.storwize_svc_flashcopy_timeout
        try:
            self.run_flashcopy(src, tgt, timeout, full_copy=full_copy)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.delete_vdisk(tgt, True)

        LOG.debug('Leave: _create_copy: snapshot %(tgt)s from '
                  'vdisk %(src)s.',
                  {'tgt': tgt, 'src': src})

    def extend_vdisk(self, vdisk, amount):
        self.ssh.expandvdisksize(vdisk, amount)

    def add_vdisk_copy(self, vdisk, dest_pool, volume_type, state, config):
        """Add a vdisk copy in the given pool."""
        resp = self.ssh.lsvdiskcopy(vdisk)
        if len(resp) > 1:
            msg = (_('add_vdisk_copy failed: A copy of volume %s exists. '
                     'Adding another copy would exceed the limit of '
                     '2 copies.') % vdisk)
            raise exception.VolumeDriverException(message=msg)
        orig_copy_id = resp[0].get("copy_id", None)

        if orig_copy_id is None:
            msg = (_('add_vdisk_copy started without a vdisk copy in the '
                     'expected pool.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        if volume_type is None:
            opts = self.get_vdisk_params(config, state, None)
        else:
            opts = self.get_vdisk_params(config, state, volume_type['id'],
                                         volume_type=volume_type)
        params = self._get_vdisk_create_params(opts)
        new_copy_id = self.ssh.addvdiskcopy(vdisk, dest_pool, params)
        return (orig_copy_id, new_copy_id)

    def is_vdisk_copy_synced(self, vdisk, copy_id):
        sync = self.ssh.lsvdiskcopy(vdisk, copy_id=copy_id)[0]['sync']
        if sync == 'yes':
            return True
        return False

    def rm_vdisk_copy(self, vdisk, copy_id):
        self.ssh.rmvdiskcopy(vdisk, copy_id)

    @staticmethod
    def can_migrate_to_host(host, state):
        if 'location_info' not in host['capabilities']:
            return None
        info = host['capabilities']['location_info']
        try:
            (dest_type, dest_id, dest_pool) = info.split(':')
        except ValueError:
            return None
        if (dest_type != 'StorwizeSVCDriver' or dest_id != state['system_id']):
            return None
        return dest_pool

    def add_vdisk_qos(self, vdisk, qos):
        """Add the QoS configuration to the volume."""
        for key, value in qos.items():
            if key in self.svc_qos_keys.keys():
                param = self.svc_qos_keys[key]['param']
                self.ssh.chvdisk(vdisk, ['-' + param, str(value)])

    def update_vdisk_qos(self, vdisk, qos):
        """Update all the QoS in terms of a key and value.

        svc_qos_keys saves all the supported QoS parameters. Going through
        this dict, we set the new values to all the parameters. If QoS is
        available in the QoS configuration, the value is taken from it;
        if not, the value will be set to default.
        """
        for key, value in self.svc_qos_keys.items():
            param = value['param']
            if key in qos.keys():
                # If the value is set in QoS, take the value from
                # the QoS configuration.
                v = qos[key]
            else:
                # If not, set the value to default.
                v = value['default']
            self.ssh.chvdisk(vdisk, ['-' + param, str(v)])

    def disable_vdisk_qos(self, vdisk, qos):
        """Disable the QoS."""
        for key, value in qos.items():
            if key in self.svc_qos_keys.keys():
                param = self.svc_qos_keys[key]['param']
                # Take the default value.
                value = self.svc_qos_keys[key]['default']
                self.ssh.chvdisk(vdisk, ['-' + param, value])

    def change_vdisk_options(self, vdisk, changes, opts, state):
        if 'warning' in opts:
            opts['warning'] = '%s%%' % str(opts['warning'])
        if 'easytier' in opts:
            opts['easytier'] = 'on' if opts['easytier'] else 'off'
        if 'autoexpand' in opts:
            opts['autoexpand'] = 'on' if opts['autoexpand'] else 'off'

        for key in changes:
            self.ssh.chvdisk(vdisk, ['-' + key, opts[key]])

    def change_vdisk_iogrp(self, vdisk, state, iogrp):
        if state['code_level'] < (6, 4, 0, 0):
            LOG.debug('Ignore change IO group as storage code level is '
                      '%(code_level)s, below the required 6.4.0.0.',
                      {'code_level': state['code_level']})
        else:
            self.ssh.movevdisk(vdisk, str(iogrp[0]))
            self.ssh.addvdiskaccess(vdisk, str(iogrp[0]))
            self.ssh.rmvdiskaccess(vdisk, str(iogrp[1]))

    def vdisk_by_uid(self, vdisk_uid):
        """Returns the properties of the vdisk with the specified UID.

        Returns None if no such disk exists.
        """

        vdisks = self.ssh.lsvdisks_from_filter('vdisk_UID', vdisk_uid)

        if len(vdisks) == 0:
            return None

        if len(vdisks) != 1:
            msg = (_('Expected single vdisk returned from lsvdisk when '
                     'filtering on vdisk_UID.  %(count)s were returned.') %
                   {'count': len(vdisks)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        vdisk = vdisks.result[0]

        return self.ssh.lsvdisk(vdisk['name'])

    def is_vdisk_in_use(self, vdisk):
        """Returns True if the specified vdisk is mapped to at least 1 host."""
        resp = self.ssh.lsvdiskhostmap(vdisk)
        return len(resp) != 0

    def rename_vdisk(self, vdisk, new_name):
        self.ssh.chvdisk(vdisk, ['-name', new_name])

    def change_vdisk_primary_copy(self, vdisk, copy_id):
        self.ssh.chvdisk(vdisk, ['-primary', copy_id])


class CLIResponse(object):
    """Parse SVC CLI output and generate iterable."""

    def __init__(self, raw, ssh_cmd=None, delim='!', with_header=True):
        super(CLIResponse, self).__init__()
        if ssh_cmd:
            self.ssh_cmd = ' '.join(ssh_cmd)
        else:
            self.ssh_cmd = 'None'
        self.raw = raw
        self.delim = delim
        self.with_header = with_header
        self.result = self._parse()

    def select(self, *keys):
        for a in self.result:
            vs = []
            for k in keys:
                v = a.get(k, None)
                if isinstance(v, six.string_types) or v is None:
                    v = [v]
                if isinstance(v, list):
                    vs.append(v)
            for item in zip(*vs):
                if len(item) == 1:
                    yield item[0]
                else:
                    yield item

    def __getitem__(self, key):
        try:
            return self.result[key]
        except KeyError:
            msg = (_('Did not find the expected key %(key)s in %(fun)s: '
                     '%(raw)s.') % {'key': key, 'fun': self.ssh_cmd,
                                    'raw': self.raw})
            raise exception.VolumeBackendAPIException(data=msg)

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

        if isinstance(self.raw, six.string_types):
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
                if len(hds) != len(row):
                    msg = (_('Unexpected CLI response: header/row mismatch. '
                             'header: %(header)s, row: %(row)s.')
                           % {'header': hds,
                              'row': row})
                    raise exception.VolumeBackendAPIException(data=msg)
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
