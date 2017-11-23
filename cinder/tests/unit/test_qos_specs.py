
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

import mock
import six
import time

from oslo_db import exception as db_exc
from oslo_utils import timeutils

from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder import utils
from cinder.volume import qos_specs
from cinder.volume import volume_types


def fake_db_qos_specs_create(context, values):
    if values['name'] == 'DupQoSName':
        raise exception.QoSSpecsExists(specs_id=values['name'])
    elif values['name'] == 'FailQoSName':
        raise db_exc.DBError()

    pass


def fake_db_get_vol_type(vol_type_number=1):
    return {'name': 'type-' + six.text_type(vol_type_number),
            'id': fake.QOS_SPEC_ID,
            'updated_at': None,
            'created_at': None,
            'deleted_at': None,
            'description': 'desc',
            'deleted': False,
            'is_public': True,
            'projects': [],
            'qos_specs_id': fake.QOS_SPEC_ID,
            'extra_specs': None}


class QoSSpecsTestCase(test.TestCase):
    """Test cases for qos specs code."""
    def setUp(self):
        super(QoSSpecsTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def _create_qos_specs(self, name, consumer='back-end', values=None):
        """Create a transfer object."""
        if values is None:
            values = {'key1': 'value1', 'key2': 'value2'}

        specs = {'name': name,
                 'consumer': consumer,
                 'specs': values}
        return db.qos_specs_create(self.ctxt, specs)['id']

    def test_create(self):
        input = {'key1': 'value1',
                 'key2': 'value2',
                 'key3': 'value3'}
        ref = qos_specs.create(self.ctxt, 'FakeName', input)
        specs_obj = qos_specs.get_qos_specs(self.ctxt, ref['id'])
        specs_obj_dic = {'consumer': specs_obj['consumer'],
                         'id': specs_obj['id'],
                         'name': specs_obj['name'],
                         'specs': specs_obj['specs']}
        expected = {'consumer': 'back-end',
                    'id': ref['id'],
                    'name': 'FakeName',
                    'specs': input}
        self.assertDictEqual(expected,
                             specs_obj_dic)

        # qos specs must have unique name
        self.assertRaises(exception.QoSSpecsExists,
                          qos_specs.create, self.ctxt, 'FakeName', input)

        # consumer must be one of: front-end, back-end, both
        input['consumer'] = 'fake'
        self.assertRaises(exception.InvalidQoSSpecs,
                          qos_specs.create, self.ctxt, 'QoSName', input)

        del input['consumer']

        self.mock_object(db, 'qos_specs_create',
                         fake_db_qos_specs_create)
        # able to catch DBError
        self.assertRaises(exception.QoSSpecsCreateFailed,
                          qos_specs.create, self.ctxt, 'FailQoSName', input)

    def test_update(self):
        def fake_db_update(context, specs_id, values):
            raise db_exc.DBError()

        qos = {'consumer': 'back-end',
               'specs': {'key1': 'value1'}}

        # qos specs must exists
        self.assertRaises(exception.QoSSpecsNotFound,
                          qos_specs.update, self.ctxt, 'fake_id', qos['specs'])

        specs_id = self._create_qos_specs('Name',
                                          qos['consumer'],
                                          qos['specs'])

        qos_specs.update(self.ctxt, specs_id,
                         {'key1': 'newvalue1', 'key2': 'value2'})

        specs = qos_specs.get_qos_specs(self.ctxt, specs_id)
        self.assertEqual('newvalue1', specs['specs']['key1'])
        self.assertEqual('value2', specs['specs']['key2'])

        # consumer must be one of: front-end, back-end, both
        self.assertRaises(exception.InvalidQoSSpecs,
                          qos_specs.update, self.ctxt, specs_id,
                          {'consumer': 'not-real'})

        self.mock_object(db, 'qos_specs_update', fake_db_update)
        self.assertRaises(exception.QoSSpecsUpdateFailed,
                          qos_specs.update, self.ctxt, specs_id, {'key':
                                                                  'new_key'})

    def test_delete(self):
        qos_id = self._create_qos_specs('my_qos')

        def fake_db_associations_get(context, id):
            vol_types = []
            if id == qos_id:
                vol_types = [fake_db_get_vol_type(id)]
            return vol_types

        def fake_db_delete(context, id):
            return {'deleted': True,
                    'deleted_at': timeutils.utcnow()}

        def fake_disassociate_all(context, id):
            pass

        self.mock_object(db, 'qos_specs_associations_get',
                         fake_db_associations_get)
        self.mock_object(qos_specs, 'disassociate_all',
                         fake_disassociate_all)
        self.mock_object(db, 'qos_specs_delete', fake_db_delete)
        self.assertRaises(exception.InvalidQoSSpecs,
                          qos_specs.delete, self.ctxt, None)
        self.assertRaises(exception.QoSSpecsNotFound,
                          qos_specs.delete, self.ctxt, 'NotFound')
        self.assertRaises(exception.QoSSpecsInUse,
                          qos_specs.delete, self.ctxt, qos_id)
        # able to delete in-use qos specs if force=True
        qos_specs.delete(self.ctxt, qos_id, force=True)

        # Can delete without forcing when no volume types
        qos_id_with_no_vol_types = self._create_qos_specs('no_vol_types')
        qos_specs.delete(self.ctxt, qos_id_with_no_vol_types, force=False)

    def test_delete_keys(self):
        def fake_db_qos_delete_key(context, id, key):
            if key == 'NotFound':
                raise exception.QoSSpecsKeyNotFound(specs_id=id,
                                                    specs_key=key)
            else:
                pass

        value = {'foo': 'Foo', 'bar': 'Bar', 'zoo': 'tiger'}
        name = 'QoSName'
        consumer = 'front-end'
        specs_id = self._create_qos_specs(name, consumer, value)
        qos_specs.delete_keys(self.ctxt, specs_id, ['foo', 'bar'])

        del value['foo']
        del value['bar']
        expected = {'name': name,
                    'id': specs_id,
                    'consumer': consumer,
                    'specs': value}
        specs = qos_specs.get_qos_specs(self.ctxt, specs_id)
        specs_dic = {'consumer': specs['consumer'],
                     'id': specs['id'],
                     'name': specs['name'],
                     'specs': specs['specs']}
        self.assertDictEqual(expected, specs_dic)

        self.mock_object(db, 'qos_specs_item_delete', fake_db_qos_delete_key)
        self.assertRaises(exception.InvalidQoSSpecs,
                          qos_specs.delete_keys, self.ctxt, None, [])
        self.assertRaises(exception.QoSSpecsNotFound,
                          qos_specs.delete_keys, self.ctxt, 'NotFound', [])
        self.assertRaises(exception.QoSSpecsKeyNotFound,
                          qos_specs.delete_keys, self.ctxt,
                          specs_id, ['NotFound'])
        self.assertRaises(exception.QoSSpecsKeyNotFound,
                          qos_specs.delete_keys, self.ctxt, specs_id,
                          ['foo', 'bar', 'NotFound'])

    @mock.patch.object(db, 'qos_specs_associations_get')
    def test_get_associations(self, mock_qos_specs_associations_get):
        vol_types = [fake_db_get_vol_type(x) for x in range(2)]

        mock_qos_specs_associations_get.return_value = vol_types
        specs_id = self._create_qos_specs('new_spec')
        res = qos_specs.get_associations(self.ctxt, specs_id)
        for vol_type in vol_types:
            expected_type = {
                'association_type': 'volume_type',
                'id': vol_type['id'],
                'name': vol_type['name']
            }
            self.assertIn(expected_type, res)

        e = exception.QoSSpecsNotFound(specs_id='Trouble')
        mock_qos_specs_associations_get.side_effect = e
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

        self.mock_object(db, 'qos_specs_associate',
                         fake_db_associate)
        self.mock_object(qos_specs, 'get_qos_specs', fake_qos_specs_get)
        self.mock_object(volume_types, 'get_volume_type_qos_specs',
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
        def fake_db_disassociate(context, id, type_id):
            raise db_exc.DBError()

        type_ref = volume_types.create(self.ctxt, 'TypeName')
        specs_id = self._create_qos_specs('QoSName')

        qos_specs.associate_qos_with_type(self.ctxt, specs_id,
                                          type_ref['id'])
        res = qos_specs.get_associations(self.ctxt, specs_id)
        self.assertEqual(1, len(res))

        qos_specs.disassociate_qos_specs(self.ctxt, specs_id, type_ref['id'])
        res = qos_specs.get_associations(self.ctxt, specs_id)
        self.assertEqual(0, len(res))

        self.assertRaises(exception.VolumeTypeNotFound,
                          qos_specs.disassociate_qos_specs,
                          self.ctxt, specs_id, 'NotFound')

        # Verify we can disassociate specs from volume_type even if they are
        # not associated with no error
        qos_specs.disassociate_qos_specs(self.ctxt, specs_id, type_ref['id'])
        qos_specs.associate_qos_with_type(self.ctxt, specs_id, type_ref['id'])
        self.mock_object(db, 'qos_specs_disassociate',
                         fake_db_disassociate)
        self.assertRaises(exception.QoSSpecsDisassociateFailed,
                          qos_specs.disassociate_qos_specs,
                          self.ctxt, specs_id, type_ref['id'])

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

        self.mock_object(db, 'qos_specs_disassociate_all',
                         fake_db_disassociate_all)
        self.mock_object(qos_specs, 'get_qos_specs',
                         fake_qos_specs_get)
        self.assertRaises(exception.QoSSpecsDisassociateFailed,
                          qos_specs.disassociate_all,
                          self.ctxt, 'Trouble')

    def test_get_all_specs(self):
        qos_specs_list = [{'name': 'Specs1',
                           'created_at': None,
                           'updated_at': None,
                           'deleted_at': None,
                           'deleted': None,
                           'consumer': 'both',
                           'specs': {'key1': 'value1',
                                     'key2': 'value2',
                                     'key3': 'value3'}},
                          {'name': 'Specs2',
                           'created_at': None,
                           'updated_at': None,
                           'deleted_at': None,
                           'deleted': None,
                           'consumer': 'both',
                           'specs': {'key1': 'value1',
                                     'key2': 'value2',
                                     'key3': 'value3',
                                     'key4': 'value4'}}]

        for index, qos_specs_dict in enumerate(qos_specs_list):
            qos_specs_id = self._create_qos_specs(
                qos_specs_dict['name'],
                qos_specs_dict['consumer'],
                qos_specs_dict['specs'])
            qos_specs_dict['id'] = qos_specs_id
            specs = db.qos_specs_get(self.ctxt, qos_specs_id)
            qos_specs_list[index]['created_at'] = utils.time_format(
                specs['created_at'])

        res = qos_specs.get_all_specs(self.ctxt)
        self.assertEqual(len(qos_specs_list), len(res))

        qos_res_simple_dict = []
        # Need to make list of dictionaries instead of VOs for assertIn to work
        for qos in res:
            qos_res_simple_dict.append(
                qos.obj_to_primitive()['versioned_object.data'])
        for qos_spec in qos_specs_list:
            self.assertIn(qos_spec, qos_res_simple_dict)

    def test_get_qos_specs(self):
        one_time_value = str(int(time.time()))
        specs = {'key1': one_time_value,
                 'key2': 'value2',
                 'key3': 'value3'}
        qos_id = self._create_qos_specs('Specs1', 'both', specs)
        specs = qos_specs.get_qos_specs(self.ctxt, qos_id)
        self.assertEqual(one_time_value, specs['specs']['key1'])
        self.assertRaises(exception.InvalidQoSSpecs,
                          qos_specs.get_qos_specs, self.ctxt, None)
