# Copyright 2011 OpenStack Foundation
# aLL Rights Reserved.
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

from lxml import etree
import mock
from oslo_utils import timeutils
import six
import webob

import cinder.api.common as common
from cinder.api.v2 import types
from cinder.api.v2.views import types as views_types
from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.volume import volume_types


def stub_volume_type(id):
    specs = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
        "key4": "value4",
        "key5": "value5"
    }
    return dict(
        id=id,
        name='vol_type_%s' % six.text_type(id),
        description='vol_type_desc_%s' % six.text_type(id),
        extra_specs=specs,
    )


def return_volume_types_get_all_types(context, filters=None, marker=None,
                                      limit=None, sort_keys=None,
                                      sort_dirs=None, offset=None,
                                      list_result=False):
    result = dict(vol_type_1=stub_volume_type(1),
                  vol_type_2=stub_volume_type(2),
                  vol_type_3=stub_volume_type(3)
                  )
    if list_result:
        return list(result.values())
    return result


def return_empty_volume_types_get_all_types(context, filters=None, marker=None,
                                            limit=None, sort_keys=None,
                                            sort_dirs=None, offset=None,
                                            list_result=False):
    if list_result:
        return []
    return {}


def return_volume_types_get_volume_type(context, id):
    if id == "777":
        raise exception.VolumeTypeNotFound(volume_type_id=id)
    return stub_volume_type(id)


def return_volume_types_get_by_name(context, name):
    if name == "777":
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    return stub_volume_type(int(name.split("_")[2]))


def return_volume_types_get_default():
    return stub_volume_type(1)


def return_volume_types_get_default_not_found():
    return {}


