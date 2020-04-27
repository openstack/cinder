# Copyright 2017 Intel Corporation
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

import webob

from cinder.api import microversions as mv
from cinder.api.v3 import group_specs as v3_group_specs
from cinder import context
from cinder import db
from cinder import exception
from cinder import rpc
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test

fake_group_specs = {
    'key1': 'value1',
    'key2': 'value2'
}

create_fake_group_specs = {
    'group_specs': {
        'key1': 'value1',
        'key2': 'value2'
    }
}

update_fake_group_specs = {
    'id': 'any_string'
}

incorrect_fake_group_specs = {
    'group_specs': {
        'key#': 'value1',
        'key2': 'value2'
    }
}


class GroupSpecsTestCase(test.TestCase):
    """test cases for the group specs API"""

    def setUp(self):
        super(GroupSpecsTestCase, self).setUp()
        self.controller = v3_group_specs.GroupTypeSpecsController()
        self.ctxt = context.RequestContext(
            user_id=fake.USER_ID,
            project_id=fake.PROJECT_ID,
            is_admin=True)

    @mock.patch.object(db, 'group_type_get', return_value={})
    @mock.patch.object(db, 'group_type_specs_get',
                       return_value=fake_group_specs)
    def test_group_types_index(self,
                               mock_group_type_specs_get,
                               mock_group_type_get):
        req = fakes.HTTPRequest.blank('v3/%s/group_specs' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.GROUP_TYPE)
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req, fake.GROUP_ID)
        group_specs_dict = res_dict['group_specs']
        mock_group_type_specs_get.assert_called()
        self.assertEqual('value1', group_specs_dict['key1'])
        self.assertEqual('value2', group_specs_dict['key2'])

    @mock.patch.object(rpc, 'get_notifier')
    @mock.patch.object(db, 'group_type_get', return_value={})
    @mock.patch.object(db, 'group_type_specs_update_or_create',
                       return_value={})
    def test_group_types_create(self,
                                mock_update_or_create,
                                mock_group_type_get,
                                mock_rpc_notifier):
        req = fakes.HTTPRequest.blank('v3/%s/group_specs' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.GROUP_TYPE)
        self.controller.create(req, fake.GROUP_ID,
                               body=create_fake_group_specs)
        self.assertTrue(mock_rpc_notifier.called)

    @mock.patch.object(rpc, 'get_notifier')
    @mock.patch.object(db, 'group_type_get', return_value={})
    @mock.patch.object(db, 'group_type_specs_get',
                       return_value=fake_group_specs)
    @mock.patch.object(db, 'group_type_specs_update_or_create',
                       return_value={})
    def test_group_types_update(self,
                                mock_update_or_create,
                                mock_typ_specs_get,
                                mock_group_type_get,
                                mock_rpc_notifier):
        req = fakes.HTTPRequest.blank('v3/%s/group_specs' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.GROUP_TYPE)
        self.controller.update(req,
                               fake.GROUP_TYPE_ID,
                               'id',
                               body=update_fake_group_specs)
        self.assertTrue(mock_rpc_notifier.called)

    @mock.patch.object(db, 'group_type_specs_get',
                       return_value=fake_group_specs)
    @mock.patch.object(db, 'group_type_get', return_value={})
    def test_group_types_show(self,
                              mock_group_type_get,
                              mock_fake_group_specs):
        req = fakes.HTTPRequest.blank('v3/%s/group_specs' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.GROUP_TYPE)
        res_dict = self.controller.show(req, fake.GROUP_TYPE_ID, 'key1')
        self.assertEqual('value1', res_dict['key1'])

    @mock.patch.object(rpc, 'get_notifier')
    @mock.patch.object(db, 'group_type_specs_delete', return_value={})
    @mock.patch.object(db, 'group_type_get', return_value={})
    def test_group_types_delete(self,
                                mock_group_type_get,
                                mock_group_spec_delete,
                                rpc_notifier_mock):
        req = fakes.HTTPRequest.blank('v3/%s/group_specs' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.GROUP_TYPE)
        self.controller.delete(req, fake.GROUP_TYPE_ID, 'key1')
        self.assertTrue(rpc_notifier_mock.called)

    @mock.patch.object(rpc, 'get_notifier')
    @mock.patch.object(db, 'group_type_specs_update_or_create',
                       return_value={})
    def test_check_type_should_raise_exception(self,
                                               mock_db_update_or_create,
                                               mock_rpc_notifier):
        req = fakes.HTTPRequest.blank('v3/%s/group_specs' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.GROUP_TYPE)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.create,
                          req,
                          fake.GROUP_ID,
                          body=create_fake_group_specs)

    @mock.patch.object(rpc, 'get_notifier')
    @mock.patch.object(db, 'group_type_get', return_value={})
    def test_delete_should_raise_exception(self,
                                           mock_group_type_get,
                                           mock_get_notifier):
        req = fakes.HTTPRequest.blank('v3/%s/group_specs' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.GROUP_TYPE)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete,
                          req,
                          fake.GROUP_TYPE_ID,
                          'key1')

    @mock.patch.object(db, 'group_type_get', return_value={})
    def test_update_should_raise_exceptions(self, mock_group_type_get):
        req = fakes.HTTPRequest.blank('v3/%s/group_specs' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.GROUP_TYPE)
        self.assertRaises(exception.ValidationError,
                          self.controller.update,
                          req,
                          fake.GROUP_TYPE_ID,
                          'id', body=None)
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, fake.GROUP_TYPE_ID, 'id',
                          body=fake_group_specs)
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, fake.GROUP_TYPE_ID, 'key1',
                          body=fake_group_specs)

    @mock.patch.object(db, 'group_type_specs_get',
                       return_value=fake_group_specs)
    @mock.patch.object(db, 'group_type_get', return_value={})
    def test_show_should_raise_exception(self,
                                         mock_group_type_get,
                                         mock_group_type_specs_get):
        req = fakes.HTTPRequest.blank('v3/%s/group_specs' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.GROUP_TYPE)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          req,
                          fake.GROUP_TYPE_ID,
                          'key')

    @mock.patch.object(rpc, 'get_notifier')
    @mock.patch.object(db, 'group_type_get', return_value={})
    @mock.patch.object(db, 'group_type_specs_update_or_create',
                       return_value={})
    def test_check_key_name_should_raise_exception(self,
                                                   mock_update_or_create,
                                                   mock_group_type_get,
                                                   mock_rpc_notifier):
        req = fakes.HTTPRequest.blank('v3/%s/group_specs' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.GROUP_TYPE)
        self.assertRaises(exception.ValidationError, self.controller.create,
                          req, fake.GROUP_ID, body=incorrect_fake_group_specs)
