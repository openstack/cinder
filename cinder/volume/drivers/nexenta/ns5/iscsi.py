# Copyright 2011 Nexenta Systems, Inc.
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
"""
:mod:`nexenta.iscsi` -- Driver to store volumes on Nexenta Appliance
=====================================================================

.. automodule:: nexenta.volume
.. moduleauthor:: Alexey Khodos <alexey.khodos@nexenta.com>
"""

from oslo_log import log as logging
from oslo_utils import units

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _, _LI, _LE, _LW
from cinder.volume import driver
from cinder.volume.drivers import nexenta
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
        self.current_num = None
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTIONS)
            self.configuration.append_config_values(
                options.NEXENTA_ISCSI_OPTIONS)
            self.configuration.append_config_values(
                options.NEXENTA_VOLUME_OPTIONS)
            self.configuration.append_config_values(
                options.NEXENTA_RRMGR_OPTIONS)
        self.nef_protocol = self.configuration.nexenta_rest_protocol
        self.nef_host = self.configuration.nexenta_host
        self.nef_port = self.configuration.nexenta_rest_port
        self.nef_user = self.configuration.nexenta_user
        self.nef_password = self.configuration.nexenta_password
        self.volume = self.configuration.nexenta_volume
        self.volume_compression = self.configuration.nexenta_volume_compression
        self.volume_deduplication = self.configuration.nexenta_volume_dedup
        self.volume_description = self.configuration.nexenta_volume_description
        self.rrmgr_compression = self.configuration.nexenta_rrmgr_compression
        self.rrmgr_tcp_buf_size = self.configuration.nexenta_rrmgr_tcp_buf_size
        self.rrmgr_connections = self.configuration.nexenta_rrmgr_connections
        self.iscsi_target_portal_port = \
            self.configuration.nexenta_iscsi_target_portal_port

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
        pool, dataset = self.volume.split('/')
        url = 'storage/pools/%s/datasetGroups' % pool
        data = {
            'name': dataset,
            'defaultVolumeBlockSize': (
                self.configuration.nexenta_ns5_blocksize * units.Ki)
        }
        try:
            self.nef(url, data)
        except nexenta.NexentaException as exc:
            if 'exists' in exc.args[0]:
                LOG.info(_LI('Dataset Group alredy exists on appliance'))
            else:
                raise
        url = 'services/iscsit'
        data = {'enabled': True}
        self.nef(url, data, method='PUT')

        target_name = self._get_target_name()
        target_group_name = self.get_valid_target_group()
        if not self._target_group_exists(target_group_name):
            url = 'san/targetgroups'
            data = {'name': target_group_name,
                    'targets': [target_name]}
            self.nef(url, data)

    def get_valid_target_group(self):
        """Check NexentaStor appliance for all existing LU mappings.
        Fill in zvol_dict with info for existing zvols
        If there is a target with less than 255 mappings,
        Return targetgroup containing this target, else create new targetgroup
        """
        tg_list = []
        url = 'san/targetgroups'
        for tg in self.nef(url).get('data'):
            if tg['name'].startswith('%s-' % self._get_target_group_name()):
                tg_list.append(tg['name'])
        if tg_list:
            tg = sorted(tg_list)[-1]
            base, num = tg.split('-')
            url = 'san/targetgroups/%s/luns' % tg
            if len(self.nef(url)) < 255:
                self.current_num = int(num)
                return tg
            else:
                self.current_num = int(num) + 1
                return '%s-%s' % (base, int(num) + 1)
        else:
            self.current_num = 1
            return '%s-%s' % (self._get_target_group_name(), 1)

    def check_for_setup_error(self):
        """Verify that the volume for our zvols exists.

        :raise: :py:exc:`LookupError`
        """
        pool, dataset = self.volume.split('/')
        url = 'storage/pools/%s/datasetGroups/%s' % (pool, dataset)
        try:
            self.nef(url)
        except jsonrpc.NexentaJSONException:
            raise LookupError(_("Volume %s does not exist in Nexenta SA"),
                              self.volume)
        services = self.nef('services')
        for service in services['data']:
            if service['id'] == 'iscsit':
                if service['status'] == 'disabled':
                    raise nexenta.NexentaException(
                        'iSCSI service is not running on NS appliance')
                break

    def _get_zvol_name(self, volume_name):
        """Return zvol name that corresponds given volume name."""
        return '%s/%s' % (self.volume, volume_name)

    def _get_target_name(self):
        """Return iSCSI target name to access volume."""
        url = 'san/iscsi/targets?alias=cinder-%s' % self.current_num
        data = self.nef(url)['data']
        if data:
            return self.nef(url)['data'][0]['name']
        else:
            url = 'san/iscsi/targets'
            data = {'alias': 'cinder-%s' % self.current_num}
            self.nef(url, data)
            return self.nef(url)['data'][0]['name']

    def _get_target_group_name(self):
        """Return Nexenta iSCSI target group name for volume."""
        return 'cinder'

    @staticmethod
    def _get_clone_snapshot_name(volume):
        """Return name for snapshot that will be used to clone the volume."""
        return 'cinder-clone-snapshot-%(id)s' % volume

    def create_volume(self, volume):
        """Create a zvol on appliance.

        :param volume: volume reference
        :return: model update dict for volume reference
        """
        pool, dataset = self.volume.split('/')
        url = 'storage/pools/%s/datasetGroups/%s/volumes' % (
            pool, dataset)
        data = {
            'name': volume['name'],
            'volumeSize': volume['size'] * units.Gi,
            'volumeBlockSize': (
                self.configuration.nexenta_ns5_blocksize * units.Ki),
            'sparseVolume': self.configuration.nexenta_sparse
        }
        self.nef(url, data)

        # zvol_name = self._get_zvol_name(volume['name'])
        # target_group_name = self._get_target_group_name(volume['name'])

        # if not self._lu_exists(volume['name']):
        #     url = 'san/targetgroups/%s/luns' % target_group_name
        #     data = {'volume': zvol_name}
        #     self.nef(url, data)
        url = 'san/targetgroups/%s-%s/luns' % (
            self._get_target_group_name(), self.current_num)
        data = {'volume': '%s/%s/%s' % (pool, dataset, volume['name'])}
        self.nef(url, data)
        return self.create_export(None, volume)

    def delete_volume(self, volume):
        """Destroy a zvol on appliance.

        :param volume: volume reference
        """
        volume_name = self._get_zvol_name(volume['name'])
        pool, group, name = volume_name.split('/')
        url = ('storage/pools/%(pool)s/datasetGroups/%(group)s'
               '/volumes/%(name)s?snapshots=true') % {
            'pool': pool,
            'group': group,
            'name': name
        }
        try:
            self.nef(url, method='DELETE')
        except nexenta.NexentaException as exc:
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
        pool, group, name = self._get_zvol_name(volume['name']).split('/')
        url = ('storage/pools/%(pool)s/datasetGroups/%(group)s/'
               'volumes/%(name)s') % {
            'pool': pool,
            'group': group,
            'name': name
        }
        self.nef(url, {'volumeSize': new_size * units.Gi}, method='PUT')

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        snapshot_vol = self._get_snapshot_volume(snapshot)
        LOG.info(_LI('Creating snapshot %(snap)s of volume %(vol)s') % {
            'snap': snapshot['name'],
            'vol': snapshot_vol['name']
        })
        zvol_name = self._get_zvol_name(snapshot_vol['name'])
        pool, group, volume = zvol_name.split('/')
        url = 'storage/pools/%(pool)s/datasetGroups/%(group)s/' \
              'volumes/%(volume)s/snapshots' % {
                  'pool': pool,
                  'group': group,
                  'volume': snapshot_vol['name']
              }
        self.nef(url, {'name': snapshot['name']})

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot on appliance.

        :param snapshot: snapshot reference
        """
        LOG.info(_LI('Deleting snapshot: %s') % snapshot['name'])
        snapshot_vol = self._get_snapshot_volume(snapshot)
        zvol_name = self._get_zvol_name(snapshot_vol['name'])
        pool, group, volume = zvol_name.split('/')
        url = ('storage/pools/%(pool)s/datasetGroups/%(group)s/'
               'volumes/%(volume)s/snapshots/%(snapshot)s') % {
            'pool': pool,
            'group': group,
            'volume': volume,
            'snapshot': snapshot['name']
        }
        try:
            self.nef(url, method='DELETE')
        except nexenta.NexentaException as exc:
            if 'EBUSY' is exc:
                LOG.warning(_LW(
                    'Could not delete snapshot %s - it has dependencies') %
                    snapshot['name'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        LOG.info(_LI('Creating volume from snapshot: %s') % snapshot['name'])
        snapshot_vol = self._get_snapshot_volume(snapshot)
        zvol_name = self._get_zvol_name(snapshot_vol['name'])
        pool, group, snapshot_vol = zvol_name.split('/')
        url = ('storage/pools/%(pool)s/datasetGroups/%(group)s/'
               'volumes/%(volume)s/snapshots/%(snapshot)s/clone') % {
            'pool': pool,
            'group': group,
            'volume': snapshot_vol,
            'snapshot': snapshot['name']
        }
        self.nef(url, {'name': volume['name']})

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        snapshot = {'volume_name': src_vref['name'],
                    'volume_id': src_vref['id'],
                    'name': self._get_clone_snapshot_name(volume)}
        LOG.debug('Creating temp snapshot of the original volume: '
                  '%(volume_name)s@%(name)s', snapshot)
        # We don't delete this snapshot, because this snapshot will be origin
        # of new volume. This snapshot will be automatically promoted by NEF
        # when user will delete origin volume. But when cloned volume deleted
        # we check its origin property and delete source snapshot if needed.
        self.create_snapshot(snapshot)
        try:
            self.create_volume_from_snapshot(volume, snapshot)
        except nexenta.NexentaException:
            LOG.error(_LE('Volume creation failed, deleting created snapshot '
                          '%(volume_name)s@%(name)s'), snapshot)
            try:
                self.delete_snapshot(snapshot)
            except (nexenta.NexentaException, exception.SnapshotIsBusy):
                LOG.warning(_LW('Failed to delete zfs snapshot '
                                '%(volume_name)s@%(name)s'), snapshot)
            raise

    def _get_snapshot_volume(self, snapshot):
        ctxt = context.get_admin_context()
        return db.volume_get(ctxt, snapshot['volume_id'])

    # def _target_exists(self, target):
    #     """Check if iSCSI target exist.

    #     :param target: target name
    #     :return: True if target exist, else False
    #     """
    #     url = 'san/iscsi/targets'
    #     resp = self.nef(url).get('data')
    #     if not resp:
    #         return False
    #     targets = []
    #     for target in resp:
    #         targets.append(target['name'])
    #     return target in targets

    def _target_group_exists(self, target_group):
        """Check if target group exist.

        :param target_group: target group
        :return: True if target group exist, else False
        """
        url = 'san/targetgroups?name=%s' % target_group
        if self.nef(url).get('data'):
            return True
        else:
            return False

    # def _lu_exists(self, volume_name):
    #     """Check if LU exists on appliance.

    #     :param zvol_name: Zvol name
    #     :raises: NexentaException if zvol not exists
    #     :return: True if LU exists, else False
    #     """
    #     try:
    #         self._get_lun(volume_name)
    #     except LookupError:
    #         return False
    #     return True

    def _get_lun(self, volume_name):
        """Get lu mapping number for Zvol.

        :param zvol_name: Zvol name
        :raises: LookupError if Zvol not exist or not mapped to LU
        :return: LUN
        """
        zvol_name = self._get_zvol_name(volume_name)
        target_group_name = '%s-%s' % (
            self._get_target_group_name(), self.current_num)
        url = 'san/targetgroups/%s/luns?volume=%s' % (
            target_group_name, zvol_name.replace('/', '%2F'))
        guid = self.nef(url)['data'][0]['guid']
        url = 'san/targetgroups/%s/luns/%s/views' % (
            target_group_name, guid)
        return self.nef(url)['data'][0]['lunNumber']

    def _get_provider_location(self, volume):
        """Returns volume iscsiadm-formatted provider location string."""
        if not volume['provider_location']:
            volume['provider_location'] = (
                '%(host)s:%(port)s,1 %(name)s %(lun)s') % {
                'host': self.nef_host,
                'port': self.configuration.nexenta_iscsi_target_portal_port,
                'name': self._get_target_name(),
                'lun': self._get_lun(volume['name'])
            }
            return volume['provider_location']
        else:
            LOG.warning(volume['provider_location'])
            volume['provider_location']

    def create_export(self, _ctx, volume):
        """Create new export for zvol.

        :param volume: reference of volume to be exported
        :return: iscsiadm-formatted provider location string
        """
        return {'provider_location': self._get_provider_location(volume)}

    # def ensure_export(self, _ctx, volume):
    #     """Recreate parts of export if necessary.

    #     :param volume: reference of volume to be exported
    #     """
    #     self._do_export(_ctx, volume, ensure=True)

    def remove_export(self, _ctx, volume):
        """Driver entry point to remove an export for a volume.

        Since exporting is idempotent in this driver, we have nothing
        to do for unexporting.
        """
        pass

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

        pool, dataset = self.volume.split('/')
        url = 'storage/pools/%s/datasetGroups/%s' % (
            pool, dataset)
        stats = self.nef(url)
        total_amount = utils.str2gib_size(
            stats['bytesAvailable'] + stats['bytesUsed'])
        free_amount = utils.str2gib_size(stats['bytesAvailable'])

        location_info = '%(driver)s:%(host)s:%(volume)s' % {
            'driver': self.__class__.__name__,
            'host': self.nef_host,
            'volume': self.volume
        }
        reserve = 100 - self.configuration.nexenta_capacitycheck
        self._stats = {
            'vendor_name': 'Nexenta',
            'dedup': self.volume_deduplication,
            'compression': self.volume_compression,
            'description': self.volume_description,
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'total_capacity_gb': total_amount,
            'free_capacity_gb': free_amount,
            'reserved_percentage': reserve,
            'QoS_support': False,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': self.iscsi_target_portal_port,
            'nef_url': self.nef.url
        }
