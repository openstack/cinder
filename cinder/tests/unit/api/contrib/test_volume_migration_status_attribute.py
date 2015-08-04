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

import json
import uuid

from lxml import etree
from oslo_utils import timeutils
import webob

from cinder import context
from cinder import test
from cinder.tests.unit.api import fakes
from cinder import volume


def fake_volume_get(*args, **kwargs):
    return {
        'id': 'fake',
        'host': 'host001',
        'status': 'available',
        'size': 5,
        'availability_zone': 'somewhere',
        'created_at': timeutils.utcnow(),
        'attach_status': None,
        'display_name': 'anothervolume',
        'display_description': 'Just another volume!',
        'volume_type_id': None,
        'snapshot_id': None,
        'project_id': 'fake',
        'migration_status': 'migrating',
        '_name_id': 'fake2',
    }


def fake_volume_get_all(*args, **kwargs):
    return [fake_volume_get()]


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v2'] = api
    return mapper


class VolumeMigStatusAttributeTest(test.TestCase):

    def setUp(self):
        super(VolumeMigStatusAttributeTest, self).setUp()
        self.stubs.Set(volume.API, 'get', fake_volume_get)
        self.stubs.Set(volume.API, 'get_all', fake_volume_get_all)
        self.UUID = uuid.uuid4()

    def test_get_volume_allowed(self):
        ctx = context.RequestContext('admin', 'fake', True)
        req = webob.Request.blank('/v2/fake/volumes/%s' % self.UUID)
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = json.loads(res.body)['volume']
        self.assertEqual('migrating', vol['os-vol-mig-status-attr:migstat'])
        self.assertEqual('fake2', vol['os-vol-mig-status-attr:name_id'])

    def test_get_volume_unallowed(self):
        ctx = context.RequestContext('non-admin', 'fake', False)
        req = webob.Request.blank('/v2/fake/volumes/%s' % self.UUID)
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = json.loads(res.body)['volume']
        self.assertNotIn('os-vol-mig-status-attr:migstat', vol)
        self.assertNotIn('os-vol-mig-status-attr:name_id', vol)

    def test_list_detail_volumes_allowed(self):
        ctx = context.RequestContext('admin', 'fake', True)
        req = webob.Request.blank('/v2/fake/volumes/detail')
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = json.loads(res.body)['volumes']
        self.assertEqual('migrating', vol[0]['os-vol-mig-status-attr:migstat'])
        self.assertEqual('fake2', vol[0]['os-vol-mig-status-attr:name_id'])

    def test_list_detail_volumes_unallowed(self):
        ctx = context.RequestContext('non-admin', 'fake', False)
        req = webob.Request.blank('/v2/fake/volumes/detail')
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = json.loads(res.body)['volumes']
        self.assertNotIn('os-vol-mig-status-attr:migstat', vol[0])
        self.assertNotIn('os-vol-mig-status-attr:name_id', vol[0])

    def test_list_simple_volumes_no_migration_status(self):
        ctx = context.RequestContext('admin', 'fake', True)
        req = webob.Request.blank('/v2/fake/volumes')
        req.method = 'GET'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = json.loads(res.body)['volumes']
        self.assertNotIn('os-vol-mig-status-attr:migstat', vol[0])
        self.assertNotIn('os-vol-mig-status-attr:name_id', vol[0])

    def test_get_volume_xml(self):
        ctx = context.RequestContext('admin', 'fake', True)
        req = webob.Request.blank('/v2/fake/volumes/%s' % self.UUID)
        req.method = 'GET'
        req.accept = 'application/xml'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = etree.XML(res.body)
        mig_key = ('{http://docs.openstack.org/volume/ext/'
                   'volume_mig_status_attribute/api/v1}migstat')
        self.assertEqual('migrating', vol.get(mig_key))
        mig_key = ('{http://docs.openstack.org/volume/ext/'
                   'volume_mig_status_attribute/api/v1}name_id')
        self.assertEqual('fake2', vol.get(mig_key))

    def test_list_volumes_detail_xml(self):
        ctx = context.RequestContext('admin', 'fake', True)
        req = webob.Request.blank('/v2/fake/volumes/detail')
        req.method = 'GET'
        req.accept = 'application/xml'
        req.environ['cinder.context'] = ctx
        res = req.get_response(app())
        vol = list(etree.XML(res.body))[0]
        mig_key = ('{http://docs.openstack.org/volume/ext/'
                   'volume_mig_status_attribute/api/v1}migstat')
        self.assertEqual('migrating', vol.get(mig_key))
        mig_key = ('{http://docs.openstack.org/volume/ext/'
                   'volume_mig_status_attribute/api/v1}name_id')
        self.assertEqual('fake2', vol.get(mig_key))
