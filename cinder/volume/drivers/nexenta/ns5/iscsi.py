# Copyright 2018 Nexenta Systems, Inc.
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

import math
import random
import uuid

from eventlet import greenthread
from oslo_log import log as logging
from oslo_utils import units
from six.moves import urllib

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.volume import driver
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils

VERSION = '1.3.2'
LOG = logging.getLogger(__name__)


class NexentaISCSIDriver(driver.ISCSIDriver):
    """Executes volume driver commands on Nexenta Appliance.

    Version history:
        1.0.0 - Initial driver version.
        1.1.0 - Added HTTPS support.
                Added use of sessions for REST calls.
                Added abandoned volumes and snapshots cleanup.
        1.2.0 - Failover support.
        1.2.1 - Configurable luns per parget, target prefix.
        1.3.0 - Removed target/TG caching, added support for target portals
                and host groups.
        1.3.1 - Refactored _do_export to query exact lunMapping.
        1.3.2 - Refactored LUN creation, use host group for LUN mappings.
    """

    VERSION = VERSION

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Nexenta_CI"

    def __init__(self, *args, **kwargs):
        super(NexentaISCSIDriver, self).__init__(*args, **kwargs)
        self.nef = None
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_ISCSI_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_DATASET_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_RRMGR_OPTS)
        self.verify_ssl = self.configuration.driver_ssl_cert_verify
        self.target_prefix = self.configuration.nexenta_target_prefix
        self.target_group_prefix = (
            self.configuration.nexenta_target_group_prefix)
        self.host_group_prefix = self.configuration.nexenta_host_group_prefix
        self.luns_per_target = self.configuration.nexenta_luns_per_target
        self.lu_writebackcache_disabled = (
            self.configuration.nexenta_lu_writebackcache_disabled)
        self.use_https = self.configuration.nexenta_use_https
        self.nef_host = self.configuration.nexenta_rest_address
        self.iscsi_host = self.configuration.nexenta_host
        self.nef_port = self.configuration.nexenta_rest_port
        self.nef_user = self.configuration.nexenta_user
        self.nef_password = self.configuration.nexenta_password
        self.storage_pool = self.configuration.nexenta_volume
        self.volume_group = self.configuration.nexenta_volume_group
        self.portal_port = self.configuration.nexenta_iscsi_target_portal_port
        self.portals = self.configuration.nexenta_iscsi_target_portals
        self.dataset_compression = (
            self.configuration.nexenta_dataset_compression)
        self.dataset_deduplication = self.configuration.nexenta_dataset_dedup
        self.dataset_description = (
            self.configuration.nexenta_dataset_description)
        self.iscsi_target_portal_port = (
            self.configuration.nexenta_iscsi_target_portal_port)

    @property
    def backend_name(self):
        backend_name = None
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = self.__class__.__name__
        return backend_name

    def do_setup(self, context):
        host = self.nef_host or self.iscsi_host
        self.nef = jsonrpc.NexentaJSONProxy(
            host, self.nef_port, self.nef_user,
            self.nef_password, self.use_https, self.verify_ssl)
        url = 'storage/volumeGroups'
        data = {
            'path': '/'.join([self.storage_pool, self.volume_group]),
            'volumeBlockSize': (
                self.configuration.nexenta_ns5_blocksize * units.Ki)
        }
        try:
            self.nef.post(url, data)
        except exception.NexentaException as e:
            if 'EEXIST' in e.args[0]:
                LOG.debug('volumeGroup already exists, skipping')
            else:
                raise

    def check_for_setup_error(self):
        """Verify that the zfs pool, vg and iscsi service exists.

        :raise: :py:exc:`LookupError`
        """
        url = 'storage/pools/%s' % self.storage_pool
        self.nef.get(url)
        url = 'storage/volumeGroups/%s' % '%2F'.join([
            self.storage_pool, self.volume_group])
        try:
            self.nef.get(url)
        except exception.NexentaException:
            raise LookupError(_(
                "Dataset group %s not found at Nexenta SA"), '/'.join(
                [self.storage_pool, self.volume_group]))
        services = self.nef.get('services')
        for service in services['data']:
            if service['name'] == 'iscsit':
                if service['state'] != 'online':
                    raise exception.NexentaException(
                        'iSCSI service is not running on NS appliance')
                break

    def create_volume(self, volume):
        """Create a zfs volume on appliance.

        :param volume: volume reference
        :return: model update dict for volume reference
        """
        url = 'storage/volumes'
        path = '/'.join([self.storage_pool, self.volume_group, volume['name']])
        data = {
            'path': path,
            'volumeSize': volume['size'] * units.Gi,
            'volumeBlockSize': (
                self.configuration.nexenta_ns5_blocksize * units.Ki),
            'sparseVolume': self.configuration.nexenta_sparse
        }
        self.nef.post(url, data)

    def delete_volume(self, volume):
        """Destroy a zfs volume on appliance.

        :param volume: volume reference
        """
        path = '%2F'.join([
            self.storage_pool, self.volume_group, volume['name']])
        url = 'storage/volumes?path=%s' % path
        data = self.nef.get(url).get('data')
        if data:
            origin = data[0].get('originalSnapshot')
        else:
            LOG.info(_LI('Volume %s does not exist, it seems it was '
                         'already deleted.'), volume['name'])
            return
        try:
            url = 'storage/volumes/%s?snapshots=true' % path
            self.nef.delete(url)
        except exception.NexentaException as exc:
            if 'Failed to destroy snap' in exc.kwargs['message']['message']:
                url = 'storage/snapshots?parent=%s' % path
                snap_map = {}
                for snap in self.nef.get(url)['data']:
                    url = 'storage/snapshots/%s' % (
                        urllib.parse.quote_plus(snap['path']))
                    data = self.nef.get(url)
                    if data['clones']:
                        snap_map[data['creationTxg']] = snap['path']
                snap = snap_map[max(snap_map)]
                url = 'storage/snapshots/%s' % urllib.parse.quote_plus(snap)
                clone = self.nef.get(url)['clones'][0]
                url = 'storage/volumes/%s/promote' % urllib.parse.quote_plus(
                    clone)
                self.nef.post(url)
                url = 'storage/volumes/%s?snapshots=true' % path
                self.nef.delete(url)
            else:
                raise
        if origin and 'clone' in origin:
            url = 'storage/snapshots/%s' % urllib.parse.quote_plus(origin)
            self.nef.delete(url)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        LOG.info('Extending volume: %(id)s New size: %(size)s GB',
                 {'id': volume['id'], 'size': new_size})
        path = '%2F'.join([
            self.storage_pool, self.volume_group, volume['name']])
        url = 'storage/volumes/%s' % path

        self.nef.put(url, {'volumeSize': new_size * units.Gi})

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        snapshot_vol = self._get_snapshot_volume(snapshot)
        LOG.info('Creating snapshot %(snap)s of volume %(vol)s', {
            'snap': snapshot['name'],
            'vol': snapshot_vol['name']
        })
        volume_path = self._get_volume_path(snapshot_vol)
        url = 'storage/snapshots'
        data = {'path': '%s@%s' % (volume_path, snapshot['name'])}
        self.nef.post(url, data)

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot on appliance.

        :param snapshot: snapshot reference
        """
        LOG.info('Deleting snapshot: %s', snapshot['name'])
        snapshot_vol = self._get_snapshot_volume(snapshot)
        volume_path = self._get_volume_path(snapshot_vol)
        pool, group, volume = volume_path.split('/')
        path = '%2F'.join([self.storage_pool, self.volume_group, volume])
        url = 'storage/snapshots/%s@%s' % (path, snapshot['name'])
        try:
            self.nef.delete(url)
        except exception.NexentaException:
            return

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        LOG.info('Creating volume from snapshot: %s', snapshot['name'])
        snapshot_vol = self._get_snapshot_volume(snapshot)
        path = '%2F'.join([
            self.storage_pool, self.volume_group, snapshot_vol['name']])
        url = 'storage/snapshots/%s@%s/clone' % (path, snapshot['name'])
        self.nef.post(url, {'targetPath': self._get_volume_path(volume)})
        if (('size' in volume) and (
                volume['size'] > snapshot['volume_size'])):
            self.extend_volume(volume, volume['size'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        snapshot = {'volume_name': src_vref['name'],
                    'volume_id': src_vref['id'],
                    'volume_size': src_vref['size'],
                    'name': self._get_clone_snapshot_name(volume)}
        LOG.debug('Creating temp snapshot of the original volume: '
                  '%s@%s', snapshot['volume_name'], snapshot['name'])
        self.create_snapshot(snapshot)
        try:
            self.create_volume_from_snapshot(volume, snapshot)
        except exception.NexentaException:
            LOG.error('Volume creation failed, deleting created snapshot '
                      '%s', '@'.join([snapshot['volume_name'],
                                     snapshot['name']]))
            try:
                self.delete_snapshot(snapshot)
            except (exception.NexentaException, exception.SnapshotIsBusy):
                LOG.warning('Failed to delete zfs snapshot '
                            '%s', '@'.join([snapshot['volume_name'],
                                           snapshot['name']]))
            raise

    def create_export(self, _ctx, volume, connector):
        """Export a volume."""
        pass

    def ensure_export(self, _ctx, volume):
        """Synchronously recreate an export for a volume."""
        pass

    def remove_export(self, _ctx, volume):
        """Remove an export for a volume."""
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        """Remove LUN mapping.

        :param volume: the volume object
        :param connector: the connector object
        """
        LOG.debug('Terminate connection for volume %s and connector: %s',
                  volume, connector)
        host_groups = [options.DEFAULT_HOST_GROUP]
        volume_path = self._get_volume_path(volume)
        params = {'fields': 'id', 'volume': volume_path}
        host_iqn = connector.get('initiator')
        host_group = self._get_host_group(host_iqn)
        if host_group:
            host_groups.append(host_group)

        for host_group in host_groups:
            params['hostGroup'] = host_group
            url = 'san/lunMappings?%s' % urllib.parse.urlencode(params)
            data = self.nef.get(url).get('data')
            if not data:
                continue
            url = 'san/lunMappings/%s' % urllib.parse.quote_plus(data[0]['id'])
            LOG.debug('Deleting LUN mapping for %s', params)
            self.nef.delete(url)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info for NexentaStor appliance."""
        LOG.debug('Updating volume stats')

        url = 'storage/volumeGroups/%s?fields=bytesAvailable,bytesUsed' % (
            '%2F'.join([self.storage_pool, self.volume_group]))
        stats = self.nef.get(url)
        free = utils.str2gib_size(stats['bytesAvailable'])
        allocated = utils.str2gib_size(stats['bytesUsed'])

        location_info = '%(driver)s:%(host)s:%(pool)s/%(group)s' % {
            'driver': self.__class__.__name__,
            'host': self.iscsi_host,
            'pool': self.storage_pool,
            'group': self.volume_group,
        }
        self._stats = {
            'vendor_name': 'Nexenta',
            'dedup': self.dataset_deduplication,
            'compression': self.dataset_compression,
            'description': self.dataset_description,
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'sparsed_volumes': self.configuration.nexenta_sparse,
            'total_capacity_gb': free + allocated,
            'free_capacity_gb': free,
            'reserved_percentage': self.configuration.reserved_percentage,
            'QoS_support': False,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': self.iscsi_target_portal_port,
            'nef_url': self.nef.url
        }

    # auxiliary methods  ######################################################
    def _get_volume_path(self, volume):
        """Return zfs volume name that corresponds given volume name."""
        return '%s/%s/%s' % (self.storage_pool, self.volume_group,
                             volume['name'])

    @staticmethod
    def _get_clone_snapshot_name(volume):
        """Return name for snapshot that will be used to clone the volume."""
        return 'cinder-clone-snapshot-%(id)s' % volume

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

    def initialize_connection(self, volume, connector):
        """Do all steps to get zfs volume exported at separate target.

        :param volume: reference of volume to be exported
        """
        LOG.debug('Initialize connection for volume: %s and connector: %s',
                  volume, connector)

        config_portals = []
        if self.iscsi_host:
            if self.portal_port:
                portal_port = int(self.portal_port)
            else:
                portal_port = options.DEFAULT_ISCSI_PORT
            config_portal = '%s:%s' % (self.iscsi_host, portal_port)
            if config_portal not in config_portals:
                config_portals.append(config_portal)

        for portal in self.portals.split(','):
            if not portal:
                continue
            host_port = portal.split(':')
            portal_host = host_port[0]
            if len(host_port) == 2:
                portal_port = int(host_port[1])
            else:
                portal_port = options.DEFAULT_ISCSI_PORT
            config_portal = '%s:%s' % (portal_host, portal_port)
            if config_portal not in config_portals:
                config_portals.append(config_portal)

        LOG.debug('Configured portals: %s', config_portals)

        host_iqn = connector.get('initiator')
        host_groups = [options.DEFAULT_HOST_GROUP]
        host_group_name = self._get_host_group(host_iqn)
        if host_group_name:
            host_groups.append(host_group_name)

        props_portals = []
        props_iqns = []
        props_luns = []
        volume_path = self._get_volume_path(volume)
        params = {'volume': volume_path}
        url = 'san/lunMappings?%s' % urllib.parse.urlencode(params)
        mappings = self.nef.get(url).get('data')
        for mapping in mappings:
            if mapping['hostGroup'] not in host_groups:
                LOG.debug('Skip LUN mapping %s', mapping)
                continue
            url = 'san/targetgroups/%s' % urllib.parse.quote_plus(
                mapping['targetGroup'])
            target_iqns = self.nef.get(url).get('members')
            for target_iqn in target_iqns:
                url = 'san/iscsi/targets/%s' % \
                    urllib.parse.quote_plus(target_iqn)
                target_portals = self.nef.get(url).get('portals')
                common_portals = set(target_portals) & set(config_portals)
                props_portals += common_portals
                props_iqns += [target_iqn] * len(common_portals)
                props_luns += [mapping['lun']] * len(common_portals)

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
            LOG.debug('Return existing LUN mapping(s) %s', props)
            return {'driver_volume_type': 'iscsi', 'data': props}

        if host_group_name is None:
            host_group_name = '%s-%s' % \
                (self.host_group_prefix, uuid.uuid4().hex)
            self._create_host_group(host_group_name, host_iqn)

        mappings_spread = {}
        members_spread = {}
        url = 'san/targetgroups'
        target_groups = self.nef.get(url).get('data')
        for target_group in target_groups:
            if not target_group['name'].startswith(self.target_group_prefix):
                LOG.debug('Skip target group %s', target_group['name'])
                continue
            if len(target_group['members']) == 0:
                LOG.debug('Found target group %s with no targets',
                          target_group['name'])
                mappings_spread[target_group['name']] = None
                members_spread[target_group['name']] = []
                continue
            params = {'targetGroup': target_group['name']}
            url = 'san/lunMappings?%s' % urllib.parse.urlencode(params)
            mappings = self.nef.get(url).get('data')
            if not len(mappings) < self.luns_per_target:
                LOG.debug('Skip target group %s, members limit reached: %s',
                          target_group['name'], len(mappings))
                continue
            LOG.debug('Found target group %s with %s members',
                      target_group['name'], len(mappings))
            mappings_spread[target_group['name']] = len(mappings)
            members_spread[target_group['name']] = target_group['members']

        if len(mappings_spread) == 0:
            target_name = '%s-%s' % (self.target_prefix, uuid.uuid4().hex)
            target_group_name = self._get_target_group_name(target_name)
            LOG.debug('Create new target group %s with member %s',
                      target_group_name, target_name)
            self._create_target(target_name, self._s2d(config_portals))
            self._create_target_group(target_group_name, [target_name])
            props_portals += config_portals
            props_iqns += [target_name] * len(config_portals)
        elif min(mappings_spread.values()) is None:
            target_group_name = min(mappings_spread, key=mappings_spread.get)
            target_name = self._get_target_name(target_group_name)
            LOG.debug('Update existing target group %s with new member %s',
                      target_group_name, target_name)
            self._create_target(target_name, config_portals)
            self._update_target_group(target_group_name, [target_name])
            props_portals += config_portals
            props_iqns += [target_name] * len(config_portals)
        else:
            target_group_name = min(mappings_spread, key=mappings_spread.get)
            target_group_members = members_spread[target_group_name]
            LOG.debug('Use existing target group %s with members %s',
                      target_group_name, target_group_members)
            url = 'san/iscsi/targets'
            targets = self.nef.get(url).get('data')
            for target in targets:
                if target['name'] in target_group_members:
                    props_portals += self._d2s(target['portals'])
                    props_iqns += [target['name']] * len(target['portals'])

        url = 'san/lunMappings'
        data = {
            'volume': volume_path,
            'targetGroup': target_group_name,
            'hostGroup': host_group_name
        }
        LOG.debug('Create LUN mapping for %s', data)
        self.nef.post(url, data)

        LOG.debug('Get LUN number of LUN mapping for %s', data)
        params = {
            'fields': 'lun',
            'volume': volume_path,
            'targetGroup': target_group_name,
            'hostGroup': host_group_name
        }
        url = 'san/lunMappings?%s' % urllib.parse.urlencode(params)
        data = self._poll_result(url)
        props_luns = [data[0]['lun']] * len(props_iqns)

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
            LOG.debug('Get LUN guid for volume %s', volume_path)
            params = {'fields': 'guid', 'volume': volume_path}
            url = 'san/logicalUnits?%s' % urllib.parse.urlencode(params)
            guid = self.nef.get(url)['data'][0]['guid']
            LOG.debug('Enable Write Back Cache for LUN %s', guid)
            url = 'san/logicalUnits/%s' % urllib.parse.quote_plus(guid)
            data = {'writebackCacheDisabled': False}
            self.nef.put(url, data)

        LOG.debug('Created new LUN mapping(s) %s', props)
        return {'driver_volume_type': 'iscsi', 'data': props}

    def _create_target_group(self, name, members):
        """Create a new target group with members.

        :param name: group name
        :param members: group members dict
        """
        url = 'san/targetgroups'
        data = {
            'name': name,
            'members': members
        }
        self.nef.post(url, data)

    def _update_target_group(self, name, members):
        """Update a existing target group with new members.

        :param name: group name
        :param members: group members dict
        """
        url = 'san/targetgroups/%s' % urllib.parse.quote_plus(name)
        data = {
            'members': members
        }
        self.nef.put(url, data)

    def _create_target(self, name, portals):
        """Create a new target with portals.

        :param name: target name
        :param portals: target portals dict
        """
        url = 'san/iscsi/targets'
        data = {
            'name': name,
            'portals': portals
        }
        self.nef.post(url, data)

    def _get_host_group(self, member):
        """Find existing host group by group member.

        :param member: host group member
        :return: host group name
        """
        url = 'san/hostgroups'
        host_groups = self.nef.get(url).get('data')
        for host_group in host_groups:
            if member in host_group['members']:
                return host_group['name']
        return None

    def _create_host_group(self, name, member):
        """Create a new host group.

        :param name: host group name
        :param member: host group member
        """
        url = 'san/hostgroups'
        data = {
            'name': name,
            'members': [member]
        }
        self.nef.post(url, data)

    def _poll_result(self, url):
        """Poll non-empty response data for NEF get method.

        :param url: NEF URL
        :return: response data list
        """
        for retry in range(0, options.POLL_RETRIES):
            data = self.nef.get(url).get('data')
            if data:
                return data
            greenthread.sleep(int(math.exp(retry)))
        return []

    def _s2d(self, css):
        """Parse list of colon-separated address and port to dictionary.

        :param css: list of colon-separated address and port
        :return: dictionary
        """
        result = []
        for key_val in css:
            key, val = key_val.split(':')
            result.append({'address': key, 'port': int(val)})
        return result

    def _d2s(self, kvp):
        """Parse dictionary to list of colon-separated address and port.

        :param kvp: dictionary
        :return: list of colon-separated address and port
        """
        result = []
        for key_val in kvp:
            result.append('%s:%s' % (key_val['address'], key_val['port']))
        return result

    def _get_snapshot_volume(self, snapshot):
        ctxt = context.get_admin_context()
        return db.volume_get(ctxt, snapshot['volume_id'])
