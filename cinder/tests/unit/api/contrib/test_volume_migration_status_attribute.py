# Copyright 2013 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_serialization import jsonutils
from oslo_utils import timeutils
import webob

from cinder import context
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder import volume


def fake_db_volume_get(*args, **kwargs):
    return {
        'id': fake.VOLUME_ID,
        'host': 'host001',
        'status': 'available',
        'size': 5,
        'availability_zone': 'somewhere',
        'created_at': timeutils.utcnow(),
        'attach_status': fields.VolumeAttachStatus.DETACHED,
        'display_name': 'anothervolume',
        'display_description': 'Just another volume!',
        'volume_type_id': None,
        'snapshot_id': None,
        'project_id': fake.PROJECT_ID,
        'migration_status': 'migrating',
        '_name_id': fake.VOLUME2_ID,
    }


def fake_volume_api_get(*args, **kwargs):
    ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
    db_volume = fake_db_volume_get()
    return fake_volume.fake_volume_obj(ctx, **db_volume)


def fake_volume_get_all(*args, **kwargs):
    return objects.VolumeList(objects=[fake_volume_api_get()])


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router_v3.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v3'] = api
    return mapper


class VolumeMigStatusAttributeTest(test.TestCase):

    def setUp(self):
        super(VolumeMigStatusAttributeTest, self).setUp()
        self.mock_object(volume.api.API, 'get', fake_volume_api_get)
        self.mock_object(volume.api.API, 'get_all', fake_volume_get_all)
        self.UUID = fake.UUID1

    def test_get_volume_allowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req = webob.Request.blank('/v3/%s/volumes/%s' % (
            fake.PROJECT_ID, self.UUID))
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volume']
        self.assertEqual('migrating',
                         vol['os-vol-mig-status-attr:migstat'])
        self.assertEqual(fake.VOLUME2_ID,
                         vol['os-vol-mig-status-attr:name_id'])

    def test_get_volume_unallowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req = webob.Request.blank('/v3/%s/volumes/%s' % (
            fake.PROJECT_ID, self.UUID))
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volume']
        self.assertNotIn('os-vol-mig-status-attr:migstat', vol)
        self.assertNotIn('os-vol-mig-status-attr:name_id', vol)

    def test_list_detail_volumes_allowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req = webob.Request.blank('/v3/%s/volumes/detail' % fake.PROJECT_ID)
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volumes']
        self.assertEqual('migrating',
                         vol[0]['os-vol-mig-status-attr:migstat'])
        self.assertEqual(fake.VOLUME2_ID,
                         vol[0]['os-vol-mig-status-attr:name_id'])

    def test_list_detail_volumes_unallowed(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req = webob.Request.blank('/v3/%s/volumes/detail' % fake.PROJECT_ID)
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volumes']
        self.assertNotIn('os-vol-mig-status-attr:migstat', vol[0])
        self.assertNotIn('os-vol-mig-status-attr:name_id', vol[0])

    def test_list_simple_volumes_no_migration_status(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req = webob.Request.blank('/v3/%s/volumes' % fake.PROJECT_ID)
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = jsonutils.loads(res.body)['volumes']
        self.assertNotIn('os-vol-mig-status-attr:migstat', vol[0])
        self.assertNotIn('os-vol-mig-status-attr:name_id', vol[0])
