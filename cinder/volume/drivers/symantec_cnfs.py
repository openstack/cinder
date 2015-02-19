# Copyright (c) 2014 Symantec Corporation
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

from cinder import exception
from cinder.i18n import _, _LW
from cinder.volume.drivers import nfs

LOG = logging.getLogger(__name__)


class SymantecCNFSDriver(nfs.NfsDriver):

    """Symantec Clustered NFS based cinder driver.

    Executes commands relating to Volumes.
    """

    VERSION = "1.0.1"
    driver_volume_type = 'nfs'

    def __init__(self, *args, **kwargs):
        self._execute = None
        self._context = None
        super(SymantecCNFSDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        self._context = context
        super(SymantecCNFSDriver, self).do_setup(context)
        opts = self.configuration.nfs_mount_options
        if not opts or opts.find('vers=3') == -1 or (
           opts.find('nfsvers=3')) == -1:
            msg = _("NFS is not configured to use NFSv3.")
            LOG.error(msg)
            raise exception.NfsException(msg)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from snapshot."""
        vol_name = volume['name']
        snap_name = snapshot['name']
        LOG.debug("SymantecNFSDriver create_volume_from_snapshot called "
                  "vol_name %r snap_name %r", vol_name, snap_name)
        self._do_clone_volume(snapshot, snap_name, volume)
        LOG.debug("SymantecNFSDriver create_volume_from_snapshot-2 %r",
                  volume['provider_location'])
        return {'provider_location': volume['provider_location']}

    def _volid_to_vol(self, volid):
        vol = self.db.volume_get(self._context, volid)
        return vol

    def create_snapshot(self, snapshot):
        """Create a snapshot of the volume."""
        src_vol_id = snapshot['volume_id']
        src_vol_name = snapshot['volume_name']
        src_vol = self._volid_to_vol(src_vol_id)
        self._do_clone_volume(src_vol, src_vol_name, snapshot)
        LOG.debug("SymantecNFSDriver create_snapshot %r",
                  snapshot['provider_location'])
        return {'provider_location': snapshot['provider_location']}

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        if not snapshot['provider_location']:
            LOG.warn(_LW('Snapshot %s does not have provider_location '
                     'specified, skipping.'), snapshot['name'])
            return
        self._ensure_share_mounted(snapshot['provider_location'])
        snap_path = self.local_path(snapshot)
        self._execute('rm', '-f', snap_path, run_as_root=True)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the volume."""
        self.create_volume_from_snapshot(volume, src_vref)

    def _get_local_volume_path(self, provider_loc, vol_name):
        mnt_path = self._get_mount_point_for_share(provider_loc)
        vol_path = os.path.join(mnt_path, vol_name)
        return vol_path

    def _do_clone_volume(self, src_vol, src_vol_name, tgt_vol):
        cnfs_share = src_vol['provider_location']
        tgt_vol_name = tgt_vol['name']
        tgt_vol_path = self._get_local_volume_path(cnfs_share, tgt_vol_name)
        src_vol_path = self._get_local_volume_path(cnfs_share, src_vol_name)
        tgt_vol_path_spl = tgt_vol_path + "::snap:vxfs:"
        self._execute('ln', src_vol_path, tgt_vol_path_spl, run_as_root=True)
        LOG.debug("SymantecNFSDrivers: do_clone_volume src_vol_path %r "
                  "tgt_vol_path %r tgt_vol_path_spl %r",
                  src_vol_path, tgt_vol_path, tgt_vol_path_spl)
        if not os.path.exists(tgt_vol_path):
            self._execute('rm', '-f', tgt_vol_path_spl, run_as_root=True)
            msg = _("Filesnap over NFS is not supported, "
                    "removing the ::snap:vxfs: file.")
            LOG.error(msg)
            raise exception.NfsException(msg)
        tgt_vol['provider_location'] = src_vol['provider_location']

    def _update_volume_stats(self):
        super(SymantecCNFSDriver, self)._update_volume_stats()
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._stats["volume_backend_name"] = backend_name or 'SymantecCNFS'
        self._stats["vendor_name"] = 'Symantec'
        self._stats["driver_version"] = self.VERSION
        self._stats["storage_protocol"] = self.driver_volume_type
