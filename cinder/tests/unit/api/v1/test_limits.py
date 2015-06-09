# Copyright 2011 OpenStack Foundation
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
Tests dealing with HTTP rate-limiting.
"""

import httplib
from xml.dom import minidom

from lxml import etree
from oslo_serialization import jsonutils
import six
import webob

from cinder.api.v1 import limits
from cinder.api import views
from cinder.api import xmlutil
import cinder.context
from cinder import test


TEST_LIMITS = [
    limits.Limit("GET", "/delayed", "^/delayed", 1, limits.PER_MINUTE),
    limits.Limit("POST", "*", ".*", 7, limits.PER_MINUTE),
    limits.Limit("POST", "/volumes", "^/volumes", 3, limits.PER_MINUTE),
    limits.Limit("PUT", "*", "", 10, limits.PER_MINUTE),
    limits.Limit("PUT", "/volumes", "^/volumes", 5, limits.PER_MINUTE),
]
NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'ns': 'http://docs.openstack.org/common/api/v1.0'
}


class BaseLimitTestSuite(test.TestCase):
    """Base test suite which provides relevant stubs and time abstraction."""

    def setUp(self):
        super(BaseLimitTestSuite, self).setUp()
        self.time = 0.0
        self.stubs.Set(limits.Limit, "_get_time", self._get_time)
        self.absolute_limits = {}

        def stub_get_project_quotas(context, project_id, usages=True):
            return {k: dict(limit=v) for k, v in self.absolute_limits.items()}

        self.stubs.Set(cinder.quota.QUOTAS, "get_project_quotas",
                       stub_get_project_quotas)

    def _get_time(self):
        """Return the "time" according to this test suite."""
        return self.time


class LimitsControllerTest(BaseLimitTestSuite):
    """Tests for `limits.LimitsController` class."""

    def setUp(self):
        """Run before each test."""
        super(LimitsControllerTest, self).setUp()
        self.controller = limits.create_resource()

    def _get_index_request(self, accept_header="application/json"):
        """Helper to set routing arguments."""
        request = webob.Request.blank("/")
        request.accept = accept_header
        request.environ["wsgiorg.routing_args"] = (None, {
            "action": "index",
            "controller": "",
        })
        context = cinder.context.RequestContext('testuser', 'testproject')
        request.environ["cinder.context"] = context
        return request

    def _populate_limits(self, request):
        """Put limit info into a request."""
        _limits = [
            limits.Limit("GET", "*", ".*", 10, 60).display(),
            limits.Limit("POST", "*", ".*", 5, 60 * 60).display(),
            limits.Limit("GET", "changes-since*", "changes-since",
                         5, 60).display(),
        ]
        request.environ["cinder.limits"] = _limits
        return request

    def test_empty_index_json(self):
        """Test getting empty limit details in JSON."""
        request = self._get_index_request()
        response = request.get_response(self.controller)
        expected = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        body = jsonutils.loads(response.body)
        self.assertEqual(expected, body)

    def test_index_json(self):
        """Test getting limit details in JSON."""
        request = self._get_index_request()
        request = self._populate_limits(request)
        self.absolute_limits = {
            'gigabytes': 512,
            'volumes': 5,
        }
        response = request.get_response(self.controller)
        expected = {
            "limits": {
                "rate": [
                    {
                        "regex": ".*",
                        "uri": "*",
                        "limit": [
                            {
                                "verb": "GET",
                                "next-available": "1970-01-01T00:00:00",
                                "unit": "MINUTE",
                                "value": 10,
                                "remaining": 10,
                            },
                            {
                                "verb": "POST",
                                "next-available": "1970-01-01T00:00:00",
                                "unit": "HOUR",
                                "value": 5,
                                "remaining": 5,
                            },
                        ],
                    },
                    {
                        "regex": "changes-since",
                        "uri": "changes-since*",
                        "limit": [
                            {
                                "verb": "GET",
                                "next-available": "1970-01-01T00:00:00",
                                "unit": "MINUTE",
                                "value": 5,
                                "remaining": 5,
                            },
                        ],
                    },

                ],
                "absolute": {"maxTotalVolumeGigabytes": 512,
                             "maxTotalVolumes": 5, },
            },
        }
        body = jsonutils.loads(response.body)
        self.assertEqual(expected, body)

    def _populate_limits_diff_regex(self, request):
        """Put limit info into a request."""
        _limits = [
            limits.Limit("GET", "*", ".*", 10, 60).display(),
            limits.Limit("GET", "*", "*.*", 10, 60).display(),
        ]
        request.environ["cinder.limits"] = _limits
        return request

    def test_index_diff_regex(self):
        """Test getting limit details in JSON."""
        request = self._get_index_request()
        request = self._populate_limits_diff_regex(request)
        response = request.get_response(self.controller)
        expected = {
            "limits": {
                "rate": [
                    {
                        "regex": ".*",
                        "uri": "*",
                        "limit": [
                            {
                                "verb": "GET",
                                "next-available": "1970-01-01T00:00:00",
                                "unit": "MINUTE",
                                "value": 10,
                                "remaining": 10,
                            },
                        ],
                    },
                    {
                        "regex": "*.*",
                        "uri": "*",
                        "limit": [
                            {
                                "verb": "GET",
                                "next-available": "1970-01-01T00:00:00",
                                "unit": "MINUTE",
                                "value": 10,
                                "remaining": 10,
                            },
                        ],
                    },

                ],
                "absolute": {},
            },
        }
        body = jsonutils.loads(response.body)
        self.assertEqual(expected, body)

    def _test_index_absolute_limits_json(self, expected):
        request = self._get_index_request()
        response = request.get_response(self.controller)
        body = jsonutils.loads(response.body)
        self.assertEqual(expected, body['limits']['absolute'])

    def test_index_ignores_extra_absolute_limits_json(self):
        self.absolute_limits = {'unknown_limit': 9001}
        self._test_index_absolute_limits_json({})


class TestLimiter(limits.Limiter):
    pass


class LimitMiddlewareTest(BaseLimitTestSuite):
    """Tests for the `limits.RateLimitingMiddleware` class."""

    @webob.dec.wsgify
    def _empty_app(self, request):
        """Do-nothing WSGI app."""
        pass

    def setUp(self):
        """Prepare middleware for use through fake WSGI app."""
        super(LimitMiddlewareTest, self).setUp()
        _limits = '(GET, *, .*, 1, MINUTE)'
        self.app = limits.RateLimitingMiddleware(self._empty_app, _limits,
                                                 "%s.TestLimiter" %
                                                 self.__class__.__module__)

    def test_limit_class(self):
        """Test that middleware selected correct limiter class."""
        assert isinstance(self.app._limiter, TestLimiter)

    def test_good_request(self):
        """Test successful GET request through middleware."""
        request = webob.Request.blank("/")
        response = request.get_response(self.app)
        self.assertEqual(200, response.status_int)

    def test_limited_request_json(self):
        """Test a rate-limited (413) GET request through middleware."""
        request = webob.Request.blank("/")
        response = request.get_response(self.app)
        self.assertEqual(200, response.status_int)

        request = webob.Request.blank("/")
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 413)

        self.assertIn('Retry-After', response.headers)
        retry_after = int(response.headers['Retry-After'])
        self.assertAlmostEqual(retry_after, 60, 1)

        body = jsonutils.loads(response.body)
        expected = "Only 1 GET request(s) can be made to * every minute."
        value = body["overLimitFault"]["details"].strip()
        self.assertEqual(value, expected)

    def test_limited_request_xml(self):
        """Test a rate-limited (413) response as XML."""
        request = webob.Request.blank("/")
        response = request.get_response(self.app)
        self.assertEqual(200, response.status_int)

        request = webob.Request.blank("/")
        request.accept = "application/xml"
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 413)

        root = minidom.parseString(response.body).childNodes[0]
        expected = "Only 1 GET request(s) can be made to * every minute."

        details = root.getElementsByTagName("details")
        self.assertEqual(details.length, 1)

        value = details.item(0).firstChild.data.strip()
        self.assertEqual(value, expected)


class LimitTest(BaseLimitTestSuite):
    """Tests for the `limits.Limit` class."""

    def test_GET_no_delay(self):
        """Test a limit handles 1 GET per second."""
        limit = limits.Limit("GET", "*", ".*", 1, 1)
        delay = limit("GET", "/anything")
        self.assertIsNone(delay)
        self.assertEqual(0, limit.next_request)
        self.assertEqual(0, limit.last_request)

    def test_GET_delay(self):
        """Test two calls to 1 GET per second limit."""
        limit = limits.Limit("GET", "*", ".*", 1, 1)
        delay = limit("GET", "/anything")
        self.assertIsNone(delay)

        delay = limit("GET", "/anything")
        self.assertEqual(1, delay)
        self.assertEqual(1, limit.next_request)
        self.assertEqual(0, limit.last_request)

        self.time += 4

        delay = limit("GET", "/anything")
        self.assertIsNone(delay)
        self.assertEqual(4, limit.next_request)
        self.assertEqual(4, limit.last_request)


class ParseLimitsTest(BaseLimitTestSuite):
    """Tests for the default limits parser in the `limits.Limiter` class."""

    def test_invalid(self):
        """Test that parse_limits() handles invalid input correctly."""
        self.assertRaises(ValueError, limits.Limiter.parse_limits,
                          ';;;;;')

    def test_bad_rule(self):
        """Test that parse_limits() handles bad rules correctly."""
        self.assertRaises(ValueError, limits.Limiter.parse_limits,
                          'GET, *, .*, 20, minute')

    def test_missing_arg(self):
        """Test that parse_limits() handles missing args correctly."""
        self.assertRaises(ValueError, limits.Limiter.parse_limits,
                          '(GET, *, .*, 20)')

    def test_bad_value(self):
        """Test that parse_limits() handles bad values correctly."""
        self.assertRaises(ValueError, limits.Limiter.parse_limits,
                          '(GET, *, .*, foo, minute)')

    def test_bad_unit(self):
        """Test that parse_limits() handles bad units correctly."""
        self.assertRaises(ValueError, limits.Limiter.parse_limits,
                          '(GET, *, .*, 20, lightyears)')

    def test_multiple_rules(self):
        """Test that parse_limits() handles multiple rules correctly."""
        try:
            l = limits.Limiter.parse_limits('(get, *, .*, 20, minute);'
                                            '(PUT, /foo*, /foo.*, 10, hour);'
                                            '(POST, /bar*, /bar.*, 5, second);'
                                            '(Say, /derp*, /derp.*, 1, day)')
        except ValueError as e:
            assert False, e

        # Make sure the number of returned limits are correct
        self.assertEqual(len(l), 4)

        # Check all the verbs...
        expected = ['GET', 'PUT', 'POST', 'SAY']
        self.assertEqual([t.verb for t in l], expected)

        # ...the URIs...
        expected = ['*', '/foo*', '/bar*', '/derp*']
        self.assertEqual([t.uri for t in l], expected)

        # ...the regexes...
        expected = ['.*', '/foo.*', '/bar.*', '/derp.*']
        self.assertEqual([t.regex for t in l], expected)

        # ...the values...
        expected = [20, 10, 5, 1]
        self.assertEqual([t.value for t in l], expected)

        # ...and the units...
        expected = [limits.PER_MINUTE, limits.PER_HOUR,
                    limits.PER_SECOND, limits.PER_DAY]
        self.assertEqual([t.unit for t in l], expected)


class LimiterTest(BaseLimitTestSuite):
    """Tests for the in-memory `limits.Limiter` class."""

    def setUp(self):
        """Run before each test."""
        super(LimiterTest, self).setUp()
        userlimits = {'limits.user3': '',
                      'limits.user0': '(get, *, .*, 4, minute);'
                                      '(put, *, .*, 2, minute)'}
        self.limiter = limits.Limiter(TEST_LIMITS, **userlimits)

    def _check(self, num, verb, url, username=None):
        """Check and yield results from checks."""
        for x in xrange(num):
            yield self.limiter.check_for_delay(verb, url, username)[0]

    def _check_sum(self, num, verb, url, username=None):
        """Check and sum results from checks."""
        results = self._check(num, verb, url, username)
        return sum(item for item in results if item)

    def test_no_delay_GET(self):
        """no delay on a single call for a limit verb we didn"t set."""
        delay = self.limiter.check_for_delay("GET", "/anything")
        self.assertEqual(delay, (None, None))

    def test_no_delay_PUT(self):
        """no delay on a single call for a known limit."""
        delay = self.limiter.check_for_delay("PUT", "/anything")
        self.assertEqual(delay, (None, None))

    def test_delay_PUT(self):
        """test delay on 11th put request.

        the 11th PUT will result in a delay of 6.0 seconds until
        the next request will be granted.
        """
        expected = [None] * 10 + [6.0]
        results = list(self._check(11, "PUT", "/anything"))

        self.assertEqual(expected, results)

    def test_delay_POST(self):
        """test delay of 8th post request.

        Ensure that the 8th POST will result in a delay of 6.0 seconds
        until the next request will be granted.
        """
        expected = [None] * 7
        results = list(self._check(7, "POST", "/anything"))
        self.assertEqual(expected, results)

        expected = 60.0 / 7.0
        results = self._check_sum(1, "POST", "/anything")
        self.assertAlmostEqual(expected, results, 8)

    def test_delay_GET(self):
        """Ensure the 11th GET will result in NO delay."""
        expected = [None] * 11
        results = list(self._check(11, "GET", "/anything"))
        self.assertEqual(expected, results)

        expected = [None] * 4 + [15.0]
        results = list(self._check(5, "GET", "/foo", "user0"))
        self.assertEqual(expected, results)

    def test_delay_PUT_volumes(self):
        """Test limit of PUT on /volumes.

        Ensure PUT on /volumes limits at 5 requests, and PUT elsewhere is
        still OK after 5 requests...
        but then after 11 total requests, PUT limiting kicks in.
        """
        # First 6 requests on PUT /volumes
        expected = [None] * 5 + [12.0]
        results = list(self._check(6, "PUT", "/volumes"))
        self.assertEqual(expected, results)

        # Next 5 request on PUT /anything
        expected = [None] * 4 + [6.0]
        results = list(self._check(5, "PUT", "/anything"))
        self.assertEqual(expected, results)

    def test_delay_PUT_wait(self):
        """Test limit on PUT is lifted.

        Ensure after hitting the limit and then waiting for the correct
        amount of time, the limit will be lifted.
        """
        expected = [None] * 10 + [6.0]
        results = list(self._check(11, "PUT", "/anything"))
        self.assertEqual(expected, results)

        # Advance time
        self.time += 6.0

        expected = [None, 6.0]
        results = list(self._check(2, "PUT", "/anything"))
        self.assertEqual(expected, results)

    def test_multiple_delays(self):
        """Ensure multiple requests still get a delay."""
        expected = [None] * 10 + [6.0] * 10
        results = list(self._check(20, "PUT", "/anything"))
        self.assertEqual(expected, results)

        self.time += 1.0

        expected = [5.0] * 10
        results = list(self._check(10, "PUT", "/anything"))
        self.assertEqual(expected, results)

        expected = [None] * 2 + [30.0] * 8
        results = list(self._check(10, "PUT", "/anything", "user0"))
        self.assertEqual(expected, results)

    def test_user_limit(self):
        """Test user-specific limits."""
        self.assertEqual(self.limiter.levels['user3'], [])
        self.assertEqual(len(self.limiter.levels['user0']), 2)

    def test_multiple_users(self):
        """Tests involving multiple users."""

        # User0
        expected = [None] * 2 + [30.0] * 8
        results = list(self._check(10, "PUT", "/anything", "user0"))
        self.assertEqual(expected, results)

        # User1
        expected = [None] * 10 + [6.0] * 10
        results = list(self._check(20, "PUT", "/anything", "user1"))
        self.assertEqual(expected, results)

        # User2
        expected = [None] * 10 + [6.0] * 5
        results = list(self._check(15, "PUT", "/anything", "user2"))
        self.assertEqual(expected, results)

        # User3
        expected = [None] * 20
        results = list(self._check(20, "PUT", "/anything", "user3"))
        self.assertEqual(expected, results)

        self.time += 1.0

        # User1 again
        expected = [5.0] * 10
        results = list(self._check(10, "PUT", "/anything", "user1"))
        self.assertEqual(expected, results)

        self.time += 1.0

        # User1 again
        expected = [4.0] * 5
        results = list(self._check(5, "PUT", "/anything", "user2"))
        self.assertEqual(expected, results)

        # User0 again
        expected = [28.0]
        results = list(self._check(1, "PUT", "/anything", "user0"))
        self.assertEqual(expected, results)

        self.time += 28.0

        expected = [None, 30.0]
        results = list(self._check(2, "PUT", "/anything", "user0"))
        self.assertEqual(expected, results)


