# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""Tests for volume and images."""

import datetime
import os
import tempfile
from unittest import mock

from oslo_utils import imageutils
from oslo_utils import units

from cinder import db
from cinder import exception
from cinder.message import message_field
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder.tests import fake_driver
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base
import cinder.volume
from cinder.volume import manager as vol_manager

QUOTAS = quota.QUOTAS
NON_EXISTENT_IMAGE_ID = '003f540f-ec6b-4293-a3f9-7c68646b0f5c'


class FakeImageService(object):
    def __init__(self, image_service=None):
        pass

    def show(self, context, image_id):
        return {'size': 2 * units.Gi,
                'disk_format': 'raw',
                'container_format': 'bare',
                'status': 'active'}


class CopyVolumeToImageTestCase(base.BaseVolumeTestCase):
    def fake_local_path(self, volume):
        return self.dst_path

    def setUp(self):
        super(CopyVolumeToImageTestCase, self).setUp()
        self.dst_fd, self.dst_path = tempfile.mkstemp()
        self.addCleanup(os.unlink, self.dst_path)
        os.close(self.dst_fd)
        self.mock_object(self.volume.driver, 'local_path',
                         self.fake_local_path)
        self.mock_cache = mock.MagicMock()
        self.image_id = '70a599e0-31e7-49b7-b260-868f441e862b'
        self.image_meta = {
            'id': self.image_id,
            'container_format': 'bare',
            'disk_format': 'raw'
        }
        self.volume_id = fake.VOLUME_ID
        self.addCleanup(db.volume_destroy, self.context, self.volume_id)

        self.volume_attrs = {
            'id': self.volume_id,
            'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
            'display_description': 'Test Desc',
            'size': 20,
            'status': 'uploading',
            'host': 'dummy',
            'volume_type_id': fake.VOLUME_TYPE_ID
        }
        self.mock_object(db.sqlalchemy.api, 'volume_type_get',
                         v2_fakes.fake_volume_type_get)

    def test_copy_volume_to_image_status_available(self):
        # creating volume testdata
        self.volume_attrs['instance_uuid'] = None
        volume_type_id = db.volume_type_create(
            self.context, {'name': 'test', 'extra_specs': {
                'image_service:store_id': 'fake_store'
            }}).get('id')
        self.volume_attrs['volume_type_id'] = volume_type_id
        db.volume_create(self.context, self.volume_attrs)

        # start test
        self.volume.copy_volume_to_image(self.context,
                                         self.volume_id,
                                         self.image_meta)

        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume['status'])

    def test_copy_volume_to_image_over_image_quota(self):
        # creating volume testdata
        self.volume_attrs['instance_uuid'] = None
        volume = db.volume_create(self.context, self.volume_attrs)

        with mock.patch.object(self.volume.driver,
                               'copy_volume_to_image') as driver_copy_mock:
            driver_copy_mock.side_effect = exception.ImageLimitExceeded

            # test with image not in queued state
            self.assertRaises(exception.ImageLimitExceeded,
                              self.volume.copy_volume_to_image,
                              self.context,
                              self.volume_id,
                              self.image_meta)
            # Assert a user message was created
            self.volume.message_api.create.assert_called_once_with(
                self.context,
                message_field.Action.COPY_VOLUME_TO_IMAGE,
                resource_uuid=volume['id'],
                exception=mock.ANY,
                detail=message_field.Detail.FAILED_TO_UPLOAD_VOLUME)

    def test_copy_volume_to_image_instance_deleted(self):
        # During uploading volume to image if instance is deleted,
        # volume should be in available status.
        self.image_meta['id'] = 'a440c04b-79fa-479c-bed1-0b816eaec379'
        # Creating volume testdata
        self.volume_attrs['instance_uuid'] = 'b21f957d-a72f-4b93-b5a5-' \
                                             '45b1161abb02'
        volume_type_id = db.volume_type_create(
            self.context, {'name': 'test', 'extra_specs': {
                'image_service:store_id': 'fake_store'
            }}).get('id')
        self.volume_attrs['volume_type_id'] = volume_type_id
        db.volume_create(self.context, self.volume_attrs)

        method = 'volume_update_status_based_on_attachment'
        with mock.patch.object(db, method,
                               wraps=getattr(db, method)) as mock_update:
            # Start test
            self.volume.copy_volume_to_image(self.context,
                                             self.volume_id,
                                             self.image_meta)
            # Check 'volume_update_status_after_copy_volume_to_image'
            # is called 1 time
            self.assertEqual(1, mock_update.call_count)

        # Check volume status has changed to available because
        # instance is deleted
        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume['status'])

    def test_copy_volume_to_image_status_use(self):
        self.image_meta['id'] = 'a440c04b-79fa-479c-bed1-0b816eaec379'
        # creating volume testdata
        volume_type_id = db.volume_type_create(
            self.context, {'name': 'test', 'extra_specs': {
                'image_service:store_id': 'fake_store'
            }}).get('id')
        self.volume_attrs['volume_type_id'] = volume_type_id
        db.volume_create(self.context, self.volume_attrs)

        # start test
        self.volume.copy_volume_to_image(self.context,
                                         self.volume_id,
                                         self.image_meta)

        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume['status'])

    def test_copy_volume_to_image_exception(self):
        self.image_meta['id'] = NON_EXISTENT_IMAGE_ID
        # creating volume testdata
        volume_type_id = db.volume_type_create(
            self.context, {'name': 'test', 'extra_specs': {
                'image_service:store_id': 'fake_store'
            }}).get('id')
        self.volume_attrs['volume_type_id'] = volume_type_id
        self.volume_attrs['status'] = 'in-use'
        db.volume_create(self.context, self.volume_attrs)

        # start test
        self.assertRaises(exception.ImageNotFound,
                          self.volume.copy_volume_to_image,
                          self.context,
                          self.volume_id,
                          self.image_meta)

        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume['status'])

    def test_copy_volume_to_image_driver_not_initialized(self):
        # creating volume testdata
        db.volume_create(self.context, self.volume_attrs)

        # set initialized to False
        self.volume.driver._initialized = False

        # start test
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.copy_volume_to_image,
                          self.context,
                          self.volume_id,
                          self.image_meta)

        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume.status)

    def test_copy_volume_to_image_driver_exception(self):
        self.image_meta['id'] = self.image_id

        image_service = fake_image.FakeImageService()
        # create new image in queued state
        queued_image_id = 'd5133f15-f753-41bd-920a-06b8c49275d9'
        queued_image_meta = image_service.show(self.context, self.image_id)
        queued_image_meta['id'] = queued_image_id
        queued_image_meta['status'] = 'queued'
        image_service.create(self.context, queued_image_meta)

        # create new image in saving state
        saving_image_id = '5c6eec33-bab4-4e7d-b2c9-88e2d0a5f6f2'
        saving_image_meta = image_service.show(self.context, self.image_id)
        saving_image_meta['id'] = saving_image_id
        saving_image_meta['status'] = 'saving'
        image_service.create(self.context, saving_image_meta)

        # create volume
        self.volume_attrs['status'] = 'available'
        self.volume_attrs['instance_uuid'] = None
        db.volume_create(self.context, self.volume_attrs)

        with mock.patch.object(self.volume.driver,
                               'copy_volume_to_image') as driver_copy_mock:
            driver_copy_mock.side_effect = exception.VolumeDriverException(
                "Error")

            # test with image not in queued state
            self.assertRaises(exception.VolumeDriverException,
                              self.volume.copy_volume_to_image,
                              self.context,
                              self.volume_id,
                              self.image_meta)
            # Make sure we are passing an OVO instance and not an ORM instance
            # to the driver
            self.assertIsInstance(driver_copy_mock.call_args[0][1],
                                  objects.Volume)
            volume = db.volume_get(self.context, self.volume_id)
            self.assertEqual('available', volume['status'])
            # image shouldn't be deleted if it is not in queued state
            image_service.show(self.context, self.image_id)

            # test with image in queued state
            self.assertRaises(exception.VolumeDriverException,
                              self.volume.copy_volume_to_image,
                              self.context,
                              self.volume_id,
                              queued_image_meta)
            volume = db.volume_get(self.context, self.volume_id)
            self.assertEqual('available', volume['status'])
            # queued image should be deleted
            self.assertRaises(exception.ImageNotFound,
                              image_service.show,
                              self.context,
                              queued_image_id)

            # test with image in saving state
            self.assertRaises(exception.VolumeDriverException,
                              self.volume.copy_volume_to_image,
                              self.context,
                              self.volume_id,
                              saving_image_meta)
            volume = db.volume_get(self.context, self.volume_id)
            self.assertEqual('available', volume['status'])
            # image in saving state should be deleted
            self.assertRaises(exception.ImageNotFound,
                              image_service.show,
                              self.context,
                              saving_image_id)

    @mock.patch.object(QUOTAS, 'reserve')
    @mock.patch.object(QUOTAS, 'commit')
    @mock.patch.object(vol_manager.VolumeManager, 'create_volume')
    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver,
                       'copy_volume_to_image')
    def _test_copy_volume_to_image_with_image_volume(
            self, mock_copy, mock_create, mock_quota_commit,
            mock_quota_reserve):
        self.volume.driver.configuration.image_upload_use_cinder_backend = True
        self.addCleanup(fake_image.FakeImageService_reset)
        image_service = fake_image.FakeImageService()

        def add_location_wrapper(ctx, id, uri, metadata):
            try:
                volume = db.volume_get(ctx, id)
                self.assertEqual(ctx.project_id,
                                 volume['metadata']['image_owner'])
            except exception.VolumeNotFound:
                pass
            return image_service.add_location_orig(ctx, id, uri, metadata)

        image_service.add_location_orig = image_service.add_location
        image_service.add_location = add_location_wrapper

        image_id = '5c6eec33-bab4-4e7d-b2c9-88e2d0a5f6f2'
        self.image_meta['id'] = image_id
        self.image_meta['status'] = 'queued'
        image_service.create(self.context, self.image_meta)

        # creating volume testdata
        self.volume_attrs['instance_uuid'] = None
        self.volume_attrs['snapshot_id'] = fake.SNAPSHOT_ID
        volume_type_id = db.volume_type_create(
            self.context, {'name': 'test', 'extra_specs': {
                'image_service:store_id': 'fake_store'
            }}).get('id')
        self.volume_attrs['volume_type_id'] = volume_type_id
        db.volume_create(self.context, self.volume_attrs)

        def fake_create(context, volume, **kwargs):
            db.volume_update(context, volume.id, {'status': 'available'})

        mock_create.side_effect = fake_create

        # start test
        self.volume.copy_volume_to_image(self.context,
                                         self.volume_id,
                                         self.image_meta)

        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume['status'])

        # return create image
        image = image_service.show(self.context, image_id)
        image_service.delete(self.context, image_id)
        return image

    def test_copy_volume_to_image_with_image_volume(self):
        image = self._test_copy_volume_to_image_with_image_volume()
        self.assertTrue(image['locations'][0]['url'].startswith('cinder://'))
        image_volume_id = image['locations'][0]['url'][9:]
        # The image volume does NOT include the snapshot_id, and include the
        # source_volid which is the uploaded-volume id.
        vol_ref = db.volume_get(self.context, image_volume_id)
        self.assertIsNone(vol_ref['snapshot_id'])
        self.assertEqual(vol_ref['source_volid'], self.volume_id)

    def test_copy_volume_to_image_with_image_volume_qcow2(self):
        self.image_meta['disk_format'] = 'qcow2'
        image = self._test_copy_volume_to_image_with_image_volume()
        self.assertNotIn('locations', image)

    @mock.patch.object(vol_manager.VolumeManager, 'delete_volume')
    @mock.patch.object(fake_image._FakeImageService, 'add_location',
                       side_effect=exception.Invalid)
    def test_copy_volume_to_image_with_image_volume_failure(
            self, mock_add_location, mock_delete):
        image = self._test_copy_volume_to_image_with_image_volume()
        self.assertNotIn('locations', image)
        self.assertTrue(mock_delete.called)

    @mock.patch('cinder.volume.manager.'
                'VolumeManager._clone_image_volume')
    @mock.patch('cinder.volume.manager.'
                'VolumeManager._create_image_cache_volume_entry')
    def test_create_image_cache_volume_entry(self,
                                             mock_cache_entry,
                                             mock_clone_image_volume):
        image_id = self.image_id
        image_meta = self.image_meta

        self.mock_cache.get_entry.return_value = mock_cache_entry

        if mock_cache_entry:
            # Entry is in cache, so basically don't do anything.
            # Make sure we didn't try and create a cache entry
            self.assertFalse(self.mock_cache.ensure_space.called)
            self.assertFalse(self.mock_cache.create_cache_entry.called)
        else:
            result = self.volume._create_image_cache_volume_entry(
                self.context, mock_clone_image_volume, image_id, image_meta)
            self.assertNotEqual(False, result)
            cache_entry = self.image_volume_cache.get_entry(
                self.context, mock_clone_image_volume, image_id, image_meta)
            self.assertIsNotNone(cache_entry)


