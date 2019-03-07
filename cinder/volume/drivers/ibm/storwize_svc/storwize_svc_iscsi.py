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
ISCSI volume driver for IBM Storwize family and SVC storage systems.

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
import collections

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import configuration as conf

from cinder.volume.drivers.ibm.storwize_svc import (
    storwize_svc_common as storwize_common)

LOG = logging.getLogger(__name__)

storwize_svc_iscsi_opts = [
    cfg.BoolOpt('storwize_svc_iscsi_chap_enabled',
                default=True,
                help='Configure CHAP authentication for iSCSI connections '
                     '(Default: Enabled)'),
]

CONF = cfg.CONF
CONF.register_opts(storwize_svc_iscsi_opts, group=conf.SHARED_CONF_GROUP)


@interface.volumedriver
class StorwizeSVCISCSIDriver(storwize_common.StorwizeSVCCommonDriver):
    """IBM Storwize V7000 and SVC iSCSI volume driver.

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
        2.2.2 - Add replication group support
        2.2.3 - Add backup snapshots support
        2.2.4 - Add hyperswap support
    """

    VERSION = "2.2.4"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "IBM_STORAGE_CI"

    def __init__(self, *args, **kwargs):
        super(StorwizeSVCISCSIDriver, self).__init__(*args, **kwargs)
        self.protocol = 'iSCSI'
        self.configuration.append_config_values(
            storwize_svc_iscsi_opts)

    @staticmethod
    def get_driver_options():
        return storwize_common.storwize_svc_opts + storwize_svc_iscsi_opts

    def validate_connector(self, connector):
        """Check connector for at least one enabled iSCSI protocol."""
        if 'initiator' not in connector:
            LOG.error('The connector does not contain the required '
                      'information.')
            raise exception.InvalidConnectorException(
                missing='initiator')

    def initialize_connection_snapshot(self, snapshot, connector):
        """Perform attach snapshot for backup snapshots."""
        # If the snapshot's source volume is a replication volume and the
        # replication volume has failed over to aux_backend,
        # attach the snapshot will be failed.
        self._check_snapshot_replica_volume_status(snapshot)

        vol_attrs = ['id', 'name', 'volume_type_id', 'display_name']
        Volume = collections.namedtuple('Volume', vol_attrs)
        volume = Volume(id=snapshot.id,
                        name=snapshot.name,
                        volume_type_id=snapshot.volume_type_id,
                        display_name='backup-snapshot')

        return self.initialize_connection(volume, connector)

    def initialize_connection(self, volume, connector):
        """Perform necessary work to make an iSCSI connection."""
        @coordination.synchronized('storwize-host-{system_id}-{host}')
        def _do_initialize_connection_locked(system_id, host):
            return self._do_initialize_connection(volume, connector)
        return _do_initialize_connection_locked(self._state['system_id'],
                                                connector['host'])

    def _do_initialize_connection(self, volume, connector):
        """Perform necessary work to make an iSCSI connection.

        To be able to create an iSCSI connection from a given host to a
        volume, we must:
        1. Translate the given iSCSI name to a host name
        2. Create new host on the storage system if it does not yet exist
        3. Map the volume to the host if it is not already done
        4. Return the connection information for relevant nodes (in the
        proper I/O group)
        """
        LOG.debug('enter: initialize_connection: volume %(vol)s with connector'
                  ' %(conn)s', {'vol': volume.id, 'conn': connector})
        if volume.display_name == 'backup-snapshot':
            LOG.debug('It is a virtual volume %(vol)s for attach snapshot.',
                      {'vol': volume.id})
            volume_name = volume.name
            backend_helper = self._helpers
            node_state = self._state
        else:
            volume_name, backend_helper, node_state = self._get_vol_sys_info(
                volume)

        host_site = self._get_volume_host_site_from_conf(volume,
                                                         connector,
                                                         iscsi=True)
        is_hyper_volume = self.is_volume_hyperswap(volume)
        if is_hyper_volume and host_site is None:
            msg = (_('There is no correct storwize_preferred_host_site '
                     'configured for a hyperswap volume %s.') % volume.name)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        # Check if a host object is defined for this host name
        host_name = backend_helper.get_host_from_connector(connector,
                                                           iscsi=True)
        if host_name is None:
            # Host does not exist - add a new host to Storwize/SVC
            host_name = backend_helper.create_host(connector, iscsi=True,
                                                   site=host_site)
        elif is_hyper_volume:
            self._update_host_site_for_hyperswap_volume(host_name, host_site)

        chap_secret = backend_helper.get_chap_secret_for_host(host_name)
        chap_enabled = self.configuration.storwize_svc_iscsi_chap_enabled
        if chap_enabled and chap_secret is None:
            chap_secret = backend_helper.add_chap_secret_to_host(host_name)
        elif not chap_enabled and chap_secret:
            LOG.warning('CHAP secret exists for host but CHAP is disabled.')

        multihostmap = self.configuration.storwize_svc_multihostmap_enabled
        lun_id = backend_helper.map_vol_to_host(volume_name, host_name,
                                                multihostmap)

        try:
            properties = self._get_single_iscsi_data(volume, connector,
                                                     lun_id, chap_secret)
            multipath = connector.get('multipath', False)
            if multipath:
                properties = self._get_multi_iscsi_data(volume, connector,
                                                        lun_id, properties,
                                                        backend_helper,
                                                        node_state)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('initialize_connection: Failed to export volume '
                          '%(vol)s due to %(ex)s.', {'vol': volume.name,
                                                     'ex': ex})
                self._do_terminate_connection(volume, connector)
                LOG.error('initialize_connection: Failed '
                          'to collect return '
                          'properties for volume %(vol)s and connector '
                          '%(conn)s.\n', {'vol': volume,
                                          'conn': connector})

        # properties may contain chap secret so must be masked
        LOG.debug('leave: initialize_connection:\n volume: %(vol)s\n '
                  'connector: %(conn)s\n properties: %(prop)s',
                  {'vol': volume.id, 'conn': connector,
                   'prop': strutils.mask_password(properties)})

        return {'driver_volume_type': 'iscsi', 'data': properties, }

    def _get_single_iscsi_data(self, volume, connector, lun_id, chap_secret):
        LOG.debug('enter: _get_single_iscsi_data: volume %(vol)s with '
                  'connector %(conn)s lun_id %(lun_id)s',
                  {'vol': volume.id, 'conn': connector,
                   'lun_id': lun_id})

        if volume.display_name == 'backup-snapshot':
            LOG.debug('It is a virtual volume %(vol)s for attach snapshot',
                      {'vol': volume.name})
            volume_name = volume.name
            backend_helper = self._helpers
            node_state = self._state
        else:
            volume_name, backend_helper, node_state = self._get_vol_sys_info(
                volume)

        volume_attributes = backend_helper.get_vdisk_attributes(volume_name)
        if volume_attributes is None:
            msg = (_('_get_single_iscsi_data: Failed to get attributes'
                     ' for volume %s.') % volume_name)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        try:
            preferred_node = volume_attributes['preferred_node_id']
            IO_group = volume_attributes['IO_group_id']
        except KeyError as e:
            msg = (_('_get_single_iscsi_data: Did not find expected column'
                     ' name in %(volume)s: %(key)s  %(error)s.'),
                   {'volume': volume_name, 'key': e.args[0],
                    'error': e})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Get preferred node and other nodes in I/O group
        preferred_node_entry = None
        io_group_nodes = []
        for node in node_state['storage_nodes'].values():
            if self.protocol not in node['enabled_protocols']:
                continue

            if node['IO_group'] != IO_group:
                continue
            io_group_nodes.append(node)
            if node['id'] == preferred_node:
                preferred_node_entry = node

        if not len(io_group_nodes):
            msg = (_('_get_single_iscsi_data: No node found in '
                     'I/O group %(gid)s for volume %(vol)s.') % {
                'gid': IO_group, 'vol': volume_name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if not preferred_node_entry:
            # Get 1st node in I/O group
            preferred_node_entry = io_group_nodes[0]
            LOG.warning('_get_single_iscsi_data: Did not find a '
                        'preferred node for volume %s.', volume_name)

        properties = {
            'target_discovered': False,
            'target_lun': lun_id,
            'volume_id': volume.id}

        if preferred_node_entry['ipv4']:
            ipaddr = preferred_node_entry['ipv4'][0]
        else:
            ipaddr = preferred_node_entry['ipv6'][0]
        properties['target_portal'] = '%s:%s' % (ipaddr, '3260')
        properties['target_iqn'] = preferred_node_entry['iscsi_name']
        if chap_secret:
            properties.update(auth_method='CHAP',
                              auth_username=connector['initiator'],
                              auth_password=chap_secret,
                              discovery_auth_method='CHAP',
                              discovery_auth_username=connector['initiator'],
                              discovery_auth_password=chap_secret)
        # properties may contain chap secret so must be masked
        LOG.debug('leave: _get_single_iscsi_data:\n volume: %(vol)s\n '
                  'connector: %(conn)s\n lun_id: %(lun_id)s\n '
                  'properties: %(prop)s',
                  {'vol': volume.id, 'conn': connector, 'lun_id': lun_id,
                   'prop': strutils.mask_password(properties)})
        return properties

    def _get_multi_iscsi_data(self, volume, connector, lun_id, properties,
                              backend_helper, node_state):
        LOG.debug('enter: _get_multi_iscsi_data: volume %(vol)s with '
                  'connector %(conn)s lun_id %(lun_id)s',
                  {'vol': volume.id, 'conn': connector,
                   'lun_id': lun_id})

        try:
            resp = backend_helper.ssh.lsportip()
        except Exception as ex:
            msg = (_('_get_multi_iscsi_data: Failed to '
                     'get port ip because of exception: '
                     '%s.') % ex)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        properties['target_iqns'] = []
        properties['target_portals'] = []
        properties['target_luns'] = []
        for node in node_state['storage_nodes'].values():
            for ip_data in resp:
                if ip_data['node_id'] != node['id']:
                    continue
                link_state = ip_data.get('link_state', None)
                valid_port = ''
                if ((ip_data['state'] == 'configured' and
                        link_state == 'active') or
                        ip_data['state'] == 'online'):
                    valid_port = (ip_data['IP_address'] or
                                  ip_data['IP_address_6'])
                if valid_port:
                    properties['target_portals'].append(
                        '%s:%s' % (valid_port, '3260'))
                    properties['target_iqns'].append(
                        node['iscsi_name'])
                    properties['target_luns'].append(lun_id)

        if not len(properties['target_portals']):
            msg = (_('_get_multi_iscsi_data: Failed to find valid port '
                     'for volume %s.') % volume.name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # properties may contain chap secret so must be masked
        LOG.debug('leave: _get_multi_iscsi_data:\n volume: %(vol)s\n '
                  'connector: %(conn)s\n lun_id: %(lun_id)s\n '
                  'properties: %(prop)s',
                  {'vol': volume.id, 'conn': connector, 'lun_id': lun_id,
                   'prop': strutils.mask_password(properties)})

        return properties

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Perform detach snapshot for backup snapshots."""
        vol_attrs = ['id', 'name', 'display_name']
        Volume = collections.namedtuple('Volume', vol_attrs)
        volume = Volume(id=snapshot.id,
                        name=snapshot.name,
                        display_name='backup-snapshot')

        return self.terminate_connection(volume, connector, **kwargs)

    def terminate_connection(self, volume, connector, **kwargs):
        """Cleanup after an iSCSI connection has been terminated."""
        # If a fake connector is generated by nova when the host
        # is down, then the connector will not have a host property,
        # In this case construct the lock without the host property
        # so that all the fake connectors to an SVC are serialized
        host = connector['host'] if 'host' in connector else ""

        @coordination.synchronized('storwize-host-{system_id}-{host}')
        def _do_terminate_connection_locked(system_id, host):
            return self._do_terminate_connection(volume, connector,
                                                 **kwargs)
        return _do_terminate_connection_locked(self._state['system_id'], host)

    def _do_terminate_connection(self, volume, connector, **kwargs):
        """Cleanup after an iSCSI connection has been terminated.

        When we clean up a terminated connection between a given connector
        and volume, we:
        1. Translate the given connector to a host name
        2. Remove the volume-to-host mapping if it exists
        3. Delete the host if it has no more mappings (hosts are created
        automatically by this driver when mappings are created)
        """
        LOG.debug('enter: terminate_connection: volume %(vol)s with connector'
                  ' %(conn)s', {'vol': volume.id, 'conn': connector})
        (info, host_name, vol_name, backend_helper,
         node_state) = self._get_map_info_from_connector(volume, connector,
                                                         iscsi=True)
        if not backend_helper:
            return info

        # Unmap volumes, if hostname is None, need to get value from vdiskmap
        host_name = backend_helper.unmap_vol_from_host(vol_name, host_name)

        # Host_name could be none
        if host_name:
            resp = backend_helper.check_host_mapped_vols(host_name)
            if not len(resp):
                backend_helper.delete_host(host_name)

        LOG.debug('leave: terminate_connection: volume %(vol)s with '
                  'connector %(conn)s', {'vol': volume.id,
                                         'conn': connector})
        return info
