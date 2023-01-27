# Copyright (c) 2023 NetApp, Inc. All rights reserved.
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
"""Mock unit tests for the NetApp block storage library"""

import copy
from unittest import mock
import uuid

import ddt
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as fake
import cinder.tests.unit.volume.drivers.netapp.fakes as na_fakes
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap import nvme_library
from cinder.volume.drivers.netapp.dataontap.performance import perf_cmode
from cinder.volume.drivers.netapp.dataontap.utils import capabilities
from cinder.volume.drivers.netapp.dataontap.utils import loopingcalls
from cinder.volume.drivers.netapp.dataontap.utils import utils as dot_utils
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import volume_utils


@ddt.ddt
class NetAppNVMeStorageLibraryTestCase(test.TestCase):

    def setUp(self):
        super(NetAppNVMeStorageLibraryTestCase, self).setUp()

        config = na_fakes.create_configuration_cmode()
        config.netapp_storage_protocol = 'nvme'
        config.netapp_login = 'admin'
        config.netapp_password = 'pass'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'https'
        config.netapp_server_port = '443'
        config.netapp_vserver = 'openstack'
        config.netapp_api_trace_pattern = 'fake_regex'

        kwargs = {
            'configuration': config,
            'host': 'openstack@netappnvme',
        }

        self.library = nvme_library.NetAppNVMeStorageLibrary(
            'driver', 'protocol', **kwargs)
        self.library.client = mock.Mock()
        self.client = self.library.client
        self.mock_request = mock.Mock()
        self.ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        self.vserver = fake.VSERVER_NAME

        self.library.perf_library = mock.Mock()
        self.library.ssc_library = mock.Mock()
        self.library.vserver = mock.Mock()

        # fakes objects.
        self.fake_namespace = nvme_library.NetAppNamespace(
            fake.NAMESPACE_HANDLE, fake.NAMESPACE_NAME, fake.SIZE,
            fake.NAMESPACE_METADATA)
        self.fake_snapshot_namespace = nvme_library.NetAppNamespace(
            fake.SNAPSHOT_NAMESPACE_HANDLE, fake.SNAPSHOT_NAME, fake.SIZE,
            None)
        self.mock_object(self.library, 'namespace_table')
        self.library.namespace_table = {
            fake.NAMESPACE_NAME: self.fake_namespace,
            fake.SNAPSHOT_NAME: self.fake_snapshot_namespace,
        }

    @mock.patch.object(perf_cmode, 'PerformanceCmodeLibrary', mock.Mock())
    @mock.patch.object(capabilities.CapabilitiesLibrary,
                       'cluster_user_supported')
    @mock.patch.object(capabilities.CapabilitiesLibrary,
                       'check_api_permissions')
    @mock.patch.object(na_utils, 'check_flags')
    def test_do_setup_san_unconfigured(self, mock_check_flags,
                                       mock_check_api_permissions,
                                       mock_cluster_user_supported):
        self.library.configuration.netapp_namespace_ostype = None
        self.library.configuration.netapp_host_type = None
        self.library.backend_name = 'fake_backend'
        fake_client = mock.Mock()
        fake_client.vserver = 'fake_vserver'
        self.mock_object(dot_utils, 'get_client_for_backend',
                         return_value=fake_client)

        self.library.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        mock_check_api_permissions.assert_called_once_with()
        mock_cluster_user_supported.assert_called_once_with()
        self.assertEqual('linux', self.library.namespace_ostype)
        self.assertEqual('linux', self.library.host_type)
        dot_utils.get_client_for_backend.assert_called_once_with(
            'fake_backend', force_rest=True)

    def test_check_for_setup_error(self):
        self.mock_object(self.library, '_get_flexvol_to_pool_map',
                         return_value=fake.POOL_NAME)
        self.mock_object(self.library, '_add_looping_tasks')
        self.library.namespace_ostype = 'linux'
        self.library.host_type = 'linux'
        self.mock_object(self.library.client, 'get_namespace_list',
                         return_value='fake_namespace_list')
        self.mock_object(self.library, '_extract_and_populate_namespaces')
        self.mock_object(self.library.loopingcalls, 'start_tasks')

        self.library.check_for_setup_error()

        self.library._get_flexvol_to_pool_map.assert_called_once_with()
        self.library._add_looping_tasks.assert_called_once_with()
        self.library.client.get_namespace_list.assert_called_once_with()
        self.library._extract_and_populate_namespaces.assert_called_once_with(
            'fake_namespace_list')
        self.library.loopingcalls.start_tasks.assert_called_once_with()

    @ddt.data(
        {'pool_map': None, 'namespace': 'linux', 'host': 'linux'},
        {'pool_map': 'fake_map', 'namespace': 'fake', 'host': 'linux'},
        {'pool_map': 'fake_map', 'namespace': 'linux', 'host': 'fake'})
    @ddt.unpack
    def test_check_for_setup_error_error(self, pool_map, namespace, host):
        self.mock_object(self.library, '_get_flexvol_to_pool_map',
                         return_value=pool_map)
        self.library.namespace_ostype = namespace
        self.library.host_type = host
        self.mock_object(self.library, '_add_looping_tasks')

        self.assertRaises(
            na_utils.NetAppDriverException,
            self.library.check_for_setup_error)

    def test_create_volume(self):
        volume_size_in_bytes = int(fake.SIZE) * units.Gi
        self.mock_object(volume_utils, 'extract_host',
                         return_value=fake.POOL_NAME)
        self.mock_object(self.library.client, 'create_namespace')
        self.mock_object(self.library, '_create_namespace_handle')
        self.mock_object(self.library, '_add_namespace_to_table')

        volume1 = copy.deepcopy(fake.test_volume)
        self.library.create_volume(volume1)

        fake_metadata = {
            'OsType': self.library.namespace_ostype,
            'Path': '/vol/aggr1/fakename',
            'Volume': 'aggr1',
            'Qtree': None
        }
        self.library.client.create_namespace.assert_called_once_with(
            fake.POOL_NAME, 'fakename', volume_size_in_bytes, fake_metadata)
        self.library._create_namespace_handle.assert_called_once_with(
            fake_metadata)

    def test_create_namespace_handle(self):
        self.library.vserver = fake.VSERVER_NAME
        res = self.library._create_namespace_handle(fake.NAMESPACE_METADATA)

        self.assertEqual(f'{fake.VSERVER_NAME}:{fake.PATH_NAMESPACE}', res)

    def test__extract_namespace_info(self):
        self.mock_object(self.library, '_create_namespace_handle',
                         return_value=fake.NAMESPACE_HANDLE)

        namespace = {'Path': fake.PATH_NAMESPACE, 'Size': fake.SIZE}
        res = self.library._extract_namespace_info(namespace)

        self.assertEqual(fake.NAMESPACE_NAME, res.name)
        self.library._create_namespace_handle.assert_called_once_with(
            namespace)

    def test__extract_and_populate_namespaces(self):
        self.mock_object(self.library, '_extract_namespace_info',
                         return_value='fake_namespace')
        self.mock_object(self.library, '_add_namespace_to_table')

        self.library._extract_and_populate_namespaces([fake.NAMESPACE_NAME])

        self.library._extract_namespace_info.assert_called_once_with(
            fake.NAMESPACE_NAME)
        self.library._add_namespace_to_table.assert_called_once_with(
            'fake_namespace')

    def test__add_namespace_to_table(self):
        namespace = nvme_library.NetAppNamespace(
            fake.NAMESPACE_HANDLE, 'fake_namespace2', fake.SIZE, None)
        self.library._add_namespace_to_table(namespace)

        has_namespace = 'fake_namespace2' in self.library.namespace_table
        self.assertTrue(has_namespace)
        self.assertEqual(namespace,
                         self.library.namespace_table['fake_namespace2'])

    def test__add_namespace_to_table_error(self):
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.library._add_namespace_to_table,
            'fake'
        )

    def test__get_namespace_from_table_error(self):
        self.mock_object(self.library.client, 'get_namespace_list',
                         return_value='fake_list')
        self.mock_object(self.library, '_extract_and_populate_namespaces')

        self.assertRaises(
            exception.VolumeNotFound,
            self.library._get_namespace_from_table,
            'fake')

        self.library.client.get_namespace_list.assert_called_once_with()
        self.library._extract_and_populate_namespaces.assert_called_once_with(
            'fake_list')

    def test__get_namespace_from_table(self):

        res = self.library._get_namespace_from_table(fake.NAMESPACE_NAME)

        self.assertEqual(self.fake_namespace, res)

    @ddt.data(exception.VolumeNotFound, netapp_api.NaApiError)
    def test__get_namespace_attr_error(self, error_obj):
        self.mock_object(self.library, '_get_namespace_from_table',
                         side_effect=error_obj)

        res = self.library._get_namespace_attr('namespace', 'name')

        self.assertIsNone(res)

    def test__get_namespace_attr(self):
        self.mock_object(self.library, '_get_namespace_from_table',
                         return_value=self.fake_namespace)

        res = self.library._get_namespace_attr('namespace', 'name')

        self.assertEqual(fake.NAMESPACE_NAME, res)

    def test_create_volume_error(self):
        self.mock_object(volume_utils, 'extract_host',
                         return_value=fake.POOL_NAME)
        self.mock_object(self.library.client, 'create_namespace',
                         side_effect=exception.VolumeBackendAPIException)
        self.mock_object(self.library, '_create_namespace_handle')
        self.mock_object(self.library, '_add_namespace_to_table')

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.library.create_volume,
            copy.deepcopy(fake.test_volume))

    def test__update_ssc(self):
        mock_get_flexvol = self.mock_object(
            self.library, '_get_flexvol_to_pool_map',
            return_value='fake_pool_map')
        self.library.ssc_library.update_ssc = mock.Mock()

        self.library._update_ssc()

        mock_get_flexvol.assert_called_once_with()
        self.library.ssc_library.update_ssc.assert_called_once_with(
            'fake_pool_map')

    def test__find_mapped_namespace_subsystem(self):
        self.mock_object(self.library.client, 'get_subsystem_by_host',
                         return_value=[{'name': fake.SUBSYSTEM}])
        self.mock_object(
            self.library.client, 'get_namespace_map',
            return_value=[{
                'subsystem': fake.SUBSYSTEM,
                'uuid': fake.UUID1
            }])

        subsystem, n_uuid = self.library._find_mapped_namespace_subsystem(
            fake.NAMESPACE_NAME, fake.HOST_NQN)

        self.assertEqual(fake.SUBSYSTEM, subsystem)
        self.assertEqual(fake.UUID1, n_uuid)
        self.library.client.get_subsystem_by_host.assert_called_once_with(
            fake.HOST_NQN)
        self.library.client.get_namespace_map.assert_called_once_with(
            fake.NAMESPACE_NAME)

    def test_delete_volume(self):
        self.mock_object(self.library, '_delete_namespace')

        self.library.delete_volume(fake.NAMESPACE_VOLUME)

        self.library._delete_namespace.assert_called_once_with(
            fake.NAMESPACE_NAME)

    def test__delete_namespace(self):
        namespace = copy.deepcopy(fake.NAMESPACE_WITH_METADATA)
        self.mock_object(self.library, '_get_namespace_attr',
                         return_value=namespace['metadata'])
        self.mock_object(self.library.client, 'destroy_namespace')

        self.library._delete_namespace(fake.NAMESPACE_NAME)

        self.library._get_namespace_attr.assert_called_once_with(
            fake.NAMESPACE_NAME, 'metadata')
        self.library.client.destroy_namespace.assert_called_once_with(
            namespace['metadata']['Path'])
        has_namespace = fake.NAMESPACE_NAME in self.library.namespace_table
        self.assertFalse(has_namespace)

    def test__delete_namespace_not_found(self):
        namespace = copy.deepcopy(fake.NAMESPACE_WITH_METADATA)
        self.mock_object(self.library, '_get_namespace_attr',
                         return_value=namespace['metadata'])
        error = netapp_api.NaApiError(
            code=netapp_api.REST_NAMESPACE_EOBJECTNOTFOUND[0])
        self.mock_object(self.library.client, 'destroy_namespace',
                         side_effect=error)

        self.library._delete_namespace(fake.NAMESPACE_NAME)

        self.library._get_namespace_attr.assert_called_once_with(
            fake.NAMESPACE_NAME, 'metadata')
        self.library.client.destroy_namespace.assert_called_once_with(
            namespace['metadata']['Path'])
        has_namespace = fake.NAMESPACE_NAME in self.library.namespace_table
        self.assertFalse(has_namespace)

    def test__delete_namespace_error(self):
        namespace = copy.deepcopy(fake.NAMESPACE_WITH_METADATA)
        self.mock_object(self.library, '_get_namespace_attr',
                         return_value=namespace['metadata'])
        self.mock_object(self.library.client, 'destroy_namespace',
                         side_effect=netapp_api.NaApiError)

        self.assertRaises(na_utils.NetAppDriverException,
                          self.library._delete_namespace,
                          fake.NAMESPACE_NAME)

    def test__delete_namespace_no_metadata(self):
        self.mock_object(self.library, '_get_namespace_attr',
                         return_value=None)
        self.mock_object(self.library.client, 'destroy_namespace')

        self.library._delete_namespace(fake.NAMESPACE_NAME)

        self.library._get_namespace_attr.assert_called_once_with(
            fake.NAMESPACE_NAME, 'metadata')
        self.library.client.destroy_namespace.assert_not_called()

    def test_add_looping_tasks(self):
        mock_add_task = self.mock_object(self.library.loopingcalls, 'add_task')
        self.mock_object(self.library, '_update_ssc')

        self.library._add_looping_tasks()

        self.library._update_ssc.assert_called_once_with()
        mock_add_task.assert_has_calls([
            mock.call(self.library._update_ssc, loopingcalls.ONE_HOUR,
                      loopingcalls.ONE_HOUR),
            mock.call(self.library._handle_ems_logging,
                      loopingcalls.ONE_HOUR)])

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
            self.client, 'send_ems_log_message')

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

    def test_get_pool(self):
        namespace = copy.deepcopy(fake.NAMESPACE_WITH_METADATA)
        self.mock_object(self.library, '_get_namespace_attr',
                         return_value=namespace['metadata'])

        res = self.library.get_pool(fake.VOLUME)

        self.assertEqual('fake_flexvol', res)
        self.library._get_namespace_attr.assert_called_once_with(
            fake.LUN_NAME, 'metadata')

    def test_delete_snapshot(self):
        mock__delete = self.mock_object(self.library, '_delete_namespace')

        self.library.delete_snapshot(fake.SNAPSHOT)

        mock__delete.assert_called_once_with(fake.SNAPSHOT_NAME)

    def test_create_volume_from_snapshot(self):
        self.mock_object(self.library, '_clone_source_to_destination')

        self.library.create_volume_from_snapshot(fake.NAMESPACE_VOLUME,
                                                 fake.SNAPSHOT)

        self.library._clone_source_to_destination.assert_called_once_with(
            {'name': fake.SNAPSHOT_NAME, 'size': fake.SIZE},
            fake.NAMESPACE_VOLUME)

    def test_create_cloned_volume(self):
        self.mock_object(self.library, '_get_namespace_from_table',
                         return_value=self.fake_namespace)
        self.mock_object(self.library, '_clone_source_to_destination')

        src_volume = {'size': fake.SIZE, 'name': 'fake_name'}
        self.library.create_cloned_volume(fake.NAMESPACE_VOLUME, src_volume)

        self.library._get_namespace_from_table.assert_called_once_with(
            'fake_name')
        self.library._clone_source_to_destination.assert_called_once_with(
            {'name': fake.NAMESPACE_NAME, 'size': fake.SIZE},
            fake.NAMESPACE_VOLUME)

    def test_clone_source_to_destination(self):
        self.mock_object(self.library, '_clone_namespace')
        self.mock_object(self.library, '_extend_volume')
        self.mock_object(self.library, 'delete_volume')

        source_vol = {'size': fake.SIZE, 'name': 'fake_source'}
        dest_size = fake.SIZE + 12
        dest_vol = {'size': dest_size, 'name': 'fake_dest'}
        self.library._clone_source_to_destination(source_vol, dest_vol)

        self.library._clone_namespace.assert_called_once_with(
            'fake_source', 'fake_dest')
        self.library._extend_volume.assert_called_once_with(
            dest_vol, dest_size)
        self.library.delete_volume.assert_not_called()

    def test_clone_source_to_destination_clone_error(self):
        self.mock_object(self.library, '_clone_namespace',
                         side_effect=exception.VolumeBackendAPIException)
        self.mock_object(self.library, '_extend_volume')
        self.mock_object(self.library, 'delete_volume')

        source_vol = {'size': fake.SIZE, 'name': 'fake_source'}
        dest_size = fake.SIZE + 12
        dest_vol = {'size': dest_size, 'name': 'fake_dest'}
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.library._clone_source_to_destination,
            source_vol, dest_vol)

    def test_clone_source_to_destination_extend_error(self):
        self.mock_object(self.library, '_clone_namespace')
        self.mock_object(self.library, '_extend_volume',
                         side_effect=exception.VolumeBackendAPIException)
        self.mock_object(self.library, 'delete_volume')

        source_vol = {'size': fake.SIZE, 'name': 'fake_source'}
        dest_size = fake.SIZE + 12
        dest_vol = {'size': dest_size, 'name': 'fake_dest'}
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.library._clone_source_to_destination,
            source_vol, dest_vol)

    @ddt.data(True, False)
    def test_get_volume_stats(self, refresh):
        self.library._stats = 'fake_stats'
        self.mock_object(self.library, '_update_volume_stats')

        res = self.library.get_volume_stats(refresh, filter_function='filter',
                                            goodness_function='good')

        self.assertEqual('fake_stats', res)
        if refresh:
            self.library._update_volume_stats.assert_called_once_with(
                filter_function='filter', goodness_function='good')
        else:
            self.library._update_volume_stats.assert_not_called()

    def test__update_volume_stats(self):

        self.library.VERSION = '1.0.0'
        self.library.driver_protocol = 'nvme'
        self.mock_object(self.library, '_get_pool_stats',
                         return_value='fake_pools')
        self.library._update_volume_stats(filter_function='filter',
                                          goodness_function='good')

        expected_ssc = {
            'volume_backend_name': 'driver',
            'vendor_name': 'NetApp',
            'driver_version': '1.0.0',
            'pools': 'fake_pools',
            'sparse_copy_volume': True,
            'replication_enabled': False,
            'storage_protocol': 'nvme',
        }
        self.assertEqual(expected_ssc, self.library._stats)

    @ddt.data({'cluster_credentials': False,
               'report_provisioned_capacity': False},
              {'cluster_credentials': True,
               'report_provisioned_capacity': True})
    @ddt.unpack
    def test_get_pool_stats(self, cluster_credentials,
                            report_provisioned_capacity):
        self.library.using_cluster_credentials = cluster_credentials
        conf = self.library.configuration
        conf.netapp_driver_reports_provisioned_capacity = (
            report_provisioned_capacity)

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
                'netapp_is_flexgroup': 'false',
            },
        }
        mock_get_ssc = self.mock_object(self.library.ssc_library,
                                        'get_ssc',
                                        return_value=ssc)
        mock_get_aggrs = self.mock_object(self.library.ssc_library,
                                          'get_ssc_aggregates',
                                          return_value=['aggr1'])

        self.library.reserved_percentage = 5
        self.library.max_over_subscription_ratio = 10
        self.library.perf_library.get_node_utilization_for_pool = (
            mock.Mock(return_value=30.0))
        mock_capacities = {
            'size-total': 10737418240.0,
            'size-available': 2147483648.0,
        }
        namespaces_provisioned_cap = [{
            'path': '/vol/volume-ae947c9b-2392-4956-b373-aaac4521f37e',
            'size': 5368709120.0  # 5GB
        }, {
            'path': '/vol/snapshot-527eedad-a431-483d-b0ca-18995dd65b66',
            'size': 1073741824.0  # 1GB
        }]
        self.mock_object(self.client,
                         'get_flexvol_capacity',
                         return_value=mock_capacities)
        self.mock_object(self.client,
                         'get_namespace_sizes_by_volume',
                         return_value=namespaces_provisioned_cap)
        self.mock_object(self.client,
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
            self.client, 'get_aggregate_capacities',
            return_value=aggr_capacities)

        result = self.library._get_pool_stats(filter_function='filter',
                                              goodness_function='goodness')

        expected = [{
            'pool_name': 'vola',
            'QoS_support': False,
            'consistencygroup_support': False,
            'consistent_group_snapshot_enabled': False,
            'reserved_percentage': 5,
            'max_over_subscription_ratio': 10,
            'multiattach': False,
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
            'online_extend_support': False,
            'netapp_is_flexgroup': 'false',
        }]
        if report_provisioned_capacity:
            expected[0].update({'provisioned_capacity_gb': 5.0})

        if not cluster_credentials:
            expected[0].update({
                'netapp_aggregate_used_percent': 0,
                'netapp_dedupe_used_percent': 0.0
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
            self.library.client, 'list_flexvols',
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
            self.library.client, 'list_flexvols',
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
            self.library.client, 'list_flexvols',
            return_value=fake.FAKE_CMODE_VOLUMES)

        result = self.library._get_flexvol_to_pool_map()

        self.assertEqual({}, result)
        mock_list_flexvols.assert_called_once_with()

    def test_create_snapshot(self):
        self.mock_object(self.library, '_create_snapshot')

        self.library.create_snapshot('fake_snap')

        self.library._create_snapshot.assert_called_once_with('fake_snap')

    def test__create_snapshot(self):
        self.mock_object(self.library, '_get_namespace_from_table',
                         return_value=self.fake_namespace)
        self.mock_object(self.library, '_clone_namespace')

        self.library._create_snapshot(fake.SNAPSHOT)

        self.library._get_namespace_from_table.assert_called_once_with(
            fake.VOLUME_NAME)
        self.library._clone_namespace.assert_called_once_with(
            fake.NAMESPACE_NAME, fake.SNAPSHOT_NAME)

    def test__clone_namespace_error(self):
        self.mock_object(self.library, '_get_namespace_attr',
                         return_value=fake.NAMESPACE_METADATA)
        self.mock_object(self.library.client, 'clone_namespace')
        self.mock_object(self.library.client, 'get_namespace_by_args',
                         return_value=[])

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.library._clone_namespace,
            fake.NAMESPACE_NAME,
            'fake_new_name')

    def test__clone_namespace(self):
        self.mock_object(self.library, '_get_namespace_attr',
                         return_value=fake.NAMESPACE_METADATA)
        self.mock_object(self.library.client, 'clone_namespace')
        fake_namespace_res = {
            'Vserver': fake.VSERVER_NAME,
            'Path': fake.NAMESPACE_NAME,
            'Size': 1024
        }
        self.mock_object(self.library.client, 'get_namespace_by_args',
                         return_value=[fake_namespace_res])
        self.mock_object(self.library, '_add_namespace_to_table')

        self.library._clone_namespace(fake.NAMESPACE_NAME, 'fake_new_name')

        self.library._get_namespace_attr.assert_called_once_with(
            fake.NAMESPACE_NAME, 'metadata')
        self.library.client.clone_namespace.assert_called_once_with(
            fake.POOL_NAME, fake.NAMESPACE_NAME, 'fake_new_name')
        self.library.client.get_namespace_by_args.assert_called_once()
        self.library._add_namespace_to_table.assert_called_once()

    def test_ensure_export(self):
        self.mock_object(self.library, '_get_namespace_attr',
                         return_value='fake_handle')

        res = self.library.ensure_export(mock.Mock(), fake.NAMESPACE_VOLUME)

        self.assertEqual({'provider_location': 'fake_handle'}, res)
        self.library._get_namespace_attr.assert_called_once_with(
            fake.NAMESPACE_NAME, 'handle')

    def test_create_export(self):
        self.mock_object(self.library, '_get_namespace_attr',
                         return_value='fake_handle')

        res = self.library.create_export(mock.Mock(), fake.NAMESPACE_VOLUME)

        self.assertEqual({'provider_location': 'fake_handle'}, res)
        self.library._get_namespace_attr.assert_called_once_with(
            fake.NAMESPACE_NAME, 'handle')

    def test__extend_volume(self):
        self.mock_object(self.library, '_get_namespace_from_table',
                         return_value=self.fake_namespace)
        self.mock_object(self.library.client, 'namespace_resize')

        self.library._extend_volume(fake.NAMESPACE_VOLUME, fake.SIZE)

        new_bytes = str(int(fake.SIZE) * units.Gi)
        self.assertEqual(new_bytes, self.fake_namespace.size)
        self.library._get_namespace_from_table.assert_called_once_with(
            fake.NAMESPACE_NAME)
        self.library.client.namespace_resize.assert_called_once_with(
            fake.PATH_NAMESPACE, new_bytes)

    @ddt.data([{'name': fake.SUBSYSTEM, 'os_type': 'linux'}], [])
    def test__get_or_create_subsystem(self, subs):
        self.mock_object(self.library.client, 'get_subsystem_by_host',
                         return_value=subs)
        self.mock_object(self.library.client, 'create_subsystem')
        self.mock_object(uuid, 'uuid4', return_value='fake_uuid')

        sub, os = self.library._get_or_create_subsystem(fake.HOST_NQN, 'linux')

        self.library.client.get_subsystem_by_host.assert_called_once_with(
            fake.HOST_NQN)
        self.assertEqual('linux', os)
        if subs:
            self.assertEqual(fake.SUBSYSTEM, sub)
        else:
            self.library.client.create_subsystem.assert_called_once_with(
                sub, 'linux', fake.HOST_NQN)
            expected_sub = 'openstack-fake_uuid'
            self.assertEqual(expected_sub, sub)

    def test__map_namespace(self):
        self.library.host_type = 'win'
        self.mock_object(self.library, '_get_or_create_subsystem',
                         return_value=(fake.SUBSYSTEM, 'linux'))
        self.mock_object(self.library, '_get_namespace_attr',
                         return_value=fake.NAMESPACE_METADATA)
        self.mock_object(self.library.client, 'map_namespace',
                         return_value=fake.UUID1)

        sub, n_uuid = self.library._map_namespace(
            fake.NAMESPACE_NAME, fake.HOST_NQN)

        self.assertEqual(fake.SUBSYSTEM, sub)
        self.assertEqual(fake.UUID1, n_uuid)
        self.library._get_or_create_subsystem.assert_called_once_with(
            fake.HOST_NQN, 'win')
        self.library.client.map_namespace.assert_called_once_with(
            fake.PATH_NAMESPACE, fake.SUBSYSTEM)

    def test_initialize_connection(self):
        self.mock_object(self.library, '_map_namespace',
                         return_value=(fake.SUBSYSTEM, fake.UUID1))
        self.mock_object(self.library.client, 'get_nvme_subsystem_nqn',
                         return_value=fake.TARGET_NQN)
        self.mock_object(self.library.client, 'get_nvme_target_portals',
                         return_value=['fake_ip'])

        res = self.library.initialize_connection(
            fake.NAMESPACE_VOLUME, {'nqn': fake.HOST_NQN})

        expected_conn_info = {
            "driver_volume_type": "nvmeof",
            "data": {
                "target_nqn": fake.TARGET_NQN,
                "host_nqn": fake.HOST_NQN,
                "portals": [('fake_ip', 4420, 'tcp')],
                "vol_uuid": fake.UUID1
            }
        }
        self.assertEqual(expected_conn_info, res)
        self.library._map_namespace.assert_called_once_with(
            fake.NAMESPACE_NAME, fake.HOST_NQN)
        self.library.client.get_nvme_subsystem_nqn.assert_called_once_with(
            fake.SUBSYSTEM)
        self.library.client.get_nvme_target_portals.assert_called_once_with()

    def test_initialize_connection_error_no_host(self):
        self.mock_object(self.library, '_map_namespace',
                         return_value=(fake.SUBSYSTEM, fake.UUID1))
        self.mock_object(self.library.client, 'get_nvme_subsystem_nqn',
                         return_value=fake.TARGET_NQN)
        self.mock_object(self.library.client, 'get_nvme_target_portals',
                         return_value=['fake_ip'])

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.library.initialize_connection,
            fake.NAMESPACE_VOLUME, {})

    def test_initialize_connection_error_no_target(self):
        self.mock_object(self.library, '_map_namespace',
                         return_value=(fake.SUBSYSTEM, fake.UUID1))
        self.mock_object(self.library.client, 'get_nvme_subsystem_nqn',
                         return_value=None)
        self.mock_object(self.library.client, 'get_nvme_target_portals',
                         return_value=['fake_ip'])

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.library.initialize_connection,
            fake.NAMESPACE_VOLUME, {'nqn': fake.HOST_NQN})

    def test_initialize_connection_error_no_portals(self):
        self.mock_object(self.library, '_map_namespace',
                         return_value=(fake.SUBSYSTEM, fake.UUID1))
        self.mock_object(self.library.client, 'get_nvme_subsystem_nqn',
                         return_value=fake.TARGET_NQN)
        self.mock_object(self.library.client, 'get_nvme_target_portals',
                         return_value=[])

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.library.initialize_connection,
            fake.NAMESPACE_VOLUME, {'nqn': fake.HOST_NQN})

    @ddt.data(fake.HOST_NQN, None)
    def test__unmap_namespace(self, host_nqn):
        mock_find = self.mock_object(
            self.library, '_find_mapped_namespace_subsystem',
            return_value=(fake.SUBSYSTEM, 'fake'))
        self.mock_object(self.library.client, 'get_namespace_map',
                         return_value=[{'subsystem': fake.SUBSYSTEM}])
        self.mock_object(self.library.client, 'unmap_namespace')

        self.library._unmap_namespace(fake.PATH_NAMESPACE, host_nqn)

        if host_nqn:
            mock_find.assert_called_once_with(fake.PATH_NAMESPACE,
                                              fake.HOST_NQN)
            self.library.client.get_namespace_map.assert_not_called()
        else:
            self.library._find_mapped_namespace_subsystem.assert_not_called()
            self.library.client.get_namespace_map.assert_called_once_with(
                fake.PATH_NAMESPACE)
        self.library.client.unmap_namespace.assert_called_once_with(
            fake.PATH_NAMESPACE, fake.SUBSYSTEM)

    @ddt.data(None, {'nqn': fake.HOST_NQN})
    def test_terminate_connection(self, connector):
        self.mock_object(self.library, '_get_namespace_attr',
                         return_value=fake.NAMESPACE_METADATA)
        self.mock_object(self.library, '_unmap_namespace')

        self.library.terminate_connection(fake.NAMESPACE_VOLUME, connector)

        self.library._get_namespace_attr.assert_called_once_with(
            fake.NAMESPACE_NAME, 'metadata')
        host = connector['nqn'] if connector else None
        self.library._unmap_namespace(fake.PATH_NAMESPACE, host)
