# Copyright (c) 2014 Alex Meade.  All rights reserved.
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

import uuid

import ddt
from lxml import etree
import mock
import six
import time

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.netapp.dataontap.client import (
    fakes as fake_client)
import cinder.tests.unit.volume.drivers.netapp.dataontap.fakes as fake
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_base


CONNECTION_INFO = {'hostname': 'hostname',
                   'transport_type': 'https',
                   'port': 443,
                   'username': 'admin',
                   'password': 'passw0rd',
                   'api_trace_pattern': 'fake_regex'}


@ddt.ddt
class NetAppBaseClientTestCase(test.TestCase):

    def setUp(self):
        super(NetAppBaseClientTestCase, self).setUp()

        self.mock_object(client_base, 'LOG')
        self.mock_object(client_base.Client, '_init_ssh_client')
        self.client = client_base.Client(**CONNECTION_INFO)
        self.client.connection = mock.MagicMock()
        self.client.connection.get_api_version.return_value = (1, 100)
        self.client.ssh_client = mock.MagicMock()
        self.connection = self.client.connection
        self.fake_volume = six.text_type(uuid.uuid4())
        self.fake_lun = six.text_type(uuid.uuid4())
        self.fake_size = '1024'
        self.fake_metadata = {'OsType': 'linux', 'SpaceReserved': 'true'}
        self.mock_send_request = self.mock_object(
            self.client.connection, 'send_request')

    def test_get_ontapi_version(self):
        version_response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <major-version>1</major-version>
                            <minor-version>19</minor-version>
                          </results>"""))
        self.connection.invoke_successfully.return_value = version_response

        major, minor = self.client.get_ontapi_version(cached=False)

        self.assertEqual('1', major)
        self.assertEqual('19', minor)

    def test_get_ontapi_version_cached(self):

        self.connection.get_api_version.return_value = (1, 20)

        major, minor = self.client.get_ontapi_version()

        self.assertEqual(1, self.connection.get_api_version.call_count)
        self.assertEqual(1, major)
        self.assertEqual(20, minor)

    def test_check_is_naelement(self):

        element = netapp_api.NaElement('name')

        self.assertIsNone(self.client.check_is_naelement(element))
        self.assertRaises(ValueError, self.client.check_is_naelement, None)

    @ddt.data({'ontap_version': '9.4', 'space_reservation': 'true'},
              {'ontap_version': '9.4', 'space_reservation': 'false'},
              {'ontap_version': '9.6', 'space_reservation': 'true'},
              {'ontap_version': '9.6', 'space_reservation': 'false'})
    @ddt.unpack
    def test_create_lun(self, ontap_version, space_reservation):
        expected_path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        self.fake_metadata['SpaceReserved'] = space_reservation
        expected_space_reservation = space_reservation
        self.mock_object(self.client, 'get_ontap_version',
                         return_value=ontap_version)
        mock_resize_lun = self.mock_object(
            client_base.Client, 'do_direct_resize')
        mock_set_space_reservation = self.mock_object(
            client_base.Client, 'set_lun_space_reservation')
        initial_size = self.fake_size

        if ontap_version < '9.5':
            initial_size = fake.MAX_SIZE_FOR_A_LUN
            expected_space_reservation = 'false'

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            self.client.create_lun(self.fake_volume,
                                   self.fake_lun,
                                   self.fake_size,
                                   self.fake_metadata)

            mock_create_node.assert_called_with(
                'lun-create-by-size',
                **{'path': expected_path,
                   'size': initial_size,
                   'ostype': self.fake_metadata['OsType'],
                   'space-reservation-enabled':
                       expected_space_reservation})
            self.connection.invoke_successfully.assert_called_with(
                mock.ANY, True)

        if ontap_version < '9.5':
            mock_resize_lun.assert_called_once_with(
                expected_path, self.fake_size)

        if ontap_version < '9.5' and space_reservation == 'true':
            mock_set_space_reservation.assert_called_once_with(
                expected_path, True)
        else:
            mock_set_space_reservation.assert_not_called()

    @ddt.data({'ontap_version': '9.4', 'space_reservation': 'true'},
              {'ontap_version': '9.4', 'space_reservation': 'false'},
              {'ontap_version': '9.6', 'space_reservation': 'true'},
              {'ontap_version': '9.6', 'space_reservation': 'false'})
    @ddt.unpack
    def test_create_lun_exact_size(self, ontap_version, space_reservation):
        expected_path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        self.connection.get_api_version.return_value = (1, 110)
        self.fake_metadata['SpaceReserved'] = space_reservation
        expected_space_reservation = self.fake_metadata['SpaceReserved']
        self.mock_object(self.client, 'get_ontap_version',
                         return_value=ontap_version)
        mock_resize_lun = self.mock_object(
            client_base.Client, 'do_direct_resize')
        mock_set_space_reservation = self.mock_object(
            client_base.Client, 'set_lun_space_reservation')
        initial_size = self.fake_size

        if ontap_version < '9.5':
            initial_size = fake.MAX_SIZE_FOR_A_LUN
            expected_space_reservation = 'false'

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            self.client.create_lun(self.fake_volume,
                                   self.fake_lun,
                                   self.fake_size,
                                   self.fake_metadata)

            mock_create_node.assert_called_with(
                'lun-create-by-size',
                **{'path': expected_path,
                   'size': initial_size,
                   'ostype': self.fake_metadata['OsType'],
                   'use-exact-size': 'true',
                   'space-reservation-enabled':
                       expected_space_reservation})
            self.connection.invoke_successfully.assert_called_with(
                mock.ANY, True)

        if ontap_version < '9.5':
            mock_resize_lun.assert_called_once_with(
                expected_path, self.fake_size)

        if ontap_version < '9.5' and space_reservation == 'true':
            mock_set_space_reservation.assert_called_once_with(
                expected_path, True)
        else:
            mock_set_space_reservation.assert_not_called()

    @ddt.data({'ontap_version': '9.4', 'space_reservation': 'true'},
              {'ontap_version': '9.4', 'space_reservation': 'false'},
              {'ontap_version': '9.6', 'space_reservation': 'true'},
              {'ontap_version': '9.6', 'space_reservation': 'false'})
    @ddt.unpack
    def test_create_lun_with_qos_policy_group_name(
            self, ontap_version, space_reservation):
        expected_path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        expected_qos_group_name = 'qos_1'
        mock_request = mock.Mock()

        self.fake_metadata['SpaceReserved'] = space_reservation
        expected_space_reservation = self.fake_metadata['SpaceReserved']
        self.mock_object(self.client, 'get_ontap_version',
                         return_value=ontap_version)
        mock_resize_lun = self.mock_object(
            client_base.Client, 'do_direct_resize')
        mock_set_space_reservation = self.mock_object(
            client_base.Client, 'set_lun_space_reservation')
        initial_size = self.fake_size

        if ontap_version < '9.5':
            initial_size = fake.MAX_SIZE_FOR_A_LUN
            expected_space_reservation = 'false'

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               return_value=mock_request
                               ) as mock_create_node:
            self.client.create_lun(
                self.fake_volume,
                self.fake_lun,
                self.fake_size,
                self.fake_metadata,
                qos_policy_group_name=expected_qos_group_name)

            mock_create_node.assert_called_with(
                'lun-create-by-size',
                **{'path': expected_path, 'size': initial_size,
                    'ostype': self.fake_metadata['OsType'],
                    'space-reservation-enabled':
                        expected_space_reservation})
            mock_request.add_new_child.assert_called_with(
                'qos-policy-group', expected_qos_group_name)
            self.connection.invoke_successfully.assert_called_with(
                mock.ANY, True)

        if ontap_version < '9.5':
            mock_resize_lun.assert_called_once_with(
                expected_path, self.fake_size)

        if ontap_version < '9.5' and space_reservation == 'true':
            mock_set_space_reservation.assert_called_once_with(
                expected_path, True)
        else:
            mock_set_space_reservation.assert_not_called()

    def test_get_ontap_version(self):
        version_response = netapp_api.NaElement(
            fake.SYSTEM_GET_VERSION_RESPONSE)
        self.connection.invoke_successfully.return_value = version_response

        result = self.client.get_ontap_version(cached=False)

        self.assertEqual(('9.6'), result)

    def test_get_ontap_version_cached(self):
        self.connection.get_ontap_version.return_value = '9.6'

        result = self.client.get_ontap_version()

        self.connection.get_ontap_version.assert_called_once_with()
        self.assertEqual(('9.6'), result)

    def test_set_lun_space_reservation(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_set_space_reservation:
            self.client.set_lun_space_reservation(path, True)

            mock_set_space_reservation.assert_called_once_with(
                'lun-set-space-reservation-info',
                **{'path': path,
                   'enable': 'True'})
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)

    @ddt.data('9.4', '9.6')
    def test_create_lun_raises_on_failure(self, ontap_version):
        self.connection.invoke_successfully = mock.Mock(
            side_effect=netapp_api.NaApiError)
        self.mock_object(self.client, 'get_ontap_version',
                         return_value=ontap_version)

        self.assertRaises(netapp_api.NaApiError,
                          self.client.create_lun,
                          self.fake_volume,
                          self.fake_lun,
                          self.fake_size,
                          self.fake_metadata)

    def test_destroy_lun(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            self.client.destroy_lun(path)

            mock_create_node.assert_called_once_with(
                'lun-destroy',
                **{'path': path})
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)

    def test_destroy_lun_force(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        mock_request = mock.Mock()

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               return_value=mock_request
                               ) as mock_create_node:
            self.client.destroy_lun(path)

            mock_create_node.assert_called_once_with('lun-destroy',
                                                     **{'path': path})
            mock_request.add_new_child.assert_called_once_with('force', 'true')
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)

    def test_map_lun(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        igroup = 'igroup'
        expected_lun_id = 'my_lun'
        mock_response = mock.Mock()
        self.connection.invoke_successfully.return_value = mock_response
        mock_response.get_child_content.return_value = expected_lun_id

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            actual_lun_id = self.client.map_lun(path, igroup)

            mock_create_node.assert_called_once_with(
                'lun-map',
                **{'path': path, 'initiator-group': igroup})
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)
            self.assertEqual(expected_lun_id, actual_lun_id)

    def test_map_lun_with_lun_id(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        igroup = 'igroup'
        expected_lun_id = 'my_lun'
        mock_response = mock.Mock()
        self.connection.invoke_successfully.return_value = mock_response
        mock_response.get_child_content.return_value = expected_lun_id

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            actual_lun_id = self.client.map_lun(path, igroup,
                                                lun_id=expected_lun_id)

            mock_create_node.assert_called_once_with(
                'lun-map',
                **{'path': path, 'initiator-group': igroup})
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)
            self.assertEqual(expected_lun_id, actual_lun_id)

    def test_map_lun_with_api_error(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        igroup = 'igroup'
        self.connection.invoke_successfully.side_effect =\
            netapp_api.NaApiError()

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            self.assertRaises(netapp_api.NaApiError, self.client.map_lun,
                              path, igroup)

            mock_create_node.assert_called_once_with(
                'lun-map',
                **{'path': path, 'initiator-group': igroup})
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)

    def test_unmap_lun(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        igroup = 'igroup'
        mock_response = mock.Mock()
        self.connection.invoke_successfully.return_value = mock_response

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            self.client.unmap_lun(path, igroup)

            mock_create_node.assert_called_once_with(
                'lun-unmap',
                **{'path': path, 'initiator-group': igroup})
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)

    def test_unmap_lun_with_api_error(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        igroup = 'igroup'
        self.connection.invoke_successfully.side_effect =\
            netapp_api.NaApiError()

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            self.assertRaises(netapp_api.NaApiError, self.client.unmap_lun,
                              path, igroup)

            mock_create_node.assert_called_once_with(
                'lun-unmap',
                **{'path': path, 'initiator-group': igroup})

    def test_unmap_lun_already_unmapped(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        igroup = 'igroup'
        EINVALIDINPUTERROR = '13115'
        self.connection.invoke_successfully.side_effect =\
            netapp_api.NaApiError(code=EINVALIDINPUTERROR)

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            self.client.unmap_lun(path, igroup)

            mock_create_node.assert_called_once_with(
                'lun-unmap',
                **{'path': path, 'initiator-group': igroup})
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)

    def test_unmap_lun_lun_not_mapped_in_group(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        igroup = 'igroup'
        EVDISK_ERROR_NO_SUCH_LUNMAP = '9016'
        self.connection.invoke_successfully.side_effect =\
            netapp_api.NaApiError(code=EVDISK_ERROR_NO_SUCH_LUNMAP)

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            self.client.unmap_lun(path, igroup)

            mock_create_node.assert_called_once_with(
                'lun-unmap',
                **{'path': path, 'initiator-group': igroup})
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)

    def test_create_igroup(self):
        igroup = 'igroup'

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            self.client.create_igroup(igroup)

            mock_create_node.assert_called_once_with(
                'igroup-create',
                **{'initiator-group-name': igroup,
                   'initiator-group-type': 'iscsi',
                   'os-type': 'default'})
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)

    def test_add_igroup_initiator(self):
        igroup = 'igroup'
        initiator = 'initiator'

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               ) as mock_create_node:
            self.client.add_igroup_initiator(igroup, initiator)

            mock_create_node.assert_called_once_with(
                'igroup-add',
                **{'initiator-group-name': igroup,
                   'initiator': initiator})
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)

    def test_do_direct_resize(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        new_size = 1024
        mock_request = mock.Mock()

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               return_value=mock_request
                               ) as mock_create_node:
            self.client.do_direct_resize(path, new_size)

            mock_create_node.assert_called_once_with(
                'lun-resize',
                **{'path': path,
                   'size': new_size})
            mock_request.add_new_child.assert_called_once_with(
                'force', 'true')
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)

    def test_do_direct_resize_not_forced(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        new_size = 1024
        mock_request = mock.Mock()

        with mock.patch.object(netapp_api.NaElement,
                               'create_node_with_children',
                               return_value=mock_request
                               ) as mock_create_node:
            self.client.do_direct_resize(path, new_size, force=False)

            mock_create_node.assert_called_once_with(
                'lun-resize',
                **{'path': path,
                   'size': new_size})
            self.assertFalse(mock_request.add_new_child.called)
            self.connection.invoke_successfully.assert_called_once_with(
                mock.ANY, True)

    def test_get_lun_geometry(self):
        expected_keys = set(['size', 'bytes_per_sector', 'sectors_per_track',
                             'tracks_per_cylinder', 'cylinders', 'max_resize'])
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        mock_response = mock.Mock()
        self.connection.invoke_successfully.return_value = mock_response

        geometry = self.client.get_lun_geometry(path)

        self.assertEqual(expected_keys, set(geometry.keys()))

    def test_get_lun_geometry_with_api_error(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        self.connection.invoke_successfully.side_effect =\
            netapp_api.NaApiError()
        geometry = self.client.get_lun_geometry(path)

        self.assertEqual({}, geometry)

    def test_get_volume_options(self):
        fake_response = netapp_api.NaElement('volume')
        fake_response.add_node_with_children('options', test='blah')
        self.connection.invoke_successfully.return_value = fake_response

        options = self.client.get_volume_options('volume')

        self.assertEqual(1, len(options))

    def test_get_volume_options_with_no_options(self):
        fake_response = netapp_api.NaElement('options')
        self.connection.invoke_successfully.return_value = fake_response

        options = self.client.get_volume_options('volume')

        self.assertEqual([], options)

    def test_move_lun(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        new_path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        fake_response = netapp_api.NaElement('options')
        self.connection.invoke_successfully.return_value = fake_response

        self.client.move_lun(path, new_path)

        self.connection.invoke_successfully.assert_called_once_with(
            mock.ANY, True)

    def test_get_igroup_by_initiators(self):
        self.assertRaises(NotImplementedError,
                          self.client.get_igroup_by_initiators,
                          fake.FC_FORMATTED_INITIATORS)

    def test_get_fc_target_wwpns(self):
        self.assertRaises(NotImplementedError,
                          self.client.get_fc_target_wwpns)

    def test_has_luns_mapped_to_initiator(self):
        initiator = fake.FC_FORMATTED_INITIATORS[0]
        version_response = netapp_api.NaElement(
            etree.XML("""
  <results status="passed">
    <lun-maps>
      <lun-map-info>
        <path>/vol/cinder1/volume-9be956b3-9854-4a5c-a7f5-13a16da52c9c</path>
        <initiator-group>openstack-4b57a80b-ebca-4d27-bd63-48ac5408d08b
        </initiator-group>
        <lun-id>0</lun-id>
      </lun-map-info>
      <lun-map-info>
        <path>/vol/cinder1/volume-ac90433c-a560-41b3-9357-7f3f80071eb5</path>
        <initiator-group>openstack-4b57a80b-ebca-4d27-bd63-48ac5408d08b
        </initiator-group>
        <lun-id>1</lun-id>
      </lun-map-info>
    </lun-maps>
  </results>"""))

        self.connection.invoke_successfully.return_value = version_response

        self.assertTrue(self.client._has_luns_mapped_to_initiator(initiator))

    def test_has_luns_mapped_to_initiator_not_mapped(self):
        initiator = fake.FC_FORMATTED_INITIATORS[0]
        version_response = netapp_api.NaElement(
            etree.XML("""
  <results status="passed">
    <lun-maps />
  </results>"""))
        self.connection.invoke_successfully.return_value = version_response
        self.assertFalse(self.client._has_luns_mapped_to_initiator(initiator))

    @mock.patch.object(client_base.Client, '_has_luns_mapped_to_initiator')
    def test_has_luns_mapped_to_initiators(self,
                                           mock_has_luns_mapped_to_initiator):
        initiators = fake.FC_FORMATTED_INITIATORS
        mock_has_luns_mapped_to_initiator.return_value = True
        self.assertTrue(self.client.has_luns_mapped_to_initiators(initiators))

    @mock.patch.object(client_base.Client, '_has_luns_mapped_to_initiator')
    def test_has_luns_mapped_to_initiators_not_mapped(
            self, mock_has_luns_mapped_to_initiator):
        initiators = fake.FC_FORMATTED_INITIATORS
        mock_has_luns_mapped_to_initiator.return_value = False
        self.assertFalse(self.client.has_luns_mapped_to_initiators(initiators))

    def test_get_performance_counter_info(self):

        self.mock_send_request.return_value = netapp_api.NaElement(
            fake_client.PERF_OBJECT_COUNTER_LIST_INFO_WAFL_RESPONSE)

        result = self.client.get_performance_counter_info('wafl',
                                                          'cp_phase_times')

        expected = {
            'name': 'cp_phase_times',
            'base-counter': 'total_cp_msecs',
            'labels': fake_client.PERF_OBJECT_COUNTER_TOTAL_CP_MSECS_LABELS,
        }
        self.assertEqual(expected, result)

        perf_object_counter_list_info_args = {'objectname': 'wafl'}
        self.mock_send_request.assert_called_once_with(
            'perf-object-counter-list-info',
            perf_object_counter_list_info_args, enable_tunneling=False)

    def test_get_performance_counter_info_not_found(self):

        self.mock_send_request.return_value = netapp_api.NaElement(
            fake_client.PERF_OBJECT_COUNTER_LIST_INFO_WAFL_RESPONSE)

        self.assertRaises(exception.NotFound,
                          self.client.get_performance_counter_info,
                          'wafl',
                          'invalid')

    def test_delete_snapshot(self):
        api_args = {
            'volume': fake.SNAPSHOT['volume_id'],
            'snapshot': fake.SNAPSHOT['name'],
        }
        self.mock_object(self.client.connection, 'send_request')

        self.client.delete_snapshot(api_args['volume'],
                                    api_args['snapshot'])

        asserted_api_args = {
            'volume': api_args['volume'],
            'snapshot': api_args['snapshot'],
        }
        self.client.connection.send_request.assert_called_once_with(
            'snapshot-delete', asserted_api_args)

    def test_create_cg_snapshot(self):
        self.mock_object(self.client, '_start_cg_snapshot',
                         return_value=fake.CONSISTENCY_GROUP_ID)
        self.mock_object(self.client, '_commit_cg_snapshot')

        self.client.create_cg_snapshot([fake.CG_VOLUME_NAME],
                                       fake.CG_SNAPSHOT_NAME)

        self.client._commit_cg_snapshot.assert_called_once_with(
            fake.CONSISTENCY_GROUP_ID)

    def test_create_cg_snapshot_no_id(self):
        self.mock_object(self.client, '_start_cg_snapshot', return_value=None)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.client.create_cg_snapshot,
                          [fake.CG_VOLUME_NAME],
                          fake.CG_SNAPSHOT_NAME)

    def test_start_cg_snapshot(self):
        snapshot_init = {
            'snapshot': fake.CG_SNAPSHOT_NAME,
            'timeout': 'relaxed',
            'volumes': [{'volume-name': fake.CG_VOLUME_NAME}],
        }
        self.mock_object(self.client.connection, 'send_request')

        self.client._start_cg_snapshot([fake.CG_VOLUME_NAME],
                                       snapshot_init['snapshot'])

        self.client.connection.send_request.assert_called_once_with(
            'cg-start', snapshot_init)

    def test_commit_cg_snapshot(self):
        snapshot_commit = {'cg-id': fake.CG_VOLUME_ID}
        self.mock_object(self.client.connection, 'send_request')

        self.client._commit_cg_snapshot(snapshot_commit['cg-id'])

        self.client.connection.send_request.assert_called_once_with(
            'cg-commit', {'cg-id': snapshot_commit['cg-id']})

    def test_wait_for_busy_snapshot_raise_exception(self):
        BUSY_SNAPSHOT = dict(fake.SNAPSHOT)
        BUSY_SNAPSHOT['busy'] = True

        # Need to mock sleep as it is called by @utils.retry
        self.mock_object(time, 'sleep')
        mock_get_snapshot = self.mock_object(self.client, 'get_snapshot',
                                             return_value=BUSY_SNAPSHOT)

        self.assertRaises(exception.SnapshotIsBusy,
                          self.client.wait_for_busy_snapshot,
                          fake.FLEXVOL, fake.SNAPSHOT_NAME)

        calls = [
            mock.call(fake.FLEXVOL, fake.SNAPSHOT_NAME),
            mock.call(fake.FLEXVOL, fake.SNAPSHOT_NAME),
            mock.call(fake.FLEXVOL, fake.SNAPSHOT_NAME),
        ]
        mock_get_snapshot.assert_has_calls(calls)

    def test_rename_snapshot(self):
        self.mock_object(self.client.connection, 'send_request')

        self.client.rename_snapshot(
            fake.SNAPSHOT['volume_id'], fake.SNAPSHOT_NAME,
            client_base.DELETED_PREFIX + fake.SNAPSHOT_NAME)

        api_args = {
            'volume': fake.SNAPSHOT['volume_id'],
            'current-name': fake.SNAPSHOT_NAME,
            'new-name':
                client_base.DELETED_PREFIX + fake.SNAPSHOT_NAME,
        }

        self.client.connection.send_request.assert_called_once_with(
            'snapshot-rename', api_args)
