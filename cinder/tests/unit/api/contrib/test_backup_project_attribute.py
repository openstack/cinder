# Copyright (c) 2016 Huawei Technologies Co., Ltd.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import ddt

from oslo_serialization import jsonutils
import webob

from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import router as router_v3
from cinder.backup import api as backup_api
from cinder import context
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.backup import fake_backup
from cinder.tests.unit import fake_constants as fake


def fake_backup_get(*args, **kwargs):
    ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
    bak = {
        'id': fake.BACKUP_ID,
        'project_id': fake.PROJECT_ID,
    }
    return fake_backup.fake_backup_obj(ctx, **bak)


def fake_backup_get_all(*args, **kwargs):
    return objects.BackupList(objects=[fake_backup_get()])


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = router_v3.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v3'] = api
    return mapper


@ddt.ddt
class BackupProjectAttributeTest(test.TestCase):

    def setUp(self):
        super(BackupProjectAttributeTest, self).setUp()
        self.stubs.Set(backup_api.API, 'get', fake_backup_get)
        self.stubs.Set(backup_api.API, 'get_all', fake_backup_get_all)

    def _send_backup_request(self, ctx, detail=False, version='3.18'):
        req = None
        if detail:
            req = webob.Request.blank(('/v3/%s/backups/detail'
                                       % fake.PROJECT_ID))
        else:
            req = webob.Request.blank('/v3/%s/backups/%s' % (fake.PROJECT_ID,
                                                             fake.BACKUP_ID))
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        req.headers['OpenStack-API-Version'] = 'volume ' + version
        req.api_version_request = api_version.APIVersionRequest(version)
        res = req.get_response(app())

        if detail:
            return jsonutils.loads(res.body)['backups']
        return jsonutils.loads(res.body)['backup']

    @ddt.data(True, False)
    def test_get_backup_with_project(self, is_admin):
        ctx = context.RequestContext(fake.USER2_ID, fake.PROJECT_ID, is_admin)
        bak = self._send_backup_request(ctx)
        if is_admin:
            self.assertEqual(fake.PROJECT_ID,
                             bak['os-backup-project-attr:project_id'])
        else:
            self.assertNotIn('os-backup-project-attr:project_id', bak)

    @ddt.data(True, False)
    def test_list_detail_backups_with_project(self, is_admin):
        ctx = context.RequestContext(fake.USER2_ID, fake.PROJECT_ID, is_admin)
        baks = self._send_backup_request(ctx, detail=True)
        if is_admin:
            self.assertEqual(fake.PROJECT_ID,
                             baks[0]['os-backup-project-attr:project_id'])
        else:
            self.assertNotIn('os-backup-project-attr:project_id', baks[0])

    def test_get_backup_under_allowed_api_version(self):
        ctx = context.RequestContext(fake.USER2_ID, fake.PROJECT_ID, True)
        bak = self._send_backup_request(ctx, version='3.17')
        self.assertNotIn('os-backup-project-attr:project_id', bak)
