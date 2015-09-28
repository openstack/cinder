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
from oslo_utils import units
from oslo_vmware import exceptions
from oslo_vmware import vim_util

from cinder import test
from cinder.volume.drivers.vmware import exceptions as vmdk_exceptions
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
        self.assertEqual('datastore1', datastore)
        self.assertEqual('myfolder/mysubfolder/', folder)
        self.assertEqual('myvm.vmx', file_name)

        test2 = '[datastore2 ]   myfolder/myvm.vmdk'
        (datastore, folder, file_name) = volumeops.split_datastore_path(test2)
        self.assertEqual('datastore2', datastore)
        self.assertEqual('myfolder/', folder)
        self.assertEqual('myvm.vmdk', file_name)

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

    def _host_runtime_info(
            self, connection_state='connected', in_maintenance=False):
        return mock.Mock(connectionState=connection_state,
                         inMaintenanceMode=in_maintenance)

    def test_is_host_usable(self):
        self.session.invoke_api.return_value = self._host_runtime_info()

        self.assertTrue(self.vops.is_host_usable(mock.sentinel.host))
        self.session.invoke_api.assert_called_once_with(
            vim_util, 'get_object_property', self.session.vim,
            mock.sentinel.host, 'runtime')

    def test_is_host_usable_with_disconnected_host(self):
        self.session.invoke_api.return_value = self._host_runtime_info(
            connection_state='disconnected')

        self.assertFalse(self.vops.is_host_usable(mock.sentinel.host))
        self.session.invoke_api.assert_called_once_with(
            vim_util, 'get_object_property', self.session.vim,
            mock.sentinel.host, 'runtime')

    def test_is_host_usable_with_host_in_maintenance(self):
        self.session.invoke_api.return_value = self._host_runtime_info(
            in_maintenance=True)

        self.assertFalse(self.vops.is_host_usable(mock.sentinel.host))
        self.session.invoke_api.assert_called_once_with(
            vim_util, 'get_object_property', self.session.vim,
            mock.sentinel.host, 'runtime')

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
        self.assertTrue(self.vops._is_usable(mount_info))

        del mount_info.mounted
        self.assertTrue(self.vops._is_usable(mount_info))

        mount_info.accessMode = "readonly"
        self.assertFalse(self.vops._is_usable(mount_info))

        mount_info.accessMode = "readWrite"
        mount_info.mounted = False
        self.assertFalse(self.vops._is_usable(mount_info))

        mount_info.mounted = True
        mount_info.accessible = False
        self.assertFalse(self.vops._is_usable(mount_info))

        del mount_info.accessible
        self.assertFalse(self.vops._is_usable(mount_info))

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
        with mock.patch.object(self.vops, 'get_summary') as get_summary:
            datastore = mock.sentinel.datastore
            summary = mock.Mock(spec=object)
            get_summary.return_value = summary

            summary.accessible = False
            hosts = self.vops.get_connected_hosts(datastore)
            self.assertEqual([], hosts)

            summary.accessible = True
            host = mock.Mock(spec=object)
            host.value = mock.sentinel.host
            host_mounts = self._create_host_mounts("readWrite", host)
            self.session.invoke_api.return_value = host_mounts
            hosts = self.vops.get_connected_hosts(datastore)
            self.assertEqual([mock.sentinel.host], hosts)
            self.session.invoke_api.assert_called_once_with(
                vim_util,
                'get_object_property',
                self.session.vim,
                datastore,
                'host')

            del host_mounts.DatastoreHostMount
            hosts = self.vops.get_connected_hosts(datastore)
            self.assertEqual([], hosts)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                'get_connected_hosts')
    def test_is_datastore_accessible(self, get_connected_hosts):
        host_1 = mock.sentinel.host_1
        host_2 = mock.sentinel.host_2
        get_connected_hosts.return_value = [host_1, host_2]

        ds = mock.sentinel.datastore
        host = mock.Mock(value=mock.sentinel.host_1)
        self.assertTrue(self.vops.is_datastore_accessible(ds, host))
        get_connected_hosts.assert_called_once_with(ds)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                'get_connected_hosts')
    def test_is_datastore_accessible_with_inaccessible(self,
                                                       get_connected_hosts):
        host_1 = mock.sentinel.host_1
        get_connected_hosts.return_value = [host_1]

        ds = mock.sentinel.datastore
        host = mock.Mock(value=mock.sentinel.host_2)
        self.assertFalse(self.vops.is_datastore_accessible(ds, host))
        get_connected_hosts.assert_called_once_with(ds)

    def test_is_valid(self):
        with mock.patch.object(self.vops, 'get_summary') as get_summary:
            summary = mock.Mock(spec=object)
            get_summary.return_value = summary

            datastore = mock.sentinel.datastore
            host = mock.Mock(spec=object)
            host.value = mock.sentinel.host

            def _is_valid(host_mounts, is_valid):
                self.session.invoke_api.return_value = host_mounts
                result = self.vops._is_valid(datastore, host)
                self.assertEqual(is_valid, result)
                self.session.invoke_api.assert_called_with(
                    vim_util,
                    'get_object_property',
                    self.session.vim,
                    datastore,
                    'host')

            # Test positive cases
            summary.maintenanceMode = 'normal'
            summary.accessible = True
            _is_valid(self._create_host_mounts("readWrite", host), True)

            # Test negative cases
            _is_valid(self._create_host_mounts("Inaccessible", host), False)
            _is_valid(self._create_host_mounts("readWrite", host, True, False),
                      False)
            _is_valid(self._create_host_mounts("readWrite", host, True, True,
                                               False), False)

            summary.accessible = False
            _is_valid(self._create_host_mounts("readWrite", host, False),
                      False)

            summary.accessible = True
            summary.maintenanceMode = 'inMaintenance'
            _is_valid(self._create_host_mounts("readWrite", host), False)

    def test_get_dss_rp(self):
        with mock.patch.object(self.vops, 'get_summary') as get_summary:
            summary = mock.Mock(spec=object)
            summary.accessible = True
            summary.maintenanceModel = 'normal'
            get_summary.return_value = summary

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
            self.assertEqual([mock.sentinel.ds1, mock.sentinel.ds2],
                             dss_actual)
            self.assertEqual(resource_pool, rp_actual)

            # invoke function with no valid datastore
            summary.maintenanceMode = 'inMaintenance'
            self.session.invoke_api.side_effect = [props,
                                                   host_mounts,
                                                   host_mounts,
                                                   resource_pool]
            self.assertRaises(exceptions.VimException,
                              self.vops.get_dss_rp,
                              host)

            # Clear side effects.
            self.session.invoke_api.side_effect = None

    def test_get_parent(self):
        # Not recursive
        child = mock.Mock(spec=object)
        child._type = 'Parent'
        ret = self.vops._get_parent(child, 'Parent')
        self.assertEqual(child, ret)

        # Recursive
        parent = mock.Mock(spec=object)
        parent._type = 'Parent'
        child = mock.Mock(spec=object)
        child._type = 'Child'
        self.session.invoke_api.return_value = parent
        ret = self.vops._get_parent(child, 'Parent')
        self.assertEqual(parent, ret)
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

        # Clear side effects.
        self.session.invoke_api.side_effect = None

    def test_get_vmfolder(self):
        self.session.invoke_api.return_value = mock.sentinel.ret
        ret = self.vops.get_vmfolder(mock.sentinel.dc)
        self.assertEqual(mock.sentinel.ret, ret)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'get_object_property',
                                                        self.session.vim,
                                                        mock.sentinel.dc,
                                                        'vmFolder')

    def test_create_folder_with_concurrent_create(self):
        parent_folder = mock.sentinel.parent_folder
        child_name = 'child_folder'

        prop_val_1 = mock.Mock(ManagedObjectReference=[])

        child_folder = mock.Mock(_type='Folder')
        prop_val_2 = mock.Mock(ManagedObjectReference=[child_folder])

        self.session.invoke_api.side_effect = [prop_val_1,
                                               exceptions.DuplicateName,
                                               prop_val_2,
                                               child_name]

        ret = self.vops.create_folder(parent_folder, child_name)

        self.assertEqual(child_folder, ret)
        expected_invoke_api = [mock.call(vim_util, 'get_object_property',
                                         self.session.vim, parent_folder,
                                         'childEntity'),
                               mock.call(self.session.vim, 'CreateFolder',
                                         parent_folder, name=child_name),
                               mock.call(vim_util, 'get_object_property',
                                         self.session.vim, parent_folder,
                                         'childEntity'),
                               mock.call(vim_util, 'get_object_property',
                                         self.session.vim, child_folder,
                                         'name')]
        self.assertEqual(expected_invoke_api,
                         self.session.invoke_api.mock_calls)

    def test_create_folder_with_empty_vmfolder(self):
        """Test create_folder when the datacenter vmFolder is empty"""
        child_folder = mock.sentinel.child_folder
        self.session.invoke_api.side_effect = [None, child_folder]

        parent_folder = mock.sentinel.parent_folder
        child_name = 'child_folder'
        ret = self.vops.create_folder(parent_folder, child_name)

        self.assertEqual(child_folder, ret)
        expected_calls = [mock.call(vim_util, 'get_object_property',
                                    self.session.vim, parent_folder,
                                    'childEntity'),
                          mock.call(self.session.vim, 'CreateFolder',
                                    parent_folder, name=child_name)]
        self.assertEqual(expected_calls,
                         self.session.invoke_api.call_args_list)

    def test_create_folder_not_present(self):
        """Test create_folder when child not present."""
        prop_val = mock.Mock(spec=object)
        child_folder = mock.sentinel.child_folder
        self.session.invoke_api.side_effect = [prop_val, child_folder]

        child_name = 'child_folder'
        parent_folder = mock.sentinel.parent_folder
        ret = self.vops.create_folder(parent_folder, child_name)

        self.assertEqual(child_folder, ret)
        expected_invoke_api = [mock.call(vim_util, 'get_object_property',
                                         self.session.vim, parent_folder,
                                         'childEntity'),
                               mock.call(self.session.vim, 'CreateFolder',
                                         parent_folder, name=child_name)]
        self.assertEqual(expected_invoke_api,
                         self.session.invoke_api.mock_calls)

        # Clear side effects.
        self.session.invoke_api.side_effect = None

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

        # Clear side effects.
        self.session.invoke_api.side_effect = None

    def test_create_folder_with_special_characters(self):
        """Test create_folder with names containing special characters."""
        # Test folder already exists case.
        child_entity_1 = mock.Mock(_type='Folder')
        child_entity_1_name = 'cinder-volumes'

        child_entity_2 = mock.Mock(_type='Folder')
        child_entity_2_name = '%2fcinder-volumes'

        prop_val = mock.Mock(ManagedObjectReference=[child_entity_1,
                                                     child_entity_2])
        self.session.invoke_api.side_effect = [prop_val,
                                               child_entity_1_name,
                                               child_entity_2_name]

        parent_folder = mock.sentinel.parent_folder
        child_name = '/cinder-volumes'
        ret = self.vops.create_folder(parent_folder, child_name)

        self.assertEqual(child_entity_2, ret)

        # Test non-existing folder case.
        child_entity_2_name = '%25%25cinder-volumes'
        new_child_folder = mock.sentinel.new_child_folder
        self.session.invoke_api.side_effect = [prop_val,
                                               child_entity_1_name,
                                               child_entity_2_name,
                                               new_child_folder]

        child_name = '%cinder-volumes'
        ret = self.vops.create_folder(parent_folder, child_name)

        self.assertEqual(new_child_folder, ret)
        self.session.invoke_api.assert_called_with(self.session.vim,
                                                   'CreateFolder',
                                                   parent_folder,
                                                   name=child_name)

        # Reset side effects.
        self.session.invoke_api.side_effect = None

    def test_create_folder_with_duplicate_name(self):
        parent_folder = mock.sentinel.parent_folder
        child_name = 'child_folder'

        prop_val_1 = mock.Mock(spec=object)
        prop_val_1.ManagedObjectReference = []

        child_entity_2 = mock.Mock(spec=object)
        child_entity_2._type = 'Folder'
        prop_val_2 = mock.Mock(spec=object)
        prop_val_2.ManagedObjectReference = [child_entity_2]
        child_entity_2_name = child_name

        self.session.invoke_api.side_effect = [
            prop_val_1,
            exceptions.DuplicateName,
            prop_val_2,
            child_entity_2_name]

        ret = self.vops.create_folder(parent_folder, child_name)
        self.assertEqual(child_entity_2, ret)
        expected_invoke_api = [mock.call(vim_util, 'get_object_property',
                                         self.session.vim, parent_folder,
                                         'childEntity'),
                               mock.call(self.session.vim, 'CreateFolder',
                                         parent_folder, name=child_name),
                               mock.call(vim_util, 'get_object_property',
                                         self.session.vim, parent_folder,
                                         'childEntity'),
                               mock.call(vim_util, 'get_object_property',
                                         self.session.vim, child_entity_2,
                                         'name')]
        self.assertEqual(expected_invoke_api,
                         self.session.invoke_api.mock_calls)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                'get_vmfolder')
    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                'create_folder')
    def test_create_vm_inventory_folder(self, create_folder, get_vmfolder):
        vm_folder_1 = mock.sentinel.vm_folder_1
        get_vmfolder.return_value = vm_folder_1

        folder_1a = mock.sentinel.folder_1a
        folder_1b = mock.sentinel.folder_1b
        create_folder.side_effect = [folder_1a, folder_1b]

        datacenter_1 = mock.Mock(value='dc-1')
        path_comp = ['a', 'b']
        ret = self.vops.create_vm_inventory_folder(datacenter_1, path_comp)

        self.assertEqual(folder_1b, ret)
        get_vmfolder.assert_called_once_with(datacenter_1)
        exp_calls = [mock.call(vm_folder_1, 'a'), mock.call(folder_1a, 'b')]
        self.assertEqual(exp_calls, create_folder.call_args_list)
        exp_cache = {'/dc-1': vm_folder_1,
                     '/dc-1/a': folder_1a,
                     '/dc-1/a/b': folder_1b}
        self.assertEqual(exp_cache, self.vops._folder_cache)

        # Test cache
        get_vmfolder.reset_mock()
        create_folder.reset_mock()

        folder_1c = mock.sentinel.folder_1c
        create_folder.side_effect = [folder_1c]

        path_comp = ['a', 'c']
        ret = self.vops.create_vm_inventory_folder(datacenter_1, path_comp)

        self.assertEqual(folder_1c, ret)
        self.assertFalse(get_vmfolder.called)
        exp_calls = [mock.call(folder_1a, 'c')]
        self.assertEqual(exp_calls, create_folder.call_args_list)
        exp_cache = {'/dc-1': vm_folder_1,
                     '/dc-1/a': folder_1a,
                     '/dc-1/a/b': folder_1b,
                     '/dc-1/a/c': folder_1c}
        self.assertEqual(exp_cache, self.vops._folder_cache)

        # Test cache with different datacenter
        get_vmfolder.reset_mock()
        create_folder.reset_mock()

        vm_folder_2 = mock.sentinel.vm_folder_2
        get_vmfolder.return_value = vm_folder_2

        folder_2a = mock.sentinel.folder_2a
        folder_2b = mock.sentinel.folder_2b
        create_folder.side_effect = [folder_2a, folder_2b]

        datacenter_2 = mock.Mock(value='dc-2')
        path_comp = ['a', 'b']
        ret = self.vops.create_vm_inventory_folder(datacenter_2, path_comp)

        self.assertEqual(folder_2b, ret)
        get_vmfolder.assert_called_once_with(datacenter_2)
        exp_calls = [mock.call(vm_folder_2, 'a'), mock.call(folder_2a, 'b')]
        self.assertEqual(exp_calls, create_folder.call_args_list)
        exp_cache = {'/dc-1': vm_folder_1,
                     '/dc-1/a': folder_1a,
                     '/dc-1/a/b': folder_1b,
                     '/dc-1/a/c': folder_1c,
                     '/dc-2': vm_folder_2,
                     '/dc-2/a': folder_2a,
                     '/dc-2/a/b': folder_2b
                     }
        self.assertEqual(exp_cache, self.vops._folder_cache)

    def test_create_disk_backing_thin(self):
        backing = mock.Mock()
        del backing.eagerlyScrub
        cf = self.session.vim.client.factory
        cf.create.return_value = backing

        disk_type = 'thin'
        ret = self.vops._create_disk_backing(disk_type, None)

        self.assertEqual(backing, ret)
        self.assertIsInstance(ret.thinProvisioned, bool)
        self.assertTrue(ret.thinProvisioned)
        self.assertEqual('', ret.fileName)
        self.assertEqual('persistent', ret.diskMode)

    def test_create_disk_backing_thick(self):
        backing = mock.Mock()
        del backing.eagerlyScrub
        del backing.thinProvisioned
        cf = self.session.vim.client.factory
        cf.create.return_value = backing

        disk_type = 'thick'
        ret = self.vops._create_disk_backing(disk_type, None)

        self.assertEqual(backing, ret)
        self.assertEqual('', ret.fileName)
        self.assertEqual('persistent', ret.diskMode)

    def test_create_disk_backing_eager_zeroed_thick(self):
        backing = mock.Mock()
        del backing.thinProvisioned
        cf = self.session.vim.client.factory
        cf.create.return_value = backing

        disk_type = 'eagerZeroedThick'
        ret = self.vops._create_disk_backing(disk_type, None)

        self.assertEqual(backing, ret)
        self.assertIsInstance(ret.eagerlyScrub, bool)
        self.assertTrue(ret.eagerlyScrub)
        self.assertEqual('', ret.fileName)
        self.assertEqual('persistent', ret.diskMode)

    def test_create_virtual_disk_config_spec(self):

        cf = self.session.vim.client.factory
        cf.create.side_effect = lambda *args: mock.Mock()

        size_kb = units.Ki
        controller_key = 200
        disk_type = 'thick'
        spec = self.vops._create_virtual_disk_config_spec(size_kb,
                                                          disk_type,
                                                          controller_key,
                                                          None)

        cf.create.side_effect = None
        self.assertEqual('add', spec.operation)
        self.assertEqual('create', spec.fileOperation)
        device = spec.device
        self.assertEqual(size_kb, device.capacityInKB)
        self.assertEqual(-101, device.key)
        self.assertEqual(0, device.unitNumber)
        self.assertEqual(controller_key, device.controllerKey)
        backing = device.backing
        self.assertEqual('', backing.fileName)
        self.assertEqual('persistent', backing.diskMode)

    def test_create_specs_for_ide_disk_add(self):
        factory = self.session.vim.client.factory
        factory.create.side_effect = lambda *args: mock.Mock()

        size_kb = 1
        disk_type = 'thin'
        adapter_type = 'ide'
        ret = self.vops._create_specs_for_disk_add(size_kb, disk_type,
                                                   adapter_type)

        factory.create.side_effect = None
        self.assertEqual(1, len(ret))
        self.assertEqual(units.Ki, ret[0].device.capacityInKB)
        self.assertEqual(200, ret[0].device.controllerKey)
        expected = [mock.call.create('ns0:VirtualDeviceConfigSpec'),
                    mock.call.create('ns0:VirtualDisk'),
                    mock.call.create('ns0:VirtualDiskFlatVer2BackingInfo')]
        factory.create.assert_has_calls(expected, any_order=True)

    def test_create_specs_for_scsi_disk_add(self):
        factory = self.session.vim.client.factory
        factory.create.side_effect = lambda *args: mock.Mock()

        size_kb = 2 * units.Ki
        disk_type = 'thin'
        adapter_type = 'lsiLogicsas'
        ret = self.vops._create_specs_for_disk_add(size_kb, disk_type,
                                                   adapter_type)

        factory.create.side_effect = None
        self.assertEqual(2, len(ret))
        self.assertEqual('noSharing', ret[1].device.sharedBus)
        self.assertEqual(size_kb, ret[0].device.capacityInKB)
        expected = [mock.call.create('ns0:VirtualLsiLogicSASController'),
                    mock.call.create('ns0:VirtualDeviceConfigSpec'),
                    mock.call.create('ns0:VirtualDisk'),
                    mock.call.create('ns0:VirtualDiskFlatVer2BackingInfo'),
                    mock.call.create('ns0:VirtualDeviceConfigSpec')]
        factory.create.assert_has_calls(expected, any_order=True)

    def test_get_create_spec_disk_less(self):
        factory = self.session.vim.client.factory
        factory.create.side_effect = lambda *args: mock.Mock()

        name = mock.sentinel.name
        ds_name = mock.sentinel.ds_name
        profile_id = mock.sentinel.profile_id
        option_key = mock.sentinel.key
        option_value = mock.sentinel.value
        extra_config = {option_key: option_value}
        ret = self.vops._get_create_spec_disk_less(name, ds_name, profile_id,
                                                   extra_config)

        factory.create.side_effect = None
        self.assertEqual(name, ret.name)
        self.assertEqual('[%s]' % ds_name, ret.files.vmPathName)
        self.assertEqual("vmx-08", ret.version)
        self.assertEqual(profile_id, ret.vmProfile[0].profileId)
        self.assertEqual(1, len(ret.extraConfig))
        self.assertEqual(option_key, ret.extraConfig[0].key)
        self.assertEqual(option_value, ret.extraConfig[0].value)
        expected = [mock.call.create('ns0:VirtualMachineFileInfo'),
                    mock.call.create('ns0:VirtualMachineConfigSpec'),
                    mock.call.create('ns0:VirtualMachineDefinedProfileSpec'),
                    mock.call.create('ns0:OptionValue')]
        factory.create.assert_has_calls(expected, any_order=True)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_create_spec_disk_less')
    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_create_specs_for_disk_add')
    def test_get_create_spec(self, create_specs_for_disk_add,
                             get_create_spec_disk_less):
        name = 'vol-1'
        size_kb = 1024
        disk_type = 'thin'
        ds_name = 'nfs-1'
        profileId = mock.sentinel.profile_id
        adapter_type = 'busLogic'
        extra_config = mock.sentinel.extra_config

        self.vops.get_create_spec(name, size_kb, disk_type, ds_name,
                                  profileId, adapter_type, extra_config)

        get_create_spec_disk_less.assert_called_once_with(
            name, ds_name, profileId=profileId, extra_config=extra_config)
        create_specs_for_disk_add.assert_called_once_with(
            size_kb, disk_type, adapter_type)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                'get_create_spec')
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
        adapter_type = mock.sentinel.adapter_type
        folder = mock.sentinel.folder
        resource_pool = mock.sentinel.resource_pool
        host = mock.sentinel.host
        ds_name = mock.sentinel.ds_name
        profile_id = mock.sentinel.profile_id
        extra_config = mock.sentinel.extra_config
        ret = self.vops.create_backing(name, size_kb, disk_type, folder,
                                       resource_pool, host, ds_name,
                                       profile_id, adapter_type, extra_config)
        self.assertEqual(mock.sentinel.result, ret)
        get_create_spec.assert_called_once_with(
            name, size_kb, disk_type, ds_name, profileId=profile_id,
            adapter_type=adapter_type, extra_config=extra_config)
        self.session.invoke_api.assert_called_once_with(self.session.vim,
                                                        'CreateVM_Task',
                                                        folder,
                                                        config=create_spec,
                                                        pool=resource_pool,
                                                        host=host)
        self.session.wait_for_task.assert_called_once_with(task)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_create_spec_disk_less')
    def test_create_backing_disk_less(self, get_create_spec_disk_less):
        create_spec = mock.sentinel.create_spec
        get_create_spec_disk_less.return_value = create_spec
        task = mock.sentinel.task
        self.session.invoke_api.return_value = task
        task_info = mock.Mock(spec=object)
        task_info.result = mock.sentinel.result
        self.session.wait_for_task.return_value = task_info
        name = 'backing_name'
        folder = mock.sentinel.folder
        resource_pool = mock.sentinel.resource_pool
        host = mock.sentinel.host
        ds_name = mock.sentinel.ds_name
        profile_id = mock.sentinel.profile_id
        extra_config = mock.sentinel.extra_config
        ret = self.vops.create_backing_disk_less(name, folder, resource_pool,
                                                 host, ds_name, profile_id,
                                                 extra_config)

        self.assertEqual(mock.sentinel.result, ret)
        get_create_spec_disk_less.assert_called_once_with(
            name, ds_name, profileId=profile_id, extra_config=extra_config)
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

        delete_disk_attribute = True

        def _create_side_effect(type):
            obj = mock.Mock()
            if type == "ns0:VirtualDiskFlatVer2BackingInfo":
                del obj.eagerlyScrub
            elif (type == "ns0:VirtualMachineRelocateSpec" and
                  delete_disk_attribute):
                del obj.disk
            else:
                pass
            return obj

        factory = self.session.vim.client.factory
        factory.create.side_effect = _create_side_effect

        datastore = mock.sentinel.datastore
        resource_pool = mock.sentinel.resource_pool
        host = mock.sentinel.host
        disk_move_type = mock.sentinel.disk_move_type
        ret = self.vops._get_relocate_spec(datastore, resource_pool, host,
                                           disk_move_type)

        self.assertEqual(datastore, ret.datastore)
        self.assertEqual(resource_pool, ret.pool)
        self.assertEqual(host, ret.host)
        self.assertEqual(disk_move_type, ret.diskMoveType)

        # Test with disk locator.
        delete_disk_attribute = False
        disk_type = 'thin'
        disk_device = mock.Mock()
        ret = self.vops._get_relocate_spec(datastore, resource_pool, host,
                                           disk_move_type, disk_type,
                                           disk_device)

        factory.create.side_effect = None
        self.assertEqual(datastore, ret.datastore)
        self.assertEqual(resource_pool, ret.pool)
        self.assertEqual(host, ret.host)
        self.assertEqual(disk_move_type, ret.diskMoveType)
        self.assertIsInstance(ret.disk, list)
        self.assertEqual(1, len(ret.disk))
        disk_locator = ret.disk[0]
        self.assertEqual(datastore, disk_locator.datastore)
        self.assertEqual(disk_device.key, disk_locator.diskId)
        backing = disk_locator.diskBackingInfo
        self.assertIsInstance(backing.thinProvisioned, bool)
        self.assertTrue(backing.thinProvisioned)
        self.assertEqual('', backing.fileName)
        self.assertEqual('persistent', backing.diskMode)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_disk_device')
    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_relocate_spec')
    def test_relocate_backing(self, get_relocate_spec, get_disk_device):
        disk_device = mock.sentinel.disk_device
        get_disk_device.return_value = disk_device

        spec = mock.sentinel.relocate_spec
        get_relocate_spec.return_value = spec

        task = mock.sentinel.task
        self.session.invoke_api.return_value = task

        backing = mock.sentinel.backing
        datastore = mock.sentinel.datastore
        resource_pool = mock.sentinel.resource_pool
        host = mock.sentinel.host
        disk_type = mock.sentinel.disk_type
        self.vops.relocate_backing(backing, datastore, resource_pool, host,
                                   disk_type)
        # Verify calls
        disk_move_type = 'moveAllDiskBackingsAndAllowSharing'
        get_disk_device.assert_called_once_with(backing)
        get_relocate_spec.assert_called_once_with(datastore, resource_pool,
                                                  host, disk_move_type,
                                                  disk_type, disk_device)
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
        self.assertEqual(snapshot, ret)
        # Test root.childSnapshotList == None
        root = mock.Mock(spec=object)
        root.name = 'root'
        del root.childSnapshotList
        ret = volops._get_snapshot_from_tree(name, root)
        self.assertIsNone(ret)
        # Test root.child == snapshot
        root.childSnapshotList = [node]
        ret = volops._get_snapshot_from_tree(name, root)
        self.assertEqual(snapshot, ret)

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

    def test_snapshot_exists(self):
        backing = mock.sentinel.backing
        invoke_api = self.session.invoke_api
        invoke_api.return_value = None

        self.assertFalse(self.vops.snapshot_exists(backing))
        invoke_api.assert_called_once_with(vim_util,
                                           'get_object_property',
                                           self.session.vim,
                                           backing,
                                           'snapshot')

        snapshot = mock.Mock()
        invoke_api.return_value = snapshot
        snapshot.rootSnapshotList = None
        self.assertFalse(self.vops.snapshot_exists(backing))

        snapshot.rootSnapshotList = [mock.Mock()]
        self.assertTrue(self.vops.snapshot_exists(backing))

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

    def _verify_extra_config(self, option_values, key, value):
        self.assertEqual(1, len(option_values))
        self.assertEqual(key, option_values[0].key)
        self.assertEqual(value, option_values[0].value)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_relocate_spec')
    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_disk_device')
    def test_get_clone_spec(self, get_disk_device, get_relocate_spec):
        factory = self.session.vim.client.factory
        factory.create.side_effect = lambda *args: mock.Mock()
        relocate_spec = mock.sentinel.relocate_spec
        get_relocate_spec.return_value = relocate_spec

        # Test with empty disk type.
        datastore = mock.sentinel.datastore
        disk_move_type = mock.sentinel.disk_move_type
        snapshot = mock.sentinel.snapshot
        disk_type = None
        backing = mock.sentinel.backing
        host = mock.sentinel.host
        rp = mock.sentinel.rp
        key = mock.sentinel.key
        value = mock.sentinel.value
        extra_config = {key: value}
        ret = self.vops._get_clone_spec(datastore, disk_move_type, snapshot,
                                        backing, disk_type, host, rp,
                                        extra_config)

        self.assertEqual(relocate_spec, ret.location)
        self.assertFalse(ret.powerOn)
        self.assertFalse(ret.template)
        self.assertEqual(snapshot, ret.snapshot)
        get_relocate_spec.assert_called_once_with(datastore, rp, host,
                                                  disk_move_type, disk_type,
                                                  None)
        self._verify_extra_config(ret.config.extraConfig, key, value)

        # Test with non-empty disk type.
        disk_device = mock.sentinel.disk_device
        get_disk_device.return_value = disk_device

        disk_type = 'thin'
        ret = self.vops._get_clone_spec(datastore, disk_move_type, snapshot,
                                        backing, disk_type, host, rp,
                                        extra_config)

        factory.create.side_effect = None
        self.assertEqual(relocate_spec, ret.location)
        self.assertFalse(ret.powerOn)
        self.assertFalse(ret.template)
        self.assertEqual(snapshot, ret.snapshot)
        get_disk_device.assert_called_once_with(backing)
        get_relocate_spec.assert_called_with(datastore, rp, host,
                                             disk_move_type, disk_type,
                                             disk_device)
        self._verify_extra_config(ret.config.extraConfig, key, value)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_clone_spec')
    def test_clone_backing(self, get_clone_spec):
        folder = mock.Mock(name='folder', spec=object)
        folder._type = 'Folder'
        task = mock.sentinel.task
        self.session.invoke_api.side_effect = [folder, task, folder, task,
                                               folder, task]
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
        get_clone_spec.assert_called_with(
            datastore, disk_move_type, snapshot, backing, None, host=None,
            resource_pool=None, extra_config=None)
        expected = [mock.call(vim_util, 'get_object_property',
                              self.session.vim, backing, 'parent'),
                    mock.call(self.session.vim, 'CloneVM_Task', backing,
                              folder=folder, name=name, spec=clone_spec)]
        self.assertEqual(expected, self.session.invoke_api.mock_calls)

        # Test linked clone_backing
        clone_type = volumeops.LINKED_CLONE_TYPE
        self.session.invoke_api.reset_mock()
        ret = self.vops.clone_backing(name, backing, snapshot, clone_type,
                                      datastore)
        # verify calls
        self.assertEqual(mock.sentinel.new_backing, ret)
        disk_move_type = 'createNewChildDiskBacking'
        get_clone_spec.assert_called_with(
            datastore, disk_move_type, snapshot, backing, None, host=None,
            resource_pool=None, extra_config=None)
        expected = [mock.call(vim_util, 'get_object_property',
                              self.session.vim, backing, 'parent'),
                    mock.call(self.session.vim, 'CloneVM_Task', backing,
                              folder=folder, name=name, spec=clone_spec)]
        self.assertEqual(expected, self.session.invoke_api.mock_calls)

        # Test with optional params (disk_type, host, resource_pool and
        # extra_config).
        clone_type = None
        disk_type = 'thin'
        host = mock.sentinel.host
        rp = mock.sentinel.rp
        extra_config = mock.sentinel.extra_config
        self.session.invoke_api.reset_mock()
        ret = self.vops.clone_backing(name, backing, snapshot, clone_type,
                                      datastore, disk_type, host, rp,
                                      extra_config)

        self.assertEqual(mock.sentinel.new_backing, ret)
        disk_move_type = 'moveAllDiskBackingsAndDisallowSharing'
        get_clone_spec.assert_called_with(
            datastore, disk_move_type, snapshot, backing, disk_type, host=host,
            resource_pool=rp, extra_config=extra_config)
        expected = [mock.call(vim_util, 'get_object_property',
                              self.session.vim, backing, 'parent'),
                    mock.call(self.session.vim, 'CloneVM_Task', backing,
                              folder=folder, name=name, spec=clone_spec)]
        self.assertEqual(expected, self.session.invoke_api.mock_calls)

        # Clear side effects.
        self.session.invoke_api.side_effect = None

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_create_specs_for_disk_add')
    def test_attach_disk_to_backing(self, create_spec):
        reconfig_spec = mock.Mock()
        self.session.vim.client.factory.create.return_value = reconfig_spec
        disk_add_config_specs = mock.Mock()
        create_spec.return_value = disk_add_config_specs
        task = mock.Mock()
        self.session.invoke_api.return_value = task

        backing = mock.Mock()
        size_in_kb = units.Ki
        disk_type = "thin"
        adapter_type = "ide"
        vmdk_ds_file_path = mock.Mock()
        self.vops.attach_disk_to_backing(backing, size_in_kb, disk_type,
                                         adapter_type, vmdk_ds_file_path)

        self.assertEqual(disk_add_config_specs, reconfig_spec.deviceChange)
        create_spec.assert_called_once_with(size_in_kb, disk_type,
                                            adapter_type,
                                            vmdk_ds_file_path)
        self.session.invoke_api.assert_called_once_with(self.session.vim,
                                                        "ReconfigVM_Task",
                                                        backing,
                                                        spec=reconfig_spec)
        self.session.wait_for_task.assert_called_once_with(task)

    def test_rename_backing(self):
        task = mock.sentinel.task
        self.session.invoke_api.return_value = task

        backing = mock.sentinel.backing
        new_name = mock.sentinel.new_name
        self.vops.rename_backing(backing, new_name)

        self.session.invoke_api.assert_called_once_with(self.session.vim,
                                                        "Rename_Task",
                                                        backing,
                                                        newName=new_name)
        self.session.wait_for_task.assert_called_once_with(task)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_disk_device')
    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_reconfigure_backing')
    def test_update_backing_disk_uuid(self, reconfigure_backing,
                                      get_disk_device):
        disk_spec = mock.Mock()
        reconfig_spec = mock.Mock()
        self.session.vim.client.factory.create.side_effect = [disk_spec,
                                                              reconfig_spec]

        disk_device = mock.Mock()
        get_disk_device.return_value = disk_device

        self.vops.update_backing_disk_uuid(mock.sentinel.backing,
                                           mock.sentinel.disk_uuid)

        get_disk_device.assert_called_once_with(mock.sentinel.backing)
        self.assertEqual(mock.sentinel.disk_uuid, disk_device.backing.uuid)
        self.assertEqual('edit', disk_spec.operation)
        self.assertEqual(disk_device, disk_spec.device)
        self.assertEqual([disk_spec], reconfig_spec.deviceChange)
        reconfigure_backing.assert_called_once_with(mock.sentinel.backing,
                                                    reconfig_spec)
        exp_factory_create_calls = [mock.call('ns0:VirtualDeviceConfigSpec'),
                                    mock.call('ns0:VirtualMachineConfigSpec')]
        self.assertEqual(exp_factory_create_calls,
                         self.session.vim.client.factory.create.call_args_list)

    def test_change_backing_profile(self):
        # Test change to empty profile.
        reconfig_spec = mock.Mock()
        empty_profile_spec = mock.sentinel.empty_profile_spec
        self.session.vim.client.factory.create.side_effect = [
            reconfig_spec, empty_profile_spec]

        task = mock.sentinel.task
        self.session.invoke_api.return_value = task

        backing = mock.sentinel.backing
        unique_profile_id = mock.sentinel.unique_profile_id
        profile_id = mock.Mock(uniqueId=unique_profile_id)
        self.vops.change_backing_profile(backing, profile_id)

        self.assertEqual([empty_profile_spec], reconfig_spec.vmProfile)
        self.session.invoke_api.assert_called_once_with(self.session.vim,
                                                        "ReconfigVM_Task",
                                                        backing,
                                                        spec=reconfig_spec)
        self.session.wait_for_task.assert_called_once_with(task)

        # Test change to non-empty profile.
        profile_spec = mock.Mock()
        self.session.vim.client.factory.create.side_effect = [
            reconfig_spec, profile_spec]

        self.session.invoke_api.reset_mock()
        self.session.wait_for_task.reset_mock()

        self.vops.change_backing_profile(backing, profile_id)

        self.assertEqual([profile_spec], reconfig_spec.vmProfile)
        self.assertEqual(unique_profile_id,
                         reconfig_spec.vmProfile[0].profileId)
        self.session.invoke_api.assert_called_once_with(self.session.vim,
                                                        "ReconfigVM_Task",
                                                        backing,
                                                        spec=reconfig_spec)
        self.session.wait_for_task.assert_called_once_with(task)

        # Clear side effects.
        self.session.vim.client.factory.create.side_effect = None

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

    def test_create_datastore_folder(self):
        file_manager = mock.sentinel.file_manager
        self.session.vim.service_content.fileManager = file_manager
        invoke_api = self.session.invoke_api

        ds_name = "nfs"
        folder_path = "test/"
        datacenter = mock.sentinel.datacenter

        self.vops.create_datastore_folder(ds_name, folder_path, datacenter)
        invoke_api.assert_called_once_with(self.session.vim,
                                           'MakeDirectory',
                                           file_manager,
                                           name="[nfs] test/",
                                           datacenter=datacenter)

    def test_create_datastore_folder_with_existing_folder(self):
        file_manager = mock.sentinel.file_manager
        self.session.vim.service_content.fileManager = file_manager
        invoke_api = self.session.invoke_api
        invoke_api.side_effect = exceptions.FileAlreadyExistsException

        ds_name = "nfs"
        folder_path = "test/"
        datacenter = mock.sentinel.datacenter

        self.vops.create_datastore_folder(ds_name, folder_path, datacenter)
        invoke_api.assert_called_once_with(self.session.vim,
                                           'MakeDirectory',
                                           file_manager,
                                           name="[nfs] test/",
                                           datacenter=datacenter)
        invoke_api.side_effect = None

    def test_create_datastore_folder_with_invoke_api_error(self):
        file_manager = mock.sentinel.file_manager
        self.session.vim.service_content.fileManager = file_manager
        invoke_api = self.session.invoke_api
        invoke_api.side_effect = exceptions.VimFaultException(
            ["FileFault"], "error")

        ds_name = "nfs"
        folder_path = "test/"
        datacenter = mock.sentinel.datacenter

        self.assertRaises(exceptions.VimFaultException,
                          self.vops.create_datastore_folder,
                          ds_name,
                          folder_path,
                          datacenter)
        invoke_api.assert_called_once_with(self.session.vim,
                                           'MakeDirectory',
                                           file_manager,
                                           name="[nfs] test/",
                                           datacenter=datacenter)
        invoke_api.side_effect = None

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

        backing.__class__.__name__ = ' VirtualDiskSparseVer2BackingInfo'
        self.assertRaises(AssertionError, self.vops.get_vmdk_path, backing)

        # Test with no disk device.
        invoke_api.return_value = []
        self.assertRaises(vmdk_exceptions.VirtualDiskNotFoundException,
                          self.vops.get_vmdk_path,
                          backing)

    def test_get_disk_size(self):
        # Test with valid disk device.
        device = mock.Mock()
        device.__class__.__name__ = 'VirtualDisk'
        disk_size_bytes = 1024
        device.capacityInKB = disk_size_bytes / units.Ki
        invoke_api = self.session.invoke_api
        invoke_api.return_value = [device]

        self.assertEqual(disk_size_bytes,
                         self.vops.get_disk_size(mock.sentinel.backing))

        # Test with no disk device.
        invoke_api.return_value = []

        self.assertRaises(vmdk_exceptions.VirtualDiskNotFoundException,
                          self.vops.get_disk_size,
                          mock.sentinel.backing)

    def test_create_virtual_disk(self):
        task = mock.Mock()
        invoke_api = self.session.invoke_api
        invoke_api.return_value = task
        spec = mock.Mock()
        factory = self.session.vim.client.factory
        factory.create.return_value = spec
        disk_mgr = self.session.vim.service_content.virtualDiskManager

        dc_ref = mock.Mock()
        vmdk_ds_file_path = mock.Mock()
        size_in_kb = 1024
        adapter_type = 'ide'
        disk_type = 'thick'
        self.vops.create_virtual_disk(dc_ref, vmdk_ds_file_path, size_in_kb,
                                      adapter_type, disk_type)

        self.assertEqual(volumeops.VirtualDiskAdapterType.IDE,
                         spec.adapterType)
        self.assertEqual(volumeops.VirtualDiskType.PREALLOCATED, spec.diskType)
        self.assertEqual(size_in_kb, spec.capacityKb)
        invoke_api.assert_called_once_with(self.session.vim,
                                           'CreateVirtualDisk_Task',
                                           disk_mgr,
                                           name=vmdk_ds_file_path,
                                           datacenter=dc_ref,
                                           spec=spec)
        self.session.wait_for_task.assert_called_once_with(task)

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                'create_virtual_disk')
    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                'delete_file')
    def test_create_flat_extent_virtual_disk_descriptor(self, delete_file,
                                                        create_virtual_disk):
        dc_ref = mock.Mock()
        path = mock.Mock()
        size_in_kb = 1024
        adapter_type = 'ide'
        disk_type = 'thick'

        self.vops.create_flat_extent_virtual_disk_descriptor(dc_ref,
                                                             path,
                                                             size_in_kb,
                                                             adapter_type,
                                                             disk_type)
        create_virtual_disk.assert_called_once_with(
            dc_ref, path.get_descriptor_ds_file_path(), size_in_kb,
            adapter_type, disk_type)
        delete_file.assert_called_once_with(
            path.get_flat_extent_ds_file_path(), dc_ref)

    def test_copy_vmdk_file(self):
        task = mock.sentinel.task
        invoke_api = self.session.invoke_api
        invoke_api.return_value = task

        disk_mgr = self.session.vim.service_content.virtualDiskManager
        src_dc_ref = mock.sentinel.src_dc_ref
        src_vmdk_file_path = mock.sentinel.src_vmdk_file_path
        dest_dc_ref = mock.sentinel.dest_dc_ref
        dest_vmdk_file_path = mock.sentinel.dest_vmdk_file_path
        self.vops.copy_vmdk_file(src_dc_ref, src_vmdk_file_path,
                                 dest_vmdk_file_path, dest_dc_ref)

        invoke_api.assert_called_once_with(self.session.vim,
                                           'CopyVirtualDisk_Task',
                                           disk_mgr,
                                           sourceName=src_vmdk_file_path,
                                           sourceDatacenter=src_dc_ref,
                                           destName=dest_vmdk_file_path,
                                           destDatacenter=dest_dc_ref,
                                           force=True)
        self.session.wait_for_task.assert_called_once_with(task)

    def test_copy_vmdk_file_with_default_dest_datacenter(self):
        task = mock.sentinel.task
        invoke_api = self.session.invoke_api
        invoke_api.return_value = task

        disk_mgr = self.session.vim.service_content.virtualDiskManager
        src_dc_ref = mock.sentinel.src_dc_ref
        src_vmdk_file_path = mock.sentinel.src_vmdk_file_path
        dest_vmdk_file_path = mock.sentinel.dest_vmdk_file_path
        self.vops.copy_vmdk_file(src_dc_ref, src_vmdk_file_path,
                                 dest_vmdk_file_path)

        invoke_api.assert_called_once_with(self.session.vim,
                                           'CopyVirtualDisk_Task',
                                           disk_mgr,
                                           sourceName=src_vmdk_file_path,
                                           sourceDatacenter=src_dc_ref,
                                           destName=dest_vmdk_file_path,
                                           destDatacenter=src_dc_ref,
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

    @mock.patch('oslo_vmware.pbm.get_profiles_by_ids')
    @mock.patch('oslo_vmware.pbm.get_profiles')
    def test_get_profile(self, get_profiles, get_profiles_by_ids):

        profile_ids = [mock.sentinel.profile_id]
        get_profiles.return_value = profile_ids

        profile_name = mock.sentinel.profile_name
        profile = mock.Mock()
        profile.name = profile_name
        get_profiles_by_ids.return_value = [profile]

        backing = mock.sentinel.backing
        self.assertEqual(profile_name, self.vops.get_profile(backing))
        get_profiles.assert_called_once_with(self.session, backing)
        get_profiles_by_ids.assert_called_once_with(self.session, profile_ids)

    @mock.patch('oslo_vmware.pbm.get_profiles_by_ids')
    @mock.patch('oslo_vmware.pbm.get_profiles')
    def test_get_profile_with_no_profile(self, get_profiles,
                                         get_profiles_by_ids):

        get_profiles.return_value = []

        backing = mock.sentinel.backing
        self.assertIsNone(self.vops.get_profile(backing))

        get_profiles.assert_called_once_with(self.session, backing)
        self.assertFalse(get_profiles_by_ids.called)

    def test_extend_virtual_disk(self):
        """Test volumeops.extend_virtual_disk."""
        task = mock.sentinel.task
        invoke_api = self.session.invoke_api
        invoke_api.return_value = task
        disk_mgr = self.session.vim.service_content.virtualDiskManager
        fake_size = 5
        fake_size_in_kb = fake_size * units.Mi
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

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_all_clusters')
    def test_get_cluster_refs(self, get_all_clusters):
        cls_1 = mock.sentinel.cls_1
        cls_2 = mock.sentinel.cls_2
        clusters = {"cls_1": cls_1, "cls_2": cls_2}
        get_all_clusters.return_value = clusters

        self.assertEqual({"cls_2": cls_2},
                         self.vops.get_cluster_refs(["cls_2"]))

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                '_get_all_clusters')
    def test_get_cluster_refs_with_invalid_cluster(self, get_all_clusters):
        cls_1 = mock.sentinel.cls_1
        cls_2 = mock.sentinel.cls_2
        clusters = {"cls_1": cls_1, "cls_2": cls_2}
        get_all_clusters.return_value = clusters

        self.assertRaises(vmdk_exceptions.ClusterNotFoundException,
                          self.vops.get_cluster_refs,
                          ["cls_1", "cls_3"])

    def test_get_cluster_hosts(self):
        host_1 = mock.sentinel.host_1
        host_2 = mock.sentinel.host_2
        hosts = mock.Mock(ManagedObjectReference=[host_1, host_2])
        self.session.invoke_api.return_value = hosts

        cluster = mock.sentinel.cluster
        ret = self.vops.get_cluster_hosts(cluster)

        self.assertEqual([host_1, host_2], ret)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'get_object_property',
                                                        self.session.vim,
                                                        cluster,
                                                        'host')

    def test_get_cluster_hosts_with_no_host(self):
        self.session.invoke_api.return_value = None

        cluster = mock.sentinel.cluster
        ret = self.vops.get_cluster_hosts(cluster)

        self.assertEqual([], ret)
        self.session.invoke_api.assert_called_once_with(vim_util,
                                                        'get_object_property',
                                                        self.session.vim,
                                                        cluster,
                                                        'host')

    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps.'
                'continue_retrieval', return_value=None)
    def test_get_all_clusters(self, continue_retrieval):
        prop_1 = mock.Mock(val='test_cluster_1')
        cls_1 = mock.Mock(propSet=[prop_1], obj=mock.sentinel.mor_1)
        prop_2 = mock.Mock(val='/test_cluster_2')
        cls_2 = mock.Mock(propSet=[prop_2], obj=mock.sentinel.mor_2)

        retrieve_result = mock.Mock(objects=[cls_1, cls_2])
        self.session.invoke_api.return_value = retrieve_result

        ret = self.vops._get_all_clusters()
        exp = {'test_cluster_1': mock.sentinel.mor_1,
               '/test_cluster_2': mock.sentinel.mor_2}
        self.assertEqual(exp, ret)
        self.session.invoke_api.assert_called_once_with(
            vim_util, 'get_objects', self.session.vim,
            'ClusterComputeResource', self.MAX_OBJECTS)
        continue_retrieval.assert_called_once_with(retrieve_result)


