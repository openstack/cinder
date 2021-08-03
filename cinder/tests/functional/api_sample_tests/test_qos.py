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

from cinder.tests.functional import api_samples_test_base as test_base


class QOSSampleJsonTest(test_base.VolumesSampleBase):
    sample_dir = "qos"

    def setUp(self):
        super(QOSSampleJsonTest, self).setUp()
        self.response = self._do_post('qos-specs', 'qos-create-request')

    def test_qos_create(self):
        self._verify_response('qos-create-response', {}, self.response, 200)

    def test_qos_list(self):
        response = self._do_get('qos-specs')
        self._verify_response('qos-list-response', {}, response, 200)

    def test_qos_show(self):
        res = jsonutils.loads(self.response.content)['qos_specs']
        response = self._do_get('qos-specs/%s' % res['id'])
        self._verify_response('qos-show-response', {}, response, 200)

    def test_qos_update(self):
        res = jsonutils.loads(self.response.content)['qos_specs']
        response = self._do_put('qos-specs/%s' % res['id'],
                                'qos-update-request')
        self._verify_response('qos-update-response', {}, response, 200)

    def test_qos_show_associations(self):
        res = jsonutils.loads(self.response.content)['qos_specs']
        response = self._do_get('qos-specs/%s/associations' % res['id'])
        self._verify_response('qos_show_response', {}, response, 200)
