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

VERSION = '1.3.0'
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
        self.use_https = self.configuration.nexenta_use_https
        self.nef_host = self.configuration.nexenta_rest_address
        self.iscsi_host = self.configuration.nexenta_host
        self.nef_port = self.configuration.nexenta_rest_port
        self.nef_user = self.configuration.nexenta_user
        self.host_group = self.configuration.nexenta_iscsi_target_host_group
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
        url = 'storage/volumes/%s' % path
        origin = self.nef.get(url).get('originalSnapshot')
        try:
            url = 'storage/volumes/%s?snapshots=true' % path
            self.nef.delete(url)
        except exception.NexentaException as exc:
            if 'Failed to destroy snap' in exc.kwargs['message']['message']:
                url = 'storage/snapshots?parent=%s' % path
                snap_map = {}
                for snap in self.nef.get(url)['data']:
                    url = 'storage/snapshots/%s' % (
                        snap['path'].replace('/', '%2F'))
                    data = self.nef.get(url)
                    if data['clones']:
                        snap_map[data['creationTxg']] = snap['path']
                snap = snap_map[max(snap_map)]
                url = 'storage/snapshots/%s' % snap.replace('/', '%2F')
                clone = self.nef.get(url)['clones'][0]
                url = 'storage/volumes/%s/promote' % clone.replace('/', '%2F')
                self.nef.post(url)
                url = 'storage/volumes/%s?snapshots=true' % path
                self.nef.delete(url)
            else:
                raise
        if origin and 'clone' in origin:
            url = 'storage/snapshots/%s' % origin.replace('/', '%2F')
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
        url = 'san/lunMappings?volume={}&fields=id'.format(
            volume_path.replace('/', '%2F')
        )
        data = self.nef.get(url)['data']
        if data:
            url = 'san/lunMappings/%s' % data[0]['id']
            try:
                self.nef.delete(url)
            except exception.NexentaException as e:
                if 'No such lun mapping' in e.args[0]:
                    LOG.debug('LU already deleted from appliance')
                else:
                    raise

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

    def _check_target_and_portals(self, tg):
        members = self.nef.get('san/targetgroups/%s' % urllib.parse.quote(
            tg, safe='')).get('members')
        target_name = members[0] if members else ''
        if target_name:
            target = self.nef.get('san/iscsi/targets/%s' % target_name)
            for portal in target['portals']:
                if portal['address'] == self.iscsi_host:
                    return target_name
        return ''

    def _do_export(self, _ctx, volume):
        """Do all steps to get zfs volume exported at separate target.

        :param volume: reference of volume to be exported
        """
        volume_path = self._get_volume_path(volume)
        lpt = self.configuration.nexenta_luns_per_target
        tg = ''
        target_name = ''
        map_dict = {}
        # Check whether the volume is exported
        url = 'san/lunMappings'
        data = self.nef.get(url).get('data')
        if data:
            for mapping in data:
                if mapping['volume'] == volume_path:
                    # Found the right mapping
                    tg = mapping['targetGroup']
                    tg_data = self.nef.get(
                        'san/targetgroups?name=%s' % urllib.parse.quote(
                            tg, safe=''))
                    target_name = tg_data['data'][0]['members'][0]
                    provider_location = (
                        '%(host)s:%(port)s,1 %(name)s %(lun)s') % {
                        'host': self.iscsi_host,
                        'port': self.portal_port,
                        'name': target_name,
                        'lun': mapping['lun'],
                    }
                    return {'provider_location': provider_location}
            # Find correct TG with lowest LUNs
            for m in data:
                map_dict.setdefault(m['targetGroup'], []).append(m)
            while not target_name and map_dict:
                tg = min({k: v for k, v in map_dict.items() if k.startswith(
                    self.configuration.nexenta_target_group_prefix)} or '')
                if tg and len(map_dict.get(tg)) <= lpt:
                    target_name = self._check_target_and_portals(tg)
                    del map_dict[tg]
                else:
                    map_dict = {}

        if not target_name:
            # Create new target and TG
            target_name = self.target_prefix + '-' + uuid.uuid4().hex
            url = 'san/iscsi/targets'
            portals = []
            if self.portals:
                for portal in self.portals.split(','):
                    address, port = portal.split(':')
                    port = int(port) if port else 3260
                    portals.append({
                        'address': address,
                        'port': port
                    })
            if not portals:
                portals = [{"address": self.iscsi_host}]
            data = {
                "portals": portals,
                'name': target_name
            }
            try:
                self.nef.post(url, data)
            except exception.NexentaException as e:
                if 'EEXIST' not in e.args[0]:
                    raise
            tg = self._get_target_group_name(target_name)
            self._create_target_group(tg, target_name)

        # Export the volume
        url = 'san/lunMappings'
        data = {
            "hostGroup": self.host_group,
            "targetGroup": tg,
            'volume': volume_path
        }
        try:
            self.nef.post(url, data)
        except exception.NexentaException as e:
            if 'No such target group' in e.args[0]:
                self._create_target_group(tg, target_name)
                self.nef.post(url, data)
            else:
                raise

        # Get LUN of just created volume
        vol_map_url = 'san/lunMappings?volume={}&fields=lun'.format(
            volume_path.replace('/', '%2F'))
        data = self.nef.get(vol_map_url).get('data')
        counter = 0
        while not data and counter < lpt:
            greenthread.sleep(1)
            counter += 1
            data = self.nef.get(vol_map_url).get('data')
        lun = data[0]['lun']

        provider_location = '%(host)s:%(port)s,1 %(name)s %(lun)s' % {
            'host': self.iscsi_host,
            'port': self.configuration.nexenta_iscsi_target_portal_port,
            'name': target_name,
            'lun': lun,
        }
        return {'provider_location': provider_location}

    def _create_target_group(self, tg_name, target_name):
        # Create new target group
        url = 'san/targetgroups'
        data = {
            'name': tg_name,
            'members': [target_name]
        }
        self.nef.post(url, data)

    def _get_snapshot_volume(self, snapshot):
        ctxt = context.get_admin_context()
        return db.volume_get(ctxt, snapshot['volume_id'])
