# Copyright (c) 2017 VMware, Inc.
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
VMware VStorageObject driver

Volume driver based on VMware VStorageObject aka First Class Disk (FCD). This
driver requires a minimum vCenter version of 6.5.
"""

from oslo_log import log as logging
from oslo_utils import units
from oslo_utils import versionutils
from oslo_vmware import image_transfer
from oslo_vmware.objects import datastore
from oslo_vmware import vim_util

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume.drivers.vmware import datastore as hub
from cinder.volume.drivers.vmware import vmdk
from cinder.volume.drivers.vmware import volumeops as vops
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)


@interface.volumedriver
class VMwareVStorageObjectDriver(vmdk.VMwareVcVmdkDriver):
    """Volume driver based on VMware VStorageObject"""

    # 1.0 - initial version based on vSphere 6.5 vStorageObject APIs
    # 1.1 - support for vStorageObject snapshot APIs
    # 1.2 - support for SPBM storage policies
    # 1.3 - support for retype
    VERSION = '1.3.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "VMware_CI"

    # minimum supported vCenter version
    MIN_SUPPORTED_VC_VERSION = '6.5'

    STORAGE_TYPE = 'vstorageobject'

    def do_setup(self, context):
        """Any initialization the volume driver needs to do while starting.

        :param context: The admin context.
        """
        super(VMwareVStorageObjectDriver, self).do_setup(context)
        self.volumeops.set_vmx_version('vmx-13')
        vc_67_compatible = versionutils.is_compatible(
            '6.7.0', self._vc_version, same_major=False)
        self._use_fcd_snapshot = vc_67_compatible
        self._storage_policy_enabled = vc_67_compatible

    def get_volume_stats(self, refresh=False):
        """Collects volume backend stats.

        :param refresh: Whether to discard any cached values and force a full
                        refresh of stats.
        :returns: dict of appropriate values.
        """
        stats = super(VMwareVStorageObjectDriver, self).get_volume_stats(
            refresh=refresh)
        stats['storage_protocol'] = self.STORAGE_TYPE
        return stats

    def _select_ds_fcd(self, volume):
        req = {}
        req[hub.DatastoreSelector.SIZE_BYTES] = volume.size * units.Gi

        if self._storage_policy_enabled:
            req[hub.DatastoreSelector.PROFILE_NAME] = (
                self._get_storage_profile(volume))
        (_host_ref, _resource_pool, summary) = self._select_datastore(req)
        return summary.datastore

    def _get_temp_image_folder(self, size_bytes, preallocated=False):
        req = {}
        req[hub.DatastoreSelector.SIZE_BYTES] = size_bytes

        if preallocated:
            req[hub.DatastoreSelector.HARD_AFFINITY_DS_TYPE] = (
                hub.DatastoreType.get_all_types() -
                {hub.DatastoreType.VSAN, hub.DatastoreType.VVOL})

        (host_ref, _resource_pool, summary) = self._select_datastore(req)

        folder_path = vmdk.TMP_IMAGES_DATASTORE_FOLDER_PATH
        dc_ref = self.volumeops.get_dc(host_ref)
        self.volumeops.create_datastore_folder(
            summary.name, folder_path, dc_ref)

        return (dc_ref, summary, folder_path)

    def _get_disk_type(self, volume):
        extra_spec_disk_type = super(
            VMwareVStorageObjectDriver, self)._get_disk_type(volume)
        return vops.VirtualDiskType.get_virtual_disk_type(extra_spec_disk_type)

    def _get_storage_profile_id(self, volume):
        if self._storage_policy_enabled:
            return super(
                VMwareVStorageObjectDriver, self)._get_storage_profile_id(
                    volume)

    def create_volume(self, volume):
        """Create a new volume on the backend.

        :param volume: Volume object containing specifics to create.
        :returns: (Optional) dict of database updates for the new volume.
        """
        disk_type = self._get_disk_type(volume)
        ds_ref = self._select_ds_fcd(volume)
        profile_id = self._get_storage_profile_id(volume)
        fcd_loc = self.volumeops.create_fcd(
            volume.name, volume.size * units.Ki, ds_ref, disk_type,
            profile_id=profile_id)
        return {'provider_location': fcd_loc.provider_location()}

    def _delete_fcd(self, provider_loc):
        fcd_loc = vops.FcdLocation.from_provider_location(provider_loc)
        self.volumeops.delete_fcd(fcd_loc)

    def delete_volume(self, volume):
        """Delete a volume from the backend.

        :param volume: The volume to delete.
        """
        if not volume.provider_location:
            LOG.warning("FCD provider location is empty for volume %s",
                        volume.id)
        else:
            self._delete_fcd(volume.provider_location)

    def initialize_connection(self, volume, connector, initiator_data=None):
        """Allow connection to connector and return connection info.

        :param volume: The volume to be attached.
        :param connector: Dictionary containing information about what is being
                          connected to.
        :param initiator_data: (Optional) A dictionary of driver_initiator_data
                               objects with key-value pairs that have been
                               saved for this initiator by a driver in previous
                               initialize_connection calls.
        :returns: A dictionary of connection information.
        """
        fcd_loc = vops.FcdLocation.from_provider_location(
            volume.provider_location)
        connection_info = {'driver_volume_type': self.STORAGE_TYPE}
        connection_info['data'] = {
            'id': fcd_loc.fcd_id,
            'ds_ref_val': fcd_loc.ds_ref_val,
            'adapter_type': self._get_adapter_type(volume)
        }
        LOG.debug("Connection info for volume %(name)s: %(connection_info)s.",
                  {'name': volume.name, 'connection_info': connection_info})
        return connection_info

    def _validate_container_format(self, container_format, image_id):
        if container_format and container_format != 'bare':
            msg = _("Container format: %s is unsupported, only 'bare' "
                    "is supported.") % container_format
            LOG.error(msg)
            raise exception.ImageUnacceptable(image_id=image_id, reason=msg)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume.

        :param context: Security/policy info for the request.
        :param volume: The volume to create.
        :param image_service: The image service to use.
        :param image_id: The image identifier.
        :returns: Model updates.
        """
        metadata = image_service.show(context, image_id)
        self._validate_disk_format(metadata['disk_format'])
        self._validate_container_format(
            metadata.get('container_format'), image_id)

        properties = metadata['properties'] or {}
        disk_type = properties.get('vmware_disktype',
                                   vmdk.ImageDiskType.PREALLOCATED)
        vmdk.ImageDiskType.validate(disk_type)

        size_bytes = metadata['size']
        dc_ref, summary, folder_path = self._get_temp_image_folder(
            volume.size * units.Gi)
        disk_name = volume.id
        if disk_type in [vmdk.ImageDiskType.SPARSE,
                         vmdk.ImageDiskType.STREAM_OPTIMIZED]:
            vmdk_path = self._create_virtual_disk_from_sparse_image(
                context, image_service, image_id, size_bytes, dc_ref,
                summary.name, folder_path, disk_name)
        else:
            vmdk_path = self._create_virtual_disk_from_preallocated_image(
                context, image_service, image_id, size_bytes, dc_ref,
                summary.name, folder_path, disk_name,
                vops.VirtualDiskAdapterType.LSI_LOGIC)

        ds_path = datastore.DatastorePath.parse(
            vmdk_path.get_descriptor_ds_file_path())
        dc_path = self.volumeops.get_inventory_path(dc_ref)

        vmdk_url = datastore.DatastoreURL(
            'https', self.configuration.vmware_host_ip, ds_path.rel_path,
            dc_path, ds_path.datastore)

        fcd_loc = self.volumeops.register_disk(
            str(vmdk_url), volume.name, summary.datastore)

        profile_id = self._get_storage_profile_id(volume)
        if profile_id:
            self.volumeops.update_fcd_policy(fcd_loc, profile_id)

        return {'provider_location': fcd_loc.provider_location()}

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image.

        :param context: Security/policy info for the request.
        :param volume: The volume to copy.
        :param image_service: The image service to use.
        :param image_meta: Information about the image.
        :returns: Model updates.
        """
        self._validate_disk_format(image_meta['disk_format'])

        fcd_loc = vops.FcdLocation.from_provider_location(
            volume.provider_location)
        hosts = self.volumeops.get_connected_hosts(fcd_loc.ds_ref())
        host = vim_util.get_moref(hosts[0], 'HostSystem')
        LOG.debug("Selected host: %(host)s for downloading fcd: %(fcd_loc)s.",
                  {'host': host, 'fcd_loc': fcd_loc})

        attached = False
        try:
            create_params = {vmdk.CREATE_PARAM_DISK_LESS: True}
            backing = self._create_backing(volume, host, create_params)
            self.volumeops.attach_fcd(backing, fcd_loc)
            attached = True

            vmdk_file_path = self.volumeops.get_vmdk_path(backing)
            conf = self.configuration

            # retrieve store information from extra-specs
            store_id = volume.volume_type.extra_specs.get(
                'image_service:store_id')

            # TODO (whoami-rajat): Remove store_id and base_image_ref
            #  parameters when oslo.vmware calls volume_utils wrapper of
            #  upload_volume instead of image_utils.upload_volume
            image_transfer.upload_image(
                context,
                conf.vmware_image_transfer_timeout_secs,
                image_service,
                image_meta['id'],
                volume.project_id,
                session=self.session,
                host=conf.vmware_host_ip,
                port=conf.vmware_host_port,
                vm=backing,
                vmdk_file_path=vmdk_file_path,
                vmdk_size=volume.size * units.Gi,
                image_name=image_meta['name'],
                store_id=store_id,
                base_image_ref=volume_utils.get_base_image_ref(volume))
        finally:
            if attached:
                self.volumeops.detach_fcd(backing, fcd_loc)
            backing = self.volumeops.get_backing_by_uuid(volume.id)
            if backing:
                self._delete_temp_backing(backing)

    def extend_volume(self, volume, new_size):
        """Extend the size of a volume.

        :param volume: The volume to extend.
        :param new_size: The new desired size of the volume.
        """
        fcd_loc = vops.FcdLocation.from_provider_location(
            volume.provider_location)
        self.volumeops.extend_fcd(fcd_loc, new_size * units.Ki)

    def _clone_fcd(self, provider_loc, name, dest_ds_ref,
                   disk_type=vops.VirtualDiskType.THIN,
                   profile_id=None):
        fcd_loc = vops.FcdLocation.from_provider_location(provider_loc)
        return self.volumeops.clone_fcd(
            name, fcd_loc, dest_ds_ref, disk_type, profile_id=profile_id)

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: Information for the snapshot to be created.
        """
        if self._use_fcd_snapshot:
            fcd_loc = vops.FcdLocation.from_provider_location(
                snapshot.volume.provider_location)
            description = "snapshot-%s" % snapshot.id
            fcd_snap_loc = self.volumeops.create_fcd_snapshot(
                fcd_loc, description=description)
            return {'provider_location': fcd_snap_loc.provider_location()}

        ds_ref = self._select_ds_fcd(snapshot.volume)
        cloned_fcd_loc = self._clone_fcd(
            snapshot.volume.provider_location, snapshot.name, ds_ref)
        return {'provider_location': cloned_fcd_loc.provider_location()}

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: The snapshot to delete.
        """
        if not snapshot.provider_location:
            LOG.debug("FCD snapshot location is empty.")
            return

        fcd_snap_loc = vops.FcdSnapshotLocation.from_provider_location(
            snapshot.provider_location)
        if fcd_snap_loc:
            self.volumeops.delete_fcd_snapshot(fcd_snap_loc)
        else:
            self._delete_fcd(snapshot.provider_location)

    def _extend_if_needed(self, fcd_loc, cur_size, new_size):
        if new_size > cur_size:
            self.volumeops.extend_fcd(fcd_loc, new_size * units.Ki)

    def _create_volume_from_fcd(self, provider_loc, cur_size, volume):
        ds_ref = self._select_ds_fcd(volume)
        disk_type = self._get_disk_type(volume)
        profile_id = self._get_storage_profile_id(volume)
        cloned_fcd_loc = self._clone_fcd(
            provider_loc, volume.name, ds_ref, disk_type=disk_type,
            profile_id=profile_id)
        self._extend_if_needed(cloned_fcd_loc, cur_size, volume.size)
        return {'provider_location': cloned_fcd_loc.provider_location()}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        :param volume: The volume to be created.
        :param snapshot: The snapshot from which to create the volume.
        :returns: A dict of database updates for the new volume.
        """
        fcd_snap_loc = vops.FcdSnapshotLocation.from_provider_location(
            snapshot.provider_location)
        if fcd_snap_loc:
            profile_id = self._get_storage_profile_id(volume)
            fcd_loc = self.volumeops.create_fcd_from_snapshot(
                fcd_snap_loc, volume.name, profile_id=profile_id)
            self._extend_if_needed(fcd_loc, snapshot.volume_size, volume.size)
            return {'provider_location': fcd_loc.provider_location()}
        else:
            return self._create_volume_from_fcd(snapshot.provider_location,
                                                snapshot.volume.size, volume)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: New Volume object
        :param src_vref: Source Volume object
        """
        return self._create_volume_from_fcd(
            src_vref.provider_location, src_vref.size, volume)

    def retype(self, context, volume, new_type, diff, host):
        if not self._storage_policy_enabled:
            return True

        profile = self._get_storage_profile(volume)
        new_profile = self._get_extra_spec_storage_profile(new_type['id'])
        if profile == new_profile:
            LOG.debug("Storage profile matches between new type and old type.")
            return True

        if self._in_use(volume):
            LOG.warning("Cannot change storage profile of attached FCD.")
            return False

        fcd_loc = vops.FcdLocation.from_provider_location(
            volume.provider_location)
        new_profile_id = self.ds_sel.get_profile_id(new_profile)
        self.volumeops.update_fcd_policy(fcd_loc, new_profile_id.uniqueId)
        return True
