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
import os
import shutil
import socket
import sys
import tempfile
import time

import enum
import eventlet
import mock
from mox3 import mox
import os_brick
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import importutils
from oslo_utils import timeutils
from oslo_utils import units
import six
from stevedore import extension
from taskflow.engines.action_engine import engine

from cinder.api import common
from cinder.brick.local_dev import lvm as brick_lvm
from cinder import context
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder import keymgr
from cinder import objects
import cinder.policy
from cinder import quota
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.brick import fake_lvm
from cinder.tests.unit import conf_fixture
from cinder.tests.unit import fake_driver
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit.keymgr import fake as fake_keymgr
from cinder.tests.unit import utils as tests_utils
from cinder import utils
import cinder.volume
from cinder.volume import configuration as conf
from cinder.volume import driver
from cinder.volume.drivers import lvm
from cinder.volume import manager as vol_manager
from cinder.volume import rpcapi as volume_rpcapi
import cinder.volume.targets.tgt
from cinder.volume import utils as volutils
from cinder.volume import volume_types


QUOTAS = quota.QUOTAS
CGQUOTAS = quota.CGQUOTAS

CONF = cfg.CONF

ENCRYPTION_PROVIDER = 'nova.volume.encryptors.cryptsetup.CryptsetupEncryptor'

fake_opt = [
    cfg.StrOpt('fake_opt1', default='fake', help='fake opts')
]


class FakeImageService(object):
    def __init__(self, db_driver=None, image_service=None):
        pass

    def show(self, context, image_id):
        return {'size': 2 * units.Gi,
                'disk_format': 'raw',
                'container_format': 'bare',
                'status': 'active'}


class BaseVolumeTestCase(test.TestCase):
    """Test Case for volumes."""

    FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa'

    def setUp(self):
        super(BaseVolumeTestCase, self).setUp()
        self.extension_manager = extension.ExtensionManager(
            "BaseVolumeTestCase")
        vol_tmpdir = tempfile.mkdtemp()
        self.flags(volumes_dir=vol_tmpdir,
                   notification_driver=["test"])
        self.addCleanup(self._cleanup)
        self.volume = importutils.import_object(CONF.volume_manager)
        self.configuration = mock.Mock(conf.Configuration)
        self.context = context.get_admin_context()
        self.context.user_id = 'fake'
        # NOTE(mriedem): The id is hard-coded here for tracking race fail
        # assertions with the notification code, it's part of an
        # elastic-recheck query so don't remove it or change it.
        self.project_id = '7f265bd4-3a85-465e-a899-5dc4854a86d3'
        self.context.project_id = self.project_id
        self.volume_params = {
            'status': 'creating',
            'host': CONF.host,
            'size': 1}
        self.stubs.Set(brick_lvm.LVM,
                       'get_all_volume_groups',
                       self.fake_get_all_volume_groups)
        fake_image.stub_out_image_service(self.stubs)
        self.stubs.Set(brick_lvm.LVM, '_vg_exists', lambda x: True)
        self.stubs.Set(os.path, 'exists', lambda x: True)
        self.volume.driver.set_initialized()
        self.volume.stats = {'allocated_capacity_gb': 0,
                             'pools': {}}
        # keep ordered record of what we execute
        self.called = []

    def _cleanup(self):
        try:
            shutil.rmtree(CONF.volumes_dir)
        except OSError:
            pass

    def fake_get_all_volume_groups(obj, vg_name=None, no_suffix=True):
        return [{'name': 'cinder-volumes',
                 'size': '5.00',
                 'available': '2.50',
                 'lv_count': '2',
                 'uuid': 'vR1JU3-FAKE-C4A9-PQFh-Mctm-9FwA-Xwzc1m'}]


class AvailabilityZoneTestCase(BaseVolumeTestCase):
    def test_list_availability_zones_cached(self):
        volume_api = cinder.volume.api.API()
        with mock.patch.object(volume_api.db,
                               'service_get_all_by_topic') as get_all:
            get_all.return_value = [
                {
                    'availability_zone': 'a',
                    'disabled': False,
                },
            ]
            azs = volume_api.list_availability_zones(enable_cache=True)
            self.assertEqual([{"name": 'a', 'available': True}], list(azs))
            self.assertIsNotNone(volume_api.availability_zones_last_fetched)
            self.assertTrue(get_all.called)
            volume_api.list_availability_zones(enable_cache=True)
            self.assertEqual(1, get_all.call_count)

    def test_list_availability_zones_no_cached(self):
        volume_api = cinder.volume.api.API()
        with mock.patch.object(volume_api.db,
                               'service_get_all_by_topic') as get_all:
            get_all.return_value = [
                {
                    'availability_zone': 'a',
                    'disabled': False,
                },
            ]
            azs = volume_api.list_availability_zones(enable_cache=False)
            self.assertEqual([{"name": 'a', 'available': True}], list(azs))
            self.assertIsNone(volume_api.availability_zones_last_fetched)

        with mock.patch.object(volume_api.db,
                               'service_get_all_by_topic') as get_all:
            get_all.return_value = [
                {
                    'availability_zone': 'a',
                    'disabled': True,
                },
            ]
            azs = volume_api.list_availability_zones(enable_cache=False)
            self.assertEqual([{"name": 'a', 'available': False}], list(azs))
            self.assertIsNone(volume_api.availability_zones_last_fetched)

    def test_list_availability_zones_refetched(self):
        timeutils.set_time_override()
        volume_api = cinder.volume.api.API()
        with mock.patch.object(volume_api.db,
                               'service_get_all_by_topic') as get_all:
            get_all.return_value = [
                {
                    'availability_zone': 'a',
                    'disabled': False,
                },
            ]
            azs = volume_api.list_availability_zones(enable_cache=True)
            self.assertEqual([{"name": 'a', 'available': True}], list(azs))
            self.assertIsNotNone(volume_api.availability_zones_last_fetched)
            last_fetched = volume_api.availability_zones_last_fetched
            self.assertTrue(get_all.called)
            volume_api.list_availability_zones(enable_cache=True)
            self.assertEqual(1, get_all.call_count)

            # The default cache time is 3600, push past that...
            timeutils.advance_time_seconds(3800)
            get_all.return_value = [
                {
                    'availability_zone': 'a',
                    'disabled': False,
                },
                {
                    'availability_zone': 'b',
                    'disabled': False,
                },
            ]
            azs = volume_api.list_availability_zones(enable_cache=True)
            azs = sorted([n['name'] for n in azs])
            self.assertEqual(['a', 'b'], azs)
            self.assertEqual(2, get_all.call_count)
            self.assertGreater(volume_api.availability_zones_last_fetched,
                               last_fetched)

    def test_list_availability_zones_enabled_service(self):
        services = [
            {'availability_zone': 'ping', 'disabled': 0},
            {'availability_zone': 'ping', 'disabled': 1},
            {'availability_zone': 'pong', 'disabled': 0},
            {'availability_zone': 'pung', 'disabled': 1},
        ]

        def stub_service_get_all_by_topic(*args, **kwargs):
            return services

        self.stubs.Set(db, 'service_get_all_by_topic',
                       stub_service_get_all_by_topic)

        def sort_func(obj):
            return obj['name']

        volume_api = cinder.volume.api.API()
        azs = volume_api.list_availability_zones()
        azs = sorted(azs, key=sort_func)

        expected = sorted([
            {'name': 'pung', 'available': False},
            {'name': 'pong', 'available': True},
            {'name': 'ping', 'available': True},
        ], key=sort_func)

        self.assertEqual(expected, azs)


