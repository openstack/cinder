# Copyright (c) 2016 Hitachi Data Systems, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
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
#

import mock
import os

from oslo_config import cfg
from xml.etree import ElementTree as ETree

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_constants
from cinder.tests.unit import fake_volume
from cinder.volume.drivers.hitachi import hnas_utils
from cinder.volume import volume_types


_VOLUME = {'name': 'cinder-volume',
           'id': fake_constants.VOLUME_ID,
           'size': 128,
           'host': 'host1@hnas-nfs-backend#default',
           'volume_type': 'default',
           'provider_location': 'hnas'}

service_parameters = ['volume_type', 'hdp']
optional_parameters = ['hnas_cmd', 'cluster_admin_ip0', 'iscsi_ip']

config_from_cinder_conf = {
    'username': 'supervisor',
    'fs': {'silver': 'silver',
           'easy-stack': 'easy-stack'},
    'ssh_port': '22',
    'chap_enabled': None,
    'cluster_admin_ip0': None,
    'ssh_private_key': None,
    'mgmt_ip0': '172.24.44.15',
    'services': {
        'default': {
            'label': u'svc_0',
            'volume_type': 'default',
            'hdp': 'easy-stack'},
        'FS-CinderDev1': {
            'label': u'svc_1',
            'volume_type': 'FS-CinderDev1',
            'hdp': 'silver'}},
    'password': 'supervisor',
    'hnas_cmd': 'ssc'}

valid_XML_str = '''
<config>
  <mgmt_ip0>172.24.44.15</mgmt_ip0>
  <username>supervisor</username>
  <password>supervisor</password>
  <ssh_enabled>False</ssh_enabled>
  <ssh_private_key>/home/ubuntu/.ssh/id_rsa</ssh_private_key>
  <svc_0>
    <volume_type>default</volume_type>
    <iscsi_ip>172.24.49.21</iscsi_ip>
    <hdp>easy-stack</hdp>
  </svc_0>
  <svc_1>
    <volume_type>silver</volume_type>
    <iscsi_ip>172.24.49.32</iscsi_ip>
    <hdp>FS-CinderDev1</hdp>
  </svc_1>
</config>
'''

XML_no_authentication = '''
<config>
  <mgmt_ip0>172.24.44.15</mgmt_ip0>
  <username>supervisor</username>
  <ssh_enabled>False</ssh_enabled>
</config>
'''

XML_empty_authentication_param = '''
<config>
  <mgmt_ip0>172.24.44.15</mgmt_ip0>
  <username>supervisor</username>
  <password></password>
  <ssh_enabled>False</ssh_enabled>
  <ssh_private_key></ssh_private_key>
  <svc_0>
    <volume_type>default</volume_type>
    <iscsi_ip>172.24.49.21</iscsi_ip>
    <hdp>easy-stack</hdp>
  </svc_0>
</config>
'''

# missing mgmt_ip0
XML_without_mandatory_params = '''
<config>
  <username>supervisor</username>
  <password>supervisor</password>
  <ssh_enabled>False</ssh_enabled>
  <svc_0>
    <volume_type>default</volume_type>
    <iscsi_ip>172.24.49.21</iscsi_ip>
    <hdp>easy-stack</hdp>
  </svc_0>
</config>
'''

XML_no_services_configured = '''
<config>
  <mgmt_ip0>172.24.44.15</mgmt_ip0>
  <username>supervisor</username>
  <password>supervisor</password>
  <ssh_enabled>False</ssh_enabled>
  <ssh_private_key>/home/ubuntu/.ssh/id_rsa</ssh_private_key>
</config>
'''

parsed_xml = {'username': 'supervisor', 'password': 'supervisor',
              'hnas_cmd': 'ssc', 'iscsi_ip': None, 'ssh_port': '22',
              'fs': {'easy-stack': 'easy-stack',
                     'FS-CinderDev1': 'FS-CinderDev1'},
              'cluster_admin_ip0': None,
              'ssh_private_key': '/home/ubuntu/.ssh/id_rsa',
              'services': {
                  'default': {'hdp': 'easy-stack', 'volume_type': 'default',
                              'label': 'svc_0'},
                  'silver': {'hdp': 'FS-CinderDev1', 'volume_type': 'silver',
                             'label': 'svc_1'}},
              'mgmt_ip0': '172.24.44.15'}

valid_XML_etree = ETree.XML(valid_XML_str)
invalid_XML_etree_no_authentication = ETree.XML(XML_no_authentication)
invalid_XML_etree_empty_parameter = ETree.XML(XML_empty_authentication_param)
invalid_XML_etree_no_mandatory_params = ETree.XML(XML_without_mandatory_params)
invalid_XML_etree_no_service = ETree.XML(XML_no_services_configured)

