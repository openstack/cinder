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


class BackupClassesSampleJsonTest(test_base.VolumesSampleBase):
    sample_dir = "backups"

    def setUp(self):
        super(BackupClassesSampleJsonTest, self).setUp()
        res = self._create_volume()
        res = jsonutils.loads(res.content)['volume']
        self._poll_volume_while(res['id'], ['creating'])
        self.subs = {
            "volume_id": res['id']
        }
        with self.common_api_sample():
            self.response = self._do_post('backups',
                                          'backup-create-request',
                                          self.subs)

    def test_backup_create(self):
        self._verify_response('backup-create-response',
                              {}, self.response, 202)

    def test_backup_list(self):
        response = self._do_get('backups')
        self._verify_response('backups-list-response',
                              {}, response, 200)