class ImageVolumeCacheTestCase(base.BaseVolumeTestCase):

    def setUp(self):
        super(ImageVolumeCacheTestCase, self).setUp()
        self.volume.driver.set_initialized()

    @mock.patch('oslo_utils.importutils.import_object')
    def test_cache_configs(self, mock_import_object):
        opts = {
            'image_volume_cache_enabled': True,
            'image_volume_cache_max_size_gb': 100,
            'image_volume_cache_max_count': 20
        }

        def conf_get(option):
            if option in opts:
                return opts[option]
            else:
                return None

        mock_driver = mock.Mock()
        mock_driver.configuration.safe_get.side_effect = conf_get
        mock_driver.configuration.extra_capabilities = 'null'

        def import_obj(*args, **kwargs):
            return mock_driver

        mock_import_object.side_effect = import_obj

        manager = vol_manager.VolumeManager(volume_driver=mock_driver)
        self.assertIsNotNone(manager)
        self.assertIsNotNone(manager.image_volume_cache)
        self.assertEqual(100, manager.image_volume_cache.max_cache_size_gb)
        self.assertEqual(20, manager.image_volume_cache.max_cache_size_count)

    def test_delete_image_volume(self):
        volume_params = {
            'status': 'creating',
            'host': 'some_host',
            'cluster_name': 'some_cluster',
            'size': 1
        }
        volume_api = cinder.volume.api.API()
        volume = tests_utils.create_volume(self.context, **volume_params)
        volume.status = 'available'
        volume.save()
        image_id = '70a599e0-31e7-49b7-b260-868f441e862b'
        db.image_volume_cache_create(self.context,
                                     volume['host'],
                                     volume_params['cluster_name'],
                                     image_id,
                                     datetime.datetime.utcnow(),
                                     volume['id'],
                                     volume['size'])
        volume_api.delete(self.context, volume)
        entry = db.image_volume_cache_get_by_volume_id(self.context,
                                                       volume['id'])
        self.assertIsNone(entry)

    def test_delete_volume_with_keymanager_exception(self):
        volume_params = {
            'host': 'some_host',
            'size': 1
        }
        volume_api = cinder.volume.api.API()
        volume = tests_utils.create_volume(self.context, **volume_params)

        with mock.patch.object(
                volume_api.key_manager, 'delete') as key_del_mock:
            key_del_mock.side_effect = Exception("Key not found")
            volume_api.delete(self.context, volume)


