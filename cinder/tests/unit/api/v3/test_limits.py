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

import ddt
import mock

from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import limits
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake


@ddt.ddt
class LimitsControllerTest(test.TestCase):
    def setUp(self):
        super(LimitsControllerTest, self).setUp()
        self.controller = limits.LimitsController()

    @ddt.data(('3.38', True), ('3.38', False), ('3.39', True), ('3.39', False))
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
        # if admin, only 3.39 and req contains project_id filter, cinder
        # returns the specified project's quota.
        if max_ver == '3.39' and has_project:
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
