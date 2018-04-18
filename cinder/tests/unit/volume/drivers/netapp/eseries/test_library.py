# Copyright (c) 2014 Andrew Kerr
# Copyright (c) 2015 Alex Meade
# Copyright (c) 2015 Rushil Chugh
# Copyright (c) 2015 Yogesh Kshirsagar
# Copyright (c) 2015 Michael Price
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

import copy
import ddt
import time
import uuid

import mock
from oslo_utils import units
import six
from six.moves import range
from six.moves import reduce

from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder import test

from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import utils as cinder_utils
from cinder.tests.unit.volume.drivers.netapp.eseries import fakes as \
    eseries_fake
from cinder.volume.drivers.netapp.eseries import client as es_client
from cinder.volume.drivers.netapp.eseries import exception as eseries_exc
from cinder.volume.drivers.netapp.eseries import host_mapper
from cinder.volume.drivers.netapp.eseries import library
from cinder.volume.drivers.netapp.eseries import utils
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import utils as volume_utils
from cinder.zonemanager import utils as fczm_utils


def get_fake_volume():
    """Return a fake Cinder Volume that can be used as a parameter"""
    return {
        'id': '114774fb-e15a-4fae-8ee2-c9723e3645ef', 'size': 1,
        'volume_name': 'lun1', 'host': 'hostname@backend#DDP',
        'os_type': 'linux', 'provider_location': 'lun1',
        'name_id': '114774fb-e15a-4fae-8ee2-c9723e3645ef',
        'provider_auth': 'provider a b', 'project_id': 'project',
        'display_name': None, 'display_description': 'lun1',
        'volume_type_id': None, 'migration_status': None, 'attach_status':
        fields.VolumeAttachStatus.DETACHED
    }


