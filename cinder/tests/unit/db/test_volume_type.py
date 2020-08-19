# Copyright 2016 Intel Corp.
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

"""Tests for volume type."""

from cinder import context
from cinder import db
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.tests.unit import utils
from cinder.volume import volume_types


class VolumeTypeTestCase(test.TestCase):
    """Test cases for volume type."""

    def setUp(self):
        super(VolumeTypeTestCase, self).setUp()
        self.ctxt = context.RequestContext(user_id=fake.USER_ID,
                                           project_id=fake.PROJECT_ID,
                                           is_admin=True)

    def test_volume_type_delete(self):
        volume_type = db.volume_type_create(self.ctxt, {'name':
                                                        'fake volume type'})
        volume_types.destroy(self.ctxt, volume_type['id'])
        self.assertRaises(exception.VolumeTypeNotFound,
                          volume_types.get_by_name_or_id, self.ctxt,
                          volume_type['id'])

    def test_volume_db_delete_last_type(self):
        default = volume_types.get_default_volume_type()
        self.assertRaises(exception.VolumeTypeDeletionError,
                          db.volume_type_destroy, self.ctxt,
                          default['id'])

    def test_volume_type_delete_with_volume_in_use(self):
        volume_type = db.volume_type_create(self.ctxt, {'name':
                                                        'fake volume type'})
        volume = db.volume_create(self.ctxt, {'volume_type_id':
                                              volume_type['id']})
        self.assertRaises(exception.VolumeTypeInUse, volume_types.destroy,
                          self.ctxt, volume_type['id'])
        db.volume_destroy(self.ctxt, volume['id'])
        volume_types.destroy(self.ctxt, volume_type['id'])

    def test_volume_type_delete_with_group_in_use(self):
        volume_type = db.volume_type_create(self.ctxt, {'name':
                                                        'fake volume type'})

        group = db.group_create(self.ctxt, {})
        db.group_volume_type_mapping_create(self.ctxt, group['id'],
                                            volume_type['id'])
        self.assertRaises(exception.VolumeTypeInUse, volume_types.destroy,
                          self.ctxt, volume_type['id'])
        db.group_destroy(self.ctxt, group['id'])
        volume_types.destroy(self.ctxt, volume_type['id'])

    def test_volume_type_delete_with_consistencygroups_in_use(self):
        volume_type = db.volume_type_create(self.ctxt, {'name':
                                                        'fake volume type'})
        consistency_group1 = db.consistencygroup_create(self.ctxt,
                                                        {'volume_type_id':
                                                         volume_type['id']})
        consistency_group2 = db.consistencygroup_create(self.ctxt,
                                                        {'volume_type_id':
                                                         volume_type['id']})
        self.assertRaises(exception.VolumeTypeInUse, volume_types.destroy,
                          self.ctxt, volume_type['id'])
        db.consistencygroup_destroy(self.ctxt, consistency_group1['id'])
        self.assertRaises(exception.VolumeTypeInUse, volume_types.destroy,
                          self.ctxt, volume_type['id'])
        db.consistencygroup_destroy(self.ctxt, consistency_group2['id'])
        volume_types.destroy(self.ctxt, volume_type['id'])

    def test_volume_type_update(self):
        vol_type_ref = volume_types.create(self.ctxt, 'fake volume type')
        updates = dict(name='test_volume_type_update',
                       description=None,
                       is_public=None)
        db.volume_type_update(self.ctxt, vol_type_ref.id, updates)
        updated_vol_type = db.volume_type_get(self.ctxt, vol_type_ref.id)
        self.assertEqual('test_volume_type_update', updated_vol_type['name'])
        volume_types.destroy(self.ctxt, vol_type_ref.id)

    def test_volume_type_get_with_qos_specs(self):
        """Ensure volume types get can load qos_specs."""
        qos_data = {'name': 'qos', 'consumer': 'front-end',
                    'specs': {'key': 'value', 'key2': 'value2'}}
        qos = utils.create_qos(self.ctxt, **qos_data)
        vol_type = db.volume_type_create(self.ctxt,
                                         {'name': 'my-vol-type',
                                          'qos_specs_id': qos['id']})

        db_vol_type = db.volume_type_get(self.ctxt, vol_type.id,
                                         expected_fields=['qos_specs'])

        expected = {('QoS_Specs_Name', 'qos'), ('consumer', 'front-end'),
                    ('key', 'value'), ('key2', 'value2')}
        actual = {(spec.key, spec.value) for spec in db_vol_type['qos_specs']}
        self.assertEqual(expected, actual)

    def test_volume_type_get_with_projects(self):
        """Ensure volume types get can load projects."""
        projects = [fake.PROJECT_ID, fake.PROJECT2_ID, fake.PROJECT3_ID]
        vol_type = db.volume_type_create(self.ctxt,
                                         {'name': 'my-vol-type'},
                                         projects=projects)

        db_vol_type = db.volume_type_get(self.ctxt, vol_type.id,
                                         expected_fields=['projects'])

        self.assertEqual(set(projects), set(db_vol_type['projects']))
