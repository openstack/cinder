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

from cinder.api.contrib import used_limits
from cinder.api.openstack import wsgi
from cinder import quota
from cinder import test
from cinder.tests.api import fakes


class FakeRequest(object):
    def __init__(self, context):
        self.environ = {'cinder.context': context}


class UsedLimitsTestCase(test.TestCase):
    def setUp(self):
        """Run before each test."""
        super(UsedLimitsTestCase, self).setUp()
        self.controller = used_limits.UsedLimitsController()

    def test_used_limits(self):
        fake_req = FakeRequest(fakes.FakeRequestContext('fake', 'fake'))
        obj = {
            "limits": {
                "rate": [],
                "absolute": {},
            },
        }
        res = wsgi.ResponseObject(obj)
        quota_map = {
            'totalVolumesUsed': 'volumes',
            'totalGigabytesUsed': 'gigabytes',
            'totalSnapshotsUsed': 'snapshots',
        }

        limits = {}
        for display_name, q in quota_map.iteritems():
            limits[q] = {'limit': 2,
                         'in_use': 1}

        def stub_get_project_quotas(context, project_id, usages=True):
            return limits

        self.stubs.Set(quota.QUOTAS, "get_project_quotas",
                       stub_get_project_quotas)

        self.mox.ReplayAll()

        self.controller.index(fake_req, res)
        abs_limits = res.obj['limits']['absolute']
        for used_limit, value in abs_limits.iteritems():
            self.assertEqual(value,
                             limits[quota_map[used_limit]]['in_use'])
