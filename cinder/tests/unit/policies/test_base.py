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


from oslo_serialization import jsonutils
import webob

from cinder.api import microversions as mv
from cinder import context as cinder_context
from cinder import objects
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import test


class CinderPolicyTests(test.TestCase):

    def setUp(self):
        super(CinderPolicyTests, self).setUp()
        self.project_id = fake_constants.PROJECT_ID
        self.other_project_id = fake_constants.PROJECT2_ID
        self.admin_context = cinder_context.RequestContext(
            user_id=fake_constants.USER_ID, project_id=self.project_id,
            roles=['admin']
        )
        self.other_admin_context = cinder_context.RequestContext(
            user_id=fake_constants.USER_ID, project_id=self.other_project_id,
            roles=['admin']
        )
        self.user_context = cinder_context.RequestContext(
            user_id=fake_constants.USER2_ID, project_id=self.project_id,
            roles=['non-admin']
        )
        self.other_user_context = cinder_context.RequestContext(
            user_id=fake_constants.USER3_ID, project_id=self.other_project_id,
            roles=['non-admin']
        )
        self.system_admin_context = cinder_context.RequestContext(
            user_id=fake_constants.USER_ID, project_id=self.project_id,
            roles=['admin'], system_scope='all')
        fake_image.mock_image_service(self)

    def _get_request_response(self, context, path, method, body=None,
                              microversion=mv.BASE_VERSION):
        request = webob.Request.blank(path)
        request.content_type = 'application/json'
        request.headers = mv.get_mv_header(microversion)
        request.method = method
        if body:
            request.headers["content-type"] = "application/json"
            request.body = jsonutils.dump_as_bytes(body)
        return request.get_response(
            fakes.wsgi_app(fake_auth_context=context)
        )

    def _create_fake_volume(self, context, status=None, attach_status=None,
                            metadata=None, admin_metadata=None):
        vol = {
            'display_name': 'fake_volume1',
            'status': 'available',
            'project_id': context.project_id
        }
        if status:
            vol['status'] = status
        if attach_status:
            vol['attach_status'] = attach_status
        if metadata:
            vol['metadata'] = metadata
        if admin_metadata:
            vol['admin_metadata'] = admin_metadata
        volume = objects.Volume(context=context, **vol)
        volume.create()
        return volume

    def _create_fake_type(self, context):
        vol_type = {
            'name': 'fake_volume1',
            'extra_specs': {},
            'is_public': True,
            'projects': [],
            'description': 'A fake volume type'
        }
        volume_type = objects.VolumeType(context=context, **vol_type)
        volume_type.create()
        return volume_type
