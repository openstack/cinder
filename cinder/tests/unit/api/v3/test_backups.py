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

import copy
import ddt
import mock
from oslo_serialization import jsonutils
from oslo_utils import strutils
import webob

from cinder.api import microversions as mv
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
        self.user_context = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)

    def _fake_update_request(self, backup_id, version=mv.BACKUP_UPDATE):
        req = fakes.HTTPRequest.blank('/v3/%s/backups/%s/update' %
                                      (fake.PROJECT_ID, backup_id))
        req.environ['cinder.context'].is_admin = True
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume ' + version
        req.api_version_request = api_version.APIVersionRequest(version)
        return req

    def test_update_wrong_version(self):
        req = self._fake_update_request(
            fake.BACKUP_ID, version=mv.get_prior_version(mv.BACKUP_UPDATE))
        body = {"backup": {"name": "Updated Test Name", }}
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.update, req, fake.BACKUP_ID,
                          body)

    def test_backup_update_with_no_body(self):
        # omit body from the request
        req = self._fake_update_request(fake.BACKUP_ID)
        self.assertRaises(exception.ValidationError,
                          self.controller.update,
                          req, fake.BACKUP_ID, body=None)

    def test_backup_update_with_unsupported_field(self):
        req = self._fake_update_request(fake.BACKUP_ID)
        body = {"backup": {"id": fake.BACKUP2_ID,
                           "description": "", }}
        self.assertRaises(exception.ValidationError,
                          self.controller.update,
                          req, fake.BACKUP_ID, body=body)

    def test_backup_update_with_backup_not_found(self):
        req = self._fake_update_request(fake.BACKUP_ID)
        updates = {
            "name": "Updated Test Name",
            "description": "Updated Test description.",
        }
        body = {"backup": updates}
        self.assertRaises(exception.NotFound,
                          self.controller.update,
                          req, fake.BACKUP_ID, body=body)

    def _create_multiple_backups_with_different_project(self):
        test_utils.create_backup(
            context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True))
        test_utils.create_backup(
            context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True))
        test_utils.create_backup(
            context.RequestContext(fake.USER_ID, fake.PROJECT2_ID, True))

    @ddt.data('backups', 'backups/detail')
    def test_list_backup_with_count_param_version_not_matched(self, action):
        self._create_multiple_backups_with_different_project()

        is_detail = True if 'detail' in action else False
        req = fakes.HTTPRequest.blank("/v3/%s?with_count=True" % action)
        req.headers = mv.get_mv_header(
            mv.get_prior_version(mv.SUPPORT_COUNT_INFO))
        req.api_version_request = mv.get_api_version(
            mv.get_prior_version(mv.SUPPORT_COUNT_INFO))
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._get_backups(req, is_detail=is_detail)
        self.assertNotIn('count', res_dict)

    @ddt.data({'method': 'backups',
               'display_param': 'True'},
              {'method': 'backups',
               'display_param': 'False'},
              {'method': 'backups',
               'display_param': '1'},
              {'method': 'backups/detail',
               'display_param': 'True'},
              {'method': 'backups/detail',
               'display_param': 'False'},
              {'method': 'backups/detail',
               'display_param': '1'}
              )
    @ddt.unpack
    def test_list_backups_with_count_param(self, method, display_param):
        self._create_multiple_backups_with_different_project()

        is_detail = True if 'detail' in method else False
        show_count = strutils.bool_from_string(display_param, strict=True)
        # Request with 'with_count' and 'limit'
        req = fakes.HTTPRequest.blank(
            "/v3/%s?with_count=%s&limit=1" % (method, display_param))
        req.headers = mv.get_mv_header(mv.SUPPORT_COUNT_INFO)
        req.api_version_request = mv.get_api_version(mv.SUPPORT_COUNT_INFO)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._get_backups(req, is_detail=is_detail)
        self.assertEqual(1, len(res_dict['backups']))
        if show_count:
            self.assertEqual(2, res_dict['count'])
        else:
            self.assertNotIn('count', res_dict)

        # Request with 'with_count'
        req = fakes.HTTPRequest.blank(
            "/v3/%s?with_count=%s" % (method, display_param))
        req.headers = mv.get_mv_header(mv.SUPPORT_COUNT_INFO)
        req.api_version_request = mv.get_api_version(mv.SUPPORT_COUNT_INFO)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._get_backups(req, is_detail=is_detail)
        self.assertEqual(2, len(res_dict['backups']))
        if show_count:
            self.assertEqual(2, res_dict['count'])
        else:
            self.assertNotIn('count', res_dict)

        # Request with admin context and 'all_tenants'
        req = fakes.HTTPRequest.blank(
            "/v3/%s?with_count=%s&all_tenants=1" % (method, display_param))
        req.headers = mv.get_mv_header(mv.SUPPORT_COUNT_INFO)
        req.api_version_request = mv.get_api_version(mv.SUPPORT_COUNT_INFO)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._get_backups(req, is_detail=is_detail)
        self.assertEqual(3, len(res_dict['backups']))
        if show_count:
            self.assertEqual(3, res_dict['count'])
        else:
            self.assertNotIn('count', res_dict)

    @ddt.data(mv.get_prior_version(mv.RESOURCE_FILTER),
              mv.RESOURCE_FILTER,
              mv.LIKE_FILTER)
    @mock.patch('cinder.api.common.reject_invalid_filters')
    def test_backup_list_with_general_filter(self, version, mock_update):
        url = '/v3/%s/backups' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url,
                                      version=version,
                                      use_admin_context=False)
        self.controller.index(req)

        if version != mv.get_prior_version(mv.RESOURCE_FILTER):
            support_like = True if version == mv.LIKE_FILTER else False
            mock_update.assert_called_once_with(req.environ['cinder.context'],
                                                mock.ANY, 'backup',
                                                support_like)

    @ddt.data(mv.get_prior_version(mv.BACKUP_SORT_NAME),
              mv.BACKUP_SORT_NAME)
    def test_backup_list_with_name(self, version):
        backup1 = test_utils.create_backup(
            self.ctxt, display_name='b_test_name',
            status=fields.BackupStatus.AVAILABLE)
        backup2 = test_utils.create_backup(
            self.ctxt, display_name='a_test_name',
            status=fields.BackupStatus.AVAILABLE)
        url = '/v3/%s/backups?sort_key=name' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, version=version)
        if version == mv.get_prior_version(mv.BACKUP_SORT_NAME):
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
                               body=body)

        backup.refresh()
        self.assertEqual(new_name, backup.display_name)
        self.assertEqual(new_description,
                         backup.display_description)

    @ddt.data({"backup": {"description": "   sample description",
                          "name": "   test name"}},
              {"backup": {"description": "sample description   ",
                          "name": "test  "}},
              {"backup": {"description": " sample description ",
                          "name": "  test  "}})
    def test_backup_update_name_description_with_leading_trailing_spaces(
            self, body):
        backup = test_utils.create_backup(
            self.ctxt,
            status=fields.BackupStatus.AVAILABLE)
        req = self._fake_update_request(fake.BACKUP_ID)

        expected_body = copy.deepcopy(body)
        self.controller.update(req,
                               backup.id,
                               body=body)
        backup.refresh()

        # backup update call doesn't return 'description' in response so get
        # the updated backup to assert name and description
        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(expected_body['backup']['name'].strip(),
                         res_dict['backup']['name'])
        self.assertEqual(expected_body['backup']['description'].strip(),
                         res_dict['backup']['description'])

    @ddt.data(mv.get_prior_version(mv.BACKUP_METADATA),
              mv.BACKUP_METADATA)
    def test_backup_show_with_metadata(self, version):
        backup = test_utils.create_backup(
            self.ctxt, display_name='test_backup_metadata',
            status=fields.BackupStatus.AVAILABLE)
        # show backup metadata
        url = '/v3/%s/backups/%s' % (fake.PROJECT_ID, backup.id)
        req = fakes.HTTPRequest.blank(url, version=version)
        backup_get = self.controller.show(req, backup.id)['backup']
        if version == mv.get_prior_version(mv.BACKUP_METADATA):
            self.assertNotIn('metadata', backup_get)
        else:
            self.assertIn('metadata', backup_get)

    def test_backup_update_with_null_validate(self):
        backup = test_utils.create_backup(
            self.ctxt,
            status=fields.BackupStatus.AVAILABLE)
        req = self._fake_update_request(fake.BACKUP_ID)

        updates = {
            "name": None,
        }
        body = {"backup": updates}
        self.controller.update(req,
                               backup.id,
                               body=body)

        backup.refresh()
        self.assertEqual(fields.BackupStatus.AVAILABLE, backup.status)
