# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
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
Unit tests for the NetApp NFS storage driver
"""

import mock
from oslo_utils import units

from cinder.brick.remotefs import remotefs as remotefs_brick
from cinder import exception
from cinder import test
from cinder.tests.volume.drivers.netapp.dataontap import fakes as fake
from cinder import utils
from cinder.volume.drivers.netapp.dataontap import nfs_base
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume.drivers import nfs


class NetAppNfsDriverTestCase(test.TestCase):
    def setUp(self):
        super(NetAppNfsDriverTestCase, self).setUp()
        configuration = mock.Mock()
        configuration.nfs_mount_point_base = '/mnt/test'
        configuration.nfs_used_ratio = 0.89
        configuration.nfs_oversub_ratio = 3.0

        kwargs = {'configuration': configuration}

        with mock.patch.object(utils, 'get_root_helper',
                               return_value=mock.Mock()):
            with mock.patch.object(remotefs_brick, 'RemoteFsClient',
                                   return_value=mock.Mock()):
                self.driver = nfs_base.NetAppNfsDriver(**kwargs)
                self.driver.db = mock.Mock()

    @mock.patch.object(nfs.NfsDriver, 'do_setup')
    @mock.patch.object(na_utils, 'check_flags')
    def test_do_setup(self, mock_check_flags, mock_super_do_setup):
        self.driver.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        self.assertTrue(mock_super_do_setup.called)

    def test_get_share_capacity_info(self):
        mock_get_capacity = self.mock_object(self.driver, '_get_capacity_info')
        mock_get_capacity.return_value = fake.CAPACITY_VALUES
        expected_total_capacity_gb = (na_utils.round_down(
            (fake.TOTAL_BYTES *
             self.driver.configuration.nfs_oversub_ratio) /
            units.Gi, '0.01'))
        expected_free_capacity_gb = (na_utils.round_down(
            (fake.AVAILABLE_BYTES *
             self.driver.configuration.nfs_oversub_ratio) /
            units.Gi, '0.01'))
        expected_reserved_percentage = round(
            100 * (1 - self.driver.configuration.nfs_used_ratio))

        result = self.driver._get_share_capacity_info(fake.NFS_SHARE)

        self.assertEqual(expected_total_capacity_gb,
                         result['total_capacity_gb'])
        self.assertEqual(expected_free_capacity_gb,
                         result['free_capacity_gb'])
        self.assertEqual(expected_reserved_percentage,
                         result['reserved_percentage'])

    def test_get_capacity_info_ipv4_share(self):
        expected = fake.CAPACITY_VALUES
        self.driver.zapi_client = mock.Mock()
        get_capacity = self.driver.zapi_client.get_flexvol_capacity
        get_capacity.return_value = fake.CAPACITY_VALUES

        result = self.driver._get_capacity_info(fake.NFS_SHARE_IPV4)

        self.assertEqual(expected, result)
        get_capacity.assert_has_calls([
            mock.call(fake.EXPORT_PATH)])

    def test_get_capacity_info_ipv6_share(self):
        expected = fake.CAPACITY_VALUES
        self.driver.zapi_client = mock.Mock()
        get_capacity = self.driver.zapi_client.get_flexvol_capacity
        get_capacity.return_value = fake.CAPACITY_VALUES

        result = self.driver._get_capacity_info(fake.NFS_SHARE_IPV6)

        self.assertEqual(expected, result)
        get_capacity.assert_has_calls([
            mock.call(fake.EXPORT_PATH)])

    def test_get_export_ip_path_volume_id_provided(self):
        mock_get_host_ip = self.mock_object(self.driver, '_get_host_ip')
        mock_get_host_ip.return_value = fake.IPV4_ADDRESS

        mock_get_export_path = self.mock_object(
            self.driver, '_get_export_path')
        mock_get_export_path.return_value = fake.EXPORT_PATH

        expected = (fake.IPV4_ADDRESS, fake.EXPORT_PATH)

        result = self.driver._get_export_ip_path(fake.VOLUME)

        self.assertEqual(expected, result)

    def test_get_export_ip_path_share_provided(self):
        expected = (fake.HOSTNAME, fake.EXPORT_PATH)

        result = self.driver._get_export_ip_path(share=fake.NFS_SHARE)

        self.assertEqual(expected, result)

    def test_get_export_ip_path_volume_id_and_share_provided(self):
        mock_get_host_ip = self.mock_object(self.driver, '_get_host_ip')
        mock_get_host_ip.return_value = fake.IPV4_ADDRESS

        mock_get_export_path = self.mock_object(
            self.driver, '_get_export_path')
        mock_get_export_path.return_value = fake.EXPORT_PATH

        expected = (fake.IPV4_ADDRESS, fake.EXPORT_PATH)

        result = self.driver._get_export_ip_path(
            fake.VOLUME, fake.NFS_SHARE)

        self.assertEqual(expected, result)

    def test_get_export_ip_path_no_args(self):
        self.assertRaises(exception.InvalidInput,
                          self.driver._get_export_ip_path)

    def test_get_host_ip(self):
        mock_get_provider_location = self.mock_object(
            self.driver, '_get_provider_location')
        mock_get_provider_location.return_value = fake.NFS_SHARE_IPV4
        expected = fake.IPV4_ADDRESS

        result = self.driver._get_host_ip(fake.VOLUME)

        self.assertEqual(expected, result)

    def test_get_export_path(self):
        mock_get_provider_location = self.mock_object(
            self.driver, '_get_provider_location')
        mock_get_provider_location.return_value = fake.NFS_SHARE
        expected = fake.EXPORT_PATH

        result = self.driver._get_export_path(fake.VOLUME)

        self.assertEqual(expected, result)
