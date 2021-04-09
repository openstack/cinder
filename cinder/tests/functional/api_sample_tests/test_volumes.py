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

from cinder.api import microversions as mv
from cinder.tests.functional import api_samples_test_base as test_base


@test_base.VolumesSampleBase.use_versions(
    mv.BASE_VERSION,  # 3.0
    mv.GROUP_VOLUME,  # 3.13
    mv.VOLUME_DETAIL_PROVIDER_ID,  # 3.21
    mv.VOLUME_SHARED_TARGETS_AND_SERVICE_FIELDS,  # 3.48
    mv.VOLUME_CLUSTER_NAME,  # 3.61
    mv.VOLUME_TYPE_ID_IN_VOLUME_DETAIL,  # 3.63
    mv.USE_QUOTA)  # 3.65
class VolumeDetailTests(test_base.VolumesSampleBase):
    """Test volume details returned for operations with different MVs.

    The details of a volume have changed in the different microversions, and we
    have multiple operations that return them, so we should confirm that each
    microversion returns the right values for all these different operations.
    """
    def setup(self):
        """Create a volume before we run each test.

        This method is called by _FunctionalTestBase right before each test is
        called.

        We cannot create the volume on the setUp method because at that time
        the API version is still 3.0, so we need it to be created right after
        the microversion under test has been set.

        This way the create method is called using the right microversion,
        which is required for some tests, like test_volume_create.
        """
        self.response = self._create_volume()

    def test_volume_list_detail(self):
        response = self._do_get('volumes/detail')
        self._verify_response('volumes-list-detailed-response',
                              {}, response, 200)

    def test_volume_show_detail(self):
        res = jsonutils.loads(self.response.content)['volume']
        response = self._do_get('volumes/%s' % res['id'])
        self._verify_response('volume-show-response',
                              {}, response, 200)

    def test_volume_create(self):
        self._verify_response('volume-create-response',
                              {}, self.response, 202)

    def test_volume_update(self):
        res = jsonutils.loads(self.response.content)['volume']
        # Use the request sample from the common API, since the request didn't
        # change with the microversion, what changes is the response.
        with self.common_api_sample():
            response = self._do_put('volumes/%s' % res['id'],
                                    'volume-update-request')
        self._verify_response('volume-update-response',
                              {}, response, 200)


class VolumesSampleJsonTest(test_base.VolumesSampleBase):
    def setUp(self):
        super(test_base.VolumesSampleBase, self).setUp()
        self.response = self._create_volume()

    def test_volume_list(self):

        response = self._do_get('volumes')
        self._verify_response('volumes-list-response',
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