class WsgiLimiterTest(BaseLimitTestSuite):
    """Tests for `limits.WsgiLimiter` class."""

    def setUp(self):
        """Run before each test."""
        super(WsgiLimiterTest, self).setUp()
        self.app = limits.WsgiLimiter(TEST_LIMITS)

    def _request_data(self, verb, path):
        """Get data describing a limit request verb/path."""
        return jsonutils.dumps({"verb": verb, "path": path})

    def _request(self, verb, url, username=None):
        """Assert that POSTing to given url triggers given action.

        Ensure POSTing to the given url causes the given username
        to perform the given action.

        Make the internal rate limiter return delay and make sure that the
        WSGI app returns the correct response.
        """
        if username:
            request = webob.Request.blank("/%s" % username)
        else:
            request = webob.Request.blank("/")

        request.method = "POST"
        request.body = self._request_data(verb, url)
        response = request.get_response(self.app)

        if "X-Wait-Seconds" in response.headers:
            self.assertEqual(response.status_int, 403)
            return response.headers["X-Wait-Seconds"]

        self.assertEqual(response.status_int, 204)

    def test_invalid_methods(self):
        """Only POSTs should work."""
        for method in ["GET", "PUT", "DELETE", "HEAD", "OPTIONS"]:
            request = webob.Request.blank("/", method=method)
            response = request.get_response(self.app)
            self.assertEqual(response.status_int, 405)

    def test_good_url(self):
        delay = self._request("GET", "/something")
        self.assertIsNone(delay)

    def test_escaping(self):
        delay = self._request("GET", "/something/jump%20up")
        self.assertIsNone(delay)

    def test_response_to_delays(self):
        delay = self._request("GET", "/delayed")
        self.assertIsNone(delay)

        delay = self._request("GET", "/delayed")
        self.assertEqual(delay, '60.00')

    def test_response_to_delays_usernames(self):
        delay = self._request("GET", "/delayed", "user1")
        self.assertIsNone(delay)

        delay = self._request("GET", "/delayed", "user2")
        self.assertIsNone(delay)

        delay = self._request("GET", "/delayed", "user1")
        self.assertEqual(delay, '60.00')

        delay = self._request("GET", "/delayed", "user2")
        self.assertEqual(delay, '60.00')


