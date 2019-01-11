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

from cinder.api.openstack import api_version_request
from cinder.tests.functional import api_samples_test_base


class VersionsSampleJsonTest(api_samples_test_base.ApiSampleTestBase):
    sample_dir = "versions"

    def setUp(self):
        super(VersionsSampleJsonTest, self).setUp()
        self.subs = {
            'max_api_version': api_version_request._MAX_API_VERSION}

    def test_versions_get_all(self):
        response = self.api.api_request('', strip_version=True)
        self._verify_response('versions-response',
                              self.subs,
                              response, 300, update_links=False)

    def test_versions_get_v3(self):
        response = self.api.api_request('v3/', strip_version=True)
        self._verify_response('version-show-response',
                              self.subs,
                              response, 200, update_links=False)
