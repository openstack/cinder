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

from cinder import context
from cinder import db
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.volume import volume_types


def fake_qos_specs_get_by_name(context, name, session=None, inactive=False):
    pass


class QualityOfServiceSpecsTableTestCase(test.TestCase):
    """Test case for QualityOfServiceSpecs model."""

    def setUp(self):
        super(QualityOfServiceSpecsTableTestCase, self).setUp()
        self.ctxt = context.RequestContext(user_id=fake.USER_ID,
                                           project_id=fake.PROJECT_ID,
                                           is_admin=True)

    def _create_qos_specs(self, name, consumer='back-end', values=None):
        """Create a transfer object."""
        if values is None:
            values = {'key1': 'value1', 'key2': 'value2'}

        specs = {'name': name,
                 'consumer': consumer,
                 'specs': values}
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
        qos_spec = {'name': 'Name1',
                    'consumer': 'front-end',
                    'specs': {'key1': 'foo', 'key2': 'bar'}}
        specs_id = self._create_qos_specs(qos_spec['name'],
                                          qos_spec['consumer'],
                                          qos_spec['specs'])

        fake_id = fake.WILL_NOT_BE_FOUND_ID
        self.assertRaises(exception.QoSSpecsNotFound,
                          db.qos_specs_get, self.ctxt, fake_id)

        specs_returned = db.qos_specs_get(self.ctxt, specs_id)
        qos_spec['created_at'] = specs_returned['created_at']
        qos_spec['id'] = specs_id
        self.assertDictEqual(qos_spec, specs_returned)

    def test_qos_specs_get_all(self):
        qos_list = [
            {'name': 'Name1',
             'consumer': 'front-end',
             'specs': {'key1': 'v1', 'key2': 'v2'}},
            {'name': 'Name2',
             'consumer': 'back-end',
             'specs': {'key1': 'v3', 'key2': 'v4'}},
            {'name': 'Name3',
             'consumer': 'back-end',
             'specs': {'key1': 'v5', 'key2': 'v6'}}]

        for index, qos in enumerate(qos_list):
            qos['id'] = self._create_qos_specs(qos['name'],
                                               qos['consumer'],
                                               qos['specs'])
            specs = db.qos_specs_get(self.ctxt, qos['id'])
            qos_list[index]['created_at'] = specs['created_at']

        specs_list_returned = db.qos_specs_get_all(self.ctxt)
        self.assertEqual(len(qos_list), len(specs_list_returned),
                         "Unexpected number of qos specs records")

        for expected_qos in qos_list:
            self.assertIn(expected_qos, specs_list_returned)

    def test_qos_specs_delete(self):
        name = str(int(time.time()))
        specs_id = self._create_qos_specs(name)

        db.qos_specs_delete(self.ctxt, specs_id)
        self.assertRaises(exception.QoSSpecsNotFound,
                          db.qos_specs_get,
                          self.ctxt, specs_id)

    def test_qos_specs_item_delete(self):
        name = str(int(time.time()))
        value = dict(foo='Foo', bar='Bar')
        specs_id = self._create_qos_specs(name, 'front-end', value)

        del value['foo']
        expected = {'name': name,
                    'id': specs_id,
                    'consumer': 'front-end',
                    'specs': value}
        db.qos_specs_item_delete(self.ctxt, specs_id, 'foo')
        specs = db.qos_specs_get(self.ctxt, specs_id)
        expected['created_at'] = specs['created_at']
        self.assertDictEqual(expected, specs)

    def test_associate_type_with_qos(self):
        self.assertRaises(exception.VolumeTypeNotFound,
                          db.volume_type_qos_associate,
                          self.ctxt, fake.VOLUME_ID, fake.QOS_SPEC_ID)
        type_id = volume_types.create(self.ctxt, 'TypeName')['id']
        specs_id = self._create_qos_specs('FakeQos')
        db.volume_type_qos_associate(self.ctxt, type_id, specs_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(1, len(res))
        self.assertEqual(type_id, res[0]['id'])
        self.assertEqual(specs_id, res[0]['qos_specs_id'])

    def test_qos_associations_get(self):
        self.assertRaises(exception.QoSSpecsNotFound,
                          db.qos_specs_associations_get,
                          self.ctxt, fake.WILL_NOT_BE_FOUND_ID)

        type_id = volume_types.create(self.ctxt, 'TypeName')['id']
        specs_id = self._create_qos_specs('FakeQos')
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(0, len(res))

        db.volume_type_qos_associate(self.ctxt, type_id, specs_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(1, len(res))
        self.assertEqual(type_id, res[0]['id'])
        self.assertEqual(specs_id, res[0]['qos_specs_id'])

        type0_id = volume_types.create(self.ctxt, 'Type0Name')['id']
        db.volume_type_qos_associate(self.ctxt, type0_id, specs_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(2, len(res))
        self.assertEqual(specs_id, res[0]['qos_specs_id'])
        self.assertEqual(specs_id, res[1]['qos_specs_id'])

    def test_qos_specs_disassociate(self):
        type_id = volume_types.create(self.ctxt, 'TypeName')['id']
        specs_id = self._create_qos_specs('FakeQos')
        db.volume_type_qos_associate(self.ctxt, type_id, specs_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(type_id, res[0]['id'])
        self.assertEqual(specs_id, res[0]['qos_specs_id'])

        db.qos_specs_disassociate(self.ctxt, specs_id, type_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(0, len(res))
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
        self.assertEqual(3, len(res))

        db.qos_specs_disassociate_all(self.ctxt, specs_id)
        res = db.qos_specs_associations_get(self.ctxt, specs_id)
        self.assertEqual(0, len(res))

    def test_qos_specs_update(self):
        name = 'FakeName'
        specs_id = self._create_qos_specs(name)
        value = {'consumer': 'both',
                 'specs': {'key2': 'new_value2', 'key3': 'value3'}}

        self.assertRaises(exception.QoSSpecsNotFound, db.qos_specs_update,
                          self.ctxt, fake.WILL_NOT_BE_FOUND_ID, value)
        db.qos_specs_update(self.ctxt, specs_id, value)
        specs = db.qos_specs_get(self.ctxt, specs_id)
        value['created_at'] = specs['created_at']
        self.assertEqual('new_value2', specs['specs']['key2'])
        self.assertEqual('value3', specs['specs']['key3'])
        self.assertEqual('both', specs['consumer'])
