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
Test suite for VMware VMDK driver.
"""

import mox

from cinder import exception
from cinder.image import glance
from cinder import test
from cinder import units
from cinder.volume import configuration
from cinder.volume.drivers.vmware import api
from cinder.volume.drivers.vmware import error_util
from cinder.volume.drivers.vmware import vim_util
from cinder.volume.drivers.vmware import vmdk
from cinder.volume.drivers.vmware import vmware_images
from cinder.volume.drivers.vmware import volumeops


class FakeVim(object):
    @property
    def service_content(self):
        return mox.MockAnything()

    @property
    def client(self):
        return mox.MockAnything()

    def Login(self, session_manager, userName, password):
        return mox.MockAnything()


class FakeTaskInfo(object):
    def __init__(self, state, result=None):
        self.state = state
        self.result = result

        class FakeError(object):
            def __init__(self):
                self.localizedMessage = None

        self.error = FakeError()


class FakeMor(object):
    def __init__(self, type, val):
        self._type = type
        self.value = val


class FakeObject(object):
    fields = {}

    def __setitem__(self, key, value):
        self.fields[key] = value

    def __getitem__(self, item):
        return self.fields[item]


class FakeManagedObjectReference(object):
    def __init__(self, lis=[]):
        self.ManagedObjectReference = lis


class FakeDatastoreSummary(object):
    def __init__(self, freeSpace, capacity, datastore=None, name=None):
        self.freeSpace = freeSpace
        self.capacity = capacity
        self.datastore = datastore
        self.name = name


class FakeSnapshotTree(object):
    def __init__(self, tree=None, name=None,
                 snapshot=None, childSnapshotList=None):
        self.rootSnapshotList = tree
        self.name = name
        self.snapshot = snapshot
        self.childSnapshotList = childSnapshotList


class FakeElem(object):
    def __init__(self, prop_set=None):
        self.propSet = prop_set


class FakeProp(object):
    def __init__(self, name=None, val=None):
        self.name = name
        self.val = val


class FakeRetrieveResult(object):
    def __init__(self, objects, token):
        self.objects = objects
        self.token = token


class FakeObj(object):
    def __init__(self, obj=None):
        self.obj = obj


class VMwareEsxVmdkDriverTestCase(test.TestCase):
    """Test class for VMwareEsxVmdkDriver."""

    IP = 'localhost'
    USERNAME = 'username'
    PASSWORD = 'password'
    VOLUME_FOLDER = 'cinder-volumes'
    API_RETRY_COUNT = 3
    TASK_POLL_INTERVAL = 5.0
    IMG_TX_TIMEOUT = 10
    MAX_OBJECTS = 100

    def setUp(self):
        super(VMwareEsxVmdkDriverTestCase, self).setUp()
        self._config = mox.MockObject(configuration.Configuration)
        self._config.append_config_values(mox.IgnoreArg())
        self._config.vmware_host_ip = self.IP
        self._config.vmware_host_username = self.USERNAME
        self._config.vmware_host_password = self.PASSWORD
        self._config.vmware_wsdl_location = None
        self._config.vmware_volume_folder = self.VOLUME_FOLDER
        self._config.vmware_api_retry_count = self.API_RETRY_COUNT
        self._config.vmware_task_poll_interval = self.TASK_POLL_INTERVAL
        self._config.vmware_image_transfer_timeout_secs = self.IMG_TX_TIMEOUT
        self._config.vmware_max_objects_retrieval = self.MAX_OBJECTS
        self._driver = vmdk.VMwareEsxVmdkDriver(configuration=self._config)
        api_retry_count = self._config.vmware_api_retry_count,
        task_poll_interval = self._config.vmware_task_poll_interval,
        self._session = api.VMwareAPISession(self.IP, self.USERNAME,
                                             self.PASSWORD, api_retry_count,
                                             task_poll_interval,
                                             create_session=False)
        self._volumeops = volumeops.VMwareVolumeOps(self._session,
                                                    self.MAX_OBJECTS)
        self._vim = FakeVim()

    def test_retry(self):
        """Test Retry."""

        class TestClass(object):

            def __init__(self):
                self.counter1 = 0

            @api.Retry(max_retry_count=2, inc_sleep_time=0.001,
                       exceptions=(Exception))
            def fail(self):
                self.counter1 += 1
                raise exception.CinderException('Fail')

        test_obj = TestClass()
        self.assertRaises(exception.CinderException, test_obj.fail)
        self.assertEqual(test_obj.counter1, 3)

    def test_create_session(self):
        """Test create_session."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.ReplayAll()
        self._session.create_session()
        m.UnsetStubs()
        m.VerifyAll()

    def test_do_setup(self):
        """Test do_setup."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'session')
        self._driver.session = self._session
        m.ReplayAll()
        self._driver.do_setup(mox.IgnoreArg())
        m.UnsetStubs()
        m.VerifyAll()

    def test_check_for_setup_error(self):
        """Test check_for_setup_error."""
        self._driver.check_for_setup_error()

    def test_get_volume_stats(self):
        """Test get_volume_stats."""
        stats = self._driver.get_volume_stats()
        self.assertEqual(stats['vendor_name'], 'VMware')
        self.assertEqual(stats['driver_version'], '1.0')
        self.assertEqual(stats['storage_protocol'], 'LSI Logic SCSI')
        self.assertEqual(stats['reserved_percentage'], 0)
        self.assertEqual(stats['total_capacity_gb'], 'unknown')
        self.assertEqual(stats['free_capacity_gb'], 'unknown')

    def test_create_volume(self):
        """Test create_volume."""
        self._driver.create_volume(mox.IgnoreArg())

    def test_success_wait_for_task(self):
        """Test successful wait_for_task."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        result = FakeMor('VirtualMachine', 'my_vm')
        success_task_info = FakeTaskInfo('success', result=result)
        m.StubOutWithMock(vim_util, 'get_object_property')
        vim_util.get_object_property(self._session.vim,
                                     mox.IgnoreArg(),
                                     'info').AndReturn(success_task_info)

        m.ReplayAll()
        ret = self._session.wait_for_task(mox.IgnoreArg())
        self.assertEqual(ret.result, result)
        m.UnsetStubs()
        m.VerifyAll()

    def test_failed_wait_for_task(self):
        """Test failed wait_for_task."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        failed_task_info = FakeTaskInfo('failed')
        m.StubOutWithMock(vim_util, 'get_object_property')
        vim_util.get_object_property(self._session.vim,
                                     mox.IgnoreArg(),
                                     'info').AndReturn(failed_task_info)

        m.ReplayAll()
        self.assertRaises(error_util.VimFaultException,
                          self._session.wait_for_task,
                          mox.IgnoreArg())
        m.UnsetStubs()
        m.VerifyAll()

    def test_continue_retrieval(self):
        """Test continue_retrieval."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        self._session.invoke_api(vim_util, 'continue_retrieval',
                                 self._vim, mox.IgnoreArg())

        m.ReplayAll()
        self._volumeops.continue_retrieval(mox.IgnoreArg())
        m.UnsetStubs()
        m.VerifyAll()

    def test_cancel_retrieval(self):
        """Test cancel_retrieval."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        self._session.invoke_api(vim_util, 'cancel_retrieval',
                                 self._vim, mox.IgnoreArg())

        m.ReplayAll()
        self._volumeops.cancel_retrieval(mox.IgnoreArg())
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_backing(self):
        """Test get_backing."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        self._session.invoke_api(vim_util, 'get_objects',
                                 self._vim, 'VirtualMachine',
                                 self.MAX_OBJECTS)

        m.ReplayAll()
        self._volumeops.get_backing(mox.IgnoreArg())
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_backing_multiple_retrieval(self):
        """Test get_backing with multiple retrieval."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        retrieve_result = FakeRetrieveResult([], 'my_token')
        self._session.invoke_api(vim_util, 'get_objects',
                                 self._vim, 'VirtualMachine',
                                 self.MAX_OBJECTS).AndReturn(retrieve_result)
        m.StubOutWithMock(self._volumeops, 'cancel_retrieval')
        self._volumeops.continue_retrieval(retrieve_result)

        m.ReplayAll()
        self._volumeops.get_backing(mox.IgnoreArg())
        m.UnsetStubs()
        m.VerifyAll()

    def test_delete_backing(self):
        """Test delete_backing."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        backing = FakeMor('VirtualMachine', 'my_vm')
        self._session.invoke_api(self._vim, 'Destroy_Task', backing)
        m.StubOutWithMock(self._session, 'wait_for_task')
        self._session.wait_for_task(mox.IgnoreArg())

        m.ReplayAll()
        self._volumeops.delete_backing(backing)
        m.UnsetStubs()
        m.VerifyAll()

    def test_delete_volume_without_backing(self):
        """Test delete_volume without backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        self._volumeops.get_backing('hello_world').AndReturn(None)

        m.ReplayAll()
        volume = FakeObject()
        volume['name'] = 'hello_world'
        self._driver.delete_volume(volume)
        m.UnsetStubs()
        m.VerifyAll()

    def test_delete_volume_with_backing(self):
        """Test delete_volume with backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops

        backing = FakeMor('VirtualMachine', 'my_vm')
        task = FakeMor('Task', 'my_task')

        m.StubOutWithMock(self._volumeops, 'get_backing')
        m.StubOutWithMock(self._volumeops, 'delete_backing')
        self._volumeops.get_backing('hello_world').AndReturn(backing)
        self._volumeops.delete_backing(backing)

        m.ReplayAll()
        volume = FakeObject()
        volume['name'] = 'hello_world'
        self._driver.delete_volume(volume)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_export(self):
        """Test create_export."""
        self._driver.create_export(mox.IgnoreArg(), mox.IgnoreArg())

    def test_ensure_export(self):
        """Test ensure_export."""
        self._driver.ensure_export(mox.IgnoreArg(), mox.IgnoreArg())

    def test_remove_export(self):
        """Test remove_export."""
        self._driver.remove_export(mox.IgnoreArg(), mox.IgnoreArg())

    def test_terminate_connection(self):
        """Test terminate_connection."""
        self._driver.terminate_connection(mox.IgnoreArg(), mox.IgnoreArg(),
                                          force=mox.IgnoreArg())

    def test_get_host(self):
        """Test get_host."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        instance = FakeObject()
        self._session.invoke_api(vim_util, 'get_object_property',
                                 self._vim, instance, 'runtime.host')

        m.ReplayAll()
        self._volumeops.get_host(instance)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_hosts(self):
        """Test get_hosts."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        self._session.invoke_api(vim_util, 'get_objects', self._vim,
                                 'HostSystem', self.MAX_OBJECTS)

        m.ReplayAll()
        self._volumeops.get_hosts()
        m.UnsetStubs()
        m.VerifyAll()

    def test_is_valid_with_accessible_attr(self):
        """Test _is_valid with accessible attribute."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        datastore = FakeMor('Datastore', 'my_ds')
        mntInfo = FakeObject()
        mntInfo.accessMode = "readWrite"
        mntInfo.accessible = True
        host = FakeMor('HostSystem', 'my_host')
        host_mount = FakeObject()
        host_mount.key = host
        host_mount.mountInfo = mntInfo
        host_mounts = FakeObject()
        host_mounts.DatastoreHostMount = [host_mount]
        self._session.invoke_api(vim_util, 'get_object_property',
                                 self._vim, datastore,
                                 'host').AndReturn(host_mounts)

        m.ReplayAll()
        self.assertTrue(self._volumeops._is_valid(datastore, host))
        m.UnsetStubs()
        m.VerifyAll()

    def test_is_valid_without_accessible_attr(self):
        """Test _is_valid without accessible attribute."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        datastore = FakeMor('Datastore', 'my_ds')
        mntInfo = FakeObject()
        mntInfo.accessMode = "readWrite"
        host = FakeMor('HostSystem', 'my_host')
        host_mount = FakeObject()
        host_mount.key = host
        host_mount.mountInfo = mntInfo
        host_mounts = FakeObject()
        host_mounts.DatastoreHostMount = [host_mount]
        self._session.invoke_api(vim_util, 'get_object_property',
                                 self._vim, datastore,
                                 'host').AndReturn(host_mounts)
        m.StubOutWithMock(self._volumeops, 'get_summary')
        summary = FakeObject()
        summary.accessible = True
        self._volumeops.get_summary(datastore).AndReturn(summary)

        m.ReplayAll()
        self.assertTrue(self._volumeops._is_valid(datastore, host))
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_dss_rp(self):
        """Test get_dss_rp."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        host = FakeObject()
        self._session.invoke_api(vim_util, 'get_object_properties',
                                 self._vim, host,
                                 ['datastore', 'parent']).AndReturn([])
        self._session.invoke_api(vim_util, 'get_object_property',
                                 self._vim, mox.IgnoreArg(), 'resourcePool')

        m.ReplayAll()
        self.assertRaises(error_util.VimException, self._volumeops.get_dss_rp,
                          host)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_dss_rp_without_datastores(self):
        """Test get_dss_rp without datastores."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        host = FakeObject()
        props = [FakeElem(prop_set=[FakeProp(name='datastore')])]
        self._session.invoke_api(vim_util, 'get_object_properties',
                                 self._vim, host,
                                 ['datastore', 'parent']).AndReturn(props)
        self._session.invoke_api(vim_util, 'get_object_property',
                                 self._vim, mox.IgnoreArg(), 'resourcePool')

        m.ReplayAll()
        self.assertRaises(error_util.VimException, self._volumeops.get_dss_rp,
                          host)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_parent(self):
        """Test get_parent."""
        # Not recursive
        child = FakeMor('Parent', 'my_parent')
        parent = self._volumeops._get_parent(child, 'Parent')
        self.assertEqual(parent, child)

        # Recursive
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        parent = FakeMor('Parent', 'my_parent1')
        child = FakeMor('Child', 'my_child')
        self._session.invoke_api(vim_util, 'get_object_property', self._vim,
                                 child, 'parent').AndReturn(parent)

        m.ReplayAll()
        ret = self._volumeops._get_parent(child, 'Parent')
        self.assertEqual(ret, parent)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_dc(self):
        """Test get_dc."""
        m = self.mox
        m.StubOutWithMock(self._volumeops, '_get_parent')
        self._volumeops._get_parent(mox.IgnoreArg(), 'Datacenter')

        m.ReplayAll()
        self._volumeops.get_dc(mox.IgnoreArg())
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_vmfolder(self):
        """Test get_vmfolder."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        datacenter = FakeMor('Datacenter', 'my_dc')
        self._session.invoke_api(vim_util, 'get_object_property', self._vim,
                                 datacenter, 'vmFolder')

        m.ReplayAll()
        dc = self._volumeops.get_vmfolder(datacenter)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_backing(self):
        """Test create_backing."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        folder = FakeMor('Folder', 'my_fol')
        resource_pool = FakeMor('ResourcePool', 'my_rs')
        host = FakeMor('HostSystem', 'my_host')
        task = FakeMor('Task', 'my_task')
        self._session.invoke_api(self._vim, 'CreateVM_Task', folder,
                                 config=mox.IgnoreArg(), pool=resource_pool,
                                 host=host).AndReturn(task)
        m.StubOutWithMock(self._session, 'wait_for_task')
        task_info = FakeTaskInfo('success', mox.IgnoreArg())
        self._session.wait_for_task(task).AndReturn(task_info)
        name = 'my_vm'
        size_kb = 1 * units.MiB
        disk_type = 'thick'
        ds_name = 'my_ds'
        m.StubOutWithMock(self._volumeops, '_get_create_spec')
        self._volumeops._get_create_spec(name, size_kb, disk_type, ds_name)

        m.ReplayAll()
        self._volumeops.create_backing(name, size_kb, disk_type, folder,
                                       resource_pool, host, ds_name)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_backing_in_inventory_multi_hosts(self):
        """Test _create_backing_in_inventory scanning multiple hosts."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        host1 = FakeObj(obj=FakeMor('HostSystem', 'my_host1'))
        host2 = FakeObj(obj=FakeMor('HostSystem', 'my_host2'))
        retrieve_result = FakeRetrieveResult([host1, host2], None)
        m.StubOutWithMock(self._volumeops, 'get_hosts')
        self._volumeops.get_hosts().AndReturn(retrieve_result)
        m.StubOutWithMock(self._driver, '_create_backing')
        volume = FakeObject()
        backing = FakeMor('VirtualMachine', 'my_back')
        mux = self._driver._create_backing(volume, host1.obj)
        mux.AndRaise(error_util.VimException('Maintenance mode'))
        mux = self._driver._create_backing(volume, host2.obj)
        mux.AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'cancel_retrieval')
        self._volumeops.cancel_retrieval(retrieve_result)
        m.StubOutWithMock(self._volumeops, 'continue_retrieval')

        m.ReplayAll()
        result = self._driver._create_backing_in_inventory(volume)
        self.assertEqual(result, backing)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_datastore(self):
        """Test get_datastore."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        backing = FakeMor('VirtualMachine', 'my_back')
        datastore = FakeMor('Datastore', 'my_ds')
        datastores = FakeManagedObjectReference([datastore])
        self._session.invoke_api(vim_util, 'get_object_property', self._vim,
                                 backing, 'datastore').AndReturn(datastores)

        m.ReplayAll()
        result = self._volumeops.get_datastore(backing)
        self.assertEqual(result, datastore)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_summary(self):
        """Test get_summary."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        datastore = FakeMor('Datastore', 'my_ds')
        self._session.invoke_api(vim_util, 'get_object_property', self._vim,
                                 datastore, 'summary')

        m.ReplayAll()
        self._volumeops.get_summary(datastore)
        m.UnsetStubs()
        m.VerifyAll()

    def test_init_conn_with_instance_and_backing(self):
        """Test initialize_connection with instance and backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        volume = FakeObject()
        volume['name'] = 'volume_name'
        volume['id'] = 'volume_id'
        volume['size'] = 1
        connector = {'instance': 'my_instance'}
        backing = FakeMor('VirtualMachine', 'my_back')
        self._volumeops.get_backing(volume['name']).AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'get_host')
        host = FakeMor('HostSystem', 'my_host')
        self._volumeops.get_host(mox.IgnoreArg()).AndReturn(host)

        m.ReplayAll()
        conn_info = self._driver.initialize_connection(volume, connector)
        self.assertEqual(conn_info['driver_volume_type'], 'vmdk')
        self.assertEqual(conn_info['data']['volume'], 'my_back')
        self.assertEqual(conn_info['data']['volume_id'], 'volume_id')
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_volume_group_folder(self):
        """Test _get_volume_group_folder."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        datacenter = FakeMor('Datacenter', 'my_dc')
        m.StubOutWithMock(self._volumeops, 'get_vmfolder')
        self._volumeops.get_vmfolder(datacenter)

        m.ReplayAll()
        self._driver._get_volume_group_folder(datacenter)
        m.UnsetStubs()
        m.VerifyAll()

    def test_select_datastore_summary(self):
        """Test _select_datastore_summary."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        datastore1 = FakeMor('Datastore', 'my_ds_1')
        datastore2 = FakeMor('Datastore', 'my_ds_2')
        datastore3 = FakeMor('Datastore', 'my_ds_3')
        datastore4 = FakeMor('Datastore', 'my_ds_4')
        datastores = [datastore1, datastore2, datastore3, datastore4]
        m.StubOutWithMock(self._volumeops, 'get_summary')
        summary1 = FakeDatastoreSummary(10, 10)
        summary2 = FakeDatastoreSummary(25, 50)
        summary3 = FakeDatastoreSummary(50, 50)
        summary4 = FakeDatastoreSummary(100, 100)
        moxd = self._volumeops.get_summary(datastore1)
        moxd.MultipleTimes().AndReturn(summary1)
        moxd = self._volumeops.get_summary(datastore2)
        moxd.MultipleTimes().AndReturn(summary2)
        moxd = self._volumeops.get_summary(datastore3)
        moxd.MultipleTimes().AndReturn(summary3)
        moxd = self._volumeops.get_summary(datastore4)
        moxd.MultipleTimes().AndReturn(summary4)

        m.ReplayAll()
        summary = self._driver._select_datastore_summary(1, datastores)
        self.assertEqual(summary, summary1)
        summary = self._driver._select_datastore_summary(10, datastores)
        self.assertEqual(summary, summary3)
        summary = self._driver._select_datastore_summary(50, datastores)
        self.assertEqual(summary, summary4)
        self.assertRaises(error_util.VimException,
                          self._driver._select_datastore_summary,
                          100, datastores)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_folder_ds_summary(self):
        """Test _get_folder_ds_summary."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        size = 1
        resource_pool = FakeMor('ResourcePool', 'my_rp')
        datacenter = FakeMor('Datacenter', 'my_dc')
        m.StubOutWithMock(self._volumeops, 'get_dc')
        self._volumeops.get_dc(resource_pool).AndReturn(datacenter)
        m.StubOutWithMock(self._driver, '_get_volume_group_folder')
        folder = FakeMor('Folder', 'my_fol')
        self._driver._get_volume_group_folder(datacenter).AndReturn(folder)
        m.StubOutWithMock(self._driver, '_select_datastore_summary')
        size = 1
        datastores = [FakeMor('Datastore', 'my_ds')]
        self._driver._select_datastore_summary(size * units.GiB, datastores)

        m.ReplayAll()
        self._driver._get_folder_ds_summary(size, resource_pool, datastores)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_disk_type(self):
        """Test _get_disk_type."""
        volume = FakeObject()
        volume['volume_type_id'] = None
        self.assertEqual(vmdk.VMwareEsxVmdkDriver._get_disk_type(volume),
                         'thin')

    def test_init_conn_with_instance_no_backing(self):
        """Test initialize_connection with instance and without backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        volume = FakeObject()
        volume['name'] = 'volume_name'
        volume['id'] = 'volume_id'
        volume['size'] = 1
        volume['volume_type_id'] = None
        connector = {'instance': 'my_instance'}
        self._volumeops.get_backing(volume['name'])
        m.StubOutWithMock(self._volumeops, 'get_host')
        host = FakeMor('HostSystem', 'my_host')
        self._volumeops.get_host(mox.IgnoreArg()).AndReturn(host)
        m.StubOutWithMock(self._volumeops, 'get_dss_rp')
        resource_pool = FakeMor('ResourcePool', 'my_rp')
        datastores = [FakeMor('Datastore', 'my_ds')]
        self._volumeops.get_dss_rp(host).AndReturn((datastores, resource_pool))
        m.StubOutWithMock(self._driver, '_get_folder_ds_summary')
        folder = FakeMor('Folder', 'my_fol')
        summary = FakeDatastoreSummary(1, 1)
        self._driver._get_folder_ds_summary(volume['size'], resource_pool,
                                            datastores).AndReturn((folder,
                                                                   summary))
        backing = FakeMor('VirtualMachine', 'my_back')
        m.StubOutWithMock(self._volumeops, 'create_backing')
        self._volumeops.create_backing(volume['name'],
                                       volume['size'] * units.MiB,
                                       mox.IgnoreArg(), folder,
                                       resource_pool, host,
                                       mox.IgnoreArg()).AndReturn(backing)

        m.ReplayAll()
        conn_info = self._driver.initialize_connection(volume, connector)
        self.assertEqual(conn_info['driver_volume_type'], 'vmdk')
        self.assertEqual(conn_info['data']['volume'], 'my_back')
        self.assertEqual(conn_info['data']['volume_id'], 'volume_id')
        m.UnsetStubs()
        m.VerifyAll()

    def test_init_conn_without_instance(self):
        """Test initialize_connection without instance and a backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        backing = FakeMor('VirtualMachine', 'my_back')
        volume = FakeObject()
        volume['name'] = 'volume_name'
        volume['id'] = 'volume_id'
        connector = {}
        self._volumeops.get_backing(volume['name']).AndReturn(backing)

        m.ReplayAll()
        conn_info = self._driver.initialize_connection(volume, connector)
        self.assertEqual(conn_info['driver_volume_type'], 'vmdk')
        self.assertEqual(conn_info['data']['volume'], 'my_back')
        self.assertEqual(conn_info['data']['volume_id'], 'volume_id')
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_snapshot_operation(self):
        """Test volumeops.create_snapshot."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        name = 'snapshot_name'
        description = 'snapshot_desc'
        backing = FakeMor('VirtualMachine', 'my_back')
        task = FakeMor('Task', 'my_task')
        self._session.invoke_api(self._vim, 'CreateSnapshot_Task', backing,
                                 name=name, description=description,
                                 memory=False, quiesce=False).AndReturn(task)
        result = FakeMor('VirtualMachineSnapshot', 'my_snap')
        success_task_info = FakeTaskInfo('success', result=result)
        m.StubOutWithMock(self._session, 'wait_for_task')
        self._session.wait_for_task(task).AndReturn(success_task_info)

        m.ReplayAll()
        self._volumeops.create_snapshot(backing, name, description)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_snapshot_without_backing(self):
        """Test vmdk.create_snapshot without backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        snapshot = FakeObject()
        snapshot['volume_name'] = 'volume_name'
        self._volumeops.get_backing(snapshot['volume_name'])

        m.ReplayAll()
        self._driver.create_snapshot(snapshot)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_snapshot_with_backing(self):
        """Test vmdk.create_snapshot with backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        snapshot = FakeObject()
        snapshot['volume_name'] = 'volume_name'
        snapshot['name'] = 'snapshot_name'
        snapshot['display_description'] = 'snapshot_desc'
        backing = FakeMor('VirtualMachine', 'my_back')
        self._volumeops.get_backing(snapshot['volume_name']).AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'create_snapshot')
        self._volumeops.create_snapshot(backing, snapshot['name'],
                                        snapshot['display_description'])

        m.ReplayAll()
        self._driver.create_snapshot(snapshot)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_snapshot_from_tree(self):
        """Test _get_snapshot_from_tree."""
        volops = volumeops.VMwareVolumeOps
        ret = volops._get_snapshot_from_tree(mox.IgnoreArg(), None)
        self.assertEqual(ret, None)
        name = 'snapshot_name'
        snapshot = FakeMor('VirtualMachineSnapshot', 'my_snap')
        root = FakeSnapshotTree(name='snapshot_name', snapshot=snapshot)
        ret = volops._get_snapshot_from_tree(name, root)
        self.assertEqual(ret, snapshot)
        snapshot1 = FakeMor('VirtualMachineSnapshot', 'my_snap_1')
        root = FakeSnapshotTree(name='snapshot_name_1', snapshot=snapshot1,
                                childSnapshotList=[root])
        ret = volops._get_snapshot_from_tree(name, root)
        self.assertEqual(ret, snapshot)

    def test_get_snapshot(self):
        """Test get_snapshot."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        name = 'snapshot_name'
        backing = FakeMor('VirtualMachine', 'my_back')
        root = FakeSnapshotTree()
        tree = FakeSnapshotTree(tree=[root])
        self._session.invoke_api(vim_util, 'get_object_property',
                                 self._session.vim, backing,
                                 'snapshot').AndReturn(tree)
        volops = volumeops.VMwareVolumeOps
        m.StubOutWithMock(volops, '_get_snapshot_from_tree')
        volops._get_snapshot_from_tree(name, root)

        m.ReplayAll()
        self._volumeops.get_snapshot(backing, name)
        m.UnsetStubs()
        m.VerifyAll()

    def test_delete_snapshot_not_present(self):
        """Test volumeops.delete_snapshot, when not present."""
        m = self.mox
        m.StubOutWithMock(self._volumeops, 'get_snapshot')
        name = 'snapshot_name'
        backing = FakeMor('VirtualMachine', 'my_back')
        self._volumeops.get_snapshot(backing, name)

        m.ReplayAll()
        self._volumeops.delete_snapshot(backing, name)
        m.UnsetStubs()
        m.VerifyAll()

    def test_delete_snapshot_when_present(self):
        """Test volumeops.delete_snapshot, when it is present."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        m.StubOutWithMock(self._volumeops, 'get_snapshot')
        name = 'snapshot_name'
        backing = FakeMor('VirtualMachine', 'my_back')
        snapshot = FakeMor('VirtualMachineSnapshot', 'my_snap')
        self._volumeops.get_snapshot(backing, name).AndReturn(snapshot)
        task = FakeMor('Task', 'my_task')
        self._session.invoke_api(self._session.vim,
                                 'RemoveSnapshot_Task', snapshot,
                                 removeChildren=False).AndReturn(task)
        m.StubOutWithMock(self._session, 'wait_for_task')
        self._session.wait_for_task(task)

        m.ReplayAll()
        self._volumeops.delete_snapshot(backing, name)
        m.UnsetStubs()
        m.VerifyAll()

    def test_delete_snapshot_without_backing(self):
        """Test delete_snapshot without backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        snapshot = FakeObject()
        snapshot['volume_name'] = 'volume_name'
        self._volumeops.get_backing(snapshot['volume_name'])

        m.ReplayAll()
        self._driver.delete_snapshot(snapshot)
        m.UnsetStubs()
        m.VerifyAll()

    def test_delete_snapshot_with_backing(self):
        """Test delete_snapshot with backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        snapshot = FakeObject()
        snapshot['name'] = 'snapshot_name'
        snapshot['volume_name'] = 'volume_name'
        backing = FakeMor('VirtualMachine', 'my_back')
        self._volumeops.get_backing(snapshot['volume_name']).AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'delete_snapshot')
        self._volumeops.delete_snapshot(backing,
                                        snapshot['name'])

        m.ReplayAll()
        self._driver.delete_snapshot(snapshot)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_cloned_volume_without_backing(self):
        """Test create_cloned_volume without a backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        volume = FakeObject()
        volume['name'] = 'volume_name'
        src_vref = FakeObject()
        src_vref['name'] = 'src_volume_name'
        self._volumeops.get_backing(src_vref['name'])

        m.ReplayAll()
        self._driver.create_cloned_volume(volume, src_vref)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_path_name(self):
        """Test get_path_name."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        backing = FakeMor('VirtualMachine', 'my_back')

        class FakePath(object):
            def __init__(self, path=None):
                self.vmPathName = path

        path = FakePath()
        self._session.invoke_api(vim_util, 'get_object_property', self._vim,
                                 backing, 'config.files').AndReturn(path)

        m.ReplayAll()
        self._volumeops.get_path_name(backing)
        m.UnsetStubs()
        m.VerifyAll()

    def test_delete_file(self):
        """Test _delete_file."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        src_path = 'src_path'
        task = FakeMor('Task', 'my_task')
        self._session.invoke_api(self._vim, 'DeleteDatastoreFile_Task',
                                 mox.IgnoreArg(), name=src_path,
                                 datacenter=mox.IgnoreArg()).AndReturn(task)
        m.StubOutWithMock(self._session, 'wait_for_task')
        self._session.wait_for_task(task)

        m.ReplayAll()
        self._volumeops.delete_file(src_path)
        m.UnsetStubs()
        m.VerifyAll()

    def test_clone_backing_by_copying(self):
        """Test _clone_backing_by_copying."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        volume = FakeObject()
        src_vmdk_path = "[datastore] src_vm/src_vm.vmdk"
        new_vmdk_path = "[datastore] dest_vm/dest_vm.vmdk"
        backing = FakeMor('VirtualMachine', 'my_back')
        m.StubOutWithMock(self._driver, '_create_backing_in_inventory')
        mux = self._driver._create_backing_in_inventory(volume)
        mux.AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'get_vmdk_path')
        self._volumeops.get_vmdk_path(backing).AndReturn(new_vmdk_path)
        m.StubOutWithMock(self._volumeops, 'get_dc')
        datacenter = FakeMor('Datacenter', 'my_dc')
        self._volumeops.get_dc(backing).AndReturn(datacenter)
        m.StubOutWithMock(self._volumeops, 'delete_vmdk_file')
        self._volumeops.delete_vmdk_file(new_vmdk_path, datacenter)
        m.StubOutWithMock(self._volumeops, 'copy_vmdk_file')
        self._volumeops.copy_vmdk_file(datacenter, src_vmdk_path,
                                       new_vmdk_path)

        m.ReplayAll()
        self._driver._clone_backing_by_copying(volume, src_vmdk_path)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_cloned_volume_with_backing(self):
        """Test create_cloned_volume with a backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        volume = FakeObject()
        src_vref = FakeObject()
        src_vref['name'] = 'src_snapshot_name'
        backing = FakeMor('VirtualMachine', 'my_vm')
        self._volumeops.get_backing(src_vref['name']).AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'get_vmdk_path')
        src_vmdk_path = "[datastore] src_vm/src_vm.vmdk"
        self._volumeops.get_vmdk_path(backing).AndReturn(src_vmdk_path)
        m.StubOutWithMock(self._driver, '_clone_backing_by_copying')
        self._driver._clone_backing_by_copying(volume, src_vmdk_path)

        m.ReplayAll()
        self._driver.create_cloned_volume(volume, src_vref)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_volume_from_snapshot_without_backing(self):
        """Test create_volume_from_snapshot without a backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        volume = FakeObject()
        volume['name'] = 'volume_name'
        snapshot = FakeObject()
        snapshot['volume_name'] = 'volume_name'
        self._volumeops.get_backing(snapshot['volume_name'])

        m.ReplayAll()
        self._driver.create_volume_from_snapshot(volume, snapshot)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_volume_from_snap_without_backing_snap(self):
        """Test create_volume_from_snapshot without a backing snapshot."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        backing = FakeMor('VirtualMachine', 'my_vm')
        m.StubOutWithMock(self._volumeops, 'get_backing')
        volume = FakeObject()
        volume['name'] = 'volume_name'
        snapshot = FakeObject()
        snapshot['volume_name'] = 'volume_name'
        self._volumeops.get_backing(snapshot['volume_name']).AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'get_snapshot')
        snapshot['name'] = 'snapshot_name'
        self._volumeops.get_snapshot(backing, snapshot['name'])

        m.ReplayAll()
        self._driver.create_volume_from_snapshot(volume, snapshot)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_volume_from_snapshot(self):
        """Test create_volume_from_snapshot."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        backing = FakeMor('VirtualMachine', 'my_vm')
        m.StubOutWithMock(self._volumeops, 'get_backing')
        volume = FakeObject()
        snapshot = FakeObject()
        snapshot['volume_name'] = 'volume_name'
        self._volumeops.get_backing(snapshot['volume_name']).AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'get_snapshot')
        snapshot['name'] = 'snapshot_name'
        snapshot_mor = FakeMor('VirtualMachineSnapshot', 'my_snap')
        self._volumeops.get_snapshot(backing,
                                     snapshot['name']).AndReturn(snapshot_mor)
        m.StubOutWithMock(self._volumeops, 'get_vmdk_path')
        src_vmdk_path = "[datastore] src_vm/src_vm-001.vmdk"
        self._volumeops.get_vmdk_path(snapshot_mor).AndReturn(src_vmdk_path)
        m.StubOutWithMock(self._driver, '_clone_backing_by_copying')
        self._driver._clone_backing_by_copying(volume, src_vmdk_path)

        m.ReplayAll()
        self._driver.create_volume_from_snapshot(volume, snapshot)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_entity_name(self):
        """Test volumeops get_entity_name."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        entity = FakeMor('VirtualMachine', 'virt')
        self._session.invoke_api(vim_util, 'get_object_property',
                                 self._vim, entity, 'name')

        m.ReplayAll()
        self._volumeops.get_entity_name(entity)
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_vmdk_path(self):
        """Test volumeops get_vmdk_path."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        backing = FakeMor('VirtualMachine', 'my_back')
        vmdk_path = '[datastore 1] folders/myvols/volume-123.vmdk'

        class VirtualDisk:
            pass
        virtualDisk = VirtualDisk()

        class VirtualDiskFlatVer2BackingInfo:
            pass
        backingInfo = VirtualDiskFlatVer2BackingInfo()
        backingInfo.fileName = vmdk_path
        virtualDisk.backing = backingInfo
        devices = [FakeObject(), virtualDisk, FakeObject()]

        moxed = self._session.invoke_api(vim_util, 'get_object_property',
                                         self._vim, backing,
                                         'config.hardware.device')
        moxed.AndReturn(devices)

        m.ReplayAll()
        actual_vmdk_path = self._volumeops.get_vmdk_path(backing)
        self.assertEqual(backingInfo.__class__.__name__,
                         'VirtualDiskFlatVer2BackingInfo')
        self.assertEqual(virtualDisk.__class__.__name__, 'VirtualDisk')
        self.assertEqual(actual_vmdk_path, vmdk_path)
        m.UnsetStubs()
        m.VerifyAll()

    def test_copy_vmdk_file(self):
        """Test copy_vmdk_file."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        dc_ref = FakeMor('Datacenter', 'dc1')
        src_path = 'src_path'
        dest_path = 'dest_path'
        task = FakeMor('Task', 'my_task')
        self._session.invoke_api(self._vim, 'CopyVirtualDisk_Task',
                                 mox.IgnoreArg(), sourceName=src_path,
                                 sourceDatacenter=dc_ref, destName=dest_path,
                                 destDatacenter=dc_ref,
                                 force=True).AndReturn(task)
        m.StubOutWithMock(self._session, 'wait_for_task')
        self._session.wait_for_task(task)

        m.ReplayAll()
        self._volumeops.copy_vmdk_file(dc_ref, src_path, dest_path)
        m.UnsetStubs()
        m.VerifyAll()

    def test_delete_vmdk_file(self):
        """Test delete_vmdk_file."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        dc_ref = FakeMor('Datacenter', 'dc1')
        vmdk_path = 'vmdk_path'
        task = FakeMor('Task', 'my_task')
        self._session.invoke_api(self._vim, 'DeleteVirtualDisk_Task',
                                 mox.IgnoreArg(), name=vmdk_path,
                                 datacenter=dc_ref).AndReturn(task)
        m.StubOutWithMock(self._session, 'wait_for_task')
        self._session.wait_for_task(task)

        m.ReplayAll()
        self._volumeops.delete_vmdk_file(vmdk_path, dc_ref)
        m.UnsetStubs()
        m.VerifyAll()

    def test_split_datastore_path(self):
        """Test volumeops split_datastore_path."""
        test1 = '[datastore1] myfolder/mysubfolder/myvm.vmx'
        (datastore,
         folder,
         file_name) = volumeops.split_datastore_path(test1)
        self.assertEqual(datastore, 'datastore1')
        self.assertEqual(folder, 'myfolder/mysubfolder/')
        self.assertEqual(file_name, 'myvm.vmx')
        test2 = '[datastore2 ]   myfolder/myvm.vmdk'
        (datastore,
         folder,
         file_name) = volumeops.split_datastore_path(test2)
        self.assertEqual(datastore, 'datastore2')
        self.assertEqual(folder, 'myfolder/')
        self.assertEqual(file_name, 'myvm.vmdk')
        test3 = 'myfolder/myvm.vmdk'
        self.assertRaises(IndexError, volumeops.split_datastore_path, test3)

    def test_copy_image_to_volume_non_vmdk(self):
        """Test copy_image_to_volume for a non-vmdk disk format."""
        m = self.mox
        image_id = 'image-123456789'
        image_meta = FakeObject()
        image_meta['disk_format'] = 'novmdk'
        image_service = m.CreateMock(glance.GlanceImageService)
        image_service.show(mox.IgnoreArg(), image_id).AndReturn(image_meta)

        m.ReplayAll()
        self.assertRaises(exception.ImageUnacceptable,
                          self._driver.copy_image_to_volume,
                          mox.IgnoreArg(), mox.IgnoreArg(),
                          image_service, image_id)
        m.UnsetStubs()
        m.VerifyAll()

    def test_copy_image_to_volume_vmdk(self):
        """Test copy_image_to_volume with an acceptable vmdk disk format."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'session')
        self._driver.session = self._session
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops

        image_id = 'image-id'
        image_meta = FakeObject()
        image_meta['disk_format'] = 'vmdk'
        image_meta['size'] = 1024 * 1024
        image_service = m.CreateMock(glance.GlanceImageService)
        image_service.show(mox.IgnoreArg(), image_id).AndReturn(image_meta)
        volume = FakeObject()
        vol_name = 'volume name'
        volume['name'] = vol_name
        backing = FakeMor('VirtualMachine', 'my_vm')
        m.StubOutWithMock(self._driver, '_create_backing_in_inventory')
        self._driver._create_backing_in_inventory(volume).AndReturn(backing)
        datastore_name = 'datastore1'
        flat_vmdk_path = 'myvolumes/myvm-flat.vmdk'
        m.StubOutWithMock(self._driver, '_get_ds_name_flat_vmdk_path')
        moxed = self._driver._get_ds_name_flat_vmdk_path(mox.IgnoreArg(),
                                                         vol_name)
        moxed.AndReturn((datastore_name, flat_vmdk_path))
        host = FakeMor('Host', 'my_host')
        m.StubOutWithMock(self._volumeops, 'get_host')
        self._volumeops.get_host(backing).AndReturn(host)
        datacenter = FakeMor('Datacenter', 'my_datacenter')
        m.StubOutWithMock(self._volumeops, 'get_dc')
        self._volumeops.get_dc(host).AndReturn(datacenter)
        datacenter_name = 'my-datacenter'
        m.StubOutWithMock(self._volumeops, 'get_entity_name')
        self._volumeops.get_entity_name(datacenter).AndReturn(datacenter_name)
        flat_path = '[%s] %s' % (datastore_name, flat_vmdk_path)
        m.StubOutWithMock(self._volumeops, 'delete_file')
        self._volumeops.delete_file(flat_path, datacenter)
        client = FakeObject()
        client.options = FakeObject()
        client.options.transport = FakeObject()
        cookies = FakeObject()
        client.options.transport.cookiejar = cookies
        m.StubOutWithMock(self._vim.__class__, 'client')
        self._vim.client = client
        m.StubOutWithMock(vmware_images, 'fetch_image')
        timeout = self._config.vmware_image_transfer_timeout_secs
        vmware_images.fetch_image(mox.IgnoreArg(), timeout, image_service,
                                  image_id, host=self.IP,
                                  data_center_name=datacenter_name,
                                  datastore_name=datastore_name,
                                  cookies=cookies,
                                  file_path=flat_vmdk_path)

        m.ReplayAll()
        self._driver.copy_image_to_volume(mox.IgnoreArg(), volume,
                                          image_service, image_id)
        m.UnsetStubs()
        m.VerifyAll()

    def test_copy_volume_to_image_non_vmdk(self):
        """Test copy_volume_to_image for a non-vmdk disk format."""
        m = self.mox
        image_meta = FakeObject()
        image_meta['disk_format'] = 'novmdk'
        volume = FakeObject()
        volume['name'] = 'vol-name'

        m.ReplayAll()
        self.assertRaises(exception.ImageUnacceptable,
                          self._driver.copy_volume_to_image,
                          mox.IgnoreArg(), volume,
                          mox.IgnoreArg(), image_meta)
        m.UnsetStubs()
        m.VerifyAll()

    def test_copy_volume_to_image_vmdk(self):
        """Test copy_volume_to_image for a valid vmdk disk format."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'session')
        self._driver.session = self._session
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops

        image_id = 'image-id-1'
        image_meta = FakeObject()
        image_meta['disk_format'] = 'vmdk'
        image_meta['id'] = image_id
        image_meta['name'] = image_id
        image_service = FakeObject()
        vol_name = 'volume-123456789'
        project_id = 'project-owner-id-123'
        volume = FakeObject()
        volume['name'] = vol_name
        volume['project_id'] = project_id
        # volumeops.get_backing
        backing = FakeMor("VirtualMachine", "my_vm")
        m.StubOutWithMock(self._volumeops, 'get_backing')
        self._volumeops.get_backing(vol_name).AndReturn(backing)
        # volumeops.get_vmdk_path
        datastore_name = 'datastore1'
        file_path = 'my_folder/my_nested_folder/my_vm.vmdk'
        vmdk_file_path = '[%s] %s' % (datastore_name, file_path)
        m.StubOutWithMock(self._volumeops, 'get_vmdk_path')
        self._volumeops.get_vmdk_path(backing).AndReturn(vmdk_file_path)
        # volumeops.create_snapshot
        snapshot_name = 'snapshot-%s' % image_id
        m.StubOutWithMock(self._volumeops, 'create_snapshot')
        self._volumeops.create_snapshot(backing, snapshot_name, None, True)
        tmp_vmdk = '[datastore1] %s.vmdk' % image_id
        # volumeops.get_host
        host = FakeMor('Host', 'my_host')
        m.StubOutWithMock(self._volumeops, 'get_host')
        self._volumeops.get_host(backing).AndReturn(host)
        # volumeops.get_dc
        datacenter_name = 'my_datacenter'
        datacenter = FakeMor('Datacenter', datacenter_name)
        m.StubOutWithMock(self._volumeops, 'get_dc')
        self._volumeops.get_dc(host).AndReturn(datacenter)
        # volumeops.copy_vmdk_file
        m.StubOutWithMock(self._volumeops, 'copy_vmdk_file')
        self._volumeops.copy_vmdk_file(datacenter, vmdk_file_path, tmp_vmdk)
        # host_ip
        host_ip = self.IP
        # volumeops.get_entity_name
        m.StubOutWithMock(self._volumeops, 'get_entity_name')
        self._volumeops.get_entity_name(datacenter).AndReturn(datacenter_name)
        # cookiejar
        client = FakeObject()
        client.options = FakeObject()
        client.options.transport = FakeObject()
        cookies = FakeObject()
        client.options.transport.cookiejar = cookies
        m.StubOutWithMock(self._vim.__class__, 'client')
        self._vim.client = client
        # flat_vmdk
        flat_vmdk_file = '%s-flat.vmdk' % image_id
        # vmware_images.upload_image
        timeout = self._config.vmware_image_transfer_timeout_secs
        m.StubOutWithMock(vmware_images, 'upload_image')
        vmware_images.upload_image(mox.IgnoreArg(), timeout, image_service,
                                   image_id, project_id, host=host_ip,
                                   data_center_name=datacenter_name,
                                   datastore_name=datastore_name,
                                   cookies=cookies,
                                   file_path=flat_vmdk_file,
                                   snapshot_name=image_meta['name'],
                                   image_version=1)
        # volumeops.delete_vmdk_file
        m.StubOutWithMock(self._volumeops, 'delete_vmdk_file')
        self._volumeops.delete_vmdk_file(tmp_vmdk, datacenter)

        m.ReplayAll()
        self._driver.copy_volume_to_image(mox.IgnoreArg(), volume,
                                          image_service, image_meta)
        m.UnsetStubs()
        m.VerifyAll()


