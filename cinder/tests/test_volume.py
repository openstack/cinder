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

import contextlib
import datetime
import mock
import os
import shutil
import socket
import tempfile

import eventlet
import mox
from oslo.config import cfg
from stevedore import extension
from taskflow.engines.action_engine import engine

from cinder.backup import driver as backup_driver
from cinder.brick.iscsi import iscsi
from cinder.brick.local_dev import lvm as brick_lvm
from cinder import context
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder import keymgr
from cinder.openstack.common import fileutils
from cinder.openstack.common import importutils
from cinder.openstack.common import jsonutils
from cinder.openstack.common.notifier import api as notifier_api
from cinder.openstack.common.notifier import test_notifier
from cinder.openstack.common import rpc
import cinder.policy
from cinder import quota
from cinder import test
from cinder.tests.brick.fake_lvm import FakeBrickLVM
from cinder.tests import conf_fixture
from cinder.tests.image import fake as fake_image
from cinder.tests.keymgr import fake as fake_keymgr
from cinder.tests import utils as tests_utils
from cinder import units
from cinder import utils
import cinder.volume
from cinder.volume import configuration as conf
from cinder.volume import driver
from cinder.volume.drivers import lvm
from cinder.volume.manager import VolumeManager
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as volutils
from cinder.volume import volume_types


QUOTAS = quota.QUOTAS

CONF = cfg.CONF

ENCRYPTION_PROVIDER = 'nova.volume.encryptors.cryptsetup.CryptsetupEncryptor'

fake_opt = [
    cfg.StrOpt('fake_opt', default='fake', help='fake opts')
]

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa'


class FakeImageService:
    def __init__(self, db_driver=None, image_service=None):
        pass

    def show(self, context, image_id):
        return {'size': 2 * units.GiB,
                'disk_format': 'raw',
                'container_format': 'bare'}


class BaseVolumeTestCase(test.TestCase):
    """Test Case for volumes."""
    def setUp(self):
        super(BaseVolumeTestCase, self).setUp()
        self.extension_manager = extension.ExtensionManager(
            "BaseVolumeTestCase")
        vol_tmpdir = tempfile.mkdtemp()
        self.flags(volumes_dir=vol_tmpdir,
                   notification_driver=[test_notifier.__name__])
        self.volume = importutils.import_object(CONF.volume_manager)
        self.context = context.get_admin_context()
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        self.volume_params = {
            'status': 'creating',
            'host': CONF.host,
            'size': 1}
        self.stubs.Set(iscsi.TgtAdm, '_get_target', self.fake_get_target)
        self.stubs.Set(brick_lvm.LVM,
                       'get_all_volume_groups',
                       self.fake_get_all_volume_groups)
        fake_image.stub_out_image_service(self.stubs)
        test_notifier.NOTIFICATIONS = []
        self.stubs.Set(brick_lvm.LVM, '_vg_exists', lambda x: True)
        self.stubs.Set(os.path, 'exists', lambda x: True)
        self.volume.driver.set_initialized()
        self.volume.stats = {'allocated_capacity_gb': 0}
        # keep ordered record of what we execute
        self.called = []

    def tearDown(self):
        try:
            shutil.rmtree(CONF.volumes_dir)
        except OSError:
            pass
        notifier_api._reset_drivers()
        super(BaseVolumeTestCase, self).tearDown()

    def fake_get_target(obj, iqn):
        return 1

    def fake_get_all_volume_groups(obj, vg_name=None, no_suffix=True):
        return [{'name': 'cinder-volumes',
                 'size': '5.00',
                 'available': '2.50',
                 'lv_count': '2',
                 'uuid': 'vR1JU3-FAKE-C4A9-PQFh-Mctm-9FwA-Xwzc1m'}]