@ddt.ddt
class NetAppEseriesLibraryTestCase(test.TestCase):
    def setUp(self):
        super(NetAppEseriesLibraryTestCase, self).setUp()

        kwargs = {'configuration':
                  eseries_fake.create_configuration_eseries()}

        self.library = library.NetAppESeriesLibrary('FAKE', **kwargs)

        # We don't want the looping calls to run
        self.mock_object(self.library, '_start_periodic_tasks')
        # Deprecated Option
        self.library.configuration.netapp_storage_pools = None
        self.library._client = eseries_fake.FakeEseriesClient()

        self.mock_object(self.library, '_start_periodic_tasks')

        self.mock_object(library.cinder_utils, 'synchronized',
                         return_value=lambda f: f)

        with mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                        new = cinder_utils.ZeroIntervalLoopingCall):
            self.library.check_for_setup_error()

        self.ctxt = context.get_admin_context()

    def test_do_setup(self):
        self.mock_object(self.library,
                         '_check_mode_get_or_register_storage_system')
        self.mock_object(es_client, 'RestClient',
                         eseries_fake.FakeEseriesClient)
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        self.library.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)

    @ddt.data('linux_dm_mp', 'linux_atto', 'linux_mpp_rdac',
              'linux_pathmanager', 'linux_sf', 'ontap', 'ontap_rdac',
              'vmware', 'windows_atto', 'windows_clustered',
              'factoryDefault', 'windows', None)
    def test_check_host_type(self, host_type):
        config = mock.Mock()
        default_host_type = self.library.host_type
        config.netapp_host_type = host_type
        self.mock_object(self.library, 'configuration', config)

        result = self.library._check_host_type()

        self.assertIsNone(result)
        if host_type:
            self.assertEqual(self.library.HOST_TYPES.get(host_type),
                             self.library.host_type)
        else:
            self.assertEqual(default_host_type, self.library.host_type)

    def test_check_host_type_invalid(self):
        config = mock.Mock()
        config.netapp_host_type = 'invalid'
        self.mock_object(self.library, 'configuration', config)

        self.assertRaises(exception.NetAppDriverException,
                          self.library._check_host_type)

    def test_check_host_type_new(self):
        config = mock.Mock()
        config.netapp_host_type = 'new_host_type'
        expected = 'host_type'
        self.mock_object(self.library, 'configuration', config)
        host_types = [{
            'name': 'new_host_type',
            'index': 0,
            'code': expected,
        }]
        self.mock_object(self.library._client, 'list_host_types',
                         return_value=host_types)

        result = self.library._check_host_type()

        self.assertIsNone(result)
        self.assertEqual(expected, self.library.host_type)

    @ddt.data(('optimal', True), ('offline', False), ('needsAttn', True),
              ('neverContacted', False), ('newKey', True), (None, True))
    @ddt.unpack
    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall', new=
                cinder_utils.ZeroIntervalLoopingCall)
    def test_check_storage_system_status(self, status, status_valid):
        system = copy.deepcopy(eseries_fake.STORAGE_SYSTEM)
        system['status'] = status
        status = status.lower() if status is not None else ''

        actual_status, actual_valid = (
            self.library._check_storage_system_status(system))

        self.assertEqual(status, actual_status)
        self.assertEqual(status_valid, actual_valid)

    @ddt.data(('valid', True), ('invalid', False), ('unknown', False),
              ('newKey', True), (None, True))
    @ddt.unpack
    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall', new=
                cinder_utils.ZeroIntervalLoopingCall)
    def test_check_password_status(self, status, status_valid):
        system = copy.deepcopy(eseries_fake.STORAGE_SYSTEM)
        system['passwordStatus'] = status
        status = status.lower() if status is not None else ''

        actual_status, actual_valid = (
            self.library._check_password_status(system))

        self.assertEqual(status, actual_status)
        self.assertEqual(status_valid, actual_valid)

    def test_check_storage_system_bad_system(self):
        exc_str = "bad_system"
        controller_ips = self.library.configuration.netapp_controller_ips
        self.library._client.list_storage_system = mock.Mock(
            side_effect=exception.NetAppDriverException(message=exc_str))
        info_log = self.mock_object(library.LOG, 'info')

        self.assertRaisesRegexp(exception.NetAppDriverException, exc_str,
                                self.library._check_storage_system)

        info_log.assert_called_once_with(mock.ANY, controller_ips)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall', new=
                cinder_utils.ZeroIntervalLoopingCall)
    def test_check_storage_system(self):
        system = copy.deepcopy(eseries_fake.STORAGE_SYSTEM)
        self.mock_object(self.library._client, 'list_storage_system',
                         return_value=system)
        update_password = self.mock_object(self.library._client,
                                           'update_stored_system_password')
        info_log = self.mock_object(library.LOG, 'info')

        self.library._check_storage_system()

        self.assertTrue(update_password.called)
        self.assertTrue(info_log.called)

    @ddt.data({'status': 'optimal', 'passwordStatus': 'invalid'},
              {'status': 'offline', 'passwordStatus': 'valid'})
    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall', new=
                cinder_utils.ZeroIntervalLoopingCall)
    def test_check_storage_system_bad_status(self, system):
        self.mock_object(self.library._client, 'list_storage_system',
                         return_value=system)
        self.mock_object(self.library._client, 'update_stored_system_password')
        self.mock_object(time, 'time', side_effect=range(0, 60, 5))

        self.assertRaisesRegexp(exception.NetAppDriverException,
                                'bad.*?status',
                                self.library._check_storage_system)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall', new=
                cinder_utils.ZeroIntervalLoopingCall)
    def test_check_storage_system_update_password(self):
        self.library.configuration.netapp_sa_password = 'password'

        def get_system_iter():
            key = 'passwordStatus'
            system = copy.deepcopy(eseries_fake.STORAGE_SYSTEM)
            system[key] = 'invalid'
            yield system
            yield system

            system[key] = 'valid'
            yield system

        self.mock_object(self.library._client, 'list_storage_system',
                         side_effect=get_system_iter())
        update_password = self.mock_object(self.library._client,
                                           'update_stored_system_password')
        info_log = self.mock_object(library.LOG, 'info')

        self.library._check_storage_system()

        update_password.assert_called_once_with(
            self.library.configuration.netapp_sa_password)
        self.assertTrue(info_log.called)

    def test_get_storage_pools_empty_result(self):
        """Verify an exception is raised if no pools are returned."""
        self.library.configuration.netapp_pool_name_search_pattern = '$'

    def test_get_storage_pools_invalid_conf(self):
        """Verify an exception is raised if the regex pattern is invalid."""
        self.library.configuration.netapp_pool_name_search_pattern = '(.*'

        self.assertRaises(exception.InvalidConfigurationValue,
                          self.library._get_storage_pools)

    def test_get_storage_pools_default(self):
        """Verify that all pools are returned if the search option is empty."""
        filtered_pools = self.library._get_storage_pools()

        self.assertEqual(eseries_fake.STORAGE_POOLS, filtered_pools)

    @ddt.data((r'[\d]+,a', ['1', '2', 'a', 'b'], ['1', '2', 'a']),
              ('1   ,    3', ['1', '2', '3'], ['1', '3']),
              ('$,3', ['1', '2', '3'], ['3']),
              ('[a-zA-Z]+', ['1', 'a', 'B'], ['a', 'B']),
              ('', ['1', '2'], ['1', '2'])
              )
    @ddt.unpack
    def test_get_storage_pools(self, pool_filter, pool_labels,
                               expected_pool_labels):
        """Verify that pool filtering via the search_pattern works correctly

        :param pool_filter: A regular expression to be used for filtering via
         pool labels
        :param pool_labels: A list of pool labels
        :param expected_pool_labels: The labels from 'pool_labels' that
         should be matched by 'pool_filter'
        """
        self.library.configuration.netapp_pool_name_search_pattern = (
            pool_filter)
        pools = [{'label': label} for label in pool_labels]

        self.library._client.list_storage_pools = mock.Mock(
            return_value=pools)

        filtered_pools = self.library._get_storage_pools()

        filtered_pool_labels = [pool['label'] for pool in filtered_pools]
        self.assertEqual(expected_pool_labels, filtered_pool_labels)

    def test_get_volume(self):
        fake_volume = copy.deepcopy(get_fake_volume())
        volume = copy.deepcopy(eseries_fake.VOLUME)
        self.library._client.list_volume = mock.Mock(return_value=volume)

        result = self.library._get_volume(fake_volume['id'])

        self.assertEqual(1, self.library._client.list_volume.call_count)
        self.assertDictEqual(volume, result)

    def test_get_volume_bad_input(self):
        volume = copy.deepcopy(eseries_fake.VOLUME)
        self.library._client.list_volume = mock.Mock(return_value=volume)

        self.assertRaises(exception.InvalidInput, self.library._get_volume,
                          None)

    def test_get_volume_bad_uuid(self):
        volume = copy.deepcopy(eseries_fake.VOLUME)
        self.library._client.list_volume = mock.Mock(return_value=volume)

        self.assertRaises(ValueError, self.library._get_volume, '1')

    def test_update_ssc_info_no_ssc(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'driveMediaType': 'ssd'}]
        pools = [{'volumeGroupRef': 'test_vg1', 'label': 'test_vg1',
                  'raidLevel': 'raid6', 'securityType': 'enabled'}]
        self.library._client = mock.Mock()
        self.library._client.features.SSC_API_V2 = na_utils.FeatureState(
            False, minimum_version="1.53.9000.1")
        self.library._client.SSC_VALID_VERSIONS = [(1, 53, 9000, 1),
                                                   (1, 53, 9010, 15)]
        self.library.configuration.netapp_pool_name_search_pattern = "test_vg1"
        self.library._client.list_storage_pools = mock.Mock(return_value=pools)
        self.library._client.list_drives = mock.Mock(return_value=drives)

        self.library._update_ssc_info()

        self.assertEqual(
            {'test_vg1': {'netapp_disk_encryption': 'true',
                          'netapp_disk_type': 'SSD',
                          'netapp_raid_type': 'raid6'}},
            self.library._ssc_stats)

    @ddt.data(True, False)
    def test_update_ssc_info(self, data_assurance_supported):
        self.library._client = mock.Mock()
        self.library._client.features.SSC_API_V2 = na_utils.FeatureState(
            True, minimum_version="1.53.9000.1")
        self.library._client.list_ssc_storage_pools = mock.Mock(
            return_value=eseries_fake.SSC_POOLS)
        self.library._get_storage_pools = mock.Mock(
            return_value=eseries_fake.STORAGE_POOLS)
        # Data Assurance is not supported on some storage backends
        self.library._is_data_assurance_supported = mock.Mock(
            return_value=data_assurance_supported)

        self.library._update_ssc_info()

        for pool in eseries_fake.SSC_POOLS:
            poolId = pool['poolId']

            raid_lvl = self.library.SSC_RAID_TYPE_MAPPING.get(
                pool['raidLevel'], 'unknown')

            if pool['pool']["driveMediaType"] == 'ssd':
                disk_type = 'SSD'
            else:
                disk_type = pool['pool']['drivePhysicalType']
                disk_type = (
                    self.library.SSC_DISK_TYPE_MAPPING.get(
                        disk_type, 'unknown'))

            da_enabled = pool['dataAssuranceCapable'] and (
                data_assurance_supported)

            thin_provisioned = pool['thinProvisioningCapable']

            expected = {
                'consistencygroup_support': True,
                'netapp_disk_encryption':
                    six.text_type(pool['encrypted']).lower(),
                'netapp_eseries_flash_read_cache':
                    six.text_type(pool['flashCacheCapable']).lower(),
                'netapp_thin_provisioned':
                    six.text_type(thin_provisioned).lower(),
                'netapp_eseries_data_assurance':
                    six.text_type(da_enabled).lower(),
                'netapp_eseries_disk_spindle_speed': pool['spindleSpeed'],
                'netapp_raid_type': raid_lvl,
                'netapp_disk_type': disk_type
            }
            actual = self.library._ssc_stats[poolId]
            self.assertDictEqual(expected, actual)

    @ddt.data(('FC', True), ('iSCSI', False))
    @ddt.unpack
    def test_is_data_assurance_supported(self, backend_storage_protocol,
                                         enabled):
        self.mock_object(self.library, 'driver_protocol',
                         backend_storage_protocol)

        actual = self.library._is_data_assurance_supported()

        self.assertEqual(enabled, actual)

    @ddt.data('scsi', 'fibre', 'sas', 'sata', 'garbage')
    def test_update_ssc_disk_types(self, disk_type):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': disk_type}}]
        pools = [{'volumeGroupRef': 'test_vg1'}]

        self.library._client.list_drives = mock.Mock(return_value=drives)
        self.library._client.get_storage_pool = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_disk_types(pools)

        expected = self.library.SSC_DISK_TYPE_MAPPING.get(disk_type, 'unknown')
        self.assertEqual({'test_vg1': {'netapp_disk_type': expected}},
                         ssc_stats)

    @ddt.data('scsi', 'fibre', 'sas', 'sata', 'garbage')
    def test_update_ssc_disk_types_ssd(self, disk_type):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'driveMediaType': 'ssd', 'driveType': disk_type}]
        pools = [{'volumeGroupRef': 'test_vg1'}]

        self.library._client.list_drives = mock.Mock(return_value=drives)
        self.library._client.get_storage_pool = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_disk_types(pools)

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SSD'}},
                         ssc_stats)

    @ddt.data('enabled', 'none', 'capable', 'unknown', '__UNDEFINED',
              'garbage')
    def test_update_ssc_disk_encryption(self, securityType):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': securityType}]
        self.library._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_disk_encryption(pools)

        # Convert the boolean value to a lower-case string value
        expected = 'true' if securityType == "enabled" else 'false'
        self.assertEqual({'test_vg1': {'netapp_disk_encryption': expected}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_multiple(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'none'},
                 {'volumeGroupRef': 'test_vg2', 'securityType': 'enabled'}]
        self.library._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_disk_encryption(pools)

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'},
                          'test_vg2': {'netapp_disk_encryption': 'true'}},
                         ssc_stats)

    @ddt.data(True, False)
    def test_get_volume_stats(self, refresh):
        fake_stats = {'key': 'val'}

        def populate_stats():
            self.library._stats = fake_stats

        self.library._update_volume_stats = mock.Mock(
            side_effect=populate_stats)
        self.library._update_ssc_info = mock.Mock()
        self.library._ssc_stats = {self.library.THIN_UQ_SPEC: True}

        actual = self.library.get_volume_stats(refresh = refresh)

        if(refresh):
            self.library._update_volume_stats.assert_called_once_with()
            self.assertEqual(fake_stats, actual)
        else:
            self.assertEqual(0, self.library._update_volume_stats.call_count)
        self.assertEqual(0, self.library._update_ssc_info.call_count)

    def test_get_volume_stats_no_ssc(self):
        """Validate that SSC data is collected if not yet populated"""
        fake_stats = {'key': 'val'}

        def populate_stats():
            self.library._stats = fake_stats

        self.library._update_volume_stats = mock.Mock(
            side_effect=populate_stats)
        self.library._update_ssc_info = mock.Mock()
        self.library._ssc_stats = None

        actual = self.library.get_volume_stats(refresh = True)

        self.library._update_volume_stats.assert_called_once_with()
        self.library._update_ssc_info.assert_called_once_with()
        self.assertEqual(fake_stats, actual)

    def test_update_volume_stats_provisioning(self):
        """Validate pool capacity calculations"""
        fake_pool = copy.deepcopy(eseries_fake.STORAGE_POOL)
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.library._get_storage_pools = mock.Mock(return_value=[fake_pool])
        self.mock_object(self.library, '_ssc_stats',
                         {fake_pool["volumeGroupRef"]: {
                             self.library.THIN_UQ_SPEC: True}})
        self.library.configuration = mock.Mock()
        reserved_pct = 5
        over_subscription_ratio = 1.0
        self.library.configuration.max_over_subscription_ratio = (
            over_subscription_ratio)
        self.library.configuration.reserved_percentage = reserved_pct
        total_gb = int(fake_pool['totalRaidedSpace']) / units.Gi
        used_gb = int(fake_pool['usedSpace']) / units.Gi
        free_gb = total_gb - used_gb
        provisioned_gb = int(fake_eseries_volume['capacity']) * 10 / units.Gi

        # Testing with 10 fake volumes
        self.library._client.list_volumes = mock.Mock(
            return_value=[eseries_fake.VOLUME for _ in range(10)])

        self.library._update_volume_stats()

        self.assertEqual(1, len(self.library._stats['pools']))
        pool_stats = self.library._stats['pools'][0]
        self.assertEqual(fake_pool['label'], pool_stats.get('pool_name'))
        self.assertEqual(reserved_pct, pool_stats['reserved_percentage'])
        self.assertEqual(over_subscription_ratio,
                         pool_stats['max_over_subscription_ratio'])
        self.assertEqual(total_gb, pool_stats.get('total_capacity_gb'))
        self.assertEqual(provisioned_gb,
                         pool_stats.get('provisioned_capacity_gb'))
        self.assertEqual(free_gb, pool_stats.get('free_capacity_gb'))

    @ddt.data(False, True)
    def test_update_volume_stats_thin_provisioning(self, thin_provisioning):
        """Validate that thin provisioning support is correctly reported"""
        fake_pool = copy.deepcopy(eseries_fake.STORAGE_POOL)
        self.library._get_storage_pools = mock.Mock(return_value=[fake_pool])
        self.mock_object(self.library, '_ssc_stats',
                         {fake_pool["volumeGroupRef"]: {
                             self.library.THIN_UQ_SPEC: thin_provisioning}})

        self.library._update_volume_stats()

        self.assertEqual(1, len(self.library._stats['pools']))
        pool_stats = self.library._stats['pools'][0]
        self.assertEqual(thin_provisioning, pool_stats.get(
            'thin_provisioning_support'))
        # Should always be True
        self.assertTrue(pool_stats.get('thick_provisioning_support'))

    def test_update_volume_stats_ssc(self):
        """Ensure that the SSC data is correctly reported in the pool stats"""
        ssc = {self.library.THIN_UQ_SPEC: True, 'key': 'val'}
        fake_pool = copy.deepcopy(eseries_fake.STORAGE_POOL)
        self.library._get_storage_pools = mock.Mock(return_value=[fake_pool])
        self.mock_object(self.library, '_ssc_stats',
                         {fake_pool["volumeGroupRef"]: ssc})

        self.library._update_volume_stats()

        self.assertEqual(1, len(self.library._stats['pools']))
        pool_stats = self.library._stats['pools'][0]
        for key in ssc:
            self.assertIn(key, pool_stats)
            self.assertEqual(ssc[key], pool_stats[key])

    def test_update_volume_stats_no_ssc(self):
        """Ensure that pool stats are correctly reported without SSC"""
        fake_pool = copy.deepcopy(eseries_fake.STORAGE_POOL)
        self.library._get_storage_pools = mock.Mock(return_value=[fake_pool])
        self.library._update_volume_stats()

        self.assertEqual(1, len(self.library._stats['pools']))
        pool_stats = self.library._stats['pools'][0]
        self.assertFalse(pool_stats.get('thin_provisioning_support'))
        # Should always be True
        self.assertTrue(pool_stats.get('thick_provisioning_support'))

    def test_terminate_connection_iscsi_no_hosts(self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}

        self.mock_object(self.library._client, 'list_hosts', return_value=[])

        self.assertRaises(exception.NotFound,
                          self.library.terminate_connection_iscsi,
                          get_fake_volume(),
                          connector)

    def test_terminate_connection_iscsi_volume_not_mapped(self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        volume = copy.deepcopy(eseries_fake.VOLUME)
        volume['listOfMappings'] = []
        self.library._get_volume = mock.Mock(return_value=volume)
        self.assertRaises(eseries_exc.VolumeNotMapped,
                          self.library.terminate_connection_iscsi,
                          get_fake_volume(),
                          connector)

    def test_terminate_connection_iscsi_volume_mapped(self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        fake_eseries_volume['listOfMappings'] = [
            eseries_fake.VOLUME_MAPPING
        ]
        self.mock_object(self.library._client, 'list_volume',
                         return_value=fake_eseries_volume)
        self.mock_object(host_mapper, 'unmap_volume_from_host')

        self.library.terminate_connection_iscsi(get_fake_volume(), connector)

        self.assertTrue(host_mapper.unmap_volume_from_host.called)

    def test_terminate_connection_iscsi_not_mapped_initiator_does_not_exist(
            self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        self.mock_object(self.library._client, 'list_hosts',
                         return_value=[eseries_fake.HOST_2])
        self.assertRaises(exception.NotFound,
                          self.library.terminate_connection_iscsi,
                          get_fake_volume(),
                          connector)

    def test_initialize_connection_iscsi_volume_not_mapped(self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         return_value=[])
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        fake_eseries_volume['listOfMappings'] = [
            eseries_fake.VOLUME_MAPPING
        ]
        self.mock_object(self.library._client, 'list_volume',
                         return_value=fake_eseries_volume)

        self.library.initialize_connection_iscsi(get_fake_volume(), connector)

        self.assertTrue(
            self.library._client.get_volume_mappings_for_volume.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_iscsi_without_chap(self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         return_value=[])
        self.mock_object(host_mapper,
                         'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)
        mock_configure_chap = self.mock_object(self.library, '_configure_chap')

        self.library.initialize_connection_iscsi(get_fake_volume(), connector)

        self.assertTrue(
            self.library._client.get_volume_mappings_for_volume.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)
        self.assertFalse(mock_configure_chap.called)

    def test_initialize_connection_iscsi_volume_not_mapped_host_does_not_exist(
            self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         return_value=[])
        self.mock_object(self.library._client, 'list_hosts', return_value=[])
        self.mock_object(self.library._client, 'create_host_with_ports',
                         return_value=eseries_fake.HOST)
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        fake_eseries_volume['listOfMappings'] = [
            eseries_fake.VOLUME_MAPPING
        ]
        self.mock_object(self.library._client, 'list_volume',
                         return_value=fake_eseries_volume)

        self.library.initialize_connection_iscsi(get_fake_volume(), connector)

        self.assertTrue(
            self.library._client.get_volume_mappings_for_volume.called)
        self.assertTrue(self.library._client.list_hosts.called)
        self.assertTrue(self.library._client.create_host_with_ports.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_iscsi_volume_already_mapped_to_target_host(
            self):
        """Should be a no-op"""
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.mock_object(self.library._client, 'list_volume',
                         return_value=fake_eseries_volume)

        self.library.initialize_connection_iscsi(get_fake_volume(), connector)

        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_iscsi_volume_mapped_to_another_host(self):
        """Should raise error saying multiattach not enabled"""
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        fake_mapping_to_other_host = copy.deepcopy(
            eseries_fake.VOLUME_MAPPING)
        fake_mapping_to_other_host['mapRef'] = eseries_fake.HOST_2[
            'hostRef']
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         side_effect=exception.NetAppDriverException)

        self.assertRaises(exception.NetAppDriverException,
                          self.library.initialize_connection_iscsi,
                          get_fake_volume(), connector)

        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    @ddt.data(eseries_fake.WWPN,
              fczm_utils.get_formatted_wwn(eseries_fake.WWPN))
    def test_get_host_with_matching_port_wwpn(self, port_id):
        port_ids = [port_id]
        host = copy.deepcopy(eseries_fake.HOST)
        host.update(
            {
                'hostSidePorts': [{'label': 'NewStore', 'type': 'fc',
                                   'address': eseries_fake.WWPN}]
            }
        )
        host_2 = copy.deepcopy(eseries_fake.HOST_2)
        host_2.update(
            {
                'hostSidePorts': [{'label': 'NewStore', 'type': 'fc',
                                   'address': eseries_fake.WWPN_2}]
            }
        )
        host_list = [host, host_2]
        self.mock_object(self.library._client,
                         'list_hosts',
                         return_value=host_list)

        actual_host = self.library._get_host_with_matching_port(
            port_ids)

        self.assertEqual(host, actual_host)

    def test_get_host_with_matching_port_iqn(self):
        port_ids = [eseries_fake.INITIATOR_NAME]
        host = copy.deepcopy(eseries_fake.HOST)
        host.update(
            {
                'hostSidePorts': [{'label': 'NewStore', 'type': 'iscsi',
                                   'address': eseries_fake.INITIATOR_NAME}]
            }
        )
        host_2 = copy.deepcopy(eseries_fake.HOST_2)
        host_2.update(
            {
                'hostSidePorts': [{'label': 'NewStore', 'type': 'iscsi',
                                   'address': eseries_fake.INITIATOR_NAME_2}]
            }
        )
        host_list = [host, host_2]
        self.mock_object(self.library._client,
                         'list_hosts',
                         return_value=host_list)

        actual_host = self.library._get_host_with_matching_port(
            port_ids)

        self.assertEqual(host, actual_host)

    def test_terminate_connection_fc_no_hosts(self):
        connector = {'wwpns': [eseries_fake.WWPN]}

        self.mock_object(self.library._client, 'list_hosts',
                         return_value=[])

        self.assertRaises(exception.NotFound,
                          self.library.terminate_connection_fc,
                          get_fake_volume(),
                          connector)

    def test_terminate_connection_fc_volume_not_mapped(self):
        connector = {'wwpns': [eseries_fake.WWPN]}
        fake_host = copy.deepcopy(eseries_fake.HOST)
        fake_host['hostSidePorts'] = [{
            'label': 'NewStore',
            'type': 'fc',
            'address': eseries_fake.WWPN
        }]
        volume = copy.deepcopy(eseries_fake.VOLUME)
        volume['listOfMappings'] = []
        self.mock_object(self.library, '_get_volume', return_value=volume)

        self.mock_object(self.library._client, 'list_hosts',
                         return_value=[fake_host])

        self.assertRaises(eseries_exc.VolumeNotMapped,
                          self.library.terminate_connection_fc,
                          get_fake_volume(),
                          connector)

    def test_terminate_connection_fc_volume_mapped(self):
        connector = {'wwpns': [eseries_fake.WWPN]}
        fake_host = copy.deepcopy(eseries_fake.HOST)
        fake_host['hostSidePorts'] = [{
            'label': 'NewStore',
            'type': 'fc',
            'address': eseries_fake.WWPN
        }]
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        fake_eseries_volume['listOfMappings'] = [
            copy.deepcopy(eseries_fake.VOLUME_MAPPING)
        ]
        self.mock_object(self.library._client, 'list_hosts',
                         return_value=[fake_host])
        self.mock_object(self.library._client, 'list_volume',
                         return_value=fake_eseries_volume)
        self.mock_object(host_mapper, 'unmap_volume_from_host')

        self.library.terminate_connection_fc(get_fake_volume(), connector)

        self.assertTrue(host_mapper.unmap_volume_from_host.called)

    def test_terminate_connection_fc_volume_mapped_no_cleanup_zone(self):
        connector = {'wwpns': [eseries_fake.WWPN]}
        fake_host = copy.deepcopy(eseries_fake.HOST)
        fake_host['hostSidePorts'] = [{
            'label': 'NewStore',
            'type': 'fc',
            'address': eseries_fake.WWPN
        }]
        expected_target_info = {
            'driver_volume_type': 'fibre_channel',
            'data': {},
        }
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        fake_eseries_volume['listOfMappings'] = [
            copy.deepcopy(eseries_fake.VOLUME_MAPPING)
        ]
        self.mock_object(self.library._client, 'list_hosts',
                         return_value=[fake_host])
        self.mock_object(self.library._client, 'list_volume',
                         return_value=fake_eseries_volume)
        self.mock_object(host_mapper, 'unmap_volume_from_host')
        self.mock_object(self.library._client, 'get_volume_mappings_for_host',
                         return_value=[
                             copy.deepcopy(eseries_fake.VOLUME_MAPPING)])

        target_info = self.library.terminate_connection_fc(get_fake_volume(),
                                                           connector)
        self.assertDictEqual(expected_target_info, target_info)

        self.assertTrue(host_mapper.unmap_volume_from_host.called)

    def test_terminate_connection_fc_volume_mapped_cleanup_zone(self):
        connector = {'wwpns': [eseries_fake.WWPN]}
        fake_host = copy.deepcopy(eseries_fake.HOST)
        fake_host['hostSidePorts'] = [{
            'label': 'NewStore',
            'type': 'fc',
            'address': eseries_fake.WWPN
        }]
        expected_target_info = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_wwn': [eseries_fake.WWPN_2],
                'initiator_target_map': {
                    eseries_fake.WWPN: [eseries_fake.WWPN_2]
                },
            },
        }
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        fake_eseries_volume['listOfMappings'] = [
            copy.deepcopy(eseries_fake.VOLUME_MAPPING)
        ]
        self.mock_object(self.library._client, 'list_hosts',
                         return_value=[fake_host])
        self.mock_object(self.library._client, 'list_volume',
                         return_value=fake_eseries_volume)
        self.mock_object(host_mapper, 'unmap_volume_from_host')
        self.mock_object(self.library._client, 'get_volume_mappings_for_host',
                         return_value=[])

        target_info = self.library.terminate_connection_fc(get_fake_volume(),
                                                           connector)
        self.assertDictEqual(expected_target_info, target_info)

        self.assertTrue(host_mapper.unmap_volume_from_host.called)

    def test_terminate_connection_fc_not_mapped_host_with_wwpn_does_not_exist(
            self):
        connector = {'wwpns': [eseries_fake.WWPN]}
        self.mock_object(self.library._client, 'list_hosts',
                         return_value=[eseries_fake.HOST_2])
        self.assertRaises(exception.NotFound,
                          self.library.terminate_connection_fc,
                          get_fake_volume(),
                          connector)

    def test_initialize_connection_fc_volume_not_mapped(self):
        connector = {'wwpns': [eseries_fake.WWPN]}
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         return_value=[])
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)
        expected_target_info = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_discovered': True,
                'target_lun': 1,
                'target_wwn': [eseries_fake.WWPN_2],
                'initiator_target_map': {
                    eseries_fake.WWPN: [eseries_fake.WWPN_2]
                },
            },
        }

        target_info = self.library.initialize_connection_fc(get_fake_volume(),
                                                            connector)

        self.assertTrue(
            self.library._client.get_volume_mappings_for_volume.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)
        self.assertDictEqual(expected_target_info, target_info)

    def test_initialize_connection_fc_volume_not_mapped_host_does_not_exist(
            self):
        connector = {'wwpns': [eseries_fake.WWPN]}
        self.library.driver_protocol = 'FC'
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         return_value=[])
        self.mock_object(self.library._client, 'list_hosts',
                         return_value=[])
        self.mock_object(self.library._client, 'create_host_with_ports',
                         return_value=eseries_fake.HOST)
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)

        self.library.initialize_connection_fc(get_fake_volume(), connector)

        self.library._client.create_host_with_ports.assert_called_once_with(
            mock.ANY, mock.ANY,
            [fczm_utils.get_formatted_wwn(eseries_fake.WWPN)],
            port_type='fc', group_id=None
        )

    def test_initialize_connection_fc_volume_already_mapped_to_target_host(
            self):
        """Should be a no-op"""
        connector = {'wwpns': [eseries_fake.WWPN]}
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)

        self.library.initialize_connection_fc(get_fake_volume(), connector)

        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_fc_volume_mapped_to_another_host(self):
        """Should raise error saying multiattach not enabled"""
        connector = {'wwpns': [eseries_fake.WWPN]}
        fake_mapping_to_other_host = copy.deepcopy(
            eseries_fake.VOLUME_MAPPING)
        fake_mapping_to_other_host['mapRef'] = eseries_fake.HOST_2[
            'hostRef']
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         side_effect=exception.NetAppDriverException)

        self.assertRaises(exception.NetAppDriverException,
                          self.library.initialize_connection_fc,
                          get_fake_volume(), connector)

        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_fc_no_target_wwpns(self):
        """Should be a no-op"""
        connector = {'wwpns': [eseries_fake.WWPN]}
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)
        self.mock_object(self.library._client, 'list_target_wwpns',
                         return_value=[])

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.library.initialize_connection_fc,
                          get_fake_volume(), connector)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_build_initiator_target_map_fc_with_lookup_service(
            self):
        connector = {'wwpns': [eseries_fake.WWPN, eseries_fake.WWPN_2]}
        self.library.lookup_service = mock.Mock()
        self.library.lookup_service.get_device_mapping_from_network = (
            mock.Mock(return_value=eseries_fake.FC_FABRIC_MAP))

        (target_wwpns, initiator_target_map, num_paths) = (
            self.library._build_initiator_target_map_fc(connector))

        self.assertSetEqual(set(eseries_fake.FC_TARGET_WWPNS),
                            set(target_wwpns))
        self.assertDictEqual(eseries_fake.FC_I_T_MAP, initiator_target_map)
        self.assertEqual(4, num_paths)

    @ddt.data(('raid0', 'raid0'), ('raid1', 'raid1'), ('raid3', 'raid5'),
              ('raid5', 'raid5'), ('raid6', 'raid6'), ('raidDiskPool', 'DDP'))
    @ddt.unpack
    def test_update_ssc_raid_type(self, raid_lvl, raid_lvl_mapping):
        pools = [{'volumeGroupRef': 'test_vg1', 'raidLevel': raid_lvl}]
        self.library._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_raid_type(pools)

        self.assertEqual({'test_vg1': {'netapp_raid_type': raid_lvl_mapping}},
                         ssc_stats)

    @ddt.data('raidAll', '__UNDEFINED', 'unknown',
              'raidUnsupported', 'garbage')
    def test_update_ssc_raid_type_invalid(self, raid_lvl):
        pools = [{'volumeGroupRef': 'test_vg1', 'raidLevel': raid_lvl}]
        self.library._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_raid_type(pools)

        self.assertEqual({'test_vg1': {'netapp_raid_type': 'unknown'}},
                         ssc_stats)

    def test_create_asup(self):
        self.library._client = mock.Mock()
        self.library._client.features.AUTOSUPPORT = na_utils.FeatureState()
        self.library._client.api_operating_mode = (
            eseries_fake.FAKE_ASUP_DATA['operating-mode'])
        self.library._app_version = eseries_fake.FAKE_APP_VERSION
        self.mock_object(
            self.library._client, 'get_asup_info',
            return_value=eseries_fake.GET_ASUP_RETURN)
        self.mock_object(
            self.library._client, 'set_counter', return_value={'value': 1})
        mock_invoke = self.mock_object(
            self.library._client, 'add_autosupport_data')

        self.library._create_asup(eseries_fake.FAKE_CINDER_HOST)

        mock_invoke.assert_called_with(eseries_fake.FAKE_KEY,
                                       eseries_fake.FAKE_ASUP_DATA)

    def test_create_asup_not_supported(self):
        self.library._client = mock.Mock()
        self.library._client.features.AUTOSUPPORT = na_utils.FeatureState(
            supported=False)
        mock_invoke = self.mock_object(
            self.library._client, 'add_autosupport_data')

        self.library._create_asup(eseries_fake.FAKE_CINDER_HOST)

        mock_invoke.assert_not_called()

    @mock.patch.object(library, 'LOG', mock.Mock())
    def test_create_volume_fail_clean(self):
        """Test volume creation fail w/o a partial volume being created.

        Test the failed creation of a volume where a partial volume with
        the name has not been created, thus no cleanup is required.
        """
        self.library._get_volume = mock.Mock(
            side_effect = exception.VolumeNotFound(message=''))
        self.library._client.create_volume = mock.Mock(
            side_effect = exception.NetAppDriverException)
        self.library._client.delete_volume = mock.Mock()
        fake_volume = copy.deepcopy(get_fake_volume())

        self.assertRaises(exception.NetAppDriverException,
                          self.library.create_volume, fake_volume)

        self.assertTrue(self.library._get_volume.called)
        self.assertFalse(self.library._client.delete_volume.called)
        self.assertEqual(1, library.LOG.error.call_count)

    @mock.patch.object(library, 'LOG', mock.Mock())
    def test_create_volume_fail_dirty(self):
        """Test volume creation fail where a partial volume has been created.

        Test scenario where the creation of a volume fails and a partial
        volume is created with the name/id that was supplied by to the
        original creation call.  In this situation the partial volume should
        be detected and removed.
        """
        fake_volume = copy.deepcopy(get_fake_volume())
        self.library._get_volume = mock.Mock(return_value=fake_volume)
        self.library._client.list_volume = mock.Mock(return_value=fake_volume)
        self.library._client.create_volume = mock.Mock(
            side_effect = exception.NetAppDriverException)
        self.library._client.delete_volume = mock.Mock()

        self.assertRaises(exception.NetAppDriverException,
                          self.library.create_volume, fake_volume)

        self.assertTrue(self.library._get_volume.called)
        self.assertTrue(self.library._client.delete_volume.called)
        self.library._client.delete_volume.assert_called_once_with(
            fake_volume["id"])
        self.assertEqual(1, library.LOG.error.call_count)

    @mock.patch.object(library, 'LOG', mock.Mock())
    def test_create_volume_fail_dirty_fail_delete(self):
        """Volume creation fail with partial volume deletion fails

        Test scenario where the creation of a volume fails and a partial
        volume is created with the name/id that was supplied by to the
        original creation call. The partial volume is detected but when
        the cleanup deletetion of that fragment volume is attempted it fails.
        """
        fake_volume = copy.deepcopy(get_fake_volume())
        self.library._get_volume = mock.Mock(return_value=fake_volume)
        self.library._client.list_volume = mock.Mock(return_value=fake_volume)
        self.library._client.create_volume = mock.Mock(
            side_effect = exception.NetAppDriverException)
        self.library._client.delete_volume = mock.Mock(
            side_effect = exception.NetAppDriverException)

        self.assertRaises(exception.NetAppDriverException,
                          self.library.create_volume, fake_volume)

        self.assertTrue(self.library._get_volume.called)
        self.assertTrue(self.library._client.delete_volume.called)
        self.library._client.delete_volume.assert_called_once_with(
            fake_volume["id"])
        self.assertEqual(2, library.LOG.error.call_count)

    def test_create_consistencygroup(self):
        fake_cg = copy.deepcopy(eseries_fake.FAKE_CINDER_CG)
        expected = {'status': 'available'}
        create_cg = self.mock_object(self.library,
                                     '_create_consistency_group',
                                     return_value=expected)

        actual = self.library.create_consistencygroup(fake_cg)

        create_cg.assert_called_once_with(fake_cg)
        self.assertEqual(expected, actual)

    def test_create_consistency_group(self):
        fake_cg = copy.deepcopy(eseries_fake.FAKE_CINDER_CG)
        expected = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        create_cg = self.mock_object(self.library._client,
                                     'create_consistency_group',
                                     return_value=expected)

        result = self.library._create_consistency_group(fake_cg)

        name = utils.convert_uuid_to_es_fmt(fake_cg['id'])
        create_cg.assert_called_once_with(name)
        self.assertEqual(expected, result)

    def test_delete_consistencygroup(self):
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        fake_cg = copy.deepcopy(eseries_fake.FAKE_CINDER_CG)
        volumes = [get_fake_volume()] * 3
        model_update = {'status': 'deleted'}
        volume_update = [{'status': 'deleted', 'id': vol['id']} for vol in
                         volumes]
        delete_cg = self.mock_object(self.library._client,
                                     'delete_consistency_group')
        updt_index = self.mock_object(
            self.library, '_merge_soft_delete_changes')
        delete_vol = self.mock_object(self.library, 'delete_volume')
        self.mock_object(self.library, '_get_consistencygroup',
                         return_value=cg)

        result = self.library.delete_consistencygroup(fake_cg, volumes)

        self.assertEqual(len(volumes), delete_vol.call_count)
        delete_cg.assert_called_once_with(cg['id'])
        self.assertEqual((model_update, volume_update), result)
        updt_index.assert_called_once_with(None, [cg['id']])

    def test_delete_consistencygroup_index_update_failure(self):
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        fake_cg = copy.deepcopy(eseries_fake.FAKE_CINDER_CG)
        volumes = [get_fake_volume()] * 3
        model_update = {'status': 'deleted'}
        volume_update = [{'status': 'deleted', 'id': vol['id']} for vol in
                         volumes]
        delete_cg = self.mock_object(self.library._client,
                                     'delete_consistency_group')
        delete_vol = self.mock_object(self.library, 'delete_volume')
        self.mock_object(self.library, '_get_consistencygroup',
                         return_value=cg)

        result = self.library.delete_consistencygroup(fake_cg, volumes)

        self.assertEqual(len(volumes), delete_vol.call_count)
        delete_cg.assert_called_once_with(cg['id'])
        self.assertEqual((model_update, volume_update), result)

    def test_delete_consistencygroup_not_found(self):
        fake_cg = copy.deepcopy(eseries_fake.FAKE_CINDER_CG)
        delete_cg = self.mock_object(self.library._client,
                                     'delete_consistency_group')
        updt_index = self.mock_object(
            self.library, '_merge_soft_delete_changes')
        delete_vol = self.mock_object(self.library, 'delete_volume')
        exc = exception.ConsistencyGroupNotFound(consistencygroup_id='')
        self.mock_object(self.library, '_get_consistencygroup',
                         side_effect=exc)

        self.library.delete_consistencygroup(fake_cg, [])

        delete_cg.assert_not_called()
        delete_vol.assert_not_called()
        updt_index.assert_not_called()

    def test_get_consistencygroup(self):
        fake_cg = copy.deepcopy(eseries_fake.FAKE_CINDER_CG)
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        name = utils.convert_uuid_to_es_fmt(fake_cg['id'])
        cg['name'] = name
        list_cgs = self.mock_object(self.library._client,
                                    'list_consistency_groups',
                                    return_value=[cg])

        result = self.library._get_consistencygroup(fake_cg)

        self.assertEqual(cg, result)
        list_cgs.assert_called_once_with()

    def test_get_consistencygroup_not_found(self):
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        list_cgs = self.mock_object(self.library._client,
                                    'list_consistency_groups',
                                    return_value=[cg])

        self.assertRaises(exception.ConsistencyGroupNotFound,
                          self.library._get_consistencygroup,
                          copy.deepcopy(eseries_fake.FAKE_CINDER_CG))

        list_cgs.assert_called_once_with()

    def test_update_consistencygroup(self):
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        fake_cg = copy.deepcopy(eseries_fake.FAKE_CINDER_CG)
        vol = copy.deepcopy(eseries_fake.VOLUME)
        volumes = [get_fake_volume()] * 3
        self.mock_object(
            self.library, '_get_volume', return_value=vol)
        self.mock_object(self.library, '_get_consistencygroup',
                         return_value=cg)

        self.library.update_consistencygroup(fake_cg, volumes, volumes)

    def test_create_consistencygroup_from_src(self):
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        fake_cg = copy.deepcopy(eseries_fake.FAKE_CINDER_CG)
        volumes = [cinder_utils.create_volume(self.ctxt) for i in range(3)]
        src_volumes = [cinder_utils.create_volume(self.ctxt) for v in volumes]
        update_cg = self.mock_object(
            self.library, '_update_consistency_group_members')
        create_cg = self.mock_object(
            self.library, '_create_consistency_group', return_value=cg)
        self.mock_object(
            self.library, '_create_volume_from_snapshot')

        self.mock_object(self.library, '_get_snapshot', return_value=snap)

        self.library.create_consistencygroup_from_src(
            fake_cg, volumes, None, None, None, src_volumes)

        create_cg.assert_called_once_with(fake_cg)
        update_cg.assert_called_once_with(cg, volumes, [])

    def test_create_consistencygroup_from_src_cgsnapshot(self):
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        fake_cg = copy.deepcopy(eseries_fake.FAKE_CINDER_CG)
        fake_vol = cinder_utils.create_volume(self.ctxt)
        cgsnap = copy.deepcopy(eseries_fake.FAKE_CINDER_CG_SNAPSHOT)
        volumes = [fake_vol]
        snapshots = [cinder_utils.create_snapshot(self.ctxt, v['id']) for v
                     in volumes]
        update_cg = self.mock_object(
            self.library, '_update_consistency_group_members')
        create_cg = self.mock_object(
            self.library, '_create_consistency_group', return_value=cg)
        clone_vol = self.mock_object(
            self.library, '_create_volume_from_snapshot')

        self.library.create_consistencygroup_from_src(
            fake_cg, volumes, cgsnap, snapshots, None, None)

        create_cg.assert_called_once_with(fake_cg)
        update_cg.assert_called_once_with(cg, volumes, [])
        self.assertEqual(clone_vol.call_count, len(volumes))

    @ddt.data({'consistencyGroupId': utils.NULL_REF},
              {'consistencyGroupId': None}, {'consistencyGroupId': '1'}, {})
    def test_is_cgsnapshot(self, snapshot_image):
        if snapshot_image.get('consistencyGroupId'):
            result = not (utils.NULL_REF == snapshot_image[
                'consistencyGroupId'])
        else:
            result = False

        actual = self.library._is_cgsnapshot(snapshot_image)

        self.assertEqual(result, actual)

    def test_add_volume_to_consistencygroup(self):
        fake_volume = cinder_utils.create_volume(self.ctxt)
        fake_volume['consistencygroup'] = (
            cinder_utils.create_consistencygroup(self.ctxt))
        fake_volume['consistencygroup_id'] = fake_volume[
            'consistencygroup']['id']
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        self.mock_object(self.library, '_get_consistencygroup',
                         return_value=cg)
        update_members = self.mock_object(self.library,
                                          '_update_consistency_group_members')

        self.library._add_volume_to_consistencygroup(fake_volume)

        update_members.assert_called_once_with(cg, [fake_volume], [])

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall', new=
                cinder_utils.ZeroIntervalLoopingCall)
    def test_copy_volume_high_priority_readonly(self):
        src_vol = copy.deepcopy(eseries_fake.VOLUME)
        dst_vol = copy.deepcopy(eseries_fake.VOLUME)
        vc = copy.deepcopy(eseries_fake.VOLUME_COPY_JOB)
        self.mock_object(self.library._client, 'create_volume_copy_job',
                         return_value=vc)
        self.mock_object(self.library._client, 'list_vol_copy_job',
                         return_value=vc)
        delete_copy = self.mock_object(self.library._client,
                                       'delete_vol_copy_job')

        result = self.library._copy_volume_high_priority_readonly(
            src_vol, dst_vol)

        self.assertIsNone(result)
        delete_copy.assert_called_once_with(vc['volcopyRef'])

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall', new=
                cinder_utils.ZeroIntervalLoopingCall)
    def test_copy_volume_high_priority_readonly_job_create_failure(self):
        src_vol = copy.deepcopy(eseries_fake.VOLUME)
        dst_vol = copy.deepcopy(eseries_fake.VOLUME)
        self.mock_object(self.library._client, 'create_volume_copy_job',
                         side_effect=exception.NetAppDriverException)

        self.assertRaises(
            exception.NetAppDriverException,
            self.library._copy_volume_high_priority_readonly, src_vol,
            dst_vol)


