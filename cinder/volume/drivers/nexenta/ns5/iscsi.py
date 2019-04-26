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
from oslo_utils import strutils
from oslo_utils import units
import six

from cinder import context
from cinder.i18n import _
from cinder import objects
from cinder.volume import driver
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume import utils
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)


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
        1.4.4 - Added storage assisted volume migration.
                Added support for volume retype.
                Added support for volume type extra specs.
                Added vendor capabilities support.
        1.4.5 - Added report discard support.
    """

    VERSION = '1.4.5'
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
        self.driver_name = self.__class__.__name__
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
        self.iscsi_target_portal_port = (
            self.configuration.nexenta_iscsi_target_portal_port)
        self.root_path = posixpath.join(self.pool, self.volume_group)
        self.group_snapshot_template = (
            self.configuration.nexenta_group_snapshot_template)
        self.origin_snapshot_template = (
            self.configuration.nexenta_origin_snapshot_template)

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
            block_size = self.configuration.nexenta_ns5_blocksize
            if block_size < 512:
                block_size *= units.Ki
            payload = {
                'path': self.root_path,
                'volumeBlockSize': block_size
            }
            self.nef.volumegroups.create(payload)
        service = self.nef.services.get('iscsit')
        if service['state'] != 'online':
            message = (_('iSCSI target service is not online: %(state)s')
                       % {'state': service['state']})
            raise jsonrpc.NefException(code='ESRCH', message=message)

    @jsonrpc.synchronized
    def create_volume(self, volume):
        """Create a zfs volume on appliance.

        :param volume: volume reference
        :returns: model update dict for volume reference
        """
        volume_path = self._get_volume_path(volume)
        volume_size = volume['size'] * units.Gi
        properties = self.nef.volumes.properties
        payload = self._get_vendor_properties(volume, properties)
        payload.update({
            'path': volume_path,
            'volumeSize': volume_size
        })
        self.nef.volumes.create(payload)

    @jsonrpc.synchronized
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

    @jsonrpc.synchronized
    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        payload = {'path': snapshot_path}
        self.nef.snapshots.create(payload)

    @jsonrpc.synchronized
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: snapshot reference
        """
        snapshot_path = self._get_snapshot_path(snapshot)
        payload = {'defer': True}
        self.nef.snapshots.delete(snapshot_path, payload)

    @jsonrpc.synchronized
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
        """Driver entry point to get the export info for a new volume."""
        pass

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
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
            if 'volume_attachment' in volume:
                if isinstance(volume['volume_attachment'], list):
                    for attachment in volume['volume_attachment']:
                        if not isinstance(attachment, dict):
                            continue
                        if 'connector' not in attachment:
                            continue
                        connectors.append(attachment['connector'])
            if connectors.count(connector) > 1:
                LOG.debug('Detected %(count)s connections from host '
                          '%(host_name)s (IP:%(host_ip)s) to volume '
                          '%(volume)s, skip terminating connection',
                          {'count': connectors.count(connector),
                           'host_name': connector.get('host', 'unknown'),
                           'host_ip': connector.get('ip', 'unknown'),
                           'volume': volume['name']})
                return True
            host_iqn = connector['initiator']
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

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh or not self._stats:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info for NexentaStor appliance."""
        payload = {'fields': 'bytesAvailable,bytesUsed'}
        dataset = self.nef.volumegroups.get(self.root_path, payload)
        free_capacity_gb = dataset['bytesAvailable'] // units.Gi
        allocated_capacity_gb = dataset['bytesUsed'] // units.Gi
        total_capacity_gb = free_capacity_gb + allocated_capacity_gb
        provisioned_capacity_gb = total_volumes = 0
        ctxt = context.get_admin_context()
        volumes = objects.VolumeList.get_all_by_host(ctxt, self.host)
        for volume in volumes:
            provisioned_capacity_gb += volume['size']
            total_volumes += 1
        volume_backend_name = (
            self.configuration.safe_get('volume_backend_name'))
        if not volume_backend_name:
            LOG.debug('Failed to get configured volume backend name')
            volume_backend_name = '%(product)s_%(protocol)s' % {
                'product': self.product_name,
                'protocol': self.storage_protocol
            }
        description = (
            self.configuration.safe_get('nexenta_dataset_description'))
        if not description:
            description = '%(product)s %(host)s:%(pool)s/%(group)s' % {
                'product': self.product_name,
                'host': self.configuration.nexenta_host,
                'pool': self.configuration.nexenta_volume,
                'group': self.configuration.nexenta_volume_group
            }
        max_over_subscription_ratio = (
            self.configuration.safe_get('max_over_subscription_ratio'))
        reserved_percentage = (
            self.configuration.safe_get('reserved_percentage'))
        if reserved_percentage is None:
            reserved_percentage = 0
        location_info = '%(driver)s:%(host)s:%(pool)s/%(group)s' % {
            'driver': self.driver_name,
            'host': self.configuration.nexenta_host,
            'pool': self.configuration.nexenta_volume,
            'group': self.configuration.nexenta_volume_group
        }
        display_name = 'Capabilities of %(product)s %(protocol)s driver' % {
            'product': self.product_name,
            'protocol': self.storage_protocol
        }
        visibility = 'public'
        self._stats = {
            'driver_version': self.VERSION,
            'vendor_name': self.vendor_name,
            'storage_protocol': self.storage_protocol,
            'volume_backend_name': volume_backend_name,
            'location_info': location_info,
            'description': description,
            'display_name': display_name,
            'pool_name': self.configuration.nexenta_volume,
            'multiattach': True,
            'QoS_support': False,
            'consistencygroup_support': True,
            'consistent_group_snapshot_enabled': True,
            'online_extend_support': True,
            'sparse_copy_volume': True,
            'thin_provisioning_support': True,
            'thick_provisioning_support': True,
            'total_capacity_gb': total_capacity_gb,
            'allocated_capacity_gb': allocated_capacity_gb,
            'free_capacity_gb': free_capacity_gb,
            'provisioned_capacity_gb': provisioned_capacity_gb,
            'total_volumes': total_volumes,
            'max_over_subscription_ratio': max_over_subscription_ratio,
            'reserved_percentage': reserved_percentage,
            'visibility': visibility,
            'nef_port': self.nef.port,
            'nef_url': self.nef.host
        }
        LOG.debug('Updated volume backend statistics for host %(host)s '
                  'and volume backend %(volume_backend_name)s: %(stats)s',
                  {'host': self.host,
                   'volume_backend_name': volume_backend_name,
                   'stats': self._stats})

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
        props['discard'] = True
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
                index = random.randrange(len(props_luns))
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
        for attempt in range(self.nef.retries):
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
            index = random.randrange(len(props_luns))
            props['target_portal'] = props_portals[index]
            props['target_iqn'] = props_iqns[index]
            props['target_lun'] = props_luns[index]

        LOG.debug('Set LUN properties for volume %(volume)s',
                  {'volume': volume_path})
        payload = {
            'volume': volume_path,
            'fields': 'guid'
        }
        logicalunits = self.nef.logicalunits.list(payload)
        guid = logicalunits[0]['guid']
        properties = self.nef.logicalunits.properties
        payload = self._get_vendor_properties(volume, properties)
        self.nef.logicalunits.set(guid, payload)

        LOG.debug('Created new LUN mapping: %(props)s',
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
            vid = utils.extract_id_from_volume_name(volume_name)
            if utils.check_already_managed_volume(vid):
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
            sid = utils.extract_id_from_snapshot_name(name)
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

    @jsonrpc.synchronized
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
        return utils.paginate_entries_list(manageable_volumes,
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

    @jsonrpc.synchronized
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
        return utils.paginate_entries_list(manageable_snapshots,
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

    def local_path(self, volume):
        """Return local path to existing local volume."""
        raise NotImplementedError()

    def migrate_volume(self, context, volume, host):
        """Migrate the volume to the specified host.

        Returns a boolean indicating whether the migration occurred,
        as well as model_update.

        :param context: Security context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug('Start storage assisted volume migration '
                  'for volume %(volume)s to host %(host)s',
                  {'volume': volume['name'],
                   'host': host['host']})
        false_ret = (False, None)
        if 'capabilities' not in host:
            LOG.debug('No host capabilities found for '
                      'the destination host %(host)s',
                      {'host': host['host']})
            return false_ret
        capabilities = host['capabilities']
        required_capabilities = [
            'vendor_name',
            'location_info',
            'storage_protocol',
            'free_capacity_gb',
            'nef_url',
            'nef_port'
        ]
        for capability in required_capabilities:
            if capability not in capabilities:
                LOG.debug('Required host capability %(capability)s not '
                          'found for the destination host %(host)s',
                          {'capability': capability, 'host': host['host']})
                return false_ret
        vendor = capabilities['vendor_name']
        if vendor != self.vendor_name:
            LOG.debug('Unsupported vendor %(vendor)s found '
                      'for the destination host %(host)s',
                      {'vendor': vendor, 'host': host['host']})
            return false_ret
        location = capabilities['location_info']
        try:
            driver, san_host, san_path = location.split(':')
        except ValueError as error:
            LOG.debug('Failed to split location info %(location)s '
                      'for the destination host %(host)s: %(error)s',
                      {'location': location, 'host': host['host'],
                       'error': error})
            return false_ret
        if not (driver and san_path):
            LOG.debug('Incomplete location info %(location)s '
                      'found for the destination host %(host)s',
                      {'location': location, 'host': host['host']})
            return false_ret
        if driver != self.driver_name:
            LOG.debug('Unsupported storage driver %(driver)s '
                      'found for the destination host %(host)s',
                      {'driver': driver, 'host': host['host']})
            return false_ret
        try:
            payload = {'fields': 'name'}
            self.nef.hpr.list(payload)
        except jsonrpc.NefException as error:
            LOG.debug('Storage assisted volume migration is unavailable '
                      'for the destination host %(host)s: %(error)s',
                      {'host': host['host'], 'error': error})
            return false_ret
        src_path = self._get_volume_path(volume)
        dst_path = posixpath.join(san_path, volume['name'])
        dst_port = capabilities['nef_port']
        src_hosts = self._get_host_addresses()
        dst_hosts = capabilities['nef_url'].split(',')
        service_name = 'cinder-migrate-%s' % volume['name']
        service_created = service_running = service_success = False
        while dst_hosts and not service_created:
            dst_host = dst_hosts.pop()
            if dst_host is not None:
                dst_host = dst_host.strip()
            payload = {
                'name': service_name,
                'sourceDataset': src_path,
                'destinationDataset': dst_path,
                'type': 'scheduled'
            }
            if dst_host not in src_hosts:
                payload['isSource'] = True
                payload['remoteNode'] = {
                    'host': dst_host,
                    'port': dst_port
                }
            elif src_path == dst_path:
                LOG.debug('Skip local to local replication: '
                          'source volume %(src_path)s and '
                          'destination volume %(dst_path)s '
                          'are the same volume',
                          {'src_path': src_path,
                           'dst_path': dst_path})
                return True, None
            try:
                self.nef.hpr.create(payload)
                service_created = True
            except jsonrpc.NefException as error:
                LOG.debug('Failed to create replication service '
                          'with payload %(payload)s: %(error)s',
                          {'payload': payload, 'error': error})
                if error.code not in ('ENOENT', 'EINVAL'):
                    return false_ret
        if service_created:
            try:
                self.nef.hpr.start(service_name)
                service_running = True
            except jsonrpc.NefException as error:
                LOG.debug('Failed to start replication service '
                          '%(service_name)s: %(error)s',
                          {'service_name': service_name,
                           'error': error})
        retry_count = 0
        while service_running and not service_success:
            try:
                service = self.nef.hpr.get(service_name)
            except jsonrpc.NefException as error:
                LOG.debug('Failed to stat replication service '
                          '%(service_name)s: %(error)s',
                          {'service_name': service_name,
                           'error': error})
                break
            state = service['state']
            if state == 'faulted':
                service_error = service['lastError']
                LOG.debug('Replication service %(service_name)s '
                          'failed with error: %(service_error)s',
                          {'service_name': service_name,
                           'service_error': service_error})
                break
            elif state == 'disabled':
                LOG.debug('Replication service %(service_name)s '
                          'successfully replicated %(src_path)s '
                          'to %(dst_host)s:%(dst_path)s',
                          {'service_name': service_name,
                           'src_path': src_path,
                           'dst_host': dst_host,
                           'dst_path': dst_path})
                service_running = False
                service_success = True
                break
            else:
                progress = service['progress']
                LOG.debug('Replication service %(service_name)s '
                          'is running, progress %(progress)s%%',
                          {'service_name': service_name,
                           'progress': progress})
                self.nef.delay(retry_count)
                retry_count += 1
        if service_created:
            payload = {
                'destroySourceSnapshots': True,
                'destroyDestinationSnapshots': True,
                'force': True
            }
            try:
                self.nef.hpr.delete(service_name, payload)
            except jsonrpc.NefException as error:
                LOG.debug('Failed to delete replication service '
                          '%(service_name)s: %(error)s',
                          {'service_name': service_name,
                           'error': error})
        if not service_success:
            return false_ret
        try:
            self.delete_volume(volume)
        except jsonrpc.NefException as error:
            LOG.debug('Failed to delete source '
                      'volume %(volume)s: %(error)s',
                      {'volume': volume['name'],
                       'error': error})
        return True, None

    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status):
        """Return model update for migrated volume.

        This method should rename the back-end volume name on the
        destination host back to its original name on the source host.

        :param context: The context of the caller
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :returns: model_update to update DB with any needed changes
        """
        name_id = None
        path = self._get_volume_path(volume)
        new_path = self._get_volume_path(new_volume)
        payload = {'newPath': path}
        try:
            self.terminate_connection(new_volume, None)
        except jsonrpc.NefException as error:
            LOG.debug('Failed to terminate all connections '
                      'to migrated volume %(volume)s before '
                      'renaming: %(error)s',
                      {'volume': new_volume['name'],
                       'error': error})
        try:
            self.nef.volumes.rename(new_path, payload)
        except jsonrpc.NefException as error:
            LOG.debug('Failed to rename volume %(new_volume)s '
                      'to %(volume)s after migration: %(error)s',
                      {'new_volume': new_volume['name'],
                       'volume': volume['name'],
                       'error': error})
            name_id = new_volume._name_id or new_volume.id
        model_update = {'_name_id': name_id}
        return model_update

    def retype(self, context, volume, new_type, diff, host):
        """Retype from one volume type to another."""
        LOG.debug('Retype volume %(volume)s to host %(host)s '
                  'and volume type %(type)s with diff %(diff)s',
                  {'volume': volume['name'], 'host': host['host'],
                   'type': new_type['name'], 'diff': diff})
        retyped = False
        migrated, model_update = self.migrate_volume(context, volume, host)
        volume_path = self._get_volume_path(volume)
        payload = {'source': True}
        volume_specs = self.nef.volumes.get(volume_path, payload)
        payload = {}
        extra_specs = volume_types.get_volume_type_extra_specs(new_type['id'])
        vendor_specs = self.nef.volumes.properties
        for vendor_spec in vendor_specs:
            property_name = vendor_spec['name']
            api = vendor_spec['api']
            if 'retype' in vendor_spec:
                LOG.debug('Skip retype vendor volume property '
                          '%(property_name)s. %(reason)s',
                          {'property_name': property_name,
                           'reason': vendor_spec['retype']})
                continue
            if property_name in extra_specs:
                extra_spec = extra_specs[property_name]
                value = self._get_vendor_value(extra_spec, vendor_spec)
                payload[api] = value
            elif (api in volume_specs and 'source' in volume_specs and
                    api in volume_specs['source'] and
                    volume_specs['source'][api] in ['local', 'received']):
                if 'cfg' in vendor_spec:
                    cfg = vendor_spec['cfg']
                    value = self.configuration.safe_get(cfg)
                    if volume_specs[api] != value:
                        payload[api] = value
                else:
                    if 'inherit' in vendor_spec:
                        LOG.debug('Skip inherit vendor volume property '
                                  '%(property_name)s. %(reason)s',
                                  {'property_name': property_name,
                                   'reason': vendor_spec['inherit']})
                        continue
                    payload[api] = None
        try:
            self.nef.volumes.set(volume_path, payload)
            retyped = True
        except jsonrpc.NefException as error:
            LOG.debug('Failed to retype volume %(volume)s: %(error)s',
                      {'volume': volume['name'], 'error': error})
        return retyped or migrated, model_update

    def _init_vendor_properties(self):
        """Create a dictionary of vendor unique properties.

        This method creates a dictionary of vendor unique properties
        and returns both created dictionary and vendor name.
        Returned vendor name is used to check for name of vendor
        unique properties.

        - Vendor name shouldn't include colon(:) because of the separator
          and it is automatically replaced by underscore(_).
          ex. abc:d -> abc_d
        - Vendor prefix is equal to vendor name.
          ex. abcd
        - Vendor unique properties must start with vendor prefix + ':'.
          ex. abcd:maxIOPS

        Each backend driver needs to override this method to expose
        its own properties using _set_property() like this:

        self._set_property(
            properties,
            "vendorPrefix:specific_property",
            "Title of property",
            _("Description of property"),
            "type")

        : return dictionary of vendor unique properties
        : return vendor name
        """
        properties = {}
        vendor_properties = []
        namespace = self.nef.volumes.namespace
        keys = ('enum', 'default', 'minimum', 'maximum')
        vendor_properties += self.nef.volumes.properties
        vendor_properties += self.nef.logicalunits.properties
        for vendor_spec in vendor_properties:
            property_spec = {}
            for key in keys:
                if key in vendor_spec:
                    property_spec[key] = vendor_spec[key]
            property_name = vendor_spec['name']
            property_title = vendor_spec['title']
            property_description = vendor_spec['description']
            property_type = vendor_spec['type']
            LOG.debug('Set %(product_name)s %(storage_protocol)s backend '
                      '%(property_type)s property %(property_name)s: '
                      '%(property_spec)s',
                      {'product_name': self.product_name,
                       'storage_protocol': self.storage_protocol,
                       'property_type': property_type,
                       'property_name': property_name,
                       'property_spec': property_spec})
            self._set_property(
                properties,
                property_name,
                property_title,
                property_description,
                property_type,
                **property_spec
            )
        return properties, namespace

    def _get_vendor_properties(self, volume, vendor_specs):
        properties = extra_specs = {}
        type_id = volume.get('volume_type_id', None)
        if type_id:
            extra_specs = volume_types.get_volume_type_extra_specs(type_id)
        for vendor_spec in vendor_specs:
            property_name = vendor_spec['name']
            if property_name in extra_specs:
                extra_spec = extra_specs[property_name]
                value = self._get_vendor_value(extra_spec, vendor_spec)
            elif 'cfg' in vendor_spec:
                cfg = vendor_spec['cfg']
                value = self.configuration.safe_get(cfg)
            else:
                continue
            api = vendor_spec['api']
            if api == 'volumeBlockSize' and value < 512:
                value *= units.Ki
            properties[api] = value
            LOG.debug('Get vendor property name %(property_name)s '
                      'with API name %(api)s and %(type)s value '
                      '%(value)s for volume %(volume)s',
                      {'property_name': property_name,
                       'api': api,
                       'type': type(value).__name__,
                       'value': value,
                       'volume': volume['name']})
        return properties

    def _get_vendor_value(self, value, vendor_spec):
        name = vendor_spec['name']
        code = 'EINVAL'
        if vendor_spec['type'] == 'integer':
            try:
                value = int(value)
            except ValueError:
                message = (_('Invalid non-integer value %(value)s for '
                             'vendor property name %(name)s')
                           % {'value': value, 'name': name})
                raise jsonrpc.NefException(code=code, message=message)
            if 'minimum' in vendor_spec:
                minimum = vendor_spec['minimum']
                if value < minimum:
                    message = (_('Integer value %(value)s is less than '
                                 'allowed minimum %(minimum)s for vendor '
                                 'property name %(name)s')
                               % {'value': value, 'minimum': minimum,
                                  'name': name})
                    raise jsonrpc.NefException(code=code, message=message)
            if 'maximum' in vendor_spec:
                maximum = vendor_spec['maximum']
                if value > maximum:
                    message = (_('Integer value %(value)s is greater than '
                                 'allowed maximum %(maximum)s for vendor '
                                 'property name %(name)s')
                               % {'value': value, 'maximum': maximum,
                                  'name': name})
                    raise jsonrpc.NefException(code=code, message=message)
        elif vendor_spec['type'] == 'string':
            try:
                value = str(value)
            except UnicodeEncodeError:
                message = (_('Invalid non-ASCII value %(value)s for vendor '
                             'property name %(name)s')
                           % {'value': value, 'name': name})
                raise jsonrpc.NefException(code=code, message=message)
        elif vendor_spec['type'] == 'boolean':
            words = value.split()
            if len(words) == 2 and words[0] == '<is>':
                value = words[1]
            try:
                value = strutils.bool_from_string(value, strict=True)
            except ValueError:
                message = (_('Invalid non-boolean value %(value)s for vendor '
                             'property name %(name)s')
                           % {'value': value, 'name': name})
                raise jsonrpc.NefException(code=code, message=message)
        if 'enum' in vendor_spec:
            enum = vendor_spec['enum']
            if value not in enum:
                message = (_('Value %(value)s is out of allowed enumeration '
                             '%(enum)s for vendor property name %(name)s')
                           % {'value': value, 'enum': enum, 'name': name})
                raise jsonrpc.NefException(code=code, message=message)
        return value
