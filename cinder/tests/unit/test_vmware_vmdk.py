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
Test suite for VMware vCenter VMDK driver.
"""

from distutils import version as ver

import ddt
import mock
from mox3 import mox
from oslo_utils import units
from oslo_vmware import api
from oslo_vmware import exceptions
from oslo_vmware import image_transfer
import six

from cinder import exception as cinder_exceptions
from cinder.image import glance
from cinder import test
from cinder.volume import configuration
from cinder.volume.drivers.vmware import datastore as hub
from cinder.volume.drivers.vmware import exceptions as vmdk_exceptions
from cinder.volume.drivers.vmware import vmdk
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


# TODO(vbala) Split test methods handling multiple cases into multiple methods,
# each handling a specific case.
@ddt.ddt
class VMwareVcVmdkDriverTestCase(test.TestCase):
    """Unit tests for VMwareVcVmdkDriver."""

    IP = 'localhost'
    PORT = 443
    USERNAME = 'username'
    PASSWORD = 'password'
    VOLUME_FOLDER = 'cinder-volumes'
    API_RETRY_COUNT = 3
    TASK_POLL_INTERVAL = 5.0
    IMG_TX_TIMEOUT = 10
    MAX_OBJECTS = 100
    TMP_DIR = "/vmware-tmp"
    CA_FILE = "/etc/ssl/rui-ca-cert.pem"
    VMDK_DRIVER = vmdk.VMwareVcVmdkDriver
    CLUSTERS = ["cls-1", "cls-2"]
    DEFAULT_VC_VERSION = '5.5'

    VOL_ID = 'abcdefab-cdef-abcd-efab-cdefabcdefab',
    DISPLAY_NAME = 'foo',
    VOL_TYPE_ID = 'd61b8cb3-aa1b-4c9b-b79e-abcdbda8b58a'
    SNAPSHOT_ID = '2f59670a-0355-4790-834c-563b65bba740'
    SNAPSHOT_NAME = 'snap-foo'
    SNAPSHOT_DESCRIPTION = 'test snapshot'

    def setUp(self):
        super(VMwareVcVmdkDriverTestCase, self).setUp()

        self._config = mock.Mock(spec=configuration.Configuration)
        self._config.vmware_host_ip = self.IP
        self._config.vmware_host_username = self.USERNAME
        self._config.vmware_host_password = self.PASSWORD
        self._config.vmware_wsdl_location = None
        self._config.vmware_volume_folder = self.VOLUME_FOLDER
        self._config.vmware_api_retry_count = self.API_RETRY_COUNT
        self._config.vmware_task_poll_interval = self.TASK_POLL_INTERVAL
        self._config.vmware_image_transfer_timeout_secs = self.IMG_TX_TIMEOUT
        self._config.vmware_max_objects_retrieval = self.MAX_OBJECTS
        self._config.vmware_tmp_dir = self.TMP_DIR
        self._config.vmware_ca_file = self.CA_FILE
        self._config.vmware_insecure = False
        self._config.vmware_cluster_name = self.CLUSTERS
        self._config.vmware_host_version = self.DEFAULT_VC_VERSION

        self._db = mock.Mock()
        self._driver = vmdk.VMwareVcVmdkDriver(configuration=self._config,
                                               db=self._db)

        api_retry_count = self._config.vmware_api_retry_count
        task_poll_interval = self._config.vmware_task_poll_interval,
        self._session = api.VMwareAPISession(self.IP, self.USERNAME,
                                             self.PASSWORD, api_retry_count,
                                             task_poll_interval,
                                             create_session=False)
        self._volumeops = volumeops.VMwareVolumeOps(self._session,
                                                    self.MAX_OBJECTS)
        self._vim = FakeVim()

    def test_get_volume_stats(self):
        stats = self._driver.get_volume_stats()

        self.assertEqual('VMware', stats['vendor_name'])
        self.assertEqual(self._driver.VERSION, stats['driver_version'])
        self.assertEqual('vmdk', stats['storage_protocol'])
        self.assertEqual(0, stats['reserved_percentage'])
        self.assertEqual('unknown', stats['total_capacity_gb'])
        self.assertEqual('unknown', stats['free_capacity_gb'])

    def _create_volume_dict(self,
                            vol_id=VOL_ID,
                            display_name=DISPLAY_NAME,
                            volume_type_id=VOL_TYPE_ID,
                            status='available'):
        return {'id': vol_id,
                'display_name': display_name,
                'name': 'volume-%s' % vol_id,
                'volume_type_id': volume_type_id,
                'status': status,
                }

    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    def test_verify_volume_creation(self, select_ds_for_volume):
        volume = self._create_volume_dict()
        self._driver._verify_volume_creation(volume)

        select_ds_for_volume.assert_called_once_with(volume)

    @mock.patch.object(VMDK_DRIVER, '_verify_volume_creation')
    def test_create_volume(self, verify_volume_creation):
        volume = self._create_volume_dict()
        self._driver.create_volume(volume)

        verify_volume_creation.assert_called_once_with(volume)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_delete_volume_without_backing(self, vops):
        vops.get_backing.return_value = None

        volume = self._create_volume_dict()
        self._driver.delete_volume(volume)

        vops.get_backing.assert_called_once_with(volume['name'])
        self.assertFalse(vops.delete_backing.called)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_delete_volume(self, vops):
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        volume = self._create_volume_dict()
        self._driver.delete_volume(volume)

        vops.get_backing.assert_called_once_with(volume['name'])
        vops.delete_backing.assert_called_once_with(backing)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.'
                '_get_volume_type_extra_spec')
    @mock.patch('cinder.volume.drivers.vmware.volumeops.'
                'VirtualDiskType.validate')
    def test_get_extra_spec_disk_type(self, validate,
                                      get_volume_type_extra_spec):
        vmdk_type = mock.sentinel.vmdk_type
        get_volume_type_extra_spec.return_value = vmdk_type

        type_id = mock.sentinel.type_id
        self.assertEqual(vmdk_type,
                         self._driver._get_extra_spec_disk_type(type_id))
        get_volume_type_extra_spec.assert_called_once_with(
            type_id, 'vmdk_type', default_value=vmdk.THIN_VMDK_TYPE)
        validate.assert_called_once_with(vmdk_type)

    @mock.patch.object(VMDK_DRIVER, '_get_extra_spec_disk_type')
    def test_get_disk_type(self, get_extra_spec_disk_type):
        vmdk_type = mock.sentinel.vmdk_type
        get_extra_spec_disk_type.return_value = vmdk_type

        volume = self._create_volume_dict()
        self.assertEqual(vmdk_type, self._driver._get_disk_type(volume))
        get_extra_spec_disk_type.assert_called_once_with(
            volume['volume_type_id'])

    def _create_snapshot_dict(self,
                              volume,
                              snap_id=SNAPSHOT_ID,
                              name=SNAPSHOT_NAME,
                              description=SNAPSHOT_DESCRIPTION):
        return {'id': snap_id,
                'volume': volume,
                'volume_name': volume['name'],
                'name': name,
                'display_description': description,
                }

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_create_snapshot_without_backing(self, vops):
        vops.get_backing.return_value = None

        volume = self._create_volume_dict()
        snapshot = self._create_snapshot_dict(volume)
        self._driver.create_snapshot(snapshot)

        vops.get_backing.assert_called_once_with(snapshot['volume_name'])
        self.assertFalse(vops.create_snapshot.called)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_create_snapshot_with_backing(self, vops):
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        volume = self._create_volume_dict()
        snapshot = self._create_snapshot_dict(volume)
        self._driver.create_snapshot(snapshot)

        vops.get_backing.assert_called_once_with(snapshot['volume_name'])
        vops.create_snapshot.assert_called_once_with(
            backing, snapshot['name'], snapshot['display_description'])

    def test_create_snapshot_when_attached(self):
        volume = self._create_volume_dict(status='in-use')
        snapshot = self._create_snapshot_dict(volume)
        self.assertRaises(cinder_exceptions.InvalidVolume,
                          self._driver.create_snapshot, snapshot)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_delete_snapshot_without_backing(self, vops):
        vops.get_backing.return_value = None

        volume = self._create_volume_dict()
        snapshot = self._create_snapshot_dict(volume)
        self._driver.delete_snapshot(snapshot)

        vops.get_backing.assert_called_once_with(snapshot['volume_name'])
        self.assertFalse(vops.delete_snapshot.called)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_delete_snapshot_with_backing(self, vops):
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        volume = self._create_volume_dict()
        snapshot = self._create_snapshot_dict(volume)
        self._driver.delete_snapshot(snapshot)

        vops.get_backing.assert_called_once_with(snapshot['volume_name'])
        vops.delete_snapshot.assert_called_once_with(
            backing, snapshot['name'])

    def test_delete_snapshot_when_attached(self):
        volume = self._create_volume_dict(status='in-use')
        snapshot = self._create_snapshot_dict(volume)

        self.assertRaises(cinder_exceptions.InvalidVolume,
                          self._driver.delete_snapshot, snapshot)

    def test_copy_image_to_volume_non_vmdk(self):
        """Test copy_image_to_volume for a non-vmdk disk format."""
        fake_context = mock.sentinel.context
        fake_image_id = 'image-123456789'
        fake_image_meta = {'disk_format': 'novmdk'}
        image_service = mock.Mock()
        image_service.show.return_value = fake_image_meta
        fake_volume = {'name': 'fake_name', 'size': 1}
        self.assertRaises(cinder_exceptions.ImageUnacceptable,
                          self._driver.copy_image_to_volume,
                          fake_context, fake_volume,
                          image_service, fake_image_id)

    @mock.patch.object(VMDK_DRIVER, '_extend_backing')
    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER,
                       '_create_virtual_disk_from_preallocated_image')
    @mock.patch.object(VMDK_DRIVER, '_create_virtual_disk_from_sparse_image')
    @mock.patch(
        'cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver._get_disk_type')
    @mock.patch.object(VMDK_DRIVER, '_get_ds_name_folder_path')
    @mock.patch.object(VMDK_DRIVER, '_create_backing')
    def test_copy_image_to_volume_non_stream_optimized(
            self, create_backing, get_ds_name_folder_path, get_disk_type,
            create_disk_from_sparse_image, create_disk_from_preallocated_image,
            vops, select_ds_for_volume, generate_uuid, extend_backing):
        self._test_copy_image_to_volume_non_stream_optimized(
            create_backing,
            get_ds_name_folder_path,
            get_disk_type,
            create_disk_from_sparse_image,
            create_disk_from_preallocated_image,
            vops,
            select_ds_for_volume,
            generate_uuid,
            extend_backing)

    def _test_copy_image_to_volume_non_stream_optimized(
            self, create_backing, get_ds_name_folder_path, get_disk_type,
            create_disk_from_sparse_image, create_disk_from_preallocated_image,
            vops, select_ds_for_volume, generate_uuid, extend_backing):
        image_size_in_bytes = 2 * units.Gi
        adapter_type = 'lsiLogic'
        image_meta = {'disk_format': 'vmdk',
                      'size': image_size_in_bytes,
                      'properties': {'vmware_disktype': 'sparse',
                                     'vmwware_adaptertype': adapter_type}}
        image_service = mock.Mock(glance.GlanceImageService)
        image_service.show.return_value = image_meta

        backing = mock.Mock()

        def create_backing_mock(volume, create_params):
            self.assertTrue(create_params[vmdk.CREATE_PARAM_DISK_LESS])
            return backing
        create_backing.side_effect = create_backing_mock

        ds_name = mock.Mock()
        folder_path = mock.Mock()
        get_ds_name_folder_path.return_value = (ds_name, folder_path)

        summary = mock.Mock()
        select_ds_for_volume.return_value = (mock.sentinel.host,
                                             mock.sentinel.rp,
                                             mock.sentinel.folder,
                                             summary)

        uuid = "6b77b25a-9136-470e-899e-3c930e570d8e"
        generate_uuid.return_value = uuid

        host = mock.Mock()
        dc_ref = mock.Mock()
        vops.get_host.return_value = host
        vops.get_dc.return_value = dc_ref

        disk_type = vmdk.EAGER_ZEROED_THICK_VMDK_TYPE
        get_disk_type.return_value = disk_type

        path = mock.Mock()
        create_disk_from_sparse_image.return_value = path
        create_disk_from_preallocated_image.return_value = path

        clone = mock.sentinel.clone
        vops.clone_backing.return_value = clone

        volume_size = 2
        vops.get_disk_size.return_value = volume_size * units.Gi

        context = mock.Mock()
        volume = {'name': 'volume_name',
                  'id': 'volume_id',
                  'size': volume_size}
        image_id = mock.Mock()

        self._driver.copy_image_to_volume(
            context, volume, image_service, image_id)

        create_params = {vmdk.CREATE_PARAM_DISK_LESS: True,
                         vmdk.CREATE_PARAM_BACKING_NAME: uuid}
        create_backing.assert_called_once_with(volume,
                                               create_params=create_params)
        create_disk_from_sparse_image.assert_called_once_with(
            context, image_service, image_id, image_size_in_bytes,
            dc_ref, ds_name, folder_path, uuid)
        vops.attach_disk_to_backing.assert_called_once_with(
            backing, image_size_in_bytes / units.Ki, disk_type,
            adapter_type, path.get_descriptor_ds_file_path())
        select_ds_for_volume.assert_called_once_with(volume)
        vops.clone_backing.assert_called_once_with(
            volume['name'], backing, None, volumeops.FULL_CLONE_TYPE,
            summary.datastore, disk_type, mock.sentinel.host, mock.sentinel.rp)
        vops.delete_backing.assert_called_once_with(backing)
        vops.update_backing_disk_uuid.assert_called_once_with(clone,
                                                              volume['id'])
        self.assertFalse(extend_backing.called)

        vops.get_backing.return_value = backing
        vops.get_disk_size.return_value = 1 * units.Gi
        create_backing.reset_mock()
        vops.attach_disk_to_backing.reset_mock()
        vops.delete_backing.reset_mock()
        vops.update_backing_disk_uuid.reset_mock()
        image_meta['properties']['vmware_disktype'] = 'preallocated'

        self._driver.copy_image_to_volume(
            context, volume, image_service, image_id)

        del create_params[vmdk.CREATE_PARAM_BACKING_NAME]
        create_backing.assert_called_once_with(volume,
                                               create_params=create_params)
        create_disk_from_preallocated_image.assert_called_once_with(
            context, image_service, image_id, image_size_in_bytes,
            dc_ref, ds_name, folder_path, volume['name'], adapter_type)
        vops.attach_disk_to_backing.assert_called_once_with(
            backing, image_size_in_bytes / units.Ki, disk_type,
            adapter_type, path.get_descriptor_ds_file_path())
        vops.update_backing_disk_uuid.assert_called_once_with(backing,
                                                              volume['id'])
        extend_backing.assert_called_once_with(backing, volume['size'])

        extend_backing.reset_mock()
        create_disk_from_preallocated_image.side_effect = (
            exceptions.VimException("Error"))

        self.assertRaises(exceptions.VimException,
                          self._driver.copy_image_to_volume,
                          context, volume, image_service, image_id)
        vops.delete_backing.assert_called_once_with(backing)
        self.assertFalse(extend_backing.called)

    @mock.patch.object(VMDK_DRIVER, '_copy_temp_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_get_temp_image_folder')
    @mock.patch(
        'cinder.volume.drivers.vmware.volumeops.FlatExtentVirtualDiskPath')
    @mock.patch.object(VMDK_DRIVER, '_copy_image')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_create_virtual_disk_from_preallocated_image(
            self, vops, copy_image, flat_extent_path, get_temp_image_folder,
            copy_temp_virtual_disk):
        self._test_create_virtual_disk_from_preallocated_image(
            vops, copy_image, flat_extent_path, get_temp_image_folder,
            copy_temp_virtual_disk)

    def _test_create_virtual_disk_from_preallocated_image(
            self, vops, copy_image, flat_extent_path, get_temp_image_folder,
            copy_temp_virtual_disk):
        context = mock.Mock()
        image_service = mock.Mock()
        image_id = mock.Mock()
        image_size_in_bytes = 2 * units.Gi
        dest_dc_ref = mock.sentinel.dest_dc_ref
        dest_ds_name = "nfs"
        dest_folder_path = "A/B/"
        dest_disk_name = "disk-1"
        adapter_type = "ide"

        dc_ref = mock.sentinel.dc_ref
        ds_name = "local-0"
        folder_path = "cinder_temp"
        get_temp_image_folder.return_value = (dc_ref, ds_name, folder_path)

        path = mock.Mock()
        dest_path = mock.Mock()
        flat_extent_path.side_effect = [path, dest_path]

        ret = self._driver._create_virtual_disk_from_preallocated_image(
            context, image_service, image_id, image_size_in_bytes, dest_dc_ref,
            dest_ds_name, dest_folder_path, dest_disk_name, adapter_type)

        create_descriptor = vops.create_flat_extent_virtual_disk_descriptor
        create_descriptor.assert_called_once_with(
            dc_ref, path, image_size_in_bytes / units.Ki, adapter_type,
            vmdk.EAGER_ZEROED_THICK_VMDK_TYPE)
        copy_image.assert_called_once_with(
            context, dc_ref, image_service, image_id, image_size_in_bytes,
            ds_name, path.get_flat_extent_file_path())
        copy_temp_virtual_disk.assert_called_once_with(dc_ref, path,
                                                       dest_dc_ref, dest_path)
        self.assertEqual(dest_path, ret)

    @mock.patch.object(VMDK_DRIVER, '_copy_temp_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_get_temp_image_folder')
    @mock.patch(
        'cinder.volume.drivers.vmware.volumeops.FlatExtentVirtualDiskPath')
    @mock.patch.object(VMDK_DRIVER, '_copy_image')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_create_virtual_disk_from_preallocated_image_with_no_disk_copy(
            self, vops, copy_image, flat_extent_path, get_temp_image_folder,
            copy_temp_virtual_disk):
        self._test_create_virtual_disk_from_preallocated_image_with_no_copy(
            vops, copy_image, flat_extent_path, get_temp_image_folder,
            copy_temp_virtual_disk)

    def _test_create_virtual_disk_from_preallocated_image_with_no_copy(
            self, vops, copy_image, flat_extent_path, get_temp_image_folder,
            copy_temp_virtual_disk):
        context = mock.Mock()
        image_service = mock.Mock()
        image_id = mock.Mock()
        image_size_in_bytes = 2 * units.Gi
        dest_dc_ref = mock.Mock(value=mock.sentinel.dest_dc_ref)
        dest_ds_name = "nfs"
        dest_folder_path = "A/B/"
        dest_disk_name = "disk-1"
        adapter_type = "ide"

        dc_ref = mock.Mock(value=mock.sentinel.dest_dc_ref)
        ds_name = dest_ds_name
        folder_path = "cinder_temp"
        get_temp_image_folder.return_value = (dc_ref, ds_name, folder_path)

        path = mock.Mock()
        flat_extent_path.return_value = path

        ret = self._driver._create_virtual_disk_from_preallocated_image(
            context, image_service, image_id, image_size_in_bytes, dest_dc_ref,
            dest_ds_name, dest_folder_path, dest_disk_name, adapter_type)

        create_descriptor = vops.create_flat_extent_virtual_disk_descriptor
        create_descriptor.assert_called_once_with(
            dc_ref, path, image_size_in_bytes / units.Ki, adapter_type,
            vmdk.EAGER_ZEROED_THICK_VMDK_TYPE)
        copy_image.assert_called_once_with(
            context, dc_ref, image_service, image_id, image_size_in_bytes,
            ds_name, path.get_flat_extent_file_path())
        self.assertFalse(copy_temp_virtual_disk.called)
        self.assertEqual(path, ret)

    @mock.patch.object(VMDK_DRIVER, '_copy_temp_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_get_temp_image_folder')
    @mock.patch(
        'cinder.volume.drivers.vmware.volumeops.FlatExtentVirtualDiskPath')
    @mock.patch.object(VMDK_DRIVER, '_copy_image')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_create_virtual_disk_from_preallocated_image_with_copy_error(
            self, vops, copy_image, flat_extent_path, get_temp_image_folder,
            copy_temp_virtual_disk):
        self._test_create_virtual_disk_from_preallocated_image_with_copy_error(
            vops, copy_image, flat_extent_path, get_temp_image_folder,
            copy_temp_virtual_disk)

    def _test_create_virtual_disk_from_preallocated_image_with_copy_error(
            self, vops, copy_image, flat_extent_path, get_temp_image_folder,
            copy_temp_virtual_disk):
        context = mock.Mock()
        image_service = mock.Mock()
        image_id = mock.Mock()
        image_size_in_bytes = 2 * units.Gi
        dest_dc_ref = mock.sentinel.dest_dc_ref
        dest_ds_name = "nfs"
        dest_folder_path = "A/B/"
        dest_disk_name = "disk-1"
        adapter_type = "ide"

        dc_ref = mock.sentinel.dc_ref
        ds_name = "local-0"
        folder_path = "cinder_temp"
        get_temp_image_folder.return_value = (dc_ref, ds_name, folder_path)

        path = mock.Mock()
        dest_path = mock.Mock()
        flat_extent_path.side_effect = [path, dest_path]

        copy_image.side_effect = exceptions.VimException("error")

        self.assertRaises(
            exceptions.VimException,
            self._driver._create_virtual_disk_from_preallocated_image,
            context, image_service, image_id, image_size_in_bytes, dest_dc_ref,
            dest_ds_name, dest_folder_path, dest_disk_name, adapter_type)

        create_descriptor = vops.create_flat_extent_virtual_disk_descriptor
        create_descriptor.assert_called_once_with(
            dc_ref, path, image_size_in_bytes / units.Ki, adapter_type,
            vmdk.EAGER_ZEROED_THICK_VMDK_TYPE)

        copy_image.assert_called_once_with(
            context, dc_ref, image_service, image_id, image_size_in_bytes,
            ds_name, path.get_flat_extent_file_path())
        vops.delete_file.assert_called_once_with(
            path.get_descriptor_ds_file_path(), dc_ref)
        self.assertFalse(copy_temp_virtual_disk.called)

    @mock.patch(
        'cinder.volume.drivers.vmware.volumeops.'
        'MonolithicSparseVirtualDiskPath')
    @mock.patch(
        'cinder.volume.drivers.vmware.volumeops.FlatExtentVirtualDiskPath')
    @mock.patch.object(VMDK_DRIVER, '_copy_temp_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_copy_image')
    def test_create_virtual_disk_from_sparse_image(
            self, copy_image, copy_temp_virtual_disk, flat_extent_path,
            sparse_path):
        self._test_create_virtual_disk_from_sparse_image(
            copy_image, copy_temp_virtual_disk, flat_extent_path, sparse_path)

    def _test_create_virtual_disk_from_sparse_image(
            self, copy_image, copy_temp_virtual_disk, flat_extent_path,
            sparse_path):
        context = mock.Mock()
        image_service = mock.Mock()
        image_id = mock.Mock()
        image_size_in_bytes = 2 * units.Gi
        dc_ref = mock.Mock()
        ds_name = "nfs"
        folder_path = "A/B/"
        disk_name = "disk-1"

        src_path = mock.Mock()
        sparse_path.return_value = src_path
        dest_path = mock.Mock()
        flat_extent_path.return_value = dest_path

        ret = self._driver._create_virtual_disk_from_sparse_image(
            context, image_service, image_id, image_size_in_bytes, dc_ref,
            ds_name, folder_path, disk_name)

        copy_image.assert_called_once_with(
            context, dc_ref, image_service, image_id, image_size_in_bytes,
            ds_name, src_path.get_descriptor_file_path())
        copy_temp_virtual_disk.assert_called_once_with(
            dc_ref, src_path, dc_ref, dest_path)
        self.assertEqual(dest_path, ret)

    @mock.patch.object(image_transfer, 'download_stream_optimized_image')
    @mock.patch.object(VMDK_DRIVER, '_extend_backing')
    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile_id')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_copy_image_to_volume_stream_optimized(self,
                                                   volumeops,
                                                   session,
                                                   get_profile_id,
                                                   _select_ds_for_volume,
                                                   extend_backing,
                                                   download_image):
        """Test copy_image_to_volume.

        Test with an acceptable vmdk disk format and streamOptimized disk type.
        """
        self._test_copy_image_to_volume_stream_optimized(volumeops,
                                                         session,
                                                         get_profile_id,
                                                         _select_ds_for_volume,
                                                         extend_backing,
                                                         download_image)

    def _test_copy_image_to_volume_stream_optimized(self, volumeops,
                                                    session,
                                                    get_profile_id,
                                                    _select_ds_for_volume,
                                                    extend_backing,
                                                    download_image):
        fake_context = mock.Mock()
        fake_backing = mock.sentinel.backing
        fake_image_id = 'image-id'
        size = 5 * units.Gi
        size_gb = float(size) / units.Gi
        fake_volume_size = 1 + size_gb
        adapter_type = 'ide'
        fake_image_meta = {'disk_format': 'vmdk', 'size': size,
                           'container_format': 'bare',
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
        vol_id = 'd11a82de-ddaa-448d-b50a-a255a7e61a1e'
        fake_volume = {'name': vol_name,
                       'id': vol_id,
                       'size': fake_volume_size,
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
        _select_ds_for_volume.side_effect = exceptions.VimException('Error')
        self.assertRaises(cinder_exceptions.VolumeBackendAPIException,
                          self._driver.copy_image_to_volume,
                          fake_context, fake_volume,
                          image_service, fake_image_id)
        self.assertFalse(volumeops.get_create_spec.called)

        # If the volume size is greater then than the backing's disk size,
        # _extend_backing will be called.
        _select_ds_for_volume.side_effect = None
        _select_ds_for_volume.return_value = (fake_host, fake_rp,
                                              fake_folder, fake_summary)
        profile_id = 'profile-1'
        get_profile_id.return_value = profile_id

        volumeops.get_disk_size.return_value = size

        backing = mock.sentinel.backing
        download_image.return_value = backing

        self._driver.copy_image_to_volume(fake_context, fake_volume,
                                          image_service, fake_image_id)

        image_service.show.assert_called_with(fake_context, fake_image_id)
        _select_ds_for_volume.assert_called_with(fake_volume)
        get_profile_id.assert_called_once_with(fake_volume)
        extra_config = {vmdk.EXTRA_CONFIG_VOLUME_ID_KEY: vol_id}
        volumeops.get_create_spec.assert_called_with(fake_volume['name'],
                                                     0,
                                                     fake_disk_type,
                                                     fake_summary.name,
                                                     profileId=profile_id,
                                                     adapter_type=adapter_type,
                                                     extra_config=extra_config)
        self.assertTrue(download_image.called)
        download_image.assert_called_with(fake_context, timeout,
                                          image_service,
                                          fake_image_id,
                                          session=session,
                                          host=self.IP,
                                          port=self.PORT,
                                          resource_pool=fake_rp,
                                          vm_folder=fake_folder,
                                          vm_import_spec=vm_import_spec,
                                          image_size=size)
        volumeops.update_backing_disk_uuid.assert_called_once_with(
            backing, fake_volume['id'])
        extend_backing.assert_called_once_with(backing, fake_volume_size)

        # If the volume size is not greater then than backing's disk size,
        # _extend_backing will not be called.
        volumeops.get_disk_size.return_value = fake_volume_size * units.Gi
        extend_backing.reset_mock()

        self._driver.copy_image_to_volume(fake_context, fake_volume,
                                          image_service, fake_image_id)

        self.assertFalse(extend_backing.called)

        # If fetch_stream_optimized_image raises an exception,
        # get_backing and delete_backing will be called.
        download_image.side_effect = exceptions.VimException('error')

        self.assertRaises(exceptions.VimException,
                          self._driver.copy_image_to_volume,
                          fake_context, fake_volume,
                          image_service, fake_image_id)
        volumeops.get_backing.assert_called_with(fake_volume['name'])
        volumeops.delete_backing.assert_called_with(fake_backing)
        self.assertFalse(extend_backing.called)

    def test_copy_volume_to_image_non_vmdk(self):
        """Test copy_volume_to_image for a non-vmdk disk format."""
        m = self.mox
        image_meta = FakeObject()
        image_meta['disk_format'] = 'novmdk'
        volume = FakeObject()
        volume['name'] = 'vol-name'
        volume['volume_attachment'] = None

        m.ReplayAll()
        self.assertRaises(cinder_exceptions.ImageUnacceptable,
                          self._driver.copy_volume_to_image,
                          mox.IgnoreArg(), volume,
                          mox.IgnoreArg(), image_meta)
        m.UnsetStubs()
        m.VerifyAll()

    def test_copy_volume_to_image_when_attached(self):
        """Test copy_volume_to_image when volume is attached."""
        m = self.mox
        volume = FakeObject()
        volume['volume_attachment'] = [mock.sentinel.volume_attachment]

        m.ReplayAll()
        self.assertRaises(cinder_exceptions.InvalidVolume,
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
        image_meta['is_public'] = True
        image_service = FakeObject()
        vol_name = 'volume-123456789'
        project_id = 'project-owner-id-123'
        volume = FakeObject()
        volume['name'] = vol_name
        size_gb = 5
        size = size_gb * units.Gi
        volume['size'] = size_gb
        volume['project_id'] = project_id
        volume['volume_attachment'] = None
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
        m.StubOutWithMock(image_transfer, 'upload_image')
        image_transfer.upload_image(mox.IgnoreArg(),
                                    timeout,
                                    image_service,
                                    image_id,
                                    project_id,
                                    session=self._session,
                                    host=host_ip,
                                    port=self.PORT,
                                    vm=backing,
                                    vmdk_file_path=vmdk_file_path,
                                    vmdk_size=size,
                                    image_name=image_id,
                                    image_version=1,
                                    is_public=True)

        m.ReplayAll()
        self._driver.copy_volume_to_image(mox.IgnoreArg(), volume,
                                          image_service, image_meta)
        m.UnsetStubs()
        m.VerifyAll()

    @mock.patch.object(VMDK_DRIVER, '_delete_temp_backing')
    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch.object(VMDK_DRIVER, '_get_volume_group_folder')
    @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    def test_retype(self, ds_sel, vops, get_volume_type_extra_specs,
                    get_volume_group_folder, generate_uuid,
                    delete_temp_backing):
        self._test_retype(ds_sel, vops, get_volume_type_extra_specs,
                          get_volume_group_folder, generate_uuid,
                          delete_temp_backing)

    def test_in_use(self):
        # Test with in-use volume.
        vol = {'size': 1, 'status': 'in-use', 'name': 'vol-1',
               'volume_type_id': 'def'}
        vol['volume_attachment'] = [mock.sentinel.volume_attachment]
        self.assertTrue(self._driver._in_use(vol))

        # Test with available volume.
        vol['status'] = 'available'
        vol['volume_attachment'] = None
        self.assertFalse(self._driver._in_use(vol))
        vol['volume_attachment'] = []
        self.assertFalse(self._driver._in_use(vol))

    def _test_retype(self, ds_sel, vops, get_volume_type_extra_specs,
                     get_volume_group_folder, genereate_uuid,
                     delete_temp_backing):
        self._driver._storage_policy_enabled = True
        context = mock.sentinel.context
        diff = mock.sentinel.diff
        host = mock.sentinel.host
        new_type = {'id': 'abc'}

        # Test with in-use volume.
        vol = {'size': 1, 'status': 'retyping', 'name': 'vol-1',
               'id': 'd11a82de-ddaa-448d-b50a-a255a7e61a1e',
               'volume_type_id': 'def',
               'project_id': '63c19a12292549818c09946a5e59ddaf'}
        vol['volume_attachment'] = [mock.sentinel.volume_attachment]
        self.assertFalse(self._driver.retype(context, vol, new_type, diff,
                                             host))

        # Test with no backing.
        vops.get_backing.return_value = None
        vol['volume_attachment'] = None
        self.assertTrue(self._driver.retype(context, vol, new_type, diff,
                                            host))

        # Test with no disk type conversion, no profile change and
        # compliant datastore.
        ds_value = mock.sentinel.datastore_value
        datastore = mock.Mock(value=ds_value)
        vops.get_datastore.return_value = datastore

        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        get_volume_type_extra_specs.side_effect = [vmdk.THIN_VMDK_TYPE,
                                                   vmdk.THIN_VMDK_TYPE,
                                                   None,
                                                   None]
        ds_sel.is_datastore_compliant.return_value = True
        self.assertTrue(self._driver.retype(context, vol, new_type, diff,
                                            host))

        # Test with no disk type conversion, profile change and
        # compliant datastore.
        new_profile = mock.sentinel.new_profile
        get_volume_type_extra_specs.side_effect = [vmdk.THIN_VMDK_TYPE,
                                                   vmdk.THIN_VMDK_TYPE,
                                                   'gold-1',
                                                   new_profile]
        ds_sel.is_datastore_compliant.return_value = True
        profile_id = mock.sentinel.profile_id
        ds_sel.get_profile_id.return_value = profile_id

        self.assertTrue(self._driver.retype(context, vol, new_type, diff,
                                            host))
        vops.change_backing_profile.assert_called_once_with(backing,
                                                            profile_id)

        # Test with disk type conversion, profile change and a backing with
        # snapshots. Also test the no candidate datastore case.
        get_volume_type_extra_specs.side_effect = [vmdk.THICK_VMDK_TYPE,
                                                   vmdk.THIN_VMDK_TYPE,
                                                   'gold-1',
                                                   new_profile]
        vops.snapshot_exists.return_value = True
        ds_sel.select_datastore.return_value = ()

        self.assertFalse(self._driver.retype(context, vol, new_type, diff,
                                             host))
        exp_req = {hub.DatastoreSelector.HARD_ANTI_AFFINITY_DS: [ds_value],
                   hub.DatastoreSelector.PROFILE_NAME: new_profile,
                   hub.DatastoreSelector.SIZE_BYTES: units.Gi}
        ds_sel.select_datastore.assert_called_once_with(exp_req)

        # Modify the previous case with a candidate datastore which is
        # different than the backing's current datastore.
        get_volume_type_extra_specs.side_effect = [vmdk.THICK_VMDK_TYPE,
                                                   vmdk.THIN_VMDK_TYPE,
                                                   'gold-1',
                                                   new_profile]
        vops.snapshot_exists.return_value = True

        host = mock.sentinel.host
        rp = mock.sentinel.rp
        candidate_ds = mock.Mock(value=mock.sentinel.candidate_ds_value)
        summary = mock.Mock(datastore=candidate_ds)
        ds_sel.select_datastore.return_value = (host, rp, summary)

        folder = mock.sentinel.folder
        get_volume_group_folder.return_value = folder

        vops.change_backing_profile.reset_mock()

        self.assertTrue(self._driver.retype(context, vol, new_type, diff,
                                            host))
        vops.relocate_backing.assert_called_once_with(
            backing, candidate_ds, rp, host, vmdk.THIN_VMDK_TYPE)
        vops.move_backing_to_folder.assert_called_once_with(backing, folder)
        vops.change_backing_profile.assert_called_once_with(backing,
                                                            profile_id)

        # Modify the previous case with no profile change.
        get_volume_type_extra_specs.side_effect = [vmdk.THICK_VMDK_TYPE,
                                                   vmdk.THIN_VMDK_TYPE,
                                                   'gold-1',
                                                   'gold-1']
        ds_sel.select_datastore.reset_mock()
        vops.relocate_backing.reset_mock()
        vops.move_backing_to_folder.reset_mock()
        vops.change_backing_profile.reset_mock()

        self.assertTrue(self._driver.retype(context, vol, new_type, diff,
                                            host))
        exp_req = {hub.DatastoreSelector.HARD_ANTI_AFFINITY_DS: [ds_value],
                   hub.DatastoreSelector.PROFILE_NAME: 'gold-1',
                   hub.DatastoreSelector.SIZE_BYTES: units.Gi}
        ds_sel.select_datastore.assert_called_once_with(exp_req)
        vops.relocate_backing.assert_called_once_with(
            backing, candidate_ds, rp, host, vmdk.THIN_VMDK_TYPE)
        vops.move_backing_to_folder.assert_called_once_with(backing, folder)
        self.assertFalse(vops.change_backing_profile.called)

        # Test with disk type conversion, profile change, backing with
        # no snapshots and candidate datastore which is same as the backing
        # datastore.
        get_volume_type_extra_specs.side_effect = [vmdk.THICK_VMDK_TYPE,
                                                   vmdk.THIN_VMDK_TYPE,
                                                   'gold-1',
                                                   new_profile]
        vops.snapshot_exists.return_value = False
        summary.datastore = datastore

        uuid = '025b654b-d4ed-47f9-8014-b71a7744eafc'
        genereate_uuid.return_value = uuid

        clone = mock.sentinel.clone
        vops.clone_backing.return_value = clone

        vops.change_backing_profile.reset_mock()

        self.assertTrue(self._driver.retype(context, vol, new_type, diff,
                                            host))
        vops.rename_backing.assert_called_once_with(backing, uuid)
        vops.clone_backing.assert_called_once_with(
            vol['name'], backing, None, volumeops.FULL_CLONE_TYPE,
            datastore, vmdk.THIN_VMDK_TYPE, host, rp)
        vops.update_backing_disk_uuid.assert_called_once_with(clone, vol['id'])
        delete_temp_backing.assert_called_once_with(backing)
        vops.change_backing_profile.assert_called_once_with(clone,
                                                            profile_id)

        # Modify the previous case with exception during clone.
        get_volume_type_extra_specs.side_effect = [vmdk.THICK_VMDK_TYPE,
                                                   vmdk.THIN_VMDK_TYPE,
                                                   'gold-1',
                                                   new_profile]

        vops.clone_backing.side_effect = exceptions.VimException('error')

        vops.update_backing_disk_uuid.reset_mock()
        vops.rename_backing.reset_mock()
        vops.change_backing_profile.reset_mock()

        self.assertRaises(
            exceptions.VimException, self._driver.retype, context, vol,
            new_type, diff, host)
        self.assertFalse(vops.update_backing_disk_uuid.called)
        exp_rename_calls = [mock.call(backing, uuid),
                            mock.call(backing, vol['name'])]
        self.assertEqual(exp_rename_calls, vops.rename_backing.call_args_list)
        self.assertFalse(vops.change_backing_profile.called)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_extend_backing(self, vops):
        vmdk_path = mock.sentinel.vmdk_path
        vops.get_vmdk_path.return_value = vmdk_path
        dc = mock.sentinel.datacenter
        vops.get_dc.return_value = dc

        backing = mock.sentinel.backing
        new_size = 1
        self._driver._extend_backing(backing, new_size)

        vops.get_vmdk_path.assert_called_once_with(backing)
        vops.get_dc.assert_called_once_with(backing)
        vops.extend_virtual_disk.assert_called_once_with(new_size,
                                                         vmdk_path,
                                                         dc)

    @mock.patch.object(image_transfer, 'copy_stream_optimized_disk')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.open', create=True)
    @mock.patch.object(VMDK_DRIVER, '_temporary_file')
    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch.object(VMDK_DRIVER, '_create_backing')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, 'session')
    def test_backup_volume(self, session, vops, create_backing, generate_uuid,
                           temporary_file, file_open, copy_disk):
        self._test_backup_volume(session, vops, create_backing, generate_uuid,
                                 temporary_file, file_open, copy_disk)

    def _test_backup_volume(self, session, vops, create_backing, generate_uuid,
                            temporary_file, file_open, copy_disk):
        volume = {'name': 'vol-1', 'id': 1, 'size': 1}
        self._db.volume_get.return_value = volume

        vops.get_backing.return_value = None
        backing = mock.sentinel.backing
        create_backing.return_value = backing

        uuid = "c1037b23-c5e9-4446-815f-3e097cbf5bb0"
        generate_uuid.return_value = uuid
        tmp_file_path = mock.sentinel.tmp_file_path
        temporary_file_ret = mock.Mock()
        temporary_file.return_value = temporary_file_ret
        temporary_file_ret.__enter__ = mock.Mock(return_value=tmp_file_path)
        temporary_file_ret.__exit__ = mock.Mock(return_value=None)

        vmdk_path = mock.sentinel.vmdk_path
        vops.get_vmdk_path.return_value = vmdk_path

        tmp_file = mock.sentinel.tmp_file
        file_open_ret = mock.Mock()
        file_open.return_value = file_open_ret
        file_open_ret.__enter__ = mock.Mock(return_value=tmp_file)
        file_open_ret.__exit__ = mock.Mock(return_value=None)

        context = mock.sentinel.context
        backup = {'id': 2, 'volume_id': 1}
        backup_service = mock.Mock()
        self._driver.backup_volume(context, backup, backup_service)

        create_backing.assert_called_once_with(volume)
        temporary_file.assert_called_once_with(suffix=".vmdk", prefix=uuid)
        self.assertEqual(mock.call(tmp_file_path, "wb"),
                         file_open.call_args_list[0])
        copy_disk.assert_called_once_with(
            context, self.IMG_TX_TIMEOUT, tmp_file, session=session,
            host=self.IP, port=self.PORT, vm=backing, vmdk_file_path=vmdk_path,
            vmdk_size=volume['size'] * units.Gi)
        self.assertEqual(mock.call(tmp_file_path, "rb"),
                         file_open.call_args_list[1])
        backup_service.backup.assert_called_once_with(backup, tmp_file)

    @mock.patch.object(VMDK_DRIVER, 'extend_volume')
    @mock.patch.object(VMDK_DRIVER, '_restore_backing')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.open', create=True)
    @mock.patch.object(VMDK_DRIVER, '_temporary_file')
    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_restore_backup(self, vops, generate_uuid, temporary_file,
                            file_open, restore_backing, extend_volume):
        self._test_restore_backup(vops, generate_uuid, temporary_file,
                                  file_open, restore_backing, extend_volume)

    def _test_restore_backup(
            self, vops, generate_uuid, temporary_file, file_open,
            restore_backing, extend_volume):
        volume = {'name': 'vol-1', 'id': 1, 'size': 1}
        backup = {'id': 2, 'size': 1}
        context = mock.sentinel.context
        backup_service = mock.Mock()

        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing
        vops.snapshot_exists.return_value = True
        self.assertRaises(
            cinder_exceptions.InvalidVolume, self._driver.restore_backup,
            context, backup, volume, backup_service)

        uuid = "c1037b23-c5e9-4446-815f-3e097cbf5bb0"
        generate_uuid.return_value = uuid
        tmp_file_path = mock.sentinel.tmp_file_path
        temporary_file_ret = mock.Mock()
        temporary_file.return_value = temporary_file_ret
        temporary_file_ret.__enter__ = mock.Mock(return_value=tmp_file_path)
        temporary_file_ret.__exit__ = mock.Mock(return_value=None)

        tmp_file = mock.sentinel.tmp_file
        file_open_ret = mock.Mock()
        file_open.return_value = file_open_ret
        file_open_ret.__enter__ = mock.Mock(return_value=tmp_file)
        file_open_ret.__exit__ = mock.Mock(return_value=None)

        vops.snapshot_exists.return_value = False
        self._driver.restore_backup(context, backup, volume, backup_service)

        temporary_file.assert_called_once_with(suffix=".vmdk", prefix=uuid)
        file_open.assert_called_once_with(tmp_file_path, "wb")
        backup_service.restore.assert_called_once_with(
            backup, volume['id'], tmp_file)
        restore_backing.assert_called_once_with(
            context, volume, backing, tmp_file_path, backup['size'] * units.Gi)
        self.assertFalse(extend_volume.called)

        temporary_file.reset_mock()
        file_open.reset_mock()
        backup_service.reset_mock()
        restore_backing.reset_mock()
        volume = {'name': 'vol-1', 'id': 1, 'size': 2}
        self._driver.restore_backup(context, backup, volume, backup_service)

        temporary_file.assert_called_once_with(suffix=".vmdk", prefix=uuid)
        file_open.assert_called_once_with(tmp_file_path, "wb")
        backup_service.restore.assert_called_once_with(
            backup, volume['id'], tmp_file)
        restore_backing.assert_called_once_with(
            context, volume, backing, tmp_file_path, backup['size'] * units.Gi)
        extend_volume.assert_called_once_with(volume, volume['size'])

    @mock.patch.object(VMDK_DRIVER, '_delete_temp_backing')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch(
        'cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver._get_disk_type')
    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER,
                       '_create_backing_from_stream_optimized_file')
    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    def test_restore_backing(
            self, generate_uuid, create_backing, select_ds, get_disk_type,
            vops, delete_temp_backing):
        self._test_restore_backing(
            generate_uuid, create_backing, select_ds, get_disk_type, vops,
            delete_temp_backing)

    def _test_restore_backing(
            self, generate_uuid, create_backing, select_ds, get_disk_type,
            vops, delete_temp_backing):
        src_uuid = "c1037b23-c5e9-4446-815f-3e097cbf5bb0"
        generate_uuid.return_value = src_uuid

        src = mock.sentinel.src
        create_backing.return_value = src

        summary = mock.Mock()
        summary.datastore = mock.sentinel.datastore
        select_ds.return_value = (mock.sentinel.host, mock.sentinel.rp,
                                  mock.ANY, summary)

        disk_type = vmdk.THIN_VMDK_TYPE
        get_disk_type.return_value = disk_type

        dest = mock.sentinel.dest
        vops.clone_backing.return_value = dest

        context = mock.sentinel.context
        volume = {'name': 'vol-1',
                  'id': 'bd45dfe5-d411-435d-85ac-2605fe7d5d8f', 'size': 1}
        backing = None
        tmp_file_path = mock.sentinel.tmp_file_path
        backup_size = units.Gi
        self._driver._restore_backing(
            context, volume, backing, tmp_file_path, backup_size)

        create_backing.assert_called_once_with(
            context, src_uuid, volume, tmp_file_path, backup_size)
        vops.clone_backing.assert_called_once_with(
            volume['name'], src, None, volumeops.FULL_CLONE_TYPE,
            summary.datastore, disk_type, mock.sentinel.host, mock.sentinel.rp)
        vops.update_backing_disk_uuid.assert_called_once_with(dest,
                                                              volume['id'])
        delete_temp_backing.assert_called_once_with(src)

        create_backing.reset_mock()
        vops.clone_backing.reset_mock()
        vops.update_backing_disk_uuid.reset_mock()
        delete_temp_backing.reset_mock()

        dest_uuid = "de4b0708-f947-4abe-98f8-75e52ce03b7b"
        tmp_uuid = "82c2a4f0-9064-4d95-bd88-6567a36018fa"
        generate_uuid.side_effect = [src_uuid, dest_uuid, tmp_uuid]

        backing = mock.sentinel.backing
        self._driver._restore_backing(
            context, volume, backing, tmp_file_path, backup_size)

        create_backing.assert_called_once_with(
            context, src_uuid, volume, tmp_file_path, backup_size)
        vops.clone_backing.assert_called_once_with(
            dest_uuid, src, None, volumeops.FULL_CLONE_TYPE,
            summary.datastore, disk_type, mock.sentinel.host, mock.sentinel.rp)
        vops.update_backing_disk_uuid.assert_called_once_with(dest,
                                                              volume['id'])
        exp_rename_calls = [mock.call(backing, tmp_uuid),
                            mock.call(dest, volume['name'])]
        self.assertEqual(exp_rename_calls, vops.rename_backing.call_args_list)
        exp_delete_temp_backing_calls = [mock.call(backing), mock.call(src)]
        self.assertEqual(exp_delete_temp_backing_calls,
                         delete_temp_backing.call_args_list)

        delete_temp_backing.reset_mock()
        vops.rename_backing.reset_mock()

        def vops_rename(backing, new_name):
            if backing == dest and new_name == volume['name']:
                raise exceptions.VimException("error")

        vops.rename_backing.side_effect = vops_rename
        generate_uuid.side_effect = [src_uuid, dest_uuid, tmp_uuid]
        self.assertRaises(
            exceptions.VimException, self._driver._restore_backing, context,
            volume, backing, tmp_file_path, backup_size)
        exp_rename_calls = [mock.call(backing, tmp_uuid),
                            mock.call(dest, volume['name']),
                            mock.call(backing, volume['name'])]
        self.assertEqual(exp_rename_calls, vops.rename_backing.call_args_list)
        exp_delete_temp_backing_calls = [mock.call(dest), mock.call(src)]
        self.assertEqual(exp_delete_temp_backing_calls,
                         delete_temp_backing.call_args_list)

    @mock.patch.object(VMDK_DRIVER, '_delete_temp_backing')
    @mock.patch.object(image_transfer, 'download_stream_optimized_data')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.open', create=True)
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_get_disk_type')
    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile_id')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    def test_create_backing_from_stream_optimized_file(
            self, select_ds, session, get_storage_profile_id, get_disk_type,
            vops, file_open, download_data, delete_temp_backing):
        self._test_create_backing_from_stream_optimized_file(
            select_ds, session, get_storage_profile_id, get_disk_type, vops,
            file_open, download_data, delete_temp_backing)

    def _test_create_backing_from_stream_optimized_file(
            self, select_ds, session, get_storage_profile_id, get_disk_type,
            vops, file_open, download_data, delete_temp_backing):
        rp = mock.sentinel.rp
        folder = mock.sentinel.folder
        summary = mock.Mock()
        summary.name = mock.sentinel.name
        select_ds.return_value = (mock.ANY, rp, folder, summary)

        import_spec = mock.Mock()
        session.vim.client.factory.create.return_value = import_spec

        profile_id = 'profile-1'
        get_storage_profile_id.return_value = profile_id

        disk_type = vmdk.THIN_VMDK_TYPE
        get_disk_type.return_value = disk_type

        create_spec = mock.Mock()
        vops.get_create_spec.return_value = create_spec

        tmp_file = mock.sentinel.tmp_file
        file_open_ret = mock.Mock()
        file_open.return_value = file_open_ret
        file_open_ret.__enter__ = mock.Mock(return_value=tmp_file)
        file_open_ret.__exit__ = mock.Mock(return_value=None)

        vm_ref = mock.sentinel.vm_ref
        download_data.return_value = vm_ref

        context = mock.sentinel.context
        name = 'vm-1'
        volume = {'name': 'vol-1',
                  'id': 'd11a82de-ddaa-448d-b50a-a255a7e61a1e',
                  'size': 1}
        tmp_file_path = mock.sentinel.tmp_file_path
        file_size_bytes = units.Gi
        ret = self._driver._create_backing_from_stream_optimized_file(
            context, name, volume, tmp_file_path, file_size_bytes)

        self.assertEqual(vm_ref, ret)
        extra_config = {vmdk.EXTRA_CONFIG_VOLUME_ID_KEY: volume['id']}
        vops.get_create_spec.assert_called_once_with(
            name, 0, disk_type, summary.name, profileId=profile_id,
            extra_config=extra_config)
        file_open.assert_called_once_with(tmp_file_path, "rb")
        download_data.assert_called_once_with(
            context, self.IMG_TX_TIMEOUT, tmp_file, session=session,
            host=self.IP, port=self.PORT, resource_pool=rp, vm_folder=folder,
            vm_import_spec=import_spec, image_size=file_size_bytes)

        download_data.side_effect = exceptions.VimException("error")
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing
        self.assertRaises(
            exceptions.VimException,
            self._driver._create_backing_from_stream_optimized_file,
            context, name, volume, tmp_file_path, file_size_bytes)
        delete_temp_backing.assert_called_once_with(backing)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'session', new_callable=mock.PropertyMock)
    def test_get_vc_version(self, session):
        # test config overrides fetching from vCenter server
        version = self._driver._get_vc_version()
        self.assertEqual(ver.LooseVersion(self.DEFAULT_VC_VERSION), version)
        # explicitly remove config entry
        self._driver.configuration.vmware_host_version = None
        session.return_value.vim.service_content.about.version = '6.0.1'
        version = self._driver._get_vc_version()
        self.assertEqual(ver.LooseVersion('6.0.1'), version)

    @ddt.data('5.1', '5.5')
    def test_validate_vcenter_version(self, version):
        # vCenter versions 5.1 and above should pass validation.
        self._driver._validate_vcenter_version(ver.LooseVersion(version))

    def test_validate_vcenter_version_with_less_than_min_supported_version(
            self):
        vc_version = ver.LooseVersion('5.0')
        # Validation should fail for vCenter version less than 5.1.
        self.assertRaises(exceptions.VMwareDriverException,
                          self._driver._validate_vcenter_version,
                          vc_version)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_validate_vcenter_version')
    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_vc_version')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'session', new_callable=mock.PropertyMock)
    def test_do_setup_with_pbm_disabled(self, session, get_vc_version,
                                        vops_cls, validate_vc_version):
        session_obj = mock.Mock(name='session')
        session.return_value = session_obj
        vc_version = ver.LooseVersion('5.0')
        get_vc_version.return_value = vc_version

        cluster_refs = mock.Mock()
        cluster_refs.values.return_value = mock.sentinel.cluster_refs
        vops = mock.Mock()
        vops.get_cluster_refs.return_value = cluster_refs

        def vops_side_effect(session, max_objects):
            vops._session = session
            vops._max_objects = max_objects
            return vops

        vops_cls.side_effect = vops_side_effect

        self._driver.do_setup(mock.ANY)

        validate_vc_version.assert_called_once_with(vc_version)
        self.assertFalse(self._driver._storage_policy_enabled)
        get_vc_version.assert_called_once_with()
        self.assertEqual(session_obj, self._driver.volumeops._session)
        self.assertEqual(session_obj, self._driver.ds_sel._session)
        self.assertEqual(mock.sentinel.cluster_refs, self._driver._clusters)
        vops.get_cluster_refs.assert_called_once_with(self.CLUSTERS)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_validate_vcenter_version')
    @mock.patch('oslo_vmware.pbm.get_pbm_wsdl_location')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_vc_version')
    def test_do_setup_with_invalid_pbm_wsdl(self, get_vc_version,
                                            get_pbm_wsdl_location,
                                            validate_vc_version):
        vc_version = ver.LooseVersion('5.5')
        get_vc_version.return_value = vc_version
        get_pbm_wsdl_location.return_value = None

        self.assertRaises(exceptions.VMwareDriverException,
                          self._driver.do_setup,
                          mock.ANY)

        validate_vc_version.assert_called_once_with(vc_version)
        self.assertFalse(self._driver._storage_policy_enabled)
        get_vc_version.assert_called_once_with()
        get_pbm_wsdl_location.assert_called_once_with(
            six.text_type(vc_version))

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_validate_vcenter_version')
    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps')
    @mock.patch('oslo_vmware.pbm.get_pbm_wsdl_location')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_vc_version')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                'session', new_callable=mock.PropertyMock)
    def test_do_setup(self, session, get_vc_version, get_pbm_wsdl_location,
                      vops_cls, validate_vc_version):
        session_obj = mock.Mock(name='session')
        session.return_value = session_obj

        vc_version = ver.LooseVersion('5.5')
        get_vc_version.return_value = vc_version
        get_pbm_wsdl_location.return_value = 'file:///pbm.wsdl'

        cluster_refs = mock.Mock()
        cluster_refs.values.return_value = mock.sentinel.cluster_refs
        vops = mock.Mock()
        vops.get_cluster_refs.return_value = cluster_refs

        def vops_side_effect(session, max_objects):
            vops._session = session
            vops._max_objects = max_objects
            return vops

        vops_cls.side_effect = vops_side_effect

        self._driver.do_setup(mock.ANY)

        validate_vc_version.assert_called_once_with(vc_version)
        self.assertTrue(self._driver._storage_policy_enabled)
        get_vc_version.assert_called_once_with()
        get_pbm_wsdl_location.assert_called_once_with(
            six.text_type(vc_version))
        self.assertEqual(session_obj, self._driver.volumeops._session)
        self.assertEqual(session_obj, self._driver.ds_sel._session)
        self.assertEqual(mock.sentinel.cluster_refs, self._driver._clusters)
        vops.get_cluster_refs.assert_called_once_with(self.CLUSTERS)

    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_get_volume_group_folder')
    def test_select_ds_for_volume(self, get_volume_group_folder, vops, ds_sel,
                                  get_storage_profile):

        profile = mock.sentinel.profile
        get_storage_profile.return_value = profile

        host_ref = mock.sentinel.host_ref
        rp = mock.sentinel.rp
        summary = mock.sentinel.summary
        ds_sel.select_datastore.return_value = (host_ref, rp, summary)

        dc = mock.sentinel.dc
        vops.get_dc.return_value = dc
        folder = mock.sentinel.folder
        get_volume_group_folder.return_value = folder

        host = mock.sentinel.host
        project_id = '63c19a12292549818c09946a5e59ddaf'
        vol = {'id': 'c1037b23-c5e9-4446-815f-3e097cbf5bb0', 'size': 1,
               'name': 'vol-c1037b23-c5e9-4446-815f-3e097cbf5bb0',
               'project_id': project_id}
        ret = self._driver._select_ds_for_volume(vol, host)

        self.assertEqual((host_ref, rp, folder, summary), ret)
        exp_req = {hub.DatastoreSelector.SIZE_BYTES: units.Gi,
                   hub.DatastoreSelector.PROFILE_NAME: profile}
        ds_sel.select_datastore.assert_called_once_with(exp_req, hosts=[host])
        vops.get_dc.assert_called_once_with(rp)
        get_volume_group_folder.assert_called_once_with(dc, project_id)

    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_get_volume_group_folder')
    def test_select_ds_for_volume_with_no_host(
            self, get_volume_group_folder, vops, ds_sel, get_storage_profile):

        profile = mock.sentinel.profile
        get_storage_profile.return_value = profile

        host_ref = mock.sentinel.host_ref
        rp = mock.sentinel.rp
        summary = mock.sentinel.summary
        ds_sel.select_datastore.return_value = (host_ref, rp, summary)

        dc = mock.sentinel.dc
        vops.get_dc.return_value = dc
        folder = mock.sentinel.folder
        get_volume_group_folder.return_value = folder

        project_id = '63c19a12292549818c09946a5e59ddaf'
        vol = {'id': 'c1037b23-c5e9-4446-815f-3e097cbf5bb0', 'size': 1,
               'name': 'vol-c1037b23-c5e9-4446-815f-3e097cbf5bb0',
               'project_id': project_id}
        ret = self._driver._select_ds_for_volume(vol)

        self.assertEqual((host_ref, rp, folder, summary), ret)
        exp_req = {hub.DatastoreSelector.SIZE_BYTES: units.Gi,
                   hub.DatastoreSelector.PROFILE_NAME: profile}
        ds_sel.select_datastore.assert_called_once_with(exp_req, hosts=None)
        vops.get_dc.assert_called_once_with(rp)
        get_volume_group_folder.assert_called_once_with(dc, project_id)

    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    def test_select_ds_for_volume_with_no_best_candidate(
            self, ds_sel, get_storage_profile):

        profile = mock.sentinel.profile
        get_storage_profile.return_value = profile

        ds_sel.select_datastore.return_value = ()

        vol = {'id': 'c1037b23-c5e9-4446-815f-3e097cbf5bb0', 'size': 1,
               'name': 'vol-c1037b23-c5e9-4446-815f-3e097cbf5bb0'}
        self.assertRaises(vmdk_exceptions.NoValidDatastoreException,
                          self._driver._select_ds_for_volume, vol)

        exp_req = {hub.DatastoreSelector.SIZE_BYTES: units.Gi,
                   hub.DatastoreSelector.PROFILE_NAME: profile}
        ds_sel.select_datastore.assert_called_once_with(exp_req, hosts=None)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_relocate_backing')
    def test_initialize_connection_with_instance_and_backing(
            self, relocate_backing, vops):

        instance = mock.sentinel.instance
        connector = {'instance': instance}

        backing = mock.Mock(value=mock.sentinel.backing_value)
        vops.get_backing.return_value = backing

        host = mock.sentinel.host
        vops.get_host.return_value = host

        volume = {'name': 'vol-1', 'id': 1}
        conn_info = self._driver.initialize_connection(volume, connector)

        relocate_backing.assert_called_once_with(volume, backing, host)

        self.assertEqual('vmdk', conn_info['driver_volume_type'])
        self.assertEqual(backing.value, conn_info['data']['volume'])
        self.assertEqual(volume['id'],
                         conn_info['data']['volume_id'])

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_relocate_backing')
    @mock.patch.object(VMDK_DRIVER, '_create_backing')
    def test_initialize_connection_with_instance_and_no_backing(
            self, create_backing, relocate_backing, vops):

        instance = mock.sentinel.instance
        connector = {'instance': instance}

        vops.get_backing.return_value = None

        host = mock.sentinel.host
        vops.get_host.return_value = host

        backing = mock.Mock(value=mock.sentinel.backing_value)
        create_backing.return_value = backing

        volume = {'name': 'vol-1', 'id': 1}
        conn_info = self._driver.initialize_connection(volume, connector)

        create_backing.assert_called_once_with(volume, host)
        self.assertFalse(relocate_backing.called)

        self.assertEqual('vmdk', conn_info['driver_volume_type'])
        self.assertEqual(backing.value, conn_info['data']['volume'])
        self.assertEqual(volume['id'],
                         conn_info['data']['volume_id'])

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_relocate_backing')
    @mock.patch.object(VMDK_DRIVER, '_create_backing')
    def test_initialize_connection_with_no_instance_and_no_backing(
            self, create_backing, relocate_backing, vops):

        vops.get_backing.return_value = None

        host = mock.sentinel.host
        vops.get_host.return_value = host

        backing = mock.Mock(value=mock.sentinel.backing_value)
        create_backing.return_value = backing

        connector = {}
        volume = {'name': 'vol-1', 'id': 1}
        conn_info = self._driver.initialize_connection(volume, connector)

        create_backing.assert_called_once_with(volume)
        self.assertFalse(relocate_backing.called)

        self.assertEqual('vmdk', conn_info['driver_volume_type'])
        self.assertEqual(backing.value, conn_info['data']['volume'])
        self.assertEqual(volume['id'],
                         conn_info['data']['volume_id'])

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_get_volume_group_folder(self, vops):
        folder = mock.sentinel.folder
        vops.create_vm_inventory_folder.return_value = folder

        datacenter = mock.sentinel.dc
        project_id = '63c19a12292549818c09946a5e59ddaf'
        self.assertEqual(folder,
                         self._driver._get_volume_group_folder(datacenter,
                                                               project_id))
        project_folder_name = 'Project (%s)' % project_id
        vops.create_vm_inventory_folder.assert_called_once_with(
            datacenter, ['OpenStack', project_folder_name, self.VOLUME_FOLDER])

    @mock.patch.object(VMDK_DRIVER, '_extend_backing')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_clone_backing_linked(self, volume_ops, extend_backing):
        """Test _clone_backing with clone type - linked."""
        clone = mock.sentinel.clone
        volume_ops.clone_backing.return_value = clone

        fake_size = 3
        fake_volume = {'volume_type_id': None, 'name': 'fake_name',
                       'id': '51e47214-8e3c-475d-b44b-aea6cd3eef53',
                       'size': fake_size}
        fake_snapshot = {'volume_name': 'volume_name',
                         'name': 'snapshot_name',
                         'volume_size': 2}
        fake_type = volumeops.LINKED_CLONE_TYPE
        fake_backing = mock.sentinel.backing
        self._driver._clone_backing(fake_volume, fake_backing, fake_snapshot,
                                    volumeops.LINKED_CLONE_TYPE,
                                    fake_snapshot['volume_size'])

        extra_config = {vmdk.EXTRA_CONFIG_VOLUME_ID_KEY: fake_volume['id']}
        volume_ops.clone_backing.assert_called_with(fake_volume['name'],
                                                    fake_backing,
                                                    fake_snapshot,
                                                    fake_type,
                                                    None,
                                                    host=None,
                                                    resource_pool=None,
                                                    extra_config=extra_config)
        volume_ops.update_backing_disk_uuid.assert_called_once_with(
            clone, fake_volume['id'])

        # If the volume size is greater than the original snapshot size,
        # _extend_backing will be called.
        extend_backing.assert_called_with(clone, fake_volume['size'])

        # If the volume size is not greater than the original snapshot size,
        # _extend_backing will not be called.
        fake_size = 2
        fake_volume['size'] = fake_size
        extend_backing.reset_mock()
        self._driver._clone_backing(fake_volume, fake_backing, fake_snapshot,
                                    volumeops.LINKED_CLONE_TYPE,
                                    fake_snapshot['volume_size'])
        self.assertFalse(extend_backing.called)

    @mock.patch.object(VMDK_DRIVER, '_extend_backing')
    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_clone_backing_full(self, volume_ops, _select_ds_for_volume,
                                extend_backing):
        """Test _clone_backing with clone type - full."""
        fake_host = mock.sentinel.host
        fake_folder = mock.sentinel.folder
        fake_datastore = mock.sentinel.datastore
        fake_resource_pool = mock.sentinel.resourcePool
        fake_summary = mock.Mock(spec=object)
        fake_summary.datastore = fake_datastore
        fake_size = 3
        _select_ds_for_volume.return_value = (fake_host,
                                              fake_resource_pool,
                                              fake_folder, fake_summary)

        clone = mock.sentinel.clone
        volume_ops.clone_backing.return_value = clone

        fake_backing = mock.sentinel.backing
        fake_volume = {'volume_type_id': None, 'name': 'fake_name',
                       'id': '51e47214-8e3c-475d-b44b-aea6cd3eef53',
                       'size': fake_size}
        fake_snapshot = {'volume_name': 'volume_name', 'name': 'snapshot_name',
                         'volume_size': 2}
        self._driver._clone_backing(fake_volume, fake_backing, fake_snapshot,
                                    volumeops.FULL_CLONE_TYPE,
                                    fake_snapshot['volume_size'])

        _select_ds_for_volume.assert_called_with(fake_volume)
        extra_config = {vmdk.EXTRA_CONFIG_VOLUME_ID_KEY: fake_volume['id']}
        volume_ops.clone_backing.assert_called_with(fake_volume['name'],
                                                    fake_backing,
                                                    fake_snapshot,
                                                    volumeops.FULL_CLONE_TYPE,
                                                    fake_datastore,
                                                    host=fake_host,
                                                    resource_pool=
                                                    fake_resource_pool,
                                                    extra_config=extra_config)
        volume_ops.update_backing_disk_uuid.assert_called_once_with(
            clone, fake_volume['id'])

        # If the volume size is greater than the original snapshot size,
        # _extend_backing will be called.
        extend_backing.assert_called_with(clone, fake_volume['size'])

        # If the volume size is not greater than the original snapshot size,
        # _extend_backing will not be called.
        fake_size = 2
        fake_volume['size'] = fake_size
        extend_backing.reset_mock()
        self._driver._clone_backing(fake_volume, fake_backing, fake_snapshot,
                                    volumeops.FULL_CLONE_TYPE,
                                    fake_snapshot['volume_size'])
        self.assertFalse(extend_backing.called)

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
        self.assertRaises(cinder_exceptions.InvalidVolume,
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

    def _test_copy_image(self, download_flat_image, session, vops,
                         expected_cacerts=False):

        dc_name = mock.sentinel.dc_name
        vops.get_entity_name.return_value = dc_name

        context = mock.sentinel.context
        dc_ref = mock.sentinel.dc_ref
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        image_size_in_bytes = 102400
        ds_name = mock.sentinel.ds_name
        upload_file_path = mock.sentinel.upload_file_path
        self._driver._copy_image(
            context, dc_ref, image_service, image_id, image_size_in_bytes,
            ds_name, upload_file_path)

        vops.get_entity_name.assert_called_once_with(dc_ref)
        cookies = session.vim.client.options.transport.cookiejar
        download_flat_image.assert_called_once_with(
            context, self.IMG_TX_TIMEOUT, image_service, image_id,
            image_size=image_size_in_bytes, host=self.IP, port=self.PORT,
            data_center_name=dc_name, datastore_name=ds_name, cookies=cookies,
            file_path=upload_file_path, cacerts=expected_cacerts)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch('oslo_vmware.image_transfer.download_flat_image')
    def test_copy_image(self, download_flat_image, session, vops):
        # Default value of vmware_ca_file is not None; it should be passed
        # to download_flat_image as cacerts.
        self._test_copy_image(download_flat_image, session, vops,
                              expected_cacerts=self._config.vmware_ca_file)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch('oslo_vmware.image_transfer.download_flat_image')
    def test_copy_image_insecure(self, download_flat_image, session, vops):
        # Set config options to allow insecure connections.
        self._config.vmware_ca_file = None
        self._config.vmware_insecure = True
        # Since vmware_ca_file is unset and vmware_insecure is True,
        # dowload_flat_image should be called with cacerts=False.
        self._test_copy_image(download_flat_image, session, vops)

    def test_copy_image_to_volume_with_ova_container(self):
        image_service = mock.Mock(glance.GlanceImageService)
        image_size = 2 * units.Gi
        adapter_type = 'ide'
        image_meta = {'disk_format': 'vmdk', 'size': image_size,
                      'container_format': 'ova',
                      'properties': {'vmware_disktype': 'streamOptimized',
                                     'vmware_adaptertype': adapter_type}}
        image_service.show.return_value = image_meta

        context = mock.sentinel.context
        vol_name = 'volume-51e47214-8e3c-475d-b44b-aea6cd3eef53'
        vol_id = '51e47214-8e3c-475d-b44b-aea6cd3eef53'
        display_name = 'foo'
        volume_size = 4
        volume = {'name': vol_name,
                  'id': vol_id,
                  'display_name': display_name,
                  'size': volume_size,
                  'volume_type_id': None}
        image_id = 'image-id'

        self.assertRaises(
            cinder_exceptions.ImageUnacceptable,
            self._driver.copy_image_to_volume, context, volume, image_service,
            image_id)

    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_create_backing_with_params(self, vops, select_ds_for_volume):
        host = mock.sentinel.host
        resource_pool = mock.sentinel.resource_pool
        folder = mock.sentinel.folder
        summary = mock.sentinel.summary
        select_ds_for_volume.return_value = (host, resource_pool, folder,
                                             summary)
        backing = mock.sentinel.backing
        vops.create_backing_disk_less.return_value = backing

        volume = {'name': 'vol-1', 'volume_type_id': None, 'size': 1,
                  'id': 'd11a82de-ddaa-448d-b50a-a255a7e61a1e'}
        create_params = {vmdk.CREATE_PARAM_DISK_LESS: True}
        ret = self._driver._create_backing(volume, host, create_params)

        self.assertEqual(backing, ret)
        extra_config = {vmdk.EXTRA_CONFIG_VOLUME_ID_KEY: volume['id']}
        vops.create_backing_disk_less.assert_called_once_with(
            'vol-1',
            folder,
            resource_pool,
            host,
            summary.name,
            profileId=None,
            extra_config=extra_config)
        self.assertFalse(vops.update_backing_disk_uuid.called)

        vops.create_backing.return_value = backing
        create_params = {vmdk.CREATE_PARAM_ADAPTER_TYPE: 'ide'}
        ret = self._driver._create_backing(volume, host, create_params)

        self.assertEqual(backing, ret)
        vops.create_backing.assert_called_once_with('vol-1',
                                                    units.Mi,
                                                    vmdk.THIN_VMDK_TYPE,
                                                    folder,
                                                    resource_pool,
                                                    host,
                                                    summary.name,
                                                    profileId=None,
                                                    adapter_type='ide',
                                                    extra_config=extra_config)
        vops.update_backing_disk_uuid.assert_called_once_with(backing,
                                                              volume['id'])

        vops.create_backing.reset_mock()
        vops.update_backing_disk_uuid.reset_mock()
        backing_name = "temp-vol"
        create_params = {vmdk.CREATE_PARAM_BACKING_NAME: backing_name}
        ret = self._driver._create_backing(volume, host, create_params)

        self.assertEqual(backing, ret)
        vops.create_backing.assert_called_once_with(backing_name,
                                                    units.Mi,
                                                    vmdk.THIN_VMDK_TYPE,
                                                    folder,
                                                    resource_pool,
                                                    host,
                                                    summary.name,
                                                    profileId=None,
                                                    adapter_type='lsiLogic',
                                                    extra_config=extra_config)
        vops.update_backing_disk_uuid.assert_called_once_with(backing,
                                                              volume['id'])

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('oslo_utils.fileutils.delete_if_exists')
    @mock.patch('tempfile.mkstemp')
    @mock.patch('os.close')
    def test_temporary_file(
            self, close, mkstemp, delete_if_exists, ensure_tree):
        fd = mock.sentinel.fd
        tmp = mock.sentinel.tmp
        mkstemp.return_value = (fd, tmp)
        prefix = ".vmdk"
        suffix = "test"
        with self._driver._temporary_file(prefix=prefix,
                                          suffix=suffix) as tmp_file:
            self.assertEqual(tmp, tmp_file)
            ensure_tree.assert_called_once_with(self.TMP_DIR)
            mkstemp.assert_called_once_with(dir=self.TMP_DIR,
                                            prefix=prefix,
                                            suffix=suffix)
            close.assert_called_once_with(fd)
        delete_if_exists.assert_called_once_with(tmp)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_get_hosts(self, vops):
        host_1 = mock.sentinel.host_1
        host_2 = mock.sentinel.host_2
        host_3 = mock.sentinel.host_3
        vops.get_cluster_hosts.side_effect = [[host_1, host_2], [host_3]]
        # host_1 and host_3 are usable, host_2 is not usable
        vops.is_host_usable.side_effect = [True, False, True]

        cls_1 = mock.sentinel.cls_1
        cls_2 = mock.sentinel.cls_2
        self.assertEqual([host_1, host_3],
                         self._driver._get_hosts([cls_1, cls_2]))
        exp_calls = [mock.call(cls_1), mock.call(cls_2)]
        self.assertEqual(exp_calls, vops.get_cluster_hosts.call_args_list)
        exp_calls = [mock.call(host_1), mock.call(host_2), mock.call(host_3)]
        self.assertEqual(exp_calls, vops.is_host_usable.call_args_list)

    @mock.patch.object(VMDK_DRIVER, '_get_hosts')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    def test_select_datastore(self, ds_sel, get_hosts):
        cls_1 = mock.sentinel.cls_1
        cls_2 = mock.sentinel.cls_2
        self._driver._clusters = [cls_1, cls_2]

        host_1 = mock.sentinel.host_1
        host_2 = mock.sentinel.host_2
        host_3 = mock.sentinel.host_3
        get_hosts.return_value = [host_1, host_2, host_3]

        best_candidate = mock.sentinel.best_candidate
        ds_sel.select_datastore.return_value = best_candidate

        req = mock.sentinel.req
        self.assertEqual(best_candidate, self._driver._select_datastore(req))
        get_hosts.assert_called_once_with(self._driver._clusters)
        ds_sel.select_datastore.assert_called_once_with(
            req, hosts=[host_1, host_2, host_3])

    @mock.patch.object(VMDK_DRIVER, '_get_hosts')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    def test_select_datastore_with_no_best_candidate(self, ds_sel, get_hosts):
        cls_1 = mock.sentinel.cls_1
        cls_2 = mock.sentinel.cls_2
        self._driver._clusters = [cls_1, cls_2]

        host_1 = mock.sentinel.host_1
        host_2 = mock.sentinel.host_2
        host_3 = mock.sentinel.host_3
        get_hosts.return_value = [host_1, host_2, host_3]

        ds_sel.select_datastore.return_value = ()

        req = mock.sentinel.req
        self.assertRaises(vmdk_exceptions.NoValidDatastoreException,
                          self._driver._select_datastore,
                          req)
        get_hosts.assert_called_once_with(self._driver._clusters)
        ds_sel.select_datastore.assert_called_once_with(
            req, hosts=[host_1, host_2, host_3])

    @mock.patch.object(VMDK_DRIVER, '_get_hosts')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    def test_select_datastore_with_single_host(self, ds_sel, get_hosts):
        best_candidate = mock.sentinel.best_candidate
        ds_sel.select_datastore.return_value = best_candidate

        req = mock.sentinel.req
        host_1 = mock.sentinel.host_1
        self.assertEqual(best_candidate,
                         self._driver._select_datastore(req, host_1))
        ds_sel.select_datastore.assert_called_once_with(req, hosts=[host_1])
        self.assertFalse(get_hosts.called)

    @mock.patch.object(VMDK_DRIVER, '_get_hosts')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    def test_select_datastore_with_empty_clusters(self, ds_sel, get_hosts):
        self._driver._clusters = None

        best_candidate = mock.sentinel.best_candidate
        ds_sel.select_datastore.return_value = best_candidate

        req = mock.sentinel.req
        self.assertEqual(best_candidate, self._driver._select_datastore(req))
        ds_sel.select_datastore.assert_called_once_with(req, hosts=None)
        self.assertFalse(get_hosts.called)

    @mock.patch.object(VMDK_DRIVER, '_get_hosts')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    def test_select_datastore_with_no_valid_host(self, ds_sel, get_hosts):
        cls_1 = mock.sentinel.cls_1
        cls_2 = mock.sentinel.cls_2
        self._driver._clusters = [cls_1, cls_2]

        get_hosts.return_value = []

        req = mock.sentinel.req
        self.assertRaises(vmdk_exceptions.NoValidHostException,
                          self._driver._select_datastore, req)
        get_hosts.assert_called_once_with(self._driver._clusters)
        self.assertFalse(ds_sel.called)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    def test_relocate_backing_nop(self, ds_sel, vops):
        self._driver._storage_policy_enabled = True
        volume = {'name': 'vol-1', 'size': 1}

        datastore = mock.sentinel.datastore
        vops.get_datastore.return_value = datastore

        profile = mock.sentinel.profile
        vops.get_profile.return_value = profile

        vops.is_datastore_accessible.return_value = True
        ds_sel.is_datastore_compliant.return_value = True

        backing = mock.sentinel.backing
        host = mock.sentinel.host
        self._driver._relocate_backing(volume, backing, host)

        vops.is_datastore_accessible.assert_called_once_with(datastore, host)
        ds_sel.is_datastore_compliant.assert_called_once_with(datastore,
                                                              profile)
        self.assertFalse(vops.relocate_backing.called)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    def test_relocate_backing_with_no_datastore(
            self, ds_sel, vops):
        self._driver._storage_policy_enabled = True
        volume = {'name': 'vol-1', 'size': 1}

        profile = mock.sentinel.profile
        vops.get_profile.return_value = profile

        vops.is_datastore_accessible.return_value = True
        ds_sel.is_datastore_compliant.return_value = False

        ds_sel.select_datastore.return_value = []

        backing = mock.sentinel.backing
        host = mock.sentinel.host

        self.assertRaises(vmdk_exceptions.NoValidDatastoreException,
                          self._driver._relocate_backing,
                          volume,
                          backing,
                          host)
        ds_sel.select_datastore.assert_called_once_with(
            {hub.DatastoreSelector.SIZE_BYTES: volume['size'] * units.Gi,
             hub.DatastoreSelector.PROFILE_NAME: profile}, hosts=[host])
        self.assertFalse(vops.relocate_backing.called)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_get_volume_group_folder')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    def test_relocate_backing(
            self, ds_sel, get_volume_group_folder, vops):
        volume = {'name': 'vol-1', 'size': 1,
                  'project_id': '63c19a12292549818c09946a5e59ddaf'}

        vops.is_datastore_accessible.return_value = False
        ds_sel.is_datastore_compliant.return_value = True

        backing = mock.sentinel.backing
        host = mock.sentinel.host

        rp = mock.sentinel.rp
        datastore = mock.sentinel.datastore
        summary = mock.Mock(datastore=datastore)
        ds_sel.select_datastore.return_value = (host, rp, summary)

        folder = mock.sentinel.folder
        get_volume_group_folder.return_value = folder

        self._driver._relocate_backing(volume, backing, host)

        vops.relocate_backing.assert_called_once_with(backing,
                                                      datastore,
                                                      rp,
                                                      host)
        vops.move_backing_to_folder.assert_called_once_with(backing,
                                                            folder)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_get_volume_group_folder')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    def test_relocate_backing_with_pbm_disabled(
            self, ds_sel, get_volume_group_folder, vops):
        self._driver._storage_policy_enabled = False
        volume = {'name': 'vol-1', 'size': 1, 'project_id': 'abc'}

        vops.is_datastore_accessible.return_value = False

        backing = mock.sentinel.backing
        host = mock.sentinel.host

        rp = mock.sentinel.rp
        datastore = mock.sentinel.datastore
        summary = mock.Mock(datastore=datastore)
        ds_sel.select_datastore.return_value = (host, rp, summary)

        folder = mock.sentinel.folder
        get_volume_group_folder.return_value = folder

        self._driver._relocate_backing(volume, backing, host)

        self.assertFalse(vops.get_profile.called)
        vops.relocate_backing.assert_called_once_with(backing,
                                                      datastore,
                                                      rp,
                                                      host)
        vops.move_backing_to_folder.assert_called_once_with(backing,
                                                            folder)
        ds_sel.select_datastore.assert_called_once_with(
            {hub.DatastoreSelector.SIZE_BYTES: volume['size'] * units.Gi,
             hub.DatastoreSelector.PROFILE_NAME: None}, hosts=[host])

    @mock.patch('oslo_vmware.api.VMwareAPISession')
    def test_session(self, apiSession):
        self._session = None

        self._driver.session()

        apiSession.assert_called_once_with(
            self._config.vmware_host_ip,
            self._config.vmware_host_username,
            self._config.vmware_host_password,
            self._config.vmware_api_retry_count,
            self._config.vmware_task_poll_interval,
            wsdl_loc=self._config.safe_get('vmware_wsdl_location'),
            pbm_wsdl_loc=None,
            cacert=self._config.vmware_ca_file,
            insecure=self._config.vmware_insecure)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_extend_backing')
    def test_extend_volume_with_no_backing(self, extend_backing, vops):
        vops.get_backing.return_value = None

        volume = {'name': 'volume-51e47214-8e3c-475d-b44b-aea6cd3eef53',
                  'volume_type_id': None, 'size': 1,
                  'id': '51e47214-8e3c-475d-b44b-aea6cd3eef53',
                  'display_name': 'foo'}
        self._driver.extend_volume(volume, 2)

        self.assertFalse(extend_backing.called)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_extend_backing')
    def test_extend_volume(self, extend_backing, vops):
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        volume = {'name': 'volume-51e47214-8e3c-475d-b44b-aea6cd3eef53',
                  'volume_type_id': None, 'size': 1,
                  'id': '51e47214-8e3c-475d-b44b-aea6cd3eef53',
                  'display_name': 'foo'}
        new_size = 2
        self._driver.extend_volume(volume, new_size)

        extend_backing.assert_called_once_with(backing, new_size)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_extend_backing')
    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    def test_extend_volume_with_no_disk_space(self, select_ds_for_volume,
                                              extend_backing, vops):
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        extend_backing.side_effect = [exceptions.NoDiskSpaceException, None]

        host = mock.sentinel.host
        rp = mock.sentinel.rp
        folder = mock.sentinel.folder
        datastore = mock.sentinel.datastore
        summary = mock.Mock(datastore=datastore)
        select_ds_for_volume.return_value = (host, rp, folder, summary)

        volume = {'name': 'volume-51e47214-8e3c-475d-b44b-aea6cd3eef53',
                  'volume_type_id': None, 'size': 1,
                  'id': '51e47214-8e3c-475d-b44b-aea6cd3eef53',
                  'display_name': 'foo'}
        new_size = 2
        self._driver.extend_volume(volume, new_size)

        create_params = {vmdk.CREATE_PARAM_DISK_SIZE: new_size}
        select_ds_for_volume.assert_called_once_with(
            volume, create_params=create_params)

        vops.relocate_backing.assert_called_once_with(backing, datastore, rp,
                                                      host)
        vops.move_backing_to_folder(backing, folder)

        extend_backing_calls = [mock.call(backing, new_size),
                                mock.call(backing, new_size)]
        self.assertEqual(extend_backing_calls, extend_backing.call_args_list)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_extend_backing')
    def test_extend_volume_with_extend_backing_error(
            self, extend_backing, vops):
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        extend_backing.side_effect = exceptions.VimException("Error")

        volume = {'name': 'volume-51e47214-8e3c-475d-b44b-aea6cd3eef53',
                  'volume_type_id': None, 'size': 1,
                  'id': '51e47214-8e3c-475d-b44b-aea6cd3eef53',
                  'display_name': 'foo'}
        new_size = 2
        self.assertRaises(exceptions.VimException, self._driver.extend_volume,
                          volume, new_size)
        extend_backing.assert_called_once_with(backing, new_size)


class ImageDiskTypeTest(test.TestCase):
    """Unit tests for ImageDiskType."""

    def test_is_valid(self):
        self.assertTrue(vmdk.ImageDiskType.is_valid("thin"))
        self.assertTrue(vmdk.ImageDiskType.is_valid("preallocated"))
        self.assertTrue(vmdk.ImageDiskType.is_valid("streamOptimized"))
        self.assertTrue(vmdk.ImageDiskType.is_valid("sparse"))
        self.assertFalse(vmdk.ImageDiskType.is_valid("thick"))

    def test_validate(self):
        vmdk.ImageDiskType.validate("thin")
        vmdk.ImageDiskType.validate("preallocated")
        vmdk.ImageDiskType.validate("streamOptimized")
        vmdk.ImageDiskType.validate("sparse")
        self.assertRaises(cinder_exceptions.ImageUnacceptable,
                          vmdk.ImageDiskType.validate,
                          "thick")