class VolumeTestCase(BaseVolumeTestCase):

    def setUp(self):
        super(VolumeTestCase, self).setUp()
        self.stubs.Set(volutils, 'clear_volume',
                       lambda a, b, volume_clear=mox.IgnoreArg(),
                       volume_clear_size=mox.IgnoreArg(),
                       lvm_type=mox.IgnoreArg(): None)

    def test_init_host_clears_downloads(self):
        """Test that init_host will unwedge a volume stuck in downloading."""
        volume = tests_utils.create_volume(self.context, status='downloading',
                                           size=0, host=CONF.host)
        volume_id = volume['id']
        self.volume.init_host()
        volume = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(volume['status'], "error")
        self.volume.delete_volume(self.context, volume_id)

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
        self.assertEqual(len(test_notifier.NOTIFICATIONS), 0)
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.create_volume,
                          self.context, volume_id)

        # NOTE(flaper87): The volume status should be error_deleting.
        volume = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(volume.status, "error")
        db.volume_destroy(context.get_admin_context(), volume_id)

    @mock.patch.object(QUOTAS, 'reserve')
    @mock.patch.object(QUOTAS, 'commit')
    @mock.patch.object(QUOTAS, 'rollback')
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
        self.assertEqual(len(test_notifier.NOTIFICATIONS), 0)
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.delete_volume,
                          self.context, volume_id)

        # NOTE(flaper87): The volume status should be error.
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
        self.assertEqual(len(test_notifier.NOTIFICATIONS), 0)
        self.volume.create_volume(self.context, volume_id)
        self.assertEqual(len(test_notifier.NOTIFICATIONS), 2)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg['event_type'], 'volume.create.start')
        expected = {
            'status': 'creating',
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
        }
        self.assertDictMatch(msg['payload'], expected)
        msg = test_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg['event_type'], 'volume.create.end')
        expected['status'] = 'available'
        self.assertDictMatch(msg['payload'], expected)
        self.assertEqual(volume_id, db.volume_get(context.get_admin_context(),
                         volume_id).id)

        self.volume.delete_volume(self.context, volume_id)
        vol = db.volume_get(context.get_admin_context(read_deleted='yes'),
                            volume_id)
        self.assertEqual(vol['status'], 'deleted')
        self.assertEqual(len(test_notifier.NOTIFICATIONS), 4)
        msg = test_notifier.NOTIFICATIONS[2]
        self.assertEqual(msg['event_type'], 'volume.delete.start')
        self.assertDictMatch(msg['payload'], expected)
        msg = test_notifier.NOTIFICATIONS[3]
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

        def fake_list_availability_zones():
            return ({'name': 'az1', 'available': True},
                    {'name': 'az2', 'available': True},
                    {'name': 'default-az', 'available': True})

        self.stubs.Set(volume_api,
                       'list_availability_zones',
                       fake_list_availability_zones)

        # Test backwards compatibility, default_availability_zone not set
        CONF.set_override('storage_availability_zone', 'az2')
        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description')
        self.assertEqual(volume['availability_zone'], 'az2')

        CONF.set_override('default_availability_zone', 'default-az')
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
            manager = VolumeManager()
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
            self.assertRaises(exception.CinderException, VolumeManager)

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
        self.assertEqual(True, res)
        volume_ref = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(volume_id, volume_ref.id)
        self.assertEqual("available", volume_ref.status)

        self.mox.UnsetStubs()
        self.volume.delete_volume(self.context, volume_id)

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

    def test_create_volume_from_snapshot(self):
        """Test volume can be created from a snapshot."""
        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src['id'])
        snapshot_id = self._create_snapshot(volume_src['id'])['id']
        self.volume.create_snapshot(self.context, volume_src['id'],
                                    snapshot_id)
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
        self.volume.delete_snapshot(self.context, snapshot_id)
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
        snapshot_id = self._create_snapshot(volume_src['id'])['id']

        # NOTE(flaper87): Set initialized to False
        self.volume.driver._initialized = False

        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.create_snapshot,
                          self.context, volume_src['id'],
                          snapshot_id)

        # NOTE(flaper87): The volume status should be error.
        snapshot = db.snapshot_get(context.get_admin_context(), snapshot_id)
        self.assertEqual(snapshot.status, "error")

        # NOTE(flaper87): Set initialized to True,
        # lets cleanup the mess
        self.volume.driver._initialized = True
        self.volume.delete_snapshot(self.context, snapshot_id)
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

        snap_id = self._create_snapshot(src_vol_id)['id']
        # no lock
        self.volume.create_snapshot(self.context, src_vol_id, snap_id)

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
        self.volume.delete_snapshot(self.context, snap_id)
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
        admin_ctxt = context.get_admin_context()

        orig_elevated = self.context.elevated

        ctxt_deepcopy = self.context.deepcopy()
        gthreads = []

        def mock_elevated(*args, **kwargs):
            # unset mock so it is only called once
            self.stubs.Set(self.context, 'elevated', orig_elevated)

            # we expect this to block and then fail
            t = eventlet.spawn(self.volume.create_volume,
                               ctxt_deepcopy,
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

    def test_create_volume_from_snapshot_delete_lock_taken(self):
        # create source volume
        src_vol = tests_utils.create_volume(self.context, **self.volume_params)
        src_vol_id = src_vol['id']

        # no lock
        self.volume.create_volume(self.context, src_vol_id)

        # create snapshot
        snap_id = self._create_snapshot(src_vol_id)['id']
        # no lock
        self.volume.create_snapshot(self.context, src_vol_id, snap_id)

        # create vol from snapshot...
        dst_vol = tests_utils.create_volume(self.context,
                                            source_volid=src_vol_id,
                                            **self.volume_params)
        dst_vol_id = dst_vol['id']
        admin_ctxt = context.get_admin_context()

        orig_elevated = self.context.elevated

        ctxt_deepcopy = self.context.deepcopy()
        gthreads = []

        def mock_elevated(*args, **kwargs):
            # unset mock so it is only called once
            self.stubs.Set(self.context, 'elevated', orig_elevated)

            # We expect this to block and then fail
            t = eventlet.spawn(self.volume.create_volume, ctxt_deepcopy,
                               volume_id=dst_vol_id, snapshot_id=snap_id)
            gthreads.append(t)

            return orig_elevated(*args, **kwargs)

        # mock something from early on in the delete operation and within the
        # lock so that when we do the create we expect it to block.
        self.stubs.Set(self.context, 'elevated', mock_elevated)

        # locked
        self.volume.delete_snapshot(self.context, snap_id)

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

        def fake_list_availability_zones():
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
                                    snapshot['id'])
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

        with contextlib.nested(
            mock.patch.object(cinder.volume.volume_types,
                              'get_volume_type_qos_specs'),
            mock.patch.object(cinder.tests.fake_driver.FakeISCSIDriver,
                              'initialize_connection')
        ) as (type_qos, driver_init):
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
        self.volume.attach_volume(self.context, volume_id, instance_uuid,
                                  None, mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(vol['status'], "in-use")
        self.assertEqual(vol['attach_status'], "attached")
        self.assertEqual(vol['mountpoint'], mountpoint)
        self.assertEqual(vol['instance_uuid'], instance_uuid)
        self.assertIsNone(vol['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 2)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'True')
        self.assertEqual(admin_metadata[1]['key'], 'attached_mode')
        self.assertEqual(admin_metadata[1]['value'], 'ro')
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual(conn_info['data']['access_mode'], 'ro')

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)
        self.volume.detach_volume(self.context, volume_id)
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual(vol['status'], "available")

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
        self.volume.attach_volume(self.context, volume_id, None,
                                  'fake_host', mountpoint, 'rw')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(vol['status'], "in-use")
        self.assertEqual(vol['attach_status'], "attached")
        self.assertEqual(vol['mountpoint'], mountpoint)
        self.assertIsNone(vol['instance_uuid'])
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual(vol['attached_host'], 'fake-host')
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 2)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'False')
        self.assertEqual(admin_metadata[1]['key'], 'attached_mode')
        self.assertEqual(admin_metadata[1]['value'], 'rw')
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual(conn_info['data']['access_mode'], 'rw')

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)
        self.volume.detach_volume(self.context, volume_id)
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual(vol['status'], "available")

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
        db.volume_update(self.context, volume_id, {'status': 'available',
                                                   'mountpoint': None,
                                                   'instance_uuid': None,
                                                   'attached_host': None,
                                                   'attached_mode': None})
        self.volume.attach_volume(self.context, volume_id, instance_uuid,
                                  None, mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(vol['status'], "in-use")
        self.assertEqual(vol['attach_status'], "attached")
        self.assertEqual(vol['mountpoint'], mountpoint)
        self.assertEqual(vol['instance_uuid'], instance_uuid)
        self.assertIsNone(vol['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 2)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'True')
        self.assertEqual(admin_metadata[1]['key'], 'attached_mode')
        self.assertEqual(admin_metadata[1]['value'], 'ro')
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual(conn_info['data']['access_mode'], 'ro')

        self.volume.detach_volume(self.context, volume_id)
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual(vol['status'], "available")
        self.assertEqual(vol['attach_status'], "detached")
        self.assertIsNone(vol['mountpoint'])
        self.assertIsNone(vol['instance_uuid'])
        self.assertIsNone(vol['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 1)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'True')

        self.volume.attach_volume(self.context, volume_id, None,
                                  'fake_host', mountpoint, 'ro')
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(vol['status'], "in-use")
        self.assertEqual(vol['attach_status'], "attached")
        self.assertEqual(vol['mountpoint'], mountpoint)
        self.assertIsNone(vol['instance_uuid'])
        self.assertEqual(vol['attached_host'], 'fake-host')
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 2)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'True')
        self.assertEqual(admin_metadata[1]['key'], 'attached_mode')
        self.assertEqual(admin_metadata[1]['value'], 'ro')
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        conn_info = self.volume.initialize_connection(self.context,
                                                      volume_id, connector)
        self.assertEqual(conn_info['data']['access_mode'], 'ro')

        self.volume.detach_volume(self.context, volume_id)
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual(vol['status'], "available")
        self.assertEqual(vol['attach_status'], "detached")
        self.assertIsNone(vol['mountpoint'])
        self.assertIsNone(vol['instance_uuid'])
        self.assertIsNone(vol['attached_host'])
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 1)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'True')

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
        self.assertEqual(vol['status'], "error_attaching")
        self.assertEqual(vol['attach_status'], "detached")
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 2)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'True')
        self.assertEqual(admin_metadata[1]['key'], 'attached_mode')
        self.assertEqual(admin_metadata[1]['value'], 'rw')

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
        self.assertEqual(vol['status'], "error_attaching")
        self.assertEqual(vol['attach_status'], "detached")
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 2)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'True')
        self.assertEqual(admin_metadata[1]['key'], 'attached_mode')
        self.assertEqual(admin_metadata[1]['value'], 'rw')

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
        self.assertEqual(vol['attach_status'], "detached")
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 1)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'True')

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
        self.assertEqual(vol['attach_status'], "detached")
        admin_metadata = vol['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 1)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'True')

    @mock.patch.object(db, 'volume_get')
    @mock.patch.object(cinder.volume.api.API, 'update')
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
            'status': 'in-use'
        }

        with mock.patch.object(db, 'volume_get') as mock_volume_get:
            mock_volume_get.return_value = fake_volume
            self.assertRaises(exception.InvalidVolume,
                              cinder.volume.api.API().reserve_volume,
                              self.context,
                              fake_volume)
            self.assertTrue(mock_volume_get.called)

    def test_unreserve_volume_success(self):
        fake_volume = {
            'id': FAKE_UUID,
            'status': 'attaching'
        }

        with mock.patch.object(cinder.volume.api.API,
                               'update') as mock_volume_update:
            mock_volume_update.return_value = fake_volume
            self.assertIsNone(cinder.volume.api.API().unreserve_volume(
                self.context,
                fake_volume
            ))
            self.assertTrue(mock_volume_update.called)

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

        total_slots = CONF.iscsi_num_targets
        for _index in xrange(total_slots):
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
        self.assertEqual(len(test_notifier.NOTIFICATIONS), 0)
        self.volume.create_volume(self.context, volume['id'])
        self.assertEqual(len(test_notifier.NOTIFICATIONS), 2)
        snapshot_id = self._create_snapshot(volume['id'])['id']
        self.volume.create_snapshot(self.context, volume['id'], snapshot_id)
        self.assertEqual(snapshot_id,
                         db.snapshot_get(context.get_admin_context(),
                                         snapshot_id).id)
        self.assertEqual(len(test_notifier.NOTIFICATIONS), 4)
        msg = test_notifier.NOTIFICATIONS[2]
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
            'volume_size': 0,
            'availability_zone': 'nova'
        }
        self.assertDictMatch(msg['payload'], expected)
        msg = test_notifier.NOTIFICATIONS[3]
        self.assertEqual(msg['event_type'], 'snapshot.create.end')
        self.assertDictMatch(msg['payload'], expected)

        self.volume.delete_snapshot(self.context, snapshot_id)
        self.assertEqual(len(test_notifier.NOTIFICATIONS), 6)
        msg = test_notifier.NOTIFICATIONS[4]
        self.assertEqual(msg['event_type'], 'snapshot.delete.start')
        expected['status'] = 'available'
        self.assertDictMatch(msg['payload'], expected)
        msg = test_notifier.NOTIFICATIONS[5]
        self.assertEqual(msg['event_type'], 'snapshot.delete.end')
        self.assertDictMatch(msg['payload'], expected)

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
        snapshot = self._create_snapshot(volume['id'], metadata=test_meta)
        snapshot_id = snapshot['id']

        snap = db.snapshot_get(context.get_admin_context(), snapshot_id)
        result_dict = dict(snap.iteritems())
        result_meta = {
            result_dict['snapshot_metadata'][0].key:
            result_dict['snapshot_metadata'][0].value}
        self.assertEqual(result_meta, test_meta)
        self.volume.delete_snapshot(self.context, snapshot_id)
        self.assertRaises(exception.NotFound,
                          db.snapshot_get,
                          self.context,
                          snapshot_id)

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
        snapshot_id = self._create_snapshot(volume['id'])['id']
        self.volume.create_snapshot(self.context, volume['id'], snapshot_id)
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
        self.volume.delete_snapshot(self.context, snapshot_id)
        self.volume.delete_volume(self.context, volume['id'])

    def test_can_delete_errored_snapshot(self):
        """Test snapshot can be created and deleted."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        snapshot_id = self._create_snapshot(volume['id'])['id']
        self.volume.create_snapshot(self.context, volume['id'], snapshot_id)
        snapshot = db.snapshot_get(context.get_admin_context(),
                                   snapshot_id)

        volume_api = cinder.volume.api.API()

        snapshot['status'] = 'badstatus'
        self.assertRaises(exception.InvalidSnapshot,
                          volume_api.delete_snapshot,
                          self.context,
                          snapshot)

        snapshot['status'] = 'error'
        self.volume.delete_snapshot(self.context, snapshot_id)
        self.volume.delete_volume(self.context, volume['id'])

    def test_create_snapshot_force(self):
        """Test snapshot in use can be created forcibly."""

        def fake_cast(ctxt, topic, msg):
            pass
        self.stubs.Set(rpc, 'cast', fake_cast)
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        # create volume and attach to the instance
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume['id'])
        db.volume_attached(self.context, volume['id'], instance_uuid,
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
        db.volume_attached(self.context, volume['id'], None,
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

    def test_delete_busy_snapshot(self):
        """Test snapshot can be created and deleted."""

        self.volume.driver.vg = FakeBrickLVM('cinder-volumes',
                                             False,
                                             None,
                                             'default')

        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        snapshot_id = self._create_snapshot(volume_id)['id']
        self.volume.create_snapshot(self.context, volume_id, snapshot_id)

        self.mox.StubOutWithMock(self.volume.driver, 'delete_snapshot')

        self.volume.driver.delete_snapshot(
            mox.IgnoreArg()).AndRaise(
                exception.SnapshotIsBusy(snapshot_name='fake'))
        self.mox.ReplayAll()
        self.volume.delete_snapshot(self.context, snapshot_id)
        snapshot_ref = db.snapshot_get(self.context, snapshot_id)
        self.assertEqual(snapshot_id, snapshot_ref.id)
        self.assertEqual("available", snapshot_ref.status)

        self.mox.UnsetStubs()
        self.volume.delete_snapshot(self.context, snapshot_id)
        self.volume.delete_volume(self.context, volume_id)

    def test_delete_no_dev_fails(self):
        """Test delete snapshot with no dev file fails."""
        self.stubs.Set(os.path, 'exists', lambda x: False)
        self.volume.driver.vg = FakeBrickLVM('cinder-volumes',
                                             False,
                                             None,
                                             'default')

        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        snapshot_id = self._create_snapshot(volume_id)['id']
        self.volume.create_snapshot(self.context, volume_id, snapshot_id)

        self.mox.StubOutWithMock(self.volume.driver, 'delete_snapshot')

        self.volume.driver.delete_snapshot(
            mox.IgnoreArg()).AndRaise(
                exception.SnapshotIsBusy(snapshot_name='fake'))
        self.mox.ReplayAll()
        self.volume.delete_snapshot(self.context, snapshot_id)
        snapshot_ref = db.snapshot_get(self.context, snapshot_id)
        self.assertEqual(snapshot_id, snapshot_ref.id)
        self.assertEqual("available", snapshot_ref.status)

        self.mox.UnsetStubs()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.delete_snapshot,
                          self.context,
                          snapshot_id)
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
                              size=None):
            pass

        def fake_clone_image(volume_ref, image_location, image_id, image_meta):
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
            self.volume.create_volume(self.context,
                                      volume_id,
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
                return {'size': 2 * units.GiB + 1,
                        'disk_format': 'raw',
                        'container_format': 'bare'}

        volume_api = cinder.volume.api.API(image_service=
                                           _ModifiedFakeImageService())

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context, 2,
                          'name', 'description', image_id=1)

    def test_create_volume_with_mindisk_error(self):
        """Verify volumes smaller than image minDisk will cause an error."""
        class _ModifiedFakeImageService(FakeImageService):
            def show(self, context, image_id):
                return {'size': 2 * units.GiB,
                        'disk_format': 'raw',
                        'container_format': 'bare',
                        'min_disk': 5}

        volume_api = cinder.volume.api.API(image_service=
                                           _ModifiedFakeImageService())

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

    def test_begin_roll_detaching_volume(self):
        """Test begin_detaching and roll_detaching functions."""
        volume = tests_utils.create_volume(self.context, **self.volume_params)
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
        self.assertIsNone(snapshot['display_name'])
        # use volume.api to update name
        volume_api = cinder.volume.api.API()
        update_dict = {'display_name': 'test update name'}
        volume_api.update_snapshot(self.context, snapshot, update_dict)
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

    def test_create_volume_from_unelevated_context(self):
        """Test context does't change after volume creation failure."""
        def fake_create_volume(*args, **kwargs):
            raise exception.CinderException('fake exception')

        #create context for testing
        ctxt = self.context.deepcopy()
        if 'admin' in ctxt.roles:
            ctxt.roles.remove('admin')
            ctxt.is_admin = False
        #create one copy of context for future comparison
        self.saved_ctxt = ctxt.deepcopy()

        self.stubs.Set(self.volume.driver, 'create_volume', fake_create_volume)

        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.assertRaises(exception.CinderException,
                          self.volume.create_volume, ctxt, volume_src['id'])

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

        def fake_list_availability_zones():
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

        expected = (
            {'name': 'pung', 'available': False},
            {'name': 'pong', 'available': True},
            {'name': 'ping', 'available': True},
        )

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

    def test_migrate_volume_generic(self):
        def fake_migr(vol, host):
            raise Exception('should not be called')

        def fake_delete_volume_rpc(self, ctxt, vol_id):
            raise Exception('should not be called')

        def fake_create_volume(self, ctxt, volume, host, req_spec, filters,
                               allow_reschedule=True):
            db.volume_update(ctxt, volume['id'],
                             {'status': 'available'})

        self.stubs.Set(self.volume.driver, 'migrate_volume', fake_migr)
        self.stubs.Set(volume_rpcapi.VolumeAPI, 'create_volume',
                       fake_create_volume)
        self.stubs.Set(self.volume.driver, 'copy_volume_data',
                       lambda x, y, z, remote='dest': True)
        self.stubs.Set(volume_rpcapi.VolumeAPI, 'delete_volume',
                       fake_delete_volume_rpc)

        volume = tests_utils.create_volume(self.context, size=0,
                                           host=CONF.host)
        host_obj = {'host': 'newhost', 'capabilities': {}}
        self.volume.migrate_volume(self.context, volume['id'],
                                   host_obj, True)
        volume = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEqual(volume['host'], 'newhost')
        self.assertIsNone(volume['migration_status'])

    def _retype_volume_exec(self, driver, snap=False, policy='on-demand',
                            migrate_exc=False, exc=None, diff_equal=False):
        elevated = context.get_admin_context()
        project_id = self.context.project_id

        db.volume_type_create(elevated, {'name': 'old', 'extra_specs': {}})
        old_vol_type = db.volume_type_get_by_name(elevated, 'old')
        db.volume_type_create(elevated, {'name': 'new', 'extra_specs': {}})
        vol_type = db.volume_type_get_by_name(elevated, 'new')
        db.quota_create(elevated, project_id, 'volumes_new', 10)

        volume = tests_utils.create_volume(self.context, size=1,
                                           host=CONF.host, status='retyping',
                                           volume_type_id=old_vol_type['id'])
        if snap:
            self._create_snapshot(volume['id'], size=volume['size'])
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
        if not exc:
            self.assertEqual(volume['volume_type_id'], vol_type['id'])
            self.assertEqual(volume['status'], 'available')
            self.assertEqual(volume['host'], 'newhost')
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


