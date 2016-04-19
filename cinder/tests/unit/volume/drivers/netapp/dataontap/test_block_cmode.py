# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
# Copyright (c) 2016 Mike Rooney. All rights reserved.
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
Mock unit tests for the NetApp block storage C-mode library
"""

import ddt
import mock
from oslo_service import loopingcall

from cinder import exception
from cinder import test
import cinder.tests.unit.volume.drivers.netapp.dataontap.fakes as fake
import cinder.tests.unit.volume.drivers.netapp.fakes as na_fakes
from cinder.volume.drivers.netapp.dataontap import block_base
from cinder.volume.drivers.netapp.dataontap import block_cmode
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_base
from cinder.volume.drivers.netapp.dataontap.performance import perf_cmode
from cinder.volume.drivers.netapp import utils as na_utils


@ddt.ddt
class NetAppBlockStorageCmodeLibraryTestCase(test.TestCase):
    """Test case for NetApp's C-Mode iSCSI library."""

    def setUp(self):
        super(NetAppBlockStorageCmodeLibraryTestCase, self).setUp()

        kwargs = {'configuration': self.get_config_cmode()}
        self.library = block_cmode.NetAppBlockStorageCmodeLibrary(
            'driver', 'protocol', **kwargs)

        self.library.zapi_client = mock.Mock()
        self.zapi_client = self.library.zapi_client
        self.library.perf_library = mock.Mock()
        self.library.ssc_library = mock.Mock()
        self.library.vserver = mock.Mock()
        self.fake_lun = block_base.NetAppLun(fake.LUN_HANDLE, fake.LUN_NAME,
                                             fake.SIZE, None)
        self.fake_snapshot_lun = block_base.NetAppLun(
            fake.SNAPSHOT_LUN_HANDLE, fake.SNAPSHOT_NAME, fake.SIZE, None)
        self.mock_object(self.library, 'lun_table')
        self.library.lun_table = {
            fake.LUN_NAME: self.fake_lun,
            fake.SNAPSHOT_NAME: self.fake_snapshot_lun,
        }
        self.mock_object(block_base.NetAppBlockStorageLibrary, 'delete_volume')

    def tearDown(self):
        super(NetAppBlockStorageCmodeLibraryTestCase, self).tearDown()

    def get_config_cmode(self):
        config = na_fakes.create_configuration_cmode()
        config.netapp_storage_protocol = 'iscsi'
        config.netapp_login = 'admin'
        config.netapp_password = 'pass'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'https'
        config.netapp_server_port = '443'
        config.netapp_vserver = 'openstack'
        return config

    @mock.patch.object(perf_cmode, 'PerformanceCmodeLibrary', mock.Mock())
    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.MagicMock(return_value=(1, 20)))
    @mock.patch.object(na_utils, 'check_flags')
    @mock.patch.object(block_base.NetAppBlockStorageLibrary, 'do_setup')
    def test_do_setup(self, super_do_setup, mock_check_flags):
        self.mock_object(client_base.Client, '_init_ssh_client')
        context = mock.Mock()

        self.library.do_setup(context)

        super_do_setup.assert_called_once_with(context)
        self.assertEqual(1, mock_check_flags.call_count)

    def test_check_for_setup_error(self):
        super_check_for_setup_error = self.mock_object(
            block_base.NetAppBlockStorageLibrary, 'check_for_setup_error')
        mock_check_api_permissions = self.mock_object(
            self.library.ssc_library, 'check_api_permissions')
        mock_start_periodic_tasks = self.mock_object(
            self.library, '_start_periodic_tasks')
        mock_get_pool_map = self.mock_object(
            self.library, '_get_flexvol_to_pool_map',
            mock.Mock(return_value={'fake_map': None}))

        self.library.check_for_setup_error()

        self.assertEqual(1, super_check_for_setup_error.call_count)
        mock_check_api_permissions.assert_called_once_with()
        self.assertEqual(1, mock_start_periodic_tasks.call_count)
        mock_get_pool_map.assert_called_once_with()

    def test_check_for_setup_error_no_filtered_pools(self):
        self.mock_object(block_base.NetAppBlockStorageLibrary,
                         'check_for_setup_error')
        mock_check_api_permissions = self.mock_object(
            self.library.ssc_library, 'check_api_permissions')
        self.mock_object(self.library, '_start_periodic_tasks')
        self.mock_object(
            self.library, '_get_flexvol_to_pool_map',
            mock.Mock(return_value={}))

        self.assertRaises(exception.NetAppDriverException,
                          self.library.check_for_setup_error)

        mock_check_api_permissions.assert_called_once_with()

    def test_find_mapped_lun_igroup(self):
        igroups = [fake.IGROUP1]
        self.zapi_client.get_igroup_by_initiators.return_value = igroups

        lun_maps = [{'initiator-group': fake.IGROUP1_NAME,
                     'lun-id': '1',
                     'vserver': fake.VSERVER_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN_PATH, fake.FC_FORMATTED_INITIATORS)

        self.assertEqual(fake.IGROUP1_NAME, igroup)
        self.assertEqual('1', lun_id)

    def test_find_mapped_lun_igroup_initiator_mismatch(self):
        self.zapi_client.get_igroup_by_initiators.return_value = []

        lun_maps = [{'initiator-group': fake.IGROUP1_NAME,
                     'lun-id': '1',
                     'vserver': fake.VSERVER_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN_PATH, fake.FC_FORMATTED_INITIATORS)

        self.assertIsNone(igroup)
        self.assertIsNone(lun_id)

    def test_find_mapped_lun_igroup_name_mismatch(self):
        igroups = [{'initiator-group-os-type': 'linux',
                    'initiator-group-type': 'fcp',
                    'initiator-group-name': 'igroup2'}]
        self.zapi_client.get_igroup_by_initiators.return_value = igroups

        lun_maps = [{'initiator-group': fake.IGROUP1_NAME,
                     'lun-id': '1',
                     'vserver': fake.VSERVER_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN_PATH, fake.FC_FORMATTED_INITIATORS)

        self.assertIsNone(igroup)
        self.assertIsNone(lun_id)

    def test_find_mapped_lun_igroup_no_igroup_prefix(self):
        igroups = [{'initiator-group-os-type': 'linux',
                    'initiator-group-type': 'fcp',
                    'initiator-group-name': 'igroup2'}]
        self.zapi_client.get_igroup_by_initiators.return_value = igroups

        lun_maps = [{'initiator-group': 'igroup2',
                     'lun-id': '1',
                     'vserver': fake.VSERVER_NAME}]
        self.zapi_client.get_lun_map.return_value = lun_maps

        (igroup, lun_id) = self.library._find_mapped_lun_igroup(
            fake.LUN_PATH, fake.FC_FORMATTED_INITIATORS)

        self.assertIsNone(igroup)
        self.assertIsNone(lun_id)

    def test_clone_lun_zero_block_count(self):
        """Test for when clone lun is not passed a block count."""

        self.library._get_lun_attr = mock.Mock(return_value={'Volume':
                                                             'fakeLUN'})
        self.library.zapi_client = mock.Mock()
        self.library.zapi_client.get_lun_by_args.return_value = [
            mock.Mock(spec=netapp_api.NaElement)]
        lun = fake.FAKE_LUN
        self.library._get_lun_by_args = mock.Mock(return_value=[lun])
        self.library._add_lun_to_table = mock.Mock()
        self.library._update_stale_vols = mock.Mock()

        self.library._clone_lun('fakeLUN', 'newFakeLUN', 'false')

        self.library.zapi_client.clone_lun.assert_called_once_with(
            'fakeLUN', 'fakeLUN', 'newFakeLUN', 'false', block_count=0,
            dest_block=0, src_block=0, qos_policy_group_name=None,
            source_snapshot=None)

    def test_clone_lun_blocks(self):
        """Test for when clone lun is passed block information."""
        block_count = 10
        src_block = 10
        dest_block = 30

        self.library._get_lun_attr = mock.Mock(return_value={'Volume':
                                                             'fakeLUN'})
        self.library.zapi_client = mock.Mock()
        self.library.zapi_client.get_lun_by_args.return_value = [
            mock.Mock(spec=netapp_api.NaElement)]
        lun = fake.FAKE_LUN
        self.library._get_lun_by_args = mock.Mock(return_value=[lun])
        self.library._add_lun_to_table = mock.Mock()
        self.library._update_stale_vols = mock.Mock()

        self.library._clone_lun('fakeLUN', 'newFakeLUN', 'false',
                                block_count=block_count, src_block=src_block,
                                dest_block=dest_block)

        self.library.zapi_client.clone_lun.assert_called_once_with(
            'fakeLUN', 'fakeLUN', 'newFakeLUN', 'false',
            block_count=block_count, dest_block=dest_block,
            src_block=src_block, qos_policy_group_name=None,
            source_snapshot=None)

    def test_clone_lun_no_space_reservation(self):
        """Test for when space_reservation is not passed."""

        self.library._get_lun_attr = mock.Mock(return_value={'Volume':
                                                             'fakeLUN'})
        self.library.zapi_client = mock.Mock()
        self.library.lun_space_reservation = 'false'
        self.library.zapi_client.get_lun_by_args.return_value = [
            mock.Mock(spec=netapp_api.NaElement)]
        lun = fake.FAKE_LUN
        self.library._get_lun_by_args = mock.Mock(return_value=[lun])
        self.library._add_lun_to_table = mock.Mock()
        self.library._update_stale_vols = mock.Mock()

        self.library._clone_lun('fakeLUN', 'newFakeLUN')

        self.library.zapi_client.clone_lun.assert_called_once_with(
            'fakeLUN', 'fakeLUN', 'newFakeLUN', 'false', block_count=0,
            dest_block=0, src_block=0, qos_policy_group_name=None,
            source_snapshot=None)

    def test_get_fc_target_wwpns(self):
        ports = [fake.FC_FORMATTED_TARGET_WWPNS[0],
                 fake.FC_FORMATTED_TARGET_WWPNS[1]]
        self.zapi_client.get_fc_target_wwpns.return_value = ports

        result = self.library._get_fc_target_wwpns()

        self.assertSetEqual(set(ports), set(result))

    @mock.patch.object(block_cmode.NetAppBlockStorageCmodeLibrary,
                       '_get_pool_stats', mock.Mock())
    def test_vol_stats_calls_provide_ems(self):
        self.library.zapi_client.provide_ems = mock.Mock()

        self.library.get_volume_stats(refresh=True)

        self.assertEqual(1, self.library.zapi_client.provide_ems.call_count)

    def test_create_lun(self):
        self.library._create_lun(
            fake.VOLUME_ID, fake.LUN_ID, fake.LUN_SIZE, fake.LUN_METADATA)

        self.library.zapi_client.create_lun.assert_called_once_with(
            fake.VOLUME_ID, fake.LUN_ID, fake.LUN_SIZE, fake.LUN_METADATA,
            None)

    def test_get_preferred_target_from_list(self):
        target_details_list = fake.ISCSI_TARGET_DETAILS_LIST
        operational_addresses = [
            target['address']
            for target in target_details_list[2:]]
        self.zapi_client.get_operational_lif_addresses = (
            mock.Mock(return_value=operational_addresses))

        result = self.library._get_preferred_target_from_list(
            target_details_list)

        self.assertEqual(target_details_list[2], result)

    def test_get_pool_stats(self):

        ssc = {
            'vola': {
                'pool_name': 'vola',
                'thick_provisioning_support': True,
                'thin_provisioning_support': False,
                'netapp_thin_provisioned': 'false',
                'netapp_compression': 'false',
                'netapp_mirrored': 'false',
                'netapp_dedup': 'true',
                'aggregate': 'aggr1',
                'netapp_raid_type': 'raid_dp',
                'netapp_disk_type': 'SSD',
            },
        }
        mock_get_ssc = self.mock_object(self.library.ssc_library,
                                        'get_ssc',
                                        mock.Mock(return_value=ssc))

        self.library.reserved_percentage = 5
        self.library.max_over_subscription_ratio = 10
        self.library.perf_library.get_node_utilization_for_pool = (
            mock.Mock(return_value=30.0))
        mock_capacities = {
            'size-total': 10737418240.0,
            'size-available': 2147483648.0,
        }
        self.mock_object(
            self.zapi_client, 'get_flexvol_capacity',
            mock.Mock(return_value=mock_capacities))

        result = self.library._get_pool_stats(filter_function='filter',
                                              goodness_function='goodness')

        expected = [{
            'pool_name': 'vola',
            'QoS_support': True,
            'consistencygroup_support': True,
            'reserved_percentage': 5,
            'max_over_subscription_ratio': 10.0,
            'total_capacity_gb': 10.0,
            'free_capacity_gb': 2.0,
            'provisioned_capacity_gb': 8.0,
            'utilization': 30.0,
            'filter_function': 'filter',
            'goodness_function': 'goodness',
            'thick_provisioning_support': True,
            'thin_provisioning_support': False,
            'netapp_thin_provisioned': 'false',
            'netapp_compression': 'false',
            'netapp_mirrored': 'false',
            'netapp_dedup': 'true',
            'aggregate': 'aggr1',
            'netapp_raid_type': 'raid_dp',
            'netapp_disk_type': 'SSD',
        }]

        self.assertEqual(expected, result)
        mock_get_ssc.assert_called_once_with()

    @ddt.data({}, None)
    def test_get_pool_stats_no_ssc_vols(self, ssc):

        mock_get_ssc = self.mock_object(self.library.ssc_library,
                                        'get_ssc',
                                        mock.Mock(return_value=ssc))

        pools = self.library._get_pool_stats()

        self.assertListEqual([], pools)
        mock_get_ssc.assert_called_once_with()

    @ddt.data('open+|demix+', 'open.+', '.+\d', '^((?!mix+).)*$',
              'open123, open321')
    def test_get_pool_map_match_selected_pools(self, patterns):

        self.library.configuration.netapp_pool_name_search_pattern = patterns
        mock_list_flexvols = self.mock_object(
            self.zapi_client, 'list_flexvols',
            mock.Mock(return_value=fake.FAKE_CMODE_VOLUMES))

        result = self.library._get_flexvol_to_pool_map()

        expected = {
            'open123': {
                'pool_name': 'open123',
            },
            'open321': {
                'pool_name': 'open321',
            },
        }
        self.assertEqual(expected, result)
        mock_list_flexvols.assert_called_once_with()

    @ddt.data('', 'mix.+|open.+', '.+', 'open123, mixed, open321',
              '.*?')
    def test_get_pool_map_match_all_pools(self, patterns):

        self.library.configuration.netapp_pool_name_search_pattern = patterns
        mock_list_flexvols = self.mock_object(
            self.zapi_client, 'list_flexvols',
            mock.Mock(return_value=fake.FAKE_CMODE_VOLUMES))

        result = self.library._get_flexvol_to_pool_map()

        self.assertEqual(fake.FAKE_CMODE_POOL_MAP, result)
        mock_list_flexvols.assert_called_once_with()

    def test_get_pool_map_invalid_conf(self):
        """Verify an exception is raised if the regex pattern is invalid"""
        self.library.configuration.netapp_pool_name_search_pattern = '(.+'

        self.assertRaises(exception.InvalidConfigurationValue,
                          self.library._get_flexvol_to_pool_map)

    @ddt.data('abc|stackopen|openstack|abc*', 'abc', 'stackopen', 'openstack',
              'abc*', '^$')
    def test_get_pool_map_non_matching_patterns(self, patterns):

        self.library.configuration.netapp_pool_name_search_pattern = patterns
        mock_list_flexvols = self.mock_object(
            self.zapi_client, 'list_flexvols',
            mock.Mock(return_value=fake.FAKE_CMODE_VOLUMES))

        result = self.library._get_flexvol_to_pool_map()

        self.assertEqual({}, result)
        mock_list_flexvols.assert_called_once_with()

    def test_update_ssc(self):

        mock_get_pool_map = self.mock_object(
            self.library, '_get_flexvol_to_pool_map',
            mock.Mock(return_value=fake.FAKE_CMODE_VOLUMES))

        result = self.library._update_ssc()

        self.assertIsNone(result)
        mock_get_pool_map.assert_called_once_with()
        self.library.ssc_library.update_ssc.assert_called_once_with(
            fake.FAKE_CMODE_VOLUMES)

    def test_delete_volume(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(
                             return_value=fake.QOS_POLICY_GROUP_INFO))
        self.mock_object(self.library, '_mark_qos_policy_group_for_deletion')

        self.library.delete_volume(fake.VOLUME)

        (block_base.NetAppBlockStorageLibrary.delete_volume.
            assert_called_once_with(fake.VOLUME))
        na_utils.get_valid_qos_policy_group_info.assert_called_once_with(
            fake.VOLUME)
        (self.library._mark_qos_policy_group_for_deletion.
            assert_called_once_with(fake.QOS_POLICY_GROUP_INFO))

    def test_delete_volume_get_valid_qos_policy_group_info_exception(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(side_effect=exception.Invalid))
        self.mock_object(self.library, '_mark_qos_policy_group_for_deletion')

        self.library.delete_volume(fake.VOLUME)

        (block_base.NetAppBlockStorageLibrary.delete_volume.
            assert_called_once_with(fake.VOLUME))
        (self.library._mark_qos_policy_group_for_deletion.
            assert_called_once_with(None))

    def test_setup_qos_for_volume(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(
                             return_value=fake.QOS_POLICY_GROUP_INFO))
        self.mock_object(self.zapi_client, 'provision_qos_policy_group')

        result = self.library._setup_qos_for_volume(fake.VOLUME,
                                                    fake.EXTRA_SPECS)

        self.assertEqual(fake.QOS_POLICY_GROUP_INFO, result)
        self.zapi_client.provision_qos_policy_group.\
            assert_called_once_with(fake.QOS_POLICY_GROUP_INFO)

    def test_setup_qos_for_volume_exception_path(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(
                             side_effect=exception.Invalid))
        self.mock_object(self.zapi_client, 'provision_qos_policy_group')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.library._setup_qos_for_volume, fake.VOLUME,
                          fake.EXTRA_SPECS)

        self.assertEqual(0,
                         self.zapi_client.
                         provision_qos_policy_group.call_count)

    def test_mark_qos_policy_group_for_deletion(self):
        self.mock_object(self.zapi_client,
                         'mark_qos_policy_group_for_deletion')

        self.library._mark_qos_policy_group_for_deletion(
            fake.QOS_POLICY_GROUP_INFO)

        self.zapi_client.mark_qos_policy_group_for_deletion\
            .assert_called_once_with(fake.QOS_POLICY_GROUP_INFO)

    def test_unmanage(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(return_value=fake.QOS_POLICY_GROUP_INFO))
        self.mock_object(self.library, '_mark_qos_policy_group_for_deletion')
        self.mock_object(block_base.NetAppBlockStorageLibrary, 'unmanage')

        self.library.unmanage(fake.VOLUME)

        na_utils.get_valid_qos_policy_group_info.assert_called_once_with(
            fake.VOLUME)
        self.library._mark_qos_policy_group_for_deletion\
            .assert_called_once_with(fake.QOS_POLICY_GROUP_INFO)
        block_base.NetAppBlockStorageLibrary.unmanage.assert_called_once_with(
            fake.VOLUME)

    def test_unmanage_w_invalid_qos_policy(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         mock.Mock(side_effect=exception.Invalid))
        self.mock_object(self.library, '_mark_qos_policy_group_for_deletion')
        self.mock_object(block_base.NetAppBlockStorageLibrary, 'unmanage')

        self.library.unmanage(fake.VOLUME)

        na_utils.get_valid_qos_policy_group_info.assert_called_once_with(
            fake.VOLUME)
        self.library._mark_qos_policy_group_for_deletion\
            .assert_called_once_with(None)
        block_base.NetAppBlockStorageLibrary.unmanage.assert_called_once_with(
            fake.VOLUME)

    def test_manage_existing_lun_same_name(self):
        mock_lun = block_base.NetAppLun('handle', 'name', '1',
                                        {'Path': '/vol/FAKE_CMODE_VOL1/name'})
        self.library._get_existing_vol_with_manage_ref = mock.Mock(
            return_value=mock_lun)
        self.mock_object(na_utils, 'get_volume_extra_specs')
        self.mock_object(na_utils, 'log_extra_spec_warnings')
        self.library._check_volume_type_for_lun = mock.Mock()
        self.library._setup_qos_for_volume = mock.Mock()
        self.mock_object(na_utils, 'get_qos_policy_group_name_from_info',
                         mock.Mock(return_value=fake.QOS_POLICY_GROUP_NAME))
        self.library._add_lun_to_table = mock.Mock()
        self.zapi_client.move_lun = mock.Mock()
        mock_set_lun_qos_policy_group = self.mock_object(
            self.zapi_client, 'set_lun_qos_policy_group')

        self.library.manage_existing({'name': 'name'}, {'ref': 'ref'})

        self.library._get_existing_vol_with_manage_ref.assert_called_once_with(
            {'ref': 'ref'})
        self.assertEqual(1, self.library._check_volume_type_for_lun.call_count)
        self.assertEqual(1, self.library._add_lun_to_table.call_count)
        self.assertEqual(0, self.zapi_client.move_lun.call_count)
        self.assertEqual(1, mock_set_lun_qos_policy_group.call_count)

    def test_manage_existing_lun_new_path(self):
        mock_lun = block_base.NetAppLun(
            'handle', 'name', '1', {'Path': '/vol/FAKE_CMODE_VOL1/name'})
        self.library._get_existing_vol_with_manage_ref = mock.Mock(
            return_value=mock_lun)
        self.mock_object(na_utils, 'get_volume_extra_specs')
        self.mock_object(na_utils, 'log_extra_spec_warnings')
        self.library._check_volume_type_for_lun = mock.Mock()
        self.library._add_lun_to_table = mock.Mock()
        self.zapi_client.move_lun = mock.Mock()

        self.library.manage_existing({'name': 'volume'}, {'ref': 'ref'})

        self.assertEqual(
            2, self.library._get_existing_vol_with_manage_ref.call_count)
        self.assertEqual(1, self.library._check_volume_type_for_lun.call_count)
        self.assertEqual(1, self.library._add_lun_to_table.call_count)
        self.zapi_client.move_lun.assert_called_once_with(
            '/vol/FAKE_CMODE_VOL1/name', '/vol/FAKE_CMODE_VOL1/volume')

    def test_start_periodic_tasks(self):

        mock_update_ssc = self.mock_object(
            self.library, '_update_ssc')
        mock_remove_unused_qos_policy_groups = self.mock_object(
            self.zapi_client, 'remove_unused_qos_policy_groups')

        update_ssc_periodic_task = mock.Mock()
        harvest_qos_periodic_task = mock.Mock()
        side_effect = [update_ssc_periodic_task, harvest_qos_periodic_task]
        mock_loopingcall = self.mock_object(
            loopingcall, 'FixedIntervalLoopingCall',
            mock.Mock(side_effect=side_effect))

        self.library._start_periodic_tasks()

        mock_loopingcall.assert_has_calls([
            mock.call(mock_update_ssc),
            mock.call(mock_remove_unused_qos_policy_groups)])
        self.assertTrue(update_ssc_periodic_task.start.called)
        self.assertTrue(harvest_qos_periodic_task.start.called)
        mock_update_ssc.assert_called_once_with()
