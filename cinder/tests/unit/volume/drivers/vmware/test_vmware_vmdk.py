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
from oslo_utils import units
from oslo_vmware import api
from oslo_vmware import exceptions
from oslo_vmware import image_transfer
import six

from cinder import context
from cinder import exception as cinder_exceptions
from cinder import test
from cinder.tests.unit import fake_volume
from cinder.volume import configuration
from cinder.volume.drivers.vmware import datastore as hub
from cinder.volume.drivers.vmware import exceptions as vmdk_exceptions
from cinder.volume.drivers.vmware import vmdk
from cinder.volume.drivers.vmware import volumeops


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
    PORT = 2321
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

    VOL_ID = 'abcdefab-cdef-abcd-efab-cdefabcdefab'
    DISPLAY_NAME = 'foo'
    VOL_TYPE_ID = 'd61b8cb3-aa1b-4c9b-b79e-abcdbda8b58a'
    VOL_SIZE = 2
    PROJECT_ID = 'd45beabe-f5de-47b7-b462-0d9ea02889bc'
    SNAPSHOT_ID = '2f59670a-0355-4790-834c-563b65bba740'
    SNAPSHOT_NAME = 'snap-foo'
    SNAPSHOT_DESCRIPTION = 'test snapshot'
    IMAGE_ID = 'eb87f4b0-d625-47f8-bb45-71c43b486d3a'
    IMAGE_NAME = 'image-1'

    def setUp(self):
        super(VMwareVcVmdkDriverTestCase, self).setUp()

        self._config = mock.Mock(spec=configuration.Configuration)
        self._config.vmware_host_ip = self.IP
        self._config.vmware_host_port = self.PORT
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
        self._context = context.get_admin_context()

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
                            status='available',
                            size=VOL_SIZE,
                            attachment=None,
                            project_id=PROJECT_ID):
        return {'id': vol_id,
                'display_name': display_name,
                'name': 'volume-%s' % vol_id,
                'volume_type_id': volume_type_id,
                'status': status,
                'size': size,
                'volume_attachment': attachment,
                'project_id': project_id,
                }

    def _create_volume_obj(self,
                           vol_id=VOL_ID,
                           display_name=DISPLAY_NAME,
                           volume_type_id=VOL_TYPE_ID,
                           status='available',
                           size=VOL_SIZE,
                           attachment=None,
                           project_id=PROJECT_ID):
        vol = self._create_volume_dict(
            vol_id, display_name, volume_type_id, status, size, attachment,
            project_id)
        return fake_volume.fake_volume_obj(self._context, **vol)

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

    @ddt.data('vmdk', 'VMDK', None)
    def test_validate_disk_format(self, disk_format):
        self._driver._validate_disk_format(disk_format)

    def test_validate_disk_format_with_invalid_format(self):
        self.assertRaises(cinder_exceptions.ImageUnacceptable,
                          self._driver._validate_disk_format,
                          'img')

    def _create_image_meta(self,
                           _id=IMAGE_ID,
                           name=IMAGE_NAME,
                           disk_format='vmdk',
                           size=1 * units.Gi,
                           container_format='bare',
                           vmware_disktype='streamOptimized',
                           vmware_adaptertype='lsiLogic',
                           is_public=True):
        return {'id': _id,
                'name': name,
                'disk_format': disk_format,
                'size': size,
                'container_format': container_format,
                'properties': {'vmware_disktype': vmware_disktype,
                               'vmware_adaptertype': vmware_adaptertype,
                               },
                'is_public': is_public,
                }

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_validate_disk_format')
    def test_copy_image_to_volume_with_invalid_container(self,
                                                         validate_disk_format):
        image_service = mock.Mock()
        image_meta = self._create_image_meta(container_format='ami')
        image_service.show.return_value = image_meta

        context = mock.sentinel.context
        volume = self._create_volume_dict()
        image_id = mock.sentinel.image_id

        self.assertRaises(
            cinder_exceptions.ImageUnacceptable,
            self._driver.copy_image_to_volume, context, volume, image_service,
            image_id)
        validate_disk_format.assert_called_once_with(image_meta['disk_format'])

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_validate_disk_format')
    @mock.patch('cinder.volume.drivers.vmware.volumeops.'
                'VirtualDiskAdapterType.validate')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.ImageDiskType.'
                'validate')
    @mock.patch.object(VMDK_DRIVER,
                       '_create_volume_from_non_stream_optimized_image')
    @mock.patch.object(VMDK_DRIVER,
                       '_fetch_stream_optimized_image')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_extend_backing')
    def _test_copy_image_to_volume(self,
                                   extend_backing,
                                   vops,
                                   fetch_stream_optimized_image,
                                   create_volume_from_non_stream_opt_image,
                                   validate_image_disk_type,
                                   validate_image_adapter_type,
                                   validate_disk_format,
                                   vmware_disk_type='streamOptimized',
                                   backing_disk_size=VOL_SIZE,
                                   call_extend_backing=False,
                                   container_format='bare'):

        image_service = mock.Mock()
        image_meta = self._create_image_meta(vmware_disktype=vmware_disk_type,
                                             container_format=container_format)
        image_service.show.return_value = image_meta

        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing
        vops.get_disk_size.return_value = backing_disk_size * units.Gi

        context = mock.sentinel.context
        volume = self._create_volume_dict()
        image_id = mock.sentinel.image_id
        self._driver.copy_image_to_volume(
            context, volume, image_service, image_id)

        validate_disk_format.assert_called_once_with(image_meta['disk_format'])
        validate_image_disk_type.assert_called_once_with(
            image_meta['properties']['vmware_disktype'])
        validate_image_adapter_type.assert_called_once_with(
            image_meta['properties']['vmware_adaptertype'])

        if vmware_disk_type == 'streamOptimized':
            fetch_stream_optimized_image.assert_called_once_with(
                context, volume, image_service, image_id, image_meta['size'],
                image_meta['properties']['vmware_adaptertype'])
        else:
            create_volume_from_non_stream_opt_image.assert_called_once_with(
                context, volume, image_service, image_id, image_meta['size'],
                image_meta['properties']['vmware_adaptertype'],
                image_meta['properties']['vmware_disktype'])

        vops.get_disk_size.assert_called_once_with(backing)
        if call_extend_backing:
            extend_backing.assert_called_once_with(backing, volume['size'])
        else:
            self.assertFalse(extend_backing.called)

    @ddt.data('sparse', 'preallocated', 'streamOptimized')
    def test_copy_image_to_volume(self, vmware_disk_type):
        self._test_copy_image_to_volume(vmware_disk_type=vmware_disk_type)

    @ddt.data('sparse', 'preallocated', 'streamOptimized')
    def test_copy_image_to_volume_with_extend_backing(self, vmware_disk_type):
        self._test_copy_image_to_volume(vmware_disk_type=vmware_disk_type,
                                        backing_disk_size=1,
                                        call_extend_backing=True)

    def test_copy_image_to_volume_with_ova_container(self):
        self._test_copy_image_to_volume(container_format='ova')

    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_disk_type')
    @mock.patch.object(VMDK_DRIVER, '_check_disk_conversion')
    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch.object(VMDK_DRIVER, '_create_backing')
    @mock.patch.object(VMDK_DRIVER, '_get_ds_name_folder_path')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_create_virtual_disk_from_sparse_image')
    @mock.patch.object(VMDK_DRIVER,
                       '_create_virtual_disk_from_preallocated_image')
    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile_id')
    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER, '_delete_temp_backing')
    def _test_create_volume_from_non_stream_optimized_image(
            self,
            delete_tmp_backing,
            select_ds_for_volume,
            get_storage_profile_id,
            create_disk_from_preallocated_image,
            create_disk_from_sparse_image,
            vops,
            get_ds_name_folder_path,
            create_backing,
            generate_uuid,
            check_disk_conversion,
            get_disk_type,
            image_disk_type='sparse',
            disk_conversion=False):

        disk_type = mock.sentinel.disk_type
        get_disk_type.return_value = disk_type
        check_disk_conversion.return_value = disk_conversion

        volume = self._create_volume_dict()
        if disk_conversion:
            disk_name = "6b77b25a-9136-470e-899e-3c930e570d8e"
            generate_uuid.return_value = disk_name
        else:
            disk_name = volume['name']

        backing = mock.sentinel.backing
        create_backing.return_value = backing

        ds_name = mock.sentinel.ds_name
        folder_path = mock.sentinel.folder_path
        get_ds_name_folder_path.return_value = (ds_name, folder_path)

        host = mock.sentinel.host
        dc_ref = mock.sentinel.dc_ref
        vops.get_host.return_value = host
        vops.get_dc.return_value = dc_ref

        vmdk_path = mock.Mock(spec=volumeops.FlatExtentVirtualDiskPath)
        create_disk_from_sparse_image.return_value = vmdk_path
        create_disk_from_preallocated_image.return_value = vmdk_path

        profile_id = mock.sentinel.profile_id
        get_storage_profile_id.return_value = profile_id

        if disk_conversion:
            rp = mock.sentinel.rp
            folder = mock.sentinel.folder
            datastore = mock.sentinel.datastore
            summary = mock.Mock(datastore=datastore)
            select_ds_for_volume.return_value = (host, rp, folder, summary)

            clone = mock.sentinel.clone
            vops.clone_backing.return_value = clone

        context = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        image_size_in_bytes = units.Gi
        adapter_type = mock.sentinel.adapter_type

        self._driver._create_volume_from_non_stream_optimized_image(
            context, volume, image_service, image_id, image_size_in_bytes,
            adapter_type, image_disk_type)

        check_disk_conversion.assert_called_once_with(image_disk_type,
                                                      mock.sentinel.disk_type)
        if disk_conversion:
            create_backing.assert_called_once_with(
                volume,
                create_params={vmdk.CREATE_PARAM_DISK_LESS: True,
                               vmdk.CREATE_PARAM_BACKING_NAME: disk_name})
        else:
            create_backing.assert_called_once_with(
                volume, create_params={vmdk.CREATE_PARAM_DISK_LESS: True})

        if image_disk_type == 'sparse':
            create_disk_from_sparse_image.assert_called_once_with(
                context, image_service, image_id, image_size_in_bytes,
                dc_ref, ds_name, folder_path, disk_name)
        else:
            create_disk_from_preallocated_image.assert_called_once_with(
                context, image_service, image_id, image_size_in_bytes,
                dc_ref, ds_name, folder_path, disk_name, adapter_type)

        get_storage_profile_id.assert_called_once_with(volume)
        vops.attach_disk_to_backing.assert_called_once_with(
            backing, image_size_in_bytes / units.Ki, disk_type,
            adapter_type, profile_id, vmdk_path.get_descriptor_ds_file_path())

        if disk_conversion:
            select_ds_for_volume.assert_called_once_with(volume)
            vops.clone_backing.assert_called_once_with(
                volume['name'], backing, None, volumeops.FULL_CLONE_TYPE,
                datastore, disk_type=disk_type, host=host, resource_pool=rp,
                folder=folder)
            delete_tmp_backing.assert_called_once_with(backing)
            vops.update_backing_disk_uuid(clone, volume['id'])
        else:
            vops.update_backing_disk_uuid(backing, volume['id'])

    @ddt.data('sparse', 'preallocated')
    def test_create_volume_from_non_stream_optimized_image(self,
                                                           image_disk_type):
        self._test_create_volume_from_non_stream_optimized_image(
            image_disk_type=image_disk_type)

    @ddt.data('sparse', 'preallocated')
    def test_create_volume_from_non_stream_opt_image_with_disk_conversion(
            self, image_disk_type):
        self._test_create_volume_from_non_stream_optimized_image(
            image_disk_type=image_disk_type, disk_conversion=True)

    @mock.patch.object(VMDK_DRIVER, '_copy_temp_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_get_temp_image_folder')
    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch(
        'cinder.volume.drivers.vmware.volumeops.FlatExtentVirtualDiskPath')
    @mock.patch.object(VMDK_DRIVER, '_copy_image')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_create_virtual_disk_from_preallocated_image(
            self, vops, copy_image, flat_extent_path, generate_uuid,
            get_temp_image_folder, copy_temp_virtual_disk):
        dc_ref = mock.Mock(value=mock.sentinel.dc_ref)
        ds_name = mock.sentinel.ds_name
        folder_path = mock.sentinel.folder_path
        get_temp_image_folder.return_value = (dc_ref, ds_name, folder_path)

        uuid = mock.sentinel.uuid
        generate_uuid.return_value = uuid
        path = mock.Mock()
        dest_path = mock.Mock()
        flat_extent_path.side_effect = [path, dest_path]

        context = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        image_size_in_bytes = 2 * units.Gi
        dest_dc_ref = mock.sentinel.dest_dc_ref
        dest_ds_name = mock.sentinel.dest_ds_name
        dest_folder_path = mock.sentinel.dest_folder_path
        dest_disk_name = mock.sentinel.dest_disk_name
        adapter_type = mock.sentinel.adapter_type
        ret = self._driver._create_virtual_disk_from_preallocated_image(
            context, image_service, image_id, image_size_in_bytes, dest_dc_ref,
            dest_ds_name, dest_folder_path, dest_disk_name, adapter_type)

        exp_flat_extent_path_calls = [
            mock.call(ds_name, folder_path, uuid),
            mock.call(dest_ds_name, dest_folder_path, dest_disk_name)]
        self.assertEqual(exp_flat_extent_path_calls,
                         flat_extent_path.call_args_list)
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
        dc_ref = mock.Mock(value=mock.sentinel.dc_ref)
        ds_name = mock.sentinel.ds_name
        folder_path = mock.sentinel.folder_path
        get_temp_image_folder.return_value = (dc_ref, ds_name, folder_path)

        path = mock.Mock()
        flat_extent_path.return_value = path

        context = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        image_size_in_bytes = 2 * units.Gi
        dest_dc_ref = mock.Mock(value=mock.sentinel.dc_ref)
        dest_ds_name = ds_name
        dest_folder_path = mock.sentinel.dest_folder_path
        dest_disk_name = mock.sentinel.dest_disk_name
        adapter_type = mock.sentinel.adapter_type
        ret = self._driver._create_virtual_disk_from_preallocated_image(
            context, image_service, image_id, image_size_in_bytes, dest_dc_ref,
            dest_ds_name, dest_folder_path, dest_disk_name, adapter_type)

        flat_extent_path.assert_called_once_with(
            dest_ds_name, dest_folder_path, dest_disk_name)
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
    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch(
        'cinder.volume.drivers.vmware.volumeops.FlatExtentVirtualDiskPath')
    @mock.patch.object(VMDK_DRIVER, '_copy_image')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_create_virtual_disk_from_preallocated_image_with_copy_error(
            self, vops, copy_image, flat_extent_path, generate_uuid,
            get_temp_image_folder, copy_temp_virtual_disk):
        dc_ref = mock.Mock(value=mock.sentinel.dc_ref)
        ds_name = mock.sentinel.ds_name
        folder_path = mock.sentinel.folder_path
        get_temp_image_folder.return_value = (dc_ref, ds_name, folder_path)

        uuid = mock.sentinel.uuid
        generate_uuid.return_value = uuid
        path = mock.Mock()
        dest_path = mock.Mock()
        flat_extent_path.side_effect = [path, dest_path]

        copy_image.side_effect = exceptions.VimException("error")

        context = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        image_size_in_bytes = 2 * units.Gi
        dest_dc_ref = mock.sentinel.dest_dc_ref
        dest_ds_name = mock.sentinel.dest_ds_name
        dest_folder_path = mock.sentinel.dest_folder_path
        dest_disk_name = mock.sentinel.dest_disk_name
        adapter_type = mock.sentinel.adapter_type
        self.assertRaises(
            exceptions.VimException,
            self._driver._create_virtual_disk_from_preallocated_image,
            context, image_service, image_id, image_size_in_bytes, dest_dc_ref,
            dest_ds_name, dest_folder_path, dest_disk_name, adapter_type)

        vops.delete_file.assert_called_once_with(
            path.get_descriptor_ds_file_path(), dc_ref)
        self.assertFalse(copy_temp_virtual_disk.called)

    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch(
        'cinder.volume.drivers.vmware.volumeops.'
        'MonolithicSparseVirtualDiskPath')
    @mock.patch(
        'cinder.volume.drivers.vmware.volumeops.FlatExtentVirtualDiskPath')
    @mock.patch.object(VMDK_DRIVER, '_copy_temp_virtual_disk')
    @mock.patch.object(VMDK_DRIVER, '_copy_image')
    def test_create_virtual_disk_from_sparse_image(
            self, copy_image, copy_temp_virtual_disk, flat_extent_path,
            sparse_path, generate_uuid):
        uuid = mock.sentinel.uuid
        generate_uuid.return_value = uuid

        src_path = mock.Mock()
        sparse_path.return_value = src_path

        dest_path = mock.Mock()
        flat_extent_path.return_value = dest_path

        context = mock.sentinel.context
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        image_size_in_bytes = 2 * units.Gi
        dc_ref = mock.sentinel.dc_ref
        ds_name = mock.sentinel.ds_name
        folder_path = mock.sentinel.folder_path
        disk_name = mock.sentinel.disk_name

        ret = self._driver._create_virtual_disk_from_sparse_image(
            context, image_service, image_id, image_size_in_bytes, dc_ref,
            ds_name, folder_path, disk_name)

        sparse_path.assert_called_once_with(ds_name, folder_path, uuid)
        copy_image.assert_called_once_with(
            context, dc_ref, image_service, image_id, image_size_in_bytes,
            ds_name, src_path.get_descriptor_file_path())
        flat_extent_path.assert_called_once_with(
            ds_name, folder_path, disk_name)
        copy_temp_virtual_disk.assert_called_once_with(
            dc_ref, src_path, dc_ref, dest_path)
        self.assertEqual(dest_path, ret)

    @mock.patch.object(VMDK_DRIVER, '_select_datastore')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_get_temp_image_folder(self, vops, select_datastore):
        host = mock.sentinel.host
        resource_pool = mock.sentinel.rp
        summary = mock.Mock()
        ds_name = mock.sentinel.ds_name
        summary.name = ds_name
        select_datastore.return_value = (host, resource_pool, summary)

        dc = mock.sentinel.dc
        vops.get_dc.return_value = dc

        image_size = 2 * units.Gi
        ret = self._driver._get_temp_image_folder(image_size)

        self.assertEqual((dc, ds_name, vmdk.TMP_IMAGES_DATASTORE_FOLDER_PATH),
                         ret)
        exp_req = {
            hub.DatastoreSelector.SIZE_BYTES: image_size,
            hub.DatastoreSelector.HARD_AFFINITY_DS_TYPE:
                {hub.DatastoreType.VMFS, hub.DatastoreType.NFS}}
        select_datastore.assert_called_once_with(exp_req)
        vops.create_datastore_folder.assert_called_once_with(
            ds_name, vmdk.TMP_IMAGES_DATASTORE_FOLDER_PATH, dc)

    @mock.patch.object(VMDK_DRIVER, '_select_ds_for_volume')
    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile_id')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_disk_type')
    @mock.patch.object(VMDK_DRIVER, '_get_extra_config')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch.object(image_transfer, 'download_stream_optimized_image')
    def _test_copy_image_to_volume_stream_optimized(self,
                                                    download_image,
                                                    session,
                                                    vops,
                                                    get_extra_config,
                                                    get_disk_type,
                                                    get_profile_id,
                                                    select_ds_for_volume,
                                                    download_error=False):
        host = mock.sentinel.host
        rp = mock.sentinel.rp
        folder = mock.sentinel.folder
        # NOTE(mriedem): The summary.name gets logged so it has to be a string
        summary = mock.Mock(name=six.text_type(mock.sentinel.ds_name))
        select_ds_for_volume.return_value = (host, rp, folder, summary)

        profile_id = mock.sentinel.profile_id
        get_profile_id.return_value = profile_id

        disk_type = mock.sentinel.disk_type
        get_disk_type.return_value = disk_type

        extra_config = mock.sentinel.extra_config
        get_extra_config.return_value = extra_config

        vm_create_spec = mock.sentinel.vm_create_spec
        vops.get_create_spec.return_value = vm_create_spec

        import_spec = mock.Mock()
        session.vim.client.factory.create.return_value = import_spec

        backing = mock.sentinel.backing
        if download_error:
            download_image.side_effect = exceptions.VimException
            vops.get_backing.return_value = backing
        else:
            download_image.return_value = backing

        context = mock.sentinel.context
        volume = self._create_volume_dict(size=3)
        image_service = mock.sentinel.image_service
        image_id = mock.sentinel.image_id
        image_size = 2 * units.Gi
        adapter_type = mock.sentinel.adapter_type

        if download_error:
            self.assertRaises(
                exceptions.VimException,
                self._driver._fetch_stream_optimized_image,
                context, volume, image_service, image_id,
                image_size, adapter_type)
        else:
            self._driver._fetch_stream_optimized_image(
                context, volume, image_service, image_id, image_size,
                adapter_type)

        select_ds_for_volume.assert_called_once_with(volume)
        vops.get_create_spec.assert_called_once_with(
            volume['name'], 0, disk_type, summary.name, profile_id=profile_id,
            adapter_type=adapter_type, extra_config=extra_config)
        self.assertEqual(vm_create_spec, import_spec.configSpec)
        download_image.assert_called_with(
            context,
            self._config.vmware_image_transfer_timeout_secs,
            image_service,
            image_id,
            session=session,
            host=self._config.vmware_host_ip,
            port=self._config.vmware_host_port,
            resource_pool=rp,
            vm_folder=folder,
            vm_import_spec=import_spec,
            image_size=image_size)
        if download_error:
            self.assertFalse(vops.update_backing_disk_uuid.called)
            vops.delete_backing.assert_called_once_with(backing)
        else:
            vops.update_backing_disk_uuid.assert_called_once_with(
                backing, volume['id'])

    def test_copy_image_to_volume_stream_optimized(self):
        self._test_copy_image_to_volume_stream_optimized()

    def test_copy_image_to_volume_stream_optimized_with_download_error(self):
        self._test_copy_image_to_volume_stream_optimized(download_error=True)

    @mock.patch.object(VMDK_DRIVER, '_in_use', return_value=True)
    def test_copy_volume_to_image_when_attached(self, in_use):
        volume = self._create_volume_dict(
            status="uploading",
            attachment=[mock.sentinel.attachment_1])
        self.assertRaises(
            cinder_exceptions.InvalidVolume,
            self._driver.copy_volume_to_image,
            mock.sentinel.context,
            volume,
            mock.sentinel.image_service,
            mock.sentinel.image_meta)
        in_use.assert_called_once_with(volume)

    @mock.patch.object(VMDK_DRIVER, '_validate_disk_format')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_create_backing')
    @mock.patch('oslo_vmware.image_transfer.upload_image')
    @mock.patch.object(VMDK_DRIVER, 'session')
    def _test_copy_volume_to_image(
            self, session, upload_image, create_backing, vops,
            validate_disk_format, backing_exists=True):
        backing = mock.sentinel.backing
        if backing_exists:
            vops.get_backing.return_value = backing
        else:
            vops.get_backing.return_value = None
            create_backing.return_value = backing

        vmdk_file_path = mock.sentinel.vmdk_file_path
        vops.get_vmdk_path.return_value = vmdk_file_path

        context = mock.sentinel.context
        volume = self._create_volume_dict()
        image_service = mock.sentinel.image_service
        image_meta = self._create_image_meta()
        self._driver.copy_volume_to_image(
            context, volume, image_service, image_meta)

        validate_disk_format.assert_called_once_with(image_meta['disk_format'])
        vops.get_backing.assert_called_once_with(volume['name'])
        if not backing_exists:
            create_backing.assert_called_once_with(volume)
        vops.get_vmdk_path.assert_called_once_with(backing)
        upload_image.assert_called_once_with(
            context,
            self._config.vmware_image_transfer_timeout_secs,
            image_service,
            image_meta['id'],
            volume['project_id'],
            session=session,
            host=self._config.vmware_host_ip,
            port=self._config.vmware_host_port,
            vm=backing,
            vmdk_file_path=vmdk_file_path,
            vmdk_size=volume['size'] * units.Gi,
            image_name=image_meta['name'],
            image_version=1)

    def test_copy_volume_to_image(self):
        self._test_copy_volume_to_image()

    def test_copy_volume_to_image_with_no_backing(self):
        self._test_copy_volume_to_image(backing_exists=False)

    def test_in_use(self):
        volume = self._create_volume_dict(
            attachment=[mock.sentinel.attachment_1])
        self.assertTrue(self._driver._in_use(volume))

    def test_in_use_with_available_volume(self):
        volume = self._create_volume_dict()
        self.assertFalse(self._driver._in_use(volume))

    @mock.patch.object(VMDK_DRIVER, '_in_use', return_value=True)
    def test_retype_with_in_use_volume(self, in_use):
        context = mock.sentinel.context
        volume = self._create_volume_dict(
            status='retyping', attachment=[mock.sentinel.attachment_1])
        new_type = mock.sentinel.new_type
        diff = mock.sentinel.diff
        host = mock.sentinel.host
        self.assertFalse(self._driver.retype(context, volume, new_type, diff,
                                             host))
        in_use.assert_called_once_with(volume)

    @mock.patch.object(VMDK_DRIVER, '_in_use', return_value=False)
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_retype_with_no_volume_backing(self, vops, in_use):
        vops.get_backing.return_value = None

        context = mock.sentinel.context
        volume = self._create_volume_dict(status='retyping')
        new_type = mock.sentinel.new_type
        diff = mock.sentinel.diff
        host = mock.sentinel.host
        self.assertTrue(self._driver.retype(context, volume, new_type, diff,
                                            host))

    @mock.patch.object(VMDK_DRIVER, '_in_use', return_value=False)
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_disk_type')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_extra_spec_disk_type')
    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, '_get_extra_spec_storage_profile')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    @mock.patch.object(VMDK_DRIVER, '_select_datastore')
    def test_retype_with_diff_profile_and_ds_compliance(
            self, select_datastore, ds_sel, get_extra_spec_storage_profile,
            get_storage_profile, get_extra_spec_disk_type, get_disk_type,
            vops, in_use):
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        datastore = mock.Mock(value='ds1')
        vops.get_datastore.return_value = datastore

        disk_type = mock.sentinel.disk_type
        get_disk_type.return_value = disk_type
        get_extra_spec_disk_type.return_value = disk_type

        self._driver._storage_policy_enabled = True
        profile = 'gold'
        get_storage_profile.return_value = profile
        new_profile = 'silver'
        get_extra_spec_storage_profile.return_value = new_profile

        ds_sel.is_datastore_compliant.return_value = True

        new_profile_id = mock.sentinel.new_profile_id
        ds_sel.get_profile_id.return_value = new_profile_id

        context = mock.sentinel.context
        volume = self._create_volume_dict(status='retyping')
        new_type = {'id': 'f04a65e0-d10c-4db7-b4a5-f933d57aa2b5'}
        diff = mock.sentinel.diff
        host = mock.sentinel.host
        self.assertTrue(self._driver.retype(context, volume, new_type, diff,
                                            host))
        ds_sel.is_datastore_compliant.assert_called_once_with(datastore,
                                                              new_profile)
        select_datastore.assert_not_called()
        vops.change_backing_profile.assert_called_once_with(backing,
                                                            new_profile_id)

    @mock.patch.object(VMDK_DRIVER, '_in_use', return_value=False)
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_disk_type')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_extra_spec_disk_type')
    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, '_get_extra_spec_storage_profile')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    @mock.patch.object(VMDK_DRIVER, '_select_datastore')
    def test_retype_with_diff_profile_and_ds_sel_no_candidate(
            self, select_datastore, ds_sel, get_extra_spec_storage_profile,
            get_storage_profile, get_extra_spec_disk_type, get_disk_type,
            vops, in_use):
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        datastore = mock.Mock(value='ds1')
        vops.get_datastore.return_value = datastore

        disk_type = mock.sentinel.disk_type
        get_disk_type.return_value = disk_type
        get_extra_spec_disk_type.return_value = disk_type

        vops.snapshot_exists.return_value = False

        self._driver._storage_policy_enabled = True
        profile = 'gold'
        get_storage_profile.return_value = profile
        new_profile = 'silver'
        get_extra_spec_storage_profile.return_value = new_profile

        ds_sel.is_datastore_compliant.return_value = False
        select_datastore.side_effect = (
            vmdk_exceptions.NoValidDatastoreException)

        context = mock.sentinel.context
        volume = self._create_volume_dict(status='retyping')
        new_type = {'id': 'f04a65e0-d10c-4db7-b4a5-f933d57aa2b5'}
        diff = mock.sentinel.diff
        host = mock.sentinel.host
        self.assertFalse(self._driver.retype(context, volume, new_type, diff,
                                             host))
        ds_sel.is_datastore_compliant.assert_called_once_with(datastore,
                                                              new_profile)
        select_datastore.assert_called_once_with(
            {hub.DatastoreSelector.SIZE_BYTES: volume['size'] * units.Gi,
             hub.DatastoreSelector.PROFILE_NAME: new_profile})

    @mock.patch.object(VMDK_DRIVER, '_in_use', return_value=False)
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_disk_type')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_extra_spec_disk_type')
    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, '_get_extra_spec_storage_profile')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    @mock.patch.object(VMDK_DRIVER, '_select_datastore')
    @mock.patch.object(VMDK_DRIVER, '_get_volume_group_folder')
    def test_retype_with_diff_extra_spec_and_vol_snapshot(
            self,
            get_volume_group_folder,
            select_datastore,
            ds_sel, get_extra_spec_storage_profile,
            get_storage_profile,
            get_extra_spec_disk_type,
            get_disk_type,
            vops,
            in_use):
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        datastore = mock.Mock(value='ds1')
        vops.get_datastore.return_value = datastore

        get_disk_type.return_value = 'thin'
        new_disk_type = 'thick'
        get_extra_spec_disk_type.return_value = new_disk_type

        vops.snapshot_exists.return_value = True

        self._driver._storage_policy_enabled = True
        profile = 'gold'
        get_storage_profile.return_value = profile
        new_profile = 'silver'
        get_extra_spec_storage_profile.return_value = new_profile

        ds_sel.is_datastore_compliant.return_value = False
        host = mock.sentinel.host
        rp = mock.sentinel.rp
        new_datastore = mock.Mock(value='ds2')
        summary = mock.Mock(datastore=new_datastore)
        select_datastore.return_value = (host, rp, summary)

        folder = mock.sentinel.folder
        get_volume_group_folder.return_value = folder

        new_profile_id = mock.sentinel.new_profile_id
        ds_sel.get_profile_id.return_value = new_profile_id

        context = mock.sentinel.context
        volume = self._create_volume_dict(status='retyping')
        new_type = {'id': 'f04a65e0-d10c-4db7-b4a5-f933d57aa2b5'}
        diff = mock.sentinel.diff
        host = mock.sentinel.host
        self.assertTrue(self._driver.retype(context, volume, new_type, diff,
                                            host))
        ds_sel.is_datastore_compliant.assert_called_once_with(datastore,
                                                              new_profile)
        select_datastore.assert_called_once_with(
            {hub.DatastoreSelector.SIZE_BYTES: volume['size'] * units.Gi,
             hub.DatastoreSelector.HARD_ANTI_AFFINITY_DS: ['ds1'],
             hub.DatastoreSelector.PROFILE_NAME: new_profile})
        vops.relocate_backing.assert_called_once_with(
            backing, new_datastore, rp, host, new_disk_type)
        vops.move_backing_to_folder.assert_called_once_with(backing, folder)
        vops.change_backing_profile.assert_called_once_with(backing,
                                                            new_profile_id)

    @mock.patch.object(VMDK_DRIVER, '_in_use', return_value=False)
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_disk_type')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_extra_spec_disk_type')
    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, '_get_extra_spec_storage_profile')
    @mock.patch.object(VMDK_DRIVER, 'ds_sel')
    @mock.patch.object(VMDK_DRIVER, '_select_datastore')
    @mock.patch.object(VMDK_DRIVER, '_get_volume_group_folder')
    @mock.patch('oslo_utils.uuidutils.generate_uuid')
    @mock.patch.object(VMDK_DRIVER, '_delete_temp_backing')
    def _test_retype_with_diff_extra_spec_and_ds_compliance(
            self,
            delete_temp_backing,
            generate_uuid,
            get_volume_group_folder,
            select_datastore,
            ds_sel,
            get_extra_spec_storage_profile,
            get_storage_profile,
            get_extra_spec_disk_type,
            get_disk_type,
            vops,
            in_use,
            clone_error=False):
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        datastore = mock.Mock(value='ds1')
        vops.get_datastore.return_value = datastore

        get_disk_type.return_value = 'thin'
        new_disk_type = 'thick'
        get_extra_spec_disk_type.return_value = new_disk_type

        vops.snapshot_exists.return_value = False

        self._driver._storage_policy_enabled = True
        profile = 'gold'
        get_storage_profile.return_value = profile
        new_profile = 'silver'
        get_extra_spec_storage_profile.return_value = new_profile

        ds_sel.is_datastore_compliant.return_value = True
        host = mock.sentinel.host
        rp = mock.sentinel.rp
        summary = mock.Mock(datastore=datastore)
        select_datastore.return_value = (host, rp, summary)

        folder = mock.sentinel.folder
        get_volume_group_folder.return_value = folder

        new_profile_id = mock.sentinel.new_profile_id
        ds_sel.get_profile_id.return_value = new_profile_id

        uuid = '025b654b-d4ed-47f9-8014-b71a7744eafc'
        generate_uuid.return_value = uuid

        if clone_error:
            vops.clone_backing.side_effect = exceptions.VimException
        else:
            new_backing = mock.sentinel.new_backing
            vops.clone_backing.return_value = new_backing

        context = mock.sentinel.context
        volume = self._create_volume_dict(status='retyping')
        new_type = {'id': 'f04a65e0-d10c-4db7-b4a5-f933d57aa2b5'}
        diff = mock.sentinel.diff
        host = mock.sentinel.host
        if clone_error:
            self.assertRaises(exceptions.VimException, self._driver.retype,
                              context, volume, new_type, diff, host)
        else:
            self.assertTrue(self._driver.retype(context, volume, new_type,
                                                diff, host))
        ds_sel.is_datastore_compliant.assert_called_once_with(datastore,
                                                              new_profile)
        select_datastore.assert_called_once_with(
            {hub.DatastoreSelector.SIZE_BYTES: volume['size'] * units.Gi,
             hub.DatastoreSelector.PROFILE_NAME: new_profile})
        vops.clone_backing.assert_called_once_with(
            volume['name'], backing, None, volumeops.FULL_CLONE_TYPE,
            datastore, disk_type=new_disk_type, host=host, resource_pool=rp,
            folder=folder)
        if clone_error:
            exp_rename_calls = [mock.call(backing, uuid),
                                mock.call(backing, volume['name'])]
            self.assertEqual(exp_rename_calls,
                             vops.rename_backing.call_args_list)
        else:
            vops.rename_backing.assert_called_once_with(backing, uuid)
            vops.update_backing_disk_uuid.assert_called_once_with(
                new_backing, volume['id'])
            delete_temp_backing.assert_called_once_with(backing)
            vops.change_backing_profile.assert_called_once_with(new_backing,
                                                                new_profile_id)

    def test_retype_with_diff_extra_spec_and_ds_compliance(self):
        self._test_retype_with_diff_extra_spec_and_ds_compliance()

    def test_retype_with_diff_extra_spec_ds_compliance_and_clone_error(self):
        self._test_retype_with_diff_extra_spec_and_ds_compliance(
            clone_error=True)

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
                                  mock.sentinel.folder, summary)

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
            summary.datastore, disk_type=disk_type, host=mock.sentinel.host,
            resource_pool=mock.sentinel.rp, folder=mock.sentinel.folder)
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
            summary.datastore, disk_type=disk_type, host=mock.sentinel.host,
            resource_pool=mock.sentinel.rp, folder=mock.sentinel.folder)
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
            context, self._config.vmware_image_transfer_timeout_secs, tmp_file,
            session=session, host=self._config.vmware_host_ip,
            port=self._config.vmware_host_port, resource_pool=rp,
            vm_folder=folder, vm_import_spec=import_spec,
            image_size=file_size_bytes)

        download_data.side_effect = exceptions.VimException("error")
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing
        self.assertRaises(
            exceptions.VimException,
            self._driver._create_backing_from_stream_optimized_file,
            context, name, volume, tmp_file_path, file_size_bytes)
        delete_temp_backing.assert_called_once_with(backing)

    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch('oslo_vmware.vim_util.get_vc_version')
    def test_get_vc_version(self, get_vc_version, session):
        self._driver.configuration.vmware_host_version = None

        version_str = '6.0.0'
        get_vc_version.return_value = version_str

        version = self._driver._get_vc_version()

        self.assertEqual(ver.LooseVersion(version_str), version)
        get_vc_version.assert_called_once_with(session)

    @mock.patch('oslo_vmware.vim_util.get_vc_version')
    def test_get_vc_version_override(self, get_vc_version):
        version = self._driver._get_vc_version()

        self.assertEqual(
            ver.LooseVersion(self._driver.configuration.vmware_host_version),
            version)
        get_vc_version.assert_not_called()

    @mock.patch('cinder.volume.drivers.vmware.vmdk.LOG')
    @ddt.data('5.1', '5.5')
    def test_validate_vcenter_version(self, version, log):
        # vCenter versions 5.1 and above should pass validation.
        self._driver._validate_vcenter_version(ver.LooseVersion(version))
        # Deprecation warning should be logged for vCenter version 5.1.
        if version == '5.1':
            log.warning.assert_called_once()
        else:
            log.warning.assert_not_called()

    def test_validate_vcenter_version_with_less_than_min_supported_version(
            self):
        vc_version = ver.LooseVersion('5.0')
        # Validation should fail for vCenter version less than 5.1.
        self.assertRaises(exceptions.VMwareDriverException,
                          self._driver._validate_vcenter_version,
                          vc_version)

    @mock.patch.object(VMDK_DRIVER, '_validate_params')
    @mock.patch.object(VMDK_DRIVER, '_get_vc_version')
    @mock.patch.object(VMDK_DRIVER, '_validate_vcenter_version')
    @mock.patch('oslo_vmware.pbm.get_pbm_wsdl_location')
    @mock.patch('cinder.volume.drivers.vmware.volumeops.VMwareVolumeOps')
    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, 'session')
    def _test_do_setup(
            self, session, vops, ds_sel_cls, vops_cls, get_pbm_wsdl_loc,
            validate_vc_version, get_vc_version, validate_params,
            enable_pbm=True):
        if enable_pbm:
            ver_str = '5.5'
            pbm_wsdl = mock.sentinel.pbm_wsdl
            get_pbm_wsdl_loc.return_value = pbm_wsdl
        else:
            ver_str = '5.1'
        vc_version = ver.LooseVersion(ver_str)
        get_vc_version.return_value = vc_version

        cls_1 = mock.sentinel.cls_1
        cls_2 = mock.sentinel.cls_2
        cluster_refs = {'cls-1': cls_1, 'cls-2': cls_2}
        vops.get_cluster_refs.return_value = cluster_refs

        self._driver.do_setup(mock.ANY)

        validate_params.assert_called_once_with()
        get_vc_version.assert_called_once_with()
        validate_vc_version.assert_called_once_with(vc_version)
        if enable_pbm:
            get_pbm_wsdl_loc.assert_called_once_with(ver_str)
            self.assertEqual(pbm_wsdl, self._driver.pbm_wsdl)
        self.assertEqual(enable_pbm, self._driver._storage_policy_enabled)
        vops_cls.assert_called_once_with(
            session, self._driver.configuration.vmware_max_objects_retrieval)
        self.assertEqual(vops_cls.return_value, self._driver._volumeops)
        ds_sel_cls.assert_called_once_with(
            vops,
            session,
            self._driver.configuration.vmware_max_objects_retrieval)
        self.assertEqual(ds_sel_cls.return_value, self._driver._ds_sel)
        vops.get_cluster_refs.assert_called_once_with(
            self._driver.configuration.vmware_cluster_name)
        self.assertEqual(list(cluster_refs.values()),
                         list(self._driver._clusters))

    def test_do_setup(self):
        self._test_do_setup()

    def test_do_setup_with_pbm_disabled(self):
        self._test_do_setup(enable_pbm=False)

    @mock.patch.object(VMDK_DRIVER, '_validate_params')
    @mock.patch.object(VMDK_DRIVER, '_get_vc_version')
    @mock.patch.object(VMDK_DRIVER, '_validate_vcenter_version')
    @mock.patch('oslo_vmware.pbm.get_pbm_wsdl_location')
    def test_do_setup_with_invalid_pbm_wsdl(
            self, get_pbm_wsdl_loc, validate_vc_version, get_vc_version,
            validate_params):
        ver_str = '5.5'
        vc_version = ver.LooseVersion(ver_str)
        get_vc_version.return_value = vc_version

        get_pbm_wsdl_loc.return_value = None

        self.assertRaises(exceptions.VMwareDriverException,
                          self._driver.do_setup,
                          mock.ANY)

        validate_params.assert_called_once_with()
        get_vc_version.assert_called_once_with()
        validate_vc_version.assert_called_once_with(vc_version)
        get_pbm_wsdl_loc.assert_called_once_with(ver_str)

    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, '_select_datastore')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_get_volume_group_folder')
    @ddt.data(None, {vmdk.CREATE_PARAM_DISK_SIZE: 2 * VOL_SIZE})
    def test_select_ds_for_volume(
            self, create_params, get_volume_group_folder, vops,
            select_datastore, get_storage_profile):

        profile = mock.sentinel.profile
        get_storage_profile.return_value = profile

        host = mock.sentinel.host
        rp = mock.sentinel.rp
        summary = mock.sentinel.summary
        select_datastore.return_value = (host, rp, summary)

        dc = mock.sentinel.dc
        vops.get_dc.return_value = dc

        folder = mock.sentinel.folder
        get_volume_group_folder.return_value = folder

        vol = self._create_volume_dict()
        ret = self._driver._select_ds_for_volume(
            vol, host=host, create_params=create_params)

        self.assertEqual((host, rp, folder, summary), ret)
        if create_params:
            exp_size = create_params[vmdk.CREATE_PARAM_DISK_SIZE] * units.Gi
        else:
            exp_size = vol['size'] * units.Gi
        exp_req = {hub.DatastoreSelector.SIZE_BYTES: exp_size,
                   hub.DatastoreSelector.PROFILE_NAME: profile}
        select_datastore.assert_called_once_with(exp_req, host)
        vops.get_dc.assert_called_once_with(rp)
        get_volume_group_folder.assert_called_once_with(dc, vol['project_id'])

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def _test_get_connection_info(self, vops, vmdk_connector=False):
        volume = self._create_volume_obj()
        backing = mock.Mock(value='ref-1')
        if vmdk_connector:
            vmdk_path = mock.sentinel.vmdk_path
            vops.get_vmdk_path.return_value = vmdk_path

            datastore = mock.Mock(value='ds-1')
            vops.get_datastore.return_value = datastore

            datacenter = mock.Mock(value='dc-1')
            vops.get_dc.return_value = datacenter

            connector = {'platform': mock.sentinel.platform,
                         'os_type': mock.sentinel.os_type}
        else:
            connector = {'instance': 'vm-1'}
        ret = self._driver._get_connection_info(volume, backing, connector)

        self.assertEqual('vmdk', ret['driver_volume_type'])
        self.assertEqual('ref-1', ret['data']['volume'])
        self.assertEqual(volume.id, ret['data']['volume_id'])
        self.assertEqual(volume.name, ret['data']['name'])

        if vmdk_connector:
            self.assertEqual(volume.size * units.Gi, ret['data']['vmdk_size'])
            self.assertEqual(vmdk_path, ret['data']['vmdk_path'])
            self.assertEqual('ds-1', ret['data']['datastore'])
            self.assertEqual('dc-1', ret['data']['datacenter'])

            config = self._driver.configuration
            exp_config = {
                'vmware_host_ip': config.vmware_host_ip,
                'vmware_host_port': config.vmware_host_port,
                'vmware_host_username': config.vmware_host_username,
                'vmware_host_password': config.vmware_host_password,
                'vmware_api_retry_count': config.vmware_api_retry_count,
                'vmware_task_poll_interval': config.vmware_task_poll_interval,
                'vmware_ca_file': config.vmware_ca_file,
                'vmware_insecure': config.vmware_insecure,
                'vmware_tmp_dir': config.vmware_tmp_dir,
                'vmware_image_transfer_timeout_secs':
                    config.vmware_image_transfer_timeout_secs,
            }
            self.assertEqual(exp_config, ret['data']['config'])

    def test_get_connection_info(self):
        self._test_get_connection_info()

    def test_get_connection_info_vmdk_connector(self):
        self._test_get_connection_info(vmdk_connector=True)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch('oslo_vmware.vim_util.get_moref')
    @mock.patch.object(VMDK_DRIVER, '_create_backing')
    @mock.patch.object(VMDK_DRIVER, '_relocate_backing')
    @mock.patch.object(VMDK_DRIVER, '_get_connection_info')
    def _test_initialize_connection(
            self, get_connection_info, relocate_backing, create_backing,
            get_moref, vops, backing_exists=True, instance_exists=True):

        backing_val = mock.sentinel.backing_val
        backing = mock.Mock(value=backing_val)
        if backing_exists:
            vops.get_backing.return_value = backing
        else:
            vops.get_backing.return_value = None
            create_backing.return_value = backing

        if instance_exists:
            instance_val = mock.sentinel.instance_val
            connector = {'instance': instance_val}

            instance_moref = mock.sentinel.instance_moref
            get_moref.return_value = instance_moref

            host = mock.sentinel.host
            vops.get_host.return_value = host
        else:
            connector = {}

        conn_info = mock.sentinel.conn_info
        get_connection_info.return_value = conn_info

        volume = self._create_volume_obj()
        ret = self._driver.initialize_connection(volume, connector)

        self.assertEqual(conn_info, ret)
        if instance_exists:
            vops.get_host.assert_called_once_with(instance_moref)
            if backing_exists:
                relocate_backing.assert_called_once_with(volume, backing, host)
                create_backing.assert_not_called()
            else:
                create_backing.assert_called_once_with(volume, host)
                relocate_backing.assert_not_called()
        elif not backing_exists:
            create_backing.assert_called_once_with(volume)
            relocate_backing.assert_not_called()
        else:
            create_backing.assert_not_called()
            relocate_backing.assert_not_called()
        get_connection_info.assert_called_once_with(volume, backing, connector)

    def test_initialize_connection_with_instance_and_backing(self):
        self._test_initialize_connection()

    def test_initialize_connection_with_instance_and_no_backing(self):
        self._test_initialize_connection(backing_exists=False)

    def test_initialize_connection_with_no_instance_and_no_backing(self):
        self._test_initialize_connection(
            backing_exists=False, instance_exists=False)

    def test_initialize_connection_with_no_instance_and_backing(self):
        self._test_initialize_connection(instance_exists=False)

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

    @mock.patch('cinder.volume.drivers.vmware.vmdk.'
                '_get_volume_type_extra_spec')
    @ddt.data('full', 'linked')
    def test_get_clone_type(self, clone_type, get_volume_type_extra_spec):
        get_volume_type_extra_spec.return_value = clone_type

        volume = self._create_volume_dict()
        self.assertEqual(clone_type, self._driver._get_clone_type(volume))
        get_volume_type_extra_spec.assert_called_once_with(
            volume['volume_type_id'], 'clone_type',
            default_value=volumeops.FULL_CLONE_TYPE)

    @mock.patch('cinder.volume.drivers.vmware.vmdk.'
                '_get_volume_type_extra_spec')
    def test_get_clone_type_invalid(
            self, get_volume_type_extra_spec):
        get_volume_type_extra_spec.return_value = 'foo'

        volume = self._create_volume_dict()
        self.assertRaises(
            cinder_exceptions.Invalid, self._driver._get_clone_type, volume)
        get_volume_type_extra_spec.assert_called_once_with(
            volume['volume_type_id'], 'clone_type',
            default_value=volumeops.FULL_CLONE_TYPE)

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
                                                    extra_config=extra_config,
                                                    folder=None)
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
        volume_ops.clone_backing.assert_called_with(
            fake_volume['name'],
            fake_backing,
            fake_snapshot,
            volumeops.FULL_CLONE_TYPE,
            fake_datastore,
            host=fake_host,
            resource_pool=fake_resource_pool,
            extra_config=extra_config,
            folder=fake_folder)
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

    @mock.patch('cinder.volume.drivers.vmware.vmdk.'
                '_get_volume_type_extra_spec')
    def test_get_extra_spec_storage_profile(self, get_volume_type_extra_spec):
        vol_type_id = mock.sentinel.vol_type_id
        self._driver._get_extra_spec_storage_profile(vol_type_id)
        get_volume_type_extra_spec.assert_called_once_with(vol_type_id,
                                                           'storage_profile')

    @mock.patch.object(VMDK_DRIVER, '_get_extra_spec_storage_profile')
    def test_get_storage_profile(self, get_extra_spec_storage_profile):
        volume = self._create_volume_dict()
        self._driver._get_storage_profile(volume)
        get_extra_spec_storage_profile.assert_called_once_with(
            volume['volume_type_id'])

    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch('oslo_vmware.pbm.get_profile_id_by_name')
    def test_get_storage_profile_id(
            self, get_profile_id_by_name, session, get_storage_profile):
        get_storage_profile.return_value = 'gold'
        profile_id = mock.sentinel.profile_id
        get_profile_id_by_name.return_value = mock.Mock(uniqueId=profile_id)

        self._driver._storage_policy_enabled = True
        volume = self._create_volume_dict()
        self.assertEqual(profile_id,
                         self._driver._get_storage_profile_id(volume))
        get_storage_profile.assert_called_once_with(volume)
        get_profile_id_by_name.assert_called_once_with(session, 'gold')

    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch('oslo_vmware.pbm.get_profile_id_by_name')
    def test_get_storage_profile_id_with_missing_extra_spec(
            self, get_profile_id_by_name, session, get_storage_profile):
        get_storage_profile.return_value = None

        self._driver._storage_policy_enabled = True
        volume = self._create_volume_dict()
        self.assertIsNone(self._driver._get_storage_profile_id(volume))
        get_storage_profile.assert_called_once_with(volume)
        self.assertFalse(get_profile_id_by_name.called)

    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch('oslo_vmware.pbm.get_profile_id_by_name')
    def test_get_storage_profile_id_with_pbm_disabled(
            self, get_profile_id_by_name, session, get_storage_profile):
        get_storage_profile.return_value = 'gold'

        volume = self._create_volume_dict()
        self.assertIsNone(self._driver._get_storage_profile_id(volume))
        get_storage_profile.assert_called_once_with(volume)
        self.assertFalse(get_profile_id_by_name.called)

    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch('oslo_vmware.pbm.get_profile_id_by_name')
    def test_get_storage_profile_id_with_missing_profile(
            self, get_profile_id_by_name, session, get_storage_profile):
        get_storage_profile.return_value = 'gold'
        get_profile_id_by_name.return_value = None

        self._driver._storage_policy_enabled = True
        volume = self._create_volume_dict()
        self.assertIsNone(self._driver._get_storage_profile_id(volume))
        get_storage_profile.assert_called_once_with(volume)
        get_profile_id_by_name.assert_called_once_with(session, 'gold')

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
            context,
            self._config.vmware_image_transfer_timeout_secs,
            image_service,
            image_id,
            image_size=image_size_in_bytes,
            host=self._config.vmware_host_ip,
            port=self._config.vmware_host_port,
            data_center_name=dc_name,
            datastore_name=ds_name,
            cookies=cookies,
            file_path=upload_file_path,
            cacerts=expected_cacerts)

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

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_get_disk_device(self, vops):
        vm = mock.sentinel.vm
        vops.get_entity_by_inventory_path.return_value = vm

        dev = mock.sentinel.dev
        vops.get_disk_device.return_value = dev

        vm_inv_path = mock.sentinel.vm_inv_path
        vmdk_path = mock.sentinel.vmdk_path
        ret = self._driver._get_disk_device(vmdk_path, vm_inv_path)

        self.assertEqual((vm, dev), ret)
        vops.get_entity_by_inventory_path.assert_called_once_with(vm_inv_path)
        vops.get_disk_device.assert_called_once_with(vm, vmdk_path)

    def test_get_existing_with_empty_source_name(self):
        self.assertRaises(cinder_exceptions.InvalidInput,
                          self._driver._get_existing,
                          {})

    def test_get_existing_with_invalid_source_name(self):
        self.assertRaises(cinder_exceptions.InvalidInput,
                          self._driver._get_existing,
                          {'source-name': 'foo'})

    @mock.patch.object(VMDK_DRIVER, '_get_disk_device', return_value=None)
    def test_get_existing_with_invalid_existing_ref(self, get_disk_device):
        self.assertRaises(cinder_exceptions.ManageExistingInvalidReference,
                          self._driver._get_existing,
                          {'source-name': '[ds1] foo/foo.vmdk@/dc-1/vm/foo'})
        get_disk_device.assert_called_once_with('[ds1] foo/foo.vmdk',
                                                '/dc-1/vm/foo')

    @mock.patch.object(VMDK_DRIVER, '_get_disk_device')
    def test_get_existing(self, get_disk_device):
        vm = mock.sentinel.vm
        disk_device = mock.sentinel.disk_device
        get_disk_device.return_value = (vm, disk_device)
        self.assertEqual(
            (vm, disk_device),
            self._driver._get_existing({'source-name':
                                        '[ds1] foo/foo.vmdk@/dc-1/vm/foo'}))
        get_disk_device.assert_called_once_with('[ds1] foo/foo.vmdk',
                                                '/dc-1/vm/foo')

    @mock.patch.object(VMDK_DRIVER, '_get_existing')
    @ddt.data((16384, 1), (1048576, 1), (1572864, 2))
    def test_manage_existing_get_size(self, test_data, get_existing):
        (capacity_kb, exp_size) = test_data
        disk_device = mock.Mock(capacityInKB=capacity_kb)
        get_existing.return_value = (mock.sentinel.vm, disk_device)

        volume = mock.sentinel.volume
        existing_ref = mock.sentinel.existing_ref
        self.assertEqual(exp_size,
                         self._driver.manage_existing_get_size(volume,
                                                               existing_ref))
        get_existing.assert_called_once_with(existing_ref)

    @mock.patch.object(VMDK_DRIVER, '_get_existing')
    @mock.patch.object(VMDK_DRIVER, '_create_backing')
    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_get_ds_name_folder_path')
    @mock.patch.object(VMDK_DRIVER, '_get_storage_profile_id')
    @mock.patch('cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver.'
                '_get_disk_type')
    def test_manage_existing(
            self, get_disk_type, get_storage_profile_id,
            get_ds_name_folder_path, vops, create_backing, get_existing):

        vm = mock.sentinel.vm
        src_path = mock.sentinel.src_path
        disk_backing = mock.Mock(fileName=src_path)
        disk_device = mock.Mock(backing=disk_backing, capacityInKB=1048576)
        get_existing.return_value = (vm, disk_device)

        backing = mock.sentinel.backing
        create_backing.return_value = backing

        src_dc = mock.sentinel.src_dc
        dest_dc = mock.sentinel.dest_dc
        vops.get_dc.side_effect = [src_dc, dest_dc]

        volume = self._create_volume_dict()
        ds_name = "ds1"
        folder_path = "%s/" % volume['name']
        get_ds_name_folder_path.return_value = (ds_name, folder_path)

        profile_id = mock.sentinel.profile_id
        get_storage_profile_id.return_value = profile_id

        disk_type = mock.sentinel.disk_type
        get_disk_type.return_value = disk_type

        existing_ref = mock.sentinel.existing_ref
        self._driver.manage_existing(volume, existing_ref)

        get_existing.assert_called_once_with(existing_ref)
        create_backing.assert_called_once_with(
            volume, create_params={vmdk.CREATE_PARAM_DISK_LESS: True})
        vops.detach_disk_from_backing.assert_called_once_with(vm, disk_device)
        dest_path = "[%s] %s%s.vmdk" % (ds_name, folder_path, volume['name'])
        vops.move_vmdk_file.assert_called_once_with(
            src_dc, src_path, dest_path, dest_dc_ref=dest_dc)
        get_storage_profile_id.assert_called_once_with(volume)
        vops.attach_disk_to_backing.assert_called_once_with(
            backing, disk_device.capacityInKB, disk_type, 'lsiLogic',
            profile_id, dest_path)
        vops.update_backing_disk_uuid.assert_called_once_with(backing,
                                                              volume['id'])

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    def test_unmanage(self, vops):
        backing = mock.sentinel.backing
        vops.get_backing.return_value = backing

        volume = self._create_volume_dict()
        self._driver.unmanage(volume)

        vops.get_backing.assert_called_once_with(volume['name'])
        vops.update_backing_extra_config.assert_called_once_with(
            backing, {vmdk.EXTRA_CONFIG_VOLUME_ID_KEY: ''})

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
            port=self._config.vmware_host_port,
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
