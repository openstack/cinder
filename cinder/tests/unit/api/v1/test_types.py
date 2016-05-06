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

from oslo_utils import timeutils

from cinder.api.v1 import types
from cinder.api.views import types as views_types
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.volume import volume_types


def stub_volume_type(id):
    specs = {"key1": "value1",
             "key2": "value2",
             "key3": "value3",
             "key4": "value4",
             "key5": "value5"}
    return dict(id=id, name='vol_type_%s' % id, extra_specs=specs)


def return_volume_types_get_all_types(context, search_opts=None):
    d = {}
    for vtype in [fake.VOLUME_TYPE_ID, fake.VOLUME_TYPE2_ID,
                  fake.VOLUME_TYPE3_ID]:
        vtype_name = 'vol_type_%s' % vtype
        d[vtype_name] = stub_volume_type(vtype)
    return d


def return_empty_volume_types_get_all_types(context, search_opts=None):
    return {}


def return_volume_types_get_volume_type(context, id):
    if id == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.VolumeTypeNotFound(volume_type_id=id)
    return stub_volume_type(id)


class VolumeTypesApiTest(test.TestCase):
    def setUp(self):
        super(VolumeTypesApiTest, self).setUp()
        self.controller = types.VolumeTypesController()

    def test_volume_types_index(self):
        self.stubs.Set(volume_types, 'get_all_types',
                       return_volume_types_get_all_types)

        req = fakes.HTTPRequest.blank('/v1/%s/types' % fake.PROJECT_ID)
        res_dict = self.controller.index(req)

        self.assertEqual(3, len(res_dict['volume_types']))

        expected_names = ['vol_type_%s' % fake.VOLUME_TYPE_ID,
                          'vol_type_%s' % fake.VOLUME_TYPE2_ID,
                          'vol_type_%s' % fake.VOLUME_TYPE3_ID]

        actual_names = map(lambda e: e['name'], res_dict['volume_types'])
        self.assertEqual(set(expected_names), set(actual_names))
        for entry in res_dict['volume_types']:
            self.assertEqual('value1', entry['extra_specs']['key1'])

    def test_volume_types_index_no_data(self):
        self.stubs.Set(volume_types, 'get_all_types',
                       return_empty_volume_types_get_all_types)

        req = fakes.HTTPRequest.blank('/v1/%s/types' % fake.PROJECT_ID)
        res_dict = self.controller.index(req)

        self.assertEqual(0, len(res_dict['volume_types']))

    def test_volume_types_show(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)

        type_id = fake.VOLUME_TYPE_ID
        req = fakes.HTTPRequest.blank('/v1/%s/types/' % fake.PROJECT_ID
                                      + type_id)
        res_dict = self.controller.show(req, type_id)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(type_id, res_dict['volume_type']['id'])
        vol_type_name = 'vol_type_' + type_id
        self.assertEqual(vol_type_name, res_dict['volume_type']['name'])

    def test_volume_types_show_not_found(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)

        req = fakes.HTTPRequest.blank('/v1/%s/types/%s' %
                                      (fake.PROJECT_ID,
                                       fake.WILL_NOT_BE_FOUND_ID))
        self.assertRaises(exception.VolumeTypeNotFound, self.controller.show,
                          req, fake.WILL_NOT_BE_FOUND_ID)

    def test_view_builder_show(self):
        view_builder = views_types.ViewBuilder()

        now = timeutils.utcnow().isoformat()
        raw_volume_type = dict(name='new_type',
                               deleted=False,
                               created_at=now,
                               updated_at=now,
                               extra_specs={},
                               deleted_at=None,
                               description=None,
                               id=fake.VOLUME_TYPE_ID)

        request = fakes.HTTPRequest.blank("/v1")
        output = view_builder.show(request, raw_volume_type)

        self.assertIn('volume_type', output)
        expected_volume_type = dict(name='new_type',
                                    extra_specs={},
                                    description=None,
                                    is_public=None,
                                    id=fake.VOLUME_TYPE_ID)
        self.assertDictMatch(expected_volume_type, output['volume_type'])

    def test_view_builder_list(self):
        view_builder = views_types.ViewBuilder()

        now = timeutils.utcnow().isoformat()
        raw_volume_types = []
        volume_type_ids = []
        for i in range(0, 10):
            volume_type_id = str(uuid.uuid4())
            volume_type_ids.append(volume_type_id)
            raw_volume_types.append(dict(name='new_type',
                                         deleted=False,
                                         created_at=now,
                                         updated_at=now,
                                         extra_specs={},
                                         deleted_at=None,
                                         description=None,
                                         id=volume_type_id))

        request = fakes.HTTPRequest.blank("/v1")
        output = view_builder.index(request, raw_volume_types)

        self.assertIn('volume_types', output)
        for i in range(0, 10):
            expected_volume_type = dict(name='new_type',
                                        extra_specs={},
                                        id=volume_type_ids[i],
                                        is_public=None,
                                        description=None)
            self.assertDictMatch(expected_volume_type,
                                 output['volume_types'][i])
