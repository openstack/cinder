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
from oslo_utils import timeutils
import six
import webob

from cinder.api.v2 import types
from cinder.api.views import types as views_types
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


def return_volume_types_get_all_types(context, search_opts=None):
    return dict(
        vol_type_1=stub_volume_type(1),
        vol_type_2=stub_volume_type(2),
        vol_type_3=stub_volume_type(3)
    )


def return_empty_volume_types_get_all_types(context, search_opts=None):
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
    def setUp(self):
        super(VolumeTypesApiTest, self).setUp()
        self.controller = types.VolumeTypesController()

    def test_volume_types_index(self):
        self.stubs.Set(volume_types, 'get_all_types',
                       return_volume_types_get_all_types)

        req = fakes.HTTPRequest.blank('/v2/fake/types')
        res_dict = self.controller.index(req)

        self.assertEqual(3, len(res_dict['volume_types']))

        expected_names = ['vol_type_1', 'vol_type_2', 'vol_type_3']
        actual_names = map(lambda e: e['name'], res_dict['volume_types'])
        self.assertEqual(set(actual_names), set(expected_names))
        for entry in res_dict['volume_types']:
            self.assertEqual('value1', entry['extra_specs']['key1'])

    def test_volume_types_index_no_data(self):
        self.stubs.Set(volume_types, 'get_all_types',
                       return_empty_volume_types_get_all_types)

        req = fakes.HTTPRequest.blank('/v2/fake/types')
        res_dict = self.controller.index(req)

        self.assertEqual(0, len(res_dict['volume_types']))

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
            id=42,
        )
        self.assertDictMatch(output['volume_type'], expected_volume_type)

    def test_view_builder_list(self):
        view_builder = views_types.ViewBuilder()

        now = timeutils.utcnow().isoformat()
        raw_volume_types = []
        for i in range(0, 10):
            raw_volume_types.append(
                dict(
                    name='new_type',
                    description='new_type_desc',
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
                extra_specs={},
                id=42 + i
            )
            self.assertDictMatch(output['volume_types'][i],
                                 expected_volume_type)


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
        self.assertEqual(len(seen), 0)

    def test_index_serializer(self):
        serializer = types.VolumeTypesTemplate()

        # Just getting some input data
        vtypes = return_volume_types_get_all_types(None)
        text = serializer.serialize({'volume_types': vtypes.values()})

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
