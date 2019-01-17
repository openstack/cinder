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
from cinder.tests.unit.image import fake as fake_image
from cinder.volume import api as volume_api


class VolumeProtectionTests(test.TestCase):

    def setUp(self):
        super(VolumeProtectionTests, self).setUp()
        self.project_id = fake_constants.PROJECT_ID
        self.other_project_id = fake_constants.PROJECT2_ID
        self.admin_context = cinder_context.RequestContext(
            user_id=uuid.uuid4().hex, project_id=self.project_id,
            roles=['admin']
        )
        self.user_context = cinder_context.RequestContext(
            user_id=uuid.uuid4().hex, project_id=self.project_id,
            roles=['non-admin']
        )
        self.other_user_context = cinder_context.RequestContext(
            user_id=uuid.uuid4().hex, project_id=self.other_project_id,
            roles=['non-admin']
        )
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
    def test_admin_can_show_tenant_id_in_volume(self, mock_volume):
        # Make sure administrators are authorized to show tenant_id
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volume']
        self.assertEqual(admin_context.project_id,
                         res_vol['os-vol-tenant-attr:tenant_id'])

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_owner_can_show_tenant_id_in_volume(self, mock_volume):
        # Make sure owners are authorized to show tenant_id in volume
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volume']
        self.assertEqual(user_context.project_id,
                         res_vol['os-vol-tenant-attr:tenant_id'])

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

    def test_admin_can_show_tenant_id_in_volume_detail(self):
        # Make sure admins are authorized to show tenant_id in volume detail
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volumes'][0]
        # Make sure owners are authorized to show tenant_id
        self.assertEqual(admin_context.project_id,
                         res_vol['os-vol-tenant-attr:tenant_id'])

    def test_owner_can_show_tenant_id_in_volume_detail(self):
        # Make sure owners are authorized to show tenant_id in volume detail
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volumes'][0]
        # Make sure owners are authorized to show tenant_id
        self.assertEqual(user_context.project_id,
                         res_vol['os-vol-tenant-attr:tenant_id'])

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

    def test_nonadmin_user_can_create_volume(self):
        user_context = self.user_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': user_context.project_id
        }
        body = {"volume": {"size": 1}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)

        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_nonadmin_user_can_create_volume_from_image(self):
        user_context = self.user_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': user_context.project_id
        }
        body = {"volume": {"size": 1, "image_id": fake_constants.IMAGE_ID}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)

        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_admin_can_create_volume(self):
        admin_context = self.admin_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': admin_context.project_id
        }
        body = {"volume": {"size": 1}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)

        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_admin_can_create_volume_from_image(self):
        admin_context = self.admin_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': admin_context.project_id
        }
        body = {"volume": {"size": 1, "image_id": fake_constants.IMAGE_ID}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)

        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_admin_can_update_volumes(self, mock_volume):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"volume": {"name": "update_name"}}
        response = self._get_request_response(admin_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_can_update_volumes(self, mock_volume):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"volume": {"name": "update_name"}}
        response = self._get_request_response(user_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_update_volumes_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context)
        mock_volume.return_value = volume

        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"volume": {"name": "update_name"}}
        response = self._get_request_response(non_owner_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_can_delete_volumes(self, mock_volume):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'DELETE')
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_admin_can_delete_volumes(self, mock_volume):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'DELETE')
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_delete_volumes_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context)
        mock_volume.return_value = volume

        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(non_owner_context, path,
                                              'DELETE')
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'attach_volume')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'detach_volume')
    def test_admin_can_attach_detach_volume(self, mock_detach, mock_attach):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-attach": {"instance_uuid": fake_constants.UUID1,
                              "mountpoint": "/dev/vdc"}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

        body = {"os-detach": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'attach_volume')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'detach_volume')
    def test_owner_can_attach_detach_volume(self, mock_detach, mock_attach):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-attach": {"instance_uuid": fake_constants.UUID1,
                              "mountpoint": "/dev/vdc"}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

        body = {"os-detach": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'attach_volume')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'detach_volume')
    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_attach_detach_volume_for_others(self, mock_volume,
                                                          mock_detach,
                                                          mock_attach):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-attach": {"instance_uuid": fake_constants.UUID1,
                              "mountpoint": "/dev/vdc"}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

        body = {"os-detach": {}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_admin_can_reserve_unreserve_volume(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-reserve": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

        body = {"os-unreserve": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_owner_can_reserve_unreserve_volume(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-reserve": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

        body = {"os-unreserve": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_reserve_unreserve_volume_for_others(self,
                                                              mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-attach": {"instance_uuid": fake_constants.UUID1,
                              "mountpoint": "/dev/vdc"}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

        body = {"os-detach": {}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'initialize_connection')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'terminate_connection')
    def test_admin_can_initialize_terminate_conn(self, mock_t, mock_i):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-initialize_connection": {'connector': {}}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)

        body = {"os-terminate_connection": {'connector': {}}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'initialize_connection')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'terminate_connection')
    def test_owner_can_initialize_terminate_conn(self, mock_t, mock_i):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-initialize_connection": {'connector': {}}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)

        body = {"os-terminate_connection": {'connector': {}}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'initialize_connection')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'terminate_connection')
    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_initialize_terminate_conn_for_others(self,
                                                               mock_volume,
                                                               mock_t,
                                                               mock_i):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-initialize_connection": {'connector': {}}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

        body = {"os-terminate_connection": {'connector': {}}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_admin_can_begin_roll_detaching(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, status='in-use',
                                          attach_status='attached')
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-begin_detaching": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

        body = {"os-roll_detaching": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_owner_can_begin_roll_detaching(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, status='in-use',
                                          attach_status='attached')
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-begin_detaching": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

        body = {"os-roll_detaching": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_begin_roll_detaching_for_others(self, mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context, status='in-use',
                                          attach_status='attached')
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-begin_detaching": {}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

        body = {"os-roll_detaching": {}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_admin_can_create_metadata(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k1": "v1"}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)

    def test_admin_can_get_metadata(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'GET')
        self.assertEqual(http_client.OK, response.status_int)
        res_meta = response.json_body['metadata']
        self.assertIn('k', res_meta)
        self.assertEqual('v', res_meta['k'])

    def test_admin_can_update_metadata(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k": "v2"}}
        response = self._get_request_response(admin_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)
        res_meta = response.json_body['metadata']
        self.assertIn('k', res_meta)
        self.assertEqual('v2', res_meta['k'])

    def test_admin_can_delete_metadata(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, metadata={"k": "v"})

        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata/%(key)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id,
            'key': 'k'
        }
        response = self._get_request_response(admin_context, path, 'DELETE')
        self.assertEqual(http_client.OK, response.status_int)

    def test_owner_can_create_metadata(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k1": "v1"}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)

    def test_owner_can_get_metadata(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'GET')
        self.assertEqual(http_client.OK, response.status_int)
        res_meta = response.json_body['metadata']
        self.assertIn('k', res_meta)
        self.assertEqual('v', res_meta['k'])

    def test_owner_can_update_metadata(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k": "v2"}}
        response = self._get_request_response(user_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)
        res_meta = response.json_body['metadata']
        self.assertIn('k', res_meta)
        self.assertEqual('v2', res_meta['k'])

    def test_owner_can_delete_metadata(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, metadata={"k": "v"})

        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata/%(key)s' % {
            'project_id': user_context.project_id, 'volume_id': volume.id,
            'key': 'k'
        }
        response = self._get_request_response(user_context, path, 'DELETE')
        self.assertEqual(http_client.OK, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_create_metadata_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context, metadata={"k": "v"})
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k1": "v1"}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_get_metadata_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context, metadata={"k": "v"})
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(non_owner_context, path, 'GET')
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_update_metadata_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context, metadata={"k": "v"})
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k": "v2"}}
        response = self._get_request_response(non_owner_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_delete_metadata_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context, metadata={"k": "v"})
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata/%(key)s' % {
            'project_id': non_owner_context.project_id,
            'volume_id': volume.id,
            'key': 'k'
        }
        response = self._get_request_response(non_owner_context, path,
                                              'DELETE')
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_admin_can_extend_volume(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_owner_can_extend_volume(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_extend_volume_for_others(self, mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_admin_can_extend_attached_volume(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(
            admin_context, path, 'POST', body=body,
            microversion=mv.VOLUME_EXTEND_INUSE)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_owner_can_extend_attached_volume(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(
            user_context, path, 'POST', body=body,
            microversion=mv.VOLUME_EXTEND_INUSE)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_extend_attached_volume_for_others(self, mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(
            non_owner_context, path, 'POST', body=body,
            microversion=mv.VOLUME_EXTEND_INUSE)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_admin_can_retype_volume(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        vol_type = self._create_fake_type(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-retype": {"new_type": "%s" % vol_type.name,
                              "migration_policy": "never"}}
        response = self._get_request_response(
            admin_context, path, 'POST', body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_owner_can_retype_volume(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        vol_type = self._create_fake_type(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-retype": {"new_type": "%s" % vol_type.name,
                              "migration_policy": "never"}}
        response = self._get_request_response(
            user_context, path, 'POST', body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_retype_volume_for_others(self, mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        vol_type = self._create_fake_type(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-retype": {"new_type": "%s" % vol_type.name,
                              "migration_policy": "never"}}
        response = self._get_request_response(
            non_owner_context, path, 'POST', body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_admin_can_update_readonly(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(
            admin_context, admin_metadata={"readonly": "False"})

        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-update_readonly_flag": {"readonly": "True"}}
        response = self._get_request_response(
            admin_context, path, 'POST', body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_owner_can_update_readonly(self):
        user_context = self.user_context

        volume = self._create_fake_volume(
            user_context, admin_metadata={"readonly": "False"})

        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-update_readonly_flag": {"readonly": "True"}}
        response = self._get_request_response(
            user_context, path, 'POST', body=body)
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_update_readonly_for_others(self, mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(
            user_context, admin_metadata={"readonly": "False"})
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-update_readonly_flag": {"readonly": "True"}}
        response = self._get_request_response(
            non_owner_context, path, 'POST', body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)
