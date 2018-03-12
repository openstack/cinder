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
Test suite for VMware vCenter FCD driver.
"""

import ddt
import mock
from oslo_utils import units
from oslo_vmware import image_transfer
from oslo_vmware.objects import datastore
from oslo_vmware import vim_util

from cinder import context
from cinder import exception as cinder_exceptions
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume import configuration
from cinder.volume.drivers.vmware import datastore as hub
from cinder.volume.drivers.vmware import fcd
from cinder.volume.drivers.vmware import vmdk
from cinder.volume.drivers.vmware import volumeops


@ddt.ddt
class VMwareVStorageObjectDriverTestCase(test.TestCase):

    IP = 'localhost'
    PORT = 2321
    IMG_TX_TIMEOUT = 10
    VMDK_DRIVER = vmdk.VMwareVcVmdkDriver
    FCD_DRIVER = fcd.VMwareVStorageObjectDriver

    VOL_ID = 'abcdefab-cdef-abcd-efab-cdefabcdefab'
    DISPLAY_NAME = 'foo'
    VOL_TYPE_ID = 'd61b8cb3-aa1b-4c9b-b79e-abcdbda8b58a'
    VOL_SIZE = 2
    PROJECT_ID = 'd45beabe-f5de-47b7-b462-0d9ea02889bc'
    IMAGE_ID = 'eb87f4b0-d625-47f8-bb45-71c43b486d3a'
    IMAGE_NAME = 'image-1'

    def setUp(self):
        super(VMwareVStorageObjectDriverTestCase, self).setUp()

        self._config = mock.Mock(spec=configuration.Configuration)
        self._config.vmware_host_ip = self.IP
        self._config.vmware_host_port = self.PORT
        self._config.vmware_image_transfer_timeout_secs = self.IMG_TX_TIMEOUT
        self._driver = fcd.VMwareVStorageObjectDriver(
            configuration=self._config)
        self._context = context.get_admin_context()

    @mock.patch.object(VMDK_DRIVER, 'do_setup')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    def test_do_setup(self, vops, vmdk_do_setup):
        self._driver.do_setup(self._context)
        vmdk_do_setup.assert_called_once_with(self._context)
        self.assertFalse(self._driver._storage_policy_enabled)
        vops.set_vmx_version.assert_called_once_with('vmx-13')

    def test_get_volume_stats(self):
        stats = self._driver.get_volume_stats()

        self.assertEqual('VMware', stats['vendor_name'])
        self.assertEqual(self._driver.VERSION, stats['driver_version'])
        self.assertEqual(self._driver.STORAGE_TYPE, stats['storage_protocol'])
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

    @mock.patch.object(FCD_DRIVER, '_select_datastore')
    def test_select_ds_fcd(self, select_datastore):
        datastore = mock.sentinel.datastore
        summary = mock.Mock(datastore=datastore)
        select_datastore.return_value = (mock.ANY, mock.ANY, summary)

        volume = self._create_volume_obj()
        ret = self._driver._select_ds_fcd(volume)
        self.assertEqual(datastore, ret)
        exp_req = {hub.DatastoreSelector.SIZE_BYTES: volume.size * units.Gi}
        select_datastore.assert_called_once_with(exp_req)

    @mock.patch.object(FCD_DRIVER, '_select_datastore')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    def _test_get_temp_image_folder(
            self, vops, select_datastore, preallocated=False):
        host = mock.sentinel.host
        summary = mock.Mock()
        summary.name = 'ds-1'
        select_datastore.return_value = (host, mock.ANY, summary)

        dc_ref = mock.sentinel.dc_ref
        vops.get_dc.return_value = dc_ref

        size_bytes = units.Gi
        ret = self._driver._get_temp_image_folder(size_bytes, preallocated)
        self.assertEqual(
            (dc_ref, summary, vmdk.TMP_IMAGES_DATASTORE_FOLDER_PATH), ret)
        exp_req = {hub.DatastoreSelector.SIZE_BYTES: size_bytes}
        if preallocated:
            exp_req[hub.DatastoreSelector.HARD_AFFINITY_DS_TYPE] = (
                {hub.DatastoreType.NFS,
                 hub.DatastoreType.VMFS,
                 hub.DatastoreType.NFS41})
        select_datastore.assert_called_once_with(exp_req)
        vops.get_dc.assert_called_once_with(host)
        vops.create_datastore_folder.assert_called_once_with(
            summary.name, vmdk.TMP_IMAGES_DATASTORE_FOLDER_PATH, dc_ref)

    def test_get_temp_image_folder(self):
        self._test_get_temp_image_folder()

    def test_get_temp_image_folder_preallocated(self):
        self._test_get_temp_image_folder(preallocated=True)

    @mock.patch.object(VMDK_DRIVER, '_get_disk_type')
    @ddt.data(('eagerZeroedThick', 'eagerZeroedThick'),
              ('thick', 'preallocated'),
              ('thin', 'thin'))
    @ddt.unpack
    def test_get_disk_type(
            self, extra_spec_disk_type, exp_ret_val, vmdk_get_disk_type):
        vmdk_get_disk_type.return_value = extra_spec_disk_type

        volume = mock.sentinel.volume
        ret = self._driver._get_disk_type(volume)
        self.assertEqual(exp_ret_val, ret)

    @mock.patch.object(FCD_DRIVER, '_select_ds_fcd')
    @mock.patch.object(FCD_DRIVER, '_get_disk_type')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    def test_create_volume(self, vops, get_disk_type, select_ds_fcd):
        ds_ref = mock.sentinel.ds_ref
        select_ds_fcd.return_value = ds_ref

        disk_type = mock.sentinel.disk_type
        get_disk_type.return_value = disk_type

        fcd_loc = mock.Mock()
        provider_loc = mock.sentinel.provider_loc
        fcd_loc.provider_location.return_value = provider_loc
        vops.create_fcd.return_value = fcd_loc

        volume = self._create_volume_obj()
        ret = self._driver.create_volume(volume)
        self.assertEqual({'provider_location': provider_loc}, ret)
        select_ds_fcd.assert_called_once_with(volume)
        get_disk_type.assert_called_once_with(volume)
        vops.create_fcd.assert_called_once_with(
            volume.name, volume.size * units.Ki, ds_ref, disk_type)

    @mock.patch.object(volumeops.FcdLocation, 'from_provider_location')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    def test_delete_fcd(self, vops, from_provider_loc):
        fcd_loc = mock.sentinel.fcd_loc
        from_provider_loc.return_value = fcd_loc

        provider_loc = mock.sentinel.provider_loc
        self._driver._delete_fcd(provider_loc)
        from_provider_loc.test_assert_called_once_with(provider_loc)
        vops.delete_fcd.assert_called_once_with(fcd_loc)

    @mock.patch.object(FCD_DRIVER, '_delete_fcd')
    def test_delete_volume(self, delete_fcd):
        volume = self._create_volume_obj()
        self._driver.delete_volume(volume)
        delete_fcd.assert_called_once_with(volume.provider_location)

    @mock.patch.object(volumeops.FcdLocation, 'from_provider_location')
    @mock.patch.object(FCD_DRIVER, '_get_adapter_type')
    def test_initialize_connection(
            self, get_adapter_type, from_provider_location):
        fcd_loc = mock.Mock(
            fcd_id=mock.sentinel.fcd_id, ds_ref_val=mock.sentinel.ds_ref_val)
        from_provider_location.return_value = fcd_loc

        adapter_type = mock.sentinel.adapter_type
        get_adapter_type.return_value = adapter_type

        volume = self._create_volume_obj()
        connector = mock.sentinel.connector
        ret = self._driver.initialize_connection(volume, connector)
        self.assertEqual(self._driver.STORAGE_TYPE, ret['driver_volume_type'])
        self.assertEqual(fcd_loc.fcd_id, ret['data']['id'])
        self.assertEqual(fcd_loc.ds_ref_val, ret['data']['ds_ref_val'])
        self.assertEqual(adapter_type, ret['data']['adapter_type'])

    def test_container_format(self):
        self._driver._validate_container_format('bare', mock.sentinel.image_id)

    def test_container_format_invalid(self):
        self.assertRaises(cinder_exceptions.ImageUnacceptable,
                          self._driver._validate_container_format,
                          'ova',
                          mock.sentinel.image_id)

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

    @mock.patch.object(FCD_DRIVER, '_get_temp_image_folder')
    @mock.patch.object(FCD_DRIVER, '_create_virtual_disk_from_sparse_image')
    @mock.patch.object(FCD_DRIVER,
                       '_create_virtual_disk_from_preallocated_image')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    @mock.patch.object(datastore, 'DatastoreURL')
    @ddt.data(vmdk.ImageDiskType.PREALLOCATED, vmdk.ImageDiskType.SPARSE,
              vmdk.ImageDiskType.STREAM_OPTIMIZED)
    def test_copy_image_to_volume(self,
                                  disk_type,
                                  datastore_url_cls,
                                  vops,
                                  create_disk_from_preallocated_image,
                                  create_disk_from_sparse_image,
                                  get_temp_image_folder):
        image_meta = self._create_image_meta(vmware_disktype=disk_type)
        image_service = mock.Mock()
        image_service.show.return_value = image_meta

        dc_ref = mock.sentinel.dc_ref
        datastore = mock.sentinel.datastore
        summary = mock.Mock(datastore=datastore)
        summary.name = 'ds1'
        folder_path = mock.sentinel.folder_path
        get_temp_image_folder.return_value = (dc_ref, summary, folder_path)

        vmdk_path = mock.Mock()
        vmdk_path.get_descriptor_ds_file_path.return_value = (
            "[ds1] cinder_vol/foo.vmdk")
        if disk_type == vmdk.ImageDiskType.PREALLOCATED:
            create_disk_from_preallocated_image.return_value = vmdk_path
        else:
            create_disk_from_sparse_image.return_value = vmdk_path

        dc_path = '/test-dc'
        vops.get_inventory_path.return_value = dc_path

        ds_url = mock.sentinel.ds_url
        datastore_url_cls.return_value = ds_url

        fcd_loc = mock.Mock()
        provider_location = mock.sentinel.provider_location
        fcd_loc.provider_location.return_value = provider_location
        vops.register_disk.return_value = fcd_loc

        volume = self._create_volume_obj()
        image_id = self.IMAGE_ID
        ret = self._driver.copy_image_to_volume(
            self._context, volume, image_service, image_id)

        self.assertEqual({'provider_location': provider_location}, ret)
        get_temp_image_folder.assert_called_once_with(volume.size * units.Gi)
        if disk_type == vmdk.ImageDiskType.PREALLOCATED:
            create_disk_from_preallocated_image.assert_called_once_with(
                self._context, image_service, image_id, image_meta['size'],
                dc_ref, summary.name, folder_path, volume.id,
                volumeops.VirtualDiskAdapterType.LSI_LOGIC)
        else:
            create_disk_from_sparse_image.assert_called_once_with(
                self._context, image_service, image_id, image_meta['size'],
                dc_ref, summary.name, folder_path, volume.id)
        datastore_url_cls.assert_called_once_with(
            'https', self._driver.configuration.vmware_host_ip,
            'cinder_vol/foo.vmdk', '/test-dc', 'ds1')
        vops.register_disk.assert_called_once_with(
            str(ds_url),
            volume.name,
            summary.datastore)

    @mock.patch.object(volumeops.FcdLocation, 'from_provider_location')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    @mock.patch.object(vim_util, 'get_moref')
    @mock.patch.object(FCD_DRIVER, '_create_backing')
    @mock.patch.object(image_transfer, 'upload_image')
    @mock.patch.object(VMDK_DRIVER, 'session')
    @mock.patch.object(FCD_DRIVER, '_delete_temp_backing')
    def test_copy_volume_to_image(
            self, delete_temp_backing, session, upload_image, create_backing,
            get_moref, vops, from_provider_loc):
        fcd_loc = mock.Mock()
        ds_ref = mock.sentinel.ds_ref
        fcd_loc.ds_ref.return_value = ds_ref
        from_provider_loc.return_value = fcd_loc

        host_ref_val = mock.sentinel.host_ref_val
        vops.get_connected_hosts.return_value = [host_ref_val]

        host = mock.sentinel.host
        get_moref.return_value = host

        backing = mock.sentinel.backing
        create_backing.return_value = backing

        vmdk_file_path = mock.sentinel.vmdk_file_path
        vops.get_vmdk_path.return_value = vmdk_file_path
        vops.get_backing_by_uuid.return_value = backing

        volume = self._create_volume_obj()
        image_service = mock.sentinel.image_service
        image_meta = self._create_image_meta()
        self._driver.copy_volume_to_image(
            self._context, volume, image_service, image_meta)

        from_provider_loc.assert_called_once_with(volume.provider_location)
        vops.get_connected_hosts.assert_called_once_with(ds_ref)
        create_backing.assert_called_once_with(
            volume, host, {vmdk.CREATE_PARAM_DISK_LESS: True})
        vops.attach_fcd.assert_called_once_with(backing, fcd_loc)
        vops.get_vmdk_path.assert_called_once_with(backing)
        conf = self._driver.configuration
        upload_image.assert_called_once_with(
            self._context,
            conf.vmware_image_transfer_timeout_secs,
            image_service,
            image_meta['id'],
            volume.project_id,
            session=session,
            host=conf.vmware_host_ip,
            port=conf.vmware_host_port,
            vm=backing,
            vmdk_file_path=vmdk_file_path,
            vmdk_size=volume.size * units.Gi,
            image_name=image_meta['name'])
        vops.detach_fcd.assert_called_once_with(backing, fcd_loc)
        delete_temp_backing.assert_called_once_with(backing)

    @mock.patch.object(volumeops.FcdLocation, 'from_provider_location')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    def test_extend_volume(self, vops, from_provider_loc):
        fcd_loc = mock.sentinel.fcd_loc
        from_provider_loc.return_value = fcd_loc

        volume = self._create_volume_obj()
        new_size = 3
        self._driver.extend_volume(volume, new_size)
        from_provider_loc.assert_called_once_with(volume.provider_location)
        vops.extend_fcd.assert_called_once_with(
            fcd_loc, new_size * units.Ki)

    @mock.patch.object(volumeops.FcdLocation, 'from_provider_location')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    def test_clone_fcd(self, vops, from_provider_loc):
        fcd_loc = mock.sentinel.fcd_loc
        from_provider_loc.return_value = fcd_loc

        dest_fcd_loc = mock.sentinel.dest_fcd_loc
        vops.clone_fcd.return_value = dest_fcd_loc

        provider_loc = mock.sentinel.provider_loc
        name = mock.sentinel.name
        dest_ds_ref = mock.sentinel.dest_ds_ref
        disk_type = mock.sentinel.disk_type
        ret = self._driver._clone_fcd(
            provider_loc, name, dest_ds_ref, disk_type)
        self.assertEqual(dest_fcd_loc, ret)
        from_provider_loc.assert_called_once_with(provider_loc)
        vops.clone_fcd.assert_called_once_with(
            name, fcd_loc, dest_ds_ref, disk_type)

    @mock.patch.object(FCD_DRIVER, '_select_ds_fcd')
    @mock.patch.object(FCD_DRIVER, '_clone_fcd')
    def test_create_snapshot(self, clone_fcd, select_ds_fcd):
        ds_ref = mock.sentinel.ds_ref
        select_ds_fcd.return_value = ds_ref

        dest_fcd_loc = mock.Mock()
        provider_location = mock.sentinel.provider_location
        dest_fcd_loc.provider_location.return_value = provider_location
        clone_fcd.return_value = dest_fcd_loc

        volume = self._create_volume_obj()
        snapshot = fake_snapshot.fake_snapshot_obj(
            self._context, volume=volume)
        ret = self._driver.create_snapshot(snapshot)
        self.assertEqual({'provider_location': provider_location}, ret)
        select_ds_fcd.assert_called_once_with(snapshot.volume)
        clone_fcd.assert_called_once_with(
            volume.provider_location, snapshot.name, ds_ref)

    @mock.patch.object(FCD_DRIVER, '_delete_fcd')
    def test_delete_snapshot(self, delete_fcd):
        volume = self._create_volume_obj()
        snapshot = fake_snapshot.fake_snapshot_obj(
            self._context, volume=volume)
        self._driver.delete_snapshot(snapshot)
        delete_fcd.assert_called_once_with(snapshot.provider_location)

    @mock.patch.object(FCD_DRIVER, 'volumeops')
    @ddt.data((1, 1), (1, 2))
    @ddt.unpack
    def test_extend_if_needed(self, cur_size, new_size, vops):
        fcd_loc = mock.sentinel.fcd_loc
        self._driver._extend_if_needed(fcd_loc, cur_size, new_size)
        if new_size > cur_size:
            vops.extend_fcd.assert_called_once_with(
                fcd_loc, new_size * units.Ki)
        else:
            vops.extend_fcd.assert_not_called()

    @mock.patch.object(FCD_DRIVER, '_select_ds_fcd')
    @mock.patch.object(FCD_DRIVER, '_get_disk_type')
    @mock.patch.object(FCD_DRIVER, '_clone_fcd')
    @mock.patch.object(FCD_DRIVER, '_extend_if_needed')
    def test_create_volume_from_fcd(
            self, extend_if_needed, clone_fcd, get_disk_type, select_ds_fcd):
        ds_ref = mock.sentinel.ds_ref
        select_ds_fcd.return_value = ds_ref

        disk_type = mock.sentinel.disk_type
        get_disk_type.return_value = disk_type

        cloned_fcd_loc = mock.Mock()
        dest_provider_loc = mock.sentinel.dest_provider_loc
        cloned_fcd_loc.provider_location.return_value = dest_provider_loc
        clone_fcd.return_value = cloned_fcd_loc

        provider_loc = mock.sentinel.provider_loc
        cur_size = 1
        volume = self._create_volume_obj()
        ret = self._driver._create_volume_from_fcd(
            provider_loc, cur_size, volume)
        self.assertEqual({'provider_location': dest_provider_loc}, ret)
        select_ds_fcd.test_assert_called_once_with(volume)
        get_disk_type.test_assert_called_once_with(volume)
        clone_fcd.assert_called_once_with(
            provider_loc, volume.name, ds_ref, disk_type=disk_type)
        extend_if_needed.assert_called_once_with(
            cloned_fcd_loc, cur_size, volume.size)

    @mock.patch.object(FCD_DRIVER, '_create_volume_from_fcd')
    def test_create_volume_from_snapshot(self, create_volume_from_fcd):
        src_volume = self._create_volume_obj()
        snapshot = fake_snapshot.fake_snapshot_obj(
            self._context, volume=src_volume)
        volume = mock.sentinel.volume
        self._driver.create_volume_from_snapshot(volume, snapshot)
        create_volume_from_fcd.assert_called_once_with(
            snapshot.provider_location, snapshot.volume.size, volume)

    @mock.patch.object(FCD_DRIVER, '_create_volume_from_fcd')
    def test_create_cloned_volume(self, create_volume_from_fcd):
        src_volume = self._create_volume_obj()
        volume = mock.sentinel.volume
        self._driver.create_cloned_volume(volume, src_volume)
        create_volume_from_fcd.assert_called_once_with(
            src_volume.provider_location, src_volume.size, volume)
