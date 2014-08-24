# Copyright 2014 IBM Corp.
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
# Authors:
#   Nilesh Bhosale <nilesh.bhosale@in.ibm.com>
#   Sasikanth Eda <sasikanth.eda@in.ibm.com>

"""
IBM NAS Volume Driver.
Currently, it supports the following IBM Storage Systems:
1. IBM Scale Out NAS (SONAS)
2. IBM Storwize V7000 Unified
3. NAS based IBM GPFS Storage Systems

Notes:
1. If you specify both a password and a key file, this driver will use the
   key file only.
2. When using a key file for authentication, it is up to the user or
   system administrator to store the private key in a safe manner.
"""

import os
import re

from oslo.config import cfg

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder.openstack.common import units
from cinder import utils
from cinder.volume.drivers import nfs
from cinder.volume.drivers.remotefs import nas_opts
from cinder.volume.drivers.san import san

VERSION = '1.1.0'

LOG = logging.getLogger(__name__)

platform_opts = [
    cfg.StrOpt('ibmnas_platform_type',
               default='v7ku',
               help=('IBMNAS platform type to be used as backend storage; '
                     'valid values are - '
                     'v7ku : for using IBM Storwize V7000 Unified, '
                     'sonas : for using IBM Scale Out NAS, '
                     'gpfs-nas : for using NFS based IBM GPFS deployments.')),
]

CONF = cfg.CONF
CONF.register_opts(platform_opts)


