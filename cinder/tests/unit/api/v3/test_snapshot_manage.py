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
from cinder.tests.unit.api.contrib import test_snapshot_manage as test_contrib
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_service


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = router_v3.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v3'] = api
    return mapper


@mock.patch('cinder.volume.api.API.get', test_contrib.volume_get)
class SnapshotManageTest(test.TestCase):
    """Test cases for cinder/api/v3/snapshot_manage.py"""
    def setUp(self):
        super(SnapshotManageTest, self).setUp()
        self._admin_ctxt = context.RequestContext(fake.USER_ID,
                                                  fake.PROJECT_ID,
                                                  True)

    def _get_resp_post(self, body, version="3.8"):
        """Helper to execute a POST manageable_snapshots API call."""
        req = webob.Request.blank('/v3/%s/manageable_snapshots' %
                                  fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume ' + version
        req.environ['cinder.context'] = self._admin_ctxt
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(app())
        return res

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.manage_existing_snapshot')
    @mock.patch('cinder.volume.api.API.create_snapshot_in_db')
    @mock.patch('cinder.objects.service.Service.get_by_args')
    def test_manage_snapshot_route(self, mock_service_get,
                                   mock_create_snapshot, mock_rpcapi):
        """Test call to manage snapshot.

        There is currently no change between the API in contrib and the API in
        v3, so here we simply check that the call is routed properly, rather
        than copying all the tests.
        """
        mock_service_get.return_value = fake_service.fake_service_obj(
            self._admin_ctxt,
            binary='cinder-volume')

        body = {'snapshot': {'volume_id': fake.VOLUME_ID, 'ref': 'fake_ref'}}
        res = self._get_resp_post(body)
        self.assertEqual(202, res.status_int, res)

    def test_manage_snapshot_previous_version(self):
        body = {'snapshot': {'volume_id': fake.VOLUME_ID, 'ref': 'fake_ref'}}
        res = self._get_resp_post(body, version="3.7")
        self.assertEqual(404, res.status_int, res)

    def _get_resp_get(self, host, detailed, paging, version="3.8"):
        """Helper to execute a GET os-snapshot-manage API call."""
        params = {'host': host}
        if paging:
            params.update({'marker': '1234', 'limit': 10,
                           'offset': 4, 'sort': 'reference:asc'})
        query_string = "?%s" % urlencode(params)
        detail = ""
        if detailed:
            detail = "/detail"
        req = webob.Request.blank('/v3/%s/manageable_snapshots%s%s' %
                                  (fake.PROJECT_ID, detail, query_string))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['OpenStack-API-Version'] = 'volume ' + version
        req.environ['cinder.context'] = self._admin_ctxt
        res = req.get_response(app())
        return res

    @mock.patch('cinder.volume.api.API.get_manageable_snapshots',
                wraps=test_contrib.api_get_manageable_snapshots)
    def test_get_manageable_snapshots_route(self, mock_api_manageable):
        """Test call to get manageable volumes.

        There is currently no change between the API in contrib and the API in
        v3, so here we simply check that the call is routed properly, rather
        than copying all the tests.
        """
        res = self._get_resp_get('fakehost', False, False)
        self.assertEqual(200, res.status_int)

    def test_get_manageable_snapshots_previous_version(self):
        res = self._get_resp_get('fakehost', False, False, version="3.7")
        self.assertEqual(404, res.status_int)

    @mock.patch('cinder.volume.api.API.get_manageable_snapshots',
                wraps=test_contrib.api_get_manageable_snapshots)
    def test_get_manageable_snapshots_detail_route(self, mock_api_manageable):
        """Test call to get manageable volumes (detailed).

        There is currently no change between the API in contrib and the API in
        v3, so here we simply check that the call is routed properly, rather
        than copying all the tests.
        """
        res = self._get_resp_get('fakehost', True, True)
        self.assertEqual(200, res.status_int)

    def test_get_manageable_snapshots_detail_previous_version(self):
        res = self._get_resp_get('fakehost', True, True, version="3.7")
        self.assertEqual(404, res.status_int)
