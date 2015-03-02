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

import mock
from oslo_config import cfg

from cinder import context
from cinder.db.sqlalchemy import api
import cinder.exception
import cinder.test
from cinder.volume import configuration as conf
from cinder.volume.drivers import block_device
from cinder.volume import utils as volutils


class TestBlockDeviceDriver(cinder.test.TestCase):
    def setUp(self):
        fake_opt = [cfg.StrOpt('fake_opt', default='fake', help='fake option')]
        super(TestBlockDeviceDriver, self).setUp()
        self.configuration = conf.Configuration(fake_opt, 'fake_group')
        self.configuration.available_devices = ['/dev/loop1', '/dev/loop2']
        self.configuration.iscsi_helper = 'tgtadm'
        self.host = 'localhost'
        self.configuration.iscsi_port = 3260
        self.configuration.volume_dd_blocksize = 1234
        self.drv = block_device.BlockDeviceDriver(
            configuration=self.configuration,
            host='localhost')

    def test_initialize_connection(self):
        TEST_VOLUME1 = {'host': 'localhost1',
                        'provider_location': '1 2 3 /dev/loop1',
                        'provider_auth': 'a b c',
                        'attached_mode': 'rw',
                        'id': 'fake-uuid'}

        TEST_CONNECTOR = {'host': 'localhost1'}

        data = self.drv.initialize_connection(TEST_VOLUME1, TEST_CONNECTOR)
        expected_data = {'data': {'auth_method': 'a',
                                  'auth_password': 'c',
                                  'auth_username': 'b',
                                  'encrypted': False,
                                  'target_discovered': False,
                                  'target_iqn': '2',
                                  'target_lun': 3,
                                  'target_portal': '1',
                                  'volume_id': 'fake-uuid'},
                         'driver_volume_type': 'iscsi'}

        self.assertEqual(expected_data, data)

    @mock.patch('cinder.volume.driver.ISCSIDriver.initialize_connection')
    def test_initialize_connection_different_hosts(self, _init_conn):
        TEST_CONNECTOR = {'host': 'localhost1'}
        TEST_VOLUME2 = {'host': 'localhost2',
                        'provider_location': '1 2 3 /dev/loop2',
                        'provider_auth': 'd e f',
                        'attached_mode': 'rw',
                        'id': 'fake-uuid-2'}
        _init_conn.return_value = 'data'

        data = self.drv.initialize_connection(TEST_VOLUME2, TEST_CONNECTOR)
        expected_data = {'data': {'auth_method': 'd',
                                  'auth_password': 'f',
                                  'auth_username': 'e',
                                  'encrypted': False,
                                  'target_discovered': False,
                                  'target_iqn': '2',
                                  'target_lun': 3,
                                  'target_portal': '1',
                                  'volume_id': 'fake-uuid-2'}}

        self.assertEqual(expected_data['data'], data['data'])

    @mock.patch('cinder.volume.drivers.block_device.BlockDeviceDriver.'
                'local_path', return_value=None)
    @mock.patch('cinder.volume.utils.clear_volume')
    def test_delete_not_volume_provider_location(self, _clear_volume,
                                                 _local_path):
        TEST_VOLUME2 = {'provider_location': None}
        self.drv.delete_volume(TEST_VOLUME2)
        _local_path.assert_called_once_with(TEST_VOLUME2)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('cinder.volume.utils.clear_volume')
    def test_delete_volume_path_exist(self, _clear_volume, _exists):
        TEST_VOLUME1 = {'provider_location': '1 2 3 /dev/loop1'}

        with mock.patch.object(self.drv, 'local_path',
                               return_value='/dev/loop1') as lp_mocked:
            with mock.patch.object(self.drv, '_get_device_size',
                                   return_value=1024) as gds_mocked:
                volutils.clear_volume(gds_mocked, lp_mocked)

                self.drv.delete_volume(TEST_VOLUME1)

                lp_mocked.assert_called_once_with(TEST_VOLUME1)
                gds_mocked.assert_called_once_with('/dev/loop1')

        self.assertTrue(_exists.called)
        self.assertTrue(_clear_volume.called)

    def test_delete_path_is_not_in_list_of_available_devices(self):
        TEST_VOLUME2 = {'provider_location': '1 2 3 /dev/loop0'}
        with mock.patch.object(self.drv, 'local_path',
                               return_value='/dev/loop0') as lp_mocked:
            self.drv.delete_volume(TEST_VOLUME2)
            lp_mocked.assert_called_once_with(TEST_VOLUME2)

    def test_create_volume(self):
        TEST_VOLUME = {'size': 1,
                       'name': 'vol1'}

        with mock.patch.object(self.drv, 'find_appropriate_size_device',
                               return_value='dev_path') as fasd_mocked:
            result = self.drv.create_volume(TEST_VOLUME)
            self.assertEqual(result, {
                'provider_location': 'dev_path'})
            fasd_mocked.assert_called_once_with(TEST_VOLUME['size'])

    def test_update_volume_stats(self):

        with mock.patch.object(self.drv, '_devices_sizes',
                               return_value={'/dev/loop1': 1024,
                                             '/dev/loop2': 1024}) as \
                ds_mocked:
            with mock.patch.object(self.drv, '_get_used_devices') as \
                    gud_mocked:
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
                gud_mocked.assert_called_once_with()
                ds_mocked.assert_called_once_with()

    @mock.patch('cinder.volume.utils.copy_volume')
    def test_create_cloned_volume(self, _copy_volume):
        TEST_SRC = {'id': '1',
                    'size': 1,
                    'provider_location': '1 2 3 /dev/loop1'}
        TEST_VOLUME = {}

        with mock.patch.object(self.drv, 'find_appropriate_size_device',
                               return_value='/dev/loop2') as fasd_mocked:
            with mock.patch.object(self.drv, '_get_device_size',
                                   return_value=1) as gds_mocked:
                with mock.patch.object(self.drv, 'local_path',
                                       return_value='/dev/loop1') as \
                        lp_mocked:
                    volutils.copy_volume('/dev/loop1', fasd_mocked, 2048,
                                         mock.sentinel,
                                         execute=self.drv._execute)

                    self.assertEqual(self.drv.create_cloned_volume(
                                     TEST_VOLUME, TEST_SRC),
                                     {'provider_location': '/dev/loop2'})
                    fasd_mocked.assert_called_once_with(TEST_SRC['size'])
                    lp_mocked.assert_called_once_with(TEST_SRC)
                    gds_mocked.assert_called_once_with('/dev/loop2')

    @mock.patch.object(cinder.image.image_utils, 'fetch_to_raw')
    def test_copy_image_to_volume(self, _fetch_to_raw):
        TEST_VOLUME = {'provider_location': '1 2 3 /dev/loop1', 'size': 1}
        TEST_IMAGE_SERVICE = "image_service"
        TEST_IMAGE_ID = "image_id"

        with mock.patch.object(self.drv, 'local_path',
                               return_value='/dev/loop1') as lp_mocked:
            self.drv.copy_image_to_volume(context, TEST_VOLUME,
                                          TEST_IMAGE_SERVICE, TEST_IMAGE_ID)
            lp_mocked.assert_called_once_with(TEST_VOLUME)

        _fetch_to_raw.assert_called_once_with(context, TEST_IMAGE_SERVICE,
                                              TEST_IMAGE_ID, '/dev/loop1',
                                              1234, size=1)

    def test_copy_volume_to_image(self):
        TEST_VOLUME = {'provider_location': '1 2 3 /dev/loop1'}
        TEST_IMAGE_SERVICE = "image_service"
        TEST_IMAGE_META = "image_meta"

        with mock.patch.object(cinder.image.image_utils, 'upload_volume') as \
                _upload_volume:
            with mock.patch.object(self.drv, 'local_path') as _local_path:
                _local_path.return_value = '/dev/loop1'
                self.drv.copy_volume_to_image(context, TEST_VOLUME,
                                              TEST_IMAGE_SERVICE,
                                              TEST_IMAGE_META)

                self.assertTrue(_local_path.called)
                _upload_volume.assert_called_once_with(context,
                                                       TEST_IMAGE_SERVICE,
                                                       TEST_IMAGE_META,
                                                       '/dev/loop1')

    def test_get_used_devices(self):
        TEST_VOLUME1 = {'host': 'localhost',
                        'provider_location': '1 2 3 /dev/loop1'}
        TEST_VOLUME2 = {'host': 'localhost',
                        'provider_location': '1 2 3 /dev/loop2'}

        def fake_local_path(vol):
            return vol['provider_location'].split()[-1]

        with mock.patch.object(api, 'volume_get_all_by_host',
                               return_value=[TEST_VOLUME1, TEST_VOLUME2]):
            with mock.patch.object(context, 'get_admin_context'):
                with mock.patch.object(self.drv, 'local_path',
                                       return_value=fake_local_path):
                    path1 = self.drv.local_path(TEST_VOLUME1)
                    path2 = self.drv.local_path(TEST_VOLUME2)
                    self.assertEqual(self.drv._get_used_devices(),
                                     set([path1, path2]))

    def test_get_device_size(self):
        dev_path = '/dev/loop1'
        out = '2048'
        with mock.patch.object(self.drv,
                               '_execute',
                               return_value=(out, None)) as _execute:
            self.assertEqual(self.drv._get_device_size(dev_path), 1)
            _execute.assert_called_once_with('blockdev', '--getsz', dev_path,
                                             run_as_root=True)

    def test_devices_sizes(self):
        with mock.patch.object(self.drv, '_get_device_size') as _get_dvc_size:
            _get_dvc_size.return_value = 1
            self.assertEqual(self.drv._devices_sizes(),
                             {'/dev/loop1': 1, '/dev/loop2': 1})

    def test_find_appropriate_size_device_no_free_disks(self):
        size = 1
        with mock.patch.object(self.drv, '_devices_sizes') as _dvc_sizes:
            with mock.patch.object(self.drv, '_get_used_devices') as \
                    _get_used_dvc:
                _dvc_sizes.return_value = {'/dev/loop1': 1024,
                                           '/dev/loop2': 1024}
                _get_used_dvc.return_value = set(['/dev/loop1', '/dev/loop2'])
                self.assertRaises(cinder.exception.CinderException,
                                  self.drv.find_appropriate_size_device, size)

    def test_find_appropriate_size_device_not_big_enough_disk(self):
        size = 2
        with mock.patch.object(self.drv, '_devices_sizes') as _dvc_sizes:
            with mock.patch.object(self.drv, '_get_used_devices') as \
                    _get_used_dvc:
                _dvc_sizes.return_value = {'/dev/loop1': 1024,
                                           '/dev/loop2': 1024}
                _get_used_dvc.return_value = set(['/dev/loop1'])
                self.assertRaises(cinder.exception.CinderException,
                                  self.drv.find_appropriate_size_device, size)

    def test_find_appropriate_size_device(self):
        size = 1
        with mock.patch.object(self.drv, '_devices_sizes') as _dvc_sizes:
            with mock.patch.object(self.drv, '_get_used_devices') as \
                    _get_used_dvc:
                _dvc_sizes.return_value = {'/dev/loop1': 2048,
                                           '/dev/loop2': 1024}
                _get_used_dvc.return_value = set()
                self.assertEqual(self.drv.find_appropriate_size_device(size),
                                 '/dev/loop2')
