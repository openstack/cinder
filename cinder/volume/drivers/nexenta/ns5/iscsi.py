# Copyright 2016 Nexenta Systems, Inc.
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

import uuid

from oslo_log import log as logging
from oslo_utils import units

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils

VERSION = '1.1.0'
LOG = logging.getLogger(__name__)
TARGET_GROUP_PREFIX = 'cinder-tg-'


@interface.volumedriver
class NexentaISCSIDriver(driver.ISCSIDriver):
    """Executes volume driver commands on Nexenta Appliance.

    .. code-block:: default

      Version history:
          1.0.0 - Initial driver version.
          1.1.0 - Added HTTPS support.
                  Added use of sessions for REST calls.

    """

    VERSION = VERSION

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Nexenta_CI"

    def __init__(self, *args, **kwargs):
        super(NexentaISCSIDriver, self).__init__(*args, **kwargs)
        self.nef = None
        # mapping of targets and groups. Groups are the keys
        self.targets = {}
        # list of volumes in target group. Groups are the keys
        self.volumes = {}
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_ISCSI_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_DATASET_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_RRMGR_OPTS)
        self.use_https = self.configuration.nexenta_use_https
        self.nef_host = self.configuration.nexenta_host
        self.nef_port = self.configuration.nexenta_rest_port
        self.nef_user = self.configuration.nexenta_user
        self.nef_password = self.configuration.nexenta_password
        self.storage_pool = self.configuration.nexenta_volume
        self.volume_group = self.configuration.nexenta_volume_group
        self.dataset_compression = (
            self.configuration.nexenta_dataset_compression)
        self.dataset_deduplication = self.configuration.nexenta_dataset_dedup
        self.dataset_description = (
            self.configuration.nexenta_dataset_description)
        self.iscsi_target_portal_port = (
            self.configuration.nexenta_iscsi_target_portal_port)

    @staticmethod
    def get_driver_options():
        return (
            options.NEXENTA_CONNECTION_OPTS +
            options.NEXENTA_ISCSI_OPTS +
            options.NEXENTA_DATASET_OPTS +
            options.NEXENTA_RRMGR_OPTS
        )

    @property
    def backend_name(self):
        backend_name = None
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = self.__class__.__name__
        return backend_name

    def do_setup(self, context):
        self.nef = jsonrpc.NexentaJSONProxy(
            self.nef_host, self.nef_port, self.nef_user,
            self.nef_password, self.use_https)
        url = 'storage/pools/%s/volumeGroups' % self.storage_pool
        data = {
            'name': self.volume_group,
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

        self._fetch_volumes()

    def _fetch_volumes(self):
        url = 'san/iscsi/targets?fields=alias,name&limit=50000'
        for target in self.nef.get(url)['data']:
            tg_name = target['alias']
            if tg_name.startswith(TARGET_GROUP_PREFIX):
                self.targets[tg_name] = target['name']
                self._fill_volumes(tg_name)

    def check_for_setup_error(self):
        """Verify that the zfs volumes exist.

        :raise: :py:exc:`LookupError`
        """
        url = 'storage/pools/%(pool)s/volumeGroups/%(group)s' % {
            'pool': self.storage_pool,
            'group': self.volume_group,
        }
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

    def _get_volume_path(self, volume):
        """Return zfs volume name that corresponds given volume name."""
        return '%s/%s/%s' % (self.storage_pool, self.volume_group,
                             volume['name'])

    @staticmethod
    def _get_clone_snapshot_name(volume):
        """Return name for snapshot that will be used to clone the volume."""
        return 'cinder-clone-snapshot-%(id)s' % volume

    def create_volume(self, volume):
        """Create a zfs volume on appliance.

        :param volume: volume reference
        :return: model update dict for volume reference
        """
        url = 'storage/pools/%(pool)s/volumeGroups/%(group)s/volumes' % {
            'pool': self.storage_pool,
            'group': self.volume_group,
        }
        data = {
            'name': volume['name'],
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

        url = ('storage/pools/%(pool)s/volumeGroups/%(group)s'
               '/volumes/%(name)s') % {
            'pool': self.storage_pool,
            'group': self.volume_group,
            'name': volume['name']
        }
        try:
            self.nef.delete(url)
        except exception.NexentaException as exc:
            # We assume that volume is gone
            LOG.warning('Got error trying to delete volume %(volume)s,'
                        ' assuming it is already gone: %(exc)s',
                        {'volume': volume, 'exc': exc})

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        LOG.info('Extending volume: %(id)s New size: %(size)s GB',
                 {'id': volume['id'], 'size': new_size})
        pool, group, name = self._get_volume_path(volume).split('/')
        url = ('storage/pools/%(pool)s/volumeGroups/%(group)s/'
               'volumes/%(name)s') % {
            'pool': pool,
            'group': group,
            'name': name
        }
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
        pool, group, volume = volume_path.split('/')
        url = ('storage/pools/%(pool)s/volumeGroups/%(group)s/'
               'volumes/%(volume)s/snapshots') % {
            'pool': pool,
            'group': group,
            'volume': snapshot_vol['name']
        }
        self.nef.post(url, {'name': snapshot['name']})

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot on appliance.

        :param snapshot: snapshot reference
        """
        LOG.info('Deleting snapshot: %s', snapshot['name'])
        snapshot_vol = self._get_snapshot_volume(snapshot)
        volume_path = self._get_volume_path(snapshot_vol)
        pool, group, volume = volume_path.split('/')
        url = ('storage/pools/%(pool)s/volumeGroups/%(group)s/'
               'volumes/%(volume)s/snapshots/%(snapshot)s') % {
            'pool': pool,
            'group': group,
            'volume': volume,
            'snapshot': snapshot['name']
        }
        try:
            self.nef.delete(url)
        except exception.NexentaException as exc:
            if 'EBUSY' in exc.args[0]:
                LOG.warning(
                    'Could not delete snapshot %s - it has dependencies',
                    snapshot['name'])
            else:
                LOG.warning(exc)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        LOG.info('Creating volume from snapshot: %s', snapshot['name'])
        snapshot_vol = self._get_snapshot_volume(snapshot)
        volume_path = self._get_volume_path(snapshot_vol)
        pool, group, snapshot_vol = volume_path.split('/')
        url = ('storage/pools/%(pool)s/volumeGroups/%(group)s/'
               'volumes/%(volume)s/snapshots/%(snapshot)s/clone') % {
            'pool': pool,
            'group': group,
            'volume': snapshot_vol,
            'snapshot': snapshot['name']
        }
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
            LOG.error('Volume creation failed, deleting created snapshot %s',
                      '@'.join([snapshot['volume_name'], snapshot['name']]))
            try:
                self.delete_snapshot(snapshot)
            except (exception.NexentaException, exception.SnapshotIsBusy):
                LOG.warning('Failed to delete zfs snapshot %s',
                            '@'.join([snapshot['volume_name'],
                                      snapshot['name']]))
            raise

    def _get_snapshot_volume(self, snapshot):
        ctxt = context.get_admin_context()
        return db.volume_get(ctxt, snapshot['volume_id'])

    def _do_export(self, _ctx, volume):
        """Do all steps to get zfs volume exported at separate target.

        :param volume: reference of volume to be exported
        """
        volume_path = self._get_volume_path(volume)

        # Find out whether the volume is exported
        vol_map_url = 'san/lunMappings?volume=%s&fields=lun' % (
            volume_path.replace('/', '%2F'))
        data = self.nef.get(vol_map_url).get('data')
        if data:
            model_update = {}
        else:
            # Choose the best target group among existing ones
            tg_name = None
            for tg in self.volumes:
                if len(self.volumes[tg]) < 20:
                    tg_name = tg
                    break
            if tg_name:
                target_name = self.targets[tg_name]
            else:
                tg_name = TARGET_GROUP_PREFIX + uuid.uuid4().hex

                # Create new target
                url = 'san/iscsi/targets'
                data = {
                    "portals": [
                        {"address": self.nef_host}
                    ],
                    'alias': tg_name
                }
                self.nef.post(url, data)

                # Get the name of just created target
                data = self.nef.get(
                    '%(url)s?fields=name&alias=%(tg_name)s' % {
                        'url': url,
                        'tg_name': tg_name
                    })['data']
                target_name = data[0]['name']

                self._create_target_group(tg_name, target_name)

                self.targets[tg_name] = target_name
                self.volumes[tg_name] = set()

            # Export the volume
            url = 'san/lunMappings'
            data = {
                "hostGroup": "all",
                "targetGroup": tg_name,
                'volume': volume_path
            }
            try:
                self.nef.post(url, data)
                self.volumes[tg_name].add(volume_path)
            except exception.NexentaException as e:
                if 'No such target group' in e.args[0]:
                    self._create_target_group(tg_name, target_name)
                    self._fill_volumes(tg_name)
                    self.nef.post(url, data)
                else:
                    raise

            # Get LUN of just created volume
            data = self.nef.get(vol_map_url).get('data')
            lun = data[0]['lun']

            provider_location = '%(host)s:%(port)s,1 %(name)s %(lun)s' % {
                'host': self.nef_host,
                'port': self.configuration.nexenta_iscsi_target_portal_port,
                'name': target_name,
                'lun': lun,
            }
            model_update = {'provider_location': provider_location}
        return model_update

    def create_export(self, _ctx, volume, connector):
        """Create new export for zfs volume.

        :param volume: reference of volume to be exported
        :return: iscsiadm-formatted provider location string
        """
        model_update = self._do_export(_ctx, volume)
        return model_update

    def ensure_export(self, _ctx, volume):
        """Recreate parts of export if necessary.

        :param volume: reference of volume to be exported
        """
        self._do_export(_ctx, volume)

    def remove_export(self, _ctx, volume):
        """Destroy all resources created to export zfs volume.

        :param volume: reference of volume to be unexported
        """
        volume_path = self._get_volume_path(volume)

        # Get ID of a LUN mapping if the volume is exported
        url = 'san/lunMappings?volume=%s&fields=id' % (
            volume_path.replace('/', '%2F'))
        data = self.nef.get(url)['data']
        if data:
            url = 'san/lunMappings/%s' % data[0]['id']
            self.nef.delete(url)
        else:
            LOG.debug('LU already deleted from appliance')

        for tg in self.volumes:
            if volume_path in self.volumes[tg]:
                self.volumes[tg].remove(volume_path)
                break

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

        url = ('storage/pools/%(pool)s/volumeGroups/%(group)s'
               '?fields=bytesAvailable,bytesUsed') % {
            'pool': self.storage_pool,
            'group': self.volume_group,
        }
        stats = self.nef.get(url)
        total_amount = utils.str2gib_size(stats['bytesAvailable'])
        free_amount = utils.str2gib_size(
            stats['bytesAvailable'] - stats['bytesUsed'])

        location_info = '%(driver)s:%(host)s:%(pool)s/%(group)s' % {
            'driver': self.__class__.__name__,
            'host': self.nef_host,
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
            'total_capacity_gb': total_amount,
            'free_capacity_gb': free_amount,
            'reserved_percentage': self.configuration.reserved_percentage,
            'QoS_support': False,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': self.iscsi_target_portal_port,
            'nef_url': self.nef.url
        }

    def _fill_volumes(self, tg_name):
        url = ('san/lunMappings?targetGroup=%s&fields=volume'
               '&limit=50000' % tg_name)
        self.volumes[tg_name] = {
            mapping['volume'] for mapping in self.nef.get(url)['data']}

    def _create_target_group(self, tg_name, target_name):
        # Create new target group
        url = 'san/targetgroups'
        data = {
            'name': tg_name,
            'members': [target_name]
        }
        self.nef.post(url, data)
