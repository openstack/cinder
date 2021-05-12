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

from oslo_serialization import jsonutils

from cinder.tests.functional.api_sample_tests import fakes
from cinder.tests.functional import api_samples_test_base as test_base


class VolumeActionsSampleJsonTest(test_base.VolumesSampleBase):
    sample_dir = "volume_actions"

    def setUp(self):
        super(VolumeActionsSampleJsonTest, self).setUp()
        self.response = self._create_volume()
        self.stub_out("cinder.volume.api.API.copy_volume_to_image",
                      fakes.stub_copy_volume_to_image)

    def test_volume_upload_image(self):
        res = jsonutils.loads(self.response.content)['volume']
        self._poll_volume_while(res['id'], ['creating'])
        response = self._do_post('volumes/%s/action' % res['id'],
                                 'volume-upload-to-image-request')
        self._verify_response('volume-upload-to-image-response',
                              {}, response, 202)
