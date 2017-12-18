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
from six.moves import http_client
import webob

from cinder import context
from cinder import db
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils


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
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

        api = fakes.router.APIRouter()
        self.app = fakes.urlmap.URLMap()
        self.app['/v2'] = api

    def _get_resp(self, volume_id):
        """Helper to build an os-unmanage req for the specified volume_id."""
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (self.ctxt.project_id, volume_id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.environ['cinder.context'] = self.ctxt
        body = {'os-unmanage': ''}
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        return res

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.delete_volume')
    def test_unmanage_volume_ok(self, mock_rpcapi):
        """Return success for valid and unattached volume."""
        vol = utils.create_volume(self.ctxt)
        res = self._get_resp(vol.id)
        self.assertEqual(http_client.ACCEPTED, res.status_int, res)

        mock_rpcapi.assert_called_once_with(self.ctxt, mock.ANY, True, False)
        vol = objects.volume.Volume.get_by_id(self.ctxt, vol.id)
        self.assertEqual('unmanaging', vol.status)
        db.volume_destroy(self.ctxt, vol.id)

    def test_unmanage_volume_bad_volume_id(self):
        """Return 404 if the volume does not exist."""
        res = self._get_resp(fake.WILL_NOT_BE_FOUND_ID)
        self.assertEqual(http_client.NOT_FOUND, res.status_int, res)

    def test_unmanage_volume_attached(self):
        """Return 400 if the volume exists but is attached."""
        vol = utils.create_volume(
            self.ctxt, status='in-use',
            attach_status=fields.VolumeAttachStatus.ATTACHED)
        res = self._get_resp(vol.id)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int, res)
        db.volume_destroy(self.ctxt, vol.id)

    def test_unmanage_volume_with_snapshots(self):
        """Return 400 if the volume exists but has snapshots."""
        vol = utils.create_volume(self.ctxt)
        snap = utils.create_snapshot(self.ctxt, vol.id)
        res = self._get_resp(vol.id)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int, res)
        db.volume_destroy(self.ctxt, vol.id)
        db.snapshot_destroy(self.ctxt, snap.id)

    def test_unmanage_encrypted_volume_denied(self):
        vol = utils.create_volume(
            self.ctxt,
            encryption_key_id='7a98391f-6619-46af-bd00-5862a3f7f1bd')
        res = self._get_resp(vol.id)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int, res)
        db.volume_destroy(self.ctxt, vol.id)
