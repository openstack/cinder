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

import mock
from oslo_utils import timeutils
import pytz

from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import objects
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import objects as test_objects

fake_qos = {'consumer': 'front-end',
            'id': fake.OBJECT_ID,
            'name': 'qos_name',
            'specs': {'key1': 'val1', 'key2': 'val2'}}

fake_qos_no_id = fake_qos.copy()
del fake_qos_no_id['id']


class TestQos(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.db.get_by_id', return_value=fake_qos)
    def test_get_by_id(self, qos_get):
        qos_object = objects.QualityOfServiceSpecs.get_by_id(
            self.context, fake.OBJECT_ID)
        self._compare(self, fake_qos, qos_object)
        qos_get.assert_called_once_with(
            self.context, models.QualityOfServiceSpecs, fake.OBJECT_ID)

    @mock.patch('cinder.db.qos_specs_create',
                return_value={'name': 'qos_name', 'id': fake.OBJECT_ID})
    def test_create(self, qos_fake_create):
        qos_object = objects.QualityOfServiceSpecs(
            self.context, **fake_qos_no_id)
        qos_object.create()
        self._compare(self, fake_qos, qos_object)

        # Fail to create a second time
        self.assertRaises(exception.ObjectActionError, qos_object.create)

        self.assertEqual(1, len(qos_fake_create.mock_calls))

    @mock.patch('cinder.db.qos_specs_item_delete')
    @mock.patch('cinder.db.qos_specs_update')
    def test_save(self, qos_fake_update, qos_fake_delete):
        qos_dict = fake_qos.copy()
        qos_dict['specs']['key_to_remove1'] = 'val'
        qos_dict['specs']['key_to_remove2'] = 'val'
        qos_object = objects.QualityOfServiceSpecs._from_db_object(
            self.context, objects.QualityOfServiceSpecs(), qos_dict)

        qos_object.specs['key1'] = 'val1'
        qos_object.save()
        # No values have changed so no updates should be made
        self.assertFalse(qos_fake_update.called)

        qos_object.consumer = 'back-end'
        qos_object.specs['key1'] = 'val2'
        qos_object.specs['new_key'] = 'val3'

        del qos_object.specs['key_to_remove1']
        del qos_object.specs['key_to_remove2']
        qos_object.save()
        qos_fake_update.assert_called_once_with(
            self.context, fake.OBJECT_ID,
            {'specs': {'key1': 'val2', 'new_key': 'val3'},
             'consumer': 'back-end'})
        qos_fake_delete.assert_has_calls([
            mock.call(self.context, fake.OBJECT_ID, 'key_to_remove1'),
            mock.call(self.context, fake.OBJECT_ID, 'key_to_remove2')],
            any_order=True)

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=timeutils.utcnow())
    @mock.patch('cinder.objects.VolumeTypeList.get_all_types_for_qos',
                return_value=None)
    @mock.patch('cinder.db.sqlalchemy.api.qos_specs_delete')
    def test_destroy_no_vol_types(self, qos_fake_delete, fake_get_vol_types,
                                  utcnow_mock):
        qos_fake_delete.return_value = {
            'deleted': True,
            'deleted_at': utcnow_mock.return_value}
        qos_object = objects.QualityOfServiceSpecs._from_db_object(
            self.context, objects.QualityOfServiceSpecs(), fake_qos)
        qos_object.destroy()

        qos_fake_delete.assert_called_once_with(mock.ANY, fake_qos['id'])
        self.assertTrue(qos_object.deleted)
        self.assertEqual(utcnow_mock.return_value.replace(tzinfo=pytz.UTC),
                         qos_object.deleted_at)

    @mock.patch('cinder.db.sqlalchemy.api.qos_specs_delete')
    @mock.patch('cinder.db.qos_specs_disassociate_all')
    @mock.patch('cinder.objects.VolumeTypeList.get_all_types_for_qos')
    def test_destroy_with_vol_types(self, fake_get_vol_types,
                                    qos_fake_disassociate, qos_fake_delete):
        qos_object = objects.QualityOfServiceSpecs._from_db_object(
            self.context, objects.QualityOfServiceSpecs(), fake_qos)
        fake_get_vol_types.return_value = objects.VolumeTypeList(
            objects=[objects.VolumeType(id=fake.VOLUME_TYPE_ID)])
        self.assertRaises(exception.QoSSpecsInUse, qos_object.destroy)

        qos_object.destroy(force=True)
        qos_fake_delete.assert_called_once_with(mock.ANY, fake_qos['id'])
        qos_fake_disassociate.assert_called_once_with(
            self.context, fake_qos['id'])

    @mock.patch('cinder.objects.VolumeTypeList.get_all_types_for_qos',
                return_value=None)
    @mock.patch('cinder.db.get_by_id', return_value=fake_qos)
    def test_get_volume_type(self, fake_get_by_id, fake_get_vol_types):
        qos_object = objects.QualityOfServiceSpecs.get_by_id(
            self.context, fake.OBJECT_ID)
        self.assertFalse(fake_get_vol_types.called)
        # Access lazy-loadable attribute
        qos_object.volume_types
        self.assertTrue(fake_get_vol_types.called)
