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

from oslo_log import log as logging
from oslo_utils.fixture import uuidsentinel as uuids

from cinder import context as cinder_context
from cinder import exception
from cinder.tests import fixtures
from cinder.tests.unit import test


LOG = logging.getLogger(__name__)

# The list of users, with characterstics/persona implied by the name,
# are declared statically for use as DDT data.
all_users = [
    'legacy_admin',
    'legacy_owner',
    'system_admin',
    # NOTE: Xena does not support these system scoped personae. They need
    # to be tested in Yoga when support is added for system scope.
    # 'system_member',
    # 'system_reader',
    # 'system_foo',
    'project_admin',
    'project_member',
    'project_reader',
    'project_foo',
    'other_project_member',
    'other_project_reader',
]


class BasePolicyTest(test.TestCase):
    def setUp(self, enforce_scope, enforce_new_defaults, *args, **kwargs):
        super().setUp(*args, **kwargs)
        self.enforce_scope = enforce_scope
        self.enforce_new_defaults = enforce_new_defaults
        self.override_config('enforce_scope',
                             enforce_scope, 'oslo_policy')
        self.override_config('enforce_new_defaults',
                             enforce_new_defaults, 'oslo_policy')
        self.policy = self.useFixture(fixtures.PolicyFixture())

        self.admin_project_id = uuids.admin_project_id
        self.project_id = uuids.project_id
        self.project_id_other = uuids.project_id_other

        self.context_details = {
            'legacy_admin': dict(
                project_id=self.admin_project_id,
                roles=['admin', 'member', 'reader'],
            ),
            'legacy_owner': dict(
                project_id=self.project_id,
                roles=[],
            ),
            'system_admin': dict(
                roles=['admin', 'member', 'reader'],
                # NOTE: The system_admin in Xena is project scoped, and will
                # change in Yoga when support is added for system scope.
                project_id=self.admin_project_id,
                # system_scope='all',
            ),
            'project_admin': dict(
                project_id=self.project_id,
                roles=['admin', 'member', 'reader'],
            ),
            'project_member': dict(
                project_id=self.project_id,
                roles=['member', 'reader'],
            ),
            'project_reader': dict(
                project_id=self.project_id,
                roles=['reader'],
            ),
            'project_foo': dict(
                project_id=self.project_id,
                roles=['foo'],
            ),
            'other_project_member': dict(
                project_id=self.project_id_other,
                roles=['member', 'reader'],
            ),
            'other_project_reader': dict(
                project_id=self.project_id_other,
                roles=['reader'],
            ),
        }

        # These context objects are useful for subclasses to create test
        # resources (e.g. volumes). Subclasses may create additional
        # contexts as needed.
        self.project_admin_context = self.create_context('project_admin')
        self.project_member_context = self.create_context('project_member')

    def is_authorized(self, user_id, authorized_users, unauthorized_users):
        if user_id in authorized_users:
            return True
        elif user_id in unauthorized_users:
            return False
        else:
            msg = ('"%s" must be either an authorized or unauthorized user.'
                   % (user_id))
            raise exception.CinderException(message=msg)

    def create_context(self, user_id):
        try:
            details = self.context_details[user_id]
        except KeyError:
            msg = ('No context details defined for user_id "%s".' % (user_id))
            raise exception.CinderException(message=msg)

        return cinder_context.RequestContext(user_id=user_id, **details)

    def common_policy_check(self, user_id, authorized_users,
                            unauthorized_users, unauthorized_exceptions,
                            rule_name, func, req, *args, **kwargs):

        req.environ['cinder.context'] = self.create_context(user_id)
        fatal = kwargs.pop('fatal', True)

        def ensure_raises(req, *args, **kwargs):
            try:
                func(req, *args, **kwargs)
            except exception.NotAuthorized as exc:
                # In case of multi-policy APIs, PolicyNotAuthorized can be
                # raised from either of the policy so checking the error
                # message, which includes the rule name, can mismatch. Tests
                # verifying the multi policy can pass rule_name as None to
                # skip the error message assert.
                if (isinstance(exc, exception.PolicyNotAuthorized) and
                        rule_name is not None):
                    self.assertEqual(
                        "Policy doesn't allow %s to be performed." %
                        rule_name, exc.args[0])
            except Exception as exc:
                self.assertIn(type(exc), unauthorized_exceptions)
            else:
                msg = ('"%s" was authorized for "%s" policy when it should '
                       'be unauthorized.' % (user_id, rule_name))
                raise exception.CinderException(message=msg)

            return None

        if self.is_authorized(user_id, authorized_users, unauthorized_users):
            # Verify the context having allowed scope and roles pass
            # the policy check.
            LOG.info('Testing authorized "%s"', user_id) # noqa: ignore=C309
            response = func(req, *args, **kwargs)
        else:
            # Verify the context not having allowed scope or roles fail
            # the policy check.
            LOG.info('Testing unauthorized "%s"', user_id) # noqa: ignore=C309
            if not fatal:
                try:
                    response = func(req, *args, **kwargs)
                    # We need to ignore the PolicyNotAuthorized
                    # exception here so that we can add the correct response
                    # in unauthorize_response for the case of fatal=False.
                    # This handle the case of multi policy checks where tests
                    # are verifying the second policy via the response of
                    # fatal-False and ignoring the response checks where the
                    # first policy itself fail to pass (even test override the
                    # first policy to allow for everyone but still, scope
                    # checks can leads to PolicyNotAuthorized error).
                    # For example: flavor extra specs policy for GET flavor
                    # API. In that case, flavor extra spec policy is checked
                    # after the GET flavor policy. So any context failing on
                    # GET flavor will raise the  PolicyNotAuthorized and for
                    # that case we do not have any way to verify the flavor
                    # extra specs so skip that context to check in test.
                except exception.PolicyNotAuthorized:
                    pass
            else:
                response = ensure_raises(req, *args, **kwargs)

        return response