class VirtualDiskPathTest(test.TestCase):
    """Unit tests for VirtualDiskPath."""

    def setUp(self):
        super(VirtualDiskPathTest, self).setUp()
        self._path = volumeops.VirtualDiskPath("nfs", "A/B/", "disk")

    def test_get_datastore_file_path(self):
        self.assertEqual("[nfs] A/B/disk.vmdk",
                         self._path.get_datastore_file_path("nfs",
                                                            "A/B/disk.vmdk"))

    def test_get_descriptor_file_path(self):
        self.assertEqual("A/B/disk.vmdk",
                         self._path.get_descriptor_file_path())

    def test_get_descriptor_ds_file_path(self):
        self.assertEqual("[nfs] A/B/disk.vmdk",
                         self._path.get_descriptor_ds_file_path())


class FlatExtentVirtualDiskPathTest(test.TestCase):
    """Unit tests for FlatExtentVirtualDiskPath."""

    def setUp(self):
        super(FlatExtentVirtualDiskPathTest, self).setUp()
        self._path = volumeops.FlatExtentVirtualDiskPath("nfs", "A/B/", "disk")

    def test_get_flat_extent_file_path(self):
        self.assertEqual("A/B/disk-flat.vmdk",
                         self._path.get_flat_extent_file_path())

    def test_get_flat_extent_ds_file_path(self):
        self.assertEqual("[nfs] A/B/disk-flat.vmdk",
                         self._path.get_flat_extent_ds_file_path())