class FakeHttplibSocket(object):
    """Fake `httplib.HTTPResponse` replacement."""

    def __init__(self, response_string):
        """Initialize new `FakeHttplibSocket`."""
        self._buffer = six.StringIO(response_string)

    def makefile(self, _mode, _other):
        """Returns the socket's internal buffer."""
        return self._buffer


class FakeHttplibConnection(object):
    """Fake `httplib.HTTPConnection`."""

    def __init__(self, app, host):
        """Initialize `FakeHttplibConnection`."""
        self.app = app
        self.host = host

    def request(self, method, path, body="", headers=None):
        """Fake method for request.

        Requests made via this connection actually get translated and
        routed into our WSGI app, we then wait for the response and turn
        it back into an `httplib.HTTPResponse`.
        """
        if not headers:
            headers = {}

        req = webob.Request.blank(path)
        req.method = method
        req.headers = headers
        req.host = self.host
        req.body = body

        resp = str(req.get_response(self.app))
        resp = "HTTP/1.0 %s" % resp
        sock = FakeHttplibSocket(resp)
        self.http_response = httplib.HTTPResponse(sock)
        self.http_response.begin()

    def getresponse(self):
        """Return our generated response from the request."""
        return self.http_response


def wire_HTTPConnection_to_WSGI(host, app):
    """Monkeypatches HTTPConnection so that if you try to connect to host, you
    are instead routed straight to the given WSGI app.

    After calling this method, when any code calls

    httplib.HTTPConnection(host)

    the connection object will be a fake.  Its requests will be sent directly
    to the given WSGI app rather than through a socket.

    Code connecting to hosts other than host will not be affected.

    This method may be called multiple times to map different hosts to
    different apps.

    This method returns the original HTTPConnection object, so that the caller
    can restore the default HTTPConnection interface (for all hosts).
    """
    class HTTPConnectionDecorator(object):
        """Wraps the real HTTPConnection class so that when you instantiate
        the class you might instead get a fake instance.
        """

        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __call__(self, connection_host, *args, **kwargs):
            if connection_host == host:
                return FakeHttplibConnection(app, host)
            else:
                return self.wrapped(connection_host, *args, **kwargs)

    oldHTTPConnection = httplib.HTTPConnection
    httplib.HTTPConnection = HTTPConnectionDecorator(httplib.HTTPConnection)
    return oldHTTPConnection


