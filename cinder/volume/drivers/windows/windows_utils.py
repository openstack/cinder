# Copyright 2013 Pedro Navarro Perez
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
Utility class for Windows Storage Server 2012 volume related operations.
"""

import ctypes
import os

from oslo.config import cfg

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.volume.drivers.windows import constants

# Check needed for unit testing on Unix
if os.name == 'nt':
    import wmi

    from ctypes import wintypes

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class WindowsUtils(object):
    """Executes volume driver commands on Windows Storage server."""

    def __init__(self, *args, **kwargs):
        # Set the flags
        self._conn_wmi = wmi.WMI(moniker='//./root/wmi')
        self._conn_cimv2 = wmi.WMI(moniker='//./root/cimv2')

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate.
        Invokes the portal and checks that is listening ISCSI traffic.
        """
        try:
            wt_portal = self._conn_wmi.WT_Portal()[0]
            listen = wt_portal.Listen
        except wmi.x_wmi as exc:
            err_msg = (_('check_for_setup_error: the state of the WT Portal '
                         'could not be verified. WMI exception: %s'))
            LOG.error(err_msg % exc)
            raise exception.VolumeBackendAPIException(data=err_msg % exc)

        if not listen:
            err_msg = (_('check_for_setup_error: there is no ISCSI traffic '
                         'listening.'))
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def get_host_information(self, volume, target_name):
        """Getting the portal and port information."""
        try:
            wt_portal = self._conn_wmi.WT_Portal()[0]
        except wmi.x_wmi as exc:
            err_msg = (_('get_host_information: the state of the WT Portal '
                         'could not be verified. WMI exception: %s'))
            LOG.error(err_msg % exc)
            raise exception.VolumeBackendAPIException(data=err_msg % exc)
        (address, port) = (wt_portal.Address, wt_portal.Port)
        # Getting the host information
        try:
            hosts = self._conn_wmi.WT_Host(Hostname=target_name)
            host = hosts[0]
        except wmi.x_wmi as exc:
            err_msg = (_('get_host_information: the ISCSI target information '
                         'could not be retrieved. WMI exception: %s'))
            LOG.error(err_msg % exc)
            raise exception.VolumeBackendAPIException(data=err_msg)

        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = '%s:%s' % (address, port)
        properties['target_iqn'] = host.TargetIQN
        properties['target_lun'] = 0
        properties['volume_id'] = volume['id']

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        return properties

    def associate_initiator_with_iscsi_target(self, initiator_name,
                                              target_name):
        """Sets information used by the iSCSI target entry."""
        try:
            cl = self._conn_wmi.__getattr__("WT_IDMethod")
            wt_idmethod = cl.new()
            wt_idmethod.HostName = target_name
            # Identification method is IQN
            wt_idmethod.Method = 4
            wt_idmethod.Value = initiator_name
            wt_idmethod.put()
        except wmi.x_wmi as exc:
            err_msg = (_('associate_initiator_with_iscsi_target: an '
                         'association between initiator: %(init)s and '
                         'target name: %(target)s could not be established. '
                         'WMI exception: %(wmi_exc)s') %
                       {'init': initiator_name, 'target': target_name,
                        'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def delete_iscsi_target(self, initiator_name, target_name):
        """Removes iSCSI targets to hosts."""

        try:
            wt_idmethod = self._conn_wmi.WT_IDMethod(HostName=target_name,
                                                     Method=4,
                                                     Value=initiator_name)[0]
            wt_idmethod.Delete_()
        except wmi.x_wmi as exc:
            err_msg = (_(
                'delete_iscsi_target: error when deleting the iscsi target '
                'associated with target name: %(target)s . '
                'WMI exception: %(wmi_exc)s') % {'target': target_name,
                                                 'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def create_volume(self, vhd_path, vol_name, vol_size=None):
        """Creates a volume."""
        try:
            cl = self._conn_wmi.__getattr__("WT_Disk")
            if vol_size:
                size_mb = vol_size * 1024
            else:
                size_mb = None
            cl.NewWTDisk(DevicePath=vhd_path,
                         Description=vol_name,
                         SizeInMB=size_mb)
        except wmi.x_wmi as exc:
            err_msg = (_(
                'create_volume: error when creating the volume name: '
                '%(vol_name)s . WMI exception: '
                '%(wmi_exc)s') % {'vol_name': vol_name, 'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def change_disk_status(self, vol_name, enabled):
        try:
            cl = self._conn_wmi.WT_Disk(Description=vol_name)[0]
            cl.Enabled = enabled
            cl.put()
        except wmi.x_wmi as exc:
            err_msg = (_(
                'Error changing disk status: '
                '%(vol_name)s . WMI exception: '
                '%(wmi_exc)s') % {'vol_name': vol_name, 'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def delete_volume(self, vol_name, vhd_path):
        """Driver entry point for destroying existing volumes."""
        try:
            disk = self._conn_wmi.WT_Disk(Description=vol_name)
            if not disk:
                LOG.debug('Skipping deleting disk %s as it does not '
                          'exist.' % vol_name)
                return
            wt_disk = disk[0]
            wt_disk.Delete_()
            vhdfiles = self._conn_cimv2.query(
                "Select * from CIM_DataFile where Name = '" +
                vhd_path + "'")
            if len(vhdfiles) > 0:
                vhdfiles[0].Delete()
        except wmi.x_wmi as exc:
            err_msg = (_(
                'delete_volume: error when deleting the volume name: '
                '%(vol_name)s . WMI exception: '
                '%(wmi_exc)s') % {'vol_name': vol_name, 'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def create_snapshot(self, vol_name, snapshot_name):
        """Driver entry point for creating a snapshot."""
        try:
            wt_disk = self._conn_wmi.WT_Disk(Description=vol_name)[0]
            # API Calls gets Generic Failure
            cl = self._conn_wmi.__getattr__("WT_Snapshot")
            disk_id = wt_disk.WTD
            out = cl.Create(WTD=disk_id)
            # Setting description since it used as a KEY
            wt_snapshot_created = self._conn_wmi.WT_Snapshot(Id=out[0])[0]
            wt_snapshot_created.Description = snapshot_name
            wt_snapshot_created.put()
        except wmi.x_wmi as exc:
            err_msg = (_(
                'create_snapshot: error when creating the snapshot name: '
                '%(vol_name)s . WMI exception: '
                '%(wmi_exc)s') % {'vol_name': snapshot_name, 'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def create_volume_from_snapshot(self, volume, snap_name):
        """Driver entry point for exporting snapshots as volumes."""
        try:
            vol_name = volume['name']
            vol_path = self.local_path(volume)

            wt_snapshot = self._conn_wmi.WT_Snapshot(Description=snap_name)[0]
            disk_id = wt_snapshot.Export()[0]
            # This export is read-only, so it needs to be copied
            # to another disk.
            wt_disk = self._conn_wmi.WT_Disk(WTD=disk_id)[0]
            wt_disk.Description = '%s-temp' % vol_name
            wt_disk.put()
            src_path = wt_disk.DevicePath

            self.copy(src_path, vol_path)
            self.create_volume(vol_path, vol_name)
            wt_disk.Delete_()
        except wmi.x_wmi as exc:
            err_msg = (_(
                'create_volume_from_snapshot: error when creating the volume '
                'name: %(vol_name)s from snapshot name: %(snap_name)s. '
                'WMI exception: %(wmi_exc)s') % {'vol_name': vol_name,
                                                 'snap_name': snap_name,
                                                 'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def delete_snapshot(self, snap_name):
        """Driver entry point for deleting a snapshot."""
        try:
            wt_snapshot = self._conn_wmi.WT_Snapshot(Description=snap_name)[0]
            wt_snapshot.Delete_()
        except wmi.x_wmi as exc:
            err_msg = (_(
                'delete_snapshot: error when deleting the snapshot name: '
                '%(snap_name)s . WMI exception: '
                '%(wmi_exc)s') % {'snap_name': snap_name, 'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def create_iscsi_target(self, target_name, ensure):
        """Creates ISCSI target."""
        try:
            cl = self._conn_wmi.__getattr__("WT_Host")
            cl.NewHost(HostName=target_name)
        except wmi.x_wmi as exc:
            excep_info = exc.com_error.excepinfo[2]
            if not ensure or excep_info.find(u'The file exists') == -1:
                err_msg = (_(
                    'create_iscsi_target: error when creating iscsi target: '
                    '%(tar_name)s . WMI exception: '
                    '%(wmi_exc)s') % {'tar_name': target_name, 'wmi_exc': exc})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)
            else:
                LOG.info(_('Ignored target creation error "%s"'
                           ' while ensuring export'), exc)

    def remove_iscsi_target(self, target_name):
        """Removes ISCSI target."""
        try:
            host = self._conn_wmi.WT_Host(HostName=target_name)
            if not host:
                LOG.debug('Skipping removing target %s as it does not '
                          'exist.' % target_name)
                return
            wt_host = host[0]
            wt_host.RemoveAllWTDisks()
            wt_host.Delete_()
        except wmi.x_wmi as exc:
            err_msg = (_(
                'remove_iscsi_target: error when deleting iscsi target: '
                '%(tar_name)s . WMI exception: '
                '%(wmi_exc)s') % {'tar_name': target_name, 'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def add_disk_to_target(self, vol_name, target_name):
        """Adds the disk to the target."""
        try:
            q = self._conn_wmi.WT_Disk(Description=vol_name)
            wt_disk = q[0]
            wt_host = self._conn_wmi.WT_Host(HostName=target_name)[0]
            wt_host.AddWTDisk(wt_disk.WTD)
        except wmi.x_wmi as exc:
            err_msg = (_(
                'add_disk_to_target: error adding disk associated to volume : '
                '%(vol_name)s to the target name: %(tar_name)s '
                '. WMI exception: %(wmi_exc)s') % {'tar_name': target_name,
                                                   'vol_name': vol_name,
                                                   'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def copy_vhd_disk(self, source_path, destination_path):
        """Copy the vhd disk from source path to destination path."""
        try:
            vhdfiles = self._conn_cimv2.query(
                "Select * from CIM_DataFile where Name = '" +
                source_path + "'")
            if len(vhdfiles) > 0:
                vhdfiles[0].Copy(destination_path)
        except wmi.x_wmi as exc:
            err_msg = (_(
                'copy_vhd_disk: error when copying disk from source path : '
                '%(src_path)s to destination path: %(dest_path)s '
                '. WMI exception: '
                '%(wmi_exc)s') % {'src_path': source_path,
                                  'dest_path': destination_path,
                                  'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def extend(self, vol_name, additional_size):
        """Extend an existing volume."""
        try:
            q = self._conn_wmi.WT_Disk(Description=vol_name)
            wt_disk = q[0]
            wt_disk.Extend(additional_size)
        except wmi.x_wmi as exc:
            err_msg = (_(
                'extend: error when extending the volume: %(vol_name)s '
                '.WMI exception: %(wmi_exc)s') % {'vol_name': vol_name,
                                                  'wmi_exc': exc})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def local_path(self, volume, format=None):
        base_vhd_folder = CONF.windows_iscsi_lun_path
        if not os.path.exists(base_vhd_folder):
            LOG.debug('Creating folder: %s' % base_vhd_folder)
            os.makedirs(base_vhd_folder)
        if not format:
            format = self.get_supported_format()
        return os.path.join(base_vhd_folder, str(volume['name']) + "." +
                            format)

    def check_min_windows_version(self, major, minor, build=0):
        version_str = self.get_windows_version()
        return map(int, version_str.split('.')) >= [major, minor, build]

    def get_windows_version(self):
        return self._conn_cimv2.Win32_OperatingSystem()[0].Version

    def get_supported_format(self):
        if self.check_min_windows_version(6, 3):
            return 'vhdx'
        else:
            return 'vhd'

    def get_supported_vhd_type(self):
        if self.check_min_windows_version(6, 3):
            return constants.VHD_TYPE_DYNAMIC
        else:
            return constants.VHD_TYPE_FIXED

    def copy(self, src, dest):
        # With large files this is 2x-3x faster than shutil.copy(src, dest),
        # especially with UNC targets.
        kernel32 = ctypes.windll.kernel32
        kernel32.CopyFileW.restype = wintypes.BOOL

        retcode = kernel32.CopyFileW(ctypes.c_wchar_p(src),
                                     ctypes.c_wchar_p(dest),
                                     wintypes.BOOL(True))
        if not retcode:
            raise IOError(_('The file copy from %(src)s to %(dest)s failed.')
                          % {'src': src, 'dest': dest})
