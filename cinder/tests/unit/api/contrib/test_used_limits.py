# Copyright 2012 OpenStack Foundation
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

import ddt
import mock

from cinder.api.contrib import used_limits
from cinder.api import microversions as mv
from cinder.api.openstack import api_version_request
from cinder.api.openstack import wsgi
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake


class FakeRequest(object):
    def __init__(self, context, filter=None, api_version='2.0'):
        self.environ = {'cinder.context': context}
        self.params = filter or {}
        self.api_version_request = api_version_request.APIVersionRequest(
            api_version)


@ddt.ddt
class UsedLimitsTestCase(test.TestCase):
    def setUp(self):
        """Run before each test."""
        super(UsedLimitsTestCase, self).setUp()
        self.controller = used_limits.UsedLimitsController()

    @ddt.data(('2.0', False),
              (mv.get_prior_version(mv.LIMITS_ADMIN_FILTER), True),
              (mv.get_prior_version(mv.LIMITS_ADMIN_FILTER), False),
              (mv.LIMITS_ADMIN_FILTER, True),
              (mv.LIMITS_ADMIN_FILTER, False))
    @mock.patch('cinder.quota.QUOTAS.get_project_quotas')
    @mock.patch('cinder.policy.authorize')
    def test_used_limits(self, ver_project, _mock_policy_authorize,
                         _mock_get_project_quotas):
        version, has_project = ver_project
        fake_req = FakeRequest(fakes.FakeRequestContext(fake.USER_ID,
                                                        fake.PROJECT_ID,
                                                        is_admin=True),
                               api_version=version)
        if has_project:
            fake_req = FakeRequest(fakes.FakeRequestContext(fake.USER_ID,
                                                            fake.PROJECT_ID,
                                                            is_admin=True),
                                   filter={'project_id': fake.UUID1},
                                   api_version=version)
        obj = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        res = wsgi.ResponseObject(obj)

        def get_project_quotas(context, project_id, quota_class=None,
                               defaults=True, usages=True):
            if project_id == fake.UUID1:
                return {"gigabytes": {'limit': 5, 'in_use': 1}}
            return {"gigabytes": {'limit': 10, 'in_use': 2}}

        _mock_get_project_quotas.side_effect = get_project_quotas
        # allow user to access used limits
        _mock_policy_authorize.return_value = True

        self.controller.index(fake_req, res)
        abs_limits = res.obj['limits']['absolute']

        # if admin, only LIMITS_ADMIN_FILTER and req contains project_id
        # filter, cinder returns the specified project's quota.
        if version == mv.LIMITS_ADMIN_FILTER and has_project:
            self.assertEqual(1, abs_limits['totalGigabytesUsed'])
        else:
            self.assertEqual(2, abs_limits['totalGigabytesUsed'])

        fake_req = FakeRequest(fakes.FakeRequestContext(fake.USER_ID,
                                                        fake.PROJECT_ID),
                               api_version=version)
        if has_project:
            fake_req = FakeRequest(fakes.FakeRequestContext(fake.USER_ID,
                                                            fake.PROJECT_ID),
                                   filter={'project_id': fake.UUID1},
                                   api_version=version)
        # if non-admin, cinder always returns self quota.
        self.controller.index(fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        self.assertEqual(2, abs_limits['totalGigabytesUsed'])

        obj = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        res = wsgi.ResponseObject(obj)

        # unallow user to access used limits
        _mock_policy_authorize.return_value = False

        self.controller.index(fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        self.assertNotIn('totalVolumesUsed', abs_limits)
        self.assertNotIn('totalGigabytesUsed', abs_limits)
        self.assertNotIn('totalSnapshotsUsed', abs_limits)
