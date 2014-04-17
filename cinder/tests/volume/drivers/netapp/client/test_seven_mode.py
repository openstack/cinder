# Copyright (c) - 2014, Alex Meade.  All rights reserved.
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

from lxml import etree
import mock
import six

from cinder import test
from cinder.volume.drivers.netapp import api as netapp_api
from cinder.volume.drivers.netapp.client import seven_mode


class NetApp7modeClientTestCase(test.TestCase):

    def setUp(self):
        super(NetApp7modeClientTestCase, self).setUp()
        self.connection = mock.MagicMock()
        self.fake_volume = six.text_type(uuid.uuid4())
        self.client = seven_mode.Client(self.connection, [self.fake_volume])
        self.fake_lun = six.text_type(uuid.uuid4())

    def tearDown(self):
        super(NetApp7modeClientTestCase, self).tearDown()

    def test_get_target_details_no_targets(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <iscsi-portal-list-entries>
                           </iscsi-portal-list-entries>
                         </results>"""))
        self.connection.invoke_successfully.return_value = response

        target_list = self.client.get_target_details()

        self.assertEqual([], target_list)

    def test_get_target_details(self):
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

        target_list = self.client.get_target_details()

        self.assertEqual([expected_target], target_list)

    def test_get_iscsi_service_details_with_no_iscsi_service(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                         </results>"""))
        self.connection.invoke_successfully.return_value = response

        iqn = self.client.get_iscsi_service_details()

        self.assertEqual(None, iqn)

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

    def test_get_igroup_by_initiator_none_found(self):
        initiator = 'initiator'
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <initiator-groups>
                           </initiator-groups>
                         </results>"""))
        self.connection.invoke_successfully.return_value = response

        igroup = self.client.get_igroup_by_initiator(initiator)

        self.assertEqual([], igroup)

    def test_get_igroup_by_initiator(self):
        initiator = 'initiator'
        expected_igroup = {
            "initiator-group-os-type": None,
            "initiator-group-type": "1337",
            "initiator-group-name": "vserver",
        }
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <initiator-groups>
                             <initiator-group-info>
                               <initiators>
                                 <initiator-info>
                                   <initiator-name>initiator</initiator-name>
                                 </initiator-info>
                               </initiators>
    <initiator-group-type>%(initiator-group-type)s</initiator-group-type>
    <initiator-group-name>%(initiator-group-name)s</initiator-group-name>
                             </initiator-group-info>
                           </initiator-groups>
                         </results>""" % expected_igroup))
        self.connection.invoke_successfully.return_value = response

        igroup = self.client.get_igroup_by_initiator(initiator)

        self.assertEqual([expected_igroup], igroup)

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

        # Assert request is made with correct arguments
        self.assertEqual('path', lun_info_args[0].get_name())
        self.assertEqual(path, lun_info_args[0].get_content())
        self.assertEqual('enable', lun_info_args[1].get_name())
        self.assertEqual('true', lun_info_args[1].get_content())

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

        self.assertEqual(expected_actual_pathname, actual_pathname)

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

        self.client.clone_file(expected_src_path, expected_dest_path)

        __, _args, __ = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        actual_src_path = actual_request \
            .get_child_by_name('source-path').get_content()
        actual_dest_path = actual_request.get_child_by_name(
            'destination-path').get_content()

        self.assertEqual(expected_src_path, actual_src_path)
        self.assertEqual(expected_dest_path, actual_dest_path)
        self.assertEqual(actual_request.get_child_by_name(
            'destination-exists'), None)

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

        __, _args, __ = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        actual_src_path = actual_request \
            .get_child_by_name('source-path').get_content()
        actual_dest_path = actual_request.get_child_by_name(
            'destination-path').get_content()

        self.assertEqual(expected_src_path, actual_src_path)
        self.assertEqual(expected_dest_path, actual_dest_path)
        self.assertEqual(actual_request.get_child_by_name(
            'destination-exists'), None)

        __, _args, __ = self.connection.invoke_successfully.mock_calls[1]
        actual_request = _args[0]
        actual_clone_id = actual_request.get_child_by_name('clone-id')
        actual_clone_id_info = actual_clone_id.get_child_by_name(
            'clone-id-info')
        actual_clone_op_id = actual_clone_id_info.get_child_by_name(
            'clone-op-id').get_content()
        actual_volume_uuid = actual_clone_id_info.get_child_by_name(
            'volume-uuid').get_content()

        self.assertEqual(fake_clone_op_id, actual_clone_op_id)
        self.assertEqual(fake_volume_id, actual_volume_uuid)

        # Ensure that the clone-clear call is made upon error
        __, _args, __ = self.connection.invoke_successfully.mock_calls[2]
        actual_request = _args[0]
        actual_clone_id = actual_request \
            .get_child_by_name('clone-id').get_content()

        self.assertEqual(fake_clone_op_id, actual_clone_id)

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
