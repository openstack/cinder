# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2015 Dustin Schoenbrun. All rights reserved.
# Copyright (c) 2016 Mike Rooney. All rights reserved.
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

import uuid

import ddt
from lxml import etree
import mock
import paramiko
import six

from cinder import exception
from cinder import ssh_utils
from cinder import test
from cinder.tests.unit.volume.drivers.netapp.dataontap.client import (
    fakes as fake_client)
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as fake
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_7mode
from cinder.volume.drivers.netapp.dataontap.client import client_base
from cinder.volume.drivers.netapp import utils as netapp_utils

CONNECTION_INFO = {'hostname': 'hostname',
                   'transport_type': 'https',
                   'port': 443,
                   'username': 'admin',
                   'password': 'passw0rd'}


@ddt.ddt
class NetApp7modeClientTestCase(test.TestCase):

    def setUp(self):
        super(NetApp7modeClientTestCase, self).setUp()

        self.fake_volume = six.text_type(uuid.uuid4())

        self.mock_object(client_7mode.Client, '_init_ssh_client')
        with mock.patch.object(client_7mode.Client,
                               'get_ontapi_version',
                               return_value=(1, 20)):
            self.client = client_7mode.Client([self.fake_volume],
                                              **CONNECTION_INFO)

        self.client.ssh_client = mock.MagicMock()
        self.client.connection = mock.MagicMock()
        self.connection = self.client.connection
        self.fake_lun = six.text_type(uuid.uuid4())

    def test_get_iscsi_target_details_no_targets(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <iscsi-portal-list-entries>
                           </iscsi-portal-list-entries>
                         </results>"""))
        self.connection.invoke_successfully.return_value = response

        target_list = self.client.get_iscsi_target_details()

        self.assertEqual([], target_list)

    def test_get_iscsi_target_details(self):
        expected_target = {
            "address": "127.0.0.1",
            "port": "1337",
            "tpgroup-tag": "7777",
        }
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <iscsi-portal-list-entries>
                              <iscsi-portal-list-entry-info>
                                <ip-address>%(address)s</ip-address>
                                <ip-port>%(port)s</ip-port>
                                <tpgroup-tag>%(tpgroup-tag)s</tpgroup-tag>
                              </iscsi-portal-list-entry-info>
                           </iscsi-portal-list-entries>
                          </results>""" % expected_target))
        self.connection.invoke_successfully.return_value = response

        target_list = self.client.get_iscsi_target_details()

        self.assertEqual([expected_target], target_list)

    def test_get_iscsi_service_details_with_no_iscsi_service(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                         </results>"""))
        self.connection.invoke_successfully.return_value = response

        iqn = self.client.get_iscsi_service_details()

        self.assertIsNone(iqn)

    def test_get_iscsi_service_details(self):
        expected_iqn = 'iqn.1998-01.org.openstack.iscsi:name1'
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <node-name>%s</node-name>
                         </results>""" % expected_iqn))
        self.connection.invoke_successfully.return_value = response

        iqn = self.client.get_iscsi_service_details()

        self.assertEqual(expected_iqn, iqn)

    def test_get_lun_list(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <luns>
                            <lun-info></lun-info>
                            <lun-info></lun-info>
                           </luns>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        luns = self.client.get_lun_list()

        self.assertEqual(2, len(luns))

    def test_get_igroup_by_initiators_none_found(self):
        initiators = fake.FC_FORMATTED_INITIATORS[0]

        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <initiator-groups>
                           </initiator-groups>
                         </results>"""))
        self.connection.invoke_successfully.return_value = response

        igroup = self.client.get_igroup_by_initiators(initiators)

        self.assertEqual([], igroup)

    def test_get_igroup_by_initiators(self):
        initiators = [fake.FC_FORMATTED_INITIATORS[0]]
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
    <initiator-groups>
      <initiator-group-info>
        <initiator-group-name>%(initiator-group-name)s</initiator-group-name>
        <initiator-group-type>%(initiator-group-type)s</initiator-group-type>
        <initiator-group-uuid>1477ee47-0e1f-4b35-a82c-dcca0b76fc44
        </initiator-group-uuid>
        <initiator-group-os-type>linux</initiator-group-os-type>
        <initiator-group-throttle-reserve>0</initiator-group-throttle-reserve>
        <initiator-group-throttle-borrow>false
        </initiator-group-throttle-borrow>
        <initiator-group-vsa-enabled>false</initiator-group-vsa-enabled>
        <initiator-group-alua-enabled>true</initiator-group-alua-enabled>
        <initiator-group-report-scsi-name-enabled>true
        </initiator-group-report-scsi-name-enabled>
        <initiator-group-use-partner>true</initiator-group-use-partner>
        <initiators>
          <initiator-info>
            <initiator-name>21:00:00:24:ff:40:6c:c3</initiator-name>
          </initiator-info>
        </initiators>
      </initiator-group-info>
    </initiator-groups>
  </results>""" % fake.IGROUP1))
        self.connection.invoke_successfully.return_value = response

        igroups = self.client.get_igroup_by_initiators(initiators)

        # make these lists of dicts comparable using hashable dictionaries
        igroups = set(
            [netapp_utils.hashabledict(igroup) for igroup in igroups])
        expected = set([netapp_utils.hashabledict(fake.IGROUP1)])

        self.assertSetEqual(igroups, expected)

    def test_get_igroup_by_initiators_multiple(self):
        initiators = fake.FC_FORMATTED_INITIATORS
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
    <initiator-groups>
      <initiator-group-info>
        <initiator-group-name>%(initiator-group-name)s</initiator-group-name>
        <initiator-group-type>%(initiator-group-type)s</initiator-group-type>
        <initiator-group-uuid>1477ee47-0e1f-4b35-a82c-dcca0b76fc44
        </initiator-group-uuid>
        <initiator-group-os-type>linux</initiator-group-os-type>
        <initiators>
          <initiator-info>
            <initiator-name>21:00:00:24:ff:40:6c:c3</initiator-name>
          </initiator-info>
          <initiator-info>
            <initiator-name>21:00:00:24:ff:40:6c:c2</initiator-name>
          </initiator-info>
        </initiators>
      </initiator-group-info>
      <initiator-group-info>
        <initiator-group-name>openstack-igroup2</initiator-group-name>
        <initiator-group-type>fcp</initiator-group-type>
        <initiator-group-uuid>1477ee47-0e1f-4b35-a82c-dcca0b76fc44
        </initiator-group-uuid>
        <initiator-group-os-type>linux</initiator-group-os-type>
        <initiators>
          <initiator-info>
            <initiator-name>21:00:00:24:ff:40:6c:c2</initiator-name>
          </initiator-info>
        </initiators>
      </initiator-group-info>    </initiator-groups>
  </results>""" % fake.IGROUP1))
        self.connection.invoke_successfully.return_value = response

        igroups = self.client.get_igroup_by_initiators(initiators)

        # make these lists of dicts comparable using hashable dictionaries
        igroups = set(
            [netapp_utils.hashabledict(igroup) for igroup in igroups])
        expected = set([netapp_utils.hashabledict(fake.IGROUP1)])

        self.assertSetEqual(igroups, expected)

    def test_clone_lun(self):
        fake_clone_start = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <clone-id>
                             <clone-id-info>
                               <clone-op-id>1337</clone-op-id>
                               <volume-uuid>volume-uuid</volume-uuid>
                             </clone-id-info>
                           </clone-id>
                         </results>"""))
        fake_clone_status = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <status>
                             <ops-info>
                               <clone-state>completed</clone-state>
                             </ops-info>
                           </status>
                         </results>"""))

        self.connection.invoke_successfully.side_effect = [fake_clone_start,
                                                           fake_clone_status]

        self.client.clone_lun('path', 'new_path', 'fakeLUN', 'newFakeLUN')
        self.assertEqual(2, self.connection.invoke_successfully.call_count)

    def test_clone_lun_api_error(self):
        fake_clone_start = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <clone-id>
                             <clone-id-info>
                               <clone-op-id>1337</clone-op-id>
                               <volume-uuid>volume-uuid</volume-uuid>
                             </clone-id-info>
                           </clone-id>
                         </results>"""))
        fake_clone_status = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <status>
                             <ops-info>
                               <clone-state>error</clone-state>
                             </ops-info>
                           </status>
                         </results>"""))

        self.connection.invoke_successfully.side_effect = [fake_clone_start,
                                                           fake_clone_status]

        self.assertRaises(netapp_api.NaApiError, self.client.clone_lun,
                          'path', 'new_path', 'fakeLUN', 'newFakeLUN')

    def test_clone_lun_multiple_zapi_calls(self):
        # Max block-ranges per call = 32, max blocks per range = 2^24
        # Force 2 calls
        bc = 2 ** 24 * 32 * 2
        fake_clone_start = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <clone-id>
                             <clone-id-info>
                               <clone-op-id>1337</clone-op-id>
                               <volume-uuid>volume-uuid</volume-uuid>
                             </clone-id-info>
                           </clone-id>
                         </results>"""))
        fake_clone_status = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <status>
                             <ops-info>
                               <clone-state>completed</clone-state>
                             </ops-info>
                           </status>
                         </results>"""))

        self.connection.invoke_successfully.side_effect = [fake_clone_start,
                                                           fake_clone_status,
                                                           fake_clone_start,
                                                           fake_clone_status]

        self.client.clone_lun('path', 'new_path', 'fakeLUN', 'newFakeLUN',
                              block_count=bc)

        self.assertEqual(4, self.connection.invoke_successfully.call_count)

    def test_clone_lun_wait_for_clone_to_finish(self):
        # Max block-ranges per call = 32, max blocks per range = 2^24
        # Force 2 calls
        bc = 2 ** 24 * 32 * 2
        fake_clone_start = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <clone-id>
                             <clone-id-info>
                               <clone-op-id>1337</clone-op-id>
                               <volume-uuid>volume-uuid</volume-uuid>
                             </clone-id-info>
                           </clone-id>
                         </results>"""))
        fake_clone_status = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <status>
                             <ops-info>
                               <clone-state>running</clone-state>
                             </ops-info>
                           </status>
                         </results>"""))
        fake_clone_status_completed = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <status>
                             <ops-info>
                               <clone-state>completed</clone-state>
                             </ops-info>
                           </status>
                         </results>"""))

        fake_responses = [fake_clone_start,
                          fake_clone_status,
                          fake_clone_status_completed,
                          fake_clone_start,
                          fake_clone_status_completed]
        self.connection.invoke_successfully.side_effect = fake_responses

        with mock.patch('time.sleep') as mock_sleep:
            self.client.clone_lun('path', 'new_path', 'fakeLUN',
                                  'newFakeLUN', block_count=bc)

            mock_sleep.assert_called_once_with(1)
            self.assertEqual(5, self.connection.invoke_successfully.call_count)

    def test_get_lun_by_args(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <luns>
                            <lun-info></lun-info>
                           </luns>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        luns = self.client.get_lun_by_args()

        self.assertEqual(1, len(luns))

    def test_get_lun_by_args_no_lun_found(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <luns>
                           </luns>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        luns = self.client.get_lun_by_args()

        self.assertEqual(0, len(luns))

    def test_get_lun_by_args_with_args_specified(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <luns>
                            <lun-info></lun-info>
                           </luns>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        lun = self.client.get_lun_by_args(path=path)

        __, _args, __ = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        lun_info_args = actual_request.get_children()

        # Assert request is made with correct arguments
        self.assertEqual('path', lun_info_args[0].get_name())
        self.assertEqual(path, lun_info_args[0].get_content())

        self.assertEqual(1, len(lun))

    def test_get_filer_volumes(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <volumes>
                            <volume-info></volume-info>
                           </volumes>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        volumes = self.client.get_filer_volumes()

        self.assertEqual(1, len(volumes))

    def test_get_filer_volumes_no_volumes(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <volumes>
                           </volumes>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        volumes = self.client.get_filer_volumes()

        self.assertEqual([], volumes)

    def test_get_lun_map(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        self.connection.invoke_successfully.return_value = mock.Mock()

        self.client.get_lun_map(path=path)

        __, _args, __ = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        lun_info_args = actual_request.get_children()

        # Assert request is made with correct arguments
        self.assertEqual('path', lun_info_args[0].get_name())
        self.assertEqual(path, lun_info_args[0].get_content())

    def test_set_space_reserve(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        self.connection.invoke_successfully.return_value = mock.Mock()

        self.client.set_space_reserve(path, 'true')

        __, _args, __ = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        lun_info_args = actual_request.get_children()

        # The children list is not generated in a stable order,
        # so figure out which entry is which.
        if lun_info_args[0].get_name() == 'path':
            path_arg = lun_info_args[0]
            enable_arg = lun_info_args[1]
        else:
            path_arg = lun_info_args[1]
            enable_arg = lun_info_args[0]

        # Assert request is made with correct arguments
        self.assertEqual('path', path_arg.get_name())
        self.assertEqual(path, path_arg.get_content())
        self.assertEqual('enable', enable_arg.get_name())
        self.assertEqual('true', enable_arg.get_content())

    def test_get_actual_path_for_export(self):
        fake_export_path = 'fake_export_path'
        expected_actual_pathname = 'fake_actual_pathname'
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <actual-pathname>%(path)s</actual-pathname>
                          </results>""" % {'path': expected_actual_pathname}))
        self.connection.invoke_successfully.return_value = response

        actual_pathname = self.client.get_actual_path_for_export(
            fake_export_path)

        __, __, _kwargs = self.connection.invoke_successfully.mock_calls[0]
        enable_tunneling = _kwargs['enable_tunneling']

        self.assertEqual(expected_actual_pathname, actual_pathname)
        self.assertTrue(enable_tunneling)

    def test_clone_file(self):
        expected_src_path = "fake_src_path"
        expected_dest_path = "fake_dest_path"
        fake_volume_id = '0309c748-0d94-41f0-af46-4fbbd76686cf'
        fake_clone_op_id = 'c22ad299-ecec-4ec0-8de4-352b887bfce2'
        fake_clone_id_response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <clone-id>
                             <clone-id-info>
                               <volume-uuid>%(volume)s</volume-uuid>
                               <clone-op-id>%(clone_id)s</clone-op-id>
                             </clone-id-info>
                           </clone-id>
                         </results>""" % {'volume': fake_volume_id,
                                          'clone_id': fake_clone_op_id}))
        fake_clone_list_response = netapp_api.NaElement(
            etree.XML("""<results>
                           <clone-list-status>
                             <clone-id-info>
                               <volume-uuid>%(volume)s</volume-uuid>
                               <clone-op-id>%(clone_id)s</clone-op-id>
                             </clone-id-info>
                               <clone-op-id>%(clone_id)s</clone-op-id>
                           </clone-list-status>
                           <status>
                             <ops-info>
                               <clone-state>completed</clone-state>
                             </ops-info>
                           </status>
                         </results>""" % {'volume': fake_volume_id,
                                          'clone_id': fake_clone_op_id}))
        self.connection.invoke_successfully.side_effect = [
            fake_clone_id_response, fake_clone_list_response]

        self.client.clone_file(expected_src_path,
                               expected_dest_path,
                               source_snapshot=fake.CG_SNAPSHOT_ID)

        __, _args, _kwargs = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        enable_tunneling = _kwargs['enable_tunneling']
        actual_src_path = actual_request \
            .get_child_by_name('source-path').get_content()
        actual_dest_path = actual_request.get_child_by_name(
            'destination-path').get_content()

        self.assertEqual(expected_src_path, actual_src_path)
        self.assertEqual(expected_dest_path, actual_dest_path)
        self.assertEqual(
            fake.CG_SNAPSHOT_ID,
            actual_request.get_child_by_name('snapshot-name').get_content())
        self.assertIsNone(actual_request.get_child_by_name(
            'destination-exists'))
        self.assertTrue(enable_tunneling)

    def test_clone_file_when_clone_fails(self):
        """Ensure clone is cleaned up on failure."""
        expected_src_path = "fake_src_path"
        expected_dest_path = "fake_dest_path"
        fake_volume_id = '0309c748-0d94-41f0-af46-4fbbd76686cf'
        fake_clone_op_id = 'c22ad299-ecec-4ec0-8de4-352b887bfce2'
        fake_clone_id_response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <clone-id>
                             <clone-id-info>
                               <volume-uuid>%(volume)s</volume-uuid>
                               <clone-op-id>%(clone_id)s</clone-op-id>
                             </clone-id-info>
                           </clone-id>
                         </results>""" % {'volume': fake_volume_id,
                                          'clone_id': fake_clone_op_id}))
        fake_clone_list_response = netapp_api.NaElement(
            etree.XML("""<results>
                           <clone-list-status>
                             <clone-id-info>
                               <volume-uuid>%(volume)s</volume-uuid>
                               <clone-op-id>%(clone_id)s</clone-op-id>
                             </clone-id-info>
                               <clone-op-id>%(clone_id)s</clone-op-id>
                           </clone-list-status>
                           <status>
                             <ops-info>
                               <clone-state>failed</clone-state>
                             </ops-info>
                           </status>
                         </results>""" % {'volume': fake_volume_id,
                                          'clone_id': fake_clone_op_id}))
        fake_clone_clear_response = mock.Mock()
        self.connection.invoke_successfully.side_effect = [
            fake_clone_id_response, fake_clone_list_response,
            fake_clone_clear_response]

        self.assertRaises(netapp_api.NaApiError,
                          self.client.clone_file,
                          expected_src_path,
                          expected_dest_path)

        __, _args, _kwargs = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        enable_tunneling = _kwargs['enable_tunneling']
        actual_src_path = actual_request \
            .get_child_by_name('source-path').get_content()
        actual_dest_path = actual_request.get_child_by_name(
            'destination-path').get_content()

        self.assertEqual(expected_src_path, actual_src_path)
        self.assertEqual(expected_dest_path, actual_dest_path)
        self.assertIsNone(actual_request.get_child_by_name(
            'destination-exists'))
        self.assertTrue(enable_tunneling)

        __, _args, _kwargs = self.connection.invoke_successfully.mock_calls[1]
        actual_request = _args[0]
        enable_tunneling = _kwargs['enable_tunneling']
        actual_clone_id = actual_request.get_child_by_name('clone-id')
        actual_clone_id_info = actual_clone_id.get_child_by_name(
            'clone-id-info')
        actual_clone_op_id = actual_clone_id_info.get_child_by_name(
            'clone-op-id').get_content()
        actual_volume_uuid = actual_clone_id_info.get_child_by_name(
            'volume-uuid').get_content()

        self.assertEqual(fake_clone_op_id, actual_clone_op_id)
        self.assertEqual(fake_volume_id, actual_volume_uuid)
        self.assertTrue(enable_tunneling)

        # Ensure that the clone-clear call is made upon error
        __, _args, _kwargs = self.connection.invoke_successfully.mock_calls[2]
        actual_request = _args[0]
        enable_tunneling = _kwargs['enable_tunneling']
        actual_clone_id = actual_request \
            .get_child_by_name('clone-id').get_content()

        self.assertEqual(fake_clone_op_id, actual_clone_id)
        self.assertTrue(enable_tunneling)

    def test_get_file_usage(self):
        expected_bytes = "2048"
        fake_path = 'fake_path'
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <unique-bytes>%(unique-bytes)s</unique-bytes>
                         </results>""" % {'unique-bytes': expected_bytes}))
        self.connection.invoke_successfully.return_value = response

        actual_bytes = self.client.get_file_usage(fake_path)

        self.assertEqual(expected_bytes, actual_bytes)

    def test_get_ifconfig(self):
        expected_response = mock.Mock()
        self.connection.invoke_successfully.return_value = expected_response

        actual_response = self.client.get_ifconfig()

        __, _args, __ = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        self.assertEqual('net-ifconfig-get', actual_request.get_name())
        self.assertEqual(expected_response, actual_response)

    def test_get_fc_target_wwpns(self):
        wwpn1 = '50:0a:09:81:90:fe:eb:a5'
        wwpn2 = '50:0a:09:82:90:fe:eb:a5'
        response = netapp_api.NaElement(
            etree.XML("""
  <results status="passed">
    <fcp-port-names>
      <fcp-port-name-info>
        <port-name>%(wwpn1)s</port-name>
        <is-used>true</is-used>
        <fcp-adapter>1a</fcp-adapter>
      </fcp-port-name-info>
      <fcp-port-name-info>
        <port-name>%(wwpn2)s</port-name>
        <is-used>true</is-used>
        <fcp-adapter>1b</fcp-adapter>
      </fcp-port-name-info>
    </fcp-port-names>
  </results>""" % {'wwpn1': wwpn1, 'wwpn2': wwpn2}))
        self.connection.invoke_successfully.return_value = response

        wwpns = self.client.get_fc_target_wwpns()

        self.assertSetEqual(set(wwpns), set([wwpn1, wwpn2]))

    def test_get_flexvol_capacity(self):
        expected_total_bytes = 1000
        expected_available_bytes = 750
        fake_flexvol_path = '/fake/vol'
        response = netapp_api.NaElement(
            etree.XML("""
            <results status="passed">
                <volumes>
                    <volume-info>
                        <size-total>%(total_bytes)s</size-total>
                        <size-available>%(available_bytes)s</size-available>
                    </volume-info>
                </volumes>
            </results>""" % {'total_bytes': expected_total_bytes,
                             'available_bytes': expected_available_bytes}))
        self.connection.invoke_successfully.return_value = response

        result = self.client.get_flexvol_capacity(fake_flexvol_path)

        expected = {
            'size-total': expected_total_bytes,
            'size-available': expected_available_bytes,
        }
        self.assertEqual(expected, result)

    def test_get_performance_instance_names(self):

        mock_send_request = self.mock_object(self.client, 'send_request')
        mock_send_request.return_value = netapp_api.NaElement(
            fake_client.PERF_OBJECT_INSTANCE_LIST_INFO_RESPONSE)

        result = self.client.get_performance_instance_names('processor')

        expected = ['processor0', 'processor1']
        self.assertEqual(expected, result)

        perf_object_instance_list_info_args = {'objectname': 'processor'}
        mock_send_request.assert_called_once_with(
            'perf-object-instance-list-info',
            perf_object_instance_list_info_args, enable_tunneling=False)

    def test_get_performance_counters(self):

        mock_send_request = self.mock_object(self.client, 'send_request')
        mock_send_request.return_value = netapp_api.NaElement(
            fake_client.PERF_OBJECT_GET_INSTANCES_SYSTEM_RESPONSE_7MODE)

        instance_names = ['system']
        counter_names = ['avg_processor_busy']
        result = self.client.get_performance_counters('system',
                                                      instance_names,
                                                      counter_names)

        expected = [
            {
                'avg_processor_busy': '13215732322',
                'instance-name': 'system',
                'timestamp': '1454146292',
            }
        ]
        self.assertEqual(expected, result)

        perf_object_get_instances_args = {
            'objectname': 'system',
            'instances': [
                {'instance': instance} for instance in instance_names
            ],
            'counters': [
                {'counter': counter} for counter in counter_names
            ],
        }
        mock_send_request.assert_called_once_with(
            'perf-object-get-instances', perf_object_get_instances_args,
            enable_tunneling=False)

    def test_get_system_name(self):

        mock_send_request = self.mock_object(self.client, 'send_request')
        mock_send_request.return_value = netapp_api.NaElement(
            fake_client.SYSTEM_GET_INFO_RESPONSE)

        result = self.client.get_system_name()

        self.assertEqual(fake_client.NODE_NAME, result)

    def test_check_iscsi_initiator_exists_when_no_initiator_exists(self):
        self.connection.invoke_successfully = mock.Mock(
            side_effect=netapp_api.NaApiError)
        initiator = fake_client.INITIATOR_IQN

        initiator_exists = self.client.check_iscsi_initiator_exists(initiator)

        self.assertFalse(initiator_exists)

    def test_check_iscsi_initiator_exists_when_initiator_exists(self):
        self.connection.invoke_successfully = mock.Mock()
        initiator = fake_client.INITIATOR_IQN

        initiator_exists = self.client.check_iscsi_initiator_exists(initiator)

        self.assertTrue(initiator_exists)

    def test_set_iscsi_chap_authentication(self):
        ssh = mock.Mock(paramiko.SSHClient)
        sshpool = mock.Mock(ssh_utils.SSHPool)
        self.client.ssh_client.ssh_pool = sshpool
        self.mock_object(self.client.ssh_client, 'execute_command')
        sshpool.item().__enter__ = mock.Mock(return_value=ssh)
        sshpool.item().__exit__ = mock.Mock(return_value=False)

        self.client.set_iscsi_chap_authentication(fake_client.INITIATOR_IQN,
                                                  fake_client.USER_NAME,
                                                  fake_client.PASSWORD)

        command = ('iscsi security add -i iqn.2015-06.com.netapp:fake_iqn '
                   '-s CHAP -p passw0rd -n fake_user')
        self.client.ssh_client.execute_command.assert_has_calls(
            [mock.call(ssh, command)]
        )

    def test_get_snapshot_if_snapshot_present_not_busy(self):
        expected_vol_name = fake.SNAPSHOT['volume_id']
        expected_snapshot_name = fake.SNAPSHOT['name']
        response = netapp_api.NaElement(
            fake_client.SNAPSHOT_INFO_FOR_PRESENT_NOT_BUSY_SNAPSHOT_7MODE)
        self.connection.invoke_successfully.return_value = response

        snapshot = self.client.get_snapshot(expected_vol_name,
                                            expected_snapshot_name)

        self.assertEqual(expected_vol_name, snapshot['volume'])
        self.assertEqual(expected_snapshot_name, snapshot['name'])
        self.assertEqual(set([]), snapshot['owners'])
        self.assertFalse(snapshot['busy'])

    def test_get_snapshot_if_snapshot_present_busy(self):
        expected_vol_name = fake.SNAPSHOT['volume_id']
        expected_snapshot_name = fake.SNAPSHOT['name']
        response = netapp_api.NaElement(
            fake_client.SNAPSHOT_INFO_FOR_PRESENT_BUSY_SNAPSHOT_7MODE)
        self.connection.invoke_successfully.return_value = response

        snapshot = self.client.get_snapshot(expected_vol_name,
                                            expected_snapshot_name)

        self.assertEqual(expected_vol_name, snapshot['volume'])
        self.assertEqual(expected_snapshot_name, snapshot['name'])
        self.assertEqual(set([]), snapshot['owners'])
        self.assertTrue(snapshot['busy'])

    def test_get_snapshot_if_snapshot_not_present(self):
        expected_vol_name = fake.SNAPSHOT['volume_id']
        expected_snapshot_name = fake.SNAPSHOT['name']
        response = netapp_api.NaElement(fake_client.SNAPSHOT_NOT_PRESENT_7MODE)
        self.connection.invoke_successfully.return_value = response

        self.assertRaises(exception.SnapshotNotFound, self.client.get_snapshot,
                          expected_vol_name, expected_snapshot_name)

    @ddt.data({
        'mock_return':
            fake_client.SNAPSHOT_INFO_MARKED_FOR_DELETE_SNAPSHOT_7MODE,
        'expected': [{
            'name': client_base.DELETED_PREFIX + fake.SNAPSHOT_NAME,
            'instance_id': 'abcd-ef01-2345-6789',
            'volume_name': fake.SNAPSHOT['volume_id'],
        }]
    }, {
        'mock_return': fake_client.NO_RECORDS_RESPONSE,
        'expected': [],
    }, {
        'mock_return':
            fake_client.SNAPSHOT_INFO_MARKED_FOR_DELETE_SNAPSHOT_7MODE_BUSY,
        'expected': [],
    })
    @ddt.unpack
    def test_get_snapshots_marked_for_deletion(self, mock_return, expected):
        api_response = netapp_api.NaElement(mock_return)
        volume_list = [fake.SNAPSHOT['volume_id']]
        self.mock_object(self.client,
                         'send_request',
                         return_value=api_response)

        result = self.client.get_snapshots_marked_for_deletion(volume_list)

        api_args = {
            'target-name': fake.SNAPSHOT['volume_id'],
            'target-type': 'volume',
            'terse': 'true',
        }

        self.client.send_request.assert_called_once_with(
            'snapshot-list-info', api_args)
        self.assertListEqual(expected, result)
