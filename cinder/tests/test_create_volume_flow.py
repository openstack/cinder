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

import time

import mock

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests import fake_snapshot
from cinder.tests import fake_volume
from cinder.volume.flows.api import create_volume
from cinder.volume.flows.manager import create_volume as create_volume_manager


class fake_scheduler_rpc_api(object):
    def __init__(self, expected_spec, test_inst):
        self.expected_spec = expected_spec
        self.test_inst = test_inst

    def create_volume(self, ctxt, topic, volume_id, snapshot_id=None,
                      image_id=None, request_spec=None,
                      filter_properties=None):

        self.test_inst.assertEqual(self.expected_spec, request_spec)


class fake_volume_api(object):
    def __init__(self, expected_spec, test_inst):
        self.expected_spec = expected_spec
        self.test_inst = test_inst

    def create_volume(self, ctxt, volume, host,
                      request_spec, filter_properties,
                      allow_reschedule=True,
                      snapshot_id=None, image_id=None,
                      source_volid=None,
                      source_replicaid=None):

        self.test_inst.assertEqual(self.expected_spec, request_spec)
        self.test_inst.assertEqual(request_spec['source_volid'], source_volid)
        self.test_inst.assertEqual(request_spec['snapshot_id'], snapshot_id)
        self.test_inst.assertEqual(request_spec['image_id'], image_id)
        self.test_inst.assertEqual(request_spec['source_replicaid'],
                                   source_replicaid)


class fake_db(object):

    def volume_get(self, *args, **kwargs):
        return {'host': 'barf'}

    def volume_update(self, *args, **kwargs):
        return {'host': 'farb'}

    def snapshot_get(self, *args, **kwargs):
        return {'volume_id': 1}

    def consistencygroup_get(self, *args, **kwargs):
        return {'consistencygroup_id': 1}


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
        self.stubs.Set(time, 'time', self.time_inc)

    def test_cast_create_volume(self):

        props = {}
        spec = {'volume_id': None,
                'source_volid': None,
                'snapshot_id': None,
                'image_id': None,
                'source_replicaid': None,
                'consistencygroup_id': None,
                'cgsnapshot_id': None}

        task = create_volume.VolumeCastTask(
            fake_scheduler_rpc_api(spec, self),
            fake_volume_api(spec, self),
            fake_db())

        task._cast_create_volume(self.ctxt, spec, props)

        spec = {'volume_id': 1,
                'source_volid': 2,
                'snapshot_id': 3,
                'image_id': 4,
                'source_replicaid': 5,
                'consistencygroup_id': 5,
                'cgsnapshot_id': None}

        task = create_volume.VolumeCastTask(
            fake_scheduler_rpc_api(spec, self),
            fake_volume_api(spec, self),
            fake_db())

        task._cast_create_volume(self.ctxt, spec, props)


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
