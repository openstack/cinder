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

from lxml import etree

import uuid
import webob.exc

from cinder.api.contrib import quotas
from cinder import context
from cinder import db
from cinder import quota
from cinder import test
from cinder.tests.unit import test_db_api

from keystonemiddleware import auth_token
from oslo_config import cfg
from oslo_config import fixture as config_fixture


CONF = cfg.CONF


def make_body(root=True, gigabytes=1000, snapshots=10,
              volumes=10, backups=10, backup_gigabytes=1000,
              tenant_id='foo', per_volume_gigabytes=-1, is_child=False):
    resources = {'gigabytes': gigabytes,
                 'snapshots': snapshots,
                 'volumes': volumes,
                 'backups': backups,
                 'backup_gigabytes': backup_gigabytes,
                 'per_volume_gigabytes': per_volume_gigabytes, }
    # need to consider preexisting volume types as well
    volume_types = db.volume_type_get_all(context.get_admin_context())

    if not is_child:
        for volume_type in volume_types:
            resources['gigabytes_' + volume_type] = -1
            resources['snapshots_' + volume_type] = -1
            resources['volumes_' + volume_type] = -1
    elif per_volume_gigabytes < 0:
        # In the case that we're dealing with a child project, we aren't
        # allowing -1 limits for the time being, so hack this to some large
        # enough value for the tests that it's essentially unlimited
        # TODO(mc_nair): remove when -1 limits for child projects are allowed
        resources['per_volume_gigabytes'] = 10000

    if tenant_id:
        resources['id'] = tenant_id
    if root:
        result = {'quota_set': resources}
    else:
        result = resources
    return result


def make_subproject_body(root=True, gigabytes=0, snapshots=0,
                         volumes=0, backups=0, backup_gigabytes=0,
                         tenant_id='foo', per_volume_gigabytes=0):
    return make_body(root=root, gigabytes=gigabytes, snapshots=snapshots,
                     volumes=volumes, backups=backups,
                     backup_gigabytes=backup_gigabytes, tenant_id=tenant_id,
                     per_volume_gigabytes=per_volume_gigabytes)


