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

import hashlib
import os

from oslo_log import log as logging
from oslo_utils import units

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils
from cinder.volume.drivers import nfs

VERSION = '1.2.0'
LOG = logging.getLogger(__name__)


@interface.volumedriver
class NexentaNfsDriver(nfs.NfsDriver):
    """Executes volume driver commands on Nexenta Appliance.

    .. code-block:: default

      Version history:
          1.0.0 - Initial driver version.
          1.1.0 - Added HTTPS support.
                  Added use of sessions for REST calls.
          1.2.0 - Support for extend volume.
                  Support for extending the volume in
                  create_volume_from_snapshot if the size of new volume
                  is larger than original volume size.

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

        self.nfs_mount_point_base = self.configuration.nexenta_mount_point_base
        self.dataset_compression = (
            self.configuration.nexenta_dataset_compression)
        self.dataset_deduplication = self.configuration.nexenta_dataset_dedup
        self.dataset_description = (
            self.configuration.nexenta_dataset_description)
        self.sparsed_volumes = self.configuration.nexenta_sparsed_volumes
        self.nef = None
        self.use_https = self.configuration.nexenta_use_https
        self.nef_host = self.configuration.nas_host
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
        self.nef = jsonrpc.NexentaJSONProxy(
            self.nef_host, self.nef_port, self.nef_user,
            self.nef_password, self.use_https)

    def check_for_setup_error(self):
        """Verify that the volume for our folder exists.

        :raise: :py:exc:`LookupError`
        """
        pool_name, fs = self._get_share_datasets(self.share)
        url = 'storage/pools/%s' % pool_name
        self.nef.get(url)
        url = 'storage/pools/%s/filesystems/%s' % (
            pool_name, self._escape_path(fs))
        self.nef.get(url)

        shared = False
        response = self.nef.get('nas/nfs')
        for share in response['data']:
            if share.get('filesystem') == self.share:
                shared = True
                break
        if not shared:
            raise LookupError(_("Dataset %s is not shared in Nexenta "
                                "Store appliance") % self.share)

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        :param volume: volume reference
        :param connector: connector reference
        """
        data = {'export': volume['provider_location'], 'name': 'volume'}
        if volume['provider_location'] in self.shares:
            data['options'] = self.shares[volume['provider_location']]
        return {
            'driver_volume_type': self.driver_volume_type,
            'data': data
        }

    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume reference
        :returns: provider_location update dict for database
        """
        self._do_create_volume(volume)
        return {'provider_location': volume['provider_location']}

    def _do_create_volume(self, volume):
        pool, fs = self._get_share_datasets(self.share)
        filesystem = '%s/%s/%s' % (pool, fs, volume['name'])
        LOG.debug('Creating filesystem on NexentaStor %s', filesystem)
        url = 'storage/pools/%s/filesystems' % pool
        data = {
            'name': '/'.join([fs, volume['name']]),
            'compressionMode': self.dataset_compression,
            'dedupMode': self.dataset_deduplication,
        }
        self.nef.post(url, data)
        volume['provider_location'] = '%s:/%s/%s' % (
            self.nef_host, self.share, volume['name'])
        try:
            self._share_folder(fs, volume['name'])
            self._ensure_share_mounted('%s:/%s/%s' % (
                self.nef_host, self.share, volume['name']))

            volume_size = volume['size']
            if getattr(self.configuration,
                       self.driver_prefix + '_sparsed_volumes'):
                self._create_sparsed_file(self.local_path(volume), volume_size)
            else:
                url = 'storage/pools/%s/filesystems/%s' % (
                    pool, '%2F'.join([self._escape_path(fs), volume['name']]))
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

        except exception.NexentaException:
            try:
                url = 'storage/pools/%s/filesystems/%s' % (
                    pool, '%2F'.join([self._escape_path(fs), volume['name']]))
                self.nef.delete(url)
            except exception.NexentaException:
                LOG.warning("Cannot destroy created folder: "
                            "%(vol)s/%(folder)s",
                            {'vol': pool, 'folder': '/'.join(
                                [fs, volume['name']])})
            raise

    def delete_volume(self, volume):
        """Deletes a logical volume.

        :param volume: volume reference
        """
        pool, fs_ = self._get_share_datasets(self.share)
        fs = self._escape_path(fs_)
        url = ('storage/pools/%(pool)s/filesystems/%(fs)s') % {
            'pool': pool,
            'fs': '%2F'.join([fs, volume['name']])
        }
        origin = self.nef.get(url).get('originalSnapshot')
        url = ('storage/pools/%(pool)s/filesystems/'
               '%(fs)s?snapshots=true') % {
            'pool': pool,
            'fs': '%2F'.join([fs, volume['name']])
        }
        try:
            self.nef.delete(url)
        except exception.NexentaException as exc:
            if 'Failed to destroy snapshot' in exc.args[0]:
                LOG.debug('Snapshot has dependent clones, skipping')
            else:
                raise
        try:
            if origin and self._is_clone_snapshot_name(origin):
                path, snap = origin.split('@')
                pool, fs = path.split('/', 1)
                snap_url = ('storage/pools/%(pool)s/'
                            'filesystems/%(fs)s/snapshots/%(snap)s') % {
                    'pool': pool,
                    'fs': fs,
                    'snap': snap
                }
                self.nef.delete(snap_url)
        except exception.NexentaException as exc:
            if 'does not exist' in exc.args[0]:
                LOG.debug(
                    'Volume %s does not exist on appliance', '/'.join(
                        [pool, fs_]))

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        LOG.info('Extending volume: %(id)s New size: %(size)s GB',
                 {'id': volume['id'], 'size': new_size})
        if self.sparsed_volumes:
            self._execute('truncate', '-s', '%sG' % new_size,
                          self.local_path(volume),
                          run_as_root=self._execute_as_root)
        else:
            block_size_mb = 1
            block_count = ((new_size - volume['size']) * units.Gi //
                           (block_size_mb * units.Mi))
            self._execute(
                'dd', 'if=/dev/zero',
                'seek=%d' % (volume['size'] * units.Gi / block_size_mb),
                'of=%s' % self.local_path(volume),
                'bs=%dM' % block_size_mb,
                'count=%d' % block_count,
                run_as_root=True)

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        volume = self._get_snapshot_volume(snapshot)
        pool, fs = self._get_share_datasets(self.share)
        url = 'storage/pools/%(pool)s/filesystems/%(fs)s/snapshots' % {
            'pool': pool,
            'fs': self._escape_path('/'.join([fs, volume['name']])),
        }
        data = {'name': snapshot['name']}
        self.nef.post(url, data)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: snapshot reference
        """
        volume = self._get_snapshot_volume(snapshot)
        pool, fs = self._get_share_datasets(self.share)
        url = ('storage/pools/%(pool)s/'
               'filesystems/%(fs)s/snapshots/%(snap)s') % {
            'pool': pool,
            'fs': self._escape_path('/'.join([fs, volume['name']])),
            'snap': snapshot['name']
        }
        try:
            self.nef.delete(url)
        except exception.NexentaException as exc:
            if 'EBUSY' is exc:
                LOG.warning(
                    'Could not delete snapshot %s - it has dependencies',
                    snapshot['name'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        snapshot_vol = self._get_snapshot_volume(snapshot)
        volume['provider_location'] = snapshot_vol['provider_location']

        pool, fs = self._get_share_datasets(self.share)
        dataset_path = '%s/%s' % (pool, fs)
        url = ('storage/pools/%(pool)s/'
               'filesystems/%(fs)s/snapshots/%(snap)s/clone') % {
            'pool': pool,
            'fs': self._escape_path('/'.join([fs, snapshot_vol['name']])),
            'snap': snapshot['name']
        }
        path = '/'.join([pool, fs, volume['name']])
        data = {'targetPath': path}
        self.nef.post(url, data)

        try:
            self._share_folder(fs, volume['name'])
        except exception.NexentaException:
            try:
                url = ('storage/pools/%(pool)s/'
                       'filesystems/%(fs)s') % {
                    'pool': pool,
                    'fs': self._escape_path('/'.join([fs, volume['name']]))
                }
                self.nef.delete(url)
            except exception.NexentaException:
                LOG.warning("Cannot destroy cloned filesystem: "
                            "%(vol)s/%(filesystem)s",
                            {'vol': dataset_path,
                             'filesystem': volume['name']})
            raise
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
        LOG.info('Creating clone of volume: %s', src_vref['id'])
        snapshot = {'volume_name': src_vref['name'],
                    'volume_id': src_vref['id'],
                    'volume_size': src_vref['size'],
                    'name': self._get_clone_snapshot_name(volume)}
        self.create_snapshot(snapshot)
        try:
            return self.create_volume_from_snapshot(volume, snapshot)
        except exception.NexentaException:
            LOG.error('Volume creation failed, deleting created snapshot '
                      '%(volume_name)s@%(name)s', snapshot)
            try:
                self.delete_snapshot(snapshot)
            except (exception.NexentaException, exception.SnapshotIsBusy):
                LOG.warning('Failed to delete zfs snapshot '
                            '%(volume_name)s@%(name)s', snapshot)
            raise

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume.

        :param volume: volume reference
        """
        nfs_share = volume['provider_location']
        return os.path.join(self._get_mount_point_for_share(nfs_share),
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

        :param nef: nef object
        :param path: path to parent filesystem
        :param filesystem: filesystem that needs to be shared
        """
        pool = self.share.split('/')[0]
        LOG.debug(
            'Creating ACL for filesystem %s on Nexenta Store', filesystem)
        url = 'storage/pools/%s/filesystems/%s/acl' % (
            pool, self._escape_path('/'.join([path, filesystem])))
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

        LOG.debug(
            'Successfully shared filesystem %s', '/'.join(
                [path, filesystem]))

    def _get_capacity_info(self, path):
        """Calculate available space on the NFS share.

        :param path: example pool/nfs
        """
        pool, fs = self._get_share_datasets(path)
        url = 'storage/pools/%s/filesystems/%s' % (
            pool, self._escape_path(fs))
        data = self.nef.get(url)
        total = utils.str2size(data['bytesAvailable'])
        allocated = utils.str2size(data['bytesUsed'])
        free = total - allocated
        return total, free, allocated

    def _get_snapshot_volume(self, snapshot):
        ctxt = context.get_admin_context()
        return db.volume_get(ctxt, snapshot['volume_id'])

    def _get_share_datasets(self, nfs_share):
        pool_name, fs = nfs_share.split('/', 1)
        return pool_name, fs

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
        share = ':/'.join([self.nef_host, self.share])
        total, free, allocated = self._get_capacity_info(self.share)
        total_space = utils.str2gib_size(total)
        free_space = utils.str2gib_size(free)

        location_info = '%(driver)s:%(share)s' % {
            'driver': self.__class__.__name__,
            'share': share
        }
        self._stats = {
            'vendor_name': 'Nexenta',
            'dedup': self.dataset_deduplication,
            'compression': self.dataset_compression,
            'description': self.dataset_description,
            'nef_url': self.nef_host,
            'driver_version': self.VERSION,
            'storage_protocol': 'NFS',
            'total_capacity_gb': total_space,
            'free_capacity_gb': free_space,
            'reserved_percentage': self.configuration.reserved_percentage,
            'QoS_support': False,
            'location_info': location_info,
            'volume_backend_name': self.backend_name,
            'nfs_mount_point_base': self.nfs_mount_point_base
        }

    def _escape_path(self, path):
        return path.replace('/', '%2F')