class VolumeTestCase(BaseVolumeTestCase):

    def setUp(self):
        super(VolumeTestCase, self).setUp()
        self._clear_patch = mock.patch('cinder.volume.utils.clear_volume',
                                       autospec=True)
        self._clear_patch.start()
        self.expected_status = 'available'

    def tearDown(self):
        super(VolumeTestCase, self).tearDown()
        self._clear_patch.stop()

    def test_init_host_clears_downloads(self):
        """Test that init_host will unwedge a volume stuck in downloading."""
        volume = tests_utils.create_volume(self.context, status='downloading',
                                           size=0, host=CONF.host)
        volume_id = volume['id']
        self.volume.init_host()
        volume = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual("error", volume['status'])
        self.volume.delete_volume(self.context, volume_id)

    def test_init_host_resumes_deletes(self):
        """init_host will resume deleting volume in deleting status."""
        volume = tests_utils.create_volume(self.context, status='deleting',
                                           size=0, host=CONF.host)
        volume_id = volume['id']
        self.volume.init_host()
        self.assertRaises(exception.VolumeNotFound, db.volume_get,
                          context.get_admin_context(), volume_id)

    def test_init_host_count_allocated_capacity(self):
        vol0 = tests_utils.create_volume(
            self.context, size=100, host=CONF.host)
        vol1 = tests_utils.create_volume(
            self.context, size=128,
            host=volutils.append_host(CONF.host, 'pool0'))
        vol2 = tests_utils.create_volume(
            self.context, size=256,
            host=volutils.append_host(CONF.host, 'pool0'))
        vol3 = tests_utils.create_volume(
            self.context, size=512,
            host=volutils.append_host(CONF.host, 'pool1'))
        vol4 = tests_utils.create_volume(
            self.context, size=1024,
            host=volutils.append_host(CONF.host, 'pool2'))
        self.volume.init_host()
        stats = self.volume.stats
        self.assertEqual(2020, stats['allocated_capacity_gb'])
        self.assertEqual(
            384, stats['pools']['pool0']['allocated_capacity_gb'])
        self.assertEqual(
            512, stats['pools']['pool1']['allocated_capacity_gb'])
        self.assertEqual(
            1024, stats['pools']['pool2']['allocated_capacity_gb'])

        # NOTE(jdg): On the create we have host='xyz', BUT
        # here we do a db.volume_get, and now the host has
        # been updated to xyz#pool-name.  Note this is
        # done via the managers init, which calls the drivers
        # get_pool method, which in the legacy case is going
        # to be volume_backend_name or None

        vol0 = db.volume_get(context.get_admin_context(), vol0['id'])
        self.assertEqual(volutils.append_host(CONF.host, 'LVM'),
                         vol0['host'])
        self.volume.delete_volume(self.context, vol0['id'])
        self.volume.delete_volume(self.context, vol1['id'])
        self.volume.delete_volume(self.context, vol2['id'])
        self.volume.delete_volume(self.context, vol3['id'])
        self.volume.delete_volume(self.context, vol4['id'])

    @mock.patch.object(vol_manager.VolumeManager, 'add_periodic_task')
    def test_init_host_repl_enabled_periodic_task(self, mock_add_p_task):
        manager = vol_manager.VolumeManager()
        with mock.patch.object(manager.driver,
                               'get_volume_stats') as m_get_stats:
            m_get_stats.return_value = {'replication': True}
            manager.init_host()
        mock_add_p_task.assert_called_once_with(mock.ANY)

    @mock.patch.object(vol_manager.VolumeManager, 'add_periodic_task')
    def test_init_host_repl_disabled_periodic_task(self, mock_add_p_task):
        manager = vol_manager.VolumeManager()
        with mock.patch.object(manager.driver,
                               'get_volume_stats') as m_get_stats:
            m_get_stats.return_value = {'replication': False}
            manager.init_host()
        self.assertEqual(0, mock_add_p_task.call_count)

    @mock.patch.object(vol_manager.VolumeManager,
                       'update_service_capabilities')
    def test_report_filter_goodness_function(self, mock_update):
        manager = vol_manager.VolumeManager()
        manager.driver.set_initialized()
        myfilterfunction = "myFilterFunction"
        mygoodnessfunction = "myGoodnessFunction"
        expected = {'name': 'cinder-volumes',
                    'filter_function': myfilterfunction,
                    'goodness_function': mygoodnessfunction,
                    }
        with mock.patch.object(manager.driver,
                               'get_volume_stats') as m_get_stats:
            with mock.patch.object(manager.driver,
                                   'get_goodness_function') as m_get_goodness:
                with mock.patch.object(manager.driver,
                                       'get_filter_function') as m_get_filter:
                    m_get_stats.return_value = {'name': 'cinder-volumes'}
                    m_get_filter.return_value = myfilterfunction
                    m_get_goodness.return_value = mygoodnessfunction
                    manager._report_driver_status(1)
                    self.assertTrue(m_get_stats.called)
                    mock_update.assert_called_once_with(expected)

    def test_is_working(self):
        # By default we have driver mocked to be initialized...
        self.assertTrue(self.volume.is_working())

        # ...lets switch it and check again!
        self.volume.driver._initialized = False
        self.assertFalse(self.volume.is_working())

    def test_create_volume_fails_with_creating_and_downloading_status(self):
        """Test init_host in case of volume.

        While the status of volume is 'creating' or 'downloading',
        volume process down.
        After process restarting this 'creating' status is changed to 'error'.
        """
        for status in ['creating', 'downloading']:
            volume = tests_utils.create_volume(self.context, status=status,
                                               size=0, host=CONF.host)

            volume_id = volume['id']
            self.volume.init_host()
            volume = db.volume_get(context.get_admin_context(), volume_id)
            self.assertEqual('error', volume['status'])
            self.volume.delete_volume(self.context, volume_id)

    def test_create_snapshot_fails_with_creating_status(self):
        """Test init_host in case of snapshot.

        While the status of snapshot is 'creating', volume process
        down. After process restarting this 'creating' status is
        changed to 'error'.
        """
        volume = tests_utils.create_volume(self.context,
                                           **self.volume_params)
        snapshot = tests_utils.create_snapshot(self.context,
                                               volume['id'],
                                               status='creating')
        snap_id = snapshot['id']
        self.volume.init_host()

        snapshot_obj = objects.Snapshot.get_by_id(self.context, snap_id)

        self.assertEqual('error', snapshot_obj.status)

        self.volume.delete_snapshot(self.context, snapshot_obj)
        self.volume.delete_volume(self.context, volume['id'])

    @mock.patch.object(QUOTAS, 'reserve')
    @mock.patch.object(QUOTAS, 'commit')
    @mock.patch.object(QUOTAS, 'rollback')
    def test_create_driver_not_initialized(self, reserve, commit, rollback):
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
        self.assertEqual(0, len(self.notifier.notifications),
                         self.notifier.notifications)
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.create_volume,
                          self.context, volume_id)

        volume = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual("error", volume.status)
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_create_driver_not_initialized_rescheduling(self):
        self.volume.driver._initialized = False

        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **self.volume_params)

        volume_id = volume['id']
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.create_volume,
                          self.context, volume_id,
                          {'volume_properties': self.volume_params},
                          {'retry': {'num_attempts': 1, 'host': []}})
        # NOTE(dulek): Volume should be rescheduled as we passed request_spec
        # and filter_properties, assert that it wasn't counted in
        # allocated_capacity tracking.
        self.assertEqual({}, self.volume.stats['pools'])

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
                              self.context, volume_id,
                              {'volume_properties': params},
                              {'retry': {'num_attempts': 1, 'host': []}})
        # NOTE(dulek): Volume should be rescheduled as we passed request_spec
        # and filter_properties, assert that it wasn't counted in
        # allocated_capacity tracking.
        self.assertEqual({}, self.volume.stats['pools'])

        db.volume_destroy(context.get_admin_context(), volume_id)

    @mock.patch.object(QUOTAS, 'rollback')
    @mock.patch.object(QUOTAS, 'commit')
    @mock.patch.object(QUOTAS, 'reserve')
    def test_delete_driver_not_initialized(self, reserve, commit, rollback):
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
        self.assertEqual(0, len(self.notifier.notifications),
                         self.notifier.notifications)
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.delete_volume,
                          self.context, volume_id)

        volume = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual("error_deleting", volume.status)
        db.volume_destroy(context.get_admin_context(), volume_id)

    @mock.patch('cinder.quota.QUOTAS.rollback', new=mock.Mock())
    @mock.patch('cinder.quota.QUOTAS.commit', new=mock.Mock())
    @mock.patch('cinder.quota.QUOTAS.reserve', return_value=['RESERVATION'])
    def test_create_delete_volume(self, _mock_reserve):
        """Test volume can be created and deleted."""
        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **self.volume_params)
        volume_id = volume['id']
        self.assertIsNone(volume['encryption_key_id'])
        self.assertEqual(0, len(self.notifier.notifications),
                         self.notifier.notifications)
        self.volume.create_volume(self.context, volume_id)
        self.assertEqual(2, len(self.notifier.notifications),
                         self.notifier.notifications)
        msg = self.notifier.notifications[0]
        self.assertEqual('volume.create.start', msg['event_type'])
        expected = {
            'status': 'creating',
            'host': socket.gethostname(),
            'display_name': 'test_volume',
            'availability_zone': 'nova',
            'tenant_id': self.context.project_id,
            'created_at': 'DONTCARE',
            'volume_id': volume_id,
            'volume_type': None,
            'snapshot_id': None,
            'user_id': 'fake',
            'launched_at': 'DONTCARE',
            'size': 1,
            'replication_status': 'disabled',
            'replication_extended_status': None,
            'replication_driver_data': None,
            'metadata': [],
            'volume_attachment': [],
        }
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[1]
        self.assertEqual('volume.create.end', msg['event_type'])
        expected['status'] = 'available'
        self.assertDictMatch(expected, msg['payload'])
        self.assertEqual(volume_id, db.volume_get(context.get_admin_context(),
                         volume_id).id)

        self.volume.delete_volume(self.context, volume_id)
        vol = db.volume_get(context.get_admin_context(read_deleted='yes'),
                            volume_id)
        self.assertEqual('deleted', vol['status'])
        self.assertEqual(4, len(self.notifier.notifications),
                         self.notifier.notifications)
        msg = self.notifier.notifications[2]
        self.assertEqual('volume.delete.start', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[3]
        self.assertEqual('volume.delete.end', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        self.assertRaises(exception.NotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_create_delete_volume_with_metadata(self):
        """Test volume can be created with metadata and deleted."""
        test_meta = {'fake_key': 'fake_value'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        result_meta = {
            volume.volume_metadata[0].key: volume.volume_metadata[0].value}
        self.assertEqual(test_meta, result_meta)

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.NotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_create_volume_with_invalid_metadata(self):
        """Test volume create with too much metadata fails."""
        volume_api = cinder.volume.api.API()
        test_meta = {'fake_key': 'fake_value' * 256}
        self.assertRaises(exception.InvalidVolumeMetadataSize,
                          volume_api.create,
                          self.context,
                          1,
                          'name',
                          'description',
                          None,
                          None,
                          None,
                          test_meta)

    def test_update_volume_metadata_with_metatype(self):
        """Test update volume metadata with different metadata type."""
        test_meta1 = {'fake_key1': 'fake_value1'}
        test_meta2 = {'fake_key1': 'fake_value2'}
        FAKE_METADATA_TYPE = enum.Enum('METADATA_TYPES', 'fake_type')
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        volume_api = cinder.volume.api.API()

        # update user metadata associated with the volume.
        result_meta = volume_api.update_volume_metadata(
            self.context,
            volume,
            test_meta2,
            False,
            common.METADATA_TYPES.user)
        self.assertEqual(test_meta2, result_meta)

        # create image metadata associated with the volume.
        result_meta = volume_api.update_volume_metadata(
            self.context,
            volume,
            test_meta1,
            False,
            common.METADATA_TYPES.image)
        self.assertEqual(test_meta1, result_meta)

        # update image metadata associated with the volume.
        result_meta = volume_api.update_volume_metadata(
            self.context,
            volume,
            test_meta2,
            False,
            common.METADATA_TYPES.image)
        self.assertEqual(test_meta2, result_meta)

        # update volume metadata with invalid metadta type.
        self.assertRaises(exception.InvalidMetadataType,
                          volume_api.update_volume_metadata,
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
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.update_volume_metadata,
                          self.context,
                          volume,
                          test_meta1,
                          False,
                          FAKE_METADATA_TYPE.fake_type)

    def test_delete_volume_metadata_with_metatype(self):
        """Test delete volume metadata with different metadata type."""
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        test_meta2 = {'fake_key1': 'fake_value1'}
        FAKE_METADATA_TYPE = enum.Enum('METADATA_TYPES', 'fake_type')
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        volume_api = cinder.volume.api.API()

        # delete user metadata associated with the volume.
        volume_api.delete_volume_metadata(
            self.context,
            volume,
            'fake_key2',
            common.METADATA_TYPES.user)

        self.assertEqual(test_meta2,
                         db.volume_metadata_get(self.context, volume_id))

        # create image metadata associated with the volume.
        result_meta = volume_api.update_volume_metadata(
            self.context,
            volume,
            test_meta1,
            False,
            common.METADATA_TYPES.image)

        self.assertEqual(test_meta1, result_meta)

        # delete image metadata associated with the volume.
        volume_api.delete_volume_metadata(
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
                          volume_api.delete_volume_metadata,
                          self.context,
                          volume,
                          'fake_key1',
                          FAKE_METADATA_TYPE.fake_type)

    def test_delete_volume_metadata_maintenance(self):
        """Test delete volume metadata in maintenance."""
        FAKE_METADATA_TYPE = enum.Enum('METADATA_TYPES', 'fake_type')
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete_volume_metadata,
                          self.context,
                          volume,
                          'fake_key1',
                          FAKE_METADATA_TYPE.fake_type)

    def test_volume_attach_in_maintenance(self):
        """Test attach the volume in maintenance."""
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.attach,
                          self.context,
                          volume, None, None, None, None)

    def test_volume_detach_in_maintenance(self):
        """Test detach the volume in maintenance."""
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.detach,
                          self.context,
                          volume, None)

    def test_initialize_connection_maintenance(self):
        """Test initialize connection in maintenance."""
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.initialize_connection,
                          self.context,
                          volume,
                          None)

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

    def test_copy_volume_to_image_maintenance(self):
        """Test copy volume to image in maintenance."""
        test_meta1 = {'fake_key1': 'fake_value1', 'fake_key2': 'fake_value2'}
        volume = tests_utils.create_volume(self.context, metadata=test_meta1,
                                           **self.volume_params)
        volume['status'] = 'maintenance'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.copy_volume_to_image,
                          self.context,
                          volume,
                          test_meta1,
                          force=True)

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
                                   'description')
        self.assertEqual('az2', volume['availability_zone'])

        self.override_config('default_availability_zone', 'default-az')
        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description')
        self.assertEqual('default-az', volume['availability_zone'])

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
                                   'description')
        self.assertIsNone(volume['volume_type_id'])
        self.assertIsNone(volume['encryption_key_id'])

        # Create default volume type
        vol_type = conf_fixture.def_vol_type
        db.volume_type_create(context.get_admin_context(),
                              {'name': vol_type, 'extra_specs': {}})

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

    @mock.patch.object(keymgr, 'API', fake_keymgr.fake_api)
    def test_create_volume_with_encrypted_volume_type(self):
        ctxt = context.get_admin_context()

        db.volume_type_create(ctxt,
                              {'id': '61298380-0c12-11e3-bfd6-4b48424183be',
                               'name': 'LUKS'})
        db.volume_type_encryption_create(
            ctxt,
            '61298380-0c12-11e3-bfd6-4b48424183be',
            {'control_location': 'front-end', 'provider': ENCRYPTION_PROVIDER})

        volume_api = cinder.volume.api.API()

        db_vol_type = db.volume_type_get_by_name(ctxt, 'LUKS')

        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description',
                                   volume_type=db_vol_type)
        self.assertEqual(db_vol_type.get('id'), volume['volume_type_id'])
        self.assertIsNotNone(volume['encryption_key_id'])

    def test_create_volume_with_provider_id(self):
        volume_params_with_provider_id = dict(provider_id='1111-aaaa',
                                              **self.volume_params)

        volume = tests_utils.create_volume(self.context,
                                           **volume_params_with_provider_id)

        self.volume.create_volume(self.context, volume['id'])
        self.assertEqual('1111-aaaa', volume['provider_id'])

    @mock.patch.object(keymgr, 'API', new=fake_keymgr.fake_api)
    def test_create_delete_volume_with_encrypted_volume_type(self):
        ctxt = context.get_admin_context()

        db.volume_type_create(ctxt,
                              {'id': '61298380-0c12-11e3-bfd6-4b48424183be',
                               'name': 'LUKS'})
        db.volume_type_encryption_create(
            ctxt,
            '61298380-0c12-11e3-bfd6-4b48424183be',
            {'control_location': 'front-end', 'provider': ENCRYPTION_PROVIDER})

        volume_api = cinder.volume.api.API()

        db_vol_type = db.volume_type_get_by_name(ctxt, 'LUKS')

        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description',
                                   volume_type=db_vol_type)

        self.assertIsNotNone(volume.get('encryption_key_id', None))
        self.assertEqual(db_vol_type.get('id'), volume['volume_type_id'])
        self.assertIsNotNone(volume['encryption_key_id'])

        volume['host'] = 'fake_host'
        volume['status'] = 'available'
        volume_api.delete(self.context, volume)

        volume = db.volume_get(self.context, volume['id'])
        self.assertEqual('deleting', volume['status'])

        db.volume_destroy(self.context, volume['id'])
        self.assertRaises(exception.NotFound,
                          db.volume_get,
                          self.context,
                          volume['id'])

    def test_extra_capabilities(self):
        # Test valid extra_capabilities.
        fake_capabilities = {'key1': 1, 'key2': 2}

        with mock.patch.object(jsonutils, 'loads') as mock_loads:
            mock_loads.return_value = fake_capabilities
            manager = vol_manager.VolumeManager()
            manager.stats = {'pools': {}}
            manager.driver.set_initialized()
            manager.publish_service_capabilities(self.context)
            self.assertTrue(mock_loads.called)
            volume_stats = manager.last_capabilities
            self.assertEqual(fake_capabilities['key1'],
                             volume_stats['key1'])
            self.assertEqual(fake_capabilities['key2'],
                             volume_stats['key2'])

    def test_extra_capabilities_fail(self):
        with mock.patch.object(jsonutils, 'loads') as mock_loads:
            mock_loads.side_effect = exception.CinderException('test')
            self.assertRaises(exception.CinderException,
                              vol_manager.VolumeManager)

    @mock.patch.object(db, 'volume_get_all_by_host')
    def test_update_replication_rel_status(self, m_get_by_host):
        m_get_by_host.return_value = [mock.sentinel.vol]
        ctxt = context.get_admin_context()
        manager = vol_manager.VolumeManager()
        with mock.patch.object(manager.driver,
                               'get_replication_status') as m_get_rep_status:
            m_get_rep_status.return_value = None
            manager._update_replication_relationship_status(ctxt)
            m_get_rep_status.assert_called_once_with(ctxt, mock.sentinel.vol)
        exp_filters = {
            'replication_status':
            ['active', 'copying', 'error', 'active-stopped', 'inactive']}
        m_get_by_host.assert_called_once_with(ctxt, manager.host,
                                              filters=exp_filters)

    @mock.patch.object(db, 'volume_get_all_by_host',
                       mock.Mock(return_value=[{'id': 'foo'}]))
    @mock.patch.object(db, 'volume_update')
    def test_update_replication_rel_status_update_vol(self, mock_update):
        """Volume is updated with replication update data."""
        ctxt = context.get_admin_context()
        manager = vol_manager.VolumeManager()
        with mock.patch.object(manager.driver,
                               'get_replication_status') as m_get_rep_status:
            m_get_rep_status.return_value = mock.sentinel.model_update
            manager._update_replication_relationship_status(ctxt)
        mock_update.assert_called_once_with(ctxt, 'foo',
                                            mock.sentinel.model_update)

    @mock.patch.object(db, 'volume_get_all_by_host',
                       mock.Mock(return_value=[{'id': 'foo'}]))
    def test_update_replication_rel_status_with_repl_support_exc(self):
        """Exception handled when raised getting replication status."""
        ctxt = context.get_admin_context()
        manager = vol_manager.VolumeManager()
        manager.driver._initialized = True
        manager.driver._stats['replication'] = True
        with mock.patch.object(manager.driver,
                               'get_replication_status') as m_get_rep_status:
            m_get_rep_status.side_effect = Exception()
            manager._update_replication_relationship_status(ctxt)

    def test_delete_busy_volume(self):
        """Test volume survives deletion if driver reports it as busy."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        self.mox.StubOutWithMock(self.volume.driver, 'delete_volume')
        self.volume.driver.delete_volume(
            mox.IgnoreArg()).AndRaise(exception.VolumeIsBusy(
                                      volume_name='fake'))
        self.mox.ReplayAll()
        res = self.volume.delete_volume(self.context, volume_id)
        self.assertTrue(res)
        volume_ref = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(volume_id, volume_ref.id)
        self.assertEqual("available", volume_ref.status)

    def test_get_volume_different_tenant(self):
        """Test can't get volume of another tenant when viewable_admin_meta."""
        volume = tests_utils.create_volume(self.context,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

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

        self.volume.delete_volume(self.context, volume_id)

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
                fake_volume = {'volume_type_id': 'fake_type_id',
                               'name': 'fake_name',
                               'host': 'fake_host',
                               'id': 'fake_volume_id'}

                fake_volume_list = []
                fake_volume_list.append([fake_volume])
                by_project.return_value = fake_volume_list
                get_all.return_value = fake_volume_list

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

    def test_delete_volume_in_error_extending(self):
        """Test volume can be deleted in error_extending stats."""
        # create a volume
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])

        # delete 'error_extending' volume
        db.volume_update(self.context, volume['id'],
                         {'status': 'error_extending'})
        self.volume.delete_volume(self.context, volume['id'])
        self.assertRaises(exception.NotFound, db.volume_get,
                          self.context, volume['id'])

    @mock.patch.object(db, 'volume_get', side_effect=exception.VolumeNotFound(
                       volume_id='12345678-1234-5678-1234-567812345678'))
    def test_delete_volume_not_found(self, mock_get_volume):
        """Test delete volume moves on if the volume does not exist."""
        volume_id = '12345678-1234-5678-1234-567812345678'
        self.assertTrue(self.volume.delete_volume(self.context, volume_id))
        self.assertTrue(mock_get_volume.called)

    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'create_volume_from_snapshot')
    def test_create_volume_from_snapshot(self, mock_create_from_snap):
        """Test volume can be created from a snapshot."""
        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src['id'])
        snapshot_id = self._create_snapshot(volume_src['id'],
                                            size=volume_src['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, volume_src['id'],
                                    snapshot_obj)
        volume_dst = tests_utils.create_volume(self.context,
                                               snapshot_id=snapshot_id,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_dst['id'])
        self.assertEqual(volume_dst['id'],
                         db.volume_get(
                             context.get_admin_context(),
                             volume_dst['id']).id)
        self.assertEqual(snapshot_id,
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).snapshot_id)

        self.volume.delete_volume(self.context, volume_dst['id'])
        self.volume.delete_snapshot(self.context, snapshot_obj)
        self.volume.delete_volume(self.context, volume_src['id'])

    @mock.patch('cinder.volume.flows.api.create_volume.get_flow')
    def test_create_volume_from_snapshot_with_types(self, _get_flow):
        """Test volume create from snapshot with types including mistmatch."""
        volume_api = cinder.volume.api.API()

        db.volume_type_create(
            context.get_admin_context(),
            {'name': 'foo',
             'extra_specs': {'volume_backend_name': 'dev_1'}})

        db.volume_type_create(
            context.get_admin_context(),
            {'name': 'biz', 'extra_specs': {'volume_backend_name': 'dev_2'}})

        foo_type = db.volume_type_get_by_name(context.get_admin_context(),
                                              'foo')
        biz_type = db.volume_type_get_by_name(context.get_admin_context(),
                                              'biz')

        snapshot = {'id': 1234,
                    'status': 'available',
                    'volume_size': 10,
                    'volume_type_id': biz_type['id']}
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.context,
                                                       **snapshot)
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
        self.assertRaises(exception.InvalidVolumeType,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          volume_type=foo_type,
                          snapshot=snapshot_obj)

        with mock.patch.object(cinder.volume.volume_types,
                               'get_volume_type') as mock_get_type:
            mock_get_type.return_value = biz_type
            snapshot_obj.volume_type_id = foo_type['id']
            volume_api.create(self.context, size=1, name='fake_name',
                              description='fake_desc', volume_type=foo_type,
                              snapshot=snapshot_obj)

        db.volume_type_destroy(context.get_admin_context(),
                               foo_type['id'])
        db.volume_type_destroy(context.get_admin_context(),
                               biz_type['id'])

    @mock.patch('cinder.volume.flows.api.create_volume.get_flow')
    def test_create_volume_from_source_with_types(self, _get_flow):
        """Test volume create from source with types including mistmatch."""
        volume_api = cinder.volume.api.API()

        db.volume_type_create(
            context.get_admin_context(),
            {'name': 'foo',
             'extra_specs': {'volume_backend_name': 'dev_1'}})

        db.volume_type_create(
            context.get_admin_context(),
            {'name': 'biz', 'extra_specs': {'volume_backend_name': 'dev_2'}})

        foo_type = db.volume_type_get_by_name(context.get_admin_context(),
                                              'foo')
        biz_type = db.volume_type_get_by_name(context.get_admin_context(),
                                              'biz')

        source_vol = {'id': 1234,
                      'status': 'available',
                      'volume_size': 10,
                      'volume_type': biz_type,
                      'volume_type_id': biz_type['id']}

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
        source_vol['volume_type_id'] = None
        source_vol['volume_type'] = None
        self.assertRaises(exception.InvalidVolumeType,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          volume_type=foo_type,
                          source_volume=source_vol)

        with mock.patch.object(cinder.volume.volume_types,
                               'get_volume_type') as mock_get_type:
            mock_get_type.return_value = biz_type
            source_vol['volume_type_id'] = biz_type['id']
            source_vol['volume_type'] = biz_type
            volume_api.create(self.context, size=1, name='fake_name',
                              description='fake_desc', volume_type=biz_type,
                              source_volume=source_vol)

        db.volume_type_destroy(context.get_admin_context(),
                               foo_type['id'])
        db.volume_type_destroy(context.get_admin_context(),
                               biz_type['id'])

    @mock.patch('cinder.volume.flows.api.create_volume.get_flow')
    def test_create_volume_from_source_with_same_backend(self, _get_flow):
        """Test volume create from source with type mismatch same backend."""
        volume_api = cinder.volume.api.API()

        foo_type = {
            'name': 'foo',
            'qos_specs_id': None,
            'deleted': False,
            'created_at': datetime.datetime(2015, 5, 8, 0, 40, 5, 408232),
            'updated_at': None,
            'extra_specs': {'volume_backend_name': 'dev_1'},
            'is_public': True,
            'deleted_at': None,
            'id': '29e43b50-2cd7-4d0c-8ddd-2119daab3a38',
            'description': None}

        biz_type = {
            'name': 'biz',
            'qos_specs_id': None,
            'deleted': False,
            'created_at': datetime.datetime(2015, 5, 8, 0, 20, 5, 408232),
            'updated_at': None,
            'extra_specs': {'volume_backend_name': 'dev_1'},
            'is_public': True,
            'deleted_at': None,
            'id': '34e54c31-3bc8-5c1d-9fff-2225bcce4b59',
            'description': None}

        source_vol = {'id': 1234,
                      'status': 'available',
                      'volume_size': 10,
                      'volume_type': biz_type,
                      'volume_type_id': biz_type['id']}

        with mock.patch.object(cinder.volume.volume_types,
                               'get_volume_type') as mock_get_type:
            mock_get_type.return_value = biz_type
            volume_api.create(self.context,
                              size=1,
                              name='fake_name',
                              description='fake_desc',
                              volume_type=foo_type,
                              source_volume=source_vol)

    @mock.patch('cinder.volume.flows.api.create_volume.get_flow')
    def test_create_from_source_and_snap_only_one_backend(self, _get_flow):
        """Test create from source and snap with type mismatch one backend."""
        volume_api = cinder.volume.api.API()

        foo_type = {
            'name': 'foo',
            'qos_specs_id': None,
            'deleted': False,
            'created_at': datetime.datetime(2015, 5, 8, 0, 40, 5, 408232),
            'updated_at': None,
            'extra_specs': {'some_key': 3},
            'is_public': True,
            'deleted_at': None,
            'id': '29e43b50-2cd7-4d0c-8ddd-2119daab3a38',
            'description': None}

        biz_type = {
            'name': 'biz',
            'qos_specs_id': None,
            'deleted': False,
            'created_at': datetime.datetime(2015, 5, 8, 0, 20, 5, 408232),
            'updated_at': None,
            'extra_specs': {'some_other_key': 4},
            'is_public': True,
            'deleted_at': None,
            'id': '34e54c31-3bc8-5c1d-9fff-2225bcce4b59',
            'description': None}

        source_vol = {'id': 1234,
                      'status': 'available',
                      'volume_size': 10,
                      'volume_type': biz_type,
                      'volume_type_id': biz_type['id']}

        snapshot = {'id': 1234,
                    'status': 'available',
                    'volume_size': 10,
                    'volume_type_id': biz_type['id']}
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.context,
                                                       **snapshot)

        with mock.patch.object(db,
                               'service_get_all_by_topic') as mock_get_service, \
            mock.patch.object(volume_api,
                              'list_availability_zones') as mock_get_azs:
            mock_get_service.return_value = [{'host': 'foo'}]
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

    def test_create_snapshot_driver_not_initialized(self):
        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src['id'])
        snapshot_id = self._create_snapshot(volume_src['id'],
                                            size=volume_src['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)

        self.volume.driver._initialized = False

        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.create_snapshot,
                          self.context, volume_src['id'], snapshot_obj)

        # NOTE(flaper87): The volume status should be error.
        self.assertEqual("error", snapshot_obj.status)

        # lets cleanup the mess
        self.volume.driver._initialized = True
        self.volume.delete_snapshot(self.context, snapshot_obj)
        self.volume.delete_volume(self.context, volume_src['id'])

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

    @mock.patch.object(cinder.volume.drivers.lvm.LVMISCSIDriver,
                       'create_volume_from_snapshot')
    def test_create_volume_from_snapshot_check_locks(
            self, mock_lvm_create):
        # mock the synchroniser so we can record events
        self.stubs.Set(utils, 'synchronized', self._mock_synchronized)
        orig_flow = engine.ActionEngine.run

        def mock_flow_run(*args, **kwargs):
            # ensure the lock has been taken
            self.assertEqual(1, len(self.called))
            # now proceed with the flow.
            ret = orig_flow(*args, **kwargs)
            return ret

        # create source volume
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        # no lock
        self.volume.create_volume(self.context, src_vol_id)

        snap_id = self._create_snapshot(src_vol_id,
                                        size=src_vol['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snap_id)
        # no lock
        self.volume.create_snapshot(self.context, src_vol_id, snapshot_obj)

        dst_vol = tests_utils.create_volume(self.context,
                                            snapshot_id=snap_id,
                                            **self.volume_params)
        dst_vol_id = dst_vol['id']
        admin_ctxt = context.get_admin_context()

        # mock the flow runner so we can do some checks
        self.stubs.Set(engine.ActionEngine, 'run', mock_flow_run)

        # locked
        self.volume.create_volume(self.context, volume_id=dst_vol_id,
                                  request_spec={'snapshot_id': snap_id})
        self.assertEqual(2, len(self.called))
        self.assertEqual(dst_vol_id, db.volume_get(admin_ctxt, dst_vol_id).id)
        self.assertEqual(snap_id,
                         db.volume_get(admin_ctxt, dst_vol_id).snapshot_id)

        # locked
        self.volume.delete_volume(self.context, dst_vol_id)
        self.assertEqual(4, len(self.called))

        # locked
        self.volume.delete_snapshot(self.context, snapshot_obj)
        self.assertEqual(6, len(self.called))

        # locked
        self.volume.delete_volume(self.context, src_vol_id)
        self.assertEqual(8, len(self.called))

        self.assertEqual(['lock-%s' % ('%s-delete_snapshot' % (snap_id)),
                          'unlock-%s' % ('%s-delete_snapshot' % (snap_id)),
                          'lock-%s' % ('%s-delete_volume' % (dst_vol_id)),
                          'unlock-%s' % ('%s-delete_volume' % (dst_vol_id)),
                          'lock-%s' % ('%s-delete_snapshot' % (snap_id)),
                          'unlock-%s' % ('%s-delete_snapshot' % (snap_id)),
                          'lock-%s' % ('%s-delete_volume' % (src_vol_id)),
                          'unlock-%s' % ('%s-delete_volume' % (src_vol_id))],
                         self.called)

        self.assertTrue(mock_lvm_create.called)

    def test_create_volume_from_volume_check_locks(self):
        # mock the synchroniser so we can record events
        self.stubs.Set(utils, 'synchronized', self._mock_synchronized)
        self.stubs.Set(utils, 'execute', self._fake_execute)

        orig_flow = engine.ActionEngine.run

        def mock_flow_run(*args, **kwargs):
            # ensure the lock has been taken
            self.assertEqual(1, len(self.called))
            # now proceed with the flow.
            ret = orig_flow(*args, **kwargs)
            return ret

        # create source volume
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        # no lock
        self.volume.create_volume(self.context, src_vol_id)

        dst_vol = tests_utils.create_volume(self.context,
                                            source_volid=src_vol_id,
                                            **self.volume_params)
        dst_vol_id = dst_vol['id']
        admin_ctxt = context.get_admin_context()

        # mock the flow runner so we can do some checks
        self.stubs.Set(engine.ActionEngine, 'run', mock_flow_run)

        # locked
        self.volume.create_volume(self.context, volume_id=dst_vol_id,
                                  request_spec={'source_volid': src_vol_id})
        self.assertEqual(2, len(self.called))
        self.assertEqual(dst_vol_id, db.volume_get(admin_ctxt, dst_vol_id).id)
        self.assertEqual(src_vol_id,
                         db.volume_get(admin_ctxt, dst_vol_id).source_volid)

        # locked
        self.volume.delete_volume(self.context, dst_vol_id)
        self.assertEqual(4, len(self.called))

        # locked
        self.volume.delete_volume(self.context, src_vol_id)
        self.assertEqual(6, len(self.called))

        self.assertEqual(['lock-%s' % ('%s-delete_volume' % (src_vol_id)),
                          'unlock-%s' % ('%s-delete_volume' % (src_vol_id)),
                          'lock-%s' % ('%s-delete_volume' % (dst_vol_id)),
                          'unlock-%s' % ('%s-delete_volume' % (dst_vol_id)),
                          'lock-%s' % ('%s-delete_volume' % (src_vol_id)),
                          'unlock-%s' % ('%s-delete_volume' % (src_vol_id))],
                         self.called)

    def test_create_volume_from_volume_delete_lock_taken(self):
        # create source volume
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        # no lock
        self.volume.create_volume(self.context, src_vol_id)

        dst_vol = tests_utils.create_volume(self.context,
                                            source_volid=src_vol_id,
                                            **self.volume_params)
        dst_vol_id = dst_vol['id']

        orig_elevated = self.context.elevated

        gthreads = []

        def mock_elevated(*args, **kwargs):
            # unset mock so it is only called once
            self.stubs.Set(self.context, 'elevated', orig_elevated)

            # we expect this to block and then fail
            t = eventlet.spawn(self.volume.create_volume,
                               self.context,
                               volume_id=dst_vol_id,
                               request_spec={'source_volid': src_vol_id})
            gthreads.append(t)

            return orig_elevated(*args, **kwargs)

        # mock something from early on in the delete operation and within the
        # lock so that when we do the create we expect it to block.
        self.stubs.Set(self.context, 'elevated', mock_elevated)

        # locked
        self.volume.delete_volume(self.context, src_vol_id)

        # we expect the volume create to fail with the following err since the
        # source volume was deleted while the create was locked. Note that the
        # volume is still in the db since it was created by the test prior to
        # calling manager.create_volume.
        with mock.patch('sys.stderr', new=six.StringIO()):
            self.assertRaises(exception.VolumeNotFound, gthreads[0].wait)

    def _raise_metadata_copy_failure(self, method, dst_vol_id, **kwargs):
        # MetadataCopyFailure exception will be raised if DB service is Down
        # while copying the volume glance metadata
        with mock.patch.object(db, method) as mock_db:
            mock_db.side_effect = exception.MetadataCopyFailure(
                reason="Because of DB service down.")
            self.assertRaises(exception.MetadataCopyFailure,
                              self.volume.create_volume,
                              self.context,
                              dst_vol_id,
                              **kwargs)

        # ensure that status of volume is 'error'
        vol = db.volume_get(self.context, dst_vol_id)
        self.assertEqual('error', vol['status'])

        # cleanup resource
        db.volume_destroy(self.context, dst_vol_id)

    @mock.patch('cinder.utils.execute')
    def test_create_volume_from_volume_with_glance_volume_metadata_none(
            self, mock_execute):
        # create source volume
        mock_execute.return_value = None
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        self.volume.create_volume(self.context, src_vol_id)
        # set bootable flag of volume to True
        db.volume_update(self.context, src_vol['id'], {'bootable': True})

        # create volume from source volume
        dst_vol = tests_utils.create_volume(self.context,
                                            source_volid=src_vol_id,
                                            **self.volume_params)
        self.volume.create_volume(self.context,
                                  dst_vol['id'])

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

        self.volume.create_volume(self.context, src_vol_id)
        # set bootable flag of volume to True
        db.volume_update(self.context, src_vol['id'], {'bootable': True})

        # create volume from source volume
        dst_vol = tests_utils.create_volume(self.context,
                                            source_volid=src_vol_id,
                                            **self.volume_params)
        self._raise_metadata_copy_failure(
            'volume_glance_metadata_copy_from_volume_to_volume',
            dst_vol['id'])

        # cleanup resource
        db.volume_destroy(self.context, src_vol_id)

    @mock.patch('cinder.utils.execute')
    def test_create_volume_from_snapshot_raise_metadata_copy_failure(
            self, mock_execute):
        # create source volume
        mock_execute.return_value = None
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        self.volume.create_volume(self.context, src_vol_id)
        # set bootable flag of volume to True
        db.volume_update(self.context, src_vol['id'], {'bootable': True})

        # create volume from snapshot
        snapshot_id = self._create_snapshot(src_vol['id'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, src_vol['id'], snapshot_obj)

        # ensure that status of snapshot is 'available'
        self.assertEqual('available', snapshot_obj.status)

        dst_vol = tests_utils.create_volume(self.context,
                                            snapshot_id=snapshot_id,
                                            **self.volume_params)
        self._raise_metadata_copy_failure(
            'volume_glance_metadata_copy_to_volume',
            dst_vol['id'])

        # cleanup resource
        snapshot_obj.destroy()
        db.volume_destroy(self.context, src_vol_id)

    @mock.patch(
        'cinder.volume.driver.VolumeDriver.create_replica_test_volume')
    @mock.patch('cinder.utils.execute')
    def test_create_volume_from_srcreplica_raise_metadata_copy_failure(
            self, mock_execute, _create_replica_test):
        mock_execute.return_value = None
        _create_replica_test.return_value = None
        # create source volume
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        self.volume.create_volume(self.context, src_vol_id)
        # set bootable flag of volume to True
        db.volume_update(self.context, src_vol['id'], {'bootable': True})

        # create volume from source volume
        dst_vol = tests_utils.create_volume(self.context,
                                            source_volid=src_vol_id,
                                            **self.volume_params)
        self._raise_metadata_copy_failure(
            'volume_glance_metadata_copy_from_volume_to_volume',
            dst_vol['id'])

        # cleanup resource
        db.volume_destroy(self.context, src_vol_id)

    @mock.patch('cinder.utils.execute')
    def test_create_volume_from_snapshot_with_glance_volume_metadata_none(
            self, mock_execute):
        # create source volume
        mock_execute.return_value = None
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        self.volume.create_volume(self.context, src_vol_id)
        # set bootable flag of volume to True
        db.volume_update(self.context, src_vol['id'], {'bootable': True})

        volume = db.volume_get(self.context, src_vol_id)

        # create snapshot of volume
        snapshot_id = self._create_snapshot(volume['id'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, volume['id'], snapshot_obj)

        # ensure that status of snapshot is 'available'
        self.assertEqual('available', snapshot_obj.status)

        # create volume from snapshot
        dst_vol = tests_utils.create_volume(self.context,
                                            snapshot_id=snapshot_id,
                                            **self.volume_params)
        self.volume.create_volume(self.context,
                                  dst_vol['id'])

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

    @mock.patch(
        'cinder.volume.driver.VolumeDriver.create_replica_test_volume')
    def test_create_volume_from_srcreplica_with_glance_volume_metadata_none(
            self, _create_replica_test):
        """Test volume can be created from a volume replica."""
        _create_replica_test.return_value = None

        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src['id'])
        db.volume_update(self.context, volume_src['id'], {'bootable': True})

        volume = db.volume_get(self.context, volume_src['id'])
        volume_dst = tests_utils.create_volume(
            self.context,
            **self.volume_params)
        self.volume.create_volume(self.context, volume_dst['id'],
                                  {'source_replicaid': volume['id']})

        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_glance_metadata_copy_from_volume_to_volume,
                          self.context, volume_src['id'], volume_dst['id'])

        self.assertEqual('available',
                         db.volume_get(self.context,
                                       volume_dst['id']).status)
        self.assertTrue(_create_replica_test.called)

        # cleanup resource
        db.volume_destroy(self.context, volume_dst['id'])
        db.volume_destroy(self.context, volume_src['id'])

    def test_create_volume_from_snapshot_delete_lock_taken(self):
        # create source volume
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        # no lock
        self.volume.create_volume(self.context, src_vol_id)

        # create snapshot
        snap_id = self._create_snapshot(src_vol_id,
                                        size=src_vol['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snap_id)
        # no lock
        self.volume.create_snapshot(self.context, src_vol_id, snapshot_obj)

        # create vol from snapshot...
        dst_vol = tests_utils.create_volume(self.context,
                                            snapshot_id=snap_id,
                                            source_volid=src_vol_id,
                                            **self.volume_params)
        dst_vol_id = dst_vol['id']

        orig_elevated = self.context.elevated

        gthreads = []

        def mock_elevated(*args, **kwargs):
            # unset mock so it is only called once
            self.stubs.Set(self.context, 'elevated', orig_elevated)

            # We expect this to block and then fail
            t = eventlet.spawn(self.volume.create_volume, self.context,
                               volume_id=dst_vol_id,
                               request_spec={'snapshot_id': snap_id})
            gthreads.append(t)

            return orig_elevated(*args, **kwargs)

        # mock something from early on in the delete operation and within the
        # lock so that when we do the create we expect it to block.
        self.stubs.Set(self.context, 'elevated', mock_elevated)

        # locked
        self.volume.delete_snapshot(self.context, snapshot_obj)

        # we expect the volume create to fail with the following err since the
        # snapshot was deleted while the create was locked. Note that the
        # volume is still in the db since it was created by the test prior to
        #  calling manager.create_volume.
        with mock.patch('sys.stderr', new=six.StringIO()):
            self.assertRaises(exception.SnapshotNotFound, gthreads[0].wait)
        # locked
        self.volume.delete_volume(self.context, src_vol_id)
        # make sure it is gone
        self.assertRaises(exception.VolumeNotFound, db.volume_get,
                          self.context, src_vol_id)

    @mock.patch.object(keymgr, 'API', fake_keymgr.fake_api)
    def test_create_volume_from_snapshot_with_encryption(self):
        """Test volume can be created from a snapshot of an encrypted volume"""
        ctxt = context.get_admin_context()

        db.volume_type_create(ctxt,
                              {'id': '61298380-0c12-11e3-bfd6-4b48424183be',
                               'name': 'LUKS'})
        db.volume_type_encryption_create(
            ctxt,
            '61298380-0c12-11e3-bfd6-4b48424183be',
            {'control_location': 'front-end', 'provider': ENCRYPTION_PROVIDER})

        volume_api = cinder.volume.api.API()

        db_vol_type = db.volume_type_get_by_name(context.get_admin_context(),
                                                 'LUKS')
        volume_src = volume_api.create(self.context,
                                       1,
                                       'name',
                                       'description',
                                       volume_type=db_vol_type)

        volume_src['host'] = 'fake_host'
        snapshot_ref = volume_api.create_snapshot_force(self.context,
                                                        volume_src,
                                                        'name',
                                                        'description')
        snapshot_ref['status'] = 'available'  # status must be available
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
        volume_src_key = key_manager.get_key(self.context,
                                             volume_src['encryption_key_id'])
        volume_dst_key = key_manager.get_key(self.context,
                                             volume_dst['encryption_key_id'])
        self.assertEqual(volume_src_key, volume_dst_key)

    def test_create_volume_from_encrypted_volume(self):
        """Test volume can be created from an encrypted volume."""
        self.stubs.Set(keymgr, 'API', fake_keymgr.fake_api)

        volume_api = cinder.volume.api.API()

        ctxt = context.get_admin_context()

        db.volume_type_create(ctxt,
                              {'id': '61298380-0c12-11e3-bfd6-4b48424183be',
                               'name': 'LUKS'})
        db.volume_type_encryption_create(
            ctxt,
            '61298380-0c12-11e3-bfd6-4b48424183be',
            {'control_location': 'front-end', 'provider': ENCRYPTION_PROVIDER})

        db_vol_type = db.volume_type_get_by_name(context.get_admin_context(),
                                                 'LUKS')
        volume_src = volume_api.create(self.context,
                                       1,
                                       'name',
                                       'description',
                                       volume_type=db_vol_type)
        volume_src['status'] = 'available'  # status must be available
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

        key_manager = volume_api.key_manager  # must use *same* key manager
        volume_src_key = key_manager.get_key(self.context,
                                             volume_src['encryption_key_id'])
        volume_dst_key = key_manager.get_key(self.context,
                                             volume_dst['encryption_key_id'])
        self.assertEqual(volume_src_key, volume_dst_key)

    def test_create_volume_from_snapshot_fail_bad_size(self):
        """Test volume can't be created from snapshot with bad volume size."""
        volume_api = cinder.volume.api.API()
        snapshot = {'id': 1234,
                    'status': 'available',
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

        self.stubs.Set(volume_api,
                       'list_availability_zones',
                       fake_list_availability_zones)

        volume_src = tests_utils.create_volume(self.context,
                                               availability_zone='az2',
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src['id'])
        snapshot = self._create_snapshot(volume_src['id'])

        self.volume.create_snapshot(self.context, volume_src['id'],
                                    snapshot)

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
                          snapshot='fake_id',
                          image_id='fake_id',
                          source_volume='fake_id')

    @mock.patch.object(cinder.volume.targets.iscsi.ISCSITarget,
                       '_get_target_chap_auth')
    @mock.patch.object(db, 'volume_admin_metadata_get')
    @mock.patch.object(db, 'volume_get')
    @mock.patch.object(db, 'volume_update')
    def test_initialize_connection_fetchqos(self,
                                            _mock_volume_update,
                                            _mock_volume_get,
                                            _mock_volume_admin_metadata_get,
                                            mock_get_target):
        """Make sure initialize_connection returns correct information."""
        _fake_admin_meta = {'fake-key': 'fake-value'}
        _fake_volume = {'volume_type_id': 'fake_type_id',
                        'name': 'fake_name',
                        'host': 'fake_host',
                        'id': 'fake_volume_id',
                        'volume_admin_metadata': _fake_admin_meta}

        _mock_volume_get.return_value = _fake_volume
        _mock_volume_update.return_value = _fake_volume
        _mock_volume_admin_metadata_get.return_value = _fake_admin_meta

        connector = {'ip': 'IP', 'initiator': 'INITIATOR'}
        qos_values = {'consumer': 'front-end',
                      'specs': {
                          'key1': 'value1',
                          'key2': 'value2'}
                      }

        with mock.patch.object(cinder.volume.volume_types,
                               'get_volume_type_qos_specs') as type_qos, \
            mock.patch.object(cinder.tests.unit.fake_driver.FakeISCSIDriver,
                              'initialize_connection') as driver_init:
            type_qos.return_value = dict(qos_specs=qos_values)
            driver_init.return_value = {'data': {}}
            mock_get_target.return_value = None
            qos_specs_expected = {'key1': 'value1',
                                  'key2': 'value2'}
            # initialize_connection() passes qos_specs that is designated to
            # be consumed by front-end or both front-end and back-end
            conn_info = self.volume.initialize_connection(self.context,
                                                          'fake_volume_id',
                                                          connector)
            self.assertDictMatch(qos_specs_expected,
                                 conn_info['data']['qos_specs'])

            qos_values.update({'consumer': 'both'})
            conn_info = self.volume.initialize_connection(self.context,
                                                          'fake_volume_id',
                                                          connector)
            self.assertDictMatch(qos_specs_expected,
                                 conn_info['data']['qos_specs'])
            # initialize_connection() skips qos_specs that is designated to be
            # consumed by back-end only
            qos_values.update({'consumer': 'back-end'})
            type_qos.return_value = dict(qos_specs=qos_values)
            conn_info = self.volume.initialize_connection(self.context,
                                                          'fake_volume_id',
                                                          connector)
            self.assertIsNone(conn_info['data']['qos_specs'])

    @mock.patch.object(fake_driver.FakeISCSIDriver, 'create_export')
    @mock.patch.object(db, 'volume_get')
    @mock.patch.object(db, 'volume_update')
    def test_initialize_connection_export_failure(self,
                                                  _mock_volume_update,
                                                  _mock_volume_get,
                                                  _mock_create_export):
        """Test exception path for create_export failure."""
        _fake_admin_meta = {'fake-key': 'fake-value'}
        _fake_volume = {'volume_type_id': 'fake_type_id',
                        'name': 'fake_name',
                        'host': 'fake_host',
                        'id': 'fake_volume_id',
                        'volume_admin_metadata': _fake_admin_meta}

        _mock_volume_get.return_value = _fake_volume
        _mock_volume_update.return_value = _fake_volume
        _mock_create_export.side_effect = exception.CinderException

        connector = {'ip': 'IP', 'initiator': 'INITIATOR'}

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.initialize_connection,
                          self.context,
                          'fake_volume_id',
                          connector)

    @mock.patch.object(cinder.volume.targets.iscsi.ISCSITarget,
                       '_get_target_chap_auth')
    @mock.patch.object(db, 'volume_admin_metadata_get')
    @mock.patch.object(db, 'volume_update')
    @mock.patch.object(db, 'volume_get')
    @mock.patch.object(fake_driver.FakeISCSIDriver, 'initialize_connection')
    @mock.patch.object(db, 'driver_initiator_data_get')
    @mock.patch.object(db, 'driver_initiator_data_update')
    def test_initialize_connection_initiator_data(self, mock_data_update,
                                                  mock_data_get,
                                                  mock_driver_init,
                                                  mock_volume_get,
                                                  mock_volume_update,
                                                  mock_metadata_get,
                                                  mock_get_target):

        fake_admin_meta = {'fake-key': 'fake-value'}
        fake_volume = {'volume_type_id': None,
                       'name': 'fake_name',
                       'host': 'fake_host',
                       'id': 'fake_volume_id',
                       'volume_admin_metadata': fake_admin_meta,
                       'encryption_key_id': ('d371e7bb-7392-4c27-'
                                             'ac0b-ebd9f5d16078')}

        mock_volume_get.return_value = fake_volume
        mock_volume_update.return_value = fake_volume
        mock_get_target.return_value = None
        connector = {'ip': 'IP', 'initiator': 'INITIATOR'}
        mock_driver_init.return_value = {
            'driver_volume_type': 'iscsi',
            'data': {'access_mode': 'rw',
                     'encrypted': False}
        }
        mock_data_get.return_value = []
        conn_info = self.volume.initialize_connection(self.context, 'id',
                                                      connector)
        # Asserts that if the driver sets the encrypted flag then the
        # VolumeManager doesn't overwrite it regardless of what's in the
        # volume for the encryption_key_id field.
        self.assertFalse(conn_info['data']['encrypted'])
        mock_driver_init.assert_called_with(fake_volume, connector)

        data = [{'key': 'key1', 'value': 'value1'}]
        mock_data_get.return_value = data
        self.volume.initialize_connection(self.context, 'id', connector)
        mock_driver_init.assert_called_with(fake_volume, connector, data)

        update = {
            'set_values': {
                'foo': 'bar'
            },
            'remove_values': [
                'foo',
                'foo2'
            ]
        }
        mock_driver_init.return_value['initiator_update'] = update
        self.volume.initialize_connection(self.context, 'id', connector)
        mock_driver_init.assert_called_with(fake_volume, connector, data)
        mock_data_update.assert_called_with(self.context, 'INITIATOR',
                                            'FakeISCSIDriver', update)

        connector['initiator'] = None
        mock_data_update.reset_mock()
        mock_data_get.reset_mock()
        mock_driver_init.return_value['data'].pop('encrypted')
        conn_info = self.volume.initialize_connection(self.context, 'id',
                                                      connector)
        # Asserts that VolumeManager sets the encrypted flag if the driver
        # doesn't set it.
        self.assertTrue(conn_info['data']['encrypted'])
        mock_driver_init.assert_called_with(fake_volume, connector)
        self.assertFalse(mock_data_get.called)
        self.assertFalse(mock_data_update.called)

    def test_run_attach_detach_volume_for_instance(self):
        """Make sure volume can be attached and detached from instance."""
        mountpoint = "/dev/sdf"
        # attach volume to the instance then to detach
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        attachment = self.volume.attach_volume(self.context, volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual("in-use", vol['status'])
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)

        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)
        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('available', vol['status'])

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_detach_invalid_attachment_id(self):
        """Make sure if the attachment id isn't found we raise."""
        attachment_id = "notfoundid"
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=False,
                                           **self.volume_params)
        self.volume.detach_volume(self.context, volume['id'],
                                  attachment_id)
        volume = db.volume_get(self.context, volume['id'])
        self.assertEqual('available', volume['status'])

        instance_uuid = '12345678-1234-5678-1234-567812345678'
        attached_host = 'fake_host'
        mountpoint = '/dev/fake'
        tests_utils.attach_volume(self.context, volume['id'],
                                  instance_uuid, attached_host,
                                  mountpoint)
        self.volume.detach_volume(self.context, volume['id'],
                                  attachment_id)
        volume = db.volume_get(self.context, volume['id'])
        self.assertEqual('in-use', volume['status'])

    def test_detach_no_attachments(self):
        self.volume_params['status'] = 'detaching'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=False,
                                           **self.volume_params)
        self.volume.detach_volume(self.context, volume['id'])
        volume = db.volume_get(self.context, volume['id'])
        self.assertEqual('available', volume['status'])

    def test_run_attach_detach_volume_for_instance_no_attachment_id(self):
        """Make sure volume can be attached and detached from instance."""
        mountpoint = "/dev/sdf"
        # attach volume to the instance then to detach
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        instance_uuid_2 = '12345678-4321-8765-4321-567812345678'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=True,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        attachment = self.volume.attach_volume(self.context, volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)
        attachment2 = self.volume.attach_volume(self.context, volume_id,
                                                instance_uuid_2, None,
                                                mountpoint, 'ro')

        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])
        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)

        self.assertRaises(exception.InvalidVolume,
                          self.volume.detach_volume,
                          self.context, volume_id)

        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('in-use', vol['status'])

        self.volume.detach_volume(self.context, volume_id, attachment2['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('available', vol['status'])

        attachment = self.volume.attach_volume(self.context, volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro')
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('in-use', vol['status'])
        self.volume.detach_volume(self.context, volume_id)
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('available', vol['status'])

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_detach_multiattach_volume_for_instances(self):
        """Make sure volume can be attached to multiple instances."""
        mountpoint = "/dev/sdf"
        # attach volume to the instance then to detach
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=True,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        attachment = self.volume.attach_volume(self.context, volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])

        instance2_uuid = '12345678-1234-5678-1234-567812345000'
        mountpoint2 = "/dev/sdx"
        attachment2 = self.volume.attach_volume(self.context, volume_id,
                                                instance2_uuid, None,
                                                mountpoint2, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertEqual('attached', attachment2['attach_status'])
        self.assertEqual(mountpoint2, attachment2['mountpoint'])
        self.assertEqual(instance2_uuid, attachment2['instance_uuid'])
        self.assertIsNone(attachment2['attached_host'])
        self.assertNotEqual(attachment, attachment2)

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)
        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('in-use', vol['status'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)

        self.volume.detach_volume(self.context, volume_id, attachment2['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('available', vol['status'])

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_twice_multiattach_volume_for_instances(self):
        """Make sure volume can be attached to multiple instances."""
        mountpoint = "/dev/sdf"
        # attach volume to the instance then to detach
        instance_uuid = '12345678-1234-5678-1234-567812345699'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=True,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        attachment = self.volume.attach_volume(self.context, volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])

        mountpoint2 = "/dev/sdx"
        attachment2 = self.volume.attach_volume(self.context, volume_id,
                                                instance_uuid, None,
                                                mountpoint2, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertIsNone(attachment2)

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)

    def test_attach_detach_not_multiattach_volume_for_instances(self):
        """Make sure volume can't be attached to more than one instance."""
        mountpoint = "/dev/sdf"
        # attach volume to the instance then to detach
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           multiattach=False,
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        attachment = self.volume.attach_volume(self.context, volume_id,
                                               instance_uuid, None,
                                               mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertFalse(vol['multiattach'])
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])

        instance2_uuid = '12345678-1234-5678-1234-567812345000'
        mountpoint2 = "/dev/sdx"
        self.assertRaises(exception.InvalidVolume,
                          self.volume.attach_volume,
                          self.context,
                          volume_id,
                          instance2_uuid,
                          None,
                          mountpoint2, 'ro')

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)
        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('available', vol['status'])

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_detach_volume_for_host(self):
        """Make sure volume can be attached and detached from host."""
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(
            self.context,
            admin_metadata={'readonly': 'False'},
            **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        attachment = self.volume.attach_volume(self.context, volume_id, None,
                                               'fake_host', mountpoint, 'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host', attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='False', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)

        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)
        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual("available", vol['status'])

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_detach_multiattach_volume_for_hosts(self):
        """Make sure volume can be attached and detached from hosts."""
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(
            self.context,
            admin_metadata={'readonly': 'False'},
            multiattach=True,
            **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        attachment = self.volume.attach_volume(self.context, volume_id, None,
                                               'fake_host', mountpoint, 'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host', attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='False', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])

        mountpoint2 = "/dev/sdx"
        attachment2 = self.volume.attach_volume(self.context, volume_id, None,
                                                'fake_host2', mountpoint2,
                                                'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertEqual('attached', attachment2['attach_status'])
        self.assertEqual(mountpoint2, attachment2['mountpoint'])
        self.assertIsNone(attachment2['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host2', attachment2['attached_host'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)
        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual("in-use", vol['status'])

        self.volume.detach_volume(self.context, volume_id, attachment2['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual("available", vol['status'])

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_twice_multiattach_volume_for_hosts(self):
        """Make sure volume can be attached and detached from hosts."""
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(
            self.context,
            admin_metadata={'readonly': 'False'},
            multiattach=True,
            **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        attachment = self.volume.attach_volume(self.context, volume_id, None,
                                               'fake_host', mountpoint, 'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertTrue(vol['multiattach'])
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host', attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='False', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])

        mountpoint2 = "/dev/sdx"
        attachment2 = self.volume.attach_volume(self.context, volume_id, None,
                                                'fake_host', mountpoint2,
                                                'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertIsNone(attachment2)

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)

    def test_run_attach_detach_not_multiattach_volume_for_hosts(self):
        """Make sure volume can't be attached to more than one host."""
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(
            self.context,
            admin_metadata={'readonly': 'False'},
            multiattach=False,
            **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        attachment = self.volume.attach_volume(self.context, volume_id, None,
                                               'fake_host', mountpoint, 'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertFalse(vol['multiattach'])
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host', attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='False', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])

        mountpoint2 = "/dev/sdx"
        self.assertRaises(exception.InvalidVolume,
                          self.volume.attach_volume,
                          self.context,
                          volume_id,
                          None,
                          'fake_host2',
                          mountpoint2,
                          'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('in-use', vol['status'])
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual('fake-host', attachment['attached_host'])

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)
        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual('available', vol['status'])

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_attach_detach_volume_with_attach_mode(self):
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        volume_id = volume['id']
        db.volume_update(self.context, volume_id, {'status': 'available', })
        self.volume.attach_volume(self.context, volume_id, instance_uuid,
                                  None, mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        attachment = vol['volume_attachment'][0]
        self.assertEqual('in-use', vol['status'])
        self.assertEqual('attached', vol['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)

        self.assertEqual('ro', conn_info['data']['access_mode'])

        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        attachment = vol['volume_attachment']
        self.assertEqual('available', vol['status'])
        self.assertEqual('detached', vol['attach_status'])
        self.assertEqual([], attachment)
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('True', admin_metadata[0]['value'])

        self.volume.attach_volume(self.context, volume_id, None,
                                  'fake_host', mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        attachment = vol['volume_attachment'][0]
        self.assertEqual('in-use', vol['status'])
        self.assertEqual('attached', vol['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertIsNone(attachment['instance_uuid'])
        self.assertEqual('fake-host', attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])

        self.volume.detach_volume(self.context, volume_id,
                                  attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        attachment = vol['volume_attachment']
        self.assertEqual('available', vol['status'])
        self.assertEqual('detached', vol['attach_status'])
        self.assertEqual([], attachment)
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('True', admin_metadata[0]['value'])

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_run_manager_attach_detach_volume_with_wrong_attach_mode(self):
        # Not allow using 'read-write' mode attach readonly volume
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        self.assertRaises(exception.InvalidVolumeAttachMode,
                          self.volume.attach_volume,
                          self.context,
                          volume_id,
                          instance_uuid,
                          None,
                          mountpoint,
                          'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('error_attaching', vol['status'])
        self.assertEqual('detached', vol['attach_status'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)

        db.volume_update(self.context, volume_id, {'status': 'available'})
        self.assertRaises(exception.InvalidVolumeAttachMode,
                          self.volume.attach_volume,
                          self.context,
                          volume_id,
                          None,
                          'fake_host',
                          mountpoint,
                          'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('error_attaching', vol['status'])
        self.assertEqual('detached', vol['attach_status'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        expected = dict(readonly='True', attached_mode='rw')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(expected, ret)

    def test_run_api_attach_detach_volume_with_wrong_attach_mode(self):
        # Not allow using 'read-write' mode attach readonly volume
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        mountpoint = "/dev/sdf"
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolumeAttachMode,
                          volume_api.attach,
                          self.context,
                          volume,
                          instance_uuid,
                          None,
                          mountpoint,
                          'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('detached', vol['attach_status'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('True', admin_metadata[0]['value'])

        db.volume_update(self.context, volume_id, {'status': 'available'})
        self.assertRaises(exception.InvalidVolumeAttachMode,
                          volume_api.attach,
                          self.context,
                          volume,
                          None,
                          'fake_host',
                          mountpoint,
                          'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual('detached', vol['attach_status'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('True', admin_metadata[0]['value'])

    def test_detach_volume_while_uploading_to_image_is_in_progress(self):
        # If instance is booted from volume with 'Terminate on Delete' flag
        # set, and when we delete instance then it tries to delete volume
        # even it is in 'uploading' state.
        # It is happening because detach call is setting volume status to
        # 'available'.
        mountpoint = "/dev/sdf"
        # Attach volume to the instance
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        self.volume.attach_volume(self.context, volume_id, instance_uuid,
                                  None, mountpoint, 'ro')
        # Change volume status to 'uploading'
        db.volume_update(self.context, volume_id, {'status': 'uploading'})
        # Call detach api
        self.volume.detach_volume(self.context, volume_id)
        vol = db.volume_get(self.context, volume_id)
        # Check that volume status is 'uploading'
        self.assertEqual("uploading", vol['status'])
        self.assertEqual("detached", vol['attach_status'])

    @mock.patch.object(cinder.volume.api.API, 'update')
    @mock.patch.object(db, 'volume_get')
    def test_reserve_volume_success(self, volume_get, volume_update):
        fake_volume = {
            'id': self.FAKE_UUID,
            'status': 'available'
        }

        volume_get.return_value = fake_volume
        volume_update.return_value = fake_volume

        self.assertIsNone(cinder.volume.api.API().reserve_volume(
            self.context,
            fake_volume,
        ))

        self.assertTrue(volume_get.called)
        self.assertTrue(volume_update.called)

    def test_reserve_volume_in_attaching(self):
        self._test_reserve_volume_bad_status('attaching')

    def test_reserve_volume_in_maintenance(self):
        self._test_reserve_volume_bad_status('maintenance')

    def _test_reserve_volume_bad_status(self, status):
        fake_volume = {
            'id': self.FAKE_UUID,
            'status': status
        }

        with mock.patch.object(db, 'volume_get') as mock_volume_get:
            mock_volume_get.return_value = fake_volume
            self.assertRaises(exception.InvalidVolume,
                              cinder.volume.api.API().reserve_volume,
                              self.context,
                              fake_volume)
            self.assertTrue(mock_volume_get.called)

    @mock.patch.object(db, 'volume_get')
    @mock.patch.object(db, 'volume_attachment_get_used_by_volume_id')
    @mock.patch.object(cinder.volume.api.API, 'update')
    def test_unreserve_volume_success(self, volume_get,
                                      volume_attachment_get_used_by_volume_id,
                                      volume_update):
        fake_volume = {
            'id': self.FAKE_UUID,
            'status': 'attaching'
        }
        fake_attachments = [{'volume_id': self.FAKE_UUID,
                             'instance_uuid': 'fake_instance_uuid'}]

        volume_get.return_value = fake_volume
        volume_attachment_get_used_by_volume_id.return_value = fake_attachments
        volume_update.return_value = fake_volume

        self.assertIsNone(cinder.volume.api.API().unreserve_volume(
            self.context,
            fake_volume
        ))

        self.assertTrue(volume_get.called)
        self.assertTrue(volume_attachment_get_used_by_volume_id.called)
        self.assertTrue(volume_update.called)

    def test_concurrent_volumes_get_different_targets(self):
        """Ensure multiple concurrent volumes get different targets."""
        volume_ids = []
        targets = []

        def _check(volume_id):
            """Make sure targets aren't duplicated."""
            volume_ids.append(volume_id)
            admin_context = context.get_admin_context()
            iscsi_target = db.volume_get_iscsi_target_num(admin_context,
                                                          volume_id)
            self.assertNotIn(iscsi_target, targets)
            targets.append(iscsi_target)

        # FIXME(jdg): What is this actually testing?
        # We never call the internal _check method?
        for _index in range(100):
            tests_utils.create_volume(self.context, **self.volume_params)
        for volume_id in volume_ids:
            self.volume.delete_volume(self.context, volume_id)

    def test_multi_node(self):
        # TODO(termie): Figure out how to test with two nodes,
        # each of them having a different FLAG for storage_node
        # This will allow us to test cross-node interactions
        pass

    @staticmethod
    def _create_snapshot(volume_id, size=1, metadata=None):
        """Create a snapshot object."""
        metadata = metadata or {}
        snap = objects.Snapshot(context.get_admin_context())
        snap.volume_size = size
        snap.user_id = 'fake'
        snap.project_id = 'fake'
        snap.volume_id = volume_id
        snap.status = "creating"
        if metadata is not None:
            snap.metadata = metadata
        snap.create()
        return snap

    def test_create_delete_snapshot(self):
        """Test snapshot can be created and deleted."""
        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **self.volume_params)
        self.assertEqual(0, len(self.notifier.notifications),
                         self.notifier.notifications)
        self.volume.create_volume(self.context, volume['id'])
        msg = self.notifier.notifications[0]
        self.assertEqual('volume.create.start', msg['event_type'])
        self.assertEqual('creating', msg['payload']['status'])
        self.assertEqual('INFO', msg['priority'])
        msg = self.notifier.notifications[1]
        self.assertEqual('volume.create.end', msg['event_type'])
        self.assertEqual('available', msg['payload']['status'])
        self.assertEqual('INFO', msg['priority'])
        if len(self.notifier.notifications) > 2:
            # Cause an assert to print the unexpected item
            # and all of the notifications.
            self.assertFalse(self.notifier.notifications[2],
                             self.notifier.notifications)
        self.assertEqual(2, len(self.notifier.notifications),
                         self.notifier.notifications)

        snapshot = self._create_snapshot(volume['id'], size=volume['size'])
        snapshot_id = snapshot.id
        self.volume.create_snapshot(self.context, volume['id'], snapshot)
        self.assertEqual(
            snapshot_id, objects.Snapshot.get_by_id(self.context,
                                                    snapshot_id).id)
        msg = self.notifier.notifications[2]
        self.assertEqual('snapshot.create.start', msg['event_type'])
        expected = {
            'created_at': 'DONTCARE',
            'deleted': '',
            'display_name': None,
            'snapshot_id': snapshot_id,
            'status': 'creating',
            'tenant_id': 'fake',
            'user_id': 'fake',
            'volume_id': volume['id'],
            'volume_size': 1,
            'availability_zone': 'nova',
            'metadata': '',
        }
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[3]
        self.assertEqual('snapshot.create.end', msg['event_type'])
        expected['status'] = 'available'
        self.assertDictMatch(expected, msg['payload'])

        if len(self.notifier.notifications) > 4:
            # Cause an assert to print the unexpected item
            # and all of the notifications.
            self.assertFalse(self.notifier.notifications[4],
                             self.notifier.notifications)

        self.assertEqual(4, len(self.notifier.notifications),
                         self.notifier.notifications)

        self.volume.delete_snapshot(self.context, snapshot)
        msg = self.notifier.notifications[4]
        self.assertEqual('snapshot.delete.start', msg['event_type'])
        expected['status'] = 'available'
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[5]
        self.assertEqual('snapshot.delete.end', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])

        if len(self.notifier.notifications) > 6:
            # Cause an assert to print the unexpected item
            # and all of the notifications.
            self.assertFalse(self.notifier.notifications[6],
                             self.notifier.notifications)

        self.assertEqual(6, len(self.notifier.notifications),
                         self.notifier.notifications)

        snap = objects.Snapshot.get_by_id(context.get_admin_context(
            read_deleted='yes'), snapshot_id)
        self.assertEqual('deleted', snap.status)
        self.assertRaises(exception.NotFound,
                          db.snapshot_get,
                          self.context,
                          snapshot_id)
        self.volume.delete_volume(self.context, volume['id'])

    def test_create_delete_snapshot_with_metadata(self):
        """Test snapshot can be created with metadata and deleted."""
        test_meta = {'fake_key': 'fake_value'}
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        snapshot = self._create_snapshot(volume['id'], size=volume['size'],
                                         metadata=test_meta)
        snapshot_id = snapshot.id

        result_dict = snapshot.metadata

        self.assertEqual(test_meta, result_dict)
        self.volume.delete_snapshot(self.context, snapshot)
        self.assertRaises(exception.NotFound,
                          db.snapshot_get,
                          self.context,
                          snapshot_id)

    @mock.patch.object(db, 'snapshot_create',
                       side_effect=exception.InvalidSnapshot(
                           'Create snapshot in db failed!'))
    def test_create_snapshot_failed_db_snapshot(self, mock_snapshot):
        """Test exception handling when create snapshot in db failed."""
        test_volume = tests_utils.create_volume(
            self.context,
            **self.volume_params)
        self.volume.create_volume(self.context, test_volume['id'])
        test_volume['status'] = 'available'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidSnapshot,
                          volume_api.create_snapshot,
                          self.context,
                          test_volume,
                          'fake_name',
                          'fake_description')

    def test_create_snapshot_failed_maintenance(self):
        """Test exception handling when create snapshot in maintenance."""
        test_volume = tests_utils.create_volume(
            self.context,
            **self.volume_params)
        self.volume.create_volume(self.context, test_volume['id'])
        test_volume['status'] = 'maintenance'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.create_snapshot,
                          self.context,
                          test_volume,
                          'fake_name',
                          'fake_description')

    @mock.patch.object(QUOTAS, 'commit',
                       side_effect=exception.QuotaError(
                           'Snapshot quota commit failed!'))
    def test_create_snapshot_failed_quota_commit(self, mock_snapshot):
        """Test exception handling when snapshot quota commit failed."""
        test_volume = tests_utils.create_volume(
            self.context,
            **self.volume_params)
        self.volume.create_volume(self.context, test_volume['id'],
                                  request_spec={})
        test_volume['status'] = 'available'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.QuotaError,
                          volume_api.create_snapshot,
                          self.context,
                          test_volume,
                          'fake_name',
                          'fake_description')

    def test_cannot_delete_volume_in_use(self):
        """Test volume can't be deleted in in-use status."""
        self._test_cannot_delete_volume('in-use')

    def test_cannot_delete_volume_maintenance(self):
        """Test volume can't be deleted in maintenance status."""
        self._test_cannot_delete_volume('maintenance')

    def _test_cannot_delete_volume(self, status):
        """Test volume can't be deleted in invalid stats."""
        # create a volume and assign to host
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        volume['status'] = status
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        # 'in-use' status raises InvalidVolume
        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete,
                          self.context,
                          volume)

        # clean up
        self.volume.delete_volume(self.context, volume['id'])

    def test_force_delete_volume(self):
        """Test volume can be forced to delete."""
        # create a volume and assign to host
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        volume['status'] = 'error_deleting'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        # 'error_deleting' volumes can't be deleted
        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete,
                          self.context,
                          volume)

        # delete with force
        volume_api.delete(self.context, volume, force=True)

        # status is deleting
        volume = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEqual('deleting', volume['status'])

        # clean up
        self.volume.delete_volume(self.context, volume['id'])

    def test_cannot_force_delete_attached_volume(self):
        """Test volume can't be force delete in attached state."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        volume['status'] = 'in-use'
        volume['attach_status'] = 'attached'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.VolumeAttached,
                          volume_api.delete,
                          self.context,
                          volume,
                          force=True)

        self.volume.delete_volume(self.context, volume['id'])

    def test_cannot_delete_volume_with_snapshots(self):
        """Test volume can't be deleted with dependent snapshots."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        snapshot = self._create_snapshot(volume['id'], size=volume['size'])
        self.volume.create_snapshot(self.context, volume['id'], snapshot)
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
        self.volume.delete_volume(self.context, volume['id'])

    def test_can_delete_errored_snapshot(self):
        """Test snapshot can be created and deleted."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        snapshot = self._create_snapshot(volume['id'], size=volume['size'])
        self.volume.create_snapshot(self.context, volume['id'], snapshot)

        volume_api = cinder.volume.api.API()

        snapshot.status = 'badstatus'
        self.assertRaises(exception.InvalidSnapshot,
                          volume_api.delete_snapshot,
                          self.context,
                          snapshot)

        snapshot.status = 'error'
        self.volume.delete_snapshot(self.context, snapshot)
        self.volume.delete_volume(self.context, volume['id'])

    def test_create_snapshot_force(self):
        """Test snapshot in use can be created forcibly."""

        instance_uuid = '12345678-1234-5678-1234-567812345678'
        # create volume and attach to the instance
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        values = {'volume_id': volume['id'],
                  'instance_uuid': instance_uuid,
                  'attach_status': 'attaching', }
        attachment = db.volume_attach(self.context, values)
        db.volume_attached(self.context, attachment['id'], instance_uuid,
                           None, '/dev/sda1')

        volume_api = cinder.volume.api.API()
        volume = volume_api.get(self.context, volume['id'])
        self.assertRaises(exception.InvalidVolume,
                          volume_api.create_snapshot,
                          self.context, volume,
                          'fake_name', 'fake_description')
        snapshot_ref = volume_api.create_snapshot_force(self.context,
                                                        volume,
                                                        'fake_name',
                                                        'fake_description')
        snapshot_ref.destroy()
        db.volume_destroy(self.context, volume['id'])

        # create volume and attach to the host
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        values = {'volume_id': volume['id'],
                  'attached_host': 'fake_host',
                  'attach_status': 'attaching', }
        attachment = db.volume_attach(self.context, values)
        db.volume_attached(self.context, attachment['id'], None,
                           'fake_host', '/dev/sda1')

        volume_api = cinder.volume.api.API()
        volume = volume_api.get(self.context, volume['id'])
        self.assertRaises(exception.InvalidVolume,
                          volume_api.create_snapshot,
                          self.context, volume,
                          'fake_name', 'fake_description')
        snapshot_ref = volume_api.create_snapshot_force(self.context,
                                                        volume,
                                                        'fake_name',
                                                        'fake_description')
        snapshot_ref.destroy()
        db.volume_destroy(self.context, volume['id'])

    def test_create_snapshot_from_bootable_volume(self):
        """Test create snapshot from bootable volume."""
        # create bootable volume from image
        volume = self._create_volume_from_image()
        volume_id = volume['id']
        self.assertEqual('available', volume['status'])
        self.assertTrue(volume['bootable'])

        # get volume's volume_glance_metadata
        ctxt = context.get_admin_context()
        vol_glance_meta = db.volume_glance_metadata_get(ctxt, volume_id)
        self.assertTrue(vol_glance_meta)

        # create snapshot from bootable volume
        snap = self._create_snapshot(volume_id)
        self.volume.create_snapshot(ctxt, volume_id, snap)

        # get snapshot's volume_glance_metadata
        snap_glance_meta = db.volume_snapshot_glance_metadata_get(
            ctxt, snap.id)
        self.assertTrue(snap_glance_meta)

        # ensure that volume's glance metadata is copied
        # to snapshot's glance metadata
        self.assertEqual(len(vol_glance_meta), len(snap_glance_meta))
        vol_glance_dict = {x.key: x.value for x in vol_glance_meta}
        snap_glance_dict = {x.key: x.value for x in snap_glance_meta}
        self.assertDictMatch(vol_glance_dict, snap_glance_dict)

        # ensure that snapshot's status is changed to 'available'
        self.assertEqual('available', snap.status)

        # cleanup resource
        snap.destroy()
        db.volume_destroy(ctxt, volume_id)

    def test_create_snapshot_from_bootable_volume_fail(self):
        """Test create snapshot from bootable volume.

        But it fails to volume_glance_metadata_copy_to_snapshot.
        As a result, status of snapshot is changed to ERROR.
        """
        # create bootable volume from image
        volume = self._create_volume_from_image()
        volume_id = volume['id']
        self.assertEqual('available', volume['status'])
        self.assertTrue(volume['bootable'])

        # get volume's volume_glance_metadata
        ctxt = context.get_admin_context()
        vol_glance_meta = db.volume_glance_metadata_get(ctxt, volume_id)
        self.assertTrue(vol_glance_meta)
        snap = self._create_snapshot(volume_id)
        snap_stat = snap.status
        self.assertTrue(snap.id)
        self.assertTrue(snap_stat)

        # set to return DB exception
        with mock.patch.object(db, 'volume_glance_metadata_copy_to_snapshot')\
                as mock_db:
            mock_db.side_effect = exception.MetadataCopyFailure(
                reason="Because of DB service down.")
            # create snapshot from bootable volume
            self.assertRaises(exception.MetadataCopyFailure,
                              self.volume.create_snapshot,
                              ctxt,
                              volume_id,
                              snap)

        # get snapshot's volume_glance_metadata
        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_snapshot_glance_metadata_get,
                          ctxt, snap.id)

        # ensure that status of snapshot is 'error'
        self.assertEqual('error', snap.status)

        # cleanup resource
        snap.destroy()
        db.volume_destroy(ctxt, volume_id)

    def test_create_snapshot_from_bootable_volume_with_volume_metadata_none(
            self):
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_id = volume['id']

        self.volume.create_volume(self.context, volume_id)
        # set bootable flag of volume to True
        db.volume_update(self.context, volume_id, {'bootable': True})

        snapshot = self._create_snapshot(volume['id'])
        self.volume.create_snapshot(self.context, volume['id'], snapshot)
        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_snapshot_glance_metadata_get,
                          self.context, snapshot.id)

        # ensure that status of snapshot is 'available'
        self.assertEqual('available', snapshot.status)

        # cleanup resource
        snapshot.destroy()
        db.volume_destroy(self.context, volume_id)

    def test_delete_busy_snapshot(self):
        """Test snapshot can be created and deleted."""

        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                      False,
                                                      None,
                                                      'default')

        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        snapshot = self._create_snapshot(volume_id, size=volume['size'])
        self.volume.create_snapshot(self.context, volume_id, snapshot)

        self.mox.StubOutWithMock(self.volume.driver, 'delete_snapshot')

        self.volume.driver.delete_snapshot(
            mox.IgnoreArg()).AndRaise(
            exception.SnapshotIsBusy(snapshot_name='fake'))
        self.mox.ReplayAll()
        snapshot_id = snapshot.id
        self.volume.delete_snapshot(self.context, snapshot)
        snapshot_ref = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.assertEqual(snapshot_id, snapshot_ref.id)
        self.assertEqual("available", snapshot_ref.status)

    @test.testtools.skipIf(sys.platform == "darwin", "SKIP on OSX")
    def test_delete_no_dev_fails(self):
        """Test delete snapshot with no dev file fails."""
        self.stubs.Set(os.path, 'exists', lambda x: False)
        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                      False,
                                                      None,
                                                      'default')

        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        snapshot = self._create_snapshot(volume_id)
        snapshot_id = snapshot.id
        self.volume.create_snapshot(self.context, volume_id, snapshot)

        self.mox.StubOutWithMock(self.volume.driver, 'delete_snapshot')

        self.volume.driver.delete_snapshot(
            mox.IgnoreArg()).AndRaise(
            exception.SnapshotIsBusy(snapshot_name='fake'))
        self.mox.ReplayAll()
        self.volume.delete_snapshot(self.context, snapshot)
        snapshot_ref = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.assertEqual(snapshot_id, snapshot_ref.id)
        self.assertEqual("available", snapshot_ref.status)

        self.mox.UnsetStubs()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.delete_snapshot,
                          self.context,
                          snapshot)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)

    @mock.patch('cinder.image.image_utils.TemporaryImages.fetch')
    @mock.patch('cinder.volume.flows.manager.create_volume.'
                'CreateVolumeFromSpecTask._clone_image_volume')
    def _create_volume_from_image(self, mock_clone_image_volume,
                                  mock_fetch_img,
                                  fakeout_copy_image_to_volume=False,
                                  fakeout_clone_image=False,
                                  clone_image_volume=False):
        """Test function of create_volume_from_image.

        Test cases call this function to create a volume from image, caller
        can choose whether to fake out copy_image_to_volume and clone_image,
        after calling this, test cases should check status of the volume.
        """
        def fake_local_path(volume):
            return dst_path

        def fake_copy_image_to_volume(context, volume,
                                      image_service, image_id):
            pass

        def fake_fetch_to_raw(ctx, image_service, image_id, path, blocksize,
                              size=None, throttle=None):
            pass

        def fake_clone_image(ctx, volume_ref,
                             image_location, image_meta,
                             image_service):
            return {'provider_location': None}, True

        dst_fd, dst_path = tempfile.mkstemp()
        os.close(dst_fd)
        self.stubs.Set(self.volume.driver, 'local_path', fake_local_path)
        if fakeout_clone_image:
            self.stubs.Set(self.volume.driver, 'clone_image', fake_clone_image)
        self.stubs.Set(image_utils, 'fetch_to_raw', fake_fetch_to_raw)
        if fakeout_copy_image_to_volume:
            self.stubs.Set(self.volume.driver, 'copy_image_to_volume',
                           fake_copy_image_to_volume)
        mock_clone_image_volume.return_value = ({}, clone_image_volume)
        mock_fetch_img.return_value = mock.MagicMock(
            spec=tests_utils.get_file_spec())

        image_id = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        volume_id = tests_utils.create_volume(self.context,
                                              **self.volume_params)['id']
        # creating volume testdata
        try:
            request_spec = {
                'volume_properties': self.volume_params,
                'image_id': image_id,
            }
            self.volume.create_volume(self.context,
                                      volume_id,
                                      request_spec)
        finally:
            # cleanup
            os.unlink(dst_path)
            volume = db.volume_get(self.context, volume_id)

        return volume

    def test_create_volume_from_image_cloned_status_available(self):
        """Test create volume from image via cloning.

        Verify that after cloning image to volume, it is in available
        state and is bootable.
        """
        volume = self._create_volume_from_image()
        self.assertEqual('available', volume['status'])
        self.assertTrue(volume['bootable'])
        self.volume.delete_volume(self.context, volume['id'])

    def test_create_volume_from_image_not_cloned_status_available(self):
        """Test create volume from image via full copy.

        Verify that after copying image to volume, it is in available
        state and is bootable.
        """
        volume = self._create_volume_from_image(fakeout_clone_image=True)
        self.assertEqual('available', volume['status'])
        self.assertTrue(volume['bootable'])
        self.volume.delete_volume(self.context, volume['id'])

    def test_create_volume_from_image_exception(self):
        """Test create volume from a non-existing image.

        Verify that create volume from a non-existing image, the volume
        status is 'error' and is not bootable.
        """
        dst_fd, dst_path = tempfile.mkstemp()
        os.close(dst_fd)

        self.stubs.Set(self.volume.driver, 'local_path', lambda x: dst_path)

        # creating volume testdata
        volume_id = 1
        db.volume_create(self.context,
                         {'id': volume_id,
                          'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                          'display_description': 'Test Desc',
                          'size': 20,
                          'status': 'creating',
                          'host': 'dummy'})

        self.assertRaises(exception.ImageNotFound,
                          self.volume.create_volume,
                          self.context,
                          volume_id,
                          {'image_id': self.FAKE_UUID})
        volume = db.volume_get(self.context, volume_id)
        self.assertEqual("error", volume['status'])
        self.assertFalse(volume['bootable'])
        # cleanup
        db.volume_destroy(self.context, volume_id)
        os.unlink(dst_path)

    def test_create_volume_from_image_copy_exception_rescheduling(self):
        """Test create volume with ImageCopyFailure

        This exception should not trigger rescheduling and allocated_capacity
        should be incremented so we're having assert for that here.
        """
        def fake_copy_image_to_volume(context, volume, image_service,
                                      image_id):
            raise exception.ImageCopyFailure()

        self.stubs.Set(self.volume.driver, 'copy_image_to_volume',
                       fake_copy_image_to_volume)
        self.assertRaises(exception.ImageCopyFailure,
                          self._create_volume_from_image)
        # NOTE(dulek): Rescheduling should not occur, so lets assert that
        # allocated_capacity is incremented.
        self.assertDictEqual(self.volume.stats['pools'],
                             {'_pool0': {'allocated_capacity_gb': 1}})

    @mock.patch('cinder.utils.brick_get_connector_properties')
    @mock.patch('cinder.utils.brick_get_connector')
    @mock.patch('cinder.volume.driver.BaseVD.secure_file_operations_enabled')
    @mock.patch('cinder.volume.driver.BaseVD._detach_volume')
    def test_create_volume_from_image_unavailable(self, mock_detach,
                                                  mock_secure, *args):
        """Test create volume with ImageCopyFailure

        We'll raise an exception inside _connect_device after volume has
        already been attached to confirm that it detaches the volume.
        """
        mock_secure.side_effect = NameError

        # We want to test BaseVD copy_image_to_volume and since FakeISCSIDriver
        # inherits from LVM it overwrites it, so we'll mock it to use the
        # BaseVD implementation.
        unbound_copy_method = cinder.volume.driver.BaseVD.copy_image_to_volume
        bound_copy_method = unbound_copy_method.__get__(self.volume.driver)
        with mock.patch.object(self.volume.driver, 'copy_image_to_volume',
                               side_effect=bound_copy_method):
            self.assertRaises(exception.ImageCopyFailure,
                              self._create_volume_from_image,
                              fakeout_copy_image_to_volume=False)
        # We must have called detach method.
        self.assertEqual(1, mock_detach.call_count)

    def test_create_volume_from_image_clone_image_volume(self):
        """Test create volume from image via image volume.

        Verify that after cloning image to volume, it is in available
        state and is bootable.
        """
        volume = self._create_volume_from_image(clone_image_volume=True)
        self.assertEqual('available', volume['status'])
        self.assertTrue(volume['bootable'])
        self.volume.delete_volume(self.context, volume['id'])

    def test_create_volume_from_exact_sized_image(self):
        """Test create volume from an image of the same size.

        Verify that an image which is exactly the same size as the
        volume, will work correctly.
        """
        try:
            volume_id = None
            volume_api = cinder.volume.api.API(
                image_service=FakeImageService())
            volume = volume_api.create(self.context, 2, 'name', 'description',
                                       image_id=1)
            volume_id = volume['id']
            self.assertEqual('creating', volume['status'])

        finally:
            # cleanup
            db.volume_destroy(self.context, volume_id)

    def test_create_volume_from_oversized_image(self):
        """Verify that an image which is too big will fail correctly."""
        class _ModifiedFakeImageService(FakeImageService):
            def show(self, context, image_id):
                return {'size': 2 * units.Gi + 1,
                        'disk_format': 'raw',
                        'container_format': 'bare',
                        'status': 'active'}

        volume_api = cinder.volume.api.API(
            image_service=_ModifiedFakeImageService())

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context, 2,
                          'name', 'description', image_id=1)

    def test_create_volume_with_mindisk_error(self):
        """Verify volumes smaller than image minDisk will cause an error."""
        class _ModifiedFakeImageService(FakeImageService):
            def show(self, context, image_id):
                return {'size': 2 * units.Gi,
                        'disk_format': 'raw',
                        'container_format': 'bare',
                        'min_disk': 5,
                        'status': 'active'}

        volume_api = cinder.volume.api.API(
            image_service=_ModifiedFakeImageService())

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context, 2,
                          'name', 'description', image_id=1)

    def test_create_volume_with_deleted_imaged(self):
        """Verify create volume from image will cause an error."""
        class _ModifiedFakeImageService(FakeImageService):
            def show(self, context, image_id):
                return {'size': 2 * units.Gi,
                        'disk_format': 'raw',
                        'container_format': 'bare',
                        'min_disk': 5,
                        'status': 'deleted'}

        volume_api = cinder.volume.api.API(
            image_service=_ModifiedFakeImageService())

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context, 2,
                          'name', 'description', image_id=1)

    @mock.patch.object(QUOTAS, "rollback")
    @mock.patch.object(QUOTAS, "commit")
    @mock.patch.object(QUOTAS, "reserve", return_value=["RESERVATION"])
    def _do_test_create_volume_with_size(self, size, *_unused_quota_mocks):
        volume_api = cinder.volume.api.API()

        volume = volume_api.create(self.context,
                                   size,
                                   'name',
                                   'description')
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

    @mock.patch.object(db, 'volume_get')
    def test_begin_detaching_fails_available(self, volume_get):
        volume_api = cinder.volume.api.API()
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_get.return_value = volume
        # Volume status is 'available'.
        self.assertRaises(exception.InvalidVolume, volume_api.begin_detaching,
                          self.context, volume)
        volume_get.assert_called_once_with(self.context, volume['id'])

        volume_get.reset_mock()
        volume['status'] = "in-use"
        volume['attach_status'] = "detached"
        # Should raise an error since not attached
        self.assertRaises(exception.InvalidVolume, volume_api.begin_detaching,
                          self.context, volume)
        volume_get.assert_called_once_with(self.context, volume['id'])

        volume_get.reset_mock()
        volume['attach_status'] = "attached"
        # Ensure when attached no exception raised
        volume_api.begin_detaching(self.context, volume)
        volume_get.assert_called_once_with(self.context, volume['id'])

        volume_get.reset_mock()
        volume['status'] = "maintenance"
        self.assertRaises(exception.InvalidVolume, volume_api.begin_detaching,
                          self.context, volume)
        volume_get.assert_called_once_with(self.context, volume['id'])

    def test_begin_roll_detaching_volume(self):
        """Test begin_detaching and roll_detaching functions."""

        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        attachment = db.volume_attach(self.context,
                                      {'volume_id': volume['id'],
                                       'attached_host': 'fake-host'})
        volume = db.volume_attached(
            self.context, attachment['id'], instance_uuid, 'fake-host', 'vdb')
        volume_api = cinder.volume.api.API()
        volume_api.begin_detaching(self.context, volume)
        volume = db.volume_get(self.context, volume['id'])
        self.assertEqual("detaching", volume['status'])
        volume_api.roll_detaching(self.context, volume)
        volume = db.volume_get(self.context, volume['id'])
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

    def test_volume_api_update_snapshot(self):
        # create raw snapshot
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        snapshot = self._create_snapshot(volume['id'])
        snapshot_id = snapshot.id
        self.assertIsNone(snapshot.display_name)
        # use volume.api to update name
        volume_api = cinder.volume.api.API()
        update_dict = {'display_name': 'test update name'}
        volume_api.update_snapshot(self.context, snapshot, update_dict)
        # read changes from db
        snap = objects.Snapshot.get_by_id(context.get_admin_context(),
                                          snapshot_id)
        self.assertEqual('test update name', snap.display_name)

    def test_volume_api_get_list_volumes_image_metadata(self):
        """Test get_list_volumes_image_metadata in volume API."""
        ctxt = context.get_admin_context()
        db.volume_create(ctxt, {'id': 'fake1', 'status': 'available',
                                'host': 'test', 'provider_location': '',
                                'size': 1})
        db.volume_glance_metadata_create(ctxt, 'fake1', 'key1', 'value1')
        db.volume_glance_metadata_create(ctxt, 'fake1', 'key2', 'value2')
        db.volume_create(ctxt, {'id': 'fake2', 'status': 'available',
                                'host': 'test', 'provider_location': '',
                                'size': 1})
        db.volume_glance_metadata_create(ctxt, 'fake2', 'key3', 'value3')
        db.volume_glance_metadata_create(ctxt, 'fake2', 'key4', 'value4')
        volume_api = cinder.volume.api.API()
        results = volume_api.get_list_volumes_image_metadata(ctxt, ['fake1',
                                                                    'fake2'])
        expect_results = {'fake1': {'key1': 'value1', 'key2': 'value2'},
                          'fake2': {'key3': 'value3', 'key4': 'value4'}}
        self.assertEqual(expect_results, results)

    @mock.patch.object(QUOTAS, 'reserve')
    def test_extend_volume(self, reserve):
        """Test volume can be extended at API level."""
        # create a volume and assign to host
        volume = tests_utils.create_volume(self.context, size=2,
                                           status='creating', host=CONF.host)
        self.volume.create_volume(self.context, volume['id'])
        volume['status'] = 'in-use'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        # Extend fails when status != available
        self.assertRaises(exception.InvalidVolume,
                          volume_api.extend,
                          self.context,
                          volume,
                          3)

        volume['status'] = 'available'
        # Extend fails when new_size < orig_size
        self.assertRaises(exception.InvalidInput,
                          volume_api.extend,
                          self.context,
                          volume,
                          1)

        # Extend fails when new_size == orig_size
        self.assertRaises(exception.InvalidInput,
                          volume_api.extend,
                          self.context,
                          volume,
                          2)

        # works when new_size > orig_size
        reserve.return_value = ["RESERVATION"]
        volume_api.extend(self.context, volume, 3)
        volume = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEqual('extending', volume['status'])
        reserve.assert_called_once_with(self.context, gigabytes=1,
                                        project_id=volume['project_id'])

        # Test the quota exceeded
        volume['status'] = 'available'
        reserve.side_effect = exception.OverQuota(overs=['gigabytes'],
                                                  quotas={'gigabytes': 20},
                                                  usages={'gigabytes':
                                                          {'reserved': 5,
                                                           'in_use': 15}})
        self.assertRaises(exception.VolumeSizeExceedsAvailableQuota,
                          volume_api.extend, self.context,
                          volume, 3)

        # clean up
        self.volume.delete_volume(self.context, volume['id'])

    def test_extend_volume_driver_not_initialized(self):
        """Test volume can be extended at API level."""
        # create a volume and assign to host
        fake_reservations = ['RESERVATION']
        volume = tests_utils.create_volume(self.context, size=2,
                                           status='available',
                                           host=CONF.host)
        self.volume.create_volume(self.context, volume['id'])

        self.volume.driver._initialized = False

        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.extend_volume,
                          self.context, volume['id'], 3,
                          fake_reservations)

        volume = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEqual('error_extending', volume.status)

        # lets cleanup the mess.
        self.volume.driver._initialized = True
        self.volume.delete_volume(self.context, volume['id'])

    def test_extend_volume_manager(self):
        """Test volume can be extended at the manager level."""
        def fake_extend(volume, new_size):
            volume['size'] = new_size

        fake_reservations = ['RESERVATION']
        volume = tests_utils.create_volume(self.context, size=2,
                                           status='creating', host=CONF.host)
        self.volume.create_volume(self.context, volume['id'])

        # Test driver exception
        with mock.patch.object(self.volume.driver,
                               'extend_volume') as extend_volume:
            extend_volume.side_effect =\
                exception.CinderException('fake exception')
            volume['status'] = 'extending'
            self.volume.extend_volume(self.context, volume['id'], '4',
                                      fake_reservations)
            volume = db.volume_get(context.get_admin_context(), volume['id'])
            self.assertEqual(2, volume['size'])
            self.assertEqual('error_extending', volume['status'])

        # Test driver success
        with mock.patch.object(self.volume.driver,
                               'extend_volume') as extend_volume:
            with mock.patch.object(QUOTAS, 'commit') as quotas_commit:
                extend_volume.return_value = fake_extend
                volume['status'] = 'extending'
                self.volume.extend_volume(self.context, volume['id'], '4',
                                          fake_reservations)
                volume = db.volume_get(context.get_admin_context(),
                                       volume['id'])
                self.assertEqual(4, volume['size'])
                self.assertEqual('available', volume['status'])
                quotas_commit.assert_called_with(
                    self.context,
                    ['RESERVATION'],
                    project_id=volume['project_id'])

        # clean up
        self.volume.delete_volume(self.context, volume['id'])

    def test_extend_volume_with_volume_type(self):
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
        volume['status'] = 'available'
        volume['host'] = 'fakehost'
        volume['volume_type_id'] = vol_type.get('id')

        volume_api.extend(self.context, volume, 200)

        try:
            usage = db.quota_usage_get(elevated, project_id, 'gigabytes_type')
            volumes_reserved = usage.reserved
        except exception.QuotaUsageNotFound:
            volumes_reserved = 0

        self.assertEqual(100, volumes_reserved)

    @mock.patch(
        'cinder.volume.driver.VolumeDriver.create_replica_test_volume')
    def test_create_volume_from_sourcereplica(self, _create_replica_test):
        """Test volume can be created from a volume replica."""
        _create_replica_test.return_value = None

        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src['id'])
        volume_dst = tests_utils.create_volume(
            self.context,
            **self.volume_params)
        self.volume.create_volume(self.context, volume_dst['id'],
                                  {'source_replicaid': volume_src['id']})
        self.assertEqual('available',
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).status)
        self.assertTrue(_create_replica_test.called)
        self.volume.delete_volume(self.context, volume_dst['id'])
        self.volume.delete_volume(self.context, volume_src['id'])

    def test_create_volume_from_sourcevol(self):
        """Test volume can be created from a source volume."""
        def fake_create_cloned_volume(volume, src_vref):
            pass

        self.stubs.Set(self.volume.driver, 'create_cloned_volume',
                       fake_create_cloned_volume)
        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src['id'])
        volume_dst = tests_utils.create_volume(self.context,
                                               source_volid=volume_src['id'],
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_dst['id'])
        self.assertEqual('available',
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).status)
        self.volume.delete_volume(self.context, volume_dst['id'])
        self.volume.delete_volume(self.context, volume_src['id'])

    @mock.patch('cinder.volume.api.API.list_availability_zones',
                return_value=({'name': 'nova', 'available': True},
                              {'name': 'az2', 'available': True}))
    def test_create_volume_from_sourcevol_fail_wrong_az(self, _mock_laz):
        """Test volume can't be cloned from an other volume in different az."""
        volume_api = cinder.volume.api.API()

        volume_src = tests_utils.create_volume(self.context,
                                               availability_zone='az2',
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src['id'])

        volume_src = db.volume_get(self.context, volume_src['id'])

        volume_dst = volume_api.create(self.context,
                                       size=1,
                                       name='fake_name',
                                       description='fake_desc',
                                       source_volume=volume_src)
        self.assertEqual('az2', volume_dst['availability_zone'])

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          source_volume=volume_src,
                          availability_zone='nova')

    def test_create_volume_from_sourcevol_with_glance_metadata(self):
        """Test glance metadata can be correctly copied to new volume."""
        def fake_create_cloned_volume(volume, src_vref):
            pass

        self.stubs.Set(self.volume.driver, 'create_cloned_volume',
                       fake_create_cloned_volume)
        volume_src = self._create_volume_from_image()
        self.volume.create_volume(self.context, volume_src['id'])
        volume_dst = tests_utils.create_volume(self.context,
                                               source_volid=volume_src['id'],
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_dst['id'])
        self.assertEqual('available',
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).status)
        src_glancemeta = db.volume_get(context.get_admin_context(),
                                       volume_src['id']).volume_glance_metadata
        dst_glancemeta = db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).volume_glance_metadata
        for meta_src in src_glancemeta:
            for meta_dst in dst_glancemeta:
                if meta_dst.key == meta_src.key:
                    self.assertEqual(meta_src.value, meta_dst.value)
        self.volume.delete_volume(self.context, volume_src['id'])
        self.volume.delete_volume(self.context, volume_dst['id'])

    def test_create_volume_from_sourcevol_failed_clone(self):
        """Test src vol status will be restore by error handling code."""
        def fake_error_create_cloned_volume(volume, src_vref):
            db.volume_update(self.context, src_vref['id'], {'status': 'error'})
            raise exception.CinderException('fake exception')

        self.stubs.Set(self.volume.driver, 'create_cloned_volume',
                       fake_error_create_cloned_volume)
        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src['id'])
        volume_dst = tests_utils.create_volume(self.context,
                                               source_volid=volume_src['id'],
                                               **self.volume_params)
        self.assertRaises(exception.CinderException,
                          self.volume.create_volume,
                          self.context,
                          volume_dst['id'])
        self.assertEqual('creating', volume_src['status'])
        self.volume.delete_volume(self.context, volume_dst['id'])
        self.volume.delete_volume(self.context, volume_src['id'])

    def test_clean_temporary_volume(self):
        def fake_delete_volume(ctxt, volume):
            db.volume_destroy(ctxt, volume['id'])

        fake_volume = tests_utils.create_volume(self.context, size=1,
                                                host=CONF.host)
        fake_new_volume = tests_utils.create_volume(self.context, size=1,
                                                    host=CONF.host)
        # Check when the migrated volume is in migration
        db.volume_update(self.context, fake_volume['id'],
                         {'migration_status': 'migrating'})
        # 1. Only clean the db
        self.volume._clean_temporary_volume(self.context, fake_volume['id'],
                                            fake_new_volume['id'],
                                            clean_db_only=True)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get, self.context,
                          fake_new_volume['id'])

        # 2. Delete the backend storage
        fake_new_volume = tests_utils.create_volume(self.context, size=1,
                                                    host=CONF.host)
        with mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume') as \
                mock_delete_volume:
            mock_delete_volume.side_effect = fake_delete_volume
            self.volume._clean_temporary_volume(self.context,
                                                fake_volume['id'],
                                                fake_new_volume['id'],
                                                clean_db_only=False)
            self.assertRaises(exception.VolumeNotFound,
                              db.volume_get, self.context,
                              fake_new_volume['id'])

        # Check when the migrated volume is not in migration
        fake_new_volume = tests_utils.create_volume(self.context, size=1,
                                                    host=CONF.host)
        db.volume_update(self.context, fake_volume['id'],
                         {'migration_status': 'non-migrating'})
        self.volume._clean_temporary_volume(self.context, fake_volume['id'],
                                            fake_new_volume['id'])
        volume = db.volume_get(context.get_admin_context(),
                               fake_new_volume['id'])
        self.assertIsNone(volume['migration_status'])

    def test_update_volume_readonly_flag(self):
        """Test volume readonly flag can be updated at API level."""
        # create a volume and assign to host
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        volume['status'] = 'in-use'

        def sort_func(obj):
            return obj['name']

        volume_api = cinder.volume.api.API()

        # Update fails when status != available
        self.assertRaises(exception.InvalidVolume,
                          volume_api.update_readonly_flag,
                          self.context,
                          volume,
                          False)

        volume['status'] = 'available'

        # works when volume in 'available' status
        volume_api.update_readonly_flag(self.context, volume, False)

        volume = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEqual('available', volume['status'])
        admin_metadata = volume['volume_admin_metadata']
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('False', admin_metadata[0]['value'])

        # clean up
        self.volume.delete_volume(self.context, volume['id'])

    def test_secure_file_operations_enabled(self):
        """Test secure file operations setting for base driver.

        General, non network file system based drivers do not have
        anything to do with "secure_file_operations". This test verifies that
        calling the method always returns False.
        """
        ret_flag = self.volume.driver.secure_file_operations_enabled()
        self.assertFalse(ret_flag)

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
                          self.context, test_vol_id,
                          {'volume_properties': self.volume_params},
                          {'retry': {'num_attempts': 1, 'host': []}})
        self.assertTrue(mock_reschedule.called)
        volume = db.volume_get(context.get_admin_context(), test_vol_id)
        self.assertEqual('creating', volume['status'])

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
                          self.context, test_vol_id,
                          {'volume_properties': self.volume_params},
                          {'retry': {'num_attempts': 1, 'host': []}})
        volume = db.volume_get(context.get_admin_context(), test_vol_id)
        self.assertEqual('error', volume['status'])


class VolumeMigrationTestCase(VolumeTestCase):
    def test_migrate_volume_driver(self):
        """Test volume migration done by driver."""
        # stub out driver and rpc functions
        self.stubs.Set(self.volume.driver, 'migrate_volume',
                       lambda x, y, z, new_type_id=None: (True,
                                                          {'user_id': 'foo'}))

        volume = tests_utils.create_volume(self.context, size=0,
                                           host=CONF.host,
                                           migration_status='migrating')
        host_obj = {'host': 'newhost', 'capabilities': {}}
        self.volume.migrate_volume(self.context, volume['id'],
                                   host_obj, False)

        # check volume properties
        volume = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEqual('newhost', volume['host'])
        self.assertEqual('success', volume['migration_status'])

    def _fake_create_volume(self, ctxt, volume, host, req_spec, filters,
                            allow_reschedule=True):
        return db.volume_update(ctxt, volume['id'],
                                {'status': self.expected_status})

    def test_migrate_volume_error(self):
        with mock.patch.object(self.volume.driver, 'migrate_volume') as \
                mock_migrate,\
                mock.patch.object(self.volume.driver, 'create_export') as \
                mock_create_export:

            # Exception case at self.driver.migrate_volume and create_export
            mock_migrate.side_effect = processutils.ProcessExecutionError
            mock_create_export.side_effect = processutils.ProcessExecutionError
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(processutils.ProcessExecutionError,
                              self.volume.migrate_volume,
                              self.context,
                              volume['id'],
                              host_obj,
                              False)
            volume = db.volume_get(context.get_admin_context(), volume['id'])
            self.assertEqual('error', volume['migration_status'])
            self.assertEqual('available', volume['status'])

    @mock.patch('cinder.compute.API')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                'migrate_volume_completion')
    @mock.patch('cinder.db.volume_get')
    def test_migrate_volume_generic(self, volume_get,
                                    migrate_volume_completion,
                                    nova_api):
        fake_volume_id = 'fake_volume_id'
        fake_new_volume = {'status': 'available', 'id': fake_volume_id}
        host_obj = {'host': 'newhost', 'capabilities': {}}
        volume_get.return_value = fake_new_volume
        update_server_volume = nova_api.return_value.update_server_volume
        volume = tests_utils.create_volume(self.context, size=1,
                                           host=CONF.host)
        with mock.patch.object(self.volume, '_copy_volume_data') as \
                mock_copy_volume:
            self.volume._migrate_volume_generic(self.context, volume,
                                                host_obj, None)
            mock_copy_volume.assert_called_with(self.context, volume,
                                                fake_new_volume,
                                                remote='dest')
            migrate_volume_completion.assert_called_with(self.context,
                                                         volume['id'],
                                                         fake_new_volume['id'],
                                                         error=False)
            self.assertFalse(update_server_volume.called)

    @mock.patch('cinder.compute.API')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                'migrate_volume_completion')
    @mock.patch('cinder.db.volume_get')
    def test_migrate_volume_generic_attached_volume(self, volume_get,
                                                    migrate_volume_completion,
                                                    nova_api):
        attached_host = 'some-host'
        fake_volume_id = 'fake_volume_id'
        fake_new_volume = {'status': 'available', 'id': fake_volume_id}
        host_obj = {'host': 'newhost', 'capabilities': {}}
        fake_uuid = fakes.get_fake_uuid()
        update_server_volume = nova_api.return_value.update_server_volume
        volume_get.return_value = fake_new_volume
        volume = tests_utils.create_volume(self.context, size=1,
                                           host=CONF.host)
        volume = tests_utils.attach_volume(self.context, volume['id'],
                                           fake_uuid, attached_host,
                                           '/dev/vda')
        self.assertIsNotNone(volume['volume_attachment'][0]['id'])
        self.assertEqual(fake_uuid,
                         volume['volume_attachment'][0]['instance_uuid'])
        self.assertEqual('in-use', volume['status'])
        self.volume._migrate_volume_generic(self.context, volume,
                                            host_obj, None)
        self.assertFalse(migrate_volume_completion.called)
        update_server_volume.assert_called_with(self.context, fake_uuid,
                                                volume['id'], fake_volume_id)

    @mock.patch.object(volume_rpcapi.VolumeAPI, 'update_migrated_volume')
    @mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume')
    @mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')
    def test_migrate_volume_for_volume_generic(self, create_volume,
                                               rpc_delete_volume,
                                               update_migrated_volume):
        fake_volume = tests_utils.create_volume(self.context, size=1,
                                                host=CONF.host)

        host_obj = {'host': 'newhost', 'capabilities': {}}
        with mock.patch.object(self.volume.driver, 'migrate_volume') as \
                mock_migrate_volume,\
                mock.patch.object(self.volume, '_copy_volume_data'),\
                mock.patch.object(self.volume.driver, 'delete_volume') as \
                delete_volume:
            create_volume.side_effect = self._fake_create_volume
            self.volume.migrate_volume(self.context, fake_volume['id'],
                                       host_obj, True)
            volume = db.volume_get(context.get_admin_context(),
                                   fake_volume['id'])
            self.assertEqual('newhost', volume['host'])
            self.assertEqual('success', volume['migration_status'])
            self.assertFalse(mock_migrate_volume.called)
            self.assertFalse(delete_volume.called)
            self.assertTrue(rpc_delete_volume.called)
            self.assertTrue(update_migrated_volume.called)

    def test_migrate_volume_generic_copy_error(self):
        with mock.patch.object(self.volume.driver, 'migrate_volume'),\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')\
                as mock_create_volume,\
                mock.patch.object(self.volume, '_copy_volume_data') as \
                mock_copy_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume'),\
                mock.patch.object(self.volume, 'migrate_volume_completion'),\
                mock.patch.object(self.volume.driver, 'create_export'):

            # Exception case at migrate_volume_generic
            # source_volume['migration_status'] is 'migrating'
            mock_create_volume.side_effect = self._fake_create_volume
            mock_copy_volume.side_effect = processutils.ProcessExecutionError
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(processutils.ProcessExecutionError,
                              self.volume.migrate_volume,
                              self.context,
                              volume['id'],
                              host_obj,
                              True)
            volume = db.volume_get(context.get_admin_context(), volume['id'])
            self.assertEqual('error', volume['migration_status'])
            self.assertEqual('available', volume['status'])

    @mock.patch('cinder.db.volume_update')
    def test_update_migrated_volume(self, volume_update):
        fake_host = 'fake_host'
        fake_new_host = 'fake_new_host'
        fake_update = {'_name_id': 'updated_id',
                       'provider_location': 'updated_location'}
        fake_elevated = 'fake_elevated'
        volume = tests_utils.create_volume(self.context, size=1,
                                           status='available',
                                           host=fake_host)
        new_volume = tests_utils.create_volume(
            self.context, size=1,
            status='available',
            provider_location='fake_provider_location',
            _name_id='fake_name_id',
            host=fake_new_host)
        new_volume['_name_id'] = 'fake_name_id'
        new_volume['provider_location'] = 'fake_provider_location'
        fake_update_error = {'_name_id': new_volume['_name_id'],
                             'provider_location':
                             new_volume['provider_location']}
        expected_update = {'_name_id': volume['_name_id'],
                           'provider_location': volume['provider_location']}
        with mock.patch.object(self.volume.driver,
                               'update_migrated_volume') as migrate_update,\
                mock.patch.object(self.context, 'elevated') as elevated:
            migrate_update.return_value = fake_update
            elevated.return_value = fake_elevated
            self.volume.update_migrated_volume(self.context, volume,
                                               new_volume, 'available')
            volume_update.assert_has_calls((
                mock.call(fake_elevated, new_volume['id'], expected_update),
                mock.call(fake_elevated, volume['id'], fake_update)))

            # Test the case for update_migrated_volume not implemented
            # for the driver.
            migrate_update.reset_mock()
            volume_update.reset_mock()
            migrate_update.side_effect = NotImplementedError
            self.volume.update_migrated_volume(self.context, volume,
                                               new_volume, 'available')
            volume_update.assert_has_calls((
                mock.call(fake_elevated, new_volume['id'], expected_update),
                mock.call(fake_elevated, volume['id'], fake_update_error)))

    def test_migrate_volume_generic_create_volume_error(self):
        self.expected_status = 'error'

        with mock.patch.object(self.volume.driver, 'migrate_volume'), \
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume') as \
                mock_create_volume, \
                mock.patch.object(self.volume, '_clean_temporary_volume') as \
                clean_temporary_volume:

            # Exception case at the creation of the new temporary volume
            mock_create_volume.side_effect = self._fake_create_volume
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(exception.VolumeMigrationFailed,
                              self.volume.migrate_volume,
                              self.context,
                              volume['id'],
                              host_obj,
                              True)
            volume = db.volume_get(context.get_admin_context(), volume['id'])
            self.assertEqual('error', volume['migration_status'])
            self.assertEqual('available', volume['status'])
            self.assertTrue(clean_temporary_volume.called)
        self.expected_status = 'available'

    def test_migrate_volume_generic_timeout_error(self):
        CONF.set_override("migration_create_volume_timeout_secs", 2)

        with mock.patch.object(self.volume.driver, 'migrate_volume'), \
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume') as \
                mock_create_volume, \
                mock.patch.object(self.volume, '_clean_temporary_volume') as \
                clean_temporary_volume, \
                mock.patch.object(time, 'sleep'):

            # Exception case at the timeout of the volume creation
            self.expected_status = 'creating'
            mock_create_volume.side_effect = self._fake_create_volume
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(exception.VolumeMigrationFailed,
                              self.volume.migrate_volume,
                              self.context,
                              volume['id'],
                              host_obj,
                              True)
            volume = db.volume_get(context.get_admin_context(), volume['id'])
            self.assertEqual('error', volume['migration_status'])
            self.assertEqual('available', volume['status'])
            self.assertTrue(clean_temporary_volume.called)
        self.expected_status = 'available'

    def test_migrate_volume_generic_create_export_error(self):
        with mock.patch.object(self.volume.driver, 'migrate_volume'),\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')\
                as mock_create_volume,\
                mock.patch.object(self.volume, '_copy_volume_data') as \
                mock_copy_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume'),\
                mock.patch.object(self.volume, 'migrate_volume_completion'),\
                mock.patch.object(self.volume.driver, 'create_export') as \
                mock_create_export:

            # Exception case at create_export
            mock_create_volume.side_effect = self._fake_create_volume
            mock_copy_volume.side_effect = processutils.ProcessExecutionError
            mock_create_export.side_effect = processutils.ProcessExecutionError
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(processutils.ProcessExecutionError,
                              self.volume.migrate_volume,
                              self.context,
                              volume['id'],
                              host_obj,
                              True)
            volume = db.volume_get(context.get_admin_context(), volume['id'])
            self.assertEqual('error', volume['migration_status'])
            self.assertEqual('available', volume['status'])

    def test_migrate_volume_generic_migrate_volume_completion_error(self):
        def fake_migrate_volume_completion(ctxt, volume_id, new_volume_id,
                                           error=False):
            db.volume_update(ctxt, volume['id'],
                             {'migration_status': 'completing'})
            raise processutils.ProcessExecutionError

        with mock.patch.object(self.volume.driver, 'migrate_volume'),\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')\
                as mock_create_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume'),\
                mock.patch.object(self.volume, 'migrate_volume_completion')\
                as mock_migrate_compl,\
                mock.patch.object(self.volume.driver, 'create_export'), \
                mock.patch.object(self.volume, '_attach_volume') \
                as mock_attach, \
                mock.patch.object(self.volume, '_detach_volume'), \
                mock.patch.object(os_brick.initiator.connector,
                                  'get_connector_properties') \
                as mock_get_connector_properties, \
                mock.patch.object(volutils, 'copy_volume') as mock_copy, \
                mock.patch.object(volume_rpcapi.VolumeAPI,
                                  'get_capabilities') \
                as mock_get_capabilities:

            # Exception case at delete_volume
            # source_volume['migration_status'] is 'completing'
            mock_create_volume.side_effect = self._fake_create_volume
            mock_migrate_compl.side_effect = fake_migrate_volume_completion
            mock_get_connector_properties.return_value = {}
            mock_attach.side_effect = [{'device': {'path': 'bar'}},
                                       {'device': {'path': 'foo'}}]
            mock_get_capabilities.return_value = {'sparse_copy_volume': True}
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(processutils.ProcessExecutionError,
                              self.volume.migrate_volume,
                              self.context,
                              volume['id'],
                              host_obj,
                              True)
            volume = db.volume_get(context.get_admin_context(), volume['id'])
            self.assertEqual('error', volume['migration_status'])
            self.assertEqual('available', volume['status'])
            mock_copy.assert_called_once_with('foo', 'bar', 0, '1M',
                                              sparse=True)

    def _test_migrate_volume_completion(self, status='available',
                                        instance_uuid=None, attached_host=None,
                                        retyping=False,
                                        previous_status='available'):
        def fake_attach_volume(ctxt, volume, instance_uuid, host_name,
                               mountpoint, mode):
            tests_utils.attach_volume(ctxt, volume['id'],
                                      instance_uuid, host_name,
                                      '/dev/vda')

        initial_status = retyping and 'retyping' or status
        old_volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host,
                                               status=initial_status,
                                               migration_status='migrating',
                                               previous_status=previous_status)
        attachment_id = None
        if status == 'in-use':
            vol = tests_utils.attach_volume(self.context, old_volume['id'],
                                            instance_uuid, attached_host,
                                            '/dev/vda')
            self.assertEqual('in-use', vol['status'])
            attachment_id = vol['volume_attachment'][0]['id']
        target_status = 'target:%s' % old_volume['id']
        new_host = CONF.host + 'new'
        new_volume = tests_utils.create_volume(self.context, size=0,
                                               host=new_host,
                                               migration_status=target_status)
        with mock.patch.object(self.volume, 'detach_volume') as \
                mock_detach_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume') as \
                mock_delete_volume, \
                mock.patch.object(volume_rpcapi.VolumeAPI, 'attach_volume') as \
                mock_attach_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI,
                                  'update_migrated_volume'),\
                mock.patch.object(self.volume.driver, 'attach_volume'):
            mock_attach_volume.side_effect = fake_attach_volume
            self.volume.migrate_volume_completion(self.context, old_volume[
                'id'], new_volume['id'])
            after_new_volume = db.volume_get(self.context, new_volume.id)
            after_old_volume = db.volume_get(self.context, old_volume.id)
            if status == 'in-use':
                mock_detach_volume.assert_called_with(self.context,
                                                      old_volume['id'],
                                                      attachment_id)
                attachment = db.volume_attachment_get_by_instance_uuid(
                    self.context, old_volume['id'], instance_uuid)
                self.assertIsNotNone(attachment)
                self.assertEqual(attached_host, attachment['attached_host'])
                self.assertEqual(instance_uuid, attachment['instance_uuid'])
            else:
                self.assertFalse(mock_detach_volume.called)
            self.assertTrue(mock_delete_volume.called)
            self.assertEqual(old_volume.host, after_new_volume.host)
            self.assertEqual(new_volume.host, after_old_volume.host)

    def test_migrate_volume_completion_retype_available(self):
        self._test_migrate_volume_completion('available', retyping=True)

    def test_migrate_volume_completion_retype_in_use(self):
        self._test_migrate_volume_completion(
            'in-use',
            '83c969d5-065e-4c9c-907d-5394bc2e98e2',
            'some-host',
            retyping=True,
            previous_status='in-use')

    def test_migrate_volume_completion_migrate_available(self):
        self._test_migrate_volume_completion()

    def test_migrate_volume_completion_migrate_in_use(self):
        self._test_migrate_volume_completion(
            'in-use',
            '83c969d5-065e-4c9c-907d-5394bc2e98e2',
            'some-host',
            retyping=False,
            previous_status='in-use')

    def test_retype_setup_fail_volume_is_available(self):
        """Verify volume is still available if retype prepare failed."""
        elevated = context.get_admin_context()
        project_id = self.context.project_id

        db.volume_type_create(elevated, {'name': 'old', 'extra_specs': {}})
        old_vol_type = db.volume_type_get_by_name(elevated, 'old')
        db.volume_type_create(elevated, {'name': 'new', 'extra_specs': {}})
        new_vol_type = db.volume_type_get_by_name(elevated, 'new')
        db.quota_create(elevated, project_id, 'volumes_new', 0)

        volume = tests_utils.create_volume(self.context, size=1,
                                           host=CONF.host, status='available',
                                           volume_type_id=old_vol_type['id'])

        api = cinder.volume.api.API()
        self.assertRaises(exception.VolumeLimitExceeded, api.retype,
                          self.context, volume, new_vol_type['id'])

        volume = db.volume_get(elevated, volume.id)
        self.assertEqual('available', volume['status'])

    def _retype_volume_exec(self, driver, snap=False, policy='on-demand',
                            migrate_exc=False, exc=None, diff_equal=False,
                            replica=False):
        elevated = context.get_admin_context()
        project_id = self.context.project_id

        db.volume_type_create(elevated, {'name': 'old', 'extra_specs': {}})
        old_vol_type = db.volume_type_get_by_name(elevated, 'old')
        db.volume_type_create(elevated, {'name': 'new', 'extra_specs': {}})
        vol_type = db.volume_type_get_by_name(elevated, 'new')
        db.quota_create(elevated, project_id, 'volumes_new', 10)

        if replica:
            rep_status = 'active'
        else:
            rep_status = 'disabled'
        volume = tests_utils.create_volume(self.context, size=1,
                                           host=CONF.host, status='retyping',
                                           volume_type_id=old_vol_type['id'],
                                           replication_status=rep_status)
        volume['previous_status'] = 'available'
        if snap:
            self._create_snapshot(volume['id'], size=volume['size'])
        if driver or diff_equal:
            host_obj = {'host': CONF.host, 'capabilities': {}}
        else:
            host_obj = {'host': 'newhost', 'capabilities': {}}

        reserve_opts = {'volumes': 1, 'gigabytes': volume['size']}
        QUOTAS.add_volume_type_opts(self.context,
                                    reserve_opts,
                                    vol_type['id'])
        reservations = QUOTAS.reserve(self.context,
                                      project_id=project_id,
                                      **reserve_opts)

        with mock.patch.object(self.volume.driver, 'retype') as _retype,\
                mock.patch.object(volume_types, 'volume_types_diff') as _diff,\
                mock.patch.object(self.volume, 'migrate_volume') as _mig,\
                mock.patch.object(db, 'volume_get') as get_volume:
            get_volume.return_value = volume
            _retype.return_value = driver
            _diff.return_value = ({}, diff_equal)
            if migrate_exc:
                _mig.side_effect = KeyError
            else:
                _mig.return_value = True

            if not exc:
                self.volume.retype(self.context, volume['id'],
                                   vol_type['id'], host_obj,
                                   migration_policy=policy,
                                   reservations=reservations)
            else:
                self.assertRaises(exc, self.volume.retype,
                                  self.context, volume['id'],
                                  vol_type['id'], host_obj,
                                  migration_policy=policy,
                                  reservations=reservations)
            get_volume.assert_called_once_with(self.context, volume['id'])

        # get volume/quota properties
        volume = db.volume_get(elevated, volume['id'])
        try:
            usage = db.quota_usage_get(elevated, project_id, 'volumes_new')
            volumes_in_use = usage.in_use
        except exception.QuotaUsageNotFound:
            volumes_in_use = 0

        # check properties
        if driver or diff_equal:
            self.assertEqual(vol_type['id'], volume['volume_type_id'])
            self.assertEqual('available', volume['status'])
            self.assertEqual(CONF.host, volume['host'])
            self.assertEqual(1, volumes_in_use)
        elif not exc:
            self.assertEqual(old_vol_type['id'], volume['volume_type_id'])
            self.assertEqual('retyping', volume['status'])
            self.assertEqual(CONF.host, volume['host'])
            self.assertEqual(1, volumes_in_use)
        else:
            self.assertEqual(old_vol_type['id'], volume['volume_type_id'])
            self.assertEqual('available', volume['status'])
            self.assertEqual(CONF.host, volume['host'])
            self.assertEqual(0, volumes_in_use)

    def test_retype_volume_driver_success(self):
        self._retype_volume_exec(True)

    def test_retype_volume_migration_bad_policy(self):
        # Test volume retype that requires migration by not allowed
        self._retype_volume_exec(False, policy='never',
                                 exc=exception.VolumeMigrationFailed)

    def test_retype_volume_migration_with_replica(self):
        self._retype_volume_exec(False,
                                 replica=True,
                                 exc=exception.InvalidVolume)

    def test_retype_volume_migration_with_snaps(self):
        self._retype_volume_exec(False, snap=True, exc=exception.InvalidVolume)

    def test_retype_volume_migration_failed(self):
        self._retype_volume_exec(False, migrate_exc=True, exc=KeyError)

    def test_retype_volume_migration_success(self):
        self._retype_volume_exec(False, migrate_exc=False, exc=None)

    def test_retype_volume_migration_equal_types(self):
        self._retype_volume_exec(False, diff_equal=True)

    def test_migrate_driver_not_initialized(self):
        volume = tests_utils.create_volume(self.context, size=0,
                                           host=CONF.host)
        host_obj = {'host': 'newhost', 'capabilities': {}}

        self.volume.driver._initialized = False
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.migrate_volume,
                          self.context, volume['id'],
                          host_obj, True)

        volume = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEqual('error', volume.migration_status)

        # lets cleanup the mess.
        self.volume.driver._initialized = True
        self.volume.delete_volume(self.context, volume['id'])

    def test_delete_source_volume_in_migration(self):
        """Test deleting a source volume that is in migration."""
        self._test_delete_volume_in_migration('migrating')

    def test_delete_destination_volume_in_migration(self):
        """Test deleting a destination volume that is in migration."""
        self._test_delete_volume_in_migration('target:vol-id')

    def _test_delete_volume_in_migration(self, migration_status):
        """Test deleting a volume that is in migration."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume = db.volume_update(self.context, volume['id'],
                                  {'status': 'available',
                                   'migration_status': migration_status})
        self.volume.delete_volume(self.context, volume['id'])

        # The volume is successfully removed during the volume delete
        # and won't exist in the database any more.
        self.assertRaises(exception.VolumeNotFound, db.volume_get,
                          self.context, volume['id'])


class ConsistencyGroupTestCase(BaseVolumeTestCase):
    def test_delete_volume_in_consistency_group(self):
        """Test deleting a volume that's tied to a consistency group fails."""
        volume_api = cinder.volume.api.API()
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        consistencygroup_id = '12345678-1234-5678-1234-567812345678'
        volume = db.volume_update(self.context, volume['id'],
                                  {'status': 'available',
                                   'consistencygroup_id': consistencygroup_id})
        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete, self.context, volume)

    @mock.patch.object(CGQUOTAS, "reserve",
                       return_value=["RESERVATION"])
    @mock.patch.object(CGQUOTAS, "commit")
    @mock.patch.object(CGQUOTAS, "rollback")
    @mock.patch.object(driver.VolumeDriver,
                       "delete_consistencygroup",
                       return_value=({'status': 'deleted'}, []))
    def test_create_delete_consistencygroup(self, fake_delete_cg,
                                            fake_rollback,
                                            fake_commit, fake_reserve):
        """Test consistencygroup can be created and deleted."""

        def fake_driver_create_cg(context, group):
            """Make sure that the pool is part of the host."""
            self.assertIn('host', group)
            host = group.host
            pool = volutils.extract_host(host, level='pool')
            self.assertEqual('fakepool', pool)
            return {'status': 'available'}

        self.stubs.Set(self.volume.driver, 'create_consistencygroup',
                       fake_driver_create_cg)

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            host='fakehost@fakedrv#fakepool')
        group = objects.ConsistencyGroup.get_by_id(self.context, group.id)
        self.assertEqual(0, len(self.notifier.notifications),
                         self.notifier.notifications)
        self.volume.create_consistencygroup(self.context, group)
        self.assertEqual(2, len(self.notifier.notifications),
                         self.notifier.notifications)
        msg = self.notifier.notifications[0]
        self.assertEqual('consistencygroup.create.start', msg['event_type'])
        expected = {
            'status': 'available',
            'name': 'test_cg',
            'availability_zone': 'nova',
            'tenant_id': self.context.project_id,
            'created_at': 'DONTCARE',
            'user_id': 'fake',
            'consistencygroup_id': group.id
        }
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[1]
        self.assertEqual('consistencygroup.create.end', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        self.assertEqual(
            group.id,
            objects.ConsistencyGroup.get_by_id(context.get_admin_context(),
                                               group.id).id)

        self.volume.delete_consistencygroup(self.context, group)
        cg = objects.ConsistencyGroup.get_by_id(
            context.get_admin_context(read_deleted='yes'), group.id)
        self.assertEqual('deleted', cg.status)
        self.assertEqual(4, len(self.notifier.notifications),
                         self.notifier.notifications)
        msg = self.notifier.notifications[2]
        self.assertEqual('consistencygroup.delete.start', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[3]
        self.assertEqual('consistencygroup.delete.end', msg['event_type'])
        expected['status'] = 'deleted'
        self.assertDictMatch(expected, msg['payload'])
        self.assertRaises(exception.NotFound,
                          objects.ConsistencyGroup.get_by_id,
                          self.context,
                          group.id)

    @mock.patch.object(CGQUOTAS, "reserve",
                       return_value=["RESERVATION"])
    @mock.patch.object(CGQUOTAS, "commit")
    @mock.patch.object(CGQUOTAS, "rollback")
    @mock.patch.object(driver.VolumeDriver,
                       "create_consistencygroup",
                       return_value={'status': 'available'})
    @mock.patch.object(driver.VolumeDriver,
                       "update_consistencygroup")
    def test_update_consistencygroup(self, fake_update_cg,
                                     fake_create_cg, fake_rollback,
                                     fake_commit, fake_reserve):
        """Test consistencygroup can be updated."""
        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')
        self.volume.create_consistencygroup(self.context, group)

        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group.id,
            **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        volume2 = tests_utils.create_volume(
            self.context,
            consistencygroup_id=None,
            **self.volume_params)
        volume_id2 = volume2['id']
        self.volume.create_volume(self.context, volume_id2)

        fake_update_cg.return_value = (
            {'status': 'available'},
            [{'id': volume_id2, 'status': 'available'}],
            [{'id': volume_id, 'status': 'available'}])

        self.volume.update_consistencygroup(self.context, group,
                                            add_volumes=volume_id2,
                                            remove_volumes=volume_id)
        cg = objects.ConsistencyGroup.get_by_id(self.context, group.id)
        expected = {
            'status': 'available',
            'name': 'test_cg',
            'availability_zone': 'nova',
            'tenant_id': self.context.project_id,
            'created_at': 'DONTCARE',
            'user_id': 'fake',
            'consistencygroup_id': group.id
        }
        self.assertEqual('available', cg.status)
        self.assertEqual(10, len(self.notifier.notifications),
                         self.notifier.notifications)
        msg = self.notifier.notifications[6]
        self.assertEqual('consistencygroup.update.start', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[8]
        self.assertEqual('consistencygroup.update.end', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        cgvolumes = db.volume_get_all_by_group(self.context, group.id)
        cgvol_ids = [cgvol['id'] for cgvol in cgvolumes]
        # Verify volume is removed.
        self.assertNotIn(volume_id, cgvol_ids)
        # Verify volume is added.
        self.assertIn(volume_id2, cgvol_ids)

        self.volume_params['status'] = 'wrong-status'
        volume3 = tests_utils.create_volume(
            self.context,
            consistencygroup_id=None,
            **self.volume_params)
        volume_id3 = volume3['id']

        volume_get_orig = self.volume.db.volume_get
        self.volume.db.volume_get = mock.Mock(
            return_value={'status': 'wrong_status',
                          'id': volume_id3})
        # Try to add a volume in wrong status
        self.assertRaises(exception.InvalidVolume,
                          self.volume.update_consistencygroup,
                          self.context,
                          group,
                          add_volumes=volume_id3,
                          remove_volumes=None)
        self.volume.db.volume_get.reset_mock()
        self.volume.db.volume_get = volume_get_orig

    @mock.patch.object(driver.VolumeDriver,
                       "create_consistencygroup",
                       return_value={'status': 'available'})
    @mock.patch.object(driver.VolumeDriver,
                       "delete_consistencygroup",
                       return_value=({'status': 'deleted'}, []))
    @mock.patch.object(driver.VolumeDriver,
                       "create_cgsnapshot",
                       return_value={'status': 'available'})
    @mock.patch.object(driver.VolumeDriver,
                       "delete_cgsnapshot",
                       return_value=({'status': 'deleted'}, []))
    @mock.patch.object(driver.VolumeDriver,
                       "create_consistencygroup_from_src",
                       return_value=(None, None))
    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'create_volume_from_snapshot')
    @mock.patch('cinder.volume.drivers.lvm.LVMVolumeDriver.'
                'create_cloned_volume')
    def test_create_consistencygroup_from_src(self,
                                              mock_create_cloned_vol,
                                              mock_create_vol_from_snap,
                                              mock_create_from_src,
                                              mock_delete_cgsnap,
                                              mock_create_cgsnap,
                                              mock_delete_cg,
                                              mock_create_cg):
        """Test consistencygroup can be created and deleted."""
        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            status='available')
        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group.id,
            status='available',
            host=CONF.host,
            size=1)
        volume_id = volume['id']
        cgsnapshot_returns = self._create_cgsnapshot(group.id, volume_id)
        cgsnapshot = cgsnapshot_returns[0]
        snapshot_id = cgsnapshot_returns[1]['id']

        # Create CG from source CG snapshot.
        group2 = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            cgsnapshot_id=cgsnapshot.id)
        group2 = objects.ConsistencyGroup.get_by_id(self.context, group2.id)
        volume2 = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group2.id,
            snapshot_id=snapshot_id,
            **self.volume_params)
        volume2_id = volume2['id']
        self.volume.create_volume(self.context, volume2_id)
        self.volume.create_consistencygroup_from_src(
            self.context, group2, cgsnapshot=cgsnapshot)
        cg2 = objects.ConsistencyGroup.get_by_id(self.context, group2.id)
        expected = {
            'status': 'available',
            'name': 'test_cg',
            'availability_zone': 'nova',
            'tenant_id': self.context.project_id,
            'created_at': 'DONTCARE',
            'user_id': 'fake',
            'consistencygroup_id': group2.id,
        }
        self.assertEqual('available', cg2.status)
        self.assertEqual(group2.id, cg2['id'])
        self.assertEqual(cgsnapshot.id, cg2['cgsnapshot_id'])
        self.assertIsNone(cg2['source_cgid'])

        msg = self.notifier.notifications[2]
        self.assertEqual('consistencygroup.create.start', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[4]
        self.assertEqual('consistencygroup.create.end', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])

        if len(self.notifier.notifications) > 6:
            self.assertFalse(self.notifier.notifications[6],
                             self.notifier.notifications)
        self.assertEqual(6, len(self.notifier.notifications),
                         self.notifier.notifications)

        self.volume.delete_consistencygroup(self.context, group2)

        if len(self.notifier.notifications) > 10:
            self.assertFalse(self.notifier.notifications[10],
                             self.notifier.notifications)
        self.assertEqual(10, len(self.notifier.notifications),
                         self.notifier.notifications)

        msg = self.notifier.notifications[6]
        self.assertEqual('consistencygroup.delete.start', msg['event_type'])
        expected['status'] = 'available'
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[8]
        self.assertEqual('consistencygroup.delete.end', msg['event_type'])
        expected['status'] = 'deleted'
        self.assertDictMatch(expected, msg['payload'])

        cg2 = objects.ConsistencyGroup.get_by_id(
            context.get_admin_context(read_deleted='yes'), group2.id)
        self.assertEqual('deleted', cg2.status)
        self.assertRaises(exception.NotFound,
                          objects.ConsistencyGroup.get_by_id,
                          self.context,
                          group2.id)

        # Create CG from source CG.
        group3 = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            source_cgid=group.id)
        volume3 = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group3.id,
            source_volid=volume_id,
            **self.volume_params)
        volume3_id = volume3['id']
        self.volume.create_volume(self.context, volume3_id)
        self.volume.create_consistencygroup_from_src(
            self.context, group3, source_cg=group)

        cg3 = objects.ConsistencyGroup.get_by_id(self.context, group3.id)

        self.assertEqual('available', cg3.status)
        self.assertEqual(group3.id, cg3.id)
        self.assertEqual(group.id, cg3.source_cgid)
        self.assertIsNone(cg3.cgsnapshot_id)

        self.volume.delete_cgsnapshot(self.context, cgsnapshot)

        self.volume.delete_consistencygroup(self.context, group)

    def test_sort_snapshots(self):
        vol1 = {'id': '1', 'name': 'volume 1',
                'snapshot_id': '1',
                'consistencygroup_id': '1'}
        vol2 = {'id': '2', 'name': 'volume 2',
                'snapshot_id': '2',
                'consistencygroup_id': '1'}
        vol3 = {'id': '3', 'name': 'volume 3',
                'snapshot_id': '3',
                'consistencygroup_id': '1'}
        snp1 = {'id': '1', 'name': 'snap 1',
                'cgsnapshot_id': '1'}
        snp2 = {'id': '2', 'name': 'snap 2',
                'cgsnapshot_id': '1'}
        snp3 = {'id': '3', 'name': 'snap 3',
                'cgsnapshot_id': '1'}
        snp1_obj = fake_snapshot.fake_snapshot_obj(self.context, **snp1)
        snp2_obj = fake_snapshot.fake_snapshot_obj(self.context, **snp2)
        snp3_obj = fake_snapshot.fake_snapshot_obj(self.context, **snp3)
        volumes = []
        snapshots = []
        volumes.append(vol1)
        volumes.append(vol2)
        volumes.append(vol3)
        snapshots.append(snp2_obj)
        snapshots.append(snp3_obj)
        snapshots.append(snp1_obj)
        i = 0
        for vol in volumes:
            snap = snapshots[i]
            i += 1
            self.assertNotEqual(vol['snapshot_id'], snap.id)
        sorted_snaps = self.volume._sort_snapshots(volumes, snapshots)
        i = 0
        for vol in volumes:
            snap = sorted_snaps[i]
            i += 1
            self.assertEqual(vol['snapshot_id'], snap.id)

        snapshots[2]['id'] = '9999'
        self.assertRaises(exception.SnapshotNotFound,
                          self.volume._sort_snapshots,
                          volumes, snapshots)

        self.assertRaises(exception.InvalidInput,
                          self.volume._sort_snapshots,
                          volumes, [])

    def test_sort_source_vols(self):
        vol1 = {'id': '1', 'name': 'volume 1',
                'source_volid': '1',
                'consistencygroup_id': '2'}
        vol2 = {'id': '2', 'name': 'volume 2',
                'source_volid': '2',
                'consistencygroup_id': '2'}
        vol3 = {'id': '3', 'name': 'volume 3',
                'source_volid': '3',
                'consistencygroup_id': '2'}
        src_vol1 = {'id': '1', 'name': 'source vol 1',
                    'consistencygroup_id': '1'}
        src_vol2 = {'id': '2', 'name': 'source vol 2',
                    'consistencygroup_id': '1'}
        src_vol3 = {'id': '3', 'name': 'source vol 3',
                    'consistencygroup_id': '1'}
        volumes = []
        src_vols = []
        volumes.append(vol1)
        volumes.append(vol2)
        volumes.append(vol3)
        src_vols.append(src_vol2)
        src_vols.append(src_vol3)
        src_vols.append(src_vol1)
        i = 0
        for vol in volumes:
            src_vol = src_vols[i]
            i += 1
            self.assertNotEqual(vol['source_volid'], src_vol['id'])
        sorted_src_vols = self.volume._sort_source_vols(volumes, src_vols)
        i = 0
        for vol in volumes:
            src_vol = sorted_src_vols[i]
            i += 1
            self.assertEqual(vol['source_volid'], src_vol['id'])

        src_vols[2]['id'] = '9999'
        self.assertRaises(exception.VolumeNotFound,
                          self.volume._sort_source_vols,
                          volumes, src_vols)

        self.assertRaises(exception.InvalidInput,
                          self.volume._sort_source_vols,
                          volumes, [])

    def _create_cgsnapshot(self, group_id, volume_id, size='0'):
        """Create a cgsnapshot object."""
        cgsnap = objects.CGSnapshot(self.context)
        cgsnap.user_id = 'fake'
        cgsnap.project_id = 'fake'
        cgsnap.consistencygroup_id = group_id
        cgsnap.status = "creating"
        cgsnap.create()

        # Create a snapshot object
        snap = objects.Snapshot(context.get_admin_context())
        snap.volume_size = size
        snap.user_id = 'fake'
        snap.project_id = 'fake'
        snap.volume_id = volume_id
        snap.status = "available"
        snap.cgsnapshot_id = cgsnap.id
        snap.create()

        return cgsnap, snap

    @mock.patch('cinder.volume.driver.VolumeDriver.create_consistencygroup',
                autospec=True,
                return_value={'status': 'available'})
    @mock.patch('cinder.volume.driver.VolumeDriver.delete_consistencygroup',
                autospec=True,
                return_value=({'status': 'deleted'}, []))
    @mock.patch('cinder.volume.driver.VolumeDriver.create_cgsnapshot',
                autospec=True,
                return_value=({'status': 'available'}, []))
    @mock.patch('cinder.volume.driver.VolumeDriver.delete_cgsnapshot',
                autospec=True,
                return_value=({'status': 'deleted'}, []))
    def test_create_delete_cgsnapshot(self,
                                      mock_del_cgsnap, mock_create_cgsnap,
                                      mock_del_cg, _mock_create_cg):
        """Test cgsnapshot can be created and deleted."""

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')
        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group.id,
            **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        if len(self.notifier.notifications) > 2:
            self.assertFalse(self.notifier.notifications[2],
                             self.notifier.notifications)
        self.assertEqual(2, len(self.notifier.notifications),
                         self.notifier.notifications)

        cgsnapshot_returns = self._create_cgsnapshot(group.id, volume_id)
        cgsnapshot = cgsnapshot_returns[0]
        self.volume.create_cgsnapshot(self.context, cgsnapshot)
        self.assertEqual(cgsnapshot.id,
                         objects.CGSnapshot.get_by_id(
                             context.get_admin_context(),
                             cgsnapshot.id).id)

        if len(self.notifier.notifications) > 6:
            self.assertFalse(self.notifier.notifications[6],
                             self.notifier.notifications)

        msg = self.notifier.notifications[2]
        self.assertEqual('cgsnapshot.create.start', msg['event_type'])
        expected = {
            'created_at': 'DONTCARE',
            'name': None,
            'cgsnapshot_id': cgsnapshot.id,
            'status': 'creating',
            'tenant_id': 'fake',
            'user_id': 'fake',
            'consistencygroup_id': group.id
        }
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[3]
        self.assertEqual('snapshot.create.start', msg['event_type'])
        msg = self.notifier.notifications[4]
        expected['status'] = 'available'
        self.assertEqual('cgsnapshot.create.end', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[5]
        self.assertEqual('snapshot.create.end', msg['event_type'])

        self.assertEqual(6, len(self.notifier.notifications),
                         self.notifier.notifications)

        self.volume.delete_cgsnapshot(self.context, cgsnapshot)

        if len(self.notifier.notifications) > 10:
            self.assertFalse(self.notifier.notifications[10],
                             self.notifier.notifications)

        msg = self.notifier.notifications[6]
        self.assertEqual('cgsnapshot.delete.start', msg['event_type'])
        expected['status'] = 'available'
        self.assertDictMatch(expected, msg['payload'])
        msg = self.notifier.notifications[8]
        self.assertEqual('cgsnapshot.delete.end', msg['event_type'])
        expected['status'] = 'deleted'
        self.assertDictMatch(expected, msg['payload'])

        self.assertEqual(10, len(self.notifier.notifications),
                         self.notifier.notifications)

        cgsnap = objects.CGSnapshot.get_by_id(
            context.get_admin_context(read_deleted='yes'),
            cgsnapshot.id)
        self.assertEqual('deleted', cgsnap.status)
        self.assertRaises(exception.NotFound,
                          objects.CGSnapshot.get_by_id,
                          self.context,
                          cgsnapshot.id)

        self.volume.delete_consistencygroup(self.context, group)

        self.assertTrue(mock_create_cgsnap.called)
        self.assertTrue(mock_del_cgsnap.called)
        self.assertTrue(mock_del_cg.called)

    @mock.patch('cinder.volume.driver.VolumeDriver.create_consistencygroup',
                return_value={'status': 'available'})
    @mock.patch('cinder.volume.driver.VolumeDriver.delete_consistencygroup',
                return_value=({'status': 'deleted'}, []))
    def test_delete_consistencygroup_correct_host(self,
                                                  mock_del_cg,
                                                  _mock_create_cg):
        """Test consistencygroup can be deleted.

        Test consistencygroup can be deleted when volumes are on
        the correct volume node.
        """

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')

        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group.id,
            host='host1@backend1#pool1',
            status='creating',
            size=1)
        self.volume.host = 'host1@backend1'
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        self.volume.delete_consistencygroup(self.context, group)
        cg = objects.ConsistencyGroup.get_by_id(
            context.get_admin_context(read_deleted='yes'),
            group.id)
        self.assertEqual('deleted', cg.status)
        self.assertRaises(exception.NotFound,
                          objects.ConsistencyGroup.get_by_id,
                          self.context,
                          group.id)

        self.assertTrue(mock_del_cg.called)

    @mock.patch('cinder.volume.driver.VolumeDriver.create_consistencygroup',
                return_value={'status': 'available'})
    def test_delete_consistencygroup_wrong_host(self, *_mock_create_cg):
        """Test consistencygroup cannot be deleted.

        Test consistencygroup cannot be deleted when volumes in the
        group are not local to the volume node.
        """

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')

        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group.id,
            host='host1@backend1#pool1',
            status='creating',
            size=1)
        self.volume.host = 'host1@backend2'
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        self.assertRaises(exception.InvalidVolume,
                          self.volume.delete_consistencygroup,
                          self.context,
                          group)
        cg = objects.ConsistencyGroup.get_by_id(self.context, group.id)
        # Group is not deleted
        self.assertEqual('available', cg.status)

    def test_create_volume_with_consistencygroup_invalid_type(self):
        """Test volume creation with ConsistencyGroup & invalid volume type."""
        vol_type = db.volume_type_create(
            context.get_admin_context(),
            dict(name=conf_fixture.def_vol_type, extra_specs={})
        )
        db_vol_type = db.volume_type_get(context.get_admin_context(),
                                         vol_type.id)
        cg = {
            'id': '1',
            'name': 'cg1',
            'volume_type_id': db_vol_type['id'],
        }
        fake_type = {
            'id': '9999',
            'name': 'fake',
        }
        vol_api = cinder.volume.api.API()

        # Volume type must be provided when creating a volume in a
        # consistency group.
        self.assertRaises(exception.InvalidInput,
                          vol_api.create,
                          self.context, 1, 'vol1', 'volume 1',
                          consistencygroup=cg)

        # Volume type must be valid.
        self.assertRaises(exception.InvalidInput,
                          vol_api.create,
                          self.context, 1, 'vol1', 'volume 1',
                          volume_type=fake_type,
                          consistencygroup=cg)

    @mock.patch.object(fake_driver.FakeISCSIDriver, 'get_volume_stats')
    @mock.patch.object(driver.BaseVD, '_init_vendor_properties')
    def test_get_capabilities(self, mock_init_vendor, mock_get_volume_stats):
        stats = {
            'volume_backend_name': 'lvm',
            'vendor_name': 'Open Source',
            'storage_protocol': 'iSCSI',
            'vendor_prefix': 'abcd'
        }
        expected = stats.copy()
        expected['properties'] = {
            'compression': {
                'title': 'Compression',
                'description': 'Enables compression.',
                'type': 'boolean'},
            'qos': {
                'title': 'QoS',
                'description': 'Enables QoS.',
                'type': 'boolean'},
            'replication': {
                'title': 'Replication',
                'description': 'Enables replication.',
                'type': 'boolean'},
            'thin_provisioning': {
                'title': 'Thin Provisioning',
                'description': 'Sets thin provisioning.',
                'type': 'boolean'},
        }

        # Test to get updated capabilities
        discover = True
        mock_get_volume_stats.return_value = stats
        mock_init_vendor.return_value = ({}, None)
        capabilities = self.volume.get_capabilities(self.context,
                                                    discover)
        self.assertEqual(expected, capabilities)
        mock_get_volume_stats.assert_called_once_with(True)

        # Test to get existing original capabilities
        mock_get_volume_stats.reset_mock()
        discover = False
        capabilities = self.volume.get_capabilities(self.context,
                                                    discover)
        self.assertEqual(expected, capabilities)
        self.assertFalse(mock_get_volume_stats.called)

        # Normal test case to get vendor unique capabilities
        def init_vendor_properties(self):
            properties = {}
            self._set_property(
                properties,
                "abcd:minIOPS",
                "Minimum IOPS QoS",
                "Sets minimum IOPS if QoS is enabled.",
                "integer",
                minimum=10,
                default=100)
            return properties, 'abcd'

        expected['properties'].update(
            {'abcd:minIOPS': {
                'title': 'Minimum IOPS QoS',
                'description': 'Sets minimum IOPS if QoS is enabled.',
                'type': 'integer',
                'minimum': 10,
                'default': 100}})

        mock_get_volume_stats.reset_mock()
        mock_init_vendor.reset_mock()
        discover = True
        mock_init_vendor.return_value = (
            init_vendor_properties(self.volume.driver))
        capabilities = self.volume.get_capabilities(self.context,
                                                    discover)
        self.assertEqual(expected, capabilities)
        self.assertTrue(mock_get_volume_stats.called)

    @mock.patch.object(fake_driver.FakeISCSIDriver, 'get_volume_stats')
    @mock.patch.object(driver.BaseVD, '_init_vendor_properties')
    @mock.patch.object(driver.BaseVD, '_init_standard_capabilities')
    def test_get_capabilities_prefix_error(self, mock_init_standard,
                                           mock_init_vendor,
                                           mock_get_volume_stats):

        # Error test case: propety does not match vendor prefix
        def init_vendor_properties(self):
            properties = {}
            self._set_property(
                properties,
                "aaa:minIOPS",
                "Minimum IOPS QoS",
                "Sets minimum IOPS if QoS is enabled.",
                "integer")
            self._set_property(
                properties,
                "abcd:compression_type",
                "Compression type",
                "Specifies compression type.",
                "string")

            return properties, 'abcd'

        expected = {
            'abcd:compression_type': {
                'title': 'Compression type',
                'description': 'Specifies compression type.',
                'type': 'string'}}

        discover = True
        mock_get_volume_stats.return_value = {}
        mock_init_standard.return_value = {}
        mock_init_vendor.return_value = (
            init_vendor_properties(self.volume.driver))
        capabilities = self.volume.get_capabilities(self.context,
                                                    discover)
        self.assertEqual(expected, capabilities['properties'])

    @mock.patch.object(fake_driver.FakeISCSIDriver, 'get_volume_stats')
    @mock.patch.object(driver.BaseVD, '_init_vendor_properties')
    @mock.patch.object(driver.BaseVD, '_init_standard_capabilities')
    def test_get_capabilities_fail_override(self, mock_init_standard,
                                            mock_init_vendor,
                                            mock_get_volume_stats):

        # Error test case: propety cannot override any standard capabilities
        def init_vendor_properties(self):
            properties = {}
            self._set_property(
                properties,
                "qos",
                "Minimum IOPS QoS",
                "Sets minimum IOPS if QoS is enabled.",
                "integer")
            self._set_property(
                properties,
                "ab::cd:compression_type",
                "Compression type",
                "Specifies compression type.",
                "string")

            return properties, 'ab::cd'

        expected = {
            'ab__cd:compression_type': {
                'title': 'Compression type',
                'description': 'Specifies compression type.',
                'type': 'string'}}

        discover = True
        mock_get_volume_stats.return_value = {}
        mock_init_standard.return_value = {}
        mock_init_vendor.return_value = (
            init_vendor_properties(self.volume.driver))
        capabilities = self.volume.get_capabilities(self.context,
                                                    discover)
        self.assertEqual(expected, capabilities['properties'])

    def test_delete_encryptied_volume(self):
        self.volume_params['status'] = 'active'
        volume = tests_utils.create_volume(self.context,
                                           **self.volume_params)
        vol_api = cinder.volume.api.API()
        with mock.patch.object(
                vol_api.key_manager,
                'delete_key',
                side_effect=Exception):
            self.assertRaises(exception.InvalidVolume,
                              vol_api.delete,
                              self.context, volume)