class QuotaSetsControllerTestBase(test.TestCase):

    class FakeProject(object):

        def __init__(self, id='foo', parent_id=None):
            self.id = id
            self.parent_id = parent_id
            self.subtree = None

    def setUp(self):
        super(QuotaSetsControllerTestBase, self).setUp()

        self.controller = quotas.QuotaSetsController()

        self.req = mock.Mock()
        self.req.environ = {'cinder.context': context.get_admin_context()}
        self.req.environ['cinder.context'].is_admin = True
        self.req.params = {}

        self._create_project_hierarchy()

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
        self.fixture = self.useFixture(config_fixture.Config(auth_token.CONF))
        self.fixture.config(auth_uri=self.auth_url, group='keystone_authtoken')

    def _create_project_hierarchy(self):
        """Sets an environment used for nested quotas tests.

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

        # project_by_id attribute is used to recover a project based on its id.
        self.project_by_id = {self.A.id: self.A, self.B.id: self.B,
                              self.C.id: self.C, self.D.id: self.D}

    def _get_project(self, context, id, subtree_as_ids=False):
        return self.project_by_id.get(id, self.FakeProject())


class QuotaSetsControllerTest(QuotaSetsControllerTestBase):
    def setUp(self):
        super(QuotaSetsControllerTest, self).setUp()
        fixture = self.useFixture(config_fixture.Config(quota.CONF))
        fixture.config(quota_driver="cinder.quota.DbQuotaDriver")
        quotas.QUOTAS = quota.VolumeTypeQuotaEngine()
        self.controller = quotas.QuotaSetsController()

    def test_defaults(self):
        result = self.controller.defaults(self.req, 'foo')
        self.assertDictMatch(make_body(), result)

    def test_show(self):
        result = self.controller.show(self.req, 'foo')
        self.assertDictMatch(make_body(), result)

    def test_show_not_authorized(self):
        self.req.environ['cinder.context'].is_admin = False
        self.req.environ['cinder.context'].user_id = 'bad_user'
        self.req.environ['cinder.context'].project_id = 'bad_project'
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
                          self.req, 'foo')

    def test_show_non_admin_user(self):
        self.controller._get_quotas = mock.Mock(side_effect=
                                                self.controller._get_quotas)
        result = self.controller.show(self.req, 'foo')
        self.assertDictMatch(make_body(), result)
        self.controller._get_quotas.assert_called_with(
            self.req.environ['cinder.context'], 'foo', False)

    def test_update(self):
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        result = self.controller.update(self.req, 'foo', body)
        self.assertDictMatch(body, result)

        body = make_body(gigabytes=db.MAX_INT, tenant_id=None)
        result = self.controller.update(self.req, 'foo', body)
        self.assertDictMatch(body, result)

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
        self.assertDictMatch(body, result)
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
        'cinder.api.openstack.wsgi.Controller.validate_integer')
    def test_update_limit(self, mock_validate_integer, mock_validate):
        mock_validate_integer.return_value = 10

        body = {'quota_set': {'volumes': 10}}
        result = self.controller.update(self.req, 'foo', body)

        self.assertEqual(10, result['quota_set']['volumes'])
        self.assertTrue(mock_validate.called)
        self.assertTrue(mock_validate_integer.called)

    def test_update_wrong_key(self):
        body = {'quota_set': {'bad': 'bad'}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_invalid_value_key_value(self):
        body = {'quota_set': {'gigabytes': "should_be_int"}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_invalid_type_key_value(self):
        body = {'quota_set': {'gigabytes': None}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_multi_value_with_bad_data(self):
        orig_quota = self.controller.show(self.req, 'foo')
        body = make_body(gigabytes=2000, snapshots=15, volumes="should_be_int",
                         backups=5, tenant_id=None)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)
        # Verify that quota values are not updated in db
        new_quota = self.controller.show(self.req, 'foo')
        self.assertDictMatch(orig_quota, new_quota)

    def test_update_bad_quota_limit(self):
        body = {'quota_set': {'gigabytes': -1000}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)
        body = {'quota_set': {'gigabytes': db.MAX_INT + 1}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_no_admin(self):
        self.req.environ['cinder.context'].is_admin = False
        self.req.environ['cinder.context'].project_id = 'foo'
        self.req.environ['cinder.context'].user_id = 'foo_user'
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          self.req, 'foo', make_body(tenant_id=None))

    def test_update_without_quota_set_field(self):
        body = {'fake_quota_set': {'gigabytes': 100}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_empty_body(self):
        body = {}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def _commit_quota_reservation(self):
        # Create simple quota and quota usage.
        ctxt = context.get_admin_context()
        res = test_db_api._quota_reserve(ctxt, 'foo')
        db.reservation_commit(ctxt, res, 'foo')
        expected = {'project_id': 'foo',
                    'volumes': {'reserved': 0, 'in_use': 1},
                    'gigabytes': {'reserved': 0, 'in_use': 2},
                    }
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(ctxt, 'foo'))

    def test_update_lower_than_existing_resources_when_skip_false(self):
        self._commit_quota_reservation()
        body = {'quota_set': {'volumes': 0},
                'skip_validation': 'false'}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)
        body = {'quota_set': {'gigabytes': 1},
                'skip_validation': 'false'}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_lower_than_existing_resources_when_skip_true(self):
        self._commit_quota_reservation()
        body = {'quota_set': {'volumes': 0},
                'skip_validation': 'true'}
        result = self.controller.update(self.req, 'foo', body)
        self.assertEqual(body['quota_set']['volumes'],
                         result['quota_set']['volumes'])

    def test_update_lower_than_existing_resources_without_skip_argument(self):
        self._commit_quota_reservation()
        body = {'quota_set': {'volumes': 0}}
        result = self.controller.update(self.req, 'foo', body)
        self.assertEqual(body['quota_set']['volumes'],
                         result['quota_set']['volumes'])

    def test_delete(self):
        result_show = self.controller.show(self.req, 'foo')
        self.assertDictMatch(make_body(), result_show)

        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5,
                         backup_gigabytes=1000, tenant_id=None)
        result_update = self.controller.update(self.req, 'foo', body)
        self.assertDictMatch(body, result_update)

        self.controller.delete(self.req, 'foo')

        result_show_after = self.controller.show(self.req, 'foo')
        self.assertDictMatch(result_show, result_show_after)

    def test_delete_with_allocated_quota_different_from_zero(self):
        self.req.environ['cinder.context'].project_id = self.A.id

        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5,
                         backup_gigabytes=1000, tenant_id=None)
        result_update = self.controller.update(self.req, self.A.id, body)
        self.assertDictMatch(body, result_update)

        # Set usage param to True in order to see get allocated values.
        self.req.params = {'usage': 'True'}
        result_show = self.controller.show(self.req, self.A.id)

        result_update = self.controller.update(self.req, self.B.id, body)
        self.assertDictMatch(body, result_update)

        self.controller.delete(self.req, self.B.id)

        result_show_after = self.controller.show(self.req, self.A.id)
        self.assertDictMatch(result_show, result_show_after)

    def test_delete_no_admin(self):
        self.req.environ['cinder.context'].is_admin = False
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          self.req, 'foo')

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
        """Sets an environment used for nested quotas tests.

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

    def _fake_quota_usage_get_all_by_project(self, context, project_id):
        proj_vals = {
            self.A.id: {'in_use': 1},
            self.B.id: {'in_use': 1},
            self.D.id: {'in_use': 0},
            self.C.id: {'in_use': 3},
            self.E.id: {'in_use': 0},
            self.F.id: {'in_use': 0},
            self.G.id: {'in_use': 0},
        }
        return {'volumes': proj_vals[project_id]}

    @mock.patch('cinder.db.quota_usage_get_all_by_project')
    def test_validate_nested_quotas_in_use_vols(self, mock_usage):
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

    def test_validate_nested_quota_negative_limits(self):
        # When we're validating, update the allocated values since we've
        # been updating child limits
        self.req.params['fix_allocated_quotas'] = True
        self.controller.validate_setup_for_nested_quota_use(self.req)
        # Update the project A quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        quota_limit = {'volumes': -1}
        body = {'quota_set': quota_limit}
        self.controller.update(self.req, self.A.id, body)

        quota_limit['volumes'] = 4
        self.controller.update(self.req, self.B.id, body)

        self.controller.validate_setup_for_nested_quota_use(self.req)

        quota_limit['volumes'] = -1
        self.controller.update(self.req, self.F.id, body)
        # Should not work because can't have a child with negative limits
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            self.controller.validate_setup_for_nested_quota_use,
            self.req)


