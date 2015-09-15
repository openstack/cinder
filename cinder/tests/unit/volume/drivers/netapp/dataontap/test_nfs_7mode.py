# Copyright (c) 2015 Tom Barron.  All rights reserved.
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
Unit tests for the NetApp 7mode NFS storage driver
"""

import ddt
import mock
from os_brick.remotefs import remotefs as remotefs_brick
from oslo_utils import units

from cinder import test
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as fake
from cinder.tests.unit.volume.drivers.netapp import fakes as na_fakes
from cinder import utils
from cinder.volume.drivers.netapp.dataontap import nfs_7mode
from cinder.volume.drivers.netapp import utils as na_utils


@ddt.ddt
class NetApp7modeNfsDriverTestCase(test.TestCase):
    def setUp(self):
        super(NetApp7modeNfsDriverTestCase, self).setUp()

        kwargs = {'configuration': self.get_config_7mode()}

        with mock.patch.object(utils, 'get_root_helper',
                               return_value=mock.Mock()):
            with mock.patch.object(remotefs_brick, 'RemoteFsClient',
                                   return_value=mock.Mock()):
                self.driver = nfs_7mode.NetApp7modeNfsDriver(**kwargs)
                self.driver._mounted_shares = [fake.NFS_SHARE]
                self.driver.ssc_vols = True
                self.driver.zapi_client = mock.Mock()

    def get_config_7mode(self):
        config = na_fakes.create_configuration_cmode()
        config.netapp_storage_protocol = 'nfs'
        config.netapp_login = 'root'
        config.netapp_password = 'pass'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'http'
        config.netapp_server_port = '80'
        return config

    @ddt.data({'nfs_sparsed_volumes': True},
              {'nfs_sparsed_volumes': False})
    @ddt.unpack
    def test_get_pool_stats(self, nfs_sparsed_volumes):

        self.driver.configuration.nfs_sparsed_volumes = nfs_sparsed_volumes
        thick = not nfs_sparsed_volumes

        total_capacity_gb = na_utils.round_down(
            fake.TOTAL_BYTES / units.Gi, '0.01')
        free_capacity_gb = na_utils.round_down(
            fake.AVAILABLE_BYTES / units.Gi, '0.01')
        provisioned_capacity_gb = total_capacity_gb - free_capacity_gb
        capacity = {
            'reserved_percentage': fake.RESERVED_PERCENTAGE,
            'max_over_subscription_ratio': fake.MAX_OVER_SUBSCRIPTION_RATIO,
            'total_capacity_gb': total_capacity_gb,
            'free_capacity_gb': free_capacity_gb,
            'provisioned_capacity_gb': provisioned_capacity_gb,
        }
        self.mock_object(self.driver,
                         '_get_share_capacity_info',
                         mock.Mock(return_value=capacity))

        result = self.driver._get_pool_stats()

        expected = [{'pool_name': '192.168.99.24:/fake/export/path',
                     'QoS_support': False,
                     'thick_provisioning_support': thick,
                     'thin_provisioning_support': not thick,
                     'free_capacity_gb': 12.0,
                     'total_capacity_gb': 4468.0,
                     'reserved_percentage': 7,
                     'max_over_subscription_ratio': 19.0,
                     'provisioned_capacity_gb': 4456.0}]

        self.assertEqual(expected, result)

    def test_shortlist_del_eligible_files(self):
        mock_get_path_for_export = self.mock_object(
            self.driver.zapi_client, 'get_actual_path_for_export')
        mock_get_path_for_export.return_value = fake.FLEXVOL

        mock_get_file_usage = self.mock_object(
            self.driver.zapi_client, 'get_file_usage')
        mock_get_file_usage.return_value = fake.CAPACITY_VALUES[0]

        expected = [(old_file, fake.CAPACITY_VALUES[0]) for old_file
                    in fake.FILE_LIST]

        result = self.driver._shortlist_del_eligible_files(
            fake.NFS_SHARE, fake.FILE_LIST)

        self.assertEqual(expected, result)

    def test_shortlist_del_eligible_files_empty_list(self):
        mock_get_export_ip_path = self.mock_object(
            self.driver, '_get_export_ip_path')
        mock_get_export_ip_path.return_value = ('', '/export_path')

        mock_get_path_for_export = self.mock_object(
            self.driver.zapi_client, 'get_actual_path_for_export')
        mock_get_path_for_export.return_value = fake.FLEXVOL

        result = self.driver._shortlist_del_eligible_files(
            fake.NFS_SHARE, [])

        self.assertEqual([], result)

    @ddt.data({'has_space': True, 'expected': True},
              {'has_space': False, 'expected': False})
    @ddt.unpack
    def test_is_share_clone_compatible(self, has_space, expected):
        mock_share_has_space_for_clone = self.mock_object(
            self.driver, '_share_has_space_for_clone')
        mock_share_has_space_for_clone.return_value = has_space

        result = self.driver._is_share_clone_compatible(fake.VOLUME,
                                                        fake.NFS_SHARE)

        self.assertEqual(expected, result)
