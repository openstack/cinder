# Copyright 2013 Josh Durgin
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import datetime

from lxml import etree
from oslo.config import cfg
import webob

from cinder.api import extensions
from cinder.api.v2 import volumes
from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.tests.api import fakes
from cinder.tests.api.v2 import stubs
from cinder.tests import fake_notifier
from cinder.tests.image import fake as fake_image
from cinder import utils
from cinder.volume import api as volume_api

CONF = cfg.CONF

NS = '{http://docs.openstack.org/api/openstack-volume/2.0/content}'

TEST_SNAPSHOT_UUID = '00000000-0000-0000-0000-000000000001'


def stub_snapshot_get(self, context, snapshot_id):
    if snapshot_id != TEST_SNAPSHOT_UUID:
        raise exception.NotFound

    return {
        'id': snapshot_id,
        'volume_id': 12,
        'status': 'available',
        'volume_size': 100,
        'created_at': None,
        'name': 'Default name',
        'description': 'Default description',
    }


class VolumeApiTest(test.TestCase):
    def setUp(self):
        super(VolumeApiTest, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        fake_image.stub_out_image_service(self.stubs)
        self.controller = volumes.VolumeController(self.ext_mgr)

        self.flags(host='fake',
                   notification_driver=[fake_notifier.__name__])

        self.stubs.Set(db, 'volume_get_all', stubs.stub_volume_get_all)
        self.stubs.Set(volume_api.API, 'delete', stubs.stub_volume_delete)
        self.stubs.Set(db, 'service_get_all_by_topic',
                       stubs.stub_service_get_all_by_topic)
        self.maxDiff = None

    def tearDown(self):
        super(VolumeApiTest, self).tearDown()
        fake_notifier.reset()

    def test_volume_create(self):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)

        vol = {
            "size": 100,
            "name": "Volume Test Name",
            "description": "Volume Test Desc",
            "availability_zone": "zone1:host1"
        }
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        res_dict = self.controller.create(req, body)
        ex = {'volume': {'attachments':
                         [{'device': '/',
                           'host_name': None,
                           'id': '1',
                           'server_id': 'fakeuuid',
                           'volume_id': '1'}],
                         'availability_zone': 'zone1:host1',
                         'bootable': 'false',
                         'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                         'description': 'Volume Test Desc',
                         'id': '1',
                         'links':
                         [{'href': 'http://localhost/v2/fake/volumes/1',
                           'rel': 'self'},
                          {'href': 'http://localhost/fake/volumes/1',
                           'rel': 'bookmark'}],
                         'metadata': {'attached_mode': 'rw',
                                      'readonly': 'False'},
                         'name': 'Volume Test Name',
                         'size': 100,
                         'snapshot_id': None,
                         'source_volid': None,
                         'status': 'fakestatus',
                         'user_id': 'fakeuser',
                         'volume_type': 'vol_type_name',
                         'encrypted': False}}
        self.assertEqual(res_dict, ex)

    def test_volume_create_with_type(self):
        vol_type = db.volume_type_create(
            context.get_admin_context(),
            dict(name=CONF.default_volume_type, extra_specs={})
        )

        db_vol_type = db.volume_type_get(context.get_admin_context(),
                                         vol_type.id)

        vol = {
            "size": 100,
            "name": "Volume Test Name",
            "description": "Volume Test Desc",
            "availability_zone": "zone1:host1",
            "volume_type": "FakeTypeName",
        }
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        # Raise 404 when type name isn't valid
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          req, body)

        # Use correct volume type name
        vol.update(dict(volume_type=CONF.default_volume_type))
        body.update(dict(volume=vol))
        res_dict = self.controller.create(req, body)
        volume_id = res_dict['volume']['id']
        self.assertEqual(len(res_dict), 1)

        # Use correct volume type id
        vol.update(dict(volume_type=db_vol_type['id']))
        body.update(dict(volume=vol))
        res_dict = self.controller.create(req, body)
        volume_id = res_dict['volume']['id']
        self.assertEqual(len(res_dict), 1)

        self.stubs.Set(volume_api.API, 'get_all',
                       lambda *args, **kwargs:
                       [stubs.stub_volume(volume_id,
                                          volume_type={'name': vol_type})])
        req = fakes.HTTPRequest.blank('/v2/volumes/detail')
        res_dict = self.controller.detail(req)

    def test_volume_creation_fails_with_bad_size(self):
        vol = {"size": '',
               "name": "Volume Test Name",
               "description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(exception.InvalidInput,
                          self.controller.create,
                          req,
                          body)

    def test_volume_creation_fails_with_bad_availability_zone(self):
        vol = {"size": '1',
               "name": "Volume Test Name",
               "description": "Volume Test Desc",
               "availability_zone": "zonen:hostn"}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(exception.InvalidInput,
                          self.controller.create,
                          req, body)

    def test_volume_create_with_image_id(self):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)

        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = {"size": '1',
               "name": "Volume Test Name",
               "description": "Volume Test Desc",
               "availability_zone": "nova",
               "imageRef": 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'}
        ex = {'volume': {'attachments': [{'device': '/',
                         'host_name': None,
                         'id': '1',
                         'server_id': 'fakeuuid',
                         'volume_id': '1'}],
                         'availability_zone': 'nova',
                         'bootable': 'false',
                         'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                         'description': 'Volume Test Desc',
                         'encrypted': False,
                         'id': '1',
                         'links':
                         [{'href': 'http://localhost/v2/fake/volumes/1',
                           'rel': 'self'},
                          {'href': 'http://localhost/fake/volumes/1',
                           'rel': 'bookmark'}],
                         'metadata': {'attached_mode': 'rw',
                                      'readonly': 'False'},
                         'name': 'Volume Test Name',
                         'size': '1',
                         'snapshot_id': None,
                         'source_volid': None,
                         'status': 'fakestatus',
                         'user_id': 'fakeuser',
                         'volume_type': 'vol_type_name'}}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        res_dict = self.controller.create(req, body)
        self.assertEqual(res_dict, ex)

    def test_volume_create_with_image_id_is_integer(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = {
            "size": '1',
            "name": "Volume Test Name",
            "description": "Volume Test Desc",
            "availability_zone": "cinder",
            "imageRef": 1234,
        }
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_with_image_id_not_uuid_format(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = {
            "size": '1',
            "name": "Volume Test Name",
            "description": "Volume Test Desc",
            "availability_zone": "cinder",
            "imageRef": '12345'
        }
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_update(self):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "update", stubs.stub_volume_update)

        updates = {
            "name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 0)
        res_dict = self.controller.update(req, '1', body)
        expected = {
            'volume': {
                'status': 'fakestatus',
                'description': 'displaydesc',
                'encrypted': False,
                'availability_zone': 'fakeaz',
                'bootable': 'false',
                'name': 'Updated Test Name',
                'attachments': [
                    {
                        'id': '1',
                        'volume_id': '1',
                        'server_id': 'fakeuuid',
                        'host_name': None,
                        'device': '/',
                    }
                ],
                'user_id': 'fakeuser',
                'volume_type': 'vol_type_name',
                'snapshot_id': None,
                'source_volid': None,
                'metadata': {'attached_mode': 'rw', 'readonly': 'False'},
                'id': '1',
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'size': 1,
                'links': [
                    {
                        'href': 'http://localhost/v2/fake/volumes/1',
                        'rel': 'self'
                    },
                    {
                        'href': 'http://localhost/fake/volumes/1',
                        'rel': 'bookmark'
                    }
                ],
            }
        }
        self.assertEqual(res_dict, expected)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)

    def test_volume_update_metadata(self):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "update", stubs.stub_volume_update)

        updates = {
            "metadata": {"qos_max_iops": 2000}
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 0)
        res_dict = self.controller.update(req, '1', body)
        expected = {'volume': {
            'status': 'fakestatus',
            'description': 'displaydesc',
            'encrypted': False,
            'availability_zone': 'fakeaz',
            'bootable': 'false',
            'name': 'displayname',
            'attachments': [{
                'id': '1',
                'volume_id': '1',
                'server_id': 'fakeuuid',
                'host_name': None,
                'device': '/',
            }],
            'user_id': 'fakeuser',
            'volume_type': 'vol_type_name',
            'snapshot_id': None,
            'source_volid': None,
            'metadata': {"qos_max_iops": 2000,
                         "readonly": "False",
                         "attached_mode": "rw"},
            'id': '1',
            'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
            'size': 1,
            'links': [
                {
                    'href': 'http://localhost/v2/fake/volumes/1',
                    'rel': 'self'
                },
                {
                    'href': 'http://localhost/fake/volumes/1',
                    'rel': 'bookmark'
                }
            ],
        }}
        self.assertEqual(res_dict, expected)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)

    def test_volume_update_with_admin_metadata(self):
        self.stubs.Set(volume_api.API, "update", stubs.stub_volume_update)

        volume = stubs.stub_volume("1")
        del volume['name']
        del volume['volume_type']
        del volume['volume_type_id']
        volume['metadata'] = {'key': 'value'}
        db.volume_create(context.get_admin_context(), volume)
        db.volume_admin_metadata_update(context.get_admin_context(), "1",
                                        {"readonly": "True",
                                         "invisible_key": "invisible_value"},
                                        False)

        updates = {
            "display_name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 0)
        admin_ctx = context.RequestContext('admin', 'fake', True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.update(req, '1', body)
        expected = {'volume': {
            'status': 'fakestatus',
            'description': 'displaydesc',
            'encrypted': False,
            'availability_zone': 'fakeaz',
            'bootable': 'false',
            'name': 'displayname',
            'attachments': [{
                'id': '1',
                'volume_id': '1',
                'server_id': 'fakeuuid',
                'host_name': None,
                'device': '/',
            }],
            'user_id': 'fakeuser',
            'volume_type': None,
            'snapshot_id': None,
            'source_volid': None,
            'metadata': {'key': 'value',
                         'readonly': 'True'},
            'id': '1',
            'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
            'size': 1,
            'links': [
                {
                    'href': 'http://localhost/v2/fake/volumes/1',
                    'rel': 'self'
                },
                {
                    'href': 'http://localhost/fake/volumes/1',
                    'rel': 'bookmark'
                }
            ],
        }}
        self.assertEqual(res_dict, expected)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)

    def test_update_empty_body(self):
        body = {}
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update,
                          req, '1', body)

    def test_update_invalid_body(self):
        body = {
            'name': 'missing top level volume key'
        }
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update,
                          req, '1', body)

    def test_update_not_found(self):
        self.stubs.Set(volume_api.API, "get", stubs.stub_volume_get_notfound)
        updates = {
            "name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update,
                          req, '1', body)

    def test_volume_list_summary(self):
        self.stubs.Set(volume_api.API, 'get_all',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes')
        res_dict = self.controller.index(req)
        expected = {
            'volumes': [
                {
                    'name': 'displayname',
                    'id': '1',
                    'links': [
                        {
                            'href': 'http://localhost/v2/fake/volumes/1',
                            'rel': 'self'
                        },
                        {
                            'href': 'http://localhost/fake/volumes/1',
                            'rel': 'bookmark'
                        }
                    ],
                }
            ]
        }
        self.assertEqual(res_dict, expected)
        # Finally test that we cached the returned volumes
        self.assertEqual(1, len(req.cached_resource()))

    def test_volume_list_detail(self):
        self.stubs.Set(volume_api.API, 'get_all',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail')
        res_dict = self.controller.detail(req)
        expected = {
            'volumes': [
                {
                    'status': 'fakestatus',
                    'description': 'displaydesc',
                    'encrypted': False,
                    'availability_zone': 'fakeaz',
                    'bootable': 'false',
                    'name': 'displayname',
                    'attachments': [
                        {
                            'device': '/',
                            'server_id': 'fakeuuid',
                            'host_name': None,
                            'id': '1',
                            'volume_id': '1'
                        }
                    ],
                    'user_id': 'fakeuser',
                    'volume_type': 'vol_type_name',
                    'snapshot_id': None,
                    'source_volid': None,
                    'metadata': {'attached_mode': 'rw', 'readonly': 'False'},
                    'id': '1',
                    'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                    'size': 1,
                    'links': [
                        {
                            'href': 'http://localhost/v2/fake/volumes/1',
                            'rel': 'self'
                        },
                        {
                            'href': 'http://localhost/fake/volumes/1',
                            'rel': 'bookmark'
                        }
                    ],
                }
            ]
        }
        self.assertEqual(res_dict, expected)
        # Finally test that we cached the returned volumes
        self.assertEqual(1, len(req.cached_resource()))

    def test_volume_list_detail_with_admin_metadata(self):
        volume = stubs.stub_volume("1")
        del volume['name']
        del volume['volume_type']
        del volume['volume_type_id']
        volume['metadata'] = {'key': 'value'}
        db.volume_create(context.get_admin_context(), volume)
        db.volume_admin_metadata_update(context.get_admin_context(), "1",
                                        {"readonly": "True",
                                         "invisible_key": "invisible_value"},
                                        False)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail')
        admin_ctx = context.RequestContext('admin', 'fakeproject', True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.detail(req)
        expected = {
            'volumes': [
                {
                    'status': 'fakestatus',
                    'description': 'displaydesc',
                    'encrypted': False,
                    'availability_zone': 'fakeaz',
                    'bootable': 'false',
                    'name': 'displayname',
                    'attachments': [
                        {
                            'device': '/',
                            'server_id': 'fakeuuid',
                            'host_name': None,
                            'id': '1',
                            'volume_id': '1'
                        }
                    ],
                    'user_id': 'fakeuser',
                    'volume_type': None,
                    'snapshot_id': None,
                    'source_volid': None,
                    'metadata': {'key': 'value', 'readonly': 'True'},
                    'id': '1',
                    'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                    'size': 1,
                    'links': [
                        {
                            'href': 'http://localhost/v2/fakeproject'
                                    '/volumes/1',
                            'rel': 'self'
                        },
                        {
                            'href': 'http://localhost/fakeproject/volumes/1',
                            'rel': 'bookmark'
                        }
                    ],
                }
            ]
        }
        self.assertEqual(res_dict, expected)

    def test_volume_index_with_marker(self):
        def stub_volume_get_all_by_project(context, project_id, marker, limit,
                                           sort_key, sort_dir, filters=None):
            return [
                stubs.stub_volume(1, display_name='vol1'),
                stubs.stub_volume(2, display_name='vol2'),
            ]
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes?marker=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(len(volumes), 2)
        self.assertEqual(volumes[0]['id'], 1)
        self.assertEqual(volumes[1]['id'], 2)

    def test_volume_index_limit(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes?limit=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(len(volumes), 1)

    def test_volume_index_limit_negative(self):
        req = fakes.HTTPRequest.blank('/v2/volumes?limit=-1')
        self.assertRaises(exception.Invalid,
                          self.controller.index,
                          req)

    def test_volume_index_limit_non_int(self):
        req = fakes.HTTPRequest.blank('/v2/volumes?limit=a')
        self.assertRaises(exception.Invalid,
                          self.controller.index,
                          req)

    def test_volume_index_limit_marker(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes?marker=1&limit=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0]['id'], '1')

    def test_volume_index_limit_offset(self):
        def stub_volume_get_all_by_project(context, project_id, marker, limit,
                                           sort_key, sort_dir, filters=None):
            return [
                stubs.stub_volume(1, display_name='vol1'),
                stubs.stub_volume(2, display_name='vol2'),
            ]
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes?limit=2&offset=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0]['id'], 2)

        req = fakes.HTTPRequest.blank('/v2/volumes?limit=-1&offset=1')
        self.assertRaises(exception.InvalidInput,
                          self.controller.index,
                          req)

        req = fakes.HTTPRequest.blank('/v2/volumes?limit=a&offset=1')
        self.assertRaises(exception.InvalidInput,
                          self.controller.index,
                          req)

    def test_volume_detail_with_marker(self):
        def stub_volume_get_all_by_project(context, project_id, marker, limit,
                                           sort_key, sort_dir, filters=None):
            return [
                stubs.stub_volume(1, display_name='vol1'),
                stubs.stub_volume(2, display_name='vol2'),
            ]
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?marker=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(len(volumes), 2)
        self.assertEqual(volumes[0]['id'], 1)
        self.assertEqual(volumes[1]['id'], 2)

    def test_volume_detail_limit(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(len(volumes), 1)

    def test_volume_detail_limit_negative(self):
        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=-1')
        self.assertRaises(exception.Invalid,
                          self.controller.index,
                          req)

    def test_volume_detail_limit_non_int(self):
        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=a')
        self.assertRaises(exception.Invalid,
                          self.controller.index,
                          req)

    def test_volume_detail_limit_marker(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?marker=1&limit=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0]['id'], '1')

    def test_volume_detail_limit_offset(self):
        def stub_volume_get_all_by_project(context, project_id, marker, limit,
                                           sort_key, sort_dir, filters=None):
            return [
                stubs.stub_volume(1, display_name='vol1'),
                stubs.stub_volume(2, display_name='vol2'),
            ]
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=2&offset=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0]['id'], 2)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=2&offset=1',
                                      use_admin_context=True)
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0]['id'], 2)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=-1&offset=1')
        self.assertRaises(exception.InvalidInput,
                          self.controller.index,
                          req)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=a&offset=1')
        self.assertRaises(exception.InvalidInput,
                          self.controller.index,
                          req)

    def test_volume_with_limit_zero(self):
        def stub_volume_get_all(context, marker, limit,
                                sort_key, sort_dir):
            return []
        self.stubs.Set(db, 'volume_get_all', stub_volume_get_all)
        req = fakes.HTTPRequest.blank('/v2/volumes?limit=0')
        res_dict = self.controller.index(req)
        expected = {'volumes': []}
        self.assertEqual(res_dict, expected)

    def test_volume_default_limit(self):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        # Number of volumes equals the max, include next link
        def stub_volume_get_all(context, marker, limit,
                                sort_key, sort_dir,
                                filters=None):
            vols = [stubs.stub_volume(i)
                    for i in xrange(CONF.osapi_max_limit)]
            if limit == None or limit >= len(vols):
                return vols
            return vols[:limit]
        self.stubs.Set(db, 'volume_get_all', stub_volume_get_all)
        for key in ['volumes', 'volumes/detail']:
            req = fakes.HTTPRequest.blank('/v2/%s?all_tenants=1' % key,
                                          use_admin_context=True)
            res_dict = self.controller.index(req)
            self.assertEqual(len(res_dict['volumes']), CONF.osapi_max_limit)
            volumes_links = res_dict['volumes_links']
            self.assertEqual(volumes_links[0]['rel'], 'next')

        # Number of volumes less then max, do not include
        def stub_volume_get_all2(context, marker, limit,
                                 sort_key, sort_dir,
                                 filters=None):
            vols = [stubs.stub_volume(i)
                    for i in xrange(100)]
            if limit == None or limit >= len(vols):
                return vols
            return vols[:limit]
        self.stubs.Set(db, 'volume_get_all', stub_volume_get_all2)
        for key in ['volumes', 'volumes/detail']:
            req = fakes.HTTPRequest.blank('/v2/%s?all_tenants=1' % key,
                                          use_admin_context=True)
            res_dict = self.controller.index(req)
            self.assertEqual(len(res_dict['volumes']), 100)
            self.assertFalse('volumes_links' in res_dict)

        # Number of volumes more then the max, include next link
        def stub_volume_get_all3(context, marker, limit,
                                 sort_key, sort_dir,
                                 filters=None):
            vols = [stubs.stub_volume(i)
                    for i in xrange(CONF.osapi_max_limit + 100)]
            if limit == None or limit >= len(vols):
                return vols
            return vols[:limit]
        self.stubs.Set(db, 'volume_get_all', stub_volume_get_all3)
        for key in ['volumes', 'volumes/detail']:
            req = fakes.HTTPRequest.blank('/v2/%s?all_tenants=1' % key,
                                          use_admin_context=True)
            res_dict = self.controller.index(req)
            self.assertEqual(len(res_dict['volumes']), CONF.osapi_max_limit)
            volumes_links = res_dict['volumes_links']
            self.assertEqual(volumes_links[0]['rel'], 'next')
        # Pass a limit that is greater then the max and the total number of
        # volumes, ensure only the maximum is returned and that the next
        # link is present
        for key in ['volumes', 'volumes/detail']:
            req = fakes.HTTPRequest.blank('/v2/%s?all_tenants=1&limit=%d'
                                          % (key, CONF.osapi_max_limit * 2),
                                          use_admin_context=True)
            res_dict = self.controller.index(req)
            self.assertEqual(len(res_dict['volumes']), CONF.osapi_max_limit)
            volumes_links = res_dict['volumes_links']
            self.assertEqual(volumes_links[0]['rel'], 'next')

    def test_volume_list_default_filters(self):
        """Tests that the default filters from volume.api.API.get_all are set.

        1. 'no_migration_status'=True for non-admins and get_all_by_project is
        invoked.
        2. 'no_migration_status' is not included for admins.
        3. When 'all_tenants' is not specified, then it is removed and
        get_all_by_project is invoked for admins.
        3. When 'all_tenants' is specified, then it is removed and get_all
        is invoked for admins.
        """
        # Non-admin, project function should be called with no_migration_status
        def stub_volume_get_all_by_project(context, project_id, marker, limit,
                                           sort_key, sort_dir, filters=None):
            self.assertEqual(filters['no_migration_targets'], True)
            self.assertFalse('all_tenants' in filters)
            return [stubs.stub_volume(1, display_name='vol1')]

        def stub_volume_get_all(context, marker, limit,
                                sort_key, sort_dir, filters=None):
            return []
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stub_volume_get_all_by_project)
        self.stubs.Set(db, 'volume_get_all', stub_volume_get_all)

        # all_tenants does not matter for non-admin
        for params in ['', '?all_tenants=1']:
            req = fakes.HTTPRequest.blank('/v2/volumes%s' % params)
            resp = self.controller.index(req)
            self.assertEqual(len(resp['volumes']), 1)
            self.assertEqual(resp['volumes'][0]['name'], 'vol1')

        # Admin, all_tenants is not set, project function should be called
        # without no_migration_status
        def stub_volume_get_all_by_project2(context, project_id, marker, limit,
                                            sort_key, sort_dir, filters=None):
            self.assertFalse('no_migration_targets' in filters)
            return [stubs.stub_volume(1, display_name='vol2')]

        def stub_volume_get_all2(context, marker, limit,
                                 sort_key, sort_dir, filters=None):
            return []
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stub_volume_get_all_by_project2)
        self.stubs.Set(db, 'volume_get_all', stub_volume_get_all2)

        req = fakes.HTTPRequest.blank('/v2/volumes', use_admin_context=True)
        resp = self.controller.index(req)
        self.assertEqual(len(resp['volumes']), 1)
        self.assertEqual(resp['volumes'][0]['name'], 'vol2')

        # Admin, all_tenants is set, get_all function should be called
        # without no_migration_status
        def stub_volume_get_all_by_project3(context, project_id, marker, limit,
                                            sort_key, sort_dir, filters=None):
            return []

        def stub_volume_get_all3(context, marker, limit,
                                 sort_key, sort_dir, filters=None):
            self.assertFalse('no_migration_targets' in filters)
            self.assertFalse('all_tenants' in filters)
            return [stubs.stub_volume(1, display_name='vol3')]
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stub_volume_get_all_by_project3)
        self.stubs.Set(db, 'volume_get_all', stub_volume_get_all3)

        req = fakes.HTTPRequest.blank('/v2/volumes?all_tenants=1',
                                      use_admin_context=True)
        resp = self.controller.index(req)
        self.assertEqual(len(resp['volumes']), 1)
        self.assertEqual(resp['volumes'][0]['name'], 'vol3')

    def test_volume_show(self):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        res_dict = self.controller.show(req, '1')
        expected = {
            'volume': {
                'status': 'fakestatus',
                'description': 'displaydesc',
                'encrypted': False,
                'availability_zone': 'fakeaz',
                'bootable': 'false',
                'name': 'displayname',
                'attachments': [
                    {
                        'device': '/',
                        'server_id': 'fakeuuid',
                        'host_name': None,
                        'id': '1',
                        'volume_id': '1'
                    }
                ],
                'user_id': 'fakeuser',
                'volume_type': 'vol_type_name',
                'snapshot_id': None,
                'source_volid': None,
                'metadata': {'attached_mode': 'rw', 'readonly': 'False'},
                'id': '1',
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'size': 1,
                'links': [
                    {
                        'href': 'http://localhost/v2/fake/volumes/1',
                        'rel': 'self'
                    },
                    {
                        'href': 'http://localhost/fake/volumes/1',
                        'rel': 'bookmark'
                    }
                ],
            }
        }
        self.assertEqual(res_dict, expected)
        # Finally test that we cached the returned volume
        self.assertIsNotNone(req.cached_resource_by_id('1'))

    def test_volume_show_no_attachments(self):
        def stub_volume_get(self, context, volume_id):
            return stubs.stub_volume(volume_id, attach_status='detached')

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        res_dict = self.controller.show(req, '1')
        expected = {
            'volume': {
                'status': 'fakestatus',
                'description': 'displaydesc',
                'encrypted': False,
                'availability_zone': 'fakeaz',
                'bootable': 'false',
                'name': 'displayname',
                'attachments': [],
                'user_id': 'fakeuser',
                'volume_type': 'vol_type_name',
                'snapshot_id': None,
                'source_volid': None,
                'metadata': {'readonly': 'False'},
                'id': '1',
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'size': 1,
                'links': [
                    {
                        'href': 'http://localhost/v2/fake/volumes/1',
                        'rel': 'self'
                    },
                    {
                        'href': 'http://localhost/fake/volumes/1',
                        'rel': 'bookmark'
                    }
                ],
            }
        }

        self.assertEqual(res_dict, expected)

    def test_volume_show_no_volume(self):
        self.stubs.Set(volume_api.API, "get", stubs.stub_volume_get_notfound)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, 1)
        # Finally test that nothing was cached
        self.assertIsNone(req.cached_resource_by_id('1'))

    def test_volume_show_with_admin_metadata(self):
        volume = stubs.stub_volume("1")
        del volume['name']
        del volume['volume_type']
        del volume['volume_type_id']
        volume['metadata'] = {'key': 'value'}
        db.volume_create(context.get_admin_context(), volume)
        db.volume_admin_metadata_update(context.get_admin_context(), "1",
                                        {"readonly": "True",
                                         "invisible_key": "invisible_value"},
                                        False)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        admin_ctx = context.RequestContext('admin', 'fakeproject', True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.show(req, '1')
        expected = {
            'volume': {
                'status': 'fakestatus',
                'description': 'displaydesc',
                'encrypted': False,
                'availability_zone': 'fakeaz',
                'bootable': 'false',
                'name': 'displayname',
                'attachments': [
                    {
                        'device': '/',
                        'server_id': 'fakeuuid',
                        'host_name': None,
                        'id': '1',
                        'volume_id': '1'
                    }
                ],
                'user_id': 'fakeuser',
                'volume_type': None,
                'snapshot_id': None,
                'source_volid': None,
                'metadata': {'key': 'value',
                             'readonly': 'True'},
                'id': '1',
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'size': 1,
                'links': [
                    {
                        'href': 'http://localhost/v2/fakeproject/volumes/1',
                        'rel': 'self'
                    },
                    {
                        'href': 'http://localhost/fakeproject/volumes/1',
                        'rel': 'bookmark'
                    }
                ],
            }
        }
        self.assertEqual(res_dict, expected)

    def test_volume_show_with_encrypted_volume(self):
        def stub_volume_get(self, context, volume_id):
            return stubs.stub_volume(volume_id, encryption_key_id='fake_id')

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        res_dict = self.controller.show(req, 1)
        self.assertEqual(res_dict['volume']['encrypted'], True)

    def test_volume_show_with_unencrypted_volume(self):
        def stub_volume_get(self, context, volume_id):
            return stubs.stub_volume(volume_id, encryption_key_id=None)

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        res_dict = self.controller.show(req, 1)
        self.assertEqual(res_dict['volume']['encrypted'], False)

    def test_volume_delete(self):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        resp = self.controller.delete(req, 1)
        self.assertEqual(resp.status_int, 202)

    def test_volume_delete_attached(self):
        def stub_volume_attached(self, context, volume, force=False):
            raise exception.VolumeAttached(volume_id=volume['id'])
        self.stubs.Set(volume_api.API, "delete", stub_volume_attached)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete,
                          req, 1)

    def test_volume_delete_no_volume(self):
        self.stubs.Set(volume_api.API, "get", stubs.stub_volume_get_notfound)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, 1)

    def test_admin_list_volumes_limited_to_project(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)

        req = fakes.HTTPRequest.blank('/v2/fake/volumes',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    def test_admin_list_volumes_all_tenants(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)

        req = fakes.HTTPRequest.blank('/v2/fake/volumes?all_tenants=1',
                                      use_admin_context=True)
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(3, len(res['volumes']))

    def test_all_tenants_non_admin_gets_all_tenants(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/fake/volumes?all_tenants=1')
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    def test_non_admin_get_by_project(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/fake/volumes')
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    def _create_volume_bad_request(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/volumes')
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_no_body(self):
        self._create_volume_bad_request(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._create_volume_bad_request(body=body)

    def test_create_malformed_entity(self):
        body = {'volume': 'string'}
        self._create_volume_bad_request(body=body)

    def test_add_visible_admin_metadata_visible_key_only(self):
        admin_metadata = [{"key": "invisible_key", "value": "invisible_value"},
                          {"key": "readonly", "value": "visible"},
                          {"key": "attached_mode", "value": "visible"}]
        metadata = [{"key": "key", "value": "value"}]
        volume = dict(volume_admin_metadata=admin_metadata,
                      volume_metadata=metadata)
        admin_ctx = context.get_admin_context()
        utils.add_visible_admin_metadata(admin_ctx, volume,
                                         self.controller.volume_api)

        self.assertEqual(volume['volume_metadata'],
                         [{"key": "key", "value": "value"},
                          {"key": "readonly", "value": "visible"},
                          {"key": "attached_mode", "value": "visible"}])

        admin_metadata = {"invisible_key": "invisible_value",
                          "readonly": "visible",
                          "attached_mode": "visible"}
        metadata = {"key": "value"}
        volume = dict(admin_metadata=admin_metadata,
                      metadata=metadata)
        admin_ctx = context.get_admin_context()
        utils.add_visible_admin_metadata(admin_ctx, volume,
                                         self.controller.volume_api)
        self.assertEqual(volume['metadata'],
                         {'key': 'value',
                          'attached_mode': 'visible',
                          'readonly': 'visible'})


class VolumeSerializerTest(test.TestCase):
    def _verify_volume_attachment(self, attach, tree):
        for attr in ('id', 'volume_id', 'server_id', 'device'):
            self.assertEqual(str(attach[attr]), tree.get(attr))

    def _verify_volume(self, vol, tree):
        self.assertEqual(tree.tag, NS + 'volume')

        for attr in ('id', 'status', 'size', 'availability_zone', 'created_at',
                     'name', 'description', 'volume_type', 'bootable',
                     'snapshot_id', 'source_volid'):
            self.assertEqual(str(vol[attr]), tree.get(attr))

        for child in tree:
            self.assertIn(child.tag, (NS + 'attachments', NS + 'metadata'))
            if child.tag == 'attachments':
                self.assertEqual(1, len(child))
                self.assertEqual('attachment', child[0].tag)
                self._verify_volume_attachment(vol['attachments'][0], child[0])
            elif child.tag == 'metadata':
                not_seen = set(vol['metadata'].keys())
                for gr_child in child:
                    self.assertIn(gr_child.get("key"), not_seen)
                    self.assertEqual(str(vol['metadata'][gr_child.get("key")]),
                                     gr_child.text)
                    not_seen.remove(gr_child.get('key'))
                self.assertEqual(0, len(not_seen))

    def test_volume_show_create_serializer(self):
        serializer = volumes.VolumeTemplate()
        raw_volume = dict(
            id='vol_id',
            status='vol_status',
            size=1024,
            availability_zone='vol_availability',
            bootable=False,
            created_at=datetime.datetime.now(),
            attachments=[
                dict(
                    id='vol_id',
                    volume_id='vol_id',
                    server_id='instance_uuid',
                    device='/foo'
                )
            ],
            name='vol_name',
            description='vol_desc',
            volume_type='vol_type',
            snapshot_id='snap_id',
            source_volid='source_volid',
            metadata=dict(
                foo='bar',
                baz='quux',
            ),
        )
        text = serializer.serialize(dict(volume=raw_volume))

        tree = etree.fromstring(text)

        self._verify_volume(raw_volume, tree)

    def test_volume_index_detail_serializer(self):
        serializer = volumes.VolumesTemplate()
        raw_volumes = [
            dict(
                id='vol1_id',
                status='vol1_status',
                size=1024,
                availability_zone='vol1_availability',
                bootable=True,
                created_at=datetime.datetime.now(),
                attachments=[
                    dict(
                        id='vol1_id',
                        volume_id='vol1_id',
                        server_id='instance_uuid',
                        device='/foo1'
                    )
                ],
                name='vol1_name',
                description='vol1_desc',
                volume_type='vol1_type',
                snapshot_id='snap1_id',
                source_volid=None,
                metadata=dict(foo='vol1_foo',
                              bar='vol1_bar', ), ),
            dict(
                id='vol2_id',
                status='vol2_status',
                size=1024,
                availability_zone='vol2_availability',
                bootable=False,
                created_at=datetime.datetime.now(),
                attachments=[dict(id='vol2_id',
                                  volume_id='vol2_id',
                                  server_id='instance_uuid',
                                  device='/foo2')],
                name='vol2_name',
                description='vol2_desc',
                volume_type='vol2_type',
                snapshot_id='snap2_id',
                source_volid=None,
                metadata=dict(foo='vol2_foo',
                              bar='vol2_bar', ), )]
        text = serializer.serialize(dict(volumes=raw_volumes))

        tree = etree.fromstring(text)

        self.assertEqual(NS + 'volumes', tree.tag)
        self.assertEqual(len(raw_volumes), len(tree))
        for idx, child in enumerate(tree):
            self._verify_volume(raw_volumes[idx], child)


class TestVolumeCreateRequestXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestVolumeCreateRequestXMLDeserializer, self).setUp()
        self.deserializer = volumes.CreateDeserializer()

    def test_minimal_volume(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/api/openstack-volume/2.0/content"
        size="1"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
            },
        }
        self.assertEqual(request['body'], expected)

    def test_name(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/api/openstack-volume/2.0/content"
        size="1"
        name="Volume-xml"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "name": "Volume-xml",
            },
        }
        self.assertEqual(request['body'], expected)

    def test_description(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/api/openstack-volume/2.0/content"
        size="1"
        name="Volume-xml"
        description="description"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "name": "Volume-xml",
                "description": "description",
            },
        }
        self.assertEqual(request['body'], expected)

    def test_volume_type(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/api/openstack-volume/2.0/content"
        size="1"
        name="Volume-xml"
        description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "name": "Volume-xml",
                "size": "1",
                "name": "Volume-xml",
                "description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
            },
        }
        self.assertEqual(request['body'], expected)

    def test_availability_zone(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/api/openstack-volume/2.0/content"
        size="1"
        name="Volume-xml"
        description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"
        availability_zone="us-east1"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "name": "Volume-xml",
                "description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
                "availability_zone": "us-east1",
            },
        }
        self.assertEqual(request['body'], expected)

    def test_metadata(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/api/openstack-volume/2.0/content"
        name="Volume-xml"
        size="1">
        <metadata><meta key="Type">work</meta></metadata></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "name": "Volume-xml",
                "size": "1",
                "metadata": {
                    "Type": "work",
                },
            },
        }
        self.assertEqual(request['body'], expected)

    def test_full_volume(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/api/openstack-volume/2.0/content"
        size="1"
        name="Volume-xml"
        description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"
        availability_zone="us-east1">
        <metadata><meta key="Type">work</meta></metadata></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "name": "Volume-xml",
                "description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
                "availability_zone": "us-east1",
                "metadata": {
                    "Type": "work",
                },
            },
        }
        self.assertEqual(request['body'], expected)

    def test_imageref(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/api/openstack-volume/2.0/content"
        size="1"
        name="Volume-xml"
        description="description"
        imageRef="4a90189d-d702-4c7c-87fc-6608c554d737"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "name": "Volume-xml",
                "description": "description",
                "imageRef": "4a90189d-d702-4c7c-87fc-6608c554d737",
            },
        }
        self.assertEqual(expected, request['body'])

    def test_snapshot_id(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/api/openstack-volume/2.0/content"
        size="1"
        name="Volume-xml"
        description="description"
        snapshot_id="4a90189d-d702-4c7c-87fc-6608c554d737"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "name": "Volume-xml",
                "description": "description",
                "snapshot_id": "4a90189d-d702-4c7c-87fc-6608c554d737",
            },
        }
        self.assertEqual(expected, request['body'])

    def test_source_volid(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/api/openstack-volume/2.0/content"
        size="1"
        name="Volume-xml"
        description="description"
        source_volid="4a90189d-d702-4c7c-87fc-6608c554d737"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "name": "Volume-xml",
                "description": "description",
                "source_volid": "4a90189d-d702-4c7c-87fc-6608c554d737",
            },
        }
        self.assertEqual(expected, request['body'])
