# Copyright 2011 OpenStack Foundation
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

from unittest import mock

import ddt
from oslo_utils import strutils
import webob

from cinder.api.contrib import types_manage
from cinder import context
from cinder import exception
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.volume import volume_types

DEFAULT_VOLUME_TYPE = fake.VOLUME_TYPE_ID
IN_USE_VOLUME_TYPE = fake.VOLUME_TYPE2_ID
UPDATE_DESC_ONLY_TYPE = fake.VOLUME_TYPE3_ID
UPDATE_NAME_ONLY_TYPE = fake.VOLUME_TYPE4_ID
UPDATE_NAME_AFTER_DELETE_TYPE = fake.VOLUME_TYPE5_ID
NOT_FOUND_VOLUME_TYPE = fake.WILL_NOT_BE_FOUND_ID


def fake_volume_type(id):
    specs = {"key1": "value1",
             "key2": "value2",
             "key3": "value3",
             "key4": "value4",
             "key5": "value5"}
    return dict(id=id,
                name='vol_type_%s' % id,
                description='vol_type_desc_%s' % id,
                extra_specs=specs)


def fake_volume_type_updated(id, is_public=True):
    return dict(id=id,
                name='vol_type_%s_%s' % (id, id),
                is_public=is_public,
                description='vol_type_desc_%s_%s' % (
                    id, id))


def fake_volume_type_updated_desc_only(id):
    return dict(id=id,
                name='vol_type_%s' % id,
                description='vol_type_desc_%s_%s' % (
                    id, id))


def return_volume_types_get_volume_type(context, id):
    if id == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.VolumeTypeNotFound(volume_type_id=id)
    return fake_volume_type(id)


def return_volume_types_destroy(context, name):
    if name == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    pass


def return_volume_types_with_volumes_destroy(context, id):
    if id == IN_USE_VOLUME_TYPE:
        raise exception.VolumeTypeInUse(volume_type_id=id)
    pass


def return_volume_types_create(context,
                               name,
                               specs,
                               is_public,
                               description):
    pass


def return_volume_types_create_duplicate_type(context,
                                              name,
                                              specs,
                                              is_public,
                                              description):
    raise exception.VolumeTypeExists(id=name)


def fake_volume_type_updated_name_only(id):
    return dict(id=id,
                name='vol_type_%s_%s' % (id, id),
                description='vol_type_desc_%s' % id)


def fake_volume_type_updated_name_after_delete(id):
    return dict(id=id,
                name='vol_type_%s' % id,
                description='vol_type_desc_%s' % id)


def return_volume_types_get_volume_type_updated(id, is_public=True):
    if id == NOT_FOUND_VOLUME_TYPE:
        raise exception.VolumeTypeNotFound(volume_type_id=id)
    if id == UPDATE_DESC_ONLY_TYPE:
        return fake_volume_type_updated_desc_only(id)
    if id == UPDATE_NAME_ONLY_TYPE:
        return fake_volume_type_updated_name_only(id)
    if id == UPDATE_NAME_AFTER_DELETE_TYPE:
        return fake_volume_type_updated_name_after_delete(id)

    # anything else
    return fake_volume_type_updated(id, is_public=is_public)


def return_volume_types_get_by_name(context, name):
    if name == NOT_FOUND_VOLUME_TYPE:
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    return fake_volume_type(name.split("_")[2])


def return_volume_types_get_default():
    return fake_volume_type(DEFAULT_VOLUME_TYPE)


def return_volume_types_get_default_not_found():
    return {}


