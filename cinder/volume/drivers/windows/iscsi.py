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

import contextlib
import os

from os_win import utilsfactory
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import units
from oslo_utils import uuidutils

from cinder import exception
from cinder.image import image_utils
from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume import utils

LOG = logging.getLogger(__name__)

windows_opts = [
    cfg.StrOpt('windows_iscsi_lun_path',
               default=r'C:\iSCSIVirtualDisks',
               help='Path to store VHD backed volumes'),
]

CONF = cfg.CONF
CONF.register_opts(windows_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class WindowsISCSIDriver(driver.ISCSIDriver):
    """Executes volume driver commands on Windows Storage server."""

    VERSION = '1.0.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Microsoft_iSCSI_CI"

    def __init__(self, *args, **kwargs):
        super(WindowsISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration = kwargs.get('configuration', None)
        if self.configuration:
            self.configuration.append_config_values(windows_opts)

        self._vhdutils = utilsfactory.get_vhdutils()
        self._tgt_utils = utilsfactory.get_iscsi_target_utils()
        self._hostutils = utilsfactory.get_hostutils()

    @staticmethod
    def get_driver_options():
        return windows_opts

    def do_setup(self, context):
        """Setup the Windows Volume driver.

        Called one time by the manager after the driver is loaded.
        Validate the flags we care about
        """
        fileutils.ensure_tree(self.configuration.windows_iscsi_lun_path)
        fileutils.ensure_tree(CONF.image_conversion_dir)

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate."""
        self._get_portals()

    def _get_portals(self):
        available_portals = set(self._tgt_utils.get_portal_locations(
            available_only=True,
            fail_if_none_found=True))
        LOG.debug("Available iSCSI portals: %s", available_portals)

        iscsi_port = self.configuration.target_port
        iscsi_ips = ([self.configuration.target_ip_address] +
                     self.configuration.iscsi_secondary_ip_addresses)
        requested_portals = {':'.join([iscsi_ip, str(iscsi_port)])
                             for iscsi_ip in iscsi_ips}

        unavailable_portals = requested_portals - available_portals
        if unavailable_portals:
            LOG.warning("The following iSCSI portals were requested but "
                        "are not available: %s.", unavailable_portals)

        selected_portals = requested_portals & available_portals
        if not selected_portals:
            err_msg = "None of the configured iSCSI portals are available."
            raise exception.VolumeDriverException(err_msg)

        return list(selected_portals)

    def _get_host_information(self, volume, multipath=False):
        """Getting the portal and port information."""
        target_name = self._get_target_name(volume)

        available_portals = self._get_portals()
        properties = self._tgt_utils.get_target_information(target_name)

        # Note(lpetrut): the WT_Host CHAPSecret field cannot be accessed
        # for security reasons.
        auth = volume.provider_auth
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()
            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        properties['target_portal'] = available_portals[0]
        properties['target_discovered'] = False
        properties['target_lun'] = 0
        properties['volume_id'] = volume.id

        if multipath:
            properties['target_portals'] = available_portals
            properties['target_iqns'] = [properties['target_iqn']
                                         for portal in available_portals]
            properties['target_luns'] = [properties['target_lun']
                                         for portal in available_portals]

        return properties

    def initialize_connection(self, volume, connector):
        """Driver entry point to attach a volume to an instance."""
        initiator_name = connector['initiator']
        target_name = volume.provider_location

        self._tgt_utils.associate_initiator_with_iscsi_target(initiator_name,
                                                              target_name)

        properties = self._get_host_information(volume,
                                                connector.get('multipath'))

        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance.

        Unmask the LUN on the storage system so the given initiator can no
        longer access it.
        """
        initiator_name = connector['initiator']
        target_name = volume.provider_location
        self._tgt_utils.deassociate_initiator(initiator_name, target_name)

    def create_volume(self, volume):
        """Driver entry point for creating a new volume."""
        vhd_path = self.local_path(volume)
        vol_name = volume.name
        vol_size_mb = volume.size * 1024

        self._tgt_utils.create_wt_disk(vhd_path, vol_name,
                                       size_mb=vol_size_mb)

    def local_path(self, volume, disk_format=None):
        base_vhd_folder = self.configuration.windows_iscsi_lun_path
        if not disk_format:
            disk_format = self._tgt_utils.get_supported_disk_format()

        disk_fname = "%s.%s" % (volume.name, disk_format)
        return os.path.join(base_vhd_folder, disk_fname)

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        vol_name = volume.name
        vhd_path = self.local_path(volume)

        self._tgt_utils.remove_wt_disk(vol_name)
        fileutils.delete_if_exists(vhd_path)

    def create_snapshot(self, snapshot):
        """Driver entry point for creating a snapshot."""
        # Getting WT_Snapshot class
        vol_name = snapshot.volume_name
        snapshot_name = snapshot.name

        self._tgt_utils.create_snapshot(vol_name, snapshot_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Driver entry point for exporting snapshots as volumes."""
        snapshot_name = snapshot.name
        vol_name = volume.name
        vhd_path = self.local_path(volume)

        self._tgt_utils.export_snapshot(snapshot_name, vhd_path)
        self._tgt_utils.import_wt_disk(vhd_path, vol_name)

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        snapshot_name = snapshot.name
        self._tgt_utils.delete_snapshot(snapshot_name)

    def ensure_export(self, context, volume):
        # iSCSI targets exported by WinTarget persist after host reboot.
        pass

    def _get_target_name(self, volume):
        return "%s%s" % (self.configuration.target_prefix,
                         volume.name)

    def create_export(self, context, volume, connector):
        """Driver entry point to get the export info for a new volume."""
        target_name = self._get_target_name(volume)
        updates = {}

        if not self._tgt_utils.iscsi_target_exists(target_name):
            self._tgt_utils.create_iscsi_target(target_name)
            updates['provider_location'] = target_name

            if self.configuration.use_chap_auth:
                chap_username = (self.configuration.chap_username or
                                 utils.generate_username())
                chap_password = (self.configuration.chap_password or
                                 utils.generate_password())

                self._tgt_utils.set_chap_credentials(target_name,
                                                     chap_username,
                                                     chap_password)

                updates['provider_auth'] = ' '.join(('CHAP',
                                                     chap_username,
                                                     chap_password))

        # This operation is idempotent
        self._tgt_utils.add_disk_to_target(volume.name, target_name)

        return updates

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        target_name = self._get_target_name(volume)
        self._tgt_utils.delete_iscsi_target(target_name)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and create a volume using it."""
        # Convert to VHD and file back to VHD
        vhd_type = self._tgt_utils.get_supported_vhd_type()
        with image_utils.temporary_file(suffix='.vhd') as tmp:
            volume_path = self.local_path(volume)
            image_utils.fetch_to_vhd(context, image_service, image_id, tmp,
                                     self.configuration.volume_dd_blocksize)
            # The vhd must be disabled and deleted before being replaced with
            # the desired image.
            self._tgt_utils.change_wt_disk_status(volume.name,
                                                  enabled=False)
            os.unlink(volume_path)
            self._vhdutils.convert_vhd(tmp, volume_path,
                                       vhd_type)
            self._vhdutils.resize_vhd(volume_path,
                                      volume.size << 30,
                                      is_file_max_size=False)
            self._tgt_utils.change_wt_disk_status(volume.name,
                                                  enabled=True)

    @contextlib.contextmanager
    def _temporary_snapshot(self, volume_name):
        try:
            snap_uuid = uuidutils.generate_uuid()
            snapshot_name = '%s-tmp-snapshot-%s' % (volume_name, snap_uuid)
            self._tgt_utils.create_snapshot(volume_name, snapshot_name)
            yield snapshot_name
        finally:
            self._tgt_utils.delete_snapshot(snapshot_name)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        disk_format = self._tgt_utils.get_supported_disk_format()
        temp_vhd_path = os.path.join(CONF.image_conversion_dir,
                                     str(image_meta['id']) + '.' + disk_format)

        try:
            with self._temporary_snapshot(volume.name) as tmp_snap_name:
                # qemu-img cannot access VSS snapshots, for which reason it
                # must be exported first.
                self._tgt_utils.export_snapshot(tmp_snap_name, temp_vhd_path)
                image_utils.upload_volume(context, image_service, image_meta,
                                          temp_vhd_path, 'vhd')
        finally:
            fileutils.delete_if_exists(temp_vhd_path)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        src_vol_name = src_vref.name
        vol_name = volume.name
        vol_size = volume.size

        new_vhd_path = self.local_path(volume)

        with self._temporary_snapshot(src_vol_name) as tmp_snap_name:
            self._tgt_utils.export_snapshot(tmp_snap_name, new_vhd_path)
            self._vhdutils.resize_vhd(new_vhd_path, vol_size << 30,
                                      is_file_max_size=False)

            self._tgt_utils.import_wt_disk(new_vhd_path, vol_name)

    def _get_capacity_info(self):
        drive = os.path.splitdrive(
            self.configuration.windows_iscsi_lun_path)[0]
        (size, free_space) = self._hostutils.get_volume_info(drive)

        total_gb = size / units.Gi
        free_gb = free_space / units.Gi
        return (total_gb, free_gb)

    def _update_volume_stats(self):
        """Retrieve stats info for Windows device."""
        LOG.debug("Updating volume stats")
        total_gb, free_gb = self._get_capacity_info()

        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or self.__class__.__name__
        data["vendor_name"] = 'Microsoft'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = 'iSCSI'
        data['total_capacity_gb'] = total_gb
        data['free_capacity_gb'] = free_gb
        data['reserved_percentage'] = self.configuration.reserved_percentage
        data['QoS_support'] = False

        self._stats = data

    def extend_volume(self, volume, new_size):
        """Extend an Existing Volume."""
        old_size = volume.size
        LOG.debug("Extend volume from %(old_size)s GB to %(new_size)s GB.",
                  {'old_size': old_size, 'new_size': new_size})
        additional_size_mb = (new_size - old_size) * 1024

        self._tgt_utils.extend_wt_disk(volume.name, additional_size_mb)

    def backup_use_temp_snapshot(self):
        return False
