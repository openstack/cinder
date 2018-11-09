# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack Foundation
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
"""Unit Tests for volume types code."""


import datetime
import mock
import time

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_utils import uuidutils

from cinder import context
from cinder import db
from cinder.db.sqlalchemy import api as db_api
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import test
from cinder.tests.unit import conf_fixture
from cinder.tests.unit import fake_constants as fake
from cinder.volume import qos_specs
from cinder.volume import volume_types


class VolumeTypeTestCase(test.TestCase):
    """Test cases for volume type code."""
    def setUp(self):
        super(VolumeTypeTestCase, self).setUp()

        self.ctxt = context.get_admin_context()
        self.vol_type1_name = str(int(time.time()))
        self.vol_type1_specs = dict(type="physical drive",
                                    drive_type="SAS",
                                    size="300",
                                    rpm="7200",
                                    visible="True")
        self.vol_type1_description = self.vol_type1_name + '_desc'

    def test_volume_type_destroy_with_encryption(self):
        volume_type = volume_types.create(self.ctxt, "type1")
        volume_type_id = volume_type.get('id')

        encryption = {
            'control_location': 'front-end',
            'provider': 'fake_provider',
        }
        db_api.volume_type_encryption_create(self.ctxt, volume_type_id,
                                             encryption)
        ret = volume_types.get_volume_type_encryption(self.ctxt,
                                                      volume_type_id)
        self.assertIsNotNone(ret)

        volume_types.destroy(self.ctxt, volume_type_id)
        ret = volume_types.get_volume_type_encryption(self.ctxt,
                                                      volume_type_id)
        self.assertIsNone(ret)

    def test_get_volume_type_by_name_with_uuid_name(self):
        """Ensure volume types can be created and found."""
        uuid_format_name = uuidutils.generate_uuid()
        volume_types.create(self.ctxt, uuid_format_name,
                            self.vol_type1_specs,
                            description=self.vol_type1_description)
        type_ref = volume_types.get_by_name_or_id(self.ctxt,
                                                  uuid_format_name)
        self.assertEqual(uuid_format_name, type_ref['name'])

    def test_volume_type_create_then_destroy(self):
        """Ensure volume types can be created and deleted."""
        project_id = fake.PROJECT_ID
        prev_all_vtypes = volume_types.get_all_types(self.ctxt)

        # create
        type_ref = volume_types.create(self.ctxt,
                                       self.vol_type1_name,
                                       self.vol_type1_specs,
                                       description=self.vol_type1_description,
                                       projects=[project_id], is_public=False)
        new = volume_types.get_volume_type_by_name(self.ctxt,
                                                   self.vol_type1_name)

        self.assertEqual(self.vol_type1_description, new['description'])

        for k, v in self.vol_type1_specs.items():
            self.assertEqual(v, new['extra_specs'][k],
                             'one of fields does not match')

        new_all_vtypes = volume_types.get_all_types(self.ctxt)
        self.assertEqual(len(prev_all_vtypes) + 1,
                         len(new_all_vtypes),
                         'drive type was not created')
        # Assert that volume type is associated to a project
        vol_type_access = db.volume_type_access_get_all(self.ctxt,
                                                        type_ref['id'])
        self.assertIn(project_id, [a.project_id for a in vol_type_access])

        # update
        new_type_name = self.vol_type1_name + '_updated'
        new_type_desc = self.vol_type1_description + '_updated'
        volume_types.update(self.ctxt, type_ref.id, new_type_name,
                            new_type_desc)
        type_ref_updated = volume_types.get_volume_type(self.ctxt, type_ref.id)
        self.assertEqual(new_type_name, type_ref_updated['name'])
        self.assertEqual(new_type_desc, type_ref_updated['description'])

        # destroy
        volume_types.destroy(self.ctxt, type_ref['id'])
        new_all_vtypes = volume_types.get_all_types(self.ctxt)
        self.assertEqual(prev_all_vtypes,
                         new_all_vtypes,
                         'drive type was not deleted')
        # Assert that associated volume type access is deleted successfully
        # on destroying the volume type
        vol_type_access = db_api._volume_type_access_query(
            self.ctxt).filter_by(volume_type_id=type_ref['id']).all()
        self.assertEqual([], vol_type_access)

    @mock.patch('cinder.quota.VolumeTypeQuotaEngine.'
                'update_quota_resource')
    def test_update_volume_type_name(self, mock_update_quota):
        type_ref = volume_types.create(self.ctxt,
                                       self.vol_type1_name,
                                       self.vol_type1_specs,
                                       description=self.vol_type1_description)
        new_type_name = self.vol_type1_name + '_updated'
        volume_types.update(self.ctxt,
                            type_ref.id,
                            new_type_name,
                            None)
        mock_update_quota.assert_called_once_with(self.ctxt,
                                                  self.vol_type1_name,
                                                  new_type_name)
        volume_types.destroy(self.ctxt, type_ref.id)

    @mock.patch('cinder.quota.VolumeTypeQuotaEngine.'
                'update_quota_resource')
    def test_update_volume_type_name_with_db_error(self, mock_update_quota):
        type_ref = volume_types.create(self.ctxt,
                                       self.vol_type1_name,
                                       self.vol_type1_specs,
                                       description=self.vol_type1_description)
        mock_update_quota.side_effect = db_exc.DBError
        new_type_name = self.vol_type1_name + '_updated'
        description = 'new_test'
        is_public = False
        self.assertRaises(exception.VolumeTypeUpdateFailed,
                          volume_types.update, self.ctxt, type_ref.id,
                          new_type_name, description, is_public)
        mock_update_quota.assert_called_once_with(self.ctxt,
                                                  self.vol_type1_name,
                                                  new_type_name)
        new = volume_types.get_volume_type_by_name(self.ctxt,
                                                   self.vol_type1_name)
        self.assertEqual(self.vol_type1_name, new.get('name'))
        self.assertEqual(self.vol_type1_description, new.get('description'))
        self.assertTrue(new.get('is_public'))
        volume_types.destroy(self.ctxt, type_ref.id)

    def test_volume_type_create_then_destroy_with_non_admin(self):
        """Ensure volume types can be created and deleted by non-admin user.

        If a non-admn user is authorized at API, volume type operations
        should be permitted.
        """
        prev_all_vtypes = volume_types.get_all_types(self.ctxt)
        self.ctxt = context.RequestContext('fake', 'fake', is_admin=False)

        # create
        type_ref = volume_types.create(self.ctxt,
                                       self.vol_type1_name,
                                       self.vol_type1_specs,
                                       description=self.vol_type1_description)
        new = volume_types.get_volume_type_by_name(self.ctxt,
                                                   self.vol_type1_name)
        self.assertEqual(self.vol_type1_description, new['description'])
        new_all_vtypes = volume_types.get_all_types(self.ctxt)
        self.assertEqual(len(prev_all_vtypes) + 1,
                         len(new_all_vtypes),
                         'drive type was not created')

        # update
        new_type_name = self.vol_type1_name + '_updated'
        new_type_desc = self.vol_type1_description + '_updated'
        volume_types.update(self.ctxt, type_ref.id, new_type_name,
                            new_type_desc)
        type_ref_updated = volume_types.get_volume_type(self.ctxt, type_ref.id)
        self.assertEqual(new_type_name, type_ref_updated['name'])
        self.assertEqual(new_type_desc, type_ref_updated['description'])

        # destroy
        volume_types.destroy(self.ctxt, type_ref['id'])
        new_all_vtypes = volume_types.get_all_types(self.ctxt)
        self.assertEqual(prev_all_vtypes,
                         new_all_vtypes,
                         'drive type was not deleted')

    def test_create_volume_type_with_invalid_params(self):
        """Ensure exception will be returned."""
        vol_type_invalid_specs = "invalid_extra_specs"

        self.assertRaises(exception.VolumeTypeCreateFailed,
                          volume_types.create, self.ctxt,
                          self.vol_type1_name,
                          vol_type_invalid_specs)

    def test_get_all_volume_types(self):
        """Ensures that all volume types can be retrieved."""
        session = db_api.get_session()
        total_volume_types = session.query(models.VolumeType).count()
        vol_types = volume_types.get_all_types(self.ctxt)
        self.assertEqual(total_volume_types, len(vol_types))

    def test_get_default_volume_type(self):
        """Ensures default volume type can be retrieved."""
        volume_types.create(self.ctxt, conf_fixture.def_vol_type, {})
        default_vol_type = volume_types.get_default_volume_type()
        self.assertEqual(conf_fixture.def_vol_type,
                         default_vol_type.get('name'))

    def test_default_volume_type_missing_in_db(self):
        """Test default volume type is missing in database.

        Ensures proper exception raised if default volume type
        is not in database.
        """
        default_vol_type = volume_types.get_default_volume_type()
        self.assertEqual({}, default_vol_type)

    def test_get_default_volume_type_under_non_default(self):
        cfg.CONF.set_default('default_volume_type', None)

        self.assertEqual({}, volume_types.get_default_volume_type())

    def test_non_existent_vol_type_shouldnt_delete(self):
        """Ensures that volume type creation fails with invalid args."""
        self.assertRaises(exception.VolumeTypeNotFound,
                          volume_types.destroy, self.ctxt, "sfsfsdfdfs")

    def test_volume_type_with_volumes_shouldnt_delete(self):
        """Ensures volume type deletion with associated volumes fail."""
        type_ref = volume_types.create(self.ctxt, self.vol_type1_name)
        db.volume_create(self.ctxt,
                         {'id': '1',
                          'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                          'display_description': 'Test Desc',
                          'size': 20,
                          'status': 'available',
                          'volume_type_id': type_ref['id']})
        self.assertRaises(exception.VolumeTypeInUse,
                          volume_types.destroy, self.ctxt, type_ref['id'])

    def test_repeated_vol_types_shouldnt_raise(self):
        """Ensures that volume duplicates don't raise."""
        new_name = self.vol_type1_name + "dup"
        type_ref = volume_types.create(self.ctxt, new_name)
        volume_types.destroy(self.ctxt, type_ref['id'])
        type_ref = volume_types.create(self.ctxt, new_name)

    def test_invalid_volume_types_params(self):
        """Ensures that volume type creation fails with invalid args."""
        self.assertRaises(exception.InvalidVolumeType,
                          volume_types.destroy, self.ctxt, None)
        self.assertRaises(exception.InvalidVolumeType,
                          volume_types.get_volume_type, self.ctxt, None)
        self.assertRaises(exception.InvalidVolumeType,
                          volume_types.get_volume_type_by_name,
                          self.ctxt, None)

    def test_volume_type_get_by_id_and_name(self):
        """Ensure volume types get returns same entry."""
        volume_types.create(self.ctxt,
                            self.vol_type1_name,
                            self.vol_type1_specs)
        new = volume_types.get_volume_type_by_name(self.ctxt,
                                                   self.vol_type1_name)

        new2 = volume_types.get_volume_type(self.ctxt, new['id'])
        self.assertEqual(new, new2)

    def test_volume_type_search_by_extra_spec(self):
        """Ensure volume types get by extra spec returns correct type."""
        volume_types.create(self.ctxt, "type1", {"key1": "val1",
                                                 "key2": "val2"})
        volume_types.create(self.ctxt, "type2", {"key2": "val2",
                                                 "key3": "val3"})
        volume_types.create(self.ctxt, "type3", {"key3": "another_value",
                                                 "key4": "val4"})

        vol_types = volume_types.get_all_types(
            self.ctxt,
            filters={'extra_specs': {"key1": "val1"}})
        self.assertEqual(1, len(vol_types))
        self.assertIn("type1", vol_types.keys())
        self.assertEqual({"key1": "val1", "key2": "val2"},
                         vol_types['type1']['extra_specs'])

        vol_types = volume_types.get_all_types(
            self.ctxt,
            filters={'extra_specs': {"key2": "val2"}})
        self.assertEqual(2, len(vol_types))
        self.assertIn("type1", vol_types.keys())
        self.assertIn("type2", vol_types.keys())

        vol_types = volume_types.get_all_types(
            self.ctxt,
            filters={'extra_specs': {"key3": "val3"}})
        self.assertEqual(1, len(vol_types))
        self.assertIn("type2", vol_types.keys())

    def test_volume_type_search_by_extra_spec_multiple(self):
        """Ensure volume types get by extra spec returns correct type."""
        volume_types.create(self.ctxt, "type1", {"key1": "val1",
                                                 "key2": "val2",
                                                 "key3": "val3"})
        volume_types.create(self.ctxt, "type2", {"key2": "val2",
                                                 "key3": "val3"})
        volume_types.create(self.ctxt, "type3", {"key1": "val1",
                                                 "key3": "val3",
                                                 "key4": "val4"})

        vol_types = volume_types.get_all_types(
            self.ctxt,
            filters={'extra_specs': {"key1": "val1", "key3": "val3"}})
        self.assertEqual(2, len(vol_types))
        self.assertIn("type1", vol_types.keys())
        self.assertIn("type3", vol_types.keys())
        self.assertEqual({"key1": "val1", "key2": "val2", "key3": "val3"},
                         vol_types['type1']['extra_specs'])
        self.assertEqual({"key1": "val1", "key3": "val3", "key4": "val4"},
                         vol_types['type3']['extra_specs'])

    def test_is_encrypted(self):
        volume_type = volume_types.create(self.ctxt, "type1")
        volume_type_id = volume_type.get('id')
        self.assertFalse(volume_types.is_encrypted(self.ctxt, volume_type_id))

        encryption = {
            'control_location': 'front-end',
            'provider': 'fake_provider',
        }
        db_api.volume_type_encryption_create(self.ctxt, volume_type_id,
                                             encryption)
        self.assertTrue(volume_types.is_encrypted(self.ctxt, volume_type_id))

    def test_add_access(self):
        project_id = fake.PROJECT_ID
        vtype = volume_types.create(self.ctxt, 'type1', is_public=False)
        vtype_id = vtype.get('id')

        volume_types.add_volume_type_access(self.ctxt, vtype_id, project_id)
        vtype_access = db.volume_type_access_get_all(self.ctxt, vtype_id)
        self.assertIn(project_id, [a.project_id for a in vtype_access])

    def test_remove_access(self):
        project_id = fake.PROJECT_ID
        vtype = volume_types.create(self.ctxt, 'type1', projects=[project_id],
                                    is_public=False)
        vtype_id = vtype.get('id')

        volume_types.remove_volume_type_access(self.ctxt, vtype_id, project_id)
        vtype_access = db.volume_type_access_get_all(self.ctxt, vtype_id)
        self.assertNotIn(project_id, vtype_access)

    def test_add_access_with_non_admin(self):
        self.ctxt = context.RequestContext('fake', 'fake', is_admin=False)
        project_id = fake.PROJECT_ID
        vtype = volume_types.create(self.ctxt, 'type1', is_public=False)
        vtype_id = vtype.get('id')

        volume_types.add_volume_type_access(self.ctxt, vtype_id, project_id)
        vtype_access = db.volume_type_access_get_all(self.ctxt.elevated(),
                                                     vtype_id)
        self.assertIn(project_id, [a.project_id for a in vtype_access])

    def test_remove_access_with_non_admin(self):
        self.ctxt = context.RequestContext('fake', 'fake', is_admin=False)
        project_id = fake.PROJECT_ID
        vtype = volume_types.create(self.ctxt, 'type1', projects=[project_id],
                                    is_public=False)
        vtype_id = vtype.get('id')

        volume_types.remove_volume_type_access(self.ctxt, vtype_id, project_id)
        vtype_access = db.volume_type_access_get_all(self.ctxt.elevated(),
                                                     vtype_id)
        self.assertNotIn(project_id, vtype_access)

    def test_get_volume_type_qos_specs(self):
        qos_ref = qos_specs.create(self.ctxt, 'qos-specs-1', {'k1': 'v1',
                                                              'k2': 'v2',
                                                              'k3': 'v3'})
        type_ref = volume_types.create(self.ctxt, "type1", {"key2": "val2",
                                                            "key3": "val3"})
        res = volume_types.get_volume_type_qos_specs(type_ref['id'])
        self.assertIsNone(res['qos_specs'])
        qos_specs.associate_qos_with_type(self.ctxt,
                                          qos_ref['id'],
                                          type_ref['id'])

        expected = {'qos_specs': {'id': qos_ref['id'],
                                  'name': 'qos-specs-1',
                                  'consumer': 'back-end',
                                  'specs': {
                                      'k1': 'v1',
                                      'k2': 'v2',
                                      'k3': 'v3'}}}
        res = volume_types.get_volume_type_qos_specs(type_ref['id'])
        specs = db.qos_specs_get(self.ctxt, qos_ref['id'])
        expected['qos_specs']['created_at'] = specs['created_at']
        self.assertDictEqual(expected, res)

    def test_volume_types_diff(self):
        # type_ref 1 and 2 have the same extra_specs, while 3 has different
        keyvals1 = {"key1": "val1", "key2": "val2"}
        keyvals2 = {"key1": "val0", "key2": "val2"}
        type_ref1 = volume_types.create(self.ctxt, "type1", keyvals1)
        type_ref2 = volume_types.create(self.ctxt, "type2", keyvals1)
        type_ref3 = volume_types.create(self.ctxt, "type3", keyvals2)

        # Check equality with only extra_specs
        diff, same = volume_types.volume_types_diff(self.ctxt, type_ref1['id'],
                                                    type_ref2['id'])
        self.assertTrue(same)
        self.assertEqual(('val1', 'val1'), diff['extra_specs']['key1'])
        diff, same = volume_types.volume_types_diff(self.ctxt, type_ref1['id'],
                                                    type_ref3['id'])
        self.assertFalse(same)
        self.assertEqual(('val1', 'val0'), diff['extra_specs']['key1'])

        # qos_ref 1 and 2 have the same specs, while 3 has different
        qos_keyvals1 = {'k1': 'v1', 'k2': 'v2', 'k3': 'v3', 'created_at': 'v4'}
        qos_keyvals2 = {'k1': 'v0', 'k2': 'v2', 'k3': 'v3'}
        qos_ref1 = qos_specs.create(self.ctxt, 'qos-specs-1', qos_keyvals1)
        qos_ref2 = qos_specs.create(self.ctxt, 'qos-specs-2', qos_keyvals1)
        qos_ref3 = qos_specs.create(self.ctxt, 'qos-specs-3', qos_keyvals2)

        # Check equality with qos specs too
        qos_specs.associate_qos_with_type(self.ctxt, qos_ref1['id'],
                                          type_ref1['id'])
        qos_specs.associate_qos_with_type(self.ctxt, qos_ref2['id'],
                                          type_ref2['id'])
        diff, same = volume_types.volume_types_diff(self.ctxt, type_ref1['id'],
                                                    type_ref2['id'])
        self.assertTrue(same)
        self.assertEqual(('val1', 'val1'), diff['extra_specs']['key1'])
        self.assertEqual(('v1', 'v1'), diff['qos_specs']['k1'])
        qos_specs.disassociate_qos_specs(self.ctxt, qos_ref2['id'],
                                         type_ref2['id'])
        qos_specs.associate_qos_with_type(self.ctxt, qos_ref3['id'],
                                          type_ref2['id'])
        diff, same = volume_types.volume_types_diff(self.ctxt, type_ref1['id'],
                                                    type_ref2['id'])
        self.assertFalse(same)
        self.assertEqual(('val1', 'val1'), diff['extra_specs']['key1'])
        self.assertEqual(('v1', 'v0'), diff['qos_specs']['k1'])
        qos_specs.disassociate_qos_specs(self.ctxt, qos_ref3['id'],
                                         type_ref2['id'])
        qos_specs.associate_qos_with_type(self.ctxt, qos_ref2['id'],
                                          type_ref2['id'])

        # And add encryption for good measure
        enc_keyvals1 = {'cipher': 'c1', 'key_size': 256, 'provider': 'p1',
                        'control_location': 'front-end'}
        enc_keyvals2 = {'cipher': 'c1', 'key_size': 128, 'provider': 'p1',
                        'control_location': 'front-end'}
        db.volume_type_encryption_create(self.ctxt, type_ref1['id'],
                                         enc_keyvals1)
        db.volume_type_encryption_create(self.ctxt, type_ref2['id'],
                                         enc_keyvals2)
        diff, same = volume_types.volume_types_diff(self.ctxt, type_ref1['id'],
                                                    type_ref2['id'])
        self.assertFalse(same)
        self.assertEqual(('val1', 'val1'), diff['extra_specs']['key1'])
        self.assertEqual(('v1', 'v1'), diff['qos_specs']['k1'])
        self.assertEqual((256, 128), diff['encryption']['key_size'])

        # Check diff equals type specs when one type is None
        diff, same = volume_types.volume_types_diff(self.ctxt, None,
                                                    type_ref1['id'])
        self.assertFalse(same)
        self.assertEqual({'key1': (None, 'val1'), 'key2': (None, 'val2')},
                         diff['extra_specs'])
        self.assertEqual({'consumer': (None, 'back-end'),
                          'k1': (None, 'v1'),
                          'k2': (None, 'v2'),
                          'k3': (None, 'v3'),
                          'created_at': (None, 'v4')}, diff['qos_specs'])
        self.assertEqual({'cipher': (None, 'c1'),
                          'control_location': (None, 'front-end'),
                          'deleted': (None, False),
                          'key_size': (None, 256),
                          'provider': (None, 'p1')},
                         diff['encryption'])

    def test_encryption_create(self):
        volume_type = volume_types.create(self.ctxt, "type1")
        volume_type_id = volume_type.get('id')
        encryption = {
            'control_location': 'front-end',
            'provider': 'fake_provider',
        }
        db_api.volume_type_encryption_create(self.ctxt, volume_type_id,
                                             encryption)
        self.assertTrue(volume_types.is_encrypted(self.ctxt, volume_type_id))

    def test_get_volume_type_encryption(self):
        volume_type = volume_types.create(self.ctxt, "type1")
        volume_type_id = volume_type.get('id')
        encryption = {
            'control_location': 'front-end',
            'provider': 'fake_provider',
        }
        db.volume_type_encryption_create(self.ctxt, volume_type_id,
                                         encryption)

        ret = volume_types.get_volume_type_encryption(self.ctxt,
                                                      volume_type_id)
        self.assertIsNotNone(ret)

    def test_get_volume_type_encryption_without_volume_type_id(self):
        ret = volume_types.get_volume_type_encryption(self.ctxt, None)
        self.assertIsNone(ret)

    def test_check_public_volume_type_failed(self):
        project_id = fake.PROJECT_ID
        volume_type = volume_types.create(self.ctxt, "type1")
        volume_type_id = volume_type.get('id')
        self.assertRaises(exception.InvalidVolumeType,
                          volume_types.add_volume_type_access,
                          self.ctxt, volume_type_id, project_id)
        self.assertRaises(exception.InvalidVolumeType,
                          volume_types.remove_volume_type_access,
                          self.ctxt, volume_type_id, project_id)

    def test_check_private_volume_type(self):
        volume_type = volume_types.create(self.ctxt, "type1", is_public=False)
        volume_type_id = volume_type.get('id')
        self.assertFalse(volume_types.is_public_volume_type(self.ctxt,
                                                            volume_type_id))

    def test_ensure__extra_specs_for_non_admin(self):
        # non-admin users get extra-specs back in type-get/list etc at DB layer
        ctxt = context.RequestContext('average-joe',
                                      'd802f078-0af1-4e6b-8c02-7fac8d4339aa',
                                      auth_token='token',
                                      is_admin=False)
        volume_types.create(self.ctxt, "type-test", is_public=False)
        vtype = volume_types.get_volume_type_by_name(ctxt, 'type-test')
        self.assertIsNotNone(vtype.get('extra_specs', None))

    def test_ensure_extra_specs_for_admin(self):
        # admin users should get extra-specs back in type-get/list etc
        volume_types.create(self.ctxt, "type-test", is_public=False)
        vtype = volume_types.get_volume_type_by_name(self.ctxt, 'type-test')
        self.assertIsNotNone(vtype.get('extra_specs', None))

    @mock.patch('cinder.volume.volume_types.get_volume_type_encryption')
    def _exec_volume_types_encryption_changed(self, enc1, enc2,
                                              expected_result,
                                              mock_get_encryption):
        def _get_encryption(ctxt, type_id):
            if enc1 and enc1['volume_type_id'] == type_id:
                return enc1
            if enc2 and enc2['volume_type_id'] == type_id:
                return enc2
            return None

        mock_get_encryption.side_effect = _get_encryption
        actual_result = volume_types.volume_types_encryption_changed(
            self.ctxt, fake.VOLUME_TYPE_ID, fake.VOLUME_TYPE2_ID)
        self.assertEqual(expected_result, actual_result)

    def test_volume_types_encryption_changed(self):
        enc1 = {'volume_type_id': fake.VOLUME_TYPE_ID,
                'cipher': 'fake',
                'created_at': 'time1', }
        enc2 = {'volume_type_id': fake.VOLUME_TYPE2_ID,
                'cipher': 'fake',
                'created_at': 'time2', }
        self._exec_volume_types_encryption_changed(enc1, enc2, False)

    def test_volume_types_encryption_changed2(self):
        enc1 = {'volume_type_id': fake.VOLUME_TYPE_ID,
                'cipher': 'fake1',
                'created_at': 'time1', }
        enc2 = {'volume_type_id': fake.VOLUME_TYPE2_ID,
                'cipher': 'fake2',
                'created_at': 'time1', }
        self._exec_volume_types_encryption_changed(enc1, enc2, True)

    def test_volume_types_encryption_changed3(self):
        self._exec_volume_types_encryption_changed(None, None, False)

    def test_volume_types_encryption_changed4(self):
        enc1 = {'volume_type_id': fake.VOLUME_TYPE_ID,
                'cipher': 'fake1',
                'created_at': 'time1', }
        self._exec_volume_types_encryption_changed(enc1, None, True)

    @mock.patch('cinder.volume.volume_types.CONF')
    @mock.patch('cinder.volume.volume_types.rpc')
    def test_notify_about_volume_type_access_usage(self, mock_rpc,
                                                   mock_conf):
        mock_conf.host = 'host1'
        project_id = fake.PROJECT_ID
        volume_type_id = fake.VOLUME_TYPE_ID

        output = volume_types.notify_about_volume_type_access_usage(
            mock.sentinel.context,
            volume_type_id,
            project_id,
            'test_suffix')

        self.assertIsNone(output)
        mock_rpc.get_notifier.assert_called_once_with('volume_type_project',
                                                      'host1')
        mock_rpc.get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.context,
            'volume_type_project.test_suffix',
            {'volume_type_id': volume_type_id,
             'project_id': project_id})
