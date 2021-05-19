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

from http import HTTPStatus
from unittest import mock

from oslo_serialization import jsonutils
import webob

from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import test


# This list of fake snapshot is used by our tests.
snapshot_id = fake.SNAPSHOT_ID
bad_snp_id = fake.WILL_NOT_BE_FOUND_ID


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router_v3.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v3'] = api
    return mapper


def api_snapshot_get(self, context, snp_id):
    """Replacement for cinder.volume.api.API.get_snapshot.

    We stub the cinder.volume.api.API.get_snapshot method to check for the
    existence of snapshot_id in our list of fake snapshots and raise an
    exception if the specified snapshot ID is not in our list.
    """
    snapshot = {'id': fake.SNAPSHOT_ID,
                'progress': '100%',
                'volume_id': fake.VOLUME_ID,
                'project_id': fake.PROJECT_ID,
                'status': fields.SnapshotStatus.AVAILABLE}
    if snp_id == snapshot_id:
        snapshot_objct = fake_snapshot.fake_snapshot_obj(context, **snapshot)
        return snapshot_objct
    else:
        raise exception.SnapshotNotFound(snapshot_id=snp_id)


@mock.patch('cinder.volume.api.API.get_snapshot', api_snapshot_get)
class SnapshotUnmanageTest(test.TestCase):
    """Test cases for cinder/api/contrib/snapshot_unmanage.py

    The API extension adds an action to snapshots, "os-unmanage", which will
    effectively issue a delete operation on the snapshot, but with a flag set
    that means that a different method will be invoked on the driver, so that
    the snapshot is not actually deleted in the storage backend.

    In this set of test cases, we are ensuring that the code correctly parses
    the request structure and raises the correct exceptions when things are not
    right, and calls down into cinder.volume.api.API.delete_snapshot with the
    correct arguments.
    """

    def _get_resp(self, snapshot_id):
        """Helper to build an os-unmanage req for the specified snapshot_id."""
        req = webob.Request.blank('/v3/%s/snapshots/%s/action' % (
            fake.PROJECT_ID, snapshot_id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.environ['cinder.context'] = context.RequestContext(fake.USER_ID,
                                                               fake.PROJECT_ID,
                                                               True)
        body = {'os-unmanage': ''}
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(app())
        return res

    @mock.patch('cinder.db.conditional_update', return_value=1)
    @mock.patch('cinder.db.snapshot_update')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.delete_snapshot')
    def test_unmanage_snapshot_ok(self, mock_rpcapi, mock_db_update,
                                  mock_conditional_update):
        """Return success for valid and unattached volume."""
        res = self._get_resp(snapshot_id)

        self.assertEqual(1, mock_rpcapi.call_count)
        self.assertEqual(3, len(mock_rpcapi.call_args[0]))
        self.assertEqual(0, len(mock_rpcapi.call_args[1]))

        self.assertEqual(HTTPStatus.ACCEPTED, res.status_int, res)

    def test_unmanage_snapshot_bad_snapshot_id(self):
        """Return 404 if the volume does not exist."""
        res = self._get_resp(bad_snp_id)
        self.assertEqual(HTTPStatus.NOT_FOUND, res.status_int, res)