class CopyVolumeToImageTestCase(BaseVolumeTestCase):
    def fake_local_path(self, volume):
        return self.dst_path

    def setUp(self):
        super(CopyVolumeToImageTestCase, self).setUp()
        self.dst_fd, self.dst_path = tempfile.mkstemp()
        self.addCleanup(os.unlink, self.dst_path)

        os.close(self.dst_fd)
        self.stubs.Set(self.volume.driver, 'local_path', self.fake_local_path)
        self.image_id = '70a599e0-31e7-49b7-b260-868f441e862b'
        self.image_meta = {
            'id': self.image_id,
            'container_format': 'bare',
            'disk_format': 'raw'
        }
        self.volume_id = 1
        self.addCleanup(db.volume_destroy, self.context, self.volume_id)

        self.volume_attrs = {
            'id': self.volume_id,
            'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
            'display_description': 'Test Desc',
            'size': 20,
            'status': 'uploading',
            'host': 'dummy'
        }

    def test_copy_volume_to_image_status_available(self):
        # creating volume testdata
        self.volume_attrs['instance_uuid'] = None
        db.volume_create(self.context, self.volume_attrs)

        # start test
        self.volume.copy_volume_to_image(self.context,
                                         self.volume_id,
                                         self.image_meta)

        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume['status'])

    def test_copy_volume_to_image_instance_deleted(self):
        # During uploading volume to image if instance is deleted,
        # volume should be in available status.
        self.image_meta['id'] = 'a440c04b-79fa-479c-bed1-0b816eaec379'
        # Creating volume testdata
        self.volume_attrs['instance_uuid'] = 'b21f957d-a72f-4b93-b5a5-' \
                                             '45b1161abb02'
        db.volume_create(self.context, self.volume_attrs)

        # Storing unmocked db api function reference here, because we have to
        # update volume status (set instance_uuid to None) before calling the
        # 'volume_update_status_based_on_attached_instance_id' db api.
        unmocked_db_api = db.volume_update_status_based_on_attachment

        def mock_volume_update_after_upload(context, volume_id):
            # First update volume and set 'instance_uuid' to None
            # because after deleting instance, instance_uuid of volume is
            # set to None
            db.volume_update(context, volume_id, {'instance_uuid': None})
            # Calling unmocked db api
            unmocked_db_api(context, volume_id)

        with mock.patch.object(
                db,
                'volume_update_status_based_on_attachment',
                side_effect=mock_volume_update_after_upload) as mock_update:

            # Start test
            self.volume.copy_volume_to_image(self.context,
                                             self.volume_id,
                                             self.image_meta)
            # Check 'volume_update_status_after_copy_volume_to_image'
            # is called 1 time
            self.assertEqual(1, mock_update.call_count)

        # Check volume status has changed to available because
        # instance is deleted
        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume['status'])

    def test_copy_volume_to_image_status_use(self):
        self.image_meta['id'] = 'a440c04b-79fa-479c-bed1-0b816eaec379'
        # creating volume testdata
        db.volume_create(self.context, self.volume_attrs)

        # start test
        self.volume.copy_volume_to_image(self.context,
                                         self.volume_id,
                                         self.image_meta)

        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume['status'])

    def test_copy_volume_to_image_exception(self):
        self.image_meta['id'] = self.FAKE_UUID
        # creating volume testdata
        self.volume_attrs['status'] = 'in-use'
        db.volume_create(self.context, self.volume_attrs)

        # start test
        self.assertRaises(exception.ImageNotFound,
                          self.volume.copy_volume_to_image,
                          self.context,
                          self.volume_id,
                          self.image_meta)

        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume['status'])

    def test_copy_volume_to_image_driver_not_initialized(self):
        # creating volume testdata
        db.volume_create(self.context, self.volume_attrs)

        # set initialized to False
        self.volume.driver._initialized = False

        # start test
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.copy_volume_to_image,
                          self.context,
                          self.volume_id,
                          self.image_meta)

        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume.status)

    def test_copy_volume_to_image_driver_exception(self):
        self.image_meta['id'] = self.image_id

        image_service = fake_image.FakeImageService()
        # create new image in queued state
        queued_image_id = 'd5133f15-f753-41bd-920a-06b8c49275d9'
        queued_image_meta = image_service.show(self.context, self.image_id)
        queued_image_meta['id'] = queued_image_id
        queued_image_meta['status'] = 'queued'
        image_service.create(self.context, queued_image_meta)

        # create new image in saving state
        saving_image_id = '5c6eec33-bab4-4e7d-b2c9-88e2d0a5f6f2'
        saving_image_meta = image_service.show(self.context, self.image_id)
        saving_image_meta['id'] = saving_image_id
        saving_image_meta['status'] = 'saving'
        image_service.create(self.context, saving_image_meta)

        # create volume
        self.volume_attrs['status'] = 'available'
        self.volume_attrs['instance_uuid'] = None
        db.volume_create(self.context, self.volume_attrs)

        with mock.patch.object(self.volume.driver,
                               'copy_volume_to_image') as driver_copy_mock:
            driver_copy_mock.side_effect = exception.VolumeDriverException(
                "Error")

            # test with image not in queued state
            self.assertRaises(exception.VolumeDriverException,
                              self.volume.copy_volume_to_image,
                              self.context,
                              self.volume_id,
                              self.image_meta)
            volume = db.volume_get(self.context, self.volume_id)
            self.assertEqual('available', volume['status'])
            # image shouldn't be deleted if it is not in queued state
            image_service.show(self.context, self.image_id)

            # test with image in queued state
            self.assertRaises(exception.VolumeDriverException,
                              self.volume.copy_volume_to_image,
                              self.context,
                              self.volume_id,
                              queued_image_meta)
            volume = db.volume_get(self.context, self.volume_id)
            self.assertEqual('available', volume['status'])
            # queued image should be deleted
            self.assertRaises(exception.ImageNotFound,
                              image_service.show,
                              self.context,
                              queued_image_id)

            # test with image in saving state
            self.assertRaises(exception.VolumeDriverException,
                              self.volume.copy_volume_to_image,
                              self.context,
                              self.volume_id,
                              saving_image_meta)
            volume = db.volume_get(self.context, self.volume_id)
            self.assertEqual('available', volume['status'])
            # image in saving state should be deleted
            self.assertRaises(exception.ImageNotFound,
                              image_service.show,
                              self.context,
                              saving_image_id)

    @mock.patch.object(QUOTAS, 'reserve')
    @mock.patch.object(QUOTAS, 'commit')
    @mock.patch.object(vol_manager.VolumeManager, 'create_volume')
    @mock.patch.object(fake_driver.FakeISCSIDriver, 'copy_volume_to_image')
    def _test_copy_volume_to_image_with_image_volume(
            self, mock_copy, mock_create, mock_quota_commit,
            mock_quota_reserve):
        self.flags(glance_api_version=2)
        self.volume.driver.configuration.image_upload_use_cinder_backend = True
        image_service = fake_image.FakeImageService()
        image_id = '5c6eec33-bab4-4e7d-b2c9-88e2d0a5f6f2'
        self.image_meta['id'] = image_id
        self.image_meta['status'] = 'queued'
        image_service.create(self.context, self.image_meta)

        # creating volume testdata
        self.volume_attrs['instance_uuid'] = None
        db.volume_create(self.context, self.volume_attrs)

        def fake_create(context, volume_id, **kwargs):
            db.volume_update(context, volume_id, {'status': 'available'})

        mock_create.side_effect = fake_create

        # start test
        self.volume.copy_volume_to_image(self.context,
                                         self.volume_id,
                                         self.image_meta)

        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual('available', volume['status'])

        # return create image
        image = image_service.show(self.context, image_id)
        image_service.delete(self.context, image_id)
        return image

    def test_copy_volume_to_image_with_image_volume(self):
        image = self._test_copy_volume_to_image_with_image_volume()
        self.assertTrue(image['locations'][0]['url'].startswith('cinder://'))

    def test_copy_volume_to_image_with_image_volume_qcow2(self):
        self.image_meta['disk_format'] = 'qcow2'
        image = self._test_copy_volume_to_image_with_image_volume()
        self.assertIsNone(image.get('locations'))

    @mock.patch.object(vol_manager.VolumeManager, 'delete_volume')
    @mock.patch.object(fake_image._FakeImageService, 'add_location',
                       side_effect=exception.Invalid)
    def test_copy_volume_to_image_with_image_volume_failure(
            self, mock_add_location, mock_delete):
        image = self._test_copy_volume_to_image_with_image_volume()
        self.assertIsNone(image.get('locations'))
        self.assertTrue(mock_delete.called)


