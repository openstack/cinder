# Copyright 2013 eBay Inc.
# Copyright 2013 OpenStack Foundation
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

import ddt
import mock
from six.moves import http_client
import webob

from cinder.api.contrib import qos_specs_manage
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake


def stub_qos_specs(id):
    res = dict(name='qos_specs_' + str(id))
    res.update(dict(consumer='back-end'))
    res.update(dict(id=str(id)))
    specs = {"key1": "value1",
             "key2": "value2",
             "key3": "value3",
             "key4": "value4",
             "key5": "value5"}
    res.update(dict(specs=specs))
    return objects.QualityOfServiceSpecs(**res)


def stub_qos_associates(id):
    return [{
            'association_type': 'volume_type',
            'name': 'FakeVolTypeName',
            'id': fake.VOLUME_TYPE_ID}]


def return_qos_specs_get_all(context, filters=None, marker=None, limit=None,
                             offset=None, sort_keys=None, sort_dirs=None):
    return [
        stub_qos_specs(fake.QOS_SPEC_ID),
        stub_qos_specs(fake.QOS_SPEC2_ID),
        stub_qos_specs(fake.QOS_SPEC3_ID),
    ]


def return_qos_specs_get_qos_specs(context, id):
    if id == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.QoSSpecsNotFound(specs_id=id)
    return stub_qos_specs(id)


def return_qos_specs_delete(context, id, force):
    if id == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.QoSSpecsNotFound(specs_id=id)
    elif id == fake.IN_USE_ID:
        raise exception.QoSSpecsInUse(specs_id=id)
    pass


def return_qos_specs_delete_keys(context, id, keys):
    if id == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.QoSSpecsNotFound(specs_id=id)

    if 'foo' in keys:
        raise exception.QoSSpecsKeyNotFound(specs_id=id,
                                            specs_key='foo')


def return_qos_specs_update(context, id, specs):
    if id == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.QoSSpecsNotFound(specs_id=id)
    elif id == fake.INVALID_ID:
        raise exception.InvalidQoSSpecs(reason=id)
    elif id == fake.UPDATE_FAILED_ID:
        raise exception.QoSSpecsUpdateFailed(specs_id=id,
                                             qos_specs=specs)
    pass


def return_qos_specs_create(context, name, specs):
    if name == 'qos_spec_%s' % fake.ALREADY_EXISTS_ID:
        raise exception.QoSSpecsExists(specs_id=name)
    elif name == 'qos_spec_%s' % fake.ACTION_FAILED_ID:
        raise exception.QoSSpecsCreateFailed(name=id, qos_specs=specs)
    elif name == 'qos_spec_%s' % fake.INVALID_ID:
        raise exception.InvalidQoSSpecs(reason=name)

    return objects.QualityOfServiceSpecs(name=name,
                                         specs=specs,
                                         consumer='back-end',
                                         id=fake.QOS_SPEC_ID)


def return_get_qos_associations(context, id):
    if id == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.QoSSpecsNotFound(specs_id=id)
    elif id == fake.RAISE_ID:
        raise exception.CinderException()

    return stub_qos_associates(id)


def return_associate_qos_specs(context, id, type_id):
    if id == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.QoSSpecsNotFound(specs_id=id)
    elif id == fake.ACTION_FAILED_ID:
        raise exception.QoSSpecsAssociateFailed(specs_id=id,
                                                type_id=type_id)
    elif id == fake.ACTION2_FAILED_ID:
        raise exception.QoSSpecsDisassociateFailed(specs_id=id,
                                                   type_id=type_id)

    if type_id == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.VolumeTypeNotFound(
            volume_type_id=type_id)

    pass


def return_disassociate_all(context, id):
    if id == fake.WILL_NOT_BE_FOUND_ID:
        raise exception.QoSSpecsNotFound(specs_id=id)
    elif id == fake.ACTION2_FAILED_ID:
        raise exception.QoSSpecsDisassociateFailed(specs_id=id,
                                                   type_id=None)