@ddt.ddt
class VolumeTypesManageApiTest(test.TestCase):
    def setUp(self):
        super(VolumeTypesManageApiTest, self).setUp()
        self.flags(host='fake')
        self.controller = types_manage.VolumeTypesManageController()
        """to reset notifier drivers left over from other api/contrib tests"""

    def test_volume_types_delete(self):
        self.mock_object(volume_types, 'get_volume_type',
                         return_volume_types_get_volume_type)
        self.mock_object(volume_types, 'destroy',
                         return_volume_types_destroy)

        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
            use_admin_context=True)
        self.assertEqual(0, len(self.notifier.notifications))
        self.controller._delete(req, DEFAULT_VOLUME_TYPE)
        self.assertEqual(1, len(self.notifier.notifications))

    def test_volume_types_delete_not_found(self):
        self.mock_object(volume_types, 'get_volume_type',
                         return_volume_types_get_volume_type)
        self.mock_object(volume_types, 'destroy',
                         return_volume_types_destroy)

        self.assertEqual(0, len(self.notifier.notifications))
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, NOT_FOUND_VOLUME_TYPE),
            use_admin_context=True)
        self.assertRaises(exception.VolumeTypeNotFound,
                          self.controller._delete, req, NOT_FOUND_VOLUME_TYPE)
        self.assertEqual(1, len(self.notifier.notifications))

    def test_volume_types_with_volumes_destroy(self):
        self.mock_object(volume_types, 'get_volume_type',
                         return_volume_types_get_volume_type)
        self.mock_object(volume_types, 'destroy',
                         return_volume_types_with_volumes_destroy)
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
            use_admin_context=True)
        self.assertEqual(0, len(self.notifier.notifications))
        self.controller._delete(req, DEFAULT_VOLUME_TYPE)
        self.assertEqual(1, len(self.notifier.notifications))

    @mock.patch('cinder.volume.volume_types.destroy')
    @mock.patch('cinder.volume.volume_types.get_volume_type')
    @mock.patch('cinder.policy.authorize')
    def test_volume_types_delete_with_non_admin(self, mock_policy_authorize,
                                                mock_get, mock_destroy):

        # allow policy authorized user to delete type
        mock_policy_authorize.return_value = None
        mock_get.return_value = \
            {'extra_specs': {"key1": "value1"},
             'id': DEFAULT_VOLUME_TYPE,
             'name': 'vol_type_1',
             'description': 'vol_type_desc_%s' % DEFAULT_VOLUME_TYPE}
        mock_destroy.side_effect = return_volume_types_destroy

        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' %
                                      (fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
                                      use_admin_context=False)
        self.assertEqual(0, len(self.notifier.notifications))
        self.controller._delete(req, DEFAULT_VOLUME_TYPE)
        self.assertEqual(1, len(self.notifier.notifications))
        # non policy authorized user fails to delete type
        mock_policy_authorize.side_effect = (
            exception.PolicyNotAuthorized(action='type_delete'))
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller._delete,
                          req, DEFAULT_VOLUME_TYPE)

    def test_create(self):
        self.mock_object(volume_types, 'create',
                         return_volume_types_create)
        self.mock_object(volume_types, 'get_volume_type_by_name',
                         return_volume_types_get_by_name)

        body = {"volume_type": {"name": "vol_type_1",
                                "os-volume-type-access:is_public": True,
                                "extra_specs": {"key1": "value1"}}}
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID,
                                      use_admin_context=True)

        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller._create(req, body=body)

        self.assertEqual(1, len(self.notifier.notifications))
        id = res_dict['volume_type']['id']
        self._check_test_results(res_dict, {
            'expected_name': 'vol_type_1',
            'expected_desc': 'vol_type_desc_%s' % id})

    @mock.patch('cinder.volume.volume_types.create')
    @mock.patch('cinder.volume.volume_types.get_volume_type_by_name')
    def test_create_with_description_of_zero_length(
            self, mock_get_volume_type_by_name, mock_create_type):
        mock_get_volume_type_by_name.return_value = \
            {'extra_specs': {"key1": "value1"},
             'id': DEFAULT_VOLUME_TYPE,
             'name': 'vol_type_1',
             'description': ''}

        type_description = ""
        body = {"volume_type": {"name": "vol_type_1",
                                "description": type_description,
                                "extra_specs": {"key1": "value1"}}}
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID,
                                      use_admin_context=True)

        res_dict = self.controller._create(req, body=body)

        self._check_test_results(res_dict, {
            'expected_name': 'vol_type_1', 'expected_desc': ''})

    def test_create_type_with_name_too_long(self):
        type_name = 'a' * 256
        body = {"volume_type": {"name": type_name,
                                "extra_specs": {"key1": "value1"}}}
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID)
        self.assertRaises(exception.ValidationError,
                          self.controller._create, req, body=body)

    def test_create_type_with_description_too_long(self):
        type_description = 'a' * 256
        body = {"volume_type": {"name": "vol_type_1",
                                "description": type_description,
                                "extra_specs": {"key1": "value1"}}}
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID)
        self.assertRaises(exception.ValidationError,
                          self.controller._create, req, body=body)

    def test_create_duplicate_type_fail(self):
        self.mock_object(volume_types, 'create',
                         return_volume_types_create_duplicate_type)
        self.mock_object(volume_types, 'get_volume_type_by_name',
                         return_volume_types_get_by_name)

        body = {"volume_type": {"name": "vol_type_1",
                                "extra_specs": {"key1": "value1"}}}
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID,
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._create, req, body=body)

    def test_create_type_with_invalid_is_public(self):
        body = {"volume_type": {"name": "vol_type_1",
                                "os-volume-type-access:is_public": "fake",
                                "description": "test description",
                                "extra_specs": {"key1": "value1"}}}
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID)
        self.assertRaises(exception.ValidationError,
                          self.controller._create, req, body=body)

    @ddt.data('0', 'f', 'false', 'off', 'n', 'no', '1', 't', 'true', 'on',
              'y', 'yes')
    @mock.patch.object(volume_types, "get_volume_type_by_name")
    @mock.patch.object(volume_types, "create")
    @mock.patch("cinder.api.openstack.wsgi.Request.cache_resource")
    @mock.patch("cinder.api.views.types.ViewBuilder.show")
    def test_create_type_with_valid_is_public_in_string(
            self, is_public, mock_show, mock_cache_resource,
            mock_create, mock_get):
        boolean_is_public = strutils.bool_from_string(is_public)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        body = {"volume_type": {"name": "vol_type_1",
                                "os-volume-type-access:is_public":
                                    is_public,
                                "extra_specs": {"key1": "value1"}}}
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID)
        req.environ['cinder.context'] = ctxt
        self.controller._create(req, body=body)
        mock_create.assert_called_once_with(
            ctxt, 'vol_type_1', {'key1': 'value1'},
            boolean_is_public, description=None)

    def _create_volume_type_bad_body(self, body):
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID)
        req.method = 'POST'
        self.assertRaises(exception.ValidationError,
                          self.controller._create, req, body=body)

    def test_create_no_body(self):
        self._create_volume_type_bad_body(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._create_volume_type_bad_body(body=body)

    def test_create_malformed_entity(self):
        body = {'volume_type': 'string'}
        self._create_volume_type_bad_body(body=body)

    @mock.patch('cinder.volume.volume_types.create')
    @mock.patch('cinder.volume.volume_types.get_volume_type_by_name')
    @mock.patch('cinder.policy.authorize')
    def test_create_with_none_admin(self, mock_policy_authorize,
                                    mock_get_volume_type_by_name,
                                    mock_create_type):

        # allow policy authorized user to create type
        mock_policy_authorize.return_value = None
        mock_get_volume_type_by_name.return_value = \
            {'extra_specs': {"key1": "value1"},
             'id': DEFAULT_VOLUME_TYPE,
             'name': 'vol_type_1',
             'description': 'vol_type_desc_1'}

        body = {"volume_type": {"name": "vol_type_1",
                                "os-volume-type-access:is_public": True,
                                "extra_specs": {"key1": "value1"}}}
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID,
                                      use_admin_context=False)

        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller._create(req, body=body)

        self.assertEqual(1, len(self.notifier.notifications))
        self._check_test_results(res_dict, {
            'expected_name': 'vol_type_1', 'expected_desc': 'vol_type_desc_1'})

        # non policy authorized user fails to create type
        mock_policy_authorize.side_effect = (
            exception.PolicyNotAuthorized(action='type_create'))
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller._create,
                          req, body=body)

    @ddt.data({'a' * 256: 'a'},
              {'a': 'a' * 256},
              {'': 'a'},
              'foo',
              None)
    def test_create_type_with_invalid_extra_specs(self, value):
        body = {"volume_type": {"name": "vol_type_1",
                                "os-volume-type-access:is_public": False,
                                "description": "test description"}}
        body['volume_type']['extra_specs'] = value
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID)
        self.assertRaises(exception.ValidationError,
                          self.controller._create, req, body=body)

    @mock.patch('cinder.volume.volume_types.update')
    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_update(self, mock_get, mock_update):
        mock_get.return_value = return_volume_types_get_volume_type_updated(
            DEFAULT_VOLUME_TYPE, is_public=False)
        body = {"volume_type": {"is_public": False}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
            use_admin_context=True)
        req.method = 'PUT'

        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller._update(req, DEFAULT_VOLUME_TYPE, body=body)
        self.assertEqual(1, len(self.notifier.notifications))
        self._check_test_results(
            res_dict,
            {'expected_desc': 'vol_type_desc_%s_%s' %
                              (DEFAULT_VOLUME_TYPE, DEFAULT_VOLUME_TYPE),
             'expected_name': 'vol_type_%s_%s' %
                              (DEFAULT_VOLUME_TYPE, DEFAULT_VOLUME_TYPE),
             'is_public': False})

    @ddt.data('0', 'f', 'false', 'off', 'n', 'no', '1', 't', 'true', 'on',
              'y', 'yes')
    @mock.patch('cinder.volume.volume_types.update')
    @mock.patch('cinder.volume.volume_types.get_volume_type')
    @mock.patch("cinder.api.openstack.wsgi.Request.cache_resource")
    @mock.patch("cinder.api.views.types.ViewBuilder.show")
    def test_update_with_valid_is_public_in_string(
            self, is_public, mock_show, mock_cache_resource,
            mock_get, mock_update):
        body = {"volume_type": {"is_public": is_public}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
            use_admin_context=True)
        req.method = 'PUT'
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = ctxt
        boolean_is_public = strutils.bool_from_string(is_public)

        self.controller._update(req, DEFAULT_VOLUME_TYPE, body=body)
        mock_update.assert_called_once_with(
            ctxt, DEFAULT_VOLUME_TYPE, None, None,
            is_public=boolean_is_public)

    @mock.patch('cinder.volume.volume_types.update')
    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_update_type_with_description_having_length_zero(
            self, mock_get_volume_type, mock_type_update):

        mock_get_volume_type.return_value = \
            {'id': DEFAULT_VOLUME_TYPE, 'name': 'vol_type_1',
             'description': ''}

        type_description = ""
        body = {"volume_type": {"description": type_description}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
            use_admin_context=True)
        req.method = 'PUT'
        resp = self.controller._update(req, DEFAULT_VOLUME_TYPE, body=body)
        self._check_test_results(resp,
                                 {'expected_desc': '',
                                  'expected_name': 'vol_type_1'})

    def test_update_type_with_name_too_long(self):
        type_name = 'a' * 256
        body = {"volume_type": {"name": type_name,
                                "description": ""}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE))
        req.method = 'PUT'
        self.assertRaises(exception.ValidationError,
                          self.controller._update, req,
                          DEFAULT_VOLUME_TYPE, body=body)

    def test_update_type_with_description_too_long(self):
        type_description = 'a' * 256
        body = {"volume_type": {"description": type_description}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE))
        req.method = 'PUT'
        self.assertRaises(exception.ValidationError,
                          self.controller._update, req,
                          DEFAULT_VOLUME_TYPE, body=body)

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    @mock.patch('cinder.volume.volume_types.update')
    def test_update_non_exist(self, mock_update, mock_get_volume_type):
        mock_get_volume_type.side_effect = exception.VolumeTypeNotFound(
            volume_type_id=NOT_FOUND_VOLUME_TYPE)
        body = {"volume_type": {"name": "vol_type_1_1",
                                "description": "vol_type_desc_1_1"}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, NOT_FOUND_VOLUME_TYPE),
            use_admin_context=True)
        req.method = 'PUT'

        self.assertEqual(0, len(self.notifier.notifications))
        self.assertRaises(exception.VolumeTypeNotFound,
                          self.controller._update, req,
                          NOT_FOUND_VOLUME_TYPE, body=body)
        self.assertEqual(1, len(self.notifier.notifications))

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    @mock.patch('cinder.volume.volume_types.update')
    def test_update_db_fail(self, mock_update, mock_get_volume_type):
        mock_update.side_effect = exception.VolumeTypeUpdateFailed(
            id=DEFAULT_VOLUME_TYPE)
        mock_get_volume_type.return_value = fake_volume_type(
            DEFAULT_VOLUME_TYPE)

        body = {"volume_type": {"name": "vol_type_1_1",
                                "description": "vol_type_desc_1_1"}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
            use_admin_context=True)
        req.method = 'PUT'

        self.assertEqual(0, len(self.notifier.notifications))
        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller._update, req,
                          DEFAULT_VOLUME_TYPE, body=body)
        self.assertEqual(1, len(self.notifier.notifications))

    def test_update_no_name_no_description(self):
        body = {"volume_type": {}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
            use_admin_context=True)
        req.method = 'PUT'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._update, req,
                          DEFAULT_VOLUME_TYPE, body=body)

    def test_update_empty_name(self):
        body = {"volume_type": {"name": "  ",
                                "description": "something"}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
            use_admin_context=True)
        req.method = 'PUT'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._update, req,
                          DEFAULT_VOLUME_TYPE, body=body)

    @mock.patch('cinder.volume.volume_types.get_volume_type')
    @mock.patch('cinder.db.volume_type_update')
    @mock.patch('cinder.quota.VolumeTypeQuotaEngine.'
                'update_quota_resource')
    def test_update_only_name(self, mock_update_quota,
                              mock_update, mock_get):
        mock_get.return_value = return_volume_types_get_volume_type_updated(
            UPDATE_NAME_ONLY_TYPE)

        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        name = "vol_type_%s" % UPDATE_NAME_ONLY_TYPE
        updated_name = "%s_%s" % (name, UPDATE_NAME_ONLY_TYPE)
        desc = "vol_type_desc_%s" % UPDATE_NAME_ONLY_TYPE
        body = {"volume_type": {"name": name}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' %
                                      (fake.PROJECT_ID, UPDATE_NAME_ONLY_TYPE))
        req.method = 'PUT'
        req.environ['cinder.context'] = ctxt

        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller._update(req, UPDATE_NAME_ONLY_TYPE,
                                           body=body)
        self.assertEqual(1, len(self.notifier.notifications))
        mock_update_quota.assert_called_once_with(ctxt, updated_name, name)
        self._check_test_results(res_dict,
                                 {'expected_name': updated_name,
                                  'expected_desc': desc})

    @mock.patch('cinder.volume.volume_types.update')
    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_update_only_description(self, mock_get, mock_update):
        mock_get.return_value = return_volume_types_get_volume_type_updated(
            UPDATE_DESC_ONLY_TYPE)
        name = "vol_type_%s" % UPDATE_DESC_ONLY_TYPE
        desc = "vol_type_desc_%s" % UPDATE_DESC_ONLY_TYPE
        updated_desc = "%s_%s" % (desc, UPDATE_DESC_ONLY_TYPE)
        body = {"volume_type": {"description": updated_desc}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, UPDATE_DESC_ONLY_TYPE),
            use_admin_context=True)
        req.method = 'PUT'

        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller._update(req, UPDATE_DESC_ONLY_TYPE,
                                           body=body)
        self.assertEqual(1, len(self.notifier.notifications))
        self._check_test_results(res_dict,
                                 {'expected_name': name,
                                  'expected_desc': updated_desc})

    @mock.patch('cinder.volume.volume_types.update')
    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_update_only_is_public(self, mock_get, mock_update):
        is_public = False
        mock_get.return_value = return_volume_types_get_volume_type_updated(
            DEFAULT_VOLUME_TYPE, is_public=is_public)
        name = "vol_type_%s" % DEFAULT_VOLUME_TYPE
        updated_name = '%s_%s' % (name, DEFAULT_VOLUME_TYPE)
        desc = "vol_type_desc_%s" % DEFAULT_VOLUME_TYPE
        updated_desc = "%s_%s" % (desc, DEFAULT_VOLUME_TYPE)
        body = {"volume_type": {"is_public": is_public}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
            use_admin_context=True)
        req.method = 'PUT'

        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller._update(req, DEFAULT_VOLUME_TYPE, body=body)
        self.assertEqual(1, len(self.notifier.notifications))
        self._check_test_results(res_dict,
                                 {'expected_name': updated_name,
                                  'expected_desc': updated_desc,
                                  'is_public': False})

    def test_update_invalid_is_public(self):
        body = {"volume_type": {"name": "test",
                                "description": "something",
                                "is_public": "fake"}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE))
        req.method = 'PUT'

        self.assertRaises(exception.ValidationError,
                          self.controller._update, req,
                          DEFAULT_VOLUME_TYPE, body=body)

    @mock.patch('cinder.volume.volume_types.update')
    @mock.patch('cinder.volume.volume_types.get_volume_type')
    def test_rename_existing_name(self, mock_get, mock_update):
        id = UPDATE_NAME_AFTER_DELETE_TYPE
        name = "vol_type_%s" % id
        updated_name = "%s_%s" % (name, id)
        desc = "vol_type_desc_%s" % id
        mock_update.side_effect = exception.VolumeTypeExists(
            id=id, name=name)
        mock_get.return_value = return_volume_types_get_volume_type_updated(
            UPDATE_NAME_AFTER_DELETE_TYPE)
        # first attempt fail
        body = {"volume_type": {"name": name}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, UPDATE_NAME_AFTER_DELETE_TYPE),
            use_admin_context=True)
        req.method = 'PUT'

        self.assertEqual(0, len(self.notifier.notifications))
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._update, req,
                          UPDATE_NAME_AFTER_DELETE_TYPE, body=body)

        self.assertEqual(1, len(self.notifier.notifications))

        # delete
        self.notifier.reset()
        self.mock_object(volume_types, 'destroy',
                         return_volume_types_destroy)
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, UPDATE_NAME_AFTER_DELETE_TYPE),
            use_admin_context=True)
        self.assertEqual(0, len(self.notifier.notifications))
        self.controller._delete(req, UPDATE_NAME_AFTER_DELETE_TYPE)
        self.assertEqual(1, len(self.notifier.notifications))

        # update again
        mock_update.side_effect = mock.MagicMock()
        body = {"volume_type": {"name": updated_name}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, UPDATE_NAME_AFTER_DELETE_TYPE),
            use_admin_context=True)
        req.method = 'PUT'

        self.notifier.reset()
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller._update(req, UPDATE_NAME_AFTER_DELETE_TYPE,
                                           body=body)
        self._check_test_results(res_dict,
                                 {'expected_name': name,
                                  'expected_desc': desc})
        self.assertEqual(1, len(self.notifier.notifications))

    @mock.patch('cinder.volume.volume_types.update')
    @mock.patch('cinder.volume.volume_types.get_volume_type')
    @mock.patch('cinder.policy.authorize')
    def test_update_with_non_admin(self, mock_policy_authorize, mock_get,
                                   mock_update):

        # allow policy authorized user to update type
        mock_policy_authorize.return_value = None
        mock_get.return_value = return_volume_types_get_volume_type_updated(
            DEFAULT_VOLUME_TYPE, is_public=False)
        name = "vol_type_%s" % DEFAULT_VOLUME_TYPE
        updated_name = "%s_%s" % (name, DEFAULT_VOLUME_TYPE)
        desc = "vol_type_desc_%s" % DEFAULT_VOLUME_TYPE
        updated_desc = "%s_%s" % (desc, DEFAULT_VOLUME_TYPE)
        body = {"volume_type": {"name": updated_name,
                                "description": updated_desc,
                                "is_public": False}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
            use_admin_context=False)

        req.method = 'PUT'

        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller._update(req, DEFAULT_VOLUME_TYPE, body=body)
        self.assertEqual(1, len(self.notifier.notifications))
        self._check_test_results(res_dict,
                                 {'expected_desc': updated_desc,
                                  'expected_name': updated_name,
                                  'is_public': False})

        # non policy authorized user fails to update type
        mock_policy_authorize.side_effect = (
            exception.PolicyNotAuthorized(action='type_update'))
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller._update,
                          req, DEFAULT_VOLUME_TYPE, body=body)

    def _check_test_results(self, results, expected_results):
        self.assertEqual(1, len(results))
        self.assertEqual(expected_results['expected_desc'],
                         results['volume_type']['description'])
        if expected_results.get('expected_name'):
            self.assertEqual(expected_results['expected_name'],
                             results['volume_type']['name'])
        if expected_results.get('is_public') is not None:
            self.assertEqual(expected_results['is_public'],
                             results['volume_type']['is_public'])

    def test_update_with_name_null(self):
        body = {"volume_type": {"name": None}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE),
            use_admin_context=True)
        req.method = 'PUT'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._update, req,
                          DEFAULT_VOLUME_TYPE, body=body)

    @ddt.data({"volume_type": {"name": None, "description": "description"}},
              {"volume_type": {"name": None, "is_public": True}},
              {"volume_type": {"description": "description",
                               "is_public": True}})
    def test_update_volume_type(self, body):
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s' % (
            fake.PROJECT_ID, DEFAULT_VOLUME_TYPE))
        req.method = 'PUT'
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = ctxt
        volume_type_1 = volume_types.create(ctxt, 'volume_type')
        res = self.controller._update(req, volume_type_1.get('id'), body=body)

        expected_name = body['volume_type'].get('name')
        if expected_name is not None:
            self.assertEqual(expected_name, res['volume_type']['name'])

        expected_is_public = body['volume_type'].get('is_public')
        if expected_is_public is not None:
            self.assertEqual(expected_is_public,
                             res['volume_type']['is_public'])

        self.assertEqual(body['volume_type'].get('description'),
                         res['volume_type']['description'])
