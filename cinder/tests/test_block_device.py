# Copyright (c) 2013 Mirantis, Inc.
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

import os.path

import mox

from cinder import context
from cinder.db.sqlalchemy import api
import cinder.exception
from cinder.image import image_utils
import cinder.test
from cinder.volume.driver import ISCSIDriver
from cinder.volume.drivers.block_device import BlockDeviceDriver
from cinder.volume import utils as volutils


class TestBlockDeviceDriver(cinder.test.TestCase):
    def setUp(self):
        super(TestBlockDeviceDriver, self).setUp()
        self.configuration = mox.MockAnything()
        self.configuration.available_devices = ['/dev/loop1', '/dev/loop2']
        self.configuration.host = 'localhost'
        self.configuration.iscsi_port = 3260
        self.drv = BlockDeviceDriver(configuration=self.configuration)

    def test_initialize_connection(self):
        TEST_VOLUME1 = {'host': 'localhost1',
                        'provider_location': '1 2 3 /dev/loop1',
                        }
        TEST_CONNECTOR = {'host': 'localhost1'}
        self.mox.StubOutWithMock(self.drv, 'local_path')
        self.drv.local_path(TEST_VOLUME1).AndReturn('/dev/loop1')
        self.mox.ReplayAll()
        data = self.drv.initialize_connection(TEST_VOLUME1, TEST_CONNECTOR)
        self.assertEqual(data, {
            'driver_volume_type': 'local',
            'data': {'device_path': '/dev/loop1'}
        })

    def test_initialize_connection_different_hosts(self):
        TEST_CONNECTOR = {'host': 'localhost1'}
        TEST_VOLUME2 = {'host': 'localhost2',
                        'provider_location': '1 2 3 /dev/loop2',
                        }
        self.mox.StubOutWithMock(ISCSIDriver, 'initialize_connection')
        ISCSIDriver.initialize_connection(TEST_VOLUME2,
                                          TEST_CONNECTOR).AndReturn('data')
        self.mox.ReplayAll()
        data = self.drv.initialize_connection(TEST_VOLUME2, TEST_CONNECTOR)
        self.assertEqual(data, 'data')

    def test_delete_not_volume_provider_location(self):
        TEST_VOLUME2 = {'provider_location': None}
        self.mox.StubOutWithMock(self.drv, 'local_path')
        self.drv.local_path(TEST_VOLUME2).AndReturn(None)
        self.mox.StubOutWithMock(self.drv, 'clear_volume')
        self.mox.ReplayAll()
        self.drv.delete_volume(TEST_VOLUME2)

    def test_delete_volume_path_exist(self):
        TEST_VOLUME1 = {'provider_location': '1 2 3 /dev/loop1'}
        self.mox.StubOutWithMock(self.drv, 'local_path')
        path = self.drv.local_path(TEST_VOLUME1).AndReturn('/dev/loop1')
        self.mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(path).AndReturn(True)
        self.mox.StubOutWithMock(self.drv, 'clear_volume')
        self.drv.clear_volume(TEST_VOLUME1)
        self.mox.ReplayAll()
        self.drv.delete_volume(TEST_VOLUME1)

    def test_delete_path_is_not_in_list_of_available_devices(self):
        TEST_VOLUME2 = {'provider_location': '1 2 3 /dev/loop0'}
        self.mox.StubOutWithMock(self.drv, 'local_path')
        self.drv.local_path(TEST_VOLUME2).AndReturn('/dev/loop0')
        self.mox.StubOutWithMock(self.drv, 'clear_volume')
        self.mox.ReplayAll()
        self.drv.delete_volume(TEST_VOLUME2)

    def test_create_volume(self):
        TEST_VOLUME = {'size': 1,
                       'name': 'vol1'}
        self.mox.StubOutWithMock(self.drv, 'find_appropriate_size_device')
        self.drv.find_appropriate_size_device(TEST_VOLUME['size']) \
            .AndReturn('dev_path')
        self.mox.ReplayAll()
        result = self.drv.create_volume(TEST_VOLUME)
        self.assertEqual(result, {
            'provider_location': 'None:3260,None None '
                                 'None dev_path'})

    def test_update_volume_stats(self):
        self.mox.StubOutWithMock(self.drv, '_devices_sizes')
        self.drv._devices_sizes().AndReturn({'/dev/loop1': 1024,
                                             '/dev/loop2': 1024})
        self.mox.StubOutWithMock(self.drv, '_get_used_devices')
        self.drv._get_used_devices().AndReturn(set())
        self.mox.StubOutWithMock(self.configuration, 'safe_get')
        self.configuration.safe_get('volume_backend_name'). \
            AndReturn('BlockDeviceDriver')
        self.mox.ReplayAll()
        self.drv._update_volume_stats()
        self.assertEqual(self.drv._stats,
                         {'total_capacity_gb': 2,
                          'free_capacity_gb': 2,
                          'reserved_percentage':
                          self.configuration.reserved_percentage,
                          'QoS_support': False,
                          'vendor_name': "Open Source",
                          'driver_version': self.drv.VERSION,
                          'storage_protocol': 'unknown',
                          'volume_backend_name': 'BlockDeviceDriver',
                          })

    def test_create_cloned_volume(self):
        TEST_SRC = {'id': '1',
                    'size': 1,
                    'provider_location': '1 2 3 /dev/loop1'}
        TEST_VOLUME = {}
        self.mox.StubOutWithMock(self.drv, 'find_appropriate_size_device')
        dev = self.drv.find_appropriate_size_device(TEST_SRC['size']).\
            AndReturn('/dev/loop2')
        self.mox.StubOutWithMock(volutils, 'copy_volume')
        self.mox.StubOutWithMock(self.drv, 'local_path')
        self.mox.StubOutWithMock(self.drv, '_get_device_size')
        self.drv.local_path(TEST_SRC).AndReturn('/dev/loop1')
        self.drv._get_device_size('/dev/loop2').AndReturn(1)
        volutils.copy_volume('/dev/loop1', dev, 2048,
                             execute=self.drv._execute)
        self.mox.ReplayAll()
        self.assertEqual(self.drv.create_cloned_volume(TEST_VOLUME, TEST_SRC),
                         {'provider_location': 'None:3260,'
                                               'None None None /dev/loop2'})

    def test_copy_image_to_volume(self):
        TEST_VOLUME = {'provider_location': '1 2 3 /dev/loop1', 'size': 1}
        TEST_IMAGE_SERVICE = "image_service"
        TEST_IMAGE_ID = "image_id"
        self.mox.StubOutWithMock(image_utils, 'fetch_to_raw')
        self.mox.StubOutWithMock(self.drv, 'local_path')
        self.drv.local_path(TEST_VOLUME).AndReturn('/dev/loop1')
        image_utils.fetch_to_raw(context, TEST_IMAGE_SERVICE,
                                 TEST_IMAGE_ID, '/dev/loop1', size=1)
        self.mox.ReplayAll()
        self.drv.copy_image_to_volume(context, TEST_VOLUME, TEST_IMAGE_SERVICE,
                                      TEST_IMAGE_ID)

    def test_copy_volume_to_image(self):
        TEST_VOLUME = {'provider_location': '1 2 3 /dev/loop1'}
        TEST_IMAGE_SERVICE = "image_service"
        TEST_IMAGE_META = "image_meta"
        self.mox.StubOutWithMock(image_utils, 'upload_volume')
        self.mox.StubOutWithMock(self.drv, 'local_path')
        self.drv.local_path(TEST_VOLUME).AndReturn('/dev/loop1')
        image_utils.upload_volume(context, TEST_IMAGE_SERVICE,
                                  TEST_IMAGE_META, '/dev/loop1')
        self.mox.ReplayAll()
        self.drv.copy_volume_to_image(context, TEST_VOLUME, TEST_IMAGE_SERVICE,
                                      TEST_IMAGE_META)

    def test_get_used_devices(self):
        TEST_VOLUME1 = {'host': 'localhost',
                        'provider_location': '1 2 3 /dev/loop1'}
        TEST_VOLUME2 = {'host': 'localhost',
                        'provider_location': '1 2 3 /dev/loop2'}
        self.mox.StubOutWithMock(api, 'volume_get_all_by_host')
        self.mox.StubOutWithMock(context, 'get_admin_context')
        context.get_admin_context()
        api.volume_get_all_by_host(None,
                                   self.configuration.host) \
            .AndReturn([TEST_VOLUME1, TEST_VOLUME2])
        self.mox.StubOutWithMock(self.drv, 'local_path')
        path1 = self.drv.local_path(TEST_VOLUME1).AndReturn('/dev/loop1')
        path2 = self.drv.local_path(TEST_VOLUME2).AndReturn('/dev/loop2')
        self.mox.ReplayAll()
        self.assertEqual(self.drv._get_used_devices(), set([path1, path2]))

    def test_get_device_size(self):
        dev_path = '/dev/loop1'
        self.mox.StubOutWithMock(self.drv, '_execute')
        out = '2048'
        self.drv._execute('blockdev', '--getsz', dev_path,
                          run_as_root=True).AndReturn((out, None))
        self.mox.ReplayAll()
        self.assertEqual(self.drv._get_device_size(dev_path), 1)

    def test_devices_sizes(self):
        self.mox.StubOutWithMock(self.drv, '_get_device_size')
        for dev in self.configuration.available_devices:
            self.drv._get_device_size(dev).AndReturn(1)
        self.mox.ReplayAll()
        self.assertEqual(self.drv._devices_sizes(),
                         {'/dev/loop1': 1, '/dev/loop2': 1})

    def test_find_appropriate_size_device_no_free_disks(self):
        size = 1
        self.mox.StubOutWithMock(self.drv, '_devices_sizes')
        self.drv._devices_sizes().AndReturn({'/dev/loop1': 1024,
                                             '/dev/loop2': 1024})
        self.mox.StubOutWithMock(self.drv, '_get_used_devices')
        self.drv._get_used_devices().AndReturn(set(['/dev/loop1',
                                                    '/dev/loop2']))
        self.mox.ReplayAll()
        self.assertRaises(cinder.exception.CinderException,
                          self.drv.find_appropriate_size_device, size)

    def test_find_appropriate_size_device_not_big_enough_disk(self):
        size = 2
        self.mox.StubOutWithMock(self.drv, '_devices_sizes')
        self.drv._devices_sizes().AndReturn({'/dev/loop1': 1024,
                                             '/dev/loop2': 1024})
        self.mox.StubOutWithMock(self.drv, '_get_used_devices')
        self.drv._get_used_devices().AndReturn(set(['/dev/loop1']))
        self.mox.ReplayAll()
        self.assertRaises(cinder.exception.CinderException,
                          self.drv.find_appropriate_size_device, size)

    def test_find_appropriate_size_device(self):
        size = 1
        self.mox.StubOutWithMock(self.drv, '_devices_sizes')
        self.drv._devices_sizes().AndReturn({'/dev/loop1': 2048,
                                             '/dev/loop2': 1024})
        self.mox.StubOutWithMock(self.drv, '_get_used_devices')
        self.drv._get_used_devices().AndReturn(set())
        self.mox.ReplayAll()
        self.assertEqual(self.drv.find_appropriate_size_device(size),
                         '/dev/loop2')
