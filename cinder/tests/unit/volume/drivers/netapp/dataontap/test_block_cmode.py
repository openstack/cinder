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

from cinder import exception
from cinder.objects import fields
from cinder import test
import cinder.tests.unit.volume.drivers.netapp.dataontap.fakes as fake
from cinder.tests.unit.volume.drivers.netapp.dataontap.utils import fakes as\
    fake_utils
import cinder.tests.unit.volume.drivers.netapp.fakes as na_fakes
from cinder.volume.drivers.netapp.dataontap import block_base
from cinder.volume.drivers.netapp.dataontap import block_cmode
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_base
from cinder.volume.drivers.netapp.dataontap.performance import perf_cmode
from cinder.volume.drivers.netapp.dataontap.utils import capabilities
from cinder.volume.drivers.netapp.dataontap.utils import data_motion
from cinder.volume.drivers.netapp.dataontap.utils import loopingcalls
from cinder.volume.drivers.netapp.dataontap.utils import utils as dot_utils
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import utils as volume_utils


@ddt.ddt
class NetAppBlockStorageCmodeLibraryTestCase(test.TestCase):
    """Test case for NetApp's C-Mode iSCSI library."""

    def setUp(self):
        super(NetAppBlockStorageCmodeLibraryTestCase, self).setUp()

        kwargs = {
            'configuration': self.get_config_cmode(),
            'host': 'openstack@cdotblock',
        }
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

    def get_config_cmode(self):
        config = na_fakes.create_configuration_cmode()
        config.netapp_storage_protocol = 'iscsi'
        config.netapp_login = 'admin'
        config.netapp_password = 'pass'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'https'
        config.netapp_server_port = '443'
        config.netapp_vserver = 'openstack'
        config.netapp_api_trace_pattern = 'fake_regex'
        return config

    @mock.patch.object(perf_cmode, 'PerformanceCmodeLibrary', mock.Mock())
    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.MagicMock(return_value=(1, 20)))
    @mock.patch.object(capabilities.CapabilitiesLibrary,
                       'cluster_user_supported')
    @mock.patch.object(capabilities.CapabilitiesLibrary,
                       'check_api_permissions')
    @mock.patch.object(na_utils, 'check_flags')
    @mock.patch.object(block_base.NetAppBlockStorageLibrary, 'do_setup')
    @mock.patch.object(client_base.Client, 'get_ontap_version',
                       mock.MagicMock(return_value='9.6'))
    def test_do_setup(self, super_do_setup, mock_check_flags,
                      mock_check_api_permissions, mock_cluster_user_supported):
        self.mock_object(client_base.Client, '_init_ssh_client')
        self.mock_object(
            dot_utils, 'get_backend_configuration',
            return_value=self.get_config_cmode())
        context = mock.Mock()

        self.library.do_setup(context)

        super_do_setup.assert_called_once_with(context)
        self.assertEqual(1, mock_check_flags.call_count)
        mock_check_api_permissions.assert_called_once_with()
        mock_cluster_user_supported.assert_called_once_with()

    def test_check_for_setup_error(self):
        super_check_for_setup_error = self.mock_object(
            block_base.NetAppBlockStorageLibrary, 'check_for_setup_error')
        mock_get_pool_map = self.mock_object(
            self.library, '_get_flexvol_to_pool_map',
            return_value={'fake_map': None})
        mock_add_looping_tasks = self.mock_object(
            self.library, '_add_looping_tasks')

        self.library.check_for_setup_error()

        self.assertEqual(1, super_check_for_setup_error.call_count)
        self.assertEqual(1, mock_add_looping_tasks.call_count)
        mock_get_pool_map.assert_called_once_with()
        mock_add_looping_tasks.assert_called_once_with()

    def test_check_for_setup_error_no_filtered_pools(self):
        self.mock_object(block_base.NetAppBlockStorageLibrary,
                         'check_for_setup_error')
        self.mock_object(self.library, '_add_looping_tasks')
        self.mock_object(
            self.library, '_get_flexvol_to_pool_map', return_value={})

        self.assertRaises(exception.NetAppDriverException,
                          self.library.check_for_setup_error)

    @ddt.data({'replication_enabled': True, 'failed_over': False,
               'cluster_credentials': True},
              {'replication_enabled': True, 'failed_over': True,
               'cluster_credentials': True},
              {'replication_enabled': False, 'failed_over': False,
               'cluster_credentials': False})
    @ddt.unpack
    def test_handle_housekeeping_tasks(
            self, replication_enabled, failed_over, cluster_credentials):
        self.library.using_cluster_credentials = cluster_credentials
        ensure_mirrors = self.mock_object(data_motion.DataMotionMixin,
                                          'ensure_snapmirrors')
        self.mock_object(self.library.ssc_library, 'get_ssc_flexvol_names',
                         return_value=fake_utils.SSC.keys())
        mock_remove_unused_qos_policy_groups = self.mock_object(
            self.zapi_client, 'remove_unused_qos_policy_groups')
        self.library.replication_enabled = replication_enabled
        self.library.failed_over = failed_over

        self.library._handle_housekeeping_tasks()

        if self.library.using_cluster_credentials:
            mock_remove_unused_qos_policy_groups.assert_called_once_with()
        else:
            mock_remove_unused_qos_policy_groups.assert_not_called()

        if replication_enabled and not failed_over:
            ensure_mirrors.assert_called_once_with(
                self.library.configuration, self.library.backend_name,
                fake_utils.SSC.keys())
        else:
            self.assertFalse(ensure_mirrors.called)

    def test_handle_ems_logging(self):
        volume_list = ['vol0', 'vol1', 'vol2']
        self.mock_object(
            self.library.ssc_library, 'get_ssc_flexvol_names',
            return_value=volume_list)
        self.mock_object(
            dot_utils, 'build_ems_log_message_0',
            return_value='fake_base_ems_log_message')
        self.mock_object(
            dot_utils, 'build_ems_log_message_1',
            return_value='fake_pool_ems_log_message')
        mock_send_ems_log_message = self.mock_object(
            self.zapi_client, 'send_ems_log_message')

        self.library._handle_ems_logging()

        mock_send_ems_log_message.assert_has_calls([
            mock.call('fake_base_ems_log_message'),
            mock.call('fake_pool_ems_log_message'),
        ])
        dot_utils.build_ems_log_message_0.assert_called_once_with(
            self.library.driver_name, self.library.app_version)
        dot_utils.build_ems_log_message_1.assert_called_once_with(
            self.library.driver_name, self.library.app_version,
            self.library.vserver, volume_list, [])

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

        self.library._clone_lun('fakeLUN', 'newFakeLUN', 'false')

        self.library.zapi_client.clone_lun.assert_called_once_with(
            'fakeLUN', 'fakeLUN', 'newFakeLUN', 'false', block_count=0,
            dest_block=0, src_block=0, qos_policy_group_name=None,
            source_snapshot=None, is_snapshot=False)

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

        self.library._clone_lun('fakeLUN', 'newFakeLUN', 'false',
                                block_count=block_count, src_block=src_block,
                                dest_block=dest_block)

        self.library.zapi_client.clone_lun.assert_called_once_with(
            'fakeLUN', 'fakeLUN', 'newFakeLUN', 'false',
            block_count=block_count, dest_block=dest_block,
            src_block=src_block, qos_policy_group_name=None,
            source_snapshot=None, is_snapshot=False)

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

        self.library._clone_lun('fakeLUN', 'newFakeLUN', is_snapshot=True)

        self.library.zapi_client.clone_lun.assert_called_once_with(
            'fakeLUN', 'fakeLUN', 'newFakeLUN', 'false', block_count=0,
            dest_block=0, src_block=0, qos_policy_group_name=None,
            source_snapshot=None, is_snapshot=True)

    def test_get_fc_target_wwpns(self):
        ports = [fake.FC_FORMATTED_TARGET_WWPNS[0],
                 fake.FC_FORMATTED_TARGET_WWPNS[1]]
        self.zapi_client.get_fc_target_wwpns.return_value = ports

        result = self.library._get_fc_target_wwpns()

        self.assertSetEqual(set(ports), set(result))

    def test_create_lun(self):
        self.library._create_lun(
            fake.VOLUME_ID, fake.LUN_ID, fake.LUN_SIZE, fake.LUN_METADATA)

        self.library.zapi_client.create_lun.assert_called_once_with(
            fake.VOLUME_ID, fake.LUN_ID, fake.LUN_SIZE, fake.LUN_METADATA,
            None)

    @ddt.data({'replication_backends': [], 'cluster_credentials': False},
              {'replication_backends': ['target_1', 'target_2'],
               'cluster_credentials': True})
    @ddt.unpack
    def test_get_pool_stats(self, replication_backends, cluster_credentials):
        self.library.using_cluster_credentials = cluster_credentials
        ssc = {
            'vola': {
                'pool_name': 'vola',
                'thick_provisioning_support': True,
                'thin_provisioning_support': False,
                'netapp_thin_provisioned': 'false',
                'netapp_compression': 'false',
                'netapp_mirrored': 'false',
                'netapp_dedup': 'true',
                'netapp_aggregate': 'aggr1',
                'netapp_raid_type': 'raid_dp',
                'netapp_disk_type': 'SSD',
            },
        }
        mock_get_ssc = self.mock_object(self.library.ssc_library,
                                        'get_ssc',
                                        return_value=ssc)
        mock_get_aggrs = self.mock_object(self.library.ssc_library,
                                          'get_ssc_aggregates',
                                          return_value=['aggr1'])
        self.mock_object(self.library, 'get_replication_backend_names',
                         return_value=replication_backends)

        self.library.reserved_percentage = 5
        self.library.max_over_subscription_ratio = 10
        self.library.perf_library.get_node_utilization_for_pool = (
            mock.Mock(return_value=30.0))
        mock_capacities = {
            'size-total': 10737418240.0,
            'size-available': 2147483648.0,
        }
        self.mock_object(self.zapi_client,
                         'get_flexvol_capacity',
                         return_value=mock_capacities)
        self.mock_object(self.zapi_client,
                         'get_flexvol_dedupe_used_percent',
                         return_value=55.0)

        aggr_capacities = {
            'aggr1': {
                'percent-used': 45,
                'size-available': 59055800320.0,
                'size-total': 107374182400.0,
            },
        }
        mock_get_aggr_capacities = self.mock_object(
            self.zapi_client, 'get_aggregate_capacities',
            return_value=aggr_capacities)

        result = self.library._get_pool_stats(filter_function='filter',
                                              goodness_function='goodness')

        expected = [{
            'pool_name': 'vola',
            'QoS_support': True,
            'consistencygroup_support': True,
            'consistent_group_snapshot_enabled': True,
            'reserved_percentage': 5,
            'max_over_subscription_ratio': 10.0,
            'multiattach': True,
            'total_capacity_gb': 10.0,
            'free_capacity_gb': 2.0,
            'netapp_dedupe_used_percent': 55.0,
            'netapp_aggregate_used_percent': 45,
            'utilization': 30.0,
            'filter_function': 'filter',
            'goodness_function': 'goodness',
            'thick_provisioning_support': True,
            'thin_provisioning_support': False,
            'netapp_thin_provisioned': 'false',
            'netapp_compression': 'false',
            'netapp_mirrored': 'false',
            'netapp_dedup': 'true',
            'netapp_aggregate': 'aggr1',
            'netapp_raid_type': 'raid_dp',
            'netapp_disk_type': 'SSD',
            'replication_enabled': False,
            'online_extend_support': True,
        }]

        expected[0].update({'QoS_support': cluster_credentials})
        if not cluster_credentials:
            expected[0].update({
                'netapp_aggregate_used_percent': 0,
                'netapp_dedupe_used_percent': 0
            })

        if replication_backends:
            expected[0].update({
                'replication_enabled': True,
                'replication_count': len(replication_backends),
                'replication_targets': replication_backends,
                'replication_type': 'async',
            })

        self.assertEqual(expected, result)
        mock_get_ssc.assert_called_once_with()
        if cluster_credentials:
            mock_get_aggrs.assert_called_once_with()
            mock_get_aggr_capacities.assert_called_once_with(['aggr1'])

    @ddt.data({}, None)
    def test_get_pool_stats_no_ssc_vols(self, ssc):

        mock_get_ssc = self.mock_object(self.library.ssc_library,
                                        'get_ssc',
                                        return_value=ssc)

        pools = self.library._get_pool_stats()

        self.assertListEqual([], pools)
        mock_get_ssc.assert_called_once_with()

    @ddt.data(r'open+|demix+', 'open.+', r'.+\d', '^((?!mix+).)*$',
              'open123, open321')
    def test_get_pool_map_match_selected_pools(self, patterns):

        self.library.configuration.netapp_pool_name_search_pattern = patterns
        mock_list_flexvols = self.mock_object(
            self.zapi_client, 'list_flexvols',
            return_value=fake.FAKE_CMODE_VOLUMES)

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
            return_value=fake.FAKE_CMODE_VOLUMES)

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
            return_value=fake.FAKE_CMODE_VOLUMES)

        result = self.library._get_flexvol_to_pool_map()

        self.assertEqual({}, result)
        mock_list_flexvols.assert_called_once_with()

    def test_update_ssc(self):

        mock_get_pool_map = self.mock_object(
            self.library, '_get_flexvol_to_pool_map',
            return_value=fake.FAKE_CMODE_VOLUMES)

        result = self.library._update_ssc()

        self.assertIsNone(result)
        mock_get_pool_map.assert_called_once_with()
        self.library.ssc_library.update_ssc.assert_called_once_with(
            fake.FAKE_CMODE_VOLUMES)

    def test_delete_volume(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         return_value=fake.QOS_POLICY_GROUP_INFO)
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
                         side_effect=exception.Invalid)
        self.mock_object(self.library, '_mark_qos_policy_group_for_deletion')

        self.library.delete_volume(fake.VOLUME)

        (block_base.NetAppBlockStorageLibrary.delete_volume.
            assert_called_once_with(fake.VOLUME))
        (self.library._mark_qos_policy_group_for_deletion.
            assert_called_once_with(None))

    def test_setup_qos_for_volume(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         return_value=fake.QOS_POLICY_GROUP_INFO)
        self.mock_object(self.zapi_client, 'provision_qos_policy_group')

        result = self.library._setup_qos_for_volume(fake.VOLUME,
                                                    fake.EXTRA_SPECS)

        self.assertEqual(fake.QOS_POLICY_GROUP_INFO, result)
        self.zapi_client.provision_qos_policy_group.\
            assert_called_once_with(fake.QOS_POLICY_GROUP_INFO)

    def test_setup_qos_for_volume_exception_path(self):
        self.mock_object(na_utils, 'get_valid_qos_policy_group_info',
                         side_effect=exception.Invalid)
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
                         return_value=fake.QOS_POLICY_GROUP_INFO)
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
                         side_effect=exception.Invalid)
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
                         return_value=fake.QOS_POLICY_GROUP_NAME)
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

    @ddt.data({'secondary_id': 'dev0', 'configured_targets': ['dev1']},
              {'secondary_id': 'dev3', 'configured_targets': ['dev1', 'dev2']},
              {'secondary_id': 'dev1', 'configured_targets': []},
              {'secondary_id': None, 'configured_targets': []})
    @ddt.unpack
    def test_failover_host_invalid_replication_target(self, secondary_id,
                                                      configured_targets):
        """This tests executes a method in the DataMotionMixin."""
        self.library.backend_name = 'dev0'
        self.mock_object(data_motion.DataMotionMixin,
                         'get_replication_backend_names',
                         return_value=configured_targets)
        complete_failover_call = self.mock_object(
            data_motion.DataMotionMixin, '_complete_failover')

        self.assertRaises(exception.InvalidReplicationTarget,
                          self.library.failover_host, 'fake_context', [],
                          secondary_id=secondary_id)
        self.assertFalse(complete_failover_call.called)

    def test_failover_host_unable_to_failover(self):
        """This tests executes a method in the DataMotionMixin."""
        self.library.backend_name = 'dev0'
        self.mock_object(
            data_motion.DataMotionMixin, '_complete_failover',
            side_effect=exception.NetAppDriverException)
        self.mock_object(data_motion.DataMotionMixin,
                         'get_replication_backend_names',
                         return_value=['dev1', 'dev2'])
        self.mock_object(self.library.ssc_library, 'get_ssc_flexvol_names',
                         return_value=fake_utils.SSC.keys())
        self.mock_object(self.library, '_update_zapi_client')

        self.assertRaises(exception.UnableToFailOver,
                          self.library.failover_host, 'fake_context', [],
                          secondary_id='dev1')
        data_motion.DataMotionMixin._complete_failover.assert_called_once_with(
            'dev0', ['dev1', 'dev2'], fake_utils.SSC.keys(), [],
            failover_target='dev1')
        self.assertFalse(self.library._update_zapi_client.called)

    def test_failover_host(self):
        """This tests executes a method in the DataMotionMixin."""
        self.library.backend_name = 'dev0'
        self.mock_object(data_motion.DataMotionMixin, '_complete_failover',
                         return_value=('dev1', []))
        self.mock_object(data_motion.DataMotionMixin,
                         'get_replication_backend_names',
                         return_value=['dev1', 'dev2'])
        self.mock_object(self.library.ssc_library, 'get_ssc_flexvol_names',
                         return_value=fake_utils.SSC.keys())
        self.mock_object(self.library, '_update_zapi_client')

        actual_active, vol_updates, __ = self.library.failover_host(
            'fake_context', [], secondary_id='dev1', groups=[])

        data_motion.DataMotionMixin._complete_failover.assert_called_once_with(
            'dev0', ['dev1', 'dev2'], fake_utils.SSC.keys(), [],
            failover_target='dev1')
        self.library._update_zapi_client.assert_called_once_with('dev1')
        self.assertTrue(self.library.failed_over)
        self.assertEqual('dev1', self.library.failed_over_backend_name)
        self.assertEqual('dev1', actual_active)
        self.assertEqual([], vol_updates)

    def test_add_looping_tasks(self):
        mock_update_ssc = self.mock_object(self.library, '_update_ssc')
        mock_handle_housekeeping = self.mock_object(
            self.library, '_handle_housekeeping_tasks')
        mock_add_task = self.mock_object(self.library.loopingcalls, 'add_task')
        mock_super_add_looping_tasks = self.mock_object(
            block_base.NetAppBlockStorageLibrary, '_add_looping_tasks')

        self.library._add_looping_tasks()

        mock_update_ssc.assert_called_once_with()
        mock_add_task.assert_has_calls([
            mock.call(mock_update_ssc,
                      loopingcalls.ONE_HOUR,
                      loopingcalls.ONE_HOUR),
            mock.call(mock_handle_housekeeping,
                      loopingcalls.TEN_MINUTES,
                      0)])
        mock_super_add_looping_tasks.assert_called_once_with()

    def test_get_backing_flexvol_names(self):
        mock_ssc_library = self.mock_object(
            self.library.ssc_library, 'get_ssc')

        self.library._get_backing_flexvol_names()

        mock_ssc_library.assert_called_once_with()

    def test_create_group(self):

        model_update = self.library.create_group(
            fake.VOLUME_GROUP)

        self.assertEqual('available', model_update['status'])

    def test_delete_group_volume_delete_failure(self):
        self.mock_object(block_cmode, 'LOG')
        self.mock_object(self.library, '_delete_lun', side_effect=Exception)

        model_update, volumes = self.library.delete_group(
            fake.VOLUME_GROUP, [fake.VG_VOLUME])

        self.assertEqual('deleted', model_update['status'])
        self.assertEqual('error_deleting', volumes[0]['status'])
        self.assertEqual(1, block_cmode.LOG.exception.call_count)

    def test_update_group(self):

        model_update, add_volumes_update, remove_volumes_update = (
            self.library.update_group(fake.VOLUME_GROUP))

        self.assertIsNone(model_update)
        self.assertIsNone(add_volumes_update)
        self.assertIsNone(remove_volumes_update)

    def test_delete_group_not_found(self):
        self.mock_object(block_cmode, 'LOG')
        self.mock_object(self.library, '_get_lun_attr', return_value=None)

        model_update, volumes = self.library.delete_group(
            fake.VOLUME_GROUP, [fake.VG_VOLUME])

        self.assertEqual(0, block_cmode.LOG.error.call_count)
        self.assertEqual(0, block_cmode.LOG.info.call_count)

        self.assertEqual('deleted', model_update['status'])
        self.assertEqual('deleted', volumes[0]['status'])

    def test_create_group_snapshot_raise_exception(self):
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)

        mock_extract_host = self.mock_object(
            volume_utils, 'extract_host', return_value=fake.POOL_NAME)

        self.mock_object(self.zapi_client, 'create_cg_snapshot',
                         side_effect=netapp_api.NaApiError)

        self.assertRaises(exception.NetAppDriverException,
                          self.library.create_group_snapshot,
                          fake.VOLUME_GROUP,
                          [fake.VG_SNAPSHOT])

        mock_extract_host.assert_called_once_with(
            fake.VG_SNAPSHOT['volume']['host'], level='pool')

    def test_create_group_snapshot(self):
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=False)

        fake_lun = block_base.NetAppLun(fake.LUN_HANDLE, fake.LUN_ID,
                                        fake.LUN_SIZE, fake.LUN_METADATA)
        self.mock_object(self.library, '_get_lun_from_table',
                         return_value=fake_lun)
        mock__clone_lun = self.mock_object(self.library, '_clone_lun')

        model_update, snapshots_model_update = (
            self.library.create_group_snapshot(fake.VOLUME_GROUP,
                                               [fake.SNAPSHOT]))

        self.assertIsNone(model_update)
        self.assertIsNone(snapshots_model_update)
        mock__clone_lun.assert_called_once_with(fake_lun.name,
                                                fake.SNAPSHOT['name'],
                                                space_reserved='false',
                                                is_snapshot=True)

    def test_create_consistent_group_snapshot(self):
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)

        self.mock_object(volume_utils, 'extract_host',
                         return_value=fake.POOL_NAME)
        mock_create_cg_snapshot = self.mock_object(
            self.zapi_client, 'create_cg_snapshot')
        mock__clone_lun = self.mock_object(self.library, '_clone_lun')
        mock_wait_for_busy_snapshot = self.mock_object(
            self.zapi_client, 'wait_for_busy_snapshot')
        mock_delete_snapshot = self.mock_object(
            self.zapi_client, 'delete_snapshot')

        model_update, snapshots_model_update = (
            self.library.create_group_snapshot(fake.VOLUME_GROUP,
                                               [fake.VG_SNAPSHOT]))

        self.assertIsNone(model_update)
        self.assertIsNone(snapshots_model_update)

        mock_create_cg_snapshot.assert_called_once_with(
            set([fake.POOL_NAME]), fake.VOLUME_GROUP['id'])
        mock__clone_lun.assert_called_once_with(
            fake.VG_SNAPSHOT['volume']['name'],
            fake.VG_SNAPSHOT['name'],
            source_snapshot=fake.VOLUME_GROUP['id'])
        mock_wait_for_busy_snapshot.assert_called_once_with(
            fake.POOL_NAME, fake.VOLUME_GROUP['id'])
        mock_delete_snapshot.assert_called_once_with(
            fake.POOL_NAME, fake.VOLUME_GROUP['id'])

    @ddt.data(None,
              {'replication_status': fields.ReplicationStatus.ENABLED})
    def test_create_group_from_src_snapshot(self, volume_model_update):
        mock_clone_source_to_destination = self.mock_object(
            self.library, '_clone_source_to_destination',
            return_value=volume_model_update)

        actual_return_value = self.library.create_group_from_src(
            fake.VOLUME_GROUP, [fake.VOLUME], group_snapshot=fake.VG_SNAPSHOT,
            snapshots=[fake.VG_VOLUME_SNAPSHOT])

        clone_source_to_destination_args = {
            'name': fake.VG_SNAPSHOT['name'],
            'size': fake.VG_SNAPSHOT['volume_size'],
        }
        mock_clone_source_to_destination.assert_called_once_with(
            clone_source_to_destination_args, fake.VOLUME)
        if volume_model_update:
            volume_model_update['id'] = fake.VOLUME['id']
        expected_return_value = ((None, [volume_model_update])
                                 if volume_model_update else (None, []))
        self.assertEqual(expected_return_value, actual_return_value)

    @ddt.data(None,
              {'replication_status': fields.ReplicationStatus.ENABLED})
    def test_create_group_from_src_group(self, volume_model_update):
        lun_name = fake.SOURCE_VG_VOLUME['name']
        mock_lun = block_base.NetAppLun(
            lun_name, lun_name, '3', {'UUID': 'fake_uuid'})
        self.mock_object(self.library, '_get_lun_from_table',
                         return_value=mock_lun)
        mock_clone_source_to_destination = self.mock_object(
            self.library, '_clone_source_to_destination',
            return_value=volume_model_update)

        actual_return_value = self.library.create_group_from_src(
            fake.VOLUME_GROUP, [fake.VOLUME],
            source_group=fake.SOURCE_VOLUME_GROUP,
            source_vols=[fake.SOURCE_VG_VOLUME])

        clone_source_to_destination_args = {
            'name': fake.SOURCE_VG_VOLUME['name'],
            'size': fake.SOURCE_VG_VOLUME['size'],
        }
        if volume_model_update:
            volume_model_update['id'] = fake.VOLUME['id']
        expected_return_value = ((None, [volume_model_update])
                                 if volume_model_update else (None, []))
        mock_clone_source_to_destination.assert_called_once_with(
            clone_source_to_destination_args, fake.VOLUME)
        self.assertEqual(expected_return_value, actual_return_value)

    def test_delete_group_snapshot(self):
        mock__delete_lun = self.mock_object(self.library, '_delete_lun')

        model_update, snapshots_model_update = (
            self.library.delete_group_snapshot(fake.VOLUME_GROUP,
                                               [fake.VG_SNAPSHOT]))

        self.assertIsNone(model_update)
        self.assertIsNone(snapshots_model_update)

        mock__delete_lun.assert_called_once_with(fake.VG_SNAPSHOT['name'])
