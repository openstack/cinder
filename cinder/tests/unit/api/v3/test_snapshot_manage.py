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

import ddt
import mock
from oslo_config import cfg
from oslo_serialization import jsonutils
from six.moves import http_client
from six.moves.urllib.parse import urlencode
import webob

from cinder.api import microversions as mv
from cinder.api.v3 import router as router_v3
from cinder.common import constants
from cinder import context
from cinder import objects
from cinder import test
from cinder.tests.unit.api.contrib import test_snapshot_manage as test_contrib
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_service


CONF = cfg.CONF


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = router_v3.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v3'] = api
    return mapper


@ddt.ddt
@mock.patch('cinder.volume.api.API.get', test_contrib.volume_get)
class SnapshotManageTest(test.TestCase):
    """Test cases for cinder/api/v3/snapshot_manage.py"""
    def setUp(self):
        super(SnapshotManageTest, self).setUp()
        self._admin_ctxt = context.RequestContext(fake.USER_ID,
                                                  fake.PROJECT_ID,
                                                  True)

    def _get_resp_post(self, body, version=mv.MANAGE_EXISTING_LIST):
        """Helper to execute a POST manageable_snapshots API call."""
        req = webob.Request.blank('/v3/%s/manageable_snapshots' %
                                  fake.PROJECT_ID)
        req.method = 'POST'
        req.headers = mv.get_mv_header(version)
        req.headers['Content-Type'] = 'application/json'
        req.environ['cinder.context'] = self._admin_ctxt
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(app())
        return res

    @mock.patch(
        'cinder.scheduler.rpcapi.SchedulerAPI.manage_existing_snapshot')
    @mock.patch('cinder.volume.api.API.create_snapshot_in_db')
    @mock.patch('cinder.objects.service.Service.get_by_id')
    def test_manage_snapshot_route(self, mock_service_get,
                                   mock_create_snapshot, mock_rpcapi):
        """Test call to manage snapshot.

        There is currently no change between the API in contrib and the API in
        v3, so here we simply check that the call is routed properly, rather
        than copying all the tests.
        """
        mock_service_get.return_value = fake_service.fake_service_obj(
            self._admin_ctxt,
            binary=constants.VOLUME_BINARY)

        body = {'snapshot': {'volume_id': fake.VOLUME_ID,
                             'ref': {'fake_ref': "fake_val"}}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.ACCEPTED, res.status_int, res)

    def test_manage_snapshot_previous_version(self):
        body = {'snapshot': {'volume_id': fake.VOLUME_ID, 'ref': 'fake_ref'}}
        res = self._get_resp_post(
            body, version=mv.get_prior_version(mv.MANAGE_EXISTING_LIST))
        self.assertEqual(http_client.NOT_FOUND, res.status_int, res)

    def _get_resp_get(self, host, detailed, paging,
                      version=mv.MANAGE_EXISTING_LIST, **kwargs):
        """Helper to execute a GET os-snapshot-manage API call."""
        params = {'host': host} if host else {}
        params.update(kwargs)
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
        req.headers = mv.get_mv_header(version)
        req.headers['Content-Type'] = 'application/json'
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
        self.assertEqual(http_client.OK, res.status_int)

    def test_get_manageable_snapshots_previous_version(self):
        res = self._get_resp_get(
            'fakehost', False, False,
            version=mv.get_prior_version(mv.MANAGE_EXISTING_LIST))
        self.assertEqual(http_client.NOT_FOUND, res.status_int)

    @mock.patch('cinder.volume.api.API.get_manageable_snapshots',
                wraps=test_contrib.api_get_manageable_snapshots)
    def test_get_manageable_snapshots_detail_route(self, mock_api_manageable):
        """Test call to get manageable volumes (detailed).

        There is currently no change between the API in contrib and the API in
        v3, so here we simply check that the call is routed properly, rather
        than copying all the tests.
        """
        res = self._get_resp_get('fakehost', True, True)
        self.assertEqual(http_client.OK, res.status_int)

    def test_get_manageable_snapshots_detail_previous_version(self):
        res = self._get_resp_get(
            'fakehost', True, True,
            version=mv.get_prior_version(mv.MANAGE_EXISTING_LIST))
        self.assertEqual(http_client.NOT_FOUND, res.status_int)

    @ddt.data((True, True, 'detail_list'), (True, False, 'summary_list'),
              (False, True, 'detail_list'), (False, False, 'summary_list'))
    @ddt.unpack
    @mock.patch('cinder.objects.Service.is_up', True)
    @mock.patch('cinder.volume.rpcapi.VolumeAPI._get_cctxt')
    @mock.patch('cinder.objects.Service.get_by_id')
    def test_get_manageable_detail(self, clustered, is_detail, view_method,
                                   get_service_mock, get_cctxt_mock):
        if clustered:
            host = None
            cluster_name = 'mycluster'
            version = mv.MANAGE_EXISTING_CLUSTER
            kwargs = {'cluster': cluster_name}
        else:
            host = 'fakehost'
            cluster_name = None
            version = mv.MANAGE_EXISTING_LIST
            kwargs = {}
        service = objects.Service(disabled=False, host='fakehost',
                                  cluster_name=cluster_name)
        get_service_mock.return_value = service
        snaps = [mock.sentinel.snap1, mock.sentinel.snap2]
        get_cctxt_mock.return_value.call.return_value = snaps

        view_data = {'manageable-snapshots': [{'vol': 'mock.sentinel.snap1'},
                                              {'vol': 'mock.sentinel.snap2'}]}
        view_path = ('cinder.api.views.manageable_snapshots.ViewBuilder.' +
                     view_method)
        with mock.patch(view_path, return_value=view_data) as detail_view_mock:
            res = self._get_resp_get(host, is_detail, False, version=version,
                                     **kwargs)

        self.assertEqual(http_client.OK, res.status_int)
        get_cctxt_mock.assert_called_once_with(service.service_topic_queue,
                                               version=('3.10', '3.0'))
        get_cctxt_mock.return_value.call.assert_called_once_with(
            mock.ANY, 'get_manageable_snapshots', marker=None,
            limit=CONF.osapi_max_limit, offset=0, sort_keys=['reference'],
            sort_dirs=['desc'], want_objects=True)
        detail_view_mock.assert_called_once_with(mock.ANY, snaps, len(snaps))
        get_service_mock.assert_called_once_with(
            mock.ANY, None, host=host, binary=constants.VOLUME_BINARY,
            cluster_name=cluster_name)

    @ddt.data(mv.MANAGE_EXISTING_LIST, mv.MANAGE_EXISTING_CLUSTER)
    def test_get_manageable_missing_host(self, version):
        res = self._get_resp_get(None, True, False, version=version)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    def test_get_manageable_both_host_cluster(self):
        res = self._get_resp_get('host', True, False,
                                 version=mv.MANAGE_EXISTING_CLUSTER,
                                 cluster='cluster')
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
