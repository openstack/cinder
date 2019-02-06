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
import re
import six

from eventlet import greenthread
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import units

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import interface
import cinder.privsep.fs
from cinder.volume.drivers.nexenta import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils
from cinder.volume.drivers import nfs

VERSION = '1.3.1'
LOG = logging.getLogger(__name__)


@interface.volumedriver
class NexentaNfsDriver(nfs.NfsDriver):  # pylint: disable=R0921
    """Executes volume driver commands on Nexenta Appliance.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver version.
        1.1.0 - Auto sharing for enclosing folder.
        1.1.1 - Added caching for NexentaStor appliance 'volroot' value.
        1.1.2 - Ignore "folder does not exist" error in delete_volume and
                delete_snapshot method.
        1.1.3 - Redefined volume_backend_name attribute inherited from
                RemoteFsDriver.
        1.2.0 - Added migrate and retype methods.
        1.3.0 - Extend volume method.
        1.3.1 - Cache capacity info and check shared folders on setup.
    """

    driver_prefix = 'nexenta'
    volume_backend_name = 'NexentaNfsDriver'
    VERSION = VERSION
    VOLUME_FILE_NAME = 'volume'

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
            self.configuration.append_config_values(
                options.NEXENTA_RRMGR_OPTS)

        self.nms_cache_volroot = self.configuration.nexenta_nms_cache_volroot
        self.rrmgr_compression = self.configuration.nexenta_rrmgr_compression
        self.rrmgr_tcp_buf_size = self.configuration.nexenta_rrmgr_tcp_buf_size
        self.rrmgr_connections = self.configuration.nexenta_rrmgr_connections
        self.nfs_mount_point_base = self.configuration.nexenta_mount_point_base
        self.volume_compression = (
            self.configuration.nexenta_dataset_compression)
        self.volume_deduplication = self.configuration.nexenta_dataset_dedup
        self.volume_description = (
            self.configuration.nexenta_dataset_description)
        self.sparsed_volumes = self.configuration.nexenta_sparsed_volumes
        self._nms2volroot = {}
        self.share2nms = {}
        self.nfs_versions = {}
        self.shares_with_capacities = {}

    @staticmethod
    def get_driver_options():
        return (
            options.NEXENTA_CONNECTION_OPTS +
            options.NEXENTA_NFS_OPTS +
            options.NEXENTA_DATASET_OPTS +
            options.NEXENTA_RRMGR_OPTS
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
        shares_config = getattr(self.configuration, self.driver_prefix +
                                '_shares_config')
        if shares_config:
            self.configuration.nfs_shares_config = shares_config
        super(NexentaNfsDriver, self).do_setup(context)
        self._load_shares_config(shares_config)
        self._mount_subfolders()

    def check_for_setup_error(self):
        """Verify that the volume for our folder exists.

        :raise: :py:exc:`LookupError`
        """
        if self.share2nms:
            for nfs_share in self.share2nms:
                nms = self.share2nms[nfs_share]
                volume_name, dataset = self._get_share_datasets(nfs_share)
                if not nms.volume.object_exists(volume_name):
                    raise LookupError(_("Volume %s does not exist in Nexenta "
                                        "Store appliance"), volume_name)
                folder = '%s/%s' % (volume_name, dataset)
                if not nms.folder.object_exists(folder):
                    raise LookupError(_("Folder %s does not exist in Nexenta "
                                        "Store appliance"), folder)
                if (folder not in nms.netstorsvc.get_shared_folders(
                        'svc:/network/nfs/server:default', '')):
                    self._share_folder(nms, volume_name, dataset)
                self._get_capacity_info(nfs_share)

    def migrate_volume(self, ctxt, volume, host):
        """Migrate if volume and host are managed by Nexenta appliance.

        :param ctxt: context
        :param volume: a dictionary describing the volume to migrate
        :param host: a dictionary describing the host to migrate to
        """
        LOG.debug('Enter: migrate_volume: id=%(id)s, host=%(host)s',
                  {'id': volume['id'], 'host': host})

        false_ret = (False, None)

        if volume['status'] not in ('available', 'retyping'):
            LOG.warning("Volume status must be 'available' or 'retyping'."
                        " Current volume status: %s", volume['status'])
            return false_ret

        if 'capabilities' not in host:
            LOG.warning("Unsupported host. No capabilities found")
            return false_ret

        capabilities = host['capabilities']
        ns_shares = capabilities['ns_shares']
        dst_parts = capabilities['location_info'].split(':')
        dst_host, dst_volume = dst_parts[1:]

        if (capabilities.get('vendor_name') != 'Nexenta' or
                dst_parts[0] != self.__class__.__name__ or
                capabilities['free_capacity_gb'] < volume['size']):
            return false_ret

        nms = self.share2nms[volume['provider_location']]
        ssh_bindings = nms.appliance.ssh_list_bindings()
        shares = []
        for bind in ssh_bindings:
            for share in ns_shares:
                if (share.startswith(ssh_bindings[bind][3]) and
                        ns_shares[share] >= volume['size']):
                    shares.append(share)
        if len(shares) == 0:
            LOG.warning("Remote NexentaStor appliance at %s should be "
                        "SSH-bound.", share)
            return false_ret
        share = sorted(shares, key=ns_shares.get, reverse=True)[0]
        snapshot = {
            'volume_name': volume['name'],
            'volume_id': volume['id'],
            'name': utils.get_migrate_snapshot_name(volume)
        }
        self.create_snapshot(snapshot)
        location = volume['provider_location']
        src = '%(share)s/%(volume)s@%(snapshot)s' % {
            'share': location.split(':')[1].split('volumes/')[1],
            'volume': volume['name'],
            'snapshot': snapshot['name']
        }
        dst = ':'.join([dst_host, dst_volume.split('/volumes/')[1]])
        try:
            nms.appliance.execute(self._get_zfs_send_recv_cmd(src, dst))
        except exception.NexentaException as exc:
            LOG.warning("Cannot send source snapshot %(src)s to "
                        "destination %(dst)s. Reason: %(exc)s",
                        {'src': src, 'dst': dst, 'exc': exc})
            return false_ret
        finally:
            try:
                self.delete_snapshot(snapshot)
            except exception.NexentaException as exc:
                LOG.warning("Cannot delete temporary source snapshot "
                            "%(src)s on NexentaStor Appliance: %(exc)s",
                            {'src': src, 'exc': exc})
        try:
            self.delete_volume(volume)
        except exception.NexentaException as exc:
            LOG.warning("Cannot delete source volume %(volume)s on "
                        "NexentaStor Appliance: %(exc)s",
                        {'volume': volume['name'], 'exc': exc})

        dst_nms = self._get_nms_for_url(capabilities['nms_url'])
        dst_snapshot = '%s/%s@%s' % (dst_volume.split('volumes/')[1],
                                     volume['name'], snapshot['name'])
        try:
            dst_nms.snapshot.destroy(dst_snapshot, '')
        except exception.NexentaException as exc:
            LOG.warning("Cannot delete temporary destination snapshot "
                        "%(dst)s on NexentaStor Appliance: %(exc)s",
                        {'dst': dst_snapshot, 'exc': exc})
        return True, {'provider_location': share}

    def _get_zfs_send_recv_cmd(self, src, dst):
        """Returns rrmgr command for source and destination."""
        return utils.get_rrmgr_cmd(src, dst,
                                   compression=self.rrmgr_compression,
                                   tcp_buf_size=self.rrmgr_tcp_buf_size,
                                   connections=self.rrmgr_connections)

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

    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        :param context: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug('Retype volume request %(vol)s to be %(type)s '
                  '(host: %(host)s), diff %(diff)s.',
                  {'vol': volume['name'],
                   'type': new_type,
                   'host': host,
                   'diff': diff})

        options = dict(
            compression='compression',
            dedup='dedup',
            description='nms:description'
        )

        retyped = False
        migrated = False
        model_update = None

        src_backend = self.__class__.__name__
        dst_backend = host['capabilities']['location_info'].split(':')[0]
        if src_backend != dst_backend:
            LOG.warning('Cannot retype from %(src_backend)s to '
                        '%(dst_backend)s.',
                        {'src_backend': src_backend,
                         'dst_backend': dst_backend})
            return False

        hosts = (volume['host'], host['host'])
        old, new = hosts
        if old != new:
            migrated, provider_location = self.migrate_volume(
                context, volume, host)

        if not migrated:
            provider_location = volume['provider_location']
            nms = self.share2nms[provider_location]
        else:
            nms_url = host['capabilities']['nms_url']
            nms = self._get_nms_for_url(nms_url)
            model_update = provider_location
            provider_location = provider_location['provider_location']

        share = provider_location.split(':')[1].split('volumes/')[1]
        folder = '%(share)s/%(volume)s' % {
            'share': share,
            'volume': volume['name']
        }

        for opt in options:
            old, new = diff.get('extra_specs').get(opt, (False, False))
            if old != new:
                LOG.debug('Changing %(opt)s from %(old)s to %(new)s.',
                          {'opt': opt, 'old': old, 'new': new})
                try:
                    nms.folder.set_child_prop(
                        folder, options[opt], new)
                    retyped = True
                except exception.NexentaException:
                    LOG.error('Error trying to change %(opt)s'
                              ' from %(old)s to %(new)s',
                              {'opt': opt, 'old': old, 'new': new})
                    return False, None
        return retyped or migrated, model_update

    def _do_create_volume(self, volume):
        nfs_share = volume['provider_location']
        nms = self.share2nms[nfs_share]

        vol, dataset = self._get_share_datasets(nfs_share)
        folder = '%s/%s' % (dataset, volume['name'])
        LOG.debug('Creating folder on Nexenta Store %s', folder)
        nms.folder.create_with_props(
            vol, folder,
            {'compression': self.configuration.nexenta_dataset_compression}
        )

        volume_path = self.remote_path(volume)
        volume_size = volume['size']
        try:
            self._share_folder(nms, vol, folder)

            if getattr(self.configuration,
                       self.driver_prefix + '_sparsed_volumes'):
                self._create_sparsed_file(nms, volume_path, volume_size)
            else:
                folder_path = '%s/%s' % (vol, folder)
                compression = nms.folder.get_child_prop(
                    folder_path, 'compression')
                if compression != 'off':
                    # Disable compression, because otherwise will not use space
                    # on disk.
                    nms.folder.set_child_prop(
                        folder_path, 'compression', 'off')
                try:
                    self._create_regular_file(nms, volume_path, volume_size)
                finally:
                    if compression != 'off':
                        # Backup default compression value if it was changed.
                        nms.folder.set_child_prop(
                            folder_path, 'compression', compression)

            self._set_rw_permissions_for_all(nms, volume_path)

            if self._get_nfs_server_version(nfs_share) < 4:
                sub_share, mnt_path = self._get_subshare_mount_point(nfs_share,
                                                                     volume)
                self._ensure_share_mounted(sub_share, mnt_path)
            self._get_capacity_info(nfs_share)
        except exception.NexentaException:
            try:
                nms.folder.destroy('%s/%s' % (vol, folder))
            except exception.NexentaException:
                LOG.warning("Cannot destroy created folder: "
                            "%(vol)s/%(folder)s",
                            {'vol': vol, 'folder': folder})
            raise

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        self._ensure_shares_mounted()

        snapshot_vol = self._get_snapshot_volume(snapshot)
        nfs_share = snapshot_vol['provider_location']
        volume['provider_location'] = nfs_share
        nms = self.share2nms[nfs_share]

        vol, dataset = self._get_share_datasets(nfs_share)
        snapshot_name = '%s/%s/%s@%s' % (vol, dataset, snapshot['volume_name'],
                                         snapshot['name'])
        folder = '%s/%s' % (dataset, volume['name'])
        nms.folder.clone(snapshot_name, '%s/%s' % (vol, folder))

        try:
            self._share_folder(nms, vol, folder)
        except exception.NexentaException:
            try:
                nms.folder.destroy('%s/%s' % (vol, folder), '')
            except exception.NexentaException:
                LOG.warning("Cannot destroy cloned folder: "
                            "%(vol)s/%(folder)s",
                            {'vol': vol, 'folder': folder})
            raise

        if self._get_nfs_server_version(nfs_share) < 4:
            sub_share, mnt_path = self._get_subshare_mount_point(nfs_share,
                                                                 volume)
            self._ensure_share_mounted(sub_share, mnt_path)

        if (('size' in volume) and (
                volume['size'] > snapshot['volume_size'])):
            self.extend_volume(volume, volume['size'])

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
        # We don't delete this snapshot, because this snapshot will be origin
        # of new volume. This snapshot will be automatically promoted by NMS
        # when user will delete its origin.
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

    def delete_volume(self, volume):
        """Deletes a logical volume.

        :param volume: volume reference
        """
        nfs_share = volume.get('provider_location')
        if nfs_share:
            nms = self.share2nms[nfs_share]
            vol, parent_folder = self._get_share_datasets(nfs_share)
            folder = '%s/%s/%s' % (vol, parent_folder, volume['name'])
            mount_path = self.remote_path(volume).strip(
                '/%s' % self.VOLUME_FILE_NAME)
            if mount_path in self._remotefsclient._read_mounts():
                cinder.privsep.fs.umount(mount_path)
            try:
                props = nms.folder.get_child_props(folder, 'origin') or {}
                nms.folder.destroy(folder, '-r')
            except exception.NexentaException as exc:
                if 'does not exist' in exc.args[0]:
                    LOG.info('Folder %s does not exist, it was '
                             'already deleted.', folder)
                    return
                raise
            self._get_capacity_info(nfs_share)
            origin = props.get('origin')
            if origin and self._is_clone_snapshot_name(origin):
                try:
                    nms.snapshot.destroy(origin, '')
                except exception.NexentaException as exc:
                    if 'does not exist' in exc.args[0]:
                        LOG.info('Snapshot %s does not exist, it was '
                                 'already deleted.', origin)
                        return
                    raise

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """
        LOG.info('Extending volume: %(id)s New size: %(size)s GB',
                 {'id': volume['id'], 'size': new_size})
        nfs_share = volume['provider_location']
        nms = self.share2nms[nfs_share]
        volume_path = self.remote_path(volume)
        if getattr(self.configuration,
                   self.driver_prefix + '_sparsed_volumes'):
            self._create_sparsed_file(nms, volume_path, new_size)
        else:
            block_size_mb = 1
            block_count = ((new_size - volume['size']) * units.Gi /
                           (block_size_mb * units.Mi))

            nms.appliance.execute(
                'dd if=/dev/zero seek=%(seek)d of=%(path)s'
                ' bs=%(bs)dM count=%(count)d' % {
                    'seek': volume['size'] * units.Gi / block_size_mb,
                    'path': volume_path,
                    'bs': block_size_mb,
                    'count': block_count
                }
            )

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: snapshot reference
        """
        volume = self._get_snapshot_volume(snapshot)
        nfs_share = volume['provider_location']
        nms = self.share2nms[nfs_share]
        vol, dataset = self._get_share_datasets(nfs_share)
        folder = '%s/%s/%s' % (vol, dataset, volume['name'])
        nms.folder.create_snapshot(folder, snapshot['name'], '-r')

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: snapshot reference
        """
        volume = self._get_snapshot_volume(snapshot)
        nfs_share = volume['provider_location']
        nms = self.share2nms[nfs_share]
        vol, dataset = self._get_share_datasets(nfs_share)
        folder = '%s/%s/%s' % (vol, dataset, volume['name'])
        try:
            nms.snapshot.destroy('%s@%s' % (folder, snapshot['name']), '')
        except exception.NexentaException as exc:
            if 'does not exist' in exc.args[0]:
                LOG.info('Snapshot %(folder)s@%(snapshot)s does not '
                         'exist, it was already deleted.',
                         {'folder': folder,
                          'snapshot': snapshot})
                return
            elif 'has dependent clones' in exc.args[0]:
                LOG.info('Snapshot %(folder)s@%(snapshot)s has dependent '
                         'clones, it will be deleted later.',
                         {'folder': folder,
                          'snapshot': snapshot})
                return

    def _create_sparsed_file(self, nms, path, size):
        """Creates file with 0 disk usage.

        :param nms: nms object
        :param path: path to new file
        :param size: size of file
        """
        nms.appliance.execute(
            'truncate --size %(size)dG %(path)s' % {
                'path': path,
                'size': size
            }
        )

    def _create_regular_file(self, nms, path, size):
        """Creates regular file of given size.

        Takes a lot of time for large files.

        :param nms: nms object
        :param path: path to new file
        :param size: size of file
        """
        block_size_mb = 1
        block_count = size * units.Gi / (block_size_mb * units.Mi)

        LOG.info('Creating regular file: %s.'
                 'This may take some time.', path)

        nms.appliance.execute(
            'dd if=/dev/zero of=%(path)s bs=%(bs)dM count=%(count)d' % {
                'path': path,
                'bs': block_size_mb,
                'count': block_count
            }
        )

        LOG.info('Regular file: %s created.', path)

    def _set_rw_permissions_for_all(self, nms, path):
        """Sets 666 permissions for the path.

        :param nms: nms object
        :param path: path to file
        """
        nms.appliance.execute('chmod ugo+rw %s' % path)

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
        nfs_share = nfs_share.encode('utf-8')
        return os.path.join(self.configuration.nexenta_mount_point_base,
                            hashlib.md5(nfs_share).hexdigest())

    def remote_path(self, volume):
        """Get volume path (mounted remotely fs path) for given volume.

        :param volume: volume reference
        """
        nfs_share = volume['provider_location']
        share = nfs_share.split(':')[1].rstrip('/')
        return '%s/%s/volume' % (share, volume['name'])

    def _share_folder(self, nms, volume, folder):
        """Share NFS folder on NexentaStor Appliance.

        :param nms: nms object
        :param volume: volume name
        :param folder: folder name
        """
        path = '%s/%s' % (volume, folder.lstrip('/'))
        share_opts = {
            'read_write': '*',
            'read_only': '',
            'root': 'nobody',
            'extra_options': 'anon=0',
            'recursive': 'true',
            'anonymous_rw': 'true',
        }
        LOG.debug('Sharing folder %s on Nexenta Store', folder)
        nms.netstorsvc.share_folder('svc:/network/nfs/server:default', path,
                                    share_opts)

    def _load_shares_config(self, share_file):
        self.shares = {}
        self.share2nms = {}

        for share in self._read_config_file(share_file):
            # A configuration line may be either:
            # host:/share_name  http://user:pass@host:[port]/
            # or
            # host:/share_name  http://user:pass@host:[port]/
            #    -o options=123,rw --other
            if not share.strip():
                continue
            if share.startswith('#'):
                continue

            share_info = re.split(r'\s+', share, 2)

            share_address = share_info[0].strip()
            nms_url = share_info[1].strip()
            share_opts = share_info[2].strip() if len(share_info) > 2 else None

            if not re.match(r'.+:/.+', share_address):
                LOG.warning("Share %s ignored due to invalid format. "
                            "Must be of form address:/export.",
                            share_address)
                continue

            self.shares[share_address] = share_opts
            self.share2nms[share_address] = self._get_nms_for_url(nms_url)

        LOG.debug('Shares loaded: %s', self.shares)

    def _get_subshare_mount_point(self, nfs_share, volume):
        mnt_path = '%s/%s' % (
            self._get_mount_point_for_share(nfs_share), volume['name'])
        sub_share = '%s/%s' % (nfs_share, volume['name'])
        return sub_share, mnt_path

    def _ensure_share_mounted(self, nfs_share, mount_path=None):
        """Ensure that NFS share is mounted on the host.

        Unlike the parent method this one accepts mount_path as an optional
        parameter and uses it as a mount point if provided.

        :param nfs_share: NFS share name
        :param mount_path: mount path on the host
        """
        mnt_flags = []
        if self.shares.get(nfs_share) is not None:
            mnt_flags = self.shares[nfs_share].split()
        num_attempts = max(1, self.configuration.nfs_mount_attempts)
        for attempt in range(num_attempts):
            try:
                if mount_path is None:
                    self._remotefsclient.mount(nfs_share, mnt_flags)
                else:
                    if mount_path in self._remotefsclient._read_mounts():
                        LOG.info('Already mounted: %s', mount_path)
                        return

                    fileutils.ensure_tree(mount_path)
                    self._remotefsclient._mount_nfs(nfs_share, mount_path,
                                                    mnt_flags)
                return
            except Exception as e:
                if attempt == (num_attempts - 1):
                    LOG.error('Mount failure for %(share)s after '
                              '%(count)d attempts.',
                              {'share': nfs_share,
                               'count': num_attempts})
                    raise exception.NfsException(six.text_type(e))
                LOG.warning(
                    'Mount attempt %(attempt)d failed: %(error)s. '
                    'Retrying mount ...',
                    {'attempt': attempt, 'error': e})
                greenthread.sleep(1)

    def _mount_subfolders(self):
        ctxt = context.get_admin_context()
        vol_entries = self.db.volume_get_all_by_host(ctxt, self.host)
        for vol in vol_entries:
            nfs_share = vol['provider_location']
            if ((nfs_share in self.shares) and
                    (self._get_nfs_server_version(nfs_share) < 4)):
                sub_share, mnt_path = self._get_subshare_mount_point(
                    nfs_share, vol)
                self._ensure_share_mounted(sub_share, mnt_path)

    def _get_nfs_server_version(self, share):
        if not self.nfs_versions.get(share):
            nms = self.share2nms[share]
            nfs_opts = nms.netsvc.get_confopts(
                'svc:/network/nfs/server:default', 'configure')
            try:
                self.nfs_versions[share] = int(
                    nfs_opts['nfs_server_versmax']['current'])
            except KeyError:
                self.nfs_versions[share] = int(
                    nfs_opts['server_versmax']['current'])
        return self.nfs_versions[share]

    def _get_capacity_info(self, nfs_share):
        """Calculate available space on the NFS share.

        :param nfs_share: example 172.18.194.100:/var/nfs
        """
        nms = self.share2nms[nfs_share]
        ns_volume, ns_folder = self._get_share_datasets(nfs_share)
        folder_props = nms.folder.get_child_props('%s/%s' % (ns_volume,
                                                             ns_folder),
                                                  'used|available')
        free = utils.str2size(folder_props['available'])
        allocated = utils.str2size(folder_props['used'])
        self.shares_with_capacities[nfs_share] = {
            'free': utils.str2gib_size(free),
            'total': utils.str2gib_size(free + allocated)}
        return free + allocated, free, allocated

    def _get_nms_for_url(self, url):
        """Returns initialized nms object for url."""
        auto, scheme, user, password, host, port, path = (
            utils.parse_nms_url(url))
        return jsonrpc.NexentaJSONProxy(scheme, host, port, path, user,
                                        password, auto=auto)

    def _get_snapshot_volume(self, snapshot):
        ctxt = context.get_admin_context()
        return db.volume_get(ctxt, snapshot['volume_id'])

    def _get_volroot(self, nms):
        """Returns volroot property value from NexentaStor appliance."""
        if not self.nms_cache_volroot:
            return nms.server.get_prop('volroot')
        if nms not in self._nms2volroot:
            self._nms2volroot[nms] = nms.server.get_prop('volroot')
        return self._nms2volroot[nms]

    def _get_share_datasets(self, nfs_share):
        nms = self.share2nms[nfs_share]
        volroot = self._get_volroot(nms)
        path = nfs_share.split(':')[1][len(volroot):].strip('/')
        volume_name = path.split('/')[0]
        folder_name = '/'.join(path.split('/')[1:])
        return volume_name, folder_name

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
        share = None
        for _share in self._mounted_shares:
            if self.shares_with_capacities[_share]['free'] > free_space:
                free_space = self.shares_with_capacities[_share]['free']
                total_space = self.shares_with_capacities[_share]['total']
                share = _share

        location_info = '%(driver)s:%(share)s' % {
            'driver': self.__class__.__name__,
            'share': share
        }
        nms_url = self.share2nms[share].url
        self._stats = {
            'vendor_name': 'Nexenta',
            'dedup': self.volume_deduplication,
            'compression': self.volume_compression,
            'description': self.volume_description,
            'nms_url': nms_url,
            'ns_shares': self.shares_with_capacities,
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
