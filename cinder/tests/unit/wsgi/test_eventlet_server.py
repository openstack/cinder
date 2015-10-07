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
import re
import socket
import ssl
import tempfile
import time

import mock
from oslo_config import cfg
from oslo_i18n import fixture as i18n_fixture
import six
from six.moves import urllib
import testtools
import webob
import webob.dec

from cinder import exception
from cinder.i18n import _
from cinder import test
from cinder.wsgi import common as wsgi_common
from cinder.wsgi import eventlet_server as wsgi

CONF = cfg.CONF

TEST_VAR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__),
                               '../var'))


def open_no_proxy(*args, **kwargs):
    # NOTE(coreycb):
    # Deal with more secure certification chain verficiation
    # introduced in python 2.7.9 under PEP-0476
    # https://github.com/python/peps/blob/master/pep-0476.txt
    if hasattr(ssl, "_create_unverified_context"):
        context = ssl._create_unverified_context()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context)
        )
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(*args, **kwargs)


class TestLoaderNothingExists(test.TestCase):
    """Loader tests where os.path.exists always returns False."""

    def setUp(self):
        super(TestLoaderNothingExists, self).setUp()
        self.stubs.Set(os.path, 'exists', lambda _: False)

    def test_config_not_found(self):
        self.assertRaises(
            exception.ConfigNotFound,
            wsgi_common.Loader,
        )


class TestLoaderNormalFilesystem(test.TestCase):
    """Loader tests with normal filesystem (unmodified os.path module)."""

    _paste_config = """
[app:test_app]
use = egg:Paste#static
document_root = /tmp
    """

    def setUp(self):
        super(TestLoaderNormalFilesystem, self).setUp()
        self.config = tempfile.NamedTemporaryFile(mode="w+t")
        self.config.write(self._paste_config.lstrip())
        self.config.seek(0)
        self.config.flush()
        self.loader = wsgi_common.Loader(self.config.name)
        self.addCleanup(self.config.close)

    def test_config_found(self):
        self.assertEqual(self.config.name, self.loader.config_path)

    def test_app_not_found(self):
        self.assertRaises(
            exception.PasteAppNotFound,
            self.loader.load_app,
            "non-existent app",
        )

    def test_app_found(self):
        url_parser = self.loader.load_app("test_app")
        self.assertEqual("/tmp", url_parser.directory)


