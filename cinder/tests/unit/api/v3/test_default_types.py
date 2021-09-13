# Copyright 2020 Red Hat, Inc.
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

from cinder.api import microversions as mv
from cinder.api.v3 import default_types
from cinder import context
from cinder import exception
from cinder import objects
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


class DefaultVolumeTypesApiTest(test.TestCase):

    def _create_volume_type(self, ctxt, volume_type_name, extra_specs=None,
                            is_public=True, projects=None):
        vol_type = objects.VolumeType(ctxt,
                                      name=volume_type_name,
                                      is_public=is_public,
                                      description='',
                                      extra_specs=extra_specs,
                                      projects=projects)
        vol_type.create()
        return vol_type

    def _set_default_type_system_scope(self, project_id=fake.PROJECT_ID,
                                       volume_type='volume_type1'):
        body = {
            'default_type':
                {'volume_type': volume_type}
        }
        req = fakes.HTTPRequest.blank('/v3/default-types/%s' % project_id,
                                      use_admin_context=True,
                                      version=mv.DEFAULT_TYPE_OVERRIDES,
                                      system_scope='all')
        res_dict = self.controller.create_update(req, id=project_id,
                                                 body=body)
        return res_dict

    def _set_default_type_project_scope(self, project_id=fake.PROJECT_ID,
                                        volume_type='volume_type1'):
        body = {
            'default_type':
                {'volume_type': volume_type}
        }
        req = fakes.HTTPRequest.blank('/v3/default-types/%s' % project_id,
                                      use_admin_context=True,
                                      version=mv.DEFAULT_TYPE_OVERRIDES)
        res_dict = self.controller.create_update(req, id=project_id,
                                                 body=body)
        return res_dict

    def setUp(self):
        super(DefaultVolumeTypesApiTest, self).setUp()
        self.controller = default_types.DefaultTypesController()
        self.ctxt = context.RequestContext(user_id=fake.USER_ID,
                                           project_id=fake.PROJECT_ID,
                                           is_admin=True,
                                           system_scope='all')
        self.type1 = self._create_volume_type(
            self.ctxt, 'volume_type1')
        self.type2 = self._create_volume_type(
            self.ctxt, 'volume_type2')

        get_patcher = mock.patch('cinder.api.api_utils.get_project',
                                 self._get_project)
        get_patcher.start()
        self.addCleanup(get_patcher.stop)

    class FakeProject(object):

        def __init__(self, id=fake.PROJECT_ID, domain_id=fake.DOMAIN_ID,
                     parent_id=None, is_admin_project=False):
            self.id = id
            self.domain_id = domain_id

    def _get_project(self, context, id, subtree_as_ids=False,
                     parents_as_ids=False, is_admin_project=False):
        return self.FakeProject(id)

    def test_default_volume_types_create_update_system_admin(self):
        res_dict = self._set_default_type_system_scope()
        self.assertEqual(fake.PROJECT_ID,
                         res_dict['default_type']['project_id'])
        self.assertEqual(self.type1.id,
                         res_dict['default_type']['volume_type_id'])

    def test_default_volume_types_create_update_project_admin(self):
        res_dict = self._set_default_type_project_scope()
        self.assertEqual(fake.PROJECT_ID,
                         res_dict['default_type']['project_id'])
        self.assertEqual(self.type1.id,
                         res_dict['default_type']['volume_type_id'])

    def test_default_volume_types_detail_system_admin(self):
        self._set_default_type_system_scope()
        req = fakes.HTTPRequest.blank('/v3/default-types/%s' % fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.DEFAULT_TYPE_OVERRIDES,
                                      system_scope='all')
        res_dict = self.controller.detail(req, fake.PROJECT_ID)

        self.assertEqual(fake.PROJECT_ID,
                         res_dict['default_type']['project_id'])
        self.assertEqual(self.type1.id,
                         res_dict['default_type']['volume_type_id'])

    def test_default_volume_types_detail_project_admin(self):
        self._set_default_type_project_scope()
        req = fakes.HTTPRequest.blank('/v3/default-types/%s' % fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.DEFAULT_TYPE_OVERRIDES)
        res_dict = self.controller.detail(req, fake.PROJECT_ID)

        self.assertEqual(fake.PROJECT_ID,
                         res_dict['default_type']['project_id'])
        self.assertEqual(self.type1.id,
                         res_dict['default_type']['volume_type_id'])

    def test_default_volume_types_detail_no_default_found(self):
        req = fakes.HTTPRequest.blank('/v3/default-types/%s' % fake.PROJECT_ID,
                                      use_admin_context=True,
                                      version=mv.DEFAULT_TYPE_OVERRIDES,
                                      system_scope='all')
        self.assertRaises(exception.VolumeTypeProjectDefaultNotFound,
                          self.controller.detail, req, fake.PROJECT_ID)

    def test_default_volume_types_list(self):
        req = fakes.HTTPRequest.blank('/v3/default-types/',
                                      use_admin_context=True,
                                      version=mv.DEFAULT_TYPE_OVERRIDES,
                                      system_scope='all')
        # Confirm this returns an empty list when no default types are set
        res_dict = self.controller.index(req)
        self.assertEqual(0, len(res_dict['default_types']))

        self._set_default_type_system_scope()
        self._set_default_type_system_scope(project_id=fake.PROJECT2_ID,
                                            volume_type='volume_type2')
        res_dict = self.controller.index(req)

        self.assertEqual(2, len(res_dict['default_types']))
        self.assertEqual(fake.PROJECT_ID,
                         res_dict['default_types'][0]['project_id'])
        self.assertEqual(fake.PROJECT2_ID,
                         res_dict['default_types'][1]['project_id'])

    def test_default_volume_types_delete_system_admin(self):
        self._set_default_type_system_scope()
        req = fakes.HTTPRequest.blank('/v3/default-types/',
                                      use_admin_context=True,
                                      version=mv.DEFAULT_TYPE_OVERRIDES,
                                      system_scope='all')
        res_dict = self.controller.index(req)
        self.assertEqual(1, len(res_dict['default_types']))

        self.controller.delete(req, fake.PROJECT_ID)
        res_dict_new = self.controller.index(req)
        self.assertEqual(0, len(res_dict_new['default_types']))

    def test_default_volume_types_delete_project_admin(self):
        self._set_default_type_project_scope()
        req = fakes.HTTPRequest.blank('/v3/default-types/',
                                      use_admin_context=True,
                                      version=mv.DEFAULT_TYPE_OVERRIDES)
        req_admin = fakes.HTTPRequest.blank('/v3/default-types/',
                                            use_admin_context=True,
                                            version=mv.DEFAULT_TYPE_OVERRIDES,
                                            system_scope='all')
        res_dict = self.controller.index(req_admin)
        self.assertEqual(1, len(res_dict['default_types']))

        self.controller.delete(req, fake.PROJECT_ID)
        res_dict_new = self.controller.index(req_admin)
        self.assertEqual(0, len(res_dict_new['default_types']))
