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

"""
Tests for cinder.api.contrib.quotas.py
"""


import mock

import uuid
import webob.exc

from cinder.api.contrib import quotas
from cinder import context
from cinder import db
from cinder import exception
from cinder import quota
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test_db_api


from oslo_config import cfg
from oslo_config import fixture as config_fixture


CONF = cfg.CONF


def make_body(root=True, gigabytes=1000, snapshots=10,
              volumes=10, backups=10, backup_gigabytes=1000,
              tenant_id=fake.PROJECT_ID, per_volume_gigabytes=-1, groups=10):
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
        resources['gigabytes_' + volume_type] = -1
        resources['snapshots_' + volume_type] = -1
        resources['volumes_' + volume_type] = -1

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
                     per_volume_gigabytes=per_volume_gigabytes)


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

        self._create_project_hierarchy()
        self.req.environ['cinder.context'].project_id = self.A.id

        get_patcher = mock.patch('cinder.quota_utils.get_project_hierarchy',
                                 self._get_project)
        get_patcher.start()
        self.addCleanup(get_patcher.stop)

        def _list_projects(context):
            return self.project_by_id.values()

        list_patcher = mock.patch('cinder.quota_utils.get_all_projects',
                                  _list_projects)
        list_patcher.start()
        self.addCleanup(list_patcher.stop)

        self.auth_url = 'http://localhost:5000'
        self.fixture = self.useFixture(config_fixture.Config(CONF))
        self.fixture.config(auth_uri=self.auth_url, group='keystone_authtoken')

    def _create_project_hierarchy(self):
        r"""Sets an environment used for nested quotas tests.

        Create a project hierarchy such as follows:
        +-----------+
        |           |
        |     A     |
        |    / \    |
        |   B   C   |
        |  /        |
        | D         |
        +-----------+
        """
        self.A = self.FakeProject(id=uuid.uuid4().hex, parent_id=None)
        self.B = self.FakeProject(id=uuid.uuid4().hex, parent_id=self.A.id)
        self.C = self.FakeProject(id=uuid.uuid4().hex, parent_id=self.A.id)
        self.D = self.FakeProject(id=uuid.uuid4().hex, parent_id=self.B.id)

        # update projects subtrees
        self.B.subtree = {self.D.id: self.D.subtree}
        self.A.subtree = {self.B.id: self.B.subtree, self.C.id: self.C.subtree}

        self.A.parents = None
        self.B.parents = {self.A.id: None}
        self.C.parents = {self.A.id: None}
        self.D.parents = {self.B.id: self.B.parents}

        # project_by_id attribute is used to recover a project based on its id.
        self.project_by_id = {self.A.id: self.A, self.B.id: self.B,
                              self.C.id: self.C, self.D.id: self.D}

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
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
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
        result = self.controller.update(self.req, fake.PROJECT_ID, body)
        self.assertDictEqual(body, result)

        body = make_body(gigabytes=db.MAX_INT, tenant_id=None)
        result = self.controller.update(self.req, fake.PROJECT_ID, body)
        self.assertDictEqual(body, result)

    def test_update_subproject_not_in_hierarchy_non_nested(self):
        # When not using nested quotas, the hierarchy should not be considered
        # for an update
        E = self.FakeProject(id=uuid.uuid4().hex, parent_id=None)
        F = self.FakeProject(id=uuid.uuid4().hex, parent_id=E.id)
        E.subtree = {F.id: F.subtree}
        self.project_by_id[E.id] = E
        self.project_by_id[F.id] = F

        # Update the project A quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        result = self.controller.update(self.req, self.A.id, body)
        self.assertDictEqual(body, result)
        # Try to update the quota of F, it will be allowed even though
        # project E doesn't belong to the project hierarchy of A, because
        # we are NOT using the nested quota driver
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        self.controller.update(self.req, F.id, body)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_string_length')
    @mock.patch(
        'cinder.utils.validate_integer')
    def test_update_limit(self, mock_validate_integer, mock_validate):
        mock_validate_integer.return_value = 10

        body = {'quota_set': {'volumes': 10}}
        result = self.controller.update(self.req, fake.PROJECT_ID, body)

        self.assertEqual(10, result['quota_set']['volumes'])
        self.assertTrue(mock_validate.called)
        self.assertTrue(mock_validate_integer.called)

    def test_update_wrong_key(self):
        body = {'quota_set': {'bad': 'bad'}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body)

    def test_update_invalid_value_key_value(self):
        body = {'quota_set': {'gigabytes': "should_be_int"}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body)

    def test_update_invalid_type_key_value(self):
        body = {'quota_set': {'gigabytes': None}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body)

    def test_update_multi_value_with_bad_data(self):
        orig_quota = self.controller.show(self.req, fake.PROJECT_ID)
        body = make_body(gigabytes=2000, snapshots=15, volumes="should_be_int",
                         backups=5, tenant_id=None)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body)
        # Verify that quota values are not updated in db
        new_quota = self.controller.show(self.req, fake.PROJECT_ID)
        self.assertDictEqual(orig_quota, new_quota)

    def test_update_bad_quota_limit(self):
        body = {'quota_set': {'gigabytes': -1000}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body)
        body = {'quota_set': {'gigabytes': db.MAX_INT + 1}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body)

    def test_update_no_admin(self):
        self.req.environ['cinder.context'].is_admin = False
        self.req.environ['cinder.context'].project_id = fake.PROJECT_ID
        self.req.environ['cinder.context'].user_id = 'foo_user'
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.update, self.req, fake.PROJECT_ID,
                          make_body(tenant_id=None))

    def test_update_without_quota_set_field(self):
        body = {'fake_quota_set': {'gigabytes': 100}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body)

    def test_update_empty_body(self):
        body = {}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body)

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

    def test_update_lower_than_existing_resources_when_skip_false(self):
        self._commit_quota_reservation()
        body = {'quota_set': {'volumes': 0},
                'skip_validation': 'false'}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body)
        # Ensure that validation works even if some resources are valid
        body = {'quota_set': {'gigabytes': 1, 'volumes': 10},
                'skip_validation': 'false'}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, fake.PROJECT_ID, body)

    def test_update_lower_than_existing_resources_when_skip_true(self):
        self._commit_quota_reservation()
        body = {'quota_set': {'volumes': 0},
                'skip_validation': 'true'}
        result = self.controller.update(self.req, fake.PROJECT_ID, body)
        self.assertEqual(body['quota_set']['volumes'],
                         result['quota_set']['volumes'])

    def test_update_lower_than_existing_resources_without_skip_argument(self):
        self._commit_quota_reservation()
        body = {'quota_set': {'volumes': 0}}
        result = self.controller.update(self.req, fake.PROJECT_ID, body)
        self.assertEqual(body['quota_set']['volumes'],
                         result['quota_set']['volumes'])

    def test_delete(self):
        result_show = self.controller.show(self.req, fake.PROJECT_ID)
        self.assertDictEqual(make_body(), result_show)

        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5,
                         backup_gigabytes=1000, tenant_id=None)
        result_update = self.controller.update(self.req, fake.PROJECT_ID, body)
        self.assertDictEqual(body, result_update)

        self.controller.delete(self.req, fake.PROJECT_ID)

        result_show_after = self.controller.show(self.req, fake.PROJECT_ID)
        self.assertDictEqual(result_show, result_show_after)

    def test_delete_with_allocated_quota_different_from_zero(self):
        self.req.environ['cinder.context'].project_id = self.A.id

        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5,
                         backup_gigabytes=1000, tenant_id=None)
        result_update = self.controller.update(self.req, self.A.id, body)
        self.assertDictEqual(body, result_update)

        # Set usage param to True in order to see get allocated values.
        self.req.params = {'usage': 'True'}
        result_show = self.controller.show(self.req, self.A.id)

        result_update = self.controller.update(self.req, self.B.id, body)
        self.assertDictEqual(body, result_update)

        self.controller.delete(self.req, self.B.id)

        result_show_after = self.controller.show(self.req, self.A.id)
        self.assertDictEqual(result_show, result_show_after)

    def test_delete_no_admin(self):
        self.req.environ['cinder.context'].is_admin = False
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.delete, self.req, fake.PROJECT_ID)

    def test_subproject_show_not_using_nested_quotas(self):
        # Current roles say for non-nested quotas, an admin should be able to
        # see anyones quota
        self.req.environ['cinder.context'].project_id = self.B.id
        self.controller.show(self.req, self.C.id)
        self.controller.show(self.req, self.A.id)


