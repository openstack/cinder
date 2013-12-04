# Copyright (c) 2014 VMware, Inc.
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
Test suite for VMware VMDK driver volumeops module.
"""

import mock

from cinder import test
from cinder import units
from cinder.volume.drivers.vmware import error_util
from cinder.volume.drivers.vmware import vim_util
from cinder.volume.drivers.vmware import volumeops


class VolumeOpsTestCase(test.TestCase):
    """Unit tests for volumeops module."""

    MAX_OBJECTS = 100

    def setUp(self):
        super(VolumeOpsTestCase, self).setUp()
        self.session = mock.MagicMock()
        self.vops = volumeops.VMwareVolumeOps(self.session, self.MAX_OBJECTS)

    def test_split_datastore_path(self):
        test1 = '[datastore1] myfolder/mysubfolder/myvm.vmx'
        (datastore, folder, file_name) = volumeops.split_datastore_path(test1)
        self.assertEqual(datastore, 'datastore1')
        self.assertEqual(folder, 'myfolder/mysubfolder/')
        self.assertEqual(file_name, 'myvm.vmx')

        test2 = '[datastore2 ]   myfolder/myvm.vmdk'
        (datastore, folder, file_name) = volumeops.split_datastore_path(test2)
        self.assertEqual(datastore, 'datastore2')
        self.assertEqual(folder, 'myfolder/')
        self.assertEqual(file_name, 'myvm.vmdk')

        test3 = 'myfolder/myvm.vmdk'
        self.assertRaises(IndexError, volumeops.split_datastore_path, test3)

    def vm(self, val):
        """Create a mock vm in retrieve result format."""
        vm = mock.MagicMock()
        prop = mock.Mock(spec=object)
        prop.val = val
        vm.propSet = [prop]
        return vm

    def test_get_backing(self):
        name = 'mock-backing'

        # Test no result
        self.session.invoke_api.return_value = None
        result = self.vops.get_backing(name)
        self.assertIsNone(result)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'get_objects',
                                                        self.session.vim,
                                                        'VirtualMachine',
                                                        self.MAX_OBJECTS)

        # Test single result
        vm = self.vm(name)
        vm.obj = mock.sentinel.vm_obj
        retrieve_result = mock.Mock(spec=object)
        retrieve_result.objects = [vm]
        self.session.invoke_api.return_value = retrieve_result
        self.vops.cancel_retrieval = mock.Mock(spec=object)
        result = self.vops.get_backing(name)
        self.assertEqual(mock.sentinel.vm_obj, result)
        self.session.invoke_api.assert_called_with(vim_util, 'get_objects',
                                                   self.session.vim,
                                                   'VirtualMachine',
                                                   self.MAX_OBJECTS)
        self.vops.cancel_retrieval.assert_called_once_with(retrieve_result)

        # Test multiple results
        retrieve_result2 = mock.Mock(spec=object)
        retrieve_result2.objects = [vm('1'), vm('2'), vm('3')]
        self.session.invoke_api.return_value = retrieve_result2
        self.vops.continue_retrieval = mock.Mock(spec=object)
        self.vops.continue_retrieval.return_value = retrieve_result
        result = self.vops.get_backing(name)
        self.assertEqual(mock.sentinel.vm_obj, result)
        self.session.invoke_api.assert_called_with(vim_util, 'get_objects',
                                                   self.session.vim,
                                                   'VirtualMachine',
                                                   self.MAX_OBJECTS)
        self.vops.continue_retrieval.assert_called_once_with(retrieve_result2)
        self.vops.cancel_retrieval.assert_called_with(retrieve_result)

    def test_delete_backing(self):
        backing = mock.sentinel.backing
        task = mock.sentinel.task
        self.session.invoke_api.return_value = task
        self.vops.delete_backing(backing)
        self.session.invoke_api.assert_called_once_with(self.session.vim,
                                                        "Destroy_Task",
                                                        backing)
        self.session.wait_for_task(task)

    def test_get_host(self):
        instance = mock.sentinel.instance
        host = mock.sentinel.host
        self.session.invoke_api.return_value = host
        result = self.vops.get_host(instance)
        self.assertEqual(host, result)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'get_object_property',
                                                        self.session.vim,
                                                        instance,
                                                        'runtime.host')

    def test_get_hosts(self):
        hosts = mock.sentinel.hosts
        self.session.invoke_api.return_value = hosts
        result = self.vops.get_hosts()
        self.assertEqual(hosts, result)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'get_objects',
                                                        self.session.vim,
                                                        'HostSystem',
                                                        self.MAX_OBJECTS)

    def test_continue_retrieval(self):
        retrieve_result = mock.sentinel.retrieve_result
        self.session.invoke_api.return_value = retrieve_result
        result = self.vops.continue_retrieval(retrieve_result)
        self.assertEqual(retrieve_result, result)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'continue_retrieval',
                                                        self.session.vim,
                                                        retrieve_result)

    def test_cancel_retrieval(self):
        retrieve_result = mock.sentinel.retrieve_result
        self.session.invoke_api.return_value = retrieve_result
        result = self.vops.cancel_retrieval(retrieve_result)
        self.assertIsNone(result)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'cancel_retrieval',
                                                        self.session.vim,
                                                        retrieve_result)

    def test_is_usable(self):
        mount_info = mock.Mock(spec=object)
        mount_info.accessMode = "readWrite"
        mount_info.mounted = True
        mount_info.accessible = True
        datastore = mock.sentinel.datastore
        self.assertTrue(self.vops._is_usable(datastore, mount_info))

        del mount_info.mounted
        self.assertTrue(self.vops._is_usable(datastore, mount_info))

        mount_info.accessMode = "readonly"
        self.assertFalse(self.vops._is_usable(datastore, mount_info))

        mount_info.accessMode = "readWrite"
        mount_info.mounted = False
        self.assertFalse(self.vops._is_usable(datastore, mount_info))

        mount_info.mounted = True
        mount_info.accessible = False
        self.assertFalse(self.vops._is_usable(datastore, mount_info))

        with mock.patch.object(self.vops, 'get_summary') as get_summary:
            del mount_info.accessible
            summary = mock.Mock(spec=object)
            summary.accessible = True
            get_summary.return_value = summary
            self.assertTrue(self.vops._is_usable(datastore, mount_info))

            summary.accessible = False
            self.assertFalse(self.vops._is_usable(datastore, mount_info))

    def _create_host_mounts(self, access_mode, host, set_accessible=True,
                            is_accessible=True, mounted=True):
        """Create host mount value of datastore with single mount info.

        :param access_mode: string specifying the read/write permission
        :param set_accessible: specify whether accessible property
                               should be set
        :param is_accessible: boolean specifying whether the datastore
                              is accessible to host
        :param host: managed object reference of the connected
                     host
        :return: list of host mount info
        """
        mntInfo = mock.Mock(spec=object)
        mntInfo.accessMode = access_mode
        if set_accessible:
            mntInfo.accessible = is_accessible
        else:
            del mntInfo.accessible
        mntInfo.mounted = mounted

        host_mount = mock.Mock(spec=object)
        host_mount.key = host
        host_mount.mountInfo = mntInfo
        host_mounts = mock.Mock(spec=object)
        host_mounts.DatastoreHostMount = [host_mount]

        return host_mounts

    def test_get_connected_hosts(self):
        datastore = mock.sentinel.datastore
        host = mock.Mock(spec=object)
        host.value = mock.sentinel.host
        host_mounts = self._create_host_mounts("readWrite", host)
        self.session.invoke_api.return_value = host_mounts

        hosts = self.vops.get_connected_hosts(datastore)
        self.assertEqual([mock.sentinel.host], hosts)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'get_object_property',
                                                        self.session.vim,
                                                        datastore,
                                                        'host')

    def test_is_valid(self):
        datastore = mock.sentinel.datastore
        host = mock.Mock(spec=object)
        host.value = mock.sentinel.host

        def _is_valid(host_mounts, is_valid):
            self.session.invoke_api.return_value = host_mounts
            result = self.vops._is_valid(datastore, host)
            self.assertEqual(is_valid, result)
            self.session.invoke_api.assert_called_with(vim_util,
                                                       'get_object_property',
                                                       self.session.vim,
                                                       datastore,
                                                       'host')
        # Test with accessible attr
        _is_valid(self._create_host_mounts("readWrite", host), True)

        # Test without accessible attr, and use summary instead
        with mock.patch.object(self.vops, 'get_summary') as get_summary:
            summary = mock.Mock(spec=object)
            summary.accessible = True
            get_summary.return_value = summary
            _is_valid(self._create_host_mounts("readWrite", host, False),
                      True)

        # Test negative cases for is_valid
        _is_valid(self._create_host_mounts("Inaccessible", host), False)
        _is_valid(self._create_host_mounts("readWrite", host, True, False),
                  False)
        _is_valid(self._create_host_mounts("readWrite", host, True, True,
                                           False), False)
        with mock.patch.object(self.vops, 'get_summary') as get_summary:
            summary = mock.Mock(spec=object)
            summary.accessible = False
            get_summary.return_value = summary
            _is_valid(self._create_host_mounts("readWrite", host, False),
                      False)

    def test_get_dss_rp(self):
        # build out props to be returned by 1st invoke_api call
        datastore_prop = mock.Mock(spec=object)
        datastore_prop.name = 'datastore'
        datastore_prop.val = mock.Mock(spec=object)
        datastore_prop.val.ManagedObjectReference = [mock.sentinel.ds1,
                                                     mock.sentinel.ds2]
        compute_resource_prop = mock.Mock(spec=object)
        compute_resource_prop.name = 'parent'
        compute_resource_prop.val = mock.sentinel.compute_resource
        elem = mock.Mock(spec=object)
        elem.propSet = [datastore_prop, compute_resource_prop]
        props = [elem]
        # build out host_mounts to be returned by 2nd invoke_api call
        host = mock.Mock(spec=object)
        host.value = mock.sentinel.host
        host_mounts = self._create_host_mounts("readWrite", host)
        # build out resource_pool to be returned by 3rd invoke_api call
        resource_pool = mock.sentinel.resource_pool
        # set return values for each call of invoke_api
        self.session.invoke_api.side_effect = [props,
                                               host_mounts,
                                               host_mounts,
                                               resource_pool]
        # invoke function and verify results
        (dss_actual, rp_actual) = self.vops.get_dss_rp(host)
        self.assertEqual([mock.sentinel.ds1, mock.sentinel.ds2], dss_actual)
        self.assertEqual(resource_pool, rp_actual)

        # invoke function with no valid datastore and verify exception raised
        host_mounts = self._create_host_mounts("inaccessible", host)
        self.session.invoke_api.side_effect = [props,
                                               host_mounts,
                                               host_mounts,
                                               resource_pool]
        self.assertRaises(error_util.VimException, self.vops.get_dss_rp, host)

    def test_get_parent(self):
        # Not recursive
        child = mock.Mock(spec=object)
        child._type = 'Parent'
        ret = self.vops._get_parent(child, 'Parent')
        self.assertEqual(ret, child)

        # Recursive
        parent = mock.Mock(spec=object)
        parent._type = 'Parent'
        child = mock.Mock(spec=object)
        child._type = 'Child'
        self.session.invoke_api.return_value = parent
        ret = self.vops._get_parent(child, 'Parent')
        self.assertEqual(ret, parent)
        self.session.invoke_api.assert_called_with(vim_util,
                                                   'get_object_property',
                                                   self.session.vim, child,
                                                   'parent')

    def test_get_dc(self):
        # set up hierarchy of objects
        dc = mock.Mock(spec=object)
        dc._type = 'Datacenter'
        o1 = mock.Mock(spec=object)
        o1._type = 'mockType1'
        o1.parent = dc
        o2 = mock.Mock(spec=object)
        o2._type = 'mockType2'
        o2.parent = o1

        # mock out invoke_api behaviour to fetch parent
        def mock_invoke_api(vim_util, method, vim, the_object, arg):
            return the_object.parent

        self.session.invoke_api.side_effect = mock_invoke_api
        ret = self.vops.get_dc(o2)
        self.assertEqual(dc, ret)

    def test_get_vmfolder(self):
        self.session.invoke_api.return_value = mock.sentinel.ret
        ret = self.vops.get_vmfolder(mock.sentinel.dc)
        self.assertEqual(mock.sentinel.ret, ret)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'get_object_property',
                                                        self.session.vim,
                                                        mock.sentinel.dc,
                                                        'vmFolder')

    def test_create_folder_not_present(self):
        """Test create_folder when child not present."""
        parent_folder = mock.sentinel.parent_folder
        child_name = 'child_folder'
        prop_val = mock.Mock(spec=object)
        prop_val.ManagedObjectReference = []
        child_folder = mock.sentinel.child_folder
        self.session.invoke_api.side_effect = [prop_val, child_folder]
        ret = self.vops.create_folder(parent_folder, child_name)
        self.assertEqual(child_folder, ret)
        expected_invoke_api = [mock.call(vim_util, 'get_object_property',
                                         self.session.vim, parent_folder,
                                         'childEntity'),
                               mock.call(self.session.vim, 'CreateFolder',
                                         parent_folder, name=child_name)]
        self.assertEqual(expected_invoke_api,
                         self.session.invoke_api.mock_calls)

    def test_create_folder_already_present(self):
        """Test create_folder when child already present."""
        parent_folder = mock.sentinel.parent_folder
        child_name = 'child_folder'
        prop_val = mock.Mock(spec=object)
        child_entity_1 = mock.Mock(spec=object)
        child_entity_1._type = 'Folder'
        child_entity_1_name = 'SomeOtherName'
        child_entity_2 = mock.Mock(spec=object)
        child_entity_2._type = 'Folder'
        child_entity_2_name = child_name
        prop_val.ManagedObjectReference = [child_entity_1, child_entity_2]
        self.session.invoke_api.side_effect = [prop_val, child_entity_1_name,
                                               child_entity_2_name]
        ret = self.vops.create_folder(parent_folder, child_name)
        self.assertEqual(child_entity_2, ret)
        expected_invoke_api = [mock.call(vim_util, 'get_object_property',
                                         self.session.vim, parent_folder,
                                         'childEntity'),
                               mock.call(vim_util, 'get_object_property',
                                         self.session.vim, child_entity_1,
                                         'name'),
                               mock.call(vim_util, 'get_object_property',
                                         self.session.vim, child_entity_2,
                                         'name')]
        self.assertEqual(expected_invoke_api,
                         self.session.invoke_api.mock_calls)

    def test_get_create_spec(self):
        factory = self.session.vim.client.factory
        factory.create.return_value = mock.Mock(spec=object)
        name = mock.sentinel.name
        size_kb = 0.5
        disk_type = 'thin'
        ds_name = mock.sentinel.ds_name
        ret = self.vops._get_create_spec(name, size_kb, disk_type, ds_name)
        self.assertEqual(name, ret.name)
        self.assertEqual('[%s]' % ds_name, ret.files.vmPathName)
        self.assertEqual(1, ret.deviceChange[1].device.capacityInKB)
        expected = [mock.call.create('ns0:VirtualLsiLogicController'),
                    mock.call.create('ns0:VirtualDeviceConfigSpec'),
                    mock.call.create('ns0:VirtualDisk'),
                    mock.call.create('ns0:VirtualDiskFlatVer2BackingInfo'),
                    mock.call.create('ns0:VirtualDeviceConfigSpec'),
                    mock.call.create('ns0:VirtualMachineFileInfo'),
                    mock.call.create('ns0:VirtualMachineConfigSpec')]
        factory.create.assert_has_calls(expected, any_order=True)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_create_spec')
    def test_create_backing(self, get_create_spec):
        create_spec = mock.sentinel.create_spec
        get_create_spec.return_value = create_spec
        task = mock.sentinel.task
        self.session.invoke_api.return_value = task
        task_info = mock.Mock(spec=object)
        task_info.result = mock.sentinel.result
        self.session.wait_for_task.return_value = task_info
        name = 'backing_name'
        size_kb = mock.sentinel.size_kb
        disk_type = mock.sentinel.disk_type
        folder = mock.sentinel.folder
        resource_pool = mock.sentinel.resource_pool
        host = mock.sentinel.host
        ds_name = mock.sentinel.ds_name
        ret = self.vops.create_backing(name, size_kb, disk_type, folder,
                                       resource_pool, host, ds_name)
        self.assertEqual(mock.sentinel.result, ret)
        get_create_spec.assert_called_once_with(name, size_kb, disk_type,
                                                ds_name, None)
        self.session.invoke_api.assert_called_once_with(self.session.vim,
                                                        'CreateVM_Task',
                                                        folder,
                                                        config=create_spec,
                                                        pool=resource_pool,
                                                        host=host)
        self.session.wait_for_task.assert_called_once_with(task)

    def test_get_datastore(self):
        backing = mock.sentinel.backing
        datastore = mock.Mock(spec=object)
        datastore.ManagedObjectReference = [mock.sentinel.ds]
        self.session.invoke_api.return_value = datastore
        ret = self.vops.get_datastore(backing)
        self.assertEqual(mock.sentinel.ds, ret)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'get_object_property',
                                                        self.session.vim,
                                                        backing, 'datastore')

    def test_get_summary(self):
        datastore = mock.sentinel.datastore
        summary = mock.sentinel.summary
        self.session.invoke_api.return_value = summary
        ret = self.vops.get_summary(datastore)
        self.assertEqual(summary, ret)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'get_object_property',
                                                        self.session.vim,
                                                        datastore,
                                                        'summary')

    def test_get_relocate_spec(self):
        factory = self.session.vim.client.factory
        spec = mock.Mock(spec=object)
        factory.create.return_value = spec
        datastore = mock.sentinel.datastore
        resource_pool = mock.sentinel.resource_pool
        host = mock.sentinel.host
        disk_move_type = mock.sentinel.disk_move_type
        ret = self.vops._get_relocate_spec(datastore, resource_pool, host,
                                           disk_move_type)
        self.assertEqual(spec, ret)
        self.assertEqual(datastore, ret.datastore)
        self.assertEqual(resource_pool, ret.pool)
        self.assertEqual(host, ret.host)
        self.assertEqual(disk_move_type, ret.diskMoveType)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_relocate_spec')
    def test_relocate_backing(self, get_relocate_spec):
        spec = mock.sentinel.relocate_spec
        get_relocate_spec.return_value = spec
        task = mock.sentinel.task
        self.session.invoke_api.return_value = task
        backing = mock.sentinel.backing
        datastore = mock.sentinel.datastore
        resource_pool = mock.sentinel.resource_pool
        host = mock.sentinel.host
        self.vops.relocate_backing(backing, datastore, resource_pool, host)
        # Verify calls
        disk_move_type = 'moveAllDiskBackingsAndAllowSharing'
        get_relocate_spec.assert_called_once_with(datastore, resource_pool,
                                                  host, disk_move_type)
        self.session.invoke_api.assert_called_once_with(self.session.vim,
                                                        'RelocateVM_Task',
                                                        backing,
                                                        spec=spec)
        self.session.wait_for_task.assert_called_once_with(task)

    def test_move_backing_to_folder(self):
        task = mock.sentinel.task
        self.session.invoke_api.return_value = task
        backing = mock.sentinel.backing
        folder = mock.sentinel.folder
        self.vops.move_backing_to_folder(backing, folder)
        # Verify calls
        self.session.invoke_api.assert_called_once_with(self.session.vim,
                                                        'MoveIntoFolder_Task',
                                                        folder,
                                                        list=[backing])
        self.session.wait_for_task.assert_called_once_with(task)

    def test_create_snapshot_operation(self):
        task = mock.sentinel.task
        self.session.invoke_api.return_value = task
        task_info = mock.Mock(spec=object)
        task_info.result = mock.sentinel.result
        self.session.wait_for_task.return_value = task_info
        backing = mock.sentinel.backing
        name = mock.sentinel.name
        desc = mock.sentinel.description
        quiesce = True
        ret = self.vops.create_snapshot(backing, name, desc, quiesce)
        self.assertEqual(mock.sentinel.result, ret)
        self.session.invoke_api.assert_called_once_with(self.session.vim,
                                                        'CreateSnapshot_Task',
                                                        backing, name=name,
                                                        description=desc,
                                                        memory=False,
                                                        quiesce=quiesce)
        self.session.wait_for_task.assert_called_once_with(task)

    def test_get_snapshot_from_tree(self):
        volops = volumeops.VMwareVolumeOps
        name = mock.sentinel.name
        # Test snapshot == 'None'
        ret = volops._get_snapshot_from_tree(name, None)
        self.assertIsNone(ret)
        # Test root == snapshot
        snapshot = mock.sentinel.snapshot
        node = mock.Mock(spec=object)
        node.name = name
        node.snapshot = snapshot
        ret = volops._get_snapshot_from_tree(name, node)
        self.assertEqual(ret, snapshot)
        # Test root.childSnapshotList == None
        root = mock.Mock(spec=object)
        root.name = 'root'
        del root.childSnapshotList
        ret = volops._get_snapshot_from_tree(name, root)
        self.assertIsNone(ret)
        # Test root.child == snapshot
        root.childSnapshotList = [node]
        ret = volops._get_snapshot_from_tree(name, root)
        self.assertEqual(ret, snapshot)

    def test_get_snapshot(self):
        # build out the root snapshot tree
        snapshot_name = mock.sentinel.snapshot_name
        snapshot = mock.sentinel.snapshot
        root = mock.Mock(spec=object)
        root.name = 'root'
        node = mock.Mock(spec=object)
        node.name = snapshot_name
        node.snapshot = snapshot
        root.childSnapshotList = [node]
        # Test rootSnapshotList is not None
        snapshot_tree = mock.Mock(spec=object)
        snapshot_tree.rootSnapshotList = [root]
        self.session.invoke_api.return_value = snapshot_tree
        backing = mock.sentinel.backing
        ret = self.vops.get_snapshot(backing, snapshot_name)
        self.assertEqual(snapshot, ret)
        self.session.invoke_api.assert_called_with(vim_util,
                                                   'get_object_property',
                                                   self.session.vim,
                                                   backing,
                                                   'snapshot')
        # Test rootSnapshotList == None
        snapshot_tree.rootSnapshotList = None
        ret = self.vops.get_snapshot(backing, snapshot_name)
        self.assertIsNone(ret)
        self.session.invoke_api.assert_called_with(vim_util,
                                                   'get_object_property',
                                                   self.session.vim,
                                                   backing,
                                                   'snapshot')

    def test_delete_snapshot(self):
        backing = mock.sentinel.backing
        snapshot_name = mock.sentinel.snapshot_name
        # Test snapshot is None
        with mock.patch.object(self.vops, 'get_snapshot') as get_snapshot:
            get_snapshot.return_value = None
            self.vops.delete_snapshot(backing, snapshot_name)
            get_snapshot.assert_called_once_with(backing, snapshot_name)
        # Test snapshot is not None
        snapshot = mock.sentinel.snapshot
        task = mock.sentinel.task
        invoke_api = self.session.invoke_api
        invoke_api.return_value = task
        with mock.patch.object(self.vops, 'get_snapshot') as get_snapshot:
            get_snapshot.return_value = snapshot
            self.vops.delete_snapshot(backing, snapshot_name)
            get_snapshot.assert_called_with(backing, snapshot_name)
            invoke_api.assert_called_once_with(self.session.vim,
                                               'RemoveSnapshot_Task',
                                               snapshot, removeChildren=False)
            self.session.wait_for_task.assert_called_once_with(task)

    def test_get_folder(self):
        folder = mock.sentinel.folder
        backing = mock.sentinel.backing
        with mock.patch.object(self.vops, '_get_parent') as get_parent:
            get_parent.return_value = folder
            ret = self.vops._get_folder(backing)
            self.assertEqual(folder, ret)
            get_parent.assert_called_once_with(backing, 'Folder')

    def test_get_clone_spec(self):
        factory = self.session.vim.client.factory
        spec = mock.Mock(spec=object)
        factory.create.return_value = spec
        datastore = mock.sentinel.datastore
        disk_move_type = mock.sentinel.disk_move_type
        snapshot = mock.sentinel.snapshot
        ret = self.vops._get_clone_spec(datastore, disk_move_type, snapshot)
        self.assertEqual(spec, ret)
        self.assertEqual(snapshot, ret.snapshot)
        self.assertEqual(spec, ret.location)
        self.assertEqual(datastore, ret.location.datastore)
        self.assertEqual(disk_move_type, ret.location.diskMoveType)
        expected_calls = [mock.call('ns0:VirtualMachineRelocateSpec'),
                          mock.call('ns0:VirtualMachineCloneSpec')]
        factory.create.assert_has_calls(expected_calls, any_order=True)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_clone_spec')
    def test_clone_backing(self, get_clone_spec):
        folder = mock.Mock(name='folder', spec=object)
        folder._type = 'Folder'
        task = mock.sentinel.task
        self.session.invoke_api.side_effect = [folder, task, folder, task]
        task_info = mock.Mock(spec=object)
        task_info.result = mock.sentinel.new_backing
        self.session.wait_for_task.return_value = task_info
        clone_spec = mock.sentinel.clone_spec
        get_clone_spec.return_value = clone_spec
        # Test non-linked clone_backing
        name = mock.sentinel.name
        backing = mock.Mock(spec=object)
        backing._type = 'VirtualMachine'
        snapshot = mock.sentinel.snapshot
        clone_type = "anything-other-than-linked"
        datastore = mock.sentinel.datstore
        ret = self.vops.clone_backing(name, backing, snapshot, clone_type,
                                      datastore)
        # verify calls
        self.assertEqual(mock.sentinel.new_backing, ret)
        disk_move_type = 'moveAllDiskBackingsAndDisallowSharing'
        get_clone_spec.assert_called_with(datastore, disk_move_type, snapshot)
        expected = [mock.call(vim_util, 'get_object_property',
                              self.session.vim, backing, 'parent'),
                    mock.call(self.session.vim, 'CloneVM_Task', backing,
                              folder=folder, name=name, spec=clone_spec)]
        self.assertEqual(expected, self.session.invoke_api.mock_calls)

        # Test linked clone_backing
        clone_type = volumeops.LINKED_CLONE_TYPE
        ret = self.vops.clone_backing(name, backing, snapshot, clone_type,
                                      datastore)
        # verify calls
        self.assertEqual(mock.sentinel.new_backing, ret)
        disk_move_type = 'createNewChildDiskBacking'
        get_clone_spec.assert_called_with(datastore, disk_move_type, snapshot)
        expected = [mock.call(vim_util, 'get_object_property',
                              self.session.vim, backing, 'parent'),
                    mock.call(self.session.vim, 'CloneVM_Task', backing,
                              folder=folder, name=name, spec=clone_spec),
                    mock.call(vim_util, 'get_object_property',
                              self.session.vim, backing, 'parent'),
                    mock.call(self.session.vim, 'CloneVM_Task', backing,
                              folder=folder, name=name, spec=clone_spec)]
        self.assertEqual(expected, self.session.invoke_api.mock_calls)

    def test_delete_file(self):
        file_mgr = mock.sentinel.file_manager
        self.session.vim.service_content.fileManager = file_mgr
        task = mock.sentinel.task
        invoke_api = self.session.invoke_api
        invoke_api.return_value = task
        # Test delete file
        file_path = mock.sentinel.file_path
        datacenter = mock.sentinel.datacenter
        self.vops.delete_file(file_path, datacenter)
        # verify calls
        invoke_api.assert_called_once_with(self.session.vim,
                                           'DeleteDatastoreFile_Task',
                                           file_mgr,
                                           name=file_path,
                                           datacenter=datacenter)
        self.session.wait_for_task.assert_called_once_with(task)

    def test_get_path_name(self):
        path = mock.Mock(spec=object)
        path_name = mock.sentinel.vm_path_name
        path.vmPathName = path_name
        invoke_api = self.session.invoke_api
        invoke_api.return_value = path
        backing = mock.sentinel.backing
        ret = self.vops.get_path_name(backing)
        self.assertEqual(path_name, ret)
        invoke_api.assert_called_once_with(vim_util, 'get_object_property',
                                           self.session.vim, backing,
                                           'config.files')

    def test_get_entity_name(self):
        entity_name = mock.sentinel.entity_name
        invoke_api = self.session.invoke_api
        invoke_api.return_value = entity_name
        entity = mock.sentinel.entity
        ret = self.vops.get_entity_name(entity)
        self.assertEqual(entity_name, ret)
        invoke_api.assert_called_once_with(vim_util, 'get_object_property',
                                           self.session.vim, entity, 'name')

    def test_get_vmdk_path(self):
        # Setup hardware_devices for test
        device = mock.Mock()
        device.__class__.__name__ = 'VirtualDisk'
        backing = mock.Mock()
        backing.__class__.__name__ = 'VirtualDiskFlatVer2BackingInfo'
        backing.fileName = mock.sentinel.vmdk_path
        device.backing = backing
        invoke_api = self.session.invoke_api
        invoke_api.return_value = [device]
        # Test get_vmdk_path
        ret = self.vops.get_vmdk_path(backing)
        self.assertEqual(mock.sentinel.vmdk_path, ret)
        invoke_api.assert_called_once_with(vim_util, 'get_object_property',
                                           self.session.vim, backing,
                                           'config.hardware.device')

    def test_copy_vmdk_file(self):
        task = mock.sentinel.task
        invoke_api = self.session.invoke_api
        invoke_api.return_value = task
        disk_mgr = self.session.vim.service_content.virtualDiskManager
        dc_ref = self.session.dc_ref
        src_vmdk_file_path = self.session.src
        dest_vmdk_file_path = self.session.dest
        self.vops.copy_vmdk_file(dc_ref, src_vmdk_file_path,
                                 dest_vmdk_file_path)
        invoke_api.assert_called_once_with(self.session.vim,
                                           'CopyVirtualDisk_Task',
                                           disk_mgr,
                                           sourceName=src_vmdk_file_path,
                                           sourceDatacenter=dc_ref,
                                           destName=dest_vmdk_file_path,
                                           destDatacenter=dc_ref,
                                           force=True)
        self.session.wait_for_task.assert_called_once_with(task)

    def test_delete_vmdk_file(self):
        task = mock.sentinel.task
        invoke_api = self.session.invoke_api
        invoke_api.return_value = task
        disk_mgr = self.session.vim.service_content.virtualDiskManager
        dc_ref = self.session.dc_ref
        vmdk_file_path = self.session.vmdk_file
        self.vops.delete_vmdk_file(vmdk_file_path, dc_ref)
        invoke_api.assert_called_once_with(self.session.vim,
                                           'DeleteVirtualDisk_Task',
                                           disk_mgr,
                                           name=vmdk_file_path,
                                           datacenter=dc_ref)
        self.session.wait_for_task.assert_called_once_with(task)

    def test_extend_virtual_disk(self):
        """Test volumeops.extend_virtual_disk."""
        task = mock.sentinel.task
        invoke_api = self.session.invoke_api
        invoke_api.return_value = task
        disk_mgr = self.session.vim.service_content.virtualDiskManager
        fake_size = 5
        fake_size_in_kb = fake_size * units.MiB
        fake_name = 'fake_volume_0000000001'
        fake_dc = mock.sentinel.datacenter
        self.vops.extend_virtual_disk(fake_size,
                                      fake_name, fake_dc)
        invoke_api.assert_called_once_with(self.session.vim,
                                           "ExtendVirtualDisk_Task",
                                           disk_mgr,
                                           name=fake_name,
                                           datacenter=fake_dc,
                                           newCapacityKb=fake_size_in_kb,
                                           eagerZero=False)
        self.session.wait_for_task.assert_called_once_with(task)