class GetActiveByWindowTestCase(BaseVolumeTestCase):
    def setUp(self):
        super(GetActiveByWindowTestCase, self).setUp()
        self.ctx = context.get_admin_context(read_deleted="yes")
        self.db_attrs = [
            {
                'id': 1,
                'host': 'devstack',
                'project_id': 'p1',
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': True, 'status': 'deleted',
                'deleted_at': datetime.datetime(1, 2, 1, 1, 1, 1),
            },

            {
                'id': 2,
                'host': 'devstack',
                'project_id': 'p1',
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': True, 'status': 'deleted',
                'deleted_at': datetime.datetime(1, 3, 10, 1, 1, 1),
            },
            {
                'id': 3,
                'host': 'devstack',
                'project_id': 'p1',
                'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                'deleted': True, 'status': 'deleted',
                'deleted_at': datetime.datetime(1, 5, 1, 1, 1, 1),
            },
            {
                'id': 4,
                'host': 'devstack',
                'project_id': 'p1',
                'created_at': datetime.datetime(1, 3, 10, 1, 1, 1),
            },
            {
                'id': 5,
                'host': 'devstack',
                'project_id': 'p1',
                'created_at': datetime.datetime(1, 5, 1, 1, 1, 1),
            }
        ]

    def test_volume_get_active_by_window(self):
        # Find all all volumes valid within a timeframe window.

        # Not in window
        db.volume_create(self.ctx, self.db_attrs[0])

        # In - deleted in window
        db.volume_create(self.ctx, self.db_attrs[1])

        # In - deleted after window
        db.volume_create(self.ctx, self.db_attrs[2])

        # In - created in window
        db.volume_create(self.context, self.db_attrs[3])

        # Not of window.
        db.volume_create(self.context, self.db_attrs[4])

        volumes = db.volume_get_active_by_window(
            self.context,
            datetime.datetime(1, 3, 1, 1, 1, 1),
            datetime.datetime(1, 4, 1, 1, 1, 1),
            project_id='p1')
        self.assertEqual(3, len(volumes))
        self.assertEqual(u'2', volumes[0].id)
        self.assertEqual(u'3', volumes[1].id)
        self.assertEqual(u'4', volumes[2].id)

    def test_snapshot_get_active_by_window(self):
        # Find all all snapshots valid within a timeframe window.
        db.volume_create(self.context, {'id': 1})
        for i in range(5):
            self.db_attrs[i]['volume_id'] = 1

        # Not in window
        del self.db_attrs[0]['id']
        snap1 = objects.Snapshot(self.ctx, **self.db_attrs[0])
        snap1.create()

        # In - deleted in window
        del self.db_attrs[1]['id']
        snap2 = objects.Snapshot(self.ctx, **self.db_attrs[1])
        snap2.create()

        # In - deleted after window
        del self.db_attrs[2]['id']
        snap3 = objects.Snapshot(self.ctx, **self.db_attrs[2])
        snap3.create()

        # In - created in window
        del self.db_attrs[3]['id']
        snap4 = objects.Snapshot(self.ctx, **self.db_attrs[3])
        snap4.create()

        # Not of window.
        del self.db_attrs[4]['id']
        snap5 = objects.Snapshot(self.ctx, **self.db_attrs[4])
        snap5.create()

        snapshots = objects.SnapshotList.get_active_by_window(
            self.context,
            datetime.datetime(1, 3, 1, 1, 1, 1),
            datetime.datetime(1, 4, 1, 1, 1, 1)).objects
        self.assertEqual(3, len(snapshots))
        self.assertEqual(snap2.id, snapshots[0].id)
        self.assertEqual(u'1', snapshots[0].volume_id)
        self.assertEqual(snap3.id, snapshots[1].id)
        self.assertEqual(u'1', snapshots[1].volume_id)
        self.assertEqual(snap4.id, snapshots[2].id)
        self.assertEqual(u'1', snapshots[2].volume_id)


