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
import os
import shutil
import tempfile

import mock
from oslo_config import cfg
from oslo_utils import importutils
from stevedore import extension

from cinder.brick.local_dev import lvm as brick_lvm
from cinder import context
from cinder.image import image_utils
from cinder import objects
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import utils as tests_utils
from cinder.volume import api as volume_api
from cinder.volume import configuration as conf


CONF = cfg.CONF


class BaseVolumeTestCase(test.TestCase):
    """Test Case for volumes."""

    FAKE_UUID = fake.IMAGE_ID

    def setUp(self, *args, **kwargs):
        super(BaseVolumeTestCase, self).setUp(*args, **kwargs)
        self.extension_manager = extension.ExtensionManager(
            "BaseVolumeTestCase")
        vol_tmpdir = tempfile.mkdtemp()
        self.flags(volumes_dir=vol_tmpdir)
        self.addCleanup(self._cleanup)
        self.volume = importutils.import_object(CONF.volume_manager)
        self.volume.message_api = mock.Mock()
        self.configuration = mock.Mock(conf.Configuration)
        self.context = context.get_admin_context()
        self.context.user_id = fake.USER_ID
        # NOTE(mriedem): The id is hard-coded here for tracking race fail
        # assertions with the notification code, it's part of an
        # elastic-recheck query so don't remove it or change it.
        self.project_id = '7f265bd4-3a85-465e-a899-5dc4854a86d3'
        self.user_context = context.RequestContext(user_id=fake.USER_ID,
                                                   project_id=self.project_id,
                                                   is_admin=False)
        self.context.project_id = self.project_id
        self.volume_params = {
            'status': 'creating',
            'host': CONF.host,
            'size': 1}
        self.mock_object(brick_lvm.LVM,
                         'get_all_volume_groups',
                         self.fake_get_all_volume_groups)
        fake_image.mock_image_service(self)
        self.mock_object(brick_lvm.LVM, '_vg_exists', lambda x: True)
        self.mock_object(os.path, 'exists', lambda x: True)
        self.mock_object(image_utils, 'check_available_space',
                         lambda x, y, z: True)
        self.volume.driver.set_initialized()
        self.volume.stats = {'allocated_capacity_gb': 0,
                             'pools': {}}
        # keep ordered record of what we execute
        self.called = []
        self.volume_api = volume_api.API()

    def _cleanup(self):
        try:
            shutil.rmtree(CONF.volumes_dir)
        except OSError:
            pass

    def fake_get_all_volume_groups(obj, vg_name=None, no_suffix=True):
        return [{'name': 'cinder-volumes',
                 'size': '5.00',
                 'available': '2.50',
                 'lv_count': '2',
                 'uuid': 'vR1JU3-FAKE-C4A9-PQFh-Mctm-9FwA-Xwzc1m'}]

    @mock.patch('cinder.image.image_utils.TemporaryImages.fetch')
    @mock.patch('cinder.volume.flows.manager.create_volume.'
                'CreateVolumeFromSpecTask._clone_image_volume')
    def _create_volume_from_image(self, mock_clone_image_volume,
                                  mock_fetch_img,
                                  fakeout_copy_image_to_volume=False,
                                  fakeout_clone_image=False,
                                  clone_image_volume=False):
        """Test function of create_volume_from_image.

        Test cases call this function to create a volume from image, caller
        can choose whether to fake out copy_image_to_volume and clone_image,
        after calling this, test cases should check status of the volume.
        """
        def fake_local_path(volume):
            return dst_path

        def fake_copy_image_to_volume(context, volume,
                                      image_service, image_id):
            pass

        def fake_fetch_to_raw(ctx, image_service, image_id, path, blocksize,
                              size=None, throttle=None):
            pass

        def fake_clone_image(ctx, volume_ref,
                             image_location, image_meta,
                             image_service):
            return {'provider_location': None}, True

        dst_fd, dst_path = tempfile.mkstemp()
        os.close(dst_fd)
        self.mock_object(self.volume.driver, 'local_path', fake_local_path)
        if fakeout_clone_image:
            self.mock_object(self.volume.driver, 'clone_image',
                             fake_clone_image)
        self.mock_object(image_utils, 'fetch_to_raw', fake_fetch_to_raw)
        if fakeout_copy_image_to_volume:
            self.mock_object(self.volume.driver, 'copy_image_to_volume',
                             fake_copy_image_to_volume)
        mock_clone_image_volume.return_value = ({}, clone_image_volume)
        mock_fetch_img.return_value = mock.MagicMock(
            spec=tests_utils.get_file_spec())

        image_id = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        # creating volume testdata
        try:
            request_spec = {
                'volume_properties': self.volume_params,
                'image_id': image_id,
                'image_size': 1
            }
            self.volume.create_volume(self.context, volume, request_spec)
        finally:
            # cleanup
            os.unlink(dst_path)
            volume = objects.Volume.get_by_id(self.context, volume.id)

        return volume
