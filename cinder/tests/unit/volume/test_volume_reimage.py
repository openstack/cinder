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
"""Tests for Volume reimage Code."""

from unittest import mock

import ddt
from oslo_concurrency import processutils

from cinder import exception
from cinder.tests.unit import fake_constants
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base


@ddt.ddt
class VolumeReimageTestCase(base.BaseVolumeTestCase):

    def setUp(self):
        super(VolumeReimageTestCase, self).setUp()
        self.patch('cinder.volume.volume_utils.clear_volume', autospec=True)
        fake_image.mock_image_service(self)
        self.image_meta = fake_image.FakeImageService().show(
            self.context, fake_constants.IMAGE_ID)

    def test_volume_reimage(self):
        volume = tests_utils.create_volume(self.context, status='downloading',
                                           previous_status='available')
        self.assertEqual(volume.status, 'downloading')
        self.assertEqual(volume.previous_status, 'available')
        self.volume.create_volume(self.context, volume)

        with mock.patch.object(self.volume.driver, 'copy_image_to_volume'
                               ) as mock_cp_img:
            self.volume.reimage(self.context, volume, self.image_meta)
            mock_cp_img.assert_called_once_with(self.context, volume,
                                                fake_image.FakeImageService(),
                                                self.image_meta['id'])
        self.assertEqual(volume.status, 'available')

    def test_volume_reimage_raise_exception(self):
        volume = tests_utils.create_volume(self.context)
        self.volume.create_volume(self.context, volume)

        with mock.patch.object(self.volume.driver, 'copy_image_to_volume'
                               ) as mock_cp_img:
            mock_cp_img.side_effect = processutils.ProcessExecutionError
            self.assertRaises(exception.ImageCopyFailure, self.volume.reimage,
                              self.context, volume, self.image_meta)
            self.assertEqual(volume.previous_status, 'available')
            self.assertEqual(volume.status, 'error')

            mock_cp_img.side_effect = exception.ImageUnacceptable(
                image_id=self.image_meta['id'], reason='')
            self.assertRaises(exception.ImageUnacceptable, self.volume.reimage,
                              self.context, volume, self.image_meta)

            mock_cp_img.side_effect = exception.ImageTooBig(
                image_id=self.image_meta['id'], reason='')
            self.assertRaises(exception.ImageTooBig, self.volume.reimage,
                              self.context, volume, self.image_meta)

            mock_cp_img.side_effect = Exception
            self.assertRaises(exception.ImageCopyFailure, self.volume.reimage,
                              self.context, volume, self.image_meta)

            mock_cp_img.side_effect = exception.ImageCopyFailure(reason='')
            self.assertRaises(exception.ImageCopyFailure, self.volume.reimage,
                              self.context, volume, self.image_meta)

    @mock.patch('cinder.volume.volume_utils.check_image_metadata')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.reimage')
    @ddt.data('available', 'error')
    def test_volume_reimage_api(self, status, mock_reimage, mock_check):
        volume = tests_utils.create_volume(self.context)
        volume.status = status
        volume.save()
        self.assertEqual(volume.status, status)
        # The available or error volume can be reimaged directly
        self.volume_api.reimage(self.context, volume, self.image_meta['id'])
        mock_check.assert_called_once_with(self.image_meta, volume.size)
        mock_reimage.assert_called_once_with(self.context, volume,
                                             self.image_meta)

    @mock.patch('cinder.volume.volume_utils.check_image_metadata')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.reimage')
    def test_volume_reimage_api_with_reimage_reserved(self, mock_reimage,
                                                      mock_check):
        volume = tests_utils.create_volume(self.context)
        # The reserved volume can not be reimaged directly, and only can
        # be reimaged with reimage_reserved flag
        volume.status = 'reserved'
        volume.save()
        self.assertEqual(volume.status, 'reserved')
        self.volume_api.reimage(self.context, volume, self.image_meta['id'],
                                reimage_reserved=True)
        mock_check.assert_called_once_with(self.image_meta, volume.size)
        mock_reimage.assert_called_once_with(self.context, volume,
                                             self.image_meta)

    def test_volume_reimage_api_with_invaild_status(self):
        volume = tests_utils.create_volume(self.context)
        # The reserved volume can not be reimaged directly, and only can
        # be reimaged with reimage_reserved flag

        volume.status = 'reserved'
        volume.save()
        self.assertEqual(volume.status, 'reserved')
        ex = self.assertRaises(exception.InvalidVolume,
                               self.volume_api.reimage,
                               self.context, volume,
                               self.image_meta['id'],
                               reimage_reserved=False)
        self.assertIn("status must be available or error",
                      str(ex))
        # The other status volume can not be reimage
        volume.status = 'in-use'
        volume.save()
        self.assertEqual(volume.status, 'in-use')
        ex = self.assertRaises(exception.InvalidVolume,
                               self.volume_api.reimage,
                               self.context, volume, self.image_meta['id'],
                               reimage_reserved=True)
        self.assertIn("status must be "
                      "available or error or reserved",
                      str(ex))
