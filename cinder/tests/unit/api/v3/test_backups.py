# Copyright (c) 2016 Intel, Inc.
# All Rights Reserved.
#
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

"""The backups V3 api."""

import ddt
import mock
import webob

from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import backups
from cinder.api.views import backups as backup_view
import cinder.backup
from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils as test_utils


@ddt.ddt
class BackupsControllerAPITestCase(test.TestCase):
    """Test cases for backups API."""

    def setUp(self):
        super(BackupsControllerAPITestCase, self).setUp()
        self.backup_api = cinder.backup.API()
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                           auth_token=True,
                                           is_admin=True)
        self.controller = backups.BackupsController()

    def _fake_update_request(self, backup_id, version='3.9'):
        req = fakes.HTTPRequest.blank('/v3/%s/backups/%s/update' %
                                      (fake.PROJECT_ID, backup_id))
        req.environ['cinder.context'].is_admin = True
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume ' + version
        req.api_version_request = api_version.APIVersionRequest(version)
        return req

    def test_update_wrong_version(self):
        req = self._fake_update_request(fake.BACKUP_ID, version='3.6')
        body = {"backup": {"name": "Updated Test Name", }}
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.update, req, fake.BACKUP_ID,
                          body)

    def test_backup_update_with_no_body(self):
        # omit body from the request
        req = self._fake_update_request(fake.BACKUP_ID)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update,
                          req, fake.BACKUP_ID, None)

    def test_backup_update_with_unsupported_field(self):
        req = self._fake_update_request(fake.BACKUP_ID)
        body = {"backup": {"id": fake.BACKUP2_ID,
                           "description": "", }}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update,
                          req, fake.BACKUP_ID, body)

    def test_backup_update_with_backup_not_found(self):
        req = self._fake_update_request(fake.BACKUP_ID)
        updates = {
            "name": "Updated Test Name",
            "description": "Updated Test description.",
        }
        body = {"backup": updates}
        self.assertRaises(exception.NotFound,
                          self.controller.update,
                          req, fake.BACKUP_ID, body)

    @ddt.data('3.30', '3.31', '3.34')
    @mock.patch('cinder.api.common.reject_invalid_filters')
    def test_backup_list_with_general_filter(self, version, mock_update):
        url = '/v3/%s/backups' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url,
                                      version=version,
                                      use_admin_context=False)
        self.controller.index(req)

        if version != '3.30':
            support_like = True if version == '3.34' else False
            mock_update.assert_called_once_with(req.environ['cinder.context'],
                                                mock.ANY, 'backup',
                                                support_like)

    @ddt.data('3.36', '3.37')
    def test_backup_list_with_name(self, version):
        backup1 = test_utils.create_backup(
            self.ctxt, display_name='b_test_name',
            status=fields.BackupStatus.AVAILABLE)
        backup2 = test_utils.create_backup(
            self.ctxt, display_name='a_test_name',
            status=fields.BackupStatus.AVAILABLE)
        url = '/v3/%s/backups?sort_key=name' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, version=version)
        if version == '3.36':
            self.assertRaises(exception.InvalidInput,
                              self.controller.index,
                              req)
        else:
            expect = backup_view.ViewBuilder().summary_list(req,
                                                            [backup1, backup2])
            result = self.controller.index(req)
            self.assertEqual(expect, result)

    def test_backup_update(self):
        backup = test_utils.create_backup(
            self.ctxt,
            status=fields.BackupStatus.AVAILABLE)
        req = self._fake_update_request(fake.BACKUP_ID)
        new_name = "updated_test_name"
        new_description = "Updated Test description."
        updates = {
            "name": new_name,
            "description": new_description,
        }
        body = {"backup": updates}
        self.controller.update(req,
                               backup.id,
                               body)

        backup.refresh()
        self.assertEqual(new_name, backup.display_name)
        self.assertEqual(new_description,
                         backup.display_description)