class QuotaSetsControllerNestedQuotasTest(QuotaSetsControllerTestBase):
    def setUp(self):
        super(QuotaSetsControllerNestedQuotasTest, self).setUp()
        fixture = self.useFixture(config_fixture.Config(quota.CONF))
        fixture.config(quota_driver="cinder.quota.NestedDbQuotaDriver")
        quotas.QUOTAS = quota.VolumeTypeQuotaEngine()
        self.controller = quotas.QuotaSetsController()

    def test_subproject_defaults(self):
        context = self.req.environ['cinder.context']
        context.project_id = self.B.id
        result = self.controller.defaults(self.req, self.B.id)
        expected = make_subproject_body(tenant_id=self.B.id)
        self.assertDictMatch(expected, result)

    def test_subproject_show(self):
        self.req.environ['cinder.context'].project_id = self.A.id
        result = self.controller.show(self.req, self.B.id)
        expected = make_subproject_body(tenant_id=self.B.id)
        self.assertDictMatch(expected, result)

    def test_subproject_show_in_hierarchy(self):
        # A user scoped to a root project in a hierarchy can see its children
        # quotas.
        self.req.environ['cinder.context'].project_id = self.A.id
        result = self.controller.show(self.req, self.D.id)
        expected = make_subproject_body(tenant_id=self.D.id)
        self.assertDictMatch(expected, result)
        # A user scoped to a parent project can see its immediate children
        # quotas.
        self.req.environ['cinder.context'].project_id = self.B.id
        result = self.controller.show(self.req, self.D.id)
        expected = make_subproject_body(tenant_id=self.D.id)
        self.assertDictMatch(expected, result)

    def test_subproject_show_target_project_equals_to_context_project(
            self):
        self.req.environ['cinder.context'].project_id = self.B.id
        result = self.controller.show(self.req, self.B.id)
        expected = make_subproject_body(tenant_id=self.B.id)
        self.assertDictMatch(expected, result)

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
        self.assertDictMatch(body, result)
        # Try to update the quota of F, it will not be allowed, since the
        # project E doesn't belongs to the project hierarchy of A.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.update, self.req, F.id, body)

    def test_update_subproject(self):
        # Update the project A quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        result = self.controller.update(self.req, self.A.id, body)
        self.assertDictMatch(body, result)
        # Update the quota of B to be equal to its parent quota
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None, is_child=True)
        result = self.controller.update(self.req, self.B.id, body)
        self.assertDictMatch(body, result)
        # Try to update the quota of C, it will not be allowed, since the
        # project A doesn't have free quota available.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None, is_child=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, self.C.id, body)
        # Successfully update the quota of D.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=1000, snapshots=7,
                         volumes=3, backups=3, tenant_id=None, is_child=True)
        result = self.controller.update(self.req, self.D.id, body)
        self.assertDictMatch(body, result)
        # An admin of B can also update the quota of D, since D is its
        # immediate child.
        self.req.environ['cinder.context'].project_id = self.B.id
        body = make_body(gigabytes=1500, snapshots=10,
                         volumes=4, backups=4, tenant_id=None, is_child=True)
        self.controller.update(self.req, self.D.id, body)

    def test_update_subproject_negative_limit(self):
        # Should not be able to set a negative limit for a child project (will
        # require further fixes to allow for this)
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(volumes=-1, is_child=True)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, self.req, self.B.id, body)

    def test_update_subproject_repetitive(self):
        # Update the project A volumes quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=10, backups=5, tenant_id=None)
        result = self.controller.update(self.req, self.A.id, body)
        self.assertDictMatch(body, result)
        # Update the quota of B to be equal to its parent quota
        # three times should be successful, the quota will not be
        # allocated to 'allocated' value of parent project
        for i in range(0, 3):
            self.req.environ['cinder.context'].project_id = self.A.id
            body = make_body(gigabytes=2000, snapshots=15,
                             volumes=10, backups=5, tenant_id=None,
                             is_child=True)
            result = self.controller.update(self.req, self.B.id, body)
            self.assertDictMatch(body, result)

    def test_update_subproject_with_not_root_context_project(self):
        # Update the project A quota.
        self.req.environ['cinder.context'].project_id = self.A.id
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        result = self.controller.update(self.req, self.A.id, body)
        self.assertDictMatch(body, result)
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
                             volumes=5, backups=5, tenant_id=None,
                             is_child=True)
        result = self.controller.update(self.req, self.B.id, expected)
        self.assertDictMatch(expected, result)

    def test_subproject_delete(self):
        self.req.environ['cinder.context'].project_id = self.A.id

        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5,
                         backup_gigabytes=1000, tenant_id=None, is_child=True)
        result_update = self.controller.update(self.req, self.A.id, body)
        self.assertDictMatch(body, result_update)

        # Set usage param to True in order to see get allocated values.
        self.req.params = {'usage': 'True'}
        result_show = self.controller.show(self.req, self.A.id)

        result_update = self.controller.update(self.req, self.B.id, body)
        self.assertDictMatch(body, result_update)

        self.controller.delete(self.req, self.B.id)

        result_show_after = self.controller.show(self.req, self.A.id)
        self.assertDictMatch(result_show, result_show_after)

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
        body = make_body(volumes=3, is_child=True)
        self.controller.update(self.req, self.B.id, body)

        # Deleting 'A' should be disallowed since 'B' is using some of that
        # quota
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          self.req, self.A.id)


class QuotaSerializerTest(test.TestCase):

    def setUp(self):
        super(QuotaSerializerTest, self).setUp()
        self.req = mock.Mock()
        self.req.environ = {'cinder.context': context.get_admin_context()}

    def test_update_serializer(self):
        serializer = quotas.QuotaTemplate()
        quota_set = make_body(root=False)
        text = serializer.serialize({'quota_set': quota_set})
        tree = etree.fromstring(text)
        self.assertEqual('quota_set', tree.tag)
        self.assertEqual(quota_set['id'], tree.get('id'))
        body = make_body(root=False, tenant_id=None)
        for node in tree:
            self.assertIn(node.tag, body)
            self.assertEqual(str(body[node.tag]), node.text)
