# Copyright 2016 EMC Corporation
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

import uuid

import ddt
import mock
from oslo_utils import strutils
from oslo_utils import timeutils
import six
import webob

import cinder.api.common as common
from cinder.api.v3 import group_specs as v3_group_specs
from cinder.api.v3 import group_types as v3_group_types
from cinder.api.v3.views import group_types as views_types
from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.volume import group_types

GROUP_TYPE_MICRO_VERSION = '3.11'
IN_USE_GROUP_TYPE = fake.GROUP_TYPE3_ID


def stub_group_type(id):
    specs = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
        "key4": "value4",
        "key5": "value5"
    }
    return dict(
        id=id,
        name='group_type_%s' % six.text_type(id),
        description='group_type_desc_%s' % six.text_type(id),
        group_specs=specs,
    )


def return_group_types_get_all_types(context, filters=None, marker=None,
                                     limit=None, sort_keys=None,
                                     sort_dirs=None, offset=None,
                                     list_result=False):
    result = dict(group_type_1=stub_group_type(1),
                  group_type_2=stub_group_type(2),
                  group_type_3=stub_group_type(3)
                  )
    if list_result:
        return list(result.values())
    return result


def return_empty_group_types_get_all_types(context, filters=None, marker=None,
                                           limit=None, sort_keys=None,
                                           sort_dirs=None, offset=None,
                                           list_result=False):
    if list_result:
        return []
    return {}


def return_group_types_get_group_type(context, id):
    if id == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.GroupTypeNotFound(group_type_id=id)
    return stub_group_type(id)


def return_group_types_get_default():
    return stub_group_type(1)


def return_group_types_get_default_not_found():
    return {}


def return_group_types_with_groups_destroy(context, id):
    if id == IN_USE_GROUP_TYPE:
        raise exception.GroupTypeInUse(group_type_id=id)


