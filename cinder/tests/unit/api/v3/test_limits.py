# Copyright 2017 Huawei Corporation
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

from unittest import mock

import ddt
from oslo_serialization import jsonutils
import webob

from cinder.api import microversions as mv
from cinder.api.middleware import rate_limit
from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import limits
from cinder.api import views
import cinder.context
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test

LIMITS_FILTER = mv.LIMITS_ADMIN_FILTER
PRE_LIMITS_FILTER = mv.get_prior_version(LIMITS_FILTER)


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


# TODO(stephenfin): Fold this into the above
@ddt.ddt
class LimitsControllerMVTest(test.TestCase):
    def setUp(self):
        super().setUp()
        self.controller = limits.LimitsController()

    @ddt.data((PRE_LIMITS_FILTER, True), (PRE_LIMITS_FILTER, False),
              (LIMITS_FILTER, True), (LIMITS_FILTER, False))
    @mock.patch('cinder.quota.VolumeTypeQuotaEngine.get_project_quotas')
    def test_get_limit_with_project_id(self, ver_project, mock_get_quotas):
        max_ver, has_project = ver_project
        req = fakes.HTTPRequest.blank('/v3/limits', use_admin_context=True)
        if has_project:
            req = fakes.HTTPRequest.blank(
                '/v3/limits?project_id=%s' % fake.UUID1,
                use_admin_context=True)
        req.api_version_request = api_version.APIVersionRequest(max_ver)

        def get_project_quotas(context, project_id, quota_class=None,
                               defaults=True, usages=True):
            if project_id == fake.UUID1:
                return {"gigabytes": {'limit': 5}}
            return {"gigabytes": {'limit': 10}}
        mock_get_quotas.side_effect = get_project_quotas

        resp_dict = self.controller.index(req)
        # if admin, only LIMITS_FILTER and req contains project_id filter,
        # cinder returns the specified project's quota.
        if max_ver == LIMITS_FILTER and has_project:
            self.assertEqual(
                5, resp_dict['limits']['absolute']['maxTotalVolumeGigabytes'])
        else:
            self.assertEqual(
                10, resp_dict['limits']['absolute']['maxTotalVolumeGigabytes'])

        # if non-admin, cinder always returns self quota.
        req = fakes.HTTPRequest.blank('/v3/limits', use_admin_context=False)
        if has_project:
            req = fakes.HTTPRequest.blank(
                '/v3/limits?project_id=%s' % fake.UUID1,
                use_admin_context=False)
        req.api_version_request = api_version.APIVersionRequest(max_ver)
        resp_dict = self.controller.index(req)

        self.assertEqual(
            10, resp_dict['limits']['absolute']['maxTotalVolumeGigabytes'])