class ImageVolumeTestCases(base.BaseVolumeTestCase):

    def setUp(self):
        super(ImageVolumeTestCases, self).setUp()
        db.volume_type_create(self.context,
                              v2_fakes.fake_default_type_get(
                                  fake.VOLUME_TYPE2_ID))
        self.vol_type = db.volume_type_get_by_name(self.context,
                                                   'vol_type_name')

    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'create_cloned_volume')
    @mock.patch('cinder.quota.QUOTAS.rollback')
    @mock.patch('cinder.quota.QUOTAS.commit')
    @mock.patch('cinder.quota.QUOTAS.reserve', return_value=["RESERVATION"])
    def test_clone_image_volume(self, mock_reserve, mock_commit,
                                mock_rollback, mock_cloned_volume):
        # Confirm  cloning does not copy quota use field
        vol = tests_utils.create_volume(self.context, use_quota=False,
                                        **self.volume_params)
        # unnecessary attributes should be removed from image volume
        vol.consistencygroup = None
        result = self.volume._clone_image_volume(self.context, vol,
                                                 {'id': fake.VOLUME_ID})
        self.assertNotEqual(False, result)
        self.assertTrue(result.use_quota)  # Original was False
        mock_reserve.assert_called_once_with(self.context, volumes=1,
                                             volumes_vol_type_name=1,
                                             gigabytes=vol.size,
                                             gigabytes_vol_type_name=vol.size)
        mock_commit.assert_called_once_with(self.context, ["RESERVATION"],
                                            project_id=vol.project_id)

    @mock.patch('cinder.quota.QUOTAS.rollback')
    @mock.patch('cinder.quota.QUOTAS.commit')
    @mock.patch('cinder.quota.QUOTAS.reserve', return_value=["RESERVATION"])
    def test_clone_image_volume_creation_failure(self, mock_reserve,
                                                 mock_commit, mock_rollback):
        vol = tests_utils.create_volume(self.context, **self.volume_params)
        with mock.patch.object(objects, 'Volume', side_effect=ValueError):
            self.assertIsNone(self.volume._clone_image_volume(
                self.context, vol, {'id': fake.VOLUME_ID}))

        mock_reserve.assert_called_once_with(self.context, volumes=1,
                                             volumes_vol_type_name=1,
                                             gigabytes=vol.size,
                                             gigabytes_vol_type_name=vol.size)
        mock_rollback.assert_called_once_with(self.context, ["RESERVATION"])

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_create_volume_from_image_cloned_status_available(
            self, mock_qemu_info):
        """Test create volume from image via cloning.

        Verify that after cloning image to volume, it is in available
        state and is bootable.
        """
        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        volume = self._create_volume_from_image()
        self.assertEqual('available', volume['status'])
        self.assertTrue(volume['bootable'])
        self.volume.delete_volume(self.context, volume)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_create_volume_from_image_not_cloned_status_available(
            self, mock_qemu_info):
        """Test create volume from image via full copy.

        Verify that after copying image to volume, it is in available
        state and is bootable.
        """
        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        volume = self._create_volume_from_image(fakeout_clone_image=True)
        self.assertEqual('available', volume['status'])
        self.assertTrue(volume['bootable'])
        self.volume.delete_volume(self.context, volume)

    def test_create_volume_from_image_exception(self):
        """Test create volume from a non-existing image.

        Verify that create volume from a non-existing image, the volume
        status is 'error' and is not bootable.
        """
        dst_fd, dst_path = tempfile.mkstemp()
        os.close(dst_fd)

        self.mock_object(self.volume.driver, 'local_path', lambda x: dst_path)

        # creating volume testdata
        kwargs = {'display_description': 'Test Desc',
                  'size': 20,
                  'availability_zone': 'fake_availability_zone',
                  'status': 'creating',
                  'attach_status': fields.VolumeAttachStatus.DETACHED,
                  'host': 'dummy'}
        volume = objects.Volume(context=self.context, **kwargs)
        volume.create()

        self.assertRaises(exception.ImageNotFound,
                          self.volume.create_volume,
                          self.context,
                          volume,
                          {'image_id': NON_EXISTENT_IMAGE_ID})
        volume = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual("error", volume['status'])
        self.assertFalse(volume['bootable'])
        # cleanup
        volume.destroy()
        os.unlink(dst_path)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_create_volume_from_image_copy_exception_rescheduling(
            self, mock_qemu_info):
        """Test create volume with ImageCopyFailure

        This exception should not trigger rescheduling and allocated_capacity
        should be incremented so we're having assert for that here.
        """
        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        def fake_copy_image_to_volume(context, volume, image_service,
                                      image_id):
            raise exception.ImageCopyFailure()

        self.mock_object(self.volume.driver, 'copy_image_to_volume',
                         fake_copy_image_to_volume)
        mock_delete = self.mock_object(self.volume.driver, 'delete_volume')
        self.assertRaises(exception.ImageCopyFailure,
                          self._create_volume_from_image)
        # NOTE(dulek): Rescheduling should not occur, so lets assert that
        # allocated_capacity is incremented.
        self.assertDictEqual(self.volume.stats['pools'],
                             {'_pool0': {'allocated_capacity_gb': 1}})
        # NOTE(dulek): As we haven't rescheduled, make sure no delete_volume
        # was called.
        self.assertFalse(mock_delete.called)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_create_volume_from_image_with_img_too_big(
            self, mock_qemu_info):
        """Test create volume with ImageCopyFailure

        This exception should not trigger rescheduling and allocated_capacity
        should be incremented so we're having assert for that here.
        """
        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        def fake_copy_image_to_volume(context, volume, image_service,
                                      image_id):
            raise exception.ImageTooBig(image_id=image_id, reason='')

        self.mock_object(self.volume.driver, 'copy_image_to_volume',
                         fake_copy_image_to_volume)
        self.assertRaises(exception.ImageTooBig,
                          self._create_volume_from_image)

    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.volume_utils.brick_get_connector')
    @mock.patch('cinder.volume.driver.BaseVD.secure_file_operations_enabled')
    @mock.patch('cinder.volume.driver.BaseVD._detach_volume')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_create_volume_from_image_unavailable(
            self, mock_qemu_info, mock_detach, mock_secure, *args):
        """Test create volume with ImageCopyFailure

        We'll raise an exception inside _connect_device after volume has
        already been attached to confirm that it detaches the volume.
        """
        mock_secure.side_effect = NameError
        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        unbound_copy_method = cinder.volume.driver.BaseVD.copy_image_to_volume
        bound_copy_method = unbound_copy_method.__get__(self.volume.driver)
        with mock.patch.object(self.volume.driver, 'copy_image_to_volume',
                               side_effect=bound_copy_method):
            self.assertRaises(exception.ImageCopyFailure,
                              self._create_volume_from_image,
                              fakeout_copy_image_to_volume=False)
        # We must have called detach method.
        self.assertEqual(1, mock_detach.call_count)

    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.volume_utils.brick_get_connector')
    @mock.patch('cinder.volume.driver.BaseVD._connect_device')
    @mock.patch('cinder.volume.driver.BaseVD._detach_volume')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_create_volume_from_image_unavailable_no_attach_info(
            self, mock_qemu_info, mock_detach, mock_connect, *args):
        """Test create volume with ImageCopyFailure

        We'll raise an exception on _connect_device call to confirm that it
        detaches the volume even if the exception doesn't have attach_info.
        """
        mock_connect.side_effect = NameError
        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        unbound_copy_method = cinder.volume.driver.BaseVD.copy_image_to_volume
        bound_copy_method = unbound_copy_method.__get__(self.volume.driver)
        with mock.patch.object(self.volume.driver, 'copy_image_to_volume',
                               side_effect=bound_copy_method):
            self.assertRaises(exception.ImageCopyFailure,
                              self._create_volume_from_image,
                              fakeout_copy_image_to_volume=False)
        # We must have called detach method.
        self.assertEqual(1, mock_detach.call_count)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_create_volume_from_image_clone_image_volume(self, mock_qemu_info):
        """Test create volume from image via image volume.

        Verify that after cloning image to volume, it is in available
        state and is bootable.
        """
        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        volume = self._create_volume_from_image(clone_image_volume=True)
        self.assertEqual('available', volume['status'])
        self.assertTrue(volume['bootable'])
        self.volume.delete_volume(self.context, volume)

    def test_create_volume_from_exact_sized_image(self):
        """Test create volume from an image of the same size.

        Verify that an image which is exactly the same size as the
        volume, will work correctly.
        """
        try:
            volume_id = None
            volume_api = cinder.volume.api.API(
                image_service=FakeImageService())
            volume = volume_api.create(self.context, 2, 'name', 'description',
                                       image_id=self.FAKE_UUID,
                                       volume_type=self.vol_type)
            volume_id = volume['id']
            self.assertEqual('creating', volume['status'])

        finally:
            # cleanup
            db.volume_destroy(self.context, volume_id)

    def test_create_volume_from_oversized_image(self):
        """Verify that an image which is too big will fail correctly."""
        class _ModifiedFakeImageService(FakeImageService):
            def show(self, context, image_id):
                return {'size': 2 * units.Gi + 1,
                        'disk_format': 'raw',
                        'container_format': 'bare',
                        'status': 'active'}

        volume_api = cinder.volume.api.API(
            image_service=_ModifiedFakeImageService())

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context, 2,
                          'name', 'description', image_id=1)

    def test_create_volume_with_mindisk_error(self):
        """Verify volumes smaller than image minDisk will cause an error."""
        class _ModifiedFakeImageService(FakeImageService):
            def show(self, context, image_id):
                return {'size': 2 * units.Gi,
                        'disk_format': 'raw',
                        'container_format': 'bare',
                        'min_disk': 5,
                        'status': 'active'}

        volume_api = cinder.volume.api.API(
            image_service=_ModifiedFakeImageService())

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context, 2,
                          'name', 'description', image_id=1)

    def test_create_volume_with_deleted_imaged(self):
        """Verify create volume from image will cause an error."""
        class _ModifiedFakeImageService(FakeImageService):
            def show(self, context, image_id):
                return {'size': 2 * units.Gi,
                        'disk_format': 'raw',
                        'container_format': 'bare',
                        'min_disk': 5,
                        'status': 'deleted',
                        'id': image_id}

        volume_api = cinder.volume.api.API(
            image_service=_ModifiedFakeImageService())

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context, 2,
                          'name', 'description', image_id=1)

    def test_copy_volume_to_image_maintenance(self):
        """Test copy volume to image in maintenance."""
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.copy_volume_to_image,
                          self.context,
                          volume,
                          test_meta1,
                          force=True)


