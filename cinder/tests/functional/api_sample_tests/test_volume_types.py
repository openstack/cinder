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

from oslo_config import cfg
from oslo_serialization import jsonutils

from cinder.tests.functional import api_samples_test_base

CONF = cfg.CONF


class VolumeTypesSampleJsonTest(api_samples_test_base.ApiSampleTestBase):
    sample_dir = "volume_type"

    def setUp(self):
        super(VolumeTypesSampleJsonTest, self).setUp()
        self.volume_type_name = "vol-type-001"
        self.subs = {
            "name": self.volume_type_name,
            "description": "volume type 0001",
            "bool": "True"
        }
        CONF.set_override("default_volume_type",
                          "vol-type-001")

    def _volume_type_create(self, subs=None):
        subs = subs if subs is not None else self.subs
        response = self._do_post('types',
                                 'volume-type-create-request',
                                 subs)
        return response

    def _encryption_type_create(self, volume_type_id):
        response = self._do_post(('types/%s/encryption') % volume_type_id,
                                 'encryption-type-create-request')
        return response

    def test_volume_type_create(self):

        response = self._volume_type_create()
        self._verify_response('volume-type-create-response',
                              self.subs, response, 200)

    def test_volume_type_show(self):

        res = self._volume_type_create()
        res = jsonutils.loads(res.content)['volume_type']
        response = self._do_get('types/%s' % res['id'])
        self._verify_response('volume-type-show-response',
                              self.subs, response, 200)

    def test_volume_type_update(self):
        res = self._volume_type_create()
        res = jsonutils.loads(res.content)['volume_type']
        response = self._do_put(
            'types/%s' % res['id'], 'volume-type-update-request', self.subs)
        self._verify_response('volume-type-update-response',
                              self.subs, response, 200)

    def test_volume_type_extra_spec_create_update(self):

        res = self._volume_type_create()
        res = jsonutils.loads(res.content)['volume_type']
        url = ("types/%s/extra_specs" % res['id'])
        response = self._do_post(
            url,
            'volume-type-extra-specs-create-update-request',
            {})
        self._verify_response(
            'volume-type-extra-specs-create-update-response',
            {}, response, 200)

    def test_volume_type_all_extra_spec_show(self):

        res = self._volume_type_create()
        res = jsonutils.loads(res.content)['volume_type']
        url = ("types/%s/extra_specs" % res['id'])
        response = self._do_get(url)
        self._verify_response(
            'volume-type-all-extra-specs-show-response',
            {}, response, 200)

    def test_volume_type_specific_extra_spec_show(self):

        res = self._volume_type_create()
        res = jsonutils.loads(res.content)['volume_type']
        url = ("types/%s/extra_specs/capabilities" % res['id'])
        response = self._do_get(url)
        self._verify_response(
            'volume-type-specific-extra-specs-show-response',
            {}, response, 200)

    def test_volume_type_show_default(self):

        self._volume_type_create()
        response = self._do_get('types/default')
        self._verify_response('volume-type-default-response',
                              self.subs, response, 200)

    def test_volume_type_list(self):

        subs = {
            "name": "vol-type-002",
            "description": "volume type 0002",
            "bool": "True"
        }
        self._volume_type_create()
        self._volume_type_create(subs)
        response = self._do_get('types')
        self._verify_response('volume-types-list-response',
                              self.subs, response, 200)

    def test_encryption_type_show(self):

        res = self._volume_type_create()
        res = jsonutils.loads(res.content)['volume_type']
        self._encryption_type_create(res['id'])
        response = self._do_get('types/%s/encryption' % res['id'])
        self._verify_response('encryption-type-show-response',
                              self.subs, response, 200)

    def test_encryption_type_show_specific_spec(self):
        res = self._volume_type_create()
        res = jsonutils.loads(res.content)['volume_type']
        self._encryption_type_create(res['id'])
        response = self._do_get('types/%s/encryption/cipher' % res['id'])
        self._verify_response('encryption-type-specific-specs-show-response',
                              self.subs, response, 200)

    def test_encryption_type_create(self):
        res = self._volume_type_create()
        res = jsonutils.loads(res.content)['volume_type']
        response = self._encryption_type_create(res['id'])
        self._verify_response('encryption-type-create-response',
                              self.subs, response, 200)

    def test_encryption_type_update(self):
        res = self._volume_type_create()
        res = jsonutils.loads(res.content)['volume_type']
        res_encrypt = self._encryption_type_create(res['id'])
        res_encrypt = jsonutils.loads(res_encrypt.content)['encryption']
        response = self._do_put(
            'types/%s/encryption/%s' % (res['id'],
                                        res_encrypt['encryption_id']),
            'encryption-type-update-request')
        self._verify_response('encryption-type-update-response',
                              self.subs, response, 200)

    def test_private_volume_type_access_add_list(self):

        subs = self.subs
        subs['bool'] = "False"
        res = self._volume_type_create(subs)
        res = jsonutils.loads(res.content)['volume_type']
        self._do_post('types/%s/action' % res['id'],
                      'volume-type-access-add-request')
        response = self._do_get(
            'types/%s/os-volume-type-access' % res['id'])
        self._verify_response('volume-type-access-list-response',
                              {}, response, 200)
