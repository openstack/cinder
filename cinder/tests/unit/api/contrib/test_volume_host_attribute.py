#   Copyright 2012 OpenStack Foundation
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

import uuid

from oslo_serialization import jsonutils
from oslo_utils import timeutils
import webob

from cinder import context
from cinder import db
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder import volume


def fake_db_volume_get(*args, **kwargs):
    return {
        'id': fake.VOLUME_ID,
        'host': 'host001',
        'status': 'available',
        'size': 5,
        'availability_zone': 'somewhere',
        'created_at': timeutils.utcnow(),
        'display_name': 'anothervolume',
        'display_description': 'Just another volume!',
        'volume_type_id': None,
        'snapshot_id': None,
        'project_id': fake.PROJECT_ID,
        'migration_status': None,
        '_name_id': fake.VOLUME2_ID,
        'attach_status': fields.VolumeAttachStatus.DETACHED,
    }


def fake_volume_api_get(*args, **kwargs):
    ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
    db_volume = fake_db_volume_get()
    return fake_volume.fake_volume_obj(ctx, **db_volume)


def fake_volume_get_all(*args, **kwargs):
    return objects.VolumeList(objects=[fake_volume_api_get()])


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v2'] = api
    return mapper


class VolumeHostAttributeTest(test.TestCase):

    def setUp(self):
        super(VolumeHostAttributeTest, self).setUp()
        self.mock_object(volume.api.API, 'get', fake_volume_api_get)
        self.mock_object(volume.api.API, 'get_all', fake_volume_get_all)
        self.mock_object(db, 'volume_get', fake_db_volume_get)

        self.UUID = uuid.uuid4()

    def test_get_volume_allowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req = webob.Request.blank('/v2/%s/volumes/%s' % (
            fake.PROJECT_ID, self.UUID))
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volume']
        self.assertEqual('host001', vol['os-vol-host-attr:host'])

    def test_get_volume_unallowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req = webob.Request.blank('/v2/%s/volumes/%s' % (
            fake.PROJECT_ID, self.UUID))
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volume']
        self.assertNotIn('os-vol-host-attr:host', vol)

    def test_list_detail_volumes_allowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req = webob.Request.blank('/v2/%s/volumes/detail' % fake.PROJECT_ID)
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volumes']
        self.assertEqual('host001', vol[0]['os-vol-host-attr:host'])

    def test_list_detail_volumes_unallowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req = webob.Request.blank('/v2/%s/volumes/detail' % fake.PROJECT_ID)
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volumes']
        self.assertNotIn('os-vol-host-attr:host', vol[0])

    def test_list_simple_volumes_no_host(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req = webob.Request.blank('/v2/%s/volumes' % fake.PROJECT_ID)
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volumes']
        self.assertNotIn('os-vol-host-attr:host', vol[0])
