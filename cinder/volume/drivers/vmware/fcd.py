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
from oslo_vmware import exceptions as vexc
from oslo_vmware import image_transfer
from oslo_vmware.objects import datastore
from oslo_vmware import vim_util

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume.drivers.vmware import vmdk
from cinder.volume.drivers.vmware import volumeops as vops
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)

LOCATION_DRIVER_NAME = 'VMwareVcFcdDriver'


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

    # flag this driver as not supporting independent snapshots
    has_independent_snapshots = False

    # FCD Cross vcenter migration is available in 8.0.3
    FCD_CROSS_VC_MIGRATION_VC_VERSION = '8.0.3'

    def _driver_name(self):
        return LOCATION_DRIVER_NAME

    def do_setup(self, context):
        """Any initialization the volume driver needs to do while starting.

        :param context: The admin context.
        """
        super(VMwareVStorageObjectDriver, self).do_setup(context)
        self.volumeops.set_vmx_version('vmx-13')
        vc_67_compatible = versionutils.is_compatible(
            '6.7.0', self._vc_version, same_major=False)
        cross_vc_migration = versionutils.is_compatible(
            self.FCD_CROSS_VC_MIGRATION_VC_VERSION, self._vc_version,
            same_major=False)
        # self._use_fcd_snapshot = vc_67_compatible
        # Hard code this for now until we decide we want real snapshots
        self._use_fcd_snapshot = False
        self._storage_policy_enabled = vc_67_compatible
        self._use_fcd_cross_vc_migration = cross_vc_migration

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
        (host, rp, folder, summary) = self._select_ds_for_volume(volume)
        return summary.datastore

    def _get_temp_image_folder_from_volume(self, volume):
        (host_ref, _resource_pool,
            folder, summary) = self._select_ds_for_volume(volume)

        folder_path = volume.name + '/'
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

    def _provider_location_to_moref_location(self, ds_location):
        """Translate the provider location to the moref format.

        We store the provider location in the database in the format:
        <fcd_id>@<datastore name>

        Translate that to the moref format:
        <fcd_id>@<datastore moref>
        """
        fcd_id, ds_name = ds_location.split('@')
        (_, _, ds_ref) = self.ds_sel.select_datastore_by_name(ds_name)
        return "%s@%s" % (fcd_id, ds_ref.datastore.value)

    def _provider_location_to_ds_name_location(self, moref_location):
        """Translate the provider location to the datastore name."""
        fcd_loc = vops.FcdLocation.from_provider_location(
            moref_location
        )
        ds_ref = fcd_loc.ds_ref()
        summary = self.volumeops.get_summary(ds_ref)
        return "%s@%s" % (fcd_loc.fcd_id, summary.name)

    def _snap_provider_location_to_ds_name_location(self, moref_location):
        """Translate the provider location to the datastore name for snapshot.

        snapshot provider location is in the format of a json string:
        {"fcd_location": "<fcd_id>@<datastore moref>",
         "fcd_snapshot_id": "<snapshotid>"}
        convert this to
        {"fcd_location": "<fcd_id>@<datastore name>",
         "fcd_snapshot_id": "<snapshotid>"}
        """
        # first get the moref snap provider location object.
        fcd_snap_loc = vops.FcdSnapshotLocation.from_provider_location(
            moref_location
        )
        # now convert the snap fcd location to the datastore name format.
        snap_location_str = self._provider_location_to_ds_name_location(
            fcd_snap_loc.fcd_loc.provider_location()
        )
        # create a new fcd snap location object with the snap location
        snap_loc = vops.FcdLocation.from_provider_location(snap_location_str)
        # replace the existing fcd_loc with the new datastore snap location
        fcd_snap_loc.fcd_loc = snap_loc
        return fcd_snap_loc.provider_location()

    def _snap_provider_location_to_moref_location(self, ds_location):
        """Translate the provider location to the moref format for snapshot.


        snapshot provider location is in the format of a json string:
        {"fcd_location": "<fcd_id>@<datastore name>",
         "fcd_snapshot_id": "<snapshotid>"}
        convert this to
        {"fcd_location": "<fcd_id>@<datastore moref>",
         "fcd_snapshot_id": "<snapshotid>"}
        """
        # first get the datastore snap provider location object.
        fcd_snap_loc = vops.FcdSnapshotLocation.from_provider_location(
            ds_location
        )
        if not fcd_snap_loc:
            return None

        # now convert the snap fcd location to the moref format.
        snap_location_str = self._provider_location_to_moref_location(
            fcd_snap_loc.fcd_loc.provider_location()
        )
        # create a new fcd snap location object with the snap location
        snap_loc = vops.FcdLocation.from_provider_location(snap_location_str)
        fcd_snap_loc.fcd_loc = snap_loc
        return fcd_snap_loc.provider_location()

    @volume_utils.trace
    def create_volume(self, volume):
        """Create a new volume on the backend.

        :param volume: Volume object containing specifics to create.
        :returns: (Optional) dict of database updates for the new volume.
        """
        disk_type = self._get_disk_type(volume)
        ds_ref = self._select_ds_fcd(volume)
        profile_id = self._get_storage_profile_id(volume)
        fcd_loc = self.volumeops.create_fcd(
            volume.id, volume.name, volume.size * units.Ki, ds_ref,
            disk_type, profile_id=profile_id)

        # Convert the provider_location from the moref format to the
        # datastore name format to store in the cinder DB.
        provider_location = self._provider_location_to_ds_name_location(
            fcd_loc.provider_location()
        )
        return {'provider_location': provider_location}

    @volume_utils.trace
    def _delete_fcd(self, provider_loc, delete_folder=True):
        fcd_loc = vops.FcdLocation.from_provider_location(provider_loc)
        self.volumeops.delete_fcd(fcd_loc, delete_folder=delete_folder)

    @volume_utils.trace
    def delete_volume(self, volume):
        """Delete a volume from the backend.

        :param volume: The volume to delete.
        """
        if not volume.provider_location:
            LOG.warning("FCD provider location is empty for volume %s",
                        volume.id)
        else:
            try:
                # we store the PL with a datastore name, but volumeops uses
                # the moref format, so we need to convert it.
                provider_loc = self._provider_location_to_moref_location(
                    volume.provider_location
                )
                self._delete_fcd(provider_loc)
            except vexc.VimException as ex:
                if "could not be found" in str(ex):
                    LOG.warning("FCD deletion failed for %s not found. "
                                "delete_volume is considered successful.",
                                volume.id)
                else:
                    raise ex

    @volume_utils.trace
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
        # Check that connection_capabilities match
        # This ensures the connector is bound to the same vCenter service
        if 'connection_capabilities' in connector:
            missing = set(self._get_connection_capabilities()) -\
                set(connector['connection_capabilities'])
            if missing:
                raise exception.ConnectorRejected(
                    reason="Connector is missing %s" % ', '.join(missing))

        fcd_loc = vops.FcdLocation.from_provider_location(
            self._provider_location_to_moref_location(
                volume.provider_location
            )
        )
        # We don't need this parameters unless backup is created/restored
        backup = False
        backing_moref = ""
        vmdk_path = ""
        datacenter = ""
        if 'cinder-volume-backup' in connector['host']:
            backup = True

        if backup:
            backing = self.volumeops.get_backing(volume.name, volume.id)
            if not backing:
                create_params = {vmdk.CREATE_PARAM_DISK_LESS: True}
                backing = self._create_backing(volume,
                                               create_params=create_params)
                self.volumeops.attach_fcd(backing, fcd_loc)
            backing_moref = backing.value
            vmdk_path = self.volumeops.get_vmdk_path(backing)
            datacenter = self.volumeops.get_dc(backing)

        connection_info = {
            'driver_volume_type': self.STORAGE_TYPE,
            'data': {
                'volume_id': volume.id,
                'name': volume.name,
                # This is needed by the backup process (os-brick)
                'config': self._get_connector_config(),
                'id': fcd_loc.fcd_id,
                'ds_ref_val': fcd_loc.ds_ref_val,
                'ds_name': volume_utils.extract_host(volume.host,
                                                     level='pool'),
                'adapter_type': self._get_adapter_type(volume),
                'profile_id': self._get_storage_profile_id(volume),
                'volume': backing_moref,
                'vmdk_size': volume.size * units.Gi,
                'vmdk_path': vmdk_path,
                'datacenter': datacenter,
            }
        }

        # instruct os-brick to use ImportVApp and HttpNfc upload for
        # disconnecting the volume
        #
        # If we are migrating to this volume, we need to
        # create a writeable handle for the migration to work.
        if self._is_volume_subject_to_import_vapp(volume):
            connection_info['data']['import_data'] = \
                self._get_connection_import_data(volume)

        LOG.debug("Connection info for volume %(name)s: %(connection_info)s.",
                  {'name': volume.name, 'connection_info': connection_info})
        return connection_info

    @volume_utils.trace
    def terminate_connection(self, volume, connector, force=False, **kwargs):
        # Checking if the connection was used to restore from a backup. In
        # that case, the VMDK connector in os-brick created a new backing
        # which will replace the initial one. Here we set the proper name
        # and backing uuid for the new backing, because os-brick doesn't do it.
        if (connector and 'platform' in connector and 'os_type' in connector
                and self._is_volume_subject_to_import_vapp(volume)):
            try:
                # we store the PL with a datastore name, but volumeops uses
                # the moref format, so we need to convert it.
                provider_loc = self._provider_location_to_moref_location(
                    volume.provider_location
                )
                self._delete_fcd(provider_loc, delete_folder=False)
            except vexc.VimException as ex:
                if "could not be found" in str(ex):
                    pass
                else:
                    raise ex

            (_, _, folder, summary) = self._select_ds_for_volume(volume)
            backing = self.volumeops.get_backing_by_uuid(volume.id)
            self.volumeops.rename_backing(backing, volume.name)
            self.volumeops.update_backing_disk_uuid(backing, volume.id)
            profile_id = self._get_storage_profile_id(volume),
            vmware_host_ip = self.configuration.vmware_host_ip

            # Now move the vmdk into the original folder here?
            dest_dc = self.volumeops.get_dc(backing)
            src_vmdk_path = self.volumeops.get_vmdk_path(backing)
            dest_vmdk_path = f"[{summary.name}] {volume.id}/{volume.id}.vmdk"
            self.volumeops.move_vmdk_file(dest_dc, src_vmdk_path,
                                          dest_vmdk_path)
            self.volumeops.reconfigure_backing_vmdk_path(
                backing,
                dest_vmdk_path
            )

            fcd_loc = self.volumeops.update_fcd_after_backup_restore(
                volume, backing, profile_id, vmware_host_ip, folder)
            provider_location = self._provider_location_to_ds_name_location(
                fcd_loc.provider_location()
            )
            volume.update({'provider_location': provider_location})
            volume.save()
        else:
            backing = self.volumeops.get_backing_by_uuid(volume.id)
            fcd_loc = vops.FcdLocation.from_provider_location(
                self._provider_location_to_moref_location(
                    volume.provider_location))
            if backing:
                self.volumeops.detach_fcd(backing, fcd_loc)
                self._delete_temp_backing(backing)

    def _validate_container_format(self, container_format, image_id):
        if container_format and container_format != 'bare':
            msg = _("Container format: %s is unsupported, only 'bare' "
                    "is supported.") % container_format
            LOG.error(msg)
            raise exception.ImageUnacceptable(image_id=image_id, reason=msg)

    @volume_utils.trace
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
        dc_ref, summary, folder_path = self._get_temp_image_folder_from_volume(
            volume)
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

        fcd_vmdk_path = vmdk_path.get_descriptor_ds_file_path()
        self.volumeops.update_fcd_vmdk_uuid(summary.datastore,
                                            fcd_vmdk_path, volume.id)

        provider_location = self._provider_location_to_ds_name_location(
            fcd_loc.provider_location()
        )
        return {'provider_location': provider_location}

    @volume_utils.trace
    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image.

        :param context: Security/policy info for the request.
        :param volume: The volume to copy.
        :param image_service: The image service to use.
        :param image_meta: Information about the image.
        :returns: Model updates.
        """
        self._validate_disk_format(image_meta['disk_format'])

        # convert the datastore name provider location to what the
        # volumeops uses, which is the moref format.
        fcd_loc = vops.FcdLocation.from_provider_location(
            self._provider_location_to_moref_location(
                volume.provider_location
            )
        )

        attached = False
        try:
            create_params = {vmdk.CREATE_PARAM_DISK_LESS: True}
            backing = self._create_backing(volume, create_params=create_params)
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

    @volume_utils.trace
    def extend_volume(self, volume, new_size):
        """Extend the size of a volume.

        :param volume: The volume to extend.
        :param new_size: The new desired size of the volume.
        """
        # convert the datastore name provider location to what the
        # volumeops uses, which is the moref format.
        fcd_loc = vops.FcdLocation.from_provider_location(
            self._provider_location_to_moref_location(
                volume.provider_location
            )
        )
        self.volumeops.extend_fcd(fcd_loc, new_size * units.Ki)

    def _clone_fcd(self, provider_loc, volume, dest_ds_ref,
                   disk_type=vops.VirtualDiskType.THIN,
                   profile_id=None):
        # Must pass in the moref format for the provider location
        fcd_loc = vops.FcdLocation.from_provider_location(provider_loc)
        cf = self._session.vim.client.factory
        consumer = self.volumeops.get_fcd_consumer(fcd_loc.ds_ref(),
                                                   fcd_loc.id(cf))
        if consumer:
            # The volume is attached, so we need to clone the volume
            (host, rp, folder, _) = self._select_ds_for_volume(volume)
            return self.volumeops.clone_fcd_attached(
                consumer, volume, fcd_loc, dest_ds_ref, disk_type,
                host, rp, folder, profile_id,
                self.configuration.vmware_host_ip
            )
        else:
            return self.volumeops.clone_fcd(
                volume, fcd_loc, dest_ds_ref,
                disk_type, profile_id=profile_id
            )

    @volume_utils.trace
    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: Information for the snapshot to be created.
        """
        if self._use_fcd_snapshot:
            fcd_loc = vops.FcdLocation.from_provider_location(
                provider_location=self._provider_location_to_moref_location(
                    snapshot.volume.provider_location
                )
            )
            description = "snapshot-%s" % snapshot.id
            fcd_snap_loc = self.volumeops.create_fcd_snapshot(
                fcd_loc, description=description)
            p_location = self._snap_provider_location_to_ds_name_location(
                fcd_snap_loc.provider_location()
            )
            return {'provider_location': p_location}

        # This is a clone operattion, not a snapshot operation.
        ds_ref = self._select_ds_fcd(snapshot.volume)
        # convert the datastore name provider location to what the
        # volumeops uses, which is the moref format.
        provider_location = self._provider_location_to_moref_location(
            snapshot.volume.provider_location
        )
        cloned_fcd_loc = self._clone_fcd(provider_location, snapshot, ds_ref)
        # Now convert the fcd snapshot provider location to the
        # datastore format
        provider_location = self._provider_location_to_ds_name_location(
            cloned_fcd_loc.provider_location()
        )
        # this is an fcd provider location format because
        # it's not a snapshot.
        return {'provider_location': provider_location}

    @volume_utils.trace
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: The snapshot to delete.
        """
        if not snapshot.provider_location:
            LOG.debug("FCD snapshot location is empty.")
            return
        snap_location = self._snap_provider_location_to_moref_location(
            snapshot.provider_location
        )
        if snap_location:
            fcd_snap_loc = vops.FcdSnapshotLocation.from_provider_location(
                snap_location)
            self.volumeops.delete_fcd_snapshot(fcd_snap_loc)
        else:
            provider_loc = self._provider_location_to_moref_location(
                snapshot.provider_location
            )
            self._delete_fcd(provider_loc)

    def _extend_if_needed(self, fcd_loc, cur_size, new_size):
        if new_size > cur_size:
            self.volumeops.extend_fcd(fcd_loc, new_size * units.Ki)

    @volume_utils.trace
    def _create_volume_from_fcd(self, provider_location, cur_size, volume):
        ds_ref = self._select_ds_fcd(volume)
        disk_type = self._get_disk_type(volume)
        profile_id = self._get_storage_profile_id(volume)
        # convert the datastore name provider location to what the
        # volumeops uses, which is the moref format.
        provider_loc = self._provider_location_to_moref_location(
            provider_location
        )
        cloned_fcd_loc = self._clone_fcd(
            provider_loc, volume, ds_ref, disk_type=disk_type,
            profile_id=profile_id)
        self._extend_if_needed(cloned_fcd_loc, cur_size, volume.size)
        # Convert the provider location from the moref format to the
        # datastore name format to store in the cinder DB.
        p_location = self._provider_location_to_ds_name_location(
            cloned_fcd_loc.provider_location()
        )
        return {'provider_location': p_location}

    @volume_utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        :param volume: The volume to be created.
        :param snapshot: The snapshot from which to create the volume.
        :returns: A dict of database updates for the new volume.
        """
        # First convert the datastore provider location to a moref format
        snap_location = self._snap_provider_location_to_moref_location(
            snapshot.provider_location
        )
        if snap_location:
            fcd_snap_loc = vops.FcdSnapshotLocation.from_provider_location(
                snap_location)
            profile_id = self._get_storage_profile_id(volume)
            fcd_loc = self.volumeops.create_fcd_from_snapshot(
                fcd_snap_loc, volume.name, volume.id, profile_id=profile_id)
            self._extend_if_needed(fcd_loc, snapshot.volume_size, volume.size)
            # Convert the provider location from the moref format to the
            # datastore name format to store in the cinder DB.
            provider_location = self._provider_location_to_ds_name_location(
                fcd_loc.provider_location()
            )
            return {'provider_location': provider_location}
        else:
            return self._create_volume_from_fcd(snapshot.provider_location,
                                                snapshot.volume.size, volume)

    @volume_utils.trace
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        :param volume: New Volume object
        :param src_vref: Source Volume object
        """
        return self._create_volume_from_fcd(
            src_vref.provider_location, src_vref.size, volume)

    @volume_utils.trace
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

        # convert the datastore name provider location to what the
        # volumeops uses, which is the moref format.
        fcd_loc = vops.FcdLocation.from_provider_location(
            self._provider_location_to_moref_location(
                volume.provider_location
            )
        )
        new_profile_id = self.ds_sel.get_profile_id(new_profile)
        self.volumeops.update_fcd_policy(fcd_loc, new_profile_id.uniqueId)
        return True

    @volume_utils.trace
    def native_cross_vc_migrate_volume(self, context, volume, host,
                                       vcenter, fcd_loc):
        dest_host = host['host']
        cross_vc = False
        if self._vcenter_instance_uuid != vcenter:
            cross_vc = True
        if volume['attach_status'] == 'attached':
            if self._vcenter_instance_uuid != vcenter:
                return self._migrate_attached_cross_vc(context, dest_host,
                                                       volume, fcd_loc)
            else:
                return self._migrate_attached_same_vc(context, dest_host,
                                                      volume, fcd_loc)
        else:
            return self._migrate_unattached(context, dest_host, volume,
                                            fcd_loc, cross_vc)

    @volume_utils.trace
    def shadow_cross_vc_migrate_volume(self, context, volume, host,
                                       vcenter, fcd_loc):
        dest_host = host['host']
        if volume['attach_status'] == 'attached':
            if self._vcenter_instance_uuid != vcenter:
                # This is a cross vcenter migration
                raise self._migrate_attached_cross_vc(
                    context, dest_host, volume, fcd_loc)
            else:
                # we can migrate to another datastore in the same vcenter
                return self._migrate_attached_same_vc(
                    context, dest_host, volume, fcd_loc)
        else:
            if self._vcenter_instance_uuid != vcenter:
                # This is a cross vcenter migration
                return self._migrate_unattached_cross_vc_legacy(
                    context, dest_host, volume, fcd_loc)
            else:
                return self._migrate_unattached(
                    context, dest_host, volume, fcd_loc)

    @volume_utils.trace
    def migrate_volume(self, context, volume, host):
        """Migrate a volume to the specified host.

        If the backing is not created, returns success.
        """
        false_ret = (False, None)
        allowed_statuses = ['available', 'reserved', 'in-use', 'maintenance',
                            'extending']
        if volume['status'] not in allowed_statuses:
            LOG.debug('Only %s volumes can be migrated using backend '
                      'assisted migration. Falling back to generic migration.',
                      " or ".join(allowed_statuses))
            return false_ret

        if 'location_info' not in host['capabilities']:
            return false_ret
        info = host['capabilities']['location_info']
        try:
            (driver_name, vcenter) = info.split(':')
        except ValueError:
            return false_ret

        if driver_name != self._driver_name():
            return false_ret

        # convert the provider location to the moref format
        # so we can pass it to the volumeops
        fcd_loc = vops.FcdLocation.from_provider_location(
            self._provider_location_to_moref_location(
                volume.provider_location
            )
        )

        if self._use_fcd_cross_vc_migration:
            return self.native_cross_vc_migrate_volume(context, volume, host,
                                                       vcenter, fcd_loc)
        else:
            return self.shadow_cross_vc_migrate_volume(context, volume, host,
                                                       vcenter, fcd_loc)

    @volume_utils.trace
    def _migrate_unattached(self, context, dest_host, volume, fcd_loc,
                            cross_vc=False):

        ds_info = self._remote_api.select_ds_for_volume(context,
                                                        cinder_host=dest_host,
                                                        volume=volume)
        if cross_vc:
            service_locator = self._remote_api.get_service_locator_info(
                context,
                dest_host)
        else:
            service_locator = None

        ds_ref = vim_util.get_moref(ds_info['datastore'], 'Datastore')
        new_profile_id = ds_info.get('profile_id')

        self.volumeops.relocate_fcd(fcd_loc, ds_ref, volume.name,
                                    service_locator)
        fcd_loc_new = vops.FcdLocation(fcd_loc.fcd_id, ds_ref.value)
        # Convert the provider location from the moref format to the
        # datastore name format to store in the cinder DB.
        prov_loc = self._provider_location_to_ds_name_location(
            fcd_loc_new.provider_location()
        )
        volume.update({'provider_location': prov_loc})
        volume.save()
        if cross_vc:
            if self._use_fcd_cross_vc_migration:
                # Use the native FCD cross vc migration from 8.0U3 and >
                self._remote_api.update_fcd_policy(
                    context, dest_host, prov_loc, new_profile_id)
            else:
                # TODO(hemna): Add the temporary shadow migration
                LOG.error("TODO: Need to add shadow migration for cross vc.")
                raise NotImplementedError()
        # todo-update policy-onremote vc and move it to folder
        else:
            self.volumeops.update_fcd_policy(fcd_loc_new, new_profile_id)

        return (True, None)

    @volume_utils.trace
    def _migrate_attached_same_vc(self, context, dest_host, volume, fcd_loc):
        get_vm_by_uuid = self.volumeops.get_backing_by_uuid
        # reusing the get_backing_by_uuid to lookup the attacher vm
        if volume['multiattach']:
            raise NotImplementedError()
        attachments = volume.volume_attachment
        instance_uuid = attachments[0]['instance_uuid']
        attachedvm = get_vm_by_uuid(instance_uuid)
        ds_info = self._remote_api.select_ds_for_volume(context,
                                                        cinder_host=dest_host,
                                                        volume=volume)
        rp_ref = vim_util.get_moref(ds_info['resource_pool'], 'ResourcePool')
        ds_ref = vim_util.get_moref(ds_info['datastore'], 'Datastore')
        self.volumeops.relocate_one_disk(attachedvm, ds_ref, rp_ref,
                                         volume_id=volume.id,
                                         profile_id=ds_info.get('profile_id'))
        fcd_loc_new = vops.FcdLocation(fcd_loc.fcd_id, ds_ref.value)
        # Convert the provider location from the moref format to the
        # datastore name format to store in the cinder DB.
        prov_loc = self._provider_location_to_ds_name_location(
            fcd_loc_new.provider_location()
        )
        volume.update({'provider_location': prov_loc})
        volume.save()
        return (True, None)

    @volume_utils.trace
    def _migrate_attached_cross_vc(self, context, dest_host, volume, fcd_loc):
        # Unclear if we need to register the disk after movement
        # Presumably it won't change as it is also part of the vmdk bdb file
        self._remote_api.select_ds_for_volume(context,
                                              cinder_host=dest_host,
                                              volume=volume)
        # ds_ref = vim_util.get_moref(ds_info['datastore'], 'Datastore')
        # fcd_loc_new = vops.FcdLocation(fcd_loc.fcd_id, ds_ref.value)
        return (True, None)

    @volume_utils.trace
    def _migrate_unattached_cross_vc_legacy(self, context, dest_host, volume,
                                            fcd_loc):
        # Migrate to other vc on older than 8.0u3 will create a temporary
        # Shadow vm backing
        ds_info = self._remote_api.select_ds_for_volume(context,
                                                        cinder_host=dest_host,
                                                        volume=volume)
        service_locator = self._remote_api.get_service_locator_info(
            context, dest_host)
        ds_ref = vim_util.get_moref(ds_info['datastore'], 'Datastore')
        new_profile_id = ds_info.get('profile_id')
        hosts = self.volumeops.get_connected_hosts(fcd_loc.ds_ref())
        host = vim_util.get_moref(hosts[0], 'HostSystem')
        create_params = {vmdk.CREATE_PARAM_DISK_LESS: True}
        backing = self._create_backing(volume, host, create_params)
        self.volumeops.attach_fcd(backing, fcd_loc)
        host_ref = vim_util.get_moref(ds_info['host'], 'HostSystem')
        rp_ref = vim_util.get_moref(ds_info['resource_pool'], 'ResourcePool')
        self.volumeops.relocate_backing(backing, ds_ref, rp_ref, host_ref,
                                        profile_id=ds_info.get('profile_id'),
                                        service=service_locator)
        fcd_loc_new = vops.FcdLocation(fcd_loc.fcd_id, ds_ref.value)
        self._remote_api.destory_backing(context, dest_host, volume)
        self._remote_api.update_fcd_policy(
            context, dest_host,
            fcd_loc_new.provider_location(),
            new_profile_id)

        # cleanup on target volume mgr
        return (True, None)