class CopyVolumeToImageTestCase(BaseVolumeTestCase):
    def fake_local_path(self, volume):
        return self.dst_path

    def setUp(self):
        super(CopyVolumeToImageTestCase, self).setUp()
        self.dst_fd, self.dst_path = tempfile.mkstemp()
        os.close(self.dst_fd)
        self.stubs.Set(self.volume.driver, 'local_path', self.fake_local_path)
        self.image_meta = {
            'id': '70a599e0-31e7-49b7-b260-868f441e862b',
            'container_format': 'bare',
            'disk_format': 'raw'
        }
        self.volume_id = 1
        self.volume_attrs = {
            'id': self.volume_id,
            'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
            'display_description': 'Test Desc',
            'size': 20,
            'status': 'uploading',
            'host': 'dummy'
        }

    def tearDown(self):
        db.volume_destroy(self.context, self.volume_id)
        os.unlink(self.dst_path)
        super(CopyVolumeToImageTestCase, self).tearDown()

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
        self.volume_attrs['instance_uuid'] = 'b21f957d-a72f-4b93-b5a5-' \
                                             '45b1161abb02'
        db.volume_create(self.context, self.volume_attrs)

        # start test
        self.volume.copy_volume_to_image(self.context,
                                         self.volume_id,
                                         self.image_meta)

        volume = db.volume_get(self.context, self.volume_id)
        self.assertEqual(volume['status'], 'in-use')

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
        vol = db.volume_create(self.context, {'id': 1})
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
        self.stubs.Set(iscsi.TgtAdm, '_get_target', self.fake_get_target)
        self.stubs.Set(brick_lvm.LVM, '_vg_exists', lambda x: True)

        def _fake_execute(_command, *_args, **_kwargs):
            """Fake _execute."""
            return self.output, None
        self.volume.driver.set_execute(_fake_execute)
        self.volume.driver.set_initialized()

    def tearDown(self):
        try:
            shutil.rmtree(CONF.volumes_dir)
        except OSError:
            pass
        super(DriverTestCase, self).tearDown()

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
            get_connector_properties(root_helper, CONF.my_ip).\
            AndReturn(properties)
        self.volume.driver._attach_volume(self.context, vol, properties).\
            AndReturn(attach_info)
        os.getuid()
        utils.execute('chown', None, '/dev/null', run_as_root=True)
        f = fileutils.file_open('/dev/null').AndReturn(file('/dev/null'))
        backup_service.backup(backup, f)
        utils.execute('chown', 0, '/dev/null', run_as_root=True)
        self.volume.driver._detach_volume(attach_info)
        self.volume.driver.terminate_connection(vol, properties)
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
            get_connector_properties(root_helper, CONF.my_ip).\
            AndReturn(properties)
        self.volume.driver._attach_volume(self.context, vol, properties).\
            AndReturn(attach_info)
        os.getuid()
        utils.execute('chown', None, '/dev/null', run_as_root=True)
        f = fileutils.file_open('/dev/null', 'wb').AndReturn(file('/dev/null'))
        backup_service.restore(backup, vol['id'], f)
        utils.execute('chown', 0, '/dev/null', run_as_root=True)
        self.volume.driver._detach_volume(attach_info)
        self.volume.driver.terminate_connection(vol, properties)
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

        self.volume.driver.vg = FakeBrickLVM('cinder-volumes',
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
        self.volume.driver.delete_volume({'name': 'test1', 'size': 1024})

    def test_lvm_migrate_volume_no_loc_info(self):
        host = {'capabilities': {}}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertEqual(moved, False)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_bad_loc_info(self):
        capabilities = {'location_info': 'foo'}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertEqual(moved, False)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_diff_driver(self):
        capabilities = {'location_info': 'FooDriver:foo:bar:default:0'}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertEqual(moved, False)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_diff_host(self):
        capabilities = {'location_info': 'LVMVolumeDriver:foo:bar:default:0'}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertEqual(moved, False)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_in_use(self):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:bar' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'in-use'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertEqual(moved, False)
        self.assertIsNone(model_update)

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

        self.volume.driver.vg = FakeBrickLVM('cinder-volumes',
                                             False,
                                             None,
                                             'default')

        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertEqual(moved, False)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_proceed(self):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:'
                        'cinder-volumes-2:default:0' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}

        def fake_execute(*args, **kwargs):
            pass

        def get_all_volume_groups():
            # NOTE(flaper87) Return just the destination
            # host to test the check of dest VG existence.
            return [{'name': 'cinder-volumes-2'}]

        def _fake_get_all_physical_volumes(obj, root_helper, vg_name):
            return [{}]

        self.stubs.Set(brick_lvm.LVM,
                       'get_all_physical_volumes',
                       _fake_get_all_physical_volumes)

        self.stubs.Set(self.volume.driver, '_execute', fake_execute)

        self.stubs.Set(volutils, 'copy_volume',
                       lambda x, y, z, sync=False, execute='foo',
                       blocksize=mox.IgnoreArg(): None)

        self.stubs.Set(volutils, 'get_all_volume_groups',
                       get_all_volume_groups)

        self.stubs.Set(self.volume.driver, '_delete_volume',
                       lambda x: None)

        self.stubs.Set(self.volume.driver, '_create_export',
                       lambda x, y, vg='vg': None)

        self.volume.driver.vg = FakeBrickLVM('cinder-volumes',
                                             False,
                                             None,
                                             'default')
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertEqual(moved, True)
        self.assertIsNone(model_update)

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
        self.volume.driver.vg = FakeBrickLVM('cinder-volumes',
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

        ref = {'lv_name': 'fake_lv'}
        vol = {'name': 'test', 'id': 1, 'size': 0}

        def _rename_volume(old_name, new_name):
            self.assertEqual(old_name, ref['lv_name'])
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

        ref = {'lv_name': 'fake_lv_bad_size'}
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

        ref = {'lv_name': 'fake_nonexistent_lv'}
        vol = {'name': 'test', 'id': 1, 'size': 0, 'status': 'available'}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.volume.driver.manage_existing_get_size,
                          vol, ref)


