# Copyright (c) 2016 Chuck Fouts. All rights reserved.
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

import mock

from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test_volume

from cinder import context
from cinder import exception
from cinder import objects
from cinder.volume.flows.manager import manage_existing
from cinder.volume import manager
from cinder.volume import utils

FAKE_HOST_POOL = 'volPool'
FAKE_HOST = 'hostname@backend'


class ManageVolumeTestCase(test_volume.BaseVolumeTestCase):

    def setUp(self):
        super(ManageVolumeTestCase, self).setUp()
        self.context = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                              True)
        self.manager = manager.VolumeManager()
        self.manager.stats = {'allocated_capacity_gb': 0, 'pools': {}}

    @staticmethod
    def _stub_volume_object_get(cls, host=FAKE_HOST):
        volume = {
            'id': fake.VOLUME_ID,
            'size': 1,
            'name': fake.VOLUME_NAME,
            'host': host,
        }
        return fake_volume.fake_volume_obj(cls.context, **volume)

    def test_manage_existing(self):
        volume_object = self._stub_volume_object_get(self)
        mock_object_volume = self.mock_object(
            objects.Volume, 'get_by_id', mock.Mock(return_value=volume_object))
        mock_run_flow_engine = self.mock_object(
            self.manager, '_run_manage_existing_flow_engine',
            mock.Mock(return_value=volume_object))
        mock_update_volume_stats = self.mock_object(
            self.manager, '_update_stats_for_managed')

        result = self.manager.manage_existing(self.context, volume_object.id)

        self.assertEqual(fake.VOLUME_ID, result)
        mock_object_volume.assert_called_once_with(self.context,
                                                   volume_object.id)
        mock_run_flow_engine.assert_called_once_with(self.context,
                                                     volume_object,
                                                     None)
        mock_update_volume_stats.assert_called_once_with(volume_object)

    def test_manage_existing_with_volume_object(self):
        volume_object = self._stub_volume_object_get(self)
        mock_object_volume = self.mock_object(objects.Volume, 'get_by_id')
        mock_run_flow_engine = self.mock_object(
            self.manager, '_run_manage_existing_flow_engine',
            mock.Mock(return_value=volume_object))
        mock_update_volume_stats = self.mock_object(
            self.manager, '_update_stats_for_managed')

        result = self.manager.manage_existing(
            self.context, volume_object.id, volume=volume_object)

        self.assertEqual(fake.VOLUME_ID, result)
        mock_object_volume.assert_not_called()
        mock_run_flow_engine.assert_called_once_with(self.context,
                                                     volume_object,
                                                     None)
        mock_update_volume_stats.assert_called_once_with(volume_object)

    def test_run_manage_existing_flow_engine(self):
        mock_volume = mock.Mock()
        volume_object = self._stub_volume_object_get(self)

        mock_flow_engine = mock.Mock()
        mock_flow_engine_run = self.mock_object(mock_flow_engine, 'run')
        mock_flow_engine_fetch = self.mock_object(
            mock_flow_engine.storage, 'fetch',
            mock.Mock(return_value=volume_object))
        mock_get_flow = self.mock_object(
            manage_existing, 'get_flow',
            mock.Mock(return_value=mock_flow_engine))

        result = self.manager._run_manage_existing_flow_engine(self.context,
                                                               mock_volume,
                                                               None)

        self.assertEqual(volume_object, result)

        mock_get_flow.assert_called_once_with(self.context,
                                              self.manager.db,
                                              self.manager.driver,
                                              self.manager.host,
                                              mock_volume,
                                              None)
        mock_flow_engine_run.assert_called_once_with()
        mock_flow_engine_fetch.assert_called_once_with('volume')

    def test_run_manage_existing_flow_engine_exception(self):
        mock_get_flow = self.mock_object(
            manage_existing, 'get_flow',
            mock.Mock(side_effect=Exception))
        volume_object = self._stub_volume_object_get(self)
        self.assertRaises(exception.CinderException,
                          self.manager._run_manage_existing_flow_engine,
                          self.context,
                          volume_object,
                          None)

        mock_get_flow.assert_called_once_with(self.context,
                                              self.manager.db,
                                              self.manager.driver,
                                              self.manager.host,
                                              volume_object,
                                              None)

    def test_update_stats_for_managed(self):
        volume_object = self._stub_volume_object_get(self,
                                                     host=FAKE_HOST +
                                                     '#volPool')
        self.manager._update_stats_for_managed(volume_object)
        backend_stats = self.manager.stats['pools'][FAKE_HOST_POOL]
        self.assertEqual(
            1, backend_stats['allocated_capacity_gb'])

    def test_update_stats_for_managed_no_pool(self):
        safe_get_backend = 'safe_get_backend'
        volume_obj = self._stub_volume_object_get(self)
        mock_safe_get = self.mock_object(
            self.manager.driver.configuration, 'safe_get',
            mock.Mock(return_value=safe_get_backend))

        self.manager._update_stats_for_managed(volume_obj)

        mock_safe_get.assert_called_once_with('volume_backend_name')
        backend_stats = self.manager.stats['pools'][safe_get_backend]
        self.assertEqual(1, backend_stats['allocated_capacity_gb'])

    def test_update_stats_for_managed_default_backend(self):
        volume_obj = self._stub_volume_object_get(self)
        mock_safe_get = self.mock_object(
            self.manager.driver.configuration, 'safe_get',
            mock.Mock(return_value=None))

        self.manager._update_stats_for_managed(volume_obj)

        mock_safe_get.assert_called_once_with('volume_backend_name')
        backend_stats = self.manager.stats['pools'][utils.DEFAULT_POOL_NAME]
        self.assertEqual(1, backend_stats['allocated_capacity_gb'])

    def test_update_stats_key_error(self):
        self.manager.stats = {}

        self.assertRaises(
            KeyError, self.manager._update_stats_for_managed,
            self._stub_volume_object_get(self))
