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

import ddt
from six.moves import http_client
import webob

from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import consistencygroups
from cinder import context
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake


@ddt.ddt
class ConsistencyGroupsAPITestCase(test.TestCase):
    """Test Case for consistency groups API."""

    def setUp(self):
        super(ConsistencyGroupsAPITestCase, self).setUp()
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                           auth_token=True,
                                           is_admin=True)
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)
        self.controller = consistencygroups.ConsistencyGroupsController()

    def _create_consistencygroup(
            self,
            ctxt=None,
            name='test_consistencygroup',
            description='this is a test consistency group',
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            availability_zone='az1',
            host='fakehost',
            status=fields.ConsistencyGroupStatus.CREATING,
            **kwargs):
        """Create a consistency group object."""
        ctxt = ctxt or self.ctxt
        consistencygroup = objects.Group(ctxt)
        consistencygroup.user_id = fake.USER_ID
        consistencygroup.project_id = fake.PROJECT_ID
        consistencygroup.availability_zone = availability_zone
        consistencygroup.name = name
        consistencygroup.description = description
        consistencygroup.group_type_id = group_type_id
        consistencygroup.volume_type_ids = volume_type_ids
        consistencygroup.host = host
        consistencygroup.status = status
        consistencygroup.update(kwargs)
        consistencygroup.create()
        return consistencygroup

    def test_update_consistencygroup_empty_parameters(self):
        consistencygroup = self._create_consistencygroup(
            ctxt=self.ctxt,
            status=fields.ConsistencyGroupStatus.AVAILABLE)
        req = fakes.HTTPRequest.blank('/v3/%s/consistencygroups/%s/update' %
                                      (fake.PROJECT_ID, consistencygroup.id))
        req.environ['cinder.context'].is_admin = True
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume 3.6'
        req.api_version_request = api_version.APIVersionRequest('3.6')
        body = {"consistencygroup": {"name": "",
                                     "description": "",
                                     "add_volumes": None,
                                     "remove_volumes": None, }}
        res_dict = self.controller.update(req,
                                          consistencygroup.id,
                                          body)
        consistencygroup = objects.Group.get_by_id(
            self.ctxt, consistencygroup.id)
        self.assertEqual(http_client.ACCEPTED, res_dict.status_int)
        self.assertEqual("", consistencygroup.name)
        self.assertEqual("", consistencygroup.description)
        consistencygroup.destroy()

    def test_update_consistencygroup_empty_parameters_unsupport_version(self):
        consistencygroup = self._create_consistencygroup(
            ctxt=self.ctxt,
            status=fields.ConsistencyGroupStatus.AVAILABLE)
        req = fakes.HTTPRequest.blank('/v3/%s/consistencygroups/%s/update' %
                                      (fake.PROJECT_ID, consistencygroup.id))
        req.environ['cinder.context'].is_admin = True
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume 3.5'
        req.api_version_request = api_version.APIVersionRequest('3.5')
        body = {"consistencygroup": {"name": "",
                                     "description": "",
                                     "add_volumes": None,
                                     "remove_volumes": None, }}
        self.assertRaisesRegexp(webob.exc.HTTPBadRequest,
                                "Name, description, add_volumes, "
                                "and remove_volumes can not be all "
                                "empty in the request body.",
                                self.controller.update,
                                req, consistencygroup.id, body)
        consistencygroup.destroy()

    def test_update_consistencygroup_all_empty_parameters_version_36(self):
        consistencygroup = self._create_consistencygroup(
            ctxt=self.ctxt,
            status=fields.ConsistencyGroupStatus.AVAILABLE)
        req = fakes.HTTPRequest.blank('/v3/%s/consistencygroups/%s/update' %
                                      (fake.PROJECT_ID, consistencygroup.id))
        req.environ['cinder.context'].is_admin = True
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume 3.6'
        req.api_version_request = api_version.APIVersionRequest('3.6')
        body = {"consistencygroup": {"name": None,
                                     "description": None,
                                     "add_volumes": None,
                                     "remove_volumes": None, }}
        self.assertRaisesRegexp(webob.exc.HTTPBadRequest, "Must specify "
                                "one or more of the following keys to "
                                "update: name, description, add_volumes, "
                                "remove_volumes.", self.controller.update,
                                req, consistencygroup.id, body)
        consistencygroup.destroy()

    def test_update_consistencygroup_all_empty_parameters_not_version_36(self):
        consistencygroup = self._create_consistencygroup(
            ctxt=self.ctxt,
            status=fields.ConsistencyGroupStatus.AVAILABLE)
        req = fakes.HTTPRequest.blank('/v3/%s/consistencygroups/%s/update' %
                                      (fake.PROJECT_ID, consistencygroup.id))
        req.environ['cinder.context'].is_admin = True
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume 3.5'
        req.api_version_request = api_version.APIVersionRequest('3.5')
        body = {"consistencygroup": {"name": None,
                                     "description": None,
                                     "add_volumes": None,
                                     "remove_volumes": None, }}
        self.assertRaisesRegexp(webob.exc.HTTPBadRequest, "Name, description, "
                                "add_volumes, and remove_volumes can not be "
                                "all empty in the request body.",
                                self.controller.update,
                                req, consistencygroup.id, body)
        consistencygroup.destroy()

    def test_update_consistencygroup_no_body(self):
        consistencygroup = self._create_consistencygroup(
            ctxt=self.ctxt,
            status=fields.ConsistencyGroupStatus.AVAILABLE)
        req = fakes.HTTPRequest.blank('/v3/%s/consistencygroups/%s/update' %
                                      (fake.PROJECT_ID, consistencygroup.id))
        req.environ['cinder.context'].is_admin = True
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume 3.5'
        req.api_version_request = api_version.APIVersionRequest('3.5')
        body = None
        self.assertRaisesRegexp(webob.exc.HTTPBadRequest,
                                "Missing request body",
                                self.controller.update,
                                req, consistencygroup.id, body)
        consistencygroup.destroy()

    def test_update_consistencygroups_no_empty_parameters(self):
        consistencygroup = self._create_consistencygroup(
            ctxt=self.ctxt,
            status=fields.ConsistencyGroupStatus.AVAILABLE)
        req = fakes.HTTPRequest.blank('/v3/%s/consistencygroups/%s/update' %
                                      (fake.PROJECT_ID, consistencygroup.id))
        req.environ['cinder.context'].is_admin = True
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume 3.5'
        req.api_version_request = api_version.APIVersionRequest('3.5')
        body = {"consistencygroup": {"name": "my_fake_cg",
                                     "description": "fake consistency group",
                                     "add_volumes": "volume-uuid-1",
                                     "remove_volumes":
                                     "volume-uuid-2, volume uuid-3", }}
        allow_empty = self.controller._check_update_parameters_v3(
            req, body['consistencygroup']['name'],
            body['consistencygroup']['description'],
            body['consistencygroup']['add_volumes'],
            body['consistencygroup']['remove_volumes'])
        self.assertEqual(False, allow_empty)
        consistencygroup.destroy()
