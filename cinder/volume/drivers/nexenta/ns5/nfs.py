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

import hashlib
import os
import six

from eventlet import greenthread
from oslo_log import log as logging
from oslo_utils import units
from six.moves import urllib

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils
from cinder.volume.drivers import nfs

VERSION = '1.6.9'
LOG = logging.getLogger(__name__)
BLOCK_SIZE_MB = 1


class NexentaNfsDriver(nfs.NfsDriver):
    """Executes volume driver commands on Nexenta Appliance.

    Version history:
        1.0.0 - Initial driver version.
        1.1.0 - Support for extend volume.
        1.2.0 - Added HTTPS support.
                Added use of sessions for REST calls.
                Added abandoned volumes and snapshots cleanup.
        1.3.0 - Failover support.
        1.4.0 - Migrate volume support and new NEF API calls.
        1.6.0 - Get mountPoint from API to support old style mount points.
                Mount and umount shares on each operation to avoid mass
                mounts on controller. Clean up mount folders on delete.
        1.6.1 - Fixed volume from image creation.
        1.6.2 - Removed redundant share mount from initialize_connection.
        1.6.3 - Adapted NexentaException for the latest Cinder.
        1.6.4 - Fixed volume mount/unmount.
        1.6.5 - Added driver_ssl_cert_verify for HA failover.
        1.6.6 - Destroy unused snapshots after deletion of it's last clone.
        1.6.7 - Fixed volume migration for HA environment.
        1.6.8 - Added deferred deletion for snapshots.
        1.6.9 - Fixed race between volume/clone deletion.
    """

    driver_prefix = 'nexenta'
    volume_backend_name = 'NexentaNfsDriver'
    VERSION = VERSION

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Nexenta_CI"

    def __init__(self, *args, **kwargs):
        super(NexentaNfsDriver, self).__init__(*args, **kwargs)
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_CONNECTION_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_NFS_OPTS)
            self.configuration.append_config_values(
                options.NEXENTA_DATASET_OPTS)

        self.verify_ssl = self.configuration.driver_ssl_cert_verify
        self.nfs_mount_point_base = self.configuration.nexenta_mount_point_base
        self.dataset_compression = (
            self.configuration.nexenta_dataset_compression)
        self.dataset_description = (
            self.configuration.nexenta_dataset_description)
        self.sparsed_volumes = self.configuration.nexenta_sparsed_volumes
        self.nef = None
        self.use_https = self.configuration.nexenta_use_https
        self.nef_host = self.configuration.nexenta_rest_address
        self.nas_host = self.configuration.nas_host
        self.share = self.configuration.nas_share_path
        self.nef_port = self.configuration.nexenta_rest_port
        self.nef_user = self.configuration.nexenta_user
        self.nef_password = self.configuration.nexenta_password

    @property
    def backend_name(self):
        backend_name = None
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = self.__class__.__name__
        return backend_name

    def do_setup(self, context):
        host = self.nef_host or self.nas_host
        pool_name, fs = self._get_share_datasets(self.share)
        self.nef = jsonrpc.NexentaJSONProxy(
            host, self.nef_port, self.nef_user,
            self.nef_password, self.use_https, pool_name, self.verify_ssl)

    def check_for_setup_error(self):
        """Verify that nas_share_path is shared over NFS."""
        pool_name, fs = self._get_share_datasets(self.share)
        url = 'storage/pools/%s' % (pool_name)
        self.nef.get(url)

        url = 'nas/nfs?filesystem=%s' % urllib.parse.quote_plus(self.share)
        data = self.nef.get(url).get('data')
        if not (data and data[0].get('shareState') == 'online'):
            msg = (_('NFS share %(share)s is not accessible')
                   % {'share': self.share})
            raise exception.NexentaException(msg)

    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume reference
        :returns: provider_location update dict for database
        """
        LOG.debug('Create volume %(volume)s',
                  {'volume': volume['name']})
        self._do_create_volume(volume)
        return {'provider_location': volume['provider_location']}

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        LOG.debug('Copy image %(image)s to volume %(volume)s',
                  {'image': image_id,
                   'volume': volume['name']})
        self._mount_volume(volume)
        super(NexentaNfsDriver, self).copy_image_to_volume(
            context, volume, image_service, image_id)
        self._unmount_volume(volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        LOG.debug('Copy volume %(volume)s to image %(image)s',
                  {'volume': volume['name'],
                   'image': image_meta['id']})
        self._mount_volume(volume)
        super(NexentaNfsDriver, self).copy_volume_to_image(
            context, volume, image_service, image_meta)
        self._unmount_volume(volume)

    def _do_create_volume(self, volume):
        pool, fs = self._get_share_datasets(self.share)
        filesystem = '%s/%s/%s' % (pool, fs, volume['name'])
        LOG.debug('Create filesystem %(filesystem)s',
                  {'filesystem': filesystem})
        url = 'storage/filesystems'
        data = {
            'path': '/'.join([pool, fs, volume['name']]),
            'compressionMode': self.dataset_compression,
        }
        try:
            self.nef.post(url, data)
        except exception.NexentaException as ex:
            err = utils.ex2err(ex)
            if err['code'] == 'EEXIST':
                LOG.debug('Filesystem %(filesystem)s already exists, '
                          'reuse existing filesystem',
                          {'filesystem': filesystem})
            else:
                raise ex
        volume['provider_location'] = '%s:/%s/%s' % (
            self.nas_host, self.share, volume['name'])
        try:
            self._share_folder(fs, volume['name'])
            self._mount_volume(volume)
            volume_size = volume['size']
            if getattr(self.configuration,
                       self.driver_prefix + '_sparsed_volumes'):
                self._create_sparsed_file(self.local_path(volume), volume_size)
            else:
                url = 'storage/filesystems/%s' % (
                    '%2F'.join([pool, fs, volume['name']]))
                compression = self.nef.get(url).get('compressionMode')
                if compression != 'off':
                    # Disable compression, because otherwise will not use space
                    # on disk.
                    self.nef.put(url, {'compressionMode': 'off'})
                try:
                    self._create_regular_file(
                        self.local_path(volume), volume_size)
                finally:
                    if compression != 'off':
                        # Backup default compression value if it was changed.
                        self.nef.put(url, {'compressionMode': compression})

        except exception.NexentaException as ex:
            try:
                url = 'storage/filesystems/%s' % (
                    '%2F'.join([pool, fs, volume['name']]))
                self.nef.delete(url)
            except exception.NexentaException:
                LOG.debug('Cannot destroy created filesystem '
                          '%(pool)s/%(filesystem)s/%(volume)s: %(error)s',
                          {'pool': pool,
                           'filesystem': fs,
                           'volume': volume['name'],
                           'error': six.text_type(ex)})
            raise ex
        finally:
            self._unmount_volume(volume)

    def _ensure_share_unmounted(self, nfs_share, mount_path=None):
        """Ensure that NFS share is unmounted on the host.

        :param nfs_share: NFS share name
        :param mount_path: mount path on the host
        """

        num_attempts = max(1, self.configuration.nfs_mount_attempts)

        if mount_path is None:
            mount_path = self._get_mount_point_for_share(nfs_share)

        if mount_path not in self._remotefsclient._read_mounts():
            LOG.debug('NFS share %(share)s is not mounted at %(path)s',
                      {'share': nfs_share,
                       'path': mount_path})
            return

        for attempt in range(num_attempts):
            try:
                self._execute('umount', mount_path, run_as_root=True)
                LOG.debug('NFS share %(share)s has been unmounted at %(path)s',
                          {'share': nfs_share,
                           'path': mount_path})
                break
            except Exception as ex:
                msg = six.text_type(ex)
                if attempt == (num_attempts - 1):
                    LOG.error('Unmount failure for %(share)s after '
                              '%(count)d attempts',
                              {'share': nfs_share,
                               'count': num_attempts})
                    raise exception.NfsException(msg)
                LOG.warning('Unmount attempt %(attempt)d failed: %(msg)s, '
                            'retrying unmount %(share)s from %(path)s',
                            {'attempt': attempt,
                             'msg': msg,
                             'share': nfs_share,
                             'path': mount_path})
                greenthread.sleep(1)

        self._delete(mount_path)

    def _mount_volume(self, volume):
        """Ensure that volume is activated and mounted on the host."""
        dataset_name = self._get_dataset_name(volume)
        dataset_url = 'storage/filesystems/%s' % (
            urllib.parse.quote_plus(dataset_name))
        dataset = self.nef.get(dataset_url)
        dataset_mount_point = dataset.get('mountPoint')
        dataset_ready = dataset.get('isMounted')
        if dataset_mount_point == 'none':
            hpr_url = 'hpr/activate'
            data = {'datasetName': dataset_name}
            self.nef.post(hpr_url, data)
            dataset = self.nef.get(dataset_url)
            dataset_mount_point = dataset.get('mountPoint')
        elif not dataset_ready:
            dataset_url = 'storage/filesystems/%s/mount' % (
                urllib.parse.quote_plus(dataset_name))
            self.nef.post(dataset_url)
        nfs_share = '%s:%s' % (self.nas_host, dataset_mount_point)
        self._ensure_share_mounted(nfs_share)

    def _unmount_volume(self, volume):
        """Ensure that volume is unmounted on the host."""
        dataset_name = self._get_dataset_name(volume)
        params = {'path': dataset_name}
        url = 'storage/filesystems?%s' % urllib.parse.urlencode(params)
        data = self.nef.get(url).get('data')
        if not data:
            return
        dataset = data[0]
        dataset_mount_point = dataset.get('mountPoint')
        nfs_share = '%s:%s' % (self.nas_host, dataset_mount_point)
        self._ensure_share_unmounted(nfs_share)

    def _create_sparsed_file(self, path, size):
        """Creates file with 0 disk usage."""
        if self.configuration.nexenta_qcow2_volumes:
            self._create_qcow2_file(path, size)
        else:
            super(NexentaNfsDriver, self)._create_sparsed_file(path, size)

    def migrate_volume(self, ctxt, volume, host):
        """Migrate if volume and host are managed by Nexenta appliance.

        :param ctxt: context
        :param volume: a dictionary describing the volume to migrate
        :param host: a dictionary describing the host to migrate to
        """
        LOG.debug('Migrate volume %(volume)s to host %(host)s',
                  {'volume': volume['name'],
                   'host': host})

        false_ret = (False, None)

        if volume['status'] not in ('available', 'retyping'):
            LOG.error('Volume %(volume)s status must be available or '
                      'retyping, current volume status is %(status)s',
                      {'volume': volume['name'],
                       'status': volume['status']})
            return false_ret

        if 'capabilities' not in host:
            LOG.error('Unsupported host %(host)s: '
                      'no capabilities found',
                      {'host': host})
            return false_ret

        capabilities = host['capabilities']

        if not ('location_info' in capabilities and
                'vendor_name' in capabilities and
                'free_capacity_gb' in capabilities):
            LOG.error('Unsupported host %(host)s: required NFS '
                      'and vendor capabilities are not found',
                      {'host': host})
            return false_ret

        dst_driver_name = capabilities['location_info'].split(':')[0]
        dst_fs = capabilities['location_info'].split(':/')[1]

        if not (capabilities['vendor_name'] == 'Nexenta' and
                dst_driver_name == self.__class__.__name__):
            LOG.error('Unsupported host %(host)s: incompatible '
                      'vendor %(vendor)s or driver %(driver)s',
                      {'host': host,
                       'vendor': capabilities['vendor_name'],
                       'driver': dst_driver_name})
            return false_ret

        if capabilities['free_capacity_gb'] < volume['size']:
            LOG.error('There is not enough space available on the '
                      'host %(host)s to migrate volume %(volume), '
                      'free space: %(free)d, required: %(size)d',
                      {'host': host,
                       'volume': volume['name'],
                       'free': capabilities['free_capacity_gb'],
                       'size': volume['size']})
            return false_ret

        nef_ips = capabilities['nef_url'].split(',')
        nef_ips.append(None)
        pool, fs = self._get_share_datasets(self.share)
        url = 'hpr/services'
        svc = 'cinder-migrate-%s' % volume['name']
        data = {
            'name': svc,
            'sourceDataset': '/'.join([pool, fs, volume['name']]),
            'destinationDataset': '/'.join([dst_fs, volume['name']]),
            'type': 'scheduled',
            'sendShareNfs': True
        }
        for nef_ip in nef_ips:
            hpr = data
            if nef_ip is not None:
                hpr['isSource'] = True
                hpr['remoteNode'] = {
                    'host': nef_ip,
                    'port': capabilities['nef_port']
                }
            try:
                self.nef.post(url, hpr)
                break
            except exception.NexentaException as ex:
                err = utils.ex2err(ex)
                if nef_ip is None or err['code'] not in ('EINVAL', 'ENOENT'):
                    LOG.error('Failed to create replication '
                              'service %(data)s: %(error)s',
                              {'data': data,
                               'error': six.text_type(err)})
                    return false_ret

        url = 'hpr/services/%s/start' % svc
        try:
            self.nef.post(url)
        except exception.NexentaException as ex:
            err = utils.ex2err(ex)
            LOG.error('Failed to start replication '
                      'service %(svc)s: %(error)s',
                      {'svc': svc,
                       'error': six.text_type(err)})
            return false_ret

        provider_location = '/'.join([
            capabilities['location_info'].lstrip('%s:' % dst_driver_name),
            volume['name']])

        data = {
            'destroySourceSnapshots': 'true',
            'destroyDestinationSnapshots': 'true'
        }
        params = urllib.parse.urlencode(data)
        in_progress = True
        url = 'hpr/services/%s' % svc
        timeout = 1
        while in_progress:
            state = self.nef.get(url)['state']
            if state == 'disabled':
                in_progress = False
            elif state == 'enabled':
                greenthread.sleep(timeout)
                timeout = timeout * 2
            else:
                url = 'hpr/services/%s?%s' % (svc, params)
                self.nef.delete(url)
                return false_ret

        url = 'hpr/services/%s?%s' % (svc, params)
        self.nef.delete(url)

        try:
            self.delete_volume(volume)
        except exception.NexentaException as ex:
            LOG.warning('Cannot delete source volume %(volume)s: %(error)s',
                        {'volume': volume['name'],
                         'error': six.text_type(ex)})

        return True, {'provider_location': provider_location}

    def terminate_connection(self, volume, connector, **kwargs):
        LOG.debug('Terminate volume connection for %(volume)s',
                  {'volume': volume['name']})
        self._unmount_volume(volume)

    def initialize_connection(self, volume, connector):
        LOG.debug('Initialize volume connection for %(volume)s',
                  {'volume': volume['name']})
        url = 'hpr/activate'
        data = {'datasetName': '/'.join([self.share, volume['name']])}
        self.nef.post(url, data)
        self._mount_volume(volume)
        data = {'export': volume['provider_location'], 'name': 'volume'}
        return {
            'driver_volume_type': self.driver_volume_type,
            'data': data,
            'mount_point_base': self.nfs_mount_point_base
        }

    def delete_volume(self, volume):
        """Deletes a logical volume.

        :param volume: volume reference
        """
        LOG.debug('Delete volume %(volume)s',
                  {'volume': volume['name']})
        path = self._get_dataset_name(volume)
        params = {'path': path}
        url = 'storage/filesystems?%s' % (
            urllib.parse.urlencode(params))
        fs_data = self.nef.get(url).get('data')
        if not fs_data:
            return
        self._unmount_volume(volume)
        params = {
            'force': 'true',
            'snapshots': 'true'
        }
        url = 'storage/filesystems/%s?%s' % (
            urllib.parse.quote_plus(path),
            urllib.parse.urlencode(params))
        try:
            self.nef.delete(url)
        except exception.NexentaException as ex:
            err = utils.ex2err(ex)
            if err['code'] == 'EEXIST':
                params = {'parent': path}
                url = 'storage/snapshots?%s' % (
                    urllib.parse.urlencode(params))
                snap_map = {}
                for snap in self.nef.get(url)['data']:
                    url = 'storage/snapshots/%s' % (
                        urllib.parse.quote_plus(snap['path']))
                    data = self.nef.get(url)
                    if data and data.get('clones'):
                        snap_map[data['creationTxg']] = snap['path']
                if snap_map:
                    snap = snap_map[max(snap_map)]
                    url = 'storage/snapshots/%s' % urllib.parse.quote_plus(
                        snap)
                    clone = self.nef.get(url)['clones'][0]
                    url = 'storage/filesystems/%s/promote' % (
                        urllib.parse.quote_plus(clone))
                    self.nef.post(url)
                params = {
                    'force': 'true',
                    'snapshots': 'true'
                }
                url = 'storage/filesystems/%s?%s' % (
                    urllib.parse.quote_plus(path),
                    urllib.parse.urlencode(params))
                self.nef.delete(url)
            else:
                raise ex

    def _delete(self, path):
        try:
            os.rmdir(path)
            LOG.debug('The mountpoint %(path)s has been successfully removed',
                      {'path': path})
        except OSError as ex:
            LOG.debug('Unable to remove mountpoint %(path)s: %(error)s',
                      {'path': path, 'error': ex.strerror})

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        LOG.info('Extending volume: %(volume)s, new size: %(size)sGB',
                 {'volume': volume['name'],
                  'size': new_size})
        self._mount_volume(volume)
        if self.sparsed_volumes:
            self._execute('truncate', '-s', '%sG' % new_size,
                          self.local_path(volume),
                          run_as_root=True)
        else:
            seek = (volume['size'] * units.Gi //
                    (BLOCK_SIZE_MB * units.Mi))
            count = ((new_size - volume['size']) * units.Gi //
                     (BLOCK_SIZE_MB * units.Mi))
            self._execute(
                'dd', 'if=/dev/zero',
                'seek=%d' % seek,
                'of=%s' % self.local_path(volume),
                'bs=%dM' % BLOCK_SIZE_MB,
                'count=%d' % count,
                run_as_root=True)
        self._unmount_volume(volume)

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        volume = self._get_snapshot_volume(snapshot)
        LOG.debug('Create snapshot %(snapshot)s for volume %(volume)s',
                  {'snapshot': snapshot['name'],
                   'volume': volume['name']})
        pool, fs = self._get_share_datasets(self.share)
        url = 'storage/snapshots'

        data = {'path': '%s@%s' % ('/'.join([pool, fs, volume['name']]),
                                   snapshot['name'])}
        self.nef.post(url, data)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: snapshot reference
        """
        LOG.debug('Delete snapshot %(snapshot)s',
                  {'snapshot': snapshot['name']})
        volume = self._get_snapshot_volume(snapshot)
        path = '%s@%s' % (self._get_dataset_name(volume),
                          snapshot['name'])
        params = {'path': path}
        url = 'storage/snapshots?%s' % urllib.parse.urlencode(params)
        snap_data = self.nef.get(url).get('data')
        if not snap_data:
            return
        params = {'defer': 'true'}
        url = 'storage/snapshots/%s?%s' % (
            urllib.parse.quote_plus(path),
            urllib.parse.urlencode(params))
        self.nef.delete(url)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        LOG.debug('Create volume %(volume)s from snapshot %(snapshot)s',
                  {'volume': volume['name'],
                   'snapshot': snapshot['name']})
        snapshot_vol = self._get_snapshot_volume(snapshot)
        volume['provider_location'] = '%s:/%s/%s' % (
            self.nas_host, self.share, volume['name'])
        pool, fs = self._get_share_datasets(self.share)
        fs_path = '%2F'.join([pool, fs, snapshot_vol['name']])
        url = ('storage/snapshots/%s/clone') % (
            '@'.join([fs_path, snapshot['name']]))
        path = '/'.join([pool, fs, volume['name']])
        data = {'targetPath': path}
        self.nef.post(url, data)

        self.nef.post(
            'storage/filesystems/%s/unmount' % urllib.parse.quote_plus(path))
        self.nef.post(
            'storage/filesystems/%s/mount' % urllib.parse.quote_plus(path))
        dataset_path = '%s/%s' % (pool, fs)
        try:
            self._share_folder(fs, volume['name'])

        except exception.NexentaException as ex:
            try:
                url = ('storage/filesystems/') % (
                    '%2F'.join([pool, fs, volume['name']]))
                self.nef.delete(url)
            except exception.NexentaException:
                LOG.warning('Cannot destroy cloned filesystem: '
                            '%(volume)s/%(filesystem)s',
                            {'volume': dataset_path,
                             'filesystem': volume['name']})
            raise ex
        if volume['size'] > snapshot['volume_size']:
            new_size = volume['size']
            volume['size'] = snapshot['volume_size']
            self.extend_volume(volume, new_size)
            volume['size'] = new_size
        return {'provider_location': volume['provider_location']}

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        snapshot = {'volume_name': src_vref['name'],
                    'volume_id': src_vref['id'],
                    'volume_size': src_vref['size'],
                    'name': self._get_clone_snapshot_name(volume)}
        LOG.debug('Create temporary snapshot %(snapshot)s '
                  'for the original volume %(volume)s',
                  {'snapshot': snapshot['name'],
                   'volume': snapshot['volume_name']})
        self.create_snapshot(snapshot)
        try:
            pl = self.create_volume_from_snapshot(volume, snapshot)
            return pl
        except exception.NexentaException as ex:
            LOG.debug('Volume creation failed, deleting temporary '
                      'snapshot %(volume)s@%(snapshot)s',
                      {'volume': snapshot['volume_name'],
                       'snapshot': snapshot['name']})
            try:
                self.delete_snapshot(snapshot)
            except (exception.NexentaException, exception.SnapshotIsBusy):
                LOG.debug('Failed to delete temporary snapshot '
                          '%(volume)s@%(snapshot)s',
                          {'volume': snapshot['volume_name'],
                           'snapshot': snapshot['name']})
            raise ex

    def _get_share_path(self, nas_host, share, volume_name):
        url = 'storage/filesystems/%s' % urllib.parse.quote_plus(
            '%s/%s' % (share, volume_name))
        return '%s:%s' % (nas_host, self.nef.get(url)['mountPoint'])

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume.

        :param volume: volume reference
        """
        share_path = self._get_share_path(
            self.nas_host, self.share, volume['name'])
        return os.path.join(self._get_mount_point_for_share(share_path),
                            'volume')

    def _get_mount_point_for_share(self, nfs_share):
        """Returns path to mount point NFS share.

        :param nfs_share: example 172.18.194.100:/var/nfs
        """
        nfs_share = nfs_share.encode('utf-8')
        return os.path.join(self.configuration.nexenta_mount_point_base,
                            hashlib.md5(nfs_share).hexdigest())

    def _share_folder(self, path, filesystem):
        """Share NFS filesystem on NexentaStor Appliance.

        :param path: path to parent filesystem
        :param filesystem: filesystem that needs to be shared
        """
        pool = self.share.split('/')[0]
        LOG.debug('Creating ACL for filesystem %(filesystem)s',
                  {'filesystem': filesystem})
        url = 'storage/filesystems/%s/acl' % (
            '%2F'.join([pool, urllib.parse.quote_plus(path), filesystem]))
        data = {
            "type": "allow",
            "principal": "everyone@",
            "permissions": [
                "list_directory",
                "read_data",
                "add_file",
                "write_data",
                "add_subdirectory",
                "append_data",
                "read_xattr",
                "write_xattr",
                "execute",
                "delete_child",
                "read_attributes",
                "write_attributes",
                "delete",
                "read_acl",
                "write_acl",
                "write_owner",
                "synchronize"
            ],
            "flags": [
                "file_inherit",
                "dir_inherit"
            ]
        }
        self.nef.post(url, data)
        LOG.debug('Successfully shared filesystem %(path)s/%(filesystem)s',
                  {'path': path,
                   'filesystem': filesystem})

    def _get_capacity_info(self, path):
        """Calculate available space on the NFS share.

        :param path: example pool/nfs
        """
        pool, fs = self._get_share_datasets(path)
        url = 'storage/filesystems/%s' % '%2F'.join([pool, fs])
        data = self.nef.get(url)
        free = utils.str2size(data['bytesAvailable'])
        allocated = utils.str2size(data['bytesUsed'])
        total = free + allocated
        return total, free, allocated

    def _get_snapshot_volume(self, snapshot):
        ctxt = context.get_admin_context()
        return db.volume_get(ctxt, snapshot['volume_id'])

    def _get_share_datasets(self, nfs_share):
        pool_name, fs = nfs_share.split('/', 1)
        return pool_name, urllib.parse.quote_plus(fs)

    def _get_dataset_name(self, volume):
        """Returns ZFS dataset name for a volume."""
        return '%s/%s' % (self.share, volume['name'])

    def _get_clone_snapshot_name(self, volume):
        """Return name for snapshot that will be used to clone the volume."""
        return 'cinder-clone-snapshot-%(id)s' % volume

    def _is_clone_snapshot_name(self, snapshot):
        """Check if snapshot is created for cloning."""
        name = snapshot.split('@')[-1]
        return name.startswith('cinder-clone-snapshot-')

    def _update_volume_stats(self):
        """Retrieve stats info for NexentaStor appliance."""
        LOG.debug('Updating volume stats')
        total, free, allocated = self._get_capacity_info(self.share)
        total_space = utils.str2gib_size(total)
        free_space = utils.str2gib_size(free)
        share = ':/'.join([self.nas_host, self.share])

        location_info = '%(driver)s:%(share)s' % {
            'driver': self.__class__.__name__,
            'share': share
        }
        self._stats = {
            'vendor_name': 'Nexenta',
            'compression': self.dataset_compression,
            'description': self.dataset_description,
            'nef_url': self.nef_host,
            'nef_port': self.nef_port,
            'driver_version': self.VERSION,
            'storage_protocol': 'NFS',
            'sparsed_volumes': self.sparsed_volumes,
            'total_capacity_gb': total_space,
            'free_capacity_gb': free_space,
            'reserved_percentage': self.configuration.reserved_percentage,
            'QoS_support': False,
            'multiattach': True,
            'location_info': location_info,
            'volume_backend_name': self.backend_name,
            'nfs_mount_point_base': self.nfs_mount_point_base
        }
