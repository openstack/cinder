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

from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder import quota
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base
from cinder.volume.flows.manager import manage_existing
from cinder.volume import manager
from cinder.volume import utils

FAKE_HOST_POOL = 'volPool'
FAKE_HOST = 'hostname@backend'

QUOTAS = quota.QUOTAS


class ManageVolumeTestCase(base.BaseVolumeTestCase):

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
        mock_run_flow_engine = self.mock_object(
            self.manager, '_run_manage_existing_flow_engine',
            return_value=volume_object)
        mock_update_volume_stats = self.mock_object(
            self.manager, '_update_stats_for_managed')

        result = self.manager.manage_existing(self.context, volume_object)

        self.assertEqual(fake.VOLUME_ID, result)
        mock_run_flow_engine.assert_called_once_with(self.context,
                                                     volume_object,
                                                     None)
        mock_update_volume_stats.assert_called_once_with(volume_object)

    def test_manage_existing_with_volume_object(self):
        volume_object = self._stub_volume_object_get(self)
        mock_object_volume = self.mock_object(objects.Volume, 'get_by_id')
        mock_run_flow_engine = self.mock_object(
            self.manager, '_run_manage_existing_flow_engine',
            return_value=volume_object)
        mock_update_volume_stats = self.mock_object(
            self.manager, '_update_stats_for_managed')

        result = self.manager.manage_existing(
            self.context, volume_object)

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
            mock_flow_engine.storage, 'fetch', return_value=volume_object)
        mock_get_flow = self.mock_object(
            manage_existing, 'get_flow', return_value=mock_flow_engine)

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
            manage_existing, 'get_flow', side_effect=Exception)
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
            return_value=safe_get_backend)

        self.manager._update_stats_for_managed(volume_obj)

        mock_safe_get.assert_called_once_with('volume_backend_name')
        backend_stats = self.manager.stats['pools'][safe_get_backend]
        self.assertEqual(1, backend_stats['allocated_capacity_gb'])

    def test_update_stats_for_managed_default_backend(self):
        volume_obj = self._stub_volume_object_get(self)
        mock_safe_get = self.mock_object(
            self.manager.driver.configuration, 'safe_get', return_value=None)

        self.manager._update_stats_for_managed(volume_obj)

        mock_safe_get.assert_called_once_with('volume_backend_name')
        backend_stats = self.manager.stats['pools'][utils.DEFAULT_POOL_NAME]
        self.assertEqual(1, backend_stats['allocated_capacity_gb'])

    def test_update_stats_key_error(self):
        self.manager.stats = {}

        self.assertRaises(
            KeyError, self.manager._update_stats_for_managed,
            self._stub_volume_object_get(self))

    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'manage_existing')
    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'manage_existing_get_size')
    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_manage_volume_with_notify(self, mock_notify, mock_size,
                                       mock_manage):
        elevated = context.get_admin_context()
        vol_type = db.volume_type_create(
            elevated, {'name': 'type1', 'extra_specs': {}})
        # create source volume
        volume_params = {'volume_type_id': vol_type.id, 'status': 'managing'}
        test_vol = tests_utils.create_volume(self.context, **volume_params)
        mock_size.return_value = 1
        mock_manage.return_value = None

        self.volume.manage_existing(self.context, test_vol, 'volume_ref')
        mock_notify.assert_called_with(self.context, test_vol,
                                       'manage_existing.end',
                                       host=test_vol.host)

    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'manage_existing_get_size')
    @mock.patch('cinder.volume.flows.manager.manage_existing.'
                'ManageExistingTask.execute')
    def test_manage_volume_raise_driver_exception(self, mock_execute,
                                                  mock_driver_get_size):
        elevated = context.get_admin_context()
        project_id = self.context.project_id
        db.volume_type_create(elevated, {'name': 'type1', 'extra_specs': {}})
        vol_type = db.volume_type_get_by_name(elevated, 'type1')
        # create source volume
        self.volume_params['volume_type_id'] = vol_type['id']
        self.volume_params['status'] = 'managing'
        test_vol = tests_utils.create_volume(self.context,
                                             **self.volume_params)
        mock_execute.side_effect = exception.VolumeBackendAPIException(
            data="volume driver got exception")
        mock_driver_get_size.return_value = 1
        # Set quota usage
        reserve_opts = {'volumes': 1, 'gigabytes': 1}
        reservations = QUOTAS.reserve(self.context, project_id=project_id,
                                      **reserve_opts)
        QUOTAS.commit(self.context, reservations)
        usage = db.quota_usage_get(self.context, project_id, 'volumes')
        volumes_in_use = usage.in_use
        usage = db.quota_usage_get(self.context, project_id, 'gigabytes')
        gigabytes_in_use = usage.in_use

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.manage_existing,
                          self.context, test_vol,
                          'volume_ref')
        # check volume status
        volume = objects.Volume.get_by_id(context.get_admin_context(),
                                          test_vol.id)
        self.assertEqual('error_managing', volume.status)
        # Delete this volume with 'error_managing_deleting' status in c-vol.
        test_vol.status = 'error_managing_deleting'
        test_vol.save()
        self.volume.delete_volume(self.context, test_vol)
        ctxt = context.get_admin_context(read_deleted='yes')
        volume = objects.Volume.get_by_id(ctxt, test_vol.id)
        self.assertEqual('deleted', volume.status)
        # Get in_use number after deleting error_managing volume
        usage = db.quota_usage_get(self.context, project_id, 'volumes')
        volumes_in_use_new = usage.in_use
        self.assertEqual(volumes_in_use, volumes_in_use_new)
        usage = db.quota_usage_get(self.context, project_id, 'gigabytes')
        gigabytes_in_use_new = usage.in_use
        self.assertEqual(gigabytes_in_use, gigabytes_in_use_new)

    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'manage_existing_get_size')
    def test_manage_volume_raise_driver_size_exception(self,
                                                       mock_driver_get_size):
        elevated = context.get_admin_context()
        project_id = self.context.project_id
        db.volume_type_create(elevated, {'name': 'type1', 'extra_specs': {}})
        # create source volume
        test_vol = tests_utils.create_volume(self.context,
                                             **self.volume_params)
        mock_driver_get_size.side_effect = exception.VolumeBackendAPIException(
            data="volume driver got exception")

        # Set quota usage
        reserve_opts = {'volumes': 1, 'gigabytes': 1}
        reservations = QUOTAS.reserve(self.context, project_id=project_id,
                                      **reserve_opts)
        QUOTAS.commit(self.context, reservations)
        usage = db.quota_usage_get(self.context, project_id, 'volumes')
        volumes_in_use = usage.in_use
        usage = db.quota_usage_get(self.context, project_id, 'gigabytes')
        gigabytes_in_use = usage.in_use

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.manage_existing,
                          self.context, test_vol,
                          'volume_ref')
        # check volume status
        volume = objects.Volume.get_by_id(context.get_admin_context(),
                                          test_vol.id)
        self.assertEqual('error_managing', volume.status)
        # Delete this volume with 'error_managing_deleting' status in c-vol.
        test_vol.status = 'error_managing_deleting'
        test_vol.save()
        self.volume.delete_volume(self.context, test_vol)
        ctxt = context.get_admin_context(read_deleted='yes')
        volume = objects.Volume.get_by_id(ctxt, test_vol.id)
        self.assertEqual('deleted', volume.status)
        # Get in_use number after raising exception
        usage = db.quota_usage_get(self.context, project_id, 'volumes')
        volumes_in_use_new = usage.in_use
        self.assertEqual(volumes_in_use, volumes_in_use_new)
        usage = db.quota_usage_get(self.context, project_id, 'gigabytes')
        gigabytes_in_use_new = usage.in_use
        self.assertEqual(gigabytes_in_use, gigabytes_in_use_new)
