import json
import socket

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _LE
from cinder.image import image_utils
from cinder.volume import driver
from cinder.volume import utils as volutils
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta.nexentaedge import jsonrpc


LOG = logging.getLogger(__name__)


class NexentaEdgeNBDTargetDriver(driver.VolumeDriver):
    """Executes commands relating to NBD Volumes."""

    VERSION = '1.0.0'

    def __init__(self, vg_obj=None, *args, **kwargs):
        super(NexentaEdgeNBDTargetDriver, self).__init__(*args, **kwargs)

        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_DATASET_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_EDGE_OPTS)
        self.restapi_protocol = self.configuration.nexenta_rest_protocol
        self.restapi_host = self.configuration.nexenta_rest_address
        self.restapi_port = self.configuration.nexenta_rest_port
        self.restapi_user = self.configuration.nexenta_rest_user
        self.restapi_password = self.configuration.nexenta_rest_password
        self.bucket_path = self.configuration.nexenta_lun_container
        self.blocksize = self.configuration.nexenta_blocksize
        self.chunksize = self.configuration.nexenta_chunksize
        self.cluster, self.tenant, self.bucket = self.bucket_path.split('/')
        self.bucket_url = ('clusters/' + self.cluster + '/tenants/' +
                           self.tenant + '/buckets/' + self.bucket)
        self.hostname = socket.gethostname()

        # Target Driver is what handles data-transport
        # Transport specific code should NOT be in
        # the driver (control path), this way
        # different target drivers can be added (iscsi, FC etc)
        target_driver = \
            self.target_mapping[self.configuration.safe_get('iscsi_helper')]

        LOG.debug('Attempting to initialize NBD driver with the '
                  'following target_driver: %s',
                  target_driver)

        self.target_driver = importutils.import_object(
            target_driver,
            configuration=self.configuration,
            db=self.db,
            executor=self._execute)

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

        self.restapi = jsonrpc.NexentaEdgeJSONProxy(
            protocol, self.restapi_host, self.restapi_port, '/',
            self.restapi_user, self.restapi_password, auto=auto)

    def check_for_setup_error(self):
        try:
            self.restapi.get(self.bucket_url + '/objects/')
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error verifying container %(bkt)s'),
                              {'bkt': self.bucket_path})

    def _get_nbd_devices(self, host):
        try:
            rsp = self.restapi.get('sysconfig/nbd/devices' +
                                   self._get_remote_url(host))
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error getting NBD list'))
        return json.loads(rsp['value'])

    def _get_nbd_number(self, volume):
        host = volutils.extract_host(volume['host'], 'host')
        nbds = self._get_nbd_devices(host)
        for dev in nbds:
            if dev['objectPath'] == self.bucket_path + '/' + volume['name']:
                return dev['number']
        return -1

    def _get_host_info(self, host):
        try:
            res = self.restapi.get('system/stats')
            servers = res['stats']['servers']
            for sid in servers:
                if host == sid or host == servers[sid]['hostname']:
                    return servers[sid]
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating volume'))
        raise Exception  # FIXME

    def _get_remote_url(self, host):
        return '?remote=' + str(self._get_host_info(host)['ipv6addr'])

    def local_path(self, volume):
        number = self._get_nbd_number(volume)
        if number == -1:
            raise Exception  # FIXME
        return '/dev/nbd' + str(number)

    def create_volume(self, volume):
        host = volutils.extract_host(volume['host'], 'host')
        try:
            self.restapi.post('nbd' + self._get_remote_url(host), {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'volSizeMB': int(volume['size']) * units.Ki,
                'blockSize': self.blocksize,
                'chunkSize': self.chunksize
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating volume'))

    def delete_volume(self, volume):
        number = self._get_nbd_number(volume)
        if number == -1:
            return
        host = volutils.extract_host(volume['host'], 'host')
        try:
            self.restapi.delete('nbd' + self._get_remote_url(host), {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'number': number
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error deleting volume'))

    def extend_volume(self, volume, new_size):
        host = volutils.extract_host(volume['host'], 'host')
        try:
            self.restapi.put('nbd/resize' + self._get_remote_url(host), {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'newSizeMB': new_size * units.Ki
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error extending volume'))

    def create_snapshot(self, snapshot):
        try:
            self.restapi.post('nbd/snapshot', {
                'objectPath': self.bucket_path + '/' + snapshot['volume_name'],
                'snapName': snapshot['name']
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating snapshot'))

    def delete_snapshot(self, snapshot):
        try:
            self.restapi.delete('nbd/snapshot', {
                'objectPath': self.bucket_path + '/' + snapshot['volume_name'],
                'snapName': snapshot['name']
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error deleting snapshot'))

    def create_volume_from_snapshot(self, volume, snapshot):
        host = volutils.extract_host(volume['host'], 'host')
        remotehost = self._get_remote_url(host)
        try:
            self.restapi.put('nbd/snapshot/clone' + remotehost, {
                'objectPath': self.bucket_path + '/' + snapshot['volume_name'],
                'snapName': snapshot['name'],
                'clonePath': self.bucket_path + '/' + volume['name']
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error cloning snapshot'))

    def create_cloned_volume(self, volume, src_vref):
        vol_url = (self.bucket_url + '/objects/' +
                   src_vref['name'] + '/clone')
        clone_body = {
            'tenant_name': self.tenant,
            'bucket_name': self.bucket,
            'object_name': volume['name']
        }
        host = volutils.extract_host(volume['host'], 'host')
        try:
            self.restapi.post(vol_url, clone_body)
            self.restapi.post('nbd' + self._get_remote_url(host), {
                'objectPath': self.bucket_path + '/' + volume['name'],
                'volSizeMB': int(src_vref['size']) * units.Ki,
                'blockSize': self.blocksize,
                'chunkSize': self.chunksize
            })
        except exception.VolumeBackendAPIException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error creating cloned volume'))

    def migrate_volume(self, ctxt, volume, host, thin=False, mirror_count=0):
        raise NotImplemented

    def get_volume_stats(self, refresh=False):
        location_info = '%(driver)s:%(host)s:%(bucket)s' % {
            'driver': self.__class__.__name__,
            'host': self.hostname,
            'bucket': self.bucket_path
        }
        return {
            'vendor_name': 'Nexenta',
            'driver_version': self.VERSION,
            'storage_protocol': 'NBD',
            'reserved_percentage': 0,
            'total_capacity_gb': 'unknown',
            'free_capacity_gb': 'unknown',
            'QoS_support': False,
            'volume_backend_name': self.backend_name,
            'location_info': location_info,
            'restapi_url': self.restapi.url
        }

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 self.local_path(volume),
                                 self.configuration.volume_dd_blocksize,
                                 size=volume['size'])

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        image_utils.upload_volume(context,
                                  image_service,
                                  image_meta,
                                  self.local_path(volume))

    # #######  Interface methods for DataPath (Target Driver) ########

    def ensure_export(self, context, volume):
        volume_path = self.local_path(volume)
        model_update = \
            self.target_driver.ensure_export(context, volume, volume_path)
        return model_update

    def create_export(self, context, volume, connector, vg=None):
        volume_path = self.local_path(volume)
        export_info = self.target_driver.create_export(
            context,
            volume,
            volume_path)
        return {'provider_location': export_info['location'],
                'provider_auth': export_info['auth'], }

    def remove_export(self, context, volume):
        self.target_driver.remove_export(context, volume)

    def initialize_connection(self, volume, connector):
        if connector['host'] != volutils.extract_host(volume['host'], 'host'):
            return self.target_driver.initialize_connection(volume, connector)
        else:
            return {
                'driver_volume_type': 'local',
                'data': {'device_path': self.local_path(volume)},
            }

    def validate_connector(self, connector):
        return self.target_driver.validate_connector(connector)

    def terminate_connection(self, volume, connector, **kwargs):
        return self.target_driver.terminate_connection(volume, connector,
                                                       **kwargs)
