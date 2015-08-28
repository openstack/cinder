# Copyright (c) 2014, 2015, Oracle and/or its affiliates. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""
ZFS Storage Appliance NFS Cinder Volume Driver
"""
import base64
import datetime as dt
import errno
import math

from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import units
import six

from cinder import exception
from cinder import utils
from cinder.i18n import _, _LE, _LI
from cinder.volume.drivers import nfs
from cinder.volume.drivers.san import san
from cinder.volume.drivers.zfssa import zfssarest


ZFSSA_OPTS = [
    cfg.StrOpt('zfssa_data_ip',
               help='Data path IP address'),
    cfg.StrOpt('zfssa_https_port', default='443',
               help='HTTPS port number'),
    cfg.StrOpt('zfssa_nfs_mount_options', default='',
               help='Options to be passed while mounting share over nfs'),
    cfg.StrOpt('zfssa_nfs_pool', default='',
               help='Storage pool name.'),
    cfg.StrOpt('zfssa_nfs_project', default='NFSProject',
               help='Project name.'),
    cfg.StrOpt('zfssa_nfs_share', default='nfs_share',
               help='Share name.'),
    cfg.StrOpt('zfssa_nfs_share_compression', default='off',
               choices=['off', 'lzjb', 'gzip-2', 'gzip', 'gzip-9'],
               help='Data compression.'),
    cfg.StrOpt('zfssa_nfs_share_logbias', default='latency',
               choices=['latency', 'throughput'],
               help='Synchronous write bias-latency, throughput.'),
    cfg.IntOpt('zfssa_rest_timeout',
               help='REST connection timeout. (seconds)'),
    cfg.BoolOpt('zfssa_enable_local_cache', default=True,
                help='Flag to enable local caching: True, False.'),
    cfg.StrOpt('zfssa_cache_directory', default='os-cinder-cache',
               help='Name of directory inside zfssa_nfs_share where cache '
                    'volumes are stored.')
]

LOG = log.getLogger(__name__)

CONF = cfg.CONF
CONF.register_opts(ZFSSA_OPTS)


def factory_zfssa():
    return zfssarest.ZFSSANfsApi()


class ZFSSANFSDriver(nfs.NfsDriver):
    """ZFSSA Cinder NFS volume driver.

    Version history:
    1.0.1:
        Backend enabled volume migration.
        Local cache feature.
    """
    VERSION = '1.0.1'
    volume_backend_name = 'ZFSSA_NFS'
    protocol = driver_prefix = driver_volume_type = 'nfs'

    def __init__(self, *args, **kwargs):
        super(ZFSSANFSDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(ZFSSA_OPTS)
        self.configuration.append_config_values(san.san_opts)
        self.zfssa = None
        self._stats = None

    def do_setup(self, context):
        if not self.configuration.nfs_oversub_ratio > 0:
            msg = _("NFS config 'nfs_oversub_ratio' invalid. Must be > 0: "
                    "%s") % self.configuration.nfs_oversub_ratio
            LOG.error(msg)
            raise exception.NfsException(msg)

        if ((not self.configuration.nfs_used_ratio > 0) and
                (self.configuration.nfs_used_ratio <= 1)):
            msg = _("NFS config 'nfs_used_ratio' invalid. Must be > 0 "
                    "and <= 1.0: %s") % self.configuration.nfs_used_ratio
            LOG.error(msg)
            raise exception.NfsException(msg)

        package = 'mount.nfs'
        try:
            self._execute(package, check_exit_code=False, run_as_root=True)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                msg = _('%s is not installed') % package
                raise exception.NfsException(msg)
            else:
                raise

        lcfg = self.configuration
        LOG.info(_LI('Connecting to host: %s.'), lcfg.san_ip)

        host = lcfg.san_ip
        user = lcfg.san_login
        password = lcfg.san_password
        https_port = lcfg.zfssa_https_port

        credentials = ['san_ip', 'san_login', 'san_password', 'zfssa_data_ip']

        for cred in credentials:
            if not getattr(lcfg, cred, None):
                exception_msg = _('%s not set in cinder.conf') % cred
                LOG.error(exception_msg)
                raise exception.CinderException(exception_msg)

        self.zfssa = factory_zfssa()
        self.zfssa.set_host(host, timeout=lcfg.zfssa_rest_timeout)

        auth_str = base64.encodestring('%s:%s' % (user, password))[:-1]
        self.zfssa.login(auth_str)

        self.zfssa.create_project(lcfg.zfssa_nfs_pool, lcfg.zfssa_nfs_project,
                                  compression=lcfg.zfssa_nfs_share_compression,
                                  logbias=lcfg.zfssa_nfs_share_logbias)

        share_args = {
            'sharedav': 'rw',
            'sharenfs': 'rw',
            'root_permissions': '777',
            'compression': lcfg.zfssa_nfs_share_compression,
            'logbias': lcfg.zfssa_nfs_share_logbias
        }

        self.zfssa.create_share(lcfg.zfssa_nfs_pool, lcfg.zfssa_nfs_project,
                                lcfg.zfssa_nfs_share, share_args)

        share_details = self.zfssa.get_share(lcfg.zfssa_nfs_pool,
                                             lcfg.zfssa_nfs_project,
                                             lcfg.zfssa_nfs_share)

        mountpoint = share_details['mountpoint']

        self.mount_path = lcfg.zfssa_data_ip + ':' + mountpoint
        https_path = 'https://' + lcfg.zfssa_data_ip + ':' + https_port + \
            '/shares' + mountpoint

        LOG.debug('NFS mount path: %s', self.mount_path)
        LOG.debug('WebDAV path to the share: %s', https_path)

        self.shares = {}
        mnt_opts = self.configuration.zfssa_nfs_mount_options
        self.shares[self.mount_path] = mnt_opts if len(mnt_opts) > 1 else None

        # Initialize the WebDAV client
        self.zfssa.set_webdav(https_path, auth_str)

        # Edit http service so that WebDAV requests are always authenticated
        args = {'https_port': https_port,
                'require_login': True}

        self.zfssa.modify_service('http', args)
        self.zfssa.enable_service('http')

        if lcfg.zfssa_enable_local_cache:
            LOG.debug('Creating local cache directory %s.',
                      lcfg.zfssa_cache_directory)
            self.zfssa.create_directory(lcfg.zfssa_cache_directory)

    def _ensure_shares_mounted(self):
        try:
            self._ensure_share_mounted(self.mount_path)
        except Exception as exc:
            LOG.error(_LE('Exception during mounting %s.'), exc)

        self._mounted_shares = [self.mount_path]
        LOG.debug('Available shares %s', self._mounted_shares)

    def check_for_setup_error(self):
        """Check that driver can login.

        Check also for properly configured pool, project and share
        Check that the http and nfs services are enabled
        """
        lcfg = self.configuration

        self.zfssa.verify_pool(lcfg.zfssa_nfs_pool)
        self.zfssa.verify_project(lcfg.zfssa_nfs_pool, lcfg.zfssa_nfs_project)
        self.zfssa.verify_share(lcfg.zfssa_nfs_pool, lcfg.zfssa_nfs_project,
                                lcfg.zfssa_nfs_share)
        self.zfssa.verify_service('http')
        self.zfssa.verify_service('nfs')

    def create_snapshot(self, snapshot):
        """Creates a snapshot of a volume."""
        LOG.info(_LI('Creating snapshot: %s'), snapshot['name'])
        lcfg = self.configuration
        snap_name = self._create_snapshot_name()
        self.zfssa.create_snapshot(lcfg.zfssa_nfs_pool, lcfg.zfssa_nfs_project,
                                   lcfg.zfssa_nfs_share, snap_name)

        src_file = snap_name + '/' + snapshot['volume_name']

        try:
            self.zfssa.create_snapshot_of_volume_file(src_file=src_file,
                                                      dst_file=
                                                      snapshot['name'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.debug('Error thrown during snapshot: %s creation',
                          snapshot['name'])
        finally:
            self.zfssa.delete_snapshot(lcfg.zfssa_nfs_pool,
                                       lcfg.zfssa_nfs_project,
                                       lcfg.zfssa_nfs_share, snap_name)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        LOG.info(_LI('Deleting snapshot: %s'), snapshot['name'])
        self.zfssa.delete_snapshot_of_volume_file(src_file=snapshot['name'])

    def create_volume_from_snapshot(self, volume, snapshot, method='COPY'):
        LOG.info(_LI('Creatng volume from snapshot. volume: %s'),
                 volume['name'])
        LOG.info(_LI('Source Snapshot: %s'), snapshot['name'])

        self._ensure_shares_mounted()
        self.zfssa.create_volume_from_snapshot_file(src_file=snapshot['name'],
                                                    dst_file=volume['name'],
                                                    method=method)

        volume['provider_location'] = self.mount_path

        if volume['size'] != snapshot['volume_size']:
            try:
                self.extend_volume(volume, volume['size'])
            except Exception:
                vol_path = self.local_path(volume)
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Error in extending volume size: Volume: '
                                  '%(volume)s Vol_Size: %(vol_size)d with '
                                  'Snapshot: %(snapshot)s Snap_Size: '
                                  '%(snap_size)d'),
                              {'volume': volume['name'],
                               'vol_size': volume['size'],
                               'snapshot': snapshot['name'],
                               'snap_size': snapshot['volume_size']})
                    self._execute('rm', '-f', vol_path, run_as_root=True)

        volume_origin = {'origin': snapshot['volume_name']}
        self.zfssa.set_file_props(volume['name'], volume_origin)

        return {'provider_location': volume['provider_location']}

    def create_cloned_volume(self, volume, src_vref):
        """Creates a snapshot and then clones the snapshot into a volume."""
        LOG.info(_LI('new cloned volume: %s'), volume['name'])
        LOG.info(_LI('source volume for cloning: %s'), src_vref['name'])

        snapshot = {'volume_name': src_vref['name'],
                    'volume_id': src_vref['id'],
                    'volume_size': src_vref['size'],
                    'name': self._create_snapshot_name()}

        self.create_snapshot(snapshot)
        return self.create_volume_from_snapshot(volume, snapshot,
                                                method='MOVE')

    def delete_volume(self, volume):
        LOG.debug('Deleting volume %s.', volume['name'])
        lcfg = self.configuration
        try:
            vol_props = self.zfssa.get_volume(volume['name'])
        except exception.VolumeNotFound:
            return
        super(ZFSSANFSDriver, self).delete_volume(volume)

        if vol_props['origin'].startswith(lcfg.zfssa_cache_directory):
            LOG.info(_LI('Checking origin %(origin)s of volume %(volume)s.'),
                     {'origin': vol_props['origin'],
                      'volume': volume['name']})
            self._check_origin(vol_props['origin'])

    def clone_image(self, context, volume,
                    image_location, image_meta,
                    image_service):
        """Create a volume efficiently from an existing image.

        Verify the image ID being used:

        (1) If there is no existing cache volume, create one and transfer
        image data to it. Take a snapshot.

        (2) If a cache volume already exists, verify if it is either alternated
        or updated. If so try to remove it, raise exception if removal fails.
        Create a new cache volume as in (1).

        Clone a volume from the cache volume and returns it to Cinder.
        """
        LOG.debug('Cloning image %(image)s to volume %(volume)s',
                  {'image': image_meta['id'], 'volume': volume['name']})
        lcfg = self.configuration
        if not lcfg.zfssa_enable_local_cache:
            return None, False

        # virtual_size is the image's actual size when stored in a volume
        # virtual_size is expected to be updated manually through glance
        try:
            virtual_size = int(image_meta['properties'].get('virtual_size'))
        except Exception:
            LOG.error(_LE('virtual_size property is not set for the image.'))
            return None, False
        cachevol_size = int(math.ceil(float(virtual_size) / units.Gi))
        if cachevol_size > volume['size']:
            exception_msg = (_LE('Image size %(img_size)dGB is larger '
                                 'than volume size %(vol_size)dGB.'),
                             {'img_size': cachevol_size,
                              'vol_size': volume['size']})
            LOG.error(exception_msg)
            return None, False

        cache_dir = '%s/' % lcfg.zfssa_cache_directory
        updated_at = six.text_type(image_meta['updated_at'].isoformat())
        cachevol_props = {
            'name': '%sos-cache-vol-%s' % (cache_dir,
                                           image_meta['id']),
            'size': cachevol_size,
            'updated_at': updated_at,
            'image_id': image_meta['id'],
        }

        try:
            cachevol_name = self._verify_cache_volume(context,
                                                      image_meta,
                                                      image_service,
                                                      cachevol_props)
            # A cache volume should be ready by now
            # Create a clone from the cache volume
            cache_vol = {
                'name': cachevol_name,
                'size': cachevol_size,
                'id': image_meta['id'],
            }
            clone_vol = self.create_cloned_volume(volume, cache_vol)
            self._update_origin(volume['name'], cachevol_name)
        except exception.VolumeBackendAPIException as exc:
            exception_msg = (_LE('Cannot clone image %(image)s to '
                                 'volume %(volume)s. Error: %(error)s.'),
                             {'volume': volume['name'],
                              'image': image_meta['id'],
                              'error': exc.message})
            LOG.error(exception_msg)
            return None, False

        return clone_vol, True

    @utils.synchronized('zfssanfs', external=True)
    def _verify_cache_volume(self, context, img_meta,
                             img_service, cachevol_props):
        """Verify if we have a cache volume that we want.

        If we don't, create one.
        If we do, check if it's been updated:
          * If so, delete it and recreate a new volume
          * If not, we are good.

        If it's out of date, delete it and create a new one.

        After the function returns, there should be a cache volume available,
        ready for cloning.
        """
        cachevol_name = cachevol_props['name']
        cache_vol = None
        LOG.debug('Verifying cache volume %s:', cachevol_name)

        try:
            cache_vol = self.zfssa.get_volume(cachevol_name)
        except exception.VolumeNotFound:
            # There is no existing cache volume, create one:
            LOG.debug('Cache volume not found. Creating one...')
            return self._create_cache_volume(context,
                                             img_meta,
                                             img_service,
                                             cachevol_props)

        # A cache volume does exist, check if it's updated:
        if ((cache_vol['updated_at'] != cachevol_props['updated_at']) or
                (cache_vol['image_id'] != cachevol_props['image_id'])):
            if cache_vol['numclones'] > 0:
                # The cache volume is updated, but has clones
                exception_msg = (_('Cannot delete '
                                   'cache volume: %(cachevol_name)s. '
                                   'It was updated at %(updated_at)s '
                                   'and currently has %(numclones)d '
                                   'volume instances.'),
                                 {'cachevol_name': cachevol_name,
                                  'updated_at': cachevol_props['updated_at'],
                                  'numclones': cache_vol['numclones']})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

            # The cache volume is updated, but has no clone, so we delete it
            # and re-create a new one:
            cache_vol = {
                'provider_location': self.mount_path,
                'name': cachevol_name,
            }
            self.delete_volume(cache_vol)
            return self._create_cache_volume(context,
                                             img_meta,
                                             img_service,
                                             cachevol_props)

        return cachevol_name

    def _create_cache_volume(self, context, img_meta,
                             img_service, cachevol_props):
        """Create a cache volume from an image.

        Returns name of the cache volume.
        """
        cache_vol = {
            'provider_location': self.mount_path,
            'size': cachevol_props['size'],
            'name': cachevol_props['name'],
        }
        LOG.debug('Creating cache volume %s', cache_vol['name'])

        try:
            super(ZFSSANFSDriver, self).create_volume(cache_vol)
            LOG.debug('Copying image data:')
            super(ZFSSANFSDriver, self).copy_image_to_volume(context,
                                                             cache_vol,
                                                             img_service,
                                                             img_meta['id'])

        except Exception as exc:
            exc_msg = (_('Fail to create cache volume %(volume)s. '
                         'Error: %(err)s'),
                       {'volume': cache_vol['name'],
                        'err': six.text_type(exc)})
            LOG.error(exc_msg)
            self.zfssa.delete_file(cache_vol['name'])
            raise exception.VolumeBackendAPIException(data=exc_msg)

        cachevol_meta = {
            'updated_at': cachevol_props['updated_at'],
            'image_id': cachevol_props['image_id'],
        }
        cachevol_meta.update({'numclones': '0'})
        self.zfssa.set_file_props(cache_vol['name'], cachevol_meta)
        return cache_vol['name']

    def _create_snapshot_name(self):
        """Creates a snapshot name from the date and time."""

        return ('cinder-zfssa-nfs-snapshot-%s' %
                dt.datetime.utcnow().isoformat())

    def _get_share_capacity_info(self):
        """Get available and used capacity info for the NFS share."""
        lcfg = self.configuration
        share_details = self.zfssa.get_share(lcfg.zfssa_nfs_pool,
                                             lcfg.zfssa_nfs_project,
                                             lcfg.zfssa_nfs_share)

        free = share_details['space_available']
        used = share_details['space_total']
        return free, used

    @utils.synchronized('zfssanfs', external=True)
    def _check_origin(self, origin):
        """Verify the cache volume of a bootable volume.

        If the cache no longer has clone, it will be deleted.
        """
        cachevol_props = self.zfssa.get_volume(origin)
        numclones = cachevol_props['numclones']
        LOG.debug('Number of clones: %d', numclones)
        if numclones <= 1:
            # This cache vol does not have any other clone
            self.zfssa.delete_file(origin)
        else:
            cachevol_props = {'numclones': six.text_type(numclones - 1)}
            self.zfssa.set_file_props(origin, cachevol_props)

    @utils.synchronized('zfssanfs', external=True)
    def _update_origin(self, vol_name, cachevol_name):
        """Update WebDAV property of a volume.

        WebDAV properties are used to keep track of:
        (1) The number of clones of a cache volume.
        (2) The cache volume name (origin) of a bootable volume.

        To avoid race conditions when multiple volumes are created and needed
        to be updated, a file lock is used to ensure that the properties are
        updated properly.
        """
        volume_origin = {'origin': cachevol_name}
        self.zfssa.set_file_props(vol_name, volume_origin)

        cache_props = self.zfssa.get_volume(cachevol_name)
        cache_props.update({'numclones':
                            six.text_type(cache_props['numclones'] + 1)})
        self.zfssa.set_file_props(cachevol_name, cache_props)

    def _update_volume_stats(self):
        """Get volume stats from zfssa"""
        self._ensure_shares_mounted()
        data = {}
        lcfg = self.configuration
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['vendor_name'] = 'Oracle'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = self.protocol

        asn = self.zfssa.get_asn()
        data['location_info'] = '%s:%s' % (asn, lcfg.zfssa_nfs_share)

        free, used = self._get_share_capacity_info()
        capacity = float(free) + float(used)
        ratio_used = used / capacity

        data['QoS_support'] = False
        data['reserved_percentage'] = 0

        if ratio_used > self.configuration.nfs_used_ratio or \
           ratio_used >= self.configuration.nfs_oversub_ratio:
            data['reserved_percentage'] = 100

        data['total_capacity_gb'] = float(capacity) / units.Gi
        data['free_capacity_gb'] = float(free) / units.Gi

        self._stats = data

    def migrate_volume(self, ctxt, volume, host):
        LOG.debug('Attempting ZFSSA enabled volume migration. volume: %(id)s, '
                  'host: %(host)s, status=%(status)s',
                  {'id': volume['id'],
                   'host': host,
                   'status': volume['status']})

        lcfg = self.configuration
        default_ret = (False, None)

        if volume['status'] != "available":
            LOG.debug('Only available volumes can be migrated using backend '
                      'assisted migration. Defaulting to generic migration.')
            return default_ret

        if (host['capabilities']['vendor_name'] != 'Oracle' or
                host['capabilities']['storage_protocol'] != self.protocol):
            LOG.debug('Source and destination drivers need to be Oracle iSCSI '
                      'to use backend assisted migration. Defaulting to '
                      'generic migration.')
            return default_ret

        if 'location_info' not in host['capabilities']:
            LOG.debug('Could not find location_info in capabilities reported '
                      'by the destination driver. Defaulting to generic '
                      'migration.')
            return default_ret

        loc_info = host['capabilities']['location_info']

        try:
            (tgt_asn, tgt_share) = loc_info.split(':')
        except ValueError:
            LOG.error(_LE("Location info needed for backend enabled volume "
                          "migration not in correct format: %s. Continuing "
                          "with generic volume migration."), loc_info)
            return default_ret

        src_asn = self.zfssa.get_asn()

        if tgt_asn == src_asn and lcfg.zfssa_nfs_share == tgt_share:
            LOG.info(_LI('Source and destination ZFSSA shares are the same. '
                         'Do nothing. volume: %s'), volume['name'])
            return (True, None)

        return (False, None)

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update for migrated volume.

        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :return model_update to update DB with any needed changes
        """

        original_name = CONF.volume_name_template % volume['id']
        current_name = CONF.volume_name_template % new_volume['id']

        LOG.debug('Renaming migrated volume: %(cur)s to %(org)s.',
                  {'cur': current_name,
                   'org': original_name})
        self.zfssa.create_volume_from_snapshot_file(src_file=current_name,
                                                    dst_file=original_name,
                                                    method='MOVE')
        provider_location = new_volume['provider_location']
        return {'_name_id': None, 'provider_location': provider_location}
