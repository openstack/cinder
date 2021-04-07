# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""Tests for Volume Code."""

import datetime
import enum
import io
import time
from unittest import mock

import castellan
from castellan.common import exception as castellan_exception
from castellan import key_manager
import ddt
import eventlet
import os_brick.initiator.connectors.iscsi
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import imageutils
from taskflow.engines.action_engine import engine

from cinder.api import common
from cinder import context
from cinder import coordination
from cinder import db
from cinder import exception
from cinder.message import message_field
from cinder import objects
from cinder.objects import fields
from cinder.policies import volumes as vol_policy
from cinder import quota
from cinder.tests import fake_driver
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import conf_fixture
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.keymgr import fake as fake_keymgr
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base
from cinder import utils
import cinder.volume
from cinder.volume import driver
from cinder.volume import manager as vol_manager
from cinder.volume import rpcapi as volume_rpcapi
import cinder.volume.targets.tgt
from cinder.volume import volume_types


QUOTAS = quota.QUOTAS

CONF = cfg.CONF

ENCRYPTION_PROVIDER = 'nova.volume.encryptors.cryptsetup.CryptsetupEncryptor'

fake_opt = [
    cfg.StrOpt('fake_opt1', default='fake', help='fake opts')
]


def create_snapshot(volume_id, size=1, metadata=None, ctxt=None,
                    **kwargs):
    """Create a snapshot object."""
    metadata = metadata or {}
    snap = objects.Snapshot(ctxt or context.get_admin_context())
    snap.volume_size = size
    snap.user_id = fake.USER_ID
    snap.project_id = fake.PROJECT_ID
    snap.volume_id = volume_id
    snap.status = fields.SnapshotStatus.CREATING
    if metadata is not None:
        snap.metadata = metadata
    snap.update(kwargs)

    snap.create()
    return snap


class KeyObject(object):
    def get_encoded(self):
        return "asdf".encode('utf-8')


class KeyObject2(object):
    def get_encoded(self):
        return "qwert".encode('utf-8')


