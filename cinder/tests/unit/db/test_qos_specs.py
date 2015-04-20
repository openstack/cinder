# Copyright (C) 2013 eBay Inc.
# Copyright (C) 2013 OpenStack Foundation
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

"""Tests for quality_of_service_specs table."""


import time

from oslo_log import log as logging

from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)


def fake_qos_specs_get_by_name(context, name, session=None, inactive=False):
    pass


class QualityOfServiceSpecsTableTestCase(test.TestCase):
    """Test case for QualityOfServiceSpecs model."""

    def setUp(self):
        super(QualityOfServiceSpecsTableTestCase, self).setUp()
        self.ctxt = context.RequestContext(user_id='user_id',
                                           project_id='project_id',
                                           is_admin=True)

    def _create_qos_specs(self, name, values=None):
        """Create a transfer object."""
        if values:
            specs = dict(name=name, qos_specs=values)
        else:
            specs = {'name': name,
                     'qos_specs': {
                         'consumer': 'back-end',
                         'key1': 'value1',
                         'key2': 'value2'}}
        return db.qos_specs_create(self.ctxt, specs)['id']

    def test_qos_specs_create(self):
        # If there is qos specs with the same name exists,
        # a QoSSpecsExists exception will be raised.
        name = 'QoSSpecsCreationTest'
        self._create_qos_specs(name)
        self.assertRaises(exception.QoSSpecsExists,
                          db.qos_specs_create, self.ctxt, dict(name=name))

        specs_id = self._create_qos_specs('NewName')
        query_id = db.qos_specs_get_by_name(
            self.ctxt, 'NewName')['id']
        self.assertEqual(specs_id, query_id)

    def test_qos_specs_get(self):
        value = dict(consumer='front-end',
                     key1='foo', key2='bar')
        specs_id = self._create_qos_specs('Name1', value)

        fake_id = 'fake-UUID'
        self.assertRaises(exception.QoSSpecsNotFound,
                          db.qos_specs_get, self.ctxt, fake_id)

        specs = db.qos_specs_get(self.ctxt, specs_id)
        expected = dict(name='Name1', id=specs_id, consumer='front-end')
        del value['consumer']
        expected.update(dict(specs=value))
        self.assertDictMatch(specs, expected)

    def test_qos_specs_get_all(self):
        value1 = dict(consumer='front-end',
                      key1='v1', key2='v2')
        value2 = dict(consumer='back-end',
                      key3='v3', key4='v4')
        value3 = dict(consumer='back-end',
                      key5='v5', key6='v6')

        spec_id1 = self._create_qos_specs('Name1', value1)
        spec_id2 = self._create_qos_specs('Name2', value2)
        spec_id3 = self._create_qos_specs('Name3', value3)

        specs = db.qos_specs_get_all(self.ctxt)
        self.assertEqual(len(specs), 3,
                         "Unexpected number of qos specs records")

        expected1 = dict(name='Name1', id=spec_id1, consumer='front-end')
        expected2 = dict(name='Name2', id=spec_id2, consumer='back-end')
        expected3 = dict(name='Name3', id=spec_id3, consumer='back-end')
        del value1['consumer']
        del value2['consumer']
        del value3['consumer']
        expected1.update(dict(specs=value1))
        expected2.update(dict(specs=value2))
        expected3.update(dict(specs=value3))
        self.assertIn(expected1, specs)
        self.assertIn(expected2, specs)
        self.assertIn(expected3, specs)

    def test_qos_specs_get_by_name(self):
        name = str(int(time.time()))
        value = dict(consumer='front-end',
                     foo='Foo', bar='Bar')
        specs_id = self._create_qos_specs(name, value)
        specs = db.qos_specs_get_by_name(self.ctxt, name)
        del value['consumer']
        expected = {'name': name,
                    'id': specs_id,
                    'consumer': 'front-end',
                    'specs': value}
        self.assertDictMatch(specs, expected)

    def test_qos_specs_delete(self):
        name = str(int(time.time()))
        specs_id = self._create_qos_specs(name)

        db.qos_specs_delete(self.ctxt, specs_id)
        self.assertRaises(exception.QoSSpecsNotFound, db.qos_specs_get,
                          self.ctxt, specs_id)

    def test_qos_specs_item_delete(self):
        name = str(int(time.time()))
        value = dict(consumer='front-end',
                     foo='Foo', bar='Bar')
        specs_id = self._create_qos_specs(name, value)

        del value['consumer']
        del value['foo']
        expected = {'name': name,
                    'id': specs_id,
                    'consumer': 'front-end',
                    'specs': value}
        db.qos_specs_item_delete(self.ctxt, specs_id, 'foo')
        specs = db.qos_specs_get_by_name(self.ctxt, name)
        self.assertDictMatch(specs, expected)

    def test_associate_type_with_qos(self):
        self.assertRaises(exception.VolumeTypeNotFound,
                          db.volume_type_qos_associate,
                          self.ctxt, 'Fake-VOLID', 'Fake-QOSID')
        type_id = volume_types.create(self.ctxt, 'TypeName')['id']
        specs_id = self._create_qos_specs('FakeQos')
        db.volume_type_qos_associate(self.ctxt, type_id, specs_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['id'], type_id)
        self.assertEqual(res[0]['qos_specs_id'], specs_id)

    def test_qos_associations_get(self):
        self.assertRaises(exception.QoSSpecsNotFound,
                          db.qos_specs_associations_get,
                          self.ctxt, 'Fake-UUID')

        type_id = volume_types.create(self.ctxt, 'TypeName')['id']
        specs_id = self._create_qos_specs('FakeQos')
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(len(res), 0)

        db.volume_type_qos_associate(self.ctxt, type_id, specs_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['id'], type_id)
        self.assertEqual(res[0]['qos_specs_id'], specs_id)

        type0_id = volume_types.create(self.ctxt, 'Type0Name')['id']
        db.volume_type_qos_associate(self.ctxt, type0_id, specs_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]['qos_specs_id'], specs_id)
        self.assertEqual(res[1]['qos_specs_id'], specs_id)

    def test_qos_specs_disassociate(self):
        type_id = volume_types.create(self.ctxt, 'TypeName')['id']
        specs_id = self._create_qos_specs('FakeQos')
        db.volume_type_qos_associate(self.ctxt, type_id, specs_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(res[0]['id'], type_id)
        self.assertEqual(res[0]['qos_specs_id'], specs_id)

        db.qos_specs_disassociate(self.ctxt, specs_id, type_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(len(res), 0)
        res = db.volume_type_get(self.ctxt, type_id)
        self.assertIsNone(res['qos_specs_id'])

    def test_qos_specs_disassociate_all(self):
        specs_id = self._create_qos_specs('FakeQos')
        type1_id = volume_types.create(self.ctxt, 'Type1Name')['id']
        type2_id = volume_types.create(self.ctxt, 'Type2Name')['id']
        type3_id = volume_types.create(self.ctxt, 'Type3Name')['id']
        db.volume_type_qos_associate(self.ctxt, type1_id, specs_id)
        db.volume_type_qos_associate(self.ctxt, type2_id, specs_id)
        db.volume_type_qos_associate(self.ctxt, type3_id, specs_id)

        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(len(res), 3)

        db.qos_specs_disassociate_all(self.ctxt, specs_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(len(res), 0)

    def test_qos_specs_update(self):
        name = 'FakeName'
        specs_id = self._create_qos_specs(name)
        value = dict(key2='new_value2', key3='value3')

        self.assertRaises(exception.QoSSpecsNotFound, db.qos_specs_update,
                          self.ctxt, 'Fake-UUID', value)
        db.qos_specs_update(self.ctxt, specs_id, value)
        specs = db.qos_specs_get(self.ctxt, specs_id)
        self.assertEqual(specs['specs']['key2'], 'new_value2')
        self.assertEqual(specs['specs']['key3'], 'value3')
