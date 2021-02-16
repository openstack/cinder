# Copyright (c) 2017 Huawei Technologies Co., Ltd.
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
import os.path
from unittest import mock

from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_policy import policy as oslo_policy

from cinder import context
from cinder import exception
from cinder import policy
from cinder.tests.unit import test
from cinder import utils

CONF = cfg.CONF


class PolicyFileTestCase(test.TestCase):

    def setUp(self):
        super(PolicyFileTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.target = {}
        self.fixture = self.useFixture(config_fixture.Config(CONF))
        self.addCleanup(policy.reset)

    def test_modified_policy_reloads(self):
        with utils.tempdir() as tmpdir:
            tmpfilename = os.path.join(tmpdir, 'policy')
            self.fixture.config(policy_file=tmpfilename, group='oslo_policy')
            policy.reset()
            policy.init()
            rule = oslo_policy.RuleDefault('example:test', "")
            policy._ENFORCER.register_defaults([rule])

            action = "example:test"
            with open(tmpfilename, "w") as policyfile:
                policyfile.write('{"example:test": ""}')
            policy.authorize(self.context, action, self.target)
            with open(tmpfilename, "w") as policyfile:
                policyfile.write('{"example:test": "!"}')
            policy._ENFORCER.load_rules(True)
            self.assertRaises(exception.PolicyNotAuthorized,
                              policy.authorize,
                              self.context, action, self.target)


class PolicyTestCase(test.TestCase):

    def setUp(self):
        super(PolicyTestCase, self).setUp()
        rules = [
            oslo_policy.RuleDefault("true", '@'),
            oslo_policy.RuleDefault("test:allowed", '@'),
            oslo_policy.RuleDefault("test:denied", "!"),
            oslo_policy.RuleDefault("test:my_file",
                                    "role:compute_admin or "
                                    "project_id:%(project_id)s"),
            oslo_policy.RuleDefault("test:early_and_fail", "! and @"),
            oslo_policy.RuleDefault("test:early_or_success", "@ or !"),
            oslo_policy.RuleDefault("test:lowercase_admin",
                                    "role:admin"),
            oslo_policy.RuleDefault("test:uppercase_admin",
                                    "role:ADMIN"),
            oslo_policy.RuleDefault("old_action_not_default", "@"),
            oslo_policy.RuleDefault("new_action", "@"),
            oslo_policy.RuleDefault("old_action_default", "rule:admin_api"),
        ]
        policy.reset()
        policy.init()
        # before a policy rule can be used, its default has to be registered.
        policy._ENFORCER.register_defaults(rules)
        self.context = context.RequestContext('fake', 'fake', roles=['member'])
        self.target = {}
        self.addCleanup(policy.reset)

    def test_authorize_nonexistent_action_throws(self):
        action = "test:noexist"
        self.assertRaises(oslo_policy.PolicyNotRegistered, policy.authorize,
                          self.context, action, self.target)

    def test_authorize_bad_action_throws(self):
        action = "test:denied"
        self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                          self.context, action, self.target)

    def test_authorize_bad_action_noraise(self):
        action = "test:denied"
        result = policy.authorize(self.context, action, self.target, False)
        self.assertFalse(result)

    def test_authorize_good_action(self):
        action = "test:allowed"
        result = policy.authorize(self.context, action, self.target)
        self.assertTrue(result)

    def test_templatized_authorization(self):
        target_mine = {'project_id': 'fake'}
        target_not_mine = {'project_id': 'another'}
        action = "test:my_file"
        policy.authorize(self.context, action, target_mine)
        self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                          self.context, action, target_not_mine)

    def test_early_AND_authorization(self):
        action = "test:early_and_fail"
        self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                          self.context, action, self.target)

    def test_early_OR_authorization(self):
        action = "test:early_or_success"
        policy.authorize(self.context, action, self.target)

    def test_ignore_case_role_check(self):
        lowercase_action = "test:lowercase_admin"
        uppercase_action = "test:uppercase_admin"
        admin_context = context.RequestContext('admin',
                                               'fake',
                                               roles=['AdMiN'])
        policy.authorize(admin_context, lowercase_action, self.target)
        policy.authorize(admin_context, uppercase_action, self.target)

    def test_enforce_properly_handles_invalid_scope_exception(self):
        self.fixture.config(enforce_scope=True, group='oslo_policy')
        project_context = context.RequestContext(project_id='fake-project-id',
                                                 roles=['bar'])
        policy.reset()
        policy.init()
        rule = oslo_policy.RuleDefault('foo', 'role:bar',
                                       scope_types=['system'])
        policy._ENFORCER.register_defaults([rule])

        self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                          project_context, 'foo', {})

    def test_enforce_does_not_raise_forbidden(self):
        self.fixture.config(enforce_scope=False, group='oslo_policy')
        project_context = context.RequestContext(project_id='fake-project-id',
                                                 roles=['bar'])
        policy.reset()
        policy.init()
        rule = oslo_policy.RuleDefault('foo', 'role:bar',
                                       scope_types=['system'])
        policy._ENFORCER.register_defaults([rule])

        self.assertTrue(policy.enforce(project_context, 'foo', {}))

    def test_enforce_passes_context_objects_to_enforcement(self):
        fake_context = context.RequestContext(roles=['foo'])
        action = 'foo'
        target = {}
        with mock.patch.object(policy._ENFORCER, 'enforce') as fake_enforce:
            policy.enforce(fake_context, action, target)
            fake_enforce.assert_called_once_with(
                action, target, fake_context, do_raise=True,
                exc=exception.PolicyNotAuthorized, action=action)

    def test_authorize_passes_context_objects_to_enforcement(self):
        fake_context = context.RequestContext(project_id='fake-project-id',
                                              user_id='fake-user-id',
                                              roles=['foo'])
        action = 'foo'
        target = {'project_id': 'fake-project-id', 'user_id': 'fake-user-id'}
        with mock.patch.object(policy._ENFORCER, 'authorize') as fake_authz:
            fake_context.authorize('foo')
            fake_authz.assert_called_once_with(
                action, target, fake_context, do_raise=True,
                exc=exception.PolicyNotAuthorized, action=action)
