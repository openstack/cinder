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

import mock
from oslo_utils import units

from cinder.brick.remotefs import remotefs as remotefs_brick
from cinder import test
from cinder.tests.volume.drivers.netapp.dataontap import fakes as fake
from cinder.tests.volume.drivers.netapp import fakes as na_fakes
from cinder import utils
from cinder.volume.drivers.netapp.dataontap import nfs_7mode
from cinder.volume.drivers.netapp import utils as na_utils


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

    def test_get_pool_stats(self):

        total_capacity_gb = na_utils.round_down(
            fake.TOTAL_BYTES / units.Gi, '0.01')
        free_capacity_gb = na_utils.round_down(
            fake.AVAILABLE_BYTES / units.Gi, '0.01')
        capacity = dict(
            reserved_percentage = fake.RESERVED_PERCENTAGE,
            total_capacity_gb = total_capacity_gb,
            free_capacity_gb = free_capacity_gb,
        )

        mock_get_capacity = self.mock_object(
            self.driver, '_get_share_capacity_info')
        mock_get_capacity.return_value = capacity

        result = self.driver._get_pool_stats()

        self.assertEqual(fake.RESERVED_PERCENTAGE,
                         result[0]['reserved_percentage'])
        self.assertEqual(total_capacity_gb, result[0]['total_capacity_gb'])
        self.assertEqual(free_capacity_gb, result[0]['free_capacity_gb'])

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
