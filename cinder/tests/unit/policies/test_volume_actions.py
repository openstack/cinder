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

import mock
from six.moves import http_client

from cinder.api import microversions as mv
from cinder.tests.unit import fake_constants
from cinder.tests.unit.policies import test_base
from cinder.volume import api as volume_api


# TODO(yikun): The below policy test cases should be added:
# * REVERT_POLICY
# * RESET_STATUS
# * FORCE_DETACH_POLICY
# * UPLOAD_PUBLIC_POLICY
# * UPLOAD_IMAGE_POLICY
# * MIGRATE_POLICY
# * MIGRATE_COMPLETE_POLICY
class VolumeProtectionTests(test_base.CinderPolicyTests):
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
