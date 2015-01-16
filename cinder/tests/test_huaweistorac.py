# Copyright (c) 2014 Huawei Technologies Co., Ltd.
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
Unit Tests for Huawei SDS hypervisor volume drivers.
"""

import mock

import os
import re
import tempfile
from xml.dom.minidom import Document

from oslo_utils import units

from cinder.brick.initiator import connector as brick_connector
from cinder import exception
from cinder import test
from cinder.volume import driver as base_driver
from cinder.volume.drivers.huaweistorhyper import huaweistorac
from cinder.volume.drivers.huaweistorhyper import utils
from cinder.volume.drivers.huaweistorhyper import vbs_client
from cinder.volume import volume_types


test_volume = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
               'size': 2,
               'volume_name': 'vol1',
               'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
               'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
               'provider_auth': None,
               'project_id': 'project',
               'display_name': 'vol1',
               'display_description': 'test volume',
               'volume_type_id': None,
               'host': '',
               'status': 'available',
               'provider_location':
               'volume-21ec7341-9256-497b-97d9-ef48edcf0635'}

test_volume_with_type = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0666',
                         'size': 2,
                         'volume_name': 'vol1',
                         'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                         'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0666',
                         'provider_auth': None,
                         'project_id': 'project',
                         'display_name': 'vol1',
                         'display_description': 'test volume',
                         'volume_type_id': 'gold',
                         'volume_type': {'name': 'gold',
                                         'extra_specs': [{'key': 'raid_level',
                                                          'value': '2'},
                                                         {'key': 'iops',
                                                          'value': '1000'}],
                                         'qos_specs': {}},
                         'host': '',
                         'status': 'available',
                         'provider_location':
                         'volume-21ec7341-9256-497b-97d9-ef48edcf0635'}
volume_type = {'name': 'gold',
               'deleted': False,
               'updated_at': None,
               'extra_specs': {'raid_level': '2',
                               'iops': '1000'},
               'deleted_at': None,
               'id': 'gold'}
volume_type_qos = {'name': 'white',
                   'deleted': False,
                   'updated_at': None,
                   'extra_specs': [{'key':
                                    'raid_level',
                                    'value': '3'},
                                   {'key': 'iops',
                                    'value':
                                    '2000'}],
                   'deleted_at': None,
                   'qos_specs': {'id': 1,
                                 'name': 'qos_specs',
                                 'consumer': 'Consumer',
                                 'specs': {'Qos-high': '10'}},
                   'id': 'white'}
test_volume_with_type_qos = {'name':
                             'volume-21ec7341-9256-497b-97d9-ef48edcf8888',
                             'size': 2,
                             'volume_name': 'vol2',
                             'id': '21ec7341-9256-497b-97d9-ef48edcf8888',
                             'volume_id':
                             '21ec7341-9256-497b-97d9-ef48edcf8888',
                             'provider_auth': None,
                             'project_id': 'project2',
                             'display_name': 'vol2',
                             'display_description': 'test volume',
                             'volume_type_id': 'white',
                             'volume_type': {'name': 'white',
                                             'extra_specs': [{'key':
                                                              'raid_level',
                                                              'value': '3'},
                                                             {'key': 'iops',
                                                              'value':
                                                              '2000'}],
                                             'qos_specs': {'id': 1,
                                                           'name': 'qos_specs',
                                                           'consumer':
                                                           'Consumer',
                                                           'specs':
                                                           {'Qos-high':
                                                            '10'}}},
                             'host': '',
                             'status': 'available',
                             'provider_location':
                             'volume-21ec7341-9256-497b-97d9-ef48edcf8888'}
test_volume_tgt = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0636',
                   'size': 2,
                   'volume_name': 'vol1',
                   'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                   'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                   'provider_auth': None,
                   'project_id': 'project',
                   'display_name': 'vol2',
                   'display_description': 'test volume',
                   'volume_type_id': None,
                   'host': '',
                   'status': 'available',
                   'provider_location':
                   'volume-21ec7341-9256-497b-97d9-ef48edcf0636'}

test_snap = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
             'size': 1,
             'volume_name': 'vol1',
             'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
             'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
             'provider_auth': None,
             'project_id': 'project',
             'display_name': 'vol1',
             'display_description': 'test volume',
             'volume_type_id': None}

test_volume_orders = ['CREATE_VOLUME_REQ',
                      'DELETE_VOLUME_REQ',
                      'CREATE_VOLUME_FROM_SNAPSHOT_REQ',
                      'CLONE_VOLUME_REQ',
                      'EXTEND_VOLUME_REQ',
                      'CREATE_SNAPSHOT_REQ',
                      'DELETE_SNAPSHOT_REQ',
                      'CREATE_FULLVOLUME_FROM_SNAPSHOT_REQ',
                      'CREATE_LUN_MAPPING_REQ',
                      'DELETE_LUN_MAPPING_REQ'
                      ]
test_context = None
test_image_service = None
test_image_meta = None
test_connector = {'ip': '173.30.0.23',
                  'initiator': 'iqn.1993-08.org.debian:01:37b12ad7d46',
                  'host': 'openstack'}


class FakeVbsClient(vbs_client.VbsClient):

    retcode = None
    delete_snapshot_ret = None

    def __init__(self, conf_file):
        super(FakeVbsClient, self).__init__(conf_file)
        self.test_normal_case = True
        self.reqs = []

    def send_message(self, msg):
        return self.__start_send_req(msg)

    def __start_send_req(self, req):
        title = self._get_title(req)
        self.reqs.append(title)
        self._set_ret()
        if self.test_normal_case:
            if title:
                if title in test_volume_orders:
                    return 'retcode=' + FakeVbsClient.retcode
                elif 'QUERY_VOLUME_REQ' == title:
                    return '''retcode=-900079'''
                elif 'QUERY_SNAPSHOT_REQ' == title:
                    return '''retcode=-900079'''
                elif 'QUERY_SINGLE_POOL_CAPABILITY_REQ' == title:
                    return {'total_capacity': '100',
                            'usable_capacity': '90',
                            'tolerance_disk_failure': '20 10',
                            'tolerance_cache_failure': '10 5'}
                elif 'QUERY_POOLS_CAPABILITY_REQ' == title:
                    return 'retcode=0\npool0=[stor_id=16384,'\
                           'total_capacity=100,usable_capacity=97,'\
                           'raid_level=5,iosp=15000,max_iops=15000,'\
                           'min_iops=0]\npool1=[stor_id=16385,'\
                           'total_capacity=100,usable_capacity=97,'\
                           'raid_level=5,iosp=25000,max_iops=25000,'\
                           'min_iops=0]\n'
        else:
            if title:
                return 'retcode=' + FakeVbsClient.retcode

    def _get_title(self, req):
        lines = re.split('\n', req)
        return lines[0][1:-1]

    def _set_ret(self):
        if self.test_normal_case:
            FakeVbsClient.retcode = '0'
        else:
            FakeVbsClient.retcode = '1'


class FakeStorACStorage(huaweistorac.StorACDriver):

    def __init__(self, configuration):
        super(FakeStorACStorage, self).__init__(configuration=configuration)
        self.configuration = configuration

    def do_setup(self, conf_file):
        self._vbs_client = FakeVbsClient(conf_file)
        self._get_default_volume_stats()


class HuaweistoracUtilsTestCase(test.TestCase):

    def setUp(self):
        super(HuaweistoracUtilsTestCase, self).setUp()
        self.request_info = {'vol_name':
                             'volume-3f'}
        self.request_type = 'QUERY_VOLUME_REQ'
        self.serialize_out_fake = '[QUERY_VOLUME_REQ]\nvol_name=volume-3f\n'

    def test_serialize(self):
        serialize_out = utils.serialize(self.request_type,
                                        self.request_info)
        self.assertEqual(self.serialize_out_fake,
                         serialize_out)

    def test_deserialize(self):
        deserialize_out = utils.deserialize('retcode=0\npool0=[stor_id=1638]',
                                            '\n')
        self.assertEqual({'retcode': '0',
                          'pool0': '[stor_id=1638]'},
                         deserialize_out)

    def test_get_valid_ip_list(self):
        iplist = utils.get_valid_ip_list(['', '127.0.0.1', '33', ''])
        self.assertEqual(['127.0.0.1'],
                         iplist)

    def test_generate_dict_from_result(self):
        result = utils.generate_dict_from_result("[stor_id=1638,iops=25]")
        self.assertEqual({'stor_id': '1638',
                          'iops': '25'},
                         result)


class StorACDriverTestCase(test.TestCase):

    def setUp(self):
        super(StorACDriverTestCase, self).setUp()

        self.fake_conf_file = tempfile.mktemp(suffix='.xml')
        self.addCleanup(os.remove, self.fake_conf_file)

        self.create_fake_conf_file()
        self.configuration = mock.Mock()
        self.configuration.use_multipath_for_image_xfer = False
        self.configuration.num_volume_device_scan_tries = 3
        self.configuration.cinder_huawei_sds_conf_file = self.fake_conf_file
        self.driver = FakeStorACStorage(configuration=self.configuration)
        self.driver.do_setup(self.fake_conf_file)
        self.driver._vbs_client.test_normal_case = True

    def create_fake_conf_file(self):
        doc = Document()

        config = doc.createElement('config')
        doc.appendChild(config)

        controller = doc.createElement('controller')
        config.appendChild(controller)

        self._xml_append_child(doc, controller, 'vbs_url', '127.0.0.1,')
        self._xml_append_child(doc, controller, 'vbs_port', '10599')
        self._xml_append_child(doc, controller, 'UserName', 'aa')
        self._xml_append_child(doc, controller, 'UserPassword', 'bb')

        policy = doc.createElement('policy')
        config.appendChild(policy)

        self._xml_append_child(doc, policy, 'force_provision_size', '2')
        self._xml_append_child(doc, policy, 'iops', '200')
        self._xml_append_child(doc, policy, 'cache_size', '2')
        self._xml_append_child(doc, policy, 'repicate_num', '2')
        self._xml_append_child(doc, policy, 'repicate_tolerant_num', '0')
        self._xml_append_child(doc, policy, 'encrypt_algorithm', '0')
        self._xml_append_child(doc, policy, 'consistency', '1')
        self._xml_append_child(doc, policy, 'compress_algorithm', '0')
        self._xml_append_child(doc, policy, 'backup_cycle', '0')
        self._xml_append_child(doc, policy, 'stor_space_level', '1')
        self._xml_append_child(doc, policy, 'QoS_support', '1')
        self._xml_append_child(doc, policy, 'tolerance_disk_failure', '0')
        self._xml_append_child(doc, policy, 'tolerance_cache_failure', '1')

        capability = doc.createElement('capability')
        config.appendChild(capability)

        self._xml_append_child(doc, capability, 'reserved_percentage', '0')
        self._xml_append_child(doc, capability, 'deduplication', '0')
        self._xml_append_child(doc, capability, 'snapshot', '1')
        self._xml_append_child(doc, capability, 'backup', '0')

        pools = doc.createElement('pools')
        config.appendChild(pools)
        pool1 = doc.createElement('pool')
        pool2 = doc.createElement('pool')
        pools.appendChild(pool1)
        pools.appendChild(pool2)

        self._xml_append_child(doc, pool1, 'pool_id', 'xxx1')
        self._xml_append_child(doc, pool1, 'iops', '200')

        newefile = open(self.fake_conf_file, 'w')
        newefile.write(doc.toprettyxml(indent=''))
        newefile.close()

    def _xml_append_child(self, doc, parent, child_name, child_text):

        child = doc.createElement(child_name)
        child_node_text = doc.createTextNode(child_text)
        child.appendChild(child_node_text)
        parent.appendChild(child)

    def test_create_volume_success(self):
        retval = self.driver.create_volume(test_volume)
        self.assertEqual("volume-21ec7341-9256-497b-97d9-ef48edcf0635",
                         retval['provider_location'])

    def test_create_volume_with_volume_type(self):
        retval = self.driver.create_volume(test_volume_with_type)
        self.assertEqual("volume-21ec7341-9256-497b-97d9-ef48edcf0666",
                         retval['provider_location'])

    def test_create_volume_from_snapshot_success(self):
        retval = self.driver. \
            create_volume_from_snapshot(test_volume, test_snap)
        self.assertEqual("volume-21ec7341-9256-497b-97d9-ef48edcf0635",
                         retval['provider_location'])

    @mock.patch.object(base_driver.VolumeDriver,
                       'copy_volume_data')
    def test_create_cloned_volume_success(self, mock_copy_volume_data):
        mock_copy_volume_data.return_value = None
        retval = self.driver.\
            create_cloned_volume(test_volume_tgt, test_volume)
        self.assertEqual("volume-21ec7341-9256-497b-97d9-ef48edcf0636",
                         retval['provider_location'])

    def test_delete_volume_success(self):
        self.driver.delete_volume(test_volume)
        self.assertEqual('0', FakeVbsClient.retcode)

    def test_extend_volume_success(self):
        new_size = 4
        self.driver.extend_volume(test_volume, new_size)
        self.assertEqual('0', FakeVbsClient.retcode)

    def test_migrate_volume_success(self):
        pass

    def test_get_volume_stats(self):
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(0, stats['free_capacity_gb'])
        self.assertEqual(0, stats['total_capacity_gb'])
        self.assertEqual('0', stats['reserved_percentage'])

    def test_create_snapshot_success(self):
        retval = self.driver.create_snapshot(test_snap)
        self.assertEqual('volume-21ec7341-9256-497b-97d9-ef48edcf0635',
                         retval['provider_location'])

    @mock.patch.object(brick_connector, 'get_connector_properties')
    @mock.patch.object(brick_connector.HuaweiStorHyperConnector,
                       'is_volume_connected')
    @mock.patch.object(brick_connector.HuaweiStorHyperConnector,
                       'connect_volume')
    @mock.patch.object(brick_connector.HuaweiStorHyperConnector,
                       'disconnect_volume')
    @mock.patch.object(base_driver.VolumeDriver,
                       '_attach_volume')
    @mock.patch.object(base_driver.VolumeDriver,
                       '_detach_volume')
    def test_delete_snapshot_success(self, mock_disconnect_volume,
                                     mock_connect_volume,
                                     mock_is_volume_connected,
                                     mock__attach_volume,
                                     mock__detach_volume,
                                     mock__get_connector_properties):
            mock_disconnect_volume.return_value = None
            mock_connect_volume.return_value = {'type': 'block',
                                                'path': '/dev/null'}

            mock_is_volume_connected.return_value = True
            mock__attach_volume.return_value = None
            mock__detach_volume.return_value = None
            mock__get_connector_properties.return_value = {}

            self.driver.delete_snapshot(test_snap)
            self.assertEqual('0', FakeVbsClient.retcode)

            mock_is_volume_connected.return_value = False
            self.driver.delete_snapshot(test_snap)
            self.assertEqual('0', FakeVbsClient.retcode)

    @mock.patch.object(base_driver.VolumeDriver,
                       'copy_volume_to_image')
    def test_copy_volume_to_image_success(self,
                                          mock_copy_volume_to_image):
        mock_copy_volume_to_image.return_value = None
        self.driver.copy_volume_to_image(test_context,
                                         test_volume,
                                         test_image_service,
                                         test_image_meta)

        expected_reqs = ['CREATE_SNAPSHOT_REQ',
                         'CREATE_VOLUME_FROM_SNAPSHOT_REQ',
                         'DELETE_VOLUME_REQ',
                         'QUERY_VOLUME_REQ']
        self.assertEqual(expected_reqs, self.driver._vbs_client.reqs)

    @mock.patch.object(base_driver.VolumeDriver,
                       'copy_volume_data')
    def test_copy_volume_data_success(self,
                                      mock_copy_volume_data):
        mock_copy_volume_data.return_value = None

        self.driver.copy_volume_data(test_context,
                                     test_volume,
                                     test_volume_tgt,
                                     remote=None)

        expected_reqs = ['CREATE_SNAPSHOT_REQ',
                         'CREATE_VOLUME_FROM_SNAPSHOT_REQ',
                         'DELETE_VOLUME_REQ',
                         'QUERY_VOLUME_REQ']
        self.assertEqual(expected_reqs, self.driver._vbs_client.reqs)

    def test_initialize_connection_success(self):
        retval = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual('HUAWEISDSHYPERVISOR', retval['driver_volume_type'])

    def test_terminate_connection_success(self):
        pass

    def test_create_volume_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_volume, test_volume)

    def test_create_volume_from_snapshot_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_volume_from_snapshot,
                          test_volume, test_snap)

    def test_create_cloned_volume_fail(self):
        self.driver._vbs_client.test_normal_case = False
        test_volume_tmp = dict(test_volume)
        test_volume_tmp.pop('provider_location')
        self.assertRaises(exception.CinderException,
                          self.driver.create_cloned_volume,
                          test_volume_tgt, test_volume_tmp)

    def test_delete_volume_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver.delete_volume, test_volume)

    def test_extend_volume_fail(self):
        new_size = 4
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver.extend_volume, test_volume, new_size)

    def create_snapshot_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_snapshot, test_snap)

    def delete_snapshot_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver.delete_snapshot, test_snap)

    def test_copy_volume_to_image_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver.copy_volume_to_image,
                          test_context,
                          test_volume,
                          test_image_service,
                          test_image_meta)

    def test_copy_volume_data_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver.copy_volume_data,
                          test_context,
                          test_volume,
                          test_volume_tgt,
                          remote=None)

    def test_terminate_connection_fail(self):
        pass

    @mock.patch.object(brick_connector.HuaweiStorHyperConnector,
                       'is_volume_connected')
    def test__is_volume_attached(self, mock_is_volume_connected):
            mock_is_volume_connected.return_value = True
            ret = self.driver._is_volume_attached('21ec7341')
            self.assertEqual(True, ret)

            mock_is_volume_connected.return_value = False
            ret = self.driver._is_volume_attached('21ec7341')
            self.assertEqual(False, ret)

    def test__create_target_volume_success(self):
        test_volume_name_tgt = test_volume_tgt['name']
        retval = self.driver._create_target_volume(test_volume,
                                                   test_volume_name_tgt,
                                                   test_volume_tgt)
        self.assertEqual("volume-21ec7341-9256-497b-97d9-ef48edcf0636",
                         retval['vol_name'])

    def test__create_linked_volume_from_snap_success(self):
        tgt_vol_name = test_volume['name']
        src_snapshot_name = test_snap['name']
        self.driver._create_linked_volume_from_snap(src_snapshot_name,
                                                    tgt_vol_name,
                                                    test_volume['size'])
        expected_reqs = ['CREATE_VOLUME_FROM_SNAPSHOT_REQ']
        self.assertEqual(expected_reqs, self.driver._vbs_client.reqs)

    def test__get_all_pool_capacity_success(self):
        retval = self.driver._get_all_pool_capacity()
        stats = retval['16384']
        self.assertEqual(97, stats['free_capacity_gb'])
        self.assertEqual(100, stats['total_capacity_gb'])
        self.assertEqual(0, stats['reserved_percentage'])

    def test__delete_snapshot_success(self):
        self.driver._delete_snapshot(test_snap)
        expected_reqs = ['DELETE_SNAPSHOT_REQ',
                         'QUERY_SNAPSHOT_REQ']
        self.assertEqual(expected_reqs, self.driver._vbs_client.reqs)

    def test__create_default_volume_stats_success(self):
        retval = self.driver._create_default_volume_stats()
        self.assertEqual('Huawei', retval['vendor_name'])

    def test__get_default_volume_stats_success(self):
        retval = self.driver._get_default_volume_stats()
        self.assertEqual('0', retval['reserved_percentage'])
        self.assertEqual('0', retval['deduplication'])
        self.assertEqual('1', retval['snapshot'])
        self.assertEqual('0', retval['backup'])

    def test__query_volume_success(self):
        retval = self.driver._query_volume(test_volume['name'])
        self.assertEqual('-900079', retval['retcode'])

    def test__is_volume_exist_success(self):
        volume_name = test_volume['name']
        retval = self.driver._is_volume_exist(volume_name)
        self.assertEqual(False, retval)

    def test__create_target_volume_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver._create_target_volume,
                          test_volume,
                          test_volume_tgt['volume_name'],
                          test_volume_tgt)

    def test__create_linked_volume_from_snap_fail(self):
        tgt_vol_name = test_volume['name']
        src_snapshot_name = test_snap['name']
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver._create_linked_volume_from_snap,
                          src_snapshot_name,
                          tgt_vol_name,
                          test_volume['size'])

    def test__get_volume_stats_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_volume_stats)

    def test__get_all_pool_capacity_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver._get_all_pool_capacity)

    def test__delete_snapshot_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.CinderException,
                          self.driver._delete_snapshot,
                          test_snap)

    def test__query_volume_fail(self):
        self.driver._vbs_client.test_normal_case = False
        retval = self.driver._query_volume(test_volume['name'])
        self.assertEqual('1', retval['retcode'])

    def test__is_volume_exist_fail(self):
        volume_name = test_volume['name']
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._is_volume_exist,
                          volume_name)

    def test_size_translate_success(self):
        exp_size = '%s' % (2 * units.Ki)
        vol_size = self.driver._size_translate(2)
        self.assertEqual(exp_size, vol_size)

    def test_update_volume_info_from_volume_extra_specs_success(self):
        volume_info = self.driver._create_storage_info('volume_info')
        extra_specs = volume_type_qos.get('extra_specs')
        self.driver._update_volume_info_from_volume_extra_specs(volume_info,
                                                                extra_specs)
        self.assertEqual('2000', volume_info['iops'])

    def test_update_volume_info_from_volume_success(self):
        volume_info = self.driver._create_storage_info('volume_info')
        self.driver._update_volume_info_from_volume(volume_info,
                                                    test_volume_with_type_qos)
        self.assertEqual('2000', volume_info['iops'])
        self.assertEqual("3", volume_info['IOPRIORITY'])

    def test_update_volume_info_from_qos_specs_success(self):
        volume_info = self.driver._create_storage_info('volume_info')
        self.driver._update_volume_info_from_qos_specs(volume_info,
                                                       volume_type_qos)
        self.assertEqual("3", volume_info['IOPRIORITY'])

    @mock.patch.object(volume_types, 'get_volume_type')
    @mock.patch.object(volume_types, 'get_volume_type_qos_specs')
    def test_update_volinfo_from_type_success(self,
                                              _mock_get_volume_types,
                                              _mock_get_volume_type_qos_specs):
        volume_info = self.driver._create_storage_info('volume_info')
        _mock_get_volume_types.return_value = volume_type_qos
        _mock_get_volume_type_qos_specs.return_value = {'qos_specs':
                                                        {'id': 1,
                                                         'name': 'qos_specs',
                                                         'consumer':
                                                         'Consumer',
                                                         'specs': {'Qos-high':
                                                                   '10'}}}
        self.driver._update_volume_info_from_volume_type(volume_info, 'white')
        self.assertEqual('100', volume_info['iops'])
        self.assertEqual("3", volume_info['IOPRIORITY'])

    def test_create_storage_info_success(self):
        volume_info = self.driver._create_storage_info('volume_info')
        self.assertEqual('', volume_info['vol_name'])
        self.assertEqual('', volume_info['vol_size'])
        self.assertEqual('0', volume_info['pool_id'])
        self.assertEqual('0', volume_info['thin_flag'])
        self.assertEqual('0', volume_info['reserved'])
        self.assertEqual('0', volume_info['volume_space_reserved'])
        self.assertEqual('0', volume_info['force_provision_size'])
        self.assertEqual('100', volume_info['iops'])
        self.assertEqual('100', volume_info['max_iops'])
        self.assertEqual('0', volume_info['min_iops'])
        self.assertEqual('0', volume_info['cache_size'])
        self.assertEqual('1', volume_info['repicate_num'])
        self.assertEqual('1', volume_info['repicate_tolerant_num'])
        self.assertEqual('0', volume_info['encrypt_algorithm'])
        self.assertEqual('0', volume_info['consistency'])
        self.assertEqual('1', volume_info['stor_space_level'])
        self.assertEqual('0', volume_info['compress_algorithm'])
        self.assertEqual('0', volume_info['deduplication'])
        self.assertEqual('0', volume_info['snapshot'])
        self.assertEqual('0', volume_info['backup_cycle'])
        self.assertEqual('0', volume_info['tolerance_disk_failure'])
        self.assertEqual('1', volume_info['tolerance_cache_failure'])

    def test_is_snapshot_exist_success(self):
        result = self.driver._is_snapshot_exist('snap-21ec7341')
        self.assertEqual(False, result)

    def test_get_volume_pool_id_success(self):
        result = self.driver._get_volume_pool_id('host#cloud')
        self.assertEqual('cloud', result)

    def test_send_request_success(self):
        volume_info = self.driver._create_storage_info('volume_info')
        volume_info['vol_name'] = 'test_vol'
        volume_info['vol_size'] = 2
        result = self.driver._send_request('CREATE_VOLUME_REQ',
                                           volume_info,
                                           'create volume error.')
        self.assertEqual('0', result['retcode'])

    def test_update_default_volume_stats_from_config_success(self):
        default_stats = {'pools_id': []}
        self.driver.\
            _update_default_volume_stats_from_config(default_stats,
                                                     self.fake_conf_file)
        self.assertEqual(True, default_stats['QoS_support'])
        self.assertEqual('200', default_stats['iops'])
        self.assertEqual('2', default_stats['cache_size'])
        self.assertEqual('2', default_stats['repicate_num'])
        self.assertEqual('0', default_stats['repicate_tolerant_num'])
        self.assertEqual('0', default_stats['encrypt_algorithm'])
        self.assertEqual('1', default_stats['consistency'])
        self.assertEqual('0', default_stats['compress_algorithm'])
        self.assertEqual('0', default_stats['backup_cycle'])
        self.assertEqual('1', default_stats['stor_space_level'])
        self.assertEqual('0', default_stats['tolerance_disk_failure'])
        self.assertEqual('1', default_stats['tolerance_cache_failure'])
        self.assertEqual('0', default_stats['reserved_percentage'])
        self.assertEqual('0', default_stats['deduplication'])
        self.assertEqual('1', default_stats['snapshot'])
        self.assertEqual('0', default_stats['backup'])

    def test_update_all_pool_capacity_from_policy_success(self):
        all_pool_policy = {'xxx1': {'total_capacity_gb': 100,
                                    'free_capacity_gb': 80,
                                    'iops': 2000}}
        all_pool_capacity = {'xxx1': {'total_capacity_gb': 80,
                                      'free_capacity_gb': 60,
                                      'iops': 1000}}
        self.driver._update_all_pool_capacity_from_policy(all_pool_capacity,
                                                          all_pool_policy)
        self.assertEqual(100, all_pool_capacity['xxx1']['total_capacity_gb'])
        self.assertEqual(80, all_pool_capacity['xxx1']['free_capacity_gb'])
        self.assertEqual(2000, all_pool_capacity['xxx1']['iops'])

    def test_extract_pool_policy_mapping_from_config_success(self):
        pools = self.driver.\
            _extract_pool_policy_mapping_from_config(self.fake_conf_file)
        self.assertEqual('200', pools['xxx1']['iops'])

    def test_is_snapshot_exist_fail(self):
        self.driver._vbs_client.test_normal_case = False
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._is_snapshot_exist,
                          'test_snap_not_exist')

    def test_get_volume_pool_id_default(self):
        pool_info = self.driver._get_volume_pool_id('host_test')
        self.assertEqual('xxx1', pool_info)

    def test_create_storage_info_fail1(self):
        volume_info = self.driver._create_storage_info('')
        self.assertEqual(None, volume_info)

    def test_create_storage_info_fail2(self):
        volume_info = self.driver._create_storage_info('volume')
        self.assertEqual(None, volume_info)

    def test__query_volume_notexist(self):
        retval = self.driver._query_volume('volume-2b73118c')
        self.assertEqual(retval['retcode'], '-900079')

    def test__is_volume_exist_notexist(self):
        volume_name = 'volume-2b73118c-2c6d-4f2c-a00a-9c27791ee814'
        retval = self.driver._is_volume_exist(volume_name)
        self.assertEqual(False, retval)