class VolumeTypesApiTest(test.TestCase):

    def _create_volume_type(self, volume_type_name, extra_specs=None,
                            is_public=True, projects=None):
        return volume_types.create(self.ctxt, volume_type_name, extra_specs,
                                   is_public, projects).get('id')

    def setUp(self):
        super(VolumeTypesApiTest, self).setUp()
        self.controller = types.VolumeTypesController()
        self.ctxt = context.RequestContext(user_id='fake',
                                           project_id='fake',
                                           is_admin=True)
        self.type_id1 = self._create_volume_type('volume_type1',
                                                 {'key1': 'value1'})
        self.type_id2 = self._create_volume_type('volume_type2',
                                                 {'key2': 'value2'})
        self.type_id3 = self._create_volume_type('volume_type3',
                                                 {'key3': 'value3'}, False,
                                                 ['fake'])

    def test_volume_types_index(self):
        self.stubs.Set(volume_types, 'get_all_types',
                       return_volume_types_get_all_types)

        req = fakes.HTTPRequest.blank('/v2/fake/types', use_admin_context=True)
        res_dict = self.controller.index(req)

        self.assertEqual(3, len(res_dict['volume_types']))

        expected_names = ['vol_type_1', 'vol_type_2', 'vol_type_3']
        actual_names = map(lambda e: e['name'], res_dict['volume_types'])
        self.assertEqual(set(expected_names), set(actual_names))
        for entry in res_dict['volume_types']:
            self.assertEqual('value1', entry['extra_specs']['key1'])

    def test_volume_types_index_no_data(self):
        self.stubs.Set(volume_types, 'get_all_types',
                       return_empty_volume_types_get_all_types)

        req = fakes.HTTPRequest.blank('/v2/fake/types')
        res_dict = self.controller.index(req)

        self.assertEqual(0, len(res_dict['volume_types']))

    def test_volume_types_index_with_limit(self):
        req = fakes.HTTPRequest.blank('/v2/fake/types?limit=1')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(1, len(res['volume_types']))
        self.assertEqual(self.type_id3, res['volume_types'][0]['id'])

        expect_next_link = ('http://localhost/v2/fake/types?limit=1'
                            '&marker=%s') % res['volume_types'][0]['id']
        self.assertEqual(expect_next_link, res['volume_type_links'][0]['href'])

    def test_volume_types_index_with_offset(self):
        req = fakes.HTTPRequest.blank('/v2/fake/types?offset=1')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(2, len(res['volume_types']))

    def test_volume_types_index_with_offset_out_of_range(self):
        url = '/v2/fake/types?offset=424366766556787'
        req = fakes.HTTPRequest.blank(url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_volume_types_index_with_limit_and_offset(self):
        req = fakes.HTTPRequest.blank('/v2/fake/types?limit=2&offset=1')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(2, len(res['volume_types']))
        self.assertEqual(self.type_id2, res['volume_types'][0]['id'])
        self.assertEqual(self.type_id1, res['volume_types'][1]['id'])

    def test_volume_types_index_with_limit_and_marker(self):
        req = fakes.HTTPRequest.blank(('/v2/fake/types?limit=1'
                                       '&marker=%s') % self.type_id2)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(1, len(res['volume_types']))
        self.assertEqual(self.type_id1, res['volume_types'][0]['id'])

    def test_volume_types_index_with_valid_filter(self):
        req = fakes.HTTPRequest.blank('/v2/fake/types?is_public=True')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(3, len(res['volume_types']))
        self.assertEqual(self.type_id3, res['volume_types'][0]['id'])
        self.assertEqual(self.type_id2, res['volume_types'][1]['id'])
        self.assertEqual(self.type_id1, res['volume_types'][2]['id'])

    def test_volume_types_index_with_invalid_filter(self):
        req = fakes.HTTPRequest.blank(('/v2/fake/types?id=%s') % self.type_id1)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)

        self.assertEqual(3, len(res['volume_types']))

    def test_volume_types_index_with_sort_keys(self):
        req = fakes.HTTPRequest.blank('/v2/fake/types?sort=id')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)
        expect_result = [self.type_id1, self.type_id2, self.type_id3]
        expect_result.sort(reverse=True)

        self.assertEqual(3, len(res['volume_types']))
        self.assertEqual(expect_result[0], res['volume_types'][0]['id'])
        self.assertEqual(expect_result[1], res['volume_types'][1]['id'])
        self.assertEqual(expect_result[2], res['volume_types'][2]['id'])

    def test_volume_types_index_with_sort_and_limit(self):
        req = fakes.HTTPRequest.blank('/v2/fake/types?sort=id&limit=2')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)
        expect_result = [self.type_id1, self.type_id2, self.type_id3]
        expect_result.sort(reverse=True)

        self.assertEqual(2, len(res['volume_types']))
        self.assertEqual(expect_result[0], res['volume_types'][0]['id'])
        self.assertEqual(expect_result[1], res['volume_types'][1]['id'])

    def test_volume_types_index_with_sort_keys_and_sort_dirs(self):
        req = fakes.HTTPRequest.blank('/v2/fake/types?sort=id:asc')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.index(req)
        expect_result = [self.type_id1, self.type_id2, self.type_id3]
        expect_result.sort()

        self.assertEqual(3, len(res['volume_types']))
        self.assertEqual(expect_result[0], res['volume_types'][0]['id'])
        self.assertEqual(expect_result[1], res['volume_types'][1]['id'])
        self.assertEqual(expect_result[2], res['volume_types'][2]['id'])

    def test_volume_types_show(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)

        type_id = str(uuid.uuid4())
        req = fakes.HTTPRequest.blank('/v2/fake/types/' + type_id)
        res_dict = self.controller.show(req, type_id)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(type_id, res_dict['volume_type']['id'])
        type_name = 'vol_type_' + type_id
        self.assertEqual(type_name, res_dict['volume_type']['name'])

    def test_volume_types_show_not_found(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)

        req = fakes.HTTPRequest.blank('/v2/fake/types/777')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, '777')

    def test_get_default(self):
        self.stubs.Set(volume_types, 'get_default_volume_type',
                       return_volume_types_get_default)
        req = fakes.HTTPRequest.blank('/v2/fake/types/default')
        req.method = 'GET'
        res_dict = self.controller.show(req, 'default')
        self.assertEqual(1, len(res_dict))
        self.assertEqual('vol_type_1', res_dict['volume_type']['name'])
        self.assertEqual('vol_type_desc_1',
                         res_dict['volume_type']['description'])

    def test_get_default_not_found(self):
        self.stubs.Set(volume_types, 'get_default_volume_type',
                       return_volume_types_get_default_not_found)
        req = fakes.HTTPRequest.blank('/v2/fake/types/default')
        req.method = 'GET'

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 'default')

    def test_view_builder_show(self):
        view_builder = views_types.ViewBuilder()

        now = timeutils.utcnow().isoformat()
        raw_volume_type = dict(
            name='new_type',
            description='new_type_desc',
            qos_specs_id='new_id',
            is_public=True,
            deleted=False,
            created_at=now,
            updated_at=now,
            extra_specs={},
            deleted_at=None,
            id=42,
        )

        request = fakes.HTTPRequest.blank("/v2")
        output = view_builder.show(request, raw_volume_type)

        self.assertIn('volume_type', output)
        expected_volume_type = dict(
            name='new_type',
            description='new_type_desc',
            is_public=True,
            id=42,
        )
        self.assertDictMatch(expected_volume_type, output['volume_type'])

    def test_view_builder_show_admin(self):
        view_builder = views_types.ViewBuilder()

        now = timeutils.utcnow().isoformat()
        raw_volume_type = dict(
            name='new_type',
            description='new_type_desc',
            qos_specs_id='new_id',
            is_public=True,
            deleted=False,
            created_at=now,
            updated_at=now,
            extra_specs={},
            deleted_at=None,
            id=42,
        )

        request = fakes.HTTPRequest.blank("/v2", use_admin_context=True)
        output = view_builder.show(request, raw_volume_type)

        self.assertIn('volume_type', output)
        expected_volume_type = dict(
            name='new_type',
            description='new_type_desc',
            qos_specs_id='new_id',
            is_public=True,
            extra_specs={},
            id=42,
        )
        self.assertDictMatch(expected_volume_type, output['volume_type'])

    def test_view_builder_show_qos_specs_id_policy(self):
        with mock.patch.object(common,
                               'validate_policy',
                               side_effect=[False, True]):
            view_builder = views_types.ViewBuilder()
            now = timeutils.utcnow().isoformat()
            raw_volume_type = dict(
                name='new_type',
                description='new_type_desc',
                qos_specs_id='new_id',
                is_public=True,
                deleted=False,
                created_at=now,
                updated_at=now,
                extra_specs={},
                deleted_at=None,
                id=42,
            )

            request = fakes.HTTPRequest.blank("/v2")
            output = view_builder.show(request, raw_volume_type)

            self.assertIn('volume_type', output)
            expected_volume_type = dict(
                name='new_type',
                description='new_type_desc',
                qos_specs_id='new_id',
                is_public=True,
                id=42,
            )
            self.assertDictMatch(expected_volume_type, output['volume_type'])

    def test_view_builder_show_extra_specs_policy(self):
        with mock.patch.object(common,
                               'validate_policy',
                               side_effect=[True, False]):
            view_builder = views_types.ViewBuilder()
            now = timeutils.utcnow().isoformat()
            raw_volume_type = dict(
                name='new_type',
                description='new_type_desc',
                qos_specs_id='new_id',
                is_public=True,
                deleted=False,
                created_at=now,
                updated_at=now,
                extra_specs={},
                deleted_at=None,
                id=42,
            )

            request = fakes.HTTPRequest.blank("/v2")
            output = view_builder.show(request, raw_volume_type)

            self.assertIn('volume_type', output)
            expected_volume_type = dict(
                name='new_type',
                description='new_type_desc',
                extra_specs={},
                is_public=True,
                id=42,
            )
            self.assertDictMatch(expected_volume_type, output['volume_type'])

    def test_view_builder_show_pass_all_policy(self):
        with mock.patch.object(common,
                               'validate_policy',
                               side_effect=[True, True]):
            view_builder = views_types.ViewBuilder()
            now = timeutils.utcnow().isoformat()
            raw_volume_type = dict(
                name='new_type',
                description='new_type_desc',
                qos_specs_id='new_id',
                is_public=True,
                deleted=False,
                created_at=now,
                updated_at=now,
                extra_specs={},
                deleted_at=None,
                id=42,
            )

            request = fakes.HTTPRequest.blank("/v2")
            output = view_builder.show(request, raw_volume_type)

            self.assertIn('volume_type', output)
            expected_volume_type = dict(
                name='new_type',
                description='new_type_desc',
                qos_specs_id='new_id',
                extra_specs={},
                is_public=True,
                id=42,
            )
            self.assertDictMatch(expected_volume_type, output['volume_type'])

    def test_view_builder_list(self):
        view_builder = views_types.ViewBuilder()

        now = timeutils.utcnow().isoformat()
        raw_volume_types = []
        for i in range(0, 10):
            raw_volume_types.append(
                dict(
                    name='new_type',
                    description='new_type_desc',
                    qos_specs_id='new_id',
                    is_public=True,
                    deleted=False,
                    created_at=now,
                    updated_at=now,
                    extra_specs={},
                    deleted_at=None,
                    id=42 + i
                )
            )

        request = fakes.HTTPRequest.blank("/v2")
        output = view_builder.index(request, raw_volume_types)

        self.assertIn('volume_types', output)
        for i in range(0, 10):
            expected_volume_type = dict(
                name='new_type',
                description='new_type_desc',
                is_public=True,
                id=42 + i
            )
            self.assertDictMatch(expected_volume_type,
                                 output['volume_types'][i])

    def test_view_builder_list_admin(self):
        view_builder = views_types.ViewBuilder()

        now = timeutils.utcnow().isoformat()
        raw_volume_types = []
        for i in range(0, 10):
            raw_volume_types.append(
                dict(
                    name='new_type',
                    description='new_type_desc',
                    qos_specs_id='new_id',
                    is_public=True,
                    deleted=False,
                    created_at=now,
                    updated_at=now,
                    extra_specs={},
                    deleted_at=None,
                    id=42 + i
                )
            )

        request = fakes.HTTPRequest.blank("/v2", use_admin_context=True)
        output = view_builder.index(request, raw_volume_types)

        self.assertIn('volume_types', output)
        for i in range(0, 10):
            expected_volume_type = dict(
                name='new_type',
                description='new_type_desc',
                qos_specs_id='new_id',
                is_public=True,
                extra_specs={},
                id=42 + i
            )
            self.assertDictMatch(expected_volume_type,
                                 output['volume_types'][i])


