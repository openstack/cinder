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

import six
import webob

from cinder.api.contrib import types_manage
from cinder import exception
from cinder import test
from cinder.tests.api import fakes
from cinder.tests import fake_notifier
from cinder.volume import volume_types


def stub_volume_type(id):
    specs = {"key1": "value1",
             "key2": "value2",
             "key3": "value3",
             "key4": "value4",
             "key5": "value5"}
    return dict(id=id,
                name='vol_type_%s' % six.text_type(id),
                description='vol_type_desc_%s' % six.text_type(id),
                extra_specs=specs)


def stub_volume_type_updated(id):
    return dict(id=id,
                name='vol_type_%s_%s' % (six.text_type(id), six.text_type(id)),
                description='vol_type_desc_%s_%s' % (
                    six.text_type(id), six.text_type(id)))


def stub_volume_type_updated_desc_only(id):
    return dict(id=id,
                name='vol_type_%s' % six.text_type(id),
                description='vol_type_desc_%s_%s' % (
                    six.text_type(id), six.text_type(id)))


def return_volume_types_get_volume_type(context, id):
    if id == "777":
        raise exception.VolumeTypeNotFound(volume_type_id=id)
    return stub_volume_type(int(id))


def return_volume_types_destroy(context, name):
    if name == "777":
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    pass


def return_volume_types_with_volumes_destroy(context, id):
    if id == "1":
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


def return_volume_types_update(context, id, name, description):
    pass


def return_volume_types_update_fail(context, id, name, description):
    raise exception.VolumeTypeUpdateFailed(id=id)


def stub_volume_type_updated_name_only(id):
    return dict(id=id,
                name='vol_type_%s_%s' % (six.text_type(id), six.text_type(id)),
                description='vol_type_desc_%s' % six.text_type(id))


def stub_volume_type_updated_name_after_delete(id):
    return dict(id=id,
                name='vol_type_%s' % six.text_type(id),
                description='vol_type_desc_%s' % six.text_type(id))


def return_volume_types_update_exist(context, id, name, description):
    raise exception.VolumeTypeExists(id=id, name=name)


def return_volume_types_get_volume_type_updated(context, id):
    if id == "777":
        raise exception.VolumeTypeNotFound(volume_type_id=id)
    if id == '888':
        return stub_volume_type_updated_desc_only(int(id))
    if id == '999':
        return stub_volume_type_updated_name_only(int(id))
    if id == '666':
        return stub_volume_type_updated_name_after_delete(int(id))

    # anything else
    return stub_volume_type_updated(int(id))


def return_volume_types_get_by_name(context, name):
    if name == "777":
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    return stub_volume_type(int(name.split("_")[2]))


def return_volume_types_get_default():
    return stub_volume_type(1)


def return_volume_types_get_default_not_found():
    return {}


