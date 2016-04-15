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

from oslo_log import log as logging
from oslo_utils import units

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _, _LI, _LE, _LW
from cinder.volume import driver
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils

VERSION = '1.0.0'
LOG = logging.getLogger(__name__)


class NexentaISCSIDriver(driver.ISCSIDriver):  # pylint: disable=R0921
    """Executes volume driver commands on Nexenta Appliance.

    Version history:
        1.0.0 - Initial driver version.
    """

    VERSION = VERSION

    def __init__(self, *args, **kwargs):
        super(NexentaISCSIDriver, self).__init__(*args, **kwargs)
        self.nef = None
        self.targets = {}
        self.targetgroups = {}
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_ISCSI_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_DATASET_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_RRMGR_OPTS)
        self.nef_protocol = self.configuration.nexenta_rest_protocol
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

    @property
    def backend_name(self):
        backend_name = None
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = self.__class__.__name__
        return backend_name

    def do_setup(self, context):
        if self.nef_protocol == 'auto':
            protocol, auto = 'http', True
        else:
            protocol, auto = self.nef_protocol, False
        self.nef = jsonrpc.NexentaJSONProxy(
            protocol, self.nef_host, self.nef_port, self.nef_user,
            self.nef_password, auto=auto)
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

    def _create_target(self, target_idx):
        target_alias = '%s-%i' % (
            self.nef_host,
            target_idx
        )

        target = self._get_target_by_alias(target_alias)
        if not target:
            url = 'san/iscsi/targets'
            data = {'alias': target_alias}
            self.nef.post(url, data)
            target = self._get_target_by_alias(target_alias)
        if not self._target_group_exists(target_alias):
            url = 'san/targetgroups'
            data = {'name': target_alias, 'targets': [target['name']]}
            self.nef.post(url, data)

        self.targetgroups[target['name']] = target_alias
        self.targets[target['name']] = []
        return target['name']

    def _get_target_name(self, volume):
        """Return iSCSI target name with least LUs."""
        provider_location = volume.get('provider_location')
        target_names = list(self.targets)
        if provider_location:
            target_name = provider_location.split(',1 ')[1].split(' ')[0]
            if not self.targets.get(target_name):
                self.targets[target_name] = []
            if not(volume['name'] in self.targets[target_name]):
                self.targets[target_name].append(volume['name'])
            if not self.targetgroups.get(target_name):
                url = 'san/iscsi/targets'
                data = self.nef.get(url).get('data')
                target_alias = data[0]['alias']
                self.targetgroups[target_name] = target_alias
        elif not target_names:
            # create first target and target group
            target_name = self._create_target(0)
            self.targets[target_name].append(volume['name'])
        else:
            target_name = target_names[0]
            for target in target_names:
                # find target with minimum number of volumes
                if len(self.targets[target]) < len(self.targets[target_name]):
                    target_name = target
            if len(self.targets[target_name]) >= 20:
                # create new target and target group
                target_name = self._create_target(len(target_names))
            if not(volume['name'] in self.targets[target_name]):
                self.targets[target_name].append(volume['name'])
        return target_name

    def _get_targetgroup_name(self, volume):
        target_name = self._get_target_name(volume)
        return self.targetgroups[target_name]

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
        pool, group, name = self._get_volume_path(volume).split('/')
        url = ('storage/pools/%(pool)s/volumeGroups/%(group)s'
               '/volumes/%(name)s') % {
            'pool': pool,
            'group': group,
            'name': name
        }
        try:
            self.nef.delete(url)
        except exception.NexentaException as exc:
            # We assume that volume is gone
            LOG.warning(_LW('Got error trying to delete volume %(volume)s,'
                            ' assuming it is already gone: %(exc)s'),
                        {'volume': volume, 'exc': exc})

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        LOG.info(_LI('Extending volume: %(id)s New size: %(size)s GB'),
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
        LOG.info(_LI('Creating snapshot %(snap)s of volume %(vol)s'), {
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
        LOG.info(_LI('Deleting snapshot: %s'), snapshot['name'])
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
                LOG.warning(_LW(
                    'Could not delete snapshot %s - it has dependencies'),
                    snapshot['name'])
            else:
                LOG.warning(exc)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        LOG.info(_LI('Creating volume from snapshot: %s'), snapshot['name'])
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
        targetPath = self._get_volume_path(volume)
        self.nef.post(url, {'targetPath': targetPath})
        url = ('storage/pools/%(pool)s/volumeGroups/'
               '%(group)s/volumes/%(name)s/promote') % {
            'pool': pool,
            'group': group,
            'name': volume['name'],
        }
        self.nef.post(url)

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
        # We don't delete this snapshot, because this snapshot will be origin
        # of new volume. This snapshot will be automatically promoted by NEF
        # when user will delete origin volume. But when cloned volume deleted
        # we check its origin property and delete source snapshot if needed.
        self.create_snapshot(snapshot)
        try:
            self.create_volume_from_snapshot(volume, snapshot)
        except exception.NexentaException:
            LOG.error(_LE('Volume creation failed, deleting created snapshot '
                          '%s'), '@'.join(
                [snapshot['volume_name'], snapshot['name']]))
            try:
                self.delete_snapshot(snapshot)
            except (exception.NexentaException, exception.SnapshotIsBusy):
                LOG.warning(_LW('Failed to delete zfs snapshot '
                                '%s'), '@'.join(
                    [snapshot['volume_name'], snapshot['name']]))
            raise

    def _get_snapshot_volume(self, snapshot):
        ctxt = context.get_admin_context()
        return db.volume_get(ctxt, snapshot['volume_id'])

    def _get_target_by_alias(self, alias):
        """Get an iSCSI target by it's alias.

        :param alias: target alias
        :return: First found target, else None
        """
        url = 'san/iscsi/targets?alias=%s' % alias
        targets = self.nef.get(url).get('data')
        if not targets:
            return None
        return targets[0]

    def _target_group_exists(self, target_group):
        """Check if target group exist.

        :param target_group: target group
        :return: True if target group exist, else False
        """
        url = 'san/targetgroups?name=%s' % target_group
        return bool(self.nef.get(url).get('data'))

    def _lu_exists(self, volume):
        """Check if LU exists on appliance.

        :param volume: cinder volume
        :return: True if LU exists, else False
        """
        try:
            self._get_lun_id(volume)
        except LookupError:
            return False
        return True

    def _get_lun_id(self, volume):
        """Get lun id for zfs volume.

        :param volume: cinder volume
        :raises: LookupError if zfs volume does not exist or not mapped to LU
        :return: LUN
        """
        volume_path = self._get_volume_path(volume)
        targetgroup_name = self._get_targetgroup_name(volume)
        url = 'san/targetgroups/%s/luns?volume=%s' % (
            targetgroup_name, volume_path.replace('/', '%2F'))
        data = self.nef.get(url).get('data')
        if not data:
            raise LookupError(_("LU does not exist for volume: %s"),
                              volume['name'])
        else:
            return data[0]['guid']

    def _get_lun(self, volume):
        try:
            lun_id = self._get_lun_id(volume)
        except LookupError:
            return None
        targetgroup_name = self._get_targetgroup_name(volume)
        url = 'san/targetgroups/%s/luns/%s/views' % (
            targetgroup_name, lun_id)
        data = self.nef.get(url).get('data')
        if not data:
            raise LookupError(_("No views found for LUN: %s"), lun_id)
        return data[0]['lunNumber']

    def _do_export(self, _ctx, volume):
        """Do all steps to get zfs volume exported at separate target.

        :param volume: reference of volume to be exported
        """
        volume_path = self._get_volume_path(volume)
        target_name = self._get_target_name(volume)
        targetgroup_name = self._get_targetgroup_name(volume)
        entry = {}

        if not self._lu_exists(volume):
            url = 'san/targetgroups/%s/luns' % targetgroup_name
            data = {'volume': volume_path}
            self.nef.post(url, data)
            entry['lun'] = self._get_lun(volume)

        model_update = {}
        if entry.get('lun') is not None:
            provider_location = '%(host)s:%(port)s,1 %(name)s %(lun)s' % {
                'host': self.nef_host,
                'port': self.configuration.nexenta_iscsi_target_portal_port,
                'name': target_name,
                'lun': entry['lun'],
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
        try:
            lun_id = self._get_lun_id(volume)
        except LookupError:
            return
        targetgroup_name = self._get_targetgroup_name(volume)
        url = 'san/targetgroups/%s/luns/%s' % (
            targetgroup_name, lun_id)
        try:
            self.nef.delete(url)
        except exception.NexentaException as exc:
            if 'No such logical unit in target group' in exc.args[0]:
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

        url = 'storage/pools/%(pool)s/volumeGroups/%(group)s' % {
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