@ddt.ddt
class VolumeTestCase(base.BaseVolumeTestCase):

    def setUp(self):
        super(VolumeTestCase, self).setUp()
        self.patch('cinder.volume.volume_utils.clear_volume', autospec=True)
        self.expected_status = 'available'
        self.service_id = 1
        self.user_context = context.RequestContext(user_id=fake.USER_ID,
                                                   project_id=fake.PROJECT_ID)
        elevated = context.get_admin_context()
        db.volume_type_create(elevated,
                              v2_fakes.fake_default_type_get(
                                  id=fake.VOLUME_TYPE2_ID))
        self.vol_type = db.volume_type_get_by_name(elevated, '__DEFAULT__')
        self._setup_volume_types()

    def _create_volume(self, context, **kwargs):
        return tests_utils.create_volume(
            context,
            volume_type_id=volume_types.get_default_volume_type()['id'],
            **kwargs)

    @mock.patch('cinder.objects.service.Service.get_minimum_rpc_version')
    @mock.patch('cinder.objects.service.Service.get_minimum_obj_version')
    @mock.patch('cinder.rpc.LAST_RPC_VERSIONS', {'cinder-scheduler': '1.3'})
    def test_reset(self, get_min_obj, get_min_rpc):
        old_version = objects.base.OBJ_VERSIONS.versions[-2]

        with mock.patch('cinder.rpc.LAST_OBJ_VERSIONS',
                        {'cinder-scheduler': old_version}):
            vol_mgr = vol_manager.VolumeManager()

        scheduler_rpcapi = vol_mgr.scheduler_rpcapi
        self.assertEqual('1.3', scheduler_rpcapi.client.version_cap)
        self.assertEqual(old_version,
                         scheduler_rpcapi.client.serializer._base.version_cap)
        get_min_obj.return_value = self.latest_ovo_version
        vol_mgr.reset()

        scheduler_rpcapi = vol_mgr.scheduler_rpcapi
        self.assertEqual(get_min_rpc.return_value,
                         scheduler_rpcapi.client.version_cap)
        self.assertEqual(get_min_obj.return_value,
                         scheduler_rpcapi.client.serializer._base.version_cap)
        self.assertIsNone(scheduler_rpcapi.client.serializer._base.manifest)

    @mock.patch('oslo_utils.importutils.import_object')
    def test_backend_availability_zone(self, mock_import_object):
        # NOTE(smcginnis): This isn't really the best place for this test,
        # but we don't currently have a pure VolumeManager test class. So
        # until we create a good suite for that class, putting here with
        # other tests that use VolumeManager.

        opts = {
            'backend_availability_zone': 'caerbannog'
        }

        def conf_get(option):
            if option in opts:
                return opts[option]
            return None

        mock_driver = mock.Mock()
        mock_driver.configuration.safe_get.side_effect = conf_get
        mock_driver.configuration.extra_capabilities = 'null'

        def import_obj(*args, **kwargs):
            return mock_driver

        mock_import_object.side_effect = import_obj

        manager = vol_manager.VolumeManager(volume_driver=mock_driver)
        self.assertIsNotNone(manager)
        self.assertEqual(opts['backend_availability_zone'],
                         manager.availability_zone)

    @mock.patch('cinder.volume.manager.VolumeManager._append_volume_stats',
                mock.Mock())
    @mock.patch.object(vol_manager.VolumeManager,
                       'update_service_capabilities')
    def test_report_filter_goodness_function(self, mock_update):
        manager = vol_manager.VolumeManager()
        manager.driver.set_initialized()
        myfilterfunction = "myFilterFunction"
        mygoodnessfunction = "myGoodnessFunction"
        expected = {'name': 'cinder-volumes',
                    'storage_protocol': 'iSCSI',
                    'cacheable': True,
                    'filter_function': myfilterfunction,
                    'goodness_function': mygoodnessfunction,
                    }
        with mock.patch.object(manager.driver,
                               'get_volume_stats') as m_get_stats:
            with mock.patch.object(manager.driver,
                                   'get_goodness_function') as m_get_goodness:
                with mock.patch.object(manager.driver,
                                       'get_filter_function') as m_get_filter:
                    m_get_stats.return_value = {'name': 'cinder-volumes',
                                                'storage_protocol': 'iSCSI',
                                                }
                    m_get_filter.return_value = myfilterfunction
                    m_get_goodness.return_value = mygoodnessfunction
                    manager._report_driver_status(context.get_admin_context())
                    self.assertTrue(m_get_stats.called)
                    mock_update.assert_called_once_with(expected)

    def test_is_working(self):
        # By default we have driver mocked to be initialized...
        self.assertTrue(self.volume.is_working())

        # ...lets switch it and check again!
        self.volume.driver._initialized = False
        self.assertFalse(self.volume.is_working())

    def _create_min_max_size_dict(self, min_size, max_size):
        return {volume_types.MIN_SIZE_KEY: min_size,
                volume_types.MAX_SIZE_KEY: max_size}

    def _setup_volume_types(self):
        """Creates 2 types, one with size limits, one without."""

        spec_dict = self._create_min_max_size_dict(2, 4)
        sized_vol_type_dict = {'name': 'limit',
                               'extra_specs': spec_dict}
        db.volume_type_create(self.context, sized_vol_type_dict)
        self.sized_vol_type = db.volume_type_get_by_name(
            self.context, sized_vol_type_dict['name'])

        unsized_vol_type_dict = {'name': 'unsized', 'extra_specs': {}}
        db.volume_type_create(context.get_admin_context(),
                              unsized_vol_type_dict)
        self.unsized_vol_type = db.volume_type_get_by_name(
            self.context, unsized_vol_type_dict['name'])

    @mock.patch('cinder.tests.unit.fake_notifier.FakeNotifier._notify')
    @mock.patch.object(QUOTAS, 'reserve')
    @mock.patch.object(QUOTAS, 'commit')
    @mock.patch.object(QUOTAS, 'rollback')
    def test_create_driver_not_initialized(self, reserve, commit, rollback,
                                           mock_notify):
        self.volume.driver._initialized = False

        def fake_reserve(context, expire=None, project_id=None, **deltas):
            return ["RESERVATION"]

        def fake_commit_and_rollback(context, reservations, project_id=None):
            pass

        reserve.return_value = fake_reserve
        commit.return_value = fake_commit_and_rollback
        rollback.return_value = fake_commit_and_rollback

        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **self.volume_params)

        volume_id = volume['id']
        self.assertIsNone(volume['encryption_key_id'])

        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.create_volume, self.context, volume)

        volume = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual("error", volume.status)
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_create_driver_not_initialized_rescheduling(self):
        self.volume.driver._initialized = False
        mock_delete = self.mock_object(self.volume.driver, 'delete_volume')

        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **self.volume_params)

        volume_id = volume['id']
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.create_volume,
                          self.context, volume,
                          {'volume_properties': self.volume_params},
                          {'retry': {'num_attempts': 1, 'host': []}})
        # NOTE(dulek): Volume should be rescheduled as we passed request_spec
        # and filter_properties, assert that it wasn't counted in
        # allocated_capacity tracking.
        self.assertEqual({'_pool0': {'allocated_capacity_gb': 0}},
                         self.volume.stats['pools'])

        # NOTE(dulek): As we've rescheduled, make sure delete_volume was
        # called.
        self.assertTrue(mock_delete.called)

        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_create_non_cinder_exception_rescheduling(self):
        params = self.volume_params
        del params['host']
        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **params)

        volume_id = volume['id']
        with mock.patch.object(self.volume.driver, 'create_volume',
                               side_effect=processutils.ProcessExecutionError):
            self.assertRaises(processutils.ProcessExecutionError,
                              self.volume.create_volume,
                              self.context, volume,
                              {'volume_properties': params},
                              {'retry': {'num_attempts': 1, 'host': []}})
        # NOTE(dulek): Volume should be rescheduled as we passed request_spec
        # and filter_properties, assert that it wasn't counted in
        # allocated_capacity tracking.
        self.assertEqual({'_pool0': {'allocated_capacity_gb': 0}},
                         self.volume.stats['pools'])

        db.volume_destroy(context.get_admin_context(), volume_id)

    @mock.patch('cinder.tests.unit.fake_notifier.FakeNotifier._notify')
    @mock.patch.object(QUOTAS, 'rollback')
    @mock.patch.object(QUOTAS, 'commit')
    @mock.patch.object(QUOTAS, 'reserve')
    def test_delete_driver_not_initialized(self, reserve, commit, rollback,
                                           mock_notify):
        self.volume.driver._initialized = False

        def fake_reserve(context, expire=None, project_id=None, **deltas):
            return ["RESERVATION"]

        def fake_commit_and_rollback(context, reservations, project_id=None):
            pass

        reserve.return_value = fake_reserve
        commit.return_value = fake_commit_and_rollback
        rollback.return_value = fake_commit_and_rollback

        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **self.volume_params)

        self.assertIsNone(volume['encryption_key_id'])
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.delete_volume, self.context, volume)

        volume = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual("error_deleting", volume.status)
        volume.destroy()

    @ddt.data(True, False)
    @mock.patch('cinder.utils.clean_volume_file_locks')
    @mock.patch('cinder.tests.unit.fake_notifier.FakeNotifier._notify')
    @mock.patch('cinder.quota.QUOTAS.rollback', new=mock.Mock())
    @mock.patch('cinder.quota.QUOTAS.commit')
    @mock.patch('cinder.quota.QUOTAS.reserve', return_value=['RESERVATION'])
    def test_create_delete_volume(self, use_quota, _mock_reserve, commit_mock,
                                  mock_notify, mock_clean):
        """Test volume can be created and deleted."""
        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **self.volume_params)
        volume_id = volume['id']

        self.assertIsNone(volume['encryption_key_id'])

        self.volume.create_volume(self.context, volume)

        self.assert_notify_called(mock_notify,
                                  (['INFO', 'volume.create.start'],
                                   ['INFO', 'volume.create.end']),
                                  any_order=True)
        self.assertEqual({'_pool0': {'allocated_capacity_gb': 1}},
                         self.volume.stats['pools'])

        # Confirm delete_volume handles use_quota field
        volume.use_quota = use_quota
        volume.save()  # Need to save to DB because of the refresh call
        commit_mock.reset_mock()
        _mock_reserve.reset_mock()
        mock_notify.reset_mock()
        self.volume.delete_volume(self.context, volume)
        vol = db.volume_get(context.get_admin_context(read_deleted='yes'),
                            volume_id)
        self.assertEqual(vol['status'], 'deleted')

        if use_quota:
            expected_capacity = 0
            self.assert_notify_called(mock_notify,
                                      (['INFO', 'volume.delete.start'],
                                       ['INFO', 'volume.delete.end']),
                                      any_order=True)
            self.assertEqual(1, _mock_reserve.call_count)
            self.assertEqual(1, commit_mock.call_count)
        else:
            expected_capacity = 1
            mock_notify.assert_not_called()
            _mock_reserve.assert_not_called()
            commit_mock.assert_not_called()
        self.assertEqual(
            {'_pool0': {'allocated_capacity_gb': expected_capacity}},
            self.volume.stats['pools'])

        self.assertRaises(exception.NotFound,
                          db.volume_get,
                          self.context,
                          volume_id)
        mock_clean.assert_called_once_with(volume_id, self.volume.driver)

    @mock.patch('cinder.tests.unit.fake_notifier.FakeNotifier._notify')
    @mock.patch('cinder.quota.QUOTAS.rollback')
    @mock.patch('cinder.quota.QUOTAS.commit')
    @mock.patch('cinder.quota.QUOTAS.reserve', return_value=['RESERVATION'])
    def test_delete_migrating_volume(self, reserve_mock, commit_mock,
                                     rollback_mock, notify_mock):
        """Test volume can be created and deleted."""
        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            migration_status='target:123',
            **self.volume_params)
        volume_id = volume['id']

        self.volume.delete_volume(self.context, volume)

        vol = db.volume_get(context.get_admin_context(read_deleted='yes'),
                            volume_id)
        self.assertEqual(vol['status'], 'deleted')

        # For migration's temp volume we don't notify or do any quota
        notify_mock.assert_not_called()
        rollback_mock.assert_not_called()
        commit_mock.assert_not_called()
        reserve_mock.assert_not_called()

    def test_create_delete_volume_with_metadata(self):
        """Test volume can be created with metadata and deleted."""
        test_meta = {'fake_key': 'fake_value'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        self.assertEqual(test_meta, volume.metadata)

        self.volume.delete_volume(self.context, volume)
        self.assertRaises(exception.NotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    @mock.patch('cinder.utils.clean_volume_file_locks')
    def test_delete_volume_frozen(self, mock_clean):
        service = tests_utils.create_service(self.context, {'frozen': True})
        volume = tests_utils.create_volume(self.context, host=service.host)
        self.assertRaises(exception.InvalidInput,
                          self.volume_api.delete, self.context, volume)
        mock_clean.assert_not_called()

    def test_delete_volume_another_cluster_fails(self):
        """Test delete of volume from another cluster fails."""
        self.volume.cluster = 'mycluster'
        volume = tests_utils.create_volume(self.context, status='available',
                                           size=1, host=CONF.host + 'fake',
                                           cluster_name=self.volume.cluster)
        self.volume.delete_volume(self.context, volume)
        self.assertRaises(exception.NotFound,
                          db.volume_get,
                          self.context,
                          volume.id)

    @mock.patch('cinder.db.volume_metadata_update')
    def test_create_volume_metadata(self, metadata_update):
        metadata = {'fake_key': 'fake_value'}
        metadata_update.return_value = metadata
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        res = self.volume_api.create_volume_metadata(self.context,
                                                     volume, metadata)
        metadata_update.assert_called_once_with(self.context, volume.id,
                                                metadata, False,
                                                common.METADATA_TYPES.user)
        self.assertEqual(metadata, res)

    @ddt.data('maintenance', 'uploading')
    def test_create_volume_metadata_maintenance(self, status):
        metadata = {'fake_key': 'fake_value'}
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume['status'] = status
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.create_volume_metadata,
                          self.context,
                          volume,
                          metadata)

    def test_update_volume_metadata_with_metatype(self):
        """Test update volume metadata with different metadata type."""
        test_meta1 = {'fake_key1': 'fake_value1'}
        test_meta2 = {'fake_key1': 'fake_value2'}
        FAKE_METADATA_TYPE = enum.Enum('METADATA_TYPES', 'fake_type')
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        self.volume.create_volume(self.context, volume)
        # update user metadata associated with the volume.
        result_meta = self.volume_api.update_volume_metadata(
            self.context,
            volume,
            test_meta2,
            False,
            common.METADATA_TYPES.user)
        self.assertEqual(test_meta2, result_meta)

        # create image metadata associated with the volume.
        result_meta = self.volume_api.update_volume_metadata(
            self.context,
            volume,
            test_meta1,
            False,
            common.METADATA_TYPES.image)
        self.assertEqual(test_meta1, result_meta)

        # update image metadata associated with the volume.
        result_meta = self.volume_api.update_volume_metadata(
            self.context,
            volume,
            test_meta2,
            False,
            common.METADATA_TYPES.image)
        self.assertEqual(test_meta2, result_meta)

        # update volume metadata with invalid metadta type.
        self.assertRaises(exception.InvalidMetadataType,
                          self.volume_api.update_volume_metadata,
                          self.context,
                          volume,
                          test_meta1,
                          False,
                          FAKE_METADATA_TYPE.fake_type)

    def test_update_volume_metadata_maintenance(self):
        """Test update volume metadata with different metadata type."""
        test_meta1 = {'fake_key1': 'fake_value1'}
        FAKE_METADATA_TYPE = enum.Enum('METADATA_TYPES', 'fake_type')
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.update_volume_metadata,
                          self.context,
                          volume,
                          test_meta1,
                          False,
                          FAKE_METADATA_TYPE.fake_type)

    @mock.patch('cinder.db.volume_update')
    def test_update_with_ovo(self, volume_update):
        """Test update volume using oslo_versionedobject."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        updates = {'display_name': 'foobbar'}
        self.volume_api.update(self.context, volume, updates)
        volume_update.assert_called_once_with(self.context, volume.id,
                                              updates)
        self.assertEqual('foobbar', volume.display_name)

    def test_delete_volume_metadata_with_metatype(self):
        """Test delete volume metadata with different metadata type."""
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        test_meta2 = {'fake_key1': 'fake_value1'}
        FAKE_METADATA_TYPE = enum.Enum('METADATA_TYPES', 'fake_type')
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        # delete user metadata associated with the volume.
        self.volume_api.delete_volume_metadata(
            self.context,
            volume,
            'fake_key2',
            common.METADATA_TYPES.user)

        self.assertEqual(test_meta2,
                         db.volume_metadata_get(self.context, volume_id))

        # create image metadata associated with the volume.
        result_meta = self.volume_api.update_volume_metadata(
            self.context,
            volume,
            test_meta1,
            False,
            common.METADATA_TYPES.image)

        self.assertEqual(test_meta1, result_meta)

        # delete image metadata associated with the volume.
        self.volume_api.delete_volume_metadata(
            self.context,
            volume,
            'fake_key2',
            common.METADATA_TYPES.image)

        # parse the result to build the dict.
        rows = db.volume_glance_metadata_get(self.context, volume_id)
        result = {}
        for row in rows:
            result[row['key']] = row['value']
        self.assertEqual(test_meta2, result)

        # delete volume metadata with invalid metadta type.
        self.assertRaises(exception.InvalidMetadataType,
                          self.volume_api.delete_volume_metadata,
                          self.context,
                          volume,
                          'fake_key1',
                          FAKE_METADATA_TYPE.fake_type)

    @mock.patch('cinder.utils.clean_volume_file_locks')
    def test_delete_volume_metadata_maintenance(self, mock_clean):
        """Test delete volume metadata in maintenance."""
        FAKE_METADATA_TYPE = enum.Enum('METADATA_TYPES', 'fake_type')
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.delete_volume_metadata,
                          self.context,
                          volume,
                          'fake_key1',
                          FAKE_METADATA_TYPE.fake_type)
        mock_clean.assert_not_called()

    def test_accept_transfer_maintenance(self):
        """Test accept transfer in maintenance."""
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.accept_transfer,
                          self.context,
                          volume,
                          None, None)

    @mock.patch.object(cinder.volume.api.API, 'list_availability_zones')
    def test_create_volume_uses_default_availability_zone(self, mock_list_az):
        """Test setting availability_zone correctly during volume create."""
        mock_list_az.return_value = ({'name': 'az1', 'available': True},
                                     {'name': 'az2', 'available': True},
                                     {'name': 'default-az', 'available': True})

        volume_api = cinder.volume.api.API()

        # Test backwards compatibility, default_availability_zone not set
        self.override_config('storage_availability_zone', 'az2')
        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description',
                                   volume_type=self.vol_type)
        self.assertEqual('az2', volume['availability_zone'])

        self.override_config('default_availability_zone', 'default-az')
        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description',
                                   volume_type=self.vol_type)
        self.assertEqual('default-az', volume['availability_zone'])

    def test_create_volume_with_default_type_misconfigured(self):
        """Test volume creation with non-existent default volume type."""
        volume_api = cinder.volume.api.API()

        self.flags(default_volume_type='fake_type')
        # Create volume with default volume type while default
        # volume type doesn't exist
        self.assertRaises(exception.VolumeTypeDefaultMisconfiguredError,
                          volume_api.create, self.context, 1,
                          'name', 'description')

    @mock.patch('cinder.quota.QUOTAS.rollback', new=mock.MagicMock())
    @mock.patch('cinder.quota.QUOTAS.commit', new=mock.MagicMock())
    @mock.patch('cinder.quota.QUOTAS.reserve', return_value=["RESERVATION"])
    def test_create_volume_with_volume_type(self, _mock_reserve):
        """Test volume creation with default volume type."""
        volume_api = cinder.volume.api.API()

        # Create volume with default volume type while default
        # volume type doesn't exist, volume_type_id should be NULL
        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description',
                                   volume_type=self.vol_type)
        self.assertIsNone(volume['encryption_key_id'])

        # Create default volume type
        vol_type = conf_fixture.def_vol_type
        db_vol_type = db.volume_type_get_by_name(context.get_admin_context(),
                                                 vol_type)

        # Create volume with default volume type
        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description')
        self.assertEqual(db_vol_type.get('id'), volume['volume_type_id'])
        self.assertIsNone(volume['encryption_key_id'])

        # Create volume with specific volume type
        vol_type = 'test'
        db.volume_type_create(context.get_admin_context(),
                              {'name': vol_type, 'extra_specs': {}})
        db_vol_type = db.volume_type_get_by_name(context.get_admin_context(),
                                                 vol_type)

        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description',
                                   volume_type=db_vol_type)
        self.assertEqual(db_vol_type.get('id'), volume['volume_type_id'])

    @mock.patch('cinder.quota.QUOTAS.rollback', new=mock.MagicMock())
    @mock.patch('cinder.quota.QUOTAS.commit', new=mock.MagicMock())
    @mock.patch('cinder.quota.QUOTAS.reserve', return_value=["RESERVATION"])
    def test_create_volume_with_volume_type_size_limits(self, _mock_reserve):
        """Test that volume type size limits are enforced."""
        volume_api = cinder.volume.api.API()

        volume = volume_api.create(self.context,
                                   2,
                                   'name',
                                   'description',
                                   volume_type=self.sized_vol_type)
        self.assertEqual(self.sized_vol_type['id'], volume['volume_type_id'])

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          1,
                          'name',
                          'description',
                          volume_type=self.sized_vol_type)
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          5,
                          'name',
                          'description',
                          volume_type=self.sized_vol_type)

    def test_create_volume_with_multiattach_volume_type(self):
        """Test volume creation with multiattach volume type."""
        elevated = context.get_admin_context()
        volume_api = cinder.volume.api.API()

        especs = dict(multiattach="<is> True")
        volume_types.create(elevated,
                            "multiattach-type",
                            especs,
                            description="test-multiattach")
        foo = objects.VolumeType.get_by_name_or_id(elevated,
                                                   "multiattach-type")

        vol = volume_api.create(self.context,
                                1,
                                'admin-vol',
                                'description',
                                volume_type=foo)
        self.assertEqual(foo['id'], vol['volume_type_id'])
        self.assertTrue(vol['multiattach'])

    def test_create_volume_with_multiattach_flag(self):
        """Tests creating a volume with multiattach=True but no special type.

        This tests the pre 3.50 microversion behavior of being able to create
        a volume with the multiattach request parameter regardless of a
        multiattach-capable volume type.
        """
        volume_api = cinder.volume.api.API()
        volume = volume_api.create(
            self.context, 1, 'name', 'description', multiattach=True,
            volume_type=self.vol_type)
        self.assertTrue(volume.multiattach)

    def _fail_multiattach_policy_authorize(self, policy):
        if policy == vol_policy.MULTIATTACH_POLICY:
            raise exception.PolicyNotAuthorized(action='Test')

    def test_create_volume_with_multiattach_volume_type_not_authorized(self):
        """Test policy unauthorized create with multiattach volume type."""
        elevated = context.get_admin_context()
        volume_api = cinder.volume.api.API()

        especs = dict(multiattach="<is> True")
        volume_types.create(elevated,
                            "multiattach-type",
                            especs,
                            description="test-multiattach")
        foo = objects.VolumeType.get_by_name_or_id(elevated,
                                                   "multiattach-type")

        with mock.patch.object(self.context, 'authorize') as mock_auth:
            mock_auth.side_effect = self._fail_multiattach_policy_authorize
            self.assertRaises(exception.PolicyNotAuthorized,
                              volume_api.create, self.context,
                              1, 'admin-vol', 'description',
                              volume_type=foo)

    def test_create_volume_with_multiattach_flag_not_authorized(self):
        """Test policy unauthorized create with multiattach flag."""
        volume_api = cinder.volume.api.API()

        with mock.patch.object(self.context, 'authorize') as mock_auth:
            mock_auth.side_effect = self._fail_multiattach_policy_authorize
            self.assertRaises(exception.PolicyNotAuthorized,
                              volume_api.create, self.context, 1, 'name',
                              'description', multiattach=True)

    @mock.patch.object(key_manager, 'API', fake_keymgr.fake_api)
    def test_create_volume_with_encrypted_volume_type_multiattach(self):
        ctxt = context.get_admin_context()

        cipher = 'aes-xts-plain64'
        key_size = 256
        control_location = 'front-end'

        db.volume_type_create(ctxt,
                              {'id': '61298380-0c12-11e3-bfd6-4b48424183be',
                               'name': 'LUKS',
                               'extra_specs': {'multiattach': '<is> True'}})
        db.volume_type_encryption_create(
            ctxt,
            '61298380-0c12-11e3-bfd6-4b48424183be',
            {'control_location': control_location,
             'provider': ENCRYPTION_PROVIDER,
             'cipher': cipher,
             'key_size': key_size})

        volume_api = cinder.volume.api.API()

        db_vol_type = db.volume_type_get_by_name(ctxt, 'LUKS')

        self.assertRaises(exception.InvalidVolume,
                          volume_api.create,
                          self.context,
                          1,
                          'name',
                          'description',
                          volume_type=db_vol_type)

    @ddt.data({'cipher': 'blowfish-cbc', 'algo': 'blowfish', 'length': 32},
              {'cipher': 'aes-xts-plain64', 'algo': 'aes', 'length': 256})
    @ddt.unpack
    @mock.patch.object(key_manager, 'API', fake_keymgr.fake_api)
    def test_create_volume_with_encrypted_volume_types(
            self, cipher, algo, length):
        ctxt = context.get_admin_context()

        key_size = length
        control_location = 'front-end'

        db.volume_type_create(ctxt,
                              {'id': '61298380-0c12-11e3-bfd6-4b48424183be',
                               'name': 'LUKS'})
        db.volume_type_encryption_create(
            ctxt,
            '61298380-0c12-11e3-bfd6-4b48424183be',
            {'control_location': control_location,
             'provider': ENCRYPTION_PROVIDER,
             'cipher': cipher,
             'key_size': key_size})

        volume_api = cinder.volume.api.API()

        db_vol_type = db.volume_type_get_by_name(ctxt, 'LUKS')

        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description',
                                   volume_type=db_vol_type)

        key_manager = volume_api.key_manager
        key = key_manager.get(self.context, volume['encryption_key_id'])
        self.assertEqual(key_size, len(key.get_encoded()) * 8)
        self.assertEqual(algo, key.algorithm)

        metadata = db.volume_encryption_metadata_get(self.context, volume.id)
        self.assertEqual(db_vol_type.get('id'), volume['volume_type_id'])
        self.assertEqual(cipher, metadata.get('cipher'))
        self.assertEqual(key_size, metadata.get('key_size'))
        self.assertIsNotNone(volume['encryption_key_id'])

    def test_create_volume_with_provider_id(self):
        volume_params_with_provider_id = dict(provider_id=fake.PROVIDER_ID,
                                              **self.volume_params)

        volume = tests_utils.create_volume(self.context,
                                           **volume_params_with_provider_id)

        self.volume.create_volume(self.context, volume)
        self.assertEqual(fake.PROVIDER_ID, volume['provider_id'])

    def test_create_volume_with_admin_metadata(self):
        with mock.patch.object(
                self.volume.driver, 'create_volume',
                return_value={'admin_metadata': {'foo': 'bar'}}):
            volume = tests_utils.create_volume(self.user_context)
            self.volume.create_volume(self.user_context, volume)
            self.assertEqual({'foo': 'bar'}, volume['admin_metadata'])

    @mock.patch.object(key_manager, 'API', new=fake_keymgr.fake_api)
    def test_create_delete_volume_with_encrypted_volume_type(self):
        cipher = 'aes-xts-plain64'
        key_size = 256
        db.volume_type_create(self.context,
                              {'id': fake.VOLUME_TYPE_ID, 'name': 'LUKS'})
        db.volume_type_encryption_create(
            self.context, fake.VOLUME_TYPE_ID,
            {'control_location': 'front-end', 'provider': ENCRYPTION_PROVIDER,
             'cipher': cipher, 'key_size': key_size})

        db_vol_type = db.volume_type_get_by_name(self.context, 'LUKS')

        volume = self.volume_api.create(self.context,
                                        1,
                                        'name',
                                        'description',
                                        volume_type=db_vol_type)

        self.assertIsNotNone(volume.get('encryption_key_id', None))
        self.assertEqual(db_vol_type.get('id'), volume['volume_type_id'])

        volume['host'] = 'fake_host'
        volume['status'] = 'available'
        db.volume_update(self.context, volume['id'], {'status': 'available'})
        self.volume_api.delete(self.context, volume)

        volume = objects.Volume.get_by_id(self.context, volume.id)
        while volume.status == 'available':
            # Must wait for volume_api delete request to process enough to
            # change the volume status.
            time.sleep(0.5)
            volume.refresh()

        self.assertEqual('deleting', volume['status'])

        db.volume_destroy(self.context, volume['id'])
        self.assertRaises(exception.NotFound,
                          db.volume_get,
                          self.context,
                          volume['id'])

    @mock.patch.object(key_manager, 'API', fake_keymgr.fake_api)
    def test_delete_encrypted_volume_fail_deleting_key(self):
        cipher = 'aes-xts-plain64'
        key_size = 256
        db.volume_type_create(self.context,
                              {'id': fake.VOLUME_TYPE_ID, 'name': 'LUKS'})
        db.volume_type_encryption_create(
            self.context, fake.VOLUME_TYPE_ID,
            {'control_location': 'front-end', 'provider': ENCRYPTION_PROVIDER,
             'cipher': cipher, 'key_size': key_size})

        db_vol_type = db.volume_type_get_by_name(self.context, 'LUKS')

        volume = self.volume_api.create(self.context,
                                        1,
                                        'name',
                                        'description',
                                        volume_type=db_vol_type)

        volume_id = volume['id']
        volume['host'] = 'fake_host'
        volume['status'] = 'available'
        db.volume_update(self.context, volume_id, {'status': 'available'})

        with mock.patch.object(
                self.volume_api.key_manager,
                'delete',
                side_effect=Exception):
            self.assertRaises(exception.InvalidVolume,
                              self.volume_api.delete,
                              self.context,
                              volume)
        volume = objects.Volume.get_by_id(self.context, volume_id)
        self.assertEqual("error_deleting", volume.status)
        volume.destroy()

    @mock.patch.object(key_manager, 'API', fake_keymgr.fake_api)
    def test_delete_encrypted_volume_key_not_found(self):
        cipher = 'aes-xts-plain64'
        key_size = 256
        db.volume_type_create(self.context,
                              {'id': fake.VOLUME_TYPE_ID, 'name': 'LUKS'})
        db.volume_type_encryption_create(
            self.context, fake.VOLUME_TYPE_ID,
            {'control_location': 'front-end', 'provider': ENCRYPTION_PROVIDER,
             'cipher': cipher, 'key_size': key_size})

        db_vol_type = db.volume_type_get_by_name(self.context, 'LUKS')

        volume = self.volume_api.create(self.context,
                                        1,
                                        'name',
                                        'description',
                                        volume_type=db_vol_type)

        volume_id = volume['id']
        volume['host'] = 'fake_host'
        volume['status'] = 'available'
        db.volume_update(self.context, volume_id, {'status': 'available'})

        with mock.patch.object(
                self.volume_api.key_manager,
                'delete',
                side_effect=castellan_exception.ManagedObjectNotFoundError(
                    uuid=fake.ENCRYPTION_KEY_ID)):
            self.volume_api.delete(self.context, volume)

        volume = objects.Volume.get_by_id(self.context, volume_id)
        self.assertEqual("deleting", volume.status)
        volume.destroy()

    @mock.patch('cinder.utils.clean_volume_file_locks')
    def test_delete_busy_volume(self, mock_clean):
        """Test volume survives deletion if driver reports it as busy."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)

        with mock.patch.object(self.volume.driver, 'delete_volume',
                               side_effect=exception.VolumeIsBusy(
                                   volume_name='fake')
                               ) as mock_del_vol:
            self.volume.delete_volume(self.context, volume)
            volume_ref = db.volume_get(context.get_admin_context(), volume_id)
            self.assertEqual(volume_id, volume_ref.id)
            self.assertEqual("available", volume_ref.status)
            mock_del_vol.assert_called_once_with(volume)
        mock_clean.assert_not_called()

    @mock.patch('cinder.utils.clean_volume_file_locks')
    def test_unmanage_encrypted_volume_fails(self, mock_clean):
        volume = tests_utils.create_volume(
            self.context,
            encryption_key_id=fake.ENCRYPTION_KEY_ID,
            **self.volume_params)
        self.volume.create_volume(self.context, volume)
        manager = vol_manager.VolumeManager()
        self.assertRaises(exception.Invalid,
                          manager.delete_volume,
                          self.context,
                          volume,
                          unmanage_only=True)
        mock_clean.assert_not_called()
        self.volume.delete_volume(self.context, volume)

    def test_unmanage_cascade_delete_fails(self):
        volume = tests_utils.create_volume(
            self.context,
            **self.volume_params)
        self.volume.create_volume(self.context, volume)
        manager = vol_manager.VolumeManager()
        self.assertRaises(exception.Invalid,
                          manager.delete_volume,
                          self.context,
                          volume,
                          unmanage_only=True,
                          cascade=True)
        self.volume.delete_volume(self.context, volume)

    def test_get_volume_different_tenant(self):
        """Test can't get volume of another tenant when viewable_admin_meta."""
        volume = tests_utils.create_volume(self.context,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)

        another_context = context.RequestContext('another_user_id',
                                                 'another_project_id',
                                                 is_admin=False)
        self.assertNotEqual(another_context.project_id,
                            self.context.project_id)

        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.VolumeNotFound, volume_api.get,
                          another_context, volume_id, viewable_admin_meta=True)
        self.assertEqual(volume_id,
                         volume_api.get(self.context, volume_id)['id'])

        self.volume.delete_volume(self.context, volume)

    def test_get_all_limit_bad_value(self):
        """Test value of 'limit' is numeric and >= 0"""
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidInput,
                          volume_api.get_all,
                          self.context,
                          limit="A")
        self.assertRaises(exception.InvalidInput,
                          volume_api.get_all,
                          self.context,
                          limit="-1")

    def test_get_all_tenants_volume_list(self):
        """Validate when the volume list for all tenants is returned"""
        volume_api = cinder.volume.api.API()

        with mock.patch.object(volume_api.db,
                               'volume_get_all_by_project') as by_project:
            with mock.patch.object(volume_api.db,
                                   'volume_get_all') as get_all:
                db_volume = {'volume_type_id': fake.VOLUME_TYPE_ID,
                             'name': 'fake_name',
                             'host': 'fake_host',
                             'id': fake.VOLUME_ID}

                volume = fake_volume.fake_db_volume(**db_volume)
                by_project.return_value = [volume]
                get_all.return_value = [volume]

                volume_api.get_all(self.context, filters={'all_tenants': '0'})
                self.assertTrue(by_project.called)
                by_project.called = False

                self.context.is_admin = False
                volume_api.get_all(self.context, filters={'all_tenants': '1'})
                self.assertTrue(by_project.called)

                # check for volume list of all tenants
                self.context.is_admin = True
                volume_api.get_all(self.context, filters={'all_tenants': '1'})
                self.assertTrue(get_all.called)

    @mock.patch('cinder.utils.clean_volume_file_locks')
    def test_delete_volume_in_error_extending(self, mock_clean):
        """Test volume can be deleted in error_extending stats."""
        # create a volume
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume)

        # delete 'error_extending' volume
        db.volume_update(self.context, volume['id'],
                         {'status': 'error_extending'})
        self.volume.delete_volume(self.context, volume)
        self.assertRaises(exception.NotFound, db.volume_get,
                          self.context, volume['id'])
        mock_clean.assert_called_once_with(volume.id, self.volume.driver)

    @mock.patch('cinder.utils.clean_volume_file_locks')
    @mock.patch.object(db.sqlalchemy.api, 'volume_get',
                       side_effect=exception.VolumeNotFound(
                           volume_id='12345678-1234-5678-1234-567812345678'))
    def test_delete_volume_not_found(self, mock_get_volume, mock_clean):
        """Test delete volume moves on if the volume does not exist."""
        volume_id = '12345678-1234-5678-1234-567812345678'
        volume = objects.Volume(self.context, status='available', id=volume_id)
        self.volume.delete_volume(self.context, volume)
        self.assertTrue(mock_get_volume.called)
        mock_clean.assert_called_once_with(volume_id, self.volume.driver)

    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'create_volume_from_snapshot')
    def test_create_volume_from_snapshot(self, mock_create_from_snap):
        """Test volume can be created from a snapshot."""
        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src)
        snapshot_id = create_snapshot(volume_src['id'],
                                      size=volume_src['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, snapshot_obj)
        volume_dst = tests_utils.create_volume(self.context,
                                               snapshot_id=snapshot_id,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_dst)
        self.assertEqual(volume_dst['id'],
                         db.volume_get(
                             context.get_admin_context(),
                             volume_dst['id']).id)
        self.assertEqual(snapshot_id,
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).snapshot_id)

        self.volume.delete_volume(self.context, volume_dst)
        self.volume.delete_snapshot(self.context, snapshot_obj)
        self.volume.delete_volume(self.context, volume_src)

    @mock.patch('cinder.volume.flows.api.create_volume.get_flow')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_create_volume_from_snapshot_with_types(
            self, _get_by_id, _get_flow):
        """Test volume create from snapshot with types including mistmatch."""
        volume_api = cinder.volume.api.API()

        foo_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            name='foo',
            extra_specs={'volume_backend_name': 'dev_1'})
        biz_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE2_ID,
            name='foo',
            extra_specs={'volume_backend_name': 'dev_2'})

        source_vol = fake_volume.fake_volume_obj(
            self.context,
            id=fake.VOLUME_ID,
            status='available',
            volume_size=10,
            volume_type_id=biz_type.id)
        source_vol.volume_type = biz_type
        snapshot = {'id': fake.SNAPSHOT_ID,
                    'status': fields.SnapshotStatus.AVAILABLE,
                    'volume_size': 10,
                    'volume_type_id': biz_type.id}
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.context,
                                                       **snapshot)
        snapshot_obj.volume = source_vol
        # Make sure the case of specifying a type that
        # doesn't match the snapshots type fails
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          volume_type=foo_type,
                          snapshot=snapshot_obj)

        # Make sure that trying to specify a type
        # when the snapshots type is None fails
        snapshot_obj.volume_type_id = None
        snapshot_obj.volume.volume_type_id = None
        snapshot_obj.volume.volume_type = None
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          volume_type=foo_type,
                          snapshot=snapshot_obj)

        snapshot_obj.volume_type_id = foo_type.id
        snapshot_obj.volume.volume_type_id = foo_type.id
        snapshot_obj.volume.volume_type = foo_type
        volume_api.create(self.context, size=1, name='fake_name',
                          description='fake_desc', volume_type=foo_type,
                          snapshot=snapshot_obj)

    @mock.patch('cinder.volume.flows.api.create_volume.get_flow')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_create_volume_from_source_with_types(
            self, _get_by_id, _get_flow):
        """Test volume create from source with types including mistmatch."""
        volume_api = cinder.volume.api.API()
        foo_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            name='foo',
            extra_specs={'volume_backend_name': 'dev_1'})

        biz_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE2_ID,
            name='biz',
            extra_specs={'volume_backend_name': 'dev_2'})

        source_vol = fake_volume.fake_volume_obj(
            self.context,
            id=fake.VOLUME_ID,
            status='available',
            volume_size=0,
            volume_type_id=biz_type.id)
        source_vol.volume_type = biz_type

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          volume_type=foo_type,
                          source_volume=source_vol)

        # Make sure that trying to specify a type
        # when the source type is None fails
        source_vol.volume_type_id = None
        source_vol.volume_type = None
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          volume_type=foo_type,
                          source_volume=source_vol)

        source_vol.volume_type_id = biz_type.id
        source_vol.volume_type = biz_type
        volume_api.create(self.context, size=1, name='fake_name',
                          description='fake_desc', volume_type=biz_type,
                          source_volume=source_vol)

    @mock.patch('cinder.volume.flows.api.create_volume.get_flow')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_create_volume_from_source_with_same_backend(
            self, _get_by_id, _get_flow):
        """Test volume create from source with type mismatch same backend."""
        volume_api = cinder.volume.api.API()

        foo_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            name='foo',
            qos_specs_id=None,
            deleted=False,
            created_at=datetime.datetime(2015, 5, 8, 0, 40, 5, 408232),
            updated_at=None,
            extra_specs={'volume_backend_name': 'dev_1'},
            is_public=True,
            deleted_at=None,
            description=None)

        biz_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE2_ID,
            name='biz',
            qos_specs_id=None,
            deleted=False,
            created_at=datetime.datetime(2015, 5, 8, 0, 20, 5, 408232),
            updated_at=None,
            extra_specs={'volume_backend_name': 'dev_1'},
            is_public=True,
            deleted_at=None,
            description=None)

        source_vol = fake_volume.fake_volume_obj(
            self.context,
            id=fake.VOLUME_ID,
            status='available',
            volume_size=10,
            volume_type_id=biz_type.id)
        source_vol.volume_type = biz_type
        volume_api.create(self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          volume_type=foo_type,
                          source_volume=source_vol)

    @mock.patch('cinder.volume.flows.api.create_volume.get_flow')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_create_from_source_and_snap_only_one_backend(
            self, _get_by_id, _get_flow):
        """Test create from source and snap with type mismatch one backend."""
        volume_api = cinder.volume.api.API()

        foo_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            name='foo',
            qos_specs_id=None,
            deleted=False,
            created_at=datetime.datetime(2015, 5, 8, 0, 40, 5, 408232),
            updated_at=None,
            extra_specs={'some_key': 3},
            is_public=True,
            deleted_at=None,
            description=None)

        biz_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE2_ID,
            name='biz',
            qos_specs_id=None,
            deleted=False,
            created_at=datetime.datetime(2015, 5, 8, 0, 20, 5, 408232),
            updated_at=None,
            extra_specs={'some_other_key': 4},
            is_public=True,
            deleted_at=None,
            description=None)

        source_vol = fake_volume.fake_volume_obj(
            self.context,
            id=fake.VOLUME_ID,
            status='available',
            volume_size=10,
            volume_type_id=biz_type.id)
        source_vol.volume_type = biz_type

        snapshot = {'id': fake.SNAPSHOT_ID,
                    'status': fields.SnapshotStatus.AVAILABLE,
                    'volume_size': 10,
                    'volume_type_id': biz_type['id']}
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.context,
                                                       **snapshot)
        snapshot_obj.volume = source_vol

        with mock.patch('cinder.db.service_get_all') as mock_get_service, \
            mock.patch.object(volume_api,
                              'list_availability_zones') as mock_get_azs:
            mock_get_service.return_value = [
                {'host': 'foo',
                 'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]
            mock_get_azs.return_value = {}
            volume_api.create(self.context,
                              size=1,
                              name='fake_name',
                              description='fake_desc',
                              volume_type=foo_type,
                              source_volume=source_vol)

            volume_api.create(self.context,
                              size=1,
                              name='fake_name',
                              description='fake_desc',
                              volume_type=foo_type,
                              snapshot=snapshot_obj)

    def _test_create_from_source_snapshot_encryptions(
            self, is_snapshot=False):
        volume_api = cinder.volume.api.API()
        foo_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            name='foo',
            extra_specs={'volume_backend_name': 'dev_1'})
        biz_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE2_ID,
            name='biz',
            extra_specs={'volume_backend_name': 'dev_1'})

        source_vol = fake_volume.fake_volume_obj(
            self.context,
            id=fake.VOLUME_ID,
            status='available',
            volume_size=1,
            volume_type_id=biz_type.id)
        source_vol.volume_type = biz_type

        snapshot = {'id': fake.SNAPSHOT_ID,
                    'status': fields.SnapshotStatus.AVAILABLE,
                    'volume_size': 1,
                    'volume_type_id': biz_type['id']}
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.context,
                                                       **snapshot)
        snapshot_obj.volume = source_vol

        with mock.patch.object(
                cinder.volume.volume_types,
                'volume_types_encryption_changed') as mock_encryption_changed:
            mock_encryption_changed.return_value = True
            self.assertRaises(exception.InvalidInput,
                              volume_api.create,
                              self.context,
                              size=1,
                              name='fake_name',
                              description='fake_desc',
                              volume_type=foo_type,
                              source_volume=(
                                  source_vol if not is_snapshot else None),
                              snapshot=snapshot_obj if is_snapshot else None)

    def test_create_from_source_encryption_changed(self):
        self._test_create_from_source_snapshot_encryptions()

    def test_create_from_snapshot_encryption_changed(self):
        self._test_create_from_source_snapshot_encryptions(is_snapshot=True)

    def _mock_synchronized(self, name, *s_args, **s_kwargs):
        def inner_sync1(f):
            def inner_sync2(*args, **kwargs):
                self.called.append('lock-%s' % (name))
                ret = f(*args, **kwargs)
                self.called.append('unlock-%s' % (name))
                return ret
            return inner_sync2
        return inner_sync1

    def _fake_execute(self, *cmd, **kwargs):
        pass

    @mock.patch.object(coordination.Coordinator, 'get_lock')
    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver,
                       'create_volume_from_snapshot')
    def test_create_volume_from_snapshot_check_locks(
            self, mock_lvm_create, mock_lock):
        orig_flow = engine.ActionEngine.run

        def mock_flow_run(*args, **kwargs):
            # ensure the lock has been taken
            mock_lock.assert_called_with('%s-delete_snapshot' % snap_id)
            # now proceed with the flow.
            ret = orig_flow(*args, **kwargs)
            return ret

        # create source volume
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)

        # no lock
        self.volume.create_volume(self.context, src_vol)

        snap_id = create_snapshot(src_vol.id,
                                  size=src_vol['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snap_id)
        # no lock
        self.volume.create_snapshot(self.context, snapshot_obj)

        dst_vol = tests_utils.create_volume(self.context,
                                            snapshot_id=snap_id,
                                            **self.volume_params)
        admin_ctxt = context.get_admin_context()

        # mock the flow runner so we can do some checks
        self.mock_object(engine.ActionEngine, 'run', mock_flow_run)

        # locked
        self.volume.create_volume(self.context, dst_vol,
                                  request_spec={'snapshot_id': snap_id})
        mock_lock.assert_called_with('%s-delete_snapshot' % snap_id)
        self.assertEqual(dst_vol.id, db.volume_get(admin_ctxt, dst_vol.id).id)
        self.assertEqual(snap_id,
                         db.volume_get(admin_ctxt, dst_vol.id).snapshot_id)

        # locked
        self.volume.delete_volume(self.context, dst_vol)
        mock_lock.assert_called_with('%s-delete_volume' % dst_vol.id)

        # locked
        self.volume.delete_snapshot(self.context, snapshot_obj)
        mock_lock.assert_called_with('%s-delete_snapshot' % snap_id)

        # locked
        self.volume.delete_volume(self.context, src_vol)
        mock_lock.assert_called_with('%s-delete_volume' % src_vol.id)

        self.assertTrue(mock_lvm_create.called)

    @mock.patch.object(coordination.Coordinator, 'get_lock')
    def test_create_volume_from_volume_check_locks(self, mock_lock):
        # mock the synchroniser so we can record events
        self.mock_object(utils, 'execute', self._fake_execute)

        orig_flow = engine.ActionEngine.run

        def mock_flow_run(*args, **kwargs):
            # ensure the lock has been taken
            mock_lock.assert_called_with('%s-delete_volume' % src_vol_id)
            # now proceed with the flow.
            ret = orig_flow(*args, **kwargs)
            return ret

        # create source volume
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        # no lock
        self.volume.create_volume(self.context, src_vol)
        self.assertEqual(0, mock_lock.call_count)

        dst_vol = tests_utils.create_volume(self.context,
                                            source_volid=src_vol_id,
                                            **self.volume_params)
        dst_vol_id = dst_vol['id']
        admin_ctxt = context.get_admin_context()

        # mock the flow runner so we can do some checks
        self.mock_object(engine.ActionEngine, 'run', mock_flow_run)

        # locked
        self.volume.create_volume(self.context, dst_vol,
                                  request_spec={'source_volid': src_vol_id})
        mock_lock.assert_called_with('%s-delete_volume' % src_vol_id)
        self.assertEqual(dst_vol_id, db.volume_get(admin_ctxt, dst_vol_id).id)
        self.assertEqual(src_vol_id,
                         db.volume_get(admin_ctxt, dst_vol_id).source_volid)

        # locked
        self.volume.delete_volume(self.context, dst_vol)
        mock_lock.assert_called_with('%s-delete_volume' % dst_vol_id)

        # locked
        self.volume.delete_volume(self.context, src_vol)
        mock_lock.assert_called_with('%s-delete_volume' % src_vol_id)

    def _raise_metadata_copy_failure(self, method, dst_vol):
        # MetadataCopyFailure exception will be raised if DB service is Down
        # while copying the volume glance metadata
        with mock.patch.object(db, method) as mock_db:
            mock_db.side_effect = exception.MetadataCopyFailure(
                reason="Because of DB service down.")
            self.assertRaises(exception.MetadataCopyFailure,
                              self.volume.create_volume,
                              self.context,
                              dst_vol)

        # ensure that status of volume is 'error'
        vol = db.volume_get(self.context, dst_vol.id)
        self.assertEqual('error', vol['status'])

        # cleanup resource
        db.volume_destroy(self.context, dst_vol.id)

    @mock.patch('cinder.utils.execute')
    def test_create_volume_from_volume_with_glance_volume_metadata_none(
            self, mock_execute):
        # create source volume
        mock_execute.return_value = None
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        self.volume.create_volume(self.context, src_vol)
        # set bootable flag of volume to True
        db.volume_update(self.context, src_vol['id'], {'bootable': True})

        # create volume from source volume
        dst_vol = tests_utils.create_volume(self.context,
                                            source_volid=src_vol_id,
                                            **self.volume_params)
        self.volume.create_volume(self.context, dst_vol)

        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_glance_metadata_copy_from_volume_to_volume,
                          self.context, src_vol_id, dst_vol['id'])

        # ensure that status of volume is 'available'
        vol = db.volume_get(self.context, dst_vol['id'])
        self.assertEqual('available', vol['status'])

        # cleanup resource
        db.volume_destroy(self.context, src_vol_id)
        db.volume_destroy(self.context, dst_vol['id'])

    @mock.patch('cinder.utils.execute')
    def test_create_volume_from_volume_raise_metadata_copy_failure(
            self, mock_execute):
        # create source volume
        mock_execute.return_value = None
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        self.volume.create_volume(self.context, src_vol)
        # set bootable flag of volume to True
        db.volume_update(self.context, src_vol['id'], {'bootable': True})

        # create volume from source volume
        dst_vol = tests_utils.create_volume(self.context,
                                            source_volid=src_vol_id,
                                            **self.volume_params)
        self._raise_metadata_copy_failure(
            'volume_glance_metadata_copy_from_volume_to_volume',
            dst_vol)

        # cleanup resource
        db.volume_destroy(self.context, src_vol_id)

    @mock.patch('cinder.utils.execute')
    def test_create_volume_from_snapshot_raise_metadata_copy_failure(
            self, mock_execute):
        # create source volume
        mock_execute.return_value = None
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        self.volume.create_volume(self.context, src_vol)
        # set bootable flag of volume to True
        db.volume_update(self.context, src_vol['id'], {'bootable': True})

        # create volume from snapshot
        snapshot_id = create_snapshot(src_vol['id'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, snapshot_obj)

        # ensure that status of snapshot is 'available'
        self.assertEqual(fields.SnapshotStatus.AVAILABLE, snapshot_obj.status)

        dst_vol = tests_utils.create_volume(self.context,
                                            snapshot_id=snapshot_id,
                                            **self.volume_params)
        self._raise_metadata_copy_failure(
            'volume_glance_metadata_copy_to_volume',
            dst_vol)

        # cleanup resource
        snapshot_obj.destroy()
        db.volume_destroy(self.context, src_vol_id)

    @mock.patch('cinder.utils.execute')
    def test_create_volume_from_snapshot_with_glance_volume_metadata_none(
            self, mock_execute):
        # create source volume
        mock_execute.return_value = None
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        self.volume.create_volume(self.context, src_vol)
        # set bootable flag of volume to True
        db.volume_update(self.context, src_vol['id'], {'bootable': True})

        volume = db.volume_get(self.context, src_vol_id)

        # create snapshot of volume
        snapshot_id = create_snapshot(volume['id'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, snapshot_obj)

        # ensure that status of snapshot is 'available'
        self.assertEqual(fields.SnapshotStatus.AVAILABLE, snapshot_obj.status)

        # create volume from snapshot
        dst_vol = tests_utils.create_volume(self.context,
                                            snapshot_id=snapshot_id,
                                            **self.volume_params)
        self.volume.create_volume(self.context, dst_vol)

        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_glance_metadata_copy_to_volume,
                          self.context, dst_vol['id'], snapshot_id)

        # ensure that status of volume is 'available'
        vol = db.volume_get(self.context, dst_vol['id'])
        self.assertEqual('available', vol['status'])

        # cleanup resource
        snapshot_obj.destroy()
        db.volume_destroy(self.context, src_vol_id)
        db.volume_destroy(self.context, dst_vol['id'])

    @ddt.data({'connector_class':
               os_brick.initiator.connectors.iscsi.ISCSIConnector,
               'rekey_supported': True,
               'already_encrypted': 'yes'},
              {'connector_class':
               os_brick.initiator.connectors.iscsi.ISCSIConnector,
               'rekey_supported': True,
               'already_encrypted': 'no'},
              {'connector_class':
               os_brick.initiator.connectors.rbd.RBDConnector,
               'rekey_supported': False,
               'already_encrypted': 'no'})
    @ddt.unpack
    @mock.patch('cinder.volume.volume_utils.delete_encryption_key')
    @mock.patch('cinder.volume.flows.manager.create_volume.'
                'CreateVolumeFromSpecTask._setup_encryption_keys')
    @mock.patch('cinder.db.sqlalchemy.api.volume_encryption_metadata_get')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.volume.driver.VolumeDriver._detach_volume')
    @mock.patch('cinder.volume.driver.VolumeDriver._attach_volume')
    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.utils.execute')
    def test_create_volume_from_volume_with_enc(
            self, mock_execute, mock_brick_gcp, mock_at, mock_det,
            mock_qemu_img_info, mock_enc_metadata_get, mock_setup_enc_keys,
            mock_del_enc_key, connector_class=None, rekey_supported=None,
            already_encrypted=None):
        # create source volume
        mock_execute.return_value = ('', '')
        mock_enc_metadata_get.return_value = {'cipher': 'aes-xts-plain64',
                                              'key_size': 256,
                                              'provider': 'luks'}
        mock_setup_enc_keys.return_value = (
            'qwert',
            'asdfg',
            fake.ENCRYPTION_KEY2_ID)

        params = {'status': 'creating',
                  'size': 1,
                  'host': CONF.host,
                  'encryption_key_id': fake.ENCRYPTION_KEY_ID}
        src_vol = tests_utils.create_volume(self.context, **params)
        src_vol_id = src_vol['id']

        self.volume.create_volume(self.context, src_vol)
        db.volume_update(self.context,
                         src_vol['id'],
                         {'encryption_key_id': fake.ENCRYPTION_KEY_ID})

        # create volume from source volume
        params['encryption_key_id'] = fake.ENCRYPTION_KEY2_ID

        attach_info = {
            'connector': connector_class(None),
            'device': {'path': '/some/device/thing'}}
        mock_at.return_value = (attach_info, src_vol)

        img_info = imageutils.QemuImgInfo()
        if already_encrypted:
            # defaults to None when not encrypted
            img_info.encrypted = 'yes'
        img_info.file_format = 'raw'
        mock_qemu_img_info.return_value = img_info

        dst_vol = tests_utils.create_volume(self.context,
                                            source_volid=src_vol_id,
                                            **params)
        self.volume.create_volume(self.context, dst_vol)

        # ensure that status of volume is 'available'
        vol = db.volume_get(self.context, dst_vol['id'])
        self.assertEqual('available', vol['status'])

        # cleanup resource
        db.volume_destroy(self.context, src_vol_id)
        db.volume_destroy(self.context, dst_vol['id'])

        if rekey_supported:
            mock_setup_enc_keys.assert_called_once_with(
                mock.ANY,
                src_vol,
                {'key_size': 256,
                 'provider': 'luks',
                 'cipher': 'aes-xts-plain64'}
            )
            if already_encrypted:
                mock_execute.assert_called_once_with(
                    'cryptsetup', 'luksChangeKey',
                    '/some/device/thing',
                    '--force-password',
                    log_errors=processutils.LOG_ALL_ERRORS,
                    process_input='qwert\nasdfg\n',
                    run_as_root=True)

            else:
                mock_execute.assert_called_once_with(
                    'cryptsetup', '--batch-mode', 'luksFormat',
                    '--type', 'luks1',
                    '--cipher', 'aes-xts-plain64', '--key-size', '256',
                    '--key-file=-', '/some/device/thing',
                    process_input='asdfg',
                    run_as_root=True)
            mock_del_enc_key.assert_called_once_with(mock.ANY,  # context
                                                     mock.ANY,  # keymgr
                                                     fake.ENCRYPTION_KEY2_ID)
        else:
            mock_setup_enc_keys.assert_not_called()
            mock_execute.assert_not_called()
            mock_del_enc_key.assert_not_called()
        mock_at.assert_called()
        mock_det.assert_called()

    @mock.patch('cinder.db.sqlalchemy.api.volume_encryption_metadata_get')
    def test_setup_encryption_keys(self, mock_enc_metadata_get):
        key_mgr = fake_keymgr.fake_api()
        self.mock_object(castellan.key_manager, 'API', return_value=key_mgr)
        key_id = key_mgr.store(self.context, KeyObject())
        key2_id = key_mgr.store(self.context, KeyObject2())

        params = {'status': 'creating',
                  'size': 1,
                  'host': CONF.host,
                  'encryption_key_id': key_id}
        vol = tests_utils.create_volume(self.context, **params)

        self.volume.create_volume(self.context, vol)
        db.volume_update(self.context,
                         vol['id'],
                         {'encryption_key_id': key_id})

        mock_enc_metadata_get.return_value = {'cipher': 'aes-xts-plain64',
                                              'key_size': 256,
                                              'provider': 'luks'}
        ctxt = context.get_admin_context()

        enc_info = {'encryption_key_id': key_id}
        with mock.patch('cinder.volume.volume_utils.create_encryption_key',
                        return_value=key2_id):
            r = cinder.volume.flows.manager.create_volume.\
                CreateVolumeFromSpecTask._setup_encryption_keys(ctxt,
                                                                vol,
                                                                enc_info)
        (source_pass, new_pass, new_key_id) = r
        self.assertNotEqual(source_pass, new_pass)
        self.assertEqual(new_key_id, key2_id)

    @mock.patch.object(key_manager, 'API', fake_keymgr.fake_api)
    def test_create_volume_from_snapshot_with_encryption(self):
        """Test volume can be created from a snapshot of an encrypted volume"""
        ctxt = context.get_admin_context()
        cipher = 'aes-xts-plain64'
        key_size = 256

        db.volume_type_create(ctxt,
                              {'id': '61298380-0c12-11e3-bfd6-4b48424183be',
                               'name': 'LUKS'})
        db.volume_type_encryption_create(
            ctxt,
            '61298380-0c12-11e3-bfd6-4b48424183be',
            {'control_location': 'front-end', 'provider': ENCRYPTION_PROVIDER,
             'cipher': cipher, 'key_size': key_size})

        volume_api = cinder.volume.api.API()

        db_vol_type = db.volume_type_get_by_name(context.get_admin_context(),
                                                 'LUKS')
        volume_src = volume_api.create(self.context,
                                       1,
                                       'name',
                                       'description',
                                       volume_type=db_vol_type)

        db.volume_update(self.context, volume_src['id'],
                         {'host': 'fake_host@fake_backend',
                          'status': 'available'})
        volume_src = objects.Volume.get_by_id(self.context, volume_src['id'])

        snapshot_ref = volume_api.create_snapshot_force(self.context,
                                                        volume_src,
                                                        'name',
                                                        'description')
        snapshot_ref['status'] = fields.SnapshotStatus.AVAILABLE
        # status must be available
        volume_dst = volume_api.create(self.context,
                                       1,
                                       'name',
                                       'description',
                                       snapshot=snapshot_ref)
        self.assertEqual(volume_dst['id'],
                         db.volume_get(
                             context.get_admin_context(),
                             volume_dst['id']).id)
        self.assertEqual(snapshot_ref['id'],
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).snapshot_id)

        # ensure encryption keys match
        self.assertIsNotNone(volume_src['encryption_key_id'])
        self.assertIsNotNone(volume_dst['encryption_key_id'])

        key_manager = volume_api.key_manager  # must use *same* key manager
        volume_src_key = key_manager.get(self.context,
                                         volume_src['encryption_key_id'])
        volume_dst_key = key_manager.get(self.context,
                                         volume_dst['encryption_key_id'])
        self.assertEqual(volume_src_key, volume_dst_key)

    def test_create_volume_from_encrypted_volume(self):
        """Test volume can be created from an encrypted volume."""
        self.mock_object(key_manager, 'API', fake_keymgr.fake_api)
        cipher = 'aes-xts-plain64'
        key_size = 256

        volume_api = cinder.volume.api.API()

        ctxt = context.get_admin_context()

        db.volume_type_create(ctxt,
                              {'id': '61298380-0c12-11e3-bfd6-4b48424183be',
                               'name': 'LUKS'})
        db.volume_type_encryption_create(
            ctxt,
            '61298380-0c12-11e3-bfd6-4b48424183be',
            {'control_location': 'front-end', 'provider': ENCRYPTION_PROVIDER,
             'cipher': cipher, 'key_size': key_size})

        db_vol_type = db.volume_type_get_by_name(context.get_admin_context(),
                                                 'LUKS')
        volume_src = volume_api.create(self.context,
                                       1,
                                       'name',
                                       'description',
                                       volume_type=db_vol_type)
        db.volume_update(self.context, volume_src['id'],
                         {'host': 'fake_host@fake_backend',
                          'status': 'available'})
        volume_src = objects.Volume.get_by_id(self.context, volume_src['id'])
        volume_dst = volume_api.create(self.context,
                                       1,
                                       'name',
                                       'description',
                                       source_volume=volume_src)
        self.assertEqual(volume_dst['id'],
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).id)
        self.assertEqual(volume_src['id'],
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).source_volid)

        # ensure encryption keys match
        self.assertIsNotNone(volume_src['encryption_key_id'])
        self.assertIsNotNone(volume_dst['encryption_key_id'])

        km = volume_api.key_manager  # must use *same* key manager
        volume_src_key = km.get(self.context,
                                volume_src['encryption_key_id'])
        volume_dst_key = km.get(self.context,
                                volume_dst['encryption_key_id'])
        self.assertEqual(volume_src_key, volume_dst_key)

    def test_delete_invalid_status_fails(self):
        self.volume_params['status'] = 'invalid1234'
        volume = tests_utils.create_volume(self.context,
                                           **self.volume_params)
        vol_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          vol_api.delete,
                          self.context,
                          volume)

    def test_create_volume_from_snapshot_fail_bad_size(self):
        """Test volume can't be created from snapshot with bad volume size."""
        volume_api = cinder.volume.api.API()

        snapshot = {'id': fake.SNAPSHOT_ID,
                    'status': fields.SnapshotStatus.AVAILABLE,
                    'volume_size': 10}
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.context,
                                                       **snapshot)
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          snapshot=snapshot_obj)

    def test_create_volume_from_snapshot_fail_wrong_az(self):
        """Test volume can't be created from snapshot in a different az."""
        volume_api = cinder.volume.api.API()

        def fake_list_availability_zones(enable_cache=False):
            return ({'name': 'nova', 'available': True},
                    {'name': 'az2', 'available': True})

        self.mock_object(volume_api,
                         'list_availability_zones',
                         fake_list_availability_zones)

        volume_src = tests_utils.create_volume(self.context,
                                               availability_zone='az2',
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src)
        snapshot = create_snapshot(volume_src['id'])

        self.volume.create_snapshot(self.context, snapshot)

        volume_dst = volume_api.create(self.context,
                                       size=1,
                                       name='fake_name',
                                       description='fake_desc',
                                       snapshot=snapshot)
        self.assertEqual('az2', volume_dst['availability_zone'])

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          snapshot=snapshot,
                          availability_zone='nova')

    def test_create_volume_with_invalid_exclusive_options(self):
        """Test volume create with multiple exclusive options fails."""
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          1,
                          'name',
                          'description',
                          snapshot=fake.SNAPSHOT_ID,
                          image_id=fake.IMAGE_ID,
                          source_volume=fake.VOLUME_ID)

    def test_reserve_volume_success(self):
        volume = tests_utils.create_volume(self.context, status='available')
        cinder.volume.api.API().reserve_volume(self.context, volume)
        volume_db = db.volume_get(self.context, volume.id)
        self.assertEqual('attaching', volume_db.status)
        db.volume_destroy(self.context, volume.id)

    def test_reserve_volume_in_attaching(self):
        self._test_reserve_volume_bad_status('attaching')

    def test_reserve_volume_in_maintenance(self):
        self._test_reserve_volume_bad_status('maintenance')

    def _test_reserve_volume_bad_status(self, status):
        volume = tests_utils.create_volume(self.context, status=status)
        self.assertRaises(exception.InvalidVolume,
                          cinder.volume.api.API().reserve_volume,
                          self.context,
                          volume)
        db.volume_destroy(self.context, volume.id)

    def test_attachment_reserve_with_bootable_volume(self):
        # test the private _attachment_reserve method with a bootable,
        # in-use, multiattach volume.
        instance_uuid = fake.UUID1
        volume = tests_utils.create_volume(self.context, status='in-use')
        tests_utils.attach_volume(self.context, volume.id, instance_uuid,
                                  'attached_host', 'mountpoint', mode='rw')
        volume.multiattach = True
        volume.bootable = True

        attachment = self.volume_api._attachment_reserve(
            self.context, volume, instance_uuid)

        self.assertEqual(attachment.attach_status, 'reserved')

    def test_attachment_reserve_conditional_update_attach_race(self):
        # Tests a scenario where two instances are racing to attach the
        # same multiattach=False volume. One updates the volume status to
        # "reserved" but the other fails the conditional update which is
        # then validated to not be the same instance that is already attached
        # to the multiattach=False volume which triggers a failure.
        volume = tests_utils.create_volume(self.context)
        # Assert that we're not dealing with a multiattach volume and that
        # it does not have any existing attachments.
        self.assertFalse(volume.multiattach)
        self.assertEqual(0, len(volume.volume_attachment))
        # Attach the first instance which is OK and should update the volume
        # status to 'reserved'.
        self.volume_api._attachment_reserve(self.context, volume, fake.UUID1)
        # Try attaching a different instance to the same volume which should
        # fail.
        ex = self.assertRaises(exception.InvalidVolume,
                               self.volume_api._attachment_reserve,
                               self.context, volume, fake.UUID2)
        self.assertIn("status must be available or downloading", str(ex))

    def test_attachment_reserve_with_instance_uuid_error_volume(self):
        # Tests that trying to create an attachment (with an instance_uuid
        # provided) on a volume that's not 'available' or 'downloading' status
        # will fail if the volume does not have any attachments, similar to how
        # the volume reserve action works.
        volume = tests_utils.create_volume(self.context, status='error')
        # Assert that we're not dealing with a multiattach volume and that
        # it does not have any existing attachments.
        self.assertFalse(volume.multiattach)
        self.assertEqual(0, len(volume.volume_attachment))
        # Try attaching an instance to the volume which should fail based on
        # the volume status.
        ex = self.assertRaises(exception.InvalidVolume,
                               self.volume_api._attachment_reserve,
                               self.context, volume, fake.UUID1)
        self.assertIn("status must be available or downloading", str(ex))

    def test_unreserve_volume_success_in_use(self):
        volume = tests_utils.create_volume(self.context, status='attaching')
        tests_utils.attach_volume(self.context, volume.id, fake.INSTANCE_ID,
                                  'attached_host', 'mountpoint', mode='rw')

        cinder.volume.api.API().unreserve_volume(self.context, volume)

        db_volume = db.volume_get(self.context, volume.id)
        self.assertEqual('in-use', db_volume.status)

    def test_unreserve_volume_success_available(self):
        volume = tests_utils.create_volume(self.context, status='attaching')

        cinder.volume.api.API().unreserve_volume(self.context, volume)

        db_volume = db.volume_get(self.context, volume.id)
        self.assertEqual('available', db_volume.status)

    def test_multi_node(self):
        # TODO(termie): Figure out how to test with two nodes,
        # each of them having a different FLAG for storage_node
        # This will allow us to test cross-node interactions
        pass

    def test_cannot_delete_volume_in_use(self):
        """Test volume can't be deleted in in-use status."""
        self._test_cannot_delete_volume('in-use')

    def test_cannot_delete_volume_maintenance(self):
        """Test volume can't be deleted in maintenance status."""
        self._test_cannot_delete_volume('maintenance')

    @mock.patch('cinder.utils.clean_volume_file_locks')
    def _test_cannot_delete_volume(self, status, mock_clean):
        """Test volume can't be deleted in invalid stats."""
        # create a volume and assign to host
        volume = tests_utils.create_volume(self.context, CONF.host,
                                           status=status)

        # 'in-use' status raises InvalidVolume
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.delete,
                          self.context,
                          volume)
        mock_clean.assert_not_called()

        # clean up
        self.volume.delete_volume(self.context, volume)

    def test_force_delete_volume(self):
        """Test volume can be forced to delete."""
        # create a volume and assign to host
        self.volume_params['status'] = 'error_deleting'
        volume = tests_utils.create_volume(self.context, **self.volume_params)

        # 'error_deleting' volumes can't be deleted
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.delete,
                          self.context,
                          volume)

        # delete with force
        self.volume_api.delete(self.context, volume, force=True)

        # status is deleting
        volume = objects.Volume.get_by_id(context.get_admin_context(),
                                          volume.id)
        self.assertEqual('deleting', volume.status)

        # clean up
        self.volume.delete_volume(self.context, volume)

    def test_cannot_force_delete_attached_volume(self):
        """Test volume can't be force delete in attached state."""
        volume = tests_utils.create_volume(self.context, CONF.host,
                                           status='in-use',
                                           attach_status=
                                           fields.VolumeAttachStatus.ATTACHED)

        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.delete,
                          self.context,
                          volume,
                          force=True)

        db.volume_destroy(self.context, volume.id)

    @mock.patch('cinder.utils.clean_volume_file_locks')
    def test__revert_to_snapshot_generic_failed(self, mock_clean):
        fake_volume = tests_utils.create_volume(self.context,
                                                status='available')
        fake_snapshot = tests_utils.create_snapshot(self.context,
                                                    fake_volume.id)
        with mock.patch.object(
                self.volume.driver,
                '_create_temp_volume_from_snapshot') as mock_temp, \
                mock.patch.object(
                    self.volume.driver,
                    'delete_volume') as mock_driver_delete, \
                mock.patch.object(
                    self.volume, '_copy_volume_data') as mock_copy:
            temp_volume = tests_utils.create_volume(self.context,
                                                    status='available')
            mock_copy.side_effect = [exception.VolumeDriverException('error')]
            mock_temp.return_value = temp_volume

            self.assertRaises(exception.VolumeDriverException,
                              self.volume._revert_to_snapshot_generic,
                              self.context, fake_volume, fake_snapshot)

            mock_copy.assert_called_once_with(
                self.context, temp_volume, fake_volume)
            mock_driver_delete.assert_called_once_with(temp_volume)
            mock_clean.assert_called_once_with(temp_volume.id,
                                               self.volume.driver)

    @mock.patch('cinder.utils.clean_volume_file_locks')
    def test__revert_to_snapshot_generic(self, mock_clean):
        fake_volume = tests_utils.create_volume(self.context,
                                                status='available')
        fake_snapshot = tests_utils.create_snapshot(self.context,
                                                    fake_volume.id)
        with mock.patch.object(
                self.volume.driver,
                '_create_temp_volume_from_snapshot') as mock_temp,\
            mock.patch.object(
                self.volume.driver, 'delete_volume') as mock_driver_delete,\
                mock.patch.object(
                    self.volume, '_copy_volume_data') as mock_copy:
            temp_volume = tests_utils.create_volume(self.context,
                                                    status='available')
            mock_temp.return_value = temp_volume
            self.volume._revert_to_snapshot_generic(
                self.context, fake_volume, fake_snapshot)
            mock_copy.assert_called_once_with(
                self.context, temp_volume, fake_volume)
            mock_driver_delete.assert_called_once_with(temp_volume)
            mock_clean.assert_called_once_with(temp_volume.id,
                                               self.volume.driver)

    @ddt.data({'driver_error': True},
              {'driver_error': False})
    @ddt.unpack
    def test__revert_to_snapshot(self, driver_error):
        mock.patch.object(self.volume, '_notify_about_snapshot_usage')
        with mock.patch.object(self.volume.driver,
                               'revert_to_snapshot') as driver_revert, \
            mock.patch.object(self.volume, '_notify_about_volume_usage'), \
            mock.patch.object(self.volume, '_notify_about_snapshot_usage'),\
            mock.patch.object(self.volume,
                              '_revert_to_snapshot_generic') as generic_revert:
            if driver_error:
                driver_revert.side_effect = [NotImplementedError]
            else:
                driver_revert.return_value = None

            self.volume._revert_to_snapshot(self.context, {}, {})

            driver_revert.assert_called_once_with(self.context, {}, {})
            if driver_error:
                generic_revert.assert_called_once_with(self.context, {}, {})

    @ddt.data({},
              {'has_snapshot': True},
              {'use_temp_snapshot': True},
              {'use_temp_snapshot': True, 'has_snapshot': True})
    @ddt.unpack
    def test_revert_to_snapshot(self, has_snapshot=False,
                                use_temp_snapshot=False):
        fake_volume = tests_utils.create_volume(self.context,
                                                status='reverting',
                                                project_id='123',
                                                size=2)
        fake_snapshot = tests_utils.create_snapshot(self.context,
                                                    fake_volume['id'],
                                                    status='restoring',
                                                    volume_size=1)
        with mock.patch.object(self.volume,
                               '_revert_to_snapshot') as _revert,\
            mock.patch.object(self.volume,
                              '_create_backup_snapshot') as _create_snapshot,\
            mock.patch.object(self.volume,
                              'delete_snapshot') as _delete_snapshot, \
            mock.patch.object(self.volume.driver,
                              'snapshot_revert_use_temp_snapshot') as \
                _use_temp_snap:
            _revert.return_value = None
            _use_temp_snap.return_value = use_temp_snapshot

            if has_snapshot:
                _create_snapshot.return_value = {'id': 'fake_snapshot'}
            else:
                _create_snapshot.return_value = None
            self.volume.revert_to_snapshot(self.context, fake_volume,
                                           fake_snapshot)
            _revert.assert_called_once_with(self.context, fake_volume,
                                            fake_snapshot)

            if not use_temp_snapshot:
                _create_snapshot.assert_not_called()
            else:
                _create_snapshot.assert_called_once_with(self.context,
                                                         fake_volume)

            if use_temp_snapshot and has_snapshot:
                _delete_snapshot.assert_called_once_with(
                    self.context, {'id': 'fake_snapshot'})
            else:
                _delete_snapshot.assert_not_called()

            fake_volume.refresh()
            fake_snapshot.refresh()
            self.assertEqual('available', fake_volume['status'])
            self.assertEqual('available', fake_snapshot['status'])
            self.assertEqual(2, fake_volume['size'])

    def test_revert_to_snapshot_failed(self):
        fake_volume = tests_utils.create_volume(self.context,
                                                status='reverting',
                                                project_id='123',
                                                size=2)
        fake_snapshot = tests_utils.create_snapshot(self.context,
                                                    fake_volume['id'],
                                                    status='restoring',
                                                    volume_size=1)
        with mock.patch.object(self.volume,
                               '_revert_to_snapshot') as _revert, \
            mock.patch.object(self.volume,
                              '_create_backup_snapshot'), \
            mock.patch.object(self.volume,
                              'delete_snapshot') as _delete_snapshot:
            _revert.side_effect = [exception.VolumeDriverException(
                message='fake_message')]
            self.assertRaises(exception.VolumeDriverException,
                              self.volume.revert_to_snapshot,
                              self.context, fake_volume,
                              fake_snapshot)
            _revert.assert_called_once_with(self.context, fake_volume,
                                            fake_snapshot)
            _delete_snapshot.assert_not_called()
            fake_volume.refresh()
            fake_snapshot.refresh()
            self.assertEqual('error', fake_volume['status'])
            self.assertEqual('available', fake_snapshot['status'])
            self.assertEqual(2, fake_volume['size'])

    def test_cannot_revert_to_snapshot_in_use(self):
        """Test volume can't be reverted to snapshot in in-use status."""
        fake_volume = tests_utils.create_volume(self.context,
                                                status='in-use')
        fake_snapshot = tests_utils.create_snapshot(self.context,
                                                    fake_volume.id,
                                                    status='available')

        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.revert_to_snapshot,
                          self.context,
                          fake_volume,
                          fake_snapshot)

    @ddt.data(True, False)
    @mock.patch('cinder.quota.QUOTAS.commit')
    @mock.patch('cinder.quota.QUOTAS.reserve')
    @mock.patch.object(vol_manager.VolumeManager,
                       '_notify_about_snapshot_usage')
    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver, 'delete_snapshot')
    def test_delete_snapshot(self, use_quota, delete_mock, notify_mock,
                             reserve_mock, commit_mock):
        """Test delete snapshot."""
        volume = tests_utils.create_volume(self.context, CONF.host)

        snapshot = create_snapshot(volume.id, size=volume.size,
                                   ctxt=self.context,
                                   use_quota=use_quota,
                                   status=fields.SnapshotStatus.AVAILABLE)

        self.volume.delete_snapshot(self.context, snapshot)

        delete_mock.assert_called_once_with(snapshot)
        self.assertEqual(2, notify_mock.call_count)
        notify_mock.assert_has_calls((
            mock.call(mock.ANY, snapshot, 'delete.start'),
            mock.call(mock.ANY, snapshot, 'delete.end'),
        ))

        if use_quota:
            reserve_mock.assert_called_once_with(
                mock.ANY, project_id=snapshot.project_id,
                gigabytes=-snapshot.volume_size,
                gigabytes_vol_type_name=-snapshot.volume_size,
                snapshots=-1, snapshots_vol_type_name=-1)
            commit_mock.assert_called_once_with(mock.ANY,
                                                reserve_mock.return_value,
                                                project_id=snapshot.project_id)
        else:
            reserve_mock.assert_not_called()
            commit_mock.assert_not_called()

        self.assertEqual(fields.SnapshotStatus.DELETED, snapshot.status)
        self.assertTrue(snapshot.deleted)

    def test_cannot_delete_volume_with_snapshots(self):
        """Test volume can't be deleted with dependent snapshots."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume)
        snapshot = create_snapshot(volume['id'], size=volume['size'])
        self.volume.create_snapshot(self.context, snapshot)
        self.assertEqual(
            snapshot.id, objects.Snapshot.get_by_id(self.context,
                                                    snapshot.id).id)

        volume['status'] = 'available'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete,
                          self.context,
                          volume)
        self.volume.delete_snapshot(self.context, snapshot)
        self.volume.delete_volume(self.context, volume)

    def test_can_delete_errored_snapshot(self):
        """Test snapshot can be created and deleted."""
        volume = tests_utils.create_volume(self.context, CONF.host)

        snapshot = create_snapshot(volume.id, size=volume['size'],
                                   ctxt=self.context,
                                   status=fields.SnapshotStatus.ERROR)

        self.volume_api.delete_snapshot(self.context, snapshot)

        self.assertEqual(fields.SnapshotStatus.DELETING, snapshot.status)
        self.volume.delete_volume(self.context, volume)

    def test_create_snapshot_set_worker(self):
        volume = tests_utils.create_volume(self.context)
        snapshot = create_snapshot(volume.id, size=volume['size'],
                                   ctxt=self.context,
                                   status=fields.SnapshotStatus.CREATING)

        self.volume.create_snapshot(self.context, snapshot)

        volume.set_worker.assert_called_once_with()

    def test_cannot_delete_snapshot_with_bad_status(self):
        volume = tests_utils.create_volume(self.context, CONF.host)
        snapshot = create_snapshot(volume.id, size=volume['size'],
                                   ctxt=self.context,
                                   status=fields.SnapshotStatus.CREATING)
        self.assertRaises(exception.InvalidSnapshot,
                          self.volume_api.delete_snapshot,
                          self.context,
                          snapshot)

        snapshot.status = fields.SnapshotStatus.ERROR
        snapshot.save()
        self.volume_api.delete_snapshot(self.context, snapshot)

        self.assertEqual(fields.SnapshotStatus.DELETING, snapshot.status)
        self.volume.delete_volume(self.context, volume)

    @mock.patch.object(QUOTAS, "rollback")
    @mock.patch.object(QUOTAS, "commit")
    @mock.patch.object(QUOTAS, "reserve", return_value=["RESERVATION"])
    def _do_test_create_volume_with_size(self, size, *_unused_quota_mocks):
        volume_api = cinder.volume.api.API()

        volume = volume_api.create(self.context,
                                   size,
                                   'name',
                                   'description',
                                   volume_type=self.vol_type)
        self.assertEqual(int(size), volume['size'])

    def test_create_volume_int_size(self):
        """Test volume creation with int size."""
        self._do_test_create_volume_with_size(2)

    def test_create_volume_string_size(self):
        """Test volume creation with string size."""
        self._do_test_create_volume_with_size('2')

    @mock.patch.object(QUOTAS, "rollback")
    @mock.patch.object(QUOTAS, "commit")
    @mock.patch.object(QUOTAS, "reserve", return_value=["RESERVATION"])
    def test_create_volume_with_bad_size(self, *_unused_quota_mocks):
        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          '2Gb',
                          'name',
                          'description')

    def test_create_volume_with_float_fails(self):
        """Test volume creation with invalid float size."""
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          '1.5',
                          'name',
                          'description')

    def test_create_volume_with_zero_size_fails(self):
        """Test volume creation with string size."""
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          '0',
                          'name',
                          'description')

    def test_begin_detaching_fails_available(self):
        volume_api = cinder.volume.api.API()
        volume = tests_utils.create_volume(self.context, status='available')
        # Volume status is 'available'.
        self.assertRaises(exception.InvalidVolume, volume_api.begin_detaching,
                          self.context, volume)

        db.volume_update(self.context, volume.id,
                         {'status': 'in-use',
                          'attach_status':
                              fields.VolumeAttachStatus.DETACHED})
        # Should raise an error since not attached
        self.assertRaises(exception.InvalidVolume, volume_api.begin_detaching,
                          self.context, volume)

        db.volume_update(self.context, volume.id,
                         {'attach_status':
                          fields.VolumeAttachStatus.ATTACHED})
        # Ensure when attached no exception raised
        volume_api.begin_detaching(self.context, volume)

        volume_api.update(self.context, volume, {'status': 'maintenance'})
        self.assertRaises(exception.InvalidVolume, volume_api.begin_detaching,
                          self.context, volume)
        db.volume_destroy(self.context, volume.id)

    def test_begin_roll_detaching_volume(self):
        """Test begin_detaching and roll_detaching functions."""

        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        attachment = db.volume_attach(self.context,
                                      {'volume_id': volume['id'],
                                       'attached_host': 'fake-host'})
        db.volume_attached(self.context, attachment['id'], instance_uuid,
                           'fake-host', 'vdb')
        volume_api = cinder.volume.api.API()
        volume_api.begin_detaching(self.context, volume)
        volume = volume_api.get(self.context, volume['id'])
        self.assertEqual("detaching", volume['status'])
        volume_api.roll_detaching(self.context, volume)
        volume = volume_api.get(self.context, volume['id'])
        self.assertEqual("in-use", volume['status'])

    def test_volume_api_update(self):
        # create a raw vol
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        # use volume.api to update name
        volume_api = cinder.volume.api.API()
        update_dict = {'display_name': 'test update name'}
        volume_api.update(self.context, volume, update_dict)
        # read changes from db
        vol = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEqual('test update name', vol['display_name'])

    def test_volume_api_update_maintenance(self):
        # create a raw vol
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume['status'] = 'maintenance'
        # use volume.api to update name
        volume_api = cinder.volume.api.API()
        update_dict = {'display_name': 'test update name'}
        self.assertRaises(exception.InvalidVolume, volume_api.update,
                          self.context, volume, update_dict)

    def test_volume_api_get_list_volumes_image_metadata(self):
        """Test get_list_volumes_image_metadata in volume API."""
        ctxt = context.get_admin_context()
        db.volume_create(ctxt, {'id': 'fake1', 'status': 'available',
                                'host': 'test', 'provider_location': '',
                                'size': 1,
                                'volume_type_id': fake.VOLUME_TYPE_ID})
        db.volume_glance_metadata_create(ctxt, 'fake1', 'key1', 'value1')
        db.volume_glance_metadata_create(ctxt, 'fake1', 'key2', 'value2')
        db.volume_create(ctxt, {'id': 'fake2', 'status': 'available',
                                'host': 'test', 'provider_location': '',
                                'size': 1,
                                'volume_type_id': fake.VOLUME_TYPE_ID})
        db.volume_glance_metadata_create(ctxt, 'fake2', 'key3', 'value3')
        db.volume_glance_metadata_create(ctxt, 'fake2', 'key4', 'value4')
        volume_api = cinder.volume.api.API()
        results = volume_api.get_list_volumes_image_metadata(ctxt, ['fake1',
                                                                    'fake2'])
        expect_results = {'fake1': {'key1': 'value1', 'key2': 'value2'},
                          'fake2': {'key3': 'value3', 'key4': 'value4'}}
        self.assertEqual(expect_results, results)

    @mock.patch.object(QUOTAS, 'limit_check')
    @mock.patch.object(QUOTAS, 'reserve')
    def test_extend_attached_volume(self, reserve, limit_check):
        volume = self._create_volume(self.context, size=2,
                                     status='available', host=CONF.host)
        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.InvalidVolume,
                          volume_api._extend,
                          self.context,
                          volume, 3, attached=True)

        db.volume_update(self.context, volume.id, {'status': 'in-use'})
        volume.refresh()
        reserve.return_value = ["RESERVATION"]
        volume_api._extend(self.context, volume, 3, attached=True)
        volume.refresh()
        self.assertEqual('extending', volume.status)
        self.assertEqual('in-use', volume.previous_status)
        reserve.assert_called_once_with(self.context, gigabytes=1,
                                        gigabytes___DEFAULT__=1,
                                        project_id=volume.project_id)
        limit_check.side_effect = None
        reserve.side_effect = None
        db.volume_update(self.context, volume.id, {'status': 'in-use'})
        volume_api.scheduler_rpcapi = mock.MagicMock()
        volume_api.scheduler_rpcapi.extend_volume = mock.MagicMock()
        volume_api._extend(self.context, volume, 3, attached=True)

        request_spec = {
            'volume_properties': volume,
            'volume_type': self.vol_type,
            'volume_id': volume.id
        }
        volume_api.scheduler_rpcapi.extend_volume.assert_called_once_with(
            self.context, volume, 3, ["RESERVATION"], request_spec)
        # clean up
        self.volume.delete_volume(self.context, volume)

    @mock.patch.object(QUOTAS, 'limit_check')
    @mock.patch.object(QUOTAS, 'reserve')
    def test_extend_volume(self, reserve, limit_check):
        """Test volume can be extended at API level."""
        # create a volume and assign to host
        volume = self._create_volume(self.context, size=2,
                                     status='in-use', host=CONF.host)
        volume_api = cinder.volume.api.API()

        # Extend fails when status != available
        self.assertRaises(exception.InvalidVolume,
                          volume_api._extend,
                          self.context,
                          volume,
                          3)

        db.volume_update(self.context, volume.id, {'status': 'available'})
        volume.refresh()
        # Extend fails when new_size < orig_size
        self.assertRaises(exception.InvalidInput,
                          volume_api._extend,
                          self.context,
                          volume,
                          1)

        # Extend fails when new_size == orig_size
        self.assertRaises(exception.InvalidInput,
                          volume_api._extend,
                          self.context,
                          volume,
                          2)

        # works when new_size > orig_size
        reserve.return_value = ["RESERVATION"]
        volume_api._extend(self.context, volume, 3)
        volume.refresh()
        self.assertEqual('extending', volume.status)
        self.assertEqual('available', volume.previous_status)
        reserve.assert_called_once_with(self.context, gigabytes=1,
                                        gigabytes___DEFAULT__=1,
                                        project_id=volume.project_id)

        # Test the quota exceeded
        db.volume_update(self.context, volume.id, {'status': 'available'})
        reserve.side_effect = exception.OverQuota(overs=['gigabytes'],
                                                  quotas={'gigabytes': 20},
                                                  usages={'gigabytes':
                                                          {'reserved': 5,
                                                           'in_use': 15}})
        self.assertRaises(exception.VolumeSizeExceedsAvailableQuota,
                          volume_api._extend, self.context,
                          volume, 3)
        db.volume_update(self.context, volume.id, {'status': 'available'})

        limit_check.side_effect = exception.OverQuota(
            overs=['per_volume_gigabytes'], quotas={'per_volume_gigabytes': 2})
        self.assertRaises(exception.VolumeSizeExceedsLimit,
                          volume_api._extend, self.context,
                          volume, 3)

        # Test scheduler path
        limit_check.side_effect = None
        reserve.side_effect = None
        db.volume_update(self.context, volume.id, {'status': 'available'})
        volume_api.scheduler_rpcapi = mock.MagicMock()
        volume_api.scheduler_rpcapi.extend_volume = mock.MagicMock()

        volume_api._extend(self.context, volume, 3)

        request_spec = {
            'volume_properties': volume,
            'volume_type': self.vol_type,
            'volume_id': volume.id
        }
        volume_api.scheduler_rpcapi.extend_volume.assert_called_once_with(
            self.context, volume, 3, ["RESERVATION"], request_spec)

        # clean up
        self.volume.delete_volume(self.context, volume)

    @mock.patch.object(QUOTAS, 'limit_check')
    @mock.patch.object(QUOTAS, 'reserve')
    def test_extend_volume_with_volume_type_limit(self, reserve, limit_check):
        """Test volume can be extended at API level."""
        volume_api = cinder.volume.api.API()
        volume = tests_utils.create_volume(
            self.context, size=2,
            volume_type_id=self.sized_vol_type['id'])

        volume_api.scheduler_rpcapi = mock.MagicMock()
        volume_api.scheduler_rpcapi.extend_volume = mock.MagicMock()

        volume_api._extend(self.context, volume, 3)

        self.assertRaises(exception.InvalidInput,
                          volume_api._extend,
                          self.context,
                          volume,
                          5)

    def test_extend_volume_driver_not_initialized(self):
        """Test volume can be extended at API level."""
        # create a volume and assign to host
        fake_reservations = ['RESERVATION']
        volume = tests_utils.create_volume(self.context, size=2,
                                           status='available',
                                           host=CONF.host)
        self.volume.create_volume(self.context, volume)

        self.volume.driver._initialized = False

        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.extend_volume,
                          self.context, volume, 3,
                          fake_reservations)

        volume.refresh()
        self.assertEqual('error_extending', volume.status)

        # lets cleanup the mess.
        self.volume.driver._initialized = True
        self.volume.delete_volume(self.context, volume)

    def _test_extend_volume_manager_fails_with_exception(self, volume):
        fake_reservations = ['RESERVATION']

        # Test driver exception
        with mock.patch.object(
                self.volume.driver, 'extend_volume',
                side_effect=exception.CinderException('fake exception')):
            with mock.patch.object(
                    self.volume.message_api, 'create') as mock_create:
                volume['status'] = 'extending'
                self.volume.extend_volume(self.context, volume, '4',
                                          fake_reservations)
                volume.refresh()
                self.assertEqual(2, volume.size)
                self.assertEqual('error_extending', volume.status)
                mock_create.assert_called_once_with(
                    self.context,
                    message_field.Action.EXTEND_VOLUME,
                    resource_uuid=volume.id,
                    detail=message_field.Detail.DRIVER_FAILED_EXTEND)

    @mock.patch('cinder.compute.API')
    def _test_extend_volume_manager_successful(self, volume, nova_api):
        """Test volume can be extended at the manager level."""
        def fake_extend(volume, new_size):
            volume['size'] = new_size

        nova_extend_volume = nova_api.return_value.extend_volume
        fake_reservations = ['RESERVATION']
        orig_status = volume.status

        # Test driver success
        with mock.patch.object(self.volume.driver,
                               'extend_volume') as extend_volume:
            with mock.patch.object(QUOTAS, 'commit') as quotas_commit:
                extend_volume.return_value = fake_extend
                volume.status = 'extending'
                self.volume.extend_volume(self.context, volume, '4',
                                          fake_reservations)
                volume.refresh()
                self.assertEqual(4, volume.size)
                self.assertEqual(orig_status, volume.status)
                quotas_commit.assert_called_with(
                    self.context,
                    ['RESERVATION'],
                    project_id=volume.project_id)
                if orig_status == 'in-use':
                    instance_uuids = [
                        attachment.instance_uuid
                        for attachment in volume.volume_attachment]
                    nova_extend_volume.assert_called_with(
                        self.context, instance_uuids, volume.id)

    def test_extend_volume_manager_available_fails_with_exception(self):
        volume = tests_utils.create_volume(self.context, size=2,
                                           status='creating', host=CONF.host)
        self.volume.create_volume(self.context, volume)
        self._test_extend_volume_manager_fails_with_exception(volume)
        self.volume.delete_volume(self.context, volume)

    def test_extend_volume_manager_available_successful(self):
        volume = tests_utils.create_volume(self.context, size=2,
                                           status='creating', host=CONF.host)
        self.volume.create_volume(self.context, volume)
        self._test_extend_volume_manager_successful(volume)
        self.volume.delete_volume(self.context, volume)

    def test_extend_volume_manager_in_use_fails_with_exception(self):
        volume = tests_utils.create_volume(self.context, size=2,
                                           status='creating', host=CONF.host)
        self.volume.create_volume(self.context, volume)
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        attachment = db.volume_attach(self.context,
                                      {'volume_id': volume.id,
                                       'attached_host': 'fake-host'})
        db.volume_attached(self.context, attachment.id, instance_uuid,
                           'fake-host', 'vdb')
        volume.refresh()
        self._test_extend_volume_manager_fails_with_exception(volume)
        self.volume.detach_volume(self.context, volume.id, attachment.id)
        self.volume.delete_volume(self.context, volume)

    def test_extend_volume_manager_in_use_successful(self):
        volume = tests_utils.create_volume(self.context, size=2,
                                           status='creating', host=CONF.host)
        self.volume.create_volume(self.context, volume)
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        attachment = db.volume_attach(self.context,
                                      {'volume_id': volume.id,
                                       'attached_host': 'fake-host'})
        db.volume_attached(self.context, attachment.id, instance_uuid,
                           'fake-host', 'vdb')
        volume.refresh()
        self._test_extend_volume_manager_successful(volume)
        self.volume.detach_volume(self.context, volume.id, attachment.id)
        self.volume.delete_volume(self.context, volume)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.extend_volume')
    def test_extend_volume_with_volume_type(self, mock_rpc_extend):
        elevated = context.get_admin_context()
        project_id = self.context.project_id
        db.volume_type_create(elevated, {'name': 'type', 'extra_specs': {}})
        vol_type = db.volume_type_get_by_name(elevated, 'type')

        volume_api = cinder.volume.api.API()
        volume = volume_api.create(self.context, 100, 'name', 'description',
                                   volume_type=vol_type)
        try:
            usage = db.quota_usage_get(elevated, project_id, 'gigabytes_type')
            volumes_in_use = usage.in_use
        except exception.QuotaUsageNotFound:
            volumes_in_use = 0
        self.assertEqual(100, volumes_in_use)
        db.volume_update(self.context, volume.id, {'status': 'available'})

        volume_api._extend(self.context, volume, 200)
        mock_rpc_extend.called_once_with(self.context, volume, 200, mock.ANY)

        try:
            usage = db.quota_usage_get(elevated, project_id, 'gigabytes_type')
            volumes_reserved = usage.reserved
        except exception.QuotaUsageNotFound:
            volumes_reserved = 0

        self.assertEqual(100, volumes_reserved)

    def test_create_volume_from_sourcevol(self):
        """Test volume can be created from a source volume."""
        def fake_create_cloned_volume(volume, src_vref):
            pass

        self.mock_object(self.volume.driver, 'create_cloned_volume',
                         fake_create_cloned_volume)
        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src)
        volume_dst = tests_utils.create_volume(self.context,
                                               source_volid=volume_src['id'],
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_dst)
        volume_dst.refresh()
        self.assertEqual('available', volume_dst.status)
        self.volume.delete_volume(self.context, volume_dst)
        self.volume.delete_volume(self.context, volume_src)

    def test_create_volume_from_sourcevol_fail_bad_size(self):
        """Test cannot clone volume with bad volume size."""
        volume_src = tests_utils.create_volume(self.context,
                                               size=3,
                                               status='available',
                                               host=CONF.host)

        self.assertRaises(exception.InvalidInput,
                          self.volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          source_volume=volume_src)

    @mock.patch('cinder.volume.api.API.list_availability_zones',
                return_value=({'name': 'nova', 'available': True},
                              {'name': 'az2', 'available': True}))
    def test_create_volume_from_sourcevol_fail_wrong_az(self, _mock_laz):
        """Test volume can't be cloned from an other volume in different az."""
        volume_api = cinder.volume.api.API()

        volume_src = self._create_volume(self.context,
                                         availability_zone='az2',
                                         **self.volume_params)
        self.volume.create_volume(self.context, volume_src)

        volume_src = db.volume_get(self.context, volume_src['id'])

        volume_dst = volume_api.create(self.context,
                                       size=1,
                                       name='fake_name',
                                       description='fake_desc',
                                       source_volume=volume_src,
                                       volume_type=
                                       objects.VolumeType.get_by_name_or_id(
                                           self.context,
                                           self.vol_type['id']))
        self.assertEqual('az2', volume_dst['availability_zone'])

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          source_volume=volume_src,
                          availability_zone='nova')

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_create_volume_from_sourcevol_with_glance_metadata(
            self, mock_qemu_info):
        """Test glance metadata can be correctly copied to new volume."""
        def fake_create_cloned_volume(volume, src_vref):
            pass

        self.mock_object(self.volume.driver, 'create_cloned_volume',
                         fake_create_cloned_volume)
        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        volume_src = self._create_volume_from_image()
        self.volume.create_volume(self.context, volume_src)
        volume_dst = tests_utils.create_volume(self.context,
                                               source_volid=volume_src['id'],
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_dst)
        self.assertEqual('available',
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).status)

        # TODO: review all tests in this file to make sure they are
        # using the defined db.api to access stuff rather than taking
        # shortcuts like the following (see LP Bug #1860817):
        # src_glancemeta = db.volume_get(context.get_admin_context(),
        #     volume_src['id']).volume_glance_metadata

        src_glancemeta = db.volume_glance_metadata_get(
            context.get_admin_context(), volume_src['id'])
        dst_glancemeta = db.volume_glance_metadata_get(
            context.get_admin_context(), volume_dst['id'])
        for meta_src in src_glancemeta:
            for meta_dst in dst_glancemeta:
                if meta_dst.key == meta_src.key:
                    self.assertEqual(meta_src.value, meta_dst.value)
        self.volume.delete_volume(self.context, volume_src)
        self.volume.delete_volume(self.context, volume_dst)

    def test_create_volume_from_sourcevol_failed_clone(self):
        """Test src vol status will be restore by error handling code."""
        def fake_error_create_cloned_volume(volume, src_vref):
            db.volume_update(self.context, src_vref['id'], {'status': 'error'})
            raise exception.CinderException('fake exception')

        self.mock_object(self.volume.driver, 'create_cloned_volume',
                         fake_error_create_cloned_volume)
        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.assertEqual('creating', volume_src.status)
        self.volume.create_volume(self.context, volume_src)
        self.assertEqual('available', volume_src.status)
        volume_dst = tests_utils.create_volume(self.context,
                                               source_volid=volume_src['id'],
                                               **self.volume_params)
        self.assertEqual('creating', volume_dst.status)
        self.assertRaises(exception.CinderException,
                          self.volume.create_volume,
                          self.context,
                          volume_dst)
        # Source volume's status is still available and dst is set to error
        self.assertEqual('available', volume_src.status)
        self.assertEqual('error', volume_dst.status)
        self.volume.delete_volume(self.context, volume_dst)
        self.volume.delete_volume(self.context, volume_src)

    def test_clean_temporary_volume(self):
        def fake_delete_volume(ctxt, volume):
            volume.destroy()

        fake_volume = tests_utils.create_volume(self.context, size=1,
                                                host=CONF.host,
                                                migration_status='migrating')
        fake_new_volume = tests_utils.create_volume(self.context, size=1,
                                                    host=CONF.host)
        # 1. Only clean the db
        self.volume._clean_temporary_volume(self.context, fake_volume,
                                            fake_new_volume,
                                            clean_db_only=True)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get, self.context,
                          fake_new_volume.id)

        # 2. Delete the backend storage
        fake_new_volume = tests_utils.create_volume(self.context, size=1,
                                                    host=CONF.host)
        with mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume') as \
                mock_delete_volume:
            mock_delete_volume.side_effect = fake_delete_volume
            self.volume._clean_temporary_volume(self.context,
                                                fake_volume,
                                                fake_new_volume,
                                                clean_db_only=False)
            self.assertRaises(exception.VolumeNotFound,
                              db.volume_get, self.context,
                              fake_new_volume.id)

        # Check when the migrated volume is not in migration
        fake_new_volume = tests_utils.create_volume(self.context, size=1,
                                                    host=CONF.host)
        fake_volume.migration_status = 'non-migrating'
        fake_volume.save()
        self.volume._clean_temporary_volume(self.context, fake_volume,
                                            fake_new_volume)
        volume = db.volume_get(context.get_admin_context(),
                               fake_new_volume.id)
        self.assertIsNone(volume.migration_status)

    def test_check_volume_filters_true(self):
        """Test bootable as filter for true"""
        volume_api = cinder.volume.api.API()
        filters = {'bootable': 'TRUE'}

        # To convert filter value to True or False
        volume_api.check_volume_filters(filters)

        # Confirming converted filter value against True
        self.assertTrue(filters['bootable'])

    def test_check_volume_filters_false(self):
        """Test bootable as filter for false"""
        volume_api = cinder.volume.api.API()
        filters = {'bootable': 'false'}

        # To convert filter value to True or False
        volume_api.check_volume_filters(filters)

        # Confirming converted filter value against False
        self.assertEqual(False, filters['bootable'])

    def test_check_volume_filters_invalid(self):
        """Test bootable as filter"""
        volume_api = cinder.volume.api.API()
        filters = {'bootable': 'invalid'}

        # To convert filter value to True or False
        volume_api.check_volume_filters(filters)

        # Confirming converted filter value against invalid value
        self.assertTrue(filters['bootable'])

    def test_update_volume_readonly_flag(self):
        """Test volume readonly flag can be updated at API level."""
        # create a volume and assign to host
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        self.volume.create_volume(self.context, volume)
        volume.status = 'in-use'

        def sort_func(obj):
            return obj['name']

        volume_api = cinder.volume.api.API()

        # Update fails when status != available
        self.assertRaises(exception.InvalidVolume,
                          volume_api.update_readonly_flag,
                          self.context,
                          volume,
                          False)

        volume.status = 'available'

        # works when volume in 'available' status
        volume_api.update_readonly_flag(self.context, volume, False)

        volume.refresh()
        self.assertEqual('available', volume.status)
        admin_metadata = volume.volume_admin_metadata
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('False', admin_metadata[0]['value'])

        # clean up
        self.volume.delete_volume(self.context, volume)

    def test_secure_file_operations_enabled(self):
        """Test secure file operations setting for base driver.

        General, non network file system based drivers do not have
        anything to do with "secure_file_operations". This test verifies that
        calling the method always returns False.
        """
        ret_flag = self.volume.driver.secure_file_operations_enabled()
        self.assertFalse(ret_flag)

    @mock.patch.object(driver.BaseVD, 'secure_file_operations_enabled')
    def test_secure_file_operations_enabled_2(self, mock_secure):
        mock_secure.return_value = True
        vol = tests_utils.create_volume(self.context)
        result = self.volume.secure_file_operations_enabled(self.context,
                                                            vol)
        mock_secure.assert_called_once_with()
        self.assertTrue(result)

    @mock.patch('cinder.volume.flows.common.make_pretty_name',
                new=mock.MagicMock())
    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.create_volume',
                return_value=None)
    @mock.patch('cinder.volume.flows.manager.create_volume.'
                'CreateVolumeFromSpecTask.execute',
                side_effect=exception.DriverNotInitialized())
    def test_create_volume_raise_rescheduled_exception(self, mock_execute,
                                                       mock_reschedule):
        # Create source volume
        test_vol = tests_utils.create_volume(self.context,
                                             **self.volume_params)
        test_vol_id = test_vol['id']
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.create_volume,
                          self.context, test_vol,
                          {'volume_properties': self.volume_params},
                          {'retry': {'num_attempts': 1, 'host': []}})
        self.assertTrue(mock_reschedule.called)
        volume = db.volume_get(context.get_admin_context(), test_vol_id)
        self.assertEqual('creating', volume['status'])
        # We increase the stats on entering the create method, but we must
        # have cleared them on reschedule.
        self.assertEqual({'_pool0': {'allocated_capacity_gb': 0}},
                         self.volume.stats['pools'])

    @mock.patch('cinder.volume.flows.manager.create_volume.'
                'CreateVolumeFromSpecTask.execute')
    def test_create_volume_raise_unrescheduled_exception(self, mock_execute):
        # create source volume
        test_vol = tests_utils.create_volume(self.context,
                                             **self.volume_params)
        test_vol_id = test_vol['id']
        mock_execute.side_effect = exception.VolumeNotFound(
            volume_id=test_vol_id)
        self.assertRaises(exception.VolumeNotFound,
                          self.volume.create_volume,
                          self.context, test_vol,
                          {'volume_properties': self.volume_params,
                           'source_volid': fake.VOLUME_ID},
                          {'retry': {'num_attempts': 1, 'host': []}})
        volume = db.volume_get(context.get_admin_context(), test_vol_id)
        self.assertEqual('error', volume['status'])
        self.assertEqual({'_pool0': {'allocated_capacity_gb': 1}},
                         self.volume.stats['pools'])

    @mock.patch('cinder.utils.api_clean_volume_file_locks')
    def test_cascade_delete_volume_with_snapshots(self, mock_api_clean):
        """Test volume deletion with dependent snapshots."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume)
        snapshot = create_snapshot(volume['id'], size=volume['size'])
        self.volume.create_snapshot(self.context, snapshot)
        self.assertEqual(
            snapshot.id, objects.Snapshot.get_by_id(self.context,
                                                    snapshot.id).id)

        volume['status'] = 'available'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        volume_api.delete(self.context,
                          volume,
                          cascade=True)
        mock_api_clean.assert_called_once_with(volume.id)

    @mock.patch('cinder.utils.api_clean_volume_file_locks')
    def test_cascade_delete_volume_with_snapshots_error(self, mock_api_clean):
        """Test volume deletion with dependent snapshots."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume)
        snapshot = create_snapshot(volume['id'], size=volume['size'])
        self.volume.create_snapshot(self.context, snapshot)
        self.assertEqual(
            snapshot.id, objects.Snapshot.get_by_id(self.context,
                                                    snapshot.id).id)

        snapshot.update({'status': fields.SnapshotStatus.CREATING})
        snapshot.save()

        volume['status'] = 'available'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete,
                          self.context,
                          volume,
                          cascade=True)
        mock_api_clean.assert_not_called()

    @mock.patch('cinder.utils.api_clean_volume_file_locks')
    def test_cascade_force_delete_volume_with_snapshots_error(self,
                                                              mock_api_clean):
        """Test volume force deletion with errored dependent snapshots."""
        volume = tests_utils.create_volume(self.context,
                                           host='fakehost')

        snapshot = create_snapshot(volume.id,
                                   size=volume.size,
                                   status=fields.SnapshotStatus.ERROR_DELETING)
        self.volume.create_snapshot(self.context, snapshot)

        volume_api = cinder.volume.api.API()

        volume_api.delete(self.context, volume, cascade=True, force=True)

        snapshot = objects.Snapshot.get_by_id(self.context, snapshot.id)
        self.assertEqual('deleting', snapshot.status)

        volume = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual('deleting', volume.status)
        mock_api_clean.assert_called_once_with(volume.id)

    def test_cascade_delete_volume_with_snapshots_in_other_project(self):
        """Test volume deletion with dependent snapshots in other project."""
        volume = tests_utils.create_volume(self.user_context,
                                           **self.volume_params)
        snapshot = create_snapshot(volume['id'], size=volume['size'],
                                   project_id=fake.PROJECT2_ID)
        self.volume.create_snapshot(self.context, snapshot)
        self.assertEqual(
            snapshot.id, objects.Snapshot.get_by_id(self.context,
                                                    snapshot.id).id)

        volume['status'] = 'available'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete,
                          self.user_context,
                          volume,
                          cascade=True)

    @mock.patch.object(driver.BaseVD, 'get_backup_device')
    @mock.patch.object(driver.BaseVD, 'secure_file_operations_enabled')
    def test_get_backup_device(self, mock_secure, mock_get_backup):
        vol = tests_utils.create_volume(self.context)
        backup = tests_utils.create_backup(self.context, vol['id'])
        mock_secure.return_value = False
        mock_get_backup.return_value = (vol, False)
        result = self.volume.get_backup_device(self.context,
                                               backup)

        mock_get_backup.assert_called_once_with(self.context, backup)
        mock_secure.assert_called_once_with()
        expected_result = {'backup_device': vol, 'secure_enabled': False,
                           'is_snapshot': False}
        self.assertEqual(expected_result, result)

    @mock.patch.object(driver.BaseVD, 'get_backup_device')
    @mock.patch.object(driver.BaseVD, 'secure_file_operations_enabled')
    def test_get_backup_device_want_objects(self, mock_secure,
                                            mock_get_backup):
        vol = tests_utils.create_volume(self.context)
        backup = tests_utils.create_backup(self.context, vol['id'])
        mock_secure.return_value = False
        mock_get_backup.return_value = (vol, False)
        result = self.volume.get_backup_device(self.context,
                                               backup, want_objects=True)

        mock_get_backup.assert_called_once_with(self.context, backup)
        mock_secure.assert_called_once_with()
        expected_result = objects.BackupDeviceInfo.from_primitive(
            {'backup_device': vol, 'secure_enabled': False,
             'is_snapshot': False},
            self.context)
        self.assertEqual(expected_result, result)

    @mock.patch('cinder.tests.fake_driver.FakeLoggingVolumeDriver.'
                'SUPPORTS_ACTIVE_ACTIVE', True)
    def test_set_resource_host_different(self):
        manager = vol_manager.VolumeManager(host='localhost-1@ceph',
                                            cluster='mycluster@ceph')
        volume = tests_utils.create_volume(self.user_context,
                                           host='localhost-2@ceph#ceph',
                                           cluster_name='mycluster@ceph')
        manager._set_resource_host(volume)
        volume.refresh()
        self.assertEqual('localhost-1@ceph#ceph', volume.host)

    @mock.patch('cinder.tests.fake_driver.FakeLoggingVolumeDriver.'
                'SUPPORTS_ACTIVE_ACTIVE', True)
    def test_set_resource_host_equal(self):
        manager = vol_manager.VolumeManager(host='localhost-1@ceph',
                                            cluster='mycluster@ceph')
        volume = tests_utils.create_volume(self.user_context,
                                           host='localhost-1@ceph#ceph',
                                           cluster_name='mycluster@ceph')
        with mock.patch.object(volume, 'save') as save_mock:
            manager._set_resource_host(volume)
            save_mock.assert_not_called()

    def test_volume_attach_attaching(self):
        """Test volume_attach."""

        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        attachment = db.volume_attach(self.context,
                                      {'volume_id': volume['id'],
                                       'attached_host': 'fake-host'})
        db.volume_attached(self.context, attachment['id'], instance_uuid,
                           'fake-host', 'vdb', mark_attached=False)
        volume_api = cinder.volume.api.API()
        volume = volume_api.get(self.context, volume['id'])
        self.assertEqual("attaching", volume['status'])
        self.assertEqual("attaching", volume['attach_status'])

    def test__append_volume_stats_with_pools(self):
        manager = vol_manager.VolumeManager()
        manager.stats = {'pools': {'pool1': {'allocated_capacity_gb': 20},
                                   'pool2': {'allocated_capacity_gb': 10}}}
        vol_stats = {'vendor_name': 'Open Source', 'pools': [
            {'pool_name': 'pool1', 'provisioned_capacity_gb': 31},
            {'pool_name': 'pool2', 'provisioned_capacity_gb': 21}]}
        manager._append_volume_stats(vol_stats)

        expected = {'vendor_name': 'Open Source', 'pools': [
            {'pool_name': 'pool1', 'provisioned_capacity_gb': 31,
             'allocated_capacity_gb': 20},
            {'pool_name': 'pool2', 'provisioned_capacity_gb': 21,
             'allocated_capacity_gb': 10}]}
        self.assertDictEqual(expected, vol_stats)

    def test__append_volume_stats_no_pools(self):
        manager = vol_manager.VolumeManager()
        manager.stats = {'pools': {'backend': {'allocated_capacity_gb': 20}}}
        vol_stats = {'provisioned_capacity_gb': 30}
        manager._append_volume_stats(vol_stats)

        expected = {'provisioned_capacity_gb': 30, 'allocated_capacity_gb': 20}
        self.assertDictEqual(expected, vol_stats)

    def test__append_volume_stats_no_pools_no_volumes(self):
        manager = vol_manager.VolumeManager()
        # This is what gets set on c-vol manager's init_host method
        manager.stats = {'pools': {}, 'allocated_capacity_gb': 0}
        vol_stats = {'provisioned_capacity_gb': 30}

        manager._append_volume_stats(vol_stats)

        expected = {'provisioned_capacity_gb': 30, 'allocated_capacity_gb': 0}
        self.assertDictEqual(expected, vol_stats)

    def test__append_volume_stats_driver_error(self):
        manager = vol_manager.VolumeManager()
        self.assertRaises(exception.ProgrammingError,
                          manager._append_volume_stats, {'pools': 'bad_data'})

    def test_default_tpool_size(self):
        self.skipTest("Bug 1811663")
        """Test we can set custom tpool size."""
        eventlet.tpool._nthreads = 10
        self.assertListEqual([], eventlet.tpool._threads)

        vol_manager.VolumeManager()

        self.assertEqual(20, eventlet.tpool._nthreads)
        self.assertListEqual([], eventlet.tpool._threads)

    def test_tpool_size(self):
        self.skipTest("Bug 1811663")
        """Test we can set custom tpool size."""
        self.assertNotEqual(100, eventlet.tpool._nthreads)
        self.assertListEqual([], eventlet.tpool._threads)

        self.override_config('backend_native_threads_pool_size', 100,
                             group='backend_defaults')
        vol_manager.VolumeManager()

        self.assertEqual(100, eventlet.tpool._nthreads)
        self.assertListEqual([], eventlet.tpool._threads)
        eventlet.tpool._nthreads = 20


