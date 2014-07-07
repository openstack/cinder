
#    Copyright 2011 OpenStack Foundation
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

from cinder import context
from cinder import test


class ContextTestCase(test.TestCase):

    def test_request_context_sets_is_admin(self):
        ctxt = context.RequestContext('111',
                                      '222',
                                      roles=['admin', 'weasel'])
        self.assertEqual(ctxt.is_admin, True)

    def test_request_context_sets_is_admin_upcase(self):
        ctxt = context.RequestContext('111',
                                      '222',
                                      roles=['Admin', 'weasel'])
        self.assertEqual(ctxt.is_admin, True)

    def test_request_context_read_deleted(self):
        ctxt = context.RequestContext('111',
                                      '222',
                                      read_deleted='yes')
        self.assertEqual(ctxt.read_deleted, 'yes')

        ctxt.read_deleted = 'no'
        self.assertEqual(ctxt.read_deleted, 'no')

    def test_request_context_read_deleted_invalid(self):
        self.assertRaises(ValueError,
                          context.RequestContext,
                          '111',
                          '222',
                          read_deleted=True)

        ctxt = context.RequestContext('111', '222')
        self.assertRaises(ValueError,
                          setattr,
                          ctxt,
                          'read_deleted',
                          True)

    def test_service_catalog_nova_only(self):
        service_catalog = [
            {u'type': u'compute', u'name': u'nova'},
            {u'type': u's3', u'name': u's3'},
            {u'type': u'image', u'name': u'glance'},
            {u'type': u'volume', u'name': u'cinder'},
            {u'type': u'ec2', u'name': u'ec2'},
            {u'type': u'object-store', u'name': u'swift'},
            {u'type': u'identity', u'name': u'keystone'},
            {u'type': None, u'name': u'S_withtypeNone'},
            {u'type': u'co', u'name': u'S_partofcompute'}]

        compute_catalog = [{u'type': u'compute', u'name': u'nova'}]
        ctxt = context.RequestContext('111', '222',
                                      service_catalog=service_catalog)
        self.assertEqual(ctxt.service_catalog, compute_catalog)

    def test_user_identity(self):
        ctx = context.RequestContext("user", "tenant",
                                     domain="domain",
                                     user_domain="user-domain",
                                     project_domain="project-domain")
        self.assertEqual('user tenant domain user-domain project-domain',
                         ctx.to_dict()["user_identity"])