class QuotaSetControllerValidateNestedQuotaSetup(QuotaSetsControllerTestBase):
    """Validates the setup before using NestedQuota driver.

    Test case validates flipping on NestedQuota driver after using the
    non-nested quota driver for some time.
    """

    def _create_project_hierarchy(self):
        r"""Sets an environment used for nested quotas tests.

        Create a project hierarchy such as follows:
        +-----------------+
        |                 |
        |     A    G   E  |
        |    / \       \  |
        |   B   C       F |
        |  /              |
        | D               |
        +-----------------+
        """
        super(QuotaSetControllerValidateNestedQuotaSetup,
              self)._create_project_hierarchy()
        # Project A, B, C, D are already defined by parent test class
        self.E = self.FakeProject(id=uuid.uuid4().hex, parent_id=None)
        self.F = self.FakeProject(id=uuid.uuid4().hex, parent_id=self.E.id)
        self.G = self.FakeProject(id=uuid.uuid4().hex, parent_id=None)

        self.E.subtree = {self.F.id: self.F.subtree}

        self.project_by_id.update({self.E.id: self.E, self.F.id: self.F,
                                   self.G.id: self.G})

    def test_validate_nested_quotas_no_in_use_vols(self):
        # Update the project A quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        quota = {'volumes': 5}
        body = {'quota_set': quota}
        self.controller.update(self.req, self.A.id, body)

        quota['volumes'] = 3
        self.controller.update(self.req, self.B.id, body)
        # Allocated value for quota A is borked, because update was done
        # without nested quota driver
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_setup_for_nested_quota_use,
                          self.req)

        # Fix the allocated values in DB
        self.req.params['fix_allocated_quotas'] = True
        self.controller.validate_setup_for_nested_quota_use(
            self.req)

        self.req.params['fix_allocated_quotas'] = False
        # Ensure that we've properly fixed the allocated quotas
        self.controller.validate_setup_for_nested_quota_use(self.req)

        # Over-allocate the quotas between children
        self.controller.update(self.req, self.C.id, body)

        # This is we should fail because the child limits are too big
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_setup_for_nested_quota_use,
                          self.req)

        quota['volumes'] = 1
        self.controller.update(self.req, self.C.id, body)

        # Make sure we're validating all hierarchy trees
        self.req.environ['cinder.context'].project_id = self.E.id
        quota['volumes'] = 1
        self.controller.update(self.req, self.E.id, body)
        quota['volumes'] = 3
        self.controller.update(self.req, self.F.id, body)

        self.assertRaises(
            webob.exc.HTTPBadRequest,
            self.controller.validate_setup_for_nested_quota_use,
            self.req)

        # Put quotas in a good state
        quota['volumes'] = 1
        self.controller.update(self.req, self.F.id, body)
        self.req.params['fix_allocated_quotas'] = True
        self.controller.validate_setup_for_nested_quota_use(self.req)

    @mock.patch('cinder.db.quota_usage_get_all_by_project')
    def test_validate_nested_quotas_in_use_vols(self, mock_usage):
        self._create_fake_quota_usages(
            {self.A.id: 1, self.B.id: 1, self.D.id: 0, self.C.id: 3,
             self.E.id: 0, self.F.id: 0, self.G.id: 0})
        mock_usage.side_effect = self._fake_quota_usage_get_all_by_project

        # Update the project A quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        quota_limit = {'volumes': 7}
        body = {'quota_set': quota_limit}
        self.controller.update(self.req, self.A.id, body)

        quota_limit['volumes'] = 3
        self.controller.update(self.req, self.B.id, body)

        quota_limit['volumes'] = 3
        self.controller.update(self.req, self.C.id, body)

        self.req.params['fix_allocated_quotas'] = True
        self.controller.validate_setup_for_nested_quota_use(self.req)

        quota_limit['volumes'] = 6
        self.controller.update(self.req, self.A.id, body)

        # Should fail because the one in_use volume of 'A'
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            self.controller.validate_setup_for_nested_quota_use,
            self.req)

    @mock.patch('cinder.db.quota_usage_get_all_by_project')
    def test_validate_nested_quotas_quota_borked(self, mock_usage):
        self._create_fake_quota_usages(
            {self.A.id: 1, self.B.id: 1, self.D.id: 0, self.C.id: 3,
             self.E.id: 0, self.F.id: 0, self.G.id: 0})
        mock_usage.side_effect = self._fake_quota_usage_get_all_by_project

        # Update the project A quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        quota_limit = {'volumes': 7}
        body = {'quota_set': quota_limit}
        self.controller.update(self.req, self.A.id, body)

        # Other quotas would default to 0 but already have some limit being
        # used
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            self.controller.validate_setup_for_nested_quota_use,
            self.req)

    @mock.patch('cinder.db.quota_usage_get_all_by_project')
    def test_validate_nested_quota_negative_limits(self, mock_usage):
        # TODO(mc_nair): this test case can be moved to Tempest once nested
        # quota coverage added
        self._create_fake_quota_usages(
            {self.A.id: 1, self.B.id: 3, self.C.id: 0, self.D.id: 2,
             self.E.id: 2, self.F.id: 0, self.G.id: 0})
        mock_usage.side_effect = self._fake_quota_usage_get_all_by_project

        # Setting E-F as children of D for this test case to flex the muscles
        # of more complex nesting
        self.D.subtree = {self.E.id: self.E.subtree}
        self.E.parent_id = self.D.id
        # Get B's subtree up to date with this change
        self.B.subtree[self.D.id] = self.D.subtree

        # Quota hierarchy now is
        #   / B - D - E - F
        # A
        #   \ C
        #
        # G

        self.req.environ['cinder.context'].project_id = self.A.id
        quota_limit = {'volumes': 10}
        body = {'quota_set': quota_limit}
        self.controller.update(self.req, self.A.id, body)

        quota_limit['volumes'] = 1
        self.controller.update(self.req, self.C.id, body)

        quota_limit['volumes'] = -1
        self.controller.update(self.req, self.B.id, body)
        self.controller.update(self.req, self.D.id, body)
        self.controller.update(self.req, self.F.id, body)
        quota_limit['volumes'] = 5
        self.controller.update(self.req, self.E.id, body)

        # Should fail because too much is allocated to children for A
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_setup_for_nested_quota_use,
                          self.req)

        # When root has -1 limit, children can allocate as much as they want
        quota_limit['volumes'] = -1
        self.controller.update(self.req, self.A.id, body)
        self.req.params['fix_allocated_quotas'] = True
        self.controller.validate_setup_for_nested_quota_use(self.req)

        # Not unlimited, but make children's allocated within bounds
        quota_limit['volumes'] = 10
        self.controller.update(self.req, self.A.id, body)
        quota_limit['volumes'] = 3
        self.controller.update(self.req, self.E.id, body)
        self.req.params['fix_allocated_quotas'] = True
        self.controller.validate_setup_for_nested_quota_use(self.req)
        self.req.params['fix_allocated_quotas'] = False
        self.controller.validate_setup_for_nested_quota_use(self.req)