class VirtualDiskTypeTest(test.TestCase):
    """Unit tests for VirtualDiskType."""

    def test_is_valid(self):
        self.assertTrue(volumeops.VirtualDiskType.is_valid("thick"))
        self.assertTrue(volumeops.VirtualDiskType.is_valid("thin"))
        self.assertTrue(volumeops.VirtualDiskType.is_valid("eagerZeroedThick"))
        self.assertFalse(volumeops.VirtualDiskType.is_valid("preallocated"))

    def test_validate(self):
        volumeops.VirtualDiskType.validate("thick")
        volumeops.VirtualDiskType.validate("thin")
        volumeops.VirtualDiskType.validate("eagerZeroedThick")
        self.assertRaises(vmdk_exceptions.InvalidDiskTypeException,
                          volumeops.VirtualDiskType.validate,
                          "preallocated")

    def test_get_virtual_disk_type(self):
        self.assertEqual("preallocated",
                         volumeops.VirtualDiskType.get_virtual_disk_type(
                             "thick"))
        self.assertEqual("thin",
                         volumeops.VirtualDiskType.get_virtual_disk_type(
                             "thin"))
        self.assertEqual("eagerZeroedThick",
                         volumeops.VirtualDiskType.get_virtual_disk_type(
                             "eagerZeroedThick"))
        self.assertRaises(vmdk_exceptions.InvalidDiskTypeException,
                          volumeops.VirtualDiskType.get_virtual_disk_type,
                          "preallocated")