class LVMVolumeDriverTestCase(DriverTestCase):
    """Test case for VolumeDriver"""
    driver_name = "cinder.volume.drivers.lvm.LVMVolumeDriver"
    FAKE_VOLUME = {'name': 'test1',
                   'id': 'test1'}

    def test_delete_volume_invalid_parameter(self):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.volume_clear = 'zero'
        configuration.volume_clear_size = 0
        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration)
        self.mox.StubOutWithMock(os.path, 'exists')

        os.path.exists(mox.IgnoreArg()).AndReturn(True)

        self.mox.ReplayAll()

        # Test volume without 'size' field and 'volume_size' field
        self.assertRaises(exception.InvalidParameterValue,
                          lvm_driver._delete_volume,
                          self.FAKE_VOLUME)

    def test_delete_volume_bad_path(self):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.volume_clear = 'zero'
        configuration.volume_clear_size = 0
        volume = dict(self.FAKE_VOLUME, size=1)
        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration)

        self.mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(mox.IgnoreArg()).AndReturn(False)
        self.mox.ReplayAll()

        self.assertRaises(exception.VolumeBackendAPIException,
                          lvm_driver._delete_volume, volume)

    def test_delete_volume_thinlvm_snap(self):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.volume_clear = 'zero'
        configuration.volume_clear_size = 0
        configuration.lvm_type = 'thin'
        lvm_driver = lvm.LVMISCSIDriver(configuration=configuration,
                                        vg_obj=mox.MockAnything())

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


