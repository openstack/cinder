# Copyright (c) 2015 Tintri.  All rights reserved.
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
Volume driver test for Tintri storage.
"""

import mock

from oslo_log import log as logging

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume.drivers.tintri import TClient
from cinder.volume.drivers.tintri import TintriDriver

LOG = logging.getLogger(__name__)


class FakeImage(object):
    def __init__(self):
        self.id = 'image-id'
        self.name = 'image-name'

    def __getitem__(self, key):
        return self.__dict__[key]


class TintriDriverTestCase(test.TestCase):
    def setUp(self):
        super(TintriDriverTestCase, self).setUp()
        self.context = context.get_admin_context()
        kwargs = {'configuration': self.create_configuration()}
        self._driver = TintriDriver(**kwargs)
        self._driver._hostname = 'host'
        self._driver._username = 'user'
        self._driver._password = 'password'
        self._provider_location = 'host:/share'
        self._driver._mounted_shares = [self._provider_location]
        self.fake_stubs()

    def create_configuration(self):
        configuration = mock.Mock()
        configuration.nfs_mount_point_base = '/mnt/test'
        configuration.nfs_mount_options = None
        configuration.nas_mount_options = None
        return configuration

    def fake_stubs(self):
        self.stubs.Set(TClient, 'login', self.fake_login)
        self.stubs.Set(TClient, 'logout', self.fake_logout)
        self.stubs.Set(TClient, 'get_snapshot', self.fake_get_snapshot)
        self.stubs.Set(TintriDriver, '_move_cloned_volume',
                       self.fake_move_cloned_volume)
        self.stubs.Set(TintriDriver, '_get_provider_location',
                       self.fake_get_provider_location)
        self.stubs.Set(TintriDriver, '_set_rw_permissions',
                       self.fake_set_rw_permissions)
        self.stubs.Set(TintriDriver, '_is_volume_present',
                       self.fake_is_volume_present)
        self.stubs.Set(TintriDriver, '_is_share_vol_compatible',
                       self.fake_is_share_vol_compatible)
        self.stubs.Set(TintriDriver, '_is_file_size_equal',
                       self.fake_is_file_size_equal)

    def fake_login(self, user_name, password):
        return 'session-id'

    def fake_logout(self):
        pass

    def fake_get_snapshot(self, volume_name):
        return 'snapshot-id'

    def fake_move_cloned_volume(self, clone_name, volume_id, share=None):
        pass

    def fake_get_provider_location(self, volume_path):
        return self._provider_location

    def fake_set_rw_permissions(self, path):
        pass

    def fake_is_volume_present(self, volume_path):
        return True

    def fake_is_share_vol_compatible(self, volume, share):
        return True

    def fake_is_file_size_equal(self, path, size):
        return True

    @mock.patch.object(TClient, 'create_snapshot', mock.Mock())
    def test_create_snapshot(self):
        snapshot = fake_snapshot.fake_snapshot_obj(self.context)
        volume = fake_volume.fake_volume_obj(self.context)
        snapshot.volume = volume
        self._driver.create_snapshot(snapshot)

    @mock.patch.object(TClient, 'create_snapshot', mock.Mock(
                       side_effect=exception.VolumeDriverException))
    def test_create_snapshot_failure(self):
        snapshot = fake_snapshot.fake_snapshot_obj(self.context)
        volume = fake_volume.fake_volume_obj(self.context)
        snapshot.volume = volume
        self.assertRaises(exception.VolumeDriverException,
                          self._driver.create_snapshot, snapshot)

    @mock.patch.object(TClient, 'delete_snapshot', mock.Mock())
    def test_delete_snapshot(self):
        snapshot = fake_snapshot.fake_snapshot_obj(self.context)
        self._driver.delete_snapshot(snapshot)

    @mock.patch.object(TClient, 'delete_snapshot', mock.Mock(
                       side_effect=exception.VolumeDriverException))
    def test_delete_snapshot_failure(self):
        snapshot = fake_snapshot.fake_snapshot_obj(self.context)
        self.assertRaises(exception.VolumeDriverException,
                          self._driver.delete_snapshot, snapshot)

    @mock.patch.object(TClient, 'clone_volume', mock.Mock())
    def test_create_volume_from_snapshot(self):
        snapshot = fake_snapshot.fake_snapshot_obj(self.context)
        volume = fake_volume.fake_volume_obj(self.context)
        self.assertEqual({'provider_location': self._provider_location},
                         self._driver.create_volume_from_snapshot(
                         volume, snapshot))

    @mock.patch.object(TClient, 'clone_volume', mock.Mock(
                       side_effect=exception.VolumeDriverException))
    def test_create_volume_from_snapshot_failure(self):
        snapshot = fake_snapshot.fake_snapshot_obj(self.context)
        volume = fake_volume.fake_volume_obj(self.context)
        self.assertRaises(exception.VolumeDriverException,
                          self._driver.create_volume_from_snapshot,
                          volume, snapshot)

    @mock.patch.object(TClient, 'clone_volume', mock.Mock())
    @mock.patch.object(TClient, 'create_snapshot', mock.Mock())
    def test_create_cloned_volume(self):
        volume = fake_volume.fake_volume_obj(self.context)
        self.assertEqual({'provider_location': self._provider_location},
                         self._driver.create_cloned_volume(volume, volume))

    @mock.patch.object(TClient, 'clone_volume', mock.Mock(
                       side_effect=exception.VolumeDriverException))
    @mock.patch.object(TClient, 'create_snapshot', mock.Mock())
    def test_create_cloned_volume_failure(self):
        volume = fake_volume.fake_volume_obj(self.context)
        self.assertRaises(exception.VolumeDriverException,
                          self._driver.create_cloned_volume, volume, volume)

    @mock.patch.object(TClient, 'clone_volume', mock.Mock())
    def test_clone_image(self):
        volume = fake_volume.fake_volume_obj(self.context)
        self.assertEqual(({'provider_location': self._provider_location,
                           'bootable': True}, True),
                         self._driver.clone_image(
                         None, volume, 'image-name', FakeImage(), None))

    @mock.patch.object(TClient, 'clone_volume', mock.Mock(
                       side_effect=exception.VolumeDriverException))
    def test_clone_image_failure(self):
        volume = fake_volume.fake_volume_obj(self.context)
        self.assertEqual(({'provider_location': None,
                           'bootable': False}, False),
                         self._driver.clone_image(
                         None, volume, 'image-name', FakeImage(), None))
