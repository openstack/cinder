# Copyright (c) 2016 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import functools
import unittest

import mock
from oslo_utils import units

from cinder import exception
from cinder.tests.unit.volume.drivers.dell_emc.unity import test_adapter
from cinder.volume.drivers.dell_emc.unity import utils


def get_volume_type_extra_specs(volume_type):
    return {'provisioning:type': volume_type}


def get_volume_type_qos_specs(type_id):
    if type_id == 'invalid_backend_qos_consumer':
        ret = {'qos_specs': {'consumer': 'invalid'}}
    elif type_id == 'both_none':
        ret = {'qos_specs': {'consumer': 'back-end', 'specs': {}}}
    elif type_id == 'max_1000_iops':
        ret = {
            'qos_specs': {
                'id': 'max_1000_iops',
                'consumer': 'both',
                'specs': {
                    'maxIOPS': 1000
                }
            }
        }
    elif type_id == 'max_2_mbps':
        ret = {
            'qos_specs': {
                'id': 'max_2_mbps',
                'consumer': 'back-end',
                'specs': {
                    'maxBWS': 2
                }
            }
        }
    else:
        ret = None
    return ret


def patch_volume_types(func):
    @functools.wraps(func)
    @mock.patch(target=('cinder.volume.volume_types'
                        '.get_volume_type_extra_specs'),
                new=get_volume_type_extra_specs)
    @mock.patch(target=('cinder.volume.volume_types'
                        '.get_volume_type_qos_specs'),
                new=get_volume_type_qos_specs)
    def func_wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return func_wrapper


