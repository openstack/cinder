# Copyright 2015 IBM Corp.
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
Volume driver for IBM FlashSystem storage systems with iSCSI protocol.

Limitations:
1. Cinder driver only works when open_access_enabled=off.

"""

import random
import threading

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.ibm import flashsystem_common as fscommon
from cinder.volume.drivers.san import san

LOG = logging.getLogger(__name__)

flashsystem_iscsi_opts = [
    cfg.IntOpt('flashsystem_iscsi_portid',
               default=0,
               help='Default iSCSI Port ID of FlashSystem. '
                    '(Default port is 0.)')
]

CONF = cfg.CONF
CONF.register_opts(flashsystem_iscsi_opts, group=conf.SHARED_CONF_GROUP)


@interface.volumedriver
class FlashSystemISCSIDriver(fscommon.FlashSystemDriver):
    """IBM FlashSystem iSCSI volume driver.

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

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "IBM_STORAGE_CI"

    def __init__(self, *args, **kwargs):
        super(FlashSystemISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(fscommon.flashsystem_opts)
        self.configuration.append_config_values(flashsystem_iscsi_opts)
        self.configuration.append_config_values(san.san_opts)

    def _check_vdisk_params(self, params):
        # Check that the requested protocol is enabled
        if not params['protocol'] in self._protocol:
            msg = (_("'%(prot)s' is invalid for "
                     "flashsystem_connection_protocol "
                     "in config file. valid value(s) are "
                     "%(enabled)s.")
                   % {'prot': params['protocol'],
                      'enabled': self._protocol})
            raise exception.InvalidInput(reason=msg)

        # Check if iscsi_ip is set when protocol is iSCSI
        if params['protocol'] == 'iSCSI' and params['iscsi_ip'] == 'None':
            msg = _("iscsi_ip_address must be set in config file when "
                    "using protocol 'iSCSI'.")
            raise exception.InvalidInput(reason=msg)

    def _create_host(self, connector):
        """Create a new host on the storage system.

        We create a host and associate it with the given connection
        information.
        """

        LOG.debug('enter: _create_host: host %s.', connector['host'])

        rand_id = six.text_type(random.randint(0, 99999999)).zfill(8)
        host_name = '%s-%s' % (self._connector_to_hostname_prefix(connector),
                               rand_id)

        ports = []

        if 'iSCSI' == self._protocol and 'initiator' in connector:
            ports.append('-iscsiname %s' % connector['initiator'])

        self._driver_assert(ports,
                            (_('_create_host: No connector ports.')))
        port1 = ports.pop(0)
        arg_name, arg_val = port1.split()
        ssh_cmd = ['svctask', 'mkhost', '-force', arg_name, arg_val, '-name',
                   '"%s"' % host_name]
        out, err = self._ssh(ssh_cmd)
        self._assert_ssh_return('successfully created' in out,
                                '_create_host', ssh_cmd, out, err)

        for port in ports:
            arg_name, arg_val = port.split()
            ssh_cmd = ['svctask', 'addhostport', '-force',
                       arg_name, arg_val, host_name]
            out, err = self._ssh(ssh_cmd)
            self._assert_ssh_return(
                (not out.strip()),
                '_create_host', ssh_cmd, out, err)

        LOG.debug(
            'leave: _create_host: host %(host)s - %(host_name)s.',
            {'host': connector['host'], 'host_name': host_name})

        return host_name

    def _find_host_exhaustive(self, connector, hosts):
        LOG.debug('enter: _find_host_exhaustive hosts: %s.', hosts)
        hname = connector['host']
        hnames = [ihost[0:ihost.rfind('-')] for ihost in hosts]
        if hname in hnames:
            host = hosts[hnames.index(hname)]
            ssh_cmd = ['svcinfo', 'lshost', '-delim', '!', host]
            out, err = self._ssh(ssh_cmd)
            self._assert_ssh_return(
                out.strip(),
                '_find_host_exhaustive', ssh_cmd, out, err)
            for attr_line in out.split('\n'):
                attr_name, foo, attr_val = attr_line.partition('!')
                if (attr_name == 'iscsi_name' and
                        'initiator' in connector and
                        attr_val == connector['initiator']):
                    LOG.debug(
                        'leave: _find_host_exhaustive connector: %s.',
                        connector)
                    return host
        else:
            LOG.warning('Host %(host)s was not found on backend storage.',
                        {'host': hname})
        return None

    def _get_vdisk_map_properties(
            self, connector, lun_id, vdisk_name, vdisk_id, vdisk_params):
        """Get the map properties of vdisk."""

        LOG.debug(
            'enter: _get_vdisk_map_properties: vdisk '
            '%(vdisk_name)s.', {'vdisk_name': vdisk_name})

        preferred_node = '0'
        IO_group = '0'

        # Get preferred node and other nodes in I/O group
        preferred_node_entry = None
        io_group_nodes = []
        for k, node in self._storage_nodes.items():
            if vdisk_params['protocol'] != node['protocol']:
                continue
            if node['id'] == preferred_node:
                preferred_node_entry = node
            if node['IO_group'] == IO_group:
                io_group_nodes.append(node)

        if not io_group_nodes:
            msg = (_('No node found in I/O group %(gid)s for volume %(vol)s.')
                   % {'gid': IO_group, 'vol': vdisk_name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if not preferred_node_entry:
            # Get 1st node in I/O group
            preferred_node_entry = io_group_nodes[0]
            LOG.warning('_get_vdisk_map_properties: Did not find a '
                        'preferred node for vdisk %s.', vdisk_name)
        properties = {
            'target_discovered': False,
            'target_lun': lun_id,
            'volume_id': vdisk_id,
        }

        type_str = 'iscsi'
        if preferred_node_entry['ipv4']:
            ipaddr = preferred_node_entry['ipv4'][0]
        else:
            ipaddr = preferred_node_entry['ipv6'][0]
        iscsi_port = self.configuration.iscsi_port
        properties['target_portal'] = '%s:%s' % (ipaddr, iscsi_port)
        properties['target_iqn'] = preferred_node_entry['iscsi_name']

        LOG.debug(
            'leave: _get_vdisk_map_properties: vdisk '
            '%(vdisk_name)s.', {'vdisk_name': vdisk_name})

        return {'driver_volume_type': type_str, 'data': properties}

    @utils.synchronized('flashsystem-init-conn', external=True)
    def initialize_connection(self, volume, connector):
        """Perform work so that an iSCSI connection can be made.

        To be able to create an iSCSI connection from a given host to a
        volume, we must:
        1. Translate the given iSCSI name to a host name
        2. Create new host on the storage system if it does not yet exist
        3. Map the volume to the host if it is not already done
        4. Return the connection information for relevant nodes (in the
        proper I/O group)

        """

        LOG.debug(
            'enter: initialize_connection: volume %(vol)s with '
            'connector %(conn)s.', {'vol': volume, 'conn': connector})

        vdisk_name = volume['name']
        vdisk_id = volume['id']
        vdisk_params = self._get_vdisk_params(volume['volume_type_id'])

        self._wait_vdisk_copy_completed(vdisk_name)

        self._driver_assert(
            self._is_vdisk_defined(vdisk_name),
            (_('vdisk %s is not defined.')
             % vdisk_name))

        lun_id = self._map_vdisk_to_host(vdisk_name, connector)

        properties = {}
        try:
            properties = self._get_vdisk_map_properties(
                connector, lun_id, vdisk_name, vdisk_id, vdisk_params)
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                self.terminate_connection(volume, connector)
                LOG.error('Failed to collect return properties for '
                          'volume %(vol)s and connector %(conn)s.',
                          {'vol': volume, 'conn': connector})

        LOG.debug(
            'leave: initialize_connection:\n volume: %(vol)s\n connector '
            '%(conn)s\n properties: %(prop)s.',
            {'vol': volume,
             'conn': connector,
             'prop': properties})

        return properties

    @utils.synchronized('flashsystem-term-conn', external=True)
    def terminate_connection(self, volume, connector, **kwargs):
        """Cleanup after connection has been terminated.

        When we clean up a terminated connection between a given connector
        and volume, we:
        1. Translate the given connector to a host name
        2. Remove the volume-to-host mapping if it exists
        3. Delete the host if it has no more mappings (hosts are created
        automatically by this driver when mappings are created)
        """
        LOG.debug(
            'enter: terminate_connection: volume %(vol)s with '
            'connector %(conn)s.',
            {'vol': volume, 'conn': connector})

        vdisk_name = volume['name']
        self._wait_vdisk_copy_completed(vdisk_name)
        host_name = self._unmap_vdisk_from_host(vdisk_name, connector)
        # checking if host_name none, if not then, check if the host has
        # any mappings, if not the host gets deleted.
        if host_name:
            if not self._get_hostvdisk_mappings(host_name):
                self._delete_host(host_name)

        LOG.debug(
            'leave: terminate_connection: volume %(vol)s with '
            'connector %(conn)s.', {'vol': volume, 'conn': connector})

        return {'driver_volume_type': 'iscsi'}

    def _get_iscsi_ip_addrs(self):
        """get ip address of iSCSI interface."""

        LOG.debug('enter: _get_iscsi_ip_addrs')

        cmd = ['svcinfo', 'lsportip']
        generator = self._port_conf_generator(cmd)
        header = next(generator, None)
        if not header:
            return

        for key in self._storage_nodes:
            if self._storage_nodes[key]['config_node'] == 'yes':
                node = self._storage_nodes[key]
                break

        if node is None:
            msg = _('No config node found.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        for port_data in generator:
            try:
                port_ipv4 = port_data['IP_address']
                port_ipv6 = port_data['IP_address_6']
                state = port_data['state']
                speed = port_data['speed']
            except KeyError:
                self._handle_keyerror('lsportip', header)
            if port_ipv4 == self.configuration.iscsi_ip_address and (
                    port_data['id'] == (
                        six.text_type(
                            self.configuration.flashsystem_iscsi_portid))):
                if state not in ('configured', 'online'):
                    msg = (_('State of node is wrong. Current state is %s.')
                           % state)
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
                if state in ('configured', 'online') and speed != 'NONE':
                    if port_ipv4:
                        node['ipv4'].append(port_ipv4)
                    if port_ipv6:
                        node['ipv6'].append(port_ipv6)
                    break
        if not (len(node['ipv4']) or len(node['ipv6'])):
            msg = _('No ip address found.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('leave: _get_iscsi_ip_addrs')

    def do_setup(self, ctxt):
        """Check that we have all configuration details from the storage."""

        LOG.debug('enter: do_setup')

        self._context = ctxt

        # Get data of configured node
        self._get_node_data()

        # Get the iSCSI IP addresses of the FlashSystem nodes
        self._get_iscsi_ip_addrs()

        for k, node in self._storage_nodes.items():
            if self.configuration.flashsystem_connection_protocol == 'iSCSI':
                if (len(node['ipv4']) or len(node['ipv6']) and
                        len(node['iscsi_name'])):
                    node['protocol'] = 'iSCSI'

        self._protocol = 'iSCSI'

        # Set for vdisk synchronization
        self._vdisk_copy_in_progress = set()
        self._vdisk_copy_lock = threading.Lock()
        self._check_lock_interval = 5

        LOG.debug('leave: do_setup')

    def _build_default_params(self):
        protocol = self.configuration.flashsystem_connection_protocol
        if protocol.lower() == 'iscsi':
            protocol = 'iSCSI'
        return {
            'protocol': protocol,
            'iscsi_ip': self.configuration.iscsi_ip_address,
            'iscsi_port': self.configuration.iscsi_port,
            'iscsi_ported': self.configuration.flashsystem_iscsi_portid,
        }

    def validate_connector(self, connector):
        """Check connector for enabled protocol."""
        valid = False
        if 'iSCSI' == self._protocol and 'initiator' in connector:
            valid = True
        if not valid:
            LOG.error('The connector does not contain the '
                      'required information: initiator is missing')
            raise exception.InvalidConnectorException(missing=(
                                                      'initiator'))
