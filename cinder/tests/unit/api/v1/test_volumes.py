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
import mock
from oslo_config import cfg
from oslo_utils import timeutils
import webob

from cinder.api import extensions
from cinder.api.v1 import volumes
from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import stubs
from cinder.tests.unit import fake_notifier
from cinder.tests.unit.image import fake as fake_image
from cinder.volume import api as volume_api


NS = '{http://docs.openstack.org/api/openstack-block-storage/1.0/content}'

TEST_SNAPSHOT_UUID = '00000000-0000-0000-0000-000000000001'

CONF = cfg.CONF


def stub_snapshot_get(self, context, snapshot_id):
    if snapshot_id != TEST_SNAPSHOT_UUID:
        raise exception.NotFound

    return {'id': snapshot_id,
            'volume_id': 12,
            'status': 'available',
            'volume_size': 100,
            'created_at': None,
            'display_name': 'Default name',
            'display_description': 'Default description', }


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
        self.stubs.Set(db, 'service_get_all_by_topic',
                       stubs.stub_service_get_all_by_topic)
        self.stubs.Set(volume_api.API, 'delete', stubs.stub_volume_delete)

    def test_volume_create(self):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)

        vol = {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        res_dict = self.controller.create(req, body)
        expected = {'volume': {'status': 'fakestatus',
                               'display_description': 'Volume Test Desc',
                               'availability_zone': 'zone1:host1',
                               'display_name': 'Volume Test Name',
                               'attachments': [],
                               'multiattach': 'false',
                               'bootable': 'false',
                               'volume_type': 'vol_type_name',
                               'snapshot_id': None,
                               'source_volid': None,
                               'metadata': {},
                               'id': '1',
                               'created_at': datetime.datetime(1900, 1, 1,
                                                               1, 1, 1),
                               'size': 100,
                               'encrypted': False}}
        self.assertEqual(expected, res_dict)

    def test_volume_create_with_type(self):
        vol_type = CONF.default_volume_type
        db.volume_type_create(context.get_admin_context(),
                              dict(name=vol_type, extra_specs={}))
        db_vol_type = db.volume_type_get_by_name(context.get_admin_context(),
                                                 vol_type)

        vol = {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1",
               "volume_type": "FakeTypeName"}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        # Raise 404 when type name isn't valid
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          req, body)
        # Use correct volume type name
        vol.update(dict(volume_type=CONF.default_volume_type))
        body.update(dict(volume=vol))
        res_dict = self.controller.create(req, body)
        self.assertIn('id', res_dict['volume'])
        self.assertEqual(1, len(res_dict))
        self.assertEqual(db_vol_type['name'],
                         res_dict['volume']['volume_type'])

        # Use correct volume type id
        vol.update(dict(volume_type=db_vol_type['id']))
        body.update(dict(volume=vol))
        res_dict = self.controller.create(req, body)
        self.assertIn('id', res_dict['volume'])
        self.assertEqual(1, len(res_dict))
        self.assertEqual(db_vol_type['name'],
                         res_dict['volume']['volume_type'])

    def test_volume_creation_fails_with_bad_size(self):
        vol = {"size": '',
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
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
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)

        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        test_id = "c905cedb-7281-47e4-8a62-f26bc5fc4c77"
        vol = {"size": '1',
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "nova",
               "imageRef": test_id}
        expected = {'volume': {'status': 'fakestatus',
                               'display_description': 'Volume Test Desc',
                               'availability_zone': 'nova',
                               'display_name': 'Volume Test Name',
                               'encrypted': False,
                               'attachments': [],
                               'multiattach': 'false',
                               'bootable': 'false',
                               'volume_type': 'vol_type_name',
                               'image_id': test_id,
                               'snapshot_id': None,
                               'source_volid': None,
                               'metadata': {},
                               'id': '1',
                               'created_at': datetime.datetime(1900, 1, 1,
                                                               1, 1, 1),
                               'size': '1'}}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        res_dict = self.controller.create(req, body)
        self.assertEqual(expected, res_dict)

    def test_volume_create_with_image_id_is_integer(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = {"size": '1',
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "cinder",
               "imageRef": 1234}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_with_image_id_not_uuid_format(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = {"size": '1',
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "cinder",
               "imageRef": '12345'}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_with_image_id_with_empty_string(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = {"size": 1,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "cinder",
               "imageRef": ''}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    @mock.patch.object(db, 'volume_admin_metadata_get',
                       return_value={'attached_mode': 'rw',
                                     'readonly': 'False'})
    @mock.patch.object(db, 'volume_get', side_effect=stubs.stub_volume_get_db)
    @mock.patch.object(volume_api.API, 'update',
                       side_effect=stubs.stub_volume_update)
    def test_volume_update(self, *args):
        updates = {
            "display_name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller.update(req, '1', body)
        expected = {'volume': {
            'status': 'fakestatus',
            'display_description': 'displaydesc',
            'availability_zone': 'fakeaz',
            'display_name': 'Updated Test Name',
            'encrypted': False,
            'attachments': [],
            'multiattach': 'false',
            'bootable': 'false',
            'volume_type': 'vol_type_name',
            'snapshot_id': None,
            'source_volid': None,
            'metadata': {'attached_mode': 'rw',
                         'readonly': 'False'},
            'id': '1',
            'created_at': datetime.datetime(1900, 1, 1, 1, 1, 1),
            'size': 1}}
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))

    @mock.patch.object(db, 'volume_admin_metadata_get',
                       return_value={"qos_max_iops": 2000,
                                     "readonly": "False",
                                     "attached_mode": "rw"})
    @mock.patch.object(db, 'volume_get', side_effect=stubs.stub_volume_get_db)
    @mock.patch.object(volume_api.API, 'update',
                       side_effect=stubs.stub_volume_update)
    def test_volume_update_metadata(self, *args):
        updates = {
            "metadata": {"qos_max_iops": 2000}
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller.update(req, '1', body)
        expected = {'volume': {
            'status': 'fakestatus',
            'display_description': 'displaydesc',
            'availability_zone': 'fakeaz',
            'display_name': 'displayname',
            'encrypted': False,
            'attachments': [],
            'multiattach': 'false',
            'bootable': 'false',
            'volume_type': 'vol_type_name',
            'snapshot_id': None,
            'source_volid': None,
            'metadata': {"qos_max_iops": 2000,
                         "readonly": "False",
                         "attached_mode": "rw"},
            'id': '1',
            'created_at': datetime.datetime(1900, 1, 1, 1, 1, 1),
            'size': 1
        }}
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))

    def test_volume_update_with_admin_metadata(self):
        def stubs_volume_admin_metadata_get(context, volume_id):
            return {'key': 'value',
                    'readonly': 'True'}
        self.stubs.Set(db, 'volume_admin_metadata_get',
                       stubs_volume_admin_metadata_get)
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
        values = {'volume_id': '1', }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], stubs.FAKE_UUID, None, '/')

        updates = {
            "display_name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertEqual(0, len(self.notifier.notifications))
        admin_ctx = context.RequestContext('admin', 'fakeproject', True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.update(req, '1', body)
        expected = {'volume': {
            'status': 'in-use',
            'display_description': 'displaydesc',
            'availability_zone': 'fakeaz',
            'display_name': 'Updated Test Name',
            'encrypted': False,
            'attachments': [{
                'attachment_id': attachment['id'],
                'id': '1',
                'volume_id': '1',
                'server_id': stubs.FAKE_UUID,
                'host_name': None,
                'device': '/'
            }],
            'multiattach': 'false',
            'bootable': 'false',
            'volume_type': None,
            'snapshot_id': None,
            'source_volid': None,
            'metadata': {'key': 'value',
                         'readonly': 'True'},
            'id': '1',
            'created_at': datetime.datetime(1900, 1, 1, 1, 1, 1),
            'size': 1}}
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))

    def test_update_empty_body(self):
        body = {}
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.update,
                          req, '1', body)

    def test_update_invalid_body(self):
        body = {'display_name': 'missing top level volume key'}
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.update,
                          req, '1', body)

    def test_update_not_found(self):
        self.stubs.Set(volume_api.API, "get", stubs.stub_volume_get_notfound)
        updates = {
            "display_name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update,
                          req, '1', body)

    def test_volume_list(self):
        def stubs_volume_admin_metadata_get(context, volume_id):
            return {'attached_mode': 'rw',
                    'readonly': 'False'}
        self.stubs.Set(db, 'volume_admin_metadata_get',
                       stubs_volume_admin_metadata_get)
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)
        self.stubs.Set(volume_api.API, 'get_all',
                       stubs.stub_volume_get_all_by_project)

        req = fakes.HTTPRequest.blank('/v1/volumes')
        res_dict = self.controller.index(req)
        expected = {'volumes': [{'status': 'fakestatus',
                                 'display_description': 'displaydesc',
                                 'availability_zone': 'fakeaz',
                                 'display_name': 'displayname',
                                 'encrypted': False,
                                 'attachments': [],
                                 'multiattach': 'false',
                                 'bootable': 'false',
                                 'volume_type': 'vol_type_name',
                                 'snapshot_id': None,
                                 'source_volid': None,
                                 'metadata': {'attached_mode': 'rw',
                                              'readonly': 'False'},
                                 'id': '1',
                                 'created_at': datetime.datetime(1900, 1, 1,
                                                                 1, 1, 1),
                                 'size': 1}]}
        self.assertEqual(expected, res_dict)
        # Finally test that we cached the returned volumes
        self.assertEqual(1, len(req.cached_resource()))

    def test_volume_list_with_admin_metadata(self):
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
        values = {'volume_id': '1', }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], stubs.FAKE_UUID, None, '/')

        req = fakes.HTTPRequest.blank('/v1/volumes')
        admin_ctx = context.RequestContext('admin', 'fakeproject', True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.index(req)
        expected = {'volumes': [{'status': 'in-use',
                                 'display_description': 'displaydesc',
                                 'availability_zone': 'fakeaz',
                                 'display_name': 'displayname',
                                 'encrypted': False,
                                 'attachments': [
                                     {'attachment_id': attachment['id'],
                                      'device': '/',
                                      'server_id': stubs.FAKE_UUID,
                                      'host_name': None,
                                      'id': '1',
                                      'volume_id': '1'}],
                                 'multiattach': 'false',
                                 'bootable': 'false',
                                 'volume_type': None,
                                 'snapshot_id': None,
                                 'source_volid': None,
                                 'metadata': {'key': 'value',
                                              'readonly': 'True'},
                                 'id': '1',
                                 'created_at': datetime.datetime(1900, 1, 1,
                                                                 1, 1, 1),
                                 'size': 1}]}
        self.assertEqual(expected, res_dict)

    def test_volume_list_detail(self):
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)
        self.stubs.Set(volume_api.API, 'get_all',
                       stubs.stub_volume_get_all_by_project)

        req = fakes.HTTPRequest.blank('/v1/volumes/detail')
        res_dict = self.controller.index(req)
        expected = {'volumes': [{'status': 'fakestatus',
                                 'display_description': 'displaydesc',
                                 'availability_zone': 'fakeaz',
                                 'display_name': 'displayname',
                                 'encrypted': False,
                                 'attachments': [],
                                 'multiattach': 'false',
                                 'bootable': 'false',
                                 'volume_type': 'vol_type_name',
                                 'snapshot_id': None,
                                 'source_volid': None,
                                 'metadata': {'attached_mode': 'rw',
                                              'readonly': 'False'},
                                 'id': '1',
                                 'created_at': datetime.datetime(1900, 1, 1,
                                                                 1, 1, 1),
                                 'size': 1}]}
        self.assertEqual(expected, res_dict)
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
        values = {'volume_id': '1', }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], stubs.FAKE_UUID, None, '/')

        req = fakes.HTTPRequest.blank('/v1/volumes/detail')
        admin_ctx = context.RequestContext('admin', 'fakeproject', True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.index(req)
        expected = {'volumes': [{'status': 'in-use',
                                 'display_description': 'displaydesc',
                                 'availability_zone': 'fakeaz',
                                 'display_name': 'displayname',
                                 'encrypted': False,
                                 'attachments': [
                                     {'attachment_id': attachment['id'],
                                      'device': '/',
                                      'server_id': stubs.FAKE_UUID,
                                      'host_name': None,
                                      'id': '1',
                                      'volume_id': '1'}],
                                 'multiattach': 'false',
                                 'bootable': 'false',
                                 'volume_type': None,
                                 'snapshot_id': None,
                                 'source_volid': None,
                                 'metadata': {'key': 'value',
                                              'readonly': 'True'},
                                 'id': '1',
                                 'created_at': datetime.datetime(1900, 1, 1,
                                                                 1, 1, 1),
                                 'size': 1}]}
        self.assertEqual(expected, res_dict)

    @mock.patch.object(db, 'volume_admin_metadata_get',
                       return_value={'attached_mode': 'rw',
                                     'readonly': 'False'})
    @mock.patch.object(db, 'volume_get', side_effect=stubs.stub_volume_get_db)
    def test_volume_show(self, *args):
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        res_dict = self.controller.show(req, '1')
        expected = {'volume': {'status': 'fakestatus',
                               'display_description': 'displaydesc',
                               'availability_zone': 'fakeaz',
                               'display_name': 'displayname',
                               'encrypted': False,
                               'attachments': [],
                               'multiattach': 'false',
                               'bootable': 'false',
                               'volume_type': 'vol_type_name',
                               'snapshot_id': None,
                               'source_volid': None,
                               'metadata': {'attached_mode': 'rw',
                                            'readonly': 'False'},
                               'id': '1',
                               'created_at': datetime.datetime(1900, 1, 1,
                                                               1, 1, 1),
                               'size': 1}}
        self.assertEqual(expected, res_dict)
        # Finally test that we cached the returned volume
        self.assertIsNotNone(req.cached_resource_by_id('1'))

    def test_volume_show_no_attachments(self):
        def stub_volume_get(self, context, volume_id, **kwargs):
            return stubs.stub_volume(volume_id, attach_status='detached')

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        res_dict = self.controller.show(req, '1')
        expected = {'volume': {'status': 'fakestatus',
                               'display_description': 'displaydesc',
                               'availability_zone': 'fakeaz',
                               'display_name': 'displayname',
                               'encrypted': False,
                               'attachments': [],
                               'multiattach': 'false',
                               'bootable': 'false',
                               'volume_type': 'vol_type_name',
                               'snapshot_id': None,
                               'source_volid': None,
                               'metadata': {'readonly': 'False'},
                               'id': '1',
                               'created_at': datetime.datetime(1900, 1, 1,
                                                               1, 1, 1),
                               'size': 1}}
        self.assertEqual(expected, res_dict)

    def test_volume_show_bootable(self):
        def stub_volume_get(self, context, volume_id, **kwargs):
            return (stubs.stub_volume(volume_id,
                    volume_glance_metadata=dict(foo='bar')))

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        res_dict = self.controller.show(req, '1')
        expected = {'volume': {'status': 'fakestatus',
                               'display_description': 'displaydesc',
                               'availability_zone': 'fakeaz',
                               'display_name': 'displayname',
                               'encrypted': False,
                               'attachments': [],
                               'multiattach': 'false',
                               'bootable': 'true',
                               'volume_type': 'vol_type_name',
                               'snapshot_id': None,
                               'source_volid': None,
                               'metadata': {'attached_mode': 'rw',
                                            'readonly': 'False'},
                               'id': '1',
                               'created_at': datetime.datetime(1900, 1, 1,
                                                               1, 1, 1),
                               'size': 1}}
        self.assertEqual(expected, res_dict)

    def test_volume_show_no_volume(self):
        self.stubs.Set(volume_api.API, "get", stubs.stub_volume_get_notfound)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          req,
                          1)
        # Finally test that we did not cache anything
        self.assertIsNone(req.cached_resource_by_id('1'))

    def test_volume_detail_limit_offset(self):
        def volume_detail_limit_offset(is_admin):
            def stub_volume_get_all_by_project(context, project_id, marker,
                                               limit, sort_keys=None,
                                               sort_dirs=None, filters=None,
                                               viewable_admin_meta=False,
                                               offset=None):
                return [
                    stubs.stub_volume(1, display_name='vol1'),
                    stubs.stub_volume(2, display_name='vol2'),
                ]

            self.stubs.Set(db, 'volume_get_all_by_project',
                           stub_volume_get_all_by_project)
            self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)

            req = fakes.HTTPRequest.blank('/v1/volumes/detail?limit=2\
                                          &offset=1',
                                          use_admin_context=is_admin)
            res_dict = self.controller.index(req)
            volumes = res_dict['volumes']
            self.assertEqual(1, len(volumes))
            self.assertEqual(2, volumes[0]['id'])

        # admin case
        volume_detail_limit_offset(is_admin=True)
        # non_admin case
        volume_detail_limit_offset(is_admin=False)

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
        values = {'volume_id': '1', }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], stubs.FAKE_UUID, None, '/')

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        admin_ctx = context.RequestContext('admin', 'fakeproject', True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.show(req, '1')
        expected = {'volume': {'status': 'in-use',
                               'display_description': 'displaydesc',
                               'availability_zone': 'fakeaz',
                               'display_name': 'displayname',
                               'encrypted': False,
                               'attachments': [
                                   {'attachment_id': attachment['id'],
                                    'device': '/',
                                    'server_id': stubs.FAKE_UUID,
                                    'host_name': None,
                                    'id': '1',
                                    'volume_id': '1'}],
                               'multiattach': 'false',
                               'bootable': 'false',
                               'volume_type': None,
                               'snapshot_id': None,
                               'source_volid': None,
                               'metadata': {'key': 'value',
                                            'readonly': 'True'},
                               'id': '1',
                               'created_at': datetime.datetime(1900, 1, 1,
                                                               1, 1, 1),
                               'size': 1}}
        self.assertEqual(expected, res_dict)

    def test_volume_show_with_encrypted_volume(self):
        def stub_volume_get(self, context, volume_id, **kwargs):
            return stubs.stub_volume(volume_id, encryption_key_id='fake_id')

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        res_dict = self.controller.show(req, 1)
        self.assertEqual(True, res_dict['volume']['encrypted'])

    def test_volume_show_with_unencrypted_volume(self):
        def stub_volume_get(self, context, volume_id, **kwargs):
            return stubs.stub_volume(volume_id, encryption_key_id=None)

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        res_dict = self.controller.show(req, 1)
        self.assertEqual(False, res_dict['volume']['encrypted'])

    def test_volume_delete(self):
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        resp = self.controller.delete(req, 1)
        self.assertEqual(202, resp.status_int)

    def test_volume_delete_no_volume(self):
        self.stubs.Set(volume_api.API, "get", stubs.stub_volume_get_notfound)

        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete,
                          req,
                          1)

    def test_admin_list_volumes_limited_to_project(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)

        req = fakes.HTTPRequest.blank('/v1/fake/volumes',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    def test_admin_list_volumes_all_tenants(self):
        req = fakes.HTTPRequest.blank('/v1/fake/volumes?all_tenants=1',
                                      use_admin_context=True)
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(3, len(res['volumes']))

    def test_all_tenants_non_admin_gets_all_tenants(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)

        req = fakes.HTTPRequest.blank('/v1/fake/volumes?all_tenants=1')
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    def test_non_admin_get_by_project(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)

        req = fakes.HTTPRequest.blank('/v1/fake/volumes')
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_string(self, get_all):
        req = mock.MagicMock()
        req.GET.copy.return_value = {'display_name': 'Volume-573108026'}
        context = mock.Mock()
        req.environ = {'cinder.context': context}
        self.controller._items(req, mock.Mock)
        get_all.assert_called_once_with(
            context, sort_dirs=['desc'], viewable_admin_meta=True,
            sort_keys=['created_at'], limit=None,
            filters={'display_name': 'Volume-573108026'}, marker=None)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_list(self, get_all):
        req = mock.MagicMock()
        req.GET.copy.return_value = {'id': "['1', '2', '3']"}
        context = mock.Mock()
        req.environ = {'cinder.context': context}
        self.controller._items(req, mock.Mock)
        get_all.assert_called_once_with(
            context, sort_dirs=['desc'], viewable_admin_meta=True,
            sort_keys=['created_at'], limit=None,
            filters={'id': ['1', '2', '3']}, marker=None)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_expression(self, get_all):
        req = mock.MagicMock()
        req.GET.copy.return_value = {'id': "d+"}
        context = mock.Mock()
        req.environ = {'cinder.context': context}
        self.controller._items(req, mock.Mock)
        get_all.assert_called_once_with(
            context, sort_dirs=['desc'], viewable_admin_meta=True,
            sort_keys=['created_at'], limit=None, filters={'id': 'd+'},
            marker=None)


class VolumeSerializerTest(test.TestCase):
    def _verify_volume_attachment(self, attach, tree):
        for attr in ('id', 'volume_id', 'server_id', 'device'):
            self.assertEqual(str(attach[attr]), tree.get(attr))

    def _verify_volume(self, vol, tree):
        self.assertEqual(NS + 'volume', tree.tag)

        for attr in ('id', 'status', 'size', 'availability_zone', 'created_at',
                     'display_name', 'display_description', 'volume_type',
                     'bootable', 'snapshot_id'):
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
            bootable='false',
            created_at=timeutils.utcnow(),
            attachments=[dict(id='vol_id',
                              volume_id='vol_id',
                              server_id='instance_uuid',
                              device='/foo')],
            display_name='vol_name',
            display_description='vol_desc',
            volume_type='vol_type',
            snapshot_id='snap_id',
            source_volid='source_volid',
            metadata=dict(foo='bar',
                          baz='quux', ), )
        text = serializer.serialize(dict(volume=raw_volume))

        tree = etree.fromstring(text)

        self._verify_volume(raw_volume, tree)

    def test_volume_index_detail_serializer(self):
        serializer = volumes.VolumesTemplate()
        raw_volumes = [dict(id='vol1_id',
                            status='vol1_status',
                            size=1024,
                            availability_zone='vol1_availability',
                            bootable='true',
                            created_at=timeutils.utcnow(),
                            attachments=[dict(id='vol1_id',
                                              volume_id='vol1_id',
                                              server_id='instance_uuid',
                                              device='/foo1')],
                            display_name='vol1_name',
                            display_description='vol1_desc',
                            volume_type='vol1_type',
                            snapshot_id='snap1_id',
                            source_volid=None,
                            metadata=dict(foo='vol1_foo',
                                          bar='vol1_bar', ), ),
                       dict(id='vol2_id',
                            status='vol2_status',
                            size=1024,
                            availability_zone='vol2_availability',
                            bootable='true',
                            created_at=timeutils.utcnow(),
                            attachments=[dict(id='vol2_id',
                                              volume_id='vol2_id',
                                              server_id='instance_uuid',
                                              device='/foo2')],
                            display_name='vol2_name',
                            display_description='vol2_desc',
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
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {"volume": {"size": "1", }, }
        self.assertEqual(expected, request['body'])

    def test_display_name(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
            },
        }
        self.assertEqual(expected, request['body'])

    def test_display_description(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
            },
        }
        self.assertEqual(expected, request['body'])

    def test_volume_type(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
            },
        }
        self.assertEqual(expected, request['body'])

    def test_availability_zone(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"
        availability_zone="us-east1"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
                "availability_zone": "us-east1",
            },
        }
        self.assertEqual(expected, request['body'])

    def test_metadata(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        display_name="Volume-xml"
        size="1">
        <metadata><meta key="Type">work</meta></metadata></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "display_name": "Volume-xml",
                "size": "1",
                "metadata": {
                    "Type": "work",
                },
            },
        }
        self.assertEqual(expected, request['body'])

    def test_full_volume(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/compute/api/v1.1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        volume_type="289da7f8-6440-407c-9fb4-7db01ec49164"
        availability_zone="us-east1">
        <metadata><meta key="Type">work</meta></metadata></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
                "availability_zone": "us-east1",
                "metadata": {
                    "Type": "work",
                },
            },
        }
        self.assertEqual(expected, request['body'])

    def test_imageref(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/volume/api/v1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        imageRef="4a90189d-d702-4c7c-87fc-6608c554d737"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "imageRef": "4a90189d-d702-4c7c-87fc-6608c554d737",
            },
        }
        self.assertEqual(expected, request['body'])

    def test_snapshot_id(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/volume/api/v1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        snapshot_id="4a90189d-d702-4c7c-87fc-6608c554d737"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "snapshot_id": "4a90189d-d702-4c7c-87fc-6608c554d737",
            },
        }
        self.assertEqual(expected, request['body'])

    def test_source_volid(self):
        self_request = """
<volume xmlns="http://docs.openstack.org/volume/api/v1"
        size="1"
        display_name="Volume-xml"
        display_description="description"
        source_volid="4a90189d-d702-4c7c-87fc-6608c554d737"></volume>"""
        request = self.deserializer.deserialize(self_request)
        expected = {
            "volume": {
                "size": "1",
                "display_name": "Volume-xml",
                "display_description": "description",
                "source_volid": "4a90189d-d702-4c7c-87fc-6608c554d737",
            },
        }
        self.assertEqual(expected, request['body'])


class VolumesUnprocessableEntityTestCase(test.TestCase):

    """Tests of places we throw 422 Unprocessable Entity from."""

    def setUp(self):
        super(VolumesUnprocessableEntityTestCase, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = volumes.VolumeController(self.ext_mgr)

    def _unprocessable_volume_create(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/volumes')
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, body)

    def test_create_no_body(self):
        self._unprocessable_volume_create(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._unprocessable_volume_create(body=body)

    def test_create_malformed_entity(self):
        body = {'volume': 'string'}
        self._unprocessable_volume_create(body=body)
