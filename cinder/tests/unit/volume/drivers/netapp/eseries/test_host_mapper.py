# Copyright (c) 2015 Alex Meade.  All rights reserved.
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
"""Mock unit tests for the NetApp E-series iscsi driver."""

import copy

import mock
import six

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.netapp.eseries \
    import fakes as eseries_fakes
from cinder.volume.drivers.netapp.eseries import host_mapper
from cinder.volume.drivers.netapp.eseries import utils


def get_fake_volume():
    return {
        'id': '114774fb-e15a-4fae-8ee2-c9723e3645ef', 'size': 1,
        'volume_name': 'lun1', 'host': 'hostname@backend#DDP',
        'os_type': 'linux', 'provider_location': 'lun1',
        'name_id': '114774fb-e15a-4fae-8ee2-c9723e3645ef',
        'provider_auth': 'provider a b', 'project_id': 'project',
        'display_name': None, 'display_description': 'lun1',
        'volume_type_id': None, 'migration_status': None, 'attach_status':
        "detached", "status": "available"
    }

FAKE_MAPPINGS = [{u'lun': 1}]

FAKE_USED_UP_MAPPINGS = map(lambda n: {u'lun': n}, range(256))

FAKE_USED_UP_LUN_ID_DICT = {n: 1 for n in range(256)}

FAKE_UNUSED_LUN_ID = set([])

FAKE_USED_LUN_ID_DICT = ({0: 1, 1: 1})

FAKE_USED_LUN_IDS = [1, 2]

FAKE_SINGLE_USED_LUN_ID = 1

FAKE_USED_UP_LUN_IDS = range(256)


