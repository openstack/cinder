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
"""
Tests for Volume Code.

"""

import datetime
import os
import shutil
import socket
import sys
import tempfile

import eventlet
import mock
import mox
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import importutils
from oslo_utils import timeutils
from oslo_utils import units
from stevedore import extension
from taskflow.engines.action_engine import engine

from cinder.backup import driver as backup_driver
from cinder.brick.local_dev import lvm as brick_lvm
from cinder import compute
from cinder import context
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder import keymgr
from cinder import objects
from cinder.openstack.common import fileutils
import cinder.policy
from cinder import quota
from cinder import test
from cinder.tests.api import fakes
from cinder.tests.brick import fake_lvm
from cinder.tests import conf_fixture
from cinder.tests import fake_driver
from cinder.tests import fake_notifier
from cinder.tests.image import fake as fake_image
from cinder.tests.keymgr import fake as fake_keymgr
from cinder.tests import utils as tests_utils
from cinder import utils
import cinder.volume
from cinder.volume import configuration as conf
from cinder.volume import driver
from cinder.volume.drivers import lvm
from cinder.volume import manager as vol_manager
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume.targets import tgt
from cinder.volume import utils as volutils
from cinder.volume import volume_types


QUOTAS = quota.QUOTAS
CGQUOTAS = quota.CGQUOTAS

CONF = cfg.CONF

ENCRYPTION_PROVIDER = 'nova.volume.encryptors.cryptsetup.CryptsetupEncryptor'

fake_opt = [
    cfg.StrOpt('fake_opt1', default='fake', help='fake opts')
]

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa'


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
    def setUp(self):
        super(BaseVolumeTestCase, self).setUp()
        self.extension_manager = extension.ExtensionManager(
            "BaseVolumeTestCase")
        vol_tmpdir = tempfile.mkdtemp()
        self.flags(volumes_dir=vol_tmpdir,
                   notification_driver=["test"])
        self.addCleanup(self._cleanup)
        with mock.patch("osprofiler.profiler.trace_cls") as mock_trace_cls:
            side_effect = lambda value: value
            mock_decorator = mock.MagicMock(side_effect=side_effect)
            mock_trace_cls.return_value = mock_decorator
            self.volume = importutils.import_object(CONF.volume_manager)
        self.configuration = mock.Mock(conf.Configuration)
        self.context = context.get_admin_context()
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
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
        fake_notifier.reset()

    def fake_get_target(obj, iqn):
        return 1

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