class WsgiLimiterProxyTest(BaseLimitTestSuite):
    """Tests for the `limits.WsgiLimiterProxy` class."""

    def setUp(self):
        """setUp for test suite.

        Do some nifty HTTP/WSGI magic which allows for WSGI to be called
        directly by something like the `httplib` library.
        """
        super(WsgiLimiterProxyTest, self).setUp()
        self.app = limits.WsgiLimiter(TEST_LIMITS)
        self.oldHTTPConnection = (
            wire_HTTPConnection_to_WSGI("169.254.0.1:80", self.app))
        self.proxy = limits.WsgiLimiterProxy("169.254.0.1:80")
        self.addCleanup(self._restore, self.oldHTTPConnection)

    def _restore(self, oldHTTPConnection):
        # restore original HTTPConnection object
        httplib.HTTPConnection = oldHTTPConnection

    def test_200(self):
        """Successful request test."""
        delay = self.proxy.check_for_delay("GET", "/anything")
        self.assertEqual(delay, (None, None))

    def test_403(self):
        """Forbidden request test."""
        delay = self.proxy.check_for_delay("GET", "/delayed")
        self.assertEqual(delay, (None, None))

        delay, error = self.proxy.check_for_delay("GET", "/delayed")
        error = error.strip()

        expected = ("60.00", "403 Forbidden\n\nOnly 1 GET request(s) can be "
                    "made to /delayed every minute.")

        self.assertEqual((delay, error), expected)


