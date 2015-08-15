#   Copyright 2014 IBM Corp.
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
import webob

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v2'] = api
    return mapper


def db_service_get_by_host_and_topic(context, host, topic):
    """Replacement for db.service_get_by_host_and_topic.

    We stub the db.service_get_by_host_and_topic method to return something
    for a specific host, and raise an exception for anything else.  We don't
    use the returned data (the code under test just use the call to check for
    existence of a host, so the content returned doesn't matter.
    """
    if host == 'host_ok':
        return {}
    raise exception.ServiceNotFound(service_id=host)

# Some of the tests check that volume types are correctly validated during a
# volume manage operation.  This data structure represents an existing volume
# type.
fake_vt = {'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
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
    vol = {
        'status': 'creating',
        'display_name': 'fake_name',
        'availability_zone': 'nova',
        'tenant_id': 'fake',
        'created_at': 'DONTCARE',
        'id': 'ffffffff-0000-ffff-0000-ffffffffffff',
        'volume_type': None,
        'snapshot_id': None,
        'user_id': 'fake',
        'launched_at': 'DONTCARE',
        'size': 0,
        'attach_status': 'detached',
        'volume_type_id': None}
    return vol


@mock.patch('cinder.db.service_get_by_host_and_topic',
            db_service_get_by_host_and_topic)
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

    def _get_resp(self, body):
        """Helper to execute an os-volume-manage API call."""
        req = webob.Request.blank('/v2/fake/os-volume-manage')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.environ['cinder.context'] = context.RequestContext('admin',
                                                               'fake',
                                                               True)
        req.body = jsonutils.dumps(body)
        res = req.get_response(app())
        return res

    @mock.patch('cinder.volume.api.API.manage_existing', wraps=api_manage)
    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_manage_volume_ok(self, mock_validate, mock_api_manage):
        """Test successful manage volume execution.

        Tests for correct operation when valid arguments are passed in the
        request body.  We ensure that cinder.volume.api.API.manage_existing got
        called with the correct arguments, and that we return the correct HTTP
        code to the caller.
        """
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref'}}
        res = self._get_resp(body)
        self.assertEqual(202, res.status_int, res)

        # Check that the manage API was called with the correct arguments.
        self.assertEqual(1, mock_api_manage.call_count)
        args = mock_api_manage.call_args[0]
        self.assertEqual(args[1], body['volume']['host'])
        self.assertEqual(args[2], body['volume']['ref'])
        self.assertTrue(mock_validate.called)

    def test_manage_volume_missing_host(self):
        """Test correct failure when host is not specified."""
        body = {'volume': {'ref': 'fake_ref'}}
        res = self._get_resp(body)
        self.assertEqual(400, res.status_int)

    def test_manage_volume_missing_ref(self):
        """Test correct failure when the ref is not specified."""
        body = {'volume': {'host': 'host_ok'}}
        res = self._get_resp(body)
        self.assertEqual(400, res.status_int)
        pass

    @mock.patch('cinder.volume.api.API.manage_existing', api_manage)
    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_manage_volume_volume_type_by_uuid(self, mock_validate):
        """Tests for correct operation when a volume type is specified by ID.

        We wrap cinder.volume.api.API.manage_existing so that managing is not
        actually attempted.
        """
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref',
                           'volume_type':
                           'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}}
        res = self._get_resp(body)
        self.assertEqual(202, res.status_int, res)
        self.assertTrue(mock_validate.called)
        pass

    @mock.patch('cinder.volume.api.API.manage_existing', api_manage)
    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_manage_volume_volume_type_by_name(self, mock_validate):
        """Tests for correct operation when a volume type is specified by name.

        We wrap cinder.volume.api.API.manage_existing so that managing is not
        actually attempted.
        """
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref',
                           'volume_type': 'good_fakevt'}}
        res = self._get_resp(body)
        self.assertEqual(202, res.status_int, res)
        self.assertTrue(mock_validate.called)
        pass

    def test_manage_volume_bad_volume_type_by_uuid(self):
        """Test failure on nonexistent volume type specified by ID."""
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref',
                           'volume_type':
                           'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'}}
        res = self._get_resp(body)
        self.assertEqual(404, res.status_int, res)
        pass

    def test_manage_volume_bad_volume_type_by_name(self):
        """Test failure on nonexistent volume type specified by name."""
        body = {'volume': {'host': 'host_ok',
                           'ref': 'fake_ref',
                           'volume_type': 'bad_fakevt'}}
        res = self._get_resp(body)
        self.assertEqual(404, res.status_int, res)
        pass