CONF = cfg.CONF


class HNASUtilsTest(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(HNASUtilsTest, self).__init__(*args, **kwargs)

    def setUp(self):
        super(HNASUtilsTest, self).setUp()
        self.context = context.get_admin_context()
        self.volume = fake_volume.fake_volume_obj(self.context, **_VOLUME)
        self.volume_type = (fake_volume.fake_volume_type_obj(None, **{
            'id': fake_constants.VOLUME_TYPE_ID, 'name': 'silver'}))

    def test_read_config(self):

        self.mock_object(os, 'access', mock.Mock(return_value=True))
        self.mock_object(ETree, 'parse',
                         mock.Mock(return_value=ETree.ElementTree))
        self.mock_object(ETree.ElementTree, 'getroot',
                         mock.Mock(return_value=valid_XML_etree))

        xml_path = 'xml_file_found'
        out = hnas_utils.read_config(xml_path,
                                     service_parameters,
                                     optional_parameters)

        self.assertEqual(parsed_xml, out)

    def test_read_config_parser_error(self):
        xml_file = 'hnas_nfs.xml'
        self.mock_object(os, 'access', mock.Mock(return_value=True))
        self.mock_object(ETree, 'parse',
                         mock.Mock(side_effect=ETree.ParseError))

        self.assertRaises(exception.ConfigNotFound, hnas_utils.read_config,
                          xml_file, service_parameters, optional_parameters)

    def test_read_config_not_found(self):
        self.mock_object(os, 'access', mock.Mock(return_value=False))

        xml_path = 'xml_file_not_found'
        self.assertRaises(exception.NotFound, hnas_utils.read_config,
                          xml_path, service_parameters, optional_parameters)

    def test_read_config_without_services_configured(self):
        xml_file = 'hnas_nfs.xml'

        self.mock_object(os, 'access', mock.Mock(return_value=True))
        self.mock_object(ETree, 'parse',
                         mock.Mock(return_value=ETree.ElementTree))
        self.mock_object(ETree.ElementTree, 'getroot',
                         mock.Mock(return_value=invalid_XML_etree_no_service))

        self.assertRaises(exception.ParameterNotFound, hnas_utils.read_config,
                          xml_file, service_parameters, optional_parameters)

    def test_read_config_empty_authentication_parameter(self):
        xml_file = 'hnas_nfs.xml'

        self.mock_object(os, 'access', mock.Mock(return_value=True))
        self.mock_object(ETree, 'parse',
                         mock.Mock(return_value=ETree.ElementTree))
        self.mock_object(ETree.ElementTree, 'getroot',
                         mock.Mock(return_value=
                                   invalid_XML_etree_empty_parameter))

        self.assertRaises(exception.ParameterNotFound, hnas_utils.read_config,
                          xml_file, service_parameters, optional_parameters)

    def test_read_config_mandatory_parameters_missing(self):
        xml_file = 'hnas_nfs.xml'

        self.mock_object(os, 'access', mock.Mock(return_value=True))
        self.mock_object(ETree, 'parse',
                         mock.Mock(return_value=ETree.ElementTree))
        self.mock_object(ETree.ElementTree, 'getroot',
                         mock.Mock(return_value=
                                   invalid_XML_etree_no_mandatory_params))

        self.assertRaises(exception.ParameterNotFound, hnas_utils.read_config,
                          xml_file, service_parameters, optional_parameters)

    def test_read_config_XML_without_authentication_parameter(self):
        xml_file = 'hnas_nfs.xml'

        self.mock_object(os, 'access', mock.Mock(return_value=True))
        self.mock_object(ETree, 'parse',
                         mock.Mock(return_value=ETree.ElementTree))
        self.mock_object(ETree.ElementTree, 'getroot',
                         mock.Mock(return_value=
                                   invalid_XML_etree_no_authentication))

        self.assertRaises(exception.ConfigNotFound, hnas_utils.read_config,
                          xml_file, service_parameters, optional_parameters)

    def test_get_pool_with_vol_type(self):
        self.mock_object(volume_types, 'get_volume_type_extra_specs',
                         mock.Mock(return_value={'service_label': 'silver'}))

        self.volume.volume_type_id = fake_constants.VOLUME_TYPE_ID
        self.volume.volume_type = self.volume_type

        out = hnas_utils.get_pool(parsed_xml, self.volume)

        self.assertEqual('silver', out)

    def test_get_pool_without_vol_type(self):
        out = hnas_utils.get_pool(parsed_xml, self.volume)
        self.assertEqual('default', out)
