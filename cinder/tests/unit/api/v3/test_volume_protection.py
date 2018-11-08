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

import uuid
import webob

import mock
from oslo_serialization import jsonutils
from six.moves import http_client

from cinder.api import microversions as mv
from cinder import context as cinder_context
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants
from cinder.volume import api as volume_api


class VolumeProtectionTests(test.TestCase):

    def setUp(self):
        super(VolumeProtectionTests, self).setUp()
        self.project_id = fake_constants.PROJECT_ID
        self.other_project_id = fake_constants.PROJECT2_ID
        self.admin_context = cinder_context.RequestContext(
            user_id=uuid.uuid4().hex, project_id=self.project_id,
            is_admin=True
        )
        self.user_context = cinder_context.RequestContext(
            user_id=uuid.uuid4().hex, project_id=self.project_id
        )
        self.other_user_context = cinder_context.RequestContext(
            user_id=uuid.uuid4().hex, project_id=self.other_project_id
        )

    def _get_request_response(self, context, path, method, body=None):
        request = webob.Request.blank(path)
        request.content_type = 'application/json'
        request.headers = mv.get_mv_header(mv.BASE_VERSION)
        request.method = method
        if body:
            request.headers["content-type"] = "application/json"
            request.body = jsonutils.dump_as_bytes(body)
        return request.get_response(
            fakes.wsgi_app(fake_auth_context=context)
        )

    def _create_fake_volume(self, context):
        vol = {
            'display_name': 'fake_volume1',
            'status': 'available',
            'project_id': context.project_id
        }
        volume = objects.Volume(context=context, **vol)
        volume.create()
        return volume

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_admin_can_show_volumes(self, mock_volume):
        # Make sure administrators are authorized to list volumes
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        self.assertEqual(response.json_body['volume']['id'], volume.id)

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_owner_can_show_volumes(self, mock_volume):
        # Make sure owners are authorized to list their volumes
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        self.assertEqual(response.json_body['volume']['id'], volume.id)

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_owner_cannot_show_volumes_for_others(self, mock_volume):
        # Make sure volumes are only exposed to their owners
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context)
        mock_volume.return_value = volume

        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(non_owner_context, path, 'GET')
        # NOTE(lbragstad): Technically, this user isn't supposed to see this
        # volume, because they didn't create it and it lives in a different
        # project. Does cinder return a 404 in cases like this? Or is a 403
        # expected?
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_admin_can_get_all_volumes_detail(self):
        # Make sure administrators are authorized to list volumes
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volumes'][0]

        self.assertEqual(volume.id, res_vol['id'])

    def test_owner_can_get_all_volumes_detail(self):
        # Make sure owners are authorized to list volumes
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volumes'][0]

        self.assertEqual(volume.id, res_vol['id'])

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_admin_can_force_delete_volumes(self, mock_volume):
        # Make sure administrators are authorized to force delete volumes
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }
        body = {"os-force_delete": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)

        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_nonadmin_cannot_force_delete_volumes(self, mock_volume):
        # Make sure volumes only can be force deleted by admin
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }
        body = {"os-force_delete": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)

        self.assertEqual(http_client.FORBIDDEN, response.status_int)
