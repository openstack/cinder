#   Copyright (c) 2016 Stratoscale, Ltd.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import mock
from oslo_serialization import jsonutils
try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode
import webob

from cinder.api.v3 import router as router_v3
from cinder import context
from cinder import test
from cinder.tests.unit.api.contrib import test_volume_manage as test_contrib
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = router_v3.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v3'] = api
    return mapper


@mock.patch('cinder.objects.service.Service.get_by_host_and_topic',
            test_contrib.service_get)
@mock.patch('cinder.volume.volume_types.get_volume_type_by_name',
            test_contrib.vt_get_volume_type_by_name)
@mock.patch('cinder.volume.volume_types.get_volume_type',
            test_contrib.vt_get_volume_type)
class VolumeManageTest(test.TestCase):
    """Test cases for cinder/api/v3/volume_manage.py"""

    def setUp(self):
        super(VolumeManageTest, self).setUp()
        self._admin_ctxt = context.RequestContext(fake.USER_ID,
                                                  fake.PROJECT_ID,
                                                  True)

    def _get_resp_post(self, body, version="3.8"):
        """Helper to execute a POST manageable_volumes API call."""
        req = webob.Request.blank('/v3/%s/manageable_volumes' %
                                  fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume ' + version
        req.environ['cinder.context'] = self._admin_ctxt
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(app())
        return res

    @mock.patch('cinder.volume.api.API.manage_existing',
                wraps=test_contrib.api_manage)
    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_manage_volume_route(self, mock_validate, mock_api_manage):
        """Test call to manage volume.

        There is currently no change between the API in contrib and the API in
        v3, so here we simply check that the call is routed properly, rather
        than copying all the tests.
        """
        body = {'volume': {'host': 'host_ok', 'ref': 'fake_ref'}}
        res = self._get_resp_post(body)
        self.assertEqual(202, res.status_int, res)

    def test_manage_volume_previous_version(self):
        body = {'volume': {'host': 'host_ok', 'ref': 'fake_ref'}}
        res = self._get_resp_post(body)
        self.assertEqual(404, res.status_int, res)

    def _get_resp_get(self, host, detailed, paging, version="3.8"):
        """Helper to execute a GET os-volume-manage API call."""
        params = {'host': host}
        if paging:
            params.update({'marker': '1234', 'limit': 10,
                           'offset': 4, 'sort': 'reference:asc'})
        query_string = "?%s" % urlencode(params)
        detail = ""
        if detailed:
            detail = "/detail"

        req = webob.Request.blank('/v3/%s/manageable_volumes%s%s' %
                                  (fake.PROJECT_ID, detail, query_string))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume ' + version
        req.environ['cinder.context'] = self._admin_ctxt
        res = req.get_response(app())
        return res

    @mock.patch('cinder.volume.api.API.get_manageable_volumes',
                wraps=test_contrib.api_get_manageable_volumes)
    def test_get_manageable_volumes_route(self, mock_api_manageable):
        """Test call to get manageable volumes.

        There is currently no change between the API in contrib and the API in
        v3, so here we simply check that the call is routed properly, rather
        than copying all the tests.
        """
        res = self._get_resp_get('fakehost', False, True)
        self.assertEqual(200, res.status_int)

    def test_get_manageable_volumes_previous_version(self):
        res = self._get_resp_get('fakehost', False, True, version="3.7")
        self.assertEqual(404, res.status_int)

    @mock.patch('cinder.volume.api.API.get_manageable_volumes',
                wraps=test_contrib.api_get_manageable_volumes)
    def test_get_manageable_volumes_detail_route(self, mock_api_manageable):
        """Test call to get manageable volumes (detailed).

        There is currently no change between the API in contrib and the API in
        v3, so here we simply check that the call is routed properly, rather
        than copying all the tests.
        """
        res = self._get_resp_get('fakehost', True, False)
        self.assertEqual(200, res.status_int)

    def test_get_manageable_volumes_detail_previous_version(self):
        res = self._get_resp_get('fakehost', True, False, version="3.7")
        self.assertEqual(404, res.status_int)
