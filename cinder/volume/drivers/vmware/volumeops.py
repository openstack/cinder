# Copyright (c) 2013 VMware, Inc.
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
Implements operations on volumes residing on VMware datastores.
"""

import json

from oslo_log import log as logging
from oslo_utils import units
from oslo_vmware import exceptions
from oslo_vmware.objects import datastore as ds_obj
from oslo_vmware import vim_util
import six
from six.moves import urllib

from cinder.i18n import _
from cinder.volume.drivers.vmware import exceptions as vmdk_exceptions


LOG = logging.getLogger(__name__)
LINKED_CLONE_TYPE = 'linked'
FULL_CLONE_TYPE = 'full'

BACKING_UUID_KEY = 'instanceUuid'


def split_datastore_path(datastore_path):
    """Split the datastore path to components.

    return the datastore name, relative folder path and the file name

    E.g. datastore_path = [datastore1] my_volume/my_volume.vmdk, returns
    (datastore1, my_volume/, my_volume.vmdk)

    :param datastore_path: Datastore path of a file
    :return: Parsed datastore name, relative folder path and file name
    """
    splits = datastore_path.split('[', 1)[1].split(']', 1)
    datastore_name = None
    folder_path = None
    file_name = None
    if len(splits) == 1:
        datastore_name = splits[0]
    else:
        datastore_name, path = splits
        # Path will be of form my_volume/my_volume.vmdk
        # we need into my_volumes/ and my_volume.vmdk
        splits = path.split('/')
        file_name = splits[len(splits) - 1]
        folder_path = path[:-len(file_name)]

    return (datastore_name.strip(), folder_path.strip(), file_name.strip())


class VirtualDiskPath(object):
    """Class representing paths of files comprising a virtual disk."""

    def __init__(self, ds_name, folder_path, disk_name):
        """Creates path object for the given disk.

        :param ds_name: name of the datastore where disk is stored
        :param folder_path: absolute path of the folder containing the disk
        :param disk_name: name of the virtual disk
        """
        self._descriptor_file_path = "%s%s.vmdk" % (folder_path, disk_name)
        self._descriptor_ds_file_path = self.get_datastore_file_path(
            ds_name, self._descriptor_file_path)

    def get_datastore_file_path(self, ds_name, file_path):
        """Get datastore path corresponding to the given file path.

        :param ds_name: name of the datastore containing the file represented
                        by the given file path
        :param file_path: absolute path of the file
        :return: datastore file path
        """
        return "[%s] %s" % (ds_name, file_path)

    def get_descriptor_file_path(self):
        """Get absolute file path of the virtual disk descriptor."""
        return self._descriptor_file_path

    def get_descriptor_ds_file_path(self):
        """Get datastore file path of the virtual disk descriptor."""
        return self._descriptor_ds_file_path


class FlatExtentVirtualDiskPath(VirtualDiskPath):
    """Paths of files in a non-monolithic disk with a single flat extent."""

    def __init__(self, ds_name, folder_path, disk_name):
        """Creates path object for the given disk.

        :param ds_name: name of the datastore where disk is stored
        :param folder_path: absolute path of the folder containing the disk
        :param disk_name: name of the virtual disk
        """
        super(FlatExtentVirtualDiskPath, self).__init__(
            ds_name, folder_path, disk_name)
        self._flat_extent_file_path = "%s%s-flat.vmdk" % (folder_path,
                                                          disk_name)
        self._flat_extent_ds_file_path = self.get_datastore_file_path(
            ds_name, self._flat_extent_file_path)

    def get_flat_extent_file_path(self):
        """Get absolute file path of the flat extent."""
        return self._flat_extent_file_path

    def get_flat_extent_ds_file_path(self):
        """Get datastore file path of the flat extent."""
        return self._flat_extent_ds_file_path


class MonolithicSparseVirtualDiskPath(VirtualDiskPath):
    """Paths of file comprising a monolithic sparse disk."""
    pass


class VirtualDiskType(object):
    """Supported virtual disk types."""

    EAGER_ZEROED_THICK = "eagerZeroedThick"
    PREALLOCATED = "preallocated"
    THIN = "thin"

    # thick in extra_spec means lazy-zeroed thick disk
    EXTRA_SPEC_DISK_TYPE_DICT = {'eagerZeroedThick': EAGER_ZEROED_THICK,
                                 'thick': PREALLOCATED,
                                 'thin': THIN
                                 }

    @staticmethod
    def is_valid(extra_spec_disk_type):
        """Check if the given disk type in extra_spec is valid.

        :param extra_spec_disk_type: disk type in extra_spec
        :return: True if valid
        """
        return (extra_spec_disk_type in
                VirtualDiskType.EXTRA_SPEC_DISK_TYPE_DICT)

    @staticmethod
    def validate(extra_spec_disk_type):
        """Validate the given disk type in extra_spec.

        This method throws an instance of InvalidDiskTypeException if the given
        disk type is invalid.

        :param extra_spec_disk_type: disk type in extra_spec
        :raises: InvalidDiskTypeException
        """
        if not VirtualDiskType.is_valid(extra_spec_disk_type):
            raise vmdk_exceptions.InvalidDiskTypeException(
                disk_type=extra_spec_disk_type)

    @staticmethod
    def get_virtual_disk_type(extra_spec_disk_type):
        """Return disk type corresponding to the extra_spec disk type.

        :param extra_spec_disk_type: disk type in extra_spec
        :return: virtual disk type
        :raises: InvalidDiskTypeException
        """
        VirtualDiskType.validate(extra_spec_disk_type)
        return (VirtualDiskType.EXTRA_SPEC_DISK_TYPE_DICT[
                extra_spec_disk_type])


class VirtualDiskAdapterType(object):
    """Supported virtual disk adapter types."""

    LSI_LOGIC = "lsiLogic"
    BUS_LOGIC = "busLogic"
    LSI_LOGIC_SAS = "lsiLogicsas"
    PARA_VIRTUAL = "paraVirtual"
    IDE = "ide"

    @staticmethod
    def is_valid(adapter_type):
        """Check if the given adapter type is valid.

        :param adapter_type: adapter type to check
        :return: True if valid
        """
        return adapter_type in [VirtualDiskAdapterType.LSI_LOGIC,
                                VirtualDiskAdapterType.BUS_LOGIC,
                                VirtualDiskAdapterType.LSI_LOGIC_SAS,
                                VirtualDiskAdapterType.PARA_VIRTUAL,
                                VirtualDiskAdapterType.IDE]

    @staticmethod
    def validate(extra_spec_adapter_type):
        """Validate the given adapter type in extra_spec.

        This method throws an instance of InvalidAdapterTypeException if the
        given adapter type is invalid.

        :param extra_spec_adapter_type: adapter type in extra_spec
        :raises: InvalidAdapterTypeException
        """
        if not VirtualDiskAdapterType.is_valid(extra_spec_adapter_type):
            raise vmdk_exceptions.InvalidAdapterTypeException(
                invalid_type=extra_spec_adapter_type)

    @staticmethod
    def get_adapter_type(extra_spec_adapter):
        """Get the adapter type to be used in VirtualDiskSpec.

        :param extra_spec_adapter: adapter type in the extra_spec
        :return: adapter type to be used in VirtualDiskSpec
        """
        VirtualDiskAdapterType.validate(extra_spec_adapter)
        # We set the adapter type as lsiLogic for lsiLogicsas/paraVirtual
        # since it is not supported by VirtualDiskManager APIs. This won't
        # be a problem because we attach the virtual disk to the correct
        # controller type and the disk adapter type is always resolved using
        # its controller key.
        if (extra_spec_adapter == VirtualDiskAdapterType.LSI_LOGIC_SAS or
                extra_spec_adapter == VirtualDiskAdapterType.PARA_VIRTUAL):
            return VirtualDiskAdapterType.LSI_LOGIC
        else:
            return extra_spec_adapter


class ControllerType(object):
    """Encapsulate various controller types."""

    LSI_LOGIC = 'VirtualLsiLogicController'
    BUS_LOGIC = 'VirtualBusLogicController'
    LSI_LOGIC_SAS = 'VirtualLsiLogicSASController'
    PARA_VIRTUAL = 'ParaVirtualSCSIController'
    IDE = 'VirtualIDEController'

    CONTROLLER_TYPE_DICT = {
        VirtualDiskAdapterType.LSI_LOGIC: LSI_LOGIC,
        VirtualDiskAdapterType.BUS_LOGIC: BUS_LOGIC,
        VirtualDiskAdapterType.LSI_LOGIC_SAS: LSI_LOGIC_SAS,
        VirtualDiskAdapterType.PARA_VIRTUAL: PARA_VIRTUAL,
        VirtualDiskAdapterType.IDE: IDE}

    @staticmethod
    def get_controller_type(adapter_type):
        """Get the disk controller type based on the given adapter type.

        :param adapter_type: disk adapter type
        :return: controller type corresponding to the given adapter type
        :raises: InvalidAdapterTypeException
        """
        if adapter_type in ControllerType.CONTROLLER_TYPE_DICT:
            return ControllerType.CONTROLLER_TYPE_DICT[adapter_type]
        raise vmdk_exceptions.InvalidAdapterTypeException(
            invalid_type=adapter_type)

    @staticmethod
    def is_scsi_controller(controller_type):
        """Check if the given controller is a SCSI controller.

        :param controller_type: controller type
        :return: True if the controller is a SCSI controller
        """
        return controller_type in [ControllerType.LSI_LOGIC,
                                   ControllerType.BUS_LOGIC,
                                   ControllerType.LSI_LOGIC_SAS,
                                   ControllerType.PARA_VIRTUAL]


class VMwareVolumeOps(object):
    """Manages volume operations."""

    def __init__(self, session, max_objects, extension_key, extension_type):
        self._session = session
        self._max_objects = max_objects
        self._extension_key = extension_key
        self._extension_type = extension_type
        self._folder_cache = {}
        self._backing_ref_cache = {}
        self._vmx_version = None

    def set_vmx_version(self, vmx_version):
        self._vmx_version = vmx_version

    def get_backing(self, name, backing_uuid):
        """Get the backing based on name or uuid.

        :param name: Name of the backing
        :param backing_uuid: UUID of the backing
        :return: Managed object reference to the backing
        """

        ref = self.get_backing_by_uuid(backing_uuid)
        if not ref:
            # old version of the driver might have created this backing and
            # hence cannot be queried by uuid
            LOG.debug("Returning cached ref for %s.", name)
            ref = self._backing_ref_cache.get(name)

        LOG.debug("Backing (%(name)s, %(uuid)s) ref: %(ref)s.",
                  {'name': name, 'uuid': backing_uuid, 'ref': ref})
        return ref

    def get_backing_by_uuid(self, uuid):
        LOG.debug("Get ref by UUID: %s.", uuid)
        result = self._session.invoke_api(
            self._session.vim,
            'FindAllByUuid',
            self._session.vim.service_content.searchIndex,
            uuid=uuid,
            vmSearch=True,
            instanceUuid=True)
        if result:
            return result[0]

    def build_backing_ref_cache(self, name_regex=None):

        LOG.debug("Building backing ref cache.")
        result = self._session.invoke_api(
            vim_util,
            'get_objects',
            self._session.vim,
            'VirtualMachine',
            self._max_objects,
            properties_to_collect=[
                'name',
                'config.instanceUuid',
                'config.extraConfig["cinder.volume.id"]'])

        while result:
            for backing in result.objects:
                instance_uuid = None
                vol_id = None

                for prop in backing.propSet:
                    if prop.name == 'name':
                        name = prop.val
                    elif prop.name == 'config.instanceUuid':
                        instance_uuid = prop.val
                    else:
                        vol_id = prop.val.value

                if name_regex and not name_regex.match(name):
                    continue

                if instance_uuid and instance_uuid == vol_id:
                    # no need to cache backing with UUID set to volume ID
                    continue

                self._backing_ref_cache[name] = backing.obj

            result = self.continue_retrieval(result)
        LOG.debug("Backing ref cache size: %d.", len(self._backing_ref_cache))

    def delete_backing(self, backing):
        """Delete the backing.

        :param backing: Managed object reference to the backing
        """
        LOG.debug("Deleting the VM backing: %s.", backing)
        task = self._session.invoke_api(self._session.vim, 'Destroy_Task',
                                        backing)
        LOG.debug("Initiated deletion of VM backing: %s.", backing)
        self._session.wait_for_task(task)
        LOG.info("Deleted the VM backing: %s.", backing)

    # TODO(kartikaditya) Keep the methods not specific to volume in
    # a different file
    def get_host(self, instance):
        """Get host under which instance is present.

        :param instance: Managed object reference of the instance VM
        :return: Host managing the instance VM
        """
        return self._session.invoke_api(vim_util, 'get_object_property',
                                        self._session.vim, instance,
                                        'runtime.host')

    def get_hosts(self):
        """Get all host from the inventory.

        :return: All the hosts from the inventory
        """
        return self._session.invoke_api(vim_util, 'get_objects',
                                        self._session.vim,
                                        'HostSystem', self._max_objects)

    def continue_retrieval(self, retrieve_result):
        """Continue retrieval of results if necessary.

        :param retrieve_result: Result from RetrievePropertiesEx
        """

        return self._session.invoke_api(vim_util, 'continue_retrieval',
                                        self._session.vim, retrieve_result)

    def cancel_retrieval(self, retrieve_result):
        """Cancel retrieval of results if necessary.

        :param retrieve_result: Result from RetrievePropertiesEx
        """

        self._session.invoke_api(vim_util, 'cancel_retrieval',
                                 self._session.vim, retrieve_result)

    # TODO(vbala): move this method to datastore module
    def _is_usable(self, mount_info):
        """Check if a datastore is usable as per the given mount info.

        The datastore is considered to be usable for a host only if it is
        writable, mounted and accessible.

        :param mount_info: Host mount information
        :return: True if datastore is usable
        """
        writable = mount_info.accessMode == 'readWrite'
        # If mounted attribute is not set, then default is True
        mounted = getattr(mount_info, 'mounted', True)
        # If accessible attribute is not set, then default is False
        accessible = getattr(mount_info, 'accessible', False)

        return writable and mounted and accessible

    def get_connected_hosts(self, datastore):
        """Get all the hosts to which the datastore is connected and usable.

        The datastore is considered to be usable for a host only if it is
        writable, mounted and accessible.

        :param datastore: Reference to the datastore entity
        :return: List of managed object references of all connected
                 hosts
        """
        summary = self.get_summary(datastore)
        if not summary.accessible:
            return []

        host_mounts = self._session.invoke_api(vim_util, 'get_object_property',
                                               self._session.vim, datastore,
                                               'host')
        if not hasattr(host_mounts, 'DatastoreHostMount'):
            return []

        connected_hosts = []
        for host_mount in host_mounts.DatastoreHostMount:
            if self._is_usable(host_mount.mountInfo):
                host_mount_key_value = vim_util.get_moref_value(host_mount.key)
                connected_hosts.append(host_mount_key_value)

        return connected_hosts

    def is_datastore_accessible(self, datastore, host):
        """Check if the datastore is accessible to the given host.

        :param datastore: datastore reference
        :return: True if the datastore is accessible
        """
        hosts = self.get_connected_hosts(datastore)
        return vim_util.get_moref_value(host) in hosts

    # TODO(vbala): move this method to datastore module
    def _in_maintenance(self, summary):
        """Check if a datastore is entering maintenance or in maintenance.

        :param summary: Summary information about the datastore
        :return: True if the datastore is entering maintenance or in
                 maintenance
        """
        if hasattr(summary, 'maintenanceMode'):
            return summary.maintenanceMode in ['enteringMaintenance',
                                               'inMaintenance']
        return False

    def _get_parent(self, child, parent_type):
        """Get immediate parent of given type via 'parent' property.

        :param child: Child entity reference
        :param parent_type: Entity type of the parent
        :return: Immediate parent of specific type up the hierarchy via
                 'parent' property
        """

        if not child:
            return None
        if child._type == parent_type:
            return child
        parent = self._session.invoke_api(vim_util, 'get_object_property',
                                          self._session.vim, child, 'parent')
        return self._get_parent(parent, parent_type)

    def get_dc(self, child):
        """Get parent datacenter up the hierarchy via 'parent' property.

        :param child: Reference of the child entity
        :return: Parent Datacenter of the param child entity
        """
        return self._get_parent(child, 'Datacenter')

    def get_vmfolder(self, datacenter):
        """Get the vmFolder.

        :param datacenter: Reference to the datacenter entity
        :return: vmFolder property of the datacenter
        """
        return self._session.invoke_api(vim_util, 'get_object_property',
                                        self._session.vim, datacenter,
                                        'vmFolder')

    def _get_child_folder(self, parent_folder, child_folder_name):
        LOG.debug("Finding child folder: %s.", child_folder_name)
        # Get list of child entities for the parent folder
        prop_val = self._session.invoke_api(vim_util, 'get_object_property',
                                            self._session.vim, parent_folder,
                                            'childEntity')

        if prop_val and hasattr(prop_val, 'ManagedObjectReference'):
            child_entities = prop_val.ManagedObjectReference

            # Return if the child folder with input name is already present
            for child_entity in child_entities:
                if child_entity._type != 'Folder':
                    continue
                child_entity_name = self.get_entity_name(child_entity)
                if (child_entity_name
                    and (urllib.parse.unquote(child_entity_name)
                         == child_folder_name)):
                    return child_entity

    def create_folder(self, parent_folder, child_folder_name):
        """Creates child folder under the given parent folder.

        :param parent_folder: Reference to the parent folder
        :param child_folder_name: Name of the child folder
        :return: Reference to the child folder
        """
        LOG.debug("Creating folder: %(child_folder_name)s under parent "
                  "folder: %(parent_folder)s.",
                  {'child_folder_name': child_folder_name,
                   'parent_folder': parent_folder})

        try:
            child_folder = self._session.invoke_api(self._session.vim,
                                                    'CreateFolder',
                                                    parent_folder,
                                                    name=child_folder_name)
            LOG.debug("Created child folder: %s.", child_folder)
        except exceptions.DuplicateName:
            # Another thread is trying to create the same folder, ignore
            # the exception.
            LOG.debug('Folder: %s already exists.', child_folder_name)
            child_folder = self._get_child_folder(parent_folder,
                                                  child_folder_name)
        return child_folder

    def create_vm_inventory_folder(self, datacenter, path_comp):
        """Create and return a VM inventory folder.

        This method caches references to inventory folders returned.

        :param datacenter: Reference to datacenter
        :param path_comp: Path components as a list
        """
        LOG.debug("Creating inventory folder: %(path_comp)s under VM folder "
                  "of datacenter: %(datacenter)s.",
                  {'path_comp': path_comp,
                   'datacenter': datacenter})
        path = "/" + vim_util.get_moref_value(datacenter)
        parent = self._folder_cache.get(path)
        if not parent:
            parent = self.get_vmfolder(datacenter)
            self._folder_cache[path] = parent

        folder = None
        for folder_name in path_comp:
            path = "/".join([path, folder_name])
            folder = self._folder_cache.get(path)
            if not folder:
                folder = self.create_folder(parent, folder_name)
                self._folder_cache[path] = folder
            parent = folder

        LOG.debug("Inventory folder for path: %(path)s is %(folder)s.",
                  {'path': path,
                   'folder': folder})
        return folder

    def extend_virtual_disk(self, requested_size_in_gb, path, dc_ref,
                            eager_zero=False):
        """Extend the virtual disk to the requested size.

        :param requested_size_in_gb: Size of the volume in GB
        :param path: Datastore path of the virtual disk to extend
        :param dc_ref: Reference to datacenter
        :param eager_zero: Boolean determining if the free space
                           is zeroed out
        """
        LOG.debug("Extending virtual disk: %(path)s to %(size)s GB.",
                  {'path': path, 'size': requested_size_in_gb})
        diskMgr = self._session.vim.service_content.virtualDiskManager

        # VMware API needs the capacity unit to be in KB, so convert the
        # capacity unit from GB to KB.
        size_in_kb = requested_size_in_gb * units.Mi
        task = self._session.invoke_api(self._session.vim,
                                        "ExtendVirtualDisk_Task",
                                        diskMgr,
                                        name=path,
                                        datacenter=dc_ref,
                                        newCapacityKb=size_in_kb,
                                        eagerZero=eager_zero)
        self._session.wait_for_task(task)
        LOG.info("Successfully extended virtual disk: %(path)s to "
                 "%(size)s GB.",
                 {'path': path, 'size': requested_size_in_gb})

    def _create_controller_config_spec(self, adapter_type):
        """Returns config spec for adding a disk controller."""
        cf = self._session.vim.client.factory

        controller_type = ControllerType.get_controller_type(adapter_type)
        controller_device = cf.create('ns0:%s' % controller_type)
        controller_device.key = -100
        controller_device.busNumber = 0
        if ControllerType.is_scsi_controller(controller_type):
            controller_device.sharedBus = 'noSharing'

        controller_spec = cf.create('ns0:VirtualDeviceConfigSpec')
        controller_spec.operation = 'add'
        controller_spec.device = controller_device
        return controller_spec

    def _create_disk_backing(self, disk_type, vmdk_ds_file_path):
        """Creates file backing for virtual disk."""
        cf = self._session.vim.client.factory
        disk_device_bkng = cf.create('ns0:VirtualDiskFlatVer2BackingInfo')

        if disk_type == VirtualDiskType.EAGER_ZEROED_THICK:
            disk_device_bkng.eagerlyScrub = True
        elif disk_type == VirtualDiskType.THIN:
            disk_device_bkng.thinProvisioned = True

        disk_device_bkng.fileName = vmdk_ds_file_path or ''
        disk_device_bkng.diskMode = 'persistent'

        return disk_device_bkng

    def _create_virtual_disk_config_spec(self, size_kb, disk_type,
                                         controller_key, profile_id,
                                         vmdk_ds_file_path):
        """Returns config spec for adding a virtual disk."""
        cf = self._session.vim.client.factory

        disk_device = cf.create('ns0:VirtualDisk')
        # disk size should be at least 1024KB
        disk_device.capacityInKB = max(units.Ki, int(size_kb))
        if controller_key < 0:
            disk_device.key = controller_key - 1
        else:
            disk_device.key = -101
        disk_device.unitNumber = 0
        disk_device.controllerKey = controller_key
        disk_device.backing = self._create_disk_backing(disk_type,
                                                        vmdk_ds_file_path)

        disk_spec = cf.create('ns0:VirtualDeviceConfigSpec')
        disk_spec.operation = 'add'
        if vmdk_ds_file_path is None:
            disk_spec.fileOperation = 'create'
        disk_spec.device = disk_device
        if profile_id:
            disk_profile = cf.create('ns0:VirtualMachineDefinedProfileSpec')
            disk_profile.profileId = profile_id
            disk_spec.profile = [disk_profile]

        return disk_spec

    def _create_specs_for_disk_add(self, size_kb, disk_type, adapter_type,
                                   profile_id, vmdk_ds_file_path=None):
        """Create controller and disk config specs for adding a new disk.

        :param size_kb: disk size in KB
        :param disk_type: disk provisioning type
        :param adapter_type: disk adapter type
        :param profile_id: storage policy profile identification
        :param vmdk_ds_file_path: Optional datastore file path of an existing
                                  virtual disk. If specified, file backing is
                                  not created for the virtual disk.
        :return: list containing controller and disk config specs
        """
        controller_spec = None
        if adapter_type == 'ide':
            # For IDE disks, use one of the default IDE controllers (with keys
            # 200 and 201) created as part of backing VM creation.
            controller_key = 200
        else:
            controller_spec = self._create_controller_config_spec(adapter_type)
            controller_key = controller_spec.device.key

        disk_spec = self._create_virtual_disk_config_spec(size_kb,
                                                          disk_type,
                                                          controller_key,
                                                          profile_id,
                                                          vmdk_ds_file_path)
        specs = [disk_spec]
        if controller_spec is not None:
            specs.append(controller_spec)
        return specs

    def _get_extra_config_option_values(self, extra_config):

        cf = self._session.vim.client.factory
        option_values = []

        for key, value in extra_config.items():
            opt = cf.create('ns0:OptionValue')
            opt.key = key
            opt.value = value
            option_values.append(opt)

        return option_values

    def _create_managed_by_info(self):
        managed_by = self._session.vim.client.factory.create(
            'ns0:ManagedByInfo')
        managed_by.extensionKey = self._extension_key
        managed_by.type = self._extension_type
        return managed_by

    def _get_create_spec_disk_less(self, name, ds_name, profileId=None,
                                   extra_config=None):
        """Return spec for creating disk-less backing.

        :param name: Name of the backing
        :param ds_name: Datastore name where the disk is to be provisioned
        :param profileId: Storage profile ID for the backing
        :param extra_config: Key-value pairs to be written to backing's
                             extra-config
        :return: Spec for creation
        """
        cf = self._session.vim.client.factory
        vm_file_info = cf.create('ns0:VirtualMachineFileInfo')
        vm_file_info.vmPathName = '[%s]' % ds_name

        create_spec = cf.create('ns0:VirtualMachineConfigSpec')
        create_spec.name = name
        create_spec.guestId = 'otherGuest'
        create_spec.numCPUs = 1
        create_spec.memoryMB = 128
        create_spec.files = vm_file_info
        # Set the default hardware version to a compatible version supported by
        # vSphere 5.0. This will ensure that the backing VM can be migrated
        # without any incompatibility issues in a mixed cluster of ESX hosts
        # with versions 5.0 or above.
        create_spec.version = self._vmx_version or "vmx-08"

        if profileId:
            vmProfile = cf.create('ns0:VirtualMachineDefinedProfileSpec')
            vmProfile.profileId = profileId
            create_spec.vmProfile = [vmProfile]

        if extra_config:
            if BACKING_UUID_KEY in extra_config:
                create_spec.instanceUuid = extra_config.pop(BACKING_UUID_KEY)
            create_spec.extraConfig = self._get_extra_config_option_values(
                extra_config)

        create_spec.managedBy = self._create_managed_by_info()
        return create_spec

    def get_create_spec(self, name, size_kb, disk_type, ds_name,
                        profile_id=None, adapter_type='lsiLogic',
                        extra_config=None):
        """Return spec for creating backing with a single disk.

        :param name: name of the backing
        :param size_kb: disk size in KB
        :param disk_type: disk provisioning type
        :param ds_name: datastore name where the disk is to be provisioned
        :param profile_id: storage policy profile identification
        :param adapter_type: disk adapter type
        :param extra_config: key-value pairs to be written to backing's
                             extra-config
        :return: spec for creation
        """
        create_spec = self._get_create_spec_disk_less(
            name, ds_name, profileId=profile_id, extra_config=extra_config)
        create_spec.deviceChange = self._create_specs_for_disk_add(
            size_kb, disk_type, adapter_type, profile_id)
        return create_spec

    def _create_backing_int(self, folder, resource_pool, host, create_spec):
        """Helper for create backing methods."""
        LOG.debug("Creating volume backing with spec: %s.", create_spec)
        task = self._session.invoke_api(self._session.vim, 'CreateVM_Task',
                                        folder, config=create_spec,
                                        pool=resource_pool, host=host)
        task_info = self._session.wait_for_task(task)
        backing = task_info.result
        LOG.info("Successfully created volume backing: %s.", backing)
        return backing

    def create_backing(self, name, size_kb, disk_type, folder, resource_pool,
                       host, ds_name, profileId=None, adapter_type='lsiLogic',
                       extra_config=None):
        """Create backing for the volume.

        Creates a VM with one VMDK based on the given inputs.

        :param name: Name of the backing
        :param size_kb: Size in KB of the backing
        :param disk_type: VMDK type for the disk
        :param folder: Folder, where to create the backing under
        :param resource_pool: Resource pool reference
        :param host: Host reference
        :param ds_name: Datastore name where the disk is to be provisioned
        :param profileId: Storage profile ID to be associated with backing
        :param adapter_type: Disk adapter type
        :param extra_config: Key-value pairs to be written to backing's
                             extra-config
        :return: Reference to the created backing entity
        """
        LOG.debug("Creating volume backing with name: %(name)s "
                  "disk_type: %(disk_type)s size_kb: %(size_kb)s "
                  "adapter_type: %(adapter_type)s profileId: %(profile)s at "
                  "folder: %(folder)s resource_pool: %(resource_pool)s "
                  "host: %(host)s datastore_name: %(ds_name)s.",
                  {'name': name, 'disk_type': disk_type, 'size_kb': size_kb,
                   'folder': folder, 'resource_pool': resource_pool,
                   'ds_name': ds_name, 'profile': profileId, 'host': host,
                   'adapter_type': adapter_type})

        create_spec = self.get_create_spec(
            name, size_kb, disk_type, ds_name, profile_id=profileId,
            adapter_type=adapter_type, extra_config=extra_config)
        return self._create_backing_int(folder, resource_pool, host,
                                        create_spec)

    def create_backing_disk_less(self, name, folder, resource_pool,
                                 host, ds_name, profileId=None,
                                 extra_config=None):
        """Create disk-less volume backing.

        This type of backing is useful for creating volume from image. The
        downloaded image from the image service can be copied to a virtual
        disk of desired provisioning type and added to the backing VM.

        :param name: Name of the backing
        :param folder: Folder where the backing is created
        :param resource_pool: Resource pool reference
        :param host: Host reference
        :param ds_name: Name of the datastore used for VM storage
        :param profileId: Storage profile ID to be associated with backing
        :param extra_config: Key-value pairs to be written to backing's
                             extra-config
        :return: Reference to the created backing entity
        """
        LOG.debug("Creating disk-less volume backing with name: %(name)s "
                  "profileId: %(profile)s at folder: %(folder)s "
                  "resource pool: %(resource_pool)s host: %(host)s "
                  "datastore_name: %(ds_name)s.",
                  {'name': name, 'profile': profileId, 'folder': folder,
                   'resource_pool': resource_pool, 'host': host,
                   'ds_name': ds_name})

        create_spec = self._get_create_spec_disk_less(
            name, ds_name, profileId=profileId, extra_config=extra_config)
        return self._create_backing_int(folder, resource_pool, host,
                                        create_spec)

    def get_datastore(self, backing):
        """Get datastore where the backing resides.

        :param backing: Reference to the backing
        :return: Datastore reference to which the backing belongs
        """
        return self._session.invoke_api(vim_util, 'get_object_property',
                                        self._session.vim, backing,
                                        'datastore').ManagedObjectReference[0]

    def get_summary(self, datastore):
        """Get datastore summary.

        :param datastore: Reference to the datastore
        :return: 'summary' property of the datastore
        """
        return self._session.invoke_api(vim_util, 'get_object_property',
                                        self._session.vim, datastore,
                                        'summary')

    def _create_relocate_spec_disk_locator(self, datastore, disk_type,
                                           disk_device):
        """Creates spec for disk type conversion during relocate."""
        cf = self._session.vim.client.factory
        disk_locator = cf.create("ns0:VirtualMachineRelocateSpecDiskLocator")
        disk_locator.datastore = datastore
        disk_locator.diskId = disk_device.key
        disk_locator.diskBackingInfo = self._create_disk_backing(disk_type,
                                                                 None)
        return disk_locator

    def _get_relocate_spec(self, datastore, resource_pool, host,
                           disk_move_type, disk_type=None, disk_device=None):
        """Return spec for relocating volume backing.

        :param datastore: Reference to the datastore
        :param resource_pool: Reference to the resource pool
        :param host: Reference to the host
        :param disk_move_type: Disk move type option
        :param disk_type: Destination disk type
        :param disk_device: Virtual device corresponding to the disk
        :return: Spec for relocation
        """
        cf = self._session.vim.client.factory
        relocate_spec = cf.create('ns0:VirtualMachineRelocateSpec')
        relocate_spec.datastore = datastore
        relocate_spec.pool = resource_pool
        relocate_spec.host = host
        relocate_spec.diskMoveType = disk_move_type

        if disk_type is not None and disk_device is not None:
            disk_locator = self._create_relocate_spec_disk_locator(datastore,
                                                                   disk_type,
                                                                   disk_device)
            relocate_spec.disk = [disk_locator]

        LOG.debug("Spec for relocating the backing: %s.", relocate_spec)
        return relocate_spec

    def relocate_backing(
            self, backing, datastore, resource_pool, host, disk_type=None):
        """Relocates backing to the input datastore and resource pool.

        The implementation uses moveAllDiskBackingsAndAllowSharing disk move
        type.

        :param backing: Reference to the backing
        :param datastore: Reference to the datastore
        :param resource_pool: Reference to the resource pool
        :param host: Reference to the host
        :param disk_type: destination disk type
        """
        LOG.debug("Relocating backing: %(backing)s to datastore: %(ds)s "
                  "and resource pool: %(rp)s with destination disk type: "
                  "%(disk_type)s.",
                  {'backing': backing,
                   'ds': datastore,
                   'rp': resource_pool,
                   'disk_type': disk_type})

        # Relocate the volume backing
        disk_move_type = 'moveAllDiskBackingsAndAllowSharing'

        disk_device = None
        if disk_type is not None:
            disk_device = self._get_disk_device(backing)

        relocate_spec = self._get_relocate_spec(datastore, resource_pool, host,
                                                disk_move_type, disk_type,
                                                disk_device)

        task = self._session.invoke_api(self._session.vim, 'RelocateVM_Task',
                                        backing, spec=relocate_spec)
        LOG.debug("Initiated relocation of volume backing: %s.", backing)
        self._session.wait_for_task(task)
        LOG.info("Successfully relocated volume backing: %(backing)s "
                 "to datastore: %(ds)s and resource pool: %(rp)s.",
                 {'backing': backing, 'ds': datastore, 'rp': resource_pool})

    def move_backing_to_folder(self, backing, folder):
        """Move the volume backing to the folder.

        :param backing: Reference to the backing
        :param folder: Reference to the folder
        """
        LOG.debug("Moving backing: %(backing)s to folder: %(fol)s.",
                  {'backing': backing, 'fol': folder})
        task = self._session.invoke_api(self._session.vim,
                                        'MoveIntoFolder_Task', folder,
                                        list=[backing])
        LOG.debug("Initiated move of volume backing: %(backing)s into the "
                  "folder: %(fol)s.", {'backing': backing, 'fol': folder})
        self._session.wait_for_task(task)
        LOG.info("Successfully moved volume "
                 "backing: %(backing)s into the "
                 "folder: %(fol)s.", {'backing': backing, 'fol': folder})

    def create_snapshot(self, backing, name, description, quiesce=False):
        """Create snapshot of the backing with given name and description.

        :param backing: Reference to the backing entity
        :param name: Snapshot name
        :param description: Snapshot description
        :param quiesce: Whether to quiesce the backing when taking snapshot
        :return: Created snapshot entity reference
        """
        LOG.debug("Snapshoting backing: %(backing)s with name: %(name)s.",
                  {'backing': backing, 'name': name})
        task = self._session.invoke_api(self._session.vim,
                                        'CreateSnapshot_Task',
                                        backing, name=name,
                                        description=description,
                                        memory=False, quiesce=quiesce)
        LOG.debug("Initiated snapshot of volume backing: %(backing)s "
                  "named: %(name)s.", {'backing': backing, 'name': name})
        task_info = self._session.wait_for_task(task)
        snapshot = task_info.result
        LOG.info("Successfully created snapshot: %(snap)s for volume "
                 "backing: %(backing)s.",
                 {'snap': snapshot, 'backing': backing})
        return snapshot

    @staticmethod
    def _get_snapshot_from_tree(name, root):
        """Get snapshot by name from the snapshot tree root.

        :param name: Snapshot name
        :param root: Current root node in the snapshot tree
        :return: None in the snapshot tree with given snapshot name
        """
        if not root:
            return None
        if root.name == name:
            return root.snapshot
        if (not hasattr(root, 'childSnapshotList') or
                not root.childSnapshotList):
            # When root does not have children, the childSnapshotList attr
            # is missing sometime. Adding an additional check.
            return None
        for node in root.childSnapshotList:
            snapshot = VMwareVolumeOps._get_snapshot_from_tree(name, node)
            if snapshot:
                return snapshot

    def get_snapshot(self, backing, name):
        """Get snapshot of the backing with given name.

        :param backing: Reference to the backing entity
        :param name: Snapshot name
        :return: Snapshot entity of the backing with given name
        """
        snapshot = self._session.invoke_api(vim_util, 'get_object_property',
                                            self._session.vim, backing,
                                            'snapshot')
        if not snapshot or not snapshot.rootSnapshotList:
            return None
        for root in snapshot.rootSnapshotList:
            return VMwareVolumeOps._get_snapshot_from_tree(name, root)

    def snapshot_exists(self, backing):
        """Check if the given backing contains snapshots."""
        snapshot = self._session.invoke_api(vim_util, 'get_object_property',
                                            self._session.vim, backing,
                                            'snapshot')
        if snapshot is None or snapshot.rootSnapshotList is None:
            return False
        return len(snapshot.rootSnapshotList) != 0

    def delete_snapshot(self, backing, name):
        """Delete a given snapshot from volume backing.

        :param backing: Reference to the backing entity
        :param name: Snapshot name
        """
        LOG.debug("Deleting the snapshot: %(name)s from backing: "
                  "%(backing)s.",
                  {'name': name, 'backing': backing})
        snapshot = self.get_snapshot(backing, name)
        if not snapshot:
            LOG.info("Did not find the snapshot: %(name)s for backing: "
                     "%(backing)s. Need not delete anything.",
                     {'name': name, 'backing': backing})
            return
        task = self._session.invoke_api(self._session.vim,
                                        'RemoveSnapshot_Task',
                                        snapshot, removeChildren=False)
        LOG.debug("Initiated snapshot: %(name)s deletion for backing: "
                  "%(backing)s.",
                  {'name': name, 'backing': backing})
        self._session.wait_for_task(task)
        LOG.info("Successfully deleted snapshot: %(name)s of backing: "
                 "%(backing)s.", {'backing': backing, 'name': name})

    def revert_to_snapshot(self, backing, name):
        LOG.debug("Revert to snapshot: %(name)s of backing: %(backing)s.",
                  {'name': name, 'backing': backing})

        snapshot = self.get_snapshot(backing, name)
        if not snapshot:
            raise vmdk_exceptions.SnapshotNotFoundException(
                name=name)

        task = self._session.invoke_api(self._session.vim,
                                        'RevertToSnapshot_Task',
                                        snapshot)
        self._session.wait_for_task(task)

    def _get_folder(self, backing):
        """Get parent folder of the backing.

        :param backing: Reference to the backing entity
        :return: Reference to parent folder of the backing entity
        """
        return self._get_parent(backing, 'Folder')

    def _get_clone_spec(self, datastore, disk_move_type, snapshot, backing,
                        disk_type, host=None, resource_pool=None,
                        extra_config=None, disks_to_clone=None):
        """Get the clone spec.

        :param datastore: Reference to datastore
        :param disk_move_type: Disk move type
        :param snapshot: Reference to snapshot
        :param backing: Source backing VM
        :param disk_type: Disk type of clone
        :param host: Target host
        :param resource_pool: Target resource pool
        :param extra_config: Key-value pairs to be written to backing's
                             extra-config
        :param disks_to_clone: UUIDs of disks to clone
        :return: Clone spec
        """
        if disk_type is not None:
            disk_device = self._get_disk_device(backing)
        else:
            disk_device = None

        relocate_spec = self._get_relocate_spec(datastore, resource_pool, host,
                                                disk_move_type, disk_type,
                                                disk_device)
        cf = self._session.vim.client.factory
        clone_spec = cf.create('ns0:VirtualMachineCloneSpec')
        clone_spec.location = relocate_spec
        clone_spec.powerOn = False
        clone_spec.template = False
        clone_spec.snapshot = snapshot

        config_spec = cf.create('ns0:VirtualMachineConfigSpec')
        config_spec.managedBy = self._create_managed_by_info()
        clone_spec.config = config_spec

        if extra_config:
            if BACKING_UUID_KEY in extra_config:
                config_spec.instanceUuid = extra_config.pop(BACKING_UUID_KEY)
            config_spec.extraConfig = self._get_extra_config_option_values(
                extra_config)

        if disks_to_clone:
            config_spec.deviceChange = (
                self._create_device_change_for_disk_removal(
                    backing, disks_to_clone))

        LOG.debug("Spec for cloning the backing: %s.", clone_spec)
        return clone_spec

    def _create_device_change_for_disk_removal(self, backing, disks_to_clone):
        disk_devices = self._get_disk_devices(backing)

        device_change = []
        for device in disk_devices:
            if device.backing.uuid not in disks_to_clone:
                device_change.append(self._create_spec_for_disk_remove(device))

        return device_change

    def clone_backing(self, name, backing, snapshot, clone_type, datastore,
                      disk_type=None, host=None, resource_pool=None,
                      extra_config=None, folder=None, disks_to_clone=None):
        """Clone backing.

        If the clone_type is 'full', then a full clone of the source volume
        backing will be created. Else, if it is 'linked', then a linked clone
        of the source volume backing will be created.

        :param name: Name for the clone
        :param backing: Reference to the backing entity
        :param snapshot: Snapshot point from which the clone should be done
        :param clone_type: Whether a full clone or linked clone is to be made
        :param datastore: Reference to the datastore entity
        :param disk_type: Disk type of the clone
        :param host: Target host
        :param resource_pool: Target resource pool
        :param extra_config: Key-value pairs to be written to backing's
                             extra-config
        :param folder: The location of the clone
        :param disks_to_clone: UUIDs of disks to clone
        """
        LOG.debug("Creating a clone of backing: %(back)s, named: %(name)s, "
                  "clone type: %(type)s from snapshot: %(snap)s on "
                  "resource pool: %(resource_pool)s, host: %(host)s, "
                  "datastore: %(ds)s with disk type: %(disk_type)s.",
                  {'back': backing, 'name': name, 'type': clone_type,
                   'snap': snapshot, 'ds': datastore, 'disk_type': disk_type,
                   'host': host, 'resource_pool': resource_pool})

        if folder is None:
            # Use source folder as the location of the clone.
            folder = self._get_folder(backing)

        if clone_type == LINKED_CLONE_TYPE:
            disk_move_type = 'createNewChildDiskBacking'
        else:
            disk_move_type = 'moveAllDiskBackingsAndDisallowSharing'
        clone_spec = self._get_clone_spec(
            datastore, disk_move_type, snapshot, backing, disk_type, host=host,
            resource_pool=resource_pool, extra_config=extra_config,
            disks_to_clone=disks_to_clone)

        task = self._session.invoke_api(self._session.vim, 'CloneVM_Task',
                                        backing, folder=folder, name=name,
                                        spec=clone_spec)
        LOG.debug("Initiated clone of backing: %s.", name)
        task_info = self._session.wait_for_task(task)
        new_backing = task_info.result
        LOG.info("Successfully created clone: %s.", new_backing)
        return new_backing

    def _reconfigure_backing(self, backing, reconfig_spec):
        """Reconfigure backing VM with the given spec."""
        LOG.debug("Reconfiguring backing VM: %(backing)s with spec: %(spec)s.",
                  {'backing': backing,
                   'spec': reconfig_spec})
        reconfig_task = self._session.invoke_api(self._session.vim,
                                                 "ReconfigVM_Task",
                                                 backing,
                                                 spec=reconfig_spec)
        LOG.debug("Task: %s created for reconfiguring backing VM.",
                  reconfig_task)
        self._session.wait_for_task(reconfig_task)

    def _get_controller(self, backing, adapter_type):
        devices = self._session.invoke_api(vim_util,
                                           'get_object_property',
                                           self._session.vim,
                                           backing,
                                           'config.hardware.device')

        controller_type = ControllerType.get_controller_type(adapter_type)
        for device in devices:
            if device.__class__.__name__ == controller_type:
                return device

    def attach_disk_to_backing(self, backing, size_in_kb, disk_type,
                               adapter_type, profile_id, vmdk_ds_file_path):
        """Attach an existing virtual disk to the backing VM.

        :param backing: reference to the backing VM
        :param size_in_kb: disk size in KB
        :param disk_type: virtual disk type
        :param adapter_type: disk adapter type
        :param profile_id: storage policy profile identification
        :param vmdk_ds_file_path: datastore file path of the virtual disk to
                                  be attached
        """
        LOG.debug("Reconfiguring backing VM: %(backing)s to add new disk: "
                  "%(path)s with size (KB): %(size)d and adapter type: "
                  "%(adapter_type)s.",
                  {'backing': backing,
                   'path': vmdk_ds_file_path,
                   'size': size_in_kb,
                   'adapter_type': adapter_type})
        cf = self._session.vim.client.factory
        reconfig_spec = cf.create('ns0:VirtualMachineConfigSpec')

        controller = self._get_controller(backing, adapter_type)
        if controller:
            disk_spec = self._create_virtual_disk_config_spec(
                size_in_kb,
                disk_type,
                controller.key,
                profile_id,
                vmdk_ds_file_path)
            specs = [disk_spec]
        else:
            specs = self._create_specs_for_disk_add(
                size_in_kb,
                disk_type,
                adapter_type,
                profile_id,
                vmdk_ds_file_path=vmdk_ds_file_path)
        reconfig_spec.deviceChange = specs
        self._reconfigure_backing(backing, reconfig_spec)
        LOG.debug("Backing VM: %s reconfigured with new disk.", backing)

    def _create_spec_for_disk_remove(self, disk_device):
        cf = self._session.vim.client.factory
        disk_spec = cf.create('ns0:VirtualDeviceConfigSpec')
        disk_spec.operation = 'remove'
        disk_spec.device = disk_device
        return disk_spec

    def detach_disk_from_backing(self, backing, disk_device):
        """Detach the given disk from backing."""

        LOG.debug("Reconfiguring backing VM: %(backing)s to remove disk: "
                  "%(disk_device)s.",
                  {'backing': backing, 'disk_device': disk_device})

        cf = self._session.vim.client.factory
        reconfig_spec = cf.create('ns0:VirtualMachineConfigSpec')
        spec = self._create_spec_for_disk_remove(disk_device)
        reconfig_spec.deviceChange = [spec]
        self._reconfigure_backing(backing, reconfig_spec)

    def rename_backing(self, backing, new_name):
        """Rename backing VM.

        :param backing: VM to be renamed
        :param new_name: new VM name
        """
        LOG.info("Renaming backing VM: %(backing)s to %(new_name)s.",
                 {'backing': backing,
                  'new_name': new_name})
        rename_task = self._session.invoke_api(self._session.vim,
                                               "Rename_Task",
                                               backing,
                                               newName=new_name)
        LOG.debug("Task: %s created for renaming VM.", rename_task)
        self._session.wait_for_task(rename_task)
        LOG.info("Backing VM: %(backing)s renamed to %(new_name)s.",
                 {'backing': backing,
                  'new_name': new_name})

    def change_backing_profile(self, backing, profile_id):
        """Change storage profile of the backing VM.

        The current profile is removed if the new profile is None.
        """
        LOG.debug("Reconfiguring backing VM: %(backing)s to change profile to:"
                  " %(profile)s.",
                  {'backing': backing,
                   'profile': profile_id})
        cf = self._session.vim.client.factory

        if profile_id is None:
            vm_profile = cf.create('ns0:VirtualMachineEmptyProfileSpec')
        else:
            vm_profile = cf.create('ns0:VirtualMachineDefinedProfileSpec')
            vm_profile.profileId = profile_id.uniqueId

        reconfig_spec = cf.create('ns0:VirtualMachineConfigSpec')
        reconfig_spec.vmProfile = [vm_profile]

        disk_device = self._get_disk_device(backing)
        disk_spec = cf.create('ns0:VirtualDeviceConfigSpec')
        disk_spec.device = disk_device
        disk_spec.operation = 'edit'
        disk_spec.profile = [vm_profile]
        reconfig_spec.deviceChange = [disk_spec]

        self._reconfigure_backing(backing, reconfig_spec)
        LOG.debug("Backing VM: %(backing)s reconfigured with new profile: "
                  "%(profile)s.",
                  {'backing': backing,
                   'profile': profile_id})

    def update_backing_disk_uuid(self, backing, disk_uuid):
        """Update backing VM's disk UUID.

        :param backing: Reference to backing VM
        :param disk_uuid: New disk UUID
        """
        LOG.debug("Reconfiguring backing VM: %(backing)s to change disk UUID "
                  "to: %(disk_uuid)s.",
                  {'backing': backing,
                   'disk_uuid': disk_uuid})

        disk_device = self._get_disk_device(backing)
        disk_device.backing.uuid = disk_uuid

        cf = self._session.vim.client.factory
        disk_spec = cf.create('ns0:VirtualDeviceConfigSpec')
        disk_spec.device = disk_device
        disk_spec.operation = 'edit'

        reconfig_spec = cf.create('ns0:VirtualMachineConfigSpec')
        reconfig_spec.deviceChange = [disk_spec]
        self._reconfigure_backing(backing, reconfig_spec)

        LOG.debug("Backing VM: %(backing)s reconfigured with new disk UUID: "
                  "%(disk_uuid)s.",
                  {'backing': backing,
                   'disk_uuid': disk_uuid})

    def update_backing_extra_config(self, backing, extra_config):
        cf = self._session.vim.client.factory
        reconfig_spec = cf.create('ns0:VirtualMachineConfigSpec')
        if BACKING_UUID_KEY in extra_config:
            reconfig_spec.instanceUuid = extra_config.pop(BACKING_UUID_KEY)
        reconfig_spec.extraConfig = self._get_extra_config_option_values(
            extra_config)
        self._reconfigure_backing(backing, reconfig_spec)
        LOG.debug("Backing: %(backing)s reconfigured with extra config: "
                  "%(extra_config)s.",
                  {'backing': backing,
                   'extra_config': extra_config})

    def update_backing_uuid(self, backing, uuid):
        cf = self._session.vim.client.factory
        reconfig_spec = cf.create('ns0:VirtualMachineConfigSpec')
        reconfig_spec.instanceUuid = uuid
        self._reconfigure_backing(backing, reconfig_spec)
        LOG.debug("Backing: %(backing)s reconfigured with uuid: %(uuid)s.",
                  {'backing': backing,
                   'uuid': uuid})

    def delete_file(self, file_path, datacenter=None):
        """Delete file or folder on the datastore.

        :param file_path: Datastore path of the file or folder
        """
        LOG.debug("Deleting file: %(file)s under datacenter: %(dc)s.",
                  {'file': file_path, 'dc': datacenter})
        fileManager = self._session.vim.service_content.fileManager
        task = self._session.invoke_api(self._session.vim,
                                        'DeleteDatastoreFile_Task',
                                        fileManager,
                                        name=file_path,
                                        datacenter=datacenter)
        LOG.debug("Initiated deletion via task: %s.", task)
        self._session.wait_for_task(task)
        LOG.info("Successfully deleted file: %s.", file_path)

    def create_datastore_folder(self, ds_name, folder_path, datacenter):
        """Creates a datastore folder.

        This method returns silently if the folder already exists.

        :param ds_name: datastore name
        :param folder_path: path of folder to create
        :param datacenter: datacenter of target datastore
        """
        fileManager = self._session.vim.service_content.fileManager
        ds_folder_path = "[%s] %s" % (ds_name, folder_path)
        LOG.debug("Creating datastore folder: %s.", ds_folder_path)
        try:
            self._session.invoke_api(self._session.vim,
                                     'MakeDirectory',
                                     fileManager,
                                     name=ds_folder_path,
                                     datacenter=datacenter)
            LOG.info("Created datastore folder: %s.", folder_path)
        except exceptions.FileAlreadyExistsException:
            LOG.debug("Datastore folder: %s already exists.", folder_path)

    def get_path_name(self, backing):
        """Get path name of the backing.

        :param backing: Reference to the backing entity
        :return: Path name of the backing
        """
        return self._session.invoke_api(vim_util, 'get_object_property',
                                        self._session.vim, backing,
                                        'config.files').vmPathName

    def get_entity_name(self, entity):
        """Get name of the managed entity.

        :param entity: Reference to the entity
        :return: Name of the managed entity
        """
        return self._session.invoke_api(vim_util, 'get_object_property',
                                        self._session.vim, entity, 'name')

    def _get_disk_device(self, backing):
        """Get the virtual device corresponding to disk."""
        hardware_devices = self._session.invoke_api(vim_util,
                                                    'get_object_property',
                                                    self._session.vim,
                                                    backing,
                                                    'config.hardware.device')
        if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
            hardware_devices = hardware_devices.VirtualDevice
        for device in hardware_devices:
            if device.__class__.__name__ == "VirtualDisk":
                return device

        LOG.error("Virtual disk device of backing: %s not found.", backing)
        raise vmdk_exceptions.VirtualDiskNotFoundException()

    def get_vmdk_path(self, backing):
        """Get the vmdk file name of the backing.

        The vmdk file path of the backing returned is of the form:
        "[datastore1] my_folder/my_vm.vmdk"

        :param backing: Reference to the backing
        :return: VMDK file path of the backing
        """
        disk_device = self._get_disk_device(backing)
        backing = disk_device.backing
        if backing.__class__.__name__ != "VirtualDiskFlatVer2BackingInfo":
            msg = _("Invalid disk backing: %s.") % backing.__class__.__name__
            LOG.error(msg)
            raise AssertionError(msg)
        return backing.fileName

    def get_disk_size(self, backing):
        """Get disk size of the backing.

        :param backing: backing VM reference
        :return: disk size in bytes
        """
        disk_device = self._get_disk_device(backing)
        return disk_device.capacityInKB * units.Ki

    def _get_virtual_disk_create_spec(self, size_in_kb, adapter_type,
                                      disk_type):
        """Return spec for file-backed virtual disk creation."""
        cf = self._session.vim.client.factory
        spec = cf.create('ns0:FileBackedVirtualDiskSpec')
        spec.capacityKb = size_in_kb
        spec.adapterType = VirtualDiskAdapterType.get_adapter_type(
            adapter_type)
        spec.diskType = VirtualDiskType.get_virtual_disk_type(disk_type)
        return spec

    def create_virtual_disk(self, dc_ref, vmdk_ds_file_path, size_in_kb,
                            adapter_type='busLogic', disk_type='preallocated'):
        """Create virtual disk with the given settings.

        :param dc_ref: datacenter reference
        :param vmdk_ds_file_path: datastore file path of the virtual disk
        :param size_in_kb: disk size in KB
        :param adapter_type: disk adapter type
        :param disk_type: vmdk type
        """
        virtual_disk_spec = self._get_virtual_disk_create_spec(size_in_kb,
                                                               adapter_type,
                                                               disk_type)
        LOG.debug("Creating virtual disk with spec: %s.", virtual_disk_spec)
        disk_manager = self._session.vim.service_content.virtualDiskManager
        task = self._session.invoke_api(self._session.vim,
                                        'CreateVirtualDisk_Task',
                                        disk_manager,
                                        name=vmdk_ds_file_path,
                                        datacenter=dc_ref,
                                        spec=virtual_disk_spec)
        LOG.debug("Task: %s created for virtual disk creation.", task)
        self._session.wait_for_task(task)
        LOG.debug("Created virtual disk with spec: %s.", virtual_disk_spec)

    def create_flat_extent_virtual_disk_descriptor(
            self, dc_ref, path, size_in_kb, adapter_type, disk_type):
        """Create descriptor for a single flat extent virtual disk.

        To create the descriptor, we create a virtual disk and delete its flat
        extent.

        :param dc_ref: reference to the datacenter
        :param path: descriptor datastore file path
        :param size_in_kb: size of the virtual disk in KB
        :param adapter_type: virtual disk adapter type
        :param disk_type: type of the virtual disk
        """
        LOG.debug("Creating descriptor: %(path)s with size (KB): %(size)s, "
                  "adapter_type: %(adapter_type)s and disk_type: "
                  "%(disk_type)s.",
                  {'path': path.get_descriptor_ds_file_path(),
                   'size': size_in_kb,
                   'adapter_type': adapter_type,
                   'disk_type': disk_type
                   })
        self.create_virtual_disk(dc_ref, path.get_descriptor_ds_file_path(),
                                 size_in_kb, adapter_type, disk_type)
        self.delete_file(path.get_flat_extent_ds_file_path(), dc_ref)
        LOG.debug("Created descriptor: %s.",
                  path.get_descriptor_ds_file_path())

    def copy_vmdk_file(self, src_dc_ref, src_vmdk_file_path,
                       dest_vmdk_file_path, dest_dc_ref=None):
        """Copy contents of the src vmdk file to dest vmdk file.

        :param src_dc_ref: Reference to datacenter containing src datastore
        :param src_vmdk_file_path: Source vmdk file path
        :param dest_vmdk_file_path: Destination vmdk file path
        :param dest_dc_ref: Reference to datacenter of dest datastore.
                            If unspecified, source datacenter is used.
        """
        LOG.debug('Copying disk: %(src)s to %(dest)s.',
                  {'src': src_vmdk_file_path,
                   'dest': dest_vmdk_file_path})

        dest_dc_ref = dest_dc_ref or src_dc_ref
        diskMgr = self._session.vim.service_content.virtualDiskManager
        task = self._session.invoke_api(self._session.vim,
                                        'CopyVirtualDisk_Task',
                                        diskMgr,
                                        sourceName=src_vmdk_file_path,
                                        sourceDatacenter=src_dc_ref,
                                        destName=dest_vmdk_file_path,
                                        destDatacenter=dest_dc_ref,
                                        force=True)

        LOG.debug("Initiated copying disk data via task: %s.", task)
        self._session.wait_for_task(task)
        LOG.info("Successfully copied disk at: %(src)s to: %(dest)s.",
                 {'src': src_vmdk_file_path, 'dest': dest_vmdk_file_path})

    def move_vmdk_file(self, src_dc_ref, src_vmdk_file_path,
                       dest_vmdk_file_path, dest_dc_ref=None):
        """Move the given vmdk file to another datastore location.

        :param src_dc_ref: Reference to datacenter containing src datastore
        :param src_vmdk_file_path: Source vmdk file path
        :param dest_vmdk_file_path: Destination vmdk file path
        :param dest_dc_ref: Reference to datacenter of dest datastore.
                            If unspecified, source datacenter is used.
        """
        LOG.debug('Moving disk: %(src)s to %(dest)s.',
                  {'src': src_vmdk_file_path, 'dest': dest_vmdk_file_path})

        dest_dc_ref = dest_dc_ref or src_dc_ref
        diskMgr = self._session.vim.service_content.virtualDiskManager
        task = self._session.invoke_api(self._session.vim,
                                        'MoveVirtualDisk_Task',
                                        diskMgr,
                                        sourceName=src_vmdk_file_path,
                                        sourceDatacenter=src_dc_ref,
                                        destName=dest_vmdk_file_path,
                                        destDatacenter=dest_dc_ref,
                                        force=True)
        self._session.wait_for_task(task)

    def copy_datastore_file(self, vsphere_url, dest_dc_ref, dest_ds_file_path):
        """Copy file to datastore location.

        :param vsphere_url: vsphere URL of the file
        :param dest_dc_ref: Reference to destination datacenter
        :param dest_file_path: Destination datastore file path
        """
        LOG.debug("Copying file: %(vsphere_url)s to %(path)s.",
                  {'vsphere_url': vsphere_url,
                   'path': dest_ds_file_path})
        location_url = ds_obj.DatastoreURL.urlparse(vsphere_url)
        src_path = ds_obj.DatastorePath(location_url.datastore_name,
                                        location_url.path)
        src_dc_ref = self.get_entity_by_inventory_path(
            location_url.datacenter_path)

        task = self._session.invoke_api(
            self._session.vim,
            'CopyDatastoreFile_Task',
            self._session.vim.service_content.fileManager,
            sourceName=six.text_type(src_path),
            sourceDatacenter=src_dc_ref,
            destinationName=dest_ds_file_path,
            destinationDatacenter=dest_dc_ref)
        self._session.wait_for_task(task)

    def delete_vmdk_file(self, vmdk_file_path, dc_ref):
        """Delete given vmdk files.

        :param vmdk_file_path: VMDK file path to be deleted
        :param dc_ref: Reference to datacenter that contains this VMDK file
        """
        LOG.debug("Deleting vmdk file: %s.", vmdk_file_path)
        diskMgr = self._session.vim.service_content.virtualDiskManager
        task = self._session.invoke_api(self._session.vim,
                                        'DeleteVirtualDisk_Task',
                                        diskMgr,
                                        name=vmdk_file_path,
                                        datacenter=dc_ref)
        LOG.debug("Initiated deleting vmdk file via task: %s.", task)
        self._session.wait_for_task(task)
        LOG.info("Deleted vmdk file: %s.", vmdk_file_path)

    def _get_all_clusters(self):
        clusters = {}
        retrieve_result = self._session.invoke_api(vim_util, 'get_objects',
                                                   self._session.vim,
                                                   'ClusterComputeResource',
                                                   self._max_objects)
        while retrieve_result:
            if retrieve_result.objects:
                for cluster in retrieve_result.objects:
                    name = urllib.parse.unquote(cluster.propSet[0].val)
                    clusters[name] = cluster.obj
            retrieve_result = self.continue_retrieval(retrieve_result)
        return clusters

    def get_cluster_refs(self, names):
        """Get references to given clusters.

        :param names: list of cluster names
        :return: Dictionary of cluster names to references
        """
        clusters_ref = {}
        clusters = self._get_all_clusters()
        for name in names:
            if name not in clusters:
                LOG.error("Compute cluster: %s not found.", name)
                raise vmdk_exceptions.ClusterNotFoundException(cluster=name)
            clusters_ref[name] = clusters[name]

        return clusters_ref

    def get_cluster_hosts(self, cluster):
        """Get hosts in the given cluster.

        :param cluster: cluster reference
        :return: references to hosts in the cluster
        """
        hosts = self._session.invoke_api(vim_util,
                                         'get_object_property',
                                         self._session.vim,
                                         cluster,
                                         'host')

        host_refs = []
        if hosts and hosts.ManagedObjectReference:
            host_refs.extend(hosts.ManagedObjectReference)

        return host_refs

    def get_entity_by_inventory_path(self, path):
        """Returns the managed object identified by the given inventory path.

        :param path: Inventory path
        :return: Reference to the managed object
        """
        return self._session.invoke_api(
            self._session.vim,
            "FindByInventoryPath",
            self._session.vim.service_content.searchIndex,
            inventoryPath=path)

    def get_inventory_path(self, entity):
        return self._session.invoke_api(
            vim_util, 'get_inventory_path', self._session.vim, entity)

    def _get_disk_devices(self, vm):
        disk_devices = []
        hardware_devices = self._session.invoke_api(vim_util,
                                                    'get_object_property',
                                                    self._session.vim,
                                                    vm,
                                                    'config.hardware.device')

        if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
            hardware_devices = hardware_devices.VirtualDevice

        for device in hardware_devices:
            if device.__class__.__name__ == "VirtualDisk":
                disk_devices.append(device)

        return disk_devices

    def get_disk_device(self, vm, vmdk_path):
        """Get the disk device of the VM which corresponds to the given path.

        :param vm: VM reference
        :param vmdk_path: Datastore path of virtual disk
        :return: Matching disk device
        """
        disk_devices = self._get_disk_devices(vm)

        for disk_device in disk_devices:
            backing = disk_device.backing
            if (backing.__class__.__name__ == "VirtualDiskFlatVer2BackingInfo"
                    and backing.fileName == vmdk_path):
                return disk_device

    def mark_backing_as_template(self, backing):
        LOG.debug("Marking backing: %s as template.", backing)
        self._session.invoke_api(self._session.vim, 'MarkAsTemplate', backing)

    def _create_fcd_backing_spec(self, disk_type, ds_ref):
        backing_spec = self._session.vim.client.factory.create(
            'ns0:VslmCreateSpecDiskFileBackingSpec')
        if disk_type == VirtualDiskType.PREALLOCATED:
            disk_type = 'lazyZeroedThick'
        backing_spec.provisioningType = disk_type
        backing_spec.datastore = ds_ref
        return backing_spec

    def _create_profile_spec(self, cf, profile_id):
        profile_spec = cf.create('ns0:VirtualMachineDefinedProfileSpec')
        profile_spec.profileId = profile_id
        return profile_spec

    def create_fcd(self, name, size_mb, ds_ref, disk_type, profile_id=None):
        cf = self._session.vim.client.factory
        spec = cf.create('ns0:VslmCreateSpec')
        spec.capacityInMB = size_mb
        spec.name = name
        spec.backingSpec = self._create_fcd_backing_spec(disk_type, ds_ref)

        if profile_id:
            profile_spec = self._create_profile_spec(cf, profile_id)
            spec.profile = [profile_spec]

        LOG.debug("Creating fcd with spec: %(spec)s on datastore: %(ds_ref)s.",
                  {'spec': spec, 'ds_ref': ds_ref})
        vstorage_mgr = self._session.vim.service_content.vStorageObjectManager
        task = self._session.invoke_api(self._session.vim,
                                        'CreateDisk_Task',
                                        vstorage_mgr,
                                        spec=spec)
        task_info = self._session.wait_for_task(task)
        fcd_loc = FcdLocation.create(task_info.result.config.id, ds_ref)
        LOG.debug("Created fcd: %s.", fcd_loc)
        return fcd_loc

    def delete_fcd(self, fcd_location):
        cf = self._session.vim.client.factory
        vstorage_mgr = self._session.vim.service_content.vStorageObjectManager
        LOG.debug("Deleting fcd: %s.", fcd_location)
        task = self._session.invoke_api(self._session.vim,
                                        'DeleteVStorageObject_Task',
                                        vstorage_mgr,
                                        id=fcd_location.id(cf),
                                        datastore=fcd_location.ds_ref())
        self._session.wait_for_task(task)

    def clone_fcd(
            self, name, fcd_location, dest_ds_ref, disk_type, profile_id=None):
        cf = self._session.vim.client.factory
        spec = cf.create('ns0:VslmCloneSpec')
        spec.name = name
        spec.backingSpec = self._create_fcd_backing_spec(disk_type,
                                                         dest_ds_ref)

        if profile_id:
            profile_spec = self._create_profile_spec(cf, profile_id)
            spec.profile = [profile_spec]

        LOG.debug("Copying fcd: %(fcd_loc)s to datastore: %(ds_ref)s with "
                  "spec: %(spec)s.",
                  {'fcd_loc': fcd_location,
                   'spec': spec,
                   'ds_ref': dest_ds_ref})
        vstorage_mgr = self._session.vim.service_content.vStorageObjectManager
        task = self._session.invoke_api(self._session.vim,
                                        'CloneVStorageObject_Task',
                                        vstorage_mgr,
                                        id=fcd_location.id(cf),
                                        datastore=fcd_location.ds_ref(),
                                        spec=spec)
        task_info = self._session.wait_for_task(task)
        dest_fcd_loc = FcdLocation.create(task_info.result.config.id,
                                          dest_ds_ref)
        LOG.debug("Clone fcd: %s.", dest_fcd_loc)
        return dest_fcd_loc

    def extend_fcd(self, fcd_location, new_size_mb):
        cf = self._session.vim.client.factory
        vstorage_mgr = self._session.vim.service_content.vStorageObjectManager
        LOG.debug("Extending fcd: %(fcd_loc)s to %(size)s.",
                  {'fcd_loc': fcd_location, 'size': new_size_mb})
        task = self._session.invoke_api(self._session.vim,
                                        'ExtendDisk_Task',
                                        vstorage_mgr,
                                        id=fcd_location.id(cf),
                                        datastore=fcd_location.ds_ref(),
                                        newCapacityInMB=new_size_mb)
        self._session.wait_for_task(task)

    def register_disk(self, vmdk_url, name, ds_ref):
        vstorage_mgr = self._session.vim.service_content.vStorageObjectManager
        LOG.debug("Registering disk: %s as fcd.", vmdk_url)
        fcd = self._session.invoke_api(self._session.vim,
                                       'RegisterDisk',
                                       vstorage_mgr,
                                       path=vmdk_url,
                                       name=name)
        fcd_loc = FcdLocation.create(fcd.config.id, ds_ref)
        LOG.debug("Created fcd: %s.", fcd_loc)
        return fcd_loc

    def attach_fcd(self, backing, fcd_location):
        cf = self._session.vim.client.factory

        reconfig_spec = cf.create('ns0:VirtualMachineConfigSpec')
        spec = self._create_controller_config_spec(
            VirtualDiskAdapterType.LSI_LOGIC)
        reconfig_spec.deviceChange = [spec]
        self._reconfigure_backing(backing, reconfig_spec)

        LOG.debug("Attaching fcd: %(fcd_loc)s to %(backing)s.",
                  {'fcd_loc': fcd_location, 'backing': backing})
        task = self._session.invoke_api(self._session.vim,
                                        "AttachDisk_Task",
                                        backing,
                                        diskId=fcd_location.id(cf),
                                        datastore=fcd_location.ds_ref())
        self._session.wait_for_task(task)

    def detach_fcd(self, backing, fcd_location):
        cf = self._session.vim.client.factory
        LOG.debug("Detaching fcd: %(fcd_loc)s from %(backing)s.",
                  {'fcd_loc': fcd_location, 'backing': backing})
        task = self._session.invoke_api(self._session.vim,
                                        "DetachDisk_Task",
                                        backing,
                                        diskId=fcd_location.id(cf))
        self._session.wait_for_task(task)

    def create_fcd_snapshot(self, fcd_location, description):
        LOG.debug("Creating fcd snapshot for %s.", fcd_location)

        vstorage_mgr = self._session.vim.service_content.vStorageObjectManager
        cf = self._session.vim.client.factory
        task = self._session.invoke_api(self._session.vim,
                                        'VStorageObjectCreateSnapshot_Task',
                                        vstorage_mgr,
                                        id=fcd_location.id(cf),
                                        datastore=fcd_location.ds_ref(),
                                        description=description)
        task_info = self._session.wait_for_task(task)
        fcd_snap_loc = FcdSnapshotLocation(fcd_location, task_info.result.id)

        LOG.debug("Created fcd snapshot: %s.", fcd_snap_loc)
        return fcd_snap_loc

    def delete_fcd_snapshot(self, fcd_snap_loc):
        LOG.debug("Deleting fcd snapshot: %s.", fcd_snap_loc)

        vstorage_mgr = self._session.vim.service_content.vStorageObjectManager
        cf = self._session.vim.client.factory
        task = self._session.invoke_api(
            self._session.vim,
            'DeleteSnapshot_Task',
            vstorage_mgr,
            id=fcd_snap_loc.fcd_loc.id(cf),
            datastore=fcd_snap_loc.fcd_loc.ds_ref(),
            snapshotId=fcd_snap_loc.id(cf))
        self._session.wait_for_task(task)

    def create_fcd_from_snapshot(self, fcd_snap_loc, name, profile_id=None):
        LOG.debug("Creating fcd with name: %(name)s from fcd snapshot: "
                  "%(snap)s.", {'name': name, 'snap': fcd_snap_loc})

        vstorage_mgr = self._session.vim.service_content.vStorageObjectManager
        cf = self._session.vim.client.factory
        if profile_id:
            profile = [self._create_profile_spec(cf, profile_id)]
        else:
            profile = None
        task = self._session.invoke_api(
            self._session.vim,
            'CreateDiskFromSnapshot_Task',
            vstorage_mgr,
            id=fcd_snap_loc.fcd_loc.id(cf),
            datastore=fcd_snap_loc.fcd_loc.ds_ref(),
            snapshotId=fcd_snap_loc.id(cf),
            name=name,
            profile=profile)
        task_info = self._session.wait_for_task(task)
        fcd_loc = FcdLocation.create(task_info.result.config.id,
                                     fcd_snap_loc.fcd_loc.ds_ref())

        LOG.debug("Created fcd: %s.", fcd_loc)
        return fcd_loc

    def update_fcd_policy(self, fcd_location, profile_id):
        LOG.debug("Changing fcd: %(fcd_loc)s storage policy to %(policy)s.",
                  {'fcd_loc': fcd_location, 'policy': profile_id})

        vstorage_mgr = self._session.vim.service_content.vStorageObjectManager
        cf = self._session.vim.client.factory
        if profile_id is None:
            profile_spec = cf.create('ns0:VirtualMachineEmptyProfileSpec')
        else:
            profile_spec = self._create_profile_spec(cf, profile_id)
        task = self._session.invoke_api(
            self._session.vim,
            'UpdateVStorageObjectPolicy_Task',
            vstorage_mgr,
            id=fcd_location.id(cf),
            datastore=fcd_location.ds_ref(),
            profile=[profile_spec])
        self._session.wait_for_task(task)

        LOG.debug("Updated fcd storage policy to %s.", profile_id)


class FcdLocation(object):

    def __init__(self, fcd_id, ds_ref_val):
        self.fcd_id = fcd_id
        self.ds_ref_val = ds_ref_val

    @classmethod
    def create(cls, fcd_id_obj, ds_ref):
        return cls(fcd_id_obj.id, vim_util.get_moref_value(ds_ref))

    def provider_location(self):
        return "%s@%s" % (self.fcd_id, self.ds_ref_val)

    def ds_ref(self):
        return vim_util.get_moref(self.ds_ref_val, 'Datastore')

    def id(self, cf):
        id_obj = cf.create('ns0:ID')
        id_obj.id = self.fcd_id
        return id_obj

    @classmethod
    def from_provider_location(cls, provider_location):
        fcd_id, ds_ref_val = provider_location.split('@')
        return cls(fcd_id, ds_ref_val)

    def __str__(self):
        return self.provider_location()


class FcdSnapshotLocation(object):

    def __init__(self, fcd_location, snapshot_id):
        self.fcd_loc = fcd_location
        self.snap_id = snapshot_id

    def provider_location(self):
        loc = {"fcd_location": self.fcd_loc.provider_location(),
               "fcd_snapshot_id": self.snap_id}
        return json.dumps(loc)

    def id(self, cf):
        id_obj = cf.create('ns0:ID')
        id_obj.id = self.snap_id
        return id_obj

    @classmethod
    def from_provider_location(cls, provider_location):
        try:
            loc = json.loads(provider_location)
            fcd_loc = FcdLocation.from_provider_location(loc['fcd_location'])
            return cls(fcd_loc, loc['fcd_snapshot_id'])
        except ValueError:
            pass

    def __str__(self):
        return self.provider_location()
