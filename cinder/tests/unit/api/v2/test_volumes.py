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
import functools

from lxml import etree
import mock
from oslo_config import cfg
from oslo_utils import timeutils
import six
from six.moves import range
from six.moves import urllib
import webob

from cinder.api import common
from cinder.api import extensions
from cinder.api.v2 import volumes
from cinder import consistencygroup as consistencygroupAPI
from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import stubs
from cinder.tests.unit import fake_notifier
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import utils
from cinder.volume import api as volume_api

CONF = cfg.CONF

NS = '{http://docs.openstack.org/api/openstack-block-storage/2.0/content}'

DEFAULT_AZ = "zone1:host1"


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
        self.ctxt = context.RequestContext('admin', 'fakeproject', True)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create(self, mock_validate):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)

        vol = self._vol_in_request_body()
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        res_dict = self.controller.create(req, body)
        ex = self._expected_vol_from_controller()
        self.assertEqual(ex, res_dict)
        self.assertTrue(mock_validate.called)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create_with_type(self, mock_validate):
        vol_type = db.volume_type_create(
            context.get_admin_context(),
            dict(name=CONF.default_volume_type, extra_specs={})
        )

        db_vol_type = db.volume_type_get(context.get_admin_context(),
                                         vol_type.id)

        vol = self._vol_in_request_body(volume_type="FakeTypeName")
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
        self.assertEqual(1, len(res_dict))

        # Use correct volume type id
        vol.update(dict(volume_type=db_vol_type['id']))
        body.update(dict(volume=vol))
        res_dict = self.controller.create(req, body)
        volume_id = res_dict['volume']['id']
        self.assertEqual(1, len(res_dict))

        self.stubs.Set(volume_api.API, 'get_all',
                       lambda *args, **kwargs:
                       [stubs.stub_volume(volume_id,
                                          volume_type={'name': vol_type})])
        req = fakes.HTTPRequest.blank('/v2/volumes/detail')
        res_dict = self.controller.detail(req)
        self.assertTrue(mock_validate.called)

    def _vol_in_request_body(self,
                             size=stubs.DEFAULT_VOL_SIZE,
                             name=stubs.DEFAULT_VOL_NAME,
                             description=stubs.DEFAULT_VOL_DESCRIPTION,
                             availability_zone=DEFAULT_AZ,
                             snapshot_id=None,
                             source_volid=None,
                             source_replica=None,
                             consistencygroup_id=None,
                             volume_type=None,
                             image_ref=None,
                             image_id=None):
        vol = {"size": size,
               "name": name,
               "description": description,
               "availability_zone": availability_zone,
               "snapshot_id": snapshot_id,
               "source_volid": source_volid,
               "source_replica": source_replica,
               "consistencygroup_id": consistencygroup_id,
               "volume_type": volume_type,
               }

        if image_id is not None:
            vol['image_id'] = image_id
        elif image_ref is not None:
            vol['imageRef'] = image_ref

        return vol

    def _expected_vol_from_controller(
            self,
            size=stubs.DEFAULT_VOL_SIZE,
            availability_zone=DEFAULT_AZ,
            description=stubs.DEFAULT_VOL_DESCRIPTION,
            name=stubs.DEFAULT_VOL_NAME,
            consistencygroup_id=None,
            source_volid=None,
            snapshot_id=None,
            metadata=None,
            attachments=None,
            volume_type=stubs.DEFAULT_VOL_TYPE,
            status=stubs.DEFAULT_VOL_STATUS,
            with_migration_status=False):
        metadata = metadata or {}
        attachments = attachments or []
        volume = {'volume':
                  {'attachments': attachments,
                   'availability_zone': availability_zone,
                   'bootable': 'false',
                   'consistencygroup_id': consistencygroup_id,
                   'created_at': datetime.datetime(1900, 1, 1, 1, 1, 1),
                   'updated_at': datetime.datetime(1900, 1, 1, 1, 1, 1),
                   'description': description,
                   'id': stubs.DEFAULT_VOL_ID,
                   'links':
                   [{'href': 'http://localhost/v2/fakeproject/volumes/1',
                     'rel': 'self'},
                    {'href': 'http://localhost/fakeproject/volumes/1',
                     'rel': 'bookmark'}],
                   'metadata': metadata,
                   'name': name,
                   'replication_status': 'disabled',
                   'multiattach': False,
                   'size': size,
                   'snapshot_id': snapshot_id,
                   'source_volid': source_volid,
                   'status': status,
                   'user_id': 'fakeuser',
                   'volume_type': volume_type,
                   'encrypted': False}}

        if with_migration_status:
            volume['volume']['migration_status'] = None

        return volume

    def _expected_volume_api_create_kwargs(self, snapshot=None,
                                           availability_zone=DEFAULT_AZ,
                                           source_volume=None):
        return {'metadata': None,
                'snapshot': snapshot,
                'source_volume': source_volume,
                'source_replica': None,
                'consistencygroup': None,
                'availability_zone': availability_zone,
                'scheduler_hints': None,
                'multiattach': False,
                }

    @mock.patch.object(volume_api.API, 'get_snapshot', autospec=True)
    @mock.patch.object(volume_api.API, 'create', autospec=True)
    def test_volume_creation_from_snapshot(self, create, get_snapshot):

        create.side_effect = stubs.stub_volume_create
        get_snapshot.side_effect = stubs.stub_snapshot_get

        snapshot_id = stubs.TEST_SNAPSHOT_UUID
        vol = self._vol_in_request_body(snapshot_id=stubs.TEST_SNAPSHOT_UUID)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        res_dict = self.controller.create(req, body)

        ex = self._expected_vol_from_controller(snapshot_id=snapshot_id)
        self.assertEqual(ex, res_dict)

        context = req.environ['cinder.context']
        get_snapshot.assert_called_once_with(self.controller.volume_api,
                                             context, snapshot_id)

        kwargs = self._expected_volume_api_create_kwargs(
            stubs.stub_snapshot(snapshot_id))
        create.assert_called_once_with(self.controller.volume_api, context,
                                       vol['size'], stubs.DEFAULT_VOL_NAME,
                                       stubs.DEFAULT_VOL_DESCRIPTION, **kwargs)

    @mock.patch.object(volume_api.API, 'get_snapshot', autospec=True)
    def test_volume_creation_fails_with_invalid_snapshot(self, get_snapshot):

        get_snapshot.side_effect = stubs.stub_snapshot_get

        snapshot_id = "fake_id"
        vol = self._vol_in_request_body(snapshot_id=snapshot_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        # Raise 404 when snapshot cannot be found.
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          req, body)

        context = req.environ['cinder.context']
        get_snapshot.assert_called_once_with(self.controller.volume_api,
                                             context, snapshot_id)

    @mock.patch.object(volume_api.API, 'get_volume', autospec=True)
    @mock.patch.object(volume_api.API, 'create', autospec=True)
    def test_volume_creation_from_source_volume(self, create, get_volume):

        get_volume.side_effect = functools.partial(stubs.stub_volume_get,
                                                   viewable_admin_meta=True)
        create.side_effect = stubs.stub_volume_create

        source_volid = '2f49aa3a-6aae-488d-8b99-a43271605af6'
        vol = self._vol_in_request_body(source_volid=source_volid)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        res_dict = self.controller.create(req, body)

        ex = self._expected_vol_from_controller(source_volid=source_volid)
        self.assertEqual(ex, res_dict)

        context = req.environ['cinder.context']
        get_volume.assert_called_once_with(self.controller.volume_api,
                                           context, source_volid)

        kwargs = self._expected_volume_api_create_kwargs(
            source_volume=stubs.stub_volume(source_volid))
        create.assert_called_once_with(self.controller.volume_api, context,
                                       vol['size'], stubs.DEFAULT_VOL_NAME,
                                       stubs.DEFAULT_VOL_DESCRIPTION, **kwargs)

    @mock.patch.object(volume_api.API, 'get_volume', autospec=True)
    def test_volume_creation_fails_with_invalid_source_volume(self,
                                                              get_volume):

        get_volume.side_effect = stubs.stub_volume_get_notfound

        source_volid = "fake_id"
        vol = self._vol_in_request_body(source_volid=source_volid)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        # Raise 404 when source volume cannot be found.
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          req, body)

        context = req.environ['cinder.context']
        get_volume.assert_called_once_with(self.controller.volume_api,
                                           context, source_volid)

    @mock.patch.object(volume_api.API, 'get_volume', autospec=True)
    def test_volume_creation_fails_with_invalid_source_replica(self,
                                                               get_volume):

        get_volume.side_effect = stubs.stub_volume_get_notfound

        source_replica = "fake_id"
        vol = self._vol_in_request_body(source_replica=source_replica)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        # Raise 404 when source replica cannot be found.
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          req, body)

        context = req.environ['cinder.context']
        get_volume.assert_called_once_with(self.controller.volume_api,
                                           context, source_replica)

    @mock.patch.object(volume_api.API, 'get_volume', autospec=True)
    def test_volume_creation_fails_with_invalid_source_replication_status(
            self, get_volume):

        get_volume.side_effect = stubs.stub_volume_get

        source_replica = '2f49aa3a-6aae-488d-8b99-a43271605af6'
        vol = self._vol_in_request_body(source_replica=source_replica)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        # Raise 400 when replication status is disabled.
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, body)

        context = req.environ['cinder.context']
        get_volume.assert_called_once_with(self.controller.volume_api,
                                           context, source_replica)

    @mock.patch.object(consistencygroupAPI.API, 'get', autospec=True)
    def test_volume_creation_fails_with_invalid_consistency_group(self,
                                                                  get_cg):

        get_cg.side_effect = stubs.stub_consistencygroup_get_notfound

        consistencygroup_id = '4f49aa3a-6aae-488d-8b99-a43271605af6'
        vol = self._vol_in_request_body(
            consistencygroup_id=consistencygroup_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        # Raise 404 when consistency group is not found.
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          req, body)

        context = req.environ['cinder.context']
        get_cg.assert_called_once_with(self.controller.consistencygroup_api,
                                       context, consistencygroup_id)

    def test_volume_creation_fails_with_bad_size(self):
        vol = self._vol_in_request_body(size="")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(exception.InvalidInput,
                          self.controller.create,
                          req,
                          body)

    def test_volume_creation_fails_with_bad_availability_zone(self):
        vol = self._vol_in_request_body(availability_zone="zonen:hostn")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(exception.InvalidInput,
                          self.controller.create,
                          req, body)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create_with_image_ref(self, mock_validate):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)

        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = self._vol_in_request_body(
            availability_zone="nova",
            image_ref="c905cedb-7281-47e4-8a62-f26bc5fc4c77")
        ex = self._expected_vol_from_controller(availability_zone="nova")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        res_dict = self.controller.create(req, body)
        self.assertEqual(ex, res_dict)
        self.assertTrue(mock_validate.called)

    def test_volume_create_with_image_ref_is_integer(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_ref=1234)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_with_image_ref_not_uuid_format(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_ref="12345")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_with_image_ref_with_empty_string(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_ref="")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create_with_image_id(self, mock_validate):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)

        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = self._vol_in_request_body(
            availability_zone="nova",
            image_id="c905cedb-7281-47e4-8a62-f26bc5fc4c77")
        ex = self._expected_vol_from_controller(availability_zone="nova")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        res_dict = self.controller.create(req, body)
        self.assertEqual(ex, res_dict)
        self.assertTrue(mock_validate.called)

    def test_volume_create_with_image_id_is_integer(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_id=1234)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_with_image_id_not_uuid_format(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_id="12345")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_with_image_id_with_empty_string(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_id="")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create_with_image_name(self, mock_validate):
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.stubs.Set(fake_image._FakeImageService,
                       "detail",
                       stubs.stub_image_service_detail)

        test_id = "Fedora-x86_64-20-20140618-sda"
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = self._vol_in_request_body(availability_zone="nova",
                                        image_ref=test_id)
        ex = self._expected_vol_from_controller(availability_zone="nova")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        res_dict = self.controller.create(req, body)
        self.assertEqual(ex, res_dict)
        self.assertTrue(mock_validate.called)

    def test_volume_create_with_image_name_has_multiple(self):
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.stubs.Set(fake_image._FakeImageService,
                       "detail",
                       stubs.stub_image_service_detail)

        test_id = "multi"
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = self._vol_in_request_body(availability_zone="nova",
                                        image_ref=test_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    def test_volume_create_with_image_name_no_match(self):
        self.stubs.Set(db, 'volume_get', stubs.stub_volume_get_db)
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)
        self.stubs.Set(fake_image._FakeImageService,
                       "detail",
                       stubs.stub_image_service_detail)

        test_id = "MissingName"
        self.ext_mgr.extensions = {'os-image-create': 'fake'}
        vol = self._vol_in_request_body(availability_zone="nova",
                                        image_ref=test_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_update(self, mock_validate):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "update", stubs.stub_volume_update)

        updates = {
            "name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller.update(req, '1', body)
        expected = self._expected_vol_from_controller(
            availability_zone=stubs.DEFAULT_AZ, name="Updated Test Name",
            metadata={'attached_mode': 'rw', 'readonly': 'False'})
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_update_deprecation(self, mock_validate):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "update", stubs.stub_volume_update)

        updates = {
            "display_name": "Updated Test Name",
            "display_description": "Updated Test Description",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller.update(req, '1', body)
        expected = self._expected_vol_from_controller(
            availability_zone=stubs.DEFAULT_AZ, name="Updated Test Name",
            description="Updated Test Description",
            metadata={'attached_mode': 'rw', 'readonly': 'False'})
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_update_deprecation_key_priority(self, mock_validate):
        """Test current update keys have priority over deprecated keys."""
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "update", stubs.stub_volume_update)

        updates = {
            "name": "New Name",
            "description": "New Description",
            "display_name": "Not Shown Name",
            "display_description": "Not Shown Description",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller.update(req, '1', body)
        expected = self._expected_vol_from_controller(
            availability_zone=stubs.DEFAULT_AZ,
            name="New Name", description="New Description",
            metadata={'attached_mode': 'rw', 'readonly': 'False'})
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_update_metadata(self, mock_validate):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)
        self.stubs.Set(volume_api.API, "update", stubs.stub_volume_update)

        updates = {
            "metadata": {"qos_max_iops": 2000}
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller.update(req, '1', body)
        expected = self._expected_vol_from_controller(
            availability_zone=stubs.DEFAULT_AZ,
            metadata={'attached_mode': 'rw', 'readonly': 'False',
                      'qos_max_iops': 2000})
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_update_with_admin_metadata(self, mock_validate):
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
        attach_tmp = db.volume_attachment_get(context.get_admin_context(),
                                              attachment['id'])
        volume_tmp = db.volume_get(context.get_admin_context(), '1')
        updates = {
            "name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        self.assertEqual(0, len(self.notifier.notifications))
        admin_ctx = context.RequestContext('admin', 'fakeproject', True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.update(req, '1', body)
        expected = self._expected_vol_from_controller(
            availability_zone=stubs.DEFAULT_AZ, volume_type=None,
            status='in-use', name='Updated Test Name',
            attachments=[{'id': '1',
                          'attachment_id': attachment['id'],
                          'volume_id': stubs.DEFAULT_VOL_ID,
                          'server_id': stubs.FAKE_UUID,
                          'host_name': None,
                          'device': '/',
                          'attached_at': attach_tmp['attach_time'],
                          }],
            metadata={'key': 'value', 'readonly': 'True'},
            with_migration_status=True)
        expected['volume']['updated_at'] = volume_tmp['updated_at']
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)

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
                    'name': stubs.DEFAULT_VOL_NAME,
                    'id': '1',
                    'links': [
                        {
                            'href': 'http://localhost/v2/fakeproject/volumes/'
                                    '1',
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
        self.assertEqual(expected, res_dict)
        # Finally test that we cached the returned volumes
        self.assertEqual(1, len(req.cached_resource()))

    def test_volume_list_detail(self):
        self.stubs.Set(volume_api.API, 'get_all',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail')
        res_dict = self.controller.detail(req)
        exp_vol = self._expected_vol_from_controller(
            availability_zone=stubs.DEFAULT_AZ,
            metadata={'attached_mode': 'rw', 'readonly': 'False'})
        expected = {'volumes': [exp_vol['volume']]}
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
        attach_tmp = db.volume_attachment_get(context.get_admin_context(),
                                              attachment['id'])
        volume_tmp = db.volume_get(context.get_admin_context(), '1')

        req = fakes.HTTPRequest.blank('/v2/volumes/detail')
        admin_ctx = context.RequestContext('admin', 'fakeproject', True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.detail(req)
        exp_vol = self._expected_vol_from_controller(
            availability_zone=stubs.DEFAULT_AZ,
            status="in-use", volume_type=None,
            attachments=[{'attachment_id': attachment['id'],
                          'device': '/',
                          'server_id': stubs.FAKE_UUID,
                          'host_name': None,
                          'id': '1',
                          'volume_id': stubs.DEFAULT_VOL_ID,
                          'attached_at': attach_tmp['attach_time'],
                          }],
            metadata={'key': 'value', 'readonly': 'True'},
            with_migration_status=True)
        exp_vol['volume']['updated_at'] = volume_tmp['updated_at']
        expected = {'volumes': [exp_vol['volume']]}
        self.assertEqual(expected, res_dict)

    def test_volume_index_with_marker(self):
        def stub_volume_get_all_by_project(context, project_id, marker, limit,
                                           sort_keys=None, sort_dirs=None,
                                           filters=None,
                                           viewable_admin_meta=False,
                                           offset=0):
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
        self.assertEqual(2, len(volumes))
        self.assertEqual(1, volumes[0]['id'])
        self.assertEqual(2, volumes[1]['id'])

    def test_volume_index_limit(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes'
                                      '?limit=1&name=foo'
                                      '&sort=id1:asc')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))

        # Ensure that the next link is correctly formatted, it should
        # contain the same limit, filter, and sort information as the
        # original request as well as a marker; this ensures that the
        # caller can simply use the "next" link and that they do not
        # need to manually insert the limit and sort information.
        links = res_dict['volumes_links']
        self.assertEqual('next', links[0]['rel'])
        href_parts = urllib.parse.urlparse(links[0]['href'])
        self.assertEqual('/v2/fakeproject/volumes', href_parts.path)
        params = urllib.parse.parse_qs(href_parts.query)
        self.assertEqual(str(volumes[0]['id']), params['marker'][0])
        self.assertEqual('1', params['limit'][0])
        self.assertEqual('foo', params['name'][0])
        self.assertEqual('id1:asc', params['sort'][0])

    def test_volume_index_limit_negative(self):
        req = fakes.HTTPRequest.blank('/v2/volumes?limit=-1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

    def test_volume_index_limit_non_int(self):
        req = fakes.HTTPRequest.blank('/v2/volumes?limit=a')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

    def test_volume_index_limit_marker(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes?marker=1&limit=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual('1', volumes[0]['id'])

    def _create_db_volumes(self, num_volumes):
        volumes = [utils.create_volume(self.ctxt, display_name='vol%s' % i)
                   for i in range(num_volumes)]
        for vol in volumes:
            self.addCleanup(db.volume_destroy, self.ctxt, vol.id)
        volumes.reverse()
        return volumes

    def test_volume_index_limit_offset(self):
        created_volumes = self._create_db_volumes(2)
        req = fakes.HTTPRequest.blank('/v2/volumes?limit=2&offset=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(created_volumes[1].id, volumes[0]['id'])

        req = fakes.HTTPRequest.blank('/v2/volumes?limit=-1&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

        req = fakes.HTTPRequest.blank('/v2/volumes?limit=a&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

    def test_volume_detail_with_marker(self):
        def stub_volume_get_all_by_project(context, project_id, marker, limit,
                                           sort_keys=None, sort_dirs=None,
                                           filters=None,
                                           viewable_admin_meta=False,
                                           offset=0):
            return [
                stubs.stub_volume(1, display_name='vol1'),
                stubs.stub_volume(2, display_name='vol2'),
            ]
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?marker=1')
        res_dict = self.controller.detail(req)
        volumes = res_dict['volumes']
        self.assertEqual(2, len(volumes))
        self.assertEqual(1, volumes[0]['id'])
        self.assertEqual(2, volumes[1]['id'])

    def test_volume_detail_limit(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=1')
        res_dict = self.controller.detail(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))

        # Ensure that the next link is correctly formatted
        links = res_dict['volumes_links']
        self.assertEqual('next', links[0]['rel'])
        href_parts = urllib.parse.urlparse(links[0]['href'])
        self.assertEqual('/v2/fakeproject/volumes/detail', href_parts.path)
        params = urllib.parse.parse_qs(href_parts.query)
        self.assertTrue('marker' in params)
        self.assertEqual('1', params['limit'][0])

    def test_volume_detail_limit_negative(self):
        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=-1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail,
                          req)

    def test_volume_detail_limit_non_int(self):
        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=a')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail,
                          req)

    def test_volume_detail_limit_marker(self):
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stubs.stub_volume_get_all_by_project)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?marker=1&limit=1')
        res_dict = self.controller.detail(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual('1', volumes[0]['id'])

    def test_volume_detail_limit_offset(self):
        created_volumes = self._create_db_volumes(2)
        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=2&offset=1')
        res_dict = self.controller.detail(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(created_volumes[1].id, volumes[0]['id'])

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=2&offset=1',
                                      use_admin_context=True)
        res_dict = self.controller.detail(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(created_volumes[1].id, volumes[0]['id'])

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=-1&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail,
                          req)

        req = fakes.HTTPRequest.blank('/v2/volumes/detail?limit=a&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail,
                          req)

    def test_volume_with_limit_zero(self):
        def stub_volume_get_all(context, marker, limit, **kwargs):
            return []
        self.stubs.Set(db, 'volume_get_all', stub_volume_get_all)
        req = fakes.HTTPRequest.blank('/v2/volumes?limit=0')
        res_dict = self.controller.index(req)
        expected = {'volumes': []}
        self.assertEqual(expected, res_dict)

    def _validate_next_link(self, detailed, item_count, osapi_max_limit, limit,
                            should_link_exist):
        keys_fns = (('volumes', self.controller.index),
                    ('volumes/detail', self.controller.detail))
        key, fn = keys_fns[detailed]

        req_string = '/v2/%s?all_tenants=1' % key
        if limit:
            req_string += '&limit=%s' % limit
        req = fakes.HTTPRequest.blank(req_string, use_admin_context=True)

        link_return = [{"rel": "next", "href": "fake_link"}]
        self.flags(osapi_max_limit=osapi_max_limit)

        def get_pagination_params(params, max_limit=CONF.osapi_max_limit,
                                  original_call=common.get_pagination_params):
            return original_call(params, max_limit)

        def _get_limit_param(params, max_limit=CONF.osapi_max_limit,
                             original_call=common._get_limit_param):
            return original_call(params, max_limit)

        with mock.patch.object(common, 'get_pagination_params',
                               get_pagination_params), \
                mock.patch.object(common, '_get_limit_param',
                                  _get_limit_param), \
                mock.patch.object(common.ViewBuilder, '_generate_next_link',
                                  return_value=link_return):
            res_dict = fn(req)
            self.assertEqual(item_count, len(res_dict['volumes']))
            self.assertEqual(should_link_exist, 'volumes_links' in res_dict)

    def test_volume_default_limit(self):
        self.stubs.UnsetAll()
        self._create_db_volumes(3)

        # Verify both the index and detail queries
        for detailed in (True, False):
            # Number of volumes less than max, do not include
            self._validate_next_link(detailed, item_count=3, osapi_max_limit=4,
                                     limit=None, should_link_exist=False)

            # Number of volumes equals the max, next link will be included
            self._validate_next_link(detailed, item_count=3, osapi_max_limit=3,
                                     limit=None, should_link_exist=True)

            # Number of volumes more than the max, include next link
            self._validate_next_link(detailed, item_count=2, osapi_max_limit=2,
                                     limit=None, should_link_exist=True)

            # Limit lower than max but doesn't limit, no next link
            self._validate_next_link(detailed, item_count=3, osapi_max_limit=5,
                                     limit=4, should_link_exist=False)

            # Limit lower than max and limits, we have next link
            self._validate_next_link(detailed, item_count=2, osapi_max_limit=4,
                                     limit=2, should_link_exist=True)

            # Limit higher than max and max limits, we have next link
            self._validate_next_link(detailed, item_count=2, osapi_max_limit=2,
                                     limit=4, should_link_exist=True)

            # Limit higher than max but none of them limiting, no next link
            self._validate_next_link(detailed, item_count=3, osapi_max_limit=4,
                                     limit=5, should_link_exist=False)

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
                                           sort_keys=None, sort_dirs=None,
                                           filters=None,
                                           viewable_admin_meta=False,
                                           offset=0):
            self.assertEqual(True, filters['no_migration_targets'])
            self.assertFalse('all_tenants' in filters)
            return [stubs.stub_volume(1, display_name='vol1')]

        def stub_volume_get_all(context, marker, limit,
                                sort_keys=None, sort_dirs=None,
                                filters=None,
                                viewable_admin_meta=False, offset=0):
            return []
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stub_volume_get_all_by_project)
        self.stubs.Set(db, 'volume_get_all', stub_volume_get_all)

        # all_tenants does not matter for non-admin
        for params in ['', '?all_tenants=1']:
            req = fakes.HTTPRequest.blank('/v2/volumes%s' % params)
            resp = self.controller.index(req)
            self.assertEqual(1, len(resp['volumes']))
            self.assertEqual('vol1', resp['volumes'][0]['name'])

        # Admin, all_tenants is not set, project function should be called
        # without no_migration_status
        def stub_volume_get_all_by_project2(context, project_id, marker, limit,
                                            sort_keys=None, sort_dirs=None,
                                            filters=None,
                                            viewable_admin_meta=False,
                                            offset=0):
            self.assertFalse('no_migration_targets' in filters)
            return [stubs.stub_volume(1, display_name='vol2')]

        def stub_volume_get_all2(context, marker, limit,
                                 sort_keys=None, sort_dirs=None,
                                 filters=None,
                                 viewable_admin_meta=False, offset=0):
            return []
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stub_volume_get_all_by_project2)
        self.stubs.Set(db, 'volume_get_all', stub_volume_get_all2)

        req = fakes.HTTPRequest.blank('/v2/volumes', use_admin_context=True)
        resp = self.controller.index(req)
        self.assertEqual(1, len(resp['volumes']))
        self.assertEqual('vol2', resp['volumes'][0]['name'])

        # Admin, all_tenants is set, get_all function should be called
        # without no_migration_status
        def stub_volume_get_all_by_project3(context, project_id, marker, limit,
                                            sort_keys=None, sort_dirs=None,
                                            filters=None,
                                            viewable_admin_meta=False,
                                            offset=0):
            return []

        def stub_volume_get_all3(context, marker, limit,
                                 sort_keys=None, sort_dirs=None,
                                 filters=None,
                                 viewable_admin_meta=False, offset=0):
            self.assertFalse('no_migration_targets' in filters)
            self.assertFalse('all_tenants' in filters)
            return [stubs.stub_volume(1, display_name='vol3')]
        self.stubs.Set(db, 'volume_get_all_by_project',
                       stub_volume_get_all_by_project3)
        self.stubs.Set(db, 'volume_get_all', stub_volume_get_all3)

        req = fakes.HTTPRequest.blank('/v2/volumes?all_tenants=1',
                                      use_admin_context=True)
        resp = self.controller.index(req)
        self.assertEqual(1, len(resp['volumes']))
        self.assertEqual('vol3', resp['volumes'][0]['name'])

    def test_volume_show(self):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        res_dict = self.controller.show(req, '1')
        expected = self._expected_vol_from_controller(
            availability_zone=stubs.DEFAULT_AZ,
            metadata={'attached_mode': 'rw', 'readonly': 'False'})
        self.assertEqual(expected, res_dict)
        # Finally test that we cached the returned volume
        self.assertIsNotNone(req.cached_resource_by_id('1'))

    def test_volume_show_no_attachments(self):
        def stub_volume_get(self, context, volume_id, **kwargs):
            return stubs.stub_volume(volume_id, attach_status='detached')

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        res_dict = self.controller.show(req, '1')
        expected = self._expected_vol_from_controller(
            availability_zone=stubs.DEFAULT_AZ,
            metadata={'readonly': 'False'})

        self.assertEqual(expected, res_dict)

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
        values = {'volume_id': '1', }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], stubs.FAKE_UUID, None, '/')
        attach_tmp = db.volume_attachment_get(context.get_admin_context(),
                                              attachment['id'])
        volume_tmp = db.volume_get(context.get_admin_context(), '1')
        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        admin_ctx = context.RequestContext('admin', 'fakeproject', True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.show(req, '1')
        expected = self._expected_vol_from_controller(
            availability_zone=stubs.DEFAULT_AZ,
            volume_type=None, status='in-use',
            attachments=[{'id': '1',
                          'attachment_id': attachment['id'],
                          'volume_id': stubs.DEFAULT_VOL_ID,
                          'server_id': stubs.FAKE_UUID,
                          'host_name': None,
                          'device': '/',
                          'attached_at': attach_tmp['attach_time'],
                          }],
            metadata={'key': 'value', 'readonly': 'True'},
            with_migration_status=True)
        expected['volume']['updated_at'] = volume_tmp['updated_at']
        self.assertEqual(expected, res_dict)

    def test_volume_show_with_encrypted_volume(self):
        def stub_volume_get(self, context, volume_id, **kwargs):
            return stubs.stub_volume(volume_id, encryption_key_id='fake_id')

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        res_dict = self.controller.show(req, 1)
        self.assertEqual(True, res_dict['volume']['encrypted'])

    def test_volume_show_with_unencrypted_volume(self):
        def stub_volume_get(self, context, volume_id, **kwargs):
            return stubs.stub_volume(volume_id, encryption_key_id=None)

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        res_dict = self.controller.show(req, 1)
        self.assertEqual(False, res_dict['volume']['encrypted'])

    def test_volume_delete(self):
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        resp = self.controller.delete(req, 1)
        self.assertEqual(202, resp.status_int)

    def test_volume_delete_attached(self):
        def stub_volume_attached(self, context, volume, force=False):
            raise exception.VolumeAttached(volume_id=volume['id'])
        self.stubs.Set(volume_api.API, "delete", stub_volume_attached)
        self.stubs.Set(volume_api.API, 'get', stubs.stub_volume_get)

        req = fakes.HTTPRequest.blank('/v2/volumes/1')
        exp = self.assertRaises(webob.exc.HTTPBadRequest,
                                self.controller.delete,
                                req, 1)
        expect_msg = "Volume cannot be deleted while in attached state"
        self.assertEqual(expect_msg, six.text_type(exp))

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

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_string(self, get_all):
        req = mock.MagicMock()
        context = mock.Mock()
        req.environ = {'cinder.context': context}
        req.params = {'display_name': 'Volume-573108026'}
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            context, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'display_name': 'Volume-573108026'},
            viewable_admin_meta=True, offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_true(self, get_all):
        req = mock.MagicMock()
        context = mock.Mock()
        req.environ = {'cinder.context': context}
        req.params = {'display_name': 'Volume-573108026', 'bootable': 1}
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            context, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'display_name': 'Volume-573108026', 'bootable': True},
            viewable_admin_meta=True, offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_false(self, get_all):
        req = mock.MagicMock()
        context = mock.Mock()
        req.environ = {'cinder.context': context}
        req.params = {'display_name': 'Volume-573108026', 'bootable': 0}
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            context, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'display_name': 'Volume-573108026', 'bootable': False},
            viewable_admin_meta=True, offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_list(self, get_all):
        req = mock.MagicMock()
        context = mock.Mock()
        req.environ = {'cinder.context': context}
        req.params = {'id': "['1', '2', '3']"}
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            context, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'id': ['1', '2', '3']}, viewable_admin_meta=True,
            offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_expression(self, get_all):
        req = mock.MagicMock()
        context = mock.Mock()
        req.environ = {'cinder.context': context}
        req.params = {'name': "d-"}
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            context, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'display_name': 'd-'}, viewable_admin_meta=True, offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_status(self, get_all):
        req = mock.MagicMock()
        ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        req.environ = {'cinder.context': ctxt}
        req.params = {'status': 'available'}
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'status': 'available'}, viewable_admin_meta=True,
            offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_metadata(self, get_all):
        req = mock.MagicMock()
        ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        req.environ = {'cinder.context': ctxt}
        req.params = {'metadata': "{'fake_key': 'fake_value'}"}
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'metadata': {'fake_key': 'fake_value'}},
            viewable_admin_meta=True, offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_availability_zone(self, get_all):
        req = mock.MagicMock()
        ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        req.environ = {'cinder.context': ctxt}
        req.params = {'availability_zone': 'nova'}
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'availability_zone': 'nova'}, viewable_admin_meta=True,
            offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_invalid_filter(self, get_all):
        req = mock.MagicMock()
        ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        req.environ = {'cinder.context': ctxt}
        req.params = {'invalid_filter': 'invalid',
                      'availability_zone': 'nova'}
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'availability_zone': 'nova'}, viewable_admin_meta=True,
            offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_sort_by_name(self, get_all):
        """Name in client means display_name in database."""

        req = mock.MagicMock()
        ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        req.environ = {'cinder.context': ctxt}
        req.params = {'sort': 'name'}
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_dirs=['desc'], viewable_admin_meta=True,
            sort_keys=['display_name'], filters={}, offset=0)

    def test_get_volume_filter_options_using_config(self):
        self.override_config('query_volume_filters', ['name', 'status',
                                                      'metadata'])
        self.assertEqual(['name', 'status', 'metadata'],
                         self.controller._get_volume_filter_options())


class VolumeSerializerTest(test.TestCase):
    def _verify_volume_attachment(self, attach, tree):
        for attr in ('id', 'volume_id', 'server_id', 'device'):
            self.assertEqual(str(attach[attr]), tree.get(attr))

    def _verify_volume(self, vol, tree):
        self.assertEqual(NS + 'volume', tree.tag)

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
            created_at=timeutils.utcnow(),
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
                created_at=timeutils.utcnow(),
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
                created_at=timeutils.utcnow(),
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
        self.assertEqual(expected, request['body'])

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
        self.assertEqual(expected, request['body'])

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
        self.assertEqual(expected, request['body'])

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
                "size": "1",
                "name": "Volume-xml",
                "description": "description",
                "volume_type": "289da7f8-6440-407c-9fb4-7db01ec49164",
            },
        }
        self.assertEqual(expected, request['body'])

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
        self.assertEqual(expected, request['body'])

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
        self.assertEqual(expected, request['body'])

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
        self.assertEqual(expected, request['body'])

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
