# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
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

import mock
from oslo_concurrency import processutils as putils

from cinder import context
from cinder import exception
from cinder import test
import cinder.tests.unit.volume.drivers.netapp.fakes as fake
from cinder import version
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import qos_specs
from cinder.volume import volume_types


class NetAppDriverUtilsTestCase(test.TestCase):

    @mock.patch.object(na_utils, 'LOG', mock.Mock())
    def test_validate_instantiation_proxy(self):
        kwargs = {'netapp_mode': 'proxy'}
        na_utils.validate_instantiation(**kwargs)
        self.assertEqual(na_utils.LOG.warning.call_count, 0)

    @mock.patch.object(na_utils, 'LOG', mock.Mock())
    def test_validate_instantiation_no_proxy(self):
        kwargs = {'netapp_mode': 'asdf'}
        na_utils.validate_instantiation(**kwargs)
        self.assertEqual(na_utils.LOG.warning.call_count, 1)

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
        self.assertEqual(fake_object.fake_attr, 'fake_value')

        # test value is changed if it should be and retval is True
        self.assertTrue(na_utils.set_safe_attr(fake_object, 'fake_attr',
                                               'new_fake_value'))
        self.assertEqual(fake_object.fake_attr, 'new_fake_value')

    def test_round_down(self):
        self.assertAlmostEqual(na_utils.round_down(5.567, '0.00'), 5.56)
        self.assertAlmostEqual(na_utils.round_down(5.567, '0.0'), 5.5)
        self.assertAlmostEqual(na_utils.round_down(5.567, '0'), 5)
        self.assertAlmostEqual(na_utils.round_down(0, '0.00'), 0)
        self.assertAlmostEqual(na_utils.round_down(-5.567, '0.00'), -5.56)
        self.assertAlmostEqual(na_utils.round_down(-5.567, '0.0'), -5.5)
        self.assertAlmostEqual(na_utils.round_down(-5.567, '0'), -5)

    def test_iscsi_connection_properties(self):

        actual_properties = na_utils.get_iscsi_connection_properties(
            fake.ISCSI_FAKE_LUN_ID, fake.ISCSI_FAKE_VOLUME,
            fake.ISCSI_FAKE_IQN, fake.ISCSI_FAKE_ADDRESS,
            fake.ISCSI_FAKE_PORT)

        actual_properties_mapped = actual_properties['data']

        self.assertDictEqual(actual_properties_mapped,
                             fake.FC_ISCSI_TARGET_INFO_DICT)

    def test_iscsi_connection_lun_id_type_str(self):
        FAKE_LUN_ID = '1'

        actual_properties = na_utils.get_iscsi_connection_properties(
            FAKE_LUN_ID, fake.ISCSI_FAKE_VOLUME, fake.ISCSI_FAKE_IQN,
            fake.ISCSI_FAKE_ADDRESS, fake.ISCSI_FAKE_PORT)

        actual_properties_mapped = actual_properties['data']

        self.assertIs(type(actual_properties_mapped['target_lun']), int)

    def test_iscsi_connection_lun_id_type_dict(self):
        FAKE_LUN_ID = {'id': 'fake_id'}

        self.assertRaises(TypeError, na_utils.get_iscsi_connection_properties,
                          FAKE_LUN_ID, fake.ISCSI_FAKE_VOLUME,
                          fake.ISCSI_FAKE_IQN, fake.ISCSI_FAKE_ADDRESS,
                          fake.ISCSI_FAKE_PORT)

    def test_get_volume_extra_specs(self):
        fake_extra_specs = {'fake_key': 'fake_value'}
        fake_volume_type = {'extra_specs': fake_extra_specs}
        fake_volume = {'volume_type_id': 'fake_volume_type_id'}
        self.mock_object(context, 'get_admin_context')
        self.mock_object(volume_types, 'get_volume_type', mock.Mock(
            return_value=fake_volume_type))
        self.mock_object(na_utils, 'log_extra_spec_warnings')

        result = na_utils.get_volume_extra_specs(fake_volume)

        self.assertEqual(fake_extra_specs, result)

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
        self.mock_object(volume_types, 'get_volume_type', mock.Mock(
            return_value=None))
        self.mock_object(na_utils, 'log_extra_spec_warnings')

        result = na_utils.get_volume_extra_specs(fake_volume)

        self.assertEqual({}, result)

    def test_log_extra_spec_warnings_obsolete_specs(self):

        mock_log = self.mock_object(na_utils.LOG, 'warning')

        na_utils.log_extra_spec_warnings({'netapp:raid_type': 'raid4'})

        self.assertEqual(1, mock_log.call_count)

    def test_log_extra_spec_warnings_deprecated_specs(self):

        mock_log = self.mock_object(na_utils.LOG, 'warning')

        na_utils.log_extra_spec_warnings({'netapp_thick_provisioned': 'true'})

        self.assertEqual(1, mock_log.call_count)

    def test_validate_qos_spec_none(self):
        qos_spec = None

        # Just return without raising an exception.
        na_utils.validate_qos_spec(qos_spec)

    def test_validate_qos_spec_keys_weirdly_cased(self):
        qos_spec = {'mAxIopS': 33000}

        # Just return without raising an exception.
        na_utils.validate_qos_spec(qos_spec)

    def test_validate_qos_spec_bad_key(self):
        qos_spec = {'maxFlops': 33000}

        self.assertRaises(exception.Invalid,
                          na_utils.validate_qos_spec,
                          qos_spec)

    def test_validate_qos_spec_bad_key_combination(self):
        qos_spec = {'maxIOPS': 33000, 'maxBPS': 10000000}

        self.assertRaises(exception.Invalid,
                          na_utils.validate_qos_spec,
                          qos_spec)

    def test_map_qos_spec_none(self):
        qos_spec = None

        result = na_utils.map_qos_spec(qos_spec, fake.VOLUME)

        self.assertEqual(None, result)

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

    def test_map_qos_spec_no_key_present(self):
        qos_spec = {}
        mock_get_name = self.mock_object(na_utils, 'get_qos_policy_group_name')
        mock_get_name.return_value = 'fake_qos_policy'
        expected = {
            'policy_name': 'fake_qos_policy',
            'max_throughput': None,
        }

        result = na_utils.map_qos_spec(qos_spec, fake.VOLUME)

        self.assertEqual(expected, result)

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
        volume = copy.deepcopy(fake.VOLUME)
        del(volume['id'])

        result = na_utils.get_qos_policy_group_name(volume)

        self.assertEqual(None, result)

    def test_get_qos_policy_group_name_from_info(self):
        expected = 'openstack-%s' % fake.VOLUME_ID
        result = na_utils.get_qos_policy_group_name_from_info(
            fake.QOS_POLICY_GROUP_INFO)

        self.assertEqual(expected, result)

    def test_get_qos_policy_group_name_from_info_no_info(self):

        result = na_utils.get_qos_policy_group_name_from_info(None)

        self.assertEqual(None, result)

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
        self.mock_object(na_utils, 'check_for_invalid_qos_spec_combination')
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
        self.mock_object(na_utils, 'check_for_invalid_qos_spec_combination')

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
        self.mock_object(na_utils, 'check_for_invalid_qos_spec_combination')

        result = na_utils.get_valid_qos_policy_group_info(fake.VOLUME)

        self.assertEqual(fake.QOS_POLICY_GROUP_INFO, result)

    def test_get_valid_backend_qos_spec_from_volume_type_no_spec(self):
        mock_get_spec = self.mock_object(
            na_utils, 'get_backend_qos_spec_from_volume_type')
        mock_get_spec.return_value = None
        mock_validate = self.mock_object(na_utils, 'validate_qos_spec')

        result = na_utils.get_valid_backend_qos_spec_from_volume_type(
            fake.VOLUME, fake.VOLUME_TYPE)

        self.assertEqual(None, result)
        self.assertEqual(0, mock_validate.call_count)

    def test_get_valid_backend_qos_spec_from_volume_type(self):
        mock_get_spec = self.mock_object(
            na_utils, 'get_backend_qos_spec_from_volume_type')
        mock_get_spec.return_value = fake.QOS_SPEC
        mock_validate = self.mock_object(na_utils, 'validate_qos_spec')

        result = na_utils.get_valid_backend_qos_spec_from_volume_type(
            fake.VOLUME, fake.VOLUME_TYPE)

        self.assertEqual(fake.QOS_POLICY_GROUP_SPEC, result)
        self.assertEqual(1, mock_validate.call_count)

    def test_get_backend_qos_spec_from_volume_type_no_qos_specs_id(self):
        volume_type = copy.deepcopy(fake.VOLUME_TYPE)
        del(volume_type['qos_specs_id'])
        mock_get_context = self.mock_object(context, 'get_admin_context')

        result = na_utils.get_backend_qos_spec_from_volume_type(volume_type)

        self.assertEqual(None, result)
        self.assertEqual(0, mock_get_context.call_count)

    def test_get_backend_qos_spec_from_volume_type_no_qos_spec(self):
        volume_type = fake.VOLUME_TYPE
        self.mock_object(context, 'get_admin_context')
        mock_get_specs = self.mock_object(qos_specs, 'get_qos_specs')
        mock_get_specs.return_value = None

        result = na_utils.get_backend_qos_spec_from_volume_type(volume_type)

        self.assertEqual(None, result)

    def test_get_backend_qos_spec_from_volume_type_with_frontend_spec(self):
        volume_type = fake.VOLUME_TYPE
        self.mock_object(context, 'get_admin_context')
        mock_get_specs = self.mock_object(qos_specs, 'get_qos_specs')
        mock_get_specs.return_value = fake.OUTER_FRONTEND_QOS_SPEC

        result = na_utils.get_backend_qos_spec_from_volume_type(volume_type)

        self.assertEqual(None, result)

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

    def test_check_for_invalid_qos_spec_combination(self):

        self.assertRaises(exception.Invalid,
                          na_utils.check_for_invalid_qos_spec_combination,
                          fake.INVALID_QOS_POLICY_GROUP_INFO,
                          fake.VOLUME_TYPE)

    def test_get_legacy_qos_policy(self):
        extra_specs = fake.LEGACY_EXTRA_SPECS
        expected = {'policy_name': fake.QOS_POLICY_GROUP_NAME}

        result = na_utils.get_legacy_qos_policy(extra_specs)

        self.assertEqual(expected, result)

    def test_get_legacy_qos_policy_no_policy_name(self):
        extra_specs = fake.EXTRA_SPECS

        result = na_utils.get_legacy_qos_policy(extra_specs)

        self.assertEqual(None, result)


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

    def setUp(self):
        super(OpenStackInfoTestCase, self).setUp()

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
