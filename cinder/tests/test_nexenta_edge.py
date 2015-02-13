#
# Copyright 2015 Nexenta Systems, Inc.
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
Unit tests for OpenStack Cinder volume driver
"""

import base64
import urllib2

import mox as mox_lib

from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import nexenta
from cinder.volume.drivers.nexenta import iscsi_ne
from cinder.volume.drivers.nexenta import jsonrpc

class TestNexentaEdgeISCSIDriver(test.TestCase):
    TEST_VOLUME_NAME = 'volume1'
    TEST_VOLUME_NAME2 = 'volume2'
    TEST_SNAPSHOT_NAME = 'snapshot1'
    TEST_VOLUME_REF = {
        'name': TEST_VOLUME_NAME,
        'size': 1,
        'id': '1',
        'status': 'available'
    }
    TEST_VOLUME_REF2 = {
        'name': TEST_VOLUME_NAME2,
        'size': 1,
        'id': '2',
        'status': 'in-use'
    }
    TEST_SNAPSHOT_REF = {
        'name': TEST_SNAPSHOT_NAME,
        'volume_name': TEST_VOLUME_NAME,
    }

    def __init__(self, method):
        super(TestNexentaEdgeISCSIDriver, self).__init__(method)

    def setUp(self):
        super(TestNexentaEdgeISCSIDriver, self).setUp()
        self.configuration = mox_lib.MockObject(conf.Configuration)
        self.configuration.nexenta_host = '1.1.1.1'
        self.configuration.nexenta_user = 'admin'
        self.configuration.nexenta_password = 'nexenta'
        self.configuration.nexenta_volume = 'cluster1/tenant1/bucket1'
        self.configuration.nexenta_rest_port = 8080
        self.configuration.nexenta_rest_protocol = 'http'
        self.configuration.nexenta_iscsi_target_portal_port = 3260
        self.configuration.nexenta_target_prefix = 'iqn:'
        self.restapi_mock = self.mox.CreateMockAnything()
        for mod in ['get', 'post']:
            setattr(self.restapi_mock, mod, self.mox.CreateMockAnything())
        self.stubs.Set(jsonrpc, 'NexentaEdgeResourceProxy',
                       lambda *_, **__: self.restapi_mock)
        self.drv = iscsi_ne.NexentaEdgeISCSIDriver(configuration=self.configuration)
        self.drv.do_setup({})

    def test_setup_error(self):
        self.restapi_mock.get('cinder').AndReturn(True)
        self.mox.ReplayAll()
        self.drv.check_for_setup_error()

    def test_setup_error_fail(self):
        self.restapi_mock.get('cinder').AndReturn(False)
        self.mox.ReplayAll()
        self.assertRaises(LookupError, self.drv.check_for_setup_error)

    def test_local_path(self):
        self.assertRaises(NotImplementedError, self.drv.local_path, '')

    def test_create_volume(self):
        self.restapi_mock.zvol.create('cinder/volume1', '1G', '8K', True)
        self.restapi_mock.stmf.list_targets()
        self.restapi_mock.iscsitarget.create_target({'target_name': 'iqn:volume1'})
        self.restapi_mock.stmf.list_targetgroups()
        self.restapi_mock.stmf.create_targetgroup('cinder/volume1')
        self.restapi_mock.stmf.list_targetgroup_members('cinder/volume1')
        self.restapi_mock.stmf.add_targetgroup_member('cinder/volume1',
                                                  'iqn:volume1')
        self.restapi_mock.scsidisk.lu_exists('cinder/volume1')
        self.restapi_mock.scsidisk.create_lu('cinder/volume1', {})
        self.restapi_mock.scsidisk.lu_shared('cinder/volume1')
        self.restapi_mock.scsidisk.add_lun_mapping_entry(
            'cinder/volume1', {'target_group': 'cinder/volume1', 'lun': '0'})
        self.mox.ReplayAll()
        self.drv.create_volume(self.TEST_VOLUME_REF)

    def test_delete_volume(self):
        self.restapi_mock.zvol.get_child_props('cinder/volume1',
                                           'origin').AndReturn({})
        self.restapi_mock.zvol.destroy('cinder/volume1', '')
        self.mox.ReplayAll()
        self.drv.delete_volume(self.TEST_VOLUME_REF)
        self.mox.ResetAll()

        c = self.restapi_mock.zvol.get_child_props('cinder/volume1', 'origin')
        c.AndReturn({'origin': 'cinder/volume0@snapshot'})
        self.restapi_mock.zvol.destroy('cinder/volume1', '')
        self.mox.ReplayAll()
        self.drv.delete_volume(self.TEST_VOLUME_REF)
        self.mox.ResetAll()

        c = self.restapi_mock.zvol.get_child_props('cinder/volume1', 'origin')
        c.AndReturn({'origin': 'cinder/volume0@cinder-clone-snapshot-1'})
        self.restapi_mock.zvol.destroy('cinder/volume1', '')
        self.restapi_mock.snapshot.destroy(
            'cinder/volume0@cinder-clone-snapshot-1', '')
        self.mox.ReplayAll()
        self.drv.delete_volume(self.TEST_VOLUME_REF)
        self.mox.ResetAll()

    def test_get_volume_stats(self):
        stats = {'size': '5368709120G',
                 'used': '5368709120G',
                 'available': '5368709120G',
                 'health': 'ONLINE'}
        self.restapi_mock.volume.get_child_props(
            self.configuration.nexenta_volume,
            'health|size|used|available').AndReturn(stats)
        self.mox.ReplayAll()
        stats = self.drv.get_volume_stats(True)
        self.assertEqual(stats['storage_protocol'], 'iSCSI')
        self.assertEqual(stats['total_capacity_gb'], 5368709120.0)
        self.assertEqual(stats['free_capacity_gb'], 5368709120.0)
        self.assertEqual(stats['reserved_percentage'], 0)
        self.assertEqual(stats['QoS_support'], False)

class TestNexentaEdgeResourceRPC(test.TestCase):
    HOST = 'example.com'
    URL = 'http://%s/' % HOST
    URL_S = 'https://%s/' % HOST
    USER = 'user'
    PASSWORD = 'password'
    HEADERS = {
        'Content-Type': 'application/json',
        'Authorization':
            'Basic %s' % ('%s:%s' % (USER, PASSWORD)).encode('base64')[:-1]
    }

    def setUp(self):
        super(TestNexentaEdgeResourceRPC, self).setUp()
        self.proxy = jsonrpc.NexentaEdgeResourceProxy(
            'http', self.HOST, 8080, '/', self.USER, self.PASSWORD, auto=True)
        self.mox.StubOutWithMock(urllib2, 'Request', True)
        self.mox.StubOutWithMock(urllib2, 'urlopen')
        self.req_mock = self.mox.CreateMockAnything()
        setattr(self.req_mock, 'get_method', self.mox.CreateMockAnything())
        self.resp_mock = self.mox.CreateMockAnything()
        self.resp_info_mock = self.mox.CreateMockAnything()
        self.resp_mock.info().AndReturn(self.resp_info_mock)
        urllib2.urlopen(self.req_mock).AndReturn(self.resp_mock)

    def test_get_call(self):
        urllib2.Request(
            'http://%s:8080/%s' % (self.HOST, 'resource'), None,
            self.HEADERS).AndReturn(self.req_mock)
        self.resp_info_mock.status = ''
        self.resp_mock.read().AndReturn('{"response": "the result"}')
        self.mox.ReplayAll()
        result = self.proxy.get('resource')
        self.assertEqual("the result", result)

    def test_post_call(self):
        urllib2.Request(
            'http://%s:8080/%s' % (self.HOST, 'resource/name'), None,
            self.HEADERS).AndReturn(self.req_mock)
        self.resp_info_mock.status = ''
        self.resp_mock.read().AndReturn('{"response": "the result"}')
        self.mox.ReplayAll()
        result = self.proxy.post('resource/name')
        self.assertEqual("the result", result)

    def test_call_auto(self):
        urllib2.Request(
            'http://%s:8080/%s' % (self.HOST, 'resource'), None,
            self.HEADERS).AndReturn(self.req_mock)
        urllib2.Request(
            'https://%s:8080/%s' % (self.HOST, 'resource'), None,
            self.HEADERS).AndReturn(self.req_mock)
        self.resp_info_mock.status = 'EOF in headers'
        self.resp_mock.read().AndReturn('{"response": "the result"}')
        urllib2.urlopen(self.req_mock).AndReturn(self.resp_mock)
        self.mox.ReplayAll()
        result = self.proxy.get('resource')
        self.assertEqual("the result", result)

    def test_call_error(self):
        urllib2.Request(
            'http://%s:8080/%s' % (self.HOST, 'resource'), None,
            self.HEADERS).AndReturn(self.req_mock)
        self.resp_info_mock.status = ''
        self.resp_mock.read().AndReturn('{"code": 200, "message": "the error"')
        self.mox.ReplayAll()
        self.assertRaises(jsonrpc.NexentaJSONException,
            self.proxy.get, 'resource')

    def test_call_fail(self):
        urllib2.Request(
            'http://%s:8080/%s' % (self.HOST, 'resource'), None,
            self.HEADERS).AndReturn(self.req_mock)
        self.resp_info_mock.status = 'EOF in headers'
        self.proxy.auto = False
        self.mox.ReplayAll()
        self.assertRaises(jsonrpc.NexentaJSONException,
            self.proxy.get, 'resource')
