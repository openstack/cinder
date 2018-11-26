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


class ExtensionsSampleJsonTest(api_samples_test_base.ApiSampleTestBase):
    sample_dir = "extensions"

    def setUp(self):
        super(ExtensionsSampleJsonTest, self).setUp()
        self.subs = {
            'max_api_version': api_version_request._MAX_API_VERSION}

    def test_extensions(self):
        response = self._do_get('extensions')
        self._verify_response('extensions-list-response',
                              self.subs,
                              response, 200, update_links=False)