class VMwareVcVmdkDriverTestCase(VMwareEsxVmdkDriverTestCase):
    """Test class for VMwareVcVmdkDriver."""

    def setUp(self):
        super(VMwareVcVmdkDriverTestCase, self).setUp()
        self._driver = vmdk.VMwareVcVmdkDriver(configuration=self._config)

    def test_create_folder_not_present(self):
        """Test create_folder when not present."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        parent_folder = FakeMor('Folder', 'my_par_fol')
        child_entities = FakeManagedObjectReference()
        self._session.invoke_api(vim_util, 'get_object_property',
                                 self._vim, parent_folder,
                                 'childEntity').AndReturn(child_entities)
        self._session.invoke_api(self._vim, 'CreateFolder', parent_folder,
                                 name='child_folder_name')

        m.ReplayAll()
        dc = self._volumeops.create_folder(parent_folder, 'child_folder_name')
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_folder_already_present(self):
        """Test create_folder when already present."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        parent_folder = FakeMor('Folder', 'my_par_fol')
        child_folder = FakeMor('Folder', 'my_child_fol')
        child_entities = FakeManagedObjectReference([child_folder])
        self._session.invoke_api(vim_util, 'get_object_property',
                                 self._vim, parent_folder,
                                 'childEntity').AndReturn(child_entities)
        self._session.invoke_api(vim_util, 'get_object_property',
                                 self._vim, child_folder,
                                 'name').AndReturn('child_folder_name')

        m.ReplayAll()
        fol = self._volumeops.create_folder(parent_folder, 'child_folder_name')
        self.assertEqual(fol, child_folder)
        m.UnsetStubs()
        m.VerifyAll()

    def test_relocate_backing(self):
        """Test relocate_backing."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._volumeops, '_get_relocate_spec')
        datastore = FakeMor('Datastore', 'my_ds')
        resource_pool = FakeMor('ResourcePool', 'my_rp')
        host = FakeMor('HostSystem', 'my_host')
        disk_move_type = 'moveAllDiskBackingsAndAllowSharing'
        self._volumeops._get_relocate_spec(datastore, resource_pool, host,
                                           disk_move_type)
        m.StubOutWithMock(self._session, 'invoke_api')
        backing = FakeMor('VirtualMachine', 'my_back')
        task = FakeMor('Task', 'my_task')
        self._session.invoke_api(self._vim, 'RelocateVM_Task',
                                 backing, spec=mox.IgnoreArg()).AndReturn(task)
        m.StubOutWithMock(self._session, 'wait_for_task')
        self._session.wait_for_task(task)

        m.ReplayAll()
        self._volumeops.relocate_backing(backing, datastore,
                                         resource_pool, host)
        m.UnsetStubs()
        m.VerifyAll()

    def test_move_backing_to_folder(self):
        """Test move_backing_to_folder."""
        m = self.mox
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        backing = FakeMor('VirtualMachine', 'my_back')
        folder = FakeMor('Folder', 'my_fol')
        task = FakeMor('Task', 'my_task')
        self._session.invoke_api(self._vim, 'MoveIntoFolder_Task',
                                 folder, list=[backing]).AndReturn(task)
        m.StubOutWithMock(self._session, 'wait_for_task')
        self._session.wait_for_task(task)

        m.ReplayAll()
        self._volumeops.move_backing_to_folder(backing, folder)
        m.UnsetStubs()
        m.VerifyAll()

    def test_init_conn_with_instance_and_backing(self):
        """Test initialize_connection with instance and backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        volume = FakeObject()
        volume['name'] = 'volume_name'
        volume['id'] = 'volume_id'
        volume['size'] = 1
        connector = {'instance': 'my_instance'}
        backing = FakeMor('VirtualMachine', 'my_back')
        self._volumeops.get_backing(volume['name']).AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'get_host')
        host = FakeMor('HostSystem', 'my_host')
        self._volumeops.get_host(mox.IgnoreArg()).AndReturn(host)
        datastore = FakeMor('Datastore', 'my_ds')
        resource_pool = FakeMor('ResourcePool', 'my_rp')
        m.StubOutWithMock(self._volumeops, 'get_dss_rp')
        self._volumeops.get_dss_rp(host).AndReturn(([datastore],
                                                    resource_pool))
        m.StubOutWithMock(self._volumeops, 'get_datastore')
        self._volumeops.get_datastore(backing).AndReturn(datastore)

        m.ReplayAll()
        conn_info = self._driver.initialize_connection(volume, connector)
        self.assertEqual(conn_info['driver_volume_type'], 'vmdk')
        self.assertEqual(conn_info['data']['volume'], 'my_back')
        self.assertEqual(conn_info['data']['volume_id'], 'volume_id')
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_volume_group_folder(self):
        """Test _get_volume_group_folder."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        datacenter = FakeMor('Datacenter', 'my_dc')
        m.StubOutWithMock(self._volumeops, 'get_vmfolder')
        self._volumeops.get_vmfolder(datacenter)
        m.StubOutWithMock(self._volumeops, 'create_folder')
        self._volumeops.create_folder(mox.IgnoreArg(),
                                      self._config.vmware_volume_folder)

        m.ReplayAll()
        self._driver._get_volume_group_folder(datacenter)
        m.UnsetStubs()
        m.VerifyAll()

    def test_init_conn_with_instance_and_backing_and_relocation(self):
        """Test initialize_connection with backing being relocated."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        volume = FakeObject()
        volume['name'] = 'volume_name'
        volume['id'] = 'volume_id'
        volume['size'] = 1
        connector = {'instance': 'my_instance'}
        backing = FakeMor('VirtualMachine', 'my_back')
        self._volumeops.get_backing(volume['name']).AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'get_host')
        host = FakeMor('HostSystem', 'my_host')
        self._volumeops.get_host(mox.IgnoreArg()).AndReturn(host)
        datastore1 = FakeMor('Datastore', 'my_ds_1')
        datastore2 = FakeMor('Datastore', 'my_ds_2')
        resource_pool = FakeMor('ResourcePool', 'my_rp')
        m.StubOutWithMock(self._volumeops, 'get_dss_rp')
        self._volumeops.get_dss_rp(host).AndReturn(([datastore1],
                                                    resource_pool))
        m.StubOutWithMock(self._volumeops, 'get_datastore')
        self._volumeops.get_datastore(backing).AndReturn(datastore2)
        m.StubOutWithMock(self._driver, '_get_folder_ds_summary')
        folder = FakeMor('Folder', 'my_fol')
        summary = FakeDatastoreSummary(1, 1, datastore1)
        size = 1
        self._driver._get_folder_ds_summary(size, resource_pool,
                                            [datastore1]).AndReturn((folder,
                                                                     summary))
        m.StubOutWithMock(self._volumeops, 'relocate_backing')
        self._volumeops.relocate_backing(backing, datastore1,
                                         resource_pool, host)
        m.StubOutWithMock(self._volumeops, 'move_backing_to_folder')
        self._volumeops.move_backing_to_folder(backing, folder)

        m.ReplayAll()
        conn_info = self._driver.initialize_connection(volume, connector)
        self.assertEqual(conn_info['driver_volume_type'], 'vmdk')
        self.assertEqual(conn_info['data']['volume'], 'my_back')
        self.assertEqual(conn_info['data']['volume_id'], 'volume_id')
        m.UnsetStubs()
        m.VerifyAll()

    def test_get_folder(self):
        """Test _get_folder."""
        m = self.mox
        m.StubOutWithMock(self._volumeops, '_get_parent')
        self._volumeops._get_parent(mox.IgnoreArg(), 'Folder')

        m.ReplayAll()
        self._volumeops._get_folder(mox.IgnoreArg())
        m.UnsetStubs()
        m.VerifyAll()

    def test_volumeops_clone_backing(self):
        """Test volumeops.clone_backing."""
        m = self.mox
        m.StubOutWithMock(self._volumeops, '_get_parent')
        backing = FakeMor('VirtualMachine', 'my_back')
        folder = FakeMor('Folder', 'my_fol')
        self._volumeops._get_folder(backing).AndReturn(folder)
        m.StubOutWithMock(self._volumeops, '_get_clone_spec')
        name = 'name'
        snapshot = FakeMor('VirtualMachineSnapshot', 'my_snap')
        datastore = FakeMor('Datastore', 'my_ds')
        self._volumeops._get_clone_spec(datastore, mox.IgnoreArg(), snapshot)
        m.StubOutWithMock(api.VMwareAPISession, 'vim')
        self._session.vim = self._vim
        m.StubOutWithMock(self._session, 'invoke_api')
        task = FakeMor('Task', 'my_task')
        self._session.invoke_api(self._vim, 'CloneVM_Task', backing,
                                 folder=folder, name=name,
                                 spec=mox.IgnoreArg()).AndReturn(task)
        m.StubOutWithMock(self._session, 'wait_for_task')
        clone = FakeMor('VirtualMachine', 'my_clone')
        task_info = FakeTaskInfo('success', clone)
        self._session.wait_for_task(task).AndReturn(task_info)

        m.ReplayAll()
        ret = self._volumeops.clone_backing(name, backing, snapshot,
                                            mox.IgnoreArg(), datastore)
        self.assertEqual(ret, clone)
        m.UnsetStubs()
        m.VerifyAll()

    def test_clone_backing_linked(self):
        """Test _clone_backing with clone type - linked."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'clone_backing')
        volume = FakeObject()
        volume['name'] = 'volume_name'
        self._volumeops.clone_backing(volume['name'], mox.IgnoreArg(),
                                      mox.IgnoreArg(),
                                      volumeops.LINKED_CLONE_TYPE,
                                      mox.IgnoreArg())

        m.ReplayAll()
        self._driver._clone_backing(volume, mox.IgnoreArg(), mox.IgnoreArg(),
                                    volumeops.LINKED_CLONE_TYPE)
        m.UnsetStubs()
        m.VerifyAll()

    def test_clone_backing_full(self):
        """Test _clone_backing with clone type - full."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_host')
        backing = FakeMor('VirtualMachine', 'my_vm')
        host = FakeMor('HostSystem', 'my_host')
        self._volumeops.get_host(backing).AndReturn(host)
        m.StubOutWithMock(self._volumeops, 'get_dss_rp')
        datastore = FakeMor('Datastore', 'my_ds')
        datastores = [datastore]
        resource_pool = FakeMor('ResourcePool', 'my_rp')
        self._volumeops.get_dss_rp(host).AndReturn((datastores,
                                                    resource_pool))
        m.StubOutWithMock(self._driver, '_select_datastore_summary')
        volume = FakeObject()
        volume['name'] = 'volume_name'
        volume['size'] = 1
        summary = FakeDatastoreSummary(1, 1, datastore=datastore)
        self._driver._select_datastore_summary(volume['size'] * units.GiB,
                                               datastores).AndReturn(summary)
        m.StubOutWithMock(self._volumeops, 'clone_backing')
        self._volumeops.clone_backing(volume['name'], backing,
                                      mox.IgnoreArg(),
                                      volumeops.FULL_CLONE_TYPE,
                                      datastore)

        m.ReplayAll()
        self._driver._clone_backing(volume, backing, mox.IgnoreArg(),
                                    volumeops.FULL_CLONE_TYPE)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_volume_from_snapshot(self):
        """Test create_volume_from_snapshot."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        snapshot = FakeObject()
        snapshot['volume_name'] = 'volume_name'
        snapshot['name'] = 'snapshot_name'
        backing = FakeMor('VirtualMachine', 'my_back')
        self._volumeops.get_backing(snapshot['volume_name']).AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'get_snapshot')
        snap_mor = FakeMor('VirtualMachineSnapshot', 'my_snap')
        self._volumeops.get_snapshot(backing,
                                     snapshot['name']).AndReturn(snap_mor)
        volume = FakeObject()
        volume['volume_type_id'] = None
        m.StubOutWithMock(self._driver, '_clone_backing')
        self._driver._clone_backing(volume, backing, snap_mor, mox.IgnoreArg())

        m.ReplayAll()
        self._driver.create_volume_from_snapshot(volume, snapshot)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_cloned_volume_with_backing(self):
        """Test create_cloned_volume with clone type - full."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        backing = FakeMor('VirtualMachine', 'my_back')
        src_vref = FakeObject()
        src_vref['name'] = 'src_vol_name'
        self._volumeops.get_backing(src_vref['name']).AndReturn(backing)
        volume = FakeObject()
        volume['volume_type_id'] = None
        m.StubOutWithMock(self._driver, '_clone_backing')
        self._driver._clone_backing(volume, backing, mox.IgnoreArg(),
                                    volumeops.FULL_CLONE_TYPE)

        m.ReplayAll()
        self._driver.create_cloned_volume(volume, src_vref)
        m.UnsetStubs()

    def test_create_lined_cloned_volume_with_backing(self):
        """Test create_cloned_volume with clone type - linked."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        backing = FakeMor('VirtualMachine', 'my_back')
        src_vref = FakeObject()
        src_vref['name'] = 'src_vol_name'
        self._volumeops.get_backing(src_vref['name']).AndReturn(backing)
        volume = FakeObject()
        volume['id'] = 'volume_id'
        m.StubOutWithMock(vmdk.VMwareVcVmdkDriver, '_get_clone_type')
        moxed = vmdk.VMwareVcVmdkDriver._get_clone_type(volume)
        moxed.AndReturn(volumeops.LINKED_CLONE_TYPE)
        m.StubOutWithMock(self._volumeops, 'create_snapshot')
        name = 'snapshot-%s' % volume['id']
        snapshot = FakeMor('VirtualMachineSnapshot', 'my_snap')
        self._volumeops.create_snapshot(backing, name,
                                        None).AndReturn(snapshot)
        m.StubOutWithMock(self._driver, '_clone_backing')
        self._driver._clone_backing(volume, backing, snapshot,
                                    volumeops.LINKED_CLONE_TYPE)

        m.ReplayAll()
        self._driver.create_cloned_volume(volume, src_vref)
        m.UnsetStubs()
        m.VerifyAll()
