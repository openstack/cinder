# Copyright 2013 IBM Corp.
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

import math
import time

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.ibm.storwize_svc import (
    replication as storwize_rep)
from cinder.volume.drivers.ibm.storwize_svc import (
    storwize_svc_common as storwize_helpers)
from cinder.volume.drivers.san import san
from cinder.volume import volume_types
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)

storwize_svc_opts = [
    cfg.StrOpt('storwize_svc_volpool_name',
               default='volpool',
               help='Storage system storage pool for volumes'),
    cfg.IntOpt('storwize_svc_vol_rsize',
               default=2,
               min=-1, max=100,
               help='Storage system space-efficiency parameter for volumes '
                    '(percentage)'),
    cfg.IntOpt('storwize_svc_vol_warning',
               default=0,
               min=-1, max=100,
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
    cfg.IntOpt('storwize_svc_vol_iogrp',
               default=0,
               help='The I/O group in which to allocate volumes'),
    cfg.IntOpt('storwize_svc_flashcopy_timeout',
               default=120,
               min=1, max=600,
               help='Maximum number of seconds to wait for FlashCopy to be '
                    'prepared.'),
    cfg.StrOpt('storwize_svc_connection_protocol',
               default='iSCSI',
               help='Connection protocol (iSCSI/FC)'),
    cfg.BoolOpt('storwize_svc_iscsi_chap_enabled',
                default=True,
                help='Configure CHAP authentication for iSCSI connections '
                     '(Default: Enabled)'),
    cfg.BoolOpt('storwize_svc_multipath_enabled',
                default=False,
                help='Connect with multipath (FC only; iSCSI multipath is '
                     'controlled by Nova)'),
    cfg.BoolOpt('storwize_svc_multihostmap_enabled',
                default=True,
                help='Allows vdisk to multi host mapping'),
    cfg.BoolOpt('storwize_svc_allow_tenant_qos',
                default=False,
                help='Allow tenants to specify QOS on create'),
    cfg.StrOpt('storwize_svc_stretched_cluster_partner',
               help='If operating in stretched cluster mode, specify the '
                    'name of the pool in which mirrored copies are stored.'
                    'Example: "pool2"'),
    cfg.BoolOpt('storwize_svc_vol_nofmtdisk',
                default=False,
                help='Specifies that the volume not be formatted during '
                     'creation.'),
]

CONF = cfg.CONF
CONF.register_opts(storwize_svc_opts)


class StorwizeSVCDriver(san.SanDriver,
                        driver.ManageableVD,
                        driver.ExtendVD, driver.SnapshotVD,
                        driver.MigrateVD, driver.ReplicaVD,
                        driver.ConsistencyGroupVD,
                        driver.CloneableImageVD, driver.TransferVD):
    """IBM Storwize V7000 and SVC iSCSI/FC volume driver.

    Version history:
    1.0 - Initial driver
    1.1 - FC support, create_cloned_volume, volume type support,
          get_volume_stats, minor bug fixes
    1.2.0 - Added retype
    1.2.1 - Code refactor, improved exception handling
    1.2.2 - Fix bug #1274123 (races in host-related functions)
    1.2.3 - Fix Fibre Channel connectivity: bug #1279758 (add delim to
            lsfabric, clear unused data from connections, ensure matching
            WWPNs by comparing lower case
    1.2.4 - Fix bug #1278035 (async migration/retype)
    1.2.5 - Added support for manage_existing (unmanage is inherited)
    1.2.6 - Added QoS support in terms of I/O throttling rate
    1.3.1 - Added support for volume replication
    1.3.2 - Added support for consistency group
    1.3.3 - Update driver to use ABC metaclasses
    """

    VERSION = "1.3.3"
    VDISKCOPYOPS_INTERVAL = 600

    def __init__(self, *args, **kwargs):
        super(StorwizeSVCDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(storwize_svc_opts)
        self._helpers = storwize_helpers.StorwizeHelpers(self._run_ssh)
        self._vdiskcopyops = {}
        self._vdiskcopyops_loop = None
        self.replication = None
        self._state = {'storage_nodes': {},
                       'enabled_protocols': set(),
                       'compression_enabled': False,
                       'available_iogrps': [],
                       'system_name': None,
                       'system_id': None,
                       'code_level': None,
                       }
        # Storwize has the limitation that can not burst more than 3 new ssh
        # connections within 1 second. So slow down the initialization.
        time.sleep(1)

    def do_setup(self, ctxt):
        """Check that we have all configuration details from the storage."""
        LOG.debug('enter: do_setup')

        # Get storage system name, id, and code level
        self._state.update(self._helpers.get_system_info())

        # Get the replication helpers
        self.replication = storwize_rep.StorwizeSVCReplication.factory(self)

        # Validate that the pool exists
        pool = self.configuration.storwize_svc_volpool_name
        try:
            self._helpers.get_pool_attrs(pool)
        except exception.VolumeBackendAPIException:
            msg = _('Failed getting details for pool %s.') % pool
            raise exception.InvalidInput(reason=msg)

        # Check if compression is supported
        self._state['compression_enabled'] = (self._helpers.
                                              compression_enabled())

        # Get the available I/O groups
        self._state['available_iogrps'] = (self._helpers.
                                           get_available_io_groups())

        # Get the iSCSI and FC names of the Storwize/SVC nodes
        self._state['storage_nodes'] = self._helpers.get_node_info()

        # Add the iSCSI IP addresses and WWPNs to the storage node info
        self._helpers.add_iscsi_ip_addrs(self._state['storage_nodes'])
        self._helpers.add_fc_wwpns(self._state['storage_nodes'])

        # For each node, check what connection modes it supports.  Delete any
        # nodes that do not support any types (may be partially configured).
        to_delete = []
        for k, node in self._state['storage_nodes'].items():
            if ((len(node['ipv4']) or len(node['ipv6']))
                    and len(node['iscsi_name'])):
                node['enabled_protocols'].append('iSCSI')
                self._state['enabled_protocols'].add('iSCSI')
            if len(node['WWPN']):
                node['enabled_protocols'].append('FC')
                self._state['enabled_protocols'].add('FC')
            if not len(node['enabled_protocols']):
                to_delete.append(k)
        for delkey in to_delete:
            del self._state['storage_nodes'][delkey]

        # Make sure we have at least one node configured
        if not len(self._state['storage_nodes']):
            msg = _('do_setup: No configured nodes.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        # Build the list of in-progress vdisk copy operations
        if ctxt is None:
            admin_context = context.get_admin_context()
        else:
            admin_context = ctxt.elevated()
        volumes = self.db.volume_get_all_by_host(admin_context, self.host)

        for volume in volumes:
            metadata = self.db.volume_admin_metadata_get(admin_context,
                                                         volume['id'])
            curr_ops = metadata.get('vdiskcopyops', None)
            if curr_ops:
                ops = [tuple(x.split(':')) for x in curr_ops.split(';')]
                self._vdiskcopyops[volume['id']] = ops

        # if vdiskcopy exists in database, start the looping call
        if len(self._vdiskcopyops) >= 1:
            self._vdiskcopyops_loop = loopingcall.FixedIntervalLoopingCall(
                self._check_volume_copy_ops)
            self._vdiskcopyops_loop.start(interval=self.VDISKCOPYOPS_INTERVAL)

        LOG.debug('leave: do_setup')

    def check_for_setup_error(self):
        """Ensure that the flags are set properly."""
        LOG.debug('enter: check_for_setup_error')

        # Check that we have the system ID information
        if self._state['system_name'] is None:
            exception_msg = (_('Unable to determine system name.'))
            raise exception.VolumeBackendAPIException(data=exception_msg)
        if self._state['system_id'] is None:
            exception_msg = (_('Unable to determine system id.'))
            raise exception.VolumeBackendAPIException(data=exception_msg)

        required_flags = ['san_ip', 'san_ssh_port', 'san_login',
                          'storwize_svc_volpool_name']
        for flag in required_flags:
            if not self.configuration.safe_get(flag):
                raise exception.InvalidInput(reason=_('%s is not set.') % flag)

        # Ensure that either password or keyfile were set
        if not (self.configuration.san_password or
                self.configuration.san_private_key):
            raise exception.InvalidInput(
                reason=_('Password or SSH private key is required for '
                         'authentication: set either san_password or '
                         'san_private_key option.'))

        opts = self._helpers.build_default_opts(self.configuration)
        self._helpers.check_vdisk_opts(self._state, opts)

        LOG.debug('leave: check_for_setup_error')

    def ensure_export(self, ctxt, volume):
        """Check that the volume exists on the storage.

        The system does not "export" volumes as a Linux iSCSI target does,
        and therefore we just check that the volume exists on the storage.
        """
        volume_defined = self._helpers.is_vdisk_defined(volume['name'])
        if not volume_defined:
            LOG.error(_LE('ensure_export: Volume %s not found on storage.'),
                      volume['name'])

    def create_export(self, ctxt, volume, connector):
        model_update = None
        return model_update

    def remove_export(self, ctxt, volume):
        pass

    def validate_connector(self, connector):
        """Check connector for at least one enabled protocol (iSCSI/FC)."""
        valid = False
        if ('iSCSI' in self._state['enabled_protocols'] and
                'initiator' in connector):
            valid = True
        if 'FC' in self._state['enabled_protocols'] and 'wwpns' in connector:
            valid = True
        if not valid:
            LOG.error(_LE('The connector does not contain the required '
                          'information.'))
            raise exception.InvalidConnectorException(
                missing='initiator or wwpns')

    def _get_vdisk_params(self, type_id, volume_type=None,
                          volume_metadata=None):
        return self._helpers.get_vdisk_params(self.configuration, self._state,
                                              type_id, volume_type=volume_type,
                                              volume_metadata=volume_metadata)

    @fczm_utils.AddFCZone
    @utils.synchronized('storwize-host', external=True)
    def initialize_connection(self, volume, connector):
        """Perform necessary work to make an iSCSI/FC connection.

        To be able to create an iSCSI/FC connection from a given host to a
        volume, we must:
        1. Translate the given iSCSI name or WWNN to a host name
        2. Create new host on the storage system if it does not yet exist
        3. Map the volume to the host if it is not already done
        4. Return the connection information for relevant nodes (in the
           proper I/O group)

        """

        LOG.debug('enter: initialize_connection: volume %(vol)s with connector'
                  ' %(conn)s', {'vol': volume['id'], 'conn': connector})

        vol_opts = self._get_vdisk_params(volume['volume_type_id'])
        volume_name = volume['name']

        # Delete irrelevant connection information that later could result
        # in unwanted behaviour. For example, if FC is used yet the hosts
        # return iSCSI data, the driver will try to create the iSCSI connection
        # which can result in a nice error about reaching the per-host maximum
        # iSCSI initiator limit.
        # First make a copy so we don't mess with a caller's connector.
        connector = connector.copy()
        if vol_opts['protocol'] == 'FC':
            connector.pop('initiator', None)
        elif vol_opts['protocol'] == 'iSCSI':
            connector.pop('wwnns', None)
            connector.pop('wwpns', None)

        # Check if a host object is defined for this host name
        host_name = self._helpers.get_host_from_connector(connector)
        if host_name is None:
            # Host does not exist - add a new host to Storwize/SVC
            host_name = self._helpers.create_host(connector)

        if vol_opts['protocol'] == 'iSCSI':
            chap_secret = self._helpers.get_chap_secret_for_host(host_name)
            chap_enabled = self.configuration.storwize_svc_iscsi_chap_enabled
            if chap_enabled and chap_secret is None:
                chap_secret = self._helpers.add_chap_secret_to_host(host_name)
            elif not chap_enabled and chap_secret:
                LOG.warning(_LW('CHAP secret exists for host but CHAP is '
                                'disabled.'))

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
            LOG.error(_LE('Did not find expected column name in '
                          'lsvdisk: %s.'), e)
            raise exception.VolumeBackendAPIException(
                data=_('initialize_connection: Missing volume attribute for '
                       'volume %s.') % volume_name)

        try:
            # Get preferred node and other nodes in I/O group
            preferred_node_entry = None
            io_group_nodes = []
            for node in self._state['storage_nodes'].values():
                if vol_opts['protocol'] not in node['enabled_protocols']:
                    continue
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

            if not preferred_node_entry and not vol_opts['multipath']:
                # Get 1st node in I/O group
                preferred_node_entry = io_group_nodes[0]
                LOG.warning(_LW('initialize_connection: Did not find a '
                                'preferred node for volume %s.'), volume_name)

            properties = {}
            properties['target_discovered'] = False
            properties['target_lun'] = lun_id
            properties['volume_id'] = volume['id']
            if vol_opts['protocol'] == 'iSCSI':
                type_str = 'iscsi'
                if len(preferred_node_entry['ipv4']):
                    ipaddr = preferred_node_entry['ipv4'][0]
                else:
                    ipaddr = preferred_node_entry['ipv6'][0]
                properties['target_portal'] = '%s:%s' % (ipaddr, '3260')
                properties['target_iqn'] = preferred_node_entry['iscsi_name']
                if chap_secret:
                    properties['auth_method'] = 'CHAP'
                    properties['auth_username'] = connector['initiator']
                    properties['auth_password'] = chap_secret
                    properties['discovery_auth_method'] = 'CHAP'
                    properties['discovery_auth_username'] = (
                        connector['initiator'])
                    properties['discovery_auth_password'] = chap_secret
            else:
                type_str = 'fibre_channel'
                conn_wwpns = self._helpers.get_conn_fc_wwpns(host_name)

                # If conn_wwpns is empty, then that means that there were
                # no target ports with visibility to any of the initiators
                # so we return all target ports.
                if len(conn_wwpns) == 0:
                    for node in self._state['storage_nodes'].values():
                        conn_wwpns.extend(node['WWPN'])

                if not vol_opts['multipath']:
                    # preferred_node_entry can have a list of WWPNs while only
                    # one WWPN may be available on the storage host.  Here we
                    # walk through the nodes until we find one that works,
                    # default to the first WWPN otherwise.
                    for WWPN in preferred_node_entry['WWPN']:
                        if WWPN in conn_wwpns:
                            properties['target_wwn'] = WWPN
                            break
                    else:
                        LOG.warning(_LW('Unable to find a preferred node match'
                                        ' for node %(node)s in the list of '
                                        'available WWPNs on %(host)s. '
                                        'Using first available.'),
                                    {'node': preferred_node,
                                     'host': host_name})
                        properties['target_wwn'] = conn_wwpns[0]
                else:
                    properties['target_wwn'] = conn_wwpns

                i_t_map = self._make_initiator_target_map(connector['wwpns'],
                                                          conn_wwpns)
                properties['initiator_target_map'] = i_t_map

                # specific for z/VM, refer to cinder bug 1323993
                if "zvm_fcp" in connector:
                    properties['zvm_fcp'] = connector['zvm_fcp']
        except Exception:
            with excutils.save_and_reraise_exception():
                self.terminate_connection(volume, connector)
                LOG.error(_LE('initialize_connection: Failed '
                              'to collect return '
                              'properties for volume %(vol)s and connector '
                              '%(conn)s.\n'), {'vol': volume,
                                               'conn': connector})

        LOG.debug('leave: initialize_connection:\n volume: %(vol)s\n '
                  'connector %(conn)s\n properties: %(prop)s',
                  {'vol': volume['id'], 'conn': connector,
                   'prop': properties})

        return {'driver_volume_type': type_str, 'data': properties, }

    def _make_initiator_target_map(self, initiator_wwpns, target_wwpns):
        """Build a simplistic all-to-all mapping."""
        i_t_map = {}
        for i_wwpn in initiator_wwpns:
            i_t_map[str(i_wwpn)] = []
            for t_wwpn in target_wwpns:
                i_t_map[i_wwpn].append(t_wwpn)

        return i_t_map

    @fczm_utils.RemoveFCZone
    @utils.synchronized('storwize-host', external=True)
    def terminate_connection(self, volume, connector, **kwargs):
        """Cleanup after an iSCSI connection has been terminated.

        When we clean up a terminated connection between a given connector
        and volume, we:
        1. Translate the given connector to a host name
        2. Remove the volume-to-host mapping if it exists
        3. Delete the host if it has no more mappings (hosts are created
           automatically by this driver when mappings are created)
        """
        LOG.debug('enter: terminate_connection: volume %(vol)s with connector'
                  ' %(conn)s', {'vol': volume['id'], 'conn': connector})
        vol_name = volume['name']
        info = {}
        if 'host' in connector:
            # maybe two hosts on the storage, one is for FC and the other for
            # iSCSI, so get host according to protocol
            vol_opts = self._get_vdisk_params(volume['volume_type_id'])
            connector = connector.copy()
            if vol_opts['protocol'] == 'FC':
                connector.pop('initiator', None)
                info = {'driver_volume_type': 'fibre_channel',
                        'data': {}}
            elif vol_opts['protocol'] == 'iSCSI':
                connector.pop('wwnns', None)
                connector.pop('wwpns', None)
                info = {'driver_volume_type': 'iscsi',
                        'data': {}}

            host_name = self._helpers.get_host_from_connector(connector)
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
                LOG.info(_LI("Need to remove FC Zone, building initiator "
                             "target map."))
                # Build info data structure for zone removing
                if 'wwpns' in connector and host_name:
                    target_wwpns = self._helpers.get_conn_fc_wwpns(host_name)
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

    def create_volume(self, volume):
        opts = self._get_vdisk_params(volume['volume_type_id'],
                                      volume_metadata=
                                      volume.get('volume_metadata'))
        pool = self.configuration.storwize_svc_volpool_name
        self._helpers.create_vdisk(volume['name'], str(volume['size']),
                                   'gb', pool, opts)
        if opts['qos']:
            self._helpers.add_vdisk_qos(volume['name'], opts['qos'])

        model_update = None
        if 'replication' in opts and opts['replication']:
            ctxt = context.get_admin_context()
            model_update = self.replication.create_replica(ctxt, volume)
        return model_update

    def delete_volume(self, volume):
        self._helpers.delete_vdisk(volume['name'], False)

        if volume['id'] in self._vdiskcopyops:
            del self._vdiskcopyops[volume['id']]

            if not len(self._vdiskcopyops):
                self._vdiskcopyops_loop.stop()
                self._vdiskcopyops_loop = None

    def create_snapshot(self, snapshot):
        ctxt = context.get_admin_context()
        try:
            source_vol = self.db.volume_get(ctxt, snapshot['volume_id'])
        except Exception:
            msg = (_('create_snapshot: get source volume failed.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        opts = self._get_vdisk_params(source_vol['volume_type_id'])
        self._helpers.create_copy(snapshot['volume_name'], snapshot['name'],
                                  snapshot['volume_id'], self.configuration,
                                  opts, False)

    def delete_snapshot(self, snapshot):
        self._helpers.delete_vdisk(snapshot['name'], False)

    def create_volume_from_snapshot(self, volume, snapshot):
        if volume['size'] != snapshot['volume_size']:
            msg = (_('create_volume_from_snapshot: Source and destination '
                     'size differ.'))
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)

        opts = self._get_vdisk_params(volume['volume_type_id'],
                                      volume_metadata=
                                      volume.get('volume_metadata'))
        self._helpers.create_copy(snapshot['name'], volume['name'],
                                  snapshot['id'], self.configuration,
                                  opts, True)
        if opts['qos']:
            self._helpers.add_vdisk_qos(volume['name'], opts['qos'])

        if 'replication' in opts and opts['replication']:
            ctxt = context.get_admin_context()
            replica_status = self.replication.create_replica(ctxt, volume)
            if replica_status:
                return replica_status

    def create_cloned_volume(self, tgt_volume, src_volume):
        if src_volume['size'] != tgt_volume['size']:
            msg = (_('create_cloned_volume: Source and destination '
                     'size differ.'))
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)

        opts = self._get_vdisk_params(tgt_volume['volume_type_id'],
                                      volume_metadata=
                                      tgt_volume.get('volume_metadata'))
        self._helpers.create_copy(src_volume['name'], tgt_volume['name'],
                                  src_volume['id'], self.configuration,
                                  opts, True)
        if opts['qos']:
            self._helpers.add_vdisk_qos(tgt_volume['name'], opts['qos'])

        if 'replication' in opts and opts['replication']:
            ctxt = context.get_admin_context()
            replica_status = self.replication.create_replica(ctxt, tgt_volume)
            if replica_status:
                return replica_status

    def extend_volume(self, volume, new_size):
        LOG.debug('enter: extend_volume: volume %s', volume['id'])
        ret = self._helpers.ensure_vdisk_no_fc_mappings(volume['name'],
                                                        allow_snaps=False)
        if not ret:
            msg = (_('extend_volume: Extending a volume with snapshots is not '
                     'supported.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        extend_amt = int(new_size) - volume['size']
        self._helpers.extend_vdisk(volume['name'], extend_amt)
        LOG.debug('leave: extend_volume: volume %s', volume['id'])

    def add_vdisk_copy(self, volume, dest_pool, vol_type):
        return self._helpers.add_vdisk_copy(volume, dest_pool,
                                            vol_type, self._state,
                                            self.configuration)

    def _add_vdisk_copy_op(self, ctxt, volume, new_op):
        metadata = self.db.volume_admin_metadata_get(ctxt.elevated(),
                                                     volume['id'])
        curr_ops = metadata.get('vdiskcopyops', None)
        if curr_ops:
            curr_ops_list = [tuple(x.split(':')) for x in curr_ops.split(';')]
            new_ops_list = curr_ops_list.append(new_op)
        else:
            new_ops_list = [new_op]
        new_ops_str = ';'.join([':'.join(x) for x in new_ops_list])
        self.db.volume_admin_metadata_update(ctxt.elevated(), volume['id'],
                                             {'vdiskcopyops': new_ops_str},
                                             False)
        if volume['id'] in self._vdiskcopyops:
            self._vdiskcopyops[volume['id']].append(new_op)
        else:
            self._vdiskcopyops[volume['id']] = [new_op]

        # We added the first copy operation, so start the looping call
        if len(self._vdiskcopyops) == 1:
            self._vdiskcopyops_loop = loopingcall.FixedIntervalLoopingCall(
                self._check_volume_copy_ops)
            self._vdiskcopyops_loop.start(interval=self.VDISKCOPYOPS_INTERVAL)

    def _rm_vdisk_copy_op(self, ctxt, volume, orig_copy_id, new_copy_id):
        try:
            self._vdiskcopyops[volume['id']].remove((orig_copy_id,
                                                     new_copy_id))
            if not len(self._vdiskcopyops[volume['id']]):
                del self._vdiskcopyops[volume['id']]
            if not len(self._vdiskcopyops):
                self._vdiskcopyops_loop.stop()
                self._vdiskcopyops_loop = None
        except KeyError:
            LOG.error(_LE('_rm_vdisk_copy_op: Volume %s does not have any '
                          'registered vdisk copy operations.'), volume['id'])
            return
        except ValueError:
            LOG.error(_LE('_rm_vdisk_copy_op: Volume %(vol)s does not have '
                          'the specified vdisk copy operation: orig=%(orig)s '
                          'new=%(new)s.'),
                      {'vol': volume['id'], 'orig': orig_copy_id,
                       'new': new_copy_id})
            return

        metadata = self.db.volume_admin_metadata_get(ctxt.elevated(),
                                                     volume['id'])
        curr_ops = metadata.get('vdiskcopyops', None)
        if not curr_ops:
            LOG.error(_LE('_rm_vdisk_copy_op: Volume metadata %s does not '
                          'have any registered vdisk copy operations.'),
                      volume['id'])
            return
        curr_ops_list = [tuple(x.split(':')) for x in curr_ops.split(';')]
        try:
            curr_ops_list.remove((orig_copy_id, new_copy_id))
        except ValueError:
            LOG.error(_LE('_rm_vdisk_copy_op: Volume %(vol)s metadata does '
                          'not have the specified vdisk copy operation: '
                          'orig=%(orig)s new=%(new)s.'),
                      {'vol': volume['id'], 'orig': orig_copy_id,
                       'new': new_copy_id})
            return

        if len(curr_ops_list):
            new_ops_str = ';'.join([':'.join(x) for x in curr_ops_list])
            self.db.volume_admin_metadata_update(ctxt.elevated(), volume['id'],
                                                 {'vdiskcopyops': new_ops_str},
                                                 False)
        else:
            self.db.volume_admin_metadata_delete(ctxt.elevated(), volume['id'],
                                                 'vdiskcopyops')

    def promote_replica(self, ctxt, volume):
        return self.replication.promote_replica(volume)

    def reenable_replication(self, ctxt, volume):
        return self.replication.reenable_replication(volume)

    def create_replica_test_volume(self, tgt_volume, src_volume):
        if src_volume['size'] != tgt_volume['size']:
            msg = (_('create_cloned_volume: Source and destination '
                     'size differ.'))
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)
        replica_status = self.replication.test_replica(tgt_volume,
                                                       src_volume)
        return replica_status

    def get_replication_status(self, ctxt, volume):
        replica_status = None
        if self.replication:
            replica_status = self.replication.get_replication_status(volume)
        return replica_status

    def _check_volume_copy_ops(self):
        LOG.debug("Enter: update volume copy status.")
        ctxt = context.get_admin_context()
        copy_items = self._vdiskcopyops.items()
        for vol_id, copy_ops in copy_items:
            try:
                volume = self.db.volume_get(ctxt, vol_id)
            except Exception:
                LOG.warning(_LW('Volume %s does not exist.'), vol_id)
                del self._vdiskcopyops[vol_id]
                if not len(self._vdiskcopyops):
                    self._vdiskcopyops_loop.stop()
                    self._vdiskcopyops_loop = None
                continue

            for copy_op in copy_ops:
                try:
                    synced = self._helpers.is_vdisk_copy_synced(volume['name'],
                                                                copy_op[1])
                except Exception:
                    LOG.info(_LI('_check_volume_copy_ops: Volume %(vol)s does '
                                 'not have the specified vdisk copy '
                                 'operation: orig=%(orig)s new=%(new)s.'),
                             {'vol': volume['id'], 'orig': copy_op[0],
                              'new': copy_op[1]})
                else:
                    if synced:
                        self._helpers.rm_vdisk_copy(volume['name'], copy_op[0])
                        self._rm_vdisk_copy_op(ctxt, volume, copy_op[0],
                                               copy_op[1])
        LOG.debug("Exit: update volume copy status.")

    def migrate_volume(self, ctxt, volume, host):
        """Migrate directly if source and dest are managed by same storage.

        We create a new vdisk copy in the desired pool, and add the original
        vdisk copy to the admin_metadata of the volume to be deleted. The
        deletion will occur using a periodic task once the new copy is synced.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug('enter: migrate_volume: id=%(id)s, host=%(host)s',
                  {'id': volume['id'], 'host': host['host']})

        false_ret = (False, None)
        dest_pool = self._helpers.can_migrate_to_host(host, self._state)
        if dest_pool is None:
            return false_ret

        ctxt = context.get_admin_context()
        if volume['volume_type_id'] is not None:
            volume_type_id = volume['volume_type_id']
            vol_type = volume_types.get_volume_type(ctxt, volume_type_id)
        else:
            vol_type = None

        self._check_volume_copy_ops()
        new_op = self.add_vdisk_copy(volume['name'], dest_pool, vol_type)
        self._add_vdisk_copy_op(ctxt, volume, new_op)
        LOG.debug('leave: migrate_volume: id=%(id)s, host=%(host)s',
                  {'id': volume['id'], 'host': host['host']})
        return (True, None)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Returns a boolean indicating whether the retype occurred.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        def retype_iogrp_property(volume, new, old):
            if new != old:
                self._helpers.change_vdisk_iogrp(volume['name'],
                                                 self._state, (new, old))

        LOG.debug('enter: retype: id=%(id)s, new_type=%(new_type)s,'
                  'diff=%(diff)s, host=%(host)s', {'id': volume['id'],
                                                   'new_type': new_type,
                                                   'diff': diff,
                                                   'host': host})

        ignore_keys = ['protocol', 'multipath']
        no_copy_keys = ['warning', 'autoexpand', 'easytier']
        copy_keys = ['rsize', 'grainsize', 'compression']
        all_keys = ignore_keys + no_copy_keys + copy_keys
        old_opts = self._get_vdisk_params(volume['volume_type_id'],
                                          volume_metadata=
                                          volume.get('volume_matadata'))
        new_opts = self._get_vdisk_params(new_type['id'],
                                          volume_type=new_type)

        # Check if retype affects volume replication
        model_update = None
        old_type_replication = old_opts.get('replication', False)
        new_type_replication = new_opts.get('replication', False)

        # Delete replica if needed
        if old_type_replication and not new_type_replication:
            self.replication.delete_replica(volume)
            model_update = {'replication_status': 'disabled',
                            'replication_driver_data': None,
                            'replication_extended_status': None}

        vdisk_changes = []
        need_copy = False
        for key in all_keys:
            if old_opts[key] != new_opts[key]:
                if key in copy_keys:
                    need_copy = True
                    break
                elif key in no_copy_keys:
                    vdisk_changes.append(key)

        dest_location = host['capabilities'].get('location_info')
        if self._stats['location_info'] != dest_location:
            need_copy = True

        if need_copy:
            self._check_volume_copy_ops()
            dest_pool = self._helpers.can_migrate_to_host(host, self._state)
            if dest_pool is None:
                return False

            # If volume is replicated, can't copy
            if new_type_replication:
                msg = (_('Unable to retype: Current action needs volume-copy,'
                         ' it is not allowed when new type is replication.'
                         ' Volume = %s'), volume['id'])
                raise exception.VolumeDriverException(message=msg)

            retype_iogrp_property(volume,
                                  new_opts['iogrp'],
                                  old_opts['iogrp'])
            try:
                new_op = self.add_vdisk_copy(volume['name'],
                                             dest_pool,
                                             new_type)
                self._add_vdisk_copy_op(ctxt, volume, new_op)
            except exception.VolumeDriverException:
                # roll back changing iogrp property
                retype_iogrp_property(volume, old_opts['iogrp'],
                                      new_opts['iogrp'])
                msg = (_('Unable to retype:  A copy of volume %s exists. '
                         'Retyping would exceed the limit of 2 copies.'),
                       volume['id'])
                raise exception.VolumeDriverException(message=msg)
        else:
            retype_iogrp_property(volume, new_opts['iogrp'], old_opts['iogrp'])

            self._helpers.change_vdisk_options(volume['name'], vdisk_changes,
                                               new_opts, self._state)

        if new_opts['qos']:
            # Add the new QoS setting to the volume. If the volume has an
            # old QoS setting, it will be overwritten.
            self._helpers.update_vdisk_qos(volume['name'], new_opts['qos'])
        elif old_opts['qos']:
            # If the old_opts contain QoS keys, disable them.
            self._helpers.disable_vdisk_qos(volume['name'], old_opts['qos'])

        # Add replica if needed
        if not old_type_replication and new_type_replication:
            model_update = self.replication.create_replica(ctxt, volume,
                                                           new_type)

        LOG.debug('exit: retype: ild=%(id)s, new_type=%(new_type)s,'
                  'diff=%(diff)s, host=%(host)s', {'id': volume['id'],
                                                   'new_type': new_type,
                                                   'diff': diff,
                                                   'host': host['host']})
        return True, model_update

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update from Storwize for migrated volume.

        This method should rename the back-end volume name(id) on the
        destination host back to its original name(id) on the source host.

        :param ctxt: The context used to run the method update_migrated_volume
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :return model_update to update DB with any needed changes
        """
        current_name = CONF.volume_name_template % new_volume['id']
        original_volume_name = CONF.volume_name_template % volume['id']
        try:
            self._helpers.rename_vdisk(current_name, original_volume_name)
        except exception.VolumeBackendAPIException:
            LOG.error(_LE('Unable to rename the logical volume '
                          'for volume: %s'), volume['id'])
            return {'_name_id': new_volume['_name_id'] or new_volume['id']}
        # If the back-end name(id) for the volume has been renamed,
        # it is OK for the volume to keep the original name(id) and there is
        # no need to use the column "_name_id" to establish the mapping
        # relationship between the volume id and the back-end volume
        # name(id).
        # Set the key "_name_id" to None for a successful rename.
        model_update = {'_name_id': None}
        return model_update

    def manage_existing(self, volume, ref):
        """Manages an existing vdisk.

        Renames the vdisk to match the expected name for the volume.
        Error checking done by manage_existing_get_size is not repeated -
        if we got here then we have a vdisk that isn't in use (or we don't
        care if it is in use.
        """
        vdisk = self._helpers.vdisk_by_uid(ref['source-id'])
        if vdisk is None:
            reason = (_('No vdisk with the UID specified by source-id %s.')
                      % ref['source-id'])
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)
        self._helpers.rename_vdisk(vdisk['name'], volume['name'])

    def manage_existing_get_size(self, volume, ref):
        """Return size of an existing Vdisk for manage_existing.

        existing_ref is a dictionary of the form:
        {'source-id': <uid of disk>}

        Optional elements are:
          'manage_if_in_use':  True/False (default is False)
            If set to True, a volume will be managed even if it is currently
            attached to a host system.
        """

        # Check that the reference is valid
        if 'source-id' not in ref:
            reason = _('Reference must contain source-id element.')
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)

        # Check for existence of the vdisk
        vdisk = self._helpers.vdisk_by_uid(ref['source-id'])
        if vdisk is None:
            reason = (_('No vdisk with the UID specified by source-id %s.')
                      % (ref['source-id']))
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)

        # Check if the disk is in use, if we need to.
        manage_if_in_use = ref.get('manage_if_in_use', False)
        if (not manage_if_in_use and
                self._helpers.is_vdisk_in_use(vdisk['name'])):
            reason = _('The specified vdisk is mapped to a host.')
            raise exception.ManageExistingInvalidReference(existing_ref=ref,
                                                           reason=reason)

        return int(math.ceil(float(vdisk['capacity']) / units.Gi))

    def unmanage(self, volume):
        """Remove the specified volume from Cinder management."""
        pass

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If we haven't gotten stats yet or 'refresh' is True,
        run update the stats first.
        """
        if not self._stats or refresh:
            self._update_volume_stats()

        return self._stats

    def create_consistencygroup(self, context, group):
        """Create a consistency group.

        IBM Storwize will create CG until cg-snapshot creation,
        db will maintain the volumes and CG relationship.
        """
        LOG.debug("Creating consistency group.")
        model_update = {'status': 'available'}
        return model_update

    def delete_consistencygroup(self, context, group):
        """Deletes a consistency group.

        IBM Storwize will delete the volumes of the CG.
        """
        LOG.debug("Deleting consistency group.")
        model_update = {}
        model_update['status'] = 'deleted'
        volumes = self.db.volume_get_all_by_group(context, group['id'])

        for volume in volumes:
            try:
                self._helpers.delete_vdisk(volume['name'], True)
                volume['status'] = 'deleted'
            except exception.VolumeBackendAPIException as err:
                volume['status'] = 'error_deleting'
                if model_update['status'] != 'error_deleting':
                    model_update['status'] = 'error_deleting'
                LOG.error(_LE("Failed to delete the volume %(vol)s of CG. "
                              "Exception: %(exception)s."),
                          {'vol': volume['name'], 'exception': err})
        return model_update, volumes

    def create_cgsnapshot(self, ctxt, cgsnapshot):
        """Creates a cgsnapshot."""
        # Use cgsnapshot id as cg name
        cg_name = 'cg_snap-' + cgsnapshot['id']
        # Create new cg as cg_snapshot
        self._helpers.create_fc_consistgrp(cg_name)

        snapshots = self.db.snapshot_get_all_for_cgsnapshot(
            ctxt, cgsnapshot['id'])
        timeout = self.configuration.storwize_svc_flashcopy_timeout

        model_update, snapshots_model = (
            self._helpers.run_consistgrp_snapshots(cg_name,
                                                   snapshots,
                                                   self._state,
                                                   self.configuration,
                                                   timeout))

        return model_update, snapshots_model

    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes a cgsnapshot."""
        cgsnapshot_id = cgsnapshot['id']
        cg_name = 'cg_snap-' + cgsnapshot_id

        snapshots = self.db.snapshot_get_all_for_cgsnapshot(context,
                                                            cgsnapshot_id)

        model_update, snapshots_model = (
            self._helpers.delete_consistgrp_snapshots(cg_name,
                                                      snapshots))

        return model_update, snapshots_model

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Updating volume stats.")
        data = {}

        data['vendor_name'] = 'IBM'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = list(self._state['enabled_protocols'])

        data['total_capacity_gb'] = 0  # To be overwritten
        data['free_capacity_gb'] = 0   # To be overwritten
        data['reserved_percentage'] = self.configuration.reserved_percentage
        data['multiattach'] = (self.configuration.
                               storwize_svc_multihostmap_enabled)
        data['QoS_support'] = True
        data['consistencygroup_support'] = True

        pool = self.configuration.storwize_svc_volpool_name
        backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = '%s_%s' % (self._state['system_name'], pool)
        data['volume_backend_name'] = backend_name

        attributes = self._helpers.get_pool_attrs(pool)
        if not attributes:
            LOG.error(_LE('Could not get pool data from the storage.'))
            exception_message = (_('_update_volume_stats: '
                                   'Could not get storage pool data.'))
            raise exception.VolumeBackendAPIException(data=exception_message)

        data['total_capacity_gb'] = (float(attributes['capacity']) /
                                     units.Gi)
        data['free_capacity_gb'] = (float(attributes['free_capacity']) /
                                    units.Gi)
        data['easytier_support'] = attributes['easy_tier'] in ['on', 'auto']
        data['compression_support'] = self._state['compression_enabled']
        data['location_info'] = ('StorwizeSVCDriver:%(sys_id)s:%(pool)s' %
                                 {'sys_id': self._state['system_id'],
                                  'pool': pool})

        if self.replication:
            data.update(self.replication.get_replication_info())

        self._stats = data