class DriverTestCase(test.TestCase):
    """Base Test class for Drivers."""
    driver_name = "cinder.volume.driver.FakeBaseDriver"

    def setUp(self):
        super(DriverTestCase, self).setUp()
        vol_tmpdir = tempfile.mkdtemp()
        self.flags(volume_driver=self.driver_name,
                   volumes_dir=vol_tmpdir)
        self.volume = importutils.import_object(CONF.volume_manager)
        self.context = context.get_admin_context()
        self.output = ""
        self.configuration = conf.Configuration(None)
        self.stubs.Set(brick_lvm.LVM, '_vg_exists', lambda x: True)

        def _fake_execute(_command, *_args, **_kwargs):
            """Fake _execute."""
            return self.output, None
        exec_patcher = mock.patch.object(self.volume.driver, '_execute',
                                         _fake_execute)
        exec_patcher.start()
        self.addCleanup(exec_patcher.stop)
        self.volume.driver.set_initialized()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        try:
            shutil.rmtree(CONF.volumes_dir)
        except OSError:
            pass

    def _attach_volume(self):
        """Attach volumes to an instance."""
        return []

    def _detach_volume(self, volume_id_list):
        """Detach volumes from an instance."""
        for volume_id in volume_id_list:
            db.volume_detached(self.context, volume_id)
            self.volume.delete_volume(self.context, volume_id)


