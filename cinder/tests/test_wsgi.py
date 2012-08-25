# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Unit tests for `cinder.wsgi`."""

import os.path
import tempfile

import unittest
import webob.dec

from cinder.api import openstack as openstack_api
from cinder import exception
from cinder.volume import xiv
from cinder import test
import cinder.wsgi


class TestLoaderNothingExists(test.TestCase):
    """Loader tests where os.path.exists always returns False."""

    def setUp(self):
        super(TestLoaderNothingExists, self).setUp()
        self.stubs.Set(os.path, 'exists', lambda _: False)

    def test_config_not_found(self):
        self.assertRaises(
            cinder.exception.ConfigNotFound,
            cinder.wsgi.Loader,
        )


class TestLoaderNormalFilesystem(unittest.TestCase):
    """Loader tests with normal filesystem (unmodified os.path module)."""

    _paste_config = """
[app:test_app]
use = egg:Paste#static
document_root = /tmp
    """

    def setUp(self):
        self.config = tempfile.NamedTemporaryFile(mode="w+t")
        self.config.write(self._paste_config.lstrip())
        self.config.seek(0)
        self.config.flush()
        self.loader = cinder.wsgi.Loader(self.config.name)

    def test_config_found(self):
        self.assertEquals(self.config.name, self.loader.config_path)

    def test_app_not_found(self):
        self.assertRaises(
            cinder.exception.PasteAppNotFound,
            self.loader.load_app,
            "non-existent app",
        )

    def test_app_found(self):
        url_parser = self.loader.load_app("test_app")
        self.assertEquals("/tmp", url_parser.directory)

    def tearDown(self):
        self.config.close()


class TestWSGIServer(unittest.TestCase):
    """WSGI server tests."""

    def test_no_app(self):
        server = cinder.wsgi.Server("test_app", None)
        self.assertEquals("test_app", server.name)

    def test_start_random_port(self):
        server = cinder.wsgi.Server("test_random_port", None, host="127.0.0.1")
        self.assertEqual(0, server.port)
        server.start()
        self.assertNotEqual(0, server.port)
        server.stop()
        server.wait()


class ExceptionTest(test.TestCase):

    def _wsgi_app(self, inner_app):
        return openstack_api.FaultWrapper(inner_app)

    def _do_test_exception_safety_reflected_in_faults(self, expose):
        class ExceptionWithSafety(exception.CinderException):
            safe = expose

        @webob.dec.wsgify
        def fail(req):
            raise ExceptionWithSafety('some explanation')

        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/').get_response(api)
        self.assertTrue('{"computeFault' in resp.body, resp.body)
        expected = ('ExceptionWithSafety: some explanation' if expose else
                    'The server has either erred or is incapable '
                    'of performing the requested operation.')
        self.assertTrue(expected in resp.body, resp.body)
        self.assertEqual(resp.status_int, 500, resp.body)

    def test_safe_exceptions_are_described_in_faults(self):
        self._do_test_exception_safety_reflected_in_faults(True)

    def test_unsafe_exceptions_are_not_described_in_faults(self):
        self._do_test_exception_safety_reflected_in_faults(False)

    def _do_test_exception_mapping(self, exception_type, msg):
        @webob.dec.wsgify
        def fail(req):
            raise exception_type(msg)

        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/').get_response(api)
        self.assertTrue(msg in resp.body, resp.body)
        self.assertEqual(resp.status_int, exception_type.code, resp.body)

        if hasattr(exception_type, 'headers'):
            for (key, value) in exception_type.headers.iteritems():
                self.assertTrue(key in resp.headers)
                self.assertEquals(resp.headers[key], value)

    def test_quota_error_mapping(self):
        self._do_test_exception_mapping(exception.QuotaError, 'too many used')

    def test_non_cinder_notfound_exception_mapping(self):
        class ExceptionWithCode(Exception):
            code = 404

        self._do_test_exception_mapping(ExceptionWithCode,
                                        'NotFound')

    def test_non_cinder_exception_mapping(self):
        class ExceptionWithCode(Exception):
            code = 417

        self._do_test_exception_mapping(ExceptionWithCode,
                                        'Expectation failed')

    def test_exception_with_none_code_throws_500(self):
        class ExceptionWithNoneCode(Exception):
            code = None

        msg = 'Internal Server Error'

        @webob.dec.wsgify
        def fail(req):
            raise ExceptionWithNoneCode()

        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/').get_response(api)
        self.assertEqual(500, resp.status_int)
