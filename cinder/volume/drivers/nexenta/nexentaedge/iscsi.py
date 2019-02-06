# Copyright 2015 Nexenta Systems, Inc.
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
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.nexenta.nexentaedge import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils as nexenta_utils


LOG = logging.getLogger(__name__)


@interface.volumedriver
class NexentaEdgeISCSIDriver(driver.ISCSIDriver):
    """Executes volume driver commands on NexentaEdge cluster.

    .. code-block:: none

      Version history:

        1.0.0 - Initial driver version.
        1.0.1 - Moved opts to options.py.
        1.0.2 - Added HA support.
        1.0.3 - Added encryption and replication count support.
        1.0.4 - Added initialize_connection.
        1.0.5 - Driver re-introduced in OpenStack.
    """

    VERSION = '1.0.5'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Nexenta_Edge_CI"

    # TODO(jsbryant) Remove driver in the 'T' release if CI is not fixed
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        super(NexentaEdgeISCSIDriver, self).__init__(*args, **kwargs)
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_ISCSI_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_DATASET_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_EDGE_OPTS)
        if self.configuration.nexenta_rest_address:
            self.restapi_host = self.configuration.nexenta_rest_address
        else:
            self.restapi_host = self.configuration.san_ip

        if self.configuration.nexenta_rest_port:
            self.restapi_port = self.configuration.nexenta_rest_port
        else:
            self.restapi_port = self.configuration.san_api_port

        if self.configuration.nexenta_client_address:
            self.target_vip = self.configuration.nexenta_client_address
        else:
            self.target_vip = self.configuration.target_ip_address
        if self.configuration.nexenta_rest_password:
            self.restapi_password = (
                self.configuration.nexenta_rest_password)
        else:
            self.restapi_password = (
                self.configuration.san_password)
        if self.configuration.nexenta_rest_user:
            self.restapi_user = self.configuration.nexenta_rest_user
        else:
            self.restapi_user = self.configuration.san_login
        self.verify_ssl = self.configuration.driver_ssl_cert_verify
        self.restapi_protocol = self.configuration.nexenta_rest_protocol
        self.iscsi_service = self.configuration.nexenta_iscsi_service
        self.bucket_path = self.configuration.nexenta_lun_container
        self.blocksize = self.configuration.nexenta_blocksize
        self.chunksize = self.configuration.nexenta_chunksize
        self.cluster, self.tenant, self.bucket = self.bucket_path.split('/')
        self.repcount = self.configuration.nexenta_replication_count
        self.encryption = self.configuration.nexenta_encryption
        self.iscsi_target_port = (self.configuration.
                                  nexenta_iscsi_target_portal_port)
        self.ha_vip = None

    @staticmethod
    def get_driver_options():
        return (
            options.NEXENTA_CONNECTION_OPTS +
            options.NEXENTA_ISCSI_OPTS +
            options.NEXENTA_DATASET_OPTS +
            options.NEXENTA_EDGE_OPTS
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
        if self.restapi_protocol == 'auto':
            protocol, auto = 'http', True
        else:
            protocol, auto = self.restapi_protocol, False

        try:
            self.restapi = jsonrpc.NexentaEdgeJSONProxy(
                protocol, self.restapi_host, self.restapi_port, '/',
                self.restapi_user, self.restapi_password,
                self.verify_ssl, auto=auto)

            data = self.restapi.get('service/' + self.iscsi_service)['data']
            self.target_name = '%s%s' % (
                data['X-ISCSI-TargetName'], data['X-ISCSI-TargetID'])
            if 'X-VIPS' in data:
                if self.target_vip not in data['X-VIPS']:
                    raise exception.NexentaException(
                        'Configured client IP address does not match any VIP'
                        ' provided by iSCSI service %s' % self.iscsi_service)
                else:
                    self.ha_vip = self.target_vip
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception('Error verifying iSCSI service %(serv)s on '
                              'host %(hst)s', {
                                  'serv': self.iscsi_service,
                                  'hst': self.restapi_host})

    def check_for_setup_error(self):
        url = 'clusters/%s/tenants/%s/buckets' % (self.cluster, self.tenant)
        if self.bucket not in self.restapi.get(url):
            raise exception.VolumeBackendAPIException(
                message=_('Bucket %s does not exist') % self.bucket)

    def _get_lu_number(self, volname):
        rsp = self.restapi.get('service/' + self.iscsi_service + '/iscsi')
        path = '%s/%s' % (self.bucket_path, volname)
        for mapping in rsp['data']:
            if mapping['objectPath'] == path:
                return mapping['number']
        return None

    def _get_provider_location(self, volume):
        lun = self._get_lu_number(volume['name'])
        if not lun:
            return None
        return '%(host)s:%(port)s,1 %(name)s %(number)s' % {
            'host': self.target_vip,
            'port': self.iscsi_target_port,
            'name': self.target_name,
            'number': lun
        }

    def create_volume(self, volume):
        data = {
            'objectPath': '%s/%s' % (
                self.bucket_path, volume['name']),
            'volSizeMB': int(volume['size']) * units.Ki,
            'blockSize': self.blocksize,
            'chunkSize': self.chunksize,
            'optionsObject': {
                'ccow-replication-count': self.repcount,
                'ccow-iops-rate-lim': self.configuration.nexenta_iops_limit}
        }
        if self.encryption:
            data['optionsObject']['ccow-encryption-enabled'] = True
        if self.ha_vip:
            data['vip'] = self.ha_vip
        try:
            self.restapi.post('service/' + self.iscsi_service + '/iscsi', data)
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(
                    'Error creating LUN for volume %s', volume['name'])
        return {'provider_location': self._get_provider_location(volume)}

    def delete_volume(self, volume):
        data = {
            'objectPath': '%s/%s' % (
                self.bucket_path, volume['name'])
        }
        try:
            self.restapi.delete(
                'service/' + self.iscsi_service + '/iscsi', data)
        except exception.VolumeBackendAPIException:
            LOG.info(
                'Error deleting LUN for volume %s', volume['name'])

    def create_export(self, context, volume, connector=None):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_discovered': False,
                'encrypted': False,
                'qos_specs': None,
                'target_iqn': self.target_name,
                'target_portal': '%s:%s' % (
                    self.target_vip, self.iscsi_target_port),
                'volume_id': volume['id'],
                'target_lun': self._get_lu_number(volume['name']),
                'access_mode': 'rw',
            }
        }

    def extend_volume(self, volume, new_size):
        try:
            self.restapi.put('service/' + self.iscsi_service + '/iscsi/resize',
                             {'objectPath': '%s/%s' % (
                                 self.bucket_path, volume['name']),
                              'newSizeMB': new_size * units.Ki})
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception('Error extending volume %s', volume['name'])

    def create_volume_from_snapshot(self, volume, snapshot):
        try:
            self.restapi.put(
                'service/' + self.iscsi_service + '/iscsi/snapshot/clone',
                {
                    'objectPath': '%s/%s' % (
                        self.bucket_path, snapshot['volume_name']),
                    'clonePath': '%s/%s' % (
                        self.bucket_path, volume['name']),
                    'snapName': snapshot['name']
                })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(
                    'Error creating volume from snapshot %s', snapshot['name'])
        if (('size' in volume) and (
                volume['size'] > snapshot['volume_size'])):
            self.extend_volume(volume, volume['size'])

    def create_snapshot(self, snapshot):
        try:
            self.restapi.post(
                'service/' + self.iscsi_service + '/iscsi/snapshot',
                {
                    'objectPath': '%s/%s' % (
                        self.bucket_path, snapshot['volume_name']),
                    'snapName': snapshot['name']
                })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception('Error creating snapshot %s', snapshot['name'])

    def delete_snapshot(self, snapshot):
        try:
            self.restapi.delete(
                'service/' + self.iscsi_service + '/iscsi/snapshot',
                {
                    'objectPath': '%s/%s' % (
                        self.bucket_path, snapshot['volume_name']),
                    'snapName': snapshot['name']
                })
        except exception.VolumeBackendAPIException:
            LOG.info('Error deleting snapshot %s', snapshot['name'])

    @staticmethod
    def _get_clone_snapshot_name(volume):
        """Return name for snapshot that will be used to clone the volume."""
        return 'cinder-clone-snapshot-%(id)s' % volume

    def create_cloned_volume(self, volume, src_vref):
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
        if volume['size'] > src_vref['size']:
            self.extend_volume(volume, volume['size'])

    def local_path(self, volume):
        raise NotImplementedError

    def get_volume_stats(self, refresh=False):
        resp = self.restapi.get('system/stats')
        summary = resp['stats']['summary']
        total = nexenta_utils.str2gib_size(summary['total_capacity'])
        free = nexenta_utils.str2gib_size(summary['total_available'])

        location_info = '%(driver)s:%(host)s:%(bucket)s' % {
            'driver': self.__class__.__name__,
            'host': self.target_vip,
            'bucket': self.bucket_path
        }
        return {
            'vendor_name': 'Nexenta',
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'reserved_percentage': 0,
            'total_capacity_gb': total,
            'free_capacity_gb': free,
            'QoS_support': False,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': self.iscsi_target_port,
            'restapi_url': self.restapi.url
        }
