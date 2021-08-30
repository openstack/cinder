# Copyright 2021 Red Hat, Inc.
# All Rights Reserved.
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

import ddt

from cinder.api import extensions
from cinder.api import microversions as mv
from cinder.api.v3 import messages
from cinder.db import api as db_api
from cinder import exception
from cinder.policies import messages as messages_policies
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.policies import base


@ddt.ddt
class MessagesPolicyTest(base.BasePolicyTest):
    authorized_users = [
        'legacy_admin',
        'legacy_owner',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
        'project_foo',
    ]

    unauthorized_users = [
        'system_member',
        'system_reader',
        'system_foo',
        'other_project_member',
        'other_project_reader',
    ]

    # Basic policy tests are without scope and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)

        self.ext_mgr = extensions.ExtensionManager()
        self.controller = messages.MessagesController(self.ext_mgr)

        self.api_path = '/v3/%s/messages' % (self.project_id)
        self.api_version = mv.MESSAGES

    def _create_message(self):
        message_values = {
            'id': fake.UUID1,
            'event_id': 'VOLUME_000001',
            'message_level': 'ERROR',
            'project_id': self.project_id,
        }
        db_api.message_create(self.project_member_context, message_values)
        return message_values['id']

    @ddt.data(*base.all_users)
    def test_get_message_policy(self, user_id):
        message_id = self._create_message()
        rule_name = messages_policies.GET_POLICY
        url = '%s/%s' % (self.api_path, message_id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        unauthorized_exceptions = [
            exception.MessageNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.show, req,
                                 id=message_id)

    @ddt.data(*base.all_users)
    def test_get_all_message_policy(self, user_id):
        self._create_message()
        rule_name = messages_policies.GET_ALL_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        # The GET_ALL_POLICY is an interesting test case, primarily because
        # the policy check passes regardless of the whether the project_id
        # in the request matches the one in the context. This is OK because
        # the WSGI controller ensures the context can access the project_id
        # in the request. So in Xena, where scope is not supported, all users
        # will tend to pass the policy check regardless of their project_id.
        authorized_users = [user_id]
        unauthorized_users = []

        # The exception is when reprecated rules are disabled, in which case
        # roles are enforced. Users without the 'reader' role should be
        # blocked.
        if self.enforce_new_defaults:
            context = self.create_context(user_id)
            if 'reader' not in context.roles:
                authorized_users = []
                unauthorized_users = [user_id]

        unauthorized_exceptions = []

        self.common_policy_check(user_id, authorized_users,
                                 unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.index, req)

    @ddt.data(*base.all_users)
    def test_delete_message_policy(self, user_id):
        message_id = self._create_message()
        rule_name = messages_policies.DELETE_POLICY
        url = '%s/%s' % (self.api_path, message_id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        # The project_reader should not be able to delete a message unless
        # the deprecated policy rules are enabled.
        if user_id == 'project_reader' and self.enforce_new_defaults:
            unauthorized_users = [user_id]
            authorized_users = []
        else:
            authorized_users = self.authorized_users
            unauthorized_users = self.unauthorized_users

        unauthorized_exceptions = [
            exception.MessageNotFound,
        ]

        self.common_policy_check(user_id, authorized_users,
                                 unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.delete, req,
                                 id=message_id)


class MessagesPolicySecureRbacTest(MessagesPolicyTest):
    authorized_users = [
        'legacy_admin',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
    ]

    unauthorized_users = [
        'legacy_owner',
        'system_member',
        'system_reader',
        'system_foo',
        'project_foo',
        'other_project_member',
        'other_project_reader',
    ]

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)
