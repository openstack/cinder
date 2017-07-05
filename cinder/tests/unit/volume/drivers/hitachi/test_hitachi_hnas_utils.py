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

import ddt
import os

from xml.etree import ElementTree as ETree

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_constants
from cinder.tests.unit import fake_volume
from cinder.volume import configuration as conf
from cinder.volume.drivers.hitachi import hnas_utils
from cinder.volume import volume_types

_VOLUME = {'name': 'cinder-volume',
           'id': fake_constants.VOLUME_ID,
           'size': 128,
           'host': 'host1@hnas-nfs-backend#default',
           'volume_type': 'default',
           'provider_location': 'hnas'}

service_parameters = ['volume_type', 'hdp']
optional_parameters = ['ssc_cmd', 'cluster_admin_ip0']

config_from_cinder_conf = {
    'username': 'supervisor',
    'fs': {'easy-stack': 'easy-stack',
           'silver': 'silver'},
    'ssh_port': 22,
    'cluster_admin_ip0': None,
    'ssh_private_key': None,
    'mgmt_ip0': '172.24.44.15',
    'ssc_cmd': 'ssc',
    'services': {
        'default': {
            'label': u'svc_0',
            'pool_name': 'default',
            'hdp': 'easy-stack'},
        'FS-CinderDev1': {
            'label': u'svc_1',
            'pool_name': 'FS-CinderDev1',
            'hdp': 'silver'}},
    'password': 'supervisor'}

valid_XML_str = '''
<config>
  <mgmt_ip0>172.24.44.15</mgmt_ip0>
  <username>supervisor</username>
  <password>supervisor</password>
  <ssh_enabled>False</ssh_enabled>
  <ssh_private_key>/home/ubuntu/.ssh/id_rsa</ssh_private_key>
  <svc_0>
    <volume_type>default</volume_type>
    <hdp>easy-stack</hdp>
  </svc_0>
  <svc_1>
    <volume_type>silver</volume_type>
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
    <hdp>easy-stack</hdp>
  </svc_0>
</config>
'''

XML_no_services_configured = '''
<config>
  <mgmt_ip0>172.24.44.15</mgmt_ip0>
  <username>supervisor</username>
  <password>supervisor</password>
  <ssh_port>10</ssh_port>
  <ssh_enabled>False</ssh_enabled>
  <ssh_private_key>/home/ubuntu/.ssh/id_rsa</ssh_private_key>
</config>
'''

parsed_xml = {'username': 'supervisor', 'password': 'supervisor',
              'ssc_cmd': 'ssc', 'ssh_port': 22,
              'fs': {'easy-stack': 'easy-stack',
                     'FS-CinderDev1': 'FS-CinderDev1'},
              'cluster_admin_ip0': None,
              'ssh_private_key': '/home/ubuntu/.ssh/id_rsa',
              'services': {
                  'default': {'hdp': 'easy-stack', 'pool_name': 'default',
                              'label': 'svc_0'},
                  'silver': {'hdp': 'FS-CinderDev1', 'pool_name': 'silver',
                             'label': 'svc_1'}},
              'mgmt_ip0': '172.24.44.15'}

valid_XML_etree = ETree.XML(valid_XML_str)
invalid_XML_etree_no_authentication = ETree.XML(XML_no_authentication)
invalid_XML_etree_empty_parameter = ETree.XML(XML_empty_authentication_param)
invalid_XML_etree_no_mandatory_params = ETree.XML(XML_without_mandatory_params)
invalid_XML_etree_no_service = ETree.XML(XML_no_services_configured)


