# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack Foundation
# Copyright 2011 University of Southern California
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
"""
Unit Tests for volume types extra specs code
"""

from cinder import context
from cinder import db
from cinder import test


class VolumeTypeExtraSpecsTestCase(test.TestCase):

    def setUp(self):
        super(VolumeTypeExtraSpecsTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.vol_type1 = dict(name="TEST: Regular volume test")
        self.vol_type1_specs = dict(vol_extra1="value1",
                                    vol_extra2="value2",
                                    vol_extra3=3)
        self.vol_type1['extra_specs'] = self.vol_type1_specs
        ref = db.volume_type_create(self.context, self.vol_type1)
        self.addCleanup(db.volume_type_destroy, context.get_admin_context(),
                        self.vol_type1['id'])
        self.volume_type1_id = ref.id
        for k, v in self.vol_type1_specs.iteritems():
            self.vol_type1_specs[k] = str(v)

        self.vol_type2_noextra = dict(name="TEST: Volume type without extra")
        ref = db.volume_type_create(self.context, self.vol_type2_noextra)
        self.addCleanup(db.volume_type_destroy, context.get_admin_context(),
                        self.vol_type2_noextra['id'])
        self.vol_type2_id = ref.id

    def test_volume_type_specs_get(self):
        expected_specs = self.vol_type1_specs.copy()
        actual_specs = db.volume_type_extra_specs_get(
            context.get_admin_context(),
            self.volume_type1_id)
        self.assertEqual(expected_specs, actual_specs)

    def test_volume_type_extra_specs_delete(self):
        expected_specs = self.vol_type1_specs.copy()
        del expected_specs['vol_extra2']
        db.volume_type_extra_specs_delete(context.get_admin_context(),
                                          self.volume_type1_id,
                                          'vol_extra2')
        actual_specs = db.volume_type_extra_specs_get(
            context.get_admin_context(),
            self.volume_type1_id)
        self.assertEqual(expected_specs, actual_specs)

    def test_volume_type_extra_specs_update(self):
        expected_specs = self.vol_type1_specs.copy()
        expected_specs['vol_extra3'] = "4"
        db.volume_type_extra_specs_update_or_create(
            context.get_admin_context(),
            self.volume_type1_id,
            dict(vol_extra3=4))
        actual_specs = db.volume_type_extra_specs_get(
            context.get_admin_context(),
            self.volume_type1_id)
        self.assertEqual(expected_specs, actual_specs)

    def test_volume_type_extra_specs_create(self):
        expected_specs = self.vol_type1_specs.copy()
        expected_specs['vol_extra4'] = 'value4'
        expected_specs['vol_extra5'] = 'value5'
        db.volume_type_extra_specs_update_or_create(
            context.get_admin_context(),
            self.volume_type1_id,
            dict(vol_extra4="value4",
                 vol_extra5="value5"))
        actual_specs = db.volume_type_extra_specs_get(
            context.get_admin_context(),
            self.volume_type1_id)
        self.assertEqual(expected_specs, actual_specs)

    def test_volume_type_get_with_extra_specs(self):
        volume_type = db.volume_type_get(
            context.get_admin_context(),
            self.volume_type1_id)
        self.assertEqual(volume_type['extra_specs'], self.vol_type1_specs)

        volume_type = db.volume_type_get(
            context.get_admin_context(),
            self.vol_type2_id)
        self.assertEqual(volume_type['extra_specs'], {})

    def test_volume_type_get_by_name_with_extra_specs(self):
        volume_type = db.volume_type_get_by_name(
            context.get_admin_context(),
            self.vol_type1['name'])
        self.assertEqual(volume_type['extra_specs'], self.vol_type1_specs)

        volume_type = db.volume_type_get_by_name(
            context.get_admin_context(),
            self.vol_type2_noextra['name'])
        self.assertEqual(volume_type['extra_specs'], {})

    def test_volume_type_get_all(self):
        expected_specs = self.vol_type1_specs.copy()

        types = db.volume_type_get_all(context.get_admin_context())

        self.assertEqual(
            types[self.vol_type1['name']]['extra_specs'], expected_specs)

        self.assertEqual(
            types[self.vol_type2_noextra['name']]['extra_specs'], {})
