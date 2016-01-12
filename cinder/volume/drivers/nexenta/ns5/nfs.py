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
"""
:mod:`nexenta.nfs` -- Driver to store volumes on NexentaStor Appliance.
=======================================================================

.. automodule:: nexenta.nfs
"""

import hashlib
import os
import re

from oslo_log import log as logging

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils
from cinder.volume.drivers import nfs

VERSION = '1.0.0'
LOG = logging.getLogger(__name__)


class NexentaNfsDriver(nfs.NfsDriver):  # pylint: disable=R0921
    """Executes volume driver commands on Nexenta Appliance.

    Version history:
        1.0.0 - Initial driver version.
    """

    driver_prefix = 'nexenta'
    volume_backend_name = 'NexentaNfsDriver'
    VERSION = VERSION

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
        self.dataset_compression = self.configuration.nexenta_dataset_compression
        self.dataset_deduplication = self.configuration.nexenta_dataset_dedup
        self.dataset_description = self.configuration.nexenta_dataset_description
        self.sparsed_volumes = self.configuration.nexenta_sparsed_volumes
        self.share2nef = {}
        self.shares = {}

    @property
    def backend_name(self):
        backend_name = None
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        if not backend_name:
            backend_name = self.__class__.__name__
        return backend_name

    def do_setup(self, context):
        super(NexentaNfsDriver, self).do_setup(context)
        self._load_shares_config(getattr(self.configuration,
                                         self.driver_prefix +
                                         '_shares_config'))

    def check_for_setup_error(self):
        """Verify that the volume for our folder exists.

        :raise: :py:exc:`LookupError`
        """
        for nfs_share in self.shares:
            nef = self.share2nef[nfs_share]
            pool_name, fs = self._get_share_datasets(nfs_share)
            url = 'storage/pools/%s' % (pool_name)
            if not nef(url):
                raise LookupError(_("Pool %s does not exist in Nexenta "
                                    "Store appliance"), pool_name)
            url = 'storage/pools/%s/filesystems/%s' % (
                pool_name, fs)
            if not nef(url):
                raise LookupError(_("filesystem %s does not exist in "
                                    "Nexenta Store appliance"), fs)

            path = '/'.join([pool_name, fs])
            shared = False
            response = nef('nas/nfs')
            for share in response['data']:
                if share.get('filesystem') == path:
                    shared = True
                    break
            if not shared:
                raise LookupError(_("Dataset %s is not shared in Nexenta "
                                    "Store appliance"), path)

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        :param volume: volume reference
        :param connector: connector reference
        """
        export = '%s/%s' % (volume['provider_location'], volume['name'])
        data = {'export': export, 'name': 'volume'}
        if volume['provider_location'] in self.shares:
            data['options'] = self.shares[volume['provider_location']]
        return {
            'driver_volume_type': self.driver_volume_type,
            'data': data
        }

    def _do_create_volume(self, volume):
        nfs_share = volume['provider_location']
        nef = self.share2nef[nfs_share]

        pool, fs = self._get_share_datasets(nfs_share)
        filesystem = '%s/%s/%s' % (pool, fs, volume['name'])
        LOG.debug('Creating filesystem on NexentaStor %s', filesystem)
        url = 'storage/pools/%s/filesystems' % pool
        data = {
            'name': '/'.join([fs, volume['name']]),
            'compressionMode': self.dataset_compression,
            'dedupMode': self.dataset_deduplication,
        }
        nef(url, data)
        try:
            path = '%s/%s' % (pool, fs)
            self._share_folder(nef, path, volume['name'])
            self._ensure_share_mounted('/'.join([nfs_share, volume['name']]))

            volume_size = volume['size']
            if getattr(self.configuration,
                       self.driver_prefix + '_sparsed_volumes'):
                self._create_sparsed_file(self.local_path(volume), volume_size)
            else:
                url = 'storage/pools/%s/filesystems/%s' % (
                    pool, '%2F'.join([fs, volume['name']]))
                compression = nef(url).get('compressionMode')
                if compression != 'off':
                    # Disable compression, because otherwise will not use space
                    # on disk.
                    nef(url, {'compressionMode': 'off'}, method='PUT')
                try:
                    self._create_regular_file(self.local_path(volume), volume_size)
                finally:
                    if compression != 'off':
                        # Backup default compression value if it was changed.
                        nef(url, {'compressionMode': compression},
                            method='PUT')

        except exception.NexentaException as exc:
            try:
                url = 'storage/pools/%s/filesystems/%s/%s' % (
                    pool, '%2F'.join([fs, volume['name']]))
                nef(url, method='DELETE')
            except exception.NexentaException:
                LOG.warning(_LW("Cannot destroy created folder: "
                                "%(vol)s/%(folder)s"),
                            {'vol': pool, 'folder': '/'.join([fs, volume['name']])})
            raise exc

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        self._ensure_shares_mounted()

        snapshot_vol = self._get_snapshot_volume(snapshot)
        nfs_share = snapshot_vol['provider_location']
        volume['provider_location'] = nfs_share
        nef = self.share2nef[nfs_share]

        pool, fs = self._get_share_datasets(nfs_share)
        dataset_path = '%s/%s' % (pool, fs)
        url = ('storage/pools/%(pool)s/'
            'filesystems/%(fs)s/snapshots/%(snap)s/clone') % {
            'pool': pool,
            'fs': '%2F'.join([fs, snapshot_vol['name']]),
            'snap': snapshot['name']
        }
        data = {'targetPath': '/'.join([pool, fs, volume['name']])}
        nef(url, data)

        try:
            self._share_folder(nef, dataset_path, volume['name'])
        except exception.NexentaException:
            try:
                url = ('storage/pools/%(pool)s/'
                       'filesystems/%(fs)s'), {
                    'pool': pool,
                    'fs': volume['name']
                }
                nef(url, method='DELETE')
            except exception.NexentaException:
                LOG.warning(_LW("Cannot destroy cloned filesystem: "
                                "%(vol)s/%(filesystem)s"),
                            {'vol': dataset_path,
                            'filesystem': volume['name']})
            raise

        return {'provider_location': volume['provider_location']}

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        LOG.info(_LI('Creating clone of volume: %s'), src_vref['id'])
        snapshot = {'volume_name': src_vref['name'],
                    'volume_id': src_vref['id'],
                    'name': self._get_clone_snapshot_name(volume)}
        # We don't delete this snapshot, because this snapshot will be origin
        # of new volume. This snapshot will be automatically promoted by nef
        # when user will delete its origin.
        self.create_snapshot(snapshot)
        try:
            return self.create_volume_from_snapshot(volume, snapshot)
        except exception.NexentaException:
            LOG.error(_LE('Volume creation failed, deleting created snapshot '
                          '%(volume_name)s@%(name)s'), snapshot)
            try:
                self.delete_snapshot(snapshot)
            except (exception.NexentaException, exception.SnapshotIsBusy):
                LOG.warning(_LW('Failed to delete zfs snapshot '
                                '%(volume_name)s@%(name)s'), snapshot)
            raise

    def delete_volume(self, volume):
        """Deletes a logical volume.

        :param volume: volume reference
        """
        super(NexentaNfsDriver, self).delete_volume(volume)

        nfs_share = volume.get('provider_location')

        if nfs_share:
            nef = self.share2nef[nfs_share]
            pool, fs = self._get_share_datasets(nfs_share)
            url = ('storage/pools/%(pool)s/filesystems/%(fs)s') % {
                'pool': pool,
                'fs': '%2F'.join([fs, volume['name']])
            }
            origin = nef(url).get('originalSnapshot')
            url = ('storage/pools/%(pool)s/filesystems/'
                '%(fs)s?snapshots=true') % {
                    'pool': pool,
                    'fs': '%2F'.join([fs, volume['name']])
                }
            nef(url, method='DELETE')
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
                    nef(snap_url, method='DELETE')
            except exception.NexentaException as exc:
                if 'does not exist' in exc:
                    LOG.debug('Volume %s does not exist on appliance', '/'.join(
                        [pool, fs]))

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        volume = self._get_snapshot_volume(snapshot)
        nfs_share = volume['provider_location']
        nef = self.share2nef[nfs_share]
        pool, fs = self._get_share_datasets(nfs_share)
        url = 'storage/pools/%(pool)s/filesystems/%(fs)s/snapshots' % {
            'pool': pool,
            'fs': '%2F'.join([fs, volume['name']]),
        }
        data = {'name': snapshot['name']}
        nef(url, data)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: snapshot reference
        """
        volume = self._get_snapshot_volume(snapshot)
        nfs_share = volume['provider_location']
        nef = self.share2nef[nfs_share]
        pool, fs = self._get_share_datasets(nfs_share)
        url = ('storage/pools/%(pool)s/'
               'filesystems/%(fs)s/snapshots/%(snap)s') % {
            'pool': pool,
            'fs': volume['name'],
            'snap': snapshot['name']
        }
        try:
            nef(url, method='DELETE')
        except exception.NexentaException as exc:
            if 'EBUSY' is exc:
                LOG.warning(_LW(
                    'Could not delete snapshot %s - it has dependencies') %
                    snapshot['name'])

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume.

        :param volume: volume reference
        """
        nfs_share = volume['provider_location']
        return os.path.join(self._get_mount_point_for_share(nfs_share),
                            volume['name'], 'volume')

    def _get_mount_point_for_share(self, nfs_share):
        """Returns path to mount point NFS share.

        :param nfs_share: example 172.18.194.100:/var/nfs
        """
        return os.path.join(self.configuration.nexenta_mount_point_base,
                            hashlib.md5(nfs_share).hexdigest())

    def remote_path(self, volume):
        """Get volume path (mounted remotely fs path) for given volume.

        :param volume: volume reference
        """
        # nfs_share = volume['provider_location']
        # path = self.share2fs[nfs_share]
        # return '%s/%s' % (path, volume['name'])
        nfs_share = volume['provider_location']
        LOG.warning(nfs_share)
        share = nfs_share.split(':')[1].rstrip('/')
        return '%s/%s/volume' % (share, volume['name'])

    def _share_folder(self, nef, path, filesystem):
        """Share NFS filesystem on NexentaStor Appliance.

        :param nef: nef object
        :param path: path to parent filesystem
        :param filesystem: filesystem that needs to be shared
        """
        # Commented code only for nfs < 4
        # LOG.debug('Sharing filesystem %s on Nexenta Store', filesystem)
        # url = 'nas/nfs'
        # data = {
        #     'filesystem': '%s/%s' % (path, filesystem),
        #     'securityContexts': [{
        #         'securityModes': ['sys'],
        #         'root': [
        #             {
        #                 'entity': '*',
        #                 'etype': 'network'
        #             }
        #         ],
        #         'readWriteList': [
        #             {
        #                 'entity': '*',
        #                 'etype': 'network'
        #             }
        #         ]
        #     }]
        # }
        # nef(url, data)

        pool = path.split('/')[0]
        LOG.debug('Creating ACL for filesystem %s on Nexenta Store', filesystem)
        url = 'storage/pools/%s/filesystems/%s/acl' % (
            pool, '%2F'.join((path.strip(pool).lstrip('/'), filesystem)))
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
        nef(url, data)

        LOG.debug('Successfully shared filesystem %s' % '/'.join([path, filesystem]))

    def _load_shares_config(self, share_file):
        for line in self._read_config_file(share_file):
            # A configuration line may be either:
            # host:/share_name  http://user:pass@host:[port]/
            # or
            # host:/share_name  http://user:pass@host:[port]/
            #    -o options=123,rw --other
            if not line.strip():
                continue
            if line.startswith('#'):
                continue

            share_info = re.split(r'\s+', line, 2)

            share_address = share_info[0].strip()   # .decode('unicode_escape')
            nef_url = share_info[1].strip()
            share_opts = share_info[2].strip() if len(share_info) > 2 else None

            if not re.match(r'.+:/.+', share_address):
                LOG.warning(_LW("Share %s ignored due to invalid format. Must "
                                "be of form address:/export.") % share_address)
                continue

            self.shares[share_address] = share_opts
            nef = self._get_nef_for_url(nef_url)
            self.share2nef[share_address] = nef

        LOG.debug('Shares loaded: %s' % self.shares)

    def _get_capacity_info(self, nfs_share):
        """Calculate available space on the NFS share.

        :param nfs_share: example 172.18.194.100:/var/nfs
        """
        nef = self.share2nef[nfs_share]
        pool, fs = self._get_share_datasets(nfs_share)
        url = 'storage/pools/%s/filesystems/%s' % (
            pool, fs)
        dataset_props = nef(url)
        free = utils.str2size(dataset_props['bytesAvailable'])
        allocated = utils.str2size(dataset_props['bytesUsed'])
        total = free + allocated
        return total, free, allocated

    def _get_nef_for_url(self, url):
        """Returns initialized nef object for url."""
        auto, scheme, user, password, host, port =\
            utils.parse_nef_url(url)
        return jsonrpc.NexentaJSONProxy(scheme, host, port, user,
                                        password, auto=auto)

    def _get_snapshot_volume(self, snapshot):
        ctxt = context.get_admin_context()
        return db.volume_get(ctxt, snapshot['volume_id'])

    def _get_share_datasets(self, nfs_share):
        path = nfs_share.split(':/')[1]
        pool_name, fs = path.split('/')
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
        total_space = 0
        free_space = 0
        shares_with_capacities = {}
        for mounted_share in self._mounted_shares:
            total, free, allocated = self._get_capacity_info(mounted_share)
            shares_with_capacities[mounted_share] = utils.str2gib_size(total)
            if total_space < utils.str2gib_size(total):
                total_space = utils.str2gib_size(total)
            if free_space < utils.str2gib_size(free):
                free_space = utils.str2gib_size(free)
                share = mounted_share

        location_info = '%(driver)s:%(share)s' % {
            'driver': self.__class__.__name__,
            'share': share
        }
        nef_url = self.share2nef[share].url
        self._stats = {
            'vendor_name': 'Nexenta',
            'dedup': self.dataset_deduplication,
            'compression': self.dataset_compression,
            'description': self.dataset_description,
            'nef_url': nef_url,
            'ns_shares': shares_with_capacities,
            'driver_version': self.VERSION,
            'storage_protocol': 'NFS',
            'total_capacity_gb': total_space,
            'free_capacity_gb': free_space,
            'reserved_percentage': 0,
            'QoS_support': False,
            'location_info': location_info,
            'volume_backend_name': self.backend_name,
            'nfs_mount_point_base': self.nfs_mount_point_base
        }