class VolumeTestCase(BaseVolumeTestCase):

    def _fake_create_iscsi_target(self, name, tid,
                                  lun, path, chap_auth=None,
                                  **kwargs):
            return 1

    def setUp(self):
        super(VolumeTestCase, self).setUp()
        self.stubs.Set(volutils, 'clear_volume',
                       lambda a, b, volume_clear=mox.IgnoreArg(),
                       volume_clear_size=mox.IgnoreArg(),
                       lvm_type=mox.IgnoreArg(),
                       throttle=mox.IgnoreArg(): None)
        self.stubs.Set(tgt.TgtAdm,
                       'create_iscsi_target',
                       self._fake_create_iscsi_target)

    def test_init_host_clears_downloads(self):
        """Test that init_host will unwedge a volume stuck in downloading."""
        volume = tests_utils.create_volume(self.context, status='downloading',
                                           size=0, host=CONF.host)
        volume_id = volume['id']
        self.volume.init_host()
        volume = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(volume['status'], "error")
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
        self.assertEqual(stats['allocated_capacity_gb'], 2020)
        self.assertEqual(
            stats['pools']['pool0']['allocated_capacity_gb'], 384)
        self.assertEqual(
            stats['pools']['pool1']['allocated_capacity_gb'], 512)
        self.assertEqual(
            stats['pools']['pool2']['allocated_capacity_gb'], 1024)

        # NOTE(jdg): On the create we have host='xyz', BUT
        # here we do a db.volume_get, and now the host has
        # been updated to xyz#pool-name.  Note this is
        # done via the managers init, which calls the drivers
        # get_pool method, which in the legacy case is going
        # to be volume_backend_name or None

        vol0 = db.volume_get(context.get_admin_context(), vol0['id'])
        self.assertEqual(vol0['host'],
                         volutils.append_host(CONF.host, 'LVM'))
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
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 0)
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.create_volume,
                          self.context, volume_id)

        volume = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(volume.status, "error")
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
        # NOTE(flaper87): Set initialized to False
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
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 0)
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.delete_volume,
                          self.context, volume_id)

        volume = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(volume.status, "error_deleting")
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_create_delete_volume(self):
        """Test volume can be created and deleted."""
        # Need to stub out reserve, commit, and rollback
        def fake_reserve(context, expire=None, project_id=None, **deltas):
            return ["RESERVATION"]

        def fake_commit(context, reservations, project_id=None):
            pass

        def fake_rollback(context, reservations, project_id=None):
            pass

        self.stubs.Set(QUOTAS, "reserve", fake_reserve)
        self.stubs.Set(QUOTAS, "commit", fake_commit)
        self.stubs.Set(QUOTAS, "rollback", fake_rollback)

        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **self.volume_params)
        volume_id = volume['id']
        self.assertIsNone(volume['encryption_key_id'])
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 0)
        self.volume.create_volume(self.context, volume_id)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg['event_type'], 'volume.create.start')
        expected = {
            'status': 'creating',
            'host': socket.gethostname(),
            'display_name': 'test_volume',
            'availability_zone': 'nova',
            'tenant_id': 'fake',
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
        }
        self.assertDictMatch(msg['payload'], expected)
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg['event_type'], 'volume.create.end')
        expected['status'] = 'available'
        self.assertDictMatch(msg['payload'], expected)
        self.assertEqual(volume_id, db.volume_get(context.get_admin_context(),
                         volume_id).id)

        self.volume.delete_volume(self.context, volume_id)
        vol = db.volume_get(context.get_admin_context(read_deleted='yes'),
                            volume_id)
        self.assertEqual(vol['status'], 'deleted')
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 4)
        msg = fake_notifier.NOTIFICATIONS[2]
        self.assertEqual(msg['event_type'], 'volume.delete.start')
        self.assertDictMatch(msg['payload'], expected)
        msg = fake_notifier.NOTIFICATIONS[3]
        self.assertEqual(msg['event_type'], 'volume.delete.end')
        self.assertDictMatch(msg['payload'], expected)
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
        self.assertEqual(result_meta, test_meta)

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

    def test_create_volume_uses_default_availability_zone(self):
        """Test setting availability_zone correctly during volume create."""
        volume_api = cinder.volume.api.API()

        def fake_list_availability_zones(enable_cache=False):
            return ({'name': 'az1', 'available': True},
                    {'name': 'az2', 'available': True},
                    {'name': 'default-az', 'available': True})

        self.stubs.Set(volume_api,
                       'list_availability_zones',
                       fake_list_availability_zones)

        # Test backwards compatibility, default_availability_zone not set
        self.override_config('storage_availability_zone', 'az2')
        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description')
        self.assertEqual(volume['availability_zone'], 'az2')

        self.override_config('default_availability_zone', 'default-az')
        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description')
        self.assertEqual(volume['availability_zone'], 'default-az')

    def test_create_volume_with_volume_type(self):
        """Test volume creation with default volume type."""
        def fake_reserve(context, expire=None, project_id=None, **deltas):
            return ["RESERVATION"]

        def fake_commit(context, reservations, project_id=None):
            pass

        def fake_rollback(context, reservations, project_id=None):
            pass

        self.stubs.Set(QUOTAS, "reserve", fake_reserve)
        self.stubs.Set(QUOTAS, "commit", fake_commit)
        self.stubs.Set(QUOTAS, "rollback", fake_rollback)

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
        self.assertEqual(volume['volume_type_id'], db_vol_type.get('id'))
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
        self.assertEqual(volume['volume_type_id'], db_vol_type.get('id'))

    def test_create_volume_with_encrypted_volume_type(self):
        self.stubs.Set(keymgr, "API", fake_keymgr.fake_api)

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
        self.assertEqual(volume['volume_type_id'], db_vol_type.get('id'))
        self.assertIsNotNone(volume['encryption_key_id'])

    def test_create_volume_with_provider_id(self):
        volume_params_with_provider_id = dict(provider_id='1111-aaaa',
                                              **self.volume_params)

        volume = tests_utils.create_volume(self.context,
                                           **volume_params_with_provider_id)

        self.volume.create_volume(self.context, volume['id'])
        self.assertEqual('1111-aaaa', volume['provider_id'])

    def test_create_delete_volume_with_encrypted_volume_type(self):
        self.stubs.Set(keymgr, "API", fake_keymgr.fake_api)

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
        self.assertEqual(volume['volume_type_id'], db_vol_type.get('id'))
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
            self.assertEqual(volume_stats['key1'],
                             fake_capabilities['key1'])
            self.assertEqual(volume_stats['key2'],
                             fake_capabilities['key2'])

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

        self.mox.UnsetStubs()
        self.volume.delete_volume(self.context, volume_id)

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

    def test_get_all_tenants_value(self):
        """Validate allowable values for --all_tenants

           Note: type of the value could be String, Boolean, or Int
        """
        api = cinder.volume.api.API()

        self.assertTrue(api._get_all_tenants_value({'all_tenants': True}))
        self.assertTrue(api._get_all_tenants_value({'all_tenants': 1}))
        self.assertFalse(api._get_all_tenants_value({'all_tenants': 'False'}))
        self.assertFalse(api._get_all_tenants_value({'all_tenants': '0'}))
        self.assertRaises(exception.InvalidInput,
                          api._get_all_tenants_value,
                          {'all_tenants': 'No'})
        self.assertRaises(exception.InvalidInput,
                          api._get_all_tenants_value,
                          {'all_tenants': -1})

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
        """"Test delete volume moves on if the volume does not exist."""
        volume_id = '12345678-1234-5678-1234-567812345678'
        self.assertTrue(self.volume.delete_volume(self.context, volume_id))
        self.assertTrue(mock_get_volume.called)

    def test_create_volume_from_snapshot(self):
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
        self.volume.create_volume(self.context, volume_dst['id'], snapshot_id)
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

        db.volume_type_create(context.get_admin_context(),
                              {'name': 'foo', 'extra_specs': {}})
        db.volume_type_create(context.get_admin_context(),
                              {'name': 'biz', 'extra_specs': {}})

        foo_type = db.volume_type_get_by_name(context.get_admin_context(),
                                              'foo')
        biz_type = db.volume_type_get_by_name(context.get_admin_context(),
                                              'biz')

        snapshot = {'id': 1234,
                    'status': 'available',
                    'volume_size': 10,
                    'volume_type_id': biz_type['id']}

        # Make sure the case of specifying a type that
        # doesn't match the snapshots type fails
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          volume_type=foo_type,
                          snapshot=snapshot)

        # Make sure that trying to specify a type
        # when the snapshots type is None fails
        snapshot['volume_type_id'] = None
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          volume_type=foo_type,
                          snapshot=snapshot)

        snapshot['volume_type_id'] = foo_type['id']
        volume_api.create(self.context, size=1, name='fake_name',
                          description='fake_desc', volume_type=foo_type,
                          snapshot=snapshot)

        db.volume_type_destroy(context.get_admin_context(),
                               foo_type['id'])
        db.volume_type_destroy(context.get_admin_context(),
                               biz_type['id'])

    @mock.patch('cinder.volume.flows.api.create_volume.get_flow')
    def test_create_volume_from_source_with_types(self, _get_flow):
        """Test volume create from source with types including mistmatch."""
        volume_api = cinder.volume.api.API()

        db.volume_type_create(context.get_admin_context(),
                              {'name': 'foo', 'extra_specs': {}})
        db.volume_type_create(context.get_admin_context(),
                              {'name': 'biz', 'extra_specs': {}})

        foo_type = db.volume_type_get_by_name(context.get_admin_context(),
                                              'foo')
        biz_type = db.volume_type_get_by_name(context.get_admin_context(),
                                              'biz')

        source_vol = {'id': 1234,
                      'status': 'available',
                      'volume_size': 10,
                      'volume_type': biz_type,
                      'volume_type_id': biz_type['id']}

        # Make sure the case of specifying a type that
        # doesn't match the snapshots type fails
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
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          volume_type=foo_type,
                          source_volume=source_vol)

        source_vol['volume_type_id'] = biz_type['id']
        source_vol['volume_type'] = biz_type
        volume_api.create(self.context, size=1, name='fake_name',
                          description='fake_desc', volume_type=biz_type,
                          source_volume=source_vol)

        db.volume_type_destroy(context.get_admin_context(),
                               foo_type['id'])
        db.volume_type_destroy(context.get_admin_context(),
                               biz_type['id'])

    def test_create_snapshot_driver_not_initialized(self):
        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src['id'])
        snapshot_id = self._create_snapshot(volume_src['id'],
                                            size=volume_src['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)

        # NOTE(flaper87): Set initialized to False
        self.volume.driver._initialized = False

        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.create_snapshot,
                          self.context, volume_src['id'], snapshot_obj)

        # NOTE(flaper87): The volume status should be error.
        snapshot = db.snapshot_get(context.get_admin_context(), snapshot_id)
        self.assertEqual(snapshot.status, "error")

        # NOTE(flaper87): Set initialized to True,
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

    def test_create_volume_from_snapshot_check_locks(self):
        # mock the synchroniser so we can record events
        self.stubs.Set(utils, 'synchronized', self._mock_synchronized)

        self.stubs.Set(self.volume.driver, 'create_volume_from_snapshot',
                       lambda *args, **kwargs: None)

        orig_flow = engine.ActionEngine.run

        def mock_flow_run(*args, **kwargs):
            # ensure the lock has been taken
            self.assertEqual(len(self.called), 1)
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
                                  snapshot_id=snap_id)
        self.assertEqual(len(self.called), 2)
        self.assertEqual(dst_vol_id, db.volume_get(admin_ctxt, dst_vol_id).id)
        self.assertEqual(snap_id,
                         db.volume_get(admin_ctxt, dst_vol_id).snapshot_id)

        # locked
        self.volume.delete_volume(self.context, dst_vol_id)
        self.assertEqual(len(self.called), 4)

        # locked
        self.volume.delete_snapshot(self.context, snapshot_obj)
        self.assertEqual(len(self.called), 6)

        # locked
        self.volume.delete_volume(self.context, src_vol_id)
        self.assertEqual(len(self.called), 8)

        self.assertEqual(self.called,
                         ['lock-%s' % ('%s-delete_snapshot' % (snap_id)),
                          'unlock-%s' % ('%s-delete_snapshot' % (snap_id)),
                          'lock-%s' % ('%s-delete_volume' % (dst_vol_id)),
                          'unlock-%s' % ('%s-delete_volume' % (dst_vol_id)),
                          'lock-%s' % ('%s-delete_snapshot' % (snap_id)),
                          'unlock-%s' % ('%s-delete_snapshot' % (snap_id)),
                          'lock-%s' % ('%s-delete_volume' % (src_vol_id)),
                          'unlock-%s' % ('%s-delete_volume' % (src_vol_id))])

    def test_create_volume_from_volume_check_locks(self):
        # mock the synchroniser so we can record events
        self.stubs.Set(utils, 'synchronized', self._mock_synchronized)
        self.stubs.Set(utils, 'execute', self._fake_execute)

        orig_flow = engine.ActionEngine.run

        def mock_flow_run(*args, **kwargs):
            # ensure the lock has been taken
            self.assertEqual(len(self.called), 1)
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
                                  source_volid=src_vol_id)
        self.assertEqual(len(self.called), 2)
        self.assertEqual(dst_vol_id, db.volume_get(admin_ctxt, dst_vol_id).id)
        self.assertEqual(src_vol_id,
                         db.volume_get(admin_ctxt, dst_vol_id).source_volid)

        # locked
        self.volume.delete_volume(self.context, dst_vol_id)
        self.assertEqual(len(self.called), 4)

        # locked
        self.volume.delete_volume(self.context, src_vol_id)
        self.assertEqual(len(self.called), 6)

        self.assertEqual(self.called,
                         ['lock-%s' % ('%s-delete_volume' % (src_vol_id)),
                          'unlock-%s' % ('%s-delete_volume' % (src_vol_id)),
                          'lock-%s' % ('%s-delete_volume' % (dst_vol_id)),
                          'unlock-%s' % ('%s-delete_volume' % (dst_vol_id)),
                          'lock-%s' % ('%s-delete_volume' % (src_vol_id)),
                          'unlock-%s' % ('%s-delete_volume' % (src_vol_id))])

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
                               volume_id=dst_vol_id, source_volid=src_vol_id)
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
                                            **self.volume_params)
        self.volume.create_volume(self.context,
                                  dst_vol['id'],
                                  source_volid=src_vol_id)

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
            dst_vol['id'],
            source_volid=src_vol_id)

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
        snapshot_ref = db.snapshot_get(self.context, snapshot_id)['status']
        self.assertEqual('available', snapshot_ref)

        dst_vol = tests_utils.create_volume(self.context,
                                            **self.volume_params)
        self._raise_metadata_copy_failure(
            'volume_glance_metadata_copy_to_volume',
            dst_vol['id'],
            snapshot_id=snapshot_id)

        # cleanup resource
        db.snapshot_destroy(self.context, snapshot_id)
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
            dst_vol['id'],
            source_volid=src_vol_id)

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
        snapshot_ref = db.snapshot_get(self.context, snapshot_id)['status']
        self.assertEqual('available', snapshot_ref)

        # create volume from snapshot
        dst_vol = tests_utils.create_volume(self.context,
                                            **self.volume_params)
        self.volume.create_volume(self.context,
                                  dst_vol['id'],
                                  snapshot_id=snapshot_id)

        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_glance_metadata_copy_to_volume,
                          self.context, dst_vol['id'], snapshot_id)

        # ensure that status of volume is 'available'
        vol = db.volume_get(self.context, dst_vol['id'])
        self.assertEqual('available', vol['status'])

        # cleanup resource
        db.snapshot_destroy(self.context, snapshot_id)
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
            source_replicaid=volume['id'],
            **self.volume_params)
        self.volume.create_volume(self.context, volume_dst['id'],
                                  source_replicaid=volume['id'])

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
                               volume_id=dst_vol_id, snapshot_id=snap_id)
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
        self.assertRaises(exception.SnapshotNotFound, gthreads[0].wait)

        # locked
        self.volume.delete_volume(self.context, src_vol_id)
        # make sure it is gone
        self.assertRaises(exception.VolumeNotFound, db.volume_get,
                          self.context, src_vol_id)

    def test_create_volume_from_snapshot_with_encryption(self):
        """Test volume can be created from a snapshot of
        an encrypted volume.
        """
        self.stubs.Set(keymgr, 'API', fake_keymgr.fake_api)

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
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          snapshot=snapshot)

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
        snapshot_obj = objects.Snapshot.get_by_id(self.context,
                                                  snapshot['id'])
        self.volume.create_snapshot(self.context, volume_src['id'],
                                    snapshot_obj)
        snapshot = db.snapshot_get(self.context, snapshot['id'])

        volume_dst = volume_api.create(self.context,
                                       size=1,
                                       name='fake_name',
                                       description='fake_desc',
                                       snapshot=snapshot)
        self.assertEqual(volume_dst['availability_zone'], 'az2')

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

    @mock.patch.object(db, 'volume_admin_metadata_get')
    @mock.patch.object(db, 'volume_get')
    @mock.patch.object(db, 'volume_update')
    def test_initialize_connection_fetchqos(self,
                                            _mock_volume_update,
                                            _mock_volume_get,
                                            _mock_volume_admin_metadata_get):
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
            mock.patch.object(cinder.tests.fake_driver.FakeISCSIDriver,
                              'initialize_connection') as driver_init:
            type_qos.return_value = dict(qos_specs=qos_values)
            driver_init.return_value = {'data': {}}
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
                                                  mock_metadata_get):

        fake_admin_meta = {'fake-key': 'fake-value'}
        fake_volume = {'volume_type_id': None,
                       'name': 'fake_name',
                       'host': 'fake_host',
                       'id': 'fake_volume_id',
                       'volume_admin_metadata': fake_admin_meta}

        mock_volume_get.return_value = fake_volume
        mock_volume_update.return_value = fake_volume
        connector = {'ip': 'IP', 'initiator': 'INITIATOR'}
        mock_driver_init.return_value = {
            'driver_volume_type': 'iscsi',
            'data': {'access_mode': 'rw'}
        }
        mock_data_get.return_value = []
        self.volume.initialize_connection(self.context, 'id', connector)
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
        self.volume.initialize_connection(self.context, 'id', connector)
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
        self.assertEqual(vol['status'], "in-use")
        self.assertEqual('attached', attachment['attach_status'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 2)
        expected = dict(readonly='True', attached_mode='ro')
        ret = {}
        for item in admin_metadata:
            ret.update({item['key']: item['value']})
        self.assertDictMatch(ret, expected)

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
        self.assertEqual(True, vol['multiattach'])
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
        self.assertEqual(True, vol['multiattach'])
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
        self.assertDictMatch(ret, expected)

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
        self.assertDictMatch(ret, expected)
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
        self.assertDictMatch(ret, expected)
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)

        self.assertEqual('ro', conn_info['data']['access_mode'])

        self.volume.detach_volume(self.context, volume_id, attachment['id'])
        vol = db.volume_get(self.context, volume_id)
        attachment = vol['volume_attachment']
        self.assertEqual('available', vol['status'])
        self.assertEqual('detached', vol['attach_status'])
        self.assertEqual(attachment, [])
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
        self.assertDictMatch(ret, expected)
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
        self.assertEqual(attachment, [])
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
        self.assertDictMatch(ret, expected)

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
        self.assertDictMatch(ret, expected)

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
            'id': FAKE_UUID,
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

    def test_reserve_volume_bad_status(self):
        fake_volume = {
            'id': FAKE_UUID,
            'status': 'attaching'
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
            'id': FAKE_UUID,
            'status': 'attaching'
        }
        fake_attachments = [{'volume_id': FAKE_UUID,
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

        for _index in xrange(100):
            tests_utils.create_volume(self.context, **self.volume_params)
        for volume_id in volume_ids:
            self.volume.delete_volume(self.context, volume_id)

    def test_multi_node(self):
        # TODO(termie): Figure out how to test with two nodes,
        # each of them having a different FLAG for storage_node
        # This will allow us to test cross-node interactions
        pass

    @staticmethod
    def _create_snapshot(volume_id, size='0', metadata=None):
        """Create a snapshot object."""
        snap = {}
        snap['volume_size'] = size
        snap['user_id'] = 'fake'
        snap['project_id'] = 'fake'
        snap['volume_id'] = volume_id
        snap['status'] = "creating"
        if metadata is not None:
            snap['metadata'] = metadata
        return db.snapshot_create(context.get_admin_context(), snap)

    def test_create_delete_snapshot(self):
        """Test snapshot can be created and deleted."""
        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **self.volume_params)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 0)
        self.volume.create_volume(self.context, volume['id'])
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg['event_type'], 'volume.create.start')
        self.assertEqual(msg['payload']['status'], 'creating')
        self.assertEqual(msg['priority'], 'INFO')
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg['event_type'], 'volume.create.end')
        self.assertEqual(msg['payload']['status'], 'available')
        self.assertEqual(msg['priority'], 'INFO')
        if len(fake_notifier.NOTIFICATIONS) > 2:
            # Cause an assert to print the unexpected item
            self.assertFalse(fake_notifier.NOTIFICATIONS[2])
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)

        snapshot_id = self._create_snapshot(volume['id'],
                                            size=volume['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, volume['id'], snapshot_obj)
        self.assertEqual(snapshot_id,
                         db.snapshot_get(context.get_admin_context(),
                                         snapshot_id).id)
        msg = fake_notifier.NOTIFICATIONS[2]
        self.assertEqual(msg['event_type'], 'snapshot.create.start')
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
            'availability_zone': 'nova'
        }
        self.assertDictMatch(msg['payload'], expected)
        msg = fake_notifier.NOTIFICATIONS[3]
        self.assertEqual(msg['event_type'], 'snapshot.create.end')
        expected['status'] = 'available'
        self.assertDictMatch(msg['payload'], expected)

        if len(fake_notifier.NOTIFICATIONS) > 4:
            # Cause an assert to print the unexpected item
            self.assertFalse(fake_notifier.NOTIFICATIONS[4])

        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 4)

        self.volume.delete_snapshot(self.context, snapshot_obj)
        msg = fake_notifier.NOTIFICATIONS[4]
        self.assertEqual(msg['event_type'], 'snapshot.delete.start')
        expected['status'] = 'available'
        self.assertDictMatch(msg['payload'], expected)
        msg = fake_notifier.NOTIFICATIONS[5]
        self.assertEqual(msg['event_type'], 'snapshot.delete.end')
        self.assertDictMatch(msg['payload'], expected)

        if len(fake_notifier.NOTIFICATIONS) > 6:
            # Cause an assert to print the unexpected item
            self.assertFalse(fake_notifier.NOTIFICATIONS[6])

        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 6)

        snap = db.snapshot_get(context.get_admin_context(read_deleted='yes'),
                               snapshot_id)
        self.assertEqual(snap['status'], 'deleted')
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
        snapshot_id = snapshot['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)

        snap = db.snapshot_get(context.get_admin_context(), snapshot_id)
        result_dict = dict(snap.iteritems())
        result_meta = {
            result_dict['snapshot_metadata'][0].key:
            result_dict['snapshot_metadata'][0].value}
        self.assertEqual(result_meta, test_meta)
        self.volume.delete_snapshot(self.context, snapshot_obj)
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

    @mock.patch.object(QUOTAS, 'commit',
                       side_effect=exception.QuotaError(
                           'Snapshot quota commit failed!'))
    def test_create_snapshot_failed_quota_commit(self, mock_snapshot):
        """Test exception handling when snapshot quota commit failed."""
        test_volume = tests_utils.create_volume(
            self.context,
            **self.volume_params)
        self.volume.create_volume(self.context, test_volume['id'])
        test_volume['status'] = 'available'
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.QuotaError,
                          volume_api.create_snapshot,
                          self.context,
                          test_volume,
                          'fake_name',
                          'fake_description')

    def test_cannot_delete_volume_in_use(self):
        """Test volume can't be deleted in invalid stats."""
        # create a volume and assign to host
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        volume['status'] = 'in-use'
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
        self.assertEqual(volume['status'], 'deleting')

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
        snapshot_id = self._create_snapshot(volume['id'],
                                            size=volume['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, volume['id'], snapshot_obj)
        self.assertEqual(snapshot_id,
                         db.snapshot_get(context.get_admin_context(),
                                         snapshot_id).id)

        volume['status'] = 'available'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete,
                          self.context,
                          volume)
        self.volume.delete_snapshot(self.context, snapshot_obj)
        self.volume.delete_volume(self.context, volume['id'])

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

    def test_can_delete_errored_snapshot(self):
        """Test snapshot can be created and deleted."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        snapshot_id = self._create_snapshot(volume['id'],
                                            size=volume['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, volume['id'], snapshot_obj)
        snapshot = db.snapshot_get(context.get_admin_context(),
                                   snapshot_id)

        volume_api = cinder.volume.api.API()

        snapshot['status'] = 'badstatus'
        self.assertRaises(exception.InvalidSnapshot,
                          volume_api.delete_snapshot,
                          self.context,
                          snapshot)

        snapshot['status'] = 'error'
        self.volume.delete_snapshot(self.context, snapshot_obj)
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
        db.snapshot_destroy(self.context, snapshot_ref['id'])
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
        db.snapshot_destroy(self.context, snapshot_ref['id'])
        db.volume_destroy(self.context, volume['id'])

    def test_create_snapshot_from_bootable_volume(self):
        """Test create snapshot from bootable volume."""
        # create bootable volume from image
        volume = self._create_volume_from_image()
        volume_id = volume['id']
        self.assertEqual(volume['status'], 'available')
        self.assertEqual(volume['bootable'], True)

        # get volume's volume_glance_metadata
        ctxt = context.get_admin_context()
        vol_glance_meta = db.volume_glance_metadata_get(ctxt, volume_id)
        self.assertTrue(vol_glance_meta)

        # create snapshot from bootable volume
        snap_id = self._create_snapshot(volume_id)['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snap_id)
        self.volume.create_snapshot(ctxt, volume_id, snapshot_obj)

        # get snapshot's volume_glance_metadata
        snap_glance_meta = db.volume_snapshot_glance_metadata_get(
            ctxt, snap_id)
        self.assertTrue(snap_glance_meta)

        # ensure that volume's glance metadata is copied
        # to snapshot's glance metadata
        self.assertEqual(len(vol_glance_meta), len(snap_glance_meta))
        vol_glance_dict = dict((x.key, x.value) for x in vol_glance_meta)
        snap_glance_dict = dict((x.key, x.value) for x in snap_glance_meta)
        self.assertDictMatch(vol_glance_dict, snap_glance_dict)

        # ensure that snapshot's status is changed to 'available'
        snapshot_ref = db.snapshot_get(ctxt, snap_id)['status']
        self.assertEqual('available', snapshot_ref)

        # cleanup resource
        db.snapshot_destroy(ctxt, snap_id)
        db.volume_destroy(ctxt, volume_id)

    def test_create_snapshot_from_bootable_volume_fail(self):
        """Test create snapshot from bootable volume.

        But it fails to volume_glance_metadata_copy_to_snapshot.
        As a result, status of snapshot is changed to ERROR.
        """
        # create bootable volume from image
        volume = self._create_volume_from_image()
        volume_id = volume['id']
        self.assertEqual(volume['status'], 'available')
        self.assertEqual(volume['bootable'], True)

        # get volume's volume_glance_metadata
        ctxt = context.get_admin_context()
        vol_glance_meta = db.volume_glance_metadata_get(ctxt, volume_id)
        self.assertTrue(vol_glance_meta)
        snap = self._create_snapshot(volume_id)
        snap_id = snap['id']
        snap_stat = snap['status']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snap_id)
        self.assertTrue(snap_id)
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
                              snapshot_obj)

        # get snapshot's volume_glance_metadata
        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_snapshot_glance_metadata_get,
                          ctxt, snap_id)

        # ensure that status of snapshot is 'error'
        snapshot_ref = db.snapshot_get(ctxt, snap_id)['status']
        self.assertEqual('error', snapshot_ref)

        # cleanup resource
        db.snapshot_destroy(ctxt, snap_id)
        db.volume_destroy(ctxt, volume_id)

    def test_create_snapshot_from_bootable_volume_with_volume_metadata_none(
            self):
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_id = volume['id']

        self.volume.create_volume(self.context, volume_id)
        # set bootable flag of volume to True
        db.volume_update(self.context, volume_id, {'bootable': True})

        snapshot_id = self._create_snapshot(volume['id'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, volume['id'], snapshot_obj)
        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_snapshot_glance_metadata_get,
                          self.context, snapshot_id)

        # ensure that status of snapshot is 'available'
        snapshot_ref = db.snapshot_get(self.context, snapshot_id)['status']
        self.assertEqual('available', snapshot_ref)

        # cleanup resource
        db.snapshot_destroy(self.context, snapshot_id)
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
        snapshot_id = self._create_snapshot(volume_id,
                                            size=volume['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, volume_id, snapshot_obj)

        self.mox.StubOutWithMock(self.volume.driver, 'delete_snapshot')

        self.volume.driver.delete_snapshot(
            mox.IgnoreArg()).AndRaise(
            exception.SnapshotIsBusy(snapshot_name='fake'))
        self.mox.ReplayAll()
        self.volume.delete_snapshot(self.context, snapshot_obj)
        snapshot_ref = db.snapshot_get(self.context, snapshot_id)
        self.assertEqual(snapshot_id, snapshot_ref.id)
        self.assertEqual("available", snapshot_ref.status)

        self.mox.UnsetStubs()
        self.volume.delete_snapshot(self.context, snapshot_obj)
        self.volume.delete_volume(self.context, volume_id)

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
        snapshot_id = self._create_snapshot(volume_id)['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)
        self.volume.create_snapshot(self.context, volume_id, snapshot_obj)

        self.mox.StubOutWithMock(self.volume.driver, 'delete_snapshot')

        self.volume.driver.delete_snapshot(
            mox.IgnoreArg()).AndRaise(
            exception.SnapshotIsBusy(snapshot_name='fake'))
        self.mox.ReplayAll()
        self.volume.delete_snapshot(self.context, snapshot_obj)
        snapshot_ref = db.snapshot_get(self.context, snapshot_id)
        self.assertEqual(snapshot_id, snapshot_ref.id)
        self.assertEqual("available", snapshot_ref.status)

        self.mox.UnsetStubs()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.delete_snapshot,
                          self.context,
                          snapshot_obj)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)

    def _create_volume_from_image(self, fakeout_copy_image_to_volume=False,
                                  fakeout_clone_image=False):
        """Test function of create_volume_from_image.

        Test cases call this function to create a volume from image, caller
        can choose whether to fake out copy_image_to_volume and conle_image,
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
            self.stubs.Set(self.volume, '_copy_image_to_volume',
                           fake_copy_image_to_volume)

        image_id = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        volume_id = tests_utils.create_volume(self.context,
                                              **self.volume_params)['id']
        # creating volume testdata
        try:
            request_spec = {'volume_properties': self.volume_params}
            self.volume.create_volume(self.context,
                                      volume_id,
                                      request_spec,
                                      image_id=image_id)
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
        self.assertEqual(volume['status'], 'available')
        self.assertEqual(volume['bootable'], True)
        self.volume.delete_volume(self.context, volume['id'])

    def test_create_volume_from_image_not_cloned_status_available(self):
        """Test create volume from image via full copy.

        Verify that after copying image to volume, it is in available
        state and is bootable.
        """
        volume = self._create_volume_from_image(fakeout_clone_image=True)
        self.assertEqual(volume['status'], 'available')
        self.assertEqual(volume['bootable'], True)
        self.volume.delete_volume(self.context, volume['id'])

    def test_create_volume_from_image_exception(self):
        """Verify that create volume from a non-existing image, the volume
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
                          volume_id, None, None, None,
                          None,
                          FAKE_UUID)
        volume = db.volume_get(self.context, volume_id)
        self.assertEqual(volume['status'], "error")
        self.assertEqual(volume['bootable'], False)
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

    def test_create_volume_from_exact_sized_image(self):
        """Verify that an image which is exactly the same size as the
        volume, will work correctly.
        """
        try:
            volume_id = None
            volume_api = cinder.volume.api.API(
                image_service=FakeImageService())
            volume = volume_api.create(self.context, 2, 'name', 'description',
                                       image_id=1)
            volume_id = volume['id']
            self.assertEqual(volume['status'], 'creating')

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

    def _do_test_create_volume_with_size(self, size):
        def fake_reserve(context, expire=None, project_id=None, **deltas):
            return ["RESERVATION"]

        def fake_commit(context, reservations, project_id=None):
            pass

        def fake_rollback(context, reservations, project_id=None):
            pass

        self.stubs.Set(QUOTAS, "reserve", fake_reserve)
        self.stubs.Set(QUOTAS, "commit", fake_commit)
        self.stubs.Set(QUOTAS, "rollback", fake_rollback)

        volume_api = cinder.volume.api.API()

        volume = volume_api.create(self.context,
                                   size,
                                   'name',
                                   'description')
        self.assertEqual(volume['size'], int(size))

    def test_create_volume_int_size(self):
        """Test volume creation with int size."""
        self._do_test_create_volume_with_size(2)

    def test_create_volume_string_size(self):
        """Test volume creation with string size."""
        self._do_test_create_volume_with_size('2')

    def test_create_volume_with_bad_size(self):
        def fake_reserve(context, expire=None, project_id=None, **deltas):
            return ["RESERVATION"]

        def fake_commit(context, reservations, project_id=None):
            pass

        def fake_rollback(context, reservations, project_id=None):
            pass

        self.stubs.Set(QUOTAS, "reserve", fake_reserve)
        self.stubs.Set(QUOTAS, "commit", fake_commit)
        self.stubs.Set(QUOTAS, "rollback", fake_rollback)

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
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.assertRaises(exception.InvalidVolume, volume_api.begin_detaching,
                          self.context, volume)
        volume['status'] = "in-use"
        volume['attach_status'] = "detached"
        # Should raise an error since not attached
        self.assertRaises(exception.InvalidVolume, volume_api.begin_detaching,
                          self.context, volume)
        volume['attach_status'] = "attached"
        # Ensure when attached no exception raised
        volume_api.begin_detaching(self.context, volume)

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
        self.assertEqual(volume['status'], "detaching")
        volume_api.roll_detaching(self.context, volume)
        volume = db.volume_get(self.context, volume['id'])
        self.assertEqual(volume['status'], "in-use")

    def test_volume_api_update(self):
        # create a raw vol
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        # use volume.api to update name
        volume_api = cinder.volume.api.API()
        update_dict = {'display_name': 'test update name'}
        volume_api.update(self.context, volume, update_dict)
        # read changes from db
        vol = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEqual(vol['display_name'], 'test update name')

    def test_volume_api_update_snapshot(self):
        # create raw snapshot
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        snapshot = self._create_snapshot(volume['id'])
        snapshot_obj = objects.Snapshot.get_by_id(self.context,
                                                  snapshot['id'])
        self.assertIsNone(snapshot['display_name'])
        # use volume.api to update name
        volume_api = cinder.volume.api.API()
        update_dict = {'display_name': 'test update name'}
        volume_api.update_snapshot(self.context, snapshot_obj, update_dict)
        # read changes from db
        snap = db.snapshot_get(context.get_admin_context(), snapshot['id'])
        self.assertEqual(snap['display_name'], 'test update name')

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
        self.assertEqual(volume['status'], 'extending')

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

        # NOTE(flaper87): Set initialized to False
        self.volume.driver._initialized = False

        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.extend_volume,
                          self.context, volume['id'], 3,
                          fake_reservations)

        volume = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEqual(volume.status, 'error_extending')

        # NOTE(flaper87): Set initialized to True,
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
            self.assertEqual(volume['size'], 2)
            self.assertEqual(volume['status'], 'error_extending')

        # Test driver success
        with mock.patch.object(self.volume.driver,
                               'extend_volume') as extend_volume:
            extend_volume.return_value = fake_extend
            volume['status'] = 'extending'
            self.volume.extend_volume(self.context, volume['id'], '4',
                                      fake_reservations)
            volume = db.volume_get(context.get_admin_context(), volume['id'])
            self.assertEqual(volume['size'], 4)
            self.assertEqual(volume['status'], 'available')

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
        self.assertEqual(volumes_in_use, 100)
        volume['status'] = 'available'
        volume['host'] = 'fakehost'
        volume['volume_type_id'] = vol_type.get('id')

        volume_api.extend(self.context, volume, 200)

        try:
            usage = db.quota_usage_get(elevated, project_id, 'gigabytes_type')
            volumes_reserved = usage.reserved
        except exception.QuotaUsageNotFound:
            volumes_reserved = 0

        self.assertEqual(volumes_reserved, 100)

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
            source_replicaid=volume_src['id'],
            **self.volume_params)
        self.volume.create_volume(self.context, volume_dst['id'],
                                  source_replicaid=volume_src['id'])
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
        self.volume.create_volume(self.context, volume_dst['id'],
                                  source_volid=volume_src['id'])
        self.assertEqual('available',
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).status)
        self.volume.delete_volume(self.context, volume_dst['id'])
        self.volume.delete_volume(self.context, volume_src['id'])

    def test_create_volume_from_sourcevol_fail_wrong_az(self):
        """Test volume can't be cloned from an other volume in different az."""
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

        volume_src = db.volume_get(self.context, volume_src['id'])

        volume_dst = volume_api.create(self.context,
                                       size=1,
                                       name='fake_name',
                                       description='fake_desc',
                                       source_volume=volume_src)
        self.assertEqual(volume_dst['availability_zone'], 'az2')

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
        self.volume.create_volume(self.context, volume_dst['id'],
                                  source_volid=volume_src['id'])
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
                    self.assertEqual(meta_dst.value, meta_src.value)
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
                          volume_dst['id'], None, None, None, None, None,
                          volume_src['id'])
        self.assertEqual(volume_src['status'], 'creating')
        self.volume.delete_volume(self.context, volume_dst['id'])
        self.volume.delete_volume(self.context, volume_src['id'])

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

        volume_api = cinder.volume.api.API()
        azs = volume_api.list_availability_zones()
        azs = list(azs).sort()

        expected = [
            {'name': 'pung', 'available': False},
            {'name': 'pong', 'available': True},
            {'name': 'ping', 'available': True},
        ].sort()

        self.assertEqual(expected, azs)

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
        self.assertEqual(volume['host'], 'newhost')
        self.assertIsNone(volume['migration_status'])

    def test_migrate_volume_error(self):
        def fake_create_volume(ctxt, volume, host, req_spec, filters,
                               allow_reschedule=True):
            db.volume_update(ctxt, volume['id'],
                             {'status': 'available'})

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
            self.assertIsNone(volume['migration_status'])
            self.assertEqual('available', volume['status'])

    @mock.patch.object(compute.nova.API, 'update_server_volume')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                'migrate_volume_completion')
    @mock.patch('cinder.db.volume_get')
    def test_migrate_volume_generic(self, volume_get,
                                    migrate_volume_completion,
                                    update_server_volume):
        fake_volume_id = 'fake_volume_id'
        fake_new_volume = {'status': 'available', 'id': fake_volume_id}
        host_obj = {'host': 'newhost', 'capabilities': {}}
        volume_get.return_value = fake_new_volume
        volume = tests_utils.create_volume(self.context, size=1,
                                           host=CONF.host)
        with mock.patch.object(self.volume.driver, 'copy_volume_data') as \
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

    @mock.patch.object(compute.nova.API, 'update_server_volume')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                'migrate_volume_completion')
    @mock.patch('cinder.db.volume_get')
    def test_migrate_volume_generic_attached_volume(self, volume_get,
                                                    migrate_volume_completion,
                                                    update_server_volume):
        attached_host = 'some-host'
        fake_volume_id = 'fake_volume_id'
        fake_new_volume = {'status': 'available', 'id': fake_volume_id}
        host_obj = {'host': 'newhost', 'capabilities': {}}
        fake_uuid = fakes.get_fake_uuid()
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
        with mock.patch.object(self.volume.driver, 'copy_volume_data') as \
                mock_copy_volume:
            self.volume._migrate_volume_generic(self.context, volume,
                                                host_obj, None)
            self.assertFalse(mock_copy_volume.called)
            self.assertFalse(migrate_volume_completion.called)

    @mock.patch.object(volume_rpcapi.VolumeAPI, 'update_migrated_volume')
    @mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume')
    @mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')
    def test_migrate_volume_for_volume_generic(self, create_volume,
                                               delete_volume,
                                               update_migrated_volume):
        fake_volume = tests_utils.create_volume(self.context, size=1,
                                                host=CONF.host)

        def fake_create_volume(ctxt, volume, host, req_spec, filters,
                               allow_reschedule=True):
            db.volume_update(ctxt, volume['id'],
                             {'status': 'available'})

        host_obj = {'host': 'newhost', 'capabilities': {}}
        with mock.patch.object(self.volume.driver, 'migrate_volume') as \
                mock_migrate_volume,\
                mock.patch.object(self.volume.driver, 'copy_volume_data'):
            create_volume.side_effect = fake_create_volume
            self.volume.migrate_volume(self.context, fake_volume['id'],
                                       host_obj, True)
            volume = db.volume_get(context.get_admin_context(),
                                   fake_volume['id'])
            self.assertEqual(volume['host'], 'newhost')
            self.assertIsNone(volume['migration_status'])
            self.assertFalse(mock_migrate_volume.called)
            self.assertFalse(delete_volume.called)
            self.assertTrue(update_migrated_volume.called)

    def test_migrate_volume_generic_copy_error(self):
        def fake_create_volume(ctxt, volume, host, req_spec, filters,
                               allow_reschedule=True):
            db.volume_update(ctxt, volume['id'],
                             {'status': 'available'})

        with mock.patch.object(self.volume.driver, 'migrate_volume'),\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')\
                as mock_create_volume,\
                mock.patch.object(self.volume.driver, 'copy_volume_data') as \
                mock_copy_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume'),\
                mock.patch.object(self.volume, 'migrate_volume_completion'),\
                mock.patch.object(self.volume.driver, 'create_export'):

            # Exception case at migrate_volume_generic
            # source_volume['migration_status'] is 'migrating'
            mock_create_volume.side_effect = fake_create_volume
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
            self.assertIsNone(volume['migration_status'])
            self.assertEqual('available', volume['status'])

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

    def test_migrate_volume_generic_create_volume_error(self):
        def fake_create_volume(ctxt, volume, host, req_spec, filters,
                               allow_reschedule=True):
            db.volume_update(ctxt, volume['id'],
                             {'status': 'error'})

        with mock.patch.object(self.volume.driver, 'migrate_volume'), \
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume') as \
                mock_create_volume, \
                mock.patch.object(self.volume, '_clean_temporary_volume') as \
                clean_temporary_volume:

            # Exception case at the creation of the new temporary volume
            mock_create_volume.side_effect = fake_create_volume
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
            self.assertIsNone(volume['migration_status'])
            self.assertEqual('available', volume['status'])
            self.assertTrue(clean_temporary_volume.called)

    def test_migrate_volume_generic_timeout_error(self):
        CONF.set_override("migration_create_volume_timeout_secs", 2)

        def fake_create_volume(ctxt, volume, host, req_spec, filters,
                               allow_reschedule=True):
            db.volume_update(ctxt, volume['id'],
                             {'status': 'creating'})

        with mock.patch.object(self.volume.driver, 'migrate_volume'), \
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume') as \
                mock_create_volume, \
                mock.patch.object(self.volume, '_clean_temporary_volume') as \
                clean_temporary_volume:

            # Exception case at the timeout of the volume creation
            mock_create_volume.side_effect = fake_create_volume
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
            self.assertIsNone(volume['migration_status'])
            self.assertEqual('available', volume['status'])
            self.assertTrue(clean_temporary_volume.called)

    def test_migrate_volume_generic_create_export_error(self):
        def fake_create_volume(ctxt, volume, host, req_spec, filters,
                               allow_reschedule=True):
            db.volume_update(ctxt, volume['id'],
                             {'status': 'available'})

        with mock.patch.object(self.volume.driver, 'migrate_volume'),\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')\
                as mock_create_volume,\
                mock.patch.object(self.volume.driver, 'copy_volume_data') as \
                mock_copy_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume'),\
                mock.patch.object(self.volume, 'migrate_volume_completion'),\
                mock.patch.object(self.volume.driver, 'create_export') as \
                mock_create_export:

            # Exception case at create_export
            mock_create_volume.side_effect = fake_create_volume
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
            self.assertIsNone(volume['migration_status'])
            self.assertEqual('available', volume['status'])

    def test_migrate_volume_generic_migrate_volume_completion_error(self):
        def fake_create_volume(ctxt, volume, host, req_spec, filters,
                               allow_reschedule=True):
            db.volume_update(ctxt, volume['id'],
                             {'status': 'available'})

        def fake_migrate_volume_completion(ctxt, volume_id, new_volume_id,
                                           error=False):
            db.volume_update(ctxt, volume['id'],
                             {'migration_status': 'completing'})
            raise processutils.ProcessExecutionError

        with mock.patch.object(self.volume.driver, 'migrate_volume'),\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')\
                as mock_create_volume,\
                mock.patch.object(self.volume.driver, 'copy_volume_data'),\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume'),\
                mock.patch.object(self.volume, 'migrate_volume_completion')\
                as mock_migrate_compl,\
                mock.patch.object(self.volume.driver, 'create_export'):

            # Exception case at delete_volume
            # source_volume['migration_status'] is 'completing'
            mock_create_volume.side_effect = fake_create_volume
            mock_migrate_compl.side_effect = fake_migrate_volume_completion
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
            self.assertIsNone(volume['migration_status'])
            self.assertEqual('available', volume['status'])

    def _test_migrate_volume_completion(self, status='available',
                                        instance_uuid=None, attached_host=None,
                                        retyping=False):
        def fake_attach_volume(ctxt, volume, instance_uuid, host_name,
                               mountpoint, mode):
            tests_utils.attach_volume(ctxt, volume['id'],
                                      instance_uuid, host_name,
                                      '/dev/vda')

        initial_status = retyping and 'retyping' or status
        old_volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host,
                                               status=initial_status,
                                               migration_status='migrating')
        attachment_id = None
        if status == 'in-use':
            vol = tests_utils.attach_volume(self.context, old_volume['id'],
                                            instance_uuid, attached_host,
                                            '/dev/vda')
            self.assertEqual(vol['status'], 'in-use')
            attachment_id = vol['volume_attachment'][0]['id']
        target_status = 'target:%s' % old_volume['id']
        new_volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host,
                                               migration_status=target_status)
        with mock.patch.object(self.volume, 'detach_volume') as \
                mock_detach_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume'),\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'attach_volume') as \
                mock_attach_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI,
                                  'update_migrated_volume'),\
                mock.patch.object(self.volume.driver, 'attach_volume'):
            mock_attach_volume.side_effect = fake_attach_volume
            self.volume.migrate_volume_completion(self.context, old_volume[
                'id'], new_volume['id'])
            if status == 'in-use':
                mock_detach_volume.assert_called_with(self.context,
                                                      old_volume['id'],
                                                      attachment_id)
                attachment = db.volume_attachment_get_by_instance_uuid(
                    self.context, old_volume['id'], instance_uuid)
                self.assertIsNotNone(attachment)
                self.assertEqual(attachment['attached_host'], attached_host)
                self.assertEqual(attachment['instance_uuid'], instance_uuid)
            else:
                self.assertFalse(mock_detach_volume.called)

    def test_migrate_volume_completion_retype_available(self):
        self._test_migrate_volume_completion('available', retyping=True)

    def test_migrate_volume_completion_retype_in_use(self):
        self._test_migrate_volume_completion(
            'in-use',
            '83c969d5-065e-4c9c-907d-5394bc2e98e2',
            'some-host',
            retyping=True)

    def test_migrate_volume_completion_migrate_available(self):
        self._test_migrate_volume_completion()

    def test_migrate_volume_completion_migrate_in_use(self):
        self._test_migrate_volume_completion(
            'in-use',
            '83c969d5-065e-4c9c-907d-5394bc2e98e2',
            'some-host')

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
        self.assertEqual(volume['status'], 'available')

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

        with mock.patch.object(self.volume.driver, 'retype') as _retype:
            with mock.patch.object(volume_types, 'volume_types_diff') as _diff:
                with mock.patch.object(self.volume, 'migrate_volume') as _mig:
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

        # get volume/quota properties
        volume = db.volume_get(elevated, volume['id'])
        try:
            usage = db.quota_usage_get(elevated, project_id, 'volumes_new')
            volumes_in_use = usage.in_use
        except exception.QuotaUsageNotFound:
            volumes_in_use = 0

        # check properties
        if driver or diff_equal:
            self.assertEqual(volume['volume_type_id'], vol_type['id'])
            self.assertEqual(volume['status'], 'available')
            self.assertEqual(volume['host'], CONF.host)
            self.assertEqual(volumes_in_use, 1)
        elif not exc:
            self.assertEqual(volume['volume_type_id'], old_vol_type['id'])
            self.assertEqual(volume['status'], 'retyping')
            self.assertEqual(volume['host'], CONF.host)
            self.assertEqual(volumes_in_use, 1)
        else:
            self.assertEqual(volume['volume_type_id'], old_vol_type['id'])
            self.assertEqual(volume['status'], 'available')
            self.assertEqual(volume['host'], CONF.host)
            self.assertEqual(volumes_in_use, 0)

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
        self.assertEqual(volume.migration_status, 'error')

        # NOTE(flaper87): Set initialized to True,
        # lets cleanup the mess.
        self.volume.driver._initialized = True
        self.volume.delete_volume(self.context, volume['id'])

    def test_update_volume_readonly_flag(self):
        """Test volume readonly flag can be updated at API level."""
        # create a volume and assign to host
        volume = tests_utils.create_volume(self.context,
                                           admin_metadata={'readonly': 'True'},
                                           **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        volume['status'] = 'in-use'

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
        self.assertEqual(volume['status'], 'available')
        admin_metadata = volume['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 1)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'False')

        # clean up
        self.volume.delete_volume(self.context, volume['id'])

    @mock.patch.object(CGQUOTAS, "reserve",
                       return_value=["RESERVATION"])
    @mock.patch.object(CGQUOTAS, "commit")
    @mock.patch.object(CGQUOTAS, "rollback")
    @mock.patch.object(driver.VolumeDriver,
                       "create_consistencygroup",
                       return_value={'status': 'available'})
    @mock.patch.object(driver.VolumeDriver,
                       "delete_consistencygroup",
                       return_value=({'status': 'deleted'}, []))
    def test_create_delete_consistencygroup(self, fake_delete_cg,
                                            fake_create_cg, fake_rollback,
                                            fake_commit, fake_reserve):
        """Test consistencygroup can be created and deleted."""
        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')
        group_id = group['id']
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 0)
        self.volume.create_consistencygroup(self.context, group_id)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg['event_type'], 'consistencygroup.create.start')
        expected = {
            'status': 'available',
            'name': 'test_cg',
            'availability_zone': 'nova',
            'tenant_id': 'fake',
            'created_at': 'DONTCARE',
            'user_id': 'fake',
            'consistencygroup_id': group_id
        }
        self.assertDictMatch(msg['payload'], expected)
        msg = fake_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg['event_type'], 'consistencygroup.create.end')
        expected['status'] = 'available'
        self.assertDictMatch(msg['payload'], expected)
        self.assertEqual(
            group_id,
            db.consistencygroup_get(context.get_admin_context(),
                                    group_id).id)

        self.volume.delete_consistencygroup(self.context, group_id)
        cg = db.consistencygroup_get(
            context.get_admin_context(read_deleted='yes'),
            group_id)
        self.assertEqual(cg['status'], 'deleted')
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 4)
        msg = fake_notifier.NOTIFICATIONS[2]
        self.assertEqual(msg['event_type'], 'consistencygroup.delete.start')
        self.assertDictMatch(msg['payload'], expected)
        msg = fake_notifier.NOTIFICATIONS[3]
        self.assertEqual(msg['event_type'], 'consistencygroup.delete.end')
        self.assertDictMatch(msg['payload'], expected)
        self.assertRaises(exception.NotFound,
                          db.consistencygroup_get,
                          self.context,
                          group_id)

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
        group_id = group['id']
        self.volume.create_consistencygroup(self.context, group_id)

        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group_id,
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

        self.volume.update_consistencygroup(self.context, group_id,
                                            add_volumes=volume_id2,
                                            remove_volumes=volume_id)
        cg = db.consistencygroup_get(
            self.context,
            group_id)
        expected = {
            'status': 'available',
            'name': 'test_cg',
            'availability_zone': 'nova',
            'tenant_id': 'fake',
            'created_at': 'DONTCARE',
            'user_id': 'fake',
            'consistencygroup_id': group_id
        }
        self.assertEqual('available', cg['status'])
        self.assertEqual(10, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[6]
        self.assertEqual('consistencygroup.update.start', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        msg = fake_notifier.NOTIFICATIONS[8]
        self.assertEqual('consistencygroup.update.end', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        cgvolumes = db.volume_get_all_by_group(self.context, group_id)
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
                          group_id,
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
    def test_create_consistencygroup_from_src(self, mock_create_from_src,
                                              mock_delete_cgsnap,
                                              mock_create_cgsnap,
                                              mock_delete_cg, mock_create_cg):
        """Test consistencygroup can be created and deleted."""
        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')
        group_id = group['id']
        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group_id,
            **self.volume_params)
        volume_id = volume['id']
        cgsnapshot_returns = self._create_cgsnapshot(group_id, volume_id)
        cgsnapshot_id = cgsnapshot_returns[0]['id']
        snapshot_id = cgsnapshot_returns[1]['id']

        group2 = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2',
            cgsnapshot_id=cgsnapshot_id)
        group2_id = group2['id']
        volume2 = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group2_id,
            snapshot_id=snapshot_id,
            **self.volume_params)
        volume2_id = volume2['id']
        self.volume.create_volume(self.context, volume2_id)
        self.volume.create_consistencygroup_from_src(
            self.context, group2_id, cgsnapshot_id=cgsnapshot_id)

        cg2 = db.consistencygroup_get(
            self.context,
            group2_id)
        expected = {
            'status': 'available',
            'name': 'test_cg',
            'availability_zone': 'nova',
            'tenant_id': 'fake',
            'created_at': 'DONTCARE',
            'user_id': 'fake',
            'consistencygroup_id': group2_id
        }
        self.assertEqual('available', cg2['status'])

        msg = fake_notifier.NOTIFICATIONS[2]
        self.assertEqual('consistencygroup.create.start', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])
        msg = fake_notifier.NOTIFICATIONS[4]
        self.assertEqual('consistencygroup.create.end', msg['event_type'])
        self.assertDictMatch(expected, msg['payload'])

        if len(fake_notifier.NOTIFICATIONS) > 6:
            self.assertFalse(fake_notifier.NOTIFICATIONS[6])
        self.assertEqual(6, len(fake_notifier.NOTIFICATIONS))

        self.volume.delete_consistencygroup(self.context, group2_id)

        if len(fake_notifier.NOTIFICATIONS) > 10:
            self.assertFalse(fake_notifier.NOTIFICATIONS[10])
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 10)

        msg = fake_notifier.NOTIFICATIONS[6]
        self.assertEqual(msg['event_type'], 'consistencygroup.delete.start')
        expected['status'] = 'available'
        self.assertDictMatch(expected, msg['payload'])
        msg = fake_notifier.NOTIFICATIONS[8]
        self.assertEqual(msg['event_type'], 'consistencygroup.delete.end')
        self.assertDictMatch(expected, msg['payload'])

        cg2 = db.consistencygroup_get(
            context.get_admin_context(read_deleted='yes'),
            group2_id)
        self.assertEqual('deleted', cg2['status'])
        self.assertRaises(exception.NotFound,
                          db.consistencygroup_get,
                          self.context,
                          group2_id)

        self.volume.delete_cgsnapshot(self.context, cgsnapshot_id)
        self.volume.delete_consistencygroup(self.context, group_id)

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
        volumes = []
        snapshots = []
        volumes.append(vol1)
        volumes.append(vol2)
        volumes.append(vol3)
        snapshots.append(snp2)
        snapshots.append(snp3)
        snapshots.append(snp1)
        i = 0
        for vol in volumes:
            snap = snapshots[i]
            i += 1
            self.assertNotEqual(vol['snapshot_id'], snap['id'])
        sorted_snaps = self.volume._sort_snapshots(volumes, snapshots)
        i = 0
        for vol in volumes:
            snap = sorted_snaps[i]
            i += 1
            self.assertEqual(vol['snapshot_id'], snap['id'])

        snapshots[2]['id'] = '9999'
        self.assertRaises(exception.SnapshotNotFound,
                          self.volume._sort_snapshots,
                          volumes, snapshots)

        self.assertRaises(exception.InvalidInput,
                          self.volume._sort_snapshots,
                          volumes, [])

    @staticmethod
    def _create_cgsnapshot(group_id, volume_id, size='0'):
        """Create a cgsnapshot object."""
        cgsnap = {}
        cgsnap['user_id'] = 'fake'
        cgsnap['project_id'] = 'fake'
        cgsnap['consistencygroup_id'] = group_id
        cgsnap['status'] = "creating"
        cgsnapshot = db.cgsnapshot_create(context.get_admin_context(), cgsnap)

        # Create a snapshot object
        snap = {}
        snap['volume_size'] = size
        snap['user_id'] = 'fake'
        snap['project_id'] = 'fake'
        snap['volume_id'] = volume_id
        snap['status'] = "available"
        snap['cgsnapshot_id'] = cgsnapshot['id']
        snapshot = db.snapshot_create(context.get_admin_context(), snap)

        return cgsnapshot, snapshot

    def test_create_delete_cgsnapshot(self):
        """Test cgsnapshot can be created and deleted."""

        rval = {'status': 'available'}
        driver.VolumeDriver.create_consistencygroup = \
            mock.Mock(return_value=rval)

        rval = {'status': 'deleted'}, []
        driver.VolumeDriver.delete_consistencygroup = \
            mock.Mock(return_value=rval)

        rval = {'status': 'available'}, []
        driver.VolumeDriver.create_cgsnapshot = \
            mock.Mock(return_value=rval)

        rval = {'status': 'deleted'}, []
        driver.VolumeDriver.delete_cgsnapshot = \
            mock.Mock(return_value=rval)

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')
        group_id = group['id']
        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group_id,
            **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        cgsnapshot = tests_utils.create_cgsnapshot(
            self.context,
            consistencygroup_id=group_id)
        cgsnapshot_id = cgsnapshot['id']

        if len(fake_notifier.NOTIFICATIONS) > 2:
            self.assertFalse(fake_notifier.NOTIFICATIONS[2])
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 2)

        cgsnapshot_returns = self._create_cgsnapshot(group_id, volume_id)
        cgsnapshot_id = cgsnapshot_returns[0]['id']
        self.volume.create_cgsnapshot(self.context, group_id, cgsnapshot_id)
        self.assertEqual(cgsnapshot_id,
                         db.cgsnapshot_get(context.get_admin_context(),
                                           cgsnapshot_id).id)

        if len(fake_notifier.NOTIFICATIONS) > 6:
            self.assertFalse(fake_notifier.NOTIFICATIONS[6])

        msg = fake_notifier.NOTIFICATIONS[2]
        self.assertEqual(msg['event_type'], 'cgsnapshot.create.start')
        expected = {
            'created_at': 'DONTCARE',
            'name': None,
            'cgsnapshot_id': cgsnapshot_id,
            'status': 'creating',
            'tenant_id': 'fake',
            'user_id': 'fake',
            'consistencygroup_id': group_id
        }
        self.assertDictMatch(msg['payload'], expected)
        msg = fake_notifier.NOTIFICATIONS[3]
        self.assertEqual(msg['event_type'], 'snapshot.create.start')
        msg = fake_notifier.NOTIFICATIONS[4]
        self.assertEqual(msg['event_type'], 'cgsnapshot.create.end')
        self.assertDictMatch(msg['payload'], expected)
        msg = fake_notifier.NOTIFICATIONS[5]
        self.assertEqual(msg['event_type'], 'snapshot.create.end')

        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 6)

        self.volume.delete_cgsnapshot(self.context, cgsnapshot_id)

        if len(fake_notifier.NOTIFICATIONS) > 10:
            self.assertFalse(fake_notifier.NOTIFICATIONS[10])

        msg = fake_notifier.NOTIFICATIONS[6]
        self.assertEqual(msg['event_type'], 'cgsnapshot.delete.start')
        expected['status'] = 'available'
        self.assertDictMatch(msg['payload'], expected)
        msg = fake_notifier.NOTIFICATIONS[8]
        self.assertEqual(msg['event_type'], 'cgsnapshot.delete.end')
        self.assertDictMatch(msg['payload'], expected)

        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 10)

        cgsnap = db.cgsnapshot_get(
            context.get_admin_context(read_deleted='yes'),
            cgsnapshot_id)
        self.assertEqual(cgsnap['status'], 'deleted')
        self.assertRaises(exception.NotFound,
                          db.cgsnapshot_get,
                          self.context,
                          cgsnapshot_id)

        self.volume.delete_consistencygroup(self.context, group_id)

    def test_delete_consistencygroup_correct_host(self):
        """Test consistencygroup can be deleted.

        Test consistencygroup can be deleted when volumes are on
        the correct volume node.
        """

        rval = {'status': 'available'}
        driver.VolumeDriver.create_consistencygroup = \
            mock.Mock(return_value=rval)

        rval = {'status': 'deleted'}, []
        driver.VolumeDriver.delete_consistencygroup = \
            mock.Mock(return_value=rval)

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')

        group_id = group['id']
        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group_id,
            host='host1@backend1#pool1',
            status='creating',
            size=1)
        self.volume.host = 'host1@backend1'
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        self.volume.delete_consistencygroup(self.context, group_id)
        cg = db.consistencygroup_get(
            context.get_admin_context(read_deleted='yes'),
            group_id)
        self.assertEqual(cg['status'], 'deleted')
        self.assertRaises(exception.NotFound,
                          db.consistencygroup_get,
                          self.context,
                          group_id)

    def test_delete_consistencygroup_wrong_host(self):
        """Test consistencygroup cannot be deleted.

        Test consistencygroup cannot be deleted when volumes in the
        group are not local to the volume node.
        """

        rval = {'status': 'available'}
        driver.VolumeDriver.create_consistencygroup = \
            mock.Mock(return_value=rval)

        group = tests_utils.create_consistencygroup(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            volume_type='type1,type2')

        group_id = group['id']
        volume = tests_utils.create_volume(
            self.context,
            consistencygroup_id=group_id,
            host='host1@backend1#pool1',
            status='creating',
            size=1)
        self.volume.host = 'host1@backend2'
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        self.assertRaises(exception.InvalidVolume,
                          self.volume.delete_consistencygroup,
                          self.context,
                          group_id)
        cg = db.consistencygroup_get(self.context,
                                     group_id)
        # Group is not deleted
        self.assertEqual(cg['status'], 'available')

    def test_secure_file_operations_enabled(self):
        """Test secure file operations setting for base driver.

        General, non network file system based drivers do not have
        anything to do with "secure_file_operations". This test verifies that
        calling the method always returns False.
        """
        ret_flag = self.volume.driver.secure_file_operations_enabled()
        self.assertFalse(ret_flag)


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
        self.assertEqual(volume['status'], 'available')

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
        self.image_meta['id'] = FAKE_UUID
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
        self.assertEqual(volume['status'], 'available')

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
        self.assertEqual(volume.status, 'available')

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
            self.assertEqual(volume['status'], 'available')
            # image shouldn't be deleted if it is not in queued state
            image_service.show(self.context, self.image_id)

            # test with image in queued state
            self.assertRaises(exception.VolumeDriverException,
                              self.volume.copy_volume_to_image,
                              self.context,
                              self.volume_id,
                              queued_image_meta)
            volume = db.volume_get(self.context, self.volume_id)
            self.assertEqual(volume['status'], 'available')
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
            self.assertEqual(volume['status'], 'available')
            # image in saving state should be deleted
            self.assertRaises(exception.ImageNotFound,
                              image_service.show,
                              self.context,
                              saving_image_id)


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
        self.assertEqual(len(volumes), 3)
        self.assertEqual(volumes[0].id, u'2')
        self.assertEqual(volumes[1].id, u'3')
        self.assertEqual(volumes[2].id, u'4')

    def test_snapshot_get_active_by_window(self):
        # Find all all snapshots valid within a timeframe window.
        db.volume_create(self.context, {'id': 1})
        for i in range(5):
            self.db_attrs[i]['volume_id'] = 1

        # Not in window
        db.snapshot_create(self.ctx, self.db_attrs[0])

        # In - deleted in window
        db.snapshot_create(self.ctx, self.db_attrs[1])

        # In - deleted after window
        db.snapshot_create(self.ctx, self.db_attrs[2])

        # In - created in window
        db.snapshot_create(self.context, self.db_attrs[3])
        # Not of window.
        db.snapshot_create(self.context, self.db_attrs[4])

        snapshots = db.snapshot_get_active_by_window(
            self.context,
            datetime.datetime(1, 3, 1, 1, 1, 1),
            datetime.datetime(1, 4, 1, 1, 1, 1),
            project_id='p1')
        self.assertEqual(len(snapshots), 3)
        self.assertEqual(snapshots[0].id, u'2')
        self.assertEqual(snapshots[0].volume.id, u'1')
        self.assertEqual(snapshots[1].id, u'3')
        self.assertEqual(snapshots[1].volume.id, u'1')
        self.assertEqual(snapshots[2].id, u'4')
        self.assertEqual(snapshots[2].volume.id, u'1')


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
        self.volume.driver.set_execute(_fake_execute)
        self.volume.driver.set_initialized()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        try:
            shutil.rmtree(CONF.volumes_dir)
        except OSError:
            pass

    def fake_get_target(obj, iqn):
        return 1

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
    driver_name = "cinder.tests.fake_driver.LoggingVolumeDriver"

    def test_backup_volume(self):
        vol = tests_utils.create_volume(self.context)
        backup = {'volume_id': vol['id']}
        properties = {}
        attach_info = {'device': {'path': '/dev/null'}}
        backup_service = self.mox.CreateMock(backup_driver.BackupDriver)
        root_helper = 'sudo cinder-rootwrap /etc/cinder/rootwrap.conf'
        self.mox.StubOutWithMock(self.volume.driver.db, 'volume_get')
        self.mox.StubOutWithMock(cinder.brick.initiator.connector,
                                 'get_connector_properties')
        self.mox.StubOutWithMock(self.volume.driver, '_attach_volume')
        self.mox.StubOutWithMock(os, 'getuid')
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(fileutils, 'file_open')
        self.mox.StubOutWithMock(self.volume.driver, '_detach_volume')
        self.mox.StubOutWithMock(self.volume.driver, 'terminate_connection')

        self.volume.driver.db.volume_get(self.context, vol['id']).\
            AndReturn(vol)
        cinder.brick.initiator.connector.\
            get_connector_properties(root_helper, CONF.my_ip, False, False).\
            AndReturn(properties)
        self.volume.driver._attach_volume(self.context, vol, properties).\
            AndReturn((attach_info, vol))
        os.getuid()
        utils.execute('chown', None, '/dev/null', run_as_root=True)
        f = fileutils.file_open('/dev/null').AndReturn(file('/dev/null'))
        backup_service.backup(backup, f)
        utils.execute('chown', 0, '/dev/null', run_as_root=True)
        self.volume.driver._detach_volume(self.context, attach_info, vol,
                                          properties)
        self.mox.ReplayAll()
        self.volume.driver.backup_volume(self.context, backup, backup_service)
        self.mox.UnsetStubs()

    def test_restore_backup(self):
        vol = tests_utils.create_volume(self.context)
        backup = {'volume_id': vol['id'],
                  'id': 'backup-for-%s' % vol['id']}
        properties = {}
        attach_info = {'device': {'path': '/dev/null'}}
        root_helper = 'sudo cinder-rootwrap /etc/cinder/rootwrap.conf'
        backup_service = self.mox.CreateMock(backup_driver.BackupDriver)
        self.mox.StubOutWithMock(cinder.brick.initiator.connector,
                                 'get_connector_properties')
        self.mox.StubOutWithMock(self.volume.driver, '_attach_volume')
        self.mox.StubOutWithMock(os, 'getuid')
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(fileutils, 'file_open')
        self.mox.StubOutWithMock(self.volume.driver, '_detach_volume')
        self.mox.StubOutWithMock(self.volume.driver, 'terminate_connection')

        cinder.brick.initiator.connector.\
            get_connector_properties(root_helper, CONF.my_ip, False, False).\
            AndReturn(properties)
        self.volume.driver._attach_volume(self.context, vol, properties).\
            AndReturn((attach_info, vol))
        os.getuid()
        utils.execute('chown', None, '/dev/null', run_as_root=True)
        f = fileutils.file_open('/dev/null', 'wb').AndReturn(file('/dev/null'))
        backup_service.restore(backup, vol['id'], f)
        utils.execute('chown', 0, '/dev/null', run_as_root=True)
        self.volume.driver._detach_volume(self.context, attach_info, vol,
                                          properties)
        self.mox.ReplayAll()
        self.volume.driver.restore_backup(self.context, backup, vol,
                                          backup_service)
        self.mox.UnsetStubs()


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
                mock.patch.object(self.volume.driver, '_delete_volume'), \
                mock.patch.object(self.volume.driver, 'create_export',
                                  return_value = None):

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
                execute=mock_execute)

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
            self.assertEqual(old_name, ref['source-name'])
            self.assertEqual(new_name, vol['name'])

        self.stubs.Set(self.volume.driver.vg, 'rename_volume',
                       _rename_volume)

        size = self.volume.driver.manage_existing_get_size(vol, ref)
        self.assertEqual(size, 2)
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
        db.backup_create(self.context, backup)['id']

        lvm_driver.check_for_setup_error()

    @mock.patch.object(utils, 'temporary_chown')
    @mock.patch.object(fileutils, 'file_open')
    @mock.patch.object(cinder.brick.initiator.connector,
                       'get_connector_properties')
    @mock.patch.object(db, 'volume_get')
    def test_backup_volume(self, mock_volume_get,
                           mock_get_connector_properties,
                           mock_file_open,
                           mock_temporary_chown):
        vol = tests_utils.create_volume(self.context)
        backup = {'volume_id': vol['id']}
        properties = {}
        attach_info = {'device': {'path': '/dev/null'}}
        backup_service = mock.Mock()

        self.volume.driver._detach_volume = mock.MagicMock()
        self.volume.driver._attach_volume = mock.MagicMock()
        self.volume.driver.terminate_connection = mock.MagicMock()

        mock_volume_get.return_value = vol
        mock_get_connector_properties.return_value = properties
        f = mock_file_open.return_value = file('/dev/null')

        backup_service.backup(backup, f, None)
        self.volume.driver._attach_volume.return_value = attach_info

        self.volume.driver.backup_volume(self.context, backup,
                                         backup_service)

        mock_volume_get.assert_called_with(self.context, vol['id'])


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
        for index in xrange(3):
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
        self.assertEqual(result["target_portal"], "0.0.0.0:0000")
        self.assertEqual(result["target_iqn"], "iqn:iqn")
        self.assertEqual(result["target_lun"], 0)

    def test_get_iscsi_properties_multiple_portals(self):
        volume = {"provider_location": '1.1.1.1:3260;2.2.2.2:3261,1 iqn:iqn 0',
                  "id": "0",
                  "provider_auth": "a b c",
                  "attached_mode": "rw"}
        iscsi_driver = \
            cinder.volume.targets.tgt.TgtAdm(configuration=self.configuration)
        result = iscsi_driver._get_iscsi_properties(volume)
        self.assertEqual(result["target_portal"], "1.1.1.1:3260")
        self.assertEqual(result["target_iqn"], "iqn:iqn")
        self.assertEqual(result["target_lun"], 0)
        self.assertEqual(["1.1.1.1:3260", "2.2.2.2:3261"],
                         result["target_portals"])
        self.assertEqual(["iqn:iqn", "iqn:iqn"], result["target_iqns"])
        self.assertEqual([0, 0], result["target_luns"])

    def test_get_volume_stats(self):

        def _fake_get_all_physical_volumes(obj, root_helper, vg_name):
            return [{}]

        def _fake_get_all_volume_groups(obj, vg_name=None, no_suffix=True):
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
            stats['pools'][0]['total_capacity_gb'], float('5.52'))
        self.assertEqual(
            stats['pools'][0]['free_capacity_gb'], float('0.52'))
        self.assertEqual(
            stats['pools'][0]['provisioned_capacity_gb'], float('5.0'))
        self.assertEqual(
            stats['pools'][0]['total_volumes'], int('1'))

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
            stats['pools'][0]['total_capacity_gb'], float('5.52'))
        self.assertEqual(
            stats['pools'][0]['free_capacity_gb'], float('0.52'))
        self.assertEqual(
            stats['pools'][0]['provisioned_capacity_gb'], float('5.0'))
        self.assertEqual(stats['storage_protocol'], 'iSER')

    @test.testtools.skip("SKIP until ISER driver is removed or fixed")
    def test_get_volume_stats2(self):
        iser_driver = lvm.LVMISERDriver(configuration=self.configuration)

        stats = iser_driver.get_volume_stats(refresh=True)

        self.assertEqual(
            stats['pools'][0]['total_capacity_gb'], 0)
        self.assertEqual(
            stats['pools'][0]['free_capacity_gb'], 0)
        self.assertEqual(
            stats['pools'][0]['provisioned_capacity_gb'], float('5.0'))
        self.assertEqual(stats['storage_protocol'], 'iSER')


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
        self.stubs.Set(brick_lvm.LVM, '_vg_exists', lambda x: True)

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
