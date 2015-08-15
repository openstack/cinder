# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack Foundation
# Copyright 2011 University of Southern California
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

from lxml import etree
import mock
import webob

from cinder.api.contrib import types_extra_specs
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes
import cinder.wsgi


def return_create_volume_type_extra_specs(context, volume_type_id,
                                          extra_specs):
    return stub_volume_type_extra_specs()


def return_volume_type_extra_specs(context, volume_type_id):
    return stub_volume_type_extra_specs()


def return_empty_volume_type_extra_specs(context, volume_type_id):
    return {}


def delete_volume_type_extra_specs(context, volume_type_id, key):
    pass


def delete_volume_type_extra_specs_not_found(context, volume_type_id, key):
    raise exception.VolumeTypeExtraSpecsNotFound("Not Found")


def stub_volume_type_extra_specs():
    specs = {"key1": "value1",
             "key2": "value2",
             "key3": "value3",
             "key4": "value4",
             "key5": "value5"}
    return specs


def volume_type_get(context, id, inactive=False, expected_fields=None):
    pass


class VolumeTypesExtraSpecsTest(test.TestCase):

    def setUp(self):
        super(VolumeTypesExtraSpecsTest, self).setUp()
        self.flags(host='fake')
        self.stubs.Set(cinder.db, 'volume_type_get', volume_type_get)
        self.api_path = '/v2/fake/os-volume-types/1/extra_specs'
        self.controller = types_extra_specs.VolumeTypeExtraSpecsController()

        """to reset notifier drivers left over from other api/contrib tests"""

    def test_index(self):
        self.stubs.Set(cinder.db, 'volume_type_extra_specs_get',
                       return_volume_type_extra_specs)

        req = fakes.HTTPRequest.blank(self.api_path)
        res_dict = self.controller.index(req, 1)

        self.assertEqual('value1', res_dict['extra_specs']['key1'])

    def test_index_no_data(self):
        self.stubs.Set(cinder.db, 'volume_type_extra_specs_get',
                       return_empty_volume_type_extra_specs)

        req = fakes.HTTPRequest.blank(self.api_path)
        res_dict = self.controller.index(req, 1)

        self.assertEqual(0, len(res_dict['extra_specs']))

    def test_show(self):
        self.stubs.Set(cinder.db, 'volume_type_extra_specs_get',
                       return_volume_type_extra_specs)

        req = fakes.HTTPRequest.blank(self.api_path + '/key5')
        res_dict = self.controller.show(req, 1, 'key5')

        self.assertEqual('value5', res_dict['key5'])

    def test_show_spec_not_found(self):
        self.stubs.Set(cinder.db, 'volume_type_extra_specs_get',
                       return_empty_volume_type_extra_specs)

        req = fakes.HTTPRequest.blank(self.api_path + '/key6')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, 1, 'key6')

    def test_delete(self):
        self.stubs.Set(cinder.db, 'volume_type_extra_specs_delete',
                       delete_volume_type_extra_specs)

        self.assertEqual(0, len(self.notifier.notifications))
        req = fakes.HTTPRequest.blank(self.api_path + '/key5')
        self.controller.delete(req, 1, 'key5')
        self.assertEqual(1, len(self.notifier.notifications))

    def test_delete_not_found(self):
        self.stubs.Set(cinder.db, 'volume_type_extra_specs_delete',
                       delete_volume_type_extra_specs_not_found)

        req = fakes.HTTPRequest.blank(self.api_path + '/key6')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, 1, 'key6')

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_string_length')
    def test_create(self, mock_validate):
        self.stubs.Set(cinder.db,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        body = {"extra_specs": {"key1": "value1"}}

        self.assertEqual(0, len(self.notifier.notifications))
        req = fakes.HTTPRequest.blank(self.api_path)
        res_dict = self.controller.create(req, 1, body)
        self.assertEqual(1, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)
        self.assertEqual('value1', res_dict['extra_specs']['key1'])

    @mock.patch.object(cinder.db, 'volume_type_extra_specs_update_or_create')
    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_string_length')
    def test_create_key_allowed_chars(
            self, mock_validate, volume_type_extra_specs_update_or_create):
        mock_return_value = {"key1": "value1",
                             "key2": "value2",
                             "key3": "value3",
                             "key4": "value4",
                             "key5": "value5"}
        volume_type_extra_specs_update_or_create.\
            return_value = mock_return_value

        body = {"extra_specs": {"other_alphanum.-_:": "value1"}}

        self.assertEqual(0, len(self.notifier.notifications))

        req = fakes.HTTPRequest.blank(self.api_path)
        res_dict = self.controller.create(req, 1, body)
        self.assertEqual(1, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)
        self.assertEqual('value1',
                         res_dict['extra_specs']['other_alphanum.-_:'])

    @mock.patch.object(cinder.db, 'volume_type_extra_specs_update_or_create')
    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_string_length')
    def test_create_too_many_keys_allowed_chars(
            self, mock_validate, volume_type_extra_specs_update_or_create):
        mock_return_value = {"key1": "value1",
                             "key2": "value2",
                             "key3": "value3",
                             "key4": "value4",
                             "key5": "value5"}
        volume_type_extra_specs_update_or_create.\
            return_value = mock_return_value

        body = {"extra_specs": {"other_alphanum.-_:": "value1",
                                "other2_alphanum.-_:": "value2",
                                "other3_alphanum.-_:": "value3"}}

        self.assertEqual(0, len(self.notifier.notifications))

        req = fakes.HTTPRequest.blank(self.api_path)
        res_dict = self.controller.create(req, 1, body)
        self.assertEqual(1, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)
        self.assertEqual('value1',
                         res_dict['extra_specs']['other_alphanum.-_:'])
        self.assertEqual('value2',
                         res_dict['extra_specs']['other2_alphanum.-_:'])
        self.assertEqual('value3',
                         res_dict['extra_specs']['other3_alphanum.-_:'])

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_string_length')
    def test_update_item(self, mock_validate):
        self.stubs.Set(cinder.db,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        body = {"key1": "value1"}

        self.assertEqual(0, len(self.notifier.notifications))
        req = fakes.HTTPRequest.blank(self.api_path + '/key1')
        res_dict = self.controller.update(req, 1, 'key1', body)
        self.assertEqual(1, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)

        self.assertEqual('value1', res_dict['key1'])

    def test_update_item_too_many_keys(self):
        self.stubs.Set(cinder.db,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        body = {"key1": "value1", "key2": "value2"}

        req = fakes.HTTPRequest.blank(self.api_path + '/key1')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'key1', body)

    def test_update_item_body_uri_mismatch(self):
        self.stubs.Set(cinder.db,
                       'volume_type_extra_specs_update_or_create',
                       return_create_volume_type_extra_specs)
        body = {"key1": "value1"}

        req = fakes.HTTPRequest.blank(self.api_path + '/bad')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, 1, 'bad', body)

    def _extra_specs_empty_update(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/types/1/extra_specs')
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, '1', body)

    def test_update_no_body(self):
        self._extra_specs_empty_update(body=None)

    def test_update_empty_body(self):
        self._extra_specs_empty_update(body={})

    def _extra_specs_create_bad_body(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/types/1/extra_specs')
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, '1', body)

    def test_create_no_body(self):
        self._extra_specs_create_bad_body(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._extra_specs_create_bad_body(body=body)

    def test_create_malformed_entity(self):
        body = {'extra_specs': 'string'}
        self._extra_specs_create_bad_body(body=body)

    def test_create_invalid_key(self):
        body = {"extra_specs": {"ke/y1": "value1"}}
        self._extra_specs_create_bad_body(body=body)

    def test_create_invalid_too_many_key(self):
        body = {"key1": "value1", "ke/y2": "value2", "key3": "value3"}
        self._extra_specs_create_bad_body(body=body)


class VolumeTypeExtraSpecsSerializerTest(test.TestCase):
    def test_index_create_serializer(self):
        serializer = types_extra_specs.VolumeTypeExtraSpecsTemplate()

        # Just getting some input data
        extra_specs = stub_volume_type_extra_specs()
        text = serializer.serialize(dict(extra_specs=extra_specs))

        tree = etree.fromstring(text)

        self.assertEqual('extra_specs', tree.tag)
        self.assertEqual(len(extra_specs), len(tree))
        seen = set(extra_specs.keys())
        for child in tree:
            self.assertIn(child.tag, seen)
            self.assertEqual(extra_specs[child.tag], child.text)
            seen.remove(child.tag)
        self.assertEqual(0, len(seen))

    def test_update_show_serializer(self):
        serializer = types_extra_specs.VolumeTypeExtraSpecTemplate()

        exemplar = dict(key1='value1')
        text = serializer.serialize(exemplar)

        tree = etree.fromstring(text)

        self.assertEqual('key1', tree.tag)
        self.assertEqual('value1', tree.text)
        self.assertEqual(0, len(tree))