class VolumeTypesManageApiTest(test.TestCase):
    def setUp(self):
        super(VolumeTypesManageApiTest, self).setUp()
        self.flags(host='fake')
        self.controller = types_manage.VolumeTypesManageController()
        """to reset notifier drivers left over from other api/contrib tests"""
        fake_notifier.reset()
        self.addCleanup(fake_notifier.reset)

    def tearDown(self):
        super(VolumeTypesManageApiTest, self).tearDown()

    def test_volume_types_delete(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)
        self.stubs.Set(volume_types, 'destroy',
                       return_volume_types_destroy)

        req = fakes.HTTPRequest.blank('/v2/fake/types/1')
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        self.controller._delete(req, 1)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

    def test_volume_types_delete_not_found(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)
        self.stubs.Set(volume_types, 'destroy',
                       return_volume_types_destroy)

        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        req = fakes.HTTPRequest.blank('/v2/fake/types/777')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller._delete,
                          req, '777')
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

    def test_volume_types_with_volumes_destroy(self):
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)
        self.stubs.Set(volume_types, 'destroy',
                       return_volume_types_with_volumes_destroy)
        req = fakes.HTTPRequest.blank('/v2/fake/types/1')
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        self.controller._delete(req, 1)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

    def test_create(self):
        self.stubs.Set(volume_types, 'create',
                       return_volume_types_create)
        self.stubs.Set(volume_types, 'get_volume_type_by_name',
                       return_volume_types_get_by_name)

        body = {"volume_type": {"name": "vol_type_1",
                                "extra_specs": {"key1": "value1"}}}
        req = fakes.HTTPRequest.blank('/v2/fake/types')

        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        res_dict = self.controller._create(req, body)

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        self._check_test_results(res_dict, {
            'expected_name': 'vol_type_1', 'expected_desc': 'vol_type_desc_1'})

    def test_create_duplicate_type_fail(self):
        self.stubs.Set(volume_types, 'create',
                       return_volume_types_create_duplicate_type)
        self.stubs.Set(volume_types, 'get_volume_type_by_name',
                       return_volume_types_get_by_name)

        body = {"volume_type": {"name": "vol_type_1",
                                "extra_specs": {"key1": "value1"}}}
        req = fakes.HTTPRequest.blank('/v2/fake/types')
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._create, req, body)

    def _create_volume_type_bad_body(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/types')
        req.method = 'POST'
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._create, req, body)

    def test_create_no_body(self):
        self._create_volume_type_bad_body(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._create_volume_type_bad_body(body=body)

    def test_create_malformed_entity(self):
        body = {'volume_type': 'string'}
        self._create_volume_type_bad_body(body=body)

    def test_update(self):
        self.stubs.Set(volume_types, 'update',
                       return_volume_types_update)
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type_updated)

        body = {"volume_type": {"name": "vol_type_1_1",
                                "description": "vol_type_desc_1_1"}}
        req = fakes.HTTPRequest.blank('/v2/fake/types/1')
        req.method = 'PUT'

        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        res_dict = self.controller._update(req, '1', body)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        self._check_test_results(res_dict,
                                 {'expected_desc': 'vol_type_desc_1_1',
                                  'expected_name': 'vol_type_1_1'})

    def test_update_non_exist(self):
        self.stubs.Set(volume_types, 'update',
                       return_volume_types_update)
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)

        body = {"volume_type": {"name": "vol_type_1_1",
                                "description": "vol_type_desc_1_1"}}
        req = fakes.HTTPRequest.blank('/v2/fake/types/777')
        req.method = 'PUT'

        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._update, req, '777', body)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

    def test_update_db_fail(self):
        self.stubs.Set(volume_types, 'update',
                       return_volume_types_update_fail)
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type)

        body = {"volume_type": {"name": "vol_type_1_1",
                                "description": "vol_type_desc_1_1"}}
        req = fakes.HTTPRequest.blank('/v2/fake/types/1')
        req.method = 'PUT'

        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller._update, req, '1', body)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

    def test_update_no_name_no_description(self):
        body = {"volume_type": {}}
        req = fakes.HTTPRequest.blank('/v2/fake/types/1')
        req.method = 'PUT'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._update, req, '1', body)

    def test_update_empty_name(self):
        body = {"volume_type": {"name": "  ",
                                "description": "something"}}
        req = fakes.HTTPRequest.blank('/v2/fake/types/1')
        req.method = 'PUT'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._update, req, '1', body)

    def test_update_only_name(self):
        self.stubs.Set(volume_types, 'update',
                       return_volume_types_update)
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type_updated)

        body = {"volume_type": {"name": "vol_type_999_999"}}
        req = fakes.HTTPRequest.blank('/v2/fake/types/999')
        req.method = 'PUT'

        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        res_dict = self.controller._update(req, '999', body)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        self._check_test_results(res_dict,
                                 {'expected_name': 'vol_type_999_999',
                                  'expected_desc': 'vol_type_desc_999'})

    def test_update_only_description(self):
        self.stubs.Set(volume_types, 'update',
                       return_volume_types_update)
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type_updated)

        body = {"volume_type": {"description": "vol_type_desc_888_888"}}
        req = fakes.HTTPRequest.blank('/v2/fake/types/888')
        req.method = 'PUT'

        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        res_dict = self.controller._update(req, '888', body)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        self._check_test_results(res_dict,
                                 {'expected_name': 'vol_type_888',
                                  'expected_desc': 'vol_type_desc_888_888'})

    def test_rename_existing_name(self):
        self.stubs.Set(volume_types, 'update',
                       return_volume_types_update_exist)
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type_updated)
        # first attempt fail
        body = {"volume_type": {"name": "vol_type_666"}}
        req = fakes.HTTPRequest.blank('/v2/fake/types/666')
        req.method = 'PUT'

        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._update, req, '666', body)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

        # delete
        fake_notifier.reset()
        self.stubs.Set(volume_types, 'destroy',
                       return_volume_types_destroy)

        req = fakes.HTTPRequest.blank('/v2/fake/types/1')
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        self.controller._delete(req, '1')
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

        # update again
        self.stubs.Set(volume_types, 'update',
                       return_volume_types_update)
        self.stubs.Set(volume_types, 'get_volume_type',
                       return_volume_types_get_volume_type_updated)
        body = {"volume_type": {"name": "vol_type_666_666"}}
        req = fakes.HTTPRequest.blank('/v2/fake/types/666')
        req.method = 'PUT'

        fake_notifier.reset()
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        res_dict = self.controller._update(req, '666', body)
        self._check_test_results(res_dict,
                                 {'expected_name': 'vol_type_666',
                                  'expected_desc': 'vol_type_desc_666'})
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))

    def _check_test_results(self, results, expected_results):
        self.assertEqual(1, len(results))
        self.assertEqual(expected_results['expected_desc'],
                         results['volume_type']['description'])
        if expected_results.get('expected_name'):
            self.assertEqual(expected_results['expected_name'],
                             results['volume_type']['name'])
