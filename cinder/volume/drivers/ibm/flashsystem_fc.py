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
Volume driver for IBM FlashSystem storage systems with FC protocol.

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
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils
import cinder.volume.driver
from cinder.volume.drivers.ibm import flashsystem_common as fscommon
from cinder.volume.drivers.san import san
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)

flashsystem_fc_opts = [
    cfg.BoolOpt('flashsystem_multipath_enabled',
                default=False,
                help='Connect with multipath (FC only).'
                     '(Default is false.)')
]

CONF = cfg.CONF
CONF.register_opts(flashsystem_fc_opts)


class FlashSystemFCDriver(fscommon.FlashSystemDriver,
                          cinder.volume.driver.FibreChannelDriver):
    """IBM FlashSystem FC volume driver.

    Version history:
    1.0.0 - Initial driver
    1.0.1 - Code clean up
    1.0.2 - Add lock into vdisk map/unmap, connection
            initialize/terminate
    1.0.3 - Initial driver for iSCSI
    1.0.4 - Split Flashsystem driver into common and FC
    1.0.5 - Report capability of volume multiattach
    1.0.6 - Fix bug #1469581, add I/T mapping check in
            terminate_connection

    """

    VERSION = "1.0.6"

    def __init__(self, *args, **kwargs):
        super(FlashSystemFCDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(fscommon.flashsystem_opts)
        self.configuration.append_config_values(flashsystem_fc_opts)
        self.configuration.append_config_values(san.san_opts)

    def _check_vdisk_params(self, params):
        # Check that the requested protocol is enabled
        if params['protocol'] != self._protocol:
            msg = (_("Illegal value '%(prot)s' specified for "
                     "flashsystem_connection_protocol: "
                     "valid value(s) are %(enabled)s.")
                   % {'prot': params['protocol'],
                      'enabled': self._protocol})
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
        if 'FC' == self._protocol and 'wwpns' in connector:
            for wwpn in connector['wwpns']:
                ports.append('-hbawwpn %s' % wwpn)

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
        for host in hosts:
            ssh_cmd = ['svcinfo', 'lshost', '-delim', '!', host]
            out, err = self._ssh(ssh_cmd)
            self._assert_ssh_return(
                out.strip(),
                '_find_host_exhaustive', ssh_cmd, out, err)
            for attr_line in out.split('\n'):
                # If '!' not found, return the string and two empty strings
                attr_name, foo, attr_val = attr_line.partition('!')
                if (attr_name == 'WWPN' and
                        'wwpns' in connector and attr_val.lower() in
                        map(str.lower, map(str, connector['wwpns']))):
                    return host
        return None

    def _get_conn_fc_wwpns(self):
        wwpns = []

        cmd = ['svcinfo', 'lsportfc']

        generator = self._port_conf_generator(cmd)
        header = next(generator, None)
        if not header:
            return wwpns

        for port_data in generator:
            try:
                if port_data['status'] == 'active':
                    wwpns.append(port_data['WWPN'])
            except KeyError:
                self._handle_keyerror('lsportfc', header)

        return wwpns

    def _get_fc_wwpns(self):
        for key in self._storage_nodes:
            node = self._storage_nodes[key]
            ssh_cmd = ['svcinfo', 'lsnode', '-delim', '!', node['id']]
            attributes = self._execute_command_and_parse_attributes(ssh_cmd)
            wwpns = set(node['WWPN'])
            for i, s in zip(attributes['port_id'], attributes['port_status']):
                if 'unconfigured' != s:
                    wwpns.add(i)
            node['WWPN'] = list(wwpns)
            LOG.info(_LI('WWPN on node %(node)s: %(wwpn)s.'),
                     {'node': node['id'], 'wwpn': node['WWPN']})

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
            msg = (_('_get_vdisk_map_properties: No node found in '
                     'I/O group %(gid)s for volume %(vol)s.')
                   % {'gid': IO_group, 'vol': vdisk_name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if not preferred_node_entry and not vdisk_params['multipath']:
            # Get 1st node in I/O group
            preferred_node_entry = io_group_nodes[0]
            LOG.warning(_LW('_get_vdisk_map_properties: Did not find a '
                            'preferred node for vdisk %s.'), vdisk_name)
        properties = {}
        properties['target_discovered'] = False
        properties['target_lun'] = lun_id
        properties['volume_id'] = vdisk_id

        type_str = 'fibre_channel'
        conn_wwpns = self._get_conn_fc_wwpns()

        if not conn_wwpns:
            msg = _('_get_vdisk_map_properties: Could not get FC '
                    'connection information for the host-volume '
                    'connection. Is the host configured properly '
                    'for FC connections?')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        properties['target_wwn'] = conn_wwpns

        if "zvm_fcp" in connector:
            properties['zvm_fcp'] = connector['zvm_fcp']

        properties['initiator_target_map'] = self._build_initiator_target_map(
            connector['wwpns'], conn_wwpns)

        LOG.debug(
            'leave: _get_vdisk_map_properties: vdisk '
            '%(vdisk_name)s.', {'vdisk_name': vdisk_name})

        return {'driver_volume_type': type_str, 'data': properties}

    @fczm_utils.AddFCZone
    @utils.synchronized('flashsystem-init-conn', external=True)
    def initialize_connection(self, volume, connector):
        """Perform work so that an FC connection can be made.

        To be able to create a FC connection from a given host to a
        volume, we must:
        1. Translate the given WWNN to a host name
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

        # TODO(edwin): might fix it after vdisk copy function is
        # ready in FlashSystem thin-provision layer. As this validation
        # is to check the vdisk which is in copying, at present in firmware
        # level vdisk doesn't allow to map host which it is copy. New
        # vdisk clone and snapshot function will cover it. After that the
        # _wait_vdisk_copy_completed need some modification.
        self._wait_vdisk_copy_completed(vdisk_name)

        self._driver_assert(
            self._is_vdisk_defined(vdisk_name),
            (_('initialize_connection: vdisk %s is not defined.')
             % vdisk_name))

        lun_id = self._map_vdisk_to_host(vdisk_name, connector)

        properties = {}
        try:
            properties = self._get_vdisk_map_properties(
                connector, lun_id, vdisk_name, vdisk_id, vdisk_params)
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                self.terminate_connection(volume, connector)
                LOG.error(_LE('initialize_connection: Failed to collect '
                              'return properties for volume %(vol)s and '
                              'connector %(conn)s.'),
                          {'vol': volume, 'conn': connector})

        LOG.debug(
            'leave: initialize_connection:\n volume: %(vol)s\n connector '
            '%(conn)s\n properties: %(prop)s.',
            {'vol': volume,
             'conn': connector,
             'prop': properties})

        return properties

    @fczm_utils.RemoveFCZone
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

        return_data = {
            'driver_volume_type': 'fibre_channel',
            'data': {},
        }

        vdisk_name = volume['name']
        self._wait_vdisk_copy_completed(vdisk_name)
        self._unmap_vdisk_from_host(vdisk_name, connector)

        host_name = self._get_host_from_connector(connector)
        if not host_name:
            properties = {}
            conn_wwpns = self._get_conn_fc_wwpns()
            properties['target_wwn'] = conn_wwpns
            properties['initiator_target_map'] = (
                self._build_initiator_target_map(
                    connector['wwpns'], conn_wwpns))
            return_data['data'] = properties

        LOG.debug(
            'leave: terminate_connection: volume %(vol)s with '
            'connector %(conn)s.', {'vol': volume, 'conn': connector})

        return return_data

    def do_setup(self, ctxt):
        """Check that we have all configuration details from the storage."""

        self._context = ctxt

        # Get data of configured node
        self._get_node_data()

        # Get the WWPNs of the FlashSystem nodes
        self._get_fc_wwpns()

        # For each node, check what connection modes it supports.  Delete any
        # nodes that do not support any types (may be partially configured).
        to_delete = []
        for k, node in self._storage_nodes.items():
            if not node['WWPN']:
                to_delete.append(k)

        for delkey in to_delete:
            del self._storage_nodes[delkey]

        # Make sure we have at least one node configured
        self._driver_assert(self._storage_nodes,
                            'do_setup: No configured nodes.')

        self._protocol = node['protocol'] = 'FC'

        # Set for vdisk synchronization
        self._vdisk_copy_in_progress = set()
        self._vdisk_copy_lock = threading.Lock()
        self._check_lock_interval = 5

    def validate_connector(self, connector):
        """Check connector."""
        if 'FC' == self._protocol and 'wwpns' not in connector:
            msg = _LE('The connector does not contain the '
                      'required information: wwpns is missing')
            LOG.error(msg)
            raise exception.InvalidConnectorException(missing='wwpns')
