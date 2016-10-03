# Copyright (c) 2015 by Tegile Systems, Inc.
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
Volume driver Test for Tegile storage.
"""

import mock

from cinder import context
from cinder.exception import TegileAPIException
from cinder import test
from cinder.volume.drivers import tegile

BASE_DRIVER = tegile.TegileIntelliFlashVolumeDriver
ISCSI_DRIVER = tegile.TegileISCSIDriver
FC_DRIVER = tegile.TegileFCDriver

test_config = mock.Mock()
test_config.san_ip = 'some-ip'
test_config.san_login = 'some-user'
test_config.san_password = 'some-password'
test_config.san_is_local = True
test_config.tegile_default_pool = 'random-pool'
test_config.tegile_default_project = 'random-project'
test_config.volume_backend_name = "unittest"

test_volume = {'host': 'node#testPool',
               'name': 'testvol',
               'id': 'a24c2ee8-525a-4406-8ccd-8d38688f8e9e',
               '_name_id': 'testvol',
               'metadata': {'project': 'testProj'},
               'provider_location': None,
               'size': 10}

test_snapshot = {'name': 'testSnap',
                 'id': '07ae9978-5445-405e-8881-28f2adfee732',
                 'volume': {'host': 'node#testPool',
                            'size': 1,
                            '_name_id': 'testvol'
                            }
                 }

array_stats = {'total_capacity_gb': 4569.199686084874,
               'free_capacity_gb': 4565.381390112452,
               'pools': [{'total_capacity_gb': 913.5,
                          'QoS_support': False,
                          'free_capacity_gb': 911.812650680542,
                          'reserved_percentage': 0,
                          'pool_name': 'pyramid'
                          },
                         {'total_capacity_gb': 2742.1996604874,
                          'QoS_support': False,
                          'free_capacity_gb': 2740.148867149747,
                          'reserved_percentage': 0,
                          'pool_name': 'cobalt'
                          },
                         {'total_capacity_gb': 913.5,
                          'QoS_support': False,
                          'free_capacity_gb': 913.4198722839355,
                          'reserved_percentage': 0,
                          'pool_name': 'test'
                          }]
               }


class FakeTegileService(object):
    @staticmethod
    def send_api_request(method, params=None,
                         request_type='post',
                         api_service='v2',
                         fine_logging=False):
        if method is 'createVolume':
            return ''
        elif method is 'deleteVolume':
            return ''
        elif method is 'createVolumeSnapshot':
            return ''
        elif method is 'deleteVolumeSnapshot':
            return ''
        elif method is 'cloneVolumeSnapshot':
            return ''
        elif method is 'listPools':
            return ''
        elif method is 'resizeVolume':
            return ''
        elif method is 'getVolumeSizeinGB':
            return 25
        elif method is 'getISCSIMappingForVolume':
            return {'target_lun': 27,
                    'target_iqn': 'iqn.2012-02.com.tegile:openstack-cobalt',
                    'target_portal': '10.68.103.106:3260'
                    }
        elif method is 'getFCPortsForVolume':
            return {'target_lun': 12,
                    'initiator_target_map':
                        '{"21000024ff59bb6e":["21000024ff578701",],'
                        '"21000024ff59bb6f":["21000024ff578700",],}',
                    'target_wwn': '["21000024ff578700","21000024ff578701",]'}
        elif method is 'getArrayStats':
            return array_stats


fake_tegile_backend = FakeTegileService()


class FakeTegileServiceFail(object):
    @staticmethod
    def send_api_request(method, params=None,
                         request_type='post',
                         api_service='v2',
                         fine_logging=False):
        raise TegileAPIException


fake_tegile_backend_fail = FakeTegileServiceFail()


class TegileIntelliFlashVolumeDriverTestCase(test.TestCase):
    def setUp(self):
        self.ctxt = context.get_admin_context()
        self.configuration = test_config
        super(TegileIntelliFlashVolumeDriverTestCase, self).setUp()

    def test_create_volume(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            self.assertEqual({
                'metadata': {'pool': 'testPool',
                             'project': test_config.tegile_default_project
                             }
            }, tegile_driver.create_volume(test_volume))

    def test_create_volume_fail(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend_fail):
            self.assertRaises(TegileAPIException,
                              tegile_driver.create_volume,
                              test_volume)

    def test_delete_volume(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            tegile_driver.delete_volume(test_volume)

    def test_delete_volume_fail(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend_fail):
            self.assertRaises(TegileAPIException,
                              tegile_driver.delete_volume,
                              test_volume)

    def test_create_snapshot(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            tegile_driver.create_snapshot(test_snapshot)

    def test_create_snapshot_fail(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend_fail):
            self.assertRaises(TegileAPIException,
                              tegile_driver.create_snapshot,
                              test_snapshot)

    def test_delete_snapshot(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            tegile_driver.delete_snapshot(test_snapshot)

    def test_delete_snapshot_fail(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend_fail):
            self.assertRaises(TegileAPIException,
                              tegile_driver.delete_snapshot,
                              test_snapshot)

    def test_create_volume_from_snapshot(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            self.assertEqual({
                'metadata': {'pool': 'testPool',
                             'project': test_config.tegile_default_project
                             }
            }, tegile_driver.create_volume_from_snapshot(test_volume,
                                                         test_snapshot))

    def test_create_volume_from_snapshot_fail(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend_fail):
            self.assertRaises(TegileAPIException,
                              tegile_driver.create_volume_from_snapshot,
                              test_volume, test_snapshot)

    def test_create_cloned_volume(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            self.assertEqual({'metadata': {'project': 'testProj',
                                           'pool': 'testPool'}},
                             tegile_driver.create_cloned_volume(test_volume,
                                                                test_volume))

    def test_create_cloned_volume_fail(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend_fail):
            self.assertRaises(TegileAPIException,
                              tegile_driver.create_cloned_volume,
                              test_volume, test_volume)

    def test_get_volume_stats(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            self.assertEqual({'driver_version': '1.0.0',
                              'free_capacity_gb': 4565.381390112452,
                              'pools': [{'QoS_support': False,
                                         'allocated_capacity_gb': 0.0,
                                         'free_capacity_gb': 911.812650680542,
                                         'pool_name': 'pyramid',
                                         'reserved_percentage': 0,
                                         'total_capacity_gb': 913.5},
                                        {'QoS_support': False,
                                         'allocated_capacity_gb': 0.0,
                                         'free_capacity_gb': 2740.148867149747,
                                         'pool_name': 'cobalt',
                                         'reserved_percentage': 0,
                                         'total_capacity_gb': 2742.1996604874},
                                        {'QoS_support': False,
                                         'allocated_capacity_gb': 0.0,
                                         'free_capacity_gb': 913.4198722839355,
                                         'pool_name': 'test',
                                         'reserved_percentage': 0,
                                         'total_capacity_gb': 913.5}],
                              'storage_protocol': 'iSCSI',
                              'total_capacity_gb': 4569.199686084874,
                              'vendor_name': 'Tegile Systems Inc.',
                              'volume_backend_name': 'unittest'},
                             tegile_driver.get_volume_stats(True))

    def test_get_pool(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            self.assertEqual('testPool', tegile_driver.get_pool(test_volume))

    def test_extend_volume(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            tegile_driver.extend_volume(test_volume, 12)

    def test_extend_volume_fail(self):
        tegile_driver = self.get_object(self.configuration)
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend_fail):
            self.assertRaises(TegileAPIException,
                              tegile_driver.extend_volume,
                              test_volume, 30)

    def test_manage_existing(self):
        tegile_driver = self.get_object(self.configuration)
        existing_ref = {'name': 'existingvol'}
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            self.assertEqual({'metadata': {'pool': 'testPool',
                                           'project': 'testProj'
                                           },
                              '_name_id': ('existingvol',)
                              }, tegile_driver.manage_existing(test_volume,
                                                               existing_ref))

    def test_manage_existing_get_size(self):
        tegile_driver = self.get_object(self.configuration)
        existing_ref = {'name': 'existingvol'}
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            self.assertEqual(25,
                             tegile_driver.manage_existing_get_size(
                                 test_volume,
                                 existing_ref))

    def test_manage_existing_get_size_fail(self):
        tegile_driver = self.get_object(self.configuration)
        existing_ref = {'name': 'existingvol'}
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend_fail):
            self.assertRaises(TegileAPIException,
                              tegile_driver.manage_existing_get_size,
                              test_volume, existing_ref)

    def get_object(self, configuration):
        class TegileBaseDriver(BASE_DRIVER):
            def initialize_connection(self, volume, connector, **kwargs):
                pass

            def terminate_connection(self, volume, connector,
                                     force=False, **kwargs):
                pass

        return TegileBaseDriver(configuration=self.configuration)


class TegileISCSIDriverTestCase(test.TestCase):
    def setUp(self):
        super(TegileISCSIDriverTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.configuration = test_config
        self.configuration.chap_username = 'fake'
        self.configuration.chap_password = "test"

    def test_initialize_connection(self):
        tegile_driver = self.get_object(self.configuration)
        connector = {'initiator': 'iqn.1993-08.org.debian:01:d0bb9a834f8'}
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            self.assertEqual(
                {'data': {'auth_method': 'CHAP',
                          'discard': False,
                          'target_discovered': (False,),
                          'auth_password': 'test',
                          'auth_username': 'fake',
                          'target_iqn': 'iqn.2012-02.'
                                        'com.tegile:openstack-cobalt',
                          'target_lun': 27,
                          'target_portal': '10.68.103.106:3260',
                          'volume_id': (
                              'a24c2ee8-525a-4406-8ccd-8d38688f8e9e',)},
                 'driver_volume_type': 'iscsi'},
                tegile_driver.initialize_connection(test_volume,
                                                    connector))

    def get_object(self, configuration):
        return ISCSI_DRIVER(configuration=configuration)


class TegileFCDriverTestCase(test.TestCase):
    def setUp(self):
        super(TegileFCDriverTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.configuration = test_config

    def test_initialize_connection(self):
        tegile_driver = self.get_object(self.configuration)
        connector = {'wwpns': ['500110a0001a3990']}
        with mock.patch.object(tegile_driver,
                               '_api_executor',
                               fake_tegile_backend):
            self.assertEqual({'data': {'encrypted': False,
                                       'initiator_target_map': {
                                           '21000024ff59bb6e':
                                               ['21000024ff578701'],
                                           '21000024ff59bb6f':
                                               ['21000024ff578700']
                                       },
                                       'target_discovered': False,
                                       'target_lun': 12,
                                       'target_wwn':
                                           ['21000024ff578700',
                                            '21000024ff578701']},
                              'driver_volume_type': 'fibre_channel'},
                             tegile_driver.initialize_connection(
                                 test_volume,
                                 connector))

    def get_object(self, configuration):
        return FC_DRIVER(configuration=configuration)
