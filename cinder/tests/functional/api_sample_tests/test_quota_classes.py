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


class QuotaClassesSampleJsonTest(test_base.VolumesSampleBase):
    sample_dir = "quota_classes"

    def setUp(self):
        super(QuotaClassesSampleJsonTest, self).setUp()

    def test_quota_classes_show(self):
        response = self._do_get('os-quota-class-sets/test_class')
        self._verify_response('quota-classes-show-response', {},
                              response, 200)

    def test_quotas_update(self):
        response = self._do_put('os-quota-class-sets/test_class',
                                'quota-classes-update-request')
        self._verify_response('quota-classes-update-response', {},
                              response, 200)
