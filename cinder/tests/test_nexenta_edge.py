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

from oslo_serialization import jsonutils


class TestNexentaEdgeISCSIDriver(test.TestCase):
    CLUSTER = 'cluster1'
    TENANT = 'tenant1'
    BUCKET = 'bucket1'
    BUCKET_PATH = CLUSTER + '/' + TENANT + '/' + BUCKET
    BUCKET_URL = 'clusters/' + CLUSTER + '/tenants/' + TENANT + \
        '/buckets/' + BUCKET
    TEST_VOLUME1 = {
        'name': 'volume1',
        'size': 1,
        'id': '1',
        'status': 'available'
    }
    TEST_VOLUME1_NEDGE = {
        'objectPath': BUCKET_PATH + '/1',
        'volSizeMB': TEST_VOLUME1['size'] * 1024,
        'blockSize': 4096,
        'chunkSize': 4096,
        'number': 1
    }
    TEST_VOLUME2 = {
        'name': 'volume2',
        'size': 1,
        'id': '2',
        'status': 'in-use',
    }
    TEST_VOLUME2_NEDGE = {
        'objectPath': BUCKET_PATH + '/2',
        'volSizeMB': TEST_VOLUME2['size'] * 1024,
        'blockSize': 4096,
        'chunkSize': 4096,
        'number': 2
    }
    TEST_SNAPSHOT = {
        'name': 'snapshot1',
        'volume_name': TEST_VOLUME1['name'],
        'volume_size': 1
    }

    def __init__(self, method):
        super(TestNexentaEdgeISCSIDriver, self).__init__(method)

    def setUp(self):
        super(TestNexentaEdgeISCSIDriver, self).setUp()
        self.configuration = mox_lib.MockObject(conf.Configuration)
        self.configuration.nexenta_host = '1.1.1.1'
        self.configuration.nexenta_user = 'admin'
        self.configuration.nexenta_password = 'nexenta'
        self.configuration.nexenta_volume = self.BUCKET_PATH
        self.configuration.nexenta_rest_port = 8080
        self.configuration.nexenta_rest_protocol = 'http'
        self.configuration.nexenta_iscsi_target_portal_port = 3260
        self.configuration.nexenta_target_prefix = 'iqn:'
        self.restapi_mock = self.mox.CreateMockAnything()
        for mod in ['get', 'post', 'put', 'delete']:
            setattr(self.restapi_mock, mod, self.mox.CreateMockAnything())
        self.stubs.Set(jsonrpc, 'NexentaEdgeResourceProxy',
                       lambda *_, **__: self.restapi_mock)
        self.drv = iscsi_ne.NexentaEdgeISCSIDriver(
            configuration=self.configuration)
        mockResponse = self.mox.CreateMockAnything()
        setattr(mockResponse, '__getitem__', lambda s: 'Target 1: iqn...')
        self.restapi_mock.get('sysconfig/iscsi/status'
                              ).AndReturn(mockResponse)
        self.mox.ReplayAll()
        self.drv.do_setup({})
        self.mox.ResetAll()

    def test_setup_error(self):
        self.restapi_mock.get(self.BUCKET_URL).AndReturn({'response': 'OK'})
        self.mox.ReplayAll()
        self.drv.check_for_setup_error()

    def test_setup_error_fail(self):
        self.restapi_mock.get(self.BUCKET_URL).AndRaise(
            nexenta.NexentaException('MOCK SETUP FAILURE'))
        self.mox.ReplayAll()
        self.assertRaises(nexenta.NexentaException,
                          self.drv.check_for_setup_error)

    def test_create_volume(self):
        self.restapi_mock.get(self.BUCKET_URL).AndReturn({
            'bucketMetadata': {}
        })
        self.restapi_mock.post('iscsi', self.TEST_VOLUME1_NEDGE).AndReturn(
           {'response': 'CREATED'})
        namemap = {}
        namemap[self.TEST_VOLUME1['name']] = self.TEST_VOLUME1_NEDGE['number']
        self.restapi_mock.put(self.BUCKET_URL, {
            'optionsObject': {'X-Name-Map': jsonutils.dumps(namemap)}
        }).AndReturn({'response': 'OK'})
        self.mox.ReplayAll()
        self.drv.create_volume(self.TEST_VOLUME1)

    def _mock_name_map(self):
        namemap = {}
        namemap[self.TEST_VOLUME1['name']] = self.TEST_VOLUME1_NEDGE['number']
        self.restapi_mock.get(self.BUCKET_URL).AndReturn({
            'bucketMetadata': {
                'X-Name-Map': jsonutils.dumps(namemap)
            }
        })
        return namemap

    def test_create_volume_2(self):
        namemap = self._mock_name_map()
        self.restapi_mock.post('iscsi', self.TEST_VOLUME2_NEDGE).AndReturn(
           {'response': 'CREATED'})
        namemap[self.TEST_VOLUME2['name']] = self.TEST_VOLUME2_NEDGE['number']
        self.restapi_mock.put(self.BUCKET_URL, {
            'optionsObject': {'X-Name-Map': jsonutils.dumps(namemap)}
        }).AndReturn({'response': 'OK'})
        self.mox.ReplayAll()
        self.drv.create_volume(self.TEST_VOLUME2)

    def test_delete_volume(self):
        namemap = self._mock_name_map()
        self.restapi_mock.delete(
            'iscsi/' + str(namemap[self.TEST_VOLUME1['name']]),
            {'objectPath': self.TEST_VOLUME1_NEDGE['objectPath']}
        ).AndReturn({'response': 'DELETED'})
        self.restapi_mock.put(
            self.BUCKET_URL,
            {'optionsObject': {'X-Name-Map': jsonutils.dumps({})}}
        ).AndReturn({'response': 'OK'})
        self.mox.ReplayAll()
        self.drv.delete_volume(self.TEST_VOLUME1)

    def test_extend_volume(self):
        namemap = self._mock_name_map()
        self.restapi_mock.post(
            'iscsi/' + str(namemap[self.TEST_VOLUME1['name']]) +
            '/resize', {'objectPath': self.TEST_VOLUME1_NEDGE['objectPath'],
                        'newSizeMB': 2048}
        ).AndReturn({'response': 'OK'})
        self.mox.ReplayAll()
        self.drv.extend_volume(self.TEST_VOLUME1, 2)

    def test_create_snapshot(self):
        namemap = self._mock_name_map()
        self.restapi_mock.post(
            self.BUCKET_URL + '/snapviews/' +
            str(namemap[self.TEST_VOLUME1['name']]) + '.snapview', {
                'ss_bucket': self.BUCKET,
                'ss_object': str(namemap[self.TEST_VOLUME1['name']]),
                'ss_name': self.TEST_SNAPSHOT['name']}
        ).AndReturn({'response': 'OK'})
        self.mox.ReplayAll()
        self.drv.create_snapshot(self.TEST_SNAPSHOT)

    def test_delete_snapshot(self):
        namemap = self._mock_name_map()
        self.restapi_mock.delete(
            self.BUCKET_URL + '/snapviews/' +
            str(namemap[self.TEST_VOLUME1['name']]) + '.snapview/snapshots/' +
            self.TEST_SNAPSHOT['name']
        ).AndReturn({'response': 'OK'})
        self.mox.ReplayAll()
        self.drv.delete_snapshot(self.TEST_SNAPSHOT)

    def test_create_volume_from_snapshot(self):
        namemap = self._mock_name_map()
        self.restapi_mock.post(
            self.BUCKET_URL + '/snapviews/' +
            str(namemap[self.TEST_VOLUME1['name']]) + '.snapview/snapshots/' +
            self.TEST_SNAPSHOT['name'], {
                'ss_tenant': self.TENANT,
                'ss_bucket': self.BUCKET,
                'ss_object': '2'  # should be allocated to 2
            }).AndReturn({'response': 'OK'})
        self.restapi_mock.post('iscsi', self.TEST_VOLUME2_NEDGE
                               ).AndReturn({'response': 'CLONED'})
        namemap[self.TEST_VOLUME2['name']] = 2
        self.restapi_mock.put(self.BUCKET_URL, {
            'optionsObject': {'X-Name-Map': jsonutils.dumps(namemap)}
        }).AndReturn({'response': 'OK'})
        self.mox.ReplayAll()
        self.drv.create_volume_from_snapshot(self.TEST_VOLUME2,
                                             self.TEST_SNAPSHOT)

    def test_create_cloned_volume(self):
        namemap = self._mock_name_map()
        self.restapi_mock.post(
            self.BUCKET_PATH + '/objects/' +
            str(namemap[self.TEST_VOLUME1['name']]), {
                'tenant_name': self.TENANT,
                'bucket_name': self.BUCKET,
                'object_name': str(self.TEST_VOLUME2_NEDGE['number'])}
        ).AndReturn({'response': 'OK'})
        self.restapi_mock.post('iscsi', self.TEST_VOLUME2_NEDGE).AndReturn(
            {'response': 'OK'})
        self.mox.ReplayAll()
        self.drv.create_cloned_volume(self.TEST_VOLUME2, self.TEST_VOLUME1)

    def test_local_path(self):
        namemap = self._mock_name_map()
        self.mox.ReplayAll()
        result = self.drv.local_path(self.TEST_VOLUME1)
        self.assertEqual(self.BUCKET_PATH + '/' +
                         str(self.TEST_VOLUME1_NEDGE['number']), result)

    def test_get_volume_stats(self):
        pass


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