class GenericVolumeDriverTestCase(DriverTestCase):
    """Test case for VolumeDriver."""
    driver_name = "cinder.tests.unit.fake_driver.LoggingVolumeDriver"

    @mock.patch.object(utils, 'temporary_chown')
    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(os_brick.initiator.connector,
                       'get_connector_properties')
    @mock.patch.object(db, 'volume_get')
    def test_backup_volume_available(self, mock_volume_get,
                                     mock_get_connector_properties,
                                     mock_file_open,
                                     mock_temporary_chown):
        vol = tests_utils.create_volume(self.context)
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        backup = tests_utils.create_backup(self.context,
                                           vol['id'])
        backup_obj = objects.Backup.get_by_id(self.context, backup.id)
        properties = {}
        attach_info = {'device': {'path': '/dev/null'}}
        backup_service = mock.Mock()

        self.volume.driver._attach_volume = mock.MagicMock()
        self.volume.driver._detach_volume = mock.MagicMock()
        self.volume.driver.terminate_connection = mock.MagicMock()
        self.volume.driver.create_snapshot = mock.MagicMock()
        self.volume.driver.delete_snapshot = mock.MagicMock()

        mock_volume_get.return_value = vol
        mock_get_connector_properties.return_value = properties
        f = mock_file_open.return_value = open('/dev/null', 'rb')

        backup_service.backup(backup_obj, f, None)
        self.volume.driver._attach_volume.return_value = attach_info, vol

        self.volume.driver.backup_volume(self.context, backup_obj,
                                         backup_service)

        mock_volume_get.assert_called_with(self.context, vol['id'])

    @mock.patch.object(utils, 'temporary_chown')
    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(os_brick.initiator.connector,
                       'get_connector_properties')
    @mock.patch.object(db, 'volume_get')
    def test_backup_volume_inuse_temp_volume(self, mock_volume_get,
                                             mock_get_connector_properties,
                                             mock_file_open,
                                             mock_temporary_chown):
        vol = tests_utils.create_volume(self.context,
                                        status='backing-up',
                                        previous_status='in-use')
        temp_vol = tests_utils.create_volume(self.context)
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        backup = tests_utils.create_backup(self.context,
                                           vol['id'])
        backup_obj = objects.Backup.get_by_id(self.context, backup.id)
        properties = {}
        attach_info = {'device': {'path': '/dev/null'}}
        backup_service = mock.Mock()

        self.volume.driver._attach_volume = mock.MagicMock()
        self.volume.driver._detach_volume = mock.MagicMock()
        self.volume.driver.terminate_connection = mock.MagicMock()
        self.volume.driver._create_temp_cloned_volume = mock.MagicMock()
        self.volume.driver._delete_temp_volume = mock.MagicMock()

        mock_volume_get.return_value = vol
        self.volume.driver._create_temp_cloned_volume.return_value = temp_vol
        mock_get_connector_properties.return_value = properties
        f = mock_file_open.return_value = open('/dev/null', 'rb')

        backup_service.backup(backup_obj, f, None)
        self.volume.driver._attach_volume.return_value = attach_info, vol

        self.volume.driver.backup_volume(self.context, backup_obj,
                                         backup_service)

        mock_volume_get.assert_called_with(self.context, vol['id'])
        self.volume.driver._create_temp_cloned_volume.assert_called_once_with(
            self.context, vol)
        self.volume.driver._delete_temp_volume.assert_called_once_with(
            self.context, temp_vol)

    @mock.patch.object(cinder.volume.driver.VolumeDriver,
                       'backup_use_temp_snapshot',
                       return_value=True)
    @mock.patch.object(utils, 'temporary_chown')
    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(os_brick.initiator.connector.LocalConnector,
                       'connect_volume')
    @mock.patch.object(os_brick.initiator.connector.LocalConnector,
                       'check_valid_device',
                       return_value=True)
    @mock.patch.object(os_brick.initiator.connector,
                       'get_connector_properties',
                       return_value={})
    @mock.patch.object(db, 'volume_get')
    def test_backup_volume_inuse_temp_snapshot(self, mock_volume_get,
                                               mock_get_connector_properties,
                                               mock_check_device,
                                               mock_connect_volume,
                                               mock_file_open,
                                               mock_temporary_chown,
                                               mock_temp_snapshot):
        vol = tests_utils.create_volume(self.context,
                                        status='backing-up',
                                        previous_status='in-use')
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        backup = tests_utils.create_backup(self.context,
                                           vol['id'])
        backup_obj = objects.Backup.get_by_id(self.context, backup.id)
        attach_info = {'device': {'path': '/dev/null'},
                       'driver_volume_type': 'LOCAL',
                       'data': {}}
        backup_service = mock.Mock()

        self.volume.driver.terminate_connection_snapshot = mock.MagicMock()
        self.volume.driver.initialize_connection_snapshot = mock.MagicMock()
        self.volume.driver.create_snapshot = mock.MagicMock()
        self.volume.driver.delete_snapshot = mock.MagicMock()
        self.volume.driver.create_export_snapshot = mock.MagicMock()
        self.volume.driver.remove_export_snapshot = mock.MagicMock()

        mock_volume_get.return_value = vol
        mock_connect_volume.return_value = {'type': 'local',
                                            'path': '/dev/null'}
        f = mock_file_open.return_value = open('/dev/null', 'rb')

        self.volume.driver._connect_device
        backup_service.backup(backup_obj, f, None)
        self.volume.driver.initialize_connection_snapshot.return_value = (
            attach_info)
        self.volume.driver.create_export_snapshot.return_value = (
            {'provider_location': '/dev/null',
             'provider_auth': 'xxxxxxxx'})

        self.volume.driver.backup_volume(self.context, backup_obj,
                                         backup_service)

        mock_volume_get.assert_called_with(self.context, vol['id'])
        self.assertTrue(self.volume.driver.create_snapshot.called)
        self.assertTrue(self.volume.driver.create_export_snapshot.called)
        self.assertTrue(
            self.volume.driver.initialize_connection_snapshot.called)
        self.assertTrue(
            self.volume.driver.terminate_connection_snapshot.called)
        self.assertTrue(self.volume.driver.remove_export_snapshot.called)
        self.assertTrue(self.volume.driver.delete_snapshot.called)

    @mock.patch.object(utils, 'temporary_chown')
    @mock.patch.object(os_brick.initiator.connector,
                       'get_connector_properties')
    @mock.patch('six.moves.builtins.open')
    def test_restore_backup(self,
                            mock_open,
                            mock_get_connector_properties,
                            mock_temporary_chown):
        dev_null = '/dev/null'
        vol = tests_utils.create_volume(self.context)
        backup = {'volume_id': vol['id'], 'id': 'backup-for-%s' % vol['id']}
        properties = {}
        attach_info = {'device': {'path': dev_null}}
        root_helper = 'sudo cinder-rootwrap /etc/cinder/rootwrap.conf'

        volume_file = mock.MagicMock()
        mock_open.return_value.__enter__.return_value = volume_file
        mock_get_connector_properties.return_value = properties

        self.volume.driver._attach_volume = mock.MagicMock()
        self.volume.driver._attach_volume.return_value = attach_info, vol
        self.volume.driver._detach_volume = mock.MagicMock()
        self.volume.driver.terminate_connection = mock.MagicMock()
        self.volume.driver.secure_file_operations_enabled = mock.MagicMock()
        self.volume.driver.secure_file_operations_enabled.side_effect = (False,
                                                                         True)
        backup_service = mock.MagicMock()

        for i in (1, 2):
            self.volume.driver.restore_backup(self.context, backup, vol,
                                              backup_service)

            mock_get_connector_properties.assert_called_with(root_helper,
                                                             CONF.my_ip,
                                                             False, False)
            self.volume.driver._attach_volume.assert_called_with(
                self.context, vol, properties)
            self.assertEqual(i, self.volume.driver._attach_volume.call_count)

            self.volume.driver._detach_volume.assert_called_with(
                self.context, attach_info, vol, properties)
            self.assertEqual(i, self.volume.driver._detach_volume.call_count)

            self.volume.driver.secure_file_operations_enabled.\
                assert_called_with()
            self.assertEqual(
                i,
                self.volume.driver.secure_file_operations_enabled.call_count
            )

            mock_temporary_chown.assert_called_once_with(dev_null)

            mock_open.assert_called_with(dev_null, 'wb')
            self.assertEqual(i, mock_open.call_count)

            backup_service.restore.assert_called_with(backup, vol['id'],
                                                      volume_file)
            self.assertEqual(i, backup_service.restore.call_count)

    def test_enable_replication_invalid_state(self):
        volume_api = cinder.volume.api.API()
        ctxt = context.get_admin_context()
        volume = tests_utils.create_volume(ctxt,
                                           size=1,
                                           host=CONF.host,
                                           replication_status='enabled')

        self.assertRaises(exception.InvalidVolume,
                          volume_api.enable_replication,
                          ctxt, volume)

    def test_enable_replication_invalid_type(self):
        volume_api = cinder.volume.api.API()
        ctxt = context.get_admin_context()

        volume = tests_utils.create_volume(self.context,
                                           size=1,
                                           host=CONF.host,
                                           replication_status='disabled')
        volume['volume_type_id'] = 'dab02f01-b50f-4ed6-8d42-2b5b9680996e'
        fake_specs = {}
        with mock.patch.object(volume_types,
                               'get_volume_type_extra_specs',
                               return_value = fake_specs):
            self.assertRaises(exception.InvalidVolume,
                              volume_api.enable_replication,
                              ctxt,
                              volume)

    def test_enable_replication(self):
        volume_api = cinder.volume.api.API()
        ctxt = context.get_admin_context()

        volume = tests_utils.create_volume(self.context,
                                           size=1,
                                           host=CONF.host,
                                           replication_status='disabled')
        volume['volume_type_id'] = 'dab02f01-b50f-4ed6-8d42-2b5b9680996e'
        fake_specs = {'replication_enabled': '<is> True'}
        with mock.patch.object(volume_rpcapi.VolumeAPI,
                               'enable_replication') as mock_enable_rep,\
            mock.patch.object(volume_types,
                              'get_volume_type_extra_specs',
                              return_value = fake_specs):

            volume_api.enable_replication(ctxt, volume)
            self.assertTrue(mock_enable_rep.called)

    def test_enable_replication_driver_initialized(self):
        volume = tests_utils.create_volume(self.context,
                                           size=1,
                                           host=CONF.host,
                                           replication_status='enabling')
        # set initialized to False
        self.volume.driver._initialized = False

        # start test
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.enable_replication,
                          self.context,
                          volume)

    def test_disable_replication_invalid_state(self):
        volume_api = cinder.volume.api.API()
        ctxt = context.get_admin_context()
        volume = tests_utils.create_volume(ctxt,
                                           size=1,
                                           host=CONF.host,
                                           replication_status='invalid-state')

        self.assertRaises(exception.InvalidVolume,
                          volume_api.disable_replication,
                          ctxt, volume)

    def test_disable_replication(self):
        volume_api = cinder.volume.api.API()
        ctxt = context.get_admin_context()

        volume = tests_utils.create_volume(self.context,
                                           size=1,
                                           host=CONF.host,
                                           replication_status='disabled')

        volume['volume_type_id'] = 'dab02f01-b50f-4ed6-8d42-2b5b9680996e'
        fake_specs = {'replication_enabled': '<is> True'}
        with mock.patch.object(volume_rpcapi.VolumeAPI,
                               'disable_replication') as mock_disable_rep,\
                mock.patch.object(volume_types,
                                  'get_volume_type_extra_specs',
                                  return_value = fake_specs):
            volume_api.disable_replication(ctxt, volume)
            self.assertTrue(mock_disable_rep.called)

            volume['replication_status'] = 'enabled'
            volume_api.disable_replication(ctxt, volume)
            self.assertTrue(mock_disable_rep.called)

    def test_disable_replication_driver_initialized(self):
        volume = tests_utils.create_volume(self.context,
                                           size=1,
                                           host=CONF.host,
                                           replication_status='disabling')
        # set initialized to False
        self.volume.driver._initialized = False

        # start test
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.disable_replication,
                          self.context,
                          volume)

    @mock.patch.object(utils, 'brick_get_connector_properties')
    @mock.patch.object(cinder.volume.driver.VolumeDriver, '_attach_volume')
    @mock.patch.object(cinder.volume.driver.VolumeDriver, '_detach_volume')
    @mock.patch.object(volutils, 'copy_volume')
    @mock.patch.object(volume_rpcapi.VolumeAPI, 'get_capabilities')
    def test_copy_volume_data(self,
                              mock_get_capabilities,
                              mock_copy,
                              mock_detach,
                              mock_attach,
                              mock_get_connector):

        src_vol = tests_utils.create_volume(self.context, size=1,
                                            host=CONF.host)
        dest_vol = tests_utils.create_volume(self.context, size=1,
                                             host=CONF.host)
        mock_get_connector.return_value = {}
        self.volume.driver._throttle = mock.MagicMock()

        attach_expected = [
            mock.call(self.context, dest_vol, {}, remote=False),
            mock.call(self.context, src_vol, {}, remote=False)]

        detach_expected = [
            mock.call(self.context, {'device': {'path': 'bar'}},
                      dest_vol, {}, force=False, remote=False),
            mock.call(self.context, {'device': {'path': 'foo'}},
                      src_vol, {}, force=False, remote=False)]

        attach_volume_returns = [
            ({'device': {'path': 'bar'}}, dest_vol),
            ({'device': {'path': 'foo'}}, src_vol),
        ]

        #  Test case for sparse_copy_volume = False
        mock_attach.side_effect = attach_volume_returns
        mock_get_capabilities.return_value = {}
        self.volume.driver.copy_volume_data(self.context,
                                            src_vol,
                                            dest_vol)

        self.assertEqual(attach_expected, mock_attach.mock_calls)
        mock_copy.assert_called_with(
            'foo', 'bar', 1024, '1M',
            throttle=self.volume.driver._throttle,
            sparse=False)
        self.assertEqual(detach_expected, mock_detach.mock_calls)

        #  Test case for sparse_copy_volume = True
        mock_attach.reset_mock()
        mock_detach.reset_mock()
        mock_attach.side_effect = attach_volume_returns
        mock_get_capabilities.return_value = {'sparse_copy_volume': True}
        self.volume.driver.copy_volume_data(self.context,
                                            src_vol,
                                            dest_vol)

        self.assertEqual(attach_expected, mock_attach.mock_calls)
        mock_copy.assert_called_with(
            'foo', 'bar', 1024, '1M',
            throttle=self.volume.driver._throttle,
            sparse=True)
        self.assertEqual(detach_expected, mock_detach.mock_calls)

        # cleanup resource
        db.volume_destroy(self.context, src_vol['id'])
        db.volume_destroy(self.context, dest_vol['id'])

    @mock.patch.object(utils, 'brick_get_connector_properties')
    @mock.patch.object(cinder.volume.manager.VolumeManager, '_attach_volume')
    @mock.patch.object(cinder.volume.manager.VolumeManager, '_detach_volume')
    @mock.patch.object(volutils, 'copy_volume')
    @mock.patch.object(volume_rpcapi.VolumeAPI, 'get_capabilities')
    def test_copy_volume_data_mgr(self,
                                  mock_get_capabilities,
                                  mock_copy,
                                  mock_detach,
                                  mock_attach,
                                  mock_get_connector):
        """Test function of _copy_volume_data."""

        src_vol = tests_utils.create_volume(self.context, size=1,
                                            host=CONF.host)
        dest_vol = tests_utils.create_volume(self.context, size=1,
                                             host=CONF.host)
        mock_get_connector.return_value = {}
        self.volume.driver._throttle = mock.MagicMock()

        attach_expected = [
            mock.call(self.context, dest_vol, {}, remote=False),
            mock.call(self.context, src_vol, {}, remote=False)]

        detach_expected = [
            mock.call(self.context, {'device': {'path': 'bar'}},
                      dest_vol, {}, force=False, remote=False),
            mock.call(self.context, {'device': {'path': 'foo'}},
                      src_vol, {}, force=False, remote=False)]

        attach_volume_returns = [
            {'device': {'path': 'bar'}},
            {'device': {'path': 'foo'}}
        ]

        #  Test case for sparse_copy_volume = False
        mock_attach.side_effect = attach_volume_returns
        mock_get_capabilities.return_value = {}
        self.volume._copy_volume_data(self.context,
                                      src_vol,
                                      dest_vol)

        self.assertEqual(attach_expected, mock_attach.mock_calls)
        mock_copy.assert_called_with('foo', 'bar', 1024, '1M', sparse=False)
        self.assertEqual(detach_expected, mock_detach.mock_calls)

        #  Test case for sparse_copy_volume = True
        mock_attach.reset_mock()
        mock_detach.reset_mock()
        mock_attach.side_effect = attach_volume_returns
        mock_get_capabilities.return_value = {'sparse_copy_volume': True}
        self.volume._copy_volume_data(self.context,
                                      src_vol,
                                      dest_vol)

        self.assertEqual(attach_expected, mock_attach.mock_calls)
        mock_copy.assert_called_with('foo', 'bar', 1024, '1M', sparse=True)
        self.assertEqual(detach_expected, mock_detach.mock_calls)

        # cleanup resource
        db.volume_destroy(self.context, src_vol['id'])
        db.volume_destroy(self.context, dest_vol['id'])


