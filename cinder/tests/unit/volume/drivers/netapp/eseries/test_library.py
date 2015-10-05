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

import mock
from oslo_utils import units
import six

from cinder import exception
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit.volume.drivers.netapp.eseries import fakes as \
    eseries_fake
from cinder.volume.drivers.netapp.eseries import client as es_client
from cinder.volume.drivers.netapp.eseries import exception as eseries_exc
from cinder.volume.drivers.netapp.eseries import host_mapper
from cinder.volume.drivers.netapp.eseries import library
from cinder.volume.drivers.netapp.eseries import utils
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.zonemanager import utils as fczm_utils


def get_fake_volume():
    return {
        'id': '114774fb-e15a-4fae-8ee2-c9723e3645ef', 'size': 1,
        'volume_name': 'lun1', 'host': 'hostname@backend#DDP',
        'os_type': 'linux', 'provider_location': 'lun1',
        'name_id': '114774fb-e15a-4fae-8ee2-c9723e3645ef',
        'provider_auth': 'provider a b', 'project_id': 'project',
        'display_name': None, 'display_description': 'lun1',
        'volume_type_id': None, 'migration_status': None, 'attach_status':
        "detached"
    }


@ddt.ddt
class NetAppEseriesLibraryTestCase(test.TestCase):
    def setUp(self):
        super(NetAppEseriesLibraryTestCase, self).setUp()

        kwargs = {'configuration':
                  eseries_fake.create_configuration_eseries()}

        self.library = library.NetAppESeriesLibrary('FAKE', **kwargs)
        # Deprecated Option
        self.library.configuration.netapp_storage_pools = None
        self.library._client = eseries_fake.FakeEseriesClient()
        self.library.check_for_setup_error()

    def test_do_setup(self):
        self.mock_object(self.library,
                         '_check_mode_get_or_register_storage_system')
        self.mock_object(es_client, 'RestClient',
                         eseries_fake.FakeEseriesClient)
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        self.library.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)

    def test_get_storage_pools_empty_result(self):
        """Verify an exception is raised if no pools are returned."""
        self.library.configuration.netapp_pool_name_search_pattern = '$'

        self.assertRaises(exception.NetAppDriverException,
                          self.library.check_for_setup_error)

    def test_get_storage_pools_invalid_conf(self):
        """Verify an exception is raised if the regex pattern is invalid."""
        self.library.configuration.netapp_pool_name_search_pattern = '(.*'

        self.assertRaises(exception.InvalidConfigurationValue,
                          self.library._get_storage_pools)

    def test_get_storage_pools_default(self):
        """Verify that all pools are returned if the search option is empty."""
        filtered_pools = self.library._get_storage_pools()

        self.assertEqual(eseries_fake.STORAGE_POOLS, filtered_pools)

    @ddt.data(('[\d]+,a', ['1', '2', 'a', 'b'], ['1', '2', 'a']),
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
        self.assertDictMatch(volume, result)

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
            self.assertDictMatch(expected, actual)

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
        self.library._get_storage_pools = mock.Mock(return_value=[fake_pool])
        self.mock_object(self.library, '_ssc_stats', new_attr={fake_pool[
            "volumeGroupRef"]: {self.library.THIN_UQ_SPEC: True}})
        self.library.configuration = mock.Mock()
        reserved_pct = 5
        over_subscription_ratio = 1.0
        self.library.configuration.max_over_subscription_ratio = (
            over_subscription_ratio)
        self.library.configuration.reserved_percentage = reserved_pct
        total_gb = int(fake_pool['totalRaidedSpace']) / units.Gi
        used_gb = int(fake_pool['usedSpace']) / units.Gi
        free_gb = total_gb - used_gb

        self.library._update_volume_stats()

        self.assertEqual(1, len(self.library._stats['pools']))
        pool_stats = self.library._stats['pools'][0]
        self.assertEqual(fake_pool['label'], pool_stats.get('pool_name'))
        self.assertEqual(reserved_pct, pool_stats['reserved_percentage'])
        self.assertEqual(over_subscription_ratio,
                         pool_stats['max_oversubscription_ratio'])
        self.assertEqual(total_gb, pool_stats.get('total_capacity_gb'))
        self.assertEqual(used_gb, pool_stats.get('provisioned_capacity_gb'))
        self.assertEqual(free_gb, pool_stats.get('free_capacity_gb'))

    @ddt.data(False, True)
    def test_update_volume_stats_thin_provisioning(self, thin_provisioning):
        """Validate that thin provisioning support is correctly reported"""
        fake_pool = copy.deepcopy(eseries_fake.STORAGE_POOL)
        self.library._get_storage_pools = mock.Mock(return_value=[fake_pool])
        self.mock_object(self.library, '_ssc_stats', new_attr={fake_pool[
            "volumeGroupRef"]: {self.library.THIN_UQ_SPEC: thin_provisioning}})

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
        self.mock_object(self.library, '_ssc_stats', new_attr={fake_pool[
            "volumeGroupRef"]: ssc})

        self.library._update_volume_stats()

        self.assertEqual(1, len(self.library._stats['pools']))
        pool_stats = self.library._stats['pools'][0]
        for key in ssc:
            self.assertIn(key, pool_stats)
            self.assertEqual(ssc[key], pool_stats[key])

    def test_update_volume_stats_no_ssc(self):
        """Ensure that that pool stats are correctly reported without SSC"""
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

        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[]))

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
                         mock.Mock(return_value=fake_eseries_volume))
        self.mock_object(host_mapper, 'unmap_volume_from_host')

        self.library.terminate_connection_iscsi(get_fake_volume(), connector)

        self.assertTrue(host_mapper.unmap_volume_from_host.called)

    def test_terminate_connection_iscsi_not_mapped_initiator_does_not_exist(
            self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[eseries_fake.HOST_2]))
        self.assertRaises(exception.NotFound,
                          self.library.terminate_connection_iscsi,
                          get_fake_volume(),
                          connector)

    def test_initialize_connection_iscsi_volume_not_mapped(self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         mock.Mock(return_value=[]))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fake.VOLUME_MAPPING))
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        fake_eseries_volume['listOfMappings'] = [
            eseries_fake.VOLUME_MAPPING
        ]
        self.mock_object(self.library._client, 'list_volume',
                         mock.Mock(return_value=fake_eseries_volume))

        self.library.initialize_connection_iscsi(get_fake_volume(), connector)

        self.assertTrue(
            self.library._client.get_volume_mappings_for_volume.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_iscsi_volume_not_mapped_host_does_not_exist(
            self):
        connector = {'initiator': eseries_fake.INITIATOR_NAME}
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         mock.Mock(return_value=[]))
        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[]))
        self.mock_object(self.library._client, 'create_host_with_ports',
                         mock.Mock(return_value=eseries_fake.HOST))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fake.VOLUME_MAPPING))
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        fake_eseries_volume['listOfMappings'] = [
            eseries_fake.VOLUME_MAPPING
        ]
        self.mock_object(self.library._client, 'list_volume',
                         mock.Mock(return_value=fake_eseries_volume))

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
                         mock.Mock(
                             return_value=eseries_fake.VOLUME_MAPPING))
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.mock_object(self.library._client, 'list_volume',
                         mock.Mock(return_value=fake_eseries_volume))

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
                         mock.Mock(
                             side_effect=exception.NetAppDriverException))

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
                         mock.Mock(return_value=host_list))

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
                         mock.Mock(return_value=host_list))

        actual_host = self.library._get_host_with_matching_port(
            port_ids)

        self.assertEqual(host, actual_host)

    def test_terminate_connection_fc_no_hosts(self):
        connector = {'wwpns': [eseries_fake.WWPN]}

        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[]))

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
        self.mock_object(self.library, '_get_volume',
                         mock.Mock(return_value=volume))

        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[fake_host]))

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
                         mock.Mock(return_value=[fake_host]))
        self.mock_object(self.library._client, 'list_volume',
                         mock.Mock(return_value=fake_eseries_volume))
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
                         mock.Mock(return_value=[fake_host]))
        self.mock_object(self.library._client, 'list_volume',
                         mock.Mock(return_value=fake_eseries_volume))
        self.mock_object(host_mapper, 'unmap_volume_from_host')
        self.mock_object(self.library._client, 'get_volume_mappings_for_host',
                         mock.Mock(return_value=[copy.deepcopy
                                                 (eseries_fake.
                                                  VOLUME_MAPPING)]))

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
                         mock.Mock(return_value=[fake_host]))
        self.mock_object(self.library._client, 'list_volume',
                         mock.Mock(return_value=fake_eseries_volume))
        self.mock_object(host_mapper, 'unmap_volume_from_host')
        self.mock_object(self.library._client, 'get_volume_mappings_for_host',
                         mock.Mock(return_value=[]))

        target_info = self.library.terminate_connection_fc(get_fake_volume(),
                                                           connector)
        self.assertDictEqual(expected_target_info, target_info)

        self.assertTrue(host_mapper.unmap_volume_from_host.called)

    def test_terminate_connection_fc_not_mapped_host_with_wwpn_does_not_exist(
            self):
        connector = {'wwpns': [eseries_fake.WWPN]}
        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[eseries_fake.HOST_2]))
        self.assertRaises(exception.NotFound,
                          self.library.terminate_connection_fc,
                          get_fake_volume(),
                          connector)

    def test_initialize_connection_fc_volume_not_mapped(self):
        connector = {'wwpns': [eseries_fake.WWPN]}
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         mock.Mock(return_value=[]))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fake.VOLUME_MAPPING))
        expected_target_info = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_discovered': True,
                'target_lun': 0,
                'target_wwn': [eseries_fake.WWPN_2],
                'access_mode': 'rw',
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
                         mock.Mock(return_value=[]))
        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[]))
        self.mock_object(self.library._client, 'create_host_with_ports',
                         mock.Mock(return_value=eseries_fake.HOST))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fake.VOLUME_MAPPING))

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
                         mock.Mock(
                             return_value=eseries_fake.VOLUME_MAPPING))

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
                         mock.Mock(
                             side_effect=exception.NetAppDriverException))

        self.assertRaises(exception.NetAppDriverException,
                          self.library.initialize_connection_fc,
                          get_fake_volume(), connector)

        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_fc_no_target_wwpns(self):
        """Should be a no-op"""
        connector = {'wwpns': [eseries_fake.WWPN]}
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fake.VOLUME_MAPPING))
        self.mock_object(self.library._client, 'list_target_wwpns',
                         mock.Mock(return_value=[]))

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
            self.library._client, 'get_firmware_version',
            mock.Mock(return_value=(
                eseries_fake.FAKE_ASUP_DATA['system-version'])))
        self.mock_object(
            self.library._client, 'get_serial_numbers',
            mock.Mock(return_value=eseries_fake.FAKE_SERIAL_NUMBERS))
        self.mock_object(
            self.library._client, 'get_model_name',
            mock.Mock(
                return_value=eseries_fake.FAKE_CONTROLLERS[0]['modelName']))
        self.mock_object(
            self.library._client, 'set_counter',
            mock.Mock(return_value={'value': 1}))
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
        self.library.check_for_setup_error()

    def test_do_setup_host_group_already_exists(self):
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        self.mock_object(self.library,
                         '_check_mode_get_or_register_storage_system')
        fake_rest_client = eseries_fake.FakeEseriesClient()
        self.mock_object(self.library, '_create_rest_client',
                         mock.Mock(return_value=fake_rest_client))
        mock_create = self.mock_object(fake_rest_client, 'create_host_group')

        self.library.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        self.assertFalse(mock_create.call_count)

    def test_do_setup_host_group_does_not_exist(self):
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        fake_rest_client = eseries_fake.FakeEseriesClient()
        self.mock_object(self.library, '_create_rest_client',
                         mock.Mock(return_value=fake_rest_client))
        mock_get_host_group = self.mock_object(
            fake_rest_client, "get_host_group_by_name",
            mock.Mock(side_effect=exception.NotFound))
        self.mock_object(self.library,
                         '_check_mode_get_or_register_storage_system')

        self.library.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        self.assertTrue(mock_get_host_group.call_count)

    def test_create_volume(self):
        self.library._client.create_volume = mock.Mock(
            return_value=eseries_fake.VOLUME)

        self.library.create_volume(get_fake_volume())
        self.assertTrue(self.library._client.create_volume.call_count)

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

    def test_create_volume_from_snapshot(self):
        fake_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.mock_object(self.library, "_schedule_and_create_volume",
                         mock.Mock(return_value=fake_eseries_volume))
        self.mock_object(self.library, "_create_snapshot_volume",
                         mock.Mock(return_value=fake_eseries_volume))
        self.mock_object(self.library._client, "delete_snapshot_volume")

        self.library.create_volume_from_snapshot(
            get_fake_volume(), fake_snapshot.fake_snapshot_obj(None))

        self.assertEqual(
            1, self.library._schedule_and_create_volume.call_count)
        self.assertEqual(1, self.library._create_snapshot_volume.call_count)
        self.assertEqual(
            1, self.library._client.delete_snapshot_volume.call_count)

    def test_create_volume_from_snapshot_create_fails(self):
        fake_dest_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.mock_object(self.library, "_schedule_and_create_volume",
                         mock.Mock(return_value=fake_dest_eseries_volume))
        self.mock_object(self.library, "_create_snapshot_volume",
                         mock.Mock(side_effect=exception.NetAppDriverException)
                         )
        self.mock_object(self.library._client, "delete_snapshot_volume")
        self.mock_object(self.library._client, "delete_volume")

        self.assertRaises(exception.NetAppDriverException,
                          self.library.create_volume_from_snapshot,
                          get_fake_volume(),
                          fake_snapshot.fake_snapshot_obj(None))

        self.assertEqual(
            1, self.library._schedule_and_create_volume.call_count)
        self.assertEqual(1, self.library._create_snapshot_volume.call_count)
        self.assertEqual(
            0, self.library._client.delete_snapshot_volume.call_count)
        # Ensure the volume we were going to copy to is cleaned up
        self.library._client.delete_volume.assert_called_once_with(
            fake_dest_eseries_volume['volumeRef'])

    def test_create_volume_from_snapshot_copy_job_fails(self):
        fake_dest_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        self.mock_object(self.library, "_schedule_and_create_volume",
                         mock.Mock(return_value=fake_dest_eseries_volume))
        self.mock_object(self.library, "_create_snapshot_volume",
                         mock.Mock(return_value=fake_dest_eseries_volume))
        self.mock_object(self.library._client, "delete_snapshot_volume")
        self.mock_object(self.library._client, "delete_volume")

        fake_failed_volume_copy_job = copy.deepcopy(
            eseries_fake.VOLUME_COPY_JOB)
        fake_failed_volume_copy_job['status'] = 'failed'
        self.mock_object(self.library._client,
                         "create_volume_copy_job",
                         mock.Mock(return_value=fake_failed_volume_copy_job))
        self.mock_object(self.library._client,
                         "list_vol_copy_job",
                         mock.Mock(return_value=fake_failed_volume_copy_job))

        self.assertRaises(exception.NetAppDriverException,
                          self.library.create_volume_from_snapshot,
                          get_fake_volume(),
                          fake_snapshot.fake_snapshot_obj(None))

        self.assertEqual(
            1, self.library._schedule_and_create_volume.call_count)
        self.assertEqual(1, self.library._create_snapshot_volume.call_count)
        self.assertEqual(
            1, self.library._client.delete_snapshot_volume.call_count)
        # Ensure the volume we were going to copy to is cleaned up
        self.library._client.delete_volume.assert_called_once_with(
            fake_dest_eseries_volume['volumeRef'])

    def test_create_volume_from_snapshot_fail_to_delete_snapshot_volume(self):
        fake_dest_eseries_volume = copy.deepcopy(eseries_fake.VOLUME)
        fake_dest_eseries_volume['volumeRef'] = 'fake_volume_ref'
        self.mock_object(self.library, "_schedule_and_create_volume",
                         mock.Mock(return_value=fake_dest_eseries_volume))
        self.mock_object(self.library, "_create_snapshot_volume",
                         mock.Mock(return_value=copy.deepcopy(
                             eseries_fake.VOLUME)))
        self.mock_object(self.library._client, "delete_snapshot_volume",
                         mock.Mock(side_effect=exception.NetAppDriverException)
                         )
        self.mock_object(self.library._client, "delete_volume")

        self.library.create_volume_from_snapshot(
            get_fake_volume(), fake_snapshot.fake_snapshot_obj(None))

        self.assertEqual(
            1, self.library._schedule_and_create_volume.call_count)
        self.assertEqual(1, self.library._create_snapshot_volume.call_count)
        self.assertEqual(
            1, self.library._client.delete_snapshot_volume.call_count)
        # Ensure the volume we created is not cleaned up
        self.assertEqual(0, self.library._client.delete_volume.call_count)

    def test_extend_volume(self):
        fake_volume = copy.deepcopy(get_fake_volume())
        volume = copy.deepcopy(eseries_fake.VOLUME)
        new_capacity = 10
        volume['objectType'] = 'volume'
        self.library.create_cloned_volume = mock.Mock()
        self.library._get_volume = mock.Mock(return_value=volume)
        self.library._client.update_volume = mock.Mock()

        self.library.extend_volume(fake_volume, new_capacity)

        self.library.create_cloned_volume.assert_called_with(mock.ANY,
                                                             fake_volume)

    def test_extend_volume_thin(self):
        fake_volume = copy.deepcopy(get_fake_volume())
        volume = copy.deepcopy(eseries_fake.VOLUME)
        new_capacity = 10
        volume['objectType'] = 'thinVolume'
        self.library._client.expand_volume = mock.Mock(return_value=volume)
        self.library._get_volume = mock.Mock(return_value=volume)

        self.library.extend_volume(fake_volume, new_capacity)

        self.library._client.expand_volume.assert_called_with(volume['id'],
                                                              new_capacity)

    def test_extend_volume_stage_2_failure(self):
        fake_volume = copy.deepcopy(get_fake_volume())
        volume = copy.deepcopy(eseries_fake.VOLUME)
        new_capacity = 10
        volume['objectType'] = 'volume'
        self.library.create_cloned_volume = mock.Mock()
        self.library._client.delete_volume = mock.Mock()
        # Create results for multiple calls to _get_volume and _update_volume
        get_volume_results = [volume, {'id': 'newId', 'label': 'newVolume'}]
        self.library._get_volume = mock.Mock(side_effect=get_volume_results)
        update_volume_results = [volume, exception.NetAppDriverException,
                                 volume]
        self.library._client.update_volume = mock.Mock(
            side_effect=update_volume_results)

        self.assertRaises(exception.NetAppDriverException,
                          self.library.extend_volume, fake_volume,
                          new_capacity)
        self.assertTrue(self.library._client.delete_volume.called)

    def test_extend_volume_stage_1_failure(self):
        fake_volume = copy.deepcopy(get_fake_volume())
        volume = copy.deepcopy(eseries_fake.VOLUME)
        new_capacity = 10
        volume['objectType'] = 'volume'
        self.library.create_cloned_volume = mock.Mock()
        self.library._get_volume = mock.Mock(return_value=volume)
        self.library._client.update_volume = mock.Mock(
            side_effect=exception.NetAppDriverException)

        self.assertRaises(exception.NetAppDriverException,
                          self.library.extend_volume, fake_volume,
                          new_capacity)

    def test_delete_non_existing_volume(self):
        volume2 = get_fake_volume()
        # Change to a nonexistent id.
        volume2['name_id'] = '88888888-4444-4444-4444-cccccccccccc'
        self.assertIsNone(self.library.delete_volume(volume2))

    def test_map_volume_to_host_volume_not_mapped(self):
        """Map the volume directly to destination host."""
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         mock.Mock(return_value=[]))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fake.VOLUME_MAPPING))

        self.library.map_volume_to_host(get_fake_volume(),
                                        eseries_fake.VOLUME,
                                        eseries_fake.INITIATOR_NAME_2)

        self.assertTrue(
            self.library._client.get_volume_mappings_for_volume.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_map_volume_to_host_volume_not_mapped_host_does_not_exist(self):
        """Should create the host map directly to the host."""
        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[]))
        self.mock_object(self.library._client, 'create_host_with_ports',
                         mock.Mock(
                             return_value=eseries_fake.HOST_2))
        self.mock_object(self.library._client,
                         'get_volume_mappings_for_volume',
                         mock.Mock(return_value=[]))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fake.VOLUME_MAPPING))

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
                         mock.Mock(
                             return_value=eseries_fake.VOLUME_MAPPING))

        self.library.map_volume_to_host(get_fake_volume(),
                                        eseries_fake.VOLUME,
                                        eseries_fake.INITIATOR_NAME)

        self.assertTrue(host_mapper.map_volume_to_multiple_hosts.called)
