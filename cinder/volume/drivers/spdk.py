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

import json

from os_brick import initiator
from os_brick.initiator import connector
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import units
import requests

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import utils
from cinder.volume import driver
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class SPDKDriver(driver.VolumeDriver):
    """Executes commands relating to Volumes."""

    VERSION = '1.0.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Mellanox_CI"

    def __init__(self, *args, **kwargs):
        # Parent sets db, host, _execute and base config
        super(SPDKDriver, self).__init__(*args, **kwargs)

        self.lvs = []
        self.ctxt = context.get_admin_context()

        target_driver = (
            self.target_mapping[self.configuration.safe_get('target_helper')])

        LOG.debug('SPDK attempting to initialize LVM driver with the '
                  'following target_driver: %s',
                  target_driver)

        self.target_driver = importutils.import_object(
            target_driver,
            configuration=self.configuration,
            executor=self._execute)

    @staticmethod
    def get_driver_options():
        return []

    def _rpc_call(self, method, params=None):
        payload = {}
        payload['jsonrpc'] = '2.0'
        payload['id'] = 1
        payload['method'] = method
        if params is not None:
            payload['params'] = params

        req = requests.post(self.url,
                            data=json.dumps(payload),
                            auth=(self.configuration.spdk_rpc_username,
                                  self.configuration.spdk_rpc_password),
                            verify=self.configuration.driver_ssl_cert_verify,
                            timeout=30)

        if not req.ok:
            raise exception.VolumeBackendAPIException(
                data=_('SPDK target responded with error: %s') % req.text)

        return req.json()['result']

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug('SPDK Updating volume stats')
        status = {'volume_backend_name': 'SPDK',
                  'vendor_name': 'Open Source',
                  'driver_version': self.VERSION,
                  'storage_protocol': 'NVMe-oF'}
        pools_status = []
        self.lvs = []

        output = self._rpc_call('bdev_lvol_get_lvstores')
        if output:
            for lvs in output:
                pool = {}
                lvs_entry = {}
                free_size = (lvs['free_clusters']
                             * lvs['cluster_size']
                             / units.Gi)
                total_size = (lvs['total_data_clusters']
                              * lvs['cluster_size']
                              / units.Gi)
                pool["volume_backend_name"] = 'SPDK'
                pool["vendor_name"] = 'Open Source'
                pool["driver_version"] = self.VERSION
                pool["storage_protocol"] = 'NVMe-oF'
                pool["total_capacity_gb"] = total_size
                pool["free_capacity_gb"] = free_size
                pool["pool_name"] = lvs['name']
                pools_status.append(pool)

                lvs_entry['name'] = lvs['name']
                lvs_entry['uuid'] = lvs['uuid']
                lvs_entry['free_size'] = free_size
                lvs_entry['total_size'] = total_size
                self.lvs.append(lvs_entry)

        status['pools'] = pools_status
        self._stats = status

        for lvs in self.lvs:
            LOG.debug('SPDK lvs name: %s, total space: %s, free space: %s',
                      lvs['name'],
                      lvs['total_size'],
                      lvs['free_size'])

    def _get_spdk_volume_name(self, name):
        output = self._rpc_call('bdev_get_bdevs')
        for bdev in output:
            for alias in bdev['aliases']:
                if name in alias:
                    return bdev['name']

    def _get_spdk_lvs_uuid(self, spdk_name):
        output = self._rpc_call('bdev_get_bdevs')
        for bdev in output:
            if spdk_name in bdev['name']:
                return bdev['driver_specific']['lvol']['lvol_store_uuid']

    def _get_spdk_lvs_free_space(self, lvs_uuid):
        self._update_volume_stats()

        for lvs in self.lvs:
            if lvs_uuid in lvs['uuid']:
                return lvs['free_size']

        return 0

    def _delete_bdev(self, name):
        spdk_name = self._get_spdk_volume_name(name)
        if spdk_name is not None:
            params = {'name': spdk_name}
            self._rpc_call('bdev_lvol_delete', params)
            LOG.debug('SPDK bdev %s deleted', spdk_name)
        else:
            LOG.debug('Could not find volume %s using SPDK driver', name)

    def _create_volume(self, volume, snapshot=None):
        output = self._rpc_call('bdev_lvol_get_lvstores')
        for lvs in output:
            free_size = (lvs['free_clusters'] * lvs['cluster_size'])
            if free_size / units.Gi >= volume.size:
                if snapshot is None:
                    params = {
                        'lvol_name': volume.name,
                        'size': volume.size * units.Gi,
                        'uuid': lvs['uuid']}
                    output2 = self._rpc_call('bdev_lvol_create', params)
                else:
                    snapshot_spdk_name = (
                        self._get_spdk_volume_name(snapshot.name))
                    params = {
                        'clone_name': volume.name,
                        'snapshot_name': snapshot_spdk_name}
                    output2 = self._rpc_call('bdev_lvol_clone', params)
                    spdk_name = self._get_spdk_volume_name(volume.name)
                    params = {'name': spdk_name}
                    self._rpc_call('bdev_lvol_inflate', params)

                    if volume.size > snapshot.volume_size:
                        params = {'name': spdk_name,
                                  'size': volume.size * units.Gi}
                        self._rpc_call('bdev_lvol_resize', params)

                LOG.debug('SPDK created lvol: %s', output2)

                return

        LOG.error('Unable to create volume using SPDK - no resources found')
        raise exception.VolumeBackendAPIException(
            data=_('Unable to create volume using SPDK'
                   ' - no resources found'))

    def do_setup(self, context):
        try:
            payload = {'method': 'bdev_get_bdevs', 'jsonrpc': '2.0', 'id': 1}
            self.url = ('%(protocol)s://%(ip)s:%(port)s/' %
                        {'protocol': self.configuration.spdk_rpc_protocol,
                         'ip': self.configuration.spdk_rpc_ip,
                         'port': self.configuration.spdk_rpc_port})
            requests.post(self.url,
                          data=json.dumps(payload),
                          auth=(self.configuration.spdk_rpc_username,
                                self.configuration.spdk_rpc_password),
                          verify=self.configuration.driver_ssl_cert_verify,
                          timeout=30)
        except Exception as err:
            err_msg = (
                _('Could not connect to SPDK target: %(err)s')
                % {'err': err})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def check_for_setup_error(self):
        """Verify that requirements are in place to use LVM driver."""

        # If configuration is incorrect we will get exception here
        self._rpc_call('bdev_get_bdevs')

    def create_volume(self, volume):
        """Creates a logical volume."""
        LOG.debug('SPDK create volume')

        return self._create_volume(volume)

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        LOG.debug('SPDK deleting volume %s', volume.name)

        self._delete_bdev(volume.name)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""

        free_size = self._get_spdk_lvs_free_space(
            self._get_spdk_lvs_uuid(
                self._get_spdk_volume_name(snapshot.name)))

        if free_size < volume.size:
            raise exception.VolumeBackendAPIException(
                data=_('Not enough space to create snapshot with SPDK'))

        return self._create_volume(volume, snapshot)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        volume = snapshot['volume']
        spdk_name = self._get_spdk_volume_name(volume.name)

        if spdk_name is None:
            raise exception.VolumeBackendAPIException(
                data=_('Could not create snapshot with SPDK driver'))

        free_size = self._get_spdk_lvs_free_space(
            self._get_spdk_lvs_uuid(spdk_name))

        if free_size < volume.size:
            raise exception.VolumeBackendAPIException(
                data=_('Not enough space to create snapshot with SPDK'))

        params = {
            'lvol_name': spdk_name,
            'snapshot_name': snapshot['name']}
        self._rpc_call('bdev_lvol_snapshot', params)

        params = {'name': spdk_name}
        self._rpc_call('bdev_lvol_inflate', params)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        spdk_name = self._get_spdk_volume_name(snapshot.name)
        if spdk_name is None:
            return

        params = {'name': spdk_name}
        bdev = self._rpc_call('bdev_get_bdevs', params)
        if 'clones' in bdev[0]['driver_specific']['lvol']:
            for clone in bdev[0]['driver_specific']['lvol']['clones']:
                spdk_name = self._get_spdk_volume_name(clone)
                params = {'name': spdk_name}
                self._rpc_call('bdev_lvol_inflate', params)

        self._delete_bdev(snapshot.name)

    def create_cloned_volume(self, volume, src_volume):
        spdk_name = self._get_spdk_volume_name(src_volume.name)

        free_size = self._get_spdk_lvs_free_space(
            self._get_spdk_lvs_uuid(spdk_name))

        # We need additional space for snapshot that will be used here
        if free_size < 2 * src_volume.size + volume.size:
            raise exception.VolumeBackendAPIException(
                data=_('Not enough space to clone volume with SPDK'))

        snapshot_name = 'snp-' + src_volume.name

        params = {
            'lvol_name': spdk_name,
            'snapshot_name': snapshot_name}
        self._rpc_call('bdev_lvol_snapshot', params)

        params = {'name': spdk_name}
        self._rpc_call('bdev_lvol_inflate', params)

        snapshot_spdk_name = self._get_spdk_volume_name(snapshot_name)
        params = {
            'clone_name': volume.name,
            'snapshot_name': snapshot_spdk_name}

        self._rpc_call('bdev_lvol_clone', params)

        spdk_name = self._get_spdk_volume_name(volume.name)
        params = {'name': spdk_name}
        self._rpc_call('bdev_lvol_inflate', params)

        self._delete_bdev(snapshot_name)

        if volume.size > src_volume.size:
            self.extend_volume(volume, volume.size)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""

        volume['provider_location'] = (
            self.create_export(context, volume, None)['provider_location'])
        connection_data = self.initialize_connection(volume, None)['data']
        target_connector = (
            connector.InitiatorConnector.factory(initiator.NVME,
                                                 utils.get_root_helper()))

        try:
            device_info = target_connector.connect_volume(connection_data)
        except Exception:
            LOG.info('Could not connect SPDK target device')
            return

        connection_data['device_path'] = device_info['path']

        try:
            image_utils.fetch_to_raw(context,
                                     image_service,
                                     image_id,
                                     device_info['path'],
                                     self.configuration.volume_dd_blocksize,
                                     size=volume['size'])

        finally:
            target_connector.disconnect_volume(connection_data, volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        volume['provider_location'] = (
            self.create_export(context, volume, None)['provider_location'])
        connection_data = self.initialize_connection(volume, None)['data']
        target_connector = (
            connector.InitiatorConnector.factory(initiator.NVME,
                                                 utils.get_root_helper()))

        try:
            device_info = target_connector.connect_volume(connection_data)
        except Exception:
            LOG.info('Could not connect SPDK target device')
            return

        connection_data['device_path'] = device_info['path']

        try:
            volume_utils.upload_volume(context,
                                       image_service,
                                       image_meta,
                                       device_info['path'],
                                       volume)
        finally:
            target_connector.disconnect_volume(connection_data, volume)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume's size."""
        spdk_name = self._get_spdk_volume_name(volume.name)
        params = {'name': spdk_name, 'size': new_size * units.Gi}
        self._rpc_call('bdev_lvol_resize', params)

    # #######  Interface methods for DataPath (Target Driver) ########
    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector, vg=None):
        export_info = self.target_driver.create_export(
            context,
            volume,
            None)
        return {'provider_location': export_info['location'],
                'provider_auth': export_info['auth'], }

    def remove_export(self, context, volume):
        self.target_driver.remove_export(context, volume)

    def initialize_connection(self, volume, connector):
        return self.target_driver.initialize_connection(volume, connector)

    def validate_connector(self, connector):
        return self.target_driver.validate_connector(connector)

    def terminate_connection(self, volume, connector, **kwargs):
        pass