class LimitsViewBuilderTest(test.TestCase):
    def setUp(self):
        super(LimitsViewBuilderTest, self).setUp()
        self.view_builder = views.limits.ViewBuilder()
        self.rate_limits = [{"URI": "*",
                             "regex": ".*",
                             "value": 10,
                             "verb": "POST",
                             "remaining": 2,
                             "unit": "MINUTE",
                             "resetTime": 1311272226},
                            {"URI": "*/volumes",
                             "regex": "^/volumes",
                             "value": 50,
                             "verb": "POST",
                             "remaining": 10,
                             "unit": "DAY",
                             "resetTime": 1311272226}]
        self.absolute_limits = {"metadata_items": 1,
                                "injected_files": 5,
                                "injected_file_content_bytes": 5}

    def test_build_limits(self):
        tdate = "2011-07-21T18:17:06"
        expected_limits = \
            {"limits": {"rate": [{"uri": "*",
                                  "regex": ".*",
                                  "limit": [{"value": 10,
                                             "verb": "POST",
                                             "remaining": 2,
                                             "unit": "MINUTE",
                                             "next-available": tdate}]},
                                 {"uri": "*/volumes",
                                  "regex": "^/volumes",
                                  "limit": [{"value": 50,
                                             "verb": "POST",
                                             "remaining": 10,
                                             "unit": "DAY",
                                             "next-available": tdate}]}],
                        "absolute": {"maxServerMeta": 1,
                                     "maxImageMeta": 1,
                                     "maxPersonality": 5,
                                     "maxPersonalitySize": 5}}}

        output = self.view_builder.build(self.rate_limits,
                                         self.absolute_limits)
        self.assertDictMatch(output, expected_limits)

    def test_build_limits_empty_limits(self):
        expected_limits = {"limits": {"rate": [],
                           "absolute": {}}}

        abs_limits = {}
        rate_limits = []
        output = self.view_builder.build(rate_limits, abs_limits)
        self.assertDictMatch(output, expected_limits)


