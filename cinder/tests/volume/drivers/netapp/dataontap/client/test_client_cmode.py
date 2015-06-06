# Copyright (c) 2014 Alex Meade.
# Copyright (c) 2015 Dustin Schoenbrun.
# All rights reserved.
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

from cinder import exception
from cinder import test
from cinder.tests.volume.drivers.netapp.dataontap.client import fakes as fake
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp import utils as netapp_utils


CONNECTION_INFO = {'hostname': 'hostname',
                   'transport_type': 'https',
                   'port': 443,
                   'username': 'admin',
                   'password': 'passw0rd',
                   'vserver': 'fake_vserver'}


class NetAppCmodeClientTestCase(test.TestCase):

    def setUp(self):
        super(NetAppCmodeClientTestCase, self).setUp()

        with mock.patch.object(client_cmode.Client,
                               'get_ontapi_version',
                               return_value=(1, 20)):
            self.client = client_cmode.Client(**CONNECTION_INFO)

        self.client.connection = mock.MagicMock()
        self.connection = self.client.connection
        self.vserver = CONNECTION_INFO['vserver']
        self.fake_volume = six.text_type(uuid.uuid4())
        self.fake_lun = six.text_type(uuid.uuid4())

    def tearDown(self):
        super(NetAppCmodeClientTestCase, self).tearDown()

    def test_get_iscsi_target_details_no_targets(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>1</num-records>
                            <attributes-list></attributes-list>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response
        target_list = self.client.get_iscsi_target_details()

        self.assertEqual([], target_list)

    def test_get_iscsi_target_details(self):
        expected_target = {
            "address": "127.0.0.1",
            "port": "1337",
            "interface-enabled": "true",
            "tpgroup-tag": "7777",
        }
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>1</num-records>
                            <attributes-list>
                              <iscsi-interface-list-entry-info>
                                <ip-address>%(address)s</ip-address>
                                <ip-port>%(port)s</ip-port>
            <is-interface-enabled>%(interface-enabled)s</is-interface-enabled>
                                <tpgroup-tag>%(tpgroup-tag)s</tpgroup-tag>
                              </iscsi-interface-list-entry-info>
                            </attributes-list>
                          </results>""" % expected_target))
        self.connection.invoke_successfully.return_value = response

        target_list = self.client.get_iscsi_target_details()

        self.assertEqual([expected_target], target_list)

    def test_get_iscsi_service_details_with_no_iscsi_service(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>0</num-records>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        iqn = self.client.get_iscsi_service_details()

        self.assertEqual(None, iqn)

    def test_get_iscsi_service_details(self):
        expected_iqn = 'iqn.1998-01.org.openstack.iscsi:name1'
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>1</num-records>
                            <attributes-list>
                              <iscsi-service-info>
                                <node-name>%s</node-name>
                              </iscsi-service-info>
                            </attributes-list>
                          </results>""" % expected_iqn))
        self.connection.invoke_successfully.return_value = response

        iqn = self.client.get_iscsi_service_details()

        self.assertEqual(expected_iqn, iqn)

    def test_get_lun_list(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>2</num-records>
                            <attributes-list>
                              <lun-info>
                              </lun-info>
                              <lun-info>
                              </lun-info>
                            </attributes-list>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        luns = self.client.get_lun_list()

        self.assertEqual(2, len(luns))

    def test_get_lun_list_with_multiple_pages(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>2</num-records>
                            <attributes-list>
                              <lun-info> </lun-info>
                              <lun-info> </lun-info>
                            </attributes-list>
                            <next-tag>fake-next</next-tag>
                          </results>"""))
        response_2 = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>2</num-records>
                            <attributes-list>
                              <lun-info> </lun-info>
                              <lun-info> </lun-info>
                            </attributes-list>
                          </results>"""))
        self.connection.invoke_successfully.side_effect = [response,
                                                           response_2]

        luns = self.client.get_lun_list()

        self.assertEqual(4, len(luns))

    def test_get_lun_map_no_luns_mapped(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>0</num-records>
                            <attributes-list></attributes-list>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        lun_map = self.client.get_lun_map(path)

        self.assertEqual([], lun_map)

    def test_get_lun_map(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        expected_lun_map = {
            "initiator-group": "igroup",
            "lun-id": "1337",
            "vserver": "vserver",
        }
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>1</num-records>
                            <attributes-list>
                              <lun-map-info>
                                <lun-id>%(lun-id)s</lun-id>
                        <initiator-group>%(initiator-group)s</initiator-group>
                                <vserver>%(vserver)s</vserver>
                              </lun-map-info>
                            </attributes-list>
                          </results>""" % expected_lun_map))
        self.connection.invoke_successfully.return_value = response

        lun_map = self.client.get_lun_map(path)

        self.assertEqual([expected_lun_map], lun_map)

    def test_get_lun_map_multiple_pages(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        expected_lun_map = {
            "initiator-group": "igroup",
            "lun-id": "1337",
            "vserver": "vserver",
        }
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>1</num-records>
                            <attributes-list>
                              <lun-map-info>
                                <lun-id>%(lun-id)s</lun-id>
                        <initiator-group>%(initiator-group)s</initiator-group>
                                <vserver>%(vserver)s</vserver>
                              </lun-map-info>
                            </attributes-list>
                            <next-tag>blah</next-tag>
                          </results>""" % expected_lun_map))
        response_2 = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>1</num-records>
                            <attributes-list>
                              <lun-map-info>
                                <lun-id>%(lun-id)s</lun-id>
                        <initiator-group>%(initiator-group)s</initiator-group>
                                <vserver>%(vserver)s</vserver>
                              </lun-map-info>
                            </attributes-list>
                          </results>""" % expected_lun_map))
        self.connection.invoke_successfully.side_effect = [response,
                                                           response_2]

        lun_map = self.client.get_lun_map(path)

        self.assertEqual([expected_lun_map, expected_lun_map], lun_map)

    def test_get_igroup_by_initiator_none_found(self):
        initiator = 'initiator'
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>0</num-records>
                            <attributes-list></attributes-list>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        igroup = self.client.get_igroup_by_initiators([initiator])

        self.assertEqual([], igroup)

    def test_get_igroup_by_initiators(self):
        initiators = ['11:22:33:44:55:66:77:88']
        expected_igroup = {
            'initiator-group-os-type': 'default',
            'initiator-group-type': 'fcp',
            'initiator-group-name': 'openstack-igroup1',
        }

        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
    <attributes-list>
      <initiator-group-info>
        <initiator-group-alua-enabled>true</initiator-group-alua-enabled>
        <initiator-group-name>%(initiator-group-name)s</initiator-group-name>
        <initiator-group-os-type>default</initiator-group-os-type>
        <initiator-group-throttle-borrow>false</initiator-group-throttle-borrow>
        <initiator-group-throttle-reserve>0</initiator-group-throttle-reserve>
        <initiator-group-type>%(initiator-group-type)s</initiator-group-type>
        <initiator-group-use-partner>true</initiator-group-use-partner>
        <initiator-group-uuid>f8aa707a-57fa-11e4-ad08-123478563412
        </initiator-group-uuid>
        <initiator-group-vsa-enabled>false</initiator-group-vsa-enabled>
        <initiators>
          <initiator-info>
            <initiator-name>11:22:33:44:55:66:77:88</initiator-name>
          </initiator-info>
        </initiators>
        <vserver>cinder-iscsi</vserver>
      </initiator-group-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>""" % expected_igroup))
        self.connection.invoke_successfully.return_value = response

        igroups = self.client.get_igroup_by_initiators(initiators)

        # make these lists of dicts comparable using hashable dictionaries
        igroups = set(
            [netapp_utils.hashabledict(igroup) for igroup in igroups])
        expected = set([netapp_utils.hashabledict(expected_igroup)])

        self.assertSetEqual(igroups, expected)

    def test_get_igroup_by_initiators_multiple(self):
        initiators = ['11:22:33:44:55:66:77:88', '88:77:66:55:44:33:22:11']
        expected_igroup = {
            'initiator-group-os-type': 'default',
            'initiator-group-type': 'fcp',
            'initiator-group-name': 'openstack-igroup1',
        }

        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
    <attributes-list>
      <initiator-group-info>
        <initiator-group-alua-enabled>true</initiator-group-alua-enabled>
        <initiator-group-name>%(initiator-group-name)s</initiator-group-name>
        <initiator-group-os-type>default</initiator-group-os-type>
        <initiator-group-throttle-borrow>false</initiator-group-throttle-borrow>
        <initiator-group-throttle-reserve>0</initiator-group-throttle-reserve>
        <initiator-group-type>%(initiator-group-type)s</initiator-group-type>
        <initiator-group-use-partner>true</initiator-group-use-partner>
        <initiator-group-uuid>f8aa707a-57fa-11e4-ad08-123478563412
        </initiator-group-uuid>
        <initiator-group-vsa-enabled>false</initiator-group-vsa-enabled>
        <initiators>
          <initiator-info>
            <initiator-name>11:22:33:44:55:66:77:88</initiator-name>
          </initiator-info>
          <initiator-info>
            <initiator-name>88:77:66:55:44:33:22:11</initiator-name>
          </initiator-info>
        </initiators>
        <vserver>cinder-iscsi</vserver>
      </initiator-group-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>""" % expected_igroup))
        self.connection.invoke_successfully.return_value = response

        igroups = self.client.get_igroup_by_initiators(initiators)

        # make these lists of dicts comparable using hashable dictionaries
        igroups = set(
            [netapp_utils.hashabledict(igroup) for igroup in igroups])
        expected = set([netapp_utils.hashabledict(expected_igroup)])

        self.assertSetEqual(igroups, expected)

    def test_get_igroup_by_initiators_multiple_pages(self):
        initiator = '11:22:33:44:55:66:77:88'
        expected_igroup1 = {
            'initiator-group-os-type': 'default',
            'initiator-group-type': 'fcp',
            'initiator-group-name': 'openstack-igroup1',
        }
        expected_igroup2 = {
            'initiator-group-os-type': 'default',
            'initiator-group-type': 'fcp',
            'initiator-group-name': 'openstack-igroup2',
        }
        response_1 = netapp_api.NaElement(
            etree.XML("""<results status="passed">
    <attributes-list>
      <initiator-group-info>
        <initiator-group-alua-enabled>true</initiator-group-alua-enabled>
        <initiator-group-name>%(initiator-group-name)s</initiator-group-name>
        <initiator-group-os-type>default</initiator-group-os-type>
        <initiator-group-throttle-borrow>false</initiator-group-throttle-borrow>
        <initiator-group-throttle-reserve>0</initiator-group-throttle-reserve>
        <initiator-group-type>%(initiator-group-type)s</initiator-group-type>
        <initiator-group-use-partner>true</initiator-group-use-partner>
        <initiator-group-uuid>f8aa707a-57fa-11e4-ad08-123478563412
        </initiator-group-uuid>
        <initiator-group-vsa-enabled>false</initiator-group-vsa-enabled>
        <initiators>
          <initiator-info>
            <initiator-name>11:22:33:44:55:66:77:88</initiator-name>
          </initiator-info>
        </initiators>
        <vserver>cinder-iscsi</vserver>
      </initiator-group-info>
    </attributes-list>
    <next-tag>12345</next-tag>
    <num-records>1</num-records>
  </results>""" % expected_igroup1))
        response_2 = netapp_api.NaElement(
            etree.XML("""<results status="passed">
    <attributes-list>
      <initiator-group-info>
        <initiator-group-alua-enabled>true</initiator-group-alua-enabled>
        <initiator-group-name>%(initiator-group-name)s</initiator-group-name>
        <initiator-group-os-type>default</initiator-group-os-type>
        <initiator-group-throttle-borrow>false</initiator-group-throttle-borrow>
        <initiator-group-throttle-reserve>0</initiator-group-throttle-reserve>
        <initiator-group-type>%(initiator-group-type)s</initiator-group-type>
        <initiator-group-use-partner>true</initiator-group-use-partner>
        <initiator-group-uuid>f8aa707a-57fa-11e4-ad08-123478563412
        </initiator-group-uuid>
        <initiator-group-vsa-enabled>false</initiator-group-vsa-enabled>
        <initiators>
          <initiator-info>
            <initiator-name>11:22:33:44:55:66:77:88</initiator-name>
          </initiator-info>
        </initiators>
        <vserver>cinder-iscsi</vserver>
      </initiator-group-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>""" % expected_igroup2))
        self.connection.invoke_successfully.side_effect = [response_1,
                                                           response_2]

        igroups = self.client.get_igroup_by_initiators([initiator])

        # make these lists of dicts comparable using hashable dictionaries
        igroups = set(
            [netapp_utils.hashabledict(igroup) for igroup in igroups])
        expected = set([netapp_utils.hashabledict(expected_igroup1),
                        netapp_utils.hashabledict(expected_igroup2)])

        self.assertSetEqual(igroups, expected)

    def test_clone_lun(self):
        self.client.clone_lun('volume', 'fakeLUN', 'newFakeLUN')
        self.assertEqual(1, self.connection.invoke_successfully.call_count)

    def test_clone_lun_multiple_zapi_calls(self):
        """Test for when lun clone requires more than one zapi call."""

        # Max block-ranges per call = 32, max blocks per range = 2^24
        # Force 2 calls
        bc = 2 ** 24 * 32 * 2
        self.client.clone_lun('volume', 'fakeLUN', 'newFakeLUN',
                              block_count=bc)
        self.assertEqual(2, self.connection.invoke_successfully.call_count)

    def test_get_lun_by_args(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>2</num-records>
                            <attributes-list>
                              <lun-info>
                              </lun-info>
                            </attributes-list>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        lun = self.client.get_lun_by_args()

        self.assertEqual(1, len(lun))

    def test_get_lun_by_args_no_lun_found(self):
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>2</num-records>
                            <attributes-list>
                            </attributes-list>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        lun = self.client.get_lun_by_args()

        self.assertEqual(0, len(lun))

    def test_get_lun_by_args_with_args_specified(self):
        path = '/vol/%s/%s' % (self.fake_volume, self.fake_lun)
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>2</num-records>
                            <attributes-list>
                              <lun-info>
                              </lun-info>
                            </attributes-list>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        lun = self.client.get_lun_by_args(path=path)

        __, _args, __ = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        query = actual_request.get_child_by_name('query')
        lun_info_args = query.get_child_by_name('lun-info').get_children()

        # Assert request is made with correct arguments
        self.assertEqual('path', lun_info_args[0].get_name())
        self.assertEqual(path, lun_info_args[0].get_content())

        self.assertEqual(1, len(lun))

    def test_file_assign_qos(self):
        expected_flex_vol = "fake_flex_vol"
        expected_policy_group = "fake_policy_group"
        expected_file_path = "fake_file_path"

        self.client.file_assign_qos(expected_flex_vol, expected_policy_group,
                                    expected_file_path)

        __, _args, __ = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        actual_flex_vol = actual_request.get_child_by_name('volume') \
            .get_content()
        actual_policy_group = actual_request \
            .get_child_by_name('qos-policy-group-name').get_content()
        actual_file_path = actual_request.get_child_by_name('file') \
            .get_content()
        actual_vserver = actual_request.get_child_by_name('vserver') \
            .get_content()

        self.assertEqual(expected_flex_vol, actual_flex_vol)
        self.assertEqual(expected_policy_group, actual_policy_group)
        self.assertEqual(expected_file_path, actual_file_path)
        self.assertEqual(self.vserver, actual_vserver)

    @mock.patch('cinder.volume.drivers.netapp.utils.resolve_hostname',
                return_value='192.168.1.101')
    def test_get_if_info_by_ip_not_found(self, mock_resolve_hostname):
        fake_ip = '192.168.1.101'
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>0</num-records>
                            <attributes-list>
                            </attributes-list>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        self.assertRaises(exception.NotFound, self.client.get_if_info_by_ip,
                          fake_ip)

    @mock.patch('cinder.volume.drivers.netapp.utils.resolve_hostname',
                return_value='192.168.1.101')
    def test_get_if_info_by_ip(self, mock_resolve_hostname):
        fake_ip = '192.168.1.101'
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>1</num-records>
                            <attributes-list>
                                <net-interface-info>
                                </net-interface-info>
                            </attributes-list>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        results = self.client.get_if_info_by_ip(fake_ip)

        self.assertEqual(1, len(results))

    def test_get_vol_by_junc_vserver_not_found(self):
        fake_vserver = 'fake_vserver'
        fake_junc = 'fake_junction_path'
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>0</num-records>
                            <attributes-list>
                            </attributes-list>
                          </results>"""))
        self.connection.invoke_successfully.return_value = response

        self.assertRaises(exception.NotFound,
                          self.client.get_vol_by_junc_vserver,
                          fake_vserver, fake_junc)

    def test_get_vol_by_junc_vserver(self):
        fake_vserver = 'fake_vserver'
        fake_junc = 'fake_junction_path'
        expected_flex_vol = 'fake_flex_vol'
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                            <num-records>1</num-records>
                            <attributes-list>
                              <volume-attributes>
                                <volume-id-attributes>
                                  <name>%(flex_vol)s</name>
                                </volume-id-attributes>
                              </volume-attributes>
                            </attributes-list>
                          </results>""" % {'flex_vol': expected_flex_vol}))
        self.connection.invoke_successfully.return_value = response

        actual_flex_vol = self.client.get_vol_by_junc_vserver(fake_vserver,
                                                              fake_junc)

        self.assertEqual(expected_flex_vol, actual_flex_vol)

    def test_clone_file(self):
        expected_flex_vol = "fake_flex_vol"
        expected_src_path = "fake_src_path"
        expected_dest_path = "fake_dest_path"
        self.connection.get_api_version.return_value = (1, 20)

        self.client.clone_file(expected_flex_vol, expected_src_path,
                               expected_dest_path, self.vserver)

        __, _args, __ = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        actual_flex_vol = actual_request.get_child_by_name('volume') \
            .get_content()
        actual_src_path = actual_request \
            .get_child_by_name('source-path').get_content()
        actual_dest_path = actual_request.get_child_by_name(
            'destination-path').get_content()

        self.assertEqual(expected_flex_vol, actual_flex_vol)
        self.assertEqual(expected_src_path, actual_src_path)
        self.assertEqual(expected_dest_path, actual_dest_path)
        self.assertEqual(actual_request.get_child_by_name(
            'destination-exists'), None)

    def test_clone_file_when_destination_exists(self):
        expected_flex_vol = "fake_flex_vol"
        expected_src_path = "fake_src_path"
        expected_dest_path = "fake_dest_path"
        self.connection.get_api_version.return_value = (1, 20)

        self.client.clone_file(expected_flex_vol, expected_src_path,
                               expected_dest_path, self.vserver,
                               dest_exists=True)

        __, _args, __ = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        actual_flex_vol = actual_request.get_child_by_name('volume') \
            .get_content()
        actual_src_path = actual_request \
            .get_child_by_name('source-path').get_content()
        actual_dest_path = actual_request.get_child_by_name(
            'destination-path').get_content()

        self.assertEqual(expected_flex_vol, actual_flex_vol)
        self.assertEqual(expected_src_path, actual_src_path)
        self.assertEqual(expected_dest_path, actual_dest_path)
        self.assertEqual(actual_request.get_child_by_name(
            'destination-exists').get_content(), 'true')

    def test_clone_file_when_destination_exists_and_version_less_than_1_20(
            self):
        expected_flex_vol = "fake_flex_vol"
        expected_src_path = "fake_src_path"
        expected_dest_path = "fake_dest_path"
        self.connection.get_api_version.return_value = (1, 19)

        self.client.clone_file(expected_flex_vol, expected_src_path,
                               expected_dest_path, self.vserver,
                               dest_exists=True)

        __, _args, __ = self.connection.invoke_successfully.mock_calls[0]
        actual_request = _args[0]
        actual_flex_vol = actual_request.get_child_by_name('volume') \
            .get_content()
        actual_src_path = actual_request \
            .get_child_by_name('source-path').get_content()
        actual_dest_path = actual_request.get_child_by_name(
            'destination-path').get_content()

        self.assertEqual(expected_flex_vol, actual_flex_vol)
        self.assertEqual(expected_src_path, actual_src_path)
        self.assertEqual(expected_dest_path, actual_dest_path)
        self.assertEqual(actual_request.get_child_by_name(
            'destination-exists'), None)

    def test_get_file_usage(self):
        expected_bytes = "2048"
        fake_vserver = 'fake_vserver'
        fake_path = 'fake_path'
        response = netapp_api.NaElement(
            etree.XML("""<results status="passed">
                           <unique-bytes>%(unique-bytes)s</unique-bytes>
                         </results>""" % {'unique-bytes': expected_bytes}))
        self.connection.invoke_successfully.return_value = response

        actual_bytes = self.client.get_file_usage(fake_vserver, fake_path)

        self.assertEqual(expected_bytes, actual_bytes)

    def test_get_operational_network_interface_addresses(self):
        expected_result = ['1.2.3.4', '99.98.97.96']
        api_response = netapp_api.NaElement(
            fake.GET_OPERATIONAL_NETWORK_INTERFACE_ADDRESSES_RESPONSE)
        self.connection.invoke_successfully.return_value = api_response

        address_list = (
            self.client.get_operational_network_interface_addresses())

        self.assertEqual(expected_result, address_list)

    def test_get_flexvol_capacity(self):
        expected_total_size = 1000
        expected_available_size = 750
        fake_flexvol_path = '/fake/vol'
        response = netapp_api.NaElement(
            etree.XML("""
            <results status="passed">
                <attributes-list>
                    <volume-attributes>
                        <volume-space-attributes>
                            <size-available>%(available_size)s</size-available>
                            <size-total>%(total_size)s</size-total>
                        </volume-space-attributes>
                    </volume-attributes>
                </attributes-list>
            </results>""" % {'available_size': expected_available_size,
                             'total_size': expected_total_size}))
        self.connection.invoke_successfully.return_value = response

        total_size, available_size = (
            self.client.get_flexvol_capacity(fake_flexvol_path))

        self.assertEqual(expected_total_size, total_size)
        self.assertEqual(expected_available_size, available_size)
