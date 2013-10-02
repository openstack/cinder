# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
"""
Unit Tests for volume types code
"""


import datetime
import time

from cinder import context
from cinder import db
from cinder.db.sqlalchemy import api as db_api
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder.tests import conf_fixture
from cinder.volume import qos_specs
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)


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

    def test_volume_type_create_then_destroy(self):
        """Ensure volume types can be created and deleted."""
        prev_all_vtypes = volume_types.get_all_types(self.ctxt)

        type_ref = volume_types.create(self.ctxt,
                                       self.vol_type1_name,
                                       self.vol_type1_specs)
        new = volume_types.get_volume_type_by_name(self.ctxt,
                                                   self.vol_type1_name)

        LOG.info(_("Given data: %s"), self.vol_type1_specs)
        LOG.info(_("Result data: %s"), new)

        for k, v in self.vol_type1_specs.iteritems():
            self.assertEqual(v, new['extra_specs'][k],
                             'one of fields doesnt match')

        new_all_vtypes = volume_types.get_all_types(self.ctxt)
        self.assertEqual(len(prev_all_vtypes) + 1,
                         len(new_all_vtypes),
                         'drive type was not created')

        volume_types.destroy(self.ctxt, type_ref['id'])
        new_all_vtypes = volume_types.get_all_types(self.ctxt)
        self.assertEqual(prev_all_vtypes,
                         new_all_vtypes,
                         'drive type was not deleted')

    def test_get_all_volume_types(self):
        """Ensures that all volume types can be retrieved."""
        session = db_api.get_session()
        total_volume_types = session.query(models.VolumeTypes).count()
        vol_types = volume_types.get_all_types(self.ctxt)
        self.assertEqual(total_volume_types, len(vol_types))

    def test_get_default_volume_type(self):
        """Ensures default volume type can be retrieved."""
        type_ref = volume_types.create(self.ctxt,
                                       conf_fixture.def_vol_type,
                                       {})
        default_vol_type = volume_types.get_default_volume_type()
        self.assertEqual(default_vol_type.get('name'),
                         conf_fixture.def_vol_type)

    def test_default_volume_type_missing_in_db(self):
        """Ensures proper exception raised if default volume type
        is not in database.
        """
        session = db_api.get_session()
        default_vol_type = volume_types.get_default_volume_type()
        self.assertEqual(default_vol_type, {})

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
            search_opts={'extra_specs': {"key1": "val1"}})
        LOG.info("vol_types: %s" % vol_types)
        self.assertEqual(len(vol_types), 1)
        self.assertIn("type1", vol_types.keys())
        self.assertEqual(vol_types['type1']['extra_specs'],
                         {"key1": "val1", "key2": "val2"})

        vol_types = volume_types.get_all_types(
            self.ctxt,
            search_opts={'extra_specs': {"key2": "val2"}})
        LOG.info("vol_types: %s" % vol_types)
        self.assertEqual(len(vol_types), 2)
        self.assertIn("type1", vol_types.keys())
        self.assertIn("type2", vol_types.keys())

        vol_types = volume_types.get_all_types(
            self.ctxt,
            search_opts={'extra_specs': {"key3": "val3"}})
        LOG.info("vol_types: %s" % vol_types)
        self.assertEqual(len(vol_types), 1)
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
            search_opts={'extra_specs': {"key1": "val1",
                                         "key3": "val3"}})
        LOG.info("vol_types: %s" % vol_types)
        self.assertEqual(len(vol_types), 2)
        self.assertIn("type1", vol_types.keys())
        self.assertIn("type3", vol_types.keys())
        self.assertEqual(vol_types['type1']['extra_specs'],
                         {"key1": "val1", "key2": "val2", "key3": "val3"})
        self.assertEqual(vol_types['type3']['extra_specs'],
                         {"key1": "val1", "key3": "val3", "key4": "val4"})

    def test_is_encrypted(self):
        volume_type = volume_types.create(self.ctxt, "type1")
        volume_type_id = volume_type.get('id')
        self.assertFalse(volume_types.is_encrypted(self.ctxt, volume_type_id))

        encryption = {
            'control_location': 'front-end',
            'provider': 'fake_provider',
        }
        db_api.volume_type_encryption_update_or_create(self.ctxt,
                                                       volume_type_id,
                                                       encryption)
        self.assertTrue(volume_types.is_encrypted(self.ctxt, volume_type_id))

    def test_get_volume_type_qos_specs(self):
        qos_ref = qos_specs.create(self.ctxt, 'qos-specs-1', {'k1': 'v1',
                                                              'k2': 'v2',
                                                              'k3': 'v3'})
        type_ref = volume_types.create(self.ctxt, "type1", {"key2": "val2",
                                                  "key3": "val3"})
        res = volume_types.get_volume_type_qos_specs(type_ref['id'])
        self.assertEqual(res['qos_specs'], None)
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
        self.assertDictMatch(expected, res)
