# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Pedro Navarro Perez
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
Volume driver for Windows Server 2012

This driver requires ISCSI target role installed

"""
import os
import sys

from oslo.config import cfg

from cinder import exception
from cinder import flags
from cinder.openstack.common import log as logging
from cinder.volume import driver

# Check needed for unit testing on Unix
if os.name == 'nt':
    import wmi


LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS

windows_opts = [
    cfg.StrOpt('windows_iscsi_lun_path',
               default='C:\iSCSIVirtualDisks',
               help='Path to store VHD backed volumes'),
]

FLAGS.register_opts(windows_opts)


class WindowsDriver(driver.ISCSIDriver):
    """Executes volume driver commands on Windows Storage server."""

    def __init__(self, *args, **kwargs):
        super(WindowsDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        """Setup the Windows Volume driver.

        Called one time by the manager after the driver is loaded.
        Validate the flags we care about
        """
        #Set the flags
        self._conn_wmi = wmi.WMI(moniker='//./root/wmi')
        self._conn_cimv2 = wmi.WMI(moniker='//./root/cimv2')

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate.
        """
        #Invoking the portal an checking that is listening
        wt_portal = self._conn_wmi.WT_Portal()[0]
        listen = wt_portal.Listen
        if not listen:
            raise exception.VolumeBackendAPIException()

    def initialize_connection(self, volume, connector):
        """Driver entry point to attach a volume to an instance.
        """
        initiator_name = connector['initiator']
        target_name = volume['provider_location']

        cl = self._conn_wmi.__getattr__("WT_IDMethod")
        wt_idmethod = cl.new()
        wt_idmethod.HostName = target_name
        wt_idmethod.Method = 4
        wt_idmethod.Value = initiator_name
        wt_idmethod.put()
        #Getting the portal and port information
        wt_portal = self._conn_wmi.WT_Portal()[0]
        (address, port) = (wt_portal.Address, wt_portal.Port)
        #Getting the host information
        hosts = self._conn_wmi.WT_Host(Hostname=target_name)
        host = hosts[0]

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

        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance.

        Unmask the LUN on the storage system so the given intiator can no
        longer access it.
        """
        initiator_name = connector['initiator']
        provider_location = volume['provider_location']
        #DesAssigning target to initiators
        wt_idmethod = self._conn_wmi.WT_IDMethod(HostName=provider_location,
                                                 Method=4,
                                                 Value=initiator_name)[0]
        wt_idmethod.Delete_()

    def create_volume(self, volume):
        """Driver entry point for creating a new volume."""
        vhd_path = self._get_vhd_path(volume)
        vol_name = volume['name']
        #The WMI procedure returns a Generic failure
        cl = self._conn_wmi.__getattr__("WT_Disk")
        cl.NewWTDisk(DevicePath=vhd_path,
                     Description=vol_name,
                     SizeInMB=volume['size'] * 1024)

    def _get_vhd_path(self, volume):
        base_vhd_folder = FLAGS.windows_iscsi_lun_path
        if not os.path.exists(base_vhd_folder):
                LOG.debug(_('Creating folder %s '), base_vhd_folder)
                os.makedirs(base_vhd_folder)
        return os.path.join(base_vhd_folder, str(volume['name']) + ".vhd")

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        vol_name = volume['name']
        wt_disk = self._conn_wmi.WT_Disk(Description=vol_name)[0]
        wt_disk.Delete_()
        vhdfiles = self._conn_cimv2.query(
            "Select * from CIM_DataFile where Name = '" +
            self._get_vhd_path(volume) + "'")
        if len(vhdfiles) > 0:
            vhdfiles[0].Delete()

    def create_snapshot(self, snapshot):
        """Driver entry point for creating a snapshot.
        """
        #Getting WT_Snapshot class
        vol_name = snapshot['volume_name']
        snapshot_name = snapshot['name']

        wt_disk = self._conn_wmi.WT_Disk(Description=vol_name)[0]
        #API Calls gets Generic Failure
        cl = self._conn_wmi.__getattr__("WT_Snapshot")
        disk_id = wt_disk.WTD
        out = cl.Create(WTD=disk_id)
        #Setting description since it used as a KEY
        wt_snapshot_created = self._conn_wmi.WT_Snapshot(Id=out[0])[0]
        wt_snapshot_created.Description = snapshot_name
        wt_snapshot_created.put()

    def create_volume_from_snapshot(self, volume, snapshot):
        """Driver entry point for exporting snapshots as volumes."""
        snapshot_name = snapshot['name']
        wt_snapshot = self._conn_wmi.WT_Snapshot(Description=snapshot_name)[0]
        disk_id = wt_snapshot.Export()[0]
        wt_disk = self._conn_wmi.WT_Disk(WTD=disk_id)[0]
        wt_disk.Description = volume['name']
        wt_disk.put()

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        snapshot_name = snapshot['name']
        wt_snapshot = self._conn_wmi.WT_Snapshot(Description=snapshot_name)[0]
        wt_snapshot.Delete_()

    def _do_export(self, _ctx, volume, ensure=False):
        """Do all steps to get disk exported as LUN 0 at separate target.

        :param volume: reference of volume to be exported
        :param ensure: if True, ignore errors caused by already existing
            resources
        :return: iscsiadm-formatted provider location string
        """
        target_name = "%s%s" % (FLAGS.iscsi_target_prefix, volume['name'])
        #ISCSI target creation
        try:
            cl = self._conn_wmi.__getattr__("WT_Host")
            cl.NewHost(HostName=target_name)
        except Exception as exc:
            excep_info = exc.com_error.excepinfo[2]
            if not ensure or excep_info.find(u'The file exists') == -1:
                raise
            else:
                LOG.info(_('Ignored target creation error "%s"'
                           ' while ensuring export'), exc)
        #Get the disk to add
        vol_name = volume['name']
        q = self._conn_wmi.WT_Disk(Description=vol_name)
        if not len(q):
            LOG.debug(_('Disk not found: %s'), vol_name)
            return None
        wt_disk = q[0]
        wt_host = self._conn_wmi.WT_Host(HostName=target_name)[0]
        wt_host.AddWTDisk(wt_disk.WTD)

        return target_name

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        self._do_export(context, volume, ensure=True)

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        loc = self._do_export(context, volume, ensure=False)
        return {'provider_location': loc}

    def remove_export(self, context, volume):
        """Driver exntry point to remove an export for a volume.
        """
        target_name = "%s%s" % (FLAGS.iscsi_target_prefix, volume['name'])

        #Get ISCSI target
        wt_host = self._conn_wmi.WT_Host(HostName=target_name)[0]
        wt_host.RemoveAllWTDisks()
        wt_host.Delete_()

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        raise NotImplementedError()

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        raise NotImplementedError()
