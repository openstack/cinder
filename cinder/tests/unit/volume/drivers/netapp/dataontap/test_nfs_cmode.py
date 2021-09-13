# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
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
"""Mock unit tests for the NetApp cmode nfs storage driver."""

from unittest import mock
import uuid

import ddt
from os_brick.remotefs import remotefs as remotefs_brick
from oslo_utils.secretutils import md5
from oslo_utils import units

from cinder import exception
from cinder.image import image_utils
from cinder.objects import fields
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as fake
from cinder.tests.unit.volume.drivers.netapp.dataontap.utils import fakes as \
    fake_ssc
from cinder.tests.unit.volume.drivers.netapp import fakes as na_fakes
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap import nfs_base
from cinder.volume.drivers.netapp.dataontap import nfs_cmode
from cinder.volume.drivers.netapp.dataontap.performance import perf_cmode
from cinder.volume.drivers.netapp.dataontap.utils import capabilities
from cinder.volume.drivers.netapp.dataontap.utils import data_motion
from cinder.volume.drivers.netapp.dataontap.utils import loopingcalls
from cinder.volume.drivers.netapp.dataontap.utils import utils as dot_utils
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume.drivers import nfs
from cinder.volume import volume_utils


@ddt.ddt
class NetAppCmodeNfsDriverTestCase(test.TestCase):
    def setUp(self):
        super(NetAppCmodeNfsDriverTestCase, self).setUp()

        kwargs = {
            'configuration': self.get_config_cmode(),
            'host': 'openstack@nfscmode',
        }

        with mock.patch.object(utils, 'get_root_helper',
                               return_value=mock.Mock()):
            with mock.patch.object(remotefs_brick, 'RemoteFsClient',
                                   return_value=mock.Mock()):
                self.driver = nfs_cmode.NetAppCmodeNfsDriver(**kwargs)
                self.driver._mounted_shares = [fake.NFS_SHARE]
                self.driver.ssc_vols = True
                self.driver.vserver = fake.VSERVER_NAME
                self.driver.ssc_enabled = True
                self.driver.perf_library = mock.Mock()
                self.driver.ssc_library = mock.Mock()
                self.driver.zapi_client = mock.Mock()
                self.driver.using_cluster_credentials = True

    def get_config_cmode(self):
        config = na_fakes.create_configuration_cmode()
        config.netapp_storage_protocol = 'nfs'
        config.netapp_login = 'admin'
        config.netapp_password = 'pass'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'http'
        config.netapp_server_port = '80'
        config.netapp_vserver = fake.VSERVER_NAME
        config.netapp_copyoffload_tool_path = 'copyoffload_tool_path'
        config.netapp_api_trace_pattern = 'fake_regex'
        return config

    @ddt.data({'active_backend_id': None, 'targets': ['dev1', 'dev2']},
              {'active_backend_id': None, 'targets': []},
              {'active_backend_id': 'dev1', 'targets': []},
              {'active_backend_id': 'dev1', 'targets': ['dev1', 'dev2']})
    @ddt.unpack
    def test_init_driver_for_replication(self, active_backend_id,
                                         targets):
        kwargs = {
            'configuration': self.get_config_cmode(),
            'host': 'openstack@nfscmode',
            'active_backend_id': active_backend_id,
        }
        self.mock_object(data_motion.DataMotionMixin,
                         'get_replication_backend_names',
                         return_value=targets)
        with mock.patch.object(utils, 'get_root_helper',
                               return_value=mock.Mock()):
            with mock.patch.object(remotefs_brick, 'RemoteFsClient',
                                   return_value=mock.Mock()):
                nfs_driver = nfs_cmode.NetAppCmodeNfsDriver(**kwargs)

                self.assertEqual(active_backend_id,
                                 nfs_driver.failed_over_backend_name)
                self.assertEqual(active_backend_id is not None,
                                 nfs_driver.failed_over)
                self.assertEqual(len(targets) > 0,
                                 nfs_driver.replication_enabled)

    @mock.patch.object(perf_cmode, 'PerformanceCmodeLibrary', mock.Mock())
    @mock.patch.object(client_cmode, 'Client', mock.Mock())
    @mock.patch.object(capabilities.CapabilitiesLibrary,
                       'cluster_user_supported')
    @mock.patch.object(capabilities.CapabilitiesLibrary,
                       'check_api_permissions')
    @mock.patch.object(nfs.NfsDriver, 'do_setup')
    @mock.patch.object(na_utils, 'check_flags')
    def test_do_setup(self, mock_check_flags, mock_super_do_setup,
                      mock_check_api_permissions, mock_cluster_user_supported):
        self.mock_object(
            dot_utils, 'get_backend_configuration',
            return_value=self.get_config_cmode())

        self.driver.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        self.assertTrue(mock_super_do_setup.called)
        mock_check_api_permissions.assert_called_once_with()
        mock_cluster_user_supported.assert_called_once_with()

    def test__update_volume_stats(self):
        mock_debug_log = self.mock_object(nfs_cmode.LOG, 'debug')
        self.mock_object(self.driver, 'get_filter_function')
        self.mock_object(self.driver, 'get_goodness_function')
        self.mock_object(self.driver, '_spawn_clean_cache_job')
        self.driver.zapi_client = mock.Mock()
        self.mock_object(self.driver, '_get_pool_stats', return_value={})
        expected_stats = {
            'driver_version': self.driver.VERSION,
            'pools': {},
            'sparse_copy_volume': True,
            'replication_enabled': False,
            'storage_protocol': 'nfs',
            'vendor_name': 'NetApp',
            'volume_backend_name': 'NetApp_NFS_Cluster_direct',
        }

        retval = self.driver._update_volume_stats()

        self.assertIsNone(retval)
        self.assertTrue(self.driver._spawn_clean_cache_job.called)
        self.assertEqual(1, mock_debug_log.call_count)
        self.assertEqual(expected_stats, self.driver._stats)

    @ddt.data({'replication_backends': [],
               'cluster_credentials': False, 'is_fg': False,
               'report_provisioned_capacity': True},
              {'replication_backends': ['target_1', 'target_2'],
               'cluster_credentials': True, 'is_fg': False,
               'report_provisioned_capacity': False},
              {'replication_backends': ['target_1', 'target_2'],
               'cluster_credentials': True, 'is_fg': True,
               'report_provisioned_capacity': False}
              )
    @ddt.unpack
    def test_get_pool_stats(self, replication_backends, cluster_credentials,
                            is_fg, report_provisioned_capacity):
        self.driver.using_cluster_credentials = cluster_credentials
        conf = self.driver.configuration
        conf.netapp_driver_reports_provisioned_capacity = (
            report_provisioned_capacity)
        self.driver.zapi_client = mock.Mock()
        ssc = {
            'vola': {
                'pool_name': '10.10.10.10:/vola',
                'thick_provisioning_support': True,
                'thin_provisioning_support': False,
                'netapp_thin_provisioned': 'false',
                'netapp_compression': 'false',
                'netapp_mirrored': 'false',
                'netapp_dedup': 'true',
                'netapp_aggregate': ['aggr1'] if is_fg else 'aggr1',
                'netapp_raid_type': ['raid_dp'] if is_fg else 'raid_dp',
                'netapp_disk_type': ['SSD'] if is_fg else 'SSD',
                'consistent_group_snapshot_enabled': True,
                'netapp_is_flexgroup': 'true' if is_fg else 'false',
            },
        }
        mock_get_ssc = self.mock_object(self.driver.ssc_library,
                                        'get_ssc',
                                        return_value=ssc)
        mock_get_aggrs = self.mock_object(self.driver.ssc_library,
                                          'get_ssc_aggregates',
                                          return_value=['aggr1'])

        self.mock_object(self.driver, 'get_replication_backend_names',
                         return_value=replication_backends)

        total_capacity_gb = na_utils.round_down(
            fake.TOTAL_BYTES // units.Gi, '0.01')
        free_capacity_gb = na_utils.round_down(
            fake.AVAILABLE_BYTES // units.Gi, '0.01')
        capacity = {
            'reserved_percentage': fake.RESERVED_PERCENTAGE,
            'max_over_subscription_ratio': fake.MAX_OVER_SUBSCRIPTION_RATIO,
            'total_capacity_gb': total_capacity_gb,
            'free_capacity_gb': free_capacity_gb,
        }
        files_provisioned_cap = [{
            'name': 'volume-ae947c9b-2392-4956-b373-aaac4521f37e',
            'file-size': 5368709120.0  # 5GB
        }, {
            'name': 'snapshot-527eedad-a431-483d-b0ca-18995dd65b66',
            'file-size': 1073741824.0  # 1GB
        }]
        self.mock_object(self.driver,
                         '_get_share_capacity_info',
                         return_value=capacity)
        self.mock_object(self.driver.zapi_client,
                         'get_file_sizes_by_dir',
                         return_value=files_provisioned_cap)
        self.mock_object(self.driver.zapi_client,
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
            self.driver.zapi_client, 'get_aggregate_capacities',
            return_value=aggr_capacities)

        self.driver.perf_library.get_node_utilization_for_pool = (
            mock.Mock(return_value=30.0))

        result = self.driver._get_pool_stats(filter_function='filter',
                                             goodness_function='goodness')

        expected = [{
            'pool_name': '10.10.10.10:/vola',
            'reserved_percentage': fake.RESERVED_PERCENTAGE,
            'max_over_subscription_ratio': fake.MAX_OVER_SUBSCRIPTION_RATIO,
            'multiattach': True,
            'total_capacity_gb': total_capacity_gb,
            'free_capacity_gb': free_capacity_gb,
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
            'consistencygroup_support': True,
            'consistent_group_snapshot_enabled': True,
            'replication_enabled': False,
            'online_extend_support': False,
            'netapp_is_flexgroup': 'false',
        }]
        if report_provisioned_capacity:
            expected[0].update({'provisioned_capacity_gb': 5.0})

        expected[0].update({'QoS_support': cluster_credentials})
        if not cluster_credentials:
            expected[0].update({
                'netapp_aggregate_used_percent': 0,
                'netapp_dedupe_used_percent': 0,
            })

        if replication_backends:
            expected[0].update({
                'replication_enabled': True,
                'replication_count': len(replication_backends),
                'replication_targets': replication_backends,
                'replication_type': 'async',
            })

        if is_fg:
            expected[0].update({
                'netapp_is_flexgroup': 'true',
                'netapp_disk_type': ['SSD'],
                'netapp_raid_type': ['raid_dp'],
                'netapp_aggregate': ['aggr1'],
                'netapp_dedupe_used_percent': 0,
                'consistencygroup_support': False,
                'consistent_group_snapshot_enabled': False,
                'multiattach': False,
            })

        self.assertEqual(expected, result)
        mock_get_ssc.assert_called_once_with()
        if cluster_credentials:
            mock_get_aggrs.assert_called_once_with()
            mock_get_aggr_capacities.assert_called_once_with(['aggr1'])

    @ddt.data({}, None)
    def test_get_pool_stats_no_ssc_vols(self, ssc):

        mock_get_ssc = self.mock_object(self.driver.ssc_library,
                                        'get_ssc',
                                        return_value=ssc)

        pools = self.driver._get_pool_stats()

        self.assertListEqual([], pools)
        mock_get_ssc.assert_called_once_with()

    def test_update_ssc(self):

        mock_ensure_shares_mounted = self.mock_object(
            self.driver, '_ensure_shares_mounted')
        mock_get_pool_map = self.mock_object(
            self.driver, '_get_flexvol_to_pool_map',
            return_value='fake_map')
        mock_update_ssc = self.mock_object(
            self.driver.ssc_library, 'update_ssc')

        result = self.driver._update_ssc()

        self.assertIsNone(result)
        mock_ensure_shares_mounted.assert_called_once_with()
        mock_get_pool_map.assert_called_once_with()
        mock_update_ssc.assert_called_once_with('fake_map')

    def test_get_pool_map(self):

        self.driver.zapi_client = mock.Mock()
        mock_get_operational_lif_addresses = self.mock_object(
            self.driver.zapi_client, 'get_operational_lif_addresses',
            return_value=[fake.SHARE_IP])
        mock_resolve_hostname = self.mock_object(
            volume_utils, 'resolve_hostname', return_value=fake.SHARE_IP)
        mock_get_flexvol = self.mock_object(
            self.driver.zapi_client, 'get_flexvol',
            return_value={'name': fake.NETAPP_VOLUME})

        result = self.driver._get_flexvol_to_pool_map()

        expected = {
            fake.NETAPP_VOLUME: {
                'pool_name': fake.NFS_SHARE,
            },
        }
        self.assertEqual(expected, result)
        mock_get_operational_lif_addresses.assert_called_once_with()
        mock_resolve_hostname.assert_called_once_with(fake.SHARE_IP)
        mock_get_flexvol.assert_called_once_with(flexvol_path=fake.EXPORT_PATH)

    def test_get_pool_map_address_not_found(self):

        self.driver.zapi_client = mock.Mock()
        self.mock_object(self.driver.zapi_client,
                         'get_operational_lif_addresses',
                         return_value=[])
        self.mock_object(volume_utils,
                         'resolve_hostname',
                         return_value=fake.SHARE_IP)

        result = self.driver._get_flexvol_to_pool_map()

        self.assertEqual({}, result)

    def test_get_pool_map_flexvol_not_found(self):

        self.driver.zapi_client = mock.Mock()
        self.mock_object(self.driver.zapi_client,
                         'get_operational_lif_addresses',
                         return_value=[fake.SHARE_IP])
        self.mock_object(volume_utils,
                         'resolve_hostname',
                         return_value=fake.SHARE_IP)
        side_effect = exception.VolumeBackendAPIException(data='fake_data')
        self.mock_object(self.driver.zapi_client,
                         'get_flexvol',
                         side_effect=side_effect)

        result = self.driver._get_flexvol_to_pool_map()

        self.assertEqual({}, result)

    @ddt.data(['/mnt/img-id1', '/mnt/img-id2'], [])
    def test__shortlist_del_eligible_files(self, old_files):
        self.driver.zapi_client = mock.Mock()
        self.driver.zapi_client.get_file_usage = mock.Mock(return_value='1000')
        mock_debug_log = self.mock_object(nfs_cmode.LOG, 'debug')
        self.mock_object(self.driver, '_get_vserver_and_exp_vol',
                         return_value=('openstack', 'fake_share'))
        expected_list = [(o, '1000') for o in old_files]

        observed_list = self.driver._shortlist_del_eligible_files(
            'fake_ip:fake_share', old_files)

        self.assertEqual(expected_list, observed_list)
        self.assertEqual(1, mock_debug_log.call_count)

    @ddt.data({'ip': None, 'shares': None},
              {'ip': 'fake_ip', 'shares': ['fip:/fsh1']})
    @ddt.unpack
    def test__share_match_for_ip_no_match(self, ip, shares):
        def side_effect(arg):
            if arg == 'fake_ip':
                return 'openstack'
            return None

        self.mock_object(self.driver, '_get_vserver_for_ip',
                         side_effect=side_effect)
        mock_debug_log = self.mock_object(nfs_cmode.LOG, 'debug')

        retval = self.driver._share_match_for_ip(ip, shares)

        self.assertIsNone(retval)
        self.assertEqual(1, mock_debug_log.call_count)

    def test__share_match_for_ip(self):
        shares = ['fip:/fsh1']
        self.mock_object(self.driver, '_get_vserver_for_ip',
                         return_value='openstack')
        mock_debug_log = self.mock_object(nfs_cmode.LOG, 'debug')

        retval = self.driver._share_match_for_ip('fip', shares)

        self.assertEqual('fip:/fsh1', retval)
        self.assertEqual(1, mock_debug_log.call_count)

    def test__get_vserver_for_ip_ignores_zapi_exception(self):
        self.driver.zapi_client = mock.Mock()
        self.driver.zapi_client.get_if_info_by_ip = mock.Mock(
            side_effect=exception.NotFound)

        vserver = self.driver._get_vserver_for_ip('FAKE_IP')

        self.assertIsNone(vserver)

    def test__get_vserver_for_ip(self):
        self.driver.zapi_client = mock.Mock()
        self.driver.zapi_client.get_if_info_by_ip = mock.Mock(
            return_value=fake.get_fake_ifs())

        vserver = self.driver._get_vserver_for_ip('FAKE_IP')

        self.assertIsNone(vserver)

    def test_check_for_setup_error(self):
        mock_add_looping_tasks = self.mock_object(
            self.driver, '_add_looping_tasks')
        mock_contains_fg = self.mock_object(
            self.driver.ssc_library, 'contains_flexgroup_pool',
            return_value=False)
        self.driver.zapi_client = mock.Mock(features=mock.Mock(
            FLEXGROUP=True))
        super_check_for_setup_error = self.mock_object(
            nfs_base.NetAppNfsDriver, 'check_for_setup_error')

        self.driver.check_for_setup_error()

        self.assertEqual(1, super_check_for_setup_error.call_count)
        self.assertEqual(1, mock_add_looping_tasks.call_count)
        mock_add_looping_tasks.assert_called_once_with()
        mock_contains_fg.assert_called_once_with()

    def test_check_for_setup_error_fail(self):
        mock_add_looping_tasks = self.mock_object(
            self.driver, '_add_looping_tasks')
        mock_contains_fg = self.mock_object(
            self.driver.ssc_library, 'contains_flexgroup_pool',
            return_value=True)
        self.driver.zapi_client = mock.Mock(features=mock.Mock(
            FLEXGROUP=False))

        self.assertRaises(
            na_utils.NetAppDriverException, self.driver.check_for_setup_error)

        self.assertEqual(1, mock_add_looping_tasks.call_count)
        mock_add_looping_tasks.assert_called_once_with()
        mock_contains_fg.assert_called_once_with()

    @ddt.data({'replication_enabled': True, 'failed_over': False,
               'cluster_credentials': True},
              {'replication_enabled': True, 'failed_over': True,
               'cluster_credentials': True},
              {'replication_enabled': False, 'failed_over': False,
               'cluster_credentials': False})
    @ddt.unpack
    def test_handle_housekeeping_tasks(
            self, replication_enabled, failed_over, cluster_credentials):
        self.driver.using_cluster_credentials = cluster_credentials
        ensure_mirrors = self.mock_object(data_motion.DataMotionMixin,
                                          'ensure_snapmirrors')
        self.mock_object(self.driver.ssc_library, 'get_ssc_flexvol_names',
                         return_value=fake_ssc.SSC.keys())
        mock_remove_unused_qos_policy_groups = self.mock_object(
            self.driver.zapi_client, 'remove_unused_qos_policy_groups')
        self.driver.replication_enabled = replication_enabled
        self.driver.failed_over = failed_over

        self.driver._handle_housekeeping_tasks()

        if self.driver.using_cluster_credentials:
            mock_remove_unused_qos_policy_groups.assert_called_once_with()
        else:
            mock_remove_unused_qos_policy_groups.assert_not_called()

        if replication_enabled and not failed_over:
            ensure_mirrors.assert_called_once_with(
                self.driver.configuration, self.driver.backend_name,
                fake_ssc.SSC.keys())
        else:
            self.assertFalse(ensure_mirrors.called)

    def test_handle_ems_logging(self):

        volume_list = ['vol0', 'vol1', 'vol2']
        self.mock_object(
            self.driver, '_get_backing_flexvol_names',
            return_value=volume_list)
        self.mock_object(
            dot_utils, 'build_ems_log_message_0',
            return_value='fake_base_ems_log_message')
        self.mock_object(
            dot_utils, 'build_ems_log_message_1',
            return_value='fake_pool_ems_log_message')
        mock_send_ems_log_message = self.mock_object(
            self.driver.zapi_client, 'send_ems_log_message')

        self.driver._handle_ems_logging()

        mock_send_ems_log_message.assert_has_calls([
            mock.call('fake_base_ems_log_message'),
            mock.call('fake_pool_ems_log_message'),
        ])
        dot_utils.build_ems_log_message_0.assert_called_once_with(
            self.driver.driver_name, self.driver.app_version)
        dot_utils.build_ems_log_message_1.assert_called_once_with(
            self.driver.driver_name, self.driver.app_version,
            self.driver.vserver, volume_list, [])

    def test_delete_volume(self):
        fake_provider_location = 'fake_provider_location'
        fake_volume = {'provider_location': fake_provider_location}
        self.mock_object(self.driver, '_delete_backing_file_for_volume')
        self.mock_object(na_utils,
                         'get_valid_qos_policy_group_info',
                         return_value=fake.QOS_POLICY_GROUP_INFO)
        self.mock_object(na_utils, 'is_qos_policy_group_spec_adaptive',
                         return_value=False)

        self.driver.delete_volume(fake_volume)

        self.driver._delete_backing_file_for_volume.assert_called_once_with(
            fake_volume)
        na_utils.get_valid_qos_policy_group_info.assert_called_once_with(
            fake_volume)
        na_utils.is_qos_policy_group_spec_adaptive.assert_called_once_with(
            fake.QOS_POLICY_GROUP_INFO)
        (self.driver.zapi_client.mark_qos_policy_group_for_deletion.
         assert_called_once_with(fake.QOS_POLICY_GROUP_INFO, False))

    def test_delete_volume_exception_path(self):
        fake_provider_location = 'fake_provider_location'
        fake_volume = {'provider_location': fake_provider_location}
        self.mock_object(self.driver, '_delete_backing_file_for_volume')
        self.mock_object(na_utils,
                         'get_valid_qos_policy_group_info',
                         return_value=fake.QOS_POLICY_GROUP_INFO)
        self.mock_object(na_utils, 'is_qos_policy_group_spec_adaptive',
                         return_value=False)
        self.mock_object(
            self.driver.zapi_client,
            'mark_qos_policy_group_for_deletion',
            side_effect=na_utils.NetAppDriverException)

        self.driver.delete_volume(fake_volume)

        self.driver._delete_backing_file_for_volume.assert_called_once_with(
            fake_volume)
        na_utils.get_valid_qos_policy_group_info.assert_called_once_with(
            fake_volume)
        na_utils.is_qos_policy_group_spec_adaptive.assert_called_once_with(
            fake.QOS_POLICY_GROUP_INFO)
        (self.driver.zapi_client.mark_qos_policy_group_for_deletion.
         assert_called_once_with(fake.QOS_POLICY_GROUP_INFO, False))

    def test_delete_backing_file_for_volume(self):
        mock_filer_delete = self.mock_object(self.driver, '_delete_file')
        mock_super_delete = self.mock_object(nfs_base.NetAppNfsDriver,
                                             'delete_volume')
        mock_flexgroup = self.mock_object(self.driver, '_is_flexgroup',
                                          return_value=False)
        mock_clone_file = self.mock_object(
            self.driver, '_is_flexgroup_clone_file_supported',
            return_value=True)

        self.driver._delete_backing_file_for_volume(fake.NFS_VOLUME)

        mock_flexgroup.assert_called_once_with(host=fake.NFS_VOLUME['host'])
        mock_clone_file.assert_not_called()
        mock_filer_delete.assert_called_once_with(
            fake.NFS_VOLUME['id'], fake.NFS_VOLUME['name'])
        self.assertEqual(0, mock_super_delete.call_count)

    @ddt.data(True, False)
    def test_delete_backing_file_for_volume_exception_path(self, super_exc):
        mock_flexgroup = self.mock_object(self.driver, '_is_flexgroup',
                                          return_value=False)
        mock_clone_file = self.mock_object(
            self.driver, '_is_flexgroup_clone_file_supported',
            return_value=True)
        mock_exception_log = self.mock_object(nfs_cmode.LOG, 'exception')
        exception_call_count = 2 if super_exc else 1
        mock_filer_delete = self.mock_object(self.driver, '_delete_file')
        mock_filer_delete.side_effect = [Exception]
        mock_super_delete = self.mock_object(nfs_base.NetAppNfsDriver,
                                             'delete_volume')
        if super_exc:
            mock_super_delete.side_effect = [Exception]

        self.driver._delete_backing_file_for_volume(fake.NFS_VOLUME)

        mock_flexgroup.assert_called_once_with(host=fake.NFS_VOLUME['host'])
        mock_clone_file.assert_not_called()
        mock_filer_delete.assert_called_once_with(
            fake.NFS_VOLUME['id'], fake.NFS_VOLUME['name'])
        mock_super_delete.assert_called_once_with(fake.NFS_VOLUME)
        self.assertEqual(exception_call_count, mock_exception_log.call_count)

    @ddt.data(True, False)
    def test_delete_snapshot(self, is_flexgroup):
        mock_delete_backing = self.mock_object(
            self.driver, '_delete_backing_file_for_snapshot')
        self.mock_object(self.driver, '_is_flexgroup',
                         return_value=is_flexgroup)
        self.mock_object(self.driver, '_is_flexgroup_clone_file_supported',
                         return_value=not is_flexgroup)
        mock_super_delete = self.mock_object(nfs_base.NetAppNfsDriver,
                                             'delete_snapshot')
        self.driver.delete_snapshot(fake.test_snapshot)

        if is_flexgroup:
            mock_super_delete.assert_called_once_with(fake.test_snapshot)
            mock_delete_backing.assert_not_called()
        else:
            mock_super_delete.assert_not_called()
            mock_delete_backing.assert_called_once_with(fake.test_snapshot)

    def test_delete_backing_file_for_snapshot(self):
        mock_filer_delete = self.mock_object(self.driver, '_delete_file')
        mock_super_delete = self.mock_object(nfs_base.NetAppNfsDriver,
                                             'delete_snapshot')

        self.driver._delete_backing_file_for_snapshot(fake.test_snapshot)

        mock_filer_delete.assert_called_once_with(
            fake.test_snapshot['volume_id'], fake.test_snapshot['name'])
        self.assertEqual(0, mock_super_delete.call_count)

    @ddt.data(True, False)
    def test_delete_backing_file_for_snapshot_exception_path(self, super_exc):
        mock_exception_log = self.mock_object(nfs_cmode.LOG, 'exception')
        exception_call_count = 2 if super_exc else 1
        mock_filer_delete = self.mock_object(self.driver, '_delete_file')
        mock_filer_delete.side_effect = [Exception]
        mock_super_delete = self.mock_object(nfs_base.NetAppNfsDriver,
                                             'delete_snapshot')
        if super_exc:
            mock_super_delete.side_effect = [Exception]

        self.driver._delete_backing_file_for_snapshot(fake.test_snapshot)

        mock_filer_delete.assert_called_once_with(
            fake.test_snapshot['volume_id'], fake.test_snapshot['name'])
        mock_super_delete.assert_called_once_with(fake.test_snapshot)
        self.assertEqual(exception_call_count, mock_exception_log.call_count)

    def test_delete_file(self):
        mock_get_vs_ip = self.mock_object(self.driver, '_get_export_ip_path')
        mock_get_vs_ip.return_value = (fake.SHARE_IP, fake.EXPORT_PATH)
        mock_get_vserver = self.mock_object(self.driver, '_get_vserver_for_ip')
        mock_get_vserver.return_value = fake.VSERVER_NAME
        mock_zapi_get_vol = self.driver.zapi_client.get_vol_by_junc_vserver
        mock_zapi_get_vol.return_value = fake.FLEXVOL
        mock_zapi_delete = self.driver.zapi_client.delete_file

        self.driver._delete_file(
            fake.test_snapshot['volume_id'], fake.test_snapshot['name'])

        mock_get_vs_ip.assert_called_once_with(
            volume_id=fake.test_snapshot['volume_id'])
        mock_get_vserver.assert_called_once_with(fake.SHARE_IP)
        mock_zapi_get_vol.assert_called_once_with(
            fake.VSERVER_NAME, fake.EXPORT_PATH)
        mock_zapi_delete.assert_called_once_with(
            '/vol/%s/%s' % (fake.FLEXVOL, fake.test_snapshot['name']))

    def test_do_qos_for_volume_no_exception(self):

        mock_get_info = self.mock_object(na_utils,
                                         'get_valid_qos_policy_group_info')
        mock_get_info.return_value = fake.QOS_POLICY_GROUP_INFO
        mock_provision_qos = self.driver.zapi_client.provision_qos_policy_group
        mock_set_policy = self.mock_object(self.driver,
                                           '_set_qos_policy_group_on_volume')
        mock_error_log = self.mock_object(nfs_cmode.LOG, 'error')
        mock_debug_log = self.mock_object(nfs_cmode.LOG, 'debug')
        mock_cleanup = self.mock_object(self.driver,
                                        '_cleanup_volume_on_failure')
        mock_is_qos_min_supported = self.mock_object(self.driver.ssc_library,
                                                     'is_qos_min_supported',
                                                     return_value=True)
        mock_extract_host = self.mock_object(volume_utils, 'extract_host',
                                             return_value=fake.POOL_NAME)

        self.driver._do_qos_for_volume(fake.NFS_VOLUME, fake.EXTRA_SPECS)

        mock_get_info.assert_has_calls([
            mock.call(fake.NFS_VOLUME, fake.EXTRA_SPECS)])
        mock_provision_qos.assert_has_calls([
            mock.call(fake.QOS_POLICY_GROUP_INFO, True)])
        mock_set_policy.assert_has_calls([
            mock.call(fake.NFS_VOLUME, fake.QOS_POLICY_GROUP_INFO, False)])
        mock_is_qos_min_supported.assert_called_once_with(fake.POOL_NAME)
        mock_extract_host.assert_called_once_with(fake.NFS_VOLUME['host'],
                                                  level='pool')
        self.assertEqual(0, mock_error_log.call_count)
        self.assertEqual(0, mock_debug_log.call_count)
        self.assertEqual(0, mock_cleanup.call_count)

    def test_do_qos_for_volume_exception_w_cleanup(self):
        mock_get_info = self.mock_object(na_utils,
                                         'get_valid_qos_policy_group_info')
        mock_get_info.return_value = fake.QOS_POLICY_GROUP_INFO
        mock_provision_qos = self.driver.zapi_client.provision_qos_policy_group
        mock_set_policy = self.mock_object(self.driver,
                                           '_set_qos_policy_group_on_volume')
        mock_set_policy.side_effect = netapp_api.NaApiError
        mock_error_log = self.mock_object(nfs_cmode.LOG, 'error')
        mock_debug_log = self.mock_object(nfs_cmode.LOG, 'debug')
        mock_cleanup = self.mock_object(self.driver,
                                        '_cleanup_volume_on_failure')
        mock_is_qos_min_supported = self.mock_object(self.driver.ssc_library,
                                                     'is_qos_min_supported',
                                                     return_value=True)
        mock_extract_host = self.mock_object(volume_utils, 'extract_host',
                                             return_value=fake.POOL_NAME)

        self.assertRaises(netapp_api.NaApiError,
                          self.driver._do_qos_for_volume,
                          fake.NFS_VOLUME,
                          fake.EXTRA_SPECS)

        mock_get_info.assert_has_calls([
            mock.call(fake.NFS_VOLUME, fake.EXTRA_SPECS)])
        mock_provision_qos.assert_has_calls([
            mock.call(fake.QOS_POLICY_GROUP_INFO, True)])
        mock_set_policy.assert_has_calls([
            mock.call(fake.NFS_VOLUME, fake.QOS_POLICY_GROUP_INFO, False)])
        mock_is_qos_min_supported.assert_called_once_with(fake.POOL_NAME)
        mock_extract_host.assert_called_once_with(fake.NFS_VOLUME['host'],
                                                  level='pool')
        self.assertEqual(1, mock_error_log.call_count)
        self.assertEqual(1, mock_debug_log.call_count)
        mock_cleanup.assert_has_calls([
            mock.call(fake.NFS_VOLUME)])

    def test_do_qos_for_volume_exception_no_cleanup(self):

        mock_get_info = self.mock_object(na_utils,
                                         'get_valid_qos_policy_group_info')
        mock_get_info.side_effect = exception.Invalid
        mock_provision_qos = self.driver.zapi_client.provision_qos_policy_group
        mock_set_policy = self.mock_object(self.driver,
                                           '_set_qos_policy_group_on_volume')
        mock_error_log = self.mock_object(nfs_cmode.LOG, 'error')
        mock_debug_log = self.mock_object(nfs_cmode.LOG, 'debug')
        mock_cleanup = self.mock_object(self.driver,
                                        '_cleanup_volume_on_failure')

        self.assertRaises(exception.Invalid, self.driver._do_qos_for_volume,
                          fake.NFS_VOLUME, fake.EXTRA_SPECS, cleanup=False)

        mock_get_info.assert_has_calls([
            mock.call(fake.NFS_VOLUME, fake.EXTRA_SPECS)])
        self.assertEqual(0, mock_provision_qos.call_count)
        self.assertEqual(0, mock_set_policy.call_count)
        self.assertEqual(1, mock_error_log.call_count)
        self.assertEqual(0, mock_debug_log.call_count)
        self.assertEqual(0, mock_cleanup.call_count)

    def test_set_qos_policy_group_on_volume(self):

        mock_get_name_from_info = self.mock_object(
            na_utils, 'get_qos_policy_group_name_from_info')
        mock_get_name_from_info.return_value = fake.QOS_POLICY_GROUP_NAME

        mock_extract_host = self.mock_object(volume_utils, 'extract_host')
        mock_extract_host.return_value = fake.NFS_SHARE

        mock_get_flex_vol_name =\
            self.driver.zapi_client.get_vol_by_junc_vserver
        mock_get_flex_vol_name.return_value = fake.FLEXVOL

        mock_file_assign_qos = self.driver.zapi_client.file_assign_qos

        self.driver._set_qos_policy_group_on_volume(
            fake.NFS_VOLUME, fake.QOS_POLICY_GROUP_INFO, False)

        mock_get_name_from_info.assert_has_calls([
            mock.call(fake.QOS_POLICY_GROUP_INFO)])
        mock_extract_host.assert_has_calls([
            mock.call(fake.NFS_HOST_STRING, level='pool')])
        mock_get_flex_vol_name.assert_has_calls([
            mock.call(fake.VSERVER_NAME, fake.EXPORT_PATH)])
        mock_file_assign_qos.assert_has_calls([
            mock.call(fake.FLEXVOL, fake.QOS_POLICY_GROUP_NAME,
                      False, fake.NFS_VOLUME['name'])])

    def test_set_qos_policy_group_on_volume_no_info(self):

        mock_get_name_from_info = self.mock_object(
            na_utils, 'get_qos_policy_group_name_from_info')

        mock_extract_host = self.mock_object(volume_utils, 'extract_host')

        mock_get_flex_vol_name =\
            self.driver.zapi_client.get_vol_by_junc_vserver

        mock_file_assign_qos = self.driver.zapi_client.file_assign_qos

        self.driver._set_qos_policy_group_on_volume(fake.NFS_VOLUME,
                                                    None, False)

        self.assertEqual(0, mock_get_name_from_info.call_count)
        self.assertEqual(0, mock_extract_host.call_count)
        self.assertEqual(0, mock_get_flex_vol_name.call_count)
        self.assertEqual(0, mock_file_assign_qos.call_count)

    def test_set_qos_policy_group_on_volume_no_name(self):

        mock_get_name_from_info = self.mock_object(
            na_utils, 'get_qos_policy_group_name_from_info')
        mock_get_name_from_info.return_value = None

        mock_extract_host = self.mock_object(volume_utils, 'extract_host')

        mock_get_flex_vol_name =\
            self.driver.zapi_client.get_vol_by_junc_vserver

        mock_file_assign_qos = self.driver.zapi_client.file_assign_qos

        self.driver._set_qos_policy_group_on_volume(
            fake.NFS_VOLUME, fake.QOS_POLICY_GROUP_INFO, False)

        mock_get_name_from_info.assert_has_calls([
            mock.call(fake.QOS_POLICY_GROUP_INFO)])
        self.assertEqual(0, mock_extract_host.call_count)
        self.assertEqual(0, mock_get_flex_vol_name.call_count)
        self.assertEqual(0, mock_file_assign_qos.call_count)

    @ddt.data({'share': None, 'is_snapshot': False},
              {'share': None, 'is_snapshot': True},
              {'share': 'fake_share', 'is_snapshot': False},
              {'share': 'fake_share', 'is_snapshot': True})
    @ddt.unpack
    def test_clone_backing_file_for_volume(self, share, is_snapshot):

        mock_get_vserver_and_exp_vol = self.mock_object(
            self.driver, '_get_vserver_and_exp_vol',
            return_value=(fake.VSERVER_NAME, fake.FLEXVOL))

        self.driver._clone_backing_file_for_volume(
            fake.FLEXVOL, 'fake_clone', fake.VOLUME_ID, share=share,
            is_snapshot=is_snapshot)

        mock_get_vserver_and_exp_vol.assert_called_once_with(
            fake.VOLUME_ID, share)
        self.driver.zapi_client.clone_file.assert_called_once_with(
            fake.FLEXVOL, fake.FLEXVOL, 'fake_clone', fake.VSERVER_NAME,
            is_snapshot=is_snapshot)

    def test__clone_backing_file_for_volume(self):
        body = fake.get_fake_net_interface_get_iter_response()
        self.driver.zapi_client.get_if_info_by_ip = mock.Mock(
            return_value=[netapp_api.NaElement(body)])
        self.driver.zapi_client.get_vol_by_junc_vserver = mock.Mock(
            return_value='nfsvol')
        self.mock_object(self.driver, '_get_export_ip_path',
                         return_value=('127.0.0.1', 'fakepath'))

        retval = self.driver._clone_backing_file_for_volume(
            'vol', 'clone', 'vol_id', share='share', is_snapshot=True)

        self.assertIsNone(retval)
        self.driver.zapi_client.clone_file.assert_called_once_with(
            'nfsvol', 'vol', 'clone', None, is_snapshot=True)

    def test_copy_from_img_service_copyoffload_nonexistent_binary_path(self):
        self.mock_object(nfs_cmode.LOG, 'debug')
        drv = self.driver
        context = object()
        volume = {'id': 'vol_id', 'name': 'name',
                  'host': 'openstack@nfscmode#192.128.1.1:/mnt_point'}
        image_service = mock.Mock()
        image_service.get_location.return_value = (mock.Mock(), mock.Mock())
        image_service.show.return_value = {'size': 0}
        image_id = 'image_id'
        drv._client = mock.Mock()
        drv._client.get_api_version = mock.Mock(return_value=(1, 20))
        nfs_base.NetAppNfsDriver._find_image_in_cache = mock.Mock(
            return_value=[])
        drv._construct_image_nfs_url = mock.Mock(return_value=["nfs://1"])
        drv._check_get_nfs_path_segs = mock.Mock(
            return_value=("test:test", "dr"))
        drv._get_ip_verify_on_cluster = mock.Mock(return_value="192.128.1.1")
        drv._get_mount_point_for_share = mock.Mock(return_value='mnt_point')
        drv._check_share_can_hold_size = mock.Mock()
        # Raise error as if the copyoffload file can not be found
        drv._clone_file_dst_exists = mock.Mock(side_effect=OSError())
        drv._discover_file_till_timeout = mock.Mock()

        # Verify the original error is propagated
        self.assertRaises(OSError, drv._copy_from_img_service,
                          context, volume, image_service, image_id)

        drv._discover_file_till_timeout.assert_not_called()

    @mock.patch.object(image_utils, 'qemu_img_info')
    def test_copy_from_img_service_raw_copyoffload_workflow_success(
            self, mock_qemu_img_info):
        drv = self.driver
        volume = {'id': 'vol_id', 'name': 'name', 'size': 1,
                  'host': 'openstack@nfscmode#ip1:/mnt_point'}
        image_id = 'image_id'
        context = object()
        image_service = mock.Mock()
        image_service.get_location.return_value = ('nfs://ip1/openstack/img',
                                                   None)
        image_service.show.return_value = {'size': 1, 'disk_format': 'raw'}

        drv._check_get_nfs_path_segs =\
            mock.Mock(return_value=('ip1', '/openstack'))
        drv._get_ip_verify_on_cluster = mock.Mock(return_value='ip1')
        drv._get_host_ip = mock.Mock(return_value='ip2')
        drv._get_export_path = mock.Mock(return_value='/exp_path')
        drv._get_provider_location = mock.Mock(return_value='share')
        drv._execute = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(return_value='mnt_point')
        drv._discover_file_till_timeout = mock.Mock(return_value=True)
        img_inf = mock.Mock()
        img_inf.file_format = 'raw'
        mock_qemu_img_info.return_value = img_inf
        drv._check_share_can_hold_size = mock.Mock()
        drv._move_nfs_file = mock.Mock(return_value=True)
        drv._delete_file_at_path = mock.Mock()
        drv._clone_file_dst_exists = mock.Mock()
        drv._post_clone_image = mock.Mock()

        retval = drv._copy_from_img_service(
            context, volume, image_service, image_id)

        self.assertTrue(retval)
        drv._get_ip_verify_on_cluster.assert_any_call('ip1')
        drv._check_share_can_hold_size.assert_called_with(
            'ip1:/mnt_point', 1)
        self.assertEqual(1, drv._execute.call_count)

    @mock.patch.object(image_utils, 'convert_image')
    @mock.patch.object(image_utils, 'qemu_img_info')
    @mock.patch('os.path.exists')
    @mock.patch('cinder.privsep.path')
    def test_copy_from_img_service_qcow2_copyoffload_workflow_success(
            self, mock_touch, mock_exists, mock_qemu_img_info,
            mock_cvrt_image):
        drv = self.driver
        cinder_mount_point_base = '/opt/stack/data/cinder/mnt/'
        # To get the cinder mount point directory, we use:
        mount_dir = md5(
            '203.0.113.122:/cinder-flexvol1'.encode('utf-8'),
            usedforsecurity=False).hexdigest()
        cinder_mount_point = cinder_mount_point_base + mount_dir
        destination_copied_file = (
            '/cinder-flexvol1/a155308c-0290-497b-b278-4cdd01de0253'
        )
        volume = {'id': 'vol_id', 'name': 'name', 'size': 1,
                  'host': 'openstack@nfscmode#203.0.113.122:/cinder-flexvol1'}
        image_id = 'image_id'
        context = object()
        image_service = mock.Mock()
        image_service.get_location.return_value = (
            'nfs://203.0.113.122/glance-flexvol1', None)
        image_service.show.return_value = {'size': 1,
                                           'disk_format': 'qcow2'}
        drv._check_get_nfs_path_segs = (
            mock.Mock(return_value=('203.0.113.122', '/openstack'))
        )

        drv._get_ip_verify_on_cluster = mock.Mock(return_value='203.0.113.122')
        drv._execute = mock.Mock()
        drv._execute_as_root = False
        drv._get_mount_point_for_share = mock.Mock(
            return_value=cinder_mount_point)
        img_inf = mock.Mock()
        img_inf.file_format = 'raw'
        mock_qemu_img_info.return_value = img_inf
        drv._check_share_can_hold_size = mock.Mock()

        drv._move_nfs_file = mock.Mock(return_value=True)
        drv._delete_file_at_path = mock.Mock()
        drv._clone_file_dst_exists = mock.Mock()
        drv._post_clone_image = mock.Mock()
        self.mock_object(uuid, 'uuid4', mock.Mock(
            return_value='a155308c-0290-497b-b278-4cdd01de0253'))

        retval = drv._copy_from_img_service(
            context, volume, image_service, image_id)

        self.assertTrue(retval)
        drv._get_ip_verify_on_cluster.assert_any_call('203.0.113.122')
        drv._check_share_can_hold_size.assert_called_with(
            '203.0.113.122:/cinder-flexvol1', 1)

        # _execute must be called once for copy-offload and again to touch
        # the top directory to refresh cache
        drv._execute.assert_has_calls(
            [
                mock.call(
                    'copyoffload_tool_path', '203.0.113.122',
                    '203.0.113.122', '/openstack/glance-flexvol1',
                    destination_copied_file, run_as_root=False,
                    check_exit_code=0
                )
            ]
        )
        self.assertEqual(1, drv._execute.call_count)
        self.assertEqual(2, drv._delete_file_at_path.call_count)
        self.assertEqual(1, drv._clone_file_dst_exists.call_count)

    def test_copy_from_cache_copyoffload_success(self):
        drv = self.driver
        volume = {'id': 'vol_id', 'name': 'name', 'size': 1,
                  'host': 'openstack@nfscmode#192.128.1.1:/exp_path'}
        image_id = 'image_id'
        cache_result = [('ip1:/openstack', 'img-cache-imgid')]
        drv._get_ip_verify_on_cluster = mock.Mock(return_value='ip1')
        drv._execute = mock.Mock()
        drv._register_image_in_cache = mock.Mock()
        drv._post_clone_image = mock.Mock()

        copied = drv._copy_from_cache(volume, image_id, cache_result)

        self.assertTrue(copied)
        drv._get_ip_verify_on_cluster.assert_any_call('ip1')
        drv._execute.assert_called_once_with(
            'copyoffload_tool_path', 'ip1', 'ip1',
            '/openstack/img-cache-imgid', '/exp_path/name',
            run_as_root=False, check_exit_code=0)

    def test_unmanage(self):
        mock_get_info = self.mock_object(na_utils,
                                         'get_valid_qos_policy_group_info')
        mock_get_info.return_value = fake.QOS_POLICY_GROUP_INFO

        mock_mark_for_deletion =\
            self.driver.zapi_client.mark_qos_policy_group_for_deletion

        super_unmanage = self.mock_object(nfs_base.NetAppNfsDriver, 'unmanage')

        self.driver.unmanage(fake.NFS_VOLUME)

        mock_get_info.assert_has_calls([mock.call(fake.NFS_VOLUME)])
        mock_mark_for_deletion.assert_has_calls([
            mock.call(fake.QOS_POLICY_GROUP_INFO)])
        super_unmanage.assert_has_calls([mock.call(fake.NFS_VOLUME)])

    def test_unmanage_invalid_qos(self):
        mock_get_info = self.mock_object(na_utils,
                                         'get_valid_qos_policy_group_info')
        mock_get_info.side_effect = exception.Invalid

        super_unmanage = self.mock_object(nfs_base.NetAppNfsDriver, 'unmanage')

        self.driver.unmanage(fake.NFS_VOLUME)

        mock_get_info.assert_has_calls([mock.call(fake.NFS_VOLUME)])
        super_unmanage.assert_has_calls([mock.call(fake.NFS_VOLUME)])

    def test_add_looping_tasks(self):
        mock_update_ssc = self.mock_object(self.driver, '_update_ssc')
        mock_handle_housekeeping = self.mock_object(
            self.driver, '_handle_housekeeping_tasks')
        mock_add_task = self.mock_object(self.driver.loopingcalls, 'add_task')
        mock_super_add_looping_tasks = self.mock_object(
            nfs_base.NetAppNfsDriver, '_add_looping_tasks')

        self.driver._add_looping_tasks()

        mock_update_ssc.assert_called_once_with()
        mock_add_task.assert_has_calls([
            mock.call(mock_update_ssc,
                      loopingcalls.ONE_HOUR,
                      loopingcalls.ONE_HOUR),
            mock.call(mock_handle_housekeeping,
                      loopingcalls.TEN_MINUTES,
                      0)])
        mock_super_add_looping_tasks.assert_called_once_with()

    @ddt.data({'type_match': True, 'expected': True},
              {'type_match': False, 'expected': False})
    @ddt.unpack
    def test_is_share_clone_compatible(self, type_match, expected):

        mock_get_flexvol_name_for_share = self.mock_object(
            self.driver, '_get_flexvol_name_for_share',
            return_value='fake_flexvol')
        mock_is_share_vol_type_match = self.mock_object(
            self.driver, '_is_share_vol_type_match', return_value=type_match)

        result = self.driver._is_share_clone_compatible(fake.VOLUME,
                                                        fake.NFS_SHARE)

        self.assertEqual(expected, result)
        mock_get_flexvol_name_for_share.assert_called_once_with(fake.NFS_SHARE)
        mock_is_share_vol_type_match.assert_called_once()

    @ddt.data({'flexvols': ['volume1', 'volume2'], 'expected': True},
              {'flexvols': ['volume3', 'volume4'], 'expected': False},
              {'flexvols': [], 'expected': False})
    @ddt.unpack
    def test_is_share_vol_type_match(self, flexvols, expected):

        mock_get_volume_extra_specs = self.mock_object(
            na_utils, 'get_volume_extra_specs',
            return_value='fake_extra_specs')
        mock_get_matching_flexvols_for_extra_specs = self.mock_object(
            self.driver.ssc_library, 'get_matching_flexvols_for_extra_specs',
            return_value=flexvols)

        result = self.driver._is_share_vol_type_match(fake.VOLUME,
                                                      fake.NFS_SHARE,
                                                      'volume1')

        self.assertEqual(expected, result)
        mock_get_volume_extra_specs.assert_called_once_with(fake.VOLUME)
        mock_get_matching_flexvols_for_extra_specs.assert_called_once_with(
            'fake_extra_specs')

    @ddt.data({'share': 'volume1', 'expected': 'volume1'},
              {'share': 'volume3', 'expected': None})
    @ddt.unpack
    def test_get_flexvol_name_for_share(self, share, expected):

        mock_get_ssc = self.mock_object(
            self.driver.ssc_library, 'get_ssc', return_value=fake_ssc.SSC)

        result = self.driver._get_flexvol_name_for_share(share)

        self.assertEqual(expected, result)
        mock_get_ssc.assert_called_once_with()

    def test_get_flexvol_name_for_share_no_ssc_vols(self):

        mock_get_ssc = self.mock_object(
            self.driver.ssc_library, 'get_ssc', return_value={})

        result = self.driver._get_flexvol_name_for_share('fake_share')

        self.assertIsNone(result)
        mock_get_ssc.assert_called_once_with()

    def test_find_image_location_with_local_copy(self):
        local_share = '/share'
        cache_result = [
            ('ip1:/openstack', 'img-cache-imgid'),
            ('ip2:/openstack', 'img-cache-imgid'),
            (local_share, 'img-cache-imgid'),
            ('ip3:/openstack', 'img-cache-imgid'),
        ]

        mock_extract_host = self.mock_object(volume_utils, 'extract_host')
        mock_extract_host.return_value = local_share

        cache_copy, found_local_copy = self.driver._find_image_location(
            cache_result, fake.VOLUME)

        self.assertEqual(cache_result[2], cache_copy)
        self.assertTrue(found_local_copy)

    def test_find_image_location_with_remote_copy(self):
        cache_result = [('ip1:/openstack', 'img-cache-imgid')]

        mock_extract_host = self.mock_object(volume_utils, 'extract_host')
        mock_extract_host.return_value = '/share'

        cache_copy, found_local_copy = self.driver._find_image_location(
            cache_result, fake.VOLUME)

        self.assertEqual(cache_result[0], cache_copy)
        self.assertFalse(found_local_copy)

    def test_find_image_location_without_cache_copy(self):
        cache_result = []
        mock_extract_host = self.mock_object(volume_utils, 'extract_host')
        mock_extract_host.return_value = '/share'

        cache_copy, found_local_copy = self.driver._find_image_location(
            cache_result, fake.VOLUME)

        self.assertIsNone(cache_copy)
        self.assertFalse(found_local_copy)

    def test_clone_file_dest_exists(self):
        self.driver._get_vserver_and_exp_vol = mock.Mock(
            return_value=(fake.VSERVER_NAME, fake.EXPORT_PATH))
        self.driver.zapi_client.clone_file = mock.Mock()

        self.driver._clone_file_dst_exists(
            fake.NFS_SHARE, fake.IMAGE_FILE_ID, fake.VOLUME['name'],
            dest_exists=True)

        self.driver._get_vserver_and_exp_vol.assert_called_once_with(
            share=fake.NFS_SHARE)
        self.driver.zapi_client.clone_file.assert_called_once_with(
            fake.EXPORT_PATH, fake.IMAGE_FILE_ID, fake.VOLUME['name'],
            fake.VSERVER_NAME, dest_exists=True)

    @ddt.data((fake.NFS_SHARE, fake.SHARE_IP),
              (fake.NFS_SHARE_IPV6, fake.IPV6_ADDRESS))
    @ddt.unpack
    def test_get_source_ip_and_path(self, share, ip):
        self.driver._get_ip_verify_on_cluster = mock.Mock(
            return_value=ip)

        src_ip, src_path = self.driver._get_source_ip_and_path(
            share, fake.IMAGE_FILE_ID)

        self.assertEqual(ip, src_ip)
        assert_path = fake.EXPORT_PATH + '/' + fake.IMAGE_FILE_ID
        self.assertEqual(assert_path, src_path)
        self.driver._get_ip_verify_on_cluster.assert_called_once_with(ip)

    def test_get_destination_ip_and_path(self):
        self.driver._get_ip_verify_on_cluster = mock.Mock(
            return_value=fake.SHARE_IP)
        mock_extract_host = self.mock_object(volume_utils, 'extract_host')
        mock_extract_host.return_value = fake.NFS_SHARE

        dest_ip, dest_path = self.driver._get_destination_ip_and_path(
            fake.VOLUME)

        self.assertEqual(fake.SHARE_IP, dest_ip)
        assert_path = fake.EXPORT_PATH + '/' + fake.LUN_NAME
        self.assertEqual(assert_path, dest_path)
        self.driver._get_ip_verify_on_cluster.assert_called_once_with(
            fake.SHARE_IP)

    def test_clone_image_copyoffload_from_cache_success(self):
        drv = self.driver
        context = object()
        volume = {'id': 'vol_id', 'name': 'name',
                  'host': 'openstack@nfscmode#192.128.1.1:/mnt_point'}
        image_service = object()
        image_location = 'img-loc'
        image_id = 'image_id'
        image_meta = {'id': image_id}
        drv.zapi_client = mock.Mock()
        drv.zapi_client.get_ontapi_version = mock.Mock(return_value=(1, 20))
        nfs_base.NetAppNfsDriver._find_image_in_cache = mock.Mock(
            return_value=[('share', 'img')])
        nfs_base.NetAppNfsDriver._direct_nfs_clone = mock.Mock(
            return_value=False)
        drv._copy_from_cache = mock.Mock(return_value=True)
        drv._is_flexgroup = mock.Mock(return_value=False)
        drv._is_flexgroup_clone_file_supported = mock.Mock(return_value=True)

        drv.clone_image(context, volume, image_location, image_meta,
                        image_service)

        drv._copy_from_cache.assert_called_once_with(
            volume, image_id, [('share', 'img')])

        drv.clone_image(context, volume, image_location, image_meta,
                        image_service)

    def test_clone_image_flexgroup(self):
        self.driver._is_flexgroup = mock.Mock(return_value=True)
        mock_clone_file = self.mock_object(
            self.driver, '_is_flexgroup_clone_file_supported',
            return_value=False)
        volume = {'host': 'openstack@nfscmode#192.128.1.1:/mnt_point'}
        context = object()
        model, cloned = self.driver.clone_image(
            context, volume, 'fake_loc', 'fake_img', 'fake_img_service')

        self.assertFalse(cloned)
        self.assertIsNone(model)
        self.driver._is_flexgroup.assert_called_once_with(host=volume['host'])
        mock_clone_file.assert_called_once_with()

    def test_clone_image_copyoffload_from_img_service(self):
        drv = self.driver
        context = object()
        volume = {'id': 'vol_id', 'name': 'name',
                  'host': 'openstack@nfscmode#192.128.1.1:/mnt_point',
                  'provider_location': '192.128.1.1:/mnt_point'}
        image_service = object()
        image_id = 'image_id'
        image_meta = {'id': image_id}
        image_location = 'img-loc'
        drv.zapi_client = mock.Mock()
        drv.zapi_client.get_ontapi_version = mock.Mock(return_value=(1, 20))
        nfs_base.NetAppNfsDriver._find_image_in_cache = mock.Mock(
            return_value=[])
        nfs_base.NetAppNfsDriver._direct_nfs_clone = mock.Mock(
            return_value=False)
        nfs_base.NetAppNfsDriver._post_clone_image = mock.Mock(
            return_value=True)
        drv._copy_from_img_service = mock.Mock(return_value=True)
        drv._is_flexgroup = mock.Mock(return_value=False)
        drv._is_flexgroup_clone_file_supported = mock.Mock(return_value=True)

        retval = drv.clone_image(
            context, volume, image_location, image_meta, image_service)

        self.assertEqual(retval, (
            {'provider_location': '192.128.1.1:/mnt_point',
             'bootable': True}, True))
        drv._copy_from_img_service.assert_called_once_with(
            context, volume, image_service, image_id)

    def test_clone_image_copyoffload_failure(self):
        mock_log = self.mock_object(nfs_cmode, 'LOG')
        drv = self.driver
        context = object()
        volume = {'id': 'vol_id', 'name': 'name', 'host': 'host'}
        image_service = object()
        image_id = 'image_id'
        image_meta = {'id': image_id}
        image_location = 'img-loc'
        drv.zapi_client = mock.Mock()
        drv.zapi_client.get_ontapi_version = mock.Mock(return_value=(1, 20))
        nfs_base.NetAppNfsDriver._find_image_in_cache = mock.Mock(
            return_value=[])
        nfs_base.NetAppNfsDriver._direct_nfs_clone = mock.Mock(
            return_value=False)
        drv._copy_from_img_service = mock.Mock(side_effect=Exception())
        drv._is_flexgroup = mock.Mock(return_value=False)
        drv._is_flexgroup_clone_file_supported = mock.Mock(return_value=True)

        retval = drv.clone_image(
            context, volume, image_location, image_meta, image_service)

        self.assertEqual(retval, ({'bootable': False,
                                   'provider_location': None}, False))
        drv._copy_from_img_service.assert_called_once_with(
            context, volume, image_service, image_id)
        mock_log.info.assert_not_called()

    def test_copy_from_remote_cache(self):
        source_ip = '192.0.1.1'
        source_path = '/openstack/img-cache-imgid'
        cache_copy = ('192.0.1.1:/openstack', fake.IMAGE_FILE_ID)
        dest_path = fake.EXPORT_PATH + '/' + fake.VOLUME['name']
        self.driver._execute = mock.Mock()
        self.driver._get_source_ip_and_path = mock.Mock(
            return_value=(source_ip, source_path))
        self.driver._get_destination_ip_and_path = mock.Mock(
            return_value=(fake.SHARE_IP, dest_path))
        self.driver._register_image_in_cache = mock.Mock()

        self.driver._copy_from_remote_cache(
            fake.VOLUME, fake.IMAGE_FILE_ID, cache_copy)

        self.driver._execute.assert_called_once_with(
            'copyoffload_tool_path', source_ip, fake.SHARE_IP,
            source_path, dest_path, run_as_root=False, check_exit_code=0)
        self.driver._get_source_ip_and_path.assert_called_once_with(
            cache_copy[0], fake.IMAGE_FILE_ID)
        self.driver._get_destination_ip_and_path.assert_called_once_with(
            fake.VOLUME)
        self.driver._register_image_in_cache.assert_called_once_with(
            fake.VOLUME, fake.IMAGE_FILE_ID)

    def test_copy_from_cache_workflow_remote_location(self):
        cache_result = [('ip1:/openstack', fake.IMAGE_FILE_ID),
                        ('ip2:/openstack', fake.IMAGE_FILE_ID),
                        ('ip3:/openstack', fake.IMAGE_FILE_ID)]
        self.driver._find_image_location = mock.Mock(return_value=[
            cache_result[0], False])
        self.driver._copy_from_remote_cache = mock.Mock()
        self.driver._post_clone_image = mock.Mock()

        copied = self.driver._copy_from_cache(
            fake.VOLUME, fake.IMAGE_FILE_ID, cache_result)

        self.assertTrue(copied)
        self.driver._copy_from_remote_cache.assert_called_once_with(
            fake.VOLUME, fake.IMAGE_FILE_ID, cache_result[0])

    def test_copy_from_cache_workflow_remote_location_no_copyoffload(self):
        cache_result = [('ip1:/openstack', fake.IMAGE_FILE_ID),
                        ('ip2:/openstack', fake.IMAGE_FILE_ID),
                        ('ip3:/openstack', fake.IMAGE_FILE_ID)]
        self.driver._find_image_location = mock.Mock(return_value=[
            cache_result[0], False])
        self.driver._copy_from_remote_cache = mock.Mock()
        self.driver._post_clone_image = mock.Mock()
        self.driver.configuration.netapp_copyoffload_tool_path = None

        copied = self.driver._copy_from_cache(
            fake.VOLUME, fake.IMAGE_FILE_ID, cache_result)

        self.assertFalse(copied)
        self.driver._copy_from_remote_cache.assert_not_called()

    def test_copy_from_cache_workflow_local_location(self):
        local_share = '/share'
        cache_result = [
            ('ip1:/openstack', 'img-cache-imgid'),
            ('ip2:/openstack', 'img-cache-imgid'),
            (local_share, 'img-cache-imgid'),
            ('ip3:/openstack', 'img-cache-imgid'),
        ]
        self.driver._find_image_location = mock.Mock(return_value=[
            cache_result[2], True])
        self.driver._clone_file_dst_exists = mock.Mock()
        self.driver._post_clone_image = mock.Mock()

        copied = self.driver._copy_from_cache(
            fake.VOLUME, fake.IMAGE_FILE_ID, cache_result)

        self.assertTrue(copied)
        self.driver._clone_file_dst_exists.assert_called_once_with(
            local_share, fake.IMAGE_FILE_ID, fake.VOLUME['name'],
            dest_exists=True)

    def test_copy_from_cache_workflow_no_location(self):
        cache_result = []
        self.driver._find_image_location = mock.Mock(
            return_value=(None, False))

        copied = self.driver._copy_from_cache(
            fake.VOLUME, fake.IMAGE_FILE_ID, cache_result)

        self.assertFalse(copied)

    def test_copy_from_cache_workflow_exception(self):
        cache_result = [('ip1:/openstack', fake.IMAGE_FILE_ID)]
        self.driver._find_image_location = mock.Mock(return_value=[
            cache_result[0], False])
        self.driver._copy_from_remote_cache = mock.Mock(
            side_effect=Exception)
        self.driver._post_clone_image = mock.Mock()

        copied = self.driver._copy_from_cache(
            fake.VOLUME, fake.IMAGE_FILE_ID, cache_result)

        self.assertFalse(copied)
        self.driver._copy_from_remote_cache.assert_called_once_with(
            fake.VOLUME, fake.IMAGE_FILE_ID, cache_result[0])
        self.assertFalse(self.driver._post_clone_image.called)

    @ddt.data({'secondary_id': 'dev0', 'configured_targets': ['dev1']},
              {'secondary_id': 'dev3', 'configured_targets': ['dev1', 'dev2']},
              {'secondary_id': 'dev1', 'configured_targets': []},
              {'secondary_id': None, 'configured_targets': []})
    @ddt.unpack
    def test_failover_host_invalid_replication_target(self, secondary_id,
                                                      configured_targets):
        """This tests executes a method in the DataMotionMixin."""
        self.driver.backend_name = 'dev0'
        self.mock_object(data_motion.DataMotionMixin,
                         'get_replication_backend_names',
                         return_value=configured_targets)
        complete_failover_call = self.mock_object(
            data_motion.DataMotionMixin, '_complete_failover')

        self.assertRaises(exception.InvalidReplicationTarget,
                          self.driver.failover_host, 'fake_context', [],
                          secondary_id=secondary_id)
        self.assertFalse(complete_failover_call.called)

    def test_failover_host_unable_to_failover(self):
        """This tests executes a method in the DataMotionMixin."""
        self.driver.backend_name = 'dev0'
        self.mock_object(data_motion.DataMotionMixin, '_complete_failover',
                         side_effect=na_utils.NetAppDriverException)
        self.mock_object(data_motion.DataMotionMixin,
                         'get_replication_backend_names',
                         return_value=['dev1', 'dev2'])
        self.mock_object(self.driver.ssc_library, 'get_ssc_flexvol_names',
                         return_value=fake_ssc.SSC.keys())
        self.mock_object(self.driver, '_update_zapi_client')

        self.assertRaises(exception.UnableToFailOver,
                          self.driver.failover_host, 'fake_context', [],
                          secondary_id='dev1')
        data_motion.DataMotionMixin._complete_failover.assert_called_once_with(
            'dev0', ['dev1', 'dev2'], fake_ssc.SSC.keys(), [],
            failover_target='dev1')
        self.assertFalse(self.driver._update_zapi_client.called)

    def test_failover_host(self):
        """This tests executes a method in the DataMotionMixin."""
        self.driver.backend_name = 'dev0'
        self.mock_object(data_motion.DataMotionMixin, '_complete_failover',
                         return_value=('dev1', []))
        self.mock_object(data_motion.DataMotionMixin,
                         'get_replication_backend_names',
                         return_value=['dev1', 'dev2'])
        self.mock_object(self.driver.ssc_library, 'get_ssc_flexvol_names',
                         return_value=fake_ssc.SSC.keys())
        self.mock_object(self.driver, '_update_zapi_client')

        actual_active, vol_updates, __ = self.driver.failover_host(
            'fake_context', [], secondary_id='dev1', groups=[])

        data_motion.DataMotionMixin._complete_failover.assert_called_once_with(
            'dev0', ['dev1', 'dev2'], fake_ssc.SSC.keys(), [],
            failover_target='dev1')
        self.driver._update_zapi_client.assert_called_once_with('dev1')
        self.assertTrue(self.driver.failed_over)
        self.assertEqual('dev1', self.driver.failed_over_backend_name)
        self.assertEqual('dev1', actual_active)
        self.assertEqual([], vol_updates)

    def test_delete_group_snapshot(self):
        mock_delete_backing_file = self.mock_object(
            self.driver, '_delete_backing_file_for_snapshot')
        snapshots = [fake.VG_SNAPSHOT]

        model_update, snapshots_model_update = (
            self.driver.delete_group_snapshot(
                fake.VG_CONTEXT, fake.VG_SNAPSHOT, snapshots))

        mock_delete_backing_file.assert_called_once_with(fake.VG_SNAPSHOT)
        self.assertIsNone(model_update)
        self.assertIsNone(snapshots_model_update)

    def test_get_snapshot_backing_flexvol_names(self):
        snapshots = [
            {'volume': {'host': 'hostA@192.168.99.25#/fake/volume1'}},
            {'volume': {'host': 'hostA@192.168.1.01#/fake/volume2'}},
            {'volume': {'host': 'hostA@192.168.99.25#/fake/volume3'}},
            {'volume': {'host': 'hostA@192.168.99.25#/fake/volume1'}},
        ]

        ssc = {
            'volume1': {'pool_name': '/fake/volume1', },
            'volume2': {'pool_name': '/fake/volume2', },
            'volume3': {'pool_name': '/fake/volume3', },
        }

        mock_get_ssc = self.mock_object(self.driver.ssc_library, 'get_ssc')
        mock_get_ssc.return_value = ssc

        hosts = [snap['volume']['host'] for snap in snapshots]
        flexvols = self.driver._get_flexvol_names_from_hosts(hosts)

        mock_get_ssc.assert_called_once_with()
        self.assertEqual(3, len(flexvols))
        self.assertIn('volume1', flexvols)
        self.assertIn('volume2', flexvols)
        self.assertIn('volume3', flexvols)

    def test_get_backing_flexvol_names(self):
        mock_ssc_library = self.mock_object(
            self.driver.ssc_library, 'get_ssc')

        self.driver._get_backing_flexvol_names()

        mock_ssc_library.assert_called_once_with()

    def test_create_group(self):
        mock_flexgroup = self.mock_object(self.driver, '_is_flexgroup',
                                          return_value=False)
        self.mock_object(volume_utils,
                         'is_group_a_cg_snapshot_type',
                         return_value=False)

        model_update = self.driver.create_group(
            fake.VG_CONTEXT, fake.VOLUME_GROUP)

        self.assertEqual('available', model_update['status'])
        mock_flexgroup.assert_called_once_with(host=fake.VOLUME_GROUP['host'])

    def test_create_group_raises(self):
        mock_flexgroup = self.mock_object(self.driver, '_is_flexgroup',
                                          return_value=True)
        mock_is_cg = self.mock_object(volume_utils,
                                      'is_group_a_cg_snapshot_type',
                                      return_value=True)

        self.assertRaises(
            na_utils.NetAppDriverException,
            self.driver.create_group,
            fake.VG_CONTEXT, fake.VOLUME_GROUP)

        mock_flexgroup.assert_called_once_with(host=fake.VOLUME_GROUP['host'])
        mock_is_cg.assert_called_once_with(fake.VOLUME_GROUP)

    def test_update_group(self):
        mock_is_cg = self.mock_object(
            volume_utils, 'is_group_a_cg_snapshot_type',
            return_value=False)
        model_update, add_volumes_update, remove_volumes_update = (
            self.driver.update_group(fake.VG_CONTEXT, "foo"))

        self.assertIsNone(add_volumes_update)
        self.assertIsNone(remove_volumes_update)
        mock_is_cg.assert_called_once_with("foo")

    def test_update_group_raises(self):
        mock_is_cg = self.mock_object(
            volume_utils, 'is_group_a_cg_snapshot_type',
            return_value=True)
        mock_is_flexgroup = self.mock_object(
            self.driver, '_is_flexgroup',
            return_value=True)

        self.assertRaises(
            na_utils.NetAppDriverException,
            self.driver.update_group,
            fake.VG_CONTEXT,
            "foo",
            add_volumes=[fake.VOLUME])
        mock_is_cg.assert_called_once_with("foo")
        mock_is_flexgroup.assert_called_once_with(host=fake.VOLUME['host'])

    @ddt.data(None,
              {'replication_status': fields.ReplicationStatus.ENABLED})
    def test_create_group_from_src(self, volume_model_update):
        volume_model_update = volume_model_update or {}
        volume_model_update.update(
            {'provider_location': fake.PROVIDER_LOCATION})
        mock_create_volume_from_snapshot = self.mock_object(
            self.driver, 'create_volume_from_snapshot',
            return_value=volume_model_update)

        model_update, volumes_model_update = (
            self.driver.create_group_from_src(
                fake.VG_CONTEXT, fake.VOLUME_GROUP, [fake.VOLUME],
                group_snapshot=fake.VG_SNAPSHOT,
                sorted_snapshots=[fake.SNAPSHOT]))

        expected_volumes_model_updates = [{'id': fake.VOLUME['id']}]
        expected_volumes_model_updates[0].update(volume_model_update)
        mock_create_volume_from_snapshot.assert_called_once_with(
            fake.VOLUME, fake.SNAPSHOT)
        self.assertIsNone(model_update)
        self.assertEqual(expected_volumes_model_updates, volumes_model_update)

    @ddt.data(None,
              {'replication_status': fields.ReplicationStatus.ENABLED})
    def test_create_group_from_src_source_vols(self, volume_model_update):
        self.driver.zapi_client = mock.Mock()
        mock_get_snapshot_flexvols = self.mock_object(
            self.driver, '_get_flexvol_names_from_hosts')
        mock_get_snapshot_flexvols.return_value = (set([fake.VG_POOL_NAME]))
        mock_clone_backing_file = self.mock_object(
            self.driver, '_clone_backing_file_for_volume')
        fake_snapshot_name = 'snapshot-temp-' + fake.VOLUME_GROUP['id']
        mock_busy = self.mock_object(
            self.driver.zapi_client, 'wait_for_busy_snapshot')
        self.mock_object(self.driver, '_get_volume_model_update',
                         return_value=volume_model_update)
        mock_is_flexgroup = self.mock_object(self.driver, '_is_flexgroup',
                                             return_value=False)

        model_update, volumes_model_update = (
            self.driver.create_group_from_src(
                fake.VG_CONTEXT, fake.VOLUME_GROUP, [fake.VG_VOLUME],
                source_group=fake.VOLUME_GROUP,
                sorted_source_vols=[fake.SOURCE_VG_VOLUME]))

        expected_volumes_model_updates = [{
            'id': fake.VG_VOLUME['id'],
            'provider_location': fake.PROVIDER_LOCATION,
        }]
        if volume_model_update:
            expected_volumes_model_updates[0].update(volume_model_update)

        mock_is_flexgroup.assert_called_once_with(
            host=fake.SOURCE_VG_VOLUME['host'])
        mock_get_snapshot_flexvols.assert_called_once_with(
            [fake.SOURCE_VG_VOLUME['host']])
        self.driver.zapi_client.create_cg_snapshot.assert_called_once_with(
            set([fake.VG_POOL_NAME]), fake_snapshot_name)
        mock_clone_backing_file.assert_called_once_with(
            fake.SOURCE_VG_VOLUME['name'], fake.VG_VOLUME['name'],
            fake.SOURCE_VG_VOLUME['id'], source_snapshot=fake_snapshot_name)
        mock_busy.assert_called_once_with(
            fake.VG_POOL_NAME, fake_snapshot_name)
        self.driver.zapi_client.delete_snapshot.assert_called_once_with(
            fake.VG_POOL_NAME, fake_snapshot_name)
        self.assertIsNone(model_update)
        self.assertEqual(expected_volumes_model_updates, volumes_model_update)

    @ddt.data(
        {'error': na_utils.NetAppDriverException, 'is_cg': True},
        {'error': NotImplementedError, 'is_cg': False})
    @ddt.unpack
    def test_create_group_from_src_raises(self, error, is_cg):
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=is_cg)
        mock_is_flexgroup = self.mock_object(self.driver, '_is_flexgroup',
                                             return_value=True)

        self.assertRaises(
            error, self.driver.create_group_from_src,
            fake.VG_CONTEXT, fake.VOLUME_GROUP, [fake.VG_VOLUME],
            source_group=fake.VOLUME_GROUP,
            sorted_source_vols=[fake.SOURCE_VG_VOLUME])

        mock_is_flexgroup.assert_called_once_with(
            host=fake.SOURCE_VG_VOLUME['host'])

    def test_create_group_from_src_invalid_parms(self):
        model_update, volumes_model_update = (
            self.driver.create_group_from_src(
                fake.VG_CONTEXT, fake.VOLUME_GROUP, [fake.VOLUME]))

        self.assertIn('error', model_update['status'])

    def test_create_group_snapshot_raise_exception(self):
        mock_is_cg_snapshot = self.mock_object(
            volume_utils, 'is_group_a_cg_snapshot_type', return_value=True)
        mock__get_flexvol_names = self.mock_object(
            self.driver, '_get_flexvol_names_from_hosts')
        self.mock_object(self.driver, '_is_flexgroup', return_value=False)

        self.mock_object(self.driver.zapi_client, 'create_cg_snapshot',
                         side_effect=netapp_api.NaApiError)
        self.assertRaises(na_utils.NetAppDriverException,
                          self.driver.create_group_snapshot,
                          fake.VG_CONTEXT,
                          fake.VOLUME_GROUP,
                          [fake.VG_SNAPSHOT])

        mock_is_cg_snapshot.assert_called_once_with(fake.VOLUME_GROUP)
        mock__get_flexvol_names.assert_called_once_with(
            [fake.VG_SNAPSHOT['volume']['host']])

    def test_create_group_snapshot(self):
        mock_is_cg_snapshot = self.mock_object(
            volume_utils, 'is_group_a_cg_snapshot_type', return_value=False)
        mock_create_snapshot = self.mock_object(
            self.driver, 'create_snapshot')

        model_update, snapshots_model_update = (
            self.driver.create_group_snapshot(fake.VG_CONTEXT,
                                              fake.VOLUME_GROUP,
                                              [fake.SNAPSHOT]))

        self.assertIsNone(model_update)
        self.assertIsNone(snapshots_model_update)
        mock_is_cg_snapshot.assert_called_once_with(fake.VOLUME_GROUP)
        mock_create_snapshot.assert_called_once_with(fake.SNAPSHOT)

    def test_create_consistent_group_snapshot(self):
        mock_is_cg_snapshot = self.mock_object(
            volume_utils, 'is_group_a_cg_snapshot_type', return_value=True)

        self.driver.zapi_client = mock.Mock()
        mock_get_snapshot_flexvols = self.mock_object(
            self.driver, '_get_flexvol_names_from_hosts')
        mock_get_snapshot_flexvols.return_value = (set([fake.VG_POOL_NAME]))
        mock_clone_backing_file = self.mock_object(
            self.driver, '_clone_backing_file_for_volume')
        mock_busy = self.mock_object(
            self.driver.zapi_client, 'wait_for_busy_snapshot')
        mock_is_flexgroup = self.mock_object(
            self.driver, '_is_flexgroup')
        mock_is_flexgroup.return_value = False

        model_update, snapshots_model_update = (
            self.driver.create_group_snapshot(fake.VG_CONTEXT,
                                              fake.VOLUME_GROUP,
                                              [fake.VG_SNAPSHOT]))

        self.assertIsNone(model_update)
        self.assertIsNone(snapshots_model_update)
        mock_is_flexgroup.assert_called_once_with(
            host=fake.VG_SNAPSHOT['volume']['host'])
        mock_is_cg_snapshot.assert_called_once_with(fake.VOLUME_GROUP)
        mock_get_snapshot_flexvols.assert_called_once_with(
            [fake.VG_SNAPSHOT['volume']['host']])
        self.driver.zapi_client.create_cg_snapshot.assert_called_once_with(
            set([fake.VG_POOL_NAME]), fake.VOLUME_GROUP_ID)
        mock_clone_backing_file.assert_called_once_with(
            fake.VG_SNAPSHOT['volume']['name'], fake.VG_SNAPSHOT['name'],
            fake.VG_SNAPSHOT['volume']['id'],
            source_snapshot=fake.VOLUME_GROUP_ID)
        mock_busy.assert_called_once_with(
            fake.VG_POOL_NAME, fake.VOLUME_GROUP_ID)
        self.driver.zapi_client.delete_snapshot.assert_called_once_with(
            fake.VG_POOL_NAME, fake.VOLUME_GROUP_ID)

    def test_create_consistent_group_snapshot_flexgroup(self):
        mock_is_cg_snapshot = self.mock_object(
            volume_utils, 'is_group_a_cg_snapshot_type', return_value=True)
        mock_is_flexgroup = self.mock_object(
            self.driver, '_is_flexgroup')
        mock_is_flexgroup.return_value = True

        self.assertRaises(na_utils.NetAppDriverException,
                          self.driver.create_group_snapshot,
                          fake.VG_CONTEXT,
                          fake.VOLUME_GROUP,
                          [fake.VG_SNAPSHOT])

        mock_is_cg_snapshot.assert_called_once_with(fake.VOLUME_GROUP)
        mock_is_flexgroup.assert_called_once_with(
            host=fake.VG_SNAPSHOT['volume']['host'])

    def test_create_group_snapshot_busy_snapshot(self):
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)
        mock_is_flexgroup = self.mock_object(
            self.driver, '_is_flexgroup')
        mock_is_flexgroup.return_value = False
        self.driver.zapi_client = mock.Mock()
        snapshot = fake.VG_SNAPSHOT
        snapshot['volume'] = fake.VG_VOLUME
        mock_get_snapshot_flexvols = self.mock_object(
            self.driver, '_get_flexvol_names_from_hosts')
        mock_get_snapshot_flexvols.return_value = (set([fake.VG_POOL_NAME]))
        mock_clone_backing_file = self.mock_object(
            self.driver, '_clone_backing_file_for_volume')
        mock_busy = self.mock_object(
            self.driver.zapi_client, 'wait_for_busy_snapshot')
        mock_busy.side_effect = exception.SnapshotIsBusy(snapshot['name'])
        mock_mark_snapshot_for_deletion = self.mock_object(
            self.driver.zapi_client, 'mark_snapshot_for_deletion')

        self.driver.create_group_snapshot(
            fake.VG_CONTEXT, fake.VG_SNAPSHOT, [snapshot])

        mock_get_snapshot_flexvols.assert_called_once_with(
            [snapshot['volume']['host']])
        mock_is_flexgroup.assert_called_once_with(
            host=snapshot['volume']['host'])
        self.driver.zapi_client.create_cg_snapshot.assert_called_once_with(
            set([fake.VG_POOL_NAME]), fake.VG_SNAPSHOT_ID)
        mock_clone_backing_file.assert_called_once_with(
            snapshot['volume']['name'], snapshot['name'],
            snapshot['volume']['id'], source_snapshot=fake.VG_SNAPSHOT_ID)
        mock_busy.assert_called_once_with(
            fake.VG_POOL_NAME, fake.VG_SNAPSHOT_ID)
        self.driver.zapi_client.delete_snapshot.assert_not_called()
        mock_mark_snapshot_for_deletion.assert_called_once_with(
            fake.VG_POOL_NAME, fake.VG_SNAPSHOT_ID)

    def test_delete_group_volume_delete_failure(self):
        self.mock_object(self.driver, 'delete_volume', side_effect=Exception)

        model_update, volumes = self.driver.delete_group(
            fake.VG_CONTEXT, fake.VOLUME_GROUP, [fake.VG_VOLUME])

        self.assertEqual('deleted', model_update['status'])
        self.assertEqual('error_deleting', volumes[0]['status'])

    def test_delete_group(self):
        mock_delete_file = self.mock_object(
            self.driver, 'delete_volume')

        model_update, volumes = self.driver.delete_group(
            fake.VG_CONTEXT, fake.VOLUME_GROUP, [fake.VG_VOLUME])

        self.assertEqual('deleted', model_update['status'])
        self.assertEqual('deleted', volumes[0]['status'])
        mock_delete_file.assert_called_once_with(fake.VG_VOLUME)

    def test__is_flexgroup_clone_file_supported(self):
        self.driver.zapi_client = mock.Mock(features=mock.Mock(
            FLEXGROUP_CLONE_FILE=True))

        is_fg_clone = self.driver._is_flexgroup_clone_file_supported()

        self.assertTrue(is_fg_clone)

    def test_copy_file(self):
        self.driver.configuration.netapp_migrate_volume_timeout = 1
        fake_job_status = {'job-status': 'complete'}
        mock_start_file_copy = self.mock_object(self.driver.zapi_client,
                                                'start_file_copy',
                                                return_value=fake.JOB_UUID)
        mock_get_file_copy_status = self.mock_object(
            self.driver.zapi_client, 'get_file_copy_status',
            return_value=fake_job_status)
        mock_cancel_file_copy = self.mock_object(
            self.driver, '_cancel_file_copy')
        ctxt = mock.Mock()
        vol_fields = {
            'id': fake.VOLUME_ID,
            'name': fake.VOLUME_NAME,
            'status': fields.VolumeStatus.AVAILABLE
        }
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)

        result = self.driver._copy_file(
            fake_vol, fake.POOL_NAME, fake.VSERVER_NAME, fake.DEST_POOL_NAME,
            fake.DEST_VSERVER_NAME, dest_file_name=fake.VOLUME_NAME,
            dest_backend_name=fake.DEST_BACKEND_NAME, cancel_on_error=True)

        mock_start_file_copy.assert_called_with(
            fake_vol.name, fake.DEST_POOL_NAME,
            src_ontap_volume=fake.POOL_NAME,
            dest_file_name=fake.VOLUME_NAME)
        mock_get_file_copy_status.assert_called_with(fake.JOB_UUID)
        mock_cancel_file_copy.assert_not_called()
        self.assertIsNone(result)

    @ddt.data(('data', na_utils.NetAppDriverTimeout),
              ('destroyed', na_utils.NetAppDriverException),
              ('destroyed', na_utils.NetAppDriverException))
    @ddt.unpack
    def test_copy_file_error(self, status_on_error, copy_exception):
        self.driver.configuration.netapp_migrate_volume_timeout = 1
        fake_job_status = {
            'job-status': status_on_error,
            'last-failure-reason': None
        }
        mock_start_file_copy = self.mock_object(self.driver.zapi_client,
                                                'start_file_copy',
                                                return_value=fake.JOB_UUID)
        mock_get_file_copy_status = self.mock_object(
            self.driver.zapi_client, 'get_file_copy_status',
            return_value=fake_job_status)
        mock_cancel_file_copy = self.mock_object(
            self.driver, '_cancel_file_copy')
        ctxt = mock.Mock()
        vol_fields = {
            'id': fake.VOLUME_ID,
            'name': fake.VOLUME_NAME,
            'status': fields.VolumeStatus.AVAILABLE
        }
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)

        self.assertRaises(copy_exception,
                          self.driver._copy_file,
                          fake_vol, fake.POOL_NAME, fake.VSERVER_NAME,
                          fake.DEST_POOL_NAME, fake.DEST_VSERVER_NAME,
                          dest_file_name=fake.VOLUME_NAME,
                          dest_backend_name=fake.DEST_BACKEND_NAME,
                          cancel_on_error=True)

        mock_start_file_copy.assert_called_with(
            fake_vol.name, fake.DEST_POOL_NAME,
            src_ontap_volume=fake.POOL_NAME,
            dest_file_name=fake.VOLUME_NAME)
        mock_get_file_copy_status.assert_called_with(fake.JOB_UUID)
        mock_cancel_file_copy.assert_called_once_with(
            fake.JOB_UUID, fake_vol, fake.DEST_POOL_NAME,
            dest_backend_name=fake.DEST_BACKEND_NAME)

    def test_migrate_volume_to_vserver(self):
        self.driver.backend_name = fake.BACKEND_NAME
        mock_copy_file = self.mock_object(self.driver, '_copy_file')
        mock_create_vserver_peer = self.mock_object(self.driver,
                                                    'create_vserver_peer')
        mock_finish_volume_migration = self.mock_object(
            self.driver, '_finish_volume_migration', return_value={})
        ctxt = mock.Mock()
        vol_fields = {'id': fake.VOLUME_ID, 'name': fake.VOLUME_NAME}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)

        updates = self.driver._migrate_volume_to_vserver(
            fake_vol, fake.NFS_SHARE, fake.VSERVER_NAME, fake.DEST_NFS_SHARE,
            fake.DEST_VSERVER_NAME, fake.DEST_BACKEND_NAME)

        mock_copy_file.assert_called_once_with(
            fake_vol, fake.EXPORT_PATH[1:], fake.VSERVER_NAME,
            fake.DEST_EXPORT_PATH[1:], fake.DEST_VSERVER_NAME,
            dest_backend_name=fake.DEST_BACKEND_NAME,
            cancel_on_error=True)
        mock_create_vserver_peer.assert_called_once_with(
            fake.VSERVER_NAME, fake.BACKEND_NAME, fake.DEST_VSERVER_NAME,
            ['file_copy'])
        mock_finish_volume_migration.assert_called_once_with(
            fake_vol, fake.DEST_NFS_SHARE)
        self.assertEqual({}, updates)

    def test_migrate_volume_create_vserver_peer_error(self):
        self.driver.backend_name = fake.BACKEND_NAME
        mock_copy_file = self.mock_object(
            self.driver, '_copy_file',
            side_effect=na_utils.NetAppDriverException)
        mock_create_vserver_peer = self.mock_object(
            self.driver, 'create_vserver_peer',
            side_effect=na_utils.NetAppDriverException)
        mock_finish_volume_migration = self.mock_object(
            self.driver, '_finish_volume_migration')
        ctxt = mock.Mock()
        vol_fields = {'id': fake.VOLUME_ID, 'name': fake.VOLUME_NAME}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)

        self.assertRaises(
            na_utils.NetAppDriverException,
            self.driver._migrate_volume_to_vserver,
            fake_vol,
            fake.NFS_SHARE,
            fake.VSERVER_NAME,
            fake.DEST_NFS_SHARE,
            fake.DEST_VSERVER_NAME,
            fake.DEST_BACKEND_NAME)
        mock_create_vserver_peer.assert_called_once_with(
            fake.VSERVER_NAME, fake.BACKEND_NAME, fake.DEST_VSERVER_NAME,
            ['file_copy'])
        mock_copy_file.assert_not_called()
        mock_finish_volume_migration.assert_not_called()

    def test_migrate_volume_to_vserver_file_copy_error(self):
        self.driver.backend_name = fake.BACKEND_NAME
        mock_create_vserver_peer = self.mock_object(
            self.driver, 'create_vserver_peer')
        mock_copy_file = self.mock_object(
            self.driver, '_copy_file',
            side_effect=na_utils.NetAppDriverException)
        mock_finish_volume_migration = self.mock_object(
            self.driver, '_finish_volume_migration')
        ctxt = mock.Mock()
        vol_fields = {'id': fake.VOLUME_ID, 'name': fake.VOLUME_NAME}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)

        self.assertRaises(
            na_utils.NetAppDriverException,
            self.driver._migrate_volume_to_vserver,
            fake_vol,
            fake.NFS_SHARE,
            fake.VSERVER_NAME,
            fake.DEST_NFS_SHARE,
            fake.DEST_VSERVER_NAME,
            fake.DEST_BACKEND_NAME)

        mock_create_vserver_peer.assert_called_once_with(
            fake.VSERVER_NAME, fake.BACKEND_NAME, fake.DEST_VSERVER_NAME,
            ['file_copy'])
        mock_copy_file.assert_called_once_with(
            fake_vol, fake.EXPORT_PATH[1:], fake.VSERVER_NAME,
            fake.DEST_EXPORT_PATH[1:], fake.DEST_VSERVER_NAME,
            dest_backend_name=fake.DEST_BACKEND_NAME,
            cancel_on_error=True)
        mock_finish_volume_migration.assert_not_called()

    def test_migrate_volume_to_vserver_file_copy_timeout(self):
        self.driver.backend_name = fake.BACKEND_NAME
        mock_create_vserver_peer = self.mock_object(
            self.driver, 'create_vserver_peer')
        mock_copy_file = self.mock_object(
            self.driver, '_copy_file',
            side_effect=na_utils.NetAppDriverTimeout)
        mock_finish_volume_migration = self.mock_object(
            self.driver, '_finish_volume_migration')
        ctxt = mock.Mock()
        vol_fields = {'id': fake.VOLUME_ID, 'name': fake.VOLUME_NAME}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)

        self.assertRaises(
            na_utils.NetAppDriverTimeout,
            self.driver._migrate_volume_to_vserver,
            fake_vol,
            fake.NFS_SHARE,
            fake.VSERVER_NAME,
            fake.DEST_NFS_SHARE,
            fake.DEST_VSERVER_NAME,
            fake.DEST_BACKEND_NAME)

        mock_create_vserver_peer.assert_called_once_with(
            fake.VSERVER_NAME, fake.BACKEND_NAME, fake.DEST_VSERVER_NAME,
            ['file_copy'])
        mock_copy_file.assert_called_once_with(
            fake_vol, fake.EXPORT_PATH[1:], fake.VSERVER_NAME,
            fake.DEST_EXPORT_PATH[1:], fake.DEST_VSERVER_NAME,
            dest_backend_name=fake.DEST_BACKEND_NAME,
            cancel_on_error=True)
        mock_finish_volume_migration.assert_not_called()

    def test_migrate_volume_to_pool(self):
        mock_copy_file = self.mock_object(self.driver, '_copy_file')
        mock_finish_volume_migration = self.mock_object(
            self.driver, '_finish_volume_migration', return_value={})
        ctxt = mock.Mock()
        vol_fields = {'id': fake.VOLUME_ID, 'name': fake.VOLUME_NAME}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)

        updates = self.driver._migrate_volume_to_pool(fake_vol,
                                                      fake.NFS_SHARE,
                                                      fake.DEST_NFS_SHARE,
                                                      fake.VSERVER_NAME,
                                                      fake.DEST_BACKEND_NAME)

        mock_copy_file.assert_called_once_with(
            fake_vol, fake.EXPORT_PATH[1:], fake.VSERVER_NAME,
            fake.DEST_EXPORT_PATH[1:], fake.VSERVER_NAME,
            dest_backend_name=fake.DEST_BACKEND_NAME,
            cancel_on_error=True)
        mock_finish_volume_migration.assert_called_once_with(
            fake_vol, fake.DEST_NFS_SHARE)
        self.assertEqual({}, updates)

    def test_migrate_volume_to_pool_file_copy_error(self):
        mock_copy_file = self.mock_object(
            self.driver, '_copy_file',
            side_effect=na_utils.NetAppDriverException)
        mock_finish_volume_migration = self.mock_object(
            self.driver, '_finish_volume_migration')
        ctxt = mock.Mock()
        vol_fields = {'id': fake.VOLUME_ID, 'name': fake.VOLUME_NAME}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)

        self.assertRaises(
            na_utils.NetAppDriverException,
            self.driver._migrate_volume_to_pool,
            fake_vol,
            fake.NFS_SHARE,
            fake.DEST_NFS_SHARE,
            fake.VSERVER_NAME,
            fake.DEST_BACKEND_NAME)

        mock_copy_file.assert_called_once_with(
            fake_vol, fake.EXPORT_PATH[1:], fake.VSERVER_NAME,
            fake.DEST_EXPORT_PATH[1:], fake.VSERVER_NAME,
            dest_backend_name=fake.DEST_BACKEND_NAME,
            cancel_on_error=True)
        mock_finish_volume_migration.assert_not_called()

    def test_migrate_volume_to_pool_file_copy_timeout(self):
        mock_copy_file = self.mock_object(
            self.driver, '_copy_file',
            side_effect=na_utils.NetAppDriverTimeout)
        mock_finish_volume_migration = self.mock_object(
            self.driver, '_finish_volume_migration')
        ctxt = mock.Mock()
        vol_fields = {'id': fake.VOLUME_ID, 'name': fake.VOLUME_NAME}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)

        self.assertRaises(
            na_utils.NetAppDriverTimeout,
            self.driver._migrate_volume_to_pool,
            fake_vol,
            fake.NFS_SHARE,
            fake.DEST_NFS_SHARE,
            fake.VSERVER_NAME,
            fake.DEST_BACKEND_NAME)

        mock_copy_file.assert_called_once_with(
            fake_vol, fake.EXPORT_PATH[1:], fake.VSERVER_NAME,
            fake.DEST_EXPORT_PATH[1:], fake.VSERVER_NAME,
            dest_backend_name=fake.DEST_BACKEND_NAME,
            cancel_on_error=True)
        mock_finish_volume_migration.assert_not_called()

    def test_finish_volume_migration(self):
        mock_delete_volume = self.mock_object(self.driver, 'delete_volume')
        ctxt = mock.Mock()
        vol_fields = {'id': fake.VOLUME_ID,
                      'host': 'fakeHost@%s#%s' % (fake.BACKEND_NAME,
                                                  fake.POOL_NAME)}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)

        result = self.driver._finish_volume_migration(fake_vol,
                                                      fake.DEST_POOL_NAME)

        mock_delete_volume.assert_called_once_with(fake_vol)
        expected = {'provider_location': fake.DEST_POOL_NAME}
        self.assertEqual(expected, result)

    def test_migrate_volume(self):
        ctx = mock.Mock()
        self.driver.backend_name = fake.BACKEND_NAME
        self.driver.netapp_vserver = fake.VSERVER_NAME
        mock_migrate_volume_ontap_assisted = self.mock_object(
            self.driver, 'migrate_volume_ontap_assisted', return_value={})
        vol_fields = {
            'id': fake.VOLUME_ID,
            'name': fake.VOLUME_NAME,
            'status': fields.VolumeStatus.AVAILABLE
        }
        fake_vol = fake_volume.fake_volume_obj(ctx, **vol_fields)

        result = self.driver.migrate_volume(ctx, fake_vol,
                                            fake.DEST_HOST_STRING)

        mock_migrate_volume_ontap_assisted.assert_called_once_with(
            fake_vol, fake.DEST_HOST_STRING, fake.BACKEND_NAME,
            fake.VSERVER_NAME)
        self.assertEqual({}, result)

    def test_migrate_volume_not_in_available_status(self):
        ctx = mock.Mock()
        self.driver.backend_name = fake.BACKEND_NAME
        self.driver.netapp_vserver = fake.VSERVER_NAME
        mock_migrate_volume_ontap_assisted = self.mock_object(
            self.driver, 'migrate_volume_ontap_assisted', return_value={})
        vol_fields = {
            'id': fake.VOLUME_ID,
            'name': fake.VOLUME_NAME,
            'status': fields.VolumeStatus.IN_USE
        }
        fake_vol = fake_volume.fake_volume_obj(ctx, **vol_fields)

        migrated, updates = self.driver.migrate_volume(ctx,
                                                       fake_vol,
                                                       fake.DEST_HOST_STRING)

        mock_migrate_volume_ontap_assisted.assert_not_called()
        self.assertFalse(migrated)
        self.assertEqual({}, updates)

    def test__revert_to_snapshot(self):
        mock_clone_backing_file_for_volume = self.mock_object(
            self.driver, '_clone_backing_file_for_volume')
        mock_get_export_ip_path = self.mock_object(
            self.driver, '_get_export_ip_path',
            return_value=(fake.SHARE_IP, fake.EXPORT_PATH))
        mock_get_vserver_for_ip = self.mock_object(
            self.driver, '_get_vserver_for_ip', return_value=fake.VSERVER_NAME)
        mock_get_vol_by_junc_vserver = self.mock_object(
            self.driver.zapi_client, 'get_vol_by_junc_vserver',
            return_value=fake.FLEXVOL)
        mock_swap_files = self.mock_object(self.driver, '_swap_files')
        mock_delete_file = self.mock_object(self.driver.zapi_client,
                                            'delete_file')

        self.driver._revert_to_snapshot(fake.SNAPSHOT_VOLUME, fake.SNAPSHOT)

        mock_clone_backing_file_for_volume.assert_called_once_with(
            fake.SNAPSHOT['name'],
            'new-%s' % fake.SNAPSHOT['name'],
            fake.SNAPSHOT_VOLUME['id'],
            is_snapshot=False)
        mock_get_export_ip_path.assert_called_once_with(
            volume_id=fake.SNAPSHOT_VOLUME['id'])
        mock_get_vserver_for_ip.assert_called_once_with(fake.SHARE_IP)
        mock_get_vol_by_junc_vserver.assert_called_once_with(
            fake.VSERVER_NAME, fake.EXPORT_PATH)
        mock_swap_files.assert_called_once_with(
            fake.FLEXVOL, fake.SNAPSHOT_VOLUME['name'],
            'new-%s' % fake.SNAPSHOT['name'])
        mock_delete_file.assert_not_called()

    @ddt.data(False, True)
    def test__revert_to_snapshot_swap_exception(self, delete_exception):
        new_snap_name = 'new-%s' % fake.SNAPSHOT['name']
        new_file_path = '/vol/%s/%s' % (fake.FLEXVOL, new_snap_name)

        self.mock_object(self.driver, '_clone_backing_file_for_volume')
        self.mock_object(self.driver, '_get_export_ip_path',
                         return_value=(fake.SHARE_IP, fake.EXPORT_PATH))
        self.mock_object(self.driver, '_get_vserver_for_ip',
                         return_value=fake.VSERVER_NAME)
        self.mock_object(self.driver.zapi_client, 'get_vol_by_junc_vserver',
                         return_value=fake.FLEXVOL)
        swap_exception = exception.VolumeBackendAPIException(data="data")
        self.mock_object(self.driver, '_swap_files',
                         side_effect=swap_exception)
        side_effect = Exception if delete_exception else lambda: True
        mock_delete_file = self.mock_object(self.driver.zapi_client,
                                            'delete_file',
                                            side_effect=side_effect)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._revert_to_snapshot,
                          fake.SNAPSHOT_VOLUME, fake.SNAPSHOT)

        mock_delete_file.assert_called_once_with(new_file_path)

    def test__swap_files(self):
        new_file = 'new-%s' % fake.SNAPSHOT['name']
        new_file_path = '/vol/%s/%s' % (fake.FLEXVOL, new_file)
        original_file_path = '/vol/%s/%s' % (fake.FLEXVOL, fake.VOLUME_NAME)
        tmp_file_path = '/vol/%s/tmp-%s' % (fake.FLEXVOL, fake.VOLUME_NAME)

        mock_rename_file = self.mock_object(
            self.driver.zapi_client, 'rename_file')
        mock_delete_file = self.mock_object(
            self.driver.zapi_client, 'delete_file')

        self.driver._swap_files(fake.FLEXVOL, fake.VOLUME_NAME, new_file)

        mock_rename_file.assert_has_calls([
            mock.call(original_file_path, tmp_file_path),
            mock.call(new_file_path, original_file_path)])

        mock_delete_file.assert_called_once_with(tmp_file_path)

    @ddt.data((True, False), (False, False), (False, True))
    @ddt.unpack
    def test__swap_files_rename_exception(self, first_exception,
                                          rollback_exception):
        new_file = 'new-%s' % fake.SNAPSHOT['name']
        new_file_path = '/vol/%s/%s' % (fake.FLEXVOL, new_file)
        original_file_path = '/vol/%s/%s' % (fake.FLEXVOL, fake.VOLUME_NAME)
        tmp_file_path = '/vol/%s/tmp-%s' % (fake.FLEXVOL, fake.VOLUME_NAME)
        side_effect = None

        def _skip_side_effect():
            return True

        if not first_exception and not rollback_exception:
            side_effect = [_skip_side_effect,
                           exception.VolumeBackendAPIException(data="data"),
                           _skip_side_effect]
        elif not first_exception and rollback_exception:
            side_effect = [_skip_side_effect,
                           exception.VolumeBackendAPIException(data="data"),
                           exception.VolumeBackendAPIException(data="data")]
        else:
            side_effect = exception.VolumeBackendAPIException(data="data")

        mock_rename_file = self.mock_object(self.driver.zapi_client,
                                            'rename_file',
                                            side_effect=side_effect)

        self.assertRaises(
            na_utils.NetAppDriverException,
            self.driver._swap_files, fake.FLEXVOL, fake.VOLUME_NAME, new_file)

        if not first_exception:
            mock_rename_file.assert_has_calls([
                mock.call(original_file_path, tmp_file_path),
                mock.call(new_file_path, original_file_path),
                mock.call(tmp_file_path, original_file_path)])
        else:
            mock_rename_file.assert_called_once_with(original_file_path,
                                                     tmp_file_path)

    def test__swap_files_delete_exception(self):
        new_file = 'new-%s' % fake.SNAPSHOT['name']

        self.mock_object(self.driver.zapi_client, 'rename_file')
        side_effect = exception.VolumeBackendAPIException(data="data")
        self.mock_object(self.driver.zapi_client, 'delete_file',
                         side_effect=side_effect)

        self.driver._swap_files(fake.FLEXVOL, fake.VOLUME_NAME, new_file)
