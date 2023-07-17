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
from cinder.tests.functional.api_sample_tests import test_volumes
from cinder.tests.functional import api_samples_test_base as test_base


@test_base.VolumesSampleBase.use_versions(
    mv.TRANSFER_WITH_SNAPSHOTS,
    mv.TRANSFER_WITH_HISTORY)
class VolumeTransfersSampleJsonTest(test_volumes.test_base.VolumesSampleBase):
    sample_dir = "volume_transfers"

    def setUp(self):
        super(VolumeTransfersSampleJsonTest, self).setUp()
        res = self._create_volume()
        res = jsonutils.loads(res.content)['volume']
        self._poll_volume_while(res['id'], ['creating'])
        self.subs = {
            "volume_id": res['id']
        }

    def _create_transfers(self, subs=None):
        response = self._do_post('volume-transfers',
                                 'volume-transfers-create-request',
                                 self.subs)
        return response

    def test_create_transfers(self):
        response = self._create_transfers(self.subs)
        self._verify_response('volume-transfers-create-response',
                              {}, response, 202)

    def test_accept_transfer(self):
        response = self._create_transfers(self.subs)
        res = jsonutils.loads(response.content)['transfer']
        subs = {
            'auth_key': res['auth_key']
        }
        with self.common_api_sample():
            response = self._do_post('volume-transfers/%s/accept' % res['id'],
                                     'volume-transfers-accept-request',
                                     subs)
            self._verify_response('volume-transfers-accept-response',
                                  {}, response, 202)

    def test_show_transfer(self):
        response = self._create_transfers(self.subs)
        res = jsonutils.loads(response.content)['transfer']
        show_response = self._do_get('volume-transfers/%s' % res['id'])
        self._verify_response('volume-transfers-show-response', {},
                              show_response, 200)

    def test_delete_transfer(self):
        response = self._create_transfers(self.subs)
        res = jsonutils.loads(response.content)['transfer']
        delete_res = self._do_delete('volume-transfers/%s' % res['id'])
        self.assertEqual(202, delete_res.status_code)
