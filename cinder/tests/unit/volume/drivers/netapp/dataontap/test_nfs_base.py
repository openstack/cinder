# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
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
Unit tests for the NetApp NFS storage driver
"""

import os

import copy
import ddt
import mock
from os_brick.remotefs import remotefs as remotefs_brick
from oslo_utils import units

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as fake
from cinder import utils
from cinder.volume.drivers.netapp.dataontap import nfs_base
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume.drivers import nfs


@ddt.ddt
class NetAppNfsDriverTestCase(test.TestCase):
    def setUp(self):
        super(NetAppNfsDriverTestCase, self).setUp()
        configuration = mock.Mock()
        configuration.reserved_percentage = 0
        configuration.nfs_mount_point_base = '/mnt/test'
        configuration.nfs_used_ratio = 1.0
        configuration.nfs_oversub_ratio = 1.1

        kwargs = {'configuration': configuration}

        with mock.patch.object(utils, 'get_root_helper',
                               return_value=mock.Mock()):
            with mock.patch.object(remotefs_brick, 'RemoteFsClient',
                                   return_value=mock.Mock()):
                self.driver = nfs_base.NetAppNfsDriver(**kwargs)
                self.driver.ssc_enabled = False
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
        expected_total_capacity_gb = na_utils.round_down(
            fake.TOTAL_BYTES / units.Gi, '0.01')
        expected_free_capacity_gb = (na_utils.round_down(
            fake.AVAILABLE_BYTES / units.Gi, '0.01'))
        expected_reserved_percentage = round(
            100 * (1 - self.driver.configuration.nfs_used_ratio))

        result = self.driver._get_share_capacity_info(fake.NFS_SHARE)

        self.assertEqual(expected_total_capacity_gb,
                         result['total_capacity_gb'])
        self.assertEqual(expected_free_capacity_gb,
                         result['free_capacity_gb'])
        self.assertEqual(expected_reserved_percentage,
                         round(result['reserved_percentage']))

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

    def test_create_volume(self):
        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(na_utils, 'get_volume_extra_specs')
        self.mock_object(self.driver, '_do_create_volume')
        self.mock_object(self.driver, '_do_qos_for_volume')
        update_ssc = self.mock_object(self.driver, '_update_stale_vols')
        expected = {'provider_location': fake.NFS_SHARE}

        result = self.driver.create_volume(fake.NFS_VOLUME)

        self.assertEqual(expected, result)
        self.assertEqual(0, update_ssc.call_count)

    def test_create_volume_no_pool(self):
        volume = copy.deepcopy(fake.NFS_VOLUME)
        volume['host'] = '%s@%s' % (fake.HOST_NAME, fake.BACKEND_NAME)
        self.mock_object(self.driver, '_ensure_shares_mounted')

        self.assertRaises(exception.InvalidHost,
                          self.driver.create_volume,
                          volume)

    def test_create_volume_exception(self):
        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(na_utils, 'get_volume_extra_specs')
        mock_create = self.mock_object(self.driver, '_do_create_volume')
        mock_create.side_effect = Exception
        update_ssc = self.mock_object(self.driver, '_update_stale_vols')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          fake.NFS_VOLUME)

        self.assertEqual(0, update_ssc.call_count)

    def test_create_volume_from_snapshot(self):
        provider_location = fake.POOL_NAME
        snapshot = fake.CLONE_SOURCE
        self.mock_object(self.driver, '_clone_source_to_destination_volume',
                         mock.Mock(return_value=provider_location))

        result = self.driver.create_cloned_volume(fake.NFS_VOLUME,
                                                  snapshot)

        self.assertEqual(provider_location, result)

    def test_clone_source_to_destination_volume(self):
        self.mock_object(self.driver, '_get_volume_location', mock.Mock(
            return_value=fake.POOL_NAME))
        self.mock_object(na_utils, 'get_volume_extra_specs', mock.Mock(
            return_value=fake.EXTRA_SPECS))
        self.mock_object(
            self.driver,
            '_clone_with_extension_check')
        self.mock_object(self.driver, '_do_qos_for_volume')
        expected = {'provider_location': fake.POOL_NAME}

        result = self.driver._clone_source_to_destination_volume(
            fake.CLONE_SOURCE, fake.CLONE_DESTINATION)

        self.assertEqual(expected, result)

    def test_clone_source_to_destination_volume_with_do_qos_exception(self):
        self.mock_object(self.driver, '_get_volume_location', mock.Mock(
            return_value=fake.POOL_NAME))
        self.mock_object(na_utils, 'get_volume_extra_specs', mock.Mock(
            return_value=fake.EXTRA_SPECS))
        self.mock_object(
            self.driver,
            '_clone_with_extension_check')
        self.mock_object(self.driver, '_do_qos_for_volume', mock.Mock(
            side_effect=Exception))

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver._clone_source_to_destination_volume,
            fake.CLONE_SOURCE,
            fake.CLONE_DESTINATION)

    def test_clone_with_extension_check_equal_sizes(self):
        clone_source = copy.deepcopy(fake.CLONE_SOURCE)
        clone_source['size'] = fake.VOLUME['size']
        self.mock_object(self.driver, '_clone_backing_file_for_volume')
        self.mock_object(self.driver, 'local_path')
        mock_discover = self.mock_object(self.driver,
                                         '_discover_file_till_timeout')
        mock_discover.return_value = True
        self.mock_object(self.driver, '_set_rw_permissions')
        mock_extend_volume = self.mock_object(self.driver, 'extend_volume')

        self.driver._clone_with_extension_check(clone_source, fake.NFS_VOLUME)

        self.assertEqual(0, mock_extend_volume.call_count)

    def test_clone_with_extension_check_unequal_sizes(self):
        clone_source = copy.deepcopy(fake.CLONE_SOURCE)
        clone_source['size'] = fake.VOLUME['size'] + 1
        self.mock_object(self.driver, '_clone_backing_file_for_volume')
        self.mock_object(self.driver, 'local_path')
        mock_discover = self.mock_object(self.driver,
                                         '_discover_file_till_timeout')
        mock_discover.return_value = True
        self.mock_object(self.driver, '_set_rw_permissions')
        mock_extend_volume = self.mock_object(self.driver, 'extend_volume')

        self.driver._clone_with_extension_check(clone_source, fake.NFS_VOLUME)

        self.assertEqual(1, mock_extend_volume.call_count)

    def test_clone_with_extension_check_extend_exception(self):
        clone_source = copy.deepcopy(fake.CLONE_SOURCE)
        clone_source['size'] = fake.VOLUME['size'] + 1
        self.mock_object(self.driver, '_clone_backing_file_for_volume')
        self.mock_object(self.driver, 'local_path')
        mock_discover = self.mock_object(self.driver,
                                         '_discover_file_till_timeout')
        mock_discover.return_value = True
        self.mock_object(self.driver, '_set_rw_permissions')
        mock_extend_volume = self.mock_object(self.driver, 'extend_volume')
        mock_extend_volume.side_effect = Exception
        mock_cleanup = self.mock_object(self.driver,
                                        '_cleanup_volume_on_failure')

        self.assertRaises(exception.CinderException,
                          self.driver._clone_with_extension_check,
                          clone_source,
                          fake.NFS_VOLUME)

        self.assertEqual(1, mock_cleanup.call_count)

    def test_clone_with_extension_check_no_discovery(self):
        self.mock_object(self.driver, '_clone_backing_file_for_volume')
        self.mock_object(self.driver, 'local_path')
        self.mock_object(self.driver, '_set_rw_permissions')
        mock_discover = self.mock_object(self.driver,
                                         '_discover_file_till_timeout')
        mock_discover.return_value = False

        self.assertRaises(exception.CinderException,
                          self.driver._clone_with_extension_check,
                          fake.CLONE_SOURCE,
                          fake.NFS_VOLUME)

    def test_create_cloned_volume(self):
        provider_location = fake.POOL_NAME
        src_vref = fake.CLONE_SOURCE
        self.mock_object(self.driver, '_clone_source_to_destination_volume',
                         mock.Mock(return_value=provider_location))

        result = self.driver.create_cloned_volume(fake.NFS_VOLUME,
                                                  src_vref)
        self.assertEqual(provider_location, result)

    def test_do_qos_for_volume(self):
        self.assertRaises(NotImplementedError,
                          self.driver._do_qos_for_volume,
                          fake.NFS_VOLUME,
                          fake.EXTRA_SPECS)

    def test_cleanup_volume_on_failure(self):
        path = '%s/%s' % (fake.NFS_SHARE, fake.NFS_VOLUME['name'])
        mock_local_path = self.mock_object(self.driver, 'local_path')
        mock_local_path.return_value = path
        mock_exists_check = self.mock_object(os.path, 'exists')
        mock_exists_check.return_value = True
        mock_delete = self.mock_object(self.driver, '_delete_file_at_path')

        self.driver._cleanup_volume_on_failure(fake.NFS_VOLUME)

        mock_delete.assert_has_calls([mock.call(path)])

    def test_cleanup_volume_on_failure_no_path(self):
        self.mock_object(self.driver, 'local_path')
        mock_exists_check = self.mock_object(os.path, 'exists')
        mock_exists_check.return_value = False
        mock_delete = self.mock_object(self.driver, '_delete_file_at_path')

        self.driver._cleanup_volume_on_failure(fake.NFS_VOLUME)

        self.assertEqual(0, mock_delete.call_count)

    def test_get_vol_for_share(self):
        self.assertRaises(NotImplementedError,
                          self.driver._get_vol_for_share,
                          fake.NFS_SHARE)

    def test_get_export_ip_path_volume_id_provided(self):
        mock_get_host_ip = self.mock_object(self.driver, '_get_host_ip')
        mock_get_host_ip.return_value = fake.IPV4_ADDRESS

        mock_get_export_path = self.mock_object(
            self.driver, '_get_export_path')
        mock_get_export_path.return_value = fake.EXPORT_PATH

        expected = (fake.IPV4_ADDRESS, fake.EXPORT_PATH)

        result = self.driver._get_export_ip_path(fake.VOLUME_ID)

        self.assertEqual(expected, result)

    def test_get_export_ip_path_share_provided(self):
        expected = (fake.SHARE_IP, fake.EXPORT_PATH)

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
            fake.VOLUME_ID, fake.NFS_SHARE)

        self.assertEqual(expected, result)

    def test_get_export_ip_path_no_args(self):
        self.assertRaises(exception.InvalidInput,
                          self.driver._get_export_ip_path)

    def test_get_host_ip(self):
        mock_get_provider_location = self.mock_object(
            self.driver, '_get_provider_location')
        mock_get_provider_location.return_value = fake.NFS_SHARE
        expected = fake.SHARE_IP

        result = self.driver._get_host_ip(fake.VOLUME_ID)

        self.assertEqual(expected, result)

    def test_get_export_path(self):
        mock_get_provider_location = self.mock_object(
            self.driver, '_get_provider_location')
        mock_get_provider_location.return_value = fake.NFS_SHARE
        expected = fake.EXPORT_PATH

        result = self.driver._get_export_path(fake.VOLUME_ID)

        self.assertEqual(expected, result)

    def test_is_share_clone_compatible(self):
        self.assertRaises(NotImplementedError,
                          self.driver._is_share_clone_compatible,
                          fake.NFS_VOLUME,
                          fake.NFS_SHARE)

    @ddt.data(
        {'size': 12, 'thin': False, 'over': 1.0, 'res': 0, 'expected': True},
        {'size': 12, 'thin': False, 'over': 1.0, 'res': 5, 'expected': False},
        {'size': 12, 'thin': True, 'over': 1.0, 'res': 5, 'expected': False},
        {'size': 12, 'thin': True, 'over': 1.1, 'res': 5, 'expected': True},
        {'size': 240, 'thin': True, 'over': 20.0, 'res': 0, 'expected': True},
        {'size': 241, 'thin': True, 'over': 20.0, 'res': 0, 'expected': False},
    )
    @ddt.unpack
    def test_share_has_space_for_clone(self, size, thin, over, res, expected):
        total_bytes = 20 * units.Gi
        available_bytes = 12 * units.Gi

        with mock.patch.object(self.driver,
                               '_get_capacity_info',
                               return_value=(
                                   total_bytes, available_bytes)):
            with mock.patch.object(self.driver,
                                   'over_subscription_ratio',
                                   over):
                with mock.patch.object(self.driver,
                                       'reserved_percentage',
                                       res):
                    result = self.driver._share_has_space_for_clone(
                        fake.NFS_SHARE,
                        size,
                        thin=thin)
        self.assertEqual(expected, result)

    @ddt.data(
        {'size': 12, 'thin': False, 'over': 1.0, 'res': 0, 'expected': True},
        {'size': 12, 'thin': False, 'over': 1.0, 'res': 5, 'expected': False},
        {'size': 12, 'thin': True, 'over': 1.0, 'res': 5, 'expected': False},
        {'size': 12, 'thin': True, 'over': 1.1, 'res': 5, 'expected': True},
        {'size': 240, 'thin': True, 'over': 20.0, 'res': 0, 'expected': True},
        {'size': 241, 'thin': True, 'over': 20.0, 'res': 0, 'expected': False},
    )
    @ddt.unpack
    @mock.patch.object(nfs_base.NetAppNfsDriver, '_get_capacity_info')
    def test_share_has_space_for_clone2(self,
                                        mock_get_capacity,
                                        size, thin, over, res, expected):
        total_bytes = 20 * units.Gi
        available_bytes = 12 * units.Gi
        mock_get_capacity.return_value = (total_bytes, available_bytes)

        with mock.patch.object(self.driver,
                               'over_subscription_ratio',
                               over):
            with mock.patch.object(self.driver,
                                   'reserved_percentage',
                                   res):
                result = self.driver._share_has_space_for_clone(
                    fake.NFS_SHARE,
                    size,
                    thin=thin)
        self.assertEqual(expected, result)
