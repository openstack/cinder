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
