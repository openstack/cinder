# Copyright 2019 Nexenta Systems, Inc.
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

import ipaddress
import posixpath
import random
import uuid

from oslo_log import log as logging
from oslo_utils import units
import six

from cinder import context
from cinder import coordination
from cinder.i18n import _
from cinder import interface
from cinder import objects
from cinder.volume import driver
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class NexentaISCSIDriver(driver.ISCSIDriver):
    """Executes volume driver commands on Nexenta Appliance.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver version.
        1.1.0 - Added HTTPS support.
              - Added use of sessions for REST calls.
              - Added abandoned volumes and snapshots cleanup.
        1.2.0 - Failover support.
        1.2.1 - Configurable luns per parget, target prefix.
        1.3.0 - Removed target/TG caching, added support for target portals
                and host groups.
        1.3.1 - Refactored _do_export to query exact lunMapping.
        1.3.2 - Revert to snapshot support.
        1.3.3 - Refactored LUN creation, use host group for LUN mappings.
        1.3.4 - Adapted NexentaException for the latest Cinder.
        1.3.5 - Added deferred deletion for snapshots.
        1.3.6 - Fixed race between volume/clone deletion.
        1.3.7 - Added consistency group support.
        1.3.8 - Added volume multi-attach.
        1.4.0 - Refactored iSCSI driver.
              - Added pagination support.
              - Added configuration parameters for REST API connect/read
                timeouts, connection retries and backoff factor.
              - Fixed HA failover.
              - Added retries on EBUSY errors.
              - Fixed HTTP authentication.
              - Added coordination for dataset operations.
        1.4.1 - Support for NexentaStor tenants.
        1.4.2 - Added manage/unmanage/manageable-list volume/snapshot support.
        1.4.3 - Added consistency group capability to generic volume group.
    """

    VERSION = '1.4.3'
    CI_WIKI_NAME = "Nexenta_CI"

    vendor_name = 'Nexenta'
    product_name = 'NexentaStor5'
    storage_protocol = 'iSCSI'
    driver_volume_type = 'iscsi'

    def __init__(self, *args, **kwargs):
        super(NexentaISCSIDriver, self).__init__(*args, **kwargs)
        if not self.configuration:
            message = (_('%(product_name)s %(storage_protocol)s '
                         'backend configuration not found')
                       % {'product_name': self.product_name,
                          'storage_protocol': self.storage_protocol})
            raise jsonrpc.NefException(code='ENODATA', message=message)
        self.configuration.append_config_values(
            options.NEXENTA_CONNECTION_OPTS)
        self.configuration.append_config_values(
            options.NEXENTA_ISCSI_OPTS)
        self.configuration.append_config_values(
            options.NEXENTA_DATASET_OPTS)
        self.nef = None
        self.volume_backend_name = (
            self.configuration.safe_get('volume_backend_name') or
            '%s_%s' % (self.product_name, self.storage_protocol))
        self.target_prefix = self.configuration.nexenta_target_prefix
        self.target_group_prefix = (
            self.configuration.nexenta_target_group_prefix)
        self.host_group_prefix = self.configuration.nexenta_host_group_prefix
        self.luns_per_target = self.configuration.nexenta_luns_per_target
        self.lu_writebackcache_disabled = (
            self.configuration.nexenta_lu_writebackcache_disabled)
        self.iscsi_host = self.configuration.nexenta_host
        self.pool = self.configuration.nexenta_volume
        self.volume_group = self.configuration.nexenta_volume_group
        self.portal_port = self.configuration.nexenta_iscsi_target_portal_port
        self.portals = self.configuration.nexenta_iscsi_target_portals
        self.sparsed_volumes = self.configuration.nexenta_sparse
        self.deduplicated_volumes = self.configuration.nexenta_dataset_dedup
        self.compressed_volumes = (
            self.configuration.nexenta_dataset_compression)
        self.dataset_description = (
            self.configuration.nexenta_dataset_description)
        self.iscsi_target_portal_port = (
            self.configuration.nexenta_iscsi_target_portal_port)
        self.root_path = posixpath.join(self.pool, self.volume_group)
        self.dataset_blocksize = self.configuration.nexenta_ns5_blocksize
        if not self.configuration.nexenta_ns5_blocksize > 128:
            self.dataset_blocksize *= units.Ki
        self.group_snapshot_template = (
            self.configuration.nexenta_group_snapshot_template)
        self.origin_snapshot_template = (
            self.configuration.nexenta_origin_snapshot_template)

    @staticmethod
    def get_driver_options():
        return (
            options.NEXENTA_CONNECTION_OPTS +
            options.NEXENTA_ISCSI_OPTS +
            options.NEXENTA_DATASET_OPTS
        )

    def do_setup(self, context):
        self.nef = jsonrpc.NefProxy(self.driver_volume_type,
                                    self.root_path,
                                    self.configuration)

    def check_for_setup_error(self):
        """Check root volume group and iSCSI target service."""
        try:
            self.nef.volumegroups.get(self.root_path)
        except jsonrpc.NefException as error:
            if error.code != 'ENOENT':
                raise
            payload = {'path': self.root_path,
                       'volumeBlockSize': self.dataset_blocksize}
            self.nef.volumegroups.create(payload)
        service = self.nef.services.get('iscsit')
        if service['state'] != 'online':
            message = (_('iSCSI target service is not online: %(state)s')
                       % {'state': service['state']})
            raise jsonrpc.NefException(code='ESRCH', message=message)

    def create_volume(self, volume):
        """Create a zfs volume on appliance.

        :param volume: volume reference
        :returns: model update dict for volume reference
        """
        payload = {
            'path': self._get_volume_path(volume),
            'volumeSize': volume['size'] * units.Gi,
            'volumeBlockSize': self.dataset_blocksize,
            'compressionMode': self.compressed_volumes,
            'sparseVolume': self.sparsed_volumes
        }
        self.nef.volumes.create(payload)

    @coordination.synchronized('{self.nef.lock}')
    def delete_volume(self, volume):
        """Deletes a logical volume.

        :param volume: volume reference
        """
        volume_path = self._get_volume_path(volume)
        delete_payload = {'snapshots': True}
        try:
            self.nef.volumes.delete(volume_path, delete_payload)
        except jsonrpc.NefException as error:
            if error.code != 'EEXIST':
                raise
            snapshots_tree = {}
            snapshots_payload = {'parent': volume_path, 'fields': 'path'}
            snapshots = self.nef.snapshots.list(snapshots_payload)
            for snapshot in snapshots:
                clones_payload = {'fields': 'clones,creationTxg'}
                data = self.nef.snapshots.get(snapshot['path'], clones_payload)
                if data['clones']:
                    snapshots_tree[data['creationTxg']] = data['clones'][0]
            if snapshots_tree:
                clone_path = snapshots_tree[max(snapshots_tree)]
                self.nef.volumes.promote(clone_path)
            self.nef.volumes.delete(volume_path, delete_payload)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        volume_path = self._get_volume_path(volume)
        payload = {'volumeSize': new_size * units.Gi}
        self.nef.volumes.set(volume_path, payload)

    @coordination.synchronized('{self.nef.lock}')
    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        payload = {'path': snapshot_path}
        self.nef.snapshots.create(payload)

    @coordination.synchronized('{self.nef.lock}')
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: snapshot reference
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        payload = {'defer': True}
        self.nef.snapshots.delete(snapshot_path, payload)

    def snapshot_revert_use_temp_snapshot(self):
        # Considering that NexentaStor based drivers use COW images
        # for storing snapshots, having chains of such images,
        # creating a backup snapshot when reverting one is not
        # actually helpful.
        return False

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert volume to snapshot."""
        volume_path = self._get_volume_path(volume)
        payload = {'snapshot': snapshot['name']}
        self.nef.volumes.rollback(volume_path, payload)

    @coordination.synchronized('{self.nef.lock}')
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        clone_path = self._get_volume_path(volume)
        payload = {'targetPath': clone_path}
        self.nef.snapshots.clone(snapshot_path, payload)
        if volume['size'] > snapshot['volume_size']:
            self.extend_volume(volume, volume['size'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        snapshot = {
            'name': self.origin_snapshot_template % volume['id'],
            'volume_id': src_vref['id'],
            'volume_name': src_vref['name'],
            'volume_size': src_vref['size']
        }
        self.create_snapshot(snapshot)
        try:
            self.create_volume_from_snapshot(volume, snapshot)
        except jsonrpc.NefException as error:
            LOG.debug('Failed to create clone %(clone)s '
                      'from volume %(volume)s: %(error)s',
                      {'clone': volume['name'],
                       'volume': src_vref['name'],
                       'error': error})
            raise
        finally:
            try:
                self.delete_snapshot(snapshot)
            except jsonrpc.NefException as error:
                LOG.debug('Failed to delete temporary snapshot '
                          '%(volume)s@%(snapshot)s: %(error)s',
                          {'volume': src_vref['name'],
                           'snapshot': snapshot['name'],
                           'error': error})

    def create_export(self, context, volume, connector):
        """Export a volume."""
        pass

    def ensure_export(self, context, volume):
        """Synchronously recreate an export for a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume."""
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate a connection to a volume.

        :param volume: a volume object
        :param connector: a connector object
        :returns: dictionary of connection information
        """
        info = {'driver_volume_type': self.driver_volume_type, 'data': {}}
        host_iqn = None
        host_groups = []
        volume_path = self._get_volume_path(volume)
        if isinstance(connector, dict) and 'initiator' in connector:
            connectors = []
            for attachment in volume['volume_attachment']:
                connectors.append(attachment.get('connector'))
            if connectors.count(connector) > 1:
                LOG.debug('Detected multiple connections on host '
                          '%(host_name)s [%(host_ip)s] for volume '
                          '%(volume)s, skip terminate volume connection',
                          {'host_name': connector.get('host', 'unknown'),
                           'host_ip': connector.get('ip', 'unknown'),
                           'volume': volume['name']})
                return True
            host_iqn = connector.get('initiator')
            host_groups.append(options.DEFAULT_HOST_GROUP)
            host_group = self._get_host_group(host_iqn)
            if host_group is not None:
                host_groups.append(host_group)
            LOG.debug('Terminate connection for volume %(volume)s '
                      'and initiator %(initiator)s',
                      {'volume': volume['name'],
                       'initiator': host_iqn})
        else:
            LOG.debug('Terminate all connections for volume %(volume)s',
                      {'volume': volume['name']})

        payload = {'volume': volume_path}
        mappings = self.nef.mappings.list(payload)
        if not mappings:
            LOG.debug('There are no LUN mappings found for volume %(volume)s',
                      {'volume': volume['name']})
            return info
        for mapping in mappings:
            mapping_id = mapping.get('id')
            mapping_tg = mapping.get('targetGroup')
            mapping_hg = mapping.get('hostGroup')
            if host_iqn is None or mapping_hg in host_groups:
                LOG.debug('Delete LUN mapping %(id)s for volume %(volume)s, '
                          'target group %(tg)s and host group %(hg)s',
                          {'id': mapping_id, 'volume': volume['name'],
                           'tg': mapping_tg, 'hg': mapping_hg})
                self._delete_lun_mapping(mapping_id)
            else:
                LOG.debug('Skip LUN mapping %(id)s for volume %(volume)s, '
                          'target group %(tg)s and host group %(hg)s',
                          {'id': mapping_id, 'volume': volume['name'],
                           'tg': mapping_tg, 'hg': mapping_hg})
        return info

    def _update_volume_stats(self):
        """Retrieve stats info for NexentaStor appliance."""
        LOG.debug('Updating volume backend %(volume_backend_name)s stats',
                  {'volume_backend_name': self.volume_backend_name})
        payload = {'fields': 'bytesAvailable,bytesUsed'}
        dataset = self.nef.volumegroups.get(self.root_path, payload)
        free = dataset['bytesAvailable'] // units.Gi
        used = dataset['bytesUsed'] // units.Gi
        total = free + used
        location_info = '%(driver)s:%(host)s:%(pool)s/%(group)s' % {
            'driver': self.__class__.__name__,
            'host': self.iscsi_host,
            'pool': self.pool,
            'group': self.volume_group,
        }
        self._stats = {
            'vendor_name': self.vendor_name,
            'dedup': self.deduplicated_volumes,
            'compression': self.compressed_volumes,
            'description': self.dataset_description,
            'nef_url': self.nef.host,
            'nef_port': self.nef.port,
            'driver_version': self.VERSION,
            'storage_protocol': self.storage_protocol,
            'sparsed_volumes': self.sparsed_volumes,
            'total_capacity_gb': total,
            'free_capacity_gb': free,
            'reserved_percentage': self.configuration.reserved_percentage,
            'QoS_support': False,
            'multiattach': True,
            'consistencygroup_support': True,
            'consistent_group_snapshot_enabled': True,
            'location_info': location_info,
            'volume_backend_name': self.volume_backend_name,
            'iscsi_target_portal_port': self.iscsi_target_portal_port
        }

    def _get_volume_path(self, volume):
        """Return ZFS datset path for the volume."""
        return posixpath.join(self.root_path, volume['name'])

    def _get_snapshot_path(self, snapshot):
        """Return ZFS snapshot path for the snapshot."""
        volume_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        volume_path = posixpath.join(self.root_path, volume_name)
        return '%s@%s' % (volume_path, snapshot_name)

    def _get_target_group_name(self, target_name):
        """Return Nexenta iSCSI target group name for volume."""
        return target_name.replace(
            self.configuration.nexenta_target_prefix,
            self.configuration.nexenta_target_group_prefix
        )

    def _get_target_name(self, target_group_name):
        """Return Nexenta iSCSI target name for volume."""
        return target_group_name.replace(
            self.configuration.nexenta_target_group_prefix,
            self.configuration.nexenta_target_prefix
        )

    def _get_host_addresses(self):
        """Return Nexenta IP addresses list."""
        host_addresses = []
        items = self.nef.netaddrs.list()
        for item in items:
            ip_cidr = six.text_type(item['address'])
            ip_addr, ip_mask = ip_cidr.split('/')
            ip_obj = ipaddress.ip_address(ip_addr)
            if not ip_obj.is_loopback:
                host_addresses.append(ip_obj.exploded)
        LOG.debug('Configured IP addresses: %(addresses)s',
                  {'addresses': host_addresses})
        return host_addresses

    def _get_host_portals(self):
        """Return configured iSCSI portals list."""
        host_portals = []
        host_addresses = self._get_host_addresses()
        portal_host = self.iscsi_host
        if portal_host:
            if portal_host in host_addresses:
                if self.portal_port:
                    portal_port = int(self.portal_port)
                else:
                    portal_port = options.DEFAULT_ISCSI_PORT
                host_portal = '%s:%s' % (portal_host, portal_port)
                host_portals.append(host_portal)
            else:
                LOG.debug('Skip not a local portal IP address %(portal)s',
                          {'portal': portal_host})
        else:
            LOG.debug('Configuration parameter nexenta_host is not defined')
        for portal in self.portals.split(','):
            if not portal:
                continue
            host_port = portal.split(':')
            portal_host = host_port[0]
            if portal_host in host_addresses:
                if len(host_port) == 2:
                    portal_port = int(host_port[1])
                else:
                    portal_port = options.DEFAULT_ISCSI_PORT
                host_portal = '%s:%s' % (portal_host, portal_port)
                if host_portal not in host_portals:
                    host_portals.append(host_portal)
            else:
                LOG.debug('Skip not a local portal IP address %(portal)s',
                          {'portal': portal_host})
        LOG.debug('Configured iSCSI portals: %(portals)s',
                  {'portals': host_portals})
        return host_portals

    def _target_group_props(self, group_name, host_portals):
        """Check and update an existing targets/portals for given target group.

        :param group_name: target group name
        :param host_portals: configured host portals list
        :returns: dictionary of portals per target
        """
        if not group_name.startswith(self.target_group_prefix):
            LOG.debug('Skip not a cinder target group %(group)s',
                      {'group': group_name})
            return {}
        group_props = {}
        payload = {'name': group_name}
        data = self.nef.targetgroups.list(payload)
        if not data:
            LOG.debug('Skip target group %(group)s: group not found',
                      {'group': group_name})
            return {}
        target_names = data[0]['members']
        if not target_names:
            target_name = self._get_target_name(group_name)
            self._create_target(target_name, host_portals)
            self._update_target_group(group_name, [target_name])
            group_props[target_name] = host_portals
            return group_props
        for target_name in target_names:
            group_props[target_name] = []
            payload = {'name': target_name}
            data = self.nef.targets.list(payload)
            if not data:
                LOG.debug('Skip target group %(group)s: '
                          'group member %(target)s not found',
                          {'group': group_name, 'target': target_name})
                return {}
            target_portals = data[0]['portals']
            if not target_portals:
                LOG.debug('Skip target group %(group)s: '
                          'group member %(target)s has no portals',
                          {'group': group_name, 'target': target_name})
                return {}
            for item in target_portals:
                target_portal = '%s:%s' % (item['address'], item['port'])
                if target_portal not in host_portals:
                    LOG.debug('Skip target group %(group)s: '
                              'group member %(target)s bind to a '
                              'non local portal address %(portal)s',
                              {'group': group_name,
                               'target': target_name,
                               'portal': target_portal})
                    return {}
                group_props[target_name].append(target_portal)
        return group_props

    def initialize_connection(self, volume, connector):
        """Do all steps to get zfs volume exported at separate target.

        :param volume: volume reference
        :param connector: connector reference
        :returns: dictionary of connection information
        """
        volume_path = self._get_volume_path(volume)
        host_iqn = connector.get('initiator')
        LOG.debug('Initialize connection for volume: %(volume)s '
                  'and initiator: %(initiator)s',
                  {'volume': volume_path, 'initiator': host_iqn})

        host_groups = [options.DEFAULT_HOST_GROUP]
        host_group = self._get_host_group(host_iqn)
        if host_group:
            host_groups.append(host_group)

        host_portals = self._get_host_portals()
        props_portals = []
        props_iqns = []
        props_luns = []
        payload = {'volume': volume_path}
        mappings = self.nef.mappings.list(payload)
        for mapping in mappings:
            mapping_id = mapping['id']
            mapping_lu = mapping['lun']
            mapping_hg = mapping['hostGroup']
            mapping_tg = mapping['targetGroup']
            if mapping_tg == options.DEFAULT_TARGET_GROUP:
                LOG.debug('Delete LUN mapping %(id)s for target group %(tg)s',
                          {'id': mapping_id, 'tg': mapping_tg})
                self._delete_lun_mapping(mapping_id)
                continue
            if mapping_hg not in host_groups:
                LOG.debug('Skip LUN mapping %(id)s for host group %(hg)s',
                          {'id': mapping_id, 'hg': mapping_hg})
                continue
            group_props = self._target_group_props(mapping_tg, host_portals)
            if not group_props:
                LOG.debug('Skip LUN mapping %(id)s for target group %(tg)s',
                          {'id': mapping_id, 'tg': mapping_tg})
                continue
            for target_iqn in group_props:
                target_portals = group_props[target_iqn]
                props_portals += target_portals
                props_iqns += [target_iqn] * len(target_portals)
                props_luns += [mapping_lu] * len(target_portals)

        props = {}
        props['target_discovered'] = False
        props['encrypted'] = False
        props['qos_specs'] = None
        props['volume_id'] = volume['id']
        props['access_mode'] = 'rw'
        multipath = connector.get('multipath', False)

        if props_luns:
            if multipath:
                props['target_portals'] = props_portals
                props['target_iqns'] = props_iqns
                props['target_luns'] = props_luns
            else:
                index = random.randrange(0, len(props_luns))
                props['target_portal'] = props_portals[index]
                props['target_iqn'] = props_iqns[index]
                props['target_lun'] = props_luns[index]
            LOG.debug('Use existing LUN mapping(s) %(props)s',
                      {'props': props})
            return {'driver_volume_type': self.driver_volume_type,
                    'data': props}

        if host_group is None:
            host_group = '%s-%s' % (self.host_group_prefix, uuid.uuid4().hex)
            self._create_host_group(host_group, [host_iqn])

        mappings_spread = {}
        targets_spread = {}
        data = self.nef.targetgroups.list()
        for item in data:
            target_group = item['name']
            group_props = self._target_group_props(target_group, host_portals)
            members = len(group_props)
            if members == 0:
                LOG.debug('Skip unsuitable target group %(tg)s',
                          {'tg': target_group})
                continue
            payload = {'targetGroup': target_group}
            data = self.nef.mappings.list(payload)
            mappings = len(data)
            if not mappings < self.luns_per_target:
                LOG.debug('Skip target group %(tg)s: '
                          'group members limit reached: %(limit)s',
                          {'tg': target_group, 'limit': mappings})
                continue
            targets_spread[target_group] = group_props
            mappings_spread[target_group] = mappings
            LOG.debug('Found target group %(tg)s with %(members)s '
                      'members and %(mappings)s LUNs',
                      {'tg': target_group, 'members': members,
                       'mappings': mappings})

        if not mappings_spread:
            target = '%s-%s' % (self.target_prefix, uuid.uuid4().hex)
            target_group = self._get_target_group_name(target)
            self._create_target(target, host_portals)
            self._create_target_group(target_group, [target])
            props_portals += host_portals
            props_iqns += [target] * len(host_portals)
        else:
            target_group = min(mappings_spread, key=mappings_spread.get)
            targets = targets_spread[target_group]
            members = targets.keys()
            mappings = mappings_spread[target_group]
            LOG.debug('Using existing target group %(tg)s '
                      'with members %(members)s and %(mappings)s LUNs',
                      {'tg': target_group, 'members': members,
                       'mappings': mappings})
            for target in targets:
                portals = targets[target]
                props_portals += portals
                props_iqns += [target] * len(portals)

        payload = {'volume': volume_path,
                   'targetGroup': target_group,
                   'hostGroup': host_group}
        self.nef.mappings.create(payload)
        mapping = {}
        for attempt in range(0, self.nef.retries):
            mapping = self.nef.mappings.list(payload)
            if mapping:
                break
            self.nef.delay(attempt)
        if not mapping:
            message = (_('Failed to get LUN number for %(volume)s')
                       % {'volume': volume_path})
            raise jsonrpc.NefException(code='ENOTBLK', message=message)
        lun = mapping[0]['lun']
        props_luns = [lun] * len(props_iqns)

        if multipath:
            props['target_portals'] = props_portals
            props['target_iqns'] = props_iqns
            props['target_luns'] = props_luns
        else:
            index = random.randrange(0, len(props_luns))
            props['target_portal'] = props_portals[index]
            props['target_iqn'] = props_iqns[index]
            props['target_lun'] = props_luns[index]

        if not self.lu_writebackcache_disabled:
            LOG.debug('Get LUN guid for volume %(volume)s',
                      {'volume': volume_path})
            payload = {'fields': 'guid', 'volume': volume_path}
            data = self.nef.logicalunits.list(payload)
            guid = data[0]['guid']
            payload = {'writebackCacheDisabled': False}
            self.nef.logicalunits.set(guid, payload)

        LOG.debug('Created new LUN mapping(s): %(props)s',
                  {'props': props})
        return {'driver_volume_type': self.driver_volume_type,
                'data': props}

    def _create_target_group(self, name, members):
        """Create a new target group with members.

        :param name: group name
        :param members: group members list
        """
        payload = {'name': name, 'members': members}
        self.nef.targetgroups.create(payload)

    def _update_target_group(self, name, members):
        """Update a existing target group with new members.

        :param name: group name
        :param members: group members list
        """
        payload = {'members': members}
        self.nef.targetgroups.set(name, payload)

    def _delete_lun_mapping(self, name):
        """Delete an existing LUN mapping.

        :param name: LUN mapping ID
        """
        self.nef.mappings.delete(name)

    def _create_target(self, name, portals):
        """Create a new target with portals.

        :param name: target name
        :param portals: target portals list
        """
        payload = {'name': name,
                   'portals': self._s2d(portals)}
        self.nef.targets.create(payload)

    def _get_host_group(self, member):
        """Find existing host group by group member.

        :param member: host group member
        :returns: host group name
        """
        host_groups = self.nef.hostgroups.list()
        for host_group in host_groups:
            members = host_group['members']
            if member in members:
                name = host_group['name']
                LOG.debug('Found host group %(name)s for member %(member)s',
                          {'name': name, 'member': member})
                return name
        return None

    def _create_host_group(self, name, members):
        """Create a new host group.

        :param name: host group name
        :param members: host group members list
        """
        payload = {'name': name, 'members': members}
        self.nef.hostgroups.create(payload)

    @staticmethod
    def _s2d(css):
        """Parse list of colon-separated address and port to dictionary.

        :param css: list of colon-separated address and port
        :returns: dictionary
        """
        result = []
        for key_val in css:
            key, val = key_val.split(':')
            result.append({'address': key, 'port': int(val)})
        return result

    @staticmethod
    def _d2s(kvp):
        """Parse dictionary to list of colon-separated address and port.

        :param kvp: dictionary
        :returns: list of colon-separated address and port
        """
        result = []
        for key_val in kvp:
            result.append('%s:%s' % (key_val['address'], key_val['port']))
        return result

    def create_consistencygroup(self, context, group):
        """Creates a consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :returns: group_model_update
        """
        group_model_update = {}
        return group_model_update

    def create_group(self, context, group):
        """Creates a group.

        :param context: the context of the caller.
        :param group: the group object.
        :returns: model_update
        """
        return self.create_consistencygroup(context, group)

    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be deleted.
        :param volumes: a list of volume dictionaries in the group.
        :returns: group_model_update, volumes_model_update
        """
        group_model_update = {}
        volumes_model_update = []
        for volume in volumes:
            self.delete_volume(volume)
        return group_model_update, volumes_model_update

    def delete_group(self, context, group, volumes):
        """Deletes a group.

        :param context: the context of the caller.
        :param group: the group object.
        :param volumes: a list of volume objects in the group.
        :returns: model_update, volumes_model_update
        """
        return self.delete_consistencygroup(context, group, volumes)

    def update_consistencygroup(self, context, group, add_volumes=None,
                                remove_volumes=None):
        """Updates a consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be updated.
        :param add_volumes: a list of volume dictionaries to be added.
        :param remove_volumes: a list of volume dictionaries to be removed.
        :returns: group_model_update, add_volumes_update, remove_volumes_update
        """
        group_model_update = {}
        add_volumes_update = []
        remove_volumes_update = []
        return group_model_update, add_volumes_update, remove_volumes_update

    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        """Updates a group.

        :param context: the context of the caller.
        :param group: the group object.
        :param add_volumes: a list of volume objects to be added.
        :param remove_volumes: a list of volume objects to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update
        """
        return self.update_consistencygroup(context, group, add_volumes,
                                            remove_volumes)

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a consistency group snapshot.

        :param context: the context of the caller.
        :param cgsnapshot: the dictionary of the cgsnapshot to be created.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :returns: group_model_update, snapshots_model_update
        """
        group_model_update = {}
        snapshots_model_update = []
        cgsnapshot_name = self.group_snapshot_template % cgsnapshot['id']
        cgsnapshot_path = '%s@%s' % (self.root_path, cgsnapshot_name)
        create_payload = {'path': cgsnapshot_path, 'recursive': True}
        self.nef.snapshots.create(create_payload)
        for snapshot in snapshots:
            volume_name = snapshot['volume_name']
            volume_path = posixpath.join(self.root_path, volume_name)
            snapshot_name = snapshot['name']
            snapshot_path = '%s@%s' % (volume_path, cgsnapshot_name)
            rename_payload = {'newName': snapshot_name}
            self.nef.snapshots.rename(snapshot_path, rename_payload)
        delete_payload = {'defer': True, 'recursive': True}
        self.nef.snapshots.delete(cgsnapshot_path, delete_payload)
        return group_model_update, snapshots_model_update

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be created.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """
        return self.create_cgsnapshot(context, group_snapshot, snapshots)

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a consistency group snapshot.

        :param context: the context of the caller.
        :param cgsnapshot: the dictionary of the cgsnapshot to be created.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :returns: group_model_update, snapshots_model_update
        """
        group_model_update = {}
        snapshots_model_update = []
        for snapshot in snapshots:
            self.delete_snapshot(snapshot)
        return group_model_update, snapshots_model_update

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be deleted.
        :param snapshots: a list of snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """
        return self.delete_cgsnapshot(context, group_snapshot, snapshots)

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        """Creates a consistency group from source.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :param volumes: a list of volume dictionaries in the group.
        :param cgsnapshot: the dictionary of the cgsnapshot as source.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :param source_cg: the dictionary of a consistency group as source.
        :param source_vols: a list of volume dictionaries in the source_cg.
        :returns: group_model_update, volumes_model_update
        """
        group_model_update = {}
        volumes_model_update = []
        if cgsnapshot and snapshots:
            for volume, snapshot in zip(volumes, snapshots):
                self.create_volume_from_snapshot(volume, snapshot)
        elif source_cg and source_vols:
            snapshot_name = self.origin_snapshot_template % group['id']
            snapshot_path = '%s@%s' % (self.root_path, snapshot_name)
            create_payload = {'path': snapshot_path, 'recursive': True}
            self.nef.snapshots.create(create_payload)
            for volume, source_vol in zip(volumes, source_vols):
                snapshot = {
                    'name': snapshot_name,
                    'volume_id': source_vol['id'],
                    'volume_name': source_vol['name'],
                    'volume_size': source_vol['size']
                }
                self.create_volume_from_snapshot(volume, snapshot)
            delete_payload = {'defer': True, 'recursive': True}
            self.nef.snapshots.delete(snapshot_path, delete_payload)
        return group_model_update, volumes_model_update

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source.

        :param context: the context of the caller.
        :param group: the Group object to be created.
        :param volumes: a list of Volume objects in the group.
        :param group_snapshot: the GroupSnapshot object as source.
        :param snapshots: a list of snapshot objects in group_snapshot.
        :param source_group: the Group object as source.
        :param source_vols: a list of volume objects in the source_group.
        :returns: model_update, volumes_model_update
        """
        return self.create_consistencygroup_from_src(context, group, volumes,
                                                     group_snapshot, snapshots,
                                                     source_group, source_vols)

    def _get_existing_volume(self, existing_ref):
        types = {
            'source-name': 'name',
            'source-guid': 'guid'
        }
        if not any(key in types for key in existing_ref):
            keys = ', '.join(types.keys())
            message = (_('Manage existing volume failed '
                         'due to invalid backend reference. '
                         'Volume reference must contain '
                         'at least one valid key: %(keys)s')
                       % {'keys': keys})
            raise jsonrpc.NefException(code='EINVAL', message=message)
        payload = {
            'parent': self.root_path,
            'fields': 'name,path,volumeSize'
        }
        for key, value in types.items():
            if key in existing_ref:
                payload[value] = existing_ref[key]
        existing_volumes = self.nef.volumes.list(payload)
        if len(existing_volumes) == 1:
            volume_path = existing_volumes[0]['path']
            volume_name = existing_volumes[0]['name']
            volume_size = existing_volumes[0]['volumeSize'] // units.Gi
            existing_volume = {
                'name': volume_name,
                'path': volume_path,
                'size': volume_size
            }
            vid = volume_utils.extract_id_from_volume_name(volume_name)
            if volume_utils.check_already_managed_volume(vid):
                message = (_('Volume %(name)s already managed')
                           % {'name': volume_name})
                raise jsonrpc.NefException(code='EBUSY', message=message)
            return existing_volume
        elif not existing_volumes:
            code = 'ENOENT'
            reason = _('no matching volumes were found')
        else:
            code = 'EINVAL'
            reason = _('too many volumes were found')
        message = (_('Unable to manage existing volume by '
                     'reference %(reference)s: %(reason)s')
                   % {'reference': existing_ref, 'reason': reason})
        raise jsonrpc.NefException(code=code, message=message)

    def _check_already_managed_snapshot(self, snapshot_id):
        """Check cinder database for already managed snapshot.

        :param snapshot_id: snapshot id parameter
        :returns: return True, if database entry with specified
                  snapshot id exists, otherwise return False
        """
        if not isinstance(snapshot_id, six.string_types):
            return False
        try:
            uuid.UUID(snapshot_id, version=4)
        except ValueError:
            return False
        ctxt = context.get_admin_context()
        return objects.Snapshot.exists(ctxt, snapshot_id)

    def _get_existing_snapshot(self, snapshot, existing_ref):
        types = {
            'source-name': 'name',
            'source-guid': 'guid'
        }
        if not any(key in types for key in existing_ref):
            keys = ', '.join(types.keys())
            message = (_('Manage existing snapshot failed '
                         'due to invalid backend reference. '
                         'Snapshot reference must contain '
                         'at least one valid key: %(keys)s')
                       % {'keys': keys})
            raise jsonrpc.NefException(code='EINVAL', message=message)
        volume_name = snapshot['volume_name']
        volume_size = snapshot['volume_size']
        volume = {'name': volume_name}
        volume_path = self._get_volume_path(volume)
        payload = {
            'parent': volume_path,
            'fields': 'name,path',
            'recursive': False
        }
        for key, value in types.items():
            if key in existing_ref:
                payload[value] = existing_ref[key]
        existing_snapshots = self.nef.snapshots.list(payload)
        if len(existing_snapshots) == 1:
            name = existing_snapshots[0]['name']
            path = existing_snapshots[0]['path']
            existing_snapshot = {
                'name': name,
                'path': path,
                'volume_name': volume_name,
                'volume_size': volume_size
            }
            sid = volume_utils.extract_id_from_snapshot_name(name)
            if self._check_already_managed_snapshot(sid):
                message = (_('Snapshot %(name)s already managed')
                           % {'name': name})
                raise jsonrpc.NefException(code='EBUSY', message=message)
            return existing_snapshot
        elif not existing_snapshots:
            code = 'ENOENT'
            reason = _('no matching snapshots were found')
        else:
            code = 'EINVAL'
            reason = _('too many snapshots were found')
        message = (_('Unable to manage existing snapshot by '
                     'reference %(reference)s: %(reason)s')
                   % {'reference': existing_ref, 'reason': reason})
        raise jsonrpc.NefException(code=code, message=message)

    @coordination.synchronized('{self.nef.lock}')
    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        existing_ref is passed straight through from the API request's
        manage_existing_ref value, and it is up to the driver how this should
        be interpreted.  It should be sufficient to identify a storage object
        that the driver should somehow associate with the newly-created cinder
        volume structure.

        There are two ways to do this:

        1. Rename the backend storage object so that it matches the,
           volume['name'] which is how drivers traditionally map between a
           cinder volume and the associated backend storage object.

        2. Place some metadata on the volume, or somewhere in the backend, that
           allows other driver requests (e.g. delete, clone, attach, detach...)
           to locate the backend storage object when required.

        If the existing_ref doesn't make sense, or doesn't refer to an existing
        backend storage object, raise a ManageExistingInvalidReference
        exception.

        The volume may have a volume_type, and the driver can inspect that and
        compare against the properties of the referenced backend storage
        object.  If they are incompatible, raise a
        ManageExistingVolumeTypeMismatch, specifying a reason for the failure.

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        """
        existing_volume = self._get_existing_volume(existing_ref)
        existing_volume_path = existing_volume['path']
        payload = {'volume': existing_volume_path}
        mappings = self.nef.mappings.list(payload)
        if mappings:
            message = (_('Failed to manage existing volume %(path)s '
                         'due to existing LUN mappings: %(mappings)s')
                       % {'path': existing_volume_path,
                          'mappings': mappings})
            raise jsonrpc.NefException(code='EEXIST', message=message)
        if existing_volume['name'] != volume['name']:
            volume_path = self._get_volume_path(volume)
            payload = {'newPath': volume_path}
            self.nef.volumes.rename(existing_volume_path, payload)

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        :returns size:       Volume size in GiB (integer)
        """
        existing_volume = self._get_existing_volume(existing_ref)
        return existing_volume['size']

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on the backend available for management by Cinder.

        Returns a list of dictionaries, each specifying a volume in the host,
        with the following keys:
        - reference (dictionary): The reference for a volume, which can be
          passed to "manage_existing".
        - size (int): The size of the volume according to the storage
          backend, rounded up to the nearest GB.
        - safe_to_manage (boolean): Whether or not this volume is safe to
          manage according to the storage backend. For example, is the volume
          in use or invalid for any reason.
        - reason_not_safe (string): If safe_to_manage is False, the reason why.
        - cinder_id (string): If already managed, provide the Cinder ID.
        - extra_info (string): Any extra information to return to the user

        :param cinder_volumes: A list of volumes in this host that Cinder
                               currently manages, used to determine if
                               a volume is manageable or not.
        :param marker:    The last item of the previous page; we return the
                          next results after this value (after sorting)
        :param limit:     Maximum number of items to return
        :param offset:    Number of items to skip after marker
        :param sort_keys: List of keys to sort results by (valid keys are
                          'identifier' and 'size')
        :param sort_dirs: List of directions to sort by, corresponding to
                          sort_keys (valid directions are 'asc' and 'desc')
        """
        manageable_volumes = []
        cinder_volume_names = {}
        for cinder_volume in cinder_volumes:
            key = cinder_volume['name']
            value = cinder_volume['id']
            cinder_volume_names[key] = value
        payload = {
            'parent': self.root_path,
            'fields': 'name,guid,path,volumeSize',
            'recursive': False
        }
        volumes = self.nef.volumes.list(payload)
        for volume in volumes:
            safe_to_manage = True
            reason_not_safe = None
            cinder_id = None
            extra_info = None
            path = volume['path']
            guid = volume['guid']
            size = volume['volumeSize'] // units.Gi
            name = volume['name']
            if name in cinder_volume_names:
                cinder_id = cinder_volume_names[name]
                safe_to_manage = False
                reason_not_safe = _('Volume already managed')
            else:
                payload = {
                    'volume': path,
                    'fields': 'hostGroup'
                }
                mappings = self.nef.mappings.list(payload)
                members = []
                for mapping in mappings:
                    hostgroup = mapping['hostGroup']
                    if hostgroup == options.DEFAULT_HOST_GROUP:
                        members.append(hostgroup)
                    else:
                        group = self.nef.hostgroups.get(hostgroup)
                        members += group['members']
                if members:
                    safe_to_manage = False
                    hosts = ', '.join(members)
                    reason_not_safe = (_('Volume is connected '
                                         'to host(s) %(hosts)s')
                                       % {'hosts': hosts})
            reference = {
                'source-name': name,
                'source-guid': guid
            }
            manageable_volumes.append({
                'reference': reference,
                'size': size,
                'safe_to_manage': safe_to_manage,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
                'extra_info': extra_info
            })
        return volume_utils.paginate_entries_list(manageable_volumes,
                                                  marker, limit, offset,
                                                  sort_keys, sort_dirs)

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything.  However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.

        :param volume: Cinder volume to unmanage
        """
        pass

    @coordination.synchronized('{self.nef.lock}')
    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        existing_ref is passed straight through from the API request's
        manage_existing_ref value, and it is up to the driver how this should
        be interpreted.  It should be sufficient to identify a storage object
        that the driver should somehow associate with the newly-created cinder
        snapshot structure.

        There are two ways to do this:

        1. Rename the backend storage object so that it matches the
           snapshot['name'] which is how drivers traditionally map between a
           cinder snapshot and the associated backend storage object.

        2. Place some metadata on the snapshot, or somewhere in the backend,
           that allows other driver requests (e.g. delete) to locate the
           backend storage object when required.

        If the existing_ref doesn't make sense, or doesn't refer to an existing
        backend storage object, raise a ManageExistingInvalidReference
        exception.

        :param snapshot:     Cinder volume snapshot to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume snapshot
        """
        existing_snapshot = self._get_existing_snapshot(snapshot, existing_ref)
        existing_snapshot_path = existing_snapshot['path']
        if existing_snapshot['name'] != snapshot['name']:
            payload = {'newName': snapshot['name']}
            self.nef.snapshots.rename(existing_snapshot_path, payload)

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of snapshot to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param snapshot:     Cinder volume snapshot to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume snapshot
        :returns size:       Volume snapshot size in GiB (integer)
        """
        existing_snapshot = self._get_existing_snapshot(snapshot, existing_ref)
        return existing_snapshot['volume_size']

    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        """List snapshots on the backend available for management by Cinder.

        Returns a list of dictionaries, each specifying a snapshot in the host,
        with the following keys:
        - reference (dictionary): The reference for a snapshot, which can be
          passed to "manage_existing_snapshot".
        - size (int): The size of the snapshot according to the storage
          backend, rounded up to the nearest GB.
        - safe_to_manage (boolean): Whether or not this snapshot is safe to
          manage according to the storage backend. For example, is the snapshot
          in use or invalid for any reason.
        - reason_not_safe (string): If safe_to_manage is False, the reason why.
        - cinder_id (string): If already managed, provide the Cinder ID.
        - extra_info (string): Any extra information to return to the user
        - source_reference (string): Similar to "reference", but for the
          snapshot's source volume.

        :param cinder_snapshots: A list of snapshots in this host that Cinder
                                 currently manages, used to determine if
                                 a snapshot is manageable or not.
        :param marker:    The last item of the previous page; we return the
                          next results after this value (after sorting)
        :param limit:     Maximum number of items to return
        :param offset:    Number of items to skip after marker
        :param sort_keys: List of keys to sort results by (valid keys are
                          'identifier' and 'size')
        :param sort_dirs: List of directions to sort by, corresponding to
                          sort_keys (valid directions are 'asc' and 'desc')

        """
        manageable_snapshots = []
        cinder_volume_names = {}
        cinder_snapshot_names = {}
        ctxt = context.get_admin_context()
        cinder_volumes = objects.VolumeList.get_all_by_host(ctxt, self.host)
        for cinder_volume in cinder_volumes:
            key = self._get_volume_path(cinder_volume)
            value = {
                'name': cinder_volume['name'],
                'size': cinder_volume['size']
            }
            cinder_volume_names[key] = value
        for cinder_snapshot in cinder_snapshots:
            key = cinder_snapshot['name']
            value = {
                'id': cinder_snapshot['id'],
                'size': cinder_snapshot['volume_size'],
                'parent': cinder_snapshot['volume_name']
            }
            cinder_snapshot_names[key] = value
        payload = {
            'parent': self.root_path,
            'fields': 'name,guid,path,parent,hprService,snaplistId',
            'recursive': True
        }
        snapshots = self.nef.snapshots.list(payload)
        for snapshot in snapshots:
            safe_to_manage = True
            reason_not_safe = None
            cinder_id = None
            extra_info = None
            name = snapshot['name']
            guid = snapshot['guid']
            path = snapshot['path']
            parent = snapshot['parent']
            if parent not in cinder_volume_names:
                LOG.debug('Skip snapshot %(path)s: parent '
                          'volume %(parent)s is unmanaged',
                          {'path': path, 'parent': parent})
                continue
            if name.startswith(self.origin_snapshot_template):
                LOG.debug('Skip temporary origin snapshot %(path)s',
                          {'path': path})
                continue
            if name.startswith(self.group_snapshot_template):
                LOG.debug('Skip temporary group snapshot %(path)s',
                          {'path': path})
                continue
            if snapshot['hprService'] or snapshot['snaplistId']:
                LOG.debug('Skip HPR/snapping snapshot %(path)s',
                          {'path': path})
                continue
            if name in cinder_snapshot_names:
                size = cinder_snapshot_names[name]['size']
                cinder_id = cinder_snapshot_names[name]['id']
                safe_to_manage = False
                reason_not_safe = _('Snapshot already managed')
            else:
                size = cinder_volume_names[parent]['size']
                payload = {'fields': 'clones'}
                props = self.nef.snapshots.get(path)
                clones = props['clones']
                unmanaged_clones = []
                for clone in clones:
                    if clone not in cinder_volume_names:
                        unmanaged_clones.append(clone)
                if unmanaged_clones:
                    safe_to_manage = False
                    dependent_clones = ', '.join(unmanaged_clones)
                    reason_not_safe = (_('Snapshot has unmanaged '
                                         'dependent clone(s) %(clones)s')
                                       % {'clones': dependent_clones})
            reference = {
                'source-name': name,
                'source-guid': guid
            }
            source_reference = {
                'name': cinder_volume_names[parent]['name']
            }
            manageable_snapshots.append({
                'reference': reference,
                'size': size,
                'safe_to_manage': safe_to_manage,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
                'extra_info': extra_info,
                'source_reference': source_reference
            })
        return volume_utils.paginate_entries_list(manageable_snapshots,
                                                  marker, limit, offset,
                                                  sort_keys, sort_dirs)

    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything. However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.

        :param snapshot: Cinder volume snapshot to unmanage
        """
        pass