class LimitsXMLSerializationTest(test.TestCase):
    def test_xml_declaration(self):
        serializer = limits.LimitsTemplate()

        fixture = {"limits": {
                   "rate": [],
                   "absolute": {}}}

        output = serializer.serialize(fixture)
        has_dec = output.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        self.assertTrue(has_dec)

    def test_index(self):
        serializer = limits.LimitsTemplate()
        fixture = {
            "limits": {
                "rate": [{
                    "uri": "*",
                    "regex": ".*",
                    "limit": [{
                        "value": 10,
                        "verb": "POST",
                        "remaining": 2,
                        "unit": "MINUTE",
                        "next-available": "2011-12-15T22:42:45Z"}]},
                    {"uri": "*/servers",
                     "regex": "^/servers",
                     "limit": [{
                         "value": 50,
                         "verb": "POST",
                         "remaining": 10,
                         "unit": "DAY",
                         "next-available": "2011-12-15T22:42:45Z"}]}],
                "absolute": {"maxServerMeta": 1,
                             "maxImageMeta": 1,
                             "maxPersonality": 5,
                             "maxPersonalitySize": 10240}}}

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'limits')

        # verify absolute limits
        absolutes = root.xpath('ns:absolute/ns:limit', namespaces=NS)
        self.assertEqual(len(absolutes), 4)
        for limit in absolutes:
            name = limit.get('name')
            value = limit.get('value')
            self.assertEqual(value, str(fixture['limits']['absolute'][name]))

        # verify rate limits
        rates = root.xpath('ns:rates/ns:rate', namespaces=NS)
        self.assertEqual(len(rates), 2)
        for i, rate in enumerate(rates):
            for key in ['uri', 'regex']:
                self.assertEqual(rate.get(key),
                                 str(fixture['limits']['rate'][i][key]))
            rate_limits = rate.xpath('ns:limit', namespaces=NS)
            self.assertEqual(len(rate_limits), 1)
            for j, limit in enumerate(rate_limits):
                for key in ['verb', 'value', 'remaining', 'unit',
                            'next-available']:
                    self.assertEqual(
                        limit.get(key),
                        str(fixture['limits']['rate'][i]['limit'][j][key]))

    def test_index_no_limits(self):
        serializer = limits.LimitsTemplate()

        fixture = {"limits": {
                   "rate": [],
                   "absolute": {}}}

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'limits')

        # verify absolute limits
        absolutes = root.xpath('ns:absolute/ns:limit', namespaces=NS)
        self.assertEqual(len(absolutes), 0)

        # verify rate limits
        rates = root.xpath('ns:rates/ns:rate', namespaces=NS)
        self.assertEqual(len(rates), 0)
