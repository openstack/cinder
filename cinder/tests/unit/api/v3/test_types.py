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
from cinder.api.v2 import types
from cinder import context
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake


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
        req = fakes.HTTPRequest.blank(
            '/v3/%s/types?extra_specs={"key1":"value1"}' % fake.PROJECT_ID,
            use_admin_context=False)
        req.api_version_request = mv.get_api_version(mv.get_prior_version(
            mv.SUPPORT_VOLUME_TYPE_FILTER))
        res_dict = self.controller.index(req)

        self.assertEqual(3, len(res_dict['volume_types']))

        # Test filter volume type with extra specs
        req = fakes.HTTPRequest.blank(
            '/v3/%s/types?extra_specs={"key1":"value1"}' % fake.PROJECT_ID,
            use_admin_context=True)
        req.api_version_request = mv.get_api_version(
            mv.SUPPORT_VOLUME_TYPE_FILTER)
        res_dict = self.controller.index(req)
        self.assertEqual(1, len(res_dict['volume_types']))
        self.assertDictEqual({'key1': 'value1',
                              'RESKEY:availability_zones': 'az1,az2'},
                             res_dict['volume_types'][0]['extra_specs'])

        # Test filter volume type with 'availability_zones'
        req = fakes.HTTPRequest.blank(
            '/v3/%s/types?extra_specs={"RESKEY:availability_zones":"az1"}'
            % fake.PROJECT_ID, use_admin_context=True)
        req.api_version_request = mv.get_api_version(
            mv.SUPPORT_VOLUME_TYPE_FILTER)
        res_dict = self.controller.index(req)
        self.assertEqual(2, len(res_dict['volume_types']))
        self.assertEqual(
            ['volume_type1', 'volume_type2'],
            sorted([az['name'] for az in res_dict['volume_types']]))
