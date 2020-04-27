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

"""Test suite for VMware vCenter FCD driver."""

from unittest import mock

import ddt
from oslo_utils import timeutils
from oslo_utils import units
from oslo_vmware import image_transfer
from oslo_vmware.objects import datastore
from oslo_vmware import vim_util

from cinder import context
from cinder import exception as cinder_exceptions
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit import utils as test_utils
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
    RESERVED_PERCENTAGE = 0
    VMDK_DRIVER = vmdk.VMwareVcVmdkDriver
    FCD_DRIVER = fcd.VMwareVStorageObjectDriver
    VC_VERSION = "6.7.0"

    VOL_ID = 'abcdefab-cdef-abcd-efab-cdefabcdefab'
    SRC_VOL_ID = '9b3f6f1b-03a9-4f1e-aaff-ae15122b6ccf'
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
        self._config.reserved_percentage = self.RESERVED_PERCENTAGE
        self._driver = fcd.VMwareVStorageObjectDriver(
            configuration=self._config)
        self._driver._vc_version = self.VC_VERSION
        self._driver._storage_policy_enabled = True
        self._context = context.get_admin_context()
        self.updated_at = timeutils.utcnow()

    @mock.patch.object(VMDK_DRIVER, 'do_setup')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    def test_do_setup(self, vops, vmdk_do_setup):
        self._driver._storage_policy_enabled = False
        self._driver.do_setup(self._context)

        vmdk_do_setup.assert_called_once_with(self._context)
        vops.set_vmx_version.assert_called_once_with('vmx-13')
        self.assertTrue(self._driver._use_fcd_snapshot)
        self.assertTrue(self._driver._storage_policy_enabled)

    @mock.patch.object(VMDK_DRIVER, 'volumeops')
    @mock.patch.object(VMDK_DRIVER, '_get_datastore_summaries')
    def test_get_volume_stats(self, _get_datastore_summaries, vops):
        FREE_GB = 7
        TOTAL_GB = 11

        class ObjMock(object):
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        _get_datastore_summaries.return_value = \
            ObjMock(objects= [
                ObjMock(propSet = [
                    ObjMock(name = "host",
                            val = ObjMock(DatastoreHostMount = [])),
                    ObjMock(name = "summary",
                            val = ObjMock(freeSpace = FREE_GB * units.Gi,
                                          capacity = TOTAL_GB * units.Gi,
                                          accessible = True))
                ])
            ])

        vops._in_maintenance.return_value = False

        stats = self._driver.get_volume_stats()

        self.assertEqual('VMware', stats['vendor_name'])
        self.assertEqual(self._driver.VERSION, stats['driver_version'])
        self.assertEqual(self._driver.STORAGE_TYPE, stats['storage_protocol'])
        self.assertEqual(self.RESERVED_PERCENTAGE,
                         stats['reserved_percentage'])
        self.assertEqual(TOTAL_GB, stats['total_capacity_gb'])
        self.assertEqual(FREE_GB, stats['free_capacity_gb'])

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

    @mock.patch.object(FCD_DRIVER, '_get_storage_profile')
    @mock.patch.object(FCD_DRIVER, '_select_datastore')
    def test_select_ds_fcd(self, select_datastore, get_storage_profile):
        profile = mock.sentinel.profile
        get_storage_profile.return_value = profile

        datastore = mock.sentinel.datastore
        summary = mock.Mock(datastore=datastore)
        select_datastore.return_value = (mock.ANY, mock.ANY, summary)

        volume = self._create_volume_obj()
        ret = self._driver._select_ds_fcd(volume)
        self.assertEqual(datastore, ret)
        exp_req = {hub.DatastoreSelector.SIZE_BYTES: volume.size * units.Gi,
                   hub.DatastoreSelector.PROFILE_NAME: profile}
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
    @mock.patch.object(FCD_DRIVER, '_get_storage_profile_id')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    def test_create_volume(self, vops, get_storage_profile_id, get_disk_type,
                           select_ds_fcd):
        ds_ref = mock.sentinel.ds_ref
        select_ds_fcd.return_value = ds_ref

        disk_type = mock.sentinel.disk_type
        get_disk_type.return_value = disk_type

        profile_id = mock.sentinel.profile_id
        get_storage_profile_id.return_value = profile_id

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
            volume.name, volume.size * units.Ki, ds_ref, disk_type,
            profile_id=profile_id)

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
        volume.provider_location = 'foo@ds1'
        self._driver.delete_volume(volume)
        delete_fcd.assert_called_once_with(volume.provider_location)

    @mock.patch.object(FCD_DRIVER, '_delete_fcd')
    def test_delete_volume_empty_provider_location(self, delete_fcd):
        volume = self._create_volume_obj()
        self._driver.delete_volume(volume)
        delete_fcd.assert_not_called()

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
    @mock.patch.object(FCD_DRIVER, '_get_storage_profile_id')
    @ddt.data(vmdk.ImageDiskType.PREALLOCATED, vmdk.ImageDiskType.SPARSE,
              vmdk.ImageDiskType.STREAM_OPTIMIZED)
    def test_copy_image_to_volume(self,
                                  disk_type,
                                  get_storage_profile_id,
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

        profile_id = mock.sentinel.profile_id
        get_storage_profile_id.return_value = profile_id

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
        vops.update_fcd_policy.assert_called_once_with(fcd_loc, profile_id)

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

        volume = test_utils.create_volume(
            self._context, volume_type_id=fake.VOLUME_TYPE_ID,
            updated_at=self.updated_at)
        extra_specs = {
            'image_service:store_id': 'fake-store'
        }
        test_utils.create_volume_type(
            self._context.elevated(), id=fake.VOLUME_TYPE_ID,
            name="test_type", extra_specs=extra_specs)

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
            image_name=image_meta['name'],
            store_id='fake-store',
            base_image_ref=None)
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
            name, fcd_loc, dest_ds_ref, disk_type, profile_id=None)

    @mock.patch.object(FCD_DRIVER, '_select_ds_fcd')
    @mock.patch.object(FCD_DRIVER, '_clone_fcd')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    @mock.patch.object(volumeops.FcdLocation, 'from_provider_location')
    def _test_create_snapshot(
            self, from_provider_loc, vops, clone_fcd, select_ds_fcd,
            use_fcd_snapshot=False):
        self._driver._use_fcd_snapshot = use_fcd_snapshot

        provider_location = mock.sentinel.provider_location
        if use_fcd_snapshot:
            fcd_loc = mock.sentinel.fcd_loc
            from_provider_loc.return_value = fcd_loc

            fcd_snap_loc = mock.Mock()
            fcd_snap_loc.provider_location.return_value = provider_location
            vops.create_fcd_snapshot.return_value = fcd_snap_loc
        else:
            ds_ref = mock.sentinel.ds_ref
            select_ds_fcd.return_value = ds_ref

            dest_fcd_loc = mock.Mock()
            dest_fcd_loc.provider_location.return_value = provider_location
            clone_fcd.return_value = dest_fcd_loc

        volume = self._create_volume_obj()
        snapshot = fake_snapshot.fake_snapshot_obj(
            self._context, volume=volume)
        ret = self._driver.create_snapshot(snapshot)
        self.assertEqual({'provider_location': provider_location}, ret)

        if use_fcd_snapshot:
            vops.create_fcd_snapshot.assert_called_once_with(
                fcd_loc, description="snapshot-%s" % snapshot.id)
        else:
            select_ds_fcd.assert_called_once_with(snapshot.volume)
            clone_fcd.assert_called_once_with(
                volume.provider_location, snapshot.name, ds_ref)

    def test_create_snapshot_legacy(self):
        self._test_create_snapshot()

    def test_create_snapshot(self):
        self._test_create_snapshot(use_fcd_snapshot=True)

    @mock.patch.object(FCD_DRIVER, '_delete_fcd')
    @mock.patch.object(volumeops.FcdSnapshotLocation, 'from_provider_location')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    def _test_delete_snapshot(
            self, vops, from_provider_loc, delete_fcd,
            empty_provider_loc=False, use_fcd_snapshot=False):
        volume = self._create_volume_obj()
        snapshot = fake_snapshot.fake_snapshot_obj(
            self._context, volume=volume)

        if empty_provider_loc:
            snapshot.provider_location = None
        else:
            snapshot.provider_location = "test"
            if use_fcd_snapshot:
                fcd_snap_loc = mock.sentinel.fcd_snap_loc
                from_provider_loc.return_value = fcd_snap_loc
            else:
                from_provider_loc.return_value = None

        self._driver.delete_snapshot(snapshot)
        if empty_provider_loc:
            delete_fcd.assert_not_called()
            vops.delete_fcd_snapshot.assert_not_called()
        elif use_fcd_snapshot:
            vops.delete_fcd_snapshot.assert_called_once_with(fcd_snap_loc)
        else:
            delete_fcd.assert_called_once_with(snapshot.provider_location)

    def test_delete_snapshot_legacy(self):
        self._test_delete_snapshot()

    def test_delete_snapshot_with_empty_provider_loc(self):
        self._test_delete_snapshot(empty_provider_loc=True)

    def test_delete_snapshot(self):
        self._test_delete_snapshot(use_fcd_snapshot=True)

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
    @mock.patch.object(FCD_DRIVER, '_get_storage_profile_id')
    @mock.patch.object(FCD_DRIVER, '_clone_fcd')
    @mock.patch.object(FCD_DRIVER, '_extend_if_needed')
    def test_create_volume_from_fcd(
            self, extend_if_needed, clone_fcd, get_storage_profile_id,
            get_disk_type, select_ds_fcd):
        ds_ref = mock.sentinel.ds_ref
        select_ds_fcd.return_value = ds_ref

        disk_type = mock.sentinel.disk_type
        get_disk_type.return_value = disk_type

        profile_id = mock.sentinel.profile_id
        get_storage_profile_id.return_value = profile_id

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
            provider_loc, volume.name, ds_ref, disk_type=disk_type,
            profile_id=profile_id)
        extend_if_needed.assert_called_once_with(
            cloned_fcd_loc, cur_size, volume.size)

    @mock.patch.object(FCD_DRIVER, '_create_volume_from_fcd')
    @mock.patch.object(volumeops.FcdSnapshotLocation, 'from_provider_location')
    @mock.patch.object(FCD_DRIVER, '_get_storage_profile_id')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    @mock.patch.object(FCD_DRIVER, '_extend_if_needed')
    def _test_create_volume_from_snapshot(
            self, extend_if_needed, vops, get_storage_profile_id,
            from_provider_loc, create_volume_from_fcd, use_fcd_snapshot=False):
        src_volume = self._create_volume_obj(vol_id=self.SRC_VOL_ID)
        snapshot = fake_snapshot.fake_snapshot_obj(
            self._context, volume=src_volume)
        volume = self._create_volume_obj(size=self.VOL_SIZE + 1)

        if use_fcd_snapshot:
            fcd_snap_loc = mock.sentinel.fcd_snap_loc
            from_provider_loc.return_value = fcd_snap_loc

            profile_id = mock.sentinel.profile_id
            get_storage_profile_id.return_value = profile_id

            fcd_loc = mock.Mock()
            provider_loc = mock.sentinel.provider_loc
            fcd_loc.provider_location.return_value = provider_loc
            vops.create_fcd_from_snapshot.return_value = fcd_loc
        else:
            from_provider_loc.return_value = None

        ret = self._driver.create_volume_from_snapshot(volume, snapshot)
        if use_fcd_snapshot:
            self.assertEqual({'provider_location': provider_loc}, ret)
            vops.create_fcd_from_snapshot.assert_called_once_with(
                fcd_snap_loc, volume.name, profile_id=profile_id)
            extend_if_needed.assert_called_once_with(
                fcd_loc, snapshot.volume_size, volume.size)
        else:
            create_volume_from_fcd.assert_called_once_with(
                snapshot.provider_location, snapshot.volume.size, volume)

    def test_create_volume_from_snapshot_legacy(self):
        self._test_create_volume_from_snapshot()

    def test_create_volume_from_snapshot(self):
        self._test_create_volume_from_snapshot(use_fcd_snapshot=True)

    @mock.patch.object(FCD_DRIVER, '_create_volume_from_fcd')
    def test_create_cloned_volume(self, create_volume_from_fcd):
        src_volume = self._create_volume_obj()
        volume = mock.sentinel.volume
        self._driver.create_cloned_volume(volume, src_volume)
        create_volume_from_fcd.assert_called_once_with(
            src_volume.provider_location, src_volume.size, volume)

    @mock.patch.object(FCD_DRIVER, '_get_storage_profile')
    @mock.patch.object(FCD_DRIVER, '_get_extra_spec_storage_profile')
    @mock.patch.object(FCD_DRIVER, '_in_use')
    @mock.patch.object(FCD_DRIVER, 'volumeops')
    @mock.patch.object(volumeops.FcdLocation, 'from_provider_location')
    @mock.patch.object(FCD_DRIVER, 'ds_sel')
    @ddt.data({},
              {'storage_policy_enabled': False},
              {'same_profile': True},
              {'vol_in_use': True}
              )
    @ddt.unpack
    def test_retype(
            self, ds_sel, from_provider_location, vops, in_use,
            get_extra_spec_storage_profile, get_storage_profile,
            storage_policy_enabled=True, same_profile=False, vol_in_use=False):
        self._driver._storage_policy_enabled = storage_policy_enabled

        if storage_policy_enabled:
            profile = mock.sentinel.profile
            get_storage_profile.return_value = profile

            if same_profile:
                new_profile = profile
            else:
                new_profile = mock.sentinel.new_profile
            get_extra_spec_storage_profile.return_value = new_profile

            in_use.return_value = vol_in_use

            if not vol_in_use:
                fcd_loc = mock.sentinel.fcd_loc
                from_provider_location.return_value = fcd_loc

                new_profile_id = mock.Mock()
                ds_sel.get_profile_id.return_value = new_profile_id

        ctxt = mock.sentinel.ctxt
        volume = self._create_volume_obj()
        new_type = {'id': mock.sentinel.new_type_id}
        diff = mock.sentinel.diff
        host = mock.sentinel.host
        ret = self._driver.retype(ctxt, volume, new_type, diff, host)

        if not storage_policy_enabled:
            self.assertTrue(ret)
        else:
            get_storage_profile.assert_called_once_with(volume)
            get_extra_spec_storage_profile.assert_called_once_with(
                new_type['id'])
            if same_profile:
                self.assertTrue(ret)
            else:
                in_use.assert_called_once_with(volume)
                if vol_in_use:
                    self.assertFalse(ret)
                else:
                    ds_sel.get_profile_id.assert_called_once_with(new_profile)
                    vops.update_fcd_policy.assert_called_once_with(
                        fcd_loc, new_profile_id.uniqueId)
