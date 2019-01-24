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

from cinder.tests.functional import api_samples_test_base


class VolumesSampleBase(api_samples_test_base.ApiSampleTestBase):
    sample_dir = "volumes"

    def _create_volume(self, _use_common_volume_api_samples=True, subs=None):

        orig_value = self.__class__._use_common_volume_api_samples
        try:
            self.__class__._use_common_volume_api_samples = (
                _use_common_volume_api_samples)
            response = self._do_post('volumes',
                                     'volume-create-request',
                                     subs)
            return response

        finally:
            self.__class__._use_common_volume_api_samples = orig_value


class VolumesSampleJsonTest(VolumesSampleBase):

    def setUp(self):
        super(VolumesSampleBase, self).setUp()
        self.response = self._create_volume()

    def test_volume_list_detail(self):

        response = self._do_get('volumes/detail')
        self._verify_response('volumes-list-detailed-response',
                              {}, response, 200)

    def test_volume_create(self):

        self._verify_response('volume-create-response',
                              {}, self.response, 202)

    def test_volume_list(self):

        response = self._do_get('volumes')
        self._verify_response('volumes-list-response',
                              {}, response, 200)

    def test_volume_show_detail(self):

        res = jsonutils.loads(self.response.content)['volume']
        response = self._do_get('volumes/%s' % res['id'])
        self._verify_response('volume-show-response',
                              {}, response, 200)

    def test_volume_update(self):

        res = jsonutils.loads(self.response.content)['volume']
        response = self._do_put('volumes/%s' % res['id'],
                                'volume-update-request')
        self._verify_response('volume-update-response',
                              {}, response, 200)

    def test_volume_metadata_create(self):

        res = jsonutils.loads(self.response.content)['volume']
        response = self._do_post('volumes/%s/metadata' % res['id'],
                                 'volume-metadata-create-request')
        self._verify_response('volume-metadata-create-response',
                              {}, response, 200)

    def test_volume_metadata_show(self):

        res = jsonutils.loads(self.response.content)['volume']
        response = self._do_get('volumes/%s/metadata' % res['id'])
        self._verify_response('volume-metadata-show-response',
                              {}, response, 200)

    def test_volume_metadata_update(self):

        res = jsonutils.loads(self.response.content)['volume']
        response = self._do_put('volumes/%s/metadata' % res['id'],
                                'volume-metadata-update-request')
        self._verify_response('volume-metadata-update-response',
                              {}, response, 200)

    def test_volume_metadata_show_specific_key(self):

        res = jsonutils.loads(self.response.content)['volume']
        self._do_put('volumes/%s/metadata' % res['id'],
                     'volume-metadata-update-request')
        response = self._do_get('volumes/%s/metadata/name' % res['id'])
        self._verify_response('volume-metadata-show-key-response',
                              {}, response, 200)
