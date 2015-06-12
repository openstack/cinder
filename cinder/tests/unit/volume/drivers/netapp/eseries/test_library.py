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

import copy

import mock
import six

from cinder import exception
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit.volume.drivers.netapp.eseries import fakes as \
    eseries_fakes
from cinder.volume.drivers.netapp.eseries import client as es_client
from cinder.volume.drivers.netapp.eseries import host_mapper
from cinder.volume.drivers.netapp.eseries import library
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


class NetAppEseriesLibraryTestCase(test.TestCase):
    def setUp(self):
        super(NetAppEseriesLibraryTestCase, self).setUp()

        kwargs = {'configuration':
                  eseries_fakes.create_configuration_eseries()}

        self.library = library.NetAppESeriesLibrary('FAKE', **kwargs)
        self.library._client = eseries_fakes.FakeEseriesClient()
        self.library.check_for_setup_error()

    def test_do_setup(self):
        self.mock_object(self.library,
                         '_check_mode_get_or_register_storage_system')
        self.mock_object(es_client, 'RestClient',
                         eseries_fakes.FakeEseriesClient)
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        self.library.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)

    def test_update_ssc_info(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'driveMediaType': 'ssd'}]

        self.library._get_storage_pools = mock.Mock(return_value=['test_vg1'])
        self.library._client.list_storage_pools = mock.Mock(return_value=[])
        self.library._client.list_drives = mock.Mock(return_value=drives)

        self.library._update_ssc_info()

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SSD'}},
                         self.library._ssc_stats)

    def test_update_ssc_disk_types_ssd(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'driveMediaType': 'ssd'}]
        self.library._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.library._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SSD'}},
                         ssc_stats)

    def test_update_ssc_disk_types_scsi(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'scsi'}}]
        self.library._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.library._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SCSI'}},
                         ssc_stats)

    def test_update_ssc_disk_types_fcal(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'fibre'}}]
        self.library._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.library._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'FCAL'}},
                         ssc_stats)

    def test_update_ssc_disk_types_sata(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'sata'}}]
        self.library._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.library._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SATA'}},
                         ssc_stats)

    def test_update_ssc_disk_types_sas(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'sas'}}]
        self.library._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.library._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'SAS'}},
                         ssc_stats)

    def test_update_ssc_disk_types_unknown(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': 'unknown'}}]
        self.library._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.library._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'unknown'}},
                         ssc_stats)

    def test_update_ssc_disk_types_undefined(self):
        drives = [{'currentVolumeGroupRef': 'test_vg1',
                   'interfaceType': {'driveType': '__UNDEFINED'}}]
        self.library._client.list_drives = mock.Mock(return_value=drives)

        ssc_stats = self.library._update_ssc_disk_types(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_type': 'unknown'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_enabled(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'enabled'}]
        self.library._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'true'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_unknown(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'unknown'}]
        self.library._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_none(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'none'}]
        self.library._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_capable(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'capable'}]
        self.library._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_disk_encryption(['test_vg1'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'}},
                         ssc_stats)

    def test_update_ssc_disk_encryption_SecType_garbage(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'garbage'}]
        self.library._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_disk_encryption(['test_vg1'])

        self.assertRaises(TypeError, 'test_vg1',
                          {'netapp_disk_encryption': 'false'}, ssc_stats)

    def test_update_ssc_disk_encryption_multiple(self):
        pools = [{'volumeGroupRef': 'test_vg1', 'securityType': 'none'},
                 {'volumeGroupRef': 'test_vg2', 'securityType': 'enabled'}]
        self.library._client.list_storage_pools = mock.Mock(return_value=pools)

        ssc_stats = self.library._update_ssc_disk_encryption(['test_vg1',
                                                              'test_vg2'])

        self.assertEqual({'test_vg1': {'netapp_disk_encryption': 'false'},
                          'test_vg2': {'netapp_disk_encryption': 'true'}},
                         ssc_stats)

    def test_terminate_connection_iscsi_no_hosts(self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}

        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[]))

        self.assertRaises(exception.NotFound,
                          self.library.terminate_connection_iscsi,
                          get_fake_volume(),
                          connector)

    def test_terminate_connection_iscsi_volume_not_mapped(self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        err = self.assertRaises(exception.NetAppDriverException,
                                self.library.terminate_connection_iscsi,
                                get_fake_volume(),
                                connector)
        self.assertIn("not currently mapped to host", six.text_type(err))

    def test_terminate_connection_iscsi_volume_mapped(self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_eseries_volume['listOfMappings'] = [
            eseries_fakes.VOLUME_MAPPING
        ]
        self.mock_object(self.library._client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        self.mock_object(host_mapper, 'unmap_volume_from_host')

        self.library.terminate_connection_iscsi(get_fake_volume(), connector)

        self.assertTrue(host_mapper.unmap_volume_from_host.called)

    def test_terminate_connection_iscsi_not_mapped_initiator_does_not_exist(
            self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[eseries_fakes.HOST_2]))
        self.assertRaises(exception.NotFound,
                          self.library.terminate_connection_iscsi,
                          get_fake_volume(),
                          connector)

    def test_initialize_connection_iscsi_volume_not_mapped(self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        self.mock_object(self.library._client, 'get_volume_mappings',
                         mock.Mock(return_value=[]))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.library.initialize_connection_iscsi(get_fake_volume(), connector)

        self.assertTrue(self.library._client.get_volume_mappings.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_iscsi_volume_not_mapped_host_does_not_exist(
            self):
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        self.mock_object(self.library._client, 'get_volume_mappings',
                         mock.Mock(return_value=[]))
        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[]))
        self.mock_object(self.library._client, 'create_host_with_port',
                         mock.Mock(return_value=eseries_fakes.HOST))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.library.initialize_connection_iscsi(get_fake_volume(), connector)

        self.assertTrue(self.library._client.get_volume_mappings.called)
        self.assertTrue(self.library._client.list_hosts.called)
        self.assertTrue(self.library._client.create_host_with_port.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_iscsi_volume_already_mapped_to_target_host(
            self):
        """Should be a no-op"""
        connector = {'initiator': eseries_fakes.INITIATOR_NAME}
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.library.initialize_connection_iscsi(get_fake_volume(), connector)

        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_initialize_connection_iscsi_volume_mapped_to_another_host(self):
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
                          self.library.initialize_connection_iscsi,
                          get_fake_volume(), connector)

        self.assertTrue(host_mapper.map_volume_to_single_host.called)


class NetAppEseriesLibraryMultiAttachTestCase(test.TestCase):
    """Test driver behavior when the netapp_enable_multiattach
    configuration option is True.
    """

    def setUp(self):
        super(NetAppEseriesLibraryMultiAttachTestCase, self).setUp()
        config = eseries_fakes.create_configuration_eseries()
        config.netapp_enable_multiattach = True

        kwargs = {'configuration': config}

        self.library = library.NetAppESeriesLibrary("FAKE", **kwargs)
        self.library._client = eseries_fakes.FakeEseriesClient()
        self.library.check_for_setup_error()

    def test_do_setup_host_group_already_exists(self):
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        self.mock_object(self.library,
                         '_check_mode_get_or_register_storage_system')
        fake_rest_client = eseries_fakes.FakeEseriesClient()
        self.mock_object(self.library, '_create_rest_client',
                         mock.Mock(return_value=fake_rest_client))
        mock_create = self.mock_object(fake_rest_client, 'create_host_group')

        self.library.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        self.assertFalse(mock_create.call_count)

    def test_do_setup_host_group_does_not_exist(self):
        mock_check_flags = self.mock_object(na_utils, 'check_flags')
        fake_rest_client = eseries_fakes.FakeEseriesClient()
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
            return_value=eseries_fakes.VOLUME)

        self.library.create_volume(get_fake_volume())
        self.assertTrue(self.library._client.create_volume.call_count)

    def test_create_volume_too_many_volumes(self):
        self.library._client.list_volumes = mock.Mock(
            return_value=[eseries_fakes.VOLUME for __ in
                          range(utils.MAX_LUNS_PER_HOST_GROUP + 1)])
        self.library._client.create_volume = mock.Mock(
            return_value=eseries_fakes.VOLUME)

        self.assertRaises(exception.NetAppDriverException,
                          self.library.create_volume,
                          get_fake_volume())
        self.assertFalse(self.library._client.create_volume.call_count)

    def test_create_volume_from_snapshot(self):
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
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
        fake_dest_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
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
        fake_dest_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        self.mock_object(self.library, "_schedule_and_create_volume",
                         mock.Mock(return_value=fake_dest_eseries_volume))
        self.mock_object(self.library, "_create_snapshot_volume",
                         mock.Mock(return_value=fake_dest_eseries_volume))
        self.mock_object(self.library._client, "delete_snapshot_volume")
        self.mock_object(self.library._client, "delete_volume")

        fake_failed_volume_copy_job = copy.deepcopy(
            eseries_fakes.VOLUME_COPY_JOB)
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
        fake_dest_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_dest_eseries_volume['volumeRef'] = 'fake_volume_ref'
        self.mock_object(self.library, "_schedule_and_create_volume",
                         mock.Mock(return_value=fake_dest_eseries_volume))
        self.mock_object(self.library, "_create_snapshot_volume",
                         mock.Mock(return_value=copy.deepcopy(
                             eseries_fakes.VOLUME)))
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

    def test_map_volume_to_host_volume_not_mapped(self):
        """Map the volume directly to destination host."""
        self.mock_object(self.library._client, 'get_volume_mappings',
                         mock.Mock(return_value=[]))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.library.map_volume_to_host(get_fake_volume(),
                                        eseries_fakes.VOLUME,
                                        eseries_fakes.INITIATOR_NAME_2)

        self.assertTrue(self.library._client.get_volume_mappings.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_map_volume_to_host_volume_not_mapped_host_does_not_exist(self):
        """Should create the host map directly to the host."""
        self.mock_object(self.library._client, 'list_hosts',
                         mock.Mock(return_value=[]))
        self.mock_object(self.library._client, 'create_host_with_port',
                         mock.Mock(
                             return_value=eseries_fakes.HOST_2))
        self.mock_object(self.library._client, 'get_volume_mappings',
                         mock.Mock(return_value=[]))
        self.mock_object(host_mapper, 'map_volume_to_single_host',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.library.map_volume_to_host(get_fake_volume(),
                                        eseries_fakes.VOLUME,
                                        eseries_fakes.INITIATOR_NAME_2)

        self.assertTrue(self.library._client.create_host_with_port.called)
        self.assertTrue(self.library._client.get_volume_mappings.called)
        self.assertTrue(host_mapper.map_volume_to_single_host.called)

    def test_map_volume_to_host_volume_already_mapped(self):
        """Should be a no-op."""
        self.mock_object(host_mapper, 'map_volume_to_multiple_hosts',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        self.library.map_volume_to_host(get_fake_volume(),
                                        eseries_fakes.VOLUME,
                                        eseries_fakes.INITIATOR_NAME)

        self.assertTrue(host_mapper.map_volume_to_multiple_hosts.called)
