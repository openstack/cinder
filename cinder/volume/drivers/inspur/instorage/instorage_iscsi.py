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
ISCSI volume driver for Inspur InStorage family and MCS storage systems.

Notes:
1. Make sure you config the password or key file. If you specify both
a password and a key file, this driver will use the key file only.
2. When a key file is used for authentication, the private key is stored
in a secure manner by the user or system administrator.
3. The defaults for creating volumes are
"-rsize 2% -autoexpand -grainsize 256 -warning 0".
These can be changed in the configuration file
or by using volume types(recommended only for advanced users).

Limitations:
1. The driver expects CLI output in English,
but the error messages may be in a localized format.
2. when you clone or create volumes from snapshots,
it not support that the source and target_rep are different size.

Perform necessary work to make an iSCSI connection:
To be able to create an iSCSI connection from a given host to a volume,
we must:
1. Translate the given iSCSI name to a host name
2. Create new host on the storage system if it does not yet exist
3. Map the volume to the host if it is not already done
4. Return the connection information for relevant nodes
(in the proper I/O group)
"""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils as cinder_utils
from cinder.volume import driver

from cinder.volume.drivers.inspur.instorage import instorage_common

LOG = logging.getLogger(__name__)

instorage_mcs_iscsi_opts = [
    cfg.BoolOpt('instorage_mcs_iscsi_chap_enabled',
                default=True,
                help='Configure CHAP authentication for iSCSI connections '
                     '(Default: Enabled)'),
]

CONF = cfg.CONF
CONF.register_opts(instorage_mcs_iscsi_opts)


@interface.volumedriver
class InStorageMCSISCSIDriver(instorage_common.InStorageMCSCommonDriver,
                              driver.ISCSIDriver):
    """Inspur InStorage iSCSI volume driver.

    Version history:

    .. code-block:: none

        1.0 - Initial driver
    """

    VERSION = "1.0.0"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "INSPUR_CI"

    def __init__(self, *args, **kwargs):
        super(InStorageMCSISCSIDriver, self).__init__(*args, **kwargs)
        self.protocol = 'iSCSI'
        self.configuration.append_config_values(
            instorage_mcs_iscsi_opts)

    @cinder_utils.trace
    @coordination.synchronized('instorage-host'
                               '{self._state[system_id]}'
                               '{connector[host]}')
    def initialize_connection(self, volume, connector):
        """Perform necessary work to make an iSCSI connection."""
        volume_name = self._get_target_vol(volume)

        # Check if a host object is defined for this host name
        host_name = self._assistant.get_host_from_connector(connector)
        if host_name is None:
            # Host does not exist - add a new host to InStorage/MCS
            host_name = self._assistant.create_host(connector)

        chap_secret = self._assistant.get_chap_secret_for_host(host_name)
        chap_enabled = self.configuration.instorage_mcs_iscsi_chap_enabled
        if chap_enabled and chap_secret is None:
            chap_secret = self._assistant.add_chap_secret_to_host(host_name)
        elif not chap_enabled and chap_secret:
            LOG.warning('CHAP secret exists for host but CHAP is disabled.')

        lun_id = self._assistant.map_vol_to_host(volume_name,
                                                 host_name,
                                                 True)

        try:
            properties = self._get_single_iscsi_data(volume, connector,
                                                     lun_id, chap_secret)
            multipath = connector.get('multipath', False)
            if multipath:
                properties = self._get_multi_iscsi_data(volume, connector,
                                                        lun_id, properties)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._do_terminate_connection(volume, connector)
                LOG.error('initialize_connection: Failed '
                          'to collect return '
                          'properties for volume %(vol)s and connector '
                          '%(conn)s.\n', {'vol': volume, 'conn': connector})

        return {'driver_volume_type': 'iscsi', 'data': properties}

    @cinder_utils.trace
    def _get_single_iscsi_data(self, volume, connector, lun_id, chap_secret):
        volume_name = self._get_target_vol(volume)
        volume_attributes = self._assistant.get_vdisk_attributes(volume_name)
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
        for node in self._state['storage_nodes'].values():
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
            ipaddr = '[%s]' % preferred_node_entry['ipv6'][0]
            # ipv6 need surround with brackets when it use port
        properties['target_portal'] = '%s:%s' % (ipaddr, '3260')
        properties['target_iqn'] = preferred_node_entry['iscsi_name']
        if chap_secret:
            properties.update(auth_method='CHAP',
                              auth_username=connector['initiator'],
                              auth_password=chap_secret,
                              discovery_auth_method='CHAP',
                              discovery_auth_username=connector['initiator'],
                              discovery_auth_password=chap_secret)
        return properties

    @cinder_utils.trace
    def _get_multi_iscsi_data(self, volume, connector, lun_id, properties):
        try:
            resp = self._assistant.ssh.lsportip()
        except Exception as ex:
            msg = (_('_get_multi_iscsi_data: Failed to '
                     'get port ip because of exception: '
                     '%s.') % six.text_type(ex))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        properties['target_iqns'] = []
        properties['target_portals'] = []
        properties['target_luns'] = []
        for node in self._state['storage_nodes'].values():
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

        return properties

    def terminate_connection(self, volume, connector, **kwargs):
        """Cleanup after an iSCSI connection has been terminated."""
        # If a fake connector is generated by nova when the host
        # is down, then the connector will not have a host property,
        # In this case construct the lock without the host property
        # so that all the fake connectors to an MCS are serialized
        host = ""
        if connector is not None and 'host' in connector:
            host = connector['host']

        @coordination.synchronized('instorage-host' + self._state['system_id']
                                   + host)
        def _do_terminate_connection_locked():
            return self._do_terminate_connection(volume, connector, **kwargs)
        return _do_terminate_connection_locked()

    @cinder_utils.trace
    def _do_terminate_connection(self, volume, connector, **kwargs):
        """Cleanup after an iSCSI connection has been terminated.

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
            # get host according to iSCSI protocol
            info = {'driver_volume_type': 'iscsi',
                    'data': {}}

            host_name = self._assistant.get_host_from_connector(connector)
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
                self._assistant.delete_host(host_name)

        return info