class VirtualDiskAdapterTypeTest(test.TestCase):
    """Unit tests for VirtualDiskAdapterType."""

    def test_is_valid(self):
        self.assertTrue(volumeops.VirtualDiskAdapterType.is_valid("lsiLogic"))
        self.assertTrue(volumeops.VirtualDiskAdapterType.is_valid("busLogic"))
        self.assertTrue(volumeops.VirtualDiskAdapterType.is_valid(
                        "lsiLogicsas"))
        self.assertTrue(volumeops.VirtualDiskAdapterType.is_valid("ide"))
        self.assertFalse(volumeops.VirtualDiskAdapterType.is_valid("pvscsi"))

    def test_validate(self):
        volumeops.VirtualDiskAdapterType.validate("lsiLogic")
        volumeops.VirtualDiskAdapterType.validate("busLogic")
        volumeops.VirtualDiskAdapterType.validate("lsiLogicsas")
        volumeops.VirtualDiskAdapterType.validate("ide")
        self.assertRaises(vmdk_exceptions.InvalidAdapterTypeException,
                          volumeops.VirtualDiskAdapterType.validate,
                          "pvscsi")

    def test_get_adapter_type(self):
        self.assertEqual("lsiLogic",
                         volumeops.VirtualDiskAdapterType.get_adapter_type(
                             "lsiLogic"))
        self.assertEqual("busLogic",
                         volumeops.VirtualDiskAdapterType.get_adapter_type(
                             "busLogic"))
        self.assertEqual("lsiLogic",
                         volumeops.VirtualDiskAdapterType.get_adapter_type(
                             "lsiLogicsas"))
        self.assertEqual("ide",
                         volumeops.VirtualDiskAdapterType.get_adapter_type(
                             "ide"))
        self.assertRaises(vmdk_exceptions.InvalidAdapterTypeException,
                          volumeops.VirtualDiskAdapterType.get_adapter_type,
                          "pvscsi")


