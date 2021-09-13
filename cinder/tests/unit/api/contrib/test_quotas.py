#
# Copyright 2013 OpenStack Foundation
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

"""Tests for cinder.api.contrib.quotas.py"""

from unittest import mock
import uuid

from oslo_config import cfg
from oslo_config import fixture as config_fixture
import webob.exc

from cinder.api.contrib import quotas
from cinder import context
from cinder import db
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.tests.unit import test_db_api


CONF = cfg.CONF


def make_body(root=True, gigabytes=1000, snapshots=10,
              volumes=10, backups=10, backup_gigabytes=1000,
              tenant_id=fake.PROJECT_ID, per_volume_gigabytes=-1, groups=10,
              subproject=False):
    resources = {'gigabytes': gigabytes,
                 'snapshots': snapshots,
                 'volumes': volumes,
                 'backups': backups,
                 'backup_gigabytes': backup_gigabytes,
                 'per_volume_gigabytes': per_volume_gigabytes,
                 'groups': groups}
    # need to consider preexisting volume types as well
    volume_types = db.volume_type_get_all(context.get_admin_context())

    for volume_type in volume_types:
        # default values for subproject are 0
        quota = 0 if subproject else -1
        resources['gigabytes_' + volume_type] = quota
        resources['snapshots_' + volume_type] = quota
        resources['volumes_' + volume_type] = quota

    if tenant_id:
        resources['id'] = tenant_id
    if root:
        result = {'quota_set': resources}
    else:
        result = resources
    return result


def make_subproject_body(root=True, gigabytes=0, snapshots=0,
                         volumes=0, backups=0, backup_gigabytes=0,
                         tenant_id=fake.PROJECT_ID, per_volume_gigabytes=0):
    return make_body(root=root, gigabytes=gigabytes, snapshots=snapshots,
                     volumes=volumes, backups=backups,
                     backup_gigabytes=backup_gigabytes, tenant_id=tenant_id,
                     per_volume_gigabytes=per_volume_gigabytes,
                     subproject=True)


class QuotaSetsControllerTestBase(test.TestCase):

    class FakeProject(object):

        def __init__(self, id=fake.PROJECT_ID, parent_id=None,
                     is_admin_project=False):
            self.id = id
            self.parent_id = parent_id
            self.subtree = None
            self.parents = None
            self.is_admin_project = is_admin_project

    def setUp(self):
        super(QuotaSetsControllerTestBase, self).setUp()

        self.controller = quotas.QuotaSetsController()

        self.req = mock.Mock()
        self.req.environ = {'cinder.context': context.get_admin_context()}
        self.req.environ['cinder.context'].is_admin = True
        self.req.params = {}

        self.req.environ['cinder.context'].project_id = uuid.uuid4().hex

        get_patcher = mock.patch('cinder.api.api_utils.get_project',
                                 self._get_project)
        get_patcher.start()
        self.addCleanup(get_patcher.stop)

        self.auth_url = 'http://localhost:5000'
        self.fixture = self.useFixture(config_fixture.Config(CONF))
        self.fixture.config(auth_url=self.auth_url, group='keystone_authtoken')

    def _get_project(self, context, id, subtree_as_ids=False,
                     parents_as_ids=False, is_admin_project=False):
        return self.project_by_id.get(id, self.FakeProject())

    def _create_fake_quota_usages(self, usage_map):
        self._fake_quota_usages = {}
        for key, val in usage_map.items():
            self._fake_quota_usages[key] = {'in_use': val}

    def _fake_quota_usage_get_all_by_project(self, context, project_id):
        return {'volumes': self._fake_quota_usages[project_id]}


