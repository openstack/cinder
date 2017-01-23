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
import webob

from cinder.api.v3 import attachments as v3_attachments
from cinder import context
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.volume import api as volume_api

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
        self.attachment1 = self._create_attachement(
            volume_uuid=fake.VOLUME_ID, instance_uuid=fake.UUID1)
        self.attachment2 = self._create_attachement(
            volume_uuid=fake.VOLUME2_ID, instance_uuid=fake.UUID1)
        self.attachment3 = self._create_attachement(
            volume_uuid=fake.VOLUME3_ID, instance_uuid=fake.UUID2)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.attachment1.destroy()
        self.attachment2.destroy()
        self.attachment3.destroy()

    def _create_attachement(self, ctxt=None, volume_uuid=None,
                            instance_uuid=None, mountpoint=None,
                            attach_time=None, detach_time=None,
                            attach_status=None, attach_mode=None):
        """Create a attachement object."""
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
