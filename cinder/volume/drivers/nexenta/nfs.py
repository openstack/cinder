# Copyright 2013 Nexenta Systems, Inc.
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
.. moduleauthor:: Mikhail Khodos <hodosmb@gmail.com>
.. moduleauthor:: Victor Rodionov <victor.rodionov@nexenta.com>
"""

import hashlib
import os
import re

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import units
from cinder.volume.drivers import nexenta
from cinder.volume.drivers.nexenta import jsonrpc
from cinder.volume.drivers.nexenta import options
from cinder.volume.drivers.nexenta import utils
from cinder.volume.drivers import nfs

VERSION = '1.1.3'
LOG = logging.getLogger(__name__)


class NexentaNfsDriver(nfs.NfsDriver):  # pylint: disable=R0921
    """Executes volume driver commands on Nexenta Appliance.

    Version history:
        1.0.0 - Initial driver version.
        1.1.0 - Auto sharing for enclosing folder.
        1.1.1 - Added caching for NexentaStor appliance 'volroot' value.
        1.1.2 - Ignore "folder does not exist" error in delete_volume and
                delete_snapshot method.
        1.1.3 - Redefined volume_backend_name attribute inherited from
                RemoteFsDriver.
    """

    driver_prefix = 'nexenta'
    volume_backend_name = 'NexentaNfsDriver'
    VERSION = VERSION

    def __init__(self, *args, **kwargs):
        super(NexentaNfsDriver, self).__init__(*args, **kwargs)
        if self.configuration:
            self.configuration.append_config_values(
                options.NEXENTA_NFS_OPTIONS)
        conf = self.configuration
        self.nms_cache_volroot = conf.nexenta_nms_cache_volroot
        self._nms2volroot = {}
        self.share2nms = {}

    def do_setup(self, context):
        super(NexentaNfsDriver, self).do_setup(context)
        self._load_shares_config(getattr(self.configuration,
                                         self.driver_prefix +
                                         '_shares_config'))

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
                self._share_folder(nms, volume_name, dataset)

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
        nms = self.share2nms[nfs_share]

        vol, dataset = self._get_share_datasets(nfs_share)
        folder = '%s/%s' % (dataset, volume['name'])
        LOG.debug('Creating folder on Nexenta Store %s', folder)
        nms.folder.create_with_props(
            vol, folder,
            {'compression': self.configuration.nexenta_volume_compression}
        )

        volume_path = self.remote_path(volume)
        volume_size = volume['size']
        try:
            self._share_folder(nms, vol, folder)

            if getattr(self.configuration,
                       self.driver_prefix + '_sparsed_volumes'):
                self._create_sparsed_file(nms, volume_path, volume_size)
            else:
                compression = nms.folder.get('compression')
                if compression != 'off':
                    # Disable compression, because otherwise will not use space
                    # on disk.
                    nms.folder.set('compression', 'off')
                try:
                    self._create_regular_file(nms, volume_path, volume_size)
                finally:
                    if compression != 'off':
                        # Backup default compression value if it was changed.
                        nms.folder.set('compression', compression)

            self._set_rw_permissions_for_all(nms, volume_path)
        except nexenta.NexentaException as exc:
            try:
                nms.folder.destroy('%s/%s' % (vol, folder))
            except nexenta.NexentaException:
                LOG.warning(_("Cannot destroy created folder: "
                              "%(vol)s/%(folder)s"),
                            {'vol': vol, 'folder': folder})
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
        nms = self.share2nms[nfs_share]

        vol, dataset = self._get_share_datasets(nfs_share)
        snapshot_name = '%s/%s/%s@%s' % (vol, dataset, snapshot['volume_name'],
                                         snapshot['name'])
        folder = '%s/%s' % (dataset, volume['name'])
        nms.folder.clone(snapshot_name, '%s/%s' % (vol, folder))

        try:
            self._share_folder(nms, vol, folder)
        except nexenta.NexentaException:
            try:
                nms.folder.destroy('%s/%s' % (vol, folder), '')
            except nexenta.NexentaException:
                LOG.warning(_("Cannot destroy cloned folder: "
                              "%(vol)s/%(folder)s"),
                            {'vol': vol, 'folder': folder})
            raise

        return {'provider_location': volume['provider_location']}

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """
        LOG.info(_('Creating clone of volume: %s'), src_vref['id'])
        snapshot = {'volume_name': src_vref['name'],
                    'volume_id': src_vref['id'],
                    'name': self._get_clone_snapshot_name(volume)}
        # We don't delete this snapshot, because this snapshot will be origin
        # of new volume. This snapshot will be automatically promoted by NMS
        # when user will delete its origin.
        self.create_snapshot(snapshot)
        try:
            return self.create_volume_from_snapshot(volume, snapshot)
        except nexenta.NexentaException:
            LOG.error(_('Volume creation failed, deleting created snapshot '
                        '%(volume_name)s@%(name)s'), snapshot)
            try:
                self.delete_snapshot(snapshot)
            except (nexenta.NexentaException, exception.SnapshotIsBusy):
                LOG.warning(_('Failed to delete zfs snapshot '
                              '%(volume_name)s@%(name)s'), snapshot)
            raise

    def delete_volume(self, volume):
        """Deletes a logical volume.

        :param volume: volume reference
        """
        super(NexentaNfsDriver, self).delete_volume(volume)

        nfs_share = volume.get('provider_location')

        if nfs_share:
            nms = self.share2nms[nfs_share]
            vol, parent_folder = self._get_share_datasets(nfs_share)
            folder = '%s/%s/%s' % (vol, parent_folder, volume['name'])
            props = nms.folder.get_child_props(folder, 'origin') or {}
            try:
                nms.folder.destroy(folder, '-r')
            except nexenta.NexentaException as exc:
                if 'does not exist' in exc.args[0]:
                    LOG.info(_('Folder %s does not exist, it was '
                               'already deleted.'), folder)
                    return
                raise
            origin = props.get('origin')
            if origin and self._is_clone_snapshot_name(origin):
                try:
                    nms.snapshot.destroy(origin, '')
                except nexenta.NexentaException as exc:
                    if 'does not exist' in exc.args[0]:
                        LOG.info(_('Snapshot %s does not exist, it was '
                                   'already deleted.'), origin)
                        return
                    raise

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
        except nexenta.NexentaException as exc:
            if 'does not exist' in exc.args[0]:
                LOG.info(_('Snapshot %s does not exist, it was '
                           'already deleted.'), '%s@%s' % (folder, snapshot))
                return
            raise

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

        LOG.info(_('Creating regular file: %s.'
                   'This may take some time.') % path)

        nms.appliance.execute(
            'dd if=/dev/zero of=%(path)s bs=%(bs)dM count=%(count)d' % {
                'path': path,
                'bs': block_size_mb,
                'count': block_count
            }
        )

        LOG.info(_('Regular file: %s created.') % path)

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

            share_address = share_info[0].strip().decode('unicode_escape')
            nms_url = share_info[1].strip()
            share_opts = share_info[2].strip() if len(share_info) > 2 else None

            if not re.match(r'.+:/.+', share_address):
                LOG.warn("Share %s ignored due to invalid format.  Must be of "
                         "form address:/export." % share_address)
                continue

            self.shares[share_address] = share_opts
            self.share2nms[share_address] = self._get_nms_for_url(nms_url)

        LOG.debug('Shares loaded: %s' % self.shares)

    def _get_capacity_info(self, nfs_share):
        """Calculate available space on the NFS share.

        :param nfs_share: example 172.18.194.100:/var/nfs
        """
        nms = self.share2nms[nfs_share]
        ns_volume, ns_folder = self._get_share_datasets(nfs_share)
        folder_props = nms.folder.get_child_props('%s/%s' % (ns_volume,
                                                             ns_folder), '')
        free = utils.str2size(folder_props['available'])
        allocated = utils.str2size(folder_props['used'])
        return free + allocated, free, allocated

    def _get_nms_for_url(self, url):
        """Returns initialized nms object for url."""
        auto, scheme, user, password, host, port, path =\
            utils.parse_nms_url(url)
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