class ISCSITestCase(DriverTestCase):
    """Test Case for ISCSIDriver"""
    driver_name = "cinder.volume.drivers.lvm.LVMISCSIDriver"
    base_driver = driver.ISCSIDriver

    def setUp(self):
        super(ISCSITestCase, self).setUp()
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.num_iscsi_scan_tries = 3
        self.configuration.iscsi_num_targets = 100
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
        self.configuration.append_config_values(mox.IgnoreArg())
        iscsi_driver = self.base_driver(configuration=self.configuration)
        iscsi_driver._execute = lambda *a, **kw: \
            ("%s dummy" % CONF.iscsi_ip_address, '')
        volume = {"name": "dummy",
                  "host": "0.0.0.0"}
        iscsi_driver._do_iscsi_discovery(volume)

    def test_get_iscsi_properties(self):
        volume = {"provider_location": '',
                  "id": "0",
                  "provider_auth": "a b c",
                  "attached_mode": "rw"}
        iscsi_driver = self.base_driver(configuration=self.configuration)
        iscsi_driver._do_iscsi_discovery = lambda v: "0.0.0.0:0000,0 iqn:iqn 0"
        result = iscsi_driver._get_iscsi_properties(volume)
        self.assertEqual(result["target_portal"], "0.0.0.0:0000")
        self.assertEqual(result["target_iqn"], "iqn:iqn")
        self.assertEqual(result["target_lun"], 0)

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
                       'get_all_volume_groups',
                       _fake_get_all_volume_groups)

        self.stubs.Set(brick_lvm.LVM,
                       'get_all_physical_volumes',
                       _fake_get_all_physical_volumes)

        self.volume.driver.vg = brick_lvm.LVM('cinder-volumes', 'sudo')

        self.volume.driver._update_volume_stats()

        stats = self.volume.driver._stats

        self.assertEqual(stats['total_capacity_gb'], float('5.52'))
        self.assertEqual(stats['free_capacity_gb'], float('0.52'))

    def test_validate_connector(self):
        iscsi_driver = self.base_driver(configuration=self.configuration)
        # Validate a valid connector
        connector = {'ip': '10.0.0.2',
                     'host': 'fakehost',
                     'initiator': 'iqn.2012-07.org.fake:01'}
        iscsi_driver.validate_connector(connector)

        # Validate a connector without the initiator
        connector = {'ip': '10.0.0.2', 'host': 'fakehost'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          iscsi_driver.validate_connector, connector)


