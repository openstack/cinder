# Copyright 2019 Nexenta Systems, Inc.
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
"""Unit tests for NexentaStor 5 REST API helper."""

import copy
import json
import posixpath
from unittest import mock
import uuid

from oslo_utils.secretutils import md5
import requests
import six

from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.nexenta.ns5 import jsonrpc


class FakeNefProxy(object):

    def __init__(self):
        self.scheme = 'https'
        self.port = 8443
        self.hosts = ['1.1.1.1', '2.2.2.2']
        self.host = self.hosts[0]
        self.root = 'pool/share'
        self.username = 'username'
        self.password = 'password'
        self.retries = 3
        self.timeout = 5
        self.session = mock.Mock()
        self.session.headers = {}

    def __getattr__(self, name):
        pass

    def delay(self, interval):
        pass

    def delete_bearer(self):
        pass

    def update_lock(self):
        pass

    def update_token(self, token):
        pass

    def update_host(self, host):
        pass

    def url(self, path):
        return '%s://%s:%s/%s' % (self.scheme, self.host, self.port, path)


class TestNefException(test.TestCase):

    def test_message(self):
        message = 'test message 1'
        result = jsonrpc.NefException(message)
        self.assertIn(message, result.msg)

    def test_message_kwargs(self):
        code = 'EAGAIN'
        message = 'test message 2'
        result = jsonrpc.NefException(message, code=code)
        self.assertEqual(code, result.code)
        self.assertIn(message, result.msg)

    def test_no_message_kwargs(self):
        code = 'ESRCH'
        message = 'test message 3'
        result = jsonrpc.NefException(None, code=code, message=message)
        self.assertEqual(code, result.code)
        self.assertIn(message, result.msg)

    def test_message_plus_kwargs(self):
        code = 'ENODEV'
        message1 = 'test message 4'
        message2 = 'test message 5'
        result = jsonrpc.NefException(message1, code=code, message=message2)
        self.assertEqual(code, result.code)
        self.assertIn(message2, result.msg)

    def test_dict(self):
        code = 'ENOENT'
        message = 'test message 4'
        result = jsonrpc.NefException({'code': code, 'message': message})
        self.assertEqual(code, result.code)
        self.assertIn(message, result.msg)

    def test_kwargs(self):
        code = 'EPERM'
        message = 'test message 5'
        result = jsonrpc.NefException(code=code, message=message)
        self.assertEqual(code, result.code)
        self.assertIn(message, result.msg)

    def test_dict_kwargs(self):
        code = 'EINVAL'
        message = 'test message 6'
        result = jsonrpc.NefException({'code': code}, message=message)
        self.assertEqual(code, result.code)
        self.assertIn(message, result.msg)

    def test_defaults(self):
        code = 'EBADMSG'
        message = 'NexentaError'
        result = jsonrpc.NefException()
        self.assertEqual(code, result.code)
        self.assertIn(message, result.msg)