class LVMISCSIVolumeDriverTestCase(DriverTestCase):
    """Test case for VolumeDriver"""
    driver_name = "cinder.volume.drivers.lvm.LVMISCSIDriver"

    def test_delete_busy_volume(self):
        """Test deleting a busy volume."""
        self.stubs.Set(self.volume.driver, '_volume_not_present',
                       lambda x: False)
        self.stubs.Set(self.volume.driver, '_delete_volume',
                       lambda x: False)

        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                      False,
                                                      None,
                                                      'default')

        self.stubs.Set(self.volume.driver.vg, 'lv_has_snapshot',
                       lambda x: True)
        self.assertRaises(exception.VolumeIsBusy,
                          self.volume.driver.delete_volume,
                          {'name': 'test1', 'size': 1024})

        self.stubs.Set(self.volume.driver.vg, 'lv_has_snapshot',
                       lambda x: False)
        self.output = 'x'
        self.volume.driver.delete_volume(
            {'name': 'test1',
             'size': 1024,
             'id': '478e14bc-a6a9-11e4-89d3-123b93f75cba'})

    def test_lvm_migrate_volume_no_loc_info(self):
        host = {'capabilities': {}}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_bad_loc_info(self):
        capabilities = {'location_info': 'foo'}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_diff_driver(self):
        capabilities = {'location_info': 'FooDriver:foo:bar:default:0'}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_diff_host(self):
        capabilities = {'location_info': 'LVMVolumeDriver:foo:bar:default:0'}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_in_use(self):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:bar' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'in-use'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    @mock.patch.object(volutils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    def test_lvm_migrate_volume_same_volume_group(self, vgs):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:'
                        'cinder-volumes:default:0' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                      False,
                                                      None,
                                                      'default')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.driver.migrate_volume, self.context,
                          vol, host)

    @mock.patch.object(lvm.LVMVolumeDriver, '_create_volume')
    @mock.patch.object(brick_lvm.LVM, 'get_all_physical_volumes')
    @mock.patch.object(brick_lvm.LVM, 'delete')
    @mock.patch.object(volutils, 'copy_volume',
                       side_effect=processutils.ProcessExecutionError)
    @mock.patch.object(volutils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    def test_lvm_migrate_volume_volume_copy_error(self, vgs, copy_volume,
                                                  mock_delete, mock_pvs,
                                                  mock_create):

        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:'
                        'cinder-volumes:default:0' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes-old',
                                                      False, None, 'default')
        self.assertRaises(processutils.ProcessExecutionError,
                          self.volume.driver.migrate_volume, self.context,
                          vol, host)
        mock_delete.assert_called_once_with(vol)

    def test_lvm_volume_group_missing(self):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:'
                        'cinder-volumes-3:default:0' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}

        def get_all_volume_groups():
            return [{'name': 'cinder-volumes-2'}]

        self.stubs.Set(volutils, 'get_all_volume_groups',
                       get_all_volume_groups)

        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                      False,
                                                      None,
                                                      'default')

        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_proceed(self):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:'
                        'cinder-volumes-2:default:0' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'testvol', 'id': 1, 'size': 2, 'status': 'available'}

        def fake_execute(*args, **kwargs):
            pass

        def get_all_volume_groups():
            # NOTE(flaper87) Return just the destination
            # host to test the check of dest VG existence.
            return [{'name': 'cinder-volumes-2'}]

        def _fake_get_all_physical_volumes(obj, root_helper, vg_name):
            return [{}]

        with mock.patch.object(brick_lvm.LVM, 'get_all_physical_volumes',
                               return_value = [{}]), \
                mock.patch.object(self.volume.driver, '_execute') \
                as mock_execute, \
                mock.patch.object(volutils, 'copy_volume') as mock_copy, \
                mock.patch.object(volutils, 'get_all_volume_groups',
                                  side_effect = get_all_volume_groups), \
                mock.patch.object(self.volume.driver, '_delete_volume'):

            self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                          False,
                                                          None,
                                                          'default')
            moved, model_update = \
                self.volume.driver.migrate_volume(self.context, vol, host)
            self.assertTrue(moved)
            self.assertIsNone(model_update)
            mock_copy.assert_called_once_with(
                '/dev/mapper/cinder--volumes-testvol',
                '/dev/mapper/cinder--volumes--2-testvol',
                2048,
                '1M',
                execute=mock_execute,
                sparse=False)

    def test_lvm_migrate_volume_proceed_with_thin(self):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:'
                        'cinder-volumes-2:default:0' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'testvol', 'id': 1, 'size': 2, 'status': 'available'}

        def fake_execute(*args, **kwargs):
            pass

        def get_all_volume_groups():
            # NOTE(flaper87) Return just the destination
            # host to test the check of dest VG existence.
            return [{'name': 'cinder-volumes-2'}]

        def _fake_get_all_physical_volumes(obj, root_helper, vg_name):
            return [{}]

        self.configuration.lvm_type = 'thin'
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         db=db)

        with mock.patch.object(brick_lvm.LVM, 'get_all_physical_volumes',
                               return_value = [{}]), \
                mock.patch.object(lvm_driver, '_execute') \
                as mock_execute, \
                mock.patch.object(volutils, 'copy_volume') as mock_copy, \
                mock.patch.object(volutils, 'get_all_volume_groups',
                                  side_effect = get_all_volume_groups), \
                mock.patch.object(lvm_driver, '_delete_volume'):

            lvm_driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                  False,
                                                  None,
                                                  'default')
            lvm_driver._sparse_copy_volume = True
            moved, model_update = \
                lvm_driver.migrate_volume(self.context, vol, host)
            self.assertTrue(moved)
            self.assertIsNone(model_update)
            mock_copy.assert_called_once_with(
                '/dev/mapper/cinder--volumes-testvol',
                '/dev/mapper/cinder--volumes--2-testvol',
                2048,
                '1M',
                execute=mock_execute,
                sparse=True)

    @staticmethod
    def _get_manage_existing_lvs(name):
        """Helper method used by the manage_existing tests below."""
        lvs = [{'name': 'fake_lv', 'size': '1.75'},
               {'name': 'fake_lv_bad_size', 'size': 'Not a float'}]
        for lv in lvs:
            if lv['name'] == name:
                return lv

    def _setup_stubs_for_manage_existing(self):
        """Helper to set up common stubs for the manage_existing tests."""
        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                      False,
                                                      None,
                                                      'default')
        self.stubs.Set(self.volume.driver.vg, 'get_volume',
                       self._get_manage_existing_lvs)

    @mock.patch.object(db, 'volume_get', side_effect=exception.VolumeNotFound(
                       volume_id='d8cd1feb-2dcc-404d-9b15-b86fe3bec0a1'))
    def test_lvm_manage_existing_not_found(self, mock_vol_get):
        self._setup_stubs_for_manage_existing()

        vol_name = 'volume-d8cd1feb-2dcc-404d-9b15-b86fe3bec0a1'
        ref = {'source-name': 'fake_lv'}
        vol = {'name': vol_name, 'id': 1, 'size': 0}

        with mock.patch.object(self.volume.driver.vg, 'rename_volume'):
            model_update = self.volume.driver.manage_existing(vol, ref)
            self.assertIsNone(model_update)

    @mock.patch.object(db, 'volume_get')
    def test_lvm_manage_existing_already_managed(self, mock_conf):
        self._setup_stubs_for_manage_existing()

        mock_conf.volume_name_template = 'volume-%s'
        vol_name = 'volume-d8cd1feb-2dcc-404d-9b15-b86fe3bec0a1'
        ref = {'source-name': vol_name}
        vol = {'name': 'test', 'id': 1, 'size': 0}

        with mock.patch.object(self.volume.driver.vg, 'rename_volume'):
            self.assertRaises(exception.ManageExistingAlreadyManaged,
                              self.volume.driver.manage_existing,
                              vol, ref)

    def test_lvm_manage_existing(self):
        """Good pass on managing an LVM volume.

        This test case ensures that, when a logical volume with the
        specified name exists, and the size is as expected, no error is
        returned from driver.manage_existing, and that the rename_volume
        function is called in the Brick LVM code with the correct arguments.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_lv'}
        vol = {'name': 'test', 'id': 1, 'size': 0}

        def _rename_volume(old_name, new_name):
            self.assertEqual(ref['source-name'], old_name)
            self.assertEqual(vol['name'], new_name)

        self.stubs.Set(self.volume.driver.vg, 'rename_volume',
                       _rename_volume)

        size = self.volume.driver.manage_existing_get_size(vol, ref)
        self.assertEqual(2, size)
        model_update = self.volume.driver.manage_existing(vol, ref)
        self.assertIsNone(model_update)

    def test_lvm_manage_existing_bad_size(self):
        """Make sure correct exception on bad size returned from LVM.

        This test case ensures that the correct exception is raised when
        the information returned for the existing LVs is not in the format
        that the manage_existing code expects.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_lv_bad_size'}
        vol = {'name': 'test', 'id': 1, 'size': 2}

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.driver.manage_existing_get_size,
                          vol, ref)

    def test_lvm_manage_existing_bad_ref(self):
        """Error case where specified LV doesn't exist.

        This test case ensures that the correct exception is raised when
        the caller attempts to manage a volume that does not exist.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_nonexistent_lv'}
        vol = {'name': 'test', 'id': 1, 'size': 0, 'status': 'available'}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.volume.driver.manage_existing_get_size,
                          vol, ref)

    def test_lvm_manage_existing_snapshot(self):
        """Good pass on managing an LVM snapshot.

        This test case ensures that, when a logical volume's snapshot with the
        specified name exists, and the size is as expected, no error is
        returned from driver.manage_existing_snapshot, and that the
        rename_volume function is called in the Brick LVM code with the correct
        arguments.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_lv'}
        snp = {'name': 'test', 'id': 1, 'size': 0}

        def _rename_volume(old_name, new_name):
            self.assertEqual(ref['source-name'], old_name)
            self.assertEqual(snp['name'], new_name)

        with mock.patch.object(self.volume.driver.vg, 'rename_volume') as \
                mock_rename_volume:
            mock_rename_volume.return_value = _rename_volume

            size = self.volume.driver.manage_existing_snapshot_get_size(snp,
                                                                        ref)
            self.assertEqual(2, size)
            model_update = self.volume.driver.manage_existing_snapshot(snp,
                                                                       ref)
            self.assertIsNone(model_update)

    def test_lvm_manage_existing_snapshot_bad_ref(self):
        """Error case where specified LV snapshot doesn't exist.

        This test case ensures that the correct exception is raised when
        the caller attempts to manage a snapshot that does not exist.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_nonexistent_lv'}
        snp = {'name': 'test', 'id': 1, 'size': 0, 'status': 'available'}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.volume.driver.manage_existing_snapshot_get_size,
                          snp, ref)

    def test_lvm_manage_existing_snapshot_bad_size(self):
        """Make sure correct exception on bad size returned from LVM.

        This test case ensures that the correct exception is raised when
        the information returned for the existing LVs is not in the format
        that the manage_existing_snapshot code expects.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_lv_bad_size'}
        snp = {'name': 'test', 'id': 1, 'size': 2}

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.driver.manage_existing_snapshot_get_size,
                          snp, ref)

    def test_lvm_unmanage(self):
        volume = tests_utils.create_volume(self.context, status='available',
                                           size=1, host=CONF.host)
        ret = self.volume.driver.unmanage(volume)
        self.assertEqual(ret, None)