class UnityUtilsTest(unittest.TestCase):
    def test_validate_pool_names_filter(self):
        all_pools = list('acd')
        pool_names = utils.validate_pool_names(list('abc'), all_pools)
        self.assertIn('a', pool_names)
        self.assertIn('c', pool_names)
        self.assertNotIn('b', pool_names)
        self.assertNotIn('d', pool_names)

    def test_validate_pool_names_non_exists(self):
        def f():
            all_pools = list('abc')
            utils.validate_pool_names(list('efg'), all_pools)

        self.assertRaises(exception.VolumeBackendAPIException, f)

    def test_validate_pool_names_default(self):
        all_pools = list('ab')
        pool_names = utils.validate_pool_names([], all_pools)
        self.assertEqual(2, len(pool_names))

        pool_names = utils.validate_pool_names(None, all_pools)
        self.assertEqual(2, len(pool_names))

    def test_build_provider_location(self):
        location = utils.build_provider_location('unity', 'thin', 'ev_1', '3')
        expected = 'id^ev_1|system^unity|type^thin|version^3'
        self.assertEqual(expected, location)

    def test_extract_provider_location_version(self):
        location = 'id^ev_1|system^unity|type^thin|version^3'
        self.assertEqual('3',
                         utils.extract_provider_location(location, 'version'))

    def test_extract_provider_location_type(self):
        location = 'id^ev_1|system^unity|type^thin|version^3'
        self.assertEqual('thin',
                         utils.extract_provider_location(location, 'type'))

    def test_extract_provider_location_system(self):
        location = 'id^ev_1|system^unity|type^thin|version^3'
        self.assertEqual('unity',
                         utils.extract_provider_location(location, 'system'))

    def test_extract_provider_location_id(self):
        location = 'id^ev_1|system^unity|type^thin|version^3'
        self.assertEqual('ev_1',
                         utils.extract_provider_location(location, 'id'))

    def test_extract_provider_location_not_found(self):
        location = 'id^ev_1|system^unity|type^thin|version^3'
        self.assertIsNone(utils.extract_provider_location(location, 'na'))

    def test_extract_provider_location_none(self):
        self.assertIsNone(utils.extract_provider_location(None, 'abc'))

    def test_extract_iscsi_uids(self):
        connector = {'host': 'fake_host',
                     'initiator': 'fake_iqn'}
        self.assertEqual(['fake_iqn'],
                         utils.extract_iscsi_uids(connector))

    def test_extract_iscsi_uids_not_found(self):
        connector = {'host': 'fake_host'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          utils.extract_iscsi_uids,
                          connector)

    def test_extract_fc_uids(self):
        connector = {'host': 'fake_host',
                     'wwnns': ['1111111111111111',
                               '2222222222222222'],
                     'wwpns': ['3333333333333333',
                               '4444444444444444']
                     }
        self.assertEqual(['11:11:11:11:11:11:11:11:33:33:33:33:33:33:33:33',
                          '22:22:22:22:22:22:22:22:44:44:44:44:44:44:44:44', ],
                         utils.extract_fc_uids(connector))

    def test_extract_fc_uids_not_found(self):
        connector = {'host': 'fake_host'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          utils.extract_iscsi_uids,
                          connector)

    def test_byte_to_gib(self):
        self.assertEqual(5, utils.byte_to_gib(5 * units.Gi))

    def test_byte_to_mib(self):
        self.assertEqual(5, utils.byte_to_mib(5 * units.Mi))

    def test_gib_to_mib(self):
        self.assertEqual(5 * units.Gi / units.Mi, utils.gib_to_mib(5))

    def test_convert_ip_to_portal(self):
        self.assertEqual('1.2.3.4:3260', utils.convert_ip_to_portal('1.2.3.4'))

    def test_convert_to_itor_tgt_map(self):
        zone_mapping = {
            'san_1': {
                'initiator_port_wwn_list':
                    ('200000051e55a100', '200000051e55a121'),
                'target_port_wwn_list':
                    ('100000051e55a100', '100000051e55a121')
            }
        }
        ret = utils.convert_to_itor_tgt_map(zone_mapping)
        self.assertEqual(['100000051e55a100', '100000051e55a121'], ret[0])
        mapping = ret[1]
        targets = ('100000051e55a100', '100000051e55a121')
        self.assertEqual(targets, mapping['200000051e55a100'])
        self.assertEqual(targets, mapping['200000051e55a121'])

    def test_get_pool_name(self):
        volume = test_adapter.MockOSResource(host='host@backend#pool_name')
        self.assertEqual('pool_name', utils.get_pool_name(volume))

    def test_ignore_exception(self):
        class IgnoredException(Exception):
            pass

        def f():
            raise IgnoredException('any exception')

        try:
            utils.ignore_exception(f)
        except IgnoredException:
            self.fail('should not raise any exception.')

    def test_assure_cleanup(self):
        data = [0]

        def _enter():
            data[0] += 10
            return data[0]

        def _exit(x):
            data[0] = x - 1

        ctx = utils.assure_cleanup(_enter, _exit, True)
        with ctx as r:
            self.assertEqual(10, r)

        self.assertEqual(9, data[0])

    def test_get_backend_qos_specs_type_none(self):
        volume = test_adapter.MockOSResource(volume_type_id=None)
        ret = utils.get_backend_qos_specs(volume)
        self.assertIsNone(ret)

    @patch_volume_types
    def test_get_backend_qos_specs_none(self):
        volume = test_adapter.MockOSResource(volume_type_id='no_qos')
        ret = utils.get_backend_qos_specs(volume)
        self.assertIsNone(ret)

    @patch_volume_types
    def test_get_backend_qos_invalid_consumer(self):
        volume = test_adapter.MockOSResource(
            volume_type_id='invalid_backend_qos_consumer')
        ret = utils.get_backend_qos_specs(volume)
        self.assertIsNone(ret)

    @patch_volume_types
    def test_get_backend_qos_both_none(self):
        volume = test_adapter.MockOSResource(volume_type_id='both_none')
        ret = utils.get_backend_qos_specs(volume)
        self.assertIsNone(ret)

    @patch_volume_types
    def test_get_backend_qos_iops(self):
        volume = test_adapter.MockOSResource(volume_type_id='max_1000_iops')
        ret = utils.get_backend_qos_specs(volume)
        expected = {'maxBWS': None, 'id': 'max_1000_iops', 'maxIOPS': 1000}
        self.assertEqual(expected, ret)

    @patch_volume_types
    def test_get_backend_qos_mbps(self):
        volume = test_adapter.MockOSResource(volume_type_id='max_2_mbps')
        ret = utils.get_backend_qos_specs(volume)
        expected = {'maxBWS': 2, 'id': 'max_2_mbps', 'maxIOPS': None}
        self.assertEqual(expected, ret)

    def test_remove_empty(self):
        option = mock.Mock()
        value_list = [' pool1', 'pool2 ', '     pool3  ']
        ret = utils.remove_empty(option, value_list)
        expected = ['pool1', 'pool2', 'pool3']
        self.assertListEqual(expected, ret)

    def test_remove_empty_none(self):
        option = mock.Mock()
        value_list = None
        ret = utils.remove_empty(option, value_list)
        expected = None
        self.assertEqual(expected, ret)

    def test_remove_empty_empty_list(self):
        option = mock.Mock()
        value_list = []
        ret = utils.remove_empty(option, value_list)
        expected = None
        self.assertEqual(expected, ret)
