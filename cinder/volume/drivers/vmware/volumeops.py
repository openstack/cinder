# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from cinder.openstack.common import log as logging
from cinder.volume.drivers.vmware import error_util
from cinder.volume.drivers.vmware import vim_util

LOG = logging.getLogger(__name__)
LINKED_CLONE_TYPE = 'linked'
FULL_CLONE_TYPE = 'full'
ALREADY_EXISTS = 'AlreadyExists'
FILE_ALREADY_EXISTS = 'FileAlreadyExists'


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


class VMwareVolumeOps(object):
    """Manages volume operations."""

    def __init__(self, session, max_objects):
        self._session = session
        self._max_objects = max_objects

    def get_backing(self, name):
        """Get the backing based on name.

        :param name: Name of the backing
        :return: Managed object reference to the backing
        """

        retrieve_result = self._session.invoke_api(vim_util, 'get_objects',
                                                   self._session.vim,
                                                   'VirtualMachine',
                                                   self._max_objects)
        while retrieve_result:
            vms = retrieve_result.objects
            for vm in vms:
                if vm.propSet[0].val == name:
                    # We got the result, so cancel further retrieval.
                    self.cancel_retrieval(retrieve_result)
                    return vm.obj
            # Result not obtained, continue retrieving results.
            retrieve_result = self.continue_retrieval(retrieve_result)

        LOG.debug(_("Did not find any backing with name: %s") % name)

    def delete_backing(self, backing):
        """Delete the backing.

        :param backing: Managed object reference to the backing
        """
        LOG.debug(_("Deleting the VM backing: %s.") % backing)
        task = self._session.invoke_api(self._session.vim, 'Destroy_Task',
                                        backing)
        LOG.debug(_("Initiated deletion of VM backing: %s.") % backing)
        self._session.wait_for_task(task)
        LOG.info(_("Deleted the VM backing: %s.") % backing)

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

    def _is_valid(self, datastore, host):
        """Check if host's datastore is accessible, mounted and writable.

        :param datastore: Reference to the datastore entity
        :param host: Reference to the host entity
        :return: True if datastore can be used for volume creation
        """

        host_mounts = self._session.invoke_api(vim_util, 'get_object_property',
                                               self._session.vim, datastore,
                                               'host')
        for host_mount in host_mounts.DatastoreHostMount:
            if host_mount.key.value == host.value:
                mntInfo = host_mount.mountInfo
                writable = mntInfo.accessMode == "readWrite"
                # If mounted attribute is not set, then default is True
                mounted = True
                if hasattr(mntInfo, "mounted"):
                    mounted = mntInfo.mounted
                if hasattr(mntInfo, "accessible"):
                    accessible = mntInfo.accessible
                else:
                    # If accessible attribute is not set, we look at summary
                    summary = self.get_summary(datastore)
                    accessible = summary.accessible
                return (accessible and mounted and writable)
        return False

    def get_dss_rp(self, host):
        """Get accessible datastores and resource pool of the host.

        :param host: Managed object reference of the host
        :return: Datastores accessible to the host and resource pool to which
                 the host belongs to
        """

        props = self._session.invoke_api(vim_util, 'get_object_properties',
                                         self._session.vim, host,
                                         ['datastore', 'parent'])
        # Get datastores and compute resource or cluster compute resource
        datastores = []
        compute_resource = None
        for elem in props:
            for prop in elem.propSet:
                if prop.name == 'datastore' and prop.val:
                    # Consider only if datastores are present under host
                    datastores = prop.val.ManagedObjectReference
                elif prop.name == 'parent':
                    compute_resource = prop.val
        # Filter datastores based on if it is accessible, mounted and writable
        valid_dss = []
        for datastore in datastores:
            if self._is_valid(datastore, host):
                valid_dss.append(datastore)
        # Get resource pool from compute resource or cluster compute resource
        resource_pool = self._session.invoke_api(vim_util,
                                                 'get_object_property',
                                                 self._session.vim,
                                                 compute_resource,
                                                 'resourcePool')
        if not valid_dss:
            msg = _("There are no valid datastores present under %s.")
            LOG.error(msg % host)
            raise error_util.VimException(msg % host)
        return (valid_dss, resource_pool)

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

    def create_folder(self, parent_folder, child_folder_name):
        """Creates child folder with given name under the given parent folder.

        The method first checks if a child folder already exists, if it does,
        then it returns a moref for the folder, else it creates one and then
        return the moref.

        :param parent_folder: Reference to the folder entity
        :param child_folder_name: Name of the child folder
        :return: Reference to the child folder with input name if it already
                 exists, else create one and return the reference
        """
        LOG.debug(_("Creating folder: %(child_folder_name)s under parent "
                    "folder: %(parent_folder)s.") %
                  {'child_folder_name': child_folder_name,
                   'parent_folder': parent_folder})

        # Get list of child entites for the parent folder
        prop_val = self._session.invoke_api(vim_util, 'get_object_property',
                                            self._session.vim, parent_folder,
                                            'childEntity')
        child_entities = prop_val.ManagedObjectReference

        # Return if the child folder with input name is already present
        for child_entity in child_entities:
            if child_entity._type != 'Folder':
                continue
            child_entity_name = self.get_entity_name(child_entity)
            if child_entity_name == child_folder_name:
                LOG.debug(_("Child folder already present: %s.") %
                          child_entity)
                return child_entity

        # Need to create the child folder
        child_folder = self._session.invoke_api(self._session.vim,
                                                'CreateFolder', parent_folder,
                                                name=child_folder_name)
        LOG.debug(_("Created child folder: %s.") % child_folder)
        return child_folder

    def _get_create_spec(self, name, size_kb, disk_type, ds_name):
        """Return spec for creating volume backing.

        :param name: Name of the backing
        :param size_kb: Size in KB of the backing
        :param disk_type: VMDK type for the disk
        :param ds_name: Datastore name where the disk is to be provisioned
        :return: Spec for creation
        """
        cf = self._session.vim.client.factory
        controller_device = cf.create('ns0:VirtualLsiLogicController')
        controller_device.key = -100
        controller_device.busNumber = 0
        controller_device.sharedBus = 'noSharing'
        controller_spec = cf.create('ns0:VirtualDeviceConfigSpec')
        controller_spec.operation = 'add'
        controller_spec.device = controller_device

        disk_device = cf.create('ns0:VirtualDisk')
        # for very small disks allocate at least 1KB
        disk_device.capacityInKB = max(1, int(size_kb))
        disk_device.key = -101
        disk_device.unitNumber = 0
        disk_device.controllerKey = -100
        disk_device_bkng = cf.create('ns0:VirtualDiskFlatVer2BackingInfo')
        if disk_type == 'eagerZeroedThick':
            disk_device_bkng.eagerlyScrub = True
        elif disk_type == 'thin':
            disk_device_bkng.thinProvisioned = True
        disk_device_bkng.fileName = ''
        disk_device_bkng.diskMode = 'persistent'
        disk_device.backing = disk_device_bkng
        disk_spec = cf.create('ns0:VirtualDeviceConfigSpec')
        disk_spec.operation = 'add'
        disk_spec.fileOperation = 'create'
        disk_spec.device = disk_device

        vm_file_info = cf.create('ns0:VirtualMachineFileInfo')
        vm_file_info.vmPathName = '[%s]' % ds_name

        create_spec = cf.create('ns0:VirtualMachineConfigSpec')
        create_spec.name = name
        create_spec.guestId = 'otherGuest'
        create_spec.numCPUs = 1
        create_spec.memoryMB = 128
        create_spec.deviceChange = [controller_spec, disk_spec]
        create_spec.files = vm_file_info

        LOG.debug(_("Spec for creating the backing: %s.") % create_spec)
        return create_spec

    def create_backing(self, name, size_kb, disk_type,
                       folder, resource_pool, host, ds_name):
        """Create backing for the volume.

        Creates a VM with one VMDK based on the given inputs.

        :param name: Name of the backing
        :param size_kb: Size in KB of the backing
        :param disk_type: VMDK type for the disk
        :param folder: Folder, where to create the backing under
        :param resource_pool: Resource pool reference
        :param host: Host reference
        :param ds_name: Datastore name where the disk is to be provisioned
        :return: Reference to the created backing entity
        """
        LOG.debug(_("Creating volume backing name: %(name)s "
                    "disk_type: %(disk_type)s size_kb: %(size_kb)s at "
                    "folder: %(folder)s resourse pool: %(resource_pool)s "
                    "datastore name: %(ds_name)s.") %
                  {'name': name, 'disk_type': disk_type, 'size_kb': size_kb,
                   'folder': folder, 'resource_pool': resource_pool,
                   'ds_name': ds_name})

        create_spec = self._get_create_spec(name, size_kb, disk_type, ds_name)
        task = self._session.invoke_api(self._session.vim, 'CreateVM_Task',
                                        folder, config=create_spec,
                                        pool=resource_pool, host=host)
        LOG.debug(_("Initiated creation of volume backing: %s.") % name)
        task_info = self._session.wait_for_task(task)
        backing = task_info.result
        LOG.info(_("Successfully created volume backing: %s.") % backing)
        return backing

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

    def _get_relocate_spec(self, datastore, resource_pool, host,
                           disk_move_type):
        """Return spec for relocating volume backing.

        :param datastore: Reference to the datastore
        :param resource_pool: Reference to the resource pool
        :param host: Reference to the host
        :param disk_move_type: Disk move type option
        :return: Spec for relocation
        """
        cf = self._session.vim.client.factory
        relocate_spec = cf.create('ns0:VirtualMachineRelocateSpec')
        relocate_spec.datastore = datastore
        relocate_spec.pool = resource_pool
        relocate_spec.host = host
        relocate_spec.diskMoveType = disk_move_type

        LOG.debug(_("Spec for relocating the backing: %s.") % relocate_spec)
        return relocate_spec

    def relocate_backing(self, backing, datastore, resource_pool, host):
        """Relocates backing to the input datastore and resource pool.

        The implementation uses moveAllDiskBackingsAndAllowSharing disk move
        type.

        :param backing: Reference to the backing
        :param datastore: Reference to the datastore
        :param resource_pool: Reference to the resource pool
        :param host: Reference to the host
        """
        LOG.debug(_("Relocating backing: %(backing)s to datastore: %(ds)s "
                    "and resource pool: %(rp)s.") %
                  {'backing': backing, 'ds': datastore, 'rp': resource_pool})

        # Relocate the volume backing
        disk_move_type = 'moveAllDiskBackingsAndAllowSharing'
        relocate_spec = self._get_relocate_spec(datastore, resource_pool, host,
                                                disk_move_type)
        task = self._session.invoke_api(self._session.vim, 'RelocateVM_Task',
                                        backing, spec=relocate_spec)
        LOG.debug(_("Initiated relocation of volume backing: %s.") % backing)
        self._session.wait_for_task(task)
        LOG.info(_("Successfully relocated volume backing: %(backing)s "
                   "to datastore: %(ds)s and resource pool: %(rp)s.") %
                 {'backing': backing, 'ds': datastore, 'rp': resource_pool})

    def move_backing_to_folder(self, backing, folder):
        """Move the volume backing to the folder.

        :param backing: Reference to the backing
        :param folder: Reference to the folder
        """
        LOG.debug(_("Moving backing: %(backing)s to folder: %(fol)s.") %
                  {'backing': backing, 'fol': folder})
        task = self._session.invoke_api(self._session.vim,
                                        'MoveIntoFolder_Task', folder,
                                        list=[backing])
        LOG.debug(_("Initiated move of volume backing: %(backing)s into the "
                    "folder: %(fol)s.") % {'backing': backing, 'fol': folder})
        self._session.wait_for_task(task)
        LOG.info(_("Successfully moved volume backing: %(backing)s into the "
                   "folder: %(fol)s.") % {'backing': backing, 'fol': folder})

    def create_snapshot(self, backing, name, description, quiesce=False):
        """Create snapshot of the backing with given name and description.

        :param backing: Reference to the backing entity
        :param name: Snapshot name
        :param description: Snapshot description
        :param quiesce: Whether to quiesce the backing when taking snapshot
        :return: Created snapshot entity reference
        """
        LOG.debug(_("Snapshoting backing: %(backing)s with name: %(name)s.") %
                  {'backing': backing, 'name': name})
        task = self._session.invoke_api(self._session.vim,
                                        'CreateSnapshot_Task',
                                        backing, name=name,
                                        description=description,
                                        memory=False, quiesce=quiesce)
        LOG.debug(_("Initiated snapshot of volume backing: %(backing)s "
                    "named: %(name)s.") % {'backing': backing, 'name': name})
        task_info = self._session.wait_for_task(task)
        snapshot = task_info.result
        LOG.info(_("Successfully created snapshot: %(snap)s for volume "
                   "backing: %(backing)s.") %
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

    def delete_snapshot(self, backing, name):
        """Delete a given snapshot from volume backing.

        :param backing: Reference to the backing entity
        :param name: Snapshot name
        """
        LOG.debug(_("Deleting the snapshot: %(name)s from backing: "
                    "%(backing)s.") %
                  {'name': name, 'backing': backing})
        snapshot = self.get_snapshot(backing, name)
        if not snapshot:
            LOG.info(_("Did not find the snapshot: %(name)s for backing: "
                       "%(backing)s. Need not delete anything.") %
                     {'name': name, 'backing': backing})
            return
        task = self._session.invoke_api(self._session.vim,
                                        'RemoveSnapshot_Task',
                                        snapshot, removeChildren=False)
        LOG.debug(_("Initiated snapshot: %(name)s deletion for backing: "
                    "%(backing)s.") %
                  {'name': name, 'backing': backing})
        self._session.wait_for_task(task)
        LOG.info(_("Successfully deleted snapshot: %(name)s of backing: "
                   "%(backing)s.") % {'backing': backing, 'name': name})

    def _get_folder(self, backing):
        """Get parent folder of the backing.

        :param backing: Reference to the backing entity
        :return: Reference to parent folder of the backing entity
        """
        return self._get_parent(backing, 'Folder')

    def _get_clone_spec(self, datastore, disk_move_type, snapshot):
        """Get the clone spec.

        :param datastore: Reference to datastore
        :param disk_move_type: Disk move type
        :param snapshot: Reference to snapshot
        :return: Clone spec
        """
        relocate_spec = self._get_relocate_spec(datastore, None, None,
                                                disk_move_type)
        cf = self._session.vim.client.factory
        clone_spec = cf.create('ns0:VirtualMachineCloneSpec')
        clone_spec.location = relocate_spec
        clone_spec.powerOn = False
        clone_spec.template = False
        clone_spec.snapshot = snapshot

        LOG.debug(_("Spec for cloning the backing: %s.") % clone_spec)
        return clone_spec

    def clone_backing(self, name, backing, snapshot, clone_type, datastore):
        """Clone backing.

        If the clone_type is 'full', then a full clone of the source volume
        backing will be created. Else, if it is 'linked', then a linked clone
        of the source volume backing will be created.

        :param name: Name for the clone
        :param backing: Reference to the backing entity
        :param snapshot: Snapshot point from which the clone should be done
        :param clone_type: Whether a full clone or linked clone is to be made
        :param datastore: Reference to the datastore entity
        """
        LOG.debug(_("Creating a clone of backing: %(back)s, named: %(name)s, "
                    "clone type: %(type)s from snapshot: %(snap)s on "
                    "datastore: %(ds)s") %
                  {'back': backing, 'name': name, 'type': clone_type,
                   'snap': snapshot, 'ds': datastore})
        folder = self._get_folder(backing)
        if clone_type == LINKED_CLONE_TYPE:
            disk_move_type = 'createNewChildDiskBacking'
        else:
            disk_move_type = 'moveAllDiskBackingsAndDisallowSharing'
        clone_spec = self._get_clone_spec(datastore, disk_move_type, snapshot)
        task = self._session.invoke_api(self._session.vim, 'CloneVM_Task',
                                        backing, folder=folder, name=name,
                                        spec=clone_spec)
        LOG.debug(_("Initiated clone of backing: %s.") % name)
        task_info = self._session.wait_for_task(task)
        new_backing = task_info.result
        LOG.info(_("Successfully created clone: %s.") % new_backing)
        return new_backing

    def delete_file(self, file_path, datacenter=None):
        """Delete file or folder on the datastore.

        :param file_path: Datastore path of the file or folder
        """
        LOG.debug(_("Deleting file: %(file)s under datacenter: %(dc)s.") %
                  {'file': file_path, 'dc': datacenter})
        fileManager = self._session.vim.service_content.fileManager
        task = self._session.invoke_api(self._session.vim,
                                        'DeleteDatastoreFile_Task',
                                        fileManager,
                                        name=file_path,
                                        datacenter=datacenter)
        LOG.debug(_("Initiated deletion via task: %s.") % task)
        self._session.wait_for_task(task)
        LOG.info(_("Successfully deleted file: %s.") % file_path)

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

    def get_vmdk_path(self, backing):
        """Get the vmdk file name of the backing.

        The vmdk file path of the backing returned is of the form:
        "[datastore1] my_folder/my_vm.vmdk"

        :param backing: Reference to the backing
        :return: VMDK file path of the backing
        """
        hardware_devices = self._session.invoke_api(vim_util,
                                                    'get_object_property',
                                                    self._session.vim,
                                                    backing,
                                                    'config.hardware.device')
        if hardware_devices.__class__.__name__ == "ArrayOfVirtualDevice":
            hardware_devices = hardware_devices.VirtualDevice
        for device in hardware_devices:
            if device.__class__.__name__ == "VirtualDisk":
                bkng = device.backing
                if bkng.__class__.__name__ == "VirtualDiskFlatVer2BackingInfo":
                    return bkng.fileName

    def copy_vmdk_file(self, dc_ref, src_vmdk_file_path, dest_vmdk_file_path):
        """Copy contents of the src vmdk file to dest vmdk file.

        During the copy also coalesce snapshots of src if present.
        dest_vmdk_file_path will be created if not already present.

        :param dc_ref: Reference to datacenter containing src and dest
        :param src_vmdk_file_path: Source vmdk file path
        :param dest_vmdk_file_path: Destination vmdk file path
        """
        LOG.debug(_('Copying disk data before snapshot of the VM'))
        diskMgr = self._session.vim.service_content.virtualDiskManager
        task = self._session.invoke_api(self._session.vim,
                                        'CopyVirtualDisk_Task',
                                        diskMgr,
                                        sourceName=src_vmdk_file_path,
                                        sourceDatacenter=dc_ref,
                                        destName=dest_vmdk_file_path,
                                        destDatacenter=dc_ref,
                                        force=True)
        LOG.debug(_("Initiated copying disk data via task: %s.") % task)
        self._session.wait_for_task(task)
        LOG.info(_("Successfully copied disk at: %(src)s to: %(dest)s.") %
                 {'src': src_vmdk_file_path, 'dest': dest_vmdk_file_path})

    def delete_vmdk_file(self, vmdk_file_path, dc_ref):
        """Delete given vmdk files.

        :param vmdk_file_path: VMDK file path to be deleted
        :param dc_ref: Reference to datacenter that contains this VMDK file
        """
        LOG.debug(_("Deleting vmdk file: %s.") % vmdk_file_path)
        diskMgr = self._session.vim.service_content.virtualDiskManager
        task = self._session.invoke_api(self._session.vim,
                                        'DeleteVirtualDisk_Task',
                                        diskMgr,
                                        name=vmdk_file_path,
                                        datacenter=dc_ref)
        LOG.debug(_("Initiated deleting vmdk file via task: %s.") % task)
        self._session.wait_for_task(task)
        LOG.info(_("Deleted vmdk file: %s.") % vmdk_file_path)