class ISERTestCase(ISCSITestCase):
    """Test Case for ISERDriver."""
    driver_name = "cinder.volume.drivers.lvm.LVMISERDriver"
    base_driver = driver.ISERDriver

    def setUp(self):
        super(ISERTestCase, self).setUp()
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.num_iser_scan_tries = 3
        self.configuration.iser_num_targets = 100
        self.configuration.iser_target_prefix = 'iqn.2010-10.org.openstack:'
        self.configuration.iser_ip_address = '0.0.0.0'
        self.configuration.iser_port = 3260

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
        self.volume.driver.vg = brick_lvm.LVM('cinder-volumes', 'sudo')

        stats = self.volume.driver.get_volume_stats(refresh=True)

        self.assertEqual(stats['total_capacity_gb'], float('5.52'))
        self.assertEqual(stats['free_capacity_gb'], float('0.52'))
        self.assertEqual(stats['storage_protocol'], 'iSER')

    def test_get_volume_stats2(self):
        iser_driver = self.base_driver(configuration=self.configuration)

        stats = iser_driver.get_volume_stats(refresh=True)

        self.assertEqual(stats['total_capacity_gb'], 'infinite')
        self.assertEqual(stats['free_capacity_gb'], 'infinite')
        self.assertEqual(stats['storage_protocol'], 'iSER')


class FibreChannelTestCase(DriverTestCase):
    """Test Case for FibreChannelDriver."""
    driver_name = "cinder.volume.driver.FibreChannelDriver"

    def test_initialize_connection(self):
        self.driver = driver.FibreChannelDriver()
        self.driver.do_setup(None)
        self.assertRaises(NotImplementedError,
                          self.driver.initialize_connection, {}, {})


class VolumePolicyTestCase(test.TestCase):

    def setUp(self):
        super(VolumePolicyTestCase, self).setUp()

        cinder.policy.reset()
        cinder.policy.init()

        self.context = context.get_admin_context()
        self.stubs.Set(brick_lvm.LVM, '_vg_exists', lambda x: True)

    def tearDown(self):
        super(VolumePolicyTestCase, self).tearDown()
        cinder.policy.reset()

    def _set_rules(self, rules):
        cinder.common.policy.set_brain(cinder.common.policy.Brain(rules))

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