class CopyVolumeToImagePrivateFunctionsTestCase(
        cinder.tests.unit.test.TestCase):

    @mock.patch('cinder.volume.api.API.get_volume_image_metadata',
                return_value={'some_key': 'some_value',
                              'cinder_encryption_key_id': 'stale_value'})
    def test_merge_volume_image_meta(self, mock_get_img_meta):
        # this is what we're passing to copy_volume_to_image
        image_meta = {
            'container_format': 'bare',
            'disk_format': 'raw',
            'cinder_encryption_key_id': 'correct_value'
        }
        self.assertNotIn('properties', image_meta)

        volume_api = cinder.volume.api.API()
        volume_api._merge_volume_image_meta(None, None, image_meta)
        # we've got 'properties' now
        self.assertIn('properties', image_meta)
        # verify the key_id is what we expect
        self.assertEqual(image_meta['cinder_encryption_key_id'],
                         'correct_value')

        translate = cinder.image.glance.GlanceImageService._translate_to_glance
        sent_to_glance = translate(image_meta)

        # this is correct, glance gets a "flat" dict of properties
        self.assertNotIn('properties', sent_to_glance)

        # make sure the image would be created in Glance with the
        # correct key_id
        self.assertEqual(image_meta['cinder_encryption_key_id'],
                         sent_to_glance['cinder_encryption_key_id'])
