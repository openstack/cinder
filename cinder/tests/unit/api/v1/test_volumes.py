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
import iso8601

import ddt
import mock
from oslo_config import cfg
import webob

from cinder.api import extensions
from cinder.api.v1 import volumes
from cinder import context
from cinder import db
from cinder import exception as exc
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v1 import stubs
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit.image import fake as fake_image
from cinder.volume import api as volume_api


NS = '{http://docs.openstack.org/api/openstack-block-storage/1.0/content}'

CONF = cfg.CONF


@ddt.ddt
class VolumeApiTest(test.TestCase):
    def setUp(self):
        super(VolumeApiTest, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        fake_image.mock_image_service(self)
        self.controller = volumes.VolumeController(self.ext_mgr)

        self.stubs.Set(db, 'volume_get_all', stubs.stub_volume_get_all)
        self.patch(
            'cinder.db.service_get_all', autospec=True,
            return_value=stubs.stub_service_get_all(None))
        self.stubs.Set(volume_api.API, 'delete', stubs.stub_volume_delete)

    def test_volume_create(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_api_create)
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)
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
                               'id': fake.VOLUME_ID,
                               'created_at': datetime.datetime(
                                   1900, 1, 1, 1, 1, 1,
                                   tzinfo=iso8601.iso8601.Utc()),
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
        self.assertRaises(exc.VolumeTypeNotFoundByName,
                          self.controller.create, req, body)
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
        self.assertRaises(exc.InvalidInput,
                          self.controller.create,
                          req,
                          body)

    def test_volume_creation_fails_with_bad_availability_zone(self):
        vol = {"size": '1',
               "name": "Volume Test Name",
               "description": "Volume Test Desc",
               "availability_zone": "zonen:hostn"}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        self.assertRaises(exc.InvalidInput,
                          self.controller.create,
                          req, body)

    def test_volume_create_with_image_id(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_api_create)
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)

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
                               'id': fake.VOLUME_ID,
                               'created_at': datetime.datetime(
                                   1900, 1, 1, 1, 1, 1,
                                   tzinfo=iso8601.iso8601.Utc()),
                               'size': 1}}
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
    @mock.patch.object(db.sqlalchemy.api, '_volume_type_get_full',
                       side_effect=stubs.stub_volume_type_get)
    @mock.patch.object(volume_api.API, 'get',
                       side_effect=stubs.stub_volume_api_get, autospec=True)
    @mock.patch.object(volume_api.API, 'update',
                       side_effect=stubs.stub_volume_update, autospec=True)
    def test_volume_update(self, *args):
        updates = {
            "display_name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller.update(req, fake.VOLUME_ID, body)
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
            'id': fake.VOLUME_ID,
            'created_at': datetime.datetime(1900, 1, 1, 1, 1, 1,
                                            tzinfo=iso8601.iso8601.Utc()),
            'size': 1}}
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))

    @mock.patch.object(db, 'volume_admin_metadata_get',
                       return_value={"qos_max_iops": 2000,
                                     "readonly": "False",
                                     "attached_mode": "rw"})
    @mock.patch.object(db.sqlalchemy.api, '_volume_type_get_full',
                       side_effect=stubs.stub_volume_type_get)
    @mock.patch.object(volume_api.API, 'get',
                       side_effect=stubs.stub_volume_api_get, autospec=True)
    @mock.patch.object(volume_api.API, 'update',
                       side_effect=stubs.stub_volume_update, autospec=True)
    def test_volume_update_metadata(self, *args):
        updates = {
            "metadata": {"qos_max_iops": 2000}
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller.update(req, fake.VOLUME_ID, body)
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
            'metadata': {"qos_max_iops": '2000',
                         "readonly": "False",
                         "attached_mode": "rw"},
            'id': fake.VOLUME_ID,
            'created_at': datetime.datetime(1900, 1, 1, 1, 1, 1,
                                            tzinfo=iso8601.iso8601.Utc()),
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

        volume = stubs.stub_volume(fake.VOLUME_ID)
        del volume['name']
        del volume['volume_type']
        del volume['volume_type_id']
        volume['metadata'] = {'key': 'value'}
        db.volume_create(context.get_admin_context(), volume)
        db.volume_admin_metadata_update(context.get_admin_context(),
                                        fake.VOLUME_ID,
                                        {"readonly": "True",
                                         "invisible_key": "invisible_value"},
                                        False)
        values = {'volume_id': fake.VOLUME_ID, }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], fake.INSTANCE_ID,
                           None, '/')

        updates = {
            "display_name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        self.assertEqual(0, len(self.notifier.notifications))
        admin_ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.update(req, fake.VOLUME_ID, body)
        expected = {'volume': {
            'status': 'in-use',
            'display_description': 'displaydesc',
            'availability_zone': 'fakeaz',
            'display_name': 'Updated Test Name',
            'encrypted': False,
            'attachments': [{
                'attachment_id': attachment['id'],
                'id': fake.VOLUME_ID,
                'volume_id': fake.VOLUME_ID,
                'server_id': fake.INSTANCE_ID,
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
            'id': fake.VOLUME_ID,
            'created_at': datetime.datetime(1900, 1, 1, 1, 1, 1,
                                            tzinfo=iso8601.iso8601.Utc()),
            'size': 1}}
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))

    def test_update_empty_body(self):
        body = {}
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.update,
                          req, fake.VOLUME_ID, body)

    def test_update_invalid_body(self):
        body = {'display_name': 'missing top level volume key'}
        req = fakes.HTTPRequest.blank('/v1/volumes/1')
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.update,
                          req, fake.VOLUME_ID, body)

    def test_update_not_found(self):

        updates = {
            "display_name": "Updated Test Name",
        }
        body = {"volume": updates}

        req = fakes.HTTPRequest.blank(
            '/v1/volumes/%s' % fake.WILL_NOT_BE_FOUND_ID)
        self.assertRaises(exc.VolumeNotFound,
                          self.controller.update,
                          req, fake.WILL_NOT_BE_FOUND_ID, body)

    def test_volume_list(self):
        def stubs_volume_admin_metadata_get(context, volume_id):
            return {'attached_mode': 'rw',
                    'readonly': 'False'}
        self.stubs.Set(db, 'volume_admin_metadata_get',
                       stubs_volume_admin_metadata_get)
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)
        self.stubs.Set(volume_api.API, 'get_all',
                       stubs.stub_volume_api_get_all_by_project)
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)

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
                                 'id': fake.VOLUME_ID,
                                 'created_at': datetime.datetime(
                                     1900, 1, 1, 1, 1, 1,
                                     tzinfo=iso8601.iso8601.Utc()),
                                 'size': 1}]}
        self.assertEqual(expected, res_dict)
        # Finally test that we cached the returned volumes
        self.assertEqual(1, len(req.cached_resource()))

    def test_volume_list_with_admin_metadata(self):
        volume = stubs.stub_volume(fake.VOLUME_ID)
        del volume['name']
        del volume['volume_type']
        del volume['volume_type_id']
        volume['metadata'] = {'key': 'value'}
        db.volume_create(context.get_admin_context(), volume)
        db.volume_admin_metadata_update(context.get_admin_context(),
                                        fake.VOLUME_ID,
                                        {"readonly": "True",
                                         "invisible_key": "invisible_value"},
                                        False)
        values = {'volume_id': fake.VOLUME_ID, }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], fake.INSTANCE_ID, None, '/')

        req = fakes.HTTPRequest.blank('/v1/volumes')
        admin_ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
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
                                      'server_id': fake.INSTANCE_ID,
                                      'host_name': None,
                                      'id': fake.VOLUME_ID,
                                      'volume_id': fake.VOLUME_ID}],
                                 'multiattach': 'false',
                                 'bootable': 'false',
                                 'volume_type': None,
                                 'snapshot_id': None,
                                 'source_volid': None,
                                 'metadata': {'key': 'value',
                                              'readonly': 'True'},
                                 'id': fake.VOLUME_ID,
                                 'created_at': datetime.datetime(
                                     1900, 1, 1, 1, 1, 1,
                                     tzinfo=iso8601.iso8601.Utc()),
                                 'size': 1}]}
        self.assertEqual(expected, res_dict)

    @mock.patch.object(db, 'volume_admin_metadata_get',
                       return_value={'attached_mode': 'rw',
                                     'readonly': 'False'})
    def test_volume_list_detail(self, *args):
        self.stubs.Set(volume_api.API, 'get_all',
                       stubs.stub_volume_api_get_all_by_project)
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)

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
                                 'id': fake.VOLUME_ID,
                                 'created_at': datetime.datetime(
                                     1900, 1, 1, 1, 1, 1,
                                     tzinfo=iso8601.iso8601.Utc()),
                                 'size': 1}]}
        self.assertEqual(expected, res_dict)
        # Finally test that we cached the returned volumes
        self.assertEqual(1, len(req.cached_resource()))

    def test_volume_list_detail_with_admin_metadata(self):
        volume = stubs.stub_volume(fake.VOLUME_ID)
        del volume['name']
        del volume['volume_type']
        del volume['volume_type_id']
        volume['metadata'] = {'key': 'value'}
        db.volume_create(context.get_admin_context(), volume)
        db.volume_admin_metadata_update(context.get_admin_context(),
                                        fake.VOLUME_ID,
                                        {"readonly": "True",
                                         "invisible_key": "invisible_value"},
                                        False)
        values = {'volume_id': fake.VOLUME_ID, }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], fake.INSTANCE_ID, None, '/')

        req = fakes.HTTPRequest.blank('/v1/volumes/detail')
        admin_ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
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
                                      'server_id': fake.INSTANCE_ID,
                                      'host_name': None,
                                      'id': fake.VOLUME_ID,
                                      'volume_id': fake.VOLUME_ID}],
                                 'multiattach': 'false',
                                 'bootable': 'false',
                                 'volume_type': None,
                                 'snapshot_id': None,
                                 'source_volid': None,
                                 'metadata': {'key': 'value',
                                              'readonly': 'True'},
                                 'id': fake.VOLUME_ID,
                                 'created_at': datetime.datetime(
                                     1900, 1, 1, 1, 1, 1,
                                     tzinfo=iso8601.iso8601.Utc()),
                                 'size': 1}]}
        self.assertEqual(expected, res_dict)

    @mock.patch.object(db, 'volume_admin_metadata_get',
                       return_value={'attached_mode': 'rw',
                                     'readonly': 'False'})
    @mock.patch.object(volume_api.API, 'get',
                       side_effect=stubs.stub_volume_api_get, autospec=True)
    @mock.patch.object(db.sqlalchemy.api, '_volume_type_get_full',
                       side_effect=stubs.stub_volume_type_get, autospec=True)
    def test_volume_show(self, *args):
        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
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
                               'id': fake.VOLUME_ID,
                               'created_at': datetime.datetime(
                                   1900, 1, 1, 1, 1, 1,
                                   tzinfo=iso8601.iso8601.Utc()),
                               'size': 1}}
        self.assertEqual(expected, res_dict)
        # Finally test that we cached the returned volume
        self.assertIsNotNone(req.cached_resource_by_id(fake.VOLUME_ID))

    def test_volume_show_no_attachments(self):
        def stub_volume_get(self, context, volume_id, **kwargs):
            vol = stubs.stub_volume(
                volume_id,
                attach_status = fields.VolumeAttachStatus.DETACHED)
            return fake_volume.fake_volume_obj(context, **vol)

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
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
                               'id': fake.VOLUME_ID,
                               'created_at': datetime.datetime(
                                   1900, 1, 1, 1, 1, 1,
                                   tzinfo=iso8601.iso8601.Utc()),
                               'size': 1}}
        self.assertEqual(expected, res_dict)

    def test_volume_show_bootable(self):
        def stub_volume_get(self, context, volume_id, **kwargs):
            vol = (stubs.stub_volume(volume_id,
                   volume_glance_metadata=dict(foo='bar')))
            return fake_volume.fake_volume_obj(context, **vol)

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
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
                               'id': fake.VOLUME_ID,
                               'created_at': datetime.datetime(
                                   1900, 1, 1, 1, 1, 1,
                                   tzinfo=iso8601.iso8601.Utc()),
                               'size': 1}}
        self.assertEqual(expected, res_dict)

    def test_volume_show_no_volume(self):

        req = fakes.HTTPRequest.blank(
            '/v1/volumes/%s' % fake.WILL_NOT_BE_FOUND_ID)
        self.assertRaises(exc.VolumeNotFound,
                          self.controller.show,
                          req,
                          fake.WILL_NOT_BE_FOUND_ID)
        # Finally test that we did not cache anything
        self.assertIsNone(req.cached_resource_by_id(fake.WILL_NOT_BE_FOUND_ID))

    def test_volume_detail_limit_offset(self):
        def volume_detail_limit_offset(is_admin):
            def stub_volume_get_all_by_project(context, project_id, marker,
                                               limit, sort_keys=None,
                                               sort_dirs=None, filters=None,
                                               viewable_admin_meta=False,
                                               offset=None):
                return [
                    stubs.stub_volume(fake.VOLUME_ID, display_name='vol1'),
                    stubs.stub_volume(fake.VOLUME2_ID, display_name='vol2'),
                ]

            self.stubs.Set(db, 'volume_get_all_by_project',
                           stub_volume_get_all_by_project)
            self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)
            self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                           stubs.stub_volume_type_get)

            req = fakes.HTTPRequest.blank('/v1/volumes/detail?limit=2\
                                          &offset=1',
                                          use_admin_context=is_admin)
            res_dict = self.controller.index(req)
            volumes = res_dict['volumes']
            self.assertEqual(1, len(volumes))
            self.assertEqual(fake.VOLUME2_ID, volumes[0]['id'])

        # admin case
        volume_detail_limit_offset(is_admin=True)
        # non_admin case
        volume_detail_limit_offset(is_admin=False)

    def test_volume_show_with_admin_metadata(self):
        volume = stubs.stub_volume(fake.VOLUME_ID)
        del volume['name']
        del volume['volume_type']
        del volume['volume_type_id']
        volume['metadata'] = {'key': 'value'}
        db.volume_create(context.get_admin_context(), volume)
        db.volume_admin_metadata_update(context.get_admin_context(),
                                        fake.VOLUME_ID,
                                        {"readonly": "True",
                                         "invisible_key": "invisible_value"},
                                        False)
        values = {'volume_id': fake.VOLUME_ID, }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], fake.INSTANCE_ID, None, '/')

        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        admin_ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        expected = {'volume': {'status': 'in-use',
                               'display_description': 'displaydesc',
                               'availability_zone': 'fakeaz',
                               'display_name': 'displayname',
                               'encrypted': False,
                               'attachments': [
                                   {'attachment_id': attachment['id'],
                                    'device': '/',
                                    'server_id': fake.INSTANCE_ID,
                                    'host_name': None,
                                    'id': fake.VOLUME_ID,
                                    'volume_id': fake.VOLUME_ID}],
                               'multiattach': 'false',
                               'bootable': 'false',
                               'volume_type': None,
                               'snapshot_id': None,
                               'source_volid': None,
                               'metadata': {'key': 'value',
                                            'readonly': 'True'},
                               'id': fake.VOLUME_ID,
                               'created_at': datetime.datetime(
                                   1900, 1, 1, 1, 1, 1,
                                   tzinfo=iso8601.iso8601.Utc()),
                               'size': 1}}
        self.assertEqual(expected, res_dict)

    def test_volume_show_with_encrypted_volume(self):
        def stub_volume_get(self, context, volume_id, **kwargs):
            vol = stubs.stub_volume(volume_id, encryption_key_id=fake.KEY_ID)
            return fake_volume.fake_volume_obj(context, **vol)

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        self.assertTrue(res_dict['volume']['encrypted'])

    def test_volume_show_with_unencrypted_volume(self):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_api_get)
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        self.assertEqual(False, res_dict['volume']['encrypted'])

    def test_volume_delete(self):
        self.stubs.Set(db.sqlalchemy.api, 'volume_get',
                       stubs.stub_volume_get_db)

        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        resp = self.controller.delete(req, fake.VOLUME_ID)
        self.assertEqual(202, resp.status_int)

    def test_volume_delete_no_volume(self):
        req = fakes.HTTPRequest.blank(
            '/v1/volumes/%s' % fake.WILL_NOT_BE_FOUND_ID)
        self.assertRaises(exc.VolumeNotFound,
                          self.controller.delete,
                          req,
                          fake.WILL_NOT_BE_FOUND_ID)

    def test_admin_list_volumes_limited_to_project(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)
        req = fakes.HTTPRequest.blank('/v1/%s/volumes' % fake.PROJECT_ID,
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    def test_admin_list_volumes_all_tenants(self):
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)
        req = fakes.HTTPRequest.blank(
            '/v1/%s/volumes?all_tenants=1' % fake.PROJECT_ID,
            use_admin_context=True)
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(3, len(res['volumes']))

    def test_all_tenants_non_admin_gets_all_tenants(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)

        req = fakes.HTTPRequest.blank(
            '/v1/%s/volumes?all_tenants=1' % fake.PROJECT_ID)
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    def test_non_admin_get_by_project(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)
        self.stubs.Set(db.sqlalchemy.api, '_volume_type_get_full',
                       stubs.stub_volume_type_get)

        req = fakes.HTTPRequest.blank('/v1/%s/volumes' % fake.PROJECT_ID)
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

    @ddt.data({'s': 'ea895e29-8485-4930-bbb8-c5616a309c0e'},
              ['ea895e29-8485-4930-bbb8-c5616a309c0e'],
              42)
    def test_volume_creation_fails_with_invalid_snapshot_type(self, value):
        snapshot_id = value
        vol = {"size": 1,
               "snapshot_id": snapshot_id}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v1/volumes')
        # Raise 400 when snapshot has not uuid type.
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, body)


class VolumesUnprocessableEntityTestCase(test.TestCase):

    """Tests of places we throw 422 Unprocessable Entity from."""

    def setUp(self):
        super(VolumesUnprocessableEntityTestCase, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = volumes.VolumeController(self.ext_mgr)

    def _unprocessable_volume_create(self, body):
        req = fakes.HTTPRequest.blank('/v1/%s/volumes' % fake.PROJECT_ID)
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