class QuotaSetsControllerTest(QuotaSetsControllerTestBase):
    def test_defaults(self):
        result = self.controller.defaults(self.req, fake.PROJECT_ID)
        self.assertDictEqual(make_body(), result)

    def test_show(self):
        result = self.controller.show(self.req, fake.PROJECT_ID)
        self.assertDictEqual(make_body(), result)

    def test_show_not_authorized(self):
        self.req.environ['cinder.context'].is_admin = False
        self.req.environ['cinder.context'].user_id = fake.USER_ID
        self.req.environ['cinder.context'].project_id = fake.PROJECT_ID
        self.req.environ['cinder.context'].roles = ['member', 'reader']
        self.assertRaises(exception.PolicyNotAuthorized, self.controller.show,
                          self.req, fake.PROJECT2_ID)

    def test_show_non_admin_user(self):
        self.controller._get_quotas = mock.Mock(side_effect=
                                                self.controller._get_quotas)
        result = self.controller.show(self.req, fake.PROJECT_ID)
        self.assertDictEqual(make_body(), result)
        self.controller._get_quotas.assert_called_with(
            self.req.environ['cinder.context'], fake.PROJECT_ID, False)

    def test_show_with_invalid_usage_param(self):
        self.req.params = {'usage': 'InvalidBool'}
        self.assertRaises(exception.InvalidParameterValue,
                          self.controller.show,
                          self.req, fake.PROJECT2_ID)

    def test_show_with_valid_usage_param(self):
        self.req.params = {'usage': 'false'}
        result = self.controller.show(self.req, fake.PROJECT_ID)
        self.assertDictEqual(make_body(), result)

    def test_update(self):
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        result = self.controller.update(self.req, fake.PROJECT_ID, body=body)
        self.assertDictEqual(body, result)

        body = make_body(gigabytes=db.MAX_INT, tenant_id=None)
        result = self.controller.update(self.req, fake.PROJECT_ID, body=body)
        self.assertDictEqual(body, result)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_string_length')
    def test_update_limit(self, mock_validate):
        body = {'quota_set': {'volumes': 10}}
        result = self.controller.update(self.req, fake.PROJECT_ID, body=body)

        self.assertEqual(10, result['quota_set']['volumes'])
        self.assertTrue(mock_validate.called)

    def test_update_wrong_key(self):
        body = {'quota_set': {'bad': 'bad'}}
        self.assertRaises(exception.InvalidInput, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)

    def test_update_invalid_value_key_value(self):
        body = {'quota_set': {'gigabytes': "should_be_int"}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)

    def test_update_invalid_type_key_value(self):
        body = {'quota_set': {'gigabytes': None}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)

    def test_update_with_no_body(self):
        body = {}
        self.assertRaises(exception.ValidationError, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)

    def test_update_with_wrong_body(self):
        body = {'test': {}}
        self.assertRaises(exception.ValidationError, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)

    def test_update_multi_value_with_bad_data(self):
        orig_quota = self.controller.show(self.req, fake.PROJECT_ID)
        body = make_body(gigabytes=2000, snapshots=15, volumes="should_be_int",
                         backups=5, tenant_id=None)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)
        # Verify that quota values are not updated in db
        new_quota = self.controller.show(self.req, fake.PROJECT_ID)
        self.assertDictEqual(orig_quota, new_quota)

    def test_update_bad_quota_limit(self):
        body = {'quota_set': {'gigabytes': -1000}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)
        body = {'quota_set': {'gigabytes': db.MAX_INT + 1}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)

    def test_update_no_admin(self):
        self.req.environ['cinder.context'].is_admin = False
        self.req.environ['cinder.context'].project_id = fake.PROJECT_ID
        self.req.environ['cinder.context'].user_id = 'foo_user'
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.update, self.req, fake.PROJECT_ID,
                          body=make_body(tenant_id=None))

    def test_update_without_quota_set_field(self):
        body = {'fake_quota_set': {'gigabytes': 100}}
        self.assertRaises(exception.ValidationError, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)

    def test_update_empty_body(self):
        body = {}
        self.assertRaises(exception.ValidationError, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)

    def _commit_quota_reservation(self):
        # Create simple quota and quota usage.
        ctxt = context.get_admin_context()
        res = test_db_api._quota_reserve(ctxt, fake.PROJECT_ID)
        db.reservation_commit(ctxt, res, fake.PROJECT_ID)
        expected = {'project_id': fake.PROJECT_ID,
                    'volumes': {'reserved': 0, 'in_use': 1},
                    'gigabytes': {'reserved': 0, 'in_use': 2},
                    }
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(ctxt,
                                                           fake.PROJECT_ID))

    def test_update_lower_than_existing_resources(self):
        self._commit_quota_reservation()
        body = {'quota_set': {'volumes': 0}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)
        # Ensure that validation works even if some resources are valid
        body = {'quota_set': {'gigabytes': 1, 'volumes': 10}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body=body)

    def test_delete(self):
        result_show = self.controller.show(self.req, fake.PROJECT_ID)
        self.assertDictEqual(make_body(), result_show)

        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5,
                         backup_gigabytes=1000, tenant_id=None)
        result_update = self.controller.update(self.req, fake.PROJECT_ID,
                                               body=body)
        self.assertDictEqual(body, result_update)

        self.controller.delete(self.req, fake.PROJECT_ID)

        result_show_after = self.controller.show(self.req, fake.PROJECT_ID)
        self.assertDictEqual(result_show, result_show_after)

    def test_delete_with_allocated_quota_different_from_zero(self):
        project_id_1 = uuid.uuid4().hex
        project_id_2 = uuid.uuid4().hex
        self.req.environ['cinder.context'].project_id = project_id_1

        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5,
                         backup_gigabytes=1000, tenant_id=None)
        result_update = self.controller.update(self.req, project_id_1,
                                               body=body)
        self.assertDictEqual(body, result_update)

        # Set usage param to True in order to see get allocated values.
        self.req.params = {'usage': 'True'}
        result_show = self.controller.show(self.req, project_id_1)

        result_update = self.controller.update(self.req, project_id_2,
                                               body=body)
        self.assertDictEqual(body, result_update)

        self.controller.delete(self.req, project_id_2)

        result_show_after = self.controller.show(self.req, project_id_1)
        self.assertDictEqual(result_show, result_show_after)

    def test_delete_no_admin(self):
        self.req.environ['cinder.context'].is_admin = False
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.delete, self.req, fake.PROJECT_ID)