@ddt.ddt
class GroupTypesApiTest(test.TestCase):

    def _create_group_type(self, group_type_name, group_specs=None,
                           is_public=True, projects=None):
        return group_types.create(self.ctxt, group_type_name, group_specs,
                                  is_public, projects).get('id')

    def setUp(self):
        super(GroupTypesApiTest, self).setUp()
        self.controller = v3_group_types.GroupTypesController()
        self.specs_controller = v3_group_specs.GroupTypeSpecsController()
        self.ctxt = context.RequestContext(user_id=fake.USER_ID,
                                           project_id=fake.PROJECT_ID,
                                           is_admin=True)
        self.user_ctxt = context.RequestContext(user_id=fake.USER2_ID,
                                                project_id=fake.PROJECT2_ID,
                                                is_admin=False)
        self.type_id1 = self._create_group_type('group_type1',
                                                {'key1': 'value1'})
        self.type_id2 = self._create_group_type('group_type2',
                                                {'key2': 'value2'})
        self.type_id3 = self._create_group_type('group_type3',
                                                {'key3': 'value3'}, False,
                                                [fake.PROJECT_ID])
        self.type_id0 = group_types.get_default_cgsnapshot_type()['id']

    @ddt.data('0', 'f', 'false', 'off', 'n', 'no', '1', 't', 'true', 'on',
              'y', 'yes')
    @mock.patch.object(group_types, "get_group_type_by_name")
    @mock.patch.object(group_types, "create")
    @mock.patch("cinder.api.openstack.wsgi.Request.cache_resource")
    @mock.patch("cinder.api.views.types.ViewBuilder.show")
    def test_create_group_type_with_valid_is_public_in_string(
            self, is_public, mock_show, mock_cache_resource,
            mock_create, mock_get):
        boolean_is_public = strutils.bool_from_string(is_public)
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID,
                                      version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt

        body = {"group_type": {"is_public": is_public, "name": "group_type1",
                               "description": None}}
        self.controller.create(req, body)
        mock_create.assert_called_once_with(
            self.ctxt, 'group_type1', {},
            boolean_is_public, description=None)

    @ddt.data(fake.GROUP_TYPE_ID, IN_USE_GROUP_TYPE)
    def test_group_type_destroy(self, grp_type_id):
        grp_type = {'id': grp_type_id, 'name': 'grp' + grp_type_id}
        self.mock_object(group_types, 'get_group_type',
                         return_value=grp_type)
        self.mock_object(group_types, 'destroy',
                         return_group_types_with_groups_destroy)
        mock_notify_info = self.mock_object(
            v3_group_types.GroupTypesController,
            '_notify_group_type_info')
        mock_notify_error = self.mock_object(
            v3_group_types.GroupTypesController,
            '_notify_group_type_error')
        req = fakes.HTTPRequest.blank('/v3/%s/group_types/%s' % (
            fake.PROJECT_ID, grp_type_id),
            version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt
        if grp_type_id == IN_USE_GROUP_TYPE:
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.controller.delete,
                              req, grp_type_id)
            mock_notify_error.assert_called_once_with(
                self.ctxt, 'group_type.delete', mock.ANY,
                group_type=grp_type)
        else:
            self.controller.delete(req, grp_type_id)
            mock_notify_info.assert_called_once_with(
                self.ctxt, 'group_type.delete', grp_type)

    def test_group_types_index(self):
        self.mock_object(group_types, 'get_all_group_types',
                         return_group_types_get_all_types)

        req = fakes.HTTPRequest.blank('/v3/%s/group_types' % fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=GROUP_TYPE_MICRO_VERSION)
        res_dict = self.controller.index(req)

        self.assertEqual(3, len(res_dict['group_types']))

        expected_names = ['group_type_1', 'group_type_2', 'group_type_3']
        actual_names = map(lambda e: e['name'], res_dict['group_types'])
        self.assertEqual(set(expected_names), set(actual_names))
        for entry in res_dict['group_types']:
            self.assertEqual('value1', entry['group_specs']['key1'])

    def test_group_types_index_no_data(self):
        self.mock_object(group_types, 'get_all_group_types',
                         return_empty_group_types_get_all_types)

        req = fakes.HTTPRequest.blank('/v3/%s/group_types' % fake.PROJECT_ID,
                                      version=GROUP_TYPE_MICRO_VERSION)
        res_dict = self.controller.index(req)

        self.assertEqual(0, len(res_dict['group_types']))

    def test_group_types_index_with_limit(self):
        req = fakes.HTTPRequest.blank('/v3/%s/group_types?limit=1' %
                                      fake.PROJECT_ID,
                                      version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(1, len(res['group_types']))
        self.assertEqual(self.type_id3, res['group_types'][0]['id'])

        expect_next_link = ('http://localhost/v3/%s/group_types?limit=1'
                            '&marker=%s' %
                            (fake.PROJECT_ID, res['group_types'][0]['id']))
        self.assertEqual(expect_next_link, res['group_type_links'][0]['href'])

    def test_group_types_index_with_offset(self):
        req = fakes.HTTPRequest.blank(
            '/v3/%s/group_types?offset=1' % fake.PROJECT_ID,
            version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(3, len(res['group_types']))

    def test_group_types_index_with_offset_out_of_range(self):
        url = '/v3/%s/group_types?offset=424366766556787' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, version=GROUP_TYPE_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_group_types_index_with_limit_and_offset(self):
        req = fakes.HTTPRequest.blank(
            '/v3/%s/group_types?limit=2&offset=1' % fake.PROJECT_ID,
            version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(2, len(res['group_types']))
        self.assertEqual(self.type_id2, res['group_types'][0]['id'])
        self.assertEqual(self.type_id1, res['group_types'][1]['id'])

    def test_group_types_index_with_limit_and_marker(self):
        req = fakes.HTTPRequest.blank('/v3/%s/group_types?limit=1'
                                      '&marker=%s' %
                                      (fake.PROJECT_ID,
                                       self.type_id2),
                                      version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(1, len(res['group_types']))
        self.assertEqual(self.type_id1, res['group_types'][0]['id'])

    def test_group_types_index_with_valid_filter(self):
        req = fakes.HTTPRequest.blank(
            '/v3/%s/group_types?is_public=True' % fake.PROJECT_ID,
            version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(4, len(res['group_types']))
        self.assertEqual(self.type_id3, res['group_types'][0]['id'])
        self.assertEqual(self.type_id2, res['group_types'][1]['id'])
        self.assertEqual(self.type_id1, res['group_types'][2]['id'])
        self.assertEqual(self.type_id0, res['group_types'][3]['id'])

    def test_group_types_index_with_invalid_filter(self):
        req = fakes.HTTPRequest.blank(
            '/v3/%s/group_types?id=%s' % (fake.PROJECT_ID, self.type_id1),
            version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(4, len(res['group_types']))

    def test_group_types_index_with_sort_keys(self):
        req = fakes.HTTPRequest.blank('/v3/%s/group_types?sort=id' %
                                      fake.PROJECT_ID,
                                      version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)
        expect_result = [self.type_id0, self.type_id1, self.type_id2,
                         self.type_id3]
        expect_result.sort(reverse=True)

        self.assertEqual(4, len(res['group_types']))
        self.assertEqual(expect_result[0], res['group_types'][0]['id'])
        self.assertEqual(expect_result[1], res['group_types'][1]['id'])
        self.assertEqual(expect_result[2], res['group_types'][2]['id'])
        self.assertEqual(expect_result[3], res['group_types'][3]['id'])

    def test_group_types_index_with_sort_and_limit(self):
        req = fakes.HTTPRequest.blank(
            '/v3/%s/group_types?sort=id&limit=2' % fake.PROJECT_ID,
            version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)
        expect_result = [self.type_id0, self.type_id1, self.type_id2,
                         self.type_id3]
        expect_result.sort(reverse=True)

        self.assertEqual(2, len(res['group_types']))
        self.assertEqual(expect_result[0], res['group_types'][0]['id'])
        self.assertEqual(expect_result[1], res['group_types'][1]['id'])

    def test_group_types_index_with_sort_keys_and_sort_dirs(self):
        req = fakes.HTTPRequest.blank(
            '/v3/%s/group_types?sort=id:asc' % fake.PROJECT_ID,
            version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)
        expect_result = [self.type_id0, self.type_id1, self.type_id2,
                         self.type_id3]
        expect_result.sort()

        self.assertEqual(4, len(res['group_types']))
        self.assertEqual(expect_result[0], res['group_types'][0]['id'])
        self.assertEqual(expect_result[1], res['group_types'][1]['id'])
        self.assertEqual(expect_result[2], res['group_types'][2]['id'])
        self.assertEqual(expect_result[3], res['group_types'][3]['id'])

    @ddt.data('0', 'f', 'false', 'off', 'n', 'no', '1', 't', 'true', 'on',
              'y', 'yes')
    @mock.patch.object(group_types, "get_group_type")
    @mock.patch.object(group_types, "update")
    @mock.patch("cinder.api.openstack.wsgi.Request.cache_resource")
    @mock.patch("cinder.api.views.types.ViewBuilder.show")
    def test_update_group_type_with_valid_is_public_in_string(
            self, is_public, mock_show, mock_cache_resource,
            mock_update, mock_get):
        boolean_is_public = strutils.bool_from_string(is_public)
        type_id = six.text_type(uuid.uuid4())
        req = fakes.HTTPRequest.blank(
            '/v3/%s/types/%s' % (fake.PROJECT_ID, type_id),
            version=GROUP_TYPE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt
        body = {"group_type": {"is_public": is_public, "name": "group_type1"}}
        self.controller.update(req, type_id, body)
        mock_update.assert_called_once_with(
            self.ctxt, type_id, 'group_type1', None,
            is_public=boolean_is_public)

    def test_group_types_show(self):
        self.mock_object(group_types, 'get_group_type',
                         return_group_types_get_group_type)

        type_id = six.text_type(uuid.uuid4())
        req = fakes.HTTPRequest.blank('/v3/%s/group_types/' % fake.PROJECT_ID
                                      + type_id,
                                      version=GROUP_TYPE_MICRO_VERSION)
        res_dict = self.controller.show(req, type_id)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(type_id, res_dict['group_type']['id'])
        type_name = 'group_type_' + type_id
        self.assertEqual(type_name, res_dict['group_type']['name'])

    def test_group_types_show_pre_microversion(self):
        self.mock_object(group_types, 'get_group_type',
                         return_group_types_get_group_type)

        type_id = six.text_type(uuid.uuid4())
        req = fakes.HTTPRequest.blank('/v3/%s/group_types/' % fake.PROJECT_ID
                                      + type_id,
                                      version='3.5')

        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.show, req, type_id)

    def test_group_types_show_not_found(self):
        self.mock_object(group_types, 'get_group_type',
                         return_group_types_get_group_type)

        req = fakes.HTTPRequest.blank('/v3/%s/group_types/%s' %
                                      (fake.PROJECT_ID,
                                       fake.WILL_NOT_BE_FOUND_ID),
                                      version=GROUP_TYPE_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, fake.WILL_NOT_BE_FOUND_ID)

    def test_get_default(self):
        self.mock_object(group_types, 'get_default_group_type',
                         return_group_types_get_default)
        req = fakes.HTTPRequest.blank('/v3/%s/group_types/default' %
                                      fake.PROJECT_ID,
                                      version=GROUP_TYPE_MICRO_VERSION)
        req.method = 'GET'
        res_dict = self.controller.show(req, 'default')
        self.assertEqual(1, len(res_dict))
        self.assertEqual('group_type_1', res_dict['group_type']['name'])
        self.assertEqual('group_type_desc_1',
                         res_dict['group_type']['description'])

    def test_get_default_not_found(self):
        self.mock_object(group_types, 'get_default_group_type',
                         return_group_types_get_default_not_found)
        req = fakes.HTTPRequest.blank('/v3/%s/group_types/default' %
                                      fake.PROJECT_ID,
                                      version=GROUP_TYPE_MICRO_VERSION)
        req.method = 'GET'

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 'default')

    def test_view_builder_show(self):
        view_builder = views_types.ViewBuilder()

        now = timeutils.utcnow().isoformat()
        raw_group_type = dict(
            name='new_type',
            description='new_type_desc',
            is_public=True,
            deleted=False,
            created_at=now,
            updated_at=now,
            group_specs={},
            deleted_at=None,
            id=42,
        )

        request = fakes.HTTPRequest.blank("/v3",
                                          version=GROUP_TYPE_MICRO_VERSION)
        output = view_builder.show(request, raw_group_type)

        self.assertIn('group_type', output)
        expected_group_type = dict(
            name='new_type',
            description='new_type_desc',
            is_public=True,
            id=42,
        )
        self.assertDictEqual(expected_group_type, output['group_type'])

    def test_view_builder_show_admin(self):
        view_builder = views_types.ViewBuilder()

        now = timeutils.utcnow().isoformat()
        raw_group_type = dict(
            name='new_type',
            description='new_type_desc',
            is_public=True,
            deleted=False,
            created_at=now,
            updated_at=now,
            group_specs={},
            deleted_at=None,
            id=42,
        )

        request = fakes.HTTPRequest.blank("/v3", use_admin_context=True,
                                          version=GROUP_TYPE_MICRO_VERSION)
        output = view_builder.show(request, raw_group_type)

        self.assertIn('group_type', output)
        expected_group_type = dict(
            name='new_type',
            description='new_type_desc',
            is_public=True,
            group_specs={},
            id=42,
        )
        self.assertDictEqual(expected_group_type, output['group_type'])

    def __test_view_builder_show_qos_specs_id_policy(self):
        with mock.patch.object(common,
                               'validate_policy',
                               side_effect=[False, True]):
            view_builder = views_types.ViewBuilder()
            now = timeutils.utcnow().isoformat()
            raw_group_type = dict(
                name='new_type',
                description='new_type_desc',
                is_public=True,
                deleted=False,
                created_at=now,
                updated_at=now,
                deleted_at=None,
                id=42,
            )

            request = fakes.HTTPRequest.blank("/v3",
                                              version=GROUP_TYPE_MICRO_VERSION)
            output = view_builder.show(request, raw_group_type)

            self.assertIn('group_type', output)
            expected_group_type = dict(
                name='new_type',
                description='new_type_desc',
                is_public=True,
                id=42,
            )
            self.assertDictEqual(expected_group_type, output['group_type'])

    def test_view_builder_show_group_specs_policy(self):
        with mock.patch.object(common,
                               'validate_policy',
                               side_effect=[True, False]):
            view_builder = views_types.ViewBuilder()
            now = timeutils.utcnow().isoformat()
            raw_group_type = dict(
                name='new_type',
                description='new_type_desc',
                is_public=True,
                deleted=False,
                created_at=now,
                updated_at=now,
                group_specs={},
                deleted_at=None,
                id=42,
            )

            request = fakes.HTTPRequest.blank("/v3",
                                              version=GROUP_TYPE_MICRO_VERSION)
            output = view_builder.show(request, raw_group_type)

            self.assertIn('group_type', output)
            expected_group_type = dict(
                name='new_type',
                description='new_type_desc',
                group_specs={},
                is_public=True,
                id=42,
            )
            self.assertDictEqual(expected_group_type, output['group_type'])

    def test_view_builder_show_pass_all_policy(self):
        with mock.patch.object(common,
                               'validate_policy',
                               side_effect=[True, True]):
            view_builder = views_types.ViewBuilder()
            now = timeutils.utcnow().isoformat()
            raw_group_type = dict(
                name='new_type',
                description='new_type_desc',
                is_public=True,
                deleted=False,
                created_at=now,
                updated_at=now,
                group_specs={},
                deleted_at=None,
                id=42,
            )

            request = fakes.HTTPRequest.blank("/v3",
                                              version=GROUP_TYPE_MICRO_VERSION)
            output = view_builder.show(request, raw_group_type)

            self.assertIn('group_type', output)
            expected_group_type = dict(
                name='new_type',
                description='new_type_desc',
                group_specs={},
                is_public=True,
                id=42,
            )
            self.assertDictEqual(expected_group_type, output['group_type'])

    def test_view_builder_list(self):
        view_builder = views_types.ViewBuilder()

        now = timeutils.utcnow().isoformat()
        raw_group_types = []
        for i in range(0, 10):
            raw_group_types.append(
                dict(
                    name='new_type',
                    description='new_type_desc',
                    is_public=True,
                    deleted=False,
                    created_at=now,
                    updated_at=now,
                    group_specs={},
                    deleted_at=None,
                    id=42 + i
                )
            )

        request = fakes.HTTPRequest.blank("/v3",
                                          version=GROUP_TYPE_MICRO_VERSION)
        output = view_builder.index(request, raw_group_types)

        self.assertIn('group_types', output)
        for i in range(0, 10):
            expected_group_type = dict(
                name='new_type',
                description='new_type_desc',
                is_public=True,
                id=42 + i
            )
            self.assertDictEqual(expected_group_type,
                                 output['group_types'][i])

    def test_view_builder_list_admin(self):
        view_builder = views_types.ViewBuilder()

        now = timeutils.utcnow().isoformat()
        raw_group_types = []
        for i in range(0, 10):
            raw_group_types.append(
                dict(
                    name='new_type',
                    description='new_type_desc',
                    is_public=True,
                    deleted=False,
                    created_at=now,
                    updated_at=now,
                    group_specs={},
                    deleted_at=None,
                    id=42 + i
                )
            )

        request = fakes.HTTPRequest.blank("/v3", use_admin_context=True,
                                          version=GROUP_TYPE_MICRO_VERSION)
        output = view_builder.index(request, raw_group_types)

        self.assertIn('group_types', output)
        for i in range(0, 10):
            expected_group_type = dict(
                name='new_type',
                description='new_type_desc',
                is_public=True,
                group_specs={},
                id=42 + i
            )
            self.assertDictEqual(expected_group_type,
                                 output['group_types'][i])

    def test_check_policy(self):
        self.controller._check_policy(self.ctxt)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller._check_policy,
                          self.user_ctxt)

        self.specs_controller._check_policy(self.ctxt)

        self.assertRaises(exception.PolicyNotAuthorized,
                          self.specs_controller._check_policy,
                          self.user_ctxt)
