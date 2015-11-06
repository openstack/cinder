#   Copyright (c) 2015 Huawei Technologies Co., Ltd.
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
from cinder.tests.unit import fake_service


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v2'] = api
    return mapper


def volume_get(self, context, volume_id, viewable_admin_meta=False):
    if volume_id == 'fake_volume_id':
        return {'id': 'fake_volume_id', 'name': 'fake_volume_name',
                'host': 'fake_host'}
    raise exception.VolumeNotFound(volume_id=volume_id)


@mock.patch('cinder.volume.api.API.get', volume_get)
class SnapshotManageTest(test.TestCase):
    """Test cases for cinder/api/contrib/snapshot_manage.py

    The API extension adds a POST /os-snapshot-manage API that is passed a
    cinder volume id, and a driver-specific reference parameter.
    If everything is passed correctly,
    then the cinder.volume.api.API.manage_existing_snapshot method
    is invoked to manage an existing storage object on the host.

    In this set of test cases, we are ensuring that the code correctly parses
    the request structure and raises the correct exceptions when things are not
    right, and calls down into cinder.volume.api.API.manage_existing_snapshot
    with the correct arguments.
    """

    def _get_resp(self, body):
        """Helper to execute an os-snapshot-manage API call."""
        req = webob.Request.blank('/v2/fake/os-snapshot-manage')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.environ['cinder.context'] = context.RequestContext('admin',
                                                               'fake',
                                                               True)
        req.body = jsonutils.dumps(body)
        res = req.get_response(app())
        return res

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.manage_existing_snapshot')
    @mock.patch('cinder.volume.api.API.create_snapshot_in_db')
    @mock.patch('cinder.db.service_get_by_host_and_topic')
    def test_manage_snapshot_ok(self, mock_db,
                                mock_create_snapshot, mock_rpcapi):
        """Test successful manage volume execution.

        Tests for correct operation when valid arguments are passed in the
        request body. We ensure that cinder.volume.api.API.manage_existing got
        called with the correct arguments, and that we return the correct HTTP
        code to the caller.
        """
        ctxt = context.RequestContext('admin', 'fake', True)
        mock_db.return_value = fake_service.fake_service_obj(ctxt)

        body = {'snapshot': {'volume_id': 'fake_volume_id', 'ref': 'fake_ref'}}
        res = self._get_resp(body)
        self.assertEqual(202, res.status_int, res)

        # Check the db.service_get_by_host_and_topic was called with correct
        # arguments.
        self.assertEqual(1, mock_db.call_count)
        args = mock_db.call_args[0]
        self.assertEqual('fake_host', args[1])

        # Check the create_snapshot_in_db was called with correct arguments.
        self.assertEqual(1, mock_create_snapshot.call_count)
        args = mock_create_snapshot.call_args[0]
        self.assertEqual('fake_volume_id', args[1].get('id'))

        # Check the volume_rpcapi.manage_existing_snapshot was called with
        # correct arguments.
        self.assertEqual(1, mock_rpcapi.call_count)
        args = mock_rpcapi.call_args[0]
        self.assertEqual('fake_ref', args[2])

    def test_manage_snapshot_missing_volume_id(self):
        """Test correct failure when volume_id is not specified."""
        body = {'snapshot': {'ref': 'fake_ref'}}
        res = self._get_resp(body)
        self.assertEqual(400, res.status_int)

    def test_manage_snapshot_missing_ref(self):
        """Test correct failure when the ref is not specified."""
        body = {'snapshot': {'volume_id': 'fake_volume_id'}}
        res = self._get_resp(body)
        self.assertEqual(400, res.status_int)

    def test_manage_snapshot_error_body(self):
        """Test correct failure when body is invaild."""
        body = {'error_snapshot': {'volume_id': 'fake_volume_id'}}
        res = self._get_resp(body)
        self.assertEqual(400, res.status_int)

    def test_manage_snapshot_error_volume_id(self):
        """Test correct failure when volume can't be found."""
        body = {'snapshot': {'volume_id': 'error_volume_id',
                             'ref': 'fake_ref'}}
        res = self._get_resp(body)
        self.assertEqual(404, res.status_int)
