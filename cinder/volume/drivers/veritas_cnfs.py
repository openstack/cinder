# Copyright (c) 2017 Veritas Technologies LLC
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

import os

from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume.drivers import nfs

LOG = logging.getLogger(__name__)


@interface.volumedriver
class VeritasCNFSDriver(nfs.NfsDriver):

    """Veritas Clustered NFS based cinder driver

      .. code-block:: default

        Version History:

          1.0.0 - Initial driver implementations for Kilo.
          1.0.1 - Liberty release driver not implemented.
                  Place holder for Liberty release in case we
                  need to support.
          1.0.2 - cinder.interface.volumedriver decorator.
                  Mitaka/Newton/Okata Release
          1.0.3 - Seperate create_cloned_volume() and
                  create_volume_from_snapshot () functionality.
                  Pike Release

    Executes commands relating to Volumes.
    """

    VERSION = "1.0.3"
    # ThirdPartySytems wiki page
    CI_WIKI_NAME = "Veritas_Access_CI"
    DRIVER_VOLUME_TYPE = 'nfs'

    def __init__(self, *args, **kwargs):
        self._execute = None
        self._context = None
        super(VeritasCNFSDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        self._context = context
        super(VeritasCNFSDriver, self).do_setup(context)
        opts = self.configuration.nfs_mount_options
        if not opts or opts.find('vers=3') == -1 or (
           opts.find('nfsvers=3')) == -1:
            msg = _("NFS is not configured to use NFSv3")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from snapshot."""
        LOG.debug('VeritasNFSDriver create_volume_from_snapshot called '
                  'volume_id = %(volume)s and snapshot_id = %(snapshot)s',
                  {'volume': volume.id, 'snapshot': snapshot.id})
        snap_name = snapshot.name
        vol_size = volume.size
        snap_size = snapshot.volume_size
        self._do_clone_volume(snapshot, snap_name, volume)
        volume.provider_location = snapshot.provider_location

        if vol_size != snap_size:
            try:
                self.extend_volume(volume, vol_size)
            except exception.ExtendVolumeError as ex:
                with excutils.save_and_reraise_exception():
                    LOG.error('Failed to extend Volume: %s', ex.msg)
                    path = self.local_path(volume)
                    self._delete_file(path)
        return {'provider_location': volume.provider_location}

    def _get_vol_by_id(self, volid):
        vol = self.db.volume_get(self._context, volid)
        return vol

    def _delete_file(self, path):
        """Deletes file from disk and return result as boolean."""
        try:
            LOG.debug('Deleting file at path %s', path)
            self._execute('rm', '-f', path, run_as_root=True)
        except OSError as ex:
            LOG.warning('Exception during deleting %s', ex.strerror)

    def create_snapshot(self, snapshot):
        """Create a snapshot of the volume."""
        src_vol_id = snapshot.volume_id
        src_vol_name = snapshot.volume_name
        src_vol = self._get_vol_by_id(src_vol_id)
        self._do_clone_volume(src_vol, src_vol_name, snapshot)
        snapshot.provider_location = src_vol.provider_location
        LOG.debug("VeritasNFSDriver create_snapshot %r",
                  snapshot.provider_location)
        return {'provider_location': snapshot.provider_location}

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        if not snapshot.provider_location:
            LOG.warning('Snapshot %s does not have provider_location '
                        'specified, skipping', snapshot.name)
            return
        self._ensure_share_mounted(snapshot.provider_location)
        snap_path = self.local_path(snapshot)
        self._delete_file(snap_path)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the volume."""

        LOG.debug('VeritasNFSDriver create_cloned_volume called '
                  'volume_id = %(volume)s and src_vol_id = %(src_vol_id)s',
                  {'volume': volume.id, 'src_vol_id': src_vref.id})
        src_vol_name = src_vref.name
        vol_size = volume.size
        src_vol_size = src_vref.size
        self._do_clone_volume(src_vref, src_vol_name, volume)
        volume.provider_location = src_vref.provider_location

        if vol_size != src_vol_size:
            try:
                self.extend_volume(volume, vol_size)
            except exception.ExtendVolumeError as ex:
                with excutils.save_and_reraise_exception():
                    LOG.error('Failed to extend Volume: %s', ex.msg)
                    path = self.local_path(volume)
                    self._delete_file(path)
        return {'provider_location': volume.provider_location}

    def _get_local_volume_path(self, provider_loc, vol_name):
        mnt_path = self._get_mount_point_for_share(provider_loc)
        vol_path = os.path.join(mnt_path, vol_name)
        return vol_path

    def _do_clone_volume(self, src_vol, src_vol_name, tgt_vol):
        cnfs_share = src_vol.provider_location
        tgt_vol_name = tgt_vol.name
        tgt_vol_path = self._get_local_volume_path(cnfs_share, tgt_vol_name)
        src_vol_path = self._get_local_volume_path(cnfs_share, src_vol_name)
        tgt_vol_path_spl = tgt_vol_path + "::snap:vxfs:"
        self._execute('ln', src_vol_path, tgt_vol_path_spl, run_as_root=True)
        LOG.debug("VeritasNFSDriver: do_clone_volume %(src_vol_path)s "
                  "%(tgt_vol_path)s %(tgt_vol_path_spl)s",
                  {'src_vol_path': src_vol_path,
                   'tgt_vol_path_spl': tgt_vol_path_spl,
                   'tgt_vol_path': tgt_vol_path})
        if not os.path.exists(tgt_vol_path):
            self._execute('rm', '-f', tgt_vol_path_spl, run_as_root=True)
            msg = _("Filesnap over NFS is not supported, "
                    "removing the ::snap:vxfs: file")
            LOG.error(msg)
            raise exception.NfsException(msg)

    def extend_volume(self, volume, size):
        """Extend the volume to new size"""
        path = self.local_path(volume)
        self._execute('truncate', '-s', '%sG' % size, path, run_as_root=True)
        LOG.debug("VeritasNFSDriver: extend_volume volume_id = %s", volume.id)

    def _update_volume_stats(self):
        super(VeritasCNFSDriver, self)._update_volume_stats()
        backend_name = self.configuration.safe_get('volume_backend_name')
        res_percentage = self.configuration.safe_get('reserved_percentage')
        self._stats["volume_backend_name"] = backend_name or 'VeritasCNFS'
        self._stats["vendor_name"] = 'Veritas'
        self._stats["reserved_percentage"] = res_percentage or 0
        self._stats["driver_version"] = self.VERSION
        self._stats["storage_protocol"] = self.DRIVER_VOLUME_TYPE