class QuotaSetsControllerNestedQuotasTest(QuotaSetsControllerTestBase):
    def setUp(self):
        super(QuotaSetsControllerNestedQuotasTest, self).setUp()
        driver = quota.NestedDbQuotaDriver()
        patcher = mock.patch('cinder.quota.VolumeTypeQuotaEngine._driver',
                             driver)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_subproject_defaults(self):
        context = self.req.environ['cinder.context']
        context.project_id = self.B.id
        result = self.controller.defaults(self.req, self.B.id)
        expected = make_subproject_body(tenant_id=self.B.id)
        self.assertDictEqual(expected, result)

    def test_subproject_show(self):
        self.req.environ['cinder.context'].project_id = self.A.id
        result = self.controller.show(self.req, self.B.id)
        expected = make_subproject_body(tenant_id=self.B.id)
        self.assertDictEqual(expected, result)

    def test_subproject_show_in_hierarchy(self):
        # A user scoped to a root project in a hierarchy can see its children
        # quotas.
        self.req.environ['cinder.context'].project_id = self.A.id
        result = self.controller.show(self.req, self.D.id)
        expected = make_subproject_body(tenant_id=self.D.id)
        self.assertDictEqual(expected, result)
        # A user scoped to a parent project can see its immediate children
        # quotas.
        self.req.environ['cinder.context'].project_id = self.B.id
        result = self.controller.show(self.req, self.D.id)
        expected = make_subproject_body(tenant_id=self.D.id)
        self.assertDictEqual(expected, result)

    def test_subproject_show_not_in_hierarchy_admin_context(self):
        E = self.FakeProject(id=uuid.uuid4().hex, parent_id=None,
                             is_admin_project=True)
        self.project_by_id[E.id] = E
        self.req.environ['cinder.context'].project_id = E.id
        result = self.controller.show(self.req, self.B.id)
        expected = make_subproject_body(tenant_id=self.B.id)
        self.assertDictEqual(expected, result)

    def test_subproject_show_target_project_equals_to_context_project(
            self):
        self.req.environ['cinder.context'].project_id = self.B.id
        result = self.controller.show(self.req, self.B.id)
        expected = make_subproject_body(tenant_id=self.B.id)
        self.assertDictEqual(expected, result)

    def test_subproject_show_not_authorized(self):
        self.req.environ['cinder.context'].project_id = self.B.id
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
                          self.req, self.C.id)
        self.req.environ['cinder.context'].project_id = self.B.id
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
                          self.req, self.A.id)

    def test_update_subproject_not_in_hierarchy(self):
        # Create another project hierarchy
        E = self.FakeProject(id=uuid.uuid4().hex, parent_id=None)
        F = self.FakeProject(id=uuid.uuid4().hex, parent_id=E.id)
        E.subtree = {F.id: F.subtree}
        self.project_by_id[E.id] = E
        self.project_by_id[F.id] = F

        # Update the project A quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        result = self.controller.update(self.req, self.A.id, body)
        self.assertDictEqual(body, result)
        # Try to update the quota of F, it will not be allowed, since the
        # project E doesn't belongs to the project hierarchy of A.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.update, self.req, F.id, body)

    def test_update_subproject_not_in_hierarchy_admin_context(self):
        E = self.FakeProject(id=uuid.uuid4().hex, parent_id=None,
                             is_admin_project=True)
        self.project_by_id[E.id] = E
        self.req.environ['cinder.context'].project_id = E.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        # Update the project A quota, not in the project hierarchy
        # of E but it will be allowed because E is the cloud admin.
        result = self.controller.update(self.req, self.A.id, body)
        self.assertDictEqual(body, result)
        # Update the quota of B to be equal to its parent A.
        result = self.controller.update(self.req, self.B.id, body)
        self.assertDictEqual(body, result)
        # Remove the admin role from project E
        E.is_admin_project = False
        # Now updating the quota of B will fail, because it is not
        # a member of E's hierarchy and E is no longer a cloud admin.
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.update, self.req, self.B.id, body)

    def test_update_subproject(self):
        # Update the project A quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        result = self.controller.update(self.req, self.A.id, body)
        self.assertDictEqual(body, result)
        # Update the quota of B to be equal to its parent quota
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        result = self.controller.update(self.req, self.B.id, body)
        self.assertDictEqual(body, result)
        # Try to update the quota of C, it will not be allowed, since the
        # project A doesn't have free quota available.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, self.C.id, body)
        # Successfully update the quota of D.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=1000, snapshots=7,
                         volumes=3, backups=3, tenant_id=None)
        result = self.controller.update(self.req, self.D.id, body)
        self.assertDictEqual(body, result)
        # An admin of B can also update the quota of D, since D is its
        # immediate child.
        self.req.environ['cinder.context'].project_id = self.B.id
        body = make_body(gigabytes=1500, snapshots=10,
                         volumes=4, backups=4, tenant_id=None)
        self.controller.update(self.req, self.D.id, body)

    def test_update_subproject_repetitive(self):
        # Update the project A volumes quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=10, backups=5, tenant_id=None)
        result = self.controller.update(self.req, self.A.id, body)
        self.assertDictEqual(body, result)
        # Update the quota of B to be equal to its parent quota
        # three times should be successful, the quota will not be
        # allocated to 'allocated' value of parent project
        for i in range(0, 3):
            self.req.environ['cinder.context'].project_id = self.A.id
            body = make_body(gigabytes=2000, snapshots=15,
                             volumes=10, backups=5, tenant_id=None)
            result = self.controller.update(self.req, self.B.id, body)
            self.assertDictEqual(body, result)

    def test_update_subproject_with_not_root_context_project(self):
        # Update the project A quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        result = self.controller.update(self.req, self.A.id, body)
        self.assertDictEqual(body, result)
        # Try to update the quota of B, it will not be allowed, since the
        # project in the context (B) is not a root project.
        self.req.environ['cinder.context'].project_id = self.B.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          self.req, self.B.id, body)

    def test_update_subproject_quota_when_parent_has_default_quotas(self):
        # Since the quotas of the project A were not updated, it will have
        # default quotas.
        self.req.environ['cinder.context'].project_id = self.A.id
        # Update the project B quota.
        expected = make_body(gigabytes=1000, snapshots=10,
                             volumes=5, backups=5, tenant_id=None)
        result = self.controller.update(self.req, self.B.id, expected)
        self.assertDictEqual(expected, result)

    def _assert_quota_show(self, proj_id, resource, in_use=0, reserved=0,
                           allocated=0, limit=0):
        self.req.params = {'usage': 'True'}
        show_res = self.controller.show(self.req, proj_id)
        expected = {'in_use': in_use, 'reserved': reserved,
                    'allocated': allocated, 'limit': limit}
        self.assertEqual(expected, show_res['quota_set'][resource])

    def test_project_allocated_considered_on_reserve(self):
        def _reserve(project_id):
            quotas.QUOTAS._driver.reserve(
                self.req.environ['cinder.context'], quotas.QUOTAS.resources,
                {'volumes': 1}, project_id=project_id)

        # A's quota will default to 10 for volumes
        quota = {'volumes': 5}
        body = {'quota_set': quota}
        self.controller.update(self.req, self.B.id, body)
        self._assert_quota_show(self.A.id, 'volumes', allocated=5, limit=10)
        quota['volumes'] = 3
        self.controller.update(self.req, self.C.id, body)
        self._assert_quota_show(self.A.id, 'volumes', allocated=8, limit=10)
        _reserve(self.A.id)
        _reserve(self.A.id)
        self.assertRaises(exception.OverQuota, _reserve, self.A.id)

    def test_update_parent_project_lower_than_child(self):
        # A's quota will be default of 10
        quota = {'volumes': 10}
        body = {'quota_set': quota}
        self.controller.update(self.req, self.B.id, body)
        quota['volumes'] = 9
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, self.req, self.A.id, body)

    def test_project_delete_with_default_quota_less_than_in_use(self):
        quota = {'volumes': 11}
        body = {'quota_set': quota}
        self.controller.update(self.req, self.A.id, body)
        quotas.QUOTAS._driver.reserve(
            self.req.environ['cinder.context'], quotas.QUOTAS.resources,
            quota, project_id=self.A.id)
        # Should not be able to delete if it will cause the used values to go
        # over quota when nested quotas are used
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete,
                          self.req,
                          self.A.id)

    def test_subproject_delete_with_default_quota_less_than_in_use(self):
        quota = {'volumes': 1}
        body = {'quota_set': quota}
        self.controller.update(self.req, self.B.id, body)
        quotas.QUOTAS._driver.reserve(
            self.req.environ['cinder.context'], quotas.QUOTAS.resources,
            quota, project_id=self.B.id)

        # Should not be able to delete if it will cause the used values to go
        # over quota when nested quotas are used
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete,
                          self.req,
                          self.B.id)

    def test_subproject_delete(self):
        self.req.environ['cinder.context'].project_id = self.A.id

        body = make_body(gigabytes=2000, snapshots=15, volumes=5, backups=5,
                         backup_gigabytes=1000, tenant_id=None)
        result_update = self.controller.update(self.req, self.A.id, body)
        self.assertDictEqual(body, result_update)

        # Set usage param to True in order to see get allocated values.
        self.req.params = {'usage': 'True'}
        result_show = self.controller.show(self.req, self.A.id)

        result_update = self.controller.update(self.req, self.B.id, body)
        self.assertDictEqual(body, result_update)

        self.controller.delete(self.req, self.B.id)

        result_show_after = self.controller.show(self.req, self.A.id)
        self.assertDictEqual(result_show, result_show_after)

    def test_subproject_delete_not_considering_default_quotas(self):
        """Test delete subprojects' quotas won't consider default quotas.

        Test plan:
        - Update the volume quotas of project A
        - Update the volume quotas of project B
        - Delete the quotas of project B

        Resources with default quotas aren't expected to be considered when
        updating the allocated values of the parent project. Thus, the delete
        operation should succeed.
        """
        self.req.environ['cinder.context'].project_id = self.A.id

        body = {'quota_set': {'volumes': 5}}
        result = self.controller.update(self.req, self.A.id, body)
        self.assertEqual(body['quota_set']['volumes'],
                         result['quota_set']['volumes'])

        body = {'quota_set': {'volumes': 2}}
        result = self.controller.update(self.req, self.B.id, body)
        self.assertEqual(body['quota_set']['volumes'],
                         result['quota_set']['volumes'])

        self.controller.delete(self.req, self.B.id)

    def test_subproject_delete_with_child_present(self):
        # Update the project A quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(volumes=5)
        self.controller.update(self.req, self.A.id, body)

        # Allocate some of that quota to a child project
        body = make_body(volumes=3)
        self.controller.update(self.req, self.B.id, body)

        # Deleting 'A' should be disallowed since 'B' is using some of that
        # quota
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          self.req, self.A.id)

    def test_subproject_delete_with_child_updates_parent_allocated(self):
        quota = {'volumes': 5}
        body = {'quota_set': quota}
        self.controller.update(self.req, self.A.id, body)

        # Allocate some of that quota to a child project using hard limit
        quota['volumes'] = -1
        self.controller.update(self.req, self.B.id, body)
        quota['volumes'] = 2
        self.controller.update(self.req, self.D.id, body)

        res = 'volumes'
        self._assert_quota_show(self.A.id, res, allocated=2, limit=5)
        self._assert_quota_show(self.B.id, res, allocated=2, limit=-1)
        self.controller.delete(self.req, self.D.id)
        self._assert_quota_show(self.A.id, res, allocated=0, limit=5)
        self._assert_quota_show(self.B.id, res, allocated=0, limit=-1)

    def test_negative_child_limit_not_affecting_parents_free_quota(self):
        quota = {'volumes': -1}
        body = {'quota_set': quota}
        self.controller.update(self.req, self.C.id, body)
        self.controller.update(self.req, self.B.id, body)

        # Shouldn't be able to set greater than parent
        quota['volumes'] = 11
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, self.B.id, body)

    def test_child_neg_limit_set_grandkid_zero_limit(self):
        cur_quota_a = self.controller.show(self.req, self.A.id)
        self.assertEqual(10, cur_quota_a['quota_set']['volumes'])

        quota = {'volumes': -1}
        body = {'quota_set': quota}
        self.controller.update(self.req, self.B.id, body)

        cur_quota_d = self.controller.show(self.req, self.D.id)
        # Default child value is 0
        self.assertEqual(0, cur_quota_d['quota_set']['volumes'])
        # Should be able to set D explicitly to 0 since that's already the val
        quota['volumes'] = 0
        self.controller.update(self.req, self.D.id, body)

    def test_grandkid_negative_one_limit_enforced(self):
        quota = {'volumes': 2, 'gigabytes': 2}
        body = {'quota_set': quota}
        self.controller.update(self.req, self.A.id, body)

        quota['volumes'] = -1
        quota['gigabytes'] = -1
        self.controller.update(self.req, self.B.id, body)
        self.controller.update(self.req, self.C.id, body)
        self.controller.update(self.req, self.D.id, body)

        def _reserve(project_id):
            quotas.QUOTAS._driver.reserve(
                self.req.environ['cinder.context'], quotas.QUOTAS.resources,
                {'volumes': 1, 'gigabytes': 1}, project_id=project_id)

        _reserve(self.C.id)
        _reserve(self.D.id)
        self.assertRaises(exception.OverQuota, _reserve, self.B.id)
        self.assertRaises(exception.OverQuota, _reserve, self.C.id)
        self.assertRaises(exception.OverQuota, _reserve, self.D.id)

        # Make sure the rollbacks went successfully for allocated for all res
        for res in quota.keys():
            self._assert_quota_show(self.A.id, res, allocated=2, limit=2)
            self._assert_quota_show(self.B.id, res, allocated=1, limit=-1)
            self._assert_quota_show(self.C.id, res, reserved=1, limit=-1)
            self._assert_quota_show(self.D.id, res, reserved=1, limit=-1)

    def test_child_update_affects_allocated_and_rolls_back(self):
        quota = {'gigabytes': -1, 'volumes': 3}
        body = {'quota_set': quota}
        self.controller.update(self.req, self.A.id, body)
        quota['volumes'] = -1
        self.controller.update(self.req, self.B.id, body)
        quota['volumes'] = 1
        self.controller.update(self.req, self.C.id, body)

        # Shouldn't be able to update to greater than the grandparent
        quota['volumes'] = 3
        quota['gigabytes'] = 1
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, self.req, self.D.id, body)
        # Validate we haven't updated either parents' allocated value for
        # any of the keys (even if some keys were valid)
        self._assert_quota_show(self.A.id, 'volumes', allocated=1, limit=3)
        self._assert_quota_show(self.A.id, 'gigabytes', limit=-1)
        self._assert_quota_show(self.B.id, 'volumes', limit=-1)
        self._assert_quota_show(self.B.id, 'gigabytes', limit=-1)

        quota['volumes'] = 2
        self.controller.update(self.req, self.D.id, body)
        # Validate we have now updated the parent and grandparents'
        self.req.params = {'usage': 'True'}
        self._assert_quota_show(self.A.id, 'volumes', allocated=3, limit=3)
        self._assert_quota_show(self.A.id, 'gigabytes', allocated=1, limit=-1)
        self._assert_quota_show(self.B.id, 'volumes', allocated=2, limit=-1)
        self._assert_quota_show(self.B.id, 'gigabytes', allocated=1, limit=-1)

    def test_negative_child_limit_reserve_and_rollback(self):
        quota = {'volumes': 2, 'gigabytes': 2}
        body = {'quota_set': quota}
        self.controller.update(self.req, self.A.id, body)

        quota['volumes'] = -1
        quota['gigabytes'] = -1
        self.controller.update(self.req, self.B.id, body)
        self.controller.update(self.req, self.C.id, body)
        self.controller.update(self.req, self.D.id, body)

        res = quotas.QUOTAS._driver.reserve(
            self.req.environ['cinder.context'], quotas.QUOTAS.resources,
            {'volumes': 2, 'gigabytes': 2}, project_id=self.D.id)

        self.req.params = {'usage': 'True'}
        quota_b = self.controller.show(self.req, self.B.id)
        self.assertEqual(2, quota_b['quota_set']['volumes']['allocated'])
        # A will be the next hard limit to set
        quota_a = self.controller.show(self.req, self.A.id)
        self.assertEqual(2, quota_a['quota_set']['volumes']['allocated'])
        quota_d = self.controller.show(self.req, self.D.id)
        self.assertEqual(2, quota_d['quota_set']['volumes']['reserved'])

        quotas.QUOTAS.rollback(self.req.environ['cinder.context'], res,
                               self.D.id)
        # After the rollback, A's limit should be properly set again
        quota_a = self.controller.show(self.req, self.A.id)
        self.assertEqual(0, quota_a['quota_set']['volumes']['allocated'])
        quota_d = self.controller.show(self.req, self.D.id)
        self.assertEqual(0, quota_d['quota_set']['volumes']['in_use'])

    @mock.patch('cinder.db.sqlalchemy.api._get_quota_usages')
    @mock.patch('cinder.db.quota_usage_get_all_by_project')
    def test_nested_quota_set_negative_limit(self, mock_usage, mock_get_usage):
        # TODO(mc_nair): this test should be moved to Tempest once nested quota
        # coverage is added
        fake_usages = {self.A.id: 1, self.B.id: 1, self.D.id: 2, self.C.id: 0}
        self._create_fake_quota_usages(fake_usages)
        mock_usage.side_effect = self._fake_quota_usage_get_all_by_project

        class FakeUsage(object):
                def __init__(self, in_use, reserved):
                    self.in_use = in_use
                    self.reserved = reserved
                    self.until_refresh = None
                    self.total = self.reserved + self.in_use

        def _fake__get_quota_usages(context, session, project_id):
            if not project_id:
                return {}
            return {'volumes': FakeUsage(fake_usages[project_id], 0)}
        mock_get_usage.side_effect = _fake__get_quota_usages

        # Update the project A quota.
        quota_limit = {'volumes': 7}
        body = {'quota_set': quota_limit}
        self.controller.update(self.req, self.A.id, body)

        quota_limit['volumes'] = 4
        self.controller.update(self.req, self.B.id, body)
        quota_limit['volumes'] = -1
        self.controller.update(self.req, self.D.id, body)

        quota_limit['volumes'] = 1
        self.controller.update(self.req, self.C.id, body)

        self.req.params['fix_allocated_quotas'] = True
        self.controller.validate_setup_for_nested_quota_use(self.req)

        # Validate that the allocated values look right for each project
        self.req.params = {'usage': 'True'}

        res = 'volumes'
        # A has given 4 vols to B and 1 vol to C (from limits)
        self._assert_quota_show(self.A.id, res, allocated=5, in_use=1, limit=7)
        self._assert_quota_show(self.B.id, res, allocated=2, in_use=1, limit=4)
        self._assert_quota_show(self.D.id, res, in_use=2, limit=-1)
        self._assert_quota_show(self.C.id, res, limit=1)

        # Update B to -1 limit, and make sure that A's allocated gets updated
        # with B + D's in_use values (one less than current limit
        quota_limit['volumes'] = -1
        self.controller.update(self.req, self.B.id, body)
        self._assert_quota_show(self.A.id, res, allocated=4, in_use=1, limit=7)

        quota_limit['volumes'] = 6
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            self.controller.update, self.req, self.B.id, body)

        quota_limit['volumes'] = 5
        self.controller.update(self.req, self.B.id, body)
        self._assert_quota_show(self.A.id, res, allocated=6, in_use=1, limit=7)
