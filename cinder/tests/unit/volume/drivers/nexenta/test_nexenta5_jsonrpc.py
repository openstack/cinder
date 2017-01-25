# Copyright 2016 Nexenta Systems, Inc.
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
Unit tests for NexentaStor 5 REST API helper
"""

import uuid

import mock
from mock import patch
from oslo_serialization import jsonutils
import requests
from requests import adapters
from six.moves import http_client

from cinder import exception
from cinder import test
from cinder.volume.drivers.nexenta.ns5 import jsonrpc

HOST = '1.1.1.1'
USERNAME = 'user'
PASSWORD = 'pass'


def gen_response(code=http_client.OK, json=None):
    r = requests.Response()
    r.headers['Content-Type'] = 'application/json'
    r.encoding = 'utf8'
    r.status_code = code
    r.reason = 'FAKE REASON'
    r.raw = mock.Mock()
    r._content = ''
    if json:
        r._content = jsonutils.dumps(json)
    return r


class TestNexentaJSONProxyAuth(test.TestCase):

    @patch('cinder.volume.drivers.nexenta.ns5.jsonrpc.requests.post')
    def test_https_auth(self, post):
        use_https = True
        port = 8443
        auth_uri = 'auth/login'
        rnd_url = 'some/random/url'

        class PostSideEffect(object):
            def __call__(self, *args, **kwargs):
                r = gen_response()
                if args[0] == '%(scheme)s://%(host)s:%(port)s/%(uri)s' % {
                        'scheme': 'https',
                        'host': HOST,
                        'port': port,
                        'uri': auth_uri}:
                    token = uuid.uuid4().hex
                    content = {'token': token}
                    r._content = jsonutils.dumps(content)
                return r
        post_side_effect = PostSideEffect()
        post.side_effect = post_side_effect

        class TestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(TestAdapter, self).__init__()
                self.counter = 0

            def send(self, request, *args, **kwargs):
                # an url is being requested for the second time
                if self.counter == 1:
                    # make the fake backend respond 401
                    r = gen_response(http_client.UNAUTHORIZED)
                    r._content = ''
                    r.connection = mock.Mock()
                    r_ = gen_response(json={'data': []})
                    r.connection.send = lambda prep, **kwargs_: r_
                else:
                    r = gen_response(json={'data': []})
                r.request = request
                self.counter += 1
                return r

        nef = jsonrpc.NexentaJSONProxy(HOST, port, USERNAME, PASSWORD,
                                       use_https)
        adapter = TestAdapter()
        nef.session.mount(
            '%(scheme)s://%(host)s:%(port)s/%(uri)s' % {
                'scheme': 'https',
                'host': HOST,
                'port': port,
                'uri': rnd_url},
            adapter)

        # successful authorization
        self.assertEqual({'data': []}, nef.get(rnd_url))

        # session timeout simulation. Client must authenticate newly
        self.assertEqual({'data': []}, nef.get(rnd_url))
        # auth URL must be requested two times at this moment
        self.assertEqual(2, post.call_count)

        # continue with the last (second) token
        self.assertEqual(nef.get(rnd_url), {'data': []})
        # auth URL must be requested two times
        self.assertEqual(2, post.call_count)


class TestNexentaJSONProxy(test.TestCase):

    def setUp(self):
        super(TestNexentaJSONProxy, self).setUp()
        self.nef = jsonrpc.NexentaJSONProxy(HOST, 0, USERNAME, PASSWORD, False)

    def gen_adapter(self, code, json=None):
        class TestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(TestAdapter, self).__init__()

            def send(self, request, *args, **kwargs):
                r = gen_response(code, json)
                r.request = request
                return r

        return TestAdapter()

    def _mount_adapter(self, url, adapter):
        self.nef.session.mount(
            '%(scheme)s://%(host)s:%(port)s/%(uri)s' % {
                'scheme': 'http',
                'host': HOST,
                'port': 8080,
                'uri': url},
            adapter)

    def test_post(self):
        random_dict = {'data': uuid.uuid4().hex}
        rnd_url = 'some/random/url'
        self._mount_adapter(rnd_url, self.gen_adapter(http_client.CREATED,
                                                      random_dict))
        self.assertEqual(random_dict, self.nef.post(rnd_url))

    def test_delete(self):
        random_dict = {'data': uuid.uuid4().hex}
        rnd_url = 'some/random/url'
        self._mount_adapter(rnd_url, self.gen_adapter(http_client.CREATED,
                                                      random_dict))
        self.assertEqual(random_dict, self.nef.delete(rnd_url))

    def test_put(self):
        random_dict = {'data': uuid.uuid4().hex}
        rnd_url = 'some/random/url'
        self._mount_adapter(rnd_url, self.gen_adapter(http_client.CREATED,
                                                      random_dict))
        self.assertEqual(random_dict, self.nef.put(rnd_url))

    def test_get_200(self):
        random_dict = {'data': uuid.uuid4().hex}
        rnd_url = 'some/random/url'
        self._mount_adapter(rnd_url, self.gen_adapter(http_client.OK,
                                                      random_dict))
        self.assertEqual(random_dict, self.nef.get(rnd_url))

    def test_get_201(self):
        random_dict = {'data': uuid.uuid4().hex}
        rnd_url = 'some/random/url'
        self._mount_adapter(rnd_url, self.gen_adapter(http_client.CREATED,
                                                      random_dict))
        self.assertEqual(random_dict, self.nef.get(rnd_url))

    def test_get_500(self):
        class TestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(TestAdapter, self).__init__()

            def send(self, request, *args, **kwargs):
                json = {
                    'code': 'NEF_ERROR',
                    'message': 'Some error'
                }
                r = gen_response(http_client.INTERNAL_SERVER_ERROR, json)
                r.request = request
                return r

        adapter = TestAdapter()
        rnd_url = 'some/random/url'
        self._mount_adapter(rnd_url, adapter)
        self.assertRaises(exception.NexentaException, self.nef.get, rnd_url)

    def test_get__not_nef_error(self):
        class TestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(TestAdapter, self).__init__()

            def send(self, request, *args, **kwargs):
                r = gen_response(http_client.NOT_FOUND)
                r._content = 'Page Not Found'
                r.request = request
                return r

        adapter = TestAdapter()
        rnd_url = 'some/random/url'
        self._mount_adapter(rnd_url, adapter)
        self.assertRaises(exception.VolumeBackendAPIException, self.nef.get,
                          rnd_url)

    def test_get__not_nef_error_empty_body(self):
        class TestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(TestAdapter, self).__init__()

            def send(self, request, *args, **kwargs):
                r = gen_response(http_client.NOT_FOUND)
                r.request = request
                return r

        adapter = TestAdapter()
        rnd_url = 'some/random/url'
        self._mount_adapter(rnd_url, adapter)
        self.assertRaises(exception.VolumeBackendAPIException, self.nef.get,
                          rnd_url)

    def test_202(self):
        redirect_url = 'redirect/url'

        class RedirectTestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(RedirectTestAdapter, self).__init__()

            def send(self, request, *args, **kwargs):
                json = {
                    'links': [{'href': redirect_url}]
                }
                r = gen_response(http_client.ACCEPTED, json)
                r.request = request
                return r

        rnd_url = 'some/random/url'
        self._mount_adapter(rnd_url, RedirectTestAdapter())
        self._mount_adapter(redirect_url, self.gen_adapter(
            http_client.CREATED))
        self.assertIsNone(self.nef.get(rnd_url))
