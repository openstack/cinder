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
from cinder.tests.api import fakes


# This list of fake volumes is used by our tests.  Each is configured in a
# slightly different way, and includes only the properties that are required
# for these particular tests to function correctly.
snapshot_vol_id = 'ffffffff-0000-ffff-0000-fffffffffffd'
detached_vol_id = 'ffffffff-0000-ffff-0000-fffffffffffe'
attached_vol_id = 'ffffffff-0000-ffff-0000-ffffffffffff'
bad_vol_id = 'ffffffff-0000-ffff-0000-fffffffffff0'

vols = {snapshot_vol_id: {'id': snapshot_vol_id,
                          'status': 'available',
                          'attach_status': 'detached',
                          'host': 'fake_host',
                          'project_id': 'fake_project',
                          'migration_status': None,
                          'consistencygroup_id': None,
                          'encryption_key_id': None},
        detached_vol_id: {'id': detached_vol_id,
                          'status': 'available',
                          'attach_status': 'detached',
                          'host': 'fake_host',
                          'project_id': 'fake_project',
                          'migration_status': None,
                          'consistencygroup_id': None,
                          'encryption_key_id': None},
        attached_vol_id: {'id': attached_vol_id,
                          'status': 'available',
                          'attach_status': 'attached',
                          'host': 'fake_host',
                          'project_id': 'fake_project',
                          'migration_status': None,
                          'consistencygroup_id': None,
                          'encryption_key_id': None}
        }


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v2'] = api
    return mapper


def api_get(self, context, volume_id):
    """Replacement for cinder.volume.api.API.get.

    We stub the cinder.volume.api.API.get method to check for the existence
    of volume_id in our list of fake volumes and raise an exception if the
    specified volume ID is not in our list.
    """
    vol = vols.get(volume_id, None)

    if not vol:
        raise exception.NotFound

    return vol


def db_snapshot_get_all_for_volume(context, volume_id):
    """Replacement for cinder.db.snapshot_get_all_for_volume.

    We stub the cinder.db.snapshot_get_all_for_volume method because when we
    go to unmanage a volume, the code checks for snapshots and won't unmanage
    volumes with snapshots.  For these tests, only the snapshot_vol_id reports
    any snapshots.  The delete code just checks for array length, doesn't
    inspect the contents.
    """
    if volume_id == snapshot_vol_id:
        return ['fake_snapshot']
    return []


@mock.patch('cinder.volume.api.API.get', api_get)
@mock.patch('cinder.db.snapshot_get_all_for_volume',
            db_snapshot_get_all_for_volume)
class VolumeUnmanageTest(test.TestCase):
    """Test cases for cinder/api/contrib/volume_unmanage.py

    The API extension adds an action to volumes, "os-unmanage", which will
    effectively issue a delete operation on the volume, but with a flag set
    that means that a different method will be invoked on the driver, so that
    the volume is not actually deleted in the storage backend.

    In this set of test cases, we are ensuring that the code correctly parses
    the request structure and raises the correct exceptions when things are not
    right, and calls down into cinder.volume.api.API.delete with the correct
    arguments.
    """

    def setUp(self):
        super(VolumeUnmanageTest, self).setUp()

    def _get_resp(self, volume_id):
        """Helper to build an os-unmanage req for the specified volume_id."""
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.environ['cinder.context'] = context.RequestContext('admin',
                                                               'fake',
                                                               True)
        body = {'os-unmanage': ''}
        req.body = jsonutils.dumps(body)
        res = req.get_response(app())
        return res

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.delete_volume')
    def test_unmanage_volume_ok(self, mock_rpcapi, mock_db):
        """Return success for valid and unattached volume."""
        res = self._get_resp(detached_vol_id)

        # volume_update is (context, id, new_data)
        self.assertEqual(mock_db.call_count, 1)
        self.assertEqual(len(mock_db.call_args[0]), 3, mock_db.call_args)
        self.assertEqual(mock_db.call_args[0][1], detached_vol_id)

        # delete_volume is (context, status, unmanageOnly)
        self.assertEqual(mock_rpcapi.call_count, 1)
        self.assertEqual(len(mock_rpcapi.call_args[0]), 3)
        self.assertEqual(mock_rpcapi.call_args[0][2], True)

        self.assertEqual(res.status_int, 202, res)

    def test_unmanage_volume_bad_volume_id(self):
        """Return 404 if the volume does not exist."""
        res = self._get_resp(bad_vol_id)
        self.assertEqual(res.status_int, 404, res)

    def test_unmanage_volume_attached_(self):
        """Return 400 if the volume exists but is attached."""
        res = self._get_resp(attached_vol_id)
        self.assertEqual(res.status_int, 400, res)

    def test_unmanage_volume_with_snapshots(self):
        """Return 400 if the volume exists but has snapshots."""
        res = self._get_resp(snapshot_vol_id)
        self.assertEqual(res.status_int, 400, res)