@ddt.ddt
class QoSSpecManageApiTest(test.TestCase):

    def _create_qos_specs(self, name, values=None):
        """Create a transfer object."""
        if values:
            specs = dict(name=name, qos_specs=values)
        else:
            specs = {'name': name,
                     'consumer': 'back-end',
                     'specs': {
                         'key1': 'value1',
                         'key2': 'value2'}}
        return db.qos_specs_create(self.ctxt, specs)['id']

    def setUp(self):
        super(QoSSpecManageApiTest, self).setUp()
        self.flags(host='fake')
        self.controller = qos_specs_manage.QoSSpecsController()
        self.ctxt = context.RequestContext(user_id=fake.USER_ID,
                                           project_id=fake.PROJECT_ID,
                                           is_admin=True)
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)
        self.qos_id1 = self._create_qos_specs("Qos_test_1")
        self.qos_id2 = self._create_qos_specs("Qos_test_2")
        self.qos_id3 = self._create_qos_specs("Qos_test_3")
        self.qos_id4 = self._create_qos_specs("Qos_test_4")

    @mock.patch('cinder.volume.qos_specs.get_all_specs',
                side_effect=return_qos_specs_get_all)
    def test_index(self, mock_get_all_specs):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs' % fake.PROJECT_ID,
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertEqual(3, len(res['qos_specs']))

        names = set()
        for item in res['qos_specs']:
            self.assertEqual('value1', item['specs']['key1'])
            names.add(item['name'])
        expected_names = ['qos_specs_%s' % fake.QOS_SPEC_ID,
                          'qos_specs_%s' % fake.QOS_SPEC2_ID,
                          'qos_specs_%s' % fake.QOS_SPEC3_ID]
        self.assertEqual(set(expected_names), names)

    def test_index_with_limit(self):
        url = '/v2/%s/qos-specs?limit=2' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        res = self.controller.index(req)

        self.assertEqual(2, len(res['qos_specs']))
        self.assertEqual(self.qos_id4, res['qos_specs'][0]['id'])
        self.assertEqual(self.qos_id3, res['qos_specs'][1]['id'])

        expect_next_link = ('http://localhost/v2/%s/qos-specs?limit'
                            '=2&marker=%s') % (
                                fake.PROJECT_ID, res['qos_specs'][1]['id'])
        self.assertEqual(expect_next_link, res['qos_specs_links'][0]['href'])

    def test_index_with_offset(self):
        url = '/v2/%s/qos-specs?offset=1' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        res = self.controller.index(req)

        self.assertEqual(3, len(res['qos_specs']))

    def test_index_with_offset_out_of_range(self):
        url = '/v2/%s/qos-specs?offset=356576877698707' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.index,
                          req)

    def test_index_with_limit_and_offset(self):
        url = '/v2/%s/qos-specs?limit=2&offset=1' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        res = self.controller.index(req)

        self.assertEqual(2, len(res['qos_specs']))
        self.assertEqual(self.qos_id3, res['qos_specs'][0]['id'])
        self.assertEqual(self.qos_id2, res['qos_specs'][1]['id'])

    def test_index_with_marker(self):
        url = '/v2/%s/qos-specs?marker=%s' % (fake.PROJECT_ID, self.qos_id4)
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        res = self.controller.index(req)

        self.assertEqual(3, len(res['qos_specs']))

    def test_index_with_filter(self):
        url = '/v2/%s/qos-specs?id=%s' % (fake.PROJECT_ID, self.qos_id4)
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        res = self.controller.index(req)

        self.assertEqual(1, len(res['qos_specs']))
        self.assertEqual(self.qos_id4, res['qos_specs'][0]['id'])

    def test_index_with_sort_keys(self):
        url = '/v2/%s/qos-specs?sort=id' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        res = self.controller.index(req)
        self.assertEqual(4, len(res['qos_specs']))
        expect_result = [self.qos_id1, self.qos_id2,
                         self.qos_id3, self.qos_id4]
        expect_result.sort(reverse=True)

        self.assertEqual(expect_result[0], res['qos_specs'][0]['id'])
        self.assertEqual(expect_result[1], res['qos_specs'][1]['id'])
        self.assertEqual(expect_result[2], res['qos_specs'][2]['id'])
        self.assertEqual(expect_result[3], res['qos_specs'][3]['id'])

    def test_index_with_sort_keys_and_sort_dirs(self):
        url = '/v2/%s/qos-specs?sort=id:asc' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, use_admin_context=True)
        res = self.controller.index(req)
        self.assertEqual(4, len(res['qos_specs']))
        expect_result = [self.qos_id1, self.qos_id2,
                         self.qos_id3, self.qos_id4]
        expect_result.sort()

        self.assertEqual(expect_result[0], res['qos_specs'][0]['id'])
        self.assertEqual(expect_result[1], res['qos_specs'][1]['id'])
        self.assertEqual(expect_result[2], res['qos_specs'][2]['id'])
        self.assertEqual(expect_result[3], res['qos_specs'][3]['id'])

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.delete',
                side_effect=return_qos_specs_delete)
    def test_qos_specs_delete(self, mock_qos_delete, mock_qos_get_specs):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s' % (
            fake.PROJECT_ID, fake.QOS_SPEC_ID), use_admin_context=True)
        self.controller.delete(req, fake.QOS_SPEC_ID)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.delete',
                side_effect=return_qos_specs_delete)
    def test_qos_specs_delete_not_found(self, mock_qos_delete,
                                        mock_qos_get_specs):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s' %
                                      (fake.PROJECT_ID,
                                       fake.WILL_NOT_BE_FOUND_ID),
                                      use_admin_context=True)
        self.assertRaises(exception.QoSSpecsNotFound,
                          self.controller.delete, req,
                          fake.WILL_NOT_BE_FOUND_ID)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.delete',
                side_effect=return_qos_specs_delete)
    def test_qos_specs_delete_inuse(self, mock_qos_delete,
                                    mock_qos_get_specs):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s' % (
            fake.PROJECT_ID, fake.IN_USE_ID), use_admin_context=True)

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          req, fake.IN_USE_ID)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.delete',
                side_effect=return_qos_specs_delete)
    def test_qos_specs_delete_inuse_force(self, mock_qos_delete,
                                          mock_qos_get_specs):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s?force=True' %
                                      (fake.PROJECT_ID, fake.IN_USE_ID),
                                      use_admin_context=True)

        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.delete,
                          req, fake.IN_USE_ID)
        self.assertEqual(1, self.notifier.get_notification_count())

    def test_qos_specs_delete_with_invalid_force(self):
        invalid_force = "invalid_bool"
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/delete_keys?force=%s' %
            (fake.PROJECT_ID, fake.QOS_SPEC_ID, invalid_force),
            use_admin_context=True)

        self.assertRaises(exception.InvalidParameterValue,
                          self.controller.delete,
                          req, fake.QOS_SPEC_ID)

    @mock.patch('cinder.volume.qos_specs.delete_keys',
                side_effect=return_qos_specs_delete_keys)
    def test_qos_specs_delete_keys(self, mock_qos_delete_keys):
        body = {"keys": ['bar', 'zoo']}
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s/delete_keys' %
                                      (fake.PROJECT_ID, fake.IN_USE_ID),
                                      use_admin_context=True)

        self.controller.delete_keys(req, fake.IN_USE_ID, body)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.delete_keys',
                side_effect=return_qos_specs_delete_keys)
    def test_qos_specs_delete_keys_qos_notfound(self, mock_qos_specs_delete):
        body = {"keys": ['bar', 'zoo']}
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s/delete_keys' %
                                      (fake.PROJECT_ID,
                                       fake.WILL_NOT_BE_FOUND_ID),
                                      use_admin_context=True)

        self.assertRaises(exception.QoSSpecsNotFound,
                          self.controller.delete_keys,
                          req, fake.WILL_NOT_BE_FOUND_ID, body)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.delete_keys',
                side_effect=return_qos_specs_delete_keys)
    def test_qos_specs_delete_keys_badkey(self, mock_qos_specs_delete):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s/delete_keys' %
                                      (fake.PROJECT_ID, fake.IN_USE_ID),
                                      use_admin_context=True)
        body = {"keys": ['foo', 'zoo']}

        self.assertRaises(exception.QoSSpecsKeyNotFound,
                          self.controller.delete_keys,
                          req, fake.IN_USE_ID, body)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.delete_keys',
                side_effect=return_qos_specs_delete_keys)
    def test_qos_specs_delete_keys_get_notifier(self, mock_qos_delete_keys):
        body = {"keys": ['bar', 'zoo']}
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s/delete_keys' %
                                      (fake.PROJECT_ID, fake.IN_USE_ID),
                                      use_admin_context=True)

        self.controller.delete_keys(req, fake.IN_USE_ID, body)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.create',
                side_effect=return_qos_specs_create)
    @mock.patch('cinder.utils.validate_dictionary_string_length')
    def test_create(self, mock_validate, mock_qos_spec_create):

        body = {"qos_specs": {"name": "qos_specs_%s" % fake.QOS_SPEC_ID,
                              "key1": "value1"}}
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True)

        res_dict = self.controller.create(req, body)

        self.assertEqual(1, self.notifier.get_notification_count())
        self.assertEqual('qos_specs_%s' % fake.QOS_SPEC_ID,
                         res_dict['qos_specs']['name'])
        self.assertTrue(mock_validate.called)

    @mock.patch('cinder.volume.qos_specs.create',
                side_effect=return_qos_specs_create)
    def test_create_invalid_input(self, mock_qos_get_specs):
        body = {"qos_specs": {"name": 'qos_spec_%s' % fake.INVALID_ID,
                              "consumer": "invalid_consumer"}}
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs' % fake.PROJECT_ID,
                                      use_admin_context=True)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.create',
                side_effect=return_qos_specs_create)
    def test_create_conflict(self, mock_qos_spec_create):
        body = {"qos_specs": {"name": 'qos_spec_%s' % fake.ALREADY_EXISTS_ID,
                              "key1": "value1"}}
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs' % fake.PROJECT_ID,
                                      use_admin_context=True)

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.create, req, body)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.create',
                side_effect=return_qos_specs_create)
    def test_create_failed(self, mock_qos_spec_create):
        body = {"qos_specs": {"name": 'qos_spec_%s' % fake.ACTION_FAILED_ID,
                              "key1": "value1"}}
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs' % fake.PROJECT_ID,
                                      use_admin_context=True)

        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.create, req, body)
        self.assertEqual(1, self.notifier.get_notification_count())

    @ddt.data({'foo': {'a': 'b'}},
              {'qos_specs': {'a': 'b'}},
              {'qos_specs': 'string'},
              None)
    def test_create_invalid_body_bad_request(self, body):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs' % fake.PROJECT_ID,
                                      use_admin_context=True)
        req.method = 'POST'
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    @ddt.data({'name': 'fake_name', 'a' * 256: 'a'},
              {'name': 'fake_name', 'a': 'a' * 256},
              {'name': 'fake_name', '': 'a'})
    def test_create_qos_with_invalid_specs(self, value):
        body = {'qos_specs': value}
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs' % fake.PROJECT_ID,
                                      use_admin_context=True)
        req.method = 'POST'
        self.assertRaises(exception.InvalidInput,
                          self.controller.create, req, body)

    @ddt.data({'name': None},
              {'name': 'n' * 256},
              {'name': ''},
              {'name': '  '})
    def test_create_qos_with_invalid_spec_name(self, value):
        body = {'qos_specs': value}
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs' % fake.PROJECT_ID,
                                      use_admin_context=True)
        req.method = 'POST'
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    @mock.patch('cinder.volume.qos_specs.update',
                side_effect=return_qos_specs_update)
    def test_update(self, mock_qos_update):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s' %
                                      (fake.PROJECT_ID, fake.QOS_SPEC_ID),
                                      use_admin_context=True)
        body = {'qos_specs': {'key1': 'value1',
                              'key2': 'value2'}}
        res = self.controller.update(req, fake.QOS_SPEC_ID, body)
        self.assertDictEqual(body, res)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.update',
                side_effect=return_qos_specs_update)
    def test_update_not_found(self, mock_qos_update):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s' %
                                      (fake.PROJECT_ID,
                                       fake.WILL_NOT_BE_FOUND_ID),
                                      use_admin_context=True)
        body = {'qos_specs': {'key1': 'value1',
                              'key2': 'value2'}}
        self.assertRaises(exception.QoSSpecsNotFound,
                          self.controller.update,
                          req, fake.WILL_NOT_BE_FOUND_ID, body)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.update',
                side_effect=return_qos_specs_update)
    def test_update_invalid_input(self, mock_qos_update):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s' %
                                      (fake.PROJECT_ID, fake.INVALID_ID),
                                      use_admin_context=True)
        body = {'qos_specs': {'key1': 'value1',
                              'key2': 'value2'}}
        self.assertRaises(exception.InvalidQoSSpecs,
                          self.controller.update,
                          req, fake.INVALID_ID, body)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.update',
                side_effect=return_qos_specs_update)
    def test_update_failed(self, mock_qos_update):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s' %
                                      (fake.PROJECT_ID,
                                       fake.UPDATE_FAILED_ID),
                                      use_admin_context=True)
        body = {'qos_specs': {'key1': 'value1',
                              'key2': 'value2'}}
        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.update,
                          req, fake.UPDATE_FAILED_ID, body)
        self.assertEqual(1, self.notifier.get_notification_count())

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    def test_show(self, mock_get_qos_specs):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s' % (
            fake.PROJECT_ID, fake.QOS_SPEC_ID), use_admin_context=True)
        res_dict = self.controller.show(req, fake.QOS_SPEC_ID)

        self.assertEqual(fake.QOS_SPEC_ID, res_dict['qos_specs']['id'])
        self.assertEqual('qos_specs_%s' % fake.QOS_SPEC_ID,
                         res_dict['qos_specs']['name'])

    @mock.patch('cinder.volume.qos_specs.get_associations',
                side_effect=return_get_qos_associations)
    def test_get_associations(self, mock_get_assciations):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/associations' % (
                fake.PROJECT_ID, fake.QOS_SPEC_ID), use_admin_context=True)
        res = self.controller.associations(req, fake.QOS_SPEC_ID)

        self.assertEqual('FakeVolTypeName',
                         res['qos_associations'][0]['name'])
        self.assertEqual(fake.VOLUME_TYPE_ID,
                         res['qos_associations'][0]['id'])

    @mock.patch('cinder.volume.qos_specs.get_associations',
                side_effect=return_get_qos_associations)
    def test_get_associations_not_found(self, mock_get_assciations):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/associations' %
            (fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID),
            use_admin_context=True)
        self.assertRaises(exception.QoSSpecsNotFound,
                          self.controller.associations,
                          req, fake.WILL_NOT_BE_FOUND_ID)

    @mock.patch('cinder.volume.qos_specs.get_associations',
                side_effect=return_get_qos_associations)
    def test_get_associations_failed(self, mock_get_associations):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/associations' % (
                fake.PROJECT_ID, fake.RAISE_ID), use_admin_context=True)
        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.associations,
                          req, fake.RAISE_ID)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.associate_qos_with_type',
                side_effect=return_associate_qos_specs)
    def test_associate(self, mock_associate, mock_get_qos):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/associate?vol_type_id=%s' %
            (fake.PROJECT_ID, fake.QOS_SPEC_ID, fake.VOLUME_TYPE_ID),
            use_admin_context=True)
        res = self.controller.associate(req, fake.QOS_SPEC_ID)

        self.assertEqual(http_client.ACCEPTED, res.status_int)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.associate_qos_with_type',
                side_effect=return_associate_qos_specs)
    def test_associate_no_type(self, mock_associate, mock_get_qos):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s/associate' %
                                      (fake.PROJECT_ID, fake.QOS_SPEC_ID),
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.associate, req, fake.QOS_SPEC_ID)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.associate_qos_with_type',
                side_effect=return_associate_qos_specs)
    def test_associate_not_found(self, mock_associate, mock_get_qos):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/associate?vol_type_id=%s' % (
                fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID,
                fake.VOLUME_TYPE_ID), use_admin_context=True)
        self.assertRaises(exception.QoSSpecsNotFound,
                          self.controller.associate, req,
                          fake.WILL_NOT_BE_FOUND_ID)

        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/associate?vol_type_id=%s' %
            (fake.PROJECT_ID, fake.QOS_SPEC_ID, fake.WILL_NOT_BE_FOUND_ID),
            use_admin_context=True)

        self.assertRaises(exception.VolumeTypeNotFound,
                          self.controller.associate, req, fake.QOS_SPEC_ID)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.associate_qos_with_type',
                side_effect=return_associate_qos_specs)
    def test_associate_fail(self, mock_associate, mock_get_qos):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/associate?vol_type_id=%s' %
            (fake.PROJECT_ID, fake.ACTION_FAILED_ID, fake.VOLUME_TYPE_ID),
            use_admin_context=True)
        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.associate, req,
                          fake.ACTION_FAILED_ID)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.disassociate_qos_specs',
                side_effect=return_associate_qos_specs)
    def test_disassociate(self, mock_disassociate, mock_get_qos):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/disassociate?vol_type_id=%s' % (
                fake.PROJECT_ID, fake.QOS_SPEC_ID, fake.VOLUME_TYPE_ID),
            use_admin_context=True)
        res = self.controller.disassociate(req, fake.QOS_SPEC_ID)
        self.assertEqual(http_client.ACCEPTED, res.status_int)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.disassociate_qos_specs',
                side_effect=return_associate_qos_specs)
    def test_disassociate_no_type(self, mock_disassociate, mock_get_qos):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/disassociate' % (
                fake.PROJECT_ID, fake.QOS_SPEC_ID), use_admin_context=True)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.disassociate, req, fake.QOS_SPEC_ID)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.disassociate_qos_specs',
                side_effect=return_associate_qos_specs)
    def test_disassociate_not_found(self, mock_disassociate, mock_get_qos):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/disassociate?vol_type_id=%s' % (
                fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID,
                fake.VOLUME_TYPE_ID), use_admin_context=True)
        self.assertRaises(exception.QoSSpecsNotFound,
                          self.controller.disassociate, req,
                          fake.WILL_NOT_BE_FOUND_ID)

        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/disassociate?vol_type_id=%s' %
            (fake.PROJECT_ID, fake.VOLUME_TYPE_ID, fake.WILL_NOT_BE_FOUND_ID),
            use_admin_context=True)
        self.assertRaises(exception.VolumeTypeNotFound,
                          self.controller.disassociate, req,
                          fake.VOLUME_TYPE_ID)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.disassociate_qos_specs',
                side_effect=return_associate_qos_specs)
    def test_disassociate_failed(self, mock_disassociate, mock_get_qos):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/disassociate?vol_type_id=%s' % (
                fake.PROJECT_ID, fake.ACTION2_FAILED_ID, fake.VOLUME_TYPE_ID),
            use_admin_context=True)
        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.disassociate, req,
                          fake.ACTION2_FAILED_ID)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.disassociate_all',
                side_effect=return_disassociate_all)
    def test_disassociate_all(self, mock_disassociate, mock_get_qos):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/disassociate_all' % (
                fake.PROJECT_ID, fake.QOS_SPEC_ID), use_admin_context=True)
        res = self.controller.disassociate_all(req, fake.QOS_SPEC_ID)
        self.assertEqual(http_client.ACCEPTED, res.status_int)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.disassociate_all',
                side_effect=return_disassociate_all)
    def test_disassociate_all_not_found(self, mock_disassociate, mock_get):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/disassociate_all' % (
                fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID),
            use_admin_context=True)
        self.assertRaises(exception.QoSSpecsNotFound,
                          self.controller.disassociate_all, req,
                          fake.WILL_NOT_BE_FOUND_ID)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs',
                side_effect=return_qos_specs_get_qos_specs)
    @mock.patch('cinder.volume.qos_specs.disassociate_all',
                side_effect=return_disassociate_all)
    def test_disassociate_all_failed(self, mock_disassociate, mock_get):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/qos-specs/%s/disassociate_all' % (
                fake.PROJECT_ID, fake.ACTION2_FAILED_ID),
            use_admin_context=True)
        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.disassociate_all, req,
                          fake.ACTION2_FAILED_ID)

    def test_index_no_admin_user(self):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs' %
                                      fake.PROJECT_ID, use_admin_context=False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.index, req)

    def test_create_no_admin_user(self):
        body = {"qos_specs": {"name": "qos_specs_%s" % fake.QOS_SPEC_ID,
                              "key1": "value1"}}
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs' %
                                      fake.PROJECT_ID, use_admin_context=False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.create, req, body)

    def test_update_no_admin_user(self):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s' %
                                      (fake.PROJECT_ID, fake.QOS_SPEC_ID),
                                      use_admin_context=False)
        body = {'qos_specs': {'key1': 'value1',
                              'key2': 'value2'}}
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.update, req, fake.QOS_SPEC_ID, body)

    def test_qos_specs_delete_no_admin_user(self):
        req = fakes.HTTPRequest.blank('/v2/%s/qos-specs/%s' % (
            fake.PROJECT_ID, fake.QOS_SPEC_ID), use_admin_context=False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.delete, req, fake.QOS_SPEC_ID)
