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

from cinder.api import microversions as mv
from cinder.api.v3 import types
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.volume import volume_types


class VolumeTypesApiTest(test.TestCase):

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

    def setUp(self):
        super(VolumeTypesApiTest, self).setUp()
        self.controller = types.VolumeTypesController()
        self.ctxt = context.RequestContext(user_id=fake.USER_ID,
                                           project_id=fake.PROJECT_ID,
                                           is_admin=True)
        self.type1 = self._create_volume_type(
            self.ctxt, 'volume_type1',
            {'key1': 'value1', 'RESKEY:availability_zones': 'az1,az2'})
        self.type2 = self._create_volume_type(
            self.ctxt, 'volume_type2',
            {'key2': 'value2', 'RESKEY:availability_zones': 'az1,az3'})
        self.type3 = self._create_volume_type(
            self.ctxt, 'volume_type3',
            {'key3': 'value3'}, False, [fake.PROJECT_ID])
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.type1.destroy()
        self.type2.destroy()
        self.type3.destroy()

    def test_volume_types_index_with_extra_specs(self):
        def _get_volume_types(extra_specs,
                              use_admin_context=True,
                              microversion=mv.SUPPORT_VOLUME_TYPE_FILTER):
            req = fakes.HTTPRequest.blank(
                '/v3/%s/types?extra_specs=%s' % (fake.PROJECT_ID, extra_specs),
                use_admin_context=use_admin_context)
            req.api_version_request = mv.get_api_version(microversion)
            res_dict = self.controller.index(req)
            return res_dict['volume_types']

        # since __DEFAULT__ type always exists, total number of volume types
        # is total_types_created + 1. In this case it's 4
        volume_types = _get_volume_types('{"key1":"value1"}',
                                         use_admin_context=False,
                                         microversion=mv.get_prior_version(
                                             mv.SUPPORT_VOLUME_TYPE_FILTER))
        self.assertEqual(4, len(volume_types))

        # Test filter volume type with extra specs
        volume_types = _get_volume_types('{"key1":"value1"}')
        self.assertEqual(1, len(volume_types))
        self.assertDictEqual({'key1': 'value1',
                              'RESKEY:availability_zones': 'az1,az2'},
                             volume_types[0]['extra_specs'])

        # Test filter volume type with 'availability_zones'
        volume_types = _get_volume_types('{"RESKEY:availability_zones":"az1"}')
        self.assertEqual(2, len(volume_types))
        self.assertEqual(
            ['volume_type1', 'volume_type2'],
            sorted([az['name'] for az in volume_types]))

        # Test ability for non-admin to filter with user visible extra specs
        volume_types = _get_volume_types('{"RESKEY:availability_zones":"az1"}',
                                         use_admin_context=False)
        self.assertEqual(2, len(volume_types))
        self.assertEqual(
            ['volume_type1', 'volume_type2'],
            sorted([az['name'] for az in volume_types]))

        # Test inability for non-admin to filter with sensitive extra specs
        volume_types = _get_volume_types('{"key1":"value1"}',
                                         use_admin_context=False)
        self.assertEqual(0, len(volume_types))

    def test_delete_non_project_default_type(self):
        type = self._create_volume_type(self.ctxt, 'type1')
        db.project_default_volume_type_set(
            self.ctxt, fake.VOLUME_TYPE_ID, fake.PROJECT_ID)
        volume_types.destroy(self.ctxt, type.id)
        self.assertRaises(exception.VolumeTypeNotFound,
                          volume_types.get_by_name_or_id,
                          self.ctxt, type.id)

    def test_cannot_delete_project_default_type(self):
        default_type = db.project_default_volume_type_set(
            self.ctxt, fake.VOLUME_TYPE_ID, fake.PROJECT_ID)
        self.assertRaises(exception.VolumeTypeDefaultDeletionError,
                          volume_types.destroy,
                          self.ctxt, default_type['volume_type_id'])
