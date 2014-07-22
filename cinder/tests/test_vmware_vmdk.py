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

from distutils.version import LooseVersion
import os

import mock
import mox

from cinder import exception
from cinder.image import glance
from cinder.openstack.common import units
from cinder import test
from cinder.volume import configuration
from cinder.volume.drivers.vmware import api
from cinder.volume.drivers.vmware import error_util
from cinder.volume.drivers.vmware import vim
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

    def Logout(self, session_manager):
        pass

    def TerminateSession(self, session_manager, sessionId):
        pass

    def SessionIsActive(self, session_manager, sessionID, userName):
        pass


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
    def __init__(self):
        self._fields = {}

    def __setitem__(self, key, value):
        self._fields[key] = value

    def __getitem__(self, item):
        return self._fields[item]


class FakeManagedObjectReference(object):
    def __init__(self, lis=None):
        self.ManagedObjectReference = lis or []


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
    VMDK_DRIVER = vmdk.VMwareEsxVmdkDriver

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
                self.counter2 = 0

            @api.Retry(max_retry_count=2, inc_sleep_time=0.001,
                       exceptions=(Exception))
            def fail(self):
                self.counter1 += 1
                raise exception.CinderException('Fail')

            @api.Retry(max_retry_count=2)
            def success(self):
                self.counter2 += 1
                return self.counter2

        test_obj = TestClass()
        self.assertRaises(exception.CinderException, test_obj.fail)
        self.assertEqual(test_obj.counter1, 3)
        ret = test_obj.success()
        self.assertEqual(1, ret)

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
        self.assertEqual(stats['driver_version'], self._driver.VERSION)
        self.assertEqual(stats['storage_protocol'], 'LSI Logic SCSI')
        self.assertEqual(stats['reserved_percentage'], 0)
        self.assertEqual(stats['total_capacity_gb'], 'unknown')
        self.assertEqual(stats['free_capacity_gb'], 'unknown')

    def test_create_volume(self):
        """Test create_volume."""
        driver = self._driver
        host = mock.sentinel.host
        rp = mock.sentinel.resource_pool
        folder = mock.sentinel.folder
        summary = mock.sentinel.summary
        driver._select_ds_for_volume = mock.MagicMock()
        driver._select_ds_for_volume.return_value = (host, rp, folder,
                                                     summary)
        # invoke the create_volume call
        volume = {'name': 'fake_volume'}
        driver.create_volume(volume)
        # verify calls made
        driver._select_ds_for_volume.assert_called_once_with(volume)

        # test create_volume call when _select_ds_for_volume fails
        driver._select_ds_for_volume.side_effect = error_util.VimException('')
        self.assertRaises(error_util.VimFaultException, driver.create_volume,
                          volume)

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
        FakeMor('Task', 'my_task')

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
        volume['name'] = 'vol_name'
        backing = FakeMor('VirtualMachine', 'my_back')
        mux = self._driver._create_backing(volume, host1.obj, {})
        mux.AndRaise(error_util.VimException('Maintenance mode'))
        mux = self._driver._create_backing(volume, host2.obj, {})
        mux.AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'cancel_retrieval')
        self._volumeops.cancel_retrieval(retrieve_result)
        m.StubOutWithMock(self._volumeops, 'continue_retrieval')

        m.ReplayAll()
        result = self._driver._create_backing_in_inventory(volume)
        self.assertEqual(result, backing)
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
        summary1 = FakeDatastoreSummary(5, 100)
        summary2 = FakeDatastoreSummary(25, 100)
        summary3 = FakeDatastoreSummary(50, 100)
        summary4 = FakeDatastoreSummary(75, 100)

        self._volumeops.get_summary(
            datastore1).MultipleTimes().AndReturn(summary1)
        self._volumeops.get_summary(
            datastore2).MultipleTimes().AndReturn(summary2)
        self._volumeops.get_summary(
            datastore3).MultipleTimes().AndReturn(summary3)
        self._volumeops.get_summary(
            datastore4).MultipleTimes().AndReturn(summary4)

        m.StubOutWithMock(self._volumeops, 'get_connected_hosts')

        host1 = FakeMor('HostSystem', 'my_host_1')
        host2 = FakeMor('HostSystem', 'my_host_2')
        host3 = FakeMor('HostSystem', 'my_host_3')
        host4 = FakeMor('HostSystem', 'my_host_4')

        self._volumeops.get_connected_hosts(
            datastore1).MultipleTimes().AndReturn([host1, host2, host3, host4])
        self._volumeops.get_connected_hosts(
            datastore2).MultipleTimes().AndReturn([host1, host2, host3])
        self._volumeops.get_connected_hosts(
            datastore3).MultipleTimes().AndReturn([host1, host2])
        self._volumeops.get_connected_hosts(
            datastore4).MultipleTimes().AndReturn([host1, host2])

        m.ReplayAll()

        summary = self._driver._select_datastore_summary(1, datastores)
        self.assertEqual(summary, summary1)

        summary = self._driver._select_datastore_summary(10, datastores)
        self.assertEqual(summary, summary2)

        summary = self._driver._select_datastore_summary(40, datastores)
        self.assertEqual(summary, summary4)

        self.assertRaises(error_util.VimException,
                          self._driver._select_datastore_summary,
                          100, datastores)
        m.UnsetStubs()
        m.VerifyAll()

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareEsxVmdkDriver.'
                'session', new_callable=mock.PropertyMock)
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareEsxVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_get_folder_ds_summary(self, volumeops, session):
        """Test _get_folder_ds_summary."""
        volumeops = volumeops.return_value
        driver = self._driver
        volume = {'size': 10, 'volume_type_id': 'fake_type'}
        rp = mock.sentinel.resource_pool
        dss = mock.sentinel.datastores
        # patch method calls from _get_folder_ds_summary
        volumeops.get_dc.return_value = mock.sentinel.dc
        volumeops.get_vmfolder.return_value = mock.sentinel.folder
        driver._get_storage_profile = mock.MagicMock()
        driver._select_datastore_summary = mock.MagicMock()
        driver._select_datastore_summary.return_value = mock.sentinel.summary
        # call _get_folder_ds_summary
        (folder, datastore_summary) = driver._get_folder_ds_summary(volume,
                                                                    rp, dss)
        # verify returned values and calls made
        self.assertEqual(mock.sentinel.folder, folder,
                         "Folder returned is wrong.")
        self.assertEqual(mock.sentinel.summary, datastore_summary,
                         "Datastore summary returned is wrong.")
        volumeops.get_dc.assert_called_once_with(rp)
        volumeops.get_vmfolder.assert_called_once_with(mock.sentinel.dc)
        driver._get_storage_profile.assert_called_once_with(volume)
        size = volume['size'] * units.Gi
        driver._select_datastore_summary.assert_called_once_with(size, dss)

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
        self._driver._get_folder_ds_summary(volume, resource_pool,
                                            datastores).AndReturn((folder,
                                                                   summary))
        backing = FakeMor('VirtualMachine', 'my_back')
        m.StubOutWithMock(self._volumeops, 'create_backing')
        self._volumeops.create_backing(volume['name'],
                                       volume['size'] * units.Mi,
                                       mox.IgnoreArg(), folder,
                                       resource_pool, host,
                                       mox.IgnoreArg(),
                                       mox.IgnoreArg(),
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

    def test_create_snapshot_without_backing(self):
        """Test vmdk.create_snapshot without backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        snapshot = FakeObject()
        snapshot['volume_name'] = 'volume_name'
        snapshot['name'] = 'snap_name'
        snapshot['volume'] = FakeObject()
        snapshot['volume']['status'] = 'available'
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
        snapshot['volume'] = FakeObject()
        snapshot['volume']['status'] = 'available'
        backing = FakeMor('VirtualMachine', 'my_back')
        self._volumeops.get_backing(snapshot['volume_name']).AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'create_snapshot')
        self._volumeops.create_snapshot(backing, snapshot['name'],
                                        snapshot['display_description'])

        m.ReplayAll()
        self._driver.create_snapshot(snapshot)
        m.UnsetStubs()
        m.VerifyAll()

    def test_create_snapshot_when_attached(self):
        """Test vmdk.create_snapshot when volume is attached."""
        snapshot = FakeObject()
        snapshot['volume'] = FakeObject()
        snapshot['volume']['status'] = 'in-use'

        self.assertRaises(exception.InvalidVolume,
                          self._driver.create_snapshot, snapshot)

    def test_delete_snapshot_without_backing(self):
        """Test delete_snapshot without backing."""
        m = self.mox
        m.StubOutWithMock(self._driver.__class__, 'volumeops')
        self._driver.volumeops = self._volumeops
        m.StubOutWithMock(self._volumeops, 'get_backing')
        snapshot = FakeObject()
        snapshot['volume_name'] = 'volume_name'
        snapshot['name'] = 'snap_name'
        snapshot['volume'] = FakeObject()
        snapshot['volume']['status'] = 'available'
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
        snapshot['name'] = 'snap_name'
        snapshot['volume'] = FakeObject()
        snapshot['volume']['status'] = 'available'
        backing = FakeMor('VirtualMachine', 'my_back')
        self._volumeops.get_backing(snapshot['volume_name']).AndReturn(backing)
        m.StubOutWithMock(self._volumeops, 'delete_snapshot')
        self._volumeops.delete_snapshot(backing,
                                        snapshot['name'])

        m.ReplayAll()
        self._driver.delete_snapshot(snapshot)
        m.UnsetStubs()
        m.VerifyAll()

    def test_delete_snapshot_when_attached(self):
        """Test delete_snapshot when volume is attached."""
        snapshot = FakeObject()
        snapshot['volume'] = FakeObject()
        snapshot['volume']['status'] = 'in-use'

        self.assertRaises(exception.InvalidVolume,
                          self._driver.delete_snapshot, snapshot)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareEsxVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_create_cloned_volume_without_backing(self, mock_vops):
        """Test create_cloned_volume without a backing."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = {'name': 'mock_vol'}
        src_vref = {'name': 'src_snapshot_name'}
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = None

        # invoke the create_volume_from_snapshot api
        driver.create_cloned_volume(volume, src_vref)

        # verify calls
        driver._verify_volume_creation.assert_called_once_with(volume)
        mock_vops.get_backing.assert_called_once_with('src_snapshot_name')

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareEsxVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_create_cloned_volume_with_backing(self, mock_vops):
        """Test create_cloned_volume with a backing."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = mock.sentinel.volume
        fake_size = 1
        src_vref = {'name': 'src_snapshot_name', 'size': fake_size}
        backing = mock.sentinel.backing
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = backing
        src_vmdk = "[datastore] src_vm/src_vm.vmdk"
        mock_vops.get_vmdk_path.return_value = src_vmdk
        driver._create_backing_by_copying = mock.MagicMock()

        # invoke the create_volume_from_snapshot api
        driver.create_cloned_volume(volume, src_vref)

        # verify calls
        driver._verify_volume_creation.assert_called_once_with(volume)
        mock_vops.get_backing.assert_called_once_with('src_snapshot_name')
        mock_vops.get_vmdk_path.assert_called_once_with(backing)
        driver._create_backing_by_copying.assert_called_once_with(volume,
                                                                  src_vmdk,
                                                                  fake_size)

    @mock.patch.object(VMDK_DRIVER, '_extend_volumeops_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_create_backing_in_inventory')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_create_backing_by_copying(self, volumeops, create_backing,
                                       _extend_virtual_disk):
        self._test_create_backing_by_copying(volumeops, create_backing,
                                             _extend_virtual_disk)

    def _test_create_backing_by_copying(self, volumeops, create_backing,
                                        _extend_virtual_disk):
        """Test _create_backing_by_copying."""
        fake_volume = {'size': 2, 'name': 'fake_volume-0000000000001'}
        fake_size = 1
        fake_src_vmdk_path = "[datastore] src_vm/src_vm.vmdk"
        fake_backing = mock.sentinel.backing
        fake_vmdk_path = mock.sentinel.path
        #"[datastore] dest_vm/dest_vm.vmdk"
        fake_dc = mock.sentinel.datacenter

        create_backing.return_value = fake_backing
        volumeops.get_vmdk_path.return_value = fake_vmdk_path
        volumeops.get_dc.return_value = fake_dc

        # Test with fake_volume['size'] greater than fake_size
        self._driver._create_backing_by_copying(fake_volume,
                                                fake_src_vmdk_path,
                                                fake_size)
        create_backing.assert_called_once_with(fake_volume)
        volumeops.get_vmdk_path.assert_called_once_with(fake_backing)
        volumeops.get_dc.assert_called_once_with(fake_backing)
        volumeops.delete_vmdk_file.assert_called_once_with(fake_vmdk_path,
                                                           fake_dc)
        volumeops.copy_vmdk_file.assert_called_once_with(fake_dc,
                                                         fake_src_vmdk_path,
                                                         fake_vmdk_path)
        _extend_virtual_disk.assert_called_once_with(fake_volume['size'],
                                                     fake_vmdk_path,
                                                     fake_dc)

        # Reset all the mocks and test with fake_volume['size']
        # not greater than fake_size
        _extend_virtual_disk.reset_mock()
        fake_size = 2
        self._driver._create_backing_by_copying(fake_volume,
                                                fake_src_vmdk_path,
                                                fake_size)
        self.assertFalse(_extend_virtual_disk.called)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareEsxVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_create_volume_from_snapshot_without_backing(self, mock_vops):
        """Test create_volume_from_snapshot without a backing."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = {'name': 'mock_vol'}
        snapshot = {'volume_name': 'mock_vol', 'name': 'mock_snap'}
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = None

        # invoke the create_volume_from_snapshot api
        driver.create_volume_from_snapshot(volume, snapshot)

        # verify calls
        driver._verify_volume_creation.assert_called_once_with(volume)
        mock_vops.get_backing.assert_called_once_with('mock_vol')

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareEsxVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_create_volume_from_snap_without_backing_snap(self, mock_vops):
        """Test create_volume_from_snapshot without a backing snapshot."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = {'volume_type_id': None, 'name': 'mock_vol'}
        snapshot = {'volume_name': 'mock_vol', 'name': 'mock_snap'}
        backing = mock.sentinel.backing
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = backing
        mock_vops.get_snapshot.return_value = None

        # invoke the create_volume_from_snapshot api
        driver.create_volume_from_snapshot(volume, snapshot)

        # verify calls
        driver._verify_volume_creation.assert_called_once_with(volume)
        mock_vops.get_backing.assert_called_once_with('mock_vol')
        mock_vops.get_snapshot.assert_called_once_with(backing,
                                                       'mock_snap')

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareEsxVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_create_volume_from_snapshot(self, mock_vops):
        """Test create_volume_from_snapshot."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = {'volume_type_id': None, 'name': 'mock_vol'}
        snapshot = {'volume_name': 'mock_vol', 'name': 'mock_snap',
                    'volume_size': 1}
        fake_size = snapshot['volume_size']
        backing = mock.sentinel.backing
        snap_moref = mock.sentinel.snap_moref
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = backing
        mock_vops.get_snapshot.return_value = snap_moref
        src_vmdk = "[datastore] src_vm/src_vm-001.vmdk"
        mock_vops.get_vmdk_path.return_value = src_vmdk
        driver._create_backing_by_copying = mock.MagicMock()

        # invoke the create_volume_from_snapshot api
        driver.create_volume_from_snapshot(volume, snapshot)

        # verify calls
        driver._verify_volume_creation.assert_called_once_with(volume)
        mock_vops.get_backing.assert_called_once_with('mock_vol')
        mock_vops.get_snapshot.assert_called_once_with(backing,
                                                       'mock_snap')
        mock_vops.get_vmdk_path.assert_called_once_with(snap_moref)
        driver._create_backing_by_copying.assert_called_once_with(volume,
                                                                  src_vmdk,
                                                                  fake_size)

    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER, '_extend_vmdk_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_extend_volume(self, volume_ops, _extend_virtual_disk,
                           _select_ds_for_volume):
        """Test extend_volume."""
        self._test_extend_volume(volume_ops, _extend_virtual_disk,
                                 _select_ds_for_volume)

    def _test_extend_volume(self, volume_ops, _extend_virtual_disk,
                            _select_ds_for_volume):
        fake_name = u'volume-00000001'
        new_size = '21'
        fake_size = '20'
        fake_vol = {'project_id': 'testprjid', 'name': fake_name,
                    'size': fake_size,
                    'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}
        fake_host = mock.sentinel.host
        fake_rp = mock.sentinel.rp
        fake_folder = mock.sentinel.folder
        fake_summary = mock.Mock(spec=object)
        fake_summary.datastore = mock.sentinel.datastore
        fake_summary.name = 'fake_name'
        fake_backing = mock.sentinel.backing
        volume_ops.get_backing.return_value = fake_backing

        # If there is enough space in the datastore, where the volume is
        # located, then the rest of this method will not be called.
        self._driver.extend_volume(fake_vol, new_size)
        _extend_virtual_disk.assert_called_with(fake_name, new_size)
        self.assertFalse(_select_ds_for_volume.called)
        self.assertFalse(volume_ops.get_backing.called)
        self.assertFalse(volume_ops.relocate_backing.called)
        self.assertFalse(volume_ops.move_backing_to_folder.called)

        # If there is not enough space in the datastore, where the volume is
        # located, then the rest of this method will be called. The first time
        # _extend_virtual_disk is called, VimFaultException is raised. The
        # second time it is called, there is no exception.
        _extend_virtual_disk.reset_mock()
        _extend_virtual_disk.side_effect = [error_util.
                                            VimFaultException(mock.Mock(),
                                                              'Error'), None]
        # When _select_ds_for_volume raises no exception.
        _select_ds_for_volume.return_value = (fake_host, fake_rp,
                                              fake_folder, fake_summary)
        self._driver.extend_volume(fake_vol, new_size)
        _select_ds_for_volume.assert_called_with(new_size)
        volume_ops.get_backing.assert_called_with(fake_name)
        volume_ops.relocate_backing.assert_called_with(fake_backing,
                                                       fake_summary.datastore,
                                                       fake_rp,
                                                       fake_host)
        _extend_virtual_disk.assert_called_with(fake_name, new_size)
        volume_ops.move_backing_to_folder.assert_called_with(fake_backing,
                                                             fake_folder)

        # If get_backing raises error_util.VimException,
        # this exception will be caught for volume extend.
        _extend_virtual_disk.reset_mock()
        _extend_virtual_disk.side_effect = [error_util.
                                            VimFaultException(mock.Mock(),
                                                              'Error'), None]
        volume_ops.get_backing.side_effect = error_util.VimException('Error')
        self.assertRaises(error_util.VimException, self._driver.extend_volume,
                          fake_vol, new_size)

        # If _select_ds_for_volume raised an exception, the rest code will
        # not be called.
        _extend_virtual_disk.reset_mock()
        volume_ops.get_backing.reset_mock()
        volume_ops.relocate_backing.reset_mock()
        volume_ops.move_backing_to_folder.reset_mock()
        _extend_virtual_disk.side_effect = [error_util.
                                            VimFaultException(mock.Mock(),
                                                              'Error'), None]
        _select_ds_for_volume.side_effect = error_util.VimException('Error')
        self.assertRaises(error_util.VimException, self._driver.extend_volume,
                          fake_vol, new_size)
        _extend_virtual_disk.assert_called_once_with(fake_name, new_size)
        self.assertFalse(volume_ops.get_backing.called)
        self.assertFalse(volume_ops.relocate_backing.called)
        self.assertFalse(volume_ops.move_backing_to_folder.called)

    def test_copy_image_to_volume_non_vmdk(self):
        """Test copy_image_to_volume for a non-vmdk disk format."""
        fake_context = mock.sentinel.context
        fake_image_id = 'image-123456789'
        fake_image_meta = {'disk_format': 'novmdk'}
        image_service = mock.Mock()
        image_service.show.return_value = fake_image_meta
        fake_volume = {'name': 'fake_name', 'size': 1}
        self.assertRaises(exception.ImageUnacceptable,
                          self._driver.copy_image_to_volume,
                          fake_context, fake_volume,
                          image_service, fake_image_id)

    @mock.patch.object(vmware_images, 'fetch_flat_image')
    @mock.patch.object(VMDK_DRIVER, '_extend_vmdk_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_get_ds_name_flat_vmdk_path')
    @mock.patch.object(VMDK_DRIVER, '_create_backing_in_inventory')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_copy_image_to_volume_vmdk(self, volume_ops, session,
                                       _create_backing_in_inventory,
                                       _get_ds_name_flat_vmdk_path,
                                       _extend_vmdk_virtual_disk,
                                       fetch_flat_image):
        """Test copy_image_to_volume with an acceptable vmdk disk format."""
        self._test_copy_image_to_volume_vmdk(volume_ops, session,
                                             _create_backing_in_inventory,
                                             _get_ds_name_flat_vmdk_path,
                                             _extend_vmdk_virtual_disk,
                                             fetch_flat_image)

    def _test_copy_image_to_volume_vmdk(self, volume_ops, session,
                                        _create_backing_in_inventory,
                                        _get_ds_name_flat_vmdk_path,
                                        _extend_vmdk_virtual_disk,
                                        fetch_flat_image):
        cookies = session.vim.client.options.transport.cookiejar
        fake_context = mock.sentinel.context
        fake_image_id = 'image-id'
        fake_image_meta = {'disk_format': 'vmdk',
                           'size': 2 * units.Gi,
                           'properties': {'vmware_disktype': 'preallocated'}}
        image_service = mock.Mock(glance.GlanceImageService)
        fake_size = 3
        fake_volume = {'name': 'volume_name', 'size': fake_size}
        fake_backing = mock.sentinel.backing
        fake_datastore_name = 'datastore1'
        flat_vmdk_path = 'myvolumes/myvm-flat.vmdk'
        fake_host = mock.sentinel.host
        fake_datacenter = mock.sentinel.datacenter
        fake_datacenter_name = mock.sentinel.datacenter_name
        timeout = self._config.vmware_image_transfer_timeout_secs

        image_service.show.return_value = fake_image_meta
        _create_backing_in_inventory.return_value = fake_backing
        _get_ds_name_flat_vmdk_path.return_value = (fake_datastore_name,
                                                    flat_vmdk_path)
        volume_ops.get_host.return_value = fake_host
        volume_ops.get_dc.return_value = fake_datacenter
        volume_ops.get_entity_name.return_value = fake_datacenter_name

        # If the volume size is greater than the image size,
        # _extend_vmdk_virtual_disk will be called.
        self._driver.copy_image_to_volume(fake_context, fake_volume,
                                          image_service, fake_image_id)
        image_service.show.assert_called_with(fake_context, fake_image_id)
        _create_backing_in_inventory.assert_called_with(fake_volume)
        _get_ds_name_flat_vmdk_path.assert_called_with(fake_backing,
                                                       fake_volume['name'])

        volume_ops.get_host.assert_called_with(fake_backing)
        volume_ops.get_dc.assert_called_with(fake_host)
        volume_ops.get_entity_name.assert_called_with(fake_datacenter)
        fetch_flat_image.assert_called_with(fake_context, timeout,
                                            image_service,
                                            fake_image_id,
                                            image_size=fake_image_meta['size'],
                                            host=self.IP,
                                            data_center_name=
                                            fake_datacenter_name,
                                            datastore_name=fake_datastore_name,
                                            cookies=cookies,
                                            file_path=flat_vmdk_path)
        _extend_vmdk_virtual_disk.assert_called_with(fake_volume['name'],
                                                     fake_size)
        self.assertFalse(volume_ops.delete_backing.called)

        # If the volume size is not greater then than the image size,
        # _extend_vmdk_virtual_disk will not be called.
        _extend_vmdk_virtual_disk.reset_mock()
        fake_size = 2
        fake_volume['size'] = fake_size
        self._driver.copy_image_to_volume(fake_context, fake_volume,
                                          image_service, fake_image_id)
        self.assertFalse(_extend_vmdk_virtual_disk.called)
        self.assertFalse(volume_ops.delete_backing.called)

        # If fetch_flat_image raises an Exception, delete_backing
        # will be called.
        fetch_flat_image.side_effect = exception.CinderException
        self.assertRaises(exception.CinderException,
                          self._driver.copy_image_to_volume,
                          fake_context, fake_volume,
                          image_service, fake_image_id)
        volume_ops.delete_backing.assert_called_with(fake_backing)

    @mock.patch.object(vmware_images, 'fetch_stream_optimized_image')
    @mock.patch.object(VMDK_DRIVER, '_extend_vmdk_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile_id')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_copy_image_to_volume_stream_optimized(self,
                                                   volumeops,
                                                   session,
                                                   get_profile_id,
                                                   _select_ds_for_volume,
                                                   _extend_virtual_disk,
                                                   fetch_optimized_image):
        """Test copy_image_to_volume.

        Test with an acceptable vmdk disk format and streamOptimized disk type.
        """
        self._test_copy_image_to_volume_stream_optimized(volumeops,
                                                         session,
                                                         get_profile_id,
                                                         _select_ds_for_volume,
                                                         _extend_virtual_disk,
                                                         fetch_optimized_image)

    def _test_copy_image_to_volume_stream_optimized(self, volumeops,
                                                    session,
                                                    get_profile_id,
                                                    _select_ds_for_volume,
                                                    _extend_virtual_disk,
                                                    fetch_optimized_image):
        fake_context = mock.Mock()
        fake_backing = mock.sentinel.backing
        fake_image_id = 'image-id'
        size = 5 * units.Gi
        size_gb = float(size) / units.Gi
        fake_volume_size = 1 + size_gb
        adapter_type = 'ide'
        fake_image_meta = {'disk_format': 'vmdk', 'size': size,
                           'properties': {'vmware_disktype': 'streamOptimized',
                                          'vmware_adaptertype': adapter_type}}
        image_service = mock.Mock(glance.GlanceImageService)
        fake_host = mock.sentinel.host
        fake_rp = mock.sentinel.rp
        fake_folder = mock.sentinel.folder
        fake_summary = mock.sentinel.summary
        fake_summary.name = "datastore-1"
        fake_vm_create_spec = mock.sentinel.spec
        fake_disk_type = 'thin'
        vol_name = 'fake_volume name'
        fake_volume = {'name': vol_name, 'size': fake_volume_size,
                       'volume_type_id': None}
        cf = session.vim.client.factory
        vm_import_spec = cf.create('ns0:VirtualMachineImportSpec')
        vm_import_spec.configSpec = fake_vm_create_spec
        timeout = self._config.vmware_image_transfer_timeout_secs

        image_service.show.return_value = fake_image_meta
        volumeops.get_create_spec.return_value = fake_vm_create_spec
        volumeops.get_backing.return_value = fake_backing

        # If _select_ds_for_volume raises an exception, get_create_spec
        # will not be called.
        _select_ds_for_volume.side_effect = error_util.VimException('Error')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.copy_image_to_volume,
                          fake_context, fake_volume,
                          image_service, fake_image_id)
        self.assertFalse(volumeops.get_create_spec.called)

        # If the volume size is greater then than the image size,
        # _extend_vmdk_virtual_disk will be called.
        _select_ds_for_volume.side_effect = None
        _select_ds_for_volume.return_value = (fake_host, fake_rp,
                                              fake_folder, fake_summary)
        profile_id = 'profile-1'
        get_profile_id.return_value = profile_id
        self._driver.copy_image_to_volume(fake_context, fake_volume,
                                          image_service, fake_image_id)
        image_service.show.assert_called_with(fake_context, fake_image_id)
        _select_ds_for_volume.assert_called_with(fake_volume)
        get_profile_id.assert_called_once_with(fake_volume)
        volumeops.get_create_spec.assert_called_with(fake_volume['name'],
                                                     0,
                                                     fake_disk_type,
                                                     fake_summary.name,
                                                     profile_id,
                                                     adapter_type)
        self.assertTrue(fetch_optimized_image.called)
        fetch_optimized_image.assert_called_with(fake_context, timeout,
                                                 image_service,
                                                 fake_image_id,
                                                 session=session,
                                                 host=self.IP,
                                                 resource_pool=fake_rp,
                                                 vm_folder=fake_folder,
                                                 vm_create_spec=
                                                 vm_import_spec,
                                                 image_size=size)
        _extend_virtual_disk.assert_called_with(fake_volume['name'],
                                                fake_volume_size)
        self.assertFalse(volumeops.get_backing.called)
        self.assertFalse(volumeops.delete_backing.called)

        # If the volume size is not greater then than the image size,
        # _extend_vmdk_virtual_disk will not be called.
        fake_volume_size = size_gb
        fake_volume['size'] = fake_volume_size
        _extend_virtual_disk.reset_mock()
        self._driver.copy_image_to_volume(fake_context, fake_volume,
                                          image_service, fake_image_id)
        self.assertFalse(_extend_virtual_disk.called)
        self.assertFalse(volumeops.get_backing.called)
        self.assertFalse(volumeops.delete_backing.called)

        # If fetch_stream_optimized_image raises an exception,
        # get_backing and delete_backing will be called.
        fetch_optimized_image.side_effect = exception.CinderException
        self.assertRaises(exception.CinderException,
                          self._driver.copy_image_to_volume,
                          fake_context, fake_volume,
                          image_service, fake_image_id)
        volumeops.get_backing.assert_called_with(fake_volume['name'])
        volumeops.delete_backing.assert_called_with(fake_backing)

    def test_copy_volume_to_image_non_vmdk(self):
        """Test copy_volume_to_image for a non-vmdk disk format."""
        m = self.mox
        image_meta = FakeObject()
        image_meta['disk_format'] = 'novmdk'
        volume = FakeObject()
        volume['name'] = 'vol-name'
        volume['instance_uuid'] = None
        volume['attached_host'] = None

        m.ReplayAll()
        self.assertRaises(exception.ImageUnacceptable,
                          self._driver.copy_volume_to_image,
                          mox.IgnoreArg(), volume,
                          mox.IgnoreArg(), image_meta)
        m.UnsetStubs()
        m.VerifyAll()

    def test_copy_volume_to_image_when_attached(self):
        """Test copy_volume_to_image when volume is attached."""
        m = self.mox
        volume = FakeObject()
        volume['instance_uuid'] = 'my_uuid'

        m.ReplayAll()
        self.assertRaises(exception.InvalidVolume,
                          self._driver.copy_volume_to_image,
                          mox.IgnoreArg(), volume,
                          mox.IgnoreArg(), mox.IgnoreArg())
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
        size_gb = 5
        size = size_gb * units.Gi
        volume['size'] = size_gb
        volume['project_id'] = project_id
        volume['instance_uuid'] = None
        volume['attached_host'] = None
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
        # vmware_images.upload_image
        timeout = self._config.vmware_image_transfer_timeout_secs
        host_ip = self.IP
        m.StubOutWithMock(vmware_images, 'upload_image')
        vmware_images.upload_image(mox.IgnoreArg(), timeout, image_service,
                                   image_id, project_id, session=self._session,
                                   host=host_ip, vm=backing,
                                   vmdk_file_path=vmdk_file_path,
                                   vmdk_size=size,
                                   image_name=image_id,
                                   image_version=1)

        m.ReplayAll()
        self._driver.copy_volume_to_image(mox.IgnoreArg(), volume,
                                          image_service, image_meta)
        m.UnsetStubs()
        m.VerifyAll()

    def test_retrieve_properties_ex_fault_checker(self):
        """Test retrieve_properties_ex_fault_checker is called."""
        m = self.mox

        class FakeVim(vim.Vim):
            def __init__(self):
                pass

            @property
            def client(self):

                class FakeRetrv(object):
                    def RetrievePropertiesEx(self, collector):
                        pass

                    def __getattr__(self, name):
                        if name == 'service':
                            return FakeRetrv()

                return FakeRetrv()

            def RetrieveServiceContent(self, type='ServiceInstance'):
                return mox.MockAnything()

        _vim = FakeVim()
        m.ReplayAll()
        # retrieve_properties_ex_fault_checker throws authentication error
        self.assertRaises(error_util.VimFaultException,
                          _vim.RetrievePropertiesEx, mox.IgnoreArg())
        m.UnsetStubs()
        m.VerifyAll()

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_extend_vmdk_virtual_disk(self, volume_ops):
        """Test vmdk._extend_vmdk_virtual_disk."""
        self._test_extend_vmdk_virtual_disk(volume_ops)

    def _test_extend_vmdk_virtual_disk(self, volume_ops):
        fake_backing = mock.sentinel.backing
        fake_vmdk_path = "[datastore] dest_vm/dest_vm.vmdk"
        fake_dc = mock.sentinel.datacenter
        fake_name = 'fake_name'
        fake_size = 7

        # If the backing is None, get_vmdk_path and get_dc
        # will not be called
        volume_ops.get_backing.return_value = None
        volume_ops.get_vmdk_path.return_value = fake_vmdk_path
        volume_ops.get_dc.return_value = fake_dc
        self._driver._extend_vmdk_virtual_disk(fake_name, fake_size)
        volume_ops.get_backing.assert_called_once_with(fake_name)
        self.assertFalse(volume_ops.get_vmdk_path.called)
        self.assertFalse(volume_ops.get_dc.called)
        self.assertFalse(volume_ops.extend_virtual_disk.called)

        # Reset the mock and set the backing with a fake,
        # all the mocks should be called.
        volume_ops.get_backing.reset_mock()
        volume_ops.get_backing.return_value = fake_backing
        self._driver._extend_vmdk_virtual_disk(fake_name, fake_size)
        volume_ops.get_vmdk_path.assert_called_once_with(fake_backing)
        volume_ops.get_dc.assert_called_once_with(fake_backing)
        volume_ops.extend_virtual_disk.assert_called_once_with(fake_size,
                                                               fake_vmdk_path,
                                                               fake_dc)

        # Test the exceptional case for extend_virtual_disk
        volume_ops.extend_virtual_disk.side_effect = error_util.VimException(
            'VimException raised.')
        self.assertRaises(error_util.VimException,
                          self._driver._extend_vmdk_virtual_disk,
                          fake_name, fake_size)