class LVMVolumeDriverTestCase(DriverTestCase):
    """Test case for VolumeDriver"""
    driver_name = "cinder.volume.drivers.lvm.LVMVolumeDriver"
    FAKE_VOLUME = {'name': 'test1',
                   'id': 'test1'}

    @mock.patch.object(fake_driver.FakeISCSIDriver, 'create_export')
    def test_delete_volume_invalid_parameter(self, _mock_create_export):
        self.configuration.volume_clear = 'zero'
        self.configuration.volume_clear_size = 0
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         db=db)
        self.mox.StubOutWithMock(os.path, 'exists')

        os.path.exists(mox.IgnoreArg()).AndReturn(True)

        self.mox.ReplayAll()
        # Test volume without 'size' field and 'volume_size' field
        self.assertRaises(exception.InvalidParameterValue,
                          lvm_driver._delete_volume,
                          self.FAKE_VOLUME)

    @mock.patch.object(fake_driver.FakeISCSIDriver, 'create_export')
    def test_delete_volume_bad_path(self, _mock_create_export):
        self.configuration.volume_clear = 'zero'
        self.configuration.volume_clear_size = 0
        self.configuration.volume_type = 'default'

        volume = dict(self.FAKE_VOLUME, size=1)
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         db=db)

        self.mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(mox.IgnoreArg()).AndReturn(False)
        self.mox.ReplayAll()

        self.assertRaises(exception.VolumeBackendAPIException,
                          lvm_driver._delete_volume, volume)

    @mock.patch.object(fake_driver.FakeISCSIDriver, 'create_export')
    def test_delete_volume_thinlvm_snap(self, _mock_create_export):
        self.configuration.volume_clear = 'zero'
        self.configuration.volume_clear_size = 0
        self.configuration.lvm_type = 'thin'
        self.configuration.iscsi_helper = 'tgtadm'
        lvm_driver = lvm.LVMISCSIDriver(configuration=self.configuration,
                                        vg_obj=mox.MockAnything(),
                                        db=db)

        # Ensures that copy_volume is not called for ThinLVM
        self.mox.StubOutWithMock(volutils, 'copy_volume')
        self.mox.StubOutWithMock(volutils, 'clear_volume')
        self.mox.StubOutWithMock(lvm_driver, '_execute')
        self.mox.ReplayAll()

        uuid = '00000000-0000-0000-0000-c3aa7ee01536'

        fake_snapshot = {'name': 'volume-' + uuid,
                         'id': uuid,
                         'size': 123}

        lvm_driver._delete_volume(fake_snapshot, is_snapshot=True)

    def test_check_for_setup_error(self):

        def get_all_volume_groups(vg):
            return [{'name': 'cinder-volumes'}]

        self.stubs.Set(volutils, 'get_all_volume_groups',
                       get_all_volume_groups)

        vg_obj = fake_lvm.FakeBrickLVM('cinder-volumes',
                                       False,
                                       None,
                                       'default')

        configuration = conf.Configuration(fake_opt, 'fake_group')
        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration,
                                         vg_obj=vg_obj, db=db)

        lvm_driver.delete_snapshot = mock.Mock()
        self.stubs.Set(volutils, 'get_all_volume_groups',
                       get_all_volume_groups)

        volume = tests_utils.create_volume(self.context,
                                           host=socket.gethostname())
        volume_id = volume['id']

        backup = {}
        backup['volume_id'] = volume_id
        backup['user_id'] = 'fake'
        backup['project_id'] = 'fake'
        backup['host'] = socket.gethostname()
        backup['availability_zone'] = '1'
        backup['display_name'] = 'test_check_for_setup_error'
        backup['display_description'] = 'test_check_for_setup_error'
        backup['container'] = 'fake'
        backup['status'] = 'creating'
        backup['fail_reason'] = ''
        backup['service'] = 'fake'
        backup['parent_id'] = None
        backup['size'] = 5 * 1024 * 1024
        backup['object_count'] = 22
        db.backup_create(self.context, backup)

        lvm_driver.check_for_setup_error()

    @mock.patch.object(utils, 'temporary_chown')
    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(os_brick.initiator.connector,
                       'get_connector_properties')
    @mock.patch.object(db, 'volume_get')
    def test_backup_volume(self, mock_volume_get,
                           mock_get_connector_properties,
                           mock_file_open,
                           mock_temporary_chown):
        vol = tests_utils.create_volume(self.context)
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        backup = tests_utils.create_backup(self.context,
                                           vol['id'])
        backup_obj = objects.Backup.get_by_id(self.context, backup.id)

        properties = {}
        attach_info = {'device': {'path': '/dev/null'}}
        backup_service = mock.Mock()

        self.volume.driver._detach_volume = mock.MagicMock()
        self.volume.driver._attach_volume = mock.MagicMock()
        self.volume.driver.terminate_connection = mock.MagicMock()

        mock_volume_get.return_value = vol
        mock_get_connector_properties.return_value = properties
        f = mock_file_open.return_value = open('/dev/null', 'rb')

        backup_service.backup(backup_obj, f, None)
        self.volume.driver._attach_volume.return_value = attach_info

        self.volume.driver.backup_volume(self.context, backup_obj,
                                         backup_service)

        mock_volume_get.assert_called_with(self.context, vol['id'])

    def test_update_migrated_volume(self):
        fake_volume_id = 'vol1'
        fake_new_volume_id = 'vol2'
        fake_provider = 'fake_provider'
        original_volume_name = CONF.volume_name_template % fake_volume_id
        current_name = CONF.volume_name_template % fake_new_volume_id
        fake_volume = tests_utils.create_volume(self.context)
        fake_volume['id'] = fake_volume_id
        fake_new_volume = tests_utils.create_volume(self.context)
        fake_new_volume['id'] = fake_new_volume_id
        fake_new_volume['provider_location'] = fake_provider
        fake_vg = fake_lvm.FakeBrickLVM('cinder-volumes', False,
                                        None, 'default')
        with mock.patch.object(self.volume.driver, 'vg') as vg:
            vg.return_value = fake_vg
            vg.rename_volume.return_value = None
            update = self.volume.driver.update_migrated_volume(self.context,
                                                               fake_volume,
                                                               fake_new_volume,
                                                               'available')
            vg.rename_volume.assert_called_once_with(current_name,
                                                     original_volume_name)
            self.assertEqual({'_name_id': None,
                              'provider_location': None}, update)

            vg.rename_volume.reset_mock()
            vg.rename_volume.side_effect = processutils.ProcessExecutionError
            update = self.volume.driver.update_migrated_volume(self.context,
                                                               fake_volume,
                                                               fake_new_volume,
                                                               'available')
            vg.rename_volume.assert_called_once_with(current_name,
                                                     original_volume_name)
            self.assertEqual({'_name_id': fake_new_volume_id,
                              'provider_location': fake_provider},
                             update)

    @mock.patch.object(utils, 'temporary_chown')
    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(os_brick.initiator.connector,
                       'get_connector_properties')
    @mock.patch.object(db, 'volume_get')
    def test_backup_volume_inuse(self, mock_volume_get,
                                 mock_get_connector_properties,
                                 mock_file_open,
                                 mock_temporary_chown):

        vol = tests_utils.create_volume(self.context,
                                        status='backing-up',
                                        previous_status='in-use')
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'

        mock_volume_get.return_value = vol
        temp_snapshot = tests_utils.create_snapshot(self.context, vol['id'])
        backup = tests_utils.create_backup(self.context,
                                           vol['id'])
        backup_obj = objects.Backup.get_by_id(self.context, backup.id)
        properties = {}
        attach_info = {'device': {'path': '/dev/null'}}
        backup_service = mock.Mock()

        self.volume.driver._detach_volume = mock.MagicMock()
        self.volume.driver._attach_volume = mock.MagicMock()
        self.volume.driver.terminate_connection = mock.MagicMock()
        self.volume.driver._create_temp_snapshot = mock.MagicMock()
        self.volume.driver._delete_temp_snapshot = mock.MagicMock()

        mock_get_connector_properties.return_value = properties
        f = mock_file_open.return_value = open('/dev/null', 'rb')

        backup_service.backup(backup_obj, f, None)
        self.volume.driver._attach_volume.return_value = attach_info
        self.volume.driver._create_temp_snapshot.return_value = temp_snapshot

        self.volume.driver.backup_volume(self.context, backup_obj,
                                         backup_service)

        mock_volume_get.assert_called_with(self.context, vol['id'])
        self.volume.driver._create_temp_snapshot.assert_called_once_with(
            self.context, vol)
        self.volume.driver._delete_temp_snapshot.assert_called_once_with(
            self.context, temp_snapshot)

    def test_create_volume_from_snapshot_none_sparse(self):

        with mock.patch.object(self.volume.driver, 'vg'), \
                mock.patch.object(self.volume.driver, '_create_volume'), \
                mock.patch.object(volutils, 'copy_volume') as mock_copy:

            # Test case for thick LVM
            src_volume = tests_utils.create_volume(self.context)
            snapshot_ref = tests_utils.create_snapshot(self.context,
                                                       src_volume['id'])
            dst_volume = tests_utils.create_volume(self.context)
            self.volume.driver.create_volume_from_snapshot(dst_volume,
                                                           snapshot_ref)

            volume_path = self.volume.driver.local_path(dst_volume)
            snapshot_path = self.volume.driver.local_path(snapshot_ref)
            volume_size = 1024
            block_size = '1M'
            mock_copy.assert_called_with(snapshot_path,
                                         volume_path,
                                         volume_size,
                                         block_size,
                                         execute=self.volume.driver._execute,
                                         sparse=False)

    def test_create_volume_from_snapshot_sparse(self):

        self.configuration.lvm_type = 'thin'
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         db=db)

        with mock.patch.object(lvm_driver, 'vg'), \
                mock.patch.object(lvm_driver, '_create_volume'), \
                mock.patch.object(volutils, 'copy_volume') as mock_copy:

            # Test case for thin LVM
            lvm_driver._sparse_copy_volume = True
            src_volume = tests_utils.create_volume(self.context)
            snapshot_ref = tests_utils.create_snapshot(self.context,
                                                       src_volume['id'])
            dst_volume = tests_utils.create_volume(self.context)
            lvm_driver.create_volume_from_snapshot(dst_volume,
                                                   snapshot_ref)

            volume_path = lvm_driver.local_path(dst_volume)
            snapshot_path = lvm_driver.local_path(snapshot_ref)
            volume_size = 1024
            block_size = '1M'
            mock_copy.assert_called_with(snapshot_path,
                                         volume_path,
                                         volume_size,
                                         block_size,
                                         execute=lvm_driver._execute,
                                         sparse=True)

    @mock.patch.object(cinder.volume.utils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    @mock.patch('cinder.brick.local_dev.lvm.LVM.update_volume_group_info')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_all_physical_volumes')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.supports_thin_provisioning',
                return_value=True)
    def test_lvm_type_auto_thin_pool_exists(self, *_unused_mocks):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.lvm_type = 'auto'

        vg_obj = fake_lvm.FakeBrickLVM('cinder-volumes',
                                       False,
                                       None,
                                       'default')

        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration,
                                         vg_obj=vg_obj)

        lvm_driver.check_for_setup_error()

        self.assertEqual('thin', lvm_driver.configuration.lvm_type)

    @mock.patch.object(cinder.volume.utils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    @mock.patch.object(cinder.brick.local_dev.lvm.LVM, 'get_volumes',
                       return_value=[])
    @mock.patch('cinder.brick.local_dev.lvm.LVM.update_volume_group_info')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_all_physical_volumes')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.supports_thin_provisioning',
                return_value=True)
    def test_lvm_type_auto_no_lvs(self, *_unused_mocks):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.lvm_type = 'auto'

        vg_obj = fake_lvm.FakeBrickLVM('cinder-volumes',
                                       False,
                                       None,
                                       'default')

        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration,
                                         vg_obj=vg_obj)

        lvm_driver.check_for_setup_error()

        self.assertEqual('thin', lvm_driver.configuration.lvm_type)

    @mock.patch.object(cinder.volume.utils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    @mock.patch('cinder.brick.local_dev.lvm.LVM.update_volume_group_info')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_all_physical_volumes')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.supports_thin_provisioning',
                return_value=False)
    def test_lvm_type_auto_no_thin_support(self, *_unused_mocks):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.lvm_type = 'auto'

        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration)

        lvm_driver.check_for_setup_error()

        self.assertEqual('default', lvm_driver.configuration.lvm_type)

    @mock.patch.object(cinder.volume.utils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    @mock.patch('cinder.brick.local_dev.lvm.LVM.update_volume_group_info')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_all_physical_volumes')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_volume')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.supports_thin_provisioning',
                return_value=False)
    def test_lvm_type_auto_no_thin_pool(self, *_unused_mocks):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.lvm_type = 'auto'

        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration)

        lvm_driver.check_for_setup_error()

        self.assertEqual('default', lvm_driver.configuration.lvm_type)

    @mock.patch.object(lvm.LVMISCSIDriver, 'extend_volume')
    def test_create_cloned_volume_by_thin_snapshot(self, mock_extend):
        self.configuration.lvm_type = 'thin'
        fake_vg = mock.Mock(fake_lvm.FakeBrickLVM('cinder-volumes', False,
                                                  None, 'default'))
        lvm_driver = lvm.LVMISCSIDriver(configuration=self.configuration,
                                        vg_obj=fake_vg,
                                        db=db)
        fake_volume = tests_utils.create_volume(self.context, size=1)
        fake_new_volume = tests_utils.create_volume(self.context, size=2)

        lvm_driver.create_cloned_volume(fake_new_volume, fake_volume)
        fake_vg.create_lv_snapshot.assert_called_once_with(
            fake_new_volume['name'], fake_volume['name'], 'thin')
        mock_extend.assert_called_once_with(fake_new_volume, 2)
        fake_vg.activate_lv.assert_called_once_with(
            fake_new_volume['name'], is_snapshot=True, permanent=True)


class ISCSITestCase(DriverTestCase):
    """Test Case for ISCSIDriver"""
    driver_name = "cinder.volume.drivers.lvm.LVMISCSIDriver"

    def setUp(self):
        super(ISCSITestCase, self).setUp()
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.iscsi_target_prefix = 'iqn.2010-10.org.openstack:'
        self.configuration.iscsi_ip_address = '0.0.0.0'
        self.configuration.iscsi_port = 3260

    def _attach_volume(self):
        """Attach volumes to an instance."""
        volume_id_list = []
        for index in range(3):
            vol = {}
            vol['size'] = 0
            vol_ref = db.volume_create(self.context, vol)
            self.volume.create_volume(self.context, vol_ref['id'])
            vol_ref = db.volume_get(self.context, vol_ref['id'])

            # each volume has a different mountpoint
            mountpoint = "/dev/sd" + chr((ord('b') + index))
            instance_uuid = '12345678-1234-5678-1234-567812345678'
            db.volume_attached(self.context, vol_ref['id'], instance_uuid,
                               mountpoint)
            volume_id_list.append(vol_ref['id'])

        return volume_id_list

    def test_do_iscsi_discovery(self):
        self.configuration = conf.Configuration(None)
        iscsi_driver = \
            cinder.volume.targets.tgt.TgtAdm(
                configuration=self.configuration)

        utils.execute = lambda *a, **kw: \
            ("%s dummy" % CONF.iscsi_ip_address, '')
        volume = {"name": "dummy",
                  "host": "0.0.0.0",
                  "id": "12345678-1234-5678-1234-567812345678"}
        iscsi_driver._do_iscsi_discovery(volume)

    def test_get_iscsi_properties(self):
        volume = {"provider_location": '',
                  "id": "0",
                  "provider_auth": "a b c",
                  "attached_mode": "rw"}
        iscsi_driver = \
            cinder.volume.targets.tgt.TgtAdm(configuration=self.configuration)
        iscsi_driver._do_iscsi_discovery = lambda v: "0.0.0.0:0000,0 iqn:iqn 0"
        result = iscsi_driver._get_iscsi_properties(volume)
        self.assertEqual("0.0.0.0:0000", result["target_portal"])
        self.assertEqual("iqn:iqn", result["target_iqn"])
        self.assertEqual(0, result["target_lun"])

    def test_get_iscsi_properties_multiple_portals(self):
        volume = {"provider_location": '1.1.1.1:3260;2.2.2.2:3261,1 iqn:iqn 0',
                  "id": "0",
                  "provider_auth": "a b c",
                  "attached_mode": "rw"}
        iscsi_driver = \
            cinder.volume.targets.tgt.TgtAdm(configuration=self.configuration)
        result = iscsi_driver._get_iscsi_properties(volume)
        self.assertEqual("1.1.1.1:3260", result["target_portal"])
        self.assertEqual("iqn:iqn", result["target_iqn"])
        self.assertEqual(0, result["target_lun"])
        self.assertEqual(["1.1.1.1:3260", "2.2.2.2:3261"],
                         result["target_portals"])
        self.assertEqual(["iqn:iqn", "iqn:iqn"], result["target_iqns"])
        self.assertEqual([0, 0], result["target_luns"])

    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_lvm_version',
                return_value=(2, 2, 100))
    def test_get_volume_stats(self, _mock_get_version):

        def _fake_get_all_physical_volumes(obj, root_helper, vg_name):
            return [{}]

        @staticmethod
        def _fake_get_all_volume_groups(root_helper, vg_name=None):
            return [{'name': 'cinder-volumes',
                     'size': '5.52',
                     'available': '0.52',
                     'lv_count': '2',
                     'uuid': 'vR1JU3-FAKE-C4A9-PQFh-Mctm-9FwA-Xwzc1m'}]

        def _fake_get_volumes(obj, lv_name=None):
            return [{'vg': 'fake_vg', 'name': 'fake_vol', 'size': '1000'}]

        self.stubs.Set(brick_lvm.LVM,
                       'get_all_volume_groups',
                       _fake_get_all_volume_groups)

        self.stubs.Set(brick_lvm.LVM,
                       'get_all_physical_volumes',
                       _fake_get_all_physical_volumes)

        self.stubs.Set(brick_lvm.LVM,
                       'get_volumes',
                       _fake_get_volumes)

        self.volume.driver.vg = brick_lvm.LVM('cinder-volumes', 'sudo')

        self.volume.driver._update_volume_stats()

        stats = self.volume.driver._stats

        self.assertEqual(
            float('5.52'), stats['pools'][0]['total_capacity_gb'])
        self.assertEqual(
            float('0.52'), stats['pools'][0]['free_capacity_gb'])
        self.assertEqual(
            float('5.0'), stats['pools'][0]['provisioned_capacity_gb'])
        self.assertEqual(
            int('1'), stats['pools'][0]['total_volumes'])
        self.assertFalse(stats['sparse_copy_volume'])

        # Check value of sparse_copy_volume for thin enabled case.
        # This value is set in check_for_setup_error.
        self.configuration = conf.Configuration(None)
        self.configuration.lvm_type = 'thin'
        vg_obj = fake_lvm.FakeBrickLVM('cinder-volumes',
                                       False,
                                       None,
                                       'default')
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         db=db,
                                         vg_obj=vg_obj)
        lvm_driver.check_for_setup_error()
        lvm_driver.vg = brick_lvm.LVM('cinder-volumes', 'sudo')
        lvm_driver._update_volume_stats()
        stats = lvm_driver._stats
        self.assertTrue(stats['sparse_copy_volume'])

    def test_validate_connector(self):
        iscsi_driver =\
            cinder.volume.targets.tgt.TgtAdm(
                configuration=self.configuration)

        # Validate a valid connector
        connector = {'ip': '10.0.0.2',
                     'host': 'fakehost',
                     'initiator': 'iqn.2012-07.org.fake:01'}
        iscsi_driver.validate_connector(connector)

        # Validate a connector without the initiator
        connector = {'ip': '10.0.0.2', 'host': 'fakehost'}
        self.assertRaises(exception.InvalidConnectorException,
                          iscsi_driver.validate_connector, connector)


class ISERTestCase(DriverTestCase):
    """Test Case for ISERDriver."""
    driver_name = "cinder.volume.drivers.lvm.LVMISERDriver"

    def setUp(self):
        super(ISERTestCase, self).setUp()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.safe_get.return_value = None
        self.configuration.num_iser_scan_tries = 3
        self.configuration.iser_target_prefix = 'iqn.2010-10.org.openstack:'
        self.configuration.iser_ip_address = '0.0.0.0'
        self.configuration.iser_port = 3260
        self.configuration.target_driver = \
            'cinder.volume.targets.iser.ISERTgtAdm'

    @test.testtools.skip("SKIP until ISER driver is removed or fixed")
    def test_get_volume_stats(self):
        def _fake_get_all_physical_volumes(obj, root_helper, vg_name):
            return [{}]

        def _fake_get_all_volume_groups(obj, vg_name=None, no_suffix=True):
            return [{'name': 'cinder-volumes',
                     'size': '5.52',
                     'available': '0.52',
                     'lv_count': '2',
                     'uuid': 'vR1JU3-FAKE-C4A9-PQFh-Mctm-9FwA-Xwzc1m'}]

        self.stubs.Set(brick_lvm.LVM,
                       'get_all_physical_volumes',
                       _fake_get_all_physical_volumes)

        self.stubs.Set(brick_lvm.LVM,
                       'get_all_volume_groups',
                       _fake_get_all_volume_groups)

        self.volume_driver = \
            lvm.LVMISERDriver(configuration=self.configuration)
        self.volume.driver.vg = brick_lvm.LVM('cinder-volumes', 'sudo')

        stats = self.volume.driver.get_volume_stats(refresh=True)

        self.assertEqual(
            float('5.52'), stats['pools'][0]['total_capacity_gb'])
        self.assertEqual(
            float('0.52'), stats['pools'][0]['free_capacity_gb'])
        self.assertEqual(
            float('5.0'), stats['pools'][0]['provisioned_capacity_gb'])
        self.assertEqual('iSER', stats['storage_protocol'])

    @test.testtools.skip("SKIP until ISER driver is removed or fixed")
    def test_get_volume_stats2(self):
        iser_driver = lvm.LVMISERDriver(configuration=self.configuration)

        stats = iser_driver.get_volume_stats(refresh=True)

        self.assertEqual(
            0, stats['pools'][0]['total_capacity_gb'])
        self.assertEqual(
            0, stats['pools'][0]['free_capacity_gb'])
        self.assertEqual(
            float('5.0'), stats['pools'][0]['provisioned_capacity_gb'])
        self.assertEqual('iSER', stats['storage_protocol'])


class FibreChannelTestCase(DriverTestCase):
    """Test Case for FibreChannelDriver."""
    driver_name = "cinder.volume.driver.FibreChannelDriver"

    def test_initialize_connection(self):
        self.assertRaises(NotImplementedError,
                          self.volume.driver.initialize_connection, {}, {})

    def test_validate_connector(self):
        """validate_connector() successful use case.

        validate_connector() does not throw an exception when
        wwpns and wwnns are both set and both are not empty.
        """
        connector = {'wwpns': ["not empty"],
                     'wwnns': ["not empty"]}
        self.volume.driver.validate_connector(connector)

    def test_validate_connector_no_wwpns(self):
        """validate_connector() throws exception when it has no wwpns."""
        connector = {'wwnns': ["not empty"]}
        self.assertRaises(exception.InvalidConnectorException,
                          self.volume.driver.validate_connector, connector)

    def test_validate_connector_empty_wwpns(self):
        """validate_connector() throws exception when it has empty wwpns."""
        connector = {'wwpns': [],
                     'wwnns': ["not empty"]}
        self.assertRaises(exception.InvalidConnectorException,
                          self.volume.driver.validate_connector, connector)

    def test_validate_connector_no_wwnns(self):
        """validate_connector() throws exception when it has no wwnns."""
        connector = {'wwpns': ["not empty"]}
        self.assertRaises(exception.InvalidConnectorException,
                          self.volume.driver.validate_connector, connector)

    def test_validate_connector_empty_wwnns(self):
        """validate_connector() throws exception when it has empty wwnns."""
        connector = {'wwnns': [],
                     'wwpns': ["not empty"]}
        self.assertRaises(exception.InvalidConnectorException,
                          self.volume.driver.validate_connector, connector)


class VolumePolicyTestCase(test.TestCase):

    def setUp(self):
        super(VolumePolicyTestCase, self).setUp()

        cinder.policy.init()

        self.context = context.get_admin_context()

    def test_check_policy(self):
        self.mox.StubOutWithMock(cinder.policy, 'enforce')
        target = {
            'project_id': self.context.project_id,
            'user_id': self.context.user_id,
        }
        cinder.policy.enforce(self.context, 'volume:attach', target)
        self.mox.ReplayAll()
        cinder.volume.api.check_policy(self.context, 'attach')

    def test_check_policy_with_target(self):
        self.mox.StubOutWithMock(cinder.policy, 'enforce')
        target = {
            'project_id': self.context.project_id,
            'user_id': self.context.user_id,
            'id': 2,
        }
        cinder.policy.enforce(self.context, 'volume:attach', target)
        self.mox.ReplayAll()
        cinder.volume.api.check_policy(self.context, 'attach', {'id': 2})


class ImageVolumeCacheTestCase(BaseVolumeTestCase):

    def setUp(self):
        super(ImageVolumeCacheTestCase, self).setUp()
        self.volume.driver.set_initialized()

    @mock.patch('oslo_utils.importutils.import_object')
    def test_cache_configs(self, mock_import_object):
        opts = {
            'image_volume_cache_enabled': True,
            'image_volume_cache_max_size_gb': 100,
            'image_volume_cache_max_count': 20
        }

        def conf_get(option):
            if option in opts:
                return opts[option]
            else:
                return None

        mock_driver = mock.Mock()
        mock_driver.configuration.safe_get.side_effect = conf_get
        mock_driver.configuration.extra_capabilities = 'null'

        def import_obj(*args, **kwargs):
            return mock_driver

        mock_import_object.side_effect = import_obj

        manager = vol_manager.VolumeManager(volume_driver=mock_driver)
        self.assertIsNotNone(manager)
        self.assertIsNotNone(manager.image_volume_cache)
        self.assertEqual(100, manager.image_volume_cache.max_cache_size_gb)
        self.assertEqual(20, manager.image_volume_cache.max_cache_size_count)

    def test_delete_image_volume(self):
        volume_params = {
            'status': 'creating',
            'host': 'some_host',
            'size': 1
        }
        volume_api = cinder.volume.api.API()
        volume = tests_utils.create_volume(self.context, **volume_params)
        volume = db.volume_update(self.context, volume['id'],
                                  {'status': 'available'})
        image_id = '70a599e0-31e7-49b7-b260-868f441e862b'
        db.image_volume_cache_create(self.context,
                                     volume['host'],
                                     image_id,
                                     datetime.datetime.utcnow(),
                                     volume['id'],
                                     volume['size'])
        volume_api.delete(self.context, volume)
        entry = db.image_volume_cache_get_by_volume_id(self.context,
                                                       volume['id'])
        self.assertIsNone(entry)
