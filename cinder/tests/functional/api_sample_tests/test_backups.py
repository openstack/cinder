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
    mv.BACKUP_UPDATE,  # 3.9
    mv.BACKUP_PROJECT,  # 3.18
    mv.BACKUP_METADATA,  # 3.43
    mv.SUPPORT_COUNT_INFO,  # 3.45
    mv.BACKUP_PROJECT_USER_ID)  # 3.56
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

    @test_base.VolumesSampleBase.override_mv(mv.BASE_VERSION)  # 3.0
    def test_backup_list(self):
        response = self._do_get('backups')
        self._verify_response('backups-list-response',
                              {}, response, 200)

    @test_base.VolumesSampleBase.override_mv(mv.SUPPORT_COUNT_INFO)  # 3.45
    def test_backup_list_with_count(self):
        response = self._do_get('backups?with_count=True')
        self._verify_response('backups-list-response',
                              {}, response, 200)

    @test_base.VolumesSampleBase.override_mv(mv.BACKUP_UPDATE)  # 3.9
    def test_backup_update(self):
        res = jsonutils.loads(self.response.content)['backup']
        response = self._do_put('backups/%s' % res['id'],
                                'backup-update-request')
        self._verify_response('backup-update-response',
                              {}, response, 200)

    def test_backup_show(self):
        res = jsonutils.loads(self.response.content)['backup']
        response = self._do_get('backups/%s' % res['id'])
        self._verify_response('backup-show-response',
                              {}, response, 200)

    @test_base.VolumesSampleBase.override_mv(mv.BASE_VERSION)  # 3.0
    def test_backup_list_detail(self):
        response = self._do_get('backups/detail')
        self._verify_response('backups-list-detailed-response',
                              {}, response, 200)

    @test_base.VolumesSampleBase.override_mv(mv.SUPPORT_COUNT_INFO)  # 3.45
    def test_backup_list_detail_with_count(self):
        response = self._do_get('backups/detail?with_count=True')
        self._verify_response('backups-list-detailed-response',
                              {}, response, 200)
