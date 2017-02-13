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
import webob

from cinder import context
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder import volume


PROJECT_ID = '88fd1da4-f464-4a87-9ce5-26f2f40743b9'


def fake_volume_get(*args, **kwargs):
    ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
    vol = {
        'id': fake.VOLUME_ID,
        'project_id': PROJECT_ID,
    }
    return fake_volume.fake_volume_obj(ctx, **vol)


def fake_volume_get_all(*args, **kwargs):
    return objects.VolumeList(objects=[fake_volume_get()])


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v2'] = api
    return mapper


class VolumeTenantAttributeTest(test.TestCase):

    def setUp(self):
        super(VolumeTenantAttributeTest, self).setUp()
        self.mock_object(volume.api.API, 'get', fake_volume_get)
        self.mock_object(volume.api.API, 'get_all', fake_volume_get_all)
        self.UUID = uuid.uuid4()

    def test_get_volume_allowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req = webob.Request.blank('/v2/%s/volumes/%s' % (
            fake.PROJECT_ID, self.UUID))
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volume']
        self.assertEqual(PROJECT_ID, vol['os-vol-tenant-attr:tenant_id'])

    def test_get_volume_unallowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req = webob.Request.blank('/v2/%s/volumes/%s' % (
            fake.PROJECT_ID, self.UUID))
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volume']
        self.assertNotIn('os-vol-tenant-attr:tenant_id', vol)

    def test_list_detail_volumes_allowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req = webob.Request.blank('/v2/%s/volumes/detail' % fake.PROJECT_ID)
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volumes']
        self.assertEqual(PROJECT_ID, vol[0]['os-vol-tenant-attr:tenant_id'])

    def test_list_detail_volumes_unallowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req = webob.Request.blank('/v2/%s/volumes/detail' % fake.PROJECT_ID)
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volumes']
        self.assertNotIn('os-vol-tenant-attr:tenant_id', vol[0])

    def test_list_simple_volumes_no_tenant_id(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req = webob.Request.blank('/v2/%s/volumes' % fake.PROJECT_ID)
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volumes']
        self.assertNotIn('os-vol-tenant-attr:tenant_id', vol[0])
