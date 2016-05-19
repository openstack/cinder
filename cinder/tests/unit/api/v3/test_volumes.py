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
from oslo_config import cfg

from cinder.api import extensions
from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import volumes
from cinder import context
from cinder import db
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_notifier
from cinder.volume.api import API as vol_get

version_header_name = 'OpenStack-API-Version'

CONF = cfg.CONF


class VolumeApiTest(test.TestCase):
    def setUp(self):
        super(VolumeApiTest, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = volumes.VolumeController(self.ext_mgr)

        self.flags(host='fake',
                   notification_driver=[fake_notifier.__name__])
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

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

    def _create_volume_with_glance_metadata(self):
        vol1 = db.volume_create(self.ctxt, {'display_name': 'test1',
                                            'project_id':
                                            self.ctxt.project_id})
        db.volume_glance_metadata_create(self.ctxt, vol1.id, 'image_name',
                                         'imageTestOne')
        vol2 = db.volume_create(self.ctxt, {'display_name': 'test2',
                                            'project_id':
                                            self.ctxt.project_id})
        db.volume_glance_metadata_create(self.ctxt, vol2.id, 'image_name',
                                         'imageTestTwo')
        db.volume_glance_metadata_create(self.ctxt, vol2.id, 'disk_format',
                                         'qcow2')
        return [vol1, vol2]

    def test_volume_index_filter_by_glance_metadata(self):
        vols = self._create_volume_with_glance_metadata()
        req = fakes.HTTPRequest.blank("/v3/volumes?glance_metadata="
                                      "{'image_name': 'imageTestOne'}")
        req.headers["OpenStack-API-Version"] = "volume 3.4"
        req.api_version_request = api_version.APIVersionRequest('3.4')
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(vols[0].id, volumes[0]['id'])

    def test_volume_index_filter_by_glance_metadata_in_unsupport_version(self):
        self._create_volume_with_glance_metadata()
        req = fakes.HTTPRequest.blank("/v3/volumes?glance_metadata="
                                      "{'image_name': 'imageTestOne'}")
        req.headers["OpenStack-API-Version"] = "volume 3.0"
        req.api_version_request = api_version.APIVersionRequest('3.0')
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(2, len(volumes))