class VMwareVcVmdkDriverTestCase(VMwareEsxVmdkDriverTestCase):
    """Test class for VMwareVcVmdkDriver."""
    VMDK_DRIVER = vmdk.VMwareVcVmdkDriver

    DEFAULT_VC_VERSION = '5.5'

    def setUp(self):
        super(VMwareVcVmdkDriverTestCase, self).setUp()
        self._config.vmware_host_version = self.DEFAULT_VC_VERSION
        self._driver = vmdk.VMwareVcVmdkDriver(configuration=self._config)

    def test_get_pbm_wsdl_location(self):
        # no version returns None
        wsdl = self._driver._get_pbm_wsdl_location(None)
        self.assertIsNone(wsdl)

        def expected_wsdl(version):
            driver_dir = os.path.join(os.path.dirname(__file__), '..',
                                      'volume', 'drivers', 'vmware')
            driver_abs_dir = os.path.abspath(driver_dir)
            return 'file://' + os.path.join(driver_abs_dir, 'wsdl', version,
                                            'pbmService.wsdl')

        # verify wsdl path for different version strings
        with mock.patch('os.path.exists') as path_exists:
            path_exists.return_value = True
            wsdl = self._driver._get_pbm_wsdl_location(LooseVersion('5'))
            self.assertEqual(expected_wsdl('5'), wsdl)
            wsdl = self._driver._get_pbm_wsdl_location(LooseVersion('5.5'))
            self.assertEqual(expected_wsdl('5.5'), wsdl)
            wsdl = self._driver._get_pbm_wsdl_location(LooseVersion('5.5.1'))
            self.assertEqual(expected_wsdl('5.5'), wsdl)
            # if wsdl path does not exist, then it returns None
            path_exists.return_value = False
            wsdl = self._driver._get_pbm_wsdl_location(LooseVersion('5.5'))
            self.assertIsNone(wsdl)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'session', new_callable=mock.PropertyMock)
    def test_get_vc_version(self, session):
        # test config overrides fetching from VC server
        version = self._driver._get_vc_version()
        self.assertEqual(self.DEFAULT_VC_VERSION, version)
        # explicitly remove config entry
        self._driver.configuration.vmware_host_version = None
        session.return_value.vim.service_content.about.version = '6.0.1'
        version = self._driver._get_vc_version()
        self.assertEqual(LooseVersion('6.0.1'), version)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_pbm_wsdl_location')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_vc_version')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'session', new_callable=mock.PropertyMock)
    def test_do_setup(self, session, _get_vc_version, _get_pbm_wsdl_location):
        session = session.return_value

        # pbm is disabled
        vc_version = LooseVersion('5.0')
        _get_vc_version.return_value = vc_version
        self._driver.do_setup(mock.ANY)
        self.assertFalse(self._driver._storage_policy_enabled)
        _get_vc_version.assert_called_once_with()

        # pbm is enabled and invalid pbm wsdl location
        vc_version = LooseVersion('5.5')
        _get_vc_version.reset_mock()
        _get_vc_version.return_value = vc_version
        _get_pbm_wsdl_location.return_value = None
        self.assertRaises(error_util.VMwareDriverException,
                          self._driver.do_setup,
                          mock.ANY)
        self.assertFalse(self._driver._storage_policy_enabled)
        _get_vc_version.assert_called_once_with()
        _get_pbm_wsdl_location.assert_called_once_with(vc_version)

        # pbm is enabled and valid pbm wsdl location
        vc_version = LooseVersion('5.5')
        _get_vc_version.reset_mock()
        _get_vc_version.return_value = vc_version
        _get_pbm_wsdl_location.reset_mock()
        _get_pbm_wsdl_location.return_value = 'fake_pbm_location'
        self._driver.do_setup(mock.ANY)
        self.assertTrue(self._driver._storage_policy_enabled)
        _get_vc_version.assert_called_once_with()
        _get_pbm_wsdl_location.assert_called_once_with(vc_version)

    @mock.patch.object(VMDK_DRIVER, '_extend_volumeops_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_create_backing_in_inventory')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_create_backing_by_copying(self, volumeops, create_backing,
                                       extend_virtual_disk):
        self._test_create_backing_by_copying(volumeops, create_backing,
                                             extend_virtual_disk)

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
        self._driver._get_folder_ds_summary(volume, resource_pool,
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

    @mock.patch.object(VMDK_DRIVER, '_extend_vmdk_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_clone_backing_linked(self, volume_ops, _extend_vmdk_virtual_disk):
        """Test _clone_backing with clone type - linked."""
        fake_size = 3
        fake_volume = {'volume_type_id': None, 'name': 'fake_name',
                       'size': fake_size}
        fake_snapshot = {'volume_name': 'volume_name',
                         'name': 'snapshot_name',
                         'volume_size': 2}
        fake_type = volumeops.LINKED_CLONE_TYPE
        fake_backing = mock.sentinel.backing
        self._driver._clone_backing(fake_volume, fake_backing, fake_snapshot,
                                    volumeops.LINKED_CLONE_TYPE,
                                    fake_snapshot['volume_size'])
        volume_ops.clone_backing.assert_called_with(fake_volume['name'],
                                                    fake_backing,
                                                    fake_snapshot,
                                                    fake_type,
                                                    None)
        # If the volume size is greater than the original snapshot size,
        # _extend_vmdk_virtual_disk will be called.
        _extend_vmdk_virtual_disk.assert_called_with(fake_volume['name'],
                                                     fake_volume['size'])

        # If the volume size is not greater than the original snapshot size,
        # _extend_vmdk_virtual_disk will not be called.
        fake_size = 2
        fake_volume['size'] = fake_size
        _extend_vmdk_virtual_disk.reset_mock()
        self._driver._clone_backing(fake_volume, fake_backing, fake_snapshot,
                                    volumeops.LINKED_CLONE_TYPE,
                                    fake_snapshot['volume_size'])
        self.assertFalse(_extend_vmdk_virtual_disk.called)

    @mock.patch.object(VMDK_DRIVER, '_extend_vmdk_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_clone_backing_full(self, volume_ops, _select_ds_for_volume,
                                _extend_vmdk_virtual_disk):
        """Test _clone_backing with clone type - full."""
        fake_host = mock.sentinel.host
        fake_backing = mock.sentinel.backing
        fake_folder = mock.sentinel.folder
        fake_datastore = mock.sentinel.datastore
        fake_resource_pool = mock.sentinel.resourcePool
        fake_summary = mock.Mock(spec=object)
        fake_summary.datastore = fake_datastore
        fake_size = 3
        fake_volume = {'volume_type_id': None, 'name': 'fake_name',
                       'size': fake_size}
        fake_snapshot = {'volume_name': 'volume_name', 'name': 'snapshot_name',
                         'volume_size': 2}
        _select_ds_for_volume.return_value = (fake_host,
                                              fake_resource_pool,
                                              fake_folder, fake_summary)
        self._driver._clone_backing(fake_volume, fake_backing, fake_snapshot,
                                    volumeops.FULL_CLONE_TYPE,
                                    fake_snapshot['volume_size'])
        _select_ds_for_volume.assert_called_with(fake_volume)
        volume_ops.clone_backing.assert_called_with(fake_volume['name'],
                                                    fake_backing,
                                                    fake_snapshot,
                                                    volumeops.FULL_CLONE_TYPE,
                                                    fake_datastore)
        # If the volume size is greater than the original snapshot size,
        # _extend_vmdk_virtual_disk will be called.
        _extend_vmdk_virtual_disk.assert_called_with(fake_volume['name'],
                                                     fake_volume['size'])

        # If the volume size is not greater than the original snapshot size,
        # _extend_vmdk_virtual_disk will not be called.
        fake_size = 2
        fake_volume['size'] = fake_size
        _extend_vmdk_virtual_disk.reset_mock()
        self._driver._clone_backing(fake_volume, fake_backing, fake_snapshot,
                                    volumeops.FULL_CLONE_TYPE,
                                    fake_snapshot['volume_size'])
        self.assertFalse(_extend_vmdk_virtual_disk.called)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_create_volume_from_snapshot_without_backing(self, mock_vops):
        """Test create_volume_from_snapshot without a backing."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = {'name': 'mock_vol'}
        snapshot = {'volume_name': 'mock_vol', 'name': 'mock_snap'}
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = None

        # invoke the create_volume_from_snapshot api
        driver.create_volume_from_snapshot(volume, snapshot)

        # verify calls
        driver._verify_volume_creation.assert_called_once_with(volume)
        mock_vops.get_backing.assert_called_once_with('mock_vol')

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_create_volume_from_snap_without_backing_snap(self, mock_vops):
        """Test create_volume_from_snapshot without a backing snapshot."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = {'volume_type_id': None, 'name': 'mock_vol'}
        snapshot = {'volume_name': 'mock_vol', 'name': 'mock_snap'}
        backing = mock.sentinel.backing
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = backing
        mock_vops.get_snapshot.return_value = None

        # invoke the create_volume_from_snapshot api
        driver.create_volume_from_snapshot(volume, snapshot)

        # verify calls
        driver._verify_volume_creation.assert_called_once_with(volume)
        mock_vops.get_backing.assert_called_once_with('mock_vol')
        mock_vops.get_snapshot.assert_called_once_with(backing,
                                                       'mock_snap')

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_create_volume_from_snapshot(self, mock_vops):
        """Test create_volume_from_snapshot."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = {'volume_type_id': None, 'name': 'mock_vol'}
        snapshot = {'volume_name': 'mock_vol', 'name': 'mock_snap',
                    'volume_size': 2}
        backing = mock.sentinel.backing
        snap_moref = mock.sentinel.snap_moref
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = backing
        mock_vops.get_snapshot.return_value = snap_moref
        driver._clone_backing = mock.MagicMock()

        # invoke the create_volume_from_snapshot api
        driver.create_volume_from_snapshot(volume, snapshot)

        # verify calls
        driver._verify_volume_creation.assert_called_once_with(volume)
        mock_vops.get_backing.assert_called_once_with('mock_vol')
        mock_vops.get_snapshot.assert_called_once_with(backing,
                                                       'mock_snap')
        default_clone_type = volumeops.FULL_CLONE_TYPE
        driver._clone_backing.assert_called_once_with(volume,
                                                      backing,
                                                      snap_moref,
                                                      default_clone_type,
                                                      snapshot['volume_size'])

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_create_cloned_volume_without_backing(self, mock_vops):
        """Test create_cloned_volume without a backing."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = {'name': 'mock_vol'}
        src_vref = {'name': 'src_snapshot_name'}
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = None

        # invoke the create_volume_from_snapshot api
        driver.create_cloned_volume(volume, src_vref)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_create_cloned_volume_with_backing(self, mock_vops):
        """Test create_cloned_volume with clone type - full."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = {'volume_type_id': None, 'name': 'mock_vol'}
        src_vref = {'name': 'src_snapshot_name', 'size': 1}
        backing = mock.sentinel.backing
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = backing
        default_clone_type = volumeops.FULL_CLONE_TYPE
        driver._clone_backing = mock.MagicMock()

        # invoke the create_volume_from_snapshot api
        driver.create_cloned_volume(volume, src_vref)

        # verify calls
        driver._verify_volume_creation.assert_called_once_with(volume)
        mock_vops.get_backing.assert_called_once_with('src_snapshot_name')
        driver._clone_backing.assert_called_once_with(volume,
                                                      backing,
                                                      None,
                                                      default_clone_type,
                                                      src_vref['size'])

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_clone_type')
    def test_create_linked_cloned_volume_with_backing(self, get_clone_type,
                                                      mock_vops):
        """Test create_cloned_volume with clone type - linked."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = {'volume_type_id': None, 'name': 'mock_vol', 'id': 'mock_id'}
        src_vref = {'name': 'src_snapshot_name', 'status': 'available',
                    'size': 1}
        backing = mock.sentinel.backing
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = backing
        linked_clone = volumeops.LINKED_CLONE_TYPE
        get_clone_type.return_value = linked_clone
        driver._clone_backing = mock.MagicMock()
        mock_vops.create_snapshot = mock.MagicMock()
        mock_vops.create_snapshot.return_value = mock.sentinel.snapshot

        # invoke the create_volume_from_snapshot api
        driver.create_cloned_volume(volume, src_vref)

        # verify calls
        driver._verify_volume_creation.assert_called_once_with(volume)
        mock_vops.get_backing.assert_called_once_with('src_snapshot_name')
        get_clone_type.assert_called_once_with(volume)
        name = 'snapshot-%s' % volume['id']
        mock_vops.create_snapshot.assert_called_once_with(backing, name, None)
        driver._clone_backing.assert_called_once_with(volume,
                                                      backing,
                                                      mock.sentinel.snapshot,
                                                      linked_clone,
                                                      src_vref['size'])

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_clone_type')
    def test_create_linked_cloned_volume_when_attached(self, get_clone_type,
                                                       mock_vops):
        """Test create_cloned_volume linked clone when volume is attached."""
        mock_vops = mock_vops.return_value
        driver = self._driver
        volume = {'volume_type_id': None, 'name': 'mock_vol', 'id': 'mock_id'}
        src_vref = {'name': 'src_snapshot_name', 'status': 'in-use'}
        backing = mock.sentinel.backing
        driver._verify_volume_creation = mock.MagicMock()
        mock_vops.get_backing.return_value = backing
        linked_clone = volumeops.LINKED_CLONE_TYPE
        get_clone_type.return_value = linked_clone

        # invoke the create_volume_from_snapshot api
        self.assertRaises(exception.InvalidVolume,
                          driver.create_cloned_volume,
                          volume,
                          src_vref)

        # verify calls
        driver._verify_volume_creation.assert_called_once_with(volume)
        mock_vops.get_backing.assert_called_once_with('src_snapshot_name')
        get_clone_type.assert_called_once_with(volume)

    @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs')
    def test_get_storage_profile(self, get_volume_type_extra_specs):
        """Test vmdk _get_storage_profile."""
        # volume with no type id returns None
        volume = FakeObject()
        volume['volume_type_id'] = None
        sp = self._driver._get_storage_profile(volume)
        self.assertEqual(None, sp, "Without a volume_type_id no storage "
                         "profile should be returned.")

        # profile associated with the volume type should be returned
        fake_id = 'fake_volume_id'
        volume['volume_type_id'] = fake_id
        get_volume_type_extra_specs.return_value = 'fake_profile'
        profile = self._driver._get_storage_profile(volume)
        self.assertEqual('fake_profile', profile)
        spec_key = 'vmware:storage_profile'
        get_volume_type_extra_specs.assert_called_once_with(fake_id, spec_key)

        # None should be returned when no storage profile is
        # associated with the volume type
        get_volume_type_extra_specs.return_value = False
        profile = self._driver._get_storage_profile(volume)
        self.assertIsNone(profile)

    @mock.patch('cinder.volume.drivers.vmware.vim_util.'
                'convert_datastores_to_hubs')
    @mock.patch('cinder.volume.drivers.vmware.vim_util.'
                'convert_hubs_to_datastores')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'session', new_callable=mock.PropertyMock)
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_filter_ds_by_profile(self, volumeops, session, hubs_to_ds,
                                  ds_to_hubs):
        """Test vmdk _filter_ds_by_profile() method."""

        volumeops = volumeops.return_value
        session = session.return_value

        # Test with no profile id
        datastores = [mock.sentinel.ds1, mock.sentinel.ds2]
        profile = 'fake_profile'
        volumeops.retrieve_profile_id.return_value = None
        self.assertRaises(error_util.VimException,
                          self._driver._filter_ds_by_profile,
                          datastores, profile)
        volumeops.retrieve_profile_id.assert_called_once_with(profile)

        # Test with a fake profile id
        profileId = 'fake_profile_id'
        filtered_dss = [mock.sentinel.ds1]
        # patch method calls from _filter_ds_by_profile
        volumeops.retrieve_profile_id.return_value = profileId
        pbm_cf = mock.sentinel.pbm_cf
        session.pbm.client.factory = pbm_cf
        hubs = [mock.sentinel.hub1, mock.sentinel.hub2]
        ds_to_hubs.return_value = hubs
        volumeops.filter_matching_hubs.return_value = mock.sentinel.hubs
        hubs_to_ds.return_value = filtered_dss
        # call _filter_ds_by_profile with a fake profile
        actual_dss = self._driver._filter_ds_by_profile(datastores, profile)
        # verify return value and called methods
        self.assertEqual(filtered_dss, actual_dss,
                         "Wrong filtered datastores returned.")
        ds_to_hubs.assert_called_once_with(pbm_cf, datastores)
        volumeops.filter_matching_hubs.assert_called_once_with(hubs,
                                                               profileId)
        hubs_to_ds.assert_called_once_with(mock.sentinel.hubs, datastores)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'session', new_callable=mock.PropertyMock)
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'volumeops', new_callable=mock.PropertyMock)
    def test_get_folder_ds_summary(self, volumeops, session):
        """Test _get_folder_ds_summary."""
        volumeops = volumeops.return_value
        driver = self._driver
        driver._storage_policy_enabled = True
        volume = {'size': 10, 'volume_type_id': 'fake_type'}
        rp = mock.sentinel.resource_pool
        dss = [mock.sentinel.datastore1, mock.sentinel.datastore2]
        filtered_dss = [mock.sentinel.datastore1]
        profile = mock.sentinel.profile

        def filter_ds(datastores, storage_profile):
            return filtered_dss

        # patch method calls from _get_folder_ds_summary
        volumeops.get_dc.return_value = mock.sentinel.dc
        volumeops.get_vmfolder.return_value = mock.sentinel.vmfolder
        volumeops.create_folder.return_value = mock.sentinel.folder
        driver._get_storage_profile = mock.MagicMock()
        driver._get_storage_profile.return_value = profile
        driver._filter_ds_by_profile = mock.MagicMock(side_effect=filter_ds)
        driver._select_datastore_summary = mock.MagicMock()
        driver._select_datastore_summary.return_value = mock.sentinel.summary
        # call _get_folder_ds_summary
        (folder, datastore_summary) = driver._get_folder_ds_summary(volume,
                                                                    rp, dss)
        # verify returned values and calls made
        self.assertEqual(mock.sentinel.folder, folder,
                         "Folder returned is wrong.")
        self.assertEqual(mock.sentinel.summary, datastore_summary,
                         "Datastore summary returned is wrong.")
        volumeops.get_dc.assert_called_once_with(rp)
        volumeops.get_vmfolder.assert_called_once_with(mock.sentinel.dc)
        volumeops.create_folder.assert_called_once_with(mock.sentinel.vmfolder,
                                                        self.VOLUME_FOLDER)
        driver._get_storage_profile.assert_called_once_with(volume)
        driver._filter_ds_by_profile.assert_called_once_with(dss, profile)
        size = volume['size'] * units.Gi
        driver._select_datastore_summary.assert_called_once_with(size,
                                                                 filtered_dss)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_extend_vmdk_virtual_disk(self, volume_ops):
        """Test vmdk._extend_vmdk_virtual_disk."""
        self._test_extend_vmdk_virtual_disk(volume_ops)

    @mock.patch.object(vmware_images, 'fetch_flat_image')
    @mock.patch.object(VMDK_DRIVER, '_extend_vmdk_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_get_ds_name_flat_vmdk_path')
    @mock.patch.object(VMDK_DRIVER, '_create_backing_in_inventory')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_copy_image_to_volume_vmdk(self, volume_ops, session,
                                       _create_backing_in_inventory,
                                       _get_ds_name_flat_vmdk_path,
                                       _extend_vmdk_virtual_disk,
                                       fetch_flat_image):
        """Test copy_image_to_volume with an acceptable vmdk disk format."""
        self._test_copy_image_to_volume_vmdk(volume_ops, session,
                                             _create_backing_in_inventory,
                                             _get_ds_name_flat_vmdk_path,
                                             _extend_vmdk_virtual_disk,
                                             fetch_flat_image)

    @mock.patch.object(vmware_images, 'fetch_stream_optimized_image')
    @mock.patch.object(VMDK_DRIVER, '_extend_vmdk_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile_id')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_copy_image_to_volume_stream_optimized(self, volumeops,
                                                   session,
                                                   get_profile_id,
                                                   _select_ds_for_volume,
                                                   _extend_virtual_disk,
                                                   fetch_optimized_image):
        """Test copy_image_to_volume.

        Test with an acceptable vmdk disk format and streamOptimized disk type.
        """
        self._test_copy_image_to_volume_stream_optimized(volumeops,
                                                         session,
                                                         get_profile_id,
                                                         _select_ds_for_volume,
                                                         _extend_virtual_disk,
                                                         fetch_optimized_image)

    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER, '_extend_vmdk_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_extend_volume(self, volume_ops, _extend_virtual_disk,
                           _select_ds_for_volume):
        """Test extend_volume."""
        self._test_extend_volume(volume_ops, _extend_virtual_disk,
                                 _select_ds_for_volume)

    @mock.patch.object(VMDK_DRIVER, '_get_folder_ds_summary')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_create_backing_with_params(self, vops, get_folder_ds_summary):
        resource_pool = mock.sentinel.resource_pool
        vops.get_dss_rp.return_value = (mock.Mock(), resource_pool)
        folder = mock.sentinel.folder
        summary = mock.sentinel.summary
        get_folder_ds_summary.return_value = (folder, summary)

        volume = {'name': 'vol-1', 'volume_type_id': None, 'size': 1}
        host = mock.Mock()
        create_params = {vmdk.CREATE_PARAM_DISK_LESS: True}
        self._driver._create_backing(volume, host, create_params)

        vops.create_backing_disk_less.assert_called_once_with('vol-1',
                                                              folder,
                                                              resource_pool,
                                                              host,
                                                              summary.name,
                                                              None)

        create_params = {vmdk.CREATE_PARAM_ADAPTER_TYPE: 'ide'}
        self._driver._create_backing(volume, host, create_params)

        vops.create_backing.assert_called_once_with('vol-1',
                                                    units.Mi,
                                                    vmdk.THIN_VMDK_TYPE,
                                                    folder,
                                                    resource_pool,
                                                    host,
                                                    summary.name,
                                                    None,
                                                    'ide')
