# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
# Copyright (c) 2015 Alex Meade.  All rights reserved.
# Copyright (c) 2015 Rushil Chugh.  All rights reserved.
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
Mock unit tests for the NetApp E-series iscsi driver
"""

import copy

import mock
import six

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.netapp.eseries import fakes as \
    eseries_fakes
from cinder.volume.drivers.netapp.eseries import client as es_client
from cinder.volume.drivers.netapp.eseries import host_mapper
from cinder.volume.drivers.netapp.eseries import iscsi as es_iscsi
from cinder.volume.drivers.netapp.eseries import utils
from cinder.volume.drivers.netapp import utils as na_utils


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


class NetAppEseriesISCSIDriverTestCase(test.TestCase):
    def setUp(self):
        super(NetAppEseriesISCSIDriverTestCase, self).setUp()

        kwargs = {'configuration':
                  eseries_fakes.create_configuration_eseries()}

        self.driver = es_iscsi.NetAppEseriesISCSIDriver(**kwargs)
        self.driver._client = eseries_fakes.FakeEseriesClient()
        self.driver.check_for_setup_error()

    def test_do_setup(self):
        self.mock_object(es_iscsi.NetAppEseriesISCSIDriver,
                         '_check_mode_get_or_register_storage_system')
        self.mock_object(es_client, 'RestClient',
                         eseries_fakes.FakeEseriesClient)
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        self.driver.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)

    def test_update_ssc_info(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'driveMediaType': 'ssd'}]

        self.driver._objects["disk_pool_refs"] = ['test_vg1']
        self.driver._client.list_storage_pools = mock.Mock(return_value=[])
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        self.driver._update_ssc_info()

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SSD'}},
                         self.driver._ssc_stats)

    def test_update_ssc_disk_types_ssd(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'driveMediaType': 'ssd'}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SSD'}},
                         ssc_stats)

    def test_update_ssc_disk_types_scsi(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'scsi'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SCSI'}},
                         ssc_stats)

    def test_update_ssc_disk_types_fcal(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'fibre'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'FCAL'}},
                         ssc_stats)

    def test_update_ssc_disk_types_sata(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'sata'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SATA'}},
                         ssc_stats)

    def test_update_ssc_disk_types_sas(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'sas'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SAS'}},
                         ssc_stats)

    def test_update_ssc_disk_types_unknown(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'unknown'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'unknown'}},
                         ssc_stats)

    def test_update_ssc_disk_types_undefined(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': '__UNDEFINED'}}]
        self.driver._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.driver._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'unknown'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_enabled(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'enabled'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'true'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_unknown(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'unknown'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_none(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'none'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_capable(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'capable'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_garbage(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'garbage'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1'])

        self.assertRaises(TypeError, 'test_vg1',
                          {'netapp_disk_encryption': 'false'}, ssc_stats)

    def test_update_ssc_disk_encryption_multiple(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'none'},
                 {'volumeGroupRef': 'test_vg2', 'securityType': 'enabled'}]
        self.driver._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.driver._update_ssc_disk_encryption(['test_vg1',
                                                            'test_vg2'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'},
                          'test_vg2': {'netapp_disk_encryption': 'true'}},
                         ssc_stats)

    def test_terminate_connection_no_hosts(self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}

        self.mock_object(self.driver._client, 'list_hosts',
                         mock.Mock(return_value=[]))

        self.assertRaises(exception.NotFound,
                          self.driver.terminate_connection,
                          get_fake_volume(),
                          connector)

    def test_terminate_connection_volume_not_mapped(self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        err = self.assertRaises(exception.NetAppDriverException,
                                self.driver.terminate_connection,
                                get_fake_volume(),
                                connector)
        self.assertIn("not currently mapped to host", six.text_type(err))

    def test_terminate_connection_volume_mapped(self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_eseries_volume['listOfMappings'] = [
            eseries_fakes.VOLUME_MAPPING
        ]
        self.mock_object(self.driver._client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        self.mock_object(host_mapper, 'unmap_volume_from_host')

        self.driver.terminate_connection(get_fake_volume(), connector)

        self.assertTrue(host_mapper.unmap_volume_from_host.called)

    def test_terminate_connection_volume_not_mapped_initiator_does_not_exist(
            self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        self.mock_object(self.driver._client, 'list_hosts',
                         mock.Mock(return_value=[eseries_fakes.HOST_2]))
        self.assertRaises(exception.NotFound,
                          self.driver.terminate_connection,
                          get_fake_volume(),
                          connector)

    def test_initialize_connection_volume_not_mapped(self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        self.mock_object(self.driver._client, 'get_volume_mappings',
                         mock.Mock(return_value=[]))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.driver.initialize_connection(get_fake_volume(), connector)

        self.assertTrue(self.driver._client.get_volume_mappings.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_volume_not_mapped_host_does_not_exist(self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        self.mock_object(self.driver._client, 'get_volume_mappings',
                         mock.Mock(return_value=[]))
        self.mock_object(self.driver._client, 'list_hosts',
                         mock.Mock(return_value=[]))
        self.mock_object(self.driver._client, 'create_host_with_port',
                         mock.Mock(return_value=eseries_fakes.HOST))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.driver.initialize_connection(get_fake_volume(), connector)

        self.assertTrue(self.driver._client.get_volume_mappings.called)
        self.assertTrue(self.driver._client.list_hosts.called)
        self.assertTrue(self.driver._client.create_host_with_port.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_volume_already_mapped_to_target_host(self):
        """Should be a no-op"""
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.driver.initialize_connection(get_fake_volume(), connector)

        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_volume_mapped_to_another_host(self):
        """Should raise error saying multiattach not enabled"""
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        fake_mapping_to_other_host = copy.deepcopy(
            eseries_fakes.VOLUME_MAPPING)
        fake_mapping_to_other_host['mapRef'] = eseries_fakes.HOST_2[
            'hostRef']
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             side_effect=exception.NetAppDriverException))

        self.assertRaises(exception.NetAppDriverException,
                          self.driver.initialize_connection,
                          get_fake_volume(), connector)

        self.assertTrue(host_mapper.map_volume_to_single_host.called)


class NetAppEseriesISCSIDriverMultiAttachTestCase(test.TestCase):
    """Test driver behavior when the netapp_enable_multiattach
    configuration option is True.
    """

    def setUp(self):
        super(NetAppEseriesISCSIDriverMultiAttachTestCase, self).setUp()
        config = eseries_fakes.create_configuration_eseries()
        config.netapp_enable_multiattach = True

        kwargs = {'configuration': config}

        self.driver = es_iscsi.NetAppEseriesISCSIDriver(**kwargs)
        self.driver._client = eseries_fakes.FakeEseriesClient()
        self.driver.check_for_setup_error()

    def test_do_setup_host_group_already_exists(self):
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        self.mock_object(es_iscsi.NetAppEseriesISCSIDriver,
                         '_check_mode_get_or_register_storage_system')
        fake_rest_client = eseries_fakes.FakeEseriesClient()
        self.mock_object(self.driver, '_create_rest_client',
                         mock.Mock(return_value=fake_rest_client))
        mock_create = self.mock_object(fake_rest_client, 'create_host_group')

        self.driver.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        self.assertFalse(mock_create.call_count)

    def test_do_setup_host_group_does_not_exist(self):
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        fake_rest_client = eseries_fakes.FakeEseriesClient()
        self.mock_object(self.driver, '_create_rest_client',
                         mock.Mock(return_value=fake_rest_client))
        mock_get_host_group = self.mock_object(
            fake_rest_client, "get_host_group_by_name",
            mock.Mock(side_effect=exception.NotFound))
        self.mock_object(es_iscsi.NetAppEseriesISCSIDriver,
                         '_check_mode_get_or_register_storage_system')

        self.driver.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        self.assertTrue(mock_get_host_group.call_count)

    def test_create_volume(self):
        self.driver._client.create_volume = mock.Mock(
            return_value=eseries_fakes.VOLUME)

        self.driver.create_volume(get_fake_volume())
        self.assertTrue(self.driver._client.create_volume.call_count)

    def test_create_volume_too_many_volumes(self):
        self.driver._client.list_volumes = mock.Mock(
            return_value=[eseries_fakes.VOLUME for __ in
                          range(utils.MAX_LUNS_PER_HOST_GROUP + 1)])
        self.driver._client.create_volume = mock.Mock(
            return_value=eseries_fakes.VOLUME)

        self.assertRaises(exception.NetAppDriverException,
                          self.driver.create_volume,
                          get_fake_volume())
        self.assertFalse(self.driver._client.create_volume.call_count)

    def test_initialize_connection_volume_not_mapped(self):
        """Map the volume directly to destination host.
        """
        connector = {'initiator': eseries_fakes.INITIATOR_NAME_2}
        self.mock_object(self.driver._client, 'get_volume_mappings',
                         mock.Mock(return_value=[]))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.driver.initialize_connection(get_fake_volume(), connector)

        self.assertTrue(self.driver._client.get_volume_mappings.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_volume_not_mapped_host_does_not_exist(self):
        """Should create the host map directly to the host."""
        connector = {'initiator': eseries_fakes.INITIATOR_NAME_2}
        self.mock_object(self.driver._client, 'list_hosts',
                         mock.Mock(return_value=[]))
        self.mock_object(self.driver._client, 'create_host_with_port',
                         mock.Mock(
                             return_value=eseries_fakes.HOST_2))
        self.mock_object(self.driver._client, 'get_volume_mappings',
                         mock.Mock(return_value=[]))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.driver.initialize_connection(get_fake_volume(), connector)

        self.assertTrue(self.driver._client.create_host_with_port.called)
        self.assertTrue(self.driver._client.get_volume_mappings.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_volume_already_mapped(self):
        """Should be a no-op."""
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        self.mock_object(host_mapper, 'map_volume_to_multiple_hosts',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.driver.initialize_connection(get_fake_volume(), connector)

        self.assertTrue(host_mapper.map_volume_to_multiple_hosts.called)
