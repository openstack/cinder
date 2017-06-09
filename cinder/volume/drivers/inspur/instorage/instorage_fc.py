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
"""
FC volume driver for Inspur InStorage family storage systems.
"""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils as cinder_utils
from cinder.volume import driver
from cinder.volume.drivers.inspur.instorage import instorage_common
from cinder.volume import utils
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


@interface.volumedriver
class InStorageMCSFCDriver(instorage_common.InStorageMCSCommonDriver,
                           driver.FibreChannelDriver):
    """INSPUR InStorage MCS FC volume driver.

    Version history:

    .. code-block:: none

        1.0 - Initial driver
    """

    VERSION = "1.0.0"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "INSPUR_CI"

    def __init__(self, *args, **kwargs):
        super(InStorageMCSFCDriver, self).__init__(*args, **kwargs)
        self.protocol = 'FC'

    @cinder_utils.trace
    @coordination.synchronized('instorage-host'
                               '{self._state[system_id]}'
                               '{connector[host]}')
    def initialize_connection(self, volume, connector):
        """Perform necessary work to make a FC connection.

        To be able to create an FC connection from a given host to a
        volume, we must:
        1. Translate the given WWNN to a host name
        2. Create new host on the storage system if it does not yet exist
        3. Map the volume to the host if it is not already done
        4. Return the connection information for relevant nodes (in the
           proper I/O group)

        """
        volume_name = self._get_target_vol(volume)

        # Check if a host object is defined for this host name
        host_name = self._assistant.get_host_from_connector(connector)
        if host_name is None:
            # Host does not exist - add a new host to InStorage/MCS
            host_name = self._assistant.create_host(connector)

        volume_attributes = self._assistant.get_vdisk_attributes(volume_name)
        if volume_attributes is None:
            msg = (_('initialize_connection: Failed to get attributes'
                     ' for volume %s.') % volume_name)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        lun_id = self._assistant.map_vol_to_host(volume_name,
                                                 host_name,
                                                 True)

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
            properties['volume_id'] = volume.id

            conn_wwpns = self._assistant.get_conn_fc_wwpns(host_name)

            # If conn_wwpns is empty, then that means that there were
            # no target ports with visibility to any of the initiators
            # so we return all target ports.
            if len(conn_wwpns) == 0:
                for node in self._state['storage_nodes'].values():
                    conn_wwpns.extend(node['WWPN'])

            properties['target_wwn'] = conn_wwpns

            i_t_map = utils.make_initiator_target_all2all_map(
                connector['wwpns'], conn_wwpns)
            properties['initiator_target_map'] = i_t_map

        except Exception:
            with excutils.save_and_reraise_exception():
                self._do_terminate_connection(volume, connector)
                LOG.error('initialize_connection: Failed '
                          'to collect return '
                          'properties for volume %(vol)s and connector '
                          '%(conn)s.\n', {'vol': volume,
                                          'conn': connector})

        info = {'driver_volume_type': 'fibre_channel', 'data': properties, }
        fczm_utils.add_fc_zone(info)
        return info

    def terminate_connection(self, volume, connector, **kwargs):
        """Cleanup after an FC connection has been terminated."""
        # If a fake connector is generated by nova when the host
        # is down, then the connector will not have a host property,
        # In this case construct the lock without the host property
        # so that all the fake connectors to an MCS are serialized
        host = ""
        if connector is not None and 'host' in connector:
            host = connector['host']

        @coordination.synchronized('instorage-host' +
                                   self._state['system_id'] + host)
        def _do_terminate_connection_locked():
            return self._do_terminate_connection(volume, connector,
                                                 **kwargs)
        return _do_terminate_connection_locked()

    @cinder_utils.trace
    def _do_terminate_connection(self, volume, connector, **kwargs):
        """Cleanup after an FC connection has been terminated.

        When we clean up a terminated connection between a given connector
        and volume, we:
        1. Translate the given connector to a host name
        2. Remove the volume-to-host mapping if it exists
        3. Delete the host if it has no more mappings (hosts are created
           automatically by this driver when mappings are created)
        """
        vol_name = self._get_target_vol(volume)
        info = {}
        if connector is not None and 'host' in connector:
            # get host according to FC protocol
            connector = connector.copy()

            connector.pop('initiator', None)
            info = {'driver_volume_type': 'fibre_channel',
                    'data': {}}

            host_name = self._assistant.get_host_from_connector(
                connector, volume_name=vol_name)
            if host_name is None:
                msg = (_('terminate_connection: Failed to get host name from'
                         ' connector.'))
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
        else:
            host_name = None

        # Unmap volumes, if hostname is None, need to get value from vdiskmap
        host_name = self._assistant.unmap_vol_from_host(vol_name, host_name)

        # Host_name could be none
        if host_name:
            resp = self._assistant.check_host_mapped_vols(host_name)
            if not len(resp):
                LOG.info("Need to remove FC Zone, building initiator "
                         "target map.")
                # Build info data structure for zone removing
                if connector is not None and 'wwpns' in connector:
                    target_wwpns = []
                    # Returning all target_wwpns in storage_nodes, since
                    # we cannot determine which wwpns are logged in during
                    # a VM deletion.
                    for node in self._state['storage_nodes'].values():
                        target_wwpns.extend(node['WWPN'])
                    init_targ_map = (utils.make_initiator_target_all2all_map
                                     (connector['wwpns'],
                                      target_wwpns))
                    info['data'] = {'initiator_target_map': init_targ_map}
                    # Only remove the zone if it's the last volume removed
                    fczm_utils.remove_fc_zone(info)
                # No volume mapped to the host, delete host from array
                self._assistant.delete_host(host_name)

        return info
