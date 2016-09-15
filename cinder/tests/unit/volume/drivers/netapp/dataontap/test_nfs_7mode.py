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
from cinder.volume.drivers.netapp.dataontap import nfs_base
from cinder.volume.drivers.netapp import utils as na_utils


@ddt.ddt
class NetApp7modeNfsDriverTestCase(test.TestCase):
    def setUp(self):
        super(NetApp7modeNfsDriverTestCase, self).setUp()

        kwargs = {
            'configuration': self.get_config_7mode(),
            'host': 'openstack@7modenfs',
        }

        with mock.patch.object(utils, 'get_root_helper',
                               return_value=mock.Mock()):
            with mock.patch.object(remotefs_brick, 'RemoteFsClient',
                                   return_value=mock.Mock()):
                self.driver = nfs_7mode.NetApp7modeNfsDriver(**kwargs)
                self.driver._mounted_shares = [fake.NFS_SHARE]
                self.driver.ssc_vols = True
                self.driver.zapi_client = mock.Mock()
                self.driver.perf_library = mock.Mock()

    def get_config_7mode(self):
        config = na_fakes.create_configuration_cmode()
        config.netapp_storage_protocol = 'nfs'
        config.netapp_login = 'root'
        config.netapp_password = 'pass'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'http'
        config.netapp_server_port = '80'
        return config

    @ddt.data({'share': None, 'is_snapshot': False},
              {'share': None, 'is_snapshot': True},
              {'share': 'fake_share', 'is_snapshot': False},
              {'share': 'fake_share', 'is_snapshot': True})
    @ddt.unpack
    def test_clone_backing_file_for_volume(self, share, is_snapshot):

        mock_get_export_ip_path = self.mock_object(
            self.driver, '_get_export_ip_path',
            mock.Mock(return_value=(fake.SHARE_IP, fake.EXPORT_PATH)))
        mock_get_actual_path_for_export = self.mock_object(
            self.driver.zapi_client, 'get_actual_path_for_export',
            mock.Mock(return_value='fake_path'))

        self.driver._clone_backing_file_for_volume(
            fake.FLEXVOL, 'fake_clone', fake.VOLUME_ID, share=share,
            is_snapshot=is_snapshot)

        mock_get_export_ip_path.assert_called_once_with(
            fake.VOLUME_ID, share)
        mock_get_actual_path_for_export.assert_called_once_with(
            fake.EXPORT_PATH)
        self.driver.zapi_client.clone_file.assert_called_once_with(
            'fake_path/' + fake.FLEXVOL, 'fake_path/fake_clone',
            None)

    @ddt.data({'nfs_sparsed_volumes': True},
              {'nfs_sparsed_volumes': False})
    @ddt.unpack
    def test_get_pool_stats(self, nfs_sparsed_volumes):

        self.driver.configuration.nfs_sparsed_volumes = nfs_sparsed_volumes
        thick = not nfs_sparsed_volumes

        total_capacity_gb = na_utils.round_down(
            fake.TOTAL_BYTES // units.Gi, '0.01')
        free_capacity_gb = na_utils.round_down(
            fake.AVAILABLE_BYTES // units.Gi, '0.01')
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
        self.mock_object(self.driver.perf_library,
                         'get_node_utilization',
                         mock.Mock(return_value=30.0))

        result = self.driver._get_pool_stats(filter_function='filter',
                                             goodness_function='goodness')

        expected = [{'pool_name': '192.168.99.24:/fake/export/path',
                     'QoS_support': False,
                     'consistencygroup_support': True,
                     'thick_provisioning_support': thick,
                     'thin_provisioning_support': not thick,
                     'free_capacity_gb': 12.0,
                     'total_capacity_gb': 4468.0,
                     'reserved_percentage': 7,
                     'max_over_subscription_ratio': 19.0,
                     'multiattach': True,
                     'provisioned_capacity_gb': 4456.0,
                     'utilization': 30.0,
                     'filter_function': 'filter',
                     'goodness_function': 'goodness'}]

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

    def test_delete_cgsnapshot(self):
        mock_delete_file = self.mock_object(self.driver, '_delete_file')

        model_update, snapshots_model_update = (
            self.driver.delete_cgsnapshot(
                fake.CG_CONTEXT, fake.CG_SNAPSHOT, [fake.SNAPSHOT]))

        mock_delete_file.assert_called_once_with(
            fake.SNAPSHOT['volume_id'], fake.SNAPSHOT['name'])
        self.assertIsNone(model_update)
        self.assertIsNone(snapshots_model_update)

    def test_get_snapshot_backing_flexvol_names(self):
        snapshots = [
            {'volume': {'host': 'hostA@192.168.99.25#/fake/volume1'}},
            {'volume': {'host': 'hostA@192.168.1.01#/fake/volume2'}},
            {'volume': {'host': 'hostA@192.168.99.25#/fake/volume3'}},
            {'volume': {'host': 'hostA@192.168.99.25#/fake/volume1'}},
        ]

        hosts = [snap['volume']['host'] for snap in snapshots]
        flexvols = self.driver._get_flexvol_names_from_hosts(hosts)

        self.assertEqual(3, len(flexvols))
        self.assertIn('volume1', flexvols)
        self.assertIn('volume2', flexvols)
        self.assertIn('volume3', flexvols)

    def test_check_for_setup_error(self):
        mock_get_ontapi_version = self.mock_object(
            self.driver.zapi_client, 'get_ontapi_version')
        mock_get_ontapi_version.return_value = ['1', '10']
        mock_add_looping_tasks = self.mock_object(
            self.driver, '_add_looping_tasks')
        mock_super_check_for_setup_error = self.mock_object(
            nfs_base.NetAppNfsDriver, 'check_for_setup_error')

        self.driver.check_for_setup_error()

        mock_get_ontapi_version.assert_called_once_with()
        mock_add_looping_tasks.assert_called_once_with()
        mock_super_check_for_setup_error.assert_called_once_with()

    def test_add_looping_tasks(self):
        mock_super_add_looping_tasks = self.mock_object(
            nfs_base.NetAppNfsDriver, '_add_looping_tasks')

        self.driver._add_looping_tasks()
        mock_super_add_looping_tasks.assert_called_once_with()

    def test_get_backing_flexvol_names(self):

        result = self.driver._get_backing_flexvol_names()

        self.assertEqual('path', result[0])
