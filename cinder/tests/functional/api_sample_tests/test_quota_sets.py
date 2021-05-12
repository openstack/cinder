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

from cinder.tests.functional import api_samples_test_base as test_base


class QuotaSetsSampleJsonTest(test_base.VolumesSampleBase):
    sample_dir = "quota_sets"

    def setUp(self):
        super(QuotaSetsSampleJsonTest, self).setUp()

    def test_quotas_show(self):
        response = self._do_get('os-quota-sets/fake_tenant')
        self._verify_response('quotas-show-response', {}, response, 200)

    def test_quotas_show_usage(self):
        response = self._do_get('os-quota-sets/fake_tenant?usage=True')
        self._verify_response('quotas-show-usage-response', {}, response, 200)

    def test_quotas_update(self):
        response = self._do_put('os-quota-sets/fake_tenant',
                                'quotas-update-request')
        self._verify_response('quotas-update-response', {}, response, 200)

    def test_quotas_defaults(self):
        response = self._do_get('os-quota-sets/fake_tenant/defaults')
        self._verify_response('quotas-show-defaults-response',
                              {}, response, 200)
