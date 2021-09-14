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

from copy import deepcopy

import ddt

from cinder.api.contrib import volume_type_access as vta
from cinder.api import microversions as mv
from cinder import objects
from cinder.policies import volume_access as vta_policies
from cinder.tests.unit.api.contrib import test_volume_type_access as vta_test
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.policies import base

IS_PUBLIC_FIELD = 'os-volume-type-access:is_public'


# the original uses a class var and admin context
class FakeRequest(vta_test.FakeRequest):
    def __init__(self, context):
        self.environ = {"cinder.context": context}


FAKE_RESP_OBJ = {
    'volume_type': {'id': fake.VOLUME_TYPE_ID},
    'volume_types': [
        {'id': fake.VOLUME_TYPE_ID},
        {'id': fake.VOLUME_TYPE3_ID}
    ]}


# need an instance var so this will work with ddt
class FakeResponse(vta_test.FakeResponse):
    def __init__(self):
        self.obj = deepcopy(FAKE_RESP_OBJ)


@ddt.ddt
class VolumeTypeAccessFieldPolicyTest(base.BasePolicyTest):

    # NOTE: We are testing directly against the extension controller.
    # Its call to context.authorize doesn't provide a target, so
    # "is_admin" or "project_id:%(project_id)s" always matches.
    authorized_users = [
        'legacy_admin',
        'project_admin',
        'system_admin',
        'legacy_owner',
        'project_member',
        'project_reader',
        'project_foo',
        'system_member',
        'system_reader',
        'system_foo',
        'other_project_member',
        'other_project_reader',
    ]

    # note: authorize is called with fatal=False, so everyone is a winner!
    everyone = authorized_users

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = vta.VolumeTypeActionController()
        self.rule_name = vta_policies.TYPE_ACCESS_POLICY
        self.api_version = mv.BASE_VERSION
        self.api_path = f'/v3/{self.project_id}/types'

    @ddt.data(*base.all_users)
    def test_type_access_policy_types_list(self, user_id):
        unauthorized_exceptions = None
        req = FakeRequest(self.create_context(user_id))
        resp = FakeResponse()

        self.common_policy_check(user_id,
                                 self.everyone,
                                 [],
                                 unauthorized_exceptions,
                                 self.rule_name,
                                 self.controller.index,
                                 req,
                                 resp)

        # this is where the real check happens
        if user_id in self.authorized_users:
            for vol_type in resp.obj['volume_types']:
                self.assertIn(IS_PUBLIC_FIELD, vol_type)
        else:
            for vol_type in resp.obj['volume_types']:
                self.assertNotIn(IS_PUBLIC_FIELD, vol_type)

    @ddt.data(*base.all_users)
    def test_type_access_policy_type_show(self, user_id):
        unauthorized_exceptions = None
        req = FakeRequest(self.create_context(user_id))
        resp = FakeResponse()

        self.common_policy_check(user_id,
                                 self.everyone,
                                 [],
                                 unauthorized_exceptions,
                                 self.rule_name,
                                 self.controller.show,
                                 req,
                                 resp,
                                 fake.VOLUME_TYPE_ID)

        if user_id in self.authorized_users:
            self.assertIn(IS_PUBLIC_FIELD, resp.obj['volume_type'])
        else:
            self.assertNotIn(IS_PUBLIC_FIELD, resp.obj['volume_type'])

    @ddt.data(*base.all_users)
    def test_type_access_policy_type_create(self, user_id):
        unauthorized_exceptions = None
        req = FakeRequest(self.create_context(user_id))
        resp = FakeResponse()
        body = None

        self.common_policy_check(user_id,
                                 self.everyone,
                                 [],
                                 unauthorized_exceptions,
                                 self.rule_name,
                                 self.controller.create,
                                 req,
                                 body,
                                 resp)

        if user_id in self.authorized_users:
            self.assertIn(IS_PUBLIC_FIELD, resp.obj['volume_type'])
        else:
            self.assertNotIn(IS_PUBLIC_FIELD, resp.obj['volume_type'])


class VolumeTypeAccessFieldPolicySecureRbacTest(
        VolumeTypeAccessFieldPolicyTest):

    # Remember that we are testing directly against the extension controller,
    # so while the below may seem over-permissive, in real life there is
    # a more selective check that happens first.
    authorized_users = [
        'legacy_admin',
        'project_admin',
        'system_admin',
        'project_member',
        'system_member',
        'other_project_member',
    ]
    # this will be anyone without the 'admin' or 'member' role
    unauthorized_users = [
        'legacy_owner',
        'project_foo',
        'project_reader',
        'system_reader',
        'system_foo',
        'other_project_reader',
    ]
    everyone = authorized_users + unauthorized_users

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)


@ddt.ddt
class VolumeTypeAccessListProjectsPolicyTest(base.BasePolicyTest):
    authorized_users = [
        'legacy_admin',
        'project_admin',
        'system_admin',
    ]
    unauthorized_users = [
        'legacy_owner',
        'project_member',
        'project_reader',
        'project_foo',
        'system_member',
        'system_reader',
        'system_foo',
        'other_project_member',
        'other_project_reader',
    ]

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = vta.VolumeTypeAccessController()
        self.volume_type = objects.VolumeType(
            self.project_admin_context,
            name='private_volume_type',
            is_public=False,
            description='volume type for srbac testing',
            extra_specs=None,
            projects=[self.project_id, self.project_id_other])
        self.volume_type.create()
        self.addCleanup(self.volume_type.destroy)
        self.api_version = mv.BASE_VERSION
        self.api_path = (f'/v3/{self.project_id}/types/'
                         f'{self.volume_type.id}/os-volume-type-access')

    @ddt.data(*base.all_users)
    def test_type_access_who_policy(self, user_id):
        """Test policy for listing projects with access to a volume type."""

        rule_name = vta_policies.TYPE_ACCESS_WHO_POLICY
        unauthorized_exceptions = None
        req = fake_api.HTTPRequest.blank(self.api_path)

        self.common_policy_check(user_id,
                                 self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.index,
                                 req,
                                 self.volume_type.id)


class VolumeTypeAccessListProjectsPolicySecureRbacTest(
        VolumeTypeAccessListProjectsPolicyTest):

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)
