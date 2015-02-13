#
#    Copyright 2010 OpenStack Foundation
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

from cinder import test
from cinder.tests import utils as test_utils


class TestUtilsTestCase(test.TestCase):
    def test_get_test_admin_context(self):
        """get_test_admin_context's return value behaves like admin context."""
        ctxt = test_utils.get_test_admin_context()

        self.assertIsNone(ctxt.project_id)
        self.assertIsNone(ctxt.user_id)
        self.assertIsNone(ctxt.domain)
        self.assertIsNone(ctxt.project_domain)
        self.assertIsNone(ctxt.user_domain)
        self.assertIsNone(ctxt.project_name)
        self.assertIsNone(ctxt.remote_address)
        self.assertIsNone(ctxt.auth_token)
        self.assertIsNone(ctxt.quota_class)

        self.assertIsNotNone(ctxt.request_id)
        self.assertIsNotNone(ctxt.timestamp)

        self.assertEqual(['admin'], ctxt.roles)
        self.assertEqual([], ctxt.service_catalog)
        self.assertEqual('no', ctxt.read_deleted)

        self.assertTrue(ctxt.read_deleted)
        self.assertTrue(ctxt.is_admin)
