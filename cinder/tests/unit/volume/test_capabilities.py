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

from unittest import mock

from oslo_serialization import jsonutils

from cinder import exception
from cinder.tests import fake_driver
from cinder.tests.unit import volume as base
from cinder.volume import driver
from cinder.volume import manager as vol_manager
# import cinder.volume.targets.tgt

"""Tests for volume capabilities test cases."""


class VolumeCapabilitiesTestCase(base.BaseVolumeTestCase):
    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver, 'get_volume_stats')
    @mock.patch.object(driver.BaseVD, '_init_vendor_properties')
    def test_get_capabilities(self, mock_init_vendor, mock_get_volume_stats):
        stats = {
            'volume_backend_name': 'lvm',
            'vendor_name': 'Open Source',
            'storage_protocol': 'iSCSI',
            'vendor_prefix': 'abcd'
        }
        expected = stats.copy()
        expected['properties'] = {
            'compression': {
                'title': 'Compression',
                'description': 'Enables compression.',
                'type': 'boolean'},
            'qos': {
                'title': 'QoS',
                'description': 'Enables QoS.',
                'type': 'boolean'},
            'replication_enabled': {
                'title': 'Replication',
                'description': 'Enables replication.',
                'type': 'boolean'},
            'thin_provisioning': {
                'title': 'Thin Provisioning',
                'description': 'Sets thin provisioning.',
                'type': 'boolean'},
        }

        # Test to get updated capabilities
        discover = True
        mock_get_volume_stats.return_value = stats
        mock_init_vendor.return_value = ({}, None)
        capabilities = self.volume.get_capabilities(self.context,
                                                    discover)
        self.assertEqual(expected, capabilities)
        mock_get_volume_stats.assert_called_once_with(True)

        # Test to get existing original capabilities
        mock_get_volume_stats.reset_mock()
        discover = False
        capabilities = self.volume.get_capabilities(self.context,
                                                    discover)
        self.assertEqual(expected, capabilities)
        self.assertFalse(mock_get_volume_stats.called)

        # Normal test case to get vendor unique capabilities
        def init_vendor_properties(self):
            properties = {}
            self._set_property(
                properties,
                "abcd:minIOPS",
                "Minimum IOPS QoS",
                "Sets minimum IOPS if QoS is enabled.",
                "integer",
                minimum=10,
                default=100)
            return properties, 'abcd'

        expected['properties'].update(
            {'abcd:minIOPS': {
                'title': 'Minimum IOPS QoS',
                'description': 'Sets minimum IOPS if QoS is enabled.',
                'type': 'integer',
                'minimum': 10,
                'default': 100}})

        mock_get_volume_stats.reset_mock()
        mock_init_vendor.reset_mock()
        discover = True
        mock_init_vendor.return_value = (
            init_vendor_properties(self.volume.driver))
        capabilities = self.volume.get_capabilities(self.context,
                                                    discover)
        self.assertEqual(expected, capabilities)
        self.assertTrue(mock_get_volume_stats.called)

    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver, 'get_volume_stats')
    @mock.patch.object(driver.BaseVD, '_init_vendor_properties')
    @mock.patch.object(driver.BaseVD, '_init_standard_capabilities')
    def test_get_capabilities_prefix_error(self, mock_init_standard,
                                           mock_init_vendor,
                                           mock_get_volume_stats):

        # Error test case: property does not match vendor prefix
        def init_vendor_properties(self):
            properties = {}
            self._set_property(
                properties,
                "aaa:minIOPS",
                "Minimum IOPS QoS",
                "Sets minimum IOPS if QoS is enabled.",
                "integer")
            self._set_property(
                properties,
                "abcd:compression_type",
                "Compression type",
                "Specifies compression type.",
                "string")

            return properties, 'abcd'

        expected = {
            'abcd:compression_type': {
                'title': 'Compression type',
                'description': 'Specifies compression type.',
                'type': 'string'}}

        discover = True
        mock_get_volume_stats.return_value = {}
        mock_init_standard.return_value = {}
        mock_init_vendor.return_value = (
            init_vendor_properties(self.volume.driver))
        capabilities = self.volume.get_capabilities(self.context,
                                                    discover)
        self.assertEqual(expected, capabilities['properties'])

    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver, 'get_volume_stats')
    @mock.patch.object(driver.BaseVD, '_init_vendor_properties')
    @mock.patch.object(driver.BaseVD, '_init_standard_capabilities')
    def test_get_capabilities_fail_override(self, mock_init_standard,
                                            mock_init_vendor,
                                            mock_get_volume_stats):

        # Error test case: property cannot override any standard capabilities
        def init_vendor_properties(self):
            properties = {}
            self._set_property(
                properties,
                "qos",
                "Minimum IOPS QoS",
                "Sets minimum IOPS if QoS is enabled.",
                "integer")
            self._set_property(
                properties,
                "ab::cd:compression_type",
                "Compression type",
                "Specifies compression type.",
                "string")

            return properties, 'ab::cd'

        expected = {
            'ab__cd:compression_type': {
                'title': 'Compression type',
                'description': 'Specifies compression type.',
                'type': 'string'}}

        discover = True
        mock_get_volume_stats.return_value = {}
        mock_init_standard.return_value = {}
        mock_init_vendor.return_value = (
            init_vendor_properties(self.volume.driver))
        capabilities = self.volume.get_capabilities(self.context,
                                                    discover)
        self.assertEqual(expected, capabilities['properties'])

    def test_extra_capabilities(self):
        # Test valid extra_capabilities.
        fake_capabilities = {'key1': 1, 'key2': 2}

        with mock.patch.object(jsonutils, 'loads') as mock_loads:
            mock_loads.return_value = fake_capabilities
            manager = vol_manager.VolumeManager()
            manager.stats = {'pools': {}}
            manager.driver.set_initialized()
            manager.publish_service_capabilities(self.context)
            self.assertTrue(mock_loads.called)
            volume_stats = manager.last_capabilities
            self.assertEqual(fake_capabilities['key1'],
                             volume_stats['key1'])
            self.assertEqual(fake_capabilities['key2'],
                             volume_stats['key2'])

    def test_extra_capabilities_fail(self):
        with mock.patch.object(jsonutils, 'loads') as mock_loads:
            mock_loads.side_effect = exception.CinderException('test')
            self.assertRaises(exception.CinderException,
                              vol_manager.VolumeManager)
