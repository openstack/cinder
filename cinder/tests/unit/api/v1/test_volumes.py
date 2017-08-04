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
from six.moves import http_client
from six.moves import range
import webob

from cinder.api import extensions
from cinder.api.v1 import volumes
from cinder import context
from cinder import db
from cinder import exception as exc
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import utils
from cinder.volume import api as volume_api

CONF = cfg.CONF


@ddt.ddt
class VolumeApiTest(test.TestCase):
    def setUp(self):
        super(VolumeApiTest, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        fake_image.mock_image_service(self)
        self.controller = volumes.VolumeController(self.ext_mgr)
        self.maxDiff = None
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

    def test_volume_create(self):
        self.mock_object(volume_api.API, 'get', v2_fakes.fake_volume_get)
        self.mock_object(volume_api.API, "create",
                         v2_fakes.fake_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

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

    @mock.patch.object(db, 'service_get_all',
                       return_value=v2_fakes.fake_service_get_all_by_topic(
                           None, None),
                       autospec=True)
    def test_volume_create_with_type(self, mock_service_get):
        vol_type = db.volume_type_create(
            context.get_admin_context(),
            dict(name=CONF.default_volume_type, extra_specs={})
        )
        db_vol_type = db.volume_type_get(context.get_admin_context(),
                                         vol_type.id)

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
        self.assertRaises(exc.InvalidAvailabilityZone,
                          self.controller.create,
                          req, body)

    def test_volume_create_with_image_id(self):
        self.mock_object(volume_api.API, "create",
                         v2_fakes.fake_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

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
        self.mock_object(volume_api.API, "create", v2_fakes.fake_volume_create)
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
        self.mock_object(volume_api.API, "create", v2_fakes.fake_volume_create)
        self.mock_object(fake_image._FakeImageService,
                         "detail",
                         v2_fakes.fake_image_service_detail)
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
        self.mock_object(volume_api.API, "create", v2_fakes.fake_volume_create)
        self.mock_object(fake_image._FakeImageService,
                         "detail",
                         v2_fakes.fake_image_service_detail)
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

    def test_volume_update(self):
        self.mock_object(volume_api.API, 'get', v2_fakes.fake_volume_api_get)
        self.mock_object(volume_api.API, "update", v2_fakes.fake_volume_update)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)
        self.mock_object(db, 'volume_admin_metadata_get',
                         return_value={'attached_mode': 'rw',
                                       'readonly': 'False'})

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

    def test_volume_update_metadata(self):
        self.mock_object(volume_api.API, 'get', v2_fakes.fake_volume_api_get)
        self.mock_object(volume_api.API, "update", v2_fakes.fake_volume_update)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

        updates = {
            "metadata": {"qos_max_iops": '2000'}
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
        self.mock_object(volume_api.API, "update", v2_fakes.fake_volume_update)

        volume = v2_fakes.create_fake_volume(fake.VOLUME_ID)
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
        self.mock_object(volume_api.API, "get",
                         v2_fakes.fake_volume_get_notfound)
        updates = {
            "name": "Updated Test Name",
        }

        body = {"volume": updates}
        req = fakes.HTTPRequest.blank(
            '/v1/volumes/%s' % fake.WILL_NOT_BE_FOUND_ID)
        self.assertRaises(exc.VolumeNotFound,
                          self.controller.update,
                          req, fake.WILL_NOT_BE_FOUND_ID, body)

    def test_volume_list(self):
        self.mock_object(volume_api.API, 'get_all',
                         v2_fakes.fake_volume_api_get_all_by_project)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

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
        volume = v2_fakes.create_fake_volume(fake.VOLUME_ID)
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

    def test_volume_list_detail(self):
        self.mock_object(volume_api.API, 'get_all',
                         v2_fakes.fake_volume_api_get_all_by_project)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/detail')
        res_dict = self.controller.detail(req)
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
        volume = v2_fakes.create_fake_volume(fake.VOLUME_ID)
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

    def test_volume_show(self):
        self.mock_object(volume_api.API, 'get', v2_fakes.fake_volume_api_get)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

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
        def fake_volume_get(self, context, volume_id, **kwargs):
            vol = v2_fakes.create_fake_volume(
                volume_id,
                attach_status=fields.VolumeAttachStatus.DETACHED)
            return fake_volume.fake_volume_obj(context, **vol)

        def fake_volume_admin_metadata_get(context, volume_id, **kwargs):
            return v2_fakes.fake_volume_admin_metadata_get(
                context, volume_id,
                attach_status=fields.VolumeAttachStatus.DETACHED)

        self.mock_object(volume_api.API, 'get', fake_volume_get)
        self.mock_object(db, 'volume_admin_metadata_get',
                         fake_volume_admin_metadata_get)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

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

    def test_volume_show_no_volume(self):
        self.mock_object(volume_api.API, "get",
                         v2_fakes.fake_volume_get_notfound)

        req = fakes.HTTPRequest.blank(
            '/v1/volumes/%s' % fake.WILL_NOT_BE_FOUND_ID)
        self.assertRaises(exc.VolumeNotFound,
                          self.controller.show,
                          req,
                          fake.WILL_NOT_BE_FOUND_ID)
        # Finally test that nothing was cached
        self.assertIsNone(req.cached_resource_by_id(fake.WILL_NOT_BE_FOUND_ID))

    def _create_db_volumes(self, num_volumes):
        volumes = [utils.create_volume(self.ctxt, display_name='vol%s' % i)
                   for i in range(num_volumes)]
        for vol in volumes:
            self.addCleanup(db.volume_destroy, self.ctxt, vol.id)
        volumes.reverse()
        return volumes

    def test_volume_detail_limit_offset(self):
        created_volumes = self._create_db_volumes(2)

        def volume_detail_limit_offset(is_admin):
            req = fakes.HTTPRequest.blank('/v1/volumes/detail?limit=2'
                                          '&offset=1',
                                          use_admin_context=is_admin)
            res_dict = self.controller.index(req)
            volumes = res_dict['volumes']
            self.assertEqual(1, len(volumes))
            self.assertEqual(created_volumes[1].id, volumes[0]['id'])

        # admin case
        volume_detail_limit_offset(is_admin=True)
        # non_admin case
        volume_detail_limit_offset(is_admin=False)

    def test_volume_show_with_admin_metadata(self):
        volume = v2_fakes.create_fake_volume(fake.VOLUME_ID)
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
        def fake_volume_get(self, context, volume_id, **kwargs):
            vol = v2_fakes.create_fake_volume(volume_id,
                                              encryption_key_id=fake.KEY_ID)
            return fake_volume.fake_volume_obj(context, **vol)

        self.mock_object(volume_api.API, 'get', fake_volume_get)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        self.assertTrue(res_dict['volume']['encrypted'])

    def test_volume_show_with_unencrypted_volume(self):
        self.mock_object(volume_api.API, 'get', v2_fakes.fake_volume_api_get)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        self.assertEqual(False, res_dict['volume']['encrypted'])

    @mock.patch.object(volume_api.API, 'delete', v2_fakes.fake_volume_delete)
    @mock.patch.object(volume_api.API, 'get', v2_fakes.fake_volume_get)
    def test_volume_delete(self):
        req = fakes.HTTPRequest.blank('/v1/volumes/%s' % fake.VOLUME_ID)
        resp = self.controller.delete(req, fake.VOLUME_ID)
        self.assertEqual(http_client.ACCEPTED, resp.status_int)

    def test_volume_delete_no_volume(self):
        self.mock_object(volume_api.API, "get",
                         v2_fakes.fake_volume_get_notfound)

        req = fakes.HTTPRequest.blank(
            '/v1/volumes/%s' % fake.WILL_NOT_BE_FOUND_ID)
        self.assertRaises(exc.VolumeNotFound,
                          self.controller.delete,
                          req, fake.WILL_NOT_BE_FOUND_ID)

    def test_admin_list_volumes_limited_to_project(self):
        self.mock_object(db, 'volume_get_all_by_project',
                         v2_fakes.fake_volume_get_all_by_project)

        req = fakes.HTTPRequest.blank('/v1/%s/volumes' % fake.PROJECT_ID,
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    @mock.patch.object(db, 'volume_get_all', v2_fakes.fake_volume_get_all)
    @mock.patch.object(db, 'volume_get_all_by_project',
                       v2_fakes.fake_volume_get_all_by_project)
    def test_admin_list_volumes_all_tenants(self):
        req = fakes.HTTPRequest.blank(
            '/v1/%s/volumes?all_tenants=1' % fake.PROJECT_ID,
            use_admin_context=True)
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(3, len(res['volumes']))

    @mock.patch.object(db, 'volume_get_all', v2_fakes.fake_volume_get_all)
    @mock.patch.object(db, 'volume_get_all_by_project',
                       v2_fakes.fake_volume_get_all_by_project)
    @mock.patch.object(volume_api.API, 'get', v2_fakes.fake_volume_get)
    def test_all_tenants_non_admin_gets_all_tenants(self):
        req = fakes.HTTPRequest.blank(
            '/v1/%s/volumes?all_tenants=1' % fake.PROJECT_ID)
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    @mock.patch.object(db, 'volume_get_all_by_project',
                       v2_fakes.fake_volume_get_all_by_project)
    @mock.patch.object(volume_api.API, 'get', v2_fakes.fake_volume_get)
    def test_non_admin_get_by_project(self):
        req = fakes.HTTPRequest.blank('/v1/%s/volumes' % fake.PROJECT_ID)
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

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
