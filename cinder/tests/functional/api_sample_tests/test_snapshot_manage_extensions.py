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

from cinder.tests.functional.api_sample_tests import fakes
from cinder.tests.functional import api_samples_test_base as base


class SnapshotManageExtensionsSampleJsonTest(base.ApiSampleTestBase):
    sample_dir = "snapshot_manage_extensions"

    def setUp(self):
        super(SnapshotManageExtensionsSampleJsonTest, self).setUp()
        self.stub_out("cinder.api.contrib.snapshot_manage."
                      "SnapshotManageController.create",
                      fakes.stub_manage_existing_snapshot)

    def test_snapshot_manage_create(self):

        response = self._do_post('os-snapshot-manage',
                                 'snapshot-manage-request',
                                 subs=self.subs)
        self._verify_response('snapshot-manage-response',
                              {}, response, 202)
