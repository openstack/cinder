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

from oslo_serialization import jsonutils
import webob

from cinder.api.middleware import rate_limit
from cinder.api.v2 import limits
from cinder.api import views
import cinder.context
from cinder.tests.unit import test


class BaseLimitTestSuite(test.TestCase):
    """Base test suite which provides relevant stubs and time abstraction."""

    def setUp(self):
        super(BaseLimitTestSuite, self).setUp()
        self.time = 0.0
        self.mock_object(rate_limit.Limit, "_get_time", self._get_time)
        self.absolute_limits = {}

        def fake_get_project_quotas(context, project_id, usages=True):
            return {k: dict(limit=v) for k, v in self.absolute_limits.items()}

        self.mock_object(cinder.quota.QUOTAS, "get_project_quotas",
                         fake_get_project_quotas)

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
            rate_limit.Limit("GET", "*", ".*", 10, 60).display(),
            rate_limit.Limit("POST", "*", ".*", 5, 60 * 60).display(),
            rate_limit.Limit(
                "GET", "changes-since*", "changes-since", 5, 60,
            ).display(),
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
            rate_limit.Limit("GET", "*", ".*", 10, 60).display(),
            rate_limit.Limit("GET", "*", "*.*", 10, 60).display(),
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
        self.absolute_limits = {"gigabytes": 1,
                                "backup_gigabytes": 2,
                                "volumes": 3,
                                "snapshots": 4,
                                "backups": 5}

    def test_build_limits(self):
        tdate = "2011-07-21T18:17:06"
        expected_limits = {
            "limits": {"rate": [{"uri": "*",
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
                       "absolute": {"maxTotalVolumeGigabytes": 1,
                                    "maxTotalBackupGigabytes": 2,
                                    "maxTotalVolumes": 3,
                                    "maxTotalSnapshots": 4,
                                    "maxTotalBackups": 5}}}

        output = self.view_builder.build(self.rate_limits,
                                         self.absolute_limits)
        self.assertDictEqual(expected_limits, output)

    def test_build_limits_empty_limits(self):
        expected_limits = {"limits": {"rate": [],
                           "absolute": {}}}

        abs_limits = {}
        rate_limits = []
        output = self.view_builder.build(rate_limits, abs_limits)
        self.assertDictEqual(expected_limits, output)