class VolumeTypesSerializerTest(test.TestCase):
    def _verify_volume_type(self, vtype, tree):
        self.assertEqual('volume_type', tree.tag)
        self.assertEqual(vtype['name'], tree.get('name'))
        self.assertEqual(vtype['description'], tree.get('description'))
        self.assertEqual(str(vtype['id']), tree.get('id'))
        self.assertEqual(1, len(tree))
        extra_specs = tree[0]
        self.assertEqual('extra_specs', extra_specs.tag)
        seen = set(vtype['extra_specs'].keys())
        for child in extra_specs:
            self.assertIn(child.tag, seen)
            self.assertEqual(vtype['extra_specs'][child.tag], child.text)
            seen.remove(child.tag)
        self.assertEqual(0, len(seen))

    def test_index_serializer(self):
        serializer = types.VolumeTypesTemplate()

        # Just getting some input data
        vtypes = return_volume_types_get_all_types(None)
        text = serializer.serialize({'volume_types': list(vtypes.values())})

        tree = etree.fromstring(text)

        self.assertEqual('volume_types', tree.tag)
        self.assertEqual(len(vtypes), len(tree))
        for child in tree:
            name = child.get('name')
            self.assertIn(name, vtypes)
            self._verify_volume_type(vtypes[name], child)

    def test_voltype_serializer(self):
        serializer = types.VolumeTypeTemplate()

        vtype = stub_volume_type(1)
        text = serializer.serialize(dict(volume_type=vtype))

        tree = etree.fromstring(text)

        self._verify_volume_type(vtype, tree)