class IBMNAS_NFSDriver(nfs.NfsDriver, san.SanDriver):
    """IBMNAS NFS based cinder driver.

    Creates file on NFS share for using it as block device on hypervisor.
    Version history:
    1.0.0 - Initial driver
    1.1.0 - Support for NFS based GPFS storage backend
    """

    driver_volume_type = 'nfs'
    VERSION = VERSION

    def __init__(self, execute=utils.execute, *args, **kwargs):
        self._context = None
        super(IBMNAS_NFSDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(nas_opts)
        self.configuration.append_config_values(platform_opts)
        self.configuration.san_ip = self.configuration.nas_ip
        self.configuration.san_login = self.configuration.nas_login
        self.configuration.san_password = self.configuration.nas_password
        self.configuration.san_private_key = \
            self.configuration.nas_private_key
        self.configuration.san_ssh_port = self.configuration.nas_ssh_port
        self.configuration.ibmnas_platform_type = \
            self.configuration.ibmnas_platform_type.lower()
        LOG.info(_('Initialized driver for IBMNAS Platform: %s.'),
                 self.configuration.ibmnas_platform_type)

    def set_execute(self, execute):
        self._execute = utils.execute

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(IBMNAS_NFSDriver, self).do_setup(context)
        self._context = context

    def check_for_setup_error(self):
        """Ensure that the flags are set properly."""
        required_flags = ['nas_ip', 'nas_ssh_port', 'nas_login',
                          'ibmnas_platform_type']
        valid_platforms = ['v7ku', 'sonas', 'gpfs-nas']

        for flag in required_flags:
            if not self.configuration.safe_get(flag):
                raise exception.InvalidInput(reason=_('%s is not set') % flag)

        # Ensure that either password or keyfile were set
        if not (self.configuration.nas_password or
                self.configuration.nas_private_key):
            raise exception.InvalidInput(
                reason=_('Password or SSH private key is required for '
                         'authentication: set either nas_password or '
                         'nas_private_key option'))

        # Ensure whether ibmnas platform type is set to appropriate value
        if self.configuration.ibmnas_platform_type not in valid_platforms:
            raise exception.InvalidInput(
                reason = (_("Unsupported ibmnas_platform_type: %(given)s."
                            " Supported platforms: %(valid)s")
                          % {'given': self.configuration.ibmnas_platform_type,
                             'valid': (', '.join(valid_platforms))}))

    def _get_provider_location(self, volume_id):
        """Returns provider location for given volume."""
        LOG.debug("Enter _get_provider_location: volume_id %s" % volume_id)
        volume = self.db.volume_get(self._context, volume_id)
        LOG.debug("Exit _get_provider_location")
        return volume['provider_location']

    def _get_export_path(self, volume_id):
        """Returns NFS export path for the given volume."""
        LOG.debug("Enter _get_export_path: volume_id %s" % volume_id)
        return self._get_provider_location(volume_id).split(':')[1]

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Enter _update_volume_stats")
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or 'IBMNAS_NFS'
        data['vendor_name'] = 'IBM'
        data['driver_version'] = self.get_version()
        data['storage_protocol'] = self.driver_volume_type

        self._ensure_shares_mounted()

        global_capacity = 0
        global_free = 0
        for share in self._mounted_shares:
            capacity, free, _used = self._get_capacity_info(share)
            global_capacity += capacity
            global_free += free

        data['total_capacity_gb'] = global_capacity / float(units.Gi)
        data['free_capacity_gb'] = global_free / float(units.Gi)
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        self._stats = data
        LOG.debug("Exit _update_volume_stats")

    def _ssh_operation(self, ssh_cmd):
        try:
            self._run_ssh(ssh_cmd)
        except processutils.ProcessExecutionError as e:
            msg = (_('Failed in _ssh_operation while execution of ssh_cmd:'
                   '%(cmd)s. Error: %(error)s') % {'cmd': ssh_cmd, 'error': e})
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _create_ibmnas_snap(self, src, dest, mount_path):
        """Create volume clones and snapshots."""
        LOG.debug("Enter _create_ibmnas_snap: src %(src)s, dest %(dest)s"
                  % {'src': src, 'dest': dest})
        if self.configuration.ibmnas_platform_type == 'gpfs-nas':
            ssh_cmd = ['mmclone', 'snap', src, dest]
            self._ssh_operation(ssh_cmd)
        else:
            if mount_path is not None:
                tmp_file_path = dest + '.snap'
                ssh_cmd = ['mkclone', '-p', dest, '-s', src, '-t',
                           tmp_file_path]
                try:
                    self._ssh_operation(ssh_cmd)
                finally:
                    # Now remove the tmp file
                    tmp_file_local_path = os.path.join(mount_path, os.path.
                                                       basename(tmp_file_path))
                    self._execute('rm', '-f', tmp_file_local_path,
                                  run_as_root=True)
            else:
                ssh_cmd = ['mkclone', '-s', src, '-t', dest]
                self._ssh_operation(ssh_cmd)
        LOG.debug("Exit _create_ibmnas_snap")

    def _create_ibmnas_copy(self, src, dest, snap):
        """Create a cloned volume, parent & the clone both remain writable."""
        LOG.debug('Enter _create_ibmnas_copy: src %(src)s, dest %(dest)s, '
                  'snap %(snap)s' % {'src': src,
                                     'dest': dest,
                                     'snap': snap})
        if self.configuration.ibmnas_platform_type == 'gpfs-nas':
            ssh_cmd = ['mmclone', 'snap', src, snap]
            self._ssh_operation(ssh_cmd)
            ssh_cmd = ['mmclone', 'copy', snap, dest]
            self._ssh_operation(ssh_cmd)
        else:
            ssh_cmd = ['mkclone', '-p', snap, '-s', src, '-t', dest]
            self._ssh_operation(ssh_cmd)
        LOG.debug("Exit _create_ibmnas_copy")

    def _resize_volume_file(self, path, new_size):
        """Resize the image file on share to new size."""
        LOG.debug("Resizing file to %sG." % new_size)
        try:
            image_utils.resize_image(path, new_size, run_as_root=True)
        except processutils.ProcessExecutionError as e:
            msg = (_("Failed to resize volume "
                     "%(volume_id)s, error: %(error)s") %
                   {'volume_id': os.path.basename(path).split('-')[1],
                    'error': e.stderr})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return True

    def extend_volume(self, volume, new_size):
        """Extend an existing volume to the new size."""
        LOG.debug("Extending volume %s" % volume['name'])
        path = self.local_path(volume)
        self._resize_volume_file(path, new_size)

    def _delete_snapfiles(self, fchild, mount_point):
        LOG.debug('Enter _delete_snapfiles: fchild %(fchild)s, '
                  'mount_point %(mount_point)s'
                  % {'fchild': fchild,
                     'mount_point': mount_point})
        if self.configuration.ibmnas_platform_type == 'gpfs-nas':
            ssh_cmd = ['mmclone', 'show', fchild]
        else:
            ssh_cmd = ['lsclone', fchild]
        try:
            (out, _err) = self._run_ssh(ssh_cmd, check_exit_code=False)
        except processutils.ProcessExecutionError as e:
            msg = (_("Failed in _delete_snapfiles. Error: %s") % e.stderr)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        fparent = None
        reInode = re.compile(
            r'.*\s+(?:yes|no)\s+\d+\s+(?P<inode>\d+)', re.M | re.S)
        match = reInode.match(out)
        if match:
            inode = match.group('inode')
            path = mount_point
            (out, _err) = self._execute('find', path, '-maxdepth', '1',
                                        '-inum', inode, run_as_root=True)
            if out:
                fparent = out.split('\n', 1)[0]
        fchild_local_path = os.path.join(mount_point, os.path.basename(fchild))
        self._execute(
            'rm', '-f', fchild_local_path, check_exit_code=False,
            run_as_root=True)

        # There is no need to check for volume references on this snapshot
        # because 'rm -f' itself serves as a simple and implicit check. If the
        # parent is referenced by another volume, system doesn't allow deleting
        # it. 'rm -f' silently fails and the subsequent check on the path
        # indicates whether there are any volumes derived from that snapshot.
        # If there are such volumes, we quit recursion and let the other
        # volumes delete the snapshot later. If there are no references, rm
        # would succeed and the snapshot is deleted.
        if not os.path.exists(fchild) and fparent:
            fpbase = os.path.basename(fparent)
            if (fpbase.endswith('.ts') or fpbase.endswith('.snap')):
                fparent_remote_path = os.path.join(os.path.dirname(fchild),
                                                   fpbase)
                self._delete_snapfiles(fparent_remote_path, mount_point)
        LOG.debug("Exit _delete_snapfiles")

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        if not volume['provider_location']:
            LOG.warn(_('Volume %s does not have provider_location specified, '
                     'skipping.'), volume['name'])
            return

        export_path = self._get_export_path(volume['id'])
        volume_name = volume['name']
        volume_path = os.path.join(export_path, volume_name)
        mount_point = os.path.dirname(self.local_path(volume))

        # Delete all dependent snapshots, the snapshot will get deleted
        # if the link count goes to zero, else rm will fail silently
        self._delete_snapfiles(volume_path, mount_point)

    def create_snapshot(self, snapshot):
        """Creates a volume snapshot."""
        export_path = self._get_export_path(snapshot['volume_id'])
        snapshot_path = os.path.join(export_path, snapshot['name'])
        volume_path = os.path.join(export_path, snapshot['volume_name'])
        nfs_share = self._get_provider_location(snapshot['volume_id'])
        mount_path = self._get_mount_point_for_share(nfs_share)
        self._create_ibmnas_snap(src=volume_path, dest=snapshot_path,
                                 mount_path=mount_path)

    def delete_snapshot(self, snapshot):
        """Deletes a volume snapshot."""
        # A snapshot file is deleted as a part of delete_volume when
        # all volumes derived from it are deleted.

        # Rename the deleted snapshot to indicate it no longer exists in
        # cinder db. Attempt to delete the snapshot.  If the snapshot has
        # clone children, the delete will fail silently. When volumes that
        # are clone children are deleted in the future, the remaining ts
        # snapshots will also be deleted.
        nfs_share = self._get_provider_location(snapshot['volume_id'])
        mount_path = self._get_mount_point_for_share(nfs_share)
        snapshot_path = os.path.join(mount_path, snapshot['name'])
        snapshot_ts_path = '%s.ts' % snapshot_path
        self._execute('mv', '-f', snapshot_path, snapshot_ts_path,
                      check_exit_code=True, run_as_root=True)
        self._execute('rm', '-f', snapshot_ts_path,
                      check_exit_code=False, run_as_root=True)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from an existing volume snapshot.

        Extends the volume if the volume size is more than the snapshot size.
        """
        export_path = self._get_export_path(snapshot['volume_id'])
        snapshot_path = os.path.join(export_path, snapshot.name)
        volume_path = os.path.join(export_path, volume['name'])

        if self.configuration.ibmnas_platform_type == 'gpfs-nas':
            ssh_cmd = ['mmclone', 'copy', snapshot_path, volume_path]
            self._ssh_operation(ssh_cmd)
        else:
            self._create_ibmnas_snap(snapshot_path, volume_path, None)

        volume['provider_location'] = self._find_share(volume['size'])
        volume_path = self.local_path(volume)
        self._set_rw_permissions_for_owner(volume_path)

        # Extend the volume if required
        self._resize_volume_file(volume_path, volume['size'])
        return {'provider_location': volume['provider_location']}

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        Extends the volume if the new volume size is more than
        the source volume size.
        """
        export_path = self._get_export_path(src_vref['id'])
        src_vol_path = os.path.join(export_path, src_vref['name'])
        dest_vol_path = os.path.join(export_path, volume['name'])
        snap_file_name = volume['name']
        snap_file_name = snap_file_name + '.snap'
        snap_file_path = os.path.join(export_path, snap_file_name)
        self._create_ibmnas_copy(src_vol_path, dest_vol_path, snap_file_path)

        volume['provider_location'] = self._find_share(volume['size'])
        volume_path = self.local_path(volume)
        self._set_rw_permissions_for_owner(volume_path)

        # Extend the volume if required
        self._resize_volume_file(volume_path, volume['size'])

        return {'provider_location': volume['provider_location']}
