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


class VolumeTransferSampleJsonTest(test_base.VolumesSampleBase):
    sample_dir = "volume_transfer"

    def setUp(self):
        super(VolumeTransferSampleJsonTest, self).setUp()
        res = self._create_volume()
        res = jsonutils.loads(res.content)['volume']
        self._poll_volume_while(res['id'], ['creating'])
        self.subs = {
            "volume_id": res['id']
        }
        self.response = self._create_transfer(self.subs)

    def _create_transfer(self, subs=None):
        response = self._do_post('os-volume-transfer',
                                 'volume-transfer-create-request',
                                 subs)
        return response

    def test_transfer_create(self):

        self._verify_response('volume-transfer-create-response',
                              {}, self.response, 202)

    def test_transfer_accept(self):

        res = jsonutils.loads(self.response.content)['transfer']
        subs = {
            "auth_key": res['auth_key']
        }
        response = self._do_post(
            'os-volume-transfer/%s/accept' % res['id'],
            'volume-transfer-accept-request',
            subs)
        self._verify_response('volume-transfer-accept-response',
                              {}, response, 202)

    def test_transfers_list(self):

        response = self._do_get('os-volume-transfer')
        self._verify_response('volume-transfers-list-response',
                              {}, response, 200)

    def test_transfer_list_detail(self):

        res = jsonutils.loads(self.response.content)['transfer']
        response = self._do_get('os-volume-transfer/%s' % res['id'])
        self._verify_response('volume-transfer-show-response',
                              {}, response, 200)

    def test_transfers_list_detail(self):

        response = self._do_get('os-volume-transfer/detail')
        self._verify_response('volume-transfers-list-detailed-response',
                              {}, response, 200)
