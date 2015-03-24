# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2014 Tom Barron.  All rights reserved.
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

import platform

import mock
from oslo_concurrency import processutils as putils

from cinder import exception
from cinder import test
import cinder.tests.volume.drivers.netapp.fakes as fake
from cinder import version
import cinder.volume.drivers.netapp.utils as na_utils


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
