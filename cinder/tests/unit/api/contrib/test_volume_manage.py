#   Copyright 2014 IBM Corp.
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
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from six.moves import http_client
from six.moves.urllib.parse import urlencode
import webob

from cinder.api.contrib import volume_manage
from cinder.api import microversions as mv
from cinder.api.openstack import api_version_request as api_version
from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume

CONF = cfg.CONF


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v2'] = api
    return mapper


def app_v3():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v3'] = api
    return mapper


def service_get(context, service_id, backend_match_level=None, host=None,
                **filters):
    """Replacement for db.sqlalchemy.api.service_get.

    We mock the db.sqlalchemy.api.service_get method to return something for a
    specific host, and raise an exception for anything else.
    We don't use the returned data (the code under test just use the call to
    check for existence of a host, so the content returned doesn't matter.
    """
    if host == 'host_ok':
        return {'disabled': False,
                'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}
    if host == 'host_disabled':
        return {'disabled': True,
                'uuid': '4200b32b-0bf9-436c-86b2-0675f6ac218e'}
    raise exception.ServiceNotFound(service_id=host)

# Some of the tests check that volume types are correctly validated during a
# volume manage operation.  This data structure represents an existing volume
# type.
fake_vt = {'id': fake.VOLUME_TYPE_ID,
           'name': 'good_fakevt'}


def vt_get_volume_type_by_name(context, name):
    """Replacement for cinder.volume.volume_types.get_volume_type_by_name.

    Overrides cinder.volume.volume_types.get_volume_type_by_name to return
    the volume type based on inspection of our fake structure, rather than
    going to the Cinder DB.
    """
    if name == fake_vt['name']:
        return fake_vt
    raise exception.VolumeTypeNotFoundByName(volume_type_name=name)


def vt_get_volume_type(context, vt_id):
    """Replacement for cinder.volume.volume_types.get_volume_type.

    Overrides cinder.volume.volume_types.get_volume_type to return the
    volume type based on inspection of our fake structure, rather than going
    to the Cinder DB.
    """
    if vt_id == fake_vt['id']:
        return fake_vt
    raise exception.VolumeTypeNotFound(volume_type_id=vt_id)


def api_manage(*args, **kwargs):
    """Replacement for cinder.volume.api.API.manage_existing.

    Overrides cinder.volume.api.API.manage_existing to return some fake volume
    data structure, rather than initiating a real volume managing.

    Note that we don't try to replicate any passed-in information (e.g. name,
    volume type) in the returned structure.
    """
    ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
    vol = {
        'status': 'creating',
        'display_name': 'fake_name',
        'availability_zone': 'nova',
        'tenant_id': fake.PROJECT_ID,
        'id': fake.VOLUME_ID,
        'volume_type': None,
        'snapshot_id': None,
        'user_id': fake.USER_ID,
        'size': 0,
        'attach_status': fields.VolumeAttachStatus.DETACHED,
        'volume_type_id': None}
    return fake_volume.fake_volume_obj(ctx, **vol)


def api_manage_new(*args, **kwargs):
    volume = api_manage()
    volume.status = 'managing'
    return volume


def api_get_manageable_volumes(*args, **kwargs):
    """Replacement for cinder.volume.api.API.get_manageable_volumes."""
    vols = [
        {'reference': {'source-name': 'volume-%s' % fake.VOLUME_ID},
         'size': 4,
         'extra_info': 'qos_setting:high',
         'safe_to_manage': False,
         'cinder_id': fake.VOLUME_ID,
         'reason_not_safe': 'volume in use'},
        {'reference': {'source-name': 'myvol'},
         'size': 5,
         'extra_info': 'qos_setting:low',
         'safe_to_manage': True,
         'cinder_id': None,
         'reason_not_safe': None}]
    return vols


@ddt.ddt
@mock.patch('cinder.db.sqlalchemy.api.service_get', service_get)
@mock.patch('cinder.volume.volume_types.get_volume_type_by_name',
            vt_get_volume_type_by_name)
@mock.patch('cinder.volume.volume_types.get_volume_type',
            vt_get_volume_type)
class VolumeManageTest(test.TestCase):
    """Test cases for cinder/api/contrib/volume_manage.py

    The API extension adds a POST /os-volume-manage API that is passed a cinder
    host name, and a driver-specific reference parameter.  If everything
    is passed correctly, then the cinder.volume.api.API.manage_existing method
    is invoked to manage an existing storage object on the host.

    In this set of test cases, we are ensuring that the code correctly parses
    the request structure and raises the correct exceptions when things are not
    right, and calls down into cinder.volume.api.API.manage_existing with the
    correct arguments.
    """

    def setUp(self):
        super(VolumeManageTest, self).setUp()
        self._admin_ctxt = context.RequestContext(fake.USER_ID,
                                                  fake.PROJECT_ID,
                                                  is_admin=True)
        self._non_admin_ctxt = context.RequestContext(fake.USER_ID,
                                                      fake.PROJECT_ID,
                                                      is_admin=False)
        self.controller = volume_manage.VolumeManageController()

    def _get_resp_post(self, body):
        """Helper to execute a POST os-volume-manage API call."""
        req = webob.Request.blank('/v2/%s/os-volume-manage' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.environ['cinder.context'] = self._admin_ctxt
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(app())
        return res

    def _get_resp_post_v3(self, body, version):
        """Helper to execute a POST os-volume-manage API call."""
        req = webob.Request.blank('/v3/%s/os-volume-manage' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.environ['cinder.context'] = self._admin_ctxt
        req.headers["OpenStack-API-Version"] = "volume " + version
        req.api_version_request = api_version.APIVersionRequest(version)
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(app_v3())
        return res

    @ddt.data({'host': 'host_ok'},
              {'host': 'user@host#backend:/vol_path'},
              {'host': 'host@backend#parts+of+pool'})
    @ddt.unpack
    @mock.patch('cinder.volume.api.API.manage_existing', wraps=api_manage)
    def test_manage_volume_ok(self, mock_api_manage, host):
        """Test successful manage volume execution.

        Tests for correct operation when valid arguments are passed in the
        request body.  We ensure that cinder.volume.api.API.manage_existing got
        called with the correct arguments, and that we return the correct HTTP
        code to the caller.
        """
        body = {'volume': {'host': host,
                           'ref': 'fake_ref'}}

        res = self._get_resp_post(body)
        self.assertEqual(http_client.ACCEPTED, res.status_int)

        # Check that the manage API was called with the correct arguments.
        self.assertEqual(1, mock_api_manage.call_count)
        args = mock_api_manage.call_args[0]
        self.assertEqual(body['volume']['host'], args[1])
        self.assertEqual(body['volume']['ref'], args[3])

    def test_manage_volume_not_ok(self):
        """Test not successful manage volume execution.

        Tests for error raised when invalid arguments are passed in the
        request body.
        """
        body = {'volume': {'host': 'host not ok',
                           'ref': 'fake_ref'}}

        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    def _get_resp_create(self, body, version=mv.BASE_VERSION):
        url = '/v3/%s/os-volume-manage' % fake.PROJECT_ID
        req = webob.Request.blank(url, base_url='http://localhost.com' + url)
        req.method = 'POST'
        req.headers = mv.get_mv_header(version)
        req.headers['Content-Type'] = 'application/json'
        req.environ['cinder.context'] = self._admin_ctxt
        req.body = jsonutils.dump_as_bytes(body)
        req.api_version_request = mv.get_api_version(version)
        res = self.controller.create(req, body=body)
        return res

    @mock.patch('cinder.volume.api.API.manage_existing', wraps=api_manage)
    def test_manage_volume_ok_cluster(self, mock_api_manage):
        body = {'volume': {'cluster': 'cluster',
                           'ref': 'fake_ref'}}
        res = self._get_resp_create(body, mv.VOLUME_MIGRATE_CLUSTER)
        self.assertEqual(['volume'], list(res.keys()))

        # Check that the manage API was called with the correct arguments.
        self.assertEqual(1, mock_api_manage.call_count)
        args = mock_api_manage.call_args[0]
        self.assertIsNone(args[1])
        self.assertEqual(body['volume']['cluster'], args[2])
        self.assertEqual(body['volume']['ref'], args[3])

    def test_manage_volume_fail_host_cluster(self):
        body = {'volume': {'host': 'host_ok',
                           'cluster': 'cluster',
                           'ref': 'fake_ref'}}
        self.assertRaises(exception.InvalidInput,
                          self._get_resp_create, body,
                          mv.VOLUME_MIGRATE_CLUSTER)

    def test_manage_volume_missing_host(self):
        """Test correct failure when host is not specified."""
        body = {'volume': {'ref': 'fake_ref'}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    @mock.patch('cinder.objects.Service.get_by_args')
    def test_manage_volume_service_not_found_on_host(self, mock_service):
        """Test correct failure when host having no volume service on it."""
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref'}}
        mock_service.side_effect = exception.ServiceNotFound(
            service_id='cinder-volume',
            host='host_ok')
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    def test_manage_volume_missing_ref(self):
        """Test correct failure when the ref is not specified."""
        body = {'volume': {'host': 'host_ok'}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    def test_manage_volume_with_invalid_bootable(self):
        """Test correct failure when invalid bool value is specified."""
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref',
                           'bootable': 'InvalidBool'}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    @mock.patch('cinder.objects.service.Service.is_up', return_value=True,
                new_callable=mock.PropertyMock)
    def test_manage_volume_disabled(self, mock_is_up):
        """Test manage volume failure due to disabled service."""
        body = {'volume': {'host': 'host_disabled', 'ref': 'fake_ref'}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int, res)
        self.assertEqual(exception.ServiceUnavailable.message,
                         res.json['badRequest']['message'])
        mock_is_up.assert_not_called()

    @mock.patch('cinder.objects.service.Service.is_up', return_value=False,
                new_callable=mock.PropertyMock)
    def test_manage_volume_is_down(self, mock_is_up):
        """Test manage volume failure due to down service."""
        body = {'volume': {'host': 'host_ok', 'ref': 'fake_ref'}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int, res)
        self.assertEqual(exception.ServiceUnavailable.message,
                         res.json['badRequest']['message'])
        self.assertTrue(mock_is_up.called)

    @mock.patch('cinder.volume.api.API.manage_existing', api_manage)
    def test_manage_volume_volume_type_by_uuid(self):
        """Tests for correct operation when a volume type is specified by ID.

        We wrap cinder.volume.api.API.manage_existing so that managing is not
        actually attempted.
        """
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref',
                           'volume_type': fake.VOLUME_TYPE_ID,
                           'bootable': True}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.ACCEPTED, res.status_int)

    @mock.patch('cinder.volume.api.API.manage_existing', api_manage)
    def test_manage_volume_volume_type_by_name(self):
        """Tests for correct operation when a volume type is specified by name.

        We wrap cinder.volume.api.API.manage_existing so that managing is not
        actually attempted.
        """
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref',
                           'volume_type': 'good_fakevt'}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.ACCEPTED, res.status_int)

    def test_manage_volume_bad_volume_type_by_uuid(self):
        """Test failure on nonexistent volume type specified by ID."""
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref',
                           'volume_type': fake.WILL_NOT_BE_FOUND_ID}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    def test_manage_volume_bad_volume_type_by_name(self):
        """Test failure on nonexistent volume type specified by name."""
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref',
                           'volume_type': 'bad_fakevt'}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    def _get_resp_get(self, host, detailed, paging, admin=True):
        """Helper to execute a GET os-volume-manage API call."""
        params = {'host': host}
        if paging:
            params.update({'marker': '1234', 'limit': 10,
                           'offset': 4, 'sort': 'reference:asc'})
        query_string = "?%s" % urlencode(params)
        detail = ""
        if detailed:
            detail = "/detail"
        url = "/v2/%s/os-volume-manage%s%s" % (fake.PROJECT_ID, detail,
                                               query_string)
        req = webob.Request.blank(url)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.environ['cinder.context'] = (self._admin_ctxt if admin
                                         else self._non_admin_ctxt)
        res = req.get_response(app())
        return res

    @mock.patch('cinder.volume.api.API.get_manageable_volumes',
                wraps=api_get_manageable_volumes)
    def test_get_manageable_volumes_non_admin(self, mock_api_manageable):
        res = self._get_resp_get('fakehost', False, False, admin=False)
        self.assertEqual(http_client.FORBIDDEN, res.status_int)
        mock_api_manageable.assert_not_called()
        res = self._get_resp_get('fakehost', True, False, admin=False)
        self.assertEqual(http_client.FORBIDDEN, res.status_int)
        mock_api_manageable.assert_not_called()

    @mock.patch('cinder.volume.api.API.get_manageable_volumes',
                wraps=api_get_manageable_volumes)
    def test_get_manageable_volumes_ok(self, mock_api_manageable):
        res = self._get_resp_get('fakehost', False, True)
        exp = {'manageable-volumes':
               [{'reference':
                 {'source-name':
                  'volume-%s' % fake.VOLUME_ID},
                 'size': 4, 'safe_to_manage': False},
                {'reference': {'source-name': 'myvol'},
                 'size': 5, 'safe_to_manage': True}]}
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(exp, jsonutils.loads(res.body))
        mock_api_manageable.assert_called_once_with(
            self._admin_ctxt, 'fakehost', None, limit=10, marker='1234',
            offset=4, sort_dirs=['asc'], sort_keys=['reference'])

    @mock.patch('cinder.volume.api.API.get_manageable_volumes',
                side_effect=messaging.RemoteError(
                    exc_type='InvalidInput', value='marker not found: 1234'))
    def test_get_manageable_volumes_non_existent_marker(self,
                                                        mock_api_manageable):
        res = self._get_resp_get('fakehost', detailed=False, paging=True)
        self.assertEqual(400, res.status_int)
        self.assertTrue(mock_api_manageable.called)

    @mock.patch('cinder.volume.api.API.get_manageable_volumes',
                wraps=api_get_manageable_volumes)
    def test_get_manageable_volumes_detailed_ok(self, mock_api_manageable):
        res = self._get_resp_get('fakehost', True, False)
        exp = {'manageable-volumes':
               [{'reference': {'source-name': 'volume-%s' % fake.VOLUME_ID},
                 'size': 4, 'reason_not_safe': 'volume in use',
                 'cinder_id': fake.VOLUME_ID, 'safe_to_manage': False,
                 'extra_info': 'qos_setting:high'},
                {'reference': {'source-name': 'myvol'}, 'cinder_id': None,
                 'size': 5, 'reason_not_safe': None, 'safe_to_manage': True,
                 'extra_info': 'qos_setting:low'}]}
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(exp, jsonutils.loads(res.body))
        mock_api_manageable.assert_called_once_with(
            self._admin_ctxt, 'fakehost', None, limit=CONF.osapi_max_limit,
            marker=None, offset=0, sort_dirs=['desc'],
            sort_keys=['reference'])

    @mock.patch('cinder.volume.api.API.get_manageable_volumes',
                side_effect=messaging.RemoteError(
                    exc_type='InvalidInput', value='marker not found: 1234'))
    def test_get_manageable_volumes_non_existent_marker_detailed(
            self, mock_api_manageable):
        res = self._get_resp_get('fakehost', detailed=True, paging=True)
        self.assertEqual(400, res.status_int)
        self.assertTrue(mock_api_manageable.called)

    @ddt.data({'a' * 256: 'a'},
              {'a': 'a' * 256},
              {'': 'a'},
              {'a': None},
              )
    def test_manage_volume_with_invalid_metadata(self, value):
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref',
                           "metadata": value}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    @mock.patch('cinder.objects.service.Service.is_up', return_value=True,
                new_callable=mock.PropertyMock)
    def test_get_manageable_volumes_disabled(self, mock_is_up):
        res = self._get_resp_get('host_disabled', False, True)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int, res)
        self.assertEqual(exception.ServiceUnavailable.message,
                         res.json['badRequest']['message'])
        mock_is_up.assert_not_called()

    @mock.patch('cinder.objects.service.Service.is_up', return_value=False,
                new_callable=mock.PropertyMock)
    def test_get_manageable_volumes_is_down(self, mock_is_up):
        res = self._get_resp_get('host_ok', False, True)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int, res)
        self.assertEqual(exception.ServiceUnavailable.message,
                         res.json['badRequest']['message'])
        self.assertTrue(mock_is_up.called)

    @mock.patch('cinder.volume.api.API.manage_existing', wraps=api_manage_new)
    def test_manage_volume_with_creating_status_in_v3(self, mock_api_manage):
        """Test managing volume to return 'creating' status in V3 API."""
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref'}}
        res = self._get_resp_post_v3(body, mv.ETAGS)
        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(1, mock_api_manage.call_count)
        self.assertEqual('creating',
                         jsonutils.loads(res.body)['volume']['status'])

    @mock.patch('cinder.volume.api.API.manage_existing', wraps=api_manage_new)
    def test_manage_volume_with_creating_status_in_v2(self, mock_api_manage):
        """Test managing volume to return 'creating' status in V2 API."""

        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref'}}
        res = self._get_resp_post(body)
        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(1, mock_api_manage.call_count)
        self.assertEqual('creating',
                         jsonutils.loads(res.body)['volume']['status'])

    @ddt.data({'volume': {}}, None)
    def test_manage_volume_with_invalid_body(self, body):
        res = self._get_resp_post(body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
