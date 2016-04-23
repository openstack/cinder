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

from cinder.api import extensions
from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import volumes
from cinder import context
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_notifier
from cinder.volume.api import API as vol_get

version_header_name = 'OpenStack-API-Version'


class VolumeApiTest(test.TestCase):

    def setUp(self):
        super(VolumeApiTest, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = volumes.VolumeController(self.ext_mgr)

        self.flags(host='fake',
                   notification_driver=[fake_notifier.__name__])
        self.ctxt = context.RequestContext(fake.user_id, fake.project_id, True)

    def test_check_volume_filters_called(self):
        with mock.patch.object(vol_get,
                               'check_volume_filters') as volume_get:
            req = fakes.HTTPRequest.blank('/v3/volumes?bootable=True')
            req.method = 'GET'
            req.content_type = 'application/json'
            req.headers = {version_header_name: 'volume 3.0'}
            req.environ['cinder.context'].is_admin = True

            self.override_config('query_volume_filters', 'bootable')
            self.controller.index(req)
            filters = req.params.copy()

            volume_get.assert_called_with(filters, False)

    def test_check_volume_filters_strict_called(self):

        with mock.patch.object(vol_get,
                               'check_volume_filters') as volume_get:
            req = fakes.HTTPRequest.blank('/v3/volumes?bootable=True')
            req.method = 'GET'
            req.content_type = 'application/json'
            req.headers = {version_header_name: 'volume 3.2'}
            req.environ['cinder.context'].is_admin = True
            req.api_version_request = api_version.max_api_version()

            self.override_config('query_volume_filters', 'bootable')
            self.controller.index(req)
            filters = req.params.copy()

            volume_get.assert_called_with(filters, True)
