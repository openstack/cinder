# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
# Copyright (c) 2016 Michael Price.  All rights reserved.
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
Mock unit tests for the NetApp driver utility module
"""

import copy
import platform
from unittest import mock

import ddt
from oslo_concurrency import processutils as putils

from cinder import context
from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.netapp.dataontap.client import (
    fakes as zapi_fakes)
import cinder.tests.unit.volume.drivers.netapp.fakes as fake
from cinder import version
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import qos_specs
from cinder.volume import volume_types


@ddt.ddt
class NetAppDriverUtilsTestCase(test.TestCase):

    @mock.patch.object(na_utils, 'LOG', mock.Mock())
    def test_validate_instantiation_proxy(self):
        kwargs = {'netapp_mode': 'proxy'}
        na_utils.validate_instantiation(**kwargs)
        na_utils.LOG.warning.assert_not_called()

    @mock.patch.object(na_utils, 'LOG', mock.Mock())
    def test_validate_instantiation_no_proxy(self):
        kwargs = {'netapp_mode': 'asdf'}
        na_utils.validate_instantiation(**kwargs)
        na_utils.LOG.warning.assert_called_once()

    def test_check_flags(self):

        class TestClass(object):
            pass

        required_flags = ['flag1', 'flag2']
        configuration = TestClass()
        setattr(configuration, 'flag1', 'value1')
        setattr(configuration, 'flag3', 'value3')
        self.assertRaises(exception.InvalidInput, na_utils.check_flags,
                          required_flags, configuration)

        setattr(configuration, 'flag2', 'value2')
        self.assertIsNone(na_utils.check_flags(required_flags, configuration))

    def test_to_bool(self):
        self.assertTrue(na_utils.to_bool(True))
        self.assertTrue(na_utils.to_bool('true'))
        self.assertTrue(na_utils.to_bool('yes'))
        self.assertTrue(na_utils.to_bool('y'))
        self.assertTrue(na_utils.to_bool(1))
        self.assertTrue(na_utils.to_bool('1'))
        self.assertFalse(na_utils.to_bool(False))
        self.assertFalse(na_utils.to_bool('false'))
        self.assertFalse(na_utils.to_bool('asdf'))
        self.assertFalse(na_utils.to_bool('no'))
        self.assertFalse(na_utils.to_bool('n'))
        self.assertFalse(na_utils.to_bool(0))
        self.assertFalse(na_utils.to_bool('0'))
        self.assertFalse(na_utils.to_bool(2))
        self.assertFalse(na_utils.to_bool('2'))

    def test_set_safe_attr(self):

        fake_object = mock.Mock()
        fake_object.fake_attr = None

        # test initial checks
        self.assertFalse(na_utils.set_safe_attr(None, fake_object, None))
        self.assertFalse(na_utils.set_safe_attr(fake_object, None, None))
        self.assertFalse(na_utils.set_safe_attr(fake_object, 'fake_attr',
                                                None))

        # test value isn't changed if it shouldn't be and retval is False
        fake_object.fake_attr = 'fake_value'
        self.assertFalse(na_utils.set_safe_attr(fake_object, 'fake_attr',
                                                'fake_value'))
        self.assertEqual('fake_value', fake_object.fake_attr)

        # test value is changed if it should be and retval is True
        self.assertTrue(na_utils.set_safe_attr(fake_object, 'fake_attr',
                                               'new_fake_value'))
        self.assertEqual('new_fake_value', fake_object.fake_attr)

    def test_round_down(self):
        self.assertAlmostEqual(na_utils.round_down(5.567), 5.56)
        self.assertAlmostEqual(na_utils.round_down(5.567, '0.00'), 5.56)
        self.assertAlmostEqual(na_utils.round_down(5.567, '0.0'), 5.5)
        self.assertAlmostEqual(na_utils.round_down(5.567, '0'), 5)
        self.assertAlmostEqual(na_utils.round_down(0, '0.00'), 0)
        self.assertAlmostEqual(na_utils.round_down(-5.567), -5.56)
        self.assertAlmostEqual(na_utils.round_down(-5.567, '0.00'), -5.56)
        self.assertAlmostEqual(na_utils.round_down(-5.567, '0.0'), -5.5)
        self.assertAlmostEqual(na_utils.round_down(-5.567, '0'), -5)

    def test_iscsi_connection_properties(self):
        actual_properties = na_utils.get_iscsi_connection_properties(
            fake.ISCSI_FAKE_LUN_ID, fake.ISCSI_FAKE_VOLUME,
            [fake.ISCSI_FAKE_IQN, fake.ISCSI_FAKE_IQN2],
            [fake.ISCSI_FAKE_ADDRESS_IPV4, fake.ISCSI_FAKE_ADDRESS2_IPV4],
            [fake.ISCSI_FAKE_PORT, fake.ISCSI_FAKE_PORT])

        actual_properties_mapped = actual_properties['data']

        self.assertDictEqual(actual_properties_mapped,
                             fake.ISCSI_MP_TARGET_INFO_DICT)

    def test_iscsi_connection_properties_single_iqn(self):
        actual_properties = na_utils.get_iscsi_connection_properties(
            fake.ISCSI_FAKE_LUN_ID, fake.ISCSI_FAKE_VOLUME,
            fake.ISCSI_FAKE_IQN,
            [fake.ISCSI_FAKE_ADDRESS_IPV4, fake.ISCSI_FAKE_ADDRESS2_IPV4],
            [fake.ISCSI_FAKE_PORT, fake.ISCSI_FAKE_PORT])

        actual_properties_mapped = actual_properties['data']
        expected = fake.ISCSI_MP_TARGET_INFO_DICT.copy()
        expected['target_iqns'][1] = expected['target_iqns'][0]

        self.assertDictEqual(actual_properties_mapped,
                             fake.ISCSI_MP_TARGET_INFO_DICT)

    def test_iscsi_connection_lun_id_type_str(self):
        FAKE_LUN_ID = '1'

        actual_properties = na_utils.get_iscsi_connection_properties(
            FAKE_LUN_ID, fake.ISCSI_FAKE_VOLUME, fake.ISCSI_FAKE_IQN,
            [fake.ISCSI_FAKE_ADDRESS_IPV4], [fake.ISCSI_FAKE_PORT])

        actual_properties_mapped = actual_properties['data']

        self.assertIs(int, type(actual_properties_mapped['target_lun']))
        self.assertDictEqual(actual_properties_mapped,
                             fake.FC_ISCSI_TARGET_INFO_DICT)

    def test_iscsi_connection_lun_id_type_dict(self):
        FAKE_LUN_ID = {'id': 'fake_id'}

        self.assertRaises(TypeError, na_utils.get_iscsi_connection_properties,
                          FAKE_LUN_ID, fake.ISCSI_FAKE_VOLUME,
                          fake.ISCSI_FAKE_IQN, [fake.ISCSI_FAKE_ADDRESS_IPV4],
                          [fake.ISCSI_FAKE_PORT])

    def test_iscsi_connection_properties_ipv6(self):
        actual_properties = na_utils.get_iscsi_connection_properties(
            '1', fake.ISCSI_FAKE_VOLUME_NO_AUTH, fake.ISCSI_FAKE_IQN,
            [fake.ISCSI_FAKE_ADDRESS_IPV6], [fake.ISCSI_FAKE_PORT])

        self.assertDictEqual(actual_properties['data'],
                             fake.FC_ISCSI_TARGET_INFO_DICT_IPV6)

    def test_get_volume_extra_specs(self):
        fake_extra_specs = {'fake_key': 'fake_value'}
        fake_volume_type = {'extra_specs': fake_extra_specs}
        fake_volume = {'volume_type_id': 'fake_volume_type_id'}
        self.mock_object(context, 'get_admin_context')
        self.mock_object(volume_types, 'get_volume_type',
                         return_value=fake_volume_type)
        self.mock_object(na_utils, 'log_extra_spec_warnings')

        result = na_utils.get_volume_extra_specs(fake_volume)

        self.assertEqual(fake_extra_specs, result)

    def test_trace_filter_func_api(self):
        na_utils.setup_api_trace_pattern("^(?!(perf)).*$")
        na_element = zapi_fakes.FAKE_NA_ELEMENT
        all_args = {'na_element': na_element}
        self.assertTrue(na_utils.trace_filter_func_api(all_args))

    def test_trace_filter_func_api_invalid(self):
        all_args = {'fake': 'not_na_element'}
        self.assertTrue(na_utils.trace_filter_func_api(all_args))

    def test_trace_filter_func_api_filtered(self):
        na_utils.setup_api_trace_pattern("^(?!(perf)).*$")
        na_element = netapp_api.NaElement("perf-object-counter-list-info")
        all_args = {'na_element': na_element}
        self.assertFalse(na_utils.trace_filter_func_api(all_args))

    def test_get_volume_extra_specs_no_type_id(self):
        fake_volume = {}
        self.mock_object(context, 'get_admin_context')
        self.mock_object(volume_types, 'get_volume_type')
        self.mock_object(na_utils, 'log_extra_spec_warnings')

        result = na_utils.get_volume_extra_specs(fake_volume)

        self.assertEqual({}, result)

    def test_get_volume_extra_specs_no_volume_type(self):
        fake_volume = {'volume_type_id': 'fake_volume_type_id'}
        self.mock_object(context, 'get_admin_context')
        self.mock_object(volume_types, 'get_volume_type', return_value=None)
        self.mock_object(na_utils, 'log_extra_spec_warnings')

        result = na_utils.get_volume_extra_specs(fake_volume)

        self.assertEqual({}, result)

    def test_log_extra_spec_warnings_obsolete_specs(self):

        mock_log = self.mock_object(na_utils.LOG, 'warning')

        na_utils.log_extra_spec_warnings({'netapp:raid_type': 'raid4'})

        mock_log.assert_called_once()

    def test_log_extra_spec_warnings_deprecated_specs(self):

        mock_log = self.mock_object(na_utils.LOG, 'warning')

        na_utils.log_extra_spec_warnings({'netapp_thick_provisioned': 'true'})

        mock_log.assert_called_once()

    def test_validate_qos_spec(self):
        qos_spec = fake.QOS_SPEC

        # Just return without raising an exception.
        na_utils.validate_qos_spec(qos_spec)

    def test_validate_qos_spec_none(self):
        qos_spec = None

        # Just return without raising an exception.
        na_utils.validate_qos_spec(qos_spec)

    def test_validate_qos_spec_adaptive(self):
        # Just return without raising an exception.
        na_utils.validate_qos_spec(fake.ADAPTIVE_QOS_SPEC)

    def test_validate_qos_spec_keys_weirdly_cased(self):
        qos_spec = {'mAxIopS': 33000, 'mInIopS': 0}

        # Just return without raising an exception.
        na_utils.validate_qos_spec(qos_spec)

    def test_validate_qos_spec_bad_key_max_flops(self):
        qos_spec = {'maxFlops': 33000}

        self.assertRaises(exception.Invalid,
                          na_utils.validate_qos_spec,
                          qos_spec)

    def test_validate_qos_spec_bad_key_min_bps(self):
        qos_spec = {'minBps': 33000}

        self.assertRaises(exception.Invalid,
                          na_utils.validate_qos_spec,
                          qos_spec)

    def test_validate_qos_spec_bad_key_min_bps_per_gib(self):
        qos_spec = {'minBPSperGiB': 33000}

        self.assertRaises(exception.Invalid,
                          na_utils.validate_qos_spec,
                          qos_spec)

    def test_validate_qos_spec_bad_key_combination_max_iops_max_bps(self):
        qos_spec = {'maxIOPS': 33000, 'maxBPS': 10000000}

        self.assertRaises(exception.Invalid,
                          na_utils.validate_qos_spec,
                          qos_spec)

    def test_validate_qos_spec_bad_key_combination_miniops_miniopspergib(self):
        qos_spec = {'minIOPS': 33000, 'minIOPSperGiB': 10000000}
        self.assertRaises(exception.Invalid,
                          na_utils.validate_qos_spec,
                          qos_spec)

    def test_validate_qos_spec_bad_key_combination_aqos_qos_max(self):
        qos_spec = {'peakIOPSperGiB': 33000, 'maxIOPS': 33000}
        self.assertRaises(exception.Invalid,
                          na_utils.validate_qos_spec,
                          qos_spec)

    def test_validate_qos_spec_bad_key_combination_aqos_qos_min(self):
        qos_spec = {'absoluteMinIOPS': 33000, 'minIOPS': 33000}
        self.assertRaises(exception.Invalid,
                          na_utils.validate_qos_spec,
                          qos_spec)

    def test_validate_qos_spec_bad_key_combination_aqos_qos_min_max(self):
        qos_spec = {
            'expectedIOPSperGiB': 33000,
            'minIOPS': 33000,
            'maxIOPS': 33000,
        }
        self.assertRaises(exception.Invalid,
                          na_utils.validate_qos_spec,
                          qos_spec)

    def test_validate_qos_spec_adaptive_and_non_adaptive(self):
        qos_spec = fake.INVALID_QOS_POLICY_GROUP_INFO_STANDARD_AND_ADAPTIVE

        self.assertRaises(exception.Invalid,
                          na_utils.validate_qos_spec,
                          qos_spec)

    def test_map_qos_spec_none(self):
        qos_spec = None

        result = na_utils.map_qos_spec(qos_spec, fake.VOLUME)

        self.assertIsNone(result)

    def test_map_qos_spec_bad_key_combination_miniops_maxbpspergib(self):
        qos_spec = {'minIOPS': 33000, 'maxBPSperGiB': 10000000}

        self.assertRaises(exception.Invalid,
                          na_utils.map_qos_spec,
                          qos_spec,
                          fake.VOLUME)

    def test_map_qos_spec_bad_key_combination_min_iops_max_bps(self):
        qos_spec = {'minIOPS': 33000, 'maxBPS': 10000000}

        self.assertRaises(exception.Invalid,
                          na_utils.map_qos_spec,
                          qos_spec,
                          fake.VOLUME)

    def test_map_qos_spec_miniops_greater_than_maxiops(self):
        qos_spec = {'minIOPS': 33001, 'maxIOPS': 33000}

        self.assertRaises(exception.Invalid,
                          na_utils.map_qos_spec,
                          qos_spec,
                          fake.VOLUME)

    def test_map_qos_spec_maxiops(self):
        qos_spec = {'maxIOPs': 33000}
        mock_get_name = self.mock_object(na_utils, 'get_qos_policy_group_name')
        mock_get_name.return_value = 'fake_qos_policy'
        expected = {
            'policy_name': 'fake_qos_policy',
            'max_throughput': '33000iops',
        }

        result = na_utils.map_qos_spec(qos_spec, fake.VOLUME)

        self.assertEqual(expected, result)

    def test_map_qos_spec_maxiopspergib(self):
        qos_spec = {'maxIOPSperGiB': 1000}
        mock_get_name = self.mock_object(na_utils, 'get_qos_policy_group_name')
        mock_get_name.return_value = 'fake_qos_policy'
        expected = {
            'policy_name': 'fake_qos_policy',
            'max_throughput': '42000iops',
        }

        result = na_utils.map_qos_spec(qos_spec, fake.VOLUME)

        self.assertEqual(expected, result)

    def test_map_qos_spec_miniopspergib_maxiopspergib(self):
        qos_spec = {'minIOPSperGiB': 1000, 'maxIOPSperGiB': 1000}
        mock_get_name = self.mock_object(na_utils, 'get_qos_policy_group_name')
        mock_get_name.return_value = 'fake_qos_policy'
        expected = {
            'policy_name': 'fake_qos_policy',
            'min_throughput': '42000iops',
            'max_throughput': '42000iops',
        }

        result = na_utils.map_qos_spec(qos_spec, fake.VOLUME)

        self.assertEqual(expected, result)

    def test_map_qos_spec_maxbps(self):
        qos_spec = {'maxBPS': 1000000}
        mock_get_name = self.mock_object(na_utils, 'get_qos_policy_group_name')
        mock_get_name.return_value = 'fake_qos_policy'
        expected = {
            'policy_name': 'fake_qos_policy',
            'max_throughput': '1000000B/s',
        }

        result = na_utils.map_qos_spec(qos_spec, fake.VOLUME)

        self.assertEqual(expected, result)

    def test_map_qos_spec_maxbpspergib(self):
        qos_spec = {'maxBPSperGiB': 100000}
        mock_get_name = self.mock_object(na_utils, 'get_qos_policy_group_name')
        mock_get_name.return_value = 'fake_qos_policy'
        expected = {
            'policy_name': 'fake_qos_policy',
            'max_throughput': '4200000B/s',
        }

        result = na_utils.map_qos_spec(qos_spec, fake.VOLUME)

        self.assertEqual(expected, result)

    def test_map_qos_spec_no_key_present(self):
        qos_spec = {}
        mock_get_name = self.mock_object(na_utils, 'get_qos_policy_group_name')
        mock_get_name.return_value = 'fake_qos_policy'
        expected = {
            'policy_name': 'fake_qos_policy',
        }

        result = na_utils.map_qos_spec(qos_spec, fake.VOLUME)

        self.assertEqual(expected, result)

    def test_map_qos_spec_miniops_maxiops(self):
        qos_spec = {'minIOPs': 25000, 'maxIOPs': 33000}
        mock_get_name = self.mock_object(na_utils, 'get_qos_policy_group_name')
        mock_get_name.return_value = 'fake_qos_policy'
        expected = {
            'policy_name': 'fake_qos_policy',
            'min_throughput': '25000iops',
            'max_throughput': '33000iops',
        }

        result = na_utils.map_qos_spec(qos_spec, fake.VOLUME)

        self.assertEqual(expected, result)

    def test_map_aqos_spec(self):
        qos_spec = {
            'expectedIOPSperGiB': '128',
            'peakIOPSperGiB': '512',
            'expectedIOPSAllocation': 'used-space',
            'peakIOPSAllocation': 'used-space',
            'absoluteMinIOPS': '75',
            'blockSize': 'ANY',
        }
        mock_get_name = self.mock_object(na_utils, 'get_qos_policy_group_name')
        mock_get_name.return_value = 'fake_qos_policy'
        expected = {
            'expected_iops': '128IOPS/GB',
            'peak_iops': '512IOPS/GB',
            'expected_iops_allocation': 'used-space',
            'peak_iops_allocation': 'used-space',
            'absolute_min_iops': '75IOPS',
            'block_size': 'ANY',
            'policy_name': 'fake_qos_policy',
        }

        result = na_utils.map_aqos_spec(qos_spec, fake.VOLUME)

        self.assertEqual(expected, result)

    @ddt.data({'expectedIOPSperGiB': '528', 'peakIOPSperGiB': '128'},
              {'expectedIOPSperGiB': '528'})
    def test_map_aqos_spec_error(self, qos_spec):
        mock_get_name = self.mock_object(na_utils, 'get_qos_policy_group_name')
        mock_get_name.return_value = 'fake_qos_policy'

        self.assertRaises(exception.Invalid, na_utils.map_aqos_spec, qos_spec,
                          fake.VOLUME)

    def test_is_qos_adaptive_adaptive_spec(self):
        aqos_spec = fake.ADAPTIVE_QOS_SPEC

        self.assertTrue(na_utils.is_qos_adaptive(aqos_spec))

    def test_is_qos_adaptive_weirdly_cased_adaptive_spec(self):
        aqos_spec = {'expecTEDiopsPERgib': '128IOPS/GB'}

        self.assertTrue(na_utils.is_qos_adaptive(aqos_spec))

    def test_is_qos_adaptive_non_adaptive_spec(self):
        qos_spec = fake.QOS_SPEC

        self.assertFalse(na_utils.is_qos_adaptive(qos_spec))

    def test_is_qos_policy_group_spec_adaptive_adaptive_spec(self):
        aqos_spec = {
            'spec': {
                'expected_iops': '128IOPS/GB',
                'peak_iops': '512IOPS/GB',
                'expected_iops_allocation': 'used-space',
                'absolute_min_iops': '75IOPS',
                'block_size': 'ANY',
                'policy_name': 'fake_policy_name',
            }
        }

        self.assertTrue(na_utils.is_qos_policy_group_spec_adaptive(aqos_spec))

    def test_is_qos_policy_group_spec_adaptive_none(self):
        qos_spec = None

        self.assertFalse(na_utils.is_qos_policy_group_spec_adaptive(qos_spec))

    def test_is_qos_policy_group_spec_adaptive_legacy(self):
        qos_spec = {
            'legacy': fake.LEGACY_QOS,
        }

        self.assertFalse(na_utils.is_qos_policy_group_spec_adaptive(qos_spec))

    def test_is_qos_policy_group_spec_adaptive_non_adaptive_spec(self):
        qos_spec = {
            'spec': {
                'max_throughput': '21834289B/s',
                'policy_name': 'fake_policy_name',
            }
        }

        self.assertFalse(na_utils.is_qos_policy_group_spec_adaptive(qos_spec))

    def test_policy_group_qos_spec_is_adaptive_invalid_spec(self):
        qos_spec = {
            'spec': {
                'max_flops': '512',
                'policy_name': 'fake_policy_name',
            }
        }

        self.assertFalse(na_utils.is_qos_policy_group_spec_adaptive(qos_spec))

    def test_map_dict_to_lower(self):
        original = {'UPperKey': 'Value'}
        expected = {'upperkey': 'Value'}

        result = na_utils.map_dict_to_lower(original)

        self.assertEqual(expected, result)

    def test_get_qos_policy_group_name(self):
        expected = 'openstack-%s' % fake.VOLUME_ID

        result = na_utils.get_qos_policy_group_name(fake.VOLUME)

        self.assertEqual(expected, result)

    def test_get_qos_policy_group_name_no_id(self):
        delattr(fake.VOLUME, '_obj_id')
        try:
            result = na_utils.get_qos_policy_group_name(fake.VOLUME)
        finally:
            fake.VOLUME._obj_id = fake.VOLUME_ID

        self.assertIsNone(result)

    def test_get_qos_policy_group_name_migrated_volume(self):
        fake.VOLUME._name_id = 'asdf'
        try:
            expected = 'openstack-' + fake.VOLUME.name_id
            result = na_utils.get_qos_policy_group_name(fake.VOLUME)
        finally:
            fake.VOLUME._name_id = None

        self.assertEqual(expected, result)

    def test_get_qos_policy_group_name_from_info(self):
        expected = 'openstack-%s' % fake.VOLUME_ID
        result = na_utils.get_qos_policy_group_name_from_info(
            fake.QOS_POLICY_GROUP_INFO)

        self.assertEqual(expected, result)

    def test_get_qos_policy_group_name_from_info_no_info(self):

        result = na_utils.get_qos_policy_group_name_from_info(None)

        self.assertIsNone(result)

    def test_get_qos_policy_group_name_from_legacy_info(self):
        expected = fake.QOS_POLICY_GROUP_NAME

        result = na_utils.get_qos_policy_group_name_from_info(
            fake.LEGACY_QOS_POLICY_GROUP_INFO)

        self.assertEqual(expected, result)

    def test_get_qos_policy_group_name_from_spec_info(self):
        expected = 'openstack-%s' % fake.VOLUME_ID

        result = na_utils.get_qos_policy_group_name_from_info(
            fake.QOS_POLICY_GROUP_INFO)

        self.assertEqual(expected, result)

    def test_get_qos_policy_group_name_from_none_qos_info(self):
        expected = None

        result = na_utils.get_qos_policy_group_name_from_info(
            fake.QOS_POLICY_GROUP_INFO_NONE)

        self.assertEqual(expected, result)

    def test_get_valid_qos_policy_group_info_exception_path(self):
        mock_get_volume_type = self.mock_object(na_utils,
                                                'get_volume_type_from_volume')
        mock_get_volume_type.side_effect = exception.VolumeTypeNotFound
        expected = fake.QOS_POLICY_GROUP_INFO_NONE

        result = na_utils.get_valid_qos_policy_group_info(fake.VOLUME)

        self.assertEqual(expected, result)

    def test_get_valid_qos_policy_group_info_volume_type_none(self):
        mock_get_volume_type = self.mock_object(na_utils,
                                                'get_volume_type_from_volume')
        mock_get_volume_type.return_value = None
        expected = fake.QOS_POLICY_GROUP_INFO_NONE

        result = na_utils.get_valid_qos_policy_group_info(fake.VOLUME)

        self.assertEqual(expected, result)

    def test_get_valid_qos_policy_group_info_no_info(self):
        mock_get_volume_type = self.mock_object(na_utils,
                                                'get_volume_type_from_volume')
        mock_get_volume_type.return_value = fake.VOLUME_TYPE
        mock_get_legacy_qos_policy = self.mock_object(na_utils,
                                                      'get_legacy_qos_policy')
        mock_get_legacy_qos_policy.return_value = None
        mock_get_valid_qos_spec_from_volume_type = self.mock_object(
            na_utils, 'get_valid_backend_qos_spec_from_volume_type')
        mock_get_valid_qos_spec_from_volume_type.return_value = None
        expected = fake.QOS_POLICY_GROUP_INFO_NONE

        result = na_utils.get_valid_qos_policy_group_info(fake.VOLUME)

        self.assertEqual(expected, result)

    def test_get_valid_legacy_qos_policy_group_info(self):
        mock_get_volume_type = self.mock_object(na_utils,
                                                'get_volume_type_from_volume')
        mock_get_volume_type.return_value = fake.VOLUME_TYPE
        mock_get_legacy_qos_policy = self.mock_object(na_utils,
                                                      'get_legacy_qos_policy')

        mock_get_legacy_qos_policy.return_value = fake.LEGACY_QOS
        mock_get_valid_qos_spec_from_volume_type = self.mock_object(
            na_utils, 'get_valid_backend_qos_spec_from_volume_type')
        mock_get_valid_qos_spec_from_volume_type.return_value = None

        result = na_utils.get_valid_qos_policy_group_info(fake.VOLUME)

        self.assertEqual(fake.LEGACY_QOS_POLICY_GROUP_INFO, result)

    def test_get_valid_spec_qos_policy_group_info(self):
        mock_get_volume_type = self.mock_object(na_utils,
                                                'get_volume_type_from_volume')
        mock_get_volume_type.return_value = fake.VOLUME_TYPE
        mock_get_legacy_qos_policy = self.mock_object(na_utils,
                                                      'get_legacy_qos_policy')
        mock_get_legacy_qos_policy.return_value = None
        mock_get_valid_qos_spec_from_volume_type = self.mock_object(
            na_utils, 'get_valid_backend_qos_spec_from_volume_type')
        mock_get_valid_qos_spec_from_volume_type.return_value =\
            fake.QOS_POLICY_GROUP_SPEC

        result = na_utils.get_valid_qos_policy_group_info(fake.VOLUME)

        self.assertEqual(fake.QOS_POLICY_GROUP_INFO, result)

    def test_get_valid_backend_qos_spec_from_volume_type_no_spec(self):
        mock_get_spec = self.mock_object(
            na_utils, 'get_backend_qos_spec_from_volume_type')
        mock_get_spec.return_value = None
        mock_map_qos_spec = self.mock_object(
            na_utils, 'map_qos_spec')
        mock_map_aqos_spec = self.mock_object(
            na_utils, 'map_aqos_spec')

        result = na_utils.get_valid_backend_qos_spec_from_volume_type(
            fake.VOLUME, fake.VOLUME_TYPE)

        self.assertIsNone(result)
        mock_map_qos_spec.assert_not_called()
        mock_map_aqos_spec.assert_not_called()

    def test_get_valid_backend_qos_spec_from_volume_type(self):
        mock_get_spec = self.mock_object(
            na_utils, 'get_backend_qos_spec_from_volume_type')
        mock_get_spec.return_value = fake.QOS_SPEC
        mock_map_aqos_spec = self.mock_object(
            na_utils, 'map_aqos_spec')

        result = na_utils.get_valid_backend_qos_spec_from_volume_type(
            fake.VOLUME, fake.VOLUME_TYPE)

        self.assertEqual(fake.QOS_POLICY_GROUP_SPEC, result)
        mock_map_aqos_spec.assert_not_called()

    def test_get_valid_backend_qos_spec_from_volume_type_adaptive(self):
        mock_get_spec = self.mock_object(
            na_utils, 'get_backend_qos_spec_from_volume_type')
        mock_get_spec.return_value = fake.ADAPTIVE_QOS_SPEC
        mock_map_qos_spec = self.mock_object(
            na_utils, 'map_qos_spec')

        result = na_utils.get_valid_backend_qos_spec_from_volume_type(
            fake.VOLUME, fake.VOLUME_TYPE)

        self.assertEqual(fake.ADAPTIVE_QOS_POLICY_GROUP_SPEC, result)
        mock_map_qos_spec.assert_not_called()

    def test_get_backend_qos_spec_from_volume_type_no_qos_specs_id(self):
        volume_type = copy.deepcopy(fake.VOLUME_TYPE)
        del(volume_type['qos_specs_id'])
        mock_get_context = self.mock_object(context, 'get_admin_context')

        result = na_utils.get_backend_qos_spec_from_volume_type(volume_type)

        self.assertIsNone(result)
        mock_get_context.assert_not_called()

    def test_get_backend_qos_spec_from_volume_type_no_qos_spec(self):
        volume_type = fake.VOLUME_TYPE
        self.mock_object(context, 'get_admin_context')
        mock_get_specs = self.mock_object(qos_specs, 'get_qos_specs')
        mock_get_specs.return_value = None

        result = na_utils.get_backend_qos_spec_from_volume_type(volume_type)

        self.assertIsNone(result)

    def test_get_backend_qos_spec_from_volume_type_with_frontend_spec(self):
        volume_type = fake.VOLUME_TYPE
        self.mock_object(context, 'get_admin_context')
        mock_get_specs = self.mock_object(qos_specs, 'get_qos_specs')
        mock_get_specs.return_value = fake.OUTER_FRONTEND_QOS_SPEC

        result = na_utils.get_backend_qos_spec_from_volume_type(volume_type)

        self.assertIsNone(result)

    def test_get_backend_qos_spec_from_volume_type_with_backend_spec(self):
        volume_type = fake.VOLUME_TYPE
        self.mock_object(context, 'get_admin_context')
        mock_get_specs = self.mock_object(qos_specs, 'get_qos_specs')
        mock_get_specs.return_value = fake.OUTER_BACKEND_QOS_SPEC

        result = na_utils.get_backend_qos_spec_from_volume_type(volume_type)

        self.assertEqual(fake.QOS_SPEC, result)

    def test_get_backend_qos_spec_from_volume_type_with_both_spec(self):
        volume_type = fake.VOLUME_TYPE
        self.mock_object(context, 'get_admin_context')
        mock_get_specs = self.mock_object(qos_specs, 'get_qos_specs')
        mock_get_specs.return_value = fake.OUTER_BOTH_QOS_SPEC

        result = na_utils.get_backend_qos_spec_from_volume_type(volume_type)

        self.assertEqual(fake.QOS_SPEC, result)

    def test_check_for_invalid_qos_spec_combination_legacy(self):
        na_utils.check_for_invalid_qos_spec_combination(
            fake.LEGACY_QOS_POLICY_GROUP_INFO,
            fake.VOLUME_TYPE)

    def test_check_for_invalid_qos_spec_combination_spec(self):
        na_utils.check_for_invalid_qos_spec_combination(
            fake.QOS_POLICY_GROUP_INFO,
            fake.VOLUME_TYPE)

    def test_check_for_invalid_qos_spec_combination_legacy_and_spec(self):
        self.assertRaises(exception.Invalid,
                          na_utils.check_for_invalid_qos_spec_combination,
                          fake.INVALID_QOS_POLICY_GROUP_INFO_LEGACY_AND_SPEC,
                          fake.VOLUME_TYPE)

    def test_get_legacy_qos_policy(self):
        extra_specs = fake.LEGACY_EXTRA_SPECS
        expected = {'policy_name': fake.QOS_POLICY_GROUP_NAME}

        result = na_utils.get_legacy_qos_policy(extra_specs)

        self.assertEqual(expected, result)

    def test_get_legacy_qos_policy_no_policy_name(self):
        extra_specs = fake.EXTRA_SPECS

        result = na_utils.get_legacy_qos_policy(extra_specs)

        self.assertIsNone(result)

    @ddt.data(("192.168.99.24:/fake/export/path", "192.168.99.24",
               "/fake/export/path"),
              ("127.0.0.1:/", "127.0.0.1", "/"),
              ("[f180::30d9]:/path_to-export/3.1/this folder", "f180::30d9",
               "/path_to-export/3.1/this folder"),
              ("[::]:/", "::", "/"),
              ("[2001:db8::1]:/fake_export", "2001:db8::1", "/fake_export"))
    @ddt.unpack
    def test_get_export_host_junction_path(self, share, host, junction_path):
        result_host, result_path = na_utils.get_export_host_junction_path(
            share)

        self.assertEqual(host, result_host)
        self.assertEqual(junction_path, result_path)

    @ddt.data("192.14.21.0/wrong_export", "192.14.21.0:8080:/wrong_export"
              "2001:db8::1:/wrong_export",
              "[2001:db8::1:/wrong_export", "2001:db8::1]:/wrong_export")
    def test_get_export_host_junction_path_with_invalid_exports(self, share):
        self.assertRaises(na_utils.NetAppDriverException,
                          na_utils.get_export_host_junction_path,
                          share)

    @ddt.data(True, False)
    def test_qos_min_feature_name(self, is_nfs):
        name = 'node'
        feature_name = na_utils.qos_min_feature_name(is_nfs, name)

        if is_nfs:
            self.assertEqual('QOS_MIN_NFS_' + name, feature_name)
        else:
            self.assertEqual('QOS_MIN_BLOCK_' + name, feature_name)


class OpenStackInfoTestCase(test.TestCase):

    UNKNOWN_VERSION = 'unknown version'
    UNKNOWN_RELEASE = 'unknown release'
    UNKNOWN_VENDOR = 'unknown vendor'
    UNKNOWN_PLATFORM = 'unknown platform'
    VERSION_STRING_RET_VAL = 'fake_version_1'
    RELEASE_STRING_RET_VAL = 'fake_release_1'
    PLATFORM_RET_VAL = 'fake_platform_1'
    VERSION_INFO_VERSION = 'fake_version_2'
    VERSION_INFO_RELEASE = 'fake_release_2'
    RPM_INFO_VERSION = 'fake_version_3'
    RPM_INFO_RELEASE = 'fake_release_3'
    RPM_INFO_VENDOR = 'fake vendor 3'
    PUTILS_RPM_RET_VAL = ('fake_version_3  fake_release_3 fake vendor 3', '')
    NO_PKG_FOUND = ('', 'whatever')
    PUTILS_DPKG_RET_VAL = ('epoch:upstream_version-debian_revision', '')
    DEB_RLS = 'upstream_version-debian_revision'
    DEB_VENDOR = 'debian_revision'

    def test_openstack_info_init(self):
        info = na_utils.OpenStackInfo()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)

    @mock.patch.object(version.version_info, 'version_string',
                       mock.Mock(return_value=VERSION_STRING_RET_VAL))
    def test_update_version_from_version_string(self):
        info = na_utils.OpenStackInfo()
        info._update_version_from_version_string()

        self.assertEqual(self.VERSION_STRING_RET_VAL, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)

    @mock.patch.object(version.version_info, 'version_string',
                       mock.Mock(side_effect=Exception))
    def test_xcption_in_update_version_from_version_string(self):
        info = na_utils.OpenStackInfo()
        info._update_version_from_version_string()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)

    @mock.patch.object(version.version_info, 'release_string',
                       mock.Mock(return_value=RELEASE_STRING_RET_VAL))
    def test_update_release_from_release_string(self):
        info = na_utils.OpenStackInfo()
        info._update_release_from_release_string()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.RELEASE_STRING_RET_VAL, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)

    @mock.patch.object(version.version_info, 'release_string',
                       mock.Mock(side_effect=Exception))
    def test_xcption_in_update_release_from_release_string(self):
        info = na_utils.OpenStackInfo()
        info._update_release_from_release_string()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)

    @mock.patch.object(platform, 'platform',
                       mock.Mock(return_value=PLATFORM_RET_VAL))
    def test_update_platform(self):
        info = na_utils.OpenStackInfo()
        info._update_platform()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.PLATFORM_RET_VAL, info._platform)

    @mock.patch.object(platform, 'platform',
                       mock.Mock(side_effect=Exception))
    def test_xcption_in_update_platform(self):
        info = na_utils.OpenStackInfo()
        info._update_platform()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)

    @mock.patch.object(na_utils.OpenStackInfo, '_get_version_info_version',
                       mock.Mock(return_value=VERSION_INFO_VERSION))
    @mock.patch.object(na_utils.OpenStackInfo, '_get_version_info_release',
                       mock.Mock(return_value=VERSION_INFO_RELEASE))
    def test_update_info_from_version_info(self):
        info = na_utils.OpenStackInfo()
        info._update_info_from_version_info()

        self.assertEqual(self.VERSION_INFO_VERSION, info._version)
        self.assertEqual(self.VERSION_INFO_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)

    @mock.patch.object(na_utils.OpenStackInfo, '_get_version_info_version',
                       mock.Mock(return_value=''))
    @mock.patch.object(na_utils.OpenStackInfo, '_get_version_info_release',
                       mock.Mock(return_value=None))
    def test_no_info_from_version_info(self):
        info = na_utils.OpenStackInfo()
        info._update_info_from_version_info()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)

    @mock.patch.object(na_utils.OpenStackInfo, '_get_version_info_version',
                       mock.Mock(return_value=VERSION_INFO_VERSION))
    @mock.patch.object(na_utils.OpenStackInfo, '_get_version_info_release',
                       mock.Mock(side_effect=Exception))
    def test_xcption_in_info_from_version_info(self):
        info = na_utils.OpenStackInfo()
        info._update_info_from_version_info()

        self.assertEqual(self.VERSION_INFO_VERSION, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)

    @mock.patch.object(putils, 'execute',
                       mock.Mock(return_value=PUTILS_RPM_RET_VAL))
    def test_update_info_from_rpm(self):
        info = na_utils.OpenStackInfo()
        found_package = info._update_info_from_rpm()

        self.assertEqual(self.RPM_INFO_VERSION, info._version)
        self.assertEqual(self.RPM_INFO_RELEASE, info._release)
        self.assertEqual(self.RPM_INFO_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)
        self.assertTrue(found_package)

    @mock.patch.object(putils, 'execute',
                       mock.Mock(return_value=NO_PKG_FOUND))
    def test_update_info_from_rpm_no_pkg_found(self):
        info = na_utils.OpenStackInfo()
        found_package = info._update_info_from_rpm()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)
        self.assertFalse(found_package)

    @mock.patch.object(putils, 'execute',
                       mock.Mock(side_effect=Exception))
    def test_xcption_in_update_info_from_rpm(self):
        info = na_utils.OpenStackInfo()
        found_package = info._update_info_from_rpm()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)
        self.assertFalse(found_package)

    @mock.patch.object(putils, 'execute',
                       mock.Mock(return_value=PUTILS_DPKG_RET_VAL))
    def test_update_info_from_dpkg(self):
        info = na_utils.OpenStackInfo()
        found_package = info._update_info_from_dpkg()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.DEB_RLS, info._release)
        self.assertEqual(self.DEB_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)
        self.assertTrue(found_package)

    @mock.patch.object(putils, 'execute',
                       mock.Mock(return_value=NO_PKG_FOUND))
    def test_update_info_from_dpkg_no_pkg_found(self):
        info = na_utils.OpenStackInfo()
        found_package = info._update_info_from_dpkg()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)
        self.assertFalse(found_package)

    @mock.patch.object(putils, 'execute',
                       mock.Mock(side_effect=Exception))
    def test_xcption_in_update_info_from_dpkg(self):
        info = na_utils.OpenStackInfo()
        found_package = info._update_info_from_dpkg()

        self.assertEqual(self.UNKNOWN_VERSION, info._version)
        self.assertEqual(self.UNKNOWN_RELEASE, info._release)
        self.assertEqual(self.UNKNOWN_VENDOR, info._vendor)
        self.assertEqual(self.UNKNOWN_PLATFORM, info._platform)
        self.assertFalse(found_package)

    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_version_from_version_string', mock.Mock())
    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_release_from_release_string', mock.Mock())
    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_platform', mock.Mock())
    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_info_from_version_info', mock.Mock())
    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_info_from_rpm', mock.Mock(return_value=True))
    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_info_from_dpkg')
    def test_update_openstack_info_rpm_pkg_found(self, mock_updt_from_dpkg):
        info = na_utils.OpenStackInfo()
        info._update_openstack_info()

        self.assertFalse(mock_updt_from_dpkg.called)

    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_version_from_version_string', mock.Mock())
    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_release_from_release_string', mock.Mock())
    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_platform', mock.Mock())
    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_info_from_version_info', mock.Mock())
    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_info_from_rpm', mock.Mock(return_value=False))
    @mock.patch.object(na_utils.OpenStackInfo,
                       '_update_info_from_dpkg')
    def test_update_openstack_info_rpm_pkg_not_found(self,
                                                     mock_updt_from_dpkg):
        info = na_utils.OpenStackInfo()
        info._update_openstack_info()

        self.assertTrue(mock_updt_from_dpkg.called)


@ddt.ddt
class FeaturesTestCase(test.TestCase):

    def setUp(self):
        super(FeaturesTestCase, self).setUp()
        self.features = na_utils.Features()

    def test_init(self):
        self.assertSetEqual(set(), self.features.defined_features)

    def test_add_feature_default(self):
        self.features.add_feature('FEATURE_1')

        self.assertTrue(self.features.FEATURE_1.supported)
        self.assertIn('FEATURE_1', self.features.defined_features)

    @ddt.data(True, False)
    def test_add_feature(self, value):
        self.features.add_feature('FEATURE_2', value)

        self.assertEqual(value, bool(self.features.FEATURE_2))
        self.assertEqual(value, self.features.FEATURE_2.supported)
        self.assertIsNone(self.features.FEATURE_2.minimum_version)
        self.assertIn('FEATURE_2', self.features.defined_features)

    @ddt.data((True, '1'), (False, 2), (False, None), (True, None))
    @ddt.unpack
    def test_add_feature_min_version(self, enabled, min_version):
        self.features.add_feature('FEATURE_2', enabled,
                                  min_version=min_version)

        self.assertEqual(enabled, bool(self.features.FEATURE_2))
        self.assertEqual(enabled, self.features.FEATURE_2.supported)
        self.assertEqual(min_version, self.features.FEATURE_2.minimum_version)
        self.assertIn('FEATURE_2', self.features.defined_features)

    @ddt.data('True', 'False', 0, 1, 1.0, None, [], {}, (True,))
    def test_add_feature_type_error(self, value):
        self.assertRaises(TypeError,
                          self.features.add_feature,
                          'FEATURE_3',
                          value)
        self.assertNotIn('FEATURE_3', self.features.defined_features)

    def test_get_attr_missing(self):
        self.assertRaises(AttributeError, getattr, self.features, 'FEATURE_4')


@ddt.ddt
class BitSetTestCase(test.TestCase):

    def test_default(self):
        self.assertEqual(na_utils.BitSet(0), na_utils.BitSet())

    def test_set(self):
        bitset = na_utils.BitSet(0)
        bitset.set(16)

        self.assertEqual(na_utils.BitSet(1 << 16), bitset)

    def test_unset(self):
        bitset = na_utils.BitSet(1 << 16)
        bitset.unset(16)

        self.assertEqual(na_utils.BitSet(0), bitset)

    def test_is_set(self):
        bitset = na_utils.BitSet(1 << 16)

        self.assertTrue(bool(bitset.is_set(16)))

    def test_not_equal(self):
        set1 = na_utils.BitSet(1 << 15)
        set2 = na_utils.BitSet(1 << 16)

        self.assertNotEqual(set1, set2)

    def test_repr(self):
        raw_val = 1 << 16
        actual = repr(na_utils.BitSet(raw_val))
        expected = str(raw_val)

        self.assertEqual(actual, expected)

    def test_str(self):
        raw_val = 1 << 16
        actual = str(na_utils.BitSet(raw_val))
        expected = bin(raw_val)

        self.assertEqual(actual, expected)

    def test_int(self):
        val = 1 << 16
        actual = int(int(na_utils.BitSet(val)))

        self.assertEqual(val, actual)

    def test_and(self):
        actual = na_utils.BitSet(1 << 16 | 1 << 15)
        actual &= 1 << 16

        self.assertEqual(na_utils.BitSet(1 << 16), actual)

    def test_or(self):
        actual = na_utils.BitSet()
        actual |= 1 << 16

        self.assertEqual(na_utils.BitSet(1 << 16), actual)

    def test_invert(self):
        actual = na_utils.BitSet(1 << 16)
        actual = ~actual

        self.assertEqual(~(1 << 16), actual)

    def test_xor(self):
        actual = na_utils.BitSet(1 << 16)
        actual ^= 1 << 16

        self.assertEqual(na_utils.BitSet(), actual)

    def test_lshift(self):
        actual = na_utils.BitSet(1)
        actual <<= 16

        self.assertEqual(na_utils.BitSet(1 << 16), actual)

    def test_rshift(self):
        actual = na_utils.BitSet(1 << 16)
        actual >>= 16

        self.assertEqual(na_utils.BitSet(1), actual)
