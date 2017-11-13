# Copyright 2015 IBM Corp.
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
"""
Volume FC driver for IBM Storwize family and SVC storage systems.

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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import configuration
from cinder.volume.drivers.ibm.storwize_svc import (
    storwize_svc_common as storwize_common)
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)

storwize_svc_fc_opts = [
    cfg.BoolOpt('storwize_svc_multipath_enabled',
                default=False,
                help='Connect with multipath (FC only; iSCSI multipath is '
                     'controlled by Nova)'),
]

CONF = cfg.CONF
CONF.register_opts(storwize_svc_fc_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class StorwizeSVCFCDriver(storwize_common.StorwizeSVCCommonDriver):
    """IBM Storwize V7000 and SVC FC volume driver.

    Version history:

    .. code-block:: none

        1.0 - Initial driver
        1.1 - FC support, create_cloned_volume, volume type support,
              get_volume_stats, minor bug fixes
        1.2.0 - Added retype
        1.2.1 - Code refactor, improved exception handling
        1.2.2 - Fix bug #1274123 (races in host-related functions)
        1.2.3 - Fix Fibre Channel connectivity: bug #1279758 (add delim
                to lsfabric, clear unused data from connections, ensure
                matching WWPNs by comparing lower case
        1.2.4 - Fix bug #1278035 (async migration/retype)
        1.2.5 - Added support for manage_existing (unmanage is inherited)
        1.2.6 - Added QoS support in terms of I/O throttling rate
        1.3.1 - Added support for volume replication
        1.3.2 - Added support for consistency group
        1.3.3 - Update driver to use ABC metaclasses
        2.0 - Code refactor, split init file and placed shared methods
              for FC and iSCSI within the StorwizeSVCCommonDriver class
        2.0.1 - Added support for multiple pools with model update
        2.1 - Added replication V2 support to the global/metro mirror
              mode
        2.1.1 - Update replication to version 2.1
        2.2 - Add CG capability to generic volume groups
        2.2.1 - Add vdisk mirror/stretch cluster support
        2.2.2 - Add npiv support
    """

    VERSION = "2.2.2"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "IBM_STORAGE_CI"

    def __init__(self, *args, **kwargs):
        super(StorwizeSVCFCDriver, self).__init__(*args, **kwargs)
        self.protocol = 'FC'
        self.configuration.append_config_values(
            storwize_svc_fc_opts)

    def validate_connector(self, connector):
        """Check connector for at least one enabled FC protocol."""
        if 'wwpns' not in connector:
            LOG.error('The connector does not contain the required '
                      'information.')
            raise exception.InvalidConnectorException(
                missing='wwpns')

    @fczm_utils.add_fc_zone
    def initialize_connection(self, volume, connector):
        """Perform necessary work to make a FC connection."""
        @utils.synchronized('storwize-host' + self._state['system_id'] +
                            connector['host'], external=True)
        def _do_initialize_connection_locked():
            return self._do_initialize_connection(volume, connector)
        return _do_initialize_connection_locked()

    def _do_initialize_connection(self, volume, connector):
        """Perform necessary work to make a FC connection.

        To be able to create an FC connection from a given host to a
        volume, we must:
        1. Translate the given WWNN to a host name
        2. Create new host on the storage system if it does not yet exist
        3. Map the volume to the host if it is not already done
        4. Return the connection information for relevant nodes (in the
           proper I/O group)

        """
        LOG.debug('enter: initialize_connection: volume %(vol)s with connector'
                  ' %(conn)s', {'vol': volume['id'], 'conn': connector})
        volume_name = self._get_target_vol(volume)

        # Check if a host object is defined for this host name
        host_name = self._helpers.get_host_from_connector(connector)
        if host_name is None:
            # Host does not exist - add a new host to Storwize/SVC
            host_name = self._helpers.create_host(connector)

        volume_attributes = self._helpers.get_vdisk_attributes(volume_name)
        if volume_attributes is None:
            msg = (_('initialize_connection: Failed to get attributes'
                     ' for volume %s.') % volume_name)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        multihostmap = self.configuration.storwize_svc_multihostmap_enabled
        lun_id = self._helpers.map_vol_to_host(volume_name, host_name,
                                               multihostmap)
        try:
            preferred_node = volume_attributes['preferred_node_id']
            IO_group = volume_attributes['IO_group_id']
        except KeyError as e:
            LOG.error('Did not find expected column name in '
                      'lsvdisk: %s.', e)
            raise exception.VolumeBackendAPIException(
                data=_('initialize_connection: Missing volume attribute for '
                       'volume %s.') % volume_name)

        try:
            # Get preferred node and other nodes in I/O group
            preferred_node_entry = None
            io_group_nodes = []
            for node in self._state['storage_nodes'].values():
                if node['id'] == preferred_node:
                    preferred_node_entry = node
                if node['IO_group'] == IO_group:
                    io_group_nodes.append(node)

            if not len(io_group_nodes):
                msg = (_('initialize_connection: No node found in '
                         'I/O group %(gid)s for volume %(vol)s.') %
                       {'gid': IO_group, 'vol': volume_name})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            if not preferred_node_entry:
                # Get 1st node in I/O group
                preferred_node_entry = io_group_nodes[0]
                LOG.warning('initialize_connection: Did not find a '
                            'preferred node for volume %s.', volume_name)

            properties = {}
            properties['target_discovered'] = False
            properties['target_lun'] = lun_id
            properties['volume_id'] = volume['id']

            conn_wwpns = self._helpers.get_conn_fc_wwpns(host_name)

            # If conn_wwpns is empty, then that means that there were
            # no target ports with visibility to any of the initiators
            # so we return all target ports.
            if len(conn_wwpns) == 0:
                for node in self._state['storage_nodes'].values():
                    # The Storwize/svc release 7.7.0.0 introduced NPIV feature,
                    # Different commands be used to get the wwpns for host I/O
                    if self._state['code_level'] < (7, 7, 0, 0):
                        conn_wwpns.extend(node['WWPN'])
                    else:
                        npiv_wwpns = self._helpers.get_npiv_wwpns(
                            node_id=node['id'],
                            host_io="yes")
                        conn_wwpns.extend(npiv_wwpns)

            properties['target_wwn'] = conn_wwpns

            i_t_map = self._make_initiator_target_map(connector['wwpns'],
                                                      conn_wwpns)
            properties['initiator_target_map'] = i_t_map

            # specific for z/VM, refer to cinder bug 1323993
            if "zvm_fcp" in connector:
                properties['zvm_fcp'] = connector['zvm_fcp']
        except Exception:
            with excutils.save_and_reraise_exception():
                self._do_terminate_connection(volume, connector)
                LOG.error('initialize_connection: Failed '
                          'to collect return '
                          'properties for volume %(vol)s and connector '
                          '%(conn)s.\n', {'vol': volume,
                                          'conn': connector})

        LOG.debug('leave: initialize_connection:\n volume: %(vol)s\n '
                  'connector %(conn)s\n properties: %(prop)s',
                  {'vol': volume['id'], 'conn': connector,
                   'prop': properties})

        return {'driver_volume_type': 'fibre_channel', 'data': properties, }

    def _make_initiator_target_map(self, initiator_wwpns, target_wwpns):
        """Build a simplistic all-to-all mapping."""
        i_t_map = {}
        for i_wwpn in initiator_wwpns:
            i_t_map[str(i_wwpn)] = []
            for t_wwpn in target_wwpns:
                i_t_map[i_wwpn].append(t_wwpn)

        return i_t_map

    @fczm_utils.remove_fc_zone
    def terminate_connection(self, volume, connector, **kwargs):
        """Cleanup after an FC connection has been terminated."""
        # If a fake connector is generated by nova when the host
        # is down, then the connector will not have a host property,
        # In this case construct the lock without the host property
        # so that all the fake connectors to an SVC are serialized
        host = connector['host'] if 'host' in connector else ""

        @utils.synchronized('storwize-host' + self._state['system_id'] + host,
                            external=True)
        def _do_terminate_connection_locked():
            return self._do_terminate_connection(volume, connector,
                                                 **kwargs)
        return _do_terminate_connection_locked()

    def _do_terminate_connection(self, volume, connector, **kwargs):
        """Cleanup after an FC connection has been terminated.

        When we clean up a terminated connection between a given connector
        and volume, we:
        1. Translate the given connector to a host name
        2. Remove the volume-to-host mapping if it exists
        3. Delete the host if it has no more mappings (hosts are created
           automatically by this driver when mappings are created)
        """
        LOG.debug('enter: terminate_connection: volume %(vol)s with connector'
                  ' %(conn)s', {'vol': volume['id'], 'conn': connector})
        vol_name = self._get_target_vol(volume)
        info = {}
        if 'host' in connector:
            # get host according to FC protocol
            connector = connector.copy()

            connector.pop('initiator', None)
            info = {'driver_volume_type': 'fibre_channel',
                    'data': {}}

            host_name = self._helpers.get_host_from_connector(
                connector, volume_name=vol_name)
            if host_name is None:
                msg = (_('terminate_connection: Failed to get host name from'
                         ' connector.'))
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
        else:
            # See bug #1244257
            host_name = None

        # Unmap volumes, if hostname is None, need to get value from vdiskmap
        host_name = self._helpers.unmap_vol_from_host(vol_name, host_name)

        # Host_name could be none
        if host_name:
            resp = self._helpers.check_host_mapped_vols(host_name)
            if not len(resp):
                LOG.info("Need to remove FC Zone, building initiator "
                         "target map.")
                # Build info data structure for zone removing
                if 'wwpns' in connector and host_name:
                    target_wwpns = []
                    # Returning all target_wwpns in storage_nodes, since
                    # we cannot determine which wwpns are logged in during
                    # a VM deletion.
                    for node in self._state['storage_nodes'].values():
                        target_wwpns.extend(node['WWPN'])
                    init_targ_map = (self._make_initiator_target_map
                                     (connector['wwpns'],
                                      target_wwpns))
                    info['data'] = {'initiator_target_map': init_targ_map}
                # No volume mapped to the host, delete host from array
                self._helpers.delete_host(host_name)

        LOG.debug('leave: terminate_connection: volume %(vol)s with '
                  'connector %(conn)s', {'vol': volume['id'],
                                         'conn': connector})
        return info