class TestNefRequest(test.TestCase):

    def setUp(self):
        super(TestNefRequest, self).setUp()
        self.proxy = FakeNefProxy()

    def fake_response(self, method, path, payload, code, content):
        request = requests.PreparedRequest()
        request.method = method
        request.url = self.proxy.url(path)
        request.headers = {'Content-Type': 'application/json'}
        request.body = None
        if method in ['get', 'delete']:
            request.params = payload
        elif method in ['put', 'post']:
            request.data = json.dumps(payload)
        response = requests.Response()
        response.request = request
        response.status_code = code
        if content:
            response._content = json.dumps(content)
        else:
            response._content = ''
        return response

    def test___call___invalid_method(self):
        method = 'unsupported'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        self.assertRaises(jsonrpc.NefException, instance, path)

    def test___call___none_path(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        self.assertRaises(jsonrpc.NefException, instance, None)

    def test___call___empty_path(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        self.assertRaises(jsonrpc.NefException, instance, '')

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___get(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {}
        content = {'name': 'snapshot'}
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        result = instance(path, payload)
        request.assert_called_with(method, path)
        self.assertEqual(content, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___get_payload(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'name': 'snapshot'}
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        result = instance(path, payload)
        params = {'params': payload}
        request.assert_called_with(method, path, **params)
        self.assertEqual(content, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___get_data_payload(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        data = [
            {
                'name': 'fs1',
                'path': 'pool/fs1'
            },
            {
                'name': 'fs2',
                'path': 'pool/fs2'
            }
        ]
        content = {'data': data}
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        instance.data = data
        result = instance(path, payload)
        params = {'params': payload}
        request.assert_called_with(method, path, **params)
        self.assertEqual(data, result)

    def test___call___get_invalid_payload(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = 'bad data'
        self.assertRaises(jsonrpc.NefException, instance, path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___delete(self, request):
        method = 'delete'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {}
        content = {'name': 'snapshot'}
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        result = instance(path, payload)
        request.assert_called_with(method, path)
        self.assertEqual(content, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___delete_payload(self, request):
        method = 'delete'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'name': 'snapshot'}
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        result = instance(path, payload)
        params = {'params': payload}
        request.assert_called_with(method, path, **params)
        self.assertEqual(content, result)

    def test___call___delete_invalid_payload(self):
        method = 'delete'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = 'bad data'
        self.assertRaises(jsonrpc.NefException, instance, path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___post(self, request):
        method = 'post'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {}
        content = None
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        result = instance(path, payload)
        request.assert_called_with(method, path)
        self.assertEqual(content, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___post_payload(self, request):
        method = 'post'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = None
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        result = instance(path, payload)
        params = {'data': json.dumps(payload)}
        request.assert_called_with(method, path, **params)
        self.assertEqual(content, result)

    def test___call___post_invalid_payload(self):
        method = 'post'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = 'bad data'
        self.assertRaises(jsonrpc.NefException, instance, path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___put(self, request):
        method = 'put'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {}
        content = None
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        result = instance(path, payload)
        request.assert_called_with(method, path)
        self.assertEqual(content, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___put_payload(self, request):
        method = 'put'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = None
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        result = instance(path, payload)
        params = {'data': json.dumps(payload)}
        request.assert_called_with(method, path, **params)
        self.assertEqual(content, result)

    def test___call___put_invalid_payload(self):
        method = 'put'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = 'bad data'
        self.assertRaises(jsonrpc.NefException, instance, path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___non_ok_response(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'code': 'ENOENT', 'message': 'error'}
        response = self.fake_response(method, path, payload, 500, content)
        request.return_value = response
        self.assertRaises(jsonrpc.NefException, instance, path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.failover')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___request_after_failover(self, request, failover):
        method = 'post'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = None
        response = self.fake_response(method, path, payload, 200, content)
        request.side_effect = [requests.exceptions.Timeout, response]
        failover.return_value = True
        result = instance(path, payload)
        params = {'data': json.dumps(payload)}
        request.assert_called_with(method, path, **params)
        self.assertEqual(content, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.failover')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test___call___request_failover_error(self, request, failover):
        method = 'put'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        request.side_effect = requests.exceptions.Timeout
        failover.return_value = False
        self.assertRaises(requests.exceptions.Timeout, instance, path, payload)

    def test_hook_default(self):
        method = 'post'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'name': 'dataset'}
        response = self.fake_response(method, path, payload, 303, content)
        result = instance.hook(response)
        self.assertEqual(response, result)

    def test_hook_200_empty(self):
        method = 'delete'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'storage/filesystems'
        payload = {'force': True}
        content = None
        response = self.fake_response(method, path, payload, 200, content)
        result = instance.hook(response)
        self.assertEqual(response, result)

    def test_hook_201_empty(self):
        method = 'post'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'storage/snapshots'
        payload = {'path': 'parent/child@name'}
        content = None
        response = self.fake_response(method, path, payload, 201, content)
        result = instance.hook(response)
        self.assertEqual(response, result)

    def test_hook_500_empty(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'storage/pools'
        payload = {'poolName': 'tank'}
        content = None
        response = self.fake_response(method, path, payload, 500, content)
        self.assertRaises(jsonrpc.NefException, instance.hook, response)

    def test_hook_200_bad_content(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'storage/volumes'
        payload = {'name': 'test'}
        content = None
        response = self.fake_response(method, path, payload, 200, content)
        response._content = 'bad_content'
        self.assertRaises(jsonrpc.NefException, instance.hook, response)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.auth')
    def test_hook_401(self, auth, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'code': 'EAUTH'}
        response = self.fake_response(method, path, payload, 401, content)
        auth.return_value = True
        content2 = {'name': 'test'}
        response2 = self.fake_response(method, path, payload, 200, content2)
        request.return_value = response2
        self.proxy.session.send.return_value = content2
        result = instance.hook(response)
        self.assertEqual(content2, result)

    def test_hook_401_max_retries(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        instance.stat[401] = self.proxy.retries
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'code': 'EAUTH'}
        response = self.fake_response(method, path, payload, 401, content)
        self.assertRaises(jsonrpc.NefException, instance.hook, response)

    def test_hook_404_nested(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        instance.lock = True
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'code': 'ENOENT'}
        response = self.fake_response(method, path, payload, 404, content)
        result = instance.hook(response)
        self.assertEqual(response, result)

    def test_hook_404_max_retries(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        instance.stat[404] = self.proxy.retries
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'code': 'ENOENT'}
        response = self.fake_response(method, path, payload, 404, content)
        self.assertRaises(jsonrpc.NefException, instance.hook, response)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.failover')
    def test_hook_404_failover_error(self, failover):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'code': 'ENOENT'}
        response = self.fake_response(method, path, payload, 404, content)
        failover.return_value = False
        result = instance.hook(response)
        self.assertEqual(response, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.failover')
    def test_hook_404_failover_ok(self, failover, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'code': 'ENOENT'}
        response = self.fake_response(method, path, payload, 404, content)
        failover.return_value = True
        content2 = {'name': 'test'}
        response2 = self.fake_response(method, path, payload, 200, content2)
        request.return_value = response2
        result = instance.hook(response)
        self.assertEqual(response2, result)

    def test_hook_500_permanent(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'code': 'EINVAL'}
        response = self.fake_response(method, path, payload, 500, content)
        self.assertRaises(jsonrpc.NefException, instance.hook, response)

    def test_hook_500_busy_max_retries(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        instance.stat[500] = self.proxy.retries
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'code': 'EBUSY'}
        response = self.fake_response(method, path, payload, 500, content)
        self.assertRaises(jsonrpc.NefException, instance.hook, response)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test_hook_500_busy_ok(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'code': 'EBUSY'}
        response = self.fake_response(method, path, payload, 500, content)
        content2 = {'name': 'test'}
        response2 = self.fake_response(method, path, payload, 200, content2)
        request.return_value = response2
        result = instance.hook(response)
        self.assertEqual(response2, result)

    def test_hook_201_no_monitor(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'monitor': 'unknown'}
        response = self.fake_response(method, path, payload, 202, content)
        self.assertRaises(jsonrpc.NefException, instance.hook, response)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test_hook_201_ok(self, request):
        method = 'delete'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {
            'links': [{
                'rel': 'monitor',
                'href': '/jobStatus/jobID'
            }]
        }
        response = self.fake_response(method, path, payload, 202, content)
        content2 = None
        response2 = self.fake_response(method, path, payload, 201, content2)
        request.return_value = response2
        result = instance.hook(response)
        self.assertEqual(response2, result)

    def test_200_no_data(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'name': 'test'}
        response = self.fake_response(method, path, payload, 200, content)
        result = instance.hook(response)
        self.assertEqual(response, result)

    def test_200_pagination_end(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {'data': 'value'}
        response = self.fake_response(method, path, payload, 200, content)
        result = instance.hook(response)
        self.assertEqual(response, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test_200_pagination_next(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        content = {
            'data': [{
                'name': 'test'
            }],
            'links': [{
                'rel': 'next',
                'href': path
            }]
        }
        response = self.fake_response(method, path, payload, 200, content)
        response2 = self.fake_response(method, path, payload, 200, content)
        request.return_value = response2
        result = instance.hook(response)
        self.assertEqual(response2, result)

    def test_request(self):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = 'parent/child'
        payload = {'key': 'value'}
        expected = {'name': 'dataset'}
        url = self.proxy.url(path)
        kwargs = payload.copy()
        kwargs['timeout'] = self.proxy.timeout
        kwargs['hooks'] = {'response': instance.hook}
        self.proxy.session.request.return_value = expected
        result = instance.request(method, path, **payload)
        self.proxy.session.request.assert_called_with(method, url, **kwargs)
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test_auth(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        method = 'post'
        path = 'auth/login'
        payload = {
            'data': json.dumps({
                'username': self.proxy.username,
                'password': self.proxy.password
            })
        }
        content = {'token': 'test'}
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        instance.auth()
        request.assert_called_with(method, path, **payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test_auth_error(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        method = 'post'
        path = 'auth/login'
        payload = {
            'data': json.dumps({
                'username': self.proxy.username,
                'password': self.proxy.password
            })
        }
        content = {'data': 'noauth'}
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        self.assertRaises(jsonrpc.NefException, instance.auth)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test_failover(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = self.proxy.root
        payload = {}
        content = {'path': path}
        response = self.fake_response(method, path, payload, 200, content)
        request.return_value = response
        result = instance.failover()
        request.assert_called_with(method, path)
        expected = True
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test_failover_timeout(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = self.proxy.root
        payload = {}
        content = {'path': path}
        response = self.fake_response(method, path, payload, 200, content)
        request.side_effect = [requests.exceptions.Timeout, response]
        result = instance.failover()
        request.assert_called_with(method, path)
        expected = True
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test_failover_404(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = self.proxy.root
        payload = {}
        content = {}
        response = self.fake_response(method, path, payload, 404, content)
        request.side_effect = [response, response]
        result = instance.failover()
        request.assert_called_with(method, path)
        expected = False
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefRequest.request')
    def test_failover_error(self, request):
        method = 'get'
        instance = jsonrpc.NefRequest(self.proxy, method)
        path = self.proxy.root
        request.side_effect = [
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError
        ]
        result = instance.failover()
        request.assert_called_with(method, path)
        expected = False
        self.assertEqual(expected, result)

    def test_getpath(self):
        method = 'get'
        rel = 'monitor'
        href = 'jobStatus/jobID'
        content = {
            'links': [
                [1, 2],
                'bad link',
                {
                    'rel': 'next',
                    'href': href
                },
                {
                    'rel': rel,
                    'href': href
                }
            ]
        }
        instance = jsonrpc.NefRequest(self.proxy, method)
        result = instance.getpath(content, rel)
        expected = href
        self.assertEqual(expected, result)

    def test_getpath_no_content(self):
        method = 'get'
        rel = 'next'
        content = None
        instance = jsonrpc.NefRequest(self.proxy, method)
        result = instance.getpath(content, rel)
        expected = None
        self.assertEqual(expected, result)

    def test_getpath_no_links(self):
        method = 'get'
        rel = 'next'
        content = {'a': 'b'}
        instance = jsonrpc.NefRequest(self.proxy, method)
        result = instance.getpath(content, rel)
        expected = None
        self.assertEqual(expected, result)

    def test_getpath_no_rel(self):
        method = 'get'
        rel = 'next'
        content = {
            'links': [
                {
                    'rel': 'monitor',
                    'href': '/jobs/jobID'
                }
            ]
        }
        instance = jsonrpc.NefRequest(self.proxy, method)
        result = instance.getpath(content, rel)
        expected = None
        self.assertEqual(expected, result)

    def test_getpath_no_href(self):
        method = 'get'
        rel = 'next'
        content = {
            'links': [
                {
                    'rel': rel
                }
            ]
        }
        instance = jsonrpc.NefRequest(self.proxy, method)
        result = instance.getpath(content, rel)
        expected = None
        self.assertEqual(expected, result)


class TestNefCollections(test.TestCase):

    def setUp(self):
        super(TestNefCollections, self).setUp()
        self.proxy = mock.Mock()
        self.instance = jsonrpc.NefCollections(self.proxy)

    def test_path(self):
        path = 'path/to/item name + - & # $ = 0'
        result = self.instance.path(path)
        quoted_path = six.moves.urllib.parse.quote_plus(path)
        expected = posixpath.join(self.instance.root, quoted_path)
        self.assertEqual(expected, result)

    def test_get(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = {'name': 'dataset'}
        path = self.instance.path(name)
        self.proxy.get.return_value = expected
        result = self.instance.get(name, payload)
        self.proxy.get.assert_called_with(path, payload)
        self.assertEqual(expected, result)

    def test_set(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = None
        path = self.instance.path(name)
        self.proxy.put.return_value = expected
        result = self.instance.set(name, payload)
        self.proxy.put.assert_called_with(path, payload)
        self.assertEqual(expected, result)

    def test_list(self):
        payload = {'key': 'value'}
        expected = [{'name': 'dataset'}]
        self.proxy.get.return_value = expected
        result = self.instance.list(payload)
        self.proxy.get.assert_called_with(self.instance.root, payload)
        self.assertEqual(expected, result)

    def test_create(self):
        payload = {'key': 'value'}
        expected = None
        self.proxy.post.return_value = expected
        result = self.instance.create(payload)
        self.proxy.post.assert_called_with(self.instance.root, payload)
        self.assertEqual(expected, result)

    def test_create_exist(self):
        payload = {'key': 'value'}
        expected = None
        self.proxy.post.side_effect = jsonrpc.NefException(code='EEXIST')
        result = self.instance.create(payload)
        self.proxy.post.assert_called_with(self.instance.root, payload)
        self.assertEqual(expected, result)

    def test_create_error(self):
        payload = {'key': 'value'}
        self.proxy.post.side_effect = jsonrpc.NefException(code='EBUSY')
        self.assertRaises(jsonrpc.NefException, self.instance.create, payload)
        self.proxy.post.assert_called_with(self.instance.root, payload)

    def test_delete(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = None
        path = self.instance.path(name)
        self.proxy.delete.return_value = expected
        result = self.instance.delete(name, payload)
        self.proxy.delete.assert_called_with(path, payload)
        self.assertEqual(expected, result)

    def test_delete_not_found(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = None
        path = self.instance.path(name)
        self.proxy.delete.side_effect = jsonrpc.NefException(code='ENOENT')
        result = self.instance.delete(name, payload)
        self.proxy.delete.assert_called_with(path, payload)
        self.assertEqual(expected, result)

    def test_delete_error(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        path = self.instance.path(name)
        self.proxy.delete.side_effect = jsonrpc.NefException(code='EINVAL')
        self.assertRaises(jsonrpc.NefException, self.instance.delete, name,
                          payload)
        self.proxy.delete.assert_called_with(path, payload)


class TestNefSettings(test.TestCase):

    def setUp(self):
        super(TestNefSettings, self).setUp()
        self.proxy = mock.Mock()
        self.instance = jsonrpc.NefSettings(self.proxy)

    def test_create(self):
        payload = {'key': 'value'}
        result = self.instance.create(payload)
        expected = NotImplemented
        self.assertEqual(expected, result)

    def test_delete(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        result = self.instance.delete(name, payload)
        expected = NotImplemented
        self.assertEqual(expected, result)


class TestNefDatasets(test.TestCase):

    def setUp(self):
        super(TestNefDatasets, self).setUp()
        self.proxy = mock.Mock()
        self.instance = jsonrpc.NefDatasets(self.proxy)

    def test_rename(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = None
        path = self.instance.path(name)
        path = posixpath.join(path, 'rename')
        self.proxy.post.return_value = expected
        result = self.instance.rename(name, payload)
        self.proxy.post.assert_called_with(path, payload)
        self.assertEqual(expected, result)


class TestNefSnapshots(test.TestCase):

    def setUp(self):
        super(TestNefSnapshots, self).setUp()
        self.proxy = mock.Mock()
        self.instance = jsonrpc.NefSnapshots(self.proxy)

    def test_clone(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = None
        path = self.instance.path(name)
        path = posixpath.join(path, 'clone')
        self.proxy.post.return_value = expected
        result = self.instance.clone(name, payload)
        self.proxy.post.assert_called_with(path, payload)
        self.assertEqual(expected, result)


class TestNefVolumeGroups(test.TestCase):

    def setUp(self):
        super(TestNefVolumeGroups, self).setUp()
        self.proxy = mock.Mock()
        self.instance = jsonrpc.NefVolumeGroups(self.proxy)

    def test_rollback(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = None
        path = self.instance.path(name)
        path = posixpath.join(path, 'rollback')
        self.proxy.post.return_value = expected
        result = self.instance.rollback(name, payload)
        self.proxy.post.assert_called_with(path, payload)
        self.assertEqual(expected, result)


class TestNefVolumes(test.TestCase):

    def setUp(self):
        super(TestNefVolumes, self).setUp()
        self.proxy = mock.Mock()
        self.instance = jsonrpc.NefVolumes(self.proxy)

    def test_promote(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = None
        path = self.instance.path(name)
        path = posixpath.join(path, 'promote')
        self.proxy.post.return_value = expected
        result = self.instance.promote(name, payload)
        self.proxy.post.assert_called_with(path, payload)
        self.assertEqual(expected, result)


class TestNefFilesystems(test.TestCase):

    def setUp(self):
        super(TestNefFilesystems, self).setUp()
        self.proxy = mock.Mock()
        self.instance = jsonrpc.NefFilesystems(self.proxy)

    def test_mount(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = None
        path = self.instance.path(name)
        path = posixpath.join(path, 'mount')
        self.proxy.post.return_value = expected
        result = self.instance.mount(name, payload)
        self.proxy.post.assert_called_with(path, payload)
        self.assertEqual(expected, result)

    def test_unmount(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = None
        path = self.instance.path(name)
        path = posixpath.join(path, 'unmount')
        self.proxy.post.return_value = expected
        result = self.instance.unmount(name, payload)
        self.proxy.post.assert_called_with(path, payload)
        self.assertEqual(expected, result)

    def test_acl(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = None
        path = self.instance.path(name)
        path = posixpath.join(path, 'acl')
        self.proxy.post.return_value = expected
        result = self.instance.acl(name, payload)
        self.proxy.post.assert_called_with(path, payload)
        self.assertEqual(expected, result)


class TestNefHpr(test.TestCase):

    def setUp(self):
        super(TestNefHpr, self).setUp()
        self.proxy = mock.Mock()
        self.instance = jsonrpc.NefHpr(self.proxy)

    def test_activate(self):
        payload = {'key': 'value'}
        expected = None
        path = posixpath.join(self.instance.root, 'activate')
        self.proxy.post.return_value = expected
        result = self.instance.activate(payload)
        self.proxy.post.assert_called_with(path, payload)
        self.assertEqual(expected, result)

    def test_start(self):
        name = 'parent/child'
        payload = {'key': 'value'}
        expected = None
        path = posixpath.join(self.instance.path(name), 'start')
        self.proxy.post.return_value = expected
        result = self.instance.start(name, payload)
        self.proxy.post.assert_called_with(path, payload)
        self.assertEqual(expected, result)


class TestNefProxy(test.TestCase):

    def setUp(self):
        super(TestNefProxy, self).setUp()
        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.nexenta_use_https = True
        self.cfg.driver_ssl_cert_verify = True
        self.cfg.nexenta_user = 'user'
        self.cfg.nexenta_password = 'pass'
        self.cfg.nexenta_rest_address = '1.1.1.1,2.2.2.2'
        self.cfg.nexenta_rest_port = 8443
        self.cfg.nexenta_rest_backoff_factor = 1
        self.cfg.nexenta_rest_retry_count = 3
        self.cfg.nexenta_rest_connect_timeout = 1
        self.cfg.nexenta_rest_read_timeout = 1
        self.cfg.nas_host = '3.3.3.3'
        self.cfg.nas_share_path = 'pool/path/to/share'
        self.nef_mock = mock.Mock()
        self.mock_object(jsonrpc, 'NefRequest',
                         return_value=self.nef_mock)

        self.proto = 'nfs'
        self.proxy = jsonrpc.NefProxy(self.proto,
                                      self.cfg.nas_share_path,
                                      self.cfg)

    def test___init___http(self):
        proto = 'nfs'
        cfg = copy.copy(self.cfg)
        cfg.nexenta_use_https = False
        result = jsonrpc.NefProxy(proto, cfg.nas_share_path, cfg)
        self.assertIsInstance(result, jsonrpc.NefProxy)

    def test___init___no_rest_port_http(self):
        proto = 'nfs'
        cfg = copy.copy(self.cfg)
        cfg.nexenta_rest_port = 0
        cfg.nexenta_use_https = False
        result = jsonrpc.NefProxy(proto, cfg.nas_share_path, cfg)
        self.assertIsInstance(result, jsonrpc.NefProxy)

    def test___init___no_rest_port_https(self):
        proto = 'nfs'
        cfg = copy.copy(self.cfg)
        cfg.nexenta_rest_port = 0
        cfg.nexenta_use_https = True
        result = jsonrpc.NefProxy(proto, cfg.nas_share_path, cfg)
        self.assertIsInstance(result, jsonrpc.NefProxy)

    def test___init___iscsi(self):
        proto = 'iscsi'
        cfg = copy.copy(self.cfg)
        result = jsonrpc.NefProxy(proto, cfg.nas_share_path, cfg)
        self.assertIsInstance(result, jsonrpc.NefProxy)

    def test___init___nfs_no_rest_address(self):
        proto = 'nfs'
        cfg = copy.copy(self.cfg)
        cfg.nexenta_rest_address = ''
        result = jsonrpc.NefProxy(proto, cfg.nas_share_path, cfg)
        self.assertIsInstance(result, jsonrpc.NefProxy)

    def test___init___iscsi_no_rest_address(self):
        proto = 'iscsi'
        cfg = copy.copy(self.cfg)
        cfg.nexenta_rest_address = ''
        cfg.nexenta_host = '4.4.4.4'
        result = jsonrpc.NefProxy(proto, cfg.nas_share_path, cfg)
        self.assertIsInstance(result, jsonrpc.NefProxy)

    def test___init___invalid_storage_protocol(self):
        proto = 'invalid'
        cfg = copy.copy(self.cfg)
        self.assertRaises(jsonrpc.NefException, jsonrpc.NefProxy,
                          proto, cfg.nas_share_path, cfg)

    @mock.patch('requests.packages.urllib3.disable_warnings')
    def test___init___no_ssl_cert_verify(self, disable_warnings):
        proto = 'nfs'
        cfg = copy.copy(self.cfg)
        cfg.driver_ssl_cert_verify = False
        disable_warnings.return_value = None
        result = jsonrpc.NefProxy(proto, cfg.nas_share_path, cfg)
        disable_warnings.assert_called()
        self.assertIsInstance(result, jsonrpc.NefProxy)

    def test_delete_bearer(self):
        self.assertIsNone(self.proxy.delete_bearer())
        self.assertNotIn('Authorization', self.proxy.session.headers)
        self.proxy.session.headers['Authorization'] = 'Bearer token'
        self.assertIsNone(self.proxy.delete_bearer())
        self.assertNotIn('Authorization', self.proxy.session.headers)

    def test_update_bearer(self):
        token = 'token'
        bearer = 'Bearer %s' % token
        self.assertNotIn('Authorization', self.proxy.session.headers)
        self.assertIsNone(self.proxy.update_bearer(token))
        self.assertIn('Authorization', self.proxy.session.headers)
        self.assertEqual(self.proxy.session.headers['Authorization'], bearer)

    def test_update_token(self):
        token = 'token'
        bearer = 'Bearer %s' % token
        self.assertIsNone(self.proxy.update_token(token))
        self.assertEqual(self.proxy.tokens[self.proxy.host], token)
        self.assertEqual(self.proxy.session.headers['Authorization'], bearer)

    def test_update_host(self):
        token = 'token'
        bearer = 'Bearer %s' % token
        host = self.cfg.nexenta_rest_address
        self.proxy.tokens[host] = token
        self.assertIsNone(self.proxy.update_host(host))
        self.assertEqual(self.proxy.session.headers['Authorization'], bearer)

    def test_skip_update_host(self):
        host = 'nonexistent'
        self.assertIsNone(self.proxy.update_host(host))

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSettings.get')
    def test_update_lock(self, get_settings):
        guid = uuid.uuid4().hex
        settings = {'value': guid}
        get_settings.return_value = settings
        self.assertIsNone(self.proxy.update_lock())
        path = '%s:%s' % (guid, self.proxy.path)
        if isinstance(path, six.text_type):
            path = path.encode('utf-8')
        expected = md5(path, usedforsecurity=False).hexdigest()
        self.assertEqual(expected, self.proxy.lock)

    def test_url(self):
        path = '/path/to/api'
        result = self.proxy.url(path)
        expected = '%s://%s:%s%s' % (self.proxy.scheme,
                                     self.proxy.host,
                                     self.proxy.port,
                                     path)
        self.assertEqual(expected, result)

    @mock.patch('eventlet.greenthread.sleep')
    def test_delay(self, sleep):
        sleep.return_value = None
        for attempt in range(0, 10):
            expected = int(self.proxy.backoff_factor * (2 ** (attempt - 1)))
            self.assertIsNone(self.proxy.delay(attempt))
            sleep.assert_called_with(expected)
