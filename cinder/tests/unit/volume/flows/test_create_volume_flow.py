# Copyright 2013 Canonical Ltd.
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
""" Tests for create_volume TaskFlow """

import mock

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_consistencygroup
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit.keymgr import mock_key_mgr
from cinder.tests.unit.volume.flows import fake_volume_api
from cinder.volume.flows.api import create_volume
from cinder.volume.flows.manager import create_volume as create_volume_manager


class CreateVolumeFlowTestCase(test.TestCase):

    def time_inc(self):
        self.counter += 1
        return self.counter

    def setUp(self):
        super(CreateVolumeFlowTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.counter = float(0)

        # Ensure that time.time() always returns more than the last time it was
        # called to avoid div by zero errors.
        self.counter = float(0)

    @mock.patch('time.time', side_effect=time_inc)
    @mock.patch('cinder.objects.ConsistencyGroup.get_by_id')
    def test_cast_create_volume(self, consistencygroup_get_by_id, mock_time):
        props = {}
        consistencygroup_obj = \
            fake_consistencygroup.fake_consistencyobject_obj(
                self.ctxt, consistencygroup_id=1, host=None)
        consistencygroup_get_by_id.return_value = consistencygroup_obj
        spec = {'volume_id': None,
                'source_volid': None,
                'snapshot_id': None,
                'image_id': None,
                'source_replicaid': None,
                'consistencygroup_id': None,
                'cgsnapshot_id': None}

        # Fake objects assert specs
        task = create_volume.VolumeCastTask(
            fake_volume_api.FakeSchedulerRpcAPI(spec, self),
            fake_volume_api.FakeVolumeAPI(spec, self),
            fake_volume_api.FakeDb())

        task._cast_create_volume(self.ctxt, spec, props)

        spec = {'volume_id': 1,
                'source_volid': 2,
                'snapshot_id': 3,
                'image_id': 4,
                'source_replicaid': 5,
                'consistencygroup_id': 5,
                'cgsnapshot_id': None}

        # Fake objects assert specs
        task = create_volume.VolumeCastTask(
            fake_volume_api.FakeSchedulerRpcAPI(spec, self),
            fake_volume_api.FakeVolumeAPI(spec, self),
            fake_volume_api.FakeDb())

        task._cast_create_volume(self.ctxt, spec, props)
        consistencygroup_get_by_id.assert_called_once_with(self.ctxt, 5)

    @mock.patch('cinder.volume.volume_types.is_encrypted')
    @mock.patch('cinder.volume.flows.api.create_volume.'
                'ExtractVolumeRequestTask.'
                '_get_volume_type_id')
    def test_extract_volume_request_from_image_encrypted(
            self,
            fake_get_volume_type_id,
            fake_is_encrypted):

        fake_image_service = fake_image.FakeImageService()
        image_id = 1
        image_meta = {}
        image_meta['id'] = image_id
        image_meta['status'] = 'active'
        image_meta['size'] = 1
        fake_image_service.create(self.ctxt, image_meta)
        fake_key_manager = mock_key_mgr.MockKeyManager()

        task = create_volume.ExtractVolumeRequestTask(
            fake_image_service,
            {'nova'})

        fake_is_encrypted.return_value = True
        self.assertRaises(exception.InvalidInput,
                          task.execute,
                          self.ctxt,
                          size=1,
                          snapshot=None,
                          image_id=image_id,
                          source_volume=None,
                          availability_zone='nova',
                          volume_type=None,
                          metadata=None,
                          key_manager=fake_key_manager,
                          source_replica=None,
                          consistencygroup=None,
                          cgsnapshot=None)

    @mock.patch('cinder.volume.volume_types.is_encrypted')
    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    @mock.patch('cinder.volume.flows.api.create_volume.'
                'ExtractVolumeRequestTask.'
                '_get_volume_type_id')
    def test_extract_volume_request_from_image(
            self,
            fake_get_type_id,
            fake_get_qos,
            fake_is_encrypted):

        fake_image_service = fake_image.FakeImageService()
        image_id = 2
        image_meta = {}
        image_meta['id'] = image_id
        image_meta['status'] = 'active'
        image_meta['size'] = 1
        fake_image_service.create(self.ctxt, image_meta)
        fake_key_manager = mock_key_mgr.MockKeyManager()
        volume_type = 'type1'

        task = create_volume.ExtractVolumeRequestTask(
            fake_image_service,
            {'nova'})

        fake_is_encrypted.return_value = False
        fake_get_type_id.return_value = 1
        fake_get_qos.return_value = {'qos_specs': None}
        result = task.execute(self.ctxt,
                              size=1,
                              snapshot=None,
                              image_id=image_id,
                              source_volume=None,
                              availability_zone='nova',
                              volume_type=volume_type,
                              metadata=None,
                              key_manager=fake_key_manager,
                              source_replica=None,
                              consistencygroup=None,
                              cgsnapshot=None)
        expected_result = {'size': 1,
                           'snapshot_id': None,
                           'source_volid': None,
                           'availability_zone': 'nova',
                           'volume_type': volume_type,
                           'volume_type_id': 1,
                           'encryption_key_id': None,
                           'qos_specs': None,
                           'source_replicaid': None,
                           'consistencygroup_id': None,
                           'cgsnapshot_id': None, }
        self.assertEqual(expected_result, result)


class CreateVolumeFlowManagerTestCase(test.TestCase):

    def setUp(self):
        super(CreateVolumeFlowManagerTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    @mock.patch('cinder.volume.flows.manager.create_volume.'
                'CreateVolumeFromSpecTask.'
                '_handle_bootable_volume_glance_meta')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_create_from_snapshot(self, snapshot_get_by_id, handle_bootable):
        fake_db = mock.MagicMock()
        fake_driver = mock.MagicMock()
        fake_manager = create_volume_manager.CreateVolumeFromSpecTask(
            fake_db, fake_driver)
        volume = fake_volume.fake_db_volume()
        orig_volume_db = mock.MagicMock(id=10, bootable=True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctxt)
        snapshot_get_by_id.return_value = snapshot_obj
        fake_db.volume_get.return_value = orig_volume_db

        fake_manager._create_from_snapshot(self.ctxt, volume,
                                           snapshot_obj.id)
        fake_driver.create_volume_from_snapshot.assert_called_once_with(
            volume, snapshot_obj)
        fake_db.volume_get.assert_called_once_with(self.ctxt,
                                                   snapshot_obj.volume_id)
        handle_bootable.assert_called_once_with(self.ctxt, volume['id'],
                                                snapshot_id=snapshot_obj.id)

    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_create_from_snapshot_update_failure(self, snapshot_get_by_id):
        fake_db = mock.MagicMock()
        fake_driver = mock.MagicMock()
        fake_manager = create_volume_manager.CreateVolumeFromSpecTask(
            fake_db, fake_driver)
        volume = fake_volume.fake_db_volume()
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctxt)
        snapshot_get_by_id.return_value = snapshot_obj
        fake_db.volume_get.side_effect = exception.CinderException

        self.assertRaises(exception.MetadataUpdateFailure,
                          fake_manager._create_from_snapshot, self.ctxt,
                          volume, snapshot_obj.id)
        fake_driver.create_volume_from_snapshot.assert_called_once_with(
            volume, snapshot_obj)
