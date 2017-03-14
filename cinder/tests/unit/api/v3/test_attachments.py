# Copyright (C) 2017 HuaWei Corporation.
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

"""
Tests for attachments Api.
"""

import ddt
import mock
import webob

from cinder.api.v3 import attachments as v3_attachments
from cinder import context
from cinder import exception
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.volume import api as volume_api
from cinder.volume import rpcapi as volume_rpcapi

ATTACHMENTS_MICRO_VERSION = '3.27'


@ddt.ddt
class AttachmentsAPITestCase(test.TestCase):
    """Test Case for attachment API."""

    def setUp(self):
        super(AttachmentsAPITestCase, self).setUp()
        self.controller = v3_attachments.AttachmentsController()
        self.volume_api = volume_api.API()
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                           auth_token=True,
                                           is_admin=True)
        self.volume1 = self._create_volume(display_name='fake_volume_1',
                                           project_id=fake.PROJECT_ID)
        self.volume2 = self._create_volume(display_name='fake_volume_2',
                                           project_id=fake.PROJECT2_ID)
        self.attachment1 = self._create_attachment(
            volume_uuid=self.volume1.id, instance_uuid=fake.UUID1)
        self.attachment2 = self._create_attachment(
            volume_uuid=self.volume1.id, instance_uuid=fake.UUID1)
        self.attachment3 = self._create_attachment(
            volume_uuid=self.volume1.id, instance_uuid=fake.UUID2)
        self.attachment4 = self._create_attachment(
            volume_uuid=self.volume2.id, instance_uuid=fake.UUID2)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.attachment1.destroy()
        self.attachment2.destroy()
        self.attachment3.destroy()
        self.attachment4.destroy()
        self.volume1.destroy()
        self.volume2.destroy()

    def _create_volume(self, ctxt=None, display_name=None, project_id=None):
        """Create a volume object."""
        ctxt = ctxt or self.ctxt
        volume = objects.Volume(ctxt)
        volume.display_name = display_name
        volume.project_id = project_id
        volume.status = 'available'
        volume.attach_status = 'attached'
        volume.create()
        return volume

    def test_create_attachment(self):
        req = fakes.HTTPRequest.blank('/v3/%s/attachments' %
                                      fake.PROJECT_ID,
                                      version=ATTACHMENTS_MICRO_VERSION)
        body = {
            "attachment":
                {
                    "connector": None,
                    "instance_uuid": fake.UUID1,
                    "volume_uuid": self.volume1.id
                },
        }

        attachment = self.controller.create(req, body)

        self.assertEqual(self.volume1.id,
                         attachment['attachment']['volume_id'])
        self.assertEqual(fake.UUID1,
                         attachment['attachment']['instance'])

    @mock.patch.object(volume_rpcapi.VolumeAPI, 'attachment_update')
    def test_update_attachment(self, mock_update):
        fake_connector = {'fake_key': 'fake_value'}
        mock_update.return_value = fake_connector
        req = fakes.HTTPRequest.blank('/v3/%s/attachments/%s' %
                                      (fake.PROJECT_ID, self.attachment1.id),
                                      version=ATTACHMENTS_MICRO_VERSION,
                                      use_admin_context=True)
        body = {
            "attachment":
                {
                    "connector": {'fake_key': 'fake_value'},
                },
        }

        attachment = self.controller.update(req, self.attachment1.id, body)

        self.assertEqual(fake_connector,
                         attachment['attachment']['connection_info'])
        self.assertEqual(fake.UUID1, attachment['attachment']['instance'])

    @mock.patch.object(objects.VolumeAttachment, 'get_by_id')
    def test_attachment_operations_not_authorized(self, mock_get):
        mock_get.return_value = {'project_id': fake.PROJECT2_ID}
        req = fakes.HTTPRequest.blank('/v3/%s/attachments/%s' %
                                      (fake.PROJECT_ID, self.attachment1.id),
                                      version=ATTACHMENTS_MICRO_VERSION,
                                      use_admin_context=False)
        body = {
            "attachment":
                {
                    "connector": {'fake_key': 'fake_value'},
                },
        }
        self.assertRaises(exception.NotAuthorized,
                          self.controller.update, req,
                          self.attachment1.id, body)
        self.assertRaises(exception.NotAuthorized,
                          self.controller.delete, req,
                          self.attachment1.id)

    @ddt.data('3.30', '3.31', '3.34')
    @mock.patch('cinder.api.common.reject_invalid_filters')
    def test_attachment_list_with_general_filter(self, version, mock_update):
        url = '/v3/%s/attachments' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url,
                                      version=version,
                                      use_admin_context=False)
        self.controller.index(req)

        if version != '3.30':
            support_like = True if version == '3.34' else False
            mock_update.assert_called_once_with(req.environ['cinder.context'],
                                                mock.ANY, 'attachment',
                                                support_like)

    @ddt.data('reserved', 'attached')
    @mock.patch.object(volume_rpcapi.VolumeAPI, 'attachment_delete')
    def test_delete_attachment(self, status, mock_delete):
        volume1 = self._create_volume(display_name='fake_volume_1',
                                      project_id=fake.PROJECT_ID)
        attachment = self._create_attachment(
            volume_uuid=volume1.id, instance_uuid=fake.UUID1,
            attach_status=status)
        req = fakes.HTTPRequest.blank('/v3/%s/attachments/%s' %
                                      (fake.PROJECT_ID, attachment.id),
                                      version=ATTACHMENTS_MICRO_VERSION,
                                      use_admin_context=True)

        self.controller.delete(req, attachment.id)

        volume2 = objects.Volume.get_by_id(self.ctxt, volume1.id)
        if status == 'reserved':
            self.assertEqual('detached', volume2.attach_status)
            self.assertRaises(
                exception.VolumeAttachmentNotFound,
                objects.VolumeAttachment.get_by_id, self.ctxt, attachment.id)
        else:
            self.assertEqual('attached', volume2.attach_status)
            mock_delete.assert_called_once_with(req.environ['cinder.context'],
                                                attachment.id, mock.ANY)

    def _create_attachment(self, ctxt=None, volume_uuid=None,
                           instance_uuid=None, mountpoint=None,
                           attach_time=None, detach_time=None,
                           attach_status=None, attach_mode=None):
        """Create an attachment object."""
        ctxt = ctxt or self.ctxt
        attachment = objects.VolumeAttachment(ctxt)
        attachment.volume_id = volume_uuid
        attachment.instance_uuid = instance_uuid
        attachment.mountpoint = mountpoint
        attachment.attach_time = attach_time
        attachment.detach_time = detach_time
        attachment.attach_status = attach_status or 'reserved'
        attachment.attach_mode = attach_mode
        attachment.create()
        return attachment

    @ddt.data("instance_uuid", "volume_uuid")
    def test_create_attachment_without_resource_uuid(self, resource_uuid):
        req = fakes.HTTPRequest.blank('/v3/%s/attachments' %
                                      fake.PROJECT_ID,
                                      version=ATTACHMENTS_MICRO_VERSION)
        body = {
            "attachment":
                {
                    "connector": None
                }
        }
        body["attachment"][resource_uuid] = "test_id"

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    @ddt.data(False, True)
    def test_list_attachments(self, is_detail):
        url = '/v3/%s/attachments' % fake.PROJECT_ID
        list_func = self.controller.index
        if is_detail:
            url = '/v3/%s/groups/detail' % fake.PROJECT_ID
            list_func = self.controller.detail
        req = fakes.HTTPRequest.blank(url, version=ATTACHMENTS_MICRO_VERSION,
                                      use_admin_context=True)
        res_dict = list_func(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(3, len(res_dict['attachments']))
        self.assertEqual(self.attachment3.id,
                         res_dict['attachments'][0]['id'])

    def test_list_attachments_with_limit(self):
        url = '/v3/%s/attachments?limit=1' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, version=ATTACHMENTS_MICRO_VERSION,
                                      use_admin_context=True)
        res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(1, len(res_dict['attachments']))

    def test_list_attachments_with_marker(self):
        url = '/v3/%s/attachments?marker=%s' % (fake.PROJECT_ID,
                                                self.attachment3.id)
        req = fakes.HTTPRequest.blank(url, version=ATTACHMENTS_MICRO_VERSION,
                                      use_admin_context=True)
        res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(2, len(res_dict['attachments']))
        self.assertEqual(self.attachment2.id,
                         res_dict['attachments'][0]['id'])

    @ddt.data("desc", "asc")
    def test_list_attachments_with_sort(self, sort_dir):
        url = '/v3/%s/attachments?sort_key=id&sort_dir=%s' % (fake.PROJECT_ID,
                                                              sort_dir)
        req = fakes.HTTPRequest.blank(url, version=ATTACHMENTS_MICRO_VERSION,
                                      use_admin_context=True)
        res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(3, len(res_dict['attachments']))
        order_ids = sorted([self.attachment1.id,
                            self.attachment2.id,
                            self.attachment3.id])
        expect_result = order_ids[2] if sort_dir == "desc" else order_ids[0]
        self.assertEqual(expect_result,
                         res_dict['attachments'][0]['id'])

    @ddt.data({'admin': True, 'request_url': '?all_tenants=1', 'count': 4},
              {'admin': False, 'request_url': '?all_tenants=1', 'count': 3},
              {'admin': True, 'request_url':
                  '?all_tenants=1&project_id=%s' % fake.PROJECT2_ID,
               'count': 1},
              {'admin': False, 'request_url': '', 'count': 3},
              {'admin': False, 'request_url': '?instance_id=%s' % fake.UUID1,
               'count': 2},
              {'admin': False, 'request_url': '?instance_id=%s' % fake.UUID2,
               'count': 1})
    @ddt.unpack
    def test_list_attachment_with_tenants(self, admin, request_url, count):
        url = '/v3/%s/attachments%s' % (fake.PROJECT_ID, request_url)
        req = fakes.HTTPRequest.blank(url, version=ATTACHMENTS_MICRO_VERSION,
                                      use_admin_context=admin)
        res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(count, len(res_dict['attachments']))