class TestWSGIServer(test.TestCase):
    """WSGI server tests."""
    def _ipv6_configured():
        try:
            with open('/proc/net/if_inet6') as f:
                return len(f.read()) > 0
        except IOError:
            return False

    def test_no_app(self):
        server = wsgi.Server("test_app", None,
                             host="127.0.0.1", port=0)
        self.assertEqual("test_app", server.name)

    def test_start_random_port(self):
        server = wsgi.Server("test_random_port", None, host="127.0.0.1")
        server.start()
        self.assertNotEqual(0, server.port)
        server.stop()
        server.wait()

    @testtools.skipIf(not _ipv6_configured(),
                      "Test requires an IPV6 configured interface")
    def test_start_random_port_with_ipv6(self):
        server = wsgi.Server("test_random_port",
                             None,
                             host="::1")
        server.start()
        self.assertEqual("::1", server.host)
        self.assertNotEqual(0, server.port)
        server.stop()
        server.wait()

    def test_server_pool_waitall(self):
        # test pools waitall method gets called while stopping server
        server = wsgi.Server("test_server", None,
                             host="127.0.0.1")
        server.start()
        with mock.patch.object(server._pool,
                               'waitall') as mock_waitall:
            server.stop()
            server.wait()
            mock_waitall.assert_called_once_with()

    def test_app(self):
        greetings = b'Hello, World!!!'

        def hello_world(env, start_response):
            if env['PATH_INFO'] != '/':
                start_response('404 Not Found',
                               [('Content-Type', 'text/plain')])
                return ['Not Found\r\n']
            start_response('200 OK', [('Content-Type', 'text/plain')])
            return [greetings]

        server = wsgi.Server("test_app", hello_world,
                             host="127.0.0.1", port=0)
        server.start()

        response = open_no_proxy('http://127.0.0.1:%d/' % server.port)
        self.assertEqual(greetings, response.read())
        server.stop()

    def test_client_socket_timeout(self):
        CONF.set_default("client_socket_timeout", 0.1)
        greetings = b'Hello, World!!!'

        def hello_world(env, start_response):
            start_response('200 OK', [('Content-Type', 'text/plain')])
            return [greetings]

        server = wsgi.Server("test_app", hello_world,
                             host="127.0.0.1", port=0)
        server.start()

        s = socket.socket()
        s.connect(("127.0.0.1", server.port))

        fd = s.makefile('rwb')
        fd.write(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n')
        fd.flush()

        buf = fd.read()
        self.assertTrue(re.search(greetings, buf))

        s2 = socket.socket()
        s2.connect(("127.0.0.1", server.port))
        time.sleep(0.2)

        fd = s2.makefile('rwb')
        fd.write(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n')
        fd.flush()

        buf = fd.read()
        # connection is closed so we get nothing from the server
        self.assertFalse(buf)
        server.stop()

    @testtools.skipIf(six.PY3, "bug/1505103: test hangs on Python 3")
    def test_app_using_ssl(self):
        CONF.set_default("ssl_cert_file",
                         os.path.join(TEST_VAR_DIR, 'certificate.crt'))
        CONF.set_default("ssl_key_file",
                         os.path.join(TEST_VAR_DIR, 'privatekey.key'))

        greetings = 'Hello, World!!!'

        @webob.dec.wsgify
        def hello_world(req):
            return greetings

        server = wsgi.Server("test_app", hello_world,
                             host="127.0.0.1", port=0)

        server.start()

        response = open_no_proxy('https://127.0.0.1:%d/' % server.port)
        self.assertEqual(greetings, response.read())

        server.stop()

    @testtools.skipIf(not _ipv6_configured(),
                      "Test requires an IPV6 configured interface")
    @testtools.skipIf(six.PY3, "bug/1505103: test hangs on Python 3")
    def test_app_using_ipv6_and_ssl(self):
        CONF.set_default("ssl_cert_file",
                         os.path.join(TEST_VAR_DIR, 'certificate.crt'))
        CONF.set_default("ssl_key_file",
                         os.path.join(TEST_VAR_DIR, 'privatekey.key'))

        greetings = 'Hello, World!!!'

        @webob.dec.wsgify
        def hello_world(req):
            return greetings

        server = wsgi.Server("test_app",
                             hello_world,
                             host="::1",
                             port=0)
        server.start()

        response = open_no_proxy('https://[::1]:%d/' % server.port)
        self.assertEqual(greetings, response.read())

        server.stop()

    def test_reset_pool_size_to_default(self):
        server = wsgi.Server("test_resize", None, host="127.0.0.1")
        server.start()

        # Stopping the server, which in turn sets pool size to 0
        server.stop()
        self.assertEqual(0, server._pool.size)

        # Resetting pool size to default
        server.reset()
        server.start()
        self.assertEqual(1000, server._pool.size)


class ExceptionTest(test.TestCase):

    def setUp(self):
        super(ExceptionTest, self).setUp()
        self.useFixture(i18n_fixture.ToggleLazy(True))

    def _wsgi_app(self, inner_app):
        # NOTE(luisg): In order to test localization, we need to
        # make sure the lazy _() is installed in the 'fault' module
        # also we don't want to install the _() system-wide and
        # potentially break other test cases, so we do it here for this
        # test suite only.
        from cinder.api.middleware import fault
        return fault.FaultWrapper(inner_app)

    def _do_test_exception_safety_reflected_in_faults(self, expose):
        class ExceptionWithSafety(exception.CinderException):
            safe = expose

        @webob.dec.wsgify
        def fail(req):
            raise ExceptionWithSafety('some explanation')

        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/').get_response(api)
        self.assertIn(b'{"computeFault', resp.body)
        expected = (b'ExceptionWithSafety: some explanation' if expose else
                    b'The server has either erred or is incapable '
                    b'of performing the requested operation.')
        self.assertIn(expected, resp.body)
        self.assertEqual(500, resp.status_int, resp.body)

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
        msg_body = (msg.encode('utf-8') if isinstance(msg, six.text_type)
                    else msg)
        self.assertIn(msg_body, resp.body)
        self.assertEqual(exception_type.code, resp.status_int, resp.body)

        if hasattr(exception_type, 'headers'):
            for (key, value) in exception_type.headers.items():
                self.assertIn(key, resp.headers)
                self.assertEqual(resp.headers[key], value)

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

        @webob.dec.wsgify
        def fail(req):
            raise ExceptionWithNoneCode()

        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/').get_response(api)
        self.assertEqual(500, resp.status_int)

    @mock.patch('cinder.i18n.translate')
    def test_cinder_exception_with_localized_explanation(self, mock_t9n):
        msg = 'My Not Found'
        msg_translation = 'Mi No Encontrado'
        message = _(msg)  # noqa

        @webob.dec.wsgify
        def fail(req):
            class MyVolumeNotFound(exception.NotFound):
                def __init__(self):
                    self.msg = message
                    self.safe = True
            raise MyVolumeNotFound()

        # Test response without localization
        def mock_get_non_localized_message(msgid, locale):
            return msg

        mock_t9n.side_effect = mock_get_non_localized_message

        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/').get_response(api)
        self.assertEqual(404, resp.status_int)
        msg_body = (msg.encode('utf-8') if isinstance(msg, six.text_type)
                    else msg)
        self.assertIn(msg_body, resp.body)

        # Test response with localization
        def mock_translate(msgid, locale):
            return msg_translation

        mock_t9n.side_effect = mock_translate

        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/').get_response(api)
        self.assertEqual(404, resp.status_int)
        if isinstance(msg_translation, six.text_type):
            msg_body = msg_translation.encode('utf-8')
        else:
            msg_body = msg_translation
        self.assertIn(msg_body, resp.body)
