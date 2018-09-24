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
from six.moves import http_client

from cinder.api import microversions as mv
from cinder import context as cinder_context
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.volume import api as volume_api


class VolumeProtectionTests(test.TestCase):

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
        fake_project_id = uuid.uuid4().hex
        admin_context = cinder_context.RequestContext(
            user_id=uuid.uuid4().hex, project_id=fake_project_id,
            is_admin=True
        )

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': fake_project_id, 'volume_id': volume.id
        }
        request = webob.Request.blank(path)
        request.content_type = 'application/json'
        request.headers = mv.get_mv_header(mv.BASE_VERSION)
        request.method = 'GET'
        response = request.get_response(
            fakes.wsgi_app(fake_auth_context=admin_context)
        )
        self.assertEqual(http_client.OK, response.status_int)
        self.assertEqual(response.json_body['volume']['id'], volume.id)

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_owner_can_show_volumes(self, mock_volume):
        # Make sure owners are authorized to list their volumes
        fake_project_id = uuid.uuid4().hex
        user_context = cinder_context.RequestContext(
            user_id=uuid.uuid4().hex, project_id=fake_project_id
        )

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': fake_project_id, 'volume_id': volume.id
        }
        request = webob.Request.blank(path)
        request.content_type = 'application/json'
        request.headers = mv.get_mv_header(mv.BASE_VERSION)
        request.method = 'GET'
        response = request.get_response(
            fakes.wsgi_app(fake_auth_context=user_context)
        )
        self.assertEqual(http_client.OK, response.status_int)
        self.assertEqual(response.json_body['volume']['id'], volume.id)

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_owner_cannot_show_volumes_for_others(self, mock_volume):
        # Make sure volumes are only exposed to their owners
        owning_project_id = uuid.uuid4().hex
        other_project_id = uuid.uuid4().hex
        owner_context = cinder_context.RequestContext(
            user_id=uuid.uuid4().hex, project_id=owning_project_id
        )
        non_owner_context = cinder_context.RequestContext(
            user_id=uuid.uuid4().hex, project_id=other_project_id
        )

        volume = self._create_fake_volume(owner_context)
        mock_volume.return_value = volume

        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': other_project_id, 'volume_id': volume.id
        }
        request = webob.Request.blank(path)
        request.content_type = 'application/json'
        request.headers = mv.get_mv_header(mv.BASE_VERSION)
        request.method = 'GET'
        response = request.get_response(
            fakes.wsgi_app(fake_auth_context=non_owner_context)
        )
        # NOTE(lbragstad): Technically, this user isn't supposed to see this
        # volume, because they didn't create it and it lives in a different
        # project. Does cinder return a 404 in cases like this? Or is a 403
        # expected?
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