@ddt.ddt
class NetAppEseriesLibraryMultiAttachTestCase(test.TestCase):
    """Test driver when netapp_enable_multiattach is enabled.

    Test driver behavior when the netapp_enable_multiattach configuration
    option is True.
    """

    def setUp(self):
        super(NetAppEseriesLibraryMultiAttachTestCase, self).setUp()
        config = eseries_fake.create_configuration_eseries()
        config.netapp_enable_multiattach = True

        kwargs = {'configuration': config}

        self.library = library.NetAppESeriesLibrary("FAKE", **kwargs)
        self.library._client = eseries_fake.FakeEseriesClient()

        self.mock_object(library.cinder_utils, 'synchronized',
                         return_value=lambda f: f)
        self.mock_object(self.library, '_start_periodic_tasks')

        self.ctxt = context.get_admin_context()

        with mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                        new = cinder_utils.ZeroIntervalLoopingCall):
            self.library.check_for_setup_error()

    def test_do_setup_host_group_already_exists(self):
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        self.mock_object(self.library,
                         '_check_mode_get_or_register_storage_system')
        fake_rest_client = eseries_fake.FakeEseriesClient()
        self.mock_object(self.library, '_create_rest_client',
                         return_value=fake_rest_client)
        mock_create = self.mock_object(fake_rest_client, 'create_host_group')

        self.library.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        self.assertFalse(mock_create.call_count)

    def test_do_setup_host_group_does_not_exist(self):
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        fake_rest_client = eseries_fake.FakeEseriesClient()
        self.mock_object(self.library, '_create_rest_client',
                         return_value=fake_rest_client)
        mock_get_host_group = self.mock_object(
            fake_rest_client, "get_host_group_by_name",
            side_effect=exception.NotFound)
        self.mock_object(self.library,
                         '_check_mode_get_or_register_storage_system')

        self.library.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        self.assertTrue(mock_get_host_group.call_count)

    def test_create_volume(self):
        self.library._client.create_volume = mock.Mock(
            return_value=eseries_fake.VOLUME)
        update_members = self.mock_object(self.library,
                                          '_update_consistency_group_members')

        self.library.create_volume(get_fake_volume())
        self.assertTrue(self.library._client.create_volume.call_count)

        update_members.assert_not_called()

    @ddt.data(('netapp_eseries_flash_read_cache', 'flash_cache', 'true'),
              ('netapp_eseries_flash_read_cache', 'flash_cache', 'false'),
              ('netapp_eseries_flash_read_cache', 'flash_cache', None),
              ('netapp_thin_provisioned', 'thin_provision', 'true'),
              ('netapp_thin_provisioned', 'thin_provision', 'false'),
              ('netapp_thin_provisioned', 'thin_provision', None),
              ('netapp_eseries_data_assurance', 'data_assurance', 'true'),
              ('netapp_eseries_data_assurance', 'data_assurance', 'false'),
              ('netapp_eseries_data_assurance', 'data_assurance', None),
              ('netapp:write_cache', 'write_cache', 'true'),
              ('netapp:write_cache', 'write_cache', 'false'),
              ('netapp:write_cache', 'write_cache', None),
              ('netapp:read_cache', 'read_cache', 'true'),
              ('netapp:read_cache', 'read_cache', 'false'),
              ('netapp:read_cache', 'read_cache', None),
              ('netapp_eseries_flash_read_cache', 'flash_cache', 'True'),
              ('netapp_eseries_flash_read_cache', 'flash_cache', '1'),
              ('netapp_eseries_data_assurance', 'data_assurance', ''))
    @ddt.unpack
    def test_create_volume_with_extra_spec(self, spec, key, value):
        fake_volume = get_fake_volume()
        extra_specs = {spec: value}
        volume = copy.deepcopy(eseries_fake.VOLUME)

        self.library._client.create_volume = mock.Mock(
            return_value=volume)
        # Make this utility method return our extra spec
        mocked_spec_method = self.mock_object(na_utils,
                                              'get_volume_extra_specs')
        mocked_spec_method.return_value = extra_specs

        self.library.create_volume(fake_volume)

        self.assertEqual(1, self.library._client.create_volume.call_count)
        # Ensure create_volume is called with the correct argument
        args, kwargs = self.library._client.create_volume.call_args
        self.assertIn(key, kwargs)
        if(value is not None):
            expected = na_utils.to_bool(value)
        else:
            expected = value
        self.assertEqual(expected, kwargs[key])

    def test_create_volume_too_many_volumes(self):
        self.library._client.list_volumes = mock.Mock(
            return_value=[eseries_fake.VOLUME for __ in
                          range(utils.MAX_LUNS_PER_HOST_GROUP + 1)])
        self.library._client.create_volume = mock.Mock(
            return_value=eseries_fake.VOLUME)

        self.assertRaises(exception.NetAppDriverException,
                          self.library.create_volume,
                          get_fake_volume())
        self.assertFalse(self.library._client.create_volume.call_count)

    @ddt.data(0, 1, 2)
    def test_create_snapshot(self, group_count):
        """Successful Snapshot creation test"""
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.library._get_volume = mock.Mock(return_value=fake_eseries_volume)
        fake_pool = copy.deepcopy(eseries_fake.STORAGE_POOL)
        self.library._get_storage_pools = mock.Mock(return_value=[fake_pool])
        fake_cinder_snapshot = copy.deepcopy(
            eseries_fake.FAKE_CINDER_SNAPSHOT)
        fake_snapshot_group_list = eseries_fake.list_snapshot_groups(
            group_count)
        fake_snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        fake_snapshot_image = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        self.library._client.create_snapshot_group = mock.Mock(
            return_value=fake_snapshot_group)
        self.library._client.list_snapshot_groups = mock.Mock(
            return_value=fake_snapshot_group_list)
        self.library._client.create_snapshot_image = mock.Mock(
            return_value=fake_snapshot_image)

        self.library.create_snapshot(fake_cinder_snapshot)

    @ddt.data(0, 1, 3)
    def test_create_cloned_volume(self, snapshot_group_count):
        """Test creating cloned volume with different exist group counts. """
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.library._get_volume = mock.Mock(return_value=fake_eseries_volume)
        fake_pool = copy.deepcopy(eseries_fake.STORAGE_POOL)
        self.library._get_storage_pools = mock.Mock(return_value=[fake_pool])
        fake_snapshot_group_list = eseries_fake.list_snapshot_groups(
            snapshot_group_count)
        self.library._client.list_snapshot_groups = mock.Mock(
            return_value=fake_snapshot_group_list)
        fake_snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        self.library._client.create_snapshot_group = mock.Mock(
            return_value=fake_snapshot_group)
        fake_snapshot_image = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        self.library._client.create_snapshot_image = mock.Mock(
            return_value=fake_snapshot_image)
        self.library._get_snapshot_group_for_snapshot = mock.Mock(
            return_value=copy.deepcopy(eseries_fake.SNAPSHOT_GROUP))
        fake_created_volume = copy.deepcopy(eseries_fake.VOLUMES[1])
        self.library.create_volume_from_snapshot = mock.Mock(
            return_value = fake_created_volume)
        fake_cinder_volume = copy.deepcopy(eseries_fake.FAKE_CINDER_VOLUME)
        extend_vol = {'id': uuid.uuid4(), 'size': 10}
        self.mock_object(self.library, '_create_volume_from_snapshot')

        self.library.create_cloned_volume(extend_vol, fake_cinder_volume)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new = cinder_utils.ZeroIntervalLoopingCall)
    def test_create_volume_from_snapshot(self):
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        fake_snap = copy.deepcopy(eseries_fake.FAKE_CINDER_SNAPSHOT)
        self.mock_object(self.library, "_schedule_and_create_volume",
                         return_value=fake_eseries_volume)
        self.mock_object(self.library, "_get_snapshot",
                         return_value=copy.deepcopy(
                             eseries_fake.SNAPSHOT_IMAGE))

        self.library.create_volume_from_snapshot(
            get_fake_volume(), fake_snap)

        self.assertEqual(
            1, self.library._schedule_and_create_volume.call_count)

    def test_create_volume_from_snapshot_create_fails(self):
        fake_dest_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.mock_object(self.library, "_schedule_and_create_volume",
                         return_value=fake_dest_eseries_volume)
        self.mock_object(self.library._client, "delete_volume")
        self.mock_object(self.library._client, "delete_snapshot_volume")
        self.mock_object(self.library, "_get_snapshot",
                         return_value=copy.deepcopy(
                             eseries_fake.SNAPSHOT_IMAGE))
        self.mock_object(self.library._client, "create_snapshot_volume",
                         side_effect=exception.NetAppDriverException)

        self.assertRaises(exception.NetAppDriverException,
                          self.library.create_volume_from_snapshot,
                          get_fake_volume(),
                          fake_snapshot.fake_snapshot_obj(None))

        self.assertEqual(
            1, self.library._schedule_and_create_volume.call_count)
        # Ensure the volume we were going to copy to is cleaned up
        self.library._client.delete_volume.assert_called_once_with(
            fake_dest_eseries_volume['volumeRef'])

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new = cinder_utils.ZeroIntervalLoopingCall)
    def test_create_volume_from_snapshot_copy_job_fails(self):
        fake_dest_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.mock_object(self.library, "_schedule_and_create_volume",
                         return_value=fake_dest_eseries_volume)
        self.mock_object(self.library, "_create_snapshot_volume",
                         return_value=fake_dest_eseries_volume)
        self.mock_object(self.library._client, "delete_volume")
        self.mock_object(self.library, "_get_snapshot",
                         return_value=copy.deepcopy(
                             eseries_fake.SNAPSHOT_IMAGE))

        fake_failed_volume_copy_job = copy.deepcopy(
            eseries_fake.VOLUME_COPY_JOB)
        fake_failed_volume_copy_job['status'] = 'failed'
        self.mock_object(self.library._client,
                         "create_volume_copy_job",
                         return_value=fake_failed_volume_copy_job)
        self.mock_object(self.library._client,
                         "list_vol_copy_job",
                         return_value=fake_failed_volume_copy_job)

        self.assertRaises(exception.NetAppDriverException,
                          self.library.create_volume_from_snapshot,
                          get_fake_volume(),
                          fake_snapshot.fake_snapshot_obj(None))

        self.assertEqual(
            1, self.library._schedule_and_create_volume.call_count)
        # Ensure the volume we were going to copy to is cleaned up
        self.library._client.delete_volume.assert_called_once_with(
            fake_dest_eseries_volume['volumeRef'])

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new = cinder_utils.ZeroIntervalLoopingCall)
    def test_create_volume_from_snapshot_fail_to_delete_snapshot_volume(self):
        fake_dest_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        fake_dest_eseries_volume['volumeRef'] = 'fake_volume_ref'
        self.mock_object(self.library, "_schedule_and_create_volume",
                         return_value=fake_dest_eseries_volume)
        self.mock_object(self.library, "_get_snapshot",
                         return_value=copy.deepcopy(
                             eseries_fake.SNAPSHOT_IMAGE))
        self.mock_object(self.library, '_create_snapshot_volume',
                         return_value=copy.deepcopy(
                             eseries_fake.SNAPSHOT_VOLUME))
        self.mock_object(self.library, "_create_snapshot_volume",
                         return_value=copy.deepcopy(
                             eseries_fake.VOLUME))
        self.mock_object(self.library._client, "delete_snapshot_volume",
                         side_effect=exception.NetAppDriverException)
        self.mock_object(self.library._client, "delete_volume")

        self.library.create_volume_from_snapshot(
            get_fake_volume(), fake_snapshot.fake_snapshot_obj(None))

        self.assertEqual(
            1, self.library._schedule_and_create_volume.call_count)
        self.assertEqual(
            1, self.library._client.delete_snapshot_volume.call_count)
        # Ensure the volume we created is not cleaned up
        self.assertEqual(0, self.library._client.delete_volume.call_count)

    def test_create_snapshot_volume_cgsnap(self):
        image = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        grp = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        self.mock_object(self.library, '_get_snapshot_group', return_value=grp)
        expected = copy.deepcopy(eseries_fake.SNAPSHOT_VOLUME)
        self.mock_object(self.library, '_is_cgsnapshot', return_value=True)
        create_view = self.mock_object(
            self.library._client, 'create_cg_snapshot_view',
            return_value=expected)

        result = self.library._create_snapshot_volume(image)

        self.assertEqual(expected, result)
        create_view.assert_called_once_with(image['consistencyGroupId'],
                                            mock.ANY, image['id'])

    def test_create_snapshot_volume(self):
        image = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        grp = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        self.mock_object(self.library, '_get_snapshot_group', return_value=grp)
        expected = copy.deepcopy(eseries_fake.SNAPSHOT_VOLUME)
        self.mock_object(self.library, '_is_cgsnapshot', return_value=False)
        create_view = self.mock_object(
            self.library._client, 'create_snapshot_volume',
            return_value=expected)

        result = self.library._create_snapshot_volume(image)

        self.assertEqual(expected, result)
        create_view.assert_called_once_with(
            image['pitRef'], mock.ANY, image['baseVol'])

    def test_create_snapshot_group(self):
        label = 'label'

        vol = copy.deepcopy(eseries_fake.VOLUME)
        snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        snapshot_group['baseVolume'] = vol['id']
        get_call = self.mock_object(
            self.library, '_get_storage_pools', return_value=None)
        create_call = self.mock_object(
            self.library._client, 'create_snapshot_group',
            return_value=snapshot_group)

        actual = self.library._create_snapshot_group(label, vol)

        get_call.assert_not_called()
        create_call.assert_called_once_with(label, vol['id'], repo_percent=20)
        self.assertEqual(snapshot_group, actual)

    def test_create_snapshot_group_legacy_ddp(self):
        self.library._client.features.REST_1_3_RELEASE = False
        vol = copy.deepcopy(eseries_fake.VOLUME)
        pools = copy.deepcopy(eseries_fake.STORAGE_POOLS)
        pool = pools[-1]
        snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        snapshot_group['baseVolume'] = vol['id']
        vol['volumeGroupRef'] = pool['id']
        pool['raidLevel'] = 'raidDiskPool'
        get_call = self.mock_object(
            self.library, '_get_storage_pools', return_value=pools)
        create_call = self.mock_object(
            self.library._client, 'create_snapshot_group',
            return_value=snapshot_group)

        actual = self.library._create_snapshot_group('label', vol)

        create_call.assert_called_with('label', vol['id'],
                                       vol['volumeGroupRef'],
                                       repo_percent=mock.ANY)
        get_call.assert_called_once_with()
        self.assertEqual(snapshot_group, actual)

    def test_create_snapshot_group_legacy_vg(self):
        self.library._client.features.REST_1_3_RELEASE = False
        vol = copy.deepcopy(eseries_fake.VOLUME)
        vol_size_gb = int(vol['totalSizeInBytes']) / units.Gi
        pools = copy.deepcopy(eseries_fake.STORAGE_POOLS)
        pool = pools[0]
        pool['raidLevel'] = 'raid6'
        snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        snapshot_group['baseVolume'] = vol['id']
        vol['volumeGroupRef'] = pool['id']

        get_call = self.mock_object(
            self.library, '_get_sorted_available_storage_pools',
            return_value=pools)
        self.mock_object(self.library._client, 'create_snapshot_group',
                         return_value=snapshot_group)
        actual = self.library._create_snapshot_group('label', vol)

        get_call.assert_called_once_with(vol_size_gb)
        self.assertEqual(snapshot_group, actual)

    def test_get_snapshot(self):
        fake_snap = copy.deepcopy(eseries_fake.FAKE_CINDER_SNAPSHOT)
        snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        get_snap = self.mock_object(
            self.library._client, 'list_snapshot_image', return_value=snap)

        result = self.library._get_snapshot(fake_snap)

        self.assertEqual(snap, result)
        get_snap.assert_called_once_with(fake_snap['provider_id'])

    def test_get_snapshot_fail(self):
        fake_snap = copy.deepcopy(eseries_fake.FAKE_CINDER_SNAPSHOT)
        get_snap = self.mock_object(
            self.library._client, 'list_snapshot_image',
            side_effect=exception.NotFound)

        self.assertRaises(exception.NotFound, self.library._get_snapshot,
                          fake_snap)

        get_snap.assert_called_once_with(fake_snap['provider_id'])

    def test_get_snapshot_group_for_snapshot(self):
        fake_id = 'id'
        snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        grp = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        get_snap = self.mock_object(
            self.library, '_get_snapshot', return_value=snap)
        get_grp = self.mock_object(self.library._client, 'list_snapshot_group',
                                   return_value=grp)

        result = self.library._get_snapshot_group_for_snapshot(fake_id)

        self.assertEqual(grp, result)
        get_grp.assert_called_once_with(snap['pitGroupRef'])
        get_snap.assert_called_once_with(fake_id)

    def test_get_snapshot_group_for_snapshot_fail(self):
        fake_id = 'id'
        snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        get_snap = self.mock_object(
            self.library, '_get_snapshot', return_value=snap)
        get_grp = self.mock_object(self.library._client, 'list_snapshot_group',
                                   side_effect=exception.NotFound)

        self.assertRaises(exception.NotFound,
                          self.library._get_snapshot_group_for_snapshot,
                          fake_id)

        get_grp.assert_called_once_with(snap['pitGroupRef'])
        get_snap.assert_called_once_with(fake_id)

    def test_get_snapshot_groups_for_volume(self):
        vol = copy.deepcopy(eseries_fake.VOLUME)
        snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        snapshot_group['baseVolume'] = vol['id']
        # Generate some snapshot groups that will not match
        snapshot_groups = [copy.deepcopy(snapshot_group) for i in range(
            self.library.MAX_SNAPSHOT_GROUP_COUNT)]
        for i, group in enumerate(snapshot_groups):
            group['baseVolume'] = str(i)
        snapshot_groups.append(snapshot_group)
        get_call = self.mock_object(
            self.library._client, 'list_snapshot_groups',
            return_value=snapshot_groups)

        groups = self.library._get_snapshot_groups_for_volume(vol)

        get_call.assert_called_once_with()
        self.assertEqual([snapshot_group], groups)

    def test_get_available_snapshot_group(self):
        vol = copy.deepcopy(eseries_fake.VOLUME)
        snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        snapshot_group['baseVolume'] = vol['id']
        snapshot_group['snapshotCount'] = 0
        # Generate some snapshot groups that will not match

        reserved_group = copy.deepcopy(snapshot_group)
        reserved_group['label'] += self.library.SNAPSHOT_VOL_COPY_SUFFIX

        full_group = copy.deepcopy(snapshot_group)
        full_group['snapshotCount'] = self.library.MAX_SNAPSHOT_COUNT

        cgroup = copy.deepcopy(snapshot_group)
        cgroup['consistencyGroup'] = True

        snapshot_groups = [snapshot_group, reserved_group, full_group, cgroup]
        get_call = self.mock_object(
            self.library, '_get_snapshot_groups_for_volume',
            return_value=snapshot_groups)

        group = self.library._get_available_snapshot_group(vol)

        get_call.assert_called_once_with(vol)
        self.assertEqual(snapshot_group, group)

    def test_get_snapshot_groups_for_volume_not_found(self):
        vol = copy.deepcopy(eseries_fake.VOLUME)
        snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        snapshot_group['baseVolume'] = vol['id']
        snapshot_group['snapshotCount'] = self.library.MAX_SNAPSHOT_COUNT
        # Generate some snapshot groups that will not match

        get_call = self.mock_object(
            self.library, '_get_snapshot_groups_for_volume',
            return_value=[snapshot_group])

        group = self.library._get_available_snapshot_group(vol)

        get_call.assert_called_once_with(vol)
        self.assertIsNone(group)

    def test_create_snapshot_available_snap_group(self):
        expected_snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        expected = {'provider_id': expected_snap['id']}
        vol = copy.deepcopy(eseries_fake.VOLUME)
        snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        fake_label = 'fakeName'
        self.mock_object(self.library, '_get_volume', return_value=vol)
        create_call = self.mock_object(
            self.library._client, 'create_snapshot_image',
            return_value=expected_snap)
        self.mock_object(self.library, '_get_available_snapshot_group',
                         return_value=snapshot_group)
        self.mock_object(utils, 'convert_uuid_to_es_fmt',
                         return_value=fake_label)
        fake_snapshot = copy.deepcopy(eseries_fake.FAKE_CINDER_SNAPSHOT)

        model_update = self.library.create_snapshot(fake_snapshot)

        self.assertEqual(expected, model_update)
        create_call.assert_called_once_with(snapshot_group['id'])

    @ddt.data(False, True)
    def test_create_snapshot_failure(self, cleanup_failure):
        """Validate the behavior for a failure during snapshot creation"""

        vol = copy.deepcopy(eseries_fake.VOLUME)
        snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        snap_vol = copy.deepcopy(eseries_fake.SNAPSHOT_VOLUME)
        fake_label = 'fakeName'
        create_fail_exc = exception.NetAppDriverException('fail_create')
        cleanup_fail_exc = exception.NetAppDriverException('volume_deletion')
        if cleanup_failure:
            exc_msg = cleanup_fail_exc.msg
            delete_snap_grp = self.mock_object(
                self.library, '_delete_snapshot_group',
                side_effect=cleanup_fail_exc)
        else:
            exc_msg = create_fail_exc.msg
            delete_snap_grp = self.mock_object(
                self.library, '_delete_snapshot_group')
        self.mock_object(self.library, '_get_volume', return_value=vol)
        self.mock_object(self.library._client, 'create_snapshot_image',
                         side_effect=create_fail_exc)
        self.mock_object(self.library._client, 'create_snapshot_volume',
                         return_value=snap_vol)
        self.mock_object(self.library, '_get_available_snapshot_group',
                         return_value=snapshot_group)
        self.mock_object(utils, 'convert_uuid_to_es_fmt',
                         return_value=fake_label)
        fake_snapshot = copy.deepcopy(eseries_fake.FAKE_CINDER_SNAPSHOT)

        self.assertRaisesRegexp(exception.NetAppDriverException,
                                exc_msg,
                                self.library.create_snapshot,
                                fake_snapshot)
        self.assertTrue(delete_snap_grp.called)

    def test_create_snapshot_no_snap_group(self):
        self.library._client.features = mock.Mock()
        expected_snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        vol = copy.deepcopy(eseries_fake.VOLUME)
        snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        fake_label = 'fakeName'
        self.mock_object(self.library, '_get_volume', return_value=vol)
        create_call = self.mock_object(
            self.library._client, 'create_snapshot_image',
            return_value=expected_snap)
        self.mock_object(self.library, '_get_snapshot_groups_for_volume',
                         return_value=[snapshot_group])
        self.mock_object(self.library, '_get_available_snapshot_group',
                         return_value=None)
        self.mock_object(utils, 'convert_uuid_to_es_fmt',
                         return_value=fake_label)
        fake_snapshot = copy.deepcopy(eseries_fake.FAKE_CINDER_SNAPSHOT)

        snapshot = self.library.create_snapshot(fake_snapshot)

        expected = {'provider_id': expected_snap['id']}
        self.assertEqual(expected, snapshot)
        create_call.assert_called_once_with(snapshot_group['id'])

    def test_create_snapshot_no_snapshot_groups_remaining(self):
        """Test the failure condition where all snap groups are allocated"""

        self.library._client.features = mock.Mock()
        expected_snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        vol = copy.deepcopy(eseries_fake.VOLUME)
        snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        snap_vol = copy.deepcopy(eseries_fake.SNAPSHOT_VOLUME)
        grp_count = (self.library.MAX_SNAPSHOT_GROUP_COUNT -
                     self.library.RESERVED_SNAPSHOT_GROUP_COUNT)
        fake_label = 'fakeName'
        self.mock_object(self.library, '_get_volume', return_value=vol)
        self.mock_object(self.library._client, 'create_snapshot_image',
                         return_value=expected_snap)
        self.mock_object(self.library._client, 'create_snapshot_volume',
                         return_value=snap_vol)
        self.mock_object(self.library, '_get_available_snapshot_group',
                         return_value=None)
        self.mock_object(self.library, '_get_snapshot_groups_for_volume',
                         return_value=[snapshot_group] * grp_count)
        self.mock_object(utils, 'convert_uuid_to_es_fmt',
                         return_value=fake_label)
        fake_snapshot = copy.deepcopy(eseries_fake.FAKE_CINDER_SNAPSHOT)

        # Error message should contain the maximum number of supported
        # snapshots
        self.assertRaisesRegexp(exception.SnapshotLimitExceeded,
                                str(self.library.MAX_SNAPSHOT_COUNT *
                                    grp_count),
                                self.library.create_snapshot, fake_snapshot)

    def test_delete_snapshot(self):
        fake_vol = cinder_utils.create_volume(self.ctxt)
        fake_snap = cinder_utils.create_snapshot(self.ctxt, fake_vol['id'])
        snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        vol = copy.deepcopy(eseries_fake.VOLUME)
        self.mock_object(self.library, '_get_volume', return_value=vol)
        self.mock_object(self.library, '_get_snapshot', return_value=snap)

        del_snap = self.mock_object(self.library, '_delete_es_snapshot')

        self.library.delete_snapshot(fake_snap)

        del_snap.assert_called_once_with(snap)

    def test_delete_es_snapshot(self):
        vol = copy.deepcopy(eseries_fake.VOLUME)
        snap_count = 30
        # Ensure that it's the oldest PIT
        snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        snapshot_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        fake_volume_refs = ['1', '2', snap['baseVol']]
        fake_snapshot_group_refs = ['3', '4', snapshot_group['id']]
        snapshots = [copy.deepcopy(snap) for i in range(snap_count)]
        bitset = na_utils.BitSet(0)
        for i, snapshot in enumerate(snapshots):
            volume_ref = fake_volume_refs[i % len(fake_volume_refs)]
            group_ref = fake_snapshot_group_refs[i %
                                                 len(fake_snapshot_group_refs)]
            snapshot['pitGroupRef'] = group_ref
            snapshot['baseVol'] = volume_ref
            snapshot['pitSequenceNumber'] = str(i)
            snapshot['id'] = i
            bitset.set(i)
        snapshots.append(snap)

        filtered_snaps = [x for x in snapshots
                          if x['pitGroupRef'] == snap['pitGroupRef']]

        self.mock_object(self.library, '_get_volume', return_value=vol)
        self.mock_object(self.library, '_get_snapshot', return_value=snap)
        self.mock_object(self.library, '_get_soft_delete_map',
                         return_value={snap['pitGroupRef']: repr(bitset)})
        self.mock_object(self.library._client, 'list_snapshot_images',
                         return_value=snapshots)
        delete_image = self.mock_object(
            self.library, '_cleanup_snapshot_images',
            return_value=({snap['pitGroupRef']: repr(bitset)}, None))

        self.library._delete_es_snapshot(snap)

        delete_image.assert_called_once_with(filtered_snaps, bitset)

    def test_delete_snapshot_oldest(self):
        vol = copy.deepcopy(eseries_fake.VOLUME)
        snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        snapshots = [snap]
        self.mock_object(self.library, '_get_volume', return_value=vol)
        self.mock_object(self.library, '_get_snapshot', return_value=snap)
        self.mock_object(self.library, '_get_soft_delete_map', return_value={})
        self.mock_object(self.library._client, 'list_snapshot_images',
                         return_value=snapshots)
        delete_image = self.mock_object(
            self.library, '_cleanup_snapshot_images',
            return_value=(None, [snap['pitGroupRef']]))

        self.library._delete_es_snapshot(snap)

        delete_image.assert_called_once_with(snapshots,
                                             na_utils.BitSet(1))

    def test_get_soft_delete_map(self):
        fake_val = 'fake'
        self.mock_object(self.library._client, 'list_backend_store',
                         return_value=fake_val)

        actual = self.library._get_soft_delete_map()

        self.assertEqual(fake_val, actual)

    def test_cleanup_snapshot_images_delete_all(self):
        image = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        images = [image] * 32
        bitset = na_utils.BitSet()
        for i, image in enumerate(images):
            image['pitSequenceNumber'] = i
            bitset.set(i)
        delete_grp = self.mock_object(self.library._client,
                                      'delete_snapshot_group')

        updt, keys = self.library._cleanup_snapshot_images(
            images, bitset)

        delete_grp.assert_called_once_with(image['pitGroupRef'])
        self.assertIsNone(updt)
        self.assertEqual([image['pitGroupRef']], keys)

    def test_cleanup_snapshot_images_delete_all_fail(self):
        image = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        bitset = na_utils.BitSet(2 ** 32 - 1)
        delete_grp = self.mock_object(
            self.library._client, 'delete_snapshot_group',
            side_effect=exception.NetAppDriverException)

        updt, keys = self.library._cleanup_snapshot_images(
            [image], bitset)

        delete_grp.assert_called_once_with(image['pitGroupRef'])
        self.assertIsNone(updt)
        self.assertEqual([image['pitGroupRef']], keys)

    def test_cleanup_snapshot_images(self):
        image = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        images = [image] * 32
        del_count = 16
        bitset = na_utils.BitSet()
        for i, image in enumerate(images):
            image['pitSequenceNumber'] = i
            if i < del_count:
                bitset.set(i)
        exp_bitset = copy.deepcopy(bitset)
        exp_bitset >>= 16
        delete_img = self.mock_object(
            self.library, '_delete_snapshot_image')

        updt, keys = self.library._cleanup_snapshot_images(
            images, bitset)

        self.assertEqual(del_count, delete_img.call_count)
        self.assertIsNone(keys)
        self.assertEqual({image['pitGroupRef']: exp_bitset}, updt)

    def test_delete_snapshot_image(self):
        snap_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)

        self.mock_object(self.library._client, 'list_snapshot_group',
                         return_value=snap_group)

        self.library._delete_snapshot_image(snap)

    def test_delete_snapshot_image_fail_cleanup(self):
        snap_group = copy.deepcopy(eseries_fake.SNAPSHOT_GROUP)
        snap_group['snapshotCount'] = 0
        snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)

        self.mock_object(self.library._client, 'list_snapshot_group',
                         return_value=snap_group)

        self.library._delete_snapshot_image(snap)

    def test_delete_snapshot_not_found(self):
        fake_snapshot = copy.deepcopy(eseries_fake.FAKE_CINDER_SNAPSHOT)
        get_snap = self.mock_object(self.library, '_get_snapshot',
                                    side_effect=exception.NotFound)

        with mock.patch.object(library, 'LOG', mock.Mock()):
            self.library.delete_snapshot(fake_snapshot)
            get_snap.assert_called_once_with(fake_snapshot)
            self.assertTrue(library.LOG.warning.called)

    @ddt.data(['key1', 'key2'], [], None)
    def test_merge_soft_delete_changes_keys(self, keys_to_del):
        count = len(keys_to_del) if keys_to_del is not None else 0
        save_store = self.mock_object(
            self.library._client, 'save_backend_store')
        index = {'key1': 'val'}
        get_store = self.mock_object(self.library, '_get_soft_delete_map',
                                     return_value=index)

        self.library._merge_soft_delete_changes(None, keys_to_del)

        if count:
            expected = copy.deepcopy(index)
            for key in keys_to_del:
                expected.pop(key, None)
            get_store.assert_called_once_with()
            save_store.assert_called_once_with(
                self.library.SNAPSHOT_PERSISTENT_STORE_KEY, expected)
        else:
            get_store.assert_not_called()
            save_store.assert_not_called()

    def test_create_cgsnapshot(self):
        fake_cgsnapshot = copy.deepcopy(eseries_fake.FAKE_CINDER_CG_SNAPSHOT)
        fake_vol = cinder_utils.create_volume(self.ctxt)
        fake_snapshots = [cinder_utils.create_snapshot(self.ctxt,
                                                       fake_vol['id'])]
        vol = copy.deepcopy(eseries_fake.VOLUME)
        image = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        image['baseVol'] = vol['id']
        cg_snaps = [image]
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)

        for snap in cg_snaps:
            snap['baseVol'] = vol['id']
        get_cg = self.mock_object(
            self.library, '_get_consistencygroup_by_name', return_value=cg)
        get_vol = self.mock_object(
            self.library, '_get_volume', return_value=vol)
        mk_snap = self.mock_object(
            self.library._client, 'create_consistency_group_snapshot',
            return_value=cg_snaps)

        model_update, snap_updt = self.library.create_cgsnapshot(
            fake_cgsnapshot, fake_snapshots)

        self.assertIsNone(model_update)
        for snap in cg_snaps:
            self.assertIn({'id': fake_snapshots[0]['id'],
                           'provider_id': snap['id'],
                           'status': 'available'}, snap_updt)
        self.assertEqual(len(cg_snaps), len(snap_updt))

        get_cg.assert_called_once_with(utils.convert_uuid_to_es_fmt(
            fake_cgsnapshot['consistencygroup_id']))
        self.assertEqual(get_vol.call_count, len(fake_snapshots))
        mk_snap.assert_called_once_with(cg['id'])

    def test_create_cgsnapshot_cg_fail(self):
        fake_cgsnapshot = copy.deepcopy(eseries_fake.FAKE_CINDER_CG_SNAPSHOT)
        fake_snapshots = [copy.deepcopy(eseries_fake.FAKE_CINDER_SNAPSHOT)]
        self.mock_object(
            self.library, '_get_consistencygroup_by_name',
            side_effect=exception.NetAppDriverException)

        self.assertRaises(
            exception.NetAppDriverException,
            self.library.create_cgsnapshot, fake_cgsnapshot, fake_snapshots)

    def test_delete_cgsnapshot(self):
        """Test the deletion of a cgsnapshot when a soft delete is required"""
        fake_cgsnapshot = copy.deepcopy(eseries_fake.FAKE_CINDER_CG_SNAPSHOT)
        fake_vol = cinder_utils.create_volume(self.ctxt)
        fake_snapshots = [cinder_utils.create_snapshot(
            self.ctxt, fake_vol['id'])]
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        cg_snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        # Ensure that the snapshot to be deleted is not the oldest
        cg_snap['pitSequenceNumber'] = str(max(cg['uniqueSequenceNumber']))
        cg_snaps = [cg_snap]
        for snap in fake_snapshots:
            snap['provider_id'] = cg_snap['id']
        vol = copy.deepcopy(eseries_fake.VOLUME)
        for snap in cg_snaps:
            snap['baseVol'] = vol['id']
        get_cg = self.mock_object(
            self.library, '_get_consistencygroup_by_name', return_value=cg)
        self.mock_object(
            self.library._client, 'delete_consistency_group_snapshot')
        self.mock_object(
            self.library._client, 'get_consistency_group_snapshots',
            return_value=cg_snaps)
        soft_del = self.mock_object(
            self.library, '_soft_delete_cgsnapshot', return_value=(None, None))

        # Mock the locking mechanism
        model_update, snap_updt = self.library.delete_cgsnapshot(
            fake_cgsnapshot, fake_snapshots)

        self.assertIsNone(model_update)
        self.assertIsNone(snap_updt)
        get_cg.assert_called_once_with(utils.convert_uuid_to_es_fmt(
            fake_cgsnapshot['consistencygroup_id']))
        soft_del.assert_called_once_with(
            cg, cg_snap['pitSequenceNumber'])

    @ddt.data(True, False)
    def test_soft_delete_cgsnapshot(self, bitset_exists):
        """Test the soft deletion of a cgsnapshot"""
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        cg_snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        seq_num = 10
        cg_snap['pitSequenceNumber'] = seq_num
        cg_snaps = [cg_snap]
        self.mock_object(
            self.library._client, 'delete_consistency_group_snapshot')
        self.mock_object(
            self.library._client, 'get_consistency_group_snapshots',
            return_value=cg_snaps)
        bitset = na_utils.BitSet(1)
        index = {cg['id']: repr(bitset)} if bitset_exists else {}
        bitset >>= len(cg_snaps)
        updt = {cg['id']: repr(bitset)}
        self.mock_object(self.library, '_get_soft_delete_map',
                         return_value=index)
        save_map = self.mock_object(self.library, '_merge_soft_delete_changes')

        model_update, snap_updt = self.library._soft_delete_cgsnapshot(
            cg, seq_num)

        self.assertIsNone(model_update)
        self.assertIsNone(snap_updt)
        save_map.assert_called_once_with(updt, None)

    def test_delete_cgsnapshot_single(self):
        """Test the backend deletion of the oldest cgsnapshot"""
        fake_cgsnapshot = copy.deepcopy(eseries_fake.FAKE_CINDER_CG_SNAPSHOT)
        fake_vol = cinder_utils.create_volume(self.ctxt)
        fake_snapshots = [cinder_utils.create_snapshot(self.ctxt,
                                                       fake_vol['id'])]
        cg_snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        cg_snaps = [cg_snap]
        for snap in fake_snapshots:
            snap['provider_id'] = cg_snap['id']
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        cg['uniqueSequenceNumber'] = [cg_snap['pitSequenceNumber']]
        vol = copy.deepcopy(eseries_fake.VOLUME)
        for snap in cg_snaps:
            snap['baseVol'] = vol['id']
        get_cg = self.mock_object(
            self.library, '_get_consistencygroup_by_name', return_value=cg)
        del_snap = self.mock_object(
            self.library._client, 'delete_consistency_group_snapshot',
            return_value=cg_snaps)

        model_update, snap_updt = self.library.delete_cgsnapshot(
            fake_cgsnapshot, fake_snapshots)

        self.assertIsNone(model_update)
        self.assertIsNone(snap_updt)
        get_cg.assert_called_once_with(utils.convert_uuid_to_es_fmt(
            fake_cgsnapshot['consistencygroup_id']))
        del_snap.assert_called_once_with(cg['id'], cg_snap[
            'pitSequenceNumber'])

    def test_delete_cgsnapshot_snap_not_found(self):
        fake_cgsnapshot = copy.deepcopy(eseries_fake.FAKE_CINDER_CG_SNAPSHOT)
        fake_vol = cinder_utils.create_volume(self.ctxt)
        fake_snapshots = [cinder_utils.create_snapshot(
            self.ctxt, fake_vol['id'])]
        cg_snap = copy.deepcopy(eseries_fake.SNAPSHOT_IMAGE)
        cg_snaps = [cg_snap]
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        self.mock_object(self.library, '_get_consistencygroup_by_name',
                         return_value=cg)
        self.mock_object(
            self.library._client, 'delete_consistency_group_snapshot',
            return_value=cg_snaps)

        self.assertRaises(
            exception.CgSnapshotNotFound,
            self.library.delete_cgsnapshot, fake_cgsnapshot, fake_snapshots)

    @ddt.data(0, 1, 10, 32)
    def test_cleanup_cg_snapshots(self, count):
        # Set the soft delete bit for 'count' snapshot images
        bitset = na_utils.BitSet()
        for i in range(count):
            bitset.set(i)
        cg = copy.deepcopy(eseries_fake.FAKE_CONSISTENCY_GROUP)
        # Define 32 snapshots for the CG
        cg['uniqueSequenceNumber'] = list(range(32))
        cg_id = cg['id']
        del_snap = self.mock_object(
            self.library._client, 'delete_consistency_group_snapshot')
        expected_bitset = copy.deepcopy(bitset) >> count
        expected_updt = {cg_id: repr(expected_bitset)}

        updt = self.library._cleanup_cg_snapshots(
            cg_id, cg['uniqueSequenceNumber'], bitset)

        self.assertEqual(count, del_snap.call_count)
        self.assertEqual(expected_updt, updt)

    @ddt.data(False, True)
    def test_get_pool_operation_progress(self, expect_complete):
        """Validate the operation progress is interpreted correctly"""

        pool = copy.deepcopy(eseries_fake.STORAGE_POOL)
        if expect_complete:
            pool_progress = []
        else:
            pool_progress = copy.deepcopy(
                eseries_fake.FAKE_POOL_ACTION_PROGRESS)

        expected_actions = set(action['currentAction'] for action in
                               pool_progress)
        expected_eta = reduce(lambda x, y: x + y['estimatedTimeToCompletion'],
                              pool_progress, 0)

        self.library._client.get_pool_operation_progress = mock.Mock(
            return_value=pool_progress)

        complete, actions, eta = self.library._get_pool_operation_progress(
            pool['id'])
        self.assertEqual(expect_complete, complete)
        self.assertEqual(expected_actions, actions)
        self.assertEqual(expected_eta, eta)

    @ddt.data(False, True)
    def test_get_pool_operation_progress_with_action(self, expect_complete):
        """Validate the operation progress is interpreted correctly"""

        expected_action = 'fakeAction'
        pool = copy.deepcopy(eseries_fake.STORAGE_POOL)
        if expect_complete:
            pool_progress = copy.deepcopy(
                eseries_fake.FAKE_POOL_ACTION_PROGRESS)
            for progress in pool_progress:
                progress['currentAction'] = 'none'
        else:
            pool_progress = copy.deepcopy(
                eseries_fake.FAKE_POOL_ACTION_PROGRESS)
            pool_progress[0]['currentAction'] = expected_action

        expected_actions = set(action['currentAction'] for action in
                               pool_progress)
        expected_eta = reduce(lambda x, y: x + y['estimatedTimeToCompletion'],
                              pool_progress, 0)

        self.library._client.get_pool_operation_progress = mock.Mock(
            return_value=pool_progress)

        complete, actions, eta = self.library._get_pool_operation_progress(
            pool['id'], expected_action)
        self.assertEqual(expect_complete, complete)
        self.assertEqual(expected_actions, actions)
        self.assertEqual(expected_eta, eta)

    @mock.patch('eventlet.greenthread.sleep')
    def test_extend_volume(self, _mock_sleep):
        """Test volume extend with a thick-provisioned volume"""

        def get_copy_progress():
            for eta in range(5, -1, -1):
                action_status = 'none' if eta == 0 else 'remappingDve'
                complete = action_status == 'none'
                yield complete, action_status, eta

        fake_volume = copy.deepcopy(get_fake_volume())
        volume = copy.deepcopy(eseries_fake.VOLUME)
        new_capacity = 10
        volume['objectType'] = 'volume'
        self.library._client.expand_volume = mock.Mock()
        self.library._get_pool_operation_progress = mock.Mock(
            side_effect=get_copy_progress())
        self.library._get_volume = mock.Mock(return_value=volume)

        self.library.extend_volume(fake_volume, new_capacity)

        # Ensure that the extend method waits until the expansion is completed
        self.assertEqual(6,
                         self.library._get_pool_operation_progress.call_count
                         )
        self.library._client.expand_volume.assert_called_with(volume['id'],
                                                              new_capacity,
                                                              False)

    def test_extend_volume_thin(self):
        """Test volume extend with a thin-provisioned volume"""

        fake_volume = copy.deepcopy(get_fake_volume())
        volume = copy.deepcopy(eseries_fake.VOLUME)
        new_capacity = 10
        volume['objectType'] = 'thinVolume'
        self.library._client.expand_volume = mock.Mock(return_value=volume)
        self.library._get_volume_operation_progress = mock.Mock()
        self.library._get_volume = mock.Mock(return_value=volume)

        self.library.extend_volume(fake_volume, new_capacity)

        self.assertFalse(self.library._get_volume_operation_progress.called)
        self.library._client.expand_volume.assert_called_with(volume['id'],
                                                              new_capacity,
                                                              True)

    def test_delete_non_existing_volume(self):
        volume2 = get_fake_volume()
        # Change to a nonexistent id.
        volume2['name_id'] = '88888888-4444-4444-4444-cccccccccccc'
        self.assertIsNone(self.library.delete_volume(volume2))

    def test_map_volume_to_host_volume_not_mapped(self):
        """Map the volume directly to destination host."""
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         return_value=[])
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)

        self.library.map_volume_to_host(get_fake_volume(),
                                        eseries_fake.VOLUME,
                                        eseries_fake.INITIATOR_NAME_2)

        self.assertTrue(
            self.library._client.get_volume_mappings_for_volume.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_map_volume_to_host_volume_not_mapped_host_does_not_exist(self):
        """Should create the host map directly to the host."""
        self.mock_object(self.library._client, 'list_hosts',
                         return_value=[])
        self.mock_object(self.library._client, 'create_host_with_ports',
                         return_value=eseries_fake.HOST_2)
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         return_value=[])
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)

        self.library.map_volume_to_host(get_fake_volume(),
                                        eseries_fake.VOLUME,
                                        eseries_fake.INITIATOR_NAME_2)

        self.assertTrue(self.library._client.create_host_with_ports.called)
        self.assertTrue(
            self.library._client.get_volume_mappings_for_volume.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_map_volume_to_host_volume_already_mapped(self):
        """Should be a no-op."""
        self.mock_object(host_mapper, 'map_volume_to_multiple_hosts',
                         return_value=eseries_fake.VOLUME_MAPPING)

        self.library.map_volume_to_host(get_fake_volume(),
                                        eseries_fake.VOLUME,
                                        eseries_fake.INITIATOR_NAME)

        self.assertTrue(host_mapper.map_volume_to_multiple_hosts.called)


class NetAppEseriesISCSICHAPAuthenticationTestCase(test.TestCase):
    """Test behavior when the use_chap_auth configuration option is True."""

    def setUp(self):
        super(NetAppEseriesISCSICHAPAuthenticationTestCase, self).setUp()
        config = eseries_fake.create_configuration_eseries()
        config.use_chap_auth = True
        config.chap_password = None
        config.chap_username = None

        kwargs = {'configuration': config}

        self.library = library.NetAppESeriesLibrary("FAKE", **kwargs)
        self.library._client = eseries_fake.FakeEseriesClient()
        self.library._client.features = mock.Mock()
        self.library._client.features = na_utils.Features()
        self.library._client.features.add_feature('CHAP_AUTHENTICATION',
                                                  supported=True,
                                                  min_version="1.53.9010.15")
        self.mock_object(self.library,
                         '_check_storage_system')
        self.library.check_for_setup_error()

    def test_initialize_connection_with_chap(self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        self.mock_object(self.library._client, 'get_volume_mappings',
                         return_value=[])
        self.mock_object(self.library._client, 'list_hosts',
                         return_value=[])
        self.mock_object(self.library._client, 'create_host_with_ports',
                         return_value=[eseries_fake.HOST])
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)
        mock_configure_chap = (
            self.mock_object(self.library,
                             '_configure_chap',
                             return_value=(eseries_fake.FAKE_CHAP_USERNAME,
                                           eseries_fake.FAKE_CHAP_SECRET)))

        properties = self.library.initialize_connection_iscsi(
            get_fake_volume(), connector)

        mock_configure_chap.assert_called_with(eseries_fake.FAKE_TARGET_IQN)
        self.assertDictEqual(eseries_fake.FAKE_TARGET_DICT, properties)

    def test_configure_chap_with_no_chap_secret_specified(self):
        mock_invoke_generate_random_secret = self.mock_object(
            volume_utils,
            'generate_password',
            return_value=eseries_fake.FAKE_CHAP_SECRET)
        mock_invoke_set_chap_authentication = self.mock_object(
            self.library._client,
            'set_chap_authentication',
            return_value=eseries_fake.FAKE_CHAP_POST_DATA)

        username, password = self.library._configure_chap(
            eseries_fake.FAKE_TARGET_IQN)

        self.assertTrue(mock_invoke_generate_random_secret.called)
        mock_invoke_set_chap_authentication.assert_called_with(
            *eseries_fake.FAKE_CLIENT_CHAP_PARAMETERS)
        self.assertEqual(eseries_fake.FAKE_CHAP_USERNAME, username)
        self.assertEqual(eseries_fake.FAKE_CHAP_SECRET, password)

    def test_configure_chap_with_no_chap_username_specified(self):
        mock_invoke_generate_random_secret = self.mock_object(
            volume_utils,
            'generate_password',
            return_value=eseries_fake.FAKE_CHAP_SECRET)
        mock_invoke_set_chap_authentication = self.mock_object(
            self.library._client,
            'set_chap_authentication',
            return_value=eseries_fake.FAKE_CHAP_POST_DATA)
        mock_log = self.mock_object(library, 'LOG')
        warn_msg = 'No CHAP username found for CHAP user'

        username, password = self.library._configure_chap(
            eseries_fake.FAKE_TARGET_IQN)

        self.assertTrue(mock_invoke_generate_random_secret.called)
        self.assertTrue(mock_log.warning.find(warn_msg))
        mock_invoke_set_chap_authentication.assert_called_with(
            *eseries_fake.FAKE_CLIENT_CHAP_PARAMETERS)
        self.assertEqual(eseries_fake.FAKE_CHAP_USERNAME, username)
        self.assertEqual(eseries_fake.FAKE_CHAP_SECRET, password)

    def test_configure_chap_with_invalid_version(self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         return_value=[])
        self.mock_object(host_mapper,
                         'map_volume_to_single_host',
                         return_value=eseries_fake.VOLUME_MAPPING)
        self.library._client.features.CHAP_AUTHENTICATION.supported = False
        self.library._client.api_version = "1.52.9010.01"

        self.assertRaises(exception.NetAppDriverException,
                          self.library.initialize_connection_iscsi,
                          get_fake_volume(),
                          connector)
