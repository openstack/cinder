
# Copyright (c) 2013 eBay Inc.
# Copyright (c) 2013 OpenStack Foundation
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
"""
Unit Tests for qos specs internal API
"""

import time

from oslo_db import exception as db_exc

from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.volume import qos_specs
from cinder.volume import volume_types


def fake_db_qos_specs_create(context, values):
    if values['name'] == 'DupQoSName':
        raise exception.QoSSpecsExists(specs_id=values['name'])
    elif values['name'] == 'FailQoSName':
        raise db_exc.DBError()

    pass


class QoSSpecsTestCase(test.TestCase):
    """Test cases for qos specs code."""
    def setUp(self):
        super(QoSSpecsTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

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

    def test_create(self):
        input = {'key1': 'value1',
                 'key2': 'value2',
                 'key3': 'value3'}
        ref = qos_specs.create(self.ctxt, 'FakeName', input)
        specs = qos_specs.get_qos_specs(self.ctxt, ref['id'])
        expected = (dict(consumer='back-end'))
        expected.update(dict(id=ref['id']))
        expected.update(dict(name='FakeName'))
        del input['consumer']
        expected.update(dict(specs=input))
        self.assertDictMatch(specs, expected)

        self.stubs.Set(db, 'qos_specs_create',
                       fake_db_qos_specs_create)

        # qos specs must have unique name
        self.assertRaises(exception.QoSSpecsExists,
                          qos_specs.create, self.ctxt, 'DupQoSName', input)

        input.update({'consumer': 'FakeConsumer'})
        # consumer must be one of: front-end, back-end, both
        self.assertRaises(exception.InvalidQoSSpecs,
                          qos_specs.create, self.ctxt, 'QoSName', input)

        del input['consumer']
        # able to catch DBError
        self.assertRaises(exception.QoSSpecsCreateFailed,
                          qos_specs.create, self.ctxt, 'FailQoSName', input)

    def test_update(self):
        def fake_db_update(context, specs_id, values):
            raise db_exc.DBError()

        input = {'key1': 'value1',
                 'consumer': 'WrongPlace'}
        # consumer must be one of: front-end, back-end, both
        self.assertRaises(exception.InvalidQoSSpecs,
                          qos_specs.update, self.ctxt, 'fake_id', input)

        input['consumer'] = 'front-end'
        # qos specs must exists
        self.assertRaises(exception.QoSSpecsNotFound,
                          qos_specs.update, self.ctxt, 'fake_id', input)

        specs_id = self._create_qos_specs('Name', input)
        qos_specs.update(self.ctxt, specs_id,
                         {'key1': 'newvalue1',
                          'key2': 'value2'})
        specs = qos_specs.get_qos_specs(self.ctxt, specs_id)
        self.assertEqual('newvalue1', specs['specs']['key1'])
        self.assertEqual('value2', specs['specs']['key2'])

        self.stubs.Set(db, 'qos_specs_update', fake_db_update)
        self.assertRaises(exception.QoSSpecsUpdateFailed,
                          qos_specs.update, self.ctxt, 'fake_id', input)

    def test_delete(self):
        def fake_db_associations_get(context, id):
            if id == 'InUse':
                return True
            else:
                return False

        def fake_db_delete(context, id):
            if id == 'NotFound':
                raise exception.QoSSpecsNotFound(specs_id=id)

        def fake_disassociate_all(context, id):
            pass

        self.stubs.Set(db, 'qos_specs_associations_get',
                       fake_db_associations_get)
        self.stubs.Set(qos_specs, 'disassociate_all',
                       fake_disassociate_all)
        self.stubs.Set(db, 'qos_specs_delete', fake_db_delete)
        self.assertRaises(exception.InvalidQoSSpecs,
                          qos_specs.delete, self.ctxt, None)
        self.assertRaises(exception.QoSSpecsNotFound,
                          qos_specs.delete, self.ctxt, 'NotFound')
        self.assertRaises(exception.QoSSpecsInUse,
                          qos_specs.delete, self.ctxt, 'InUse')
        # able to delete in-use qos specs if force=True
        qos_specs.delete(self.ctxt, 'InUse', force=True)

    def test_delete_keys(self):
        def fake_db_qos_delete_key(context, id, key):
            if key == 'NotFound':
                raise exception.QoSSpecsKeyNotFound(specs_id=id,
                                                    specs_key=key)
            else:
                pass

        def fake_qos_specs_get(context, id):
            if id == 'NotFound':
                raise exception.QoSSpecsNotFound(specs_id=id)
            else:
                pass

        value = dict(consumer='front-end',
                     foo='Foo', bar='Bar', zoo='tiger')
        specs_id = self._create_qos_specs('QoSName', value)
        qos_specs.delete_keys(self.ctxt, specs_id, ['foo', 'bar'])
        del value['consumer']
        del value['foo']
        del value['bar']
        expected = {'name': 'QoSName',
                    'id': specs_id,
                    'consumer': 'front-end',
                    'specs': value}
        specs = qos_specs.get_qos_specs(self.ctxt, specs_id)
        self.assertDictMatch(expected, specs)

        self.stubs.Set(qos_specs, 'get_qos_specs', fake_qos_specs_get)
        self.stubs.Set(db, 'qos_specs_item_delete', fake_db_qos_delete_key)
        self.assertRaises(exception.InvalidQoSSpecs,
                          qos_specs.delete_keys, self.ctxt, None, [])
        self.assertRaises(exception.QoSSpecsNotFound,
                          qos_specs.delete_keys, self.ctxt, 'NotFound', [])
        self.assertRaises(exception.QoSSpecsKeyNotFound,
                          qos_specs.delete_keys, self.ctxt,
                          'Found', ['NotFound'])
        self.assertRaises(exception.QoSSpecsKeyNotFound,
                          qos_specs.delete_keys, self.ctxt, 'Found',
                          ['foo', 'bar', 'NotFound'])

    def test_get_associations(self):
        def fake_db_associate_get(context, id):
            if id == 'Trouble':
                raise db_exc.DBError()
            return [{'name': 'type-1', 'id': 'id-1'},
                    {'name': 'type-2', 'id': 'id-2'}]

        self.stubs.Set(db, 'qos_specs_associations_get',
                       fake_db_associate_get)
        expected1 = {'association_type': 'volume_type',
                     'name': 'type-1',
                     'id': 'id-1'}
        expected2 = {'association_type': 'volume_type',
                     'name': 'type-2',
                     'id': 'id-2'}
        res = qos_specs.get_associations(self.ctxt, 'specs-id')
        self.assertIn(expected1, res)
        self.assertIn(expected2, res)

        self.assertRaises(exception.CinderException,
                          qos_specs.get_associations, self.ctxt,
                          'Trouble')

    def test_associate_qos_with_type(self):
        def fake_qos_specs_get(context, id):
            if id == 'NotFound':
                raise exception.QoSSpecsNotFound(specs_id=id)
            else:
                pass

        def fake_db_associate(context, id, type_id):
            if id == 'Trouble':
                raise db_exc.DBError()
            elif type_id == 'NotFound':
                raise exception.VolumeTypeNotFound(volume_type_id=type_id)
            pass

        def fake_vol_type_qos_get(type_id):
            if type_id == 'Invalid':
                return {'qos_specs': {'id': 'Invalid'}}
            else:
                return {'qos_specs': None}

        type_ref = volume_types.create(self.ctxt, 'TypeName')
        specs_id = self._create_qos_specs('QoSName')

        qos_specs.associate_qos_with_type(self.ctxt, specs_id,
                                          type_ref['id'])
        res = qos_specs.get_associations(self.ctxt, specs_id)
        self.assertEqual(1, len(res))
        self.assertEqual('TypeName', res[0]['name'])
        self.assertEqual(type_ref['id'], res[0]['id'])

        self.stubs.Set(db, 'qos_specs_associate',
                       fake_db_associate)
        self.stubs.Set(qos_specs, 'get_qos_specs', fake_qos_specs_get)
        self.stubs.Set(volume_types, 'get_volume_type_qos_specs',
                       fake_vol_type_qos_get)
        self.assertRaises(exception.VolumeTypeNotFound,
                          qos_specs.associate_qos_with_type,
                          self.ctxt, 'specs-id', 'NotFound')
        self.assertRaises(exception.QoSSpecsAssociateFailed,
                          qos_specs.associate_qos_with_type,
                          self.ctxt, 'Trouble', 'id')
        self.assertRaises(exception.QoSSpecsNotFound,
                          qos_specs.associate_qos_with_type,
                          self.ctxt, 'NotFound', 'id')
        self.assertRaises(exception.InvalidVolumeType,
                          qos_specs.associate_qos_with_type,
                          self.ctxt, 'specs-id', 'Invalid')

    def test_disassociate_qos_specs(self):
        def fake_qos_specs_get(context, id):
            if id == 'NotFound':
                raise exception.QoSSpecsNotFound(specs_id=id)
            else:
                pass

        def fake_db_disassociate(context, id, type_id):
            if id == 'Trouble':
                raise db_exc.DBError()
            elif type_id == 'NotFound':
                raise exception.VolumeTypeNotFound(volume_type_id=type_id)
            pass

        type_ref = volume_types.create(self.ctxt, 'TypeName')
        specs_id = self._create_qos_specs('QoSName')

        qos_specs.associate_qos_with_type(self.ctxt, specs_id,
                                          type_ref['id'])
        res = qos_specs.get_associations(self.ctxt, specs_id)
        self.assertEqual(1, len(res))

        qos_specs.disassociate_qos_specs(self.ctxt, specs_id, type_ref['id'])
        res = qos_specs.get_associations(self.ctxt, specs_id)
        self.assertEqual(0, len(res))

        self.stubs.Set(db, 'qos_specs_disassociate',
                       fake_db_disassociate)
        self.stubs.Set(qos_specs, 'get_qos_specs',
                       fake_qos_specs_get)
        self.assertRaises(exception.VolumeTypeNotFound,
                          qos_specs.disassociate_qos_specs,
                          self.ctxt, 'specs-id', 'NotFound')
        self.assertRaises(exception.QoSSpecsDisassociateFailed,
                          qos_specs.disassociate_qos_specs,
                          self.ctxt, 'Trouble', 'id')

    def test_disassociate_all(self):
        def fake_db_disassociate_all(context, id):
            if id == 'Trouble':
                raise db_exc.DBError()
            pass

        def fake_qos_specs_get(context, id):
            if id == 'NotFound':
                raise exception.QoSSpecsNotFound(specs_id=id)
            else:
                pass

        type1_ref = volume_types.create(self.ctxt, 'TypeName1')
        type2_ref = volume_types.create(self.ctxt, 'TypeName2')
        specs_id = self._create_qos_specs('QoSName')

        qos_specs.associate_qos_with_type(self.ctxt, specs_id,
                                          type1_ref['id'])
        qos_specs.associate_qos_with_type(self.ctxt, specs_id,
                                          type2_ref['id'])
        res = qos_specs.get_associations(self.ctxt, specs_id)
        self.assertEqual(2, len(res))

        qos_specs.disassociate_all(self.ctxt, specs_id)
        res = qos_specs.get_associations(self.ctxt, specs_id)
        self.assertEqual(0, len(res))

        self.stubs.Set(db, 'qos_specs_disassociate_all',
                       fake_db_disassociate_all)
        self.stubs.Set(qos_specs, 'get_qos_specs',
                       fake_qos_specs_get)
        self.assertRaises(exception.QoSSpecsDisassociateFailed,
                          qos_specs.disassociate_all,
                          self.ctxt, 'Trouble')

    def test_get_all_specs(self):
        input = {'key1': 'value1',
                 'key2': 'value2',
                 'key3': 'value3',
                 'consumer': 'both'}
        specs_id1 = self._create_qos_specs('Specs1', input)
        input.update({'key4': 'value4'})
        specs_id2 = self._create_qos_specs('Specs2', input)

        expected1 = {
            'id': specs_id1,
            'name': 'Specs1',
            'consumer': 'both',
            'specs': {'key1': 'value1',
                      'key2': 'value2',
                      'key3': 'value3'}}
        expected2 = {
            'id': specs_id2,
            'name': 'Specs2',
            'consumer': 'both',
            'specs': {'key1': 'value1',
                      'key2': 'value2',
                      'key3': 'value3',
                      'key4': 'value4'}}
        res = qos_specs.get_all_specs(self.ctxt)
        self.assertEqual(2, len(res))
        self.assertIn(expected1, res)
        self.assertIn(expected2, res)

    def test_get_qos_specs(self):
        one_time_value = str(int(time.time()))
        input = {'key1': one_time_value,
                 'key2': 'value2',
                 'key3': 'value3',
                 'consumer': 'both'}
        id = self._create_qos_specs('Specs1', input)
        specs = qos_specs.get_qos_specs(self.ctxt, id)
        self.assertEqual(one_time_value, specs['specs']['key1'])

        self.assertRaises(exception.InvalidQoSSpecs,
                          qos_specs.get_qos_specs, self.ctxt, None)

    def test_get_qos_specs_by_name(self):
        one_time_value = str(int(time.time()))
        input = {'key1': one_time_value,
                 'key2': 'value2',
                 'key3': 'value3',
                 'consumer': 'back-end'}
        self._create_qos_specs(one_time_value, input)
        specs = qos_specs.get_qos_specs_by_name(self.ctxt,
                                                one_time_value)
        self.assertEqual(one_time_value, specs['specs']['key1'])

        self.assertRaises(exception.InvalidQoSSpecs,
                          qos_specs.get_qos_specs_by_name, self.ctxt, None)
