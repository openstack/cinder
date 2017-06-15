# Copyright (c) 2013 - 2016 Huawei Technologies Co., Ltd.
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
Unit Tests for Huawei FusionStorage drivers.
"""

import mock
from oslo_config import cfg
from oslo_service import loopingcall

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.tests.unit import fake_constants
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume import configuration as conf
from cinder.volume.drivers.fusionstorage import dsware
from cinder.volume.drivers.fusionstorage import fspythonapi


test_volume = {'name': 'test_vol1',
               'size': 4,
               'volume_metadata': '',
               'host': 'host01@dsware',
               'instance_uuid': None,
               'provider_id': '127.0.0.1',
               'id': fake_constants.VOLUME_ID}

test_src_volume = {'name': 'test_vol2',
                   'size': 4,
                   'status': 'available'}

test_snapshot = {
    'name': 'test_snapshot1',
    'volume_id': fake_constants.VOLUME_ID,
    'volume_size': '4'}


class FakeDSWAREDriver(dsware.DSWAREDriver):
    def __init__(self):
        configuration = conf.Configuration(
            [
                cfg.StrOpt('fake'),
            ],
            None
        )
        super(FakeDSWAREDriver, self).__init__(configuration=configuration)
        self.dsware_client = fspythonapi.FSPythonApi()
        self.manage_ip = '127.0.0.1'
        self.pool_type = '1'


class DSwareDriverTestCase(test.TestCase):
    def setUp(self):
        super(DSwareDriverTestCase, self).setUp()
        self.driver = FakeDSWAREDriver()
        self.context = context.get_admin_context()
        self.volume = fake_volume.fake_volume_obj(context=self.context,
                                                  **test_volume)
        self.scr_volume = fake_volume.fake_volume_obj(context=self.context,
                                                      **test_src_volume)
        self.snapshot = fake_snapshot.fake_snapshot_obj(context=self.context,
                                                        **test_snapshot)

    def test_private_get_dsware_manage_ip(self):
        retval = self.driver._get_dsware_manage_ip(self.volume)
        self.assertEqual('127.0.0.1', retval)

        test_volume_fail_dict = {'name': 'test_vol',
                                 'size': 4,
                                 'volume_metadata': '',
                                 'host': 'host01@dsware',
                                 'provider_id': None}
        test_volume_fail = fake_volume.fake_volume_obj(context=self.context,
                                                       **test_volume_fail_dict)
        self.assertRaises(exception.CinderException,
                          self.driver._get_dsware_manage_ip,
                          test_volume_fail)

    def test_private_get_poolid_from_host(self):
        retval = self.driver._get_poolid_from_host(
            'abc@fusionstorage_sas2copy#0')
        self.assertEqual('0', retval)

        retval = self.driver._get_poolid_from_host(
            'abc@fusionstorage_sas2copy@0')
        self.assertEqual(self.driver.pool_type, retval)

        retval = self.driver._get_poolid_from_host(None)
        self.assertEqual(self.driver.pool_type, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'create_volume')
    @mock.patch.object(fspythonapi.FSPythonApi, 'query_dsware_version')
    @mock.patch.object(dsware.DSWAREDriver, '_get_poolid_from_host')
    def test_private_create_volume_old_version(self, mock_get_poolid,
                                               mock_query_dsware,
                                               mock_create_volume):
        # query_dsware_version return 1, old version
        mock_query_dsware.return_value = 1
        mock_create_volume.return_value = 0
        self.driver._create_volume(self.volume.name,
                                   self.volume.size,
                                   True,
                                   'abc@fusionstorage_sas2copy')
        mock_create_volume.assert_called_with(self.volume.name, 0,
                                              self.volume.size, 1)

        self.driver._create_volume(self.volume.name,
                                   self.volume.size,
                                   False,
                                   'abc@fusionstorage_sas2copy')
        mock_create_volume.assert_called_with(self.volume.name, 0,
                                              self.volume.size, 0)

    @mock.patch.object(fspythonapi.FSPythonApi, 'create_volume')
    @mock.patch.object(fspythonapi.FSPythonApi, 'query_dsware_version')
    @mock.patch.object(dsware.DSWAREDriver, '_get_poolid_from_host')
    def test_private_create_volume_new_version(self, mock_get_poolid,
                                               mock_query_dsware,
                                               mock_create_volume):
        # query_dsware_version return 0, new version
        mock_query_dsware.return_value = 0
        mock_get_poolid.return_value = 0
        mock_create_volume.return_value = 0
        self.driver._create_volume(self.volume.name,
                                   self.volume.size,
                                   True,
                                   'abcE@fusionstorage_sas2copy#0')
        mock_create_volume.assert_called_with(self.volume.name, 0,
                                              self.volume.size, 1)

        self.driver._create_volume(self.volume.name,
                                   self.volume.size,
                                   False,
                                   'abc@fusionstorage_sas2copy#0')
        mock_create_volume.assert_called_with(self.volume.name, 0,
                                              self.volume.size, 0)

        mock_query_dsware.return_value = 0
        mock_get_poolid.return_value = 1
        mock_create_volume.return_value = 0
        self.driver._create_volume(self.volume.name,
                                   self.volume.size,
                                   True,
                                   'abc@fusionstorage_sas2copy#1')
        mock_create_volume.assert_called_with(self.volume.name, 1,
                                              self.volume.size, 1)

        self.driver._create_volume(self.volume.name,
                                   self.volume.size,
                                   False,
                                   'abc@fusionstorage_sas2copy#1')
        mock_create_volume.assert_called_with(self.volume.name, 1,
                                              self.volume.size, 0)

    @mock.patch.object(fspythonapi.FSPythonApi, 'create_volume')
    @mock.patch.object(fspythonapi.FSPythonApi, 'query_dsware_version')
    @mock.patch.object(dsware.DSWAREDriver, '_get_poolid_from_host')
    def test_private_create_volume_query_version_fail(self, mock_get_poolid,
                                                      mock_query_dsware,
                                                      mock_create_volume):
        # query_dsware_version return 500015, query dsware version failed!
        mock_query_dsware.return_value = 500015
        self.assertRaises(exception.CinderException,
                          self.driver._create_volume,
                          self.volume.name,
                          self.volume.size,
                          True,
                          'abc@fusionstorage_sas2copy#0')
        self.assertRaises(exception.CinderException,
                          self.driver._create_volume,
                          self.volume.name,
                          self.volume.size,
                          False,
                          'abc@fusionstorage_sas2copy#0')

    @mock.patch.object(fspythonapi.FSPythonApi, 'create_volume')
    @mock.patch.object(fspythonapi.FSPythonApi, 'query_dsware_version')
    @mock.patch.object(dsware.DSWAREDriver, '_get_poolid_from_host')
    def test_private_create_volume_fail(self, mock_get_poolid,
                                        mock_query_dsware,
                                        mock_create_volume):
        mock_query_dsware.return_value = 1
        # create_volume return 1, create volume failed
        mock_create_volume.return_value = 1
        self.assertRaises(exception.CinderException,
                          self.driver._create_volume,
                          self.volume.name,
                          self.volume.size,
                          True,
                          'abc@fusionstorage_sas2copy#0')
        self.assertRaises(exception.CinderException,
                          self.driver._create_volume,
                          self.volume.name,
                          self.volume.size,
                          False,
                          'abc@fusionstorage_sas2copy#0')

    @mock.patch.object(dsware.DSWAREDriver, '_create_volume')
    @mock.patch.object(fspythonapi.FSPythonApi, 'get_manage_ip')
    def test_create_volume(self, mock_get_manage_ip, mock_create_volume):
        # success
        mock_get_manage_ip.return_value = self.driver.manage_ip
        retval = self.driver.create_volume(self.volume)
        self.assertEqual({"provider_id": self.driver.manage_ip},
                         retval)

        # failure
        mock_create_volume.side_effect = exception.CinderException(
            'DSWARE Create Volume failed!')

        self.assertRaises(exception.CinderException,
                          self.driver.create_volume,
                          self.volume)

    @mock.patch.object(fspythonapi.FSPythonApi, 'create_volume_from_snap')
    def test_private_create_volume_from_snap(self, mock_create_volume):
        mock_create_volume.side_effect = [0, 1]
        self.driver._create_volume_from_snap(self.volume.name,
                                             self.volume.size,
                                             self.snapshot.name)
        # failure
        self.assertRaises(exception.CinderException,
                          self.driver._create_volume_from_snap,
                          self.volume.name, self.volume.size,
                          self.snapshot.name)

    @mock.patch.object(fspythonapi.FSPythonApi, 'extend_volume')
    def test_extend_volume(self, mock_extend_volume):
        mock_extend_volume.return_value = 0
        self.driver.extend_volume(self.volume, 5)

        mock_extend_volume.return_value = 0
        self.assertRaises(exception.CinderException,
                          self.driver.extend_volume,
                          self.volume,
                          3)

        mock_extend_volume.return_value = 1
        self.assertRaises(exception.CinderException,
                          self.driver.extend_volume,
                          self.volume,
                          5)

    @mock.patch.object(dsware.DSWAREDriver, '_create_volume_from_snap')
    @mock.patch.object(fspythonapi.FSPythonApi, 'get_manage_ip')
    def test_create_volume_from_snap(self, mock_manage_ip, mock_create_vol):
        # success
        mock_manage_ip.return_value = self.driver.manage_ip
        retval = self.driver.create_volume_from_snapshot(self.volume,
                                                         self.snapshot)
        self.assertEqual({"provider_id": self.driver.manage_ip},
                         retval)

        # failure
        mock_create_vol.side_effect = exception.CinderException(
            'DSWARE:create volume from snap failed')
        self.assertRaises(exception.CinderException,
                          self.driver.create_volume_from_snapshot,
                          self.volume, self.snapshot)

    @mock.patch.object(fspythonapi.FSPythonApi, 'create_volume_from_volume')
    @mock.patch.object(fspythonapi.FSPythonApi, 'get_manage_ip')
    @mock.patch.object(dsware.DSWAREDriver,
                       '_wait_for_create_cloned_volume_finish_timer')
    def test_create_cloned_volume(self, mock_wait_finish,
                                  mock_get_manage_ip, mock_create_volume):
        # success
        mock_create_volume.return_value = None
        mock_get_manage_ip.return_value = self.driver.manage_ip
        mock_wait_finish.return_value = True
        retval = self.driver.create_cloned_volume(self.volume, self.scr_volume)
        self.assertEqual({"provider_id": "127.0.0.1"}, retval)

        # failure:create exception
        mock_create_volume.return_value = 500015
        self.assertRaises(exception.CinderException,
                          self.driver.create_cloned_volume,
                          self.volume, self.scr_volume)
        # failure:wait exception
        mock_create_volume.return_value = None
        mock_wait_finish.return_value = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_cloned_volume,
                          self.volume, self.scr_volume)

    @mock.patch.object(fspythonapi.FSPythonApi, 'query_volume')
    def test_private_check_create_cloned_volume_finish(self,
                                                       mock_query_volume):
        query_result_done = {'result': 0, 'vol_name': 'vol1',
                             'father_name': 'vol1_father', 'status': '0',
                             'vol_size': '1024', 'real_size': '1024',
                             'pool_id': 'pool1', 'create_time': '01/01/2015'}

        query_result_doing = {'result': 0, 'vol_name': 'vol1',
                              'father_name': 'vol1_father', 'status': '6',
                              'vol_size': '1024', 'real_size': '1024',
                              'pool_id': 'pool1', 'create_time': '01/01/2015'}

        mock_query_volume.side_effect = [
            query_result_done, query_result_doing, query_result_doing]

        # success
        self.assertRaises(loopingcall.LoopingCallDone,
                          self.driver._check_create_cloned_volume_finish,
                          self.volume.name)

        # in the process of creating volume
        self.driver.count = self.driver.configuration.clone_volume_timeout - 1
        self.driver._check_create_cloned_volume_finish(self.volume.name)
        self.assertEqual(self.driver.configuration.clone_volume_timeout,
                         self.driver.count)

        # timeout
        self.driver.count = self.driver.configuration.clone_volume_timeout
        self.assertRaises(loopingcall.LoopingCallDone,
                          self.driver._check_create_cloned_volume_finish,
                          self.volume.name)

    @mock.patch.object(dsware.DSWAREDriver,
                       '_check_create_cloned_volume_finish')
    def test_private_wait_for_create_cloned_volume_finish_timer(self,
                                                                mock_check):
        mock_check.side_effect = [loopingcall.LoopingCallDone(retvalue=True),
                                  loopingcall.LoopingCallDone(retvalue=False)]
        retval = self.driver._wait_for_create_cloned_volume_finish_timer(
            self.volume.name)
        self.assertTrue(retval)

        retval = self.driver._wait_for_create_cloned_volume_finish_timer(
            self.volume.name)
        self.assertFalse(retval)

    def test_private_analyse_output(self):
        out = 'ret_code=10\nret_desc=test\ndev_addr=/sda\n'
        retval = self.driver._analyse_output(out)
        self.assertEqual({'dev_addr': '/sda',
                          'ret_desc': 'test', 'ret_code': '10'},
                         retval)

        out = 'abcdefg'
        retval = self.driver._analyse_output(out)
        self.assertEqual({}, retval)

    def test_private_attach_volume(self):
        success = ['ret_code=0\nret_desc=success\ndev_addr=/dev/sdb\n', '']
        failure = ['ret_code=50510011\nret_desc=failed\ndev_addr=/dev/sdb\n',
                   '']
        mock_execute = self.mock_object(self.driver, '_execute')
        mock_execute.side_effect = [success, failure]
        # attached successful
        retval = self.driver._attach_volume(self.volume.name,
                                            self.driver.manage_ip)
        self.assertEqual({'dev_addr': '/dev/sdb',
                          'ret_desc': 'success', 'ret_code': '0'},
                         retval)
        # attached failure
        retval = self.driver._attach_volume(self.volume.name,
                                            self.driver.manage_ip)
        self.assertEqual({'dev_addr': '/dev/sdb',
                          'ret_desc': 'failed', 'ret_code': '50510011'},
                         retval)

    def test_private_detach_volume(self):
        success = ['ret_code=0\nret_desc=success\ndev_addr=/dev/sdb\n', '']
        failure = ['ret_code=50510011\nret_desc=failed\ndev_addr=/dev/sdb\n',
                   '']
        mock_execute = self.mock_object(self.driver, '_execute')
        mock_execute.side_effect = [success, failure]
        # detached successful
        retval = self.driver._detach_volume(self.volume.name,
                                            self.driver.manage_ip)
        self.assertEqual({'dev_addr': '/dev/sdb',
                          'ret_desc': 'success', 'ret_code': '0'},
                         retval)
        # detached failure
        retval = self.driver._detach_volume(self.volume.name,
                                            self.driver.manage_ip)
        self.assertEqual({'dev_addr': '/dev/sdb',
                          'ret_desc': 'failed',
                          'ret_code': '50510011'},
                         retval)

    def test_private_query_volume_attach(self):
        success = ['ret_code=0\nret_desc=success\ndev_addr=/dev/sdb\n', '']
        failure = ['ret_code=50510011\nret_desc=failed\ndev_addr=/dev/sdb\n',
                   '']
        mock_execute = self.mock_object(self.driver, '_execute')
        mock_execute.side_effect = [success, failure]
        # query successful
        retval = self.driver._query_volume_attach(self.volume.name,
                                                  self.driver.manage_ip)
        self.assertEqual({'dev_addr': '/dev/sdb',
                          'ret_desc': 'success',
                          'ret_code': '0'},
                         retval)
        # query failure
        retval = self.driver._query_volume_attach(self.volume.name,
                                                  self.driver.manage_ip)
        self.assertEqual({'dev_addr': '/dev/sdb',
                          'ret_desc': 'failed',
                          'ret_code': '50510011'},
                         retval)

    @mock.patch.object(dsware.DSWAREDriver, '_get_dsware_manage_ip')
    @mock.patch.object(dsware.DSWAREDriver, '_attach_volume')
    @mock.patch.object(image_utils, 'fetch_to_raw')
    @mock.patch.object(dsware.DSWAREDriver, '_detach_volume')
    def test_copy_image_to_volume(self, mock_detach, mock_fetch,
                                  mock_attach, mock_get_manage_ip):
        success = {'ret_code': '0',
                   'ret_desc': 'success',
                   'dev_addr': '/dev/sdb'}
        failure = {'ret_code': '50510011',
                   'ret_desc': 'failed',
                   'dev_addr': '/dev/sdb'}
        context = ''
        image_service = ''
        image_id = ''
        mock_get_manage_ip.return_value = '127.0.0.1'
        mock_attach.side_effect = [success, failure, success]
        mock_detach.side_effect = [success, failure, failure]

        # success
        self.driver.copy_image_to_volume(context, self.volume, image_service,
                                         image_id)

        # failure - attach failure
        self.assertRaises(exception.CinderException,
                          self.driver.copy_image_to_volume,
                          context, self.volume, image_service, image_id)

        # failure - detach failure
        self.assertRaises(exception.CinderException,
                          self.driver.copy_image_to_volume,
                          context, self.volume, image_service, image_id)

    @mock.patch.object(dsware.DSWAREDriver, '_get_dsware_manage_ip')
    @mock.patch.object(dsware.DSWAREDriver, '_attach_volume')
    @mock.patch.object(dsware.DSWAREDriver, '_query_volume_attach')
    @mock.patch.object(image_utils, 'upload_volume')
    @mock.patch.object(dsware.DSWAREDriver, '_detach_volume')
    def test_copy_volume_to_image_success(self, mock_detach, mock_upload,
                                          mock_query, mock_attach,
                                          mock_get_manage_ip):
        success = {'ret_code': '0',
                   'ret_desc': 'success',
                   'dev_addr': '/dev/sdb'}
        already_attached = {'ret_code': '50151401',
                            'ret_desc': 'already_attached',
                            'dev_addr': '/dev/sdb'}
        context = ''
        image_service = ''
        image_meta = ''

        mock_get_manage_ip.return_value = '127.0.0.1'
        mock_attach.return_value = success
        mock_detach.return_value = success
        self.driver.copy_volume_to_image(context, self.volume, image_service,
                                         image_meta)
        mock_upload.assert_called_with('', '', '', '/dev/sdb')

        mock_attach.return_value = already_attached
        mock_query.return_value = success
        mock_detach.return_value = success
        self.driver.copy_volume_to_image(context, self.volume, image_service,
                                         image_meta)
        mock_upload.assert_called_with('', '', '', '/dev/sdb')

    @mock.patch.object(dsware.DSWAREDriver, '_get_dsware_manage_ip')
    @mock.patch.object(dsware.DSWAREDriver, '_attach_volume')
    @mock.patch.object(dsware.DSWAREDriver, '_query_volume_attach')
    @mock.patch.object(image_utils, 'upload_volume')
    @mock.patch.object(dsware.DSWAREDriver, '_detach_volume')
    def test_copy_volume_to_image_attach_fail(self, mock_detach, mock_upload,
                                              mock_query, mock_attach,
                                              mock_get_manage_ip):
        failure = {'ret_code': '50510011',
                   'ret_desc': 'failed',
                   'dev_addr': '/dev/sdb'}
        context = ''
        image_service = ''
        image_meta = ''

        mock_get_manage_ip.return_value = '127.0.0.1'
        mock_attach.return_value = failure
        self.assertRaises(exception.CinderException,
                          self.driver.copy_volume_to_image,
                          context, self.volume, image_service, image_meta)
        mock_attach.return_value = None
        self.assertRaises(exception.CinderException,
                          self.driver.copy_volume_to_image,
                          context, self.volume, image_service, image_meta)

    @mock.patch.object(dsware.DSWAREDriver, '_get_dsware_manage_ip')
    @mock.patch.object(dsware.DSWAREDriver, '_attach_volume')
    @mock.patch.object(dsware.DSWAREDriver, '_query_volume_attach')
    @mock.patch.object(image_utils, 'upload_volume')
    @mock.patch.object(dsware.DSWAREDriver, '_detach_volume')
    def test_copy_volume_to_image_query_attach_fail(self, mock_detach,
                                                    mock_upload, mock_query,
                                                    mock_attach,
                                                    mock_get_manage_ip):
        already_attached = {'ret_code': '50151401',
                            'ret_desc': 'already_attached',
                            'dev_addr': '/dev/sdb'}
        failure = {'ret_code': '50510011',
                   'ret_desc': 'failed',
                   'dev_addr': '/dev/sdb'}
        context = ''
        image_service = ''
        image_meta = ''

        mock_get_manage_ip.return_value = '127.0.0.1'
        mock_attach.return_value = already_attached
        mock_query.return_value = failure
        self.assertRaises(exception.CinderException,
                          self.driver.copy_volume_to_image,
                          context, self.volume, image_service, image_meta)

        mock_query.return_value = None
        self.assertRaises(exception.CinderException,
                          self.driver.copy_volume_to_image,
                          context, self.volume, image_service, image_meta)

    @mock.patch.object(dsware.DSWAREDriver, '_get_dsware_manage_ip')
    @mock.patch.object(dsware.DSWAREDriver, '_attach_volume')
    @mock.patch.object(dsware.DSWAREDriver, '_query_volume_attach')
    @mock.patch.object(image_utils, 'upload_volume')
    @mock.patch.object(dsware.DSWAREDriver, '_detach_volume')
    def test_copy_volume_to_image_upload_fail(self, mock_detach, mock_upload,
                                              mock_query, mock_attach,
                                              mock_get_manage_ip):
        success = {'ret_code': '0',
                   'ret_desc': 'success',
                   'dev_addr': '/dev/sdb'}
        already_attached = {'ret_code': '50151401',
                            'ret_desc': 'already_attached',
                            'dev_addr': '/dev/sdb'}
        context = ''
        image_service = ''
        image_meta = ''

        mock_get_manage_ip.return_value = '127.0.0.1'
        mock_attach.return_value = already_attached
        mock_query.return_value = success
        mock_upload.side_effect = exception.CinderException(
            'upload_volume error')
        self.assertRaises(exception.CinderException,
                          self.driver.copy_volume_to_image,
                          context, self.volume, image_service, image_meta)

    @mock.patch.object(fspythonapi.FSPythonApi, 'query_volume')
    def test_private_get_volume(self, mock_query):
        result_success = {'result': 0}
        result_not_exist = {'result': "50150005\n"}
        result_exception = {'result': "50510006\n"}

        mock_query.side_effect = [
            result_success, result_not_exist, result_exception]

        retval = self.driver._get_volume(self.volume.name)
        self.assertTrue(retval)

        retval = self.driver._get_volume(self.volume.name)
        self.assertFalse(retval)

        self.assertRaises(exception.CinderException,
                          self.driver._get_volume,
                          self.volume.name)

    @mock.patch.object(fspythonapi.FSPythonApi, 'delete_volume')
    def test_private_delete_volume(self, mock_delete):
        result_success = 0
        result_not_exist = '50150005\n'
        result_being_deleted = '50151002\n'
        result_exception = '51050006\n'

        mock_delete.side_effect = [result_success, result_not_exist,
                                   result_being_deleted, result_exception]

        retval = self.driver._delete_volume(self.volume.name)
        self.assertTrue(retval)

        retval = self.driver._delete_volume(self.volume.name)
        self.assertTrue(retval)

        retval = self.driver._delete_volume(self.volume.name)
        self.assertTrue(retval)

        self.assertRaises(exception.CinderException,
                          self.driver._delete_volume, self.volume.name)

    @mock.patch.object(dsware.DSWAREDriver, '_get_volume')
    @mock.patch.object(dsware.DSWAREDriver, '_delete_volume')
    def test_delete_volume(self, mock_delete, mock_get):
        mock_get.return_value = False
        retval = self.driver.delete_volume(self.volume)
        self.assertTrue(retval)

        mock_get.return_value = True
        mock_delete.return_value = True
        retval = self.driver.delete_volume(self.volume)
        self.assertTrue(retval)

        mock_get.return_value = True
        mock_delete.side_effect = exception.CinderException(
            'delete volume exception')
        self.assertRaises(exception.CinderException,
                          self.driver.delete_volume,
                          self.volume)

        mock_get.side_effect = exception.CinderException(
            'get volume exception')
        self.assertRaises(exception.CinderException,
                          self.driver.delete_volume,
                          self.volume)

    @mock.patch.object(fspythonapi.FSPythonApi, 'query_snap')
    def test_private_get_snapshot(self, mock_query):
        result_success = {'result': 0}
        result_not_found = {'result': "50150006\n"}
        result_exception = {'result': "51050007\n"}
        mock_query.side_effect = [result_success, result_not_found,
                                  result_exception]

        retval = self.driver._get_snapshot(self.snapshot.name)
        self.assertTrue(retval)

        retval = self.driver._get_snapshot(self.snapshot.name)
        self.assertFalse(retval)

        self.assertRaises(exception.CinderException,
                          self.driver._get_snapshot,
                          self.snapshot.name)

    @mock.patch.object(fspythonapi.FSPythonApi, 'create_snapshot')
    def test_private_create_snapshot(self, mock_create):
        mock_create.side_effect = [0, 1]

        self.driver._create_snapshot(self.snapshot.name,
                                     self.volume.name)

        self.assertRaises(exception.CinderException,
                          self.driver._create_snapshot,
                          self.snapshot.name, self.volume.name)

    @mock.patch.object(fspythonapi.FSPythonApi, 'delete_snapshot')
    def test_private_delete_snapshot(self, mock_delete):
        mock_delete.side_effect = [0, 1]

        self.driver._delete_snapshot(self.snapshot.name)

        self.assertRaises(exception.CinderException,
                          self.driver._delete_snapshot, self.snapshot.name)

    @mock.patch.object(dsware.DSWAREDriver, '_get_volume')
    @mock.patch.object(dsware.DSWAREDriver, '_create_snapshot')
    def test_create_snapshot(self, mock_create, mock_get):
        mock_get.return_value = True
        self.driver.create_snapshot(self.snapshot)

        mock_create.side_effect = exception.CinderException(
            'create snapshot failed')
        self.assertRaises(exception.CinderException,
                          self.driver.create_snapshot, self.snapshot)

        mock_get.side_effect = [
            False, exception.CinderException('get volume failed')]
        self.assertRaises(exception.CinderException,
                          self.driver.create_snapshot,
                          self.snapshot)
        self.assertRaises(exception.CinderException,
                          self.driver.create_snapshot,
                          self.snapshot)

    @mock.patch.object(dsware.DSWAREDriver, '_get_snapshot')
    @mock.patch.object(dsware.DSWAREDriver, '_delete_snapshot')
    def test_delete_snapshot(self, mock_delete, mock_get):
        mock_get.side_effect = [True, False, exception.CinderException, True]
        self.driver.delete_snapshot(self.snapshot)
        self.driver.delete_snapshot(self.snapshot)

        self.assertRaises(exception.CinderException,
                          self.driver.delete_snapshot,
                          self.snapshot)
        mock_delete.side_effect = exception.CinderException(
            'delete snapshot exception')
        self.assertRaises(exception.CinderException,
                          self.driver.delete_snapshot,
                          self.snapshot)

    @mock.patch.object(fspythonapi.FSPythonApi, 'query_pool_info')
    def test_private_update_single_pool_info_status(self, mock_query):
        pool_info = {'result': 0,
                     'pool_id': 10,
                     'total_capacity': 10240,
                     'used_capacity': 5120,
                     'alloc_capacity': 7168}
        pool_info_none = {'result': 1}

        mock_query.side_effect = [pool_info, pool_info_none]

        self.driver._update_single_pool_info_status()
        self.assertEqual({'total_capacity_gb': 10.0,
                          'free_capacity_gb': 5.0,
                          'volume_backend_name': None,
                          'vendor_name': 'Open Source',
                          'driver_version': '1.0',
                          'storage_protocol': 'dsware',
                          'reserved_percentage': 0,
                          'QoS_support': False},
                         self.driver._stats)

        self.driver._update_single_pool_info_status()
        self.assertIsNone(self.driver._stats)

    @mock.patch.object(fspythonapi.FSPythonApi, 'query_pool_type')
    def test_private_update_multi_pool_of_same_type_status(self, mock_query):
        query_result = (0, [{'result': 0,
                             'pool_id': '0',
                             'total_capacity': '10240',
                             'used_capacity': '5120',
                             'alloc_capacity': '7168'}])
        query_result_none = (0, [])

        mock_query.side_effect = [query_result, query_result_none]

        self.driver._update_multi_pool_of_same_type_status()
        self.assertEqual({'volume_backend_name': None,
                          'vendor_name': 'Open Source',
                          'driver_version': '1.0',
                          'storage_protocol': 'dsware',
                          'pools': [{'pool_name': '0',
                                     'total_capacity_gb': 10.0,
                                     'allocated_capacity_gb': 5.0,
                                     'free_capacity_gb': 5.0,
                                     'QoS_support': False,
                                     'reserved_percentage': 0}]},
                         self.driver._stats)

        self.driver._update_multi_pool_of_same_type_status()
        self.assertIsNone(self.driver._stats)

    def test_private_calculate_pool_info(self):
        pool_sets = [{'pool_id': 0,
                      'total_capacity': 10240,
                      'used_capacity': 5120,
                      'QoS_support': False,
                      'reserved_percentage': 0}]
        retval = self.driver._calculate_pool_info(pool_sets)
        self.assertEqual([{'pool_name': 0,
                           'total_capacity_gb': 10.0,
                           'allocated_capacity_gb': 5.0,
                           'free_capacity_gb': 5.0,
                           'QoS_support': False,
                           'reserved_percentage': 0}],
                         retval)

    @mock.patch.object(dsware.DSWAREDriver, '_update_single_pool_info_status')
    @mock.patch.object(dsware.DSWAREDriver,
                       '_update_multi_pool_of_same_type_status')
    @mock.patch.object(fspythonapi.FSPythonApi, 'query_dsware_version')
    def test_get_volume_stats(self, mock_query, mock_type, mock_info):
        mock_query.return_value = 1

        self.driver.get_volume_stats(False)
        mock_query.assert_not_called()

        self.driver.get_volume_stats(True)
        mock_query.assert_called_once_with()