class ControllerTypeTest(test.TestCase):
    """Unit tests for ControllerType."""

    def test_get_controller_type(self):
        self.assertEqual(volumeops.ControllerType.LSI_LOGIC,
                         volumeops.ControllerType.get_controller_type(
                             'lsiLogic'))
        self.assertEqual(volumeops.ControllerType.BUS_LOGIC,
                         volumeops.ControllerType.get_controller_type(
                             'busLogic'))
        self.assertEqual(volumeops.ControllerType.LSI_LOGIC_SAS,
                         volumeops.ControllerType.get_controller_type(
                             'lsiLogicsas'))
        self.assertEqual(volumeops.ControllerType.IDE,
                         volumeops.ControllerType.get_controller_type(
                             'ide'))
        self.assertRaises(vmdk_exceptions.InvalidAdapterTypeException,
                          volumeops.ControllerType.get_controller_type,
                          'invalid_type')

    def test_is_scsi_controller(self):
        self.assertTrue(volumeops.ControllerType.is_scsi_controller(
            volumeops.ControllerType.LSI_LOGIC))
        self.assertTrue(volumeops.ControllerType.is_scsi_controller(
            volumeops.ControllerType.BUS_LOGIC))
        self.assertTrue(volumeops.ControllerType.is_scsi_controller(
            volumeops.ControllerType.LSI_LOGIC_SAS))
        self.assertFalse(volumeops.ControllerType.is_scsi_controller(
            volumeops.ControllerType.IDE))