class VolumeTestCaseLocks(base.BaseVolumeTestCase):
    MOCK_TOOZ = False

    def test_create_volume_from_volume_delete_lock_taken(self):
        # create source volume
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        # no lock
        self.volume.create_volume(self.context, src_vol)

        dst_vol = tests_utils.create_volume(self.context,
                                            source_volid=src_vol_id,
                                            **self.volume_params)

        orig_elevated = self.context.elevated

        gthreads = []

        def mock_elevated(*args, **kwargs):
            # unset mock so it is only called once
            self.mock_object(self.context, 'elevated', orig_elevated)

            # we expect this to block and then fail
            t = eventlet.spawn(self.volume.create_volume,
                               self.context,
                               volume=dst_vol,
                               request_spec={'source_volid': src_vol_id})
            gthreads.append(t)

            return orig_elevated(*args, **kwargs)

        # mock something from early on in the delete operation and within the
        # lock so that when we do the create we expect it to block.
        self.mock_object(self.context, 'elevated', mock_elevated)

        # locked
        self.volume.delete_volume(self.context, src_vol)

        # we expect the volume create to fail with the following err since the
        # source volume was deleted while the create was locked. Note that the
        # volume is still in the db since it was created by the test prior to
        # calling manager.create_volume.
        with mock.patch('sys.stderr', new=io.StringIO()):
            self.assertRaises(exception.VolumeNotFound, gthreads[0].wait)

    def test_create_volume_from_snapshot_delete_lock_taken(self):
        # create source volume
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)

        # no lock
        self.volume.create_volume(self.context, src_vol)

        # create snapshot
        snap_id = create_snapshot(src_vol.id,
                                  size=src_vol['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snap_id)
        # no lock
        self.volume.create_snapshot(self.context, snapshot_obj)

        # create vol from snapshot...
        dst_vol = tests_utils.create_volume(self.context,
                                            snapshot_id=snap_id,
                                            source_volid=src_vol.id,
                                            **self.volume_params)

        orig_elevated = self.context.elevated

        gthreads = []

        def mock_elevated(*args, **kwargs):
            # unset mock so it is only called once
            self.mock_object(self.context, 'elevated', orig_elevated)

            # We expect this to block and then fail
            t = eventlet.spawn(self.volume.create_volume, self.context,
                               volume=dst_vol,
                               request_spec={'snapshot_id': snap_id})
            gthreads.append(t)

            return orig_elevated(*args, **kwargs)

        # mock something from early on in the delete operation and within the
        # lock so that when we do the create we expect it to block.
        self.mock_object(self.context, 'elevated', mock_elevated)

        # locked
        self.volume.delete_snapshot(self.context, snapshot_obj)

        # we expect the volume create to fail with the following err since the
        # snapshot was deleted while the create was locked. Note that the
        # volume is still in the db since it was created by the test prior to
        #  calling manager.create_volume.
        with mock.patch('sys.stderr', new=io.StringIO()):
            self.assertRaises(exception.SnapshotNotFound, gthreads[0].wait)
        # locked
        self.volume.delete_volume(self.context, src_vol)
        # make sure it is gone
        self.assertRaises(exception.VolumeNotFound, db.volume_get,
                          self.context, src_vol.id)