class NetAppEseriesHostMapperTestCase(test.TestCase):
    def setUp(self):
        super(NetAppEseriesHostMapperTestCase, self).setUp()

        self.client = eseries_fakes.FakeEseriesClient()

    def test_unmap_volume_from_host_volume_mapped_to_host(self):
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_eseries_volume['listOfMappings'] = [
            eseries_fakes.VOLUME_MAPPING
        ]
        self.mock_object(self.client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        self.mock_object(self.client, 'delete_volume_mapping')

        host_mapper.unmap_volume_from_host(self.client, get_fake_volume(),
                                           eseries_fakes.HOST,
                                           eseries_fakes.VOLUME_MAPPING)

        self.assertTrue(self.client.delete_volume_mapping.called)

    def test_unmap_volume_from_host_volume_mapped_to_different_host(self):
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        # Mapped to host 1
        fake_eseries_volume['listOfMappings'] = [
            eseries_fakes.VOLUME_MAPPING
        ]
        self.mock_object(self.client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        self.mock_object(self.client, 'delete_volume_mapping')
        self.mock_object(self.client, 'get_host_group',
                         mock.Mock(
                             side_effect=exception.NotFound))

        err = self.assertRaises(exception.NetAppDriverException,
                                host_mapper.unmap_volume_from_host,
                                self.client, get_fake_volume(),
                                eseries_fakes.HOST_2,
                                eseries_fakes.VOLUME_MAPPING)
        self.assertIn("not currently mapped to host", six.text_type(err))

    def test_unmap_volume_from_host_volume_mapped_to_host_group_but_not_host(
            self):
        """Test volume mapped to host not in specified host group.

        Ensure an error is raised if the specified host is not in the
        host group the volume is mapped to.
        """
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_volume_mapping = copy.deepcopy(eseries_fakes.VOLUME_MAPPING)
        fake_volume_mapping['mapRef'] = eseries_fakes.MULTIATTACH_HOST_GROUP[
            'clusterRef']
        fake_eseries_volume['listOfMappings'] = [fake_volume_mapping]
        self.mock_object(self.client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        fake_host = copy.deepcopy(eseries_fakes.HOST)
        fake_host['clusterRef'] = utils.NULL_REF
        self.mock_object(self.client, 'list_hosts',
                         mock.Mock(return_value=[fake_host]))

        err = self.assertRaises(exception.NetAppDriverException,
                                host_mapper.unmap_volume_from_host,
                                self.client, get_fake_volume(),
                                fake_host,
                                fake_volume_mapping)
        self.assertIn("not currently mapped to host", six.text_type(err))

    def test_unmap_volume_from_host_volume_mapped_to_multiattach_host_group(
            self):
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_volume_mapping = copy.deepcopy(eseries_fakes.VOLUME_MAPPING)
        fake_volume_mapping['mapRef'] = eseries_fakes.MULTIATTACH_HOST_GROUP[
            'clusterRef']
        fake_eseries_volume['listOfMappings'] = [fake_volume_mapping]
        self.mock_object(self.client, 'delete_volume_mapping')
        self.mock_object(self.client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        fake_volume = get_fake_volume()
        fake_volume['status'] = 'detaching'

        host_mapper.unmap_volume_from_host(self.client, fake_volume,
                                           eseries_fakes.HOST,
                                           fake_volume_mapping)

        self.assertTrue(self.client.delete_volume_mapping.called)

    def test_unmap_volume_from_host_volume_mapped_to_multiattach_host_group_and_migrating(  # noqa
            self):
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_volume_mapping = copy.deepcopy(eseries_fakes.VOLUME_MAPPING)
        fake_volume_mapping['mapRef'] = eseries_fakes.MULTIATTACH_HOST_GROUP[
            'clusterRef']
        fake_eseries_volume['listOfMappings'] = [fake_volume_mapping]
        self.mock_object(self.client, 'delete_volume_mapping')
        self.mock_object(self.client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        fake_volume = get_fake_volume()
        fake_volume['status'] = 'in-use'

        host_mapper.unmap_volume_from_host(self.client, fake_volume,
                                           eseries_fakes.HOST,
                                           fake_volume_mapping)

        self.assertFalse(self.client.delete_volume_mapping.called)

    def test_unmap_volume_from_host_volume_mapped_to_outside_host_group(self):
        """Test volume mapped to host group without host.

        Ensure we raise error when we find a volume is mapped to an unknown
        host group that does not have the host.
        """
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_volume_mapping = copy.deepcopy(eseries_fakes.VOLUME_MAPPING)
        fake_ref = "8500000060080E500023C7340036035F515B78FD"
        fake_volume_mapping['mapRef'] = fake_ref
        fake_eseries_volume['listOfMappings'] = [fake_volume_mapping]
        self.mock_object(self.client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        fake_host = copy.deepcopy(eseries_fakes.HOST)
        fake_host['clusterRef'] = utils.NULL_REF
        self.mock_object(self.client, 'list_hosts',
                         mock.Mock(return_value=[fake_host]))
        self.mock_object(self.client, 'get_host_group',
                         mock.Mock(return_value=
                                   eseries_fakes.FOREIGN_HOST_GROUP))

        err = self.assertRaises(exception.NetAppDriverException,
                                host_mapper.unmap_volume_from_host,
                                self.client, get_fake_volume(),
                                eseries_fakes.HOST,
                                fake_volume_mapping)
        self.assertIn("unsupported host group", six.text_type(err))

    def test_unmap_volume_from_host_volume_mapped_to_outside_host_group_w_host(
            self):
        """Test volume mapped to host in unknown host group.

        Ensure we raise error when we find a volume is mapped to an unknown
        host group that has the host.
        """
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_volume_mapping = copy.deepcopy(eseries_fakes.VOLUME_MAPPING)
        fake_ref = "8500000060080E500023C7340036035F515B78FD"
        fake_volume_mapping['mapRef'] = fake_ref
        fake_eseries_volume['clusterRef'] = fake_ref
        fake_eseries_volume['listOfMappings'] = [fake_volume_mapping]
        self.mock_object(self.client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        fake_host = copy.deepcopy(eseries_fakes.HOST)
        fake_host['clusterRef'] = utils.NULL_REF
        self.mock_object(self.client, 'list_hosts',
                         mock.Mock(return_value=[fake_host]))
        self.mock_object(self.client, 'get_host_group',
                         mock.Mock(return_value=
                                   eseries_fakes.FOREIGN_HOST_GROUP))

        err = self.assertRaises(exception.NetAppDriverException,
                                host_mapper.unmap_volume_from_host,
                                self.client, get_fake_volume(),
                                eseries_fakes.HOST,
                                fake_volume_mapping)

        self.assertIn("unsupported host group", six.text_type(err))

    def test_map_volume_to_single_host_volume_not_mapped(self):
        self.mock_object(self.client, 'create_volume_mapping',
                         mock.Mock(
                             return_value=eseries_fakes.VOLUME_MAPPING))

        host_mapper.map_volume_to_single_host(self.client, get_fake_volume(),
                                              eseries_fakes.VOLUME,
                                              eseries_fakes.HOST,
                                              None,
                                              False)

        self.assertTrue(self.client.create_volume_mapping.called)

    def test_map_volume_to_single_host_volume_already_mapped_to_target_host(
            self):
        """Should be a no-op"""
        self.mock_object(self.client, 'create_volume_mapping',
                         mock.Mock())

        host_mapper.map_volume_to_single_host(self.client,
                                              get_fake_volume(),
                                              eseries_fakes.VOLUME,
                                              eseries_fakes.HOST,
                                              eseries_fakes.VOLUME_MAPPING,
                                              False)

        self.assertFalse(self.client.create_volume_mapping.called)

    def test_map_volume_to_single_host_volume_mapped_to_multiattach_host_group(
            self):
        """Test map volume to a single host.

        Should move mapping to target host if volume is not migrating or
        attached(in-use). If volume is not in use then it should not require a
        mapping making it ok to sever the mapping to the host group.
        """
        fake_mapping_to_other_host = copy.deepcopy(
            eseries_fakes.VOLUME_MAPPING)
        fake_mapping_to_other_host['mapRef'] = \
            eseries_fakes.MULTIATTACH_HOST_GROUP['clusterRef']
        self.mock_object(self.client, 'move_volume_mapping_via_symbol',
                         mock.Mock(return_value={'lun': 5}))

        host_mapper.map_volume_to_single_host(self.client,
                                              get_fake_volume(),
                                              eseries_fakes.VOLUME,
                                              eseries_fakes.HOST,
                                              fake_mapping_to_other_host,
                                              False)

        self.assertTrue(self.client.move_volume_mapping_via_symbol.called)

    def test_map_volume_to_single_host_volume_mapped_to_multiattach_host_group_and_migrating(  # noqa
            self):
        """Should raise error saying multiattach not enabled"""
        fake_mapping_to_other_host = copy.deepcopy(
            eseries_fakes.VOLUME_MAPPING)
        fake_mapping_to_other_host['mapRef'] = \
            eseries_fakes.MULTIATTACH_HOST_GROUP['clusterRef']
        fake_volume = get_fake_volume()
        fake_volume['attach_status'] = "attached"

        err = self.assertRaises(exception.NetAppDriverException,
                                host_mapper.map_volume_to_single_host,
                                self.client, fake_volume,
                                eseries_fakes.VOLUME,
                                eseries_fakes.HOST,
                                fake_mapping_to_other_host,
                                False)

        self.assertIn('multiattach is disabled', six.text_type(err))

    def test_map_volume_to_single_host_volume_mapped_to_multiattach_host_group_and_attached(  # noqa
            self):
        """Should raise error saying multiattach not enabled"""
        fake_mapping_to_other_host = copy.deepcopy(
            eseries_fakes.VOLUME_MAPPING)
        fake_mapping_to_other_host['mapRef'] = \
            eseries_fakes.MULTIATTACH_HOST_GROUP['clusterRef']
        fake_volume = get_fake_volume()
        fake_volume['attach_status'] = "attached"

        err = self.assertRaises(exception.NetAppDriverException,
                                host_mapper.map_volume_to_single_host,
                                self.client, fake_volume,
                                eseries_fakes.VOLUME,
                                eseries_fakes.HOST,
                                fake_mapping_to_other_host,
                                False)

        self.assertIn('multiattach is disabled', six.text_type(err))

    def test_map_volume_to_single_host_volume_mapped_to_another_host(self):
        """Should raise error saying multiattach not enabled"""
        fake_mapping_to_other_host = copy.deepcopy(
            eseries_fakes.VOLUME_MAPPING)
        fake_mapping_to_other_host['mapRef'] = eseries_fakes.HOST_2[
            'hostRef']

        err = self.assertRaises(exception.NetAppDriverException,
                                host_mapper.map_volume_to_single_host,
                                self.client, get_fake_volume(),
                                eseries_fakes.VOLUME,
                                eseries_fakes.HOST,
                                fake_mapping_to_other_host,
                                False)

        self.assertIn('multiattach is disabled', six.text_type(err))

    def test_map_volume_to_multiple_hosts_volume_already_mapped_to_target_host(
            self):
        """Should be a no-op."""
        self.mock_object(self.client, 'create_volume_mapping',
                         mock.Mock())

        host_mapper.map_volume_to_multiple_hosts(self.client,
                                                 get_fake_volume(),
                                                 eseries_fakes.VOLUME,
                                                 eseries_fakes.HOST,
                                                 eseries_fakes.VOLUME_MAPPING)

        self.assertFalse(self.client.create_volume_mapping.called)

    def test_map_volume_to_multiple_hosts_volume_mapped_to_multiattach_host_group(  # noqa
            self):
        """Should ensure target host is in the multiattach host group."""
        fake_host = copy.deepcopy(eseries_fakes.HOST_2)
        fake_host['clusterRef'] = utils.NULL_REF

        fake_mapping_to_host_group = copy.deepcopy(
            eseries_fakes.VOLUME_MAPPING)
        fake_mapping_to_host_group['mapRef'] = \
            eseries_fakes.MULTIATTACH_HOST_GROUP['clusterRef']

        self.mock_object(self.client, 'set_host_group_for_host')
        self.mock_object(self.client, 'get_host_group',
                         mock.Mock(
                             return_value=eseries_fakes.MULTIATTACH_HOST_GROUP)
                         )

        host_mapper.map_volume_to_multiple_hosts(self.client,
                                                 get_fake_volume(),
                                                 eseries_fakes.VOLUME,
                                                 fake_host,
                                                 fake_mapping_to_host_group)

        self.assertEqual(
            1, self.client.set_host_group_for_host.call_count)

    def test_map_volume_to_multiple_hosts_volume_mapped_to_multiattach_host_group_with_lun_collision(  # noqa
            self):
        """Should ensure target host is in the multiattach host group."""
        fake_host = copy.deepcopy(eseries_fakes.HOST_2)
        fake_host['clusterRef'] = utils.NULL_REF
        fake_mapping_to_host_group = copy.deepcopy(
            eseries_fakes.VOLUME_MAPPING)
        fake_mapping_to_host_group['mapRef'] = \
            eseries_fakes.MULTIATTACH_HOST_GROUP['clusterRef']
        self.mock_object(self.client, 'set_host_group_for_host',
                         mock.Mock(side_effect=exception.NetAppDriverException)
                         )

        self.assertRaises(exception.NetAppDriverException,
                          host_mapper.map_volume_to_multiple_hosts,
                          self.client,
                          get_fake_volume(),
                          eseries_fakes.VOLUME,
                          fake_host,
                          fake_mapping_to_host_group)

    def test_map_volume_to_multiple_hosts_volume_mapped_to_another_host(self):
        """Test that mapping moves to another host group.

        Should ensure both existing host and destination host are in
        multiattach host group and move the mapping to the host group.
        """

        existing_host = copy.deepcopy(eseries_fakes.HOST)
        existing_host['clusterRef'] = utils.NULL_REF
        target_host = copy.deepcopy(eseries_fakes.HOST_2)
        target_host['clusterRef'] = utils.NULL_REF
        self.mock_object(self.client, 'get_host',
                         mock.Mock(return_value=existing_host))
        self.mock_object(self.client, 'set_host_group_for_host')
        self.mock_object(self.client, 'get_host_group',
                         mock.Mock(side_effect=exception.NotFound))
        mock_move_mapping = mock.Mock(
            return_value=eseries_fakes.VOLUME_MAPPING_TO_MULTIATTACH_GROUP)
        self.mock_object(self.client,
                         'move_volume_mapping_via_symbol',
                         mock_move_mapping)

        host_mapper.map_volume_to_multiple_hosts(self.client,
                                                 get_fake_volume(),
                                                 eseries_fakes.VOLUME,
                                                 target_host,
                                                 eseries_fakes.VOLUME_MAPPING)

        self.assertEqual(
            2, self.client.set_host_group_for_host.call_count)

        self.assertTrue(self.client.move_volume_mapping_via_symbol
                        .called)

    def test_map_volume_to_multiple_hosts_volume_mapped_to_another_host_with_lun_collision_with_source_host(  # noqa
            self):
        """Test moving source host to multiattach host group.

        Should fail attempting to move source host to multiattach host
        group and raise an error.
        """

        existing_host = copy.deepcopy(eseries_fakes.HOST)
        existing_host['clusterRef'] = utils.NULL_REF
        target_host = copy.deepcopy(eseries_fakes.HOST_2)
        target_host['clusterRef'] = utils.NULL_REF
        self.mock_object(self.client, 'get_host',
                         mock.Mock(return_value=existing_host))
        self.mock_object(self.client, 'set_host_group_for_host',
                         mock.Mock(side_effect=[
                             None,
                             exception.NetAppDriverException
                         ]))
        self.mock_object(self.client, 'get_host_group',
                         mock.Mock(side_effect=exception.NotFound))
        mock_move_mapping = mock.Mock(
            return_value=eseries_fakes.VOLUME_MAPPING_TO_MULTIATTACH_GROUP)
        self.mock_object(self.client,
                         'move_volume_mapping_via_symbol',
                         mock_move_mapping)

        self.assertRaises(exception.NetAppDriverException,
                          host_mapper.map_volume_to_multiple_hosts,
                          self.client,
                          get_fake_volume(),
                          eseries_fakes.VOLUME,
                          target_host,
                          eseries_fakes.VOLUME_MAPPING)

    def test_map_volume_to_multiple_hosts_volume_mapped_to_another_host_with_lun_collision_with_dest_host(  # noqa
            self):
        """Test moving destination host to multiattach host group.

        Should fail attempting to move destination host to multiattach host
        group and raise an error.
        """

        existing_host = copy.deepcopy(eseries_fakes.HOST)
        existing_host['clusterRef'] = utils.NULL_REF
        target_host = copy.deepcopy(eseries_fakes.HOST_2)
        target_host['clusterRef'] = utils.NULL_REF
        self.mock_object(self.client, 'get_host',
                         mock.Mock(return_value=existing_host))
        self.mock_object(self.client, 'set_host_group_for_host',
                         mock.Mock(side_effect=[
                             exception.NetAppDriverException,
                             None
                         ]))
        self.mock_object(self.client, 'get_host_group',
                         mock.Mock(side_effect=exception.NotFound))
        mock_move_mapping = mock.Mock(
            return_value=eseries_fakes.VOLUME_MAPPING_TO_MULTIATTACH_GROUP)
        self.mock_object(self.client,
                         'move_volume_mapping_via_symbol',
                         mock_move_mapping)

        self.assertRaises(exception.NetAppDriverException,
                          host_mapper.map_volume_to_multiple_hosts,
                          self.client,
                          get_fake_volume(),
                          eseries_fakes.VOLUME,
                          target_host,
                          eseries_fakes.VOLUME_MAPPING)

    def test_map_volume_to_multiple_hosts_volume_mapped_to_foreign_host_group(
            self):
        """Test a target when the host is in a foreign host group.

        Should raise an error stating the volume is mapped to an
        unsupported host group.
        """
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_volume_mapping = copy.deepcopy(eseries_fakes.VOLUME_MAPPING)
        fake_ref = "8500000060080E500023C7340036035F515B78FD"
        fake_volume_mapping['mapRef'] = fake_ref
        self.mock_object(self.client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        fake_host = copy.deepcopy(eseries_fakes.HOST)
        fake_host['clusterRef'] = utils.NULL_REF
        self.mock_object(self.client, 'get_host_group',
                         mock.Mock(return_value=
                                   eseries_fakes.FOREIGN_HOST_GROUP))

        err = self.assertRaises(exception.NetAppDriverException,
                                host_mapper.map_volume_to_multiple_hosts,
                                self.client,
                                get_fake_volume(),
                                eseries_fakes.VOLUME,
                                fake_host,
                                fake_volume_mapping)
        self.assertIn("unsupported host group", six.text_type(err))

    def test_map_volume_to_multiple_hosts_volume_mapped_to_host_in_foreign_host_group(  # noqa
            self):
        """Test a target when the host is in a foreign host group.

        Should raise an error stating the volume is mapped to a
        host that is in an unsupported host group.
        """
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_volume_mapping = copy.deepcopy(eseries_fakes.VOLUME_MAPPING)
        fake_host = copy.deepcopy(eseries_fakes.HOST_2)
        fake_host['clusterRef'] = eseries_fakes.FOREIGN_HOST_GROUP[
            'clusterRef']
        fake_volume_mapping['mapRef'] = fake_host['hostRef']
        fake_eseries_volume['listOfMappings'] = [fake_volume_mapping]
        self.mock_object(self.client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        self.mock_object(self.client, 'get_host',
                         mock.Mock(return_value=fake_host))
        self.mock_object(self.client, 'get_host_group',
                         mock.Mock(side_effect=[
                             eseries_fakes.FOREIGN_HOST_GROUP]))

        err = self.assertRaises(exception.NetAppDriverException,
                                host_mapper.map_volume_to_multiple_hosts,
                                self.client,
                                get_fake_volume(),
                                eseries_fakes.VOLUME,
                                eseries_fakes.HOST,
                                fake_volume_mapping)

        self.assertIn("unsupported host group", six.text_type(err))

    def test_map_volume_to_multiple_hosts_volume_target_host_in_foreign_host_group(  # noqa
            self):
        """Test a target when the host is in a foreign host group.

        Should raise an error stating the target host is in an
        unsupported host group.
        """
        fake_eseries_volume = copy.deepcopy(eseries_fakes.VOLUME)
        fake_volume_mapping = copy.deepcopy(eseries_fakes.VOLUME_MAPPING)
        fake_host = copy.deepcopy(eseries_fakes.HOST_2)
        fake_host['clusterRef'] = eseries_fakes.FOREIGN_HOST_GROUP[
            'clusterRef']
        self.mock_object(self.client, 'list_volumes',
                         mock.Mock(return_value=[fake_eseries_volume]))
        self.mock_object(self.client, 'get_host',
                         mock.Mock(return_value=eseries_fakes.HOST))
        self.mock_object(self.client, 'get_host_group',
                         mock.Mock(side_effect=[
                             eseries_fakes.FOREIGN_HOST_GROUP]))

        err = self.assertRaises(exception.NetAppDriverException,
                                host_mapper.map_volume_to_multiple_hosts,
                                self.client,
                                get_fake_volume(),
                                eseries_fakes.VOLUME,
                                fake_host,
                                fake_volume_mapping)

        self.assertIn("unsupported host group", six.text_type(err))

    def test_get_unused_lun_ids(self):
        unused_lun_ids = host_mapper._get_unused_lun_ids(FAKE_MAPPINGS)
        self.assertEqual(set(range(2, 256)), unused_lun_ids)

    def test_get_unused_lun_id_counter(self):
        used_lun_id_count = host_mapper._get_used_lun_id_counter(
            FAKE_MAPPINGS)
        self.assertEqual(FAKE_USED_LUN_ID_DICT, used_lun_id_count)

    def test_get_unused_lun_ids_used_up_luns(self):
        unused_lun_ids = host_mapper._get_unused_lun_ids(
            FAKE_USED_UP_MAPPINGS)
        self.assertEqual(FAKE_UNUSED_LUN_ID, unused_lun_ids)

    def test_get_lun_id_counter_used_up_luns(self):
        used_lun_ids = host_mapper._get_used_lun_id_counter(
            FAKE_USED_UP_MAPPINGS)
        self.assertEqual(FAKE_USED_UP_LUN_ID_DICT, used_lun_ids)

    def test_host_not_full(self):
        fake_host = copy.deepcopy(eseries_fakes.HOST)
        self.assertFalse(host_mapper._is_host_full(self.client, fake_host))

    def test_host_full(self):
        fake_host = copy.deepcopy(eseries_fakes.HOST)
        self.mock_object(self.client, 'get_volume_mappings_for_host',
                         mock.Mock(return_value=FAKE_USED_UP_MAPPINGS))
        self.assertTrue(host_mapper._is_host_full(self.client, fake_host))

    def test_get_free_lun(self):
        fake_host = copy.deepcopy(eseries_fakes.HOST)
        with mock.patch('random.sample') as mock_random:
            mock_random.return_value = [3]
            lun = host_mapper._get_free_lun(self.client, fake_host, False,
                                            [])
        self.assertEqual(3, lun)

    def test_get_free_lun_host_full(self):
        fake_host = copy.deepcopy(eseries_fakes.HOST)
        self.mock_object(host_mapper, '_is_host_full',
                         mock.Mock(return_value=True))
        self.assertRaises(
            exception.NetAppDriverException,
            host_mapper._get_free_lun,
            self.client, fake_host, False, FAKE_USED_UP_MAPPINGS)

    def test_get_free_lun_no_unused_luns(self):
        fake_host = copy.deepcopy(eseries_fakes.HOST)
        lun = host_mapper._get_free_lun(self.client, fake_host, False,
                                        FAKE_USED_UP_MAPPINGS)
        self.assertEqual(255, lun)

    def test_get_free_lun_no_unused_luns_host_not_full(self):
        fake_host = copy.deepcopy(eseries_fakes.HOST)
        self.mock_object(host_mapper, '_is_host_full',
                         mock.Mock(return_value=False))
        lun = host_mapper._get_free_lun(self.client, fake_host, False,
                                        FAKE_USED_UP_MAPPINGS)
        self.assertEqual(255, lun)

    def test_get_free_lun_no_lun_available(self):
        fake_host = copy.deepcopy(eseries_fakes.HOST_3)
        self.mock_object(self.client, 'get_volume_mappings_for_host',
                         mock.Mock(return_value=FAKE_USED_UP_MAPPINGS))

        self.assertRaises(exception.NetAppDriverException,
                          host_mapper._get_free_lun,
                          self.client, fake_host, False,
                          FAKE_USED_UP_MAPPINGS)

    def test_get_free_lun_multiattach_enabled_no_unused_ids(self):
        fake_host = copy.deepcopy(eseries_fakes.HOST_3)
        self.mock_object(self.client, 'get_volume_mappings',
                         mock.Mock(return_value=FAKE_USED_UP_MAPPINGS))

        self.assertRaises(exception.NetAppDriverException,
                          host_mapper._get_free_lun,
                          self.client, fake_host, True,
                          FAKE_USED_UP_MAPPINGS)

    def test_get_lun_by_mapping(self):
        used_luns = host_mapper._get_used_lun_ids_for_mappings(FAKE_MAPPINGS)
        self.assertEqual(set([0, 1]), used_luns)

    def test_get_lun_by_mapping_no_mapping(self):
        used_luns = host_mapper._get_used_lun_ids_for_mappings([])
        self.assertEqual(set([0]), used_luns)

    def test_lun_id_available_on_host(self):
        fake_host = copy.deepcopy(eseries_fakes.HOST)
        self.assertTrue(host_mapper._is_lun_id_available_on_host(
            self.client, fake_host, FAKE_UNUSED_LUN_ID))

    def test_no_lun_id_available_on_host(self):
        fake_host = copy.deepcopy(eseries_fakes.HOST_3)
        self.mock_object(self.client, 'get_volume_mappings_for_host',
                         mock.Mock(return_value=FAKE_USED_UP_MAPPINGS))

        self.assertFalse(host_mapper._is_lun_id_available_on_host(
            self.client, fake_host, FAKE_SINGLE_USED_LUN_ID))