@ddt.ddt
class HNASUtilsTest(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(HNASUtilsTest, self).__init__(*args, **kwargs)

    def setUp(self):
        super(HNASUtilsTest, self).setUp()

        self.fake_conf = conf.Configuration(hnas_utils.drivers_common_opts,
                                            conf.SHARED_CONF_GROUP)

        self.override_config('hnas_username', 'supervisor',
                             conf.SHARED_CONF_GROUP)
        self.override_config('hnas_password', 'supervisor',
                             conf.SHARED_CONF_GROUP)
        self.override_config('hnas_mgmt_ip0', '172.24.44.15',
                             conf.SHARED_CONF_GROUP)
        self.override_config('hnas_svc0_pool_name', 'default',
                             conf.SHARED_CONF_GROUP)
        self.override_config('hnas_svc0_hdp', 'easy-stack',
                             conf.SHARED_CONF_GROUP)
        self.override_config('hnas_svc1_pool_name', 'FS-CinderDev1',
                             conf.SHARED_CONF_GROUP)
        self.override_config('hnas_svc1_hdp', 'silver',
                             conf.SHARED_CONF_GROUP)

        self.context = context.get_admin_context()
        self.volume = fake_volume.fake_volume_obj(self.context, **_VOLUME)
        self.volume_type = (fake_volume.fake_volume_type_obj(None, **{
            'id': fake_constants.VOLUME_TYPE_ID, 'name': 'silver'}))

    def test_read_xml_config(self):
        self.mock_object(os, 'access', return_value=True)
        self.mock_object(ETree, 'parse', return_value=ETree.ElementTree)
        self.mock_object(ETree.ElementTree, 'getroot',
                         return_value=valid_XML_etree)

        xml_path = 'xml_file_found'
        out = hnas_utils.read_xml_config(xml_path,
                                         service_parameters,
                                         optional_parameters)

        self.assertEqual(parsed_xml, out)

    def test_read_xml_config_parser_error(self):
        xml_file = 'hnas_nfs.xml'
        self.mock_object(os, 'access', return_value=True)
        self.mock_object(ETree, 'parse', side_effect=ETree.ParseError)

        self.assertRaises(exception.ConfigNotFound, hnas_utils.read_xml_config,
                          xml_file, service_parameters, optional_parameters)

    def test_read_xml_config_not_found(self):
        self.mock_object(os, 'access', return_value=False)

        xml_path = 'xml_file_not_found'
        self.assertRaises(exception.NotFound, hnas_utils.read_xml_config,
                          xml_path, service_parameters, optional_parameters)

    def test_read_xml_config_without_services_configured(self):
        xml_file = 'hnas_nfs.xml'

        self.mock_object(os, 'access', return_value=True)
        self.mock_object(ETree, 'parse', return_value=ETree.ElementTree)
        self.mock_object(ETree.ElementTree, 'getroot',
                         return_value=invalid_XML_etree_no_service)

        self.assertRaises(exception.ParameterNotFound,
                          hnas_utils.read_xml_config, xml_file,
                          service_parameters, optional_parameters)

    def test_read_xml_config_empty_authentication_parameter(self):
        xml_file = 'hnas_nfs.xml'

        self.mock_object(os, 'access', return_value=True)
        self.mock_object(ETree, 'parse', return_value=ETree.ElementTree)
        self.mock_object(ETree.ElementTree, 'getroot',
                         return_value=invalid_XML_etree_empty_parameter)

        self.assertRaises(exception.ParameterNotFound,
                          hnas_utils.read_xml_config, xml_file,
                          service_parameters, optional_parameters)

    def test_read_xml_config_mandatory_parameters_missing(self):
        xml_file = 'hnas_nfs.xml'

        self.mock_object(os, 'access', return_value=True)
        self.mock_object(ETree, 'parse', return_value=ETree.ElementTree)
        self.mock_object(ETree.ElementTree, 'getroot',
                         return_value=invalid_XML_etree_no_mandatory_params)

        self.assertRaises(exception.ParameterNotFound,
                          hnas_utils.read_xml_config, xml_file,
                          service_parameters, optional_parameters)

    def test_read_config_xml_without_authentication_parameter(self):
        xml_file = 'hnas_nfs.xml'

        self.mock_object(os, 'access', return_value=True)
        self.mock_object(ETree, 'parse', return_value=ETree.ElementTree)
        self.mock_object(ETree.ElementTree, 'getroot',
                         return_value=invalid_XML_etree_no_authentication)

        self.assertRaises(exception.ConfigNotFound, hnas_utils.read_xml_config,
                          xml_file, service_parameters, optional_parameters)

    def test_get_pool_with_vol_type(self):
        self.mock_object(volume_types, 'get_volume_type_extra_specs',
                         return_value={'service_label': 'silver'})

        self.volume.volume_type_id = fake_constants.VOLUME_TYPE_ID
        self.volume.volume_type = self.volume_type

        out = hnas_utils.get_pool(parsed_xml, self.volume)

        self.assertEqual('silver', out)

    def test_get_pool_with_vol_type_id_none(self):
        self.volume.volume_type_id = None
        self.volume.volume_type = self.volume_type

        out = hnas_utils.get_pool(parsed_xml, self.volume)

        self.assertEqual('default', out)

    def test_get_pool_with_missing_service_label(self):
        self.mock_object(volume_types, 'get_volume_type_extra_specs',
                         return_value={'service_label': 'gold'})

        self.volume.volume_type_id = fake_constants.VOLUME_TYPE_ID
        self.volume.volume_type = self.volume_type

        out = hnas_utils.get_pool(parsed_xml, self.volume)

        self.assertEqual('default', out)

    def test_get_pool_without_vol_type(self):
        out = hnas_utils.get_pool(parsed_xml, self.volume)
        self.assertEqual('default', out)

    def test_read_cinder_conf_nfs(self):
        out = hnas_utils.read_cinder_conf(self.fake_conf)

        self.assertEqual(config_from_cinder_conf, out)

    def test_read_cinder_conf_break(self):
        self.override_config('hnas_username', None, conf.SHARED_CONF_GROUP)
        self.override_config('hnas_password', None, conf.SHARED_CONF_GROUP)
        self.override_config('hnas_mgmt_ip0', None, conf.SHARED_CONF_GROUP)
        out = hnas_utils.read_cinder_conf(self.fake_conf)
        self.assertIsNone(out)

    @ddt.data('hnas_username', 'hnas_password',
              'hnas_mgmt_ip0', 'hnas_svc0_pool_name',
              'hnas_svc0_hdp', )
    def test_init_invalid_conf_parameters(self, attr_name):
        self.override_config(attr_name, None, conf.SHARED_CONF_GROUP)

        self.assertRaises(exception.InvalidParameterValue,
                          hnas_utils.read_cinder_conf, self.fake_conf)
